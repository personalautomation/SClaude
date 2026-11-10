#!/usr/bin/env bash
#
# Step 4's rounds: what the review said since the session last looked,
# when a round begins and ends, and whether the same conversation takes the
# next one or a fresh session does.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The comments that appeared on a PR while step 4's session was closed.
#
# Returning to step 4 goes through `--resume`, and that opens the previous
# conversation silently and without a prompt: the session sees exactly what it
# saw when it left. The review meanwhile goes on — a reviewer adds a comment, a
# check turns red from somebody else's merge into main — and the human had to
# retell that by hand, to a session that would not think to re-read for itself.
#
# We count from the transcript's last entry, that is from the moment the step
# last did something. Not from `steps.review.started`: the session lives for
# hours and reads the PR all that time, so a comment that arrived mid-work has
# already been dealt with — while from the start it would look new.
#
# Silent on any trouble: no transcript, no gh, no network — an empty string, and
# the return goes as before, with a silent `--resume`. This is a summary, not a
# condition of the work.
review_news() {
  local wt="$1" step="$2"
  local state="$wt/.sclaude/local/feature/state.json" pr since

  [[ "$step" == "review" ]] || return 0
  pr="$(state_get "$state" pr || true)"
  [[ -n "$pr" && "$pr" != "null" ]] || return 0

  since="$(review_last_look "$wt")"
  [[ -n "$since" ]] || return 0

  python3 "$LIB/review/pr_context.py" "$wt" "$pr" "$(gh_repo)" "$since" 2>/dev/null || true
}

# What a fix session is handed, counted, for its line in the topic:
# "findings: 2 not fixed yet, 4 new · red: tests" (brief in pr_context.py),
# split at the session's last look for a resumed one. Nothing for another
# step, or when GitHub cannot say.
#
#   review_brief <wt> <step> [resumed]
review_brief() {
  local wt="$1" step="$2" pr
  [[ "$step" == "review" ]] || return 0
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" ]] || return 0
  python3 "$LIB/review/pr_context.py" --handed "$wt" "$pr" "$(gh_repo)" \
    ${3:+"$(review_last_look "$wt")"} 2>/dev/null || true
}

# When the review step's session last looked at the pull request: its
# transcript's last entry, the mark review_news counts new comments from.
# The entry's time is the file's mtime: the transcript is appended to on every
# message, so that is precisely "when the step last worked", with no reason to
# read the whole jsonl for it. Not the round's start (round_since): a session
# carries on past its last look. Empty with no session or transcript.
#
#   review_last_look <wt>
review_last_look() {
  local session transcript
  session="$(state_get "$1/.sclaude/local/feature/state.json" steps.review.session 2>/dev/null || true)"
  [[ -n "$session" && "$session" != "null" ]] || return 0
  transcript="$(session_transcript "$1" "$session")"
  [[ -f "$transcript" ]] && date -Iseconds -r "$transcript" 2>/dev/null
  return 0
}

# Where a fix session's round begins: now, and the head it starts from. From
# its launch rather than its last look: what the review on this machine
# confirmed between two rounds is the earlier round's, said at its end.
# Only once the last round ended (review_round_ends): a session a person left
# and came back to is the same round, and its tally counts all of it.
#
#   review_round_begins <wt>
review_round_begins() {
  local state="$1/.sclaude/local/feature/state.json"
  [[ "$(state_get "$state" steps.review.round_open 2>/dev/null || true)" == "true" ]] && return 0
  state_set "$state" steps.review.round_since "$(date -Iseconds)"
  state_set "$state" steps.review.round_head "$(git -C "$1" rev-parse HEAD 2>/dev/null || echo null)"
  state_set "$state" steps.review.round_open true
}

# A round is over: sclaude closed the session on its report, or the review
# closed the round. The next launch begins a new one.
review_round_ends() {
  state_set "$1/.sclaude/local/feature/state.json" steps.review.round_open null 2>/dev/null || true
}

