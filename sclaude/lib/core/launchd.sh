# sclaude's launchd agents on macOS: what systemd's user units are on Linux.
#
# The templates are launchd/<label>.plist in the checkout. install.sh writes
# each into ~/Library/LaunchAgents with this machine's values put in for
# @HOME@, @PATH@ and @LOGS@ and loads it; units_refresh (instruments.sh)
# writes them again when an update changed a template. Written, not linked,
# for the same reason as the units: a link would carry the placeholders.
#
# sclaude's own agents are sclaude.*: the watcher and the proxy, on every Mac.
# keepawake.* are the extras' (./install.sh --extras): the minute's count of
# holders and the holding side. The phone's gate comes with the Telegram bot.

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

# Loads an agent from its file, unloading the one loaded first: launchd reads
# a plist only when it is loaded.
launchd_load() {
  local label="$1" plist
  plist="$(launchd_dir)/$label.plist"
  launchd_loaded "$label" && launchctl bootout "$(launchd_domain)/$label" >/dev/null 2>&1
  launchctl bootstrap "$(launchd_domain)" "$plist" 2>/dev/null
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
# that is not loaded is loaded; a loaded one is named, for the person to
# reload: unloading the proxy from here would stop the sclaude it started.
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
