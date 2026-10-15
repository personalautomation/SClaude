#!/usr/bin/env bash
#
# The review of a pull request when the project does not want it in Actions:
# `review` in .sclaude/config.json (project_review_mode).
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# The review workflow runs on a GitHub runner, and the runner is billed by the
# minute for the whole time it waits on the model, on top of the tokens. A
# private repository on the free plan has 2000 such minutes a month, and two
# weeks of reviews spent them. So a project can say where its review runs:
#
#   github  the workflow, as before; nothing here applies.
#   local   sclaude runs the same /code-review on this machine, headless, on
#           the head step 4 opens on and again on each head a review session
#           leaves, and posts its findings as threads on the pull request,
#           as the workflow does (local_review.py). Tokens only, no runner
#           minutes.
#   off     no review at all; step 4 answers only the checks and what people
#           wrote.
#
# Both of the last two put the `no-review` label on the pull request, the
# workflow's own switch: its jobs are then skipped by their condition, and a
# skipped job costs no minutes. The label is asked for at step 3 (pr.md) so the
# pull request is opened with it, and put on again here at step 4 for one
# opened before.

# How the headless review runs. The workflow's own choice: Opus at `medium`.
LOCAL_REVIEW_MODEL="${LOCAL_REVIEW_MODEL:-opus}"
LOCAL_REVIEW_LEVEL="${LOCAL_REVIEW_LEVEL:-medium}"
# A pass that posts this many new findings or more has likely stopped at the
# review's own cap with more left unsaid, so the same range is read again,
# told what was just posted, for the next batch — what the workflow does by
# leaving a capped run's commit unmarked. At most LOCAL_REVIEW_PASSES passes
# a head, so a review that keeps finding cannot hold the step for ever.
LOCAL_REVIEW_CAP="${LOCAL_REVIEW_CAP:-10}"
LOCAL_REVIEW_PASSES="${LOCAL_REVIEW_PASSES:-5}"

# The local review's own files, beside the feature's other scratch. The
# findings are not among them: they are threads on the pull request.
#
#   local-review-rounds.jsonl   one line per run: when, how long, the range,
#                               how many posted and resolved — the rounds the
#                               report counts, and the head last reviewed
#   local-review-unposted.json  findings GitHub would not take yet, posted on
#                               the next call and counted open until then
#   local-review-answer.md      the last run's answer, as the model gave it
#   local-review.log            the last run's stderr
local_review_file() {
  echo "$1/.sclaude/local/feature/local-review$2"
}

# Put the `no-review` label on the pull request when the project's review is
# not GitHub's. Silent and best-effort: a label that could not be put on costs
# one review's minutes, not the step.
#
#   review_label_sync <wt> <pr>
review_label_sync() {
  local wt="$1" pr="$2" mode
  [[ -n "$pr" && "$pr" != "null" ]] || return 0
  mode="$(project_review_mode "$wt")"
  [[ "$mode" == "github" ]] && return 0
  command -v gh >/dev/null 2>&1 || return 0
  ( cd "$wt" || exit 0
    gh pr view "$pr" --json labels --jq '.labels[].name' 2>/dev/null | grep -qx no-review && exit 0
    gh label create no-review --color d4c5f9 \
      --description "Skip the automatic Claude code review on this pull request" >/dev/null 2>&1 || true
    if gh pr edit "$pr" --add-label no-review >/dev/null 2>&1; then
      info "  PR #$pr labelled no-review: this project's review is \`$mode\`, not GitHub's."
    fi
  ) || true
  return 0
}

# Switch the repository's own GitHub Actions workflows off for `review: local`,
# and back on for `github` — the ones this switched off, and no others.
#
#   review_actions_sync <repo root> <mode>
#
# `local` is for when the Actions minutes ran out, and with none left every
# workflow still starts on each push and fails at once — a red run and an
# email each time, about nothing in the code. A disabled workflow does not
# start. This is the repository's setting (`gh workflow disable`), not a
# change to the workflow files, which stay as the project keeps them. Only
# the ones in .github/workflows: what GitHub runs for itself (Dependabot) is
# not the project's to switch. Which ones were switched off is kept in the
# main tree's scratch, so `github` turns back on exactly those, not a
# workflow somebody disabled for a reason of their own. `off` changes
# nothing: no review is not no CI.
review_actions_sync() {
  local root="$1" mode="$2" list id name
  command -v gh >/dev/null 2>&1 || return 0
  list="$root/.sclaude/local/actions-disabled"
  case "$mode" in
    local)
      mkdir -p "$(dirname "$list")" 2>/dev/null || return 0
      while IFS=$'\t' read -r id name; do
        [[ -n "$id" ]] || continue
        if (cd "$root" && gh workflow disable "$id" >/dev/null 2>&1); then
          printf '%s\t%s\n' "$id" "$name" >> "$list"
          info "  GitHub Actions: \"$name\" switched off — it fails without minutes and mails about it."
        else
          warn "  GitHub Actions: could not switch \"$name\" off (gh workflow disable $id)."
        fi
      done < <(cd "$root" && gh api "repos/{owner}/{repo}/actions/workflows" --paginate \
                 --jq '.workflows[] | select(.state == "active" and (.path | startswith(".github/workflows/"))) | "\(.id)\t\(.name)"' 2>/dev/null)
      ;;
    github)
      [[ -s "$list" ]] || return 0
      while IFS=$'\t' read -r id name; do
        [[ -n "$id" ]] || continue
        if (cd "$root" && gh workflow enable "$id" >/dev/null 2>&1); then
          info "  GitHub Actions: \"$name\" switched back on."
        else
          warn "  GitHub Actions: could not switch \"$name\" back on (gh workflow enable $id)."
        fi
      done < "$list"
      rm -f "$list"
      ;;
  esac
  return 0
}

