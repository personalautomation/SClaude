#!/usr/bin/env python3
# procinfo.sh and procinfo.py answer what sclaude asks about other processes
# and their ports, from /proc and ss on Linux and from ps and lsof on macOS.
#
# Each answer is checked against a real process this bench starts — a sleep
# with a mark in its environment, in a directory of its own, and a listening
# socket — on whichever system it runs, so the half for the other system is
# the other machine's run. And no code outside the module reads /proc or runs
# ss itself again: such a line works on Linux alone, and says nothing on a Mac.
#
# Run it with: python3 tests/procinfo.py
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, os.path.join(LIB, "core"))
import procinfo  # noqa: E402

failures = []


def check(name, got, want):
    print(("PASS  " if got == want else "FAIL  ") + name)
    if got != want:
        failures.append(name)
        print("  want: %r\n  got:  %r" % (want, got))


def sh(body):
    script = 'set -uo pipefail\nsource "%s/core/procinfo.sh"\n%s\n' % (LIB, body)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60).stdout.strip()


tmp = os.path.realpath(tempfile.mkdtemp())
server = socket.socket()
proc = None
try:
    work = os.path.join(tmp, "a dir")
    os.makedirs(work)
    # The sleep on PATH: macOS hides the environment of its own /bin/sleep.
    sleep = os.path.realpath(shutil.which("sleep"))
    proc = subprocess.Popen([sleep, "60"], cwd=work,
                            env=dict(os.environ, SCLAUDE_PROCINFO_MARK="tree one"))
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    time.sleep(0.3)
    pid = proc.pid

    check("proc_name", sh('proc_name %d' % pid), os.path.basename(sleep))
    check("proc_cmdline", sh('proc_cmdline %d' % pid).split()[-1], "60")
    check("proc_exe", sh('proc_exe %d' % pid), sleep)
    check("proc_parent", sh('proc_parent %d' % pid), str(os.getpid()))
    check("proc_cwd: a directory with a space", sh('proc_cwd %d' % pid), work)
    check("proc_cwds: listed", "%d %s" % (pid, work) in sh('proc_cwds').splitlines(), True)
    check("proc_env_has: the whole value",
          sh('proc_env_has %d "SCLAUDE_PROCINFO_MARK=tree one" && echo y || echo n' % pid), "y")
    check("proc_env_has: not a prefix of it",
          sh('proc_env_has %d "SCLAUDE_PROCINFO_MARK=tree" && echo y || echo n' % pid), "n")
    check("proc_env_anywhere: found",
          sh('proc_env_anywhere "SCLAUDE_PROCINFO_MARK=tree one" && echo y || echo n'), "y")
    # The search itself names the value: it must not find itself.
    check("proc_env_anywhere: not found in its own search",
          sh('proc_env_anywhere "SCLAUDE_PROCINFO_MARK=tree two" && echo y || echo n'), "n")
    start = sh('proc_start %d' % pid)
    check("proc_start: a word", bool(start) and " " not in start, True)
    check("proc_start: the same for the same process", sh('proc_start %d' % pid), start)
    check("proc_start: nothing for no process", sh('proc_start 999999'), "")
    check("ports_listening", str(port) in sh('ports_listening').split(), True)
    check("port_pid", sh('port_pid %d' % port), str(os.getpid()))
    check("port_addresses: loopback", sh('port_addresses %d' % port), "127.0.0.1:%d" % port)
    check("port_addresses: nobody", sh('port_addresses 1'), "")
    check("load_one: a number", bool(re.match(r"^[0-9.]+$", sh('load_one'))), True)
    check("ports_pids: the port and its listener",
          "%d %d" % (port, os.getpid()) in sh('ports_pids').splitlines(), True)

    # What a server puts out grows when it answers: this bench answers a
    # client of its own socket, by write(2). macOS keeps no such counter, and
    # gives nothing.
    client = socket.create_connection(("127.0.0.1", port))
    conn, _ = server.accept()
    before = sh('proc_output_bytes %d' % os.getpid())
    os.write(conn.fileno(), b"x" * 5000)
    client.recv(10000)
    time.sleep(0.2)
    after = sh('proc_output_bytes %d' % os.getpid())
    if sys.platform == "darwin":
        check("proc_output_bytes: nothing on macOS", (before, after), ("", ""))
    else:
        check("proc_output_bytes: numbers", (before.isdigit(), after.isdigit()), (True, True))
        check("proc_output_bytes: an answer counts",
              after.isdigit() and before.isdigit() and int(after) - int(before) >= 5000, True)
    check("proc_output_bytes: nothing for no process", sh('proc_output_bytes 999999'), "")
    conn.close()
    client.close()

    # The keyboard at the machine itself: the Mac's HID system answers; Linux
    # gives no such answer to a process outside the session.
    idle = sh('input_idle || echo none')
    if sys.platform == "darwin":
        check("input_idle: seconds on macOS", idle.isdigit(), True)
    else:
        check("input_idle: no answer on Linux", idle, "none")

    check("procinfo.py: listening_pids", os.getpid() in procinfo.listening_pids().get(port, set()), True)
    check("procinfo.py: working_dirs", (pid, work) in procinfo.working_dirs(), True)
    check("procinfo.py: environ_of", "SCLAUDE_PROCINFO_MARK=tree one" in procinfo.environ_of(pid), True)
