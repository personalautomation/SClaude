#!/usr/bin/env bash
#
# Step 4's gate, on the way in and on the way out: it asks the pull request
# whether the review finished with nothing open, the threads the person kept,
# and the reports.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The way back to a session, from the gate or from the local review whose
# pass found something; each spelled out, as the map's arrows are.
#
#   review_back_edge <wt> <review_close|local_pass> <by> <how> [<key>=<value>…]
review_back_edge() {
  local wt="$1" from="$2"
  shift 2
  if [[ "$from" == local_pass ]]; then
    cycle_edge "$wt" local_pass review "$@"
  else
    cycle_edge "$wt" review_close review "$@"
  fi
}

# Where a feature stands as step 4 opens, by the ways its history wrote:
# `out` before the step (on the draft pull request, or nothing written),
# `gate` where an entry was left in the gate, `session` at the session —
# or past step 4 (`later`), sent back by a way no code writes into the
# session (a hand-back taken up at the next start, a rollback, a return
# from a held production): then the gate's ways would hang from the last
# pass's close, and none are written.
#
#   review_entry_place <wt>
review_entry_place() {
  case "$(last_place "$1" draft_pr ci_review review_close local_pass review \
            preview in_qa qa_check qa_verdict handoff merge merge_wait merged ship prod hold_ways epilogue)" in
    review) echo session ;;
    ci_review|review_close|local_pass) echo gate ;;
    draft_pr|"") echo out ;;
    *) echo later ;;
  esac
}

