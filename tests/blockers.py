#!/usr/bin/env python3
#
# A test bench for the "blocked by" checks: sclaude/lib/github/blockers.py, the issue
# picker's rows (fetch_issues in picker.sh) and the question before a feature
# starts (issue_blockers_gate in github.sh).
#
# gh is a stub on PATH that answers from fixed JSON, so nothing here touches
# the network. What is guarded:
#
#   * only OPEN blockers count — a closed one is history, and stopping a start
#     over it would teach people to answer "y" without reading;
#   * gh failing makes every check silent, never a refusal;
#   * the picker row gains a fifth column and keeps its first four in place
#     (pick_start cuts the number and title by position), and a sixth, the
#     issue's board status (board_status.py), drawn rightmost — empty, never
#     a lost list, when the board cannot be read;
#   * the gate asks only when something is open, and "n" stops the start.
#
# Run it with: python3 tests/blockers.py
import json
import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from blockers import open_blockers  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def blocked_by(*pairs):
    return {"nodes": [{"number": n, "state": s, "title": "t%d" % n}
                      for n, s in pairs],
            "totalCount": len(pairs)}


ISSUES = [
    {"number": 61, "title": "Alpha", "labels": [{"name": "Dev"}],
     "assignees": [], "blockedBy": blocked_by((60, "CLOSED"), (37, "OPEN"))},
    {"number": 60, "title": "Beta", "labels": [], "assignees": [],
     "blockedBy": blocked_by((140, "CLOSED"))},
    {"number": 59, "title": "Gamma", "labels": [], "assignees": [],
     "blockedBy": {"nodes": [], "totalCount": 0}},
]


BOARD = {"data": {"repository": {
    "i61": {"state": "OPEN", "projectItems": {"nodes": [
        {"fieldValueByName": None},
        {"fieldValueByName": {"name": "In  progress"}}]}},
    "i60": {"state": "CLOSED", "projectItems": {"nodes": []}},
    "i59": None}}}


def stub_dir(fail=False, board=True, issues=ISSUES):
    """A directory with a gh that prints issues (list), one of them (view) or
    BOARD (graphql, unless board is false)."""
    d = tempfile.mkdtemp()
    data = os.path.join(d, "issues.json")
    with open(data, "w") as fh:
        json.dump(issues, fh)
    gh = os.path.join(d, "gh")
    with open(gh, "w") as fh:
        fh.write("""#!/usr/bin/env python3
import json, sys
if %r:
    sys.exit(1)
args = sys.argv[1:]
issues = json.load(open(%r))
if args[:2] == ["api", "user"]:
    print("me")
elif args[:2] == ["issue", "list"]:
    print(json.dumps(issues))
elif args[:2] == ["issue", "view"]:
    print(json.dumps(next(i for i in issues if str(i["number"]) == args[2])))
elif args[:2] == ["api", "graphql"] and %r:
    print(json.dumps(%r))
else:
    sys.exit(1)
""" % (fail, data, board, BOARD))
    os.chmod(gh, 0o755)
    return d


def run(cmd, d, stdin=""):
    env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"])
    done = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          env=env, timeout=60)
    return done.stdout, done.returncode


# --- the parsing -------------------------------------------------------------

check("open only", open_blockers(ISSUES[0]), [(37, "t37")])
check("closed only", open_blockers(ISSUES[1]), [])
check("no links", open_blockers({"number": 1}), [])
check("a plain list from gh", open_blockers(
    {"blockedBy": [{"number": 5, "state": "OPEN", "title": "a  b"}]}),
    [(5, "a b")])

# --- the command line --------------------------------------------------------

d = stub_dir()
script = os.path.join(LIB, "github", "blockers.py")
check("issue mode", run([sys.executable, script, "issue", "o/r", "61"], d),
      ("37\tt37\n", 0))
check("issue mode, nothing open",
      run([sys.executable, script, "issue", "o/r", "60"], d), ("", 0))
check("list mode, only the asked and blocked ones",
      run([sys.executable, script, "list", "o/r", "61", "60", "59"], d),
      ("61\t#37\n", 0))
check("list mode, not asked", run([sys.executable, script, "list", "o/r",
                                   "60"], d), ("", 0))

broken = stub_dir(fail=True)
check("gh failing is silent",
      run([sys.executable, script, "issue", "o/r", "61"], broken), ("", 0))
check("gh failing is silent in a list",
      run([sys.executable, script, "list", "o/r", "61"], broken), ("", 0))

# --- the picker's rows -------------------------------------------------------

rows, _ = run(["bash", "-c",
               'BOLD=""; DIM=""; GREEN=""; OFF=""; REPO=.\n'
               'source "%s/core/picker.sh"\n'
               'gh_repo() { echo o/r; }\n'
               'fetch_issues' % LIB], d)
