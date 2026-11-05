#!/usr/bin/env bash
#
# Launching a step and moving to the next one: the session, its end, and
# what is checked before the feature goes on.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- launching a step --------------------------------------------------------

# Who is holding the session open. Prints a human-readable "where exactly", or
# nothing if the session is free.
#
# We ask claude itself rather than pgrep. The previous pattern looked for the
# UUID in the command line — and found nothing for a session started without
# arguments: in `ps` it looks simply like "claude", while the UUID lives inside
# the process. Verified: pgrep finds a session started by sclaude (which has
# --session-id in its line) but does not see a neighbouring window opened by
# hand — and "busy" is precisely the case where a human is already sitting in
# the conversation.
#
# With two entrances the cost of the mistake grew: not noticing a holder, the
# orchestrator launches claude over an open session, that exits immediately, and
# the step looks as though it finished instantly.
#
# `claude agents --json` knows both interactive and background sessions and needs
# no terminal — verified under the daemon. Silent on any trouble: no claude, no
# answer, broken JSON — we consider the session free and go on as before. A false
# "busy" is worse than a missed one: it stops the work entirely.
#
# Any id of the conversation counts: Claude Code may have carried it on under a
# new one, which is what it reports, and claude_launch would resume that one
# (session_transcript in state.sh).
#
#   session_holder <session> <dir its transcripts are kept for>
session_holder() {
  local session="$1" ids
  [[ -n "$session" ]] || return 0
  ids="$(python3 "$LIB/cycle/session_end.py" chain "$(transcript_dir "$2")/$session.jsonl" 2>/dev/null \
    | sed 's#.*/##; s#\.jsonl$##')"
  timeout 15 claude agents --json 2>/dev/null | SCLAUDE_SESSION="${ids:-$session}" python3 -c '
import json, os, sys
want = os.environ["SCLAUDE_SESSION"].split()
try:
    agents = json.load(sys.stdin)
except (ValueError, OSError):
    sys.exit(0)
if not isinstance(agents, list):
    sys.exit(0)
for a in agents:
    if not isinstance(a, dict) or a.get("sessionId") not in want:
        continue
    # We name what this session can be found by: for a background one the short
    # id for `claude attach`, for an interactive one the pid of the window it is
    # open in.
    if a.get("id"):
        print("background session %s — claude attach %s" % (a["id"], a["id"]))
    elif a.get("pid"):
        print("pid %s" % a["pid"])
    else:
        print("another window")
    break
' 2>/dev/null || true
}

