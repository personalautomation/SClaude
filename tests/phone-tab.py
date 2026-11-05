#!/usr/bin/env python3
#
# A press on the phone runs sclaude as the laptop's terminal would:
#
#   * start_sclaude (keepawake/sessions.py) opens a Windows Terminal tab that
#     runs a script: sclaude with its arguments and SCLAUDE_FROM_PHONE=1, then
#     a shell; the command is in the script, not on wt.exe's command line,
#     which splits at `;`, and the tab's title has none;
#   * with no Windows Terminal, or a tab that never takes its script, it
#     starts sclaude in the background, as before;
#   * under SCLAUDE_FROM_PHONE the arrow-key lists (person_at_terminal in ui.sh)
#     and the machine's update question (update_can_ask in developer.sh) give
#     way, as they do with no terminal, and so does a question meant for the
#     terminal alone (`ask` with no channel): nobody is at the tab.
#
# Run it with: python3 tests/phone-tab.py
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    print(("PASS  " if got == want else "FAIL  ") + name)
    if got != want:
        failures.append(name)
        print("  want: %r\n  got:  %r" % (want, got))


from keepawake import sessions, shell  # noqa: E402

tmp = tempfile.mkdtemp()
os.environ["TMPDIR"] = tmp
tempfile.tempdir = None
launched, ran = [], []


taken = {}


class Popen:
    """wt.exe: the tab takes its script (reads it, removes it) unless told not
    to open."""
    opens = True

    def __init__(self, argv, **kw):
        launched.append((argv, kw))
        if Popen.opens:
            with open(argv[-1]) as fh:
                taken[argv[-1]] = fh.read()
            os.unlink(argv[-1])


saved = (sessions.windows_terminal, sessions.subprocess.Popen, shell.run)
try:
    sessions.windows_terminal = lambda: ("wt.exe", "Distro")
    sessions.subprocess.Popen = Popen
    shell.run = lambda cmd, timeout=25: ran.append(cmd)
    sessions._start("/repo dir", ["new", "--", "a; b"])
    argv, kw = launched[0]
    check("tab: wt.exe opens a tab in the distribution",
          argv[:4] + argv[6:11], ["wt.exe", "-w", "0", "new-tab", "wsl.exe", "-d",
                                  "Distro", "--", "bash"])
    check("tab: the title has no `;` for wt.exe to split at", ";" in argv[5], False)
    check("tab: from a Windows directory", kw.get("cwd"), "/mnt/c")
    script = taken[argv[-1]]
    check("tab: the script runs sclaude marked as from the phone",
          "SCLAUDE_FROM_PHONE=1 sclaude new -- 'a; b'\n" in script, True)
    check("tab: the script goes into the repository first",
          "cd '/repo dir' || exit\n" in script, True)
    check("tab: a shell stays when sclaude ends", script.endswith("exec bash -i\n"), True)
    check("tab: nothing started in the background", ran, [])
    written = os.path.join(tmp, "taken.sh")
    with open(written, "w") as fh:
        fh.write(script)

    # A tab that never takes its script: taken back, and the background start.
    launched.clear()
    Popen.opens = False
    sessions.TAB_WAIT = 0.5
    sessions._start("/repo", ["y"])
    check("tab not opened: its script taken back", os.path.exists(launched[0][0][-1]), False)
    check("tab not opened: started in the background",
          ran, ["cd /repo && setsid sclaude y < /dev/null > /dev/null 2>&1 &"])
    ran.clear()

    launched.clear()
    sessions.windows_terminal = lambda: None
    sessions._start("/repo", ["x"])
    check("no terminal: no tab", launched, [])
    check("no terminal: started in the background",
          ran, ["cd /repo && setsid sclaude x < /dev/null > /dev/null 2>&1 &"])
finally:
    sessions.windows_terminal, sessions.subprocess.Popen, shell.run = saved

# Checked once Popen is real again: sessions' subprocess is the module itself.
check("tab: the script parses",
      subprocess.run(["bash", "-n", written], capture_output=True).returncode, 0)
