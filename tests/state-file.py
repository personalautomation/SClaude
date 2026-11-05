#!/usr/bin/env python3
# state_file.py (sclaude/lib/core): a feature's state.json changed under a lock
# and written whole, by every writer — state_set in state.sh among them.
#
# Two writers raise one counter side by side while a reader keeps reading the
# file: with the lock no raise is lost, and with the whole-file write the
# reader never finds the file empty or cut short. Then state_set itself, run
# from several shells at once on different fields: every field lands.
#
# Run it with: python3 tests/state-file.py
import json
import os
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "sclaude", "lib", "core")
STATE_SH = os.path.join(CORE, "state.sh")
sys.path.insert(0, CORE)
import state_file  # noqa: E402

failures = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


RAISE = r"""
import json, sys
sys.path.insert(0, sys.argv[2])
import state_file
for _ in range(int(sys.argv[3])):
    with state_file.update(sys.argv[1]) as data:
        data["n"] = data.get("n", 0) + 1
        data["pad"] = "x" * 20000   # a write long enough to be caught half done
"""

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "state.json")
    state_file.write(path, {"n": 0})
    check("written whole: a file of its own, readable", json.load(open(path)) == {"n": 0})
    check("readable by others, as the record it replaces was",
          oct(os.stat(path).st_mode & 0o777) == "0o644")

    bad = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                with open(path) as fh:
                    json.load(fh)
            except ValueError:
                bad.append(1)

    t = threading.Thread(target=reader)
    t.start()
    per = 150
    writers = [subprocess.Popen([sys.executable, "-c", RAISE, path, CORE, str(per)])
               for _ in range(2)]
    codes = [w.wait() for w in writers]
    stop.set()
    t.join()
    check("both writers ran", codes == [0, 0])
    check("no raise lost between two writers", json.load(open(path))["n"] == 2 * per)
    check("the reader never found the file half written", not bad)
    left = sorted(f for f in os.listdir(tmp) if f != "state.json")
    check("nothing left beside it but its lock", left == ["state.json.lock"])

    # An exception inside update leaves the record as it was.
    try:
        with state_file.update(path) as data:
            data["n"] = -1
            raise SystemExit(0)
    except SystemExit:
        pass
    check("an exit inside update writes nothing", json.load(open(path))["n"] == 2 * per)

    missing = os.path.join(tmp, "none.json")
    try:
        with state_file.update(missing):
            pass
        check("a missing record is not made up", False)
    except FileNotFoundError:
        check("a missing record is not made up", True)
    with state_file.update(missing, create=True) as data:
        data["a"] = 1
    check("create=True starts one", json.load(open(missing)) == {"a": 1})

    # state_set from several shells at once, each on a field of its own: the
    # read-modify-write is under the lock, so none overwrites another's field.
    state_file.write(path, {})
    script = 'source "%s"; for i in $(seq 15); do state_set "%s" "f.$1" "$i"; done' % (STATE_SH, path)
    shells = [subprocess.Popen(["bash", "-c", script, "-", "k%d" % k]) for k in range(6)]
    for sh in shells:
        sh.wait()
    got = json.load(open(path)).get("f", {})
    check("state_set from six shells at once: every field landed",
          got == {"k%d" % k: 15 for k in range(6)})

# The writers find state_file.py at ${STATE_CORE:-${LIB:-}/core} and swallow
# their errors (`2>/dev/null || true`): without either variable the state
# would silently stop being written. sclaude sets LIB before it sources a
# module, and state.sh sets STATE_CORE as it is sourced.
with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    text = fh.read()
check("bin/sclaude sets LIB before it sources the modules",
      0 <= text.find("\nLIB=") < text.find('source "$LIB/$_module.sh"'))
check("bin/sclaude sources core/state", "core/state " in text)
out = subprocess.run(["bash", "-c", 'source "%s"; echo "$STATE_CORE"' % STATE_SH],
                     capture_output=True, text=True).stdout.strip()
check("state.sh names its own folder in STATE_CORE", out == CORE)
writers = []
for folder, _, files in os.walk(os.path.join(ROOT, "sclaude", "lib")):
    for name in files:
        if name.endswith(".sh"):
            with open(os.path.join(folder, name)) as fh:
                if "import state_file" in fh.read():
                    writers.append(name)
bad = []
for folder, _, files in os.walk(os.path.join(ROOT, "sclaude", "lib")):
    for name in files:
        if not name.endswith(".sh"):
            continue
        with open(os.path.join(folder, name)) as fh:
            body = fh.read()
        for block in body.split("python3 - ")[1:]:
            head = body[:body.index(block)].rsplit("\n", 1)[-1]
            if "import state_file" in block.split("\nPY")[0] and 'PYTHONPATH="${STATE_CORE:-${LIB:-}/core}"' not in head:
                bad.append(name)
check("every shell writer through state_file is told where it is", not bad and len(writers) >= 6)

# Every field the shell names is in the schema (state_schema.py), and every
# entry there is named somewhere: a mistyped path reads as "not set", without
# an error, and a field the code stopped using leaves a description of nothing.
import re  # noqa: E402
import glob  # noqa: E402
import state_schema  # noqa: E402
SHELL = sorted(glob.glob(os.path.join(ROOT, "sclaude", "lib", "*", "*.sh"))) + [
    os.path.join(ROOT, "bin", "sclaude"), os.path.join(ROOT, "bin", "sclaude-watch")]
CALL = re.compile(r'state_(?:get|set) +"[^"]*" +["\']?([A-Za-z_.${}-]+)'
                  # and a field read from a snapshot (state_snapshot)
                  r'|\$\{snap\[([A-Za-z_.$-]+)\]')
paths = {}
for name in SHELL:
    with open(name) as fh:
        for n, line in enumerate(fh, 1):
            for m in CALL.finditer(line):
                path = re.sub(r"\$\{?[A-Za-z_]+\}?", state_schema.WILD, m.group(1) or m.group(2))
                paths.setdefault(path, "%s:%d" % (os.path.relpath(name, ROOT), n))
check("the shell names many state fields (the scan works)", len(paths) > 100)
check("the scan reads snapshots too", "rollback.prod.code" in paths and "friction.<*>.session" in paths)
unknown = sorted("%s (%s)" % (p, w) for p, w in paths.items() if not state_schema.known(p))
check("every state field the shell names is in state_schema.py: %s" % unknown, not unknown)


def named(pattern):
    """Whether some path in the code could be this schema entry."""
    want = pattern.split(".")
    return any(len(want) == len(p.split(".")) and
               all(state_schema._segment_ok(a, b) for a, b in zip(want, p.split(".")))
               for p in paths)


stale = sorted(p for p, _, _ in state_schema.FIELDS
               if p not in state_schema.WRITTEN_WHOLE and not named(p))
check("every entry of state_schema.py is named in the code: %s" % stale, not stale)
patterns = [p for p, _, _ in state_schema.FIELDS]
check("state_schema.py lists each path once", len(patterns) == len(set(patterns)))

if failures:
    print("%d failed" % len(failures))
    sys.exit(1)
print("state-file: ok")
