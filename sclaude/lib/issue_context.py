#!/usr/bin/env python3
#
# A snapshot of the issue for step 1 — the issue itself, its parent and the
# titles of its neighbours.
#
# Step 1 used to fetch this itself, and the prompt carried twenty lines about
# how exactly: which fields to ask for, why `--comments` will not do (it
# replaces the body with the discussion rather than adding it), how many hops to
# make along the links. The instruction about the flag exists only so that the
# model does not step on a rake; when the orchestrator brings the issue there is
# no rake and no need for the instruction.
#
# One hop along the links, no deeper — the same rule as was in the prompt: on a
# large epic the walk would drag in a dozen issues with their bodies. We read
# whole the parent (the business goal usually lies in it) and every blocker
# (what it delivers is what this issue is built on). From the other neighbours —
# sub-issues, the parent's other children, issues the description points to —
# we take the title and state.
#
# Issues the description points to count as links though GitHub does not know
# them as such. "A button on the #124 page" is a dependency whether or not
# anyone clicked "blocked by"; a session that saw only the formal links missed
# it, and planned the entry point as an open question.
#
# Silent on any trouble: no gh, no network, no permissions — empty output, and
# the prompt keeps its previous instruction.
import json
import os
import re
import subprocess
import sys

# Our markers come from the module that declares them all. The path is added
# explicitly because this file is run as a script, from whatever directory the
# orchestrator happens to be in.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import issue_comments  # noqa: E402
from issue_chain import nodes  # noqa: E402
from issue_comments import AC_CLOSE, AC_OPEN, REQUEST  # noqa: E402

FIELDS = ("number,title,body,state,url,labels,milestone,issueType,parent,"
          "subIssues,blockedBy,blocking,comments")

# A blocker brings its body, so there are fewer of them; past the cap the rest
# stay one line each. Every list of one-line links stops at MAX_LINKS, and when
# it has to stop the open issues go first: a closed one is history, an open one
# is work still in the way or still to be shared.
MAX_BLOCKERS = 10
MAX_LINKS = 50

# A blocker body is cut here. The snapshot travels to render_prompt.py as one
# environment variable, and Linux refuses an exec whose single variable passes
# 128 KiB: ten bodies at the 64 KiB GitHub allows would stop step 1 from
# starting at all. Ten at this size leave room for everything else.
MAX_BODY = 6000

# How many mentioned numbers one query asks about. Only MAX_LINKS are shown,
# but which ones depends on their state, so a few more are asked for.
MAX_ASKED = 4 * MAX_LINKS

# GraphQL takes an issue number as a 32-bit Int; a larger one, say a date
# written as #20240101123, invalidates the whole query rather than one alias.
MAX_NUMBER = 2 ** 31 - 1

# Blockers and mentioned issues arrive in one GraphQL request each rather than
# one `gh issue view` per issue: fifty of those would hold the step's start for
# most of a minute.
BRIEF_QUERY = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { %s }
}"""
BRIEF_ITEM = ("n%d: issueOrPullRequest(number: %d) {"
              " ... on Issue { %s }"
              " ... on PullRequest { %s } }")
BRIEF_FIELDS = "number title state"
BODY_FIELDS = BRIEF_FIELDS + " body"


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


def head(issue):
    """An issue's header: number, title, state, labels, milestone."""
    bits = ["**#%s — %s**" % (issue.get("number"), issue.get("title") or "")]
    facts = []
    state = issue.get("state")
    if state:
        facts.append(state.lower())
    kind = issue.get("issueType")
    if isinstance(kind, dict) and kind.get("name"):
        facts.append(kind["name"])
    labels = [l.get("name") for l in (issue.get("labels") or []) if l.get("name")]
    if labels:
        facts.append("labels: " + ", ".join(labels))
    milestone = issue.get("milestone")
    if isinstance(milestone, dict) and milestone.get("title"):
        facts.append("milestone: " + milestone["title"])
    if facts:
        bits.append(" · ".join(facts))
    return bits


