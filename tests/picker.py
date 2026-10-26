#!/usr/bin/env python3
#
# A test bench for choosing with arrow keys: pick_list from
# sclaude/lib/picker.sh.
#
# One thing is checked — the cursor's movement — and not because the rest does
# not matter but because this is where things have already broken. The list of
# actions on a feature contains a separator before "drop the feature"; the cursor
# would stand on it and could not draw itself on a blank line: to the eye the
# list froze, and "drop the feature" looked unreachable. The failure is invisible
# — no exit code, no message — so the only way to catch it is like this, by
# really pressing keys.
#
# Through a real pty rather than by reading the function with one's eyes:
# pick_list reads /dev/tty and draws to /dev/tty, and without a terminal nothing
# of it is left.
#
# Run it with: python3 tests/picker.py
import os
import pty
import re
import select
import struct
import sys
import termios
import fcntl
import time

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

KEYS = {"D": b"\x1b[B", "U": b"\x1b[A", "S": b" ", "E": b"\r", "Q": b"q"}


def drive(rows, keys, height=24):
    """Runs pick_list over the rows, pressing keys. Returns (output, code).

    The rows are "label<TAB>hint", as pick_list accepts them. A blank line means
    a separator.
    """
    script = (
        'BOLD=""; DIM=""; GREEN=""; OFF=""\n'
        'source "%s/picker.sh"\n'
        'out="$(pick_list "Title" %s)"; rc=$?\n'
        'printf "RESULT=%%s rc=%%s\\n" "$out" "$rc"\n'
    ) % (LIB, " ".join("'%s'" % r for r in rows))

    pid, fd = pty.fork()
    if pid == 0:
        os.execv("/bin/bash", ["bash", "-c", script])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", height, 100, 0, 0))

    buf, step, deadline = b"", 0, time.time() + 20
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.4)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            buf += data
        elif step < len(keys):
            os.write(fd, KEYS[keys[step]])
            step += 1
        else:
            break
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except OSError:
        pass
    return ANSI.sub("", buf.decode(errors="replace"))


def result_of(out):
    # The last line is RESULT=<index> rc=<code>; the index is empty on a
    # refusal.
    for line in reversed(out.splitlines()):
        if line.startswith("RESULT="):
            body = line[len("RESULT="):]
            idx, _, rc = body.partition(" rc=")
            return idx.strip(), rc.strip()
    return None, None


def main():
    # A list of exactly the shape feature_actions draws: the separator stands
    # second from last, before "drop the feature".
    rows = [
        "Continue\tstep 2/6 development",
        "Sync with main\tup to date",
        "Review friction\t3 entries",
        "\t",                       # the separator
        "Drop the feature\tclears everything",
        "Go back\t",
    ]

    # A step down is a step of the cursor: the separator does not swallow the
    # press. Without the skip the seventh (here the third) press landed on the
    # blank line, and the list froze.
    idx, rc = result_of(drive(rows, "DDDE"))
    check("a separator does not swallow a down press", (idx, rc), ("4", "0"))

    # Up is the same thing in reverse: from "Go back" (5) one step up gives
    # "Drop the feature" (4), stepping over the separator on the way.
    idx, rc = result_of(drive(rows, "DDDDUE"))
    check("a separator does not swallow an up press", (idx, rc), ("4", "0"))

    # And up through the separator itself: from "Drop" (4) a step up gives
    # "Review friction" (2) rather than the blank line numbered 3.
    idx, rc = result_of(drive(rows, "DDDUE"))
    check("up steps over a separator", (idx, rc), ("2", "0"))

    # The last item is reachable: what all this is about stands precisely behind
    # the separator.
    idx, rc = result_of(drive(rows, "DDDDE"))
    check("the last item is reachable", (idx, rc), ("5", "0"))

    # Down from the last item leads nowhere.
    idx, rc = result_of(drive(rows, "DDDDDDDDE"))
    check("the bottom of the list does not overflow", (idx, rc), ("5", "0"))

    # Nor does up from the first.
    idx, rc = result_of(drive(rows, "UUUE"))
    check("the top of the list does not overflow", (idx, rc), ("0", "0"))

    # A refusal by key: code 1 and an empty answer. The caller tells "left" from
    # "chose" by it, and they must not be confused — "Nothing done" rests on
    # that.
    idx, rc = result_of(drive(rows, "Q"))
    check("q declines", (idx, rc), ("", "1"))

    # The space bar gives code 3 and the number of the row we stood on: by it
    # the menu toggles the checkbox and redraws the list from the same place.
    idx, rc = result_of(drive(rows, "DS"))
    check("space returns the row and code 3", (idx, rc), ("1", "3"))

    # Going back up is a contract between the list and whoever called it.
    # feature_actions returns 10 for both "Go back" and q, and by that ten the
    # menu redraws itself instead of ending. We check the contract itself: the
    # last item being chosen and leaving with a key must differ only in what the
    # list returns — while the menu treats them the same.
    idx, rc = result_of(drive(rows, "DDDDE"))
    check("the last item is chosen like any other", (idx, rc), ("5", "0"))
    idx, rc = result_of(drive(rows, "Q"))
    check("leaving with a key is distinguishable from choosing", rc, "1")

    # No terminal means code 2 and not a line to the screen: the caller leaves
    # for the numbered question, with which the same choice is made from a
    # phone.
    #
    # Through bash explicitly: os.popen calls /bin/sh, and there is neither
    # source nor bash functions there — the check would silently turn into
    # "command not found". In a session of its own, so that /dev/tty is not
    # the terminal of whoever runs the test.
    import subprocess
    out = subprocess.run(
        ["bash", "-c",
         'BOLD=""; DIM=""; GREEN=""; OFF=""; source "%s/picker.sh"; '
         'out="$(pick_list "T" "a\tb" < /dev/null)"; echo "[$out] rc=$?"' % LIB],
        capture_output=True, text=True, start_new_session=True).stdout.strip()
    check("no terminal gives code 2 and silence", out, "[] rc=2")

    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    total = 11
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
