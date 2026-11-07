#!/usr/bin/env python3
#
# A feature planned as several pull requests (sclaude/prompts/plan.md, "If I
# choose to split").
#
# The orchestrator runs one pull request per feature. Step 1 used to be told
# to propose a split above a size and nothing after that: a plan came out with
# every part's criteria marked by part, and step 2 had nothing to say it should
# build only the first. Guarded here:
#
#   * step 1 is told that the feature becomes the first part alone and that
#     each later part is filed as an issue of its own, a sub-issue of the
#     feature's issue when it has one;
#   * step 2 is told to build only the first part of a plan that still holds
#     several, and to file the later parts the same way;
#   * the struck form step 2 is shown for a later part's criterion is one
#     plan_criteria drops: struck after the identifier, the line still read
#     as a live criterion and was added back to the issue;
#   * both prompts render with and without an issue, and the sub-issue command
#     names the feature's issue only when there is one.
#
# Run it with: python3 tests/plan-split.py
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PROMPTS = os.path.join(ROOT, "sclaude", "prompts")
RENDER = os.path.join(ROOT, "sclaude", "lib", "cycle", "render_prompt.py")

failures = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def render(step, issue):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SCLAUDE_V_", "SCLAUDE_B_"))}
    env["SCLAUDE_V_FEATURE"] = "demo-feature"
    if issue:
        env["SCLAUDE_V_ISSUE"] = issue
    out = subprocess.run(
        [sys.executable, RENDER, os.path.join(PROMPTS, step + ".md"), PROMPTS],
        env=env, capture_output=True, text=True)
    check("%s.md renders %s an issue" % (step, "with" if issue else "without"),
          out.returncode == 0)
    return out.stdout


SUB = "issues/41/sub_issues"
CREATE = "gh issue create"

for step, lead in (("plan", "this feature becomes the first part, and only that"),
                   ("code", "This feature is one pull request.")):
    with_issue = render(step, "41")
    without = render(step, "")
    check("%s.md says the feature is one pull request" % step, lead in with_issue)
    check("%s.md files a later part as an issue" % step,
          CREATE in with_issue and CREATE in without)
    check("%s.md makes it a sub-issue of the feature's issue" % step,
          SUB in with_issue)
    check("%s.md names no sub-issue without an issue" % step,
          "sub_issues" not in without)

sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib", "cycle"))
import acceptance  # noqa: E402

struck = re.search(r"`(- \[ \] ~~AC\d+\. …~~)`", render("code", "41"))
check("code.md shows a struck criterion", bool(struck))
if struck:
    got = acceptance.plan_criteria("- [ ] AC1. Kept.\n" + struck.group(1) + "\n")
    check("the struck form is not read as a criterion", got == [("AC1", "Kept.")])

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
