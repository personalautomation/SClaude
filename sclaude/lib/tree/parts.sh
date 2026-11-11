#!/usr/bin/env bash
#
# A feature built in parts: one issue, one plan, one QA, and a pull request
# for each part.
#
# A feature too big for one review is split at step 1, at the person's word,
# into parts each reviewed on its own (plan_parts.py reads them from the plan).
# Built first, reviewed after the person has accepted the whole: a review
# spent on code the person has not seen is thrown away by the first large
# remark, and a person shown half a feature cannot judge it.
#
# Step 2 builds the parts one after another, each in a session of its own, on
# a branch of its own, `<branch>-<n>`, made off the part before it (part 1 off
# the feature's branch, which stays where it left main). No pull request and
# no review between them: each part's session has its diff read by a fresh
# subagent (code.md), and ends on its own marker — or on the person's Accept
# when the project asks for a look at each part (`partAccept: each`). After
# the last part a session on its branch checks the whole feature as one, with
# the demo and the person's Accept (`parts.built`, then `parts.accepted`).
# Between two parts, the one just built is shown to the person in a demo of
# what it added (demo_part in demo.sh), so that their remarks reach the next
# part's session early; the whole feature's demo starts from those scenarios.
#
# Then steps 3 and 4 run once for each part, in the order they were built: the
# feature's branch becomes the parts' common branch, each part's pull request
# goes into it, is reviewed there — the review reads that diff alone, since
# the parts before it are in the base already — and is merged into it. The
# next part's branch takes the common branch in by a merge before its pull
# request opens (parts_enter), so that its diff is its own. Once every part is
# in (`parts.done`), step 3 opens the feature's own pull request into main,
# step 4 reviews the seams between the parts, and the rest of the cycle —
# preview, QA, merge, production — runs once for the whole feature.
#
# The state's `step` goes code for each part, code once more for the whole,
# then pr → review for each part (`parts.current` counts both rounds), so that the sessions and the review's
# machinery work unchanged; `branch` names the branch at work, and
# `parts.umbrella` the common one throughout.
#
# Everything GitHub could have changed by hand is checked before each move
# (parts_check): a base edited, a part merged before its review closed, a
# branch rewritten. A finding stops the cycle and says what to do; nothing is
# repaired behind the person's back.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Pushes <refspec> to origin within a minute, and on failure says <what>
# with git's own words under it — the product's pre-push hook runs here, and
# a refusal without what it found leaves nothing to go on — or that it timed
# out, which leaves no words.
#
#   parts_push <wt> <what> <refspec or push option>...
parts_push() {
  local push_out rc=0
  push_out="$(GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$1" push -q origin "${@:3}" 2>&1)" || rc=$?
  (( rc == 0 )) && return 0
  warn "  $2"
  (( rc == 124 )) && push_out="the push timed out after a minute"
  [[ -z "$push_out" ]] || warn "$(tail -n 12 <<< "$push_out" | sed 's/^/     /')"
  return 1
}

# Whether <ref> is all in origin's main — the common branch where it left
# main, before any part merged: such a push carries nothing for the
# product's pre-push hook to judge. A hook that looks at the tree's database
# finds every part's work there and would refuse the push whenever a part is
# not on GitHub — its push failed, say. A stale origin/main only says no.
#
#   parts_in_main <wt> <ref>
parts_in_main() {
  git -C "$1" merge-base --is-ancestor "$2" refs/remotes/origin/main 2>/dev/null
}

# Whether the feature is split, and where its parts stand.
#
#   parts_split <state>      — split into two or more parts
#   parts_open <state>       — split, and the last part not merged yet
#   parts_building <state>   — split, and a part still being built (step 2)
#   parts_whole <state>      — every part built: step 2 checks the whole
#   parts_reviewing <state>  — built and accepted: a part's pull request and
#                              review (steps 3 and 4)
parts_split() {
  local total; total="$(state_get "$1" parts.total 2>/dev/null || true)"
  [[ "$total" =~ ^[0-9]+$ && "$total" -ge 2 ]]
}

parts_open() {
  parts_split "$1" && [[ "$(state_get "$1" parts.done 2>/dev/null || true)" != "true" ]]
}

parts_building() {
  parts_open "$1" && [[ "$(state_get "$1" parts.built 2>/dev/null || true)" != "true" ]]
}

parts_whole() {
  parts_open "$1" && ! parts_building "$1" \
    && [[ "$(state_get "$1" parts.accepted 2>/dev/null || true)" != "true" ]]
}

parts_reviewing() {
  parts_open "$1" && [[ "$(state_get "$1" parts.accepted 2>/dev/null || true)" == "true" ]]
}

# The last part the feature is built with: the plan's last, or the one before
# the first the person left out (cmd_parts stop).
parts_last() {
  local dropped; dropped="$(state_get "$1" parts.dropped 2>/dev/null || true)"
  if [[ "$dropped" =~ ^[0-9]+$ ]]; then echo $((dropped - 1)); else state_get "$1" parts.total; fi
}

# The part at work, its branch, and the common branch.
parts_now() { state_get "$1" parts.current 2>/dev/null || true; }
parts_umbrella() { state_get "$1" parts.umbrella 2>/dev/null || true; }
parts_branch() { printf '%s-%s\n' "$1" "$2"; }

# "part 2/3" while a part is built or reviewed, nothing otherwise.
parts_label() {
  parts_building "$1" || parts_reviewing "$1" || return 0
  printf 'part %s/%s\n' "$(parts_now "$1")" "$(parts_last "$1")"
}

# The branch the pull request at work goes into, which is what its review
# reads against: the common branch while the parts are reviewed, main after.
#
#   parts_base <state>
parts_base() {
  if parts_reviewing "$1"; then parts_umbrella "$1"; else echo main; fi
}

# What a part at work is built on: the branch of the part before it, the
# common branch for part 1.
#
#   parts_below <state> <n>
parts_below() {
  if [[ "$2" -le 1 ]]; then parts_umbrella "$1"; else parts_branch "$(parts_umbrella "$1")" $(($2 - 1)); fi
}

