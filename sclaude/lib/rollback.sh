#!/usr/bin/env bash
#
# Putting production back.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# The cycle could ship to production and had no way back. A red production
# regression set a label and opened fixing sessions — against a live broken
# production, up to two of them, minutes each. The mark said what was wrong; it
# did nothing about it.
#
# So the order is reversed here: production is restored first, and only then is
# anything fixed. Restoring is two halves that are not symmetrical.
#
# The code half is exact. `vercel rollback` moves the production alias back to a
# deployment that is still on hosting, and that deployment is the one this
# feature displaced — recorded before shipping, when the answer was still
# unambiguous.
#
# The database half cannot be. Migrations here are forward-only, prod has
# neither PITR nor physical backups, and the way back is written as a commented
# `-- down:` block that the project's own documentation calls "comments, not a
# mechanism: nothing runs them, somebody reads them". A third of the migrations
# have no block at all, and among those that do are blocks whose missing half
# lives inside a comment. So this runs what is genuinely runnable, with the
# human agreeing to it, and refuses the rest out loud — naming every migration
# either way. down_blocks.py is the part that tells them apart.
#
# What must never happen is the quiet middle: a block half-run, or a migration
# skipped without being named. A schema that is ahead of the code can at least
# be described.

# --- what is on hosting ------------------------------------------------------

# The project's production deployments, newest first, as
# "<url>\t<sha>\t<state>\t<createdAt>\t<ready>". `ready` is when the build
# finished — the moment a production deployment takes the alias — and is empty
# for one that never got there.
#
# From the main repository, always: the link to the Vercel project lives in
# $REPO/.vercel, and a worktree has none — the same reason the preview deploy is
# launched from here with a path rather than by cd-ing into the tree.
#
# Silent and empty on anything unknown: no vercel, no network, not logged in.
# The callers treat emptiness as "we do not know", which is never the same as
# "there is nothing there".
vercel_prod_deployments() {
  local json
  json="$(cd "$REPO" && vercel ls --json --environment production --limit 20 \
            2>/dev/null)" || return 0
  [[ -n "$json" ]] || return 0

  # vercel prints a progress line before the JSON ("Retrieving project…"), so
  # the document starts at the first brace rather than at the first byte.
  VERCEL_LS_JSON="$json" python3 <<'PY' 2>/dev/null || true
import json, os, sys

raw = os.environ["VERCEL_LS_JSON"]
start = raw.find("{")
if start < 0:
    sys.exit(0)
try:
    data = json.loads(raw[start:])
except ValueError:
    sys.exit(0)

for item in data.get("deployments") or []:
    if not isinstance(item, dict):
        continue
    # target is checked even though the query asked for production: a filter
    # that silently stops filtering would put a preview URL in front of a
    # rollback, and that is not a mistake to make once.
    if (item.get("target") or "") != "production":
        continue
    url = item.get("url") or ""
    if url and not url.startswith("http"):
        url = "https://" + url
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    print("\t".join([
        url,
        (meta.get("githubCommitSha") or "")[:40],
        (item.get("state") or "").upper(),
        str(item.get("createdAt") or ""),
        str(item.get("ready") or ""),
    ]))
PY
}

# The deployment currently serving production — the first READY one.
#
# READY rather than merely the first: a deployment that errored or is still
# building is on the list and is not what anybody is looking at.
vercel_prod_current() {
  vercel_prod_deployments | awk -F'\t' '$3 == "READY" { print; exit }'
}

# Records, before a prod deploy, the deployment that is about to be displaced.
#
# Before, and that is the whole of it: afterwards the answer has moved, and
# working it out later means picking a row by position — which is how a rollback
# goes to the wrong release. Here the question is unambiguous, because what is
# serving production right now is exactly what we are about to replace.
#
# Silent on failure, like deploy_remember: a deploy that worked must not be
# reported as broken because a note could not be filed. The cost of the note
# being missing is that the rollback refuses rather than guesses.
rollback_remember_previous() {
  local wt="$1" line url sha
  line="$(vercel_prod_current)" || return 0
  [[ -n "$line" ]] || return 0
  url="$(printf '%s' "$line" | cut -f1)"
  sha="$(printf '%s' "$line" | cut -f2)"
  [[ -n "$url" ]] || return 0
  state_set "$wt/.sclaude/local/feature/state.json" rollback.prod.url "$url" 2>/dev/null || true
  [[ -n "$sha" ]] && state_set "$wt/.sclaude/local/feature/state.json" rollback.prod.sha "$sha" \
    2>/dev/null || true
}

