#!/usr/bin/env bash
#
# Sorting out the local branches: which have nothing left to hold.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Which processes work in a tree left behind (proc_cwds), on Linux and macOS.
source "$(dirname "${BASH_SOURCE[0]}")/../core/procinfo.sh"

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
  gh pr list --head "$1" --base main --state merged --limit 1 --json headRefOid \
    --jq '.[0].headRefOid // empty' 2>/dev/null || true
}

# Deletes a local branch whose work is in main: `git branch -d`, and when git
# refuses, -D if the local tip is the head of the branch's merged pull request.
# A squash merge leaves the branch's commits out of main, so -d refuses every
# squash-merged branch; the matching head says nothing is lost.
#
# Commits past the pull request's head are let go too when main already holds
# what they change: sclaude's own housekeeping lands on the branch after the
# merge (the deferred entries left to main, a prompt fix carried to main by
# hand), and the branch was kept for commits whose content was on main. The
# test is a merge of the tip into origin/main from the merged head: a result
# with main's own tree adds nothing. Anything else is left alone, and so is
# every branch when git is too old for --merge-base (a refusal, not a guess).
#
#   branch_delete_merged <branch>  → 0 deleted, 2 deleted as squash-merged, 1 kept
branch_delete_merged() {
  local branch="$1"
  git -C "$REPO" branch -d "$branch" >/dev/null 2>&1 && return 0
  branch_squash_held "$branch" || return 1
  git -C "$REPO" branch -D "$branch" >/dev/null 2>&1 && return 2
  return 1
}

# Whether main holds everything a branch carries by way of its merged pull
# request (the test branch_delete_merged deletes by, above). Asked before a
# tree is removed too, so that it never goes for a branch that stays.
#
#   branch_squash_held <branch> [<tip>]  → 0 held, 1 not (or not known)
#
# <tip>, when given, is judged rather than the branch's tip read again: the
# one the caller then deletes.
branch_squash_held() {
  local branch="$1" tip="${2:-}" head merged
  [[ -n "$tip" ]] \
    || tip="$(git -C "$REPO" rev-parse -q --verify "refs/heads/$branch" 2>/dev/null)" || return 1
  head="$(cd "$REPO" && merged_pr_head "$branch")"
  [[ -n "$head" ]] || return 1
  # The head may be a commit GitHub alone has (pushed from elsewhere, its
  # branch deleted after the merge); a pull request's head can be fetched.
  git -C "$REPO" cat-file -e "$head^{commit}" 2>/dev/null \
    || git -C "$REPO" fetch -q --no-write-fetch-head origin "$head" 2>/dev/null || true
  # A tip behind the merged head (the PR got commits this clone never
  # fetched) is all in it.
  if ! git -C "$REPO" merge-base --is-ancestor "$tip" "$head" 2>/dev/null; then
    git -C "$REPO" merge-base --is-ancestor "$head" "$tip" 2>/dev/null || return 1
    merged="$(git -C "$REPO" merge-tree --write-tree --merge-base="$head" \
                origin/main "$tip" 2>/dev/null)" || return 1
    [[ "$merged" == "$(git -C "$REPO" rev-parse -q --verify 'origin/main^{tree}')" ]] \
      || return 1
  fi
  return 0
}

