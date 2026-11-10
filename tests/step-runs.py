#!/usr/bin/env python3
#
# A test bench for the sessions a step ran in, and how the issue summary shows
# them.
#
# The rule: one row per claude conversation. The same conversation entered
# several times is one row, from its first start to its last exit; a new
# conversation is a row of its own. A conversation that never began has no row.
#
# step_run is sourced and run for real, against a state file in a temporary
# directory; the renderer is cut out of issue_sync and fed that file.
#
# Run it with: python3 tests/step-runs.py
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
# The renderer cut out of issue_sync imports state_file, as sclaude runs it
# (PYTHONPATH set by issue_sync).
os.environ["PYTHONPATH"] = os.path.join(LIB, "core")
github = "".join(open(os.path.join(LIB, _m), encoding="utf-8").read() for _m in ("github/github.sh", "github/issue_sync.sh", "github/board.sh", "github/outcome.sh"))

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def shell(wt, script):
    subprocess.run(
        ["bash", "-c", 'source "$1/core/state.sh"; source "$1/core/steps.sh"; wt="$2"; ' + script,
         "_", LIB, wt],
        check=True)


def render(state_path):
    body = re.search(r"body=\"\$\(SCLAUDE_STEPS=.*?<<'PY'[^\n]*\n(.*?)\nPY\n", github, re.S).group(1)
    spec = "plan=planning\ncode=development\npr=pull request\nreview=review\n"
    out = subprocess.run([sys.executable, "-", state_path], input=body, text=True,
                         capture_output=True, env={**os.environ, "SCLAUDE_STEPS": spec},
                         check=True).stdout
    return [line for line in out.splitlines() if line.startswith("| ") and "Step |" not in line]


