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
# It runs in plan mode, as the friction reviews do: it reads and reports, and
# changes nothing — the product, sclaude's workshop (core-open is given to it
# without a question) — before the person has approved a plan for it. In auto
# mode that yes was the prompt's word alone.
#
# With nothing in 1 and nothing in 3 the session closes itself, with nothing to
# approve: plan mode forbids it the done marker, so it ends its report on
# RETRO_NOTHING_SAID instead, which the watcher reads as one (session_end.py
# watch-said), and its report is printed here. With anything to act on it
# stays open, and the person talks it through there: the worktree is still in
# place for whatever they decide to finish in it.
#
# A later clean-up goes back into the same conversation (retro-again.md),
# told what ran since its last turn, to look at its report again.
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

# How many of the branch's commits the second pass is listed; the rest it is
# told the number of, and reads with git.
RETRO_SINCE_COMMITS=40

# The line the session ends its report on when it has nothing to act on, which
# closes it; the prompts are given it as <nothing-said>.
RETRO_NOTHING_SAID="Nothing to act on: sclaude closes this session."

# What the second pass is told when nothing ran since the first.
RETRO_NOTHING_SINCE="Nothing but this clean-up: no step, review or sync ran, and no commit reached the branch. So this is me coming back to the conversation: carry on with it, and check your report against what is on disk now."

