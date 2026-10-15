#!/usr/bin/env python3
# The review report (sclaude/lib/review_report.py) and what feeds it: threads
# classified by what happened to them, rounds by the review that posted them,
# findings on earlier fixes, reversals, cost per launch (run_cost) and the
# trend line. gh is faked; nothing touches the network.
#
# Rounds are review runs, never the review id of a comment: the review posts
# each inline comment as a review of its own, and grouping by that id once
# turned one pull request into 118 rounds of one finding each.
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


BASE = 4264149000


def URL(n):
    return "https://github.com/o/r/pull/7#discussion_r%d" % (BASE + n)


def thread(n, at, path, line, resolved=False, fixed=False,
           reply="Left as it is, at the author's decision: the person decided so."):
    # Every comment a review of its own, as the real review posts them.
    comments = [{"body": "**Finding %d**" % n, "createdAt": at, "url": URL(n)}]
    if fixed:
        comments.append({"body": "Resolved automatically: fixed in abc1234.", "createdAt": at,
                         "url": URL(n + 1000)})
    elif resolved:
        comments.append({"body": reply, "createdAt": at, "url": URL(n + 1000)})
    return {"isResolved": resolved or fixed, "path": path, "line": line, "originalLine": line,
            "comments": {"nodes": comments}}


R1, R2, R3 = "2026-10-14T09:00:00Z", "2026-10-14T10:00:00Z", "2026-10-14T11:00:00Z"
NODES = [
    # Round 1: four findings, three fixed, one closed on the person's word.
    thread(1, R1, "a.py", 10, fixed=True),
    thread(2, R1, "a.py", 50, fixed=True),
    thread(3, R1, "b.py", 5, fixed=True),
    thread(4, R1, "c.py", 1, resolved=True),
    # Round 2: three, two of them on lines round 1 fixed; one declined again
    # with a reply that cites the decline in round 1.
    thread(5, R2, "a.py", 12, fixed=True),
    thread(6, R2, "b.py", 7, resolved=True, reply="Left as it is: as on r%d." % (BASE + 4)),
    thread(7, R2, "d.py", 100, fixed=True),
    # Round 3: three open, one of them left for the person, two on fixes; the
    # one left sits next to the decline of round 1.
    thread(8, R3, "a.py", 14),
    thread(9, R3, "a.py", 49),
    thread(10, R3, "c.py", 3),
]
RUN = {"workflowName": "Claude Code Review", "status": "completed"}
RUNS = [
    dict(RUN, createdAt="2026-10-14T08:58:00Z", updatedAt="2026-10-14T09:10:00Z"),
    dict(RUN, createdAt="2026-10-14T09:58:00Z", updatedAt="2026-10-14T10:20:00Z"),
    dict(RUN, createdAt="2026-10-14T10:58:00Z", updatedAt="2026-10-14T11:05:00Z"),
    # Refused on workflow validation in seconds: reviewed nothing.
    dict(RUN, createdAt="2026-10-14T11:30:00Z", updatedAt="2026-10-14T11:30:10Z"),
    # Still running: not in the trend yet.
    dict(RUN, createdAt="2026-10-14T12:00:00Z", updatedAt="2026-10-14T12:00:00Z", status="in_progress"),
    {"workflowName": "Claude on @mention", "status": "completed",
     "createdAt": R2, "updatedAt": "2026-10-14T10:05:00Z"},
    {"workflowName": "Tests", "status": "completed", "createdAt": R2, "updatedAt": "2026-10-14T11:00:00Z"},
]


def fake_gh(args, cwd=None):
    if args[:2] == ["api", "graphql"]:
        return {"data": {"repository": {"pullRequest": {"reviewThreads": {
            "pageInfo": {"hasNextPage": False}, "nodes": NODES}}}}}
    if args[:2] == ["run", "list"]:
        return RUNS
    return None


review_report.gh_json = fake_gh

