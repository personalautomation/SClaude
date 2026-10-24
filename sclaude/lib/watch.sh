#!/usr/bin/env bash
#
# Waiting for QA without a session open.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Once the preview regression is green and the issue has moved to "In QA", there
# is nothing left for a session to do: the next thing that happens is a person
# looking at the deployment, and that takes hours or days. Holding a session
# open for it costs tokens for nothing, and closing it used to mean nobody
# noticed when QA answered.
#
# So the waiting moves out of the session entirely. A file per feature records
# what to watch, a systemd timer reads those files every few minutes, and
# Telegram says when something changed. The timer looks and it tells; acting is
# sclaude's job when the human comes back — except the hand-off of the pull
# request once QA has accepted the work, which the timer starts itself through
# `sclaude _handoff` (see bin/sclaude-watch).
#
# The directory lies beside the epilogue's, outside every repository, and for
# the same reason: this is one machine's state, the feature's tree may be gone
# by then, and a service file inside somebody's product repository would ride
# into their next commit.

watch_dir() {
  echo "$HOME/.claude/sclaude/watch"
}

# The watch file for a feature, created empty if missing or unreadable.
#
# Self-healing for the reason epilogue_state is: writing is not atomic — python
# truncates and rewrites — so an interruption at that instant leaves a file that
# is empty or half-written. Left alone it stays dead, and a dead watch file is
# indistinguishable from a feature nobody is waiting on.
watch_state() {
  local slug="$1" dir; dir="$(watch_dir)"
  mkdir -p "$dir" 2>/dev/null || return 1
  local file="$dir/$slug.json"
  if [[ ! -s "$file" ]] || ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' \
       "$file" 2>/dev/null; then
    echo '{}' > "$file" || return 1
  fi
  echo "$file"
}

# Begin watching a feature. Called once the preview regression is green and the
# issue has been moved into QA.
#
# The mark is the moment from which a comment counts as new — the same device
# review_news uses for a PR, and for the same reason: everything said before it
# was said while somebody was still working, and has been seen.
watch_start() {
  local wt="$1" slug="$2" issue="$3" pr="$4" file repo now

  [[ -n "$issue" && "$issue" != "null" ]] || return 0

  # Where the issue actually is, before claiming anything about it.
  #
  # An issue can reach Done without passing through here at all: a merge
  # carrying `Closes #N` closes it, and a board with the "Item closed" workflow
  # enabled moves the item in the same second. Arming a watch then leaves a
  # timer waiting for a transition that has already happened — and on its first
  # sweep the watcher compares Done against the "In QA" we would have written,
  # sees a difference, and announces that QA passed something nobody looked at.
  #
  # Empty means nothing is known — no gh, no network, no board — and that is
  # not a reason to skip the watch: the timer is harmless when it has nothing
  # to compare, and a feature nobody is watching is the worse of the two.
  now="$(issue_status_now "$issue" 2>/dev/null || true)"
  if column_is "$now" "$QA_DONE"; then
    echo ""
    info "Issue #$issue is already '$QA_DONE' — no QA watch armed."
    info "  It was closed and moved there without passing through '$QA_TO',"
    info "  which a merge carrying 'Closes #$issue' does on its own."
    return 0
  fi

  file="$(watch_state "$slug")" || return 0
  repo="$(gh_repo 2>/dev/null || true)"

  state_set "$file" feature "$slug"
  state_set "$file" issue "$issue"
  [[ -n "$pr" && "$pr" != "null" ]] && state_set "$file" pr "$pr"
  [[ -n "$repo" ]] && state_set "$file" repo "$repo"
  # Where the project lives, so the timer can run `sclaude _handoff` in it
  # once QA has accepted the work (bin/sclaude-watch, handoff).
  [[ -n "${REPO:-}" ]] && state_set "$file" root "$REPO"
  # And the feature's worktree, whose topic the timer's messages go to
  # (sclaude-notify --in) rather than to the main chat.
  [[ -n "$wt" ]] && state_set "$file" worktree "$wt"
  # A watch re-armed after a return waits for a new acceptance, and the
  # hand-off of the head before it says nothing about this one. Cleared here as
  # well as on the timer's own sight of a move: `sclaude return` records the
  # new column itself, so the timer never sees the move happen.
  state_set "$file" handoff null
  # The board's names, for bin/sclaude-watch: it runs from a timer with none of
  # these modules and no project config in reach, so the columns it compares
  # against travel with the file. Absent ones stay absent — the watcher then
  # reports any move as a move, without calling it a pass or a return.
  [[ -n "$QA_FROM" ]] && state_set "$file" columns.back "$QA_FROM"
  # Backlog is a hand-back too: QA sending a feature to the start of the queue
  # is saying "not this", exactly as In progress is.
  [[ -n "$PROGRESS_FROM" ]] && state_set "$file" columns.backlog "$PROGRESS_FROM"
  [[ -n "$QA_DONE" ]] && state_set "$file" columns.done "$QA_DONE"
  # And In QA itself, so an issue moved back into it is recognised as the wait
  # going on rather than reported as one more unexpected column.
  [[ -n "$QA_TO" ]] && state_set "$file" columns.qa "$QA_TO"
  # The column observed, not the one assumed. They differ whenever the QA move
  # did not go through — a human had moved the issue elsewhere first — and the
  # watcher's whole method is to compare what it sees now against what was
  # recorded here. Recording a column the issue is not in makes its very first
  # comparison a false alarm.
  state_set "$file" status "${now:-$QA_TO}"
  # UTC, not local time. GitHub timestamps every comment in UTC, and the
  # watcher compares the two as strings — so a mark written as +01:00 would sit
  # an hour ahead of the instant it means, and every comment left in that first
  # hour would be read as older than the mark and dropped. That is precisely the
  # comment this exists to catch: the one QA leaves straight after looking.
  state_set "$file" since "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

  echo ""
  info "QA watch armed on issue #$issue: the timer keeps looking even with this"
  info "  terminal closed, and Telegram will say when the column moves."
  return 0
}