# The deployment to roll back to, as "<url>\t<sha>", or nothing.
#
# The record comes first: it was taken at the one moment the answer was certain.
# Falling back to the list is for a rollback of a deploy that predates this
# bookkeeping — then the newest READY production deployment whose commit is not
# the one we shipped is the best available answer, and it is still an answer
# about a commit rather than about a row's position.
rollback_target() {
  # `state` on a line of its own: bash assigns a `local` list left to right and
  # does not see a name from the same command, so `local wt="$1"
  # state="$wt/..."` yields `/.sclaude/local/feature/state.json` — a path that reads as
  # nothing there rather than as an error.
  local wt="$1" url sha ours
  local state="$wt/.sclaude/local/feature/state.json"

  url="$(state_get "$state" rollback.prod.url 2>/dev/null || true)"
  if [[ -n "$url" && "$url" != "null" ]]; then
    sha="$(state_get "$state" rollback.prod.sha 2>/dev/null || true)"
    [[ "$sha" == "null" ]] && sha=""
    printf '%s\t%s\n' "$url" "$sha"
    return 0
  fi

  ours="$(state_get "$state" deploy.prod.sha 2>/dev/null || true)"
  [[ "$ours" == "null" ]] && ours=""
  vercel_prod_deployments | awk -F'\t' -v ours="$ours" '
    $3 != "READY" { next }
    ours != "" && $2 == ours { next }
    { print $1 "\t" $2; exit }
  '
}

# The commits that leave production along with this feature's, as subjects.
#
# Main takes several merges a day here, so a rollback routinely carries other
# people's work back out with ours. That is usually the right trade — production
# is broken now — but it must be said before, not discovered after.
#
# Empty when there is nothing else, or when it cannot be worked out.
rollback_collateral() {
  local target_sha="$1" ours="$2"
  [[ -n "$target_sha" && -n "$ours" ]] || return 0
  git -C "$REPO" rev-parse --quiet --verify "$target_sha^{commit}" >/dev/null 2>&1 || return 0
  git -C "$REPO" rev-parse --quiet --verify "$ours^{commit}" >/dev/null 2>&1 || return 0
  # Everything between the deployment we are going back to and the one we
  # shipped, minus the merge that brought this feature in. --no-merges keeps the
  # list about work rather than about the shape of the history.
  git -C "$REPO" log --no-merges --format='%h %s' "$target_sha..$ours" 2>/dev/null
}

# --- the code half -----------------------------------------------------------

# Puts production back to a deployment that is still on hosting.
#
#   rollback_vercel <wt> <url>   0 = production restored
#
# Not through run_vercel, and that is a decision rather than an oversight: that
# function appends `--json` to every command it is given, and `vercel rollback`
# has no such flag; its parser then looks for a deployment object that a
# rollback does not return. run_vercel exists to hide a deploy's tail of
# suggestions, and a rollback has no tail.
#
# The exit code is not trusted on its own. `--timeout` can expire while the
# rollback is still in flight, and vercel then reports a failure for something
# that is about to succeed — so the answer comes from `rollback status`, which
# is the same question asked of the world rather than of a process.
rollback_vercel() {
  local wt="$1" url="$2" rc waited=0

  echo ""
  echo "${BLUE}\$ vercel rollback $url --yes --timeout 3m${OFF}"
  ( cd "$REPO" && vercel rollback "$url" --yes --timeout 3m 2>&1 ) | sed 's/^/  /'
  rc="${PIPESTATUS[0]}"

  # Whatever the code said, ask hosting. A rollback still in progress is not a
  # failure, and one reported as done is worth confirming before the next step
  # runs a suite against it.
  #
  # And the poll's answer is what decides, which is what the paragraph above
  # always claimed and the code did not do: the loop ran, observed the rollback
  # land, and then threw the observation away so that `$rc` alone spoke. The
  # case that made it wrong is the one `--timeout` exists for — the rollback
  # still landing when the three minutes are up, vercel exiting non-zero, and
  # production restored while the cycle was told it was not. Everything
  # downstream followed: no confirmation run, no incident on the issue, no
  # rewind to the review step, and `deploy_unchanged` left without the mark
  # that stops it skipping the fix.
  local settled=0
  while [[ "$waited" -lt 120 ]]; do
    local status status_rc
    status="$(cd "$REPO" && vercel rollback status 2>&1)"; status_rc=$?
    if printf '%s' "$status" | grep -qi 'in progress\|pending'; then
      # Only where somebody is watching: under a pipe or a redirect to a log —
      # which is how this runs from the bot path — a rewriting line leaves raw
      # escape codes in the file and nothing ever clears them. The same guard
      # regression_run's spinner uses.
      [[ -t 1 ]] && printf '\r\033[2K  waiting for the rollback to finish (%ss)…' "$waited"
      sleep 5
      waited=$((waited + 5))
      continue
    fi
    [[ "$waited" -gt 0 && -t 1 ]] && printf '\r\033[2K'
    # "No deployment rollback in progress" with a zero exit means nothing is in
    # flight — either it landed or it never started, and the two are told apart
    # by whether `vercel rollback` itself succeeded. A non-zero exit here is the
    # status command failing, which says nothing either way.
    [[ "$status_rc" -eq 0 ]] && settled=1
    break
  done

  if [[ "$rc" -eq 0 ]]; then
    return 0
  fi
  # A non-zero rollback with hosting reporting nothing in flight *and* a poll
  # that took time is the timeout case: the command gave up, the rollback
  # finished. Trusting it needs both halves — a rollback that never started
  # also leaves nothing in flight, and it is told apart by having taken no time
  # at all.
  if [[ "$settled" -eq 1 && "$waited" -gt 0 ]]; then
    warn "  vercel rollback timed out, but hosting reports it finished."
    info "  Treating production as rolled back; the confirmation run checks it."
    return 0
  fi
  warn "  vercel rollback failed — production is unchanged."
  return 1
}

