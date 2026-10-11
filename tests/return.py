#!/usr/bin/env python3
#
# Returning a finished feature to development, by hand.
#
# QA moving the card out of "In QA" has always sent a feature back to step 4.
# Every other reason did not have a way: PR #143 in social went to "done" on a
# review that read a third of it, and its ten real findings could only be sent
# back by pretending QA had moved the card. `sclaude return` is that same return
# under its own name, and both paths now land in one place.
#
# Guarded here:
#
#   * return_since — the watch's mark first, else when step 4 closed, in UTC;
#   * return_to_development — the notes (reason first), the card moved from
#     "In QA" to "In progress", the column recorded so the timer does not
#     announce it, and the verdict cmd_resume acts on;
#   * the rewind marks the state `returned` and records the mark;
#   * return_brief — the session is told where to read, and from when;
#   * a silent return still briefs a fresh session;
#   * `sclaude return` refuses a feature that is not finished.
#
# Run it with: python3 tests/return.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def run_bash(script, cwd, home, instruments,
             modules=("io", "ui", "steps", "state", "watch")):
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
    body += 'HOME=%s; INSTRUMENTS=%s\n' % (home, instruments)
    body += 'QA_TO="In QA"; QA_FROM="In progress"; PROGRESS_FROM="Backlog"; QA_DONE="Done"\n'
    for name in modules:
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('die()  { echo "$*" >&2; exit 1; }\n'
             'warn() { echo "$*" >&2; }\n'
             'info() { echo "$*"; }\n'
             'say()  { echo "$*"; }\n'
             'issue_sync() { :; }\n'
             'gh_repo() { echo o/r; }\n'
             # The board, as a log of the moves asked for and one column read.
             'issue_move_status() { echo "MOVE $*" >> "%s/moves"; }\n'
             'issue_status_now() { echo "In progress"; }\n' % home)
    body += script
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, timeout=30)
    return out.stdout, out.stderr, out.returncode


def feature(root, step="done", finished="2026-10-01T19:46:28+01:00"):
    wt = os.path.join(root, "wt")
    os.makedirs(os.path.join(wt, ".feature"), exist_ok=True)
    state = {"feature": "demo", "branch": "feat/demo", "issue": 71, "pr": 208,
             "step": step,
             "steps": {"plan": {"done": True}, "code": {"done": True},
                       "pr": {"done": True},
                       "review": {"done": True, "finished": finished}},
             "regression": {"preview": {"status": "passed"}}}
    with open(os.path.join(wt, ".feature", "state.json"), "w") as fh:
        json.dump(state, fh)
    return wt


def read_state(wt):
    with open(os.path.join(wt, ".feature", "state.json")) as fh:
        return json.load(fh)


tmp = tempfile.mkdtemp()
try:
    home = os.path.join(tmp, "home")
    watch = os.path.join(home, ".claude", "sclaude", "watch")
    os.makedirs(watch)
    # A stand-in for bin/sclaude-watch: `--notes` prints what it was asked.
    inst = os.path.join(tmp, "instruments")
    os.makedirs(os.path.join(inst, "bin"))
    with open(os.path.join(inst, "bin", "sclaude-watch"), "w") as fh:
        fh.write('#!/usr/bin/env bash\n'
                 '[[ "$1" == "--notes" ]] || exit 1\n'
                 'echo "### On issue #$3"; echo; echo "notes for $2 #$3 PR $4 since $5"\n')
    os.chmod(os.path.join(inst, "bin", "sclaude-watch"), 0o755)

    # --- return_since --------------------------------------------------------
    wt = feature(tmp)
    out, _, _ = run_bash('return_since "%s" demo' % wt, wt, home, inst)
    check("since-from-review-finished-in-utc", out.strip(), "2026-10-01T18:46:28+00:00")
    with open(os.path.join(watch, "demo.json"), "w") as fh:
        json.dump({"since": "2026-10-01T18:55:52+00:00"}, fh)
    out, _, _ = run_bash('return_since "%s" demo' % wt, wt, home, inst)
    check("since-prefers-the-watch-mark", out.strip(), "2026-10-01T18:55:52+00:00")
    os.remove(os.path.join(watch, "demo.json"))

    # --- return_to_development ----------------------------------------------
    out, err, rc = run_bash(
        'return_to_development "%s" demo "the review missed ten findings"' % wt,
        wt, home, inst)
    check("return-succeeds", rc, 0)
    with open(os.path.join(watch, "demo.qa.md")) as fh:
        notes = fh.read()
    check("reason-comes-first", notes.startswith("### The reason given\n\nthe review missed ten findings"), True)
    check("notes-collected-from-the-mark",
          "notes for o/r #71 PR 208 since 2026-10-01T18:46:28+00:00" in notes, True)
    with open(os.path.join(home, "moves")) as fh:
        check("card-moved-from-qa-to-progress", fh.read().strip(), "MOVE 71 In QA In progress")
    with open(os.path.join(watch, "demo.json")) as fh:
        w = json.load(fh)
    check("verdict-returned", w.get("verdict"), "returned")
    check("column-recorded-for-the-timer", w.get("status"), "In progress")

    # The board path and this one meet in qa_take_back: the rewind.
    out, err, rc = run_bash('qa_take_back "%s" demo' % wt, wt, home, inst)
    st = read_state(wt)
    check("rewound-to-review", st.get("step"), "review")
    check("marked-returned", st.get("reopened_by"), "returned")
    check("mark-recorded", st.get("reopened_since"), "2026-10-01T18:46:28+00:00")
    check("preview-verdict-cleared", st["regression"]["preview"].get("status"), None)

    # --- return_brief ---------------------------------------------------------
    out, _, _ = run_bash('return_brief "%s" 71 208' % wt, wt, home, inst,
                         modules=("io", "ui", "steps", "state", "watch", "run"))
    check("brief-names-the-mark", "since 2026-10-01T18:46:28+00:00" in out, True)
    check("brief-reads-the-issue", "`gh issue view 71 --json comments`" in out, True)
    check("brief-reads-the-pr-lines", "pulls/208/comments" in out, True)
    out, _, _ = run_bash('return_brief "%s" null null' % wt, wt, home, inst,
                         modules=("io", "ui", "steps", "state", "watch", "run"))
    check("brief-without-issue-or-pr", "gh " in out, False)

    # --- a silent return still briefs a fresh session -------------------------
    with open(os.path.join(LIB, "run.sh")) as fh:
        run_src = fh.read()
    fresh = run_src[run_src.index('local qa_fresh; qa_fresh='):]
    fresh = fresh[:fresh.index('issue_sync "$wt"')]
    check("silent-return-branch-present",
          'reopened_by 2>/dev/null || true)" == "returned" ]]' in fresh
          and 'return_brief' in fresh.split("elif", 1)[1], True)

    # --- `sclaude return` refuses an unfinished feature ----------------------
    with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
        src = fh.read()
    body = src[src.index("cmd_return() {"):]
    body = body[:body.index("\n}\n") + 3]
    check("only-from-done", 'if [[ "$step" != "done" ]]; then' in body, True)
    check("hands-over-to-resume", body.rstrip().endswith('cmd_resume "$slug"\n}')
          or 'cmd_resume "$slug"' in body.splitlines()[-2], True)
    check("dispatched", 'return)        shift;' in src, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
