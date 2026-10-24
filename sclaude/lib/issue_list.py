#!/usr/bin/env python3
#
# The open issues a feature can start from, and the branch name each suggests:
# what the terminal's picker (pick_start in picker.sh) and the bot's Mini App
# both offer when a feature starts, so the two cannot disagree.
#
#   issue_list.py rows <owner/repo>
#       one line per open issue, one's own first and the freshest first:
#       <mine?>\t<number>\t<title>\t<labels, comma-separated>\t<open blockers>
#   issue_list.py suggest <number> <title>
#       the branch name suggested for that issue (suggest_slug in bin/sclaude)
#
# "Mine?" is 1 when the issue is assigned to whoever gh is authenticated as. We
# ask gh for the login rather than writing it as a constant: it has already
# changed once in a project.
#
# The open blockers are "#12 #34", or empty: an issue that cannot start yet is
# marked in the list rather than discovered after its worktree exists (see
# blockers.py).
#
# `rows` exits 1 with nothing printed when gh is missing, fails or finds no
# open issue: the caller then starts the feature by name.
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blockers import gh_json, open_blockers  # noqa: E402

LIMIT = 50

# Who gh is authenticated as, asked once per process: the bot's menu fetches
# the list again and again, and the login does not change under it. A failure
# is remembered for a minute, so a gh that does not answer costs one wait per
# press rather than two.
LOGIN_RETRY = 60
_LOGIN = {}


def login():
    if _LOGIN.get("name") is not None:
        return _LOGIN["name"]
    if time.time() - _LOGIN.get("failed", 0) < LOGIN_RETRY:
        return ""
    try:
        done = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        done = None
    if not done or done.returncode != 0:
        _LOGIN["failed"] = time.time()
        return ""
    _LOGIN["name"] = done.stdout.strip()
    return _LOGIN["name"]


def fetch(repo):
    """[{mine, number, title, labels, blocked, blockers}] of the open issues, in the
    picker's order; None when gh cannot say."""
    me = login()
    issues = gh_json(["issue", "list", "-R", repo, "--state", "open", "--limit", str(LIMIT),
                      "--json", "number,title,labels,assignees,blockedBy"])
    if not isinstance(issues, list):
        return None
    rows = []
    for it in issues:
        mine = any(a.get("login") == me for a in it.get("assignees") or [])
        blockers = open_blockers(it)
        rows.append({
            "mine": mine,
            "number": it["number"],
            "title": " ".join((it.get("title") or "").split()),
            "labels": ",".join(l["name"] for l in it.get("labels") or []),
            "blocked": " ".join("#%s" % n for n, _ in blockers),
            # (number, title) of each: what the question before a start names.
            "blockers": blockers,
        })
    # One's own issues on top, and within a block the freshest first.
    rows.sort(key=lambda r: (0 if r["mine"] else 1, -r["number"]))
    return rows


def slugify(name):
    # ASCII only, as `tr` and `sed` in bin/sclaude's slugify: str.lower() would
    # turn "İ" into an "i" that the branch sclaude makes does not have.
    lowered = re.sub(r"[A-Z]", lambda m: m.group(0).lower(), name)
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


# A trailing preposition or article adds nothing: "change-an-account-how" reads
# worse than "change-an-account".
TRAILING = {"a", "an", "the", "to", "of", "for", "on", "in", "by", "with", "and",
            "how", "our", "this"}


def suggest(number, title):
    """The number and the title's first words, no longer than 40 characters
    all together, trimmed on word boundaries: a word cut off in the middle
    reads worse than one word fewer. A title that is entirely non-Latin
    leaves the number alone."""
    number = str(number)
    words = []
    for word in slugify(title).split("-"):
        if not word or len(words) >= 4:
            break
        if len(number) + 1 + len("-".join(words)) + 1 + len(word) > 40:
            break
        words.append(word)
    while len(words) > 1 and words[-1] in TRAILING:
        words.pop()
    return "%s-%s" % (number, "-".join(words)) if words else "issue-%s" % number


def main(argv):
    if len(argv) == 2 and argv[0] == "rows":
        rows = fetch(argv[1])
        if not rows:
            return 1
        for r in rows:
            print("%d\t%d\t%s\t%s\t%s" % (1 if r["mine"] else 0, r["number"], r["title"],
                                          r["labels"], r["blocked"]))
        return 0
    if len(argv) == 3 and argv[0] == "suggest":
        print(suggest(argv[1], argv[2]))
        return 0
    sys.stderr.write("usage: issue_list.py rows <owner/repo> | suggest <number> <title>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
