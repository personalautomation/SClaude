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
#   * `sclaude core-open` lets the session write there. Only the
#     retrospective and the reviews open it, without a question: they start
#     in plan mode, so the person approved their plan. A step's session is
#     refused it and says in the friction log what got in its way
#     (forbidden-commands.py CORE_OPEN_NO);
#   * the session commits there, reviews its change — sreview for a
#     maintainer of sclaude (MAINTAINERS), a review of its choosing for
#     anybody else — and says so with `sclaude core-ready`;
#   * when the session ends, sclaude publishes it (workshop_publish): the
#     check for the product's details, the tests the change touches, and then
#     main for a maintainer, squashed into one commit, or one pull request a
#     tree for anybody else;
#   * every stop on the way — a change not finished, red tests, a line that
#     may name the product, a machine that shows what goes public first
#     (sclaude.contribute), main out of reach, a refused push — is one
#     question, the person's (workshop_decide): send it, reopen the session
#     that made it, or drop it. Nothing waits without that question: asked
#     again whenever the tree is opened, and the feature's clean-up waits for
#     its answer. `sclaude core-send` is a send typed by hand; core-open
#     refuses under sclaude.contribute off.
#
# The record of who may write and what is ready is .sclaude/local/
# instruments.json beside it (workshop.py), which write-guard.py reads.

# What a session sent back to its unfinished change is told; what exactly is
# missing (workshop_missing) follows it.
WORKSHOP_RESUME="You changed sclaude in this feature's workshop, and the change is not finished. sclaude reopened this session for it. Finish the change, commit it in the workshop, review it as your instructions say, and run \`sclaude core-ready\`; sclaude publishes it when you end the session. If the change should not go out at all, say so and leave it: nothing unfinished is published. What is missing:"

# Said to a session reopened because the tests before publishing were red,
# with the red files and where their output is after it.
WORKSHOP_RED_WORD="sclaude ran the tests your change to sclaude touches before publishing it, and some were red, so nothing was published. sclaude reopened this session for them. Read their output and find whose the failure is: run each red test again on your head, and on origin/main in the workshop. A test that passes on a second run is flaky, and a flaky test is still yours to make steady; one red on origin/main too is still yours to fix, as the repository's rules say. Fix it in the workshop, commit, review it as your instructions say, and run \`sclaude core-ready\`. When you end the session sclaude tests it again and publishes it. If the change should not go out at all, say so in your report: the person decides whether it is sent, reopened or dropped. Red:"

workshop_dir() { printf '%s/.sclaude/local/instruments\n' "$1"; }
workshop_record() { printf '%s/.sclaude/local/instruments.json\n' "$1"; }
workshop_py() { python3 "$LIB/improve/workshop.py" "$@"; }

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
  [[ "$(contribute_mode)" != off ]] \
    || die "changing sclaude is off on this machine (sclaude.contribute is off in $INSTRUMENTS): log what you would fix in the friction log instead"
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  if [[ ! -d "$ws" ]]; then
    workshop_make "$tree" || die "could not make the workshop at $ws"
  fi
  # Opened the first time by this session: the plan approved, the way in.
  if ! workshop_py approved "$rec" "$session" 2>/dev/null; then
    WORKSHOP_SESSION="$session" workshop_edge "$tree" w_ask w_open person "the plan approved in the session"
    WORKSHOP_SESSION="$session" workshop_edge "$tree" w_open w_change sclaude "sclaude core-open"
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
  WORKSHOP_SESSION="$session" workshop_edge "$tree" w_change w_ready session "sclaude core-ready" \
    note="reviewed: $how; head ${head:0:8}"
  echo "Ready: sclaude publishes it when this session ends."
}

# What keeps the tree's workshop from being ready, in a line, for the person
# and for the session sent back to it: one of uncommitted work, sreview's
# mark (a maintainer's), or core-ready not run.
#
#   workshop_missing <tree>
workshop_missing() {
  local ws head mark
  ws="$(workshop_dir "$1")"
  if [[ -n "$(git -C "$ws" status --porcelain 2>/dev/null)" ]]; then
    echo "uncommitted changes in $ws: commit them there, or drop them."
    return
  fi
  head="$(git -C "$ws" rev-parse HEAD 2>/dev/null)"
  if developer_is_maintainer; then
    mark="$(workshop_sreview_mark "$ws")"
    if [[ "$(head -n1 "$mark" 2>/dev/null)" != "$head" ]]; then
      echo "sreview's mark of a finished review at the head (${head:0:8}): /sreview has not finished on it — run it from $ws, or, if the person has decided the review has gone far enough, they answer \"stop\" to its question — then sclaude core-ready."
      return
    fi
  fi
  echo "sclaude core-ready has not been run on the head (${head:0:8})."
}