os.unlink(written)


# Under `script`, so that /dev/tty opens: the one case the mark decides.
def in_tty(body, env):
    cmd = 'bash -c \'source "%s/core/ui.sh" 2>/dev/null; source "%s/core/picker.sh" 2>/dev/null;' \
          ' source "%s/core/developer.sh" 2>/dev/null; %s; echo "rc=$?"\'' % (LIB, LIB, LIB, body)
    out = subprocess.run(["script", "-qec", cmd, "/dev/null"], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, env=dict(os.environ, **env)).stdout
    return out.strip().splitlines()[-1].strip() if out.strip() else "?"


check("person_at_terminal: a terminal and the person at it",
      in_tty("person_at_terminal", {"SCLAUDE_FROM_PHONE": ""}), "rc=0")
check("person_at_terminal: a tab started from the phone",
      in_tty("person_at_terminal", {"SCLAUDE_FROM_PHONE": "1"}), "rc=1")
check("pick_list: gives way (2) in a tab started from the phone",
      in_tty("pick_list t a b", {"SCLAUDE_FROM_PHONE": "1"}), "rc=2")
check("update_can_ask: not in a tab started from the phone",
      in_tty("update_can_ask", {"SCLAUDE_FROM_PHONE": "1"}), "rc=1")
check("ask, terminal alone: no answer in a tab started from the phone",
      in_tty('source "%s/core/ui.sh" 2>/dev/null; ASK_DIR="" ask "q? " a yn' % LIB,
             {"SCLAUDE_FROM_PHONE": "1"}), "rc=1")
def typed(body, env, keys):
    cmd = 'bash -c \'source "%s/core/ui.sh" 2>/dev/null; %s\'' % (LIB, body)
    return subprocess.run(["script", "-qec", cmd, "/dev/null"], capture_output=True, text=True,
                          input=keys, env=dict(os.environ, **env)).stdout


SECRET = ('source "%s/core/environment.sh" 2>/dev/null; warn() { :; }; envs() { return 1; };'
          ' v=$(environment_value /x prod KEY); echo "got=$v"' % LIB)
check("environment_value: the secret typed at the terminal",
      "got=s3cret" in typed(SECRET, {"SCLAUDE_FROM_PHONE": ""}, "s3cret\n"), True)
check("environment_value: nothing read in a tab started from the phone",
      "got=s3cret" in typed(SECRET, {"SCLAUDE_FROM_PHONE": "1"}, "s3cret\n"), False)
check("environment_value: no secret asked in a tab started from the phone",
      in_tty('source "%s/core/ui.sh" 2>/dev/null; source "%s/core/environment.sh" 2>/dev/null;'
             ' warn() { :; }; envs() { return 1; }; environment_value /x prod KEY' % (LIB, LIB),
             {"SCLAUDE_FROM_PHONE": "1"}), "rc=1")
check("update_can_ask: at a terminal",
      in_tty("update_can_ask", {"SCLAUDE_FROM_PHONE": ""}), "rc=0")

# The bot never takes a phone-started asker for the person at the terminal,
# however fresh its tab (a new pty's atime is now).
import time  # noqa: E402
from keepawake import asks  # noqa: E402
for flag, want in (("1", False), ("", True)):
    with subprocess.Popen(["script", "-qec", "sleep 5", "/dev/null"], stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL, env=dict(os.environ, SCLAUDE_FROM_PHONE=flag)) as p:
        kid = 0
        for _ in range(50):
            out = subprocess.run(["pgrep", "-P", str(p.pid)], capture_output=True, text=True).stdout.split()
            if out:
                kid = int(out[0])
                break
            time.sleep(0.1)
        check("at_terminal: the tab's process found (%s)" % (flag or "laptop"), kid != 0, True)
        check("at_terminal: a fresh tab %s" % ("from the phone is not the person" if flag
                                               else "at the laptop is"),
              asks.at_terminal({"pid": kid}), want)
        p.kill()

if failures:
    print("FAILED: %d" % len(failures))
    sys.exit(1)
print("all good")
