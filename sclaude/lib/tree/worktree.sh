#!/usr/bin/env bash
#
# Preparing a feature's tree and the dev server in it.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- preparing the worktree --------------------------------------------------
#
# `claude --worktree` creates a worktree but does not carry untracked files
# across, and without them the worktree does not work: .env.local is in
# .gitignore, and so is node_modules. Symlinks rather than copies — editing a key
# in the main repo must reach every feature at once.

link_env() {
  local wt="$1" name target found=0
  shopt -s nullglob
  for src in "$REPO"/.env "$REPO"/.env.*; do
    [[ -e "$src" ]] || continue
    name="$(basename "$src")"
    # A versioned one (.env.example and its like) is already in the worktree
    # as its own file, checked out with the rest.
    git -C "$wt" ls-files --error-unmatch -- "$name" >/dev/null 2>&1 && continue
    if [[ -e "$wt/$name" && ! -L "$wt/$name" ]]; then
      warn "  $name already exists here as a real file — leaving it alone"
      continue
    fi
    # .env.local in the main repo is itself a symlink to .env.dev or .env.prod,
    # and a product's switch may read the target's name to name the current
    # environment. A symlink to a symlink would give it a target named
    # ".env.local", that is an environment "local", which does not exist. So we
    # point at the same target rather than at the symlink itself.
    if [[ -L "$src" ]]; then
      target="$(readlink -f "$src")" || continue
    else
      target="$src"
    fi
    ln -sfn "$target" "$wt/$name"
    found=$((found + 1))
  done
  shopt -u nullglob
  # And the files the config names elsewhere (envs/dev/.env): untracked, so a
  # new worktree does not have them, and the tree's environments were not found.
  local env_name file rel
  while IFS= read -r env_name; do
    file="$(envs file "$REPO" "$env_name" 2>/dev/null)" || continue
    rel="${file#"$REPO"/}"
    [[ "$rel" != "$file" && "$rel" == */* && -e "$file" && ! -e "$wt/$rel" ]] || continue
    mkdir -p "$wt/$(dirname "$rel")" && ln -sfn "$(readlink -f "$file")" "$wt/$rel" \
      && found=$((found + 1))
  done < <(envs names "$REPO" 2>/dev/null)
  info "  environment: $found .env files linked to the main repo"
}

# --- a feature's environment -------------------------------------------------
#
# A feature works against this machine's chosen database, and that is a
# condition rather than a wish: the dev server, the step's checks and the
# Supabase MCP look where `.env.local` looks. It does not come about by itself —
# `link_env` points the links where they point in the main repository at the
# moment of creation, and that stands wherever it was left. After an
# `npm run db:promote` it stays on prod: returning is the last line of the "Ship
# to production" block, that is the human's step, which can be skipped. A
# feature created at that moment got `.env.local -> .env.prod`, and `npm run
# dev` came up against prod silently — indistinguishable from a normal start
# from the outside. **That is what this function is for, and it is why it still
# acts rather than merely reporting.**
#
# Which database, though, is no longer a constant. It used to be the literal
# "dev" written here three times; it is now environment_choose (environment.sh),
# which reads $SCLAUDE_ENV, then this machine's saved answer, and asks only if
# neither has one. A developer running Supabase locally and a developer on the
# shared project are both right, and this function no longer has an opinion
# about which of them is using it.
#
# No answer at all is a real outcome — a project with no environments, a call
# with no terminal to ask at. Then the only thing still worth doing is the
# original guard: refuse to leave a feature pointed at production. Everything
# else is left alone.
#
# Each worktree has its own supabase/.temp (not a symlink), so switching here
# stays inside the feature and does not touch the main repository.
# Returns 0 when the tree was already right, 1 when it was switched (a server
# started before then read the old environment), and 2 when it may be on a
# protected environment and could not be moved: no server should run in it.
force_env() {
  local wt="$1" name want
  # A product that names no environments does not do them (envs.py).
  [[ -n "$(environment_names "$wt")" ]] || return 0

  name="$(environment_current "$wt")"
  want="$(environment_choose "$wt" || true)"

  # Nobody could say where this should point. The feature keeps whatever it has,
  # unless what it has is production — which is the one answer that is wrong
  # whoever is asking.
  if [[ -z "$want" ]]; then
    if [[ -n "$name" ]] && environment_protected "$wt" "$name"; then
      warn ""
      warn "  this worktree is on \"$name\", a protected environment, and there is"
      warn "  no answer for where it should be instead (no SCLAUDE_ENV, nothing"
      warn "  saved, no terminal to ask at)."
      warn "  The dev server would run against it — fix this before trusting anything."
      return 2
    fi
    return 0
  fi

  [[ "$name" == "$want" ]] && return 0

  # The exit code tells "it was already right" from "it had to be changed": a
  # server started before the switch read the old environment and cannot be
  # trusted.
  if environment_switch "$wt" "$want"; then
    info "  environment: switched to $want${name:+ (was $name)}"
    return 1
  fi

  # .env.local moved and the CLI link did not: the server reads the right
  # file, and ensure_linked says what the link still lacks.
  local now; now="$(environment_current "$wt")"
  [[ -n "$now" && "$now" == "$want" ]] && return 1
  # Not moved at all, and it may be on production: said out loud, and the
  # dev server kept off it (2).
  warn ""
  warn "  switching this worktree to $want failed, and it is on ${now:-an unknown environment}."
  warn "  No dev server runs in it until that is fixed: readlink $(environment_link "$wt")"
  return 2
}

# What a finished install in a tree leaves in its node_modules: the hash of
# the lockfile it installed, which check_deps reads.
DEPS_MARK=".sclaude-lock"

# The product's dependencies (`deps` in its config): the folder they install
# into (dir), the lockfile that pins them, the command that installs them in
# place (install) and from scratch (ci), and a cache their old versions leave
# behind (cache, "" for none). The presets are npm's; a tree without the
# lockfile or the folder has nothing done to it, and a product that sets the
# folder or the lockfile to "" has no dependencies sclaude handles.
deps_get() {
  local key="$1" wt="${2:-${REPO:-}}" value
  if value="$(project_get "deps.$key" "$wt" 2>/dev/null)"; then
    echo "$value"
    return 0
  fi
  case "$key" in
    dir)      echo node_modules ;;
    lockfile) echo package-lock.json ;;
    install)  echo "npm install" ;;
    ci)       echo "npm ci" ;;
    cache)    echo ".next/dev" ;;
  esac
}

# The cache old dependencies leave in a tree, removed with them.
deps_drop_cache() {
  local cache; cache="$(deps_get cache "$1")"
  [[ -n "$cache" && "$cache" != /* && "$cache" != *..* ]] && rm -rf "${1:?}/$cache"
  return 0
}

# Whether the product has dependencies sclaude handles: a folder and a
# lockfile named. Without this, `rm -rf "$wt/$dir"` on an empty dir would be
# the whole tree.
deps_named() {
  [[ -n "$(deps_get dir "$1")" && -n "$(deps_get lockfile "$1")" ]]
}

deps_lock_hash() {
  sha256sum "$1/$(deps_get lockfile "$1")" 2>/dev/null | cut -d' ' -f1
}

# The product's install in a tree, and the mark when it finished.
deps_install() {
  deps_named "$1" || return 0
  local install; install="$(deps_get install "$1")"
  if ( cd "$1" && eval "$install" ); then
    deps_lock_hash "$1" > "$1/$(deps_get dir "$1")/$DEPS_MARK" 2>/dev/null || true
  else
    warn "  $install failed"
  fi
}

# A Node process working in the main checkout, if there is one: its pid. A
# server, a typecheck, a linter, a test runner or an install started there
# reads its node_modules, and `npm ci` would delete it under them. By the
# process's working directory and its executable: npm, npx, next and the
# rest all run as node, whatever title they give themselves (a plain node
# names its thread node-MainThread, npm shows "npm run dev").
#
# Two kinds do not count, or a Claude session sitting in the checkout would
# hold the refresh off for as long as it is open: Claude Code run by node,
# and the session's MCP servers — `npm exec <server>` started by the session
# itself in its directory, which runs from npx's cache and reads none of the
# checkout's packages (main_node_mcp). An `npx` the session runs through its
# shell is a tool like any other and counts: `npx tsx script.ts` imports the
# checkout's packages.
main_node_pid() {
  local proc repo
  repo="$(readlink -f "$REPO")"
  for proc in /proc/[0-9]*; do
    [[ "$(readlink -f "$proc/cwd" 2>/dev/null)" == "$repo" ]] || continue
    [[ "$(readlink -f "$proc/exe" 2>/dev/null)" == */node ]] || continue
    main_node_claude "${proc#/proc/}" && continue
    main_node_mcp "${proc#/proc/}" && continue
    echo "${proc#/proc/}"
    return 0
  done
  return 0
}