# Where the tree's workshop stands: none (nothing unpublished), ready (made
# and reviewed, marked ready at its head) or unready (uncommitted, or not
# marked ready at its head). Whatever is not none waits on the person's
# answer to workshop_decide, asked again at every opening of the tree until
# it comes; the feature's clean-up waits for it too (cmd_done).
workshop_state() {
  local tree="$1" ws rec start head ready dirty
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  [[ -d "$ws" ]] || { echo none; return; }
  start="$(workshop_py get "$rec" start 2>/dev/null)"
  head="$(git -C "$ws" rev-parse HEAD 2>/dev/null)"
  dirty="$(git -C "$ws" status --porcelain 2>/dev/null)"
  [[ -z "$dirty" && "$head" == "$start" ]] && { echo none; return; }
  ready="$(workshop_py get "$rec" ready.head 2>/dev/null)"
  [[ -z "$dirty" && "$ready" == "$head" ]] && echo ready || echo unready
}

# The one question a stopped change gets, the person's: send it as it is,
# reopen the session that made it — the same conversation, told what stopped
# it — or drop it. <choices> are the ones that make sense here (no send for a
# change not finished, no reopen with no session to reopen). Sets
# WORKSHOP_CHOICE to send, reopen, drop, or none: nobody answered, or the
# person is away ([g], a night) — then nothing is decided for them, and the
# question is asked again when the tree is next opened (workshop_pending).
# The way in is written by the caller, as the way out of a send, which
# only the caller knows. WORKSHOP_WHY is left saying what stopped it, the
# context with it, for the session a reopen sends back; the history gets
# `asked` for a question left open, `reopened`, or `dropped`.
#
#   workshop_decide <tree> <why> <context> <choices…>
workshop_decide() {
  local tree="$1" why="$2" context="$3" rec answer c n=0 line
  shift 3
  local -a choices=() labels=()
  rec="$(workshop_record "$tree")"
  # No reopen with no session to reopen: the answer would change nothing.
  for c in "$@"; do
    if [[ "$c" == reopen ]] && ! workshop_reopenable "$rec"; then
      info "  The session that made it cannot be reopened (where it ran is gone): drop it, or leave it for this tree's next retrospective or friction review, which may open the workshop and finish it."
      continue
    fi
    choices+=("$c")
  done
  WORKSHOP_CHOICE=none WORKSHOP_WHY="$why${context:+
$context}"
  workshop_py put "$rec" asked "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$why")"
  echo ""
  warn "  sclaude's change in $(workshop_dir "$tree") is not published: $why"
  while IFS= read -r line; do [[ -n "$line" ]] && warn "     $line"; done <<< "$context"
  # Away: nobody is there to read what would go public, nor to say what to
  # drop; asked again at the next opening, and the clean-up waits for it.
  if declare -F review_go_on >/dev/null && review_go_on "$tree"; then
    info "  You are away: asked again when the tree is next opened."
    workshop_history "$tree" asked
    return 0
  fi
  for c in "${choices[@]}"; do
    case "$c" in
      send)   labels+=("Send — publish it as it is") ;;
      reopen) labels+=("Reopen — back into the session that made it") ;;
      drop)   labels+=("Drop — empty the workshop; the change is kept under refs/sclaude/dropped") ;;
    esac
  done
  for c in "${labels[@]}"; do n=$((n + 1)); info "    $n $c"; done
  # As before the change went out: a context the phone would show cut is
  # answered at the terminal, so that a send from the phone never covers
  # lines it did not show.
  local here="" tries=0 shown
  (( ${#context} > WORKSHOP_PHONE_MAX )) && { warn "  Too long for a question on the phone: answer it here, at the terminal."; here=1; }
  # Each question forgets the lines warned before it (ask_forget): asked
  # again, it carries them again, so a send from the phone covers what it shows.
  shown="${ASK_CONTEXT:-}"
  while :; do
    ASK_CONTEXT="$shown"
    if [[ -n "$here" ]]; then
      ASK_DIR="" ask "  Send, reopen or drop? [1-$n] " answer "pick:$n" "${labels[@]}"
    else
      ask "  Send, reopen or drop? [1-$n] " answer "pick:$n" "${labels[@]}"
    fi || {
      info "  Nobody answered: asked again when the tree is next opened."
      workshop_history "$tree" asked
      return 0
    }
    [[ "$answer" =~ ^[0-9]+$ ]] && (( answer >= 1 && answer <= n )) && break
    # A channel that keeps handing back what is no choice is nobody answering.
    (( ++tries < 5 )) || { info "  No choice made: asked again when the tree is next opened."; workshop_history "$tree" asked; return 0; }
    printf '%s\n' "  Answer 1-$n." >&2
  done
  WORKSHOP_CHOICE="${choices[$((answer - 1))]}"
  workshop_py put "$rec" asked null
  case "$WORKSHOP_CHOICE" in
    reopen) workshop_edge "$tree" w_decide w_change person "$ASKED_HOW"
            workshop_history "$tree" reopened ;;
    drop)   workshop_drop "$tree" "$ASKED_HOW" ;;
  esac
  return 0
}

