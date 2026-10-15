#!/usr/bin/env python3
#
# Where a project's review runs: `review` in .sclaude/config.json, and the
# review run on this machine when it says `local`.
#
# The review workflow in Actions bills its runner by the minute while it waits
# on the model, so a project may run the same /code-review here (`local`) or
# not at all (`off`). Guarded here:
#
#   * project_review_mode reads the key, and anything it does not know is
#     `github` — a typo must not switch off the review a project has;
#   * review_label_sync puts the `no-review` label on only when the review is
#     not GitHub's; the label is what makes the workflow skip itself;
#   * local_review keeps its findings where the workflow does, as threads on
#     the pull request: the first run reads the whole pull request and posts
#     its findings; a run on the same head runs nothing and reads the count
#     from GitHub; a later run reads only the new commits, is handed every
#     thread still open, resolves the ones it judges fixed with the
#     resolver's reply, and is told what the author declined. A thread left
#     open by an interrupted session stays open — nothing counts as fixed for
#     not being raised again. An answer with no count, or a head not pushed,
#     records nothing;
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
sys.path.insert(0, LIB)
import pr_context  # noqa: E402

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


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


# gh, standing in for GitHub: the pull request's review threads in a JSON
# file, the calls local_review.py makes, and a log of every call.
GH = r'''#!/usr/bin/env python3
import json, os, sys
world = os.environ["GH_WORLD"]
args = sys.argv[1:]
with open(world + ".log", "a") as fh:
    fh.write(" ".join(args) + "\n")
try:
    with open(world) as fh:
        data = json.load(fh)
except OSError:
    data = {"threads": [], "next": 1}
def save():
    with open(world, "w") as fh:
        json.dump(data, fh)
def field(name):
    for i, a in enumerate(args):
        if a in ("-f", "-F") and args[i + 1].startswith(name + "="):
            return args[i + 1][len(name) + 1:]
    return None
if args[:2] == ["api", "graphql"]:
    query = field("query") or ""
    if "addPullRequestReviewThreadReply" in query:
        for t in data["threads"]:
            if t["id"] == field("id"):
                t["comments"].append({"body": field("b"), "url": t["comments"][0]["url"] + "x"})
        save(); print("{}"); sys.exit(0)
    if "resolveReviewThread" in query:
        for t in data["threads"]:
            if t["id"] == field("id"):
                t["isResolved"] = True
        save(); print("{}"); sys.exit(0)
    nodes = [{"id": t["id"], "isResolved": t["isResolved"], "isOutdated": False,
              "path": t["path"], "line": t["line"], "originalLine": t["line"],
              "comments": {"nodes": t["comments"]}} for t in data["threads"]]
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}}))
    sys.exit(0)
if args[:1] == ["api"] and args[1].endswith("/comments") and field("body"):
    path = field("path")
    if path == "nowhere" or (path == "fileonly" and field("line")):
        sys.exit(1)
    n = data["next"]; data["next"] += 1
    data["threads"].append({"id": "T%d" % n, "isResolved": False, "path": path,
                            "line": int(field("line")) if field("line") else None,
                            "comments": [{"body": field("body"),
                                          "url": "https://github.com/o/r/pull/7#discussion_r%d" % (100 + n)}]})
    save(); print("{}"); sys.exit(0)
sys.exit(0)
'''

