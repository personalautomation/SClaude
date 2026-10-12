#!/usr/bin/env bash
#
# A retrospective over a finished feature, while everything it left is still there.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# cmd_done removes the worktree, and with it the last copy of a lot: the state,
# the plan, the friction logs, the record of the terminal (terminal.sh). So
# right before it asks, a Claude session reads all of that and answers three
# questions, from what is written there and nothing else:
#
#   1. what the person may have missed — a warning that scrolled past, a
#      question answered in a hurry, something promised and not done;
#   2. how the person could work better, by what actually happened;
#   3. what sclaude could do better, by what this feature ran into.
#
# With nothing in 1 and nothing in 3 the session closes itself (the done
# marker, as the friction review's), and its report is printed here. With
# anything to act on it stays open, and the person talks it through there:
# the worktree is still in place for whatever they decide to finish in it.
#
# What the conversation fixes in the project is committed on the feature's own
# branch. cmd_done then finds the commits (retro_changed_code) and puts the
# feature back on step 3 (retro_reopen): from there they go the way the
# feature's own did — pull request, review, preview, QA, merge — and the
# automatic review's findings reach a session like any other round's. Once a
# retrospective opened a pull request from a branch and worktree of its own
# instead; the review left two findings on it, and nothing
# in sclaude knew the pull request was there.
#
#   SCLAUDE_RETRO=off   skip it.

run_retro() {
  local wt="$1" slug="$2" pr="${3:-}" issue="${4:-}"
  [[ "${SCLAUDE_RETRO:-on}" != "off" ]] || return 0
  # A conversation needs somebody at the terminal; the epilogue run from a
  # timer or a phone has nobody to hold it open for.
  [[ -t 0 && -t 1 ]] || return 0
  [[ -f "$PROMPTS/retro.md" ]] || return 0
  # Once per pass through the review. A "no" to the clean-up brings `sclaude
  # done` back later, and the retrospective it already had would be paid for a
  # second time to say the same. One that never got going (dropped) or was cut
  # off leaves no finished run, and is offered again. But a retrospective that
  # changed the code sent the feature round the cycle again (retro_reopen), and
  # that second pull request, its review and its QA are new matter: a run that
  # started before step 4 last closed does not count.
  local fstate="$wt/.sclaude/local/feature/state.json"
  if [[ -f "$fstate" ]] && python3 - "$fstate" <<'PY' 2>/dev/null; then
import json, sys
from datetime import datetime
s = json.load(open(sys.argv[1]))
runs = ((s.get("retro") or {}).get("runs")) or []
closed = ((s.get("steps") or {}).get("review") or {}).get("finished")

def after_review(run):
    if not closed:
        return True
    try:
        return datetime.fromisoformat(run["started"]) >= datetime.fromisoformat(closed)
    except (KeyError, TypeError, ValueError):
        return True

sys.exit(0 if any(isinstance(r, dict) and r.get("done") and after_review(r)
                  for r in runs) else 1)
PY
    info "   The retrospective for '$slug' already took place (its row is in the issue); not running it again."
    return 0
  fi

  local terminal session done_file prompt
  terminal="$(term_render "$wt" 2>/dev/null || true)"
  session="$(new_session_id)"
  done_file="${TMPDIR:-/tmp}/sclaude-retro-$slug.done"

  prompt="$(SCLAUDE_V_TERMINAL="${terminal:-}" \
    SCLAUDE_V_TERMINAL_RAW="$wt/.sclaude/local/feature/terminal" \
    SCLAUDE_V_TRANSCRIPTS="$(transcript_dir "$wt")" \
    SCLAUDE_V_WORKTREE="$wt" \
    SCLAUDE_V_BRANCH="$(state_get "$fstate" branch 2>/dev/null || true)" \
    SCLAUDE_V_INSTRUMENTS="$INSTRUMENTS" \
    SCLAUDE_V_DONE_MARKER="$done_file" \
    render_prompt retro "$slug" "$pr" "$issue" "$wt")" || return 0

  echo ""
  echo "${BOLD}${BLUE}── $slug · a retrospective before the clean-up ──${OFF}"
  info "   opus / medium / auto · $wt"
  if [[ -n "$terminal" ]]; then
    info "   the terminal, as it was: $terminal"
  else
    info "   no terminal recording for this feature — it reads the state and the transcripts"
  fi
  info "   It closes by itself if it finds nothing to act on. SCLAUDE_RETRO=off skips it."
  echo ""

  [[ -f "$fstate" ]] && session_runs "$fstate" retro open "$session"
  local project_before project_after
  project_before="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"

  session_watch_start "" "$session" "$done_file" "$wt" retro
  local before_instruments; before_instruments="$(instruments_state)"
  local -a guard=()
  mapfile -t guard < <(review_guard_settings "$wt")
  ( cd "$wt" && claude_launch --session-id "$session" --model opus --effort medium \
      "${guard[@]}" \
      --permission-mode auto --add-dir "$INSTRUMENTS" --add-dir "$TERM_DIR" \
      --add-dir "$(cd "$wt" && term_dir)" \
      --add-dir "$HOME/.claude/projects" \
      -n "retro/$slug" "$prompt" )
  session_watch_stop
  instruments_unchanged "$before_instruments" "retrospective" || true
  session_closed "$done_file" "$wt" "$session" \
    "The retrospective found nothing to act on, and sclaude closed it." \
    || retro_report "$wt" "$session"

  if [[ -f "$fstate" ]]; then
    if session_started "$wt" "$session"; then
      session_runs "$fstate" retro finish "$session"
    else
      session_runs "$fstate" retro drop "$session"
    fi
  fi

  # Whether the conversation changed the project's code. Kept in the state
  # rather than in a variable: a "no" to the clean-up, or a run cut off before
  # cmd_done got to it, brings `done` back later without a retrospective, and the
  # commits still need their pull request (retro_changed_code).
  project_after="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"
  if [[ -f "$fstate" && -n "$project_before" && -n "$project_after" \
        && "$project_before" != "$project_after" ]]; then
    state_set "$fstate" retro.project_from "$project_before"
    state_set "$fstate" retro.project_to "$project_after"
  fi

  # sclaude's checkout is read-only to the conversation (review_guard_settings):
  # what it changes is the product's, and the branch above carries it.
  return 0
}