# Whether a process is Claude Code's own: the native binary, named claude,
# Claude Code's package run by node, or a plugin's hook or server run from
# ~/.claude/plugins. Not any command line that mentions claude: the shell of
# a session's Bash tool sources a snapshot under ~/.claude, and a path in a
# workshop holds "sclaude".
main_node_claude() {
  [[ "$(cat "/proc/$1/comm" 2>/dev/null)" == claude ]] && return 0
  local cmd
  cmd="$(tr '\0' ' ' 2>/dev/null <"/proc/$1/cmdline")"
  [[ "$cmd" == */claude-code/* || "$cmd" == */.claude/plugins/* ]]
}

# A process's parent pid. The field after the title, which may hold spaces
# and parentheses itself ("npm run dev", "next-server (v16…)"): read from the
# last ")" on.
proc_parent() {
  local stat rest
  stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
  rest="${stat##*) }"
  set -- $rest
  echo "${2:-}"
}

# Whether a process is one of a Claude session's MCP servers: it, or one of
# the few processes above it (node under its title, under sh), is
# `npm exec`/npx started directly by Claude Code.
main_node_mcp() {
  local pid="$1" hop name parent
  for hop in 1 2 3 4 5; do
    [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 ]] || return 1
    name="$(cat "/proc/$pid/comm" 2>/dev/null)"
    parent="$(proc_parent "$pid")"
    if [[ "$name" == "npm exec"* || "$name" == npx* ]]; then
      main_node_claude "$parent"
      return
    fi
    pid="$parent"
  done
  return 1
}

# The lock around the main checkout's node_modules: refresh_main holds it
# while `npm ci` rebuilds the directory, and link_node_modules while it links
# from it, so a feature started meanwhile neither links a half-installed
# directory nor runs a second install into the same one. In the git directory,
# shared by every worktree and outside the working tree.
deps_lock_file() {
  local dir
  dir="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
    || dir="${TMPDIR:-/tmp}/sclaude-$(printf %s "$REPO" | sha1sum | cut -c1-12)"
  mkdir -p "$dir" 2>/dev/null
  echo "$dir/sclaude-node-modules.lock"
}

# Before a feature is branched off, the main checkout is brought to
# origin/main and its node_modules to the lockfile it then has. A new tree
# links the main checkout's node_modules (link_node_modules), and check_deps
# compares the lockfiles only: a main checkout whose lockfile had moved on
# without an install handed every new feature the old packages, and nothing
# asked, since the tree's lockfile and the main one agreed.
#
# Only on main, and only a plain fast-forward: another session may have
# switched the shared checkout to a branch of its own, or be editing it, and
# both are left alone — git refuses a fast-forward that would overwrite an
# edit, where --autostash would have put the edit in the shared stash and
# could leave conflict markers behind. The tree is branched from origin/main
# either way.
#
# `npm ci`, never `npm install`: ci removes node_modules before it installs,
# so the files the other trees hard-link stay as they were, while install
# edits them in place and the edit reaches every tree through the links. Not
# while a Node process works in the checkout (main_node_pid), and its
# Turbopack cache goes with the old packages, as check_deps drops a tree's. A
# finished install leaves DEPS_MARK as a tree's does; with no mark yet, npm's
# own hidden lockfile newer than the lockfile says the install is current.
refresh_main() {
  local branch askf
  branch="$(git -C "$REPO" symbolic-ref -q --short HEAD 2>/dev/null || true)"
  if [[ "$branch" != main ]]; then
    warn "  the main checkout is on ${branch:-a detached HEAD}, not main: left as it is,"
    warn "  and the node_modules a new feature links from it may be behind origin/main."
    return 0
  fi
  # The fast-forward and the install under one lock: a second start moving
  # the lockfile while the first installs would leave the first marking
  # packages it never installed.
  askf="$(mktemp)"
  (
    flock 9
    local hash mark pid dir ci
    if ! git -C "$REPO" merge -q --ff-only origin/main >/dev/null 2>&1; then
      warn "  the main checkout could not be fast-forwarded to origin/main (an edit in"
      warn "  the way, or commits of its own): left as it is. Once it is not:"
      warn "  git -C $REPO merge --ff-only origin/main"
    fi
    deps_named "$REPO" || exit 0
    dir="$(deps_get dir "$REPO")"
    ci="$(deps_get ci "$REPO")"
    [[ -f "$REPO/$(deps_get lockfile "$REPO")" && -d "$REPO/$dir" ]] || exit 0
    hash="$(deps_lock_hash "$REPO")"
    mark="$(cat "$REPO/$dir/$DEPS_MARK" 2>/dev/null || true)"
    [[ -n "$hash" && "$mark" == "$hash" ]] && exit 0
    # npm keeps a hidden copy of the lockfile it installed; newer than the
    # lockfile, the install is current. Other tools keep none, and are asked.
    if [[ -z "$mark" && "$REPO/$dir/.package-lock.json" -nt "$REPO/$(deps_get lockfile "$REPO")" ]]; then
      printf '%s\n' "$hash" > "$REPO/$dir/$DEPS_MARK" 2>/dev/null || true
      exit 0
    fi
    # Only npm's install is run unasked: main_node_pid sees what works in
    # npm's folder, and what holds another tool's folder it cannot tell. So
    # another tool's is asked about, below and outside the lock — a question
    # can wait for hours, and every other start would wait on it — and its
    # mark written when it ran here: a file's time in the folder is no proof
    # of an install.
    if [[ "$dir" != node_modules ]]; then
      printf '%s\n' "$hash" > "$askf"
      exit 0
    fi
    pid="$(main_node_pid)"
    if [[ -n "$pid" ]]; then
      warn "  the main checkout's lockfile changed, but a Node process works in it (pid $pid):"
      warn "  its $dir was not reinstalled. Once it ends: (cd $REPO && $ci)"
      exit 0
    fi
    info "  $dir: the main checkout's lockfile changed — $ci there…"
    if ( cd "$REPO" && eval "$ci" ); then
      deps_drop_cache "$REPO"
      printf '%s\n' "$hash" > "$REPO/$dir/$DEPS_MARK" 2>/dev/null || true
    else
      warn "  $ci failed in the main checkout: run it there by hand — (cd $REPO && $ci)"
    fi
  ) 9>"$(deps_lock_file)"
  if [[ -s "$askf" ]]; then
    local dir ci answer=""
    dir="$(deps_get dir "$REPO")"
    ci="$(deps_get ci "$REPO")"
    warn "  the main checkout's lockfile changed, and its $dir may be behind it."
    ask "  Run $ci there now? Nothing should be running in it. [y/n] " answer yn || answer=""
    if is_yes "$answer"; then
      # The lock again, and the lockfile and the mark looked at again: the
      # question may have waited hours, and another start fast-forwarded and
      # installed meanwhile. The mark is the hash installed now, not the one
      # the question was asked about.
      (
        flock 9
        local now; now="$(deps_lock_hash "$REPO")"
        [[ -n "$now" && "$(cat "$REPO/$dir/$DEPS_MARK" 2>/dev/null)" == "$now" ]] && exit 0
        if ( cd "$REPO" && eval "$ci" ); then
          deps_drop_cache "$REPO"
          printf '%s\n' "$now" > "$REPO/$dir/$DEPS_MARK.tmp" 2>/dev/null \
            && mv "$REPO/$dir/$DEPS_MARK.tmp" "$REPO/$dir/$DEPS_MARK" 2>/dev/null || true
        else
          warn "  $ci failed in the main checkout: run it there by hand — (cd $REPO && $ci)"
        fi
      ) 9>"$(deps_lock_file)"
    else
      warn "  its $dir was not reinstalled. When nothing runs there: (cd $REPO && $ci)"
    fi
  fi
  rm -f "$askf"
}

# Hard links rather than a symlink to a directory: Turbopack refuses to work
# with a symlink that leads outside the project — "Symlink
# [project]/node_modules is invalid, it points out of the filesystem root" — and
# `next dev` dies at start-up. `cp -al` creates links to the same inodes, so the
# data is not duplicated: about 10 seconds and almost no space, while the
# directory is a real one.
link_node_modules() {
  local wt="$1" dir
  deps_named "$wt" || return 0
  dir="$(deps_get dir "$wt")"
  [[ -d "$REPO/$dir" ]] || { warn "  the main repo has no $dir — skipping"; return; }
  [[ -e "$wt/$dir" ]] && return
  # A symlink from earlier versions: it breaks Turbopack, so we replace it with
  # links.
  [[ -L "$wt/$dir" ]] && rm -f "$wt/$dir"
  info "  $dir: hard-linking from the main repo…"
  # Under refresh_main's lock: never from a directory a clean install is rebuilding.
  if ( flock -s 9; cp -al "$REPO/$dir" "$wt/$dir" ) 9>"$(deps_lock_file)" 2>/dev/null; then
    info "  $dir: done"
  else
    # Different filesystems or links refused — then an honest install.
    warn "  hard links did not work out, installing dependencies instead"
    deps_install "$wt"
  fi
}

# node_modules is copied with links from the main repo and is correct exactly
# while the branch has not touched the dependencies. As soon as package-lock.json
# has diverged, the directory starts lying — and lies silently, on somebody
# else's package versions.
#
# The reinstall stops this tree's dev server first and drops .next/dev with it.
# The server outlives a step, so it is usually up when this runs, and in feature
# 104 it kept serving while node_modules was torn down and reinstalled under it.
# Every page then failed with "Cannot find module '@vercel/turbopack/postcss'",
# and a plain restart did not help: Turbopack's persistent cache in .next/dev
# still resolved modules into the old tree. The step spent ten calls finding
# that out. ensure_dev starts a fresh server when the step begins, and the proxy
# does it on the next page open.
#
# Once installed here, node_modules is this tree's own, and the comparison with
# the main repo no longer says anything about it: the main checkout lagging
# behind origin made the two lockfiles differ on a branch that never touched
# them, and every start asked again — a yes tearing down a working install and
# the dev server with it. So a finished install leaves the hash of the lockfile
# it installed (DEPS_MARK), and a tree whose lockfile still has that hash is
# not asked.
check_deps() {
  local wt="$1" answer hash dir lock
  deps_named "$wt" || return 0
  dir="$(deps_get dir "$wt")"
  lock="$(deps_get lockfile "$wt")"
  [[ -d "$wt/$dir" ]] || return 0
  cmp -s "$REPO/$lock" "$wt/$lock" && return 0
  hash="$(deps_lock_hash "$wt")"
  [[ -n "$hash" && "$(cat "$wt/$dir/$DEPS_MARK" 2>/dev/null)" == "$hash" ]] && return 0
  warn ""
  warn "  $lock here differs from the main repo's (the branch or the main"
  warn "  checkout moved), and $dir was linked from there: it may not match."
  ask "  Run $(deps_get install "$wt") in this worktree? [y/n] " answer yn
  if is_yes "$answer"; then
    # An install edits the directory in place, and hard links share files with
    # the main repo — the edit would reach there too. So we tear it down and
    # install from scratch.
    stop_own_dev "$wt" && info "  dev server: stopped for the reinstall, it starts again fresh"
    deps_drop_cache "$wt"
    rm -rf "${wt:?}/$dir"
    deps_install "$wt"
  fi
}

# --- the dev server ----------------------------------------------------------
#
# The orchestrator runs the server, not the session. The reason is simple: a
# `next dev` started from a claude session stays in its process group and will
# not let it exit — and exiting is what a step ends with. `setsid` takes the
# server into a session of its own, where it outlives both claude and sclaude
# itself.
#
# Chrome, by comparison, detaches itself: `chrome-debug` does a `disown`, and the
# browser it started stays with PPID=1, holding nobody's session. So it needs no
# `setsid` — but it still has to be started, and that used to mean "by hand".
# Hence `ensure_chrome` below: the step's prompt requires checking the work
# through the chrome-devtools MCP, and the MCP server is connected with
# `--browserUrl` and does not start a browser itself — it only attaches to a port
# already open.
#
# Every feature has a server of its own, on a port of its own. It used to be one
# port for all of them, deliberately, and that stopped being right the day two
# features were worked on at once: the second one's browser and e2e went to the
# first one's server, silently and green. Nobody is meant to remember the ports,
# though. `sclaude-proxy` listens on :3000 and hands each connection to the
# server the Host names, so a feature is always http://<feature>.localhost:3000.
# A different host rather than only a different port is also what keeps two
# features' sign-ins apart in one browser: cookies ignore the port.

# An explicit DEV_PORT pins every server to that one port and bypasses the
# proxy and the registry altogether. It exists for the integration bench, which
# drives a whole `sclaude <feature>` and must neither find the developer's real
# servers nor register its fixtures next to them. Nothing in service sets it.
#
# Validated the way MERGE_POLL is: it reaches `ss | grep ":$port "`, so a
# non-numeric value would silently match nothing and make every server
# invisible.
DEV_PORT_PINNED=""
[[ "${DEV_PORT:-}" =~ ^[1-9][0-9]*$ ]] && DEV_PORT_PINNED="$DEV_PORT"

# The range the features' own ports come from. Not from 3000 up: 3000 is the
# proxy's, and the ports right after it are where other tools settle when they
# find 3000 taken.
DEV_PORT_FIRST=3100
DEV_PORT_LAST=3199

# Where the proxy listens, and where it learns which feature is where: one
# symlink per feature, <label> -> worktree. The worktree's state holds the
# port, so the link is all the proxy needs and nothing here can go stale in a
# way that matters — a link to a removed tree is skipped by both sides.
PROXY_PORT="${SCLAUDE_PROXY_PORT:-3000}"
DEV_REGISTRY="${SCLAUDE_DEV_REGISTRY:-$HOME/.claude/sclaude/dev}"

# Gives a worktree its label and its port, once, and registers it for the
# proxy. Prints nothing; the answers are in the state as `dev.label` and
# `dev.port`.
#
# Chosen once and then remembered rather than computed from the name each time:
# the state is what makes the address stable between runs, and the lock is what
# stops two sessions starting together from choosing the same port. A hash of
# the name would give neither — at a hundred ports and eight features the odds
# of two names landing on one port are about one in four.
#
# The label is the feature's slug, cut to what a DNS name allows. A tree that is
# not a feature — the main repository, run by `sclaude dev` — is `main`. A label
# another live worktree already holds gets a numeric suffix rather than taking
# the link from it.
#
# `avoid` asks for a new port even though one is recorded: the recorded one is
# held by a process from another directory, which is not ours to kill.
dev_claim() {
  local wt="$1" avoid="${2:-}" state="$1/.sclaude/local/feature/state.json" main=0
  [[ "$wt" == "${REPO:-}" ]] && main=1
  mkdir -p "$wt/.sclaude/local/feature" "$DEV_REGISTRY" || return 1
  [[ -s "$state" ]] || echo '{}' > "$state"
  (
    flock -w 10 9 || exit 1
    # An argument rather than a pipe: the script itself arrives on stdin.
    local listening
    listening="$(ss -ltnH 2>/dev/null | awk '{print $4}' | sed 's/.*://' | tr '\n' ' ')"
    PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$wt" "$state" "$DEV_REGISTRY" "$main" "$avoid" \
      "$DEV_PORT_FIRST" "$DEV_PORT_LAST" "$listening" <<'PY'
import json, os, re, sys
import state_file

wt, state, registry, main, avoid, first, last, listening = sys.argv[1:9]
first, last = int(first), int(last)
listening = {int(p) for p in listening.split() if p.isdigit()}

state_file.lock(state)
with open(state) as fh:
    data = json.load(fh)
dev = data.setdefault("dev", {})


def label_of():
    if main == "1":
        return "main"
    raw = data.get("feature") or os.path.basename(wt)
    label = re.sub(r"[^a-z0-9]+", "-", str(raw).lower()).strip("-")[:63].strip("-")
    return label or "feature"


def owner(label):
    """The worktree a label is registered to, if that worktree still exists."""
    link = os.path.join(registry, label)
    if not os.path.islink(link):
        return None
    target = os.path.realpath(link)
    if not os.path.isfile(os.path.join(target, ".sclaude/local/feature", "state.json")):
        return None
    return target


def port_of(tree):
    try:
        with open(os.path.join(tree, ".sclaude/local/feature", "state.json")) as fh:
            port = (json.load(fh).get("dev") or {}).get("port")
    except (OSError, ValueError, AttributeError):
        return None
    return port if isinstance(port, int) else None


real = os.path.realpath(wt)

label = dev.get("label")
if not label or owner(label) not in (None, real):
    base = label_of()
    label, n = base, 1
    while owner(label) not in (None, real):
        n += 1
        label = "%s-%d" % (base[:60], n)

taken = set(listening)
for name in os.listdir(registry):
    tree = owner(name)
    if tree and tree != real:
        port = port_of(tree)
        if port:
            taken.add(port)

port = dev.get("port")
if not isinstance(port, int) or avoid:
    if avoid.isdigit():
        taken.add(int(avoid))
    port = next((p for p in range(first, last + 1) if p not in taken), None)
    if port is None:
        sys.stderr.write("no free port in %d-%d\n" % (first, last))
        sys.exit(1)

dev["label"], dev["port"] = label, port
state_file.write(state, data)

link = os.path.join(registry, label)
if os.path.islink(link) or os.path.exists(link):
    os.unlink(link)
os.symlink(real, link)

# Links to trees that are gone. The proxy skips them anyway; this only keeps
# its list from filling with the dead.
for name in os.listdir(registry):
    path = os.path.join(registry, name)
    if os.path.islink(path) and not owner(name):
        os.unlink(path)
PY
  ) 9>"$DEV_REGISTRY/.lock"
}

# The port this worktree's server listens on. Claims one on first use.
feature_port() {
  local wt="$1" port
  [[ -n "$DEV_PORT_PINNED" ]] && { echo "$DEV_PORT_PINNED"; return 0; }
  port="$(state_get "$wt/.sclaude/local/feature/state.json" dev.port 2>/dev/null)"
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    dev_claim "$wt" || return 1
    port="$(state_get "$wt/.sclaude/local/feature/state.json" dev.port 2>/dev/null)"
  fi
  [[ "$port" =~ ^[0-9]+$ ]] && echo "$port"
}

# Where a person or a session opens this feature: through the proxy by its
# label, or straight at the port when the port is pinned.
feature_url() {
  local wt="$1" label
  if [[ -n "$DEV_PORT_PINNED" ]]; then
    echo "http://localhost:$DEV_PORT_PINNED"
    return 0
  fi
  label="$(state_get "$wt/.sclaude/local/feature/state.json" dev.label 2>/dev/null)"
  if [[ -z "$label" ]]; then
    dev_claim "$wt" || { echo "http://localhost:$PROXY_PORT"; return 0; }
    label="$(state_get "$wt/.sclaude/local/feature/state.json" dev.label 2>/dev/null)"
  fi
  echo "http://$label.localhost:$PROXY_PORT"
}

# Is the proxy answering? Without it the feature's address leads nowhere, and
# the direct port is the one that works.
#
# Asked many times a step — every address printed or passed on goes through
# dev_address — so it asks the proxy's cheap /__sclaude/ping, and the answer is
# kept for half a minute in a file rather than a variable: most callers are
# $(…) subshells, where a variable would be forgotten on return.
proxy_up() {
  local cache="$DEV_REGISTRY/.proxy-up" now
  now="$(date +%s)"
  if [[ -f "$cache" ]] && (( now - $(stat -c %Y "$cache" 2>/dev/null || echo 0) < 30 )); then
    [[ "$(cat "$cache" 2>/dev/null)" == "up" ]]
    return
  fi
  local answer=down
  [[ "$(curl -s -m 2 "http://127.0.0.1:$PROXY_PORT/__sclaude/ping" 2>/dev/null)" == "sclaude-proxy" ]] \
    && answer=up
  mkdir -p "$DEV_REGISTRY" 2>/dev/null && printf '%s\n' "$answer" > "$cache" 2>/dev/null
  [[ "$answer" == "up" ]]
}

# The address to hand out: the feature's own, or — when the proxy is down — the
# port itself, with nothing lost but the name.
dev_address() {
  local wt="$1"
  if [[ -z "$DEV_PORT_PINNED" ]] && ! proxy_up; then
    echo "http://localhost:$(feature_port "$wt")"
    return 0
  fi
  feature_url "$wt"
}

# The proxy's page that lists the feature's users, each a sign-in without a
# password (users_page in bin/sclaude-proxy), when it can list them: through
# the proxy, at the feature's own address, with devLogin in the project's
# config and a local database of the feature's own (supabase in
# sclaude/lib/tree/dev_login.py, which reads files only). Nothing otherwise: the
# page answered 409 or "No such feature" where the header sent the person.
#
#   dev_users_address <worktree>
dev_users_address() {
  local wt="$1" addr
  [[ -z "$DEV_PORT_PINNED" ]] && proxy_up || return 1
  addr="$(feature_url "$wt")"
  [[ "$addr" != "http://localhost:$PROXY_PORT" ]] || return 1
  python3 - "$LIB" "$wt" 2>/dev/null <<'PY' || return 1
import sys
sys.path.insert(0, sys.argv[1])
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import dev_login
try:
    sys.exit(0 if dev_login.supabase(sys.argv[2])[3] else 1)
except Exception:
    sys.exit(1)
PY
  echo "$addr/__sclaude/users"
}

# The feature's process map on the proxy (sclaude/lib/flow/process.py): where it
# stands in the cycle, lit, and what can be done with it now. Nothing when
# the proxy is not up or the feature has no label yet: the map is the
# proxy's page.
#
#   flow_address <worktree>
flow_address() {
  local label
  [[ -z "$DEV_PORT_PINNED" ]] && proxy_up || return 1
  label="$(state_get "$1/.sclaude/local/feature/state.json" dev.label 2>/dev/null)"
  [[ -n "$label" && "$label" != "null" ]] || return 1
  echo "http://localhost:$PROXY_PORT/__sclaude/flow?f=$label"
}

# Everything a process started in the feature must see besides its own
# arguments: today, the feature's own database (featuredb.sh). A no-op where that
# module is not loaded.
dev_env_load() {
  declare -F db_env_load >/dev/null || return 0
  db_env_load "$1"
}

# A feature's server listens on this machine alone: dev_loopback.cjs, loaded
# into every Node process the command starts, moves a listen on every
# interface to 127.0.0.1, where sclaude-proxy reaches it. The proxy's filter
# — this machine and the tailnet — is then the only way in. Run in the
# subshell that starts the server; NODE_OPTIONS the product sets is kept.
#
# Only for the servers sclaude starts — this dev server and the build
# regression_serve_build serves — at the user's decision (2026-11-04): not
# for the regression's parts or a session's own runs, where a test that
# listens on :: and connects over ::1, or a container calling back through
# host.docker.internal on a Linux Docker, would go red for no fault of the
# feature. A suite's webServer reuses the server already running.
dev_net_env() {
  local shim="$LIB/tree/dev_loopback.cjs"
  [[ -f "$shim" ]] || return 0
  export NODE_OPTIONS="--require=\"$shim\"${NODE_OPTIONS:+ $NODE_OPTIONS}"
  # Read back by dev_exposed_warn: a server whose environment carries it was
  # started this way, and one without it was not.
  export SCLAUDE_DEV_LOOPBACK=1
}

# The addresses past loopback a port is listened on, one a line; none when
# the server kept to this machine. The shim reaches only a Node server that
# gets sclaude's NODE_OPTIONS: a product script that sets its own
# (`NODE_OPTIONS=... next dev`) replaces it, and another runtime (bun, deno,
# python) never reads it. This is how either is seen — at the start, and
# again by every later ensure_dev that finds the server up.
dev_exposed() {
  local port="$1"
  ss -ltnH "sport = :$port" 2>/dev/null | awk '{print $4}' \
    | sed 's/%[^:]*:/:/' | grep -vE '^(127\.|\[::1\]:|\[::ffff:127\.)' || true
}

# Said when a server is open past loopback: where, and what fixes it. Once
# per server process (the PID in exposed-said beside the feature's state),
# since warn also goes to the feature's topic and ensure_dev runs at every
# step and in the regression. SCLAUDE_DEV_LOOPBACK in the environment of
# the listener or one of its parents tells the two causes apart: without it
# the server was started without dev_net_env — before it existed, or by
# hand — and a start through sclaude is the fix; with it the shim was lost
# on the way (the parents too: a launcher that gives the server an
# environment of its own drops the mark with the shim), and the product's
# command is.
dev_exposed_warn() {
  local wt="$1" port="$2" open pid said="$1/.sclaude/local/feature/exposed-said"
  open="$(dev_exposed "$port" | paste -sd' ' -)"
  [[ -n "$open" ]] || return 0
  pid="$(dev_pid "$port")"
  [[ -n "$pid" && "$(cat "$said" 2>/dev/null)" == "$pid" ]] && return 0
  [[ -n "$pid" ]] && printf '%s\n' "$pid" > "$said" 2>/dev/null
  warn "  dev server: listens on $open, past the proxy's filter."
  if [[ -n "$pid" ]] && ! dev_marked "$pid"; then
    local name
    name="$(state_get "$wt/.sclaude/local/feature/state.json" feature 2>/dev/null || true)"
    warn "  It was started without sclaude's loopback; restart it: sclaude dev --stop $name && sclaude dev $name"
  else
    warn "  Its command names that address itself, starts the server with an environment"
    warn "  of its own or NODE_OPTIONS without \$NODE_OPTIONS in it, or runs no Node;"
    warn "  127.0.0.1 there, or the environment passed on, keeps it here."
  fi
}

# Whether a process or one of its parents carries dev_net_env's mark.
dev_marked() {
  local pid="$1" n=0
  while [[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 1 && "$n" -lt 32 ]]; do
    tr '\0' '\n' 2>/dev/null <"/proc/$pid/environ" | grep -qx 'SCLAUDE_DEV_LOOPBACK=1' && return 0
    pid="$(awk '/^PPid:/ { print $2 }' "/proc/$pid/status" 2>/dev/null)"
    n=$((n + 1))
  done
  return 1
}

# The PID of the process listening on a port, or empty.
dev_pid() {
  local port="$1"
  [[ "$port" =~ ^[0-9]+$ ]] || return 0
  ss -ltnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | head -1
}

# A process's working directory — that is how we learn which worktree the server
# was started from.
dev_cwd() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  readlink -f "/proc/$pid/cwd" 2>/dev/null
}

# A log of its own for every run, and the usual name a link to the latest.
#
# `log_new <wt> <name> <prefix>` makes `.sclaude/local/feature/logs/<name
# without .log>/<prefix>_<date>_<time>.log` and points
# `.sclaude/local/feature/<name>` at it, so whatever reads or appends to the usual name meets this run alone,
# and the runs before it stay beside it to compare. One file rewritten by each
# run lost exactly the run a fixing session needed: the regression gate runs a
# red stage again before opening one, and the server is restarted before every
# local run. The files go with the worktree, so nothing prunes them.
log_new() {
  local dir="$1/.sclaude/local/feature" name="$2" file n=1 tail=""
  file="logs/${name%.log}/${3}_$(date +%Y-%m-%d_%H-%M-%S)"
  # A run that fails at once is rerun within the same second.
  while [[ -e "$dir/$file$tail.log" ]]; do n=$((n + 1)); tail="_$n"; done
  file="$file$tail.log"
  mkdir -p "$dir/logs/${name%.log}" && : > "$dir/$file" && ln -sfn "$file" "$dir/$name"
}

# The folder's own log of its runs, where a run has an outcome: `runs.tsv`
# beside the files, a line per run — the file, `passed` or what else it ended
# as, and the set it ran (a stage and its parts). Appended when the run ends.
#
#   log_end <wt> <name> <outcome> <set>
log_end() {
  local dir="$1/.sclaude/local/feature" file
  file="$(readlink "$dir/$2" 2>/dev/null)" || return 0
  printf '%s\t%s\t%s\n' "${file##*/}" "$3" "$4" >> "$dir/${file%/*}/runs.tsv" 2>/dev/null || true
}

# The file a set went red with: its first run after the last that passed on
# the same set. The set is the last run's, or with <prefix> the last run's
# whose set begins with it (a stage, `prod:`), since another stage may have
# run since. Empty when that run passed.
#
#   log_red_since <wt> <name> [<prefix>]   → a file name in the folder, or nothing
log_red_since() {
  local index
  index="$(readlink "$1/.sclaude/local/feature/$2" 2>/dev/null)" || return 0
  index="$1/.sclaude/local/feature/${index%/*}/runs.tsv"
  [[ -s "$index" ]] || return 0
  awk -F'\t' -v p="${3:-}" '{ f[NR] = $1; o[NR] = $2; s[NR] = $3 }
    END { set = ""; since = ""
          for (i = NR; i >= 1 && set == ""; i--) if (index(s[i], p) == 1) set = s[i]
          if (set == "") exit
          for (i = 1; i <= NR; i++) if (s[i] == set) since = (o[i] == "passed") ? "" : (since == "" ? f[i] : since)
          print since }' "$index"
}

# Starts the dev server for this worktree, if one is not already up from the
# same place.
#
# A process from another directory on this feature's port used to be the
# human's question — restart it, or look at somebody else's code. With a port
# per feature it is neither: it is somebody else's server that happens to sit
# where ours was going to, and a "yes" would have killed another feature's
# server. So we step aside to another port instead, and say so.
ensure_dev() {
  local wt="$1" pid cwd log port
  log="$wt/.sclaude/local/feature/dev.log"

  # A tree being removed gets no server, and no database either — see stop_dev.
  [[ -e "$wt/.sclaude/local/feature/closing" ]] && return 0

  # The regression's build on the port instead of the dev server, left there by
  # a run that did not finish — see regression_serve_build. Found running from
  # this tree, it would pass below for the dev server.
  if [[ -n "${REGRESSION_SERVING_MARK:-}" && -e "$wt/$REGRESSION_SERVING_MARK" ]]; then
    stop_own_dev "$wt" >/dev/null 2>&1
    rm -f "$wt/$REGRESSION_SERVING_MARK"
  fi

  # Before starting rather than after: the server reads the environment once at
  # start-up, and once up against prod it stays that way until a restart. The
  # check stands here rather than only in prepare_worktree, because a step may
  # resume a week later, and anyone may have moved the environment inside the
  # feature in the meantime.
  local switched=0 env_rc=0
  force_env "$wt" || env_rc=$?
  if (( env_rc == 2 )); then
    # Possibly on production, and it could not be moved: a server here would
    # read and write there. One already running is stopped, the database left.
    stop_own_dev "$wt" >/dev/null 2>&1 || true
    warn "  dev server: not started — see the environment warning above"
    return 0
  fi
  (( env_rc )) && switched=1

  port="$(feature_port "$wt")" || { warn "  dev server: no port could be claimed — see $DEV_REGISTRY"; return 0; }

  # The PATH this was started with, for sclaude-proxy: it starts a feature's
  # server itself when somebody opens a stopped one, and under systemd it has
  # none of the shell's — no nvm, so no node, no npm, no npx.
  [[ -z "$DEV_PORT_PINNED" ]] && printf '%s\n' "$PATH" > "$DEV_REGISTRY/.path" 2>/dev/null

  # The feature's own database, before the server that reads it. A server
  # started against another database — the shared one, before this feature had
  # its own, or a stack since rebuilt on other ports — is as wrong as one
  # started on the old environment, and is restarted the same way.
  if declare -F ensure_db >/dev/null; then
    local before after
    before="$(cat "$wt/.sclaude/local/feature/db.env" 2>/dev/null)"
    ensure_db "$wt"
    after="$(cat "$wt/.sclaude/local/feature/db.env" 2>/dev/null)"
    [[ "$before" == "$after" ]] || switched=1
    db_shared_warning "$wt"
  fi

  pid="$(dev_pid "$port")"
  if [[ -n "$pid" ]]; then
    cwd="$(dev_cwd "$pid")"
    if [[ "$cwd" == "$wt" ]]; then
      # Our own server, but started before the switch: it read the environment
      # at start-up, and leaving it means looking into the old database through a
      # page that looks correct.
      if [[ "$switched" -eq 0 ]]; then
        # Nothing said: a server already up is the usual case, and its
        # address is the step's header's. Starting or restarting one is said,
        # and so is one open past loopback — here too, for a server that took
        # longer than the start's wait to listen. Not restarted for it: a
        # server started by hand shares its launcher's process group, which
        # stop_dev_pid would take down with it.
        dev_exposed_warn "$wt" "$port"
        return 0
      else
        info "  dev server: restarting — it was started on the old environment"
        stop_dev_pid "$pid" "$port"
      fi
    elif [[ -n "$DEV_PORT_PINNED" ]]; then
      warn "  port $port is held by a server from ${cwd:-another directory}, and DEV_PORT pins it — not starting"
      return 0
    else
      dev_claim "$wt" "$port" || { warn "  dev server: no other port could be claimed"; return 0; }
      warn "  port $port is held by ${cwd:-another directory} — this feature moves to $(feature_port "$wt")"
      port="$(feature_port "$wt")"
    fi
  fi

  # setsid takes the server into a session of its own, nohup detaches it from
  # the terminal: without this it dies along with sclaude, and until then holds
  # claude's session. --fork is essential: without it setsid does not create a
  # session when the caller is already a group leader, and the server stays
  # attached. All three streams are closed, otherwise the $(...) substitution
  # around the call waits for the inherited stdout to close.
  #
  # PORT is the one thing that tells the server where to listen: `next dev`
  # reads it, and so does anything else that follows the convention.
  #
  # SCLAUDE_DEV_URL is where the server will be reached from, which the server
  # cannot work out for itself: it sees its own port, not the proxy's name. An
  # app builds its sign-in redirects and the links in its emails from its own
  # address, and left at localhost:3000 they lead to the list of features — or,
  # through a cookie, to another feature entirely. What the app does with it is
  # the project's business; sclaude only says it.
  local url devcmd; url="$(dev_address "$wt")"
  devcmd="$(dev_command "$wt")"
  log_new "$wt" dev.log dev
  ( cd "$wt" && dev_env_load "$wt" && dev_net_env && PORT="$port" SCLAUDE_DEV_URL="$url" \
      SCLAUDE_DEV_TREE="$wt" setsid --fork bash -c "$devcmd" > "$log" 2>&1 < /dev/null & ) >/dev/null 2>&1

  if [[ -z "$DEV_PORT_PINNED" ]] && ! proxy_up; then
    warn "  sclaude-proxy is not answering on :$PROXY_PORT — use the port directly,"
    warn "  or: systemctl --user enable --now sclaude-proxy.socket"
  fi

  # We do not wait for readiness: the first build of a cold worktree takes tens
  # of seconds, and the session would not start for all that time. The server
  # will catch up — by the time the browser matters, it has long been ready. We
  # wait only a couple of seconds to catch a start-up crash, which is visible at
  # once. DEV_START_WAIT, in whole seconds, is for a bench whose npm starts
  # nothing: there the whole wait is spent on a port that never opens.
  local waited=0 ticks=6
  [[ "${DEV_START_WAIT:-}" =~ ^[0-9]+$ ]] && ticks=$(( 10#$DEV_START_WAIT * 2 ))
  while [[ "$waited" -lt "$ticks" ]]; do
    sleep 0.5
    waited=$((waited + 1))
    [[ -n "$(dev_pid "$port")" ]] && { info "  dev server: up on $(dev_address "$wt")"; dev_exposed_warn "$wt" "$port"; return 0; }
  done
  # The port is not open yet — that is normal for a cold build, but not when the
  # process is already dead. The difference is whether a process of its own
  # session still works in this tree (dev_alive).
  if dev_alive "$wt"; then
    info "  dev server: building, $(dev_address "$wt") opens in a minute (log: .sclaude/local/feature/dev.log)"
  else
    warn "  the dev server did not start — see $log"
  fi
}

# The command that runs the product's dev server (`commands.dev`), `npm run
# dev` when the config names none. It is told where to listen by PORT.
dev_command() {
  project_get commands.dev "$1" 2>/dev/null || echo "npm run dev"
}

# Whether the dev server started in this tree is still alive, port open or
# not: every process it started carries SCLAUDE_DEV_TREE=<tree> in its
# environment, whatever it runs and whatever it calls itself.
dev_alive() {
  local proc want="SCLAUDE_DEV_TREE=$1"
  for proc in /proc/[0-9]*; do
    grep -qzxF -- "$want" "$proc/environ" 2>/dev/null && return 0
  done
  return 1
}

# --- the browser -------------------------------------------------------------

CHROME_PORT="${CHROME_DEBUG_PORT:-9222}"

# Starts Chrome with the debugging port, if it is not answering yet.
#
# The second half of the same environment as the dev server: the step's prompt
# tells it to check the work through the chrome-devtools MCP, and that one
# connects to a ready port and does not open a browser itself. While this was
# missing, a step began with "Could not connect to Chrome" and spent several
# turns finding `chrome-debug`, reading it and making sure that starting it would
# not hold the process group — a conclusion already reached and written down
# above.
#
# We measure liveness by the port answering, as `chrome-debug` itself does: it is
# an answering port that the MCP server needs, whereas `pgrep` would speak only
# of a process that might not have opened it yet or might already have lost
# it.
ensure_chrome() {
  local wt="$1" log

  # A browser already up is not brought forward: `chrome-debug` would raise the
  # window, and doing that at every start of a step means yanking it out from
  # under someone looking at another feature. It only gets this feature's
  # address, in a background tab, and not even that if a tab of this feature
  # is already open.
  if curl -sf -m 2 "http://127.0.0.1:$CHROME_PORT/json/version" >/dev/null 2>&1; then
    # "Already up" once in this process: nothing done, said again at every
    # session of every round.
    local up=""
    [[ "${CHROME_SAID:-}" == 1 ]] || up="  chrome: already up on port $CHROME_PORT"
    CHROME_SAID=1
    if command -v chrome-debug >/dev/null 2>&1; then
      case "$(chrome-debug --tab "$(dev_address "$wt")" 2>/dev/null)" in
        *opened*) info "  chrome: up on port $CHROME_PORT, this feature opened in a background tab" ;;
        *) [[ -n "$up" ]] && info "$up" ;;
      esac
    else
      [[ -n "$up" ]] && info "$up"
    fi
    return 0
  fi

  if ! command -v chrome-debug >/dev/null 2>&1; then
    warn "  chrome-debug not found — the step will have no browser to verify in"
    return 0
  fi

  # `setsid` is not needed: chrome-debug does a `disown`, and the browser stays
  # with PPID=1 (see the comment on the section above). A background start with
  # closed streams is enough, otherwise the substitution around the call would
  # wait for stdout.
  log="$wt/.sclaude/local/feature/chrome.log"
  # Opened at the feature's own address: chrome-debug with no URL lands on the
  # bare proxy, which is the list of every feature rather than this one.
  ( chrome-debug "$(dev_address "$wt")" > "$log" 2>&1 < /dev/null & ) >/dev/null 2>&1

  # We do not wait for readiness — for the same reasons as with the server: a
  # cold start is measured in seconds, and the step gets to the browser much
  # later.
  info "  chrome: starting on port $CHROME_PORT (log: .sclaude/local/feature/chrome.log)"
}

# Kills the server's whole process tree: next-server lives as a grandchild, and
# killing the parent alone would leave it an orphan still holding the port.
stop_dev_pid() {
  local pid="$1" port="$2" pgid
  [[ -n "$pid" ]] || return 0
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')"
  if [[ -n "$pgid" ]]; then
    kill -TERM -"$pgid" 2>/dev/null
  else
    kill -TERM "$pid" 2>/dev/null
  fi
  local waited=0
  while [[ "$waited" -lt 20 ]] && [[ -n "$(dev_pid "$port")" ]]; do
    sleep 0.25
    waited=$((waited + 1))
  done
  [[ -n "$pgid" && -n "$(dev_pid "$port")" ]] && kill -KILL -"$pgid" 2>/dev/null
  # A free port is not a dead group. The launcher outlives next-server by a
  # moment, and in a project it can carry a file watcher: still alive while the tree
  # is being removed, it saw the deletions as a rebuild and wrote .dev-build back
  # into the directory, and `git worktree remove` failed on "Directory not
  # empty". So the group has to be gone, not just the listener.
  if [[ -n "$pgid" ]]; then
    waited=0
    while [[ "$waited" -lt 20 ]] && kill -0 -"$pgid" 2>/dev/null; do
      sleep 0.25
      waited=$((waited + 1))
    done
    kill -0 -"$pgid" 2>/dev/null && kill -KILL -"$pgid" 2>/dev/null
  fi
  return 0
}

# Stops the server started from this worktree, and only that one. Succeeds if it
# stopped something. It leaves the database and the proxy link alone: stop_dev
# adds those for a tree about to be removed, and check_deps wants the server
# down and nothing else.
#
# Nothing is claimed here: a tree with no port recorded has no server of ours to
# stop. The one exception is 3000 — a server this tree started before features
# had ports of their own is still sitting there.
stop_own_dev() {
  local wt="$1" pid cwd port stopped=1
  for port in "$DEV_PORT_PINNED" "$(state_get "$wt/.sclaude/local/feature/state.json" dev.port 2>/dev/null)" 3000; do
    [[ -n "$port" ]] || continue
    pid="$(dev_pid "$port")"
    [[ -n "$pid" ]] || continue
    cwd="$(dev_cwd "$pid")"
    [[ "$cwd" == "$wt" ]] || continue
    stop_dev_pid "$pid" "$port"
    stopped=0
  done
  return "$stopped"
}

# Kills the server only if it was started from this worktree — we do not touch
# somebody else's. Both callers remove the tree straight after, so the proxy's
# link to it goes too, and so does the feature's own database.
#
# Which ports it looks at is stop_own_dev's business — see there.
#
# The order is the point. A browser left open on the feature keeps asking the
# proxy for it, and the proxy starts a stopped server by itself. While the
# registry link stood through the seconds db_remove takes, that is exactly what
# happened: a fresh server came up in its own session, outside every group we
# had waited for, its watcher wrote .dev-build back while git was deleting the
# tree, and `git worktree remove` failed on "Directory not empty". It would have
# brought the dropped database back too. So the tree is marked as closing and
# unlinked before anything is stopped — ensure_dev and the proxy both honour
# the mark — and the server is looked for once more after the database, for a
# start that got in before the mark did.
stop_dev() {
  local wt="$1" label stopped=0
  label="$(state_get "$wt/.sclaude/local/feature/state.json" dev.label 2>/dev/null)"
  [[ -d "$wt/.sclaude/local/feature" ]] && touch "$wt/.sclaude/local/feature/closing"
  if [[ -n "$label" && -L "$DEV_REGISTRY/$label" \
        && "$(readlink -f "$DEV_REGISTRY/$label")" == "$(readlink -f "$wt")" ]]; then
    rm -f "$DEV_REGISTRY/$label"
  fi
  stop_own_dev "$wt" && stopped=1
  # The feature's database goes with it: the volumes are its data, and a tree
  # about to be removed is the last moment anything knows they are there.
  declare -F db_remove >/dev/null && db_remove "$wt"
  stop_own_dev "$wt" && stopped=1
  [[ "$stopped" -eq 1 ]] && echo "  ${GREEN}dev server stopped${OFF}"
  return 0
}

# Removes a feature's worktree, its server and its database with it. Fails only
# when git refused and left the work in place.
#
# Removing it ends the feature for the bot as well: its Telegram topic goes
# (ask_feature_end in io.sh). The bot's record of the topic lives in the
# worktree, so it is read before the worktree goes.
remove_worktree() {
  local wt="$1" record="" label
  declare -F ask_record >/dev/null && record="$(ask_record "$wt")"
  label="$(state_get "$wt/.sclaude/local/feature/state.json" dev.label 2>/dev/null)"
  remove_worktree_tree "$wt" || return 1
  # The ref that keeps the tree the feature's last demo played
  # (skills/sdemo/demo.py, DEMO_REF) goes with the tree, once it is gone,
  # whichever way it went: nothing else would ever delete it, and it holds
  # those files from gc. A removal git refused leaves the tree, its work and
  # its demo standing.
  [[ -n "$label" ]] && git -C "$REPO" update-ref -d "refs/sclaude/demo/$label" >/dev/null 2>&1
  declare -F ask_feature_end >/dev/null && ask_feature_end "$record"
  return 0
}

# The removal itself. One failure is not a refusal: git has deleted everything
# it knew and dropped the tree from its list, and rmdir found a file written
# after that. Whoever wrote it has been stopped by now, so what is left is its
# leftovers and nothing else, and they go the same way.
remove_worktree_tree() {
  local wt="$1" out
  stop_dev "$wt"
  # sclaude's workshop inside it is a worktree of sclaude's checkout, which
  # git there knows nothing of (workshop.sh).
  declare -F workshop_remove >/dev/null && workshop_remove "$wt"
  out="$(git -C "$REPO" worktree remove --force "$wt" 2>&1)" && return 0
  if git -C "$REPO" worktree list --porcelain | grep -qxF "worktree $wt"; then
    printf '%s\n' "$out" >&2
    # The tree stays, and the work in it goes on: the bot's menu and the dev
    # server take it back.
    rm -f "$wt/.sclaude/local/feature/closing"
    return 1
  fi
  stop_own_dev "$wt"
  rm -rf -- "$wt" || return 1
  git -C "$REPO" worktree prune
  info "  removed what was written into $wt after git had deleted it"
  return 0
}

# Worktrees a session made beside the feature's, for a pull request of their
# own, once that pull request is merged. Offered by `done` before it removes the
# feature's own worktree, one question each.
#
# A session sometimes opens a side pull request from a worktree it makes itself:
# once a review moved a workflow fix into a pull request of its own from
# ~/myapp-review-dispatch-fix, and said it could be removed after the merge.
# Nothing removed it: `done` takes away the feature's own worktree, and sclaude
# never knew of the other. Here it is found by what it is — a worktree with no
# .sclaude/local/feature of its own (so no feature's, running or not), whose branch GitHub
# reports merged, with nothing uncommitted in it.
side_worktrees_offer() {
  local path branch pr answer line
  command -v gh >/dev/null 2>&1 || return 0
  while IFS= read -r line; do
    path="${line%%$'\t'*}"
    branch="${line#*$'\t'}"
    [[ -n "$path" && -n "$branch" && "$path" != "$REPO" ]] || continue
    [[ -d "$path" && ! -e "$path/.sclaude/local/feature" ]] || continue
    [[ -z "$(git -C "$path" status --porcelain 2>/dev/null)" ]] || continue
    pr="$(cd "$REPO" && gh pr list --head "$branch" --state merged --limit 1 \
            --json number --jq '.[0].number // empty' 2>/dev/null)" || continue
    [[ "$pr" =~ ^[0-9]+$ ]] || continue
    echo ""
    say "  ${BOLD}$path${OFF} is the worktree of $branch, and PR #$pr from it is merged."
    ask "${BOLD}  Remove that worktree and its local branch? [y/n] ${OFF}" answer yn
    is_yes "$answer" || continue
    if git -C "$REPO" worktree remove "$path" >/dev/null 2>&1; then
      git -C "$REPO" branch -d "$branch" >/dev/null 2>&1 \
        || warn "  local branch $branch kept: it carries commits that are not in main"
      info "  removed $path"
    else
      warn "  could not remove $path — git worktree remove $path"
    fi
  done < <(git -C "$REPO" worktree list --porcelain 2>/dev/null | awk '
    /^worktree /{ p = substr($0, 10) }
    /^branch refs\/heads\//{ print p "\t" substr($0, 19) }')
}

# The internal paths sclaude creates itself (SCRATCH_PATHS) and how they are
# kept out of git and of Vercel uploads live in scratch.sh.

# What is uncommitted in a worktree — less the internal files the script created
# itself. Those are temporary and go away with the worktree; showing them in a
# question that says "you are about to lose this work" means asking about what
# nobody minds losing. More exact paths to leave out may follow the tree.
#
#   worktree_dirt <wt> [<path>...]
worktree_dirt() {
  local wt="$1" line path p keep
  shift
  local -a skip=("${SCRATCH_PATHS[@]}" "$@")
  # We parse line by line rather than with a regex: the path in
  # `status --short` starts at the third character, and an exact comparison is
  # more reliable than a pattern that has to be escaped for every dot in a
  # name.
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    path="${line:3}"
    path="${path%/}"
    keep=1
    for p in "${skip[@]}"; do
      [[ "$path" == "$p" || "$path" == "$p/"* ]] && { keep=0; break; }
    done
    [[ "$keep" -eq 1 ]] && printf '%s\n' "$line"
  done < <(git -C "$wt" status --short --untracked-files=all 2>/dev/null)
}

# --- the branch's freshness --------------------------------------------------
#
# A feature's tree is created from a fresh origin/main (cmd_new), but time passes
# between steps: one feature's step 1 happened on 7
# September, step 2 on the eighth, and main moved 19 commits forward in a day.
# Step 2 opened on a branch without somebody else's migration 0057, which had
# already been applied to both databases: `npm run check:migrations` died at
# once, and the step's own migration would have collided with it by number. The
# session worked it out and merged main itself — five calls before the work even
# began, and that with the answer known in advance.
#
# So freshness is checked when every step opens rather than only when the tree is
# created: the gap arises precisely between steps.
#
# The decision is the same one `sclaude sync` makes, but its unambiguous half is
# done silently: for a branch with no commits of its own a fast-forward changes
# nothing except that it stops lying. A real merge is made without a question
# too; one that would stall on conflicts goes to the sync with main, whose
# session resolves them, since untangling them under a session that is about
# to open is not acceptable.
#
# Before a local regression the branch has usually not been pushed yet, and
# one that is behind main is put on top of it without a question
# (sync_unpublished): nothing of anybody else's rests on its commits.
sync_branch() {
  local wt="$1" state branch slug behind dirty
  state="$wt/.sclaude/local/feature/state.json"
  branch="$(state_get "$state" branch 2>/dev/null)" || return 0
  [[ -n "$branch" && "$branch" != "null" ]] || return 0
  slug="$(state_get "$state" feature 2>/dev/null)" || slug=""

  # A merge left under way (a sync broken off mid-way, one by hand) holds the
  # step: its files may carry conflict markers. First of all: before the
  # count of what main has, which a merge that took it all would put at none,
  # and before the check on uncommitted work its staged files would pass for.
  if merge_under_way "$wt"; then
    sync_branch_held "$wt" "$slug"
    return 1
  fi

  # Silently: the network here is a convenience rather than an obligation. No
  # origin means we work with what we have, as cmd_sync does.
  git -C "$REPO" fetch origin -q 2>/dev/null || true

  # Commits that only add deferred entries are not worth a merge
  # (deferred_to_main): they come along with the next one that is.
  behind="$(deferred_rev_count "$REPO" "$branch..origin/main")" || return 0
  # Empty or "0" means there is nothing to compare or nothing to merge in. A
  # non-number means rev-list did not work out: there is no origin/main, or the
  # branch did not resolve. We stay quiet — the step can do nothing about it, and
  # a warning at every start stops being read.
  [[ "$behind" =~ ^[0-9]+$ ]] || return 0
  [[ "$behind" -eq 0 ]] && return 0

  # Uncommitted work must not be merged into: merge would stop halfway. We check
  # before everything else — offering what is known to be impossible is
  # lying.
  dirty="$(worktree_dirt "$wt")"
  if [[ -n "$dirty" ]]; then
    warn ""
    warn "  $branch is $behind commit(s) behind origin/main, and there is"
    warn "  uncommitted work here — merge it yourself once this step is done:"
    warn "    sclaude sync ${slug:-<feature>}"
    return 0
  fi

  # A branch with no commits of its own: a fast-forward is all that is
  # needed.
  if git -C "$wt" merge --ff-only origin/main >/dev/null 2>&1; then
    info "  branch: fast-forwarded $behind commit(s) from origin/main"
    return 0
  fi

  # The fast-forward did not apply, which means the branch has something of its
  # own, and this is a real merge — made without a question. One used to stand
  # here, and its "no" bought nothing: the sync before the preview
  # (remind_prod) merges main in all the same, only later, after step 3 and the
  # review have worked on a branch that is not what merges.
  warn ""
  warn "  $branch is $behind commit(s) behind origin/main and has commits of its own:"
  warn "  merging main in before the session opens, so it does not work on a stale branch."
  # A merge that would stop on conflicts is the sync with main's (sync_offer),
  # which resolves them — the person cannot, from a phone, and a step must not
  # open on a half-merged tree. Otherwise the plain merge below, and also after
  # a sync that found nothing to resolve after all (0), or took a hand-off back
  # with nothing merged (5).
  #
  # A sync the person left unfinished is not opened again here: unasked, it
  # would come back at every start — each review round, a resume — while the
  # conflict stands. The step opens on the branch as it is, and the sync goes
  # on from the menu, or before the preview, where it has to.
  local crc=0
  if sync_broken_off "$state"; then
    merge_conflicts "$wt" nofetch >/dev/null || crc=$?
    if [[ "$crc" -eq 1 ]]; then
      warn "  A sync with main was left unfinished — the step opens on the branch as it stands."
      warn "  Carry it on with: sclaude sync ${slug:-<feature>}"
      return 0
    fi
  fi
  local synced=0
  sync_offer "$wt" "$slug" "$(state_get "$state" pr 2>/dev/null || true)" || synced=$?
  [[ "$synced" -eq 3 ]] && return 0
  if [[ "$synced" -eq 1 ]]; then
    # A half-merged tree holds the step, as above. Otherwise the sync stopped
    # short — the session left, the branch had diverged, the push failed —
    # and has said what comes next; the step opens on the branch as it is: a
    # step held by a merge nobody asked for could not be opened at all from a
    # phone.
    if merge_under_way "$wt"; then
      sync_branch_held "$wt" "$slug"
      return 1
    fi
    if git -C "$wt" merge-base --is-ancestor origin/main HEAD 2>/dev/null; then
      warn "  main is merged in here; the step opens on it."
    else
      warn "  Not merged — the step opens on the branch as it stands."
    fi
    return 0
  fi

  local merged=0
  sync_plain_merge "$wt" "$branch" "$slug" || merged=$?
  [[ "$merged" -eq 0 ]] && return 0
  if [[ "$merged" -eq 2 ]]; then
    sync_branch_held "$wt" "$slug"
    return 1
  fi
  warn "  The step opens on the branch as it stands; merge it with: sclaude sync ${slug:-<feature>}"
  return 0
}

# What a step's start says when a merge of main is under way in the tree, and
# the step is held for it.
#
#   sync_branch_held <wt> <slug>
sync_branch_held() {
  warn ""
  warn "  A merge is under way in the tree; the step has not been started."
  warn "  Finish it with: sclaude sync ${2:-<feature>}   or back it out: git -C $1 merge --abort"
}

# A branch origin has never seen, behind main, put on top of main: rebased,
# silently, when it rebases cleanly over a clean tree. Before a local
# regression (regression_gate), which judges the branch against main's
# product: main moved during step 2 once, the suite's schema check failed on
# the branch's older copy of a file main had changed, and a fixing session was
# opened only to do this rebase. A branch that was pushed is sync_branch's —
# rewriting commits somebody may have is not done without a question — and a
# rebase that would stop on a conflict is backed out and left to the suite.
#
#   sync_unpublished <wt>
sync_unpublished() {
  local wt="$1" state branch behind pr remote
  state="$wt/.sclaude/local/feature/state.json"
  branch="$(state_get "$state" branch 2>/dev/null)" || return 0
  [[ -n "$branch" && "$branch" != "null" ]] || return 0
  [[ "$(git -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null)" == "$branch" ]] || return 0
  # Pushed once, by what is known here first, before any network: a pull
  # request recorded, or an upstream of the branch's own name — GitHub
  # deletes a merged branch, and a rollback later finds it gone from origin.
  # Only of its own name: a branch started from origin/main tracks main from
  # birth (branch.autoSetupMerge), and that is no sign it was ever pushed.
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -z "$pr" || "$pr" == "null" ]] || return 0
  [[ "$(git -C "$wt" config --get "branch.$branch.merge" 2>/dev/null)" != "refs/heads/$branch" ]] || return 0
  [[ -z "$(worktree_dirt "$wt")" ]] || return 0
  # Bounded, and never a prompt: it stands before the suite, which needs no
  # network of its own.
  GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$REPO" fetch origin -q 2>/dev/null || true
  git -C "$wt" rev-parse -q --verify origin/main >/dev/null 2>&1 || return 0
  remote="$(GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" ls-remote --heads origin "$branch" 2>/dev/null)" || return 0
  [[ -z "$remote" ]] || return 0
  behind="$(deferred_rev_count "$REPO" "$branch..origin/main")" || return 0
  [[ "$behind" =~ ^[0-9]+$ && "$behind" -gt 0 ]] || return 0
  if git -C "$wt" rebase -q origin/main >/dev/null 2>&1; then
    info "  branch: not pushed yet, so put on top of origin/main ($behind commit(s) behind it)"
  else
    git -C "$wt" rebase --abort >/dev/null 2>&1 || true
  fi
  return 0
}

# The Supabase CLI's link: whether it exists at all.
#
# force_env above looks at the environment's name and stops there, and a name
# and a link are not the same thing: .env.local can point at the right file
# while the Supabase CLI is linked to another project, or to none. `supabase db
# push` obeys the link. So the link is checked on its own, and made again when
# it disagrees — before the step, while no server of this step is up yet.
ensure_linked() {
  local wt="$1" want
  [[ -f "$wt/supabase/config.toml" ]] || return 0
  want="$(environment_choose "$wt" || true)"
  [[ -n "$want" ]] || return 0
  [[ "$(environment_current "$wt")" == "$want" ]] || return 0
  [[ "$(environment_settled "$wt")" == "$want" ]] && return 0
  if environment_switch "$wt" "$want"; then
    info "  supabase: linked to \"$want\" (the CLI pointed elsewhere in this worktree)"
    return 0
  fi
  # It did not work out, and we say so out loud: the step would otherwise learn
  # of it only when a db push died in the middle of the work, or reached
  # another project.
  warn ""
  warn "  the Supabase CLI in this worktree is not linked to \"$want\", and linking"
  warn "  it failed. \`supabase db push\` is refused until it is."
  return 0
}

prepare_worktree() {
  local wt="$1"
  link_env "$wt"
  force_env "$wt"
  ensure_linked "$wt"
  link_node_modules "$wt"
  check_deps "$wt"
  scratch_hide "$REPO"
  write_vercelignore "$wt"
}