# What a fix session leaves at its end, for its line in the topic: the
# commits it made in its round and how the findings stand (brief --done):
# "2 commits · findings: 1 declined, 5 for the review to check, 0 new".
# The round is from its launch (review_round_begins). Nothing for another
# step, or when there is no round to count.
#
#   review_tally <wt> <step>
review_tally() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" pr since head commits standing
  [[ "$2" == "review" ]] || return 0
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  since="$(state_get "$state" steps.review.round_since 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" && -n "$since" && "$since" != "null" ]] || return 0
  # From the head it started on, not by date: a rebase or a merge of main
  # dates every commit anew. A head no longer in the history (rebased away)
  # counts nothing rather than everything.
  head="$(state_get "$state" steps.review.round_head 2>/dev/null || true)"
  if [[ -n "$head" && "$head" != "null" ]] && git -C "$wt" merge-base --is-ancestor "$head" HEAD 2>/dev/null; then
    commits="$(git -C "$wt" rev-list --count --first-parent --no-merges "$head..HEAD" 2>/dev/null || echo 0)"
  else
    commits=0
  fi
  standing="$(python3 "$LIB/review/pr_context.py" --done "$wt" "$pr" "$(gh_repo)" "$since" 2>/dev/null || true)"
  printf '%s %s%s\n' "$commits" "$([[ "$commits" == 1 ]] && echo commit || echo commits)" \
    "${standing:+ · $standing}"
}

# May step 4 close without a session, if the review turns out clean?
#
# Not when the step has a session of its own already — an interrupted one is
# resumed, never skipped — and not when anything sent the review back.
review_skippable() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json" session
  session="$(state_get "$state" steps.review.session 2>/dev/null || true)"
  if [[ -n "$session" && "$session" != "null" ]] && live_session "$wt" "$session" >/dev/null; then
    return 1
  fi
  [[ "$(state_get "$state" reopened 2>/dev/null || true)" == "review" ]] && return 1
  [[ "$(watch_verdict "$slug")" == "returned" ]] && return 1
  [[ -z "$(watch_notes "$slug")" ]] || return 1
  return 0
}

# The automatic review stopped on Claude's usage limit: wait for the reset and
# run it again, rather than open a session to find that out.
#
#   review_quota_rerun <wt> <slug> <pr> <repo>
#
# Returns 0 when it started the rerun — the caller goes back to waiting for
# the review — and 1 when the review did not fail on its quota, or the rerun
# could not be started; then everything goes on as before.
#
# The review runs under the same subscription as the sessions here, so with
# two features at work it runs out with them. A session handed that red check
# had nothing to fix: RED_CHECK_ADVICE in pr_context.py told it to rerun after
# the reset, and the session stood waiting for hours, on the same quota. The
# wait is sclaude's now, and costs nothing. Ctrl-C leaves it; nothing has
# started. Everything it prints goes to stderr, as the gate's waits
# (review_close_gate) print theirs.
review_quota_rerun() {
  local wt="$1" slug="$2" pr="$3" repo="$4" got run reset due now left
  got="$(python3 "$LIB/review/pr_context.py" --quota "$wt" "$pr" "$repo" 2>/dev/null || true)"
  [[ -n "$got" ]] || return 1
  read -r run reset <<<"$got"
  [[ "$run" =~ ^[0-9]+$ ]] || return 1
  # Already running again — ours from a moment ago, still shown as the old
  # failure, or somebody else's: nothing to start, only to wait for.
  local status; status="$(gh run view "$run" --json status --jq .status 2>/dev/null || true)"
  if [[ -n "$status" && "$status" != "completed" ]]; then
    sleep "${MERGE_POLL:-30}"
    return 0
  fi
  # Two minutes past the reset, or half an hour when the log did not say.
  if [[ "$reset" =~ ^[0-9]+$ && "$reset" -gt 0 ]]; then
    due=$(( reset + 120 ))
  else
    due=$(( $(date +%s) + 1800 ))
  fi
  {
    echo ""
    warn "  The automatic review of PR #$pr stopped on Claude's usage limit — not on the code."
    info "  sclaude runs it again at $(date -d "@$due" +%H:%M), once the limit has reset; no session is needed for it."
    info "  Ctrl-C to leave — the feature resumes here with: $SELF $slug"
  } >&2
  notify_feature "$slug" --wt "$wt" --quiet \
    "The automatic review of PR #$pr ran out of Claude quota; sclaude reruns it at $(date -d "@$due" +%H:%M)." \
    >/dev/null 2>&1 || true
  while now="$(date +%s)"; (( now < due )); do
    left=$(( due - now ))
    [[ -t 2 ]] && printf '\r\033[2K\033[?7l  %sRunning by itself%s — the review reruns in %s\033[?7h' \
      "$DIM" "$OFF" "$(regression_duration "$left")" >&2
    sleep $(( left < 60 ? left : 60 ))
  done
  [[ -t 2 ]] && printf '\r\033[2K' >&2
  if ! gh run rerun "$run" --failed >/dev/null 2>&1; then
    warn "  Could not rerun it (gh run rerun $run --failed) — the review session will look at it." >&2
    return 1
  fi
  info "  The automatic review is running again (run $run)." >&2
  # GitHub takes a moment to mark the rerun as running; asked at once, the
  # pull request still shows the failure, and this would start it twice.
  sleep "${MERGE_POLL:-30}"
  return 0
}

