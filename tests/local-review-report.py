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
#     of the pull request (gh_json), and the mode is read from the main
#     checkout first;
#   * the local review's own words are not taken for a person's.
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
    check("issue-rounds", run.get("rounds"), 2)

    # --- the report ---------------------------------------------------------------
    import review_report
    check("no-journal", review_report.local_runs(wt), None)
    write(journal, "\n".join(json.dumps({"at": "2026-10-15T1%d:00:00+00:00" % i, "seconds": 300,
                                         "base": "x", "head": "h%d" % i, "new": 1, "resolved": 0})
                             for i in range(3)) + "\n")
    runs = review_report.local_runs(wt)
    check("runs", [r["start"].hour for r in runs], [10, 11, 12])

    def at(h):
        return datetime.datetime(2026, 10, 15, h, 5, tzinfo=datetime.timezone.utc)

    def thread(n, h, fate):
        return {"id": str(n), "cites": set(), "path": "a.ts", "line": n * 20,
                "created": at(h), "round": None, "fate": fate, "left_open": False}

    review_report.threads = lambda cwd, pr, repo: [thread(1, 10, "fixed"), thread(2, 10, "no fix"),
                                                   thread(3, 11, "fixed"), thread(4, 12, "open")]
    review_report.review_runs = lambda cwd, branch: failures.append(("workflow-runs-read", "", ""))
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
    review_report.review_runs = lambda cwd, branch: asked.append(branch) or []
    buf = io.StringIO()
    with redirect_stdout(buf):
        review_report.main()
    check("github-mode-reads-workflow-runs", asked, ["feature"])
    check_true("github-mode-not-local", "reviewed on this machine" not in buf.getvalue())

    # --- the door the pull request is read through --------------------------
    import pr_context
    rollup = [{"name": "Checks", "workflowName": "Checks", "conclusion": "FAILURE"},
              {"context": pr_context.FINDINGS_CHECK, "state": "FAILURE"},
              {"name": "Vercel", "workflowName": "", "conclusion": "SUCCESS"}]
    real_gh, real_mode = pr_context.gh, pr_context.review_mode
    pr_context.gh = lambda args, cwd=None: json.dumps({"statusCheckRollup": rollup})
    pr_context.review_mode = lambda cwd: "local"
    got = pr_context.gh_json(["pr", "view", "7", "--json", "statusCheckRollup"])
    check("local-drops-actions", [c.get("name") for c in got["statusCheckRollup"]], ["Vercel"])
    # The findings check also comes as a check run made through the API: it
    # names no workflow, only itself.
    check("local-drops-findings-run", pr_context.without_actions(
        [{"name": pr_context.FINDINGS_CHECK, "workflowName": "", "conclusion": "FAILURE"}]), [])
    got = pr_context.gh_json(["api", "repos/o/r/commits/x/check-runs"])
    check("local-other-calls-untouched", len(got["statusCheckRollup"]), 3)
    pr_context.review_mode = lambda cwd: "github"
    got = pr_context.gh_json(["pr", "view", "7", "--json", "statusCheckRollup"])
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
