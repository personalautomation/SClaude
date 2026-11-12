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
# the main checkout does not have yet, a feature in flight adding it, and a
# regression stage takes the parts the worktree's list adds to main's
# (project_regression_parts). A command or the stack's tool the branch
# changed is the worktree's (project_tree_first), one key is read from the
# worktree alone (regression_serve_command), and the check before a merge
# reads the merged tree's (merge_build_check).
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
#
# A setting with choices (CHOICES in config_menu.py) set for this machine
# alone, in .sclaude/local/config.json beside the main checkout's config,
# comes first: the committed file is what the project recommends, and
# `sclaude config` writes a person's own choice there, outside git.
project_get() {
  local path="$1" wt="${2:-}" file
  if [[ "$path" != *.* && -n "${REPO:-}" ]] \
     && grep -qF "\"$path\"" "$REPO/.sclaude/local/config.json" 2>/dev/null \
     && python3 "$(dirname "${BASH_SOURCE[0]}")/config_menu.py" mine "$REPO/.sclaude/config.json" "$path" 2>/dev/null; then
    return 0
  fi
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

# Whether the product uses an integration (vercel, supabase): named in its
# team's `integrations`, or, while it names none, evidently there
# (policy.py uses). What an integration runs is run only where it is on.
product_uses() {
  python3 "$(dirname "${BASH_SOURCE[0]}")/../improve/policy.py" uses "${2:-${REPO:-.}}" "$1" 2>/dev/null
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
#
# Main's list, and in it each part the worktree's list adds, right after the
# part before it there. The stage's key is main's, so a branch that added a
# check to it went through its own regression without that check, which then
# ran first on the next feature's. A part the branch drops still runs: no
# branch switches a check off for itself before the merge. An added part's
# command is the worktree's, a key main lacks (project_get).
project_regression_parts() {
  local stage="$1" wt="${2:-}" file own p i at=0 list="$1"
  local -a out=() mine=()
  file="$(project_config "$wt")" || return 0
  # A deployed stage runs what the project chose for it
  # (project_stage_regression): none, the smoke list, or its own.
  list="$(project_stage_list "$stage" "$wt")" || return 0
  stage="$list"
  mapfile -t out < <(project_value "$file" "regression.$stage")
  own="${wt:+$wt/.sclaude/config.json}"
  if [[ -n "$own" && -f "$own" && "$own" != "$file" ]]; then
    mapfile -t mine < <(project_value "$own" "regression.$stage")
    for p in "${mine[@]}"; do
      for i in "${!out[@]}"; do
        [[ "${out[$i]}" == "$p" ]] && { at=$((i + 1)); continue 2; }
      done
      out=("${out[@]:0:$at}" "$p" "${out[@]:$at}")
      at=$((at + 1))
    done
  fi
  echo "${out[*]}"
}

# What a deployed stage's regression is: `full` (its own list in
# `regression`), `smoke` (`regression.smoke`, the product's few vital paths;
# the full list where the product declares none, since a choice to check
# less must not become checking nothing) or `none`. Absent or unknown is
# full. Read like `review`, the main checkout first.
#
#   project_stage_regression <preview|prod> [wt]
project_stage_regression() {
  local mode
  mode="$(project_get "$1Regression" "${2:-}" 2>/dev/null || true)"
  case "$mode" in
    smoke|none) echo "$mode" ;;
    *) echo full ;;
  esac
}

# Whether production has no suite by the project's own word: prodRegression
# none, or a config that reads and declares no list for it. Not when the
# config is missing or is not JSON: the list is empty then too, with nobody
# having said so, and a red must not be dropped on that (remind_prod and
# `sclaude regression <name> prod` ask this before they do).
#
#   project_prod_suite_declined [wt]
project_prod_suite_declined() {
  local wt="${1:-}" file
  [[ "$(project_stage_regression prod "$wt")" == none ]] && return 0
  file="$(project_config "$wt")" || return 1
  python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$file" 2>/dev/null || return 1
  [[ -z "$(project_regression_parts prod "$wt" 2>/dev/null)" ]]
}

# Which list of `regression` a stage runs: its own, `smoke`, or nothing
# (exit 1) for a deployed stage set to none.
#
#   project_stage_list <stage> [wt]
project_stage_list() {
  local stage="$1" wt="${2:-}"
  # A rollback's confirmation borrows production's list (regression_parts).
  [[ "$stage" == rollback ]] && stage=prod
  if [[ "$stage" == preview || "$stage" == prod ]]; then
    case "$(project_stage_regression "$stage" "$wt")" in
      none)  return 1 ;;
      smoke) project_smoke_declared "$wt" && stage=smoke ;;
    esac
  fi
  echo "$stage"
}

# Whether the product declares a smoke list, in main's config or the tree's.
project_smoke_declared() {
  local wt="${1:-}" file own
  file="$(project_config "$wt")" || return 1
  [[ -n "$(project_value "$file" regression.smoke)" ]] && return 0
  own="${wt:+$wt/.sclaude/config.json}"
  [[ -n "$own" && -f "$own" && -n "$(project_value "$own" regression.smoke)" ]]
}

# How the stage's run is named where it is not the full list: "smoke", or
# "smoke — none declared, the full list". Empty for full.
#
#   project_stage_regression_word <preview|prod> [wt]
project_stage_regression_word() {
  [[ "$(project_stage_regression "$1" "${2:-}")" == smoke ]] || return 0
  if project_smoke_declared "${2:-}"; then
    echo smoke
  else
    echo "smoke — none declared, the full list"
  fi
}

# Whether the feature is shown as video (the sdemo skill): `on`, the default,
# or `off`. Read like `review`, the main checkout first.
project_demo_mode() {
  [[ "$(project_get demo "${1:-}" 2>/dev/null || true)" == off ]] && echo off || echo on
}

