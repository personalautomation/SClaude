#!/usr/bin/env bash
#
# Starting a feature and coming back to one: `sclaude new` with its options,
# `sclaude <feature>`, and `sclaude issue`.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

slugify() {
  # printf rather than echo: echo takes a name that is -n or -e for its own
  # option and prints nothing.
  printf '%s\n' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9]\+/-/g' -e 's/^-\+//' -e 's/-\+$//'
}

# A suggested branch name from an issue: the number and the title's first words,
# all together no longer than 40 characters. issue_list.py makes it, as it does
# for the bot's Mini App, which offers the same name.
suggest_slug() {
  python3 "$LIB/github/issue_list.py" suggest "$1" "$2"
}

# The cycle's start: a choice between a name thought up and an open issue.
start_feature() {
  local choice; choice="$(pick_start)" || { info "Cancelled."; return 0; }
  case "$choice" in
    manual) cmd_new ;;
    issue*) cmd_new "" "$(cut -f2 <<< "$choice")" "$(cut -f3 <<< "$choice")" ;;
  esac
}

# `sclaude new [options] [name]`: with no name, the picker. The options answer
# ahead what cmd_new would ask, for a start made where its questions have no
# one to ask — the bot's Mini App, which has already shown the person the issue,
# its blockers and the branch name:
#
#   --issue <n>       start from issue n; the name is then the branch's
#   --create-issue    a feature by name gets an issue, unasked
#   --no-issue        it gets none, unasked
#   --blocked-ok      start despite open blockers: they were shown
#   --                the name follows, even one that starts with a dash
new_from_args() {
  local name="" issue=""
  NEW_CREATE_ISSUE="" NEW_BLOCKED_OK=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --issue)        [[ "${2:-}" =~ ^[0-9]+$ ]] || die "--issue takes a number"
                      issue="$2"; shift ;;
      --create-issue) NEW_CREATE_ISSUE=yes ;;
      --no-issue)     NEW_CREATE_ISSUE=no ;;
      --blocked-ok)   NEW_BLOCKED_OK=1 ;;
      # The rest is the name, whatever it starts with.
      --)             shift; name="${*:-}"; break ;;
      -*)             die "sclaude new: unknown option $1" ;;
      # Words not quoted together are still one name: `sclaude new dark mode`.
      *)              name="${name:+$name }$1" ;;
    esac
    shift
  done
  if [[ -n "$issue" && -z "$name" ]]; then
    # The name is suggested from the issue's title, as the picker suggests it.
    cmd_new "" "$issue" "$(gh issue view "$issue" -R "$(gh_repo)" --json title -q .title 2>/dev/null)"
  elif [[ -n "$name" ]]; then
    cmd_new "$name" "$issue"
  else
    start_feature
  fi
}

