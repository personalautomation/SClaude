#!/usr/bin/env python3
#
# The acceptance criteria — carried from the approved plan into a comment on
# the issue, and read back out of it for the steps that come after.
#
# Step 1 agrees them with the human inside the plan, under a heading of their
# own, and the plan is not shown for approval without them (the hook
# plan-on-disk.py). Once it is approved, the orchestrator posts them as a
# comment of their own on the issue, the list between a pair of markers — if
# the issue has none yet. After that the comment is where corrections land, and
# a later plan that disagrees with it is reported rather than written over.
# The one exception is growth: a criterion step 2 agreed with the human mid-way
# is appended after the session (--extend), and nothing already there changes.
# From there they are the one statement of what this feature has to do that
# outlives the worktree: the plan is rewritten whenever development deviates,
# the commits describe what was built rather than what was asked for, and
# `.sclaude/local/feature/` dies with the tree.
#
# A comment and not the description: the description is the task as a human
# set it, and it stays exactly that — see issue_comments.py. Issues from before
# the move carry the section in the body instead; it is still read there, and
# never written.
#
# The issue is also where QA works: it is the business record of the feature,
# the pull request a technical one. The boxes in the comment are ticked there,
# and the merge question reads them from there.
#
# Every later step reads the criteria from that one place rather than carrying
# a copy. A copy would be the thing that goes stale: the human edits the comment
# in GitHub, and a criterion embedded in a prompt two steps ago would then be
# quoting a requirement nobody holds any more.
#
# Reading is silent on any trouble, like issue_context and issue_chain: no gh,
# no network, no permissions, no criteria — empty output, and the prompt keeps
# whatever it says without the block. Writing (--sync) answers with a word, so
# that the orchestrator can say the copy did not happen.
import os
import re
import sys

# The markers of the criteria, from the module that declares all of ours. The
# path is added explicitly because this file is run as a script, from whatever
# directory the orchestrator happens to be in.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import issue_comments  # noqa: E402
from issue_comments import AC_CLOSE, AC_OPEN  # noqa: E402,F401

# A criterion's line inside the section: a markdown task-list item whose text
# starts with its identifier.
#
# The checkbox is matched and its state kept, but nothing here decides by it —
# whether a box is ticked is QA's business, a step being handed the list needs
# every criterion regardless, and the merge question only shows it. The identifier is captured because the commits refer to
# it (`Requirement: AC2`) and the number, not the wording, is what they agree
# on.
#
# The separator after the identifier is optional and greedy: a hand-edited list
# writes `AC1.`, `AC1:` or plain `AC1`, and the punctuation belongs to the
# identifier rather than to the text. Left to the text it produces a criterion
# reading "." — a line that is not a requirement but parses as one.
CRITERION = re.compile(
    r"^\s*-\s*\[(?P<done>[ xX])\]\s*(?P<id>AC\d+)\s*[.:)]*\s*(?P<text>.*?)\s*$")

# What the old issue template carried before step 1 had filled anything in. A
# section holding only this is empty, not written — otherwise the placeholder
# itself would be handed to step 2 as a requirement. New issues no longer get
# the section, but older bodies still hold it.
PLACEHOLDER = "_To be agreed during planning._"


def fetch(number, cwd=None):
    """The issue's body and comments, or None when they cannot be had."""
    return issue_comments.fetch(number, cwd)


def source(issue):
    """Where the issue's criteria live: (comment, text).

    Our comment when there is one. Otherwise the body, for an issue from before
    the criteria moved out of it — with comment None, so that nothing is ever
    written back there.
    """
    own = issue_comments.find(issue["comments"], AC_OPEN)
    if own is not None:
        return own, own.get("body") or ""
    return None, issue["body"]


def fetch_text(number, cwd=None):
    """The text holding the issue's criteria, or None."""
    issue = fetch(number, cwd)
    return None if issue is None else source(issue)[1]


