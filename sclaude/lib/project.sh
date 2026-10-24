#!/usr/bin/env bash
#
# What sclaude knows about the project it is looking after.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# The README has always said this tool is "not tied to any project". It was not
# true: the regression's parts and their npm scripts, the manuals' paths, the
# production host, the migrations directory and the promote procedure were all
# written into the library. A second project would have needed edits to the
# source rather than a file of its own.
#
# So they move here, into `.sclaude/config.json` in whichever repository
# sclaude is run from — the same repository it is already finding with
# `main_repo`. A file in the product rather than a table in the orchestrator:
# the answers belong to the product, they change when it changes, and the person
# changing them is the person working in it.
#
# Nothing here is required. A repository with no config still gets the cycle —
# four steps, a worktree, an issue, a pull request — and loses only what the
# config would have described: there is no regression to gate on, no manuals to
# put in front of step 1, no production to ship to. Every reader below answers
# emptiness rather than dying, and the callers already treat an empty answer as
# "we do not know" rather than as "there is nothing".
#
# The file is read on demand and not cached. It is small, it is read a handful
# of times per command, and a cache would be one more thing to invalidate when
# the wizard writes it mid-run.

# The config's path: the main checkout's, one for every feature. A worktree
# has its own copy, the one its branch carries, and was preferred once — so a
# key set in the main checkout (`merge: auto`, uncommitted or merged after the
# feature began) reached one feature and not the next. The worktree's answers
# only with no main checkout's at all; project_get also takes from it a key
# the main checkout does not have yet, a feature in flight adding it.
project_config() {
  local wt="${1:-}"
  if [[ -n "${REPO:-}" && -f "$REPO/.sclaude/config.json" ]]; then
    echo "$REPO/.sclaude/config.json"
    return 0
  fi
  [[ -n "$wt" && -f "$wt/.sclaude/config.json" ]] || return 1
  echo "$wt/.sclaude/config.json"
}

# The config file a whole section is read from, for the readers that take it
# whole rather than through project_get: the main checkout's, or the
# worktree's when only that one has the section yet — a feature adding it.
#
#   project_config_with <key> [wt]
project_config_with() {
  local key="$1" wt="${2:-}" file
  file="$(project_config "$wt")" || return 1
  if ! project_value "$file" "$key" >/dev/null \
     && [[ -n "$wt" && -f "$wt/.sclaude/config.json" ]] \
     && project_value "$wt/.sclaude/config.json" "$key" >/dev/null; then
    file="$wt/.sclaude/config.json"
  fi
  echo "$file"
}

# A value from the config by dotted path, or nothing.
#
# The same shape as state_get, and for the same reason: reading JSON with grep
# means a field that moves is read wrongly and silently. A list comes back one
# item per line, which is what every caller here wants.
project_get() {
  local path="$1" wt="${2:-}" file
  file="$(project_config "$wt")" || return 1
  # Key by key: one the main checkout lacks is taken from the worktree's copy.
  project_value "$file" "$path" && return 0
  [[ -n "$wt" && -f "$wt/.sclaude/config.json" && "$wt/.sclaude/config.json" != "$file" ]] \
    && project_value "$wt/.sclaude/config.json" "$path"
}

# One value by dotted path out of one config file; 1 when it is not there.
project_value() {
  python3 - "$1" "$2" <<'PY' 2>/dev/null
import json, sys

try:
    with open(sys.argv[1]) as fh:
        node = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)

for key in sys.argv[2].split("."):
    if not isinstance(node, dict) or key not in node:
        sys.exit(1)
    node = node[key]

if node is None:
    sys.exit(1)
if isinstance(node, list):
    # One per line: the callers read these with `while read` or into an array,
    # and a JSON list printed as itself would have to be parsed twice.
    for item in node:
        print(item if not isinstance(item, (dict, list))
              else json.dumps(item, ensure_ascii=False))
elif isinstance(node, bool):
    print(str(node).lower())
else:
    print(node)
PY
}

# True when the project describes something under this key.
project_has() {
  [[ -n "$(project_get "$1" "${2:-}" 2>/dev/null || true)" ]]
}

# --- what the rest of the orchestrator asks -----------------------------------
#
# Each of these has a default that is *absence* rather than this project's
# answer. A default that named `supabase/migrations` would work silently in the
# wrong repository, which is the failure this whole file exists to remove.

# The parts of a regression stage, in order. Empty means the project has no
# regression for that stage, and the gate skips it.
project_regression_parts() {
  local stage="$1" wt="${2:-}"
  project_get "regression.$stage" "$wt" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'
}

# The command behind a named part. Empty means the part is not described, which
# regression_run treats as a typo rather than as something to skip.
project_command() {
  project_get "commands.$1" "${2:-}" 2>/dev/null
}

# Where production lives, as the suite should address it: the siteUrl of the
# protected environment (envs.py). Its one place; `prod.siteUrl` was a second.
project_prod_url() {
  environment_site "${1:-${REPO:-.}}"
}

