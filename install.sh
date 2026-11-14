#!/usr/bin/env bash
#
# Lays out symlinks to this repository's scripts and skills and sets up the
# systemd user units. Idempotent: run it as many times as you like.
#
# By default only sclaude: the orchestrator, its watcher, proxy and gate, the
# pr skill, the status line. The machine tools that grew up next to it —
# keepawake and its Telegram bot, code-server, wsl-update, the Windows side —
# come with --extras. Somebody who came for sclaude does not expect them.
#
# The extras have three platforms: WSL, where keepawake holds Windows awake
# from the Windows side and wsl-update keeps the distribution current; plain
# Linux, where keepawake-linux holds this machine awake itself; and macOS,
# where keepawake-macos does, with a power assertion.
#
# On macOS sclaude runs with Homebrew's bash 5 and GNU tools, which this
# offers to install, and launchd's agents in place of the systemd units. Of
# the extras a Mac takes all but wsl-update and the Windows side: keepawake,
# its Telegram bot and code-server.
#
#   ./install.sh               sclaude only (and the extras, if an earlier
#                              install put them in)
#   ./install.sh --extras      sclaude and the machine tools
#   ./install.sh --lid         the extras, and what lets keepawake hold a
#                              closed lid, without asking: a polkit rule on
#                              Linux, a sudoers rule for pmset on macOS
#   ./install.sh --no-lid      do not add it, and do not ask
#   --polkit, --no-polkit      the same as --lid and --no-lid
#
# Three questions of this machine are asked once, and kept in this checkout's
# git config (sclaude.update, sclaude.contribute, sclaude.leaks): whether
# sclaude updates itself from its public main, whether what a session fixes in
# sclaude is sent there, and what happens when such a fix may name your
# product. A re-run keeps the answers; these set them without asking:
#
#   --update=notify|auto|off     notify says what is new, `sclaude update`
#                                takes it; auto takes it at every start
#   --contribute=ask|send|off    ask shows the change and waits for a yes;
#                                off keeps sessions from changing sclaude
#   --leaks=ask|auto|off         a change that may name your product: asked
#                                about (ask, and off alike) or sent unasked
#
# With no terminal to ask in, they stay unset, which sclaude reads as ask.
#
set -euo pipefail

POLKIT_CHOICE=ask
EXTRAS=0
SET_UPDATE=""
SET_CONTRIBUTE=""
SET_LEAKS=""
for arg in "$@"; do
  case "$arg" in
    --extras)    EXTRAS=1 ;;
    --lid|--polkit)       POLKIT_CHOICE=yes; EXTRAS=1 ;;  # the rule is keepawake's
    --no-lid|--no-polkit) POLKIT_CHOICE=no ;;
    --update=*)
      SET_UPDATE="${arg#*=}"
      [[ " auto notify off " == *" $SET_UPDATE "* ]] \
        || { echo "install.sh: --update takes notify, auto or off" >&2; exit 2; } ;;
    --contribute=*)
      SET_CONTRIBUTE="${arg#*=}"
      [[ " send ask off " == *" $SET_CONTRIBUTE "* ]] \
        || { echo "install.sh: --contribute takes ask, send or off" >&2; exit 2; } ;;
    --leaks=*)
      SET_LEAKS="${arg#*=}"
      [[ " ask auto off " == *" $SET_LEAKS "* ]] \
        || { echo "install.sh: --leaks takes ask, auto or off" >&2; exit 2; } ;;
    # The comment at the top, however long it grows.
    -h|--help)   awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' \
                   "${BASH_SOURCE[0]}"; exit 0 ;;
    *)           echo "install.sh: unknown option $arg (see --help)" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- macOS: Homebrew's bash and the GNU tools ---------------------------------
#
# sclaude is written for bash 4 and the GNU userland; a Mac has bash 3.2 and
# BSD's tools, and sclaude/lib/core/macos.sh puts Homebrew's builds first for
# every entry point. What is missing of them is offered here, with the
# command shown first; then the installer goes on under bash 5 itself, so up
# to here it is written for bash 3.2.
#
# SCLAUDE_OS (linux or macos) overrides what the system says, for the tests:
# tests/install.py runs the Linux installer on a Mac too.
MACOS=0
case "${SCLAUDE_OS:-}" in
  macos) MACOS=1 ;;
  linux) ;;
  *) [[ "${OSTYPE:-}" == darwin* ]] && MACOS=1 ;;
