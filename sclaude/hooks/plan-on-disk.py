#!/usr/bin/env python3
#
# Step 1's plan, at the moment it is presented: saved next to the feature, and
# not shown for approval without its acceptance criteria.
#
# The plan goes to disk at the moment it is presented, not when it is approved.
# The "Exit plan mode?" dialogue unfolds over the plan and covers it. While it is
# open there is nothing to get back to the text with: the dialogue has no
# scrolling, and Ctrl+G edits the input box rather than showing the plan. And
# the reading has to happen right then — the answer to the dialogue is the
# decision, and "I will read it first and answer after" does not work.
#
# Claude Code's own file (~/.claude/plans/<slug>.md) is no help: verified on a
# live session — before approval it is not there.
#
# So we put the plan next to the feature ourselves, on every presentation. This
# also makes the step able to survive an interruption: if the session ends
# without reaching approval, .feature/plan.md will still be in place — the last
# of what was drafted.
#
# The acceptance criteria are the one part of the plan that says what "done"
# means, and until this gate nothing held them there but the prompt's word: a
# plan with an empty section was approved, and closed the step, exactly like a
# full one. A plan without them is refused here — a deny, which cancels the
# approval dialogue before the human sees it and hands the reason to the model;
# it adds the section and presents again. That is the one decision this hook
# makes. It never allows: an "allow" would approve the plan on the human's
# behalf.
#
# The gate reads the plan, not the issue: the plan is always at hand — no
# network, no gh — and it is where step 1 puts the list whoever wrote the issue.
# The orchestrator copies it into the issue once the plan is approved.
#
# One hook rather than two on the same call. Hooks on one event run in
# parallel, and a separate gate left this one to work out the gate's decision
# for itself, only to know whether to send its hint about a dialogue that might
# never open.
#
# Silent on everything it cannot judge: no feature around the session (someone
# else's planning), a plan that cannot be read. A hook that fails closed on its
# own trouble would lock step 1 for a reason that has nothing to do with the
# plan.
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                os.pardir, "lib"))
from acceptance import plan_verdict  # noqa: E402
from presented_plan import plan_text  # noqa: E402

# The hint goes through systemMessage: a hook has no channel of its own to the
# terminal, and what has to be said is for the human rather than the model. The
# model will read it and pass it on in words — step 1's prompt tells it to do
# exactly that, right before presenting the plan.
HINT = (
    "The plan is saved to .feature/plan.md — it can be opened and read in full "
    "while the approval dialog waits for an answer. In the session itself the "
    "plan scrolls with Ctrl+O (transcript view; q exits). Remind the human of "
    "both ways before they answer the dialog: the dialog covers the plan and "
    "does not scroll."
)

# The refusals are spelled out whole, because the model gets nothing else: it
# has to be able to fix the plan from this text alone. Two of them, because
# "there is no section" and "the section has nothing in it the gate can read"
# need different fixes, and telling a model the first when the second is true
# sends it off to add a second section.
FORMAT = (
    "one list item per criterion, starting with its identifier: "
    "`- [ ] AC1. <observable behaviour>`, `- [ ] AC2. ...`. If the change "
    "genuinely has nothing a person could observe (a refactor, say), put the "
    "single line `No observable change: <why>` under that heading instead."
)
# The ending both refusals share. collect-denials.py recognises this hook's
# refusals by it — a gate doing its job, not friction — and tests/hooks.py
# guards that the two agree.
TAIL = "Then present the plan again."
MISSING = ("The plan has no acceptance criteria, so it was not shown for "
           "approval. Add a section headed `## Acceptance criteria` near the top "
           "of the plan, with " + FORMAT + " " + TAIL)
EMPTY = ("The plan's `## Acceptance criteria` section has nothing in it that "
         "reads as a criterion, so it was not shown for approval. Keep that one "
         "section and put in it " + FORMAT + " " + TAIL)


def feature_dir(start):
    """The .feature/ directory, up the tree from the session's working
    directory."""
    here = os.path.abspath(start or ".")
    while True:
        candidate = os.path.join(here, ".feature")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    # A call with neither the text nor a path is let through unchecked. There
    # is nothing to judge, and refusing would make approval impossible rather
    # than the plan better. It is not a way round the gate either: capture_plan
    # reads the approved call the same way, finds no plan, and step 1 does not
    # close.
    plan = plan_text(payload.get("tool_input") or {})
    if not plan or not plan.strip():
        return 0

    target = feature_dir(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR"))
    if target is None:
        # No feature found means the session was not started by the
        # orchestrator. We pass silently: the hook must not get in the way of
        # someone else's planning.
        return 0

    try:
        with open(os.path.join(target, "plan.md"), "w") as fh:
            fh.write(plan if plan.endswith("\n") else plan + "\n")
    except OSError:
        pass

    verdict = plan_verdict(plan)
    if verdict in ("missing", "empty"):
        reason = MISSING if verdict == "missing" else EMPTY
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False))
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "systemMessage": HINT,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