rows = [r.split("\t") for r in rows.splitlines()]
check("picker row width", sorted({len(r) for r in rows}), [6])
check("picker keeps number and title in place",
      [(r[1], r[2]) for r in rows],
      [("61", "Alpha"), ("60", "Beta"), ("59", "Gamma")])
check("picker marks the blocked one", [r[4] for r in rows], ["#37", "", ""])
check("picker shows the board status", [r[5] for r in rows],
      ["In progress", "Closed", ""])

no_board = stub_dir(board=False)
rows, _ = run(["bash", "-c",
               'BOLD=""; DIM=""; GREEN=""; OFF=""; REPO=.\n'
               'source "%s/core/picker.sh"\n'
               'gh_repo() { echo o/r; }\n'
               'fetch_issues' % LIB], no_board)
rows = [r.split("\t") for r in rows.splitlines()]
check("no board: the list stays", [r[1] for r in rows], ["61", "60", "59"])
check("no board: the column is empty", [r[5] for r in rows], ["", "", ""])

# No open issue is an answer, told apart from gh failing: the picker says the
# list could not be fetched only for the second.
FETCH = ('BOLD=""; DIM=""; GREEN=""; OFF=""; REPO=.\n'
         'source "%s/core/picker.sh"\n'
         'gh_repo() { echo o/r; }\n'
         'fetch_issues' % LIB)
check("no open issue: nothing, and success", run(["bash", "-c", FETCH], stub_dir(issues=[])),
      ("", 0))
check("gh failing: a failure", run(["bash", "-c", FETCH], broken)[1], 1)

# The drawing: the status stands last, after the labels, in yellow.
# draw_picker writes to /dev/tty, so it runs under a pty of its own.
def draw(script):
    pid, fd = pty.fork()
    if pid == 0:
        os.execv("/bin/bash", ["bash", "-c", script])
    buf = b""
    while True:
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        buf += data
    os.waitpid(pid, 0)
    return buf.decode("utf-8", "replace")


drawn = draw('BOLD=""; DIM="<d>"; GREEN=""; OFF="</>"; YELLOW="<y>"\n'
             'source "%s/core/picker.sh"\n'
             'ISSUE_ROWS=($\'1\\t61\\tAlpha\\tDev\\t\\tIn progress\')\n'
             'PICKER_COLS=80\n'
             'draw_picker 0 1 2 > /dev/null\n' % LIB)
line = next((l for l in drawn.splitlines() if "#61" in l), "")
check("status drawn rightmost in yellow",
      line.rstrip().endswith("<d>Dev</>  <y>In progress</>"), True)

# With PICK_START_CONFIG the settings are the last row, under a heading of
# their own; without it they are not drawn at all.
def draw_config(flag, cur):
    return draw('BOLD="<b>"; DIM=""; GREEN=""; OFF="</>"; YELLOW=""\n'
                'source "%s/core/picker.sh"\n'
                'ISSUE_ROWS=($\'1\\t61\\tAlpha\\tDev\\t\\t\')\n'
                'PICKER_COLS=80; PICK_START_CONFIG=%s\n'
                'draw_picker 0 %d 3 > /dev/null\n' % (LIB, flag, cur))


drawn = draw_config("1", 2).splitlines()
config = [i for i, l in enumerate(drawn) if "config.json, explained" in l]
check("the settings row is drawn", len(config), 1)
check("under its heading", bool(config) and "── project" in drawn[config[0] - 1], True)
check("the cursor stands on it", bool(config) and "<b>config</>" in drawn[config[0]], True)
check("no settings row unasked", "config.json" in draw_config("", 1), False)

# With no issue list to show, the picker still offers the name and the
# settings when asked for them; unasked, it goes straight to the name.
# The child may end without drawing — the regression this guards — so the
# reads stop at its end (EIO on Linux) and at a deadline, never hang.
def pick(flag, keys):
    pid, fd = pty.fork()
    if pid == 0:
        os.execv("/bin/bash", ["bash", "-c",
                 'BOLD=""; DIM=""; GREEN=""; OFF=""; YELLOW=""\n'
                 'source "%s/core/picker.sh"\n'
                 'person_at_terminal() { true; }\n'
                 'r="$(PICK_START_CONFIG=%s pick_start "")"; echo "RESULT=$r"\n' % (LIB, flag)])
    deadline = time.time() + 10
    out = [b""]           # everything read, and where the last mark was found

    def read_until(mark):
        """Reads until mark appears in what is new since the last one; False
        when the output ended, or the deadline passed, first."""
        start = len(out[0])
        while mark not in out[0][start:] and time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                return False
            if not data:
                return False
            out[0] += data
        return mark in out[0][start:]

    for key in keys:
        # Each key goes once the picture asking for it is on the screen.
        if not read_until(b"q cancel"):
            break
        os.write(fd, key)
    # To the end of the output: the mark never comes.
    read_until(b"\0")
    if time.time() >= deadline:
        os.kill(pid, 9)
    os.waitpid(pid, 0)
    os.close(fd)
    buf = out[0]
    m = re.search(r"RESULT=(\S*)", buf.decode("utf-8", "replace"))
    return m.group(1) if m else None


