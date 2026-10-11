#!/usr/bin/env bash
#
# Issues and pull requests: everything that goes through gh.
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
issue_close_done() {
  local issue="$1" outcome="${2:-shipped}" repo state

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  state="$(gh api "repos/$repo/issues/$issue" --jq .state 2>/dev/null)" || return 0
  [[ "$state" == open ]] || return 0

  if gh issue close "$issue" --repo "$repo" --reason completed >/dev/null 2>&1; then
    if [[ "$outcome" == declined ]]; then
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

# A summary of the work's progress — in the issue the feature was created from.
#
# Until now the link was one-way: the issue was read to choose a feature and
# start the plan, and was not touched again. The issue meanwhile said nothing
# about anything — issue #43 closed with a merge and zero comments, and from it
# one could learn neither that the work had happened nor what it was done with.
#
# One comment, rewritten at every transition, rather than a feed: a feed repeats
# what is visible in the PR, and has to be read from the bottom up to understand
# where the work stands. We find our own comment by a marker in the first line —
# `gh issue comment --edit-last` will not do, twice over: gh 2.45.0 (which is
# what is installed here) has no --create-if-none, so the first call would fail,
# and "the author's last comment" is not necessarily our summary.
#
# It breaks nothing: no issue, no gh, no network and we warn and carry on.
# Reporting is not worth stalling a step over.
issue_sync() {
  # Two declarations rather than one: in `local a="$1" b="$a/x"` bash under
  # set -u trips over the $a that does not exist yet.
  local wt="$1"
  local state="$wt/.sclaude/local/feature/state.json" issue repo body id

  issue="$(state_get "$state" issue || true)"
  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  # The steps' order and names come from STEP_SPEC rather than being repeated
  # here as a fifth copy: while they lived as a separate dictionary, an added
  # step made it into the cycle but not into the issue's summary.
  local spec="" st
  for st in "${STEPS[@]}"; do
    spec+="$st=$(step_title "$st")"$'\n'
  done

  # What each friction review actually changed in the orchestrator.
  #
  # run_friction records the instruments HEAD on either side of a review that
  # committed; here those ranges become commit subjects. The reading is done in
  # shell rather than inside the heredoc because git lives in ~/instruments and
  # the summary is assembled from the product's worktree — and because
  # INSTRUMENTS is not exported, so the child python cannot see it anyway.
  #
  # One line per commit, `key<TAB>sha<TAB>subject<TAB>files`, the last being
  # the paths the commit touched, space-separated: the renderer needs them to
  # give each commit of a `mixed` review a verdict of its own. A range whose commits have
  # since been rewritten or dropped yields nothing, and the review falls back to
  # the verdict-only row below — or to no row at all, if it left no verdict
  # either. A summary is not worth failing over, and a row naming a sha that no
  # longer resolves would send a reader after a commit they cannot open.
  #
  # A review earns a row if it committed or if it left a verdict. The second is
  # how a `deliberate` outcome appears at all: it changed nothing on purpose, so
  # it has no range and `git log` has nothing to say about it — and that is the
  # ordinary outcome of a review, not a rare one.
  local fixes="" fkey ffrom fto
  for fkey in $(python3 - "$state" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        reviews = json.load(fh).get("friction") or {}
except (OSError, ValueError):
    reviews = {}
for key, node in reviews.items():
    if not isinstance(node, dict):
        continue
    if ((node.get("project_from") and node.get("project_to"))
            or (node.get("from") and node.get("to")) or node.get("verdict")):
        print(key)
PY
  ); do
    # A review commits into the product now, on the feature's branch: that
    # range, read in the worktree. A state from before then may still carry
    # an orchestrator range, read where it was made.
    local fgit="$wt"
    ffrom="$(state_get "$state" "friction.$fkey.project_from" || true)"
    fto="$(state_get "$state" "friction.$fkey.project_to" || true)"
    if [[ -z "$ffrom" || -z "$fto" ]]; then
      fgit="$INSTRUMENTS"
      ffrom="$(state_get "$state" "friction.$fkey.from" || true)"
      fto="$(state_get "$state" "friction.$fkey.to" || true)"
    fi
    if [[ -n "$ffrom" && -n "$fto" ]]; then
      while IFS= read -r line; do
        [[ -n "$line" ]] || continue
        fixes+="$fkey"$'\t'"$line"$'\t'"$(git -C "$fgit" diff-tree \
          --no-commit-id --name-only -r "${line%%$'\t'*}" 2>/dev/null \
          | tr '\n' ' ')"$'\n'
      done < <(git -C "$fgit" log --no-merges --format='%h%x09%s' \
                 "$ffrom..$fto" 2>/dev/null || true)
    else
      # No commits: one row carrying the verdict alone, with empty sha and
      # subject. The renderer fills the Change cell from the verdict's note.
      fixes+="$fkey"$'\t'$'\t'$'\n'
    fi
  done

  body="$(SCLAUDE_STEPS="$spec" SCLAUDE_FIXES="$fixes" python3 - "$state" <<'PY' 2>/dev/null
import json, os, sys

ORDER, TITLES = [], {}
for line in os.environ.get("SCLAUDE_STEPS", "").splitlines():
    if "=" in line:
        name, title = line.split("=", 1)
        ORDER.append(name)
        TITLES[name] = title

with open(sys.argv[1]) as fh:
    s = json.load(fh)

slug = s.get("feature", "")
steps = s.get("steps") or {}
current = s.get("step", "")


def when(value):
    # 2026-09-01T08:14:03+03:00 -> 2026-09-01 08:14. Minutes are enough, and
    # the offset only gets in the way in a table.
    if not value:
        return "—"
    return value[:16].replace("T", " ")


# The friction review that followed a step or a fixing session, by its key.
#
# Reviews are kept per subject — `friction.<step>`, `friction.fix-<stage>-<n>`
# — so the column is a lookup rather than a scan. An empty cell means the log
# was empty and no review was launched, which is the ordinary case: every step
# and every fixing session gets one offered, and most have nothing to read.
reviews = s.get("friction") or {}


def friction_cell(key):
    """Every friction review for one step or fixing session, one per line.

    A subject can have several: a stalled review is followed by a new
    conversation, and a step that closes twice is reviewed twice. The node's
    own fields describe the latest; the earlier ones are read from their runs
    (session_runs, state.sh).
    """
    node = reviews.get(key)
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)] \
        if isinstance(node, dict) else []
    # A latest pass whose log was empty opened no session, so every run is
    # an earlier review's.
    if not (isinstance(node, dict) and node.get("empty")):
        runs = runs[:-1]
    earlier = []
    for run in runs:
        sid = (run.get("session") or "")[:8]
        if run.get("stalled"):
            word = "stalled"
        elif run.get("done"):
            word = run.get("outcome") or "reviewed"
        else:
            word = "interrupted"
        earlier.append("`%s` %s" % (sid, word) if sid else word)
    return "<br>".join(earlier + [latest_friction_cell(key)])


