#!/usr/bin/env python3
#
# A test bench for reading a migration's `-- down:` block.
#
# This is the one piece of the rollback that decides whether SQL runs against
# production, so the cases below are chosen for the ways it can be wrong rather
# than for coverage. Two of them cost more than the rest:
#
#   * a block called runnable that is not — its `drop` runs, the half that puts
#     the thing back sits inside a comment, and production loses a view nobody
#     can rebuild from the file;
#   * a block missed entirely, reported as "nothing was written down" — which
#     reads as the safe answer and is how a destructive block goes unmentioned.
#
# Both happened: the first in a block that dropped a view and rebuilt it in a
# comment, the second in a block whose header carried a rule of dashes that an
# end-of-line anchor did not match.
#
# The fixtures are shapes real migrations were written in, with neutral names.
# A product's whole migrations folder can be classified too, by pointing
# SCLAUDE_MIGRATIONS at it: instruments stays testable without one.
#
# Run it with: python3 tests/down_blocks.py
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
from down_blocks import classify, classify_file, extract, split

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def verdict(text):
    return classify(text)["verdict"]


def block(*lines):
    """A migration whose forward half is trivial and whose down block is given."""
    return "create table public.t (id int);\n\n-- down:\n" + "\n".join(lines) + "\n"


# --- finding the block -------------------------------------------------------

check("no-block-is-none", extract("create table public.t (id int);\n"), None)

# The header with a rule of dashes after it. A real migration wrote it that
# way, and an anchor insisting on end-of-line after the colon missed the file — reporting
# "nothing was written down" about a block that drops two columns.
ruled = ("create table public.t (id int);\n"
         "-- down: ---------------------------------------------------------\n"
         "--\n"
         "--   alter table public.t drop column if exists x;\n")
check("ruled-header-found", extract(ruled) is not None, True)
check("ruled-header-classified", verdict(ruled), "destructive")

# The block ends at the first line that is not a comment.
stops = block("--   drop view if exists public.v;") + "\nselect 1;\n"
check("block-stops-at-code", len([l for l in extract(stops) if "select 1" in l]), 0)


# --- the three classes -------------------------------------------------------

# (a) runnable: plain statements, nothing removed.
check("runnable-one-statement",
      verdict(block("--", "--   drop function if exists public.f();")),
      "runnable")
check("runnable-several",
      verdict(block("--   drop trigger if exists t on public.x;",
                    "--   drop function if exists public.f();")),
      "runnable")

# Dropping behaviour is not destructive: a function, a view, a trigger and a
# policy take no rows with them. A block that is exactly one `drop function`
# is common, and warning about it every time is how a warning stops being read.
for kind in ("drop function if exists public.f();",
             "drop view if exists public.v;",
             "drop trigger if exists t on public.x;",
             "drop policy if exists p on public.x;"):
    check("not-destructive-%s" % kind.split()[1], verdict(block("--   " + kind)), "runnable")

# (b) destructive: rows go.
for sql in ("delete from public.events where kind = 'x';",
            "truncate public.t;",
            "drop table public.t;",
            "alter table public.t drop column c;"):
    check("destructive-%s" % sql.split()[0], verdict(block("--   " + sql)), "destructive")

# (c) prose. The ellipsis case is the dangerous one: strip the inner comments
# and what is left parses, runs, and leaves production without the view.
danger = block(
    "--   -- the view cannot lose columns by being replaced, so: drop it,",
    "--   -- recreate it in the shape above without the trailing columns.",
    "--",
    "--   drop view if exists public.v;",
    "--   -- ...recreate from the previous schema snapshot, ending at",
    "--   -- the last column...",
    "--   revoke all on public.v from anon, authenticated;")
check("ellipsis-is-prose", verdict(danger), "prose")
check_true("ellipsis-says-why", "missing" in classify(danger)["reason"])
# And the statements are still returned: the report shows what it found rather
# than hiding it.
check_true("prose-still-reports-its-sql", len(classify(danger)["sql"]) > 0)

check("rebuild-is-prose",
      verdict(block("--   -- recreate the view from the earlier migration by hand",
                    "--   drop view if exists public.v;")),
      "prose")