with tempfile.TemporaryDirectory() as wt:
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    path = os.path.join(wt, ".sclaude/local/feature", "state.json")
    with open(path, "w") as fh:
        json.dump({"feature": "x", "step": "review", "steps": {
            # From before `runs`: its session is taken as the first run, with
            # the start the step already recorded.
            "code": {"session": "c0000000-old", "started": "2026-09-30T10:00:00+00:00"},
        }}, fh)

    shell(wt, '''
        step_run "$wt" code open c0000000-old
        step_run "$wt" code end c0000000-old
        step_run "$wt" code open c0000000-old
        step_run "$wt" code end c0000000-old
        step_run "$wt" code close
        step_run "$wt" review open r1111111
        step_run "$wt" review end r1111111
        step_run "$wt" review open r2222222
        step_run "$wt" review drop r2222222
        step_run "$wt" review open r3333333
    ''')
    with open(path) as fh:
        s = json.load(fh)
    code_runs = s["steps"]["code"]["runs"]
    check("same-session-is-one-run", len(code_runs), 1)
    check("first-start-kept", code_runs[0]["started"], "2026-09-30T10:00:00+00:00")
    check("close-marks-last-run", code_runs[0].get("done"), True)
    check("stillborn-session-dropped",
          [r["session"] for r in s["steps"]["review"]["runs"]], ["r1111111", "r3333333"])

    # The merge closes the review the preview fix reopened.
    shell(wt, 'state_set "$wt/.sclaude/local/feature/state.json" reopened_by preview; step_close_merged "$wt"')
    rows = render(path)
    titles = [r.split("|")[1].strip() for r in rows]
    check("one-row-per-session",
          titles, ["planning", "development", "pull request", "review (1)", "review (2)"])
    statuses = [r.split("|")[2].strip() for r in rows]
    check("statuses", statuses[3:], ["interrupted", "done"])
    check("closed-review-has-end", rows[4].split("|")[5].strip() != "—", True)

    # What the automatic review handed each review session: those open when
    # it began, plus every thread opened while it ran — a session can carry on
    # through several rounds. The fake answers "<open> <opened since>".
    fake = os.path.join(wt, "fakelib")
    os.makedirs(os.path.join(fake, "review"))
    with open(os.path.join(fake, "review/pr_context.py"), "w") as fh:
        fh.write("import os, sys\n"
                 "assert sys.argv[1] == '--threads' and sys.argv[5]\n"
                 "print(os.environ.get('THREADS', ''))\n")

    def comments(session, answer):
        subprocess.run(["bash", "-c",
                        'source "$1/core/state.sh"; source "$1/core/steps.sh"; LIB="$3"; '
                        'gh_repo() { echo o/r; }; THREADS="$5" run_comments "$2" "$4" 143',
                        "_", LIB, wt, fake, session, answer], check=True)

    comments("r1111111", "5 0")   # opens on five
    comments("r1111111", "3 4")   # two fixed, four new in the next round
    comments("r3333333", "1 0")
    comments("r3333333", "")      # unreadable: the count stays
    titles = [r.split("|")[1].strip() for r in render(path)]
    check("comments-shown", titles[3:], ["review (1) - 9 \U0001F4AC", "review (2) - 1 \U0001F4AC"])

    # The rounds a session worked follow its comments: one when it opens, one
    # more for every round it carried on into.
    def rounds(session, n):
        subprocess.run(["bash", "-c",
                        'source "$1/core/state.sh"; source "$1/core/steps.sh"; run_rounds "$2" "$3" "$4"',
                        "_", LIB, wt, session, str(n)], check=True)

    rounds("r1111111", 1)
    rounds("r1111111", 3)
    rounds("r3333333", "x")       # not a number: nothing written
    titles = [r.split("|")[1].strip() for r in render(path)]
    check("rounds-shown", titles[3:],
          ["review (1) - 9 \U0001F4AC - 3 \U0001F501", "review (2) - 1 \U0001F4AC"])
    body = subprocess.run([sys.executable, "-", path], text=True, capture_output=True,
                          input=re.search(r"body=\"\$\(SCLAUDE_STEPS=.*?<<'PY'[^\n]*\n(.*?)\nPY\n",
                                          github, re.S).group(1),
                          env={**os.environ, "SCLAUDE_STEPS": "review=review\n"}).stdout
    check("no-legend-under-table", "review comments" in body or "review rounds" in body, False)

    # A friction review that stalled and was started again: both are named in
    # the cell, the stalled one first.
    shell(wt, '''
        f="$wt/.sclaude/local/feature/state.json"
        session_runs "$f" friction.review open s1111111
        session_runs "$f" friction.review stall s1111111
        session_runs "$f" friction.review open s2222222
        session_runs "$f" friction.review finish s2222222 fixed
        state_set "$f" friction.review.done true
        state_set "$f" friction.review.was s2222222
        state_set "$f" friction.review.fixed true
        session_runs "$f" epilogue open e1111111
        session_runs "$f" epilogue finish e1111111
        session_runs "$f" epilogue open e2222222
        session_runs "$f" epilogue drop e2222222
    ''')
    rows = render(path)
    review_row = [r for r in rows if r.startswith("| review (2)")][0]
    check("friction-cell-names-every-review", review_row.split("|")[6].strip(),
          "`s1111111` stalled<br>`s2222222` fixed")
    # A stalled transcript still exists, so the next attempt resumes the same
    # conversation: one run, and no longer stalled once it has finished.
    shell(wt, '''
        f="$wt/.sclaude/local/feature/state.json"
        session_runs "$f" friction.fix-preview-1 open t1111111
        session_runs "$f" friction.fix-preview-1 stall t1111111
        session_runs "$f" friction.fix-preview-1 open t1111111
        session_runs "$f" friction.fix-preview-1 finish t1111111 reviewed
    ''')
    with open(path) as fh:
        resumed = json.load(fh)["friction"]["fix-preview-1"]["runs"]
    check("resumed-stall-is-one-run", len(resumed), 1)
    check("resumed-stall-cleared", resumed[0].get("stalled"), None)
    check("resumed-stall-outcome", resumed[0].get("outcome"), "reviewed")

    # A sync's friction review (sync-N, sync.sh) is named in its row.
    shell(wt, '''
        f="$wt/.sclaude/local/feature/state.json"
        session_runs "$f" sync open y1111111
        session_runs "$f" sync finish y1111111
        session_runs "$f" friction.sync-1 open z1111111
        session_runs "$f" friction.sync-1 finish z1111111 fixed
        state_set "$f" friction.sync-1.done true
        state_set "$f" friction.sync-1.was z1111111
        state_set "$f" friction.sync-1.fixed true
    ''')
    sync_row = [r for r in render(path) if r.startswith("| sync with main")][0]
    check("sync-row-names-its-friction-review", "—" not in sync_row.split("|")[6], True)

    # A part's own demo (demo_part) and a refresh: each named and counted
    # among its own kind and part, the part said once.
    shell(wt, '''
        f="$wt/.sclaude/local/feature/state.json"
        SCLAUDE_ABOUT="part 1" SCLAUDE_ABOUT_PART=1 session_runs "$f" demo open d1111111
        SCLAUDE_ABOUT="part 1" SCLAUDE_ABOUT_PART=1 session_runs "$f" demo finish d1111111
        SCLAUDE_ABOUT="part 2" SCLAUDE_ABOUT_PART=2 session_runs "$f" demo open d2222222
        SCLAUDE_ABOUT="part 2" SCLAUDE_ABOUT_PART=2 session_runs "$f" demo finish d2222222
        SCLAUDE_ABOUT="preview" session_runs "$f" demo open d3333333
        SCLAUDE_ABOUT="preview" session_runs "$f" demo finish d3333333
    ''')
    demo_rows = [r.split("|")[1].strip() for r in render(path) if "demo" in r.split("|")[1]]
    check("demo rows: a part's demo by its part, a refresh apart, each counted among its own",
          demo_rows, ["part demo · part 1", "part demo · part 2", "demo refresh"])

    # Syncs across parts keep their position, which their friction reviews'
    # titles (sync-<n>) name them by.
    with open(path) as fh:
        data = json.load(fh)
    data["sync"] = {"runs": [{"session": "s%d" % k, "part": p} for k, p in ((1, "1"), (2, "2"), (3, "2"))]}
    with open(path, "w") as fh:
        json.dump(data, fh)
    sync_rows = [r.split("|")[1].strip() for r in render(path) if r.startswith("| sync with main")]
    check("sync rows: numbered by position across parts",
          sync_rows, ["sync with main (1) · part 1", "sync with main (2) · part 2", "sync with main (3) · part 2"])

    status_rows = [r for r in rows if r.startswith("| status update")]
    check("epilogue-is-a-row", len(status_rows), 1)
    check("epilogue-row-done", status_rows[0].split("|")[2].strip(), "done")


