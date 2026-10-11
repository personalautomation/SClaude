#!/usr/bin/env python3
#
# A test bench for the sessions a step ran in, and how the issue summary shows
# them.
#
# The rule: one row per claude conversation. The same conversation entered
# several times is one row, from its first start to its last exit; a new
# conversation is a row of its own. A conversation that never began has no row.
#
# step_run is sourced and run for real, against a state file in a temporary
# directory; the renderer is cut out of issue_sync and fed that file.
#
# Run it with: python3 tests/step-runs.py
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
github = open(os.path.join(LIB, "github.sh"), encoding="utf-8").read()

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def shell(wt, script):
    subprocess.run(
        ["bash", "-c", 'source "$1/state.sh"; source "$1/steps.sh"; wt="$2"; ' + script,
         "_", LIB, wt],
        check=True)


def render(state_path):
    body = re.search(r"body=\"\$\(SCLAUDE_STEPS=.*?<<'PY'[^\n]*\n(.*?)\nPY\n", github, re.S).group(1)
    spec = "plan=planning\ncode=development\npr=pull request\nreview=review\n"
    out = subprocess.run([sys.executable, "-", state_path], input=body, text=True,
                         capture_output=True, env={**os.environ, "SCLAUDE_STEPS": spec},
                         check=True).stdout
    return [line for line in out.splitlines() if line.startswith("| ") and "Step |" not in line]


with tempfile.TemporaryDirectory() as wt:
    os.makedirs(os.path.join(wt, ".feature"))
    path = os.path.join(wt, ".feature", "state.json")
    with open(path, "w") as fh:
        json.dump({"feature": "x", "step": "review", "steps": {
            # From before `runs`: its session is taken as the first run, with
            # the start the step already recorded.
            "code": {"session": "c0000000-old", "started": "2026-09-30T10:00:00+00:00"},
        }}, fh)

    shell(wt, '''
        step_run "$wt" code open c0000000-old
        step_run "$wt" code end c0000000-old
        step_run "$wt" code open c0000000-old
        step_run "$wt" code end c0000000-old
        step_run "$wt" code close
        step_run "$wt" review open r1111111
        step_run "$wt" review end r1111111
        step_run "$wt" review open r2222222
        step_run "$wt" review drop r2222222
        step_run "$wt" review open r3333333
    ''')
    with open(path) as fh:
        s = json.load(fh)
    code_runs = s["steps"]["code"]["runs"]
    check("same-session-is-one-run", len(code_runs), 1)
    check("first-start-kept", code_runs[0]["started"], "2026-09-30T10:00:00+00:00")
    check("close-marks-last-run", code_runs[0].get("done"), True)
    check("stillborn-session-dropped",
          [r["session"] for r in s["steps"]["review"]["runs"]], ["r1111111", "r3333333"])

    # The merge closes the review the preview fix reopened.
    shell(wt, 'state_set "$wt/.feature/state.json" reopened_by preview; step_close_merged "$wt"')
    rows = render(path)
    titles = [r.split("|")[1].strip() for r in rows]
    check("one-row-per-session",
          titles, ["planning", "development", "pull request", "review (1)", "review (2)"])
    statuses = [r.split("|")[2].strip() for r in rows]
    check("statuses", statuses[3:], ["interrupted", "done"])
    check("closed-review-has-end", rows[4].split("|")[5].strip() != "—", True)

    # What the automatic review handed each review session: those open when
    # it began, plus every thread opened while it ran — a session can carry on
    # through several rounds. The fake answers "<open> <opened since>".
    fake = os.path.join(wt, "fakelib")
    os.makedirs(fake)
    with open(os.path.join(fake, "pr_context.py"), "w") as fh:
        fh.write("import os, sys\n"
                 "assert sys.argv[1] == '--threads' and sys.argv[5]\n"
                 "print(os.environ.get('THREADS', ''))\n")

    def comments(session, answer):
        subprocess.run(["bash", "-c",
                        'source "$1/state.sh"; source "$1/steps.sh"; LIB="$3"; '
                        'gh_repo() { echo o/r; }; THREADS="$5" run_comments "$2" "$4" 143',
                        "_", LIB, wt, fake, session, answer], check=True)

    comments("r1111111", "5 0")   # opens on five
    comments("r1111111", "3 4")   # two fixed, four new in the next round
    comments("r3333333", "1 0")
    comments("r3333333", "")      # unreadable: the count stays
    titles = [r.split("|")[1].strip() for r in render(path)]
    check("comments-shown", titles[3:], ["review (1) - 9 comments", "review (2) - 1 comment"])

    # A friction review that stalled and was started again: both are named in
    # the cell, the stalled one first.
    shell(wt, '''
        f="$wt/.feature/state.json"
        session_runs "$f" friction.review open s1111111
        session_runs "$f" friction.review stall s1111111
        session_runs "$f" friction.review open s2222222
        session_runs "$f" friction.review finish s2222222 fixed
        state_set "$f" friction.review.done true
        state_set "$f" friction.review.was s2222222
        state_set "$f" friction.review.fixed true
        session_runs "$f" epilogue open e1111111
        session_runs "$f" epilogue finish e1111111
        session_runs "$f" epilogue open e2222222
        session_runs "$f" epilogue drop e2222222
    ''')
    rows = render(path)
    review_row = [r for r in rows if r.startswith("| review (2)")][0]
    check("friction-cell-names-every-review", review_row.split("|")[6].strip(),
          "`s1111111` stalled<br>`s2222222` fixed")
    # A stalled transcript still exists, so the next attempt resumes the same
    # conversation: one run, and no longer stalled once it has finished.
    shell(wt, '''
        f="$wt/.feature/state.json"
        session_runs "$f" friction.fix-preview-1 open t1111111
        session_runs "$f" friction.fix-preview-1 stall t1111111
        session_runs "$f" friction.fix-preview-1 open t1111111
        session_runs "$f" friction.fix-preview-1 finish t1111111 reviewed
    ''')
    with open(path) as fh:
        resumed = json.load(fh)["friction"]["fix-preview-1"]["runs"]
    check("resumed-stall-is-one-run", len(resumed), 1)
    check("resumed-stall-cleared", resumed[0].get("stalled"), None)
    check("resumed-stall-outcome", resumed[0].get("outcome"), "reviewed")

    status_rows = [r for r in rows if r.startswith("| status update")]
    check("epilogue-is-a-row", len(status_rows), 1)
    check("epilogue-row-done", status_rows[0].split("|")[2].strip(), "done")


