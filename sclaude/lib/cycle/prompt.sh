#!/usr/bin/env bash
#
# A step's prompt: sclaude's own text with the gathered blocks put in,
# and what the product and the person add to it.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# A step's prompt lies as a file next to the script; we substitute the feature's
# name and, for the review step, the PR's number. We keep the prompts outside:
# they are edited more often than the logic.
#
# sclaude/lib/cycle/render_prompt.py does the assembling. sed used to do the
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
  local -x SCLAUDE_V_DEFERRED="$(deferred_file "${wt:-${REPO:-.}}" "$slug")"
  local -x SCLAUDE_V_DEV_PORT="3000"
  # The product's manuals as its config names them, for the prompts to say
  # where they are rather than one product's pages.
  local -x SCLAUDE_V_MANUALS
  SCLAUDE_V_MANUALS="$(python3 "$LIB/cycle/manual_names.py" "${wt:-${REPO:-.}}" 2>/dev/null || true)"
  # And its own database, when it has one: the conditional paragraph about it
  # drops out of the prompt otherwise.
  local -x SCLAUDE_V_DB_API=""
  # The shared environment the feature works against, if it is not the local
  # one — the prompt then says what not to do there.
  local -x SCLAUDE_V_SHARED_DB=""
  [[ -n "$wt" ]] && declare -F db_shared_env >/dev/null \
    && SCLAUDE_V_SHARED_DB="$(db_shared_env "$wt" 2>/dev/null || true)"
  if [[ -n "$wt" && -f "$wt/.sclaude/local/feature/state.json" ]]; then
    SCLAUDE_V_DEV_URL="$(dev_address "$wt")"
    SCLAUDE_V_DEV_PORT="$(feature_port "$wt" || echo 3000)"
    local dbbase; dbbase="$(state_get "$wt/.sclaude/local/feature/state.json" db.base 2>/dev/null || true)"
    [[ -f "$wt/.sclaude/local/feature/db.env" && "$dbbase" =~ ^[0-9]+$ ]] \
      && SCLAUDE_V_DB_API="http://127.0.0.1:$((dbbase + 1))"
  fi
  # Where the project's review runs (project_review_mode): step 3 opens the
  # pull request labelled no-review unless it is GitHub's, and step 4 is told
  # when the findings come from this machine rather than from threads.
  local -x SCLAUDE_V_REVIEW_MODE SCLAUDE_V_NO_REVIEW="" SCLAUDE_V_REVIEW_LOCAL=""
  SCLAUDE_V_REVIEW_MODE="$(project_review_mode "$wt")"
  [[ "$SCLAUDE_V_REVIEW_MODE" != "github" ]] && SCLAUDE_V_NO_REVIEW=1
  [[ "$SCLAUDE_V_REVIEW_MODE" == "local" ]] && SCLAUDE_V_REVIEW_LOCAL=1
  # Whether step 2 records a demo (project_demo_mode): <if:demo> in code.md.
  local -x SCLAUDE_V_DEMO=""
  [[ "$(project_demo_mode "$wt")" == on ]] && SCLAUDE_V_DEMO=1
  # A feature built in parts (parts.sh). <if:in-parts> while a part is built:
  # <part> of <parts>, its branch going into <umbrella>, which is <base>, what
  # its pull request and its review are read against. <if:parts-done> once
  # every part is in <umbrella>: step 2 closes on the whole feature, step 3
  # opens its pull request into main, step 4 reads the seams. <base> is main
  # for every other feature. No demo in a part's session: it is the whole
  # feature's, recorded once the parts are in.
  local -x SCLAUDE_V_BASE="main" SCLAUDE_V_PART="" SCLAUDE_V_PARTS="" SCLAUDE_V_PART_TITLE=""
  local -x SCLAUDE_V_UMBRELLA="" SCLAUDE_V_IN_PARTS="" SCLAUDE_V_PARTS_DONE="" SCLAUDE_V_NOT_IN_PARTS=1
  local -x SCLAUDE_V_PARTS_DROPPED=""
  if [[ -n "$wt" && -f "$wt/.sclaude/local/feature/state.json" ]] \
     && declare -F parts_split >/dev/null && parts_split "$wt/.sclaude/local/feature/state.json"; then
    local pstate="$wt/.sclaude/local/feature/state.json"
    SCLAUDE_V_UMBRELLA="$(parts_umbrella "$pstate")"
    SCLAUDE_V_PARTS="$(state_get "$pstate" parts.total)"
    if parts_open "$pstate"; then
      SCLAUDE_V_IN_PARTS=1 SCLAUDE_V_NOT_IN_PARTS=""
      SCLAUDE_V_PART="$(parts_now "$pstate")"
      SCLAUDE_V_PART_TITLE="$(state_get "$pstate" "parts.$SCLAUDE_V_PART.title" 2>/dev/null || true)"
      SCLAUDE_V_BASE="$SCLAUDE_V_UMBRELLA"
      SCLAUDE_V_DEMO=""
    else
      SCLAUDE_V_PARTS_DONE=1
      local dropped; dropped="$(state_get "$pstate" parts.dropped 2>/dev/null || true)"
      if [[ "$dropped" =~ ^[0-9]+$ ]]; then
        SCLAUDE_V_PARTS_DROPPED="$dropped-$SCLAUDE_V_PARTS"
        [[ "$dropped" == "$SCLAUDE_V_PARTS" ]] && SCLAUDE_V_PARTS_DROPPED="$dropped"
      fi
    fi
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
        python3 "$LIB/github/issue_context.py" "$issue" "$wt" 2>/dev/null || true)"
      SCLAUDE_B_MANUAL_TOC="$(python3 "$LIB/cycle/manual_toc.py" "$wt" 2>/dev/null || true)"
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
        python3 "$LIB/cycle/acceptance.py" ${SCLAUDE_V_PART:+--part "$SCLAUDE_V_PART"} "$issue" "$wt" 2>/dev/null || true)"
      # The "User request" comment step 1 keeps. Step 2 adds to it what the
      # human asked for during development: without it that lived only in a
      # commit footer, and the issue went on describing the planned scope.
      [[ -n "$issue" ]] && SCLAUDE_B_USER_REQUEST="$(
        python3 "$LIB/github/issue_context.py" --request "$issue" "$wt" 2>/dev/null || true)"
      ;;
    pr)
      SCLAUDE_B_FEATURE_IN_HISTORY="$(python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from pr_context import feature_in_history
