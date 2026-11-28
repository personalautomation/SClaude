#!/usr/bin/env python3
#
# The text of a plan presented through ExitPlanMode.
#
# Two readers: the hook on ExitPlanMode (plan-on-disk.py), at the moment the plan
# is presented, and capture_plan in plan.sh, which takes the approved one from
# the transcript. One function for both, because the input's shape has changed
# under us once already — the plan used to arrive as text and now mostly comes
# as a path to a file — and two copies of the reading would drift the next time
# it changes, leaving the gate and the saved plan disagreeing about what was
# presented.
import os


def plan_text(tool_input):
    """The plan in an ExitPlanMode call's input, or None when it cannot be had.

    The text itself when the call carries it; otherwise the file the call names.
    An input with neither is normal rather than a failure: verified on a live
    session where, of four calls, only the first carried the text.

    A file is read as it stands now, so a file edited after its call was
    presented gives the later version. Accepted on purpose: the file's
    earlier versions are in no record this reads, and rebuilding them from
    the transcript's edits would be a second, fragile copy of the plan.
    """
    if not isinstance(tool_input, dict):
        return None
    plan = tool_input.get("plan")
    if plan:
        return plan
    path = tool_input.get("planFilePath")
    if not path:
        return None
    try:
        with open(os.path.expanduser(path)) as fh:
            return fh.read()
    except OSError:
        return None


class PlanCalls:
    """The ExitPlanMode calls of a transcript and the answers to them, read
    entry by entry in order.

    An answer is found by its call's id, not by coming next. A session may put
    up its plan in the same turn as another call — an edit to the plan file,
    then the plan — and that call's result is written first, while the plan's
    answer comes minutes later, when the person has read it. Taking the next
    result for the plan's took the edit's for it: the approval that followed
    went unseen, and a step-1 session approved a second time was never closed.

    Only the conversation counts — assistant and user entries, no subagent's
    (`isSidechain`) and none of the copies of what was sent to the model —
    and a call once answered is never opened again. PlanCalls filters for
    itself, whatever a reader filtered before, so that the three agree.

    Three readers: capture_plan in plan.sh, `approved` and `watch_plan` in
    session_end.py.
    """

    def __init__(self):
        self.open = {}
        self.answered = set()
        self.latest = None

    def answers(self, entry):
        """Each answer this entry gives to a call put up before it, as
        (the call's input, whether it was approved), in order. A call this
        entry puts up is remembered for later entries."""
        out = []
        # The conversation alone: Claude Code also keeps copies of what it
        # sent to the model (`api-request-blob`, no timestamp), which repeat
        # calls and results, ids and all.
        if entry.get("type") not in ("assistant", "user") or entry.get("isSidechain"):
            return out
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            return out
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "ExitPlanMode" \
                    and block.get("id") and block["id"] not in self.answered:
                self.open[block["id"]] = block.get("input") or {}
                self.latest = block["id"]
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in self.open:
                self.answered.add(block["tool_use_id"])
                given = self.open.pop(block["tool_use_id"])
                # Two wordings, "approved your plan" and, for an empty plan,
                # "approved exiting plan mode": caught by their common part.
                out.append((given, "has approved" in str(block.get("content"))))
        return out

    def last_open(self):
        """The input of the last call put up, while it is still unanswered;
        None once it has its answer. An older call left without one — a
        session killed with its dialog open and resumed — is not on screen
        any more: a later plan, answered or not, took its place."""
        return self.open.get(self.latest)
