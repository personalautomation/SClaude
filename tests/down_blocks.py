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
# Both are real: the first is migration 0055, the second was 0048, whose header
# carries a rule of dashes that an end-of-line anchor did not match.
#
# The fixtures are the shapes actually in the product repository. Where it is
# checked out, every one of its migrations is classified too — instruments must
# stay testable without it, so that half is guarded.
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

# The header with a rule of dashes after it. 0048 writes it that way, and an
# anchor insisting on end-of-line after the colon missed the file — reporting
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
# policy take no rows with them. 0060 is exactly one `drop function`, and
# warning about it every time is how a warning stops being read.
for kind in ("drop function if exists public.f();",
             "drop view if exists public.v;",
             "drop trigger if exists t on public.x;",
             "drop policy if exists p on public.x;"):
    check("not-destructive-%s" % kind.split()[1], verdict(block("--   " + kind)), "runnable")

# (b) destructive: rows go.
for sql in ("delete from public.notifications where kind = 'x';",
            "truncate public.t;",
            "drop table public.t;",
            "alter table public.t drop column c;"):
    check("destructive-%s" % sql.split()[0], verdict(block("--   " + sql)), "destructive")

# (c) prose. The ellipsis case is the dangerous one: strip the inner comments
# and what is left parses, runs, and leaves production without the view.
danger = block(
    "--   -- profile_cards cannot lose columns by being replaced, so: drop the view,",
    "--   -- recreate it in the shape above without the six trailing columns.",
    "--",
    "--   drop view if exists public.profile_cards;",
    "--   -- ...recreate from section 7 of 0051's schema snapshot, ending at",
    "--   -- bio_search_text...",
    "--   revoke all on public.profile_cards from anon, authenticated;")
check("ellipsis-is-prose", verdict(danger), "prose")
check_true("ellipsis-says-why", "missing" in classify(danger)["reason"])
# And the statements are still returned: the report shows what it found rather
# than hiding it.
check_true("prose-still-reports-its-sql", len(classify(danger)["sql"]) > 0)

check("rebuild-is-prose",
      verdict(block("--   -- recreate the view from 0051 by hand",
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

# An English sentence flush among the statements — 0052 and 0059 write their
# closing paragraph inside the block, with the same indentation as the SQL.
mixed = block("--   update public.tiers set limits = '{}'::jsonb where code = 'free';",
              "--",
              "--   Nothing else goes back: no column, function, policy or grant is",
              "--   touched here, and a bio already written past 280 characters would",
              "--   simply stop validating on the next save.")
check("trailing-prose-does-not-become-sql", verdict(mixed), "runnable")
check("trailing-prose-kept-out-of-sql", len(classify(mixed)["sql"]), 1)

# A block that was written and says there is nothing to undo is not the same as
# no block at all — 0031. Calling it `absent` would accuse somebody of an
# omission and invite the next reader to "fix" a deliberate decision.
noted = block("--   the 0029 body, with `c.id <> (select auth.uid())` in place of the",
              "--   line above — which is the bug, so there is nothing worth going back to.")
check("note-without-statements-is-prose", verdict(noted), "prose")
check("absent-is-only-for-no-block",
      verdict("create table public.t (id int);\n"), "absent")


# --- statements across several lines ----------------------------------------

# 0055's `grant select (...)` runs to eight lines; grouping is by semicolon, not
# by line, or a rollback would run a third of a statement.
multi = block("--   grant select (id, username, avatar_media_id,",
              "--                 visibility, tier, created_at)",
              "--     on public.profiles to anon, authenticated;")
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


# --- against the real migrations --------------------------------------------
#
# Guarded: instruments is machine-level and must stay testable with no product
# checked out.

SOCIAL = os.path.expanduser("~/myapp/supabase/migrations")
if os.path.isdir(SOCIAL):
    # The anchors, each one a shape that cost something to get right.
    for name, want in (
            ("0060_cancel_email_change.sql", "runnable"),
            ("0061_announce_a_moved_address.sql", "runnable"),
            ("0059_email_changed_notification.sql", "destructive"),
            ("0048_country_points.sql", "destructive"),
            ("0055_links_phone_and_tax.sql", "prose"),
            ("0051_bio_plain_text_without_recursion.sql", "prose"),
            ("0031_people_districts_null_caller.sql", "prose"),
    ):
        path = os.path.join(SOCIAL, name)
        if os.path.isfile(path):
            check("real-%s" % name[:4], classify_file(path)["verdict"], want)

    # And the property that matters across the whole set: a block is called
    # absent only when the file really has no `-- down:` line, and nothing
    # offered for execution holds a line that is not a statement.
    header = re.compile(r"^--[ \t]*down:", re.M)
    opener = re.compile(
        r"^\s*(?:create|drop|alter|grant|revoke|insert|update|delete|truncate"
        r"|comment|set|select|with|do|begin|commit|refresh|analyze|vacuum|reindex)\b",
        re.I)
    missed = phantom = stray = 0
    for entry in sorted(os.listdir(SOCIAL)):
        if not entry.endswith(".sql"):
            continue
        path = os.path.join(SOCIAL, entry)
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
