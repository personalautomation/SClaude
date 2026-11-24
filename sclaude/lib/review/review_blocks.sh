#!/usr/bin/env bash
#
# Review blocks (review_blocks.py says why): a pull request too big for one
# review is cut, as step 4 starts, into blocks read one after another, then a
# pass over the seams.
#
# The state keeps where the review stands — `blocks.total` (the blocks and
# the seams, 0 when the pull request is read whole), `blocks.current`;
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
# Block <k>'s id (the one read now without <k>): its name for good, which the
# journal and the history name it by — its place until a split moved the
# places (blocks_split). The seams have none.
blocks_id() {
  local k="${2:-$(blocks_now "$1")}"
  python3 "$LIB/review/review_blocks.py" id "$(blocks_file "$1")" "$k" 2>/dev/null || echo "$k"
}
# Block <k> as the person reads it, named: its place of the total — the
# progress — and, once a split moved the places, its id before it:
# "block 2/5", "block 3 (4/5)", and "the seams (5/5)" — called so, as the
# review report and the review map call their rounds (SEAMS in
# review_report.py), so that their place is not read as a block 5 after a
# block 3. A line opening with it capitalises it ("${label^}").
blocks_label() {
  local k="${2:-$(blocks_now "$1")}" total="${3:-}" id
  [[ -n "$total" ]] || total="$(blocks_total "$1")"
  if [[ "$k" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ ]] && (( k < total )); then id="$(blocks_id "$1" "$k")"
  elif [[ "$k" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ ]] && (( k == total )); then echo "the seams ($k/$total)"; return
  else id="$k"; fi
  if [[ "$id" == "$k" ]]; then echo "block $k/$total"; else echo "block $id ($k/$total)"; fi
}
blocks_total() { state_get "$1/.sclaude/local/feature/state.json" blocks.total 2>/dev/null || true; }
# Whether blocks are read and the one read now is not the last (the seams):
# closing it opens the next rather than ending step 4.
blocks_before_last() {
  blocks_active "$1" || return 1
  local bk bt; bk="$(blocks_now "$1")"; bt="$(blocks_total "$1")"
  [[ "$bk" =~ ^[0-9]+$ && "$bt" =~ ^[0-9]+$ ]] && (( bk < bt ))
}

