#!/usr/bin/env python3
#
# The review step, one round per session.
#
# On one pull request five review rounds ran in one conversation, and every file
# each fix read stayed in its context. Now a session fixes through subagents,
# and once the automatic review closes everything it fixed and posts new
# findings, it writes a marker and stops; the orchestrator ends it, records it
# in the issue, and opens a fresh one that sees only the threads still open.
#
# Guarded here:
#
#   * session_watch_start ends the claude process of that session — found by
#     `--session-id` or `--resume` and its id — once a marker appears and the
#     turn that wrote it has ended, and leaves every other process alone;
#   * it waits while the turn is still running, and calls the closing off when
#     a person types anything but /exit after the marker;
#   * session_watch_stop ends the watcher when the session exits by itself;
#   * session_end.py hands back the session's last message, the one printed
#     once the orchestrator has closed it;
#   * session_runs records why a session was ended, and the issue shows it;
#   * the snapshot a fresh session gets lists open review threads in full, with
#     their replies, across pages; of the resolved ones it counts them all and
#     lists in one line those on a file that still has an open thread, so a new
#     finding that would undo an earlier fix can be seen as one;
#   * the prompt names the same marker file the orchestrator watches;
#   * a closed round stays in the same session while its context is under
#     REVIEW_CONTEXT_MAX_PCT, and goes to a fresh one past it: the tokens
#     come from the transcript, the share from what the status line left,
#     and every review session's end is logged with both.
#
# Run it with: python3 tests/review-round.py
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def functions(source, names):
    out = []
    for name in names:
        m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
        if not m:
            failures.append(("function-present-" + name, True, False))
            continue
        out.append(m.group(0))
    return "\n".join(out)


with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()
WATCH = 'source "%s/state.sh"\nLIB="%s"\n' % (LIB, LIB) + functions(
    RUN, ["round_marker", "done_marker", "session_watch_start", "session_watch_stop"])
END = os.path.join(LIB, "session_end.py")

