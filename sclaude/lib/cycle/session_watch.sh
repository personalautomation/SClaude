#!/usr/bin/env bash
#
# Watching a step's session: the markers it writes when its work is done,
# the watcher that closes claude on them, and the record of how it ended.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Where [N] in sclaude's tab stops the run: everything after the session ran
# as on its own end, and sclaude stops before the next step's session, or
# before the preview after step 4 (session_watch_stop marks it). Said once:
# the run unwinds after it, and nothing below opens a session.
#
# The mark is a file named by this sclaude's process ($$, the same in its
# subshells and kept by code_reload's exec), not a variable in the
# environment: the sessions launched before the stop is reached copy every
# exported variable, and a sclaude run inside one of them would stop too.
# With the process's start time beside the pid: a mark left by a run that
# never reached a stop (after the epilogue, a Ctrl-C) is not taken by a later
# sclaude given the same pid.
#
#   stop_asked <what would begin> <slug>
stop_file() { printf '%s/sclaude-stop-%s-%s' "${TMPDIR:-/tmp}" "$$" "$(awk '{print $22}' "/proc/$$/stat" 2>/dev/null)"; }

stop_asked() {
  [[ -e "$(stop_file)" ]] || return 1
  rm -f "$(stop_file)"
  echo ""
  say_here "${BOLD}Stopped before $1, as you asked ([N]).${OFF}"
  info "  Come back with: $SELF $2"
  return 0
}

# A session whose work is done, closed without anybody typing /exit.
#
# Every session sclaude opens ends on a word it can check or that the person
# has already given, so /exit after it is a formality:
#
#   * review — review_close_gate asks the pull request whether the review
#     finished with nothing open;
#   * a fixing session — regression_gate runs the suite again;
#   * pr — capture_pr finds the pull request, and its head is what was pushed;
#   * plan — the approval is the person's own decision, made in the session
#     (it is also the marker: step 1 cannot write files);
#   * code — the person accepts the work in the session's own dialog
#     (code_accepted); after a session left with /exit sclaude asks whether
#     it works, and a "no" goes back to the same session;
#   * friction and the epilogue — the person approved the plan in the session,
#     and nothing after them waits on a check.
#
# Where a check fails, the work goes back to a session — without a person to
# ask, since nobody typed /exit (see auto_return).
done_marker() {
  echo "$1/.sclaude/local/feature/session-done"
}

# Whether the person accepted step 2's work in the session's own dialog,
# during this launch of it: the question code.md ends on, answered "Accept"
# with nothing typed after it (session_end.py accepted). Counted from the
# launch — the run's `resumed`, or its `started` (session_runs) — so that an
# answer given in an earlier launch of a resumed conversation is not taken
# for this one's.
#
#   code_accepted <wt> <session>
code_accepted() {
  local wt="$1" session="$2" since
  since="$(python3 - "$wt/.sclaude/local/feature/state.json" "$session" <<'PY' 2>/dev/null
import datetime, json, sys
with open(sys.argv[1]) as fh:
    runs = ((json.load(fh).get("steps") or {}).get("code") or {}).get("runs") or []
mine = [r for r in runs if isinstance(r, dict) and r.get("session") == sys.argv[2]]
began = (mine[-1].get("resumed") or mine[-1].get("started")) if mine else ""
print(int(datetime.datetime.fromisoformat(began).timestamp()) if began else 0)
PY
)"
  [[ "$since" =~ ^[0-9]+$ ]] || since=0
  [[ "$(python3 "$LIB/cycle/session_end.py" accepted "$(session_transcript "$wt" "$session")" "$since" 2>/dev/null)" == yes ]]
}

# What a conversation opened again with a message is told of its marker.
#
# None stands by then: session_closed takes it off as the session closes, and
# session_watch_start as the next one opens, so that an old marker cannot
# close a session that has not done its work yet. The session does not know
# that. It remembers writing one, and a development session sent back with
# "it does not work yet" found nothing to change, said its marker "already
# stood", and stayed open until somebody typed /exit. A fixing session's
# regression.blocked was the same case (regression_fix).
#
# Whoever ended the session last: the sentence is true either way, and keeps
# the reasons the instructions give to leave a marker out. Telling only the
# ones sclaude closed meant knowing that across processes, and every way of
# keeping it — a variable, the run's outcome — lost it somewhere.
#
#   marker_gone <marker>...   — paths as the session's prompt names them
marker_gone() {
  local names="" m
  for m in "$@"; do names+="${names:+ or }\`$m\`"; done
  printf '**No marker closes this session now** (%s): sclaude takes it off whenever it closes or reopens this conversation, so one written before no longer stands. When this work is done, write it as your instructions say, also when it turned out to need no change; leave it out only where they tell you to.' "$names"
}