# May step 4 close? Waits out a review still running, then, if anything is
# left open, goes back to a review session unasked — held instead when the
# person left the last one with [g] off. Returns 0 to go on closing.
#
#   review_close_gate <wt> <slug> <pr> [entry|quiet]
#
# Its answer, as `pr_context.py --close` gives it: `ok`, `pending` or
# `open: <why>`. Anything unreadable is `ok`.
#
# With `entry` or `quiet`, the same gate opens step 4, before any session.
# `quiet` writes none of the gate's ways to the history: run_step gives it
# where the feature stands at the session already, or past step 4
# (review_entry_place) — it came there by a way of its own, or by one no
# code writes. With a known REVIEW_KNOWN_COUNT (review: local,
# the search ended, counted by run_step) no pass runs and that count decides;
# `?`, a count that could not be read, opens the session. 0 when the
# step may close with no session at all, 1 when a session is needed, which
# run_step then opens — the gate asks nothing and opens none itself. It asks
# the pull request the way in's question, `pr_context.py --state` (clean,
# unreviewed, dirty, pending, unknown): conservative where the way out is
# lenient — a person's comment anywhere, or a state that cannot be read, is a
# session — since a wrong "clean" here skips the only look at what people
# wrote. The word it ended on is left in REVIEW_ENTRY_WORD, and the local
# review's count of what is open (or `failed`) in REVIEW_ENTRY_COUNT, for the
# session run_step opens.
review_close_gate() {
  local wt="$1" slug="$2" pr="$3" entry="${4:-}" word waited=0 announced=0 answer repo said="" said_read=0 failed=0 go_box=""
  local gate_reported=0 question=--close skippable=1 edges=1
  if [[ -n "$entry" ]]; then
    question=--state
    [[ "$entry" == quiet ]] && edges=0
    # A session of its own already (one interrupted is resumed, never
    # skipped), or the review sent back: the pull request is not asked —
    # the session opens whatever it shows, so nothing is waited for, no
    # rerun after the quota either — only the local pass gives its count.
    review_skippable "$wt" "$slug" || skippable=0
  fi
  REVIEW_ENTRY_WORD="" REVIEW_ENTRY_COUNT=""
  # Where the way back to a session starts: the gate, or the local review
  # when the gate's own pass found something.
  local back_from=review_close
  # Who let the step close, for the history's way out of the gate, written
  # as the step closes (after_step); the way back is written here.
  REVIEW_CLOSE_BY=sclaude REVIEW_CLOSE_HOW="nothing open on the PR" REVIEW_CLOSE_NOTE=""
  # No pull request to ask: the way out lets the step close, the way in
  # opens the session, as it did before the gate was asked there.
  local unread=0; [[ -n "$entry" ]] && unread=1
  [[ -n "$pr" && "$pr" != "null" ]] || return "$unread"
  command -v gh >/dev/null 2>&1 || return "$unread"
  repo="$(gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || return "$unread"
  # A project that reviews on this machine: the review the workflow would run
  # after the session's push runs here, once the pull request has nothing
  # open but review threads — it resolves the ones the push fixed and posts
  # what it finds, and the pull request is asked again. Not before: a red
  # check or an unpushed commit sends the work back anyway, and a review of
  # it would be paid for nothing. A review that did not run is put to the
  # person rather than sent back to a session, which could do nothing about
  # it and would end the same way.
  #
  # On the way in the pass runs whatever the pull request shows — the session
  # it opens starts on the findings — except once the person ended the
  # search: what is open then goes to the session as it is.
  local local_due=0
  [[ "$(project_review_mode "$wt")" == "local" ]] && local_due=1
  if [[ -n "$entry" && -n "${REVIEW_KNOWN_COUNT:-}" ]]; then
    local_due=0
    REVIEW_ENTRY_COUNT="$REVIEW_KNOWN_COUNT"
  fi
  while :; do
    # Findings the review on this machine left open are open, whatever the
    # pull request answers: its own threads are not in review_state's word;
    # nor is a count that could not be read.
    if [[ -n "$entry" && "$REVIEW_ENTRY_COUNT" =~ ^[1-9][0-9]*$ ]]; then
      word="open: the review on this machine leaves $REVIEW_ENTRY_COUNT finding(s) open"
      break
    fi
    if [[ -n "$entry" && "$REVIEW_ENTRY_COUNT" == "?" ]]; then
      word="open: the threads the review left could not be counted"
      break
    fi
    if [[ -n "$entry" && "$skippable" -eq 0 ]]; then
      word="open: the step's own session"
    else
      word="$(python3 "$LIB/review/pr_context.py" "$question" "$wt" "$pr" "$repo" 2>/dev/null || true)"
      if [[ "$word" == open:*red:* || "$word" == dirty ]] && review_quota_rerun "$wt" "$slug" "$pr" "$repo"; then
        continue
      fi
    fi
    # On the way in the local pass comes first, whatever is still running:
    # what it finds is the session's; a wait is only for a close.
    if [[ "$word" != "pending" || ( -n "$entry" && "$local_due" -eq 1 ) ]]; then
      if [[ "$local_due" -eq 1 ]] && [[ -n "$entry" || "$word" == "ok" || "$word" == yours:* \
            || "$word" =~ ^open:\ [0-9]+\ review\ thread\(s\)\ open$ ]]; then
        local_due=0
        local count
        # The search ended: the session's fixes are checked only when the
        # person says so — a pass is paid for, and they stopped the review
        # to stop paying for rounds.
        if [[ -n "$(review_enough "$wt")" ]] && ! local_review_done "$wt"; then
          count="$(local_review_count "$wt" "$pr")" || count="?"
          echo ""
          info "  You ended the search for new findings; $count thread(s) are open on PR #$pr."
          if review_go_on "$wt"; then
            info "  [g] go on by itself is ticked: checking the fixes with a review pass."
            answer=1
          else
            # One choice of three, asked once: as two yes/no questions in a
            # row it was answered twice, the second only after the first's "no".
            info "    1) Check the fixes with a review pass — it resolves the threads they fixed and looks for nothing new"
            info "    2) Close step 4 now, with the $count thread(s) as they are"
            info "    3) Leave it open and come back later"
            # Asked again on anything but 1-3: a stray Enter left in the
            # terminal read as "leave it open" and ended the step. No answer
            # at all (nobody to ask) leaves it open, as before.
            while :; do
              ask "${BOLD}Choose 1-3: ${OFF}" answer "pick:3" \
                "Check the fixes" "Close step 4" "Leave it open" || { answer=3; ASKED_HOW=""; break; }
              [[ "$answer" == [123] ]] && break
              printf '%s\n' "  Answer 1, 2 or 3." >&2
            done
          fi
          if [[ "$answer" != 1 ]]; then
            if [[ "$answer" != 2 ]]; then
              info "  Left open. Come back with: $SELF $slug"
              cycle_edge "$wt" review_close review "$( [[ -n "$ASKED_HOW" ]] && echo person || echo none)" \
                "$ASKED_HOW" note="left open, $count thread(s)"
              return 1
            fi
            [[ "$count" =~ ^[0-9]+$ ]] \
              && state_set "$wt/.sclaude/local/feature/state.json" steps.review.left_open "$count" 2>/dev/null
            say "${BOLD}Step 4 closes as you said, with the threads as they are.${OFF}"
            REVIEW_CLOSE_BY=person REVIEW_CLOSE_HOW="$ASKED_HOW" REVIEW_CLOSE_NOTE="$count thread(s) left as they are"
            return 0
          fi
        fi
        # The pass the gate runs is a block of the map's own: from the gate
        # to the local review, and from it back to the gate, or on to a
        # session with what it found (the way back below starts there).
        [[ "$edges" -eq 0 ]] || cycle_edge "$wt" review_close local_pass sclaude "review: local" note="${word}"
        # On the way in, a head the gate reviewed already was reported where
        # it ran: its table is not printed again before the session.
        local fresh_pass=1
        [[ -n "$entry" ]] && local_review_done "$wt" && fresh_pass=0
        count="$(local_review "$wt" "$pr")" || count="failed"
        [[ -n "$entry" ]] && REVIEW_ENTRY_COUNT="$count"
        # Nothing printed is read as nothing found below, and recorded so.
        if [[ "$count" =~ ^[0-9]*$ ]]; then
          [[ "${count:-0}" -eq 0 && "$edges" -eq 1 ]] && cycle_edge "$wt" local_pass review_close sclaude "nothing found"
          [[ "${count:-0}" -gt 0 ]] && back_from=local_pass
        fi
        if [[ "$count" == "failed" ]]; then
          [[ "$edges" -eq 0 ]] || cycle_edge "$wt" local_pass review_close sclaude "the review on this machine" note="it did not run"
          failed=$((failed + 1))
          warn ""
          warn "  The review on this machine did not run on $(git -C "$wt" rev-parse --short HEAD 2>/dev/null); its log: $(local_review_file "$wt" .log)"
          # On the way in the session opens on what is open, as before the
          # gate was asked there; the pass runs again at its end.
          if [[ -n "$entry" ]]; then
            word="open: the review on this machine did not run"
            break
          fi
          # A "no" is not "leave": the review is what the person wants, so it
          # runs again here, rather than at the next `sclaude` they would
          # have to type. Only no answer at all (nobody to ask) leaves it open.
          if review_go_on "$wt" && [[ "$failed" -le "$REVIEW_GO_ON_RETRIES" ]]; then
            # After a pause that grows, a minute more each time: a failure
            # that lasts — a usage limit, the network — would otherwise spend
            # every retry in a minute.
            info "  [g] go on by itself is ticked: reviewing it again in $((failed * REVIEW_GO_ON_PAUSE))s ($failed of $REVIEW_GO_ON_RETRIES)."
            if review_go_on_pause "$wt" $((failed * REVIEW_GO_ON_PAUSE)); then
              local_due=1
              continue
            fi
          fi
          if ! ask "${BOLD}Go on with this head unreviewed? n reviews it again [y/n] ${OFF}" answer yn; then
            info "  Left open. Come back with: $SELF $slug"
            cycle_edge "$wt" review_close review none "" note="the review on this machine did not run"
            return 1
          fi
          is_yes "$answer" && REVIEW_CLOSE_BY=person REVIEW_CLOSE_HOW="$ASKED_HOW" \
            REVIEW_CLOSE_NOTE="the head unreviewed: the review on this machine did not run"
          if ! is_yes "$answer"; then
            info "  Reviewing it again; Ctrl-C leaves, and the next \`$SELF\` starts it again."
            local_due=1
            continue
          fi
        elif [[ "$count" -eq 0 ]]; then
          # Nothing left open: the step closes on this pass, and its round
          # (found nothing, nothing to fix) ends the table the person last saw
          # — unless that table is the one just printed on this head, by the
          # pass on the way into step 4.
          [[ "$fresh_pass" -eq 1 ]] && review_report_unshown "$wt" "$slug"
          gate_reported=1
        elif [[ "$count" -gt 0 ]]; then
          # The report printed as the session ended was made before this
          # run: once more with it, where the person decides whether to go
          # on fixing.
          [[ "$fresh_pass" -eq 1 ]] && review_report "$wt" "$slug"
          gate_reported=1
          # Open by its own count, not by asking GitHub again: a finding in
          # the conversation, or one still waiting to be posted, is no thread
          # for the pull request to show.
          word="open: the review on this machine leaves $count finding(s) open"
          break
        fi
        continue
      fi
      break
    fi
    if [[ "$waited" -ge "$REVIEW_WAIT_MAX" ]]; then
      word="open: the automatic review of PR #$pr has not finished"
      break
    fi
    if [[ "$announced" -eq 0 ]]; then
      announced=1
      if [[ -n "$entry" ]]; then
        info "  Waiting for the automatic review of PR #$pr to finish."
      else
        info "  The automatic review of PR #$pr is still running; step 4 closes once it has finished."
      fi
      info "  Ctrl-C to leave — the feature resumes here with: $SELF $slug"
    fi
    # `s` here as in the local review, for the review in Actions: what it
    # posts now is the last search — a session still takes what was open
    # before, but what the reviews after it find new is left on the pull
    # request (see below). A local review takes its keys itself.
    # Read once a wait, and kept here after: a python per poll for a hint.
    # [g] too: it decides the questions after this wait in Actions as well.
    [[ "$said_read" -eq 1 ]] || { said="$(review_enough "$wt")"; go_box="$(review_go_box "$wt")"; said_read=1; }
    if [[ -t 1 ]]; then
      local hint="only if you want to step in: ${BOLD}[s]${OFF} last review for new findings" what="the review"
      [[ "$local_due" -eq 1 ]] && { what="the checks"; hint=""; }
      [[ -n "$said" && -n "$hint" ]] && hint="the last review for new findings · ${BOLD}[s]${OFF} takes it back"
      [[ -n "$hint" ]] && hint+=" · $go_box ${BOLD}[g]${OFF} go on by itself"
      printf '\r\033[2K\033[?7l  %sRunning by itself%s — waiting for %s of PR #%s (%s so far)%s\033[?7h' \
        "$DIM" "$OFF" "$what" "$pr" "$(regression_duration "$waited")" "${hint:+ · $hint}"
    fi
    local began=$SECONDS
    poll_pause "$MERGE_POLL"
    waited=$((waited + SECONDS - began))
    # Cleared before the next look: what that prints starts a line of its own.
    [[ -t 1 ]] && printf '\r\033[2K'
    if [[ "$POLL_KEY" == [gG] && "$local_due" -eq 0 ]]; then
      review_go_on_toggle "$wt"; go_box="$(review_go_box "$wt")"
    fi
    if [[ "$POLL_KEY" == [sS] && "$local_due" -eq 0 ]]; then
      if [[ -n "$said" ]]; then said=""; review_enough_set "$wt" ""
      else said=pass; review_enough_set "$wt" pass
      fi
    fi
  done
  # The way in: closed with no session when nothing is open and nothing
  # waits for one; else run_step opens the session, which asks nothing here.
  if [[ -n "$entry" ]]; then
    REVIEW_ENTRY_WORD="$word"
    if [[ "$skippable" -eq 1 && ( "$word" == clean || "$word" == unreviewed ) ]]; then
      REVIEW_CLOSE_NOTE="$word"
      return 0
    fi
    [[ "$edges" -eq 0 ]] || review_back_edge "$wt" "$back_from" sclaude "something open on the PR" note="$word"
    return 1
  fi
  # The search ended (review_enough), with the review in Actions: it cannot
  # be told to only check the fixes, so what it posted after the last session
  # began is left on the pull request; what that session had and did not
  # settle goes the ordinary way. A local review posts nothing new by then.
  if [[ -n "$(review_enough "$wt")" && "$word" =~ ^open:\ [0-9]+\ review\ thread\(s\)\ open$ ]]; then
    local split older newer
    split="$(python3 "$LIB/review/pr_context.py" --open-since "$wt" "$pr" "$repo" \
               "$(review_session_since "$wt")" 2>/dev/null || true)"
    read -r older newer <<<"$split"
    if [[ "${older:-}" == "0" && "${newer:-0}" -gt 0 ]]; then
      review_enough_close "$wt" "$pr" "$newer"
      REVIEW_CLOSE_HOW="you ended the search" REVIEW_CLOSE_NOTE="$newer finding(s) left on the PR"
      return 0
    fi
  fi
  # Only the threads the person kept: no session, a wait for their hand. Once
  # they are resolved the pull request is asked again from the top — whatever
  # else is open by then takes the ordinary way.
  if [[ "$word" == yours:* ]]; then
    if review_night_offer "$wt" "$slug" "$pr" "$repo"; then
      cycle_edge "$wt" review_close review person "$ASKED_HOW" note="threads left at night"
      # Taken back: the threads are open work again, and the round goes the
      # way any open thread does — a fresh session (the one resumed would be
      # the night's, told to decide), and the gate after it as after any.
      python3 "$LIB/review/pr_context.py" --night-take "$wt" >/dev/null 2>&1 || true
      state_set "$wt/.sclaude/local/feature/state.json" steps.review.session null
      run_step "$wt" "$slug" review
      return 1
    fi
    review_yours_wait "$wt" "$slug" "$pr" "$repo" || return 1
    review_close_gate "$wt" "$slug" "$pr"
    return $?
  fi
  [[ "$word" == open:* ]] || return 0

  # Findings left open are what a report printed on this head says, its
  # last round yellow (review_report.py): said again here, in two more lines,
  # they were read as news. With no report on this head that showed these
  # findings and rounds — the review in Actions posted more or finished a
  # run while the gate waited, the person resolved some, a gate reached with
  # no session before it — the report is printed now, and the topic hears
  # it as it hears every report. Anything else that holds
  # the step — a red check, a review still running — is not in the table,
  # and is said.
  # The feature's topic still hears both lines, as before: the report's
  # message there carries the newest session's row only, and this is where
  # the review stands from the fix session's last look (docs/keepawake.md).
  # And where the last round left it, counted from the fix session's last
  # look: what the review confirmed fixed, what the session had seen and
  # did not fix, what the review found since (brief in pr_context.py).
  local standing
  standing="$(python3 "$LIB/review/pr_context.py" --brief "$wt" "$pr" "$repo" \
                "$(review_last_look "$wt")" 2>/dev/null || true)"
  if [[ "$word" =~ ^open:\ ([0-9]+\ review\ thread\(s\)\ open|the\ review\ on\ this\ machine\ leaves\ [0-9]+\ finding\(s\)\ open)$ ]]; then
    # Printed by this gate's own pass just now; else asked again, and said
    # only when what it shows — the open findings and the rounds — is not
    # what was last shown on this head.
    [[ "$gate_reported" -eq 0 ]] && review_report_unshown "$wt" "$slug"
    # And kept for a question that may follow ([g]'s ceiling, then "Close
    # step 4 anyway?"): the phone shows a question with the lines before it
    # (ask_note), and this is what that question is about.
    ask_feed warn "Step 4 is not done — ${word#open: }."
    ask_note "Step 4 is not done — ${word#open: }."
    [[ -n "$standing" ]] && { ask_feed warn "  $standing"; ask_note "  $standing"; }
  else
    warn ""
    warn "${BOLD}Step 4 is not done — ${word#open: }.${OFF}"
    [[ -n "$standing" ]] && warn "  $standing"
  fi
  # Back to a session unasked, whoever closed the last one: the person ends
  # the rounds with the review's keys — [s] (⏭ on the topic) makes the next
  # session the last for new findings, [n]/[r] in sclaude's tab act at once —
  # and a question here only held the rounds until somebody came to answer
  # it. The one question left is [g]'s ceiling: thirty rounds unattended,
  # and the person decides whether there is a thirty-first.
  local go_on=0
  if review_go_on "$wt"; then
    review_go_on_round "$wt" && go_on=1 || go_on=2
  fi
  # Said before the next session: the rounds stopping converging is what
  # [s] is for.
  review_stuck_say "$wt"
  # Except after the person left the session (/exit, Ctrl-C) with [g] off:
  # that is their word to stop, and going back unasked reopened the same
  # conversation within seconds when it had committed nothing new.
  if [[ -n "${SESSION_EXITED:-}" && "$go_on" -eq 0 ]]; then
    info "  You left the session: step 4 stays open. Come back with: $SELF $slug"
    review_back_edge "$wt" "$back_from" person "${SESSION_HOW:-/exit or Ctrl-C}" note="held: ${word#open: }"
    return 1
  fi
  # Unsaid: the session's own heading follows, its status line with [s].
  local back_by=sclaude back_how="back unasked"
  [[ "$go_on" -eq 1 ]] && back_how="[g] — you are away"
  if [[ "$go_on" -eq 2 ]]; then
    ask "${BOLD}Back to a review session for it? [y/n] ${OFF}" answer yn && back_by=person || back_by=none
    back_how="$ASKED_HOW ([g]'s ceiling)"
  else
    answer=y
  fi
  if is_yes "$answer"; then
    review_back_edge "$wt" "$back_from" "$back_by" "$back_how" note="${word#open: }"
    # A session sclaude closed: review_reopen picks the session, a fresh one
    # for a new round, as it does unasked.
    if [[ -n "${SESSION_AUTO_CLOSED:-}" ]]; then
      review_reopen "$wt" "$slug" "$pr" "$repo" "$waited"
      return 1
    fi
    run_step "$wt" "$slug" review
    return 1
  fi
  ask "${BOLD}Close step 4 anyway, with that left as it is? [y/n] ${OFF}" answer yn && back_by=person || back_by=none
  if ! is_yes "$answer"; then
    info "  Left open. Come back with: $SELF $slug"
    review_back_edge "$wt" "$back_from" "$back_by" "$ASKED_HOW" note="held: ${word#open: }"
    return 1
  fi
  REVIEW_CLOSE_BY=person REVIEW_CLOSE_HOW="$ASKED_HOW" REVIEW_CLOSE_NOTE="closed anyway: ${word#open: }"
  return 0
}

