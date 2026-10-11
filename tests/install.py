#!/usr/bin/env python3
#
# A bench for install.sh's one question: keepawake's polkit rule on plain Linux.
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


def world(tmp):
    home = os.path.join(tmp, "home")
    stubs = os.path.join(tmp, "stubs")
    etc = os.path.join(tmp, "etc", "polkit-1", "rules.d")
    for d in (home, stubs, etc):
        os.makedirs(d, exist_ok=True)
    calls = os.path.join(tmp, "systemctl.calls")
    for name, body in (
            ("systemctl", 'echo "$*" >> %s\nexit 0\n' % calls),
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


def run(env, *args, answer=None):
    """install.sh with stdin from a pipe, or from a terminal typing `answer`."""
    if answer is None:
        done = subprocess.run([INSTALL] + list(args), env=env, capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=120)
        return done.stdout + done.stderr
    primary, secondary = pty.openpty()
    proc = subprocess.Popen([INSTALL] + list(args), env=env, stdin=secondary,
                            stdout=secondary, stderr=secondary, close_fds=True)
    os.close(secondary)
    out = b""
    sent = False
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            chunk = os.read(primary, 4096)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if not sent and b"Add it now?" in out:
            os.write(primary, (answer + "\n").encode())
            sent = True
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

    print("--no-polkit")
    out = run(env, "--no-polkit")
    check("no-polkit-silent", "optional polkit rule" in out, False)
    check("no-polkit-writes-nothing", os.path.exists(rule), False)

    print("asked in a terminal")
    out = run(env, answer="")
    check("tty-undo-before-question",
          -1 < out.find("sudo rm %s" % rule) < out.find("Add it now?"), True)
    check("tty-enter-is-no", os.path.exists(rule), False)
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
        os.remove(os.path.join(env["HOME"], ".config", "instruments", "polkit-rule"))
        out = run(env, answer="")
        check("unreadable-without-note-asks", "Add it now?" in out, True)
    finally:
        os.chmod(etc_dir, 0o755)

    print("--polkit")
    env, rule, calls = world(os.path.join(tmp, "flag"))
    out = run(env, "--polkit")
    check("flag-writes-without-asking",
          (os.path.exists(rule), "Add it now?" in out), (True, False))

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