# The plan's parts, into the state, as step 2 starts: once, when the plan
# first says it is split, or again while part 1 is still being built (a
# replan) — and undone when such a replan no longer splits it. Only a feature
# that has not opened its pull request: one further on is not split under it.
#
#   parts_capture <wt>
parts_capture() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" plan="$1/.sclaude/local/feature/plan.md"
  local listed total n title pr
  [[ -f "$plan" && -f "$state" ]] || return 0
  listed="$(python3 "$LIB/cycle/plan_parts.py" list "$plan" 2>/dev/null || true)"
  if parts_split "$state"; then
    # Under way: a part with a pull request or past it holds the lines where
    # they are, and a replan's new count is the person's to bring here.
    n=1
    parts_building "$state" && [[ "$(parts_now "$state")" == 1 ]] || return 0
    if [[ -z "$listed" ]]; then
      parts_uncapture "$wt"
      return
    fi
  else
    [[ -n "$listed" ]] || return 0
    pr="$(state_get "$state" pr 2>/dev/null || true)"
    if [[ -n "$pr" && "$pr" != null ]]; then
      [[ "$(cd "$wt" && gh pr view "$pr" --json state --jq .state 2>/dev/null)" == OPEN ]] \
        && warn "  The plan splits the feature, but its pull request #$pr is open already: it stays one pull request."
      return 0
    fi
    state_set "$state" parts.umbrella "$(state_get "$state" branch)"
    state_set "$state" parts.current 1
    state_set "$state" parts.done false
    info "  The plan splits the feature into $(printf '%s\n' "$listed" | grep -c .) parts, built one after another; once you"
    info "  accept the whole, each gets a pull request of its own into $(state_get "$state" branch), reviewed alone."
  fi
  total="$(printf '%s\n' "$listed" | grep -c .)"
  state_set "$state" parts.total "$total"
  while IFS=$'\t' read -r n title; do
    [[ -n "$n" ]] && state_set "$state" "parts.$n.title" "${title:-part $n}"
  done <<< "$listed"
  history_add "$state" parts capture total="$total"
}

# A replan that no longer splits the feature, before part 1 had a pull
# request: part 1's work goes back onto the feature's branch (a fast-forward:
# the part was made off it) and the parts leave the state. Over uncommitted
# work the tree stays where it is and the person is told.
#
#   parts_uncapture <wt>
parts_uncapture() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" umbrella part here
  umbrella="$(parts_umbrella "$state")"; part="$(parts_branch "$umbrella" 1)"
  here="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
  if git -C "$wt" rev-parse -q --verify "refs/heads/$part" >/dev/null; then
    if [[ "$here" != "$part" && "$here" != "$umbrella" ]]; then
      warn "  The plan is no longer split, and part 1's work is on $part: put the tree on $umbrella or $part, then run $SELF again."
      return 1
    fi
    if [[ -n "$(worktree_dirt "$wt")" ]]; then
      warn "  The plan is no longer split, and the tree has uncommitted work: commit it, then run $SELF again."
      return 1
    fi
    { [[ "$here" == "$umbrella" ]] || git -C "$wt" switch -q "$umbrella"; } \
      && git -C "$wt" merge -q --ff-only "$part" \
      && git -C "$wt" branch -q -D "$part" \
      || { warn "  Could not bring $part back onto $umbrella: do it by hand, then run $SELF again."; return 1; }
  fi
  state_set "$state" branch "$umbrella"
  state_set "$state" parts null
  history_add "$state" parts uncapture
  info "  The plan is no longer split: the feature is one pull request again, on $umbrella."
}