# Sorts the local branches into buckets and prints a line per branch:
#
#   drop  <branch>  <reason>   — nothing left to hold, we offer to delete it
#   keep  <branch>  <reason>   — displayed, but not touched
#
# main and the current branch are not considered at all.
classify_branches() {
  local current merged_list branch state has_own wt tree st part wt_status
  local -A parts_of=()
  # Without --prune the local refs/remotes/origin/* outlive branches that have
  # long been gone from GitHub, and the whole "the remote branch is gone" check
  # lies. A second of network; we skip silently when there is none.
  git -C "$REPO" fetch origin --prune -q 2>/dev/null || true
  current="$(git -C "$REPO" branch --show-current)"
  # The branches with no commits of their own beyond origin/main. Computed
  # once.
  merged_list="$(git -C "$REPO" branch --merged origin/main --format='%(refname:short)')"
  # The parts' branches of a feature built in parts belong to it while its
  # tree is here: the parts are built on them without a tree of their own,
  # and `sclaude done` deletes them with the feature (parts_branches).
  while IFS= read -r tree; do
    st="$tree/.sclaude/local/feature/state.json"
    [[ -f "$st" ]] || continue
    while IFS= read -r part; do
      [[ -n "$part" ]] && parts_of["$part"]="$(state_get "$st" parts.umbrella 2>/dev/null || true)"
    done < <(parts_branches "$st" 2>/dev/null)
  done < <(git -C "$REPO" worktree list --porcelain | sed -n 's/^worktree //p')

  while IFS=$'\t' read -r branch wt; do
    [[ -z "$branch" || "$branch" == "main" || "$branch" == "$current" ]] && continue

    has_own=1
    grep -qxF "$branch" <<< "$merged_list" && has_own=0

    # A branch with a live worktree is work in progress, however many commits
    # it holds: the orchestrator drives it, and `sclaude done` removes it after
    # the merge. Asking about it here would mean offering to tear down an
    # unfinished feature.
    if [[ -n "${parts_of[$branch]+set}" ]]; then
      printf 'keep\t%s\t%s\n' "$branch" "a part of ${parts_of[$branch]:-a feature in progress}, deleted with it"
      continue
    fi
    if [[ -n "$wt" ]]; then
      # A tree opened by hand outlives its merged pull request with nothing
      # to remove it: `sclaude done` knows only features. It was listed as in
      # progress for good. One with no .sclaude/local at all is not sclaude's
      # — a feature's, a deferred review's with its workshop inside, a
      # recording — and when main holds all its branch carries
      # (branch_squash_held: a merged pull request, nothing past it main
      # lacks) a clean one goes with its branch, review_branches removing the
      # tree first. One with changes of its own, one a process works in (a
      # session, an editor going on after the merge) and one whose status
      # git does not give are the human's. So is a tree that is not there:
      # deleted by hand, or on a drive not mounted now (a feature's gone
      # looks like any other), so it is said, not offered.
      if [[ ! -d "$wt" ]]; then
        printf 'keep\t%s\t%s\n' "$branch" "its worktree is missing (deleted, or not mounted) — if it is gone: git worktree remove $(printf '%q' "$wt")"
        continue
      fi
      if [[ ! -e "$wt/.sclaude/local" ]] && branch_squash_held "$branch"; then
        wt_status="$(git -C "$wt" status --porcelain 2>/dev/null)" || wt_status="unreadable"
        if [[ -z "$wt_status" ]] && ! proc_in_dir "$(readlink -f "$wt")"; then
          printf 'drop\t%s\t%s\n' "$branch" "PR merged, its worktree left behind ($wt)"
        else
          printf 'keep\t%s\t%s\n' "$branch" "PR merged, but its worktree is in use or not clean ($wt)"
        fi
        continue
      fi
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
        # Work in progress, said as what is known without asking GitHub: a
        # pull request is not guessed at — a part's branch never has one.
        printf 'keep\t%s\t%s\n' "$branch" "has commits, pushed"
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
    # A branch checked out in a tree left behind cannot be deleted while the
    # tree is there. Asked again here, before the tree goes, rather than
    # taken from the list: the question may have waited while a commit was
    # made in the tree, and a GitHub that does not answer now leaves both
    # standing; a process that came into the tree meanwhile keeps it too, and
    # so does a tree that went missing (unmounted, or a feature's deleted).
    # `git worktree remove` without --force takes only a clean one.
    # The tip judged is the one deleted (update-ref with the old value): a
    # commit made after it was read keeps the branch. update-ref leaves the
    # branch's section in the config, which `branch -D` would have taken.
    local bwt btip
    bwt="$(git -C "$REPO" for-each-ref --format='%(worktreepath)' "refs/heads/$branch")"
    if [[ -n "$bwt" ]]; then
      btip="$(git -C "$REPO" rev-parse -q --verify "refs/heads/$branch")"
      if [[ -z "$btip" ]] || ! branch_squash_held "$branch" "$btip"; then
        warn "  $branch — could not confirm main holds all of it (a new commit, or GitHub did not answer); its worktree $bwt left alone"
      elif [[ ! -d "$bwt" ]]; then
        warn "  $branch — its worktree $bwt is missing now; left alone"
      elif proc_in_dir "$(readlink -f "$bwt")"; then
        warn "  $branch — something works in its worktree $bwt now; left alone"
      elif ! git -C "$REPO" worktree remove "$bwt" >/dev/null 2>&1; then
        warn "  $branch — its worktree $bwt could not be removed; left alone"
      elif git -C "$REPO" update-ref -d "refs/heads/$branch" "$btip" >/dev/null 2>&1; then
        git -C "$REPO" config --remove-section "branch.$branch" >/dev/null 2>&1 || true
        echo "  ${GREEN}deleted${OFF} $branch and its worktree $bwt"
      else
        warn "  $branch — its worktree $bwt was removed, but git refused to delete the branch"
      fi
      continue
    fi
    # Only commits a merged PR and main do not hold go to the human
    # (branch_delete_merged).
    local rc=0
    branch_delete_merged "$branch" || rc=$?
    if [[ "$rc" == 0 ]]; then
      echo "  ${GREEN}deleted${OFF} $branch"
    elif [[ "$rc" == 2 ]]; then
      echo "  ${GREEN}deleted${OFF} $branch (squash-merged)"
    else
      warn "  $branch — git refused: it carries commits in neither main nor a merged PR"
      ask "  Force-delete it (git branch -D)? [y/n] " answer yn
      if is_yes "$answer"; then
        git -C "$REPO" branch -D "$branch" >/dev/null && echo "  ${GREEN}deleted${OFF} $branch"
      fi
    fi
  done <<< "$drop"
}

# The parts' branches of a feature being cleaned up (sclaude done): the parts
# were joined into the feature's branch, so each one goes once its commits
# are all in that branch's last tip — the local branch, and origin's as
# GitHub has it; one carrying more is kept, and said. Called only when the
# feature's branch itself went.
#
#   branches_parts_delete <feature tip>   (names on stdin, one a line)
branches_parts_delete() {
  local feature_tip="$1" part tip theirs
  while IFS= read -r part; do
    [[ -n "$part" ]] || continue
    tip="$(git -C "$REPO" rev-parse -q --verify "refs/heads/$part" 2>/dev/null || true)"
    if [[ -n "$tip" ]]; then
      if [[ -n "$feature_tip" ]] && git -C "$REPO" merge-base --is-ancestor "$tip" "$feature_tip" 2>/dev/null; then
        git -C "$REPO" branch -D "$part" >/dev/null 2>&1 || true
      else
        warn "  local branch $part kept: it carries commits the feature's branch did not take"
      fi
    fi
    theirs="$(git -C "$REPO" ls-remote --heads origin "$part" 2>/dev/null | cut -f1)"
    [[ -n "$theirs" ]] || continue
    if [[ -n "$feature_tip" ]] && git -C "$REPO" merge-base --is-ancestor "$theirs" "$feature_tip" 2>/dev/null; then
      git -C "$REPO" push origin --delete "$part" >/dev/null 2>&1 \
        || warn "  could not delete origin/$part"
    else
      warn "  origin/$part kept: it carries commits the feature's branch did not take"
    fi
  done
}
