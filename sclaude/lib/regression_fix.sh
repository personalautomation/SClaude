#!/usr/bin/env bash
#
# The session that fixes a red regression: what it is told, the marks it
# leaves, and how its fixes are counted.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Which step fixes a stage's failure.
#
# Local means the code is wrong and step 2 is where code is written. A deployed
# stage means the branch is already a pull request, and review is the step that
# pushes to it — including after production, because the worktree and the branch
# now outlive the prod deploy (remind_prod cleans up last). What that session
# must not do is commit to main: the feature's PR is merged by then, so a fix
# branches from a fresh main and opens a new pull request of its own. The prompt
# says so; the step's own bans already refuse a merge.
regression_fix_step() {
  case "$1" in
    local) printf 'code' ;;
    *)     printf 'review' ;;
  esac
}

# What became of one fixing session, kept beside its id.
#
# A space-joined string aligned with `fixes`, position for position, because
# state_set writes scalars and a list is not among the shapes it can carry —
# the same constraint that made `fixes` a string. The reader numbers rows by
# position in `fixes`, so both sides derive the row from the same thing.
#
# Two operations, and keeping them apart is the whole of it. A launch appends a
# word — that is what makes the string grow in step with `fixes`. An outcome
# rewrites the last word, which is the session that was just launched; every
# earlier word is settled history.
#
# Written as one function with an append flag rather than two, because the two
# must agree on the shape of the string, and a second function is a second
# place for that agreement to rot.
fix_status_set() {
  fix_word_set "$1" "$2" fix_status "$3" "${4:-}"
}

# The same shape for any field aligned with `fixes`: fix_status, and the
# session's own start and end times (fix_started, fix_finished).
fix_word_set() {
  local state="$1" stage="$2" field="$3" value="$4" append="${5:-}"
  local current
  current="$(state_get "$state" "regression.$stage.$field" 2>/dev/null || true)"
  if [[ "$append" == "append" || -z "$current" ]]; then
    state_set "$state" "regression.$stage.$field" "${current:+$current }$value"
  else
    state_set "$state" "regression.$stage.$field" \
      "$(printf '%s' "$current" | awk -v v="$value" '{ $NF = v; print }')"
  fi
}

