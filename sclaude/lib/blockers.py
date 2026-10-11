#!/usr/bin/env python3
#
# Which issues still block a feature's issue — the GitHub "blocked by" links
# whose other end is open.
#
# Until now these links only reached step 1's prompt (issue_context.py), and by
# then the worktree, the branch and the board move had already happened. A
# feature started on top of unfinished work is planned against code that does
# not exist yet, and its plan is redone once the blocker lands. So the links are
# shown where the choice is made: in the issue picker, in the feature list, and
# as a question before `sclaude new` creates anything.
#
#   blockers.py issue <owner/repo> <number>
#       the open blockers of one issue, "<number>\t<title>" per line
#   blockers.py list <owner/repo> <number>...
#       for each given open issue that has open blockers, one line
#       "<number>\t#<b1> #<b2>"
#
# Only the formal links count. issue_context.py also treats an issue the body
# mentions as a dependency, which is right for a prompt a model reads and wrong
# for a question that stops a person: "see #124" is not "cannot start before
# #124".
#
# Silent on any trouble — no gh, no network, no permissions: empty output and
# exit code 0, so the caller carries on as it did before this check existed.
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from issue_chain import nodes  # noqa: E402

# Enough for every open issue of the repositories this runs on. A feature whose
# issue falls outside it shows no mark, which is what an unreachable gh shows
# too.
LIST_LIMIT = 300


def open_blockers(issue):
    """The open "blocked by" links of an issue from gh's JSON, as (number, title)."""
    return [(b.get("number"), " ".join((b.get("title") or "").split()))
            for b in nodes(issue, "blockedBy")
            if (b.get("state") or "").upper() == "OPEN" and b.get("number")]


def gh_json(args):
    try:
        done = subprocess.run(["gh"] + args, capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def main(argv):
    if len(argv) >= 3 and argv[0] == "issue":
        issue = gh_json(["issue", "view", argv[2], "-R", argv[1],
                         "--json", "blockedBy"])
        for number, title in open_blockers(issue or {}):
            print("%s\t%s" % (number, title))
        return 0
    if len(argv) >= 2 and argv[0] == "list":
        wanted = set(argv[2:])
        if not wanted:
            return 0
        issues = gh_json(["issue", "list", "-R", argv[1], "--state", "open",
                          "--limit", str(LIST_LIMIT),
                          "--json", "number,blockedBy"])
        for issue in issues if isinstance(issues, list) else []:
            if str(issue.get("number")) not in wanted:
                continue
            found = open_blockers(issue)
            if found:
                print("%s\t%s" % (issue["number"],
                                  " ".join("#%s" % n for n, _ in found)))
        return 0
    print("usage: blockers.py issue <owner/repo> <number>\n"
          "       blockers.py list <owner/repo> <number>...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