def section(body):
    """The text between the markers, or "" when there is no complete pair.

    An opening marker without a closing one means the body was edited by hand
    and the pair broken. We read nothing then rather than reading to the end:
    everything below the break belongs to somebody else, and handing it to a
    step as a requirement is worse than handing it nothing.
    """
    if not body:
        return ""
    start = body.find(AC_OPEN)
    if start < 0:
        return ""
    end = body.find(AC_CLOSE, start + len(AC_OPEN))
    if end < 0:
        return ""
    return body[start + len(AC_OPEN):end].strip("\n")


def criteria(text):
    """The criteria in a block of text as a list of (id, text, done).

    Only lines that are task-list items with an `ACn` identifier count. Prose
    around them is ignored rather than rejected: step 1 may leave a sentence of
    context above the list, and a criterion is recognised by its shape.
    """
    out = []
    for line in (text or "").splitlines():
        found = CRITERION.match(line)
        if not found:
            continue
        text = found.group("text").strip()
        if not text or text == PLACEHOLDER:
            continue
        out.append((found.group("id"),
                    text,
                    found.group("done").lower() == "x"))
    return out


def parse(body):
    """The criteria in a comment's or a body's section, as (id, text, done)."""
    return criteria(section(body))


# --- the plan ------------------------------------------------------------------
#
# The approved plan is where the criteria are agreed: step 1 puts them at its
# head, under a heading of their own, and approving the plan is approving them.
# Two readers look for them there. The hook on ExitPlanMode refuses to show the
# human a plan without them, and the orchestrator copies them into the issue
# once the plan is approved. Both read the plan rather than the issue because
# the plan is always at hand: no network, no gh, and no question of who wrote
# the issue.
#
# The plan is read more loosely than the issue. The issue's section is ours and
# always in one shape; the plan is a model's prose, and a refusal that says "no
# criteria" to a plan that plainly has them sends the model round in circles.
# What counts is an identifier on a list item; what the plan's copy of the list
# looks like is normalised on the way into the issue.

# The heading the criteria sit under in the plan: any of the top three levels,
# and a trailing colon is the same heading.
PLAN_HEADING = re.compile(r"^(?P<level>#{1,3})\s+Acceptance criteria\s*:?\s*$",
                          re.IGNORECASE)
HEADING = re.compile(r"^(?P<level>#{1,6})\s")
FENCE = re.compile(r"^\s*(```|~~~)")

# A criterion in the plan: any list item — hyphen, star, plus or a number —
# with or without a checkbox, whose text starts with its identifier. A box the
# plan ticked is read and then dropped: a tick is QA's, not step 1's.
PLAN_CRITERION = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(?:\*\*)?(?P<id>AC\d+)(?:\*\*)?"
    r"\s*[.:)]*(?:\*\*)?\s*(?P<text>.*?)\s*$")

# The one honest alternative to a list: a change with nothing a person could
# check on a deployment, a refactor say. Spelled out as a line of its own, with
# the reason after the colon, so that it is told apart from a section somebody
# forgot to fill in. A reason is required — "No observable change:" alone is
# the placeholder again in other words.
NONE_DECLARED = re.compile(
    r"^\s*(?:-\s*)?[*_]*No observable change[*_]*\s*:[*_]*\s*(?P<why>.*?\S)\s*$",
    re.IGNORECASE)


def plan_section(text):
    """The text under the plan's acceptance criteria heading, or None.

    None when there is no such heading; "" when there is one with nothing under
    it. The two are told apart because the refusal for each says a different
    thing.

    The heading is looked for outside fenced code only: a plan quoting a
    markdown snippet must not have its criteria found inside the quote. Once
    in the section, a fence is part of it — step 1's prompt shows the no-change
    line in one, and a model copying the example copies the fence too — and a
    heading inside a fence does not end it.

    The section ends at the next heading of its own level or higher, and under
    a `#` heading at the next `##` too: a plan titled "# Acceptance criteria"
    and then "## How" has not put its implementation into its criteria.
    """
    out = []
    level = None
    fenced = False
    for line in (text or "").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if level is None:
            if not fenced:
                found = PLAN_HEADING.match(line)
                if found:
                    level = max(len(found.group("level")), 2)
            continue
        found = HEADING.match(line)
        if found and not fenced and len(found.group("level")) <= level:
            break
        out.append(line)
    if level is None:
        return None
    return "\n".join(out).strip("\n")


