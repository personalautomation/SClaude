#!/usr/bin/env python3
#
# The review findings that reached no thread, carried into step 4's snapshot.
#
# The project's review job hands the code-review skill a commit range, and with
# that target the skill ignores --comment: the findings check goes red with "N
# review findings posted as a comment, not as threads" while nothing is posted.
# Once three review sessions in a row dug the findings out of the job log.
# pr_context.render() now reads them from that log itself.
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIB, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ctx = load("pr_context")
ctx.open_threads = lambda cwd, pr, repo: ([], [])

REPORT = ("Skill \"code-review\" completed (forked execution).\n\nResult:\n"
          "I found three low-severity items:\n\n- `a.mjs:262` shadowed `i`\n\n"
          "`--comment` was ignored: the target is a commit range, not a GitHub PR.")
# The shape of the real line: a timestamp, indentation, colour codes around it.
LOG = "\n".join([
    "2026-10-09T02:16:57.8891008Z \x1b[36;1m  \"type\": \"tool_result\",\x1b[0m",
    "2026-10-09T02:16:57.8891486Z         \"content\": %s," % json.dumps(REPORT),
    "2026-10-09T02:16:57.8891999Z   \"is_error\": false",
])
ROLLUP = [
    {"name": "Review — delta, whole PR once all fixed (Opus)", "workflowName": "Claude Code Review",
     "conclusion": "SUCCESS",
     "detailsUrl": "https://github.com/o/r/actions/runs/37873629772/job/113637089485"},
    {"name": ctx.FINDINGS_CHECK, "conclusion": "FAILURE"},
]
calls = []


def snapshot(title, comments=(), log=LOG, flag_known=True):
    def fake_json(args, cwd=None):
        if args[:2] == ["pr", "view"]:
            return {"statusCheckRollup": ROLLUP, "comments": list(comments),
                    "headRefOid": "abc"}
        return {"check_runs": [{"name": ctx.FINDINGS_CHECK, "output": {"title": title}}]}

    def fake_gh(args, cwd=None):
        calls.append(args)
        if "--allow-escape-sequences" in args and not flag_known:
            return None
        return log if args[-1].endswith("/jobs/113637089485/logs") else None
    ctx.gh_json = fake_json
    ctx.gh = fake_gh
    return ctx.render("/nonexistent", 160, "o/r")


snap = snapshot("3 review findings posted as a comment, not as threads")
check("section-shown", "### Review findings that reached no thread" in snap, True)
check("report-text-carried", "- `a.mjs:262` shadowed `i`" in snap, True)
check("preamble-dropped", "completed (forked execution)" in snap, False)
check("run-named", "37873629772" in snap, True)
check("log-asked-with-the-flag", "--allow-escape-sequences" in calls[0], True)

check("older-gh-without-the-flag",
      "shadowed" in snapshot("3 review findings posted as a comment, not as threads",
                             flag_known=False), True)
check("ordinary-title-no-section",
      "reached no thread" in snapshot("2 unresolved review findings in the whole PR"), False)
check("real-comment-no-section",
      "reached no thread" in snapshot(
          "3 review findings posted as a comment, not as threads",
          comments=[{"author": {"login": "claude"}, "body": "Findings: ..."}]), False)
check("no-result-in-log-no-section",
      "reached no thread" in snapshot("3 review findings posted as a comment, not as threads",
                                      log="nothing here"), False)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
