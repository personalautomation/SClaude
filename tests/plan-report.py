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
#   * a later session that changed the plan gets only the change printed —
#     the lines added and removed, under the heading they sit in — under a
#     headline saying how much changed, and only once;
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


with open(os.path.join(LIB, "cycle", "run.sh")) as fh:
    RUN = fh.read()
found = re.search(r"^plan_report\(\) \{\n.*?^\}\n", RUN, re.S | re.M)
if not found:
    print("FAIL plan_report not found in run.sh")
    sys.exit(1)
changes = re.search(r"^plan_changes\(\) \{\n.*?^\}\n", RUN, re.S | re.M)
if not changes:
    print("FAIL plan_changes not found in run.sh")
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
    body = PRELUDE + changes.group(0) + found.group(0) + 'plan_report "%s" "%s"\n' % (wt, step)
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
    check("changed-headline", "Plan changed (.sclaude/local/feature/plan.md) · +1 −0 lines:" in out, True)
    check("changed-line-added", "  +- and this too\n" in out, True)
    check("changed-context-kept", "   - do it\n" in out, True)
    check("changed-under-its-heading", "  # Plan\n   - do it\n  +- and this too\n" in out, True)
    check("changed-names-the-file", "The whole plan: .sclaude/local/feature/plan.md" in out, True)
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

    # --- a change is shown under its own section's heading --------------------
    with open(plan, "w") as fh:
        fh.write("# Plan\n\n## One\n\n- a\n- b\n- c\n\n## Two\n\n- d\n- e\n- f\n")
    report(wt, "code")
    fed()
    with open(plan, "w") as fh:
        fh.write("# Plan\n\n## One\n\n- a\n- b\n- c\n\n## Two\n\n- d\n- E\n- f\n")
    out = report(wt, "code")
    check("section-heading-above", "  ## Two\n   - d\n  -- e\n  +- E\n   - f\n" in out, True)
    check("section-other-left-out", "- b" in out, False)
    check("section-replaced-counts", "· +1 −1 lines:" in out, True)
    # A change right under a heading has that heading as its context line, so
    # the section before it is not named above it.
    with open(plan, "w") as fh:
        fh.write("# Plan\n\n## One\n- A\n")
    report(wt, "code")
    with open(plan, "w") as fh:
        fh.write("# Plan\n\n## One\n- B\n")
    out = report(wt, "code")
    check("heading-as-context", "   ## One\n  -- A\n  +- B\n" in out, True)
    check("heading-not-doubled", "  # Plan\n" in out, False)
    # The heading is the whole line, multi-byte characters and all — diff -F
    # would cut it to 40 bytes.
    long = "### Part 2 — Notifications in the topic and the terminal"
    with open(plan, "w") as fh:
        fh.write("# Plan\n\n%s\n\n- a\n- b\n- c\n" % long)
    report(wt, "code")
    with open(plan, "w") as fh:
        fh.write("# Plan\n\n%s\n\n- a\n- B\n- c\n" % long)
    check("heading-whole", "  %s\n   - a\n" % long in report(wt, "code"), True)
    # A comment in a fenced block is not a heading.
    fenced = "# Plan\n\n## Steps\n\n```\n# install deps\nnpm i\n```\n\n- a\n- %s\n- c\n"
    with open(plan, "w") as fh:
        fh.write(fenced % "b")
    report(wt, "code")
    with open(plan, "w") as fh:
        fh.write(fenced % "B")
    out = report(wt, "code")
    check("fence-not-a-heading", "  ## Steps\n   - a\n" in out, True)
    # No heading above the change: nothing is named above it.
    with open(plan, "w") as fh:
        fh.write("intro\n\n- a\n- b\n- c\n")
    report(wt, "code")
    with open(plan, "w") as fh:
        fh.write("intro\n\n- a\n- B\n- c\n")
    out = report(wt, "code")
    check("no-heading-no-label", out.split("lines:\n\n", 1)[-1].startswith("   - a\n"), True)

# --- wired into session_ended, on both ways out ------------------------------
ended = re.search(r"^session_ended\(\) \{\n.*?^\}\n", RUN, re.S | re.M).group(0)
check("called-twice-in-session-ended", ended.count('plan_report "$wt" "$step"'), 2)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
