# shellcheck shell=bash
#
# sclaude's workshop opened by hand: `sclaude workshop`, which the bot's
# 🛠 button runs in a tab on the laptop.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# The retrospective and the reviews change sclaude in their tree's workshop,
# and sclaude publishes what they made (workshop.sh). This one belongs to no
# tree and no product: the person wants something of sclaude, and a session
# does it with them, answered over Remote Control. So the script only makes the
# place and starts the session; the session reads the repository's rules and
# does the work, its review and its publishing itself, as a person working in
# the repository would (prompts/workbench.md).
#
# The place is a worktree of the checkout made from origin's main, beside it
# (workbench_dir):
# the live checkout stays read-only, since every other session runs from it
# (sclaude_guard_args). Plan mode, as the retrospective: the person approves
# what the session will do before it writes.

# Where a workshop is made: beside the checkout, under a name that does not
# begin with the checkout's path — write-guard tells a command's targets by
# the paths it names, and one naming the workshop would name the read-only
# checkout too.
workbench_dir() { printf '%s/sclaude-workshop-%s\n' "${INSTRUMENTS%/*}" "$1"; }

# Whether a commit's work is on origin's main, proven, never guessed: the
# commit itself is there (a squash pushed from it, or nothing ever committed),
# or merging it into main would change nothing (its commits there after a
# rebase or squash merge, committed and reverted, a merge's own edits
# counted).
#
# Not by patch-id, at the person's decision (2026-11-05): it took a change
# differing only in indentation, or one main had made and then reverted, for
# this one, and the work went. A pull request whose lines main has edited
# since no longer merges cleanly, and is kept, with the way back, for the
# person to remove by hand.
workbench_on_main() {
  local wt="$1" rev="$2" tree
  git -C "$wt" merge-base --is-ancestor "$rev" origin/main 2>/dev/null && return 0
  tree="$(git -C "$wt" merge-tree --write-tree origin/main "$rev" 2>/dev/null)" || return 1
  [[ "$tree" == "$(git -C "$wt" rev-parse "origin/main^{tree}" 2>/dev/null)" ]]
}

# Whether what a workshop holds is on origin's main: nothing uncommitted, and
# both its HEAD and the branch it was made on (which workbench_remove deletes,
# wherever HEAD went since) on main. Anything git cannot answer counts as not
# on main: it is kept.
workbench_published() {
  local wt="$1" branch="workshop/${1##*/sclaude-workshop-}"
  [[ -z "$(git -C "$wt" status --porcelain 2>/dev/null)" ]] || return 1
  git -C "$wt" rev-parse -q --verify origin/main >/dev/null 2>&1 || return 1
  workbench_on_main "$wt" HEAD || return 1
  ! git -C "$wt" rev-parse -q --verify "refs/heads/$branch" >/dev/null 2>&1 \
    || workbench_on_main "$wt" "$branch"
}

# Whether a session still works in a workshop: a process whose directory is
# in it. A press never removes one under a live session.
workbench_busy() {
  local wt="$1" cwd p
  for p in /proc/[0-9]*/cwd; do
    cwd="$(readlink "$p" 2>/dev/null)" || continue
    [[ "$cwd" == "$wt" || "$cwd" == "$wt"/* ]] && return 0
  done
  return 1
}

# A workshop and the branch it was made on removed; 1 when git would not. The
# branch by the workshop's name: the session may have moved HEAD to another
# (a pull request's) or left it detached.
workbench_remove() {
  local wt="$1"
  git -C "$INSTRUMENTS" worktree remove "$wt" >/dev/null 2>&1 || return 1
  git -C "$INSTRUMENTS" branch -q -D "workshop/${wt##*/sclaude-workshop-}" >/dev/null 2>&1
  return 0
}

# The worktree goes when what it holds is on origin's main, and stays, said,
# while anything is not; the way back is the conversation the session went
# on in (Claude Code may give it a new id, session_latest).
workbench_close() {
  local wt="$1" session="$2"
  GIT_TERMINAL_PROMPT=0 timeout 20 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null || true
  if workbench_published "$wt" && workbench_remove "$wt"; then
    info "  The workshop is closed: what it held is on main."
    return 0
  fi
  local latest; latest="$(session_latest "$wt" "$session" 2>/dev/null)"
  warn "  The workshop stays at $wt: it holds what main does not."
  warn "  Go on with it: cd $(printf '%q' "$wt") && claude --resume ${latest:-$session}"
}

cmd_workshop() {
  # The session's conversation needs a terminal, as a step's does.
  ( exec < /dev/tty ) 2>/dev/null \
    || die "the workshop needs a terminal: run $SELF workshop in one"
  # A machine set not to change sclaude (sclaude.contribute off, developer.sh)
  # gets no workshop either.
  [[ "$(contribute_mode)" != off ]] \
    || die "changing sclaude is off on this machine (sclaude.contribute); ./install.sh --contribute=ask turns it on"
  local stamp wt branch base session prompt kept
  GIT_TERMINAL_PROMPT=0 timeout 20 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null || true
  # Workshops an earlier press left — a pull request merged since, a session
  # that published after all — go once what they hold is on main.
  for kept in "$(workbench_dir "")"[0-9]*; do
    [[ -d "$kept" ]] && ! workbench_busy "$kept" && workbench_published "$kept" && workbench_remove "$kept" \
      && info "  removed an earlier workshop, now on main: $kept"
  done
  stamp="$(date +%Y%m%d-%H%M%S)"
  wt="$(workbench_dir "$stamp")"
  branch="workshop/$stamp"
  base="$(git -C "$INSTRUMENTS" rev-parse -q --verify origin/main 2>/dev/null \
          || git -C "$INSTRUMENTS" rev-parse HEAD)" || die "sclaude's checkout has no main"
  git -C "$INSTRUMENTS" worktree add -q -b "$branch" "$wt" "$base" 2>/dev/null \
    || die "could not make the workshop at $wt"

  prompt="$(W_DIR="$wt" W_BRANCH="$branch" W_LIVE="$INSTRUMENTS" \
    W_MAINTAINER="$(developer_is_maintainer && echo yes || echo no)" \
    W_DEV="$(developer_name 2>/dev/null || echo local)" \
    python3 - "$PROMPTS/workbench.md" <<'PY'
import os, sys
text = open(sys.argv[1], encoding="utf-8").read()
for key, env in (("<workshop>", "W_DIR"), ("<branch>", "W_BRANCH"), ("<live>", "W_LIVE"),
                 ("<maintainer>", "W_MAINTAINER"), ("<developer>", "W_DEV")):
    text = text.replace(key, os.environ.get(env, ""))
print(text)
PY
)" || die "no prompt for the workshop"

  # The live checkout read-only and sreview's folder open, as for every
  # session (sclaude_guard_args), and leniently, as a step's: tests with loops
  # and redirections name nothing the strict reading accepts.
  local -a gargs=()
  mapfile -t gargs < <(sclaude_guard_args)
  local -a guard=(--settings "{\"hooks\": {\"PreToolUse\": [$(guard_entry "${gargs[@]}" --lenient)]}}")
  session="$(new_session_id)"
  echo ""
  echo "${BOLD}${BLUE}── sclaude's workshop ──${OFF}"
  info "   opus / medium / plan · $wt ($branch)"
  echo ""
  ( cd "$wt" && claude_launch --session-id "$session" --model opus --effort medium \
      "${guard[@]}" --permission-mode plan -n "sclaude workshop" "$prompt" )
  workbench_close "$wt" "$session"
}
