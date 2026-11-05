#!/usr/bin/env bash
#
# Claude in a tab of its own, beside sclaude.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# A session takes the whole terminal, and what sclaude printed before it — the
# step, the review's news, the findings — scrolls out of sight for the hours the
# session runs. Where the terminal has tabs to open, the session goes into a
# new tab and sclaude's own output stays readable in the tab it was started in.
# A tab rather than a split pane: claude gets the full width of the window, and
# its tab carries the session name.
#
# Only under WSL2, on this machine's own console, is a tab opened. Everywhere
# else — ssh from Termius, the terminal inside code-server — claude runs in
# place, as it always did: over ssh into the same WSL, wt.exe is there and
# works, and it would open the tab on the desktop at home, where nobody is
# looking, while sclaude waited for a session nobody could reach.
#
# $WT_SESSION alone is not the test. A WSL console that Windows Terminal took
# over from somewhere else (Ubuntu from the Start menu, wsl.exe run by hand)
# has no $WT_SESSION, since nothing put it in WSLENV, and sessions ran in place
# there although a tab was what was wanted. What a local console always has is
# $WSL_INTEROP — init hands it to every process started through wsl.exe — and
# what ssh and code-server have is their own marks: $SSH_CONNECTION/$SSH_TTY
# and TERM_PROGRAM=vscode. $WT_SESSION, where present, settles it.
#
#   SCLAUDE_PANE=off   always in place.
#   SCLAUDE_PANE_WAIT  seconds to wait for the tab to start (default 20).
#   SCLAUDE_PANE_FOCUS=follow  let the new tab take the focus, as Windows
#                      Terminal does by itself; by default it goes back to the
#                      tab that had it (pane_focus_keep).

pane_available() {
  [[ "${SCLAUDE_PANE:-on}" != "off" ]] || return 1
  [[ -n "${WSL_DISTRO_NAME:-}" ]] || return 1
  [[ -t 0 && -t 1 ]] || return 1
  if [[ -z "${WT_SESSION:-}" ]]; then
    [[ -n "${WSL_INTEROP:-}" ]] || return 1
    [[ -z "${SSH_CONNECTION:-}${SSH_TTY:-}" ]] || return 1
    [[ "${TERM_PROGRAM:-}" != "vscode" ]] || return 1
  fi
  command -v wt.exe >/dev/null 2>&1
}

# The focus kept where it was while a tab opens: pane-focus.ps1, started before
# wt.exe and left running until the new tab is there. Returns once the script
# has seen which tab is selected; without powershell.exe, at once.
#
# The script takes whichever tab appears next for its own, so one launch at a
# time: two features resumed together after a usage limit would otherwise each
# note the other's new tab as the one to go back to. The lock is held by the
# script for as long as it runs. A script not ready within ten seconds — still
# waiting for the lock, or slow to start — is given up on, and this tab takes
# the focus. Killing it reaches only its WSL side, so the script is also told
# how long it has left once it holds the lock, and counts that from its own
# start by the Windows clock (the two clocks part after a sleep): past it, its
# snapshot may already hold this new tab, and it leaves without acting on some
# later one. Three seconds short of ours, for the start of powershell.exe that
# neither side counts.
PANE_FOCUS_PS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pane-focus.ps1"
pane_focus_keep() {
  [[ "${SCLAUDE_PANE_FOCUS:-stay}" != "follow" ]] || return 0
  command -v powershell.exe >/dev/null 2>&1 || return 0
  local fd line keeper lock="${TMPDIR:-/tmp}/sclaude-pane-focus.lock"
  local started=${EPOCHREALTIME/[.,]/}
  # Encoded rather than named by its path: a script on the WSL share is one
  # the execution policy may refuse to run. stdin from /dev/null: a Windows
  # program given the terminal reads from it through WSL, and would take keys
  # meant for sclaude or claude.
  exec {fd}< <(exec 9>>"$lock"; flock -w 10 9 || exit 0
               left=$(( 7000 - (${EPOCHREALTIME/[.,]/} - started) / 1000 ))
               (( left > 0 )) || exit 0
               encoded="$({ echo "\$budget = $left"; cat "$PANE_FOCUS_PS"; } \
                          | iconv -f UTF-8 -t UTF-16LE | base64 -w0)" || exit 0
               cd /mnt/c 2>/dev/null
               exec powershell.exe -NoProfile -NonInteractive -EncodedCommand "$encoded" </dev/null 2>/dev/null)
  keeper=$!
  read -r -t 10 -u "$fd" line || kill "$keeper" 2>/dev/null
  exec {fd}<&-
}

