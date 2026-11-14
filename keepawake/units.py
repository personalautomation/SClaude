# keepawake's Telegram bot — the machine's services it starts, stops and asks
# about: systemd's user units on Linux, launchd's agents on macOS.
#
# The bot names a service by its systemd unit everywhere. On a Mac the same
# name stands for the agent install.sh writes from launchd/<label>.plist
# (sclaude/lib/core/launchd.sh), and this module says what to run for it. One
# place, so that a button does the same on both systems and a label renamed in
# launchd/ is renamed here alone.
#
# Part of the bot that keepawake/telegramd.py runs; bin/sclaude-notify asks
# it whether the bot is up.

import os
import shlex
import subprocess
import sys


# A unit and its agent. bin/keepawake (unit_state, service_up) names the same
# pairs for `keepawake status` and the count of holders.
LABELS = {
    "keepawake-telegram.service": "keepawake.telegram",
    "code-server.service": "keepawake.code-server",
    "sclaude-gate.socket": "sclaude.gate",
}

# Where launchd's agents write their output: launchd_logs in launchd.sh.
LOGS = "~/Library/Logs/sclaude"
LOG_FILES = {"keepawake.telegram": "telegram.log"}


def on_macos():
    """macOS, or what SCLAUDE_OS says for the tests (linux, macos)."""
    said = os.environ.get("SCLAUDE_OS")
    if said:
        return said == "macos"
    return sys.platform == "darwin"


def label(unit):
    """The launchd label of a unit; a name that is no unit of ours is taken
    for a label already (KEEPAWAKE_UNIT may name one)."""
    return LABELS.get(unit, unit)


def target(unit):
    """launchctl's name for the agent: in the domain of the user's login
    session, where install.sh loads it."""
    return "gui/%d/%s" % (os.getuid(), label(unit))


def plist(unit):
    return os.path.expanduser("~/Library/LaunchAgents/%s.plist" % label(unit))


def command(verb, unit):
    """The shell command that does `verb` (start, stop, restart) to a unit.

    On macOS: kickstart starts an agent (-k kills a running one first, which
    is systemctl's restart), and one written but not loaded is loaded first,
    as systemctl finds a unit file by itself. kill TERM stops it: the agents
    started on demand are not kept alive after a clean exit."""
    if not on_macos():
        return "systemctl --user %s %s" % (verb, shlex.quote(unit))
    tgt = shlex.quote(target(unit))
    if verb == "stop":
        return "launchctl kill TERM %s" % tgt
    load = "{ launchctl print %s >/dev/null 2>&1 || launchctl bootstrap gui/%d %s; }" % (
        tgt, os.getuid(), shlex.quote(plist(unit)))
    return "%s && launchctl kickstart %s%s" % (load, "-k " if verb == "restart" else "", tgt)


def active(unit, timeout=5):
    """Whether the unit runs. A socket counts once it is loaded: launchd
    listens for it from then on, as systemd does for an active socket."""
    try:
        if not on_macos():
            return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=timeout).returncode == 0
        out = subprocess.run(["launchctl", "print", target(unit)], capture_output=True,
                             text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    if out.returncode != 0:
        return False
    if unit.endswith(".socket"):
        return True
    return any(line.strip() == "state = running" for line in out.stdout.splitlines())


def restart_later(unit, delay):
    """Restart the unit `delay` seconds from now, from a process of its own.

    For the bot restarting itself: the restart kills it mid-handling, so the
    answer goes first and the restart after, from a new session that the
    kill of the bot's process group does not reach."""
    return subprocess.Popen(["bash", "-c", "sleep %s; %s" % (delay, command("restart", unit))],
                            start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log_command(unit):
    """What to type on the laptop to read the unit's log."""
    if not on_macos():
        return "journalctl --user -u %s" % unit
    name = LOG_FILES.get(label(unit), label(unit) + ".log")
    return "tail -n 50 %s/%s" % (LOGS, name)
