#!/usr/bin/env bash
#
# Review blocks (review_blocks.py says why): a pull request too big for one
# review is cut, as step 4 starts, into blocks read one after another, then a
# pass over the seams.
#
# The state keeps where the review stands — `blocks.total` (the blocks and
# the seams, 0 when the pull request is read whole), `blocks.current`,
# `blocks.base` (written by parts_join alone, after it empties the node: the
# commit the review reads from, when it is not where the branch left main — a
# feature whose first parts were reviewed the old way — and gone as soon as
# another pull request than the first one seen is);
# the cut itself is review-blocks.json beside it, there while blocks are read
# and taken off after the seams. Meanwhile the review runs on this machine
# (project_review_mode): a review in Actions reads the whole pull request and
# cannot be held to a block; under a github setting the project's CI still
# counts (project_review_in_blocks, in_blocks in pr_context.py). `blocks.pr` is the pull request the node belongs to: a new one, after
# a merged one was reopened, is decided again.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

blocks_file() { echo "$1/.sclaude/local/feature/review-blocks.json"; }

# Whether the review of <wt> is read in blocks.
blocks_active() {
  local total
  total="$(state_get "$1/.sclaude/local/feature/state.json" blocks.total 2>/dev/null || true)"
  [[ "$total" =~ ^[0-9]+$ && "$total" -ge 2 && -f "$(blocks_file "$1")" ]]
}

blocks_now() { state_get "$1/.sclaude/local/feature/state.json" blocks.current 2>/dev/null || true; }
blocks_total() { state_get "$1/.sclaude/local/feature/state.json" blocks.total 2>/dev/null || true; }

# The commit the review reads from: the one recorded, else where the branch
# left main.
blocks_base() {
  local wt="$1" base
  base="$(state_get "$wt/.sclaude/local/feature/state.json" blocks.base 2>/dev/null || true)"
  if [[ "$base" =~ ^[0-9a-f]{40}$ ]] && git -C "$wt" cat-file -e "$base^{commit}" 2>/dev/null; then
    echo "$base"
  else
    git -C "$wt" merge-base origin/main HEAD 2>/dev/null
  fi
}

# The cut, once, as step 4 starts on a pull request: nothing when the
# project has no review, when it is decided already, or when the diff is
# small enough to read whole (`reviewBlocks.from` changed lines, generated
# files left out; 5000 when unset) — then `blocks.total` is 0 and the review
# runs as it always did. Past it a session cuts the blocks
# (blocks_cut_session), a second try told what the first got wrong; two
# refusals fall back to the parts the feature was built in, and with none,
# to the whole.
#
#   blocks_ensure <wt> <pr>
blocks_ensure() {
  local wt="$1" pr="$2" state="$1/.sclaude/local/feature/state.json"
  local total base lines from size file try faults="" n seen
  [[ -n "$pr" && "$pr" != null ]] || return 0
  # The pull request this belongs to, claimed the first time one is seen —
  # with the base parts_join left, decided or not: another pull request
  # (one merged, reopened) starts afresh, with neither.
  seen="$(state_get "$state" blocks.pr 2>/dev/null || true)"
  if [[ -n "$seen" && "$seen" != null && "$seen" != "$pr" ]]; then
    blocks_clear "$wt"
  fi
  state_set "$state" blocks.pr "$pr"
  total="$(blocks_total "$wt")"
  [[ -n "$total" && "$total" != null ]] && return 0
  [[ "$(project_review_setting "$wt")" != off ]] || return 0
  base="$(blocks_base "$wt")" || return 0
  [[ -n "$base" ]] || return 0
  from="$(project_get reviewBlocks.from "$wt" 2>/dev/null || true)"; [[ "$from" =~ ^[0-9]+$ ]] || from=5000
  size="$(project_get reviewBlocks.size "$wt" 2>/dev/null || true)"; [[ "$size" =~ ^[0-9]+$ ]] || size=3000
  lines="$(python3 "$LIB/review/review_blocks.py" size "$wt" "$base" 2>/dev/null || echo 0)"
  if (( lines <= from )); then
    state_set "$state" blocks.total 0
    return 0
  fi
  file="$(blocks_file "$wt")"
  echo ""
  info "  PR #$pr changes $lines lines, past the $from one review reads well: it is cut into blocks."
  for try in 1 2; do
    if blocks_cut_session "$wt" "$base" "$size" "$file" "$faults" \
       && faults="$(python3 "$LIB/review/review_blocks.py" validate "$wt" "$base" "$file" "$size")"; then
      faults=""
      break
    fi
    [[ -n "$faults" ]] || faults="the answer held no JSON object of the shape asked for"
    warn "  The cut, try $try, does not hold:"
    printf '%s\n' "$faults" | head -8 | sed 's/^/    /' >&2
    rm -f "$file"
  done
  if [[ ! -f "$file" ]] \
     && python3 "$LIB/review/review_blocks.py" draft "$wt" "$base" "$state" "$file" 2>/dev/null; then
    warn "  The blocks are the parts the feature was built in."
    ask_feed say "⚠️ The review's cut did not hold twice: its blocks are the parts the feature was built in." 2>/dev/null || true
  fi
  n=0
  [[ -f "$file" ]] && n="$(python3 "$LIB/review/review_blocks.py" count "$file" 2>/dev/null || echo 0)"
  if (( n < 2 )); then
    rm -f "$file"
    state_set "$state" blocks.total 0
    warn "  No cut into blocks: the pull request is read whole."
    return 0
  fi
  state_set "$state" blocks.total $((n + 1))
  state_set "$state" blocks.current 1
  history_add "$state" blocks cut total="$n"
  # The review in Actions told to leave it: it is read here now. Whether the
  # pull request carried the label before is kept, when GitHub said: the
  # seams leave it on only where it plainly did (blocks_next) — a label the
  # person put there stays; one nobody could tell about comes off, at the
  # person's word (2026-11-12): a review too many is better than none.
  local labels
  if labels="$(cd "$wt" && gh pr view "$pr" --json labels --jq '.labels[].name' 2>/dev/null)"; then
    if grep -qx no-review <<< "$labels"; then state_set "$state" blocks.label_before yes
    else state_set "$state" blocks.label_before no; fi
  fi
  review_label_sync "$wt" "$pr"
  local said; said="$(python3 "$LIB/review/review_blocks.py" summary "$file" 2>/dev/null)"
  info "  Read in this order, each to a clean verdict (the cut: $file):"
  printf '%s\n' "$said" | sed 's/^/    /' >&2
  ask_feed say "🧱 PR #$pr is read in $((n + 1)) blocks:"$'\n'"$said" 2>/dev/null || true
  return 0
}