# Puts the tree where the step at work runs, before its session starts:
#
#   - a part being built (step 2): its own branch, made off the part before it
#     the first time (part 1 off the common branch), switched to after that;
#   - the whole feature checked (step 2, after the last part): the last
#     part's branch, which carries every part;
#   - a part reviewed (steps 3 and 4): its branch, with the part before it as
#     its review left it and the common branch merged in, so that its pull
#     request's diff is the part alone (parts_take_common).
#
# A feature whose plan was split after its code began on the common branch
# itself — the parts came in after step 2 started — has that work taken as
# part 1: `<branch>-1` is made at its head and the common branch put back
# where it left main. Only while the common branch is not on GitHub past that
# point: a pushed branch is not moved under anybody.
#
# Never over uncommitted work or a merge under way: the step is not started,
# and the person is told why.
#
#   parts_enter <wt>   → 1 when the tree could not be put there
parts_enter() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json"
  local umbrella n part here base remote below b
  parts_open "$state" || return 0
  umbrella="$(parts_umbrella "$state")"; n="$(parts_now "$state")"
  [[ -n "$umbrella" && "$n" =~ ^[0-9]+$ ]] || return 0
  parts_whole "$state" && n="$(parts_last "$state")"
  part="$(parts_branch "$umbrella" "$n")"
  here="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
  if [[ "$here" != "$part" ]]; then
    if [[ -n "$(worktree_dirt "$wt")" ]] || merge_under_way "$wt"; then
      warn ""
      warn "  This step works on $part, and the tree is on ${here:-a detached HEAD}"
      warn "  with uncommitted work or a merge under way: commit it or put it away, then run $SELF again."
      return 1
    fi
    GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" fetch origin -q 2>/dev/null || true
    below="$(parts_below "$state" "$n")"
    if git -C "$wt" rev-parse -q --verify "refs/heads/$part" >/dev/null; then
      git -C "$wt" switch -q "$part" 2>/dev/null || { warn "  Could not switch the tree to $part."; return 1; }
    elif ! parts_building "$state"; then
      warn ""
      warn "  Part $n was built on $part, and the branch is gone from this machine."
      warn "  Bring it back (git -C $wt switch $part, from GitHub or the reflog), then run $SELF again."
      return 1
    elif [[ "$here" == "$below" ]]; then
      base="$(git -C "$wt" merge-base origin/main HEAD 2>/dev/null || true)"
      remote="$(git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$umbrella" 2>/dev/null || true)"
      if [[ "$n" == 1 && -n "$base" && "$(git -C "$wt" rev-parse HEAD)" != "$base" ]]; then
        # Work made on the common branch before the split: it becomes part 1.
        if [[ -n "$remote" && "$remote" != "$base" ]]; then
          warn ""
          warn "  $umbrella carries this feature's work and is on GitHub, so it cannot be made"
          warn "  the parts' common branch by moving it back. Make $part from it by hand, put"
          warn "  $umbrella back at $(git -C "$wt" rev-parse --short "$base") (git push --force-with-lease), then run $SELF again."
          return 1
        fi
        git -C "$wt" switch -q -c "$part" || { warn "  Could not make $part."; return 1; }
        git -C "$wt" branch -f "$umbrella" "$base" >/dev/null 2>&1 \
          || { warn "  Could not put $umbrella back where it left main."; return 1; }
        info "  The work so far is part 1, on $part; $umbrella is the parts' common branch."
        history_add "$state" parts adopt part="$n"
      else
        git -C "$wt" switch -q -c "$part" || { warn "  Could not make $part."; return 1; }
      fi
    else
      warn ""
      warn "  This feature's part $n is built on $part, off $below, and the tree is on ${here:-a detached HEAD}."
      warn "  Put it on $below (or on $part), then run $SELF again."
      return 1
    fi
  fi
  # The state names the part's branch before anything below reads it: a sync
  # session reads `branch` for the branch it merges into.
  parts_on "$state" "$n" "$part"
  if parts_reviewing "$state"; then
    parts_take_common "$wt" "$state" "$n" || return 1
    local heads k refs=()
    heads="$(GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" ls-remote --heads origin 2>/dev/null || true)"
    # The parts not yet reviewed go up together, those not on GitHub yet:
    # the tree holds the work of every part — a database migrated by all of
    # them, say — and a pre-push hook that asks whether a branch on GitHub
    # carries that work refuses a part pushed alone while the later parts
    # are on this machine only. One push hands the hook every part at once,
    # atomic: a hook that passed the parts for each other must not see origin
    # take some and refuse the rest.
    for (( k = n; k <= $(parts_last "$state"); k++ )); do
      b="$(parts_branch "$umbrella" "$k")"
      git -C "$wt" rev-parse -q --verify "refs/heads/$b" >/dev/null || continue
      grep -q "[[:space:]]refs/heads/$b\$" <<< "$heads" || refs+=("refs/heads/$b:refs/heads/$b")
    done
    (( ${#refs[@]} )) && { parts_push "$wt" \
      "Could not push the parts' branches: each part's pull request comes from its own (git push origin ${refs[*]%%:*})." \
      --atomic "${refs[@]}" || true; }
    # The pull request goes into the common branch, so GitHub has to have it.
    if ! grep -q "[[:space:]]refs/heads/$umbrella\$" <<< "$heads"; then
      local verify=()
      parts_in_main "$wt" "refs/heads/$umbrella" && verify=(--no-verify)
      parts_push "$wt" \
        "Could not push $umbrella: the part's pull request needs it on GitHub (git push origin $umbrella)." \
        "refs/heads/$umbrella:refs/heads/$umbrella" "${verify[@]}" || true
    fi
  fi
  if parts_whole "$state"; then
    [[ "$here" == "$part" ]] || info "  Every part is built: the whole feature, on $part."
  elif parts_reviewing "$state"; then
    info "  Part $n of $(parts_last "$state"): ${BOLD}$(state_get "$state" "parts.$n.title" 2>/dev/null)${OFF} — its pull request, from $part into $umbrella."
  else
    info "  Part $n of $(parts_last "$state"): ${BOLD}$(state_get "$state" "parts.$n.title" 2>/dev/null)${OFF} — on $part, off $below."
  fi
  return 0
}

# A part about to be reviewed takes in what the reviews before it left, by
# merges, so that its pull request into the common branch shows the part
# alone, the merges' resolutions with it:
#
#   1. the part before it, as its review left it — the head its pull request
#      was squashed from, by GitHub's word or origin's copy of the branch,
#      never the local branch: a commit put on it afterwards was never
#      reviewed.
#      This part was built on that part's commits from before its review, so
#      the review's changes, a revert or a file deleted included, come in as
#      changes. Merged from the common branch alone, whose base is from before
#      every part, a change this part already carries would win over the
#      review's undoing of it, without a conflict. A head that cannot be found
#      holds the part rather than skip this;
#   2. the common branch, commit by commit on its first parent: the part
#      before's merge there — a squash, a merge commit, or its commits
#      rebased one by one, found by the tree it leaves — recorded as merged
#      (`-s ours`; the
#      earlier ones are in its head already) — its content is here by 1, and
#      merged again from a base before every part it would conflict on every
#      line this part changed in an earlier part's code — and everything else
#      merged: main synced there between parts, a commit put there by hand.
#
# A merge that would stop on conflicts — the common case at 1: a review's fix
# meeting this part's use of the same code — goes to the sync session
# (parts_merge_in). A merge left under way by a sync broken off is carried on
# first, with what MERGE_HEAD says it merges. The common branch is fetched
# first: it may have moved on GitHub since the tree was last put here.
#
#   parts_take_common <wt> <state> <n>   → 1 when the part waits
parts_take_common() {
  local wt="$1" state="$2" n="$3" umbrella part prev="" pr head="" slug c mh said
  umbrella="$(parts_umbrella "$state")"; part="$(parts_branch "$umbrella" "$n")"
  slug="$(state_get "$state" feature 2>/dev/null || true)"
  GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" fetch -q origin "$umbrella" 2>/dev/null || true
  if [[ "$n" -gt 1 ]]; then
    prev="$(parts_branch "$umbrella" $((n - 1)))"
    # The reviewed head of the part before: what GitHub says its pull
    # request merged (parts_head answers a hash only when GitHub did and the
    # commit is here). Not origin's copy of the branch while a pull request
    # is on record: GitHub may have deleted the branch on merge, leaving the
    # copy from before a suggestion committed there. Never the local branch,
    # which may lack such a commit or carry one nobody reviewed. Only with
    # no pull request on record (the part merged by hand), origin's branch,
    # fetched now into a ref of sclaude's own, emptied first — never
    # origin/<part> left from an earlier fetch: the parts' branches go up
    # before their reviews (parts_enter), so a branch GitHub deleted on merge
    # leaves that copy at the head from before the review. Nor FETCH_HEAD,
    # which a setting stops git writing and any other fetch rewrites. A fetch
    # that fails is told apart: the branch gone, or origin not reached. The
    # earlier parts' squashes are in it already: that part took them in the
    # same way.
    local below=$((n - 1)) own unreached=""
    pr="$(state_get "$state" "parts.$below.pr" 2>/dev/null || true)"
    if [[ -n "$pr" && "$pr" != null ]]; then
      head="$(parts_head "$wt" "$pr" "")"
    else
      own="refs/sclaude/parts/$prev"
      git -C "$wt" update-ref -d "$own" 2>/dev/null || true
      if GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" fetch -q origin "+refs/heads/$prev:$own" 2>/dev/null; then
        head="$(git -C "$wt" rev-parse -q --verify "$own^{commit}" 2>/dev/null || true)"
      else
        local listed=0
        GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" ls-remote -q --exit-code --heads origin "refs/heads/$prev" >/dev/null 2>&1 || listed=$?
        (( listed == 2 )) || unreached=1
      fi
      git -C "$wt" update-ref -d "$own" 2>/dev/null || true
    fi
    if [[ ! "$head" =~ ^[0-9a-f]{40}$ ]]; then
      warn ""
      warn "  Part $n takes part $((n - 1)) in as its review left it, and sclaude cannot find that head:"
      if [[ -n "$pr" && "$pr" != null ]]; then
        warn "  GitHub did not say what PR #$pr merged, or its head could not be fetched"
        warn "  (refs/pull/$pr/head). The part waits: run $SELF again once GitHub answers."
      elif [[ -n "$unreached" ]]; then
        warn "  $prev could not be fetched from origin (no answer, or refused)."
        warn "  The part waits: run $SELF again once origin answers."
      else
        warn "  no pull request of part $((n - 1)) is on record, and origin has no $prev."
        warn "  Push part $((n - 1)) as its review left it there (git push origin <commit>:refs/heads/$prev),"
        warn "  then run $SELF again."
      fi
      ask_feed say "⚠️ Part $n waits: the head part $((n - 1))'s review left is not found — see the terminal." 2>/dev/null || true
      return 1
    fi
    # By name when the local branch is that very commit: the session reads
    # a name better than a hash.
    [[ "$(git -C "$wt" rev-parse -q --verify "refs/heads/$prev" 2>/dev/null)" == "$head" ]] && head="$prev"
  fi
  # A merge broken off, carried on with what it merges.
  if merge_under_way "$wt"; then
    mh="$(git -C "$wt" rev-parse -q --verify MERGE_HEAD 2>/dev/null)"
    if [[ -n "$prev" && "$mh" == "$(git -C "$wt" rev-parse -q --verify "$head^{commit}" 2>/dev/null)" ]]; then
      parts_merge_in "$wt" "$slug" "$part" "$prev" "$mh" || return 1
    else
      parts_merge_in "$wt" "$slug" "$part" "$umbrella" "$mh" || return 1
    fi
  fi
  [[ -n "$prev" ]] && { parts_merge_in "$wt" "$slug" "$part" "$prev" "$head" || return 1; }
  # The part before's merge on the common branch is a run of its first
  # parent, from a commit c to a commit e whose tree is what c's parent and
  # the part's reviewed head make together: one commit for a squash or a
  # merge commit, the part's commits one by one for a rebase. Found by the
  # trees, not by each commit's patch, which moves with the lines around it.
  # Recorded as merged at e (`-s ours`), which takes the whole run.
  local -a walk=()
  mapfile -t walk < <(git -C "$wt" rev-list --first-parent --reverse "HEAD..refs/remotes/origin/$umbrella" 2>/dev/null)
  local i k want e
  for (( i = 0; i < ${#walk[@]}; i++ )); do
    c="${walk[$i]}"
    git -C "$wt" merge-base --is-ancestor "$c" HEAD 2>/dev/null && continue
    e=""
    if [[ -n "$prev" ]]; then
      want="$(git -C "$wt" merge-tree --write-tree "$c^1" "$head" 2>/dev/null | head -1)"
      for (( k = i; k < ${#walk[@]}; k++ )); do
        [[ "$(git -C "$wt" rev-parse "${walk[$k]}^{tree}" 2>/dev/null)" == "$want" ]] && { e="${walk[$k]}"; break; }
      done
    fi
    if [[ -n "$e" ]]; then
      if [[ -n "$(worktree_dirt "$wt")" ]]; then
        warn ""
        warn "  $part has to take $umbrella in before its pull request, and the tree has uncommitted"
        warn "  work: commit it or put it away, then run $SELF again."
        return 1
      fi
      said="$(git -C "$wt" merge -q -s ours --no-edit -m "Merge $umbrella: part $((n - 1))'s merge there, already here" "$e" 2>&1)" || {
        warn "  Could not record part $((n - 1))'s merge in $part:"
        printf '%s\n' "$said" | tail -5 | sed 's/^/    /'
        ask_feed say "⚠️ Part $n waits: its branch does not take $umbrella in yet — see the terminal." 2>/dev/null || true
        return 1
      }
      continue
    fi
    parts_merge_in "$wt" "$slug" "$part" "$umbrella" "$c" || return 1
  done
  return 0
}

# One merge into a part's branch (parts_take_common): nothing when it is in
# already; a plain merge when it goes cleanly; otherwise the sync session
# (sync_with_main in sync.sh) with <name> as what it merges (SYNC_FROM, and
# <ref> as the revision, SYNC_REF, when it is not origin's <name>): the same
# session, watch and friction review as a sync with main. A merge left under
# way, by a sync broken off, goes there too, and is carried on. No session
# opens on a half-merged tree, and nothing is pushed over the part's branch on
# origin.
#
#   parts_merge_in <wt> <slug> <part> <name> <ref|"">   → 1 when the part waits
parts_merge_in() {
  local wt="$1" slug="$2" part="$3" name="$4" ref="$5" rev rc=0
  local SYNC_FROM="$name" SYNC_REF="$ref"
  rev="$(sync_source 2>/dev/null || echo "${ref:-origin/$name}")"
  if ! git -C "$wt" rev-parse -q --verify "$rev^{commit}" >/dev/null; then
    rev="refs/heads/$name"
    git -C "$wt" rev-parse -q --verify "$rev" >/dev/null || return 0
    SYNC_REF="$rev"
  fi
  if ! merge_under_way "$wt"; then
    git -C "$wt" merge-base --is-ancestor "$rev" HEAD 2>/dev/null && return 0
    if [[ -n "$(worktree_dirt "$wt")" ]]; then
      warn ""
      warn "  $part has to take $name in before its pull request, and the tree has uncommitted"
      warn "  work: commit it or put it away, then run $SELF again."
      return 1
    fi
    if git -C "$wt" merge -q --no-edit -m "Merge $name into $part" "$rev" >/dev/null 2>&1; then
      info "  $name merged into $part."
      return 0
    fi
    git -C "$wt" merge --abort >/dev/null 2>&1 || true
  fi
  if ! declare -F sync_with_main >/dev/null; then
    warn ""
    warn "  $part does not take $name in without conflicts. Merge it by hand, or in a Claude session:"
    warn "    git -C $wt merge $rev"
    warn "  commit the merge, then run $SELF again."
    return 1
  fi
  info "  $part does not take $name in without conflicts: a session resolves them."
  sync_with_main "$wt" "$slug" || rc=$?
  # 0: merges cleanly as it stands; 3: merged by the session.
  if [[ "$rc" -eq 0 || "$rc" -eq 3 ]] && git -C "$wt" merge-base --is-ancestor "$rev" HEAD 2>/dev/null; then
    info "  $name merged into $part."
    return 0
  fi
  if [[ "$rc" -eq 0 ]]; then
    # The check found no conflict, or could not tell (no network, an old
    # git), and the merge here stops all the same — on a file in the way, a
    # hook: nothing a session was opened for. Git says why.
    local said
    said="$(git -C "$wt" merge --no-edit -m "Merge $name into $part" "$rev" 2>&1)" && {
      info "  $name merged into $part."; return 0; }
    merge_under_way "$wt" && git -C "$wt" merge --abort >/dev/null 2>&1
    warn ""
    warn "  $part does not take $name in, and no conflict was found for a session to resolve."
    printf '%s\n' "$said" | tail -5 | sed 's/^/    /'
    warn "  Clear that, or merge by hand (git -C $wt merge $rev), then run $SELF again."
  fi
  ask_feed say "⚠️ Part ${part##*-} waits: its branch does not take $name in yet — see the terminal." 2>/dev/null || true
  return 1
}

# The state follows the tree onto a part's branch.
parts_on() {
  local state="$1" n="$2" part="$3"
  [[ "$(state_get "$state" branch 2>/dev/null || true)" == "$part" ]] || state_set "$state" branch "$part"
  [[ "$(state_get "$state" "parts.$n.branch" 2>/dev/null || true)" == "$part" ]] \
    || state_set "$state" "parts.$n.branch" "$part"
}

# What GitHub says of the parts' pull requests, against what the cycle
# expects of them now: one line per thing wrong, nothing when all holds.
# Nothing to say while the parts are built and the whole checked: no part has
# a pull request yet.
#
#   - each part's pull request goes into the common branch;
#   - the parts before the one at work are merged; the one at work is open,
#     and a draft until its review closes (<moment> `merge`: about to merge);
#   - what GitHub has of the part's branch is what the tree has, or behind
#     it: a branch rewritten there (a rebase from its page) or moved on by
#     somebody else is not pushed over, nor built on;
#   - after the parts (<moment> `final`): every part merged, none left open,
#     and the common branch on GitHub.
#
# Each line says what to do; parts_check_say prints them. Read from GitHub on
# every call: what matters is what somebody may have pressed since.
#
#   parts_check <wt> [merge|final]   → the lines; 1 when there are any, 2 when GitHub did not answer
parts_check() {
  local wt="$1" moment="${2:-}" state="$1/.sclaude/local/feature/state.json"
  local umbrella n now total pr json base pstate draft head local_head done_flag out=""
  parts_split "$state" || return 0
  [[ "$moment" == final ]] || parts_reviewing "$state" || return 0
  umbrella="$(parts_umbrella "$state")"; now="$(parts_now "$state")"
  # Parts the person left out (cmd_parts stop) are not the cycle's any more.
  total="$(parts_last "$state")"
  done_flag="$(state_get "$state" parts.done 2>/dev/null || true)"
  [[ "$done_flag" == true ]] && now=$((total + 1))
  for (( n = 1; n <= total && n <= now; n++ )); do
    pr="$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)"
    if [[ -z "$pr" || "$pr" == null ]]; then
      (( n < now )) && out+="Part $n has no pull request on record, and the parts after it were begun: open it into $umbrella, or tell sclaude its number."$'\n'
      continue
    fi
    json="$(cd "$wt" && gh pr view "$pr" --json baseRefName,state,isDraft,headRefOid 2>/dev/null)" || return 2
    IFS=$'\t' read -r base pstate draft head < <(printf '%s' "$json" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("\t".join([d.get("baseRefName") or "", d.get("state") or "", str(d.get("isDraft")).lower(), d.get("headRefOid") or ""]))')
    if [[ "$base" != "$umbrella" && "$pstate" != MERGED ]]; then
      out+="PR #$pr (part $n) goes into $base, not $umbrella: put it back with  gh pr edit $pr --base $umbrella"$'\n'
    fi
    if (( n < now )); then
      [[ "$pstate" == MERGED ]] && [[ "$base" == "$umbrella" ]] && continue
      case "$pstate" in
        MERGED) out+="PR #$pr (part $n) was merged into $base, not $umbrella: bring its commits into $umbrella by hand."$'\n' ;;
        CLOSED) out+="PR #$pr (part $n) was closed without merging, after its review: reopen it (gh pr reopen $pr), or drop the part from the plan."$'\n' ;;
        *)      out+="PR #$pr (part $n) is still open, and its part is behind: merge it into $umbrella  (gh pr merge $pr --squash)."$'\n' ;;
      esac
      continue
    fi
    # The part at work.
    case "$pstate" in
      MERGED) out+="PR #$pr (part $n) was merged by hand before its review closed."$'\n'; continue ;;
      CLOSED) out+="PR #$pr (part $n) was closed by hand: reopen it (gh pr reopen $pr), or drop the part from the plan."$'\n'; continue ;;
    esac
    if [[ "$draft" != true && "$moment" != merge ]]; then
      out+="PR #$pr (part $n) was marked ready by hand before its review closed — nothing merges it but sclaude, once the review closes: put it back with  gh pr ready $pr --undo"$'\n'
    fi
    local_head="$(git -C "$wt" rev-parse -q --verify "refs/heads/$(parts_branch "$umbrella" "$n")" 2>/dev/null || true)"
    if [[ -n "$head" && -n "$local_head" && "$head" != "$local_head" ]] \
       && ! git -C "$wt" merge-base --is-ancestor "$head" "$local_head" 2>/dev/null; then
      if git -C "$wt" cat-file -e "$head^{commit}" 2>/dev/null \
         && git -C "$wt" merge-base --is-ancestor "$local_head" "$head" 2>/dev/null; then
        out+="GitHub's $(parts_branch "$umbrella" "$n") is ahead of the tree (pushed from elsewhere, or updated from its page): take it with  git -C $wt merge --ff-only origin/$(parts_branch "$umbrella" "$n")"$'\n'
      else
        out+="GitHub's $(parts_branch "$umbrella" "$n") is not what the tree has: it was rewritten there (a rebase from its page?). Bring the two together by hand before the part goes on."$'\n'
      fi
    fi
  done
  if [[ "$moment" == final ]] \
     && [[ -z "$(GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" ls-remote --heads origin "$umbrella" 2>/dev/null)" ]]; then
    out+="$umbrella, the parts' common branch, is not on GitHub: was it deleted? Restore it from a merged part's page before the feature goes on."$'\n'
  fi
  [[ -n "$out" ]] || return 0
  printf '%s' "$out"
  return 1
}

# The check, said: nothing when all holds; the lines, and 1, when not. A
# GitHub that does not answer holds nothing up — the check is for hands, not
# for the network.
#
#   parts_check_say <wt> [moment]
parts_check_say() {
  local lines rc=0
  lines="$(parts_check "$@")" || rc=$?
  [[ "$rc" -eq 1 ]] || return 0
  echo ""
  warn "  The parts' pull requests are not where the cycle left them:"
  while IFS= read -r line; do
    [[ -n "$line" ]] && warn "  - $line"
  done <<< "$lines"
  ask_feed say "⚠️ The parts' pull requests changed on GitHub by hand — see the terminal." 2>/dev/null || true
  return 1
}

# The part at work's pull request was merged by hand before its review
# closed. Asked, not assumed: yes takes it as the review's end and goes on to
# the next part; no leaves it, and the review of what it carried can still be
# read in step 4, on the common branch.
#
#   parts_merged_early <wt> <slug>   → 0 when the cycle went on
parts_merged_early() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json" n pr answer
  n="$(parts_now "$state")"; pr="$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)"
  echo ""
  warn "  PR #$pr (part $n) was merged into $(parts_umbrella "$state") by hand, before its review closed."
  ask "${BOLD}Take it as the part's end and go on to the next part? Its open threads are read again in step 4. [y/n] ${OFF}" answer yn || return 1
  is_yes "$answer" || { info "  Left as it is. Come back with: $SELF $slug"; return 1; }
  history_add "$state" parts early part="$n"
  parts_advance "$wt" "$slug" merged
}

# The part's review closed: its pull request goes into the common branch, and
# the next part's pull request is opened — or, after the last one, the
# feature's own, from the common branch into main.
#
#   parts_advance <wt> <slug> [merged]   — `merged`: GitHub has merged it already
parts_advance() {
  local wt="$1" slug="$2" already="${3:-}" state="$1/.sclaude/local/feature/state.json"
  local umbrella n total pr method="" before="" after extra answer seen head=""
  umbrella="$(parts_umbrella "$state")"; n="$(parts_now "$state")"
  total="$(parts_last "$state")"
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != null ]] || pr="$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)"
  if [[ -z "$already" ]]; then
    parts_check_say "$wt" merge || { info "  Part $n waits. Come back with: $SELF $slug"; return 1; }
    method="$(merge_method)"
    before="$(git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$umbrella" 2>/dev/null || true)"
    # Kept until the check below has passed: a run cut off, or a "no" to it,
    # comes back to the same check.
    [[ -n "$before" ]] && state_set "$state" "parts.$n.before" "$before"
    (cd "$wt" && gh pr ready "$pr" >/dev/null 2>&1) || true
    # Squashed: the common branch keeps one commit a part, and its pull
    # request the part's own history. Another way where the repository
    # allows no squash: the next part finds the merge by the tree it leaves,
    # whichever way it went (parts_take_common).
    # Refused one way — a rebase over the part's merges, a way the
    # repository does not allow after all, or GitHub busy — the others are
    # tried, the preferred one first: at the person's word, landing the part
    # matters more than the way.
    local way merged_how=""
    for way in "$method" --squash --merge --rebase; do
      [[ "$way" == "$method" && -n "$merged_how" ]] && continue
      if (cd "$wt" && gh pr merge "$pr" "$way" >/dev/null 2>&1); then
        merged_how="$way"; break
      fi
      # Merged all the same (an answer lost on the way back): done.
      [[ "$(cd "$wt" && gh pr view "$pr" --json state --jq .state 2>/dev/null)" == MERGED ]] \
        && { merged_how="$way"; break; }
      merged_how="tried"
    done
    if [[ "$merged_how" == tried || -z "$merged_how" ]]; then
      warn "  PR #$pr (part $n) could not be merged into $umbrella in any way GitHub offers: see  gh pr view $pr"
      info "  Merge it, then come back with: $SELF $slug"
      return 1
    fi
    info "  PR #$pr (part $n) merged into $umbrella."
  fi
  # Once: a run cut off after the merge comes back here (run_step reads
  # `parts.<n>.merged`), and the merge is not recorded twice.
  seen="$(state_get "$state" "parts.$n.merged" 2>/dev/null || true)"
  if [[ -z "$seen" || "$seen" == null ]]; then
    state_set "$state" "parts.$n.pr" "$pr"
    state_set "$state" "parts.$n.merged" "$(date -Iseconds)"
    history_add "$state" parts merged part="$n" pr="$pr"
    ask_feed say "🧩 Part $n/$total merged into $umbrella (PR #$pr)." 2>/dev/null || true
  fi

  GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$wt" fetch origin -q 2>/dev/null || true
  git -C "$wt" switch -q "$umbrella" 2>/dev/null \
    || { warn "  Could not switch the tree to $umbrella."; return 1; }
  git -C "$wt" merge -q --ff-only "origin/$umbrella" 2>/dev/null \
    || { warn "  $umbrella here does not fast-forward to GitHub's: bring the two together, then run $SELF $slug"; return 1; }
  # Only the part came in: anything else on the common branch was put there
  # by hand, past every review, and is shown before the cycle builds on it.
  after="$(git -C "$wt" rev-parse HEAD)"
  before="$(state_get "$state" "parts.$n.before" 2>/dev/null || true)"
  if [[ "$before" != checked ]]; then
    head="$(parts_head "$wt" "$pr" "$(parts_branch "$umbrella" "$n")")"
    # Merged by hand, sclaude never saw the common branch before it: where
    # the part left it stands in.
    [[ -n "$before" && "$before" != null ]] \
      || before="$(git -C "$wt" merge-base "$head" "$after" 2>/dev/null || true)"
  fi
  if [[ "$before" != checked && -n "$before" ]]; then
    extra="$(parts_extra "$wt" "$before" "$after" "$head")"
    if [[ -n "$extra" ]]; then
      echo ""
      warn "  $umbrella carries commits no part brought:"
      printf '%s\n' "$extra" | sed 's/^/    /'
      ask "${BOLD}Go on with them in? They are reviewed with the rest in step 4. [y/n] ${OFF}" answer yn || return 1
      is_yes "$answer" || { info "  Left as it is. Come back with: $SELF $slug"; return 1; }
    fi
    state_set "$state" "parts.$n.before" checked
  fi
  state_set "$state" branch "$umbrella"
  parts_reset_steps "$state" "$n" pr review

  # Main into the common branch now, between parts, where no session is at
  # work: the next part takes it in with the parts before it (parts_enter),
  # and nothing piles up for the end.
  sync_branch "$wt" || { info "  The next part waits for the sync. Come back with: $SELF $slug"; return 1; }
  # Past the product's pre-push hook, as sync_with_main pushes its own merge
  # (sync.sh): the merged parts were reviewed in their pull requests and main
  # is origin's, while the tree's database holds every part's work, which
  # such a hook refuses the push for whenever a part is not on GitHub.
  if [[ "$(git -C "$wt" rev-parse HEAD)" != "$(git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$umbrella" 2>/dev/null)" ]]; then
    parts_push "$wt" "Could not push $umbrella after the sync: git -C $wt push origin $umbrella" \
      "HEAD:refs/heads/$umbrella" --no-verify || true
  fi

  if (( n < total )); then
    state_set "$state" parts.current $((n + 1))
    state_set "$state" step pr
    issue_sync "$wt"
    echo ""
    info "  On to part $((n + 1)) of $total: its pull request into $umbrella."
    run_step "$wt" "$slug" pr
  else
    state_set "$state" parts.done true
    state_set "$state" step pr
    issue_sync "$wt"
    echo ""
    info "  Every part is reviewed and in $umbrella: the feature's pull request into main,"
    info "  and a review of the seams between the parts."
    run_step "$wt" "$slug" pr
  fi
}

