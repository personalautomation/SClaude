#!/usr/bin/env bash
#
# Launching a step, moving to the next one, and the friction review between
# them.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- launching a step --------------------------------------------------------

# A step's prompt lies as a file next to the script; we substitute the feature's
# name and, for the review step, the PR's number. We keep the prompts outside:
# they are edited more often than the logic.
#
# sclaude/lib/render_prompt.py does the assembling. sed used to do the
# substituting, and that was a mistake waiting to happen: in its replacement `&`
# means the whole matched text and `|` is the delimiter itself. Through
# <feature> that is unreachable (slugify leaves only [a-z0-9-]), but embedding
# gathered data in a prompt — the issue, the PR's checks, the manuals' tables of
# contents — is impossible with such a substitution at all.
#
# The values go as environment variables rather than arguments: an issue's body
# and a PR's list of comments run to kilobytes, and ARG_MAX does not stretch.
#
# The blocks are assembled right here, each best-effort: the gathering did not
# work, there is no network, there is no gh — the block is empty, and the prompt
# keeps its previous instruction inside itself.
render_prompt() {
  local step="$1" slug="$2" pr="${3:-}" issue="${4:-}" wt="${5:-}"
  local file="$PROMPTS/$step.md"
  [[ -f "$file" ]] || die "no prompt for step $step: $file"

  local -x SCLAUDE_V_FEATURE="$slug"
  local -x SCLAUDE_V_PR="${pr:-—}"
  local -x SCLAUDE_V_ISSUE="$issue"
  # Where this feature's dev server is, for the prompts that send the session to
  # it. Every feature has its own now, so a constant here would send one
  # feature's checks to another's code. No tree — the status epilogue — has no
  # server, and the plain address is as good as any.
  local -x SCLAUDE_V_DEV_URL="http://localhost:3000"
  # The deferred file the friction note points at (deferred.sh).
  local -x SCLAUDE_V_DEFERRED="$DEFERRED_FILE"
  local -x SCLAUDE_V_DEV_PORT="3000"
  # And its own database, when it has one: the conditional paragraph about it
  # drops out of the prompt otherwise.
  local -x SCLAUDE_V_DB_API=""
  # The shared environment the feature works against, if it is not the local
  # one — the prompt then says what not to do there.
  local -x SCLAUDE_V_SHARED_DB=""
  [[ -n "$wt" ]] && declare -F db_shared_env >/dev/null \
    && SCLAUDE_V_SHARED_DB="$(db_shared_env "$wt" 2>/dev/null || true)"
  if [[ -n "$wt" && -f "$wt/.feature/state.json" ]]; then
    SCLAUDE_V_DEV_URL="$(dev_address "$wt")"
    SCLAUDE_V_DEV_PORT="$(feature_port "$wt" || echo 3000)"
    local dbbase; dbbase="$(state_get "$wt/.feature/state.json" db.base 2>/dev/null || true)"
    [[ -f "$wt/.feature/db.env" && "$dbbase" =~ ^[0-9]+$ ]] \
      && SCLAUDE_V_DB_API="http://127.0.0.1:$((dbbase + 1))"
  fi
  local -x SCLAUDE_B_ISSUE_CONTEXT=""
  local -x SCLAUDE_B_MANUAL_TOC=""
  local -x SCLAUDE_B_PR_CONTEXT=""
  local -x SCLAUDE_B_FEATURE_IN_HISTORY=""
  local -x SCLAUDE_B_ISSUE_CHAIN=""
  local -x SCLAUDE_B_ACCEPTANCE=""
  local -x SCLAUDE_B_USER_REQUEST=""
  local -x SCLAUDE_B_REOPENED=""
  # Filled by the caller rather than by the case below: a failed regression is
  # not a property of the step. The same failure reaches `code` from the local
  # stage and `review` from a deployed one, and only regression_fix knows which
  # stage failed and what it printed. Empty here means an ordinary launch, and
  # the block's line drops out of the prompt by itself.
  local -x SCLAUDE_B_REGRESSION="${SCLAUDE_B_REGRESSION:-}"

  case "$step" in
    plan)
      [[ -n "$issue" ]] && SCLAUDE_B_ISSUE_CONTEXT="$(
        python3 "$LIB/issue_context.py" "$issue" "$wt" 2>/dev/null || true)"
      SCLAUDE_B_MANUAL_TOC="$(python3 "$LIB/manual_toc.py" "$wt" 2>/dev/null || true)"
      ;;
    code)
      # What step 1 agreed with the human, read back from the issue rather than
      # carried in the plan. The plan holds a copy — step 1 puts the list at its
      # head — but the issue is where a correction lands: the human edits it in
      # GitHub, and the plan keeps saying what was agreed a week ago.
      #
      # Best-effort like every other block. No issue, no gh, no section — the
      # orchestrator could not write it after step 1, or the human's own
      # "Acceptance criteria" heading kept it from adding one — and the block is
      # empty, its line drops out of the prompt, and the step reads the criteria
      # out of the plan as it would have anyway.
      [[ -n "$issue" ]] && SCLAUDE_B_ACCEPTANCE="$(
        python3 "$LIB/acceptance.py" "$issue" "$wt" 2>/dev/null || true)"
      # The "User request" comment step 1 keeps. Step 2 adds to it what the
      # human asked for during development: without it that lived only in a
      # commit footer, and the issue went on describing the planned scope.
      [[ -n "$issue" ]] && SCLAUDE_B_USER_REQUEST="$(
        python3 "$LIB/issue_context.py" --request "$issue" "$wt" 2>/dev/null || true)"
      ;;
    pr)
      SCLAUDE_B_FEATURE_IN_HISTORY="$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
from pr_context import feature_in_history
sys.stdout.write(feature_in_history(sys.argv[2]))' "$LIB" "$wt" 2>/dev/null || true)"
      # The same plain list as step 2's. It goes into the pull request for the
      # code's reviewer; the boxes stay in the issue, where QA ticks them.
      [[ -n "$issue" ]] && SCLAUDE_B_ACCEPTANCE="$(
        python3 "$LIB/acceptance.py" "$issue" "$wt" 2>/dev/null || true)"
      # Back after the merge, for commits the retrospective left (retro.sh): the
      # feature's pull request is merged, and this one carries only them.
      [[ -n "$wt" ]] && SCLAUDE_B_REOPENED="$(retro_pr_block "$wt" 2>/dev/null || true)"
      ;;
    review)
      [[ -n "$pr" ]] && SCLAUDE_B_PR_CONTEXT="$(
        python3 "$LIB/pr_context.py" "$wt" "$pr" "$(gh_repo)" 2>/dev/null || true)"
      # The review a production rollback sent the cycle back to. No gate opens
      # it, so nobody else fills the block: without this the session got the
      # ordinary review prompt about a pull request it was told was open, with
      # no word of the failure, the rollback or the new pull request the fix
      # needs — and had nothing to fix.
      if [[ -z "$SCLAUDE_B_REGRESSION" && -n "$wt" ]] \
         && [[ "$(state_get "$wt/.feature/state.json" reopened_by 2>/dev/null || true)" == "prod" ]]; then
        SCLAUDE_B_REGRESSION="$(regression_fix_block "$wt" prod 2>/dev/null || true)"
      fi
      ;;
    status)
      # The directory for gh is the main repository rather than the feature's
      # tree: by this moment there is none. The deployment block is not
      # assembled here — run_status passes it ready, because it knows the
      # outcome of the blocks the human answered a minute ago.
      [[ -n "$issue" ]] && SCLAUDE_B_ISSUE_CHAIN="$(
        python3 "$LIB/issue_chain.py" "$issue" "$REPO" 2>/dev/null || true)"
      ;;
  esac

  python3 "$LIB/render_prompt.py" "$file" "$PROMPTS" \
    || die "could not assemble the prompt for step $step"
}

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
  local state="$wt/.feature/state.json" session transcript pr since

  [[ "$step" == "review" ]] || return 0
  pr="$(state_get "$state" pr || true)"
  [[ -n "$pr" && "$pr" != "null" ]] || return 0

  session="$(state_get "$state" "steps.$step.session" || true)"
  [[ -n "$session" ]] || return 0
  transcript="$(transcript_dir "$wt")/$session.jsonl"
  [[ -f "$transcript" ]] || return 0

  # The last entry's time is the file's mtime: the transcript is appended to on
  # every message, so that is precisely "when the step last worked". There is no
  # reason to read the whole jsonl for it.
  since="$(date -Iseconds -r "$transcript" 2>/dev/null)" || return 0
  [[ -n "$since" ]] || return 0

  python3 "$LIB/pr_context.py" "$wt" "$pr" "$(gh_repo)" "$since" 2>/dev/null || true
}

# May step 4 close without a session, if the review turns out clean?
#
# Not when the step has a session of its own already — an interrupted one is
# resumed, never skipped — and not when anything sent the review back.
review_skippable() {
  local wt="$1" slug="$2" state="$1/.feature/state.json" session
  session="$(state_get "$state" steps.review.session 2>/dev/null || true)"
  if [[ -n "$session" && "$session" != "null" ]] && live_session "$wt" "$session" >/dev/null; then
    return 1
  fi
  [[ "$(state_get "$state" reopened 2>/dev/null || true)" == "review" ]] && return 1
  [[ "$(watch_verdict "$slug")" == "returned" ]] && return 1
  [[ -z "$(watch_notes "$slug")" ]] || return 1
  return 0
}