# The directory migrations live in, relative to the tree. Empty means the
# project has no migrations at all, and everything about promoting and reverting
# them drops out of the cycle.
project_migrations_dir() {
  project_get "database.migrations" "${1:-}" 2>/dev/null
}

# Who reviews the project's pull requests: `github` (the review workflow in
# Actions, what every project had before this key), `local` (sclaude runs the
# same /code-review on this machine, local_review.sh) or `off`. Absent, or a
# word it does not know, is `github`: the review a project already has is not
# switched off by a typo.
#
# Read from the main checkout first, not the feature's tree: where the review
# runs is a choice about the project's spending, made now (`sclaude config`),
# and a feature branched last week must not go on with the old one until it
# merges main. The tree's copy answers only where the main checkout has none.
project_review_mode() {
  local mode
  mode="$(project_get review "${1:-}" 2>/dev/null || true)"
  case "$mode" in
    local|off) echo "$mode" ;;
    *) echo github ;;
  esac
}

# Who gives QA's word (`qa`) and who merges (`merge`): `github` (a person, on
# GitHub; sclaude waits), `both` (the same, or a key pressed in sclaude's wait
# does it from here) or `auto` (sclaude does it itself and waits for nobody).
# Absent or unknown, each is what it was before the keys existed: QA on
# GitHub, and a merge sclaude offers beside the one on GitHub. Read like
# `review`, the main checkout first: a choice made now, not when a branch
# was cut.
#
#   project_flow_mode <qa|merge> [wt]
project_flow_mode() {
  local key="$1" mode
  mode="$(project_get "$key" "${2:-}" 2>/dev/null || true)"
  case "$mode" in
    github|both|auto) echo "$mode" ;;
    *) [[ "$key" == merge ]] && echo both || echo github ;;
  esac
}


# --- the board ----------------------------------------------------------------
#
# Is this column that one? Every comparison of board column names goes through
# here, and it ignores case and surrounding spaces.
#
# The names are typed by people in two places that never see each other: the
# board on GitHub and `board.columns` in .sclaude/config.json. "In QA" in one and
# "In qa" in the other is the same column to anyone reading them, and an exact
# comparison turned that into silence — no move into QA, no Done recognised,
# a wait that never ends. An empty name never matches: a column the project
# does not declare is not the column an issue has none of.
column_is() {
  local a="$1" b="$2"
  a="${a#"${a%%[![:space:]]*}"}"; a="${a%"${a##*[![:space:]]}"}"
  b="${b#"${b%%[![:space:]]*}"}"; b="${b%"${b##*[![:space:]]}"}"
  [[ -n "$a" && -n "$b" && "${a,,}" == "${b,,}" ]]
}
#
# The GitHub board a team runs its issues through: which column means "started",
# which means "ready for QA", which one QA ends in, which date fields the Gantt
# chart reads, and the label and type a new issue gets. These were literals in
# github.sh and bin/sclaude-watch — one team's board ("Backlog", "In progress",
# "In QA", "Done", a `Dev` label, a `Feature` type), silently applied to every
# other team's.
#
#   "board": {
#     "columns": { "backlog": …, "progress": …, "qa": …, "done": … },
#     "dates":   { "start": …, "end": … },
#     "issue":   { "label": …, "type": … }
#   }
#
# Every key is optional and, as everywhere in this file, absent means not done:
# no `columns.qa` and nothing is moved into QA, no `dates.start` and no date is
# written, no `issue.label` and the issue is created without one. The callers in
# github.sh, watch.sh and deploy.sh each check for an empty name before acting
# on it — an empty column compared against an empty status would otherwise match.
#
# Loaded into the variables the rest of the code already used, once per command
# (require_repo), in one python call rather than eight.
board_load() {
  local key value file
  PROGRESS_FROM="" PROGRESS_TO="" QA_FROM="" QA_TO="" QA_DONE=""
  PROGRESS_DATE_FIELD="" PROGRESS_END_FIELD="" ISSUE_LABEL="" ISSUE_TYPE=""
  file="$(project_config_with board "${1:-}")" || return 0
  while IFS=$'\t' read -r key value; do
    case "$key" in
      columns.backlog)  PROGRESS_FROM="$value" ;;
      columns.progress) PROGRESS_TO="$value"; QA_FROM="$value" ;;
      columns.qa)       QA_TO="$value" ;;
      columns.done)     QA_DONE="$value" ;;
      dates.start)      PROGRESS_DATE_FIELD="$value" ;;
      dates.end)        PROGRESS_END_FIELD="$value" ;;
      issue.label)      ISSUE_LABEL="$value" ;;
      issue.type)       ISSUE_TYPE="$value" ;;
    esac
  done < <(python3 - "$file" <<'BOARD' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        board = json.load(fh).get("board") or {}
except (OSError, ValueError, AttributeError):
    sys.exit(0)
for group in ("columns", "dates", "issue"):
    for key, value in (board.get(group) or {}).items():
        if isinstance(value, str) and value and "\t" not in value:
            print("%s.%s\t%s" % (group, key, value))
BOARD
)
  return 0
}

