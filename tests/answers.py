#!/usr/bin/env python3
#
# What a typed answer is taken for.
#
# Once "Merge origin/main into …? [y/N] n" merged, twice. A
# Cyrillic letter typed and erased with Backspace on a terminal without
# `iutf8` loses only its last byte; the first, \320 or \321, stayed in the
# line, invisible, and bash matched it against the first byte of "д" or "у" in
# is_yes: "\321n" was a yes.
#
# Guarded here:
#
#   * clean_reply drops bytes that are not UTF-8;
#   * only y, yes, n and no count, in any case — Cyrillic and other words
#     count as neither;
#   * typed in a real terminal — "т", Backspace, "n" — the answer is no;
#   * a yes/no question takes no default: an empty line, or a word that is
#     neither, is asked again; the end of input stops it with an empty reply;
#   * free text typed while the question also waits on the channel is edited
#     in place: the arrows move the cursor, a word typed after them lands
#     there, an arrow pressed before typing leaves nothing behind, a space
#     typed first is not Enter, a prompt wider than the terminal is not shown
#     twice, a feature ended while a line is half typed ends the wait, and an
#     answer from the channel still counts while nothing has been typed.
#
# Run it with: python3 tests/answers.py
import os
import pty
import select
import subprocess
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def verdict(raw):
    script = ('source "%s/ui.sh"; r="$(clean_reply "$1")"; '
              'is_yes "$r" && echo yes || { is_no "$r" && echo no || echo neither; }' % LIB)
    return subprocess.run(["bash", "-c", script, "_", raw], capture_output=True,
                          text=True, env=dict(os.environ, LANG="C.UTF-8")).stdout.strip()


for raw, want in [("\udcd1n", "no"), ("\udcd0n", "no"), ("\udcd0y", "yes"),
                  ("y", "yes"), ("n", "no"), ("Y", "yes"), ("N", "no"),
                  ("yes", "yes"), ("YeS", "yes"), ("no", "no"), ("NO", "no"),
                  ("", "neither"), ("yep", "neither"), ("nope", "neither"),
                  ("у", "neither"), ("н", "neither"), ("да", "neither"),
                  ("нет", "neither"), ("\x1b[?1;2cy", "yes")]:
    arg = raw.encode("utf-8", "surrogateescape").decode("utf-8", "surrogateescape")
    check("verdict-%r" % raw, verdict(arg), want)

# --- a yes/no question has no default ----------------------------------------
def asked(stdin):
    script = ('BOLD=""; OFF=""; source "%s/io.sh"; source "%s/ui.sh"; unset ASK_DIR; '
              'ask "Ship? [y/n] " answer yn; rc=$?; echo "[$answer] rc=$rc"' % (LIB, LIB))
    p = subprocess.run(["bash", "-c", script], input=stdin, capture_output=True,
                       text=True, timeout=10, start_new_session=True,
                       env=dict(os.environ, LANG="C.UTF-8"))
    return p.stdout.strip(), p.stderr.count("Answer y or n.")


check("empty-then-y", asked("\n\ny\n"), ("[y] rc=0", 2))
check("word-then-n", asked("maybe\nn\n"), ("[n] rc=0", 1))
check("empty-then-eof", asked("\n"), ("[] rc=1", 1))
check("eof-at-once", asked(""), ("[] rc=1", 0))

# --- typed into a terminal ---------------------------------------------------
script = ('BOLD=""; OFF=""; source "%s/io.sh"; source "%s/ui.sh"; unset ASK_DIR; '
          'stty -iutf8; ask "Merge? [y/n] " answer yn; '
          'is_yes "$answer" && echo VERDICT=yes || echo VERDICT=no' % (LIB, LIB))
pid, fd = pty.fork()
if pid == 0:
    os.environ["LANG"] = "C.UTF-8"
    os.execvp("bash", ["bash", "-c", script])
time.sleep(1)
for chunk in ("т".encode(), b"\x7f", b"n", b"\r"):
    os.write(fd, chunk)
    time.sleep(0.2)
