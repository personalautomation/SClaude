#!/usr/bin/env bash
#
# Moving a feature between steps by hand: replan, return, the friction review,
# the regression, the epilogue, reset, and the hooks a session ends through.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

cmd_replan() {
  require_repo
  local slug="${1:-}" wt state step answer
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF replan <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"
  step="$(state_get "$state" step)" || die "corrupted state: $state"

  echo ""
  if [[ "$step" == "plan" ]]; then
    # The step is already the first one — but that does not mean there is
    # nothing to do. The conversation going on there may have reached a dead end,
    # and "start the planning afresh" is exactly what people come here for.
    # Refusing was a mistake: it left the old session in the state, and the next
    # launch returned to the same dead end.
    echo "Feature '$slug' starts step 1 over, in a new conversation."
    info "  The plan in .sclaude/local/feature/plan.md stays as it is — the new session reads it."
  else
    echo "Feature '$slug' goes back from $(step_label "$step") to step 1, planning."
    info "  A new conversation starts — the approved plan is not reopened."
    info "  Anything already written stays in the worktree; step 1 will ask about it."
  fi
  ask "${BOLD}Go back to planning? [y/n] ${OFF}" answer yn
  is_yes "$answer" || { info "Left as it is."; return 0; }

  # A new conversation rather than a --resume. The previous one either ended in
  # approval — and continuing it means arguing with a decision already taken — or
  # got stuck, and then there is even less reason to return to it: a session gets
  # its hook settings at launch, so even a repaired orchestrator will not save
  # it.
  state_set "$state" steps.plan.session null
  # Every step, because planning afresh un-passes all of them. The same four
  # lines the regression's rewind and the QA hand-back want — see
  # step_rewind_to in steps.sh.
  step_rewind_to "$wt" plan "${STEPS[@]}"
  issue_sync "$wt"

  prepare_worktree "$wt"
  run_step "$wt" "$slug" plan
}

# Send a finished feature back to development: `sclaude return <name> [reason]`.
#
# For every reason a feature has to go back other than QA moving its card —
# which the watcher already turns into the same return. The work happens in
# return_to_development (watch.sh); this checks the feature is one that can be
# returned and hands over to cmd_resume, which acts on the `returned` verdict
# exactly as it does for the board, so there is one way back, not two.
#
# Only from `done`. A feature on an earlier step is still being developed, and
# what it needs is said where its session will read it — on the pull request or
# the issue — not a rewind.
cmd_return() {
  require_repo
  local slug="${1:-}" wt state step
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF return <name> [reason]"
  shift
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"
  step="$(state_get "$state" step)" || die "corrupted state: $state"

  if [[ "$step" != "done" ]]; then
    echo ""
    echo "Feature '$slug' is still in development: $(step_label "$step")."
    info "  There is nothing to return it from. Say what is wrong on the pull request"
    info "  or the issue, where its session reads it, and continue: $SELF $slug"
    return 0
  fi

  # Held on a red production (prod_red_hold names this way forward): the fix
  # goes back as production's red sends it, so the review session is handed
  # the failure (regression_fix_block), and the reason with it, rather than a
  # QA hand-back with none. Asked as remind_prod asks it, so the command and
  # the pass agree: a red left from an earlier release is not this one's, and
  # GitHub's silence stops both.
  if [[ "$(regression_status "$wt" prod)" == failed ]]; then
    local carries=0
    prod_carries_feature "$wt" || carries=$?
    if [[ "$carries" -eq 0 ]]; then
      state_set "$state" regression.prod.reason "${*:-null}"
      regression_rewind "$wt" "$slug" prod
      cycle_edge "$wt" hold_ways r_step4 person "$SELF return" stage=prod note="${*:-}"
      info "  Back on the review to fix production forward, in this same tree."
      cmd_resume "$slug"
      return
    fi
    # A hand-back from QA moves the card and cannot be taken back: not on a
    # guess.
    if [[ "$carries" -eq 2 ]]; then
      warn "GitHub could not say whether production carries '$slug'; nothing was"
      warn "returned. Try again once it can (gh auth status): $SELF return $slug${*:+ \"$*\"}"
      return 1
    fi
    info "  Production's last regression was red, but production does not carry this"
    info "  feature now: returned as a hand-back from QA."
  fi

  return_to_development "$wt" "$slug" "$@" || die "could not return '$slug': see $state"
  cmd_resume "$slug"
}