# A function body: a semicolon inside `$$` does not end the statement, so this
# reader cannot split it. psql could; we refuse rather than half-parse.
check("dollar-quoted-is-prose",
      verdict(block("--   create or replace function public.f() returns text",
                    "--   language plpgsql as $$",
                    "--   begin",
                    "--     return 'x';",
                    "--   end;",
                    "--   $$;")),
      "prose")

# An English sentence flush among the statements: migrations write their
# closing paragraph inside the block, with the same indentation as the SQL.
mixed = block("--   update public.plans set limits = '{}'::jsonb where code = 'free';",
              "--",
              "--   Nothing else goes back: no column, function, policy or grant is",
              "--   touched here, and a value already written past the new limit would",
              "--   simply stop validating on the next save.")
check("trailing-prose-does-not-become-sql", verdict(mixed), "runnable")
check("trailing-prose-kept-out-of-sql", len(classify(mixed)["sql"]), 1)

# A block that was written and says there is nothing to undo is not the same as
# no block at all. Calling it `absent` would accuse somebody of an
# omission and invite the next reader to "fix" a deliberate decision.
noted = block("--   the earlier body, with the check above in place of this one,",
              "--   which is the bug, so there is nothing worth going back to.")
check("note-without-statements-is-prose", verdict(noted), "prose")
check("absent-is-only-for-no-block",
      verdict("create table public.t (id int);\n"), "absent")


# --- statements across several lines ----------------------------------------

# A `grant select (...)` can run to several lines; grouping is by semicolon, not
# by line, or a rollback would run a third of a statement.
multi = block("--   grant select (id, name, picture_id,",
              "--                 visibility, plan, created_at)",
              "--     on public.accounts to anon, authenticated;")
stmts, _ = split(extract(multi))
check("multiline-is-one-statement", len(stmts), 1)
check_true("multiline-joined", stmts[0].startswith("grant select (id"))
check_true("multiline-complete", stmts[0].endswith(";"))


# --- the forward direction ---------------------------------------------------
#
# Whether the migration itself took something away decides whether rolling the
# code back alone is safe: old code against an additive schema is fine, against
# a dropped column it is not.

check("forward-additive",
      classify("alter table public.t add column c int;\n")["forward_destructive"],
      False)
check("forward-drops-column",
      classify("alter table public.t drop column c;\n")["forward_destructive"],
      True)
check("forward-renames-column",
      classify("alter table public.t rename column a to b;\n")["forward_destructive"],
      True)
# The down block must not be read as the forward direction: its `drop` is the
# undoing of an `add`, not a destruction.
check("forward-ignores-the-down-block",
      classify(block("--   alter table public.t drop column c;"))["forward_destructive"],
      False)


# --- against a product's migrations ----------------------------------------
#
# Optional: instruments is machine-level and must stay testable with no product
# checked out. SCLAUDE_MIGRATIONS names a folder of migrations, and the property
# that matters across a whole set is checked on it: a block is called absent
# only when the file really has no `-- down:` line, and nothing offered for
# execution holds a line that is not a statement.

MIGRATIONS = os.environ.get("SCLAUDE_MIGRATIONS", "")
if MIGRATIONS and os.path.isdir(MIGRATIONS):
    header = re.compile(r"^--[ \t]*down:", re.M)
    opener = re.compile(
        r"^\s*(?:create|drop|alter|grant|revoke|insert|update|delete|truncate"
        r"|comment|set|select|with|do|begin|commit|refresh|analyze|vacuum|reindex)\b",
        re.I)
    missed = phantom = stray = 0
    for entry in sorted(os.listdir(MIGRATIONS)):
        if not entry.endswith(".sql"):
            continue
        path = os.path.join(MIGRATIONS, entry)
        record = classify_file(path)
        with open(path, encoding="utf-8") as fh:
            has_block = header.search(fh.read()) is not None
        if has_block and record["verdict"] == "absent":
            missed += 1
        if not has_block and record["verdict"] != "absent":
            phantom += 1
        if record["verdict"] in ("runnable", "destructive"):
            stray += sum(1 for s in record["sql"] if not opener.match(s))
    check("real-no-block-missed", missed, 0)
    check("real-no-phantom-block", phantom, 0)
    check("real-no-prose-among-statements", stray, 0)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
