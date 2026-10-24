#!/usr/bin/env bash
#
# The sync with main: step 5 of the cycle the menu shows (cycle_number), run
# only when the feature's branch would not merge.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# A reviewed branch whose pull request conflicts with main went on to the
# preview, to QA and to the merge as if nothing were wrong, and then waited
# there: merge_offer said "it conflicts with main — resolve them and push",
# and merge_wait went on asking GitHub every half minute for hours, for a
# merge nobody could make. The conflict is known long before that, and for
# nothing: `git merge-tree` merges in memory and names the files, with no
# session and no GitHub. So remind_prod asks it before the preview (QA looks
# at the code that will merge, not at the branch alone), again after QA's yes
# and before the hand-off for the merge, and merge_wait asks it while it
# waits — main moves while QA works. On a conflict a session merges main into the branch and pushes,
# and the preview, its regression and QA run again on what it pushed.
#
# A conflict in the deferred logs alone needs no session: they are logs of
# rows (deferred.sh), and their merge is the rows of both sides, which
# sclaude writes itself.

# How often merge_wait looks whether main has moved into a conflict, in
# seconds: a fetch, so not every poll of the merge; overridable and validated
# as MERGE_POLL is.
SYNC_POLL="${SYNC_POLL:-120}"
[[ "$SYNC_POLL" =~ ^[1-9][0-9]*$ ]] || SYNC_POLL=120

# The branch the tree is on; 1, and nothing printed, when HEAD is detached.
sync_branch_name() {
  local b
  b="$(git -C "$1" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$b" && "$b" != "HEAD" ]] || return 1
  printf '%s\n' "$b"
}

# Whether a merge is under way in the tree (MERGE_HEAD).
merge_under_way() {
  [[ -n "$(git -C "$1" rev-parse -q --verify MERGE_HEAD 2>/dev/null)" ]]
}

# Whether the tree holds no uncommitted change to a tracked file.
tree_clean() {
  [[ -z "$(git -C "$1" status --porcelain --untracked-files=no 2>/dev/null)" ]]
}

# Where origin has the tree's branch, as last fetched or pushed; nothing when
# it does not have it.
sync_origin_tip() {
  local b
  b="$(sync_branch_name "$1")" || return 0
  git -C "$1" rev-parse -q --verify "refs/remotes/origin/$b" 2>/dev/null || true
}

# A sync left open, closed: its conflict went another way, and the menu stops
# showing it.
#
#   sync_close_open <state>
sync_close_open() {
  sync_broken_off "$1" || return 0
  session_runs "$1" sync close
}

# Fetches origin's main and, when origin has it, the tree's branch: what
# merge_conflicts asks about. 1 when main could not be fetched.
sync_fetch() {
  local branch
  git -C "$1" fetch -q origin main 2>/dev/null || return 1
  branch="$(sync_branch_name "$1")" \
    && { git -C "$1" fetch -q origin "$branch" 2>/dev/null || true; }
  return 0
}

# What merging origin/main into the branch would leave in conflict, without
# merging anything: the paths, one a line.
#
# The branch is its tip on origin when origin has it: that is what the pull
# request merges. GitHub's "Update branch" or its conflict editor moves only
# that one, and a merge made here and not pushed is not in it yet — counted
# as clean, it sent unpushed code to the preview and a conflicting pull
# request to the merge wait. A branch origin does not have (before step 3)
# is the tree's HEAD. Commits here that origin's tip lacks are asked about
# too: whoever merges main here merges them, and a tip that merges cleanly
# said nothing of theirs. A caller that has just fetched passes `nofetch`.
#
#   merge_conflicts <wt> [nofetch]   → 0 merges cleanly, 1 conflicts (paths
#                                      printed), 2 cannot tell (no network, a
#                                      git without merge-tree --write-tree,
#                                      which came in 2.38)
merge_conflicts() {
  local wt="$1" tip=HEAD branch rc=0
  branch="$(sync_branch_name "$wt")" || branch=""
  if [[ "${2:-}" != nofetch ]]; then
    sync_fetch "$wt" || return 2
  fi
  [[ -n "$branch" ]] && git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$branch" >/dev/null \
    && tip="refs/remotes/origin/$branch"
  merge_conflicts_at "$wt" "$tip" || rc=$?
  if [[ "$rc" -eq 0 && "$tip" != HEAD ]] \
     && ! git -C "$wt" merge-base --is-ancestor HEAD "$tip" 2>/dev/null; then
    merge_conflicts_at "$wt" HEAD || rc=$?
  fi
  return "$rc"
}

