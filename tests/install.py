#!/usr/bin/env python3
#
# A bench for install.sh: what it installs by default and with --extras, what
# it says without systemd, code-server's local port, and its one question —
# keepawake's polkit rule on plain Linux.
#
# The real install.sh runs with a temporary HOME, the platform forced to plain
# Linux, and stubs for systemctl, loginctl and sudo ahead of everything on PATH
# (sudo runs the command as this user; systemctl records what it was asked).
# The rule's path is a temporary one, so nothing under /etc is touched.
#
# What each case would look like broken:
#
#   WSL                 a question about a Linux-only rule on a Windows laptop.
#   no terminal         an installer run from a script hangs on a read.
#   the question        the undo command shown only after the yes, or never.
#   --polkit            the rule not written, or keepawake-linux not restarted
#                       and still holding idle only until the next boot.
#   already in place    asked again on every re-run of an idempotent installer.
#   Enter               taken for an answer: sclaude has no defaults.
#   sclaude only        a newcomer given a Telegram bot and an editor server
#                       they did not ask for, or a machine that had them losing
#                       them on a plain re-run.
#   no systemd          the installer stopping half-way without a word.
#   code-server :8080   the forward enabled on code-server's own default port:
#                       the server failing with EADDRINUSE every 10 s.
#
# Run it with: python3 tests/install.py
import os
import pty
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
INSTALL = os.path.join(ROOT, "install.sh")
failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


def world(tmp, systemd=True):
    home = os.path.join(tmp, "home")
    stubs = os.path.join(tmp, "stubs")
    etc = os.path.join(tmp, "etc", "polkit-1", "rules.d")
    for d in (home, stubs, etc):
        os.makedirs(d, exist_ok=True)
    calls = os.path.join(tmp, "systemctl.calls")
    for name, body in (
            ("systemctl", 'echo "$*" >> %s\nexit %d\n' % (calls, 0 if systemd else 1)),
            ("loginctl", 'echo yes\n'),
            ("sudo", '"$@"\n'),
            ("cmd.exe", 'exit 127\n')):
        path = os.path.join(stubs, name)
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\n" + body)
        os.chmod(path, 0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("KEEPAWAKE_")}
    env.update(HOME=home, USER="someone", KEEPAWAKE_PLATFORM="linux",
               KEEPAWAKE_POLKIT_RULE=os.path.join(etc, "49-keepawake.rules"),
               PATH=stubs + ":" + os.environ["PATH"])
    return env, os.path.join(etc, "49-keepawake.rules"), calls


