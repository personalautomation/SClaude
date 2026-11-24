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
    for name in ("core/io", "core/ui", "core/steps", "core/state", "tree/branches", "tree/sync", "improve/retro"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('info() { :; }; warn() { :; }\n'
             'issue_sync() { echo SYNC; }\n'
             'issue_hold_open() { echo "HOLD $1"; }\n'
             'watch_stop() { echo "UNWATCH $1"; }\n'
             'issue_move_status() { echo "MOVE $1|$2|$3"; }\n'
             'QA_DONE=Done; PROGRESS_TO="In progress"\n')
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
    out, err, rc = run_bash('retro_reopen "%s" 160 demo' % wt, wt, bin_dir)
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
    # The board moves the reopened issue on its own; the watch on the merged
    # pull request would have read that as QA handing the feature back.
    check("qa-watch-stopped", "UNWATCH demo" in out, True)
    check("issue-synced", "SYNC" in out, True)
    # Back at work: the board's Done goes back to In progress.
    check("board-back-in-progress", "MOVE 145|Done|In progress" in out, True)
    # The other way back to step 3 — a feature with no change of its own the
    # retrospective gave one — moves the board the same way.
    with open(os.path.join(LIB, "commands", "done.sh")) as fh:
        check("board-back-on-the-no-change-way-too", fh.read().count('retro_board_back "$issue"'), 1)

    # --- step 3 is told ---------------------------------------------------------
    out, _, _ = run_bash('retro_pr_block "%s"' % wt, wt, bin_dir)
    check("block-names-the-merged-pr", "PR #160 carried it and is merged" in out, True)
    check("block-names-the-range", "`git log %s..HEAD`" % merged[:7] in out, True)

    # --- after a squash merge the branch moves onto main --------------------
    # main holds the pull request as one squashed commit; the branch holds
    # its own history up to the merged head and two commits past it. Merging
    # main in would meet the squash in conflicts: the branch is moved onto
    # main with the two alone.
    def g(cwd, *args):
        return subprocess.run(git + ["-C", cwd] + list(args), capture_output=True, text=True,
                              check=True).stdout.strip()
    origin = os.path.join(tmp, "squash.git")
    sq = os.path.join(tmp, "squash")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, sq], check=True, capture_output=True)
    with open(os.path.join(sq, "app.txt"), "w") as fh:
        fh.write("base\n")
    g(sq, "add", "-A"); g(sq, "commit", "-q", "-m", "base"); g(sq, "push", "-q", "origin", "HEAD:main")
    g(sq, "switch", "-q", "-c", "feat/demo")
    for line in ("one", "two"):
        with open(os.path.join(sq, "app.txt"), "a") as fh:
            fh.write(line + "\n")
        g(sq, "commit", "-qam", line)
    pr_head = g(sq, "rev-parse", "HEAD")
    # The squash on main: the same content, another commit.
    g(sq, "switch", "-q", "main")
    g(sq, "merge", "-q", "--squash", "feat/demo"); g(sq, "commit", "-q", "-m", "squashed (#160)")
    g(sq, "push", "-q", "origin", "main")
    g(sq, "switch", "-q", "feat/demo")
    for name in ("fix1.txt", "fix2.txt"):
        with open(os.path.join(sq, name), "w") as fh:
            fh.write("x\n")
        g(sq, "add", name); g(sq, "commit", "-q", "-m", "retro " + name)
    sq_bin = os.path.join(tmp, "squash-bin")
    os.makedirs(sq_bin)
    with open(os.path.join(sq_bin, "gh"), "w") as fh:
        fh.write('#!/usr/bin/env bash\nfor a; do [[ "${prev:-}" == --head ]] && b="$a"; prev="$a"; done\n'
                 '[[ "$b" == feat/demo ]] && echo %s\n' % pr_head)
    os.chmod(os.path.join(sq_bin, "gh"), 0o755)
    sq_state = os.path.join(sq, ".sclaude/local/feature/state.json")
    os.makedirs(os.path.dirname(sq_state), exist_ok=True)

    def sq_reopened(**extra):
        # As retro_reopen leaves it: the merged pull request, no move yet.
        with open(sq_state, "w") as fh:
            json.dump(dict({"branch": "feat/demo", "reopened_by": "retro", "reopened_pr": 160}, **extra), fh)
    sq_reopened()
    out, err, rc = run_bash('info() { echo "INFO $*"; }; retro_move_past "%s"' % sq, sq, sq_bin)
    check("squash: the move is written down for step 3",
          bool(json.load(open(sq_state)).get("retro", {}).get("moved")), True)
    check("squash: the branch is main and the two commits past the merged head",
          (g(sq, "rev-parse", "HEAD~2"), g(sq, "log", "--format=%s", "-2").split("\n"),
           "now stand on origin/main" in out),
          (g(sq, "rev-parse", "origin/main"), ["retro fix2.txt", "retro fix1.txt"], True))
    # Step 3 is told the commits by where they now stand.
    out, _, _ = run_bash('retro_pr_block "%s"' % sq, sq, sq_bin)
    check("squash: step 3 is told the moved commits as origin/main..HEAD",
          ("`git log origin/main..HEAD`" in out, "rebase them onto" in out), (True, False))

    # Rebased by step 3 itself (no record), then step 3 started again: the
    # branch is plainly on main, and is told so.
    sq_reopened()
    out, _, _ = run_bash('retro_pr_block "%s"' % sq, sq, sq_bin)
    check("squash: a branch plainly on main with no record is told it is moved",
          "`git log origin/main..HEAD`" in out, True)

    def back_on_head(name):
        # The branch at the merged head again, with one fresh commit past it,
        # sent back anew: no move written down.
        sq_reopened()
        g(sq, "reset", "-q", "--hard", pr_head)
        with open(os.path.join(sq, name), "w") as fh:
            fh.write("x\n")
        g(sq, "add", name); g(sq, "commit", "-q", "-m", "retro " + name)
        return g(sq, "rev-parse", "HEAD")

    def on_origin():
        return subprocess.run(["git", "-C", sq, "ls-remote", "--heads", "origin", "feat/demo"],
                              capture_output=True, text=True).stdout.strip()

    # On origin at the merged head: it holds nothing main lacks, and goes,
    # so step 3 pushes the moved branch with no force.
    back_on_head("fix3.txt")
    g(sq, "push", "-q", "origin", "%s:refs/heads/feat/demo" % pr_head)
    run_bash('retro_move_past "%s"' % sq, sq, sq_bin)
    check("squash: a branch on origin at the merged head goes, and the branch moves",
          (on_origin(), g(sq, "rev-parse", "HEAD~1")), ("", g(sq, "rev-parse", "origin/main")))
    # On origin past the merged head: somebody's work there — left as it is.
    before = back_on_head("fix4.txt")
    g(sq, "push", "-q", "-f", "origin", "HEAD:refs/heads/feat/demo")
    run_bash('retro_move_past "%s"' % sq, sq, sq_bin)
    check("squash: a branch on origin past the merged head is left as it is",
          (g(sq, "rev-parse", "HEAD"), bool(on_origin())), (before, True))
    g(sq, "push", "-q", "origin", ":refs/heads/feat/demo")
    # Origin not answering is no "absent": left as it is.
    url = g(sq, "remote", "get-url", "origin")
    g(sq, "remote", "set-url", "origin", os.path.join(tmp, "nowhere.git"))
    run_bash('retro_move_past "%s"' % sq, sq, sq_bin)
    g(sq, "remote", "set-url", "origin", url)
    check("squash: no answer from origin leaves the branch as it is", g(sq, "rev-parse", "HEAD"), before)
    # Main merged in after the merged head: the sync resolves it, not a replay.
    sq_reopened()
    g(sq, "merge", "-q", "--no-edit", "origin/main")
    before = g(sq, "rev-parse", "HEAD")
    run_bash('retro_move_past "%s"' % sq, sq, sq_bin)
    check("squash: main merged in after the merged head leaves the branch as it is",
          g(sq, "rev-parse", "HEAD"), before)
    out, _, _ = run_bash('retro_pr_block "%s"' % sq, sq, sq_bin)
    check("squash: with main merged in, step 3 is not asked to rebase",
          ("do not rebase it" in out, "rebase them onto" in out, "--first-parent --no-merges" in out),
          (True, False, True))
    # gh not answering: the branch was not moved, and step 3 keeps the rebase.
    mute = os.path.join(tmp, "mute-bin")
    os.makedirs(mute, exist_ok=True)
    with open(os.path.join(mute, "gh"), "w") as fh:
        fh.write("#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(mute, "gh"), 0o755)
    sq_reopened()
    out, _, _ = run_bash('retro_pr_block "%s"' % sq, sq, mute)
    check("squash: an unknown merged head is not taken for a moved branch",
          ("<head of #160>" in out, "rebase them onto" in out, "already moved" in out), (True, True, False))
    # Another branch ending in the same name, at the merged head, approves
    # nothing: origin is asked for refs/heads/<branch> exactly.
    before = back_on_head("fix5.txt")
    g(sq, "push", "-q", "origin", "%s:refs/heads/bot/feat/demo" % pr_head)
    g(sq, "push", "-q", "-f", "origin", "HEAD:refs/heads/feat/demo")
    run_bash('retro_move_past "%s"' % sq, sq, sq_bin)
    check("squash: a branch named alike elsewhere does not get this one deleted",
          (g(sq, "rev-parse", "HEAD"), bool(on_origin())), (before, True))
    g(sq, "push", "-q", "origin", ":refs/heads/feat/demo", ":refs/heads/bot/feat/demo")
    # A move that stops on a conflict is taken back: the sync before step 3
    # resolves it, as before.
    g(sq, "push", "-q", "origin", ":refs/heads/feat/demo")
    g(sq, "switch", "-q", "main")
    with open(os.path.join(sq, "fix1.txt"), "w") as fh:
        fh.write("main\n")
    g(sq, "add", "fix1.txt"); g(sq, "commit", "-q", "-m", "main touches fix1"); g(sq, "push", "-q", "origin", "main")
    g(sq, "switch", "-q", "feat/demo")
    # Back on the merged head, with one commit past it that main's change meets.
    g(sq, "reset", "-q", "--hard", pr_head)
    with open(os.path.join(sq, "fix1.txt"), "w") as fh:
        fh.write("branch\n")
    g(sq, "add", "fix1.txt"); g(sq, "commit", "-q", "-m", "retro fix1 again")
    before = g(sq, "rev-parse", "HEAD")
    out, _, _ = run_bash('info() { echo "INFO $*"; }; retro_move_past "%s"' % sq, sq, sq_bin)
    check("squash: a conflict leaves the branch as it was, and says main is merged in",
          (g(sq, "rev-parse", "HEAD"), g(sq, "status", "--porcelain", "--untracked-files=no"),
           "do not move onto origin/main cleanly" in out),
          (before, "", True))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

run_src = "".join(open(os.path.join(LIB, m), encoding="utf-8").read()
          for m in ("cycle/run.sh", "cycle/session_watch.sh", "cycle/prompt.sh"))
check("step-3-refuses-the-merged-number",
      '"$number" == "$seen" ]] && number=""' in run_src, True)
check("step-3-gets-the-block", 'SCLAUDE_B_REOPENED="$(retro_pr_block' in run_src
      and 'local -x SCLAUDE_B_REOPENED=""' in run_src, True)
with open(os.path.join(ROOT, "sclaude", "prompts", "pr.md")) as fh:
    check("pr-prompt-has-the-block", "<block:reopened>" in fh.read(), True)

# --- `done` reopens before it cleans up -----------------------------------------
src = "".join(open(os.path.join(ROOT, _p)).read()
    for _p in ("bin/sclaude", "sclaude/lib/commands/start.sh", "sclaude/lib/commands/menu.sh", "sclaude/lib/commands/step_commands.sh", "sclaude/lib/commands/done.sh", "sclaude/lib/commands/feature_commands.sh"))
m = re.search(r"^cmd_done\(\) \{\n.*?^\}\n", src, re.S | re.M)
body = m.group(0) if m else ""
retro_at = body.find("run_retro ")
new_at = body.find('retro_changed_code "$wt" "$branch"')
clean_at = body.find("Remove all of it?")
check("done-asks-after-the-retrospective", 0 <= retro_at < new_at < clean_at, True)
check("done-resumes-the-feature",
      'retro_reopen "$wt" "$pr" "$slug"' in body and 'cmd_resume "$slug"' in body, True)
check("no-change-reopen-stops-the-watch", 'watch_stop "$slug"\n    issue_hold_open "$issue"' in body, True)
# sclaude's code changed under the clean-up: it goes on in a fresh process by
# itself, not by a command the person has to type (and may type wrong): after
# the workshop published before the retrospective, and after the
# retrospective's own (the retry that came third is gone: a stopped change
# is the person's question now, and the clean-up waits for its answer).
check("done-goes-on-fresh", body.count('done_fresh "$slug"'), 2)
# After the retrospective the fresh run does not ask about it again; before
# it, it holds it.
check("fresh-run-after-the-retro", body.count('done_fresh "$slug" "$retro_flag"'), 1)
check("clean-up-waits-for-the-workshop", 'if [[ "$(workshop_state "$wt")" != none ]]; then' in body, True)
check("fresh-run-keeps-the-word", 'done_fresh "$slug" "${retro_ran_here:+retro}"' in body, True)
check("fresh-run-skips-it-once", 'if [[ -z "$retro_ran_here" ]]; then\n    run_retro' in body
      and "unset SCLAUDE_DONE_RETRO_RAN" in body, True)
check("done-does-not-stop-for-the-code", "goes on in a fresh one: $SELF done" in body, False)
m = re.search(r"^done_fresh\(\) \{\n.*?^\}\n", src, re.S | re.M)
check("fresh-run-is-a-new-process", m is not None
      and 'SCLAUDE_SYNCED=1 SCLAUDE_DONE_RETRO_RAN="${2:-}" "$INSTRUMENTS/bin/sclaude" _done "$1"' in m.group(0), True)
# Its "no" to the clean-up reaches the caller: `_done` keeps the exit code.
check("fresh-run-keeps-the-code", '_done)         shift; cmd_done "${1:-}" ;;' in src, True)
# Opened again after remind_prod got to the clean-up for this pull request and
# this production, a done feature goes to the clean-up, not through production
# and the epilogue; a pass that stopped short of it leaves no mark.
m = re.search(r"^cmd_resume\(\) \{\n.*?^\}\n", src, re.S | re.M)
resume = m.group(0) if m else ""
left_at = resume.find('[[ "$ended" == "$(prod_pass_mark "$wt")" ]]')
done_at = resume.find('if [[ -n "$cleanup_left" ]]; then\n      cmd_done "$slug"')
check("resume-done-goes-to-the-clean-up", 0 < left_at < done_at
      and '"$ended" == "$(prod_pass_mark "$wt" nodeploy)"' in resume, True)
# A production gone red since is not taken to the clean-up: remind_prod holds it.
check("resume-done-not-over-a-red-production",
      re.search(r'\[\[ "\$ended" == "\$\(prod_pass_mark "\$wt"\)" \]\] \\\n'
                r'\s*&& \[\[ "\$\(regression_status "\$wt" prod\)" != failed \]\] && prod_carries_feature "\$wt"; \}',
                resume) is not None, True)
deploy_src = "".join(open(os.path.join(LIB, _m)).read()
    for _m in ("ship/deploy.sh", "ship/shipped.sh", "ship/vercel.sh", "ship/qa.sh", "ship/merge.sh", "ship/demo.sh"))
m = re.search(r"^remind_prod\(\) \{\n.*?^\}\n", deploy_src, re.S | re.M)
remind = m.group(0) if m else ""
mark_at = remind.rfind("prod_pass.ended")
last_done_at = remind.rfind('if ! cmd_done "$slug"; then')
check("pass-marked-before-the-clean-up", 0 < mark_at < last_done_at
      and '[[ "$prod_live" -eq 1 ]] && state_set' in remind
      and remind.count("prod_pass.ended") == 2, True)
# Marked once the epilogue ran, before anything else can stop the pass.
check("pass-marked-after-the-epilogue",
      remind.rfind("run_status ") < mark_at < remind.rfind("db_main_up"), True)

# --- the retrospective records that it changed the code ------------------------------
with open(os.path.join(LIB, "improve", "retro.sh")) as fh:
    retro_src = fh.read()
check("run-retro-records-the-change",
      'state_set "$fstate" retro.project_to "$project_after"' in retro_src, True)

# --- a second retrospective resumes the first ------------------------------------
# Once a second pass was skipped as already paid for, and a person who had left
# with Ctrl-C could not get back into it. It resumes now (tests/terminal.py runs
# it); here, that the skip did not come back and the resume reaches claude.
check("no-skip-as-paid-for", "already took place" in retro_src, False)
check("resumes-the-conversation", 'which=(--resume "$session")' in retro_src
      and 'claude_launch "${which[@]}"' in retro_src, True)
check("second-pass-prompt", 'template=retro-again' in retro_src
      and os.path.exists(os.path.join(ROOT, "sclaude", "prompts", "retro-again.md")), True)

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
    end = os.path.join(LIB, "cycle", "session_end.py")
    first = subprocess.run(["python3", end, "first", transcript], capture_output=True,
                           text=True).stdout.strip()
    last = subprocess.run(["python3", end, "last", transcript], capture_output=True,
                          text=True).stdout.strip()
    check("first-is-the-report", first, "## 1. What I may have missed")
    check("last-is-the-conversation-end", last, "Committed on the branch.")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
check("report-printed-when-left-open",
      '&& retro_report "$wt" "$session" "$last"' in retro_src, True)

# --- plan mode, and closing on its own word ------------------------------------
# The retrospective runs in plan mode, so nothing changes — sclaude's workshop
# included, which opens for it without a question — before the person approved
# a plan. Plan mode forbids it the done marker; with nothing to act on it ends
# its report on RETRO_NOTHING_SAID, and the watcher closes it on that.
check("retro-in-plan-mode", "--permission-mode plan" in retro_src
      and "--permission-mode auto" not in retro_src, True)
said = re.search(r'^RETRO_NOTHING_SAID="([^"]+)"', retro_src, re.M)
check("closing-line-declared", said is not None, True)
check("closing-line-to-the-watcher",
      'retro "$RETRO_NOTHING_SAID"' in retro_src
      and 'SCLAUDE_V_NOTHING_SAID="$RETRO_NOTHING_SAID"' in retro_src, True)
for name in ("retro.md", "retro-again.md"):
    with open(os.path.join(ROOT, "sclaude", "prompts", name)) as fh:
        text = fh.read()
    check("%s-names-the-line" % name, "`<nothing-said>`" in text, True)
    check("%s-no-marker" % name, "<done-marker>" in text, False)
run_src = "".join(open(os.path.join(LIB, m), encoding="utf-8").read()
          for m in ("cycle/run.sh", "cycle/session_watch.sh", "cycle/prompt.sh"))
check("watcher-reads-the-line",
      'watch-said "$transcript" "$started" "$said"' in run_src, True)


def timed(kind, text, at, end=True, human=False):
    e = entry(kind, text, human=human)
    e["timestamp"] = "2026-10-27T10:00:%02dZ" % at
    if kind == "assistant":
        e["message"]["stop_reason"] = "end_turn" if end else "tool_use"
    return e


def watch_said(es, after=0, line="Nothing to act on: sclaude closes this session."):
    path = os.path.join(tmp, "s.jsonl")
    with open(path, "w") as fh:
        for e in es:
            fh.write(json.dumps(e) + "\n")
    return subprocess.run(["python3", os.path.join(LIB, "cycle", "session_end.py"), "watch-said",
                           path, str(after), line],
                          capture_output=True, text=True).stdout.strip()


LINE = said.group(1) if said else ""
REPORT = "## 1. nothing\n\n## 3. nothing\n\n**%s**\n" % LINE
tmp = tempfile.mkdtemp()
try:
    check("said-ends-it", watch_said([timed("user", "go", 1, human=True),
                                      timed("assistant", REPORT, 2)], line=LINE), "ended")
    check("said-mid-turn-waits", watch_said([timed("assistant", REPORT, 2, end=False)],
                                            line=LINE), "working")
    check("a-person-after-it-keeps-it",
          watch_said([timed("assistant", REPORT, 2), timed("user", "wait", 3, human=True)],
                     line=LINE), "human")
    check("the-answer-to-them-keeps-it",
          watch_said([timed("assistant", REPORT, 2), timed("user", "wait", 3, human=True),
                      timed("assistant", "Sure.", 4)], line=LINE), "none")
    check("not-the-last-line-does-not-count",
          watch_said([timed("assistant", "%s\n\nBut section 1 has a point." % LINE, 2)],
                     line=LINE), "none")
    check("an-earlier-pass-does-not-count",
          watch_said([timed("assistant", REPORT, 2)], after=9999999999, line=LINE), "none")
    check("no-line-no-close", watch_said([timed("assistant", "## 1. a warning", 2)],
                                         line=LINE), "none")
    # Said, then taken back: a command run after it, a correction after it.
    run = timed("assistant", None, 3, end=False)
    run["message"]["content"] = [{"type": "tool_use", "name": "Bash", "input": {"command": "git status"}}]
    check("a-command-after-it-takes-it-back",
          watch_said([timed("assistant", REPORT, 2, end=False), run,
                      timed("user", "M a.txt", 4),
                      timed("assistant", "Correction: section 1 has uncommitted work.", 5)],
                     line=LINE), "none")
    check("a-near-copy-counts",
          watch_said([timed("assistant", "## 3. nothing\n\n- %s" % LINE.rstrip("."), 2)],
                     line=LINE), "ended")
    # Put into a plan, as plan mode bids: its dialog waiting is the turn's end,
    # and an answer to it goes on with the turn.
    plan = timed("assistant", None, 2, end=False)
    plan["message"]["content"] = [{"type": "tool_use", "name": "ExitPlanMode",
                                   "input": {"plan": REPORT}}]
    check("a-plan-ending-on-it-counts", watch_said([plan], line=LINE), "ended")
    check("an-answered-plan-goes-on",
          watch_said([plan, timed("user", "User rejected", 3)], line=LINE), "working")
    path = os.path.join(tmp, "p.jsonl")
    with open(path, "w") as fh:
        fh.write(json.dumps(plan) + "\n")
    shown = subprocess.run(["python3", os.path.join(LIB, "cycle", "session_end.py"), "last", path],
                           capture_output=True, text=True).stdout
    check("a-waiting-plan-is-the-report", LINE in shown, True)
    # The report in the person's language: a line after it in Cyrillic is a
    # line, and a correction in it takes the closing back.
    check("a-cyrillic-line-after-it-counts",
          watch_said([timed("assistant", REPORT + "\nСессия остаётся открытой.", 2)],
                     line=LINE), "none")
    check("a-cyrillic-correction-takes-it-back",
          watch_said([timed("assistant", REPORT, 2, end=False),
                      timed("assistant", "Хотя нет — первый пункт стоит обсудить.", 3)],
                     line=LINE), "none")
    # A plan that names a file rather than carrying its text.
    plan_file = os.path.join(tmp, "plan.md")
    with open(plan_file, "w") as fh:
        fh.write(REPORT)
    by_file = timed("assistant", None, 2, end=False)
    by_file["message"]["content"] = [{"type": "tool_use", "name": "ExitPlanMode",
                                      "input": {"planFilePath": plan_file}}]
    check("a-plan-by-file-counts", watch_said([by_file], line=LINE), "ended")

    def said_by(kind, es):
        path = os.path.join(tmp, "f.jsonl")
        with open(path, "w") as fh:
            for e in es:
                fh.write(json.dumps(e) + "\n")
        return subprocess.run(["python3", os.path.join(LIB, "cycle", "session_end.py"), kind, path],
                              capture_output=True, text=True).stdout.strip()

    # Said as a message and as a plan: printed once.
    shown = said_by("last", [timed("assistant", REPORT, 1, end=False), plan])
    check("a-report-in-both-printed-once", shown.count(LINE), 1)
    # The report given as a plan, the plan turned down with a word: the plan
    # is the report, not the answer after it.
    shown = said_by("first", [timed("user", "go", 0, human=True), plan,
                              timed("user", "rejected: talk first", 3),
                              timed("assistant", "Sure, what first?", 4)])
    check("a-plan-is-the-first-report", LINE in shown and "Sure" not in shown, True)
    # A plan is the whole report (the prompts say so): printed alone.
    short = timed("assistant", None, 2, end=False)
    short["message"]["content"] = [{"type": "tool_use", "name": "ExitPlanMode",
                                    "input": {"plan": "No changes.\n\n" + LINE}}]
    for kind in ("last", "first"):
        shown = said_by(kind, [timed("user", "go", 0, human=True),
                               timed("assistant", "Reading the state.", 1, end=False), short])
        check("%s-prints-the-plan-alone" % kind,
              "No changes." in shown and "Reading" not in shown, True)
    for name in ("retro.md", "retro-again.md"):
        with open(os.path.join(ROOT, "sclaude", "prompts", name)) as fh:
            check("%s-plan-carries-every-section" % name, "every section in full" in fh.read(), True)
    # Odd inputs are silent, as the rest of the module; a plan that is not a
    # text falls back to the file the call names.
    e = timed("assistant", None, 2, end=False)
    e["message"]["content"] = [{"type": "tool_use", "name": "ExitPlanMode",
                                "input": {"plan": ["a"], "planFilePath": plan_file}}]
    check("a-plan-not-text-reads-the-file", watch_said([e], line=LINE), "ended")
    e["message"]["content"][0]["input"] = {"planFilePath": 123}
    check("a-path-not-text-is-silent", watch_said([e], line=LINE), "none")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- the prompt names the branch -------------------------------------------------
with open(os.path.join(ROOT, "sclaude", "prompts", "retro.md")) as fh:
    prompt = fh.read()
# In the rules both passes include, so a resumed one is given them too.
with open(os.path.join(ROOT, "sclaude", "prompts", "_retro-rules.md")) as fh:
    rules = fh.read()
check("prompt-names-the-branch", "own branch, `<branch>`" in rules
      and "<include:retro-rules>" in prompt, True)
with open(os.path.join(LIB, "improve", "retro.sh")) as fh:
    check("branch-passed-to-prompt", 'SCLAUDE_V_BRANCH=' in fh.read(), True)

# --- the declined proposals go back to the person's list ---------------------------
#
# The session works on a copy; only the lines it added since the copy go
# back, appended to the list as it is by then.
dtmp = tempfile.mkdtemp()
try:
    home = os.path.join(dtmp, "repo", ".sclaude", "local", "retro-declined.md")
    here = os.path.join(dtmp, "wt-retro-declined.md")
    bin_d = os.path.join(dtmp, "bin")
    os.makedirs(bin_d)

    def back():
        run_bash('retro_declined_back "%s" "%s"' % (here, home), dtmp, bin_d)

    def into():
        run_bash('retro_declined_in "%s" "%s"' % (here, home), dtmp, bin_d)

    def read(path):
        with open(path) as fh:
            return fh.read()

    # No list yet: whatever the session wrote is the list.
    with open(here, "w") as fh:
        fh.write("- A\n")
    back()
    check("declined-first-line", read(home), "- A\n")
    # A copy taken, then another hand adds B; a session that wrote nothing
    # leaves B in place, and one that added C adds C alone.
    into()
    with open(home, "a") as fh:
        fh.write("- B\n")
    back()
    check("declined-untouched-copy-keeps-others", read(home), "- A\n- B\n")
    with open(here, "a") as fh:
        fh.write("- C\n")
    back()
    check("declined-only-added-lines", read(home), "- A\n- B\n- C\n")
    # A copy left by a pass that ended before carrying it back is carried
    # back before the next copy is taken.
    with open(here, "a") as fh:
        fh.write("- D\n")
    into()
    check("declined-leftover-carried-first", (read(home), read(here)),
          ("- A\n- B\n- C\n- D\n", "- A\n- B\n- C\n- D\n"))
    os.remove(here)
    back()
    check("declined-kept-without-a-copy", read(home), "- A\n- B\n- C\n- D\n")
    # A list saved without a final newline takes the next line on its own.
    into()
    with open(home, "w") as fh:
        fh.write("- A\n- B\n- C\n- D")
    with open(here, "a") as fh:
        fh.write("- E\n")
    back()
    check("declined-after-no-final-newline", read(home), "- A\n- B\n- C\n- D\n- E\n")
    # A kept copy (the list could not be written) saved without a final
    # newline takes the list's newer lines each on its own.
    with open(here, "w") as fh:
        fh.write("- A\n- F")
    with open(here + ".base", "w") as fh:
        fh.write("- A\n")
    run_bash('retro_declined_append "%s" "- G"' % here, dtmp, bin_d)
    check("declined-append-after-no-final-newline", read(here), "- A\n- F\n- G\n")
finally:
    shutil.rmtree(dtmp, ignore_errors=True)

# --- a feature with no change of its own has a retrospective too -------------------
#
# Once a feature did all of its work in sclaude's own checkout, ended as one
# with no change (no_change.sh), and `done` skipped the retrospective because
# there was no pull request to read.
check("done-runs-retro-for-no-change",
      re.search(r'\n\s*(?:\[\[ -n "\$retro_ran_here" \]\] \|\| )?run_retro "\$wt" "\$slug" "\$pr" "\$issue"\n', body) is not None, True)
check("done-retro-before-settle",
      0 <= body.find("run_retro ") < body.find('no_change_settle "$wt"'), True)
check("done-reopens-no-change-with-own-work",
      'state_set "$state" no_change null' in body
      and "step_rewind_to \"$wt\" pr pr review" in body, True)
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import render_prompt
values = {"feature": "f", "pr": "\u2014", "pr-number": "", "no-change": "1",
          "issue": "9", "branch": "feat/f", "worktree": "/w", "instruments": "/i",
          "terminal": "", "terminal-raw": "/r", "transcripts": "/t",
          "nothing-said": "Nothing to act on."}
no_pr = render_prompt.render(prompt, os.path.join(ROOT, "sclaude", "prompts"), values, {})
check("no-change-prompt-names-no-pr", "#\u2014" not in no_pr and "pull request #" not in no_pr, True)
check("no-change-prompt-names-the-issue", "The issue #9" in no_pr, True)
values.update({"pr": "5", "pr-number": "5", "no-change": ""})
with_pr = render_prompt.render(prompt, os.path.join(ROOT, "sclaude", "prompts"), values, {})
check("merged-prompt-unchanged", "is merged, and" in with_pr
      and "The pull request #5 and the issue #9" in with_pr, True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
