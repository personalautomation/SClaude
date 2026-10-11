#!/usr/bin/env python3
#
# Where a session may not write.
#
#   --team          a product's shared sclaude rules (.sclaude/team/) are
#                   written by its maintainers only. sclaude passes this for a
#                   session of somebody who is not on `maintainers` in the
#                   product's .sclaude/config.json (product_maintainer in
#                   developer.sh); their rules go to .sclaude/people/<name>/,
#                   and a maintainer can lift one into team/.
#   --readonly DIR  nothing under DIR. sclaude passes its own checkout for the
#                   friction review, the retrospective and the monthly deferred
#                   review: they read the orchestrator to understand a
#                   restriction, and what they decide goes into the product.
#                   A change to sclaude's out-of-the-box behaviour is a
#                   deliberate pull request, never a session's side effect.
#
# Reading is never refused. Like every hook here it guards against an
# accident, not against a session set on getting round it: a script written
# elsewhere and run is out of its sight.
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell import tokenize  # noqa: E402

TEAM = re.compile(r"(^|/)\.sclaude/team(/|$)")
READONLY_REASON = ("{dir} is sclaude's own checkout, and a session does not change "
                   "it: what this review decides goes into the product's .sclaude/ "
                   "or its code. A change to sclaude itself is proposed deliberately "
                   "(sclaude propose), so leave it as a deferred entry of class "
                   "sclaude-default.")
REASON = ("the product's shared sclaude rules (.sclaude/team/) are written by its "
          "maintainers — `maintainers` in .sclaude/config.json. Put the rule in your own "
          ".sclaude/people/<name>/ instead; a maintainer can lift it into team/.")

# Bash words that change a file named after them.
WRITERS = ("cp", "mv", "rm", "tee", "touch", "install", "ln", "truncate", "mkdir",
           "rmdir", "dd")


# git subcommands that change a repository: in a read-only checkout they are
# writes, whichever file they name.
GIT_WRITES = ("commit", "add", "rm", "mv", "reset", "checkout", "switch", "restore",
              "merge", "rebase", "cherry-pick", "revert", "stash", "apply", "am",
              "push", "tag", "branch", "pull", "clean", "worktree", "config")


# Writers whose last argument alone is written: the rest is read.
TO_LAST = ("cp", "mv", "install", "ln")
SEPS = ("|", "||", "&&", ";", "&")


def write_targets(command, cwd):
    """(word, directory it is relative to) for every path the command writes.

    None when the command cannot be parsed. Followed through `cd`, so
    `cd "$wt" && echo x > f` writes f in the worktree; a `cd` to a path with a
    variable in it makes the directory unknown, and an unknown directory is
    the sclaude checkout's to the read-only check, which is the safe side.
    """
    words = tokenize(command)
    if words is None:
        return None
    out, where, segment = [], cwd, []
    for w in words + [";"]:
        if w not in SEPS:
            segment.append(w)
            continue
        if segment:
            names = [c.rsplit("/", 1)[-1] for c in segment]
            if names[0] == "cd":
                target = segment[1] if len(segment) > 1 else "~"
                where = None if "$" in target else os.path.join(where or cwd, os.path.expanduser(target))
            for i, word in enumerate(segment):
                bare = re.sub(r"^\d?[<>]+&?", "", word)
                before = segment[i - 1] if i else ""
                if bare and (before in (">", ">>", "&>", "1>", "2>")
                             or (bare != word and ">" in word)):
                    out.append((bare, where))
            args = [c for c in segment[1:] if not c.startswith("-") and not re.match(r"^\d?[<>]", c)]
            name = names[0]
            if name in TO_LAST and args:
                out.append((args[-1], where))
            elif name in WRITERS:
                out += [(a, where) for a in args]
            elif name in ("sed", "perl") and any(c.startswith("-i") or c == "--in-place" for c in segment):
                out += [(a, where) for a in args[1:]]
            elif names[:2] in (["git", "checkout"], ["git", "restore"]):
                out += [(a, where) for a in args[1:]]
        segment = []
    return out


def git_writes_in(command, cwd, inside):
    """Does a git call change a repository in a directory `inside` accepts?

    The directory is followed through `cd` and `git -C`; one that cannot be
    told (a variable) counts as inside, which is the safe side.
    """
    words = tokenize(command)
    if words is None:
        return False
    where, call = cwd, []
    for w in words + [";"]:
        if w not in SEPS:
            call.append(w)
            continue
        names = [c.rsplit("/", 1)[-1] for c in call]
        if names and names[0] == "cd" and len(call) > 1:
            where = None if "$" in call[1] else os.path.join(where or cwd, os.path.expanduser(call[1]))
        elif names and names[0] == "git":
            here, j = where, 1
            while j < len(call) and call[j].startswith("-"):
                if call[j] == "-C" and j + 1 < len(call):
                    here = None if "$" in call[j + 1] else os.path.join(
                        here or cwd, os.path.expanduser(call[j + 1]))
                    j += 1
                j += 1
            if j < len(call) and call[j] in GIT_WRITES and (here is None or inside(here)):
                return True
        call = []
    return False


def refuses(payload, team, readonly):
    """The reason to refuse this call, or None."""
    tool = payload.get("tool_name")
    data = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()

    def inside(path, base=None):
        full = os.path.realpath(os.path.join(base or cwd, os.path.expanduser(path)))
        return any(full == d or full.startswith(d + os.sep) for d in readonly)

    def is_team(path):
        return team and TEAM.search(path) is not None

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(data.get("file_path") or data.get("notebook_path") or "")
        if readonly and path and inside(path):
            return READONLY_REASON.format(dir=readonly[0])
        if is_team(path):
            return REASON
        return None
    if tool == "Bash":
        command = str(data.get("command", ""))
        targets = write_targets(command, cwd)
        if targets is None:
            # Unparsable: refused only where it names a guarded place at all.
            if (readonly and any(d in command for d in readonly)) or (team and TEAM.search(command)):
                return READONLY_REASON.format(dir=readonly[0]) if readonly else REASON
            return None
        if readonly:
            for word, base in targets:
                # An unknown directory: an absolute path still tells, a relative
                # one is taken as the checkout's.
                if base is None and not os.path.isabs(os.path.expanduser(word)):
                    return READONLY_REASON.format(dir=readonly[0])
                if inside(word, base):
                    return READONLY_REASON.format(dir=readonly[0])
            if git_writes_in(command, cwd, inside):
                return READONLY_REASON.format(dir=readonly[0])
        if team and any(TEAM.search(word) for word, _ in targets):
            return REASON
    return None


def main():
    argv = sys.argv[1:]
    team = "--team" in argv
    readonly = [os.path.realpath(argv[i + 1]) for i, a in enumerate(argv)
                if a == "--readonly" and i + 1 < len(argv)]
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    reason = refuses(payload, team, readonly)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