# --- the database half -------------------------------------------------------

# The migrations this branch put into production, newest first.
#
# Read from the record rather than from git, and that is the whole of it. The
# obvious range, `origin/main...HEAD -- supabase/migrations`, is what
# branch_has_migrations asks — and by the time a production rollback runs, the
# branch is merged, so origin/main contains those migrations and the range is
# empty. The DB half would then report "nothing to reverse" about a feature that
# added four tables, confidently and every single time.
#
# So the list is written down before the promote, while the range still answers,
# and this reads it back. The git fallback is for a rollback that happens before
# the merge, where the range is still the truth.
rollback_migrations_list() {
  local wt="$1" recorded
  recorded="$(state_get "$wt/.sclaude/local/feature/state.json" deploy.prod.migrations 2>/dev/null || true)"
  if [[ -n "$recorded" && "$recorded" != "null" ]]; then
    printf '%s\n' $recorded | sort -r
    return 0
  fi
  # --diff-filter=A: a migration this branch *modified* is not one to reverse,
  # and the down block of somebody else's migration is not ours to run.
  local dir; dir="$(project_migrations_dir "$wt" || true)"
  [[ -n "$dir" ]] || return 0
  git -C "$wt" diff --name-only --diff-filter=A origin/main...HEAD \
    -- "$dir" 2>/dev/null | sort -r
}

# Records that list, at the one moment it can still be computed. Called from
# remind_prod's migrations arm, before the promote runs.
rollback_remember_migrations() {
  local wt="$1" files dir
  dir="$(project_migrations_dir "$wt" || true)"
  [[ -n "$dir" ]] || return 0
  files="$(git -C "$wt" diff --name-only --diff-filter=A origin/main...HEAD \
             -- "$dir" 2>/dev/null | tr '\n' ' ')"
  files="${files% }"
  [[ -n "$files" ]] || return 0
  state_set "$wt/.sclaude/local/feature/state.json" deploy.prod.migrations "$files" 2>/dev/null || true
}

# What the branch's migrations say about going back, as a table plus a verdict.
#
# Prints the table on stdout and answers by exit code:
#   0  every block is runnable and none removes rows
#   1  at least one removes rows — runnable, but it costs data
#   2  at least one cannot be run: prose, or no block at all
#
# The table names every migration, including the ones with nothing written down.
# That is the point: a migration silently skipped is how a schema ends up in a
# state nobody can describe, and "no down block" is the loudest row here rather
# than an absent one.
rollback_migrations_report() {
  local wt="$1" file worst=0 any=0
  local -a paths=()

  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    paths+=("$wt/$file")
  done < <(rollback_migrations_list "$wt")

  [[ "${#paths[@]}" -gt 0 ]] || return 0

  echo ""
  echo "${BOLD}The migrations this branch put into production:${OFF}"
  echo ""

  local json
  json="$(python3 "$LIB/down_blocks.py" --classify "${paths[@]}" 2>/dev/null)" || json=""
  [[ -n "$json" ]] || { warn "  could not read the migrations — the schema stays as it is."; return 2; }

  local line verdict name reason
  while IFS=$'\t' read -r name verdict reason; do
    [[ -n "$name" ]] || continue
    any=1
    case "$verdict" in
      runnable)
        printf '  %s%-46s%s %s\n' "$GREEN" "$name" "$OFF" "reversible — $reason" ;;
      destructive)
        printf '  %s%-46s%s %s\n' "$YELLOW" "$name" "$OFF" "reversible, but $reason"
        [[ "$worst" -lt 1 ]] && worst=1 ;;
      prose)
        printf '  %s%-46s%s %s\n' "$RED" "$name" "$OFF" "cannot be run — $reason"
        worst=2 ;;
      absent)
        printf '  %s%-46s%s %s\n' "$RED" "$name" "$OFF" "no down block — $reason"
        worst=2 ;;
    esac
  done < <(printf '%s\n' "$json" | python3 -c '
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        record = json.loads(line)
    except ValueError:
        continue
    # The reason is flattened before it is joined with tabs. It cannot hold a
    # newline today, because split() joins the lines of one statement with
    # spaces — but the shell reads these rows with a tab-separated read, and a
    # single embedded newline would be read as a second row whose first field
    # is the tail of a sentence. It would match no arm of the case and drop
    # that migration from the table which exists precisely so that nothing is
    # dropped in silence. A cheap guard against an expensive failure.
    #
    # (No apostrophes in this block: it is a single-quoted python argument, and
    # one would close the literal. CLAUDE.md records the trap.)
    reason = " ".join((record.get("reason") or "").split())
    print("\t".join([record["file"], record["verdict"], reason]))
')

  [[ "$any" -eq 1 ]] || return 0
  return "$worst"
}