# The block a fixing prompt embeds (`<block:regression>`): which stage failed,
# on which part, the tail of its log, and what the session must know about the
# pull request and about a rollback.
#
# Two callers. regression_fix, for a session the gate opens, passes `gate` and
# gets _regression-fail.md as well: that file speaks of the gate's rerun and of
# the note the gate reads back. run.sh, for the review session that follows a
# production rollback, passes nothing — no gate runs after that session, and a
# note it wrote would be read by nobody.
#
# `merged` is the pull request's state when the caller knows it; prod implies
# it, since production ships only after the merge.
regression_fix_block() {
  local wt="$1" stage="$2" merged="${3:-}" mode="${4:-}"
  local state="$wt/.sclaude/local/feature/state.json" log="$wt/.sclaude/local/feature/regression.log"
  local failed pr issue
  failed="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
  [[ "$failed" == "null" ]] && failed=""
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ "$issue" == "null" ]] && issue=""

  # The block the prompt embeds: which stage, which part, and the tail of the
  # log. The tail rather than the whole file — the session can open the file
  # itself, and the prompt's job is to say where to look, not to be the log.
  # Which log to quote. After a rollback it is not the one at the usual path:
  # regression_run points it at a new file, and the confirmation run that
  # follows a rollback is a regression_run — so by the time this session opens,
  # `.sclaude/local/feature/regression.log` describes the *previous release passing*. That is
  # the opposite of the evidence this session needs and plausible enough that
  # nobody would question it, which is why rollback_keep_log records the
  # failing run's file.
  # Production's alone: nothing clears these keys, and a later local or preview
  # red read through them was quoted the old production run instead of its own.
  local rolled="" kept=""
  if [[ "$stage" == "prod" ]]; then
    rolled="$(state_get "$state" rollback.prod.code 2>/dev/null || true)"
    kept="$(state_get "$state" rollback.prod.log 2>/dev/null || true)"
  fi
  [[ "$kept" == "null" ]] && kept=""
  [[ -n "$kept" && -s "$kept" ]] || kept="$log"

  local dfail; dfail="$(state_get "$state" "regression.$stage.deploy_failed" 2>/dev/null || true)"
  [[ "$dfail" == "null" ]] && dfail=""
  if [[ -n "$dfail" ]]; then
    # Not the suite: the deploy itself (preview_ship, remind_prod), whose
    # output stayed in the terminal.
    printf '**The %s deploy failed at `%s`.**\n\n' "$stage" "$dfail"
    printf 'Its output is not kept: run that command again from the main repository to see the error '
    printf '(for a Vercel build, `vercel inspect --logs <url>` shows its log). Find the cause in the code, '
    printf 'the build or a migration and fix it. A cause outside the code — the login to Vercel, the network, '
    printf 'a limit — is not yours to fix: say so in `.sclaude/local/feature/regression.blocked`, and change nothing.\n\n'
    if [[ "$stage" == "prod" ]]; then
      printf 'Production still runs the release it had; if the promote ran, its database may already carry the new migrations.\n\n'
      # Its suite, run after the failure when the promote began (remind_prod).
      if [[ "$(state_get "$state" regression.prod.after_failure 2>/dev/null || true)" == red ]]; then
        printf 'Production'"'"'s suite, run after the failure, is **red** on `%s` — the old code on the new schema. Its last lines:\n\n' "${failed:-a part}"
        printf '```\n%s\n```\n\n' "$(tail -30 "$log" 2>/dev/null)"
      fi
    else
      printf 'Commit and push the fix; sclaude deploys the branch again after you, and that deploy, then the suite against it, is the judge.\n\n'
    fi
  else
  printf '**The %s regression failed on `%s`.**\n\n' "$stage" "${failed:-a part}"
  if [[ "$rolled" == "done" && "$kept" != "$log" ]]; then
    printf 'That run'"'"'s full output is kept at `%s` — read it rather than\n' "${kept#$wt/}"
    printf '`.sclaude/local/feature/regression.log`, which now holds the check made *after* the\n'
    printf 'rollback, against the previous release. Its last lines:\n\n'
  else
    printf 'The full output is in `.sclaude/local/feature/regression.log`; its last lines:\n\n'
  fi
  printf '```\n%s\n```\n\n' "$(tail -30 "$kept" 2>/dev/null)"
  # Where the earlier runs are, and which of them are this failure's.
  local since; since="$(log_red_since "$wt" regression.log "$stage:")"
  printf 'Every run keeps its own log under `.sclaude/local/feature/logs/`, named by when it began: '
  printf '`regression/` (`<stage>_<date>_<time>.log`; `regression.log` is the latest), and the servers the suites ran against, '
  printf '`e2e-server/` and `dev/`. `regression/runs.tsv` lists each run'"'"'s file, outcome and set (stage and parts). '
  if [[ -n "$since" ]]; then
    printf 'This set went red with `%s`: that log and the ones after it on the same set are this failure'"'"'s runs, ' "$since"
    printf 'and the server logs of the same times beside them — compare what failed in each, since a spec red in every one is no flake. '
    printf 'Anything older can be skipped.'
  fi
  printf '\n\n'
  local reason; reason="$(state_get "$state" "regression.$stage.reason" 2>/dev/null || true)"
  [[ -n "$reason" && "$reason" != "null" ]] && printf '### The reason given\n\n%s\n\n' "$reason"
  fi
  # A merged pull request cannot be reopened, so the fix needs a new one — from
  # this same branch. sclaude follows the feature by the branch its state
  # names: the PR it records, whether that PR is merged, what the preview
  # deploys. A fix on a branch of another name is one it never sees, and it
  # reads the old branch as merged and walks the fix past preview and QA.
  # after_step refuses a review that ends on another branch.
  if [[ "$stage" == "prod" || "$merged" == "MERGED" ]]; then
    if [[ "$stage" == "prod" ]]; then
      printf 'This failed against production, and the feature'"'"'s pull request #%s is already merged. ' "$pr"
    else
      # A preview can go red after the merge: the human may merge while the
      # review step is still open. The review prompt below then describes the
      # pull request as open, and a session believing it pushes to a dead branch.
      printf 'The feature'"'"'s pull request #%s is already merged, whatever the step prompt below says about it being open. ' "$pr"
    fi
    printf 'Do not commit to `main`, and stay on this branch: merge a fresh `origin/main` into it, '
    printf 'commit the fix, push, and open a new pull request from this same branch%s. ' \
      "${issue:+ carrying \`Closes #$issue\`}"
    printf 'The merged one cannot be reopened, and the orchestrator follows the feature by '
    printf 'this branch'"'"'s name — a fix on a branch of another name is one it never sees.\n\n'
  fi
  if [[ "$rolled" == "done" ]]; then
    cat "$PROMPTS/_rollback-fix.md" 2>/dev/null
    printf '\n'
  fi
  [[ "$mode" == "gate" && -z "$dfail" ]] && cat "$PROMPTS/_regression-fail.md" 2>/dev/null
  return 0
}

