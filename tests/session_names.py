#!/usr/bin/env python3
#
# The names sclaude gives a feature's sessions (`claude -n`), numbered so the
# status line, which cuts a long name short, still says which session it is:
#
#   * steps are 1-4 in STEPS order, a second conversation of a step is `1-2`;
#   * every review round is numbered, the first included: `4-1-review`;
#   * a friction review carries the number of the session it reviews;
#   * a fixing session goes under the step it fixes in;
#   * the epilogue is 5, the retrospective 6;
#   * a tab title starts with the emoji of its kind (pane_icon), a friction
#     review of a fixing session counted as friction.
#
# Run it with: python3 tests/session_names.py
import json
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s: want %r, got %r" % (name, want, got))


def label(*args):
    script = 'source "%s/steps.sh"; source "%s/regression.sh"; session_label "$@"' % (LIB, LIB)
    p = subprocess.run(["bash", "-c", script, "bash"] + list(args),
                       capture_output=True, text=True, timeout=30)
    return p.stdout.strip()


with tempfile.TemporaryDirectory() as tmp:
    state = os.path.join(tmp, "state.json")
    with open(state, "w") as fh:
        json.dump({"steps": {
            "plan": {"runs": [{"session": "p1"}]},
            "code": {"runs": [{"session": "c1"}, {"session": "c2"}]},
            "review": {"runs": [{"session": "r1"}, {"session": "r2"}]},
        }}, fh)
    check("plan", label("step", state, "plan", "p1"), "1-plan")
    check("code-again", label("step", state, "code", "c2"), "2-2-code")
    check("review-first", label("step", state, "review", "r1"), "4-1-review")
    check("review-second", label("step", state, "review", "r2"), "4-2-review")

check("friction-plan", label("friction", "plan-1"), "1-friction")
check("friction-review", label("friction", "review-2"), "4-2-friction")
check("friction-old-key", label("friction", "code"), "2-friction")
check("friction-fix", label("friction", "fix-preview-1"), "4-fix-preview-1-friction")
check("fix-local", label("fix", "fix-local-2"), "2-fix-local-2")
check("epilogue", label("epilogue"), "5-epilogue")
check("retro", label("retro"), "6-retro")


def icon(title):
    p = subprocess.run(["bash", "-c", 'source "%s/pane.sh"; pane_icon "$1"' % LIB, "bash", title],
                       capture_output=True, text=True, timeout=30)
    return p.stdout


for title, want in (("1-plan/x", "📝"), ("2-2-code/x", "💻"), ("3-pr/x", "📤"),
                    ("4-1-review/x", "🔍"), ("4-2-friction/x", "🧱"),
                    ("4-fix-preview-1/x", "🔧"), ("4-fix-preview-1-friction/x", "🧱"),
                    ("5-epilogue/x", "🏁"), ("6-retro/x", "🔁"),
                    ("friction/deferred", "🧱"), ("demo/code", "")):
    check("icon " + title, icon(title), want)

sys.exit(1 if failed else 0)