# Drops the workshop's change: what it holds, committed as it was left, is
# kept under refs/sclaude/dropped/<time> in sclaude's checkout, which nothing
# clears by itself, and the workshop goes back to where it started.
#
#   workshop_drop <tree> <how>
workshop_drop() {
  local tree="$1" ws rec start ref
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  start="$(workshop_py get "$rec" start)"
  local -a G=(env -u GIT_CONFIG_COUNT git -C "$ws")
  if [[ -n "$("${G[@]}" status --porcelain 2>/dev/null)" ]]; then
    "${G[@]}" add -A >/dev/null 2>&1
    "${G[@]}" commit -q --no-verify -m "wip: dropped from a sclaude workshop" >/dev/null 2>&1 || true
  fi
  ref="refs/sclaude/dropped/$(date -u +%Y%m%d-%H%M%S)"
  "${G[@]}" update-ref "$ref" HEAD
  "${G[@]}" reset -q --hard "$start"
  "${G[@]}" clean -qfd
  workshop_py put "$rec" ready null
  workshop_py put "$rec" reopen null
  workshop_py put "$rec" asked null
  workshop_edge "$tree" w_decide w_drop person "$2" note="$ref"
  workshop_history "$tree" dropped
  info "  Dropped. It is kept as $ref: git -C $INSTRUMENTS log $ref"
}

# After a session, from claude_launch: what it made in the workshop goes out,
# or the person decides what becomes of it.
#
#   workshop_after_session <session> <the launch's arguments…>
workshop_after_session() {
  local session="$1" tree ws rec state red_back=0 missing
  # The session whose pass the edges below belong to (workshop_edge).
  local WORKSHOP_SESSION="$session"
  shift
  tree="$(workshop_tree)" || return 0
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] && workshop_py approved "$rec" "$session" || return 0
  ws="$(workshop_dir "$tree")"
  while :; do
    state="$(workshop_state "$tree")"
    workshop_history "$tree" "$state" "$session"
    [[ "$state" == none ]] && { workshop_py put "$rec" reopen null; return 0; }
    # The session to reopen, now or at a later opening: the last that worked
    # on the change.
    workshop_py reopen "$rec" "$session" "$PWD" "$@"
    if [[ "$state" == ready ]]; then
      workshop_edge "$tree" w_ready w_exit sclaude "the session ended"
    else
      workshop_edge "$tree" w_change w_exit sclaude "the session ended"
    fi
    workshop_edge "$tree" w_exit w_ready_gate sclaude ""
    if [[ "$state" == ready ]]; then
      WORKSHOP_RED=() WORKSHOP_NEXT=""
      # Red goes back into the session twice at most, unasked; then it is the
      # person's question.
      WORKSHOP_FROM=w_ready_gate WORKSHOP_BACK=$(( red_back < 2 )) workshop_publish "$tree"
      case "$WORKSHOP_NEXT" in
        back)
          red_back=$((red_back + 1))
          info "  Back into the session that made it, told what is red."
          workshop_history "$tree" sent-back "$session"
          claude_again_args "$@"
          resume_latest "${CLAUDE_AGAIN[@]}"
          claude_launch_once "${CLAUDE_LATEST[@]}" "$WORKSHOP_RED_WORD ${WORKSHOP_RED[*]}. Their output: $WORKSHOP_RED_LOG"
          continue ;;
        reopen)
          claude_again_args "$@"
          resume_latest "${CLAUDE_AGAIN[@]}"
          claude_launch_once "${CLAUDE_LATEST[@]}" "$WORKSHOP_REOPEN_WORD $WORKSHOP_WHY"
          continue ;;
      esac
      return 0
    fi
    missing="$(workshop_missing "$tree")"
    workshop_edge "$tree" w_ready_gate w_decide sclaude "" note="not finished"
    workshop_decide "$tree" "not finished" "$missing" reopen drop
    if [[ "$WORKSHOP_CHOICE" == reopen ]]; then
      claude_again_args "$@"
      claude_launch_once "${CLAUDE_AGAIN[@]}" "$WORKSHOP_RESUME $missing"
      continue
    fi
    return 0
  done
}