# Record a column sclaude saw itself, so the timer does not announce it again.
#
# qa_wait watches the same issue as the timer, from inside the session. When it
# sees Done it acts on it there and then; left alone, the timer's next sweep
# would compare Done against the "In QA" recorded here and send a "QA passed"
# message about something the person already answered in the terminal.
watch_mark() {
  local slug="$1" status="$2"
  local file; file="$(watch_dir)/$slug.json"
  [[ -s "$file" ]] || return 0
  state_set "$file" status "$status" 2>/dev/null || true
  # A pass the timer got to first is answered here just the same. A return is
  # not cleared: its comments still have to reach a session, and run_step
  # acknowledges them once they have.
  case "$(state_get "$file" verdict 2>/dev/null || true)" in
    done|other) state_set "$file" verdict null 2>/dev/null || true ;;
  esac
  return 0
}

# Look once, the way the timer does, for this feature alone.
#
# qa_wait saw the issue leave In QA backwards. The comments QA left are what
# the review session has to answer, and bin/sclaude-watch is the one place that
# collects them — verbatim, into the file run_step hands to the session. So it
# is asked to look now rather than in up to five minutes. Quiet: the person is
# at the terminal, and a Telegram message about what they are looking at is
# noise.
watch_look_now() {
  local slug="$1"
  [[ -x "$INSTRUMENTS/bin/sclaude-watch" ]] || return 0
  SCLAUDE_WATCH_QUIET=1 "$INSTRUMENTS/bin/sclaude-watch" "$slug" >/dev/null 2>&1 || true
  return 0
}

# The feature was returned to development: say so, and put the cycle on the
# review step.
#
#   qa_take_back <wt> <slug>
#
# The half of a hand-back that both entrances share: cmd_resume, when the
# timer saw it while nobody was here, and remind_prod, when qa_wait saw it
# live. The caller then runs the review step, whose run_step hands QA's
# comments to the session and acknowledges them once it has.
#
# Returns non-zero when the rewind did not take — no state to write to — so the
# caller does not open a session on a step the state does not name.
qa_take_back() {
  local wt="$1" slug="$2" step
  watch_rewind "$wt" "$slug"
  step="$(state_get "$wt/.sclaude/local/feature/state.json" step)" || true
  # Read back rather than assumed: watch_rewind answers nothing when there is
  # no state to write to, and `step_title done` is empty — the line would then
  # read "returns to step ''". Saying it only when the rewind took is the
  # honest shape.
  if [[ "$step" == "review" ]]; then
    info "  The cycle returns to step '$(step_title "$step")'; the preview is checked again."
    return 0
  fi
  warn "  The cycle could not be put back on the review step — see the state."
  return 1
}

