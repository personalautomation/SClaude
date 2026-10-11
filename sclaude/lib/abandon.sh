#!/usr/bin/env bash
#
# Abandoning a started feature: removing all its traces — here and on GitHub.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- abandoning a feature ----------------------------------------------------
#
# `done` clears up after success: the PR is merged, the work is in main, all
# that is left is sweeping. Here it is the opposite — the work was decided
# against, and its traces live in five places at once: the worktree, the local
# branch, the branch in origin, the pull request, the issue. Forgetting any of
# them means leaving rubbish that will be remembered in a month and not
# understood.
#
# So one command for all five — but not one question for all five, as in `done`.
# There the human agrees to a clean-up after the merge, where there is nothing
# to lose; here every "yes" destroys something nobody asked to have destroyed,
# and their costs differ: a worktree with uncommitted work cannot be recovered
# by anything, whereas a closed issue can be reopened. So we ask before each
# action separately, and refusing one does not cancel the rest: sometimes the
# branches need tearing down while the issue stays.

# What the feature has to its name, one line per trace:
#
#   <kind>\t<what exactly>\t<explanation>
#
# The kinds: worktree, branch, remote, pr, issue. We print no empty lines — what
# does not exist has no place in the list.
#
# We gather everything before the first question: the human must see the whole
# picture before agreeing to the first piece. Asking "remove the worktree?"
# without showing that a branch, a PR and an issue stand behind it means leading
# them blind.
abandon_traces() {
  # `state` on a line of its own, and this is a fix rather than a style: bash
  # assigns a `local` list left to right and does not see a name from the same
  # command, so `local wt="$1" state="$wt/.sclaude/local/feature/state.json"` set `state` to
  # `/.sclaude/local/feature/state.json`. state_get answered nothing for every field, and the
  # table that stands in front of an irreversible deletion showed the worktree
  # and no branch, no PR, no issue — the very "leading them blind" the comment
  # above says this function exists to prevent.
  local wt="$1"
  local state="$wt/.sclaude/local/feature/state.json"
  local branch issue pr repo dirty pr_state issue_state

  branch="$(state_get "$state" branch || true)"
  issue="$(state_get "$state" issue || true)"
  pr="$(state_get "$state" pr || true)"
  [[ "$issue" == "null" ]] && issue=""
  [[ "$pr" == "null" ]] && pr=""

  dirty="$(worktree_dirt "$wt")"
  if [[ -n "$dirty" ]]; then
    printf 'worktree\t%s\t%s\n' "$wt" \
      "$(wc -l <<< "$dirty") uncommitted change(s) — they exist nowhere else"
  else
    printf 'worktree\t%s\t%s\n' "$wt" "the feature's working tree"
  fi

  # The friction log disappears with the tree, and worktree_dirt will not
  # mention it: .sclaude/local/feature/ is hidden from git. As a separate line — but not a
  # separate question: it lies inside the worktree, and the same "yes" carries
  # it away.
  local fcount; fcount="$(friction_count "$wt" || true)"
  if [[ -n "$fcount" && "$fcount" != "0" ]]; then
    printf 'friction\t%s entry(ies)\t%s\n' "$fcount" \
      "unreviewed — goes with the worktree, review it before saying yes"
  fi

  if [[ -n "$branch" ]]; then
    local ahead=""
    ahead="$(git -C "$REPO" rev-list --count "origin/main..$branch" 2>/dev/null)" || ahead=""
    if git -C "$REPO" show-ref --verify --quiet "refs/heads/$branch"; then
      printf 'branch\t%s\t%s\n' "$branch" \
        "${ahead:-?} commit(s) of its own"
    fi
    if git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
      printf 'remote\torigin/%s\t%s\n' "$branch" "pushed to GitHub"
    fi
  fi

  # We ask GitHub about the PR and the issue rather than trusting the state:
  # between the record and this minute they may have been closed by hand, and
  # offering to close what is closed is noise the human learns to answer without
  # looking.
  repo="$(gh_repo)" || repo=""
  if [[ -n "$repo" ]] && command -v gh >/dev/null 2>&1; then
    # We look for the PR by branch even when the number is recorded: step 3 may
    # not have reached capture_pr, and a branch with an open PR does not stop
    # having one because of that.
    if [[ -z "$pr" && -n "$branch" ]]; then
      pr="$(gh pr list --repo "$repo" --head "$branch" --state open --limit 1 \
              --json number --jq '.[0].number' 2>/dev/null)" || pr=""
    fi
    if [[ -n "$pr" ]]; then
      pr_state="$(gh pr view "$pr" --repo "$repo" --json state --jq .state 2>/dev/null)" || pr_state=""
      case "$pr_state" in
        OPEN)   printf 'pr\t#%s\t%s\n' "$pr" "open — will be closed, not deleted" ;;
        MERGED) printf 'pr\t#%s\t%s\n' "$pr" "already merged — left alone" ;;
        CLOSED) printf 'pr\t#%s\t%s\n' "$pr" "already closed — nothing to do" ;;
      esac
    fi
    if [[ -n "$issue" ]]; then
      issue_state="$(gh issue view "$issue" --repo "$repo" --json state --jq .state 2>/dev/null)" || issue_state=""
      case "$issue_state" in
        OPEN)   printf 'issue\t#%s\t%s\n' "$issue" "open — will be closed as not planned" ;;
        CLOSED) printf 'issue\t#%s\t%s\n' "$issue" "already closed — nothing to do" ;;
      esac
    fi
  fi
}

