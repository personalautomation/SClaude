#!/usr/bin/env python3
#
# units_refresh brings the installed systemd units up to the repository's.
#
# install.sh writes a unit with the checkout's path put in for @REPO@, and an
# update that changed one left it as it was: a unit an older install.sh linked
# into the repository came to read @REPO@ literally, and the bot crash-looped.
#
# Run it with: python3 tests/units.py
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def refresh(inst, cfg):
    script = ('source "%s/ui.sh" 2>/dev/null; source "%s/run.sh"; INSTRUMENTS="%s"; '
              'systemctl() { echo "$*" >> "%s/reloads"; case "$2" in '
              'is-failed) [ -e "%s/failed-$4" ] ;; is-active) [ -e "%s/active-$4" ] ;; '
              'is-enabled) cat "%s/enabled-$3" 2>/dev/null || echo static ;; esac; }; '
              'info() { echo "INFO $*"; }; units_refresh' % (LIB, LIB, inst, cfg, cfg, cfg, cfg))
    return subprocess.run(["bash", "-c", script], env=dict(os.environ, HOME=cfg), check=True,
                          capture_output=True, text=True).stdout


tmp = tempfile.mkdtemp()
try:
    inst = os.path.join(tmp, "inst")
    os.makedirs(os.path.join(inst, "systemd"))
    for name, body in (("a.service", "ExecStart=@REPO@/bin/x\n"), ("b.service", "ExecStart=@REPO@/bin/y\n")):
        with open(os.path.join(inst, "systemd", name), "w") as fh:
            fh.write(body)
    cfg = os.path.join(tmp, "cfg")
    units = os.path.join(cfg, ".config", "systemd", "user")
    os.makedirs(units)
    os.symlink(os.path.join(inst, "systemd", "a.service"), os.path.join(units, "a.service"))

    refresh(inst, cfg)
    a = os.path.join(units, "a.service")
    check("a link is written out", os.path.islink(a), False)
    check("with the checkout's path", open(a).read(), "ExecStart=%s/bin/x\n" % inst)
    check("the repository's file is untouched",
          open(os.path.join(inst, "systemd", "a.service")).read(), "ExecStart=@REPO@/bin/x\n")
    check("a unit not installed stays so", os.path.exists(os.path.join(units, "b.service")), False)
    check("systemd is told", os.path.exists(os.path.join(cfg, "reloads")), True)

    os.remove(os.path.join(cfg, "reloads"))
    refresh(inst, cfg)
    check("nothing to do, nothing said", os.path.exists(os.path.join(cfg, "reloads")), False)

    with open(os.path.join(inst, "systemd", "a.service"), "a") as fh:
        fh.write("KillMode=process\n")
    refresh(inst, cfg)
    check("a changed unit is written again", "KillMode=process" in open(a).read(), True)

    masked = os.path.join(units, "b.service")
    os.symlink("/dev/null", masked)
    refresh(inst, cfg)
    check("a masked unit stays masked", os.readlink(masked), "/dev/null")

    def calls():
        try:
            with open(os.path.join(cfg, "reloads")) as fh:
                return fh.read()
        finally:
            os.remove(os.path.join(cfg, "reloads"))

    calls()

    def touch(name):
        open(os.path.join(cfg, name), "w").close()

    def change(unit):
        with open(os.path.join(inst, "systemd", unit), "a") as fh:
            fh.write("# changed\n")

    def reset():
        for f in os.listdir(cfg):
            if f.split("-")[0] in ("failed", "active", "enabled"):
                os.remove(os.path.join(cfg, f))

    change("a.service")
    touch("active-a.service")
    out = refresh(inst, cfg)
    check("a running unit is not restarted", "restart a.service" in calls(), False)
    check("it is named for the person", "systemctl --user restart a.service" in out, True)
    reset()

    change("a.service")
    touch("failed-a.service")
    refresh(inst, cfg)
    check("a failed static unit is not started", "start --no-block a.service" in calls(), False)
    reset()

    change("a.service")
    touch("failed-a.service")
    with open(os.path.join(cfg, "enabled-a.service"), "w") as fh:
        fh.write("enabled-runtime\n")
    refresh(inst, cfg)
    check("a failed enabled unit is started", "start --no-block a.service" in calls(), True)
    reset()

    with open(os.path.join(inst, "systemd", "a.socket"), "w") as fh:
        fh.write("[Socket]\n")
    with open(os.path.join(units, "a.socket"), "w") as fh:
        fh.write("[Socket]\n")
    change("a.service")
    touch("failed-a.service")
    refresh(inst, cfg)
    log = calls()
    check("a failed socket-started unit comes back by its socket",
          ("reset-failed a.socket" in log, "start --no-block a.socket" in log), (True, True))
    reset()

    os.remove(a)
    os.symlink(os.path.join(tmp, "moved", "systemd", "a.service"), a)
    refresh(inst, cfg)
    check("a link into a moved checkout is repaired", os.path.islink(a), False)

    os.remove(a)
    own = os.path.join(tmp, "mine.service")
    open(own, "w").close()
    os.symlink(own, a)
    refresh(inst, cfg)
    check("a unit of the person's own stays", os.path.islink(a), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
