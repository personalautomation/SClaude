#!/usr/bin/env python3
#
# A feature built in parts: what the plan says about them.
#
# Step 1 proposes splitting a feature too big for one review, and the person
# decides. A split feature stays one issue, one plan and one QA: the plan
# keeps a `## Parts` section, one `### Part <n> — <title>` heading for each,
# and every acceptance criterion says which part makes it true, `AC7. [part 2]
# …`. Step 2 then builds the parts one after another, each in a pull request
# of its own into the feature's branch, reviewed alone (parts.sh), and the
# feature's own pull request into main carries them all at the end.
#
# Read from the plan rather than kept in the state alone: the plan is what the
# person approved, and a replan that moves a line moves it here.
#
#   plan_parts.py list <plan>          one "<n>\t<title>" line per part; nothing
#                                      when the plan is not split (fewer than two)
#   plan_parts.py criteria <plan> <n>  the identifiers of part <n>'s criteria
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path

# The section's heading, at any of the top three levels.
SECTION = re.compile(r"^(?P<level>#{1,3})\s+Parts\s*:?\s*$", re.IGNORECASE)
HEADING = re.compile(r"^(?P<level>#{1,6})\s")
FENCE = re.compile(r"^\s*(```|~~~)")
# A part's heading under it: `### Part 2 — Tickets page`, with a dash of any
# kind, a colon, a full stop or only a space between the number and the title.
# The parts are the headings at the level of the first one: a deeper
# `#### Part 1 notes` inside a part is that part's text.
PART = re.compile(r"^(?P<level>#{2,6})\s+Part\s+(?P<n>\d+)\b\s*(?:[—–:.-]+\s*)?(?P<title>.*?)\s*$",
                  re.IGNORECASE)
# The part a criterion's text opens with: `[part 2] The tickets page lists…`.
# Bold around it is the plan's formatting, not the text's. `[PR 2]` is read
# the same: a plan written before the parts had a shape of their own marked
# them so, and the issue's list keeps the words it was given.
TAG = re.compile(r"^\s*(?:\*\*)?\[(?:part|pr)\s+(?P<n>\d+)\](?:\*\*)?\s*", re.IGNORECASE)


def plan_parts(text):
    """The parts the plan names, as [(n, title)] in their order; [] for a plan
    that is not split.

    Only under the `## Parts` heading, outside fenced code: a plan quoting an
    example of the section must not be read as split. One part alone is no
    split either — there is nothing to review apart.
    """
    out = []
    level = part_level = None
    fenced = False
    for line in (text or "").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if level is None:
            found = SECTION.match(line)
            if found:
                level = len(found.group("level"))
            continue
        found = PART.match(line)
        if found and part_level in (None, len(found.group("level"))):
            part_level = len(found.group("level"))
            out.append((int(found.group("n")), (found.group("title") or "").strip()))
            continue
        heading = HEADING.match(line)
        if heading and len(heading.group("level")) <= level:
            break
    numbers = [n for n, _ in out]
    if len(out) < 2 or numbers != list(range(1, len(out) + 1)):
        return []
    return out


def criterion_part(text):
    """The part a criterion's text names, or None when it names none."""
    found = TAG.match(text or "")
    return int(found.group("n")) if found else None


def of_part(criteria, n):
    """The criteria — tuples whose first two items are (id, text) — that part
    <n> answers for. One naming no part is the whole feature's, and every part
    keeps it in sight."""
    return [c for c in criteria if criterion_part(c[1]) in (None, n)]


def main(argv):
    if len(argv) >= 2 and argv[0] == "list":
        try:
            with open(argv[1]) as fh:
                text = fh.read()
        except OSError:
            return 0
        for n, title in plan_parts(text):
            print("%d\t%s" % (n, title))
        return 0
    if len(argv) >= 3 and argv[0] == "criteria":
        import acceptance
        try:
            with open(argv[1]) as fh:
                text = fh.read()
        except OSError:
            return 0
        found = acceptance.plan_criteria(acceptance.plan_section(text) or "")
        print(" ".join(cid for cid, _ in of_part(found, int(argv[2]))))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