# The clean-up is the only irreversible command here, which is why it checks the
# fact of the merge with GitHub rather than trusting the state, and asks before
# every deletion.
# Reviewing the friction by hand: usually this happens by itself, after every
# step, but the log stays to hand — and going back to what was reviewed is
# sometimes needed too.
cmd_friction() {
  require_repo
  local slug="${1:-}" wt
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF friction <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"

  # An unclosed review — one that began and was interrupted — is resumed without
  # asking about either the log or what was reviewed: the log in that case is
  # empty by construction, and what has to be returned to is the conversation.
  # run_friction works that out; here it is enough not to turn it away with the
  # emptiness check.
  local state="$wt/.sclaude/local/feature/state.json"
  # Typed at a terminal, the person is here: [g] holds nothing it runs
  # (friction_hold). From the phone's menu, with no terminal, it may; and a
  # review it cannot hold waits for the terminal (run_friction).
  local FRICTION_NO_HOLD=""; [[ -t 0 && -t 1 ]] && FRICTION_NO_HOLD=1
  local fkey; fkey="$(friction_pending "$state" || true)"
  if [[ -n "$fkey" ]]; then
    run_friction "$wt" "$slug" "$fkey"
    return 0
  fi

  local log="$wt/.sclaude/local/feature/friction.log" reread=""
  if [[ ! -s "$log" ]]; then
    # What was reviewed lies next to it under .reviewed — bringing it back is
    # cheaper than explaining to the human that there is nothing left to look at.
    #
    # This must not be done with a copy: run_friction appends the log to
    # .reviewed, and the copy landed on top of the original — every round doubled
    # every entry. So we do not copy but say outright: what has to be read is
    # what was reviewed.
    if [[ -s "$log.reviewed" ]]; then
      info "Nothing new; re-reading the entries reviewed last time."
      reread=1
    else
      info "friction.log is empty — nothing to review."
      return 0
    fi
  fi
  local lkey; lkey="$(last_run_key "$state")"
  [[ -n "$lkey" ]] || lkey="$(state_get "$state" step || echo "?")"
  run_friction "$wt" "$slug" "$lkey" "$reread"
}

