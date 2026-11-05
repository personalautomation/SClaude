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
#     tree for anybody else. A change left unfinished is not published, and
#     its session is offered back, at once and when the feature is next opened;
#   * what goes out is the machine's to say (sclaude.contribute, developer.sh):
#     sent, shown and asked (workshop_consent), or not made at all — core-open
#     refuses under `off`, and `sclaude core-send` sends a change held back.
#
# The record of who may write and what is ready is .sclaude/local/
# instruments.json beside it (workshop.py), which write-guard.py reads.

# What a session sent back to its unfinished change is told; what exactly is
# missing (workshop_missing) follows it.
WORKSHOP_RESUME="You changed sclaude in this feature's workshop, and the change is not finished. sclaude reopened this session for it. Finish the change, commit it in the workshop, review it as your instructions say, and run \`sclaude core-ready\`; sclaude publishes it when you end the session. If the change should not go out at all, say so and leave it: nothing unfinished is published. What is missing:"

# Said to a session reopened because the tests before publishing were red,
# with the red files and where their output is after it.
WORKSHOP_RED_WORD="sclaude ran the tests your change to sclaude touches before publishing it, and some were red, so nothing was published. sclaude reopened this session for them. Read their output and find whose the failure is: run each red test again on your head, and on origin/main in the workshop. A test that passes on a second run is flaky, and a flaky test is still yours to make steady; one red on origin/main too is still yours to fix, as the repository's rules say. Fix it in the workshop, commit, review it as your instructions say, and run \`sclaude core-ready\`. When you end the session sclaude tests it again and publishes it. If the change should not go out at all, say so in your report: the person decides, and a head you leave as it was is checked again when the tree is next opened. Red:"

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