run_step() {
  # <opening>: what sclaude itself has to tell the session it opens — why an
  # automatic return brought it back, or what the person said is wrong. A
  # parameter rather than a global, so it reaches this session or none: a
  # global left set by a run that opened nothing went to the next session
  # opened, whatever step that was.
  # <kept>: `kept` when review_reopen keeps a new round in the recorded
  # session; counted only if that session is resumed here, for the same
  # reason. A start that stops short (no terminal, the session held in
  # another tab) counts nothing, and the `sclaude <name>` after it resumes
  # the session without the word, so that round goes uncounted: the user's
  # decision of 2026-11-03 — the count is statistics, and a mark kept in the
  # state to cover it counted rounds nobody kept.
  local wt="$1" slug="$2" step="$3" told="${4:-}" kept="${5:-}"
  local state="$wt/.sclaude/local/feature/state.json"
  local model effort mode session prompt pr
  stop_asked "step '$(step_title "$step")'" "$slug" && return 0
  # While a review session works in its own tab, this terminal takes the
  # review's boxes, [s] and [g] (review_pane_keys); the tab wait in
  # claude_launch_once calls it. Set in the launch's own subshell below
  # (pane_keys_for), not here: bash's `local` reaches every function this one
  # calls, and the friction review launched after the session would take the
  # boxes too.

  model="$(step_model "$step")"
  effort="$(step_effort "$step")"
  mode="$(step_mode "$step")"
  [[ "$step" == "review" ]] && capture_reopened_pr "$wt"
  pr="$(state_get "$state" pr || true)"
  local issue; issue="$(state_get "$state" issue || true)"
  # A new feature reaches its first step without naming itself to
  # feature_worktree.
  declare -F term_attach >/dev/null && term_attach "$wt"
  declare -F tab_title >/dev/null && tab_title "$slug"

  # A merged PR closes everything left of the cycle: the work is in main, the
  # review took place, and there is nothing left to check a preview on. There is
  # nothing to ask here — the steps with nothing to do are simply marked as
  # passed.
  #
  # Unless somebody has since said the review did not, in fact, take place.
  # That claim is the one thing this shortcut cannot see. QA now looks before
  # the merge, but a branch can still be merged by hand while QA has it, and
  # features started under the old order (merge, then QA) were merged by the
  # time QA answered. QA hands it back, the cycle is put on `review` — and this
  # line read the merge,
  # concluded there was nothing to do, marked the steps passed again and
  # returned to the production reminder. The rewind was undone in the same
  # breath it was made, and the preview verdict cleared with it.
  #
  # So a step that was deliberately reopened is not closed by a merge. The mark
  # is written by whoever reopened it rather than inferred from the state: an
  # open `review.done` looks the same whether the cycle was sent back or has
  # simply not got there yet, and reading it that way would stop step 3 closing
  # on a merge — which is the case the shortcut exists for.
  #
  # It is cleared when the step closes for real (after_step), so it describes
  # this pass and not the feature.
  local reopened
  reopened="$(state_get "$state" reopened 2>/dev/null || true)"
  # Except a reopening by a preview fix. That fix is green on the preview
  # already, and remind_prod carries it on to QA and the merge in the same run
  # without ever coming back to this step — so after the merge the mark holds
  # nothing, and honouring it opened a review of a merged pull request that
  # after_step then refused to close, waiting for a second pull request nobody
  # needed.
  [[ "$(state_get "$state" reopened_by 2>/dev/null || true)" == "preview" ]] && reopened=""
  if [[ "$reopened" != "$step" ]] && [[ "$step" == "pr" || "$step" == "review" ]]; then
    local branch pr_state
    branch="$(state_get "$state" branch || true)"
    if [[ -n "$branch" ]] && [[ "$(branch_pr_state "$branch")" == "MERGED" ]]; then
      capture_pr "$wt"
      echo ""
      info "The PR for $branch is already merged — nothing left to do in step '$(step_title "$step")'$(
        [[ "$step" == "pr" ]] && printf " or '%s'" "$(step_title review)"
      )."
      step_close_merged "$wt"
      issue_sync "$wt"
      echo "${GREEN}Feature '$slug' has been through every step.${OFF}"
      remind_prod "$wt" "$slug"
      return 0
    fi
  fi

  # A feature with no change of its own has no pull request to open
  # (no_change.sh). after_step ends such a feature as step 2 closes; this is
  # for one whose step 2 closed without that check, before it existed.
  if [[ "$step" == "pr" && ( -z "$pr" || "$pr" == "null" ) ]] && no_change_feature "$wt" >/dev/null; then
    no_change_finish "$wt" "$slug"
    return 0
  fi

  # Entering step 4 invalidates step 2's regression.
  #
  # Without this the gate at the end of the review is a no-op: step 2 closed
  # green, nothing ever clears the verdict, and `regression_gate` short-circuits
  # on `passed` without running anything — which is exactly the case the gate
  # was added for, since step 4 pushes fixes to the branch and the green run was
  # about code that has since changed.
  #
  # Only the local stage, and only here. The deployed stages are about
  # deployments that have not happened yet at this point, and clearing them
  # would throw away a preview verdict that is still true.
  #
  # Unless the verdict names the tree it was about and that tree is still the
  # one here: regression_gate compares them, so a review that changed nothing
  # does not run the suite a second time, and one that changed anything does.
  # A verdict with no tree recorded is cleared as before.
  if [[ "$step" == "review" ]]; then
    local tested; tested="$(state_get "$state" regression.local.tree 2>/dev/null || true)"
    [[ -n "$tested" && "$tested" != "null" ]] \
      || state_set "$state" regression.local.status null
    state_set "$state" regression.local.attempts 0
    # A new round, so its first red is rerun once before a session (the gate).
    state_set "$state" regression.local.orchestrator_fixes 0
  fi

  echo ""
  echo "${BOLD}${BLUE}── $slug · $(phase_title step "$step") ──${OFF}"
  # The topic hears of the step's session once it is opened, below, and of the
  # step itself when it closes: entering it here is often a return to one that
  # goes on. The indented lines under the banner stay here (notices.py).
  # Where to look at it, before anything else: with a server per feature,
  # localhost:3000 is the list of features, and the feature's own address is
  # the one thing a person needs from this header. Through the proxy, the
  # page that lists the feature's users, each a sign-in without a password
  # (users_page in bin/sclaude-proxy): the address alone was said again by
  # the dev server's line below, and landed on a sign-in form.
  local users
  if users="$(dev_users_address "$wt")"; then
    echo "   ${BOLD}Sign in as any user: $users${OFF}"
  else
    echo "   ${BOLD}Open it at $(dev_address "$wt")${OFF}"
  fi
  local map; map="$(flow_address "$wt")" && info "   Where it stands: $map"
  info "   $model / $effort / $mode · $wt"
  # A step whose session is finished, and which waits only on the local
  # regression (after_step marks it, and session_ended on step 2's accept in
  # the session, before the friction review), goes back to its closing check.
  # So does step 1 or 2 closed with [n] or [N] in sclaude's tab
  # (session_take_as_done) and left on the way.
  # Resuming the session instead put the person in front of its old report:
  # the watcher clears the marker on the way in, nothing in the session writes
  # it again, and the conversation stood open until somebody typed /exit.
  # Anything sclaude has to tell the session (<told>) opens it as before.
  #
  # The mark stays, so that a check left on the way (Ctrl-C in step 4's wait
  # for the review, "left open") comes back here next time; a check that
  # sends the step back to its session (step 4's open threads) calls run_step
  # from inside after_step, whose RUN_STEP_IN_GATE makes that one open it.
  # Step 4's fixes from the regression are pushed first, as on the way into a
  # session, so the review reads them; nobody was at a session's end to
  # answer for it.
  if [[ -z "$told" && -z "${RUN_STEP_IN_GATE:-}" \
        && "$(state_get "$state" "steps.$step.gate" 2>/dev/null || true)" == "true" ]]; then
    info "   The session is finished; the step waits only for its closing checks."
    [[ "$step" == "review" ]] && { regression_push_fix "$wt" "${pr:-}" || true; }
    SESSION_AUTO_CLOSED=""; SESSION_EXITED=""
    after_step "$wt" "$slug" "$step" gate
    return 0
  fi
  # Before the server and before the session: merging main in under a running
  # server means changing the code under its feet, and a merge stalled on
  # conflicts leaves a tree on which a session must not be opened at all. A
  # refusal here is the one case where a step does not start.
  sync_branch "$wt" || return 0

  # A review that passed clean has nothing for a session to answer.
  #
  # Decided here — after sync_branch, which can move HEAD, and before the dev
  # server and Chrome, which a step that opens no session has no use for.
  #
  # Only on a first entry, and never on a review that was sent back: QA's
  # return, a red deployed stage or a replan all mark `reopened`, and a return
  # can arrive with no comment at all — a silent hand-back is still a hand-back,
  # and skipping it sent the cycle straight back to QA with nothing changed,
  # round and round. The verdict is checked too, for a return the timer saw
  # before the rewind was written.
  #
  # A review the workflow skipped on purpose ("unreviewed") closes the step too:
  # a session could only say the review did not run. It is said here instead.
  #
  # A project whose review is not GitHub's (project_review_mode) has its pull
  # request labelled so the workflow skips itself; one that reviews on this
  # machine is reviewed here, on the head the session would open on. Findings
  # keep the session; none leave the step to the checks and the comments.
  local review_word="" review_mode="" local_count=""
  if [[ "$step" == "review" ]]; then
    # What a regression's fixing session committed, which it is not told to
    # push, goes to the pull request first: the review reads only what the
    # pull request carries, and with four such commits behind it the review
    # here did not run and the session was told so, for a person to push.
    regression_push_fix "$wt" "${pr:-}" || true
    review_mode="$(project_review_mode "$wt")"
    review_label_sync "$wt" "$pr"
    # Once the person ended the search (review_enough), nothing is reviewed
    # on the way in: what is open goes to the session, and a check of its
    # fixes waits for the person's word (review_close_gate). Unreadable, the
    # pull request's own state decides below.
    if [[ "$review_mode" == "local" && -n "$(review_enough "$wt")" ]]; then
      local_count="$(local_review_count "$wt" "$pr")" || local_count=""
    elif [[ "$review_mode" == "local" ]]; then
      # A pass that runs here — the first of step 4, or the first on a head
      # nobody reviewed yet — is reported before the session opens, to the
      # terminal and the topic, as the gate reports one it runs: the session
      # started on findings whose numbers nobody had been shown. A head the
      # gate reviewed already was reported there.
      local fresh_pass=1
      local_review_done "$wt" && fresh_pass=0
      local_count="$(local_review "$wt" "$pr")" || local_count="failed"
      [[ "$fresh_pass" -eq 1 && "$local_count" =~ ^[1-9][0-9]*$ ]] && review_report "$wt" "$slug"
    fi
  fi
  [[ "$step" == "review" ]] && [[ -z "$local_count" || "$local_count" == "0" ]] \
    && review_skippable "$wt" "$slug" \
    && review_word="$(review_wait_state "$wt" "$slug" "$pr")"
  if [[ "$review_word" == "clean" || "$review_word" == "unreviewed" ]]; then
    state_set "$state" "steps.$step.started" "$(date -Iseconds)"
    if [[ "$review_word" == "clean" ]]; then
      say "${GREEN}✓ The automatic review of PR #$pr passed with no findings, no comments and every check green.${OFF}"
    elif [[ "$review_mode" == "local" ]]; then
      say "${GREEN}✓ The review on this machine found nothing in PR #$pr; every check is green and nobody commented.${OFF}"
    elif [[ "$review_mode" == "off" ]]; then
      warn "  PR #$pr was NOT reviewed: the project's .sclaude/config.json turns the review off."
      info "  Every check is green and nobody commented."
    else
      warn "  PR #$pr was NOT reviewed: the review workflow skipped it (marked not-reviewed)."
      info "  Every check is green and nobody commented."
    fi
    info "  Nothing to answer, so no review session is opened."
    after_step "$wt" "$slug" "$step"
    return 0
  fi
  # Not started without its rules: a session whose policy could not be read
  # would run with none of the product's bans (policy_rules says why on the
  # terminal). Before the dev server and Chrome, which a step that does not
  # start would leave running for nothing.
  local settings
  settings="$(step_settings "$step" "$wt")" \
    || { warn "  The step was not started: sclaude could not read its rules (see above)."; return 1; }
  ensure_dev "$wt"
  ensure_chrome "$wt"
  echo ""

  # We name the session ourselves: a UUID generated in advance survives any way
  # of leaving claude, whereas fishing the id out of ~/.claude/projects after the
  # fact means guessing which of the files was just written.
  session="$(state_get "$state" "steps.$step.session" || true)"

  # A dead id — one whose conversation never took place — is forgotten: an
  # empty one below leads into the first-launch branch by itself, while one that
  # is non-empty and dead prevents starting at all. The boundary is worked out in
  # live_session (state.sh), and so is what it costs.
  if [[ -n "$session" ]] && ! live_session "$wt" "$session" >/dev/null; then
    info "   the session recorded for this step never started — beginning a new one"
    # Its run goes too: left open, with no end, it was counted as running
    # until now — one such run made a 16-minute session read as eight hours
    # in the review's report.
    session_runs "$state" "steps.$step" drop "$session"
    session=""
  fi

  # An open session cannot be opened a second time: claude exits immediately,
  # printing "Resume this session with…". From the outside that is
  # indistinguishable from a step that finished instantly, and the human then
  # answers "finished?" about something that never began. So we check ourselves
  # and name the culprit.
  local holder
  if [[ -n "$session" ]]; then
    holder="$(session_holder "$session" "$wt")"
    if [[ -n "$holder" ]]; then
      warn ""
      warn "  This step's session is already open elsewhere ($holder)."
      warn "  Close it there and try again — or just carry on where it is open."
      return 0
    fi
  fi

  local -a extra; mapfile -t extra <<< "$settings"

  # The local review's findings are threads on the pull request, so they reach
  # the session as the workflow's do: in the snapshot of a fresh one, and as
  # news to a resumed one (review_news). What is counted here is the round —
  # one per reviewed head handed to a session, as the workflow's runs are.
  local local_round=0
  if [[ "$local_count" =~ ^[1-9] ]]; then
    local lhead; lhead="$(local_review_head "$wt")"
    if [[ -z "$session" || "$(state_get "$state" steps.review.local_told 2>/dev/null || true)" != "$lhead" ]]; then
      state_set "$state" steps.review.local_told "$lhead"
      local_round=1
    fi
  elif [[ "$local_count" == "failed" ]]; then
    told="$(printf 'The review on this machine did not run on this head (its log: `%s`): say so in your report, and handle what the pull request itself shows.%s' \
      "$(local_review_file "$wt" .log | sed "s|^$wt/||")" "${told:+$'\n\n'$told}")"
  fi

  # A step's conversation needs a terminal, and without one we stop rather than
  # work around it.
  #
  # This used to launch `claude --bg` instead: the session would connect to
  # Remote Control and the conversation continue in the mobile app. It was
  # written for an entrance nobody uses. Every way the cycle is actually driven
  # gives a terminal — Termius over ssh is a real tty, and so is the terminal
  # inside code-server. Nothing automated starts a step at all: sclaude-watch
  # only polls GitHub and prints `sclaude <slug>` for a human to run, and the
  # Telegram bot is read-only by its own documentation.
  #
  # So a step with no terminal is not a phone, it is a mistake — sclaude invoked
  # by something that was never meant to invoke it: `ssh host sclaude <feature>`
  # without -t, a systemd unit, a cron line, a wrapper reading the output
  # through a pipe. Carrying on there costs more than stopping. The step goes
  # somewhere nobody is watching, after_step is never reached, and with it go
  # the next step and the friction review; the orchestrator returns as though
  # it had done its work.
  #
  # We check openability in a subshell: a bare `: < /dev/tty 2>/dev/null` prints
  # "No such device or address" past the suppression when there is no terminal at
  # all. Around a subshell the redirection covers the open error too. The same
  # device is in pick_start and in ask.
  if ! ( exec < /dev/tty ) 2>/dev/null; then
    warn ""
    warn "  No terminal — this step will not start."
    warn ""
    warn "  A step's conversation needs a tty, and by design every entrance has"
    warn "  one: ssh with a terminal, or the terminal inside code-server."
    warn "  Reaching this means $SELF was invoked by something that cannot give"
    warn "  one — ssh without -t, a systemd unit, cron, or a pipe."
    warn ""
    warn "  Nothing has been started and nothing recorded; the feature stays"
    warn "  where it was. Run it again from a real terminal: $SELF $slug"
    return 1
  fi

  if [[ -n "$session" ]]; then
    # The review may have moved on while the session was closed. What appeared
    # we pass as a prompt: a `--resume` without one opens the conversation
    # silently, and the human would have to retell what is new.
    local news; news="$(review_news "$wt" "$step")"
    # What QA said while nobody was here. The watcher saved it beside the watch
    # file rather than summarising it, so the session gets the comments as they
    # were written — it is answering a person, and a paraphrase of a complaint
    # is a poor thing to answer.
    local qa; qa="$(watch_notes "$slug")"
    if [[ -n "$qa" ]]; then
      news="$(printf '%s\n\n%s\n\n%s\n' "${news:-}" "$(return_brief "$wt" "$issue" "$pr")" "$qa")"
      info "   resuming this step's session — the feature was returned to development"
    elif [[ -n "$news" ]]; then
      info "   resuming this step's session — the PR has moved on since"
    else
      info "   resuming this step's interrupted session"
    fi
    # Whatever there is to tell, and nothing when there is nothing: a silent
    # `--resume` opens the previous conversation and the human carries it on
    # themselves.
    #
    # An opening line used to be invented here when there was no news and the
    # step was going into the background — a session nobody was sitting at
    # would otherwise stand with an "idle — send a prompt to start" mark while
    # the human had been sent to the Claude app. Background steps are refused
    # now, so there is always somebody at the terminal, and a manufactured
    # prompt would only talk over them.
    # What sclaude itself has to tell it goes first.
    local opening="$news"
    [[ -n "$told" ]] && opening="$(printf '%s%s' "$told" "${news:+$'\n\n'$news}")"
    # No marker_gone for step 1, which writes no marker: the plan's approval
    # closes it. A review on this machine writes no review-round (review.md).
    if [[ -n "$opening" && "$step" != "plan" ]]; then
      local gone=(.sclaude/local/feature/session-done)
      [[ "$step" == "review" && "$review_mode" != "local" ]] && gone+=(.sclaude/local/feature/review-round)
      opening="$(printf '%s\n\n%s' "$opening" "$(marker_gone "${gone[@]}")")"
    fi
    RUN_STEP_LAUNCHED=1
    state_set "$state" "steps.$step.gate" null
    step_run "$wt" "$step" open "$session"
    local brief; brief="$(review_brief "$wt" "$step" resumed)"
    # Where this round begins, for the account the session's end gives.
    [[ "$step" == "review" ]] && review_round_begins "$wt"
    ask_feed say "$(phase_line resumed step "$step" "$(step_session_number "$state" "$step" "$session")")${brief:+ · $brief}${qa:+ · returned by QA}"
    # A round review_reopen kept in this session counts here, as on the round
    # marker's path: the session's next row in review-context.log says which
    # of its rounds it ends (segment in review_stats.py), and in Actions the
    # issue's row how many it worked. A local review's row counts reviewed
    # heads handed to the session instead (run_local_round below): a new
    # thread from a person, with no pass on a new head, adds none there.
    if [[ "$step" == "review" && "$kept" == "kept" ]]; then
      local kept_rounds; kept_rounds="$(state_get "$state" steps.review.rounds 2>/dev/null || true)"
      [[ "$kept_rounds" =~ ^[0-9]+$ ]] || kept_rounds=0
      kept_rounds=$((kept_rounds + 1))
      state_set "$state" steps.review.rounds "$kept_rounds"
      [[ "$review_mode" == "local" ]] || run_rounds "$wt" "$session" "$((kept_rounds + 1))"
    fi
    [[ "$step" == "review" ]] && run_comments "$wt" "$session" "$pr"
    [[ "$local_round" -eq 1 ]] && run_local_round "$wt" "$session"
    # The issue hears of it too, as on the fresh path below. A review session
    # that carries on into its next round comes back through here, its row now
    # counting the findings that round brought; without this the issue kept the
    # first round's count until the session finally ended.
    issue_sync "$wt"
    session_watch_start "$wt" "$session" "" "" "$step"
    ( cd "$wt" && dev_env_load "$wt" && pane_keys_for "$step" "$wt" && session_git_env "$session" && claude_launch --resume "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$(session_label step "$state" "$step" "$session")/$slug" ${opening:+"$opening"} )
    session_watch_stop
  else
    session="$(new_session_id)"
    state_set "$state" "steps.$step.session" "$session"
    # The step's start, for the summary in the issue. We write it only for a new
    # session: for a resumed one the step began then, not now.
    state_set "$state" "steps.$step.started" "$(date -Iseconds)"
    # The rounds a review session closed are counted per session (see
    # review_context_log).
    [[ "$step" == "review" ]] && state_set "$state" "steps.$step.rounds" null
    step_run "$wt" "$step" open "$session"
    [[ "$step" == "review" ]] && run_comments "$wt" "$session" "$pr"
    [[ "$step" == "review" ]] && run_rounds "$wt" "$session" 1
    prompt="$(render_prompt "$step" "$slug" "$pr" "$issue" "$wt")"
    # QA's comments reach a fresh session too. They used to be read only on the
    # resume path, so a hand-back that arrived after the recorded session had
    # gone — the transcript cleaned up, the step closed days ago — was appended
    # to a prompt nobody built and then filed away by watch_seen at the end of
    # this same function: consumed without ever having been shown. A hand-back
    # arriving late is precisely when the transcript is most likely to be gone.
    local qa_fresh; qa_fresh="$(watch_notes "$slug")"
    # A return with nothing collected is still a return — the card moved with
    # no comment, or the reason is on a line the copy missed — and the session
    # must hear that it was sent back, or it opens on an empty list of review
    # comments and calls the step done.
    if [[ -n "$qa_fresh" ]]; then
      prompt="$(printf '%s\n\n%s\n\n%s\n' "$prompt" "$(return_brief "$wt" "$issue" "$pr")" "$qa_fresh")"
    elif [[ "$step" == "review" \
            && "$(state_get "$state" reopened_by 2>/dev/null || true)" == "returned" ]]; then
      prompt="$(printf '%s\n\n%s\n' "$prompt" "$(return_brief "$wt" "$issue" "$pr")")"
    fi
    # We update the summary here rather than only at transitions: the session's
    # id is known right now, and the step will live for hours. Otherwise a dash
    # stands on the "in progress" line in the issue all that time — and there is
    # nothing to return to a running step from another machine
    # (`claude --resume`) by.
    # Told something by sclaude — a session that could not be resumed is
    # opened afresh, and what was meant for it still reaches it.
    [[ -n "$told" ]] && prompt="$(printf '%s\n\n%s\n' "$prompt" "$told")"
    # After the QA notes are read: whether QA sent it back goes on the line.
    local brief returned=""
    brief="$(review_brief "$wt" "$step")"
    [[ "$step" == "review" ]] && { review_round_ends "$wt"; review_round_begins "$wt"; }
    if [[ -n "$qa_fresh" ]] || [[ "$step" == "review" \
          && "$(state_get "$state" reopened_by 2>/dev/null || true)" == "returned" ]]; then
      returned=" · returned by QA"
    fi
    ask_feed say "$(phase_line started step "$step" "$(step_session_number "$state" "$step" "$session")")${brief:+ · $brief}$returned"
    RUN_STEP_LAUNCHED=1
    state_set "$state" "steps.$step.gate" null
    issue_sync "$wt"
    session_watch_start "$wt" "$session" "" "" "$step"
    ( cd "$wt" && dev_env_load "$wt" && pane_keys_for "$step" "$wt" && session_git_env "$session" && claude_launch --session-id "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$(session_label step "$state" "$step" "$session")/$slug" "$prompt" )
    session_watch_stop
  fi

  # The session may have run for hours, and sclaude may have changed under it:
  # what follows is then done by the new code rather than by what this process
  # loaded at its start. See code_reload.
  code_reload "$slug" "$step" "$session"
  session_ended "$wt" "$slug" "$step" "$session"
}