# claude, in a new tab where there can be one, in place otherwise.
#
#   claude_launch <claude args…>
#
# A drop-in for `claude`: called inside the same subshell, after the same cd
# and the same environment, and returning claude's own exit status.
#
# The tab is a fresh login under wsl.exe, which inherits nothing from here. So
# the tab runs a script that carries everything over: every exported variable
# (dev_env_load and session_git_env put the database and the git hooks there),
# the working directory and the arguments, each quoted by printf %q. Through a
# file rather than on wt.exe's command line also because wt.exe splits its own
# arguments on `;`, and a prompt is full of them.
#
# wt.exe returns at once, so the wait is ours: the script records its pid, and
# we wait for that pid to go. A tab closed by its cross ends the script with
# it, which reads here as the session ending — the same as /exit. The script
# rather than claude is what we wait for, and claude is not exec'ed: a tab
# whose process exits non-zero stays open with an "exited with code" banner, and
# claude ended by the session watcher exits 143. The script exits 0 and the
# tab closes; claude's status comes back through a file.
#
# The session watcher (session_watch_start) needs nothing new: it finds claude
# by its arguments, and both tabs live in the same distribution.
claude_launch() {
  local session="" i next status
  for ((i = 1; i < $#; i++)); do
    case "${!i}" in
      --session-id|--resume) next=$((i + 1)); session="${!next}"; break ;;
    esac
  done
  # The kind's emoji goes into the name itself (named_with_icon): claude sets
  # the tab title from the session name, over whatever wt.exe was given.
  local -a args=()
  local named=""
  for arg in "$@"; do
    if [[ -n "$named" ]]; then args+=("$(named_with_icon "$arg")"); named=""; continue; fi
    [[ "$arg" == "-n" ]] && named=1
    args+=("$arg")
  done
  set -- "${args[@]}"
  resume_latest "$@"
  set -- "${CLAUDE_LATEST[@]}"
  # The session's id reaches its commands: `sclaude core-open` and
  # `core-ready` name the session they are run by (workshop.sh).
  [[ -n "$session" ]] && export SCLAUDE_SESSION="$session"
  # The id the tab wait's session keys act on (session_keys): not
  # SCLAUDE_SESSION, which a sclaude run from inside a session inherits.
  SESSION_KEYS_ID="$session"
  # A restart nobody carried out — pressed in a launch outside the loop
  # below — is not this launch's to reopen.
  local ctl; ctl="$(session_ctl_file "$session")"
  [[ -n "$session" && "$(cat "$ctl" 2>/dev/null)" == restart* ]] && rm -f "$ctl"
  claude_launch_once "$@"
  status=$?
  # Closed by the session watcher because the usage limit had reset, or by
  # [r] in sclaude's tab (session_keys), not ended: opened again where it
  # stopped (claude_again_args). After the limit with a word to carry on; after
  # [r] silently, so that the reopening costs no turn of its own.
  local limit_file="${TMPDIR:-/tmp}/sclaude-limit-$session"
  while [[ -n "$session" ]]; do
    local word=()
    if [[ -s "$limit_file" ]]; then
      rm -f "$limit_file"
      echo ""
      info "   The usage limit has reset — resuming the session where it stopped."
      word=("$CLAUDE_LIMIT_RESUME")
    elif [[ "$(cat "$ctl" 2>/dev/null)" == restarting ]]; then
      rm -f "$ctl"
      echo ""
      info "   Reopening the same conversation, as you asked ([r])."
    else
      break
    fi
    claude_again_args "$@"
    resume_latest "${CLAUDE_AGAIN[@]}"
    CLAUDE_AGAIN=("${CLAUDE_LATEST[@]}")
    claude_launch_once "${CLAUDE_AGAIN[@]}" "${word[@]}"
    status=$?
  done
  # What it changed in sclaude, in the tree's workshop: published, or the
  # session offered back to finish it.
  [[ -n "$session" ]] && declare -F workshop_after_session >/dev/null \
    && workshop_after_session "$session" "$@"
  # Whether the session's screen is gone with it: a tab closes when claude
  # exits, and its last message with it; in place it stays on the screen.
  # session_ended prints it again for a tab (session_report). Marked after
  # the last launch, the one the person left. A file named by the session,
  # not a variable: the caller runs this in a subshell, and a code reload
  # replaces the process between the exit and that point.
  [[ -n "$session" ]] && pane_mark "$session" "$SCLAUDE_IN_PANE"
  return "$status"
}

# The launch's arguments into CLAUDE_LATEST, with a `--resume` taken to where
# the conversation went on: Claude Code may give a running conversation a new
# id, and hides the old one as superseded (session_latest in state.sh).
# Everything else of sclaude's keeps the id it launched with — SCLAUDE_SESSION,
# state.json, the usage-limit file — and the watcher finds the process by any
# id of the chain.
#
#   resume_latest <the launch's arguments…>
resume_latest() {
  local arg resume=""
  CLAUDE_LATEST=()
  for arg in "$@"; do
    if [[ -n "$resume" ]] && declare -F session_latest >/dev/null; then
      arg="$(session_latest "$PWD" "$arg")"
    fi
    resume=""
    [[ "$arg" == "--resume" ]] && resume=1
    CLAUDE_LATEST+=("$arg")
  done
}

# The arguments that open a launched session again, into CLAUDE_AGAIN: the
# first launch's up to and including `-n <name>`, which every caller passes
# right before its prompt; the prompt gives way to the caller's word to carry
# on, since the opening one was answered long ago. A `--session-id` becomes
# `--resume`, since the conversation now exists.
#
#   claude_again_args <the launch's arguments…>
claude_again_args() {
  local arg named=""
  CLAUDE_AGAIN=()
  for arg in "$@"; do
    if [[ -n "$named" ]]; then CLAUDE_AGAIN+=("$arg"); break; fi
    case "$arg" in
      --session-id) CLAUDE_AGAIN+=(--resume) ;;
      -n) CLAUDE_AGAIN+=(-n); named=1 ;;
      *) CLAUDE_AGAIN+=("$arg") ;;
    esac
  done
}