# --- a friction review per session -----------------------------------------
#
# The key names the session by its row: `review-2` is the second run of the
# review step. Every ended session has one; the running one is queued; a
# step-wide key from before is shown on the last row only, and never on a row
# still running — that is how one live seventh round read `nothing`.
def sh_out(wt, script):
    return subprocess.run(
        ["bash", "-c", 'source "$1/core/state.sh"; source "$1/core/steps.sh"; wt="$2"; ' + script,
         "_", LIB, wt], check=True, capture_output=True, text=True).stdout.strip()


with tempfile.TemporaryDirectory() as wt:
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    path = os.path.join(wt, ".sclaude/local/feature", "state.json")
    with open(path, "w") as fh:
        json.dump({"feature": "x", "step": "review", "steps": {},
                   "friction": {"review": {"empty": True}}}, fh)
    shell(wt, '''
        step_run "$wt" code open c1111111
        step_run "$wt" code end c1111111
        step_run "$wt" code close
        step_run "$wt" review open r1111111
        step_run "$wt" review end r1111111 "fixes confirmed"
        step_run "$wt" review open r2222222
        step_run "$wt" review end r2222222 "fixes confirmed"
        step_run "$wt" review open r3333333
    ''')
    f = "$wt/.sclaude/local/feature/state.json"
    check("key-of-session", sh_out(wt, 'step_run_key "%s" review r2222222' % f), "review-2")
    check("key-of-latest", sh_out(wt, 'step_run_key "%s" review' % f), "review-3")
    check("key-without-runs", sh_out(wt, 'step_run_key "%s" plan' % f), "plan")
    check("session-of-key", sh_out(wt, 'step_run_session "%s" review-1' % f), "r1111111")
    check("session-of-fix-key", sh_out(wt, 'step_run_session "%s" fix-preview-1' % f), "")
    check("last-run-key", sh_out(wt, 'last_run_key "%s"' % f), "review-3")

    # Legacy only: the step-wide `nothing` must not reach the running round.
    cells = {r.split("|")[1].strip(): r.split("|")[6].strip() for r in render(path)}
    check("legacy-running-row-queued", cells["review (3)"], "queued")
    check("legacy-earlier-row-dash", cells["review (1)"], "—")

    shell(wt, '''
        f="$wt/.sclaude/local/feature/state.json"
        state_set "$f" friction.review-1.empty true
        state_set "$f" friction.review-2.done true
        state_set "$f" friction.review-2.was s2222222
        state_set "$f" friction.review-2.fixed true
        state_set "$f" friction.code-1.empty true
    ''')
    cells = {r.split("|")[1].strip(): r.split("|")[6].strip() for r in render(path)}
    check("per-run-empty", cells["review (1)"], "nothing")
    check("per-run-fixed", cells["review (2)"], "`s2222222` fixed")
    check("per-run-running-queued", cells["review (3)"], "queued")
    check("per-run-single-row-step", cells["development"], "nothing")