# The watcher beside a session that may end itself.
#
#   session_watch_start <wt> <session> [<marker> <cwd> <kind> <said>]
#
# The session writes a marker — round_marker or done_marker — and gives its
# report as its last message. The watcher waits for that turn to end, then
# SESSION_GRACE seconds more for the person to read it, and ends the claude
# process, found by its session id in its arguments (`--session-id` or
# `--resume`) and nowhere else.
#
# A person who types anything in the meantime — an answer, a question, a
# command other than /exit — is still working with the session. The marker is
# then removed rather than acted on: closing the conversation under them would
# take it away mid-sentence. The session writes it again when it is done
# again. The transcript tells both apart (session_end.py watch).
#
# The epilogue and the friction review name their own marker and the
# directory their transcript is kept under — the epilogue the feature's tree
# (the main repository once the tree is gone), the friction review
# instruments — and <wt> is then empty.
#
# Step 1 writes no marker: its kind, "plan", makes the plan's approval the
# moment counted from instead (session_end.py approved). A person who types
# after the approval keeps the session: it then waits for /exit.
#
# The retrospective, in plan mode too, writes none either: <said> is the line
# it ends its report on when it has nothing to act on, and that message is the
# moment counted from (session_end.py watch-said). The watcher writes the
# marker itself, for session_closed.
#
# The person may also have the last word from sclaude's tab (session_keys in
# pane.sh): [n] makes the watcher write the done marker itself and close the
# session at once, as finished; with [k] it closes nothing until the key is
# pressed again, and a session kept so ends with the person's /exit, its
# marker standing. [r] makes it treat the reopened conversation as a resumed
# one: no marker, nothing before the reopening counted.
#
# SESSION_POLL and SESSION_GRACE are seconds, overridable for the tests.
session_watch_start() {
  local wt="$1" session="$2" done="${3:-}" cwd="${4:-$1}" kind="${5:-}" said="${6:-}"
  local round="" transcript ctl
  SESSION_WATCHER=""
  SESSION_WATCHED=""
  [[ -n "$session" ]] || return 0
  [[ -n "$wt" ]] && round="$(round_marker "$wt")"
  [[ -n "$done" ]] || done="$(done_marker "$wt")"
  rm -f ${round:+"$round"} "$done"
  # The person's word from sclaude's tab (session_keys in pane.sh): [n] closes
  # the session as if it had written its marker, [k] keeps it open. A word
  # left by an earlier launch is not this one's. The watched file tells the
  # keys that there is a watcher to act on them, and of which kind.
  ctl="$(session_ctl_file "$session")"
  local keep; keep="$(session_keep_file "$session")"
  rm -f "$ctl" "$keep"
  SESSION_WATCHED="$(session_watched_file "$session")"
  SESSION_WATCHED_ID="$session"
  SESSION_WATCHED_KIND="${kind:--}"
  rm -f "$SESSION_WATCHED"
  local watched_mark="$SESSION_WATCHED"
  transcript="$(transcript_dir "$cwd")/$session.jsonl"
  # Only an approval given while this watcher runs counts: a session reopened
  # after an earlier approval — sclaude interrupted before the step closed —
  # has a person back at it, who approved nothing this time.
  local started; started="$(date +%s)"
  # A session standing on a usage limit is closed once the limit has reset,
  # and claude_launch opens it again with a word to carry on: see `limit` in
  # session_end.py for the evening that cost. The person hears of it on
  # Telegram when it happens, with the time it will resume. This file is how
  # the watcher tells claude_launch that it closed the session for the limit
  # rather than for good.
  local limit_file="${TMPDIR:-/tmp}/sclaude-limit-$session"
  local label
  label="${wt:-$cwd}"
  label="${label##*/}${kind:+ ($kind)}"
  rm -f "$limit_file"
  (
    marker="" since="" ended="" size="" seen="" verdict="" grace="" word=""
    lseen="" hit="" told="" acted="" due=0
    # The process is found by any id the conversation has had: Claude Code
    # may carry it on under a new one while it runs, and the transcript with
    # it (session_transcript in state.sh); the process keeps the one it was
    # launched with, which claude_launch may have taken from further along.
    ids="$session"
    while sleep "${SESSION_POLL:-5}"; do
      word="$(cat "$ctl" 2>/dev/null || true)"
      if [[ "$word" == next || "$word" == next-later ]]; then
        # [n] or [N]: the work is taken as done, so the marker is written
        # here, the way the session would have — the done one, never a review
        # round's, since the person asked for the step to go on, not for
        # another round. Not for the retrospective, whose marker says it has
        # nothing to act on: it is closed as its /exit would close it.
        [[ -n "$round" ]] && rm -f "$round"
        [[ "$kind" == retro || -s "$done" ]] || echo "closed from sclaude's terminal ([n])" > "$done"
        rm -f "$watched_mark"
        pkill -TERM -f -- "(--session-id|--resume) ($ids)( |$)" 2>/dev/null || true
        exit 0
      fi
      if [[ "$word" == restart ]]; then
        # [r]: the step goes again — the conversation is opened again
        # (claude_launch), and this watcher goes on for it as a resumed
        # session's would (session_watch_start): no marker standing, nothing
        # before the reopening counted, an approval or a said line included.
        # The same as [R] and the next `sclaude <feature>`, only at once. So,
        # as after any resume, a session that does not write its marker again
        # ends as one a person left. Leaving the marker instead closed the
        # reopened conversation once the grace ran out — within three seconds
        # of step 2's accept — and an old approval did the same to a plan.
        rm -f ${round:+"$round"} "$done"
        # To the fraction of a second: an approval given in the same second,
        # just before the press, is not the reopened conversation's.
        started="$(date +%s.%N)"
        ended="" seen="" verdict=""
        echo restarting > "$ctl"
        pkill -TERM -f -- "(--session-id|--resume) ($ids)( |$)" 2>/dev/null || true
        continue
      fi
      size="$(stat -c %s "$transcript" 2>/dev/null || echo 0)"
      if [[ "$size" != "$lseen" ]]; then
        # Only a transcript that grew can have gone on in another one.
        chain="$(python3 "$LIB/cycle/session_end.py" chain "$transcript" 2>/dev/null)"
        if [[ -n "$chain" && "${chain##*$'\n'}" != "$transcript" ]]; then
          transcript="${chain##*$'\n'}"
          while read -r t; do
            t="${t##*/}"; t="${t%.jsonl}"
            [[ "|$ids|" == *"|$t|"* ]] || ids+="|$t"
          done <<<"$chain"
          size="$(stat -c %s "$transcript" 2>/dev/null || echo 0)"
          seen=""
        fi
        lseen="$size"
        hit="$(python3 "$LIB/cycle/session_end.py" limit "$transcript" "$started" 2>/dev/null)"
      fi
      if [[ -n "$hit" ]]; then
        read -r huuid hreset htype <<<"$hit"
        if [[ "$huuid" != "$acted" ]]; then
          if [[ "$huuid" != "$told" ]]; then
            told="$huuid"
            # A minute past the reset, or half an hour from now when the
            # entry did not say: a second limit then is simply waited out
            # again.
            if [[ "$hreset" =~ ^[0-9]+$ && "$hreset" -gt 0 ]]; then
              due=$(( hreset + ${LIMIT_MARGIN:-60} ))
            else
              due=$(( $(date +%s) + ${LIMIT_RETRY:-1800} ))
            fi
            [[ -x "${INSTRUMENTS:-}/bin/sclaude-notify" ]] \
              && "$INSTRUMENTS/bin/sclaude-notify" --in "${wt:-$cwd}" --as "${label% (*}" "Claude hit its ${htype//_/-} limit${kind:+ in the $kind session}. sclaude resumes the session by itself at $(date -d "@$due" +%H:%M)." \
                   >/dev/null 2>&1 || true
          fi
          if (( $(date +%s) >= due )); then
            acted="$huuid"
            echo "$huuid" > "$limit_file"
            pkill -TERM -f -- "(--session-id|--resume) ($ids)( |$)" 2>/dev/null || true
          fi
        fi
        continue
      fi
      marker="" since=""
      if [[ -n "$round" && -s "$round" ]]; then marker="$round"
      elif [[ -s "$done" ]]; then marker="$done"
      fi
      if [[ -n "$marker" ]]; then
        since="$(stat -c %Y "$marker" 2>/dev/null || echo 0)"
      elif [[ "$kind" != "plan" && -z "$said" ]]; then
        ended=""; continue
      fi
      # The transcript is read again only when it has grown: a planning
      # session lives for hours, and its file reaches megabytes.
      size="$(stat -c %s "$transcript" 2>/dev/null || echo 0)"
      if [[ "$size:$since" != "$seen" ]]; then
        seen="$size:$since"
        if [[ -n "$marker" ]]; then
          verdict="$(python3 "$LIB/cycle/session_end.py" watch "$transcript" "$since" 2>/dev/null)"
        elif [[ -n "$said" ]]; then
          verdict="$(python3 "$LIB/cycle/session_end.py" watch-said "$transcript" "$started" "$said" 2>/dev/null)"
        else
          verdict="$(python3 "$LIB/cycle/session_end.py" watch-plan "$transcript" "$started" 2>/dev/null)"
        fi
      fi
      case "$verdict" in
        human)
          # The person spoke within the grace: what the grace is for, perhaps.
          # Not a session [k] kept, nor one past its grace: that was no grace.
          if [[ -n "$ended" && ! -e "$keep" ]] && (( $(date +%s) - ended < ${grace:-30} )); then
            wait_note session-grace human "$(( $(date +%s) - ended ))" "${kind:--} grace ${grace:-30}"
          fi
          [[ -n "$marker" ]] && rm -f "$marker"; ended="" ;;
        ended)
          [[ -n "$ended" ]] || ended="$(date +%s)"
          # The grace is for reading the report. Step 2's marker says
          # `accepted` once the person has read it and answered its question
          # (code.md): there is nothing left to wait for.
          grace="${SESSION_GRACE:-30}"
          [[ "$marker" == "$done" && "$(head -c 16 "$done" 2>/dev/null)" == accepted* ]] \
            && grace="${SESSION_ACCEPT_GRACE:-3}"
          # [k]: kept open on the person's word, until they take it back.
          if [[ ! -e "$keep" ]] && (( $(date +%s) - ended >= grace )); then
            # A key's word read again, now: said since the top of this pass
            # — [r] with [k] taken off between the two reads — it is the next
            # pass's to act on. Closed here as ended, the press was lost.
            case "$(cat "$ctl" 2>/dev/null || true)" in
              next|next-later|restart) continue ;;
            esac
            wait_note session-grace closed "$(( $(date +%s) - ended ))" "${kind:--} grace $grace"
            # What session_ended looks for to know it was not a person's /exit.
            [[ -n "$marker" ]] || echo "${said:-plan approved}" > "$done"
            # No watcher from here: the keys that need one are not offered
            # to a launch after this (session_key_has).
            rm -f "$watched_mark"
            pkill -TERM -f -- "(--session-id|--resume) ($ids)( |$)" 2>/dev/null || true
            exit 0
          fi ;;
        *) ended="" ;;
      esac
    done
  ) &
  SESSION_WATCHER=$!
  # Its kind and its pid, for the keys: one left by a watcher that is gone —
  # a sclaude killed — is no watcher.
  echo "${kind:--} $SESSION_WATCHER" > "$SESSION_WATCHED"
  return 0
}