# When the review step's current session began: its first run's start, or
# nothing. What --open-since splits the open threads by.
#
#   review_session_since <wt>
review_session_since() {
  local state="$1/.sclaude/local/feature/state.json" session
  session="$(state_get "$state" steps.review.session 2>/dev/null || true)"
  python3 - "$state" "$session" <<'PY' 2>/dev/null || true
import json, sys
with open(sys.argv[1]) as fh:
    runs = ((json.load(fh).get("steps") or {}).get("review") or {}).get("runs") or []
starts = [r.get("started") or "" for r in runs
          if isinstance(r, dict) and r.get("session") == sys.argv[2]]
print(min((s for s in starts if s), default=""))
PY
}

# Where a review that is not done goes, when its session was closed by the
# orchestrator rather than by a person: unasked with [g] ticked, on the
# person's yes without it (review_close_gate).
#
#   review_reopen <wt> <slug> <pr> <repo> <waited>
#
# By whose work is left, the way review.md tells a session to decide for
# itself:
#
#   * the automatic review has not finished — there is nothing to fix yet, and
#     no session is opened for it;
#   * threads open since before the session began, or a red check — that
#     session's own work, and it knows why it changed what it did: it is
#     resumed, and told what is still open;
#   * only threads opened after it began — a new round, which goes where a
#     round marker would send it: to the same session while review_keep says
#     its context is light and cached, to a fresh one otherwise.
review_reopen() {
  local wt="$1" slug="$2" pr="$3" repo="$4" waited="$5"
  local state="$wt/.sclaude/local/feature/state.json" since split older newer session held pct why
  if [[ "$waited" -ge "$REVIEW_WAIT_MAX" ]]; then
    info "  Nothing to fix until it has finished. Come back with: $SELF $slug"
    return 0
  fi
  since="$(review_session_since "$wt")"
  split="$(python3 "$LIB/review/pr_context.py" --open-since "$wt" "$pr" "$repo" "$since" 2>/dev/null || true)"
  read -r older newer <<<"$split"
  # Which session it is, the session's heading says ("resuming" or not).
  if [[ "${older:-}" == "0" && "${newer:-0}" -gt 0 ]]; then
    session="$(state_get "$state" steps.review.session 2>/dev/null || true)"
    [[ "$session" == "null" ]] && session=""
    if [[ -n "$session" ]]; then
      held="$(review_context "$wt" "$session")"
      pct="$(awk '{print $3}' <<<"$held")"
      if why="$(review_keep "$wt" "$session" "$held")"; then
        # The round it closed is counted by run_step, and only once it has
        # resumed this session (`kept`).
        info "  Its context is at ${pct}% (under ${REVIEW_CONTEXT_MAX_PCT}%) and $why: the same session takes the findings still open."
        REVIEW_KEPT_SAID=1  # run_step leaves out its own "resuming" line
        run_step "$wt" "$slug" review "$(review_carry_on "$pct")" kept
        return 0
      fi
      info "  The new findings go to a fresh session, without this one's context: $why."
    fi
    review_stuck_say "$wt"
    state_set "$state" steps.review.session null
  fi
  run_step "$wt" "$slug" review
}