# Returning to an interrupted epilogue. As a separate command, because by this
# moment the feature is closed and cleared away: it is not in the menu, nor in
# the action list — there is nothing to show, and the tree does not exist. The
# only way back is to name it, and the warn in run_status names exactly this
# command.
# The regression on demand, outside a step's gate.
#
# It runs the stage and reports; it does not open fixing sessions and does not
# rewind steps. That is deliberate. From a gate a red run means "the step does
# not close, here is what to do about it", and the loop that follows is the
# answer. From a menu item somebody may have pressed to find out where things
# stand, the same loop would start sessions nobody asked for — so this answers
# the question and stops, and the gate does the gating when the step ends.
#
# The stage is always `local`: preview and production are asked about their own
# deployments, which do not exist to be re-tested on demand — remind_prod runs
# those right after it makes them.
cmd_regression() {
  require_repo
  local slug="${1:-}" stage="${2:-local}" wt
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF regression <name> [prod]"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"

  # Production's suite, by hand: the one way to tell a production held red
  # (prod_red_hold) that it is green again. Only checked — on red nothing is
  # rolled back, which is `rollback`'s to do and asks.
  if [[ "$stage" == "prod" ]]; then
    local state="$wt/.sclaude/local/feature/state.json" rc=0
    # Only of a production that carries the feature: one rolled back, or not
    # yet holding its fix, would answer green about another release, and
    # take the feature's red off with it.
    if ! prod_carries_feature "$wt"; then
      warn "Production does not carry '$slug' as far as can be told (not shipped from"
      warn "here, rolled back, its fix not shipped yet — or GitHub could not be asked):"
      warn "its suite would say nothing about the feature."
      return 1
    fi
    regression_run "$wt" "$slug" prod || rc=$?
    echo ""
    if [[ "$rc" -eq 0 ]]; then
      # Another release on top no longer matters once production is green; on
      # anything else it still does, and the hold goes on saying so.
      state_set "$state" regression.prod.intruded null 2>/dev/null || true
      state_set "$state" regression.prod.attempts 0 2>/dev/null || true
      regression_clear_mark "$wt" prod
      info "  Production is green. Carry on with: $SELF $slug"
      return 0
    fi
    if [[ "$rc" -eq 2 ]] && project_prod_suite_declined "$wt"; then
      # No suite for production by the project's word (`prodRegression: none`
      # or no list; project_prod_suite_declined): the person
      # chose to check nothing there, so the red held of an earlier run goes,
      # as remind_prod drops it after a ship.
      state_set "$state" regression.prod.status null 2>/dev/null || true
      state_set "$state" regression.prod.unrunnable null 2>/dev/null || true
      state_set "$state" regression.prod.intruded null 2>/dev/null || true
      state_set "$state" regression.prod.attempts 0 2>/dev/null || true
      regression_clear_mark "$wt" prod
      info "  Nothing holds production now. Carry on with: $SELF $slug"
      return 0
    fi
    if [[ "$rc" -eq 2 ]]; then
      info "  It could not run; nothing changed. Run it again once it can."
    else
      info "  Still red, and nothing was rolled back. To go back to the release"
      info "  before this feature, with the fix from the review: $SELF rollback $slug"
    fi
    return 1
  fi
  [[ "$stage" == "local" ]] || die "usage: $SELF regression <name> [prod]"

  prepare_worktree "$wt"
  if regression_run "$wt" "$slug" local; then
    info "  The step will not run it again unless something changes."
    return 0
  fi

  echo ""
  info "  Nothing was started to fix it: this was a run you asked for, not a gate."
  info "  Closing the step runs it again and fixes it then: $SELF $slug"
  return 1
}

cmd_epilogue() {
  require_repo
  local slug="${1:-}" file

  # Without a name, whatever is waiting. Usually nothing: an epilogue is rarely
  # interrupted, and an empty list is then an answer rather than an excuse.
  if [[ -z "$slug" ]]; then
    local rows; rows="$(pending_epilogues)"
    [[ -n "$rows" ]] || { info "No unfinished epilogues."; return 0; }
    echo ""
    echo "${BOLD}Unfinished epilogues${OFF}"
    while IFS=$'\t' read -r slug file; do
      [[ -n "$slug" ]] || continue
      info "  $slug — issue #$(state_get "$file" issue || echo "?"), started $(state_get "$file" started || echo "?")"
    done <<< "$rows"
    echo ""
    info "Resume one with: $SELF epilogue <name>"
    return 0
  fi

  file="$(epilogue_dir)/$slug.json"
  [[ -f "$file" ]] || die "no epilogue recorded for: $slug"
  # As in pending_epilogues: a closed epilogue leaves no file behind, so nobody
  # will come here with one. The check is insurance against a record from the
  # previous arrangement.
  [[ "$(state_get "$file" done || echo false)" != "true" ]] \
    || { info "The epilogue for '$slug' is already finished."; return 0; }

  local issue; issue="$(state_get "$file" issue || true)"
  [[ -n "$issue" && "$issue" != "null" ]] || die "the epilogue state carries no issue"

  # We take the deployment's outcome from the state: the interrupted attempt,
  # which knew the situation, wrote it. It cannot be assembled here by hand —
  # there is no tree, and remind_prod passed these values as arguments.
  #
  # This used to say "MERGED 1 1" — a guess, and a wrong one: an epilogue is
  # created on an unmerged branch too (deploy.sh, the "there is no merge yet"
  # branch). Resuming such a one, sclaude would write into the issue and its
  # parents that the feature was merged and in prod — as a trustworthy outcome,
  # over the top of the truth.
  local pr merged preview prod
  pr="$(state_get "$file" pr || true)";          [[ "$pr" == "null" ]] && pr=""
  merged="$(state_get "$file" merged || true)";  [[ "$merged" == "null" ]] && merged=""
  preview="$(state_get "$file" preview || echo 0)"
  prod="$(state_get "$file" prod || echo 0)"
  # Whether it was about a red preview: without it the resumed session would
  # be told nothing was deployed.
  local preview_red; preview_red="$(state_get "$file" preview_red || echo 0)"
  [[ "$preview_red" == 1 ]] || preview_red=0

  # The tree when it is still there: a green epilogue finished here clears
  # the red words' flag in its state, or every green pass would write again.
  local wt; wt="$(feature_worktree "$slug" 2>/dev/null)" || wt=""
  run_status "$slug" "$issue" "$pr" "$merged" "$preview" "$prod" "$wt" "$preview_red"
}