# The SQL that would reverse the branch's migrations, newest first, as a file.
#
# Written to a file rather than inlined for two reasons: the human reads it
# before answering, and the command they are shown stays one readable line
# rather than a wall of statements. It lives under .sclaude/local/feature/, so it dies with
# the worktree like everything else the orchestrator writes.
#
# Each migration's row in the tool's history table goes with its statements. A
# migration tool records what it has applied — Supabase in
# `supabase_migrations.schema_migrations`, others elsewhere — and a down block
# run by hand leaves the row behind, after which the project's own migration
# check reports a divergence and the next promote refuses. A rollback that
# blocks every future promote has not finished the job.
#
# Which table that is belongs to the project, under `database.historyTable`. A
# project that names none gets the statements alone, and the rollback says so:
# guessing a table name and deleting from it is worse than leaving a row.
rollback_migrations_sql() {
  # `out` on its own line, for the reason rollback_target records.
  local wt="$1" file
  local out="$wt/.sclaude/local/feature/rollback/down.sql"
  local -a paths=()

  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    paths+=("$wt/$file")
  done < <(rollback_migrations_list "$wt")
  [[ "${#paths[@]}" -gt 0 ]] || return 1

  mkdir -p "$(dirname "$out")" 2>/dev/null || return 1

  # The classification goes in through the environment and the script through a
  # heredoc, which is this library's shape wherever both are needed (see
  # merge_readiness in deploy.sh). `python3 - <<PY` reads the *script* from
  # stdin, so a pipeline into it never reaches the code — and an apostrophe in
  # a `python3 -c '...'` argument would close the literal, which CLAUDE.md
  # records as its own trap. This form has neither problem.
  local classified
  classified="$(python3 "$LIB/down_blocks.py" --classify "${paths[@]}" 2>/dev/null)" \
    || return 1
  [[ -n "$classified" ]] || return 1

  ROLLBACK_CLASSIFIED="$classified" \
  ROLLBACK_HISTORY_TABLE="$(project_get database.historyTable "$wt" || true)" \
    python3 > "$out" <<'PY' || return 1
import json, os, sys

# Only the blocks that can actually be run. A prose or absent one has already
# been named in the report; writing a commented placeholder for it here would
# put a file in front of the human that looks complete and is not.
out = []
for line in os.environ["ROLLBACK_CLASSIFIED"].splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        record = json.loads(line)
    except ValueError:
        continue
    if record["verdict"] not in ("runnable", "destructive"):
        continue
    out.append("-- %s (%s)" % (record["file"], record["verdict"]))
    out.extend(record["sql"])
    history = os.environ.get("ROLLBACK_HISTORY_TABLE") or ""
    if record["version"] and history:
        # The migration tool records what it has applied in this table, and a
        # down block run by hand leaves the row behind — after which the
        # project's migration check reports a divergence and the next promote
        # refuses. The version is a filename's numeric prefix, but it is escaped
        # rather than concatenated: a value reaching SQL unescaped is not a
        # thing to leave to a naming convention.
        version = record["version"].replace("'", "''")
        out.append(
            "delete from " + history + " "
            "where version = '" + version + "';")
    out.append("")

sys.stdout.write("\n".join(out))
PY

  [[ -s "$out" ]] || { rm -f "$out"; return 1; }
  echo "$out"
}

# Runs the assembled down blocks against production, if the human agrees.
#
#   rollback_migrations <wt> <slug>
#
# Writes rollback.db.status and says what it did. Never runs anything on its
# own: the code half is automatic because a broken production is not a decision,
# and this half is not, because deleting rows is.
#
# The default is N here, against the code half's yes. The two directions are not
# alike — a code rollback is undone by deploying again, and a `delete from` is
# undone by nothing.
rollback_migrations() {
  local wt="$1" slug="$2" answer sql rc
  local state="$wt/.sclaude/local/feature/state.json"

  rollback_migrations_report "$wt"
  rc=$?

  # No migrations at all: the commonest case, and it deserves no paragraph.
  if [[ "$rc" -eq 0 ]] && ! rollback_migrations_list "$wt" | grep -q .; then
    state_set "$state" rollback.db.status none 2>/dev/null || true
    return 0
  fi

  if [[ "$rc" -eq 2 ]]; then
    echo ""
    warn "  The schema cannot be put back, so it is left alone."
    info "  Production now runs the previous code against the new schema."
    info "  Whether that is fine or fatal depends on the migrations above: one"
    info "  that only added a column the old code ignores is harmless, one that"
    info "  took something away is not."
    info "  Nothing partial is offered — a schema reverted halfway is one nobody"
    info "  can describe."
    state_set "$state" rollback.db.status ahead 2>/dev/null || true
    return 0
  fi

  sql="$(rollback_migrations_sql "$wt")" || {
    state_set "$state" rollback.db.status ahead 2>/dev/null || true
    return 0
  }

  echo ""
  echo "${BOLD}This would run against production:${OFF}"
  echo ""
  sed 's/^/  /' "$sql"
  echo ""
  [[ "$rc" -eq 1 ]] && warn "  It deletes rows. They do not come back."

  ask "${BOLD}Run it against production? [y/n] ${OFF}" answer yn
  if ! is_yes "$answer"; then
    info "  Left alone — the schema stays ahead of the code."
    state_set "$state" rollback.db.status declined 2>/dev/null || true
    return 0
  fi

  rollback_apply_sql "$wt" "$sql"
}