session_watch_stop() {
  local kind="" word="" ctl=""
  if [[ -n "${SESSION_WATCHED:-}" ]]; then
    # From the variable: the watcher takes its mark off as it closes the session.
    kind="${SESSION_WATCHED_KIND:-}"
    ctl="$(session_ctl_file "$SESSION_WATCHED_ID")"
    word="$(cat "$ctl" 2>/dev/null || true)"
  fi
  if [[ -n "${SESSION_WATCHER:-}" ]]; then
    # The watcher goes before its files do: with [k]'s file taken away while
    # it still polled, its next pass found an ended turn and nothing keeping
    # the session, and closed it. Held still first, so that it neither makes
    # that pass nor starts another `sleep` meanwhile; then it dies at once,
    # mid-iteration or not, as it always has. The `sleep` of its poll, which
    # would outlive it holding whatever output it was given until the poll
    # ends, goes after it — only the sleep, anything else it had running is
    # left as before; killed after the watcher, so no bash is left to report
    # it "Terminated" in the person's terminal.
    local poll
    kill -STOP "$SESSION_WATCHER" 2>/dev/null || true
    poll="$(pgrep -P "$SESSION_WATCHER" -x sleep 2>/dev/null || true)"
    kill "$SESSION_WATCHER" 2>/dev/null || true
    kill -CONT "$SESSION_WATCHER" 2>/dev/null || true
    [[ -z "$poll" ]] || kill $poll 2>/dev/null || true
    wait "$SESSION_WATCHER" 2>/dev/null || true
    SESSION_WATCHER=""
  fi
  if [[ -n "${SESSION_WATCHED:-}" ]]; then
    rm -f "$SESSION_WATCHED" "$(session_keep_file "$SESSION_WATCHED_ID")"
  fi
  SESSION_WATCHED=""
  # The person's word from sclaude's tab about when to go on (session_keys
  # in pane.sh). [N]: everything after this session runs as on its own end,
  # and sclaude stops where the next step would begin (stop_asked).
  [[ "$word" == next-later ]] && : > "$(stop_file)"
  # [R] on any session but a step's, whose end session_ended handles: closed
  # as /exit would close it, and sclaude stops right here, as if its terminal
  # had been closed while the session ran. Every such session is opened again
  # where it was by the next run, which finds its record unfinished.
  if [[ "$word" == later ]]; then
    case "$kind" in
      plan|code|pr|review) ;;
      *)
        rm -f "$ctl"
        stty sane 2>/dev/null || true
        echo ""
        say_here "${BOLD}Closed at your word ([R]): sclaude stops here.${OFF}"
        info "  Come back with: $SELF${ASK_SLUG:+ $ASK_SLUG} — it opens this conversation again."
        exit 0 ;;
    esac
  fi
  return 0
}

