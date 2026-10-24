#!/usr/bin/env python3
#
# The plan, printed in the orchestrator's terminal (plan_report in run.sh).
#
# A session's last message is printed once it is closed, and that message is
# not the plan: step 1 ends with a report about it. Guarded here:
#
#   * after step 1 the approved plan is printed whole, and printed again after
#     a replan even when its text is the same;
#   * after a later session nothing is printed while .sclaude/local/feature/plan.md is the
#     plan printed last;
#   * a later session that changed the plan gets it printed, under a headline
#     saying it changed, and only once;
#   * a feature with no record of a printed plan prints nothing and starts one;
#   * plan_report runs in session_ended, on both ways out of a session.
#
# Run it with: python3 tests/plan-report.py
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()
found = re.search(r"^plan_report\(\) \{\n.*?^\}\n", RUN, re.S | re.M)
if not found:
    print("FAIL plan_report not found in run.sh")
    sys.exit(1)

# capture_plan is stubbed: it writes the approved plan from $APPROVED, or fails
# when there is none, as the real one does without an approval.
PRELUDE = """
BOLD=""; OFF=""
say() { printf '%s\\n' "$*"; }
ask_note() { :; }
say_here() { printf '%s\\n' "$*"; }
ask_feed() { printf '%s\\n' "$2" >> "$FEED"; }
capture_plan() {
  [[ -n "${APPROVED:-}" ]] || return 1
  printf '%s\\n' "$APPROVED" > "$1/.sclaude/local/feature/plan.md"
}
"""


FEED = os.path.join(tempfile.mkdtemp(), "feed")


def fed():
    # What the topic was told since the last call.
    try:
        with open(FEED) as fh:
            said = fh.read()
    except OSError:
        said = ""
    open(FEED, "w").close()
    return said


def report(wt, step, approved=""):
    env = dict(os.environ, APPROVED=approved, FEED=FEED)
    body = PRELUDE + found.group(0) + 'plan_report "%s" "%s"\n' % (wt, step)
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                          env=env, timeout=30).stdout


with tempfile.TemporaryDirectory() as tmp:
    wt = os.path.join(tmp, "wt")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    plan = os.path.join(wt, ".sclaude/local/feature", "plan.md")

    # --- no approval in step 1: nothing to print -----------------------------
    check("plan-unapproved-silent", report(wt, "plan"), "")

    # --- step 1 prints the approved plan -------------------------------------
    out = report(wt, "plan", "# Plan\n\n- do it")
    check("plan-headline", "Approved plan" in out, True)
    check("plan-body-indented", "  # Plan\n" in out and "  - do it\n" in out, True)
    # The topic gets the fact, not a path to a file it cannot open.
    check("plan-approved-told", fed(), "Plan approved\n")

    # --- a later session that left it alone prints nothing -------------------
    check("code-unchanged-silent", report(wt, "code"), "")

    # --- a later session that changed it ------------------------------------
    with open(plan, "a") as fh:
        fh.write("- and this too\n")
    out = report(wt, "code")
    check("changed-headline", "Plan changed" in out, True)
    check("changed-body", "  - and this too\n" in out, True)
    check("changed-told-by-size", fed(), "Plan changed · +1 −0 lines\n")
    check("changed-only-once", report(wt, "review"), "")

    # --- a replan prints the plan again, even unchanged ----------------------
    out = report(wt, "plan", "# Plan\n\n- do it")
    check("replan-prints-again", "Approved plan" in out, True)

    # --- a feature from before the record: silent, then tracked -------------
    os.remove(os.path.join(wt, ".sclaude/local/feature", "plan.printed"))
    check("no-record-silent", report(wt, "code"), "")
    check("no-record-started", os.path.exists(os.path.join(wt, ".sclaude/local/feature", "plan.printed")), True)
    with open(plan, "a") as fh:
        fh.write("- one more\n")
    check("tracked-after-start", "Plan changed" in report(wt, "code"), True)

# --- wired into session_ended, on both ways out ------------------------------
ended = re.search(r"^session_ended\(\) \{\n.*?^\}\n", RUN, re.S | re.M).group(0)
check("called-twice-in-session-ended", ended.count('plan_report "$wt" "$step"'), 2)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
