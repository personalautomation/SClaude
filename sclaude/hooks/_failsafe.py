#!/usr/bin/env python3
#
# A hook that fails refuses; it never lets the call through.
#
# Claude Code runs a command when its PreToolUse hook exits with an error, so a
# hook that raised, at import or later, used to drop every ban it held. Each
# hook installs this first, before importing anything of sclaude's: an
# exception that reaches the top becomes a refusal, printed the way Claude
# Code reads one, and the hook exits 0 so that it is read.
#
# The standard library only, so that nothing it needs can be what broke.
import json
import os
import sys
import traceback

# The tail every refusal of the step hook ends with, so collect-denials.py
# knows the refusal as a hook's own (OWN_MARKERS) and does not log it twice.
TAIL = "  Tell the human and stop — the next move is theirs."

# What the hook knows of the call when it breaks, for the friction log: the
# hook sets "subject" once it has read the payload.
CONTEXT = {"subject": ""}


def step():
    argv = sys.argv[1:]
    return argv[argv.index("--step") + 1] if "--step" in argv[:-1] else ""


def install(hook):
    """Turn any uncaught exception in this process into a refusal by `hook`."""
    def refuse(kind, exc, tb):
        reason = ("sclaude's %s failed (%s: %s), so this call is refused rather than "
                  "let through unchecked." % (hook, kind.__name__, exc))
        # Where it broke, for whoever repairs it: the refusal names only the
        # exception.
        sys.stderr.write("".join(traceback.format_exception(kind, exc, tb)))
        # Into the friction log, as the hook's own refusals go. The text ends
        # with TAIL, so collect-denials skips it as already written, and a
        # broken hook reached the friction review from nowhere.
        try:
            from _friction import note
            note(step(), "failsafe", CONTEXT.get("subject", ""), reason)
        except Exception:  # noqa: BLE001 — the log is the lesser loss
            pass
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason + TAIL,
        }}) + "\n")
        sys.stdout.flush()
        os._exit(0)
    sys.excepthook = refuse
