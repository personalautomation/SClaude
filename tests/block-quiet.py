#!/usr/bin/env python3
#
# A deploy block's command shown short (sclaude/lib/ship/block_quiet.py, run
# by run_block in vercel.sh): its first lines, every line that says something
# failed and its last line on the screen, all of it in the log; the command
# on a terminal of its own; a question left without its newline shown at
# once; the command's own exit kept.
#
# Run it with: python3 tests/block-quiet.py
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
QUIET = os.path.join(ROOT, "sclaude", "lib", "ship", "block_quiet.py")
VERCEL = open(os.path.join(ROOT, "sclaude", "lib", "ship", "vercel.sh")).read()
DEPLOY = open(os.path.join(ROOT, "sclaude", "lib", "ship", "deploy.sh")).read()

failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s: got %r, want %r" % (name, got, want))


with tempfile.TemporaryDirectory() as tmp:
    log = os.path.join(tmp, "logs", "ship.log")
    script = "for i in $(seq 1 120); do echo \"  PASS check $i\"; done; " \
             "echo 'remote: error: one thing went wrong'; " \
             "for i in $(seq 121 130); do echo \"  PASS check $i\"; done; echo 'All checks passed.'"
    out = subprocess.run([sys.executable, QUIET, log, script], capture_output=True, text=True, timeout=30)
    lines = [l.rstrip("\r") for l in out.stdout.splitlines()]
    check("head-shown", lines[:2], ["  PASS check 1", "  PASS check 2"])
    check("failure-shown", "remote: error: one thing went wrong" in lines, True)
    check("middle-not-shown", "  PASS check 60" in lines, False)
    check("last-line-shown", "All checks passed." in lines, True)
    check("says-where-the-rest-is", lines[-1], "  … 122 line(s) not shown — the whole output: %s" % log)
    with open(log) as fh:
        whole = fh.read()
    check("all-in-the-log", ("  PASS check 60\n" in whole, whole.count("\n")), (True, 132))

    # With a terminal here, the command has one of its own, as it had
    # before, and Ctrl-C is not taken from it.
    def on_terminal(command):
        master, slave = os.openpty()
        try:
            return subprocess.run([sys.executable, QUIET, log, command], stdin=slave,
                                  capture_output=True, text=True, timeout=30).stdout
        finally:
            os.close(master)
            os.close(slave)
    check("command-sees-a-terminal", on_terminal("[ -t 1 ] && echo tty || echo pipe").strip(), "tty")
    check("ctrl-c-not-ignored-by-the-command", on_terminal("trap -p INT; echo end").strip(), "end")
    # Without one, the command reads the end of its input rather than wait.
    out = subprocess.run([sys.executable, QUIET, log, "[ -t 1 ] && echo tty || echo pipe; read -t 5 x; echo rc=$?"],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    check("no-terminal-piped-and-ends", out.stdout.split(), ["pipe", "rc=1"])

    # Short output is shown whole, with no note.
    out = subprocess.run([sys.executable, QUIET, log, "printf 'one\\ntwo\\n'"],
                         capture_output=True, text=True, timeout=30)
    check("short-whole", out.stdout.replace("\r", ""), "one\ntwo\n")

    # A question waiting without its newline reaches the screen at once.
    quiet = subprocess.Popen([sys.executable, QUIET, log, "printf 'Continue? [y/n] '; sleep 2; echo; echo done"],
                             stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
    import select
    ready, _, _ = select.select([quiet.stdout], [], [], 1.5)
    first = os.read(quiet.stdout.fileno(), 100) if ready else b""
    quiet.wait(timeout=10)
    check("prompt-shown-before-its-newline", first.startswith(b"Continue? [y/n]"), True)

    # Piped, an interrupt to the filter does not leave the command behind:
    # it reads on until the command ends.
    import signal as _signal
    import time as _time
    piped = subprocess.Popen([sys.executable, QUIET, log, "sleep 1; echo finished"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, text=True)
    _time.sleep(0.4)
    piped.send_signal(_signal.SIGINT)
    said, _ = piped.communicate(timeout=10)
    check("piped-waits-out-an-interrupt", (piped.returncode, "finished" in said), (0, True))

    # The rest of a question's line — an answer's Enter — reaches the screen
    # past the head too, so what follows is not glued to the question.
    long_q = "for i in $(seq 1 20); do echo l$i; done; printf 'Go? '; sleep 1; echo; echo 'error: after'"
    out = subprocess.run([sys.executable, QUIET, log, long_q], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=30)
    check("question-line-ended", "Go? \nerror: after\n" in out.stdout, True)

    # The command's exit is the filter's.
    rc = subprocess.run([sys.executable, QUIET, log, "echo x; exit 3"], capture_output=True, timeout=30).returncode
    check("exit-kept", rc, 3)

check("run-block-uses-it-but-not-for-cd",
      ('"$cmd" != cd\\ * ]]' in VERCEL, 'block_quiet.py" "$SCLAUDE_BLOCK_LOG" "$cmd"' in VERCEL), (True, True))
check("production-blocks-log", DEPLOY.count('SCLAUDE_BLOCK_LOG="$ship_log" run_block'), 2)

if failed:
    print("%d check(s) failed" % failed)
    sys.exit(1)
print("All checks passed.")