# What the watcher found has been acted on: forget the verdict and put the
# comments aside.
#
# The notes are moved rather than deleted, the way run_friction moves its log
# into .reviewed: they were written by a person, they are the only copy outside
# GitHub, and a feature that comes back round deserves to be able to look at
# what was said last time. The verdict, by contrast, is a flag and is simply
# cleared — it means "something changed since you last looked", and once it has
# been looked at it means nothing.
#
# Silent when there is nothing to forget: this runs after every session, and
# most of them never heard from QA at all.
watch_seen() {
  local slug="$1"
  local dir; dir="$(watch_dir)"
  local file="$dir/$slug.json"
  local notes="$dir/$slug.qa.md"

  [[ -s "$file" ]] || return 0
  [[ "$(state_get "$file" verdict 2>/dev/null || true)" == "" ]] \
    && [[ ! -s "$notes" ]] && return 0

  state_set "$file" verdict null
  [[ -s "$notes" ]] && cat "$notes" >> "$dir/$slug.qa.md.seen" 2>/dev/null
  rm -f "$notes" 2>/dev/null || true
  return 0
}

# Stop watching: the feature moved on, or was abandoned.
watch_stop() {
  local slug="$1" dir; dir="$(watch_dir)"
  rm -f "$dir/$slug.json" "$dir/$slug.qa.md" "$dir/$slug.qa.md.seen" 2>/dev/null || true
  return 0
}

# What the watcher noticed, for sclaude to act on when the human comes back.
# Empty when nothing has changed, or when the feature is not being watched.
watch_verdict() {
  local slug="$1"
  local file; file="$(watch_dir)/$slug.json"
  [[ -s "$file" ]] || return 0
  state_get "$file" verdict 2>/dev/null || true
}

# The QA comments the watcher saved, if any.
watch_notes() {
  # Two declarations rather than one: in `local a="$1" b="$a/x"` bash expands
  # both right-hand sides before binding a single name, so $slug there is not
  # the parameter yet. The same trap is described at friction_count.
  local slug="$1"
  local file; file="$(watch_dir)/$slug.qa.md"
  [[ -s "$file" ]] || return 0
  cat "$file"
}

# The feature was returned to development: put the cycle on the review step.
#
#   watch_rewind <wt> <slug>
#
# The watcher saw the column move out of "In QA" and saved what was said; this
# is the other half — the cycle actually going back. Without it the finding was
# delivered and ignored: `watch_start` is called from remind_prod, so a feature
# waiting on QA always sits at `step: done`, and a done feature goes to
# remind_prod rather than to a session. The comments reached no session because
# no session was opened.
#
# No question asked. QA moving an issue out of that column is a judgement
# already made, and "back to the review?" would be asking whether they meant it
# — the same reason a rolled-back production is not put to a vote.
#
# The preview's verdict goes with it, and only the preview's. run_step clears
# the local stage on entering review and deliberately spares the deployed ones,
# because "a preview verdict that is still true" is worth keeping — but after a
# hand-back the preview is precisely what QA looked at and rejected. Left
# `passed`, regression_gate short-circuits on it and the fix goes back to QA
# without the deployment ever being checked again. `prod` is not cleared: if
# production shipped, that verdict is about a deployment the comment did not
# concern.
watch_rewind() {
  local wt="$1" slug="$2"
  local state="$wt/.sclaude/local/feature/state.json"
  [[ -f "$state" ]] || return 0

  step_rewind_to "$wt" review review
  # The mark run_step reads before letting a merged PR close the step. QA now
  # looks before the merge, but a branch merged by hand meanwhile, or a feature
  # from the old order (merge, then QA), would otherwise conclude there is
  # nothing left to do, mark the steps passed again and return to the
  # production reminder. The rewind would be undone in the same breath it was
  # made.
  state_set "$state" reopened review 2>/dev/null || true
  # One name for every way back: QA moving the card, `sclaude return`, a
  # review finding found late. Why it came back is in the notes, and the
  # session reads the issue and the pull request for itself; what it does next
  # does not depend on who sent it.
  state_set "$state" reopened_by returned 2>/dev/null || true
  # From when the session looks for what was said. The watch's mark when there
  # is one — set when the feature went to QA — and otherwise the moment the
  # review step closed: everything before it was said while the feature was
  # being worked on, and has been answered.
  local since; since="$(return_since "$wt" "$slug")"
  state_set "$state" reopened_since "${since:-null}" 2>/dev/null || true
  # Which pull request was the one QA looked at. When that one is already
  # merged, the fix has to arrive as a new pull request (a merged one cannot be
  # reopened), and after_step refuses to close the review until the branch
  # carries a number that is not this one.
  local pr; pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" ]] \
    && state_set "$state" reopened_pr "$pr" 2>/dev/null || true
  state_set "$state" regression.preview.status null 2>/dev/null || true
  state_set "$state" regression.preview.attempts 0 2>/dev/null || true
  # Counted for the merge summary (pr_handoff.py): how often the work came
  # back is what tells a merger whether "QA accepted it" was the first look or
  # the fourth.
  local returns; returns="$(state_get "$state" qa_returns 2>/dev/null || echo 0)"
  [[ "$returns" =~ ^[0-9]+$ ]] || returns=0
  state_set "$state" qa_returns "$((returns + 1))" 2>/dev/null || true
  issue_sync "$wt"
  return 0
}