with tempfile.TemporaryDirectory() as wt:
    feature = os.path.join(wt, ".sclaude/local/feature")
    os.makedirs(feature)
    state = os.path.join(feature, "state.json")
    with open(state, "w") as fh:
        json.dump({"feature": "x", "steps": {"review": {"runs": [
            {"session": "s1", "started": "2026-10-14T08:30:00+00:00",
             "finished": "2026-10-14T10:30:00+00:00", "outcome": "fixes confirmed", "rounds": 1},
            {"session": "s2", "started": "2026-10-14T10:30:00+00:00", "rounds": 2},
        ]}}}, fh)
    with open(os.path.join(feature, "review-yours"), "w") as fh:
        fh.write("%s\tleave it\n" % URL(10))
    with open(os.path.join(feature, "review-reversals"), "w") as fh:
        fh.write("%s\twould undo abc\n" % URL(9))
    log = os.path.join(wt, "review-context.log")
    with open(log, "w") as fh:
        fh.write("t\tx\ts1\tfresh session\t1\t1\t1\t1\t1\t4\t2\n")
        fh.write("t\tother\ts9\tdone\t1\t1\t1\t1\t1\t4\t5\n")

    # --- classification ------------------------------------------------------
    found = review_report.threads(wt, "7", "o/r")
    check("fates", [t["fate"] for t in found],
          ["fixed", "fixed", "fixed", "no fix", "fixed", "no fix", "fixed", "open", "open", "no fix"])
    check("rounds-without-runs", [len(g["threads"]) for g in review_report.rounds(found, None)],
          [4, 3, 3])
    runs = review_report.review_runs(wt, "feat")
    check("runs-of-the-review-only", [(r["seconds"], r["running"]) for r in runs],
          [(720.0, False), (1320.0, False), (420.0, False), (0.0, True)])
    groups = review_report.rounds(found, runs)
    check("rounds-by-run", [len(g["threads"]) for g in groups], [4, 3, 3, 0])
    review_report.mark_near_fixes(found)
    check("near-fixes", [t["near_fix"] for t in found],
          [False, False, False, False, True, True, False, True, True, False])
    review_report.mark_repeats(found)
    check("repeats", [t["repeat"] for t in found],
          [False, False, False, False, False, True, False, False, False, True])
    check("cites", [t["cites_declined"] for t in found],
          [False, False, False, False, False, True, False, False, False, False])
    check("by-session", [(label, len(gs)) for label, _, gs in
                         review_report.by_session(groups, review_report.sessions(wt))],
          [("1", 2), ("2", 2)])
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
    check("per-run", "Findings per review run, oldest first: 4 3 3 (one more still running)" in text, True)
    check("closed-without-fix",
          "Fixed: 5 (50%). Closed without a fix: 3 (30%), 1 of them waiting for you" in text, True)
    check("acted-on", "Acted on, of the last 8 settled findings: 62%." in text, True)
    check("raised-again",
          "Raised again after a decline: 2 findings (2 declined again, 1 citing the earlier thread)."
          in text, True)
    check("back-and-forth",
          "Back and forth: 4 findings on lines an earlier round fixed; 3 declined" in text, True)
    check("hot-file", "a.py: findings in 3 of 4 rounds" in text, True)
    check("cost", "Cost: $4.50 over 1 of 2 sessions, last launch $1.00." in text, True)
    check("bot-runs", "Automatic review: 4 runs, 41m of runner time." in text, True)
    # Session 1: the runs at 08:58 and 09:58 — seven findings, five fixed,
    # two declined, two on fixes, one raised again after a decline.
    row = [l.split() for l in text.splitlines() if l.split()[:1] == ["1"]]
    check("session-row", row and row[0][-7:], ["2", "7", "5", "2", "0", "2", "1"])
    check("trend", "Converging slowly." in text, True)
    check("fixes-feed-the-review", "the fixes are feeding the review" in text, True)

# --- the fate of a resolved thread: the last decision reply decides ---------------
def fate(*replies):
    """A resolved thread's fate, each reply (body, author type)."""
    comments = [{"body": "**F**", "createdAt": R1, "url": URL(500)}] + [
        {"body": b, "author": {"__typename": kind}, "createdAt": R1, "url": URL(600 + i)}
        for i, (b, kind) in enumerate(replies)]
    saved = review_report.gh_json
    review_report.gh_json = lambda args, cwd=None: {"data": {"repository": {"pullRequest": {
        "reviewThreads": {"pageInfo": {"hasNextPage": False}, "nodes": [
            {"isResolved": True, "path": "x.py", "line": 1, "comments": {"nodes": comments}}]}}}}}
    try:
        with tempfile.TemporaryDirectory() as wt:
            return review_report.threads(wt, "7", "o/r")[0]["fate"]
    finally:
        review_report.gh_json = saved


AUTO = ("Resolved automatically: fixed in abc1234. x", "Bot")
LEFT = ("Left as it is, at the author's decision: no.", "User")
check("resolved-without-reply", fate(), "fixed")
check("resolved-with-chatter", fate(("Fixed in abc, thanks.", "User")), "fixed")
check("declined", fate(LEFT), "no fix")
check("declined-then-chatter", fate(LEFT, ("I disagree.", "User")), "no fix")
check("auto-resolved-reopened-declined", fate(AUTO, LEFT), "no fix")
check("declined-reopened-fixed", fate(LEFT, AUTO), "fixed")
check("decline-from-a-bot", fate(("Left as it is, says a bot.", "Bot")), "fixed")
check("decline-indented", fate(("  Left as it is: no.", "User")), "no fix")

# --- the verdict alone ---------------------------------------------------------
v = review_report.verdict
check("climbing", v([3, 4, 6], 0.9, 0, 6, 6).startswith("Not converging: findings per round are climbing"), True)
check("level", v([4, 4, 4], 0.9, 0, 4, 4).startswith("Not converging: findings per round hold level"), True)
check("converging", v([8, 6, 2, 1], 0.9, 0, 1, 0),
      "Converging: the last rounds found half or less of the first. Nothing is open.")
check("noise", "mostly asking for what nobody fixes" in v([2, 1, 1], 0.3, 0, 1, 1), True)
check("early", v([5], None, 0, 5, 5), "Too few rounds for a trend.")

# --- wiring --------------------------------------------------------------------
with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()
with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    BIN = fh.read()
# Four for the rounds of the review on GitHub, and one more where the review
# on this machine finds something after a session (review_close_gate).
check("printed-at-every-round-close", RUN.count('review_report "$wt" "$slug"'), 5)
check("cost-taken-at-session-end", '[[ "$step" == "review" ]] && run_cost "$wt" "$session"' in RUN, True)
with open(os.path.join(ROOT, "sclaude", "prompts", "review.md")) as fh:
    check("prompt-cites-declines", "`as on r<id>`" in fh.read(), True)
check("cite-read", review_report.CITED.findall("Left as it is: as on r4264149143 and r4264974786."),
      ["4264149143", "4264974786"])
check("command", 'review-report) shift; cmd_review_report "$(slugify "${1:-}")" ;;' in BIN, True)
with open(os.path.join(ROOT, "statusline.py")) as fh:
    check("statusline-leaves-the-cost", '"cost_usd": cost' in fh.read(), True)

if failed:
    sys.exit(1)
print("All checks passed.")
