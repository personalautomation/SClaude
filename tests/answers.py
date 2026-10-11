#!/usr/bin/env python3
#
# What a typed answer is taken for.
#
# On #143 in social, "Merge origin/main into …? [y/N] n" merged, twice. A
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
#     neither, is asked again; the end of input stops it with an empty reply.
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

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
