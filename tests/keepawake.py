#!/usr/bin/env python3
#
# A test bench for keepawake's state.
#
# It covers where the cost of a mistake is high rather than what is easy to
# check. The main thing here is concurrency: two writers edit one file that
# PowerShell reads at the same time, and broken JSON here means not "it looks
# ugly" but a laptop that fell asleep mid-work or did not sleep all night. A bug
# like that shows up once a month and cannot be debugged after the fact, so it is
# checked here with a hammer: a thousand reads against two writing processes.
#
# Run it with: python3 tests/keepawake.py
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from keepawake import state
from keepawake.state import (HARD_HOLDERS, HOLD_SECONDS, REFUSAL_HOLDS,
                             SOFT_HOLDERS, STALE_AFTER, VERSION, WARN_BEFORE,
                             blank, extend, needs_warning, read, refuses,
                             should_hold, touch, write)

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


class sandbox(object):
    # The real state file must not be touched: it governs a live machine's
    # sleep.
    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="keepawake-test-")
        self.path = os.path.join(self.dir, "state.json")
        os.environ["KEEPAWAKE_STATE"] = self.path
        os.environ["KEEPAWAKE_LOCK"] = os.path.join(self.dir, ".lock")
        return self

    def __exit__(self, *exc):
        os.environ.pop("KEEPAWAKE_STATE", None)
        os.environ.pop("KEEPAWAKE_LOCK", None)
        return False


NOW = 1757000000


# ---------------------------------------------------------------- fail-safe

# A table of inputs with one answer: do not hold. Every row is a real failure
# that will happen: there is no file (the first run), the JSON is broken (a write
# was interrupted), the version is foreign (a format upgrade), until is in the
# past (the deadline passed), updated is stale (WSL died and the file
# remained).
def fail_safe_cases():
    fresh = NOW - 10
    return [
        ("no file", None),
        ("an empty dict", {}),
        ("a foreign version", {"version": 2, "until_ts": NOW + 600, "updated_ts": fresh}),
        ("the deadline has passed", {"version": VERSION, "until_ts": NOW - 1, "updated_ts": fresh}),
        ("the deadline is exactly now", {"version": VERSION, "until_ts": NOW, "updated_ts": fresh}),
        ("a stale heartbeat", {"version": VERSION, "until_ts": NOW + 600,
                                 "updated_ts": NOW - STALE_AFTER}),
        ("until is not a number", {"version": VERSION, "until_ts": "later", "updated_ts": fresh}),
        ("updated is not a number", {"version": VERSION, "until_ts": NOW + 600,
                              "updated_ts": None}),
    ]


for name, data in fail_safe_cases():
    check("fail-safe: %s" % name, should_hold(data, NOW), False)

# Holders of two kinds. Hard ones (a live SSH session, a terminal in
# code-server, traffic in the tailnet) mean a person is at the machine: sleep
# does not come while they are there, and the deadline is not looked at at all
# with them. Soft ones (claude, the dev server) mean work is going on but there
# may be nobody around — they give an hour and a question when it runs out.
check("hard and soft do not overlap",
      set(HARD_HOLDERS) & set(SOFT_HOLDERS), set())

# code-server is counted twice and differently: a live tab in the browser is a
# person (hard), while the service itself lives for days on its own (soft).
check_true("a code-server session is hard", "code" in HARD_HOLDERS)
check_true("the code-server service is soft", "codesrv" in SOFT_HOLDERS)

# We determine a live session by the heartbeat file code-server touches once a
# minute while the page is open. Counting processes is unreliable: extension
# hosts see out a three-hour reconnection-grace-time after the tab is closed.
script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "bin", "keepawake")
body_ka = open(script_path).read()
check_true("a session is found by its heartbeat", "heartbeat" in body_ka)
check_true("the threshold is larger than the update period",
           "CODE_ALIVE_SECONDS=120" in body_ka)

# An sclaude step and an open VS Code are work too, but with nobody around.
check_true("an sclaude step is soft", "sclaude" in SOFT_HOLDERS)
check_true("VS Code is soft", "vscode" in SOFT_HOLDERS)

hard_base = {"version": VERSION, "updated_ts": NOW - 10}
check_true("a hard holder holds with an expired deadline",
           should_hold(dict(hard_base, hard_hold=True, until_ts=NOW - 999), NOW))
check_true("a hard holder holds with a zero deadline",
           should_hold(dict(hard_base, hard_hold=True, until_ts=0), NOW))
check("without a hard holder an expired deadline does not hold",
      should_hold(dict(hard_base, hard_hold=False, until_ts=NOW - 1), NOW), False)
# A stale heartbeat cancels a hard hold too: a silent WSL can confirm nothing,
# otherwise its last word would keep the laptop awake for ever.
check("a stale heartbeat cancels a hard hold",
      should_hold({"version": VERSION, "updated_ts": NOW - STALE_AFTER,
                   "hard_hold": True, "until_ts": NOW + 600}, NOW), False)

# With a hard holder an "extend?" question is pointless: there will be no
# sleep.
check("with a hard holder we do not warn",
      needs_warning({"version": VERSION, "updated_ts": NOW - 10, "hard_hold": True,
                     "until_ts": NOW + 60, "warned_for_ts": 0}, NOW), False)
check_true("without a hard holder we warn",
           needs_warning({"version": VERSION, "updated_ts": NOW - 10,
                          "hard_hold": False, "until_ts": NOW + WARN_BEFORE,
                          "warned_for_ts": 0}, NOW))

check("we hold with a live deadline and a fresh heartbeat",
      should_hold({"version": VERSION, "until_ts": NOW + 600,
                   "updated_ts": NOW - 10}, NOW), True)

# The heartbeat boundary: exactly at the threshold we do not hold, a second
# fresher and we do.
check("a heartbeat exactly at the threshold",
      should_hold({"version": VERSION, "until_ts": NOW + 600,
                   "updated_ts": NOW - STALE_AFTER}, NOW), False)
check("a heartbeat a second fresher than the threshold",
      should_hold({"version": VERSION, "until_ts": NOW + 600,
                   "updated_ts": NOW - STALE_AFTER + 1}, NOW), True)


# --------------------------------------------------------------- broken JSON

with sandbox() as box:
    with open(box.path, "w") as fh:
        fh.write('{"version": 1, "until_ts": 175700')  # the write was interrupted
    check("broken JSON reads as empty", read(box.path)["until_ts"], 0)
    check("broken JSON does not hold", should_hold(read(box.path), NOW), False)

    with open(box.path, "w") as fh:
        fh.write("[]")  # not a dict
    check("a non-dict reads as empty", read(box.path)["version"], VERSION)
    check("a non-dict does not hold", should_hold(read(box.path), NOW), False)


# ----------------------------------------------------------------- extending

data = blank()
data["until_ts"] = NOW + HOLD_SECONDS + 900   # longer than an hour: a manual extension
extend(data, NOW)
check("max(): a long deadline is not shortened",
      data["until_ts"], NOW + HOLD_SECONDS + 900)

data = blank()
data["until_ts"] = NOW + 100
extend(data, NOW)
check("max(): a short deadline is extended", data["until_ts"], NOW + HOLD_SECONDS)

data = blank()
extend(data, NOW)
check("extending from zero", data["until_ts"], NOW + HOLD_SECONDS)
check_true("extending writes the local label", bool(data["until_local"]))


# ------------------------------------------------------------------ refusal

data = blank()
data["decision"] = "sleep"
data["decision_ts"] = NOW
check_true("a fresh refusal applies", refuses(data, NOW))

# A refusal has to expire. The window used to be counted from until_ts, and
# "Let it sleep" resets until_ts to the current moment — the window's start moved
# into the past for good, and the refusal became indefinite: one press of a
# button and extending never worked again, even with a live session.
data["decision_ts"] = NOW - REFUSAL_HOLDS
check("a refusal at the boundary has expired", refuses(data, NOW), False)
data["decision_ts"] = NOW - REFUSAL_HOLDS - 3600
check("an old refusal does not apply", refuses(data, NOW), False)
data["decision_ts"] = NOW - REFUSAL_HOLDS + 5
check_true("a refusal before the boundary still holds", refuses(data, NOW))

# That very case: release zeroed the deadline while the session is alive. The
# refusal has to let go, otherwise the laptop stops being held for ever.
data = blank()
data["until_ts"] = NOW - REFUSAL_HOLDS
data["decision"] = "sleep"
data["decision_ts"] = NOW - REFUSAL_HOLDS
check("a refusal does not outlive its window even with a zeroed deadline",
      refuses(data, NOW), False)

data = blank()
data["decision"] = "extend"
data["decision_ts"] = NOW
check("extending does not count as a refusal", refuses(data, NOW), False)


# A decision lives for its own holding cycle and is erased with it. Without this
# the field stayed in the file for ever, and status explained today's hold by
# yesterday's press of a button: "decision: sleep" eleven hours after the laptop
# had slept by it and woken up again.
data = blank()
data["decision"] = "sleep"
data["decision_ts"] = NOW - 300
touch(data, NOW)
check("a fresh refusal survives a touch", data["decision"], "sleep")

data["decision"] = "sleep"
data["decision_ts"] = NOW - REFUSAL_HOLDS - 3600
touch(data, NOW)
check("a stale refusal is erased", data["decision"], "")
check("the decision's stamp is erased with it", data["decision_ts"], 0)

# An extension has a lifetime of its own: while the very time the human asked
# for is still running.
data = blank()
data["decision"] = "extend"
data["decision_ts"] = NOW - 60
data["until_ts"] = NOW + 1800
data.setdefault("holders", {})["manual"] = {"until_ts": NOW + 1800}
touch(data, NOW)
check("an extension lives while the manual deadline runs", data["decision"], "extend")

data["holders"]["manual"] = {"until_ts": NOW - 60}
touch(data, NOW)
check("the extension is erased once the manual deadline has passed", data["decision"], "")


# ------------------------------------------------------------------ warning

data = blank()
data["until_ts"] = NOW + WARN_BEFORE + 60
check("too early to warn", needs_warning(data, NOW), False)

data["until_ts"] = NOW + WARN_BEFORE
check_true("the warning threshold", needs_warning(data, NOW))

# Once sent, we do not send it a second time for the same deadline.
data["warned_for_ts"] = data["until_ts"]
check("we do not warn twice", needs_warning(data, NOW), False)

# Extended: a new deadline, a new warning, and the flag needs no resetting.
extend(data, NOW)
check("after extending it is too early to warn", needs_warning(data, NOW), False)
check_true("the flag fell behind the new deadline", data["warned_for_ts"] != data["until_ts"])
# We have reached the new deadline's threshold.
later = data["until_ts"] - WARN_BEFORE
check_true("after extending we warn again", needs_warning(data, later))

data = blank()
data["until_ts"] = NOW - 1
check("an expired deadline does not warn", needs_warning(data, NOW), False)


# ---------------------------------------------------------------- callback

# A press on yesterday's message must not extend the hold at an arbitrary moment
# the next day, so callback_data holds the until_ts the message was sent for.
def parse_callback(raw):
    action, _, ts = raw.partition(":")
    try:
        return action, int(ts)
    except ValueError:
        return action, None


def callback_fresh(data, raw):
    action, ts = parse_callback(raw)
    if ts is None:
        return False
    return ts == (data.get("until_ts") or 0)


data = blank()
data["until_ts"] = NOW + 600
check("a fresh callback is accepted", callback_fresh(data, "extend:%d" % (NOW + 600)), True)
check("a stale callback is rejected", callback_fresh(data, "extend:%d" % (NOW - 99)), False)
check("a callback with no stamp is rejected", callback_fresh(data, "extend"), False)
check("parsing the action", parse_callback("sleep:%d" % NOW)[0], "sleep")


# ------------------------------------------------------------- parsing sshd

# A live SSH session is always a descendant of sshd. who/w will not do here:
# utmp is filled in inconsistently under WSL, and tmux/screen give false
# negatives.
def ssh_sessions(entries):
    seen = set()
    for cmdline, ppid in entries:
        if not cmdline.startswith("sshd:"):
            continue
        if ppid == 1 and "@" not in cmdline:
            continue          # the master daemon
        if "[accepted]" in cmdline or "[net]" in cmdline:
            continue          # not a session yet
        if "@" not in cmdline:
            continue
        seen.add(cmdline.rsplit("@", 1)[1])
    return len(seen)


check("the master daemon does not count",
      ssh_sessions([("sshd: /usr/sbin/sshd -D [listener]", 1)]), 0)
check("accepted does not count",
      ssh_sessions([("sshd: [accepted]", 900)]), 0)
check("one session",
      ssh_sessions([("sshd: ilia@pts/2", 900)]), 1)
check("two sessions on different ptys",
      ssh_sessions([("sshd: ilia@pts/2", 900), ("sshd: ilia@pts/3", 900)]), 2)
check("duplicates on one pty collapse",
      ssh_sessions([("sshd: ilia@pts/2", 900), ("sshd: ilia@pts/2", 901)]), 1)
check("an unrelated process does not count",
      ssh_sessions([("bash", 900), ("sshd: ilia@pts/2", 900)]), 1)


# --------------------------------------------------------- the bash counters

