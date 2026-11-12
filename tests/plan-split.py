#!/usr/bin/env python3
#
# A feature planned in parts (sclaude/prompts/plan.md, "If I choose to split").
#
# A feature too big to build and show in one go is split at step 1, at the
# person's word. It stays one issue, one plan, one pull request and one QA,
# and is built in parts inside step 2 (parts.sh). An earlier way made the first part the feature and filed the
# rest as issues of their own: preview, QA, the demo and production then ran
# once per part, and main got each part on its own. Guarded here:
#
#   * step 1 is told the feature stays one, to write the `## Parts` section in
#     the shape plan_parts.py reads and to mark each criterion's part, and to
#     file no issue for a part — with an issue, to bring back parts an
#     earlier session filed as sub-issues;
#   * what step 1 is shown as the shape is what plan_parts.py reads;
#   * step 2, inside a part, builds that part alone, and is not told to file
#     anything or strike criteria;
#   * both prompts render with and without an issue.
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


def render(step, issue, in_part=False):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SCLAUDE_V_", "SCLAUDE_B_"))}
    env["SCLAUDE_V_FEATURE"] = "demo-feature"
    env["SCLAUDE_V_BASE"] = "feat/demo" if in_part else "main"
    if in_part:
        env.update(SCLAUDE_V_IN_PARTS="1", SCLAUDE_V_PART="2", SCLAUDE_V_PARTS="3",
                   SCLAUDE_V_PART_TITLE="Tickets page", SCLAUDE_V_UMBRELLA="feat/demo")
    else:
        env["SCLAUDE_V_NOT_IN_PARTS"] = "1"
    if issue:
        env["SCLAUDE_V_ISSUE"] = issue
    out = subprocess.run(
        [sys.executable, RENDER, os.path.join(PROMPTS, step + ".md"), PROMPTS],
        env=env, capture_output=True, text=True)
    check("%s.md renders %s an issue%s" % (step, "with" if issue else "without",
                                           " in a part" if in_part else ""),
          out.returncode == 0)
    return out.stdout


LEAD = "the feature stays one: one issue, one plan, one pull request, one QA"
for issue in ("41", ""):
    plan = render("plan", issue)
    check("plan.md says the feature stays one (%s)" % (issue or "no issue"), LEAD in plan)
    check("plan.md files no issue for a part (%s)" % (issue or "no issue"),
          "gh issue create" not in plan and "sub_issues" not in plan.replace("sub-issues", ""))
    check("plan.md asks for the parts section and each criterion's part (%s)" % (issue or "no issue"),
          "`## Parts`" in plan and "`### Part <n> — <title>`" in plan
          and "`- [ ] AC7. [part 2] …`" in plan)
check("plan.md brings back parts filed as issues, with an issue",
      "sub-issues of #41" in render("plan", "41"))
check("plan.md names no sub-issue without an issue",
      "sub-issues" not in render("plan", ""))

# What step 1 is shown is what the orchestrator reads.
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib"))
import _path  # noqa: E402,F401
import acceptance  # noqa: E402
import plan_parts  # noqa: E402

shown = render("plan", "41")
heading = re.search(r"`(### Part <n> — <title>)`", shown).group(1)
example = "## Parts\n\n%s\n\n%s\n" % (heading.replace("<n>", "1").replace("<title>", "One"),
                                     heading.replace("<n>", "2").replace("<title>", "Two"))
check("the heading step 1 is shown is read", plan_parts.plan_parts(example) == [(1, "One"), (2, "Two")])
criterion = re.search(r"`(- \[ \] AC7\. \[part 2\] …)`", shown).group(1)
found = acceptance.plan_criteria(criterion.replace("…", "Lists tickets.") + "\n")
check("the criterion step 1 is shown names its part",
      [plan_parts.criterion_part(t) for _, t in found] == [2])

for issue in ("41", ""):
    code = render("code", issue, in_part=True)
    check("code.md in a part builds that part alone (%s)" % (issue or "no issue"),
          "this session builds part 2 of 3: Tickets page" in code)
    check("code.md files nothing and strikes nothing (%s)" % (issue or "no issue"),
          "gh issue create" not in code and "~~AC" not in code)
check("code.md outside the parts says nothing of them",
      "builds part" not in render("code", "41"))

if failures:
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
