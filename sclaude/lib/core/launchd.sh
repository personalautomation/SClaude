#!/usr/bin/env bash
#
# sclaude's launchd agents on macOS: what systemd's user units are on Linux.
#
# The templates are launchd/<label>.plist in the checkout. install.sh writes
# each into ~/Library/LaunchAgents with this machine's values put in for
# @HOME@, @PATH@ and @LOGS@ and loads it, and removes the file of one it
# keeps off (launchd loads every file there at login); units_refresh
# (instruments.sh) writes them again when an update changed a template.
# Written, not linked, for the same reason as the units: a link would carry
# the placeholders.
#
# sclaude's own agents are sclaude.*: the watcher and the proxy, on every Mac.
# keepawake.* are the extras' (./install.sh --extras): the minute's count of
# holders, the holding side and the Telegram bot.

launchd_dir() { printf '%s\n' "$HOME/Library/LaunchAgents"; }
launchd_logs() { printf '%s\n' "$HOME/Library/Logs/sclaude"; }
launchd_domain() { printf 'gui/%s\n' "$(id -u)"; }

# The labels of the agents the checkout has templates for, one a line:
# sclaude's own (the default, `core`), the extras' (`extras`) or both (`all`).
launchd_labels() {
  local kind="${1:-core}" src label
  for src in "$INSTRUMENTS"/launchd/*.plist; do
    [[ -f "$src" ]] || continue
    label="${src##*/}"
    label="${label%.plist}"
    case "$kind:$label" in
      core:sclaude.*|extras:keepawake*|all:*) echo "$label" ;;
    esac
  done
}

# A value made safe for a sed replacement between | delimiters.
launchd_escape() { printf '%s' "$1" | sed 's/[&|\\]/\\&/g'; }

# The template filled in, on stdout: `launchd_render <label> <PATH>`.
launchd_render() {
  local src="$INSTRUMENTS/launchd/$1.plist"
  [[ -f "$src" ]] || return 1
  sed -e "s|@HOME@|$(launchd_escape "$HOME")|g" \
      -e "s|@LOGS@|$(launchd_escape "$(launchd_logs)")|g" \
      -e "s|@PATH@|$(launchd_escape "$2")|g" \
      -e "s|@REPO@|$(launchd_escape "$INSTRUMENTS")|g" "$src"
}

# The PATH an installed agent runs with, or nothing.
launchd_path_of() {
  plutil -extract EnvironmentVariables.PATH raw -o - "$(launchd_dir)/$1.plist" 2>/dev/null
}

# 0 when launchd has the agent loaded.
launchd_loaded() {
  launchctl print "$(launchd_domain)/$1" >/dev/null 2>&1
}

# When launchd_load last loaded an agent. launchd reads a plist only when it
# loads it, so a file newer than this is not what the job runs on — written
# by install.sh or by units_refresh since — and launchd_current says so. A
# login loads the files too, without this mark: the next install.sh then
# reloads each agent once more than it had to.
launchd_mark() {
  printf '%s/sclaude/launchd/%s.loaded\n' "${XDG_STATE_HOME:-$HOME/.local/state}" "$1"
}

# 0 when the agent is loaded from its file as the file is now.
launchd_current() {
  launchd_loaded "$1" && [[ ! "$(launchd_dir)/$1.plist" -nt "$(launchd_mark "$1")" ]]
}

# Unloads an agent and waits for its job to be gone; 1 when it is not.
#
# bootout returns while the job's process may still be exiting — the holder
# lets go of its assertion and the lid on SIGTERM first, the bot finishes its
# long poll — and until it is gone launchd still prints the job, and refuses
# the label to a bootstrap ("Bootstrap failed: 5: Input/output error"). A
# reload by install.sh left keepawake.hold unloaded that way, the Mac unheld
# with a one-line note. So the job is waited for, ten seconds past the 20
# launchd gives a process to exit before it kills it (ExitTimeOut): a job
# still there then is one launchd did not take down.
LAUNCHD_WAIT_TRIES="${LAUNCHD_WAIT_TRIES:-60}"
launchd_unload() {
  local try
  launchd_loaded "$1" || return 0
  launchctl bootout "$(launchd_domain)/$1" >/dev/null 2>&1
  for (( try = 0; try < LAUNCHD_WAIT_TRIES; try++ )); do
    launchd_loaded "$1" || return 0
    sleep 0.5
  done
  return 1
}

# Loads an agent from its file, unloading the one loaded first, and tries the
# load a few times before it counts as failed. The mark takes the file's own
# time, read before the load: a file written while it loads is then newer
# than the mark, and reloaded once more rather than taken for what runs.
launchd_load() {
  local label="$1" try plist mark
  plist="$(launchd_dir)/$label.plist"
  mark="$(launchd_mark "$label")"
  mkdir -p "${mark%/*}" && touch -r "$plist" "$mark.next" 2>/dev/null
  launchd_unload "$label" || true
  for (( try = 0; try < 3; try++ )); do
    if launchctl bootstrap "$(launchd_domain)" "$plist" 2>/dev/null; then
      mv -f "$mark.next" "$mark" 2>/dev/null
      return 0
    fi
    sleep 1
  done
  rm -f "$mark.next"
  return 1
}

# Writes an agent's file with the given PATH; 0 when it changed, 1 when it
# was the same already, 2 when it could not be written.
launchd_write() {
  local label="$1" path="$2" plist want
  plist="$(launchd_dir)/$label.plist"
  want="$(launchd_render "$label" "$path")" || return 2
  [[ -f "$plist" && "$(cat "$plist" 2>/dev/null)" == "$want" ]] && return 1
  mkdir -p "$(launchd_dir)" "$(launchd_logs)" || return 2
  rm -f "$plist"
  printf '%s\n' "$want" > "$plist" || return 2
  return 0
}

# Brings the installed agents up to the checkout's templates, each with the
# PATH it was installed with. Only agents already installed are touched. One
# that is not loaded is loaded, as launchd would load it at the next login
# (install.sh leaves no file for an agent it keeps off); a loaded one is
# named, for the person to reload: unloading the proxy from here would stop
# the sclaude it started. Its file is written all the same, for the next
# login to load, and install.sh finds it newer than its last load
# (launchd_current) and reloads it.
launchd_refresh() {
  local label path rc stale=""
  [[ -d "$(launchd_dir)" ]] || return 0
  while read -r label; do
    [[ -n "$label" && -f "$(launchd_dir)/$label.plist" ]] || continue
    path="$(launchd_path_of "$label")"
    [[ -n "$path" ]] || path="$PATH"
    launchd_write "$label" "$path"
    rc=$?
    (( rc == 0 )) || continue
    if launchd_loaded "$label"; then
      stale+=" $label"
    else
      launchd_load "$label" || true
    fi
  done < <(launchd_labels all)
  [[ -n "$stale" ]] && info "  updated, and running on the old file until reloaded:${stale} (./install.sh reloads them)"
  return 0
}
