#!/usr/bin/env bash
#
# A feature built in parts: one issue, one plan, one QA, and a pull request
# for each part.
#
# A feature too big for one review is split at step 1, at the person's word,
# into parts each reviewed on its own (plan_parts.py reads them from the plan).
# The feature's branch becomes the parts' common branch: each part is built on
# a branch of its own off it, `<branch>-<n>`, opened as a pull request into
# it, reviewed there as any pull request is — the review reads that diff
# alone, since the parts before it are in the base already — and merged into
# it. The next part starts from the common branch with the earlier parts in
# it. Nothing reaches main until every part is in: then step 2 closes as
# usual on the common branch (the person's word that it works, the demo),
# step 3 opens the feature's own pull request into main, step 4 reviews the
# seams between the parts, and the rest of the cycle — preview, QA, merge,
# production — runs once for the whole feature.
#
# The parts live inside step 2. The state's `step` goes code → pr → review for
# each part, so that the sessions and the review's machinery work unchanged;
# `parts.done` false says it is all step 2 (step_label, position). `branch`
# names the branch at work — the part's while the parts are built, the common
# one after — and `parts.umbrella` the common one throughout.
#
# Everything GitHub could have changed by hand is checked before each move
# (parts_check): a base edited, a part merged before its review closed, a
# branch rewritten. A finding stops the cycle and says what to do; nothing is
# repaired behind the person's back.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Whether the feature is split, and whether its parts are still being built.
#
#   parts_split <state>   — split into two or more parts
#   parts_open <state>    — split, and the last part not merged yet
parts_split() {
  local total; total="$(state_get "$1" parts.total 2>/dev/null || true)"
  [[ "$total" =~ ^[0-9]+$ && "$total" -ge 2 ]]
}

parts_open() {
  parts_split "$1" && [[ "$(state_get "$1" parts.done 2>/dev/null || true)" != "true" ]]
}

# The part at work, its branch, and the common branch.
parts_now() { state_get "$1" parts.current 2>/dev/null || true; }
parts_umbrella() { state_get "$1" parts.umbrella 2>/dev/null || true; }
parts_branch() { printf '%s-%s\n' "$1" "$2"; }

# "part 2/3" while the parts are built, nothing otherwise.
parts_label() {
  parts_open "$1" || return 0
  printf 'part %s/%s\n' "$(parts_now "$1")" "$(state_get "$1" parts.total 2>/dev/null)"
}

# The branch the pull request at work goes into, which is what its review
# reads against: the common branch while the parts are built, main after.
#
#   parts_base <state>
parts_base() {
  if parts_open "$1"; then parts_umbrella "$1"; else echo main; fi
}

# The plan's parts, into the state, as step 2 starts: once, when the plan
# first says it is split, or again while part 1 has no pull request yet (a
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
    [[ "$(parts_now "$state")" == 1 && "$(state_get "$state" parts.done 2>/dev/null || true)" != true ]] || return 0
    [[ -z "$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)" ]] || return 0
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
    info "  The plan splits the feature into $(printf '%s\n' "$listed" | grep -c .) parts: each gets a pull request of its own,"
    info "  reviewed alone, into $(state_get "$state" branch); the feature goes to main once, with all of them."
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