cmd_new() {
  require_repo
  local name="${1:-}" issue="${2:-}" slug wt branch

  # A repository sclaude has not been told about yet gets the offer to write
  # `.sclaude/config.json` — which checks make up a regression, where the manuals are,
  # what production's address is. Most of it is read out of the repository and
  # shown for correction rather than asked from scratch.
  #
  # Here rather than in require_repo: require_repo runs for `sclaude status`
  # too, which the bot calls on a timeout, and a question there would hang it. Starting a feature is the
  # moment somebody is present and the answers are about to matter.
  #
  # A decline is an answer and the feature starts anyway: without a config there
  # is no regression to gate on and no production to ship to, and the cycle says
  # so where it would have run them.
  project_init "$REPO" || true

  # Before the branch name is asked: a feature that is not going to start
  # should not cost the person a name first.
  if [[ -n "$issue" && -z "${NEW_BLOCKED_OK:-}" ]] && ! issue_blockers_gate "$issue"; then
    info "Cancelled."
    return 0
  fi

  if [[ -z "$name" && -n "$issue" ]]; then
    # The name is suggested rather than imposed: the line can be edited right
    # there.
    local suggested; suggested="$(suggest_slug "$issue" "${3:-}")"
    if [[ -t 0 ]] && person_at_terminal; then
      read -e -i "$suggested" -rp "Branch name: " name < /dev/tty || name=""
      name="$(clean_reply "$name")"
    else
      ask "Branch name [$suggested]: " name
    fi
    [[ -z "$name" ]] && name="$suggested"
  elif [[ -z "$name" ]]; then
    ask "Feature name: " name
    # An empty answer here is a refusal rather than an error: there is no
    # "shall we start" question any more, and this is the only way to change
    # one's mind when the picker did not appear.
    [[ -z "$name" ]] && { info "Cancelled."; return 0; }
  fi
  slug="$(slugify "$name")"
  [[ -n "$slug" ]] || die "a feature name needs at least one letter or digit: $name"

  branch="feat/$slug"
  wt="$(dirname "$REPO")/$(basename "$REPO")-$slug"

  [[ -e "$wt" ]] && die "directory already exists: $wt"
  git -C "$REPO" show-ref --verify --quiet "refs/heads/$branch" \
    && die "branch already exists: $branch (continue the feature with: $SELF $slug)"

  # A feature started from a name used to stay without an issue for ever:
  # issue_sync says nothing without a number, and step 1's prompt loses the whole
  # block about the issue along with it. We ask here — after the checks, so that
  # an issue is not created for a feature that cannot be created anyway, and
  # before the worktree, so that a refusal leaves nothing on disk.
  if [[ -z "$issue" ]]; then
    echo ""
    case "${NEW_CREATE_ISSUE:-}" in
      yes) issue="$(issue_create "$name")" || issue="" ;;
      no)  issue="" ;;
      *)   issue="$(issue_offer "$name")" || issue="" ;;
    esac
    [[ -n "$issue" ]] && info "  issue #$issue created for this feature"
  fi

  # An issue the work has started on must not stay in Backlog. Here rather than
  # in issue_sync: "the work has started" is exactly one moment of the cycle, and
  # repeating the move at every step transition would mean putting back into
  # progress an issue the human has meanwhile moved to another column themselves.
  # Through an `if` rather than a trailing `&&`: that would return 1 for a
  # feature without an issue, and this line ends a branch — the same case as in
  # deploy.sh.
  if [[ -n "$issue" ]]; then issue_start_progress "$issue"; fi

  echo ""
  info "Branching from a fresh origin/main…"
  git -C "$REPO" fetch origin || die "git fetch failed"
  refresh_main
  git -C "$REPO" worktree add "$wt" -b "$branch" origin/main || die "could not create the worktree"

  mkdir -p "$wt/.sclaude/local/feature"
  # From here the questions are the feature's and go to its channel, and so to
  # its topic in the bot (ask_channel). Not before: the bot keeps the topic in
  # the worktree, and the name and the issue were asked before there was one.
  local ASK_SLUG="$slug"
  ask_feature_begin
  python3 - "$wt/.sclaude/local/feature/state.json" "$slug" "$branch" "$wt" "$issue" <<'PY'
import json, sys, datetime
path, slug, branch, wt, issue = sys.argv[1:6]
state = {
    'feature': slug,
    'branch': branch,
    'worktree': wt,
    'issue': int(issue) if issue else None,
    'step': 'plan',
    'steps': {},
    'pr': None,
    'created': datetime.date.today().isoformat(),
}
with open(path, 'w') as fh:
    json.dump(state, fh, indent=2, ensure_ascii=False)
    fh.write('\n')
PY

  echo "${GREEN}Feature '$slug' created:${OFF} $wt (branch $branch)"
  # The issue learns of the work at once rather than after the first closed
  # step: until now it stayed silent through the whole planning, and from the
  # outside the feature looked untouched.
  cycle_edge "$wt" new prepare person "$SELF new" note="${issue:+issue #$issue}"
  [[ -n "$issue" ]] && cycle_edge "$wt" prepare board_start sclaude "issue #$issue to in progress"
  issue_sync "$wt"
  prepare_worktree "$wt"
  cycle_edge "$wt" prepare plan sclaude "the tree prepared"

  run_step "$wt" "$slug" "plan"
}