def open_first(items):
    """Open issues ahead of closed ones, otherwise in the order given."""
    return sorted(items, key=lambda it: (it.get("state") or "").upper() != "OPEN")


def capped(items, total=0, limit=MAX_LINKS):
    """The rows for at most `limit` items, open ones first when some must go,
    and the items those rows show.

    `total` is the count gh reports beside its nodes, which may be more than
    it sent; the line about what was left out counts by whichever is larger.
    """
    kept = items if len(items) <= limit else open_first(items)[:limit]
    rows = [line(it) for it in kept]
    hidden = max(len(items), total) - len(kept)
    if hidden > 0:
        rows.append("  - …and %d more, not shown." % hidden)
    return rows, kept


def briefs(numbers, url, cwd=None, fields=BRIEF_FIELDS):
    """The given fields of each issue in `numbers`, in the order given.

    The repository is taken from the issue URL. Silent on any trouble, like the
    rest of this file: what does not arrive is not listed.
    """
    parts = (url or "").split("/")
    if len(parts) < 5 or not numbers:
        return []
    owner, name = parts[3], parts[4]
    query = BRIEF_QUERY % " ".join(BRIEF_ITEM % (n, n, fields, fields)
                                   for n in numbers)
    try:
        # -f, not -F: -F types its value, and a repository called 2048 would
        # go out as an Int to a String! variable.
        done = subprocess.run(
            ["gh", "api", "graphql", "-f", "query=" + query,
             "-f", "owner=" + owner, "-f", "name=" + name],
            cwd=cwd, capture_output=True, text=True, timeout=60)
        repo = json.loads(done.stdout)["data"]["repository"] or {}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError,
            TypeError):
        return []
    found = [repo.get("n%d" % n) for n in numbers]
    return [it for it in found if isinstance(it, dict) and it.get("number")]


def link_nodes(issue, field):
    return [it for it in nodes(issue, field) if isinstance(it, dict)]


def link_total(issue, field):
    """The count gh reports for a link field, which `nodes` may fall short of."""
    value = issue.get(field)
    total = value.get("totalCount") if isinstance(value, dict) else None
    return total if isinstance(total, int) else 0


def cut(text, number):
    """A body no longer than MAX_BODY, saying where the rest is."""
    if len(text) <= MAX_BODY:
        return text
    return (text[:MAX_BODY].rstrip() + "\n\n_…cut at %d characters; the rest: "
            "`gh issue view %s`._" % (MAX_BODY, number))


def line(it, mark=""):
    return "  - #%s %s (%s)%s" % (it.get("number"), it.get("title") or "",
                                  (it.get("state") or "?").lower(), mark)


def mentions(issue, skip):
    """Numbers of the issues this one's body points to, in order of mention.

    Both spellings count: `#124` and a full URL into the same repository. A URL
    into another repository is somebody else's #124 and is left alone, and so
    is anything already shown under another heading.
    """
    body = issue.get("body") or ""
    url = issue.get("url") or ""
    # Owner and repository names are case-insensitive on GitHub.
    base = url.rsplit("/", 1)[0].lower() if "/issues/" in url else None
    found = []
    for m in re.finditer(r"(https://github\.com/[^/\s]+/[^/\s]+/issues)/(\d+)"
                         r"|(?<![\w&/#])#(\d+)\b", body):
        if m.group(2):
            if m.group(1).lower() != base:
                continue
            n = int(m.group(2))
        else:
            n = int(m.group(3))
        if 0 < n <= MAX_NUMBER and n not in skip and n not in found:
            found.append(n)
            if len(found) >= MAX_ASKED:
                break
    return found


