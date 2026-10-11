#!/usr/bin/env python3
#
# The terminal recording (sclaude/lib/terminal.sh) and its playback
# (term_render.py).
#
# Guarded here:
#
#   * a run at a terminal is recorded, keeps its arguments and its exit status,
#     and records once — a re-executed run goes on in the same file;
#   * no terminal, or SCLAUDE_TERM=off, records nothing;
#   * a feature lists each run once, and only while a run is recorded;
#   * playback gives the text a terminal would hold: a line redrawn in place
#     is one line, the scrollback survives a clear of it, a Claude session
#     that ran in place is one line naming it, and a feature's runs come out
#     in the order they started, each under a heading.
#
# Run it with: python3 tests/terminal.py
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


def in_pty(argv, env, timeout=30):
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(argv[0], argv, env)
    text = b""
    start = time.time()
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                text += chunk
        except OSError:
            break
        if time.time() - start > timeout:
            os.kill(pid, signal.SIGKILL)
            break
    _, status = os.waitpid(pid, 0)
    return text.decode(errors="replace"), os.waitstatus_to_exitcode(status)


tmp = tempfile.mkdtemp()
# Outside any repository: inside one the recording goes to its .sclaude folder
# rather than the HOME below, and this bench would write into the real tree.
os.chdir(tmp)
try:
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    term_dir = os.path.join(home, ".claude", "sclaude", "terminal")

    # A stand-in for sclaude: records, re-executes itself once as an update
    # would, and prints what it was given.
    prog = os.path.join(tmp, "prog")
    with open(prog, "w") as fh:
        fh.write(r'''#!/usr/bin/env bash
source "%s/terminal.sh"
term_record "$@"
if [[ -z "${AGAIN:-}" ]]; then export AGAIN=1; exec "$0" "$@"; fi
echo "args=[$1][$2] rec=${SCLAUDE_TERM:-none}"
exit 5
''' % LIB)
    os.chmod(prog, 0o755)

    env = dict(os.environ, HOME=home)
    env.pop("SCLAUDE_TERM", None)

    def recordings():
        if not os.path.isdir(term_dir):
            return []
        return sorted(os.listdir(term_dir))

    # --- at a terminal: recorded, arguments and exit status intact ---
    # An old recording left readable, from before the directory was closed.
    os.makedirs(term_dir)
    os.chmod(term_dir, 0o755)
    old_rec = os.path.join(term_dir, "00000000-000000-1.log")
    with open(old_rec, "w") as fh:
        fh.write("old\n")
    os.chmod(old_rec, 0o644)
    was = os.umask(0o022)
    try:
        text, rc = in_pty([prog, "a b", "c'd"], env)
    finally:
        os.umask(was)
    check("tty-dir-private", oct(os.stat(term_dir).st_mode & 0o777), "0o700")
    check("tty-old-closed", oct(os.stat(old_rec).st_mode & 0o777), "0o600")
    os.remove(old_rec)
    for name in recordings():
        check("tty-recording-private", oct(os.stat(os.path.join(term_dir, name)).st_mode & 0o777), "0o600")
    check("tty-status", rc, 5)
    check("tty-args", "args=[a b][c'd]" in text, True)
    check("tty-one-recording", len(recordings()), 1)
    if recordings():
        with open(os.path.join(term_dir, recordings()[0]), errors="replace") as fh:
            body = fh.read()
        check("tty-recorded-output", "args=[a b][c'd]" in body, True)
        check("tty-names-itself", "rec=" + os.path.join(term_dir, recordings()[0]) in text, True)

    # --- $SHELL is not bash: the arguments still arrive whole ---
    # script hands its command to $SHELL; dash, like fish, reads none of the
    # $'...' quoting bash's printf %q writes for a newline.
    shutil.rmtree(term_dir, ignore_errors=True)
    text, rc = in_pty([prog, "x\ny", "it's"], dict(env, SHELL="/bin/sh"))
    check("sh-status", rc, 5)
    check("sh-args", "args=[x\r\ny][it's]" in text, True)
    check("sh-launcher-gone", [n for n in os.listdir(os.environ.get("TMPDIR", "/tmp"))
                               if n.startswith("sclaude-term.")], [])

    # --- no terminal, or switched off: nothing recorded ---
    shutil.rmtree(term_dir, ignore_errors=True)
    p = subprocess.run([prog, "x"], env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=30)
    check("no-tty-status", p.returncode, 5)
    check("no-tty-unrecorded", "rec=none" in p.stdout, True)
    text, rc = in_pty([prog, "x"], dict(env, SCLAUDE_TERM="off"))
    check("off-status", rc, 5)
    check("off-unrecorded", recordings(), [])

    # --- a feature lists each run once ---
    wt = os.path.join(tmp, "wt")
    os.makedirs(os.path.join(wt, ".feature"))
    script = r'''
source "%s/terminal.sh"
SCLAUDE_TERM=/r/one.log term_attach "%s"
SCLAUDE_TERM=/r/one.log term_attach "%s"
SCLAUDE_TERM=/r/two.log term_attach "%s"
SCLAUDE_TERM=off term_attach "%s"
SCLAUDE_TERM= term_attach "%s"
''' % ((LIB,) + (wt,) * 5)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    with open(os.path.join(wt, ".feature", "terminal")) as fh:
        check("attach-once-each", fh.read().split(), ["/r/one.log", "/r/two.log"])

    # --- the marks around a session in place: only in a recorded run ---
    marks = r'''
source "%s/terminal.sh"
SCLAUDE_TERM=/r/x.log term_skip begin --model opus --session-id 0123abcd-ef "the prompt"
echo
SCLAUDE_TERM=/r/x.log term_skip end
echo
SCLAUDE_TERM=off term_skip begin --session-id 0123
''' % LIB
    text, _ = in_pty(["bash", "-c", marks], env)
    check("marks-begin", "\x1b]7771;sclaude-skip;begin;0123abcd-ef\x07" in text, True)
    check("marks-end", "\x1b]7771;sclaude-skip;end\x07" in text, True)
    check("marks-off", text.count("sclaude-skip"), 2)
    p = subprocess.run(["bash", "-c", marks], capture_output=True, text=True, timeout=30)
    check("marks-not-to-a-pipe", "sclaude-skip" in p.stdout, False)

    # --- playback ---
    rec = os.path.join(tmp, "rec")
    os.makedirs(rec)
    run = os.path.join(rec, "20261009-100000-1.log")
    later = os.path.join(rec, "20261009-100500-2.log")

    def recording(path, started, body):
        with open(path, "wb") as fh:
            fh.write(('Script started on %s [COMMAND="x" TERM="xterm" TTY="/dev/pts/1" '
                      'COLUMNS="80" LINES="10"]\n' % started).encode())
            fh.write(body)
            fh.write(b'\nScript done on %s [COMMAND_EXIT_CODE="0"]\n' % started.encode())

    lines = b"".join(b"line %d\r\n" % i for i in range(1, 31))
    recording(run, "2026-10-09 10:00:00+01:00",
              b"start\r\n" + lines + b"spin 1\r\x1b[Kspin 2\r\x1b[Kspin done\r\n"
              b"\x1b[3J\x1b[?1049halt screen\r\n\x1b[?1049l"
              b"\x1b]7771;sclaude-skip;begin;0123abcd-ef\x07\x1b[2Jsession screen\r\n"
              b"\x1b]7771;sclaude-skip;end\x07the end\r\n")
    recording(later, "2026-10-09 10:05:00+01:00",
              b"second run\r\n\x1b]7771;sclaude-skip;begin;99\x07still running\r\n")
    with open(os.path.join(wt, ".feature", "terminal"), "w") as fh:
        fh.write(later + "\n" + run + "\n" + os.path.join(rec, "gone.log") + "\n")
    script = r'''
LIB="%s"
source "$LIB/terminal.sh"
term_render "%s"
''' % (LIB, wt)
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    out = os.path.join(wt, ".feature", "terminal.txt")
    check("render-prints-path", p.stdout.strip(), out)
    text = open(out).read() if os.path.exists(out) else ""
    check("render-scrollback-kept", "line 1\n" in text and "start\n" in text, True)
    check("render-redraw-is-one-line", "spin done" in text and "spin 1" not in text, True)
    check("render-alt-screen-kept", "alt screen" in text, True)
    check("render-session-cut", "session screen" in text, False)
    check("render-session-named", "in this window: 0123abcd-ef;" in text, True)
    check("render-after-session", "the end" in text and "line 30" in text, True)
    check("render-open-session-cut", "still running" in text, False)
    check("render-in-order", 0 <= text.find("the end") < text.find("second run"), True)
    check("render-two-headings", text.count("sclaude · started"), 2)
    check("render-no-script-lines", "Script started" in text or "Script done" in text, False)

    open(os.path.join(wt, ".feature", "terminal"), "w").close()
    p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    check("render-nothing", p.returncode, 1)

    # --- the retrospective runs once per feature ---
    def retro(state):
        with open(os.path.join(wt, ".feature", "state.json"), "w") as fh:
            fh.write(state)
        script = r'''
PROMPTS="%s/../prompts"
info() { echo "INFO $*"; }
term_render() { echo "RENDERED" > /dev/tty; }
render_prompt() { return 1; }
new_session_id() { echo 0; }
transcript_dir() { echo /t; }
source "%s/retro.sh"
run_retro "%s" demo 7 3
echo "rc=$?"
''' % (LIB, LIB, wt)
        return in_pty(["bash", "-c", script], env)[0]

    text = retro('{"retro": {"runs": [{"session": "a", "done": true}]}}')
    check("retro-once-skips", "RENDERED" in text, False)
    check("retro-once-says-so", "already took place" in text, True)
    check("retro-once-rc", "rc=0" in text, True)
    # Dropped or cut off: no finished run, so it goes ahead (and reaches the
    # render, the first thing past the check).
    text = retro('{"retro": {"runs": [{"session": "a"}]}}')
    check("retro-unfinished-runs", "RENDERED" in text, True)
    check("retro-unfinished-not-skipped", "already took place" in text, False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- where a project's runs are recorded (term_dir, scratch_hide) ---
proj = tempfile.mkdtemp()
try:
    subprocess.run(["git", "init", "-q", proj], check=True)
    sub = os.path.join(proj, "app")
    os.makedirs(sub)

    def where(cwd, home="/h"):
        script = 'HOME=%s; source "%s/terminal.sh"; term_dir' % (home, LIB)
        return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True,
                              text=True).stdout.strip()

    # Nothing to configure: always sclaude's folder in the main repository,
    # from any directory in it, and the home directory outside one.
    check("dir-in-the-repository", where(sub), os.path.join(proj, ".sclaude", "terminal"))
    check("dir-outside-a-repo", where(tempfile.gettempdir()), "/h/.claude/sclaude/terminal")

    rec = os.path.join(proj, ".sclaude", "terminal")
    script = ('source "%s/terminal.sh"; source "%s/scratch.sh"; scratch_hide; scratch_hide; '
              'mkdir -p "%s"; touch "%s/r.log"' % (LIB, LIB, rec, rec))
    subprocess.run(["bash", "-c", script], cwd=sub, check=True)
    with open(os.path.join(proj, ".git", "info", "exclude")) as fh:
        check("exclude-once", fh.read().splitlines().count(".sclaude"), 1)
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=proj,
                            capture_output=True, text=True).stdout
    check("exclude-hides-recordings", ".sclaude" in status, False)
finally:
    shutil.rmtree(proj, ignore_errors=True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
