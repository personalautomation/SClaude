#!/usr/bin/env python3
#
# A test bench for the "blocked by" checks: sclaude/lib/blockers.py, the issue
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
#     (pick_start cuts the number and title by position);
#   * the gate asks only when something is open, and "n" stops the start.
#
# Run it with: python3 tests/blockers.py
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
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
    {"number": 151, "title": "Identity", "labels": [{"name": "Dev"}],
     "assignees": [], "blockedBy": blocked_by((150, "CLOSED"), (127, "OPEN"))},
    {"number": 150, "title": "Categories", "labels": [], "assignees": [],
     "blockedBy": blocked_by((140, "CLOSED"))},
    {"number": 149, "title": "Free", "labels": [], "assignees": [],
     "blockedBy": {"nodes": [], "totalCount": 0}},
]


def stub_dir(fail=False):
    """A directory with a gh that prints ISSUES (list) or one of them (view)."""
    d = tempfile.mkdtemp()
    data = os.path.join(d, "issues.json")
    with open(data, "w") as fh:
        json.dump(ISSUES, fh)
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
else:
    sys.exit(1)
""" % (fail, data))
    os.chmod(gh, 0o755)
    return d


def run(cmd, d, stdin=""):
    env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"])
    done = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          env=env, timeout=60)
    return done.stdout, done.returncode


# --- the parsing -------------------------------------------------------------

check("open only", open_blockers(ISSUES[0]), [(127, "t127")])
check("closed only", open_blockers(ISSUES[1]), [])
check("no links", open_blockers({"number": 1}), [])
check("a plain list from gh", open_blockers(
    {"blockedBy": [{"number": 5, "state": "OPEN", "title": "a  b"}]}),
    [(5, "a b")])

# --- the command line --------------------------------------------------------

d = stub_dir()
script = os.path.join(LIB, "blockers.py")
check("issue mode", run([sys.executable, script, "issue", "o/r", "151"], d),
      ("127\tt127\n", 0))
check("issue mode, nothing open",
      run([sys.executable, script, "issue", "o/r", "150"], d), ("", 0))
check("list mode, only the asked and blocked ones",
      run([sys.executable, script, "list", "o/r", "151", "150", "149"], d),
      ("151\t#127\n", 0))
check("list mode, not asked", run([sys.executable, script, "list", "o/r",
                                   "150"], d), ("", 0))

broken = stub_dir(fail=True)
check("gh failing is silent",
      run([sys.executable, script, "issue", "o/r", "151"], broken), ("", 0))
check("gh failing is silent in a list",
      run([sys.executable, script, "list", "o/r", "151"], broken), ("", 0))

# --- the picker's rows -------------------------------------------------------

rows, _ = run(["bash", "-c",
               'BOLD=""; DIM=""; GREEN=""; OFF=""; REPO=.\n'
               'source "%s/picker.sh"\n'
               'gh_repo() { echo o/r; }\n'
               'fetch_issues' % LIB], d)
rows = [r.split("\t") for r in rows.splitlines()]
check("picker row width", sorted({len(r) for r in rows}), [5])
check("picker keeps number and title in place",
      [(r[1], r[2]) for r in rows],
      [("151", "Identity"), ("150", "Categories"), ("149", "Free")])
check("picker marks the blocked one", [r[4] for r in rows], ["#127", "", ""])

# --- the question before a start ---------------------------------------------

# ui.sh gives is_yes; warn and ask are replaced after it with plain stdout and
# stdin, since the real ones talk to /dev/tty and the question channel.
GATE = ('BOLD=""; DIM=""; GREEN=""; OFF=""; LIB="%s"\n'
        'source "%s/ui.sh" 2>/dev/null\n'
        'warn() { echo "W:$*"; }\n'
        'ask() { local __r; read -r __r; printf -v "$2" %%s "$__r"; }\n'
        'source "%s/github.sh"\n'
        'gh_repo() { echo o/r; }\n'
        'issue_blockers_gate NUMBER && echo START || echo STOP\n') % (LIB, LIB, LIB)

out, _ = run(["bash", "-c", GATE.replace("NUMBER", "151")], d, "n\n")
check("gate names the blocker", "W:  #127  t127" in out, True)
check("gate stops on no", out.strip().splitlines()[-1], "STOP")
out, _ = run(["bash", "-c", GATE.replace("NUMBER", "151")], d, "y\n")
check("gate starts on yes", out.strip().splitlines()[-1], "START")
out, _ = run(["bash", "-c", GATE.replace("NUMBER", "150")], d, "")
check("gate is silent with nothing open", out.strip(), "START")
out, _ = run(["bash", "-c", GATE.replace("NUMBER", "151")], broken, "")
check("gate is silent when gh fails", out.strip(), "START")

for name, want, got in failures:
    print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
