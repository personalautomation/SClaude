#!/usr/bin/env bash
#
# An issue's place on the project board: its status column, its dates, and
# the pull request's own card and draft state at the handoff to QA.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

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
# themselves keeps it there. The one exception is qa_retest (qa.sh): an
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

# Marks a draft pull request ready for review, so that it can be merged. For a
# change nothing deploys (no_change.sh), which no QA hand-off ever makes ready.
# Breaks nothing: a failure is a warning, and merge_offer names the draft.
#
#   pr_undraft <pr>
pr_undraft() {
  local pr="$1" repo
  [[ "$pr" =~ ^[0-9]+$ ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ "$(gh pr view "$pr" --repo "$repo" --json isDraft --jq .isDraft 2>/dev/null)" == true ]] || return 0
  if gh pr ready "$pr" --repo "$repo" >/dev/null 2>&1; then
    info "PR #$pr marked ready for review."
  else
    warn "  could not mark PR #$pr ready — do it by hand (Ready for review)"
  fi
  return 0
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
  history_add "$state" handoff done
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