# Commits on the feature's branch that its merged pull request did not carry,
# when the retrospective made any — or nothing.
#
#   retro_changed_code <wt> <branch>  → their count, or nothing
#
# Only when the retrospective changed the code: a branch can carry other commits
# past the merge (an unpushed regression fix, say), and those are not
# what this sends back to step 3. Once the second pull request is merged, its
# head carries the commits and the count is nothing again.
#
# Counted from the merged pull request's head rather than from origin/main: a
# squash merge leaves every commit of the feature outside main, and all of them
# would count.
retro_changed_code() {
  local wt="$1" branch="$2" head n to
  [[ -n "$branch" ]] || return 0
  to="$(state_get "$wt/.sclaude/local/feature/state.json" retro.project_to 2>/dev/null || true)"
  [[ -n "$to" && "$to" != "null" ]] || return 0
  head="$(cd "$REPO" && merged_pr_head "$branch")"
  [[ -n "$head" ]] || return 0
  git -C "$wt" cat-file -e "$head^{commit}" 2>/dev/null \
    || git -C "$wt" fetch -q origin "$head" 2>/dev/null || return 0
  n="$(git -C "$wt" rev-list --count "$head..HEAD" 2>/dev/null || true)"
  [[ "$n" =~ ^[1-9][0-9]*$ ]] && echo "$n"
  return 0
}