def latest_friction_cell(key):
    """What became of the latest friction review for one step or fixing session.

    Six answers, because the dash used to stand for four different things and a
    reader could not tell which. Every one of them is written by the
    orchestrator at the moment it happens; nothing here is inferred.
    """
    node = reviews.get(key)
    if not isinstance(node, dict):
        # No node at all: the cycle has not reached this step. Not "there was no
        # friction" — nobody has looked yet.
        return "queued"
    # An empty log, recorded as such by run_friction. The ordinary case: the
    # step ran into no ban worth reporting, so no session was launched.
    if node.get("empty"):
        return "nothing"
    # `done` is asked before the id, and that order is the whole point. The id
    # used to be asked first, on the reasoning that a closed review has none —
    # but a review interrupted between `done` and the clearing of `session` has
    # both, and the column then called a finished review `open` for the rest of
    # the feature's life. `done` is the field that says what happened;
    # `session` only says where to return, and a closed review needs no return.
    if node.get("done"):
        # A closed review keeps its id in `was` so the column can name the
        # conversation. It is a separate field rather than `session` itself:
        # run_friction reads `session` to decide whether to resume, and an id
        # left there sends the next review into the closed conversation instead
        # of a new one.
        was = node.get("was")
        if node.get("unread"):
            # Closed by hand through `sclaude reset`. The entries stayed in
            # .reviewed with nobody reading them.
            verdict = "unread"
        elif node.get("fixed"):
            # The review committed to the orchestrator: HEAD moved while it ran.
            verdict = "fixed"
        else:
            # It read the entries and changed nothing — every ban deliberate.
            verdict = "reviewed"
        return "`%s` %s" % (was[:8], verdict) if was else verdict
    sid = node.get("session")
    if sid:
        if node.get("stalled"):
            # claude exited at the door. The id names a transcript with nothing
            # in it, so there is no conversation to go back to — this one is
            # cleared rather than resumed.
            return "`%s` stalled" % sid[:8]
        # Interrupted with a conversation to return to, and holding the cycle
        # until `sclaude friction` or `sclaude reset` closes it.
        return "`%s` open" % sid[:8]
    return "queued"


def run_friction_cell(name, number, last, status, per_run):
    """The Friction cell for one session of a step.

    The session's own review when it has one. A session still running has had
    none yet: `queued`, whatever an older review of the step says — reading
    the step-wide key there called a reopened review step's live round
    `nothing`, an answer about an earlier pass. The step-wide key, on the last
    row, for a feature from before per-session keys. A dash for the rest:
    a session from before them, or one whose review never ran.
    """
    key = "%s-%d" % (name, number)
    if key in reviews:
        return friction_cell(key)
    if last and status == "in progress":
        return "queued"
    if last and not per_run and name in reviews:
        return friction_cell(name)
    return "—"


def fix_name(stage):
    """A regression-fixing session's name in the tables. The local run is the
    ordinary one and goes unnamed; a deployed stage is said."""
    return "fix after regression" if stage == "local" else "fix after %s regression" % stage


def fix_status_cell(stage, number):
    """How one fixing session ended.

    Five answers, and the same reasoning that gave the Friction column its six:
    a dash for every row meant a stage with four fixing sessions could not say
    which of them made it green. Every value is written by regression_gate at
    the moment it happens; nothing here is inferred from the stage's status.

    A row with no record is still a dash. Features that ran before this field
    existed have `fixes` and no `fix_status`, and guessing backwards from how
    the stage finally ended would invent a history nobody observed.
    """
    words = ((s.get("regression") or {}).get(stage) or {}).get("fix_status") or ""
    words = words.split()
    return words[number - 1] if number <= len(words) else "—"


rows = []
for name in ORDER:
    node = steps.get(name) or {}
    session = node.get("session")
    if node.get("done"):
        status = "done"
    elif name == current:
        status = "in progress"
    elif session:
        status = "interrupted"
    else:
        status = "—"
    # One row per conversation the step ran in (step_run, steps.sh). A step
    # re-entered in the same conversation is one row spanning its first start
    # and last exit; a new conversation is a row of its own, numbered. The
    # step's status and friction review belong to its last row; an earlier one
    # either closed the step on a pass since reopened, or was left behind.
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)]
    if not runs:
        # A feature from before `runs`, or a step that opened no session (a
        # clean review): the step's own fields, as they always were.
        rows.append("| %s | %s | %s | %s | %s | %s |" % (
            TITLES[name],
            status,
            "`%s`" % session[:8] if session else "—",
            when(node.get("started")),
            when(node.get("finished")),
            friction_cell(name),
        ))
        continue
    # The friction review follows every session (session_ended), keyed
    # `<step>-<n>` by the session's row — so each row has its own cell. A
    # feature from before that keyed it by the step alone, reviewed at the
    # step's close: that review sits on the last row, and the rows above it
    # had none of their own.
    per_run = any(("%s-%d" % (name, n)) in reviews for n in range(1, len(runs) + 1))
    for number, run in enumerate(runs, start=1):
        last = number == len(runs)
        sid = run.get("session") or ""
        if last:
            run_status = status
            # The later of the last exit and the step's closing: after_step
            # closes it once the session is gone, and a merge can close it
            # days later without one.
            ends = [run.get("finished")]
            if node.get("done"):
                ends.append(node.get("finished"))
            finished = max((e for e in ends if e), default=None)
        else:
            run_status = run.get("outcome") or ("done" if run.get("done") else "interrupted")
            finished = run.get("finished")
        # What the automatic review handed a review session (run_comments).
        comments = run.get("comments")
        said = ""
        if isinstance(comments, int):
            said = " - %d comment%s" % (comments, "" if comments == 1 else "s")
        rows.append("| %s | %s | %s | %s | %s | %s |" % (
            TITLES[name] + (" (%d)" % number if len(runs) > 1 else "") + said,
            run_status,
            "`%s`" % sid[:8] if sid else "—",
            when(run.get("started")),
            when(finished),
            run_friction_cell(name, number, last, run_status, per_run),
        ))

