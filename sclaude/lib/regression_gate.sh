#!/usr/bin/env bash
#
# The regression gate: a step closes only on a green run of the suite on the
# tree it leaves, and a red one goes back to a session.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The gate: run the stage, and if it is red, fix it and run it again.
#
# The shape is run_friction's, deliberately: a caller writes
#
#   if ! regression_gate "$wt" "$slug" local; then … return 0; fi
#
# and the step stays where it is. A gate that returned "true, but" would be a
# gate in name only.
#
# But a red run is not the end of the road. Stopping there would leave the
# human with a broken feature and a log, which is the situation the gate exists
# to prevent — so a failure opens a fixing session, and when that session ends
# the same stage runs again. Green means the cycle carries on by itself; red
# means one more attempt, and then the feature is handed back.
#
# A stage already green is not run again. The state is per stage and is reset by
# the run itself, so this is not a cache to go stale: `code` closing means the
# tree was green at that moment, and the next thing that can invalidate it is a
# commit, which starts the step over anyway.
# Take the stage's red mark off the issue chain, now that it is green.
#
# Here rather than in the epilogue, and that is the point of it: the epilogue
# runs once at the end of the cycle, while a stage can go red and green again
# several times before then — and between those two moments the mark is the only
# thing telling a reader of the epic that the deployment is broken. Left until
# the end it would be a mark nobody could trust, because it would lag the truth
# by however long the fix took.
#
# Unconditional rather than guarded by "was it red before". The state that would
# answer that is the same state a fixing session may have rewritten, and asking
# costs a request we are already making; removing a label that is not there is a
# no-op on GitHub's side and silent on ours.
#
# Quiet on everything unknown — no issue, no gh, no chain. A green regression is
# not worth failing over a label, and the caller has already recorded the pass.
regression_clear_mark() {
  local wt="$1" stage="$2" issue repo numbers

  [[ "$stage" == "preview" || "$stage" == "prod" ]] || return 0
  issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue 2>/dev/null || true)"
  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  # The same walk run_status makes, for the same reason: the mark went on to the
  # whole chain, so it has to come off the whole chain. A walk that fails leaves
  # us the issue itself, which is better than leaving the mark everywhere.
  numbers="$(python3 "$LIB/issue_chain.py" --numbers "$issue" "$REPO" 2>/dev/null)" \
    || numbers=""
  [[ -n "$numbers" ]] || numbers="$issue"

  clear_regression_label "$repo" "$stage" "$numbers"
}

# Takes a blocked note off, keeping it in regression.notes beside it.
#
# A note says what failed, why, and what would have to change and who could
# change it. Deleted when the stage went green on a rerun, or when the person
# answered its question, the last part went with it: a flaky test's fix,
# named as belonging to a change of its own, reached no issue, no deferred
# entry and no report. The notes file lives in the feature's folder, where the
# retrospective reads it before the clean-up removes the tree.
#
#   blocked_note_keep <wt> <stage> <why>
blocked_note_keep() {
  local note="$1/.sclaude/local/feature/regression.blocked"
  [[ -s "$note" ]] || { rm -f "$note"; return 0; }
  { printf '=== %s · %s · %s\n' "$(date -Iseconds)" "$2" "$3"
    cat "$note"; printf '\n'; } >> "$1/.sclaude/local/feature/regression.notes" 2>/dev/null
  rm -f "$note"
}

