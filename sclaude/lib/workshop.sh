# shellcheck shell=bash
#
# The workshop: where a sclaude session changes sclaude itself.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# sclaude's live checkout ($INSTRUMENTS) is read-only to every session it
# runs (write-guard.py --readonly): every other session, on this feature and
# the others, runs from it, and a hook edited there changes them all on their
# next call. Sessions once committed to it and pushed its main themselves,
# from a private product's material, into a public repository nobody had read
# the change in; and a retrospective allowed to commit there could not send
# what it made, while one review session's fix waited a month in a deferred
# file because the review could not touch it at all.
#
# So a change to sclaude is made in a worktree of the checkout, one per tree
# (a feature's, or a deferred review's), at .sclaude/local/instruments, and
# shared by every session of that tree:
#
#   * `sclaude core-open` lets the session write there. In a step it is asked
#     of the person, by Claude Code itself (forbidden-commands.py answers
#     "ask"), for every session; a retrospective and the reviews that start in
#     plan mode, whose plan the person approved, get it without a question;
#   * the session commits there, reviews its change — sreview for a
#     maintainer of sclaude (MAINTAINERS), a review of its choosing for
#     anybody else — and says so with `sclaude core-ready`;
#   * when the session ends, sclaude publishes it (workshop_publish): the
#     check for the product's details, the tests the change touches, and then
#     main for a maintainer, squashed into one commit, or one pull request a
#     tree for anybody else. A change left unfinished is not published, and
#     its session is offered back, at once and when the feature is next opened.
#
# The record of who may write and what is ready is .sclaude/local/
# instruments.json beside it (workshop.py), which write-guard.py reads.

# What a session sent back to its unfinished change is told.
WORKSHOP_RESUME="You changed sclaude in this feature's workshop, and the change is not finished: it is uncommitted, or not reviewed, or not marked ready. sclaude reopened this session for it. Finish the change, commit it in the workshop, review it as your instructions say, and run \`sclaude core-ready\`; sclaude publishes it when you end the session. If the change should not go out at all, say so and leave it: nothing unfinished is published."

workshop_dir() { printf '%s/.sclaude/local/instruments\n' "$1"; }
workshop_record() { printf '%s/.sclaude/local/instruments.json\n' "$1"; }
workshop_py() { python3 "$LIB/workshop.py" "$@"; }

# The tree a command runs for: the product's, also from inside its workshop.
workshop_tree() {
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null)" || return 1
  top="${top%/.sclaude/local/instruments}"
  [[ "$(cd "$top" && pwd -P)" != "$(cd "$INSTRUMENTS" && pwd -P)" ]] || return 1
  printf '%s\n' "$top"
}

# Where sreview marks a finished run for the branch it reviewed: the head it
# finished on, on the first line (skills/sreview/SKILL.md, "Report").
workshop_sreview_mark() {
  local ws="$1" common branch
  common="$(git -C "$ws" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  branch="$(git -C "$ws" rev-parse --abbrev-ref HEAD 2>/dev/null)" || return 1
  printf '%s/sreview/branches/%s.reviewed\n' "$common" "$branch"
}

# Makes the tree's workshop from origin's main. A maintainer's is on a branch
# nobody sees, since what is published is one commit on main; anybody else's
# is the branch its pull request comes from — never named after the feature,
# since the repository is public.
workshop_make() {
  local tree="$1" ws rec base branch name
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  GIT_TERMINAL_PROMPT=0 timeout 20 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null || true
  base="$(git -C "$INSTRUMENTS" rev-parse -q --verify origin/main 2>/dev/null \
          || git -C "$INSTRUMENTS" rev-parse HEAD)" || return 1
  if developer_is_maintainer; then
    branch="workshop/$(date +%Y%m%d-%H%M%S)"
  else
    name="$(developer_name 2>/dev/null)"
    branch="dev/${name:-local}-$(date +%Y%m%d-%H%M%S)"
  fi
  mkdir -p "$(dirname "$ws")"
  git -C "$INSTRUMENTS" worktree add -q -b "$branch" "$ws" "$base" >/dev/null 2>&1 || return 1
  workshop_py put "$rec" start "\"$base\""
  workshop_py put "$rec" branch "\"$branch\""
}