esac
if [[ $MACOS -eq 1 ]]; then
  MACOS_FUNCTIONS_ONLY=1
  # shellcheck source=sclaude/lib/core/macos.sh
  source "$REPO/sclaude/lib/core/macos.sh"
  unset MACOS_FUNCTIONS_ONLY
  if ! macos_brew >/dev/null; then
    echo "error: sclaude on macOS needs Homebrew — https://brew.sh — then re-run ./install.sh" >&2
    exit 1
  fi
  MACOS_NEED="$(macos_missing)"
  if [[ -n "$MACOS_NEED" ]]; then
    echo "macOS: sclaude runs with Homebrew's bash 5 and GNU tools; missing: $MACOS_NEED"
    echo "  $(macos_brew)/bin/brew install $MACOS_NEED"
    if [[ ! -t 0 ]]; then
      echo "  No terminal to ask in: run that, then ./install.sh again." >&2
      exit 1
    fi
    # No default, as everywhere in sclaude: asked again until it is a yes or
    # a no. End of input is a no.
    while :; do
      read -rp "  Install them now? [y/n] " answer || { answer=n; echo; }
      case "$answer" in
        y|Y|yes|YES|Yes) break ;;
        n|N|no|NO|No) echo "  Not installed: sclaude cannot run without them." >&2; exit 1 ;;
        *) echo "  Please answer y or n." ;;
      esac
    done
    # shellcheck disable=SC2086  # the formulae, one word each
    "$(macos_brew)/bin/brew" install $MACOS_NEED \
      || { echo "error: brew install failed; nothing else was done" >&2; exit 1; }
  fi
  # Under bash 5 from here on, with the GNU tools first: this re-executes the
  # installer with its own arguments when it runs under the system's bash.
  source "$REPO/sclaude/lib/core/macos.sh"
fi
BIN="$HOME/.local/bin"
UNITS="$HOME/.config/systemd/user"
SKILLS="$HOME/.claude/skills"
CLAUDE="$HOME/.claude"

mkdir -p "$BIN" "$SKILLS" "$CLAUDE"
[[ $MACOS -eq 1 ]] || mkdir -p "$UNITS"

# A machine an earlier install gave the extras keeps them on a plain re-run:
# leaving its keepawake and bot units unwritten would let them drift from the
# repository without a word.
if [[ $EXTRAS -eq 0 && -L "$BIN/keepawake" ]]; then
  EXTRAS=1
  echo "extras: kept — an earlier install put them in"
fi

# Whether ~/.config/keepawake/env has the bot's token: the bot's unit or agent
# is turned on only then. A service falling into a restart loop straight after
# installation is a poor first impression and rubbish in the log.
bot_token_set() {
  [[ -s "$HOME/.config/keepawake/env" ]] \
    && grep -q '^KEEPAWAKE_BOT_TOKEN=.\+' "$HOME/.config/keepawake/env" 2>/dev/null
}

# A systemd unit, written into $UNITS with this checkout's path put in for
# @REPO@: the checkout may live under any name, and a unit cannot find it any
# other way. Written, not linked — a link would carry the placeholder — so
# re-run this after a unit changes. The old link, if any, goes first: writing
# through it would rewrite the file in the repository.
unit() {
  rm -f "$UNITS/$1"
  sed "s|@REPO@|$REPO|g" "$REPO/systemd/$1" > "$UNITS/$1"
}

# Asked of keepawake/state.py rather than tested again here: that is what
# decides where keepawake writes its state, and two copies of the test would
# one day set up the units for one platform while the state went to the other.
# KEEPAWAKE_PLATFORM (wsl|linux) overrides it there — for the tests.
WSL=0
[[ $MACOS -eq 0 && "$(python3 "$REPO/keepawake/state.py" platform 2>/dev/null)" == wsl ]] && WSL=1
if [[ $MACOS -eq 1 ]]; then
  echo "platform: macOS"
else
  echo "platform: $([[ $WSL -eq 1 ]] && echo WSL || echo Linux)"
fi

# systemd's user manager runs sclaude's watcher, proxy and gate, and every
# extra. `command -v systemctl` is not enough: WSL ships the binary without
# systemd running (no systemd=true in /etc/wsl.conf), and then the first
# `systemctl --user` fails and set -e stops the install half-way without a
# word. Asked once here, and what to do said plainly.
SYSTEMD=0
if [[ $MACOS -eq 1 ]]; then
  : # launchd's agents, below
elif command -v systemctl >/dev/null 2>&1 \
   && systemctl --user show-environment >/dev/null 2>&1; then
  SYSTEMD=1
else
  echo "" >&2
  echo "error: systemd's user manager does not answer (systemctl --user)." >&2
  echo "       sclaude needs it for its watcher, proxy and gate." >&2
  if [[ $WSL -eq 1 ]]; then
    echo "       In WSL, turn systemd on: put these two lines in /etc/wsl.conf" >&2
    echo "         [boot]" >&2
    echo "         systemd=true" >&2
    echo "       then run 'wsl --shutdown' from Windows, open WSL again and re-run" >&2
    echo "       ./install.sh." >&2
  else
    echo "       Use a distribution that boots with systemd, log in to a session" >&2
    echo "       of your own (not su or sudo), and re-run ./install.sh." >&2
  fi
  echo "       The links below are laid out anyway; no unit is enabled." >&2
  echo "" >&2
