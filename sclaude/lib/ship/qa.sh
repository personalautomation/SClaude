#!/usr/bin/env bash
#
# QA on a feature's preview: whether it accepted, what it missed, a retest after
# a change, and the wait for its verdict.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# Whether QA accepted the preview last sent to them (`qa.sha`, accepted in
# `qa.accepted` by qa_accepted). With `deployed`, also that it is still the
# deployed one (`deploy.preview.sha`): a preview deployed after their yes whose
# run went red never reached qa_sent, so `qa.sha` still names the one before
# it — accepted, but not what is there. qa_missed asks without it: a preview
# deployed by hand after the yes, carrying the same product, moves
# `deploy.preview.sha` alone, and calling that unaccepted raised a false
# "never passed QA". Quiet and false without a tree or a record.
#
#   qa_accepted_now <wt> [deployed]
qa_accepted_now() {
  [[ -n "${1:-}" ]] || return 1
  local state="$1/.sclaude/local/feature/state.json" sent accepted
  sent="$(state_get "$state" qa.sha 2>/dev/null || true)"
  accepted="$(state_get "$state" qa.accepted 2>/dev/null || true)"
  [[ -n "$sent" && "$sent" != "null" && "$accepted" == "$sent" ]] || return 1
  [[ "${2:-}" == deployed ]] || return 0
  [[ "$(state_get "$state" deploy.preview.sha 2>/dev/null || true)" == "$sent" ]]
}

# What the preview regression said, for the words of an automatic QA: green,
# or that none ran because the project runs none there. Only the gate's
# green or the project's own "none" reach the automatic acceptance.
#
#   preview_suite_said <wt>
preview_suite_said() {
  local wt="${1:-}"
  if [[ -n "$(regression_parts preview "$wt" 2>/dev/null)" ]]; then
    printf 'the preview regression is green'
  elif [[ "$(project_stage_regression preview "$wt")" == none ]]; then
    printf 'no preview regression ran (previewRegression is none)'
  else
    printf 'no preview regression is declared'
  fi
}

# Did the issue miss QA entirely? Says so out loud, and answers by exit code.
#
# It misses when the branch was merged before the preview regression went green:
# `Closes #N` closes the issue at the merge, and a board with the "Item closed"
# workflow moves the item to Done in the same second. The QA move that runs just
# before this then finds the issue in a column it may not take it from, and the
# feature reaches production without anybody having looked at its deployment.
#
# A function rather than the dozen lines inline: the caller sits directly above
# the red-preview path, whose `return 0` tests/regression.py requires to be
# within sixteen lines of the gate call — a guard against exactly the kind of
# growth that would push it out of sight.
#
# Quiet and false on everything unknown: no issue, no gh, no board. The question
# is "do we know this went in unchecked", and not knowing is not a yes.
#
# Quiet as well when QA did accept the preview that is there now (qa_accepted).
# Every later run of a merged feature lands here with the issue in Done, and
# on one feature the second and third runs said "nobody checked the deployment" of a
# preview QA had accepted before the merge.
qa_missed() {
  local issue="$1" merged="${2:-}" wt="${3:-}"

  [[ -n "$issue" && "$issue" != "null" ]] || return 1
  qa_accepted_now "$wt" && return 1
  # Done with the pull request still open is the ordinary state now: QA comes
  # before the merge, and Done is how they say yes. Only a merge explains a
  # Done that nobody put there, so only a merged branch is asked about.
  [[ "$merged" == "MERGED" ]] || return 1
  # A board with no QA column declared has no "past QA" to have skipped.
  [[ -n "$QA_DONE" ]] || return 1
  column_is "$(issue_status_now "$issue" 2>/dev/null || true)" "$QA_DONE" || return 1

  echo ""
  warn "Issue #$issue is already '$QA_DONE' — it never passed through '$QA_TO'."
  info "  The branch was merged before this preview run went green, so nobody"
  info "  checked the deployment before it went in."
  return 0
}