def plan_criteria(section_text):
    """The criteria in the plan's section, as a list of (id, text)."""
    out = []
    for line in (section_text or "").splitlines():
        found = PLAN_CRITERION.match(line)
        if not found:
            continue
        text = found.group("text").strip()
        if text and text != PLACEHOLDER:
            out.append((found.group("id"), text))
    return out


def plan_verdict(text):
    """What the plan says about acceptance: one of four words.

    "criteria"      — at least one ACn item;
    "none-declared" — no items, and a `No observable change: <why>` line;
    "empty"         — the heading is there, and nothing under it counts;
    "missing"       — no heading at all.
    """
    body = plan_section(text)
    if body is None:
        return "missing"
    if plan_criteria(body):
        return "criteria"
    for line in body.splitlines():
        if NONE_DECLARED.match(line):
            return "none-declared"
    return "empty"


def plan_content(text):
    """The lines the issue's section should hold, from the plan; [] for none.

    The criteria are rewritten into one shape rather than copied verbatim, so
    that whatever the plan's formatting, the issue holds lines parse() reads
    back — and every box unticked.
    """
    section_text = plan_section(text) or ""
    found = plan_criteria(section_text)
    if found:
        return ["- [ ] %s. %s" % (cid, body) for cid, body in found]
    for line in section_text.splitlines():
        match = NONE_DECLARED.match(line)
        if match:
            return ["No observable change: %s" % match.group("why")]
    return []


# A heading of that name a human wrote, with no markers of ours around a list.
OWN_HEADING = re.compile(r"^#{1,6}\s+Acceptance criteria\s*:?\s*$",
                         re.IGNORECASE | re.MULTILINE)


def merge_section(text, lines):
    """A comment's text with the section holding `lines`, or None.

    With both markers in place, only the span between them changes — a note QA
    wrote below the list survives. With neither, the text is a new comment's,
    and the section is the whole of it. With one marker and not the other the
    pair was broken by a hand edit, and nothing is written: where our section
    ends is then anybody's guess.
    """
    text = text or ""
    inner = "\n".join(lines)
    start = text.find(AC_OPEN)
    has_close = AC_CLOSE in text
    if start >= 0:
        end = text.find(AC_CLOSE, start + len(AC_OPEN))
        if end < 0:
            return None
        return text[:start + len(AC_OPEN)] + "\n" + inner + "\n" + text[end:]
    if has_close:
        return None
    block = "## Acceptance criteria\n\n%s\n%s\n%s\n" % (AC_OPEN, inner, AC_CLOSE)
    return text + gap(text) + block + NOTE


# What the comment says below the list. Addressed to whoever opens the issue:
# they did not take part in planning and need to know what the list is and
# where it came from.
NOTE = ("\n<sub>Agreed while planning and approved with the plan. QA ticks the "
        "boxes here. Written by <code>sclaude</code>; the issue description is "
        "left as its author wrote it.</sub>\n")


def gap(text):
    """What to add after `text` so that a new block starts after a blank line."""
    if not text.strip() or text.endswith("\n\n"):
        return ""
    return "\n" if text.endswith("\n") else "\n\n"


