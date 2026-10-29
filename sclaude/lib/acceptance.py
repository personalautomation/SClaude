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
# A criterion the review reworded in the plan is the other: it is shown to the
# human as the review closes, and written over the issue's only at their yes
# (--reword).
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
# the pull request a technical one. The boxes in the comment are ticked there —
# by QA, or all at once by sclaude when the project lets it accept (`qa` in
# its config, --tick) — and the merge question reads them from there.
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

# A criterion's cases: the list items indented under it, when its first line
# only leads into them ("The total shows:" and one item per case). They are
# part of its text — without them the line promises nothing, and a box ticked
# against it accepts nothing either.
#
# Only list items count. QA writes its note under a criterion as an indented
# line too, and that note is the issue's, never the plan's: read as part of the
# text, it would make every criterion QA wrote under read differently from the
# plan, and a rewording at the person's yes would erase it. A criterion the plan
# wraps onto an indented line of prose is read without that line, for the same
# reason: the two cannot be told apart. A note QA writes as a list item is
# the other side of that: it reads as a case, so the criterion reads
# differently from the plan, and a rewording the person approves, having seen
# both texts, may replace it — guessing which items are notes would be wrong
# either way. A box on a case is dropped, like the plan's tick on the
# criterion: the criterion's own box is the one QA ticks.
#
# Rarer shapes are not read, on purpose: a case wrapped onto a second line, a
# criterion among another one's cases, a code sample under a criterion. Plans
# write one line per item, each such shape would be a rule of its own here,
# and a loss shows plainly in the issue the person reads.
CASE = re.compile(r"^(?P<indent> +)(?P<mark>(?:[-*+]|\d+[.)])\s+)"
                  r"(?:\[[ xX]\]\s*)?(?P<rest>\S.*?)\s*$")


def with_cases(lines, pattern):
    """Each line `pattern` matches, with the cases under it: (match, cases, at).

    `cases` is the text the criterion carries on, "" when it has none: every
    item under it on a line of its own, the shallowest two spaces in and the
    deeper ones as much further as they were, a tab in the indent counted as
    four columns.
    `at` lists the indices of the criterion's line and of its cases' lines,
    for a writer replacing them. The lines under a criterion end at the next
    criterion, or a line no deeper than the criterion's own (an item beside
    it); a blank line ends nothing, since a list written loose is the same
    list. A note on a line of prose among them is passed over and left out;
    one written as a list item is a case (see CASE).
    """
    out = []
    current = None
    for index, line in enumerate(lines):
        # Tabs in the indent count as four columns; one inside the text is a
        # space, so the text reads the same wherever its line starts.
        body = line.lstrip(" \t")
        line = line[:len(line) - len(body)].expandtabs(4) + body.replace("\t", " ")
        found = pattern.match(line)
        indent = len(line) - len(line.lstrip(" "))
        if found:
            current = (found, [], [index], indent)
            out.append(current)
            continue
        if current is None:
            continue
        case = CASE.match(line)
        if not line.strip():
            continue
        if indent <= current[3]:
            current = None
        elif case:
            current[1].append(case)
            current[2].append(index)
    result = []
    for found, cases, at, _ in out:
        text = ""
        if cases:
            depth = min(len(c.group("indent")) for c in cases)
            text = "".join("\n  %s%s%s" % (c.group("indent")[depth:],
                                            c.group("mark"), c.group("rest"))
                           for c in cases)
        result.append((found, text, at))
    return result