# Takes an accepted issue back to QA when the preview it was accepted on has
# been replaced.
#
#   qa_retest <wt> <issue> <pr> [fresh]   → 0 when it took the issue back
#
# Done with the pull request still open is QA's yes — but a yes to the
# deployment they looked at. When the preview now carries different code (a fix
# for a red regression, a review comment, anything pushed and deployed since),
# what they accepted is no longer what would be merged, so the issue goes back
# to In QA and the merge waits for a new yes.
#
# "Different" is measured, not assumed: qa_sent records in `qa.sha` the preview
# commit QA was sent to look at, and deploy.preview.sha is what is on preview
# now. Two callers ask:
#
#   * remind_prod, right after a fresh preview deploy went green, with `fresh`
#     set. A feature from before the record existed has none, and there a
#     deploy that just happened is the change.
#   * qa_wait, on seeing Done and before it says the merge is next. Without a
#     record it cannot tell and leaves the issue alone: bouncing every feature
#     already accepted on the day this shipped would be its own mistake.
#
# This is the one move out of Done sclaude makes, and the reason it may is the
# same as for In QA itself: the claim is checkable.
#
# Only with the pull request open. A merged one is in Done because `Closes #N`
# put it there, and qa_missed speaks about that case.
#
# The pull request goes back to a draft as well, and the recorded hand-off is
# forgotten: pr_qa_handoff marked it ready when QA said yes, and leaving it
# ready lets anybody merge what nobody has checked. Forgetting the head makes
# the next yes hand it over again.
#
# Breaks nothing: no gh, no board, no Done column — silence and 1.
qa_retest() {
  local wt="$1" issue="$2" pr="$3" fresh="${4:-}" state sent now repo view pr_state draft

  [[ -n "$issue" && "$issue" != "null" && -n "$QA_DONE" && -n "$QA_TO" ]] || return 1
  [[ "$pr" =~ ^[0-9]+$ && -d "$wt/.sclaude/local/feature" ]] || return 1
  state="$wt/.sclaude/local/feature/state.json"
  sent="$(state_get "$state" qa.sha 2>/dev/null || true)"
  now="$(state_get "$state" deploy.preview.sha 2>/dev/null || true)"
  [[ -n "$now" && "$now" != "null" ]] || return 1
  if [[ -n "$sent" && "$sent" != "null" ]]; then
    [[ "$sent" != "$now" ]] || return 1
  else
    [[ -n "$fresh" ]] || return 1
  fi
  column_is "$(issue_status_now "$issue" 2>/dev/null || true)" "$QA_DONE" || return 1
  command -v gh >/dev/null 2>&1 || return 1
  repo="$(gh_repo)" || return 1
  [[ -n "$repo" ]] || return 1
  view="$(gh pr view "$pr" --repo "$repo" --json state,isDraft \
            --jq '[.state, (.isDraft|tostring)] | @tsv' 2>/dev/null)" || return 1
  IFS=$'\t' read -r pr_state draft <<<"$view"
  [[ "$pr_state" == OPEN ]] || return 1

  # QA answers for the product. A preview that changed only by what main
  # brought in and by files that are not the product (NO_DEPLOY: sclaude's own
  # .sclaude, docs, the workflows) carries the product QA passed: their yes
  # stands, and is moved on to the new commit.
  if [[ -n "$sent" && "$sent" != "null" ]] && qa_product_same "$wt" "$sent" "$now"; then
    echo ""
    info "Issue #$issue stays in '$QA_DONE': since QA looked (${sent:0:8} → ${now:0:8}), only main and"
    info "  files that are not the product changed — this branch's product is what QA passed."
    [[ "$(state_get "$state" qa.accepted 2>/dev/null || true)" == "$sent" ]] \
      && state_set "$state" qa.accepted "$now" 2>/dev/null || true
    state_set "$state" qa.sha "$now" 2>/dev/null || true
    return 1
  fi

  echo ""
  say "${BOLD}Issue #$issue is in '$QA_DONE', but the code on preview has changed since QA looked.${OFF}"
  info "  Preview is at ${now:0:8}${sent:+, QA was sent ${sent:0:8}} — it goes back to '$QA_TO' to be checked again."
  issue_move_status "$issue" "$QA_DONE" "$QA_TO"
  pr_unhandoff "$wt" "$pr" "$repo" "PR #$pr is a draft again until QA accepts its issues." "$draft"
  qa_sent "$wt"
  return 0
}

