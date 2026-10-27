#!/usr/bin/env python3
#
# A test bench for the DORA page (sclaude/lib/dora.py).
#
# The sources — Vercel, GitHub — are stood in for by their parsed answers: what
# is guarded here is the arithmetic on them, where a mistake does not look
# wrong on the page. A rollback's commits counted twice reads as a busy week;
# a cycle record from another product reads as one of ours; a rollback seen
# both on GitHub and in the record reads as two failures.
#
# Run it with: python3 tests/dora.py
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
import dora  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def ms(at):
    return int(at.timestamp() * 1000)


def git(repo, *args, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when.isoformat()
    return subprocess.run(["git", "-C", repo] + list(args), check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, name, at):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name, when=at)
    return git(repo, "rev-parse", "HEAD")


def deploy(uid, sha, at):
    return {"uid": uid, "url": uid + ".example", "sha": sha, "state": "READY",
            "created": ms(at), "ready": ms(at)}


def main():
    root = tempfile.mkdtemp()
    try:
        run_checks(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d failures" % len(failures) if failures else "ok")
    return 1 if failures else 0


def run_checks(root):
    # --- levels ---------------------------------------------------------------
    check("frequency: daily is elite", dora.level("frequency", 1.0), "Elite")
    check("frequency: twice a week is high", dora.level("frequency", 2 / 7), "High")
    check("frequency: twice a month is medium", dora.level("frequency", 2 / 30), "Medium")
    check("lead: 16 hours is elite", dora.level("lead", 16 * 3600), "Elite")
    check("lead: three days is high", dora.level("lead", 3 * dora.DAY), "High")
    check("failure: none is elite", dora.level("failure", 0.0), "Elite")
    check("failure: a fifth is low", dora.level("failure", 0.2), "Low")
    check("restore: unknown has no level", dora.level("restore", None), None)

    # The incident comment is found by what rollback_incident writes.
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "sclaude", "lib", "rollback.sh")) as fh:
        rollback = fh.read()
    check("rollback.sh writes the marker searched for",
          'ROLLBACK_MARKER="%s"' % dora.ROLLBACK_MARKER in rollback, True)
    check("rollback.sh writes the heading searched for",
          "## %s — " % dora.ROLLBACK_HEADING in rollback, True)

    # --- which commits each deploy shipped -------------------------------------
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    t0 = NOW - timedelta(days=10)
    a = commit(repo, "a", t0)
    b = commit(repo, "b", t0 + timedelta(hours=1))
    c = commit(repo, "c", t0 + timedelta(hours=2))
    d = commit(repo, "d", t0 + timedelta(days=2))
    deploys = [
        deploy("d1", a, t0 + timedelta(minutes=30)),
        deploy("d2", c, t0 + timedelta(hours=5)),
        # Rolled back to the first release by hand, then forward again: the
        # third deploy follows an older one and must not ship b and c anew.
        deploy("d3", a, t0 + timedelta(hours=6)),
        deploy("d4", d, t0 + timedelta(days=2, hours=3)),
        # A deploy of a commit this checkout has never seen is counted as a
        # deploy and ships no changes we can name.
        deploy("d5", "f" * 40, t0 + timedelta(days=3)),
    ]
    shipped = dora.commits_first_shipped(repo, deploys)
    check("the oldest deploy has no baseline", "d1" in shipped, False)
    check("a deploy ships what no earlier one had",
          sorted(s for s, _, _ in shipped["d2"]), sorted([b, c]))
    check("a deploy after a rollback ships nothing anew", shipped.get("d3"), [])
    check("the next deploy ships only its own", [s for s, _, _ in shipped["d4"]], [d])
    check("an unknown commit ships nothing", "d5" in shipped, False)

    # A squashed pull request's clock starts at its first commit, a commit on
    # main at its own author date.
    pulls = {"7": {"branch": "feat/7-thing", "merge": c,
                   "first": (t0 - timedelta(days=1)).isoformat(), "created": None, "merged": None}}
    changes = {(x["deploy"], x["sha"]): x for x in dora.changes(repo, deploys, pulls)}
    check("a pull request counts from its first commit",
          changes[("d2", c)]["seconds"], (timedelta(days=1, hours=5)).total_seconds())
    check("the pull request is named", changes[("d2", c)]["pr"], "7")
    check("a direct commit counts from its author date",
          changes[("d2", b)]["seconds"], 4 * 3600.0)

    # --- failures ---------------------------------------------------------------
    gh_found = [{"issue": 7, "at": (t0 + timedelta(hours=5, minutes=40)).isoformat()}]
    records = [
        # The same rollback, seen in the record twenty minutes later.
        {"rollback": {"at": (t0 + timedelta(hours=6)).isoformat()}},
        # A rollback GitHub does not know about.
        {"rollback": {"at": (t0 + timedelta(days=2, hours=4)).isoformat()}},
        {"feature": "plain"},
    ]
    rollbacks = dora.incidents(gh_found, records)
    check("one rollback seen twice is one incident", len(rollbacks), 2)
    failed = dora.failures(deploys, rollbacks)
    check("an incident falls on the deploy serving before it",
          [dep["uid"] for dep, _ in failed], ["d2", "d4"])

    m = dora.window_metrics(deploys, dora.changes(repo, deploys, pulls), failed,
                            NOW - timedelta(days=30), NOW)
    check("deploys in the window", m["deploys"], 5)
    check("failure rate is failed deploys over deploys", m["failure"], 2 / 5)
    check("restore is the median from deploy to rollback", m["restore"], (40 + 60) / 2 * 60)

    # Weeks before the first deploy are not weeks with no deploys.
    weeks = dora.weekly(deploys, [], NOW)
    check("the weeks start at the first deploy's", weeks[0][0], dora.week_start(dora.deploy_time(deploys[0])))
    check("every deploy lands in a week", sum(w[1] for w in weeks), 5)
    old = [deploy("x", a, NOW - timedelta(days=200))]
    check("a long history is cut to the last weeks", len(dora.weekly(old, [], NOW)), dora.WEEKS)

    # --- cycle records ----------------------------------------------------------
    log = os.path.join(root, "cycles.jsonl")
    lines = [
        {"feature": "7-thing", "repo": None, "pr": 7, "outcome": "done"},
        {"feature": "8-other", "repo": None, "pr": 7, "outcome": "done"},
        {"feature": "9-elsewhere", "repo": "/somewhere/else", "pr": 9, "outcome": "done"},
        {"feature": "10-ours", "repo": repo, "pr": 10, "outcome": "done"},
    ]
    with open(log, "w") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines) + "not json\n")
    saved = dora.log_path
    dora.log_path = lambda: log
    try:
        got = [r["feature"] for r in dora.cycles(repo, pulls)]
    finally:
        dora.log_path = saved
    check("a record is ours by its repo, or by a PR opened from its branch",
          got, ["7-thing", "10-ours"])

    parts = dora.cycle_parts({"steps": {"plan": {"seconds": 60}, "review": {"seconds": None}},
                              "regression": {"local": {"seconds": 5}, "prod": {"seconds": 7}}})
    check("a cycle is cut by step, the regression's stages together",
          parts, {"plan": 60, "code": 0, "pr": 0, "review": 0, "regression": 12})

    # --- the page ---------------------------------------------------------------
    data = {"deploys": deploys, "pulls": pulls, "incidents": gh_found,
            "records": [], "notes": ["Vercel could not be asked."], "github": "o/r"}
    page = dora.render(repo, data, dora.compute(repo, data, NOW))
    for label in ("Deployment frequency", "Lead time for changes",
                  "Change failure rate", "Time to restore"):
        check("the page shows " + label, label in page, True)
    check("the page says which source was missing", "Vercel could not be asked." in page, True)
    check("the page names the product", "o/r" in page, True)
    # Every figure on the page carries its note, and the guide colours it.
    import re as _re
    labels = _re.findall(r"<div class='tile[^']*'><div class=label>([^<]+)", page)
    notes = page.count("<div class=note hidden>")
    check("every tile has why, aim and how", notes, len(labels))
    check("a tile is coloured by DORA's level", "class='tile good'" in page, True)
    # The switch, and a figure that scales with a feature's size drawn both
    # ways, the switch showing one.
    check("the switch is on the page", "data-mode=norm" in page and "data-mode=abs" in page, True)
    check("a scaling figure is drawn absolute and per complexity",
          page.count("<div class=label>Feature cycle time <span class=scales"), 2)
    import metrics_guide
    check("lower is better", metrics_guide.judge("Hotfix rate", 0.05), "good")
    check("watch band", metrics_guide.judge("Hotfix rate", 0.15), "watch")
    check("higher is better", metrics_guide.judge("Cache hit rate", 0.5), "poor")
    check("a band between", metrics_guide.judge("Refactor work", 0.07), "watch")
    check("an unjudged figure has no colour", metrics_guide.judge("Sessions", 400), None)
    check("an unknown value has no colour", metrics_guide.judge("Hotfix rate", None), None)
    check("a label with its window finds its note", metrics_guide.lookup("Spend, last 30 days")
          is not None, True)

    # The review per feature: rounds are the review's runs, threads summed
    # over every pull request of the feature, and kept until one is added.
    import types
    fake = types.ModuleType("review_report")
    calls = []
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def fake_threads(cwd, pr, repo):
        calls.append(pr)
        return [{"created": t0 + timedelta(minutes=int(pr)), "fate": f}
                for f in (("fixed", "no fix") if pr == "1" else ("fixed", "open"))]
    fake.threads = fake_threads
    fake.review_runs = lambda cwd, branch: [{"start": t0, "running": False},
                                            {"start": t0 + timedelta(minutes=1), "running": False},
                                            {"start": t0 + timedelta(minutes=5), "running": False}]
    fake.rounds = lambda found, runs: [{} for _ in runs] or [{}]
    sys.modules["review_report"] = fake
    try:
        cache = os.path.join(root, "review-rounds.json")
        pulls_rr = {"1": {"branch": "feat/7-x"}, "2": {"branch": "feat/7-x"},
                    "3": {"branch": "feat/8-y"}}
        got = dora.gh_review_rounds(repo, "o/r", pulls_rr, {"7-x"}, cache)
        check("a feature's review over all its pull requests", got["7-x"],
              {"prs": ["1", "2"], "rounds": 3, "threads": 4, "fixed": 2, "declined": 1, "open": 1})
        check("an unfinished feature is not read", "8-y" in got, False)
        calls.clear()
        dora.gh_review_rounds(repo, "o/r", pulls_rr, {"7-x"}, cache)
        check("a feature already read is kept", calls, [])
        pulls_rr["4"] = {"branch": "feat/7-x"}
        dora.gh_review_rounds(repo, "o/r", pulls_rr, {"7-x"}, cache)
        check("a new pull request reads the feature again", sorted(calls), ["1", "2", "4"])
    finally:
        del sys.modules["review_report"]

    # The team part only where the product asks for generated teammates.
    check("no team part by default", "id=team" in page, False)
    os.makedirs(os.path.join(repo, ".sclaude"), exist_ok=True)
    with open(os.path.join(repo, ".sclaude", "config.json"), "w") as fh:
        json.dump({"metricsTeam": "demo"}, fh)
    demo = dora.render(repo, data, dora.compute(repo, data, NOW))
    check("metricsTeam demo adds the team part", "<div id=team></div>" in demo, True)
    team = json.loads(_re.search(r"<script type=application/json id=team-data>(.*?)</script>",
                                 demo, _re.S).group(1))
    check("the teammates and their profiles", (team["others"], sorted(team["metrics"][0]["profiles"])),
          (list(dora.SIMULATED), sorted(dora.SIMULATED)))
    check("the team is in the contents", "<a href='#team'>Team</a>" in demo, True)
    check("every figure of the table has its note",
          [m["key"] for m in team["metrics"] if not m.get("mix") and not m.get("note")], [])
    check("the team's own tiles and derived rows have notes",
          [k for k in ("team_features", "team_lines", "bus", "team_spend", "leverage", "merge_freq")
           if k not in team["notes"]], [])
    # This machine's own setting wins over the product's.
    os.makedirs(os.path.join(repo, ".sclaude", "local"), exist_ok=True)
    with open(os.path.join(repo, ".sclaude", "local", "config.json"), "w") as fh:
        json.dump({"metricsTeam": "real"}, fh)
    check("a machine's own metricsTeam wins", dora.team_mode(repo), "real")
    os.remove(os.path.join(repo, ".sclaude", "config.json"))
    with open(os.path.join(repo, ".sclaude", "local", "config.json"), "w") as fh:
        json.dump({"metricsTeam": "demo"}, fh)
    check("and works without the product's", dora.team_mode(repo), "demo")
    os.remove(os.path.join(repo, ".sclaude", "local", "config.json"))

    # The page has a table of contents, one entry per part, each linking to it.
    toc = _re.findall(r"<li><a href='#([^']+)'>", page)
    check("the contents name every part", sorted(toc),
          sorted(_re.findall(r"<section id='([^']+)'>", page)))
    check("the health radar is drawn both ways", page.count("aria-label='Health radar'"), 2)

    # The health of the whole: each direction the mean of its figures' scores
    # in the mode, the index their mean, the imbalance best less worst.
    speed = dora.axis("Speed", [("Hotfix rate", 0.05, 0.05), ("Hotfix rate", 0.15, 0.30),
                                ("Sessions", 1, 1), ("Hotfix rate", None, None)], "abs")
    check("a direction averages its scored figures", (speed[1], len(speed[2])), (87.5, 2))
    check("per complexity takes the normalised value",
          dora.axis("Speed", [("Hotfix rate", 0.05, 0.30)], "norm")[1], 0.0)
    index, spread, best, worst = dora.health_of([("A", 90.0, []), ("B", 30.0, []), ("C", None, [])])
    check("the index is the mean of the directions with a score", index, 60.0)
    check("the imbalance is best less worst", (spread, best[0], worst[0]), (60.0, "A", "B"))

    # Unclear requirements are relative to size: a question per criterion.
    sized = {"a": {"points": 10.0, "unit": 1.0}, "b": {"points": 4.0, "unit": 0.4}}
    figures = dora.requirement_figures(
        [{"feature": "a", "issue": 1}, {"feature": "b", "issue": 2}],
        {"1": {"significant": True, "changed": True, "added": 2, "change": 0.3,
               "request_words": 200, "description_words": 50},
         "2": {"significant": False, "changed": False, "added": 0, "change": 0.0,
               "request_words": 60, "description_words": 60}},
        [{"feature": "a", "step": "plan", "questions": 6}, {"feature": "b", "step": "plan", "questions": 5},
         {"feature": "b", "step": "code", "questions": 9}], sized)
    check("changed in development", (figures["significant"], figures["changed"]), (0.5, 0.5))
    check("a feature with a question per criterion or more is unclear", figures["unclear_n"], 1)
    check("only plan sessions' questions count", figures["questions"], 5.5)
    check("request growth over the description", figures["growth"], 2.5)

    empty = {"deploys": [], "pulls": {}, "incidents": [], "records": [], "notes": [], "github": None}
    page = dora.render(repo, empty, dora.compute(repo, empty, NOW))
    check("an empty history still draws", "No production deploy found." in page, True)

    # --- refreshing ---------------------------------------------------------------
    # The sources stood in for: no network in a bench.
    dora.vercel_deployments = lambda r: None
    dora.gh_name = lambda r: None
    dora.log_path = lambda: log
    os.environ.pop("SCLAUDE_DORA_EVERY", None)
    target = os.path.join(repo, dora.DIR, dora.PAGE)
    check("a missing page is built", dora.refresh(repo), True)
    check("it is where the proxy serves it from",
          os.path.isfile(os.path.join(repo, ".sclaude/local/dora/index.html")), True)
    check("a fresh page is left alone", dora.refresh(repo), False)
    check("force rebuilds a fresh page", dora.refresh(repo, force=True), True)
    os.environ["SCLAUDE_DORA_EVERY"] = "0"
    check("a page older than the interval is rebuilt", dora.refresh(repo), True)
    os.environ.pop("SCLAUDE_DORA_EVERY")
    check("a tree that is not a repository builds nothing",
          dora.refresh(os.path.join(root, "nothing"), force=True), False)

    # A second refresh while the first holds the lock leaves at once.
    import fcntl
    held = open(os.path.join(repo, dora.DIR, ".lock"), "w")
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        before = os.path.getmtime(target)
        result = []
        t = threading.Thread(target=lambda: result.append(dora.refresh(repo, force=True)))
        t.start()
        t.join(10)
        check("a refresh finds the lock taken and leaves", result, [False])
        check("the page was not touched", os.path.getmtime(target), before)
    finally:
        held.close()


if __name__ == "__main__":
    sys.exit(main())
