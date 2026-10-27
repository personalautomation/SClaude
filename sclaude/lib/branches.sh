#!/usr/bin/env bash
#
# Sorting out the local branches: which have nothing left to hold.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- branches with nothing left to hold --------------------------------------
#
# Branches pile up: the PR is merged, the work is in main, and the local branch
# stays hanging around. Two things say there is nothing left to hold — a merged
# PR and a remote branch that is gone (GitHub deletes it after a merge).
# Everything else is a question for the human rather than the script, so it is
# only displayed.

# A branch's PR state in one word: MERGED, CLOSED, OPEN, or empty when gh does
# not answer or there never was a PR. It costs a network request, so we ask only
# about branches that already look closed.
#
# PR_STATE_KNOWN set (cmd_flow, which has just asked): its answer, PR_STATE,
# rather than the same question again from each caller below it.
branch_pr_state() {
  if [[ -n "${PR_STATE_KNOWN:-}" ]]; then
    printf '%s\n' "${PR_STATE:-}"
    return 0
  fi
  gh pr list --head "$1" --state all --limit 1 --json state --jq '.[0].state' \
    2>/dev/null || true
}

# The head commit of the branch's merged PR, or empty when there is none or gh
# does not answer. A squash merge leaves the branch's commits out of main, so
# `git branch -d` refuses; a local tip equal to this commit says the refusal is
# a false alarm — everything the branch holds went into main through the PR.
merged_pr_head() {
  gh pr list --head "$1" --state merged --limit 1 --json headRefOid \
    --jq '.[0].headRefOid // empty' 2>/dev/null || true
}

# Deletes a local branch whose work is in main: `git branch -d`, and when git
# refuses, -D if the local tip is the head of the branch's merged pull request.
# A squash merge leaves the branch's commits out of main, so -d refuses every
# squash-merged branch; the matching head says nothing is lost. A branch with
# commits past its pull request is left alone.
#
#   branch_delete_merged <branch>  → 0 deleted, 2 deleted as squash-merged, 1 kept
branch_delete_merged() {
  local branch="$1" tip head
  git -C "$REPO" branch -d "$branch" >/dev/null 2>&1 && return 0
  tip="$(git -C "$REPO" rev-parse -q --verify "refs/heads/$branch" 2>/dev/null)" || return 1
  head="$(cd "$REPO" && merged_pr_head "$branch")"
  [[ -n "$head" && "$tip" == "$head" ]] || return 1
  git -C "$REPO" branch -D "$branch" >/dev/null 2>&1 && return 2
  return 1
}