# Review the tree's HEAD on this machine, unless that head has been reviewed
# already; print how many review threads are open.
#
#   local_review <wt> <pr>   → <count> on stdout; 1 when the review did not run
#
# The first run reads the whole pull request (origin/main...HEAD); later runs
# read only the commits since the last head reviewed, as the workflow's review
# reads a push, and check at the new head every thread still open — resolving
# the ones the code no longer has. The count is of every open thread, old and
# new, less the ones the person keeps to resolve by hand: a session that fixed
# half of them and was interrupted finds the other half open on GitHub.
# Everything it says goes to stderr: stdout is the count.
local_review() {
  local wt="$1" pr="$2" head last base scope out count answer repo
  local journal; journal="$(local_review_file "$wt" -rounds.jsonl)"
  head="$(git -C "$wt" rev-parse HEAD 2>/dev/null)" || return 1
  repo="$(REPO="$wt" gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || { warn "  No GitHub repository for $wt: the local review did not run." >&2; return 1; }
  # A thread is posted on a commit of the pull request: a head it does not
  # carry yet cannot take one.
  if ! local_review_pushed "$wt" "$pr"; then
    warn "  ${head:0:7} is not the head of PR #$pr: the local review posts on what the pull request carries. Push, then run $SELF again." >&2
    return 1
  fi
  if python3 "$LIB/local_review.py" cached "$journal" "$head" 2>/dev/null; then
    python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null || return 1
    return 0
  fi
  # From the last head reviewed — or, when this head was left with more to
  # read (a capped pass whose follow-up never ran), over the same range again.
  last="$(python3 "$LIB/local_review.py" since "$journal" "$head" 2>/dev/null || true)"
  if [[ -n "$last" && "$last" != "$head" ]] && git -C "$wt" merge-base --is-ancestor "$last" "$head" 2>/dev/null; then
    base="$last"
    scope="the commits since the last review: \`git diff $base..$head\`"
  else
    base="$(git -C "$wt" merge-base origin/main "$head" 2>/dev/null)" || return 1
    scope="the whole pull request: \`git diff $base..$head\`"
  fi

  command -v claude >/dev/null 2>&1 || { warn "  No claude on this machine: the local review did not run." >&2; return 1; }
  info "  Reviewing PR #${pr:-?} on this machine ($LOCAL_REVIEW_MODEL, $LOCAL_REVIEW_LEVEL): ${base:0:7}..${head:0:7}." >&2
  info "  It takes minutes; Ctrl-C leaves, and the next \`$SELF\` starts it again." >&2

  local earlier began new more cap pass=1
  answer="$(local_review_file "$wt" -answer.md)"
  while :; do
    if ! earlier="$(python3 "$LIB/local_review.py" prompt "$wt" "$pr" "$repo" "$journal" 2>>"$(local_review_file "$wt" .log)")"; then
      warn "  GitHub did not say which findings are open: the local review did not run pass $pass." >&2
      [[ "$pass" -gt 1 ]] || return 1
      count="$(python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null)" || return 1
      break
    fi
    began=$SECONDS
    out="$(cd "$wt" && claude -p "$(local_review_prompt "$pr" "$head" "$scope" "$earlier")" \
             --model "$LOCAL_REVIEW_MODEL" \
             --allowedTools "Read" "Grep" "Glob" "Skill" "Agent" \
               "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git blame:*)" \
             --disallowedTools "Edit" "Write" "NotebookEdit" "Bash(gh:*)" \
               "Bash(git push:*)" "Bash(git commit:*)" \
             2>"$(local_review_file "$wt" .log)")"
    printf '%s\n' "$out" > "$answer"
    # The last pass allowed records no "more": the head is done with what it
    # has, rather than read again on every later call.
    cap="$LOCAL_REVIEW_CAP"; [[ "$pass" -ge "$LOCAL_REVIEW_PASSES" ]] && cap=0
    if ! read -r count new more < <(python3 "$LIB/local_review.py" record "$wt" "$pr" "$repo" "$answer" \
                                      "$base" "$head" "$((SECONDS - began))" "$journal" "$cap" \
                                      2>>"$(local_review_file "$wt" .log)") || [[ -z "${count:-}" ]]; then
      # A later pass that fails leaves the earlier ones recorded: the head
      # counts as reviewed with what they posted.
      if [[ "$pass" -gt 1 ]]; then
        warn "  Pass $pass of the local review was not recorded; the first $((pass - 1)) stand." >&2
        count="$(python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null)" || return 1
        break
      fi
      warn "  The local review was not recorded: no findings count in its answer, or GitHub took none of them." >&2
      warn "  Its answer: $answer; the next \`$SELF\` reviews this head again." >&2
      return 1
    fi
    # By what the pass found, not what GitHub took: a capped pass with a
    # finding refused is still capped.
    if [[ "${more:-0}" != 1 ]]; then
      [[ "$pass" -ge "$LOCAL_REVIEW_PASSES" && "$new" -ge "$LOCAL_REVIEW_CAP" ]] \
        && warn "  Pass $pass still found the cap; stopping at $LOCAL_REVIEW_PASSES passes — more may be left unsaid." >&2
      break
    fi
    pass=$((pass + 1))
    info "  That pass found the cap ($LOCAL_REVIEW_CAP): reading ${base:0:7}..${head:0:7} again for the rest, pass $pass." >&2
  done
  if [[ "$count" -eq 0 ]]; then
    info "  The local review leaves nothing open on PR #$pr." >&2
  else
    info "  The local review leaves $count thread(s) open on PR #$pr." >&2
  fi
  echo "$count"
}