# We check the detector's functions as they are, pulling them out of the script:
# duplicating their logic in the test would mean checking a copy rather than what
# actually runs.
def bash_count(func, fake_procs="", snapshot=None, overrides=None):
    snapshot = snapshot or os.path.join(tempfile.gettempdir(),
                                        "keepawake-test-snapshot")
    # We pull not one function but everything it rests on: count_claude uses
    # ppid_of, LOG_DIR and the CPU constants, and without them it behaves
    # differently from the real script.
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "bin", "keepawake")
    parts = []
    for expr in ("/^LOG_DIR=/p", "/^DEV_PORT=/p",
                 "/^SOFT_SNAPSHOT=/p", "/^SOFT_SNAPSHOT_NEW=/p",
                 "/^CLAUDE_PROJECTS=/p", "/^CLAUDE_FRESH_MINUTES=/p",
                 "/^CLAUDE_REMEMBER_MINUTES=/p",
                 "/^VSCODE_HISTORY=/p", "/^DEV_LOG_REL=/p",
                 "/^have()/,/^}/p", "/^ppid_of/,/^}/p",
                 # The soft holders' sign of activity: the previous run's
                 # snapshot and a comparison against it. Without them the count_
                 # functions do not run at all.
                 "/^read_snapshot/,/^}/p", "/^remember/,/^}/p",
                 "/^grew/,/^}/p", "/^io_wchar_of/,/^}/p",
                 "/^transcript_size/,/^}/p", "/^sclaude_states/,/^}/p",
                 "/^%s/,/^}/p" % func):
        parts.append(subprocess.run(["sed", "-n", expr, script],
                                    capture_output=True, text=True).stdout)
    snippet = "\n".join(p for p in parts if p.strip())
    # A snapshot of our own rather than one shared with the real detector:
    # otherwise the count depends on what the timer saw a minute ago, and the
    # test flickers along with it.
    #
    # run_once moves the snapshot rather than the count_ functions themselves:
    # they only accumulate into .new. We repeat that move here, otherwise a
    # second call in a row would compare itself against emptiness and count the
    # holder as new every time.
    body = "\n".join([
        snippet,
        'SOFT_SNAPSHOT=%s' % shlex.quote(snapshot),
        'SOFT_SNAPSHOT_NEW="$SOFT_SNAPSHOT.new"',
        ': > "$SOFT_SNAPSHOT_NEW"',
        "\n".join('%s=%s' % (k, shlex.quote(v))
                   for k, v in (overrides or {}).items()),
        fake_procs,
        func,
        'mv -f "$SOFT_SNAPSHOT_NEW" "$SOFT_SNAPSHOT"',
    ])
    out = subprocess.run(["bash", "-c", body], capture_output=True, text=True)
    return out.stdout.strip()


# An open session waiting for input is not work. That is exactly why the laptop
# once did not sleep until morning: the claude process lived from the evening on,
# the detector extended the deadline every minute, and no warning came — the
# deadline moved forward faster than it approached the threshold.
#
# The sign of work is a growing conversation transcript rather than a live
# process or its CPU time. The transcript grows from the conversation: a session
# waiting for input appends nothing to it. The fuss of excluding ourselves and
# our ancestors fell away with it — the detector is started from under claude
# among other places, and by processes counting itself produced an endless
# hold.
ka_body = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "bin", "keepawake")).read()
check_true("claude's busyness is measured by the transcript",
           "CLAUDE_PROJECTS" in ka_body)
# The size specifically rather than the modification time: an open and forgotten
# session touches its transcript every half hour without appending anything. By
# mtime it looked like work and extended the deadline by an hour — the laptop
# would not sleep for days.
check_true("the sign of work is the transcript's size, not its mtime",
           "-printf '%s %p" in ka_body)
check_true("the previous run's snapshot is kept", "SOFT_SNAPSHOT" in ka_body)
check_true("old transcripts are cut off by freshness",
           "CLAUDE_FRESH_MINUTES" in ka_body)
# bfs, which stands here in place of GNU find, does not understand relative
# stamps like "-5 min" and silently finds nothing — the holder would always go
# dark. We check the selection itself rather than the absence of the word: it
# legitimately lives in the comment explaining why it will not do.
check_true("freshness is selected with -mmin",
           '-mmin "-$CLAUDE_FRESH_MINUTES"' in ka_body)


# We fake the transcripts on disk: count_claude looks only at them, and there is
# no need to start a real claude session for a test.
def with_transcripts(files, snapshot, projects=None):
    """files: {session name: how many seconds ago it was modified}."""
    projects = projects or tempfile.mkdtemp(prefix="keepawake-test-")
    proj = os.path.join(projects, "-home-test")
    os.makedirs(proj, exist_ok=True)
    now = time.time()
    for name, age in files.items():
        path = os.path.join(proj, "%s.jsonl" % name)
        with open(path, "w") as fh:
            fh.write("{}\n")
        os.utime(path, (now - age, now - age))
    return projects, bash_count("count_claude", snapshot=snapshot,
                                overrides={"CLAUDE_PROJECTS": projects})


snap_tr = os.path.join(tempfile.gettempdir(), "keepawake-test-transcripts")
if os.path.exists(snap_tr):
    os.unlink(snap_tr)

# A fresh transcript not yet in the snapshot is work: there is nothing to judge
# by, and the better way to be wrong is towards "do not sleep in the middle of
# the work".
projects, out = with_transcripts({"live": 1}, snap_tr)
check("a fresh transcript counts as work", int(out), 1)

# The same transcript, unchanged since the previous run, is silence.
_, out = with_transcripts({}, snap_tr, projects=projects)
check("the transcript is not growing — the session does not hold", int(out), 0)

# A touch without a write is not work. A forgotten session behaves exactly that
# way: it touches the file every half hour without appending a line.
os.utime(os.path.join(projects, "-home-test", "live.jsonl"), None)
_, out = with_transcripts({}, snap_tr, projects=projects)
check("a touch without a write does not hold", int(out), 0)

# An appended line, however, is work.
with open(os.path.join(projects, "-home-test", "live.jsonl"), "a") as fh:
    fh.write('{"x":1}\n')
_, out = with_transcripts({}, snap_tr, projects=projects)
check("the transcript grew — the session holds again", int(out), 1)

# A transcript that fell out of the freshness window and came back through a
# touch is not a new session. The snapshot has to remember its size until the
# file becomes really old.
#
# Without that memory you got a sawtooth: five minutes of silence and the key is
# gone from the snapshot; a touch without a write and the file is back in the
# window with no key, so "first appearance" counts as work. A forgotten session
# extended the deadline that way every half hour, even after touches had stopped
# counting as work in themselves.
snap_gap = os.path.join(tempfile.gettempdir(), "keepawake-test-gap")
if os.path.exists(snap_gap):
    os.unlink(snap_gap)
projects_gap, out = with_transcripts({"gap": 1}, snap_gap)
check("a fresh transcript counts as work (the window)", int(out), 1)

path_gap = os.path.join(projects_gap, "-home-test", "gap.jsonl")
old_time = time.time() - 10 * 60
os.utime(path_gap, (old_time, old_time))
_, out = with_transcripts({}, snap_gap, projects=projects_gap)
check("one that fell out of the window does not hold", int(out), 0)
check_true("the size of the one that fell out is kept in the snapshot",
           any(line.startswith("claude:gap ")
               for line in open(snap_gap).read().splitlines()))

os.utime(path_gap, None)          # a touch without a write — the file is fresh again
_, out = with_transcripts({}, snap_gap, projects=projects_gap)
check("one that came back into the window does not count as a new session", int(out), 0)


# A forgotten session: the transcript is there but the last entry is old. That is
# exactly what an sclaude step that was opened and left looks like.
snap_old = os.path.join(tempfile.gettempdir(), "keepawake-test-old")
if os.path.exists(snap_old):
    os.unlink(snap_old)
_, out = with_transcripts({"forgotten": 3600}, snap_old)
check("a forgotten session does not hold", int(out), 0)

# Two sessions at once are two holders: one leaving must not put out the
# other.
snap_two = os.path.join(tempfile.gettempdir(), "keepawake-test-two")
if os.path.exists(snap_two):
    os.unlink(snap_two)
_, out = with_transcripts({"one": 1, "two": 1}, snap_two)
check("two live sessions are counted separately", int(out), 2)



# The command's name in /proc/PID/stat sits in brackets and may contain spaces —
# field 4 is then not the ppid but a piece of the name. A live example from this
# machine: "npm exec chrome", where field 4 is "chrome)". Walking up the
# ancestors died on that, and with it the exclusion of our own session, meaning
# the hold would never end.
#
# We set a name with spaces through prctl(PR_SET_NAME): exec -a changes argv[0]
# while it is comm that reaches stat, so faking it through argv will not do
# here.
spaced = subprocess.Popen([sys.executable, "-c", """
import ctypes, time
ctypes.CDLL("libc.so.6").prctl(15, b"npm exec chrome", 0, 0, 0)
time.sleep(15)
"""])
time.sleep(0.6)
try:
    comm = open("/proc/%d/comm" % spaced.pid).read().strip()
    check("comm really does contain spaces", comm, "npm exec chrome")

    snippet = subprocess.run(
        ["sed", "-n", "/^ppid_of/,/^}/p",
         os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                      "bin", "keepawake")],
        capture_output=True, text=True).stdout
    got = subprocess.run(["bash", "-c", "%s\nppid_of %d" % (snippet, spaced.pid)],
                         capture_output=True, text=True).stdout.strip()
    check_true("ppid_of returns a number for a name with spaces", got.isdigit())

    bad = subprocess.run(
        ["bash", "-c", "awk '{print $4}' /proc/%d/stat" % spaced.pid],
        capture_output=True, text=True).stdout.strip()
    check_true("field 4 of stat is unreliable for such a name", not bad.isdigit())
finally:
    spaced.terminate()
    spaced.wait(timeout=5)


# ------------------------------------------- status in systemd's environment

# The fourth case in a row of "works in the terminal, breaks under systemd": the
# service's PATH contains neither ~/.local/bin nor the Windows paths. status
# reported "PowerShell not running" even though the process was alive — because
# tasklist.exe could not be found. Checking for the Windows side with a command
# that is itself missing means always getting the same wrong answer.
script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                      "bin", "keepawake")
bare = subprocess.run(
    ["env", "-i", "HOME=" + os.path.expanduser("~"), "USER=" + os.environ.get("USER", "ilia"),
     "PATH=/usr/local/bin:/usr/bin:/bin", script, "status"],
    capture_output=True, text=True, timeout=60).stdout

# The HEALTH section is always in the output — that is what we check on. The
# Windows details unfold only on a failure, and looking for them would mean
# testing what broke rather than that status did not lie.
plain = re.sub(r"\x1b\[[0-9;]*m", "", bare)
sys_line = next((l for l in plain.splitlines() if "HEALTH" in l), "")
check_true("status prints the HEALTH section", bool(sys_line))
win_line = next((l for l in plain.splitlines() if "Windows" in l and "•" in l), "")
if os.path.exists("/mnt/c/Windows/System32/tasklist.exe"):
    # Neither the traffic light nor the section's line must report the Windows
    # side dead when the cause is an unreachable tasklist.exe. We look at them
    # rather than the whole output: SSH says "not running" about itself too, and
    # confusing the two means catching someone else's failure instead of ours.
    check_true("under a bare PATH it does not report a false \"not running\"",
               "the Windows side is not holding" not in sys_line
               and "not running" not in win_line)
# The "could not ask" branch cannot be reproduced through PATH: the path to
# System32 is a constant in the script, and tasklist.exe is found even under
# env -i. So we substitute winexe itself — otherwise the "not knowing is not
# green" check would always be true and would guard nothing.
probe = r"""
eval "$(sed -n '/^cmd_status() {/,/^}$/p' %s)"
eval "$(sed -n '/^win_log() {/,/^}$/p' %s)"
eval "$(sed -n '/^human_left() {/,/^}$/p' %s)"
NOW=$(date +%%s)
state() { case "$1" in
  get) printf '%%s\n' $((NOW+3600)) $((NOW-40)) 1 "" False "09:00" 0 0 0 0 0 0 0 0 0;;
  const) echo 900;; hold) return 0;; esac; }
unit_state() { echo active; }
for f in ssh code_session tailscale claude sclaude dev vscode code_server; do
  eval "count_$f(){ echo 0; }"
done
winexe() { return 127; }
systemctl() { return 0; }
ss() { echo "LISTEN 0 128 100.0.0.1:22 0.0.0.0:*"; }
cmd_status
""" % (script, script, script)
unknown = subprocess.run(["bash", "-c", probe],
                         capture_output=True, text=True, timeout=60).stdout
check_true("an unreachable tasklist does not give a green light",
           "🟡" in unknown and "has not been checked" in unknown)
check_true("an unreachable tasklist is not passed off as a breakage",
           "🔴 HEALTH" not in unknown)

# Links inside holder names. The script marks them with control characters and
# the bot turns them into an <a href> — a divergence between these two places
# shows up nowhere else: in the terminal the markers unfold, in Telegram they
# stay as visible rubbish or end up as a 400 error.
raw = subprocess.run([script, "status", "--raw"],
                     capture_output=True, text=True, timeout=60).stdout
if "\x01" in raw:
    marked = [l for l in raw.splitlines() if "\x01" in l]
    check_true("the link marker is closed entirely",
               all("\x02" in l and "\x03" in l for l in marked))
    # Telegram rejects an <a href> on anything that does not look like a link,
    # rejecting the whole message with a 400 error — the address has to be a URL
    # with a scheme.
    addrs = re.findall("\x01([^\x02]*)\x02", raw)
    check_true("the addresses are URLs with a scheme",
               all(re.match(r"[a-z]+://", a) for a in addrs))
    # There must be no markers in the terminal: they unfold into brackets.
    plainrun = subprocess.run([script, "status"],
                              capture_output=True, text=True, timeout=60).stdout
    check_true("no markers are left in the terminal",
               not any(c in plainrun for c in "\x01\x02\x03"))
    check_true("in the terminal the address shows in brackets",
               all("(%s)" % a in plainrun for a in addrs))

# And status itself must not die with a non-zero code in such an environment.
rc = subprocess.run(
    ["env", "-i", "HOME=" + os.path.expanduser("~"), "USER=" + os.environ.get("USER", "ilia"),
     "PATH=/usr/local/bin:/usr/bin:/bin", script, "status"],
    capture_output=True, text=True, timeout=60).returncode
check("status does not die under a bare PATH", rc, 0)


# ---------------------------------------------------------- the Windows user

