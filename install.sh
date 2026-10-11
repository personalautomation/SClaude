#!/usr/bin/env bash
#
# Lays out symlinks to this repository's scripts and skills and sets up the
# systemd user units. Idempotent: run it as many times as you like.
#
# Two platforms: WSL, where keepawake holds Windows awake from the Windows side
# and wsl-update keeps the distribution current, and plain Linux, where
# keepawake-linux holds this machine awake itself. Everything else is the same
# on both.
#
#   ./install.sh               ask about the optional parts where they apply
#   ./install.sh --polkit      add keepawake's polkit rule without asking
#   ./install.sh --no-polkit   do not add it, and do not ask
#
set -euo pipefail

POLKIT_CHOICE=ask
for arg in "$@"; do
  case "$arg" in
    --polkit)    POLKIT_CHOICE=yes ;;
    --no-polkit) POLKIT_CHOICE=no ;;
    -h|--help)   sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           echo "install.sh: unknown option $arg (see --help)" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HOME/.local/bin"
UNITS="$HOME/.config/systemd/user"
SKILLS="$HOME/.claude/skills"
CLAUDE="$HOME/.claude"

mkdir -p "$BIN" "$UNITS" "$SKILLS" "$CLAUDE"

# Asked of keepawake/state.py rather than tested again here: that is what
# decides where keepawake writes its state, and two copies of the test would
# one day set up the units for one platform while the state went to the other.
# KEEPAWAKE_PLATFORM (wsl|linux) overrides it there — for the tests.
WSL=0
[[ "$(python3 "$REPO/keepawake/state.py" platform 2>/dev/null)" == wsl ]] && WSL=1
echo "platform: $([[ $WSL -eq 1 ]] && echo WSL || echo Linux)"

for tool in sclaude sclaude-notify sclaude-watch sclaude-proxy keepawake chrome-debug \
            code-server-start code-server-proxy; do
  ln -sfn "$REPO/bin/$tool" "$BIN/$tool"
done
echo "symlinked: sclaude, sclaude-notify, sclaude-watch, sclaude-proxy, keepawake, chrome-debug, code-server-* in $BIN"

if [[ $WSL -eq 1 ]]; then
  ln -sfn "$REPO/bin/wsl-update"        "$BIN/wsl-update"
  ln -sfn "$REPO/bin/keepawake-windows" "$BIN/keepawake-windows"
  ln -sfn "$REPO/systemd/wsl-update.service"        "$UNITS/wsl-update.service"
  ln -sfn "$REPO/systemd/wsl-update.timer"          "$UNITS/wsl-update.timer"
  ln -sfn "$REPO/systemd/keepawake-windows.service" "$UNITS/keepawake-windows.service"
  echo "symlinked (WSL): wsl-update, keepawake-windows and their units"
else
  ln -sfn "$REPO/bin/keepawake-linux"             "$BIN/keepawake-linux"
  ln -sfn "$REPO/systemd/keepawake-linux.service" "$UNITS/keepawake-linux.service"
  echo "symlinked (Linux): keepawake-linux and its unit"
fi

ln -sfn "$REPO/systemd/code-server.service"        "$UNITS/code-server.service"
ln -sfn "$REPO/systemd/code-server-local.socket"   "$UNITS/code-server-local.socket"
ln -sfn "$REPO/systemd/code-server-local.service"  "$UNITS/code-server-local.service"
ln -sfn "$REPO/systemd/keepawake.service"          "$UNITS/keepawake.service"
ln -sfn "$REPO/systemd/keepawake.timer"            "$UNITS/keepawake.timer"
ln -sfn "$REPO/systemd/keepawake-telegram.service" "$UNITS/keepawake-telegram.service"
ln -sfn "$REPO/systemd/sclaude-watch.service"      "$UNITS/sclaude-watch.service"
ln -sfn "$REPO/systemd/sclaude-watch.timer"        "$UNITS/sclaude-watch.timer"
ln -sfn "$REPO/systemd/sclaude-proxy.socket"       "$UNITS/sclaude-proxy.socket"
ln -sfn "$REPO/systemd/sclaude-proxy.service"      "$UNITS/sclaude-proxy.service"
echo "symlinked: $UNITS/keepawake{.service,.timer,-telegram.service}, code-server.service, sclaude-watch{.service,.timer}, sclaude-proxy{.socket,.service}"

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

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload
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

  # code-server deliberately does not come up at boot: it goes out by itself
  # after 59 minutes of idling (idle-timeout-seconds in config.yaml), and
  # autostart would bring back to life what was just deliberately shut down. It
  # is brought up by a button in the bot.
  if [[ -f "$HOME/.config/code-server/config.yaml" ]]; then
    echo "on demand: code-server ($(awk '/bind-addr/{print $2}' "$HOME/.config/code-server/config.yaml")) — by a button in the bot"
    # The local port for the Windows browser: Windows is not in the tailnet,
    # because Tailscale runs inside WSL and the tailnet address is unreachable
    # from it. On contact the socket will bring the server up too — Requires in
    # code-server-local.service.
    systemctl --user enable --now code-server-local.socket
    echo "enabled: code-server-local.socket (localhost:8080, brings the server up on demand)"
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

  systemctl --user list-timers keepawake.timer sclaude-watch.timer --no-pager || true
else
  echo "systemctl not found — skipped timer setup" >&2
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
if [[ -n "${NO_SSHD:-}" ]]; then
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
POLKIT_MARK="$HOME/.config/instruments/polkit-rule"
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
  local answer=""
  read -rp "  Add it now? [y/N] " answer || answer=""
  case "$answer" in
    y|Y|yes|YES|Yes) polkit_add ;;
    *) echo "  Not added. Later: ./install.sh --polkit" ;;
  esac
}

polkit_offer

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "note: $BIN is not on PATH — add it in your shell rc" >&2 ;;
esac

echo ""
echo "next: run 'sclaude doctor' — it checks what is still missing and names the fix"