def render_all(state_path, running=""):
    body = re.search(r"body=\"\$\(SCLAUDE_STEPS=.*?<<'PY'[^\n]*\n(.*?)\nPY\n", github, re.S).group(1)
    spec = "plan=planning\ncode=development\npr=pull request\nreview=review\n"
    env = {**os.environ, "SCLAUDE_STEPS": spec, "TZ": "UTC"}
    env.pop("SCLAUDE_SUMMARY_RUNNING", None)
    if running:
        env["SCLAUDE_SUMMARY_RUNNING"] = running
    return subprocess.run([sys.executable, "-", state_path], input=body, text=True,
                          capture_output=True, env=env, check=True).stdout


# The heading names the kind of comment and nothing of the feature; every
# local review pass a model ran is a row; the retrospective while it runs is
# in progress, not interrupted.
with tempfile.TemporaryDirectory() as wt:
    feature = os.path.join(wt, ".sclaude/local/feature")
    os.makedirs(feature)
    path = os.path.join(feature, "state.json")
    with open(path, "w") as fh:
        json.dump({"feature": "42-some-thing", "step": "done", "pr": 7,
                   "retro": {"runs": [{"session": "t1111111-x", "started": "2026-10-02T10:00:00+00:00"}]}}, fh)
    with open(os.path.join(feature, "review-rounds.jsonl"), "w") as fh:
        for row in ({"at": "2026-10-01T09:00:00+00:00", "seconds": 120, "new": 3, "session": "p1111111-a"},
                    {"at": "2026-10-01T09:30:00+00:00", "seconds": 0, "new": 0},
                    {"at": "2026-10-01T10:00:00+00:00", "seconds": 60, "new": 1},
                    {"at": "2026-10-01T10:30:00+00:00", "seconds": 40, "spent": True,
                     "session": "s1111111-b"}):
            fh.write(json.dumps(row) + "\n")
    out = render_all(path, running="retro")
    lines = out.splitlines()
    check("heading-is-the-first-visible-line", lines[1], "## Sessions and progress")
    check("heading-names-nothing-of-the-feature", "42" in lines[1] or "some-thing" in lines[1], False)
    check("feature-below-the-heading", "Feature `42-some-thing`" in lines[3], True)
    passes = [r for r in lines if r.startswith("| local review")]
    check("a-row-per-pass-a-model-ran", len(passes), 3)
    check("a-stopped-pass-is-not-done", passes[2].split("|")[2].strip(), "stopped, not recorded")
    check("pass-row-names-session-and-findings",
          [c.strip() for c in passes[0].split("|")[1:6]],
          ["local review (1) - 3 \U0001F4AC", "done", "`p1111111`", "2026-10-01 09:00", "2026-10-01 09:02"])
    check("pass-from-before-ids-has-a-dash", passes[1].split("|")[3].strip(), "—")
    retro = [r for r in lines if r.startswith("| retrospective")]
    check("running-retro-in-progress", retro[0].split("|")[2].strip(), "in progress")
    # Not said to be running, an open run is one cut off: interrupted.
    retro = [r for r in render_all(path).splitlines() if r.startswith("| retrospective")]
    check("open-retro-not-running-interrupted", retro[0].split("|")[2].strip(), "interrupted")
    # A resumed one keeps its earlier end, and still runs when it is said to.
    with open(path) as fh:
        st = json.load(fh)
    st["retro"]["runs"][0].update(finished="2026-10-02T10:30:00+00:00", done=True,
                                  resumed="2026-10-02T11:00:00+00:00")
    with open(path, "w") as fh:
        json.dump(st, fh)
    retro = [r for r in render_all(path, running="retro").splitlines() if r.startswith("| retrospective")]
    check("resumed-retro-running", retro[0].split("|")[2].strip(), "in progress")
    check("resumed-retro-head", "· step 7/7 retro" in render_all(path, running="retro"), True)
    check("finished-retro-head", "· all done" in render_all(path), True)
    # The journal is UTC; the row is in the machine's own time.
    env = {**os.environ, "SCLAUDE_STEPS": "review=review\n", "TZ": "Etc/GMT-3"}
    body = re.search(r"body=\"\$\(SCLAUDE_STEPS=.*?<<'PY'[^\n]*\n(.*?)\nPY\n", github, re.S).group(1)
    local = subprocess.run([sys.executable, "-", path], input=body, text=True,
                           capture_output=True, env=env, check=True).stdout
    first = [r for r in local.splitlines() if r.startswith("| local review (1)")][0]
    check("pass-in-local-time", [c.strip() for c in first.split("|")[4:6]],
          ["2026-10-01 12:00", "2026-10-01 12:02"])

for name, want, got in failures:
    print("FAIL %s\n  expected: %r\n  got:      %r" % (name, want, got))
if failures:
    print("\n%d check(s) failed." % len(failures))
    sys.exit(1)
print("All checks passed.")
