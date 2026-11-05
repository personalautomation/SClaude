#!/usr/bin/env bash
#
# Commands on a feature in work: syncing it with main, the news on its pull
# request, its preview, a rollback, and its dev server.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Checking a branch against main. The only place where a feature learns that the
# world has moved on: until now a branch equalled origin/main exactly once — at
# the moment it was created — and diverged silently after that. A feature that
# has lain for a week plans and writes code against an outdated foundation, and
# that is discovered at the merge.
#
# We count both sides rather than one: "12 behind" without "3 of its own" does
# not say what it threatens. We merge rather than rebase: the branch is already
# in origin, it may have an open PR, and rewriting its history means breaking
# what the review is looking at. A merge leaves a commit but does not touch what
# has already been published.
cmd_sync() {
  require_repo
  local slug="${1:-}" wt branch behind ahead answer pr
  # Typed at a terminal, the person is here: [g] holds nothing it runs
  # (friction_hold). From the phone's menu, with no terminal, it may.
  local FRICTION_NO_HOLD=""; [[ -t 0 && -t 1 ]] && FRICTION_NO_HOLD=1
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF sync <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"
  branch="$(state_get "$wt/.sclaude/local/feature/state.json" branch)" || die "the state carries no branch"
  # sync_gate takes back a hand-off for the merge when the sync pushes code
  # nobody has checked, from here as from the run.
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr 2>/dev/null || true)"

  echo ""
  info "Fetching origin…"
  git -C "$REPO" fetch origin -q 2>/dev/null || warn "  could not reach origin — using what we have"

  behind="$(git -C "$REPO" rev-list --count "$branch..origin/main" 2>/dev/null)" || behind="?"
  ahead="$(git -C "$REPO" rev-list --count "origin/main..$branch" 2>/dev/null)" || ahead="?"

  echo ""
  say "${BOLD}$slug${OFF} — $ahead commit(s) of its own, $behind behind origin/main."

  # A sync broken off — a session the person left, perhaps mid-merge — goes
  # back to that session, which sync_with_main tells them this command does:
  # the uncommitted work refused below would be its own half-done merge.
  #
  # Its conflict may have gone meanwhile — resolved by hand or on GitHub, or
  # main moved — and then sync_with_main closes it and says nothing more: the
  # sync goes on below as an ordinary one. A merge still under way here is
  # never that: sync_with_main has the session finish it.
  #
  # A merge under way that no sync left — the person's own, by hand — is
  # theirs: a session takes it over only on a yes, as any paid one starts.
  local under_way=""
  merge_under_way "$wt" && under_way=1
  if [[ -n "$under_way" ]] && ! sync_broken_off "$wt/.sclaude/local/feature/state.json"; then
    echo ""
    warn "  A merge is under way in $wt."
    ask "${BOLD}Have a session finish it — resolve, check, push? [y/n] ${OFF}" answer yn
    is_yes "$answer" || {
      info "  Left as it is. Finish it: git -C $wt commit, or back out: git -C $wt merge --abort"
      return 0
    }
  fi
  if [[ -n "$under_way" ]] || sync_broken_off "$wt/.sclaude/local/feature/state.json"; then
    local resumed=0
    sync_gate "$wt" "$slug" "$pr" nofetch || resumed=$?
    # 5, a hand-off taken back over commits from elsewhere (said there), is
    # no merge: the sync below still runs.
    [[ "$resumed" -eq 5 ]] && resumed=0
    [[ "$resumed" -eq 3 ]] && echo "${GREEN}Merged — $branch now carries everything from main.${OFF}"
    [[ "$resumed" -eq 0 ]] || return 0
    behind="$(git -C "$REPO" rev-list --count "$branch..origin/main" 2>/dev/null)" || behind="?"
  fi

  if [[ "$behind" == "0" ]]; then
    info "  Nothing to do: the branch already has everything from main."
    return 0
  fi

  # A "?" instead of a number means rev-list did not work: there is no
  # origin/main, or the branch did not resolve. Asking "merge it in?" after that
  # is the same as asking over uncommitted work below: offering what is known to
  # be impossible is lying. The only difference is that there it is the human's
  # work in the way, while here we have nothing to compare.
  if [[ "$behind" == "?" ]]; then
    warn ""
    warn "  Could not compare $branch with origin/main."
    info "  Is there an origin/main to merge from? Try: git -C $REPO fetch origin"
    return 0
  fi

  # Uncommitted work must not be merged into: merge would stop halfway and leave
  # the tree in a state that would have to be untangled by hand. We check before
  # the question — offering what is known not to work out is lying.
  local dirty; dirty="$(worktree_dirt "$wt")"
  if [[ -n "$dirty" ]]; then
    warn ""
    warn "  Uncommitted work in the worktree — commit or stash it first:"
    printf '%s\n' "$dirty"
    return 0
  fi

  # A branch updated on GitHub is merged from there: the check below is about
  # origin's tip, and the merge must start from the same commit.
  sync_catch_up "$wt"
  if sync_diverged "$wt"; then
    warn ""
    warn "  $branch here and on origin have both moved — bring them together first:"
    warn "    git -C $wt pull --no-rebase"
    return 0
  fi

  # A merge that would stop on conflicts is not left half-done for the person
  # to untangle — from a phone they cannot: the sync with main (sync.sh)
  # resolves them, by itself for the deferred logs and in a session otherwise.
  # Not asked, even when a session resolves the conflicts: the branch has to
  # merge with main before its preview and its merge whatever is answered, so
  # a "no" would only put the same session off (sync_offer).
  local synced=0 merged=0
  echo ""
  sync_offer "$wt" "$slug" "$pr" || synced=$?
  case "$synced" in
    0|2|5) ;;
    3) echo "${GREEN}Merged — $branch now carries everything from main.${OFF}"; return 0 ;;
    *) return 0 ;;
  esac
  sync_plain_merge "$wt" "$branch" "$slug" || merged=$?
  if [[ "$merged" -eq 2 ]]; then
    warn "  The merge stopped, and backing it out failed — finish it or: git -C $wt merge --abort"
  fi
}