# Step 4 closes with the findings the review in Actions posted after the
# person ended the search (review_enough): they stay open threads on the
# pull request, nothing is resolved or dropped for it.
#
#   review_enough_close <wt> <pr> <count>
review_enough_close() {
  local wt="$1" pr="$2" count="$3"
  state_set "$wt/.sclaude/local/feature/state.json" steps.review.left_open "$count" 2>/dev/null
  say "${BOLD}Step 4 closes: you ended the search for new findings.${OFF}"
  info "  $count finding(s) the review posted after that stay open on PR #$pr as they are."
}

# The review threads the person decided to leave as they are, and that are
# still open: theirs to resolve on GitHub (see YOURS_FILE in pr_context.py).
#
#   review_yours_report <wt> <pr> [<repo>]
#
# Printed by sclaude itself at the end of every review session rather than left
# to the session's report: once three reports in a row said "you close the
# thread" in their middle, with no link, and the thread came back each round.
# Prints nothing when there is nothing to resolve. Returns 0 when it printed.
review_yours_report() {
  local wt="$1" pr="$2" repo="${3:-}" lines link where note
  [[ -s "$wt/.sclaude/local/feature/review-yours" && -n "$pr" && "$pr" != "null" ]] || return 1
  [[ -n "$repo" ]] || repo="$(gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || return 1
  lines="$(python3 "$LIB/review/pr_context.py" --yours "$wt" "$pr" "$repo" 2>/dev/null || true)"
  [[ -n "$lines" ]] || return 1
  echo ""
  say "${BOLD}Yours to resolve on GitHub — you decided to leave these as they are:${OFF}"
  while IFS=$'\t' read -r link where note; do
    say "  • $where${note:+ — $note}"
    say "    $link"
  done <<< "$lines"
  info "  Open each link and press \"Resolve conversation\". Until then the review counts them as open,"
  info "  and step 4 cannot close."
  return 0
}

