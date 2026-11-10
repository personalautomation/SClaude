#!/usr/bin/env python3
#
# What a demo refresh is doing, shown while it runs (demo_refresh in
# demo.sh). The session that writes the demo again runs headless for up to
# forty minutes; without this the terminal said one grey line and nothing
# more until it ended.
#
#   <claude -p --output-format stream-json --verbose> 2>&1 | \
#     demo_progress.py watch <wt> <log> [<limit seconds>]
#
# Two sources:
#   - the session's events on stdin (stream-json): its tool calls say what
#     it is at — reading the change, writing the script, keeping the last
#     demo. A line that is not JSON (claude's stderr, `demo.py replay`'s
#     output) goes to the log as it is;
#   - the feature's state, `demo_progress`, which demo.py play keeps from the
#     player's `progress:` lines (play.mjs): which recording, which scenario
#     of how many, which step. The same field statusline.py shows in Claude
#     Code's status line wherever /sdemo runs.
#
# Out:
#   stdout  one line per change of what it does, `<level>\t<verb>\t<rest>`
#           (level ok, warn or say), for demo.sh to print in its colours and
#           hand to the feature's topic;
#   stderr  a status line redrawn every second — only on a terminal;
#   <log>   the same changes with their time, what the session said, its
#           commands and its final answer: refresh.log, read when something
#           went wrong.
import json
import os
import sys
import threading
import time

STATE = ".sclaude/local/feature/state.json"
DEMO_DIR = ".sclaude/local/demo"
FIELD = "demo_progress"
DIM, BOLD, OFF = "\033[2m", "\033[1m", "\033[0m"
KINDS = {"delta": "the delta", "main": "the whole feature"}