out = b""
end = time.time() + 5
while time.time() < end:
    r, _, _ = select.select([fd], [], [], 0.3)
    if r:
        try:
            d = os.read(fd, 4000)
        except OSError:
            break
        if not d:
            break
        out += d
check("typed-erased-cyrillic-then-n", "VERDICT=no" in out.decode(errors="replace"), True)

# --- free text, typed while the channel is waiting too --------------------
def typed(keys, channel=None, prompt="What is wrong? ", cols=None, end_feature=False):
    """What ask hands back, and what the screen showed, for keys typed at a
    terminal with the channel open. end_feature ends the feature from outside
    after the keys, as the bot does."""
    import fcntl
    import json
    import shutil
    import struct
    import tempfile
    import termios
    d = tempfile.mkdtemp(prefix="sclaude-answers-")
    try:
        script = ('BOLD=$\'\\e[1m\'; OFF=$\'\\e[0m\'; source "%s/io.sh"; source "%s/ui.sh"; '
                  'ASK_DIR=%s; ASK_SLUG=demo; ASK_POLL=0.3; ask "${BOLD}%s${OFF}" said; '
                  'echo "SAID[$said]"' % (LIB, LIB, d, prompt))
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["LANG"] = "C.UTF-8"
            os.execvp("bash", ["bash", "-c", script])
        if cols:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, cols, 0, 0))
        channel_dir = os.path.join(d, "ask", "demo")
        time.sleep(1)
        if channel is not None:
            with open(os.path.join(channel_dir, "answer.json.tmp"), "w") as fh:
                json.dump({"reply": channel}, fh)
            os.replace(os.path.join(channel_dir, "answer.json.tmp"),
                       os.path.join(channel_dir, "answer.json"))
        for chunk in keys:
            os.write(fd, chunk)
            # Longer than a turn of the wait: the line must outlive its ends.
            time.sleep(0.5)
        if end_feature:
            open(os.path.join(channel_dir, "ended"), "w").close()
        out = b""
        end = time.time() + 6
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.3)
            if r:
                try:
                    data = os.read(fd, 4000)
                except OSError:
                    break
                if not data:
                    break
                out += data
        # Still there after the wait is a process stuck in a read: a failure
        # to report, not a bench to hang.
        if os.waitpid(pid, os.WNOHANG) == (0, 0):
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        text = out.decode(errors="replace")
        start = text.rfind("SAID[")
        said = text[start + 5:text.find("]", start)] if start >= 0 else None
        return said, text
    finally:
        shutil.rmtree(d, ignore_errors=True)


check("free-text-edited-with-the-arrows",
      typed([b"a", b"bc", b"\x1b[D\x1b[D", b"X", b"\r"])[0], "aXbc")
check("free-text-arrow-before-typing-leaves-nothing",
      typed([b"\x1b[D", b"ok", b"\r"])[0], "ok")
check("free-text-cyrillic", typed(["ж".encode(), "ук".encode(), b"\r"])[0], "жук")
check("free-text-empty-enter", typed([b"\r"])[0], "")
check("free-text-space-first-is-not-enter", typed([b" ", b"ok", b"\r"])[0], "ok")
check("free-text-from-the-channel", typed([], channel="from the phone")[0], "from the phone")
# A prompt wider than the terminal: every row it took is erased before
# readline prints it again, so its words are on the screen once.
wide = "What is not working, said in as many words as it takes to wrap? "
said, screen = typed([b"a", b"\r"], prompt=wide, cols=40)
check("free-text-wrapped-prompt-answer", said, "a")
check("free-text-wrapped-prompt-erased-upwards", "\x1b[1A" in screen, True)
# The feature ended from the bot while a line is half typed: the process says
# so and goes, rather than waiting in readline for ever.
said, screen = typed([b"half"], end_feature=True)
check("free-text-feature-ended-mid-line", (said, "has ended elsewhere" in screen), (None, True))

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