# Decisions a night session took for the person (NIGHT_MARK in
# pr_context.py) are theirs to confirm: offered a session that asks about
# each and, on their yes, replies and resolves the thread itself — rather
# than left for their hand on GitHub. The question waits for the person, so
# at night it waits. 0 when they took the session.
#
#   review_night_offer <wt> <slug> <pr> <repo>
review_night_offer() {
  local wt="$1" slug="$2" pr="$3" repo="$4" night answer
  night="$(python3 "$LIB/review/pr_context.py" --night-yours "$wt" "$pr" "$repo" 2>/dev/null || echo 0)"
  [[ "${night:-0}" =~ ^[0-9]+$ && "$night" -gt 0 ]] || return 1
  echo ""
  say "${BOLD}$night review thread(s) were left at night for you to confirm.${OFF}"
  notify_feature "$slug" --wt "$wt" \
    "PR #$pr: $night review thread(s) were left at night for you to confirm." \
    >/dev/null 2>&1 || true
  # A night still on would reach the session (sclaude's own prompt does not
  # end it), which would then decide again instead of asking: the person
  # answering here is back, so a yes ends it.
  local isleep="$INSTRUMENTS/skills/isleep/night.py" ends=""
  [[ -f "$isleep" ]] && python3 "$isleep" active >/dev/null 2>&1 && ends=" (this ends the night)"
  ask "${BOLD}Go through them with a review session now$ends? [y/n] ${OFF}" answer yn
  is_yes "$answer" || return 1
  [[ -n "$ends" ]] && python3 "$isleep" off --away \
    "The person ended the night by answering sclaude (its terminal or the phone), and they have just written." \
    >/dev/null 2>&1
  return 0
}

