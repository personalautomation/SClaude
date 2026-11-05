#!/usr/bin/env bash
#
# A feature's outcome: the deploy and regression labels on its pull request,
# the line `sclaude status` prints about it, and the epilogues offered.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- a feature's outcome -----------------------------------------------------
#
# A closed sub-issue changes an epic's state, but the epic says nothing about it:
# to understand where it stands, the children had to be opened one by one. One
# has ten of them. A "Current status" section in the description at every level
# of the chain removes that walk.

# A deployment label, created on demand.
#
# This repository has three labels today — Design, Marketing, Dev — and no
# deployed-* at all. We create them ourselves, and `--force` makes that
# idempotent: if the label already exists, its colour and description are updated
# rather than an error being raised.
#
# It breaks nothing: no permission for labels and we stay quiet and carry on. The
# section in the description does not depend on the labels, and there is no
# reason to lose it because of them.
ensure_deploy_label() {
  local repo="$1" name="$2" color="$3" desc="$4"
  gh label create "$name" --repo "$repo" --color "$color" \
     --description "$desc" --force >/dev/null 2>&1 || true
}

# The labels go onto the whole chain: onto the issue itself and onto every
# parent.
#
# A parent needs the label no less: an epic is read to understand what of it is
# already in prod, and the answer "part of it, yes" is the one being looked for.
# The qualifications about which part exactly are carried by the "Current status"
# section — that is what it is prose for.
#
# We only add and never remove: a label is a trace of where the work has been,
# and removing one would argue with a human who put it there by hand. That holds
# for every label this function is given — which in practice is `deployed-*`, the
# ones a person is most likely to have applied themselves after shipping without
# us. The one label that does come off again is cleared by
# clear_regression_label below, and the reason it is allowed to is written there.
apply_deploy_labels() {
  local repo="$1" labels="$2" numbers="$3" number name
  for number in $numbers; do
    for name in $labels; do
      gh issue edit "$number" --repo "$repo" --add-label "$name" \
        >/dev/null 2>&1 \
        || warn "  could not label issue #$number with $name"
    done
  done
}

# The red mark on a stage whose regression failed, taken off again when it passes.
#
# This is the only place in the repository that removes a label, and it is worth
# saying why the rule above does not reach it. `deployed-*` is a statement about
# where the work went, and it stays true for ever: the code did reach that
# hosting on that day, and a person may well have put the label there by hand.
# `<stage>-regression-red` is a statement about right now — the suite against
# that deployment fails — and it stops being true the moment the suite passes.
# The script is the only author of it, from a machine-readable result, and it is
# the only reader that has to undo it.
#
# A mark that says "broken" and cannot be cleared is worse than no mark at all:
# it would still be sitting on the epic a year after the fix shipped, and every
# reader after the first would have to open the issue to find out that it lies.
#
# It comes off the whole chain, because that is where it went on. Quiet on
# failure, like every other label call here: a green regression must not be
# reported as a failure because gh could not edit an issue.
clear_regression_label() {
  local repo="$1" stage="$2" numbers="$3" name number

  name="$(regression_red_label "$stage")" || return 0
  [[ -n "$name" ]] || return 0

  for number in $numbers; do
    gh issue edit "$number" --repo "$repo" --remove-label "$name" \
      >/dev/null 2>&1 || true
  done
}

# The name of a stage's red label, and the single place that knows it.
#
# Three callers need it — the two that apply it and the one that clears it — and
# a fourth copy of the string is how the pair would drift apart: a label set
# under one spelling and cleared under another is never cleared at all. `local`
# has none, deliberately: it is not a deployment, nobody can open it, and the
# section already says where the work was checked.
regression_red_label() {
  case "$1" in
    preview) printf 'preview-regression-red' ;;
    prod)    printf 'prod-regression-red' ;;
    *)       return 1 ;;
  esac
}