# What a session reopened after a usage limit is told.
CLAUDE_LIMIT_RESUME="The usage limit that stopped you has reset; sclaude reopened this session. Carry on where you stopped. A subagent or background command the limit cut off did not finish — check what it left and start it again if its work is still needed."

# claude in this very terminal. When the run is recorded (terminal.sh), the
# session's screen is marked off on both sides: it is in the session's
# transcript already, and the playback leaves only a line naming it.
#
# SCLAUDE_FROM_PHONE stays with sclaude: it tells sclaude's own questions the
# person is on the phone. In the session it told nothing — its commands have
# no terminal anyway — and reached every test the session ran, whose
# terminal cases then failed.
claude_here() {
  local status phone="${SCLAUDE_FROM_PHONE-}" had="${SCLAUDE_FROM_PHONE+1}"
  declare -F term_skip >/dev/null && term_skip begin "$@"
  # Not in a subshell: claude stands in as a function in the benches, and
  # what it counts must outlive the call.
  unset SCLAUDE_FROM_PHONE
  claude "$@"
  status=$?
  [[ -n "$had" ]] && export SCLAUDE_FROM_PHONE="$phone"
  declare -F term_skip >/dev/null && term_skip end
  return "$status"
}

# The emoji of a session's kind, by what its name (session_label) says it is,
# so the tabs tell the stages apart at a glance.
#
# The icons are phase_icon's (steps.sh), the ones the feature's topic opens
# each line about the session with: one table for both.
pane_icon() {
  case "$1" in
    *friction*)             phase_icon friction ;;
    *-fix-*)                phase_icon fix ;;
    [0-9]*-plan[/\(\ ]*)    phase_icon step plan ;;
    [0-9]*-code[/\(\ ]*)    phase_icon step code ;;
    [0-9]*-pr[/\(\ ]*)      phase_icon step pr ;;
    [0-9]*-review[/\(\ ]*)  phase_icon step review ;;
    [0-9]*-sync[/\(\ ]*)    phase_icon sync ;;
    [0-9]*-epilogue[/\(\ ]*) phase_icon epilogue ;;
    [0-9]*-retro[/\(\ ]*)   phase_icon retro ;;
  esac
}

