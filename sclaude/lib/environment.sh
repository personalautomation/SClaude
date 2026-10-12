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

# What the product says about its environments lives in its
# .sclaude/config.json, `environments`, each one naming the .env file that
# holds it (envs.py, which this reads through). A product that names none does
# not do environments, and every caller below treats that as such rather than
# as an error — same shape as project.sh's absent sections.
#
# The tree passed in is the one the question is about: a feature's worktree,
# where link_env has put every .env file of the main repository as a symlink,
# or the main repository itself.
envs() {
  python3 "${LIB:-$(dirname "${BASH_SOURCE[0]}")}/envs.py" "$@" 2>/dev/null
}

environment_names() {
  envs names "$1" || true
}

# Whether a name is one this project protects — `protected: true`, which is how
# the product marks a database holding somebody's real data. Silence means
# protected: a name we cannot resolve is not permission.
environment_protected() {
  [[ -n "$2" ]] || return 0
  envs protected "$1" "$2"
}

# Whether an environment names a hosted Supabase project: its file's URL is a
# project's. A local stack is reached by address and has none.
environment_has_ref() {
  [[ -n "$2" ]] || return 1
  envs ref "$1" "$2" >/dev/null
}

# Whether an environment can be worked against from this machine: not
# protected, not `deployed`, and with no siteUrl other than a loopback address
# (envs.py). A deployed preview is perfectly safe to write to and still not
# somewhere a local `npm run dev` and a local browser suite belong.
environment_runnable() {
  [[ -n "$2" ]] || return 1
  envs runnable "$1" "$2"
}

# The environment a tree is on: the one whose file its .env.local points at.
environment_current() {
  envs current "$1" "$1" || true
}

# The same, but only when the Supabase CLI's link agrees with it, which is the
# answer that matters before anything writes to a database.
environment_settled() {
  envs settled "$1" "$1" || true
}

# One value from an environment's file. When the product names no file for
# it, or the file lacks the key, the person is asked at the terminal, every
# time, and told that naming the file once spares them the question. Nothing,
# and 1, without a terminal.
#
#   environment_value <tree> <name> <KEY>
environment_value() {
  local wt="$1" name="$2" key="$3" found
  if found="$(envs value "$wt" "$name" "$key")" && [[ -n "$found" ]]; then
    printf '%s' "$found"
    return 0
  fi
  [[ -t 0 && -t 2 ]] || return 1
  warn "  $key for \"$name\" is not in a file sclaude knows of." >&2
  warn "  Name the file once — \"environments\": {\"$name\": {\"env\": \".env.$name\"}} in" >&2
  warn "  .sclaude/config.json — and this question goes away." >&2
  local reply=""
  read -r -s -p "  $key: " reply < /dev/tty || return 1
  echo "" >&2
  [[ -n "$reply" ]] || return 1
  printf '%s' "$reply"
}

