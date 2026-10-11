#!/usr/bin/env python3
#
# pr_link_issue: a PR that GitHub failed to link to its issue gets linked by hand.
# issue_hold_open / issue_close_done: the issue stays open until the cycle ends.
#
# A pull request once ended with `Closes #N` and GitHub never linked them, so the
# merge would have left the issue open. These run the real function against a
# stubbed `gh` that logs every call, and assert on which calls were made.
#
# Run it with: python3 tests/pr_link.py
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def run(pr_state, linked, mutation_ok=True, issue="40", body="Closes #40"):
    """Run pr_link_issue once; return (gh call log, stderr+stdout)."""
    wt = tempfile.mkdtemp()
    os.makedirs(os.path.join(wt, ".feature"))
    with open(os.path.join(wt, ".feature", "state.json"), "w") as f:
        f.write('{"issue": %s}' % issue)
    log = os.path.join(wt, "gh-calls")
    script = f"""
set -uo pipefail
BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""
source "{LIB}/ui.sh"; source "{LIB}/state.sh"; source "{LIB}/github.sh"
info() {{ echo "$*"; }}; warn() {{ echo "$*" >&2; }}
gh_repo() {{ echo o/r; }}
gh() {{
  echo "$*" >> "{log}"
  case "$*" in
    "api repos/o/r/pulls/"*"--jq .body") printf '%s\n' "{body}" ;;
    "api repos/o/r/pulls/"*) echo "{pr_state} PR_NODE" ;;
    "pr view"*) printf '%s' "{linked}" ;;
    "api repos/o/r/issues/"*) echo ISSUE_NODE ;;
    "api graphql"*) {"return 0" if mutation_ok else "return 1"} ;;
  esac
}}
pr_link_issue "{wt}" 137
"""
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    calls = open(log).read() if os.path.exists(log) else ""
    return calls, out.stdout + out.stderr


def mutated(calls):
    return "addCloseIssueReferences" in calls


# Already linked by the keyword: nothing to do.
calls, _ = run("open", "40\n")
check("linked PR is left alone", mutated(calls), False)

# Linked to other issues but not ours: link it.
calls, out = run("open", "12\n")
check("unlinked PR gets the mutation", mutated(calls), True)
check("mutation carries both node ids",
      "i=ISSUE_NODE" in calls and "p=PR_NODE" in calls, True)
check("success is reported", "linked to issue #40 by hand" in out, True)

# `4` must not count as `40`, nor `400`.
calls, _ = run("open", "4\n400\n")
check("a prefix number is not a match", mutated(calls), True)

# `Refs #40` and nothing closing it: a choice (a follow-up to a shipped issue), left unlinked.
calls, out = run("open", "", body="Follow-up.\n\nRefs #40")
check("refs-only is left unlinked", mutated(calls), False)
check("refs-only says so", "without closing it" in out, True)
# `Refs #400` is not about #40, and `Closes` beside `Refs` still links.
calls, _ = run("open", "", body="Refs #400")
check("refs to another number still links", mutated(calls), True)
calls, _ = run("open", "", body="Refs #40\nCloses #40")
check("refs with closes still links", mutated(calls), True)

# A merged or closed PR: the link would come too late to matter.
calls, _ = run("closed", "")
check("closed PR is skipped", mutated(calls), False)

# The mutation fails: a warning, not a failure.
calls, out = run("open", "", mutation_ok=False)
check("failure warns", "linking it failed" in out, True)

# No issue in the state: gh is never asked.
calls, _ = run("open", "", issue="null")
check("no issue, no calls", calls, "")



def run_issue(func, state, reason="completed", ok=True, args=""):
    """Run issue_hold_open or issue_close_done on #40; return (calls, output)."""
    log = os.path.join(tempfile.mkdtemp(), "gh-calls")
    script = f"""
set -uo pipefail
BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""
source "{LIB}/ui.sh"; source "{LIB}/state.sh"; source "{LIB}/github.sh"
info() {{ echo "$*"; }}; warn() {{ echo "$*" >&2; }}
gh_repo() {{ echo o/r; }}
gh() {{
  echo "$*" >> "{log}"
  case "$*" in
    "api repos/o/r/issues/40 --jq .state") echo {state} ;;
    "api repos/o/r/issues/40"*) [[ {state} == closed && {reason} == completed ]] && echo yes ;;
    "issue "*) {"return 0" if ok else "return 1"} ;;
  esac
}}
{func} 40 {args}
"""
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    calls = open(log).read() if os.path.exists(log) else ""
    return calls, out.stdout + out.stderr


# Closed early by the board or the merge: reopened.
calls, out = run_issue("issue_hold_open", "closed")
check("completed close is undone", "issue reopen 40" in calls, True)
check("reopen is reported", "Issue #40 reopened" in out, True)

# Closed as not planned (abandon): left alone.
calls, _ = run_issue("issue_hold_open", "closed", reason="not_planned")
check("not-planned close is kept", "issue reopen" in calls, False)

# Open: nothing to do.
calls, _ = run_issue("issue_hold_open", "open")
check("open issue is not reopened", "issue reopen" in calls, False)

# Reopen fails: a warning.
calls, out = run_issue("issue_hold_open", "closed", ok=False)
check("failed reopen warns", "reopening it failed" in out, True)

# The end of the cycle closes an open issue as completed.
calls, out = run_issue("issue_close_done", "open")
check("cycle end closes", "issue close 40 --repo o/r --reason completed" in calls, True)

# Production declined: the issue closes all the same, and says so.
calls, out = run_issue("issue_close_done", "open", args="declined")
check("declined closes", "issue close 40 --repo o/r --reason completed" in calls, True)
check("declined says so", "production was declined" in out, True)

# Already closed: not closed twice.
calls, _ = run_issue("issue_close_done", "closed")
check("closed issue is not closed again", "issue close" in calls, False)

if failures:
    for name, want, got in failures:
        print(f"FAIL {name}: want {want!r}, got {got!r}")
    sys.exit(1)
print("ok")
