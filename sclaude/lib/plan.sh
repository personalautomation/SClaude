#!/usr/bin/env bash
#
# Step 1's plan — from its own session's transcript.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Step 1's plan — from its own session's transcript, into .sclaude/local/feature/plan.md.
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
#
# One more approval is not in the transcript: [n] or [N] pressed in sclaude's
# tab while the plan dialog was open (session_take_as_done in run.sh), which
# marks the step's gate. The session was closed with the call unanswered, and
# that call, the last thing in the conversation, is the plan approved. A call
# the hook on ExitPlanMode refused has its answer, and is not taken. An answer
# written once the key closed the session (`steps.plan.taken_at`, the
# watcher's marker's time) does not count: Claude Code may record the open
# call as interrupted as it goes, and that is the closing, not a refusal.
capture_plan() {
  local wt="$1" session pending=""
  local state="$wt/.sclaude/local/feature/state.json"
  session="$(state_get "$state" steps.plan.session)" || return 1
  [[ -n "$session" ]] || return 1
  if [[ "$(state_get "$state" steps.plan.gate 2>/dev/null || true)" == "true" ]]; then
    pending="$(state_get "$state" steps.plan.taken_at 2>/dev/null || true)"
    [[ "$pending" =~ ^[0-9]+(\.[0-9]+)?$ ]] || pending=0
  fi

  python3 - "$wt" "$session" "$LIB" "$pending" <<'PY'
import json
import os
import sys

wt, session = sys.argv[1], sys.argv[2]
sys.path.insert(0, sys.argv[3])
from presented_plan import plan_text
from session_end import chain

# The project's directory in ~/.claude/projects — the path with everything but
# letters and digits replaced by a hyphen. Verified against every directory on
# this machine.
encoded = "".join(c if c.isalnum() else "-" for c in wt)
transcript = os.path.expanduser(
    os.path.join("~/.claude/projects", encoded, session + ".jsonl")
)
# Where the conversation went on, should Claude Code have given it a new id.
transcript = chain(transcript)[-1]

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
import datetime


def written(entry):
    """When a transcript entry was written, in seconds; 0 when it says not."""
    try:
        return datetime.datetime.fromisoformat(
            str(entry.get("timestamp")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


# Taken from sclaude's terminal: the seconds the session was closed at.
taken_at = float(sys.argv[4]) if sys.argv[4] else None
approved = None
pending = None
for line in lines:
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    if taken_at and written(entry) >= taken_at:
        break
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

# Approved from sclaude's terminal: the call left open when it was closed.
if taken_at is not None and pending is not None:
    approved = pending

if approved is None:
    sys.exit(1)

plan = plan_text(approved)

# There was an approval but no text: the plan lay in a file that was not kept.
# The step must not be closed with an empty bridge to step 2 — better that it
# does not close.
if not plan or not plan.strip():
    sys.exit(1)

target = os.path.join(wt, ".sclaude/local/feature", "plan.md")
os.makedirs(os.path.dirname(target), exist_ok=True)
with open(target, "w") as fh:
    fh.write(plan if plan.endswith("\n") else plan + "\n")
PY
}