# How the deployment ended, as prose for the prompt.
#
# The session must not work this out itself: preview and prod are blocks the
# human answered a minute ago, and their outcome is known exactly. Guessing from
# the repository whether it "made it" would be more expensive and worse.
status_outcome() {
  local pr="$1" merged="$2" preview="$3" prod="$4" preview_red="${5:-0}" prod_red="${6:-0}"
  local pr_text

  # A feature with no change of its own (no_change.sh) has no pull request,
  # and nothing of it was deployed: "Pull request #null" would be the sentence.
  if [[ -z "$pr" || "$pr" == "null" ]]; then
    echo "There was no pull request: the feature left no change of its own in this repository, so nothing was merged or deployed here. What it did is in the issue's comments — its plan and its step reports; work done outside this repository is named there too."
    return 0
  fi

  if [[ "$merged" == "MERGED" ]]; then
    pr_text="Pull request #$pr is merged; branch and worktree are gone."
  else
    pr_text="Pull request #$pr is not merged yet — the merge is mine to do."
  fi

  if [[ "$prod" == "1" ]]; then
    echo "$pr_text Preview deployed, prod deployed — the feature is in production."
  elif [[ "$prod_red" == "1" && "$preview" == "1" ]]; then
    # Production shipped and its suite failed against it. Both halves belong in
    # the sentence: the preview is genuinely green — its own regression passed,
    # or this line would never have been reached — and `deployed-preview` stands
    # on that. What does not stand is a reader's assumption that production
    # works, and the label cannot hold the qualifier, so the words do.
    #
    # Above the preview branches rather than below them, and that ordering is
    # the whole of this case: left under `preview == "1"` it would come out as
    # "prod postponed", which is the exact lie the branch exists to remove.
    echo "$pr_text Preview deployed and green; prod deployed, but the regression against it is red — production is live and broken, and a fix is on its way through the review."
  elif [[ "$prod_red" == "1" ]]; then
    # The same event with no preview of our own this run: a feature resumed
    # after the merge, or a preview skipped because that tree is already up
    # there. There is nothing green to point the reader at, so the sentence does
    # not invent one.
    echo "$pr_text Prod deployed, but the regression against it is red — production is live and broken, and a fix is on its way through the review."
  elif [[ "$preview" == "1" && "$merged" == "MERGED" ]]; then
    echo "$pr_text Preview deployed, prod postponed — the feature is not in production yet."
  elif [[ "$preview" == "1" ]]; then
    echo "$pr_text Preview deployed; there was no prod deploy, and there cannot be one before the merge."
  elif [[ "$preview_red" == "1" ]]; then
    # The deploy happened and the suite failed against it, so neither of the
    # two sentences below is true: "nothing was deployed" is wrong, and the
    # ones above claim a preview that works. It is a separate case because it
    # is the only one where the code is somewhere and that somewhere is broken
    # — and it carries no label, deliberately: prose can hold the qualifier,
    # `deployed-preview` cannot.
    echo "$pr_text Preview deployed, but the regression against it is red — the feature is not ready to merge, and there is no prod deploy."
  elif [[ "$merged" == "MERGED" ]]; then
    echo "$pr_text Neither preview nor prod was deployed this time."
  else
    echo "$pr_text Nothing was deployed at all: the work is awaiting merge."
  fi
}