# What has changed on the PR since the step last saw it.
#
# review_news (review_round.sh) assembles this — the same gathering that goes as a prompt
# into a resumed step 4. Until now there was no other way to see it: without
# opening the step, a human did not know whether there was anything new there at
# all.
cmd_news() {
  require_repo
  local slug="${1:-}" wt pr news
  [[ -n "$slug" ]] || die "name the feature: $SELF news <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr || true)"
  [[ -n "$pr" && "$pr" != "null" ]] || { info "Feature '$slug' has no pull request yet."; return 0; }

  # review_news shows what is new relative to step 4's last session, and it
  # returns nothing for four different reasons. One of them has to be separated
  # out: there may be no review session at all — step 3 has just closed and step
  # 4 has not begun. "There is nothing new" is then untrue in exactly the
  # opposite way: everything there is new, there is simply nothing to count it
  # from.
  local session
  session="$(state_get "$wt/.sclaude/local/feature/state.json" steps.review.session || true)"
  echo ""
  if [[ -z "$session" || "$session" == "null" ]]; then
    info "PR #$pr has not been reviewed yet — step 4 hasn't run."
    info "  Everything on it is new. Open it with: $SELF $slug"
    return 0
  fi

  news="$(review_news "$wt" review)"
  if [[ -z "$news" ]]; then
    info "PR #$pr: nothing new since the last review session."
    return 0
  fi
  echo "${BOLD}PR #$pr — what has happened since the last review session:${OFF}"
  echo ""
  printf '%s\n' "$news"
}

# A preview deploy on demand.
#
# With the same block as in the cycle's epilogue: the command is one and the
# same, and there is no reason for them to diverge. Preview used to be offered
# exactly once — at the end — and a refusal meant there would be no second offer
# until the epilogue was gone through again.
#
# From the main repository with a path to the worktree: the project's link lies
# in its .vercel/, and the feature's tree has none — a vercel launched from there
# would create a new project instead of deploying to this one.
cmd_preview() {
  require_repo
  local slug="${1:-}" wt
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF preview <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"

  # The record, the same one remind_prod keeps. Without it a preview sent from
  # here leaves no trace, deploy_unchanged has nothing to compare against, and
  # the cycle offers the same unchanged tree again as though it had never gone.
  # It matters more now that the section reports the deployed commit: a deploy
  # nobody wrote down is a commit the issue cannot name.
  #
  # The migrations first, as in the cycle: a preview recorded here is one the
  # cycle later skips as unchanged, so a deploy without them would stay without
  # them.
  preview_apply_migrations "$wt" || true
  # The topic hears of it as of the cycle's (preview_ship): the deploy's own
  # lines stay in the terminal.
  ask_feed say "$(phase_line started deploy preview)"
  if preview_deploy "$wt"; then
    deploy_remember "$wt" preview
    ask_feed say "$(phase_line finished deploy preview)"
  else
    ask_feed alarm "$(phase_line failed deploy preview) · the log is in the terminal"
  fi
}