# Under the systemd timer PATH contains no Windows paths, and cmd.exe is not
# found there: the detector died on every run of the timer while working
# flawlessly from the terminal. Determining the name has to survive an empty
# PATH.
#
# Only where there is a Windows drive: on plain Linux there is no Windows user to
# find, and the state lives elsewhere (tests/keepawake-linux.py covers that).
saved_path = os.environ.get("PATH", "")
if os.path.isdir("/mnt/c/Windows"):
    try:
        os.environ["PATH"] = "/usr/bin:/bin"
        check_true("the Windows user's name is found without cmd.exe in PATH",
                   bool(state.win_user()))
        check_true("the state's path is assembled without cmd.exe",
                   state.state_path().startswith("/mnt/c/Users/"))
    finally:
        os.environ["PATH"] = saved_path

# An explicit setting overrides the search — that is what the tests use and what
# can save you on a machine with several profiles.
os.environ["KEEPAWAKE_WIN_USER"] = "someone"
try:
    check("KEEPAWAKE_WIN_USER takes priority", state.win_user(), "someone")
finally:
    os.environ.pop("KEEPAWAKE_WIN_USER", None)


# --------------------------------------------------------------------- time

# Everything decisions are made by has to stay a whole epoch: a string here will
# one day slip into a comparison and break it silently.
with sandbox() as box:
    with state.locked() as data:
        extend(data, NOW)
        touch(data, NOW)
    saved = json.load(open(box.path))
    check_true("until_ts is an integer", isinstance(saved["until_ts"], int))
    check_true("updated_ts is an integer", isinstance(saved["updated_ts"], int))
    check_true("the local label is a string", isinstance(saved["until_local"], str))
    check("the local label does not leak into the logic",
          should_hold(saved, NOW), True)


# -------------------------------------------------------------- concurrency