# sclaude core-open: the session that runs it may change sclaude, in the
# tree's workshop. Run by the session; the hook asks the person first where
# that is the rule.
cmd_core_open() {
  local session="${SCLAUDE_SESSION:-}" tree ws rec
  [[ -n "$session" ]] \
    || die "core-open is for sclaude's sessions; by hand, change $INSTRUMENTS itself"
  tree="$(workshop_tree)" || die "run it inside the product's tree"
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  if [[ ! -d "$ws" ]]; then
    workshop_make "$tree" || die "could not make the workshop at $ws"
  fi
  workshop_py approve "$rec" "$session"
  echo "sclaude's workshop for this tree: $ws ($(git -C "$ws" rev-parse --abbrev-ref HEAD))"
  echo "Change sclaude there and nowhere else; commit there by its CLAUDE.md, never push."
  if developer_is_maintainer; then
    echo "Then review it with /sreview, run from the workshop, and run \`sclaude core-ready\`."
  else
    echo "Then review it, and run \`sclaude core-ready --review \"<how it was reviewed>\"\`."
  fi
  echo "sclaude publishes it when this session ends."
}

# sclaude core-ready [--review "<how>"]: the session's change in the workshop
# is finished and reviewed, and goes out when the session ends.
cmd_core_ready() {
  local session="${SCLAUDE_SESSION:-}" tree ws rec start head how="" mark
  [[ "${1:-}" == "--review" ]] && how="${2:-}"
  [[ -n "$session" ]] || die "core-ready is for sclaude's sessions"
  tree="$(workshop_tree)" || die "run it inside the product's tree"
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  [[ -d "$ws" ]] && workshop_py approved "$rec" "$session" \
    || die "this session has not opened the workshop (sclaude core-open)"
  [[ -z "$(git -C "$ws" status --porcelain 2>/dev/null)" ]] \
    || die "the workshop has uncommitted changes: commit them there, or drop them, first"
  start="$(workshop_py get "$rec" start)"
  head="$(git -C "$ws" rev-parse HEAD)"
  if [[ "$head" == "$start" ]]; then
    echo "Nothing is committed in the workshop since it was last published: nothing to send."
    return 0
  fi
  if developer_is_maintainer; then
    mark="$(workshop_sreview_mark "$ws")"
    [[ "$(head -n1 "$mark" 2>/dev/null)" == "$head" ]] \
      || die "sreview has not finished on the workshop's head ($head): run /sreview from $ws first"
    how="sreview"
  else
    [[ -n "$how" ]] || die "say how the change was reviewed: sclaude core-ready --review \"<how>\""
  fi
  workshop_py ready "$rec" "$session" "$head" "$how"
  echo "Ready: sclaude publishes it when this session ends."
}

# Where the tree's workshop stands for <session>: none (nothing unpublished),
# ready, blocked (ready, but held back at this head by the person, for the
# product's details: only a new commit lifts it), unready (uncommitted, or not marked ready at
# its head), or pending (an earlier session's change is unfinished there,
# which holds back everything made after it).
workshop_state() {
  local tree="$1" session="$2" ws rec start head ready pending
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  [[ -d "$ws" ]] || { echo none; return; }
  start="$(workshop_py get "$rec" start 2>/dev/null)"
  head="$(git -C "$ws" rev-parse HEAD 2>/dev/null)"
  local dirty; dirty="$(git -C "$ws" status --porcelain 2>/dev/null)"
  [[ -z "$dirty" && "$head" == "$start" ]] && { echo none; return; }
  pending="$(workshop_py get "$rec" pending.session 2>/dev/null)"
  [[ -n "$pending" && "$pending" != "$session" ]] && { echo pending; return; }
  ready="$(workshop_py get "$rec" ready.head 2>/dev/null)"
  if [[ -z "$dirty" && "$ready" == "$head" ]]; then
    [[ "$(workshop_py get "$rec" blocked.head 2>/dev/null)" == "$head" ]] && echo blocked || echo ready
  else
    echo unready
  fi
}