# Erasing a step's traces and starting it afresh — a "safe boot" for a feature
# that will not start.
#
# Returning to a session is the ordinary path, and almost always the right one:
# context is worth more than a clean slate. But sometimes there is nowhere or
# nothing to return to: the transcript is damaged, the session hangs open in
# somebody else's process, the step hits a limit right at the entrance and does
# not survive to a conversation. The state then holds an id that cannot be opened
# and cannot be forgotten — and the feature stands still.
#
# All three cases were already caught separately: efeb328 learned to forget an id
# with no transcript, session_holder to recognise an open session. There was no
# common way out, and only one remained — editing state.json by hand.
#
# We erase precisely the launch's trace: the session's id, the start time, the
# background-launch flag. We touch nothing of what the step did in the world —
# the commits, the branch, the PR, the plan and the friction log stay in place.
# This is a restart of the conversation rather than a rollback of the work; for a
# rollback there is replan, and for abandoning, drop.
cmd_reset() {
  require_repo
  local slug="${1:-}" wt state step answer
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF reset <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"
  step="$(state_get "$state" step)" || die "corrupted state: $state"

  # An unclosed friction review comes first and as a separate question rather
  # than together with the step. There are two reasons.
  #
  # It holds the step: while the review is not closed, cmd_resume leads into it
  # rather than into the step — so "the feature is not moving" most often means
  # exactly this, and it is exactly this that has to be cleared. One question for
  # both would additionally offer a restart of the step that nobody asked for.
  #
  # And their scope differs. Here a step has its launch trace erased while its
  # conversation stays on disk; a review, on the other hand, has nothing to close
  # but a flag — the entries have long been in .reviewed, and nobody will offer
  # them a second time. That has to be asked outright: "close it unreviewed"
  # rather than "start afresh".
  local fsession fkey
  fkey="$(friction_pending "$state" || true)"
  fsession=""
  [[ -n "$fkey" ]] && fsession="$(state_get "$state" "friction.$fkey.session" || true)"
  if [[ -n "$fsession" && "$fsession" != "null" ]]; then
    echo ""
    echo "Feature '$slug' has an unfinished friction review, and it holds the step."
    local fwhere; fwhere="$(state_get "$state" "friction.$fkey.cwd" || true)"
    if live_session "${fwhere:-$INSTRUMENTS}" "$fsession" >/dev/null; then
      info "  Its conversation stays on disk — it is only forgotten here."
      info "  Read it any time: claude --resume $fsession"
    else
      info "  Its conversation left no transcript — there is nothing to lose."
    fi
    info "  The entries stay in .sclaude/local/feature/friction.log.reviewed, marked as reviewed;"
    info "  re-read them any time with: $SELF friction $slug"
    ask "${BOLD}Close the friction review and move on? [y/n] ${OFF}" answer yn
    if is_yes "$answer"; then
      state_set "$state" "friction.$fkey.done" true
      # Keep the id under `was`, as run_friction does when it closes one
      # normally: the conversation stays on disk, and the issue's Friction
      # column names it so there is something to resume.
      state_set "$state" "friction.$fkey.was" "$fsession"
      # And say that nobody read it. This closes a review by hand, leaving the
      # entries in .reviewed unexamined — an outcome worth telling apart from a
      # review that ran, which is what the column would otherwise show.
      state_set "$state" "friction.$fkey.unread" true
      state_set "$state" "friction.$fkey.session" null
      info "  The friction review is closed."
    else
      info "  Left as it is — the feature stays on it."
      return 0
    fi
  fi

  [[ "$step" != "done" ]] || { info "Feature '$slug' has been through every step."; return 0; }

  local session; session="$(state_get "$state" "steps.$step.session" || true)"

  echo ""
  echo "Feature '$slug' starts step $(step_label "$step") over, in a new conversation."
  if [[ -n "$session" && "$session" != "null" ]]; then
    if live_session "$wt" "$session" >/dev/null; then
      info "  The recorded conversation stays on disk — it is only forgotten here."
      info "  Read it any time: claude --resume $session"
    else
      info "  The recorded conversation left no transcript — there is nothing to lose."
    fi
  fi
  info "  Commits, branch, PR, the plan and the friction log all stay as they are."
  ask "${BOLD}Start this step over? [y/n] ${OFF}" answer yn
  is_yes "$answer" || { info "Left as it is."; return 0; }

  state_set "$state" "steps.$step.session" null
  state_set "$state" "steps.$step.started" null
  state_set "$state" "steps.$step.bg" null
  state_set "$state" "steps.$step.gate" null

  # And the regression's exhausted attempts. Without this a stage that used up
  # both fixing sessions stays wedged: every later entry runs the whole suite
  # again, minutes of it, only to refuse at the limit — and "start this step
  # over" is exactly where a human says the attempts should start over too.
  local rs
  for rs in local preview prod; do
    state_set "$state" "regression.$rs.attempts" 0
    # A new round, so its first red is rerun once before a session (the gate).
    state_set "$state" "regression.$rs.orchestrator_fixes" 0
  done

  prepare_worktree "$wt"
  run_step "$wt" "$slug" "$step"
}

