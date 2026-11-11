#!/usr/bin/env python3
"""The demo's progress, wherever a demo is recorded.

  - play.mjs prints `progress: {json}` lines; demo.py play keeps them in the
    feature's state as `demo_progress` (not on the screen), merging a step
    into its scenario, and clears it when the player ends; outside a feature
    of sclaude it writes nothing;
  - demo_progress.py watch (demo_refresh in demo.sh) turns a session's
    stream-json events and that field into one line per change, with a try
    counted per kind and the recording's outcome from its demo.json, and
    keeps a readable refresh.log;
  - statusline.py shows the same field in Claude Code's status line, and
    nothing once the process that wrote it is gone.

Run it with: python3 tests/demo-progress.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_PY = os.path.join(ROOT, "skills", "sdemo", "demo.py")
WATCH = os.path.join(ROOT, "sclaude", "lib", "ship", "demo_progress.py")
failures = []


def check(name, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (name, got, want))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def state_of(wt):
    with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json")) as fh:
        return json.load(fh)


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


root = tempfile.mkdtemp()

# --- demo.py play: the player's progress lines go into the state ---------------
wt = os.path.join(root, "wt")
write(os.path.join(wt, ".sclaude", "local", "feature", "state.json"), json.dumps({"feature": "f1", "pr": 7}))
st = os.path.join(wt, ".sclaude", "local", "feature", "state.json")
player = os.path.join(root, "player.sh")
write(player, """#!/bin/sh
echo 'progress: {"kind": "delta", "scenario": 1, "of": 2, "title": "Sign in", "viewport": "phone", "step": 0}'
sleep 0.4
cp %(st)s %(root)s/snap1
echo 'progress: {"step": 3}'
sleep 0.4
cp %(st)s %(root)s/snap2
echo 'scenario 1: done'
echo 'progress: not json'
""" % {"st": st, "root": root})
os.chmod(player, 0o755)
run = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("demo", %r)
demo = importlib.util.module_from_spec(spec); spec.loader.exec_module(demo)
sys.exit(demo.play_watched([%r], sys.argv[1]))
""" % (DEMO_PY, player)
done = subprocess.run([sys.executable, "-c", run, wt], capture_output=True, text=True)
check("play: the player's exit code comes back", done.returncode, 0)
check("play: other lines pass on, progress lines do not",
      done.stdout, "scenario 1: done\nprogress: not json\n")
with open(os.path.join(root, "snap1")) as fh:
    snap1 = json.load(fh)["demo_progress"]
with open(os.path.join(root, "snap2")) as fh:
    snap2 = json.load(fh)["demo_progress"]
check("play: the scenario is in the state while it plays",
      (snap1.get("kind"), snap1.get("scenario"), snap1.get("of"), snap1.get("viewport"),
       isinstance(snap1.get("pid"), int), isinstance(snap1.get("since"), int)),
      ("delta", 1, 2, "phone", True, True))
check("play: a step merges into its scenario",
      (snap2.get("step"), snap2.get("scenario"), snap2.get("title"), snap2.get("since")),
      (3, 1, "Sign in", snap1.get("since")))
check("play: cleared when the player ends, the rest of the state kept",
      (state_of(wt).get("demo_progress", "missing"), state_of(wt).get("pr")), (None, 7))

bare = os.path.join(root, "bare")
os.makedirs(bare)
subprocess.run([sys.executable, "-c", run, bare], capture_output=True, text=True)
check("play: outside a feature of sclaude nothing is written",
      os.path.exists(os.path.join(bare, ".sclaude")), False)

# --- watch: the session's events and the state, said as they change -----------
wt2 = os.path.join(root, "wt2")
st2 = os.path.join(wt2, ".sclaude", "local", "feature", "state.json")
write(st2, json.dumps({"feature": "f2"}))
log = os.path.join(root, "refresh.log")


def progress(fields):
    data = state_of(wt2)
    data["demo_progress"] = fields
    write(st2, json.dumps(data))


def recording(name, kind, scenarios):
    write(os.path.join(wt2, ".sclaude", "local", "demo", name, "demo.json"),
          json.dumps({"kind": kind, "scenarios": scenarios}))


def ev(kind, **fields):
    return json.dumps(dict(type=kind, **fields)) + "\n"


def tool(name, **args):
    return ev("assistant", message={"content": [{"type": "tool_use", "name": name, "input": args}]})