def criterion_line(cid, body):
    """A criterion written into the issue's section, its box empty."""
    head, cases = (body.split("\n", 1) + [""])[:2]
    line = ("- [ ] %s. %s" % (cid, head)).rstrip()
    return line + ("\n" + cases if cases else "")


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
    for found, cases, _ in with_cases((text or "").splitlines(), CRITERION):
        text = found.group("text").strip()
        if not (text or cases) or text == PLACEHOLDER:
            continue
        out.append((found.group("id"),
                    text + cases,
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
    for found, cases, _ in with_cases((section_text or "").splitlines(),
                                      PLAN_CRITERION):
        text = found.group("text").strip()
        if (text or cases) and text != PLACEHOLDER:
            out.append((found.group("id"), text + cases))
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
        return [criterion_line(cid, body) for cid, body in found]
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
        [criterion_line(cid, body) for cid, body in added]
    new = merge_section(text, new_lines)
    if new is None:
        return "torn", []
    cid = issue_comments.comment_id(own)
    if cid is None or not issue_comments.edit(cid, new, cwd):
        return "refused", []
    return "extended", ["%s added" % c for c, _ in added] + differ


def reword(number, plan_text, cwd=None, write=False):
    """The criteria the plan words otherwise than the issue. (word, details).

    The review changes what a feature does at the person's word, and the
    criterion that described the old behaviour is reworded in the plan, under
    the same identifier. extend() reports such a criterion and leaves it — the
    issue is where corrections land — so QA, or the automatic acceptance,
    ticked the wording nobody built any more. This lists them for the person,
    and with `write` puts the plan's wording into our comment, at the person's
    yes.

    Only criteria both sides have and word differently are touched. Their box
    is emptied: a tick was given to the old text. Every other line, the ticks
    and a prose note QA left stay as they were, as sync() and extend() keep
    everything; a note written as a list item is a case (see CASE) and goes
    with the wording. A criterion a person reworded in GitHub reads
    differently too, which is why nothing is written without that yes.

    "differs"     — details are "<id>\\t<issue's text>\\t<plan's text>" lines;
    "reworded"    — with `write`, those criteria now read as the plan does;
    "unchanged"   — nothing both sides have reads differently;
    "body"        — the same details, for criteria that live in the
                    description, which is never written: listing or not;
    and "unreadable", "torn", "refused" as for tick_all().
    """
    issue = fetch(number, cwd)
    if issue is None:
        return "unreadable", []
    own, text = source(issue)
    planned = dict(plan_criteria(plan_section(plan_text) or ""))
    changed = [(cid, have, planned[cid]) for cid, have, _ in parse(text)
               if cid in planned and planned[cid] != have]
    if not changed:
        return "unchanged", []
    # One line a criterion, for the shell reading them with `read`: the
    # breaks before its cases are shown, not kept.
    details = ["\t".join(part.replace("\n", " ⏎ ") for part in row)
               for row in changed]
    # Before the listing's word: a yes to writing a description is a yes to
    # nothing, so the person is not asked for one.
    if own is None:
        return "body", details
    if not write:
        return "differs", details
    new_text = dict((cid, body) for cid, _, body in changed)
    lines = section(text).split("\n")
    # The criterion's line and its cases make way for the plan's wording, and
    # the blank lines of a list written loose with them; a prose note QA left
    # among them stays where it was.
    for found, _, at in reversed(with_cases(lines, CRITERION)):
        cid = found.group("id")
        if cid in new_text:
            for index in reversed(range(at[0] + 1, at[-1] + 1)):
                if index in at or not lines[index].strip():
                    del lines[index]
            lines[at[0]] = criterion_line(cid, new_text[cid])
    new = merge_section(text, lines)
    if new is None:
        return "torn", details
    cid = issue_comments.comment_id(own)
    if cid is None or not issue_comments.edit(cid, new, cwd):
        return "refused", details
    return "reworded", details


def status(number, cwd=None):
    """The criteria as QA left them in the issue, one line each, or ""."""
    return "\n".join("%s %s. %s" % ("✓" if done else "☐", cid, text)
                     for cid, text, done in parse(fetch_text(number, cwd)))


def tick_all(number, cwd=None):
    """Tick every criterion in our comment: QA accepted from sclaude. A word.

    "ticked"     — the boxes that were empty are ticked now;
    "already"    — every box was ticked;
    "nothing"    — the issue has no criteria to tick;
    "body"       — the criteria live in the description of an issue from
                   before the move, which is never written;
    "unreadable" — gh could not give us the issue;
    "torn"       — our comment has one marker without the other;
    "refused"    — gh would not take the edit.

    Only the boxes change. The wording and any note QA left stay as they are,
    the same promise sync() and extend() keep.
    """
    issue = fetch(number, cwd)
    if issue is None:
        return "unreadable"
    own, text = source(issue)
    # A pair broken by a hand edit reads as no criteria at all; said apart
    # here, so an acceptance does not go through quietly with none ticked.
    start = text.find(AC_OPEN) if own is not None else -1
    if own is not None and (
            (start >= 0 and text.find(AC_CLOSE, start + len(AC_OPEN)) < 0)
            or (start < 0 and AC_CLOSE in text)):
        return "torn"
    found = parse(text)
    if not found:
        return "nothing"
    if all(done for _, _, done in found):
        return "already"
    if own is None:
        return "body"
    lines = [BOX.sub(r"\1x]", line, count=1) if CRITERION.match(line) else line
             for line in section(text).split("\n")]
    new = merge_section(text, lines)
    if new is None:
        return "torn"
    cid = issue_comments.comment_id(own)
    if cid is None or not issue_comments.edit(cid, new, cwd):
        return "refused"
    return "ticked"


# The empty box of a criterion line, for tick_all.
BOX = re.compile(r"^(\s*-\s*\[) \]")


def unticked(number, cwd=None):
    """The identifiers QA has not ticked yet, as "AC2, AC5", or ""."""
    return ", ".join(cid for cid, _, done in parse(fetch_text(number, cwd))
                     if not done)


def main():
    argv = sys.argv[1:]
    mode = None
    if argv and argv[0] in ("--sync", "--extend", "--status", "--unticked",
                            "--verdict", "--tick", "--reworded", "--reword"):
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
        if mode in ("--reworded", "--reword"):
            # --reworded lists, --reword writes; the word first either way.
            with open(argv[1]) as fh:
                plan_text = fh.read()
            cwd = argv[2] if len(argv) > 2 else None
            word, details = reword(number, plan_text, cwd, write=mode == "--reword")
            sys.stdout.write("\n".join([word] + details) + "\n")
            return 0 if word in ("differs", "reworded", "unchanged", "body") else 1
        cwd = argv[1] if len(argv) > 1 else None
        if mode == "--tick":
            word = tick_all(number, cwd)
            sys.stdout.write(word + "\n")
            return 0 if word in ("ticked", "already", "nothing") else 1
        if mode == "--status":
            sys.stdout.write(status(number, cwd))
        elif mode == "--unticked":
            sys.stdout.write(unticked(number, cwd))
        else:
            sys.stdout.write(render(number, cwd))
    except Exception:
        return 1 if mode in ("--sync", "--extend", "--verdict", "--tick",
                             "--reworded", "--reword") else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