# Raises the session that fixes a failed run.
#
# A new session every time rather than a resume: a failure is a fresh task with
# a log to read, and resuming the step's own conversation would drop it into a
# context that believes it has already finished. The step's session id in the
# state is deliberately left alone — this session is not the step.
#
# No question before it. The human has just watched the run fail; asking
# "shall I fix it?" is asking whether they meant what the gate already decided.
regression_fix() {
  local wt="$1" slug="$2" stage="$3"
  local state="$wt/.sclaude/local/feature/state.json"
  local step model effort mode session prompt pr issue
  local -a extra

  step="$(regression_fix_step "$stage")"
  [[ -f "$PROMPTS/$step.md" ]] || return 1

  pr="$(state_get "$state" pr 2>/dev/null || true)"
  issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ "$issue" == "null" ]] && issue=""
  # Asked rather than inferred from the stage: regression_fix_block tells the
  # session what a merged pull request means for where the fix goes.
  local merged=""
  if [[ "$stage" != "prod" && -n "$pr" && "$pr" != "null" ]]; then
    merged="$(cd "$wt" && gh pr view "$pr" --json state -q .state 2>/dev/null || true)"
  fi

  model="$(step_model "$step")"
  effort="$(step_effort "$step")"
  mode="$(step_mode "$step")"

  local -x SCLAUDE_B_REGRESSION
  SCLAUDE_B_REGRESSION="$(regression_fix_block "$wt" "$stage" "$merged" gate)"

  local settings
  # 5: not started, for sclaude's own trouble rather than the branch's, so the
  # caller neither counts it as an attempt nor reports a failed fix.
  settings="$(step_settings "$step" "$wt")" \
    || { warn "  The fix was not started: sclaude could not read its rules (see above)."; return 5; }
  mapfile -t extra <<< "$settings"

  # The same part red again after a fix goes back to the session that made the
  # fix: it has just learnt that its guess was wrong, and with its context it
  # knows what it already tried rather than trying it a second time. Another
  # part red is another problem, and gets a session of its own. The limit on
  # attempts is what stops a session from circling one wrong idea — after it
  # the person is asked.
  local failed resume=""
  failed="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
  # A deploy that failed is what the session fixes, not the suite's part.
  local dfail; dfail="$(state_get "$state" "regression.$stage.deploy_failed" 2>/dev/null || true)"
  [[ -n "$dfail" && "$dfail" != "null" ]] && failed="the deploy"
  session="$(state_get "$state" "regression.$stage.fix_session" 2>/dev/null || true)"
  if [[ -n "$failed" && "$failed" != "null" \
        && "$(state_get "$state" "regression.$stage.fix_for" 2>/dev/null || true)" == "$failed" ]] \
     && live_session "$wt" "$session" >/dev/null; then
    resume=1
    echo ""
    # Not "after its fix": the session may have ended on a note instead.
    info "  Still red on $failed — back to the same session."
    ask_feed say "$(phase_line resumed fix "$stage" "$failed") · still red on the same part"
  else
    session="$(new_session_id)"
    echo ""
    info "  Opening a session in step '$(step_title "$step")' to fix it."
    ask_feed say "$(phase_line started fix "$stage" "$([[ "$failed" != "null" ]] && echo "$failed")")"
  fi
  state_set "$state" "regression.$stage.fix_session" "$session"
  state_set "$state" "regression.$stage.fix_for" "${failed:-null}"

  # The fixing session's id, recorded so the issue's summary can name it.
  #
  # Deliberately not in `steps.<name>.session`: that field is the step's own
  # conversation, and the orchestrator resumes by it. A fix is a separate
  # conversation about the same step, so it goes beside the stage it belongs
  # to — and the summary prints it as a line of its own rather than in the
  # table, where it would read as though the step had been restarted.
  #
  # Space-joined rather than a JSON list: state_set writes scalars, coercing
  # digits and true/false/null, and a list is not among the shapes it can put
  # in. A string of ids is the representation it can carry unharmed.
  local fixes
  fixes="$(state_get "$state" "regression.$stage.fixes" 2>/dev/null || true)"
  state_set "$state" "regression.$stage.fixes" "${fixes:+$fixes }${session:0:8}"
  # Its name: the row it takes in `fixes`, the number run_friction keys by.
  local name
  name="$(session_label fix "fix-$stage-$(( $(printf '%s' "$fixes" | wc -w) + 1 ))")/$slug"

  # And an outcome beside the id, opened as `open`.
  #
  # Written before the session runs rather than after it, for the same reason
  # the id is: a session interrupted halfway leaves the row saying what is true
  # of it — there is a conversation to return to — instead of nothing. The
  # endings below overwrite it.
  fix_status_set "$state" "$stage" open append
  # And the session's own times, in the same shape. The summary used to show
  # the friction review's times on this row, which left a session whose review
  # had nothing to read with no times at all. `-` holds the end's place until
  # the session exits, so an interrupted one keeps the words aligned.
  # A feature that already had sessions before these fields existed gets a
  # `-` for each, so the words stay aligned with `fixes` by position.
  if [[ -z "$(state_get "$state" "regression.$stage.fix_started" 2>/dev/null || true)" ]]; then
    local older
    older="$(( $(printf '%s' "$fixes" | wc -w) ))"
    while [[ "$older" -gt 0 ]]; do
      fix_word_set "$state" "$stage" fix_started - append
      fix_word_set "$state" "$stage" fix_finished - append
      older=$((older - 1))
    done
  fi
  fix_word_set "$state" "$stage" fix_started "$(date -Iseconds)" append
  fix_word_set "$state" "$stage" fix_finished - append
  # A note left by a session before is not this one's finding, and is taken
  # off only now that a session is opening: one that never starts (its rules
  # unreadable, its prompt missing) leaves it for the next start's question.
  history_add "$state" "fix.$stage" start session="$session"
  blocked_note_keep "$wt" "$stage" "a fixing session opened"
  session_watch_start "$wt" "$session"
  if [[ -n "$resume" ]]; then
    # One wording for a session that ended on a fix and one that ended on a
    # note: which it was is not kept once an orchestrator fix overwrites the
    # status, and the session knows anyway.
    prompt="$(printf '**The %s %s again.** If you ended last time on a note, it was taken off: write `.sclaude/local/feature/regression.blocked` again if the cause is still outside this tree, or this session ends as a fix that did not hold.\n\n%s\n\n%s\n' \
      "$stage" "$([[ "$failed" == "the deploy" ]] && echo "deploy failed" || echo "regression ran again and failed on the same part")" \
      "$(marker_gone .sclaude/local/feature/session-done)" "$SCLAUDE_B_REGRESSION")"
    ( cd "$wt" && dev_env_load "$wt" && claude_launch --resume "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$name" "$prompt" )
  else
    prompt="$(render_prompt "$step" "$slug" "$pr" "$issue" "$wt")"
    ( cd "$wt" && dev_env_load "$wt" && claude_launch --session-id "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$name" "$prompt" )
  fi
  session_watch_stop
  fix_word_set "$state" "$stage" fix_finished "$(date -Iseconds)"
  history_add "$state" "fix.$stage" end session="$session"

  # The session said its fix is in and the watcher closed it; the gate's next
  # run is the judge. Its report is printed here, since claude's screen went
  # with it. See done_marker.
  session_closed "$(done_marker "$wt")" "$wt" "$session" "" "" \
    fix "$stage" "$([[ "$failed" != "null" ]] && echo "$failed")" || true

  # A session that exited at the door leaves no assistant record, and the row
  # should say so rather than carry an id nobody can resume. The wall clock is
  # not asked: it times the wrapper, and a session that died on entry can spend
  # seven seconds doing it — which is how this feature got a `fix-preview-3` of
  # 0.2 seconds marked done. The transcript is the honest witness.
  session_started "$wt" "$session" || fix_status_set "$state" "$stage" stalled

  # And the friction review for the session that has just ended.
  #
  # A fixing session runs into missing tools exactly as a step does — it is
  # reading a regression log and trying to reproduce a failure, which is the
  # kind of work a ban gets in the way of. Its entries used to have nowhere to
  # go: the reviews after each step all happen earlier in the cycle, and the
  # deployed stages run inside remind_prod, after the last of them. Nothing
  # would have picked these up before cmd_done removed the tree.
  #
  # One review per fixing session, keyed by that session's place in `fixes`.
  #
  # NOT by `regression.<stage>.attempts`, which is what this did first and got
  # wrong. That counter is a limit, not an identifier: it is reset to zero in
  # three places — by a green run (regression_gate), by `sclaude reset`, and on
  # entering step 4, which clears the local stage's. `fixes` only ever grows.
  # So a stage that went red, was fixed, went green and went red again wrote
  # both reviews to `fix-<stage>-1`: the second overwrote the first, and the
  # summary — which numbers the rows by position in `fixes` — then looked up a
  # `fix-<stage>-2` that did not exist. Row one showed the second review's
  # times against the first session's id, and row two claimed no review had
  # happened when one had.
  #
  # Counting the position here makes the writer and the reader derive the key
  # from the same thing, so no reset of the counter can pull them apart.
  #
  # An empty log means no session, by run_friction's own emptiness check: a
  # fixing session that hit no obstacle is the ordinary case, and a review with
  # nothing to read costs a launch for nothing.
  local number
  number="$(state_get "$state" "regression.$stage.fixes" 2>/dev/null || true)"
  number="$(printf '%s' "$number" | wc -w)"
  [[ "$number" =~ ^[0-9]+$ && "$number" -ge 1 ]] || number=1
  run_friction "$wt" "$slug" "fix-$stage-$number" || true

  # The friction review changed the orchestrator. A cause "outside this branch"
  # is very often the orchestrator itself — once a preview e2e ran with
  # the worktree's local database because of how sclaude wired the environment,
  # and the review right here fixed exactly that. Stopping with "blocked" and
  # "carry on with sclaude <feature>" then hands the human an errand the machine
  # can do: the note's cause may be gone, and the only way to know is to run the
  # stage again. 4 says so to the gate, which re-runs with the new code.
  #
  # The note goes: it described the state before the fix, and left in place it
  # would stop the next run with "has that been dealt with?" about a cause the
  # fix was for. If the fix did not help, the next red run writes a new one.
  if [[ "$(state_get "$state" "friction.fix-$stage-$number.fixed" 2>/dev/null || true)" == "true" ]]; then
    blocked_note_keep "$wt" "$stage" "the friction review changed sclaude"
    return 4
  fi

  # A session that found the cause outside this tree leaves a note rather than a
  # commit, and that is a third outcome — neither "fixed" nor "failed to fix".
  #
  # Without it such a session has no sanctioned way to end: the prompt above
  # tells it to fix the cause and re-run, so a session that correctly concludes
  # "the deployment points at a different bucket, nothing here to change" spends
  # its last turns arguing that it should be allowed to close. Then the gate
  # counts the attempt and answers the argument with an identical run.
  #
  # 3 says so to the gate, which stops without spending the attempt.
  [[ -s "$wt/.sclaude/local/feature/regression.blocked" ]] && return 3
  return 0
}