# What happens once a step's claude has exited: the round's rotation, the
# step's record, and the way on. Split out of run_step so that a process whose
# code went stale while the session ran can hand exactly this part to a fresh
# one (`sclaude _session-ended`).
session_ended() {
  local wt="$1" slug="$2" step="$3" session="$4"
  local state="$wt/.sclaude/local/feature/state.json"
  # after_step reads these as run_step's; after code_reload there is no
  # run_step above, and `set -u` stops on the first of them.
  local pr issue
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  issue="$(state_get "$state" issue 2>/dev/null || true)"
  # What the review handed this session over all its rounds, before its row
  # is written for the last time.
  [[ "$step" == "review" ]] && run_comments "$wt" "$session" "$pr"
  # And what this launch of it cost, for the review report.
  [[ "$step" == "review" ]] && run_cost "$wt" "$session"

  # A session that never got going did not work — it refused to start. Asking
  # "is the step finished?" after that means offering to close a step that never
  # was.
  #
  # By the transcript rather than by the clock: see session_started. The clock
  # timed the wrapper and let a stillborn session through whenever the launch
  # itself took longer than the threshold.
  if ! session_started "$wt" "$session"; then
    # The topic heard it started: it hears this end, numbered while the run
    # is still there to number it.
    ask_feed say "$(phase_line ended step "$step" "$(step_session_number "$state" "$step" "$session")") · claude exited at once, see the terminal"
    step_run "$wt" "$step" drop "$session"
    warn ""
    warn "  claude exited immediately — the step never started."
    # Run in a tab, it printed there, and the tab went with it: what is
    # "above" here is sclaude's own output. The tab's log kept the rest.
    local tab_end=""
    pane_marked "$session" && tab_end="$(pane_last_exit "$wt")"
    if [[ -n "$tab_end" ]]; then
      local code="${tab_end%%$'\n'*}" line
      case "$code" in
        130|143) warn "  Its tab ended it (exit $code): Ctrl-C there, or the tab was closed." ;;
        0)       warn "  It exited on its own (exit 0) before the session began." ;;
        *)       warn "  It exited with code $code." ;;
      esac
      if [[ "$tab_end" == *$'\n'* ]]; then
        info "  What it wrote:"
        while IFS= read -r line; do info "    $line"; done <<<"${tab_end#*$'\n'}"
      fi
      info "  The tab's log: $PANE_LOG. The step stays where it was."
    else
      warn "  See what it printed above; the step stays where it was."
    fi
    return 0
  fi
  # The person's word from sclaude's tab, if they gave one (session_keys in
  # pane.sh). Forward ([n], [N]) is acted on below, once the watcher's marker
  # has made it a session sclaude closed. Again, later ([R]) closed it as
  # /exit would, so a marker it wrote meanwhile is not acted on: the
  # person's word came after it.
  local said_key taken_at=""
  said_key="$(session_ctl_take "$session")"
  [[ "$said_key" == later ]] && rm -f "$(done_marker "$wt")" "$(round_marker "$wt")"
  # When the key closed it: the marker the watcher wrote then (capture_plan).
  # To the fraction of a second: the plan's call may be written in the same
  # second, just before.
  [[ "$said_key" == next* ]] && taken_at="$(stat -c %.Y "$(done_marker "$wt")" 2>/dev/null || true)"
  # The review round is over: the automatic review closed every finding this
  # session fixed, and posted new ones. While its context is light and still
  # cached the same session takes them; otherwise they go to a session of
  # their own, with none of this one's context (review_keep). That session's
  # row in the issue says why this one ended; the next one is a row of its
  # own. See round_marker.
  if [[ "$step" == "review" && -s "$(round_marker "$wt")" ]]; then
    local round_note; round_note="$(head -c 300 "$(round_marker "$wt")")"
    rm -f "$(round_marker "$wt")"
    # The terminal may have been left mid-redraw by the signal.
    stty sane 2>/dev/null || true
    session_report "$wt" "$session"
    plan_report "$wt" "$step"
    local rounds; rounds="$(state_get "$state" "steps.$step.rounds" 2>/dev/null || true)"
    [[ "$rounds" =~ ^[0-9]+$ ]] || rounds=0
    rounds=$((rounds + 1))
    # The topic hears of the round as of a fix session's end, with what it
    # left; the terminal keeps its own words for it below.
    local tally; tally="$(review_tally "$wt" "$step")"
    review_round_ends "$wt"
    ask_feed say "$(phase_line finished step "$step" "$(step_session_number "$state" "$step" "$session")" "$rounds")${tally:+ · $tally}"
    local held pct why
    held="$(review_context "$wt" "$session")"
    pct="$(awk '{print $3}' <<<"$held")"
    if why="$(review_keep "$wt" "$session" "$held")"; then
      state_set "$state" "steps.$step.rounds" "$rounds"
      # The round it now starts counts too; run_step writes it to the issue.
      run_rounds "$wt" "$session" "$((rounds + 1))"
      review_context_log "$wt" "$slug" "$session" "carried on" "$held" "$rounds"
      echo ""
      say_here "${BOLD}Review round closed: the automatic review confirmed every fix this session made.${OFF}"
      [[ -n "$round_note" ]] && info "  $round_note"
      info "  Its context is at ${pct}% (under ${REVIEW_CONTEXT_MAX_PCT}%) and $why: the same session takes the new findings."
      review_yours_report "$wt" "$pr" || true
      review_report "$wt" "$slug"
      run_step "$wt" "$slug" "$step" "$(review_carry_on "$pct")"
      return 0
    fi
    review_context_log "$wt" "$slug" "$session" "fresh session" "$held" "$rounds"
    state_set "$state" "steps.$step.rounds" null
    # Every round it worked was closed, the last one included.
    run_rounds "$wt" "$session" "$rounds"
    step_run "$wt" "$step" end "$session" "fixes confirmed"
    local round_key; round_key="$(step_run_key "$state" "$step" "$session")"
    state_set "$state" "steps.$step.session" null
    watch_seen "$slug"
    issue_sync "$wt"
    echo ""
    say_here "${BOLD}Review round closed: the automatic review confirmed every fix this session made.${OFF}"
    [[ -n "$round_note" ]] && info "  $round_note"
    info "  The new findings go to a fresh session, without this one's context: $why."
    review_yours_report "$wt" "$pr" || true
    review_report "$wt" "$slug"
    if ! run_friction "$wt" "$slug" "$round_key"; then
      info "  The next round waits for it: $SELF $slug"
      return 0
    fi
    run_step "$wt" "$slug" "$step"
    return 0
  fi
  # The session said it was done and the watcher closed it: its report is
  # printed here, since claude's screen went with it, and the gates after it
  # act on what they find without asking — the person did not type /exit, so
  # nobody is at the session's end to answer. See done_marker. Step 4's gate
  # goes back to a session unasked either way, unless the person left the
  # session with [g] off (SESSION_EXITED below, review_close_gate).
  SESSION_AUTO_CLOSED=""
  session_closed "$(done_marker "$wt")" "$wt" "$session" "" "$(review_tally "$wt" "$step")" \
    step "$step" "$(step_session_number "$state" "$step" "$session")" \
    && SESSION_AUTO_CLOSED=1
  # Left by the person — /exit, or Ctrl-C in sclaude's tab — with no key of
  # sclaude's tab said: step 4's gate holds the rounds there (review_close_gate).
  SESSION_EXITED=""
  [[ -z "$SESSION_AUTO_CLOSED" && -z "$said_key" ]] && SESSION_EXITED=1
  [[ "$step" == "review" && -n "$SESSION_AUTO_CLOSED" ]] && review_round_ends "$wt"
  # Step 2 asks its question in its own dialog (code_accepted). A yes there
  # finishes the session as the terminal's yes does: the step waits for the
  # regression alone (`steps.code.gate`), so after_step asks nothing, and a
  # start after an interruption on the way — the friction review cut off, a
  # Ctrl-C — goes to the regression rather than back into this session.
  # after_step writes the criteria: before reading the yes on a pass that is
  # not back at the gate, and on every pass before the step closes.
  if [[ "$step" == "code" && -n "$SESSION_AUTO_CLOSED" ]] && code_accepted "$wt" "$session"; then
    state_set "$state" "steps.$step.gate" true
  fi
  # [n] or [N] in sclaude's tab is the same yes, and for step 1 the approval
  # of the plan on screen: after_step then goes on without asking.
  if [[ "$said_key" == next* && -n "$SESSION_AUTO_CLOSED" ]]; then
    session_take_as_done "$wt" "$step" "$taken_at" || true
  fi
  # Left by the person in a tab of its own: the tab closed with its last
  # message, which is often the one that says what is left — once a review
  # session's account of what it resolved and what it waits for went with it.
  if pane_marked "$session" && [[ -z "$SESSION_AUTO_CLOSED" ]]; then
    session_report "$wt" "$session"
  fi
  plan_report "$wt" "$step"
  [[ "$step" == "review" ]] && { review_yours_report "$wt" "$pr" || true; }
  [[ "$step" == "review" ]] && review_report "$wt" "$slug"
  if [[ "$step" == "review" ]]; then
    local closed_rounds; closed_rounds="$(state_get "$state" "steps.$step.rounds" 2>/dev/null || true)"
    [[ "$closed_rounds" =~ ^[0-9]+$ ]] || closed_rounds=0
    review_context_log "$wt" "$slug" "$session" "$([[ -n "$SESSION_AUTO_CLOSED" ]] && echo done || echo exit)" \
      "$(review_context "$wt" "$session")" "$closed_rounds"
  fi
  # A session that wrote its marker ended its own work, and its row in the
  # issue says so: without a reason an earlier row reads "interrupted", as it
  # did for every review session the review on this machine sent back to.
  step_run "$wt" "$step" end "$session" "${SESSION_AUTO_CLOSED:+finished}"

  # The friction review follows every session, not every step.
  #
  # It used to run once the step closed, on the reasoning that the fix is
  # needed by the step about to start. The reasoning holds, one level down: the
  # next thing to start is the next session, and that is often the same step's.
  # The review step rotates a session per round of the automatic review — one pull
  # request ran seven — so a ban the first round hit could be met by every round after
  # it and still be reviewed only once, at the end. A session that leaves the
  # step open (a "no" to the question, an unmerged review) used to carry its
  # entries into the next one with nobody reading them.
  #
  # Before after_step rather than after it: after_step leads into the next step
  # and does not come back, and on the last step it leads to remind_prod, whose
  # cmd_done removes the tree with .sclaude/local/feature/ and an unread log in it. Closing a
  # step after this adds no review of its own — its last session has just had
  # one.
  #
  # If the review did not take place — a limit, a closed terminal — we stop
  # here, as between steps before: the session is recorded, and
  # `sclaude <feature>` returns to the review first (cmd_resume).
  if ! run_friction "$wt" "$slug" "$(step_run_key "$state" "$step" "$session")"; then
    info "  The feature waits for it: $SELF $slug"
    return 0
  fi

  # The QA hand-back has been delivered: the session above was given it as its
  # opening prompt. Clearing it here, before after_step, rather than after:
  # after_step leads into the next step and does not come back, so anything
  # below it would run only when the whole remaining cycle has unwound.
  #
  # Left uncleared, the same comments were prepended to every later resume of
  # this feature — and, worse, suppressed the accurate `review_news` message,
  # because the QA branch is tested first. The session kept being told to
  # address complaints it had already addressed.
  watch_seen "$slug"

  # [R]: everything a person's /exit is followed by has run, the friction
  # review included; the step's checks are not, and the step stays.
  if [[ "$said_key" == later ]]; then
    echo ""
    say_here "${BOLD}Closed at your word ([R]): the step stays where it is.${OFF}"
    info "  Come back with: $SELF $slug — it opens this conversation again."
    return 0
  fi

  after_step "$wt" "$slug" "$step"
}

