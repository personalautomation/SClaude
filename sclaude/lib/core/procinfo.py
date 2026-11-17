"""What sclaude asks about other processes and the ports they listen on, on
Linux and on macOS alike: the Python half of procinfo.sh.

Linux answers from /proc and `ss`; macOS has neither, and answers from `lsof`,
and from the kernel for a process's words and environment.

  python3 procinfo.py env-has <pid> NAME=VALUE    exit 0 when it holds it
  python3 procinfo.py env-anywhere NAME=VALUE     exit 0 when any process does

procinfo.sh asks the two of them on macOS, where ps shows an environment with
spaces between its entries and a value may hold spaces itself.
"""
import os
import re
import struct
import subprocess
import sys

DARWIN = sys.platform == "darwin"


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def listening_pids():
    """{port: set of pids listening on it over TCP}, from one run."""
    found = {}
    if DARWIN:
        pid = None
        for line in _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"]).splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith("n") and pid is not None:
                port = line.rsplit(":", 1)[-1]
                if port.isdigit():
                    found.setdefault(int(port), set()).add(pid)
        return found
    for line in _run(["ss", "-ltnpH"]).splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        port = cols[3].rsplit(":", 1)[-1]
        if not port.isdigit():
            continue
        for pid in re.findall(r"pid=(\d+)", line):
            found.setdefault(int(port), set()).add(int(pid))
    return found


def working_dirs():
    """[(pid, cwd)] of every process whose directory can be read, in one pass."""
    out = []
    if DARWIN:
        pid = None
        argv = ["lsof", "-a", "-d", "cwd", "-u", str(os.getuid()), "-Fpn"]
        for line in _run(argv).splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = int(line[1:])
            elif line.startswith("n") and pid is not None:
                out.append((pid, line[1:]))
        return out
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            out.append((int(name), os.readlink("/proc/%s/cwd" % name)))
        except OSError:
            continue
    return out


def darwin_procargs(pid):
    """(words, environment) of a process on macOS, exactly, from the kernel
    (KERN_PROCARGS2, what ps reads too). The buffer is the word count, the
    executable's path, the padding after it, then the words and the
    environment's entries, each ending in a zero byte. The system's own
    binaries keep their environment from it; a node never does."""
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    mib = (ctypes.c_int * 3)(1, 49, int(pid))      # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        raise OSError("no such process")
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        raise OSError("no such process")
    raw = buf.raw[:size.value]
    if len(raw) < 4:
        raise OSError("no words")
    argc = struct.unpack("i", raw[:4])[0]
    at = raw.index(b"\0", 4)
    while at < len(raw) and raw[at] == 0:
        at += 1
    parts = raw[at:].split(b"\0")
    words = [w.decode(errors="replace") for w in parts[:argc]]
    env = []
    for entry in parts[argc:]:
        if not entry:
            break
        env.append(entry.decode(errors="replace"))
    return words, env


def environ_of(pid):
    """A process's environment, one NAME=VALUE an entry; [] when unreadable."""
    try:
        if DARWIN:
            return darwin_procargs(pid)[1]
        with open("/proc/%d/environ" % int(pid), "rb") as fh:
            return [e.decode(errors="replace") for e in fh.read().split(b"\0") if e]
    except (OSError, ValueError):
        return []


def user_pids():
    """This user's processes."""
    if not DARWIN:
        return [int(n) for n in os.listdir("/proc") if n.isdigit()]
    out = _run(["ps", "-U", str(os.getuid()), "-o", "pid="])
    return [int(p) for p in out.split() if p.isdigit()]


def main(argv):
    if len(argv) == 3 and argv[0] == "env-has" and argv[1].isdigit():
        return 0 if argv[2] in environ_of(int(argv[1])) else 1
    if len(argv) == 2 and argv[0] == "env-anywhere":
        return 0 if any(argv[1] in environ_of(p) for p in user_pids()) else 1
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