sys.stdout.write(feature_in_history(sys.argv[2], sys.argv[3]))' "$LIB" "$wt" "$SCLAUDE_V_BASE" 2>/dev/null || true)"
      # The same plain list as step 2's. It goes into the pull request for the
      # code's reviewer; the boxes stay in the issue, where QA ticks them.
      [[ -n "$issue" ]] && SCLAUDE_B_ACCEPTANCE="$(
        python3 "$LIB/cycle/acceptance.py" ${SCLAUDE_V_PART:+--part "$SCLAUDE_V_PART"} "$issue" "$wt" 2>/dev/null || true)"
      # Back after the merge, for commits the retrospective left (retro.sh): the
      # feature's pull request is merged, and this one carries only them.
      [[ -n "$wt" ]] && SCLAUDE_B_REOPENED="$(retro_pr_block "$wt" 2>/dev/null || true)"
      ;;
    review)
      [[ -n "$pr" ]] && SCLAUDE_B_PR_CONTEXT="$(
        python3 "$LIB/review/pr_context.py" "$wt" "$pr" "$(gh_repo)" 2>/dev/null || true)"
      # The feature's own pull request after its parts: what is still open on
      # the parts' pull requests, which no session reads any more.
      if [[ -n "$SCLAUDE_V_PARTS_DONE" ]]; then
        local part_prs=() pn ppr
        local last_part="$SCLAUDE_V_PARTS"
        [[ "${dropped:-}" =~ ^[0-9]+$ ]] && last_part=$((dropped - 1))
        for (( pn = 1; pn <= last_part; pn++ )); do
          ppr="$(state_get "$wt/.sclaude/local/feature/state.json" "parts.$pn.pr" 2>/dev/null || true)"
          [[ -n "$ppr" && "$ppr" != null ]] && part_prs+=("$ppr")
        done
        if [[ ${#part_prs[@]} -gt 0 ]]; then
          local parts_open_block
          parts_open_block="$(python3 "$LIB/review/pr_context.py" --parts-threads "$wt" "$(gh_repo)" "${part_prs[@]}" 2>/dev/null || true)"
          [[ -n "$parts_open_block" ]] && SCLAUDE_B_PR_CONTEXT+=$'\n\n'"$parts_open_block"
        fi
      fi
      # The review a production rollback sent the cycle back to. No gate opens
      # it, so nobody else fills the block: without this the session got the
      # ordinary review prompt about a pull request it was told was open, with
      # no word of the failure, the rollback or the new pull request the fix
      # needs — and had nothing to fix.
      if [[ -z "$SCLAUDE_B_REGRESSION" && -n "$wt" ]] \
         && [[ "$(state_get "$wt/.sclaude/local/feature/state.json" reopened_by 2>/dev/null || true)" == "prod" ]]; then
        SCLAUDE_B_REGRESSION="$(regression_fix_block "$wt" prod 2>/dev/null || true)"
      fi
      # The same comment as step 2's: a thread can end in a change of scope,
      # and without it the issue went on describing the scope before it.
      [[ -n "$issue" ]] && SCLAUDE_B_USER_REQUEST="$(
        python3 "$LIB/github/issue_context.py" --request "$issue" "$wt" 2>/dev/null || true)"
      ;;
    status)
      # The directory for gh is the main repository rather than the feature's
      # tree: by this moment there is none. The deployment block is not
      # assembled here — run_status passes it ready, because it knows the
      # outcome of the blocks the human answered a minute ago.
      [[ -n "$issue" ]] && SCLAUDE_B_ISSUE_CHAIN="$(
        python3 "$LIB/github/issue_chain.py" "$issue" "$REPO" 2>/dev/null || true)"
      ;;
  esac

  # The paragraph on changing sclaude in the tree's workshop (workshop.sh):
  # the retrospective's alone among the steps' prompts. A step's session logs
  # what got in its way (friction.log), and its friction review changes
  # sclaude; `sclaude core-open` is refused it (forbidden-commands.py).
  local -x SCLAUDE_B_WORKSHOP=""
  case "$step" in
    retro|retro-again) SCLAUDE_B_WORKSHOP="$(workshop_rules "$wt")" ;;
  esac

  python3 "$LIB/cycle/render_prompt.py" "$file" "$PROMPTS" \
    || die "could not assemble the prompt for step $step"
  prompt_additions "$step" "${wt:-${REPO:-}}"
}

# What the product, and then the person, add to a prompt sclaude ships: the
# text of .sclaude/team/prompts/<step>.md and .sclaude/people/<name>/prompts/
# <step>.md in the tree, each under a heading naming its file. Appended, never
# put in place of sclaude's own text: the prompts carry markers and formats
# sclaude's code reads back, and a product that replaced one would stop
# receiving every later improvement to it. A rule that contradicts sclaude's
# is a change to sclaude, proposed as such.
#
#   prompt_additions <step> <tree>
prompt_additions() {
  local step="$1" tree="$2" name file who
  [[ -n "$tree" ]] || return 0
  name="$(developer_name 2>/dev/null || true)"
  for file in "$tree/.sclaude/team/prompts/$step.md" \
              ${name:+"$tree/.sclaude/people/$name/prompts/$step.md"}; do
    [[ -s "$file" ]] || continue
    if [[ "$file" == */team/* ]]; then who="This product adds"; else who="$name adds"; fi
    printf '\n\n---\n\n**%s** (`%s`):\n\n' "$who" "${file#"$tree"/}"
    cat "$file"
  done
}