# The commit the review reads from: where the branch left main.
blocks_base() {
  git -C "$1" merge-base origin/main HEAD 2>/dev/null
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
  # The pull request this belongs to, claimed the first time one is seen,
  # decided or not: another pull request (one merged, reopened) starts
  # afresh.
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
  size="$(project_get reviewBlocks.size "$wt" 2>/dev/null || true)"; [[ "$size" =~ ^[0-9]+$ ]] || size=3000  # SIZE in review_blocks.py
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
# the state and the blocks' kept records — for the new one to be
# decided afresh.
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
- Order the blocks so that what others rest on comes first. Lean the foundation into the first blocks — the data model and the rules it enforces, the shared files many behaviours call, the files that build the \`rules\` every behaviour follows, the most important behaviour — then the behaviours built on it; the manuals last. The foundation still goes in by behaviour: the behaviour that rests most directly on it takes it into its block, with its criteria, rather than a block of the schema and the helpers alone. A fix in the foundation reaches every block: read early, the later blocks read on code already reviewed rather than code that will still change under them. A leaning, not a law: a file only one behaviour uses goes with that behaviour, wherever it comes.
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

# A block past the size, before it is read whole (its first read, or again
# once it went stale): a session splits it by behaviour, as the cut was
# made, the faults of a first try told to a second; parts that hold take its
# place (review_blocks.py split) and the blocks after move up a place,
# keeping their ids. 0 when it was split, for the caller to read the first
# part; 1 when it is read as it is — within the size, the seams, or two
# tries that did not hold. Its cost is a cut's, under a dollar: the whole
# read it comes before is the price, and that is read in earnest after it.
#
#   blocks_split <wt> <head>
blocks_split() {
  local wt="$1" head="$2" state="$1/.sclaude/local/feature/state.json" k total limit file id
  local answer text faults="" told="" judged="" try n parts rc
  k="$(blocks_now "$wt")"; total="$(blocks_total "$wt")"
  [[ "$k" =~ ^[0-9]+$ && "$total" =~ ^[0-9]+$ ]] && (( k < total )) || return 1
  limit="$(project_get reviewBlocks.size "$wt" 2>/dev/null || true)"; [[ "$limit" =~ ^[0-9]+$ ]] || limit=3000  # SIZE in review_blocks.py
  file="$(blocks_file "$wt")"
  python3 "$LIB/review/review_blocks.py" outgrown "$wt" "$file" "$k" "$head" "$limit" 2>/dev/null || return 1
  id="$(blocks_id "$wt" "$k")"
  answer="$(local_review_file "$wt" -split.md)"
  # Everything it says goes to stderr: local_review, which calls it, answers
  # with its findings count on stdout.
  info "  Block $id has grown past $limit changed lines: a session splits it by behaviour ($LOCAL_REVIEW_MODEL)…" >&2
  # Only an answer judged and found wanting is told to the next try, and
  # only then is the head marked: a session that failed (a quota, the
  # network) judged nothing, and a crash here is sclaude's, not the answer's.
  for try in 1 2; do
    text="$(blocks_split_prompt "$(python3 "$LIB/review/review_blocks.py" brief "$wt" "$file" "$k" "$head")" \
              "$(blocks_base "$wt")" "$head" "$limit" "$told")"
    if ! ( cd "$wt" && exec claude -p "$text" --model "$LOCAL_REVIEW_MODEL" \
             --allowedTools "Read" "Grep" "Glob" \
               "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" \
             --disallowedTools "Edit" "Write" "NotebookEdit" "Bash(gh:*)" \
               "Bash(git push:*)" "Bash(git commit:*)" \
             >"$answer" 2>>"$(local_review_file "$wt" .log)" </dev/null ); then
      warn "  The session splitting block $id, try $try, failed."
      continue
    fi
    rc=0
    faults="$(python3 "$LIB/review/review_blocks.py" split "$wt" "$file" "$k" "$head" "$answer" "$limit" \
              2>>"$(local_review_file "$wt" .log)")" || rc=$?
    if (( rc == 0 )); then
      n="$(python3 "$LIB/review/review_blocks.py" count "$file" 2>/dev/null || echo 0)"
      parts=$(( n + 1 - total + 1 ))
      state_set "$state" blocks.total $((n + 1))
      history_add "$state" blocks split block="$id" parts="$parts"
      local said; said="$(python3 "$LIB/review/review_blocks.py" summary "$file" 2>/dev/null)"
      info "  Block $id is split in $parts; the blocks now:" >&2
      printf '%s\n' "$said" | sed 's/^/    /' >&2
      ask_feed say "🧱 Block $id had grown past $limit lines: it is split in $parts, each read whole; now reading $(blocks_label "$wt" "$k")."$'\n'"$said" 2>/dev/null || true
      return 0
    fi
    if [[ -z "$faults" ]]; then
      warn "  Checking the split of block $id failed (its log: $(local_review_file "$wt" .log))."
      break
    fi
    judged=1 told="$faults"
    warn "  The split of block $id, try $try, does not hold:"
    printf '%s\n' "$faults" | head -8 | sed 's/^/    /' >&2
  done
  # Judged and not held: not tried again on this head, so a pass that fails
  # or is stopped and runs again (ten times, gone on by itself) does not pay
  # for two sessions each time. A session that failed, or a crash of the
  # check, marks nothing, even though a retry pays again: at the user's
  # decision (2026-11-15), a passing failure must not leave the block
  # unsplit for the rest of the head.
  [[ -n "$judged" ]] && python3 "$LIB/review/review_blocks.py" tried "$file" "$k" "$head" 2>/dev/null
  warn "  Block $id is read whole as it is."
  return 1
}

blocks_split_prompt() {
  local brief="$1" base="$2" head="$3" size="$4" faults="$5"
  cat <<TEXT
You split one review block of a pull request in two or more, unattended: nobody will answer a question. Change no file; answer with one JSON object and nothing else.

The pull request is \`git diff $base..$head\`, read in blocks, one after another, each read whole by a review. This block has grown past what one review reads whole in earnest — its fixes, the files they added, or a rework: it is to be read as two blocks or more instead. Its plan is .sclaude/local/feature/plan.md.

$brief

Rules — the same as the blocks were cut by:
- A block is one or more behaviours — groups of its criteria — with the files that carry them, so that a reviewer follows each rule end to end, through every layer it passes, to its tests. Cut by behaviour, not by layer.
- Every file above is in exactly one block; a file several behaviours share goes to the block of the behaviour the others rest on, or, when that block would grow past the size, into a block of its own right after it. Tests go with the code they test; a file a fix added goes with the behaviour it fixes.
- Files marked generated go with the code they follow and do not count towards the size.
- Files marked "no longer changed" go with the behaviour they carry, in a block that also has changed files: a block of them alone has nothing to read.
- Each block's changed lines, generated files left out, stay under $size, unless the block is a single file.
- Every criterion above is in exactly one block.
- Order the blocks so that what others rest on comes first: the data model and the rules it enforces, the shared files and the files that build the rules every behaviour follows lean into the first block, with the behaviour that rests most directly on them — not a block of one layer; a leaning, not a law: a file only one behaviour uses goes with that behaviour.
- Read the code as you need to (\`git show $head:<path>\`, \`git diff $base..$head -- <path>\`) — do not read it all.
${faults:+
A split tried before did not hold: mend these, and keep the rest of the rules:
$faults
}
Answer with exactly this shape, nothing around it:
{"blocks": [{"title": "<the behaviours, in a few words>", "criteria": ["AC1", "AC4"], "files": ["<path>", ...], "why": "<one sentence: what holds these together>", "contracts": ["<with block N: what one gives the other>"]}]}
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
  # Still changed past its size since its whole read: the person ended the
  # search, or let the head go unreviewed — it closes, and its close says so
  # (the terminal here, the topic in the close's own line below).
  local unread=""
  if blocks_stale "$wt" "$head"; then
    unread=", its latest change not read whole (the search was ended, or the head went unreviewed)"
    local label; label="$(blocks_label "$wt" "$k")"
    warn_here "  Closing ${label}$unread."
  fi
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
    # The topic, told of each block's close, is told of the last one too.
    # The seams are never stale (they own no file), so no "not read whole".
    ask_feed say "🧱 The seams of PR #${pr:-?} reviewed: every block and the seams between them are read." 2>/dev/null || true
    return 1
  fi
  python3 "$LIB/review/review_blocks.py" close "$(blocks_file "$wt")" "$k" "$head" 2>/dev/null || true
  local id; id="$(blocks_id "$wt" "$k")"
  history_add "$state" blocks closed block="$id"
  local named; named="$(blocks_label "$wt" "$k")"
  ask_feed say "🧱 ${named^} of PR #${pr:-?} reviewed$unread." 2>/dev/null || true
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
# Kept when there already: a block closed again is a close cut off before
# blocks.current moved on, and steps.review is the reset one by then — the
# first pass's record is the block's.
if "steps" not in block and steps.get("review"):
    block["steps"] = {"review": steps.get("review")}
review = steps.get("review") or {}
# The conversations (the polish round taken is the feature's, `polished`).
steps["review"] = {"runs": review["runs"]} if review.get("runs") else {}
state_file.write(path, data)
PY
  state_set "$state" blocks.current $((k + 1))
  echo ""
  if (( k + 1 == total )); then
    info "  ${named^} is reviewed. Last: the seams between the blocks."
  else
    info "  ${named^} is reviewed. Next: $(blocks_label "$wt" $((k + 1)) "$total")."
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

# Whether the block read now changed by reviewBlocks.size lines or more
# since its last whole read (review_blocks.py stale): more than a round's
# diff is read well, so its next pass reads it whole (local_review_run),
# also on a head a round read as a diff; the gate runs a pass before every
# close here, so the block is read whole before it closes, and
# local_review_done answers "not done" meanwhile, so the pass is reported.
# With the search ended it is not, and its close says so (blocks_next).
#
#   blocks_stale <wt> <head>
blocks_stale() {
  local wt="$1" head="$2" k whole_at limit pr
  k="$(blocks_now "$wt")"; [[ "$k" =~ ^[0-9]+$ ]] || return 1
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr 2>/dev/null || true)"
  whole_at="$(SCLAUDE_REVIEW_BLOCK="$(blocks_id "$wt" "$k")" python3 "$LIB/review/local_review.py" whole "$(review_journal "$wt")" "$pr" 2>/dev/null || true)"
  [[ -n "$whole_at" && "$whole_at" != "$head" ]] || return 1
  limit="$(project_get reviewBlocks.size "$wt" 2>/dev/null || true)"; [[ "$limit" =~ ^[0-9]+$ ]] || limit=3000  # SIZE in review_blocks.py
  python3 "$LIB/review/review_blocks.py" stale "$wt" "$(blocks_file "$wt")" "$k" "$whole_at" "$head" "$limit" 2>/dev/null
}

#   blocks_touched <wt> <since> <head>
blocks_touched() {
  python3 "$LIB/review/review_blocks.py" touched "$1" "$(blocks_file "$1")" "$(blocks_now "$1")" "$2" "$3" 2>/dev/null || true
}
