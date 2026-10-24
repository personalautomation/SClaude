#!/usr/bin/env python3
#
# The names sclaude gives a feature's sessions (`claude -n`), numbered so the
# status line, which cuts a long name short, still says which session it is:
#
#   * steps are 1-4 in STEPS order, a second conversation of a step is
#     `1-plan(2)`: the round always comes last, and the first has none;
#   * a friction review carries the number of the session it reviews;
#   * a fixing session goes under the step it fixes in;
#   * the sync with main is 5, the epilogue 6, the retrospective 7;
#   * the name carries the emoji of its kind before the slug
#     (named_with_icon), a friction review of a fixing session counted as
#     friction.
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
    check("code-again", label("step", state, "code", "c2"), "2-code(2)")
    check("review-first", label("step", state, "review", "r1"), "4-review")
    check("review-second", label("step", state, "review", "r2"), "4-review(2)")
    number = lambda *a: subprocess.run(
        ["bash", "-c", 'source "%s/steps.sh"; step_session_number "$@"' % LIB, "bash"] + list(a),
        capture_output=True, text=True, timeout=30).stdout.strip()
    check("session-number-second", number(state, "code", "c2"), "2")
    check("session-number-none", number(state, "pr", "x"), "")

check("friction-plan", label("friction", "plan-1"), "1-friction")
check("friction-review", label("friction", "review-2"), "4-friction(2)")
check("friction-old-key", label("friction", "code"), "2-friction")
check("friction-fix", label("friction", "fix-preview-1"), "4-fix-preview-friction")
check("friction-fix-again", label("friction", "fix-prod-3"), "4-fix-prod-friction(3)")
check("fix-local", label("fix", "fix-local-2"), "2-fix-local(2)")
check("fix-first", label("fix", "fix-preview-1"), "4-fix-preview")
check("sync", label("sync", "1"), "5-sync")
check("sync-again", label("sync", "2"), "5-sync(2)")
check("epilogue", label("epilogue"), "6-epilogue")
check("retro", label("retro"), "7-retro")


def icon(title):
    p = subprocess.run(["bash", "-uc", 'source "%s/steps.sh"; source "%s/pane.sh"; pane_icon "$1"' % (LIB, LIB), "bash", title],
                       capture_output=True, text=True, timeout=30)
    return p.stdout


for title, want in (("1-plan/x", "📝"), ("2-code(2)/x", "💻"), ("3-pr/x", "📤"),
                    ("4-review/x", "🛠"), ("4-review(2)/x", "🛠"), ("4-friction(2)/x", "🧱"),
                    ("4-fix-preview(2)/x", "🔧"), ("4-fix-preview-friction/x", "🧱"),
                    ("5-sync/x", "🔀"), ("5-sync(2)/x", "🔀"),
                    ("6-epilogue/x", "🏁"), ("7-retro/x", "🔁"),
                    ("friction/deferred", "🧱"), ("demo/code", "")):
    check("icon " + title, icon(title), want)



def named(name):
    p = subprocess.run(["bash", "-uc", 'source "%s/steps.sh"; source "%s/pane.sh"; named_with_icon "$1"' % (LIB, LIB), "bash", name],
                       capture_output=True, text=True, timeout=30)
    return p.stdout


# The emoji goes into the name, before the slug: claude titles the tab with
# the name, and cuts it at the end.
for name, want in (("4-review(2)/x", "4-review(2) 🛠/x"), ("1-plan/x", "1-plan 📝/x"),
                   ("4-review(2) 🛠/x", "4-review(2) 🛠/x"), ("demo/code", "demo/code"),
                   ("chat", "chat")):
    check("named " + name, named(name), want)
    check("icon kept " + name, icon(named(name)), icon(name))

# The line that tells a session started or ended: one shape for every kind,
# numbered over the seven of the cycle as the menu numbers it.
def phase(*args):
    script = 'source "%s/steps.sh"; source "%s/regression.sh"; phase_line "$@"' % (LIB, LIB)
    return subprocess.run(["bash", "-c", script, "bash"] + list(args),
                          capture_output=True, text=True, timeout=30).stdout.strip()