# A part's session closed and its regression is green: the part's demo is
# recorded and sent to the person (demo_part), and the next part is
# built — or, after the last one, step 2 checks the whole feature on the last
# part's branch, with the demo and the person's Accept, and the parts' pull
# requests follow from part 1.
#
#   parts_built <wt> <slug>
parts_built() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json" n last
  n="$(parts_now "$state")"; last="$(parts_last "$state")"
  history_add "$state" parts built part="$n"
  ask_feed say "🧩 Part $n/$last built." 2>/dev/null || true
  parts_reset_steps "$state" "$n" code
  state_set "$state" step code
  if (( n < last )); then
    state_set "$state" parts.current $((n + 1))
    issue_sync "$wt"
    # Shown to the person before the next part builds on it: a demo of what
    # the part added, recorded here between the parts (demo.sh). After the
    # state moved on: a recording cut off (Ctrl-C, a closed terminal) leaves
    # the next part to start, not this one to be built again.
    declare -F demo_part >/dev/null && demo_part "$wt" "$n"
    echo ""
    info "  On to part $((n + 1)) of $last."
  else
    state_set "$state" parts.built true
    state_set "$state" parts.current 1
    issue_sync "$wt"
    echo ""
    info "  Every part is built. Step 2 closes on the whole feature: checked as one, shown,"
    info "  and accepted by you; then each part's pull request, reviewed one by one."
  fi
  run_step "$wt" "$slug" code
}