# A session name with its kind's emoji between the label and the slug:
# `4-review(2)/12-login` is `4-review(2) 🛠/12-login`. In the name rather than
# only in wt.exe's --title, because claude titles the tab with the session
# name and the title given at the start does not survive; and before the
# slash, because the tab cuts a long title at its end, where the slug is. A
# name that has its emoji already, or no kind, is returned as it is.
named_with_icon() {
  local name="$1" icon head
  [[ "$name" == */* && "${name%%/*}" != *" "* ]] || { printf '%s' "$name"; return; }
  icon="$(pane_icon "$name")"
  [[ -n "$icon" ]] || { printf '%s' "$name"; return; }
  head="${name%%/*}"
  printf '%s %s/%s' "$head" "$icon" "${name#*/}"
}

# The session's keys in sclaude's tab, while the session runs in its own.
#
# A session ends itself: it writes its marker, or the plan is approved, and
# the watcher closes it (session_watch_start). Agreeing with it in the session
# costs a turn — an approval in the plan dialog is read with the whole
# conversation behind it — and some sessions are better closed, or kept, on
# the person's word. So this terminal, free while the session works in its
# tab, takes these keys (session_keys, from the tab wait in
# claude_launch_once). The letter says where the work goes on, the case when:
#
#   [n] forward, now: the session is closed as if it had ended itself — the
#       watcher writes its marker, and for a step the plan on screen counts as
#       approved and step 2's work as accepted (session_take_as_done in
#       run.sh); everything after runs as on that end, the friction review
#       and the step's checks included, and the cycle goes on;
#   [N] forward, later: the same, and sclaude stops where the next step, or
#       production after step 4, would begin (stop_asked in session_watch.sh);
#   [r] again, now: the session is closed as /exit would close it, and the
#       same conversation is opened again at once, without a message
#       (claude_launch): a fresh claude process, nothing for it to read;
#   [R] again, later: closed as /exit would close it, and sclaude stops; the
#       next `sclaude <feature>` opens this conversation again — a step's
#       after its friction review (session_ended in run.sh), any other kind
#       at once, as if the terminal had been closed (session_watch_stop);
#   [k] keep it open: the watcher does not close it on its marker or the
#       plan's approval; pressed again, it does. A state rather than a word
#       about the end, so it has a file of its own (session_keep_file), which
#       [r] leaves standing.
#
# Every key is pressed twice within five seconds: a stray one changes
# nothing. [n], [N], [R] and [k] need the watcher, which writes the marker and
# does the closing; the retrospective, whose own marker means "nothing to act
# on", has no marker written for it, and [n] closes it as its /exit would.
#
# The word is a file named by the session (session_ctl_file), since the ones
# who read it — the watcher, claude_launch, session_ended — are other
# processes or come after a code reload. [r] is the watcher's to carry out
# where there is one: it goes on for the reopened conversation as a resumed
# session's watcher would — the marker off, nothing before the reopening
# counted — then writes `restarting` for claude_launch and ends the process.
# Left to claude_launch alone, the watcher still held the old "its work is
# done" and closed the reopened conversation within a poll. Without a tab there are no keys:
# claude has the terminal.
SESSION_KEYS_ARMED=""
SESSION_KEYS_AT=0
session_ctl_file()     { printf '%s/sclaude-ctl-%s' "${TMPDIR:-/tmp}" "$1"; }
session_keep_file()    { printf '%s/sclaude-keep-%s' "${TMPDIR:-/tmp}" "$1"; }
# Written by session_watch_start with the watcher's kind, removed when it stops.
session_watched_file() { printf '%s/sclaude-watch-%s' "${TMPDIR:-/tmp}" "$1"; }

# The word the person gave for a session that has ended, taken: next,
# next-later or later (a restart is taken by claude_launch). Empty when none.
#
#   session_ctl_take <session>
session_ctl_take() {
  local file word
  file="$(session_ctl_file "$1")"
  word="$(cat "$file" 2>/dev/null || true)"
  rm -f "$file"
  case "$word" in next|next-later|later) printf '%s' "$word" ;; esac
}