# A session has ended, and the feature's topic is told so by its phase_line
# however it ended: "finished" when the watcher closed it on its report,
# "ended" when a person left it, which says nothing of the work being done.
# When the watcher closed it, its report too, printed in this terminal under
# the same line, with the marker removed so the next session starts clean. The
# note is what only a close by sclaude says — the retrospective's "nothing to
# act on" — and goes with it; the tally is what the session leaves however it
# ended — a fix session's commits and findings (review_tally).
#
#   session_closed <marker> <cwd> <session> <note> <tally> <phase_line kind and args>
#
# Returns 0 when the session was closed by sclaude, 1 when a person left it.
session_closed() {
  local marker="$1" cwd="$2" session="$3" note="$4" tally="$5" line
  shift 5
  if [[ ! -s "$marker" ]]; then
    ask_feed say "$(phase_line ended "$@")${tally:+ · $tally}"
    return 1
  fi
  rm -f "$marker"
  line="$(phase_line finished "$@")${tally:+ · $tally}${note:+ · $note}"
  ask_feed say "$line"
  # The terminal may have been left mid-redraw by the signal.
  stty sane 2>/dev/null || true
  echo ""
  say_here "${BOLD}$line — sclaude closed it.${OFF}"
  session_report "$cwd" "$session"
  return 0
}

# The last message of a session the orchestrator closed, printed in its own
# terminal: claude's screen went with the process, and the person may not have
# finished reading the report before it did. Its advice to type /exit is cut
# out by session_end.py, and the line after it says why: whatever the cut
# missed, the person reads that the session is closed.
#
# All of it is for this terminal only, so echo rather than say: the message
# itself never reaches the feature's topic, and the two headings around it
# would arrive there bare, the /exit one about a terminal the reader is not at.
#
#   session_report <wt> <session>
session_report() {
  local text
  text="$(python3 "$LIB/cycle/session_end.py" last "$(session_transcript "$1" "$2")" 2>/dev/null || true)"
  [[ -n "$text" ]] || return 0
  echo ""
  echo "${BOLD}Its last message:${OFF}"
  echo ""
  printf '%s\n' "$text" | sed 's/^/  /'
  echo ""
  echo "${BOLD}No /exit needed — sclaude carries on.${OFF}"
}