fi

for tool in sclaude sclaude-notify sclaude-watch sclaude-proxy chrome-debug; do
  ln -sfn "$REPO/bin/$tool" "$BIN/$tool"
done
echo "symlinked: sclaude, sclaude-notify, sclaude-watch, sclaude-proxy, chrome-debug in $BIN"

if [[ $MACOS -eq 0 ]]; then
  unit sclaude-watch.service
  unit sclaude-watch.timer
  unit sclaude-proxy.socket
  unit sclaude-proxy.service
  unit sclaude-gate.socket
  unit sclaude-gate.service
  echo "units: $UNITS/sclaude-watch{.service,.timer}, sclaude-proxy{.socket,.service}, sclaude-gate{.socket,.service}"
fi

if [[ $EXTRAS -eq 1 && $MACOS -eq 1 ]]; then
  # The holding side, the minute's count, the bot and code-server are launchd
  # agents, below. No code-server-proxy: the forward is for a Windows browser
  # outside the tailnet, and a Mac's browser is in it.
  for tool in keepawake keepawake-macos code-server-start; do
    ln -sfn "$REPO/bin/$tool" "$BIN/$tool"
  done
  echo "symlinked (extras): keepawake, keepawake-macos, code-server-start in $BIN"
elif [[ $EXTRAS -eq 1 ]]; then
  for tool in keepawake code-server-start code-server-proxy; do
    ln -sfn "$REPO/bin/$tool" "$BIN/$tool"
  done
  echo "symlinked (extras): keepawake, code-server-* in $BIN"

  if [[ $WSL -eq 1 ]]; then
    ln -sfn "$REPO/bin/wsl-update"        "$BIN/wsl-update"
    ln -sfn "$REPO/bin/keepawake-windows" "$BIN/keepawake-windows"
    unit wsl-update.service
    unit wsl-update.timer
    unit keepawake-windows.service
    echo "symlinked (WSL): wsl-update, keepawake-windows and their units"
  else
    ln -sfn "$REPO/bin/keepawake-linux"             "$BIN/keepawake-linux"
    unit keepawake-linux.service
    echo "symlinked (Linux): keepawake-linux and its unit"
  fi

  unit code-server.service
  unit code-server-local.socket
  unit code-server-local.service
  unit keepawake.service
  unit keepawake.timer
  unit keepawake-telegram.service
  echo "units (extras): $UNITS/keepawake{.service,.timer,-telegram.service}, code-server{.service,-local.socket,-local.service}"
fi

ln -sfn "$REPO/skills/pr" "$SKILLS/pr"
echo "symlinked: $SKILLS/pr"
ln -sfn "$REPO/skills/sreview" "$SKILLS/sreview"
echo "symlinked: $SKILLS/sreview"
ln -sfn "$REPO/skills/isleep" "$SKILLS/isleep"
echo "symlinked: $SKILLS/isleep"
ln -sfn "$REPO/skills/sdemo" "$SKILLS/sdemo"
echo "symlinked: $SKILLS/sdemo"
# /isleep's night outlives a session through hooks every session runs; they do
# nothing while no night is on. A settings file that does not read leaves
# them out with a word, and the rest of the install goes on.
if python3 "$REPO/skills/isleep/night.py" install "$CLAUDE/settings.json"; then
  echo "hooks: /isleep in $CLAUDE/settings.json"
fi

# settings.json points at ~/.claude/statusline.py — the symlink is what makes
# that setting work after the machine is reinstalled.
ln -sfn "$REPO/statusline.py" "$CLAUDE/statusline.py"
echo "symlinked: $CLAUDE/statusline.py"

# This repository's hooks live in githooks/; there is no `npm install` here to
# point at them, as a product's might, so we do it here.
git -C "$REPO" config core.hooksPath githooks
echo "hooks: $REPO/githooks"

# --- what sclaude may do with the network: asked once --------------------------

# The words and what they mean are sclaude's own (developer.sh), so the
# question here and the one a start asks say the same.
INSTRUMENTS="$REPO"
# shellcheck source=sclaude/lib/core/developer.sh
source "$REPO/sclaude/lib/core/developer.sh"