# Whether a watcher runs beside this session: its mark names its pid.
session_watcher_alive() {
  local kind pid
  { read -r kind pid < "$(session_watched_file "$SESSION_KEYS_ID")"; } 2>/dev/null || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}

# Whether this session takes the key: see above.
session_key_has() {
  case "$1" in
    r) return 0 ;;
    n|N|R|k) session_watcher_alive ;;
    *) return 1 ;;
  esac
}

session_key_words() {
  case "$1" in
    n) echo "forward, now: close it as if it had finished, and go on" ;;
    N) echo "forward, later: close it as if it had finished; sclaude stops before the next step" ;;
    r) echo "again, now: close it and reopen the same conversation" ;;
    R) echo "again, later: close it; sclaude stops, and opens this conversation next time" ;;
    k) echo "keep it open: no closing by itself (again to undo)" ;;
  esac
}

# The same, in a word or two, for the legend: the long words are said when a
# key is pressed, where they are read.
session_key_label() {
  case "$1" in
    n) echo "next" ;;
    N) echo "next, not now" ;;
    r) echo "reopen" ;;
    R) echo "reopen, not now" ;;
    k) echo "keep it open" ;;
  esac
}

# A line above the status line, which the next tick draws again.
session_keys_say() {
  printf '\r\033[2K' >&2
  info "   $*"
}

# The keys this session takes, said once as the wait begins: one line. Five
# lines of them, every session, buried the lines above that said where the
# feature stood; what a key does in full is said when it is pressed.
session_keys_legend() {
  local k line=""
  for k in n N r R; do
    session_key_has "$k" && line+="${line:+ · }${BOLD:-}[$k]${OFF:-} $(session_key_label "$k")"
  done
  [[ -n "$line" ]] && info "   ${DIM:-}Keys here, each pressed twice:${OFF:-} $line"
  return 0
}

# What the session's keys add to a wait's status line: [k]'s box, green when
# ticked, and a key pressed once, waiting for its second press. Both on the
# status line, not as lines of their own: a toggle said in words was two
# lines a press, and four for a press taken back.
session_keys_tail() {
  local out="" now
  if session_key_has k; then
    if [[ -e "$(session_keep_file "$SESSION_KEYS_ID")" ]]; then
      out=" · ${GREEN:-}☑${OFF:-} ${BOLD:-}[k]${OFF:-} ${GREEN:-}kept open${OFF:-}"
    else
      out=" · ☐ ${BOLD:-}[k]${OFF:-} keep open"
    fi
  fi
  now="$(date +%s)"
  if [[ -n "${SESSION_KEYS_ARMED:-}" ]] && (( now - SESSION_KEYS_AT <= 5 )); then
    # The legend's word, not the long one: a status line wider than the
    # terminal wrapped, and every redraw left a copy of it on the screen.
    out+=" · ${YELLOW:-}[$SESSION_KEYS_ARMED] $(session_key_label "$SESSION_KEYS_ARMED") — press $SESSION_KEYS_ARMED again to finish${OFF:-}"
  fi
  printf '%s' "$out"
}