def render(number, cwd=None):
    """The block a step's prompt embeds, or "" when there is nothing to embed.

    A plain numbered list, for both readers. Step 2 is told what to build and
    refers to a criterion by its identifier. Step 3 puts the list into the pull
    request for the code's reviewer — without boxes, because the boxes are
    ticked in the issue, where QA works, and a second checklist in the PR is a
    second place for a tick to land and drift from the first.
    """
    found = parse(fetch_text(number, cwd))
    if not found:
        return ""

    out = ["#### Acceptance criteria",
           "",
           "Agreed with the human at step 1 and kept in issue #%s. This is what "
           "the feature has to do — the plan says how." % number,
           ""]
    for cid, text, _ in found:
        out.append("- **%s.** %s" % (cid, text))
    out.append("")
    out.append("They live in a comment on the issue, between `%s` and `%s`. "
               "If they look out of date, re-read them: "
               "`gh issue view %s --json comments`."
               % (AC_OPEN, AC_CLOSE, number))
    return "\n".join(out)


def differences(issue, plan):
    """How the issue's criteria and the plan's differ, as short phrases."""
    ours = dict((cid, text) for cid, text, _ in issue)
    theirs = dict(plan)
    out = []
    for cid, text in plan:
        if cid not in ours:
            out.append("%s is only in the plan" % cid)
        elif ours[cid] != text:
            out.append("%s reads differently" % cid)
    for cid, _, _ in issue:
        if cid not in theirs:
            out.append("%s is only in the issue" % cid)
    return out


def sync(number, plan_text, cwd=None):
    """Put the approved plan's criteria on the issue, if it has none yet.

    Returns (word, details). The word is one of:

    "written"     — there was no criteria comment, or ours was empty, and now
                    it holds the plan's list;
    "unchanged"   — the issue already says what the plan says;
    "differs"     — the issue has criteria of its own that differ from the
                    plan; nothing was written, and `details` says how;
    "nothing"     — the plan has nothing to copy;
    "unreadable"  — gh could not give us the issue;
    "torn"        — our comment has one marker without the other, so nothing
                    was written;
    "own-heading" — no criteria of ours, but a human wrote an "Acceptance
                    criteria" heading in the description; a second list of the
                    same name beside it would leave QA two, so nothing was
                    written;
    "refused"     — gh would not take the comment.

    Only an empty section is ever written. Once criteria are on the issue the
    issue is where corrections land: the human rewords one in GitHub, adds
    another, QA notes something under a third. A replan starting from an older
    list must not overwrite that — it is said out loud instead, and the human
    decides which side is right.

    The description is never written, whatever it holds. An issue from before
    the move with a filled section in its body is compared like a comment; one
    whose section is empty or the old placeholder gets a comment, and the
    placeholder stays where it was.
    """
    issue = fetch(number, cwd)
    if issue is None:
        return "unreadable", []
    lines = plan_content(plan_text)
    if not lines:
        return "nothing", []

    own, text = source(issue)
    if own is None and AC_OPEN not in text and AC_CLOSE not in text \
            and OWN_HEADING.search(text):
        return "own-heading", []

    # A torn pair reads as an empty section here. In our comment it is caught
    # by merge_section below, which refuses to write into it; in a body it is
    # nothing we would write into anyway.
    inner = section(text)
    written = inner.strip() and inner.strip() != PLACEHOLDER
    if written:
        planned = plan_criteria(plan_section(plan_text) or "")
        if planned:
            found = differences(parse(text), planned)
            return ("differs", found) if found else ("unchanged", [])
        # The plan declares no observable change; the issue says something.
        return ("unchanged", []) if inner.strip() == lines[0] else (
            "differs", ["the plan declares no observable change"])

    if own is None:
        done = issue_comments.post(number, merge_section("", lines), cwd)
    else:
        new = merge_section(text, lines)
        if new is None:
            return "torn", []
        cid = issue_comments.comment_id(own)
        done = cid is not None and issue_comments.edit(cid, new, cwd)
    return ("written", []) if done else ("refused", [])