# What [n] and [N] in sclaude's tab take as said for a step's session
# (session_keys in pane.sh), beside the marker the watcher writes: the
# answers that end steps 1 and 2 in the session itself — the plan on screen
# approved, step 2's work accepted. Marked as the step's gate, which
# after_step reads as that yes; step 1's plan is read back now, its call still
# unanswered in the transcript (capture_plan reads the gate). With no plan
# presented there is nothing to take, and it returns 1: after_step then sends
# the session back to present one, as after any end without a plan. Steps 3
# and 4 end on their marker alone.
#
#   session_take_as_done <wt> <step> [<seconds it was closed at>]
session_take_as_done() {
  local wt="$1" step="$2" taken_at="${3:-}" state="$1/.sclaude/local/feature/state.json"
  case "$step" in
    plan)
      state_set "$state" "steps.$step.gate" true
      state_set "$state" "steps.$step.taken_at" "${taken_at:-null}"
      if ! capture_plan "$wt"; then
        state_set "$state" "steps.$step.gate" null
        warn "  No plan was presented in the session, so there is none to take as approved."
        return 1
      fi ;;
    code)
      state_set "$state" "steps.$step.gate" true
      # Written as the session ends, as on a yes in the session (after_step).
      extend_acceptance "$wt" ;;
  esac
  return 0
}

