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
# The extras have two platforms: WSL, where keepawake holds Windows awake from
# the Windows side and wsl-update keeps the distribution current, and plain
# Linux, where keepawake-linux holds this machine awake itself.
#
#   ./install.sh               sclaude only (and the extras, if an earlier
#                              install put them in)
#   ./install.sh --extras      sclaude and the machine tools
#   ./install.sh --polkit      the extras, and keepawake's polkit rule
#                              without asking
#   ./install.sh --no-polkit   do not add it, and do not ask
#
set -euo pipefail

POLKIT_CHOICE=ask
EXTRAS=0
for arg in "$@"; do
  case "$arg" in
    --extras)    EXTRAS=1 ;;
    --polkit)    POLKIT_CHOICE=yes; EXTRAS=1 ;;  # the rule is keepawake's
    --no-polkit) POLKIT_CHOICE=no ;;
    # The comment at the top, however long it grows.
    -h|--help)   awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' \
                   "${BASH_SOURCE[0]}"; exit 0 ;;
    *)           echo "install.sh: unknown option $arg (see --help)" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
UNITS="$HOME/.config/systemd/user"
SKILLS="$HOME/.claude/skills"
CLAUDE="$HOME/.claude"

mkdir -p "$BIN" "$UNITS" "$SKILLS" "$CLAUDE"

# A machine an earlier install gave the extras keeps them on a plain re-run:
# leaving its keepawake and bot units unwritten would let them drift from the
# repository without a word.
if [[ $EXTRAS -eq 0 && -L "$BIN/keepawake" ]]; then
  EXTRAS=1
  echo "extras: kept — an earlier install put them in"
fi

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
[[ "$(python3 "$REPO/keepawake/state.py" platform 2>/dev/null)" == wsl ]] && WSL=1
echo "platform: $([[ $WSL -eq 1 ]] && echo WSL || echo Linux)"

# systemd's user manager runs sclaude's watcher, proxy and gate, and every
# extra. `command -v systemctl` is not enough: WSL ships the binary without
# systemd running (no systemd=true in /etc/wsl.conf), and then the first
# `systemctl --user` fails and set -e stops the install half-way without a
# word. Asked once here, and what to do said plainly.
SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 \
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

unit sclaude-watch.service
unit sclaude-watch.timer
unit sclaude-proxy.socket
unit sclaude-proxy.service
unit sclaude-gate.socket
unit sclaude-gate.service
echo "units: $UNITS/sclaude-watch{.service,.timer}, sclaude-proxy{.socket,.service}, sclaude-gate{.socket,.service}"

if [[ $EXTRAS -eq 1 ]]; then
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

# settings.json points at ~/.claude/statusline.py — the symlink is what makes
# that setting work after the machine is reinstalled.
ln -sfn "$REPO/statusline.py" "$CLAUDE/statusline.py"
echo "symlinked: $CLAUDE/statusline.py"

# This repository's hooks live in githooks/; there is no `npm install` here to
# point at them, as a product's might, so we do it here.
git -C "$REPO" config core.hooksPath githooks
echo "hooks: $REPO/githooks"

# --- keepawake: the Windows side and the secrets -----------------------------

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

    # We enable the daemon only with the token filled in: a service falling into a
    # restart loop straight after installation is a poor first impression and
    # rubbish in the journal.
    if [[ -s "$HOME/.config/keepawake/env" ]] \
       && grep -q '^KEEPAWAKE_BOT_TOKEN=.\+' "$HOME/.config/keepawake/env" 2>/dev/null; then
      systemctl --user enable --now keepawake-telegram.service
      echo "enabled: keepawake-telegram.service"
    else
      echo "note: keepawake-telegram is not enabled — there is no token in ~/.config/keepawake/env" >&2
    fi
  fi

  systemctl --user list-timers sclaude-watch.timer $([[ $EXTRAS -eq 1 ]] && echo keepawake.timer) --no-pager || true
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
  echo "      see the \"keepawake\" section in the README" >&2
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
  [[ $WSL -eq 0 ]] || return 0
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

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "note: $BIN is not on PATH — add it in your shell rc" >&2 ;;
esac

if [[ $EXTRAS -eq 0 ]]; then
  echo "extras: not installed — keepawake, its Telegram bot, code-server, wsl-update"
  echo "        come with ./install.sh --extras"
fi

echo ""
echo "next: run 'sclaude doctor' — it checks what is still missing and names the fix"
# Without systemd the install is not whole, and a script running it should
# know: the error above said what to do.
[[ $SYSTEMD -eq 1 ]] || exit 1