# Asks one setting, unless a flag set it or an earlier install did. No
# default, as everywhere in sclaude: a key that names no line is passed over.
# End of input, or no terminal, leaves it unset, which sclaude reads as ask.
#
#   setting_offer <key> <flag value> <explain fn> <words, the recommended first>
setting_offer() {
  local key="$1" flag="$2" explain="$3" words="$4" now answer
  if [[ -n "$flag" ]]; then
    sclaude_setting_set "$key" "$flag"
    echo "sclaude.$key: $flag"
    return 0
  fi
  now="$(sclaude_setting "$key")"
  if [[ -n "$now" ]]; then
    echo "sclaude.$key: $now (kept; ./install.sh --$key=… changes it)"
    return 0
  fi
  echo ""
  "$explain"
  if [[ ! -t 0 ]]; then
    echo "  No terminal to ask in: left unset, which means ask. Later: ./install.sh --$key=<${words// /|}>" >&2
    return 0
  fi
  # A key for each line of the explanation, from this installer's stdin.
  setting_pick answer "$words" "" /dev/stdin 2>&1 \
    || { echo "  Left unset, which means ask."; return 0; }
  sclaude_setting_set "$key" "$answer"
  echo "sclaude.$key: $answer"
}

setting_offer update "$SET_UPDATE" update_modes_explain "notify auto off"
setting_offer contribute "$SET_CONTRIBUTE" contribute_modes_explain "ask send off"
setting_offer leaks "$SET_LEAKS" leaks_modes_explain "ask auto off"

# --- keepawake: the Windows side and the secrets -----------------------------

# The secrets are the Telegram bot's.
if [[ $EXTRAS -eq 1 ]]; then
  # The secrets directory. We do not touch the env file itself: an installer must
  # never overwrite somebody's token.
  mkdir -p "$HOME/.config/keepawake"
  chmod 700 "$HOME/.config/keepawake"
  if [[ ! -f "$HOME/.config/keepawake/env" ]]; then
    echo "note: fill in ~/.config/keepawake/env (a sample is at $REPO/keepawake/env.example)" >&2
  else
    # We fix the permissions rather than only complaining about them: at start-up
    # the daemon refuses to work with a file the group can read, and getting a
    # refusal instead of a fix is a poor substitute for one chmod. We do not touch
    # the contents.
    chmod 600 "$HOME/.config/keepawake/env"
  fi

  # The PowerShell script is copied to the Windows drive rather than symlinked:
  # over \\wsl$ it would be unreachable exactly when it is needed — with WSL
  # stopped.
  WINUSER=""
  [[ $WSL -eq 1 ]] && WINUSER="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r')"
  if [[ $WSL -eq 0 ]]; then
    : # nothing on a Windows drive to install
  elif [[ -n "$WINUSER" && -d "/mnt/c/Users/$WINUSER" ]]; then
    WINDIR="/mnt/c/Users/$WINUSER/.keepawake"
    mkdir -p "$WINDIR"
    # With a BOM rather than a cp: PowerShell 5.1 reads UTF-8 without a BOM as
    # ANSI, so any non-ASCII byte decodes to something else, string lengths drift
    # apart, and the script dies on "Missing closing }" where everything is written
    # correctly. The script is ASCII today, but the BOM costs nothing and removes
    # the whole class of failure.
    printf '\xEF\xBB\xBF' > "$WINDIR/KeepAwake.ps1"
    cat "$REPO/windows/KeepAwake.ps1" >> "$WINDIR/KeepAwake.ps1"
    echo "copied: $WINDIR/KeepAwake.ps1 (UTF-8 with a BOM)"

    # systemd inside WSL starts the Windows side rather than the Windows startup
    # folder: while the distribution is not running there is nobody to hold for,
    # and a process hanging there is not wanted. We remove the old startup shortcut
    # if it is left over from an earlier version.
    STARTUP="/mnt/c/Users/$WINUSER/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    if [[ -f "$STARTUP/KeepAwake.vbs" ]]; then
      rm -f "$STARTUP/KeepAwake.vbs"
      echo "removed: $STARTUP/KeepAwake.vbs (systemd starts it now)"
    fi
  else
    echo "note: no Windows profile found — keepawake's Windows side is not installed" >&2
  fi
fi