# The main test. Two processes write the state in a loop while a reader reads a
# thousand times: not one piece of broken JSON and not one lost extension.
with sandbox() as box:
    with state.locked() as data:
        touch(data, NOW)

    writer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "keepawake", "state.py")
    env = dict(os.environ)

    def hammer(seconds):
        for _ in range(12):
            subprocess.run([sys.executable, writer, "extend", str(seconds)],
                           env=env, capture_output=True)

    torn = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                with open(box.path, "r") as fh:
                    json.load(fh)
            except ValueError:
                torn.append(1)          # we read half the file
            except OSError:
                pass

    watcher = threading.Thread(target=reader)
    watcher.start()
    threads = [threading.Thread(target=hammer, args=(s,)) for s in (600, 1200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    watcher.join()

    check("not a single torn read", len(torn), 0)
    final = read(box.path)
    check_true("the state stayed valid", final["version"] == VERSION)
    # Both writers extended from "now"; the longer of them had to survive,
    # because extend takes the max rather than the last thing written.
    check_true("the extension was not lost",
               final["until_ts"] >= int(time.time()) + 1100)

    leftovers = [n for n in os.listdir(box.dir) if ".tmp." in n]
    check("the temporary files are cleared away", leftovers, [])


# ---------------------------------------------------------------- CLI

with sandbox() as box:
    env = dict(os.environ)
    writer = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "keepawake", "state.py")

    def run(*args):
        return subprocess.run([sys.executable, writer] + list(args),
                              env=env, capture_output=True, text=True)

    run("holders", "claude=1", "ssh=0", "code=0")
    saved = read(box.path)
    check("holders recorded the counter", saved["holders"]["claude"]["count"], 1)
    check_true("holders extended the deadline", saved["until_ts"] > int(time.time()) + 3000)

    out = run("get", "holders.claude.count")
    check("get fetches a nested field", out.stdout.strip(), "1")

    check("hold returns 0 while holding", run("hold").returncode, 0)

    run("release")
    saved = read(box.path)
    check("release sets the decision", saved["decision"], "sleep")
    check_true("release drops the hold", saved["until_ts"] <= int(time.time()))
    check("hold returns 1 with no hold", run("hold").returncode, 1)

    # The refusal holds while the detector runs with live holders.
    run("holders", "claude=1")
    saved = read(box.path)
    check_true("a refusal stops the detector extending",
               saved["until_ts"] <= int(time.time()))

    # A manual extension lifts the refusal — the human changed their mind.
    run("extend", "3600")
    saved = read(box.path)
    check("a manual extension lifts the refusal", saved["decision"], "")
    check_true("the manual extension restored the deadline",
               saved["until_ts"] > int(time.time()) + 3000)


# ------------------------------------------------------------- the daemon

# We check the daemon whole but without the network: the bot is substituted,
# while parsing an update and deciding are pure functions of the parsed JSON,
# which is what makes them checkable.
class FakeBot(object):
    def __init__(self):
        self.sent = []
        self.edits = []
        self.answers = []
        self.anchors = []
        self.asks = []
        self.chat_id = 12345

    def send(self, text, kb=None, quiet=False):
        # quiet as the third element rather than a separate list: the checks
        # take sent[i][0] and [1], and an appended tail does not touch them.
        self.sent.append((text, kb, quiet))
        return 777

    def edit(self, mid, text, kb=None):
        self.edits.append((mid, text))

    def answer(self, cid, text=None, alert=False):
        self.answers.append((text, alert))

    def ask(self, text, placeholder):
        self.asks.append((text, placeholder))
        return 778

    def anchor(self, text):
        self.anchors.append(text)

    def commands(self):
        pass

    def menu_button(self):
        pass


with sandbox() as box:
    os.environ["KEEPAWAKE_BOT_TOKEN"] = "test:token"
    os.environ["KEEPAWAKE_CHAT_ID"] = "12345"
    from keepawake import telegramd

    bot = FakeBot()
    handler = telegramd.Handler(bot)
    now = int(time.time())

    with state.locked() as st:
        extend(st, now, WARN_BEFORE)
        touch(st, now)
    until = read()["until_ts"]

    telegramd.check_warning(bot)
    check("the warning was sent once", len(bot.sent), 1)
    check("the deadline's stamp is recorded", read()["warned_for_ts"], until)
    check_true("the buttons carry the deadline",
               all(str(until) in b["callback_data"] for b in bot.sent[0][1][0]))

    telegramd.check_warning(bot)
    check("we do not warn twice", len(bot.sent), 1)

    # A press on yesterday's message must not extend the hold today.
    handler.callback({"id": "c1", "data": "extend:1", "message": {"message_id": 5}})
    check("a stale callback gives an alert", bot.answers[-1],
          (telegramd.t("sleep.stale"), True))
    check("a stale callback did not touch the deadline", read()["until_ts"], until)

    handler.callback({"id": "c2", "data": "extend:%d" % until,
                      "message": {"message_id": 6}})
    after = read()
    check_true("a fresh callback extended it", after["until_ts"] > until)
    check("the decision is recorded", after["decision"], "extend")

    current = read()["until_ts"]
    handler.callback({"id": "c3", "data": "sleep:%d" % current,
                      "message": {"message_id": 7}})
    after = read()
    check("the refusal is recorded", after["decision"], "sleep")
    check("after a refusal we do not hold", should_hold(after, int(time.time())), False)
    check_true("after a refusal the deadline is not in the future", after["until_ts"] <= int(time.time()) + 1)

    # A restart: the daemon kills itself, and only the next process can report
    # "I am back". The errand lives in the state because there is nowhere to
    # remember it in a dying process's memory.
    bot2 = FakeBot()
    with state.locked() as st:
        st["restart_notify"] = 42
        st["restart_from_pid"] = os.getpid() + 100000   # certainly somebody else's pid
    telegramd.report_restart(bot2)
    check("the restart was reported", len(bot2.edits), 1)
    check("reported into the same message", bot2.edits[0][0], 42)
    check("the errand is cleared", read()["restart_notify"], 0)

    # A repeat call stays quiet: otherwise every restart of the daemon (and it
    # has Restart=always) would send a message nobody asked for.
    telegramd.report_restart(bot2)
    check("with no errand it stays quiet", len(bot2.edits), 1)

    # The same process — the restart has not happened yet, it is too early to
    # report.
    with state.locked() as st:
        st["restart_notify"] = 43
        st["restart_from_pid"] = os.getpid()
    telegramd.report_restart(bot2)
    check("our own pid does not count as a restart", len(bot2.edits), 1)
    with state.locked() as st:
        st["restart_notify"] = 0
        st["restart_from_pid"] = 0

    check_true("uptime_of gives a number", isinstance(telegramd.uptime_of(1), int))

    # --- the keyboard below the input box ----------------------------------
    #
    # It is set once per language rather than at every start: it only arrives
    # together with a message, and the daemon restarts both by a button in the
    # menu and with the system. A repeat would mean a message in the chat on
    # every restart.
    bot3 = FakeBot()
    with state.locked() as st:
        st["anchor_lang"] = ""
    telegramd.ensure_anchor(bot3)
    check("the keyboard is set", len(bot3.anchors), 1)
    telegramd.ensure_anchor(bot3)
    check("we do not set it twice", len(bot3.anchors), 1)

    # A change of language has to replace it: the button's caption would stay in
    # the old one.
    was = telegramd.current()
    telegramd.set_lang("en" if was == "ru" else "ru")
    telegramd.ensure_anchor(bot3)
    check("after a change of language we set it again", len(bot3.anchors), 2)
    telegramd.set_lang(was)

    # Pressing the button opens the menu — in the current language and in the
    # previous one: the person's keyboard may have stayed labelled the old
    # way.
    from keepawake.i18n import STRINGS
    for label in STRINGS["menu.button"]:
        check_true("the '%s' button is recognised" % label,
                   telegramd.is_menu_button(label))
    check("unrelated text is not a button",
          telegramd.is_menu_button("23:30"), False)

    # The button must not be swallowed by the time parsing: having pressed it in
    # the "until what time" dialogue, a person expects the menu rather than "I
    # did not understand the time".
    bot4 = FakeBot()
    h4 = telegramd.Handler(bot4)
    with state.locked() as st:
        st["awaiting"] = "awake_until"
    h4.message({"text": STRINGS["menu.button"][0]})
    check("the button in the dialogue opens the menu", len(bot4.sent), 1)
    check("the button clears the wait", read().get("awaiting"), "")

    # We raise the input box only when we are waiting for text. Usually a person
    # presses buttons here and the phone's keyboard is in the way; for the
    # question about a time it is the other way round.
    bot6 = FakeBot()
    h6 = telegramd.Handler(bot6)
    state.write(blank())
    h6.callback({"id": "a", "data": "menu_extend", "message": {"message_id": 1}})
    check("the menu does not raise the input box", len(bot6.asks), 0)
    h6.callback({"id": "a", "data": "awake_until", "message": {"message_id": 1}})
    check("the question about a time raises the box", len(bot6.asks), 1)
    check("the hint names the format", bot6.asks[0][1], telegramd.t("awake.hint"))
    check("the question kept its 'back' button", len(bot6.edits), 2)

    # A missed format means asking again with the box ready rather than with an
    # ordinary message: otherwise the person opens the keyboard by hand once
    # more.
    h6.message({"text": "a quarter past seven"})
    check("an unparsed time asks again with the box", len(bot6.asks), 2)
    check("an unparsed time does not clear the wait",
          read().get("awaiting"), "awake_until")
    h6.message({"text": "23:30"})
    check("a parsed time does not raise the box", len(bot6.asks), 2)
    check("a parsed time clears the wait", read().get("awaiting"), "")

    # Every section reachable by buttons has a command, and each has to resolve
    # to an existing method: the list in setMyCommands is built from the same
    # table, and a typo in it would become a suggestion for a command that
    # answers "unknown command".
    from keepawake.i18n import STRINGS as CMDS
    for cname, (cmethod, ckey) in telegramd.COMMANDS.items():
        check_true("/%s leads to a method" % cname,
                   hasattr(telegramd.Handler, cmethod))
        check_true("/%s is described in i18n" % cname, ckey in CMDS)
    check("/start opens the same as /menu",
          telegramd.COMMANDS["start"], telegramd.COMMANDS["menu"])

    bot7 = FakeBot()
    h7 = telegramd.Handler(bot7)
    state.write(blank())
    for cname in ("menu", "status", "awake", "chrome", "code", "sclaude",
                  "settings"):
        before = len(bot7.sent)
        h7.message({"text": "/" + cname})
        check("/%s answers" % cname, len(bot7.sent), before + 1)

    # Arguments and the @bot_name must not get in the parsing's way: Telegram
    # appends the name itself when a command is chosen from the suggestions.
    before = len(bot7.sent)
    h7.message({"text": "/status@keepawake_bot"})
    check("a command with an @name is parsed", len(bot7.sent), before + 1)
    before = len(bot7.sent)
    h7.message({"text": "/status and something else"})
    check("a command with a tail is parsed", len(bot7.sent), before + 1)

    # /extend extends and /sleep releases — the same as the buttons.
    now7 = int(time.time())
    h7.message({"text": "/extend"})
    check_true("/extend extends", read()["until_ts"] >= now7 + HOLD_SECONDS - 5)
    h7.message({"text": "/sleep"})
    after7 = read()
    check("/sleep sets the refusal", after7["decision"], "sleep")
    check("/sleep drops the hard hold", after7["hard_hold"], False)
    check("after /sleep we do not hold", should_hold(after7, int(time.time())), False)

    # An unknown command still answers with the menu rather than staying
    # quiet.
    before = len(bot7.sent)
    h7.message({"text": "/nosuchcommand"})
    check("an unknown command answers", len(bot7.sent), before + 1)
    check("an unknown command gives the menu", bot7.sent[-1][1], telegramd.menu_keyboard())

    # A command beats an open question about a time — otherwise there would be
    # no way out of a dialogue begun by mistake except the right answer.
    with state.locked() as st:
        st["awaiting"] = "awake_until"
    h7.message({"text": "/status"})
    check("a command clears the wait", read().get("awaiting"), "")

    # --- the sleep submenu -------------------------------------------------
    now = int(time.time())
    state.write(blank())
    h5 = telegramd.Handler(FakeBot())
    h5.callback({"id": "a", "data": "awake:14400", "message": {"message_id": 1}})
    check_true("extending by four hours", read()["until_ts"] >= now + 14400)
    h5.callback({"id": "a", "data": "awake:3600", "message": {"message_id": 1}})
    check_true("a shorter deadline does not shorten it", read()["until_ts"] >= now + 14400)
    h5.callback({"id": "a", "data": "awake_forever", "message": {"message_id": 1}})
    check_true("'for ever' holds longer than a day",
               read()["until_ts"] > now + 86400)
    check_true("'for ever' is still under STALE_AFTER",
               should_hold(read(), now + STALE_AFTER + 1) is False)
    h5.callback({"id": "a", "data": "awake_release", "message": {"message_id": 1}})
    after = read()
    check("releasing sets the refusal", after["decision"], "sleep")
    check("after releasing we do not hold", should_hold(after, int(time.time())), False)

    # Parsing a time: one that has passed today means tomorrow, otherwise a
    # request for "until 7:00" at night would mean a deadline in the past, that
    # is instant sleep.
    base = int(datetime.datetime(2026, 9, 6, 22, 0).timestamp())
    check_true("an evening time is today",
               telegramd.parse_hhmm("23:30", base) == int(
                   datetime.datetime(2026, 9, 6, 23, 30).timestamp()))
    check_true("a morning time is tomorrow",
               telegramd.parse_hhmm("7:00", base) == int(
                   datetime.datetime(2026, 9, 7, 7, 0).timestamp()))
    for bad in ("25:00", "12:99", "nonsense", ""):
        check("the rubbish %r is rejected" % bad, telegramd.parse_hhmm(bad, base), 0)

    # --- a manual extension: the mark and the return to usual behaviour ----
    #
    # From the outside a manual deadline is indistinguishable from the usual
    # hour — the same until_ts. The mark exists so that status can explain "why
    # until 23:00 if a single claude is alive", and it has to go out by itself
    # without leaving the system in a special mode.
    now = int(time.time())
    st = blank()
    extend(st, now, 3 * 3600, manual=True)
    touch(st, now)
    check_true("the manual deadline is marked", state.manual_until(st, now) > 0)
    check("the stamp equals the deadline", state.manual_until(st, now), st["until_ts"])

    # An automatic extension does not set the mark: otherwise every hour of
    # claude's work would look like the human's decision.
    auto = blank()
    extend(auto, now)
    touch(auto, now)
    check("the detector does not set the stamp", state.manual_until(auto, now), 0)

    # The return to normal. There are no holders: the deadline plays out and
    # goes out along with the mark, and the usual calculation applies from
    # then on.
    after = now + 3 * 3600
    # The detector is alive all this time and refreshes the heartbeat once a
    # minute — without that should_hold would reject the state by STALE_AFTER,
    # and what was checked would be a stale file rather than the mark.
    touch(st, after - 60)
    check_true("we hold until the end", should_hold(st, after - 60))
    touch(st, after + 1)
    check("after the end we do not hold", should_hold(st, after + 1), False)
    check("the stamp went out by itself", state.manual_until(st, after + 1), 0)

    # The warning comes half an hour before a manual deadline too — otherwise a
    # long extension would end unasked.
    warn_at = after - WARN_BEFORE + 60
    touch(st, warn_at)
    check_true("we warn about a manual deadline too", needs_warning(st, warn_at))

    # A holder that comes back gives exactly an hour again rather than the
    # remainder of the manual deadline.
    revived = dict(st)
    extend(revived, after + 3600)
    touch(revived, after + 3600)
    check("after a manual deadline, the usual hour",
          revived["until_ts"], after + 3600 + HOLD_SECONDS)
    check("and now without the stamp", state.manual_until(revived, after + 3600), 0)

    # Lights-out clears the mark immediately: otherwise status would talk about
    # an extension the human took away from themselves.
    dropped = blank()
    extend(dropped, now, 3 * 3600, manual=True)
    dropped["until_ts"] = now
    state.drop_manual(dropped)
    check("lights-out clears the stamp", state.manual_until(dropped, now), 0)

    # The mark cannot outlive the general deadline: "release the holds" lowers
    # until_ts, and talking about a manual extension after that will not do.
    orphan = blank()
    extend(orphan, now, 3 * 3600, manual=True)
    orphan["until_ts"] = now          # the deadline was lowered and the stamp was left
    check("the stamp does not outlive the deadline", state.manual_until(orphan, now), 0)

    # A stale file cancels a manual hold too: a silent WSL can confirm nothing,
    # however distant the deadline.
    stale = blank()
    extend(stale, now, 7 * 24 * 3600, manual=True)
    touch(stale, now + 3600)          # the detector is alive
    check_true("a week-long deadline holds", should_hold(stale, now + 3600))
    touch(stale, now)                 # and now it has fallen silent
    check("a stale file beats the deadline",
          should_hold(stale, now + STALE_AFTER + 60), False)

    # --- the language switch -----------------------------------------------
    #
    # The flag's point is that it survives the next update: language_code
    # arrives with every press, and without pinning the choice would live until
    # the very first button — that is, the switch would be useless.
    state.write(blank())
    telegramd.set_lang("en")
    bot5 = FakeBot()
    h6 = telegramd.Handler(bot5)
    en = {"from": {"language_code": "en-GB"}}

    h6.callback(dict(id="l1", data="lang:ru", message={"message_id": 1}, **en))
    check("the choice is recorded", read()["lang"], "ru")
    check("the choice is pinned", read()["lang_pinned"], True)
    check("the language switched", telegramd.current(), "ru")

    telegramd.remember_lang({"language_code": "en-GB"})
    check("the client does not override a pinned language", telegramd.current(), "ru")
    check("the pin holds", read()["lang_pinned"], True)

    h6.callback(dict(id="l2", data="lang:auto", message={"message_id": 1}, **en))
    check("the pin is removed", read()["lang_pinned"], False)
    check("the language is taken from the press", telegramd.current(), "en")
    telegramd.remember_lang({"language_code": "ru-RU"})
    check("without a pin the client leads again", telegramd.current(), "ru")

    # The language screen marks the current choice with exactly one dot —
    # otherwise it is unclear what is chosen at all.
    for pin, lang, want in (("ru", "ru", 1), ("en", "en", 1), (None, None, 1)):
        state.write(blank())
        if pin:
            telegramd.set_lang(pin)
            with state.locked() as st:
                st["lang"], st["lang_pinned"] = pin, True
        marks = sum(b["text"].startswith("● ")
                    for row in telegramd.lang_keyboard() for b in row)
        check("one selection mark (%s)" % (pin or "auto"), marks, want)
    telegramd.set_lang(was)

    # --- there is a way out of every screen --------------------------------
    #
    # The Sclaude button once opened a screen where "back" led only to the
    # repositories, and from there to Settings, that is into a branch the person
    # never opened. There must be no dead ends in either language.
    from keepawake.i18n import STRINGS as S
    backs = set(S["menu.back"])
    for lang in ("ru", "en"):
        telegramd.set_lang(lang)
        screens = {
            "keepawake": telegramd.awake_keyboard(),
            "chrome": telegramd.chrome_keyboard(),
            "code-server": telegramd.code_keyboard(),
            "settings": telegramd.services_keyboard(),
            "docs": telegramd.docs_keyboard(),
            "lang": telegramd.lang_keyboard(),
            "repos": telegramd.repos_keyboard(),
            "features": telegramd.features_keyboard("instruments"),
            "features-empty": telegramd.features_keyboard("no-such-repo"),
        }
        for name, kb in screens.items():
            texts = [b["text"] for row in kb for b in row]
            check_true("%s/%s: there is a way out" % (lang, name),
                       any(x in backs for x in texts))
    telegramd.set_lang(was)

    # Choosing a repository. sclaude works only inside a repository, and a
    # person has several — from the home directory, where systemd starts the
    # daemon, it complained "not a git repository".
    with state.locked() as st:
        st["sclaude_repo"] = ""
    check("with no choice, empty", telegramd.repo_choice(), "")

    with state.locked() as st:
        st["sclaude_repo"] = "/net/takogo/repo"
    check("a non-existent choice is discarded", telegramd.repo_choice(), "")

    real = telegramd.known_repos()
    if real:
        with state.locked() as st:
            st["sclaude_repo"] = real[0]
        check("a choice of an existing repository holds",
              telegramd.repo_choice(), real[0])
        marks = [b["text"] for row in telegramd.repos_keyboard() for b in row]
        check("the chosen one is marked exactly once",
              sum(1 for m in marks if m.startswith("● ")), 1)
        check("there is no 'all at once' item any more",
              any("all at once" in m for m in marks), False)

    # Parsing the sclaude status table: the menu's second level is buttons onto
    # features, and it is built from these columns.
    sample = ("FEATURE                STEP           WORKTREE\n"
              "34-sample-site         2. code        /home/u/myapp-34\n"
              "password-change        4. review      /home/u/myapp-pw\n")
    saved_run = telegramd.run
    telegramd.run = lambda cmd, timeout=25: sample
    # The buttons are built for a repository by name, and the name is looked up
    # among the git repositories in HOME. Left to the real HOME this section
    # passed only on a machine that happened to have ~/myapp checked out.
    saved_known = telegramd.known_repos
    telegramd.known_repos = lambda: ["/nonexistent/myapp"]
    try:
        feats, raw = telegramd.features_of("/tmp/whatever")
        check("features parsed", len(feats), 2)
        check("the feature's name", feats[0][0], "34-sample-site")
        check("the feature's step in full", feats[0][1], "2. code")
        check("the worktree separately", feats[0][2], "/home/u/myapp-34")
        check("the table's header did not get into the features",
              any(f[0] == "FEATURE" for f in feats), False)

        labels = [b["text"] for row in telegramd.features_keyboard("myapp")
                  for b in row]
        check_true("the button has the name and the step", "34-sample-site — 2. code" in labels)

        # The message above the buttons is one line. An sclaude status table
        # below it would repeat the buttons: a feature's name and step stand on
        # them, there is nothing on a phone to open a worktree path with, and the
        # branch breakdown is about branches without features, that is about
        # exactly what is not in this list.
        body = telegramd.repo_text("myapp")
        check_true("the message has the number of features", "2" in body)
        check_true("there is no table under the header", "FEATURE" not in body)
        check_true("the worktree is not shown", "/home/u" not in body)
        check_true("there is no branch breakdown", "Branches in progress" not in body)
        check_true("the message is one line", len(body.strip().splitlines()) == 1)
        check_true("there is no path on the button",
                   not any("/home/u" in l for l in labels))

        # Every feature button addresses its own feature — otherwise a press
        # would open somebody else's. A feature's row is now two buttons: the
        # wide one drives the step, the narrow one leads to the list of actions
        # on the same feature.
        datas = [b["callback_data"] for row in telegramd.features_keyboard("myapp")
                 for b in row if b["callback_data"].startswith("go:")]
        check("a callback for every feature", len(datas), 2)
        check_true("the callback carries the repository and the feature",
                   datas[0] == "go:myapp:34-sample-site")
        acts = [b["callback_data"] for row in telegramd.features_keyboard("myapp")
                for b in row if b["callback_data"].startswith("acts:")]
        check("an actions button for every feature", len(acts), 2)
        check_true("the actions button carries the same feature",
                   acts[0] == "acts:myapp:34-sample-site")
    finally:
        telegramd.known_repos = saved_known
        telegramd.run = saved_run

    # A repository with no features shows the main branch's state: the person
    # opened it to learn something, and an empty "no features" line does not
    # answer that.
    real_repo = telegramd.known_repos()
    if real_repo:
        rname = os.path.basename(real_repo[0])
        st_main = telegramd.main_branch_state(real_repo[0])
        check_true("the state is named",
                   any(m in st_main["extra"] for m in ("✅", "⚠️", "⬆️")))
        if not st_main["empty"]:
            check_true("the branch is determined", st_main["branch"] not in ("", "?"))
            check_true("the commit is determined", st_main["commit"] not in ("", "?"))

        # No text must show git's raw complaints: git's format and python's %
        # substitution have already fought once (%%s was eaten by the second
        # pass), and a fresh repository with no commits answers every question
        # with a fatal line. Neither is what one shows a person.
        for repo in telegramd.known_repos():
            body = telegramd.repo_text(os.path.basename(repo))
            check("no git complaints in the text of %s" % os.path.basename(repo),
                  "fatal:" in body, False)

    # A repository with no features: there are no feature buttons, but the way
    # out upwards remains.
    telegramd.run = lambda cmd, timeout=25: "No features in progress."
    try:
        feats, _ = telegramd.features_of("/tmp/whatever")
        check("no features, no rows", feats, [])
        rows = telegramd.features_keyboard("myapp")
        # We count the exits rather than the rows: there are now two navigation
        # rows ("to the repositories" and "to the main menu"), and tying to their
        # number would break on any rearrangement. Only one thing matters — that
        # there is somewhere to go from here.
        labels = [b["text"] for row in rows for b in row]
        targets = [b["callback_data"] for row in rows for b in row]
        check("there are no feature buttons", [x for x in targets if x.startswith("feat:")], [])
        check_true("the way out to the repositories", "svc_repos" in targets)
        check_true("the way out to the main menu", "menu_back" in targets)
    finally:
        telegramd.run = saved_run

    # Routing the callbacks. A check for "has a colon" has already intercepted
    # repo: and feat: once — they appeared after the sleep buttons, and a press
    # on a repository answered "the message is out of date". Every button has to
    # land in its own branch, and that must break in the tests rather than on the
    # phone.
    with state.locked() as st:
        state.extend(st, int(time.time()))
        state.touch(st, int(time.time()))
    live = read()["until_ts"]

    saved_run = telegramd.run
    telegramd.run = lambda cmd, timeout=25: "No features in progress."
    try:
        # Every button is run through the real handler. Checking the keyboards
        # and the texts separately is not enough: the docs section passed the
        # tests that way and died in the bot — a local variable shadowed an
        # imported function, and that is visible only when it is called.
        routed = ["menu_extend", "menu_status", "menu_chrome", "menu_services",
                  "menu_back", "menu_code", "svc_repos", "svc_sclaude",
                  "svc_docs", "repo:myapp", "feat:myapp:nothing",
                  "chrome_start", "code_start", "idle_keep", "noop",
                  "devopen:no-such-feature", "devstop:no-such-feature"]
        from keepawake import docs as _docs
        routed += ["doc:" + k for k in _docs.SECTIONS]
        for data in routed:
            probe = FakeBot()
            try:
                telegramd.Handler(probe).callback(
                    {"id": "x", "data": data, "message": {"message_id": 9}})
            except Exception as exc:
                failures.append(("the %s button dies" % data, "no errors", exc))
                continue
            said_stale = any("out of date" in (e[1] or "") for e in probe.edits)
            check("%s does not go into the sleep handler" % data, said_stale, False)
            if data != "noop":      # a row caption is silent on purpose
                check_true("%s answered something" % data,
                           bool(probe.edits or probe.sent))

        # The sleep buttons, on the other hand, have to go there.
        for data in ("extend:%d" % live, "sleep:%d" % live):
            probe = FakeBot()
            telegramd.Handler(probe).callback(
                {"id": "x", "data": data, "message": {"message_id": 9}})
            check_true("%s is handled as a decision" % data.split(":")[0],
                       bool(probe.edits))
    finally:
        telegramd.run = saved_run

    with state.locked() as st:
        st["sclaude_repo"] = ""

    os.environ.pop("KEEPAWAKE_BOT_TOKEN", None)
    os.environ.pop("KEEPAWAKE_CHAT_ID", None)


# --------------------------------------------------------------- the menu

os.environ["KEEPAWAKE_BOT_TOKEN"] = "test:token"
os.environ["KEEPAWAKE_CHAT_ID"] = "12345"
from keepawake import telegramd as tg_menu

# The main menu's layout: sclaude and code-server live at the top level rather
# than hidden in the settings — they are what people reach for most often.
top = [b["callback_data"] for row in tg_menu.menu_keyboard() for b in row]
check_true("code-server at the top level", "menu_code" in top)
check_true("sclaude at the top level", "svc_sclaude" in top)
check_true("chrome at the top level", "menu_chrome" in top)

# And they are not duplicated in the settings.
inner = [b["callback_data"] for row in tg_menu.services_keyboard() for b in row]
check("sclaude is not duplicated in the settings", "svc_sclaude" in inner, False)
check_true("the repository stayed in the settings", "svc_repos" in inner)

# code-server's password must not reach the message: it would settle in the
# chat's history and on Telegram's servers for ever.
cfg = os.path.expanduser("~/.config/code-server/config.yaml")
if os.path.exists(cfg):
    secret = ""
    for line in open(cfg):
        if line.startswith("password:"):
            secret = line.split(":", 1)[1].strip()
    if secret:
        check("the password does not reach the card", secret in tg_menu.code_text(), False)
    # The Chrome card reminds you which address to look at the project on: the
    # browser's window stands on the laptop, and a person on a phone needs the
    # link rather than the browser itself.
    # The Chrome card lists every feature sclaude has registered, each with a
    # link for the phone and the address for the laptop, read from the same
    # registry the proxy reads.
    reg = tempfile.mkdtemp(prefix="keepawake-test-registry-")
    wt = tempfile.mkdtemp(prefix="keepawake-test-feature-")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    with open(os.path.join(wt, ".sclaude/local/feature", "state.json"), "w") as fh:
        json.dump({"dev": {"label": "sample-one", "port": 1}}, fh)
    os.symlink(wt, os.path.join(reg, "sample-one"))
    os.symlink("/nonexistent", os.path.join(reg, "gone"))
    saved_registry = tg_menu.DEV_REGISTRY
    tg_menu.DEV_REGISTRY = reg
    try:
        chrome_body = tg_menu.chrome_text()
        # The phone has no *.localhost: its link goes through the proxy's page
        # that picks the feature with a cookie — at the tailscale serve name
        # when there is one, since only a name survives a sign-in.
        check_true("the phone link picks the feature through the proxy",
                   'href="%s/__sclaude/select?f=sample-one"' % tg_menu.phone_origin()
                   in chrome_body)
        saved_run = tg_menu.run
        try:
            tg_menu.run = lambda cmd, timeout=25: json.dumps({"Web": {
                "box.tail1.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}}}) \
                if "serve status" in cmd else saved_run(cmd, timeout)
            check("a tailscale serve name in front of :3000 is the phone's origin",
                  tg_menu.phone_origin(), "https://box.tail1.ts.net")
            tg_menu.run = lambda cmd, timeout=25: "" if "serve status" in cmd else saved_run(cmd, timeout)
            check_true("without it, the node's own address",
                       tg_menu.phone_origin().endswith(":%d" % tg_menu.DEV_PORT))
        finally:
            tg_menu.run = saved_run
        check_true("the laptop address is the feature's own name",
                   "<code>http://sample-one.localhost:%d</code>" % tg_menu.DEV_PORT
                   in chrome_body)
        check_true("a feature whose server is down says so", "⏹" in chrome_body)
        check("a link to a tree that is gone is left out", "gone" in chrome_body, False)
        check_true("the proxy's state is named", "sclaude-proxy" in chrome_body)

        rows = tg_menu.chrome_keyboard()
        datas = [b.get("callback_data") for row in rows for b in row]
        check_true("the first row is the browser",
                   any(b["callback_data"].startswith("chrome_") for b in rows[0]))
        check_true("each feature can be opened", "devopen:sample-one" in datas)
        check("a stopped feature has no stop button", "devstop:sample-one" in datas, False)
        check("the last row goes back", rows[-1][0]["callback_data"], "menu_back")
        # The row caption is not a button: pressing it must do nothing.
        check_true("the row captions are marked noop", "noop" in datas)

        # 📱: while the gate is down it is a callback that opens it, and nothing
        # is on the internet; once the gate runs, the same button is the Mini
        # App at the funnel's address, and a row closes the access again.
        check_true("a closed gate: 📱 opens it", "devphone:sample-one" in datas)
        check("a closed gate: no Mini App yet",
              any("web_app" in b for row in rows for b in row), False)
        check("a closed gate: nothing to close", "gate_stop" in datas, False)
        saved_run = tg_menu.run
        try:
            def gate_up(cmd, timeout=25):
                if "is-active" in cmd and tg_menu.GATE_UNIT in cmd:
                    return "active"
                if "tailscale status" in cmd:
                    return json.dumps({"Self": {"DNSName": "box.tail1.ts.net."}})
                return saved_run(cmd, timeout)
            tg_menu.run = gate_up
            check("the funnel address is the node's name on :8443",
                  tg_menu.gate_origin(), "https://box.tail1.ts.net:8443")
            rows = tg_menu.chrome_keyboard()
            apps = [b["web_app"]["url"] for row in rows for b in row if "web_app" in b]
            check("an open gate: 📱 is the Mini App", apps,
                  ["https://box.tail1.ts.net:8443/__sclaude/tg?f=sample-one"])
            check_true("an open gate can be closed",
                       "gate_stop" in [b.get("callback_data") for row in rows for b in row])
            check_true("the card says the phone access is open",
                       tg_menu.t("chrome.gateup") in tg_menu.chrome_text())
            tg_menu.run = lambda cmd, timeout=25: "" if "tailscale status" in cmd \
                else gate_up(cmd, timeout)
            check("no tailnet name: no Mini App, the callback stays",
                  "devphone:sample-one" in [b.get("callback_data")
                                            for row in tg_menu.chrome_keyboard() for b in row],
                  True)
        finally:
            tg_menu.run = saved_run
    finally:
        tg_menu.DEV_REGISTRY = saved_registry
        shutil.rmtree(reg, ignore_errors=True)
        shutil.rmtree(wt, ignore_errors=True)

    # nvm lies outside the service's PATH, and without it sclaude dev died with
    # "setsid: failed to execute npm". The version is read dynamically: a
    # hardcoded one would break quietly when Node was updated.
    nvm = tg_menu.nvm_bin()
    if os.path.isdir(os.path.expanduser("~/.nvm/versions/node")):
        check_true("nvm's directory is found", bool(nvm) and os.path.isdir(nvm))
        check_true("npm is visible to the bot's commands",
                   tg_menu.run("command -v npm").endswith("npm"))

    # port_open must not lie: a closed port is False, an open one True.
    check("a closed port is not open", tg_menu.port_open(59999), False)

    # code-server opens the same repository as the one chosen for sclaude: two
    # different "current projects" would confuse somebody who switched one and
    # expects the second to have switched too.
    saved_choice = read().get("sclaude_repo") or ""
    repos_now = tg_menu.known_repos()
    if repos_now:
        with state.locked() as st:
            st["sclaude_repo"] = repos_now[0]
        check("the folder follows the choice",
              tg_menu.code_folder(), os.path.basename(repos_now[0]))
        check_true("the folder reaches the card",
                   os.path.basename(repos_now[0]) in tg_menu.code_text())
    with state.locked() as st:
        st["sclaude_repo"] = ""
    check("with no choice the home directory opens", tg_menu.code_folder(), "~")
    with state.locked() as st:
        st["sclaude_repo"] = saved_choice

    # systemd inside WSL starts the Windows side rather than the Windows startup
    # folder: while the distribution is not running there is nobody to hold for,
    # and a process hanging there is not wanted. ExecStop is essential — without
    # it the process would outlive WSL stopping.
    winunit = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "systemd", "keepawake-windows.service")).read()
    check_true("the Windows side starts with WSL", "[Install]" in winunit)
    check_true("and is shut down on stop", "ExecStop=" in winunit)
    win_lines = [l.strip() for l in winunit.split("\n") if not l.strip().startswith("#")]
    check("StartLimitIntervalSec is not in [Service]",
          any(l == "StartLimitIntervalSec=0" for l in win_lines[win_lines.index("[Service]"):])
          if "[Service]" in win_lines else False, False)

    # Finding the process on that side must not rely on nested quotes: doubled
    # '' are lost when passed through bash, and the WMI query becomes invalid —
    # the check silently failed to find a live process.
    winwrap = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "bin", "keepawake-windows")).read()
    check("there is no WMI filter with nested quotes", "-Filter \"Name=''" in winwrap, False)
    check_true("the process is found by its command line", "KeepAwake.ps1" in winwrap)

    # code-server goes out by itself after an hour of idling, so it does not come
    # up at boot: autostart would bring back to life what had just gone out.
    unit = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "systemd", "code-server.service")).read()
    # We look for the directive at the start of a line rather than for a
    # substring: the words "[Install]" and "WantedBy" occur in the comments that
    # explain why they are not here — and a containment check caught its own
    # explanation.
    unit_lines = [l.strip() for l in unit.split("\n") if not l.strip().startswith("#")]
    check("code-server has no [Install] section", "[Install]" in unit_lines, False)
    check("code-server has no WantedBy",
          any(l.startswith("WantedBy=") for l in unit_lines), False)
    check_true("exiting on idle does not count as a failure",
               "Restart=on-failure" in unit)

    cfg_path = os.path.expanduser("~/.config/code-server/config.yaml")
    if os.path.exists(cfg_path):
        check_true("the idle timeout is set",
                   "idle-timeout-seconds" in open(cfg_path).read())

    # The forward to localhost has to wait until the server opens its port:
    # otherwise the first request after idling was cut off, and the link had to
    # be pressed twice.
    proxy = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                              "systemd", "code-server-local.service")).read()
    check_true("the forward brings the server up", "Requires=code-server.service" in proxy)
    # The forward must have no [Install]: with one the service starts at boot and
    # drags code-server along through Requires= — exactly what the absence of
    # [Install] on the server itself avoids. It is the socket that must be
    # enabled.
    proxy_lines = [l.strip() for l in proxy.split("\n") if not l.strip().startswith("#")]
    check("the forward has no [Install] section", "[Install]" in proxy_lines, False)
    sock = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "systemd", "code-server-local.socket")).read()
    check_true("the socket is enabled rather than the service", "WantedBy=sockets.target" in sock)

    # Waiting for the port to be ready and the address from the config live in
    # the wrapper: systemd cannot substitute a command's output into ExecStart,
    # and a hardcoded address would survive a change of the node's address
    # silently.
    wrapper = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "bin", "code-server-proxy")).read()
    check_true("the forward waits for the port to be ready", "/dev/tcp/" in wrapper)
    check_true("the address is read from the config", "bind-addr" in wrapper)
    # We look at the code rather than the text: the address is mentioned in the
    # comments that explain why it is not here — and a substring check caught its
    # own explanation.
    def code_only(text):
        return "\n".join(l for l in text.split("\n") if not l.strip().startswith("#"))
    check("the address is not hardcoded in the wrapper", "100.72" in code_only(wrapper), False)
    check("the address is not hardcoded in the unit", "100.72" in code_only(proxy), False)

    # The start wrapper has to survive an empty or broken choice: a failed
    # service is worse than an empty editor.
    starter = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "bin", "code-server-start")
    check_true("the start wrapper is in place", os.access(starter, os.X_OK))
    body = open(starter).read()
    check_true("the wrapper falls back to $HOME", '"$HOME"' in body)

    check_true("the link points at the address from the config",
               tg_menu.code_url().startswith("http://"))
    # Telegram makes a link only of what looks like a domain or an IP.
    # "localhost" does not qualify: it stays text even inside an explicit
    # <a href>, which is additionally rejected with a 400 error.
    body = tg_menu.code_text()
    check("localhost is not used as a link", "localhost:8080" in body, False)
    check_true("the local address is given as an IP", "127.0.0.1:8080" in body)

