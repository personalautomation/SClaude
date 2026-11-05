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