if [[ $SYSTEMD -eq 1 ]]; then
  systemctl --user daemon-reload
  # Harmless with nothing to watch: the sweep exits at once when
  # ~/.claude/sclaude/watch is empty or absent, which is the usual state.
  systemctl --user enable --now sclaude-watch.timer
  echo "enabled: sclaude-watch.timer (asks GitHub what QA has done)"

  # :3000 may still be held by a dev server started before features had ports
  # of their own. Enabling the socket then fails, and failing the whole install
  # over it would be out of proportion: say what holds it and go on.
  if systemctl --user enable --now sclaude-proxy.socket 2>/dev/null; then
    echo "enabled: sclaude-proxy.socket (<feature>.localhost:3000 for every feature)"
  else
    echo "note: sclaude-proxy.socket did not start — something holds :3000:" >&2
    ss -ltnp 2>/dev/null | grep ':3000 ' >&2 || true
    echo "      stop it, then: systemctl --user enable --now sclaude-proxy.socket" >&2
  fi

  # The phone's gate: a loopback-only socket, harmless until a funnel points
  # at it — which the bot's phone button does, once, by a person's choice. The
  # service goes first: a gate from before the socket bound :3001 itself, and
  # stopped is only stopped — the socket brings it back on demand.
  systemctl --user stop sclaude-gate.service 2>/dev/null || true
  if systemctl --user enable --now sclaude-gate.socket 2>/dev/null; then
    echo "enabled: sclaude-gate.socket (127.0.0.1:3001, the phone's entry behind tailscale funnel)"
  else
    echo "note: sclaude-gate.socket did not start — something holds 127.0.0.1:3001" >&2
  fi

  if [[ $EXTRAS -eq 1 ]]; then
    systemctl --user enable --now keepawake.timer
    echo "enabled: keepawake.timer"
    if [[ $WSL -eq 1 ]]; then
      systemctl --user enable --now wsl-update.timer
      echo "enabled: wsl-update.timer"
      systemctl --user enable --now keepawake-windows.service
      echo "enabled: keepawake-windows.service (the hold on the Windows side)"
    else
      systemctl --user enable --now keepawake-linux.service
      echo "enabled: keepawake-linux.service (the hold on this machine)"
    fi
    # code-server deliberately does not come up at boot: it goes out by itself
    # after 59 minutes of idling (idle-timeout-seconds in config.yaml), and
    # autostart would bring back to life what was just deliberately shut down. It
    # is brought up by a button in the bot.
    if [[ -f "$HOME/.config/code-server/config.yaml" ]]; then
      bind="$(sed -n 's/^bind-addr:[[:space:]]*//p' "$HOME/.config/code-server/config.yaml" | head -1)"
      echo "on demand: code-server (${bind:-127.0.0.1:8080, its default}) — by a button in the bot"
      # The local port for the Windows browser: Windows is not in the tailnet,
      # because Tailscale runs inside WSL and the tailnet address is unreachable
      # from it. On contact the socket will bring the server up too — Requires in
      # code-server-local.service.
      #
      # Only for a server bound elsewhere. 127.0.0.1:8080 is code-server's own
      # default: a server left on it (or on every address) needs no forward to
      # be reached from localhost, and the socket would take its port — the
      # server failing with EADDRINUSE every 10 s, and the proxy forwarding
      # into its own socket.
      case "${bind:-127.0.0.1:8080}" in
        127.0.0.1:8080|localhost:8080|0.0.0.0:8080|\[::\]:8080|\[::1\]:8080)
          systemctl --user disable --now code-server-local.socket 2>/dev/null || true
          echo "note: code-server listens on localhost:8080 itself — the local forward is not enabled" >&2
          echo "      (put bind-addr on the tailnet address to reach it from a phone)" >&2
          ;;
        *)
          systemctl --user enable --now code-server-local.socket
          echo "enabled: code-server-local.socket (localhost:8080, brings the server up on demand)"
          ;;
      esac
    else
      echo "note: no ~/.config/code-server/config.yaml — code-server is not configured" >&2
    fi

    # We enable the daemon only with the token filled in (bot_token_set).
    if bot_token_set; then
      systemctl --user enable --now keepawake-telegram.service
      echo "enabled: keepawake-telegram.service"
    else
      echo "note: keepawake-telegram is not enabled — there is no token in ~/.config/keepawake/env" >&2
    fi
  fi

  systemctl --user list-timers sclaude-watch.timer $([[ $EXTRAS -eq 1 ]] && echo keepawake.timer) --no-pager || true
fi