# What a pull request decided before left, taken out whole — the cut beside
# the state, the blocks' kept records and the base — for the new one to be
# decided afresh: a pull request opened after a merged one reads from main,
# however the merged one was merged.
#
#   blocks_clear <wt>
blocks_clear() {
  rm -f "$(blocks_file "$1")"
  PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$1/.sclaude/local/feature/state.json" <<'PY'
import json, sys
import state_file
path = sys.argv[1]
state_file.lock(path)
with open(path) as fh:
    data = json.load(fh)
data["blocks"] = {}
state_file.write(path, data)
PY
}

# The session that cuts: read-only, headless, answering with the cut's JSON
# alone. <faults>, from a try before, tells it what to mend.
#
#   blocks_cut_session <wt> <base> <size> <file> <faults>   → 1 when it gave no JSON
blocks_cut_session() {
  local wt="$1" base="$2" size="$3" file="$4" faults="$5" head listing answer text
  head="$(git -C "$wt" rev-parse HEAD)"
  listing="$(python3 "$LIB/review/review_blocks.py" files "$wt" "$base" "$wt/.sclaude/local/feature/state.json")"
  answer="$(local_review_file "$wt" -blocks.md)"
  text="$(blocks_cut_prompt "$base" "$head" "$size" "$listing" "$faults")"
  info "  A session cuts the blocks ($LOCAL_REVIEW_MODEL)…"
  ( cd "$wt" && exec claude -p "$text" --model "$LOCAL_REVIEW_MODEL" \
           --allowedTools "Read" "Grep" "Glob" \
             "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" \
           --disallowedTools "Edit" "Write" "NotebookEdit" "Bash(gh:*)" \
             "Bash(git push:*)" "Bash(git commit:*)" \
           >"$answer" 2>>"$(local_review_file "$wt" .log)" </dev/null ) || return 1
  python3 "$LIB/review/review_blocks.py" take "$answer" "$file" "$base" "$head" 2>>"$(local_review_file "$wt" .log)"
}