# Leaving a session means nothing in itself — a step is closed by its result
# rather than by a process that has ended. While there is no result, launching
# again returns to the same step with the same context.
#
# We ask only where the result cannot be looked at. Three steps out of four leave
# a checkable trace, and each has its own:
#
#   plan   — the approved plan, which is .sclaude/local/feature/plan.md. It is approved in the
#            session itself, in a dialogue where the plan is visible whole;
#            asking the same thing a second time, when the plan is no longer
#            before one's eyes, means teaching people to hit Enter without
#            looking.
#   pr     — the PR that was opened. gh shows it, and step 4 needs its number
#            anyway.
#   review — a merged PR. The review ended not when the window closed but when
#            the work travelled into main.
#
# That leaves `code`: "the code is ready" is a judgement, it leaves no trace in
# the world, and only a human can close the step.
#
# A question whose answer is already known is not insurance but a habit of
# answering without looking. Should a human get it wrong, the feature travels to
# a review of a PR that does not exist. Changing one's mind after an automatic
# close is possible: `sclaude replan <feature>` returns the feature to step 1.
after_step() {
  # <gate_only>: "gate" when run_step comes straight back to the closing
  # check of a step whose session is already finished (`steps.<step>.gate`).
  local wt="$1" slug="$2" step="$3" gate_only="${4:-}"
  local state="$wt/.sclaude/local/feature/state.json" next answer
  # A run_step called from the checks below (step 4's open threads) is sent
  # to the session, and must open it rather than take run_step's way back to
  # these checks on `steps.<step>.gate`.
  # Local, so it ends with this call however it returns.
  local RUN_STEP_IN_GATE=1

  echo ""
  case "$step" in
    plan)
      if ! capture_plan "$wt"; then
        # Back to the session next time, not to this check: a gate marked by
        # [n] or [N] (session_take_as_done) found nothing to close on.
        state_set "$state" "steps.$step.gate" null
        warn "  No approved plan in this session — the step is not finished."
        auto_return "$wt" "$slug" "$step" \
          "**sclaude could not read the approved plan's text**, so step 1 is not finished: the plan was approved, but the text behind it was not kept. Present the plan for approval again, in full." \
          && return 0
        info "  Approve the plan in the session (it is shown for review), then leave."
        info "  Come back with: $SELF $slug"
        return 0
      fi
      info "  Plan saved to .sclaude/local/feature/plan.md — it is what step 2 starts from."
      sync_acceptance "$wt" "$slug"
      ;;
    pr)
      # capture_pr asks gh for the number and puts it into the state — and it
      # is the check as well: the number appeared there, so there is a PR.
      # capture_pr itself says nothing about either a missing PR or a missing
      # network, so we look at the state.
      local number
      capture_pr "$wt"
      number="$(state_get "$state" pr || true)"
      # Reopened after a merge, the branch still answers with the merged pull
      # request until the new one is open, and that number is not this step done.
      local seen; seen="$(state_get "$state" reopened_pr 2>/dev/null || true)"
      [[ -n "$seen" && "$seen" != "null" && "$number" == "$seen" ]] && number=""
      if [[ -z "$number" || "$number" == "null" ]]; then
        warn "  No pull request for this branch yet — the step is not finished."
        auto_return "$wt" "$slug" "$step" \
          "**sclaude found no pull request for this branch**, so step 3 is not finished. Open it, then finish as the prompt says." \
          && return 0
        info "  Open it in the session, then leave."
        info "  Come back with: $SELF $slug"
        return 0
      fi
      # The pull request is what the automatic review reads. A commit left
      # unpushed is one step 4 starts without and the review never sees.
      local unpushed
      unpushed="$(python3 "$LIB/review/pr_context.py" --unpushed "$wt" "$number" 2>/dev/null || true)"
      if [[ "$unpushed" =~ ^[1-9][0-9]*$ ]]; then
        warn "  $unpushed commit(s) here are not on GitHub — PR #$number does not carry them."
        auto_return "$wt" "$slug" "$step" \
          "**$unpushed commit(s) on this branch are not pushed**, so PR #$number does not carry them. Push the branch, then finish as the prompt says." \
          && return 0
        info "  Push it in the session, then leave."
        info "  Come back with: $SELF $slug"
        return 0
      fi
      ;;
    review)
      # A reopened feature's session opened its new pull request just now:
      # everything below — the gate, the push, the close — is about that one.
      capture_reopened_pr "$wt"
      pr="$(state_get "$state" pr 2>/dev/null || true)"
      # Leaving the session is not the review being done. Once a third round's
      # session exited while the automatic review of its push was still
      # running, and that review then opened six new threads: closing here
      # would have sent the feature to QA with them. So the step closes only
      # once the review has finished with the pushed head and left nothing
      # open — or when the human says to close it anyway.
      if ! review_close_gate "$wt" "$slug" "${pr:-}"; then
        return 0
      fi
      # The release candidate's own gate. Step 4 pushes fixes to the branch,
      # and between the last of them and the merge nothing ran the suite: the
      # regression from step 2 was green about code that has since changed.
      #
      # Red here keeps the step open: the preview QA will look at is built from
      # this tree, and handing QA a branch the suite already fails on wastes
      # the one check only a person can make.
      #
      # Not for a change nothing deploys (no_change.sh): there is no preview
      # for QA, and the suite would test main's product.
      if no_deploy_feature "$wt"; then
        no_deploy_say "No local regression before the merge."
      else
        # Marked as step 2's is, and for the same hang (run_step).
        state_set "$state" "steps.$step.gate" true
        if ! regression_gate "$wt" "$slug" local; then
          [[ -n "${REGRESSION_TAKEN_OVER:-}" ]] && state_set "$state" "steps.$step.gate" null
          info "  The review waits for a green regression: $SELF $slug"
          return 0
        fi
      fi
      # A red run above opens a fixing session, which commits its fix and is
      # not told to push (a step's next session pushes it on the way in, in
      # run_step, but the step may close right here). review_close_gate has
      # already asked whether the pull request carries every commit, so
      # nothing asked again: once
      # the fix went green here, the preview was deployed from this tree with
      # it, QA accepted that preview — and the pull request merged without it.
      # So it is pushed now, and the review reads it like any other push.
      local fix_pushed=0
      regression_push_fix "$wt" "${pr:-}" || fix_pushed=$?
      # A refused push goes to the session, told why: a passing blip it just
      # pushes again, a pre-push hook or a branch moved on GitHub it fixes,
      # and a worktree left on main or detached it puts back on the branch.
      # Back to it by itself after a session that closed itself (at most
      # AUTO_RETURNS), straight away on run_step's way back; after a /exit
      # the next start opens it, the mark gone.
      if [[ "$fix_pushed" -eq 2 ]]; then
        state_set "$state" "steps.$step.gate" null
        # Empty, not an error, on a detached HEAD.
        local here; here="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
        local unpushed="**The regression's fix could not be pushed to PR #${pr:-?}.** sclaude's push was refused, or the worktree is not on the feature's branch (${here:-a detached HEAD} now). Get the commits onto the pull request — push them, fix what refused the push (a pre-push hook, a branch that moved on GitHub), or bring them onto the feature's branch — then finish as the prompt says."
        auto_return "$wt" "$slug" "$step" "$unpushed" && return 0
        if [[ "$gate_only" == "gate" ]]; then
          run_step "$wt" "$slug" "$step" "$unpushed"
          return 0
        fi
        info "  The review waits for the fix to reach PR #${pr:-?}: $SELF $slug"
        return 0
      fi
      if [[ "$fix_pushed" -eq 0 ]] && ! review_close_gate "$wt" "$slug" "${pr:-}"; then
        return 0
      fi
      local branch; branch="$(state_get "$state" branch || true)"
      # The review closes here and the pull request stays open.
      #
      # This used to wait for the merge, and that put the whole back half of the
      # cycle in the wrong order: the preview, its regression, "In QA" and the
      # QA watch all live in remind_prod, which runs only once this step has
      # closed — so the branch was merged first and QA looked at main
      # afterwards, when their verdict could no longer hold anything back.
      # One feature showed it plainly: the review step closed in the same
      # second its pull request was merged, and the preview was deployed after both.
      #
      # The order now is review → preview → QA → merge. The waits for QA and
      # for the merge are in remind_prod (qa_wait, merge_wait), after the
      # deployment QA is meant to look at exists.
      #
      # One merged case is still refused: after a hand-back from a feature that
      # was merged before QA saw it (the old order), the branch's pull request
      # is still that merged one. `reopened_pr` records the number QA saw, and a
      # merged pull request cannot be reopened, so the fix needs a new one before
      # this step may close. A pull request that is still open takes the fix
      # itself, and closes the step as any other would.
      #
      # capture_pr has already run for this step, so `pr` is whatever the branch
      # carries now rather than what the state remembered.
      # The fix must stay on the branch the state names. Every later question
      # — which pull request, is it merged, what the preview deploys — is
      # asked of that name, and a fix on another branch leaves the old one
      # answering MERGED: the review would close on it, the preview and QA be
      # skipped as already merged, and production ship main without the fix.
      local on_branch; on_branch="$(git -C "$wt" branch --show-current 2>/dev/null || true)"
      if [[ -n "$branch" && -n "$on_branch" && "$on_branch" != "$branch" ]]; then
        echo ""
        warn "  The worktree is on $on_branch, and this feature is $branch."
        info "  sclaude follows the feature by its branch, so the fix has to be on it:"
        info "  switch back, merge $on_branch into it (or cherry-pick the fix), push,"
        info "  and open the pull request from $branch."
        info "  Come back with: $SELF $slug"
        # Its session's work, not these checks' again (run_step's way back).
        state_set "$state" "steps.$step.gate" null
        return 0
      fi

      local seen_pr; seen_pr="$(state_get "$state" reopened_pr 2>/dev/null || true)"
      local now_pr; now_pr="$(state_get "$state" pr 2>/dev/null || true)"
      local pr_state=""
      [[ -n "$branch" ]] && pr_state="$(branch_pr_state "$branch")"
      if [[ -n "$seen_pr" && "$seen_pr" != "null" && "$seen_pr" == "$now_pr" \
            && "$pr_state" == "MERGED" ]]; then
        echo ""
        case "$(state_get "$state" reopened_by 2>/dev/null || true)" in
          prod) if [[ "$(state_get "$state" regression.prod.deploy_failed 2>/dev/null || true)" =~ ^(null)?$ ]]; then
                  warn "  This is still the pull request production was rolled back from (#$seen_pr)."
                else
                  warn "  This is still the pull request whose ship to production failed (#$seen_pr)."
                fi ;;
          returned|qa) warn "  This is still the pull request the feature was returned on (#$seen_pr)." ;;
          *)    warn "  This is still the merged pull request the review was reopened on (#$seen_pr)." ;;
        esac
        info "  A merged pull request cannot be reopened, so the fix needs one of"
        info "  its own; the review stays open until the branch carries it."
        info "  Come back with: $SELF $slug"
        # The session opens the new pull request: it is where the next start goes.
        state_set "$state" "steps.$step.gate" null
        return 0
      fi

      # Before QA reads the criteria: a merged pull request has had its QA.
      if [[ "$pr_state" != "MERGED" ]]; then
        extend_acceptance "$wt" reworded
        reword_acceptance "$wt"
      fi
      if [[ "$pr_state" == "MERGED" ]]; then
        info "  PR #${pr:-?} is merged — the review is done."
      elif no_deploy_feature "$wt"; then
        info "  Review closed. Next: the merge of PR #${pr:-?}, with no preview, QA or production."
      else
        # Which ticket QA will work in, beside which pull request. state_get
        # answers a missing issue with the string "null", and "issue #null" is
        # worse than saying nothing.
        local next_issue="$issue"
        [[ "$next_issue" == "null" ]] && next_issue=""
        info "  Review closed — PR #${pr:-?} stays open until QA has accepted the feature."
        info "  Next: the preview, then QA${next_issue:+ on issue #$next_issue}, then the merge."
      fi
      ;;
    *)
      # Criteria the session agreed with the human mid-step are in the plan
      # only; QA ticks in the issue. Written as the session ends — before the
      # question, or on an accept in the session — so that the list does not
      # wait for the person or the regression; and again before the step
      # closes, since step 3 copies the issue's list into the pull request:
      # that one catches a write cut off or refused, a pass back at the gate,
      # and criteria a fixing session added. It writes only what the issue
      # lacks, and leaves rewordings to the first write and to step 4. Never a hold: a write GitHub
      # refuses is warned about, and the plan keeps the list (sync_acceptance).
      # Once the person has said yes about this session's work there is
      # nothing to ask again: back at the gate (run_step, `steps.code.gate`),
      # or straight from session_ended when they accepted it in the session
      # itself, through the question code.md ends on (code_accepted, which
      # sets the same gate). Without it — the session left with /exit, a
      # proposal still open — the question is asked here, as before.
      [[ "$gate_only" == "gate" ]] || extend_acceptance "$wt"
      if [[ "$gate_only" == "gate" ]]; then
        answer=y
      elif [[ "$(state_get "$state" "steps.$step.gate" 2>/dev/null || true)" == "true" ]]; then
        answer=y
        info "  You accepted the work: in the session, or with [n] in this terminal."
      else
        ask "${BOLD}Please check everything yourself after AI. Do you confirm that everything works as it should? [y/n] ${OFF}" answer yn
      fi
      if ! is_yes "$answer"; then
        # Back to the same session, which knows what it built: a person is in
        # the loop, so there is no limit on how often. What they say is wrong
        # becomes its first message, rather than opening on an empty prompt.
        local wrong=""
        ask "${BOLD}What is not working? It goes back to the session as your message (Enter to leave the step for later): ${OFF}" wrong || true
        if [[ -z "$wrong" ]]; then
          info "The step stays current. Come back with: $SELF $slug"
          return 0
        fi
        info "  Back to the development session."
        run_step "$wt" "$slug" "$step" "**The person checked the work and it does not work yet:** $wrong"
        return 0
      fi
      # The human's word says the work is done; the regression says whether it
      # works. This is the trace in the world that `code` was missing — the
      # other three steps have one, and until now this step closed on a
      # judgement alone.
      #
      # After the question rather than before it: a run takes minutes, and
      # spending them on a step the human was not claiming to have finished is
      # how a gate teaches people to dread the question. The gate opens a
      # fixing session itself when the run is red, so there is nothing to say
      # here beyond where the feature now waits.
      #
      # Unless the feature changed nothing of its own: then there is nothing
      # for the suite, the pull request or a deployment to be about, and the
      # cycle ends here (no_change.sh).
      #
      # And no regression for a change nothing deploys (no_change.sh): the
      # suite would test main's product, which this branch does not touch.
      if no_change_feature "$wt" >/dev/null; then
        no_change_finish "$wt" "$slug" code
        return 0
      fi
      if no_deploy_feature "$wt"; then
        no_deploy_say "No local regression: the pull request and its review come next."
      else
        # The session is finished and the person has confirmed it: from here
        # the step waits on the regression alone. Marked before the run, so
        # that a red one, or a Ctrl-C in it, brings the next `sclaude
        # <feature>` back here rather than into the finished session (see
        # run_step).
        state_set "$state" "steps.$step.gate" true
        if ! regression_gate "$wt" "$slug" local; then
          # Out of fixing sessions, and the person said they would take it on:
          # the next start opens the step's session for them, not the suite.
          [[ -n "${REGRESSION_TAKEN_OVER:-}" ]] && state_set "$state" "steps.$step.gate" null
          info "  The step waits for a green regression: $SELF $slug"
          return 0
        fi
      fi
      # `reworded`: a criterion worded otherwise in the issue was reported by
      # the write above, and step 4 asks about it (reword_acceptance).
      extend_acceptance "$wt" reworded
      ;;
  esac

  step_run "$wt" "$step" close
  ask_feed say "$(phase_line done step "$step")"
  # The automatic returns are counted per closing of a step: a step that
  # closed has used none of them on its next run.
  state_set "$state" "steps.$step.auto_returns" null 2>/dev/null || true
  state_set "$state" "steps.$step.gate" null 2>/dev/null || true
  state_set "$state" "steps.$step.done" true
  state_set "$state" "steps.$step.finished" "$(date -Iseconds)"
  # The person's "enough" was about this round of step 4: a review the
  # feature is sent back to starts without it.
  if [[ "$step" == "review" ]]; then
    state_set "$state" steps.review.enough null
    # [g] is the person's for the whole review; its rounds count afresh.
    state_set "$state" steps.review.go_on_rounds null
    state_set "$state" steps.review.go_on_ceiling null
    review_said_drop
  fi
  # The step closed for real, so it is no longer a reopened one. The mark
  # describes a pass rather than the feature: left behind, it would keep a
  # merged PR from ever closing this step again.
  state_set "$state" reopened null 2>/dev/null || true
  state_set "$state" reopened_pr null 2>/dev/null || true
  state_set "$state" reopened_by null 2>/dev/null || true

  if ! next="$(step_next "$step")"; then
    state_set "$state" step "done"
    issue_sync "$wt"
    echo ""
    echo "${GREEN}Feature '$slug' has been through every step.${OFF}"
    remind_prod "$wt" "$slug"
    return 0
  fi

  state_set "$state" step "$next"

  # The PR's number is already in the state: capture_pr wrote it when closing
  # step 3 — step 4 needs it to read the comments. So the summary goes into the
  # issue with the number rather than without it.
  issue_sync "$wt"

  # There is no "shall we go on?" question here: a closed step is what
  # readiness to go on means, and a confirmation with nothing to prevent only
  # teaches people to hit Enter without looking. Changing one's mind is still
  # possible — Ctrl-C.
  run_step "$wt" "$slug" "$next"
}