os.environ.pop("KEEPAWAKE_BOT_TOKEN", None)
os.environ.pop("KEEPAWAKE_CHAT_ID", None)


# ------------------------------------------------------------------ access

# The bot drives somebody's machine, so the access checks have to be in the
# tests rather than only in someone's head.
os.environ["KEEPAWAKE_BOT_TOKEN"] = "test:token"
os.environ["KEEPAWAKE_CHAT_ID"] = "12345"
from keepawake import telegramd as tg_acl

# A repository's name arrives in callback_data and reaches a shell command. Even
# with shlex.quote it is unwise to rely on escaping alone: the name has to come
# from the list of known repositories.
for evil in ("../../etc", "..", "no-such-repo", "myapp; rm -rf /", "", "/etc"):
    check("a forged repository name is rejected: %r" % evil,
          tg_acl.repo_path(evil), "")

real_names = [os.path.basename(r) for r in tg_acl.known_repos()]
if real_names:
    check_true("a real name passes", bool(tg_acl.repo_path(real_names[0])))

# A command with a forged name must execute nothing.
saved_run = tg_acl.run
executed = []
tg_acl.run = lambda cmd, timeout=25: executed.append(cmd) or "No features in progress."
try:
    tg_acl.features_of_name("../../etc")
    check("no command is launched for a foreign name", executed, [])