# Whenever the tree is opened (a start, done, a deferred review): a change
# still waiting on the person's answer is asked about again. A ready one goes
# through its checks again first, since main or the tests may have moved;
# one not finished is asked straight away.
#
#   workshop_pending <tree>
workshop_pending() {
  local tree="$1" rec ws session missing
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] || return 0
  ws="$(workshop_dir "$tree")"
  case "$(workshop_state "$tree")" in
    none) return 0 ;;
    ready)
      WORKSHOP_NEXT=""
      WORKSHOP_FROM=w_decide workshop_publish "$tree"
      [[ "$WORKSHOP_NEXT" == reopen ]] || return 0
      missing="$WORKSHOP_REOPEN_WORD $WORKSHOP_WHY" ;;
    unready)
      missing="$(workshop_missing "$tree")"
      workshop_edge "$tree" w_ready_gate w_decide sclaude "" note="not finished"
      workshop_decide "$tree" "not finished" "$missing" reopen drop
      [[ "$WORKSHOP_CHOICE" == reopen ]] || return 0
      missing="$WORKSHOP_RESUME $missing" ;;
  esac
  local -a saved=()
  mapfile -d '' -t saved < <(workshop_py reopen-args "$rec")
  session="$(workshop_py get "$rec" reopen.session)"
  claude_again_args "${saved[@]:1}"
  # The session reopened publishes its next head as any session does: a
  # core-send that led here is no send of what it will make.
  ( unset WORKSHOP_SEND WORKSHOP_FROM
    cd "${saved[0]}" || exit 0
    [[ -f "$tree/.sclaude/local/feature/state.json" ]] && declare -F dev_env_load >/dev/null \
      && dev_env_load "$tree"
    declare -F session_git_env >/dev/null && session_git_env "$session"
    claude_launch "${CLAUDE_AGAIN[@]}" "$missing" )
  return 0
}

