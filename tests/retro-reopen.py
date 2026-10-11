#!/usr/bin/env python3
#
# Commits the retrospective leaves on a merged feature's branch send it back to
# step 3, and on through the review like the feature itself.
#
# Once a retrospective opened a pull request from a branch and worktree of its
# own; the automatic review left two findings on it, and nothing in sclaude knew
# the pull request existed. Now the fix is committed on the feature's branch,
# and `done` reopens step 3 for it. Guarded here, with gh faked:
#
#   * retro_changed_code counts the commits past the merged pull request's head
#     once the retrospective changed the code, and says nothing when it did not or
#     when there are none;
#   * retro_reopen rewinds to step 3 with the marks run_step and after_step
#     read, and clears the preview verdict;
#   * step 3 does not take the merged number for its pull request, and is told
#     it opens a second one;
#   * `done` checks right after the retrospective, before the clean-up;
#   * a finished retrospective is not run again until step 4 closes once more, so
#     the second pass through the cycle gets one of its own;
#   * the retrospective is told which branch the fix goes on;
#   * its report and its last message are printed in sclaude's terminal once
#     the person leaves it (session_end.py first / last).
#
# Run it with: python3 tests/retro-reopen.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def run_bash(script, cwd, bin_dir):
    body = "set -uo pipefail\n"
    body += 'BOLD=""; OFF=""; REPO=%s\n' % cwd
    for name in ("io", "ui", "steps", "state", "branches", "retro"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('info() { :; }; warn() { :; }\n'
             'issue_sync() { echo SYNC; }\n'
             'issue_hold_open() { echo "HOLD $1"; }\n')
    body += script
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"])
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, env=env, timeout=30)
    return out.stdout, out.stderr, out.returncode


