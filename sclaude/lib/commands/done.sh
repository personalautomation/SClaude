#!/usr/bin/env bash
#
# `sclaude done`: closing a merged feature — its tree, its branch, its traces.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The clean-up of a feature in a sclaude process of its own, for cmd_done
# when sclaude's code changed under it: the running bash holds the old code
# while every Python helper it calls is read anew from disk. It used to stop
# there and print the command, and the person who typed a different one
# instead went back through production and the epilogue for nothing. Given
# `retro`, the retrospective already ran here: the fresh run does not ask
# again whether to go back into it. Its start-up leaves the checkout alone
# (SCLAUDE_SYNCED): this run has just seen it move.
#
#   done_fresh <slug> [retro]
done_fresh() {
  echo ""
  say "${BOLD}sclaude's own code changed under this run; the clean-up goes on in a fresh one ($SELF done $1).${OFF}"
  SCLAUDE_SYNCED=1 SCLAUDE_DONE_RETRO_RAN="${2:-}" "$INSTRUMENTS/bin/sclaude" _done "$1"
}

cmd_done() {
  require_repo
  local slug="${1:-}" wt branch merged pr answer
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  # From done_fresh, once: a step this run resumes and the clean-up of a
  # later round hold their retrospective as usual.
  local retro_ran_here="${SCLAUDE_DONE_RETRO_RAN:-}"
  unset SCLAUDE_DONE_RETRO_RAN
  [[ -n "$slug" ]] || die "name the feature: $SELF done <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"
  branch="$(state_get "$wt/.sclaude/local/feature/state.json" branch)" || die "the state carries no branch"
  # The retrospective and the clean-up come after any ship: a ship question
  # a pass cut off left marked is not pending any more (position).
  state_set "$wt/.sclaude/local/feature/state.json" prod_pass.shipping null 2>/dev/null || true

  IFS=$'\t' read -r merged pr < <(gh pr view "$branch" --repo "$(git -C "$REPO" remote get-url origin)" \
    --json state,number --jq '[.state, .number] | @tsv' 2>/dev/null) || true
  local no_change; no_change="$(state_get "$wt/.sclaude/local/feature/state.json" no_change 2>/dev/null || true)"
  # A feature built in parts (parts.sh): its parts' branches go with it,
  # read now — the state goes with the tree.
  local part_branches=""
  declare -F parts_branches >/dev/null && part_branches="$(parts_branches "$wt/.sclaude/local/feature/state.json")"
  local issue; issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue 2>/dev/null || true)"
  [[ "$no_change" == "true" || "$merged" == "MERGED" ]] \
    || die "the PR for $branch is not merged (state: ${merged:-not found}). Cleaning up comes after the merge."

  # The retrospective, while everything it reads is still here (retro.sh). Before
  # the list below rather than after it, so the list stands right above the
  # question it belongs to.
  #
  # A feature with no change of its own has one too: such a feature may have
  # done all of its work elsewhere — once, all of it in sclaude's own checkout —
  # and skipping the retrospective there skipped the one look back it had.
  # What a session left in the feature's workshop gets its last chance before
  # the clean-up takes the workshop — offered back, or tried again — and
  # before the retrospective, which then runs with the fix. The retrospective's
  # own unfinished change is asked about as it ends (workshop_after_session).
  local live_before; live_before="$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null || true)"
  # Friction no review has read goes first: the retrospective reads the logs,
  # and the clean-up removes them (friction_before_retro). After live_before,
  # so that what such a review publishes to sclaude counts below too. Run in
  # the fresh run after a retrospective (done_fresh) as well, where the log
  # may hold the retrospective's own entries. A retrospective that ran in this
  # process and published nothing is cleaned up after with its own entries
  # unread, as it was before this check.
  # The way here, once: `sclaude done` typed, or the cycle's end calling it.
  if [[ "${SCLAUDE_COMMAND:-}" == done ]]; then
    once_edge "$wt" epilogue done_cmd person "$SELF done"
  else
    once_edge "$wt" epilogue done_cmd sclaude "the epilogue ended"
  fi
  once_edge "$wt" done_cmd friction_left sclaude ""
  if ! friction_before_retro "$wt" "$slug"; then
    info "  The retrospective and the clean-up wait for it: $SELF done $slug"
    return 1
  fi
  once_edge "$wt" friction_left retro sclaude "no friction left unread"
  workshop_pending "$wt"
  # What it published moved sclaude's code: the retrospective, like the
  # clean-up below, runs in a fresh process, on the code it reads.
  if [[ "$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null || true)" != "$live_before" ]]; then
    done_fresh "$slug" "${retro_ran_here:+retro}"
    return
  fi

  if [[ -z "$retro_ran_here" ]]; then
    run_retro "$wt" "$slug" "$pr" "$issue"
    cycle_edge "$wt" retro retro_fix sclaude "the retrospective ended"
  fi
  # Said to a fresh run below, which then does not ask about it again: only a
  # retrospective that ran to its end, here or in the run before.
  local retro_flag=""
  if [[ -n "$retro_ran_here" ]] || retro_ran "$wt/.sclaude/local/feature/state.json"; then
    retro_flag=retro
  fi

  # sclaude's own code changed while the retrospective ran — what it published
  # from the workshop was brought into the checkout (workshop_live_update).
  # This process carries on in the old bash while every Python helper it calls
  # is read anew from disk, so the clean-up goes on in a run of its own, told
  # that the retrospective has just run.
  if [[ -n "${RETRO_INSTRUMENTS_CHANGED:-}" ]]; then
    done_fresh "$slug" "$retro_flag"
    return
  fi

  # A change to sclaude still in the workshop waits on the person's question
  # (workshop_decide): send, reopen or drop. Past here the workshop goes with
  # the tree, so the clean-up waits for the answer, which the next run asks
  # for again (workshop_pending, above).
  if [[ "$(workshop_state "$wt")" != none ]]; then
    warn "  The clean-up waits for sclaude's change in this tree's workshop: send, reopen or drop it — $SELF done $slug asks again."
    return 1
  fi

  # A retrospective that committed the feature's own work on a branch with no
  # change has given it a change: the feature goes to its pull-request step,
  # the way a merged one goes back there (retro_reopen).
  # Only for its commits: uncommitted work is no_change_settle's to refuse.
  local state="$wt/.sclaude/local/feature/state.json" retro_to
  retro_to="$(state_get "$state" retro.project_to 2>/dev/null || true)"
  if [[ "$no_change" == "true" && -n "$retro_to" && "$retro_to" != "null" ]] \
     && [[ -z "$(worktree_dirt "$wt")" ]] && ! no_change_feature "$wt" >/dev/null; then
    state_set "$state" no_change null
    cycle_edge "$wt" retro_fix pr sclaude "git" note="the feature now carries work of its own"
    step_rewind_to "$wt" pr pr review
    state_set "$state" steps.pr.session null 2>/dev/null || true
    # The watch on QA's earlier answer is spent, as in retro_reopen.
    watch_stop "$slug"
    issue_hold_open "$issue"
    issue_sync "$wt"
    echo ""
    say "${BOLD}'$slug' now carries work of its own on $branch — it goes on to step '$(step_title pr)' for it.${OFF}"
    cmd_resume "$slug"
    return 0
  fi

  # A feature with no change of its own has no pull request to wait for
  # (no_change.sh). What sclaude committed on its branch goes where it belongs
  # first: the branch is deleted below, and anything left on it with it.
  if [[ "$no_change" == "true" ]]; then
    local settled=0
    no_change_settle "$wt" || settled=$?
    (( settled == 2 )) \
      && die "nobody answered where the product changes on $branch go — the clean-up waits for it: $SELF done $slug"
    (( settled == 0 )) \
      || die "something sclaude committed on $branch did not reach main — the clean-up waits for it: $SELF done $slug"
  fi

  # Code the retrospective changed is not cleaned up with the feature: the feature
  # goes back to step 3 for it by itself, and through the review, the preview,
  # QA and the merge after it. The clean-up waits for that merge.
  local again=""
  [[ "$no_change" == "true" ]] || again="$(retro_changed_code "$wt" "$branch")"
  if [[ -n "$again" ]]; then
    cycle_edge "$wt" retro_fix pr sclaude "git" note="$again change(s) PR #$pr does not carry"
    retro_reopen "$wt" "$pr" "$slug" || die "could not reopen '$slug': see $wt/.sclaude/local/feature/state.json"
    echo ""
    say "${BOLD}The retrospective committed $again change(s) PR #$pr does not carry — '$slug' goes back to step '$(step_title pr)' for them.${OFF}"
    info "  The clean-up waits until their pull request is merged too: $SELF done $slug"
    cmd_resume "$slug"
    return 0
  fi

  cycle_edge "$wt" retro_fix cleanup sclaude "git" note="no code changed by the retrospective"

  # The feature is closed, so it is cleared away whole, with one question.
  # Splitting it into three would mean asking about parts of what the human has
  # already agreed to.
  #
  # Pruned first: GitHub may have deleted the branch at the merge, and a stale
  # origin/<branch> would put a branch on this list that is not there — and
  # then fail to delete it.
  git -C "$REPO" fetch origin --prune >/dev/null 2>&1
  local remote=0
  git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$branch" && remote=1

  echo ""
  echo "This will be removed:"
  echo "  worktree  $wt"
  echo "  branch    $branch"
  [[ "$remote" -eq 1 ]] && echo "  branch    origin/$branch"

  # A copy of the PR fetched for reading — `git fetch origin pull/N/head:prN` —
  # is the same work under another name, and nothing else ever removes it: the
  # next sclaude would ask about it on its own. It goes with the feature only
  # when everything it holds is already in origin/main; otherwise it is left
  # for the branch sort-out, which shows it and asks.
  local copy=""
  if [[ -n "$pr" ]] && git -C "$REPO" show-ref --verify --quiet "refs/heads/pr$pr" \
      && git -C "$REPO" merge-base --is-ancestor "pr$pr" origin/main 2>/dev/null; then
    copy="pr$pr"
    echo "  branch    $copy  (a local copy of PR #$pr, nothing new in it)"
  fi

  # The only thing that deserves a mention of its own is uncommitted work: it
  # exists only here and will disappear for good.
  local dirty; dirty="$(worktree_dirt "$wt")"
  if [[ -n "$dirty" ]]; then
    echo ""
    warn "Uncommitted work will go with them:"
    printf '%s\n' "$dirty"
  fi

  # An unreviewed friction log is the second thing that exists only here.
  # worktree_dirt says nothing about it: .sclaude/local/feature/ is hidden from git, and by
  # construction it is not in the list of uncommitted changes. So we say it
  # separately —
  # analysis that has already been paid for must not disappear unmentioned.
  local fcount; fcount="$(friction_count "$wt" || true)"
  if [[ -n "$fcount" && "$fcount" != "0" ]]; then
    echo ""
    warn "$fcount unreviewed friction entry(ies) will go with them."
    info "  Review them first: $SELF friction $slug"
  fi

  echo ""
  # Returning 1 on a refusal is not an error but an answer: the epilogue decides
  # by it whether to mention `sclaude done`. For a direct call from the terminal
  # the exit code means nothing, everything there is said in words.
  local clean_by=person
  ask "${BOLD}Remove all of it? [y/n] ${OFF}" answer yn || clean_by=none
  if ! is_yes "$answer"; then
    cycle_edge "$wt" cleanup kept "$clean_by" "$ASKED_HOW"
    info "Cancelled."
    return 1
  fi
  # Written for its run's own record: the tree, and its history with it, goes below.
  cycle_edge "$wt" cleanup end person "$ASKED_HOW"

  # The side worktrees' questions, right after the agreement and before
  # anything is done: they are the feature's last (its topic in the bot goes
  # with its worktree), and they may wait long for an answer — a person who
  # leaves one unanswered leaves the feature as it was, not half cleaned.
  side_worktrees_offer

  # We append the summary before the clean-up: state.json lives inside the
  # worktree and will disappear with it, and there will be nothing left to
  # assemble it from.
  state_set "$wt/.sclaude/local/feature/state.json" cleaned true
  issue_sync "$wt"

  # And the cycle's own record, for the same reason and in the same window.
  # Everything the cycle measured about itself is in that file, and nothing has
  # ever outlived it: the questions it could answer — is the cycle getting
  # faster, which step holds it up, are two fixing attempts enough — have not
  # been askable at all.
  #
  # After issue_sync rather than before: that call writes the last thing the
  # state learns, and a record taken ahead of it would be missing it.
  metrics_append "$wt" done

  # The QA watch ends with the feature. Left behind, its file would have a timer
  # asking GitHub about a closed issue every five minutes for ever — and telling
  # somebody about it the next time a human touched that column.
  watch_stop "$slug"

  # We shut the server down after the agreement but before the directory is
  # removed: any earlier and a refusal would leave the human without a server;
  # any later and it would go on running in a worktree that does not exist,
  # holding the port.
  remove_worktree "$wt" || die "could not remove the worktree"

  # Never a plain -D: a squash-merged branch goes when its tip is the merged
  # PR's head, or its commits past it change nothing main lacks; any other
  # stays (branch_delete_merged).
  # Without a pull request there is no merged head to compare with: what the
  # branch held is on main already, or was dropped at no_change_settle.
  local kept=0
  if [[ "$no_change" == "true" ]]; then
    no_change_branch_delete "$branch" || kept=1
  else
    branch_delete_merged "$branch" || kept=$?
  fi
  if [[ "$kept" == 1 ]]; then
    warn "  local branch $branch kept: it carries commits that are not in main"
    warn "  to force it: git branch -D $branch"
  fi

  # Checked again right before -D: -D does not look at main itself, so the
  # ancestry test is the only thing standing between it and lost commits.
  if [[ -n "$copy" ]]; then
    if git -C "$REPO" merge-base --is-ancestor "$copy" origin/main 2>/dev/null; then
      git -C "$REPO" branch -D "$copy" >/dev/null 2>&1 \
        || warn "  could not delete the local branch $copy"
    else
      warn "  local branch $copy kept: it carries commits that are not in main"
    fi
  fi

  # push's output is muted: .githooks/pre-push does not tell deleting a branch
  # from an ordinary push and runs all the database checks, dumping their report
  # — which has nothing to do with the clean-up.
  if [[ "$remote" -eq 1 ]]; then
    git -C "$REPO" push origin --delete "$branch" >/dev/null 2>&1 \
      || warn "  could not delete origin/$branch"
  fi

  # The parts' branches: each one's pull request was squashed into the
  # feature's branch, so git cannot see them merged; GitHub's word that the
  # pull request merged is what lets them go.
  local part_branch
  while IFS= read -r part_branch; do
    [[ -n "$part_branch" ]] || continue
    [[ "$(branch_pr_state "$part_branch")" == MERGED ]] || {
      git -C "$REPO" rev-parse -q --verify "refs/heads/$part_branch" >/dev/null \
        && warn "  local branch $part_branch kept: its pull request is not merged"
      # Pushed before its review (parts_enter), it is on GitHub too.
      [[ -n "$(git -C "$REPO" ls-remote --heads origin "$part_branch" 2>/dev/null)" ]] \
        && warn "  origin/$part_branch kept: its pull request is not merged (git push origin --delete $part_branch)"
      continue
    }
    git -C "$REPO" branch -D "$part_branch" >/dev/null 2>&1 || true
    [[ -n "$(git -C "$REPO" ls-remote --heads origin "$part_branch" 2>/dev/null)" ]] \
      && { git -C "$REPO" push origin --delete "$part_branch" >/dev/null 2>&1 \
             || warn "  could not delete origin/$part_branch"; }
  done <<< "$part_branches"

  echo "${GREEN}Feature '$slug' cleaned up.${OFF}"
}
