#!/usr/bin/env python3
# Static checks that catch what a reader misses and no bench runs into: an
# undefined or unused name in Python (ruff's pyflakes rules, F), and in shell
# what shellcheck calls an error. shellcheck's warnings are not asked for: the
# code splits words and orders redirections on purpose, and nearly all of them
# were that.
#
# Both tools come through uvx, from its cache only: a machine without them,
# or offline before the first fetch, skips the check and says so. Fetch them
# once with `uvx ruff --version; uvx --from shellcheck-py shellcheck -V`.
#
# Run it with: python3 tests/lint.py
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tracked():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True, text=True).stdout
    return [p for p in out.split("\0") if p and os.path.isfile(os.path.join(ROOT, p))]


def shebang(path):
    try:
        with open(os.path.join(ROOT, path), "rb") as fh:
            return fh.readline().decode(errors="replace")
    except OSError:
        return ""


def tool(*argv):
    """The tool's command line, or None when uvx cannot run it offline."""
    if not shutil.which("uvx"):
        return None
    cmd = ["uvx", "--offline", *argv]
    probe = subprocess.run(cmd + ["--version"], capture_output=True, cwd=ROOT)
    return cmd if probe.returncode == 0 else None


files = tracked()
python = [p for p in files if p.endswith(".py")
          or (not os.path.splitext(p)[1] and "python" in shebang(p))]
shell = [p for p in files if p.endswith((".sh", ".bash"))
         or (not os.path.splitext(p)[1] and "bash" in shebang(p))]

failed = False
skipped = []

ruff = tool("ruff")
if ruff is None:
    skipped.append("ruff")
else:
    r = subprocess.run(ruff + ["check", "--no-cache", "--select", "F", "--output-format", "concise", "-q"] + python,
                       capture_output=True, text=True, cwd=ROOT)
    print(("ok   " if r.returncode == 0 else "FAIL ") + "ruff F over %d Python files" % len(python))
    if r.returncode:
        print(r.stdout + r.stderr)
        failed = True

shellcheck = tool("--from", "shellcheck-py", "shellcheck")
if shellcheck is None:
    skipped.append("shellcheck")
else:
    # One process per batch, side by side: shellcheck alone takes some 20 s.
    jobs = os.cpu_count() or 4
    batches = [shell[i::jobs] for i in range(jobs) if shell[i::jobs]]
    procs = [subprocess.Popen(shellcheck + ["-S", "error", "-f", "gcc"] + b,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
             for b in batches]
    out = "".join(p.communicate()[0] for p in procs)
    bad = any(p.returncode for p in procs)
    print(("ok   " if not bad else "FAIL ") + "shellcheck errors over %d shell files" % len(shell))
    if bad:
        print(out)
        failed = True

if skipped:
    print("skipped: %s (not in uvx's cache)" % ", ".join(skipped))
if failed:
    sys.exit(1)
print("lint: ok")