# Puts the feature back on step 3, so the commits go out the way the feature's
# own did: step 3 opens their pull request, step 4 takes the automatic review's
# findings, and the preview, QA and the merge follow as after any review.
#
#   retro_reopen <wt> <merged pr>
#
# The marks are the ones a production rollback writes (regression.sh). The
# branch's merged pull request still answers for it: `reopened` keeps run_step
# from closing step 3 on it at once, and `reopened_pr` keeps after_step from
# taking its number for the new one. The preview verdict goes too: it was given
# on code without these commits.
retro_reopen() {
  local wt="$1" old="$2" state="$1/.sclaude/local/feature/state.json"
  [[ -f "$state" ]] || return 1
  step_rewind_to "$wt" pr pr review
  state_set "$state" reopened pr 2>/dev/null || true
  state_set "$state" reopened_by retro 2>/dev/null || true
  [[ -n "$old" && "$old" != "null" ]] \
    && state_set "$state" reopened_pr "$old" 2>/dev/null || true
  state_set "$state" regression.preview.status null 2>/dev/null || true
  # Fresh conversations for both steps. A closed step keeps its session's id,
  # and run_step resumes whatever id it finds: once step 3 reopened
  # the conversation that had opened the first pull request three days before, with no word of
  # the new commits, and it sat waiting for input. The runs stay, and so do
  # their rows in the issue.
  state_set "$state" steps.pr.session null 2>/dev/null || true
  state_set "$state" steps.review.session null 2>/dev/null || true
  issue_hold_open "$(state_get "$state" issue 2>/dev/null || true)"
  issue_sync "$wt"
  return 0
}

# The paragraph step 3 is given when retro_reopen sent the feature back to it,
# or nothing.
#
#   retro_pr_block <wt>
retro_pr_block() {
  local state="$1/.sclaude/local/feature/state.json" old
  [[ "$(state_get "$state" reopened_by 2>/dev/null || true)" == "retro" ]] || return 0
  old="$(state_get "$state" reopened_pr 2>/dev/null || true)"
  [[ -n "$old" && "$old" != "null" ]] || return 0
  cat <<EOF
**This is a second pull request for the feature.** PR #$old carried it and is merged. Since then the retrospective over the feature committed more on this branch, and sclaude sent the feature back to this step for them. A merged pull request cannot be reopened, so open a new one from this branch.

- It carries only the commits #$old did not: \`git log $(git -C "$1" rev-parse --short "$(cd "$REPO" && merged_pr_head "$(state_get "$state" branch)")" 2>/dev/null || echo "<head of #$old>")..HEAD\`. When \`origin/main..HEAD\` shows more than those (#$old was squash-merged), rebase them onto \`origin/main\` first, so the pull request holds nothing that is already merged.
- Its description says what these commits change and why, and names #$old as the pull request the feature shipped in. The acceptance criteria are the feature's and were checked on #$old: list only those these commits touch, and if they touch none, say so in place of the list.
- The manuals and the regression test question are about these commits only.
EOF
}

# What the retrospective said, printed in this terminal once the person has left
# it: claude's screen goes with the process, and the report is the one record
# of the retrospective a reader of this terminal has. The report ends the first
# turn; when the conversation went on after it, its last message follows,
# since that is where what was decided is.
#
#   retro_report <wt> <session>
retro_report() {
  local transcript report last
  transcript="$(transcript_dir "$1")/$2.jsonl"
  report="$(python3 "$LIB/session_end.py" first "$transcript" 2>/dev/null || true)"
  last="$(python3 "$LIB/session_end.py" last "$transcript" 2>/dev/null || true)"
  [[ -n "$report" ]] || return 0
  echo ""
  say "${BOLD}The retrospective's report:${OFF}"
  echo ""
  printf '%s\n' "$report" | sed 's/^/  /'
  if [[ -n "$last" && "$last" != "$report" ]]; then
    echo ""
    say "${BOLD}And its last message, after the conversation:${OFF}"
    echo ""
    printf '%s\n' "$last" | sed 's/^/  /'
  fi
  echo ""
}