# Sorts the local branches into buckets and prints a line per branch:
#
#   drop  <branch>  <reason>   — nothing left to hold, we offer to delete it
#   keep  <branch>  <reason>   — displayed, but not touched
#
# main and the current branch are not considered at all.
classify_branches() {
  local current merged_list branch state has_own wt
  # Without --prune the local refs/remotes/origin/* outlive branches that have
  # long been gone from GitHub, and the whole "the remote branch is gone" check
  # lies. A second of network; we skip silently when there is none.
  git -C "$REPO" fetch origin --prune -q 2>/dev/null || true
  current="$(git -C "$REPO" branch --show-current)"
  # The branches with no commits of their own beyond origin/main. Computed
  # once.
  merged_list="$(git -C "$REPO" branch --merged origin/main --format='%(refname:short)')"

  while IFS=$'\t' read -r branch wt; do
    [[ -z "$branch" || "$branch" == "main" || "$branch" == "$current" ]] && continue

    has_own=1
    grep -qxF "$branch" <<< "$merged_list" && has_own=0

    # A branch with a live worktree is work in progress, however many commits
    # it holds: the orchestrator drives it, and `sclaude done` removes it after
    # the merge. Asking about it here would mean offering to tear down an
    # unfinished feature.
    if [[ -n "$wt" ]]; then
      if [[ "$has_own" -eq 0 ]]; then
        printf 'keep\t%s\t%s\n' "$branch" "feature in progress, no commits yet"
      else
        printf 'keep\t%s\t%s\n' "$branch" "feature in progress"
      fi
      continue
    fi

    # Whether origin/<the same name> exists. We look precisely at the branch of
    # the same name rather than at the upstream: branches here are created from
    # origin/main and their upstream points at main, which is not going
    # anywhere.
    if git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
      # The remote branch is in place: the work still lives there. We ask gh
      # only when no commits of its own are left — otherwise this is work in
      # progress.
      if [[ "$has_own" -eq 0 ]]; then
        state="$(branch_pr_state "$branch")"
        if [[ "$state" == "MERGED" ]]; then
          printf 'drop\t%s\t%s\n' "$branch" "PR merged"
        else
          printf 'keep\t%s\t%s\n' "$branch" "nothing of its own beyond main"
        fi
      else
        printf 'keep\t%s\t%s\n' "$branch" "has commits, PR still open"
      fi
      continue
    fi

    # There is no remote branch of the same name. Either GitHub removed it
    # after the merge or the branch was never pushed — those are different
    # things, and the PR's state decides between them.
    state="$(branch_pr_state "$branch")"
    case "$state" in
      MERGED) printf 'drop\t%s\t%s\n' "$branch" "PR merged, remote branch gone" ;;
      CLOSED) printf 'keep\t%s\t%s\n' "$branch" "PR closed unmerged — the commits live only here" ;;
      OPEN)   printf 'keep\t%s\t%s\n' "$branch" "PR open, but the remote branch is gone" ;;
      # There never was a PR (or gh is silent). No commits of its own means
      # nothing to hold; if there are, they exist only here, and that is for
      # the human.
      *)      if [[ "$has_own" -eq 0 ]]; then
                printf 'drop\t%s\t%s\n' "$branch" "no commits, no remote branch"
              else
                printf 'keep\t%s\t%s\n' "$branch" "never pushed — the commits live only here"
              fi ;;
    esac
  done < <(git -C "$REPO" for-each-ref refs/heads \
             --format='%(refname:short)%09%(worktreepath)')
}

# Shows the breakdown and, if there is anything to delete, offers to do it.
# Called where the human is looking at the overall picture anyway.
review_branches() {
  local rows drop keep table answer branch reason
  rows="$(classify_branches)" || return 0
  [[ -z "$rows" ]] && return 0

  drop="$(printf '%s\n' "$rows" | awk -F'\t' '$1 == "drop"')"
  keep="$(printf '%s\n' "$rows" | awk -F'\t' '$1 == "keep"')"

  if [[ -n "$keep" ]]; then
    echo "${BOLD}Branches in progress:${OFF}"
    table=""
    while IFS=$'\t' read -r _ branch reason; do
      [[ -z "$branch" ]] && continue
      table+="  $branch"$'\t'"$reason"$'\n'
    done <<< "$keep"
    align_columns "$table"
  fi

  [[ -z "$drop" ]] && return 0

  echo ""
  echo "${BOLD}Branches with nothing left to hold:${OFF}"
  table=""
  while IFS=$'\t' read -r _ branch reason; do
    [[ -z "$branch" ]] && continue
    table+="  $branch"$'\t'"$reason"$'\n'
  done <<< "$drop"
  align_columns "$table"

  echo ""
  ask "Delete them? [y/n] " answer yn
  is_yes "$answer" || return 0

  while IFS=$'\t' read -r _ branch reason; do
    [[ -z "$branch" ]] && continue
    # Only commits beyond a merged PR go to the human (branch_delete_merged).
    local rc=0
    branch_delete_merged "$branch" || rc=$?
    if [[ "$rc" == 0 ]]; then
      echo "  ${GREEN}deleted${OFF} $branch"
    elif [[ "$rc" == 2 ]]; then
      echo "  ${GREEN}deleted${OFF} $branch (squash-merged, the PR head matches)"
    else
      warn "  $branch — git refused: it carries commits in neither main nor a merged PR"
      ask "  Force-delete it (git branch -D)? [y/n] " answer yn
      if is_yes "$answer"; then
        git -C "$REPO" branch -D "$branch" >/dev/null && echo "  ${GREEN}deleted${OFF} $branch"
      fi
    fi
  done <<< "$drop"
}