# What the headless review is told. The scope sentence follows the workflow's
# own, so that a local review reads what an Actions one would; what it is told
# about earlier findings is read from the pull request (local_review.py prompt).
#
#   local_review_prompt <pr> <head> <scope> <earlier>
local_review_prompt() {
  local pr="$1" head="$2" scope="$3" earlier="$4"
  cat <<TEXT
You are reviewing pull request #${pr:-?} unattended, on the developer's machine. Nobody will answer a question and nothing will wake you: when you end your turn the run is over, so collect every agent's result within this turn.

Invoke the \`code-review\` skill with the Skill tool, with these arguments on one line:

    $LOCAL_REVIEW_LEVEL <scope>

where <scope> is plain words saying: review $scope; review every changed file in it, none left out as unimportant, generated files may be skimmed; the tree is checked out at $head, so read the code as it is here; do not run the app, or any build or test.${earlier:+ Add to the scope, verbatim, what follows about earlier findings.}
TEXT
  [[ -n "$earlier" ]] && printf '\n%s\n' "$earlier"
  cat <<TEXT

Post nothing to GitHub and change no file: sclaude posts your findings from your answer.

When the skill is done, answer with nothing else. First the new findings, one per section:

### <path>:<line> — <the finding in one line>
<the failure scenario: concrete inputs or state, and the wrong result>

then a \`RESOLVED: <id> — <how, in a sentence>\` line for each earlier open finding the code no longer has, and last a line of its own, \`FINDINGS: <n>\`, the number of new findings above — \`FINDINGS: 0\` when there are none.
TEXT
}

# One more round handed to a resumed review session, for its row in the
# issue: the threads it was given are counted by run_comments, as on GitHub;
# the rounds are the reviews it worked through, the first counted when it
# opened (run_rounds), one more for each local review that brought it back.
#
#   run_local_round <wt> <session>
run_local_round() {
  local wt="$1" session="$2"
  [[ -n "$session" ]] || return 0
  python3 - "$wt/.sclaude/local/feature/state.json" "$session" <<'PY' 2>/dev/null || true
import json, sys
path, session = sys.argv[1:3]
with open(path) as fh:
    data = json.load(fh)
runs = ((data.get("steps") or {}).get("review") or {}).get("runs") or []
mine = [r for r in runs if isinstance(r, dict) and r.get("session") == session]
if not mine:
    sys.exit(0)
run = mine[-1]
run["rounds"] = (run.get("rounds") if isinstance(run.get("rounds"), int) else 0) + 1
with open(path, "w") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

# Whether the tree's HEAD is the head of the pull request: what a thread can
# be posted on. Asked of GitHub rather than of the upstream, which a branch
# made from origin/main keeps pointing at until somebody pushes with -u.
#
#   local_review_pushed <wt> <pr>
local_review_pushed() {
  local wt="$1" pr="$2" remote
  remote="$(cd "$wt" && gh pr view "$pr" --json headRefOid --jq .headRefOid 2>/dev/null)" || return 1
  [[ -n "$remote" && "$remote" == "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" ]]
}

# The head the last local review covered, or nothing.
local_review_head() {
  python3 "$LIB/local_review.py" base "$(local_review_file "$1" -rounds.jsonl)" 2>/dev/null || true
}