# Step 4 has nothing open but the threads the person kept: no session for
# them, only a wait for the person to resolve them on GitHub.
#
#   review_yours_wait <wt> <slug> <pr> <repo>
#
# Returns 0 once none of them is open, 1 when the person leaves (Ctrl-C ends
# sclaude itself; a "no" leaves the step open). Whether anything else is open
# is the caller's to ask again.
review_yours_wait() {
  local wt="$1" slug="$2" pr="$3" repo="$4" word answer
  # Asked even when the links could not be read: answering "resolved" for the
  # person sent the gate round again, asking GitHub the same thing for ever.
  review_yours_report "$wt" "$pr" "$repo" \
    || warn "  Threads you decided to leave are still open on PR #$pr — resolve them there."
  notify_feature "$slug" --wt "$wt" \
    "PR #$pr waits for you — resolve on GitHub the review threads you decided to leave as they are." \
    >/dev/null 2>&1 || true
  while :; do
    ask "${BOLD}Resolved them? [y/n] ${OFF}" answer yn
    if ! is_yes "$answer"; then
      info "  Left open. Come back with: $SELF $slug"
      return 1
    fi
    word="$(python3 "$LIB/review/pr_context.py" --close "$wt" "$pr" "$repo" 2>/dev/null || true)"
    [[ "$word" == yours:* ]] || return 0
    warn "  GitHub still shows ${word#yours: } of them open."
    review_yours_report "$wt" "$pr" "$repo" || true
  done
}

