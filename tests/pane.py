#!/usr/bin/env python3
#
# Claude in a tab of its own, under Windows Terminal in WSL2.
#
# Guarded here, with stand-ins for wt.exe and claude:
#
#   * over ssh, in code-server, in a console that is not WSL's own, without a
#     terminal, or with SCLAUDE_PANE=off, claude runs in place; a WSL console
#     without $WT_SESSION still gets a tab;
#   * in a pane, claude gets the same arguments — a prompt with `;`, quotes and
#     newlines intact — the same working directory and the exported variables,
#     but not this login's WSL_INTEROP; its exit status comes back;
#   * a pane that never starts is given up on and claude runs in place, and a
#     pane starting after that does not run it a second time;
#   * Ctrl-C in sclaude ends the claude in the pane and sclaude carries on.
#   * in a recorded run (terminal.sh) a tab is not recorded, and a session in
#     place is marked off for the playback to cut, with nothing else changed.
#
# Run it with: python3 tests/pane.py
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


tmp = tempfile.mkdtemp()
try:
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    wt = os.path.join(tmp, "work dir")
    os.makedirs(wt)
    out = os.path.join(tmp, "claude.json")
    panes = os.path.join(tmp, "panes")

    def write(name, body):
        path = os.path.join(bin_dir, name)
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\n" + body)
        os.chmod(path, 0o755)

    # Records how it was called, and where, and exits as told.
    write("claude", r'''
[[ -t 0 ]] && export PANE_TEST_TTY=1
python3 - "$@" <<'PY'
import json, os, sys
with open(os.environ["PANE_TEST_OUT"], "w") as fh:
    json.dump({"argv": sys.argv[1:], "cwd": os.getcwd(),
               "foo": os.environ.get("PANE_TEST_FOO"),
               "interop": os.environ.get("WSL_INTEROP"),
               "tty": bool(os.environ.get("PANE_TEST_TTY"))}, fh)
PY
[[ -n "${PANE_TEST_SLEEP:-}" ]] && sleep "$PANE_TEST_SLEEP"
exit "${PANE_TEST_RC:-0}"
''')

    # Records the subcommand of each call (after `-w 0`), and starts the script after `--` as
    # a detached process with a bare environment, as Windows Terminal starting
    # a fresh wsl.exe would — late, or never, if told.
    write("wt.exe", r'''
echo "$3" >> "$PANE_TEST_PANES"
while [[ $# -gt 0 && "$1" != "--" ]]; do shift; done
shift
case "${PANE_TEST_WT:-start}" in
  never) exit 0 ;;
  late)  ( sleep 3; setsid env -i PATH=/usr/bin:/bin "$@" </dev/null >/dev/null 2>&1 ) & disown ;;
  *)     setsid env -i PATH=/usr/bin:/bin "$@" </dev/null >/dev/null 2>&1 & disown ;;
esac
exit 0
''')

    PROMPT = "Fix it; then say \"done\" — it's $HOME `x`\nsecond line"

    def run(extra_env=None, tty=True, interrupt_after=None):
        for f in (out, panes):
            if os.path.exists(f):
                os.remove(f)
        script = r'''
warn() { echo "WARN $*" >&2; }
info() { echo "INFO $*"; }
[[ -n "${PANE_TEST_PRELOAD:-}" ]] && source "$PANE_TEST_PRELOAD"
source "%s/pane.sh"
cd "%s"
claude_launch --session-id 0000 -n "demo/code" "$PANE_TEST_PROMPT"
echo "rc=$?"
''' % (LIB, wt)
        env = dict(os.environ,
                   PATH=bin_dir + os.pathsep + os.environ["PATH"],
                   PANE_TEST_OUT=out, PANE_TEST_PANES=panes,
                   PANE_TEST_PROMPT=PROMPT, PANE_TEST_FOO="a b;c",
                   WT_SESSION="test", WSL_DISTRO_NAME="Test",
                   WSL_INTEROP="/run/WSL/1_interop", TMPDIR=tmp)
        for name in ("SCLAUDE_PANE", "SSH_CONNECTION", "SSH_TTY", "TERM_PROGRAM"):
            env.pop(name, None)
        env.update(extra_env or {})
        env = {k: v for k, v in env.items() if v is not None}
        if not tty:
            p = subprocess.run(["bash", "-c", script], env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=60)
            return p.stdout
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe("bash", ["bash", "-c", script], env)
        text = b""
        start = time.time()
        sent = False
        while True:
            if interrupt_after and not sent and time.time() - start > interrupt_after:
                os.write(fd, b"\x03")
                sent = True
            try:
                r, _, _ = select.select([fd], [], [], 0.2)
                if r:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    text += chunk
            except OSError:
                break
            if time.time() - start > 60:
                os.kill(pid, signal.SIGKILL)
                break
        os.waitpid(pid, 0)
        return text.decode(errors="replace")

    def seen():
        if not os.path.exists(out):
            return None
        with open(out) as fh:
            return json.load(fh)

    def pane_count():
        if not os.path.exists(panes):
            return 0
        with open(panes) as fh:
            return len(fh.read().split())

    def pane_kinds():
        with open(panes) as fh:
            return fh.read().split()

    # --- in a pane: everything carried over, and the status back ---
    text = run({"PANE_TEST_RC": "7"})
    got = seen() or {}
    check("pane-opened", pane_count(), 1)
    # A tab of its own, not a split of the tab sclaude runs in.
    check("pane-is-tab", pane_kinds(), ["new-tab"])
    check("pane-argv", got.get("argv"), ["--session-id", "0000", "-n", "demo/code", PROMPT])
    check("pane-cwd", got.get("cwd"), wt)
    check("pane-env", got.get("foo"), "a b;c")
    check("pane-no-interop", got.get("interop"), None)
    check("pane-status", "rc=7" in text, True)
    check("pane-says-where", "in a new tab" in text, True)
    check("pane-cleaned-up", [n for n in os.listdir(tmp) if n.startswith("sclaude-pane.")], [])

    # --- a recorded run: the tab is not recorded, a session in place is
    # marked off ---
    run_log = os.path.join(tmp, "run.log")
    recorded = {"SCLAUDE_TERM": run_log,
                "PANE_TEST_PRELOAD": os.path.join(LIB, "terminal.sh")}
    text = run(dict(recorded, PANE_TEST_RC="4"))
    got = seen() or {}
    check("recorded-argv", got.get("argv"), ["--session-id", "0000", "-n", "demo/code", PROMPT])
    check("recorded-status", "rc=4" in text, True)
    check("recorded-no-tab-log", [n for n in os.listdir(tmp) if n.endswith(".log")], [])
    check("recorded-tab-unmarked", "sclaude-skip" in text, False)
    text = run(dict(recorded, PANE_TEST_RC="6", WT_SESSION=None,
                    SSH_CONNECTION="1.2.3.4 5 6.7.8.9 22"))
    got = seen() or {}
    check("recorded-here-argv", got.get("argv"), ["--session-id", "0000", "-n", "demo/code", PROMPT])
    check("recorded-here-status", "rc=6" in text, True)
    check("recorded-here-marked", "sclaude-skip;begin;0000" in text and "sclaude-skip;end" in text, True)

    # --- a tab without $WT_SESSION: a WSL console Windows Terminal took over ---
    text = run({"PANE_TEST_RC": "5", "WT_SESSION": None})
    check("no-wt-local-tab", pane_count(), 1)
    check("no-wt-local-status", "rc=5" in text, True)

    # --- in place: ssh, code-server, not a WSL console, no terminal, or off ---
    for name, env, tty in (("ssh", {"WT_SESSION": None, "SSH_CONNECTION": "1.2.3.4 5 6.7.8.9 22"}, True),
                           ("ssh-tty", {"WT_SESSION": None, "SSH_TTY": "/dev/pts/3"}, True),
                           ("code-server", {"WT_SESSION": None, "TERM_PROGRAM": "vscode"}, True),
                           ("no-interop", {"WT_SESSION": None, "WSL_INTEROP": None}, True),
                           ("no-tty", {}, False),
                           ("off", {"SCLAUDE_PANE": "off"}, True)):
        text = run(dict(env, PANE_TEST_RC="3"), tty=tty)
        got = seen() or {}
        check("%s-no-pane" % name, pane_count(), 0)
        check("%s-ran" % name, got.get("argv", [None])[-1:], [PROMPT])
        if "WSL_INTEROP" not in env:
            check("%s-interop-kept" % name, got.get("interop"), "/run/WSL/1_interop")
        check("%s-status" % name, "rc=3" in text, True)

    # --- a pane that never starts: in place after the wait ---
    text = run({"PANE_TEST_WT": "never", "SCLAUDE_PANE_WAIT": "1"})
    got = seen() or {}
    check("never-ran-in-place", got.get("tty"), True)
    check("never-warned", "did not start" in text, True)

    # --- a pane that starts after sclaude gave up runs nothing ---
    text = run({"PANE_TEST_WT": "late", "SCLAUDE_PANE_WAIT": "1"})
    os.remove(out)
    time.sleep(4)
    check("late-pane-runs-nothing", seen(), None)

    # --- Ctrl-C in sclaude ends the session in the pane, sclaude goes on ---
    t0 = time.time()
    text = run({"PANE_TEST_SLEEP": "30"}, interrupt_after=3)
    check("ctrl-c-ends-the-session", time.time() - t0 < 15, True)
    check("ctrl-c-sclaude-goes-on", "rc=" in text, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