# The part that actually touches production, kept separate so the environment is
# put back whatever happens inside it.
#
# The main tree is switched to production (environment_switch): the
# credential is read from production's .env file either way, and the switch is
# there so the schema snapshot afterwards is taken from production. A tree
# left pointing at production is a machine whose next `npm run dev` talks to
# it, so the switch back — to wherever the tree was — is not on the success
# path but after it, unconditionally.
rollback_apply_sql() {
  local wt="$1" sql="$2" url rc
  local state="$wt/.sclaude/local/feature/state.json"

  # A failure here still falls through to the switch back at the end rather
  # than returning: `switched` carries the outcome instead of an early return.
  # The credential is never printed: psql takes it as an argument, and the
  # argument is not echoed.
  local switched=1 prod snapshot schema_dump
  prod="$(environment_production "$REPO")"
  schema_dump="$(project_get database.schemaDump "$wt" || true)"

  if [[ -z "$prod" ]]; then
    warn "  The project does not say which environment is production."
    info "  .sclaude/config.json marks it \"protected\" under environments."
    state_set "$state" rollback.db.status ahead 2>/dev/null || true
    return 0
  fi

  # Kept exactly, rather than by name: a .env.local that is no declared
  # environment has no name to switch back to.
  snapshot="$(environment_snapshot "$REPO")" || {
    warn "  could not keep the main tree's environment to put it back — nothing was run."
    state_set "$state" rollback.db.status ahead 2>/dev/null || true
    return 0
  }
  if ! environment_switch "$REPO" "$prod"; then
    switched=0
    warn "  could not switch to the production environment — nothing was run."
    state_set "$state" rollback.db.status ahead 2>/dev/null || true
    url=""
  else
    url="$(environment_value "$REPO" "$prod" "$(environment_key "$REPO" database)" || true)"
  fi

  if [[ "$switched" -eq 0 ]]; then
    : # already reported; fall through to the switch back
  elif [[ -z "$url" ]]; then
    warn "  no database URL for \"$prod\" — nothing was run."
    state_set "$state" rollback.db.status ahead 2>/dev/null || true
  else
    echo "${BLUE}\$ psql -v ON_ERROR_STOP=1 -f ${sql#$wt/}${OFF}"
    # ON_ERROR_STOP because psql carries on by default, and a down block applied
    # halfway is worse than one not applied at all.
    # `$rc` alone, and PIPESTATUS deliberately not consulted. Reading it here
    # was wrong in the one direction that matters: `rc=1` is itself a command,
    # so it resets PIPESTATUS to (0), and `${PIPESTATUS[0]:-$rc}` then found a
    # set, non-empty `0` and never fell back. A psql that stopped on an error
    # halfway through a down block was reported as "the schema is back",
    # recorded as `reverted` in the incident comment and in the metrics, and
    # followed by a schema dump taken from a half-reverted database. The
    # `partial` branch below could not be reached at all.
    #
    # `if cmd | sed` is correct under this script's `set -o pipefail`: the
    # pipeline's status is psql's whenever psql fails.
    if psql "$url" -v ON_ERROR_STOP=1 -q -f "$sql" 2>&1 | sed 's/^/  /'; then
      rc=0
    else
      rc=1
    fi
    if [[ "$rc" -eq 0 ]]; then
      echo "${GREEN}  ✓ the schema is back.${OFF}"
      state_set "$state" rollback.db.status reverted 2>/dev/null || true
      # The snapshot has to follow, or supabase/schema.sql describes a schema
      # production no longer has and the next local regression fails for a
      # reason that has nothing to do with the branch. Left uncommitted, as
      # a promote leaves it: naming what was reverted is a sentence for a human
      # to write.
      if [[ -n "$schema_dump" ]]; then
        ( cd "$REPO" && eval "$schema_dump" ) >/dev/null 2>&1 \
          && info "  the schema snapshot was regenerated — it is uncommitted." \
          || warn "  could not regenerate the schema snapshot."
      fi
    else
      warn "  psql stopped on an error — the schema is partly reverted."
      warn "  Read the output above: what ran, ran. Nothing here will guess."
      state_set "$state" rollback.db.status partial 2>/dev/null || true
    fi
  fi

  # Back to where the tree was, always — including after every early return
  # above, which is why they set the status and fall through to here.
  environment_restore "$REPO" "$snapshot" \
    || warn "  could not put the main tree's environment back — check: readlink $REPO/.env.local"
  return 0
}

# --- the whole rollback ------------------------------------------------------