# macOS: the watcher and the proxy as launchd agents in the user's login
# session (sclaude/lib/core/launchd.sh). They run with this PATH — the GNU
# tools first, ~/.local/bin on it — as the units run with systemd's. Loaded
# again on every run, so that a changed template takes effect here and now.
if [[ $MACOS -eq 1 ]]; then
  INSTRUMENTS="$REPO"
  # shellcheck source=sclaude/lib/core/launchd.sh
  source "$REPO/sclaude/lib/core/launchd.sh"
  agent_path="$PATH"
  [[ ":$agent_path:" == *":$BIN:"* ]] || agent_path="$agent_path:$BIN"
  # The proxy binds :3000 itself here, and launchd binds the gate's :3001 as
  # it loads sclaude.gate: something else on either — a dev server started
  # before features had ports of their own, a gate run by hand — would leave
  # the agent restarting every ten seconds, or not loaded at all. Said, and the
  # rest goes on. A port the agent itself holds is no obstacle: it is reloaded.
  port_holder() {
    launchd_loaded "$1" && return 0
    { lsof -nP -iTCP:"$2" -sTCP:LISTEN -Fc 2>/dev/null || true; } | sed -n 's/^c//p' | head -1
  }
  declare -A held=([sclaude.proxy]="$(port_holder sclaude.proxy 3000)"
                   [sclaude.gate]="$(port_holder sclaude.gate 3001)")
  declare -A port_of=([sclaude.proxy]=3000 [sclaude.gate]=3001)
  while read -r label; do
    [[ -n "$label" ]] || continue
    # The bot only with its token (bot_token_set). Without one an agent
    # written earlier is left as it is: taking it out is the person's call.
    if [[ "$label" == keepawake.telegram ]] && ! bot_token_set; then
      echo "note: keepawake.telegram is not set up — there is no token in ~/.config/keepawake/env" >&2
      continue
    fi
    launchd_write "$label" "$agent_path" || true
    if [[ -n "${held[$label]:-}" ]]; then
      echo "note: ${held[$label]} holds :${port_of[$label]} — $label is written but not loaded;" >&2
      echo "      stop it, then: launchctl bootstrap $(launchd_domain) $(launchd_dir)/$label.plist" >&2
      continue
    fi
    if launchd_load "$label"; then
      echo "loaded: $label ($(launchd_dir)/$label.plist, log in $(launchd_logs))"
    else
      echo "note: launchd did not load $label; see $(launchd_dir)/$label.plist" >&2
    fi
  done < <(launchd_labels; [[ $EXTRAS -eq 1 ]] && launchd_labels extras)
  # The phone's gate goes out through `tailscale funnel`, and the bot reads
  # the tailnet's addresses with the same command. The Mac app does not put
  # it on PATH by itself.
  if [[ $EXTRAS -eq 1 ]] && ! command -v tailscale >/dev/null 2>&1; then
    echo "note: no tailscale command on PATH — the bot's phone links and the phone's gate need it;" >&2
    echo "      the Tailscale app offers to install it in its settings (or: brew install tailscale)" >&2
  fi
  # code-server is loaded and not started, as on Linux: a button in the bot
  # brings it up, and its idle timeout takes it down.
  if [[ $EXTRAS -eq 1 ]]; then
    if [[ -f "$HOME/.config/code-server/config.yaml" ]]; then
      bind="$(sed -n 's/^bind-addr:[[:space:]]*//p' "$HOME/.config/code-server/config.yaml" | head -1)"
      echo "on demand: code-server (${bind:-127.0.0.1:8080, its default}) — by a button in the bot"
    else
      echo "note: no ~/.config/code-server/config.yaml — code-server is not configured" >&2
    fi
    if [[ ! -x "$HOME/.local/bin/code-server" ]] && ! command -v code-server >/dev/null 2>&1; then
      echo "note: code-server is not installed — brew install code-server" >&2
    fi
  fi
  if [[ $EXTRAS -eq 1 ]] && ! launchctl print system/com.openssh.sshd >/dev/null 2>&1; then
    echo "note: Remote Login is off — no SSH session from a phone; turn it on in" >&2
    echo "      System Settings → General → Sharing" >&2
  fi
fi

# systemctl --user lives only while there is a user session. Closing the last
# local terminal will kill the daemon — and that is precisely the scenario all
# this is done for: working from a phone with the laptop closed.
if command -v loginctl >/dev/null 2>&1; then
  if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
    echo "note: run 'sudo loginctl enable-linger $USER' — otherwise the daemon" >&2
    echo "      will stop when you close the last terminal" >&2
  fi
fi

# Asked of the package manager only where there is one we know; elsewhere of
# the binary itself.
if command -v dpkg >/dev/null 2>&1; then
  dpkg -l openssh-server 2>/dev/null | grep -q '^ii' || NO_SSHD=1
else
  command -v sshd >/dev/null 2>&1 || [[ -x /usr/sbin/sshd ]] || NO_SSHD=1
fi
if [[ $EXTRAS -eq 1 && -n "${NO_SSHD:-}" ]]; then
  echo "note: openssh-server is not installed — mobile SSH sessions are impossible;" >&2
  echo "      see the \"keepawake\" section in docs/tools.md" >&2
fi

# --- keepawake's polkit rule: optional, plain Linux only ---------------------
#
# logind lets a process outside a login session — which keepawake-linux, a
# user service under linger, is — block idle only. Blocking sleep and the lid
# switch needs a polkit rule, and writing one needs sudo, so it is offered
# rather than done: the person decides, knowing what it is for and how to undo
# it. The undo command is shown before the question, not after the yes.
#
# Where it does not apply nothing is said at all: under WSL the Windows side
# holds the machine, and without logind or polkit there is nothing to grant.
# Without a terminal (or with --no-polkit) it is a note; --polkit adds it
# without asking.
POLKIT_RULE="${KEEPAWAKE_POLKIT_RULE:-/etc/polkit-1/rules.d/49-keepawake.rules}"
# Where this installer notes that it wrote the rule. Fedora and Arch keep
# rules.d unreadable to a normal user, so the rule itself cannot be seen from
# here; the note is what `sclaude doctor` and the next run read there instead.
POLKIT_MARK="$HOME/.config/sclaude/polkit-rule"
# The settings folder was ~/.config/instruments/ before the repository's name
# changed; an older install's is moved once rather than lost.
[[ -d "$HOME/.config/instruments" && ! -e "$HOME/.config/sclaude" ]] \
  && mv "$HOME/.config/instruments" "$HOME/.config/sclaude"