# Whether the record names a session that can be reopened: its launch kept,
# and where it ran still there.
workshop_reopenable() {
  local -a saved=()
  mapfile -d '' -t saved < <(workshop_py reopen-args "$1" 2>/dev/null)
  (( ${#saved[@]} > 1 )) && [[ -d "${saved[0]}" ]]
}

# What in the change may name the product, for the person's question after
# the tests: the lines, one a line, or nothing. sclaude.leaks auto shows them
# and lets them go; ask and off ask about them alike — the person who sees
# them and sends is taking that risk knowingly. A send kept for the same
# lines (leaks_ok) does not ask about them again.
#
#   workshop_leaks <workshop> <base> <tree>
#
# The same lines found again, in the diff or in the messages, wherever a
# rebase onto a newer main moved them, are the same (P-3 in sreview's
# policies); a line not shown then is not.
workshop_leaks() {
  local ws="$1" base="$2" tree="$3" hits rec id found
  rec="$(workshop_record "$tree")"
  WORKSHOP_HITS="" WORKSHOP_HITS_ID=""
  if hits="$(workshop_py leaks "$ws" "$base" "$tree")"; then
    workshop_edge "$tree" w_leaks w_tests sclaude "workshop.py leaks" note="nothing found"
    return 0
  fi
  found="$(grep -c . <<< "$hits") line(s)"
  # Named without the commit, which a rebase or the squash renames.
  id="$(sed -E 's/^commit [0-9a-f]+: /commit: /' <<< "$hits" | sort | sha1sum | cut -c1-40)"
  if [[ -n "$id" && "$(workshop_py get "$rec" leaks_ok 2>/dev/null)" == "$id" ]]; then
    workshop_edge "$tree" w_leaks w_tests person "the same lines, sent before" note="$found"
    return 0
  fi
  if [[ "$(leaks_mode)" == auto ]]; then
    info "  sclaude.leaks is auto: these go out unasked:"
    local line; while IFS= read -r line; do info "     $line"; done <<< "$hits"
    workshop_edge "$tree" w_leaks w_tests setting "sclaude.leaks=auto" note="$found"
    return 0
  fi
  WORKSHOP_HITS="$hits" WORKSHOP_HITS_ID="$id"
  workshop_edge "$tree" w_leaks w_tests sclaude "workshop.py leaks" note="$found, asked after the tests"
  return 0
}

# How long the flagged lines may run and still reach a question in Telegram
# whole, with room for the lines around them: under ASK_CONTEXT_MAX in keepawake/asks.py.
WORKSHOP_PHONE_MAX=1200

# The tests the change touches, as CLAUDE.md picks them for a commit: every
# test file that names a changed file; and bash -n on every shell file. In a
# clean environment, since the session's (its git hooks, its question channel)
# is no test's business. Each test in a session of its own, with no terminal:
# one that checks what happens without a terminal (the picker's) would
# otherwise find the person's and wait there for a key. Its own session is
# also out of the terminal's reach for Ctrl-C and a closed tab, so those are
# caught here: the test's session gets the signal the terminal would have sent
# it (on Ctrl-C a test still runs its teardown), and so does sclaude.
#
#   workshop_tests <workshop> <base>
workshop_tests() {
  local ws="$1" base="$2" f t log pid rc sig="" saved
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
  local n=${#tests[@]} i=0 began=$SECONDS started tty="" line
  [[ -t 1 ]] && tty=1
  info "  Testing sclaude itself before it goes out: $n test file(s) the change touches."
  # Beside the workshop, not one file in /tmp for every tree: another
  # tree's run overwrote the output before anybody read it.
  log="$ws-tests.log"
  : > "$log"
  saved="$(trap -p INT TERM HUP)"
  trap 'sig=INT' INT; trap 'sig=TERM' TERM; trap 'sig=HUP' HUP
  for t in "${tests[@]}"; do
    # One line on the terminal, redrawn for each test (the feed gets the
    # outcome): a run of minutes with nothing on the screen reads as one that
    # hangs, and a line per test buried the question that came after it. A red
    # test keeps a line of its own.
    i=$((i + 1)) started=$SECONDS
    # Cut to the terminal's width: a line that wraps is cleared only on its
    # last row, and the rows above pile up.
    if [[ -n "$tty" ]]; then
      line="    [$i/$n] ${t#tests/} …"
      printf '\r\033[K%s%s%s' "$DIM" "${line:0:$(( ${COLUMNS:-$(tput cols 2>/dev/null || echo 80)} - 1 ))}" "$OFF"
    fi
    # In the background, so not a group leader: setsid then makes the session
    # in place, and $! is its id.
    ( cd "$ws" && exec setsid env -i HOME="$HOME" PATH="$PATH" USER="${USER:-}" LANG="${LANG:-C.UTF-8}" \
        TMPDIR="${TMPDIR:-/tmp}" python3 "$t" </dev/null >>"$log" 2>&1 ) &
    pid=$!
    wait "$pid"; rc=$?
    if [[ -n "$sig" ]]; then
      [[ -n "$tty" ]] && printf '\r\033[K'
      kill -s "$sig" -- "-$pid" 2>/dev/null
      # A second signal cuts a stuck teardown short; nothing outlives sclaude.
      wait "$pid" 2>/dev/null
      kill -KILL -- "-$pid" 2>/dev/null
      break
    fi
    if (( rc != 0 )); then
      [[ -n "$tty" ]] && printf '\r\033[K'
      printf '%s    ✗ %s, %ds%s\n' "$RED" "${t#tests/}" "$((SECONDS - started))" "$OFF"
      failed+=("$t")
    fi
  done
  [[ -n "$tty" && -z "$sig" ]] && printf '\r\033[K'
  trap - INT TERM HUP
  eval "$saved"
  [[ -n "$sig" ]] && { kill -s "$sig" "$BASHPID"; return 1; }
  # Said only when all is green: `failed` holds the bash -n failures too, and
  # "1 of 1 green" right above "Red: bash -n …" read as a pass.
  if (( ${#failed[@]} == 0 )); then
    (( n == 0 )) || info "  Tests: all $n green, $((SECONDS - began))s."
    # For the history's way out of the tests (workshop_consent).
    WORKSHOP_GREEN="$n test file(s) green, $((SECONDS - began))s"
    return 0
  fi
  warn "  Red: ${failed[*]} — not published; it stays in $ws. The output: $log"
  # For the question that sends the session back (workshop_after_session).
  WORKSHOP_RED=("${failed[@]}") WORKSHOP_RED_LOG="$log"
  return 1
}


# How a session's change in the workshop came out, in the feature's history
# (history_add): its state when the session ended (none, ready, unready) and
# how the publication went (main, pr; red when its tests were red and the
# person was asked, sent-back when red tests reopened the session unasked,
# asked when the person's question was left unanswered, reopened, dropped).
# The session is the one that ended, or WORKSHOP_SESSION for a publication:
# the process map plays the pass after that session.
#
#   workshop_history <tree> <op> [<session>]
workshop_history() {
  history_add "$1/.sclaude/local/feature/state.json" workshop "$2" \
    session="${3:-${WORKSHOP_SESSION:-}}"
}

# A way taken on the workshop's map (history_edge), in the pass of the
# session WORKSHOP_SESSION names, as workshop_history's rows are.
#
#   workshop_edge <tree> <from> <to> <by> <how> [<key>=<value>…]
workshop_edge() {
  local tree="$1"
  shift
  history_edge "$tree/.sclaude/local/feature/state.json" "$@" session="${WORKSHOP_SESSION:-}"
}

# Said to a session the person reopened from the question; what stopped the
# change follows it.
WORKSHOP_REOPEN_WORD="The person reopened this session for your change to sclaude in this feature's workshop, which sclaude did not publish. Look at what stopped it, change it in the workshop, commit, review it as your instructions say, and run \`sclaude core-ready\`; sclaude checks it again when you end the session. What stopped it:"

# Brings the workshop up to sclaude's main: fetched, and for a maintainer
# rebased onto it and squashed into one commit. Sets WORKSHOP_BASE, what the
# change is measured from, or WORKSHOP_WHY when it cannot.
#
#   workshop_prepare <tree>
workshop_prepare() {
  local tree="$1" ws rec start msg
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  start="$(workshop_py get "$rec" start)"
  # sclaude's own git, not the session's: its hooks and its trailer are for
  # what the session commits.
  local -a G=(env -u GIT_CONFIG_COUNT git -C "$ws")
  if ! GIT_TERMINAL_PROMPT=0 timeout 30 "${G[@]}" fetch -q origin main 2>/dev/null; then
    WORKSHOP_WHY="sclaude's repository is out of reach"
    return 1
  fi
  if developer_is_maintainer; then
    if ! "${G[@]}" rebase -q origin/main >/dev/null 2>&1; then
      "${G[@]}" rebase --abort >/dev/null 2>&1
      WORKSHOP_WHY="it conflicts with sclaude's main; the session can rebase it there"
      return 1
    fi
    WORKSHOP_BASE=origin/main
  else
    WORKSHOP_BASE="$start"
  fi
  if developer_is_maintainer && (( $("${G[@]}" rev-list --count origin/main..HEAD) > 1 )); then
    msg="$(workshop_py squash-message "$ws" origin/main)"
    "${G[@]}" reset -q --soft origin/main && "${G[@]}" commit -q -F - <<< "$msg" \
      || { WORKSHOP_WHY="it could not be squashed into one commit"; return 1; }
  fi
  # The rebase and the squash are sclaude's own and change nothing reviewed:
  # the head they leave is the ready one.
  workshop_py put "$rec" ready.head "\"$("${G[@]}" rev-parse HEAD)\""
  return 0
}

# Pushes the change: to main for a maintainer, as the workshop's own branch
# and its one pull request for anybody else. WORKSHOP_WHY when it did not go.
#
#   workshop_push <tree>
workshop_push() {
  local tree="$1" ws rec how branch
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  how="$(workshop_py get "$rec" ready.review 2>/dev/null || true)"
  local -a G=(env -u GIT_CONFIG_COUNT git -C "$ws")
  if developer_is_maintainer; then
    GIT_TERMINAL_PROMPT=0 "${G[@]}" push -q origin HEAD:main >/dev/null 2>&1 \
      || { WORKSHOP_WHY="the push to main was refused (main moved meanwhile?)"; return 1; }
    info "  ${GREEN}Published to sclaude's main${OFF}: $("${G[@]}" log -1 --format='%h %s')"
    return 0
  fi
  branch="$("${G[@]}" rev-parse --abbrev-ref HEAD)"
  PROPOSE_DIR="$ws" \
    PROPOSE_INTRO="Changes to sclaude made in a sclaude session's workshop and reviewed there (${how:-review not named}). Later pushes to the branch update this pull request." \
    instruments_propose "$branch" "$("${G[@]}" rev-list --count origin/main..HEAD)" \
    || { WORKSHOP_WHY="the pull request was not sent (no gh, no login, or the push failed)"; return 1; }
}

# What the person is shown before they decide whether it goes public: where
# it goes, the commits and the files, and the lines that may name the
# product.
#
#   workshop_shown <tree> <base>
workshop_shown() {
  local ws url where
  ws="$(workshop_dir "$1")"
  url="$(git -C "$ws" remote get-url origin 2>/dev/null)"
  [[ -n "$url" ]] || url="the repository of sclaude"
  developer_is_maintainer && where="a commit on its main" || where="a pull request"
  echo "It goes to $url, which is public, as $where:"
  git -C "$ws" log --format='%h %s' "$2..HEAD" 2>/dev/null
  git -C "$ws" diff --stat=100 "$2..HEAD" 2>/dev/null
  echo "The whole change: git -C $ws diff $2..HEAD"
  if [[ -n "${WORKSHOP_HITS:-}" ]]; then
    echo "sclaude's repository is public, and these lines may name the product:"
    echo "$WORKSHOP_HITS"
  fi
}

# Publishes what the tree's workshop holds, ready and reviewed, through its
# checks; every stop on the way is the person's question (workshop_decide).
# WORKSHOP_FROM says where it comes from: w_ready_gate after a session, which
# makes any question left open before stale; w_decide at an opening (or
# core-send), which comes back out of the question when one was left open,
# and from the ready gate when none was (a run cut off before it asked).
# WORKSHOP_SEND=1 (core-send) is the person's yes to sending, typed by hand:
# the commits are not shown again, but lines that may name the product still
# are, with the question — a send covers only what it was shown.
#
# A send that goes back through the checks (after red tests, a refused push,
# or core-send's) writes its way in only once the preparation is through:
# a preparation that fails first leaves the walk standing on the question.
# WORKSHOP_BACK=1 sends red tests back into the session unasked
# (WORKSHOP_NEXT=back); a reopen the person chose is WORKSHOP_NEXT=reopen,
# with what stopped it in WORKSHOP_WHY.
#
#   workshop_publish <tree>
workshop_publish() {
  # sent: how the person said send to what goes public (core-send, or their
  # answer at the question that showed it); entry: how a send back into the
  # checks was given, written once the preparation is through.
  # at: where the walk on the map stands, which every way written leaves from.
  local tree="$1" ws rec at=w_ready_gate step=prep ask="" opened=""
  local sent="${WORKSHOP_SEND:+sclaude core-send}" entry="${WORKSHOP_SEND:+sclaude core-send}"
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  WORKSHOP_GREEN="" WORKSHOP_NEXT="" WORKSHOP_WHY="" WORKSHOP_HITS=""
  if [[ "${WORKSHOP_FROM:-w_ready_gate}" == w_ready_gate ]]; then
    workshop_py put "$rec" asked null
  else
    opened=1
    workshop_py get "$rec" asked >/dev/null 2>&1 && at=w_decide
  fi
  echo ""
  info "${BOLD}sclaude's change from this tree's workshop${OFF}"
  # --no-pager: printed straight to the terminal, a list longer than the screen
  # would stop publishing in less until somebody pressed q.
  git --no-pager -C "$ws" log --format='     %h %s' "$(workshop_py get "$rec" start)..HEAD" --not origin/main 2>/dev/null
  while :; do
    case "$step" in
      prep)
        if ! workshop_prepare "$tree"; then
          [[ "$at" == w_ready_gate ]] && workshop_edge "$tree" w_ready_gate w_decide sclaude "" note="$WORKSHOP_WHY"
          at=w_decide entry=""
          workshop_decide "$tree" "$WORKSHOP_WHY" "" send reopen drop
          workshop_outcome || return 0
          # A send here is a try again, not a yes to what was never shown.
          entry="${ASKED_HOW:-the question}"
          continue
        fi
        # A run cut off midway (Ctrl-C in the tests, a closed terminal) left
        # the walk where it stopped, which nothing records: its opening's way
        # in leaves from the gate or the question, and the replay fills the
        # gap along the map. Approximate on purpose — the person's decision
        # of 2026-11-10: what goes out and what is asked stay exact, and a
        # field for where a run stopped is not worth its surface.
        if [[ -n "$entry$opened" ]]; then
          local by=person how="$entry"
          [[ -n "$entry" ]] || by=sclaude how="the tree opened again"
          if [[ "$at" == w_decide ]]; then
            workshop_edge "$tree" w_decide w_leaks "$by" "$how"
          else
            workshop_edge "$tree" w_ready_gate w_leaks "$by" "$how"
          fi
        else
          workshop_edge "$tree" w_ready_gate w_leaks sclaude "marked ready at the head" \
            note="reviewed: $(workshop_py get "$rec" ready.review 2>/dev/null || echo "not named")"
        fi
        entry="" opened=""
        step=checks ;;
      checks)
        workshop_leaks "$ws" "$WORKSHOP_BASE" "$tree"
        if ! workshop_tests "$ws" "$WORKSHOP_BASE"; then
          if [[ "${WORKSHOP_BACK:-0}" == 1 ]]; then
            workshop_edge "$tree" w_tests w_change sclaude "sent back unasked" note="red: ${WORKSHOP_RED[*]}"
            WORKSHOP_NEXT=back
            return 0
          fi
          workshop_edge "$tree" w_tests w_clear sclaude "" note="red: ${WORKSHOP_RED[*]}"
          workshop_history "$tree" red
          workshop_edge "$tree" w_clear w_decide sclaude "" note="red"
          workshop_decide "$tree" "red: ${WORKSHOP_RED[*]}" "The output: $WORKSHOP_RED_LOG" send reopen drop
          workshop_outcome || return 0
          entry="${ASKED_HOW:-the question}" at=w_decide step=prep
          continue
        fi
        workshop_edge "$tree" w_tests w_clear sclaude "" note="${WORKSHOP_GREEN:-}"
        step=clear ;;
      clear)
        # Asked on a hit — lines a send was not given for (leaks_ok) — or on
        # a machine where what goes public is shown first (sclaude.contribute
        # ask; off asks too — a session that made a change under it is the
        # exception, and the person's send is theirs to give), unless the
        # person sent it already by hand (core-send).
        ask=""
        [[ "$(contribute_mode)" != send && -z "$sent" ]] && ask=1
        [[ -n "$WORKSHOP_HITS" ]] && ask=1
        if [[ -z "$ask" ]]; then
          workshop_edge "$tree" w_clear w_who "$( [[ -n "$sent" ]] && echo person || echo setting)" \
            "${sent:-sclaude.contribute=send}"
          step=who
          continue
        fi
        workshop_edge "$tree" w_clear w_decide sclaude "" note="$( [[ -n "$WORKSHOP_HITS" ]] && echo "product details" || echo "sclaude.contribute=$(contribute_mode)")"
        workshop_decide "$tree" "$( [[ -n "$WORKSHOP_HITS" ]] && echo "it may name the product" || echo "it waits for your yes to go public")" \
          "$(workshop_shown "$tree" "$WORKSHOP_BASE")" send reopen drop
        workshop_outcome || return 0
        # A send is kept for the lines it was shown.
        [[ -n "${WORKSHOP_HITS_ID:-}" ]] && workshop_py put "$rec" leaks_ok "\"$WORKSHOP_HITS_ID\""
        workshop_edge "$tree" w_decide w_who person "$ASKED_HOW"
        sent="${ASKED_HOW:-the question}" step=who ;;
      who)
        if ! workshop_push "$tree"; then
          warn "  $WORKSHOP_WHY"
          workshop_edge "$tree" w_who w_decide sclaude "" note="$WORKSHOP_WHY"
          workshop_decide "$tree" "$WORKSHOP_WHY" "" send reopen drop
          workshop_outcome || return 0
          # Tried again from the start: for a maintainer main may have moved
          # under it, and what goes is checked on the base it goes onto.
          entry="${ASKED_HOW:-the question}" at=w_decide step=prep
          continue
        fi
        break ;;
    esac
  done
  local -a G=(env -u GIT_CONFIG_COUNT git -C "$ws")
  workshop_py put "$rec" start "\"$("${G[@]}" rev-parse HEAD)\""
  workshop_py put "$rec" ready null
  workshop_py put "$rec" reopen null
  workshop_py put "$rec" asked null
  if developer_is_maintainer; then
    workshop_edge "$tree" w_who w_main sclaude "MAINTAINERS" note="$("${G[@]}" log -1 --format='%h')"
    workshop_edge "$tree" w_main w_done sclaude ""
  else
    workshop_edge "$tree" w_who w_pr sclaude "MAINTAINERS" note="$("${G[@]}" rev-parse --abbrev-ref HEAD)"
    workshop_edge "$tree" w_pr w_done sclaude ""
  fi
  workshop_history "$tree" "$(developer_is_maintainer && echo main || echo pr)"
  developer_is_maintainer && workshop_live_update
  return 0
}

# After workshop_decide inside workshop_publish: 0 to go on with a send;
# 1 to stop — dropped, unanswered (asked again at the next opening), or a
# reopen, which the caller runs (WORKSHOP_NEXT=reopen).
workshop_outcome() {
  [[ "$WORKSHOP_CHOICE" == send ]] && return 0
  [[ "$WORKSHOP_CHOICE" == reopen ]] && WORKSHOP_NEXT=reopen
  return 1
}

# sclaude core-send: by the person, in the product's tree — the answer send
# to the question the workshop's change is waiting on, typed by hand: the
# checks run again as at an opening, without showing the commits again;
# lines that may name the product, red tests or a failed push still stop it
# with the question, whose reopen is acted on here too.
cmd_core_send() {
  local tree rec
  # The person's word, and only theirs: from a session it would be the yes
  # the question exists to ask for.
  [[ -z "${SCLAUDE_SESSION:-}" ]] \
    || die "core-send is the person's, not a session's: sclaude asks them when the session ends"
  tree="$(workshop_tree)" || die "run it inside the product's tree whose workshop holds the change"
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] || { info "  This tree has no workshop: nothing to send."; return 0; }
  case "$(workshop_state "$tree")" in
    ready) ;;
    none)  info "  Nothing in this tree's workshop waits to be sent."; return 0 ;;
    *)     die "the workshop's change is not finished: $(workshop_missing "$tree")" ;;
  esac
  WORKSHOP_SEND=1 workshop_pending "$tree"
}