# Says, once a pull request and loudly, that the review's report finds the rounds
# no longer converging, or fed by their own fixes (steps.review.stuck, written
# by review_report), and how
# to end the search: each round's new findings went to a fresh session for as
# long as the person did not press `s` — eighteen rounds on one feature, most
# of their findings in what users do not see. Said, not asked: whether the
# rounds wait for somebody is [g]'s to say, and without it the question after
# this is asked anyway (review_close_gate). The keys that end the search are
# there too: `s` while a review pass runs, ⏭ on the topic's message of the
# pass and of the session (review_enough).
#
#   review_stuck_say <wt>
review_stuck_say() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" said pr
  said="$(state_get "$state" steps.review.stuck 2>/dev/null || true)"
  [[ -n "$said" && "$said" != "null" ]] || return 0
  [[ -z "$(review_enough "$wt")" ]] || return 0
  # Once per pull request, by its number: a feature reopened after its merge
  # goes on under a new one, whose rounds were said about nothing yet, and a
  # verdict on the merged one's is no verdict on them (review_report).
  # A state from before the keying: a verdict with no number is the current
  # pull request's, and `true` said for it.
  local verdict_pr said_for
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  verdict_pr="$(state_get "$state" steps.review.stuck_pr 2>/dev/null || true)"
  [[ -n "$verdict_pr" && "$verdict_pr" != "null" ]] || verdict_pr="$pr"
  said_for="$(state_get "$state" steps.review.stuck_said 2>/dev/null || true)"
  [[ "$said_for" == "true" ]] && said_for="$pr"
  [[ "$verdict_pr" == "$pr" && "$said_for" != "$pr" ]] || return 0
  state_set "$state" steps.review.stuck_said "$pr" 2>/dev/null || true
  # To the feature's topic alone, where ⏭ is: the terminal has just printed
  # the verdict in red under the report, and [s] stands on every status line
  # of the review, so the same words there were read twice.
  ask_feed warn "  The review's report: $said"
  ask_feed warn "  To make this the last session for new findings: [s] while a review pass runs, or ⏭ on the feature's topic. The open findings still go to a session."
  # A question after it ([g]'s ceiling) shows it on the phone as its context.
  ask_note "  The review's report: $said"
  return 0
}

# The review step, one round per session.
#
# A review round: the session fixes the open findings — through subagents, so
# its own context holds the coordination rather than every file it read — and
# pushes; the automatic review reads the fixes and closes what they fixed. When
# it has closed every one of them and posted new findings, the session that
# fixed the old ones has nothing left to answer, and all it carries into the
# new findings is context. Once five rounds ran in one conversation.
#
# A session cannot clear its own context — /clear and /compact are the
# person's, and no tool reaches them — so the orchestrator does it. The
# session writes round_marker and stops; the watcher below ends the claude
# process, and session_ended decides who takes the new findings.
#
# Not always a fresh session. A fresh one starts from nothing on a pull
# request this one has been settling, and may undo what it settled; it pays
# the door again, too — the plan, the snapshot, the rules. So while the
# conversation holds less than REVIEW_CONTEXT_MAX_PCT of its window, the same
# session is resumed with the new findings (review_carry_on). Past it, the
# session is recorded as ended with "fixes confirmed" and a fresh one opens,
# whose prompt carries the pull request as it stands — the new findings, and
# only them, open. A round is closed only once every fix the session made is
# confirmed, so the threshold never takes a session away from its own
# unfinished work.
round_marker() {
  echo "$1/.sclaude/local/feature/review-round"
}