# Puts production back: the code, then as much of the schema as can honestly go.
#
#   rollback_prod <wt> <slug> [--auto]
#
# 0 = production was restored, non-zero = it was not, and nothing downstream
# should behave as though it were.
#
# --auto skips the "roll back?" question. A red production regression is not a
# decision anybody needs to confirm — production is broken, and the release
# before it is the one known-good thing within reach. From the terminal the
# human is present, so they are asked, with the default yes.
#
# The one place --auto still stops to ask: a migration that took something away
# whose down block cannot be run. Then the previous build would meet a schema it
# was never written for, and rolling the code back can be the worse of the two
# failures. That case is rare and specific, and it is the only exception.
rollback_prod() {
  local wt="$1" slug="$2" auto="${3:-}"
  local state="$wt/.sclaude/local/feature/state.json"
  # `commit` rather than reusing `line` for the collateral loop below: `line`
  # holds the target, and a loop that overwrites the value it was chosen from is
  # a trap for the next edit even where it happens to be harmless today.
  local line url sha ours answer collateral commit

  # The log that caused this, before anything overwrites it.
  #
  # regression_run opens with `: > "$log"`, and the confirmation run that
  # follows a rollback is a regression_run. Without a copy taken here, the
  # fixing session would be handed a log describing the *previous release
  # passing* — the exact opposite of the evidence it needs, and a plausible
  # enough document that nobody would question it.
  rollback_keep_log "$wt" prod

  line="$(rollback_target "$wt")" || line=""
  url="$(printf '%s' "$line" | cut -f1)"
  sha="$(printf '%s' "$line" | cut -f2)"

  if [[ -z "$url" ]]; then
    echo ""
    warn "Cannot tell which deployment to roll back to."
    info "  Nothing was recorded for this feature, and the production list"
    info "  named nothing usable. Rolling back by hand:"
    info "    vercel ls --environment production"
    info "    vercel rollback <url>"
    state_set "$state" rollback.prod.code refused 2>/dev/null || true
    return 1
  fi

  ours="$(state_get "$state" deploy.prod.sha 2>/dev/null || true)"
  [[ "$ours" == "null" ]] && ours=""

  echo ""
  echo "${BOLD}Rolling production back.${OFF}"
  info "  to:   $url${sha:+  ($(printf '%s' "$sha" | cut -c1-8))}"
  [[ -n "$ours" ]] && info "  from: $(printf '%s' "$ours" | cut -c1-8) — this feature"

  # What else leaves production with us. Said before, never discovered after.
  collateral="$(rollback_collateral "$sha" "$ours")"
  if [[ -n "$collateral" ]]; then
    echo ""
    warn "  This also takes out work that is not this feature's:"
    while IFS= read -r commit; do
      [[ -n "$commit" ]] && info "    $commit"
    done <<< "$collateral"
  fi

  # The narrow exception to --auto: the old build against a schema it does not
  # know. rollback_migrations_report has the classification; here we only need
  # to know whether any migration took something away and cannot be undone.
  if rollback_forward_hazard "$wt"; then
    echo ""
    warn "  This feature's migrations took something away, and their down blocks"
    warn "  cannot be run. The previous build would meet a schema it was never"
    warn "  written for, which can break it in ways a red regression does not."
    ask "${BOLD}  Roll the code back anyway? [y/n] ${OFF}" answer yn
    if ! is_yes "$answer"; then
      info "  Left as it is. Production runs this feature, and its regression is red."
      info "  Rolling forward instead — fixing and shipping again — may be the way."
      state_set "$state" rollback.prod.code refused 2>/dev/null || true
      return 1
    fi
  elif [[ "$auto" != "--auto" ]]; then
    echo ""
    ask "${BOLD}Roll production back? [y/n] ${OFF}" answer yn
    if ! is_yes "$answer"; then
      info "  Cancelled — production is unchanged."
      return 1
    fi
  fi

  if ! rollback_vercel "$wt" "$url"; then
    state_set "$state" rollback.prod.code failed 2>/dev/null || true
    return 1
  fi

  state_set "$state" rollback.prod.code done 2>/dev/null || true
  state_set "$state" rollback.prod.at "$(date -Iseconds)" 2>/dev/null || true
  [[ -n "$sha" ]] && state_set "$state" rollback.prod.to_sha "$sha" 2>/dev/null || true
  echo "${GREEN}✓ Production is back at ${sha:0:8}${sha:+ — }$url${OFF}"

  rollback_migrations "$wt" "$slug"
  return 0
}

# True when a migration of this branch took something away and its down block
# cannot be run — the one case where rolling the code back may be worse than
# leaving it.
#
# False on everything unknown: no migrations, no classifier, nothing readable.
# The question is "do we know this is hazardous", and not knowing is not a yes.
rollback_forward_hazard() {
  local wt="$1" file
  local -a paths=()
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    paths+=("$wt/$file")
  done < <(rollback_migrations_list "$wt")
  [[ "${#paths[@]}" -gt 0 ]] || return 1

  python3 "$LIB/down_blocks.py" --classify "${paths[@]}" 2>/dev/null \
    | python3 -c '
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        record = json.loads(line)
    except ValueError:
        continue
    if record["forward_destructive"] and record["verdict"] in ("prose", "absent"):
        sys.exit(0)
sys.exit(1)
'
}