# The commits the common branch took between <before> and <after>, by its
# first parent, that are not the part's: neither the part's whole change (a
# squash, or a merge commit read by its first parent) nor one of its own
# commits (a rebase merge). What is left was put there past the part's review.
# A rebase merge over such a commit may list the part's first commits too:
# there is something to look at either way.
#
#   parts_extra <wt> <before> <after> <part head>   → one "<sha> <subject>" a line
parts_extra() {
  local wt="$1" before="$2" after="$3" part="$4" known="" c id
  # Nothing came but the part: the common branch is what the part alone
  # makes of it, whatever way it was merged.
  [[ "$(git -C "$wt" merge-tree --write-tree "$before" "$part" 2>/dev/null | head -1)" \
     == "$(git -C "$wt" rev-parse "$after^{tree}" 2>/dev/null)" ]] && return 0
  if git -C "$wt" rev-parse -q --verify "$part^{commit}" >/dev/null; then
    known="$( { git -C "$wt" diff "$(git -C "$wt" merge-base "$before" "$part")" "$part"
                git -C "$wt" log -p --no-merges --format='commit %H' "$before..$part"; } 2>/dev/null \
              | git -C "$wt" patch-id --stable | cut -d' ' -f1)"
  fi
  for c in $(git -C "$wt" rev-list --first-parent "$before..$after" 2>/dev/null); do
    id="$(git -C "$wt" diff "$c^1" "$c" 2>/dev/null | git -C "$wt" patch-id --stable | cut -d' ' -f1)"
    [[ -n "$id" ]] && grep -qxF "$id" <<< "$known" && continue
    # A squash or a merge commit of the part over something else: its tree
    # is the part merged into its parent (a patch id differs by the context).
    [[ "$(git -C "$wt" merge-tree --write-tree "$c^1" "$part" 2>/dev/null | head -1)" \
       == "$(git -C "$wt" rev-parse "$c^{tree}")" ]] && continue
    git -C "$wt" log -1 --oneline "$c"
  done
}