# Holds the workshop's ready change back at its head: the person said no to
# it, and trying again would only ask again. A new commit there, marked
# ready, lifts it. Every other stop is tried again when the tree is next
# opened, whatever it was.
#
#   workshop_block <tree> <why>
workshop_block() {
  local ws rec
  ws="$(workshop_dir "$1")"
  rec="$(workshop_record "$1")"
  workshop_py put "$rec" blocked "$(python3 -c 'import json, sys; print(json.dumps({"head": sys.argv[1], "why": sys.argv[2]}))' \
    "$(git -C "$ws" rev-parse HEAD)" "$2")"
  warn "  Not published, and held at this head: $2"
}

# After a session, from claude_launch: what it made in the workshop goes out,
# or it is offered the session back to finish it.
#
#   workshop_after_session <session> <the launch's arguments…>
workshop_after_session() {
  local session="$1" tree ws rec state answer
  shift
  tree="$(workshop_tree)" || return 0
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] && workshop_py approved "$rec" "$session" || return 0
  ws="$(workshop_dir "$tree")"
  while :; do
    state="$(workshop_state "$tree" "$session")"
    case "$state" in
      none) return 0 ;;
      ready) workshop_publish "$tree"; return 0 ;;
      blocked)
        info "  sclaude's change in $ws waits: $(workshop_py get "$rec" blocked.why)"
        return 0 ;;
      pending)
        warn "  This session's change to sclaude waits in $ws: an earlier session's there is unfinished."
        return 0 ;;
    esac
    echo ""
    warn "  This session changed sclaude in its workshop ($ws), and did not finish:"
    [[ -n "$(git -C "$ws" status --porcelain 2>/dev/null)" ]] \
      && warn "  uncommitted changes there." || warn "  not reviewed and marked ready (sclaude core-ready)."
    ask "  Back into the session to finish it? [y/n] " answer yn
    if is_yes "$answer"; then
      claude_again_args "$@"
      claude_launch_once "${CLAUDE_AGAIN[@]}" "$WORKSHOP_RESUME"
      continue
    fi
    workshop_py put "$rec" pending null
    workshop_py pending "$rec" "$session" "$PWD" "$@"
    info "  Left in the workshop and not published; sclaude offers the session back when the feature is next opened."
    return 0
  done
}

