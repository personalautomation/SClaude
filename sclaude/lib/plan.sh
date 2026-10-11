#!/usr/bin/env bash
#
# Step 1's plan — from its own session's transcript.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Step 1's plan — from its own session's transcript, into .feature/plan.md.
#
# Step 1 cannot write the file itself: it runs in plan mode, and that forbids
# writing before any permissions are even considered. But the plan goes outside
# anyway — the confirmation dialogue shows it, and it stays in the transcript as
# an ExitPlanMode call. That is where we take it from, thereby leaving the mode
# alone.
#
# We take the last APPROVED call rather than the last one at all. Presenting a
# plan several times is an everyday thing: the human reads it, rejects it, asks
# for a rework. A rejected call is a draft, and it differs from the outcome
# beyond recognition.
#
# The file already exists by this moment: the plan-on-disk hook puts every
# presented plan there so that there is something to read it with while the
# dialogue covers the screen. Here it is overwritten with the approved one — the
# only one the human accepted, and which will therefore go on as step 2's
# assignment.
#
# A non-zero code means "there was no approved plan in this session": the step
# then does not close, rather than closing with an empty bridge to step 2.
capture_plan() {
  local wt="$1" session
  session="$(state_get "$wt/.feature/state.json" steps.plan.session)" || return 1
  [[ -n "$session" ]] || return 1

  python3 - "$wt" "$session" "$LIB" <<'PY'
import json
import os
import sys

wt, session = sys.argv[1], sys.argv[2]
sys.path.insert(0, sys.argv[3])
from presented_plan import plan_text

# The project's directory in ~/.claude/projects — the path with everything but
# letters and digits replaced by a hyphen. Verified against every directory on
# this machine.
encoded = "".join(c if c.isalnum() else "-" for c in wt)
transcript = os.path.expanduser(
    os.path.join("~/.claude/projects", encoded, session + ".jsonl")
)

try:
    with open(transcript) as fh:
        lines = fh.readlines()
except OSError:
    sys.exit(1)

# The approval is visible not in the call itself but in its result — in the next
# tool_result block. So we go through the file in order: we remember a presented
# call and accept it only when an approval arrives right after.
#
# There are two wordings of approval, and the second occurs exactly when the plan
# is empty: "approved your plan" against "approved exiting plan mode". We catch
# both by their common part, otherwise an approved step looks unclosed.
#
# The plan may not be in the call at all. ExitPlanMode has stopped accepting it
# as a parameter — it reads a file whose path it puts into planFilePath — so an
# empty input is not a failure but the current norm. presented_plan reads it
# the same way the hook on ExitPlanMode does.
approved = None
pending = None
for line in lines:
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        continue
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("name") == "ExitPlanMode" and block.get("type") == "tool_use":
            pending = block.get("input") or {}
        elif block.get("type") == "tool_result" and pending is not None:
            if "has approved" in str(block.get("content")):
                approved = pending
            pending = None

if approved is None:
    sys.exit(1)

plan = plan_text(approved)

# There was an approval but no text: the plan lay in a file that was not kept.
# The step must not be closed with an empty bridge to step 2 — better that it
# does not close.
if not plan or not plan.strip():
    sys.exit(1)

target = os.path.join(wt, ".feature", "plan.md")
os.makedirs(os.path.dirname(target), exist_ok=True)
with open(target, "w") as fh:
    fh.write(plan if plan.endswith("\n") else plan + "\n")
PY
}