# The head GitHub merged for a part's pull request: what was squashed, with
# a suggestion committed on GitHub or without a commit the tree never
# pushed. Fetched from the pull request's own ref when the machine lacks
# it; the local branch where GitHub cannot say.
#
#   parts_head <wt> <pr> <part branch>   → a commit or the branch's name
parts_head() {
  local wt="$1" pr="$2" part="$3" head
  head="$(cd "$wt" && gh pr view "$pr" --json headRefOid --jq .headRefOid 2>/dev/null || true)"
  if [[ "$head" =~ ^[0-9a-f]{40}$ ]]; then
    git -C "$wt" cat-file -e "$head^{commit}" 2>/dev/null \
      || GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" fetch -q origin "refs/pull/$pr/head" 2>/dev/null || true
    git -C "$wt" cat-file -e "$head^{commit}" 2>/dev/null && { echo "$head"; return; }
  fi
  echo "$part"
}

# The steps of a part closed, for the next part to start afresh: a new
# conversation for each step, a review's rounds counted again. The list of
# conversations stays (`runs`) — the issue's summary and the costs read it —
# and what the part's steps held is kept under the part. Only the steps
# named: `code` after a part is built, `pr review` after it is reviewed — the
# whole feature's step 2, and its Accept, stay while the parts are reviewed.
#
#   parts_reset_steps <state> <n> <step>...
parts_reset_steps() {
  PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$@" <<'PY'
import json, sys
path, n, names = sys.argv[1], sys.argv[2], sys.argv[3:]
import state_file
state_file.lock(path)
with open(path) as fh:
    data = json.load(fh)
steps = data.setdefault("steps", {})
part = data.setdefault("parts", {}).setdefault(n, {})
# Kept once for each step: a run cut off after this comes back, and finds
# the steps reset.
kept = part.setdefault("steps", {})
for s in names:
    if s not in kept and steps.get(s):
        kept[s] = steps.get(s)
    runs = (steps.get(s) or {}).get("runs")
    steps[s] = {"runs": runs} if runs else {}
if "pr" in names:
    for key in ("pr", "reopened", "reopened_pr", "reopened_by"):
        data[key] = None
state_file.write(path, data)
PY
}

