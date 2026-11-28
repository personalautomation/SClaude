#!/usr/bin/env python3
#
# The friction log: what a step ran into and why that got in its way.
#
# The steps' bans were configured blind, and when a restriction turns out to be
# unnecessary we learn of it by accident. The --tools allowlist once took
# subagents away from step 1, and that came to light only because the session
# got "No such tool available" three times and complained out loud. How many
# times a step took an expensive detour in silence is unknown.
#
# We write at the moment of refusal rather than parsing the transcript
# afterwards: it has been measured that a live feature's step transcript is
# almost a megabyte containing zero refusals, while searching for the word
# "denied" mostly finds the model's own text where the word simply occurred.
#
# A caveat to the above: only our own refusals are written this way — those
# issued by our hook. A refusal from auto mode's built-in classifier is not
# visible to a hook at all, Claude Code has no event for it, and it reaches the
# log through parsing the transcript — collect-denials.py, after the step ends.
# There is still no reason to do that by searching for a word: a refusal entry
# has a toolDenialKind field, and it answers precisely.
#
# The log lives in .sclaude/local/feature/ next to dev.log: the directory is already in
# .gitignore and already goes away with the worktree, so the entries do not
# outlive the feature.
import datetime
import os

# Whether this process is a call from Claude Code: None until the hook has
# read its payload (heard()). Claude Code always names the event it runs a hook
# for; a payload typed by hand — a review probing its fix — does not, and its
# refusal is no step's friction, whatever tree or step it names.
LIVE = None


def heard(payload):
    """Note whether the hook's payload came from Claude Code; a payload that
    is not an object leaves it unknown, so a hook it breaks still logs."""
    global LIVE
    LIVE = bool(payload.get("hook_event_name")) if isinstance(payload, dict) else None


def log_path(start=None):
    """The path to the log, or None when there is nowhere to write.

    The only starting point is CLAUDE_PROJECT_DIR: the step's session sets it,
    and it points at the root of the feature's worktree. The current directory
    cannot be the starting point, convenient as it looks. These same hooks are
    run by hand by the friction review session — to check that a fix holds — and
    it does a `cd` into the feature's tree while doing so. Four of its test
    refusals landed in password-change's log indistinguishable from the real
    ones, with someone else's step in the field, and the next review had to work
    out from the timestamps that these were not friction.

    We do still walk up the tree, so that a worktree's root stays the root if
    the hook is one day called from somewhere inside it, but no further than
    the first repository's root: the workshop is a checkout of its own nested
    inside a feature's tree, and a review's subagent that ran the hooks by hand
    there, with CLAUDE_PROJECT_DIR set to the workshop, walked out of it into
    the feature's log and wrote its probes there as the feature's friction.
    """
    root = start or os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return None
    here = os.path.abspath(root)
    while True:
        candidate = os.path.join(here, ".sclaude/local/feature")
        if os.path.isdir(candidate):
            return os.path.join(candidate, "friction.log")
        parent = os.path.dirname(here)
        if parent == here or os.path.exists(os.path.join(here, ".git")):
            return None
        here = parent


def note(step, source, subject, reason):
    """Append an entry. Silently does nothing if there can be no log.

    Errors are swallowed deliberately: the log is a side benefit, and bringing
    the hook down for its sake would mean trading a working ban for statistics
    that were not gathered.
    """
    # A review session's own refusals (the retrospective and the reviews run
    # under --step friction) are not a step's friction: written here, they sat
    # in the log until the next step's review read them as that step's.
    if step == "friction":
        return
    # A payload typed by hand is a probe, not a step's call. Unknown (a hook
    # that broke before reading its payload) still writes: a broken hook
    # reaches the log.
    if LIVE is False:
        return
    try:
        path = log_path()
        if not path:
            return
        stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        # Tabs in the fields would break the parsing, newlines the
        # paragraph.
        clean = lambda s: " ".join(str(s).split())
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s\t%s\t%s\t%s\n\t%s\n\n" % (
                stamp, clean(step) or "?", clean(source), clean(subject),
                clean(reason),
            ))
    except Exception:
        pass