tmp = tempfile.mkdtemp()
try:
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    wt = os.path.join(tmp, "wt")
    subprocess.run(["git", "init", "-q", "-b", "feat/demo", wt], check=True)
    subprocess.run(git + ["-C", wt, "commit", "-q", "--allow-empty", "-m", "a"], check=True)
    merged = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True,
                            text=True).stdout.strip()

    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    with open(os.path.join(bin_dir, "gh"), "w") as fh:
        # feat/demo has a merged pull request whose head is the first commit.
        fh.write('#!/usr/bin/env bash\n'
                 'for a; do [[ "${prev:-}" == --head ]] && b="$a"; prev="$a"; done\n'
                 '[[ "$b" == feat/demo ]] && echo %s\n' % merged)
    os.chmod(os.path.join(bin_dir, "gh"), 0o755)

    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    state = {"feature": "demo", "branch": "feat/demo", "issue": 145, "pr": 160,
             "step": "done",
             "steps": {"pr": {"done": True, "session": "old-pr"},
                       "review": {"done": True, "session": "old-review",
                                  "finished": "2026-10-09T10:00:00+01:00"}},
             "regression": {"preview": {"status": "passed"}}}
    path = os.path.join(wt, ".sclaude/local/feature", "state.json")
    with open(path, "w") as fh:
        json.dump(state, fh)

    # --- retro_changed_code ----------------------------------------------------
    out, _, _ = run_bash('retro_changed_code "%s" feat/demo' % wt, wt, bin_dir)
    check("nothing-past-the-merge", out.strip(), "")
    subprocess.run(git + ["-C", wt, "commit", "-q", "--allow-empty", "-m", "fix"], check=True)
    out, _, _ = run_bash('retro_changed_code "%s" feat/demo' % wt, wt, bin_dir)
    check("not-without-the-retrospective-changing-code", out.strip(), "")
    state["retro"] = {"project_from": merged, "project_to": "abc"}
    with open(path, "w") as fh:
        json.dump(state, fh)
    out, _, _ = run_bash('retro_changed_code "%s" feat/demo' % wt, wt, bin_dir)
    check("counts-the-fix", out.strip(), "1")
    out, _, _ = run_bash('retro_changed_code "%s" feat/none' % wt, wt, bin_dir)
    check("nothing-without-a-merged-pr", out.strip(), "")

    # --- retro_reopen ---------------------------------------------------------
    out, err, rc = run_bash('retro_reopen "%s" 160' % wt, wt, bin_dir)
    check("reopen-succeeds", rc, 0)
    with open(path) as fh:
        st = json.load(fh)
    check("back-on-step-3", st.get("step"), "pr")
    check("step-3-not-done", st["steps"]["pr"].get("done"), False)
    check("review-not-done", st["steps"]["review"].get("done"), False)
    check("marked-reopened", st.get("reopened"), "pr")
    check("step-3-opens-a-fresh-session", st["steps"]["pr"].get("session"), None)
    check("step-4-opens-a-fresh-session", st["steps"]["review"].get("session"), None)
    check("marked-by-retro", st.get("reopened_by"), "retro")
    check("merged-pr-remembered", st.get("reopened_pr"), 160)
    check("preview-verdict-cleared", st["regression"]["preview"].get("status"), None)
    check("issue-held-open", "HOLD 145" in out, True)
    check("issue-synced", "SYNC" in out, True)

    # --- step 3 is told ---------------------------------------------------------
    out, _, _ = run_bash('retro_pr_block "%s"' % wt, wt, bin_dir)
    check("block-names-the-merged-pr", "PR #160 carried it and is merged" in out, True)
    check("block-names-the-range", "`git log %s..HEAD`" % merged[:7] in out, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

with open(os.path.join(LIB, "run.sh")) as fh:
    run_src = fh.read()
check("step-3-refuses-the-merged-number",
      '"$number" == "$seen" ]] && number=""' in run_src, True)
check("step-3-gets-the-block", 'SCLAUDE_B_REOPENED="$(retro_pr_block' in run_src
      and 'local -x SCLAUDE_B_REOPENED=""' in run_src, True)
with open(os.path.join(ROOT, "sclaude", "prompts", "pr.md")) as fh:
    check("pr-prompt-has-the-block", "<block:reopened>" in fh.read(), True)

# --- `done` reopens before it cleans up -----------------------------------------
with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    src = fh.read()
m = re.search(r"^cmd_done\(\) \{\n.*?^\}\n", src, re.S | re.M)
body = m.group(0) if m else ""
retro_at = body.find("run_retro ")
new_at = body.find('retro_changed_code "$wt" "$branch"')
clean_at = body.find("Remove all of it?")
check("done-asks-after-the-retrospective", 0 <= retro_at < new_at < clean_at, True)
check("done-resumes-the-feature",
      'retro_reopen "$wt" "$pr"' in body and 'cmd_resume "$slug"' in body, True)

# --- the retrospective records that it changed the code ------------------------------
with open(os.path.join(LIB, "retro.sh")) as fh:
    retro_src = fh.read()
check("run-retro-records-the-change",
      'state_set "$fstate" retro.project_to "$project_after"' in retro_src, True)

# --- a retrospective per pass through the review -------------------------------------
guard = re.search(r"python3 - \"\$fstate\" <<'PY' 2>/dev/null; then\n(.*?)\nPY\n", retro_src, re.S)
check("guard-present", bool(guard), True)


def ran_already(review_finished, retro_started):
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "state.json")
        with open(path, "w") as fh:
            json.dump({"steps": {"review": {"finished": review_finished}},
                       "retro": {"runs": [{"started": retro_started, "done": True}]}}, fh)
        return subprocess.run(["python3", "-", path], input=guard.group(1),
                              text=True, capture_output=True).returncode == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if guard:
    check("skipped-after-a-no-to-the-clean-up",
          ran_already("2026-10-09T15:59:30+01:00", "2026-10-09T19:49:38+01:00"), True)
    check("run-again-after-the-second-review",
          ran_already("2026-10-12T11:00:00+01:00", "2026-10-09T19:49:38+01:00"), False)

# --- the report reaches sclaude's terminal ----------------------------------------
def entry(kind, text=None, human=False, tool=False):
    if kind == "assistant":
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    e = {"type": "user", "message": {"content": text or ""}}
    if human:
        e["origin"] = {"kind": "human"}
    return e


tmp = tempfile.mkdtemp()
try:
    transcript = os.path.join(tmp, "t.jsonl")
    with open(transcript, "w") as fh:
        for e in (entry("user", "the prompt", human=True),
                  entry("assistant", "Reading the state."),
                  entry("user", "tool result"),
                  entry("assistant", "## 1. What I may have missed"),
                  entry("user", "fix it", human=True),
                  entry("assistant", "Committed on the branch.")):
            fh.write(json.dumps(e) + "\n")
    end = os.path.join(LIB, "session_end.py")
    first = subprocess.run(["python3", end, "first", transcript], capture_output=True,
                           text=True).stdout.strip()
    last = subprocess.run(["python3", end, "last", transcript], capture_output=True,
                          text=True).stdout.strip()
    check("first-is-the-report", first, "## 1. What I may have missed")
    check("last-is-the-conversation-end", last, "Committed on the branch.")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
check("report-printed-when-left-open", '|| retro_report "$wt" "$session"' in retro_src, True)

# --- the prompt names the branch -------------------------------------------------
with open(os.path.join(ROOT, "sclaude", "prompts", "retro.md")) as fh:
    prompt = fh.read()
check("prompt-names-the-branch", "own branch, `<branch>`" in prompt, True)
with open(os.path.join(LIB, "retro.sh")) as fh:
    check("branch-passed-to-prompt", 'SCLAUDE_V_BRANCH=' in fh.read(), True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