# Back to the session of a step whose closing check failed, when sclaude
# closed it rather than a person — so there is nobody at its end to ask.
#
#   auto_return <wt> <slug> <step> <why>
#
# The same session is resumed, told <why>: it knows what it tried and where it
# stopped, and a fresh one would have to find that out again. At most
# AUTO_RETURNS times per closing of the step; after that, and after a person's
# /exit, it returns 1 and the caller says what to do by hand. Every return
# spends the subscription's limit, and a check that fails twice is more likely
# a problem for a person than for a third try.
AUTO_RETURNS=2
auto_return() {
  local wt="$1" slug="$2" step="$3" why="$4" state="$1/.sclaude/local/feature/state.json" used
  [[ -n "${SESSION_AUTO_CLOSED:-}" ]] || return 1
  used="$(state_get "$state" "steps.$step.auto_returns" 2>/dev/null || true)"
  [[ "$used" =~ ^[0-9]+$ ]] || used=0
  if [[ "$used" -ge "$AUTO_RETURNS" ]]; then
    warn "  $used automatic returns to the session did not help — it needs you."
    return 1
  fi
  # Counted before the session opens: its own end comes back here, and must
  # see this return as spent. Given back if run_step opened nothing — a merge
  # conflict, the session open elsewhere — so the caller says what to do by
  # hand, and the next attempt still has it.
  state_set "$state" "steps.$step.auto_returns" "$((used + 1))"
  info "  Back to the same session ($((used + 1)) of $AUTO_RETURNS automatic returns)."
  RUN_STEP_LAUNCHED=""
  run_step "$wt" "$slug" "$step" "$why"
  if [[ -z "$RUN_STEP_LAUNCHED" ]]; then
    state_set "$state" "steps.$step.auto_returns" "$used"
    return 1
  fi
  return 0
}

