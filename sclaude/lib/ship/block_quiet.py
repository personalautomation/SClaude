#!/usr/bin/env python3
# A command of a deploy block run and shown short (run_block in vercel.sh):
# its first lines, every line that says something failed, and its last line
# on the screen; all of it in the log the caller names.
#
#   block_quiet.py <log> <command>
#
# A production block runs a pull, the product's own promote and a push whose
# hooks print their checks: a hundred lines of a diffstat and a hundred and
# more of PASS, around the one line that said all was well. Shown whole, they
# pushed what sclaude said before them off the screen, and they are in the
# log for whoever wants them.
#
# The command still has a terminal when there is one here: it runs on a
# pseudo-terminal of its own, whose output is what is filtered, and the keys
# typed here reach it — a command that asks only when it sees a terminal asks
# as before, and one piped would have stopped asking or printed for a
# machine. With no terminal here it is piped, as it was, and reads the input
# this was given. A line it leaves without its newline for a moment is a
# question, and is shown at once. The exit is the command's own.

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import tty

HEAD = 8
# What is shown past the head, whatever it is.
SAYS_FAILED = re.compile(r"fail|error|fatal|✗|denied|refused|reject|conflict|abort|panic", re.I)
COLOUR = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x1b]*(\x1b\\|\x07)")
PROMPT_WAIT = 0.5


def plain(text):
    return COLOUR.sub("", text).replace("\r", "")


class Shown(object):
    """What reaches the screen of what the command printed."""

    def __init__(self, out, log):
        self.out, self.log = out, log
        self.shown = self.hidden = 0
        self.last = ""
        self.last_shown = True
        self.pending = b""
        # A question shown before its newline: the rest of its line — the
        # answer's echo, its Enter — goes to the screen whatever it holds, or
        # what is shown next would run on from the question.
        self.mid_line = False

    def write(self, text):
        self.out.write(text)
        self.out.flush()

    def line(self, raw):
        text = raw.decode("utf-8", "replace")
        self.log.write(plain(text))
        bare = plain(text).strip()
        if self.mid_line:
            self.mid_line = False
            self.write(text)
            return
        if bare:
            self.last = text
        if self.shown < HEAD or SAYS_FAILED.search(bare):
            self.write(text)
            self.shown += 1
            self.last_shown = True
        elif bare:
            self.hidden += 1
            self.last_shown = False

    def feed(self, chunk):
        self.pending += chunk
        while b"\n" in self.pending:
            raw, self.pending = self.pending.split(b"\n", 1)
            self.line(raw + b"\n")

    def quiet(self):
        """Nothing came for a moment: a line begun is a question."""
        if self.pending:
            text = self.pending.decode("utf-8", "replace")
            self.log.write(plain(text))
            self.write(text)
            self.pending = b""
            self.last_shown = True
            self.mid_line = True

    def end(self):
        if self.pending:
            self.line(self.pending + b"\n")
            self.pending = b""
        if not self.hidden:
            return
        if not self.last_shown and self.last:
            self.write(self.last if self.last.endswith("\n") else self.last + "\n")
            self.hidden -= 1
        if self.hidden:
            self.write("  … %d line(s) not shown — the whole output: %s\n" % (self.hidden, self.log.name))


def piped(command, shown):
    """With no terminal here, as before: the command's output through a
    pipe, its input the one this was given — at its end a question reads
    the end, rather than waiting on a terminal nobody types into."""
    proc = subprocess.Popen(["bash", "-c", command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # Ignored here only, after the start: an interrupt passed on to the
    # group reaches the command, and this one reads on until it ends,
    # rather than leave it writing to a pipe nobody reads.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    fd = proc.stdout.fileno()
    try:
        while True:
            ready, _, _ = select.select([fd], [], [], PROMPT_WAIT)
            if not ready:
                shown.quiet()
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            shown.feed(chunk)
    finally:
        shown.end()
    return proc.wait()


def run(command, shown):
    """The command on a pseudo-terminal when there is a terminal here — its
    output to `shown`, the keys typed here to it — and piped when there is
    none; its exit code."""
    stdin = sys.stdin.fileno()
    if not os.isatty(stdin):
        return piped(command, shown)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("bash", ["bash", "-c", command])
    # A Ctrl-C reaches the command through its terminal; this one waits for
    # it to end rather than leaving it behind. Ignored here only, after the
    # fork: ignored before, the command would inherit it through exec and
    # nothing could stop it from the keyboard.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        size = fcntl.ioctl(stdin, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass
    saved = termios.tcgetattr(stdin)
    # The keys as they are typed, Ctrl-C included, for the command's own
    # terminal to read and to signal by.
    tty.setraw(stdin)
    try:
        while True:
            ready, _, _ = select.select([fd, stdin], [], [], PROMPT_WAIT)
            if not ready:
                shown.quiet()
                continue
            if stdin in ready:
                data = os.read(stdin, 1024)
                if data:
                    os.write(fd, data)
            if fd in ready:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                shown.feed(chunk)
    finally:
        termios.tcsetattr(stdin, termios.TCSADRAIN, saved)
        shown.end()
        os.close(fd)
    _, status = os.waitpid(pid, 0)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return os.WEXITSTATUS(status)


def main():
    if len(sys.argv) != 3:
        print("usage: block_quiet.py <log> <command>", file=sys.stderr)
        return 2
    path, command = sys.argv[1], sys.argv[2]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        log = open(path, "a", encoding="utf-8")
    except OSError:
        log = open(os.devnull, "w")
    with log:
        return run(command, Shown(sys.stdout, log))


if __name__ == "__main__":
    sys.exit(main())