# The fixing sessions, as rows of their own beneath the steps.
#
# In the same table rather than a second one: they are part of the same story,
# and a reader following a feature top to bottom should not have to find where
# the second table starts.
#
# Status used to be a dash here, on the reasoning that a fixing session has no
# step status to report. That much is still true — it has no `done` in `steps`,
# and the step words do not apply to it — but it was the wrong question. A
# fixing session has an outcome, regression_gate knows it exactly at the moment
# it happens, and the dash threw it away: a stage with four of them showed four
# identical cells, one of which had made it green.
#
# The times are the session's own, from fix_started and fix_finished, which
# regression_fix writes aligned with `fixes`. Features that ran before those
# fields existed fall back to the friction review's times, which is all they
# recorded; a row with neither carries dashes and still earns its place — it
# says the session happened.
STAGE_ORDER = ("local", "preview", "prod")
for stage in STAGE_ORDER:
    ids = ((s.get("regression") or {}).get(stage) or {}).get("fixes") or ""
    stage_node = (s.get("regression") or {}).get(stage) or {}
    starts = (stage_node.get("fix_started") or "").split()
    ends = (stage_node.get("fix_finished") or "").split()
    for number, short in enumerate(ids.split(), start=1):
        key = "fix-%s-%d" % (stage, number)
        node = reviews.get(key) if isinstance(reviews.get(key), dict) else {}
        if number <= len(starts) and starts[number - 1] != "-":
            end = ends[number - 1] if number <= len(ends) else ""
            node = {"started": starts[number - 1],
                    "finished": "" if end == "-" else end}
        rows.append("| %s (%d) | %s | `%s` | %s | %s | %s |" % (
            fix_name(stage),
            number,
            fix_status_cell(stage, number),
            short,
            when(node.get("started")),
            when(node.get("finished")),
            friction_cell(key),
        ))

# The epilogues: the sessions that rewrite the status section in the issue and
# its parents. They run several times in a feature's life — after the preview,
# after production — and each conversation is a row, like every other claude
# session the orchestrator starts.
epilogue_runs = [r for r in ((s.get("epilogue") or {}).get("runs") or [])
                 if isinstance(r, dict)]
for number, run in enumerate(epilogue_runs, start=1):
    sid = run.get("session") or ""
    rows.append("| status update%s | %s | %s | %s | %s | — |" % (
        " (%d)" % number if len(epilogue_runs) > 1 else "",
        "done" if run.get("done") else "interrupted",
        "`%s`" % sid[:8] if sid else "—",
        when(run.get("started")),
        when(run.get("finished")),
    ))

# The retrospective before the clean-up (retro.sh): one more conversation, the
# last one, and a row like the rest.
retro_runs = [r for r in ((s.get("retro") or {}).get("runs") or [])
              if isinstance(r, dict)]
for number, run in enumerate(retro_runs, start=1):
    sid = run.get("session") or ""
    rows.append("| retrospective%s | %s | %s | %s | %s | — |" % (
        " (%d)" % number if len(retro_runs) > 1 else "",
        "done" if run.get("done") else "interrupted",
        "`%s`" % sid[:8] if sid else "—",
        when(run.get("started")),
        when(run.get("finished")),
    ))

if current == "done":
    head = "all steps complete"
else:
    index = ORDER.index(current) + 1 if current in ORDER else 0
    head = "step %d/%d %s" % (index, len(ORDER), TITLES.get(current, current))

out = [
    "<!-- sclaude:%s -->" % slug,
    "**Feature `%s`** · %s" % (slug, head),
    "",
    "| Step | Status | Session | Started | Finished | Friction |",
    "|---|---|---|---|---|---|",
    *rows,
    "",
]

line = "Branch `%s`" % s.get("branch", "")
if s.get("pr"):
    line += " · PR #%s" % s["pr"]
out.append(line)

wt = s.get("worktree") or ""
out.append("Worktree `%s`%s" % (
    wt.rsplit("/", 1)[-1],
    " — removed" if s.get("cleaned") else "",
))

# The regression, and what it cost.
#
# Two lines rather than columns in the table above: a stage is not a step. The
# table's rows are the cycle's four steps, and a reader who found "preview red
# on e2e" wedged into one of them would reasonably conclude the step itself had
# failed. These stand underneath, where they read as what they are — what the
# machine checked, and what it had to do about it.
#
# Absent entirely when nothing has run: a feature that never reached a
# regression should not carry a line saying so.
STAGES = ("local", "preview", "prod")
regression = s.get("regression") or {}
verdicts = []
for stage in STAGES:
    node = regression.get(stage) or {}
    status = node.get("status")
    if not status:
        continue
    if status == "passed":
        verdicts.append("%s green" % stage)
    elif status == "failed":
        where = node.get("failed_at")
        verdicts.append("%s red%s" % (stage, " on `%s`" % where if where else ""))
    elif status == "running":
        verdicts.append("%s running" % stage)
if verdicts:
    out.append("Regression: %s" % ", ".join(verdicts))

# A step that went into the background, which by design cannot happen.
#
# sclaude refuses to start a step without a terminal now, so nothing writes this
# field any more. It is still read: features started by an earlier sclaude carry
# it, and their summaries should say what happened rather than leave the reader
# to wonder why the cycle stopped moving. A backgrounded step never reaches
# after_step, so it got no next step and no friction review.
backgrounded = [TITLES.get(name, name) for name in ORDER
                if (steps.get(name) or {}).get("bg")]
if backgrounded:
    out.append(
        "⚠ Ran in the background: %s. By design there are no background runs —"
        " a step with no terminal is now refused rather than detached. This one"
        " predates that, and the cycle stopped after it: no next step and no"
        " friction review were started."
        % ", ".join(backgrounded))

# The address the preview regression was aimed at. A reader of the issue can
# open the deployment QA is looking at without going to find it.
preview_url = (regression.get("preview") or {}).get("url")
if preview_url:
    out.append("Preview: %s" % preview_url)

# What the friction reviews changed in the orchestrator.
#
# A second table rather than more columns in the first: these rows are not the
# feature's steps. One review can produce several commits, and a step that met
# no friction produces none — neither shape fits a row-per-step table, and
# wedging them in would make the first table lie about what a row is.
#
# Only reviews that committed appear. A review that read the entries and found
# every ban deliberate is a proper outcome and is already reported in the
# Friction column above; repeating it here as an empty row would say nothing.
# When no review changed anything the whole section is absent.
#
# The subjects come from `git log` in ~/instruments, gathered by issue_sync —
# see the comment there. Conventional Commits already name the kind of change,
# so the subject is printed as it stands rather than parsed into a verdict.
def fix_label(key):
    """The step or fixing session a review belonged to, as a reader knows it."""
    if key.startswith("fix-"):
        rest = key[4:]
        stage, _, number = rest.rpartition("-")
        return "%s (%s)" % (fix_name(stage), number) if stage else rest
    # A step session's review, `review-3`: named as its row in the first table.
    step, _, number = key.rpartition("-")
    if step in TITLES and number.isdigit():
        return "%s (%s)" % (TITLES[step], number)
    return TITLES.get(key, key)