run_retro() {
  local wt="$1" slug="$2" pr="${3:-}" issue="${4:-}"
  RETRO_INSTRUMENTS_CHANGED=""
  local fstate="$wt/.sclaude/local/feature/state.json"
  [[ "${SCLAUDE_RETRO:-on}" != "off" ]] || return 0
  # A conversation needs somebody at the terminal; the epilogue run from a
  # timer or a phone has nobody to hold it open for.
  [[ -t 0 && -t 1 ]] || return 0
  [[ -f "$PROMPTS/retro.md" ]] || return 0
  # Every clean-up holds one, and a second is the first conversation resumed,
  # told what has happened since its last turn (retro_since) and asked to go
  # over what it said again. Once a second pass was skipped as already paid
  # for: a person who had left with Ctrl-C could not get back into it, and a
  # feature that went round the cycle again — a rollback, the retrospective's
  # own fixes — was never looked back on a second time. Resuming costs less
  # than starting over, and keeps what the first pass read and was told.
  # A run that never answered — dropped, or killed before its first reply —
  # left no conversation to resume.
  #
  # The conversation is the newest one that answered: a later run killed
  # before its first reply does not hide the one before it.
  local last="" since="" answers_before=0
  if [[ -f "$fstate" ]]; then
    local candidate count at answered_at="" fallback=""
    local -a unanswered=()
    while IFS=$'\t' read -r candidate fallback; do
      IFS=$'\t' read -r count at < <(retro_answers "$(transcript_dir "$wt")/$candidate.jsonl")
      if (( ${count:-0} > 0 )); then
        last="$candidate" answers_before="$count" answered_at="${at:-$fallback}"
        break
      fi
      unanswered+=("$candidate")
    done < <(python3 - "$fstate" <<'PY' 2>/dev/null
import json, sys
runs = ((json.load(open(sys.argv[1])).get("retro") or {}).get("runs")) or []
for r in reversed([r for r in runs if isinstance(r, dict) and r.get("session")]):
    print("%s\t%s" % (r["session"], r.get("finished") or ""))
PY
)
    # Runs after it that never answered go: closing marks the last run done,
    # and that has to be the one resumed.
    if [[ -n "$last" ]]; then
      for candidate in "${unanswered[@]}"; do
        session_runs "$fstate" retro drop "$candidate"
      done
    fi
    # Since the time of its last answer, read from the conversation itself (the
    # run's end when the records carry no time): the run's fields move on a
    # pass that never answered, and one cut off has only its start, which
    # would count its own commits as news. The commits from the head it last
    # left (retro.head), when it recorded one.
    if [[ -n "$last" ]]; then
      # Main as it is: its commits a sync merged in are left out by it, and a
      # stale copy would list them as the branch's own.
      GIT_TERMINAL_PROMPT=0 timeout 20 git -C "$wt" fetch -q origin main 2>/dev/null || true
      since="$(retro_since "$wt" "$answered_at" \
        "$(state_get "$fstate" retro.head 2>/dev/null || true)")"
      # Nothing has run since — a "no" to the clean-up brought `done` back —
      # so a pass would only repeat itself, and is paid for. Offered, not held:
      # the person who wants back into the conversation says so.
      if [[ -z "$since" && -n "$answered_at" ]]; then
        local again
        ask "${BOLD}Nothing has run on '$slug' since its retrospective. Go back into it? [y/n] ${OFF}" again yn
        is_yes "$again" || return 0
      fi
    fi
  fi

  local terminal session done_file prompt
  terminal="$(term_render "$wt" 2>/dev/null || true)"
  # The project's config as the main checkout holds it — `sclaude config`
  # writes there and leaves it uncommitted — copied where the session reads.
  local config="$wt/.sclaude/local/feature/main-config.json"
  cp "$REPO/.sclaude/config.json" "$config" 2>/dev/null || echo '{}' > "$config"
  session="${last:-$(new_session_id)}"
  done_file="${TMPDIR:-/tmp}/sclaude-retro-$slug.done"
  rm -f "$done_file"

  # The pull request's number, or nothing: a feature with no change of its own
  # (no_change.sh) has none, and render_prompt fills an empty <pr> with a dash.
  local pr_number="$pr" no_change=""
  [[ "$pr_number" == "null" ]] && pr_number=""
  [[ "$(state_get "$fstate" no_change 2>/dev/null || true)" == "true" ]] && no_change=1

  # The same values for both prompts: the rules on sclaude's checkout may have
  # changed since the first pass, and the second is given them as they are.
  local template=retro since_block=""
  if [[ -n "$last" ]]; then
    template=retro-again
    since_block="${since:-$RETRO_NOTHING_SINCE}"
  fi
  prompt="$(SCLAUDE_V_TERMINAL="${terminal:-}" \
    SCLAUDE_B_SINCE="$since_block" \
    SCLAUDE_V_PR_NUMBER="$pr_number" \
    SCLAUDE_V_NO_CHANGE="$no_change" \
    SCLAUDE_V_TERMINAL_RAW="$wt/.sclaude/local/feature/terminal" \
    SCLAUDE_V_TRANSCRIPTS="$(transcript_dir "$wt")" \
    SCLAUDE_V_WORKTREE="$wt" \
    SCLAUDE_V_BRANCH="$(state_get "$fstate" branch 2>/dev/null || true)" \
    SCLAUDE_V_INSTRUMENTS="$INSTRUMENTS" \
    SCLAUDE_V_CONFIG="$config" \
    SCLAUDE_V_NOTHING_SAID="$RETRO_NOTHING_SAID" \
    render_prompt "$template" "$slug" "$pr" "$issue" "$wt")" || return 0

  echo ""
  echo "${BOLD}${BLUE}── $slug · $(phase_title retro), before the clean-up ──${OFF}"
  info "   opus / medium / plan · $wt"
  [[ -n "$last" ]] \
    && info "   the same conversation again, told what happened since its last turn"
  if [[ -n "$terminal" ]]; then
    info "   the terminal, as it was: $terminal"
  else
    info "   no terminal recording for this feature — it reads the state and the transcripts"
  fi
  info "   It closes by itself if it finds nothing to act on. SCLAUDE_RETRO=off skips it."
  echo ""

  # The rules first: a session refused here leaves no watcher and no open run.
  local -a guard=()
  local guard_out
  guard_out="$(review_guard_settings "$wt")" \
    || { warn "  The retrospective was not started: sclaude could not read its rules (see above)."; return 1; }
  mapfile -t guard <<< "$guard_out"
  # Past every reason not to start: the topic hears of a start that happens.
  ask_feed say "$(phase_line "$([[ -n "$last" ]] && echo resumed || echo started)" retro)"

  [[ -f "$fstate" ]] && session_runs "$fstate" retro open "$session"
  local project_before project_after
  project_before="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"

  session_watch_start "" "$session" "$done_file" "$wt" retro "$RETRO_NOTHING_SAID"
  local before_instruments; before_instruments="$(instruments_state)"
  local -a which=(--session-id "$session")
  [[ -n "$last" ]] && which=(--resume "$session")
  ( cd "$wt" && claude_launch "${which[@]}" --model opus --effort medium \
      "${guard[@]}" \
      --permission-mode plan --add-dir "$INSTRUMENTS" --add-dir "$TERM_DIR" \
      --add-dir "$(cd "$wt" && term_dir)" \
      --add-dir "$HOME/.claude/projects" \
      -n "$(session_label retro)/$slug" "$prompt" )
  session_watch_stop
  # The live checkout moved on while it ran: what it published was brought in
  # (workshop_live_update), or another hand updated it.
  local instruments_moved=""
  [[ "$(instruments_state | cut -d' ' -f1)" != "${before_instruments%% *}" ]] && instruments_moved=1
  instruments_unchanged "$before_instruments" "retrospective" || true
  # A resumed conversation has the first pass's answers already: this pass
  # ran only if it added one. One that did not — refused at the door, left at
  # once — is neither reported nor counted, and its run keeps its last end.
  local answered="" answers_after
  answers_after="$(retro_answers "$(transcript_dir "$wt")/$session.jsonl" | cut -f1)"
  (( ${answers_after:-0} > answers_before )) && answered=1
  # The close always, for its line in the topic: the start was said.
  session_closed "$done_file" "$wt" "$session" "nothing to act on" "" retro \
    || { [[ -n "$answered" ]] && retro_report "$wt" "$session" "$last"; } || true

  if [[ -f "$fstate" ]]; then
    if [[ -n "$answered" ]]; then
      session_runs "$fstate" retro finish "$session"
      # For cmd_done, which then stops short of the clean-up: sclaude's code
      # changed under the running bash. Only for a run recorded as done,
      # which the next `sclaude done` does not hold again.
      RETRO_INSTRUMENTS_CHANGED="$instruments_moved"
    elif [[ -z "$last" ]]; then
      session_runs "$fstate" retro drop "$session"
    fi
  fi

  # Deferred entries go to main by themselves (deferred_to_main): three lines
  # of log once sent a merged feature round the whole cycle again.
  [[ -n "$project_before" ]] && { deferred_to_main "$wt" "$project_before" || true; }
  # Where this pass left the branch, past deferred_to_main's own commit: the
  # next pass's commits start there.
  [[ -n "$answered" && -f "$fstate" ]] \
    && state_set "$fstate" retro.head "$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)" 2>/dev/null

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

  # What it changed in the product is the product's, and the branch above
  # carries it; what it changed in sclaude is said above.
  return 0
}