# The status line of a wait with no keys of the caller's.
session_keys_line() {
  printf '\r\033[2K\033[?7l\033[?25l  %sThe session works in its tab%s%s\033[?7h' \
    "${DIM:-}" "${OFF:-}" "$(session_keys_tail)" >&2
}

# One tick of the tab wait: <key> pressed, or empty. Returns 0 when the key
# was this session's, 1 to hand it on to the caller's keys. The case counts:
# n and N are two keys.
#
#   session_keys <key> <pid of the tab's script>
session_keys() {
  local key="${1:-}" pid="$2" ctl word now
  [[ -n "$key" ]] || return 1
  # Another key cancels one pressed once: its yellow goes from the status line.
  session_key_has "$key" || { SESSION_KEYS_ARMED=""; return 1; }
  ctl="$(session_ctl_file "$SESSION_KEYS_ID")"
  now="$(date +%s)"
  if [[ "$SESSION_KEYS_ARMED" != "$key" ]] || (( now - SESSION_KEYS_AT > 5 )); then
    # Said on the status line (session_keys_tail), for five seconds.
    SESSION_KEYS_ARMED="$key"
    SESSION_KEYS_AT="$now"
    return 0
  fi
  SESSION_KEYS_ARMED=""
  if [[ "$key" == k ]]; then
    local keep; keep="$(session_keep_file "$SESSION_KEYS_ID")"
    # Its box on the status line says it (session_keys_tail).
    if [[ -e "$keep" ]]; then rm -f "$keep"; else : > "$keep"; fi
    return 0
  fi
  case "$key" in
    n) word=next ;;
    N) word=next-later ;;
    r) word=restart ;;
    R) word=later ;;
  esac
  # With no watcher, [r] is carried out here: there is no marker to take off.
  [[ "$word" == restart ]] && ! session_watcher_alive && word=restarting
  echo "$word" > "$ctl"
  session_keys_say "[$key] $(session_key_words "$key")."
  # Forward and a watched restart are the watcher's to close: it writes or
  # takes off the session's marker first.
  [[ "$word" == next* || "$word" == restart ]] || pkill -TERM -P "$pid" 2>/dev/null || true
  return 0
}

# The mark a session that ran in a tab leaves for session_ended.
#
#   pane_mark <session> <1 or empty>   set or clear it
#   pane_marked <session>              true once, when it was set; clears it
pane_mark() {
  local file="${TMPDIR:-/tmp}/sclaude-in-pane-$1"
  if [[ -n "$2" ]]; then : > "$file"; else rm -f "$file"; fi
}
pane_marked() {
  local file="${TMPDIR:-/tmp}/sclaude-in-pane-$1"
  [[ -e "$file" ]] || return 1
  rm -f "$file"
}

# Where a claude run in a tab leaves its stderr and its exit, relative to the
# feature's worktree. Appended to, run after run.
PANE_LOG=".sclaude/local/feature/claude-tab.log"

# How the last claude run in a tab ended, from PANE_LOG: its exit code on the
# first line, then the last few lines it wrote on stderr. Nothing when the log
# has no finished run. For a session that left at once: its tab closed with
# it, and the terminal sclaude runs in never saw what it printed.
#
#   pane_last_exit <wt>
pane_last_exit() {
  local log="$1/$PANE_LOG"
  [[ -s "$log" ]] || return 0
  awk '
    / started$/ && /^=== / { n = 0; code = ""; next }
    /^=== .* exit [0-9]+$/ { code = $NF; next }
    { if (length($0)) said[n++] = $0 }
    END {
      if (code == "") exit
      print code
      for (i = (n > 5 ? n - 5 : 0); i < n; i++) print said[i]
    }' "$log"
}

