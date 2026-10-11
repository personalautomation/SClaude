#!/usr/bin/env bash
#
# Which database this machine's features work against.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# For a long time the answer was the literal string "dev", written into
# force_dev three times over. That was true while one person worked against one
# shared database. It stopped being true when the product grew a local Supabase
# stack: a developer who touches migrations wants a database nobody else is
# looking at, and a developer who only moves pixels has no reason to install
# Docker for it. Both are right, and neither is the default for the other.
#
# So the name is a per-machine setting rather than a constant, and the one place
# it is decided is here.
#
#   $SCLAUDE_ENV        explicit, and beats everything. Meant for a shell
#                       profile, a bench, a one-off `SCLAUDE_ENV=dev sclaude …`.
#   the saved answer     what this machine said last time it was asked.
#   the question         asked once, when neither of the above has an answer.
#
# What is NOT here is a default. A guess would put somebody on the shared
# database believing they were isolated, or on an empty local one believing they
# were looking at real data — and both mistakes are quiet. Asking costs one
# question per machine, once.

# Where the answer lives.
#
# Beside the QA watch and the epilogue's state, outside every repository, for
# the reason given at length in state.sh: $REPO is the product's tree, where
# `git add -A` is an everyday thing, and a service file naming a developer's
# choice would ride into somebody else's commit.
#
# One file for the machine rather than one per project: the question it answers
# is "does this person run a database locally", and that is about the person and
# their laptop, not about which repository they happen to have open. A project
# whose environments are named differently is handled by the validation below —
# a saved name the project does not know is discarded and asked again.
environment_file() {
  echo "$HOME/.claude/sclaude/environment"
}

# The names this project actually has, one per line.
#
# Read from the product's own config/environments.json rather than declared
# here: sclaude does not get to decide what a project calls its databases. A
# project without that file (or without node) answers nothing, and every caller
# below treats that as "this project does not do environments" rather than as an
# error — same shape as project.sh's absent sections.
environment_names() {
  local wt="$1"
  [[ -f "$wt/config/environments.json" ]] || return 0
  python3 - "$wt/config/environments.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)
if isinstance(data, dict):
    for name in data:
        print(name)
PY
}

# Whether a name is one this project protects — `confirm: true`, which is how
# the product marks a database holding somebody's real account.
#
# Used to keep production off the list of things a feature may be pointed at.
# Silence means protected: a name we cannot resolve is not permission.
environment_protected() {
  local wt="$1" name="$2" rc
  [[ -n "$name" ]] || return 0
  [[ -f "$wt/config/environments.json" ]] || return 0
  # The exit code is captured on its own line. `python3 … <<'PY' || return 0`
  # attaches the `||` to the redirection rather than to the finished command,
  # and the function then answers "protected" for everything — which reads as a
  # working guard and is really a guard that has stopped asking.
  python3 - "$wt/config/environments.json" "$name" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)          # unreadable: protected
entry = data.get(sys.argv[2]) if isinstance(data, dict) else None
if not isinstance(entry, dict):
    sys.exit(0)          # unknown name: protected
sys.exit(1 if not entry.get("confirm") else 0)
PY
  rc=$?
  return "$rc"
}

# Whether an environment names a hosted project — a `ref` the Supabase CLI can
# be linked to.
#
# A local stack has none: it is reached by address, and `env:<name>` skips the
# link for it. Callers use this to tell "the link is missing and should be made"
# from "there is no link to make", which otherwise look identical from outside.
#
# Silence means no ref, like everywhere else here: unreadable config, unknown
# name and a null ref all mean the same thing to every caller.
environment_has_ref() {
  local wt="$1" name="$2" rc
  [[ -n "$name" ]] || return 1
  [[ -f "$wt/config/environments.json" ]] || return 1
  # Exit code on its own line, for the reason in environment_protected above.
  python3 - "$wt/config/environments.json" "$name" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
entry = data.get(sys.argv[2]) if isinstance(data, dict) else None
if not isinstance(entry, dict):
    sys.exit(1)
sys.exit(0 if entry.get("ref") else 1)
PY
  rc=$?
  return "$rc"
}

# Whether an environment can be worked against from this machine.
#
# Not every unprotected environment can. A project may declare one that names a
# deployed host rather than a developer's own server — this product's `preview`
# is the case that taught us: it is the name the Vercel previews run under, it
# shares its database with `dev`, and it is perfectly safe to write to. It is
# simply not somewhere a local `npm run dev` and a local browser suite belong,
# and the suite says so by refusing to start.
#
# The signal is `siteUrl`, which is already the project's statement of "where
# does this answer": a loopback address for the environments a developer runs,
# something else for a deployed one, and null where there is no fixed address
# because every deployment gets its own. A separate flag would be a second
# answer to a question the config already answers.
#
# **A project that names no address anywhere is answering nothing, not "no".**
# The first version read a missing `siteUrl` as "not runnable", which is right
# for a config that uses the field and wrong for one that does not: there every
# environment fell out, `environment_choices` came back empty, and force_env
# stopped switching at all — including away from a production environment a
# `db:promote` had left behind, which is the guard it exists for. So the field
# is consulted only where the project uses it: if no environment declares one,
# it tells us nothing and everything unprotected stays a choice.
#
# Where the field *is* used, absent or unreadable still means not runnable. The
# cost of that direction is one fewer environment offered; the cost of the other
# is a feature pointed somewhere its own regression refuses to run.
environment_runnable() {
  local wt="$1" name="$2" rc
  [[ -n "$name" ]] || return 1
  [[ -f "$wt/config/environments.json" ]] || return 1
  python3 - "$wt/config/environments.json" "$name" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)