cmd_resume() {
  require_repo
  local slug="$1" wt step
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  step="$(state_get "$wt/.sclaude/local/feature/state.json" step)" || die "corrupted state: $wt/.sclaude/local/feature/state.json"

  # The PR may have appeared at any moment — step 3 creates it itself, and if
  # the session closed by another route the number did not reach the state. We
  # ask gh rather than relying on the step advancing: step 4 needs that number in
  # its prompt.
  [[ -z "$(state_get "$wt/.sclaude/local/feature/state.json" pr || true)" ]] && capture_pr "$wt"

  # What the watcher saw while no session was open. It changes nothing itself —
  # that is the whole design — so this is where its finding is acted on.
  #
  # Above the done-feature return below, and that placement is the whole of a
  # bug this once had. `watch_start` is called from remind_prod, so a feature
  # waiting on QA always sits at `step: done` — the one state this block was
  # written for was the one state it could not be reached in. QA returned the
  # feature, the comments were saved, and the human got the production reminder
  # as though nothing had been said.
  case "$(watch_verdict "$slug")" in
    done)
      echo ""
      say "${BOLD}QA passed this one while you were away.${OFF}"
      info "  The issue is in Done; the merge is next."
      # Acknowledged here, because nothing downstream will. watch_seen is called
      # from inside run_step, and a passed feature goes to remind_prod instead —
      # so the verdict would stay set and this banner would print on every
      # `sclaude <slug>` from now until the clean-up. It could not happen before
      # this block moved above the done-return, where it was unreachable for
      # exactly these features.
      #
      # But notes can be here, and an earlier comment claiming otherwise was
      # wrong. The watcher's `Done` branch only writes the verdict; it never
      # touches `.qa.md`. So a feature QA handed back on Friday and passed on
      # Monday arrives here with the Friday complaints still on disk, and
      # acknowledging blindly would file them into `.qa.md.seen` — which nothing
      # reads — without a session ever seeing them.
      #
      # They are shown rather than swallowed. Whether they still matter is the
      # human's call: QA passed the feature afterwards, so most likely the
      # complaint was answered or withdrawn, but that is not a thing to decide
      # on somebody's behalf in silence.
      local stranded; stranded="$(watch_notes "$slug")"
      if [[ -n "$stranded" ]]; then
        echo ""
        warn "  QA had left comments before they passed it:"
        while IFS= read -r line; do
          [[ -n "$line" ]] && info "    $line"
        done <<< "$stranded"
        info "  They were never handed to a session. Kept in the watch directory."
      fi
      watch_seen "$slug"
      ;;
    returned)
      echo ""
      say "${BOLD}This feature was returned to development.${OFF}"
      info "  What was said since — on the issue and on the pull request — goes into"
      info "  the review session below, and the session reads both for itself as well."
      # The cycle goes back with them. Their comments are handed to the step's
      # session by run_step, and without this there is no session to hand them
      # to: the review is recorded as finished and nothing reopens it.
      qa_take_back "$wt" "$slug" || true
      step="$(state_get "$wt/.sclaude/local/feature/state.json" step)" || true
      # Deliberately NOT acknowledged here: the comments have not been delivered
      # yet. run_step hands them to the session and calls watch_seen once it
      # has, which is the only moment at which they have actually been read.
      ;;
  esac

  # A change to sclaude a session left unfinished in the feature's workshop is
  # offered back first, and one whose publishing stopped short is tried again:
  # until then nothing of it is published. Before the end of the cycle too,
  # since the sessions after it use it; but not on the way into the clean-up,
  # which asks itself, ahead of the retrospective (cmd_done).
  #
  # Only the clean-up is left for a feature with no change (no_change.sh),
  # which has nothing to deploy, and for one whose last pass through
  # remind_prod got to the clean-up for this pull request and this production
  # (prod_pass.ended), unless production went red since (remind_prod then
  # holds it). Sent through it again — the clean-up stopped for sclaude's
  # code — it read the retrospective's commits as a preview nobody tested,
  # said QA was skipped, and ran the epilogue a second time for nothing, and
  # came to the same clean-up.
  local fstate="$wt/.sclaude/local/feature/state.json" cleanup_left="" ended
  if [[ "$step" == "done" ]]; then
    ended="$(state_get "$fstate" prod_pass.ended 2>/dev/null || true)"
    if [[ "$(state_get "$fstate" no_change 2>/dev/null || true)" == "true" \
          || "$ended" == "$(prod_pass_mark "$wt" nodeploy)" ]] \
       || { [[ "$ended" == "$(prod_pass_mark "$wt")" ]] \
            && [[ "$(regression_status "$wt" prod)" != failed ]] && prod_carries_feature "$wt"; }; then
      cleanup_left=1
    fi
  fi
  [[ -n "$cleanup_left" ]] || workshop_pending "$wt"

  if [[ "$step" == "done" ]]; then
    echo "Feature '$slug' has been through every step."
    # A sync's friction review left open after the steps holds the run as one
    # between steps does (sync_with_main): it comes first.
    local dkey; dkey="$(friction_pending "$fstate" || true)"
    if [[ -n "$dkey" ]] && ! run_friction "$wt" "$slug" "$dkey"; then
      return 0
    fi
    if [[ -n "$cleanup_left" ]]; then
      cmd_done "$slug" || true
    else
      remind_prod "$wt" "$slug"
    fi
    return 0
  fi

  # An unclosed friction review comes before the step — for the same reason it
  # stands between steps at all: the fix is needed by the step that is about to
  # start. If the review was interrupted, the feature waits here rather than
  # travelling on.
  local fkey; fkey="$(friction_pending "$fstate" || true)"
  if [[ -n "$fkey" ]]; then
    # The key names what the review was about, so there is nothing left to look
    # up: it used to be read from friction.after beside a nameless slot.
    if ! run_friction "$wt" "$slug" "$fkey"; then
      return 0
    fi
  fi

  # A regression that was killed mid-run leaves "running" in the state. It is
  # not resumed from where it stopped — the phase inside a run is deliberately
  # not recorded — but it must be said out loud, or the next run looks like it
  # started for no reason.
  local rstage
  for rstage in local preview prod; do
    if [[ "$(state_get "$fstate" "regression.$rstage.status" || true)" == "running" ]]; then
      info "The $rstage regression was interrupted — it starts again from the beginning."
      info "  The previous log is still in .sclaude/local/feature/regression.log."
      state_set "$fstate" "regression.$rstage.status" null
    fi
  done

  # A friction fix that was committed and never sent.
  #
  # No push of sclaude's own checkout here any more: the review sessions do not
  # commit to it (they change the product), and a change to sclaude itself is
  # proposed deliberately.


  prepare_worktree "$wt"
  run_step "$wt" "$slug" "$step"
}