fix_rows = []
for line in os.environ.get("SCLAUDE_FIXES", "").splitlines():
    key, tab, rest = line.partition("\t")
    if not tab:
        continue
    sha, tab, rest = rest.partition("\t")
    if not tab:
        continue
    subject, _, files = rest.partition("\t")
    fix_rows.append((key, sha, subject, files.split()))


# The verdict of one row. The review gives one for all of its work, and when it
# is a single kind every row carries it: the review read the entries and the
# commits do not say more than it did. `mixed` is the one word that tells a
# reader nothing about any particular row, so there each commit is judged by
# what it touched — known-denials.txt alone is a ban confirmed, anything else
# changed the orchestrator. Putting entries off commits nothing (the deferred
# file is local state, deferred.sh), so a `mixed` review with no commit lifted
# nothing: what is left of it is both of the other kinds.
KNOWN_PATH = "sclaude/known-denials.txt"


def row_verdict(verdict, sha, files):
    if verdict != "mixed":
        return [verdict] if verdict else []
    if not sha:
        return ["deliberate", "deferred"]
    if any(f != KNOWN_PATH for f in files):
        return ["lifted"]
    if KNOWN_PATH in files:
        return ["deliberate"]
    # A commit whose paths were not read back says nothing either way; the
    # review's own word is then all there is.
    return ["mixed"]


if fix_rows:
    out += [
        "",
        "**What the friction reviews changed**",
        "",
        "| Step | Verdict | Commit | Change |",
        "|---|---|---|---|",
    ]
    # Every row names its step and its verdict, even when the row above had
    # the same: a reader scanning one row should not have to look up the table
    # to learn whose commit it is, and a verdict per review rather than per
    # commit is what made `mixed` necessary at all.
    for key, sha, subject, files in fix_rows:
        node = reviews.get(key) if isinstance(reviews.get(key), dict) else {}
        kinds = row_verdict(node.get("verdict") or "", sha, files)
        # A row with no commit is a review that changed nothing on purpose. Its
        # Change cell carries the verdict's own note, which is the only account
        # of it there is; a commit's row keeps the subject.
        if sha:
            change = subject.replace("|", "\\|")
        else:
            change = (node.get("verdict_note") or "").replace("|", "\\|")
        out.append("| %s | %s | %s | %s |" % (
            fix_label(key),
            " ".join("`%s`" % k for k in kinds) or "—",
            "`%s`" % sha if sha else "—",
            change,
        ))