for args, want in (
        (("started", "step", "plan", "1"), "📝 Step 1/7 planning: session 1 started"),
        (("finished", "step", "review", "2"), "🛠 Step 4/7 review: fix session 2 finished"),
        (("done", "step", "review"), "✅ Step 4/7 done: review"),
        (("finished", "step", "review", "1", "3"), "🛠 Step 4/7 review: fix session 1, round 3 finished"),
        (("finished", "friction", "review-3"), "🧱 Friction review finished: after step 4/7 review, fix session 3"),
        (("ended", "friction", "code"), "🧱 Friction review ended: after step 2/7 development"),
        (("started", "friction", "fix-preview-1"), "🧱 Friction review started: after the preview regression fix 1"),
        (("started", "fix", "local", "e2e"), "🔧 Regression fix started: local, on e2e"),
        (("finished", "fix", "preview"), "🔧 Regression fix finished: preview"),
        (("started", "local-review", "7", "3"), "🔍 Local review started: PR #7, round 3"),
        (("finished", "local-review", "7", "4", "verify"), "🔍 Local review finished: PR #7, round 4, fixes only"),
        (("started", "sync", "2"), "🔀 Step 5/7 started: sync with main, session 2"),
        (("finished", "sync"), "🔀 Step 5/7 finished: sync with main"),
        (("finished", "epilogue"), "🏁 Step 6/7 finished: epilogue"),
        (("started", "retro"), "🔁 Step 7/7 started: retrospective"),
        (("finished", "deferred"), "🧱 Deferred friction review finished")):
    check("phase " + " ".join(args), phase(*args), want)

# The bot leads a message with exactly these icons (OWN_ICON): every one
# phase_icon gives, and no other.
sys.path.insert(0, os.path.join(LIB, "..", ".."))
from keepawake import notices  # noqa: E402
icons = subprocess.run(["bash", "-c", 'source "%s/steps.sh"; for a in "step plan" "step code" '
                        '"step pr" "step review" "step other" "step review done" friction deferred '
                        'fix local-review regression deploy sync epilogue retro; do '
                        'set -- $a; phase_icon "$1" "${2:-}" "${3:-}"; echo; done' % LIB],
                       capture_output=True, text=True, timeout=30).stdout.split()
check("the bot knows every phase icon", sorted(set(icons)), sorted(notices.PHASE_ICONS))

# The menu names the cycle's steps by their number (webmenu's act.steps):
# one name for each, in both languages.
from keepawake import i18n  # noqa: E402
total = subprocess.run(["bash", "-c", 'source "%s/steps.sh"; cycle_total' % LIB],
                       capture_output=True, text=True, timeout=30).stdout.strip()
for half in i18n.STRINGS["act.steps"]:
    check("act.steps names every step", str(len(half.split(" · "))), total)

# The banner a session opens with in the terminal names it as the topic does.
def title(*args):
    script = 'source "%s/steps.sh"; source "%s/regression.sh"; phase_title "$@"' % (LIB, LIB)
    return subprocess.run(["bash", "-c", script, "bash"] + list(args),
                          capture_output=True, text=True, timeout=30).stdout.strip()


for args, want in (
        (("step", "code"), "Step 2/7 development"),
        (("friction", "review-3"), "Friction review after step 4/7 review, fix session 3"),
        (("friction", "fix-local-2"), "Friction review after the local regression fix 2"),
        (("fix", "local", "e2e"), "Regression fix: local, on e2e"),
        (("regression", "preview"), "Regression: preview"),
        (("sync",), "Step 5/7 sync with main"),
        (("epilogue",), "Step 6/7 epilogue"),
        (("retro",), "Step 7/7 retrospective"),
        (("deferred",), "Deferred friction review"),
        # A key past the steps, as `sclaude friction` may pass, is said as it is.
        (("friction", "done"), "Friction review of done")):
    check("title " + " ".join(args), title(*args), want)

sys.exit(1 if failed else 0)
