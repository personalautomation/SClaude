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
#   * the focus keeper (pane-focus.ps1) is started, and heard from, before
#     wt.exe opens the tab, and not at all with SCLAUDE_PANE_FOCUS=follow;
#     the script itself, which needs a Windows desktop, is not run here. It
#     does not get the terminal as its stdin, is told the time it has left, and one
#     never ready is stopped.
#   * in a recorded run (terminal.sh) a tab is not recorded, and a session in
#     place is marked off for the playback to cut, with nothing else changed.
#
# Run it with: python3 tests/pane.py
import json
import os
import pty
import re
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
[[ -n "${PANE_TEST_STDERR:-}" ]] && echo "$PANE_TEST_STDERR" >&2
# A child left running with claude's stderr, as an MCP server may be.
[[ -n "${PANE_TEST_CHILD:-}" ]] && { sleep 30 & }
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

    # The focus keeper: notes that it ran and whether the tab was open by then,
    # and says it is ready, as pane-focus.ps1 does. Always stood in for, so
    # that no run here reaches the real desktop.
    focus = os.path.join(tmp, "focus")
    write("powershell.exe", r'''
[[ -s "$PANE_TEST_PANES" ]] && echo after >> "$PANE_TEST_FOCUS" || echo before >> "$PANE_TEST_FOCUS"
[[ -t 0 ]] && echo stdin-tty >> "$PANE_TEST_FOCUS"
# The script opens with the time it has left, a little under seven seconds.
while [[ $# -gt 0 && "$1" != "-EncodedCommand" ]]; do shift; done
first="$(base64 -d <<< "$2" | iconv -f UTF-16LE -t UTF-8 | head -1)"
left=${first#\$budget = }
[[ "$left" =~ ^[0-9]+$ ]] && (( left > 4000 && left <= 7000 )) || echo "bad-budget:$first" >> "$PANE_TEST_FOCUS"
if [[ -n "${PANE_TEST_FOCUS_SILENT:-}" ]]; then
  echo $$ > "$PANE_TEST_FOCUS.pid"
  sleep 30
fi
echo ready
''')

    PROMPT = "Fix it; then say \"done\" — it's $HOME `x`\nsecond line"

    # What the tab wait draws once a second and after every key it takes
    # (session_keys_line in pane.sh).
    STATUS_LINE = b"The session works in its tab"
    # Said once the tab is up and its wait about to begin (claude_launch).
    TAB_UP = b"claude is running in a new tab"
    # When run() last sent its Ctrl-C, and when the script went on after the
    # session (its `rc=` line).
    interrupted_at = [None]
    went_on_at = [None]

    def run(extra_env=None, tty=True, interrupt_after=None, keys_at=None, keys_after=None):
        """`keys_after`: the keys' seconds count from when these bytes first
        show, not from the start — under the whole suite's load a session
        may take seconds to come up, and a key sent before it reads keys is
        lost."""
        for f in (out, panes, focus):
            if os.path.exists(f):
                os.remove(f)
        script = r'''
warn() { echo "WARN $*" >&2; }
info() { echo "INFO $*"; }
[[ -n "${PANE_TEST_PRELOAD:-}" ]] && source "$PANE_TEST_PRELOAD"
source "%s/core/steps.sh"
source "%s/core/pane.sh"
cd "%s"
( claude_launch --session-id 0000 -n "demo/code" "$PANE_TEST_PROMPT" )
echo "rc=$?"
( pane_marked 0000 ) && echo "in-pane=[1]" || echo "in-pane=[]"
''' % (LIB, LIB, wt)
        env = dict(os.environ,
                   PATH=bin_dir + os.pathsep + os.environ["PATH"],
                   PANE_TEST_OUT=out, PANE_TEST_PANES=panes, PANE_TEST_FOCUS=focus,
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
            # Ctrl-C as at a person's terminal: a bench started as a background
            # job (`python3 tests/pane.py &`) inherits SIGINT ignored, and bash
            # cannot trap a signal ignored when it starts.
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.execvpe("bash", ["bash", "-c", script], env)
        text = b""
        start = time.time()
        sent = False
        # One (seconds, bytes) pair, or a list of them, sent in order.
        keys = list(keys_at) if keys_at and isinstance(keys_at, list) else ([keys_at] if keys_at else [])
        # A key is sent only once the one before it has been taken: the wait
        # reads a key and then swallows whatever else is waiting (poll_pause,
        # so that an arrow or a stray word answers nothing), and a second key
        # sent while the loop lagged under the suite's load went with it. Two
        # status lines drawn since the last key mean it was read: the first
        # may be the draw that was under way, the second follows the read.
        drawn_at_send = None
        while True:
            # interrupt_after: seconds from the start, or (bytes, seconds) — from
            # when those bytes show, as for keys_after.
            if isinstance(interrupt_after, tuple) and interrupt_after[0] in text:
                interrupt_after = time.time() - start + interrupt_after[1]
            if (isinstance(interrupt_after, (int, float)) and not sent
                    and time.time() - start > interrupt_after):
                os.write(fd, b"\x03")
                sent = True
                interrupted_at[0] = time.time()
            if keys_after and isinstance(keys_after, bytes) and keys_after in text:
                keys_after = time.time()
            base = keys_after if isinstance(keys_after, float) else (None if keys_after else start)
            taken = drawn_at_send is None or text.count(STATUS_LINE) >= drawn_at_send + 2
            if keys and base is not None and taken and time.time() - base > keys[0][0]:
                os.write(fd, keys.pop(0)[1])
                drawn_at_send = text.count(STATUS_LINE)
            try:
                r, _, _ = select.select([fd], [], [], 0.2)
                if r:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    text += chunk
                    if went_on_at[0] is None and b"rc=" in text:
                        went_on_at[0] = time.time()
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
    # The tab closed with the session's last message: session_ended prints it.
    check("pane-marked", "in-pane=[1]" in text, True)
    check("focus-kept-before-the-tab", open(focus).read().split() if os.path.exists(focus) else None, ["before"])
    check("pane-cleaned-up", [n for n in os.listdir(tmp) if n.startswith("sclaude-pane.")], [])

    # --- a keeper never ready is stopped, not left to act on a later tab ---
    began = time.time()
    text = run({"PANE_TEST_FOCUS_SILENT": "1"})
    check("silent-keeper-tab-opened", (pane_count(), "rc=0" in text), (1, True))
    check("silent-keeper-gave-up", 9 < time.time() - began < 25, True)
    keeper_pid = int(open(focus + ".pid").read()) if os.path.exists(focus + ".pid") else None
    time.sleep(0.5)
    check("silent-keeper-stopped", keeper_pid is not None and not os.path.exists("/proc/%d" % keeper_pid), True)

    # --- SCLAUDE_PANE_FOCUS=follow: the new tab keeps the focus ---
    text = run({"SCLAUDE_PANE_FOCUS": "follow"})
    check("follow-tab-opened", pane_count(), 1)
    check("follow-no-keeper", os.path.exists(focus), False)

    # --- in a feature's tree: what claude said and how it left, kept there ---
    feature = os.path.join(wt, ".sclaude", "local", "feature")
    os.makedirs(feature, exist_ok=True)
    text = run({"PANE_TEST_RC": "7", "PANE_TEST_STDERR": "Error: session in use"})
    check("logged-status", "rc=7" in text, True)
    deadline = time.time() + 5
    tab_log = os.path.join(feature, "claude-tab.log")

    def tab_lines():
        return open(tab_log).read().splitlines() if os.path.exists(tab_log) else []

    while len(tab_lines()) < 3 and time.time() < deadline:
        time.sleep(0.1)
    logged = tab_lines()
    # What claude said comes before the exit line when the tee keeps up: the
    # tab waits for it two seconds and no longer (a child claude left may hold
    # its stderr for good), so under a heavy load it can land after, and the
    # order is not what is checked here.
    exit_line = [l for l in logged if l.endswith(" exit 7")]
    check("tab-log-shape", (len(logged), logged[0].endswith(" demo/code started") if logged else None,
                            "Error: session in use" in logged, len(exit_line)),
          (3, True, True, 1))
    # A child holding claude's stderr does not hold the launch: the tee is
    # waited for a moment, not until the child is gone.
    began = time.time()
    text = run({"PANE_TEST_RC": "0", "PANE_TEST_CHILD": "1"})
    check("child-does-not-hold-the-launch", ("rc=0" in text, time.time() - began < 15), (True, True))
    shutil.rmtree(os.path.join(wt, ".sclaude"))

    # --- a recorded run: the tab is not recorded, a session in place is
    # marked off ---
    run_log = os.path.join(tmp, "run.log")
    recorded = {"SCLAUDE_TERM": run_log,
                "PANE_TEST_PRELOAD": os.path.join(LIB, "core", "terminal.sh")}
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
        check("%s-not-marked" % name, "in-pane=[]" in text, True)

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
    # Sent once the wait has begun, and timed from the Ctrl-C to the script
    # going on (its rc= line): the tab's own start, slow under the suite's
    # load, is not what is measured.
    went_on_at[0] = None
    text = run({"PANE_TEST_SLEEP": "30"}, interrupt_after=(TAB_UP, 1))
    check("ctrl-c-ends-the-session",
          None not in (interrupted_at[0], went_on_at[0])
          and went_on_at[0] - interrupted_at[0] < 15, True)
    check("ctrl-c-sclaude-goes-on", "rc=" in text, True)

    # --- the caller's keys while the session runs in its tab (PANE_KEYS): this
    # terminal is free, and each second's key is handed on, empty after none.
    probe = os.path.join(tmp, "keys.sh")
    pressed = os.path.join(tmp, "pressed")
    with open(probe, "w") as fh:
        # It says on the screen that it was called, so the key goes once the
        # wait takes keys rather than at a guess.
        fh.write('source "%s/core/ui.sh"\nPANE_KEYS=(keys_probe)\n'
                 'keys_probe() { echo "[$1]" >> "%s"; printf "probed " >&2; }\n' % (LIB, pressed))
    text = run({"PANE_TEST_SLEEP": "10", "PANE_TEST_PRELOAD": probe}, keys_at=(0.3, b"g"),
               keys_after=b"probed")
    with open(pressed) as fh:
        took = fh.read().split()
    check("pane-keys-handed-on", "[g]" in took, True)
    check("pane-keys-every-second", took.count("[]") >= 1, True)

    # --- the session's own keys (session_keys): [r] twice reopens the same
    # conversation without a message, a single press does nothing, and the
    # keys that need a watcher are offered only with one. The stand-in
    # records every launch.
    launches = os.path.join(tmp, "launches")
    write("claude", r'''
echo "$*" | tr '\n' ' ' >> "$PANE_TEST_LAUNCHES"; echo >> "$PANE_TEST_LAUNCHES"
sleep "${PANE_TEST_SLEEP:-0}"
''')
    ctl = os.path.join(tmp, "sclaude-ctl-0000")

    def launched():
        if not os.path.exists(launches):
            return []
        with open(launches) as fh:
            return fh.read().splitlines()

    for f in (launches, ctl):
        if os.path.exists(f):
            os.remove(f)
    plain = os.path.join(tmp, "plain.sh")
    with open(plain, "w") as fh:
        fh.write('source "%s/core/ui.sh"\n' % LIB)
    # Room for both presses: each key waits for the one before to be taken,
    # which under the suite's load can take a few seconds.
    text = run({"PANE_TEST_SLEEP": "12", "PANE_TEST_LAUNCHES": launches, "PANE_TEST_PRELOAD": plain},
               keys_at=[(0.5, b"r"), (1.1, b"r")], keys_after=b"Keys here")
    got = launched()
    check("r-twice-reopens", len(got) >= 2, True)
    check("r-first-launch", got[:1], ["--session-id 0000 -n demo/code " + PROMPT.replace("\n", " ") + " "])
    # Reopened silently: --resume, the name, and no prompt after it.
    check("r-reopens-silently", got[1:2], ["--resume 0000 -n demo/code "])
    check("tab-line-says-which-session",
          "· new session." in text and "· same session, resumed." in text, True)
    check("r-word-taken", os.path.exists(ctl), False)
    check("r-said", "Reopening the same conversation" in text, True)
    check("keys-legend", "Keys here, each pressed twice:" in text and "[r] reopen" in text, True)
    # No watcher: [n], [N], [R] and [k] are not offered.
    check("keys-legend-without-watcher",
          any(k in text for k in ("[n]", "[N]", "[R]", "[k]")), False)

    os.remove(launches)
    # The press is said on the status line, drawn once a second: room for
    # several draws after it, under the load of the whole suite.
    text = run({"PANE_TEST_SLEEP": "7", "PANE_TEST_LAUNCHES": launches, "PANE_TEST_PRELOAD": plain},
               keys_at=[(0.5, b"r")], keys_after=b"Keys here")
    check("r-once-does-nothing", len(launched()), 1)
    check("r-once-asks-again", "[r] reopen — press r again to finish" in text, True)

    # Under a watcher: [k] twice toggles the keep word; n then N arm two
    # different keys and do nothing; [R] twice ends it and leaves its word.
    os.remove(launches)
    step = os.path.join(tmp, "step.sh")
    with open(step, "w") as fh:
        # A live watcher: its kind and a pid that runs (this script's own).
        fh.write('source "%s/core/ui.sh"\necho "plan $$" > "%s/sclaude-watch-0000"\n' % (LIB, tmp))
    # Six keys, each sent once the one before was taken: room for all of them
    # before the stand-in ends on its own. [R] twice ends it sooner.
    text = run({"PANE_TEST_SLEEP": "20", "PANE_TEST_LAUNCHES": launches, "PANE_TEST_PRELOAD": step},
               keys_at=[(0.5, b"k"), (1.0, b"k"), (1.5, b"n"), (2.0, b"N"), (2.5, b"R"), (3.0, b"R")], keys_after=b"Keys here")
    check("R-ends-it-once", len(launched()), 1)
    with open(ctl) as fh:
        check("R-leaves-its-word", fh.read().strip(), "later")
    check("watched-legend", "[N] next, not now" in text and "[R] reopen, not now" in text, True)
    # [k] is a box on the status line, ticked by two presses: no line of words.
    check("k-twice-ticks-its-box", "☑ [k] kept open" in text and "[k] on:" not in text, True)
    check("case-is-another-key", "press N again to finish" in text, True)
    # A status line never wraps: a wrapped one is drawn again under itself
    # every second.
    with open(os.path.join(LIB, "core", "pane.sh")) as fh:
        check("status-line-does-not-wrap", "\\033[?7l" in fh.read(), True)
    os.remove(ctl)
    os.remove(os.path.join(tmp, "sclaude-watch-0000"))

    # --- a --resume goes to where the conversation went on --------------------
    # Claude Code may carry a conversation on under a new id and hide the old
    # one as superseded; the launch resumes the new one, and only a --resume.
    home = os.path.join(tmp, "home")
    tdir = os.path.join(home, ".claude", "projects", re.sub(r"[^a-zA-Z0-9]", "-", wt))
    os.makedirs(tdir, exist_ok=True)
    with open(os.path.join(tdir, "old.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "continued-in", "continuedInSessionId": "new"}) + "\n")
    open(os.path.join(tdir, "new.jsonl"), "w").close()
    script = ('source "%s/core/state.sh"; source "%s/core/pane.sh"; cd "%s"; HOME="%s"\n'
              'resume_latest --resume old -n old "--resume"; echo "${CLAUDE_LATEST[*]}"\n'
              'resume_latest --session-id old -n x; echo "${CLAUDE_LATEST[*]}"\n'
              'resume_latest --resume other; echo "${CLAUDE_LATEST[*]}"\n') % (LIB, LIB, wt, home)
    got = subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout.splitlines()
    check("resume-goes-to-the-continuation", got,
          ["--resume new -n old --resume", "--session-id old -n x", "--resume other"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# How the last run in a tab ended, for a session that left at once: the tab
# closed with it, and only its log saw what it printed.
tmp = tempfile.mkdtemp()
try:
    wt = os.path.join(tmp, "wt")
    os.makedirs(os.path.join(wt, ".sclaude", "local", "feature"))
    log = os.path.join(wt, ".sclaude", "local", "feature", "claude-tab.log")

    def last_exit(text):
        with open(log, "w") as fh:
            fh.write(text)
        script = 'source "%s/core/pane.sh"; pane_last_exit "%s"' % (LIB, wt)
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True).stdout.splitlines()

    earlier = ("=== 2026-01-01T10:00:00+00:00 1-plan/x started\n"
               "an old complaint\n"
               "=== 2026-01-01T10:20:00+00:00 exit 143\n")
    check("tab-exit-interrupted", last_exit(
        earlier + "=== 2026-01-02T09:00:00+00:00 3-pr/x started\n"
                  "=== 2026-01-02T09:00:01+00:00 exit 130\n"), ["130"])
    check("tab-exit-with-its-words", last_exit(
        earlier + "=== 2026-01-02T09:00:00+00:00 3-pr/x started\n"
                  "Error: no such session\n\n"
                  "=== 2026-01-02T09:00:01+00:00 exit 1\n"), ["1", "Error: no such session"])
    check("tab-exit-still-running", last_exit(
        earlier + "=== 2026-01-02T09:00:00+00:00 3-pr/x started\n"), [])
    check("tab-exit-no-log", last_exit(""), [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