out += [
    "",
    "<sub>Written by <code>sclaude</code>. Session ids resume with "
    "<code>claude --resume &lt;id&gt;</code> on the machine that ran them.</sub>",
]
print("\n".join(out))
PY
)" || return 0
  [[ -n "$body" ]] || return 0

  # Our own comment by its marker. gh has its own jq here, no external one is
  # required.
  id="$(gh api "repos/$repo/issues/$issue/comments" --paginate \
        --jq "map(select(.body | startswith(\"<!-- sclaude:$(state_get "$state" feature) -->\"))) | .[0].id" \
        2>/dev/null)" || id=""

  if [[ -n "$id" && "$id" != "null" ]]; then
    gh api --silent -X PATCH "repos/$repo/issues/comments/$id" \
      -f body="$body" >/dev/null 2>&1 \
      || warn "  could not update the summary on issue #$issue"
  else
    gh api --silent -X POST "repos/$repo/issues/$issue/comments" \
      -f body="$body" >/dev/null 2>&1 \
      || warn "  could not comment on issue #$issue"
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
# reach GitHub is "Email edit and show", not "email-edit-and-show".
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

# --- an issue's place on the board -------------------------------------------
#
# An issue the work has started on must not stay in Backlog with an empty start
# date. The board is the only place that shows what a person is busy with right
# now and since which day, and an issue lying untouched all that time while a
# feature runs on it lies about exactly that.
#
# Both fields are set at a feature's start and only forwards: one column changes,
# Backlog → In progress, and only an empty date is filled in. The rest is
# somebody else's decision: "In review" is set by whoever sent it for review,
# "Done" by whoever closed it, the date by whoever knew it; out-arguing them
# would take the board's meaning away.
#
# The columns we move between, and the date field. By name rather than as
# literals through the code: rename a column or a field and there is one place to
# edit — `board` in the project's .sclaude/config.json, read by board_load
# (project.sh) into PROGRESS_FROM (`columns.backlog`) and PROGRESS_TO
# (`columns.progress`). We look a column up by name rather than by an option's
# id: every board has its own ids, whereas the name is what a person sees with
# their eyes, and it is the name that "move it into progress" refers to.
#
# QA_TO (`columns.qa`) is where an issue goes once the preview regression is
# green.
#
# This is the one status sclaude sets that the paragraph above says belongs to a
# human, and the exception is deliberate rather than an oversight. "In review"
# means "I am asking you to look at this", which is a request only the person
# making it can make. "In QA" means something a machine can establish and a
# person cannot without repeating the work: the branch is deployed, and every
# test passed against the deployment. Claiming that is not taking the board's
# meaning away — it is filling in the one column whose entry condition is
# checkable.
#
# It is still only from the column before it (QA_FROM, which is
# `columns.progress` again): a human who has moved the issue somewhere
# themselves keeps it there. The one exception is qa_retest (deploy.sh): an
# issue QA accepted is taken back from Done when a new preview replaces the
# code they accepted, for the same checkable reason.
#
# QA_DONE (`columns.done`) is the column QA ends in, named although sclaude
# never writes it.
#
# It is a human's to set — that is the rule the paragraphs above are about — but
# it still has to be recognised, because a board can reach it without us: a
# merge carrying `Closes #N` closes the issue, and a project with the "Item
# closed" workflow enabled moves the item to Done in the same second. An issue
# that got there is past QA, not waiting for it, and watch_start reads this to
# tell one from the other.
#
# bin/sclaude-watch needs the same names and runs from a timer with none of
# these modules sourced, so watch_start writes them into the watch file.
#
# PROGRESS_DATE_FIELD is `dates.start`; PROGRESS_END_FIELD (`dates.end`) is the
# end of a bar on the Gantt chart. Issues have no field of their own for the
# fact of finishing, and there is no reason to create one: Roadmap draws a bar
# from a pair of DATE fields, and there are exactly two in the repository —
# "Start date" and "Target date". The computed "Closed" that GitHub maintains
# itself does not enter that choice, so an issue's closing date is invisible to
# the chart. We take "Target date": it was filled in by hand the same way — on #9
# it coincides with the day the issue was closed.

# Where an issue lies on the boards: one line per item of it, as
# `key=value` pairs separated by tabs —
#
#   item=<id> project=<id> board=<name>
#   status_field=<id> status_option=<id> status=<current column>
#
# As pairs rather than positions: there is more than one field here, and
# positional parsing would have to be edited for every next one. Empty values do
# not lose their keys — the key stays with an empty right-hand side.
#
# Empty output means the issue is on no board at all: there is nothing to move,
# and that is not an error. Exit code 1 means the request did not go through.
#
# In one request rather than three: the ids of the item, the board, the field and
# its options come from one place and cannot diverge between calls.
# The third argument is the column being moved to, and it decides which option
# id comes back resolved: a board names its columns, but the mutation wants an
# id, and only this query knows both. It defaults to PROGRESS_TO so the original
# caller reads as it always did.
#
# The number may be a pull request's: it shares the issues' numbering and sits
# on the same boards, and pr_board_set moves it through this same reader.
# `repository.issue` answers null for a pull request, `issueOrPullRequest` for
# both.
issue_status_items() {
  local repo="$1" number="$2" owner name json

  owner="${repo%%/*}"
  name="${repo##*/}"

  json="$(gh api graphql \
    -f owner="$owner" -f name="$name" -F number="$number" \
    -f query='
      query($owner:String!, $name:String!, $number:Int!) {
        repository(owner:$owner, name:$name) {
          issueOrPullRequest(number:$number) {
            ... on Issue { id projectItems(first:10) { ...items } }
            ... on PullRequest { id projectItems(first:10) { ...items } }
          }
        }
      }
      fragment items on ProjectV2ItemConnection {
        nodes {
          id
          project { id title }
          fieldValueByName(name:"Status") {
            ... on ProjectV2ItemFieldSingleSelectValue {
              name
              field {
                ... on ProjectV2SingleSelectField { id options { id name } }
              }
            }
          }
        }
      }' 2>/dev/null)" || return 1

  SCLAUDE_ITEMS_JSON="$json" python3 - "${3:-$PROGRESS_TO}" <<'PY' 2>/dev/null
import json, os, sys

want = sys.argv[1]
try:
    data = json.loads(os.environ["SCLAUDE_ITEMS_JSON"])
except ValueError:
    sys.exit(1)

repo = (data.get("data") or {}).get("repository") or {}
issue = repo.get("issueOrPullRequest") or repo.get("issue") or {}
for item in (issue.get("projectItems") or {}).get("nodes") or []:
    project = item.get("project") or {}
    if not project.get("id"):
        continue

    status = item.get("fieldValueByName") or {}
    field = status.get("field") or {}
    # Case and surrounding spaces ignored, as column_is does in the shell:
    # the name comes from .sclaude/config.json, typed apart from the board.
    option = next((o["id"] for o in field.get("options") or []
                   if (o.get("name") or "").strip().casefold()
                   == (want or "").strip().casefold()), "")

    row = {
        "item": item["id"],
        "project": project["id"],
        "board": project.get("title") or "",
        # Empty when the board has no "In progress" column: there is nowhere to
        # move to.
        "status_field": field.get("id") or "" if option else "",
        "status_option": option,
        "status": status.get("name") or "",
    }
    print("\t".join("%s=%s" % (k, v) for k, v in row.items()))
PY
}

# The start date is a field of the issue itself rather than of the board.
#
# On the board "Start date" is shown as a column, and at first glance it is where
# Status is. But GitHub answers a write to it in plain words: "Issue field
# values cannot be updated using the updateProjectV2ItemFieldValue mutation».
# Issue fields (`repository.issueFields`) are a separate, newer mechanism: the
# value lives on the issue and is equally visible from every board it has landed
# on. Hence the difference in the code: the column is edited on each project
# item, the date once on the issue.
#
# Prints `<issue id>\t<field id>\t<date or empty>`; empty output means the
# repository has no field with that name or it is not a date one. Exit code 1
# means the request did not go through.
issue_date_field() {
  local repo="$1" number="$2" want="$3" owner name json

  owner="${repo%%/*}"
  name="${repo##*/}"

  json="$(gh api graphql \
    -f owner="$owner" -f name="$name" -F number="$number" \
    -f query='
      query($owner:String!, $name:String!, $number:Int!) {
        repository(owner:$owner, name:$name) {
          issueFields(first:50) {
            nodes { ... on IssueFieldDate { id name dataType } }
          }
          issue(number:$number) {
            id
            issueFieldValues(first:50) {
              nodes {
                ... on IssueFieldDateValue {
                  value
                  field { ... on IssueFieldDate { id } }
                }
              }
            }
          }
        }
      }' 2>/dev/null)" || return 1

  SCLAUDE_DATE_JSON="$json" python3 - "$want" <<'PY' 2>/dev/null
import json, os, sys

want = sys.argv[1]
try:
    data = json.loads(os.environ["SCLAUDE_DATE_JSON"])
except ValueError:
    sys.exit(1)

repo = (data.get("data") or {}).get("repository") or {}
issue = repo.get("issue") or {}
if not issue.get("id"):
    sys.exit(0)

# We take the field from the repository's list of fields rather than from the
# issue's value: an empty value is not in the list at all, and the id to write by
# would disappear along with it. dataType guards against a field of the same name
# with a different type: a `dateValue` will not go into one.
field = next((f for f in repo.get("issueFields", {}).get("nodes") or []
              if f.get("name") == want and f.get("dataType") == "DATE"), None)
if not field:
    sys.exit(0)

current = ""
for value in (issue.get("issueFieldValues") or {}).get("nodes") or []:
    if ((value.get("field") or {}).get("id")) == field["id"]:
        current = value.get("value") or ""
        break

print("\t".join([issue["id"], field["id"], current]))
PY
}

# Moves an issue from Backlog to In progress and, if the start date is empty,
# sets today's.
#
# The date is not tied to the column's transition: "the work has started" is
# today regardless of where the issue lay on the board, and an empty field on an
# issue a feature is running on is as untrue as its Backlog. We never touch a
# date already set: it stands there because somebody put it there.
#
# It breaks nothing: no gh, no network, no project permission, the issue not on a
# board — a warning or silence, and the cycle goes on. A place on the board is
# the same reporting as the milestone and the summary above, not a condition of
# the work.
issue_start_progress() {
  local issue="$1" repo

  issue_move_status "$issue" "$PROGRESS_FROM" "$PROGRESS_TO"

  # The date is not part of the move: an issue on no board at all still has a
  # start date worth filling in, which is why this is not inside the walk.
  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0
  issue_start_date "$repo" "$issue"
  return 0
}

# Moves an issue into "In QA" once the preview regression is green.
#
# The same shape as issue_start_progress and for the same reasons: one column
# forward, only from the column the cycle itself put the issue in, and silence
# about anything a human has moved elsewhere. What differs is only which pair of
# columns, so the walk over the boards is shared rather than copied — see
# issue_move_status below.
#
# Called after the preview regression passes, which is what makes the claim
# checkable: the branch is deployed and the suite ran against the deployment.
#
# From Backlog as well as from In progress: QA hands a feature back with either,
# and the fix goes back to QA the same way whichever one they chose. Left in
# Backlog, the issue never reached In QA again and the wait for QA never ended.
issue_qa_ready() {
  issue_move_status "$1" "$QA_FROM" "$QA_TO" "$PROGRESS_FROM"
}

# Where the issue lies right now — one column name, or nothing.
#
# A reader rather than a mover, and the only one: everything else here writes.
# It exists because a caller sometimes has to know the column before deciding
# whether to act at all, and watch_start is that caller — arming a QA watch on
# an issue already past QA makes the watcher report a move that happened before
# anybody was waiting for it.
#
# The boards are walked the way issue_move_status walks them, and the first
# non-empty status wins. More than one board is possible and they can disagree;
# a single answer is still the right shape here, because the question being
# asked is "has this issue been dealt with somewhere", and one board saying yes
# settles it.
#
# Silence on every failure, exactly like the movers: no gh, no network, no
# project scope, the issue on no board. The caller cannot tell those apart from
# "no column", and must not need to — an empty answer means "nothing known",
# and the safe reading of that is to carry on as before.
issue_status_now() {
  local issue="$1" repo rows line key value status

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0
  rows="$(issue_status_items "$repo" "$issue")" || return 0

  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    status=""
    while IFS='=' read -r key value; do
      [[ "$key" == "status" ]] && status="$value"
    done < <(tr '\t' '\n' <<< "$line")
    if [[ -n "$status" ]]; then
      echo "$status"
      return 0
    fi
  done <<< "$rows"
  return 0
}

# The walk both movers share: read where the issue lies on every board, and move
# the ones that are still in `from` — or in the optional fourth argument, a
# second column that counts as `from`.
#
# Failure is never fatal here. A board is a convenience, and a feature whose
# cycle stopped because a column could not be written would be a worse trade
# than a column that is briefly wrong.
issue_move_status() {
  local issue="$1" from="$2" to="$3" also="${4:-}" repo rows
  local item project board status_field status_option status

  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  # A column the project does not name is a move it does not make. A project
  # with no `board` section at all is told so once per command: before the
  # names moved into .sclaude/config.json every project got the same four columns,
  # and one configured back then would otherwise lose its board in silence.
  # A section that leaves a column out is a choice and is not remarked on.
  if [[ -z "$from" || -z "$to" ]]; then
    if [[ -z "${BOARD_NOTED:-}" ]] && ! project_has board; then
      BOARD_NOTED=1
      info "Issue #$issue is not moved on the board: .sclaude/config.json has no \`board\`"
      info "  section naming its columns (see sclaude/config.example.json)."
    fi
    return 0
  fi
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  if ! rows="$(issue_status_items "$repo" "$issue" "$to")"; then
    warn "  could not read issue #$issue on the board; if the token lacks the right: gh auth refresh -s project"
    return 0
  fi

  local line key value
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    item=""; project=""; board=""; status_field=""; status_option=""; status=""
    while IFS='=' read -r key value; do
      case "$key" in
        item)          item="$value" ;;
        project)       project="$value" ;;
        board)         board="$value" ;;
        status_field)  status_field="$value" ;;
        status_option) status_option="$value" ;;
        status)        status="$value" ;;
      esac
    done < <(tr '\t' '\n' <<< "$line")
    [[ -n "$item" && -n "$status_field" ]] || continue

    if ! column_is "$status" "$from" && ! column_is "$status" "$also"; then
      column_is "$status" "$to" \
        || info "Issue #$issue is '${status:-no status}' on '$board' — left as it is."
    elif gh project item-edit --id "$item" --project-id "$project" \
           --field-id "$status_field" --single-select-option-id "$status_option" \
           >/dev/null 2>&1; then
      info "Issue #$issue moved to '$to' on '$board'."
    else
      warn "  could not move issue #$issue to '$to' on '$board' — do it by hand"
    fi
  done <<< "$rows"
  return 0
}