finally:
    tg_acl.run = saved_run

# A foreign chat must not be handled at all — that is the only thing separating
# the machine from anyone who finds the bot by name.
check_true("the chat_id check is in the update parsing",
           'get("id") != bot.chat_id' in open(
               os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "keepawake", "telegramd.py")).read())

os.environ.pop("KEEPAWAKE_BOT_TOKEN", None)
os.environ.pop("KEEPAWAKE_CHAT_ID", None)


# ---------------------------------------------------------------- the docs

# The docs have to survive a reinstall six months from now, so they must not
# break silently: Telegram rejects a whole message on invalid markup or an
# exceeded limit, and the person would see emptiness instead of help.
from keepawake import docs as docs_mod

check_true("the sections are there", len(docs_mod.SECTIONS) >= 5)
for key in docs_mod.SECTIONS:
    for lang in ("ru", "en"):
        body_d = docs_mod.section(key, lang)
        check_true("%s/%s is non-empty" % (key, lang), len(body_d) > 200)
        # Telegram's ceiling is 4096 bytes, so we count in those rather than
        # characters: Cyrillic takes two apiece.
        check_true("%s/%s fits within the limit" % (key, lang),
                   len(body_d.encode()) < 4000)
        # Paired tags: an unclosed <b> leads to the whole message being
        # rejected.
        for tag in ("b", "i", "code"):
            check("%s/%s the %s tags are paired" % (key, lang, tag),
                  body_d.count("<%s>" % tag), body_d.count("</%s>" % tag))
        # Telegram does not forgive bare < and > outside tags.
        stripped = re.sub(r"</?(b|i|code)>", "", body_d)
        check("%s/%s has no unescaped brackets" % (key, lang),
              "<" in stripped.replace("&lt;", "").replace("&gt;", ""), False)

check("an unknown section does not bring it down", docs_mod.section("nope", "ru"), "")

# Every menu button has to lead to an existing section, otherwise a press
# silently returns to the menu.
os.environ["KEEPAWAKE_BOT_TOKEN"] = "test:token"
os.environ["KEEPAWAKE_CHAT_ID"] = "12345"
from keepawake import telegramd as tg_docs
doc_buttons = [b["callback_data"] for row in tg_docs.docs_keyboard() for b in row
               if b["callback_data"].startswith("doc:")]
check("there are as many buttons as sections",
      len(doc_buttons), len(docs_mod.SECTIONS))
for cb in doc_buttons:
    check_true("the %s button leads to a section" % cb,
               bool(docs_mod.section(cb.split(":", 1)[1], "ru")))
os.environ.pop("KEEPAWAKE_BOT_TOKEN", None)
os.environ.pop("KEEPAWAKE_CHAT_ID", None)


# A code-server tab holds the machine without a TTY: the person reads code
# without typing anything. Its heartbeat is as much a sign of presence as a
# keystroke, otherwise an open tab looks like "an hour without input".
ka_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "bin", "keepawake")).read()
idle_fn = ka_src[ka_src.index("idle_seconds()"):]
idle_fn = idle_fn[:idle_fn.index("\n}")]
check_true("idling takes code-server's heartbeat into account",
           "CODE_HEARTBEAT" in idle_fn)


# ------------------------------------------- the reason for imminent sleep

# "It will sleep in 30 minutes" does not by itself say what has happened. There
# are three reasons, and the decision made by button depends on them.
os.environ["KEEPAWAKE_BOT_TOKEN"] = "test:token"
os.environ["KEEPAWAKE_CHAT_ID"] = "12345"
from keepawake import telegramd as tg_why

now_w = int(time.time())
reason_nobody = tg_why.sleep_reason({"holders": {}}, now_w)
reason_soft = tg_why.sleep_reason(
    {"holders": {"claude": {"count": 1}}}, now_w)
reason_refused = tg_why.sleep_reason(
    {"holders": {"ssh": {"count": 1}}, "decision": "sleep",
     "decision_ts": now_w, "until_ts": now_w}, now_w)

check_true("the 'nobody is left' reason is non-empty", len(reason_nobody) > 20)
check_true("the reason distinguishes soft holders", reason_soft != reason_nobody)
check_true("the reason distinguishes a refusal", reason_refused != reason_nobody)
check_true("with soft holders they are named themselves", "Claude" in reason_soft)

# The warning must carry the reason rather than only the time.
with sandbox():
    with state.locked() as st:
        extend(st, now_w, WARN_BEFORE)
        touch(st, now_w)
        st["holders"]["claude"] = {"count": 1, "seen_ts": now_w}
    probe = FakeBot()
    tg_why.check_warning(probe)
    check("the warning was sent", len(probe.sent), 1)
    body_w = probe.sent[0][0]
    check_true("the text has the reason", "Claude" in body_w)
    check_true("the text says what comes next", "Windows" in body_w or "15" in body_w)

os.environ.pop("KEEPAWAKE_BOT_TOKEN", None)
os.environ.pop("KEEPAWAKE_CHAT_ID", None)


# ----------------------------------------------- forgotten hard holders

# Hard holders can be left over from a forgotten session: SSH is open and the
# person has gone. We ask once an hour — but only when there really are no traces
# of work, otherwise the question would interrupt a long build.
os.environ["KEEPAWAKE_BOT_TOKEN"] = "test:token"
os.environ["KEEPAWAKE_CHAT_ID"] = "12345"
from keepawake import telegramd as tg_idle

def idle_state(**kw):
    now_i = int(time.time())
    base = dict(hard_hold=True, busy=0, idle_seconds=5000, hard_since=now_i - 9000,
                idle_asked_ts=0, until_ts=now_i + 600, updated_ts=now_i)
    base.update(kw)
    with state.locked() as st:
        st.update(base)

with sandbox():
    cases = [
        ("idling with a hard holder — we ask", {}, 1),
        ("the machine is busy — we stay quiet", {"busy": 1}, 0),
        ("recent input — we stay quiet", {"idle_seconds": 300}, 0),
        ("no hard holders — we stay quiet", {"hard_hold": False}, 0),
        ("we asked just now — we stay quiet",
         {"idle_asked_ts": int(time.time())}, 0),
    ]
    for name, kw, want in cases:
        idle_state(**kw)
        probe = FakeBot()
        tg_idle.check_idle_hold(probe)
        check(name, len(probe.sent), want)

    # 999999 is the placeholder for "no interactive sessions at all" rather than
    # "a very long idle". Because of that a "277 hours without input" once
    # arrived about a machine that had been working since the day before.
    idle_state(idle_seconds=tg_idle.IDLE_UNKNOWN)
    probe = FakeBot()
    tg_idle.check_idle_hold(probe)
    check("with an unknown idle we stay quiet", len(probe.sent), 0)

    # hard_since=0 means "we are holding but do not know since when". "It has
    # not slept for 0 minutes" is the first thing read in the message, and lying
    # there will not do.
    idle_state(hard_since=0)
    probe = FakeBot()
    tg_idle.check_idle_hold(probe)
    check("with no start of the hold we stay quiet", len(probe.sent), 0)

    # Three options, and each does its own thing.
    idle_state()
    probe = FakeBot()
    tg_idle.check_idle_hold(probe)
    buttons = [b["callback_data"] for row in probe.sent[0][1] for b in row]
    check("three options", len(buttons), 3)
    check_true("there is a 'carry on'", "idle_keep" in buttons)
    check_true("there is a way into the menu", "menu_extend" in buttons)
    check_true("there is a 'sleep'", "idle_sleep" in buttons)

    # "Sleep" drops both the hard hold and the deadline — otherwise the button
    # would be useless with a live SSH session.
    idle_state()
    probe = FakeBot()
    tg_idle.Handler(probe).callback(
        {"id": "x", "data": "idle_sleep", "message": {"message_id": 9}})
    after_sleep = read()
    check("sleep drops the hard hold", after_sleep["hard_hold"], False)
    check("sleep sets the refusal", after_sleep["decision"], "sleep")
    check("after sleeping we do not hold",
          should_hold(after_sleep, int(time.time())), False)

    # And the detector will not bring the hold back while the refusal lives:
    # they pressed "sleep" knowing about the live session.
    with state.locked() as st:
        refused_now = refuses(st, int(time.time()))
        st["hard_hold"] = True and not refused_now
    check("the detector does not resurrect the hold under a refusal",
          read()["hard_hold"], False)

    # "Carry on" changes nothing but postpones the next question by an hour.
    idle_state()
    probe = FakeBot()
    tg_idle.Handler(probe).callback(
        {"id": "x", "data": "idle_keep", "message": {"message_id": 9}})
    kept = read()
    check("carrying on does not touch the hold", kept["hard_hold"], True)
    check_true("carrying on postpones the question", kept["idle_asked_ts"] > 0)
    probe2 = FakeBot()
    tg_idle.check_idle_hold(probe2)
    check("right after 'carry on' we do not ask", len(probe2.sent), 0)

os.environ.pop("KEEPAWAKE_BOT_TOKEN", None)
os.environ.pop("KEEPAWAKE_CHAT_ID", None)


# -------------------------------------------------------------- language

# Telegram reports the client's language in from.language_code. Russian stays
# for those whose client is Russian; everyone else gets English.
from keepawake import i18n

# English by default: Russian is switched on by an explicit sign rather than by
# an absence of data.
for code, want in (("ru", "ru"), ("ru-RU", "ru"), ("RU", "ru"),
                   ("en", "en"), ("en-GB", "en"), ("de", "en"),
                   ("uk", "en"), (None, "en"), ("", "en")):
    check("language_code %r" % code, i18n.normalize(code), want)
check("the default language is English", i18n.DEFAULT, "en")

# Plural forms: Russian needs three of them, and 11 and 21 are the usual place
# for a mistake. The expected strings below are Russian on purpose — this is the
# bilingual half of the bot (see i18n.py), and the check exists for it.
i18n.set_lang("ru")
check("ru: 1 session", i18n.ssh_holders(1), "1 SSH-сессия")
check("ru: 2 sessions", i18n.ssh_holders(2), "2 SSH-сессии")
check("ru: 5 sessions", i18n.ssh_holders(5), "5 SSH-сессий")
check("ru: 11 sessions", i18n.ssh_holders(11), "11 SSH-сессий")
check("ru: 21 sessions", i18n.ssh_holders(21), "21 SSH-сессия")
i18n.set_lang("en")
check("1 session", i18n.ssh_holders(1), "1 SSH session")
check("2 sessions", i18n.ssh_holders(2), "2 SSH sessions")

# No string must be lost in translation: both halves of a pair are filled in,
# otherwise the bot shows emptiness instead of text.
empty = [k for k, pair in i18n.STRINGS.items() if not pair[0] or not pair[1]]
check("there are no empty translations", empty, [])
same_key = [k for k in i18n.STRINGS if i18n.t(k) == k]
check("every key resolves", same_key, [])

# An unknown key must not bring the bot down — it returns the key itself.
check("an unknown key is safe", i18n.t("no.such.key"), "no.such.key")

# Substitutions work in both languages.
for lang in ("ru", "en"):
    i18n.set_lang(lang)
    out = i18n.t("sleep.extended", at="12:34")
    check_true("substitution %s" % lang, "12:34" in out)

i18n.set_lang("ru")


# ------------------------------------- the activity of soft holders

# A soft holder has to prove work rather than existence: a VS Code left open and
# forgotten, a dev server listening in silence, an abandoned sclaude session —
# none of these is a reason to deny the laptop sleep. The countdown runs from the
# moment of the last activity, and each has its own sign — but everywhere it is a
# trace of work on disk rather than CPU time spent.
#
# None of this concerns hard holders: a live SSH session or an open tab means a
# person at the machine, and their mere presence is enough.
check_true("soft holders are checked against the previous run's snapshot",
           "SOFT_SNAPSHOT" in ka_body)
check_true("VS Code's activity is measured by its edit journal",
           "VSCODE_HISTORY" in ka_body)
# We look for the dev server's log by the process's working directory: sclaude
# puts it at <worktree>/.sclaude/local/feature/dev.log, and cwd leads there whoever started the
# server. The counter of written bytes stays as a fallback — for a server started
# by hand where there is no such log.
check_true("the dev server's activity is measured by its log", "DEV_LOG_REL" in ka_body)
check_true("the log is found by the process's working directory",
           "/proc/$pid/cwd" in ka_body)
check_true("without a log the counter of written bytes is left",
           "io_wchar_of" in ka_body)
check_true("hard holders require no sign of activity",
           "grew" not in ka_body[ka_body.index("count_ssh()"):
                                 ka_body.index("CODE_HEARTBEAT=")])

