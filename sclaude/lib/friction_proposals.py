#!/usr/bin/env python3
"""A friction log that holds only proposals, as rows for the deferred file.

The friction review always puts a proposed CLAUDE.md rule off: the rules are
decided together once a month, by how often each comes back (_friction-body.md).
So a log with nothing else in it has nothing to decide, and on one feature
three friction reviews in a row were opus sessions whose whole work was one
line appended to friction-deferred.tsv. run_friction now asks this first, and
writes the rows itself when the answer is yes.

    friction_proposals.py <log> <project> <feature> <step>

Prints one row per proposal, in the deferred file's six tab-separated fields,
and exits 0 when every entry in the log is a proposal. Exits 1 and prints
nothing when any entry is something else, or the log cannot be read: that log
goes to a session as before.

An entry is the proposal line the step prompts describe,

    <date> proposal: <the rule>
    <date> proposal (<class>): <the rule>

followed by indented lines saying what it would have prevented. The class is
the deferred file's: a proposal that names none gets DEFAULT_CLASS, and the
monthly review groups by what the rule says when the classes do not.
"""
import re
import sys

DEFAULT_CLASS = "claude-md-proposal"
PROPOSAL = re.compile(
    r"(\d{4}-\d{2}-\d{2})\S*\s+proposal\s*(?:\(([a-z0-9][a-z0-9-]*)\))?\s*:\s*(.+)")


def one_line(text):
    return " ".join(text.split())


def rows(lines, project, feature, step):
    """The rows, or None when the log is not proposals alone."""
    entries = []
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        found = PROPOSAL.fullmatch(line.strip()) if not line[:1].isspace() else None
        if found:
            entries.append([found.group(1), found.group(2) or DEFAULT_CLASS,
                            found.group(3), []])
        elif line[:1].isspace() and entries:
            entries[-1][3].append(line.strip())
        else:
            return None
    if not entries:
        return None
    out = []
    for date, klass, rule, context in entries:
        text = "Proposal: " + one_line(rule)
        if context:
            text += " (" + one_line(" ".join(context)) + ")"
        out.append("\t".join([date, project, feature, step, klass, text]))
    return out


def main():
    if len(sys.argv) != 5:
        return 1
    try:
        with open(sys.argv[1], encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return 1
    got = rows(lines, *sys.argv[2:5])
    if got is None:
        return 1
    sys.stdout.write("\n".join(got) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
