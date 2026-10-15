#!/usr/bin/env python3
#
# qa_wait: what sclaude does while QA has the feature.
#
# The end of the cycle is review → preview → QA → merge. qa_wait is the step in
# the middle: it watches the issue's column and decides what a move means.
# Done is a pass, In progress or Backlog is a hand-back, and any other column
# is unexpected — the person is asked to fix the status, and the wait goes on.
#
# The column is scripted: issue_status_now is replaced by a function that
# answers one line of a file per call and repeats the last line. `sleep` is a
# no-op, so a wait of many polls runs in no time. Everything else is the real
# deploy.sh and watch.sh.
#
# Run it with: python3 tests/qa-wait.py
import json
import os
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


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def run(tmp, columns, watch=None, unticked="", board=True, names=None,
        merged_after=None, extra=""):
    """Run qa_wait over a scripted sequence of columns.

    Returns (stdout + stderr, exit code, watch file contents or None).
    """
    home = os.path.join(tmp, "home")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home)
    seq = os.path.join(tmp, "columns")
    if os.path.exists(seq + ".calls"):
        os.remove(seq + ".calls")
    with open(seq, "w") as fh:
        fh.write("\n".join(columns) + "\n")
    watch_file = os.path.join(home, ".claude", "sclaude", "watch", "demo.json")
    if watch is not None:
        os.makedirs(os.path.dirname(watch_file))
        with open(watch_file, "w") as fh:
            json.dump(watch, fh)

    # A stand-in for acceptance.py: qa_wait asks it which criteria are
    # unticked, and the real one reaches GitHub.
    fake_lib = os.path.join(tmp, "lib")
    os.makedirs(fake_lib, exist_ok=True)
    with open(os.path.join(fake_lib, "acceptance.py"), "w") as fh:
        fh.write("import sys\nsys.stdout.write(%r)\n" % unticked)

    backlog, progress, qa, done = names or ("Backlog", "In progress", "In QA", "Done")
    board_vars = ('PROGRESS_FROM="%s"; QA_FROM="%s"; QA_TO="%s"; QA_DONE="%s"\n'
                  % (backlog, progress, qa, done)) if board else \
                 'PROGRESS_FROM=""; QA_FROM=""; QA_TO=""; QA_DONE=""\n'
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
    for name in ("io", "ui", "steps", "state", "project", "watch", "deploy"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('warn() { echo "$*"; }\n'
             'info() { echo "$*"; }\n'
             'say()  { echo "$*"; }\n'
             'sleep() { :; }\n'
             'regression_duration() { echo "${1}s"; }\n'
             'SELF=sclaude; REPO=.\n'
             'LIB="%s"\n' % fake_lib)
    body += board_vars
    # One line per call; the last line repeats, so a sequence that ends in a
    # column the wait never leaves would spin — the timeout below catches it.
    body += '''
issue_status_now() {
  local first
  first="$(head -n 1 "%s")"
  if [[ "$(wc -l < "%s")" -gt 1 ]]; then
    sed -i 1d "%s"
  fi
  printf '%%s\\n' "$first"
}
# Called in a command substitution, so the count lives in a file: a variable
# would be incremented in a subshell and never seen again.
branch_pr_state() {
  local n; n=$(( $(cat "%s.calls" 2>/dev/null || echo 0) + 1 ))
  echo "$n" > "%s.calls"
  if [[ -n "%s" && "$n" -ge "%s" ]]; then echo MERGED; else echo OPEN; fi
}
%s
qa_wait demo 71 208 feat/demo
echo "rc=$?"
''' % (seq, seq, seq, seq, seq, merged_after or "", merged_after or 0, extra)
    env = dict(os.environ, HOME=home, QA_POLL="1")
    try:
        out = subprocess.run(["bash", "-c", body], capture_output=True,
                             text=True, timeout=30, env=env)
        text = out.stdout + out.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None, None
    rc = None
    for line in text.splitlines():
        if line.startswith("rc="):
            rc = int(line[3:])
    try:
        with open(watch_file) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = None
    return text, rc, state


tmp = tempfile.mkdtemp()
try:
    armed = {"feature": "demo", "issue": 71, "status": "In QA"}

    # --- QA accepts ----------------------------------------------------------
    out, rc, state = run(tmp, ["In QA", "In QA", "Done"], watch=dict(armed))
    check("accept-returns-zero", rc, 0)
    check_true("accept-announces-the-wait", "Waiting for QA on issue #71" in out)
    check_true("accept-names-the-criteria", "acceptance criteria" in out)
    check_true("accept-says-qa-accepted", "QA accepted issue #71" in out)
    check_true("accept-says-the-merge-is-next",
               "Now waiting for the merge of PR #208" in out)
    # The timer must not announce the same pass a second time.
    check("accept-marks-the-watch", (state or {}).get("status"), "Done")
    check_true("accept-no-unticked-warning-when-all-ticked", "not ticked" not in out)

    # Unticked criteria are a warning, not a gate.
    out, rc, _ = run(tmp, ["In QA", "Done"], watch=dict(armed), unticked="AC2, AC5")
    check("unticked-still-passes", rc, 0)
    check_true("unticked-are-named", "but not ticked: AC2, AC5" in out)

    # Already in Done on arrival: the merge question says it, so this is quiet.
    out, rc, _ = run(tmp, ["Done"], watch=dict(armed))
    check("already-done-returns-zero", rc, 0)
    check_true("already-done-is-quiet", "Waiting for QA" not in out)

    # A pass the timer got to first is answered here too.
    out, rc, state = run(tmp, ["Done"], watch=dict(armed, verdict="done"))
    check("timer-pass-cleared", (state or {}).get("verdict"), None)

    # --- QA hands it back ----------------------------------------------------
    for back in ("In progress", "Backlog"):
        out, rc, _ = run(tmp, ["In QA", "In QA", back], watch=dict(armed))
        check("hand-back-to-%s" % back, rc, 2)
        check_true("hand-back-to-%s-not-unexpected" % back, "unexpected" not in out)

    # The timer saw the hand-back first: the column already reads In progress,
    # and the recorded one does too. The verdict is what says it was a return.
    out, rc, _ = run(tmp, ["In progress"],
                     watch=dict(armed, status="In progress", verdict="returned"))
    check("timer-hand-back-returns-two", rc, 2)

    # --- an unexpected column ------------------------------------------------
    out, rc, _ = run(tmp, ["In QA", "Review", "Review", "Review", "Done"],
                     watch=dict(armed))
    check("unexpected-then-done", rc, 0)
    check("unexpected-said-once", out.count("unexpected while waiting for QA"), 1)
    check_true("unexpected-names-the-column", "Issue #71 is in 'Review'" in out)
    check_true("unexpected-asks-for-a-fix", "Please set the ticket status" in out)
    check_true("unexpected-names-both-back-columns",
               "'In progress' or 'Backlog'" in out)

    # From an unexpected column back to In progress is still a hand-back.
    out, rc, _ = run(tmp, ["In QA", "Review", "In progress"], watch=dict(armed))
    check("unexpected-then-back", rc, 2)

    # Put back into QA after an unexpected move: said, and the wait goes on.
    out, rc, _ = run(tmp, ["Review", "In QA", "Done"], watch=dict(armed))
    check("unexpected-then-qa-then-done", rc, 0)
    check_true("back-in-qa-said", "is back in 'In QA'" in out)

    # An issue that never reached QA (the move did not go through) is not a
    # hand-back: the watch recorded In progress when it was armed.
    out, rc, _ = run(tmp, ["In progress", "In progress", "In QA", "Done"],
                     watch=dict(armed, status="In progress"))
    check("never-in-qa-is-not-a-hand-back", rc, 0)
    check_true("never-in-qa-is-unexpected", "unexpected while waiting for QA" in out)

    # --- column names are not case-sensitive ---------------------------------
    #
    # The names in .sclaude/config.json are typed apart from the board. "done" in the
    # config and "Done" on the board are the same column.
    odd = ("BACKLOG", " in progress ", "in qa", "done")
    out, rc, _ = run(tmp, ["In QA", "Done"], watch=dict(armed), names=odd)
    check("case-done", rc, 0)
    check_true("case-done-not-unexpected", "unexpected" not in out)
    out, rc, _ = run(tmp, ["In QA", "In Progress"], watch=dict(armed), names=odd)
    check("case-hand-back", rc, 2)
    out, rc, _ = run(tmp, ["In QA", "backlog"], watch=dict(armed), names=odd)
    check("case-hand-back-backlog", rc, 2)

    # column_is itself: case and surrounding spaces ignored, empty never equal.
    def column_is(a, b):
        body = 'source "%s/project.sh"\ncolumn_is "$1" "$2"\n' % LIB
        return subprocess.run(["bash", "-c", body, "x", a, b],
                              capture_output=True).returncode == 0
    check("column-is-case", column_is("In QA", "in qa"), True)
    check("column-is-spaces", column_is(" Done ", "done"), True)
    check("column-is-different", column_is("In QA", "Done"), False)
    check("column-is-empty", column_is("", ""), False)
    check("column-is-one-empty", column_is("Done", ""), False)

    # --- merged while QA had it ---------------------------------------------
    out, rc, _ = run(tmp, ["In QA"] * 5, watch=dict(armed), merged_after=2)
    check("merge-during-qa-returns-three", rc, 3)

    # --- nothing to wait for -------------------------------------------------
    out, rc, _ = run(tmp, ["In QA"], watch=dict(armed), board=False)
    check("no-board-returns-zero", rc, 0)
    check_true("no-board-is-quiet", "Waiting for QA" not in out)

    # gh silent: nothing known is not a column, and not a reason to wait.
    out, rc, _ = run(tmp, [""], watch=dict(armed))
    check("no-answer-returns-zero", rc, 0)

    # gh silent in the middle of a wait is not a change.
    out, rc, _ = run(tmp, ["In QA", "", "", "Done"], watch=dict(armed))
    check("silence-mid-wait-keeps-waiting", rc, 0)
    check_true("silence-is-not-unexpected", "unexpected" not in out)

    # --- accepted from sclaude (`qa`) ---------------------------------------
    #
    # The board move is stubbed: it records itself, and the column read after
    # it is what the scripted sequence says next.
    moved = os.path.join(tmp, "moved")
    accept = ('''
qa_accept_here() { echo "accepted:$2" >> "%s"; [[ "${ACCEPT_FAILS:-}" ]] && return 1; return 0; }
''' % moved)

    def accepted():
        if not os.path.exists(moved):
            return []
        with open(moved) as fh:
            calls = fh.read().split()
        os.remove(moved)
        return calls

    out, rc, _ = run(tmp, ["In QA", "Done"], watch=dict(armed),
                     extra=accept + "project_flow_mode() { echo auto; }")
    check("auto-returns-zero", rc, 0)
    check("auto-accepts-once", accepted(), ["accepted:auto"])
    check_true("auto-says-so", "qa` is auto" in out)
    check_true("auto-does-not-wait", "Waiting for QA" not in out)

    out, rc, _ = run(tmp, ["In QA", "In QA", "Done"], watch=dict(armed),
                     extra=accept + "ACCEPT_FAILS=1; project_flow_mode() { echo auto; }")
    check("auto-refused-waits-for-the-board", rc, 0)
    check("auto-refused-tried-once", accepted(), ["accepted:auto"])
    check_true("auto-refused-says-so", "waiting for QA on the board instead" in out)

    # With `both`, a pressed and confirmed accepts; github ignores the key.
    keyed = accept + '''
poll_pause() { POLL_KEY=a; }
qa_accept_offer() { return 0; }
'''
    out, rc, _ = run(tmp, ["In QA", "Done"], watch=dict(armed),
                     extra=keyed + "project_flow_mode() { echo both; }")
    check("both-key-accepts", accepted(), ["accepted:key"])
    check_true("both-names-the-key", "press a here" in out)
    out, rc, _ = run(tmp, ["In QA", "Done"], watch=dict(armed),
                     extra=keyed + "project_flow_mode() { echo github; }")
    check("github-ignores-the-key", accepted(), [])
    check_true("github-does-not-name-the-key", "press a here" not in out)

finally:
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