# Wait for the automatic review of the pull request, then say how it went.
#
#   review_wait_state <wt> <slug> <pr>   → clean | dirty | unknown
#
# Step 4 used to open its session straight after step 3, while the review was
# still running, and the session then waited on it or read an empty list. When
# the review finds nothing — PR #136: "No issues found", every check green —
# that session had nothing to do but say so, and cost a launch to say it.
#
# pr_context.py decides; this only waits out `pending`, the way the merge wait
# does, and gives up after REVIEW_WAIT_MAX seconds with `unknown`, which opens
# the session as before. Ctrl-C leaves and loses nothing: the step has not
# started. Everything it prints goes to stderr, since stdout is the answer.
review_wait_state() {
  local wt="$1" slug="$2" pr="$3" word waited=0 announced=0
  [[ -n "$pr" && "$pr" != "null" ]] || { echo unknown; return 0; }
  command -v gh >/dev/null 2>&1 || { echo unknown; return 0; }
  local repo; repo="$(gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || { echo unknown; return 0; }
  while :; do
    word="$(python3 "$LIB/pr_context.py" --state "$wt" "$pr" "$repo" 2>/dev/null || true)"
    if [[ "$word" == "dirty" ]] && review_quota_rerun "$wt" "$slug" "$pr" "$repo"; then
      continue
    fi
    [[ "$word" == "pending" ]] || break
    if [[ "$waited" -ge "$REVIEW_WAIT_MAX" ]]; then
      word="unknown"
      break
    fi
    if [[ "$announced" -eq 0 ]]; then
      announced=1
      info "  Waiting for the automatic review of PR #$pr to finish." >&2
      info "  Ctrl-C to leave — the feature resumes here with: $SELF $slug" >&2
    fi
    [[ -t 2 ]] && printf '\r\033[2K  %sHuman in the loop%s — waiting for the review checks (%s so far, next check in %ss)' \
      "$DIM" "$OFF" "$(regression_duration "$waited")" "$MERGE_POLL" >&2
    sleep "$MERGE_POLL"
    waited=$((waited + MERGE_POLL))
  done
  [[ "$announced" -eq 1 && -t 2 ]] && printf '\r\033[2K' >&2
  echo "${word:-unknown}"
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
# started. Everything it prints goes to stderr: review_wait_state answers on
# stdout.
review_quota_rerun() {
  local wt="$1" slug="$2" pr="$3" repo="$4" got run reset due now left
  got="$(python3 "$LIB/pr_context.py" --quota "$wt" "$pr" "$repo" 2>/dev/null || true)"
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
  "${INSTRUMENTS:-}/bin/sclaude-notify" --quiet \
    "$slug: the automatic review of PR #$pr ran out of Claude quota; sclaude reruns it at $(date -d "@$due" +%H:%M)." \
    >/dev/null 2>&1 || true
  while now="$(date +%s)"; (( now < due )); do
    left=$(( due - now ))
    [[ -t 2 ]] && printf '\r\033[2K  %sHuman in the loop%s — the review reruns in %s' \
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
session_holder() {
  local session="$1"
  [[ -n "$session" ]] || return 0
  timeout 15 claude agents --json 2>/dev/null | SCLAUDE_SESSION="$session" python3 -c '
import json, os, sys
want = os.environ["SCLAUDE_SESSION"]
try:
    agents = json.load(sys.stdin)
except (ValueError, OSError):
    sys.exit(0)
if not isinstance(agents, list):
    sys.exit(0)
for a in agents:
    if not isinstance(a, dict) or a.get("sessionId") != want:
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
  local wt="$1" slug="$2" step="$3" told="${4:-}"
  local state="$wt/.feature/state.json"
  local model effort mode session prompt pr

  model="$(step_model "$step")"
  effort="$(step_effort "$step")"
  mode="$(step_mode "$step")"
  pr="$(state_get "$state" pr || true)"
  local issue; issue="$(state_get "$state" issue || true)"
  # A new feature reaches its first step without naming itself to
  # feature_worktree.
  declare -F term_attach >/dev/null && term_attach "$wt"

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
  fi

  echo ""
  echo "${BOLD}${BLUE}── $slug · step $(($(step_index "$step") + 1))/${#STEPS[@]}: $(step_title "$step") ──${OFF}"
  # Where to look at it, before anything else: with a server per feature,
  # localhost:3000 is the list of features, and the feature's own address is
  # the one thing a person needs from this header.
  echo "   ${BOLD}Open it at $(dev_address "$wt")${OFF}"
  info "   $model / $effort / $mode · $wt"
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
  if [[ "$step" == "review" ]] && review_skippable "$wt" "$slug" \
     && [[ "$(review_wait_state "$wt" "$slug" "$pr")" == "clean" ]]; then
    state_set "$state" "steps.$step.started" "$(date -Iseconds)"
    state_set "$state" "steps.$step.skipped" "clean review"
    say "${GREEN}✓ The automatic review of PR #$pr passed with no findings, no comments and every check green.${OFF}"
    info "  Nothing to answer, so no review session is opened."
    after_step "$wt" "$slug" "$step"
    return 0
  fi
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
    session=""
  fi

  # An open session cannot be opened a second time: claude exits immediately,
  # printing "Resume this session with…". From the outside that is
  # indistinguishable from a step that finished instantly, and the human then
  # answers "finished?" about something that never began. So we check ourselves
  # and name the culprit.
  local holder
  if [[ -n "$session" ]]; then
    holder="$(session_holder "$session")"
    if [[ -n "$holder" ]]; then
      warn ""
      warn "  This step's session is already open elsewhere ($holder)."
      warn "  Close it there and try again — or just carry on where it is open."
      return 0
    fi
  fi

  local -a extra; mapfile -t extra < <(step_settings "$step" "$wt")

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
    RUN_STEP_LAUNCHED=1
    step_run "$wt" "$step" open "$session"
    [[ "$step" == "review" ]] && run_comments "$wt" "$session" "$pr"
    session_watch_start "$wt" "$session" "" "" "$step"
    ( cd "$wt" && dev_env_load "$wt" && session_git_env "$session" && claude_launch --resume "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$slug/$step" ${opening:+"$opening"} )
    session_watch_stop
  else
    session="$(new_session_id)"
    state_set "$state" "steps.$step.session" "$session"
    # The step's start, for the summary in the issue. We write it only for a new
    # session: for a resumed one the step began then, not now.
    state_set "$state" "steps.$step.started" "$(date -Iseconds)"
    step_run "$wt" "$step" open "$session"
    [[ "$step" == "review" ]] && run_comments "$wt" "$session" "$pr"
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
    RUN_STEP_LAUNCHED=1
    issue_sync "$wt"
    session_watch_start "$wt" "$session" "" "" "$step"
    ( cd "$wt" && dev_env_load "$wt" && session_git_env "$session" && claude_launch --session-id "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$slug/$step" "$prompt" )
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
  local state="$wt/.feature/state.json"
  # after_step reads these as run_step's; after code_reload there is no
  # run_step above, and `set -u` stops on the first of them.
  local pr issue
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  issue="$(state_get "$state" issue 2>/dev/null || true)"
  # What the review handed this session over all its rounds, before its row
  # is written for the last time.
  [[ "$step" == "review" ]] && run_comments "$wt" "$session" "$pr"

  # A session that never got going did not work — it refused to start. Asking
  # "is the step finished?" after that means offering to close a step that never
  # was.
  #
  # By the transcript rather than by the clock: see session_started. The clock
  # timed the wrapper and let a stillborn session through whenever the launch
  # itself took longer than the threshold.
  if ! session_started "$wt" "$session"; then
    step_run "$wt" "$step" drop "$session"
    warn ""
    warn "  claude exited immediately — the step never started."
    warn "  See what it printed above; the step stays where it was."
    return 0
  fi
  # The review round is over: the automatic review closed every finding this
  # session fixed, and posted new ones. The new ones go to a session of their
  # own, with none of this one's context — it has no old finding left to
  # answer, and the conversation that fixed them is only weight now. This
  # session's row in the issue says why it ended; the next one is a row of its
  # own. See session_watch_start.
  if [[ "$step" == "review" && -s "$(round_marker "$wt")" ]]; then
    local round_note; round_note="$(head -c 300 "$(round_marker "$wt")")"
    rm -f "$(round_marker "$wt")"
    # The terminal may have been left mid-redraw by the signal.
    stty sane 2>/dev/null || true
    session_report "$wt" "$session"
    plan_report "$wt" "$step"
    step_run "$wt" "$step" end "$session" "fixes confirmed"
    local round_key; round_key="$(step_run_key "$state" "$step" "$session")"
    state_set "$state" "steps.$step.session" null
    watch_seen "$slug"
    issue_sync "$wt"
    echo ""
    say "${BOLD}Review round closed: the automatic review confirmed every fix this session made.${OFF}"
    [[ -n "$round_note" ]] && info "  $round_note"
    info "  The new findings go to a fresh session, without this one's context."
    review_yours_report "$wt" "$pr" || true
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
  # nobody is at the session's end to answer. See done_marker.
  SESSION_AUTO_CLOSED=""
  session_closed "$(done_marker "$wt")" "$wt" "$session" \
    "The session reported its work done, and sclaude closed it." \
    && SESSION_AUTO_CLOSED=1
  plan_report "$wt" "$step"
  [[ "$step" == "review" ]] && { review_yours_report "$wt" "$pr" || true; }
  step_run "$wt" "$step" end "$session"

  # The friction review follows every session, not every step.
  #
  # It used to run once the step closed, on the reasoning that the fix is
  # needed by the step about to start. The reasoning holds, one level down: the
  # next thing to start is the next session, and that is often the same step's.
  # The review step rotates a session per round of the automatic review — #125
  # ran seven — so a ban the first round hit could be met by every round after
  # it and still be reviewed only once, at the end. A session that leaves the
  # step open (a "no" to the question, an unmerged review) used to carry its
  # entries into the next one with nobody reading them.
  #
  # Before after_step rather than after it: after_step leads into the next step
  # and does not come back, and on the last step it leads to remind_prod, whose
  # cmd_done removes the tree with .feature/ and an unread log in it. Closing a
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

  after_step "$wt" "$slug" "$step"
}

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
  ac_issue="$(state_get "$wt/.feature/state.json" issue || true)"

  # The hook should have made this impossible. Should it have been bypassed —
  # an older session, a hook that failed open — the human hears it now rather
  # than finding an empty checklist at QA.
  verdict="$(python3 "$LIB/acceptance.py" --verdict "$wt/.feature/plan.md" 2>/dev/null || true)"
  if [[ "$verdict" == "missing" || "$verdict" == "empty" ]]; then
    warn "  The approved plan has no acceptance criteria — nothing will say what \"done\" means."
    info "  To agree them now: $SELF replan $slug"
    return 0
  fi

  [[ -n "$ac_issue" && "$ac_issue" != "null" ]] || return 0
  out="$(python3 "$LIB/acceptance.py" --sync "$ac_issue" "$wt/.feature/plan.md" "$wt" 2>/dev/null || true)"
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
                info "  The agreed list is in .feature/plan.md; copy it there if QA should tick it." ;;
    *)          warn "  Could not write the acceptance criteria to issue #$ac_issue — they are in .feature/plan.md only." ;;
  esac
}