# The end of a step's session, run by a sclaude that has just replaced one whose
# code went stale while the session ran. See code_reload.
cmd_session_ended() {
  require_repo
  local slug="${1:-}" step="${2:-}" session="${3:-}" wt
  # code_reload execs into this from inside a step: the binding of the process
  # it replaced is gone, and the step's last questions are still the feature's.
  local ASK_SLUG="$slug"
  [[ -n "$slug" && -n "$step" && -n "$session" ]] || die "usage: $SELF _session-ended <name> <step> <session>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"
  session_ended "$wt" "$slug" "$step" "$session"
}

# The hand-off of a pull request QA has accepted, for the timer: it sees Done
# while nobody has sclaude open, and the hand-off should not wait for somebody
# to come back. The same pr_qa_handoff the wait for QA runs, so the two cannot
# drift apart, and its exit code is passed through unchanged (see there). A
# feature that no longer exists is 2: nothing left to hand over, ever.
cmd_handoff() {
  require_repo
  local slug="${1:-}" wt state pr issue
  [[ -n "$slug" ]] || die "usage: $SELF _handoff <name>"
  wt="$(feature_worktree "$slug")" || { echo "no such feature: $slug" >&2; return 2; }
  state="$wt/.sclaude/local/feature/state.json"
  pr="$(state_get "$state" pr || true)"
  issue="$(state_get "$state" issue || true)"
  pr_qa_handoff "$wt" "$pr" "$issue"
}