# grew() is the shared predicate "the counter has grown since last time". The
# whole countdown rests on it, and its cases are worth checking separately.
def bash_grew(prev_line, key, now, threshold):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "bin", "keepawake")
    parts = []
    for expr in ("/^LOG_DIR=/p", "/^SOFT_SNAPSHOT=/p", "/^SOFT_SNAPSHOT_NEW=/p",
                 "/^read_snapshot/,/^}/p", "/^remember/,/^}/p",
                 "/^grew/,/^}/p"):
        parts.append(subprocess.run(["sed", "-n", expr, script],
                                    capture_output=True, text=True).stdout)
    snap = os.path.join(tempfile.gettempdir(), "keepawake-test-grew")
    with open(snap, "w") as fh:
        fh.write(prev_line)
    body = "\n".join([
        "\n".join(p for p in parts if p.strip()),
        'SOFT_SNAPSHOT=%s' % shlex.quote(snap),
        'SOFT_SNAPSHOT_NEW="$SOFT_SNAPSHOT.new"',
        ': > "$SOFT_SNAPSHOT_NEW"',
        'declare -A prev=(); read_snapshot prev',
        'grew %s %d %d prev && echo yes || echo no' % (shlex.quote(key), now,
                                                       threshold),
    ])
    out = subprocess.run(["bash", "-c", body], capture_output=True, text=True)
    return out.stdout.strip()


check("the counter grew — active", bash_grew("dev:1 1000\n", "dev:1", 2000, 256), "yes")
check("the counter stands still — not active", bash_grew("dev:1 1000\n", "dev:1", 1000, 256), "no")
check("growth below the threshold — not active",
      bash_grew("dev:1 1000\n", "dev:1", 1100, 256), "no")
check("a first appearance — active", bash_grew("", "dev:1", 1000, 256), "yes")


# ------------------------------------- a holder without a person

# Soft holders divide in two, and the division is not a formality. claude,
# sclaude and VS Code prove work: the transcript, the step's state and the edit
# journal grow because somebody — a person or an agent — is doing something. The
# dev server and the code-server service prove only their own existence: the dev
# server's log grows from the requests of a forgotten open tab, and the service is
# alive simply because it was switched on.
#
# For such a holder the sign alone is not enough: it flares up every minute, the
# deadline moves an hour forward faster than it approaches the warning threshold,
# and the laptop does not sleep for days — exactly the case already worked
# through with claude's transcript. So it asks about a person as well.
def bash_fn(names, stubs, call):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "bin", "keepawake")
    parts = []
    for name in names:
        parts.append(subprocess.run(
            ["sed", "-n", "/^%s() {/,/^}$/p" % name, script],
            capture_output=True, text=True).stdout)
    body = "\n".join(parts + [stubs, call])
    return subprocess.run(["bash", "-c", body],
                          capture_output=True, text=True, timeout=60).stdout.strip()


def bash_dev(active, around):
    wt = tempfile.mkdtemp(prefix="keepawake-test-dev-")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    open(os.path.join(wt, ".sclaude/local/feature", "dev.log"), "w").write("GET / 200\n")
    stubs = "\n".join([
        'DEV_PORT=3000',
        'DEV_LOG_REL=".sclaude/local/feature/dev.log"',
        'ss() { echo \'LISTEN 0 511 0.0.0.0:3000 0.0.0.0:* users:(("node",pid=42,fd=20))\'; }',
        'readlink() { printf %%s %s; }' % shlex.quote(wt),
        'read_snapshot() { :; }',
        'grew() { return %d; }' % (0 if active else 1),
        'someone_around() { return %d; }' % (0 if around else 1),
    ])
    return bash_fn(["count_dev"], stubs, "count_dev")


check("the log is growing and a person is around — we hold", bash_dev(True, True), "1")
check("the log is growing but nobody has been at the machine for an hour — we do not hold",
      bash_dev(True, False), "0")
check("the log was not touched — we do not hold even with a person", bash_dev(False, True), "0")


# One server per feature: any of them being worked with holds, whatever port it
# sits on — and a port outside sclaude's ranges is somebody else's (a database,
# say) and holds nothing.
def bash_devs(listeners):
    wt = tempfile.mkdtemp(prefix="keepawake-test-devs-")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    open(os.path.join(wt, ".sclaude/local/feature", "dev.log"), "w").write("GET / 200\n")
    lines = "\n".join(
        "LISTEN 0 511 0.0.0.0:%d 0.0.0.0:* users:((\"node\",pid=%d,fd=20))" % (port, pid)
        for port, pid in listeners)
    stubs = "\n".join([
        'DEV_PORT=3000', 'DEV_PORT_FIRST=3100', 'DEV_PORT_LAST=3199',
        'DEV_LOG_REL=".sclaude/local/feature/dev.log"',
        "ss() { printf '%%s\\n' %s; }" % shlex.quote(lines),
        # Only pid 42 is a feature's server with a log; any other has none.
        'readlink() { case "$2" in /proc/42/*) printf %%s %s ;; *) printf %%s /nonexistent ;; esac; }'
        % shlex.quote(wt),
        'io_wchar_of() { :; }',
        'read_snapshot() { :; }',
        'grew() { return 0; }',
        'someone_around() { return 0; }',
    ])
    return bash_fn(["count_dev"], stubs, "count_dev")


check("a feature's own server in the range holds", bash_devs([(3000, 7), (3142, 42)]), "1")
check("a listener outside the dev ports holds nothing", bash_devs([(5432, 42)]), "0")
# Compared as numbers: as text, "31234" sorts below "3199" and passed.
check("a port that only looks like the range as text holds nothing",
      bash_devs([(31234, 42)]), "0")


def bash_codesrv(around):
    stubs = "\n".join([
        'systemctl() { return 0; }',
        'someone_around() { return %d; }' % (0 if around else 1),
    ])
    return bash_fn(["count_code_server"], stubs, "count_code_server")


check("the code-server service with a person present is a holder", bash_codesrv(True), "1")
check("a running service does not hold by itself", bash_codesrv(False), "0")


# "Is there anyone here" means recent input or noticeable load. The first
# answers for a person, the second for a long build without a single keystroke:
# that is work too.
def bash_around(idle, loaded_ok):
    stubs = "\n".join([
        'IDLE_AFTER=3600',
        'idle_seconds() { printf %%s %d; }' % idle,
        'loaded() { return %d; }' % (0 if loaded_ok else 1),
    ])
    return bash_fn(["someone_around"], stubs,
                   'someone_around && echo yes || echo no')


check("recent input — somebody is there", bash_around(60, False), "yes")
check("an hour of silence and a quiet machine — nobody", bash_around(4000, False), "no")
check("an hour of silence but a build is running — not nobody", bash_around(4000, True), "yes")
# 999999 is the placeholder for "no interactive sessions at all". The daemon does
# not judge by it (there a tab or traffic is holding and there may be no
# terminal), but here it does: no sessions means no input by which a person could
# have made themselves known.
check("no sessions at all — nobody", bash_around(999999, False), "no")

# Busyness is written after the snapshot is swapped, so it is computed from the
# claude count already taken: a repeat count_claude would compare transcript
# sizes with themselves and would always answer "not busy".
check_true("busyness is taken from the claude count rather than from is_busy",
           "(( claude )) || loaded" in ka_body)

# ------------------------------------- the person at the terminal

# A question always goes to the chat, but a sound only when there is no person at
# the terminal. The cost of a mistake here is exactly what the whole thing was
# undertaken for: a needless sound in the middle of work at the laptop.
#
# The bench runs on real ptys rather than a faked os.stat: we check precisely the
# kernel property the sign rests on — which stamp is moved by what. With a mock
# the test would prove only that the mock is set up as intended.

import pty

from keepawake import telegramd as tg_quiet


class Pty(object):
    # A pty with a live bash at the far end: the process gets a real controlling
    # terminal, and we get both of its ends.
    def __enter__(self):
        self.master, slave = pty.openpty()
        self.name = os.ttyname(slave)
        self.proc = subprocess.Popen(
            ["bash", "-c", "read -r x; sleep 30"],
            stdin=slave, stdout=slave, stderr=slave,
            preexec_fn=os.setsid, close_fds=True)
        os.close(slave)
        time.sleep(0.3)
        return self

    def age(self, seconds):
        # Age both stamps. A fresh pty is created with the current time in both,
        # and without ageing "600 seconds ago" is indistinguishable from "just
        # created" — the first version of this test was fooled exactly that
        # way.
        old = time.time() - seconds
        os.utime(self.name, (old, old))

    def prints(self, text):
        # We print from the process's side, as ask() itself does: we write to
        # the slave end, having opened it afresh. Writing to the master is input
        # "from outside", that is a different event entirely, and it affects the
        # terminal's stamps differently.
        with open(self.name, "w") as fh:
            fh.write(text)
            fh.flush()
        time.sleep(0.3)

    def types(self, text):
        os.write(self.master, text.encode())
        time.sleep(0.4)

    def __exit__(self, *exc):
        self.proc.kill()
        self.proc.wait()
        os.close(self.master)
        return False


with Pty() as term:
    check("the process's terminal is found", tg_quiet.tty_of_pid(term.proc.pid),
          term.name)

    term.age(600)
    check("a silent terminal — nobody at it",
          tg_quiet.at_terminal({"pid": term.proc.pid}), False)

    # The main check of the whole undertaking. ask() prints the prompt into the
    # terminal right after laying the question out — and if the sign looks at
    # mtime, that output declares the person present. Every question in a row
    # then goes out silent, those asked from the bot included, that is the sign
    # works inside out. The test fails on exactly that substitution.
    term.prints("Do you confirm that everything works as it should? [y/n] ")
    check("printing a prompt does not count as presence",
          tg_quiet.at_terminal({"pid": term.proc.pid}), False)

    term.types("y\n")
    check("what was typed counts as presence",
          tg_quiet.at_terminal({"pid": term.proc.pid}), True)

    term.age(600)
    check("what was typed long ago does not count",
          tg_quiet.at_terminal({"pid": term.proc.pid}), False)

# A launch from the bot goes through setsid and has no terminal at all. That is
# the main case that must not be muted: it can only be answered from a phone.
check("a process with no terminal", tg_quiet.tty_of_pid(os.getpid()) is None
      or tg_quiet.tty_of_pid(os.getpid()).startswith("/dev/pts"), True)
check("a dead pid", tg_quiet.tty_of_pid(999999), None)
check("there is no pid in the question", tg_quiet.at_terminal({}), False)
check("the pid is not a number", tg_quiet.at_terminal({"pid": "abc"}), False)


# --- and the same thing whole, through check_asks --------------------------

def asks_quiet(pid):
    # We put a question into a temporary repository's channel and look at what
    # sound the message went out with. Returns the sent message's quiet, or
    # None.
    root = tempfile.mkdtemp()
    repo = os.path.join(root, "repo")
    os.makedirs(os.path.join(repo, ".git", "sclaude"))
    with open(os.path.join(repo, ".git", "sclaude", "ask.json"), "w") as fh:
        json.dump({"prompt": "Ship it?", "form": "yn", "context": "",
                   "id": "deadbeef", "pid": pid}, fh)
    bot = FakeBot()
    path = os.path.join(root, "state.json")
    old_env = os.environ.get("KEEPAWAKE_STATE")
    os.environ["KEEPAWAKE_STATE"] = path
    old_repos = tg_quiet.known_repos
    tg_quiet.known_repos = lambda: [repo]
    try:
        tg_quiet.check_asks(bot)
    finally:
        tg_quiet.known_repos = old_repos
        if old_env is None:
            os.environ.pop("KEEPAWAKE_STATE", None)
        else:
            os.environ["KEEPAWAKE_STATE"] = old_env
    return bot.sent[0][2] if bot.sent else None


with Pty() as term:
    term.types("y\n")
    check("a question from a live terminal — silently",
          asks_quiet(term.proc.pid), True)
    term.age(600)
    check("a question from an abandoned terminal — with sound",
          asks_quiet(term.proc.pid), False)

# A question with no terminal — a launch from the bot — always with sound.
check("a question with no terminal — with sound", asks_quiet(os.getpid()), False)

# ------------------------------------- idling by a tty's two stamps

# A tty has two stamps, and one is not enough. mtime is moved by a program's
# output: a forgotten tab with `tail -f` prints into the void and looks like work
# — because of which the question about a forgotten session was never asked at
# all. atime is moved by reading from the terminal, that is by what was typed,
# but an automaton feeding input into a pty moves it too. Idling is counted by
# the smaller stamp — "nobody is there only when both are silent".
#
# The terminals are real: a faked os.stat would prove only that the fake is set
# up as intended, whereas what we are checking is the kernel's behaviour.