check("no issues: the settings are still reachable", pick("1", [b"\x1b[B", b"\r"]), "config")
check("no issues: the name is the first row", pick("1", [b"\r"]), "manual")
check("no issues, no settings asked: the name at once", pick("", []), "manual")

# A long row in a narrow terminal stays within it: a wrapped row would leave
# screen rows behind at every redraw. The width is counted here by hand, apart
# from the code under test: 🏗 is two cells on screen though Unicode calls it
# neutral. The blockers outlast the status and the labels; a short title
# leaves its unused room to them.
def screen_width(text):
    return sum(2 if c == "\U0001F3D7" else 1 for c in text)


def draw_row(row, cols):
    drawn = draw('BOLD=""; DIM=""; GREEN=""; OFF=""; YELLOW=""\n'
                 'source "%s/core/picker.sh"\n'
                 "ISSUE_ROWS=($'%s')\n"
                 'PICKER_COLS=%d\n'
                 'draw_picker 0 1 2 > /dev/null\n' % (LIB, row, cols))
    return next((l for l in drawn.splitlines() if "#62" in l), "").rstrip()


STATUS = "\U0001F3D7" * 12 + " Waiting for review"
line = draw_row("1\\t62\\t" + "Long title " * 6 + "\\tbug,needs-design,frontend,"
                "backend,priority:high\\t#37 #40\\t" + STATUS, 60)
check("a long row fits the terminal", screen_width(line) <= 60, True)
check("a long row keeps its blockers", "blocked by #37 #40" in line, True)
check("a long row keeps its status", "\U0001F3D7" in line, True)

# Labels clipped after the blockers leave room for the " · " between them,
# rather than taking it from the title.
line = draw_row("1\\t62\\tFix login\\tbug,needs-design,frontend,backend"
                "\\t#37 #40\\tDraft", 66)
check("clipped labels after the blockers fit",
      (screen_width(line) <= 66, "Fix login  blocked by #37 #40 · bug" in line),
      (True, True))

# The blockers lose whole numbers, never part of one.
line = draw_row("1\\t62\\t" + "Long title " * 6 + "\\t\\t#37 #40 #41\\t", 52)
check("blockers clipped by whole numbers", line.endswith("blocked by #37 …"), True)

# The narrowest picker, a long title: the title gives way to the bare word
# rather than hide that the issue is blocked, and the labels and the status,
# which matter less, go.
line = draw_row("1\\t62\\t" + "Long title " * 3 + "\\tbug\\t#37 #40\\tIn progress", 40)
check("blocked shown at the narrowest",
      (line.endswith("  blocked"), "In" in line, screen_width(line) <= 40),
      (True, False, True))

line = draw_row("1\\t62\\tFix login\\tbug\\t#37 #40\\tWaiting for review", 70)
check("a short title leaves its room",
      line.endswith("Fix login  blocked by #37 #40 · bug  Waiting for review"),
      True)

# --- the question before a start ---------------------------------------------

# ui.sh gives is_yes; warn and ask are replaced after it with plain stdout and
# stdin, since the real ones talk to /dev/tty and the question channel.
GATE = ('BOLD=""; DIM=""; GREEN=""; OFF=""; LIB="%s"\n'
        'source "%s/core/ui.sh" 2>/dev/null\n'
        'warn() { echo "W:$*"; }\n'
        'ask() { local __r; read -r __r; printf -v "$2" %%s "$__r"; }\n'
        'for _m in github/github github/issue_sync github/board github/outcome; do source "%s/$_m.sh"; done\n'
        'gh_repo() { echo o/r; }\n'
        'issue_blockers_gate NUMBER && echo START || echo STOP\n') % (LIB, LIB, LIB)

out, _ = run(["bash", "-c", GATE.replace("NUMBER", "61")], d, "n\n")
check("gate names the blocker", "W:  #37  t37" in out, True)
check("gate stops on no", out.strip().splitlines()[-1], "STOP")
out, _ = run(["bash", "-c", GATE.replace("NUMBER", "61")], d, "y\n")
check("gate starts on yes", out.strip().splitlines()[-1], "START")
out, _ = run(["bash", "-c", GATE.replace("NUMBER", "60")], d, "")
check("gate is silent with nothing open", out.strip(), "START")
out, _ = run(["bash", "-c", GATE.replace("NUMBER", "61")], broken, "")
check("gate is silent when gh fails", out.strip(), "START")

for name, want, got in failures:
    print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