tmp = tempfile.mkdtemp()
try:
    wt = os.path.join(tmp, "wt")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    session = "0f1e2d3c-aaaa-bbbb-cccc-000000000001"

    def fake(args):
        """A long-running process whose arguments look like claude's."""
        return subprocess.Popen(["bash", "-c", 'exec -a "claude %s" sleep 60' % args])

    home = os.path.join(tmp, "home")
    tdir = os.path.join(home, ".claude", "projects", re.sub(r"[^a-zA-Z0-9]", "-", wt))
    os.makedirs(tdir)
    transcript = os.path.join(tdir, session + ".jsonl")

    def stamp(offset=1.0):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + offset)) + ".000Z"

    def say(*entries):
        with open(transcript, "a") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")

    def turn_end(text="Done.\n\nNothing open."):
        return {"type": "assistant", "timestamp": stamp(),
                "message": {"stop_reason": "end_turn",
                            "content": [{"type": "text", "text": text}]}}

    def typed(text):
        return {"type": "user", "timestamp": stamp(), "origin": {"kind": "human"},
                "message": {"content": text}}

    def command(name):
        return {"type": "system", "subtype": "local_command", "timestamp": stamp(),
                "content": "<command-name>%s</command-name>" % name}

    def watched(marker, after, wait=1.5):
        """Start the watcher, write the marker, add `after` to the transcript."""
        open(transcript, "w").close()
        script = WATCH + """
export HOME="%s"
SESSION_POLL=0.2 SESSION_GRACE=0
session_watch_start "%s" "%s"
sleep 0.4
echo "x" > "%s"
sleep %s
session_watch_stop
echo "watcher=[$SESSION_WATCHER]"
""" % (home, wt, session, os.path.join(wt, ".sclaude/local/feature", marker), wait)
        proc = subprocess.Popen(["bash", "-c", script], stdout=subprocess.PIPE, text=True)
        time.sleep(0.8)
        say(*after)
        return proc.communicate(timeout=30)[0]

    # --- a marker and an ended turn end that session's process, and only it ---
    for marker in ("review-round", "session-done"):
        target = fake("--session-id %s --model opus" % session)
        resumed_other = fake("--resume 99999999-0000-0000-0000-000000000000")
        mentions = fake("--name x-%s" % session)  # the id, but not as a session flag
        watched(marker, [turn_end()])
        time.sleep(0.3)
        check("%s-ends-the-session" % marker, target.poll() is not None, True)
        check("%s-other-session-left-alone" % marker, resumed_other.poll(), None)
        check("%s-id-without-flag-left-alone" % marker, mentions.poll(), None)
        for p in (target, resumed_other, mentions):
            p.kill()

    # --- the turn that wrote the marker is still running: nothing yet ---------
    target = fake("--resume %s" % session)
    watched("session-done", [{"type": "assistant", "timestamp": stamp(),
                              "message": {"stop_reason": "tool_use", "content": []}}])
    check("running-turn-not-closed", target.poll(), None)
    target.kill()

    # --- a person typed after the marker: called off, marker gone -------------
    target = fake("--resume %s" % session)
    watched("session-done", [turn_end(), typed("wait, one more thing")])
    check("typed-calls-it-off", target.poll(), None)
    check("typed-removes-the-marker",
          os.path.exists(os.path.join(wt, ".sclaude/local/feature", "session-done")), False)
    target.kill()

    target = fake("--resume %s" % session)
    watched("session-done", [turn_end(), command("/cost")])
    check("command-calls-it-off", target.poll(), None)
    target.kill()

    # --- /exit is what the watcher does anyway: it does not call it off -------
    target = fake("--resume %s" % session)
    watched("session-done", [turn_end(), command("/exit")])
    time.sleep(0.3)
    check("exit-does-not-call-it-off", target.poll() is not None, True)
    target.kill()

    # --- no marker: the watcher is stopped and kills nothing ------------------
    target = fake("--resume %s" % session)
    script = WATCH + """
export HOME="%s"
SESSION_POLL=0.2 SESSION_GRACE=0
session_watch_start "%s" "%s"
sleep 0.6
session_watch_stop
echo "watcher=[$SESSION_WATCHER]"
""" % (home, wt, session)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         timeout=30).stdout
    check("no-marker-no-kill", target.poll(), None)
    check("watcher-cleared", "watcher=[]" in out, True)
    # Writing the marker after the watcher is stopped changes nothing.
    with open(os.path.join(wt, ".sclaude/local/feature", "review-round"), "w") as fh:
        fh.write("late\n")
    say(turn_end())
    time.sleep(0.5)
    check("stopped-watcher-stays-stopped", target.poll(), None)
    target.kill()
    os.remove(os.path.join(wt, ".sclaude/local/feature", "review-round"))

    # --- step 1: the plan's approval is its marker ----------------------------
    for approval, closes in (("User has approved your plan.", True),
                             ("User rejected the plan.", False)):
        target = fake("--session-id %s" % session)
        open(transcript, "w").close()
        done_file = os.path.join(wt, ".sclaude/local/feature", "session-done")
        script = WATCH + """
export HOME="%s"
SESSION_POLL=0.2 SESSION_GRACE=0
session_watch_start "%s" "%s" "" "" plan
sleep 1.8
session_watch_stop
""" % (home, wt, session)
        proc = subprocess.Popen(["bash", "-c", script])
        time.sleep(0.5)
        say({"type": "assistant", "timestamp": stamp(),
             "message": {"stop_reason": "tool_use",
                         "content": [{"type": "tool_use", "name": "ExitPlanMode", "input": {}}]}},
            {"type": "user", "timestamp": stamp(),
             "message": {"content": [{"type": "tool_result", "content": approval}]}},
            turn_end("The plan is approved."))
        proc.wait(timeout=30)
        time.sleep(0.3)
        check("plan-%s" % ("approved-closes" if closes else "rejected-stays"),
              target.poll() is not None, closes)
        check("plan-%s-marks-it" % ("approved" if closes else "rejected"),
              os.path.exists(done_file), closes)
        target.kill()
        if os.path.exists(done_file):
            os.remove(done_file)

    # --- an approval from before this launch does not count -------------------
    target = fake("--resume %s" % session)
    open(transcript, "w").close()
    say({"type": "assistant", "timestamp": stamp(-60),
         "message": {"stop_reason": "tool_use",
                     "content": [{"type": "tool_use", "name": "ExitPlanMode", "input": {}}]}},
        {"type": "user", "timestamp": stamp(-59),
         "message": {"content": [{"type": "tool_result", "content": "User has approved your plan."}]}},
        dict(turn_end("Approved earlier."), timestamp=stamp(-58)))
    script = WATCH + """
export HOME="%s"
SESSION_POLL=0.2 SESSION_GRACE=0
session_watch_start "%s" "%s" "" "" plan
sleep 1.2
session_watch_stop
""" % (home, wt, session)
    subprocess.run(["bash", "-c", script], timeout=30)
    check("stale-approval-ignored", target.poll(), None)
    target.kill()

    # --- unpushed: commits on no remote, and only for an open pull request ----
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git = lambda *a: subprocess.run(["git", "-C", repo] + list(a), capture_output=True, text=True)
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "a")
    git("update-ref", "refs/remotes/origin/b", "HEAD")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "b")
    spec = importlib.util.spec_from_file_location("pr_context_u", os.path.join(LIB, "pr_context.py"))
    pcu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pcu)
    check("unpushed-counted", pcu.unpushed(repo, {"state": "OPEN"}), 1)
    check("unpushed-closed-pr-not-asked", pcu.unpushed(repo, {"state": "MERGED"}), 0)
    git("update-ref", "refs/remotes/origin/b", "HEAD")
    check("unpushed-none", pcu.unpushed(repo, {"state": "OPEN"}), 0)

    # --- the epilogue: no worktree, a marker and a cwd of its own -------------
    target = fake("--session-id %s" % session)
    open(transcript, "w").close()
    own = os.path.join(tmp, "epilogue.done")
    script = WATCH + """
export HOME="%s"
SESSION_POLL=0.2 SESSION_GRACE=0
session_watch_start "" "%s" "%s" "%s"
sleep 0.4
echo done > "%s"
sleep 1.5
session_watch_stop
""" % (home, session, own, wt, own)
    proc = subprocess.Popen(["bash", "-c", script])
    time.sleep(0.8)
    say(turn_end())
    proc.wait(timeout=30)
    time.sleep(0.3)
    check("epilogue-marker-ends-the-session", target.poll() is not None, True)
    target.kill()
    os.remove(own)
    with open(os.path.join(LIB, "github.sh")) as fh:
        GH = fh.read()
    check("epilogue-watched", 'session_watch_start "" "$session" "$done_file" "$REPO"' in GH, True)
    check("epilogue-reports", 'session_closed "$done_file" "$REPO" "$session"' in GH, True)

    # --- the last message is the text after the last thing handed in ----------
    open(transcript, "w").close()
    say(typed("go"),
        {"type": "assistant", "timestamp": stamp(),
         "message": {"content": [{"type": "text", "text": "Pushing now."},
                                 {"type": "tool_use", "name": "Bash"}]}},
        {"type": "user", "timestamp": stamp(), "message": {"content": [{"type": "tool_result"}]}},
        {"type": "assistant", "timestamp": stamp(), "isSidechain": True,
         "message": {"content": [{"type": "text", "text": "a subagent"}]}},
        turn_end("Done: all closed.\n\nOpen: nothing."))
    last = subprocess.run([sys.executable, END, "last", transcript],
                          capture_output=True, text=True).stdout
    check("last-message", last, "Done: all closed.\n\nOpen: nothing.\n")

    # --- the advice to type /exit is cut, the rest of the report kept ---------
    open(transcript, "w").close()
    say(turn_end("Done.\n\n- all closed;\n- close Claude with `/exit`;\n- sclaude goes on.\n\n"
                 "Ready. Now type /exit. Then the preview."))
    last = subprocess.run([sys.executable, END, "last", transcript],
                          capture_output=True, text=True).stdout
    check("exit-advice-cut", last,
          "Done.\n\n- all closed;\n- sclaude goes on.\n\nReady. Then the preview.\n")
    check("closed-said-after-the-report",
          "You do not need to type /exit" in RUN[RUN.index("session_report() {"):], True)

    # --- the ended session is recorded with its reason ------------------------
    state = os.path.join(wt, ".sclaude/local/feature", "state.json")
    with open(state, "w") as fh:
        json.dump({"steps": {"review": {}}}, fh)
    body = 'source "%s/state.sh"\n' % LIB
    body += 'session_runs "%s" steps.review open S1\n' % state
    body += 'session_runs "%s" steps.review end S1 "fixes confirmed"\n' % state
    body += 'session_runs "%s" steps.review open S2\n' % state
    subprocess.run(["bash", "-c", body], timeout=30)
    with open(state) as fh:
        runs = json.load(fh)["steps"]["review"]["runs"]
    check("two-rows", [r["session"] for r in runs], ["S1", "S2"])
    check("reason-recorded", runs[0].get("outcome"), "fixes confirmed")
    check("second-row-open", runs[1].get("finished"), None)
    # Through step_run, as run_step records it: it used to drop the reason.
    body = 'source "%s/state.sh"\nsource "%s/steps.sh"\n' % (LIB, LIB)
    body += 'step_run "%s" review open S3\n' % wt
    body += 'step_run "%s" review end S3 "fixes confirmed"\n' % wt
    subprocess.run(["bash", "-c", body], timeout=30)
    with open(state) as fh:
        runs = json.load(fh)["steps"]["review"]["runs"]
    check("step-run-passes-the-reason", runs[-1].get("outcome"), "fixes confirmed")
    with open(os.path.join(LIB, "github.sh")) as fh:
        gh_src = fh.read()
    check("issue-shows-the-reason",
          'run_status = run.get("outcome") or ("done" if run.get("done") else "interrupted")' in gh_src,
          True)

    # --- run_step rotates on the marker ----------------------------------------
    rot = RUN[RUN.index('if [[ "$step" == "review" && -s "$(round_marker "$wt")" ]]; then'):]
    rot = rot[:rot.index("\n  fi\n")]
    check("rotation-records-the-reason", 'step_run "$wt" "$step" end "$session" "fixes confirmed"' in rot, True)
    check("rotation-forgets-the-session", 'state_set "$state" "steps.$step.session" null' in rot, True)
    check("rotation-writes-the-issue", 'issue_sync "$wt"' in rot, True)
    check("rotation-opens-a-fresh-session", 'run_step "$wt" "$slug" "$step"' in rot, True)
    # A round carried on in the same session resumes it through run_step, and
    # the issue row must show the comments that round added.
    resume = RUN[RUN.index('claude_launch --resume "$session"') - 600:RUN.index('claude_launch --resume "$session"')]
    check("resume-writes-the-issue",
          resume.index('run_comments "$wt" "$session" "$pr"') < resume.index('issue_sync "$wt"'), True)
    check("every-step-launch-watched",
          RUN.count('    session_watch_start "$wt" "$session" "" "" "$step"\n'), 2)
    check("both-launches-unwatched", RUN.count("    session_watch_stop\n"), 2)

    # --- a failed closing check goes back to the same session, twice at most --
    ret = RUN[RUN.index("auto_return() {"):]
    ret = ret[:ret.index("\n}\n")]
    check("auto-return-only-after-auto-close", '[[ -n "${SESSION_AUTO_CLOSED:-}" ]] || return 1' in ret, True)
    check("auto-return-limited", '[[ "$used" -ge "$AUTO_RETURNS" ]]' in ret and "AUTO_RETURNS=2" in RUN, True)
    check("auto-return-resumes", 'run_step "$wt" "$slug" "$step" "$why"' in ret, True)
    check("auto-return-unspent-when-nothing-opened",
          'if [[ -z "$RUN_STEP_LAUNCHED" ]]; then\n    state_set "$state" "steps.$step.auto_returns" "$used"' in ret, True)
    check("no-global-opening", "SESSION_OPENING" in RUN, False)
    after = RUN[RUN.index("after_step() {"):]
    after = after[:after.index("\n}\n")]
    check("plan-returns", after.count('auto_return "$wt" "$slug" "$step"'), 3)
    check("pr-checks-the-push", 'pr_context.py" --unpushed "$wt" "$number"' in after, True)
    check("code-no-goes-back",
          'run_step "$wt" "$slug" "$step" "**The person checked the work and it does not work yet:** $wrong"' in after, True)
    check("code-enter-leaves-for-later",
          'if [[ -z "$wrong" ]]; then\n          info "The step stays current.' in after, True)
    check("returns-reset-on-close", 'state_set "$state" "steps.$step.auto_returns" null' in after, True)
    check("resume-hears-the-opening", '[[ -n "$told" ]] && opening=' in RUN, True)
    check("fresh-hears-the-opening", '[[ -n "$told" ]] && prompt=' in RUN, True)
    # A resumed review counts what its interrupted run committed: the base is
    # kept with the review, not taken from HEAD again.
    check("friction-base-kept", '[[ -n "$session" ]] && project_before="$(state_get "$state" '
          '"friction.$key.project_base"' in RUN, True)
    check("friction-base-must-be-an-ancestor",
          'merge-base --is-ancestor "$project_before" HEAD' in RUN, True)
    check("friction-watched", RUN.count('session_watch_start "" "$session" "$done_file" "$where"'), 2)

    # --- the prompt names the marker the orchestrator watches -----------------
    with open(os.path.join(ROOT, "sclaude", "prompts", "review.md")) as fh:
        prompt = fh.read()
    check("prompt-names-the-marker", "> .sclaude/local/feature/review-round" in prompt, True)
    check("prompt-uses-subagents", "Fix through subagents" in prompt, True)
    check("code-watches-the-same-file", 'echo "$1/.sclaude/local/feature/review-round"' in RUN, True)

    # --- the context a session holds: its own requests, not a subagent's ------
    def used(tokens, cached=0, side=False):
        e = {"type": "assistant", "timestamp": stamp(),
             "message": {"stop_reason": "end_turn", "content": [],
                         "usage": {"input_tokens": tokens, "cache_read_input_tokens": cached,
                                   "cache_creation_input_tokens": 0, "output_tokens": 50}}}
        if side:
            e["isSidechain"] = True
        return e

    open(transcript, "w").close()
    say(used(10, 50000), used(5, 70000), used(900000, side=True), used(0))
    held = subprocess.run([sys.executable, END, "context", transcript],
                          capture_output=True, text=True).stdout
    check("context-now-and-start", held, "70005 50010\n")
    open(transcript, "w").close()
    check("context-none-when-empty",
          subprocess.run([sys.executable, END, "context", transcript],
                         capture_output=True, text=True).stdout, "")

    # --- the status line leaves the share where sclaude reads it --------------
    sid = "statusline-test-%d" % os.getpid()
    shared = "/tmp/claude-statusline-context-%s" % sid
    subprocess.run([sys.executable, os.path.join(ROOT, "statusline.py")],
                   input=json.dumps({"session_id": sid, "context_window":
                                     {"used_percentage": 12.6, "context_window_size": 1000000}}),
                   capture_output=True, text=True, timeout=30)
    try:
        with open(shared) as fh:
            check("statusline-leaves-the-share", json.load(fh),
                  {"used_percentage": 12.6, "context_window_size": 1000000})
    except OSError:
        check("statusline-leaves-the-share", "missing", "written")

    # --- review_context joins the two, review_context_log writes the line ------
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", repo], check=True)
    ctx_wt = os.path.join(repo, "wt")
    os.makedirs(os.path.join(ctx_wt, ".sclaude/local/feature"))
    with open(os.path.join(ctx_wt, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump({"steps": {"review": {"runs": [{"session": sid, "comments": 7}]}}}, fh)
    ctx_dir = os.path.join(home, ".claude", "projects", re.sub(r"[^a-zA-Z0-9]", "-", ctx_wt))
    os.makedirs(ctx_dir)
    with open(os.path.join(ctx_dir, sid + ".jsonl"), "w") as fh:
        fh.write(json.dumps(used(10, 50000)) + "\n" + json.dumps(used(3, 120000)) + "\n")
    script = 'source "%s/state.sh"\nsource "%s/scratch.sh"\nLIB="%s"\nREVIEW_CONTEXT_MAX_PCT=40\n' % (LIB, LIB, LIB)
    script += functions(RUN, ["review_context", "review_context_log", "review_carry_on", "reversals_file"])
    script += '\nexport HOME="%s"\nheld="$(review_context "%s" "%s")"\necho "$held"\n' % (home, ctx_wt, sid)
    script += 'review_context_log "%s" feat "%s" "carried on" "$held" 2\n' % (ctx_wt, sid)
    script += 'review_carry_on 12\n'
    reversals = os.path.join(ctx_wt, ".sclaude/local/feature/review-reversals")
    with open(reversals, "w") as fh:
        fh.write("https://x/pull/1#discussion_r1\tundoes abc\nhttps://x/pull/1#discussion_r2\tundoes def\n")
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
    check("reversals-emptied-once-counted", os.path.getsize(reversals), 0)
    check("context-joined", out.split("\n")[0], "120003 50010 13 1000000")
    check("carry-on-names-the-share", "Your context is at 12% — under the 40%" in out, True)
    try:
        with open(os.path.join(repo, ".sclaude/local/review-context.log")) as fh:
            row = fh.read().rstrip("\n").split("\t")
        check("log-row", row[1:], ["feat", sid, "carried on", "120003", "50010", "13", "1000000", "2", "7", "2"])
    except OSError:
        check("log-row", "missing", "written")
    os.remove(shared)
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
    check("context-without-statusline", out.split("\n")[0], "120003 50010 - -")

    # --- the round goes on in the same session under the threshold -------------
    check("threshold-decides", '[[ "$pct" =~ ^[0-9]+$ && "$pct" -lt "$REVIEW_CONTEXT_MAX_PCT" ]]' in rot, True)
    check("carry-on-resumes-with-a-word", 'run_step "$wt" "$slug" "$step" "$(review_carry_on "$pct")"' in rot, True)
    carry = rot[rot.index('-lt "$REVIEW_CONTEXT_MAX_PCT" ]]; then'):rot.index("    fi\n")]
    check("carry-on-keeps-the-session", "steps.$step.session" in carry or "end \"$session\"" in carry, False)
    check("rotation-logged", 'review_context_log "$wt" "$slug" "$session" "fresh session"' in rot, True)
    check("exit-logged", RUN.count('review_context_log "$wt" "$slug" "$session"'), 3)
    with open(os.path.join(LIB, "steps.sh")) as fh:
        check("threshold-default", 'REVIEW_CONTEXT_MAX_PCT="${REVIEW_CONTEXT_MAX_PCT:-40}"' in fh.read(), True)
    check("prompt-four-passes", "Four such passes at most" in prompt, True)
    check("prompt-leaves-the-choice", "who takes them is the orchestrator's call" in prompt, True)
    check("prompt-names-the-reversals-file",
          ">> .sclaude/local/feature/review-reversals" in prompt
          and 'echo "$1/.sclaude/local/feature/review-reversals"' in RUN, True)

    # --- review-stats reads the log back --------------------------------------
    spec = importlib.util.spec_from_file_location("review_stats", os.path.join(LIB, "review_stats.py"))
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    log = os.path.join(tmp, "review-context.log")
    with open(log, "w") as fh:
        for line in (
            # One session: two rounds carried on, then done in its third.
            ["t", "f", "A", "carried on", "80000", "50000", "8", "1000000", "1", "4", "0"],
            ["t", "f", "A", "carried on", "110000", "50000", "11", "1000000", "2", "6", "1"],
            ["t", "f", "A", "done", "140000", "50000", "14", "1000000", "2", "7", "1"],
            # Another, one round, closed by a person.
            ["t", "g", "B", "exit", "70000", "60000", "7", "1000000", "0", "2", "0"],
            ["broken line"],
        ):
            fh.write("\t".join(line) + "\n")
    data = rs.rows(log)
    check("stats-rows", len(data), 4)
    check("stats-segment", [rs.segment(r) for r in data], [1, 2, 3, 1])
    text = rs.report(data)
    check("stats-sessions", "2 review sessions, 4 rows" in text, True)
    check("stats-door", "holds 55k before" in text, True)
    check("stats-reversals-first", "first round of a session: 0 over 2" in text, True)
    check("stats-reversals-later", "later rounds: 2 over 2 stretches (1.00 each)" in text, True)
    check("stats-window", "1% of the window is 10k" in text, True)
    check("stats-empty", rs.report([]), "No review sessions logged yet.")
    check("stats-command", "review-stats)  cmd_review_stats ;;" in open(os.path.join(ROOT, "bin", "sclaude")).read(), True)

    # --- a fresh session sees open threads only --------------------------------
    spec = importlib.util.spec_from_file_location("pr_context", os.path.join(LIB, "pr_context.py"))
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)
    REVIEW_JOB = "Review — delta, whole PR once all fixed (Opus)"

    def thread(resolved, path, body, replies=()):
        return {"isResolved": resolved, "isOutdated": False, "path": path, "line": 7,
                "originalLine": 7,
                "comments": {"nodes": [{"author": {"login": "claude"}, "body": body}]
                             + [{"author": {"login": "ilia"}, "body": r} for r in replies]}}

    pages = [
        {"pageInfo": {"hasNextPage": True, "endCursor": "c1"},
         "nodes": [thread(True, "a.ts", "old, fixed"), thread(False, "b.ts", "still open", ["why?"])]},
        {"pageInfo": {"hasNextPage": False, "endCursor": None},
         "nodes": [thread(True, "c.ts", "old too"), thread(False, "d.ts", "second page"),
                   thread(True, "b.ts", "**Filter in the guard.** It runs on.\nlong body",
                          ["Resolved automatically: fixed in abc. Moved to the guard."])]},
    ]
    calls = []

    def fake_gh(args, cwd=None):
        if args[:2] == ["pr", "view"]:
            return {"statusCheckRollup": [], "comments": [], "title": "t", "url": "u"}
        if args[:2] == ["api", "graphql"]:
            calls.append(args)
            page = pages[1] if any(a == "after=c1" for a in args) else pages[0]
            return {"data": {"repository": {"pullRequest": {"reviewThreads": page}}}}
        return None

    pc.gh_json = fake_gh
    out = pc.render(tmp, "143", "o/r")
    check("both-pages-read", len(calls), 2)
    check("open-thread-shown", "still open" in out and "second page" in out, True)
    check("resolved-elsewhere-left-out", "old, fixed" in out or "old too" in out, False)
    check("resolved-counted", "3 review threads already resolved" in out, True)
    check("resolved-nearby-listed",
          "- `b.ts:7` **Filter in the guard.** → fixed in abc. Moved to the guard." in out,
          True)
    check("resolved-nearby-headline-only", "long body" in out or "runs on" in out, False)
    check("reply-kept", "> **reply — ilia:** why?" in out, True)

    # --- a closed session's leftovers, split by whose they are -----------------
    real_open_threads = pc.open_threads
    pc.open_threads = lambda cwd, pr, repo: ([{"created": "2026-10-02T10:00:00Z"},
                                              {"created": "2026-10-02T12:00:00Z"},
                                              {"created": ""}], [])
    check("open-since-split", pc.open_since(tmp, "143", "o/r", "2026-10-02T12:00:00+01:00"), (2, 1))
    pc.open_threads = real_open_threads
    gate = RUN[RUN.index("review_close_gate() {"):]
    gate = gate[:gate.index("\n}\n")]
    check("auto-closed-gate-asks-nobody",
          gate.index('review_reopen "$wt" "$slug" "$pr" "$repo" "$waited"')
          < gate.index("Back to a review session for it?"), True)
    reopen = RUN[RUN.index("review_reopen() {"):]
    reopen = reopen[:reopen.index("\n}\n")]
    check("new-round-gets-a-fresh-session",
          'state_set "$state" steps.review.session null' in reopen, True)
    with open(os.path.join(LIB, "regression.sh")) as fh:
        REG = fh.read()
    fix = REG[REG.index("regression_fix() {"):]
    fix = fix[:fix.index("\n}\n")]
    check("fix-session-watched", 'session_watch_start "$wt" "$session"' in fix, True)
    check("same-part-resumes-the-fixer",
          '"regression.$stage.fix_for" 2>/dev/null || true)" == "$failed"' in fix
          and 'claude_launch --resume "$session"' in fix, True)
    check("green-forgets-the-fixer", 'state_set "$state" "regression.$stage.fix_session" null' in REG, True)

    # --- step 4 closes only once the review is done with the head -------------
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()

    UNPUSHED = pc.unpushed

    def close(view, threads_open=0, cwd=ROOT):
        def gh(args, cwd=None):
            if args[:2] == ["pr", "view"]:
                return view
            if args[:2] == ["api", "graphql"]:
                nodes = [thread(False, "x.ts", "open")] * threads_open
                return {"data": {"repository": {"pullRequest": {"reviewThreads": {
                    "pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}}
            return None
        pc.gh_json = gh
        # Against this repository the answer would depend on whether its own
        # commits are pushed yet; the unpushed cases use a tree of their own.
        pc.unpushed = UNPUSHED if cwd != ROOT else (lambda where, view: 0)
        return pc.close_state(cwd, "143", "o/r")

    green = [{"name": "checks", "status": "COMPLETED", "conclusion": "SUCCESS"},
             {"name": pc.FINDINGS_CHECK, "status": "COMPLETED", "conclusion": "SUCCESS"}]
    base = {"headRefOid": head, "state": "OPEN", "createdAt": "2020-01-01T00:00:00Z"}
    check("close-ok", close(dict(base, statusCheckRollup=green)), "ok")
    check("close-pending",
          close(dict(base, statusCheckRollup=green + [{"name": REVIEW_JOB, "workflowName": "Claude Code Review", "status": "IN_PROGRESS"}])),
          "pending")
    red = [green[0], {"name": pc.FINDINGS_CHECK, "status": "COMPLETED", "conclusion": "FAILURE"}]
    check("close-open", close(dict(base, statusCheckRollup=red), threads_open=6),
          "open: red: %s; 6 review thread(s) open" % pc.FINDINGS_CHECK)
    check("close-threads-alone", close(dict(base, statusCheckRollup=green), threads_open=1),
          "open: 1 review thread(s) open")
    # Commits here on no remote hold the step; a pull request whose head is
    # merely different — moved ahead by GitHub's "Update branch" — does not.
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "c")
    check("close-unpushed", close(dict(base, statusCheckRollup=green), cwd=repo),
          "open: 1 commit(s) here are not pushed, so the pull request does not carry them")
    git("update-ref", "refs/remotes/origin/b", "HEAD")
    check("close-head-ahead-is-fine",
          close(dict(base, headRefOid="0" * 40, statusCheckRollup=green), cwd=repo), "ok")
    # Pushed, and GitHub still names the commit before as the head, with its
    # green checks: wait, not close. A friction push after the last round was
    # closed on in under a minute, and its review's threads were left behind.
    older = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                           capture_output=True, text=True).stdout.strip()
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "friction")
    git("update-ref", "refs/remotes/origin/b", "HEAD")
    check("close-stale-head-waits",
          close(dict(base, headRefOid=older, statusCheckRollup=green), cwd=repo), "pending")
    RECENT = pc.recent
    pc.recent = lambda created, cwd: False
    check("close-stale-head-for-long-is-said",
          close(dict(base, headRefOid=older, statusCheckRollup=green), cwd=repo),
          "open: PR #143 still names %s as its head, behind this branch" % older[:8])
    pc.recent = RECENT
    check("close-merged", close(dict(base, state="MERGED", statusCheckRollup=red), 3), "ok")
    check("close-unreadable", close(None), "ok")

    a = RUN[RUN.index("\nafter_step() {"):]
    a = a[a.index("    review)"):]
    check("gate-before-regression",
          a.index("review_close_gate") < a.index("regression_gate"), True)
    # Once the regression's fixing session committed, nobody pushed, and
    # the pull request merged without the fix. After the gate, the fix is pushed
    # and the review is asked again.
    rg = a.index('regression_gate "$wt"')
    pf = a.index('regression_push_fix "$wt"')
    check("regression-fix-pushed-after-gate",
          rg < pf < a.index('review_close_gate "$wt"', pf), True)
    push = functions(RUN, ["regression_push_fix"])
    origin = os.path.join(tmp, "push-origin.git")
    clone = os.path.join(tmp, "push-clone")
    fakelib = os.path.join(tmp, "push-lib")
    os.makedirs(fakelib)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, clone], check=True,
                   stderr=subprocess.DEVNULL)
    subprocess.run(git + ["-C", clone, "switch", "-q", "-c", "feat/x"], check=True)
    subprocess.run(git + ["-C", clone, "commit", "-q", "--allow-empty", "-m", "fix"],
                   check=True)

    def push_fix(ahead, pr="160"):
        with open(os.path.join(fakelib, "pr_context.py"), "w") as fh:
            fh.write("print(%d)\n" % ahead)
        script = ('LIB="%s"; info() { :; }; warn() { :; }\n%s\n'
                  'regression_push_fix "%s" "%s"; echo "rc=$?"'
                  % (fakelib, push, clone, pr))
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return out.stdout.strip().splitlines()[-1]

    check("push-fix-nothing-ahead", push_fix(0), "rc=1")
    check("push-fix-no-pr", push_fix(1, pr="null"), "rc=1")
    check("push-fix-pushes", push_fix(1), "rc=0")
    check("push-fix-reached-origin",
          subprocess.run(["git", "-C", origin, "rev-parse", "-q", "--verify",
                          "refs/heads/feat/x"], capture_output=True).returncode, 0)
    shutil.rmtree(origin)
    check("push-fix-failed", push_fix(1), "rc=2")

    se = RUN[RUN.index("\nsession_ended() {"):]
    se = se[:se.index("\n}\n")]
    check("session-ended-reads-pr-and-issue",
          'pr="$(state_get "$state" pr' in se and 'issue="$(state_get "$state" issue' in se, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