def neighbours(issue):
    """The neighbours, one line each: the title and state have already arrived.

    The links arrive as an object {"nodes": [...], "totalCount": N} rather than
    a list — and that is not a formatting detail. Iterating such an object gives
    string keys, isinstance(..., dict) discards them, and the "Links" section
    quietly did not print at all: step 1 never saw either sub-issues or blockers.
    """
    out = []
    for field, label in (("subIssues", "Sub-issues"),
                         ("blocking", "Blocking")):
        rows, _ = capped(link_nodes(issue, field), link_total(issue, field))
        if rows:
            out.append("- **%s:**" % label)
            out.extend(rows)
    return out


def render(number, cwd=None):
    issue = fetch(number, cwd)
    if issue is None:
        return ""

    # The prompt supplies the section's heading — only the content is here,
    # otherwise the assembled prompt would have two headings in a row about the
    # same thing.
    out = []
    out.extend(head(issue))
    out.append("")

    body = (issue.get("body") or "").strip()
    if body:
        out.append(body)
    else:
        out.append("_The issue body is empty._")
    out.append("")

    # Our own comments are not discussion. The progress summary is the very
    # step it reports on, and the request and the criteria are shown below,
    # under what they are, rather than as somebody's remark.
    comments = issue_comments.discussion(issue.get("comments"))
    if comments:
        out.append("#### Comments (%d)" % len(comments))
        out.append("")
        for c in comments:
            author = ((c.get("author") or {}).get("login")) or "?"
            text = (c.get("body") or "").strip()
            out.append("**%s:**" % author)
            out.append("")
            out.append(text)
            out.append("")
    else:
        out.append("No comments.")
        out.append("")

    number = issue.get("number")
    shown = {number}
    parent = issue.get("parent")
    if isinstance(parent, dict) and parent.get("number"):
        full = fetch(parent["number"], cwd) or parent
        shown.add(full.get("number"))
        out.append("#### Parent issue")
        out.append("")
        out.extend(head(full))
        out.append("")
        ptext = (full.get("body") or "").strip()
        out.append(ptext if ptext else "_Body is empty._")
        out.append("")
        # The parent's other children: the map of the epic, and where the
        # boundary of this issue runs.
        siblings = link_nodes(full, "subIssues")
        if siblings:
            out.append("Its sub-issues — this one among them:")
            out.append("")
            mine = [it for it in siblings if it.get("number") == number]
            rows, kept = capped([it for it in siblings if it not in mine],
                                link_total(full, "subIssues") - len(mine))
            # Only what is on the page counts as shown: a sibling the cap
            # left out must still be listed if the description mentions it.
            shown.update(it.get("number") for it in kept)
            out.extend(line(it, "  ← this issue") for it in mine)
            out.extend(rows)
            out.append("")

    blockers = link_nodes(issue, "blockedBy")
    if blockers:
        out.append("#### Blocked by")
        out.append("")
        out.append("This issue is built on these. Read each as part of the "
                   "task: what it delivers, and whether that exists yet.")
        out.append("")
        blockers = open_first(blockers)
        first = blockers[:MAX_BLOCKERS]
        bodies = {it.get("number"): it for it in briefs(
            [it.get("number") for it in first], issue.get("url"), cwd,
            BODY_FIELDS)}
        rest = []
        for it in first:
            full = bodies.get(it.get("number"))
            if full is None:
                rest.append(it)
                continue
            shown.add(it.get("number"))
            out.extend(head(full))
            out.append("")
            btext = (full.get("body") or "").strip()
            out.append(cut(btext, it.get("number")) if btext
                       else "_Body is empty._")
            out.append("")
        rest += blockers[MAX_BLOCKERS:]
        if rest:
            out.append("Without their bodies here — open them yourself:")
            out.append("")
            rows, kept = capped(rest, link_total(issue, "blockedBy")
                                - (len(blockers) - len(rest)))
            shown.update(it.get("number") for it in kept)
            out.extend(rows)
            out.append("")

    links = neighbours(issue)
    for field in ("subIssues", "blocking"):
        shown.update(it.get("number") for it in link_nodes(issue, field))
    pointed = briefs(mentions(issue, shown), issue.get("url"), cwd)
    if pointed:
        links.append("- **Mentioned in the description:**")
        links.extend(capped(pointed)[0])

    if links:
        out.append("#### Links")
        out.append("")
        out.extend(links)
        out.append("")
        out.append("Only title and state are shown here. An issue the "
                   "description points to is part of the task as much as a "
                   "formal blocker: open it with `gh issue view <N>`. For the "
                   "rest, open a body where the link looks material. No "
                   "deeper than one hop.")
        out.append("")

    out.extend(own_comments(issue))
    return "\n".join(out).rstrip("\n")