# Whether two commits of a branch carry the same product of its own: what each
# changes against the main it stands on, less what is not the product
# (NO_DEPLOY), compared as text (qa_own_diff). A merge of main moves the base
# and leaves the branch's own change as it was; a conflict resolved in a
# product file, a fix, or main changing the very lines the branch touches (the
# context of its hunks) makes them differ, and QA looks again. Anything that
# cannot be read says "differ".
#
#   qa_product_same <wt> <a> <b>
qa_product_same() {
  local wt="$1" a="$2" b="$3" c base pa pb
  local -a spec
  mapfile -t spec < <(no_deploy_pathspec 2>/dev/null)
  (( ${#spec[@]} )) || return 1
  for c in "$a" "$b"; do
    git -C "$wt" cat-file -e "$c^{commit}" 2>/dev/null || return 1
  done
  base="$(git -C "$wt" merge-base "$a" origin/main 2>/dev/null)" || return 1
  pa="$(qa_own_diff "$wt" "$base" "$a" "${spec[@]}")" || return 1
  base="$(git -C "$wt" merge-base "$b" origin/main 2>/dev/null)" || return 1
  pb="$(qa_own_diff "$wt" "$base" "$b" "${spec[@]}")" || return 1
  [[ "$pa" == "$pb" ]]
}

# The hash of a commit's change against <base> on the paths given, less what
# only says where it lies: the line numbers in `@@` and the `index` blob ids,
# which move with main's edits elsewhere in a file. The function context after
# the line numbers stays: in doubt this errs toward "changed", since a header
# main edits above the branch's lines costs QA a second look, while a false
# "same" lets an unseen change ship. Not patch-id, which ignores whitespace — a
# line re-indented out of a Python block is a change QA has not seen. Binary
# files by their content (`--binary`), every file by its bytes rather than a
# textconv driver's view of it, and renames found whatever the person's git
# config says, less their `similarity index` line, which moves with main's
# edits to the file — with renames off, a renamed file reads as all of it
# deleted and added, and any such edit would ask QA again. Streamed rather than
# held in a variable, which would drop NUL bytes. A diff that fails is a
# failure, not an empty change.
#
#   qa_own_diff <wt> <base> <commit> <pathspec>...
qa_own_diff() {
  local wt="$1" base="$2" c="$3" h
  shift 3
  h="$(set -o pipefail
       git -C "$wt" diff --binary --no-textconv --no-ext-diff --find-renames --no-color \
         "$base" "$c" -- "$@" 2>/dev/null \
         | sed -e '/^index /d' -e '/^similarity index /d' -e '/^dissimilarity index /d' \
               -e 's/^@@ -[0-9,]* +[0-9,]* @@/@@/' | sha1sum)" || return 1
  echo "${h%% *}"
}

# A hand-off for the merge (pr_qa_handoff) taken back: the pull request a
# draft again, unless it is one already (<draft> "true"), and the recorded
# hand-off forgotten, so that the next yes hands it over again. qa_retest and
# the sync with main (sync_withdraw) take it back.
#
#   pr_unhandoff <wt> <pr> <repo> <what is said> [draft]
pr_unhandoff() {
  if [[ "${5:-}" != true ]]; then
    if gh pr ready "$2" --repo "$3" --undo >/dev/null 2>&1; then
      info "$4"
    else
      warn "  could not make PR #$2 a draft — do it by hand (Convert to draft)"
    fi
  fi
  state_set "$1/.sclaude/local/feature/state.json" handoff "" 2>/dev/null || true
}

# Records which preview commit QA has been sent to look at — see qa_retest.
qa_sent() {
  local state="$1/.sclaude/local/feature/state.json" now
  now="$(state_get "$state" deploy.preview.sha 2>/dev/null || true)"
  [[ -n "$now" && "$now" != "null" ]] || return 0
  state_set "$state" qa.sha "$now" 2>/dev/null || true
  history_add "$state" qa in
}

# Records that QA accepted the preview commit they were sent (`qa.sha`), for
# qa_missed. A later qa_sent moves `qa.sha` on, and the record then no longer
# matches: a new preview is not accepted until QA says so again.
qa_accepted() {
  [[ -n "${1:-}" ]] || return 0
  local state="$1/.sclaude/local/feature/state.json" sent
  sent="$(state_get "$state" qa.sha 2>/dev/null || true)"
  [[ -n "$sent" && "$sent" != "null" ]] || return 0
  state_set "$state" qa.accepted "$sent" 2>/dev/null || true
  history_add "$state" qa accepted
}

# --- waiting for QA ----------------------------------------------------------
#
# The order at the end of the cycle is review → preview → QA → merge →
# production. The first two are sclaude's; QA and the merge are people's —
# unless `qa` or `merge` in the project's config says otherwise (both: a key
# in the wait does it from here; auto: sclaude does it at once) — and
# sclaude waits for each with the session it already has rather than exiting
# and leaving a person to remember `sclaude <feature>`. Each wait says which
# event it is waiting for, and moves on the moment that event happens.
#
# Ctrl-C leaves either wait and loses nothing: the feature sits at `step: done`
# and `sclaude <feature>` comes back into remind_prod, where an unchanged
# preview is skipped and the wait picks up where it was. The QA watch keeps
# looking in the meantime, so Telegram still says when the column moves.

# Is this column one QA hands a feature back with?
#
# In progress (`columns.progress`) and Backlog (`columns.backlog`) both mean
# "not accepted, needs work" — one says "now", the other "later", and neither
# is a pass. A column the project does not name is never a match: an empty name
# compared against an empty status would otherwise be.
qa_back_column() {
  local column="$1"
  [[ -n "$column" ]] || return 1
  column_is "$column" "$QA_FROM" && return 0
  column_is "$column" "$PROGRESS_FROM" && return 0
  return 1
}

# QA's word given from sclaude rather than on the board — `qa` is `both` and a
# person pressed `a` in the wait, or it is `auto`. The issue then reads as if
# QA had worked in it: every criterion ticked, and the issue moved from In QA
# to Done. A comment says who accepted it, since a column moved and boxes
# ticked under the gh account would otherwise read as a person having looked.
#
#   qa_accept_here <issue> <key|auto> [wt]
#
# Returns 0 once the issue is in Done, 1 when it is not — the board could not
# be read or written — and the wait goes on for a person to move it.
qa_accept_here() {
  local issue="$1" how="$2" wt="${3:-}" word who
  # The move first: boxes ticked and a comment saying "accepted" on an issue
  # the board kept in In QA would claim what did not happen.
  issue_move_status "$issue" "$QA_TO" "$QA_DONE"
  column_is "$(issue_status_now "$issue" 2>/dev/null || true)" "$QA_DONE" || return 1
  word="$(python3 "$LIB/cycle/acceptance.py" --tick "$issue" "${REPO:-.}" 2>/dev/null || true)"
  case "$word" in
    ticked) info "  Every acceptance criterion in issue #$issue is ticked." ;;
    already|nothing) ;;
    body) warn "  The criteria of issue #$issue are in its description, which sclaude never writes — tick them there." ;;
    torn) warn "  The criteria comment on issue #$issue lost one of its markers — nothing ticked; tick them on GitHub." ;;
    *) warn "  Could not tick the criteria in issue #$issue${word:+ ($word)} — tick them on GitHub." ;;
  esac
  if [[ "$how" == auto ]]; then
    who="automatically: \`qa\` is \`auto\` in .sclaude/config.json, and $(preview_suite_said "$wt"). Nobody looked at the preview."
  else
    declare -F developer_name >/dev/null && who="$(developer_name 2>/dev/null || true)"
    who="from sclaude${who:+ by $who}, in the wait for QA."
  fi
  # A heading that names the kind of comment, the same on every issue.
  gh issue comment "$issue" --repo "$(gh_repo)" --body "$(printf '## QA Accepted\n\nAccepted %s' "$who")" >/dev/null 2>&1 \
    || warn "  Could not comment on issue #$issue that sclaude accepted it."
  return 0
}

