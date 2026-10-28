#!/usr/bin/env bash
#
# A feature's own local Supabase.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Two features working against one local database see each other's schema — a
# migration written in one lands under the other — and a `db reset` in one wipes
# the other's data. So a feature whose environment is the project's local stack
# gets a stack of its own: its own containers, its own volumes, its own block of
# ports. The rewriting of the config and the environment file it leaves behind
# are in feature_db.py; this file decides when, and runs the CLI.
#
# What a project declares, in .sclaude/config.json:
#
#   "database": { "local": {
#       "environment": "localdb",           the environment that means "local"
#       "exclude": ["studio", …],           containers a feature does not need
#       "setup": "npm run seed",            run once, on a new stack
#       "env": { "NEXT_PUBLIC_SUPABASE_URL": "API_URL", … },
#       "cli": "npx --yes supabase"         optional; this is the default
#   } }
#
# `env` maps the project's variable names to the keys `supabase status -o env`
# prints. The result is .sclaude/local/feature/db.env, and every process sclaude starts in the
# feature — the dev server, the regression, the claude session — sources it.
# A project's own dotenv loading must let an already-set variable win, or the
# file's values would be overwritten by .env.local's shared ones.
#
# No declaration, no stack: the feature keeps whatever .env.local points at, as
# before.

# The blocks of ports stacks are given, ten each. Well clear of the main stack's
# 54320-54329 and of the dev servers' 3100-3199.
DB_BLOCK_FIRST=55000
DB_BLOCK_LAST=55990

db_cli() {
  local cli; cli="$(project_get database.local.cli "$1" 2>/dev/null || true)"
  echo "${cli:-npx --yes supabase}"
}

# The environment a tree is on: the one whose file its .env.local points at
# (environment.sh). Empty when the product names no environments.
db_env_name() {
  environment_current "$1"
}

# Should this tree have a stack of its own right now?
#
# Not the main repository: its stack is the one everybody already has, on the
# ports in its own config. Not under a pinned DEV_PORT — that is the integration
# bench, which must not start containers. And only while the tree's environment
# is the local one: a feature on the shared cloud project has nothing local to
# isolate.
db_wanted() {
  local wt="$1" want
  [[ "$wt" != "${REPO:-}" ]] || return 1
  [[ -z "${DEV_PORT_PINNED:-}" ]] || return 1
  [[ -f "$wt/supabase/config.toml" ]] || return 1
  want="$(project_get database.local.environment "$wt" 2>/dev/null || true)"
  [[ -n "$want" ]] || return 1
  [[ "$(db_env_name "$wt")" == "$want" ]]
}

# This tree's block of ports: recorded once in its state as db.base, under the
# same lock the dev ports are claimed with. A block is free when no other
# registered tree has recorded it and nothing listens on any port in it.
db_base() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" base listening
  base="$(state_get "$state" db.base 2>/dev/null)"
  [[ "$base" =~ ^[0-9]+$ ]] && { echo "$base"; return 0; }
  mkdir -p "$DEV_REGISTRY" || return 1
  (
    flock -w 10 9 || exit 1
    listening="$(ss -ltnH 2>/dev/null | awk '{print $4}' | sed 's/.*://' | tr '\n' ' ')"
    python3 - "$wt" "$state" "$DEV_REGISTRY" "$DB_BLOCK_FIRST" "$DB_BLOCK_LAST" \
      "$listening" <<'PY'
import json, os, sys

wt, state, registry, first, last, listening = sys.argv[1:7]
first, last = int(first), int(last)
listening = {int(p) for p in listening.split() if p.isdigit()}
real = os.path.realpath(wt)

taken = set()
for name in os.listdir(registry):
    tree = os.path.realpath(os.path.join(registry, name))
    if tree == real or not os.path.islink(os.path.join(registry, name)):
        continue
    try:
        with open(os.path.join(tree, ".sclaude/local/feature", "state.json")) as fh:
            base = (json.load(fh).get("db") or {}).get("base")
    except (OSError, ValueError, AttributeError):
        continue
    if isinstance(base, int):
        taken.add(base)

for base in range(first, last + 1, 10):
    if base in taken or any(p in listening for p in range(base, base + 10)):
        continue
    with open(state) as fh:
        data = json.load(fh)
    data.setdefault("db", {})["base"] = base
    with open(state, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(base)
    sys.exit(0)
sys.stderr.write("no free block of ports in %d-%d\n" % (first, last))
sys.exit(1)
PY
  ) 9>"$DEV_REGISTRY/.lock"
}

