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
# The log lives in .feature/ next to dev.log: the directory is already in
# .gitignore and already goes away with the worktree, so the entries do not
# outlive the feature.
import datetime
import os


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

    We do still walk up the tree: it costs nothing, and a worktree's root stays
    the root even if the hook is one day called from somewhere inside.
    """
    root = start or os.environ.get("CLAUDE_PROJECT_DIR")
    if not root:
        return None
    here = os.path.abspath(root)
    while True:
        candidate = os.path.join(here, ".feature")
        if os.path.isdir(candidate):
            return os.path.join(candidate, "friction.log")
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def note(step, source, subject, reason):
    """Append an entry. Silently does nothing if there can be no log.

    Errors are swallowed deliberately: the log is a side benefit, and bringing
    the hook down for its sake would mean trading a working ban for statistics
    that were not gathered.
    """
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