# Puts the tree on the part at work before its session starts: the branch
# made off the common branch the first time, switched to after that.
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
#   parts_enter <wt>   → 1 when the tree could not be put on the part
parts_enter() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json"
  local umbrella n part here base remote
  parts_open "$state" || return 0
  umbrella="$(parts_umbrella "$state")"; n="$(parts_now "$state")"
  [[ -n "$umbrella" && "$n" =~ ^[0-9]+$ ]] || return 0
  part="$(parts_branch "$umbrella" "$n")"
  here="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
  if [[ "$here" == "$part" ]]; then
    parts_on "$state" "$n" "$part"
    return 0
  fi
  if [[ -n "$(worktree_dirt "$wt")" ]] || merge_under_way "$wt"; then
    warn ""
    warn "  This feature's part $n is built on $part, and the tree is on ${here:-a detached HEAD}"
    warn "  with uncommitted work or a merge under way: commit it or put it away, then run $SELF again."
    return 1
  fi
  GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" fetch origin -q 2>/dev/null || true
  if git -C "$wt" rev-parse -q --verify "refs/heads/$part" >/dev/null; then
    git -C "$wt" switch -q "$part" 2>/dev/null || { warn "  Could not switch the tree to $part."; return 1; }
  elif [[ "$here" == "$umbrella" ]]; then
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
    warn "  This feature's part $n is built on $part, off $umbrella, and the tree is on ${here:-a detached HEAD}."
    warn "  Put it on $umbrella (or on $part), then run $SELF again."
    return 1
  fi
  # The pull request goes into the common branch, so GitHub has to have it.
  if [[ -z "$(GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$wt" ls-remote --heads origin "$umbrella" 2>/dev/null)" ]]; then
    GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$wt" push -q origin "refs/heads/$umbrella:refs/heads/$umbrella" 2>/dev/null \
      || warn "  Could not push $umbrella: the part's pull request needs it on GitHub (git push origin $umbrella)."
  fi
  parts_on "$state" "$n" "$part"
  info "  Part $n of $(state_get "$state" parts.total): ${BOLD}$(state_get "$state" "parts.$n.title" 2>/dev/null)${OFF} — on $part, into $umbrella."
  return 0
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
  umbrella="$(parts_umbrella "$state")"; now="$(parts_now "$state")"
  total="$(state_get "$state" parts.total)"
  done_flag="$(state_get "$state" parts.done 2>/dev/null || true)"
  [[ "$done_flag" == true ]] && now=$((total + 1))
  # Parts the person left out (cmd_parts stop) are not the cycle's any more.
  local dropped; dropped="$(state_get "$state" parts.dropped 2>/dev/null || true)"
  [[ "$dropped" =~ ^[0-9]+$ ]] && total=$((dropped - 1))
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
# the next part starts — or, after the last one, step 2 closes on the common
# branch with every part in it.
#
#   parts_advance <wt> <slug> [merged]   — `merged`: GitHub has merged it already
parts_advance() {
  local wt="$1" slug="$2" already="${3:-}" state="$1/.sclaude/local/feature/state.json"
  local umbrella n total pr method="" before="" after extra answer seen head=""
  umbrella="$(parts_umbrella "$state")"; n="$(parts_now "$state")"
  total="$(state_get "$state" parts.total)"
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != null ]] || pr="$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)"
  if [[ -z "$already" ]]; then
    parts_check_say "$wt" merge || { info "  Part $n waits. Come back with: $SELF $slug"; return 1; }
    before="$(git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$umbrella" 2>/dev/null || true)"
    # Kept until the check below has passed: a run cut off, or a "no" to it,
    # comes back to the same check.
    [[ -n "$before" ]] && state_set "$state" "parts.$n.before" "$before"
    (cd "$wt" && gh pr ready "$pr" >/dev/null 2>&1) || true
    # Squashed: the common branch keeps one commit a part, and its pull
    # request the part's own history. Another way where the repository
    # allows no squash.
    method="--squash"
    [[ "$(merge_method)" == "--squash" ]] || method="$(merge_method)"
    if ! (cd "$wt" && gh pr merge "$pr" "$method" >/dev/null 2>&1); then
      warn "  PR #$pr (part $n) could not be merged into $umbrella: see  gh pr view $pr"
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
  parts_reset_steps "$state" "$n"

  # Main into the common branch now, between parts, where no session is at
  # work: the next part starts on it, and nothing piles up for the end.
  sync_branch "$wt" || { info "  The next part waits for the sync. Come back with: $SELF $slug"; return 1; }
  if [[ "$(git -C "$wt" rev-parse HEAD)" != "$(git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$umbrella" 2>/dev/null)" ]]; then
    GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$wt" push -q origin "HEAD:refs/heads/$umbrella" 2>/dev/null \
      || warn "  Could not push $umbrella after the sync: git -C $wt push origin $umbrella"
  fi

  if (( n < total )); then
    state_set "$state" parts.current $((n + 1))
    state_set "$state" step code
    issue_sync "$wt"
    echo ""
    info "  On to part $((n + 1)) of $total."
    run_step "$wt" "$slug" code
  else
    state_set "$state" parts.done true
    state_set "$state" step code
    issue_sync "$wt"
    echo ""
    info "  Every part is in $umbrella. Step 2 closes on it: the whole feature, checked and shown,"
    info "  then the pull request into main."
    run_step "$wt" "$slug" code
  fi
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
# and what the part's steps held is kept under the part.
#
#   parts_reset_steps <state> <n>
parts_reset_steps() {
  PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$1" "$2" <<'PY'
import json, sys
path, n = sys.argv[1], sys.argv[2]
import state_file
state_file.lock(path)
with open(path) as fh:
    data = json.load(fh)
steps = data.setdefault("steps", {})
part = data.setdefault("parts", {}).setdefault(n, {})
# Kept once: a run cut off after this comes back, and finds the steps reset.
if not part.get("steps"):
    part["steps"] = {s: steps.get(s) for s in ("code", "pr", "review") if steps.get(s)}
for s in ("code", "pr", "review"):
    runs = (steps.get(s) or {}).get("runs")
    steps[s] = {"runs": runs} if runs else {}
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

# The person ends a split feature with the parts merged so far: the part at
# work and the ones after it are left out, and step 2 closes on the common
# branch as after the last part. The whole-feature session is told which
# parts were left out (<if:parts-dropped>): it strikes their criteria, files
# them as an issue of their own, and takes them off the issue's list, so
# that QA tests what is built.
#
#   cmd_parts <slug> stop
cmd_parts() {
  require_repo
  local slug="${1:-}" verb="${2:-}" wt state n total pr answer umbrella
  local ASK_SLUG="$slug"
  [[ -n "$slug" && "$verb" == stop ]] || die "usage: $SELF parts <name> stop"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"
  parts_open "$state" || die "feature '$slug' is not being built in parts"
  n="$(parts_now "$state")"; total="$(state_get "$state" parts.total)"
  umbrella="$(parts_umbrella "$state")"
  (( n > 1 )) || die "no part of '$slug' is merged yet: nothing to ship. To change the plan: $SELF replan $slug"
  if [[ -n "$(worktree_dirt "$wt")" ]]; then
    die "the tree of '$slug' has uncommitted work: commit it or put it away first"
  fi
  # A part already merged is in the feature: the cycle goes on from it.
  pr="$(state_get "$state" "parts.$n.pr" 2>/dev/null || true)"
  if [[ -n "$(state_get "$state" "parts.$n.merged" 2>/dev/null | grep -v '^null$' || true)" ]] \
     || { [[ -n "$pr" && "$pr" != null ]] \
          && [[ "$(cd "$wt" && gh pr view "$pr" --json state --jq .state 2>/dev/null)" == MERGED ]]; }; then
    die "part $n of '$slug' is merged already: run $SELF $slug to go on, and stop at the next part"
  fi
  echo ""
  echo "Feature '$slug' would ship with parts 1–$((n - 1)) of $total, already merged into $umbrella."
  info "  Part $n — and every part after it — is left out: its criteria are struck from the plan and the"
  info "  issue, and filed as an issue of their own. What part $n built stays on its branch."
  ask "${BOLD}End the parts here? [y/n] ${OFF}" answer yn
  is_yes "$answer" || { info "Left as it is."; return 0; }
  if [[ -n "$pr" && "$pr" != null ]]; then
    (cd "$wt" && gh pr close "$pr" --comment "Left out: the feature ships with the parts before this one; this part goes into an issue of its own." >/dev/null 2>&1) \
      && info "  PR #$pr (part $n) closed." || warn "  could not close PR #$pr — close it by hand"
  fi
  git -C "$wt" switch -q "$umbrella" || die "could not switch the tree to $umbrella"
  GIT_TERMINAL_PROMPT=0 timeout 60 git -C "$wt" fetch origin -q 2>/dev/null || true
  git -C "$wt" merge -q --ff-only "origin/$umbrella" 2>/dev/null || true
  state_set "$state" branch "$umbrella"
  parts_reset_steps "$state" "$n"
  # The count stays the plan's: the feature is still one built in parts,
  # and `parts.dropped` says from which part on they were left out.
  state_set "$state" parts.dropped "$n"
  state_set "$state" parts.done true
  state_set "$state" step code
  history_add "$state" parts stop part="$n"
  issue_sync "$wt"
  info "  Step 2 closes on $umbrella: the whole of parts 1–$((n - 1)), checked as one."
  run_step "$wt" "$slug" code
}