# The moment from which what was said counts as new, for a return.
#
#   return_since <wt> <slug>   → an ISO-8601 time in UTC, or nothing
#
# The QA watch's own mark first: it is when the feature was handed to QA, and
# the watcher compares comments against it. Without a watch — returned before
# QA was ever asked, or after the watch was cleared — the time the review step
# closed. Nothing when neither is known; the session then reads everything.
return_since() {
  local wt="$1" slug="$2" since
  since="$(state_get "$(watch_dir)/$slug.json" since 2>/dev/null || true)"
  if [[ -z "$since" || "$since" == "null" ]]; then
    since="$(state_get "$wt/.sclaude/local/feature/state.json" steps.review.finished 2>/dev/null || true)"
    # The state writes local time with an offset; GitHub and the watcher
    # compare in UTC, as strings.
    [[ -n "$since" && "$since" != "null" ]] \
      && since="$(date -u -d "$since" +%Y-%m-%dT%H:%M:%S+00:00 2>/dev/null || true)"
  fi
  [[ "$since" == "null" ]] && since=""
  echo "$since"
}

# Send a finished feature back to development by hand: `sclaude return`.
#
#   return_to_development <wt> <slug> [reason...]
#
# The same return the board makes when QA moves the card out of "In QA", for
# every other reason a feature has to go back — a review finding that surfaced
# after the step was skipped as clean, a problem noticed in
# the preview, a second thought. It does here what the watcher and cmd_resume
# do between them for the board:
#
#   * saves what was said since the mark, on the issue and on the pull request,
#     where run_step hands it to the session — with the reason first, when one
#     was given, since it may be said nowhere else;
#   * moves the card from "In QA" back to "In progress", so the board does not
#     claim QA has a feature that is being fixed, and records that column in
#     the watch so the timer does not announce the move as QA's;
#   * leaves the verdict `returned`, which cmd_resume then acts on exactly as it
#     does for the board: the rewind, and the review step with the notes.
#
# Returns non-zero when there is nothing to return: no state.
return_to_development() {
  local wt="$1" slug="$2"; shift 2
  local reason="$*" state="$wt/.sclaude/local/feature/state.json" file issue pr repo since notes
  [[ -f "$state" ]] || return 1
  issue="$(state_get "$state" issue 2>/dev/null || true)"; [[ "$issue" == "null" ]] && issue=""
  pr="$(state_get "$state" pr 2>/dev/null || true)"; [[ "$pr" == "null" ]] && pr=""
  repo="$(gh_repo 2>/dev/null || true)"
  since="$(return_since "$wt" "$slug")"

  file="$(watch_state "$slug")" || return 1
  [[ -n "$since" ]] && state_set "$file" since "$since"

  notes=""
  if [[ -n "$repo" && -n "$issue" && -x "$INSTRUMENTS/bin/sclaude-watch" ]]; then
    notes="$("$INSTRUMENTS/bin/sclaude-watch" --notes "$repo" "$issue" "${pr:-null}" \
               "${since:-1970-01-01T00:00:00+00:00}" 2>/dev/null || true)"
  fi
  {
    [[ -n "$reason" ]] && printf '### The reason given\n\n%s\n\n' "$reason"
    [[ -n "$notes" ]] && printf '%s\n' "$notes"
  } > "$(watch_dir)/$slug.qa.md"
  [[ -s "$(watch_dir)/$slug.qa.md" ]] || rm -f "$(watch_dir)/$slug.qa.md"

  if [[ -n "$issue" ]]; then
    issue_move_status "$issue" "$QA_TO" "$QA_FROM"
    local now; now="$(issue_status_now "$issue" 2>/dev/null || true)"
    [[ -n "$now" ]] && state_set "$file" status "$now"
  fi
  state_set "$file" verdict returned
  return 0
}
