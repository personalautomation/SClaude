#!/usr/bin/env python3
#
# Reading the `-- down:` block of a migration, and saying honestly what can be
# done with it.
#
# The project's rule (docs/database-operations.md) is that every migration ends
# with a commented block holding the statements that put it back, and the rule
# says outright what they are: "They are comments, not a mechanism: nothing runs
# them, somebody reads them."
#
# A production rollback wants to run them anyway, because rolling the code back
# and leaving the schema ahead is half an answer. That is possible for some of
# them and impossible for others, and the whole value of this file is telling
# the two apart before anything touches production. It never runs anything
# itself.
#
# Four verdicts, and the interesting ones are the last two:
#
#   runnable     every statement is there and can be executed as it stands.
#   destructive  runnable, and it deletes rows a person would miss.
#   prose        the block is a note to a human, not a script. It may look like
#                SQL — that is exactly the case worth catching.
#   absent       no `-- down:` block at all. The loudest of the four: nothing
#                was written down when the migration shipped.
#
# Verified against all 61 migrations in the product repository; the shapes below
# are the ones that are actually there, not defensive guesses.
import glob
import json
import os
import re
import sys

# The block opens with this line and runs to the first line that is not a
# comment (usually the end of the file).
#
# The trailing run of dashes is not decoration to be tolerated grudgingly: 0048
# writes the header as `-- down: ------------------------------...`, and an
# anchor that insisted on end-of-line after the colon missed that file
# entirely — reporting "nothing was written down" about a block that drops two
# columns. A missed block is the worst answer this file can give, because it
# reads as the safe one.
OPEN = re.compile(r"^--[ \t]*down:[ \t]*-*[ \t]*$", re.M)

# A line inside the block that is itself a comment once the outer `--` comes
# off: `--   -- recreate the view ...`. These are prose written among the
# statements rather than around them, and finding one is not by itself a reason
# to refuse — see ELLIPSIS.
INNER_COMMENT = re.compile(r"^\s*--")

# What makes a block prose rather than a script: it points at something the
# reader has to go and get.
#
# This is the rule that matters most, and it earns its place from a real file.
# 0055's block reads:
#
#     drop view if exists public.profile_cards;
#     -- ...recreate from section 7 of 0051's schema snapshot, ending at
#     -- bio_search_text...
#     revoke all on public.profile_cards from anon, authenticated;
#
# Strip the inner comments and what is left parses, runs, and leaves production
# without the view — the `drop` happens, the recreation does not. A block whose
# missing half lives inside a comment is the one shape that must never be
# called runnable, and an ellipsis is how this repository writes "and the rest
# goes here".
ELLIPSIS = re.compile(r"\.\.\.|…")

# Phrases that say a human has to do it. Matched against the block's inner
# comments only, so an ordinary explanatory sentence does not trip them.
BY_HAND = re.compile(
    r"\brecreate\b|\brebuild\b|\bby hand\b|\bmanually\b|\bsee (?:section|migration)\b",
    re.I)

# A dollar-quoted body — `as $$ ... $$` — which is how a function is written.
#
# Inside one, a semicolon ends a statement of the function's own language and
# not the statement being read, so the line-by-line grouping below cannot tell
# where the thing ends. 0051's block holds a whole plpgsql function that way,
# and the grouping split it into nine fragments, gluing the English sentence
# above it onto the first. psql itself handles `$$` correctly — the limit is in
# this reader, not in postgres — so the honest answer is to refuse rather than
# to half-parse it.
DOLLAR_QUOTED = re.compile(r"\$\$|\$[A-Za-z_][A-Za-z0-9_]*\$")

# A fragment of English where a statement should be. Every SQL statement in
# these blocks opens with a verb; a sentence does not, and the ones that appear
# here are introductions to the block ("The 0050 body, which is the bug this
# migration exists to remove").
STATEMENT_START = re.compile(
    r"^\s*(?:create|drop|alter|grant|revoke|insert|update|delete|truncate|comment"
    r"|set|select|with|do|begin|commit|refresh|analyze|vacuum|reindex)\b",
    re.I)

# A statement that removes rows. `drop table` and `alter table ... drop column`
# take the rows with them; `delete` and `truncate` are about nothing else.
#
# Deliberately not `drop function`, `drop view`, `drop trigger` or `drop
# policy`: those remove behaviour, and the rows they read stay where they are.
# 0060's block is exactly one `drop function` and is an ordinary reversal;
# calling it destructive would put a warning in front of the human every time
# and teach them to click through it.
DESTRUCTIVE = re.compile(
    r"^\s*(?:delete\s+from|truncate|drop\s+table|drop\s+schema)\b"
    r"|^\s*alter\s+table\s+\S+\s+drop\s+column\b",
    re.I | re.M)

# The forward direction: a migration that took something away. Its old code
# cannot run against the new schema, which is what decides whether rolling the
# code back alone is safe.
FORWARD_DESTRUCTIVE = re.compile(
    r"^\s*(?:drop\s+table|drop\s+schema)\b"
    r"|^\s*alter\s+table\s+\S+\s+(?:drop\s+column|alter\s+column\s+\S+\s+type)\b"
    r"|^\s*alter\s+table\s+\S+\s+rename\s+column\b",
    re.I | re.M)