# How full a review session's context is.
#
#   review_context <wt> <session>   → "<tokens now> <tokens at start> <pct> <window>"
#
# The tokens are read from the transcript (session_end.py context); the share
# and the window from what the status line last left for the session
# (CONTEXT_FILE in statusline.py), since only Claude Code knows the window. A
# share it did not leave is "-": the round then rotates as it always did.
review_context() {
  local wt="$1" session="$2" tokens pct="" size="" file
  # The status line names its file by the id Claude Code has now.
  file="/tmp/claude-statusline-context-$(session_latest "$wt" "$session")"
  tokens="$(python3 "$LIB/cycle/session_end.py" context "$(session_transcript "$wt" "$session")" 2>/dev/null || true)"
  [[ -n "$tokens" ]] || tokens="- -"
  if [[ -s "$file" ]]; then
    read -r pct size < <(python3 - "$file" <<'PY' 2>/dev/null || true
import json, sys
with open(sys.argv[1]) as fh:
    d = json.load(fh)
size = d.get("context_window_size")
print("%d %s" % (round(d["used_percentage"]), size if isinstance(size, int) else "-"))
PY
)
  fi
  echo "$tokens ${pct:--} ${size:--}"
}

# Whether the next review round stays in the session that closed this one.
#
#   review_keep <wt> <session> <held>   → exit 0 to keep it; prints why
#
# <held> is review_context's line. Kept only while both hold:
#
#   * its context is under REVIEW_CONTEXT_MAX_PCT — a heavy one goes on
#     dragging every file the earlier rounds read;
#   * its prompt cache is likely alive: the last request it made is younger
#     than REVIEW_CACHE_TTL less REVIEW_CACHE_MARGIN. Resumed after that, the
#     whole context is sent again uncached, and a fresh session costs less.
#
# A share or a time that cannot be read sends the round to a fresh session,
# as it always went.
review_keep() {
  local wt="$1" session="$2" held="$3" pct at idle limit
  pct="$(awk '{print $3}' <<<"$held")"
  if ! [[ "$pct" =~ ^[0-9]+$ ]]; then
    echo "its share of the context window is unknown"
    return 1
  fi
  if [[ "$pct" -ge "$REVIEW_CONTEXT_MAX_PCT" ]]; then
    echo "its context is at ${pct}% (${REVIEW_CONTEXT_MAX_PCT}% or more)"
    return 1
  fi
  at="$(python3 "$LIB/cycle/session_end.py" requested "$(session_transcript "$wt" "$session")" 2>/dev/null || true)"
  if ! [[ "$at" =~ ^[0-9]+$ ]]; then
    echo "the time of its last request could not be read"
    return 1
  fi
  idle=$(( $(date +%s) - at ))
  (( idle < 0 )) && idle=0
  limit=$(( REVIEW_CACHE_TTL - REVIEW_CACHE_MARGIN ))
  if [[ "$idle" -ge "$limit" ]]; then
    echo "its last request was $((idle / 60)) min ago, and its prompt cache has likely expired (kept for $((limit / 60)) min)"
    return 1
  fi
  echo "its prompt cache is likely alive (last request $((idle / 60)) min ago)"
  return 0
}