POLKIT_OFF="sudo rm $POLKIT_RULE && rm -f $POLKIT_MARK && systemctl --user restart keepawake-linux.service"

polkit_present() {
  [[ -f "$POLKIT_RULE" ]] && return 0
  [[ -r "$(dirname "$POLKIT_RULE")" ]] && return 1
  [[ -f "$POLKIT_MARK" ]]
}

polkit_rule_text() {
  printf '%s\n' \
    '// Written by instruments/install.sh: lets keepawake-linux hold off sleep and' \
    '// the lid switch for this user while there is work going on.' \
    "// To remove: $POLKIT_OFF" \
    'polkit.addRule(function(action, subject) {' \
    '  if ((action.id == "org.freedesktop.login1.inhibit-block-sleep" ||' \
    '       action.id == "org.freedesktop.login1.inhibit-handle-lid-switch") &&' \
    "      subject.user == \"$USER\") {" \
    '    return polkit.Result.YES;' \
    '  }' \
    '});'
}

polkit_add() {
  if polkit_rule_text | sudo tee "$POLKIT_RULE" >/dev/null; then
    mkdir -p "$(dirname "$POLKIT_MARK")"
    echo "$POLKIT_RULE" > "$POLKIT_MARK"
    systemctl --user restart keepawake-linux.service 2>/dev/null || true
    echo "added: $POLKIT_RULE — a closed lid no longer sleeps while there is work"
    echo "       to turn it off: $POLKIT_OFF"
  else
    echo "note: the polkit rule was not written (sudo refused or failed);" >&2
    echo "      keepawake-linux keeps holding idle only" >&2
  fi
}

polkit_offer() {
  [[ $EXTRAS -eq 1 ]] || return 0
  [[ $WSL -eq 0 && $MACOS -eq 0 ]] || return 0
  command -v loginctl >/dev/null 2>&1 || return 0
  [[ -d "$(dirname "$(dirname "$POLKIT_RULE")")" ]] || return 0

  if polkit_present; then
    echo "keepawake: the polkit rule is in place — a closed lid does not sleep while there is work"
    echo "           to turn it off: $POLKIT_OFF"
    return 0
  fi
  [[ "$POLKIT_CHOICE" == no ]] && return 0
  if [[ "$POLKIT_CHOICE" == yes ]]; then
    polkit_add
    return 0
  fi

  local laptop=""
  if compgen -G "/proc/acpi/button/lid/*" >/dev/null \
     || compgen -G "/sys/class/power_supply/BAT*" >/dev/null; then
    laptop=1
  fi

  echo ""
  echo "keepawake: an optional polkit rule (plain Linux only)"
  echo "  Without it keepawake-linux can only stop the idle timer from suspending"
  echo "  this machine. Closing the lid or an explicit suspend still puts it to"
  echo "  sleep, and whatever runs from your phone — an SSH session, a Claude"
  echo "  step — dies with it."
  echo "  With it, the lid is ignored only while there is work going on (claude,"
  echo "  SSH, code-server); once the work ends the machine sleeps as usual."
  if [[ -n "$laptop" ]]; then
    echo "  This looks like a laptop: worth it if you close it and keep working"
    echo "  from a phone. Not needed if it always stays open."
  else
    echo "  This does not look like a laptop, so the lid part will rarely matter;"
    echo "  it still guards against an explicit suspend under remote work."
  fi
  echo "  It lets processes of user '$USER' hold off sleep, and grants nothing else."
  echo "  Writing it needs sudo. To turn it off later:"
  echo "    $POLKIT_OFF"

  if [[ ! -t 0 ]]; then
    echo "  No terminal to ask in: run ./install.sh --polkit to add it." >&2
    return 0
  fi
  # No default, as everywhere in sclaude: asked again until it is a yes or a
  # no. End of input is a no — there is nobody left to answer.
  local answer=""
  while :; do
    read -rp "  Add it now? [y/n] " answer || { answer=n; echo; }
    case "${answer,,}" in
      y|yes) polkit_add; break ;;
      n|no)  echo "  Not added. Later: ./install.sh --polkit"; break ;;
      *)     echo "  Please answer y or n." ;;
    esac
  done
}