# Shows the picture and asks about each trace separately.
#
# The return is always 0: refusing every question is an answer rather than a
# failure, and the menu behind it must not complain.
cmd_abandon() {
  require_repo
  local slug="${1:-}" wt state traces answer
  [[ -n "$slug" ]] || die "name the feature: $SELF drop <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"

  # Everything needed from the state is read now, in one go. state.json lies
  # inside the worktree and disappears with it on the very first agreement —
  # while the questions about the PR and the issue come after. While they were
  # read in place, they silently came back empty, and an abandoned feature left
  # an open PR and an open issue behind it: precisely the traces this command is
  # written for.
  local branch issue pr repo
  branch="$(state_get "$state" branch || true)"
  issue="$(state_get "$state" issue || true)"
  pr="$(state_get "$state" pr || true)"
  [[ "$issue" == "null" ]] && issue=""
  [[ "$pr" == "null" ]] && pr=""
  repo="$(gh_repo)" || repo=""

  echo ""
  info "Looking at what feature '$slug' has left around…"
  traces="$(abandon_traces "$wt")"

  echo ""
  echo "${BOLD}Feature '$slug' — everything it has:${OFF}"
  local table="" kind what why
  while IFS=$'\t' read -r kind what why; do
    [[ -z "$kind" ]] && continue
    table+="  $kind"$'\t'"$what"$'\t'"$why"$'\n'
  done <<< "$traces"
  align_columns "$table"

  echo ""
  warn "None of this comes back. Each step below is asked separately."

  # The order runs from the irreversible to the reversible. A human who changes
  # their mind partway down the list loses less than if the issue had been closed
  # first while the worktree with the work stayed hanging without it.

  # --- uncommitted work --------------------------------------------------
  local dirty; dirty="$(worktree_dirt "$wt")"
  if [[ -n "$dirty" ]]; then
    echo ""
    warn "Uncommitted work in $wt:"
    printf '%s\n' "$dirty"
  fi

  # --- worktree ----------------------------------------------------------
  #
  # We shut the dev server down only along with the tree: it was started for it,
  # and there is no reason to leave it holding a port in a deleted directory. If
  # the tree is kept, we do not touch the server either: the work goes on.
  local wt_gone=0
  echo ""
  ask "${BOLD}Remove the worktree $wt? [y/n] ${OFF}" answer yn
  if is_yes "$answer"; then
    # The cycle's record, while there is still a state to read it from. Here
    # rather than at the top of the command because the tree may well be kept:
    # a feature whose worktree survives has not finished, and a record written
    # for it would be one more line saying a cycle ended when it had not.
    #
    # `dropped` rather than `done`, and the difference is the point. These
    # timings describe a decision to stop, not a cycle that ran its course, and
    # averaging the two together would make every abandoned feature look like a
    # fast one.
    metrics_append "$wt" dropped
    if remove_worktree "$wt"; then
      echo "  ${GREEN}removed${OFF} $wt"
      wt_gone=1
    else
      warn "  could not remove the worktree — leaving it and everything under it"
    fi
  else
    info "  worktree kept."
  fi

  # --- the local branch --------------------------------------------------
  #
  # Only after the tree is gone: git refuses to delete a branch that a live
  # worktree stands on, and without this the question would be asked in vain.
  if [[ -n "$branch" ]] && git -C "$REPO" show-ref --verify --quiet "refs/heads/$branch"; then
    echo ""
    if [[ "$wt_gone" -eq 0 ]]; then
      info "  local branch $branch kept: its worktree is still there."
    else
      ask "${BOLD}Delete the local branch $branch? [y/n] ${OFF}" answer yn
      if is_yes "$answer"; then
        # -D straight away: -d would refuse here almost always — an abandoned
        # branch is precisely one with commits that never reached main — and its
        # refusal would have to be re-asked with a second question about the same
        # thing. The human has already seen in the table how many commits the
        # branch has, and agreed to exactly that.
        if git -C "$REPO" branch -D "$branch" >/dev/null 2>&1; then
          echo "  ${GREEN}deleted${OFF} $branch"
        else
          warn "  could not delete $branch"
        fi
      else
        info "  local branch kept."
      fi
    fi
  fi

  # --- the branch in origin ----------------------------------------------
  if [[ -n "$branch" ]] \
     && git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo ""
    ask "${BOLD}Delete origin/$branch on GitHub? [y/n] ${OFF}" answer yn
    if is_yes "$answer"; then
      # The output is muted: .githooks/pre-push does not tell deleting a branch
      # from an ordinary push and dumps a report of checks that has nothing to do
      # with the deletion.
      if git -C "$REPO" push origin --delete "$branch" >/dev/null 2>&1; then
        echo "  ${GREEN}deleted${OFF} origin/$branch"
        git -C "$REPO" fetch origin --prune >/dev/null 2>&1
      else
        warn "  could not delete origin/$branch — the PR may still be holding it"
      fi
    else
      info "  origin/$branch kept."
    fi
  fi

  # --- the pull request --------------------------------------------------
  #
  # We close rather than delete: deleting a PR through the API is not possible at
  # all, and there is no need — a closed PR remains the history of the decision
  # not to do this work.
  if [[ -n "$repo" ]] && command -v gh >/dev/null 2>&1; then
    if [[ -z "$pr" && -n "$branch" ]]; then
      pr="$(gh pr list --repo "$repo" --head "$branch" --state open --limit 1 \
              --json number --jq '.[0].number' 2>/dev/null)" || pr=""
    fi
    if [[ -n "$pr" ]] \
       && [[ "$(gh pr view "$pr" --repo "$repo" --json state --jq .state 2>/dev/null)" == "OPEN" ]]; then
      echo ""
      ask "${BOLD}Close pull request #$pr? [y/n] ${OFF}" answer yn
      if is_yes "$answer"; then
        if gh pr close "$pr" --repo "$repo" \
             --comment "Closed: the feature was abandoned before the merge." \
             >/dev/null 2>&1; then
          echo "  ${GREEN}closed${OFF} PR #$pr"
        else
          warn "  could not close PR #$pr — close it by hand"
        fi
      else
        info "  PR #$pr kept open."
      fi
    fi
  fi

  # --- the issue ---------------------------------------------------------
  #
  # "Not planned" rather than "completed": the issue is closed because the work
  # was decided against, and in a milestone's report these two outcomes must not
  # look the same.
  if [[ -n "$repo" ]] && command -v gh >/dev/null 2>&1; then
    if [[ -n "$issue" ]] \
       && [[ "$(gh issue view "$issue" --repo "$repo" --json state --jq .state 2>/dev/null)" == "OPEN" ]]; then
      echo ""
      ask "${BOLD}Close issue #$issue as not planned? [y/n] ${OFF}" answer yn
      if is_yes "$answer"; then
        if gh issue close "$issue" --repo "$repo" --reason "not planned" \
             --comment "Closed: the feature was abandoned before the merge." \
             >/dev/null 2>&1; then
          echo "  ${GREEN}closed${OFF} issue #$issue"
        else
          warn "  could not close issue #$issue — close it by hand"
        fi
      else
        info "  issue #$issue kept open."
      fi
    fi
  fi

  # An abandoned feature's waiting epilogue is a trace of the same kind as the
  # branch and the PR: there is no reason to write "Current status" into an issue
  # closed as not planned. We do not make a question of it: the file is internal,
  # the human never created it and does not know about it, and the list above is
  # long enough as it is.
  #
  # Only along with the tree: if the tree stayed, the feature is in progress, and
  # all its state stays with it.
  [[ "$wt_gone" -eq 1 ]] && epilogue_forget "$slug"

  # The QA watch ends with the feature regardless of what happened to the tree:
  # abandoning it means nobody is waiting for QA on it any more, and a file left
  # behind would have the timer asking GitHub about it every five minutes for
  # ever.
  watch_stop "$slug"

  echo ""
  if [[ "$wt_gone" -eq 1 ]]; then
    echo "${GREEN}Feature '$slug' dropped.${OFF}"
  else
    info "Feature '$slug' is still in progress — its worktree stayed."
  fi
  return 0
}