# What `sclaude checks` adds on a red, for the session waiting on it: whether
# review_keep would keep this conversation for the findings on code it did
# not touch. Kept, it takes them at once, in the push it is making anyway
# (sclaude/prompts/review.md, step 4): stopping for them cost a whole review
# round when they came with findings on its own fixes, and a restart when
# they came alone — only for sclaude to hand them back to it. Not kept, it
# stops as before and a fresh session takes them. No line when the session
# cannot be read: the prompt's rule without one is to stop.
#
# The two lines' openings are spelled out in review.md; tests/review-round.py
# checks the two agree.
CHECKS_KEEP_YES="New findings on code you did not touch are yours as well"
CHECKS_KEEP_NO="New findings on code you did not touch go to a fresh session"
#
#   review_checks_keep <wt>
review_checks_keep() {
  local wt="$1" session held why
  session="$(state_get "$wt/.sclaude/local/feature/state.json" steps.review.session 2>/dev/null || true)"
  [[ -n "$session" && "$session" != "null" ]] || return 0
  held="$(review_context "$wt" "$session")"
  if why="$(review_keep "$wt" "$session" "$held")"; then
    echo "$CHECKS_KEEP_YES: this conversation would be kept for them ($why, context $(awk '{print $3}' <<<"$held")%)."
  else
    echo "$CHECKS_KEEP_NO: $why."
  fi
}

# One line per review session's end, in the main tree's .sclaude/local/,
# where it outlives the feature's worktree; tab-separated:
#
#   <time> <feature> <session> <outcome> <tokens now> <tokens at start> <pct> <window> <rounds> <comments> <reversals>
#
# The outcome is "carried on" (the same session takes the next round), "fresh
# session" (the threshold sent the next round elsewhere), "done" (sclaude
# closed it on its done marker) or "exit" (a person did). rounds is how many
# rounds the session closed, comments the threads the review handed it
# (run_comments), reversals the findings the session declined since the last
# row because they would undo a settled fix (reversals_file). It is what
# REVIEW_CONTEXT_MAX_PCT is to be judged by — `sclaude review-stats` reads it:
# what a round costs, what a session costs before it starts, how tokens and
# the share relate, and whether the sessions that carried on did worse.
review_context_log() {
  local wt="$1" slug="$2" session="$3" outcome="$4" held="$5" rounds="$6" root comments reversals
  root="$(scratch_root "$wt")" || return 0
  # Counted and emptied: each row holds the stretch since the one before it.
  reversals="$(grep -c . "$(reversals_file "$wt")" 2>/dev/null || true)"
  [[ "$reversals" =~ ^[0-9]+$ ]] || reversals=0
  : > "$(reversals_file "$wt")" 2>/dev/null || true
  comments="$(python3 - "$wt/.sclaude/local/feature/state.json" "$session" <<'PY' 2>/dev/null || true
import json, sys
with open(sys.argv[1]) as fh:
    runs = ((json.load(fh).get("steps") or {}).get("review") or {}).get("runs") or []
mine = [r for r in runs if isinstance(r, dict) and r.get("session") == sys.argv[2]]
print(mine[-1].get("comments", "-") if mine else "-")
PY
)"
  mkdir -p "$root/.sclaude/local" 2>/dev/null || return 0
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$slug" "$session" "$outcome" \
    "$(tr ' ' '\t' <<<"${held:-- - - -}")" "${rounds:--}" "${comments:--}" "$reversals" \
    >> "$root/.sclaude/local/review-context.log" 2>/dev/null || true
}

# Where a review session notes a finding it declined because applying it would
# undo a fix the pull request had already settled — one line each, the
# thread's link and what it would undo. review.md asks for it; the count goes
# into review_context_log, the measure of whether a long session still holds
# on to what it settled.
reversals_file() {
  echo "$1/.sclaude/local/feature/review-reversals"
}

# What the same review session is told when it takes the next round.
#
#   review_carry_on <pct>
review_carry_on() {
  printf '%s' "**The review round is closed, and this conversation takes the next one.** The review confirmed every fix you made. Your context is at $1% — under the ${REVIEW_CONTEXT_MAX_PCT}% at which sclaude opens a fresh session — and still cached, so the findings still open are yours now: what this conversation settled stays in view while you fix them. Re-read the pull request (\`gh pr checks <pr>\`, \`gh pr view <pr> --comments\`, \`gh api repos/{owner}/{repo}/pulls/<pr>/comments\`); its open threads are your list. Work them as step 1 of the prompt says, through subagents. From here they are threads you are fixing, and the round ends by the same rules as before."
}