# Brings the live checkout up to what was just published, when that is safe
# here and now — on main, clean, nobody else's sclaude running from it — so
# the next session runs the fix. Otherwise the next sclaude start does
# (instruments_sync).
workshop_live_update() {
  local other
  if [[ "$(update_mode)" != auto ]]; then
    info "  $INSTRUMENTS takes it with: $SELF update"
    return 0
  fi
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
# session of <tree> that may: the retrospective and the friction and monthly
# reviews, whose approved plan is the yes. Empty with no tree.
#
#   workshop_rules <tree>
workshop_rules() {
  local tree="$1" maintainer="" other=1
  [[ -n "$tree" && -f "$PROMPTS/_workshop.md" ]] || return 0
  if [[ "$(contribute_mode)" == off ]]; then
    SCLAUDE_V_INSTRUMENTS="$INSTRUMENTS" \
      python3 "$LIB/cycle/render_prompt.py" "$PROMPTS/_workshop-closed.md" "$PROMPTS"
    return
  fi
  developer_is_maintainer && { maintainer=1; other=""; }
  SCLAUDE_V_WORKSHOP="$(workshop_dir "$tree")" SCLAUDE_V_INSTRUMENTS="$INSTRUMENTS" \
    SCLAUDE_V_CORE_MAINTAINER="$maintainer" SCLAUDE_V_CORE_OTHER="$other" \
    python3 "$LIB/cycle/render_prompt.py" "$PROMPTS/_workshop.md" "$PROMPTS"
}
