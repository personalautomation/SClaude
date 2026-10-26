#!/usr/bin/env python3
#
# The figures of a review run on this machine (`review: local`), which posts
# its findings as threads like the workflow but runs nowhere GitHub records:
#
#   * review_report.py counts the threads as always, and takes the rounds from
#     the local review's journal instead of the workflow's runs;
#   * run_local_round adds a round to the review session handed one, for its
#     row in the issue;
#   * in `local` the checks GitHub Actions ran are dropped from every reading
#     of the pull request (pr_view), and the mode is read from the main
#     checkout first;
#   * the local review's own words are not taken for a person's;
#   * a pull request that replaced a merged one starts the report afresh.
#
# Run it with: python3 tests/local-review-report.py
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


tmp = tempfile.mkdtemp()
try:
    wt = os.path.join(tmp, "wt")
    feature = os.path.join(wt, ".sclaude", "local", "feature")
    journal = os.path.join(feature, "local-review-rounds.jsonl")

    # --- the issue row ------------------------------------------------------------
    write(os.path.join(feature, "state.json"), json.dumps(
        {"steps": {"review": {"runs": [{"session": "s1", "rounds": 1}]}}}))
    body = 'source "%s/local_review.sh"\n' % LIB
    for _ in range(2):
        subprocess.run(["bash", "-c", body + 'run_local_round %s s1' % wt], check=True)
    with open(os.path.join(feature, "state.json")) as fh:
        run = json.load(fh)["steps"]["review"]["runs"][0]
    # Opened with its first round counted; each local review that brings it
    # back adds one.
    check("issue-rounds", run.get("rounds"), 3)

    # --- the report ---------------------------------------------------------------
    import review_report
    check("no-journal", review_report.local_runs(wt), None)
    write(journal, "\n".join(json.dumps({"at": "2026-10-15T1%d:00:00+00:00" % i, "seconds": 300,
                                         "base": "x", "head": "h%d" % i, "new": 1, "resolved": 0})
                             for i in range(3)) + "\n")
    runs = review_report.local_runs(wt)
    check("runs", [r["start"].hour for r in runs], [10, 11, 12])
    # Passes over one range are one review run.
    with open(journal, "a") as fh:
        for minute in ("05", "09"):
            fh.write(json.dumps({"at": "2026-10-15T12:%s:00+00:00" % minute, "seconds": 120,
                                 "base": "x", "head": "h2", "new": 1}) + "\n")
    runs = review_report.local_runs(wt)
    check("passes-one-run", ([r["start"].hour for r in runs], runs[-1]["seconds"]),
          ([10, 11, 12], 540.0))
    write(journal, "\n".join(json.dumps({"at": "2026-10-15T1%d:00:00+00:00" % i, "seconds": 300,
                                         "base": "x", "head": "h%d" % i, "new": 1, "resolved": 0})
                             for i in range(3)) + "\n")

    def at(h):
        return datetime.datetime(2026, 10, 15, h, 5, tzinfo=datetime.timezone.utc)

    def thread(n, h, fate):
        return {"id": str(n), "cites": set(), "path": "a.ts", "line": n * 20,
                "created": at(h), "round": None, "fate": fate, "left_open": False}

    review_report.threads = lambda cwd, pr, repo: [thread(1, 10, "fixed"), thread(2, 10, "no fix"),
                                                   thread(3, 11, "fixed"), thread(4, 12, "open")]
    review_report.review_runs = lambda cwd, branch, since: failures.append(("workflow-runs-read", "", ""))
    real_pr_created = review_report.pr_created
    review_report.pr_created = lambda cwd, pr: None
    review_report.review_mode = lambda cwd: "local"
    sys.argv = ["review_report.py", wt, "7", "o/r", "feature"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        review_report.main()
    out = buf.getvalue()
    check_true("report-says-local", "reviewed on this machine" in out)
    check_true("report-per-round", "oldest first: 2 1 1" in out)
    check_true("report-local-runs", "Local review: 3 runs" in out and "no Actions minutes" in out)
    check_true("report-fates", "Fixed: 2 (50%). Closed without a fix: 1 (25%)" in out)

    # Switched back to the workflow: a journal left from the local rounds is
    # not read, the workflow's runs are.
    review_report.review_mode = lambda cwd: "github"
    asked = []
    review_report.review_runs = lambda cwd, branch, since: asked.append(branch) or []
    buf = io.StringIO()
    with redirect_stdout(buf):
        review_report.main()
    check("github-mode-reads-workflow-runs", asked, ["feature"])
    check_true("github-mode-not-local", "reviewed on this machine" not in buf.getvalue())

    # --- a second pull request ---------------------------------------------
    # A feature reopened after its merge goes on under a new pull request, in
    # the same state and journal. The report starts when that one opened:
    # counted with it, the merged one's rounds, whose threads are not read,
    # were rounds that found nothing, and its first findings read as a review
    # that stopped converging.
    real_gh_json = review_report.gh_json
    review_report.gh_json = lambda args, cwd=None: {"createdAt": "2026-10-15T10:30:00Z"}
    since = real_pr_created(wt, 9)
    # Less a margin for this machine's clock, which stamps the journal.
    check("pr-created", (since.hour, since.minute), (10, 28))
    review_report.gh_json = lambda args, cwd=None: None
    check("pr-created-unreadable", real_pr_created(wt, 9), None)
    review_report.gh_json = real_gh_json
    write(os.path.join(feature, "state.json"), json.dumps({"steps": {"review": {"runs": [
        {"session": s, "started": "2026-10-15T%s:00+00:00" % a, "finished": "2026-10-15T%s:00+00:00" % b,
         "done": True} for s, a, b in (("a", "09:00", "10:00"), ("b", "10:20", "10:50"),
                                       ("c", "11:00", "11:20"))]
        # One of the merged pull request's that never ended, and the last,
        # still going.
        + [{"session": "d", "started": "2026-10-15T09:30:00+00:00"},
           {"session": "e", "started": "2026-10-15T11:30:00+00:00"}]}}}))
    check("since-journal", [r["start"].hour for r in review_report.local_runs(wt, since)], [11, 12])
    # The session that opened the pull request is still the new one's.
    check("since-sessions", [s["start"].strftime("%H:%M") for s in review_report.sessions(wt, since)],
          ["10:20", "11:00", "11:30"])
    check("unknown-since-journal", [r["start"].hour for r in review_report.local_runs(wt)], [10, 11, 12])
    check("unknown-since-sessions", len(review_report.sessions(wt)), 5)
    # No verdict on rounds that may be two pull requests': the opening of
    # the new one could not be read on a reopened feature.
    check("reopened", review_report.reopened(wt), False)
    write(os.path.join(feature, "state.json"), json.dumps({"reopened_pr": 7}))
    check("reopened-after-merge", review_report.reopened(wt), True)

    # capture_reopened_pr records the new pull request a step-4 session opened
    # on a reopened feature, and nothing else: asked of the feature's branch,
    # and only with the tree on it.
    subprocess.run(["git", "init", "-q", "-b", "feat", wt], check=True)

    def captured(state, number, on="feat"):
        subprocess.run(["git", "-C", wt, "symbolic-ref", "HEAD", "refs/heads/" + on], check=True)
        state = dict({"branch": "feat"}, **state)
        write(os.path.join(feature, "state.json"), json.dumps(state))
        subprocess.run(["bash", "-c", 'source "%s/state.sh"; source "%s/github.sh"; '
                        'gh() { [[ "$3" == --json || "$3" == feat ]] && echo %s; }; info() { :; }; '
                        'pr_link_issue() { :; }; pr_setup() { :; }; issue_hold_open() { :; }; '
                        'capture_reopened_pr "%s"' % (LIB, LIB, number, wt)], check=True)
        with open(os.path.join(feature, "state.json")) as fh:
            return json.load(fh).get("pr")
    check("reopened-new-pr", captured({"pr": 7, "reopened_pr": 7}, 9), 9)
    check("reopened-not-yet", captured({"pr": 7, "reopened_pr": 7}, 7), 7)
    check("not-reopened", captured({"pr": 7}, 9), 7)
    check("reopened-already-recorded", captured({"pr": 9, "reopened_pr": 7}, 11), 9)
    check("reopened-tree-elsewhere", captured({"pr": 7, "reopened_pr": 7}, 9, on="other"), 7)
    # Step 4's close records it before its gate, which would read the merged one.
    run_sh = open(os.path.join(LIB, "run.sh"), encoding="utf-8").read()
    close = run_sh[run_sh.index("    review)\n      # A reopened feature"):]
    check_true("close-captures-before-gate",
               close.index("capture_reopened_pr") < close.index("review_close_gate"))

    # --- the door the pull request is read through --------------------------
    import pr_context
    rollup = [{"name": "Checks", "workflowName": "Checks", "conclusion": "FAILURE"},
              {"context": pr_context.FINDINGS_CHECK, "state": "FAILURE"},
              {"name": "Vercel", "workflowName": "", "conclusion": "SUCCESS"}]
    real_gh, real_mode = pr_context.gh, pr_context.review_mode
    pr_context.gh = lambda args, cwd=None: json.dumps({"statusCheckRollup": rollup})
    pr_context.review_mode = lambda cwd: "local"
    got = pr_context.pr_view(None, 7, "statusCheckRollup")
    check("local-drops-actions", [c.get("name") for c in got["statusCheckRollup"]], ["Vercel"])
    # The findings check also comes as a check run made through the API: it
    # names no workflow, only itself.
    check("local-drops-findings-run", pr_context.without_actions(
        [{"name": pr_context.FINDINGS_CHECK, "workflowName": "", "conclusion": "FAILURE"}]), [])
    got = pr_context.gh_json(["pr", "view", "7", "--json", "statusCheckRollup"])
    check("raw-read-untouched", len(got["statusCheckRollup"]), 3)
    pr_context.review_mode = lambda cwd: "github"
    got = pr_context.pr_view(None, 7, "statusCheckRollup")
    check("github-keeps-actions", len(got["statusCheckRollup"]), 3)
    pr_context.gh, pr_context.review_mode = real_gh, real_mode

    # And the mode itself: the main checkout first, as project.sh reads it.
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", repo], check=True)
    write(os.path.join(repo, ".sclaude", "config.json"), json.dumps({"review": "local"}))
    check("mode-from-main", pr_context.review_mode(repo), "local")
    tree = os.path.join(tmp, "tree")
    write(os.path.join(tree, ".sclaude", "config.json"), json.dumps({"review": "off"}))
    check("mode-from-tree-outside-git", pr_context.review_mode(tree), "off")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