# Puts a pull request into a column on every board it is on — from wherever it
# lies, unlike issue_move_status, which moves only from the column the cycle
# itself put an issue in.
#
#   pr_board_set <pr> <column> [issue]
#
# The difference is deliberate. An issue's column is QA's voice and a person's
# move must never be undone; a pull request's column says only where it stands
# in the cycle, and the two moments that set it — QA accepting every issue, and
# the merge — are facts sclaude has just established. A board's own workflows
# may set it too (a merged PR to Done); writing the same column twice costs
# nothing.
#
# A PR on no board is put on the boards its issue is on: a column cannot be
# set on a board the PR is absent from, and the issue's boards are where people
# look for the work.
#
# It breaks nothing: an undeclared column, no gh, no project scope — silence or
# a warning. Exit 1 when a warning was given, so the hand-off knows it is not
# finished and tries again.
pr_board_set() {
  local pr="$1" to="$2" issue="${3:-}" repo rows line key value failed=0
  local item project board status_field status_option status

  [[ "$pr" =~ ^[0-9]+$ && -n "$to" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  if ! rows="$(issue_status_items "$repo" "$pr" "$to")"; then
    warn "  could not read PR #$pr on the board; if the token lacks the right: gh auth refresh -s project"
    return 1
  fi

  if [[ -z "$rows" && -n "$issue" && "$issue" != "null" ]]; then
    local pr_id projects
    pr_id="$(gh api "repos/$repo/pulls/$pr" --jq .node_id 2>/dev/null)" || pr_id=""
    projects="$(issue_status_items "$repo" "$issue" "$to" 2>/dev/null \
                  | tr '\t' '\n' | sed -n 's/^project=//p' | sort -u)" || projects=""
    for project in $projects; do
      [[ -n "$pr_id" ]] || break
      gh api graphql -f p="$project" -f c="$pr_id" \
        -f query='mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}' \
        >/dev/null 2>&1 \
        || { warn "  could not put PR #$pr on the board of issue #$issue"; failed=1; }
    done
    [[ -n "$projects" ]] && rows="$(issue_status_items "$repo" "$pr" "$to" 2>/dev/null)"
  fi

  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    item=""; project=""; board=""; status_field=""; status_option=""; status=""
    while IFS='=' read -r key value; do
      case "$key" in
        item)          item="$value" ;;
        project)       project="$value" ;;
        board)         board="$value" ;;
        status_field)  status_field="$value" ;;
        status_option) status_option="$value" ;;
        status)        status="$value" ;;
      esac
    done < <(tr '\t' '\n' <<< "$line")
    [[ -n "$item" ]] || continue
    column_is "$status" "$to" && continue
    if [[ -z "$status_field" ]]; then
      info "PR #$pr is not moved on '$board': it has no '$to' column."
    elif gh project item-edit --id "$item" --project-id "$project" \
           --field-id "$status_field" --single-select-option-id "$status_option" \
           >/dev/null 2>&1; then
      info "PR #$pr moved to '$to' on '$board'."
    else
      warn "  could not move PR #$pr to '$to' on '$board' — do it by hand"
      failed=1
    fi
  done <<< "$rows"
  return "$failed"
}

