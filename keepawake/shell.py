# keepawake's Telegram bot — running commands for the bot: the PATH a systemd
# unit lacks, and the wrapper every command goes through.
#
# Part of the bot that keepawake/telegramd.py runs.

import logging
import os
import signal
import subprocess

from keepawake.i18n import t


log = logging.getLogger("keepawake")


# --- commands ---------------------------------------------------------------

# ~/.local/bin, where keepawake, chrome-debug and sclaude live, is not in the
# daemon's PATH: systemd gives a bare system PATH rather than the one an
# interactive shell assembles from ~/.profile. From the terminal the commands
# were found, from under the service they were not, and every button answered
# "not found".
LOCAL_BIN = os.path.expanduser("~/.local/bin")


def nvm_bin():
    # npm and node live in the directory of nvm's active version, which is not
    # in the service's PATH: an interactive shell assembles it from
    # ~/.nvm/nvm.sh. Without this `sclaude dev` died with "setsid: failed to
    # execute npm".
    #
    # We read the version from ~/.nvm/alias/default rather than hardcoding it:
    # otherwise updating Node would quietly break the button until the next edit
    # of the code.
    base = os.path.expanduser("~/.nvm/versions/node")
    alias = os.path.expanduser("~/.nvm/alias/default")
    try:
        want = open(alias).read().strip()
    except OSError:
        want = ""
    try:
        candidates = os.listdir(base)
    except OSError:
        return ""
    if not candidates:
        return ""

    def version_key(name):
        # By numbers rather than by letters: sorted() puts "v9.11.2" above
        # "v24.20.0", and the fallback branch would silently pick an ancient
        # Node. That branch is not hypothetical — here alias/default equals
        # "lts/*", which matches no directory by prefix.
        parts = []
        for chunk in name.lstrip("v").split("."):
            parts.append(int(chunk) if chunk.isdigit() else 0)
        return parts

    # We resolve "lts/*" and other aliases through ~/.nvm/alias/, otherwise
    # they would never match a directory name.
    if want.startswith("lts/"):
        try:
            want = open(os.path.expanduser("~/.nvm/alias/" + want)).read().strip()
        except OSError:
            want = ""

    for name in sorted(candidates, key=version_key, reverse=True):
        if want and (name == want or name.lstrip("v").startswith(want.lstrip("v"))):
            return os.path.join(base, name, "bin")
    return os.path.join(base, max(candidates, key=version_key), "bin")


def run(cmd, timeout=25):
    # The bot's commands are short and free of dialogue; anything longer has no
    # place here.
    env = dict(os.environ)
    parts = [LOCAL_BIN]
    nvm = nvm_bin()
    if nvm:
        parts.append(nvm)
    env["PATH"] = ":".join(parts) + ":" + env.get("PATH", "")
    # In a session of its own, and the whole group killed on a timeout:
    # subprocess.run kills only the shell it started, and whatever the shell
    # was running (`cd … && sclaude status`) lived on as an orphan, still
    # counted as "another sclaude" by every later run.
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env,
                                start_new_session=True)
    except Exception as exc:
        return t("cmd.error", err=exc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return t("cmd.timeout", sec=timeout)
    except Exception as exc:
        return t("cmd.error", err=exc)
    text = (stdout or "") + (stderr or "")
    return text.strip() or t("cmd.empty")


def uptime_of(pid):
    try:
        with open("/proc/%d/stat" % pid) as fh:
            # Field 22 (starttime) is in ticks since the system booted. The
            # command's name in brackets may contain spaces, so we cut at ")".
            fields = fh.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])
        hz = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as fh:
            up = float(fh.read().split()[0])
        return max(0, int(up - ticks / hz))
    except Exception:
        return 0