entry = data.get(sys.argv[2])
if not isinstance(entry, dict):
    sys.exit(1)

# Does this project use siteUrl at all? If no environment declares one, the
# field says nothing here and cannot be read as a refusal -- see the note above.
uses_site = any(
    isinstance(v, dict) and v.get("siteUrl") for v in data.values()
)
if not uses_site:
    sys.exit(0)

site = entry.get("siteUrl") or ""
sys.exit(0 if ("localhost" in site or "127.0.0.1" in site) else 1)
PY
  rc=$?
  return "$rc"
}

# The names a feature may be pointed at: everything this project declares, minus
# the protected ones and the ones that cannot be run against from here.
environment_choices() {
  local wt="$1" name
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    environment_protected "$wt" "$name" && continue
    environment_runnable "$wt" "$name" || continue
    printf '%s\n' "$name"
  done < <(environment_names "$wt")
}

# The saved answer, if it is still a name this project offers.
#
# Validated on every read rather than trusted: the file outlives the project it
# was written for, and a machine that worked on two products would otherwise
# carry one's answer into the other. An unusable saved name is simply not an
# answer — the caller asks again.
environment_saved() {
  local wt="$1" saved file
  file="$(environment_file)"
  [[ -f "$file" ]] || return 1
  saved="$(tr -d '[:space:]' < "$file" 2>/dev/null || true)"
  [[ -n "$saved" ]] || return 1
  # Process substitution rather than a pipe. `grep -q` exits on its first match,
  # which kills `environment_choices` with SIGPIPE, and `set -o pipefail`
  # (bin/sclaude) then reports the whole pipeline as failed — so a saved answer
  # was rejected unless it happened to be the *last* line of the list, and the
  # machine was asked again on every step. The bench missed it because its
  # fixture saves the name that sorts last.
  grep -qxF "$saved" < <(environment_choices "$wt") || return 1
  printf '%s' "$saved"
}

environment_save() {
  local name="$1" file dir
  file="$(environment_file)"
  dir="$(dirname "$file")"
  mkdir -p "$dir" 2>/dev/null || return 0
  printf '%s\n' "$name" > "$file" 2>/dev/null || true
}

# The answer, asking if there is nobody who has answered yet.
#
# Returns the name on stdout, or nothing at all when the question cannot be put
# — no terminal, no channel, a project with no environments to choose from.
# "Nothing" is a real answer here and every caller handles it by leaving the
# worktree's environment alone: refusing to run because a question went
# unanswered would stop `sclaude status`, which the bot calls with a timeout and
# no terminal.
environment_choose() {
  local wt="$1" saved choices count name reply

  if [[ -n "${SCLAUDE_ENV:-}" ]]; then
    # An explicit name still may not be production, and still has to be somewhere
    # a feature can actually be worked on: the variable is a convenience, not an
    # override of the two rules this file has. Ignoring it rather than failing —
    # the fallbacks below are perfectly good answers, and a variable set once in
    # a profile should not stop a cycle months later.
    if environment_protected "$wt" "$SCLAUDE_ENV"; then
      warn "  SCLAUDE_ENV=$SCLAUDE_ENV names a protected environment — ignoring it." >&2
    elif ! environment_runnable "$wt" "$SCLAUDE_ENV"; then
      warn "  SCLAUDE_ENV=$SCLAUDE_ENV is not an environment a feature can run" >&2
      warn "  against on this machine — ignoring it." >&2
    else
      printf '%s' "$SCLAUDE_ENV"
      return 0
    fi
  fi

  saved="$(environment_saved "$wt" || true)"
  if [[ -n "$saved" ]]; then
    printf '%s' "$saved"
    return 0
  fi

  mapfile -t choices < <(environment_choices "$wt")
  count="${#choices[@]}"
  [[ "$count" -gt 0 ]] || return 0

  # One choice is not a question. This is the ordinary case for a project with a
  # single unprotected environment, and asking would be a toll.
  if [[ "$count" -eq 1 ]]; then
    environment_save "${choices[0]}"
    printf '%s' "${choices[0]}"
    return 0
  fi

  # The question is asked once per machine, and the answer outlives this
  # feature — so it is worth a sentence of explanation rather than a bare list.
  info "" >&2
  info "  Which database should features on this machine work against?" >&2
  info "  Asked once; change it later with: rm $(environment_file)" >&2
  local i=1
  for name in "${choices[@]}"; do
    info "    $i) $name" >&2
    i=$((i + 1))
  done

  ask "  Choose 1-$count: " reply "pick:$count" "${choices[@]}" || return 0
  [[ "$reply" =~ ^[0-9]+$ ]] || return 0
  [[ "$reply" -ge 1 && "$reply" -le "$count" ]] || return 0

  name="${choices[$((reply - 1))]}"
  environment_save "$name"
  printf '%s' "$name"
}

