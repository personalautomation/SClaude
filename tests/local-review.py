#!/usr/bin/env python3
#
# Where a project's review runs: `review` in .sclaude/config.json.
#
# The review workflow in Actions bills its runner by the minute while it waits
# on the model, so a project may run the same /code-review on this machine
# (`local`) or not at all (`off`). Guarded here:
#
#   * project_review_mode reads the key, and anything it does not know is
#     `github` — a typo must not switch off the review a project has.
#   * review_label_sync puts the `no-review` label on only when the review is
#     not GitHub's; the label is what makes the workflow skip itself.
#   * local_review reads the whole pull request first and only the new commits
#     after, does not run twice on one head, tells the model what was reported
#     and declined before, and refuses an answer with no `FINDINGS: <n>`.
#   * the step prompts render with the review's mode and without it.
#
# Run it with: python3 tests/local-review.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
PROMPTS = os.path.join(ROOT, "sclaude", "prompts")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, check=False).stdout.strip()


def run_bash(script, cwd, path):
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""; SELF=sclaude\n'
    for name in ("io", "ui", "state", "project", "local_review"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('warn() { echo "$*" >&2; }\n'
             'info() { echo "$*"; }\n')
    body += script
    env = dict(os.environ, PATH=path + os.pathsep + os.environ["PATH"])
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, timeout=60, env=env)
    return out.stdout, out.stderr, out.returncode


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


