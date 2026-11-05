#!/usr/bin/env bash
#
# The cycle's epilogue — preview, QA, the merge and production, step by step
# (remind_prod) — and what is said when shipping failed. The parts it calls
# are in shipped.sh, vercel.sh, qa.sh, merge.sh and demo.sh.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# A ship to production that failed, looked into at once: time is dear there.
# Production keeps the release it had — vercel switches it whole — but a
# promote that began may have put the new migrations under it, so its suite is
# asked first. Then a fixing session, told which command failed and what the
# suite said (regression_fix_block), and by what it did:
#   a fix committed — step 4 reopened for its pull request, the whole way
#     round, as after a red production; resumed at once, or by the restarted
#     sclaude when the friction review fixed sclaude too;
#   sclaude fixed (4) — restarted, the ship offered again;
#   a cause outside the code (3) — its note shown, the ship offered next run;
#   nothing changed, or no session (5) — the person's, the ship offered again.
#
#   ship_failed <wt> <slug> <the command that failed> <1 when the promote began>
ship_failed() {
  local wt="$1" slug="$2" failed="$3" began="$4"
  local state="$1/.sclaude/local/feature/state.json" before fix_rc=0 moved=""
  if [[ -n "$began" ]]; then
    info "  The promote began: production may run its old code on the new migrations. Its suite says how it is:"
    local now_rc=0
    regression_run "$wt" "$slug" prod || now_rc=$?
    case "$now_rc" in
      0) info "  Production answers green." ;;
      1) alarm "  Production is red now — its old code on the new schema."
         state_set "$state" regression.prod.after_failure red 2>/dev/null || true ;;
      *) warn "  Production's suite could not run — see above." ;;
    esac
  fi
  state_set "$state" regression.prod.deploy_failed "${failed:-the ship}" 2>/dev/null || true
  before="$(git -C "$wt" rev-parse HEAD 2>/dev/null)"
  info "  It failed at: ${failed:-the ship}. A session looks into it now."
  regression_fix "$wt" "$slug" prod || fix_rc=$?
  [[ "$fix_rc" -ne 5 && "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" != "$before" ]] && moved=1
  # A note beside a fix — part of the cause outside the code — is shown and
  # kept, not left for the next gate to read as its own.
  if [[ -n "$moved" && "$fix_rc" -eq 3 ]]; then
    warn "  The session also left a note — part of the cause is outside the code:"
    sed 's/^/    /' "$wt/.sclaude/local/feature/regression.blocked" 2>/dev/null
    blocked_note_keep "$wt" prod "the ship failed"
  fi
  if [[ -n "$moved" ]]; then
    fix_status_set "$state" prod fixed
    regression_rewind "$wt" "$slug" prod
    info "  The fix goes the whole way round: step 4 is reopened for its pull request."
  fi
  case "$fix_rc" in
    4)
      [[ -n "$moved" ]] || fix_status_set "$state" prod orchestrator-fixed
      info "  The friction review fixed the orchestrator — restarting sclaude."
      exec "$INSTRUMENTS/bin/sclaude" "$slug" ;;
    5)
      info "  Put it right and carry on: $SELF $slug"
      return 0 ;;
  esac
  if [[ -n "$moved" ]]; then
    cmd_resume "$slug"
    return $?
  fi
  if [[ "$fix_rc" -eq 3 ]]; then
    fix_status_set "$state" prod blocked
    warn "  The cause is outside the code, says the session:"
    sed 's/^/    /' "$wt/.sclaude/local/feature/regression.blocked" 2>/dev/null
    blocked_note_keep "$wt" prod "the ship failed"
    info "  Put it right; the next $SELF $slug offers the ship again."
    return 0
  fi
  fix_status_set "$state" prod unchanged
  warn "  The session changed nothing in the branch."
  info "  Put it right and carry on: $SELF $slug — the ship is offered again."
  return 0
}

