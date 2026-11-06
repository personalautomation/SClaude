#!/usr/bin/env python3
#
# reword_acceptance in acceptance.sh: as the review closes, a criterion the plan words
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


with open(os.path.join(LIB, "cycle", "acceptance.sh")) as fh:
    SOURCE = fh.read()
BODY = function(SOURCE, "reword_acceptance")
EXTEND = function(SOURCE, "extend_acceptance")
with open(os.path.join(LIB, "core", "ui.sh")) as fh:
    UI = fh.read()
IS_YES = function(UI, "is_yes") + function(UI, "is_no")

# Answers --reworded with the difference in `differs`, and records --reword.
FAKE = r'''#!/usr/bin/env python3
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the fake lib, above cycle/
mode = sys.argv[1]
if mode == "--reworded":
    with open(os.path.join(here, "differs")) as fh:
        sys.stdout.write(fh.read())
elif mode == "--extend":
    with open(os.path.join(here, "extended")) as fh:
        sys.stdout.write(fh.read())
elif mode == "--reword":
    with open(os.path.join(here, "written"), "a") as fh:
        fh.write(sys.argv[2] + "\n")
    sys.stdout.write("reworded\n")
'''

tmp = tempfile.mkdtemp(prefix="sclaude-reword-")
try:
    lib = os.path.join(tmp, "lib")
    os.makedirs(os.path.join(lib, "cycle"))
    with open(os.path.join(lib, "cycle", "acceptance.py"), "w") as fh:
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
        script = ('source "%s/core/state.sh"\nLIB="%s"\nBOLD=""; OFF=""\n'
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

    # extend_acceptance lists what it wrote under "updated", and a criterion
    # the plan words otherwise apart from it: listed among the additions, it
    # read as if the issue had taken the new wording.
    def extend(out_text):
        with open(os.path.join(lib, "extended"), "w") as fh:
            fh.write(out_text)
        script = ('source "%s/core/state.sh"\nLIB="%s"\n'
                  'info() { printf "I %%s\\n" "$*"; }\nwarn() { printf "W %%s\\n" "$*"; }\n'
                  '%s\nextend_acceptance "%s"\n') % (os.path.abspath(LIB), lib, EXTEND, wt)
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True).stdout

    out = extend("extended\nAC3 added\nAC2 reads differently\n")
    lines = out.splitlines()
    updated = next(i for i, l in enumerate(lines) if "updated from the plan" in l)
    differ = next((i for i, l in enumerate(lines) if "differ from issue" in l), None)
    check("extend: the addition is listed as updated",
          lines[updated + 1].strip(), "I     AC3 added".strip())
    check("extend: a reworded criterion gets its own warning", differ is not None, True)
    check("extend: ...below the additions, not among them",
          differ is not None and lines.index("I     AC2 reads differently") > differ, True)
    out = extend("extended\nAC3 added\n")
    check("extend: nothing reworded, no warning", "differ from issue" in out, False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.exit(1)
print("ok")