# QA has accepted the work: hand the pull request over to whoever merges it.
#
#   pr_qa_handoff <wt> <pr> <issue>   → 0 when handed over (now or before)
#
# Only once every issue the PR closes is in the Done column — a PR closing two
# issues is not ready because QA accepted one of them. Then, in one go:
#
#   * the draft is marked ready, which is what lets anybody merge it;
#   * the PR goes to the backlog column: it now waits for a person, the merger,
#     and is nobody's work in progress;
#   * its assignees are cleared — the author's part is over, and whoever picks
#     the merge up assigns themselves;
#   * a summary comment says what the merge decision rests on (pr_handoff.py
#     summary), so the merger does not have to open the issue.
#
# Once per head. The state records the head handed over, so a resume does not
# undo a person's later moves or post the summary again; QA accepting a newer
# head after a return hands it over afresh, and the summary is rewritten in
# place. A head is recorded only when every step went through: each one is
# safe to repeat, so a partial hand-off is simply tried again.
#
# The exit code says which of these happened, because the timer acts on it
# rather than on the words printed:
#
#   0  handed over now
#   1  not yet — QA has not accepted another of the PR's issues, or GitHub did
#      not answer; worth asking again
#   2  never — the PR is merged or closed, there is none, or the board declares
#      no Done column; asking again would change nothing
#   3  handed over before, for this head
#   4  handed over in part — a step warned, and the next try repeats it
#
# Two callers can reach this at once: sclaude waiting for QA in a terminal,
# and the timer (bin/sclaude-watch) when nobody is. Both see the same Done
# within the same few minutes, and without a lock both would post the summary.
# The second one in waits, then finds the head already handed over.
#
# Breaks nothing, like the rest of this file: every step is a warning at worst.
pr_qa_handoff() {
  [[ -d "$1/.sclaude/local/feature" ]] || return 2
  ( flock -w 120 9 || exit 1; pr_qa_handoff_now "$@" ) 9>"$1/.sclaude/local/feature/handoff.lock"
}

pr_qa_handoff_now() {
  local wt="$1" pr="$2" issue="${3:-}"
  local state="$wt/.sclaude/local/feature/state.json" repo view head draft
  local -a waiting=() numbers=()

  [[ "$pr" =~ ^[0-9]+$ && -n "$QA_DONE" ]] || return 2
  command -v gh >/dev/null 2>&1 || return 1
  repo="$(gh_repo)" || return 1
  [[ -n "$repo" ]] || return 1
  view="$(gh pr view "$pr" --repo "$repo" --json state,headRefOid,isDraft \
            --jq '[.state, .headRefOid, (.isDraft|tostring)] | @tsv' 2>/dev/null)" || return 1
  local pr_state failed=0
  IFS=$'\t' read -r pr_state head draft <<<"$view"
  [[ -n "$head" ]] || return 1
  [[ "$pr_state" == OPEN ]] || return 2
  [[ "$(state_get "$state" handoff 2>/dev/null || true)" == "$head" ]] && return 3

  local n column
  while IFS= read -r n; do
    [[ -n "$n" ]] || continue
    numbers+=("$n")
    column="$(issue_status_now "$n" 2>/dev/null || true)"
    column_is "$column" "$QA_DONE" || waiting+=("#$n (${column:-no status})")
  done < <(python3 "$LIB/pr_handoff.py" tickets "$wt" "$pr" "$issue" 2>/dev/null)
  [[ "${#numbers[@]}" -gt 0 ]] || return 1
  if [[ "${#waiting[@]}" -gt 0 ]]; then
    echo ""
    info "PR #$pr stays a draft: QA has not accepted ${waiting[*]} yet."
    return 1
  fi

  echo ""
  say "${BOLD}QA accepted every issue of PR #$pr — handing it over for the merge.${OFF}"
  if [[ "$draft" == true ]]; then
    if gh pr ready "$pr" --repo "$repo" >/dev/null 2>&1; then
      info "PR #$pr marked ready for review."
    else
      warn "  could not mark PR #$pr ready — do it by hand (Ready for review)"
      failed=1
    fi
  fi
  pr_board_set "$pr" "$PROGRESS_FROM" "$issue" || failed=1

  local assignees
  assignees="$(gh pr view "$pr" --repo "$repo" --json assignees \
                 --jq '[.assignees[].login] | join(",")' 2>/dev/null)" || { assignees=""; failed=1; }
  if [[ -n "$assignees" ]]; then
    if gh pr edit "$pr" --repo "$repo" --remove-assignee "$assignees" >/dev/null 2>&1; then
      info "PR #$pr unassigned ($assignees) — the merge is whoever picks it up."
    else
      warn "  could not unassign PR #$pr — do it by hand"
      failed=1
    fi
  fi

  local note="$wt/.sclaude/local/feature/merge-ready.md" posted=failed
  if python3 "$LIB/pr_handoff.py" summary "$wt" "$pr" "$state" "$QA_DONE" "${numbers[@]}" \
       > "$note" 2>/dev/null && [[ -s "$note" ]]; then
    posted="$(python3 "$LIB/pr_handoff.py" comment "$wt" "$pr" "$note" 2>/dev/null)" || posted=failed
  fi
  rm -f "$note"
  case "$posted" in
    posted|edited) info "PR #$pr: the summary for the merge is in its conversation." ;;
    *)             warn "  could not write the merge summary on PR #$pr"; failed=1 ;;
  esac
  if [[ "$failed" -ne 0 ]]; then
    info "  The hand-off of PR #$pr is incomplete; it is tried again on the next look."
    return 4
  fi
  state_set "$state" handoff "$head" 2>/dev/null || true
  return 0
}

