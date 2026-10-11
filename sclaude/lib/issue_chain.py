#!/usr/bin/env python3
#
# An issue and the whole chain of its parents — for the session that writes the
# feature's outcome.
#
# A closed sub-issue changes an epic's state, but the epic says nothing about
# it: to understand where it stands, the children had to be opened one by one.
# One had ten of them. Here the chain is assembled whole and once, and a
# separate session writes the "Current status" section from it — see
# sclaude/prompts/status.md.
#
# The section is a comment of ours on each issue, never a part of its
# description — see issue_comments.py.
#
# The same comment carries a "Current behaviour" section where the product no
# longer does what a description says: a child that is a change request to its
# parent, or a feature that left its own description behind while it was built.
# That is why the feature brings its discussion along — the decisions taken
# while building it ("Returned from QA", answers to questions) are where it
# left its description — and why every level brings its "User request"
# comment, the planner's record of what the description did not say.
#
# A separate file rather than an extension of issue_context.py: that one renders
# a single issue for the planner — with the links around it, with the advice
# about the "User request" comment, with its own set of fields. What is needed
# here is different: the chain upwards, the progress at each level, and the
# discussion of the feature alone (a parent's runs to kilobytes, and what it
# settled is already in the parent's own Current behaviour).
#
# Silent on any trouble: no gh, no network, no permissions — empty output and
# exit code 0. The section in the issue is a benefit, not a condition of the
# cycle working.
import json
import os
import subprocess
import sys

# This file is run as a script, from whatever directory the orchestrator is in,
# so the import below needs its own directory on the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Comments are fetched for our own ones on every level, and for the discussion
# on the feature — see the header.
FIELDS = ("number,title,body,state,url,labels,parent,subIssues,"
          "subIssuesSummary,comments")

# The walk's depth. The limit is not there for elegance: `parent` comes from
# GitHub rather than from our state, and a loop #A → #B → #A would spin gh until
# Ctrl-C. This repository's real chains are one or two levels deep.
MAX_DEPTH = 10

# Our markers, from the module that declares them all.
import issue_comments  # noqa: E402
from issue_comments import AC_OPEN, REQUEST, ROLLBACK, STATUS  # noqa: E402

# The snapshot travels to render_prompt.py as one environment variable, and the
# prompt it ends up in reaches claude as one argument; Linux refuses an exec
# whose single string passes 128 KiB, and run_status then skips the epilogue
# without a word. So the snapshot as a whole is held to MAX_SNAPSHOT, which
# leaves room for the rest of the prompt, and every limit here is in UTF-8
# bytes — a Russian thread is twice its length in characters.
#
# The descriptions and our own comments come first and are not cut, apart from
# the "User request" comments, which step 2 keeps growing and which arrive from
# every level. The feature's discussion gets what is left, up to
# MAX_DISCUSSION: each comment is cut at MAX_COMMENT, and the newest are kept
# when they do not all fit, because a later decision overrides an earlier one,
# so the latest are the ones that say how the product behaves.
MAX_SNAPSHOT = 96 * 1024
MAX_COMMENT = 6000
MAX_DISCUSSION = 40000