# The stack's project_id: the project's own, suffixed with the feature's label,
# so `docker ps` says whose containers they are.
#
# Kept to what the Supabase CLI keeps before naming anything: characters
# outside [a-zA-Z0-9_.-] become "_", and the whole is cut to 40 characters.
# The containers carry the CLI's form, so a longer id names a container that
# does not exist — a long feature label made the copy of the main database
# fail with "No such container". A longer id is cut short of 40 and ends in a
# hash of the whole, or two labels alike in their first 40 characters would
# share one stack.
#
# Recorded in the state as db.project_id the first time, and read from there
# afterwards. A stack started before the hash, under the CLI's plain cut, is
# found by its container and keeps that name: a new one would leave it, with
# its data, behind.
db_project_id() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" own label id cut
  id="$(state_get "$state" db.project_id 2>/dev/null)"
  [[ -n "$id" ]] && { echo "$id"; return 0; }
  own="$(sed -n 's/^project_id *= *"\([^"]*\)".*/\1/p' "$wt/supabase/config.toml" | head -1)"
  label="$(state_get "$state" dev.label 2>/dev/null)"
  [[ -n "$label" ]] || label="$(basename "$wt")"
  id="$(sed -E 's/[^a-zA-Z0-9_.-]+/_/g' <<<"${own:-project}-$label")"
  if (( ${#id} > 40 )); then
    cut="${id:0:40}"
    if docker inspect "$(db_container "$cut")" >/dev/null 2>&1; then
      id="$cut"
    else
      id="${id:0:31}-$(printf '%s' "$id" | sha1sum | cut -c1-8)"
    fi
  fi
  [[ -f "$state" ]] && state_set "$state" db.project_id "$id"
  echo "$id"
}

# .sclaude/local/feature/supabase/supabase: the rewritten config, and a symlink for
# everything else in the tree's supabase/. Rebuilt on every start, so a change
# to the config inside the feature reaches its stack. The CLI's own .temp and
# .branches are the stack's, not the tree's, and are left alone.
db_workdir() {
  local wt="$1" base="$2" dir="$1/.sclaude/local/feature/supabase/supabase" entry name
  mkdir -p "$dir" || return 1
  python3 "$LIB/feature_db.py" config "$wt/supabase/config.toml" "$dir/config.toml" \
    "$(db_project_id "$wt")" "$base" || return 1
  shopt -s nullglob dotglob
  for entry in "$wt"/supabase/*; do
    name="$(basename "$entry")"
    case "$name" in config.toml|.temp|.branches) continue ;; esac
    [[ -L "$dir/$name" || ! -e "$dir/$name" ]] || continue
    ln -sfn "$entry" "$dir/$name"
  done
  shopt -u nullglob dotglob
}

# Whether the Docker daemon answers; what it said on stderr goes to stdout.
# Bounded: a half-started Docker Desktop accepts the connection and never
# replies, and an unbounded `docker info` would hang the step with it
# (bin/wsl-update guards the same probe). A `docker` that is a shell function —
# the tests' stand-in — is called as it is: timeout runs programs only.
docker_info() {
  if [[ "$(type -t docker)" == "function" ]]; then
    docker info 2>&1 >/dev/null
  else
    timeout 20 docker info 2>&1 >/dev/null
  fi
}

docker_up() {
  docker_info >/dev/null
}

# Where Docker Desktop's launcher is, reached from WSL, or nothing.
#
# SCLAUDE_DOCKER_DESKTOP first. Then this Windows user's own install and the
# machine-wide one, both asked of Windows rather than assumed under /mnt/c: the
# automount root is configurable, and on a shared machine the first install a
# glob over every user finds may be somebody else's.
docker_desktop_exe() {
  local local_app="" candidate
  if command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    local_app="$(cd /mnt/c 2>/dev/null || cd /; timeout 10 cmd.exe /c 'echo %LOCALAPPDATA%' 2>/dev/null | tr -d '\r')"
    [[ "$local_app" == *%* ]] && local_app=""
  fi
  for candidate in "${SCLAUDE_DOCKER_DESKTOP:-}" \
      "${local_app:+$(wslpath -u "$local_app" 2>/dev/null)/Programs/DockerDesktop/Docker Desktop.exe}" \
      "$(wslpath -u 'C:\Program Files\Docker\Docker\Docker Desktop.exe' 2>/dev/null)"; do
    [[ -n "$candidate" && -f "$candidate" ]] && { echo "$candidate"; return 0; }
  done
  return 1
}

# Brings Docker up when it is down and a stack needs it. Returns 1 when it
# cannot, and the caller falls back as it always did.
#
# On 2026-10-10 a feature's local regression failed on a database check with Docker
# stopped: no stack answered, the fixing session found that, wrote
# regression.blocked and stopped. sclaude had already said "Docker is not
# running" at the start of the step, and starting it was one command. So
# sclaude starts it itself rather than only saying so.
#
# Two ways in, the first that applies: Docker Desktop on Windows, reached from
# WSL (docker_desktop_exe), or a docker.service under systemd, started only
# where sudo needs no password: a password prompt in the middle of a step would
# hang it with nobody told.
#
# Only a daemon that is not there is started. A socket this user may not open,
# or a CLI that is missing, is not something starting Docker mends, and it is
# not tried.
#
# The wait is bounded: Docker Desktop takes about half a minute, and
# SCLAUDE_DOCKER_WAIT (seconds, 120 by default) caps it. A start that did not
# bring it up is remembered for ten minutes (DOCKER_FAILED): every step, every
# `sclaude dev` and every page the proxy starts calls this, and each would
# otherwise wait the whole limit again for the same answer.
#
# SCLAUDE_DOCKER_START=off starts nothing, for the tests and for a machine
# where Docker is somebody else's to run.
DOCKER_FAILED="${SCLAUDE_DEV_REGISTRY:-$HOME/.claude/sclaude/dev}/.docker-failed"
docker_ensure() {
  docker_up && { rm -f "$DOCKER_FAILED"; return 0; }
  [[ "${SCLAUDE_DOCKER_START:-on}" != "off" ]] || return 1
  if [[ -n "$(find "$DOCKER_FAILED" -mmin -10 2>/dev/null)" ]]; then
    warn "  docker: a start failed less than ten minutes ago — not waiting for it again"
    return 1
  fi
  local why exe="" waited=0 limit="${SCLAUDE_DOCKER_WAIT:-120}"
  [[ "$limit" =~ ^[0-9]+$ ]] || limit=120
  why="$(docker_info || true)"
  case "$why" in
    *"permission denied"*) warn "  docker: this user may not use the Docker socket"; return 1 ;;
  esac
  if exe="$(docker_desktop_exe)"; then
    info "  docker: not running — starting Docker Desktop…"
    ( setsid "$exe" </dev/null >/dev/null 2>&1 & )
  elif command -v systemctl >/dev/null 2>&1 && systemctl cat docker.service >/dev/null 2>&1 \
       && ! systemctl is-active --quiet docker && sudo -n true 2>/dev/null; then
    info "  docker: not running — starting docker.service…"
    sudo -n systemctl start docker >/dev/null 2>&1 || { touch "$DOCKER_FAILED" 2>/dev/null; return 1; }
  else
    return 1
  fi
  while ! docker_up; do
    if (( waited >= limit )); then
      warn "  docker: still not up after ${limit}s"
      mkdir -p "$(dirname "$DOCKER_FAILED")" 2>/dev/null && touch "$DOCKER_FAILED" 2>/dev/null
      return 1
    fi
    sleep 2
    waited=$((waited + 2))
  done
  rm -f "$DOCKER_FAILED"
  info "  docker: up after ${waited}s"
  return 0
}

# Starts this feature's stack if it should have one, and writes the file that
# points the feature at it. Removes that file whenever the feature should not
# have one — a feature switched to the cloud project must not keep sourcing a
# local address.
#
# A stack that cannot be started is loud and not fatal: the feature then works
# against the shared local database, as every feature did before, and the
# warning says so rather than letting it look isolated.
ensure_db() {
  local wt="$1" dir="$1/.sclaude/local/feature/supabase" envf="$1/.sclaude/local/feature/db.env"
  local log="$1/.sclaude/local/feature/db.log" state="$1/.sclaude/local/feature/state.json"
  local base cli exclude setup status

  if ! db_wanted "$wt"; then
    rm -f "$envf"
    return 0
  fi
  if ! docker_ensure; then
    rm -f "$envf"
    if [[ "${SCLAUDE_DOCKER_START:-on}" == "off" ]]; then
      warn "  database: Docker is not running — this feature shares the main local database"
    else
      warn "  database: Docker is not running and sclaude could not start it — this feature shares the main local database"
    fi
    return 0
  fi
  base="$(db_base "$wt")" || { rm -f "$envf"; warn "  database: no free block of ports — sharing the main local database"; return 0; }
  db_workdir "$wt" "$base" || { rm -f "$envf"; warn "  database: could not lay out $dir"; return 0; }
  cli="$(db_cli "$wt")"

  if ! (cd "$wt" && $cli status --workdir "$dir" -o env) >/dev/null 2>&1; then
    if [[ "$(state_get "$state" db.ready 2>/dev/null)" == "true" ]]; then
      info "  database: starting this feature's own Supabase again (its data is kept)…"
    else
      info "  database: starting this feature's own Supabase (a new one takes about a minute)…"
    fi
    exclude="$(project_get database.local.exclude "$wt" 2>/dev/null | paste -sd, -)"
    if ! (cd "$wt" && $cli start --workdir "$dir" ${exclude:+-x "$exclude"}) >> "$log" 2>&1; then
      rm -f "$envf"
      warn "  database: supabase start failed — see .sclaude/local/feature/db.log; sharing the main local database"
      return 0
    fi
  fi

  # Migrations the stack has not seen: the feature's own, written since the
  # last start, and main's, merged in by sync_branch or rebased under by
  # sync_unpublished. One out of order — main brought one numbered below one
  # already applied here — applies all the same (--include-all): refused, it
  # left the suite running on a schema without main's change. One that still
  # fails is the stack's alone, and rebuilding it is the answer.
  if ! (cd "$wt" && $cli migration up --include-all --workdir "$dir") >> "$log" 2>&1; then
    warn "  database: pending migrations did not apply — see .sclaude/local/feature/db.log."
    warn "  This feature's database is its own; rebuild it with: npx supabase db reset"
  fi

  # The temporary file is this process's own: a lazy start of the dev server
  # can run this beside the regression's, and with one shared name the first
  # mv took the file from under the second ("mv: cannot stat …db.env.tmp").
  status="$(cd "$wt" && $cli status --workdir "$dir" -o env 2>/dev/null)"
  if ! python3 "$LIB/feature_db.py" envfile "$(project_config_with database.local "$wt")" "$dir" \
         <<<"$status" > "$envf.tmp.$$"; then
    rm -f "$envf" "$envf.tmp.$$"
    warn "  database: the stack did not report every value the project maps — sharing the main local database"
    return 0
  fi
  mv "$envf.tmp.$$" "$envf"

  # Filled once: a new stack has the schema and nothing else, and a feature
  # that cannot sign anybody in cannot be looked at.
  if [[ "$(state_get "$state" db.ready 2>/dev/null)" != "true" ]]; then
    if db_copy_main "$wt"; then
      state_set "$state" db.ready true
    else
      setup="$(project_get database.local.setup "$wt" 2>/dev/null || true)"
      if [[ -n "$setup" ]]; then
        info "  database: filling it ($setup)…"
        if (cd "$wt" && set -a && . "$envf" && set +a && eval "$setup") >> "$log" 2>&1; then
          state_set "$state" db.ready true
          state_set "$state" db.filled "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        else
          warn "  database: $setup failed — see .sclaude/local/feature/db.log"
        fi
      else
        state_set "$state" db.ready true
      fi
    fi
  fi
  info "  database: this feature's own, API :$((base + 1)), Postgres :$((base + 2))"
}

# The Postgres container of a stack, by its project_id.
db_container() { echo "supabase_db_$1"; }

# The main local stack's Postgres container, by the project_id in a tree's
# tracked config (every tree carries the main one's), kept to the CLI's form
# as db_project_id keeps a feature's.
db_main_container() {
  local own
  own="$(sed -n 's/^project_id *= *"\([^"]*\)".*/\1/p' "$1/supabase/config.toml" 2>/dev/null | head -1)"
  [[ -n "$own" ]] || return 1
  own="$(sed -E 's/[^a-zA-Z0-9_.-]+/_/g' <<<"$own")"
  db_container "${own:0:40}"
}

# The migration versions a stack has applied, one a line, in order.
db_applied() {
  docker exec "$1" psql -U supabase_admin -d postgres -Atc \
    "select version from supabase_migrations.schema_migrations order by version" 2>/dev/null
}

# The versions of the migration files a listing names — the part of each
# name before its first "_", as the Supabase CLI reads it. The folder is the
# CLI's, supabase/migrations under its workdir, whatever else a product's
# config names: it is the one `migration up` and `db reset` apply.
db_file_versions() {
  sed -n 's#^\(.*/\)\{0,1\}\([0-9][0-9]*\)_[^/]*\.sql$#\2#p' | sort
}

# The main local stack, brought up to main's migrations: the files on
# origin/main (main when there is no remote), whatever the main checkout has
# checked out — another session may have it on a branch.
#
# Every feature's stack is filled from it (db_copy_main), and nothing applied
# what a merge brought: features have stacks of their own, so the main one is
# no longer where anybody writes migrations. It fell weeks behind, each copy
# carried rows shaped for an old schema, and main's migrations that came after
# then failed on them in the feature.
#
# Run at the end of a cycle, once the merge is in, and before every copy. Quiet
# when nothing is pending. A stack that is not running is left so, and a
# failure is a warning and no more: the main stack is the developer's, and
# sclaude does not rebuild it.
db_main_up() {
  local repo="${REPO:-}" main ref pending tmp cli log
  [[ -n "$repo" && -f "$repo/supabase/config.toml" ]] || return 0
  [[ -n "$(project_get database.local.environment "$repo" 2>/dev/null || true)" ]] || return 0
  main="$(db_main_container "$repo")" || return 0
  [[ "$(docker inspect -f '{{.State.Running}}' "$main" 2>/dev/null)" == "true" ]] || return 0
  ref=origin/main
  git -C "$repo" rev-parse -q --verify "$ref^{commit}" >/dev/null 2>&1 || ref=main
  git -C "$repo" rev-parse -q --verify "$ref^{commit}" >/dev/null 2>&1 || return 0
  local applied files foreign
  applied="$(db_applied "$main" | sort)"
  files="$(git -C "$repo" ls-tree --name-only "$ref" supabase/migrations/ 2>/dev/null | db_file_versions)"
  pending="$(comm -13 <(printf '%s\n' "$applied") <(printf '%s\n' "$files") | grep -c .)"
  [[ "$pending" -gt 0 ]] || return 0
  # Versions the stack has and main does not — a feature that ran on this
  # database, a migration renamed before its merge: the CLI refuses every
  # migration then, so it is said once, by name, rather than tried and failed.
  foreign="$(comm -23 <(printf '%s\n' "$applied") <(printf '%s\n' "$files") | grep . | paste -sd' ')"
  if [[ -n "$foreign" ]]; then
    warn "  database: the main local database has migrations main does not ($foreign),"
    warn "  so main's $pending new one(s) cannot be applied to it. Look at it in the main checkout."
    return 0
  fi

  # A workdir of main's own: its config and its migrations, so a branch
  # checked out in the main tree does not decide what the stack gets.
  tmp="$(mktemp -d)" || return 0
  mkdir -p "$tmp/supabase"
  if ! git -C "$repo" show "$ref:supabase/config.toml" > "$tmp/supabase/config.toml" 2>/dev/null \
     || ! git -C "$repo" archive "$ref" supabase/migrations | tar -x -C "$tmp" 2>/dev/null; then
    rm -rf "$tmp"
    warn "  database: could not read main's migrations — the main local database stays as it is"
    return 0
  fi
  # Everything else of the tree's supabase/ beside them, as db_workdir gives a
  # feature's stack: the config can name templates, a .env or seed files, and
  # without them it does not load.
  local entry
  shopt -s nullglob dotglob
  for entry in "$repo"/supabase/*; do
    case "$(basename "$entry")" in config.toml|migrations|.temp|.branches) continue ;; esac
    ln -sfn "$entry" "$tmp/supabase/$(basename "$entry")"
  done
  shopt -u nullglob dotglob
  log="$repo/.sclaude/local/db-main.log"
  mkdir -p "$(dirname "$log")"
  cli="$(db_cli "$repo")"
  info "  database: applying main's $pending new migration(s) to the main local database…"
  # --include-all: features merge in another order than their migrations are
  # numbered, and one numbered below the last applied is main's all the same;
  # without it the CLI refused it, and the stack stayed behind for good.
  # Under a lock: features end their cycles and fill new stacks in parallel,
  # and two runs on the one database clashed on the same migrations.
  if ! ( flock -w 300 9 || exit 1
         cd "$repo" && $cli migration up --include-all --workdir "$tmp" ) 9>"$repo/.sclaude/local/db-main.lock" >> "$log" 2>&1; then
    warn "  database: they did not apply — see $log"
    warn "  The main local database stays behind main; look before anything rebuilds it."
  fi
  rm -rf "$tmp"
  return 0
}

# The feature's stack built again from its own migrations, empty, for the seed
# to fill: what a copy that went wrong leaves behind otherwise is a schema
# that is neither main's nor the feature's.
db_feature_rebuild() {
  local wt="$1"
  (cd "$wt" && $(db_cli "$wt") db reset --no-seed \
     --workdir "$wt/.sclaude/local/feature/supabase") >> "$wt/.sclaude/local/feature/db.log" 2>&1 && return 0
  warn "  database: rebuilding this feature's database failed — rebuild it with: npx supabase db reset"
  return 1
}

# The feature's own migrations, applied to its stack again after the copy set
# it back to main's schema; warned about when they do not apply.
db_feature_up() {
  local wt="$1"
  (cd "$wt" && $(db_cli "$wt") migration up --include-all \
     --workdir "$wt/.sclaude/local/feature/supabase") >> "$wt/.sclaude/local/feature/db.log" 2>&1 && return 0
  warn "  database: this feature's migrations did not apply — see .sclaude/local/feature/db.log."
  warn "  This feature's database is its own; rebuild it with: npx supabase db reset"
  return 1
}

# Fills a new stack with the main local database's data, when the project asks
# for that (`copyFromMain`) and the main stack is running. Fails otherwise, and
# the caller falls back to the project's setup.
#
# A copy rather than a seed because the main database is what a developer has
# built up to look at things with — every person copied in from prod, not only
# the seeded cast — and because the ids come with it: objects in the bucket are
# kept under the user's id, the bucket is one per developer, so the copied
# people's avatars are already there and nothing new is uploaded for them. A
# seed makes new people with new ids and uploads theirs afresh.
#
# Data only, over the schema the main database has: the feature's stack is set
# back to main's last migration first (db reset --version) when it has more,
# public's tables are emptied, main's rows go in, and only then do the
# feature's own migrations apply — over main's data, as they will over
# production's. Emptied because a migration that inserts reference rows with
# generated ids inserted them in both stacks under different ids: kept, the
# feature's rows stood and main's were skipped as conflicts, while main's rows
# pointing at them loaded with foreign keys off and pointed at nothing — until
# a later migration put a foreign key back and failed on them.
#
# That needs every migration main has applied to be one of the tree's, and the
# tree to have none main lacks below main's last: otherwise the schemas cannot
# be made one, and the copy goes as INSERT ... ON CONFLICT DO NOTHING over the
# feature's schema as it stands, the rows a migration inserted kept as the
# feature has them.
#
# Triggers and foreign keys are off for the load (session_replication_role),
# so the order of tables does not matter. auth.schema_migrations is GoTrue's
# own and is left out. A row that no longer fits — a column the feature made
# NOT NULL, say — is an error in the log and is not copied; the rest is.
#
# Columns are named in every INSERT (--column-inserts), not given by position:
# the main database is often migrations behind, and a positional row from an
# older table fills the new table's columns in order — a value lands in the
# wrong column, or a column added since is left NULL. Named, a column the main
# database lacks takes its default, and one the feature dropped is an error.
#
# A main database behind the feature's migrations is the usual reason rows do
# not fit, so the warning says so and names how far behind it is.
#
# The ids that came across are recorded, and when: teardown (db_remove) needs
# to tell the people shared with the main database, whose objects are the main
# database's, from the ones this feature made.
db_copy_main() {
  local wt="$1" log="$1/.sclaude/local/feature/db.log" state="$1/.sclaude/local/feature/state.json"
  local main feature errors
  [[ "$(project_get database.local.copyFromMain "$wt" 2>/dev/null)" == "true" ]] || return 1
  main="$(db_main_container "$wt")" || return 1
  feature="$(db_container "$(db_project_id "$wt")")"
  # A Docker started a moment ago (docker_ensure) is still bringing the main
  # stack's containers back, and a copy refused now is refused for good: the
  # seed fills the stack and db.ready is set. So a stack that exists is given
  # half a minute to come up; one that does not is answered at once.
  local tries=0
  while [[ "$(docker inspect -f '{{.State.Running}}' "$main" 2>/dev/null)" != "true" ]]; do
    if (( tries >= 15 )) || ! docker inspect "$main" >/dev/null 2>&1; then
      warn "  database: the main local stack is not running — filling from the seed instead"
      return 1
    fi
    sleep 2
    tries=$((tries + 1))
  done
  # Asked before the dump, so the warning names the cause: a load into a
  # container that is not there only said "loading the copy failed".
  if ! docker inspect "$feature" >/dev/null 2>&1; then
    warn "  database: no container $feature for this feature's stack — filling from the seed instead"
    return 1
  fi
  db_main_up

  info "  database: copying the main local database into it…"
  # To a file first, and checked, rather than piped straight in: a dump that
  # fails half way — the main stack stopping mid-copy, a permission refused —
  # would otherwise load whatever it had produced, report no errors, and mark a
  # half-empty database as filled for good. A failed dump leaves the stack
  # empty and falls back to the seed. Taken before the feature's schema is set
  # back below, so that a failed dump leaves the stack as its migrations built it.
  # Main's migrations and its rows read together, under the lock db_main_up
  # applies migrations under: read apart, a parallel update could move the
  # main database between them, and the feature's schema be set to a version
  # its loaded rows were not dumped at.
  local dump="$wt/.sclaude/local/feature/db-copy.sql" theirs newest wipe="" reset="" lock
  lock="${REPO:-$wt}/.sclaude/local/db-main.lock"
  mkdir -p "$(dirname "$lock")" 2>/dev/null
  exec 8>"$lock"
  flock -w 300 8 || true
  theirs="$(db_applied "$main")"
  newest="$(tail -1 <<<"$theirs")"
  if ! docker exec "$main" pg_dump -U supabase_admin -d postgres --data-only --column-inserts \
         --on-conflict-do-nothing --schema=auth --schema=public \
         --exclude-table=auth.schema_migrations > "$dump" 2>>"$log" \
     || ! grep -q '^INSERT INTO' "$dump"; then
    exec 8>&-
    rm -f "$dump"
    warn "  database: copying the main database failed — see .sclaude/local/feature/db.log; filling from the seed instead"
    return 1
  fi
  exec 8>&-

  if [[ -n "$newest" ]] && cmp -s <(sort <<<"$theirs") \
       <(ls "$wt/supabase/migrations" 2>/dev/null | db_file_versions | awk -v n="$newest" '$0 + 0 <= n + 0'); then
    if [[ "$(db_applied "$feature")" != "$theirs" ]]; then
      info "  database: setting this feature's schema back to the main database's ($newest) for the copy…"
      if ! (cd "$wt" && $(db_cli "$wt") db reset --version "$newest" --no-seed \
              --workdir "$wt/.sclaude/local/feature/supabase") >> "$log" 2>&1; then
        rm -f "$dump"
        db_feature_rebuild "$wt"
        warn "  database: setting it back failed — see .sclaude/local/feature/db.log; filling from the seed instead"
        return 1
      fi
      reset=1
    fi
    wipe="$(docker exec "$feature" psql -U supabase_admin -d postgres -Atc \
      "select string_agg(format('%I.%I', schemaname, tablename), ', ') from pg_tables where schemaname = 'public'" 2>>"$log")"
    # Set back, the stack has main's reference rows under ids of its own
    # again: without the list to empty them by, main's rows would point at
    # nothing — the very fault this copy is shaped against.
    if [[ -n "$reset" && -z "$wipe" ]]; then
      rm -f "$dump"
      db_feature_rebuild "$wt"
      warn "  database: could not list this feature's tables to empty them — see .sclaude/local/feature/db.log; filling from the seed instead"
      return 1
    fi
  fi

  # Emptied on its own, stopping at an error: inside the load, a TRUNCATE
  # refused — a table outside public pointing into it — was one more error
  # line, and the feature's rows stood where main's were meant to go.
  if [[ -n "$wipe" ]] && ! docker exec "$feature" psql -U supabase_admin -d postgres -q -v ON_ERROR_STOP=1 \
         -c "SET session_replication_role = replica;" -c "TRUNCATE $wipe;" >>"$log" 2>&1; then
    # Set back, its reference rows are under ids of its own: main's would
    # load beside them and point at nothing. Not set back, the schema is
    # main's already and the rows go in as before.
    if [[ -n "$reset" ]]; then
      rm -f "$dump"
      db_feature_rebuild "$wt"
      warn "  database: emptying this feature's tables failed — see .sclaude/local/feature/db.log; filling from the seed instead"
      return 1
    fi
    warn "  database: emptying this feature's tables failed — main's rows go in beside the feature's, as before"
  fi
  local out rc
  out="$(docker exec -i "$feature" psql -U supabase_admin -d postgres -q \
           -c "SET session_replication_role = replica;" -f - < "$dump" 2>&1 >/dev/null)"
  rc=$?
  rm -f "$dump"
  printf '%s\n' "$out" >> "$log"
  # Set back to main's schema, the stack lacks the feature's own migrations
  # until they apply over main's rows. A load that failed, or migrations that
  # do not apply over them, leave it on a schema that is neither: it is built
  # again from the feature's migrations, and the seed fills it.
  if [[ "$rc" -ne 0 ]]; then
    [[ -n "$reset" ]] && db_feature_rebuild "$wt"
    warn "  database: loading the copy failed — see .sclaude/local/feature/db.log; filling from the seed instead"
    return 1
  fi
  if [[ -n "$reset" ]] && ! db_feature_up "$wt"; then
    db_feature_rebuild "$wt"
    warn "  database: filling from the seed instead of the copy"
    return 1
  fi
  errors="$(grep -c 'ERROR:' <<<"$out")"
  docker exec "$feature" psql -U supabase_admin -d postgres -Atc "select id from auth.users" \
    > "$wt/.sclaude/local/feature/db-copied-users" 2>>"$log" || return 1
  state_set "$state" db.filled "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  state_set "$state" db.copied true
  if [[ "${errors:-0}" -gt 0 ]]; then
    warn "  database: copied, but $errors row(s) did not fit this feature's schema — see .sclaude/local/feature/db.log"
    warn "  by table: $(db_error_tables <<<"$out")"
    db_warn_main_behind "$main" "$feature"
  fi
  info "  database: $(wc -l < "$wt/.sclaude/local/feature/db-copied-users") people copied from the main database"
  return 0
}

# Where the rows that did not fit belong, from psql's errors on stdin:
# "1278 in public.activities, 3 in public.tiers".
db_error_tables() {
  grep -oE 'ERROR: .* relation "[^"]+"' | sed -E 's/.*relation "([^"]+)"/\1/' \
    | sort | uniq -c | sort -rn \
    | awk '{ printf "%s%s in %s", (NR > 1 ? ", " : ""), $1, ($2 ~ /\./ ? $2 : "public." $2) }'
}

# Says so when the main database has not applied migrations this feature's
# stack has — the usual reason its rows do not fit. A feature's own new
# migrations are counted too; on a fresh branch there are none.
db_warn_main_behind() {
  local main="$1" feature="$2" mine theirs missing newest
  theirs="$(db_applied "$main")" || return 0
  mine="$(db_applied "$feature")" || return 0
  missing="$(comm -13 <(sort <<<"$theirs") <(sort <<<"$mine") | grep -c .)"
  [[ "$missing" -gt 0 ]] || return 0
  newest="$(tail -1 <<<"$theirs")"
  warn "  The main local database is $missing migration(s) behind this feature's (it stops at ${newest:-none})."
  warn "  Bring it up to date in the main checkout with: npx supabase migration up"
}

# The shared environment this feature works against, when it is not the
# project's local one: prints its name, or fails. A feature on the cloud dev
# project shares its database with the whole team.
db_shared_env() {
  local wt="$1" want name
  want="$(project_get database.local.environment "$wt" 2>/dev/null || true)"
  [[ -n "$want" ]] || return 1
  name="$(db_env_name "$wt")"
  [[ -n "$name" && "$name" != "$want" ]] || return 1
  echo "$name"
}

# Does this feature change the database — its migrations differ from main's,
# committed or not?
db_touches_schema() {
  local wt="$1" dir base
  dir="$(project_migrations_dir "$wt" 2>/dev/null || true)"
  [[ -n "$dir" ]] || return 1
  base="$(git -C "$wt" merge-base HEAD origin/main 2>/dev/null \
          || git -C "$wt" merge-base HEAD main 2>/dev/null)" || return 1
  [[ -n "$(git -C "$wt" diff --name-only "$base" -- "$dir" 2>/dev/null)" \
     || -n "$(git -C "$wt" status --porcelain -- "$dir" 2>/dev/null)" ]]
}

# Said at the start of a step, not refused: the cloud project is a legitimate
# place to work, only not for a change to the schema, which lands under every
# other feature pointed at it. The session's hook asks the same before a push.
db_shared_warning() {
  local wt="$1" name local
  name="$(db_shared_env "$wt")" || return 0
  db_touches_schema "$wt" || return 0
  local="$(project_get database.local.environment "$wt" 2>/dev/null)"
  warn ""
  warn "  database: this feature changes the schema ($(project_migrations_dir "$wt")),"
  warn "  but works against \"$name\", which the whole team shares — every feature"
  warn "  pointed there sees these migrations. Database work belongs on \"$local\","
  warn "  where the feature gets a database of its own: SCLAUDE_ENV=$local for one run,"
  warn "  or rm $(environment_file) to be asked again"
}

# Loads this feature's database environment into the current shell, if it has
# one. For the subshells that start the dev server and the claude session.
db_env_load() {
  local envf="$1/.sclaude/local/feature/db.env"
  [[ -f "$envf" ]] || return 0
  set -a
  # shellcheck source=/dev/null
  . "$envf"
  set +a
}

# Stops the stack and keeps its data: the next ensure_db brings it back as it
# was, in seconds rather than the minute a new one takes. For a server stopped
# by hand or for idling.
db_stop() {
  local wt="$1" dir="$1/.sclaude/local/feature/supabase"
  [[ -f "$dir/supabase/config.toml" ]] || return 0
  docker_up || return 0
  (cd "$wt" && $(db_cli "$wt") stop --workdir "$dir") >/dev/null 2>&1 \
    && echo "  ${GREEN}feature database stopped${OFF} (its data is kept)"
  return 0
}

# Removes the stack and its data. Only for a tree about to be removed — the
# volumes are the feature's database, and nothing else holds a copy.
#
# What the database owned outside itself goes first: the project's `teardown`
# (for example, the objects its people have in object storage, a bucket every
# local database of the developer's shares). It needs the database to ask who was in it, so a
# stack stopped for idling is started for the purpose. It is told which people
# were copied from the main database, and when — their objects are partly the
# main database's. A failed teardown is said, not fatal: a leftover object is a
# cost, and the tree is going either way.
db_remove() {
  local wt="$1" dir="$1/.sclaude/local/feature/supabase" envf="$1/.sclaude/local/feature/db.env"
  local log="$1/.sclaude/local/feature/db.log" cli teardown exclude
  [[ -f "$dir/supabase/config.toml" ]] || return 0
  # Started if it has to be: this is the last moment anything knows the stack
  # and its teardown exist — the tree goes next, and with it db.env and the
  # list of people copied.
  docker_ensure || { warn "  database: Docker is down — this feature's stack is left behind"; return 0; }
  cli="$(db_cli "$wt")"
  teardown="$(project_get database.local.teardown "$wt" 2>/dev/null || true)"
  if [[ -n "$teardown" && -f "$envf" ]]; then
    if ! (cd "$wt" && $cli status --workdir "$dir" -o env) >/dev/null 2>&1; then
      exclude="$(project_get database.local.exclude "$wt" 2>/dev/null | paste -sd, -)"
      (cd "$wt" && $cli start --workdir "$dir" ${exclude:+-x "$exclude"}) >> "$log" 2>&1
    fi
    # Exported rather than prefixed: `eval` is a special builtin, and an
    # assignment in front of one is not passed to what it runs.
    #
    # The list of copied people is named only for a stack that was copied. A
    # seeded one has none, and saying so by leaving the variable out keeps the
    # other case unambiguous: a list named and unreadable is a reason for the
    # teardown to remove nothing, not a sign that nobody was copied.
    local copied=""
    [[ "$(state_get "$wt/.sclaude/local/feature/state.json" db.copied 2>/dev/null)" == "true" ]] \
      && copied="$wt/.sclaude/local/feature/db-copied-users"
    if (cd "$wt" && set -a && . "$envf" && set +a \
          && { [[ -z "$copied" ]] || export SCLAUDE_DB_COPIED_USERS="$copied"; } \
          && export SCLAUDE_DB_FILLED="$(state_get "$wt/.sclaude/local/feature/state.json" db.filled 2>/dev/null)" \
          && eval "$teardown") >> "$log" 2>&1; then
      tail -1 "$log" | sed 's/^ */  /'
    else
      warn "  database: $teardown failed — what it owned outside the database may remain (.sclaude/local/feature/db.log)"
    fi
  fi
  (cd "$wt" && $cli stop --no-backup --workdir "$dir") >/dev/null 2>&1 \
    && echo "  ${GREEN}feature database removed${OFF}"
  return 0
}