# What a product's review sessions cost, from review_context_log's log.
cmd_review_stats() {
  local root
  root="$(main_repo 2>/dev/null)" || die "run it inside a product's repository"
  python3 "$LIB/review/review_stats.py" "$root/.sclaude/local/review-context.log"
}

# Whether another review round is worth it: rounds, findings fixed and closed
# without a fix, findings on earlier fixes, cost and the trend.
# Counted from the pull request and the feature's state, without a model.
# Printed at the close of every review round and by `sclaude review-report`.
#
#   review_report <wt> <slug>
# The report, unless what it would show is what the last report in this
# process showed on this head (REVIEW_REPORTED, written by review_report).
#
#   review_report_unshown <wt> <slug>
review_report_unshown() {
  local unless=""
  # Unset until a report in this process showed something (set -u).
  local reported="${REVIEW_REPORTED:-}"
  [[ -n "$reported" && "${reported%% *}" == "$(git -C "$1" rev-parse HEAD 2>/dev/null)" ]] \
    && unless="${reported#* }"
  REVIEW_REPORT_UNLESS="$unless" review_report "$1" "$2"
}

review_report() {
  local wt="$1" slug="$2" state pr repo
  state="$wt/.sclaude/local/feature/state.json"
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" ]] || return 0
  repo="$(gh_repo 2>/dev/null || true)"
  # The last session's numbers go to the feature's topic as well, a message
  # per round (ask_notice) — not for the report between two passes of one
  # local review (REVIEW_REPORT_QUIET), which would send one each pass.
  local brief stuck shown; brief="$(mktemp)"; stuck="$(mktemp)"; shown="$(mktemp)"
  # <REVIEW_REPORT_UNLESS>: what the report last showed on this head, as it
  # wrote it ("open:<ids> rounds:<finished>/<all>", review_report.py); the
  # same again, it prints and sends nothing (review_close_gate).
  SCLAUDE_REPORT_BRIEF="$brief" SCLAUDE_REPORT_STUCK="$stuck" SCLAUDE_REPORT_OPEN="$shown" \
    SCLAUDE_REPORT_UNLESS="${REVIEW_REPORT_UNLESS:-}" \
    python3 "$LIB/review/review_report.py" "$wt" "$pr" "$repo" \
    "$(state_get "$state" branch 2>/dev/null || true)" 2>/dev/null || true
  # The verdict, when the rounds stopped converging, for review_stuck_say;
  # "-" when they did not, and nothing when the report could not tell, which
  # keeps what was there.
  local verdict; verdict="$(cat "$stuck" 2>/dev/null)"
  if [[ "$verdict" == "-" ]]; then
    state_set "$state" steps.review.stuck "" 2>/dev/null || true
  elif [[ -n "$verdict" ]]; then
    state_set "$state" steps.review.stuck "$verdict" 2>/dev/null || true
    state_set "$state" steps.review.stuck_pr "$pr" 2>/dev/null || true
  fi
  local ASK_SLUG="$slug"
  # The head the terminal last saw a report on, and what it showed: the open
  # findings and the rounds (review_close_gate). Kept as it was when nothing was printed:
  # the threads unreadable, or the same as last shown.
  [[ -s "$shown" ]] && REVIEW_REPORTED="$(git -C "$wt" rev-parse HEAD 2>/dev/null) $(cat "$shown")"
  [[ -n "${REVIEW_REPORT_QUIET:-}" ]] || ask_notice "$(cat "$brief" 2>/dev/null)"
  rm -f "$brief" "$stuck" "$shown"
}