# The question behind `a`: the criteria as they stand, then yes or no. A key
# alone is too easy to press by accident in a wait that lasts hours.
qa_accept_offer() {
  local issue="$1" criteria line answer
  criteria="$(python3 "$LIB/cycle/acceptance.py" --status "$issue" "${REPO:-.}" 2>/dev/null || true)"
  echo ""
  if [[ -n "$criteria" ]]; then
    say "Acceptance criteria in issue #$issue:"
    while IFS= read -r line; do say "  $line"; done <<<"$criteria"
  fi
  ask "${BOLD}Accept issue #$issue: tick every criterion and move it to '$QA_DONE'? [y/n] ${OFF}" answer yn
  is_yes "$answer"
}

# Wait until QA has decided about the issue.
#
#   qa_wait <slug> <issue> <pr> [branch] [wt]
#
# Done is checked against the preview before it counts: when the code there
# changed since QA was sent to look, qa_retest takes the issue back to In QA
# and the wait goes on. With no worktree given that check is skipped.
#
# Returns 0 when the issue is in Done — or when there is nothing to wait for:
# no issue, no Done column declared, the issue on no board or gh silent. The
# merge question that follows reads the column itself and words itself for
# each of those, so this does not need to tell them apart.
#
# Returns 2 when the feature was returned to development: the issue left In QA for In
# progress or Backlog. The caller puts the cycle back on the review step.
#
# Returns 3 when the pull request was merged while QA still had it — on
# GitHub, by hand. A merge settles the two conditions it can (merged, and Done
# on a board that closes issues with `Closes #N`), so the wait ends there; the
# caller says out loud that QA was skipped.
#
# Any other column is unexpected while QA has the feature: nobody's verdict
# lives there. This says so once per column, asks for the status to be set
# properly, and keeps waiting — the board is a person's to fix, not ours to
# guess about.
#
# The acceptance criteria do not gate Done. GitHub Projects cannot refuse a
# status change, so a gate would have to undo a person's move after the fact;
# it names the unticked ones instead, and the merge question names them again.
#
# `qa` in the project's config decides who may give the word besides the
# board (project_flow_mode): with `both`, `a` pressed during the wait accepts
# from here; with `auto`, an issue in In QA is accepted at once, once — if the
# board refuses the move, the wait goes on as with `github`.
qa_wait() {
  local slug="$1" issue="$2" pr="$3" branch="${4:-}" wt="${5:-}"
  local now prev said="" waited=0 logged=0 announced=0 unticked start=$SECONDS
  local mode auto_tried=0 keys=""

  [[ -n "$issue" && "$issue" != "null" && -n "$QA_DONE" ]] || return 0
  now="$(issue_status_now "$issue" 2>/dev/null || true)"
  [[ -n "$now" ]] || return 0

  # The timer may have seen the hand-back before this session did. Its verdict
  # is the record of that, and the column it recorded then is where the issue
  # still is — so without this the move would look like one that never left a
  # back column.
  [[ "$(watch_verdict "$slug")" == "returned" ]] && return 2

  mode="$(project_flow_mode qa "$wt")"

  # The column before this look, which is what tells a hand-back from an issue
  # that never reached QA at all. The watch file holds the one observed when QA
  # was asked to look; without one, In QA is what issue_qa_ready claimed.
  prev="$(state_get "$(watch_dir)/$slug.json" status 2>/dev/null || true)"
  [[ -n "$prev" && "$prev" != "null" ]] || prev="$QA_TO"

  while :; do
    if [[ -n "$now" ]]; then
      if column_is "$now" "$QA_DONE" && qa_retest "$wt" "$issue" "$pr"; then
        # Accepted, but on code that is no longer on preview: back in QA, and
        # the wait announces itself again.
        now="$QA_TO"
        watch_mark "$slug" "$now"
        announced=0
      elif column_is "$now" "$QA_DONE"; then
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        watch_mark "$slug" "$now"
        qa_accepted "$wt"
        # Said only after a wait. An issue already in Done on arrival is
        # announced by the merge question itself, and two headings saying the
        # same thing is how people learn to skip both.
        if [[ "$announced" -eq 1 ]]; then
          echo ""
          say "${BOLD}QA accepted issue #$issue — it is in '$QA_DONE'.${OFF}"
          unticked="$(python3 "$LIB/cycle/acceptance.py" --unticked "$issue" "${REPO:-.}" 2>/dev/null || true)"
          [[ -n "$unticked" ]] \
            && warn "  QA moved #$issue to '$QA_DONE', but not ticked: $unticked."
          info "  Now waiting for the merge of PR #$pr."
        fi
        return 0
      elif qa_back_column "$now" && ! qa_back_column "$prev"; then
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        history_add "$wt/.sclaude/local/feature/state.json" qa back
        return 2
      elif ! column_is "$now" "$QA_TO" && ! column_is "$now" "$said"; then
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        echo ""
        warn "  Issue #$issue is in '$now' — unexpected while waiting for QA."
        info "  Please set the ticket status: '$QA_DONE' if it is accepted,"
        info "  '$QA_FROM'${PROGRESS_FROM:+ or '$PROGRESS_FROM'} if it needs work."
        said="$now"
        # Said here; the timer need not say it again on Telegram.
        watch_mark "$slug" "$now"
      elif column_is "$now" "$QA_TO" && [[ -n "$said" ]]; then
        # Put back into QA: the unexpected column is no longer the news.
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        info "  Issue #$issue is back in '$QA_TO'."
        said=""
        watch_mark "$slug" "$now"
      fi
      prev="$now"
    fi

    if [[ "$mode" == auto && "$auto_tried" -eq 0 ]] && column_is "$now" "$QA_TO"; then
      auto_tried=1
      [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
      echo ""
      say "${BOLD}Accepting issue #$issue: \`qa\` is auto, and $(preview_suite_said "$wt").${OFF}"
      if qa_accept_here "$issue" auto "$wt"; then
        now="$QA_DONE"
        continue
      fi
      warn "  It is not in '$QA_DONE' — waiting for QA on the board instead."
    fi

    if [[ "$announced" -eq 0 ]]; then
      announced=1
      echo ""
      say "${BOLD}Waiting for QA on issue #$issue.${OFF}"
      info "  QA checks the acceptance criteria in the issue and moves it to '$QA_DONE'."
      [[ "$mode" == both ]] \
        && info "  Or press a here to accept it from sclaude: every criterion ticked, the issue moved."
      info "  The merge of PR #$pr comes after that."
      info "  Ctrl-C to leave — the QA watch keeps looking, and Telegram will say when"
      info "  the column moves. Resume with: $SELF $slug"
      echo ""
    fi
    keys=""
    [[ "$mode" == both ]] && column_is "$now" "$QA_TO" && keys=", a accepts here"
    if [[ -t 1 ]]; then
      printf '\r\033[2K\033[?7l  %sHuman in the loop%s — waiting for QA (%s so far, next check in %ss, any key checks now%s)\033[?7h' \
        "$DIM" "$OFF" "$(regression_duration "$waited")" "$QA_POLL" "$keys"
    elif [[ $((waited - logged)) -ge 300 || "$waited" -eq 0 ]]; then
      # Without a terminal, a line every five minutes: this ends up in a log
      # somebody reads later.
      info "  waiting for QA on issue #$issue ($(regression_duration "$waited"))"
      logged="$waited"
    fi
    # A key cuts the pause short, so the time is counted rather than added up.
    poll_pause "$QA_POLL"
    waited=$((SECONDS - start))
    # Read again before asking: QA may have moved the issue during the pause,
    # and their move is not one to answer over.
    if [[ "$mode" == both && "$POLL_KEY" == [aA] ]] \
       && column_is "$(issue_status_now "$issue" 2>/dev/null || true)" "$QA_TO"; then
      [[ -t 1 ]] && printf '\r\033[2K'
      if qa_accept_offer "$issue" && ! qa_accept_here "$issue" key "$wt"; then
        warn "  Issue #$issue is not in '$QA_DONE' — nothing ticked; move it on the board."
      fi
    fi
    if [[ -n "$branch" && "$(branch_pr_state "$branch")" == "MERGED" ]]; then
      [[ -t 1 ]] && printf '\r\033[2K'
      return 3
    fi
    now="$(issue_status_now "$issue" 2>/dev/null || true)"
  done
}
