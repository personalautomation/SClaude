#!/usr/bin/env bash
#
# The issue's acceptance criteria as a step leaves them: synced to the
# issue, extended, reworded with the person.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The approved plan's acceptance criteria, copied into the issue — once.
#
# The orchestrator is the section's only writer, and it writes an empty one
# only: the seeded placeholder, a section with nothing in it, or none at all
# (a body a human wrote, an issue older than the section). Step 1 agrees the
# list inside the plan, and the hook on ExitPlanMode keeps a plan without one
# from being approved; what is left is putting it where it outlives the
# worktree and where QA ticks it. Doing that here rather than asking the
# session to means the markers are always ours.
#
# Once the issue has criteria, the issue is where corrections land: the human
# rewords one in GitHub, adds another, QA notes something under a third. A
# replan that starts from an older list must not write over that, so a plan
# that disagrees with the issue is reported, with what differs, and the human
# decides which side is right.
#
# Never a reason to hold the step. The plan keeps its own copy and every later
# step falls back to it.
sync_acceptance() {
  local wt="$1" slug="$2" ac_issue verdict out word line
  ac_issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"

  # The hook should have made this impossible. Should it have been bypassed —
  # an older session, a hook that failed open — the human hears it now rather
  # than finding an empty checklist at QA.
  verdict="$(python3 "$LIB/acceptance.py" --verdict "$wt/.sclaude/local/feature/plan.md" 2>/dev/null || true)"
  if [[ "$verdict" == "missing" || "$verdict" == "empty" ]]; then
    warn "  The approved plan has no acceptance criteria — nothing will say what \"done\" means."
    info "  To agree them now: $SELF replan $slug"
    return 0
  fi

  [[ -n "$ac_issue" && "$ac_issue" != "null" ]] || return 0
  out="$(python3 "$LIB/acceptance.py" --sync "$ac_issue" "$wt/.sclaude/local/feature/plan.md" "$wt" 2>/dev/null || true)"
  word="${out%%$'\n'*}"
  case "$word" in
    written)    info "  Acceptance criteria posted as a comment on issue #$ac_issue — QA ticks them there." ;;
    unchanged|nothing) ;;
    differs)    warn "  The plan's acceptance criteria differ from issue #$ac_issue — the issue was left as it is:"
                while IFS= read -r line; do info "    $line"; done < <(tail -n +2 <<<"$out")
                info "  The issue is where corrections land. If the plan is right, edit the criteria in GitHub." ;;
    torn)       warn "  The criteria comment on issue #$ac_issue has one marker without the other — nothing was written."
                info "  Mend the pair in GitHub (<!-- sclaude:ac --> … <!-- /sclaude:ac -->); the next approved plan writes them." ;;
    own-heading) warn "  Issue #$ac_issue already has an \"Acceptance criteria\" heading in its description — nothing was added."
                info "  The agreed list is in .sclaude/local/feature/plan.md; copy it there if QA should tick it." ;;
    *)          warn "  Could not write the acceptance criteria to issue #$ac_issue — they are in .sclaude/local/feature/plan.md only." ;;
  esac
}

# The criteria step 2 added to the plan, appended to the issue's list.
#
# Only new identifiers are written; a criterion worded differently in the plan
# is reported, as sync_acceptance reports it. Quiet when nothing changed: this
# runs after every code session, and as the review closes, with `reworded`.
#
#   extend_acceptance <wt> [reworded]
extend_acceptance() {
  local wt="$1" asked="${2:-}" ac_issue out word line details
  ac_issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"
  [[ -n "$ac_issue" && "$ac_issue" != "null" && -f "$wt/.sclaude/local/feature/plan.md" ]] || return 0
  out="$(python3 "$LIB/acceptance.py" --extend "$ac_issue" "$wt/.sclaude/local/feature/plan.md" "$wt" 2>/dev/null || true)"
  word="${out%%$'\n'*}"
  details="$(tail -n +2 <<<"$out")"
  # `reworded`: the caller asks about those itself (reword_acceptance), and
  # "edit them in GitHub" here would contradict its question.
  [[ "$asked" == reworded ]] && details="$(grep -v ' reads differently$' <<<"$details" || true)"
  case "$word" in
    written|extended)
                info "  Acceptance criteria on issue #$ac_issue updated from the plan:"
                while IFS= read -r line; do [[ -n "$line" ]] && info "    $line"; done <<<"$details" ;;
    unchanged|nothing) ;;
    differs)    [[ -n "$details" ]] || return 0
                warn "  The plan's acceptance criteria differ from issue #$ac_issue — only new ones are added:"
                while IFS= read -r line; do info "    $line"; done <<<"$details"
                info "  The issue is where corrections land. If the plan is right, edit the criteria in GitHub." ;;
    *)          warn "  Could not add the new acceptance criteria to issue #$ac_issue ($word) — they are in .sclaude/local/feature/plan.md only." ;;
  esac
}

# The criteria the review reworded in the plan, offered to the issue before QA.
#
# The review changes what a feature does at the person's word, and its session
# rewords the criterion in the plan (prompts/review.md). The issue keeps the old
# text — extend_acceptance writes only new criteria — and QA, or the automatic
# acceptance, then ticked a behaviour nobody built any more. Asked rather than
# written: a criterion the person reworded in GitHub reads differently from the
# plan too, and there the issue is right. A "no" is remembered for that same
# difference, so the question does not come back with every round.
#
#   reword_acceptance <wt>
reword_acceptance() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" plan="$1/.sclaude/local/feature/plan.md"
  local ac_issue out word details mark kept answer cid have want
  ac_issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ -n "$ac_issue" && "$ac_issue" != "null" && -f "$plan" ]] || return 0
  out="$(python3 "$LIB/acceptance.py" --reworded "$ac_issue" "$plan" "$wt" 2>/dev/null || true)"
  word="${out%%$'\n'*}"
  [[ "$word" == differs || "$word" == body ]] || return 0
  details="$(tail -n +2 <<<"$out")"
  mark="$(printf '%s' "$details" | sha1sum | cut -c1-16)"
  kept="$(state_get "$state" acceptance.kept 2>/dev/null || true)"
  [[ "$kept" == "$mark" ]] && return 0
  echo ""
  warn "  The plan words these acceptance criteria otherwise than issue #$ac_issue:"
  while IFS=$'\t' read -r cid have want; do
    info "    $cid in the issue: $have"
    info "    $cid in the plan:  $want"
  done <<<"$details"
  info "  QA ticks the issue's wording — a criterion changed in the review and left there is ticked as it was."
  if [[ "$word" == body ]]; then
    warn "  Issue #$ac_issue keeps its criteria in the description, which sclaude never writes: edit them there before QA."
    return 0
  fi
  ask "${BOLD}  Write the plan's wording into issue #$ac_issue? [y/n] ${OFF}" answer yn
  # Only a no is kept: no answer at all (no terminal, no channel) settles
  # nothing, and the question comes again at the next close.
  if is_no "$answer"; then
    state_set "$state" acceptance.kept "$mark" 2>/dev/null || true
    info "  Left as the issue says."
    return 0
  fi
  if ! is_yes "$answer"; then
    warn "  No answer: issue #$ac_issue keeps its wording, and this is asked again as the review next closes."
    return 0
  fi
  out="$(python3 "$LIB/acceptance.py" --reword "$ac_issue" "$plan" "$wt" 2>/dev/null || true)"
  case "${out%%$'\n'*}" in
    reworded) info "  Issue #$ac_issue now reads as the plan, those boxes empty again." ;;
    *)        warn "  Could not write issue #$ac_issue — edit those criteria in GitHub before QA." ;;
  esac
}