# The criteria step 2 added to the plan, appended to the issue's list.
#
# Only new identifiers are written; a criterion worded differently in the plan
# is reported, as sync_acceptance reports it. Quiet when nothing changed: this
# runs after every code session.
extend_acceptance() {
  local wt="$1" ac_issue out word line
  ac_issue="$(state_get "$wt/.feature/state.json" issue || true)"
  [[ -n "$ac_issue" && "$ac_issue" != "null" && -f "$wt/.feature/plan.md" ]] || return 0
  out="$(python3 "$LIB/acceptance.py" --extend "$ac_issue" "$wt/.feature/plan.md" "$wt" 2>/dev/null || true)"
  word="${out%%$'\n'*}"
  case "$word" in
    written|extended)
                info "  Acceptance criteria on issue #$ac_issue updated from the plan:"
                while IFS= read -r line; do info "    $line"; done < <(tail -n +2 <<<"$out") ;;
    unchanged|nothing) ;;
    differs)    warn "  The plan's acceptance criteria differ from issue #$ac_issue — only new ones are added:"
                while IFS= read -r line; do info "    $line"; done < <(tail -n +2 <<<"$out")
                info "  The issue is where corrections land. If the plan is right, edit the criteria in GitHub." ;;
    *)          warn "  Could not add the new acceptance criteria to issue #$ac_issue ($word) — they are in .feature/plan.md only." ;;
  esac
}

# Leaving a session means nothing in itself — a step is closed by its result
# rather than by a process that has ended. While there is no result, launching
# again returns to the same step with the same context.
#
# We ask only where the result cannot be looked at. Three steps out of four leave
# a checkable trace, and each has its own:
#
#   plan   — the approved plan, which is .feature/plan.md. It is approved in the
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
  local wt="$1" slug="$2" step="$3"
  local state="$wt/.feature/state.json" next answer

  echo ""
  case "$step" in
    plan)
      if ! capture_plan "$wt"; then
        warn "  No approved plan in this session — the step is not finished."
        auto_return "$wt" "$slug" "$step" \
          "**sclaude could not read the approved plan's text**, so step 1 is not finished: the plan was approved, but the text behind it was not kept. Present the plan for approval again, in full." \
          && return 0
        info "  Approve the plan in the session (it is shown for review), then leave."
        info "  Come back with: $SELF $slug"
        return 0
      fi
      info "  Plan saved to .feature/plan.md — it is what step 2 starts from."
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
      unpushed="$(python3 "$LIB/pr_context.py" --unpushed "$wt" "$number" 2>/dev/null || true)"
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
      # Leaving the session is not the review being done. #143's third round
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
      if ! regression_gate "$wt" "$slug" local; then
        info "  The review waits for a green regression: $SELF $slug"
        return 0
      fi
      # A red run above opens a fixing session, which commits its fix and is
      # not told to push. review_close_gate has already asked whether the pull
      # request carries every commit, so nothing asked again: on feature 145
      # the fix went green here, the preview was deployed from this tree with
      # it, QA accepted that preview — and the pull request merged without it.
      # So it is pushed now, and the review reads it like any other push.
      local fix_pushed=0
      regression_push_fix "$wt" "${pr:-}" || fix_pushed=$?
      if [[ "$fix_pushed" -eq 2 ]]; then
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
      # Feature #104 showed it plainly: the review step closed in the same
      # second PR #136 was merged, and the preview was deployed after both.
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
          prod) warn "  This is still the pull request production was rolled back from (#$seen_pr)." ;;
          returned|qa) warn "  This is still the pull request the feature was returned on (#$seen_pr)." ;;
          *)    warn "  This is still the merged pull request the review was reopened on (#$seen_pr)." ;;
        esac
        info "  A merged pull request cannot be reopened, so the fix needs one of"
        info "  its own; the review stays open until the branch carries it."
        info "  Come back with: $SELF $slug"
        return 0
      fi

      if [[ "$pr_state" == "MERGED" ]]; then
        info "  PR #${pr:-?} is merged — the review is done."
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
      # only; QA ticks in the issue. Before the question, on every exit: the
      # list should not wait for the human to call the step done.
      extend_acceptance "$wt"
      ask "${BOLD}Please check everything yourself after AI. Do you confirm that everything works as it should? [y/n] ${OFF}" answer yn
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
      if ! regression_gate "$wt" "$slug" local; then
        info "  The step waits for a green regression: $SELF $slug"
        return 0
      fi
      ;;
  esac

  step_run "$wt" "$step" close
  # The automatic returns are counted per closing of a step: a step that
  # closed has used none of them on its next run.
  state_set "$state" "steps.$step.auto_returns" null 2>/dev/null || true
  state_set "$state" "steps.$step.done" true
  state_set "$state" "steps.$step.finished" "$(date -Iseconds)"
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
  local wt="$1" slug="$2" step="$3" why="$4" state="$1/.feature/state.json" used
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

# The refusals Claude Code itself issued — into the friction log.
#
# The hook writes only its own: forbidden-commands.py calls note() from deny().
# But in auto mode a command is also judged by the built-in classifier, and its
# refusal is invisible to a hook — Claude Code has no "permission denied" event
# at all. Such a refusal stays only in the transcript, in the toolDenialKind
# field, and collect-denials.py takes it from there once the step has ended.
#
# The caller names the session rather than leaving it to be read from
# steps.<step>.session: a rotated review round has cleared that field by the
# time its review runs, and reading it gathered nothing — the classifier's
# refusals in every round but the last were never collected. The directory is
# the worktree's path with everything but letters and digits replaced by a
# hyphen; the same method as in capture_plan and in run_friction below.
collect_denials() {
  local wt="$1" step="$2" session="${3:-}"
  local transcript

  [[ -n "$session" ]] || return 0

  transcript="$(transcript_dir "$wt")/$session.jsonl"
  [[ -f "$transcript" ]] || return 0

  # CLAUDE_PROJECT_DIR is the same thing the hook finds the log by: the feature
  # worktree's root. The silence on an error is deliberate, as in note() itself:
  # statistics that were not gathered are no reason to bring a feature's cycle
  # down.
  CLAUDE_PROJECT_DIR="$wt" python3 "$HOOKS/collect-denials.py" \
    "$step" "$transcript" 2>/dev/null || true
}