# Points a tree at an environment: .env.local to its file and, for a product
# on Supabase, the CLI linked to its project — or unlinked, for a local one,
# since `supabase db push` obeys a leftover ref and not .env.local. Returns 0
# when both are where they should be.
#
#   environment_switch <tree> <name> [--over-file]
environment_switch() {
  local wt="$1" name="$2" file ref password
  file="$(envs file "$wt" "$name")" || return 1
  [[ -f "$file" ]] || { warn "  $name: $file does not exist"; return 1; }
  # A .env.local that is a file of the person's own, not a link, is theirs:
  # replaced, it was gone, and no name could bring it back. Left alone, unless
  # the caller kept it to put back (--over-file, after environment_snapshot).
  if [[ -e "$wt/.env.local" && ! -L "$wt/.env.local" && "${3:-}" != "--over-file" ]]; then
    warn "  $wt/.env.local is a file of its own, not a link to an environment: left as it is."
    warn "  Move it to .env.<name> and name it under \"environments\" in .sclaude/config.json."
    return 1
  fi
  local before; before="$(readlink -f "$wt/.env.local" 2>/dev/null || true)"
  ln -sfn "$(readlink -f "$file")" "$wt/.env.local" || return 1
  # NEXT_PUBLIC_* is inlined at build time, so a .next built on the old file
  # keeps serving the old project's URL and keys. Only when the target moved:
  # relinking the CLI alone leaves the build as it is.
  [[ "$before" != "$(readlink -f "$file")" && -d "$wt/.next" ]] && rm -rf "$wt/.next"
  [[ -f "$wt/supabase/config.toml" ]] || return 0
  if ref="$(envs ref "$wt" "$name")"; then
    password="$(envs value "$wt" "$name" "$(environment_key "$wt" database)" \
                | python3 -c 'import sys, urllib.parse as u; print(u.unquote(u.urlsplit(sys.stdin.read().strip()).password or ""))' 2>/dev/null)"
    [[ -n "$password" ]] || { warn "  $name: no database URL in $file, so the Supabase CLI was not linked"; return 1; }
    # The password goes to the CLI as an argument, never to the terminal;
    # npx's own notice would echo the argv, so it is silenced.
    ( cd "$wt" && npm_config_loglevel=silent $(db_cli "$wt" 2>/dev/null || echo "npx --yes supabase") \
        link --project-ref "$ref" -p "$password" >/dev/null 2>&1 ) || return 1
  else
    rm -f "$wt/supabase/.temp/project-ref"
  fi
  [[ "$(environment_settled "$wt")" == "$name" ]]
}

# What a tree is on, exactly, kept so that it can be put back: .env.local as it
# is (a link, or a file of the person's own) and the Supabase CLI's link. A
# switch by name cannot restore a .env.local that is a plain file or points at
# a file the config does not name: environment_current has no name for it, and
# the tree used to stay on whatever it was switched to — production, after a
# rollback. Prints the directory the copy is in, private to this user.
#
#   environment_snapshot <tree>
environment_snapshot() {
  local wt="$1" dir
  dir="$(umask 077 && mktemp -d "${TMPDIR:-/tmp}/sclaude-env.XXXXXX")" || return 1
  if [[ -L "$wt/.env.local" ]]; then
    readlink "$wt/.env.local" > "$dir/link"
  elif [[ -e "$wt/.env.local" ]]; then
    cp -p "$wt/.env.local" "$dir/file"
  fi
  [[ -d "$wt/supabase/.temp" ]] && cp -rp "$wt/supabase/.temp" "$dir/temp"
  echo "$dir"
}

# Puts back what environment_snapshot kept, and removes the copy.
#
#   environment_restore <tree> <dir>
environment_restore() {
  local wt="$1" dir="$2" before
  [[ -n "$dir" && -d "$dir" ]] || return 1
  before="$(readlink -f "$wt/.env.local" 2>/dev/null || true)"
  rm -f "$wt/.env.local"
  if [[ -f "$dir/link" ]]; then
    ln -sfn "$(cat "$dir/link")" "$wt/.env.local"
  elif [[ -f "$dir/file" ]]; then
    cp -p "$dir/file" "$wt/.env.local"
  fi
  if [[ -d "$wt/supabase" ]]; then
    rm -rf "$wt/supabase/.temp"
    [[ -d "$dir/temp" ]] && cp -rp "$dir/temp" "$wt/supabase/.temp"
  fi
  # A build made on the file in between serves its keys: as environment_switch.
  [[ "$before" != "$(readlink -f "$wt/.env.local" 2>/dev/null || true)" && -d "$wt/.next" ]] \
    && rm -rf "$wt/.next"
  rm -rf "$dir"
}

# The name of a key sclaude reads from the files (`envKeys`, envs.py).
environment_key() {
  python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import envs; print(envs.keys(sys.argv[2])[sys.argv[3]])' \
    "${LIB:-$(dirname "${BASH_SOURCE[0]}")}" "$1" "$2" 2>/dev/null
}

# Production's name (envs.py: the protected environment, or of several the one
# at a public address), or nothing.
environment_production() {
  envs production "$1" || true
}

# Production's address, from the protected environment that names one.
environment_site() {
  envs site "$1" || true
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

