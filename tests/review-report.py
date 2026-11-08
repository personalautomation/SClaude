#!/usr/bin/env python3
# The review report (sclaude/lib/review/review_report.py) and what feeds it: threads
# classified by what happened to them, rounds by the review that posted them,
# findings on earlier fixes, reversals, the cost in two parts (the review's
# passes, the fixing launches from run_cost) and the trend line. gh is faked; nothing touches the network.
#
# Rounds are review runs, never the review id of a comment: the review posts
# each inline comment as a review of its own, and grouping by that id once
# turned one pull request into 118 rounds of one finding each.
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
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
    # A round opens with its findings and goes on with their fix: each run
    # goes to the session that began after it (the first run also to one
    # begun before); session 2, untimed here, began after the second alone.
    check("fixers", review_report.fixers(groups, review_report.sessions(wt)), [[0], [1], [], []])

    # A run left without an end in the middle — a session that never started —
    # is not counted until now; only the last run can still be going.
    gap = tempfile.mkdtemp()
    os.makedirs(os.path.join(gap, ".sclaude/local/feature"))
    with open(os.path.join(gap, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump({"steps": {"review": {"runs": [
            {"session": "a", "started": "2026-10-14T08:00:00+00:00", "finished": "2026-10-14T08:10:00+00:00"},
            {"session": "b", "started": "2026-10-14T08:10:00+00:00"},
            {"session": "c", "started": "2026-10-14T08:20:00+00:00"},
        ]}}}, fh)
    spans = [s["seconds"] for s in review_report.sessions(gap)]
    check("an unended earlier run is not counted until now", spans[:2], [600.0, None])
    check("the last run still is", spans[2] is not None and spans[2] > 0, True)
    shutil.rmtree(gap, ignore_errors=True)

    # Stuck: not converging over enough rounds that one bad round is not it.
    check("stuck-over-enough-rounds", review_report.stuck([5, 5, 5, 5], "Not converging: hold level."), True)
    check("not-stuck-too-few", review_report.stuck([5, 5, 5], "Not converging: hold level."), False)
    check("not-stuck-converging", review_report.stuck([9, 5, 3, 1], "Converging: half."), False)
    said = "Converging: half. " + review_report.FEEDING
    check("stuck-when-fixes-feed-it-two-rounds", review_report.stuck([8, 6, 5, 3, 2], said, 2), True)
    check("not-stuck-feeding-one-round", review_report.stuck([6, 4, 2, 1], said, 1), False)
    check("not-stuck-feeding-too-few-rounds", review_report.stuck([8, 6, 5], said, 3), False)
    on, off = {"near_fix": True}, {"near_fix": False}
    check("feeding-streak-counts-back", review_report.feeding_streak(
        [{"threads": [on]}, {"threads": [off, off]}, {"threads": [on, off]}, {"threads": [on]}]), 2)
    check("feeding-streak-empty-round-breaks", review_report.feeding_streak(
        [{"threads": [on]}, {"threads": []}]), 0)

    # --- cost per launch, from what the status line left ----------------------
    context = "/tmp/claude-statusline-context-s2"
    try:
        def launch(cost):
            with open(context, "w") as fh:
                json.dump({"used_percentage": 10, "context_window_size": 1000, "cost_usd": cost}, fh)
            subprocess.run(["bash", "-c", 'source "$1/core/state.sh"; source "$1/core/steps.sh"; run_cost "$2" s2',
                            "_", LIB, wt], check=True, timeout=30)
        launch(2.0)
        launch(3.5)   # a running total carried over a resume: 1.5 added
        launch(1.0)   # a total started again from zero: 1.0 added
    finally:
        os.remove(context)
    with open(state) as fh:
        runs = json.load(fh)["steps"]["review"]["runs"]
    check("costs-per-launch", runs[1].get("costs"), [2.0, 1.5, 1.0])
    check("each-launch-timed", len(runs[1].get("cost_at") or []), 3)
    check("other-session-untouched", "costs" in runs[0], False)
    # The launches ran now, after this bench's review runs: the printed
    # report below has them begun on the runs' findings instead — one after
    # each of the runs at 09:58, 10:58 and 12:00 — and the session taken up
    # again after its end on the last, a launch whose cost is not in yet.
    with open(state) as fh:
        data = json.load(fh)
    data["steps"]["review"]["runs"][1].update(
        cost_at=["2026-10-14T10:30:00+00:00", "2026-10-14T11:10:00+00:00", "2026-10-14T12:05:00+00:00"],
        finished="2026-10-14T12:20:00+00:00", resumed="2026-10-14T12:30:00+00:00")
    with open(state, "w") as fh:
        json.dump(data, fh)

    # --- the printed report --------------------------------------------------
    sys.argv = ["review/review_report.py", wt, "7", "o/r", "feat"]
    out = io.StringIO()
    brief_file = os.path.join(wt, "brief.txt")
    os.environ[review_report.BRIEF_ENV] = brief_file
    try:
        with contextlib.redirect_stdout(out):
            review_report.main()
    finally:
        del os.environ[review_report.BRIEF_ENV]
    text = out.getvalue()
    with open(brief_file) as fh:
        brief = fh.read()
    # The phone's copy: where review stands, the newest session only.
    lines = brief.splitlines()
    # The phone hears the last finished round: the running one has said
    # nothing yet.
    check("brief-title", lines[0], "Review — PR 7, round 3, session 2.2")
    check("brief-is-the-last-finished-round", lines[1],
          "found 3 · on fixes 2 · repeats 1 · declined 1 · fixed 0 · waiting 2")
    # A row a round, read by the columns' widths: find, fix, result.
    widths = [int(re.sub(r"\D", "", f)) for _, f, _ in review_report.COLUMNS]

    def cells(line):
        out, at = [], 8
        for w in widths:
            out.append(line[at:at + w].strip())
            at += w + 1
        return out
    rows = {l[2:7].strip(): cells(l) for l in text.splitlines()
            if re.match(r"^  (\d+|total)\s", l)}
    check("a-row-per-round", sorted(rows), ["1", "2", "3", "4", "total"])
    check("heading-groups", [w for w in ("── find", "── fix", "── result") if w in text],
          ["── find", "── fix", "── result"])
    # The review's time and cost; the workflow's review is not priced, and
    # the run still going has not finished either.
    check("find", [rows[k][1:6] for k in "1234"],
          [["12m", "—", "4", "0", "0"], ["22m", "—", "3", "2", "1"],
           ["7m", "—", "3", "2", "1"], ["w", "w", "0", "0", "0"]])
    # Session 2 answered three runs: a label each, no row of its sum.
    check("fix-session", [rows[k][6] for k in "1234"], ["1", "2.1", "2.2", "2.3"])
    # A launch on the run it began after; the one running now has not
    # given its cost.
    check("fix-cost-per-launch", [rows[k][8] for k in "1234"], ["", "$2.00", "$1.50", "w"])
    check("fix-took-to-the-next-run", [rows[k][7] for k in "12"], ["1h28m", "28m"])
    check("result", [rows[k][9:] for k in "1234"],
          [["1", "3", "0"], ["1", "2", "0"], ["1", "0", "2"], ["w", "w", "w"]])
    # The total is where the review stands now: what is known so far, a row
    # still waiting left out — the run still going, the launch whose cost
    # is not taken yet.
    check("total", rows["total"][1:6] + rows["total"][8:],
          ["41m", "—", "10", "4", "2", "$3.50", "3", "5", "2"])
    check("total-fix-took-summed", rows["total"][7] not in ("", "w"), True)
    check("days", review_report.hours(3 * 86400 + 5 * 3600), "3d05h")
    # The cost in two parts. The review's: what could be priced, "—" when
    # nothing could (the workflow's review here), nothing without a run.
    check("review-cost-summed", review_report.review_cost([{"cost": 1.5}, {"cost": 0.25}]), "$1.75")
    check("review-cost-unknown", review_report.review_cost([{"cost": None}]), "—")
    check("review-cost-no-run", review_report.review_cost([]), "")
    # With the launches' times, a launch goes on the last run before it — the
    # run whose findings it fixed: one that pushed nothing (reopened) adds to
    # that run instead of shifting the rest.
    def t(hh):
        return review_report.parse("2026-10-14T%s:00+00:00" % hh)
    runs2 = [{"at": t("10:00"), "seconds": 300}, {"at": t("11:00"), "seconds": 300}]
    check("fixes-by-time", review_report.fixes_per_round(
        {"costs": [2.0, 0.5, 1.0, 0.25], "cost_at": [t("10:05"), t("10:20"), t("10:40"), t("11:30")]},
        runs2), [3.5, 0.25])
    # On GitHub a launch waits inside for the run of its own push and ends
    # after it; it began on the run before. One begun before every run goes
    # on the first.
    check("fixes-by-start-on-github", review_report.fixes_per_round(
        {"costs": [2.0, 1.0], "cost_at": [t("09:50"), t("10:30")]}, runs2), [3.0, None])
    # Untimed: one launch a run the session answered, the rest on its last.
    check("fixes-by-position-without-times", review_report.fixes_per_round(
        {"costs": [2.0, 1.0, 0.25], "cost_at": []}, runs2), [2.0, 1.25])
    check("fixes-by-position-on-its-runs", review_report.fixes_per_round(
        {"costs": [2.0], "cost_at": []}, runs2, [1]), [None, 2.0])
    # The shape of a local review: a pass, then a session fixing what it
    # found, then the next pass nobody has answered yet.
    s1 = {"start": t("10:10"), "end": t("10:50"), "going": False, "costs": [3.0],
          "cost_at": [t("10:10")]}
    check("fixers-local", review_report.fixers(runs2, [s1]), [[0], []])
    check("fix-took-local", review_report.fix_window(0, runs2, [s1], [0]), 2400.0)
    check("fix-cost-local", review_report.fixes_per_round(s1, runs2, [0]), [3.0, None])
    # Taken up again after its end, as session_runs leaves it (the old end
    # kept, `resumed` set): going, and its new launch answers the next run.
    back = tempfile.mkdtemp()
    os.makedirs(os.path.join(back, ".sclaude/local/feature"))
    with open(os.path.join(back, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump({"steps": {"review": {"runs": [
            {"session": "a", "started": "2026-10-14T10:10:00+00:00", "finished": "2026-10-14T10:50:00+00:00",
             "resumed": "2026-10-14T11:10:00+00:00", "costs": [3.0], "cost_at": ["2026-10-14T10:10:00+00:00"]},
        ]}}}, fh)
    resumed = review_report.sessions(back)
    check("resumed-is-going", resumed[0]["going"], True)
    # Its cost given, the launch has ended, though its end is written only
    # after the report the session's close prints.
    with open(os.path.join(back, ".sclaude/local/feature/state.json")) as fh:
        given = json.load(fh)
    given["steps"]["review"]["runs"][0].update(costs=[3.0, 0.5], cost_at=[
        "2026-10-14T10:10:00+00:00", "2026-10-14T11:10:00+00:00"])
    with open(os.path.join(back, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump(given, fh)
    check("cost-given-launch-ended", review_report.sessions(back)[0]["going"], False)
    check("resumed-answers-the-next-run", review_report.fixers(runs2, resumed), [[0], [0]])
    shutil.rmtree(back, ignore_errors=True)
    check("running-launch-on-its-run", [review_report.window(i, runs2, t("11:10")) for i in (0, 1)],
          [False, True])
    # A fix's time counts only launches in its window, not a later run's.
    runs3 = runs2 + [{"at": t("12:00"), "seconds": 300}]
    s3 = dict(s1, end=t("12:30"), costs=[1.0, 1.0], cost_at=[t("10:10"), t("12:10")])
    check("fix-took-in-its-window", review_report.fix_window(0, runs3, [s3], [0]), 3000.0)
    # On GitHub the launch waits inside for the run of its own push: that run
    # is not its fix, and found nothing to fix.
    waiting = {"start": t("10:05"), "end": t("10:45"), "going": False, "costs": [], "cost_at": []}
    check("waiting-launch-not-the-next-runs-fix",
          review_report.fixers([{"at": t("10:00")}, {"at": t("10:30")}], [waiting]), [[0], []])
    # On GitHub a launch that comes back red from `sclaude checks` may fix
    # that run's findings itself (review.md, "on your own fixes"), hand them
    # on, or have only a red CI check: the red counts as taken up only when
    # the same launch waits for checks again, and nothing is written on a
    # run that has ended.
    took = tempfile.mkdtemp()
    os.makedirs(os.path.join(took, ".sclaude/local/feature"))
    took_state = os.path.join(took, ".sclaude/local/feature/state.json")

    def took_up(run, *steps):
        with open(took_state, "w") as fh:
            json.dump({"steps": {"review": {"runs": [run]}}}, fh)
        for what in steps:
            subprocess.run(["bash", "-c", 'source "$1/core/state.sh"; source "$1/core/steps.sh"; run_took_up "$2" "$3"',
                            "_", LIB, took, what], check=True, timeout=30)
        with open(took_state) as fh:
            return len(json.load(fh)["steps"]["review"]["runs"][0].get("took_up") or [])
    going_run = {"session": "a", "started": "2026-10-14T10:05:00+00:00"}
    check("took-up-red-then-wait", took_up(dict(going_run), "wait", "red", "wait"), 1)
    check("took-up-not-on-a-red-handed-on", took_up(dict(going_run), "wait", "red"), 0)
    check("took-up-not-without-a-red", took_up(dict(going_run), "wait", "wait"), 0)
    check("took-up-not-after-the-end", took_up(dict(going_run, finished="2026-10-14T10:45:00+00:00"),
                                               "red", "wait"), 0)
    # Times from session_runs carry the local offset, the red's the UTC one:
    # read as moments, not as text.
    # Begun two minutes ago, written ten hours east: as text it sorts after
    # the red stamped now in UTC, as moments before it.
    east = datetime.timezone(datetime.timedelta(hours=10))
    begun = (datetime.datetime.now(east) - datetime.timedelta(minutes=2)).replace(microsecond=0).isoformat()
    check("took-up-across-offsets", took_up({"session": "a", "started": begun}, "red", "wait"), 1)
    check("took-up-not-with-an-outcome", took_up(dict(going_run, outcome="fixes confirmed"), "red", "wait"), 0)
    check("took-up-resumed", took_up(dict(going_run, finished="2026-10-14T10:45:00+00:00",
                                          resumed="2026-10-14T11:00:00+00:00"), "red", "wait"), 1)
    check("took-up-not-a-red-before-the-resume",
          took_up(dict(going_run, checks_red="2026-10-14T10:40:00+00:00",
                       resumed="2026-10-14T11:00:00+00:00", finished="2026-10-14T10:45:00+00:00"), "wait"), 0)
    shutil.rmtree(took, ignore_errors=True)
    # Read back, the run it took up is that launch's, and fixed while it goes.
    gh = [{"at": t("10:00")}, {"at": t("10:30")}, {"at": t("11:05")}]
    fixing = dict(waiting, start=t("10:40"), end=None, going=True, took_up=[t("11:20")])
    gh[2]["threads"] = [{"fate": "open"}]
    check("took-up-answers-its-run", review_report.fixers(gh, [fixing]), [[], [0], [0]])
    # A red on a run of nothing (a deployment check), fixed and waited on
    # again: no fix of that run.
    gh[2]["threads"] = []
    check("took-up-not-on-a-run-of-nothing", review_report.fixers(gh, [fixing]), [[], [0], []])
    # A run begun and not finished is not "no review run yet" on the phone.
    check("brief-first-run-going", review_report.brief(7, None, "", True).splitlines()[0],
          "Review — PR 7: the first review run is going.")
    review_report.COLOUR = True
    try:
        lit = review_report.row(("", "", "", 5, 0, 0, "", "", "w", 0, 2, 3), base=review_report.YELLOW, rnd="6")
    finally:
        review_report.COLOUR = False
    check("last-round-yellow-keeps-red-waiting-green-fixed-dim-w",
          ("\033[31m      3" in lit, "\033[32m    2" in lit, "\033[33m6" in lit, "\033[2m     w" in lit),
          (True, True, True, True))
    check_true = lambda name, ok: check(name, bool(ok), True)
    # Threads that could not be read give no status: its zeros would tell
    # the phone a review with open findings is clean.
    os.remove(brief_file)
    saved_threads = review_report.threads
    review_report.threads = lambda cwd, pr, repo: None
    os.environ[review_report.BRIEF_ENV] = brief_file
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            review_report.main()
    finally:
        del os.environ[review_report.BRIEF_ENV]
        review_report.threads = saved_threads
    check("brief-not-from-unread-threads", os.path.exists(brief_file), False)
    zeros = dict.fromkeys(review_report.BRIEF_ROWS, 0)
    check("brief-skips-a-round-still-running",
          review_report.newest([("round 1", zeros, False), ("round 2", zeros, True)])[0], "round 1")
    check("brief-nothing-finished", review_report.newest([("round 1", zeros, True)]), None)
    check_true("brief-verdict", "Converging slowly." in brief)
    # What was last shown — the open findings and the rounds — the same
    # again: nothing printed or sent.
    shown_file = os.path.join(wt, "shown.txt")
    os.environ[review_report.OPEN_ENV] = shown_file
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            review_report.main()
    finally:
        del os.environ[review_report.OPEN_ENV]
    with open(shown_file) as fh:
        shown = fh.read()
    check("shown-names-the-open-threads-and-rounds", shown.startswith("open:") and " rounds:" in shown and not shown.startswith("open: "), True)
    for unless, printed in ((shown, False), ("open:other", True)):
        os.environ[review_report.UNLESS_ENV] = unless
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                review_report.main()
        finally:
            del os.environ[review_report.UNLESS_ENV]
        check("unless-%s" % ("same" if not printed else "other"), bool(out.getvalue()), printed)
    check("still-running", "one review run still running" in text, True)
    check("closed-without-fix",
          "Fixed 5 of 10 (50%) · without a fix 3 (30%), 1 waiting for you to resolve on GitHub" in text, True)
    # The last round still has open findings: its decline is left out until
    # its fixes have had their chance (5 of 7, not 5 of 8).
    check("acted-on", "acted on 71% of the last 7" in text, True)
    # What the table shows already is not said again under it.
    check("table-not-repeated",
          [w for w in ("Back and forth", "Hot files", "Cost", "runner time") if w in text], [])
    check("no-colour-off-a-terminal", "\033[" in text, False)
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

# A minor thread a night session resolves itself (review.md, "At night"): the
# reply the prompt spells out counts as a decline, and its reason is the
# decision, so the next review is told not to raise it again.
NIGHT_MINOR = "Left as it is, minor \u2014 resolved at night without the author:"
PROMPT = open(os.path.join(ROOT, "sclaude", "prompts", "review.md"), encoding="utf-8").read()
check("night-minor-reply-in-prompt", ("`%s`" % NIGHT_MINOR) in PROMPT, True)
check("night-minor-declined", fate((NIGHT_MINOR + " style only.", "User")), "no fix")
import pr_context  # noqa: E402
check("night-minor-decision", pr_context.decline_of(
    [{"body": NIGHT_MINOR + " style only.", "author": {"__typename": "User"}}]), "style only.")

# The night check reads the thread fresh and takes it only when its one comment
# is a bot's or ends with the local review's signature: the prompt spells it.
check("night-check-names-local-signature", ("`%s`" % pr_context.LOCAL_SIGNATURE) in PROMPT, True)

# --- the verdict alone ---------------------------------------------------------
v = review_report.verdict
check("climbing", v([3, 4, 6], 0.9, 0, 6, 6).startswith("Not converging: findings per round are climbing"), True)
check("level", v([4, 4, 4], 0.9, 0, 4, 4).startswith("Not converging: findings per round hold level"), True)
check("converging", v([8, 6, 2, 1], 0.9, 0, 1, 0),
      "Converging: the last 2 rounds found half or less of the last 4's average. Nothing is open.")
# Rising again after a low: the first rounds' many findings do not hide it.
check("rising-after-a-low", v([8, 13, 8, 5, 2, 3, 1, 2, 5, 5], 0.9, 0, 5, 5)
      .startswith("Not converging: findings per round are climbing"), True)
check("noise", "mostly asking for what nobody fixes" in v([2, 1, 1], 0.3, 0, 1, 1), True)
check("early", v([5], None, 0, 5, 5), "Too few rounds for a trend.")

# --- wiring --------------------------------------------------------------------
RUN = "".join(open(os.path.join(LIB, m), encoding="utf-8").read()
          for m in ("cycle/run.sh", "review/review_round.sh", "review/review_gate.sh", "improve/friction.sh", "cycle/session_watch.sh"))
BIN = "".join(open(os.path.join(ROOT, _p)).read()
    for _p in ("bin/sclaude", "sclaude/lib/commands/start.sh", "sclaude/lib/commands/menu.sh", "sclaude/lib/commands/step_commands.sh", "sclaude/lib/commands/done.sh", "sclaude/lib/commands/feature_commands.sh"))
# Four for the rounds of the review on GitHub, two where the review on this
# machine ends a pass after a session (review_close_gate: something open, or
# nothing — the last table, its round of nothing included), and one where
# it finds something on the way into step 4, before the first session, and
# one where the gate finds what is open with no report on this head printed
# (review_close_gate).
check("printed-at-every-round-close",
      len(re.findall(r'review_report(?:_unshown)? "\$wt" "\$slug"', RUN)), 8)
check("checks-red-takes-up-the-round",
      ('run_took_up "$wt" wait' in RUN, '(( rc == 1 )) && run_took_up "$wt" red' in RUN), (True, True))
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