# The friction review: the session that fixes the orchestrator after every step session.
#
# Steps run into bans, and some of those bans are unnecessary — they were
# configured blind. .feature/friction.log accumulates the records of that; here a
# separate session reads them, proposes a fix and, with the human's agreement,
# makes it.
#
# Why a full session rather than a review in the script: deciding "is this ban
# deliberate or an obstacle" requires context — what the step was trying to do
# and what it cost. That is reading a transcript and reasoning, not a grep.
#
# The directory is ~/instruments rather than the feature's worktree: it is the
# orchestrator being edited, not the product, and it is committed straight to
# main. The transcripts lie outside both directories, hence --add-dir: without it
# the file tools will not go there. The feature's worktree is added as well:
# friction is often the project's to fix — its scripts, its CLAUDE.md — and a
# review that could only edit instruments left those for somebody to notice.
# The fourth argument is "re-read what was reviewed": the log is empty and the
# human wants to go back to what has already been reviewed. We then skip both the
# gathering and the tidying — there is nothing to move, and the session reads
# .reviewed anyway.
#
# This used to be done differently: cmd_friction copied .reviewed back into log
# only to pass the emptiness check below, and the tidying then immediately
# appended a copy into .reviewed over the original. Every such round doubled the
# log — twelve entries became twenty-four, then forty-eight, and the review
# session paid for every copy as for a new entry.
run_friction() {
  local wt="$1" slug="$2" key="$3" reread="${4:-}"
  local log="$wt/.feature/friction.log"
  local reviewed="$log.reviewed"
  local state="$wt/.feature/state.json"
  # The key names what is reviewed: `review-3` is the third session of the
  # review step (step_run_key), `fix-preview-1` a fixing session, and a bare
  # step name the key a review had before it followed every session. The step
  # and the session number are read back out of it for the label and for
  # gathering that session's refusals.
  local step="$key" number=""
  if [[ "$key" =~ ^([a-z]+)-([0-9]+)$ ]]; then
    step="${BASH_REMATCH[1]}"
    number="${BASH_REMATCH[2]}"
  fi

  # An unclosed review is one that began and did not reach the end. It changes
  # the answer to "is there anything to review": the log in that case is empty by
  # construction (it was moved into .reviewed before that session), and the
  # emptiness check below would turn away the return into the interrupted
  # conversation.
  #
  # Strictly this review, by key. The question "is anything unclosed anywhere"
  # is a different one and is asked below: `pending` also decides whether the
  # fresh log is moved into .reviewed, and a review of some other key hanging
  # open must not stop this one's entries from being moved — they would never
  # be read.
  local pending=""
  [[ "$(friction_pending "$state" || true)" == "$key" ]] && pending=1

  # An unclosed review elsewhere holds the cycle all the same.
  #
  # It used to hold nothing. The gate above was the only reader of
  # friction_pending here, and it compares against this step's key — so a review
  # keyed `fix-preview-1` was never equal to the step `review`, never fired, and
  # the feature travelled on with it open. Feature 103 carried one to the end
  # that way. cmd_resume and cmd_reset already ask the bare question; this makes
  # the three agree.
  #
  # We send the caller to that review rather than running this one: two open
  # reviews at once would be two conversations editing the orchestrator.
  local other; other="$(friction_pending "$state" || true)"
  if [[ -n "$other" && "$other" != "$key" ]]; then
    warn ""
    warn "  An earlier friction review is still open: $other."
    warn "  It holds the cycle — close it first: $SELF friction $slug"
    return 1
  fi

  # First we gather what the hook could not record: the refusals Claude Code
  # itself issued. There is no hook for such an event — PostToolUse fires only
  # after a successful call — so they are read from the finished step's
  # transcript. This goes BEFORE the emptiness check: a step obstructed by the
  # classifier alone leaves the log empty, and without the gathering the review
  # would not come up at all. That is exactly how three refusals in step 4 of
  # feature 75-review-58-results were lost.
  [[ -n "$reread" ]] || collect_denials "$wt" "$step" "$(step_run_session "$state" "$key")"

  # Empty means there is nothing to review and we do not start a session. When
  # re-reading we look at what was reviewed: there is no fresh log in that case by
  # definition. An unclosed review goes past both checks: it is returning to a
  # conversation rather than starting a new one, and the log is no longer needed
  # for that.
  #
  # An empty log is recorded rather than passed over in silence. Without that
  # the state says nothing at all, and nothing is what a feature abandoned
  # before this step says too — the issue's column could not tell "there was no
  # friction here" from "we never got this far", and printed the same dash for
  # both. One flag settles it, and it is the ordinary case: most steps run into
  # nothing.
  if [[ -n "$pending" ]]; then
    :
  elif [[ -n "$reread" ]]; then
    [[ -s "$reviewed" ]] || return 0
  else
    [[ -s "$log" ]] || {
      state_set "$state" "friction.$key.empty" true
      return 0
    }
  fi

  # One friction review on the machine at a time: they all edit the one
  # instruments tree. On 2026-10-07 at 00:31 #145 and #152 each started one
  # from the same commit, and the two committed a minute apart; they happened
  # to touch different files. The second now waits, and starts on the first
  # one's commits — the tree is shared, so there is nothing to fetch.
  #
  # Taken before the log is moved into .reviewed: a Ctrl-C while waiting
  # leaves the entries where the next review reads them. Every return from
  # here to the session's end gives it up again — see friction_unlock.
  FRICTION_LOCK=""
  FRICTION_LOCK_FILE="$(git -C "$INSTRUMENTS" rev-parse --path-format=absolute \
    --git-common-dir 2>/dev/null)/sclaude-friction.lock"
  if declare -F lock_take >/dev/null && [[ "$FRICTION_LOCK_FILE" == /* ]]; then
    lock_take FRICTION_LOCK "$FRICTION_LOCK_FILE" "$slug, a friction review" "a friction review"
  fi
  # Proposals alone have nothing to decide: see friction_proposals.py. They are
  # put off here, under the lock, since the deferred file is the instruments
  # tree's, and the log moves into .reviewed as a reviewed one does.
  if [[ -z "$reread" && -z "$pending" ]] \
     && friction_defer_proposals "$wt" "$slug" "$key" "$step"; then
    { cat "$log" >> "$reviewed" 2>/dev/null && rm -f "$log"; } || true
    friction_unlock
    push_instruments
    return 0
  fi
  # What is being reviewed, and which prompt says so.
  #
  # A step's review and a fixing session's differ in their opening and their
  # ending and in nothing else — the log's shape, the four sources, what is
  # worth fixing and what is a deliberate ban are the same questions. So the
  # middle lives in _friction-body.md and the two prompts are a header and a
  # tail around it.
  #
  # The label matters in three places below, and `step_title` answers for none
  # of them on a fixing key: it looks up STEP_SPEC and returns empty for
  # `fix-preview-1`, which left the prompt reading `the "" regression` and the
  # terminal `after step ''`.
  local label head_prompt
  if [[ "$step" == fix-* ]]; then
    local rest="${step#fix-}"
    label="${rest%-*}"
    head_prompt="$PROMPTS/friction-fix.md"
  else
    label="$(step_title "$step")"
    head_prompt="$PROMPTS/friction.md"
  fi
  [[ -f "$head_prompt" && -f "$PROMPTS/_friction-body.md" ]] || { friction_unlock; return 0; }

  # We move the log away BEFORE the session rather than after it: the line that
  # stands after the return from `claude` cannot be trusted. The review exists
  # precisely to edit this very file, and bash reads a script lazily, by offset
  # into an open descriptor — rewriting bin/sclaude in place shifts everything
  # below the point of the edit. A Ctrl-C in the session carries the script away
  # the same way. After the `code` step of the password-change feature the
  # tidying did not happen, and twelve reviewed entries came up for review a
  # second time, together with a session and its cost.
  #
  # What was reviewed lies next to it under .reviewed — going back to it is still
  # possible, and that is what `sclaude friction` lives on.
  #
  # We append rather than replace. `mv -f` destroyed the previous .reviewed
  # whenever there already was one: on feature 75-review-58-results step 2's
  # entry about check:links was lost that way — 860 bytes that no longer exist.
  # The round trip through cmd_friction (which copies .reviewed back into log)
  # made that even more certain: it is enough for somebody to have added a line
  # between reviews.
  #
  # When re-reading there is nothing to move: the log is empty and .reviewed is
  # already in place — touching it would mean doubling it.
  # An unclosed review moves nothing here either: its log is already in
  # .reviewed, and a repeat would double the entries — precisely the trouble
  # described a paragraph above about the round trip through cmd_friction.
  [[ -n "$reread" || -n "$pending" ]] \
    || { cat "$log" >> "$reviewed" 2>/dev/null && rm -f "$log" || true; }

  local transcript prompt count
  transcript="$(python3 - "$wt" "$wt/.feature/state.json" <<'PYEOF'
import json, os, sys
wt, state = sys.argv[1], sys.argv[2]
# The same method as in capture_plan: the sessions directory is the worktree's
# path with everything but letters and digits replaced by a hyphen.
encoded = "".join(c if c.isalnum() else "-" for c in wt)
base = os.path.expanduser(os.path.join("~/.claude/projects", encoded))
try:
    with open(state) as fh:
        saved = json.load(fh)
except (OSError, ValueError):
    saved = {}
steps = saved.get("steps") or {}
out = []
# Every session a step ran in, named as its row in the issue. The step's own
# `session` used to be the only one listed, and a rotated review round clears
# it — so the review that follows that round was handed every transcript but
# the one it was about.
for name, node in steps.items():
    node = node or {}
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)]
    sids = [r.get("session") for r in runs] or [node.get("session")]
    for number, sid in enumerate(sids, start=1):
        if not sid:
            continue
        path = os.path.join(base, sid + ".jsonl")
        if os.path.exists(path):
            out.append("%s%s — %s" % (name, " (%d)" % number if len(sids) > 1 else "", path))

# The fixing sessions, which are not steps and are not in `steps`. Their ids
# are kept beside the stage that raised them, and only the first eight
# characters of each: that is what the issue's summary prints, and it is enough
# to find the file — the transcripts are named by the full UUID, so this is a
# prefix match. Forty files in a live directory collide on eight hex characters
# at a rate not worth the state it would take to store the rest; should two
# ever match, the first is no worse than the nothing this used to find.
import glob
for stage, node in (saved.get("regression") or {}).items():
    for short in ((node or {}).get("fixes") or "").split():
        found = sorted(glob.glob(os.path.join(base, short + "*.jsonl")))
        if found:
            # Named as its row in the issue (fix_name in github.sh).
            name = "fix after regression" if stage == "local" else "fix after %s regression" % stage
            out.append("%s — %s" % (name, found[0]))

print("; ".join(out) if out else base)
PYEOF
)"

  # The body is spliced in where the header says `<body>`, then the
  # substitutions run over the whole thing — the tags live on both sides of the
  # seam, `<log>` and `<transcript>` in the body, `<step>` and `<feature>` in
  # the header. `r` reads the file in after the matching line; `d` removes the
  # marker itself, which would otherwise stay above it.
  # The review closes itself once its change is committed, or once it has
  # decided there is nothing to change: it writes this file before its report
  # (see session_watch_start). It runs in instruments, outside the feature's
  # worktree, so the marker is a path of its own, as the epilogue's is.
  local done_file="${TMPDIR:-/tmp}/sclaude-friction-$slug.done"

  # The deferred file the review may append to lives outside instruments
  # (deferred.sh); it is created here so the session finds it with its header.
  deferred_ensure || true
  prompt="$(sed -e "/^<body>$/r $PROMPTS/_friction-body.md" -e "/^<body>$/d" \
    "$head_prompt" \
    | sed -e "s|<feature>|$slug|g" -e "s|<step>|$label|g" \
      -e "s|<deferred>|$DEFERRED_FILE|g" \
      -e "s|<log>|$reviewed|g" -e "s|<transcript>|$transcript|g" \
      -e "s|<done-marker>|$done_file|g" -e "s|<worktree>|$wt|g" \
      -e "s|<branch>|$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "the feature's branch")|g")"

  # The entries begin with a date; "^2" also caught any line of prose starting
  # with a two — on a live log of three entries it gave one.
  count="$(grep -cE '^20[0-9]{2}-' "$reviewed" 2>/dev/null || echo 0)"

  echo ""
  echo "${BOLD}${BLUE}── $slug · friction review after $([[ "$step" == fix-* ]] \
    && printf "the %s fix" "$label" || printf "step '%s'%s" "$label" "${number:+, session $number}") ──${OFF}"
  info "   opus / medium / plan · $INSTRUMENTS"
  info "   $count entries · $(basename "$reviewed")"
  echo ""

  # A review is as much a session as a step, and it is interrupted the same way:
  # by a limit, by a closed terminal, by Ctrl-C. The difference was that a step
  # has somewhere to return to while a review did not: the id was recorded
  # nowhere, the log had already been moved into .reviewed — and the next attempt
  # started the review afresh, paying for the same entries a second time. So it
  # now has a place of its own in the state, next to steps, and it is written
  # BEFORE the launch.
  #
  # We name the session ourselves, as in a step: there is no --bg here (a review
  # runs in the terminal), so --session-id is available, and a UUID generated in
  # advance survives any way of leaving.
  #
  # A review's sessions directory is not a step's: it works in ~/instruments
  # rather than in the feature's tree. The transcript lies at that path, and we
  # check the id's liveness by it too.
  local session
  session="$(state_get "$state" "friction.$key.session" || true)"
  if [[ -n "$session" ]] && ! live_session "$INSTRUMENTS" "$session" >/dev/null; then
    session=""
  fi

  # An open session cannot be opened a second time — the same trouble as with a
  # step: claude exits immediately, printing "Resume this session with…". The
  # five-second threshold below will catch that and leave the review unclosed,
  # but it will tell the human "it did not start" rather than "it is already
  # open" — and they will look for the culprit themselves. So we check here and
  # name it.
  if [[ -n "$session" ]]; then
    local fholder; fholder="$(session_holder "$session")"
    if [[ -n "$fholder" ]]; then
      warn ""
      warn "  This friction review is already open elsewhere ($fholder)."
      warn "  Close it there and try again — or just carry on where it is open."
      warn "  To drop it and move on: $SELF reset $slug"
      friction_unlock
      return 1
    fi
  fi

  # A non-maintainer's review must not commit to main. instruments_sync moved
  # them off it at the start; this is the net under that, for a switch that
  # failed or a checkout made by hand since.
  if ! developer_is_maintainer \
     && [[ "$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null)" == "main" ]]; then
    warn ""
    warn "  The friction review would commit the orchestrator to main, and"
    warn "  MAINTAINERS does not list you. Switch $INSTRUMENTS to dev/<your name>"
    warn "  and run it again: $SELF friction $slug"
    friction_unlock
    return 1
  fi

  local before after project_before project_after
  before="$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null || true)"
  project_before="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"

  # A stall belongs to the conversation that stalled, which its run keeps.
  # Left on the node, it would name this one stalled while it runs — resumed
  # or new: a stalled transcript can exist, so a stall is often resumed.
  state_set "$state" "friction.$key.stalled" null 2>/dev/null || true

  if [[ -n "$session" ]]; then
    # Returning to an interrupted review. The log does not need moving — it is
    # already in .reviewed, and that is what the session was reading; the prompt
    # is the same as it was.
    info "   resuming the interrupted friction review"
    session_runs "$state" "friction.$key" open "$session"
    session_watch_start "" "$session" "$done_file" "$INSTRUMENTS"
    ( cd "$INSTRUMENTS" && claude_launch --resume "$session" --model opus --effort medium \
        --permission-mode plan --add-dir "$HOME/.claude/projects" --add-dir "$wt" \
        --add-dir "$(dirname "$DEFERRED_FILE")" -n "friction/$slug" \
        "Back in the friction review for feature '$slug'. Pick up where the conversation left off; re-read $reviewed if you need to." )
  else
    session="$(new_session_id)"
    # Keyed by what the review is about. `friction.after` used to carry that,
    # because the slot itself was nameless; now the name is the key and the
    # field has nothing left to say.
    state_set "$state" "friction.$key.session" "$session"
    state_set "$state" "friction.$key.started" "$(date -Iseconds)"
    state_set "$state" "friction.$key.done" false
    # What an earlier review of this key came to belongs to that review, which
    # its run keeps. Left on the node, latest_friction_cell reads them first
    # and gives this new review the old one's answer.
    local flag
    for flag in empty fixed unread; do
      state_set "$state" "friction.$key.$flag" null 2>/dev/null || true
    done
    session_runs "$state" "friction.$key" open "$session"
    session_watch_start "" "$session" "$done_file" "$INSTRUMENTS"
    ( cd "$INSTRUMENTS" && claude_launch --session-id "$session" --model opus --effort medium \
        --permission-mode plan --add-dir "$HOME/.claude/projects" --add-dir "$wt" \
        --add-dir "$(dirname "$DEFERRED_FILE")" -n "friction/$slug" "$prompt" )
  fi
  session_watch_stop
  session_closed "$done_file" "$INSTRUMENTS" "$session" \
    "The friction review reported its work done, and sclaude closed it." || true

  after="$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null || true)"
  local changed=""
  if [[ -n "$before" && -n "$after" && "$before" != "$after" ]]; then
    changed=1
    push_instruments
  fi
  friction_unlock
  # And the project's: a review may fix the project in the feature's worktree
  # too, committing on the feature's branch (_friction-body.md). Pushed here,
  # with the project's own hooks, so the pull request carries the fix.
  project_after="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "$project_before" && -n "$project_after" && "$project_before" != "$project_after" ]]; then
    changed=1
    friction_push_project "$wt"
  fi

  # A session that never got going did not review anything — it refused to
  # start or hit a limit right at the entrance. Marking such a review closed
  # means losing it silently: the log is already in .reviewed, and nobody will
  # offer it a second time. The same witness by which run_step tells a step that
  # never happened.
  if ! session_started "$INSTRUMENTS" "$session"; then
    # Marked so the issue can say which kind of open this is. An interrupted
    # review has a conversation to return to; one that never started has
    # nothing, and telling a human to go back to it sends them to an empty
    # transcript.
    state_set "$state" "friction.$key.stalled" true
    # Kept rather than dropped: a stalled review is a row the Friction column
    # already names, and the next attempt opens a new conversation beside it.
    session_runs "$state" "friction.$key" stall "$session"
    warn ""
    warn "  The friction review did not start — it stays open."
    warn "  Come back to it with: $SELF friction $slug"
    return 1
  fi

  session_runs "$state" "friction.$key" finish "$session" \
    "$([[ -n "$changed" ]] && echo fixed || echo reviewed)"
  state_set "$state" "friction.$key.done" true
  state_set "$state" "friction.$key.finished" "$(date -Iseconds)"
  # And we forget the id: the review took place, and there is nowhere left to
  # return to. Left behind, it is as poisonous as a step's dead id, only the
  # other way round — it is alive. The next step's review reads this same field,
  # the closed conversation's transcript is in place, live_session says "alive",
  # and the return branch opens the CLOSED review instead of a new one: the
  # fresh entries are not reviewed at all. Per-key storage narrows that to one
  # step rather than to whatever was reviewed last, but it does not remove it —
  # the id still has to go.
  state_set "$state" "friction.$key.was" "$session"
  # Whether the review changed anything. The HEAD comparison above already knows
  # — it is what decides the push — and throwing the answer away left the column
  # unable to tell a review that fixed the orchestrator from one that read the
  # entries and concluded every ban was deliberate. Both are proper outcomes;
  # they are not the same outcome.
  [[ -n "$changed" ]] && state_set "$state" "friction.$key.fixed" true
  # And which commits it was. The boolean above says a fix happened; the range
  # says what the fix was, and the issue's second table is rendered from it by
  # `git log`. Without it a reader is told the orchestrator changed and has to
  # go and find out how.
  #
  # The range is honest: nothing else moves instruments' HEAD while a review
  # runs. Another feature's review waits in the friction queue, and
  # push_instruments (the other toucher, called on the way into a feature)
  # pushes and never commits, so before..after holds the review's own work and
  # nothing else.
  if [[ -n "$changed" && "$before" != "$after" ]]; then
    state_set "$state" "friction.$key.from" "$before"
    state_set "$state" "friction.$key.to" "$after"
  fi
  # And the project's own commits, when the review fixed the project too: the
  # range above is instruments' and says nothing of them.
  if [[ -n "$project_before" && -n "$project_after" && "$project_before" != "$project_after" ]]; then
    state_set "$state" "friction.$key.project_from" "$project_before"
    state_set "$state" "friction.$key.project_to" "$project_after"
  fi
  # And what the review decided, in its own words.
  #
  # The range above says what changed; it cannot say that nothing changed on
  # purpose. A review that read every entry and found each ban working as
  # intended commits nothing, so it has no range, so the issue's table had no
  # row for it at all — and that is the ordinary outcome, not a rare one. The
  # verdict is the only place it can be recorded.
  #
  # Read from the transcript rather than written by the session: see
  # friction_verdict. A review that never printed the line leaves the fields
  # unset and the table falls back to naming the commits, which is what it did
  # before this existed.
  local verdict
  verdict="$(friction_verdict "$INSTRUMENTS" "$session" || true)"
  if [[ -n "$verdict" ]]; then
    state_set "$state" "friction.$key.verdict" "${verdict%%$'\t'*}"
    local note="${verdict#*$'\t'}"
    [[ -n "$note" && "$note" != "$verdict" ]] \
      && state_set "$state" "friction.$key.verdict_note" "$note"
  fi
  state_set "$state" "friction.$key.session" null
  return 0
}

# Pushes the feature's branch after a friction review committed to it.
#
# Not a reason to stop: like push_instruments, a failed push is about delivery,
# and the next step's push carries the commit as well.
friction_push_project() {
  local wt="$1" branch
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" && "$branch" != "main" ]] || return 0
  if git -C "$wt" push -q origin "$branch" 2>/dev/null; then
    info "  the friction review's fix to the project is pushed to $branch"
  else
    warn "  could not push the friction review's fix to $branch — push it by hand:"
    warn "    git -C $wt push origin $branch"
  fi
}

# Puts off a friction log that holds only proposed CLAUDE.md rules, without a
# session: the rows go into the deferred file (outside instruments, see
# deferred.sh), and the state records the review the way a session's deferral
# does. Nothing is committed — the orchestrator did not change. Returns 1 to
# leave the log to a session: anything but proposals in it, or a deferred file
# that could not be written.
#
#   friction_defer_proposals <wt> <slug> <key> <step>
friction_defer_proposals() {
  local wt="$1" slug="$2" key="$3" step="$4"
  local log="$wt/.feature/friction.log" state="$wt/.feature/state.json"
  local rows n now
  [[ -s "$log" ]] || return 1
  rows="$(python3 "$LIB/friction_proposals.py" "$log" "$(basename "$REPO")" \
            "$slug" "$step" 2>/dev/null)" || return 1
  [[ -n "$rows" ]] || return 1
  n="$(grep -c . <<< "$rows")"
  deferred_ensure || return 1
  printf '%s\n' "$rows" >> "$DEFERRED_FILE" 2>/dev/null || return 1
  now="$(date -Iseconds)"
  state_set "$state" "friction.$key.started" "$now"
  state_set "$state" "friction.$key.finished" "$now"
  state_set "$state" "friction.$key.done" true
  state_set "$state" "friction.$key.verdict" deferred
  state_set "$state" "friction.$key.verdict_note" \
    "only CLAUDE.md proposals ($n), put off by sclaude without a session"
  echo ""
  info "  friction after '$key': $n CLAUDE.md proposal(s), put off to the monthly review — no session needed"
  return 0
}

# Pushes what a regression's fixing session committed and the open pull
# request does not carry yet. See the step-4 close in after_step.
#
#   regression_push_fix <wt> <pr>  → 0 pushed, 1 nothing to push, 2 push failed
regression_push_fix() {
  local wt="$1" pr="$2" ahead branch
  [[ -n "$pr" && "$pr" != "null" ]] || return 1
  ahead="$(python3 "$LIB/pr_context.py" --unpushed "$wt" "$pr" 2>/dev/null || true)"
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

# Gives up the friction queue run_friction took, if it took one.
friction_unlock() {
  declare -F lock_release >/dev/null || return 0
  lock_release "${FRICTION_LOCK:-}" "${FRICTION_LOCK_FILE:-}"
  FRICTION_LOCK=""
}

# Sends the review's commits to origin.
#
# The review edits the orchestrator and commits to the branch instruments_sync
# put it on — main for a maintainer, dev/<name> for everybody else — but until
# now nobody did the pushing, and the fix stayed on one machine. That is not
# noticeable at once: the next step takes it from the working tree and behaves
# correctly, so an unpushed commit lies there exactly until somebody remembers
# it.
#
# Without a question: the commit has already been approved by the human inside
# the review session, and a second confirmation would stand in the middle of the
# cycle, before the next step.
#
# A failed push does not bring the cycle down — it is about delivery rather than
# the work: the fix is in place and available to the step. So we warn and carry
# on, naming the command to finish it by hand.
push_instruments() {
  local branch ahead
  branch="$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" ]] || return 0
  # Only the branches sclaude itself commits to. A maintainer's `wip/foo` is
  # theirs to publish or not, and pushing it unasked on the way into a feature
  # would decide that for them.
  instruments_own_branch "$branch" || return 0

  # Nothing to send is the ordinary case once this is also called on the way
  # into a feature: say nothing and cost nothing. A branch with no upstream
  # answers this with a fatal error rather than a number, so the question is
  # asked in a way that cannot throw — hence `|| true` and the digit check
  # rather than `@{u}`, which dies where there is no upstream at all.
  #
  # Counted against everything origin has rather than against origin/<branch>:
  # a developer's dev/<name> does not exist on origin until its first push, and
  # a count against a missing ref is an error — which read as "nothing to send"
  # and kept the branch on this machine for ever.
  # With no origin at all, "not on origin" is every commit there is — so no
  # origin is asked about first, and answers nothing.
  git -C "$INSTRUMENTS" remote get-url origin >/dev/null 2>&1 || return 0
  ahead="$(git -C "$INSTRUMENTS" rev-list --count HEAD --not --remotes=origin 2>/dev/null || true)"
  [[ "$ahead" =~ ^[0-9]+$ ]] || return 0
  [[ "$ahead" -gt 0 ]] || return 0

  info "  instruments: pushing $ahead commit(s) to origin/$branch"
  if GIT_TERMINAL_PROMPT=0 git -C "$INSTRUMENTS" push -u origin "$branch" >/dev/null 2>&1; then
    info "  instruments: pushed"
  else
    warn "  instruments: push failed — the work is committed but not sent"
    warn "  finish it by hand: git -C $INSTRUMENTS push origin $branch"
    # Somebody outside the team that owns this repository cannot push to it at
    # all, and that is by design: their fixes reach everybody through a pull
    # request from a fork of their own.
    if ! developer_is_maintainer; then
      warn "  no write access? propose it instead:"
      warn "    cd $INSTRUMENTS && gh repo fork --remote --remote-name fork"
      warn "    git push -u fork $branch && gh pr create --fill"
    fi
  fi
}

# The branches sclaude may push and merge main into: main, and this person's
# dev/<name>. Anything else in ~/instruments is somebody's own work in progress.
instruments_own_branch() {
  local branch="$1" name
  [[ "$branch" == "main" ]] && return 0
  name="$(developer_name 2>/dev/null || true)"
  [[ "$branch" == "dev/${name:-local}" ]]
}

# Whether another sclaude is running from this checkout, in another terminal.
#
# Its bash has sourced the modules already, but its claude sessions read hooks
# and prompts from disk when they use them, and it calls the python helpers by
# path with the arguments of the code it loaded. Updating the files under it is
# the in-place-edit hazard CLAUDE.md describes, spread across processes — so the
# update waits for a moment when nobody else is running.
#
# Another terminal, not this one: a process in our own session is this run and
# its subshells. The bot's short `sclaude status` calls count too, and only cost
# an update deferred to the next command.
#
# Nor our own ancestors. term_record runs this sclaude under script(1), which
# starts it in a session of its own, and script's command line names sclaude:
# every recorded run read its own recorder as "another sclaude (pid N)" — N being
# the pid in the name of its own recording — and never updated (feature 145).
#
# Every one of them is named, one per session, with what it runs and for how
# long: naming the first alone sent the person to close it only to meet the
# next, and a bare pid says nothing about a process with no terminal of its own.
instruments_others() {
  local mysid pid sid etime args up=$$ ancestors=" " seen=" " found=""
  mysid="$(ps -o sid= -p $$ 2>/dev/null | tr -d ' ')"
  while up="$(ps -o ppid= -p "$up" 2>/dev/null | tr -d ' ')" \
        && [[ "$up" =~ ^[0-9]+$ && "$up" -gt 1 ]]; do
    ancestors+="$up "
  done
  while read -r pid sid etime args; do
    [[ -n "$mysid" && "$sid" == "$mysid" ]] && continue
    [[ "$ancestors" == *" $pid "* ]] && continue
    [[ "$seen" == *" $sid "* ]] && continue
    if [[ "$args" =~ (^|[[:space:]/])sclaude([[:space:]]|$) ]]; then
      seen+="$sid "
      found+="${found:+, }pid $pid: sclaude${args##*sclaude}, up $etime"
    fi
  done < <(ps -eo pid=,sid=,etime=,args= 2>/dev/null)
  [[ -n "$found" ]] || return 1
  echo "$found"
}

# Brings the orchestrator up to date before anything runs, and puts a
# non-maintainer on a branch of their own.
#
# Everybody installs instruments from one repository rather than keeping a fork,
# so the only way a fix reaches a team is this: at the start of a command that
# is about to act, fetch main and bring it in. Without it each machine runs
# whatever it happened to clone, and a copy used from two machines runs two
# orchestrators.
#
# The branch comes first. MAINTAINERS says who may commit the orchestrator to
# main; for anybody else the friction review has to commit somewhere else, and
# switching branches under a running review would change the prompts and hooks
# it reads from disk mid-session. So it happens here, before any step, and the
# process restarts on the result.
#
# What is deliberately left alone:
#
#   a dirty tree       somebody is editing the orchestrator by hand; a merge
#                      would mix into their work. Said, not done.
#   a conflict         aborted, said, and the run continues on the code as it
#                      was — a broken merge is worse than a stale orchestrator.
#   no network         silent; the fetch is bounded so it cannot hang a start.
#   SCLAUDE_NO_SYNC    set by benches, which run the real bin/sclaude from this
#                      repository and must not fetch or merge anything.
#   another sclaude    running from this checkout in another terminal: its
#                      sessions read the files being replaced (see
#                      instruments_others). The update waits for a free moment.
#   another branch     anything but main and dev/<name> is somebody's own work,
#                      and main is not merged into it.
#
# After a change the process re-executes itself: bash has already read this
# file and sourced every module, and carrying on would run the old code over
# the new files. SCLAUDE_SYNCED stops the second run from doing it again.
instruments_sync() {
  [[ -z "${SCLAUDE_NO_SYNC:-}" && -z "${SCLAUDE_SYNCED:-}" ]] || return 0
  git -C "$INSTRUMENTS" remote get-url origin >/dev/null 2>&1 || return 0

  local branch changed="" name own behind other
  branch="$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" ]] || return 0

  if other="$(instruments_others)"; then
    info "  instruments: not updated — another sclaude is running from it ($other)"
    return 0
  fi

  if [[ "$branch" == "main" ]] && ! developer_is_maintainer; then
    name="$(developer_name)"
    own="dev/${name:-local}"
    if git -C "$INSTRUMENTS" show-ref --verify -q "refs/heads/$own"; then
      git -C "$INSTRUMENTS" switch -q "$own" 2>/dev/null
    else
      git -C "$INSTRUMENTS" switch -q -c "$own" 2>/dev/null
    fi
    if [[ "$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null)" == "$own" ]]; then
      info "  instruments: on $own — MAINTAINERS does not list you, so fixes go here"
      branch="$own"
      changed=1
    else
      warn "  instruments: could not switch to $own; staying on main"
    fi
  fi

  if GIT_TERMINAL_PROMPT=0 timeout 20 \
       git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null; then
    behind="$(git -C "$INSTRUMENTS" rev-list --count HEAD..origin/main 2>/dev/null || true)"
    if [[ "$behind" =~ ^[0-9]+$ && "$behind" -gt 0 ]]; then
      if [[ -n "$(git -C "$INSTRUMENTS" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
        warn "  instruments: $behind commit(s) behind main, not updated —"
        warn "  $INSTRUMENTS has uncommitted changes"
      elif [[ "$branch" == "main" ]]; then
        if git -C "$INSTRUMENTS" merge -q --ff-only origin/main >/dev/null 2>&1; then
          info "  instruments: updated by $behind commit(s) from main"
          changed=1
        else
          warn "  instruments: main has diverged from origin/main; not updated"
        fi
      elif ! instruments_own_branch "$branch"; then
        info "  instruments: $behind commit(s) behind main; $branch is not"
        info "  sclaude's to merge into (only main and dev/<name> are)"
      else
        local merge_out
        if merge_out="$(git -C "$INSTRUMENTS" merge -q --no-edit origin/main 2>&1)"; then
          info "  instruments: merged $behind commit(s) from main into $branch"
          changed=1
        elif [[ -n "$(git -C "$INSTRUMENTS" ls-files -u 2>/dev/null)" ]]; then
          # A real conflict: our merge stopped half-way, and only then is there
          # a merge of ours to abort. Aborting on any failure could abort
          # somebody else's merge — another process holding index.lock is also
          # a failure.
          git -C "$INSTRUMENTS" merge --abort >/dev/null 2>&1 || true
          warn "  instruments: merging main into $branch conflicts; left as it was"
          warn "  resolve it by hand: git -C $INSTRUMENTS merge origin/main"
        else
          warn "  instruments: could not merge main into $branch; left as it was"
          warn "  git said: $(head -1 <<< "$merge_out")"
        fi
      fi
    fi
  fi

  [[ -n "$changed" ]] || return 0
  export SCLAUDE_SYNCED=1
  exec "$0" "$@"
}

# May step 4 close? Waits out a review still running, then, if anything is
# left open, offers the session back. Returns 0 to go on closing.
#
#   review_close_gate <wt> <slug> <pr>
#
# Its answer, as `pr_context.py --close` gives it: `ok`, `pending` or
# `open: <why>`. Anything unreadable is `ok`.
review_close_gate() {
  local wt="$1" slug="$2" pr="$3" word waited=0 announced=0 answer repo
  [[ -n "$pr" && "$pr" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || return 0
  while :; do
    word="$(python3 "$LIB/pr_context.py" --close "$wt" "$pr" "$repo" 2>/dev/null || true)"
    if [[ "$word" == open:*red:* ]] && review_quota_rerun "$wt" "$slug" "$pr" "$repo"; then
      continue
    fi
    [[ "$word" == "pending" ]] || break
    if [[ "$waited" -ge "$REVIEW_WAIT_MAX" ]]; then
      word="open: the automatic review of PR #$pr has not finished"
      break
    fi
    if [[ "$announced" -eq 0 ]]; then
      announced=1
      info "  The automatic review of PR #$pr is still running; step 4 closes once it has finished."
      info "  Ctrl-C to leave — the feature resumes here with: $SELF $slug"
    fi
    sleep "$MERGE_POLL"
    waited=$((waited + MERGE_POLL))
  done
  # Only the threads the person kept: no session, a wait for their hand. Once
  # they are resolved the pull request is asked again from the top — whatever
  # else is open by then takes the ordinary way.
  if [[ "$word" == yours:* ]]; then
    review_yours_wait "$wt" "$slug" "$pr" "$repo" || return 1
    review_close_gate "$wt" "$slug" "$pr"
    return $?
  fi
  [[ "$word" == open:* ]] || return 0

  warn ""
  warn "  Step 4 is not done — ${word#open: }."
  if [[ -n "${SESSION_AUTO_CLOSED:-}" ]]; then
    review_reopen "$wt" "$slug" "$pr" "$repo" "$waited"
    return 1
  fi
  ask "${BOLD}Back to a review session for it? [y/n] ${OFF}" answer yn
  if is_yes "$answer"; then
    run_step "$wt" "$slug" review
    return 1
  fi
  ask "${BOLD}Close step 4 anyway, with that left as it is? [y/n] ${OFF}" answer yn
  if ! is_yes "$answer"; then
    info "  Left open. Come back with: $SELF $slug"
    return 1
  fi
  return 0
}

# The review threads the person decided to leave as they are, and that are
# still open: theirs to resolve on GitHub (see YOURS_FILE in pr_context.py).
#
#   review_yours_report <wt> <pr> [<repo>]
#
# Printed by sclaude itself at the end of every review session rather than left
# to the session's report: on #161 three reports in a row said "you close the
# thread" in their middle, with no link, and the thread came back each round.
# Prints nothing when there is nothing to resolve. Returns 0 when it printed.
review_yours_report() {
  local wt="$1" pr="$2" repo="${3:-}" lines link where note
  [[ -s "$wt/.feature/review-yours" && -n "$pr" && "$pr" != "null" ]] || return 1
  [[ -n "$repo" ]] || repo="$(gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || return 1
  lines="$(python3 "$LIB/pr_context.py" --yours "$wt" "$pr" "$repo" 2>/dev/null || true)"
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
  "${INSTRUMENTS:-}/bin/sclaude-notify" \
    "$slug: PR #$pr waits for you — resolve on GitHub the review threads you decided to leave as they are." \
    >/dev/null 2>&1 || true
  while :; do
    ask "${BOLD}Resolved them? [y/n] ${OFF}" answer yn
    if ! is_yes "$answer"; then
      info "  Left open. Come back with: $SELF $slug"
      return 1
    fi
    word="$(python3 "$LIB/pr_context.py" --close "$wt" "$pr" "$repo" 2>/dev/null || true)"
    [[ "$word" == yours:* ]] || return 0
    warn "  GitHub still shows ${word#yours: } of them open."
    review_yours_report "$wt" "$pr" "$repo" || true
  done
}

# Where a review that is not done goes, when its session was closed by the
# orchestrator rather than by a person — so nobody is there to be asked.
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
#   * only threads opened after it began — a new round, which gets a fresh
#     session, as a round marker would have given it.
review_reopen() {
  local wt="$1" slug="$2" pr="$3" repo="$4" waited="$5"
  local state="$wt/.feature/state.json" session since split older newer
  if [[ "$waited" -ge "$REVIEW_WAIT_MAX" ]]; then
    info "  Nothing to fix until it has finished. Come back with: $SELF $slug"
    return 0
  fi
  session="$(state_get "$state" steps.review.session 2>/dev/null || true)"
  since="$(python3 - "$state" "$session" <<'PY' 2>/dev/null || true
import json, sys
with open(sys.argv[1]) as fh:
    runs = ((json.load(fh).get("steps") or {}).get("review") or {}).get("runs") or []
starts = [r.get("started") or "" for r in runs
          if isinstance(r, dict) and r.get("session") == sys.argv[2]]
print(min((s for s in starts if s), default=""))
PY
)"
  split="$(python3 "$LIB/pr_context.py" --open-since "$wt" "$pr" "$repo" "$since" 2>/dev/null || true)"
  read -r older newer <<<"$split"
  if [[ "${older:-}" == "0" && "${newer:-0}" -gt 0 ]]; then
    info "  The review posted $newer new finding(s) — a fresh session takes them."
    state_set "$state" steps.review.session null
  else
    info "  Back to the session that was fixing them."
  fi
  run_step "$wt" "$slug" review
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
  cat "$INSTRUMENTS/bin/sclaude" "$LIB"/*.sh 2>/dev/null | cksum
}

# Continue on the code on disk, if it is no longer the code this process runs.
#
#   code_reload <slug> <step> <session>
#
# bash holds the functions it sourced, so a sclaude started before a fix keeps
# the old behaviour to the end — and a step's session lives for hours. The fix
# for step 4's rounds landed while #143's review session ran, and on that
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
  since="$(state_get "$wt/.feature/state.json" reopened_since 2>/dev/null || true)"
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

# The review step, one round per session.
#
# A review round: the session fixes the open findings — through subagents, so
# its own context holds the coordination rather than every file it read — and
# pushes; the automatic review reads the fixes and closes what they fixed. When
# it has closed every one of them and posted new findings, the session that
# fixed the old ones has nothing left to answer, and all it carries into the
# new findings is context. On #143 five rounds ran in one conversation.
#
# A session cannot clear its own context — /clear and /compact are the
# person's, and no tool reaches them — so the orchestrator does it. The
# session writes round_marker and stops; the watcher below ends the claude
# process, and run_step records the session as ended with "fixes confirmed"
# and opens a fresh one, whose prompt carries the pull request as it stands —
# the new findings, and only them, open.
round_marker() {
  echo "$1/.feature/review-round"
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
#   * code — sclaude asks the person whether it works, and a "no" goes back to
#     the same session;
#   * friction and the epilogue — the person approved the plan in the session,
#     and nothing after them waits on a check.
#
# Where a check fails, the work goes back to a session — without a person to
# ask, since nobody typed /exit (see auto_return).
done_marker() {
  echo "$1/.feature/session-done"
}

# The watcher beside a session that may end itself.
#
#   session_watch_start <wt> <session> [<marker> <cwd> <kind>]
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
# The epilogue and the friction review run outside the feature's worktree — in
# the main repository, in instruments — so they name their own marker and the
# directory their transcript is kept under; <wt> is then empty.
#
# Step 1 writes no marker: its kind, "plan", makes the plan's approval the
# moment counted from instead (session_end.py approved). A person who types
# after the approval keeps the session: it then waits for /exit.
#
# SESSION_POLL and SESSION_GRACE are seconds, overridable for the tests.
session_watch_start() {
  local wt="$1" session="$2" done="${3:-}" cwd="${4:-$1}" kind="${5:-}"
  local round="" transcript
  SESSION_WATCHER=""
  [[ -n "$session" ]] || return 0
  [[ -n "$wt" ]] && round="$(round_marker "$wt")"
  [[ -n "$done" ]] || done="$(done_marker "$wt")"
  rm -f ${round:+"$round"} "$done"
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
    marker="" since="" ended="" size="" seen="" verdict=""
    lseen="" hit="" told="" acted="" due=0
    while sleep "${SESSION_POLL:-5}"; do
      size="$(stat -c %s "$transcript" 2>/dev/null || echo 0)"
      if [[ "$size" != "$lseen" ]]; then
        lseen="$size"
        hit="$(python3 "$LIB/session_end.py" limit "$transcript" "$started" 2>/dev/null)"
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
              && "$INSTRUMENTS/bin/sclaude-notify" "$label: Claude hit its ${htype//_/-} limit. sclaude resumes the session by itself at $(date -d "@$due" +%H:%M)." \
                   >/dev/null 2>&1 || true
          fi
          if (( $(date +%s) >= due )); then
            acted="$huuid"
            echo "$huuid" > "$limit_file"
            pkill -TERM -f -- "(--session-id|--resume) $session" 2>/dev/null || true
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
      elif [[ "$kind" != "plan" ]]; then
        ended=""; continue
      fi
      # The transcript is read again only when it has grown: a planning
      # session lives for hours, and its file reaches megabytes.
      size="$(stat -c %s "$transcript" 2>/dev/null || echo 0)"
      if [[ "$size:$since" != "$seen" ]]; then
        seen="$size:$since"
        if [[ -n "$marker" ]]; then
          verdict="$(python3 "$LIB/session_end.py" watch "$transcript" "$since" 2>/dev/null)"
        else
          verdict="$(python3 "$LIB/session_end.py" watch-plan "$transcript" "$started" 2>/dev/null)"
        fi
      fi
      case "$verdict" in
        human) [[ -n "$marker" ]] && rm -f "$marker"; ended="" ;;
        ended)
          [[ -n "$ended" ]] || ended="$(date +%s)"
          if (( $(date +%s) - ended >= ${SESSION_GRACE:-30} )); then
            # What session_ended looks for to know it was not a person's /exit.
            [[ -n "$marker" ]] || echo "plan approved" > "$done"
            pkill -TERM -f -- "(--session-id|--resume) $session" 2>/dev/null || true
            exit 0
          fi ;;
        *) ended="" ;;
      esac
    done
  ) &
  SESSION_WATCHER=$!
  return 0
}

session_watch_stop() {
  [[ -n "${SESSION_WATCHER:-}" ]] || return 0
  kill "$SESSION_WATCHER" 2>/dev/null || true
  wait "$SESSION_WATCHER" 2>/dev/null || true
  SESSION_WATCHER=""
  return 0
}

# Whether the watcher closed a session, and if it did, its report: printed,
# with the marker removed so the next session starts clean.
#
#   session_closed <marker> <cwd> <session> <headline>
#
# Returns 0 when the session was closed by sclaude, 1 when a person left it.
session_closed() {
  [[ -s "$1" ]] || return 1
  rm -f "$1"
  # The terminal may have been left mid-redraw by the signal.
  stty sane 2>/dev/null || true
  echo ""
  say "${BOLD}$4${OFF}"
  session_report "$2" "$3"
  return 0
}

# The last message of a session the orchestrator closed, printed in its own
# terminal: claude's screen went with the process, and the person may not have
# finished reading the report before it did. Its advice to type /exit is cut
# out by session_end.py, and the line after it says why: whatever the cut
# missed, the person reads that the session is closed.
#
#   session_report <wt> <session>
session_report() {
  local text
  text="$(python3 "$LIB/session_end.py" last "$(transcript_dir "$1")/$2.jsonl" 2>/dev/null || true)"
  [[ -n "$text" ]] || return 0
  echo ""
  say "${BOLD}The session's last message — the Claude session is already closed, do not type /exit:${OFF}"
  echo ""
  printf '%s\n' "$text" | sed 's/^/  /'
  echo ""
  say "${BOLD}You do not need to type /exit: sclaude has already left the Claude session, and carries on from here.${OFF}"
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
#   * after any other session it is printed only when .feature/plan.md differs
#     from the copy printed last, under a headline saying that it changed.
#
# .feature/plan.printed is that copy. A feature planned before it existed has
# none: the plan is then taken as seen, since there is nothing to tell a change
# from.
plan_report() {
  local wt="$1" step="$2" plan="$1/.feature/plan.md" printed="$1/.feature/plan.printed"
  local headline
  if [[ "$step" == "plan" ]]; then
    capture_plan "$wt" || return 0
    headline="The approved plan — .feature/plan.md, what step 2 starts from:"
  else
    [[ -s "$plan" ]] || return 0
    if [[ ! -e "$printed" ]]; then
      cp "$plan" "$printed" 2>/dev/null || true
      return 0
    fi
    cmp -s "$plan" "$printed" && return 0
    headline="The plan was changed in this session — .feature/plan.md now reads:"
  fi
  echo ""
  say "${BOLD}$headline${OFF}"
  echo ""
  sed 's/^/  /' "$plan"
  echo ""
  cp "$plan" "$printed" 2>/dev/null || true
}
