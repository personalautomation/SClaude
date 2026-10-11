#!/usr/bin/env python3
#
# A bench for keepawake on plain Linux: where the state lives without Windows,
# and bin/keepawake-linux, the holding side that replaces KeepAwake.ps1 there.
#
# systemd-inhibit is replaced by a stub that either holds (sleeps) or refuses
# (exits at once) per lock level, so the fallback from the full set to idle can
# be driven without asking logind for anything.
#
# What each case would look like broken:
#
#   state path            state.py raises "could not determine the Windows
#                         user" on every machine that is not WSL.
#   hold / release        the machine sleeps under work, or never sleeps.
#   stale state           a dead counter keeps the laptop awake for ever.
#   fallback to idle      a refused lid-switch lock means no lock at all.
#   log lines             `keepawake status` greps "hold set|hold released|
#                         holding" and finds nothing to show.
#
# Run it with: python3 tests/keepawake-linux.py
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


tmp = tempfile.mkdtemp()
os.environ.pop("KEEPAWAKE_STATE", None)
os.environ["KEEPAWAKE_PLATFORM"] = "linux"
os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "xdg")

from keepawake import state  # noqa: E402

print("state without Windows")
check("state-path-linux", state.state_path(),
      os.path.join(tmp, "xdg", "keepawake", "state.json"))
check("hold-log-linux", state.hold_log_path(),
      os.path.join(tmp, "xdg", "keepawake", "hold.log"))
check("platform-cli", subprocess.run(
    [sys.executable, os.path.join(ROOT, "keepawake", "state.py"), "platform"],
    capture_output=True, text=True, env=os.environ).stdout.strip(), "linux")
# Under WSL the holder is KeepAwake.ps1, and its log keeps its old name beside
# the state on drive C.
os.environ["KEEPAWAKE_PLATFORM"] = "wsl"
os.environ["KEEPAWAKE_STATE"] = os.path.join(tmp, "c", "state.json")
check("hold-log-wsl", state.hold_log_path(), os.path.join(tmp, "c", "keepawake-ps.log"))
os.environ.pop("KEEPAWAKE_STATE")
os.environ["KEEPAWAKE_PLATFORM"] = "linux"

# --- the holder ---------------------------------------------------------------

stub = os.path.join(tmp, "inhibit")
with open(stub, "w") as fh:
    fh.write('#!/usr/bin/env bash\n'
             'case " $REFUSE " in *" $1 "*) exit 1 ;; esac\n'
             'exec sleep 300\n')
os.chmod(stub, 0o755)
os.environ["KEEPAWAKE_INHIBIT"] = stub
os.environ["KEEPAWAKE_STATE"] = os.path.join(tmp, "state.json")
os.environ["KEEPAWAKE_HOLD_LOG"] = os.path.join(tmp, "hold.log")

loader = importlib.machinery.SourceFileLoader(
    "keepawake_linux", os.path.join(ROOT, "bin", "keepawake-linux"))
spec = importlib.util.spec_from_loader("keepawake_linux", loader)
kl = importlib.util.module_from_spec(spec)
loader.exec_module(kl)


def set_state(**fields):
    data = state.blank()
    data.update(fields)
    state.write(data)


def log_lines():
    try:
        with open(os.environ["KEEPAWAKE_HOLD_LOG"]) as fh:
            return [line.split("  ", 1)[1].strip() for line in fh if "  " in line]
    except OSError:
        return []


now = int(time.time())
holder = kl.Holder()
try:
    print("hold and release")
    set_state(updated_ts=now, until_ts=now + 3600)
    check("holds-while-wanted", holder.tick(now), True)
    check("lock-alive", holder.holding(), True)
    check("full-set-first", holder.what, kl.WHAT[0])
    check("hold-set-logged", log_lines()[-1].startswith("hold set, until "), True)

    set_state(updated_ts=now, until_ts=now - 1)
    holder.tick(now)
    check("released-when-not-wanted", holder.holding(), False)
    check("release-logged", log_lines()[-1], "hold released")

    print("hard hold and staleness")
    set_state(updated_ts=now, hard_hold=True)
    holder.tick(now)
    check("hard-hold-logged", log_lines()[-1], "hold set: a person is at the machine")
    set_state(updated_ts=now - state.STALE_AFTER - 1, hard_hold=True)
    holder.tick(now)
    check("stale-releases", holder.holding(), False)

    print("fallback")
    os.environ["REFUSE"] = "sleep:idle:handle-lid-switch sleep:idle"
    holder = kl.Holder()
    set_state(updated_ts=now, until_ts=now + 3600)
    holder.tick(now)
    check("falls-back-to-idle", (holder.holding(), holder.what), (True, "idle"))
    check("partial-noted-once",
          sum(1 for line in log_lines() if line.startswith("NOTE: logind granted only")), 1)
    holder.release()

    os.environ["REFUSE"] = " ".join(kl.WHAT)
    holder = kl.Holder()
    holder.tick(now)
    holder.tick(now)
    check("refused-everything-no-lock", holder.holding(), False)
    check("refusal-said-once",
          sum(1 for line in log_lines() if line.startswith("ERROR: systemd-inhibit refused")), 1)
    os.environ.pop("REFUSE")

    print("the lines keepawake status greps for")
    keepawake = open(os.path.join(ROOT, "bin", "keepawake"), encoding="utf-8").read()
    pattern = re.search(r'grep -E "([^"]+)"', keepawake[keepawake.index("win_log() {"):]).group(1)
    for line in ("hold set, until 14:00", "hold set: a person is at the machine",
                 "hold released", "holding, until 14:00"):
        check("status-greps-%s" % line.split(",")[0].split(":")[0].replace(" ", "-"),
              re.search(pattern, line) is not None, True)
    source = open(os.path.join(ROOT, "bin", "keepawake-linux"), encoding="utf-8").read()
    for literal in ('"hold set: a person is at the machine"', '"hold set, until %s"',
                    '"hold released"', '"holding, until %s"'):
        check("linux-writes-%s" % literal.strip('"').split(",")[0].split(":")[0].replace(" ", "-"),
              literal in source, True)
    ps1 = open(os.path.join(ROOT, "windows", "KeepAwake.ps1"), encoding="utf-8").read()
    for literal in ("hold set: a person is at the machine", "hold set, until",
                    "hold released", "holding, until"):
        check("windows-writes-same-%s" % literal.split(",")[0].split(":")[0].replace(" ", "-"),
              literal in ps1, True)
finally:
    holder.release()

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