# A feature's outcome — into its issue and into every parent.
#
# In a separate session rather than as a template in the script: "where this epic
# stands now" is a judgement, not a substitution. The script assembles the chain,
# the percentages and the labels itself and hands them over ready; writing two
# sentences that need no re-checking is beyond it.
#
# Not as a cycle step: by this minute the feature's worktree has been removed
# along with state.json — there is nowhere to record the step's completion, and
# a `cd "$wt"` would no longer work. In its construction this is closest to the
# friction review: a session outside STEPS, with a prompt of its own, launched
# from the main repository.
#
# It breaks nothing: no issue, no gh, no network and we exit silently. There is
# nothing to warn about: this is the end of a successful cycle, and a yellow line
# would read as a failure.
# An unclosed epilogue is offered when the menu opens.
#
# It is the only thing that was not picked up by itself. A feature in progress
# has a worktree, it is visible in the menu, and `sclaude <feature>` sees
# everything that is left through to the end. A closed one has nothing: the tree
# is removed, it has left the menu — and an interrupted epilogue would lie in
# .sclaude/epilogue for as long as you like while the section in the issue stayed
# as it was all that time. The only way back was a command one had to remember.
#
# So we ask here, next to the branch review: the same place, the same occasion —
# a clean-up before the work rather than in the middle of it — and the same form
# of question.
#
# We ask rather than do it silently: this opens a model session, and doing so
# unasked means spending somebody's money on what the human did not ask for
# right now. A refusal spoils nothing — we will offer again next time, and the
# state is in place.
offer_epilogues() {
  local rows; rows="$(pending_epilogues)"
  [[ -n "$rows" ]] || return 0

  local slug file issue started answer table=""
  echo ""
  echo "${BOLD}Unfinished epilogue:${OFF}"
  while IFS=$'\t' read -r slug file; do
    [[ -n "$slug" ]] || continue
    issue="$(state_get "$file" issue || echo "?")"
    started="$(state_get "$file" started || true)"
    table+="  $slug"$'\t'"issue #$issue, broke off $(epilogue_age "$started")"$'\n'
  done <<< "$rows"
  align_columns "$table"

  echo ""
  ask "Finish it now? [y/n] " answer yn
  is_yes "$answer" || { info "Left as it is — it will be offered again."; return 0; }

  # We gather the names into an array and only then launch. This cannot be done
  # with a loop over a here-string: a nested command inherits the loop's stdin,
  # that is the same list — and claude, instead of a terminal, gets the remaining
  # lines as input, runs into EOF and exits immediately. The five-second
  # threshold would take that for "it did not start", the state would stay
  # waiting, and the menu would offer the same thing again and again while
  # agreeing changed nothing.
  local -a slugs=()
  while IFS=$'\t' read -r slug file; do
    [[ -n "$slug" ]] || continue
    slugs+=("$slug")
  done <<< "$rows"

  for slug in "${slugs[@]}"; do
    cmd_epilogue "$slug" || true
  done
}

# What the epilogue last wrote, as one line: the commit plus the outcome it
# described. Both halves are needed. The commit alone would skip the update that
# says "now in production" — a prod deploy can follow a preview without main
# moving. The outcome alone would miss new commits under an unchanged verdict.
status_fingerprint() {
  local wt="$1" pr="$2" merged="$3" preview="$4" prod="$5" sha
  sha="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)" || sha=""
  [[ -n "$sha" ]] || return 1
  printf '%s %s %s %s %s' "$sha" "${pr:-}" "${merged:-}" "$preview" "$prod"
}

# The seventh argument is the feature's worktree, and it is optional: the
# epilogue's own memory lives in that tree's state.json, so a caller without one
# — cmd_epilogue, resuming a feature whose tree is already cleaned up — simply
# keeps no record (with the tree still there, it passes it). That costs nothing there: a cleaned-up feature is reached
# only by naming it, never by the menu offering it.
# The issue chain says the preview is red, from a stop before (run_status
# records it): green now, the status is written again rather than left wrong
# for the whole of QA and the merge — on every green pass until a session has
# written it.
#
#   status_green_again <slug> <issue> <pr> <merged> <wt>
status_green_again() {
  [[ "$(state_get "$5/.sclaude/local/feature/state.json" status.preview_red 2>/dev/null || true)" == true ]] \
    || return 0
  run_status "$1" "$2" "$3" "$4" 1 0 "$5"
}