regression_gate() {
  local wt="$1" slug="$2" stage="$3"
  local state="$wt/.sclaude/local/feature/state.json"
  local attempts
  REGRESSION_TAKEN_OVER=""

  # A local verdict is about a tree, and it stays true exactly as long as the
  # tree does. After a review that left no comments nothing in the tree has
  # moved since step 2 ran the suite, and running it again would spend minutes
  # to learn what is already known. Any change — a commit, an edit not yet
  # committed, a verdict recorded before trees were — and it runs.
  #
  # Only local: a deployed verdict is about a deployment, which remind_prod
  # compares on its own terms (deploy_unchanged).
  local only=""
  # Judged against main as it is now, when the branch can be moved there
  # without a question (sync_unpublished).
  [[ "$stage" == "local" ]] && declare -F sync_unpublished >/dev/null && sync_unpublished "$wt"
  if [[ "$stage" == "local" && "$(regression_status "$wt" local)" == "passed" ]]; then
    local was now
    was="$(state_get "$state" regression.local.tree 2>/dev/null || true)"
    now="$(regression_tree "$wt")"
    if [[ -n "$now" && "$was" == "$now" ]]; then
      echo ""
      info "  Local regression already green on this exact tree (${now:0:8}) — not run again."
      return 0
    fi
    # Only the manuals moved since the green run: the checks that read the
    # code, not the whole suite. For the first run only — once a fixing session
    # has touched the tree, the diff is no longer just the manuals.
    only="$(regression_manual_parts "$wt" "$was" "$now" || true)"
    state_set "$state" regression.local.status null
  fi

  # Already green: nothing ran now and nothing was fixed now, so nothing is
  # rewound. A rewind belongs to the green run that followed a fix, and that
  # run did it at the time.
  # A preview verdict is about the tree that was deployed and run, and the
  # tree moves: a production rollback sends the fix round again, and a green
  # recorded before it would let the new tree past without its suite. So a
  # recorded tree that is not this one — or none, or a dirty one — is no
  # verdict at all, the same rule the local stage keeps above.
  if [[ "$stage" == "preview" && "$(regression_status "$wt" preview)" == "passed" ]]; then
    local ran_on; ran_on="$(state_get "$state" regression.preview.tree 2>/dev/null || true)"
    local tree_now; tree_now="$(regression_tree "$wt")"
    if [[ -z "$tree_now" || "$ran_on" != "$tree_now" ]]; then
      state_set "$state" regression.preview.status null
    fi
  fi

  if [[ "$(regression_status "$wt" "$stage")" == "passed" ]]; then
    return 0
  fi

  # A note from the previous pass is a question to the human that nothing used
  # to ask. The session that wrote it found the cause outside this worktree and
  # named what had to change and who could change it — and then the next
  # `sclaude` ran the same suite for four minutes, failed the same way, and
  # opened a session to reach the same conclusion. The note was a message with
  # no delivery.
  #
  # So it is read back here, before anything is spent. If the cause has been
  # addressed the note goes and the run proceeds; if it has not, there is
  # nothing to learn from running, and saying so costs a second rather than
  # minutes.
  local note="$wt/.sclaude/local/feature/regression.blocked"
  # A rerun before any fixing session, once a gate (below). A yes here is one.
  local reran=0 rerun_part="" ran_only=""
  if [[ -s "$note" ]]; then
    echo ""
    warn "  The last $stage run was blocked by a cause outside this branch:"
    while IFS= read -r line; do
      info "  $line"
    done < "$note"
    echo ""
    # Not "has it been dealt with": the commonest note is a flaky test, with
    # nothing to deal with, and a yes to that question was a yes to a rerun.
    local fixed=""
    ask "${BOLD}  Run the $stage regression again? [y/n] ${OFF}" fixed yn || true
    if is_yes "$fixed"; then
      blocked_note_keep "$wt" "$stage" "run again at the person's word"
      reran=1
      info "  Running $stage again; the note is kept in .sclaude/local/feature/regression.notes."
    else
      info "  Leaving it: the run would fail the same way."
      info "  The note is .sclaude/local/feature/regression.blocked; carry on with: $SELF $slug"
      return 1
    fi
  fi

  local rc fixed_here=0 blocked_reruns=0
  if [[ -n "$only" ]]; then
    echo ""
    info "  Only the manuals changed since the last green run — running $only."
  fi
  while :; do
    # A preview run is about the deployment, so the deployment must be the
    # tree. A fixing session commits to the branch and the loop comes round
    # here while the preview still serves the commit before the fix: the rerun
    # would check code that is gone, stay red on a fix that works, or go green
    # on a loosened test with the fix never deployed, and record that verdict
    # against a tree nobody deployed. So a moved tree is deployed first.
    #
    # Unknown counts as moved (deploy_unchanged is false on no record), and a
    # redeploy that fails is the stage's red below: a run against the old
    # address answers a question nobody asked.
    if [[ "$stage" == "preview" ]] && ! deploy_unchanged "$wt" preview; then
      echo ""
      info "  The branch moved since its preview was deployed — deploying it again."
      preview_apply_migrations "$wt" || true
    fi
    # A deploy that fails is the stage's red, fixed the way a red run is:
    # its session told which command failed (preview_ship records it), the
    # attempts counted, the deploy tried again on the fix.
    if [[ "$stage" == "preview" ]] && ! deploy_unchanged "$wt" preview && ! preview_ship "$wt"; then
      rc=1
      only=""
      state_set "$state" "regression.$stage.failed_at" "the deploy"
      state_set "$state" "regression.$stage.status" failed
    else
      ran_only="$only"
      regression_run "$wt" "$slug" "$stage" "$only"
      rc=$?
      only=""
    fi

    if [[ "$rc" -eq 0 ]]; then
      # Green, and if a session preceded this run it is the one that did it.
      # `fix_status_set` rewrites the last word, which is that session; a stage
      # that went green with no fixing session at all has an empty string and
      # gets nothing.
      #
      # Except a session that ended `blocked`: it changed nothing, so the green
      # run after it (the rerun of a flake, or a cause dealt with outside) is
      # not its doing, and its row keeps saying what it found.
      local last_fix
      last_fix="$(state_get "$state" "regression.$stage.fix_status" 2>/dev/null || true)"
      [[ -n "$last_fix" && "${last_fix##* }" != "blocked" ]] \
        && fix_status_set "$state" "$stage" green
      if [[ -s "$wt/.sclaude/local/feature/regression.blocked" ]]; then
        info "  The note the fixing session left is kept in .sclaude/local/feature/regression.notes:"
        info "  whatever it says would have to change is not done by a green run."
      fi
      blocked_note_keep "$wt" "$stage" "green on a rerun"
      # The flake stays on record: green by itself is not "nothing happened".
      [[ -n "$rerun_part" ]] && printf '=== %s · %s · green on a rerun, no fixing session\nRed at first on: %s\n\n' \
        "$(date -Iseconds)" "$stage" "$rerun_part" >> "$wt/.sclaude/local/feature/regression.notes" 2>/dev/null
      state_set "$state" "regression.$stage.attempts" 0
      regression_clear_mark "$wt" "$stage"
      state_set "$state" "regression.$stage.orchestrator_fixes" 0
      # A later red is a new problem, even on the same part: it gets a fresh
      # session rather than the one whose fix has just gone green.
      state_set "$state" "regression.$stage.fix_session" null
      state_set "$state" "regression.$stage.fix_for" null
      # The cycle goes back to the step the fix belongs to only when there was
      # a fix. It used to go back on every green run, so a preview that simply
      # passed put a finished feature back on step 4, marked as reopened.
      [[ "$fixed_here" -eq 1 ]] && regression_rewind "$wt" "$slug" "$stage"
      return 0
    fi

    # 2 means the stage could not run at all. There is nothing for a session to
    # fix, so we stop without spending one and without counting it against the
    # two attempts a real failure gets.
    #
    # But "could not run" has two shapes and they must not share an answer. A
    # deployed stage with no address is a deploy that did not happen, and the
    # step is right to wait. A project that declares no regression for this
    # stage has none to wait for — holding the cycle there would mean a
    # repository without a suite could never close a step at all, which is the
    # opposite of what making the config optional was for.
    if [[ "$rc" -eq 2 ]]; then
      [[ -z "$(regression_parts "$stage" "$wt" 2>/dev/null || true)" ]] && return 0
      return 1
    fi

    # The count lives in the state rather than in a variable here: a session
    # closed halfway through would otherwise reset it, and a limit that resets
    # is not a limit. It is cleared by a green run above.
    attempts="$(state_get "$state" "regression.$stage.attempts" 2>/dev/null || echo 0)"
    [[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0

    # The first red no session has looked at yet is run again once, without
    # asking. The commonest red is a test that flaked on a loaded machine, and
    # a fixing session is the dearest way to learn it: one spent half an hour
    # to conclude the cause was outside, and the rerun after it went green. A
    # deploy that failed is not rerun here: preview_ship has tried it already.
    # "No session yet" is read from the state as well: a session whose friction
    # review fixed sclaude gives its attempt back, and on the preview restarts
    # sclaude, which would take its red for a first one. The rerun repeats the
    # red run, a manuals-only one included, not the whole stage.
    local red_at ofixes
    red_at="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
    ofixes="$(state_get "$state" "regression.$stage.orchestrator_fixes" 2>/dev/null || echo 0)"
    [[ "$ofixes" =~ ^[0-9]+$ ]] || ofixes=0
    if [[ "$reran" -lt 1 && "$attempts" -eq 0 && "$ofixes" -eq 0 && "$red_at" != "the deploy" ]]; then
      reran=1
      only="$ran_only"
      [[ -n "$red_at" && "$red_at" != "null" ]] && rerun_part="$red_at" || rerun_part="a part"
      info "  Running $stage again once before opening a fixing session: a flaky failure goes green on its own."
      continue
    fi
    rerun_part=""

    if [[ "$attempts" -ge "$REGRESSION_MAX_ATTEMPTS" ]]; then
      echo ""
      warn "  The $stage regression is still red after $attempts fixing session(s)."
      info "  A test that does not come right in two goes usually means the wrong"
      info "  thing is being fixed — which is why the limit stops here rather than"
      info "  spending a third session on the same guess."
      local failed_part
      failed_part="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
      [[ -n "$failed_part" && "$failed_part" != "null" ]] || failed_part="a part"
      if [[ "$failed_part" == "the deploy" ]]; then
        info "  Failed on: the deploy. Its output was in the terminal above."
      else
        info "  Failed on: $failed_part. The log is .sclaude/local/feature/regression.log"
      fi
      notify_feature "$slug" "Regression still red on $stage
$attempts fixing session(s) did not help — it needs you.
Log: .sclaude/local/feature/regression.log" 2>/dev/null || true

      # The limit stops the machine, not the human. Stopping silently would hand
      # back a feature with no way forward but `sclaude reset`, and the person
      # who has just read the log is exactly the one who knows whether a third
      # session is worth it — they may have fixed the cause by hand, or changed
      # the environment under it, which is the common case on a deployed stage.
      #
      # Asked rather than assumed: two failed goes are evidence against a third,
      # but only the person who read the log knows. ask takes only an explicit
      # y or n, so a reflex Enter at the end of a long run settles nothing.
      echo ""
      local again=""
      ask "${BOLD}  Open another fixing session? [y/n] ${OFF}" again yn || true
      if is_yes "$again"; then
        # Clearing the count and falling through to the fix below, rather than
        # going round to the top of the loop. The top is regression_run, and a
        # re-run is the one thing known to be pointless here: the same suite
        # against the same address with the same tree answers the same way. The
        # human who says yes is asking for another look at the failure, not for
        # a fourth confirmation that it fails.
        state_set "$state" "regression.$stage.attempts" 0
        attempts=0
        info "  Opening another session on $stage."
      else
        info "  Carry on when you are ready with: $SELF $slug"
        # The person takes it from here, so the step's own session is where
        # the next start goes, not this gate again (after_step reads it). An
        # explicit no only: no answer (the terminal gone) settles nothing.
        is_no "$again" && REGRESSION_TAKEN_OVER=1
        return 1
      fi
    fi

    state_set "$state" "regression.$stage.attempts" "$((attempts + 1))"
    regression_fix "$wt" "$slug" "$stage"
    local frc=$?
    if [[ "$frc" -eq 5 ]]; then
      state_set "$state" "regression.$stage.attempts" "$attempts"
      info "  Nothing was spent on $stage. Repair sclaude's rules, then: $SELF $slug"
      return 1
    fi

    # 4 means the friction review after the session fixed the orchestrator.
    # The stage is run again rather than reported: a red run must never be
    # something the cycle walks past, and "carry on with sclaude <feature>" was
    # exactly that. The attempt is given back — it was not the branch that was
    # wrong.
    #
    # With the new code, not the old. bash has every function of this process
    # in memory already, so a loop round here would run the regression exactly
    # as it ran before the fix. The preview re-enters through remind_prod,
    # which redeploys a preview whose last run was red, so the process is
    # replaced by a fresh `sclaude <feature>` that reads the fixed modules. The
    # other stages have no such clean re-entry — local goes back through its
    # step's session, prod through a deploy of an unchanged main — so they go
    # round here, in-process: the fixes a review makes are to hooks and prompts
    # far more often than to regression.sh itself.
    #
    # Not without end. Each pass spends a fixing session and a friction review,
    # and a review can always find something to change; after
    # REGRESSION_MAX_ATTEMPTS such passes the attempt is counted like any other,
    # so the ordinary limit stops the machine and asks the person.
    if [[ "$frc" -eq 4 ]]; then
      fixed_here=1
      fix_status_set "$state" "$stage" orchestrator-fixed
      local ofix
      ofix="$(state_get "$state" "regression.$stage.orchestrator_fixes" 2>/dev/null || echo 0)"
      [[ "$ofix" =~ ^[0-9]+$ ]] || ofix=0
      state_set "$state" "regression.$stage.orchestrator_fixes" "$((ofix + 1))"
      if [[ "$ofix" -lt "$REGRESSION_MAX_ATTEMPTS" ]]; then
        state_set "$state" "regression.$stage.attempts" "$attempts"
      fi
      echo ""
      info "  The friction review fixed the orchestrator — running $stage again."
      if [[ "$stage" == "preview" ]]; then
        info "  Restarting sclaude so the run uses the fixed code."
        exec "$INSTRUMENTS/bin/sclaude" "$slug"
      fi
      continue
    fi

    # 3 means the session found the cause outside this worktree and wrote it
    # down instead of editing code to make a red run go green. The attempt is
    # given back, the stage is run once more (below), and if the next session
    # says the same, the note is put in front of the human, who is the only one
    # who can change a deployment's environment.
    if [[ "$frc" -eq 3 ]]; then
      # Neither "fixed" nor "failed to fix": the third outcome, and the attempt
      # is given back. It stays distinct from `red` because the attempt is not
      # counted — merging the two would put the row numbers at odds with
      # `attempts`.
      fix_status_set "$state" "$stage" blocked
      state_set "$state" "regression.$stage.attempts" "$attempts"
      echo ""
      warn "  The $stage regression is red for a reason outside this branch."
      while IFS= read -r line; do
        info "  $line"
      done < "$wt/.sclaude/local/feature/regression.blocked"
      echo ""
      info "  Nothing was changed, and the attempt was not counted."

      # Run again once, without asking. Returning dropped the person at the
      # shell only for the next start to put the same note in front of them —
      # and the commonest note, a test that flaked on a loaded machine, needs
      # nothing but the run made again. Once, because a cause that really is
      # outside (a deployment's environment) would otherwise go round for ever:
      # red, a session, the same note, red again.
      #
      # The note stays through the run: an interrupted one leaves it for the
      # next start's question. A green run drops it, the next fixing session
      # writes its own.
      if [[ "$blocked_reruns" -lt 1 ]]; then
        blocked_reruns=$((blocked_reruns + 1))
        info "  Running $stage again, once: a flaky failure goes green on its own."
        continue
      fi
      info "  Blocked again after a second run, so it is not noise."
      info "  The note is .sclaude/local/feature/regression.blocked; carry on with: $SELF $slug"
      notify_feature "$slug" "${stage^} regression blocked from outside
The fixing session found the cause outside the branch and changed nothing.
Note: .sclaude/local/feature/regression.blocked" 2>/dev/null || true
      return 1
    fi

    [[ "$frc" -eq 0 ]] || return 1
    fixed_here=1

    # The session finished and the loop goes round to run the stage again. If
    # that run is green the branch at the top rewrites this to `green`; if it
    # is red again, `red` is what this session came to. Recording it here rather
    # than inferring it at render time is the rule the Friction column follows:
    # every value is written at the moment it happens.
    #
    # `stalled` is not overwritten: a session that never ran did not leave the
    # stage red, it left nothing at all, and the row should keep saying so.
    [[ "$(state_get "$state" "regression.$stage.fix_status" 2>/dev/null || true)" \
       == *stalled ]] || fix_status_set "$state" "$stage" red
  done
}

# The tree a run is about: HEAD's commit when the working tree is clean, and
# nothing when it is not. An uncommitted edit has no name, so a dirty tree never
# matches a recorded one and the suite always runs on it.
#
# worktree_dirt rather than a bare `git status`: it leaves out sclaude's own
# scratch paths (.sclaude/local/feature, .vercelignore), which are untracked wherever the
# exclude was never written — and then no tree would ever match. It is the
# same question deploy_unchanged asks, and the two must not disagree.
regression_tree() {
  local wt="$1"
  git -C "$wt" rev-parse HEAD >/dev/null 2>&1 || return 0
  [[ -z "$(worktree_dirt "$wt")" ]] || return 0
  git -C "$wt" rev-parse HEAD 2>/dev/null || true
}

# Puts the cycle back on the step the fix belongs to, once the stage is green.
#
# After the green run rather than before the fix, and that ordering is the
# whole of it. Rewinding first would mean a state that lies the moment a
# session is interrupted: the step stands open with no work done in it. Doing
# it here describes what actually happened — there are changes, they have been
# checked, and the cycle honestly returns to the step they belong to.
#
# The idiom is cmd_replan's (bin/sclaude): clear `done` and `finished`, set
# `step`, and let the caller's own run_step carry it forward.
regression_rewind() {
  local wt="$1" slug="$2" stage="$3"
  local -a rewind=()

  case "$stage" in
    # Step 2 is already the current one — there is nothing to rewind into.
    local) return 0 ;;
    # The pull request is open and pushes still reach the branch, so the review
    # is where the fix belongs.
    preview) rewind=(review) ;;
    # Production also rewinds to the review, and deliberately not to step 3 as
    # well. A merged pull request is `closed` on GitHub's side and cannot be
    # reopened, so the fix does need a pull request of its own — but step 3
    # cannot tell a new one from the merged one: capture_pr asks `gh pr view`,
    # which on that branch still answers with the old number, and the step's
    # check is only that a number exists. Rewinding into a step that closes
    # itself on stale evidence buys nothing. The review session opens the new
    # pull request instead, carrying `Closes #N` for the same issue — one
    # business task, two pull requests, which is the only shape that ships.
    prod) rewind=(review) ;;
    *) return 0 ;;
  esac

  # The four lines this used to spell out live in step_rewind_to (steps.sh):
  # `cmd_replan` and the QA hand-back want the same ones, differing only in
  # which steps they name.
  step_rewind_to "$wt" "${rewind[0]}" "${rewind[@]}"
  # The same two marks the QA hand-back writes, and for the same reason: by the
  # time a deployed stage goes red the pull request is merged — production ships
  # after the merge — so `run_step` would treat the review as having nothing left
  # to do, and `after_step` would close it again the moment the session exited.
  # Only one of the two reopeners used to write them, which left this path with
  # exactly the bug the other one had fixed.
  local state="$wt/.sclaude/local/feature/state.json" pr
  state_set "$state" reopened "${rewind[0]}" 2>/dev/null || true
  # And who reopened it. A preview fix is already green on the preview and goes
  # on to QA and the merge in the same run: once merged, the mark has nothing
  # left to hold, and run_step lets the merge close the review. A production
  # one holds until a new pull request arrives, and render_prompt hands that
  # review the failure. QA's hand-back writes its own (watch_rewind).
  state_set "$state" reopened_by "$stage" 2>/dev/null || true
  # A production fix goes the whole way round, preview suite included — and the
  # preview gate short-circuits on a verdict it already holds. The tree check
  # there would catch it too; clearing it here says so where it happens.
  [[ "$stage" == "prod" ]] \
    && state_set "$state" regression.preview.status null 2>/dev/null || true
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" ]] \
    && state_set "$state" reopened_pr "$pr" 2>/dev/null || true
  issue_sync "$wt"
  info "  The cycle returns to step '$(step_title "${rewind[0]}")'."
  return 0
}