# Pushes what a regression's fixing session committed and the open pull
# request does not carry yet. See the step-4 close in after_step.
#
#   regression_push_fix <wt> <pr>  → 0 pushed, 1 nothing to push, 2 push failed
regression_push_fix() {
  local wt="$1" pr="$2" ahead branch
  [[ -n "$pr" && "$pr" != "null" ]] || return 1
  ahead="$(python3 "$LIB/review/pr_context.py" --unpushed "$wt" "$pr" 2>/dev/null || true)"
  [[ "$ahead" =~ ^[1-9][0-9]*$ ]] || return 1
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" && "$branch" != "main" ]] || return 2
  echo ""
  info "  The regression's fix is $ahead commit(s) PR #$pr does not carry — pushing $branch."
  if git -C "$wt" push -q origin "$branch"; then
    info "  pushed; the automatic review reads it before step 4 closes"
    return 0
  fi
  warn "  could not push $branch, so PR #$pr still lacks the fix. Push it by hand:"
  warn "    git -C $wt push origin $branch"
  return 2
}

# The git a step's session runs commits with: its hooks go through
# sclaude/githooks, which add `Sclaude-Session: <id>` to every commit message
# and then run the project's own hooks. Exported into the subshell claude is
# launched from, so it reaches claude's commands and nothing else — the
# repository's config is not touched, and a commit made by hand is as before.
# GIT_CONFIG_* is appended to, not replaced, in case something set it already.
#
#   session_git_env <session>
session_git_env() {
  local n="${GIT_CONFIG_COUNT:-0}"
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  export SCLAUDE_SESSION="$1"
  export "GIT_CONFIG_KEY_$n=core.hooksPath"
  export "GIT_CONFIG_VALUE_$n=$INSTRUMENTS/sclaude/githooks"
  export GIT_CONFIG_COUNT=$((n + 1))
}