# Puts today's date into an empty field — shared by both ends of the bar. A
# separate function rather than the tail of one particular thing: the board and
# an issue's fields are different GitHub mechanisms, and an issue having no board
# at all is no reason to leave it without dates.
#
# We never touch a filled field and stay quiet about it: the date stands there
# because somebody put it there, and there is nothing to say.
issue_set_date() {
  local repo="$1" issue="$2" field_name="$3" said="$4"
  local row id field current today

  [[ -n "$field_name" ]] || return 0
  row="$(issue_date_field "$repo" "$issue" "$field_name")" || {
    warn "  could not read '$field_name' on issue #$issue"
    return 0
  }
  [[ -n "$row" ]] || return 0

  IFS=$'\t' read -r id field current <<< "$row"
  [[ -n "$id" && -n "$field" ]] || return 0
  [[ -z "$current" ]] || return 0

  today="$(date +%F)"
  if gh api graphql --silent \
       -f issue="$id" -f field="$field" -f date="$today" \
       -f query='
         mutation($issue:ID!, $field:ID!, $date:String!) {
           setIssueFieldValue(input:{
             issueId: $issue,
             issueFields: [{fieldId: $field, dateValue: $date}]
           }) { clientMutationId }
         }' >/dev/null 2>&1; then
    info "Issue #$issue $said ($today)."
  else
    warn "  could not set '$field_name' on issue #$issue — set it by hand if it matters"
  fi
  return 0
}

# The work's start: today, if the field is empty.
issue_start_date() {
  issue_set_date "$1" "$2" "$PROGRESS_DATE_FIELD" "starts today"
}

# The work's end — by the pull request's merge.
#
# The merge rather than the issue's closing: GitHub closes it itself, by
# `Closes #N`, and sclaude takes no part at that moment. The nearest point where
# it looks at the world again is the cycle's epilogue, and the merge is already
# visible there. The difference between the two moments is the seconds of one
# press.
#
# Today's date rather than the issue's `closedAt`: a bar on the Gantt chart must
# end when the work ended, and the epilogue follows the merge. They diverge only
# if the human came back to a postponed epilogue the next day, and then an extra
# day of bar is more honest than a missing date.
issue_end_date() {
  issue_set_date "$1" "$2" "$PROGRESS_END_FIELD" "ends today"
}

# --- a feature's outcome -----------------------------------------------------
#
# A closed sub-issue changes an epic's state, but the epic says nothing about it:
# to understand where it stands, the children had to be opened one by one. #59
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
# keeps no record. That costs nothing there: a cleaned-up feature is reached
# only by naming it, never by the menu offering it.
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
  if [[ -n "$wt" ]]; then
    fingerprint="$(status_fingerprint "$wt" "$pr" "$merged" "$preview" "$prod" || true)"
    if [[ -n "$fingerprint" ]] \
       && [[ "$fingerprint" == "$(state_get "$wt/.sclaude/local/feature/state.json" status.fingerprint 2>/dev/null || true)" ]]; then
      echo ""
      info "The status in issue #$issue already describes this — nothing changed, skipping."
      info "  To write it again anyway: $SELF epilogue $slug"
      return 0
    fi
  fi

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

  echo ""
  echo "${BOLD}${BLUE}── $slug · current status in issue #$issue and its parents ──${OFF}"
  info "   sonnet / medium / auto · $REPO"
  info "   chain: $(tr '\n' ' ' <<< "$numbers")${labels:+ · labels: $labels}"
  echo ""

  # Our own state goes in the main repository: the feature's tree is gone, and
  # there is nowhere to write into .sclaude/local/feature/state.json. The details are in
  # epilogue_state (state.sh).
  #
  # We name the session ourselves and write the id BEFORE launching: otherwise an
  # interrupted epilogue is lost entirely — the feature is closed, the menu will
  # not show it, and the section in the issue silently stays as it was.
  local estate session
  estate="$(epilogue_state "$slug")" || estate=""
  if [[ -n "$estate" ]]; then
    session="$(state_get "$estate" session || true)"
    if [[ -n "$session" ]] && ! live_session "$REPO" "$session" >/dev/null; then
      session=""
    fi
  fi

  local -a extra; mapfile -t extra < <(status_settings)

  # Every claude conversation belongs in the issue's table, the epilogue's
  # included. Recorded in the feature's state while there is one; the id is
  # named in advance even when there is no epilogue state, so the row has one.
  local fstate=""
  [[ -n "$wt" && -f "$wt/.sclaude/local/feature/state.json" ]] && fstate="$wt/.sclaude/local/feature/state.json"
  [[ -n "${session:-}" ]] || session="$(new_session_id)"
  [[ -n "$fstate" ]] && session_runs "$fstate" epilogue open "$session"

  session_watch_start "" "$session" "$done_file" "$REPO"
  if [[ -n "$estate" && "$session" == "$(state_get "$estate" session 2>/dev/null || true)" ]]; then
    info "   resuming the interrupted epilogue"
    ( cd "$REPO" && claude_launch --resume "$session" --model sonnet --effort medium \
        --permission-mode auto "${extra[@]}" -n "status/$slug" \
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
      ( cd "$REPO" && claude_launch --session-id "$session" --model sonnet --effort medium \
          --permission-mode auto "${extra[@]}" -n "status/$slug" "$prompt" )
    else
      # The state could not be created — we write the epilogue anyway: the
      # section in the issue matters more than the ability to return to an
      # interrupted session.
      ( cd "$REPO" && claude_launch --session-id "$session" --model sonnet --effort medium \
          --permission-mode auto "${extra[@]}" -n "status/$slug" "$prompt" )
    fi
  fi
  session_watch_stop
  # It said its comments are written, and the watcher closed it: the report is
  # printed here, since claude's screen went with it.
  session_closed "$done_file" "$REPO" "$session" \
    "The epilogue reported its comments written, and sclaude closed it." || true
  # Whether it took place, by the transcript rather than the clock — the
  # witness run_step and run_friction use (session_started, state.sh). The
  # clock timed the wrapper, and the row and the epilogue's own state must not
  # give two answers.
  local ran=0
  session_started "$REPO" "$session" && ran=1

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

  if [[ -n "$estate" ]]; then
    if [[ "$ran" -ne 1 ]]; then
      # There used to be a command here that the human had to remember and type
      # themselves. Now there is nothing to type: the menu itself offers to
      # finish an unclosed epilogue, at the very next launch of sclaude.
      #
      # So the line with the command was removed rather than left "just in case".
      # A hint that describes a different path from the one things will actually
      # take is worse than no hint: the human does extra work and then stops
      # trusting the other hints as well. The command has not gone anywhere — it
      # is in --help — but it is no longer the ordinary path.
      warn ""
      warn "  The epilogue did not start — the status in issue #$issue is unchanged."
      warn "  sclaude will offer to finish it the next time you open the menu."
      return 1
    fi
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
  return 0
}
