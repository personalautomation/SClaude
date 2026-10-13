#!/usr/bin/env python3
#
# sclaude's own comments on an issue: the user request, the acceptance criteria
# and the current status (with the current behaviour).
#
# An issue's description is never edited after it is created. It used to be:
# step 1 kept a "User request" section in it, the orchestrator appended the
# acceptance criteria, and the epilogue a "Current status" block — to bodies a
# human wrote as well. A developer who opens an issue has then no way to tell
# the task they were given from what a tool made of it, and cannot trust that
# the task has not changed under them. Everything sclaude has to say goes into
# comments instead, each one found again by a marker so that it is rewritten in
# place rather than repeated.
#
# The markers are declared here and only here: acceptance.py, issue_context.py
# and issue_chain.py import them. The shell does not need them.
#
# Silent on any trouble, like the modules that use it: no gh, no network, no
# permissions — None or False, and the caller decides what that means.
import json
import re
import subprocess

# The user request, as step 1 records it: the whole of it, the description's
# requirements restated together with what the conversation decided, so that
# the comment alone says what is being built. Heads its comment. Issues created before the move carry it in the body instead, at the
# end of a "## User request" section.
REQUEST = "<!-- sclaude:user-request -->"

# The acceptance criteria. A pair rather than one marker: the criteria are a
# span inside their comment, with a heading above and a note below, and QA may
# add a line of their own under the list.
AC_OPEN = "<!-- sclaude:ac -->"
AC_CLOSE = "<!-- /sclaude:ac -->"

# The "Current status" the epilogue writes on every issue of the chain. Heads
# its comment, which may carry a "Current behaviour" section below the status:
# how the product actually behaves where that differs from the description.
# One comment rather than two, so the session keeps a single id per issue.
# Bodies written before the move may still carry a block that starts with it.
STATUS = "<!-- sclaude:status -->"

# The "ready to merge" summary on a pull request, written once QA has accepted
# every issue it closes (pr_handoff.py). Heads its comment, which is rewritten
# rather than repeated when QA accepts a later head.
MERGE_READY = "<!-- sclaude:merge-ready -->"

# The incident a production rollback writes on the feature's issue
# (rollback.sh, which declares it too and writes the comment). Nothing rewrites
# it; it is here so the epilogue can tell it from the other comments of ours:
# what was rolled back is part of how the feature behaves now, and the progress
# summary beside it is not. tests/status.py keeps the two spellings equal.
ROLLBACK = "<!-- sclaude:rollback -->"

# The prefix every marker of ours starts with — the progress summary and the
# incident comments too. A comment that starts with it is not discussion.
PREFIX = "<!-- sclaude:"

# The REST id of a comment is the tail of its URL. `gh issue view` gives the
# GraphQL node id in `id`, which the REST endpoint for editing does not take.
URL_ID = re.compile(r"#issuecomment-(\d+)$")


def fetch(number, cwd=None):
    """The issue's body and comments as {"body", "comments"}, or None."""
    try:
        done = subprocess.run(
            ["gh", "issue", "view", str(number), "--json", "body,comments"],
            cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        issue = json.loads(done.stdout)
    except ValueError:
        return None
    return {"body": issue.get("body") or "",
            "comments": issue.get("comments") or []}


def comment_id(comment):
    """A comment's REST id, as a string, or None."""
    found = URL_ID.search((comment or {}).get("url") or "")
    return found.group(1) if found else None


def find(comments, marker):
    """The first comment carrying `marker`, or None.

    "Carrying" rather than "starting with": the acceptance comment opens with
    its heading, and its markers stand around the list below it.
    """
    for c in comments or []:
        if marker in (c.get("body") or ""):
            return c
    return None


def is_ours(text):
    """Whether a comment is one of sclaude's rather than discussion."""
    text = (text or "").strip()
    return text.startswith(PREFIX) or AC_OPEN in text


def discussion(comments, keep=()):
    """The non-empty comments people wrote, oldest first.

    `keep` names markers of ours that count as discussion all the same, for a
    reader who needs them: the epilogue reads a rollback incident as one.
    """
    out = []
    for c in comments or []:
        text = (c.get("body") or "").strip()
        if not text:
            continue
        if is_ours(text) and not any(text.startswith(m) for m in keep):
            continue
        out.append(c)
    return out


def size(text):
    """The length that counts against an exec: UTF-8 bytes, not characters.

    A Cyrillic character is two of them, so a cap in characters lets a Russian
    thread through at twice the size it was meant to allow.
    """
    return len((text or "").encode("utf-8"))


def cut(text, limit, rest):
    """`text` within `limit` bytes, saying where the rest is when it is cut.

    `rest` is the command that prints the whole text.
    """
    if size(text) <= limit:
        return text
    head = text.encode("utf-8")[:limit].decode("utf-8", "ignore").rstrip()
    return head + "\n\n[…cut at %d bytes; the whole text: `%s`]" % (limit, rest)


def read_command(cid):
    """The command that prints one comment of the issue in full."""
    return "gh api repos/{owner}/{repo}/issues/comments/%s --jq .body" % cid


def post(number, body, cwd=None):
    """Add a comment to the issue. True when gh took it."""
    try:
        done = subprocess.run(
            ["gh", "issue", "comment", str(number), "--body-file", "-"],
            input=body, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def edit(cid, body, cwd=None):
    """Replace a comment's text. True when gh took it."""
    try:
        done = subprocess.run(
            ["gh", "api", "-X", "PATCH",
             "repos/{owner}/{repo}/issues/comments/%s" % cid, "--input", "-"],
            input=json.dumps({"body": body}), cwd=cwd, capture_output=True,
            text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


# The two commands a session is given for keeping a comment of its own. Here
# rather than in each prompt so that the planning step and the epilogue are told
# the same thing.
def create_command(number):
    return "gh issue comment %s --body-file -" % number


def edit_command(cid):
    return ("gh api -X PATCH repos/{owner}/{repo}/issues/comments/%s "
            "-F body=@-" % cid)