def fetch(number, cwd=None):
    try:
        done = subprocess.run(
            ["gh", "issue", "view", str(number), "--json", FIELDS],
            cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def chain(number, cwd=None):
    """An issue and its parents, from the bottom up. The issue itself first."""
    out, seen = [], set()
    current = number
    while current is not None and len(out) < MAX_DEPTH:
        if current in seen:
            break
        seen.add(current)
        issue = fetch(current, cwd)
        if issue is None:
            break
        out.append(issue)
        # `parent` arrives as a flat object — {id, number, state, title, url} —
        # or null. There is no .nodes to unwrap here, unlike the links below:
        # GitHub uses different shapes for these, and confusing them is
        # expensive.
        parent = issue.get("parent")
        current = parent.get("number") if isinstance(parent, dict) else None
    return out


def nodes(issue, field):
    """An issue's links as a list.

    gh returns subIssues (and blockedBy, and blocking) as an object
    {"nodes": [...], "totalCount": N} rather than a list. Iterating such an
    object gives string keys, and code written "as for a list" quietly finds
    nothing: that is exactly how the "Links" section never reached step 1.
    """
    value = issue.get(field)
    if isinstance(value, dict):
        return value.get("nodes") or []
    return value or []


def progress(issue):
    """"9 of 10 closed (90%)", or None when there are no children."""
    summary = issue.get("subIssuesSummary")
    if not isinstance(summary, dict):
        return None
    total = summary.get("total") or 0
    if not total:
        return None
    return "%s of %s closed (%s%%)" % (
        summary.get("completed", 0), total, summary.get("percentCompleted", 0))


def level_name(index):
    if index == 0:
        return "level 0 (the feature itself)"
    if index == 1:
        return "level 1 (parent)"
    return "level %d (parent of level %d)" % (index, index - 1)


def head(issue):
    """An issue's header on one line: state, labels, progress over its
    children."""
    facts = []
    state = issue.get("state")
    if state:
        facts.append(state.lower())
    labels = [l.get("name") for l in (issue.get("labels") or []) if l.get("name")]
    facts.append("labels: " + ", ".join(labels) if labels else "no labels")
    done = progress(issue)
    facts.append("sub-issues: " + done if done else "no sub-issues")
    return " · ".join(facts)


def render_one(issue, index, room=MAX_DISCUSSION):
    out = ["### #%s — %s · %s" % (
        issue.get("number"), issue.get("title") or "", level_name(index))]
    out.append("")
    out.append(head(issue))
    out.append("")

    children = nodes(issue, "subIssues")
    if children:
        for child in children:
            if not isinstance(child, dict):
                continue
            out.append("- #%s %s (%s)" % (
                child.get("number"), child.get("title") or "",
                (child.get("state") or "?").lower()))
        out.append("")

    body = issue.get("body") or ""
    out.append("**The description, in full — for reading only:**")
    out.append("")
    # The delimiters are needed because bodies contain both `#` headings and
    # `---`: without them someone else's markup dissolves into ours, and the
    # session cannot see where the description ends.
    out.append("<<<BODY")
    out.append(body)
    out.append("BODY")
    out.append("")
    if STATUS in body:
        out.append("The description still holds a `%s` block from before the "
                   "status moved to a comment. Leave it: the description is "
                   "not edited." % STATUS)
        out.append("")

    comments = issue.get("comments") or []
    criteria = issue_comments.find(comments, AC_OPEN)
    if criteria is not None:
        out.append("**The acceptance criteria comment** (not yours — read the "
                   "boxes, don't tick them):")
        out.append("")
        out.append("<<<CRITERIA")
        out.append((criteria.get("body") or "").strip())
        out.append("CRITERIA")
        out.append("")

    request = issue_comments.find(comments, REQUEST)
    if request is not None:
        out.append("**The \"User request\" comment** (not yours — what the "
                   "planning step recorded beyond the description):")
        out.append("")
        out.append("<<<REQUEST")
        out.append(clipped(request))
        out.append("REQUEST")
        out.append("")

    if index == 0:
        out.extend(discussion(issue, room))

    out.extend(status_comment(issue))
    out.append("")
    return out


def clipped(comment):
    """A comment's text within MAX_COMMENT, pointing at the whole of it."""
    text = (comment.get("body") or "").strip()
    cid = issue_comments.comment_id(comment)
    rest = issue_comments.read_command(cid) if cid else "gh issue view --json comments"
    return issue_comments.cut(text, MAX_COMMENT, rest)


def discussion(issue, room=MAX_DISCUSSION):
    """The feature's discussion, oldest first, within `room` bytes.

    A rollback incident is ours but counts: what was rolled back is part of how
    the feature behaves now.
    """
    said = issue_comments.discussion(issue.get("comments"), keep=(ROLLBACK,))
    if not said:
        return ["**The discussion:** none.", ""]
    room = min(room, MAX_DISCUSSION)
    kept, used = [], 0
    for c in reversed(said):
        text = clipped(c)
        if used + issue_comments.size(text) > room:
            break
        author = ((c.get("author") or {}).get("login")) or "?"
        kept.append((author, text))
        used += issue_comments.size(text)
    kept.reverse()
    out = ["**The discussion** (%d comment%s, oldest first — decisions taken "
           "while building the feature; a later one overrides an earlier "
           "one):" % (len(said), "" if len(said) == 1 else "s"), ""]
    if len(kept) < len(said):
        out.append("%s left out for size: `gh issue view %s --json comments "
                   "--jq '.comments[].body'` has them all."
                   % ("All of them are" if not kept else
                      "The %d oldest are" % (len(said) - len(kept)),
                      issue.get("number")))
        out.append("")
    for author, text in kept:
        out.append("<<<COMMENT by %s" % author)
        out.append(text)
        out.append("COMMENT")
        out.append("")
    return out


def status_comment(issue):
    """The issue's status comment and the command that writes it."""
    number = issue.get("number")
    found = issue_comments.find(issue.get("comments") or [], STATUS)
    cid = issue_comments.comment_id(found) if found else None
    if found is None or not cid:
        return ["There is no status comment on #%s yet — create it: `%s`."
                % (number, issue_comments.create_command(number))]
    return ["**The status comment, as it stands:**",
            "",
            "<<<STATUS",
            (found.get("body") or "").strip(),
            "STATUS",
            "",
            "Rewrite it in place, never add a second one: `%s`."
            % issue_comments.edit_command(cid)]


def render(number, cwd=None):
    issues = chain(number, cwd)
    if not issues:
        return ""
    # Everything but the discussion first, to learn how much room it leaves.
    rest = sum(issue_comments.size("\n".join(render_one(issue, index, 0)))
               for index, issue in enumerate(issues))
    room = MAX_SNAPSHOT - rest
    out = []
    for index, issue in enumerate(issues):
        out.extend(render_one(issue, index, room))
    if len(issues) == 1:
        out.append("This issue has no parents — the chain ends here.")
    else:
        out.append("There are no parents above level %d — the chain ends there."
                   % (len(issues) - 1))
    return "\n".join(out).rstrip("\n")


def chain_numbers(number, cwd=None):
    """Just the chain's numbers, one per line — for applying labels."""
    return "\n".join(str(i.get("number")) for i in chain(number, cwd)
                     if i.get("number") is not None)


def main():
    argv = sys.argv[1:]
    numbers_only = False
    if argv and argv[0] == "--numbers":
        numbers_only = True
        argv = argv[1:]
    if not argv or not argv[0].strip():
        return 0
    cwd = argv[1] if len(argv) > 1 else None
    try:
        text = (chain_numbers if numbers_only else render)(argv[0].strip(), cwd)
        sys.stdout.write(text)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