# Before anything else runs on a tree: a session that left its change to
# sclaude unfinished is offered back. A "no" leaves it, and the work goes on.
#
#   workshop_pending <tree>
workshop_pending() {
  local tree="$1" rec ws session answer
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] || return 0
  # A change finished and reviewed whose publishing stopped short is tried
  # again, whatever stopped it; one the person held back is only said.
  case "$(workshop_state "$tree" "")" in
    ready) workshop_publish "$tree"; return 0 ;;
    blocked) info "  sclaude's change in $(workshop_dir "$tree") waits: $(workshop_py get "$rec" blocked.why)"
             return 0 ;;
  esac
  session="$(workshop_py get "$rec" pending.session 2>/dev/null)" || return 0
  ws="$(workshop_dir "$tree")"
  echo ""
  warn "  An earlier session left a change to sclaude unfinished in this tree's workshop ($ws)."
  ask "  Back into that session to finish it? [y/n] " answer yn
  if ! is_yes "$answer"; then
    info "  Left as it is: nothing of it is published until it is finished."
    return 0
  fi
  local -a saved=()
  mapfile -d '' -t saved < <(workshop_py pending-args "$rec")
  (( ${#saved[@]} > 1 )) || { warn "  The session's launch was not recorded; finish it by hand in $ws."; return 0; }
  workshop_py put "$rec" pending null
  claude_again_args "${saved[@]:1}"
  ( cd "${saved[0]}" || exit 0
    [[ -f "$tree/.sclaude/local/feature/state.json" ]] && declare -F dev_env_load >/dev/null \
      && dev_env_load "$tree"
    declare -F session_git_env >/dev/null && session_git_env "$session"
    claude_launch "${CLAUDE_AGAIN[@]}" "$WORKSHOP_RESUME" )
  return 0
}

# What in the change may name the product: the person decides.
#
#   workshop_leaks <workshop> <base> <tree>
#
# A "yes" holds for what it was shown, every line: the same lines found again, in the
# diff or in the messages, wherever a rebase onto a newer main moved them, do
# not ask it again on a retry (P-3 in sreview's policies); a line not shown
# then does.
workshop_leaks() {
  local ws="$1" base="$2" tree="$3" hits answer rec id
  rec="$(workshop_record "$tree")"
  hits="$(workshop_py leaks "$ws" "$base" "$tree")" && return 0
  # Named without the commit, which a rebase or the squash renames.
  id="$(sed -E 's/^commit [0-9a-f]+: /commit: /' <<< "$hits" | sort | sha1sum | cut -c1-40)"
  [[ -n "$id" && "$(workshop_py get "$rec" leaks_ok 2>/dev/null)" == "$id" ]] && return 0
  warn "  sclaude's repository is public, and the change may name the product:"
  # Every line, and through warn, so that the question in Telegram carries them
  # too: a "yes" is kept for all of them (below).
  local line
  while IFS= read -r line; do warn "     $line"; done <<< "$hits"
  # A list longer than a question in Telegram holds loses its middle there
  # (ASK_CONTEXT_MAX in keepawake/telegramd.py), and a "yes" from the phone
  # would cover lines never seen: such a list is asked at the terminal alone,
  # and nobody there is no answer — tried again later, not held.
  if (( ${#hits} > WORKSHOP_PHONE_MAX )); then
    warn "  Too many lines for a question on the phone: answer it here, at the terminal."
    if ! ASK_DIR="" ask "  Publish it anyway? [y/n] " answer yn; then
      info "  Nobody answered at the terminal: it is tried again when the tree is next opened."
      return 2
    fi
  else
    ask "  Publish it anyway? [y/n] " answer yn
  fi
  if is_yes "$answer"; then
    [[ -n "$id" ]] && workshop_py put "$rec" leaks_ok "\"$id\""
    return 0
  fi
  info "  Not published: it stays in $ws, where a session of this tree can reword it."
  return 1
}

# How long the flagged lines may run and still reach a question in Telegram
# whole, with room for the lines around them: under telegramd's ASK_CONTEXT_MAX.
WORKSHOP_PHONE_MAX=1200

# The tests the change touches, as CLAUDE.md picks them for a commit: every
# test file that names a changed file; and bash -n on every shell file. In a
# clean environment, since the session's (its git hooks, its question channel)
# is no test's business.
#
#   workshop_tests <workshop> <base>
workshop_tests() {
  local ws="$1" base="$2" f t log
  local -a files=() tests=() failed=()
  # A rename as the deletion and the addition it is: a test that names the old
  # file is the one a rename breaks.
  mapfile -t files < <(git -C "$ws" diff --name-only --no-renames "$base"..HEAD 2>/dev/null)
  for f in "${files[@]}"; do
    case "$f" in
      *.sh|bin/*) [[ -f "$ws/$f" ]] && head -n1 "$ws/$f" | grep -q bash \
                    && { bash -n "$ws/$f" 2>/dev/null || failed+=("bash -n $f"); } ;;
    esac
    while IFS= read -r t; do
      [[ " ${tests[*]} " == *" $t "* ]] || tests+=("$t")
    done < <(cd "$ws" && grep -l -- "$(basename "${f%.*}")" tests/*.py 2>/dev/null)
  done
  info "  Checking it: ${#tests[@]} test file(s) the change touches."
  log="${TMPDIR:-/tmp}/sclaude-workshop-tests.log"
  : > "$log"
  for t in "${tests[@]}"; do
    ( cd "$ws" && env -i HOME="$HOME" PATH="$PATH" USER="${USER:-}" LANG="${LANG:-C.UTF-8}" \
        TMPDIR="${TMPDIR:-/tmp}" python3 "$t" </dev/null >>"$log" 2>&1 ) || failed+=("$t")
  done
  (( ${#failed[@]} == 0 )) && return 0
  warn "  Red: ${failed[*]} — not published; it stays in $ws. The output: $log"
  return 1
}

# Publishes what the tree's workshop holds, ready and reviewed: for a
# maintainer to main, rebased on origin's and squashed into one commit; for
# anybody else to the workshop's own branch and its one pull request.
#
#   workshop_publish <tree>
workshop_publish() {
  local tree="$1" ws rec start base how msg branch
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  start="$(workshop_py get "$rec" start)"
  how="$(workshop_py get "$rec" ready.review 2>/dev/null || true)"
  # How the last try stopped, for whoever asks whether one more is worth it
  # (cmd_done): set again below when it stops on the way.
  workshop_py put "$rec" stopped null
  echo ""
  info "${BOLD}sclaude's change from this tree's workshop${OFF}"
  git -C "$ws" log --format='     %h %s' "$start..HEAD" 2>/dev/null
  # sclaude's own git, not the session's: its hooks and its trailer are for
  # what the session commits.
  local -a G=(env -u GIT_CONFIG_COUNT git -C "$ws")
  if ! GIT_TERMINAL_PROMPT=0 timeout 30 "${G[@]}" fetch -q origin main 2>/dev/null; then
    warn "  Could not reach sclaude's repository: not published; it stays in $ws, and is tried again when the tree is next opened."
    workshop_py put "$rec" stopped '"on the way"'
    return 0
  fi
  if developer_is_maintainer; then
    if ! "${G[@]}" rebase -q origin/main >/dev/null 2>&1; then
      "${G[@]}" rebase --abort >/dev/null 2>&1
      warn "  It conflicts with sclaude's main: not published; it stays in $ws, and is tried again when"
      warn "  the tree is next opened. A session of this tree can rebase it there and mark it ready again."
      return 0
    fi
    base=origin/main
  else
    base="$start"
  fi
  if developer_is_maintainer && (( $("${G[@]}" rev-list --count origin/main..HEAD) > 1 )); then
    msg="$(workshop_py squash-message "$ws" origin/main)"
    "${G[@]}" reset -q --soft origin/main && "${G[@]}" commit -q -F - <<< "$msg" \
      || { warn "  Could not squash it into one commit: not published; it stays in $ws."; return 0; }
  fi
  # The rebase and the squash are sclaude's own and change nothing reviewed:
  # the head they leave is the ready one, so that whatever stops it below is
  # tried again from there (workshop_pending), not taken for an unfinished
  # change of the next session's.
  workshop_py put "$rec" ready.head "\"$("${G[@]}" rev-parse HEAD)\""
  local leaked=0
  workshop_leaks "$ws" "$base" "$tree" || leaked=$?
  if (( leaked == 1 )); then
    workshop_block "$tree" "held back for the product's details; a session of this tree rewords it"
    return 0
  fi
  (( leaked == 0 )) || return 0
  workshop_tests "$ws" "$base" || { info "  It is tried again when the tree is next opened."; return 0; }
  if developer_is_maintainer; then
    if ! GIT_TERMINAL_PROMPT=0 "${G[@]}" push -q origin HEAD:main >/dev/null 2>&1; then
      warn "  The push to main was refused (main moved meanwhile?): it stays in $ws,"
      warn "  and is tried again when the tree is next opened."
      workshop_py put "$rec" stopped '"on the way"'
      return 0
    fi
    info "  ${GREEN}Published to sclaude's main${OFF}: $("${G[@]}" log -1 --format='%h %s')"
  else
    branch="$("${G[@]}" rev-parse --abbrev-ref HEAD)"
    # Only a push that went through counts; anything short of it is tried
    # again, a push made by hand meanwhile included.
    PROPOSE_DIR="$ws" \
      PROPOSE_INTRO="Changes to sclaude made in a sclaude session's workshop and reviewed there (${how:-review not named}). Later pushes to the branch update this pull request." \
      instruments_propose "$branch" "$("${G[@]}" rev-list --count origin/main..HEAD)" \
      || { warn "  Not sent (no gh, no login, or the push failed): it stays in $ws, and is tried again when the tree is next opened."
           workshop_py put "$rec" stopped '"on the way"'
           return 0; }
  fi
  workshop_py put "$rec" start "\"$("${G[@]}" rev-parse HEAD)\""
  workshop_py put "$rec" ready null
  workshop_py put "$rec" blocked null
  developer_is_maintainer && workshop_live_update
  return 0
}

# Brings the live checkout up to what was just published, when that is safe
# here and now — on main, clean, nobody else's sclaude running from it — so
# the next session runs the fix. Otherwise the next sclaude start does
# (instruments_sync).
workshop_live_update() {
  local other
  if [[ "$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null)" != main \
        || -n "$(git -C "$INSTRUMENTS" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    info "  $INSTRUMENTS is not a clean main: it takes the change when you update it."
    return 0
  fi
  if other="$(instruments_others)"; then
    info "  $INSTRUMENTS takes it at the next sclaude start: another sclaude runs from it ($other)."
    return 0
  fi
  GIT_TERMINAL_PROMPT=0 timeout 20 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null
  # Commits of the checkout's own that origin does not have — work made there
  # by hand and not pushed yet — keep it from following: said, with the way.
  local own
  own="$(git -C "$INSTRUMENTS" rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
  if [[ "$own" =~ ^[1-9] ]]; then
    info "  $INSTRUMENTS has $own commit(s) of its own that origin does not: bring them on top of it"
    info "  (git -C $INSTRUMENTS pull --rebase origin main), and the change is there too."
  elif git -C "$INSTRUMENTS" merge -q --ff-only origin/main >/dev/null 2>&1; then
    info "  $INSTRUMENTS is on it now: the next session runs it."
  else
    info "  $INSTRUMENTS takes it at the next sclaude start."
  fi
}

# Whether the tree's workshop holds work not yet published.
workshop_unpublished() {
  local ws rec
  ws="$(workshop_dir "$1")"
  rec="$(workshop_record "$1")"
  [[ -d "$ws" ]] || return 1
  [[ -n "$(git -C "$ws" status --porcelain 2>/dev/null)" \
     || "$(git -C "$ws" rev-parse HEAD 2>/dev/null)" != "$(workshop_py get "$rec" start 2>/dev/null)" ]]
}

# Takes the tree's workshop away with the tree. Work never published is kept
# on its branch in sclaude's checkout, committed as it was left, and said.
#
#   workshop_remove <tree>
workshop_remove() {
  local tree="$1" ws rec start branch
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  if [[ -d "$ws" ]]; then
    start="$(workshop_py get "$rec" start 2>/dev/null || true)"
    branch="$(git -C "$ws" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    if [[ -n "$(git -C "$ws" status --porcelain 2>/dev/null)" ]]; then
      env -u GIT_CONFIG_COUNT git -C "$ws" add -A >/dev/null 2>&1
      env -u GIT_CONFIG_COUNT git -C "$ws" commit -q --no-verify \
        -m "wip: left unfinished in a sclaude workshop" >/dev/null 2>&1 || true
    fi
    if [[ -n "$branch" && "$(git -C "$ws" rev-parse HEAD 2>/dev/null)" != "$start" ]]; then
      warn "  sclaude's workshop held a change never published; it stays on branch $branch:"
      warn "  git -C $INSTRUMENTS log $branch --not origin/main"
      branch=""
    fi
    git -C "$INSTRUMENTS" worktree remove --force "$ws" >/dev/null 2>&1 || rm -rf -- "$ws"
    [[ -n "$branch" ]] && git -C "$INSTRUMENTS" branch -q -D "$branch" >/dev/null 2>&1
  fi
  git -C "$INSTRUMENTS" worktree prune >/dev/null 2>&1
  rm -f "$rec"
  return 0
}

# The prompt's paragraph on changing sclaude (prompts/_workshop.md), for a
# session of <tree>: `ask` for a step, whose `sclaude core-open` Claude Code
# asks the person about, `free` for a review session, whose is not asked.
# Empty with no tree: the epilogue's is gone.
#
#   workshop_rules <tree> ask|free
workshop_rules() {
  local tree="$1" mode="$2" maintainer="" other=1
  [[ -n "$tree" && -f "$PROMPTS/_workshop.md" ]] || return 0
  developer_is_maintainer && { maintainer=1; other=""; }
  SCLAUDE_V_WORKSHOP="$(workshop_dir "$tree")" SCLAUDE_V_INSTRUMENTS="$INSTRUMENTS" \
    SCLAUDE_V_CORE_ASK="$([[ "$mode" == ask ]] && echo 1)" \
    SCLAUDE_V_CORE_FREE="$([[ "$mode" == free ]] && echo 1)" \
    SCLAUDE_V_CORE_MAINTAINER="$maintainer" SCLAUDE_V_CORE_OTHER="$other" \
    python3 "$LIB/render_prompt.py" "$PROMPTS/_workshop.md" "$PROMPTS"
}
