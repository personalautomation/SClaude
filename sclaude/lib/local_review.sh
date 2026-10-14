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
#           the commits step 4 opens on, and again on each head a review
#           session leaves. Its findings go to the session as text, not as
#           threads on the pull request. Tokens only, no runner minutes.
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

# Where a feature keeps the local review's results, beside its other scratch.
#
#   local-review.md        the findings on the last head reviewed, as text
#   local-review-head      "<sha> <count>": that head and how many it found
#   local-review-seen.md   every finding reported on this pull request so far,
#                          for the next run not to repeat
#   local-review-declined  the ones the person decided to leave, one per line
#                          (path:line, a tab, the decision), written by the
#                          review session as review.md tells it
#   local-review.log       the last run's stderr
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
# already; print how many findings it has.
#
#   local_review <wt> <pr>   → <count> on stdout; 1 when the review did not run
#
# The first run reads the whole pull request (origin/main...HEAD); later runs
# read only the commits since the last head reviewed, as the workflow's review
# reads a push, and are told what was reported and declined before. Everything
# it says goes to stderr: stdout is the count.
local_review() {
  local wt="$1" pr="$2" head last lsha lcount base scope out count
  head="$(git -C "$wt" rev-parse HEAD 2>/dev/null)" || return 1
  last="$(cat "$(local_review_file "$wt" -head)" 2>/dev/null || true)"
  read -r lsha lcount <<<"$last"
  if [[ "${lsha:-}" == "$head" && "${lcount:-}" =~ ^[0-9]+$ ]]; then
    echo "$lcount"
    return 0
  fi
  if [[ -n "${lsha:-}" ]] && git -C "$wt" merge-base --is-ancestor "$lsha" "$head" 2>/dev/null; then
    base="$lsha"
    scope="the commits since the last review: \`git diff $base..$head\`"
  else
    base="$(git -C "$wt" merge-base origin/main "$head" 2>/dev/null)" || return 1
    scope="the whole pull request: \`git diff $base..$head\`"
  fi

  command -v claude >/dev/null 2>&1 || { warn "  No claude on this machine: the local review did not run." >&2; return 1; }
  info "  Reviewing PR #${pr:-?} on this machine ($LOCAL_REVIEW_MODEL, $LOCAL_REVIEW_LEVEL): ${head:0:7}, ${base:0:7}..${head:0:7}." >&2
  info "  It takes minutes; Ctrl-C leaves, and the next \`$SELF\` starts it again." >&2

  out="$(cd "$wt" && claude -p "$(local_review_prompt "$wt" "$pr" "$base" "$head" "$scope")" \
           --model "$LOCAL_REVIEW_MODEL" \
           --allowedTools "Read" "Grep" "Glob" "Skill" "Agent" \
             "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git blame:*)" \
           --disallowedTools "Edit" "Write" "NotebookEdit" "Bash(gh:*)" \
             "Bash(git push:*)" "Bash(git commit:*)" \
           2>"$(local_review_file "$wt" .log)")"
  count="$(printf '%s\n' "$out" | local_review_count)"
  if [[ -z "$count" ]]; then
    warn "  The local review ended without a findings count; nothing recorded." >&2
    warn "  Its last words: $(printf '%s\n' "$out" | tail -n 3 | tr '\n' ' ')" >&2
    return 1
  fi

  {
    printf '## Local review of %s..%s — %s finding(s)\n\n' "${base:0:7}" "${head:0:7}" "$count"
    printf '%s\n' "$out" | sed -E '/^[[:space:]]*FINDINGS:[[:space:]]*[0-9]+[[:space:]]*$/d'
  } > "$(local_review_file "$wt" .md)"
  [[ "$count" -gt 0 ]] && { cat "$(local_review_file "$wt" .md)"; echo; } >> "$(local_review_file "$wt" -seen.md)"
  echo "$head $count" > "$(local_review_file "$wt" -head)"
  if [[ "$count" -eq 0 ]]; then
    info "  The local review found nothing on ${head:0:7}." >&2
  else
    info "  The local review found $count on ${head:0:7}: $(local_review_file "$wt" .md)" >&2
  fi
  echo "$count"
}

# The count from the review's answer: its last `FINDINGS: <n>` line.
local_review_count() {
  sed -nE 's/^[[:space:]]*FINDINGS:[[:space:]]*([0-9]+)[[:space:]]*$/\1/p' | tail -n 1
}

# What the headless review is told. The scope sentence follows the workflow's
# own, so that a local review reads what an Actions one would.
#
#   local_review_prompt <wt> <pr> <base> <head> <scope>
local_review_prompt() {
  local wt="$1" pr="$2" base="$3" head="$4" scope="$5" seen declined
  seen="$(local_review_file "$wt" -seen.md)"
  declined="$(local_review_file "$wt" -declined)"
  cat <<EOF
You are reviewing pull request #${pr:-?} unattended, on the developer's machine. Nobody will answer a question and nothing will wake you: when you end your turn the run is over, so collect every agent's result within this turn.

Invoke the \`code-review\` skill with the Skill tool, with these arguments on one line:

    $LOCAL_REVIEW_LEVEL <scope>

where <scope> is plain words saying: review $scope; review every changed file in it, none left out as unimportant, generated files may be skimmed; the tree is checked out at $head, so read the code as it is here; do not run the app, or any build or test.
EOF
  [[ -s "$seen" ]] && cat <<EOF
Add to the scope: findings already reported on this pull request are in \`${seen#"$wt"/}\`; do not report one of them again unless the code it rests on changed so that it is new.
EOF
  [[ -s "$declined" ]] && cat <<EOF
Add to the scope: the author decided to leave the findings in \`${declined#"$wt"/}\` as they are, each with the reason; do not report one of them again, reworded or on another line, unless the code it rests on changed so that the reason no longer holds — then say which change.
EOF
  cat <<EOF

Post nothing to GitHub and change no file: the findings go to a person through your answer.

When the skill is done, answer with its findings and nothing else, one per section:

### <path>:<line> — <the finding in one line>
<the failure scenario: concrete inputs or state, and the wrong result>

and end with a line of its own, \`FINDINGS: <n>\`, the number of findings above — \`FINDINGS: 0\` when there are none.
EOF
}

# What a review session is told about the local review's findings on HEAD.
#
#   local_review_told <wt>
local_review_told() {
  local wt="$1" file
  file="$(local_review_file "$wt" .md)"
  [[ -s "$file" ]] || return 0
  printf '**The review ran on this machine** (`review: local` in `.sclaude/config.json`). Its findings, also in `%s`:\n\n' \
    "${file#"$wt"/}"
  cat "$file"
}

# The head the last local review covered, or nothing.
local_review_head() {
  local sha
  read -r sha _ < "$(local_review_file "$1" -head)" 2>/dev/null || return 0
  echo "$sha"
}