# --- the wizard ---------------------------------------------------------------
#
# A repository with no `.sclaude/config.json` is not an error and not a dead end: the
# orchestrator offers to write one, and the offer is worth taking because most
# of the answers are already in the repository. project_init.py reads
# package.json, the directory layout and whatever the project keeps about its
# environments, and proposes; this shows each proposal and takes a correction.
#
# Shown before taken, always. A guess accepted in silence is the failure this
# file was written to remove — a table inside the orchestrator that happened to
# match one project — and a guess that is merely invisible is the same table
# with extra steps.
#
# Returns 0 when a config now exists, non-zero when the human declined or it
# could not be written. A decline is an answer: the cycle carries on without the
# parts a config would have described.
project_init() {
  local root="${1:-$REPO}" answer proposal
  local file="$root/.sclaude/config.json"

  if [[ -f "$file" ]]; then
    info "  $root already has .sclaude/config.json"
    return 0
  fi

  echo ""
  echo "${BOLD}This repository has no .sclaude/config.json.${OFF}"
  say "  It is where sclaude keeps what it knows about a project: which checks"
  say "  make up a regression, where the manuals are, what production's address"
  say "  is, where the migrations live. Without it the cycle still runs — there"
  say "  is simply no regression to gate on and no production to ship to."
  echo ""

  proposal="$(python3 "$LIB/project_init.py" "$root" 2>/dev/null)" || proposal=""
  if [[ -z "$proposal" || "$proposal" == "{}" ]]; then
    warn "  Nothing could be worked out about this project automatically."
    info "  Write .sclaude/config.json by hand — sclaude/config.example.json is a"
    info "  starting point — and run this again."
    return 1
  fi

  say "${BOLD}Read out of the repository:${OFF}"
  echo ""
  project_init_describe "$proposal"
  echo ""

  ask "${BOLD}Write this to .sclaude/config.json? [y/n] ${OFF}" answer yn
  if ! is_yes "$answer"; then
    info "  Not written. The cycle runs without it."
    return 1
  fi

  mkdir -p "$(dirname "$file")" 2>/dev/null
  printf '%s\n' "$proposal" > "$file" || {
    warn "  could not write $file"
    return 1
  }
  echo "${GREEN}✓ Written: $file${OFF}"
  info "  Commit it: it describes the project, so it belongs to the project."
  info "  Edit it by hand whenever the answers change — nothing here rewrites it."
  return 0
}

# The proposal in a person's words rather than as JSON. What is being agreed to
# is "these commands will run against production one day", and a wall of braces
# is not a thing anybody reads before saying yes.
project_init_describe() {
  PROPOSAL_JSON="$1" python3 <<'PY'
import json, os

try:
    data = json.loads(os.environ["PROPOSAL_JSON"])
except ValueError:
    raise SystemExit(0)

commands = data.get("commands") or {}
regression = data.get("regression") or {}

if regression.get("local"):
    print("  The regression on this machine, in order:")
    for part in regression["local"]:
        print("    %-14s %s" % (part, commands.get(part, "?")))
else:
    print("  No regression on this machine — no checks were recognised.")

for stage in ("preview", "prod"):
    if regression.get(stage):
        print("  Against a %s deployment: %s"
              % (stage, ", ".join(regression[stage])))

if regression.get("manual"):
    print("  When only the manuals changed: %s" % ", ".join(regression["manual"]))

manuals = data.get("manuals") or []
if manuals:
    print("")
    print("  The manuals step 1 reads and step 3 updates:")
    for entry in manuals:
        print("    %s" % entry.get("path"))

envs = data.get("environments") if isinstance(data.get("environments"), dict) else {}
named = {k: v for k, v in envs.items() if isinstance(v, dict) and v.get("env")}
if named:
    print("")
    print("  Environments, by the .env file each one is:")
    for name, entry in named.items():
        print("    %-10s %s%s" % (name, entry["env"], "  (protected)" if entry.get("protected") else ""))

db = data.get("database") or {}
if db:
    print("")
    if db.get("migrations"):
        print("  Migrations live in: %s" % db["migrations"])
    if db.get("applyPreview"):
        print("  Applying them to the preview database: %s" % db["applyPreview"])
    if db.get("promote"):
        print("  Promoting them to production: %s" % db["promote"])

board = data.get("board") or {}
columns = board.get("columns") or {}
if columns:
    print("")
    print("  The board sclaude moves issues on:")
    for role, said in (("backlog", "a started feature leaves"),
                       ("progress", "it goes to"),
                       ("qa", "it goes to once the preview is green"),
                       ("done", "QA passes it by moving it to")):
        if columns.get(role):
            print("    %-38s '%s'" % (said, columns[role]))
dates = board.get("dates") or {}
if dates:
    print("  The date fields it fills in: %s"
          % ", ".join("'%s'" % dates[k] for k in ("start", "end") if dates.get(k)))
PY
}
