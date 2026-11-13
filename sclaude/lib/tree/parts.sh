#!/usr/bin/env bash
#
# A feature built in parts: one issue, one plan, one pull request, one QA,
# built part by part.
#
# A feature too big to build and show in one go is split at step 1, at the
# person's word, into parts (plan_parts.py reads them from the plan). The
# parts are for building and showing; the review reads the finished feature,
# cut into blocks of its own (review_blocks.sh).
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
# Accepted, the parts become one branch, the feature's (parts_join,
# `parts.done`): the parts are stacked, so the last part's branch carries
# them all. From there the feature is one like any other — its pull request
# into main at step 3, its review at step 4, which a feature this size reads
# in blocks — and the rest of the cycle runs once for the whole.
#
# The state's `step` goes code for each part, then code once more for the
# whole (`parts.current` counts the parts); `branch` names the branch at
# work, and `parts.umbrella` the feature's.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Whether the feature is split, and where its parts stand.
#
#   parts_split <state>      — split into two or more parts
#   parts_open <state>       — split, and the parts not yet one branch
#   parts_building <state>   — split, and a part still being built (step 2)
#   parts_whole <state>      — every part built: step 2 checks the whole
#   parts_joining <state>    — accepted, and the parts not yet one branch
#                              (parts_join was cut off, or runs now)
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

parts_joining() {
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

# "part 2/3" while a part is built, nothing otherwise.
parts_label() {
  parts_building "$1" || return 0
  printf 'part %s/%s\n' "$(parts_now "$1")" "$(parts_last "$1")"
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
    # Under way: a part built or past it holds the lines where
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
    info "  accept the whole, they become one branch, $(state_get "$state" branch), and one pull request."
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
#     part's branch, which carries every part.
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
  if parts_whole "$state"; then
    [[ "$here" == "$part" ]] || info "  Every part is built: the whole feature, on $part."
  else
    info "  Part $n of $(parts_last "$state"): ${BOLD}$(state_get "$state" "parts.$n.title" 2>/dev/null)${OFF} — on $part, off $below."
  fi
  return 0
}

# One merge into a part's branch (parts_join): nothing when it is in
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
      warn "  $part has to take $name in before the parts are one branch, and the tree has uncommitted"
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

# The whole accepted: the parts become one branch, the feature's, and the
# feature goes on as one — its pull request into main at step 3.
#
# The parts are stacked, so the last part's branch carries them all: the
# feature's branch is moved to it, and the tree with it. Where that branch
# took commits of its own since the parts left it — main synced in
# between — it is merged into the last part first, a session resolving
# the conflicts (parts_merge_in). Each part's commits are kept as a range (`parts.<n>.range`): the review's cut reads
# which part changed what. Cut off half-way, the next run comes back here
# (parts_joining) and goes on where it stopped.
#
#   parts_join <wt> <slug>   → 1 when the parts could not be joined yet
parts_join() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json"
  local umbrella last tip n b below from here
  umbrella="$(parts_umbrella "$state")"; last="$(parts_last "$state")"
  tip="$(parts_branch "$umbrella" "$last")"
  GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" fetch -q origin 2>/dev/null || true
  if ! git -C "$wt" rev-parse -q --verify "refs/heads/$tip" >/dev/null; then
    warn "  The last part's branch, $tip, is not on this machine: bring it back, then run $SELF $slug"
    return 1
  fi
  for (( n = 1; n <= last; n++ )); do
    [[ -n "$(state_get "$state" "parts.$n.range" 2>/dev/null || true)" ]] && continue
    b="$(parts_branch "$umbrella" "$n")"
    git -C "$wt" rev-parse -q --verify "refs/heads/$b" >/dev/null || continue
    below="$(parts_below "$state" "$n")"
    from="$(git -C "$wt" merge-base "$below" "$b" 2>/dev/null || true)"
    [[ -n "$from" ]] && state_set "$state" "parts.$n.range" "$from..$(git -C "$wt" rev-parse "$b")"
  done
  # On the last part's branch — or, a run cut off after the move, on the
  # feature's, which carries it already; a sync broken off on the last part
  # is carried on where it stands (parts_merge_in).
  here="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
  if [[ "$here" != "$tip" ]] && ! merge_under_way "$wt" \
     && ! { [[ "$here" == "$umbrella" ]] && git -C "$wt" merge-base --is-ancestor "$tip" HEAD 2>/dev/null; }; then
    if [[ -n "$(worktree_dirt "$wt")" ]]; then
      warn "  The parts become one branch on $tip, and the tree is on ${here:-a detached HEAD}"
      warn "  with uncommitted work: commit it or put it away, then run $SELF $slug"
      return 1
    fi
    git -C "$wt" switch -q "$tip" || { warn "  Could not switch the tree to $tip."; return 1; }
    here="$tip"
  fi
  # What the feature's branch holds that the parts do not: GitHub's copy
  # first, where main was synced in; the tree's when GitHub has none.
  local theirs="refs/remotes/origin/$umbrella"
  git -C "$wt" rev-parse -q --verify "$theirs" >/dev/null || theirs="refs/heads/$umbrella"
  if [[ "$here" == "$tip" ]] && ! git -C "$wt" merge-base --is-ancestor "$theirs" HEAD 2>/dev/null; then
    # The state names the branch the tree is on before the sync reads it
    # (parts_on): the session is told to merge into and push `branch`, and
    # the umbrella left there would send it to the wrong one.
    state_set "$state" branch "$tip"
    parts_merge_in "$wt" "$slug" "$tip" "$umbrella" "$theirs" || return 1
  fi
  if [[ "$here" == "$tip" ]]; then
    git -C "$wt" branch -q -f "$umbrella" HEAD \
      && git -C "$wt" switch -q "$umbrella" \
      || { warn "  Could not move $umbrella to $tip: do it by hand (git -C $wt branch -f $umbrella $tip), then run $SELF $slug"; return 1; }
  fi
  state_set "$state" branch "$umbrella"
  state_set "$state" parts.done true
  state_set "$state" step pr
  history_add "$state" parts joined total="$last"
  ask_feed say "🧩 The $last parts are one branch, $umbrella: the feature's pull request next." 2>/dev/null || true
  issue_sync "$wt"
  echo ""
  info "  The $last parts are one branch, $umbrella. Next: the feature's pull request into main."
  run_step "$wt" "$slug" pr
}

# A part's session closed and its regression is green: the part's demo is
# recorded and sent to the person (demo_part), and the next part is
# built — or, after the last one, step 2 checks the whole feature on the last
# part's branch, with the demo and the person's Accept, and the parts become
# one branch (parts_join).
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
    info "  and accepted by you; then one pull request for it all."
  fi
  run_step "$wt" "$slug" code
}

# The steps of a part closed, for the next part to start afresh: a new
# conversation for each step, a review's rounds counted again. The list of
# conversations stays (`runs`) — the issue's summary and the costs read it —
# and what the part's steps held is kept under the part. Only the steps
# named: `code` after a part is built.
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