# Where the tree's workshop stands for <session>: none (nothing unpublished),
# ready, blocked (ready, but held back at this head: the person's no to the
# product's details or to sending it, sclaude.leaks off on a hit, or
# sclaude.contribute off; a new commit made ready, or core-send, lifts it),
# unready (uncommitted, or not marked ready at its head), or pending (an
# earlier session's change is unfinished there, which holds back everything
# made after it).
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
# it, sclaude.leaks is off and the check hit, or sclaude.contribute is off,
# and trying again would only ask again. A new commit there, marked ready, or core-send lifts it.
# Every other stop is tried again when the tree is next opened, whatever it
# was.
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
  local session="$1" tree ws rec state answer red_back=0 red_head="" by
  # The session whose pass the edges below belong to (workshop_edge).
  local WORKSHOP_SESSION="$session"
  shift
  tree="$(workshop_tree)" || return 0
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] && workshop_py approved "$rec" "$session" || return 0
  ws="$(workshop_dir "$tree")"
  while :; do
    state="$(workshop_state "$tree" "$session")"
    workshop_history "$tree" "$state" "$session"
    case "$state" in
      ready) workshop_edge "$tree" w_ready w_exit sclaude "the session ended" ;;
      unready) workshop_edge "$tree" w_change w_exit sclaude "the session ended" ;;
    esac
    [[ "$state" == none ]] || workshop_edge "$tree" w_exit w_ready_gate sclaude ""
    case "$state" in
      none) workshop_py put "$rec" pending null; return 0 ;;
      ready)
        workshop_py put "$rec" pending null
        # Sent back for red tests and left at the same head — whatever
        # ended the session: testing the same head again now tells nothing
        # new. It waits, ready, for the next opening, as any red run does;
        # a session that thinks it should not go out says so to the person.
        if [[ -n "$red_head" && "$(git -C "$ws" rev-parse HEAD)" == "$red_head" ]]; then
          info "  The session left it as it was: checked again when the tree is next opened."
          workshop_edge "$tree" w_ready_gate w_wait sclaude "the head as it was when sent back"
          workshop_history "$tree" unchanged "$session"
          return 0
        fi
        WORKSHOP_RED=()
        # Red now goes back into the session twice at most (below): the
        # publication writes its way out of the tests by that.
        WORKSHOP_FROM=w_ready_gate WORKSHOP_BACK=$(( red_back < 2 )) workshop_publish "$tree"
        (( ${#WORKSHOP_RED[@]} )) || return 0
        # Red before it went out: the session that made the change is the one
        # to look, while it still has the change in mind, rather than the
        # next opening of the tree trying the same tests again. Unasked — the
        # person said so — and twice at most, so that a test the session
        # cannot turn green does not hold the cycle in a loop.
        if (( red_back >= 2 )); then
          info "  Sent back twice and still red: left ready, checked again when the tree is next opened."
          return 0
        fi
        red_back=$((red_back + 1))
        red_head="$(git -C "$ws" rev-parse HEAD)"
        info "  Back into the session that made it, told what is red."
        workshop_history "$tree" sent-back "$session"
        claude_again_args "$@"
        # Where the conversation went on, if Claude Code moved it to a new id.
        resume_latest "${CLAUDE_AGAIN[@]}"
        claude_launch_once "${CLAUDE_LATEST[@]}" "$WORKSHOP_RED_WORD ${WORKSHOP_RED[*]}. Their output: $WORKSHOP_RED_LOG"
        continue ;;
      blocked)
        workshop_py put "$rec" pending null
        workshop_edge "$tree" w_ready_gate w_held sclaude "held at this head before" \
          note="$(workshop_py get "$rec" blocked.why)"
        info "  sclaude's change in $ws waits: $(workshop_py get "$rec" blocked.why)"
        return 0 ;;
      pending)
        workshop_edge "$tree" w_ready_gate w_pending sclaude "an earlier session's change is unfinished"
        warn "  This session's change to sclaude waits in $ws: an earlier session's there is unfinished."
        return 0 ;;
    esac
    echo ""
    local missing; missing="$(workshop_missing "$tree")"
    workshop_edge "$tree" w_ready_gate w_back sclaude "" note="$missing"
    warn "  This session changed sclaude in its workshop ($ws), and did not finish. Missing:"
    warn "  $missing"
    ask "  Back into the session to finish it? [y/n] " answer yn && by=person || by=none
    if is_yes "$answer"; then
      workshop_edge "$tree" w_back w_change person "$ASKED_HOW"
      claude_again_args "$@"
      claude_launch_once "${CLAUDE_AGAIN[@]}" "$WORKSHOP_RESUME $missing"
      continue
    fi
    workshop_py pending "$rec" "$session" "$PWD" "$@"
    workshop_edge "$tree" w_back w_pending "$by" "$ASKED_HOW"
    workshop_history "$tree" left "$session"
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
    ready) WORKSHOP_FROM=w_wait workshop_publish "$tree"; return 0 ;;
    blocked) info "  sclaude's change in $(workshop_dir "$tree") waits: $(workshop_py get "$rec" blocked.why)"
             return 0 ;;
  esac
  ws="$(workshop_dir "$tree")"
  if ! session="$(workshop_py get "$rec" pending.session 2>/dev/null)"; then
    # Unfinished with nobody recorded to send back — a run killed between the
    # session and its question: said, so it is not forgotten.
    [[ "$(workshop_state "$tree" "")" == unready ]] || return 0
    echo ""
    warn "  A change to sclaude in this tree's workshop ($ws) is unfinished, and no session is"
    warn "  recorded to finish it. Missing: $(workshop_missing "$tree")"
    warn "  The next session of this tree that opens the workshop can finish it."
    return 0
  fi
  echo ""
  # A session that cannot be sent back — its launch not recorded, or where
  # it ran gone — is said once and dropped, not offered on every opening.
  local -a saved=()
  mapfile -d '' -t saved < <(workshop_py pending-args "$rec")
  if (( ${#saved[@]} <= 1 )) || [[ ! -d "${saved[0]}" ]]; then
    warn "  An earlier session left a change to sclaude unfinished in $ws, and cannot be sent back"
    warn "  (where it ran is gone, or its launch was not recorded): finish it by hand there, or"
    warn "  a session of this tree that opens the workshop can. Missing: $(workshop_missing "$tree")"
    workshop_py put "$rec" pending null
    return 0
  fi
  local missing; missing="$(workshop_missing "$tree")"
  warn "  An earlier session left a change to sclaude unfinished in this tree's workshop ($ws). Missing:"
  warn "  $missing"
  ask "  Back into that session to finish it? [y/n] " answer yn
  if ! is_yes "$answer"; then
    info "  Left as it is: nothing of it is published until it is finished."
    return 0
  fi
  WORKSHOP_SESSION="$session" workshop_edge "$tree" w_pending w_change person "$ASKED_HOW"
  # The record stays until the session has finished it (workshop_after_session
  # clears it then): a run cut off after the session would lose it otherwise.
  claude_again_args "${saved[@]:1}"
  ( cd "${saved[0]}" || exit 0
    [[ -f "$tree/.sclaude/local/feature/state.json" ]] && declare -F dev_env_load >/dev/null \
      && dev_env_load "$tree"
    declare -F session_git_env >/dev/null && session_git_env "$session"
    claude_launch "${CLAUDE_AGAIN[@]}" "$WORKSHOP_RESUME $missing" )
  return 0
}

# What in the change may name the product: the person decides. 0 to go on,
# 1 held at the person's no, 2 not now, 3 held unasked by sclaude.leaks off
# (told apart for the history: the map does not play it as the person's no).
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
  if hits="$(workshop_py leaks "$ws" "$base" "$tree")"; then
    workshop_edge "$tree" w_leaks w_tests sclaude "workshop.py leaks" note="nothing found"
    return 0
  fi
  local found; found="$(grep -c . <<< "$hits") line(s)"
  # Named without the commit, which a rebase or the squash renames.
  id="$(sed -E 's/^commit [0-9a-f]+: /commit: /' <<< "$hits" | sort | sha1sum | cut -c1-40)"
  if [[ -n "$id" && "$(workshop_py get "$rec" leaks_ok 2>/dev/null)" == "$id" ]]; then
    workshop_edge "$tree" w_leaks w_leak_ask sclaude "workshop.py leaks" note="$found"
    workshop_edge "$tree" w_leak_ask w_tests person "the same lines, yes given before"
    return 0
  fi
  warn "  sclaude's repository is public, and the change may name the product:"
  # Every line, and through warn, so that the question in Telegram carries them
  # too: a "yes" is kept for all of them (below).
  local line
  while IFS= read -r line; do warn "     $line"; done <<< "$hits"
  # The machine's say in the question (sclaude.leaks, developer.sh). A
  # change the person sends by name (core-send) is asked, whatever it says:
  # they are at the terminal, and off would hold it again.
  local mode; mode="$(leaks_mode)"
  [[ -n "${WORKSHOP_SEND:-}" && "$mode" == off ]] && mode=ask
  case "$mode" in
    auto)
      info "  sclaude.leaks is auto: published with them, unasked."
      workshop_edge "$tree" w_leaks w_tests setting "sclaude.leaks=auto" note="$found"
      return 0 ;;
    off)
      info "  sclaude.leaks is off: not published; it stays in $ws, where a session of this tree can reword it."
      workshop_edge "$tree" w_leaks w_held setting "sclaude.leaks=off" note="$found"
      return 3 ;;
  esac
  workshop_edge "$tree" w_leaks w_leak_ask sclaude "workshop.py leaks" note="$found"
  # A list longer than a question in Telegram holds loses its middle there
  # (ASK_CONTEXT_MAX in keepawake/asks.py), and a "yes" from the phone
  # would cover lines never seen: such a list is asked at the terminal alone,
  # and nobody there is no answer — tried again later, not held.
  if (( ${#hits} > WORKSHOP_PHONE_MAX )); then
    warn "  Too many lines for a question on the phone: answer it here, at the terminal."
    if ! ASK_DIR="" ask "  Publish it anyway? [y/n] " answer yn; then
      info "  Nobody answered at the terminal: it is tried again when the tree is next opened."
      workshop_edge "$tree" w_leak_ask w_wait none "terminal" note="too long for the phone"
      return 2
    fi
  elif ! ask "  Publish it anyway? [y/n] " answer yn; then
    info "  Nobody answered: it is tried again when the tree is next opened."
    workshop_edge "$tree" w_leak_ask w_wait none ""
    return 2
  fi
  if is_yes "$answer"; then
    [[ -n "$id" ]] && workshop_py put "$rec" leaks_ok "\"$id\""
    workshop_edge "$tree" w_leak_ask w_tests person "$ASKED_HOW"
    return 0
  fi
  info "  Not published: it stays in $ws, where a session of this tree can reword it."
  workshop_edge "$tree" w_leak_ask w_held person "$ASKED_HOW"
  return 1
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
# (history_add): its state when the session ended (none, ready, blocked,
# pending, left) and how the publication went (main, pr, held, declined, waits, red,
# stopped; leaks-off and contribute-off for a hold the person was not asked about,
# leaks-waits for a leak question nobody answered), and sent-back when red tests reopen the session, unchanged when it
# leaves the head as it was. The session is the one that ended, or WORKSHOP_SESSION for a
# publication: the process map plays the pass after that session.
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

# Publishes what the tree's workshop holds, ready and reviewed: for a
# maintainer to main, rebased on origin's and squashed into one commit; for
# anybody else to the workshop's own branch and its one pull request.
#
#   workshop_publish <tree>
workshop_publish() {
  local tree="$1" ws rec start base how msg branch from="${WORKSHOP_FROM:-w_ready_gate}"
  ws="$(workshop_dir "$tree")"
  rec="$(workshop_record "$tree")"
  start="$(workshop_py get "$rec" start)"
  how="$(workshop_py get "$rec" ready.review 2>/dev/null || true)"
  # How the last try stopped, for whoever asks whether one more is worth it
  # (cmd_done): set again below when it stops on the way.
  workshop_py put "$rec" stopped null
  WORKSHOP_GREEN=""
  echo ""
  info "${BOLD}sclaude's change from this tree's workshop${OFF}"
  # Not what main has already: a try that stopped after its rebase leaves
  # start below the main it rebased on, and those commits are nobody's change.
  # --no-pager: printed straight to the terminal, a list longer than the screen
  # would stop publishing in less until somebody pressed q.
  git --no-pager -C "$ws" log --format='     %h %s' "$start..HEAD" --not origin/main 2>/dev/null
  # sclaude's own git, not the session's: its hooks and its trailer are for
  # what the session commits.
  local -a G=(env -u GIT_CONFIG_COUNT git -C "$ws")
  if ! GIT_TERMINAL_PROMPT=0 timeout 30 "${G[@]}" fetch -q origin main 2>/dev/null; then
    warn "  Could not reach sclaude's repository: not published; it stays in $ws, and is tried again when the tree is next opened."
    workshop_py put "$rec" stopped '"on the way"'
    [[ "$from" == w_ready_gate ]] && workshop_edge "$tree" w_ready_gate w_wait sclaude "git fetch" note="sclaude's repository out of reach"
    workshop_history "$tree" stopped
    return 0
  fi
  if developer_is_maintainer; then
    if ! "${G[@]}" rebase -q origin/main >/dev/null 2>&1; then
      "${G[@]}" rebase --abort >/dev/null 2>&1
      warn "  It conflicts with sclaude's main: not published; it stays in $ws, and is tried again when"
      warn "  the tree is next opened. A session of this tree can rebase it there and mark it ready again."
      [[ "$from" == w_ready_gate ]] && workshop_edge "$tree" w_ready_gate w_wait sclaude "git rebase" note="conflicts with sclaude's main"
      workshop_history "$tree" stopped
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
  # The way into the checks: the session's end, the tree opened again after
  # a wait, or the person's core-send.
  if [[ -n "${WORKSHOP_SEND:-}" && "$from" == w_held ]]; then
    workshop_edge "$tree" w_held w_leaks person "sclaude core-send"
  elif [[ -n "${WORKSHOP_SEND:-}" ]]; then
    workshop_edge "$tree" w_wait w_leaks person "sclaude core-send"
  elif [[ "$from" == w_wait ]]; then
    workshop_edge "$tree" w_wait w_leaks sclaude "the tree opened again"
  else
    workshop_edge "$tree" w_ready_gate w_leaks sclaude "marked ready at the head" note="reviewed: ${how:-not named}"
  fi
  local leaked=0
  workshop_leaks "$ws" "$base" "$tree" || leaked=$?
  if (( leaked == 1 )); then
    workshop_block "$tree" "held back for the product's details; a session of this tree rewords it"
    workshop_history "$tree" held
    return 0
  fi
  if (( leaked == 3 )); then
    workshop_block "$tree" "held back for the product's details, unasked (sclaude.leaks is off); a session of this tree rewords it, or $SELF core-send asks"
    workshop_history "$tree" leaks-off
    return 0
  fi
  (( leaked == 0 )) || { workshop_history "$tree" leaks-waits; return 0; }
  if ! workshop_tests "$ws" "$base"; then
    if [[ "${WORKSHOP_BACK:-0}" == 1 ]]; then
      workshop_edge "$tree" w_tests w_change sclaude "sent back unasked" note="red: ${WORKSHOP_RED[*]}"
    else
      info "  It is tried again when the tree is next opened."
      workshop_edge "$tree" w_tests w_wait sclaude "" note="red: ${WORKSHOP_RED[*]}"
    fi
    workshop_history "$tree" red
    return 0
  fi
  local consent=0
  workshop_consent "$tree" "$ws" "$base" || consent=$?
  if (( consent == 1 || consent == 3 )); then
    workshop_history "$tree" "$( (( consent == 1 )) && echo declined || echo contribute-off)"
    return 0
  fi
  (( consent == 0 )) || { workshop_history "$tree" waits; return 0; }
  if developer_is_maintainer; then
    if ! GIT_TERMINAL_PROMPT=0 "${G[@]}" push -q origin HEAD:main >/dev/null 2>&1; then
      warn "  The push to main was refused (main moved meanwhile?): it stays in $ws,"
      warn "  and is tried again when the tree is next opened."
      workshop_py put "$rec" stopped '"on the way"'
      workshop_edge "$tree" w_who w_wait sclaude "git push" note="the push to main was refused"
      workshop_history "$tree" stopped
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
           workshop_edge "$tree" w_who w_wait sclaude "gh" note="the pull request was not sent"
           workshop_history "$tree" stopped
           return 0; }
  fi
  workshop_py put "$rec" start "\"$("${G[@]}" rev-parse HEAD)\""
  workshop_py put "$rec" ready null
  workshop_py put "$rec" blocked null
  if developer_is_maintainer; then
    workshop_edge "$tree" w_who w_main sclaude "MAINTAINERS" note="$("${G[@]}" log -1 --format='%h')"
  else
    workshop_edge "$tree" w_who w_pr sclaude "MAINTAINERS" note="$branch"
  fi
  workshop_history "$tree" "$(developer_is_maintainer && echo main || echo pr)"
  developer_is_maintainer && workshop_live_update
  return 0
}

# Whether the workshop's change may go to sclaude's public repository now, by
# the machine's sclaude.contribute (developer.sh): `send` yes, `off` held,
# `ask` the person sees the commits and the files and says. 0 to send, 1
# held at this head by the person's no (a new commit or `sclaude core-send`
# lifts it), 3 held the same way, unasked, by `off`, 2 not now — tried
# again when the tree is next opened. WORKSHOP_SEND, set by
# core-send, is the person's yes already given.
#
#   workshop_consent <tree> <workshop> <base>
workshop_consent() {
  local tree="$1" ws="$2" base="$3" url where text line answer q mode
  mode="$(contribute_mode)"
  [[ -n "${WORKSHOP_SEND:-}" ]] && mode=core-send
  # Green, the way out of the tests: held unasked by off, else on to the question.
  if [[ "$mode" == off ]]; then
    workshop_edge "$tree" w_tests w_held setting "sclaude.contribute=off" note="${WORKSHOP_GREEN:-}"
  else
    workshop_edge "$tree" w_tests w_send sclaude "" note="${WORKSHOP_GREEN:-}"
  fi
  case "$mode" in
    core-send)
      workshop_edge "$tree" w_send w_who person "sclaude core-send"
      return 0 ;;
    send)
      workshop_edge "$tree" w_send w_who setting "sclaude.contribute=send"
      return 0 ;;
    off)
      workshop_block "$tree" "sending changes to sclaude is off on this machine (sclaude.contribute); $SELF core-send sends this one"
      return 3 ;;
  esac
  # Away ([g] ticked by hand or by sleep_mode, a night): nobody is there to
  # read what would go public, and a yes is not the away answer to that.
  if declare -F review_go_on >/dev/null && review_go_on "$tree"; then
    info "  You are away: sending sclaude's change to its public repository waits for you, and is asked when the tree is next opened."
    workshop_edge "$tree" w_send w_wait setting "[g] — you are away"
    return 2
  fi
  url="$(git -C "$ws" remote get-url origin 2>/dev/null)"
  developer_is_maintainer && where="a commit on its main" || where="a pull request"
  text="$(git -C "$ws" log --format='%h %s' "$base..HEAD" 2>/dev/null
          git -C "$ws" diff --stat=100 "$base..HEAD" 2>/dev/null)"
  echo ""
  [[ -n "$url" ]] || url="the repository of sclaude"
  info "  It goes to $url, which is public, as $where:"
  while IFS= read -r line; do info "     $line"; done <<< "$text"
  info "  The whole change: git -C $ws diff $base..HEAD"
  q="  Send it? [y/n] "
  # As with the leak question: a list the phone would show cut is answered
  # at the terminal, and nobody there is not a no.
  if (( ${#text} > WORKSHOP_PHONE_MAX )); then
    warn "  Too long for a question on the phone: answer it here, at the terminal."
    ASK_DIR="" ask "$q" answer yn \
      || { info "  Nobody answered at the terminal: it is asked again when the tree is next opened."
           workshop_edge "$tree" w_send w_wait none "terminal" note="too long for the phone"; return 2; }
  else
    ask "$q" answer yn \
      || { info "  Nobody answered: it is asked again when the tree is next opened."
           workshop_edge "$tree" w_send w_wait none ""; return 2; }
  fi
  if is_yes "$answer"; then
    workshop_edge "$tree" w_send w_who person "$ASKED_HOW"
    return 0
  fi
  workshop_block "$tree" "you did not send it; $SELF core-send in this tree sends it"
  workshop_edge "$tree" w_send w_held person "$ASKED_HOW"
  return 1
}

# sclaude core-send: by the person, in the product's tree — the workshop's
# change they held back (or that sclaude.contribute off kept) goes out now,
# through the same checks, their yes given.
cmd_core_send() {
  local tree rec
  # The person's word, and only theirs: from a session it would be the yes
  # sclaude.contribute and sclaude.leaks exist to ask for.
  [[ -z "${SCLAUDE_SESSION:-}" ]] \
    || die "core-send is the person's, not a session's: sclaude asks them when the session ends"
  tree="$(workshop_tree)" || die "run it inside the product's tree whose workshop holds the change"
  rec="$(workshop_record "$tree")"
  [[ -f "$rec" ]] || { info "  This tree has no workshop: nothing to send."; return 0; }
  local from=w_wait
  case "$(workshop_state "$tree" "")" in
    blocked) workshop_py put "$rec" blocked null; from=w_held ;;
    ready)   ;;
    none)    info "  Nothing in this tree's workshop waits to be sent."; return 0 ;;
    *)       die "the workshop's change is not finished: $(workshop_missing "$tree")" ;;
  esac
  WORKSHOP_SEND=1 WORKSHOP_FROM="$from" workshop_publish "$tree"
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