polkit_offer

# --- keepawake's sudoers rule: optional, macOS only ---------------------------
#
# The power assertion keepawake-macos takes stops idle sleep, but nothing a
# user's process can take keeps a MacBook up with its lid closed: only root
# can, with `pmset -a disablesleep 1`. A sudoers rule lets this user run
# exactly that and its `0` without a password, and nothing else; the holder
# turns it on while it holds and off when it lets go. Offered as the polkit
# rule is, with the undo command shown before the question: it is a rule in
# the system's sudo, and the person decides.
#
# The undo turns disablesleep off too: with the rule gone a holder could no
# longer turn it off itself, and a Mac left with it on never sleeps.
SUDOERS_RULE="${KEEPAWAKE_SUDOERS_RULE:-/etc/sudoers.d/keepawake}"
LID_OFF="sudo rm $SUDOERS_RULE && sudo pmset -a disablesleep 0"

lid_rule_text() {
  printf '%s\n' \
    "# Written by sclaude's install.sh: lets keepawake-macos keep a closed lid from" \
    '# sleeping the Mac while there is work going on, and nothing else.' \
    "# To remove: $LID_OFF" \
    "$USER ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 1, /usr/bin/pmset -a disablesleep 0"
}

lid_add() {
  local tmp
  tmp="$(mktemp)"
  lid_rule_text > "$tmp"
  # visudo checks it before sudo reads it: a broken file in sudoers.d stops
  # sudo working at all.
  if visudo -cf "$tmp" >/dev/null \
     && sudo install -m 0440 -o root -g wheel "$tmp" "$SUDOERS_RULE"; then
    echo "added: $SUDOERS_RULE — a closed lid no longer sleeps while there is work"
    echo "       to turn it off: $LID_OFF"
  else
    echo "note: the sudoers rule was not written (sudo refused, or visudo did not pass it);" >&2
    echo "      keepawake-macos keeps holding idle sleep only" >&2
  fi
  rm -f "$tmp"
}

lid_offer_macos() {
  [[ $EXTRAS -eq 1 && $MACOS -eq 1 ]] || return 0
  if [[ -f "$SUDOERS_RULE" ]]; then
    echo "keepawake: the sudoers rule is in place — a closed lid does not sleep while there is work"
    echo "           to turn it off: $LID_OFF"
    return 0
  fi
  [[ "$POLKIT_CHOICE" == no ]] && return 0
  if [[ "$POLKIT_CHOICE" == yes ]]; then
    lid_add
    return 0
  fi

  echo ""
  echo "keepawake: an optional sudoers rule for the lid (macOS)"
  echo "  Without it keepawake-macos stops only idle sleep. Closing the lid still"
  echo "  puts the Mac to sleep, and whatever runs from your phone — an SSH"
  echo "  session, a Claude step — stops with it."
  echo "  With it, keepawake turns pmset's disablesleep on while there is work"
  echo "  going on (claude, SSH, a tailnet connection) and off once it ends."
  echo "  The Mac then stays awake with the lid shut, in a bag too, until the"
  echo "  work ends: worth it if you close it and keep working from a phone."
  echo "  It lets user '$USER' run 'pmset -a disablesleep 1' and '… 0' without a"
  echo "  password, and nothing else. Writing it needs sudo. To turn it off later:"
  echo "    $LID_OFF"

  if [[ ! -t 0 ]]; then
    echo "  No terminal to ask in: run ./install.sh --lid to add it." >&2
    return 0
  fi
  # No default, as everywhere in sclaude: asked again until it is a yes or a
  # no. End of input is a no — there is nobody left to answer.
  local answer=""
  while :; do
    read -rp "  Add it now? [y/n] " answer || { answer=n; echo; }
    case "${answer,,}" in
      y|yes) lid_add; break ;;
      n|no)  echo "  Not added. Later: ./install.sh --lid"; break ;;
      *)     echo "  Please answer y or n." ;;
    esac
  done
}

lid_offer_macos

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "note: $BIN is not on PATH — add it in your shell rc" >&2 ;;
esac

if [[ $EXTRAS -eq 0 && $MACOS -eq 1 ]]; then
  echo "extras: not installed — keepawake and its Telegram bot come with ./install.sh --extras"
elif [[ $EXTRAS -eq 0 ]]; then
  echo "extras: not installed — keepawake, its Telegram bot, code-server, wsl-update"
  echo "        come with ./install.sh --extras"
fi

echo ""
echo "next: run 'sclaude doctor' — it checks what is still missing and names the fix"
# Without systemd the install is not whole, and a script running it should
# know: the error above said what to do. macOS has launchd instead.
[[ $SYSTEMD -eq 1 || $MACOS -eq 1 ]] || exit 1