blocks_cut_prompt() {
  local base="$1" head="$2" size="$3" listing="$4" faults="$5"
  cat <<TEXT
You cut a pull request into review blocks, unattended: nobody will answer a question. Change no file; answer with one JSON object and nothing else.

The pull request is \`git diff $base..$head\`, too big for one review to read well. Its plan is .sclaude/local/feature/plan.md: what it promises, its acceptance criteria (identifiers like AC1), and, when it was built in parts, its \`## Parts\`.

A block is what one review reads first and whole: one or more behaviours — groups of the plan's criteria — with the files that carry them, so that a reviewer follows each rule end to end, from its criterion through every layer of this product it passes to its tests. Cut by behaviour, not by layer: a block of one layer leaves every rule half-read, and its bugs are where the layers meet. The parts the feature was built in are a hint, not the cut: they were made for building and showing, and the same central files run through all of them.

Rules:
- Every changed file below is in exactly one block — its owner, which reads it whole. A file several behaviours share (a central component, a function every action calls) goes to the block of the behaviour the others rest on; when that block would grow past the size, put the shared files in a block of their own right after it.
- Tests go with the code they test. A manual or help page for users goes in a last block of its own.
- Files a tool wrote (marked generated below) go with the code they follow, and do not count towards the size.
- Each block's changed lines, generated files left out, stay under $size, unless the block is a single file.
- Every criterion of the plan is in exactly one block — or in \`rules\`, when it is a rule every behaviour follows (permissions, errors, validation shared by all) rather than a behaviour of its own; a criterion the plan marks for no part is often one.
- Order the blocks so that what others rest on comes first: the behaviour the rest build on, then those built on it; the manuals last.
- Two to eight blocks. Read the code as you need to (\`git show $head:<path>\`, \`git diff $base..$head -- <path>\`) — do not read it all.

The changed files — path, lines changed, generated or not, the parts whose commits changed it:
$listing
${faults:+
A cut tried before did not hold: mend these, and keep the rest of the rules:
$faults
}
Answer with exactly this shape, nothing around it:
{"blocks": [{"title": "<the behaviours, in a few words>", "criteria": ["AC1", "AC4"], "files": ["<path>", ...], "why": "<one sentence: what holds these together>", "contracts": ["<with block N: what one gives the other>"]}], "rules": [{"title": "<the rule>", "criteria": ["AC9"], "where": ["<path that builds it>"]}]}
TEXT
}

# A block's review closed: the next block opens — the step's records begun
# again, as for a new round of the review, the head it closed at kept for
# the seams — or, after the seams, the cut is taken off, the review goes back
# to where the project runs it, and the step closes as any other. 0 when a
# block opened, for the caller to run step 4 again.
#
#   blocks_next <wt> <slug>
blocks_next() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json" k total pr head
  blocks_active "$wt" || return 1
  k="$(blocks_now "$wt")"; total="$(blocks_total "$wt")"
  [[ "$k" =~ ^[0-9]+$ ]] || return 1
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  head="$(git -C "$wt" rev-parse HEAD)"
  if (( k >= total )); then
    history_add "$state" blocks done
    rm -f "$(blocks_file "$wt")"
    # Back to where the project reviews: a review in Actions that the label
    # held off reads the pull request again (review_label_sync put it on).
    if [[ "$(project_review_mode "$wt")" == github \
          && "$(state_get "$state" blocks.label_before 2>/dev/null || true)" != yes ]]; then
      (cd "$wt" && gh pr edit "$pr" --remove-label no-review >/dev/null 2>&1) || true
    fi
    info "  Every block of PR #${pr:-?} and the seams between them are read."
    return 1
  fi
  python3 "$LIB/review/review_blocks.py" close "$(blocks_file "$wt")" "$k" "$head" 2>/dev/null || true
  history_add "$state" blocks closed block="$k"
  ask_feed say "🧱 Block $k/$total of PR #${pr:-?} reviewed." 2>/dev/null || true
  # The step's record begun again, its conversations kept (the issue's
  # summary and the costs read `runs`), and what it held kept under the
  # block: a block's rounds, its "enough", counted apart.
  PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$state" "$k" <<'PY'
import json, sys
path, k = sys.argv[1], sys.argv[2]
import state_file
state_file.lock(path)
with open(path) as fh:
    data = json.load(fh)
steps = data.setdefault("steps", {})
block = data.setdefault("blocks", {}).setdefault(k, {})
if "steps" not in block and steps.get("review"):
    block["steps"] = {"review": steps.get("review")}
runs = (steps.get("review") or {}).get("runs")
steps["review"] = {"runs": runs} if runs else {}
state_file.write(path, data)
PY
  state_set "$state" blocks.current $((k + 1))
  echo ""
  if (( k + 1 == total )); then
    info "  Block $k of $total is reviewed. Last: the seams between the blocks."
  else
    info "  Block $k of $total is reviewed. Next: block $((k + 1))."
  fi
  return 0
}

# What the review pass reads (local_review_run) while blocks are read: the
# block's first read, whole, or the seams — empty once the block has been
# read and only the rounds' new commits are left, which the pass reads
# across the whole pull request, with the closed blocks' files they touched
# (blocks_touched).
#
#   blocks_scope <wt> <head>
blocks_scope() {
  local wt="$1" head="$2" k total
  k="$(blocks_now "$wt")"; total="$(blocks_total "$wt")"
  if (( k >= total )); then
    python3 "$LIB/review/review_blocks.py" seams "$wt" "$(blocks_file "$wt")" "$head"
  else
    python3 "$LIB/review/review_blocks.py" scope "$wt" "$(blocks_file "$wt")" "$k" "$head"
  fi
}

#   blocks_touched <wt> <since> <head>
blocks_touched() {
  python3 "$LIB/review/review_blocks.py" touched "$1" "$(blocks_file "$1")" "$(blocks_now "$1")" "$2" "$3" 2>/dev/null || true
}
