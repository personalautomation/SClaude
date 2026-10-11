#!/usr/bin/env python3
#
# A terminal recording, turned back into the text a person saw.
#
#   term_render.py <out> <recording>...
#
# A recording is what script(1) wrote of a sclaude run (see terminal.sh):
# every byte sent to the terminal, escape sequences included. Stripping the
# escapes is not enough to read it: a picker redraws its list in place, a
# spinner rewrites its line, and with the cursor movements gone each redraw
# lands as a line of its own. So the bytes are played into a real terminal
# instead — a detached tmux with a deep scrollback, at the size the recording
# was made — and what that terminal holds afterwards is the text: the
# scrollback and the screen, exactly as they would have stood in the window.
#
# Before playing:
#
#   * a Claude session that ran in place is cut out, from the mark term_skip
#     put before it to the one after, and a line naming its transcript stands
#     in its place. Its screen is in that transcript already; here it would be
#     most of the file. A session still running when this is read has no
#     closing mark, and is cut to the end.
#   * ESC [ 3 J, which clears the scrollback, is dropped. Claude sends it when
#     it repaints the whole screen, and played back it would erase everything
#     above it.
#   * the switches to and from the alternate screen are dropped. What a
#     program draws there never reaches the scrollback, so it would be lost;
#     drawn on the main screen it stays.
#
# The recordings go into <out> one after another, ordered by when each began,
# each under a heading naming when it started. A recording that cannot be
# played is named in its heading and skipped: the rest are still worth
# reading.
#
# Exits 0 when <out> was written, 1 when there was nothing to write, 2 on a
# usage error.
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

HEADER = re.compile(rb"^Script started on (\S+ \S+)(?: \[(.*)\])?$")
SIZE = re.compile(rb'COLUMNS="(\d+)" LINES="(\d+)"')
DROP = re.compile(rb"\x1b\[3J|\x1b\[\?(?:1049|1047|47)[hl]")
SKIP = re.compile(rb"\x1b\]7771;sclaude-skip;begin;([0-9a-f-]*)\x07"
                  rb"(?:.*?\x1b\]7771;sclaude-skip;end\x07|.*\Z)", re.S)


def cut_sessions(body):
    """Each Claude session that ran in place, down to a line naming it."""
    def stand_in(match):
        session = match.group(1).decode() or "unknown id"
        return (b"\x1b[0m\r\n[a Claude session ran here, in this window: %s; "
                b"what it showed is in its transcript]\r\n" % session.encode())
    return SKIP.sub(stand_in, body)
# Deep enough for a day of a session; tmux keeps it in memory only while the
# render runs.
HISTORY = 5000000


def split_recording(data):
    """The header's start time and size, and the body without the two
    lines script(1) adds around it."""
    started, cols, rows = "", 200, 50
    first, sep, rest = data.partition(b"\n")
    match = HEADER.match(first.rstrip(b"\r"))
    if match:
        started = match.group(1).decode(errors="replace")
        size = SIZE.search(match.group(2) or b"")
        if size:
            cols, rows = int(size.group(1)), int(size.group(2))
        data = rest
    # The closing line, when the program ended rather than the recording being
    # read while it runs.
    tail = data.rfind(b"\nScript done on ")
    if tail != -1:
        data = data[:tail]
    return started, max(cols, 20), max(rows, 5), data


def play(body, cols, rows):
    """The text a terminal of that size holds after receiving body."""
    socket = "sclaude-render-%s" % uuid.uuid4().hex[:12]
    work = tempfile.mkdtemp(prefix="sclaude-render.")
    try:
        feed = os.path.join(work, "feed")
        with open(feed, "wb") as fh:
            fh.write(DROP.sub(b"", cut_sessions(body)))
        conf = os.path.join(work, "tmux.conf")
        with open(conf, "w") as fh:
            fh.write("set -g history-limit %d\n" % HISTORY)
            fh.write("set -g status off\n")
        tmux = ["tmux", "-L", socket, "-f", conf]
        # cat, then a signal on a channel the caller waits on, then a sleep
        # that keeps the pane — and its scrollback — alive for the capture.
        # stty raw: the pane's own line discipline must not turn the
        # recording's \r\n into anything else.
        inner = "stty raw -echo; cat %s; tmux -L %s wait-for -S played; sleep 600" % (
            shlex_quote(feed), socket)
        subprocess.run(tmux + ["new-session", "-d", "-x", str(cols), "-y", str(rows),
                               "-s", "r", inner],
                       check=True, capture_output=True, timeout=30)
        subprocess.run(tmux + ["wait-for", "played"], check=True, timeout=600)
        out = subprocess.run(tmux + ["capture-pane", "-p", "-J", "-S", "-", "-E", "-",
                                     "-t", "r"],
                             check=True, capture_output=True, timeout=120)
        return out.stdout.decode("utf-8", errors="replace")
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)


def shlex_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def tidy(text):
    """Trailing spaces off every line, runs of blank lines down to one."""
    lines = [line.rstrip() for line in text.split("\n")]
    out, blank = [], 0
    for line in lines:
        blank = blank + 1 if not line else 0
        if blank <= 1:
            out.append(line)
    return "\n".join(out).strip("\n") + "\n"


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: term_render.py <out> <recording>...\n")
        return 2
    if not shutil.which("tmux"):
        sys.stderr.write("term_render: tmux is not installed\n")
        return 1
    out_path, paths = sys.argv[1], sys.argv[2:]

    parts = []
    for path in paths:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        started, cols, rows, body = split_recording(data)
        parts.append((started, path, cols, rows, body))
    if not parts:
        return 1
    parts.sort(key=lambda p: (p[0], p[1]))

    with open(out_path, "w", encoding="utf-8") as out:
        for started, path, cols, rows, body in parts:
            heading = "sclaude · started %s · %s" % (started or "?", path)
            out.write("=" * 78 + "\n" + heading + "\n" + "=" * 78 + "\n\n")
            try:
                out.write(tidy(play(body, cols, rows)))
            except (subprocess.SubprocessError, OSError) as exc:
                out.write("(could not be played back: %s)\n" % exc)
            out.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
