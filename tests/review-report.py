#!/usr/bin/env python3
# The review report (sclaude/lib/review_report.py) and what feeds it: threads
# classified by what happened to them, rounds by the review that posted them,
# findings on earlier fixes, reversals, cost per launch (run_cost) and the
# trend line. gh is faked; nothing touches the network.
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import review_report  # noqa: E402

failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s: got %r, want %r" % (name, got, want))


URL = "https://github.com/o/r/pull/7#discussion_r%d"


def thread(n, review, at, path, line, resolved=False, fixed=False):
    comments = [{"body": "**Finding %d**" % n, "createdAt": at, "url": URL % n,
                 "pullRequestReview": {"databaseId": review, "submittedAt": at}}]
    if fixed:
        comments.append({"body": "Resolved automatically: fixed in abc1234.", "createdAt": at,
                         "url": URL % (n + 1000), "pullRequestReview": None})
    elif resolved:
        comments.append({"body": "Leaving it: the person decided so.", "createdAt": at,
                         "url": URL % (n + 1000), "pullRequestReview": None})
    return {"isResolved": resolved or fixed, "path": path, "line": line, "originalLine": line,
            "comments": {"nodes": comments}}


R1, R2, R3 = "2026-10-14T09:00:00Z", "2026-10-14T10:00:00Z", "2026-10-14T11:00:00Z"
NODES = [
    # Round 1: four findings, three fixed, one closed on the person's word.
    thread(1, 11, R1, "a.py", 10, fixed=True),
    thread(2, 11, R1, "a.py", 50, fixed=True),
    thread(3, 11, R1, "b.py", 5, fixed=True),
    thread(4, 11, R1, "c.py", 1, resolved=True),
    # Round 2: three, two of them on lines round 1 fixed.
    thread(5, 12, R2, "a.py", 12, fixed=True),
    thread(6, 12, R2, "b.py", 7, resolved=True),
    thread(7, 12, R2, "d.py", 100, fixed=True),
    # Round 3: three open, one of them left for the person, two on fixes.
    thread(8, 13, R3, "a.py", 14),
    thread(9, 13, R3, "a.py", 49),
    thread(10, 13, R3, "e.py", 3),
]


def fake_gh(args, cwd=None):
    if args[:2] == ["api", "graphql"]:
        return {"data": {"repository": {"pullRequest": {"reviewThreads": {
            "pageInfo": {"hasNextPage": False}, "nodes": NODES}}}}}
    if args[:2] == ["run", "list"]:
        return [{"workflowName": "Claude Code Review", "createdAt": R1, "updatedAt": "2026-10-14T09:10:00Z"},
                {"workflowName": "Claude Code Review", "createdAt": R2, "updatedAt": "2026-10-14T10:20:00Z"},
                {"workflowName": "Tests", "createdAt": R2, "updatedAt": "2026-10-14T11:00:00Z"}]
    return None


review_report.gh_json = fake_gh

