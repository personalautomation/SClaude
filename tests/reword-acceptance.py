#!/usr/bin/env python3
#
# reword_acceptance in run.sh: as the review closes, a criterion the plan words
# otherwise than the issue is shown and offered to the issue. A yes writes it
# (acceptance.py --reword), a no is remembered for that same difference, and a
# new difference asks again.
#
# acceptance.py is stood in for by a script that answers from files, so that
# no issue is read or written; the question is answered from a file too.
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "sclaude", "lib")
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def function(source, name):
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
    if not m:
        failures.append(("function-present-" + name, True, False))
        return ""
    return m.group(0)


with open(os.path.join(LIB, "run.sh")) as fh:
    BODY = function(fh.read(), "reword_acceptance")
with open(os.path.join(LIB, "ui.sh")) as fh:
    UI = fh.read()
IS_YES = function(UI, "is_yes") + function(UI, "is_no")

# Answers --reworded with the difference in `differs`, and records --reword.
FAKE = r'''#!/usr/bin/env python3
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
mode = sys.argv[1]
if mode == "--reworded":
    with open(os.path.join(here, "differs")) as fh:
        sys.stdout.write(fh.read())
elif mode == "--reword":
    with open(os.path.join(here, "written"), "a") as fh:
        fh.write(sys.argv[2] + "\n")
    sys.stdout.write("reworded\n")
'''

tmp = tempfile.mkdtemp(prefix="sclaude-reword-")
try:
    lib = os.path.join(tmp, "lib")
    os.makedirs(lib)
    with open(os.path.join(lib, "acceptance.py"), "w") as fh:
        fh.write(FAKE)
    wt = os.path.join(tmp, "wt")
    feature = os.path.join(wt, ".sclaude", "local", "feature")
    os.makedirs(feature)
    with open(os.path.join(feature, "state.json"), "w") as fh:
        fh.write('{"issue": 7}\n')
    with open(os.path.join(feature, "plan.md"), "w") as fh:
        fh.write("## Acceptance criteria\n\n- AC1. From three letters.\n")

    def run(differs, answer):
        with open(os.path.join(lib, "differs"), "w") as fh:
            fh.write(differs)
        script = ('source "%s/state.sh"\nLIB="%s"\nBOLD=""; OFF=""\n'
                  'info() { printf "%%s\\n" "$*"; }\nwarn() { printf "%%s\\n" "$*"; }\n'
                  'ask() { echo ASKED; printf -v "$2" "%%s" "%s"; }\n%s\n%s\n'
                  'reword_acceptance "%s"\n') % (os.path.abspath(LIB), lib, answer,
                                                  IS_YES, BODY, wt)
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True).stdout

    def written():
        path = os.path.join(lib, "written")
        if not os.path.exists(path):
            return 0
        with open(path) as fh:
            return len(fh.read().splitlines())

    one = "differs\nAC1\tFrom two letters.\tFrom three letters.\n"
    out = run("unchanged\n", "y")
    check("nothing differs: no question", "ASKED" in out, False)

    out = run(one, "n")
    check("a difference is asked about", "ASKED" in out, True)
    check("both wordings are shown",
          "From two letters." in out and "From three letters." in out, True)
    check("a no writes nothing", written(), 0)

    out = run(one, "y")
    check("the same difference after a no is not asked again", "ASKED" in out, False)

    three = "differs\nAC3\tA.\tB.\n"
    out = run(three, "")
    check("no answer is asked", "ASKED" in out, True)
    check("no answer writes nothing", written(), 0)
    out = run(three, "n")
    check("no answer is not kept as a no: asked again", "ASKED" in out, True)

    out = run("body\nAC4\tOld.\tNew.\n", "y")
    check("criteria in the description: shown, not asked", "ASKED" in out, False)
    check("...and told where to edit them", "edit them there" in out, True)
    check("...and nothing written", written(), 0)

    two = one + "AC2\tOld.\tNew.\n"
    out = run(two, "y")
    check("a new difference asks again", "ASKED" in out, True)
    check("a yes writes the issue", written(), 1)
    check("and says so", "now reads as the plan" in out, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.exit(1)
print("ok")