def own_comments(issue):
    """What sclaude keeps on this issue, and what step 1 may do with it.

    The description is not ours, whoever wrote it — see issue_comments.py. The
    "User request" is step 1's, in a comment of its own, and the session is
    handed the command that rewrites it: an id it would otherwise have to dig
    out of a URL, and a second comment each time it failed to.
    """
    out = []
    comments = issue.get("comments") or []
    number = issue.get("number")

    out.append("**The description is not yours.** Don't edit it, whoever "
               "wrote it: everything you record goes into comments.")
    body = issue.get("body") or ""
    if REQUEST in body:
        out.append("")
        out.append("This body is from before that rule: it carries a "
                   "`## User request` section an earlier session wrote. Read "
                   "it as history, and leave it where it is.")
    out.append("")

    out.extend(request_lines(number, comments))

    criteria = issue_comments.find(comments, AC_OPEN)
    if criteria is not None:
        out.append("#### The acceptance criteria comment")
        out.append("")
        out.append((criteria.get("body") or "").strip())
        out.append("")
        out.append("Not yours: the orchestrator wrote it from an approved plan "
                   "and only ever fills it when it is empty. Leave it as it is.")
    elif AC_OPEN in body:
        out.append("The acceptance criteria are in the body, between `%s` and "
                   "`%s` — an issue from before they moved to a comment. They "
                   "are read from there; leave them as they are."
                   % (AC_OPEN, AC_CLOSE))
    else:
        out.append("There are no acceptance criteria of ours on this issue. "
                   "Agree them with me in the plan; once it is approved, the "
                   "orchestrator posts them as a comment — unless the "
                   "description already has an \"Acceptance criteria\" "
                   "heading of its own, in which case it posts nothing and "
                   "those are the starting point.")
    out.append("")
    return out


def request_lines(number, comments):
    """The "User request" comment as it stands, and the command that keeps it.

    Shared by step 1, which writes the comment, and step 2, which adds what the
    human asked for during development: both have to rewrite the one comment
    rather than post a second.
    """
    out = []
    request = issue_comments.find(comments, REQUEST)
    cid = issue_comments.comment_id(request) if request else None
    if request is not None and cid:
        out.append("#### Your \"User request\" comment")
        out.append("")
        out.append((request.get("body") or "").strip())
        out.append("")
        out.append("It exists — rewrite it in place, never add a second one: "
                   "`%s`." % issue_comments.edit_command(cid))
    else:
        out.append("There is no \"User request\" comment yet. Create it with "
                   "`%s`; the command prints its URL, and the number after "
                   "`#issuecomment-` is the id you rewrite it by: `%s`."
                   % (issue_comments.create_command(number),
                      issue_comments.edit_command("<id>")))
    out.append("")
    return out


def request(number, cwd=None):
    """Step 2's block: the "User request" comment and its command, or ""."""
    issue = issue_comments.fetch(number, cwd)
    if issue is None:
        return ""
    return "\n".join(request_lines(number, issue.get("comments"))).rstrip("\n")


def main():
    argv = sys.argv[1:]
    mode = None
    if argv and argv[0] == "--request":
        mode, argv = argv[0], argv[1:]
    if not argv or not argv[0].strip():
        return 0
    cwd = argv[1] if len(argv) > 1 else None
    try:
        build = request if mode == "--request" else render
        sys.stdout.write(build(argv[0].strip(), cwd))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