# --- after the rollback ------------------------------------------------------

# Runs the suite against production once more, to answer one question: is the
# release we went back to serving properly?
#
# Its own stage, not a second `prod` run, and that separation is structural
# rather than a convention to remember. `regression.prod.status` goes on
# describing the feature, so nothing downstream can read this green as the
# feature's: not regression_gate's short-circuit, not regression_clear_mark, not
# the labels, not the epilogue's prose.
#
# Never through regression_gate. A red confirmation must not open a fixing
# session — what failed is the release before this feature, and no session
# working on this branch can mend it. What it earns is a person, now.
rollback_confirm() {
  local wt="$1" slug="$2"

  echo ""
  info "Checking that the release we went back to is serving properly."
  info "  This is about the rollback, not about the feature: a green run here"
  info "  says production works again, and says nothing about the fix."

  regression_run "$wt" "$slug" rollback
  local rc=$?

  if [[ "$rc" -eq 0 ]]; then
    echo "${GREEN}✓ Production is green again on the previous release.${OFF}"
    return 0
  fi

  # 2 is "could not run", and it must not be reported as red. The stage answers
  # it for three reasons that are all facts about the setup rather than about
  # production: the project declares no regression for this stage, there is no
  # address to aim at, or the environment is broken. Every other caller in the
  # cycle tells 1 from 2; this one did not, so `sclaude rollback` on a project
  # with no declared prod suite woke somebody with "production is STILL red"
  # about a suite that never ran.
  if [[ "$rc" -eq 2 ]]; then
    echo ""
    info "  The confirmation run could not be made — see above."
    info "  Production was rolled back; whether the previous release serves"
    info "  properly is unverified rather than known to be broken."
    return 0
  fi

  echo ""
  warn "The rollback did not mend production: the suite is red against it too."
  info "  Something outside this feature is wrong — the release before it was"
  info "  green when it shipped. Look now rather than carrying on."
  "$INSTRUMENTS/bin/sclaude-notify" "$slug: rolled production back and it is STILL red.
The previous release does not fix it — something else is wrong.
Log: .sclaude/local/feature/regression.log" 2>/dev/null || true
  return 1
}

# Keeps the failing run's log, which the next regression_run would truncate.
#
# `.sclaude/local/feature/regression.log` is rewritten at the head of every run (`: > "$log"`
# in regression_run), and a rollback is followed immediately by the confirmation
# run. So the evidence that caused the rollback survives only if it is copied
# first. The path goes into the state, and regression_fix reads it from there.
#
# Silent on failure: a log that could not be copied costs the fixing session its
# starting point, never the rollback.
rollback_keep_log() {
  local wt="$1" stage="$2" src dest
  src="$wt/.sclaude/local/feature/regression.log"
  [[ -s "$src" ]] || return 0
  dest="$wt/.sclaude/local/feature/rollback/regression-$stage-$(date +%Y%m%d-%H%M%S).log"
  mkdir -p "$(dirname "$dest")" 2>/dev/null || return 0
  cp "$src" "$dest" 2>/dev/null || return 0
  state_set "$wt/.sclaude/local/feature/state.json" rollback.prod.log "$dest" 2>/dev/null || true
}

# The marker on an incident comment. Unlike the request, criteria and status
# markers in issue_comments.py, this one marks nothing rewritable: it is here so
# a reader — and a later session — can find these comments among the thread, not
# so anything can edit them.
ROLLBACK_MARKER="<!-- sclaude:rollback -->"