# What has happened to a feature since <when>, the end of its retrospective's
# last turn, for the second pass (retro-again.md): every run of a step, a
# review, a sync or a friction review that started after it — the epilogue
# is left out, since every clean-up runs one; a rollback or a reopening shows
# as the steps that ran again — and the branch's own commits since, main's
# merged in left out. Nothing at all when nothing happened.
#
#   retro_since <wt> <when> [head]
#
# The commits from [head] when the repository still has it — exact, where a
# date misses what a merge with main brought in — and by their date otherwise.
retro_since() {
  local wt="$1" when="$2" head="${3:-}" state="$1/.sclaude/local/feature/state.json"
  [[ -n "$when" && -f "$state" ]] || return 0
  # A list that could not be read says so rather than coming out empty, which
  # would tell the person and the model that nothing ran.
  python3 - "$state" "$when" <<'PY' 2>/dev/null \
    || echo "- sclaude could not read what ran since from state.json: read it there yourself"
import json, sys
from datetime import datetime

state, when = json.load(open(sys.argv[1])), sys.argv[2]
since = datetime.fromisoformat(when)

lines = []

def walk(node, path):
    if not isinstance(node, dict):
        return
    if path in ("retro", "epilogue"):
        return
    for run in node.get("runs") or []:
        if not isinstance(run, dict):
            continue
        try:
            started = datetime.fromisoformat(run.get("started") or "")
            finished = datetime.fromisoformat(run["finished"]) if run.get("finished") else None
            how = "finished %s" % run["finished"] if finished else "not finished"
            if started > since:
                lines.append((started.timestamp(),
                              "- %s: a session started %s, %s" % (path, run["started"], how)))
            # A conversation entered again is one run with its first start:
            # one resumed since shows by its end.
            elif finished and finished > since:
                lines.append((finished.timestamp(), "- %s: a session started %s and resumed since, %s"
                              % (path, run["started"], how)))
        except (TypeError, ValueError):
            continue
    for key, value in node.items():
        if key != "runs" and isinstance(value, dict):
            walk(value, "%s.%s" % (path, key) if path else key)

walk(state, "")
for _, line in sorted(lines):
    print(line)
PY
  # --cherry-pick: step 3 rebases the retrospective's commits after a squash
  # merge, and the copies are not news.
  if [[ -n "$head" && "$head" != "null" ]] && git -C "$wt" cat-file -e "$head^{commit}" 2>/dev/null; then
    git -C "$wt" log --right-only --cherry-pick --no-merges \
      --format='- commit %h %s (%ci)' "$head...HEAD" --not origin/main 2>/dev/null
  else
    git -C "$wt" log --no-merges --since="@$(date -d "$when" +%s 2>/dev/null || echo 0)" \
      --format='- commit %h %s (%ci)' HEAD --not origin/main 2>/dev/null
  fi | awk -v cap="$RETRO_SINCE_COMMITS" 'NR <= cap { print } END { if (NR > cap) printf "- and %d more commits\n", NR - cap }'
}

