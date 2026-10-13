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
  claude_launch_once "$@"
  status=$?
  # Closed by the session watcher because the usage limit had reset, not
  # ended: opened again where it stopped. The arguments are the first
  # launch's up to and including `-n <name>`, which every caller passes
  # right before its prompt; the prompt gives way to a word to carry on —
  # the opening one was answered long ago. A `--session-id` becomes
  # `--resume`, since the conversation now exists.
  local limit_file="${TMPDIR:-/tmp}/sclaude-limit-$session"
  while [[ -n "$session" && -s "$limit_file" ]]; do
    rm -f "$limit_file"
    local -a again=()
    local arg named=""
    for arg in "$@"; do
      if [[ -n "$named" ]]; then again+=("$arg"); break; fi
      case "$arg" in
        --session-id) again+=(--resume) ;;
        -n) again+=(-n); named=1 ;;
        *) again+=("$arg") ;;
      esac
    done
    echo ""
    info "   The usage limit has reset — resuming the session where it stopped."
    claude_launch_once "${again[@]}" "$CLAUDE_LIMIT_RESUME"
    status=$?
  done
  return "$status"
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

# The emoji a tab title starts with, by the kind of session its name
# (session_label) says it is, so the tabs tell the stages apart at a glance.
# The name itself is left as it is: only the tab shows the emoji.
pane_icon() {
  case "$1" in
    *friction*)             printf '🧱' ;;
    *-fix-*)                printf '🔧' ;;
    [0-9]*-plan[/\(]*)      printf '📝' ;;
    [0-9]*-code[/\(]*)      printf '💻' ;;
    [0-9]*-pr[/\(]*)        printf '📤' ;;
    [0-9]*-review[/\(]*)    printf '🔍' ;;
    [0-9]*-epilogue[/\(]*)  printf '🏁' ;;
    [0-9]*-retro[/\(]*)     printf '🔁' ;;
  esac
}

# One launch of claude, in a tab or in place. claude_launch around it adds the
# return after a usage limit.
claude_launch_once() {
  if ! pane_available; then
    claude_here "$@"
    return
  fi

  local dir; dir="$(mktemp -d "${TMPDIR:-/tmp}/sclaude-pane.XXXXXX")" || { claude_here "$@"; return; }
  local script="$dir/run" title="claude" i name
  for ((i = 1; i < $#; i++)); do
    [[ "${!i}" == "-n" ]] && { name=$((i + 1)); title="${!name}"; break; }
  done
  local icon; icon="$(pane_icon "$title")"
  [[ -n "$icon" ]] && title="$icon $title"

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
    printf 'claude'
    printf ' %q' "$@"
    printf '\n'
    printf 'echo $? > %q\n' "$dir/status"
    echo 'exit 0'
  } > "$script"

  # From a Windows directory: wt.exe and wsl.exe complain about a cwd inside
  # the distribution, which they see as a UNC path.
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