# The parts' branches, for the clean-up: GitHub deletes a merged one itself
# where the repository says so, and these go from the machine too.
#
#   parts_branches <state>   → one name a line
parts_branches() {
  local state="$1" umbrella total n
  parts_split "$state" || return 0
  umbrella="$(parts_umbrella "$state")"; total="$(state_get "$state" parts.total)"
  for (( n = 1; n <= total; n++ )); do parts_branch "$umbrella" "$n"; done
}

# The parts' pull requests still open, for an abandoned feature.
#
#   parts_open_prs <wt>   → one number a line
parts_open_prs() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" total n pr
  parts_split "$state" || return 0
  total="$(state_get "$state" parts.total)"
  for (( n = 1; n <= total; n++ )); do
    pr="$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)"
    [[ -n "$pr" && "$pr" != null ]] || continue
    [[ "$(cd "$wt" && gh pr view "$pr" --json state --jq .state 2>/dev/null)" == OPEN ]] && echo "$pr"
  done
}

# The person ends a split feature with the parts built so far: the part at
# work and the ones after it are left out, and step 2 checks the whole on the
# last part kept, as after the last part. The whole-feature session is told
# which parts were left out (<if:parts-dropped>): it strikes their criteria,
# files them as an issue of their own, and takes them off the issue's list,
# so that QA tests what is built. Only while the parts are built: once the
# person has accepted the whole, what ships is a replan's to change.
#
#   cmd_parts <slug> stop
cmd_parts() {
  require_repo
  local slug="${1:-}" verb="${2:-}" wt state n total answer umbrella keep
  local ASK_SLUG="$slug"
  [[ -n "$slug" && "$verb" == stop ]] || die "usage: $SELF parts <name> stop"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"
  parts_open "$state" || die "feature '$slug' is not being built in parts"
  parts_building "$state" \
    || die "every part of '$slug' is built and the whole accepted: to leave a part out now, $SELF replan $slug"
  n="$(parts_now "$state")"; total="$(state_get "$state" parts.total)"
  umbrella="$(parts_umbrella "$state")"
  (( n > 1 )) || die "no part of '$slug' is built yet: nothing to ship. To change the plan: $SELF replan $slug"
  keep="$(parts_branch "$umbrella" $((n - 1)))"
  if [[ -n "$(worktree_dirt "$wt")" ]]; then
    die "the tree of '$slug' has uncommitted work: commit it or put it away first"
  fi
  echo ""
  echo "Feature '$slug' would ship with parts 1–$((n - 1)) of $total, built on $keep."
  info "  Part $n — and every part after it — is left out: its criteria are struck from the plan and the"
  info "  issue, and filed as an issue of their own. What part $n built stays on its branch."
  ask "${BOLD}End the parts here? [y/n] ${OFF}" answer yn
  is_yes "$answer" || { info "Left as it is."; return 0; }
  git -C "$wt" switch -q "$keep" || die "could not switch the tree to $keep"
  parts_reset_steps "$state" "$n" code
  # The count stays the plan's: the feature is still one built in parts,
  # and `parts.dropped` says from which part on they were left out.
  state_set "$state" parts.dropped "$n"
  state_set "$state" parts.built true
  state_set "$state" parts.current 1
  state_set "$state" branch "$keep"
  state_set "$state" step code
  history_add "$state" parts stop part="$n"
  issue_sync "$wt"
  info "  Step 2 closes on $keep: the whole of parts 1–$((n - 1)), checked as one."
  run_step "$wt" "$slug" code
}