watch = subprocess.Popen([sys.executable, WATCH, "watch", wt2, log, "2400"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
feed = watch.stdin
feed.write(ev("system", subtype="init"))
feed.write("a line that is not json\n")
feed.write(ev("assistant", message={"content": [{"type": "text", "text": "Reading the diff first."}]}))
feed.write(tool("Bash", command="python3 /x/skills/sdemo/demo.py last"))
feed.write(tool("Bash", command="git diff abc123"))
feed.write(tool("Read", file_path=os.path.join(wt2, "app.ts")))
feed.write(tool("Write", file_path=os.path.join(wt2, ".sclaude/local/demo/delta.mjs")))
feed.write(tool("Bash", command="python3 /x/skills/sdemo/demo.py play delta.mjs"))
feed.flush()
time.sleep(1)  # the events read before the recording shows in the state
me = os.getpid()
progress({"pid": me, "since": int(time.time()), "kind": "delta", "scenario": 1, "of": 3, "step": 2})
time.sleep(1.5)
recording("20261110-1", "delta", [{"steps": [{"ok": True}]}] * 3)
progress(None)
time.sleep(1.5)
# Looking at the recording reads no change; a script edited by a heredoc is written.
feed.write(tool("Read", file_path="/tmp/frame.png"))
feed.write(tool("Bash", command="git show HEAD:app.ts"))
feed.write(tool("Bash", command="python3 - <<'X'\np='.sclaude/local/demo/delta.mjs'\nopen(p,'w').write(s)\nX"))
feed.flush()
time.sleep(1)
progress({"pid": me, "since": int(time.time()), "kind": "delta", "scenario": 1, "of": 3, "playing": 1})
time.sleep(1.5)
recording("20261110-2", "delta", [{"steps": [{"ok": False}]}, {"steps": []}])
progress(None)
time.sleep(1.5)
feed.write(tool("Bash", command="python3 /x/skills/sdemo/demo.py keep \"nothing changed\""))
feed.write(ev("result", result="The demo page: http://x/", is_error=False))
feed.close()
out = watch.stdout.read()
watch.wait(timeout=15)
said = [line.split("\t")[:2] + [line.split("\t")[2].rsplit(" (", 1)[0]] for line in out.splitlines()]
check("watch: one line per change, in order", said, [
    ["say", "Reading", "what changed since the last demo"],
    ["say", "Writing", "the demo script"],
    ["say", "Recording", "the delta — 3 scenarios"],
    ["ok", "Recorded", "the delta: 3 scenarios"],
    ["say", "Writing", "the demo script"],
    ["say", "Recording", "the delta — 1 of 3 scenarios again, try 2"],
    ["warn", "Recorded", "the delta: 2 scenarios, 1 not as expected"],
    ["say", "Keeping", "the last demo — nothing a user sees changed"],
])
check("watch: each line carries the time spent", all(line.endswith("s)") for line in out.splitlines()), True)
check("watch: no status line when stderr is not a terminal", watch.stderr.read(), "")
with open(log) as fh:
    text = fh.read()
check("watch: the log keeps what is not json, what the session said, its commands and its answer",
      ("a line that is not json" in text, "» Reading the diff first." in text,
       "Bash git diff abc123" in text, "The demo page: http://x/" in text, "Recording the delta" in text),
      (True, True, True, True, True))

done = subprocess.run([sys.executable, WATCH, "watch", wt2, log], input="", capture_output=True,
                      text=True, timeout=10)
check("watch: empty input ends it quietly", (done.returncode, done.stdout), (0, ""))

progress({"pid": dead_pid(), "since": 1, "kind": "main", "scenario": 2, "of": 4})
done = subprocess.run([sys.executable, WATCH, "watch", wt2, log], input="", capture_output=True,
                      text=True, timeout=10)
check("watch: a recording whose process is gone is not taken for one playing", done.stdout, "")

# --- statusline.py: the same field in Claude Code's status line ---------------
spec = importlib.util.spec_from_file_location("statusline", os.path.join(ROOT, "statusline.py"))
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)
d = {"workspace": {"project_dir": wt2}}
progress({"pid": os.getpid(), "since": 1, "kind": "delta", "scenario": 2, "of": 4, "step": 5})
check("statusline: the demo playing in this tree", sl.demo_progress(d), "🎬 delta 2/4 · step 5")
progress({"pid": os.getpid(), "since": 1, "kind": "main", "scenario": 1, "of": 6})
check("statusline: a full demo before its first step", sl.demo_progress(d), "🎬 demo 1/6")
progress({"pid": dead_pid(), "since": 1, "kind": "main", "scenario": 1, "of": 6})
check("statusline: nothing once the process is gone", sl.demo_progress(d), None)
progress(None)
check("statusline: nothing when nothing plays", sl.demo_progress(d), None)
check("statusline: the pull request still read from the same state",
      sl.feature_pr({"workspace": {"project_dir": wt}}), "#7")

# --- the sides agree ---------------------------------------------------------
with open(os.path.join(ROOT, "skills", "sdemo", "play.mjs")) as fh:
    play = fh.read()
with open(DEMO_PY) as fh:
    demo_src = fh.read()
with open(os.path.join(ROOT, "sclaude", "lib", "ship", "demo.sh")) as fh:
    sh = fh.read()
check("play.mjs prints the prefix demo.py reads",
      ('console.log("progress: " + JSON.stringify(fields))' in play, 'PROGRESS = "progress: "' in demo_src),
      (True, True))
check("play.mjs sends the fields the readers use",
      all(k + ":" in play for k in ("kind", "scenario", "of", "title", "viewport", "step")), True)
check("demo.sh: the session's events stream into demo_progress.py",
      ("--output-format stream-json --verbose" in sh, "demo_progress.py\" watch" in sh,
       '| demo_progress "$wt" "$log"' in sh), (True, True, True))

if failures:
    print("FAIL tests/demo-progress.py")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("ok tests/demo-progress.py")