with tempfile.TemporaryDirectory() as wt:
    feature = os.path.join(wt, ".sclaude/local/feature")
    os.makedirs(feature)
    state = os.path.join(feature, "state.json")
    with open(state, "w") as fh:
        json.dump({"feature": "x", "steps": {"review": {"runs": [
            {"session": "s1", "started": "2026-10-14T09:00:00+00:00",
             "finished": "2026-10-14T10:00:00+00:00", "outcome": "fixes confirmed", "rounds": 1},
            {"session": "s2", "started": "2026-10-14T10:00:00+00:00", "rounds": 2},
        ]}}}, fh)
    with open(os.path.join(feature, "review-yours"), "w") as fh:
        fh.write("%s\tleave it\n" % (URL % 10))
    with open(os.path.join(feature, "review-reversals"), "w") as fh:
        fh.write("%s\twould undo abc\n" % (URL % 9))
    log = os.path.join(wt, "review-context.log")
    with open(log, "w") as fh:
        fh.write("t\tx\ts1\tfresh session\t1\t1\t1\t1\t1\t4\t2\n")
        fh.write("t\tother\ts9\tdone\t1\t1\t1\t1\t1\t4\t5\n")

    # --- classification ------------------------------------------------------
    found = review_report.threads(wt, "7", "o/r")
    check("fates", [t["fate"] for t in found],
          ["fixed", "fixed", "fixed", "no fix", "fixed", "no fix", "fixed", "open", "open", "no fix"])
    review_report.mark_near_fixes(found)
    check("near-fixes", [t["near_fix"] for t in found],
          [False, False, False, False, True, True, False, True, True, False])
    check("rounds", [len(ts) for _, ts in review_report.rounds(found)], [4, 3, 3])
    check("reversals-of-this-feature-only", review_report.logged_reversals(log, "x"), 2)

    # --- cost per launch, from what the status line left ----------------------
    context = "/tmp/claude-statusline-context-s2"
    try:
        def launch(cost):
            with open(context, "w") as fh:
                json.dump({"used_percentage": 10, "context_window_size": 1000, "cost_usd": cost}, fh)
            subprocess.run(["bash", "-c", 'source "$1/state.sh"; source "$1/steps.sh"; run_cost "$2" s2',
                            "_", LIB, wt], check=True, timeout=30)
        launch(2.0)
        launch(3.5)   # a running total carried over a resume: 1.5 added
        launch(1.0)   # a total started again from zero: 1.0 added
    finally:
        os.remove(context)
    with open(state) as fh:
        runs = json.load(fh)["steps"]["review"]["runs"]
    check("costs-per-launch", runs[1].get("costs"), [2.0, 1.5, 1.0])
    check("other-session-untouched", "costs" in runs[0], False)

    # --- the printed report --------------------------------------------------
    sys.argv = ["review_report.py", wt, "7", "o/r", "feat", "x", log]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        review_report.main()
    text = out.getvalue()
    check("per-round", "Findings per round: 4 → 3 → 3" in text, True)
    check("closed-without-fix",
          "Fixed: 5 (50%). Closed without a fix: 3 (30%), 1 of them waiting for you" in text, True)
    check("acted-on", "Acted on in the last two rounds: 50% of what was settled." in text, True)
    check("back-and-forth",
          "Back and forth: 4 findings on lines an earlier round fixed; 3 declined" in text, True)
    check("hot-file", "a.py: findings in 3 rounds" in text, True)
    check("cost", "$4.50 (last round $1.00), $0.90 per fixed finding" in text, True)
    check("bot-runs", "Automatic review: 2 runs, 30m of runner time" in text, True)
    check("trend", "Converging slowly." in text, True)
    check("fixes-feed-the-review", "the fixes are feeding the review" in text, True)

# --- the verdict alone ---------------------------------------------------------
v = review_report.verdict
check("climbing", v([3, 4, 6], 0.9, 0, 6, 6).startswith("Not converging: findings per round are climbing"), True)
check("level", v([4, 4, 4], 0.9, 0, 4, 4).startswith("Not converging: findings per round hold level"), True)
check("converging", v([8, 6, 2, 1], 0.9, 0, 1, 0),
      "Converging: the last two rounds found half or less of the first two. Nothing is open.")
check("noise", "mostly asking for what nobody fixes" in v([2, 1, 1], 0.3, 0, 1, 1), True)
check("early", v([5], None, 0, 5, 5), "Too few rounds for a trend.")

# --- wiring --------------------------------------------------------------------
with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()
with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    BIN = fh.read()
check("printed-at-every-round-close", RUN.count('review_report "$wt" "$slug"'), 4)
check("cost-taken-at-session-end", '[[ "$step" == "review" ]] && run_cost "$wt" "$session"' in RUN, True)
check("command", 'review-report) shift; cmd_review_report "$(slugify "${1:-}")" ;;' in BIN, True)
with open(os.path.join(ROOT, "statusline.py")) as fh:
    check("statusline-leaves-the-cost", '"cost_usd": cost' in fh.read(), True)

if failed:
    sys.exit(1)
print("All checks passed.")