def run(env, *args, answer=None, extras=True, rc=None):
    """install.sh with stdin from a pipe, or from a terminal typing `answer`
    (a list types one answer per question asked). --extras unless told not to;
    `rc`, a list, receives the exit code."""
    args = (["--extras"] if extras else []) + list(args)
    if answer is None:
        done = subprocess.run([INSTALL] + args, env=env, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=120)
        if rc is not None:
            rc.append(done.returncode)
        return done.stdout + done.stderr
    answers = [answer] if isinstance(answer, str) else list(answer)
    primary, secondary = pty.openpty()
    proc = subprocess.Popen([INSTALL] + args, env=env, stdin=secondary,
                            stdout=secondary, stderr=secondary, close_fds=True)
    os.close(secondary)
    out = b""
    sent = 0
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            chunk = os.read(primary, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if sent < len(answers) and out.count(b"Add it now?") > sent:
            os.write(primary, (answers[sent] + "\n").encode())
            sent += 1
    proc.wait(timeout=30)
    os.close(primary)
    return out.decode(errors="replace")


with tempfile.TemporaryDirectory() as tmp:
    print("where it does not apply")
    env, rule, calls = world(os.path.join(tmp, "wsl"))
    env["KEEPAWAKE_PLATFORM"] = "wsl"
    out = run(env)
    check("wsl-says-nothing", "polkit" in out, False)

    print("no terminal")
    env, rule, calls = world(os.path.join(tmp, "pipe"))
    out = run(env)
    check("pipe-explains", "optional polkit rule" in out, True)
    check("pipe-shows-undo", "sudo rm %s" % rule in out, True)
    check("pipe-points-at-flag", "./install.sh --polkit" in out, True)
    check("pipe-writes-nothing", os.path.exists(rule), False)
    # The units are written with this checkout's path, under whatever name it
    # has: a file, not a link, and no placeholder left in it.
    telegram = os.path.join(env["HOME"], ".config", "systemd", "user", "keepawake-telegram.service")
    check("unit-is-a-file", (os.path.isfile(telegram), os.path.islink(telegram)), (True, False))
    if os.path.isfile(telegram):
        body = open(telegram).read()
        check("unit-names-the-checkout", "%s/keepawake/telegramd.py" % os.path.realpath(ROOT) in body
              or "%s/keepawake/telegramd.py" % ROOT in body, True)
        check("unit-has-no-placeholder", "@REPO@" in body, False)

    print("--no-polkit")
    out = run(env, "--no-polkit")
    check("no-polkit-silent", "optional polkit rule" in out, False)
    check("no-polkit-writes-nothing", os.path.exists(rule), False)

    print("asked in a terminal")
    out = run(env, answer=["", "maybe", "n"])
    check("tty-undo-before-question",
          -1 < out.find("sudo rm %s" % rule) < out.find("Add it now?"), True)
    check("tty-enter-asks-again", out.count("Add it now?"), 3)
    check("tty-no-writes-nothing", os.path.exists(rule), False)
    out = run(env, answer="y")
    check("tty-yes-writes", os.path.exists(rule), True)
    if os.path.exists(rule):
        text = open(rule).read()
        check("rule-names-the-user", 'subject.user == "someone"' in text, True)
        check("rule-grants-sleep-and-lid",
              ("inhibit-block-sleep" in text, "inhibit-handle-lid-switch" in text),
              (True, True))
        check("rule-carries-its-undo", "sudo rm %s" % rule in text, True)
    check("yes-restarts-the-holder",
          "--user restart keepawake-linux.service" in open(calls).read(), True)

    print("already in place")
    out = run(env, answer="y")
    check("present-not-asked-again", "Add it now?" in out, False)
    check("present-shows-undo", "to turn it off: sudo rm %s" % rule in out, True)

    print("rules.d not readable (Fedora, Arch)")
    # The rule is there but cannot be seen from a normal user; the note the
    # installer left when it wrote the rule is what is read instead.
    etc_dir = os.path.dirname(rule)
    os.chmod(etc_dir, 0o000)
    try:
        out = run(env, answer="y")
        check("unreadable-with-note-not-asked", "Add it now?" in out, False)
        os.remove(os.path.join(env["HOME"], ".config", "sclaude", "polkit-rule"))
        out = run(env, answer="n")
        check("unreadable-without-note-asks", "Add it now?" in out, True)
    finally:
        os.chmod(etc_dir, 0o755)

    print("--polkit")
    env, rule, calls = world(os.path.join(tmp, "flag"))
    out = run(env, "--polkit")
    check("flag-writes-without-asking",
          (os.path.exists(rule), "Add it now?" in out), (True, False))

    print("sclaude only")
    env, rule, calls = world(os.path.join(tmp, "core"))
    out = run(env, extras=False)
    bin_ = os.path.join(env["HOME"], ".local", "bin")
    units = os.path.join(env["HOME"], ".config", "systemd", "user")
    check("core-links-sclaude", os.path.islink(os.path.join(bin_, "sclaude")), True)
    check("core-enables-the-watch", "enable --now sclaude-watch.timer" in open(calls).read(), True)
    check("core-no-keepawake", os.path.lexists(os.path.join(bin_, "keepawake")), False)
    check("core-no-bot-unit", os.path.exists(os.path.join(units, "keepawake-telegram.service")), False)
    check("core-no-code-server", os.path.lexists(os.path.join(bin_, "code-server-start")), False)
    check("core-no-polkit-question", "polkit" in out, False)
    check("core-names-the-flag", "./install.sh --extras" in out, True)
    run(env)
    out = run(env, "--no-polkit", extras=False)
    check("extras-kept-on-a-plain-rerun",
          ("extras: kept" in out,
           os.path.exists(os.path.join(units, "keepawake-telegram.service"))), (True, True))

    print("no systemd")
    env, rule, calls = world(os.path.join(tmp, "nosystemd"), systemd=False)
    code = []
    out = run(env, extras=False, rc=code)
    check("nosystemd-says-so", "systemd's user manager does not answer" in out, True)
    check("nosystemd-names-the-fix", "re-run ./install.sh" in out, True)
    check("nosystemd-enables-nothing", "enable" in open(calls).read(), False)
    check("nosystemd-still-links", os.path.islink(os.path.join(env["HOME"], ".local", "bin", "sclaude")), True)
    check("nosystemd-exits-nonzero", code, [1])
    env["KEEPAWAKE_PLATFORM"] = "wsl"
    out = run(env, extras=False)
    check("nosystemd-wsl-names-wsl-conf", "systemd=true" in out and "wsl --shutdown" in out, True)

    print("code-server's local port")
    for name, bind, want in (("default", None, False),
                             ("loopback-8080", "127.0.0.1:8080", False),
                             ("tailnet", "100.64.0.1:8080", True)):
        env, rule, calls = world(os.path.join(tmp, "cs-" + name))
        cfg = os.path.join(env["HOME"], ".config", "code-server")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config.yaml"), "w") as fh:
            fh.write("password: x\n" + ("bind-addr: %s\n" % bind if bind else ""))
        run(env, "--no-polkit")
        check("code-server-%s-socket" % name,
              "enable --now code-server-local.socket" in open(calls).read(), want)

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