# Puts production back to the release before this feature, by hand.
#
# The same code the red-prod path runs automatically, minus the `--auto`: there
# the decision has been taken by a suite, here it is taken by a person, and a
# person gets asked. The default is yes — by the time somebody has typed this,
# they know what they want, and a default of no would make the common case take
# two keystrokes.
#
# A cleaned-up feature cannot be rolled back this way: feature_worktree dies,
# and the record of what it shipped died with the tree. The message says what to
# do instead rather than leaving somebody at a dead end.
cmd_rollback() {
  require_repo
  local slug="${1:-}" wt
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF rollback <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug
  A feature that has been cleaned up keeps no record of what it shipped.
  By hand: vercel ls --environment production, then vercel rollback <url>"

  # The same gate the action list applies: nothing is offered until the feature
  # has actually reached production. The menu had it and the typed command did
  # not, and the gap was reachable — `rollback_remember_previous` runs before
  # the prod block and regardless of whether the human accepts it, so
  # `rollback.prod.url` can name a deployment for a ship that never happened.
  # `deploy.prod.sha` is written only by a deploy that succeeded, so it is the
  # honest question.
  local shipped; shipped="$(state_get "$wt/.sclaude/local/feature/state.json" deploy.prod.sha 2>/dev/null || true)"
  if [[ -z "$shipped" || "$shipped" == "null" ]]; then
    warn "Feature '$slug' has not been shipped to production from here."
    info "  There is nothing to roll back: production is serving whatever it"
    info "  was serving before this feature existed."
    info "  What is on hosting now: vercel ls --environment production"
    return 1
  fi

  rollback_prod "$wt" "$slug" || return 1
  rollback_confirm "$wt" "$slug" || true
  rollback_incident "$wt" "$slug" \
    "$(state_get "$wt/.sclaude/local/feature/state.json" issue 2>/dev/null || true)"
  # Production no longer carries the feature, so the fix goes on from the
  # review, as after the automatic rollback. Left on `done`, the next pass
  # asked to ship the same main again, and a "no" led to the clean-up of the
  # tree the fix was to be made in. Only from `done`: a feature already back
  # in development — its fix's pull request perhaps open — keeps its round,
  # and a second rewind would take that pull request for the rolled back one.
  # And only for a red: a rollback made with production green is the
  # person's own reason, and the review would be handed a failure no suite
  # found.
  local step; step="$(state_get "$wt/.sclaude/local/feature/state.json" step 2>/dev/null || true)"
  if [[ "$step" == "done" && "$(regression_status "$wt" prod)" != failed ]]; then
    info "  Production's suite was not red, so the feature is not sent back. To fix"
    info "  something from the review: $SELF return $slug"
  elif [[ "$step" == "done" ]]; then
    regression_rewind "$wt" "$slug" prod
    info "  The fix goes on from the review step, in this same tree: $SELF $slug"
  else
    info "  The feature is in development ($(step_label "$step")); it goes on from there: $SELF $slug"
  fi
}

# The server usually starts by itself before a step; this command is for the
# cases where it is needed without a session or simply has to be switched off.
cmd_dev() {
  require_repo
  # --no-browser is for sclaude-proxy, which starts a server because a browser
  # is already asking for it — and may be a phone's, where a window opening on
  # the laptop helps nobody.
  local browser=1 a
  local -a args=()
  for a in "$@"; do
    [[ "$a" == "--no-browser" ]] && { browser=0; continue; }
    args+=("$a")
  done
  set -- "${args[@]}"
  local arg="${1:-}" pid cwd wt

  # `stop` takes the feature as its second word; without one, the tree it was
  # called from. Every feature has a server of its own now, so "the" server no
  # longer names anything.
  if [[ "$arg" == "--stop" || "$arg" == "stop" ]]; then
    local port
    if [[ -n "${2:-}" ]]; then
      wt="$(feature_worktree "$(slugify "$2")")" || die "no such feature: $2"
    else
      wt="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not a git repository"
    fi
    port="$DEV_PORT_PINNED"
    [[ -n "$port" ]] || port="$(state_get "$wt/.sclaude/local/feature/state.json" dev.port 2>/dev/null || true)"
    pid="$(dev_pid "$port")"
    if [[ -n "$pid" ]]; then
      cwd="$(dev_cwd "$pid")"
      # Before anything is stopped: refusing after the database had gone down
      # would say nothing was stopped while this feature's database was.
      [[ "$cwd" == "$wt" ]] || die "port $port is held by ${cwd:-an unknown directory}, not by $wt — leaving it"
    fi
    # The database goes to sleep with the server: it holds memory and is of no
    # use without it, and the next start brings both back. Also when the server
    # is already down — a database left running on its own is the same waste.
    declare -F db_stop >/dev/null && db_stop "$wt"
    [[ -z "$pid" ]] && { echo "The dev server of $(basename "$wt") is not running."; return 0; }
    echo "Stopping the server from $wt…"
    stop_dev_pid "$pid" "$port"
    echo "${GREEN}stopped${OFF}"
    return 0
  fi

  if [[ -n "$arg" ]]; then
    wt="$(feature_worktree "$(slugify "$arg")")" || die "no such feature: $arg"
  else
    # Without a name, the server for the worktree it was called from.
    wt="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not a git repository"
  fi
  mkdir -p "$wt/.sclaude/local/feature"
  ensure_dev "$wt"
  [[ "$browser" -eq 1 ]] && ensure_chrome "$wt"
  return 0
}
