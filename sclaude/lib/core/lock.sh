#!/usr/bin/env bash
#
# Machine-wide queues: one holder at a time for work two features must not do
# side by side.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Two features ran in parallel for the first time on 2026-10-06, each in its
# own sclaude, and two kinds of work collided:
#
#   * the local regression. One's e2e failed on timeouts while the other's sessions
#     ran tsc and next-server beside it — load average 6–7 on eight CPUs. A
#     fixing session spent its time proving that nothing was wrong with the
#     code, and the timings both runs wrote made the next estimates wrong;
#   * the friction review. Both features started one at 00:31 from the same
#     instruments commit, two conversations editing the orchestrator in one
#     working tree. They happened to touch different files. Nothing made sure
#     they would, and run_friction's commit range (before..after) took for
#     granted that nothing else moved HEAD while its review ran.
#
# Both are flock(1) on a file, held by a process that ends with the sclaude
# that took it — Ctrl-C, a closed tab, a crash — so there is no stale lock to
# clean up. Beside the lock lies a holder note, which only says who is in front
# while somebody waits.

# Takes a queue, waiting for its holder to finish first.
#
#   lock_take <var> <file> <who> <what>
#
# <var> receives the holder's pid, for lock_release; the function's own
# variables are prefixed, so no name a caller passes is shadowed. <who> is
# written to the holder note — the feature and the work, as the waiting side
# will read it. <what> names the work for the waiting line: "a regression".
#
# The lock is held by a small process of its own, not by this shell. Held
# here, its descriptor would pass to every child started while it is held —
# and a `next dev` restarted inside the queue outlives the run, so it would
# hold the queue shut for every other feature until somebody stopped it. The
# holder watches this shell and lets go when it is gone (Ctrl-C, a closed
# tab), so there is no stale lock either.
#
# Never a reason to stop: a lock that cannot be taken is skipped with a
# warning, as before this existed. A queue is a courtesy between features;
# the work itself is not hostage to it.
lock_take() {
  local __lock_var="$1" __lock_file="$2" __lock_who="$3" __lock_what="$4"
  local __lock_ready __lock_pid __lock_holder __lock_started __lock_told=""
  printf -v "$__lock_var" '%s' ""
  command -v flock >/dev/null 2>&1 || return 0
  mkdir -p "$(dirname "$__lock_file")" 2>/dev/null || return 0
  __lock_ready="$(mktemp -u "${TMPDIR:-/tmp}/sclaude-lock.XXXXXX")"
  (
    exec 9>>"$__lock_file" || exit 1
    if ! flock -n 9; then
      : > "$__lock_ready.busy"
      flock 9 || exit 1
    fi
    : > "$__lock_ready"
    # The sleep gets no copy of the locked descriptor: lock_release kills this
    # shell, and a sleep holding one kept the queue taken for up to a second
    # after, so the same run taking it again was told another one held it.
    while kill -0 "$$" 2>/dev/null; do sleep 1 9>&-; done
  ) </dev/null >/dev/null 2>&1 &
  __lock_pid=$!
  __lock_started="$(date +%s)"
  while [[ ! -e "$__lock_ready" ]]; do
    if ! kill -0 "$__lock_pid" 2>/dev/null; then
      rm -f "$__lock_ready.busy"
      warn "  could not take the queue at $__lock_file — $__lock_what runs without it"
      return 0
    fi
    if [[ -z "$__lock_told" && -e "$__lock_ready.busy" ]]; then
      __lock_told=1
      __lock_holder="$(cat "$__lock_file.holder" 2>/dev/null || true)"
      echo ""
      warn "  ${__lock_holder:-Another sclaude} is running $__lock_what now."
      info "  This one waits for it, so the two do not compete for the machine."
      info "  Ctrl-C to leave — nothing has started yet."
    fi
    sleep 0.2
  done
  rm -f "$__lock_ready" "$__lock_ready.busy"
  [[ -n "$__lock_told" ]] \
    && info "  …the queue is free after $(( $(date +%s) - __lock_started ))s; going on."
  printf '%s, since %s (pid %s)\n' "$__lock_who" "$(date +%H:%M)" "$$" > "$__lock_file.holder" 2>/dev/null || true
  printf -v "$__lock_var" '%s' "$__lock_pid"
}

# Gives the queue up. Idempotent: an empty pid is a queue not taken.
#
#   lock_release <pid> <file>
#
# The note goes first, while the lock is still held: removed after, it could
# remove the note of whoever took the queue in between.
lock_release() {
  local pid="$1" file="$2"
  [[ -n "$pid" ]] || return 0
  rm -f "$file.holder" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