# How many answers a conversation holds, and when it gave its last one (an
# ISO time, or nothing), in one read of a transcript that runs to megabytes:
# what a resumed pass is measured against. An answer is an `assistant`
# record, as session_started counts them.
#
#   retro_answers <transcript>   → <count><TAB><time>
retro_answers() {
  [[ -f "$1" ]] || { printf '0\t\n'; return 0; }
  python3 - "$1" <<'PY' 2>/dev/null || printf '0\t\n'
import json, sys
n, last = 0, ""
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        entry = json.loads(line)
    except ValueError:
        continue
    # An API error or a usage limit is written as an assistant record too.
    if isinstance(entry, dict) and entry.get("type") == "assistant" \
            and not entry.get("isApiErrorMessage"):
        n += 1
        last = (entry.get("timestamp") or last).replace("Z", "+00:00")
print("%d\t%s" % (n, last))
PY
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
#   retro_reopen <wt> <merged pr> <slug>
#
# The marks are the ones a production rollback writes (regression.sh). The
# branch's merged pull request still answers for it: `reopened` keeps run_step
# from closing step 3 on it at once, and `reopened_pr` keeps after_step from
# taking its number for the new one. The preview verdict goes too: it was given
# on code without these commits.
retro_reopen() {
  local wt="$1" old="$2" slug="$3" state="$1/.sclaude/local/feature/state.json"
  [[ -f "$state" ]] || return 1
  step_rewind_to "$wt" pr pr review
  state_set "$state" reopened pr 2>/dev/null || true
  state_set "$state" reopened_by retro 2>/dev/null || true
  [[ -n "$old" && "$old" != "null" ]] \
    && state_set "$state" reopened_pr "$old" 2>/dev/null || true
  state_set "$state" regression.preview.status null 2>/dev/null || true
  # The hand-off was the merged pull request's: the new one is not handed over
  # until its own QA, and sync_gate would take it "back" at once.
  state_set "$state" handoff null 2>/dev/null || true
  # Fresh conversations for both steps. A closed step keeps its session's id,
  # and run_step resumes whatever id it finds: once step 3 reopened
  # the conversation that had opened the first pull request three days before, with no word of
  # the new commits, and it sat waiting for input. The runs stay, and so do
  # their rows in the issue.
  state_set "$state" steps.pr.session null 2>/dev/null || true
  state_set "$state" steps.review.session null 2>/dev/null || true
  # QA said yes to the merged pull request, and the watch on that answer is
  # spent: the new one is put to QA again, and watch_start arms a fresh watch
  # then. Left armed, it read the board moving the issue back to In progress —
  # on its reopening, or on the new pull request linking it — as QA handing the
  # feature back, and the cycle would have gone round the review once more with
  # sclaude's own status comments for QA's notes.
  watch_stop "$slug"
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
# since that is where what was decided is. A pass that resumed an earlier
# conversation (non-empty third argument) has the first pass's report as its
# first turn, so only the last message is printed, which is this pass's.
#
#   retro_report <wt> <session> [resumed]
retro_report() {
  local transcript report last
  transcript="$(transcript_dir "$1")/$2.jsonl"
  last="$(python3 "$LIB/session_end.py" last "$transcript" 2>/dev/null || true)"
  if [[ -n "${3:-}" ]]; then
    [[ -n "$last" ]] || return 0
    echo ""
    say "${BOLD}The retrospective's report, this pass:${OFF}"
    echo ""
    printf '%s\n' "$last" | sed 's/^/  /'
    echo ""
    return 0
  fi
  report="$(python3 "$LIB/session_end.py" first "$transcript" 2>/dev/null || true)"
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