def bash_idle(ttys, heartbeat="/nonexistent"):
    """ttys: names like ['pts/3'] — what ps will show. Prints the idle time."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                          "bin", "keepawake")
    body = "\n".join([
        subprocess.run(["sed", "-n", "/^idle_seconds()/,/^}/p", script],
                       capture_output=True, text=True).stdout,
        'CODE_HEARTBEAT=%s' % shlex.quote(heartbeat),
        'ps() { printf "%%s\\n" %s; }' % " ".join(shlex.quote(t) for t in ttys),
        "idle_seconds",
    ])
    out = subprocess.run(["bash", "-c", body], capture_output=True, text=True)
    return int(out.stdout.strip() or -1)


def pty_named(age_m, age_a):
    """A live pty with the given stamp ages. Returns (name, process, master)."""
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    proc = subprocess.Popen(["bash", "-c", "read -r x; sleep 30"],
                            stdin=slave, stdout=slave, stderr=slave,
                            preexec_fn=os.setsid, close_fds=True)
    os.close(slave)
    time.sleep(0.3)
    now = time.time()
    os.utime(name, (now - age_a, now - age_m))
    return name, proc, master


# The main check. The stamps have diverged: printing happened a minute ago,
# typing a day ago — that is precisely a forgotten tab with a log. Idling has to
# be counted by the older event. The test fails on a return to plain mtime.
name, proc, master = pty_named(age_m=60, age_a=86400)
try:
    idle = bash_idle([name.replace("/dev/", "")])
    check_true("output to a terminal does not count as presence", idle > 3600)
    check_true("idling is counted by the older stamp", abs(idle - 86400) < 120)
finally:
    proc.kill(); proc.wait(); os.close(master)

# The reverse skew: an automaton fed input (atime is fresh) while there has been
# no output for a long time. Not a person either — one of the stamps is
# silent.
name, proc, master = pty_named(age_m=86400, age_a=60)
try:
    check_true("machine input does not count as presence",
               bash_idle([name.replace("/dev/", "")]) > 3600)
finally:
    proc.kill(); proc.wait(); os.close(master)

# A live person: both stamps are fresh, because the shell echoes what is
# typed.
name, proc, master = pty_named(age_m=5, age_a=5)
try:
    check_true("a live session counts as presence",
               bash_idle([name.replace("/dev/", "")]) < 60)
finally:
    proc.kill(); proc.wait(); os.close(master)

# One live terminal is enough: a forgotten tab next to it spoils nothing.
live, p1, m1 = pty_named(age_m=5, age_a=5)
dead, p2, m2 = pty_named(age_m=60, age_a=86400)
try:
    check_true("one live terminal outweighs a forgotten one",
               bash_idle([live.replace("/dev/", ""),
                          dead.replace("/dev/", "")]) < 60)
finally:
    for p, m in ((p1, m1), (p2, m2)):
        p.kill(); p.wait(); os.close(m)

# The "nothing to measure" placeholder is intact: no sessions is not "a very
# long idle".
check("no terminals — the placeholder", bash_idle([]), 999999)

# A code-server tab holds the machine without a TTY. Its heartbeat is an
# ordinary file that code-server touches once a minute, and mtime there means
# exactly what it says: the two-stamp rule does not apply to it.
hb = os.path.join(tempfile.mkdtemp(), "heartbeat")
open(hb, "w").close()
check_true("code-server's heartbeat counts as presence",
           bash_idle([], heartbeat=hb) < 60)

# ------------------------------------------------------- the choice buttons
#
# A question with the form pick:N arrives in the chat as buttons. While there
# were no option labels, the buttons carried numbers alone — "1 2 3" — and had to
# be pressed while checking against the list in the text above them. Among the
# options there is sometimes "drop the feature", so the cost of a blind press
# here is not zero.

from keepawake import telegramd as _tg

# The labels were passed — a button per option, with its name and its own number
# in the answer.
_kb = _tg.ask_keyboard("myapp", {
    "form": "pick:3",
    "options": ["Continue", "Sync with main", "Drop the feature"],
})
check("the choice buttons are labelled", [b[0]["text"] for b in _kb],
      ["Continue", "Sync with main", "Drop the feature"])
check("the choice buttons answer with a number",
      [b[0]["callback_data"] for b in _kb],
      ["answer:myapp:1", "answer:myapp:2", "answer:myapp:3"])

# No labels means the previous behaviour down to the last character: whoever
# does not know about options noticed nothing.
check("without labels the digits remain",
      [b["text"] for row in _tg.ask_keyboard("myapp", {"form": "pick:3"}) for b in row],
      ["1", "2", "3"])

# There are as many labels as options — otherwise they cannot be trusted: a list
# that had drifted would label the buttons with the wrong names, and that is
# worse than honest digits.
check("a mismatch in the labels gives digits",
      [b["text"] for row in _tg.ask_keyboard(
          "myapp", {"form": "pick:3", "options": ["Continue"]}) for b in row],
      ["1", "2", "3"])

# A long list does become a wall — but at the twenty-fifth option rather than
# the eighth: see the ceiling checks below.

# A label that is too long is cut from the tail: an option's start is what
# matters.
_long = _tg.ask_keyboard("myapp", {"form": "pick:1", "options": ["A" * 90]})
check_true("a long label is trimmed", len(_long[0][0]["text"]) <= 60)
check_true("a long label is cut from the tail",
           _long[0][0]["text"].startswith("AAA") and _long[0][0]["text"].endswith("…"))

# An empty label does not leave an empty button: better a number than something
# with nothing for the eye to land on.
check("an empty label is replaced by a number",
      _tg.ask_keyboard("myapp", {"form": "pick:1", "options": [""]})[0][0]["text"],
      "1")

# Labelled buttons have a ceiling of their own. Nine options is exactly how many
# the list of actions on a feature has, and with the old shared threshold of
# eight it got no buttons at all — which is what the whole thing was for.
check("nine labelled buttons fit",
      len(_tg.ask_keyboard("myapp", {"form": "pick:9",
                                      "options": ["a%d" % i for i in range(9)]})), 9)
check("twenty-four — still yes",
      len(_tg.ask_keyboard("myapp", {"form": "pick:24",
                                      "options": ["a%d" % i for i in range(24)]})), 24)
check("twenty-five — as text now",
      _tg.ask_keyboard("myapp", {"form": "pick:25",
                                  "options": ["a%d" % i for i in range(25)]}), [])
# The unlabelled ones kept the old one: a digit is checked against the list by
# eye, and by the ninth that costs more than typing the number by hand.
check("nine unlabelled ones do not fit",
      _tg.ask_keyboard("myapp", {"form": "pick:9"}), [])

# The numbered list above labelled buttons is the same list a second time. We
# remove precisely that, leaving the lines that explain the question.
_ctx = "71-email · issue #71\n  1)  Continue  step 2/4\n  2)  Drop  clears all"
_named = _tg.ask_text("myapp", {"form": "pick:2", "prompt": "Which one?",
                                 "context": _ctx, "options": ["Continue", "Drop"]})
check_true("the list above labelled buttons is removed", "1)  Continue" not in _named)
check_true("the line with the issue next to the buttons stayed", "issue #71" in _named)

# Without labels the list has to stay: "3" says nothing until it is written next
# to it what the third option is.
_bare = _tg.ask_text("myapp", {"form": "pick:2", "prompt": "Which one?",
                                "context": _ctx})
check_true("the list stayed with numeric buttons", "1)  Continue" in _bare)

# The feature list's buttons: the wide one drives the step, the narrow one leads
# to the actions on the same feature. That is the Telegram form of the terminal's
# checkbox, unfolded across the width.
_feat_rows = [r for r in _tg.features_keyboard("myapp")
              if len(r) == 2 and r[1]["callback_data"].startswith("acts:")]
if _feat_rows:
    _row = _feat_rows[0]
    _slug = _row[1]["callback_data"].split(":", 2)[2]
    check("the wide feature button drives the step",
          _row[0]["callback_data"], "go:myapp:%s" % _slug)
    check("the narrow feature button leads to the actions",
          _row[1]["callback_data"], "acts:myapp:%s" % _slug)
    check_true("the narrow button has no caption", len(_row[1]["text"]) <= 4)
    check_true("the feature's name is trimmed to half a row",
               len(_row[0]["text"]) <= 40)

# A question about a particular feature is shown with its card. There is nothing
# in the orchestrator to assemble it with — whether the session is alive is known
# to the bot — so the orchestrator only names the feature in the feature field,
# and ask_text builds the card.
_ask_card = _tg.ask_text("myapp", {"form": "pick:2", "prompt": "Which one?",
                                    "feature": "no-such-feature",
                                    "options": ["a", "b"]})
check_true("a non-existent feature does not bring the question down",
           "no-such-feature" in _ask_card)
check_true("a question with a card has its own prompt",
           "Which one?" in _ask_card)

# Without the feature field, the previous look down to the last character:
# "myapp is asking".
_plain = _tg.ask_text("myapp", {"form": "yn", "prompt": "Ship it? [y/n] "})
check_true("an ordinary question is untouched", "Ship it?" in _plain)
check_true("an ordinary question keeps its header",
           _tg.t("ask.title", repo="myapp", prompt="Ship it? [y/n] ") in _plain)

# The field gets through from the orchestrator: io.sh puts it there from
# ASK_FEATURE.
import subprocess as _sp, tempfile as _tf, json as _js, os as _os
_d = _tf.mkdtemp()
_sp.run(["bash", "-c",
         'source %s/sclaude/lib/io.sh; ASK_DIR=%s ASK_FEATURE=my-feat '
         'ask_publish "Which one? [1-2] " "pick:2" "A" "B" >/dev/null'
         % (_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), _d)],
        capture_output=True)
with open(_os.path.join(_d, "ask.json")) as _fh:
    _q = _js.load(_fh)
check("ASK_FEATURE reaches the channel", _q.get("feature"), "my-feat")
# Without the variable there is no field at all: an empty one would mean "a
# feature with no name".
_sp.run(["bash", "-c",
         'source %s/sclaude/lib/io.sh; ASK_DIR=%s '
         'ask_publish "Done? [y/n] " "yn" >/dev/null'
         % (_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), _d)],
        capture_output=True)
with open(_os.path.join(_d, "ask.json")) as _fh:
    _q2 = _js.load(_fh)
check("without ASK_FEATURE there is no field", "feature" in _q2, False)

# "Back" among the answers is recognised by the option's label rather than its
# number: its number differs every time — the action list shows only what
# applies.
check_true("Go back is an exit", _tg.is_back_option("Go back"))
check_true("none, go back is too", _tg.is_back_option("none, go back"))
check_true("the Russian 'Назад' with an arrow", _tg.is_back_option("‹ Назад"))
check("a real action does not count as an exit",
      _tg.is_back_option("Drop the feature"), False)
check("the 'Continue' item even less so", _tg.is_back_option("Continue"), False)
check("an empty label is not an exit", _tg.is_back_option(""), False)

# A button's caption is trimmed by bytes rather than characters: Telegram's
# ceiling is in bytes, and 59 Cyrillic characters are 110 bytes, twice as many.
# The non-ASCII data below is the point of the check.
check_true("non-ASCII text fits within the ceiling",
           len(_tg.clip_bytes("Продолжить работу над фичей и посмотреть, "
                              "что там происходит", 60).encode("utf-8")) <= 60)
check("we do not touch a short one", _tg.clip_bytes("short", 60), "short")
check_true("a trimmed one ends with an ellipsis",
           _tg.clip_bytes("A" * 90, 60).endswith("…"))
# The cut must go by characters: slicing bytes would tear a multi-byte character
# in half.
_tg.clip_bytes("я" * 90, 60).encode("utf-8")   # must not raise

# The features that ran out of buttons are named in the text. While the sclaude
# status table lay under the header they were at least visible in it; without it
# the ninth feature disappeared from the chat entirely — neither a button nor a
# line.
_saved_feats = _tg.features_of_name
try:
    _tg.features_of_name = lambda n: (
        [("feat-%d" % i, "2/4 development", "/wt/%d" % i) for i in range(1, 10)], "")
    _nine = _tg.repo_text("myapp")
    check_true("the counter counts all nine", "9" in _nine)
    check_true("the ninth feature is named in the text", "feat-9" in _nine)
    check("there are still eight buttons",
          len([r for r in _tg.features_keyboard("myapp")
               if len(r) == 2 and r[1]["callback_data"].startswith("acts:")]), 8)
    # Eight features fit whole — there must then be no extra line.
    _tg.features_of_name = lambda n: (
        [("feat-%d" % i, "2/4 development", "/wt/%d" % i) for i in range(1, 9)], "")
    # Both halves of the bilingual string are checked: the bot picks by the
    # client's language, and the addendum must be absent in either.
    check_true("with eight features there is no addendum",
               "Not shown" not in _tg.repo_text("myapp")
               and i18n.STRINGS["repo.rest"][0].split(":")[0].strip() not in _tg.repo_text("myapp"))
finally:
    _tg.features_of_name = _saved_feats

# The "answer with a number" hint is needed exactly when no buttons were
# available.
check_true("with buttons there is no hint about a number",
           _tg.t("ask.pick") not in _tg.ask_text(
               "myapp", {"form": "pick:2", "prompt": "Which one?",
                          "options": ["A", "B"]}))
check_true("without buttons there is a hint about a number",
           _tg.t("ask.pick") in _tg.ask_text(
               "myapp", {"form": "pick:12", "prompt": "Which one?"}))

# --- which sclaude features the detector sees (sclaude_states) -------------
#
# A step holds the machine awake only if its feature's state.json is found.
# When the state moved two levels deeper the old `find -maxdepth 3` found
# none, and every check here still passed: none of them looked.
_ka = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "keepawake")
_fn = subprocess.run(["sed", "-n", "/^sclaude_states/,/^}/p", _ka],
                     capture_output=True, text=True).stdout
_home = tempfile.mkdtemp(prefix="keepawake-test-home-")
try:
    _want = os.path.join(_home, "myapp-12-x", ".sclaude", "local", "feature", "state.json")
    os.makedirs(os.path.dirname(_want))
    open(_want, "w").close()
    # Not a feature: the main repository has a .sclaude/ but no feature state.
    os.makedirs(os.path.join(_home, "myapp", ".sclaude", "local"))
    _out = subprocess.run(["bash", "-c", _fn + "\nsclaude_states"],
                          env=dict(os.environ, HOME=_home),
                          capture_output=True, text=True).stdout.split()
    check("sclaude_states finds a feature worktree's state", _out, [_want])
    # And one an older sclaude still runs, in the old place.
    _old = os.path.join(_home, "myapp-13-y", ".feature", "state.json")
    os.makedirs(os.path.dirname(_old))
    open(_old, "w").close()
    _out = subprocess.run(["bash", "-c", _fn + "\nsclaude_states"],
                          env=dict(os.environ, HOME=_home),
                          capture_output=True, text=True).stdout.split()
    check("sclaude_states finds the old place too", sorted(_out), sorted([_want, _old]))
    # The bot reads the old place too, for the same trees.
    check("telegramd reads the old place", telegramd.state_path(os.path.dirname(os.path.dirname(_old))), _old)
    check("telegramd prefers the new place",
          telegramd.state_path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_want))))),
          _want)
finally:
    shutil.rmtree(_home, ignore_errors=True)

# ------------------------------------------------------------- the outcome

if failures:
    print("FAILED: %d" % len(failures))
    for name, want, got in failures:
        print("  %s\n    expected: %r\n    got:      %r" % (name, want, got))
    sys.exit(1)

print("keepawake: all checks passed")