# Returning a feature to step 1. Step 1 is closed by the plan's approval inside
# the session, and development begins right after the exit — the pause at which
# one could change one's mind is gone. This command is that "changed my mind":
# the plan turned out to be the wrong one, and it has to be discussed afresh.
#
# The only transition that moves the state backwards, which is why it asks. What
# step 2 wrote stays in the worktree: what to do with code already written is the
# human's decision, and it is taken in conversation rather than by a command's
# flag. Step 1 will see those changes and ask about them itself.
# An issue for a feature created before sclaude learned to create them — and for
# one whose human declined at the start and then changed their mind. Without this
# such a feature stays without an issue for ever: the question is asked only in
# cmd_new, once.
cmd_issue() {
  require_repo
  local slug="${1:-}" wt state issue
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  [[ -n "$slug" ]] || die "name the feature: $SELF issue <name>"
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug (list them with: $SELF status)"
  state="$wt/.sclaude/local/feature/state.json"

  issue="$(state_get "$state" issue || true)"
  if [[ -n "$issue" && "$issue" != "null" ]]; then
    info "Feature '$slug' already has issue #$issue."
    return 0
  fi

  echo ""
  issue="$(issue_offer "$slug")" || { info "Cancelled."; return 0; }
  [[ -n "$issue" ]] || return 0

  state_set "$state" issue "$issue"
  echo "${GREEN}Issue #$issue created for '$slug'.${OFF}"
  # The summary at once: otherwise the issue would stand empty until the next
  # transition.
  issue_sync "$wt"
}