tmp = tempfile.mkdtemp()
try:
    stubs = os.path.join(tmp, "bin")
    calls = os.path.join(tmp, "calls")
    # claude: records its prompt, answers with whatever ANSWER holds.
    write(os.path.join(stubs, "claude"),
          '#!/bin/sh\nprintf "%%s\\n---\\n" "$2" >> "%s/claude"\ncat "%s/answer"\n'
          % (calls, tmp), 0o755)
    # gh: records its arguments; a pull request with no labels.
    write(os.path.join(stubs, "gh"),
          '#!/bin/sh\necho "$*" >> "%s/gh"\n' % calls, 0o755)
    os.makedirs(calls)

    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    write(os.path.join(repo, "a.txt"), "a\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "first", cwd=repo)
    git("update-ref", "refs/remotes/origin/main", "HEAD", cwd=repo)
    base = git("rev-parse", "HEAD", cwd=repo)
    write(os.path.join(repo, "a.txt"), "b\n")
    git("commit", "-qam", "change", cwd=repo)
    head = git("rev-parse", "HEAD", cwd=repo)
    os.makedirs(os.path.join(repo, ".sclaude", "local", "feature"))
    config = os.path.join(repo, ".sclaude", "config.json")

    def mode(value):
        write(config, json.dumps({} if value is None else {"review": value}))
        out, _, _ = run_bash('REPO=%s; project_review_mode' % repo, repo, stubs)
        return out.strip()

    # --- the mode -------------------------------------------------------------
    check("mode-absent", mode(None), "github")
    check("mode-local", mode("local"), "local")
    check("mode-off", mode("off"), "off")
    check("mode-github", mode("github"), "github")
    check("mode-typo-is-github", mode("locla"), "github")

    def gh_calls():
        try:
            with open(os.path.join(calls, "gh")) as fh:
                return fh.read()
        except OSError:
            return ""
        finally:
            open(os.path.join(calls, "gh"), "w").close()

    # --- the label ------------------------------------------------------------
    mode("github")
    run_bash('REPO=%s; review_label_sync %s 7' % (repo, repo), repo, stubs)
    check("github-no-label", gh_calls(), "")
    mode("off")
    run_bash('REPO=%s; review_label_sync %s 7' % (repo, repo), repo, stubs)
    check_true("off-labels", "pr edit 7 --add-label no-review" in gh_calls())
    run_bash('REPO=%s; review_label_sync %s null' % (repo, repo), repo, stubs)
    check("no-pr-no-label", gh_calls(), "")

    # --- the review -----------------------------------------------------------
    mode("local")
    feature = os.path.join(repo, ".sclaude", "local", "feature")

    def review(answer):
        write(os.path.join(tmp, "answer"), answer)
        return run_bash('REPO=%s; local_review %s 7' % (repo, repo), repo, stubs)

    def prompts():
        try:
            with open(os.path.join(calls, "claude")) as fh:
                return fh.read()
        except OSError:
            return ""
        finally:
            open(os.path.join(calls, "claude"), "w").close()

    finding = "### a.txt:1 — b is wrong\nWith a, b comes out.\n\nFINDINGS: 1\n"
    out, err, rc = review(finding)
    check("first-count", (out.strip(), rc), ("1", 0))
    first = prompts()
    check_true("first-reads-whole-pr", "the whole pull request" in first
               and "git diff %s..%s" % (base, head) in first)
    check_true("first-not-told-seen", "local-review-seen.md" not in first)
    with open(os.path.join(feature, "local-review.md")) as fh:
        text = fh.read()
    check_true("findings-kept", "a.txt:1 — b is wrong" in text and "FINDINGS:" not in text)
    with open(os.path.join(feature, "local-review-head")) as fh:
        check("head-recorded", fh.read().strip(), "%s 1" % head)

    # The same head again: the answer on record, and no second run.
    out, _, rc = review("FINDINGS: 5\n")
    check("same-head-cached", (out.strip(), rc), ("1", 0))
    check("same-head-no-run", prompts(), "")

    # A new commit: only it is read, and the model hears what came before.
    write(os.path.join(feature, "local-review-declined"), "a.txt:1\tleave it\n")
    write(os.path.join(repo, "a.txt"), "c\n")
    git("commit", "-qam", "fix", cwd=repo)
    newer = git("rev-parse", "HEAD", cwd=repo)
    out, _, rc = review("Nothing found.\n\nFINDINGS: 0\n")
    check("delta-count", (out.strip(), rc), ("0", 0))
    second = prompts()
    check_true("delta-reads-new-commits", "since the last review" in second
               and "git diff %s..%s" % (head, newer) in second)
    check_true("delta-told-seen", ".sclaude/local/feature/local-review-seen.md" in second)
    check_true("delta-told-declined", ".sclaude/local/feature/local-review-declined" in second)

    # No count in the answer: nothing recorded, and the caller hears it failed.
    write(os.path.join(repo, "a.txt"), "d\n")
    git("commit", "-qam", "more", cwd=repo)
    out, _, rc = review("I could not finish.\n")
    check("no-count-fails", rc, 1)
    with open(os.path.join(feature, "local-review-head")) as fh:
        check("no-count-not-recorded", fh.read().split()[0], newer)

    # What the session is told names the file and carries the findings.
    out, _, _ = run_bash('local_review_told %s' % repo, repo, stubs)
    check_true("told", "review: local" in out and "local-review.md" in out)

    # --- the prompts ------------------------------------------------------------
    def render(step, **values):
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("SCLAUDE_V_", "SCLAUDE_B_")):
                del env[key]
        env.update({"SCLAUDE_V_FEATURE": "f", "SCLAUDE_V_PR": "7", "SCLAUDE_V_ISSUE": "",
                    "SCLAUDE_V_MANUALS": "m", "SCLAUDE_V_DEV_URL": "u",
                    "SCLAUDE_V_DEV_PORT": "1", "SCLAUDE_V_DEFERRED": "d",
                    "SCLAUDE_V_DB_API": "", "SCLAUDE_V_SHARED_DB": "",
                    "SCLAUDE_V_NO_REVIEW": "", "SCLAUDE_V_REVIEW_LOCAL": "",
                    "SCLAUDE_V_REVIEW_MODE": "github"})
        env.update(values)
        out = subprocess.run([sys.executable, os.path.join(LIB, "render_prompt.py"),
                              os.path.join(PROMPTS, step + ".md"), PROMPTS],
                             capture_output=True, text=True, env=env)
        return out.returncode, out.stdout + out.stderr

    rc, text = render("pr")
    check("pr-github-renders", rc, 0)
    check_true("pr-github-no-label", "/pr no-review" not in text)
    rc, text = render("pr", SCLAUDE_V_NO_REVIEW="1", SCLAUDE_V_REVIEW_MODE="local")
    check("pr-local-renders", rc, 0)
    check_true("pr-local-label", "/pr no-review" in text and "`local`" in text)
    rc, text = render("review")
    check("review-github-renders", rc, 0)
    check_true("review-github-no-local", "reviews on this machine" not in text)
    rc, text = render("review", SCLAUDE_V_REVIEW_LOCAL="1", SCLAUDE_V_REVIEW_MODE="local")
    check("review-local-renders", rc, 0)
    check_true("review-local-told", "reviews on this machine" in text
               and "local-review-declined" in text)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