# One launch of claude, in a tab or in place. claude_launch around it adds the
# return after a usage limit.
claude_launch_once() {
  SCLAUDE_IN_PANE=""
  if ! pane_available; then
    claude_here "$@"
    return
  fi

  local dir; dir="$(mktemp -d "${TMPDIR:-/tmp}/sclaude-pane.XXXXXX")" || { claude_here "$@"; return; }
  local script="$dir/run" title="claude" i name
  for ((i = 1; i < $#; i++)); do
    [[ "${!i}" == "-n" ]] && { name=$((i + 1)); title="${!name}"; break; }
  done

  {
    echo "#!/usr/bin/env bash"
    # Not carried over: what belongs to the tab sclaude runs in. WSL_INTEROP
    # names this login's interop socket, and the new tab has its own;
    # SCLAUDE_FROM_PHONE is sclaude's, not the session's (claude_here).
    for name in $(compgen -e); do
      case "$name" in
        WSL_INTEROP|WT_SESSION|WT_PROFILE_ID|SHLVL|PWD|OLDPWD|_|SCLAUDE_FROM_PHONE) continue ;;
      esac
      printf 'export %s=%q\n' "$name" "${!name}"
    done
    printf 'cd -- %q || exit 0\n' "$PWD"
    # Whoever makes the directory first runs claude: the tab, or sclaude
    # itself after giving up on it (below). Never both.
    printf 'mkdir %q 2>/dev/null || exit 0\n' "$dir/claimed"
    printf 'echo $$ > %q.tmp && mv %q.tmp %q\n' "$dir/pid" "$dir/pid" "$dir/pid"
    # What claude said on stderr and how it exited, kept in the feature's
    # worktree (PANE_LOG): the tab closes with claude, and a session that left
    # at once — as one did on its resume, its transcript untouched — left
    # nothing to tell why. Through tee, so the tab still shows it. Only in a
    # feature's tree, which its clean-up removes with the log.
    local log=""
    [[ -d "$PWD/.sclaude/local/feature" ]] && log="$PWD/$PANE_LOG"
    if [[ -n "$log" ]]; then
      printf 'echo "=== $(date -Iseconds)" %q >> %q\n' "$title started" "$log"
      printf 'claude'
      printf ' %q' "$@"
      # The tee deaf to the signals the tab ends claude with (the trap below
      # signals every child): it lives until claude closes its stderr, and
      # claude winding down never writes into a pipe nobody reads.
      printf ' 2> >(trap %q INT TERM HUP; exec tee -a %q >&2)\n' "" "$log"
      # The tee runs on its own: waited for a moment, so what claude said is
      # in the log before the line saying how it exited — and no longer,
      # since a child claude left running (an MCP server, a dev server) may
      # hold its stderr open, and the tee with it, for good.
      printf 'rc=$?; n=0; for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 $! 2>/dev/null || break; sleep 0.2; n=$((n+1)); done\n'
      printf 'echo "=== $(date -Iseconds) exit $rc" >> %q\n' "$log"
      printf 'echo $rc > %q\n' "$dir/status"
      # How long the tee took, and whether it outlived the wait. Decided with
      # builtins, then written by a child of its own: sclaude waits for this
      # tab's process to end, not for its status, and the note holds it up
      # by nothing.
      if [[ -n "${SCLAUDE_WAITS_LOG:-}" ]]; then
        printf 'alive=done; ((n >= 10)) && kill -0 $! 2>/dev/null && alive=outlived\n'
        printf '( trap "" HUP; source %q && SCLAUDE_WAITS_LOG=%q wait_note tab-tee "$alive" "$((n / 5)).$((n %% 5 * 2))" "exit $rc" ) </dev/null >/dev/null 2>&1 &\n' \
          "$LIB/core/ui.sh" "$SCLAUDE_WAITS_LOG"
      fi
    else
      printf 'claude'
      printf ' %q' "$@"
      printf '\n'
      printf 'echo $? > %q\n' "$dir/status"
    fi
    echo 'exit 0'
  } > "$script"

  # From a Windows directory: wt.exe and wsl.exe complain about a cwd inside
  # the distribution, which they see as a UNC path.
  pane_focus_keep
  if ! ( cd /mnt/c 2>/dev/null; wt.exe -w 0 new-tab --title "$title" \
           wsl.exe -d "$WSL_DISTRO_NAME" -- bash "$script" ) >/dev/null 2>&1; then
    rm -rf "$dir"
    claude_here "$@"
    return
  fi

  local waited=0 pid=""
  while [[ ! -s "$dir/pid" ]]; do
    if (( waited >= ${SCLAUDE_PANE_WAIT:-20} )) && mkdir "$dir/claimed" 2>/dev/null; then
      warn "   the new tab did not start — claude runs here instead"
      rm -rf "$dir"
      claude_here "$@"
      return
    fi
    sleep 1
    waited=$((waited + 1))
  done
  pid="$(cat "$dir/pid")"
  SCLAUDE_IN_PANE=1

  # And which conversation: a review round may go on in the one that fixed
  # the last round's findings or start afresh, and the heading above says
  # it only for a resume with something new to tell.
  local which="new session" arg
  for arg in "$@"; do [[ "$arg" == --resume ]] && { which="same session, resumed"; break; }; done
  info "   claude is running in a new tab ($title) · $which."
  # Left here, Ctrl-C would end sclaude and leave the session running with
  # nobody to carry on after it: no next step, no friction review. It ends the
  # session instead, and sclaude goes on as after an /exit. A sclaude tab
  # closed by its cross does the same, rather than leave claude orphaned.
  # The caller's keys for this wait, if it has any (PANE_KEYS: a command, the
  # key pressed appended): the session is in another tab, so this terminal's
  # keys are free. Called once a second, with an empty key after none. The
  # session's own keys (session_keys) come first, for every session sclaude
  # launches with an id; a key they take is not handed on.
  local keys=""
  [[ -n "${PANE_KEYS[*]:-}" || -n "${SESSION_KEYS_ID:-}" ]] && keys_usable && keys=1
  [[ -n "$keys" && -n "${SESSION_KEYS_ID:-}" ]] && session_keys_legend
  # No echo meanwhile: a key pressed while the caller reads its state, between
  # two reads, would land on its status line. The mode is saved and given
  # back as it was, on the way out too.
  local mode=""
  [[ -n "$keys" ]] && { mode="$(stty -g < /dev/tty 2>/dev/null)"; stty -echo < /dev/tty 2>/dev/null; }
  trap 'pkill -TERM -P "$pid" 2>/dev/null || true; [[ -n "$mode" ]] && stty "$mode" < /dev/tty 2>/dev/null' INT TERM HUP
  while kill -0 "$pid" 2>/dev/null; do
    if [[ -n "$keys" ]]; then
      poll_pause 1
      if [[ -n "${SESSION_KEYS_ID:-}" ]] && session_keys "$POLL_KEY" "$pid"; then
        POLL_KEY=""
      fi
      if [[ -n "${PANE_KEYS[*]:-}" ]]; then
        "${PANE_KEYS[@]}" "$POLL_KEY"
      else
        session_keys_line
      fi
    else
      sleep 1
    fi
  done
  [[ -n "$keys" ]] && printf '\r\033[2K\033[?25h' >&2
  [[ -n "$mode" ]] && stty "$mode" < /dev/tty 2>/dev/null
  trap - INT TERM HUP

  local status=1
  [[ -s "$dir/status" ]] && status="$(cat "$dir/status")"
  rm -rf "$dir"
  return "$status"
}