tmp = tempfile.mkdtemp()
try:
    stubs = os.path.join(tmp, "bin")
    world = os.path.join(tmp, "world.json")
    calls = os.path.join(tmp, "claude.calls")
    write(os.path.join(stubs, "gh"), GH, 0o755)
    # claude: records its prompt, answers with whatever the answer file holds.
    write(os.path.join(stubs, "claude"),
          '#!/bin/sh\nprintf "%%s\\n---\\n" "$2" >> "%s"\ncat "%s/answer"\n' % (calls, tmp), 0o755)

    remote = os.path.join(tmp, "o", "r.git")
    os.makedirs(remote)
    git("init", "-q", "--bare", "-b", "main", cwd=remote)
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    git("remote", "add", "origin", remote, cwd=repo)
    write(os.path.join(repo, "a.txt"), "a\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "first", cwd=repo)
    git("push", "-q", "-u", "origin", "main", cwd=repo)
    base = git("rev-parse", "HEAD", cwd=repo)
    git("checkout", "-q", "-b", "feature", cwd=repo)
    write(os.path.join(repo, "a.txt"), "b\n")
    git("commit", "-qam", "change", cwd=repo)
    git("push", "-q", "-u", "origin", "feature", cwd=repo)
    head = git("rev-parse", "HEAD", cwd=repo)
    os.makedirs(os.path.join(repo, ".sclaude", "local", "feature"))
    config = os.path.join(repo, ".sclaude", "config.json")
    journal = os.path.join(repo, ".sclaude", "local", "feature", "local-review-rounds.jsonl")

    def run_bash(script):
        body = "set -uo pipefail\n"
        body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""; SELF=sclaude\n'
        for name in ("io", "ui", "state", "project", "picker", "local_review"):
            body += 'source "%s/%s.sh"\n' % (LIB, name)
        body += 'LIB="%s"\nwarn() { echo "$*" >&2; }\ninfo() { echo "$*"; }\n' % LIB
        body += script
        env = dict(os.environ, PATH=stubs + os.pathsep + os.environ["PATH"], GH_WORLD=world)
        out = subprocess.run(["bash", "-c", body], cwd=repo, capture_output=True,
                             text=True, timeout=60, env=env)
        return out.stdout, out.stderr, out.returncode

    def mode(value):
        write(config, json.dumps({} if value is None else {"review": value}))
        out, _, _ = run_bash('REPO=%s; project_review_mode' % repo)
        return out.strip()

    def gh_log():
        try:
            with open(world + ".log") as fh:
                return fh.read()
        except OSError:
            return ""
        finally:
            open(world + ".log", "w").close()

    # --- the mode -------------------------------------------------------------
    check("mode-absent", mode(None), "github")
    check("mode-local", mode("local"), "local")
    check("mode-off", mode("off"), "off")
    check("mode-github", mode("github"), "github")
    check("mode-typo-is-github", mode("locla"), "github")

    # --- the label ------------------------------------------------------------
    mode("github")
    run_bash('REPO=%s; review_label_sync %s 7' % (repo, repo))
    check("github-no-label", gh_log(), "")
    mode("off")
    run_bash('REPO=%s; review_label_sync %s 7' % (repo, repo))
    check_true("off-labels", "pr edit 7 --add-label no-review" in gh_log())
    run_bash('REPO=%s; review_label_sync %s null' % (repo, repo))
    check("no-pr-no-label", gh_log(), "")

    # --- the review -----------------------------------------------------------
    mode("local")

    def review(answer):
        write(os.path.join(tmp, "answer"), answer)
        return run_bash('REPO=%s; local_review %s 7' % (repo, repo))

    def prompts():
        try:
            with open(calls) as fh:
                return fh.read()
        except OSError:
            return ""
        finally:
            open(calls, "w").close()

    def threads():
        with open(world) as fh:
            return json.load(fh)["threads"]

    out, err, rc = review("### a.txt:1 — b is wrong\nWith a, b comes out.\n\n"
                          "### a.txt:1 — another\nAnd so on.\n\nFINDINGS: 2\n")
    check("first-count", (out.strip(), rc), ("2", 0))
    first = prompts()
    check_true("first-reads-whole-pr", "the whole pull request" in first
               and "git diff %s..%s" % (base, head) in first)
    check("first-posted", [t["comments"][0]["body"].splitlines()[0] for t in threads()],
          ["**b is wrong**", "**another**"])
    check_true("signed", all(pr_context.LOCAL_SIGNATURE in t["comments"][0]["body"]
                             for t in threads()))

    # The same head again: the count from GitHub, and no second run.
    out, _, rc = review("FINDINGS: 5\n")
    check("same-head-cached", (out.strip(), rc), ("2", 0))
    check("same-head-no-run", prompts(), "")

    # A session fixed one, declined the other on GitHub, and pushed: the next
    # run reads the new commit, is handed the open thread and told the
    # declined one, and resolves what it judges fixed.
    t = threads()
    with open(world) as fh:
        data = json.load(fh)
    data["threads"][1]["comments"].append({"body": "Left as it is, at the author's decision: keep it",
                                           "url": "u"})
    data["threads"][1]["isResolved"] = True
    with open(world, "w") as fh:
        json.dump(data, fh)
    write(os.path.join(repo, "a.txt"), "c\n")
    git("commit", "-qam", "fix", cwd=repo)
    git("push", "-q", cwd=repo)
    newer = git("rev-parse", "HEAD", cwd=repo)
    out, _, rc = review("RESOLVED: r101 — b now checked\n\nFINDINGS: 0\n")
    check("delta-count", (out.strip(), rc), ("0", 0))
    second = prompts()
    check_true("delta-reads-new-commits", "since the last review" in second
               and "git diff %s..%s" % (head, newer) in second)
    check_true("delta-handed-open", "r101 · a.txt:1 — **b is wrong**" in second)
    check_true("delta-told-declined", "keep it" in second)
    t = threads()
    check("resolved-thread", t[0]["isResolved"], True)
    check_true("resolver-reply", t[0]["comments"][-1]["body"].startswith(pr_context.RESOLVER_PREFIX)
               and pr_context.LOCAL_SIGNATURE in t[0]["comments"][-1]["body"])

    # An interrupted session: a commit that fixes nothing. The open thread
    # stays open, and so does the count.
    with open(world) as fh:
        data = json.load(fh)
    data["threads"][0]["isResolved"] = False
    with open(world, "w") as fh:
        json.dump(data, fh)
    write(os.path.join(repo, "a.txt"), "d\n")
    git("commit", "-qam", "half", cwd=repo)
    git("push", "-q", cwd=repo)
    out, _, rc = review("FINDINGS: 0\n")
    check("unfixed-stays-open", (out.strip(), rc), ("1", 0))
    prompts()

    # A finding GitHub will not take on its line goes on its file.
    write(os.path.join(repo, "a.txt"), "e\n")
    git("commit", "-qam", "more", cwd=repo)
    git("push", "-q", cwd=repo)
    out, _, rc = review("### fileonly:9 — on the file\nx\n\nFINDINGS: 1\n")
    check("file-level-count", (out.strip(), rc), ("2", 0))
    check("file-level-thread", threads()[-1]["path"], "fileonly")
    prompts()

    # No count in the answer, or nothing GitHub would take: nothing recorded,
    # so the next run reviews the same head again.
    write(os.path.join(repo, "a.txt"), "f\n")
    git("commit", "-qam", "again", cwd=repo)
    git("push", "-q", cwd=repo)
    with open(journal) as fh:
        before = fh.read()
    _, _, rc = review("I could not finish.\n")
    check("no-count-fails", rc, 1)
    _, _, rc = review("### nowhere:1 — lost\nx\n\nFINDINGS: 1\n")
    check("nothing-posted-fails", rc, 1)
    with open(journal) as fh:
        check("failures-not-recorded", fh.read(), before)
    prompts()

    # A head GitHub does not have yet: no run.
    write(os.path.join(repo, "a.txt"), "g\n")
    git("commit", "-qam", "local only", cwd=repo)
    _, err, rc = review("FINDINGS: 0\n")
    check("unpushed-fails", rc, 1)
    check("unpushed-no-run", prompts(), "")

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
               and "Nothing in this project's flow runs on GitHub Actions" in text)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