def extend(number, plan_text, cwd=None):
    """Add the criteria step 2 agreed to the issue's list. (word, details).

    Development turns up requirements planning missed: the human asks for
    something mid-step, agrees it is a criterion, and the session adds it to
    the plan under the next free identifier. sync() would not carry it over —
    the list is already filled — and the issue, where QA ticks, would never
    hear of it.

    Only additions are written: a criterion whose identifier the issue does not
    have yet goes to the end of the list, unticked. Everything already there —
    the wording, the ticks, a note QA left — is the issue's, exactly as with
    sync(); a criterion that reads differently in the plan is reported, not
    rewritten.

    The words are sync()'s, plus "extended" (details name what was added, then
    what still differs) — and an empty list is filled the way sync() fills it.
    An issue keeping its criteria in the description is never written: it
    answers "differs" with what the plan has that the issue does not.
    """
    issue = fetch(number, cwd)
    if issue is None:
        return "unreadable", []
    own, text = source(issue)
    inner = section(text)
    if not inner.strip() or inner.strip() == PLACEHOLDER:
        return sync(number, plan_text, cwd)

    planned = plan_criteria(plan_section(plan_text) or "")
    if not planned:
        return "nothing", []
    have = parse(text)
    known = set(cid for cid, _, _ in have)
    added = [(cid, body) for cid, body in planned if cid not in known]
    # Only rewording is worth a word here. A criterion missing from the plan was
    # added in GitHub, which is where corrections are meant to land, and saying
    # so after every session would teach the human to skip the line.
    differ = [d for d in differences(have, planned) if d.endswith("differently")]
    if not added:
        return ("differs", differ) if differ else ("unchanged", [])
    if own is None:
        return "differs", ["%s is only in the plan" % cid for cid, _ in added] + differ

    new_lines = inner.rstrip("\n").splitlines() + \
        ["- [ ] %s. %s" % (cid, body) for cid, body in added]
    new = merge_section(text, new_lines)
    if new is None:
        return "torn", []
    cid = issue_comments.comment_id(own)
    if cid is None or not issue_comments.edit(cid, new, cwd):
        return "refused", []
    return "extended", ["%s added" % c for c, _ in added] + differ


def status(number, cwd=None):
    """The criteria as QA left them in the issue, one line each, or ""."""
    return "\n".join("%s %s. %s" % ("✓" if done else "☐", cid, text)
                     for cid, text, done in parse(fetch_text(number, cwd)))


def unticked(number, cwd=None):
    """The identifiers QA has not ticked yet, as "AC2, AC5", or ""."""
    return ", ".join(cid for cid, _, done in parse(fetch_text(number, cwd))
                     if not done)


def main():
    argv = sys.argv[1:]
    mode = None
    if argv and argv[0] in ("--sync", "--extend", "--status", "--unticked",
                            "--verdict"):
        mode, argv = argv[0], argv[1:]
    try:
        if mode == "--verdict":
            # The plan's file rather than an issue: no network involved.
            with open(argv[0]) as fh:
                sys.stdout.write(plan_verdict(fh.read()) + "\n")
            return 0
        if not argv or not argv[0].strip():
            return 0
        number = argv[0].strip()
        if mode in ("--sync", "--extend"):
            # The word on the first line, what differs on the lines after it.
            with open(argv[1]) as fh:
                plan_text = fh.read()
            cwd = argv[2] if len(argv) > 2 else None
            word, details = (sync if mode == "--sync" else extend)(
                number, plan_text, cwd)
            sys.stdout.write("\n".join([word] + details) + "\n")
            return 0 if word in ("written", "extended", "unchanged",
                                 "nothing") else 1
        cwd = argv[1] if len(argv) > 1 else None
        if mode == "--status":
            sys.stdout.write(status(number, cwd))
        elif mode == "--unticked":
            sys.stdout.write(unticked(number, cwd))
        else:
            sys.stdout.write(render(number, cwd))
    except Exception:
        return 1 if mode in ("--sync", "--extend", "--verdict") else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
