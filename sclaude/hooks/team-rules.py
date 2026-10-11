#!/usr/bin/env python3
#
# A product's shared sclaude rules are written by its maintainers only.
#
# A product keeps what sclaude should know about it in .sclaude/: the team's
# rules in .sclaude/team/, each developer's own in .sclaude/people/<name>/.
# Who maintains the product is `maintainers` in its .sclaude.json
# (product_maintainer in developer.sh). sclaude attaches this hook only to the
# sessions of somebody who is not on that list, so it has nothing to decide
# about the person: it refuses a write into .sclaude/team/ and lets everything
# else through, reading included. The person's own folder is where their
# session's rules go instead, and a maintainer can lift one into the team's.
#
# Like every hook here it guards against an accident, not against a session
# set on getting round it: a script written elsewhere and run is out of its
# sight. The product's pull-request review is where a change to team/ is seen
# by a maintainer either way.
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell import tokenize  # noqa: E402

TEAM = re.compile(r"(^|/)\.sclaude/team(/|$)")
REASON = ("the product's shared sclaude rules (.sclaude/team/) are written by its "
          "maintainers — `maintainers` in .sclaude.json. Put the rule in your own "
          ".sclaude/people/<name>/ instead; a maintainer can lift it into team/.")

# Bash words that change a file named after them.
WRITERS = ("cp", "mv", "rm", "tee", "touch", "install", "ln", "truncate", "mkdir",
           "rmdir", "dd")


def bash_writes_team(command):
    """Does this command write into a .sclaude/team/ path, as far as it shows?"""
    words = tokenize(command)
    if words is None:
        return bool(TEAM.search(command))
    for i, w in enumerate(words):
        # `>>.sclaude/team/f` carries the redirection on the path itself.
        if not TEAM.search(re.sub(r"^\d?[<>]+&?", "", w.split("=", 1)[-1])):
            continue
        before = words[i - 1] if i else ""
        # A redirection into it, written apart (`> f`) or joined (`>f`).
        if before in (">", ">>", "&>", "1>", "2>") or re.match(r"^\d?>>?", w):
            return True
        # A writing command anywhere in its call, or sed/perl in place.
        start = i
        while start > 0 and words[start - 1] not in ("|", "||", "&&", ";", "&"):
            start -= 1
        call = words[start:i]
        names = [c.rsplit("/", 1)[-1] for c in call]
        if any(n in WRITERS for n in names):
            return True
        if any(n in ("sed", "perl") for n in names) and any(
                c.startswith("-i") or c == "--in-place" for c in call):
            return True
        if names[:2] == ["git", "checkout"] or names[:2] == ["git", "restore"]:
            return True
    return False


def refuses(payload):
    tool = payload.get("tool_name")
    data = payload.get("tool_input") or {}
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(data.get("file_path") or data.get("notebook_path") or "")
        return TEAM.search(path) is not None
    if tool == "Bash":
        return bash_writes_team(str(data.get("command", "")))
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if refuses(payload):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