cmd_review_report() {
  require_repo
  local slug="${1:-}" wt
  [[ -n "$slug" ]] || die "name the feature: $SELF review-report <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"
  review_report "$wt" "$slug"
}

# `sclaude checks [<pr>]`: step 4's wait after a push, from the feature's
# worktree; the pull request of the current branch when none is named. Its
# exit code is the verdict: see wait_checks in pr_context.py. Not `die`, whose
# 1 is the verdict "red": what stops it before the wait is "could not read".
cmd_checks() {
  local pr="${1:-}" wt repo
  wt="$(git rev-parse --show-toplevel 2>/dev/null)" \
    || { echo "could not read: not a git repository: $(pwd)"; exit 4; }
  if [[ -z "$pr" ]]; then
    pr="$(cd "$wt" && gh pr view --json number --jq .number 2>/dev/null)" \
      || { echo "could not read: no pull request for this branch; name it, $SELF checks <pr>"; exit 4; }
  fi
  [[ "$pr" =~ ^[0-9]+$ ]] || { echo "could not read: not a pull request number: $pr"; exit 4; }
  repo="$(REPO="$wt" gh_repo)"
  local rc=0
  # Waiting again after a red: this launch fixed what that red showed.
  run_took_up "$wt" wait
  python3 "$LIB/review/pr_context.py" --wait "$wt" "$pr" "$repo" "$REVIEW_WAIT_MAX" || rc=$?
  (( rc == 1 )) && { run_took_up "$wt" red; review_checks_keep "$wt"; }
  # A verdict on a review run (green, red, the head unreviewed): sclaude's tab
  # prints the report by it (review_pane_keys). Not "could not read".
  (( rc <= 3 )) && printf '%s %s %s\n' "$rc" "$(git -C "$wt" rev-parse --short HEAD 2>/dev/null)" "$(date +%s)" \
    > "$(review_checked_file "$wt")" 2>/dev/null
  exit "$rc"
}