# The same for one revision, with nothing fetched.
#
#   merge_conflicts_at <wt> <rev>
merge_conflicts_at() {
  local out rc=0
  out="$(git -C "$1" merge-tree --write-tree --name-only --no-messages "$2" origin/main 2>/dev/null)" || rc=$?
  case "$rc" in
    0) return 0 ;;
    # The first line is the tree it would write; the paths follow.
    1) printf '%s\n' "$out" | tail -n +2 | grep -v '^$'; return 1 ;;
    *) return 2 ;;
  esac
}

# Whether every path given is a file of the branch under the deferred folders
# — as DEFERRED_PATHSPECS in deferred.sh names them, matched by git itself, so
# the two cannot drift apart.
#
#   sync_deferred_only <wt> <path>...
sync_deferred_only() {
  local wt="$1" f logs
  shift
  [[ $# -gt 0 ]] || return 1
  logs="$(git -C "$wt" ls-files -- "${DEFERRED_PATHSPECS[@]}" 2>/dev/null)" || return 1
  for f in "$@"; do
    grep -qxF -- "$f" <<< "$logs" || return 1
  done
}

# Whether the tree's branch and its tip on origin have each commits the other
# lacks.
sync_diverged() {
  local wt="$1" remote
  remote="$(sync_origin_tip "$wt")"
  [[ -n "$remote" ]] || return 1
  ! git -C "$wt" merge-base --is-ancestor "$remote" HEAD 2>/dev/null \
    && ! git -C "$wt" merge-base --is-ancestor HEAD "$remote" 2>/dev/null
}

# A merge with main made here and committed, but not pushed: the pull request
# lacks only the push. Pushed then, as a session would have.
#
#   sync_push_pending <wt>   → 0 pushed, 1 nothing of the kind, 2 the push failed
sync_push_pending() {
  local wt="$1" branch remote
  branch="$(sync_branch_name "$wt")" && [[ "$branch" != "main" ]] || return 1
  remote="$(sync_origin_tip "$wt")"
  [[ -n "$remote" && "$(git -C "$wt" rev-parse HEAD)" != "$remote" ]] || return 1
  git -C "$wt" merge-base --is-ancestor "$remote" HEAD 2>/dev/null || return 1
  # And main is in it: the unpushed work is the merge with main, not some
  # other session's commits that happen to merge cleanly.
  git -C "$wt" merge-base --is-ancestor origin/main HEAD 2>/dev/null || return 1
  ! merge_under_way "$wt" && tree_clean "$wt" || return 1
  merge_conflicts_at "$wt" HEAD >/dev/null || return 1
  if ! GIT_TERMINAL_PROMPT=0 git -C "$wt" push -q origin "$branch" >/dev/null 2>&1; then
    warn "  main is merged into $branch here, but the push failed. Push it by hand:"
    warn "    git -C $wt push origin $branch"
    return 2
  fi
  return 0
}

# The branch brought up to its own tip on origin, when that is ahead and the
# tree is clean: a branch updated on GitHub is merged from there, and a sync
# pushed from behind it would be refused.
sync_catch_up() {
  local wt="$1" remote
  remote="$(sync_origin_tip "$wt")"
  [[ -n "$remote" ]] && tree_clean "$wt" && ! merge_under_way "$wt" || return 0
  git -C "$wt" merge-base --is-ancestor HEAD "$remote" 2>/dev/null || return 0
  git -C "$wt" merge -q --ff-only "$remote" >/dev/null 2>&1 || true
}

# Merges origin/main into the branch when only the deferred logs conflict:
# main's rows of each, then the rows the branch added since the two parted
# (deferred_minus of the merge base) less the rows main added since then —
# deferred_to_main sends a branch's rows to main, and they would come twice.
# Not the branch's whole copy: rows it took from main at an earlier merge and
# main has since removed — the monthly review removes what it decided — would
# come back. Nor less all of main's copy: a row the branch repeats on purpose
# (the monthly review counts the repeats) would cancel against the one both
# sides had. Committed, and pushed when origin has the branch —
# one not pushed yet stays local, as a session leaves it. Past hooks, as
# deferred_to_main's push is: the logs are all it resolves, and the rest is
# main's, which passed its own. On any trouble before the commit the merge is
# called off and the tree left as it was.
#
#   sync_deferred <wt> <path>...   → 0 merged (and pushed), 1 not done,
#                                    2 merged here, but the push failed
sync_deferred() {
  local wt="$1" f tmp branch failed=""
  shift
  branch="$(sync_branch_name "$wt")" && [[ "$branch" != "main" ]] || return 1
  tree_clean "$wt" || return 1
  # --no-commit, so that the merge is committed below and only there, after
  # the logs: it stops on their conflicts anyway.
  git -C "$wt" merge -q --no-ff --no-commit origin/main >/dev/null 2>&1
  merge_under_way "$wt" || return 1
  tmp="$(mktemp -d)"
  for f in "$@"; do
    # Both sides must have the file: a log one side deleted is a decision,
    # not rows to add up.
    if ! git -C "$wt" show ":3:$f" > "$tmp/main" 2>/dev/null \
       || ! git -C "$wt" show ":2:$f" > "$tmp/branch" 2>/dev/null; then
      failed=1; break
    fi
    # No base: the file came on both sides since, and all of the branch's
    # rows are its own.
    git -C "$wt" show ":1:$f" > "$tmp/base" 2>/dev/null || : > "$tmp/base"
    deferred_minus "$tmp/base" "$tmp/branch" > "$tmp/added" \
      && deferred_minus "$tmp/base" "$tmp/main" > "$tmp/theirs" \
      && deferred_minus "$tmp/theirs" "$tmp/added" > "$tmp/own" \
      && awk '{ print }' "$tmp/main" "$tmp/own" > "$wt/$f" && git -C "$wt" add -- "$f" \
      || { failed=1; break; }
  done
  rm -rf "$tmp"
  if [[ -n "$failed" || -n "$(git -C "$wt" diff --name-only --diff-filter=U 2>/dev/null)" ]] \
     || ! git -C "$wt" commit -q --no-edit --no-verify >/dev/null 2>&1; then
    git -C "$wt" merge --abort >/dev/null 2>&1 || true
    return 1
  fi
  [[ -n "$(sync_origin_tip "$wt")" ]] || return 0
  if ! GIT_TERMINAL_PROMPT=0 git -C "$wt" push -q --no-verify origin "$branch" >/dev/null 2>&1; then
    warn "  main is merged into $branch here, but the push failed. Push it by hand:"
    warn "    git -C $wt push origin $branch"
    return 2
  fi
  return 0
}

# Whether the branch is in the shape a sync leaves it: no merge under way, no
# change left uncommitted, merging cleanly with origin/main, and pushed — when
# origin has the branch at all: one not pushed yet (cmd_sync before step 3)
# stays local.
#
#   sync_settled <wt>
#
# A check that cannot be made (no network) does not count against it, as in
# sync_with_main: the push the session made moved origin's ref here already.
sync_settled() {
  local wt="$1" rc=0 remote
  sync_branch_name "$wt" >/dev/null || return 1
  ! merge_under_way "$wt" && tree_clean "$wt" || return 1
  merge_conflicts "$wt" >/dev/null || rc=$?
  [[ "$rc" -ne 1 ]] || return 1
  remote="$(sync_origin_tip "$wt")"
  [[ -z "$remote" || "$(git -C "$wt" rev-parse HEAD)" == "$remote" ]]
}

# A pull request handed over for the merge (pr_qa_handoff) goes back to a
# draft when its code is about to change under QA's yes: the sync pushes code
# nobody checked, and until the preview and QA have seen it nothing should
# merge it — here or on GitHub. qa_retest does the same once a fresh preview
# is green; this does not wait for that, which may never come.
#
#   sync_withdraw <wt> <pr> [what moved it]
sync_withdraw() {
  local state="$1/.sclaude/local/feature/state.json" repo
  [[ "$2" =~ ^[0-9]+$ ]] || return 0
  [[ -n "$(state_get "$state" handoff 2>/dev/null | grep -v '^null$')" ]] || return 0
  repo="$(gh_repo)" || return 0
  pr_unhandoff "$1" "$2" "$repo" "PR #$2 is a draft again until the preview and QA have seen ${3:-the sync}."
}

# The sync as remind_prod and the menu take it: sync_with_main, and a pull
# request handed over for the merge made a draft again when the branch moved
# on origin — by the sync's word (3), or by a push the session made before it
# stopped short (1, with a change left uncommitted, say): either way origin
# has code nobody has checked.
#
# Origin's tip is held against the head the hand-off was made on (`handoff`,
# pr_qa_handoff): a branch that moved by other hands — a push from another
# machine, GitHub's "Update branch" — carries code nobody has checked too,
# and the hand-off goes back for it as for the sync, said in its own words.
# Against that head rather than the tip before this call: whatever fetched
# in between — the menu, a step's start, deferred_to_main — had moved the ref
# already, and the commits went unseen. Such commits are 3, as a sync is: the
# code QA passed has changed, and the run starts over on it. Returned as 0,
# remind_prod handed the pull request over again at once, unchecked.
#
# Only a tip with commits the hand-off lacks: a ref not fetched since lags
# behind it, and is not new code. Without that head here to compare with,
# a push the call's own session made before it stopped short (1) still
# counts, by the tip moving during the call.
#
#   sync_gate <wt> <slug> <pr> [nofetch]
#     → sync_with_main's 0, 1 or 3, or 5: taken back for commits from
#       elsewhere with nothing merged — the run starts over as for 3, and
#       nobody is told "merged"
sync_gate() {
  local rc=0 handed tip before
  before="$(sync_origin_tip "$1")"
  sync_with_main "$1" "$2" "${4:-}" || rc=$?
  if [[ "$rc" -eq 3 ]]; then
    sync_withdraw "$1" "$3"
    return "$rc"
  fi
  handed="$(state_get "$1/.sclaude/local/feature/state.json" handoff 2>/dev/null || true)"
  tip="$(sync_origin_tip "$1")"
  if [[ -n "$handed" && "$handed" != "null" ]] && git -C "$1" cat-file -e "$handed^{commit}" 2>/dev/null; then
    if [[ -n "$tip" && "$tip" != "$handed" ]] \
       && ! git -C "$1" merge-base --is-ancestor "$tip" "$handed" 2>/dev/null; then
      if [[ "$rc" -eq 0 ]]; then
        sync_withdraw "$1" "$3" "the commits that reached its branch on origin"
        rc=5
      else
        sync_withdraw "$1" "$3"
      fi
    fi
  elif [[ "$rc" -eq 1 && "$tip" != "$before" ]]; then
    sync_withdraw "$1" "$3"
  fi
  return "$rc"
}

# The merge with main a step's start or the menu offers, when it would stop
# on conflicts: the question (sync_ask), and on a yes the sync (sync_gate).
# A merge that would not stop is the caller's own, plain `git merge`.
#
#   sync_offer <wt> <slug> <branch> <pr>
#     → 2 no conflict (or cannot tell): the caller merges, or asks first;
#       4 a no to the question; otherwise sync_gate's 0, 1 or 3
sync_offer() {
  local conflicts crc=0
  conflicts="$(merge_conflicts "$1" nofetch)" || crc=$?
  [[ "$crc" -eq 1 ]] || return 2
  sync_ask "$1" "$3" "$conflicts" || return 4
  sync_gate "$1" "$2" "$4" nofetch
}

# The question before a merge that would stop on conflicts, with the files,
# and what resolves them: sclaude itself when only the deferred logs conflict,
# a paid session otherwise.
#
#   sync_ask <wt> <branch> <conflicts>   → 0 on a yes
sync_ask() {
  local wt="$1" branch="$2" answer how="a session resolving them"
  local -a files
  mapfile -t files <<< "$3"
  sync_deferred_only "$wt" "${files[@]}" && how="sclaude merging the deferred logs itself"
  info "  The merge would stop on conflicts in ${#files[@]} file(s):"
  printf '%s\n' "${files[@]}" | sed 's/^/    /'
  ask "${BOLD}Merge origin/main into $branch, with $how? [y/n] ${OFF}" answer yn
  is_yes "$answer"
}

# The check, and the sync when it is needed.
#
#   sync_with_main <wt> <slug> [nofetch]   → 0 merges cleanly as it is,
#                                  1 still does not (the run stops),
#                                  3 synced: the branch moved, and what
#                                    followed the old head runs again
#
# "Cannot tell" is 0: a check that could not be made is no reason to stop a
# run, and GitHub says the same thing later in its own words (merge_offer).
sync_with_main() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json"
  local conflicts rc=0 pr issue branch session n prompt settings unfinished="" what
  local -a files extra

  conflicts="$(merge_conflicts "$wt" "${3:-}")" || rc=$?
  # Behind origin's tip (updated on GitHub, its conflict editor perhaps): the
  # tree catches up, and the answer above, which is about that tip, stands —
  # what runs next works on this tree.
  sync_catch_up "$wt"
  # A merge under way here — a sync broken off mid-way, or one by hand — is
  # no clean branch whatever origin's tip says: its files may hold conflict
  # markers, and the preview would deploy them. What is left unmerged is the
  # conflict; with nothing left, the session checks and commits it — said in
  # words of its own, not as a file in conflict.
  if merge_under_way "$wt"; then
    conflicts="$(git -C "$wt" diff --name-only --diff-filter=U 2>/dev/null)"
    [[ -n "$conflicts" ]] || unfinished=1
    rc=1
  elif [[ "$rc" -eq 1 ]]; then
    # Apart both ways — commits here origin lacks, and there that this tree
    # lacks: whatever merges main in here is a push origin refuses.
    if sync_diverged "$wt"; then
      warn "  The branch here and on origin have both moved: bring them together first"
      warn "  (git -C $wt pull --no-rebase), then: $SELF sync $slug"
      return 1
    fi
    # Ahead of origin's tip with main merged: the push is all that is missing.
    local prc=0
    sync_push_pending "$wt" || prc=$?
    if [[ "$prc" -eq 0 ]]; then
      info "  main was merged into the branch here and not pushed — pushed it now."
      sync_close_open "$state"
      return 3
    fi
    [[ "$prc" -eq 2 ]] && return 1
  fi
  if [[ "$rc" -ne 1 ]]; then
    # A sync left open whose conflict went another way — resolved by hand,
    # on GitHub, or main moved — is over.
    [[ "$rc" -eq 0 ]] && sync_close_open "$state"
    return 0
  fi
  files=()
  [[ -n "$conflicts" ]] && mapfile -t files <<< "$conflicts"
  what="${#files[@]} file(s) conflict"
  [[ -n "$unfinished" ]] && what="a merge of main is under way here, resolved and not committed"
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  echo ""
  # Reviewed, with its pull request open: what remind_prod calls this for.
  # From the menu (cmd_sync) it may be any step, before a pull request.
  local reviewed=""
  [[ "$(state_get "$state" step 2>/dev/null || true)" == "done" && "$pr" =~ ^[0-9]+$ ]] && reviewed=1
  if [[ "$pr" =~ ^[0-9]+$ ]]; then
    warn "PR #$pr does not merge with main: $what."
  else
    warn "The branch does not merge with main: $what."
  fi
  (( ${#files[@]} )) && printf '%s\n' "${files[@]}" | sed 's/^/    /'

  if [[ -z "$unfinished" ]] && sync_deferred_only "$wt" "${files[@]}"; then
    local drc=0
    sync_deferred "$wt" "${files[@]}" || drc=$?
    if [[ "$drc" -eq 0 ]]; then
      sync_close_open "$state"
      info "  Only the deferred logs: main is merged in with both sides' rows."
      ask_feed say "$(phase_line finished sync) · only the deferred logs, merged by sclaude"
      return 3
    fi
    # Merged, with nothing left for a session: the next sync pushes it
    # (sync_push_pending), or the person does.
    [[ "$drc" -eq 2 ]] && return 1
    info "  Only the deferred logs, but sclaude could not merge them itself — a session will."
  fi

  issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ "$issue" == "null" ]] && issue=""
  branch="$(state_get "$state" branch 2>/dev/null || true)"
  # The review step's rules: the session works in the feature's tree and
  # pushes its branch, as a review fix does.
  settings="$(step_settings review "$wt")" \
    || { warn "  The sync was not started: sclaude could not read its rules (see above)."; return 1; }
  mapfile -t extra <<< "$settings"

  # A session the person left goes on where it was; a sync that finished
  # before is a new conflict and a new session.
  local runs_info open resume=""
  runs_info="$(sync_runs_info "$state")"
  IFS=$'\t' read -r n open session <<< "$runs_info"
  [[ "$open" == open ]] || session=""
  if live_session "$wt" "$session" >/dev/null; then
    resume=1
  else
    session="$(new_session_id)"
  fi
  session_runs "$state" sync open "$session"
  n="$(sync_runs_info "$state" | cut -f1)"
  [[ "$n" =~ ^[1-9][0-9]*$ ]] || n=1

  echo ""
  echo "${BOLD}${BLUE}── $slug · $(phase_title sync): merge main into $branch ──${OFF}"
  info "   $(step_model review) / $(step_effort review) / $(step_mode review) · $wt"
  echo ""
  ask_feed say "$(phase_line "$([[ -n "$resume" ]] && echo resumed || echo started)" sync "$n") · $what"

  rm -f "$(done_marker "$wt")"
  session_watch_start "$wt" "$session"
  if [[ -n "$resume" ]]; then
    if [[ -n "$unfinished" ]]; then
      prompt="The merge with \`origin/main\` is still under way here: nothing is left unmerged, but it is not committed. Check it and carry on with the sync as agreed above."
    else
      prompt="The branch still does not merge with \`origin/main\`. These files conflict now:"$'\n\n'"$(printf '    %s\n' "${files[@]}")"$'\n\n'"Carry on with the sync as agreed above."
    fi
    ( cd "$wt" && dev_env_load "$wt" && claude_launch --resume "$session" \
        --model "$(step_model review)" --effort "$(step_effort review)" \
        --permission-mode "$(step_mode review)" "${extra[@]}" \
        -n "$(session_label sync "$n")/$slug" "$prompt" )
  else
    prompt="$(SCLAUDE_V_BRANCH="$branch" SCLAUDE_V_CONFLICTS="$conflicts" SCLAUDE_V_UNFINISHED="$unfinished" \
      SCLAUDE_V_REVIEWED="$reviewed" \
      SCLAUDE_V_UNREVIEWED="$([[ -z "$reviewed" ]] && echo 1)" \
      render_prompt sync "$slug" "$pr" "$issue" "$wt")" || { session_watch_stop; return 1; }
    ( cd "$wt" && dev_env_load "$wt" && claude_launch --session-id "$session" \
        --model "$(step_model review)" --effort "$(step_effort review)" \
        --permission-mode "$(step_mode review)" "${extra[@]}" \
        -n "$(session_label sync "$n")/$slug" "$prompt" )
  fi
  session_watch_stop
  session_closed "$(done_marker "$wt")" "$wt" "$session" "" "" sync "$n" || true

  if ! session_started "$wt" "$session"; then
    session_runs "$state" sync drop "$session"
    return 1
  fi
  if sync_settled "$wt"; then
    session_runs "$state" sync finish "$session"
    return 3
  fi
  session_runs "$state" sync end "$session"
  echo ""
  warn "The branch still does not merge cleanly with main, or is not pushed."
  if [[ -n "$reviewed" ]]; then
    info "  The preview, QA and the merge wait for it. Carry on with: $SELF $slug"
  else
    info "  The session is resumed by the next sync: $SELF sync $slug"
  fi
  return 1
}
