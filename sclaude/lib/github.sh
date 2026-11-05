#!/usr/bin/env bash
#
# Issues and pull requests through gh: opening and capturing the pull request,
# linking and closing the issue, creating one, and its blockers. The issue's
# summary is in issue_sync.sh, its place on the board in board.sh, and the
# feature's outcome in outcome.sh.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The issues' milestone — onto the pull request as well.
#
# An issue and its PR are one piece of work, and in a milestone they must lie
# together: otherwise the milestone's report shows half of what was done, and the
# board shows the issue in the milestone with its PR hanging outside it.
# `Closes #N` does not do this: it links them and will close the issue on the
# merge, but it carries no fields across.
#
# Every issue the PR closes is asked, not only the feature's own (pr_handoff.py
# tickets). An issue with no milestone is no candidate: it has no opinion, and
# leaving the PR out of a milestone because one issue was never filed into any
# would be letting the emptiest answer win. Two issues in two milestones are a
# real disagreement, and only a person can settle it, so they are asked; no
# answer leaves the PR out of both rather than guessing.
#
# We take the milestone from the issues themselves rather than from the
# feature's state: days pass between the issue being created and this step,
# during which the milestone may have been changed by hand, and a dispute
# between two sources is won by the one the human is looking at.
#
# We never touch a milestone already set on the PR — it stands there because
# somebody put it there, and out-arguing that is not our business.
#
# It breaks nothing: no issue, no milestone, no network, no permissions and we
# exit silently. A milestone on a PR is a reporting convenience, not a condition
# of the work.
pr_milestone() {
  local wt="$1" number="$2"
  local issue repo milestone current candidates

  issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"
  [[ "$issue" == "null" ]] && issue=""
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  # A PR is an issue too, and its milestone is in the same field, so we read it
  # with the same request as an issue's. We still write through `gh pr edit`: it
  # looks a milestone up by name, whereas a PATCH on issues accepts only its
  # number, which we do not have.
  current="$(gh api "repos/$repo/issues/$number" --jq '.milestone.title // ""' 2>/dev/null)" || current=""
  candidates="$(python3 "$LIB/pr_handoff.py" milestones "$wt" "$number" "$issue" 2>/dev/null)" || candidates=""
  [[ -n "$candidates" ]] || return 0

  if [[ -n "$current" ]]; then
    grep -qxF "$current" < <(cut -f1 <<<"$candidates") \
      || info "PR #$number keeps its own milestone '$current' (its issues are in: $(cut -f1 <<<"$candidates" | paste -sd, - | sed 's/,/, /g'))."
    return 0
  fi

  local -a titles=() whose=()
  local title from
  while IFS=$'\t' read -r title from; do
    [[ -n "$title" ]] || continue
    titles+=("$title"); whose+=("$from")
  done <<<"$candidates"

  if [[ "${#titles[@]}" -eq 1 ]]; then
    milestone="${titles[0]}"
  else
    echo ""
    say "${BOLD}The issues of PR #$number are in different milestones:${OFF}"
    local i answer
    for i in "${!titles[@]}"; do
      say "  $((i + 1)). ${titles[$i]}  ${DIM}(${whose[$i]})${OFF}"
    done
    ask "Which milestone does PR #$number go in? [1-${#titles[@]}, Enter to leave it out] " \
      answer "pick:${#titles[@]}" "${titles[@]}" || answer=""
    if [[ "$answer" =~ ^[0-9]+$ ]] && (( answer >= 1 && answer <= ${#titles[@]} )); then
      milestone="${titles[$((answer - 1))]}"
    else
      info "PR #$number left out of any milestone — set it by hand when it is decided."
      return 0
    fi
  fi

  if (cd "$wt" && gh pr edit "$number" --milestone "$milestone" >/dev/null 2>&1); then
    info "PR #$number added to milestone '$milestone', with its issues."
  else
    warn "  could not put PR #$number in milestone '$milestone' — set it by hand if it matters"
  fi
  return 0
}

# A new pull request as the cycle wants it: a draft, assigned to whoever opened
# it, in its issues' milestone.
#
# A draft because it is not ready to merge until QA has accepted its issues —
# the merge offer refuses a draft, and so does GitHub's button, which makes the
# state a guard rather than a label. pr_qa_handoff marks it ready at that
# moment. Assigned to its author because until then the work is theirs: the
# board's "assigned to me" is how a developer finds what is waiting on them,
# and the hand-off clears it when it stops being so.
#
# Once per pull request: capture_pr runs again on every resume and every
# re-check of step 3, and making a PR a draft again after QA marked it ready
# would undo the hand-off. The number done is recorded in the state.
#
# Like everything here, it breaks nothing — a failure is a warning.
pr_setup() {
  local wt="$1" number="$2"
  local state="$wt/.sclaude/local/feature/state.json" repo json

  [[ "$(state_get "$state" pr_setup 2>/dev/null || true)" == "$number" ]] && return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0
  json="$(gh pr view "$number" --repo "$repo" --json state,isDraft,author,assignees \
            --jq '[.state, (.isDraft|tostring), .author.login, (.assignees|length|tostring)] | @tsv' \
            2>/dev/null)" || return 0
  local pr_state draft author assigned
  IFS=$'\t' read -r pr_state draft author assigned <<<"$json"
  # A merged PR picked up by the early exit is past the draft and the
  # assignee; its milestone still belongs in the report.
  if [[ "$pr_state" != OPEN ]]; then
    pr_milestone "$wt" "$number"
    return 0
  fi

  if [[ "$draft" != true ]]; then
    if gh pr ready "$number" --repo "$repo" --undo >/dev/null 2>&1; then
      info "PR #$number is a draft until QA accepts its issues."
    else
      warn "  could not make PR #$number a draft — do it by hand (Convert to draft)"
    fi
  fi
  if [[ "$assigned" == 0 && -n "$author" ]]; then
    if gh pr edit "$number" --repo "$repo" --add-assignee "$author" >/dev/null 2>&1; then
      info "PR #$number assigned to its author, $author."
    else
      warn "  could not assign PR #$number to $author — do it by hand"
    fi
  fi
  pr_milestone "$wt" "$number"
  state_set "$state" pr_setup "$number" 2>/dev/null || true
  return 0
}

capture_pr() {
  local wt="$1" number
  number="$(cd "$wt" && gh pr view --json number --jq .number 2>/dev/null)" || return 0
  [[ -n "$number" ]] || return 0
  state_set "$wt/.sclaude/local/feature/state.json" pr "$number"
  info "PR #$number recorded in the feature's state."
  # Here rather than in step 3: every PR found comes through here — both one
  # just opened and one picked up by the early exit on an already merged one.
  pr_link_issue "$wt" "$number"
  pr_setup "$wt" "$number"
  issue_hold_open "$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"
}

# The pull request the branch has now, recorded once it is a new one. A
# feature reopened after its merge by a rollback or QA's hand-back goes back
# to step 4, whose session opens the new pull request, and nothing else asks
# the branch again: the state went on naming the merged one, and with it the
# review report and the step's close.
#
#   capture_reopened_pr <wt>
capture_reopened_pr() {
  local state="$1/.sclaude/local/feature/state.json" seen number branch
  seen="$(state_get "$state" reopened_pr 2>/dev/null || true)"
  [[ -n "$seen" && "$seen" != "null" && "$seen" == "$(state_get "$state" pr 2>/dev/null || true)" ]] \
    || return 0
  # By the feature's branch, not the one the tree is on: a session that left
  # it on another branch would give the feature that branch's pull request.
  branch="$(state_get "$state" branch 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "null" ]] || return 0
  [[ "$(git -C "$1" branch --show-current 2>/dev/null)" == "$branch" ]] || return 0
  number="$(cd "$1" && gh pr view "$branch" --json number --jq .number 2>/dev/null)" || return 0
  [[ -n "$number" && "$number" != "$seen" ]] || return 0
  capture_pr "$1"
}

# The issue stays open until the whole cycle is over, and sclaude closes it.
#
# Two things close it too early, and neither is a mistake on its own. A board
# with the "Auto-close issue" workflow closes an issue the moment its status
# becomes Done — and Done is how QA says yes, before the merge. And a merge
# carrying `Closes #N` (or a manual closing link, see pr_link_issue) closes it
# at the merge, before production and its regression. An issue once went
# Closed that way with its PR still open.
#
# Closed means "nothing left to do here", and until production is green that is
# not true: a red production regression sends the work back to review under
# this same issue. So the status may say Done — that is QA's answer — while the
# issue stays open, and issue_close_done closes it at the very end.
#
# Only a completed close is undone. "Not planned" is what abandon writes, and
# somebody closing a feature that way meant it.
issue_hold_open() {
  local issue="$1" repo closed

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  closed="$(gh api "repos/$repo/issues/$issue" \
    --jq 'select(.state == "closed" and .state_reason == "completed") | "yes"' 2>/dev/null)" || return 0
  [[ "$closed" == yes ]] || return 0

  if gh issue reopen "$issue" --repo "$repo" >/dev/null 2>&1; then
    info "Issue #$issue reopened — it was closed before the cycle ended; sclaude closes it when the cycle ends."
  else
    warn "  issue #$issue was closed before the cycle ended, and reopening it failed — reopen it by hand"
  fi
  return 0
}

# The other half: the cycle is over, the issue closes. "shipped" when
# production carries the feature and its regression is green, "declined" when
# the human said no to production — the work is merged and accepted either way.
# "nosuite" when production carries it and the project runs no suite there
# (project_prod_suite_declined): nothing was checked, so nothing is called green.
# "unchanged" when the feature changed nothing in the code, "nodeploy" when it
# changed only what nothing deploys (both no_change.sh).
issue_close_done() {
  local issue="$1" outcome="${2:-shipped}" repo state

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  state="$(gh api "repos/$repo/issues/$issue" --jq .state 2>/dev/null)" || return 0
  [[ "$state" == open ]] || return 0

  if gh issue close "$issue" --repo "$repo" --reason completed >/dev/null 2>&1; then
    if [[ "$outcome" == unchanged ]]; then
      info "Issue #$issue closed — the feature changed nothing in the code, so it had no pull request."
    elif [[ "$outcome" == nodeploy ]]; then
      info "Issue #$issue closed — merged; the change is one nothing deploys."
    elif [[ "$outcome" == shipoff ]]; then
      info "Issue #$issue closed — merged and accepted; sclaude does not deploy production here (ship: off)."
    elif [[ "$outcome" == nosuite ]]; then
      info "Issue #$issue closed — the feature is in production; no production regression is declared here."
    elif [[ "$outcome" == declined ]]; then
      info "Issue #$issue closed — merged and accepted; production was declined."
      info "  Ship it later from ${REPO:-the repository}: vercel --prod"
    else
      info "Issue #$issue closed — the feature is in production and its regression is green."
    fi
  else
    warn "  could not close issue #$issue — close it by hand"
  fi
  return 0
}

# The PR linked to its issue as a closing reference — checked, and made if missing.
#
# The body ends with `Closes #N` and GitHub is supposed to link the two from it.
# Usually it does; once it did not, with nothing in the body,
# the base branch or the permissions to explain why, and re-saving the body did
# not help. An unlinked PR is not cosmetic: the merge closes the issue through
# that same link, so without it the issue stays open and the board card never
# reaches Done.
#
# addCloseIssueReferences is what the "Development" box in the issue sidebar
# does by hand. A manual link sits beside a keyword one, so adding it while
# GitHub is still parsing the body costs nothing.
#
# Only an open PR: after the merge the moment the link was for has passed.
# Not a PR whose body says `Refs #N` and closes nothing: see below.
# Like pr_milestone, it breaks nothing — any failure is a warning.
pr_link_issue() {
  local wt="$1" number="$2"
  local issue repo pr_state linked issue_id pr_id body

  issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"
  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  pr_state="$(gh api "repos/$repo/pulls/$number" --jq '.state + " " + .node_id' 2>/dev/null)" || return 0
  pr_id="${pr_state#* }"
  [[ "${pr_state%% *}" == open ]] || return 0

  linked="$(cd "$wt" && gh pr view "$number" --json closingIssuesReferences \
    --jq '.closingIssuesReferences[].number' 2>/dev/null)" || return 0
  grep -qx "$issue" <<<"$linked" && return 0

  # `Refs #N` with no closing keyword is a choice, not a link GitHub missed: a
  # follow-up pull request for an issue already shipped says
  # so on purpose. sclaude closes the issue itself when the cycle ends.
  body="$(gh api "repos/$repo/pulls/$number" --jq .body 2>/dev/null || true)"
  if grep -qiE "(^|[^[:alnum:]])refs?[[:space:]]+#$issue([^0-9]|$)" <<<"$body" \
     && ! grep -qiE "(close[sd]?|fix(e[sd])?|resolve[sd]?)[[:space:]]+#$issue([^0-9]|$)" <<<"$body"; then
    info "PR #$number refers to issue #$issue without closing it (Refs #$issue) — left unlinked, as written."
    return 0
  fi

  issue_id="$(gh api "repos/$repo/issues/$issue" --jq .node_id 2>/dev/null)" || issue_id=""
  if [[ -n "$issue_id" && -n "$pr_id" ]] && gh api graphql \
      -f query='mutation($i:ID!,$p:ID!){addCloseIssueReferences(input:{issueId:$i,pullRequestIds:[$p]}){clientMutationId}}' \
      -f i="$issue_id" -f p="$pr_id" >/dev/null 2>&1; then
    info "PR #$number linked to issue #$issue by hand — GitHub did not link them from 'Closes #$issue'."
  else
    warn "  PR #$number is not linked to issue #$issue, and linking it failed — link it in the issue's Development box, or the merge will not close the issue"
  fi
  return 0
}

# The body of an issue being created. One for both `gh issue create` attempts
# below: the second differs only in its set of fields rather than its text, and
# copies that had diverged would give issues with different bodies depending on
# whether a label was found.
#
# It is written once and never edited again — see issue_comments.py. It used
# to be a template with empty "User request" and "Acceptance criteria"
# sections that step 1 and the orchestrator filled in later, which made the
# description a thing that changes under whoever is reading it. What the
# request turns out to be, the criteria and the status all go into comments,
# and the body says so, for whoever opens the issue before any of them exist.
issue_body() {
  cat <<'EOF'
Created by `sclaude` when this feature was started. What was asked for, the acceptance criteria and the current status are kept in the comments below; this description is not edited.
EOF
}

# Creates an issue for a feature and prints its number.
#
# The title is the name as the human typed it rather than the slug: what should
# reach GitHub is "Sample feature one", not "sample-feature-one".
#
# The body is one line saying where the rest will be: step 1 records the request
# in a comment as the conversation goes, because its content exists only there.
# Until then the issue at least shows that it was created and by whom.
#
# The milestone is the earliest open one by due date, an overdue one included.
# "The nearest one not overdue" sounds tidier but leads a new issue away from
# those it ought to lie beside: the work is happening in precisely the overdue
# milestone.
#
# It breaks nothing: no gh, no network, no permissions and we warn, print
# nothing, and the feature is created without an issue. Creating an issue is a
# convenience, not a condition of the work.
issue_create() {
  local title="$1" repo milestone url number

  command -v gh >/dev/null 2>&1 || { warn "  no gh — the feature starts without an issue"; return 1; }
  repo="$(gh_repo)" || repo=""
  [[ -n "$repo" ]] || { warn "  could not tell which repository this is — the feature starts without an issue"; return 1; }

  # The milestone and the label are not critical: if they turn out to be
  # missing, the issue must still be created. So the milestone is looked up
  # separately and substituted only if it was found.
  milestone="$(gh api "repos/$repo/milestones" --paginate --jq \
    '[.[] | select(.state == "open")] | sort_by(.due_on // "9999") | .[0].title' \
    2>/dev/null)" || milestone=""
  [[ "$milestone" == "null" ]] && milestone=""

  local -a args=(
    --repo "$repo"
    --title "$title"
    --body-file -
    --assignee "@me"
  )
  # The project's, from `board.issue` in .sclaude/config.json; absent means none.
  [[ -n "${ISSUE_LABEL:-}" ]] && args+=(--label "$ISSUE_LABEL")
  [[ -n "${ISSUE_TYPE:-}" ]] && args+=(--type "$ISSUE_TYPE")
  [[ -n "$milestone" ]] && args+=(--milestone "$milestone")

  url="$(gh issue create "${args[@]}" < <(issue_body) 2>/dev/null)" || url=""

  # The label or the type may not have been found — gh then refuses entirely. A
  # second attempt without them: the issue matters more than its fields.
  if [[ -z "$url" ]]; then
    args=(--repo "$repo" --title "$title" --body-file - --assignee "@me")
    [[ -n "$milestone" ]] && args+=(--milestone "$milestone")
    url="$(gh issue create "${args[@]}" < <(issue_body) 2>/dev/null)" || url=""
    [[ -n "$url" ]] && warn "  the issue was created without its label or type"
  fi

  [[ -n "$url" ]] || { warn "  could not create the issue — the feature starts without one"; return 1; }

  number="${url##*/}"
  [[ "$number" =~ ^[0-9]+$ ]] || { warn "  gh printed something unexpected: $url"; return 1; }
  echo "$number"
}

# Asks whether to create an issue, and creates it. Prints the number or
# nothing.
issue_offer() {
  local title="$1" answer
  ask "${BOLD}Create a GitHub issue for this feature? [y/n] ${OFF}" answer yn
  is_yes "$answer" || return 1
  issue_create "$title"
}

# Before a feature starts from an issue that GitHub says is blocked by open
# issues: names them and asks whether to start anyway. Returns 1 when the answer
# is no.
#
# A question rather than a refusal: "blocked by" is set by hand and goes stale,
# and sometimes the blocker is exactly what this feature is meant to finish.
# The person knows; sclaude only makes sure they are told before the worktree,
# the branch and the board move exist rather than after.
#
# Silent when the blockers cannot be read: no answer from gh is not a reason to
# stop a start that worked without this check.
issue_blockers_gate() {
  local issue="$1" open answer number title
  open="$(python3 "$LIB/blockers.py" issue "$(gh_repo)" "$issue" 2>/dev/null)" || return 0
  [[ -z "$open" ]] && return 0
  echo ""
  warn "Issue #$issue is blocked by open issues:"
  while IFS=$'\t' read -r number title; do
    warn "  #$number  $title"
  done <<< "$open"
  ask "${BOLD}Start it anyway? [y/n] ${OFF}" answer yn
  is_yes "$answer"
}

# Open blockers of the features in progress, one GitHub request for all of them:
# "<issue>\t#68 #70" per blocked issue, read from the issue numbers given.
# Empty when none is blocked or gh cannot answer.
features_blockers() {
  [[ $# -gt 0 ]] || return 0
  python3 "$LIB/blockers.py" list "$(gh_repo)" "$@" 2>/dev/null || true
}