# Writes the incident onto the feature's issue, as a new comment.
#
# A comment rather than a new Bug issue, and the reason is in the code rather
# than in taste. `state.json` holds one `issue`, read in nine places; the labels
# and the status section go on the whole chain of parents that number walks. A
# second issue would have no parents, so the epic above this feature would never
# learn that production broke — and the fix, which is meaningless without this
# feature's code, would be split across two `Closes #N` targets. regression_rewind
# already puts the cycle back into the review step in this same worktree, and
# its own comment calls that shape "one business task, two pull requests, which
# is the only shape that ships".
#
# A new comment rather than an edit of the last one, unlike issue_sync's rolling
# summary. A rollback is an event with a time: a feature rolled back twice has
# two of them, and overwriting the first would erase the history of the first
# failure. issue_sync's summary goes on being rewritten beside these.
#
# Quiet on everything unknown — no issue, no gh, no network. A rollback must not
# be reported as failed because a comment could not be posted.
rollback_incident() {
  local wt="$1" slug="$2" issue="${3:-}"
  local state="$wt/.sclaude/local/feature/state.json"
  local repo failed log target to_sha db_status confirm body

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  failed="$(state_get "$state" regression.prod.failed_at 2>/dev/null || true)"
  [[ -z "$failed" || "$failed" == "null" ]] && failed="a part"
  target="$(state_get "$state" rollback.prod.url 2>/dev/null || true)"
  [[ "$target" == "null" ]] && target=""
  to_sha="$(state_get "$state" rollback.prod.to_sha 2>/dev/null || true)"
  [[ "$to_sha" == "null" ]] && to_sha=""
  db_status="$(state_get "$state" rollback.db.status 2>/dev/null || true)"
  [[ "$db_status" == "null" ]] && db_status=""
  confirm="$(regression_status "$wt" rollback 2>/dev/null || true)"
  log="$(state_get "$state" rollback.prod.log 2>/dev/null || true)"
  [[ "$log" == "null" ]] && log=""

  body="$(
    printf '%s\n' "$ROLLBACK_MARKER"
    printf '## Production rolled back — %s\n\n' "$(date '+%Y-%m-%d %H:%M')"
    printf 'The production regression failed on `%s` after this feature shipped, so ' "$failed"
    printf 'production was restored to the release before it. Nothing was fixed first: a '
    printf 'fixing session against a live broken production is minutes with nobody served.\n\n'

    printf '**Code** — rolled back.\n'
    [[ -n "$target" ]] && printf -- '- now serving: %s%s\n' "$target" \
      "${to_sha:+ (\`${to_sha:0:8}\`)}"
    # `failed` is read together with what failed. regression_environment_broken
    # writes the same word for a suite that could not run at all — no browser,
    # no address, a missing dependency — and a comment on the issue claiming
    # "the previous release does not fix this" about a run that never happened
    # sends somebody after the wrong thing.
    case "$confirm" in
      passed)
        printf -- '- the suite against production is green again\n' ;;
      failed)
        if [[ -s "$wt/.sclaude/local/feature/regression.blocked" ]]; then
          printf -- '- the confirmation run could not be made (see `.sclaude/local/feature/regression.blocked`) — whether the previous release serves properly is unverified\n'
        else
          printf -- '- **the suite is still red against it** — the previous release does not fix this, so something outside the feature is wrong\n'
        fi ;;
      *)
        printf -- '- the confirmation run did not complete\n' ;;
    esac
    printf '\n'

    printf '**Schema** — '
    case "$db_status" in
      reverted) printf 'rolled back with it.\n\n' ;;
      declined) printf 'left ahead of the code, by choice: the down blocks were not run.\n\n' ;;
      partial)  printf '**partly reverted** — psql stopped on an error partway. Read the run above before anything else.\n\n' ;;
      none)     printf 'untouched: this branch added no migrations.\n\n' ;;
      *)        printf 'NOT rolled back. Production runs the previous code against the new schema.\n\n' ;;
    esac

    rollback_incident_migrations "$wt"

    printf '**What failed:** `%s`' "$failed"
    [[ -n "$log" ]] && printf ' — the run'"'"'s log is kept at `%s` in the worktree' "${log#$wt/}"
    printf '.\n\n'

    printf 'main still holds the commit that broke this, so the next production deploy '
    printf 'ships it again unless the fix lands first.\n\n'

    printf 'The fix carries on in this same issue: the cycle has returned to the review '
    printf 'step in the feature'"'"'s worktree, and goes the whole way round again — local '
    printf 'suite, merge, preview and its suite, then production. The merged pull request '
    printf 'cannot be reopened, so the fix arrives as a second one carrying `Closes #%s`.\n' "$issue"
  )"

  gh issue comment "$issue" --repo "$repo" --body-file - <<< "$body" >/dev/null 2>&1 \
    || warn "  could not write the incident onto issue #$issue"
}

# The migrations table for the incident comment, or nothing.
rollback_incident_migrations() {
  local wt="$1" file
  local -a paths=()
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    paths+=("$wt/$file")
  done < <(rollback_migrations_list "$wt")
  [[ "${#paths[@]}" -gt 0 ]] || return 0

  local classified
  classified="$(python3 "$LIB/down_blocks.py" --classify "${paths[@]}" 2>/dev/null)" || return 0
  [[ -n "$classified" ]] || return 0

  printf '| migration | down block | what happened |\n|---|---|---|\n'
  ROLLBACK_CLASSIFIED="$classified" \
  ROLLBACK_DB_STATUS="$(state_get "$wt/.sclaude/local/feature/state.json" rollback.db.status 2>/dev/null || true)" \
    python3 <<'PY' 2>/dev/null || true
import json, os

status = os.environ.get("ROLLBACK_DB_STATUS") or ""
ran = status == "reverted"

WHAT = {
    "runnable": "reversed" if ran else "not run",
    "destructive": "reversed" if ran else "not run",
    "prose": "**cannot be run**",
    "absent": "**nothing was written down**",
}
BLOCK = {
    "runnable": "executable",
    "destructive": "destructive",
    "prose": "prose",
    "absent": "none",
}

for line in os.environ["ROLLBACK_CLASSIFIED"].splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        record = json.loads(line)
    except ValueError:
        continue
    verdict = record["verdict"]
    print("| `%s` | %s | %s |" % (record["file"], BLOCK.get(verdict, verdict),
                                  WHAT.get(verdict, "")))
PY
  printf '\n'
}
