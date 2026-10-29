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
  claude_launch_once "$@"
  status=$?
  # Closed by the session watcher because the usage limit had reset, not
  # ended: opened again where it stopped (claude_again_args).
  local limit_file="${TMPDIR:-/tmp}/sclaude-limit-$session"
  while [[ -n "$session" && -s "$limit_file" ]]; do
    rm -f "$limit_file"
    claude_again_args "$@"
    resume_latest "${CLAUDE_AGAIN[@]}"
    CLAUDE_AGAIN=("${CLAUDE_LATEST[@]}")
    echo ""
    info "   The usage limit has reset — resuming the session where it stopped."
    claude_launch_once "${CLAUDE_AGAIN[@]}" "$CLAUDE_LIMIT_RESUME"
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
claude_here() {
  local status
  declare -F term_skip >/dev/null && term_skip begin "$@"
  claude "$@"
  status=$?
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
    # names this login's interop socket, and the new tab has its own.
    for name in $(compgen -e); do
      case "$name" in
        WSL_INTEROP|WT_SESSION|WT_PROFILE_ID|SHLVL|PWD|OLDPWD|_) continue ;;
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
      printf 'rc=$?; for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 $! 2>/dev/null || break; sleep 0.2; done\n'
      printf 'echo "=== $(date -Iseconds) exit $rc" >> %q\n' "$log"
      printf 'echo $rc > %q\n' "$dir/status"
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

  info "   claude is running in a new tab ($title)."
  info "   Ctrl-C here ends that session, the same as /exit there."
  # Left here, Ctrl-C would end sclaude and leave the session running with
  # nobody to carry on after it: no next step, no friction review. It ends the
  # session instead, and sclaude goes on as after an /exit. A sclaude tab
  # closed by its cross does the same, rather than leave claude orphaned.
  trap 'pkill -TERM -P "$pid" 2>/dev/null || true' INT TERM HUP
  while kill -0 "$pid" 2>/dev/null; do
    sleep 1
  done
  trap - INT TERM HUP

  local status=1
  [[ -s "$dir/status" ]] && status="$(cat "$dir/status")"
  rm -rf "$dir"
  return "$status"
}
