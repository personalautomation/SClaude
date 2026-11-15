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

# launchd_load marks each load under the state directory: under HOME here.
os.environ.pop("XDG_STATE_HOME", None)

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def refresh(inst, cfg):
    script = ('source "%s/core/ui.sh" 2>/dev/null; source "%s/improve/instruments.sh"; INSTRUMENTS="%s"; '
              'systemctl() { echo "$*" >> "%s/reloads"; case "$2" in '
              'is-failed) [ -e "%s/failed-$4" ] ;; is-active) [ -e "%s/active-$4" ] ;; '
              'is-enabled) cat "%s/enabled-$3" 2>/dev/null || echo static ;; esac; }; '
              'info() { echo "INFO $*"; }; units_refresh' % (LIB, LIB, inst, cfg, cfg, cfg, cfg))
    # The systemd side wherever the bench runs: launchd's is below.
    return subprocess.run(["bash", "-c", script], env=dict(os.environ, HOME=cfg, SCLAUDE_OS="linux"),
                          check=True, capture_output=True, text=True).stdout


def agents_refresh(inst, home):
    """units_refresh as macOS runs it, launchd's side, on any machine:
    launchctl logs what it is told (`print` answers for a loaded-<label>
    file), plutil reads the PATH as the real one would."""
    script = ('source "%s/core/ui.sh" 2>/dev/null; source "%s/improve/instruments.sh"; INSTRUMENTS="%s"; '
              'launchctl() { echo "$*" >> "%s/launchctl"; [[ "$1" != print ]] || [[ -e "%s/loaded-${2##*/}" ]]; }; '
              'plutil() { sed -n "/<key>PATH<\\/key>/{n;s/.*<string>\\(.*\\)<\\/string>.*/\\1/p}" "${@: -1}"; }; '
              'info() { echo "INFO $*"; }; units_refresh' % (LIB, LIB, inst, home, home))
    return subprocess.run(["bash", "-c", script], env=dict(os.environ, HOME=home, SCLAUDE_OS="macos"),
                          check=True, capture_output=True, text=True).stdout


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

    # --- macOS: the launchd agents (sclaude/lib/core/launchd.sh) -------------
    home = os.path.join(tmp, "mac")
    agents_dir = os.path.join(home, "Library", "LaunchAgents")
    os.makedirs(agents_dir)
    os.makedirs(os.path.join(inst, "launchd"))
    template = ("<key>ProgramArguments</key><string>@HOME@/.local/bin/x</string>\n"
                "<key>PATH</key>\n<string>@PATH@</string>\n")
    for label in ("sclaude.w", "sclaude.v"):
        with open(os.path.join(inst, "launchd", label + ".plist"), "w") as fh:
            fh.write(template)
    agent = os.path.join(agents_dir, "sclaude.w.plist")
    with open(agent, "w") as fh:
        fh.write("<key>PATH</key>\n<string>/kept/path</string>\n")

    def launched():
        log = os.path.join(home, "launchctl")
        try:
            with open(log) as fh:
                return fh.read()
        except FileNotFoundError:
            return ""
        finally:
            if os.path.exists(log):
                os.remove(log)

    agents_refresh(inst, home)
    written = open(agent).read()
    check("agent: written from the template", "%s/.local/bin/x" % home in written, True)
    check("agent: the PATH it was installed with kept", "<string>/kept/path</string>" in written, True)
    check("agent: one not installed stays so",
          os.path.exists(os.path.join(agents_dir, "sclaude.v.plist")), False)
    check("agent: not loaded, so loaded", "bootstrap gui/" in launched(), True)
    check("no systemd unit dir made", os.path.exists(os.path.join(home, ".config", "systemd")), False)

    agents_refresh(inst, home)
    check("agent: nothing changed, nothing loaded", "bootstrap" in launched(), False)

    with open(os.path.join(inst, "launchd", "sclaude.w.plist"), "a") as fh:
        fh.write("<!-- changed -->\n")
    open(os.path.join(home, "loaded-sclaude.w"), "w").close()
    out = agents_refresh(inst, home)
    log = launched()
    check("agent: a loaded one is not reloaded", ("bootout" in log, "bootstrap" in log), (False, False))
    check("agent: it is named for the person", "sclaude.w" in out and "./install.sh" in out, True)
    check("agent: but written", "<!-- changed -->" in open(agent).read(), True)

    # A reload waits for the old job to be gone: bootout returns while its
    # process still exits, and launchd refuses the label until then. Here
    # `print` answers "loaded" twice after the bootout, and a bootstrap before
    # that fails, as launchd's does.
    gone = os.path.join(home, "gone-after")
    script = ('source "%s/core/ui.sh" 2>/dev/null; source "%s/core/launchd.sh"; INSTRUMENTS="%s"; '
              'sleep() { :; }; '
              'launchctl() { echo "$*" >> "%s/launchctl"; case "$1" in '
              'bootout) echo 2 > "%s" ;; '
              'print) [[ -e "%s" ]] || return 0; n=$(cat "%s"); (( n > 0 )) || return 1; '
              'echo $(( n - 1 )) > "%s"; return 0 ;; '
              'bootstrap) [[ ! -e "%s" || "$(cat "%s")" == 0 ]] ;; esac; }; '
              'launchd_load sclaude.w; echo "rc=$?"' % ((LIB, LIB, inst, home) + (gone,) * 6))
    out = subprocess.run(["bash", "-c", script], env=dict(os.environ, HOME=home, SCLAUDE_OS="macos"),
                         capture_output=True, text=True).stdout
    log = launched().splitlines()
    check("agent: a reload waits for the old job, then loads it",
          ([line.split()[0] for line in log], out.strip()),
          (["print", "bootout", "print", "print", "print", "bootstrap"], "rc=0"))

    script = ('source "%s/core/ui.sh" 2>/dev/null; source "%s/core/launchd.sh"; INSTRUMENTS="%s"; '
              'sleep() { :; }; launchctl() { echo "$*" >> "%s/launchctl"; [[ "$1" != bootstrap && "$1" != print ]]; }; '
              'launchd_load sclaude.w; echo "rc=$?"' % (LIB, LIB, inst, home))
    out = subprocess.run(["bash", "-c", script], env=dict(os.environ, HOME=home, SCLAUDE_OS="macos"),
                         capture_output=True, text=True).stdout
    check("agent: a load launchd keeps refusing fails after a few tries",
          (launched().count("bootstrap"), out.strip()), (3, "rc=1"))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