run_status() {
  local slug="$1" issue="$2" pr="$3" merged="$4" preview="$5" prod="$6" wt="${7:-}"
  # The eighth is the red preview, and it is deliberately not folded into
  # `preview`: that argument decides the labels, and a red run must not produce
  # one. This says the deploy happened anyway, which only the prose needs.
  local preview_red="${8:-0}"
  # The ninth is the same for production, and it is a second flag rather than a
  # stage name in the eighth because the two are not alternatives: a red prod
  # leaves `preview` standing at 1 on its own green evidence, and one argument
  # holding "which stage is red" would have nothing to say about the stage that
  # is not. Unlike the eighth, this one does reach the labels — it is what adds
  # the red mark — but neither of them touches the two `deployed-*` lines.
  local prod_red="${9:-0}"
  local repo labels="" numbers prompt fingerprint=""

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  [[ -f "$PROMPTS/status.md" ]] || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  # The epilogue is a model session that rewrites a section in the issue and
  # in every parent. Run again over an unchanged situation it spends money to
  # produce the same paragraphs — so when the fingerprint matches what was
  # written last time, we say so and stop. The labels below are not reapplied
  # either: they were applied in that same run, from these same values.
  # Red words still standing over a green preview are not "this", whatever the
  # fingerprint says.
  if [[ -n "$wt" ]]; then
    fingerprint="$(status_fingerprint "$wt" "$pr" "$merged" "$preview" "$prod" || true)"
    if [[ -n "$fingerprint" ]] \
       && [[ "$fingerprint" == "$(state_get "$wt/.sclaude/local/feature/state.json" status.fingerprint 2>/dev/null || true)" ]] \
       && [[ "$preview_red" == 1 || "$(state_get "$wt/.sclaude/local/feature/state.json" status.preview_red 2>/dev/null || true)" != true ]]; then
      echo ""
      info "The status in issue #$issue already describes this — nothing changed, skipping."
      info "  To write it again anyway: $SELF epilogue $slug"
      return 0
    fi
  fi

  # The labels alone (STATUS_LABELS_ONLY, the merge's wait): no walk of the
  # chain when none is earned.
  [[ -n "${STATUS_LABELS_ONLY:-}" && "$preview$prod$preview_red$prod_red" != *1* ]] && return 0

  # issue_chain.py computes the chain — the same walk that will go into the
  # prompt. There is deliberately no copy of our own on gh+jq here: two walks
  # would diverge, and the labels would land somewhere other than the text. If
  # the gathering did not work, we at least label the issue itself.
  numbers="$(python3 "$LIB/issue_chain.py" --numbers "$issue" "$REPO" 2>/dev/null)" \
    || numbers=""
  [[ -n "$numbers" ]] || numbers="$issue"

  # If prod is shipped then preview stands behind it: the code travelled further
  # than there. The converse is not true, and there will be no prod label when
  # the deployment is postponed.
  [[ "$preview" == "1" || "$prod" == "1" ]] && labels="deployed-preview"
  [[ "$prod" == "1" ]] && labels="${labels:+$labels }deployed-prod"

  # The red marks are kept apart from the two above rather than joined to them,
  # because they are a different kind of claim and have a different life. A
  # `deployed-*` is permanent and says where the work went; a red mark says the
  # suite against that deployment fails today, and clear_regression_label takes
  # it off when the suite passes. Joining them into one string would work right
  # up to the moment somebody cleared the wrong half.
  local marks=""
  [[ "$preview_red" == "1" ]] && marks="$(regression_red_label preview)"
  [[ "$prod_red" == "1" ]] && marks="${marks:+$marks }$(regression_red_label prod)"

  # The script sets the labels rather than the session: there is nothing to
  # decide here — the same principle by which the orchestrator assembles a step's
  # context.
  #
  # deployed-locally is deliberately not created, even though the issue names
  # it. It would be true of every issue from the start of step 2 while
  # `next dev` is alive, and false the moment the laptop is closed: such a
  # label's meaning is decided by somebody else's process on one machine. And it
  # is not a deployment — nobody but the machine's owner can open it. The section
  # itself says where the work was checked locally.
  if [[ -n "$labels" ]]; then
    ensure_deploy_label "$repo" deployed-preview fbca04 \
      "On a Vercel preview deployment, not yet in production"
    [[ "$prod" == "1" ]] && ensure_deploy_label "$repo" deployed-prod 0e8a16 \
      "Live in production"
    apply_deploy_labels "$repo" "$labels" "$numbers"
  fi

  # The red marks go on through the same function: applying is applying, and the
  # asymmetry between these and the `deployed-*` pair is in the clearing, which
  # happens elsewhere entirely.
  if [[ -n "$marks" ]]; then
    [[ "$preview_red" == "1" ]] \
      && ensure_deploy_label "$repo" "$(regression_red_label preview)" b60205 \
         "Deployed to preview, but the regression against it is red"
    [[ "$prod_red" == "1" ]] \
      && ensure_deploy_label "$repo" "$(regression_red_label prod)" b60205 \
         "Deployed to production, but the regression against it is red"
    apply_deploy_labels "$repo" "$marks" "$numbers"
  fi
  # The labels alone, no session: where the words need no rewriting
  # (remind_prod's merge wait).
  [[ -n "${STATUS_LABELS_ONLY:-}" ]] && return 0

  # What the session is told when no `deployed-*` label was earned. Said rather
  # than left blank: "none" alone would have it guess why, and a deploy that
  # happened and then failed its suite is the case where the reason is not the
  # obvious one.
  #
  # Below the label lines rather than above them, because it has to know whether
  # anything survived — a red prod keeps `deployed-prod` and never reaches here
  # at all, which is why only the preview case has a sentence of its own.
  local no_labels="none: neither preview nor prod was deployed"
  [[ "$preview_red" == "1" ]] \
    && no_labels="none: the preview deploy happened, but its regression is red, so it gets no label"
  # A red prod always keeps `deployed-prod`, so this line is unreachable today.
  # It is here because the sentence above would be a lie if it ever stopped
  # being unreachable, and a lie in the one place the session has no way to
  # check: it is told what the labels say and writes prose to match.
  [[ "$prod_red" == "1" ]] \
    && no_labels="none: the prod deploy happened, but its regression is red, so it gets no label"
  # The marks are named either way: they are not `deployed-*`, so they never fill
  # the blank, but a session told "labels: none" while a red mark sits on the
  # issue would be describing a different issue than the reader is looking at.
  [[ -n "$marks" ]] && no_labels="$no_labels (the issue does carry $marks)"

  # What the session is actually told. One variable rather than three nested
  # substitutions on the line below: the rule is "every label that went on, or
  # the sentence explaining why none did", and that reads as two branches
  # because it is two branches.
  local said
  if [[ -n "$labels" ]]; then
    said="$labels${marks:+ $marks}"
  else
    said="$no_labels"
  fi

  # The commits that are actually on hosting, for the section to name.
  #
  # The section is the only record that outlives the feature: state.json goes
  # with the worktree minutes from now, and with it every trace of which commit
  # this was. A label cannot carry a sha and prose can, and a reader a month
  # later can check the claim — `git rev-parse main` against what is written —
  # instead of taking a boolean on trust.
  #
  # Empty when there is no worktree to read: cmd_epilogue resumes a feature whose
  # tree is already gone, and a shortened nothing is still nothing. The prompt
  # says what to do with an empty value.
  local shas="" psha dsha
  if [[ -n "$wt" ]]; then
    psha="$(state_get "$wt/.sclaude/local/feature/state.json" deploy.preview.sha 2>/dev/null || true)"
    dsha="$(state_get "$wt/.sclaude/local/feature/state.json" deploy.prod.sha 2>/dev/null || true)"
    [[ -n "$dsha" && "$dsha" != "null" ]] \
      && shas="production: $(git -C "$REPO" rev-parse --short "$dsha" 2>/dev/null || echo "$dsha")"
    [[ -n "$psha" && "$psha" != "null" ]] \
      && shas="${shas:+$shas; }preview: $(git -C "$REPO" rev-parse --short "$psha" 2>/dev/null || echo "$psha")"
  fi
  [[ -n "$shas" ]] || shas="not recorded"

  # The epilogue closes itself once its comments are written: it writes this
  # file before its report, and the watcher ends the session (see
  # session_watch_start). Outside the repository and outside ~/.claude, where
  # a session in auto mode writes without being asked, and named after the
  # feature so a resumed epilogue is told the same path.
  local done_file="${TMPDIR:-/tmp}/sclaude-epilogue-$slug.done"

  # The pull request's number for the prompt to name in commands, and empty
  # when there is none. Not <pr>: render_prompt fills that with a dash when
  # there is no PR, so a conditional on it never drops and the session was
  # told to run `gh pr diff —`.
  local pr_number="$pr"
  [[ "$pr_number" == "null" ]] && pr_number=""

  prompt="$(SCLAUDE_V_DEPLOY_SHAS="$shas" \
            SCLAUDE_V_PR_NUMBER="$pr_number" \
            SCLAUDE_V_DONE_MARKER="$done_file" \
            SCLAUDE_B_DEPLOY_OUTCOME="$(status_outcome "$pr" "$merged" "$preview" "$prod" "$preview_red" "$prod_red")" \
            SCLAUDE_V_LABELS="$said" \
            render_prompt status "$slug" "$pr" "$issue" "")" || return 0
  [[ -n "$prompt" ]] || return 0

  # In the feature's worktree, as every other step: its transcript is then
  # where the process map reads the feature's conversations. The main checkout
  # only when the tree is already gone — a resumed epilogue after the
  # clean-up, which then starts afresh rather than resume a conversation kept
  # under the other directory.
  local cwd="$REPO"
  [[ -n "$wt" && -d "$wt" ]] && cwd="$wt"

  echo ""
  echo "${BOLD}${BLUE}── $slug · $(phase_title epilogue): the status into issue #$issue and its parents ──${OFF}"
  info "   sonnet / medium / auto · $cwd"
  info "   chain: $(tr '\n' ' ' <<< "$numbers")${labels:+ · labels: $labels}"
  echo ""

  # Our own state goes outside the feature's tree: an epilogue finished later
  # may find the tree gone, and .sclaude/local/feature/state.json with it. The details are in
  # epilogue_state (state.sh).
  #
  # We name the session ourselves and write the id BEFORE launching: otherwise an
  # interrupted epilogue is lost entirely — the feature is closed, the menu will
  # not show it, and the section in the issue silently stays as it was.
  local estate session
  estate="$(epilogue_state "$slug")" || estate=""
  if [[ -n "$estate" ]]; then
    session="$(state_get "$estate" session || true)"
    if [[ -n "$session" ]] && ! live_session "$cwd" "$session" >/dev/null; then
      session=""
    fi
    # An interrupted one about another preview (red, now green) is not
    # taken up: its words are the old ones.
    [[ -n "$session" && "$(state_get "$estate" preview 2>/dev/null || true)$(state_get "$estate" preview_red 2>/dev/null || true)" \
        != "$preview$preview_red" ]] && session=""
  fi

  local settings
  settings="$(status_settings)" \
    || { warn "  The status session was not started: sclaude could not read its rules (see above)."; return 1; }
  local -a extra; mapfile -t extra <<< "$settings"
  # Past every reason not to start: the topic hears of a start that happens.
  local verb=started
  [[ -n "$estate" && -n "${session:-}" && "$session" == "$(state_get "$estate" session 2>/dev/null || true)" ]] \
    && verb=resumed
  ask_feed say "$(phase_line "$verb" epilogue) · writes the status into issue #$issue"

  # Every claude conversation belongs in the issue's table, the epilogue's
  # included. Recorded in the feature's state while there is one; the id is
  # named in advance even when there is no epilogue state, so the row has one.
  local fstate=""
  [[ -n "$wt" && -f "$wt/.sclaude/local/feature/state.json" ]] && fstate="$wt/.sclaude/local/feature/state.json"
  [[ -n "${session:-}" ]] || session="$(new_session_id)"
  # Before the merge a status is the preview's (red, or written again green):
  # the history says so, and the map plays it beside the preview.
  local about=""
  [[ -n "$pr" && "$pr" != null && "$merged" != MERGED ]] && about=preview
  [[ -n "$fstate" ]] && SCLAUDE_ABOUT="$about" session_runs "$fstate" epilogue open "$session"

  session_watch_start "" "$session" "$done_file" "$cwd"
  if [[ -n "$estate" && "$session" == "$(state_get "$estate" session 2>/dev/null || true)" ]]; then
    info "   resuming the interrupted epilogue"
    ( cd "$cwd" && claude_launch --resume "$session" --model sonnet --effort medium \
        --permission-mode auto "${extra[@]}" -n "$(session_label epilogue)/$slug" \
        "Back in the epilogue for feature '$slug'. Pick up where the conversation left off." )
  else
    if [[ -n "$estate" ]]; then
      state_set "$estate" session "$session"
      state_set "$estate" issue "$issue"
      state_set "$estate" started "$(date -Iseconds)"
      state_set "$estate" done false
      # The deployment's outcome goes into the state too, and that is no luxury:
      # otherwise there is nothing to assemble a resumed epilogue from. It writes
      # "where the feature is now" into the issue, and that is exactly these four
      # values; without them they would have to be invented, and the invention
      # would travel into the issue as fact.
      state_set "$estate" pr "${pr:-}"
      state_set "$estate" merged "${merged:-}"
      state_set "$estate" preview "$preview"
      state_set "$estate" prod "$prod"
      state_set "$estate" preview_red "$preview_red"
      ( cd "$cwd" && claude_launch --session-id "$session" --model sonnet --effort medium \
          --permission-mode auto "${extra[@]}" -n "$(session_label epilogue)/$slug" "$prompt" )
    else
      # The state could not be created — we write the epilogue anyway: the
      # section in the issue matters more than the ability to return to an
      # interrupted session.
      ( cd "$cwd" && claude_launch --session-id "$session" --model sonnet --effort medium \
          --permission-mode auto "${extra[@]}" -n "$(session_label epilogue)/$slug" "$prompt" )
    fi
  fi
  session_watch_stop
  # It said its comments are written, and the watcher closed it: the report is
  # printed here, since claude's screen went with it.
  local written=0
  session_closed "$done_file" "$cwd" "$session" "" "" epilogue && written=1
  # Whether it took place, by the transcript rather than the clock — the
  # witness run_step and run_friction use (session_started, state.sh). The
  # clock timed the wrapper, and the row and the epilogue's own state must not
  # give two answers.
  local ran=0
  session_started "$cwd" "$session" && ran=1

  if [[ -n "$fstate" ]]; then
    if [[ "$ran" -eq 1 ]]; then
      session_runs "$fstate" epilogue finish "$session"
    else
      session_runs "$fstate" epilogue drop "$session"
    fi
    # The row goes into the issue now: the callers return straight after, and
    # the next sync may be days away or never come.
    issue_sync "$wt"
  fi

  # A red run arms the rewrite whether or not its words got written: a session
  # left pending about the red preview is replaced by the green one, rather
  # than finished later with the red words.
  [[ -n "$wt" && "$preview_red" == 1 ]] \
    && state_set "$wt/.sclaude/local/feature/state.json" status.preview_red true 2>/dev/null

  # There used to be a command here that the human had to remember and type
  # themselves. Now there is nothing to type: the menu itself offers to
  # finish an unclosed epilogue, at the very next launch of sclaude.
  #
  # So the line with the command was removed rather than left "just in case".
  # A hint that describes a different path from the one things will actually
  # take is worse than no hint: the human does extra work and then stops
  # trusting the other hints as well. The command has not gone anywhere — it
  # is in --help — but it is no longer the ordinary path.
  if [[ "$ran" -ne 1 ]]; then
    warn ""
    warn "  The epilogue did not start — the status in issue #$issue is unchanged."
    [[ -n "$estate" ]] && warn "  sclaude will offer to finish it the next time you open the menu."
    return 1
  fi
  if [[ -n "$estate" ]]; then
    # The epilogue took place — its state has done its work and goes. There is
    # no longer a "done" mark on disk: nobody read a closed record, while it
    # would have accumulated a file per completed feature.
    epilogue_forget "$slug"
  fi

  # And the fingerprint of what was just described, so that a return to a
  # finished feature does not pay for these paragraphs twice. Deliberately not
  # in the epilogue's own file: that one is a to-do list, and it is deleted the
  # moment the work is done — which is exactly when this becomes worth keeping.
  # Here it lives in the feature's state, beside the deploys it describes.
  #
  # Only when it ran to the end: the early return above is the "did not start"
  # path, and marking that as written would silence the epilogue for good.
  [[ -n "$fingerprint" && -n "$wt" ]] \
    && state_set "$wt/.sclaude/local/feature/state.json" status.fingerprint "$fingerprint" 2>/dev/null
  # And the red words armed above are cleared only by a green session that
  # said its comments are written (session_closed): one cut off after its
  # first reply leaves the red words standing, and the next green pass tries
  # again (status_green_again).
  [[ -n "$wt" && "$preview_red" != 1 && "$written" -eq 1 ]] \
    && state_set "$wt/.sclaude/local/feature/state.json" status.preview_red null 2>/dev/null
  return 0
}