def clock(seconds):
    seconds = max(0, int(seconds))
    return "%dm%02ds" % (seconds // 60, seconds % 60)


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def read_progress(wt):
    """The recording playing now, from the feature's state; None when none
    does, or when the process that wrote it is gone."""
    try:
        with open(os.path.join(wt, STATE)) as fh:
            now = json.load(fh).get(FIELD)
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(now, dict) or not alive(now.get("pid")):
        return None
    return now


def recorded(wt, since):
    """What the newest recording made after `since` came to, from its
    demo.json: (kind, scenarios, not as expected), or None."""
    root = os.path.join(wt, DEMO_DIR)
    best = None
    try:
        names = os.listdir(root)
    except OSError:
        return None
    for name in names:
        path = os.path.join(root, name, "demo.json")
        try:
            at = os.path.getmtime(path)
        except OSError:
            continue
        if at >= since - 1 and (best is None or at > best[0]):
            best = (at, path)
    if not best:
        return None
    try:
        with open(best[1]) as fh:
            demo = json.load(fh)
    except (OSError, ValueError):
        return None
    scenarios = demo.get("scenarios") or []
    bad = sum(1 for s in scenarios
              if s.get("error") or any(x.get("ok") is False or x.get("error")
                                       for x in s.get("steps") or []))
    return demo.get("kind") or "main", len(scenarios), bad


def bar(done, total, width=10):
    """`[■■■□□□]`, one box per scenario up to `width`, scaled past it."""
    if not total:
        return ""
    cells = min(total, width)
    full = round(cells * done / total)
    return "[" + "■" * full + "□" * (cells - full) + "]"


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


class Watch:
    def __init__(self, wt, log, limit):
        self.wt, self.limit = wt, limit
        self.began = time.time()
        self.log = open(log, "a", buffering=1)
        self.lock = threading.Lock()
        self.tty = sys.stderr.isatty()
        self.phase = ""          # what the session is at, from its tool calls
        self.playing = None      # the recording seen playing: (pid, since, kind)
        self.tries = {}          # recordings started, by kind
        self.status = False      # a status line is on screen
        self.done = threading.Event()

    # --- output -------------------------------------------------------------

    def note(self, text):
        self.log.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), text))

    def say(self, level, verb, rest):
        """A change of what it does: a line for demo.sh, and one in the log."""
        rest = "%s (%s)" % (rest, clock(time.time() - self.began))
        with self.lock:
            self.clear()
            sys.stdout.write("%s\t%s\t%s\n" % (level, verb, rest))
            sys.stdout.flush()
            self.note("%s %s" % (verb, rest))

    def clear(self):
        if self.status:
            sys.stderr.write("\r\033[2K")
            sys.stderr.flush()
            self.status = False

    def draw(self, now):
        if not self.tty:
            return
        if now:
            kind = KINDS.get(now.get("kind"), "the demo")
            n, of = int(now.get("scenario") or 0), int(now.get("of") or 0)
            what = "recording %s %s scenario %d of %d" % (kind, bar(n - 1, of), n, of)
            if now.get("title"):
                what += " «%s»" % str(now["title"])[:40]
            if now.get("viewport") == "phone":
                what += " (phone)"
            if now.get("step"):
                what += ", step %s" % now["step"]
        else:
            what = self.phase or "starting the session"
        spent = time.time() - self.began
        line = "  %sRunning by itself%s — demo: %s%s%s · %s%s%s" % (
            DIM, OFF, BOLD, what, OFF, DIM,
            clock(spent) + (" of at most %s" % clock(self.limit) if self.limit else ""), OFF)
        with self.lock:
            # No wrap: a status line longer than the terminal would scroll
            # one more line at every redraw.
            sys.stderr.write("\r\033[2K\033[?7l" + line + "\033[?7h")
            sys.stderr.flush()
            self.status = True

    # --- the session's events -----------------------------------------------

    def event(self, line):
        line = line.rstrip("\n")
        if not line.strip():
            return
        try:
            ev = json.loads(line)
        except ValueError:
            ev = None
        if not isinstance(ev, dict):
            with self.lock:
                self.log.write(line + "\n")
            return
        kind = ev.get("type")
        if kind == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text", "").strip():
                    with self.lock:
                        self.note("» " + block["text"].strip().replace("\n", "\n    "))
                elif block.get("type") == "tool_use":
                    self.tool(block.get("name") or "", block.get("input") or {})
        elif kind == "result":
            with self.lock:
                self.note("the session ended%s: %s" % (
                    " with an error" if ev.get("is_error") else "",
                    str(ev.get("result") or ev.get("subtype") or "").strip()))

    def tool(self, name, args):
        command = str(args.get("command") or "")
        target = str(args.get("file_path") or args.get("path") or "")
        with self.lock:
            self.note("  %s %s" % (name, command or target or json.dumps(args)[:200]))
        if name == "Bash" and "demo.py" in command and " keep" in command:
            self.set_phase("keeping the last demo", "say", "Keeping",
                           "the last demo — nothing a user sees changed")
        elif name == "Bash" and "demo.py" in command and " play" in command:
            # The recording says itself, from the state (poll).
            self.phase = "starting the player"
        elif name in ("Edit", "Write") and DEMO_DIR in target:
            self.set_phase("writing the demo script", "say", "Writing", "the demo script")
        elif name in ("Read", "Grep", "Glob") or (
                name == "Bash" and any(g in command for g in ("git diff", "git log", "git show"))):
            if self.phase not in ("writing the demo script",):
                self.set_phase("reading what changed", "say", "Reading",
                               "what changed since the last demo")

    def set_phase(self, phase, level, verb, rest):
        if phase == self.phase:
            return
        self.phase = phase
        self.say(level, verb, rest)

    # --- the recording, from the state ----------------------------------------

    def poll(self):
        while not self.done.is_set():
            self.step()
            self.done.wait(1)
        self.step()

    def step(self):
        now = read_progress(self.wt)
        key = (now.get("pid"), now.get("since")) if now else None
        if self.playing and (not now or key != self.playing[:2]):
            self.ended()
        if now and (not self.playing or key != self.playing[:2]) and now.get("of"):
            kind = now.get("kind") or "main"
            self.tries[kind] = self.tries.get(kind, 0) + 1
            self.playing = key + (kind,)
            self.phase = "recording"
            again = ", try %d" % self.tries[kind] if self.tries[kind] > 1 else ""
            self.say("say", "Recording", "%s — %s%s" % (
                KINDS.get(kind, kind), plural(int(now["of"]), "scenario"), again))
        self.draw(now if self.playing else None)

    def ended(self):
        pid, since, kind = self.playing
        self.playing = None
        self.phase = "checking the recording"
        got = recorded(self.wt, since or self.began)
        if not got:
            self.say("warn", "Stopped", "recording %s — it did not finish" % KINDS.get(kind, kind))
            return
        kind, n, bad = got
        if bad:
            self.say("warn", "Recorded", "%s: %s, %d not as expected" % (
                KINDS.get(kind, kind), plural(n, "scenario"), bad))
        else:
            self.say("ok", "Recorded", "%s: %s" % (KINDS.get(kind, kind), plural(n, "scenario")))

    def run(self, stream):
        poller = threading.Thread(target=self.poll, daemon=True)
        poller.start()
        try:
            for line in stream:
                self.event(line)
        finally:
            self.done.set()
            poller.join(timeout=5)
            with self.lock:
                self.clear()
            self.log.close()


def main(argv):
    if len(argv) < 3 or argv[0] != "watch":
        sys.stderr.write("usage: demo_progress.py watch <wt> <log> [<limit seconds>]\n")
        return 2
    limit = int(argv[3]) if len(argv) > 3 and argv[3].isdigit() else 0
    Watch(argv[1], argv[2], limit).run(sys.stdin)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