# What this process's code is: bin/sclaude and every module it sourced.
# The prompts are left out — they are read afresh for every session anyway.
code_fingerprint() {
  cat "$INSTRUMENTS/bin/sclaude" "$LIB"/*/*.sh 2>/dev/null | cksum
}

# Continue on the code on disk, if it is no longer the code this process runs.
#
#   code_reload <slug> <step> <session>
#
# bash holds the functions it sourced, so a sclaude started before a fix keeps
# the old behaviour to the end — and a step's session lives for hours. The fix
# for step 4's rounds landed while a review session ran, and on that
# session's /exit the old code would have closed the step with new findings
# still open. Here, between claude's exit and anything done about it, the
# process replaces itself with the current sclaude, which picks up where this
# one stands. It does not return when it reloads.
code_reload() {
  [[ -n "${SCLAUDE_CODE:-}" && -z "${SCLAUDE_NO_RELOAD:-}" ]] || return 0
  [[ "$(code_fingerprint)" != "$SCLAUDE_CODE" ]] || return 0
  # The terminal may have been left mid-redraw by claude.
  stty sane 2>/dev/null || true
  info ""
  info "  sclaude changed while the session ran — continuing on the new code."
  exec "$INSTRUMENTS/bin/sclaude" _session-ended "$@"
}

# What a session is told when the feature it opens on was returned to
# development, ahead of the notes the orchestrator collected.
#
#   return_brief <wt> <issue> <pr>
#
# The notes are a copy, taken when the return was noticed; the session is told
# where the originals are and from when, so it reads them itself — a reply
# added since, or a thread on a line, is part of what it has to answer. One
# text for every way back: QA, a late review finding, a second thought.
return_brief() {
  local wt="$1" issue="$2" pr="$3" since
  [[ "$issue" == "null" ]] && issue=""
  [[ "$pr" == "null" ]] && pr=""
  since="$(state_get "$wt/.sclaude/local/feature/state.json" reopened_since 2>/dev/null || true)"
  [[ "$since" == "null" ]] && since=""
  printf '**This feature was returned to development.** What has to be done is what was said about it%s' \
    "${since:+ since $since}"
  printf ' — on the issue%s and on the pull request%s, its conversation and the comments on its lines. ' \
    "${issue:+ (#$issue)}" "${pr:+ (#$pr)}"
  printf 'Read those yourself before anything else'
  [[ -n "$issue" || -n "$pr" ]] && printf ':'
  [[ -n "$issue" ]] && printf ' `gh issue view %s --json comments`' "$issue"
  [[ -n "$pr" ]] && printf '%s `gh pr view %s --comments` and `gh api repos/{owner}/{repo}/pulls/%s/comments`' \
    "${issue:+,}" "$pr" "$pr"
  printf '. Below is what the orchestrator collected when the feature was returned, the reason first when one was given.\n'
}

# The plan, printed in the orchestrator's terminal when it is new to the person
# reading it there.
#
#   plan_report <wt> <step>
#
# The last message is not the plan. Step 1 ends with a report about the plan,
# while the plan itself was in the approval dialogue, which went with claude's
# screen; a later step that reworks the plan (code.md allows it, once agreed)
# says so somewhere in the conversation, and not necessarily last. So:
#
#   * after step 1 the approved plan is printed whole, every time — a replan
#     included;
#   * after any other session it is printed only when .sclaude/local/feature/plan.md differs
#     from the copy printed last, under a headline saying that it changed.
#
# .sclaude/local/feature/plan.printed is that copy. A feature planned before it existed has
# none: the plan is then taken as seen, since there is nothing to tell a change
# from.
plan_report() {
  local wt="$1" step="$2" plan="$1/.sclaude/local/feature/plan.md" printed="$1/.sclaude/local/feature/plan.printed"
  local headline told
  if [[ "$step" == "plan" ]]; then
    capture_plan "$wt" || return 0
    headline="Approved plan (.sclaude/local/feature/plan.md):"
    told="Plan approved"
  else
    [[ -s "$plan" ]] || return 0
    if [[ ! -e "$printed" ]]; then
      cp "$plan" "$printed" 2>/dev/null || true
      return 0
    fi
    cmp -s "$plan" "$printed" && return 0
    headline="Plan changed (.sclaude/local/feature/plan.md):"
    # The plan is printed for this terminal alone; the topic gets how much
    # of it changed, a path being nothing to a phone.
    local added removed
    read -r added removed < <(diff "$printed" "$plan" 2>/dev/null \
      | awk '/^>/ { a++ } /^</ { r++ } END { print a + 0, r + 0 }')
    told="Plan changed · +$added −$removed lines"
  fi
  ask_feed say "$told"
  echo ""
  say_here "${BOLD}$headline${OFF}"
  echo ""
  sed 's/^/  /' "$plan"
  echo ""
  cp "$plan" "$printed" 2>/dev/null || true
}