remind_prod() {
  local wt="$1" slug="$2" pr branch merged migrations=""
  # [N] in sclaude's tab during step 4: production is the next step.
  stop_asked "the preview, QA and production" "$slug" && return 0
  # A ship marked by a pass that was cut off is not going on: this pass asks
  # again, and marks it again (below).
  state_set "$wt/.sclaude/local/feature/state.json" prod_pass.shipping null 2>/dev/null || true
  # A ship that failed before is not this pass's: its fix (regression_fix_block)
  # is over, or the ship is asked about again below.
  state_set "$wt/.sclaude/local/feature/state.json" regression.prod.deploy_failed null 2>/dev/null || true
  state_set "$wt/.sclaude/local/feature/state.json" regression.prod.after_failure null 2>/dev/null || true
  local issue preview_done=0 prod_done=0 prod_tried=0 prod_unanswered=0 qa_skipped=0
  # What `deployed-preview` is actually about, which is not preview_done.
  #
  # preview_done means "we shipped one in this run", and it is right for what it
  # is used for — the questions, the QA move, watch_start. The label means
  # something else: a preview is on hosting and its suite passed against it. The
  # two came apart when the red path stopped claiming the label. Consider a run
  # that goes red, a fixing session that commits nothing because the cause was
  # outside the branch, and a person who redeploys by hand: on the next pass
  # deploy_unchanged is true, so preview_done stays 0, the gate short-circuits
  # on the `passed` it recorded — and a green preview would never be labelled at
  # all. So the label is read from the two things it names, and both are already
  # written down.
  local preview_live=0
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr || echo "?")"
  branch="$(state_get "$wt/.sclaude/local/feature/state.json" branch || true)"
  # The issue's number, the branch and the PR are read here, once, and the rest
  # of the function works from them. The clean-up that used to remove the tree
  # in the middle of this function now stands at its end, so the state no longer
  # vanishes underfoot — but a single snapshot is still what this wants: the
  # values are asked for in several places below, and re-reading them would mean
  # a function whose behaviour changes depending on when each line ran.
  issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"
  [[ "$issue" == "null" ]] && issue=""
  [[ -n "$branch" ]] && merged="$(branch_pr_state "$branch")"
  # Production carries the feature and its last regression was not green: the
  # pass stops here, before the preview, the question of shipping and the
  # issue, the epilogue and the clean-up (prod_red_hold). GitHub is asked
  # whether production carries it only then, and the answer kept for the
  # issue below (carried_asked).
  local carried=0 carried_asked="" carries=0
  if [[ "${merged:-}" == "MERGED" && "$(regression_status "$wt" prod)" == failed ]]; then
    carried_asked=1
    prod_carries_feature "$wt" || carries=$?
    if [[ "$carries" -eq 0 ]]; then
      carried=1
      prod_red_hold "$wt" "$slug"
      return 0
    fi
    # Red, and not known whether production carries it: held as well, as
    # `return` stops on the same silence, rather than shipped past or closed.
    if [[ "$carries" -eq 2 ]]; then
      echo ""
      alarm "Production's last regression was red, and GitHub could not say whether it carries '$slug'."
      info "  Nothing goes on until it can (gh auth status). Then: $SELF $slug"
      return 0
    fi
  fi
  branch_has_migrations "$wt" && migrations=1
  # Or noted by an earlier run (rollback_remember_migrations): one stopped
  # before production and run again once main was brought level finds the
  # range empty, the merge pulled down by then, and would ship without the
  # promote the branch needs. Promoting what is applied already changes
  # nothing.
  [[ -z "$migrations" ]] \
    && [[ -n "$(state_get "$wt/.sclaude/local/feature/state.json" deploy.prod.migrations 2>/dev/null \
                | grep -v '^null$')" ]] \
    && migrations=1
  # Named once here: the prod block adds it to a commit, and the rollback reads
  # the same answer from the same place.
  local migrations_dir; migrations_dir="$(project_migrations_dir "$wt" || true)"
  # A change nothing deploys (no_change.sh) has no preview for QA to look at
  # and nothing for production to ship: of all below, only the merge is left.
  local no_deploy=0
  no_deploy_feature "$wt" && no_deploy=1

  echo ""
  if [[ "${merged:-}" == "MERGED" ]]; then
    echo "${BOLD}Feature $slug: PR #$pr is merged.${OFF}"
    # Seen here also when it was merged with nobody waiting: the history
    # keeps the first time only (process.py).
    history_add "$wt/.sclaude/local/feature/state.json" merge merged
    # A sync left open is over with the merge: it was for a merge that has
    # happened (on GitHub, past it), and the issue's summary stops naming it.
    sync_close_open "$wt/.sclaude/local/feature/state.json"
  elif [[ "$no_deploy" -eq 1 ]]; then
    echo "${BOLD}Feature $slug: PR #$pr is open.${OFF}"
    echo "${DIM}Next: the merge, which is yours to do — nothing here deploys.${OFF}"
  else
    echo "${BOLD}Feature $slug: PR #$pr is open.${OFF}"
    echo "${DIM}Next: the preview, then QA, then the merge — the merge is yours to do.${OFF}"
  fi

  # Whether the branch merges with main, before anything is shown to QA: the
  # preview and QA would otherwise look at code that is not what merges, and
  # the merge wait below would wait for a merge nobody can make. On a conflict
  # the sync with main (sync.sh) merges main in and pushes, and the run goes
  # on with that: the preview below sees a changed tree and deploys it.
  # Not for a pull request closed without a merge: it never merges, however
  # well its branch does.
  if [[ "${merged:-}" != "MERGED" && "${merged:-}" != "CLOSED" && "$pr" =~ ^[0-9]+$ ]]; then
    # sync_gate: a pull request an earlier run handed over goes back to a
    # draft before the new code reaches it.
    local synced=0
    sync_gate "$wt" "$slug" "$pr" || synced=$?
    [[ "$synced" -eq 1 ]] && return 0
  fi

  # The order is not arbitrary: preview deploys the worktree's contents, so it
  # is asked about before the clean-up that removes that worktree.
  #
  # Preview is launched from the main repository with a path to the worktree: the
  # project's link lies in its .vercel/, and the worktree has none — a `vercel`
  # launched from there would create a new project instead of deploying to this
  # one.
  #
  # We remember the block's outcome: the labels will be set from it and the
  # session will learn from it what to write. The preview is not asked about —
  # it is the deployment QA looks at, and nothing after it can happen without
  # one — so run_block returns zero exactly when every command succeeded: the
  # label means "shipped", and a failed deploy has not shipped.
  #
  # Through an `if` rather than `&& preview_done=1`: under `set -o pipefail` a
  # trailing `&&` at the end of a function would make its status one on an
  # ordinary refusal.
  # The deployment's address is captured rather than only printed (preview_ship
  # does it): run_block runs its commands in a subshell and returns pass or
  # fail, so a caller has no other way to learn it, and the preview regression
  # below has to aim the suite somewhere. run_vercel writes it only on a
  # successful deploy.
  #
  # Unless this very tree is already up there. Then there is nothing to ask: the
  # answer is known, and we say it as a statement rather than a question. The
  # deploy stays available on purpose — `sclaude preview <slug>` and the menu's
  # own "Deploy a preview" item both reach run_block directly — because a
  # deliberate re-deploy of an unchanged tree is a real thing to want, just not
  # a thing to be asked about every time.
  #
  # preview_done stays 0 here, and that is deliberate: it means "shipped in this
  # run", the labels and the epilogue's outcome are built from it, and nothing
  # was shipped. What is already on hosting the issue learned when it went there.
  #
  # Skipped only when this very tree is on hosting and its run was green, or
  # when QA accepted this very preview before the merge: a stage that runs no
  # suite has no green to show, and its accepted preview is no exception. An
  # unchanged tree whose last run was red is deployed again: the fix that
  # followed may have been outside the tree (an environment variable, a
  # setting on Vercel), and the only way to learn whether it worked is a fresh
  # deployment and a fresh run.
  #
  # And skipped, loudly, when the pull request is already merged. The preview
  # exists so that QA can look before the merge; after it there is nothing left
  # for that look to hold back, and a red run would send a feature that is
  # already in main back into review. A merged branch whose preview was never
  # green is an exception to the flow — somebody merged before QA — and it is
  # said in red rather than in passing.
  #
  # The one exception to "nothing goes on past a red or missing regression".
  # Production needs three things: a green preview regression, the issue in
  # Done, and the merge. A merge satisfies the last two by itself (`Closes #N`
  # moves the issue to Done), and for this case alone production is offered
  # without the first. Everywhere else it is unreachable without all three:
  # an open pull request stops at the fallback below, and a red preview
  # returns before it.
  if [[ "$no_deploy" -eq 1 ]]; then
    no_deploy_say "No preview, no QA on one, no production: the merge is what is left."
  elif deploy_unchanged "$wt" preview \
     && [[ "$(regression_status "$wt" preview)" == "passed" ]]; then
    echo ""
    info "Preview already deployed at $(deploy_head "$wt" preview | cut -c1-8) — unchanged and green, skipping."
    info "  To send it again anyway: $SELF preview $slug"
    preview_apply_migrations "$wt" || true
    # A red status a green rewrite did not get written over is tried again.
    status_green_again "$slug" "$issue" "$pr" "${merged:-}" "$wt"
    preview_live=1
  elif [[ "${merged:-}" == "MERGED" ]] && deploy_unchanged "$wt" preview && qa_accepted_now "$wt" deployed; then
    # Merged after QA accepted this very preview — sclaude's own merge, or a
    # person's right after it. A stage that runs no suite (`none`) leaves no
    # green status for the branch above, and without this every later pass
    # called such a feature merged before QA and asked to ship it "anyway".
    echo ""
    info "Preview at $(deploy_head "$wt" preview | cut -c1-8) — QA accepted it before the merge; not deployed again."
    preview_live=1
  elif [[ "${merged:-}" == "MERGED" ]]; then
    echo ""
    alarm "PR #$pr is already merged — the preview and QA are skipped."
    alarm "  This is an exception to the flow: QA comes before the merge, and this"
    alarm "  feature went into main without a green preview${issue:+ or QA on issue #$issue}."
    alarm "  Production is offered without the preview regression — only in this case."
    qa_skipped=1
  else
    preview_apply_migrations "$wt" || true
    # Deployed or not, the gate takes it on: a deploy that failed its tries
    # is its red, fixed as a red run is.
    preview_ship "$wt" || true
    preview_done=1
  fi

  # The preview regression, and the board's column behind it.
  #
  # This is the one place where "it works" can be said about a deployment rather
  # than about a tree: the branch is on real hosting, and the suite runs against
  # that hosting. A green run here is what makes "In QA" a statement of fact
  # rather than a request — see QA_TO in board.sh.
  #
  # A red one opens a fixing session in step 4, where the pull request is still
  # open and pushes still reach the branch — and when two of those have not
  # made it green, the gate hands the feature back. Everything below this line
  # depends on that: the merge, the clean-up and production all assume the
  # branch is worth shipping, and a red preview is the statement that it is not
  # yet. So we stop here rather than carrying on to offer them.
  #
  # The gate has already put the cycle back on step 4 by this point, so there is
  # somewhere to carry on to — `sclaude <slug>` resumes into the review.
  #
  # A skipped preview does not come in here, and nothing inside is lost by that:
  # the gate short-circuits on a `passed` it already recorded, the issue is
  # already in the column issue_qa_ready would move it to, and watch_start was
  # called when the deploy actually happened. The one thing that does not belong
  # to the deploy is the QA question below — whether anybody looked at this
  # before it was merged is a fact about the issue, true or false regardless of
  # who deployed what today. So it is asked either way.
  if [[ "$preview_done" -eq 1 ]]; then
    if regression_gate "$wt" "$slug" preview; then
      preview_live=1
      status_green_again "$slug" "$issue" "$pr" "${merged:-}" "$wt"
      # Green, and before QA is sent to it: what changed and the whole feature,
      # for QA to see — where a person does QA.
      [[ "$(project_flow_mode qa "$wt")" != auto ]] && demo_refresh "$wt" preview
      qa_retest "$wt" "$issue" "$pr" fresh || true
      [[ -n "$issue" ]] && issue_qa_ready "$issue"
      cycle_edge "$wt" preview in_qa sclaude "preview regression green"
      cycle_edge "$wt" in_qa qa_check sclaude "the issue moved to ${QA_TO:-QA}"
      qa_sent "$wt"
      qa_missed "$issue" "${merged:-}" "$wt" && qa_skipped=1
      watch_start "$wt" "$slug" "$issue" "$pr"
    else
      # Zero for preview, although the deploy did happen: the label says the
      # code is on preview, and a reader takes that as "it is there and it
      # works" — the epilogue's own prompt words it as "preview passed means
      # deployed-preview". A red run is the statement that it does not work
      # yet, and the fixing session in step 4 will push again, so the commit
      # the label would be about is already on its way out. The section still
      # gets written, and it is where the deploy is named: prose can say "on
      # preview, regression red", a label cannot.
      cycle_edge "$wt" preview review sclaude "preview regression red"
      run_status "$slug" "$issue" "$pr" "${merged:-}" 0 0 "$wt" 1 0
      echo ""
      warn "The preview regression is red — the feature is not ready to merge."
      info "  The issue stays where it is, and production is not offered."
      info "  Carry on with: $SELF $slug"
      return 0
    fi
  elif [[ "$no_deploy" -ne 1 ]] && qa_missed "$issue" "${merged:-}" "$wt"; then
    qa_skipped=1
  fi

  # We re-read the PR's state here rather than using what was read at the start:
  # between that read and this line came the preview deploy and minutes of
  # waiting — precisely the window in which the merge happens. Everything below
  # depends on the merge, and being wrong in that direction costs more than one
  # request to gh.
  if [[ -n "$branch" && "${merged:-}" != "MERGED" ]]; then
    merged="$(branch_pr_state "$branch")"
    if [[ "${merged:-}" == "MERGED" ]]; then
      echo ""
      echo "${BOLD}PR #$pr has been merged since we started.${OFF}"
    fi
  fi

  # The merge itself, offered rather than only asked for.
  #
  # Here, and not a line earlier: everything above is what makes the branch
  # worth merging — it is deployed to preview, the suite ran against that
  # deployment, and a red run returned long before this point. And not a line
  # later either: the whole of the rest of this function is the merge's
  # consequences, so a merge agreed to here carries straight on into them
  # within the same run — the issue's end date below, then the clean-up and
  # production — instead of ending the cycle with an errand.
  #
  # The column is read at this moment rather than remembered from earlier. QA
  # takes hours, and the deploy and the regression above take minutes of them:
  # an issue that reached Done while they ran is a merge to offer now.
  #
  # QA first. The preview above is what they look at, and until they have
  # decided there is nothing to offer: merging now would be merging something
  # nobody has accepted. A hand-back goes straight into the review session with
  # QA's comments, in this same run.
  #
  # Both waits need a preview that is up and green. Without one — a deploy
  # that failed every try — there is nothing for QA to look at and the
  # issue never went to In QA, so a column of In progress would read as a
  # hand-back that never happened. That run ends with the reminder below, as it
  # always did.
  if [[ "${merged:-}" != "MERGED" && "$preview_live" -eq 1 ]]; then
    local qa_verdict=0
    qa_wait "$slug" "$issue" "$pr" "$branch" "$wt" || qa_verdict=$?
    if [[ "$qa_verdict" -eq 3 ]]; then
      merged="MERGED"
      qa_skipped=1
      echo ""
      alarm "PR #$pr was merged while QA still had issue #$issue."
      alarm "  This is an exception to the flow: QA comes before the merge."
    fi
    if [[ "$qa_verdict" -eq 2 ]]; then
      cycle_edge "$wt" qa_check qa_verdict "${QA_BY:-qa}" "${QA_HOW:-the board}"
      cycle_edge "$wt" qa_verdict review qa "the board" note="issue #$issue left $QA_TO"
      echo ""
      say "${BOLD}Issue #$issue left '$QA_TO': the feature returns to development.${OFF}"
      info "  What was said since — on the issue and on the pull request — goes into"
      info "  the review session below."
      # The comments are collected by the watcher, verbatim, into the file
      # run_step hands to the session — asked to look now rather than at its
      # next sweep.
      watch_look_now "$slug"
      qa_take_back "$wt" "$slug" || return 0
      run_step "$wt" "$slug" review
      return 0
    fi
    # Main moves while QA works, and what merged cleanly before the preview
    # may not now. Asked before the hand-off below: one made and taken back
    # a moment later flips the board, the pull request and its summary for
    # nothing. A sync here changes the code QA passed, so the run starts over
    # on it: the preview, its regression, and QA again (qa_retest).
    if [[ "${merged:-}" != "MERGED" ]]; then
      local resynced=0
      sync_gate "$wt" "$slug" "$pr" || resynced=$?
      [[ "$resynced" -eq 1 ]] && return 0
      if [[ "$resynced" -eq 3 || "$resynced" -eq 5 ]]; then
        # Back to the preview on the synced code, from wherever the history
        # last left the feature: the merge's wait, the hand-off (or the merge
        # question after it), or QA's yes before any hand-off.
        local moved="main merged in"
        [[ "$resynced" -eq 5 ]] && moved="commits reached the branch from elsewhere"
        qa_way_back "$wt" "the branch moved" "$moved"
        remind_prod "$wt" "$slug"
        return $?
      fi
    fi
    # QA said yes — to this issue. The pull request is handed over only when
    # every issue it closes is in Done, and until then it stays a draft, which
    # is what holds the merge offer below back (see pr_qa_handoff).
    if [[ "$qa_verdict" -eq 0 ]]; then
      local handed=0
      # QA's yes, once in this pass of QA: a run while the merge waits takes
      # no way again, one after a way back does. The way into the hand-off
      # is written where it is made (pr_qa_handoff_now), here or by the QA
      # timer; the way on from it once it is made.
      qa_yes_edge "$wt"
      pr_qa_handoff "$wt" "$pr" "$issue" || handed=$?
      [[ "$handed" -eq 0 || "$handed" -eq 3 ]] \
        && once_edge "$wt" handoff merge sclaude "pr_qa_handoff" note="PR #$pr ready"
      # Done before — by an earlier run, or by the QA timer while this one
      # waited, whose words went to Telegram rather than here.
      [[ "$handed" -eq 3 ]] \
        && info "PR #$pr was already handed over for the merge: ready, in the backlog, with its summary."
    fi
  fi
  # Without a deploy no QA hand-off makes the pull request ready, so it is
  # made ready here: a draft cannot be merged.
  local offer_mode=""
  if [[ "$no_deploy" -eq 1 ]]; then
    offer_mode=nodeploy
    if [[ "${merged:-}" != "MERGED" ]]; then pr_undraft "$pr"; fi
  fi
  if [[ "${merged:-}" != "MERGED" ]] && merge_offer "$slug" "$pr" "$issue" "$offer_mode" "$wt"; then
    merged="MERGED"
  fi
  # Declined, or GitHub named something in the way: the merge is then done on
  # GitHub, and this notices it rather than ending the run with an errand.
  if [[ "${merged:-}" != "MERGED" ]] && [[ "$preview_live" -eq 1 || "$no_deploy" -eq 1 ]]; then
    local wait_rc=0
    merge_wait "$slug" "$issue" "$pr" "$branch" "$offer_mode" "$wt" || wait_rc=$?
    [[ "$wait_rc" -eq 0 ]] && merged="MERGED"
    # Main moved under the wait and the branch no longer merges: the sync,
    # and the run again on what it pushes.
    if [[ "$wait_rc" -eq 3 ]]; then
      cycle_edge "$wt" merge_wait preview sclaude "the branch moved" note="main no longer merges cleanly"
      # The pull request goes back to a draft now: it was handed over, and
      # the sync in the run below pushes code nobody has checked.
      sync_withdraw "$wt" "$pr"
      remind_prod "$wt" "$slug"
      return $?
    fi
    # Closed without a merge: there is nothing left to wait for, and the
    # reminder below would tell the person to merge a pull request that no
    # longer can be. No status session for it — the pull request's own state
    # says it — but the labels the preview earned go on, sclaude's own work.
    if [[ "$wait_rc" -eq 2 ]]; then
      STATUS_LABELS_ONLY=1 run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" 0 "$wt"
      return 0
    fi
  fi

  # The work has ended — that is visible here and only here. GitHub closes the
  # issue itself by `Closes #N`, at the moment of the merge, when sclaude is not
  # running; this line is the first thing it does on learning of the merge, and
  # it does not matter whether that happened a minute ago or last week.
  # Symmetrical to the cycle's start, which fills in the empty start field the
  # same way.
  if [[ "${merged:-}" == "MERGED" && -n "$issue" ]]; then
    issue_end_date "$(gh_repo)" "$issue"
  fi
  # The pull request's own column follows the merge to Done. The hand-off put
  # it in the backlog to wait for the merger, and a board whose workflow moves
  # merged PRs does this by itself — but not every board has that workflow
  # switched on, and a merged PR left waiting in the backlog is a lie on it.
  [[ "${merged:-}" == "MERGED" ]] && { pr_board_set "$pr" "$QA_DONE" "$issue" || true; }

  # And the cycle ends with it. A preview fix put the cycle back on the review
  # and this run carried it on to the merge without ever returning there, so
  # the review is still open — closed now, by the merge, as run_step would.
  # Only that reopening, by the same rule run_step follows: QA's hand-back and
  # production's wait for a session, and a merge must not swallow them.
  if [[ "${merged:-}" == "MERGED" ]] \
     && [[ "$(state_get "$wt/.sclaude/local/feature/state.json" step 2>/dev/null || true)" == "review" ]] \
     && [[ "$(state_get "$wt/.sclaude/local/feature/state.json" reopened_by 2>/dev/null || true)" == "preview" ]]; then
    step_close_merged "$wt"
    issue_sync "$wt"
  fi
  # Whatever closed it by now — QA's Done through the board's auto-close, or
  # the merge — came before production. See issue_hold_open (github.sh).
  # Not once the merge is in production: that close was the cycle's own end,
  # and a pass after a declined clean-up reopened the issue only to close it
  # again a moment later.
  # Asked once a pass, and kept: it asks GitHub, and the close at the end
  # must not read a different answer than the hold here did — nor than the
  # one at the top, when that asked already. The merge may have come in this
  # pass since; then it is asked here.
  [[ -z "$carried_asked" && "${merged:-}" == "MERGED" ]] && prod_carries_feature "$wt" && carried=1
  if [[ "$carried" -eq 0 ]]; then
    issue_hold_open "$issue"
  fi

  # Neither the clean-up nor production has anything to do before the merge: the
  # worktree still holds the only copy of the work, while `vercel --prod` and
  # `db:promote` look at main, where the feature's code is not yet — the promote
  # would run idle and the deploy would ship a prod without it. So we go further
  # only when merged, and otherwise say what this will continue with and where
  # exactly we stopped.
  if [[ "${merged:-}" != "MERGED" ]]; then
    echo ""
    # Which ticket is being waited on, not only which pull request. The PR's
    # number is what the merge is done to; the issue's is what a person tracks
    # the work by and what QA answers in — and by the time this line is read
    # the two have often been apart for days. merge_offer has already said its
    # piece when it had one, so this is the plain case: nobody has passed the
    # feature yet, or GitHub named an obstacle just above.
    #
    # Reached with no green preview up — the waits above need one — or with
    # no branch for merge_wait to ask about. Without a preview the next thing
    # is not the merge but the preview itself, since QA has nothing to look at.
    if [[ "$no_deploy" -eq 1 ]]; then
      info "Waiting for the merge of PR #$pr${issue:+ (issue #$issue)}."
      info "  Merge it, then run: $SELF done $slug"
    elif [[ "$preview_live" -ne 1 ]]; then
      info "No green preview is up, so QA has nothing to look at yet."
      info "  QA and the merge come after it. Once the cause is fixed: $SELF $slug"
    else
      info "Waiting for the merge of PR #$pr${issue:+ (issue #$issue)}."
      info "  Merge it, then run: $SELF done $slug"
      info "  It removes the worktree and the branches. Production comes after"
      local promote_cmd; promote_cmd="$(project_get database.promote "$wt" 2>/dev/null || true)"
      info "  that, from $REPO: ${migrations:+${promote_cmd:-the promote command}, then }vercel --prod."
    fi
    # No status session for waiting on the merge — a session per wait spent
    # money to restate the pull request's state — but the labels the preview
    # earned go on the issue chain (deployed-preview), sclaude's own work.
    STATUS_LABELS_ONLY=1 run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" 0 "$wt"
    return 0
  fi

  # The clean-up used to stand here, before production. It now stands at the
  # end, and the reason is the regression that follows the prod deploy: a red
  # run there needs the worktree it would have removed — the log to read, the
  # state to record, and a tree to open a fixing session in. Nothing required
  # the order that was: preview had to come before the clean-up because it
  # deploys the worktree's contents, and production had to come after the merge
  # because it looks at main. Both still hold.

  # Merged, and nothing to ship: the cycle ends with the issue and the clean-up.
  # Unless the merge took more than this tree held: then production is asked
  # about as usual, the preview and QA it skipped named in the question.
  local merged_unchecked=0
  if [[ "$no_deploy" -eq 1 ]] && ! no_deploy_merged "$pr"; then
    no_deploy=0
    qa_skipped=1
    merged_unchecked=1
    echo ""
    alarm "PR #$pr merged files outside $(printf '%s ' "${NO_DEPLOY[@]}")— or GitHub did not say which."
    alarm "  It went in without a regression, a preview or QA; production is asked about below."
  fi
  if [[ "$no_deploy" -eq 1 ]]; then
    # Closed before the epilogue reads it, as at the cycle's end below.
    issue_close_done "$issue" nodeploy
    run_status "$slug" "$issue" "$pr" "${merged:-}" 0 0 "$wt"
    state_set "$wt/.sclaude/local/feature/state.json" prod_pass.ended "$(prod_pass_mark "$wt" nodeploy)"
    if ! cmd_done "$slug"; then
      info "Later: $SELF done $slug"
    fi
    return 0
  fi

  once_edge "$wt" merged ship sclaude "PR #$pr merged"

  # The production question, sharpened when nobody passed the branch through QA.
  #
  # One question, not two: the human is already being asked whether to ship, and
  # a second prompt about the same decision would be answered the way repeated
  # prompts always are. So the warning goes into the note run_block already
  # prints and the question itself says what is being agreed to — the same
  # argument the clean-up makes for having no question of its own.
  #
  # Only an explicit y ships — ask re-asks until it gets y or n, so neither an
  # unattended Enter nor one left over from the wait can. This is the whole of
  # the protection available: the repository is private on a free plan, where
  # branch protection and rulesets are refused, so the merge itself cannot be
  # held back — only the deploy that would follow it.
  # The project's say in the question (project_ship_mode): `auto` ships
  # without the plain one — the "anyway" ones below are still asked, since a
  # gate was passed over and nobody said yes to that — and `off` never ships.
  local prod_note prod_ask ship_mode
  ship_mode="$(project_ship_mode "$wt")"
  if [[ "$merged_unchecked" -eq 1 ]]; then
    prod_note="Merged as a change nothing deploys, but it carried more — no regression, preview or QA ran on it."
    prod_ask="Ship to production anyway?"
  elif [[ "$qa_skipped" -eq 1 ]]; then
    prod_note="Merged before this preview run went green — nobody passed it through '$QA_TO'."
    prod_ask="Ship to production anyway?"
  else
    prod_note=""
    prod_ask="Ship to production?"
    [[ "$ship_mode" == auto ]] && prod_ask=""
  fi
  # Production red with an earlier release of this feature (a fix sent forward
  # by `return`): the question says so, so that a "no", which closes the
  # issue, is not given without knowing it. Apart from prod_note, whose
  # defaults below say what the block does with migrations. Not after a
  # rollback: production serves the release before, checked green on its own
  # stage, while the feature's status stays the red it was rolled back for.
  local prod_red=""
  if [[ "$(regression_status "$wt" prod)" == failed \
        && "$(state_get "$wt/.sclaude/local/feature/state.json" rollback.prod.code 2>/dev/null || true)" != "done" ]]; then
    prod_red="Production's last regression was red — this ships the fix. "
  fi

  # As with preview: when main is what production already has (deploy_unchanged
  # says when) there is nothing here to decide. Said and
  # not asked — and unlike preview there is no second door, by design: shipping
  # an unchanged main to prod is not a thing anybody needs a shortcut for, and
  # `vercel --prod` from $REPO is the honest way to do it deliberately.

  # What a rollback would need, recorded while it can still be worked out.
  #
  # Both answers move the moment the block below runs. The deployment now
  # serving production is exactly the one this ship is about to displace —
  # afterwards, telling it from ours means picking a row by position, which is
  # how a rollback goes to the wrong release. And the branch's migrations are
  # `origin/main...HEAD`, a range that empties the instant `git pull` brings the
  # merge down: a rollback asking it later is told there is nothing to reverse,
  # confidently and every time.
  #
  # Both are best-effort and silent: a note that could not be filed costs a
  # rollback its certainty, never the deploy.
  #
  # Then main in the main tree is checked (prod_main_unready): a stop there
  # leaves the issue open and the tree in place, so the same command picks
  # production up once main is level, and is not a decline. Then what rides
  # along, whose fetch of main empties the range rollback_remember_migrations
  # reads — so in this order. See prod_riders.py: on 2026-10-09 one feature
  # shipped another's migration without a word about it.
  # Asked once: main on origin may move between two askings, and a second
  # answer of "changed" would ship past what only the first one's branch
  # records and checks.
  local riders="" rider_issues="" prod_same=0 ship_rc=0
  deploy_unchanged "$wt" prod && prod_same=1
  if [[ "$prod_same" -eq 0 && "$ship_mode" != off ]]; then
    rollback_remember_previous "$wt"
    [[ -n "$migrations" ]] && rollback_remember_migrations "$wt"

    if prod_main_unready "$REPO"; then
      cycle_edge "$wt" ship epilogue sclaude "main in the main tree" note="not ready to ship from"
      info "  Then run: $SELF $slug"
      run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" 0 "$wt"
      return 0
    fi

    riders="$(prod_riders "$wt" "$slug")"
    prod_riders_say "$riders"
    # ship: auto spares the question about this feature alone: what rides
    # along with it is other features' code, which nobody said yes to.
    [[ -z "$prod_ask" && -n "${riders//[[:space:]]/}" ]] && prod_ask="Ship to production, with what rides along?"
    rider_issues="$(awk -F'\t' '$1 == "feature" && $3 != "-" { gsub(",", " ", $3); print $3 }' \
      <<< "$riders" | tr '\n' ' ')"
    # Their migrations go to production with the code that needs them: a ship
    # that only this branch would have done without a promote still needs one.
    if [[ -z "$migrations" ]] \
       && awk -F'\t' '$1 == "feature" && $5 != "-" { found = 1 } END { exit !found }' <<< "$riders"; then
      migrations=1
      prod_note="${prod_note:-The branch adds no migrations, but what ships with it does: promote first, then ship.}"
    fi
  fi

  # The question and the ship it leads to: the process map stands the feature
  # on them meanwhile (position in process_position.py), however long the answer takes
  # — it may come from the phone the next morning. Taken off below once
  # answered, yes or no; kept when nobody answered, since the question still
  # stands, and taken off by the next pass, which asks it again (as when this
  # one is cut off at the question).
  [[ "$prod_same" -eq 0 && "$ship_mode" != off ]] \
    && { state_set "$wt/.sclaude/local/feature/state.json" prod_pass.shipping "$(date -Iseconds)" 2>/dev/null || true; }
  if [[ "$prod_same" -eq 1 ]]; then
    echo ""
    info "Production already at $(deploy_head "$wt" prod | cut -c1-8) — unchanged, skipping."
  elif [[ "$ship_mode" == off ]]; then
    echo ""
    info "Production: not deployed — ship is off in .sclaude/config.json."
    info "  Ship it by hand when you choose: cd $REPO && vercel --prod"
  elif [[ -n "$migrations" ]]; then
    # The promote's own commands come from the project: which script applies
    # migrations to production, which paths hold them and the schema snapshot,
    # and how the tree is put back on dev afterwards. They were this product's
    # npm scripts written into the orchestrator, so a repository that promoted
    # differently could not be shipped from here at all.
    #
    # A project with migrations and no promote command is a gap worth saying out
    # loud rather than papering over with a guess: the block is assembled from
    # what is declared, and a missing promote leaves the migrations unshipped
    # where a guessed one would run something nobody named.
    local -a prod_cmds=("cd $REPO" "git pull --ff-only --autostash")
    local promote_cmd schema_path
    promote_cmd="$(project_get database.promote "$wt" || true)"
    schema_path="$(project_get database.schemaFile "$wt" || true)"
    if [[ -n "$promote_cmd" ]]; then
      prod_cmds+=("$promote_cmd")
      prod_cmds+=("git add $migrations_dir${schema_path:+ $schema_path}")
      # Only with something to commit: a promote of what production has
      # already (an earlier run's record, a rider's) changes no file, and a
      # bare `git commit` then failed the block before `vercel --prod`.
      prod_cmds+=("git diff --cached --quiet || git commit -m 'chore(db): promote migrations for $slug'")
      prod_cmds+=("git push")
    else
      warn "  The branch adds migrations and the project names no promote command."
      info "  They will not be applied to production by this block; .sclaude/config.json"
      info "  describes it under database.promote."
    fi
    prod_cmds+=("vercel --prod")
    # What production uploads is the main tree, and sclaude keeps its own
    # folder there (scratch.sh).
    write_vercelignore "$REPO"
    # A promote may switch the main tree to production. It is put back
    # exactly as it was (environment_snapshot), by name it could not when
    # .env.local is no declared environment, and outside the block: the block
    # stops at its first failure, and a promote that failed halfway is when
    # the tree is most likely left on production.
    local snapshot=""
    [[ -n "$promote_cmd" ]] && snapshot="$(environment_snapshot "$REPO")"

    if SCLAUDE_BLOCK_AT="$wt/.sclaude/local/feature/deploy.at" run_block \
      "Production" \
      "$prod_red${prod_note:-The branch adds migrations: promote first, then ship.}" \
      "$prod_ask" \
      "${prod_cmds[@]}"; then
      prod_done=1
      deploy_remember "$wt" prod
    else
      ship_rc=$?
      case $ship_rc in 2) prod_tried=1 ;; 3) prod_unanswered=1 ;; esac
    fi
    if [[ -n "$snapshot" ]]; then
      environment_restore "$REPO" "$snapshot" \
        || warn "  could not put the main tree's environment back — check: readlink $REPO/.env.local"
    fi
  else
    write_vercelignore "$REPO"
    if SCLAUDE_BLOCK_AT="$wt/.sclaude/local/feature/deploy.at" run_block \
      "Production" \
      "$prod_red${prod_note:-The branch adds no migrations.}" \
      "$prod_ask" \
      "cd $REPO" \
      "git pull --ff-only --autostash" \
      "vercel --prod"; then
      prod_done=1
      deploy_remember "$wt" prod
    else
      ship_rc=$?
      case $ship_rc in 2) prod_tried=1 ;; 3) prod_unanswered=1 ;; esac
    fi
  fi

  # The way out of the question, for the history: the person's answer, the
  # project's ship setting, or nobody's.
  if [[ "$prod_same" -eq 0 && "$ship_mode" == off ]]; then
    cycle_edge "$wt" ship epilogue setting "ship=off"
  elif [[ "$prod_same" -eq 0 ]]; then
    local ship_by=person ship_how="$ASKED_HOW"
    [[ -z "$prod_ask" ]] && ship_by=setting ship_how="ship=auto"
    case "$ship_rc" in
      0|2) cycle_edge "$wt" ship prod "$ship_by" "$ship_how" ;;
      1)   cycle_edge "$wt" ship epilogue person "$ASKED_HOW" ;;
      3)   cycle_edge "$wt" ship epilogue none "" ;;
    esac
  fi

  # Unanswered, the question still stands: the map keeps the feature on it.
  [[ "$prod_unanswered" -eq 1 ]] \
    || state_set "$wt/.sclaude/local/feature/state.json" prod_pass.shipping null 2>/dev/null || true

  # Production starts with a question, which reaches the phone by itself:
  # the topic hears only how it ended.
  if [[ "$prod_done" -eq 1 ]]; then
    state_set "$wt/.sclaude/local/feature/state.json" regression.prod.deploy_failed null 2>/dev/null || true
    history_add "$wt/.sclaude/local/feature/state.json" deploy.prod done
    local prod_url; prod_url="$(project_prod_url "$wt" 2>/dev/null || true)"
    ask_feed say "$(phase_line finished deploy production)${prod_url:+ · $prod_url}"
  elif [[ "$prod_tried" -eq 1 ]]; then
    history_add "$wt/.sclaude/local/feature/state.json" deploy.prod failed
    ask_feed alarm "$(phase_line failed deploy production) · the log is in the terminal"
  fi

  # A ship that was tried and failed is not a "no": it went on to close the
  # issue as declined, the epilogue saying so, and the clean-up. It stops
  # here, the issue held open, for another try, and the main local database
  # brought level with whatever the promote already put on main. No epilogue:
  # its status has no word for a failed ship — "merged, not in production",
  # which the issue says already, is true — and its session would push the
  # failing command's output off the screen above the warning.
  if [[ "$prod_tried" -eq 1 ]]; then
    db_main_up
    echo ""
    warn "The ship to production failed — see above. Nothing is closed or cleaned up."
    local failed; failed="$(cat "$wt/.sclaude/local/feature/deploy.at" 2>/dev/null)"
    rm -f "$wt/.sclaude/local/feature/deploy.at"
    local began=""
    [[ -n "${promote_cmd:-}" && -n "$failed" && "$failed" != "cd $REPO" && "$failed" != git\ pull* ]] && began=1
    cycle_edge "$wt" prod review sclaude "the ship failed" note="at: ${failed:-?}"
    ship_failed "$wt" "$slug" "$failed" "$began"
    return $?
  fi

  # Nobody answered the question (the terminal gone, the phone silent): not
  # a no, which closes the issue as declined and cleans up. The issue stays
  # open and the next `sclaude <feature>` asks again (remind_prod, after
  # every step).
  if [[ "$prod_unanswered" -eq 1 ]]; then
    echo ""
    warn "Nobody answered whether to ship to production. Nothing is closed or cleaned up."
    info "  Asked again with: $SELF $slug"
    ask_feed say "$(phase_line ended deploy production) · nobody answered: asked again at the next $SELF $slug"
    # The issue hears of the merge this pass made, as at the other stop
    # before production (prod_main_unready).
    run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" 0 "$wt"
    return 0
  fi

  # The features that went out with this one are in production too, and their
  # issues say so. Labels only: their issues were closed by their own cycles.
  if [[ "$prod_done" -eq 1 && -n "${rider_issues// /}" ]]; then
    local rider_repo; rider_repo="$(gh_repo 2>/dev/null || true)"
    if [[ -n "$rider_repo" ]]; then
      ensure_deploy_label "$rider_repo" deployed-prod 0e8a16 "Live in production"
      apply_deploy_labels "$rider_repo" "deployed-preview deployed-prod" "$rider_issues"
      info "  Marked deployed-prod as well, shipped with this one:$(printf ' #%s' $rider_issues)"
    fi
  fi

  # The production regression: read-only, against the address the project itself
  # calls production. It runs before the clean-up so that a failure still has a
  # worktree to be fixed in — and after the deploy, because what it checks is
  # the deployment.
  if [[ "$prod_done" -eq 1 ]]; then
    # `regression_run`, not `regression_gate`, and this is the whole of the
    # difference between prod and every other stage.
    #
    # The gate's loop is: run, and on red open a fixing session, up to two of
    # them, then run again. That is right for local and preview, where nobody is
    # looking at the deployment and the only cost of a red run is time. Here it
    # meant two Opus sessions — minutes each — against a live broken production,
    # with the mark on the issue saying so and nothing doing anything about it.
    #
    # So the order is reversed: production is restored first, and only then is
    # anything fixed. regression_rewind at the end puts the cycle back on the
    # review step, where the fixing session belongs — and by then it runs against
    # a production that works.
    # This release's suite has not run yet: a red recorded of the one before
    # (held, then fixed forward) must not hold this one if its run says 2.
    state_set "$wt/.sclaude/local/feature/state.json" regression.prod.intruded null 2>/dev/null || true
    state_set "$wt/.sclaude/local/feature/state.json" regression.prod.status null 2>/dev/null || true
    state_set "$wt/.sclaude/local/feature/state.json" regression.prod.unrunnable null 2>/dev/null || true
    regression_run "$wt" "$slug" prod
    local prod_rc=$?

    # Red, but was it this feature? A production deploy made by somebody else
    # during the run means the suite was looking at a moving target, and the
    # rollback below would take their release away too (see
    # regression_deploy_intruded). So the run is repeated once against what is
    # serving now, and if it is still red nothing is rolled back automatically:
    # the release on top is not ours to remove.
    local intruders="" intruded=0
    if [[ "$prod_rc" -eq 1 ]]; then
      intruders="$(regression_deploy_intruded prod \
        "$(state_get "$wt/.sclaude/local/feature/state.json" regression.prod.started 2>/dev/null || true)" \
        "$(state_get "$wt/.sclaude/local/feature/state.json" regression.prod.finished 2>/dev/null || true)")" \
        && intruded=1
    fi
    if [[ "$intruded" -eq 1 ]]; then
      state_set "$wt/.sclaude/local/feature/state.json" regression.prod.intruded \
        "$(cut -f1 <<< "$intruders" | paste -sd' ')" 2>/dev/null || true
      echo ""
      warn "Production was deployed again while its regression was running:"
      while IFS=$'\t' read -r url created; do
        info "  $url"
      done <<< "$intruders"
      info "  The red may not be this feature's. Running the suite once more"
      info "  against what production serves now."
      regression_run "$wt" "$slug" prod
      prod_rc=$?
      if [[ "$prod_rc" -eq 1 ]]; then
        run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt" 0 1
        echo ""
        warn "Production is still red, and another release now sits on top of this one."
        cycle_edge "$wt" prod_ok hold_ways sclaude "red again" stage=prod note="another release on top: not rolled back"
        cycle_edge "$wt" prod epilogue sclaude "production regression" note="red, another release on top: not rolled back"
        info "  Nothing was rolled back: going back to the release before this"
        info "  feature would remove that one too. Look at the log, talk to whoever"
        info "  deployed it, and roll back by hand if it is this feature's:"
        info "    $SELF rollback $slug"
        info "  The worktree stays: $wt"
        return 0
      fi
    fi

    if [[ "$prod_rc" -eq 0 ]]; then
      # Green on the repeat after another release landed: that release is no
      # longer a reason for anything.
      state_set "$wt/.sclaude/local/feature/state.json" regression.prod.intruded null 2>/dev/null || true
      state_set "$wt/.sclaude/local/feature/state.json" regression.prod.attempts 0 2>/dev/null || true
      regression_clear_mark "$wt" prod
    elif [[ "$prod_rc" -eq 2 ]] && project_prod_suite_declined "$wt"; then
      # No suite for production by the project's word — `prodRegression:
      # none`, or no list declared — said by regression_run, and not a suite
      # that failed to run (project_prod_suite_declined: an unreadable config
      # empties the list too, and must not drop a red). The cycle goes on to its end, the
      # retrospective and the clean-up; a red mark left by an earlier run
      # comes off, since nothing will ever run to take it off.
      regression_clear_mark "$wt" prod
    elif [[ "$prod_rc" -eq 2 ]]; then
      # The stage could not run at all — no address to aim at, nothing served.
      # A rollback is not the answer to a suite that never ran: the deployment
      # we would go back to may be the one that is not answering.
      run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt" 0 1
      echo ""
      cycle_edge "$wt" prod epilogue sclaude "production regression" note="the suite could not run"
      warn "The production regression could not run — see above."
      info "  Nothing was rolled back: a suite that did not run says nothing"
      info "  about what is serving production."
      info "  The worktree stays: $wt"
      info "  Carry on with: $SELF $slug"
      return 0
    else
      # Red. Production goes back before anything else happens.
      cycle_edge "$wt" prod_ok rollback sclaude "red" stage=prod
      rollback_prod "$wt" "$slug" --auto
      local rb_rc=$?
      [[ "$rb_rc" -ne 0 ]] && cycle_edge "$wt" rollback hold_ways sclaude "the rollback failed" stage=prod

      # prod_done stays 1 and `deployed-prod` goes on: the code did reach
      # production, which is the whole of what that label says, and it is true
      # whatever the suite then found. What the label cannot say is that
      # production is broken right now — so the red mark says it, and
      # clear_regression_label takes it off when the stage next comes back
      # green. The preview keeps its own value: its suite passed in this same
      # run, and withdrawing a label it earned would be a second inaccuracy
      # covering the first.
      run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt" 0 1

      if [[ "$rb_rc" -ne 0 ]]; then
        cycle_edge "$wt" prod epilogue sclaude "production regression" note="red, not rolled back"
        echo ""
        warn "Production is broken and could not be rolled back."
        info "  Read what it said above and put it back by hand; the worktree and"
        info "  the branch stay where they are."
        info "  The worktree: $wt"
        info "  Carry on with: $SELF $slug"
        return 0
      fi

      rollback_confirm "$wt" "$slug"
      rollback_incident "$wt" "$slug" "$issue"

      echo ""
      warn "Production regression was red — production has been rolled back."
      info "  The feature is not in production; the release before it is."
      info "  The fix carries on from the review step, in this same tree, and"
      info "  goes the whole way round again: local suite, merge, preview and"
      info "  its suite, then production."
      info "  The worktree stays: $wt"
      info "  Carry on with: $SELF $slug"
      cycle_edge "$wt" prod review sclaude "production regression" note="red: rolled back"
      regression_rewind "$wt" "$slug" prod
      return 0
    fi
  fi

  # The cycle is over here: every red or unrunnable production regression
  # returned above (one the project declares none of is neither). So the issue closes — whether production carries the
  # feature or the human declined to ship it. A declined production used to
  # leave the issue open, and nothing ever came back to close it: one issue
  # stayed open, merged and accepted, after its production question was
  # answered no. Shipping later is `vercel --prod` from the repository, which
  # needs no open issue.
  #
  # Before the epilogue, not after it: issue_hold_open kept the issue open
  # until now, and an epilogue that read it open wrote "still open" of a
  # feature about to close — and the closed, deployed-prod case status.md
  # answers with no comment at all could never come up.
  local prod_live=0
  if [[ "$prod_done" -eq 1 ]]; then
    cycle_edge "$wt" prod epilogue sclaude "production regression" \
      note="$(project_prod_suite_declined "$wt" && echo "no suite for production" || echo green)"
  fi
  if [[ "$prod_done" -eq 1 || "$carried" -eq 1 ]]; then
    prod_live=1
    if project_prod_suite_declined "$wt"; then
      issue_close_done "$issue" nosuite
    else
      issue_close_done "$issue" shipped
    fi
  elif [[ "$ship_mode" == off ]]; then
    issue_close_done "$issue" shipoff
  else
    issue_close_done "$issue" declined
  fi

  # The outcome into the issue and its parents, before the clean-up: until this
  # line it is not known whether the feature made it to prod, and "where it is
  # now" is half of what the section exists for.
  #
  # Production as it stands, not as this run shipped it — as preview_live is
  # for the preview. Given prod_done, a pass after a declined clean-up, with
  # production already there, described a different outcome from the pass
  # that shipped it: the fingerprint missed, and a second epilogue rewrote the
  # same status.
  # Nobody did QA: the issue's demo is brought up to the code here, for its
  # record, before the epilogue writes the issue's last word.
  [[ "$(project_flow_mode qa "$wt")" == auto ]] && demo_refresh "$wt" epilogue
  run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_live" "$wt"

  # The pass got here for this pull request and this production, the epilogue
  # run: opened again, the feature goes to the clean-up (cmd_resume). A new
  # ship, a second pull request or a pass cut off before here leaves it
  # standing apart.
  [[ "$prod_live" -eq 1 ]] && state_set "$wt/.sclaude/local/feature/state.json" prod_pass.ended \
    "$(prod_pass_mark "$wt")"

  # The merge is in main now, its migrations too, and the main local database
  # is what the next feature's stack is filled from (db_main_up).
  db_main_up

  # And only now the clean-up. It checks the merge against GitHub, shows what
  # exactly will disappear, and asks — once. There is deliberately no question
  # of our own here: asking before it would mean asking twice about the same
  # thing, and only it shows the list of what will be deleted, so its question
  # is the informed one. A refusal differs from agreement by the exit code —
  # only so as to hint at what this will continue with.
  #
  # A feature whose production regression failed keeps its tree either way: the
  # human answering "no" here is what the fixing session needs, and the hint
  # below is the way back.
  if ! cmd_done "$slug"; then
    info "Later: $SELF done $slug"
  fi
}
