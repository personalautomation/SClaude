#!/usr/bin/env python3
#
# The figures of a review on this machine (`review: local`), which has no
# threads on the pull request to count:
#
#   * local_review_journal writes one line per run, its findings read back
#     from the headings of local-review.md;
#   * run_local_findings adds a run's findings and one round to the review
#     session told them, for its row in the issue;
#   * review_report.py reads the journal instead of the threads: a finding of
#     an earlier run not raised again is fixed, one near a declined line is
#     not, the last run's are open, and a later finding near a declined one
#     is a repeat.
#
# Run it with: python3 tests/local-review-report.py
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


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def run_bash(script, cwd):
    body = "set -uo pipefail\n"
    for name in ("io", "ui", "state", "project", "local_review"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += script
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True, text=True, timeout=60)
    return out.stdout, out.stderr, out.returncode


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


tmp = tempfile.mkdtemp()
try:
    wt = os.path.join(tmp, "wt")
    feature = os.path.join(wt, ".sclaude", "local", "feature")
    journal = os.path.join(feature, "local-review-rounds.jsonl")

    # --- the journal ------------------------------------------------------------
    write(os.path.join(feature, "local-review.md"),
          "## Local review of a..b — 2 finding(s)\n\n"
          "### src/a.ts:10 — null slips through\nWith x empty, y.\n\n"
          "### src/b.ts:3 — wrong order\nSorted after the cut.\n")
    run_bash('local_review_journal %s aaa bbb 2 42' % wt, wt)
    with open(journal) as fh:
        rows = [json.loads(l) for l in fh]
    check("journal-one-row", len(rows), 1)
    check("journal-findings", [(f["path"], f["line"]) for f in rows[0]["findings"]],
          [("src/a.ts", 10), ("src/b.ts", 3)])
    check("journal-figures", (rows[0]["base"], rows[0]["head"], rows[0]["count"],
                              rows[0]["seconds"]), ("aaa", "bbb", 2, 42))

    # --- the issue row ------------------------------------------------------------
    write(os.path.join(feature, "state.json"), json.dumps(
        {"steps": {"review": {"runs": [{"session": "s1", "rounds": 1}]}}}))
    run_bash('run_local_findings %s s1 2' % wt, wt)
    run_bash('run_local_findings %s s1 3' % wt, wt)
    run_bash('run_local_findings %s s1 ""' % wt, wt)
    with open(os.path.join(feature, "state.json")) as fh:
        run = json.load(fh)["steps"]["review"]["runs"][0]
    check("issue-comments", run.get("comments"), 5)
    check("issue-rounds", run.get("rounds"), 2)

    # --- the report ---------------------------------------------------------------
    def row(at, findings):
        return json.dumps({"at": at, "seconds": 300, "base": "x", "head": "y",
                           "count": len(findings),
                           "findings": [{"path": p, "line": l, "title": "t"} for p, l in findings]})

    write(journal, "\n".join([
        row("2026-10-15T10:00:00+00:00", [("src/a.ts", 10), ("src/b.ts", 3), ("src/c.ts", 50)]),
        row("2026-10-15T11:00:00+00:00", [("src/c.ts", 52)]),
        row("2026-10-15T12:00:00+00:00", [("src/d.ts", 1)]),
    ]) + "\n")
    write(os.path.join(feature, "local-review-declined"), "src/c.ts:50\tleave it\n")

    sys.path.insert(0, LIB)
    import review_report
    found, runs = review_report.local_rounds(wt)
    check("runs", len(runs), 3)
    fates = {(t["path"], t["line"]): t["fate"] for t in found}
    check("earlier-not-raised-is-fixed", fates[("src/a.ts", 10)], "fixed")
    check("declined-is-no-fix", fates[("src/c.ts", 50)], "no fix")
    check("near-declined-is-no-fix", fates[("src/c.ts", 52)], "no fix")
    check("last-run-is-open", fates[("src/d.ts", 1)], "open")
    review_report.rounds(found, runs)
    review_report.mark_repeats(found)
    check("repeat-after-decline",
          [t["repeat"] for t in found if (t["path"], t["line"]) == ("src/c.ts", 52)], [True])

    out = subprocess.run([sys.executable, os.path.join(LIB, "review_report.py"), wt, "7", ""],
                         capture_output=True, text=True).stdout
    check_true("report-says-local", "reviewed on this machine" in out)
    check_true("report-per-round", "oldest first: 3 1 1" in out)
    check_true("report-local-runs", "Local review: 3 runs" in out and "no Actions minutes" in out)

    os.remove(journal)
    check("no-journal", review_report.local_rounds(wt), (None, None))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