# Whether a feature built in parts is shown to the person after each part
# (parts.sh): `whole`, the default — the person accepts the whole feature
# once every part is built — or `each`, where every part's session ends on
# its demo and the same Accept question.
project_part_accept() {
  [[ "$(project_get partAccept "${1:-}" 2>/dev/null || true)" == each ]] && echo each || echo whole
}

# Whether the merge goes on to production: `ask` (the question after the
# merge), `auto` (shipped without it, unless a gate was passed over or other
# features' code rides along, which are still asked) or `off` (sclaude never deploys production). Absent or unknown
# is ask. Read like `review`.
project_ship_mode() {
  local mode
  mode="$(project_get ship "${1:-}" 2>/dev/null || true)"
  case "$mode" in
    auto|off) echo "$mode" ;;
    *) echo ask ;;
  esac
}

# The parts project_regression_parts runs for this branch only: the ones its
# list adds to main's.
project_regression_added() {
  local stage="$1" wt="${2:-}" file main p out="" list
  file="$(project_config "$wt")" || return 0
  list="$(project_stage_list "$stage" "$wt")" || return 0
  main=" $(project_value "$file" "regression.$list" | tr '\n' ' ')"
  for p in $(project_regression_parts "$stage" "$wt"); do
    [[ "$main" == *" $p "* ]] || out+="${out:+ }$p"
  done
  echo "$out"
}

# A value the branch's own code depends on — the commands a stage runs, the
# tool version a feature's stack starts on — is the tree's when the branch
# changed it. Every other key is read main first (project_config), and so
# were these: a branch that changed the command its code needed, or pinned a
# newer tool, ran with main's, and its session redid by hand what sclaude had
# started. A value the branch left as it found it is still main's, so a fix
# made in the main checkout reaches every feature as before.
#
#   project_tree_first <dotted.path> [wt]
project_tree_first() {
  local path="$1" wt="${2:-}" mine base then
  if [[ -n "$wt" && -f "$wt/.sclaude/config.json" ]] \
     && mine="$(project_value "$wt/.sclaude/config.json" "$path")"; then
    base="$(git -C "$wt" merge-base HEAD main 2>/dev/null)"
    then="$(project_value <(git -C "$wt" show "$base:.sclaude/config.json" 2>/dev/null) "$path")"
    if [[ -n "$base" && "$mine" != "$then" ]]; then
      printf '%s\n' "$mine"
      return 0
    fi
  fi
  project_get "$path" "$wt"
}

# The command behind a named part. Empty means the part is not described, which
# regression_run treats as a typo rather than as something to skip.
project_command() {
  project_tree_first "commands.$1" "${2:-}" 2>/dev/null
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
# Actions, what every project had before this key), `github-local` (the same,
# and when it cannot run — Claude's limit, no Actions minutes — the feature
# moves to the review here), `local` (sclaude runs the same /code-review on
# this machine, local_review.sh) or `off`. Absent, or a word it does not
# know, is `github`: the review a project already has is not switched off by
# a typo. With `github` alone a review that cannot run stops step 4.
#
# Read from the main checkout first, not the feature's tree: where the review
# runs is a choice about the project's spending, made now (`sclaude config`),
# and a feature branched last week must not go on with the old one until it
# merges main. The tree's copy answers only where the main checkout has none.
#
# project_review_setting is the word as set; project_review_mode where the
# feature's review runs now: `github-local` is `github`, or `local` for a
# feature whose review could not run on GitHub and moved to this machine
# (review_fallback_set in review_round.sh): its tree holds the mark. Either
# github word is `local` too while the pull request is read in review blocks
# (BLOCKS_FILE in pr_context.py reads the same file).
project_review_setting() {
  local mode
  mode="$(project_get review "${1:-}" 2>/dev/null || true)"
  case "$mode" in
    local|off|github-local) echo "$mode" ;;
    *) echo github ;;
  esac
}

project_review_mode() {
  local mode
  mode="$(project_review_setting "${1:-}")"
  if [[ "$mode" == github-local ]]; then
    if [[ -n "${1:-}" && -f "$1/.sclaude/local/feature/review-fallback" ]]; then mode=local; else mode=github; fi
  fi
  # A pull request read in review blocks (review_blocks.sh) is read here:
  # a review in Actions reads the whole and cannot be held to a block. The
  # same rule as review_mode in pr_context.py.
  [[ "$mode" == github && -n "${1:-}" && -f "$1/.sclaude/local/feature/review-blocks.json" ]] && mode=local
  echo "$mode"
}

# Whether the review runs here only because the pull request is read in
# review blocks — `github`, or `github-local` with no move here — so the
# Actions run and their CI counts: the same rule as in_blocks in pr_context.py.
project_review_in_blocks() {
  [[ -n "${1:-}" && -f "$1/.sclaude/local/feature/review-blocks.json" ]] || return 1
  case "$(project_review_setting "$1")" in
    github) return 0 ;;
    github-local) [[ ! -f "$1/.sclaude/local/feature/review-fallback" ]] ;;
    *) return 1 ;;
  esac
}

# When step 4's review goes on by itself where nobody set `[g]` by hand
# (review_go_on in local_review.sh): `auto` while an /isleep night over every
# session is on (`night.py active`; a `here` night does not count), `on` always, `off` never. Absent or unknown is `auto`.
# Read like `review`, from the main checkout first.
project_sleep_mode() {
  local mode
  mode="$(project_get sleep_mode "${1:-}" 2>/dev/null || true)"
  case "$mode" in
    on|off) echo "$mode" ;;
    *) echo auto ;;
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

  proposal="$(python3 "$LIB/core/project_init.py" "$root" 2>/dev/null)" || proposal=""
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