# --- a friction review per session -----------------------------------------
#
# The key names the session by its row: `review-2` is the second run of the
# review step. Every ended session has one; the running one is queued; a
# step-wide key from before is shown on the last row only, and never on a row
# still running — that is how #125's live seventh round read `nothing`.
def sh_out(wt, script):
    return subprocess.run(
        ["bash", "-c", 'source "$1/state.sh"; source "$1/steps.sh"; wt="$2"; ' + script,
         "_", LIB, wt], check=True, capture_output=True, text=True).stdout.strip()


with tempfile.TemporaryDirectory() as wt:
    os.makedirs(os.path.join(wt, ".feature"))
    path = os.path.join(wt, ".feature", "state.json")
    with open(path, "w") as fh:
        json.dump({"feature": "x", "step": "review", "steps": {},
                   "friction": {"review": {"empty": True}}}, fh)
    shell(wt, '''
        step_run "$wt" code open c1111111
        step_run "$wt" code end c1111111
        step_run "$wt" code close
        step_run "$wt" review open r1111111
        step_run "$wt" review end r1111111 "fixes confirmed"
        step_run "$wt" review open r2222222
        step_run "$wt" review end r2222222 "fixes confirmed"
        step_run "$wt" review open r3333333
    ''')
    f = "$wt/.feature/state.json"
    check("key-of-session", sh_out(wt, 'step_run_key "%s" review r2222222' % f), "review-2")
    check("key-of-latest", sh_out(wt, 'step_run_key "%s" review' % f), "review-3")
    check("key-without-runs", sh_out(wt, 'step_run_key "%s" plan' % f), "plan")
    check("session-of-key", sh_out(wt, 'step_run_session "%s" review-1' % f), "r1111111")
    check("session-of-fix-key", sh_out(wt, 'step_run_session "%s" fix-preview-1' % f), "")
    check("last-run-key", sh_out(wt, 'last_run_key "%s"' % f), "review-3")

    # Legacy only: the step-wide `nothing` must not reach the running round.
    cells = {r.split("|")[1].strip(): r.split("|")[6].strip() for r in render(path)}
    check("legacy-running-row-queued", cells["review (3)"], "queued")
    check("legacy-earlier-row-dash", cells["review (1)"], "—")

    shell(wt, '''
        f="$wt/.feature/state.json"
        state_set "$f" friction.review-1.empty true
        state_set "$f" friction.review-2.done true
        state_set "$f" friction.review-2.was s2222222
        state_set "$f" friction.review-2.fixed true
        state_set "$f" friction.code-1.empty true
    ''')
    cells = {r.split("|")[1].strip(): r.split("|")[6].strip() for r in render(path)}
    check("per-run-empty", cells["review (1)"], "nothing")
    check("per-run-fixed", cells["review (2)"], "`s2222222` fixed")
    check("per-run-running-queued", cells["review (3)"], "queued")
    check("per-run-single-row-step", cells["development"], "nothing")

for name, want, got in failures:
    print("FAIL %s\n  expected: %r\n  got:      %r" % (name, want, got))
if failures:
    print("\n%d check(s) failed." % len(failures))
    sys.exit(1)
print("All checks passed.")