finally:
    server.close()
    if proc:
        proc.kill()
        proc.wait()
    shutil.rmtree(tmp, ignore_errors=True)

# Nothing but procinfo reads /proc or runs ss — keepawake's detector and
# holders included, which run on macOS too. The bot's Python modules
# (keepawake/*.py) keep their own reads, each with macOS's beside it. A
# comment saying where something comes from is not a read.
OWN = {os.path.join("sclaude", "lib", "core", n) for n in ("procinfo.sh", "procinfo.py")}
READ = re.compile(r"""/proc/|["']/proc["']|\bss\s+-|\["ss",""")
paths = [os.path.join("bin", n) for n in os.listdir(os.path.join(ROOT, "bin"))
         if n.startswith(("sclaude", "chrome-debug", "keepawake"))]
for top in ("sclaude", "skills"):
    for d, _, names in os.walk(os.path.join(ROOT, top)):
        paths += [os.path.relpath(os.path.join(d, n), ROOT) for n in names
                  if n.endswith((".sh", ".py")) and "__pycache__" not in d]
strays = []
for rel in sorted(set(paths)):
    if rel in OWN or rel == os.path.join("skills", "isleep", "night.py"):
        continue
    with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            code = line.split("#", 1)[0] if not line.lstrip().startswith(("'", '"')) else line
            if READ.search(code) and "procinfo" not in line:
                strays.append("%s:%d" % (rel, n))
check("no /proc or ss outside procinfo", strays, [])
# night.py is a skill on its own, linked into ~/.claude/skills: it keeps its
# reads, and macOS's beside each.
night = open(os.path.join(ROOT, "skills", "isleep", "night.py"), encoding="utf-8").read()
check("night.py reads macOS beside each /proc",
      night.count('Path(f"/proc/') <= night.count("if DARWIN"), True)

# procinfo.sh hands macOS's environment questions to procinfo.py by the name
# of a subcommand: each name it calls is one main() takes (2 is its usage).
called = re.findall(r'"\$PROCINFO_PY" ([\w-]+)', open(os.path.join(LIB, "core", "procinfo.sh")).read())
check("procinfo.sh calls procinfo.py", sorted(set(called)), ["env-anywhere", "env-has"])
for sub in sorted(set(called)):
    args = [sub, str(os.getpid()), "PATH=" + os.environ.get("PATH", "")] if sub == "env-has" \
        else [sub, "PATH=" + os.environ.get("PATH", "")]
    check("procinfo.py takes %s" % sub, procinfo.main(args) != 2, True)

if failures:
    print("FAILED: %d" % len(failures))
    sys.exit(1)
print("all good")
