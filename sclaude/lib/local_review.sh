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

# The local review's own files, beside the feature's other scratch. The
# findings are not among them: they are threads on the pull request.
#
#   local-review-rounds.jsonl   one line per run: when, how long, the range,
#                               how many posted and resolved — the rounds the
#                               report counts, and the head last reviewed
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
  # A thread is posted on a commit GitHub has: a head not pushed yet cannot
  # carry one.
  if [[ "$(git -C "$wt" rev-parse '@{upstream}' 2>/dev/null)" != "$head" ]]; then
    warn "  ${head:0:7} is not pushed: the local review posts on commits GitHub has. Push, then run $SELF again." >&2
    return 1
  fi
  if python3 "$LIB/local_review.py" cached "$journal" "$head" 2>/dev/null; then
    python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" 2>/dev/null || return 1
    return 0
  fi
  last="$(local_review_head "$wt")"
  if [[ -n "$last" ]] && git -C "$wt" merge-base --is-ancestor "$last" "$head" 2>/dev/null; then
    base="$last"
    scope="the commits since the last review: \`git diff $base..$head\`"
  else
    base="$(git -C "$wt" merge-base origin/main "$head" 2>/dev/null)" || return 1
    scope="the whole pull request: \`git diff $base..$head\`"
  fi

  command -v claude >/dev/null 2>&1 || { warn "  No claude on this machine: the local review did not run." >&2; return 1; }
  info "  Reviewing PR #${pr:-?} on this machine ($LOCAL_REVIEW_MODEL, $LOCAL_REVIEW_LEVEL): ${base:0:7}..${head:0:7}." >&2
  info "  It takes minutes; Ctrl-C leaves, and the next \`$SELF\` starts it again." >&2

  local began=$SECONDS
  out="$(cd "$wt" && claude -p "$(local_review_prompt "$wt" "$pr" "$repo" "$head" "$scope")" \
           --model "$LOCAL_REVIEW_MODEL" \
           --allowedTools "Read" "Grep" "Glob" "Skill" "Agent" \
             "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git blame:*)" \
           --disallowedTools "Edit" "Write" "NotebookEdit" "Bash(gh:*)" \
             "Bash(git push:*)" "Bash(git commit:*)" \
           2>"$(local_review_file "$wt" .log)")"
  answer="$(local_review_file "$wt" -answer.md)"
  printf '%s\n' "$out" > "$answer"
  if ! count="$(python3 "$LIB/local_review.py" record "$wt" "$pr" "$repo" "$answer" \
                  "$base" "$head" "$((SECONDS - began))" "$journal" 2>>"$(local_review_file "$wt" .log)")"; then
    warn "  The local review was not recorded: no findings count in its answer, or GitHub took none of them." >&2
    warn "  Its answer: $answer; the next \`$SELF\` reviews this head again." >&2
    return 1
  fi
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
#   local_review_prompt <wt> <pr> <repo> <head> <scope>
local_review_prompt() {
  local wt="$1" pr="$2" repo="$3" head="$4" scope="$5" earlier
  earlier="$(python3 "$LIB/local_review.py" prompt "$wt" "$pr" "$repo" 2>/dev/null || true)"
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

# One more round handed to a review session, for its row in the issue: the
# threads it was given are counted by run_comments, as on GitHub; the rounds
# there are the workflow's runs it worked through, here the local ones.
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
run["local_rounds"] = (run.get("local_rounds") or 0) + 1
run["rounds"] = run["local_rounds"]
with open(path, "w") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

# The head the last local review covered, or nothing.
local_review_head() {
  python3 "$LIB/local_review.py" base "$(local_review_file "$1" -rounds.jsonl)" 2>/dev/null || true
}