def extract(text):
    """The `-- down:` block's lines with the outer `--` removed, or None.

    None means there is no block. An empty list means there is one and it holds
    nothing, which is the same thing to a caller and is reported as `absent`.
    """
    found = OPEN.search(text)
    if not found:
        return None
    out = []
    for line in text[found.end():].split("\n"):
        stripped = line.rstrip()
        if not stripped.strip():
            out.append("")
            continue
        if not stripped.lstrip().startswith("--"):
            # The block ends at the first line that is not a comment.
            break
        out.append(stripped.lstrip()[2:])
    return out


def split(lines):
    """The block's lines as (sql, prose).

    Indentation is not the test, though it looks like one: the blocks are
    indented by three spaces in most files and by one in 0052, and the prose
    around them follows the same indentation. What separates them is whether a
    line is itself a comment — `-- recreate the view` inside the block — and
    whether it looks like a statement.

    A line that is neither is prose: the trailing paragraphs that explain what
    the rollback costs ("Rolling this back therefore erases the record of every
    address change already announced") are written flush inside the block in
    0052 and 0059, and treating them as SQL would hand psql an English
    sentence.
    """
    sql, prose = [], []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if INNER_COMMENT.match(text):
            prose.append(text.lstrip("-").strip())
            continue
        sql.append(text)
    # A statement ends in a semicolon somewhere in the group; a paragraph does
    # not. We decide per contiguous group rather than per line, because a
    # statement is routinely written across several lines — 0055's `grant
    # select (id, username, ...)` runs to eight.
    statements, sentences = [], []
    group = []
    for line in sql + [""]:
        if line:
            group.append(line)
            if not line.endswith(";"):
                continue
        if group:
            joined = " ".join(group)
            (statements if joined.rstrip().endswith(";") else sentences).append(joined)
            group = []
    prose.extend(sentences)
    return statements, prose


def classify(text, path=None):
    """One migration's down block, as a record.

    `sql` is what would be run — and it is only ever offered for the `runnable`
    and `destructive` verdicts. For `prose` it is still returned, because the
    report shows the human what it found rather than hiding it.
    """
    name = os.path.basename(path) if path else ""
    version = name.split("_", 1)[0] if name else ""
    record = {
        "file": name,
        "version": version,
        "verdict": "absent",
        "sql": [],
        "prose": [],
        "reason": "",
        "forward_destructive": bool(FORWARD_DESTRUCTIVE.search(strip_down(text))),
    }

    lines = extract(text)
    if lines is None:
        record["reason"] = "no `-- down:` block — nothing was written down"
        return record

    statements, prose = split(lines)
    record["sql"] = statements
    record["prose"] = prose

    if not statements:
        # A block that was written and holds no statements is not the same as no
        # block at all, and the two must not share a verdict. 0031's says "the
        # 0029 body, with ... — which is the bug, so there is nothing here worth
        # going back to": somebody thought about the rollback and concluded it
        # should not happen. Reporting that as "nothing was written down" would
        # accuse them of an omission and, worse, would read to the next person as
        # a gap to be filled rather than a decision to be respected.
        record["verdict"] = "prose"
        record["reason"] = ("the block is a note with no statements in it"
                            if prose else "the block is empty")
        return record

    # Prose first: a block that points elsewhere is not runnable however well
    # its statements parse. This order is the whole point — 0055 would
    # otherwise come back runnable and drop a view it cannot put back.
    joined_prose = " ".join(prose)
    if ELLIPSIS.search(joined_prose) or ELLIPSIS.search(" ".join(statements)):
        record["verdict"] = "prose"
        record["reason"] = "an ellipsis stands where statements should be — part of it is missing"
        return record
    if BY_HAND.search(joined_prose):
        record["verdict"] = "prose"
        record["reason"] = "it tells a person what to rebuild rather than saying how"
        return record

    # A function body defeats the grouping above — see DOLLAR_QUOTED. Refusing
    # is the honest answer: what this reader produces for such a block is
    # fragments, and running fragments against production is the one outcome
    # worth every other precaution here.
    if any(DOLLAR_QUOTED.search(s) for s in statements):
        record["verdict"] = "prose"
        record["reason"] = ("it defines a function with a $$ body, which this "
                            "reader cannot split into statements safely")
        return record

    # A "statement" that does not begin with a verb is a sentence that slipped
    # through the grouping. One is enough to refuse the block: it means the
    # split is wrong here, and a wrong split is how prose reaches psql.
    stray = [s for s in statements if not STATEMENT_START.match(s)]
    if stray:
        record["verdict"] = "prose"
        record["reason"] = ("prose is mixed in among the statements (%s…)"
                            % stray[0][:40].strip())
        return record

    if DESTRUCTIVE.search("\n".join(statements)):
        record["verdict"] = "destructive"
        record["reason"] = "it removes rows"
        return record

    record["verdict"] = "runnable"
    record["reason"] = "%d statement(s)" % len(statements)
    return record


def strip_down(text):
    """The migration without its down block — the forward statements alone."""
    found = OPEN.search(text)
    return text[:found.start()] if found else text


def classify_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return classify(fh.read(), path)
    except OSError:
        return {"file": os.path.basename(path), "version": "", "verdict": "absent",
                "sql": [], "prose": [], "reason": "the file could not be read",
                "forward_destructive": False}


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--classify":
        argv = argv[1:]
    paths = []
    for arg in argv:
        paths.extend(sorted(glob.glob(arg)) if any(c in arg for c in "*?[") else [arg])
    if not paths:
        return 0
    for path in paths:
        sys.stdout.write(json.dumps(classify_file(path), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
