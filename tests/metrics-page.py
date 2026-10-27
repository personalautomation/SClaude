#!/usr/bin/env python3
#
# A test bench for what the metrics page counts beyond DORA: Claude's
# sessions from its transcripts (sclaude/lib/claude_usage.py), and the quality
# of the work from sclaude's own records (sclaude/lib/dev_quality.py).
#
# The transcripts are written here in Claude Code's shape, cut down to the
# lines that are read. What is guarded is the counting: a cumulative cost
# record taken once rather than summed, a tool call logged twice counted once,
# a feature whose name starts like a step not taken for one.
#
# Run it with: python3 tests/metrics-page.py
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
import claude_usage  # noqa: E402
import dev_quality  # noqa: E402
import metrics_extra as mx  # noqa: E402
from issue_comments import AC_CLOSE, AC_OPEN, REQUEST  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def compact(entry):
    """A line as Claude Code writes it: no spaces after separators, which the
    scan's byte matches rely on."""
    return json.dumps(entry, separators=(",", ":"), ensure_ascii=False)


def write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("".join(compact(x) + "\n" for x in lines))


def assistant(msg_id, tools=(), usage=None, ts="2026-10-20T10:00:00Z"):
    content = [{"type": "tool_use", "id": t[0], "name": t[1], "input": {}} for t in tools]
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": msg_id, "model": "m", "content": content,
                        "usage": usage or {"input_tokens": 1, "output_tokens": 2}}}


def cost_state(start, cost, out):
    return {"type": "cost-state", "startTime": start, "totalCostUSD": cost,
            "totalLinesAdded": 10, "totalLinesRemoved": 1, "totalAPIDuration": 100,
            "totalToolDuration": 50,
            "modelUsage": {"m": {"inputTokens": 5, "outputTokens": out, "thinkingTokens": 3,
                                 "cacheReadInputTokens": 90, "cacheCreationInputTokens": 5,
                                 "costUSD": cost}}}


def main():
    root = tempfile.mkdtemp()
    try:
        usage_checks(root)
        quality_checks(root)
        extra_checks(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d failures" % len(failures) if failures else "ok")
    return 1 if failures else 0


def usage_checks(root):
    # --- the step a session ran -------------------------------------------------
    for title, want in [
        ("2-code 💻/12-price-field", "code"),
        ("4-friction(23) 🧱/12-price-field", "friction"),
        ("2-fix-local(2) 🔧/12-price-field", "fix"),
        ("2-fix-local-friction(2) 🧱/12-price-field", "friction"),
        ("4-2-review/13-icons", "review"),
        # The feature's own name starts with a number and a step's word.
        ("14-review-the-menu/plan", "plan"),
        ("15-fix-the-layout/code", "code"),
        ("retro/16-pages", "retro"),
        (None, "manual"),
        ("something else", "other"),
    ]:
        check("step of %r" % title, claude_usage.step_of(title), want)

    # --- one transcript -----------------------------------------------------------
    projects = os.path.join(root, "projects")
    repo = os.path.join(root, "home", "prod")
    base = claude_usage.project_name(repo)
    # Every character but a letter or a digit becomes a dash: a temporary
    # directory's underscore too.
    check("a project is named the way Claude Code names it",
          claude_usage.project_name("/tmp/a_b.c/d"), "-tmp-a-b-c-d")
    main_session = os.path.join(projects, base + "-7-thing", "s1.jsonl")
    write(main_session, [
        {"type": "custom-title", "customTitle": "2-code 💻/7-thing"},
        assistant("a", tools=[("t1", "Bash"), ("t2", "Read")]),
        # The same message logged again, as Claude Code does per block.
        assistant("a", tools=[("t1", "Bash"), ("t2", "Read")]),
        assistant("b", tools=[("t3", "mcp__srv__click")], ts="2026-10-20T11:00:00Z"),
        cost_state(1, 1.0, 100),
        # Cumulative: the run's last record is its total.
        cost_state(1, 2.5, 300),
        # Resumed: a second run in the same file adds its own.
        cost_state(2, 0.5, 50),
        {"type": "user", "toolDenialKind": "permission-rule"},
        {"type": "user", "isCompactSummary": True},
        # Typed by the person; a tool's result, a meta line and a
        # notification are not.
        {"type": "user", "promptSource": "typed", "message": {"content": "go"}},
        {"type": "user", "message": {"content": "an older Claude Code's typed line"}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
        {"type": "user", "isMeta": True, "message": {"content": "skill text"}},
        {"type": "user", "promptSource": "system", "message": {"content": "<task-notification>"}},
    ])
    sub = os.path.join(projects, base + "-7-thing", "s1", "subagents", "agent-x.jsonl")
    write(sub, [assistant("c", tools=[("t9", "Grep")],
                          usage={"input_tokens": 4, "output_tokens": 6,
                                 "cache_read_input_tokens": 10})])
    write(os.path.join(projects, base, "s2.jsonl"), [assistant("d")])
    # Another product whose path only starts like this one's.
    write(os.path.join(projects, base + "x", "s3.jsonl"), [assistant("e")])
    write(os.path.join(projects, base + "-7-thing--sclaude-local-instruments", "s4.jsonl"),
          [assistant("f")])

    cache = os.path.join(root, "sessions.json")
    found = {(s["feature"], s["session"], s["sub"]): s
             for s in claude_usage.sessions(repo, cache, root=projects)}
    s1 = found[("7-thing", "s1", False)]
    check("each run's last cost record, summed over runs", s1["cost"], 3.0)
    check("tokens from the cost record", s1["tokens"]["output"], 350)
    check("a tool call logged twice counts once", s1["tools"], {"Bash": 1, "Read": 1, "mcp__srv__click": 1})
    check("the step from the session's name", s1["step"], "code")
    check("refusals by kind", s1["denials"], {"permission-rule": 1})
    check("compactions", s1["compactions"], 1)
    check("messages the person typed", s1["prompts"], 2)
    # The person's turns: each typed message after Claude's turn, with how
    # long they took and Claude's calls before it.
    check("the person's turns", [(t[1], t[2]) for t in s1["human"]], [(0, 3), (0, 0)])

    # Waits, and an answer to Claude's question.
    asked = os.path.join(projects, base + "-7-thing", "s5.jsonl")
    write(asked, [
        {"type": "user", "promptSource": "typed", "timestamp": "2026-10-20T10:00:00Z",
         "message": {"content": "sclaude's opening prompt"}},
        {"type": "assistant", "timestamp": "2026-10-20T10:01:00Z",
         "message": {"id": "m1", "content": [
             {"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
              "input": {"questions": [{"question": "a"}, {"question": "b"}]}}]}},
        {"type": "user", "timestamp": "2026-10-20T10:03:00Z",
         "message": {"content": [{"type": "tool_result", "tool_use_id": "q1", "content": "x"}]}},
        {"type": "assistant", "timestamp": "2026-10-20T10:04:00Z",
         "message": {"id": "m2", "content": [{"type": "tool_use", "id": "t7", "name": "Bash", "input": {}}]}},
        {"type": "user", "promptSource": "typed", "timestamp": "2026-10-20T12:00:00Z",
         "message": {"content": "back after lunch"}},
    ])
    found5 = [x for x in claude_usage.sessions(repo, cache, root=projects) if x["session"] == "s5"][0]
    check("each question of a call counts", found5["questions"], 2)
    check("an answer to Claude's question is a turn, timed from the question",
          (found5["human"][0][1], found5["human"][0][2]), (120, 1))
    check("a wait past the cap counts as the cap", found5["human"][1][1], claude_usage.AWAY)
    check("the opening prompt is no turn", len(found5["human"]), 2)
    check("first and last timestamps", (s1["start"], s1["end"]),
          ("2026-10-20T10:00:00Z", "2026-10-20T11:00:00Z"))
    agent = found[("7-thing", "s1", True)]
    check("a subagent belongs to its session", agent["session"], "s1")
    check("a subagent has no cost of its own", agent["cost"], None)
    check("a subagent's tokens come from its messages", agent["tokens"]["cache_read"], 10)
    check("the main checkout's sessions are main's", ("main", "s2", False) in found, True)
    check("another product's sessions are left out",
          any(s["session"] == "s3" for s in found.values()), False)
    check("a workshop's session is the workshop's",
          found[("7-thing", "s4", False)]["step"], "workshop")

    # A transcript that did not change is not read again.
    with open(cache) as fh:
        kept = json.load(fh)
    rel = os.path.relpath(main_session, projects)
    kept[rel]["summary"]["cost"] = 99.0
    with open(cache, "w") as fh:
        json.dump(kept, fh)
    again = {(s["feature"], s["session"], s["sub"]): s
             for s in claude_usage.sessions(repo, cache, root=projects)}
    check("an unchanged transcript comes from the cache", again[("7-thing", "s1", False)]["cost"], 99.0)
    with open(main_session, "a") as fh:
        fh.write(compact(cost_state(3, 1.0, 10)) + "\n")
    again = {(s["feature"], s["session"], s["sub"]): s
             for s in claude_usage.sessions(repo, cache, root=projects)}
    check("a grown transcript is read again", again[("7-thing", "s1", False)]["cost"], 4.0)


def quality_checks(root):
    records = [
        {"outcome": "done",
         "steps": {"code": {"friction": {"empty": False, "fixed": True, "verdict": "lifted"}},
                   "review": {"friction": {"empty": True}}},
         "regression": {"local": {"status": "passed", "fixes": []},
                        "preview": {"status": "passed",
                                    "fixes": [{"status": "red"}, {"status": "green"}]}}},
        {"outcome": "done",
         "steps": {"plan": {"friction": {"empty": False, "fixed": False, "verdict": "deliberate"}}},
         "regression": {"local": {"status": "passed", "fixes": [{"status": "green"}]}}},
    ]
    reg = dev_quality.regression(records)
    check("local: two runs, one green first time", (reg["local"]["runs"], reg["local"]["first_pass"]), (2, 1))
    check("preview: a fixed stage did not pass first time", reg["preview"]["first_pass"], 0)
    check("fixing sessions and the red ones", (reg["preview"]["fixes"], reg["preview"]["red_fixes"]), (2, 1))
    check("a stage never run is no run", reg["prod"]["runs"], 0)
    fr = dev_quality.friction(records)
    check("an empty friction log is no review", fr["reviews"], 2)
    check("verdicts", fr["verdicts"], {"lifted": 1, "deliberate": 1})
    check("reviews that changed the rules", fr["fixed"], 1)

    repo = os.path.join(root, "repo")
    os.makedirs(os.path.join(repo, ".sclaude", "local"))
    os.makedirs(os.path.join(repo, ".sclaude", "team", "deferred"))
    with open(os.path.join(repo, ".sclaude", "team", "deferred", "7.tsv"), "w") as fh:
        fh.write("a\tb\n\nc\td\n")
    check("deferred entries, blank lines aside", dev_quality.deferred(repo), 2)
    with open(os.path.join(repo, dev_quality.REVIEW_LOG), "w") as fh:
        fh.write("t\tf\ts1\tcarried on\t1\t1\t1\t1\t1\t18\t0\n"
                 "t\tf\ts1\tdone\t1\t1\t1\t1\t0\t5\t2\n"
                 "t\tg\ts2\texit\t-\t-\t-\t-\t-\t-\t1\n"
                 "short line\n")
    check("the review log: a row a round, counts added up", dev_quality.review_log(repo),
          {"sessions": 2, "rounds": 3, "comments": 23, "reversals": 3,
           "door": 1, "end_pct": 0.01})

    # The criteria, from a stand-in for gh.
    bin_dir = os.path.join(root, "bin")
    os.makedirs(bin_dir)
    body = "## Acceptance criteria\n\n%s\n- [x] one\n- [ ] two\n- [X] three\n%s\n" % (AC_OPEN, AC_CLOSE)
    with open(os.path.join(bin_dir, "gh"), "w") as fh:
        fh.write("#!/bin/sh\ncat <<'EOF'\n%s\nEOF\n" % body)
    os.chmod(os.path.join(bin_dir, "gh"), 0o755)
    path = os.environ["PATH"]
    os.environ["PATH"] = bin_dir + os.pathsep + path
    try:
        cache = os.path.join(root, "acceptance.json")
        check("criteria ticked and in all", dev_quality.acceptance(repo, "o/r", [7], cache), {"7": [2, 3]})
    finally:
        os.environ["PATH"] = path
    check("an issue's criteria are kept", dev_quality.acceptance(repo, "o/r", [7], cache), {"7": [2, 3]})

    # How the requirements moved after the plan was approved: the criteria
    # comment's creation is the start, every body is read version by version,
    # and QA's ticks are no change.
    def edits(*pairs):
        return {"userContentEdits": {"nodes": [{"editedAt": t, "diff": d} for t, d in pairs]}}
    ac_v1 = "%s\n- [ ] AC1. one\n- [ ] AC2. two\n%s" % (AC_OPEN, AC_CLOSE)
    ac_ticked = ac_v1.replace("[ ]", "[x]")
    request_v1 = "%s\n## User request\n\nBuild the thing." % REQUEST
    request_v2 = request_v1 + "\n\n%s\n\n- one more\n- and another" % dev_quality.ADDED_HEADING
    issue = {"body": "Build a thing, please, with words.",
             "comments": {"nodes": [
                 dict({"createdAt": "2026-10-01T10:00:00Z", "body": request_v2},
                      **edits(("2026-10-01T10:00:00Z", request_v1), ("2026-10-02T10:00:00Z", request_v2))),
                 dict({"createdAt": "2026-10-01T12:00:00Z", "body": ac_ticked},
                      **edits(("2026-10-01T12:00:00Z", ac_v1), ("2026-10-03T10:00:00Z", ac_ticked)))]}}
    moves = dev_quality.requirement_moves(issue)
    check("development starts when the criteria are posted", moves["start"], "2026-10-01T12:00:00Z")
    check("requirements added in development", moves["added"], 2)
    check("two added in development is significant", moves["significant"], True)
    check("ticks alone change no criterion", moves["criteria"], [2, 2])
    ticks_only = dict(issue, comments={"nodes": [issue["comments"]["nodes"][1]]})
    check("ticks alone are no change", dev_quality.requirement_moves(ticks_only)["changed"], False)
    check("no criteria comment, no start", dev_quality.requirement_moves({"body": "x", "comments": {"nodes": []}}),
          None)
    grown = dict(issue, comments={"nodes": [issue["comments"]["nodes"][1] | edits(
        ("2026-10-01T12:00:00Z", ac_v1),
        ("2026-10-04T10:00:00Z", ac_v1.replace(AC_CLOSE, "- [ ] AC3. three\n" + AC_CLOSE)))]})
    check("a criterion added after the start is significant",
          (dev_quality.requirement_moves(grown)["criteria"], dev_quality.requirement_moves(grown)["significant"]),
          ([2, 3], True))

    # main's history.
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def commit(path, text, message):
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text)
        subprocess.run(["git", "-C", repo, "add", path], check=True, env=env)
        subprocess.run(["git", "-C", repo, "commit", "-qm", message], check=True, env=env)

    subprocess.run(["git", "-C", repo, "init", "-qb", "main"], check=True, env=env)
    commit("src/a.py", "1\n2\n", "feat: a\n\nbody\n\nSclaude-Session: abc")
    commit("tests/a_test.py", "1\n", "test: a\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>")
    commit("db/migrations/001.sql", "x\n", "feat: schema")
    commit("src/a.py", "1\n", 'Revert "feat: a"')
    hist = dev_quality.history(repo, datetime.now(timezone.utc) - timedelta(days=1))
    check("commits", hist["commits"], 4)
    check("commits a Claude session signed", hist["by_claude"], 2)
    check("reverts", hist["reverts"], 1)
    check("lines in tests", (hist["test_added"], hist["added"]), (1, 4))
    check("migrations added", hist["migrations"], 1)
    check("per author: commits, lines, signed by Claude", hist["authors"],
          {"t": {"commits": 4, "lines": 5, "by_claude": 2}})


def at(hours):
    return datetime(2026, 10, 20, 9, tzinfo=timezone.utc) + timedelta(hours=hours)


def iso(hours):
    return at(hours).isoformat()


def extra_checks(root):
    from datetime import datetime as dt

    def when(v):
        if isinstance(v, dt):
            return v
        return dt.fromisoformat(v) if isinstance(v, str) else None

    check("commit type", [mx.commit_type(x) for x in
                          ("fix(ui)!: a", "feat: b", 'Revert "x"', "no type", "chore(deps): c")],
          ["fix", "feat", "revert", "other", "chore"])
    check("issue of a branch", [mx.issue_of_branch(b) for b in ("feat/12-price", "fix/7-x", "dev/me", None)],
          [12, 7, None, None])

    # --- DORA beyond the four --------------------------------------------------
    pulls = {
        "1": {"branch": "feat/12-price", "created": iso(1), "merged": iso(3), "first": iso(0),
              "reviewed": iso(1.5), "approved": None, "threads": 4, "resolved": 3,
              "author": "a", "early": 30, "lines": 40},
        # The same feature again, after its first reached production.
        "2": {"branch": "feat/12-price", "created": iso(30), "merged": iso(31), "first": iso(29),
              "reviewed": None, "approved": None, "threads": 0, "resolved": 0,
              "author": "a", "early": 10, "lines": 10},
        "3": {"branch": "fix/13-crash", "created": iso(40), "merged": iso(41), "first": iso(39),
              "reviewed": iso(40.5), "approved": iso(40.6), "threads": 1, "resolved": 1,
              "author": "b"},
    }
    deploys = [{"uid": u, "ready": iso(h)} for u, h in (("d1", 4), ("d2", 32), ("d3", 42), ("d4", 50))]

    def change(dep, pr, subject, hours, start):
        return {"deploy": dep, "pr": pr, "subject": subject, "shipped": at(hours),
                "start": at(start), "seconds": (hours - start) * 3600}
    shipped = [
        change("d1", "1", "feat: price", 4, 0),
        # A fix inside the new feature's own PR is that feature's work.
        change("d1", "1", "fix: price rounding", 4, 0),
        change("d2", "2", "feat: price again", 32, 29),
        change("d3", "3", "fix: crash", 42, 39),
        change("d4", None, "feat: direct", 50, 49),
    ]

    def deploy_time(d):
        return when(d["ready"])
    records = [{"regression": {"prod": {"status": "passed"}}},
               {"regression": {"prod": {"status": "failed"}}}, {}]
    dm = mx.dora_more(deploys, shipped, pulls, records, when, deploy_time, at(-1), at(72))
    check("rework: a later PR of a shipped feature, and a fix branch", dm["rework_n"], 2)
    check("rework rate over deploys that shipped changes", dm["rework"], 2 / 4)
    check("hotfix: followed within a day by rework", dm["hotfix_n"], 1)
    check("coding time: first commit to PR", dm["coding"], 3600.0)
    check("deploy time: merge to production", dm["deploy"], 3600.0)
    check("batch size", dm["batch"], 1.0)
    check("reliability: the production suite's verdicts", (dm["reliability"], dm["reliability_n"]), (0.5, 2))
    check("interval between deploys", dm["interval"], 10 * 3600.0)

    dv = mx.devex(pulls, shipped, when, at(-1), at(72))
    check("pickup: opened to first answer", dv["pickup"], 0.5 * 3600)
    check("approve: only where approved", (dv["approvals"], dv["approve"]), (1, 0.1 * 3600))
    check("maturity: lines before opening over all", dv["maturity"], 40 / 50)
    check("PRs with no answer at all", dv["unreviewed"], 1 / 3)
    check("threads resolved", dv["resolved"], 4 / 5)

    issues = {"12": {"created": iso(-48), "closed": iso(5), "bug": False, "reopened": 1,
                     "parent": 5, "open": False, "assigned": True},
              "13": {"created": iso(30), "closed": iso(42), "bug": True, "reopened": 0,
                     "parent": None, "open": False, "assigned": True},
              "14": {"created": iso(0), "closed": None, "bug": False, "reopened": 0,
                     "parent": None, "open": True, "assigned": False}}
    regression = [{"regression": {"local": {"fixes": [{}]}, "preview": {"fixes": []}}}]
    sw = mx.software(issues, shipped, pulls, regression, [("d", "t")], when, at(-1), 4000)
    check("escaped: production's share of what was found", sw["escaped"], 1 / 2)
    check("defect density per 1,000 lines", sw["defect_density"], 0.25)
    check("bug resolution", sw["bug_resolution"], 12 * 3600.0)
    check("reopened over closed", sw["reopened"], 1 / 2)
    check("planned: from a PR of an issue", sw["planned"], 4 / 5)
    check("through a PR", sw["through_pr"], 4 / 5)
    hy = mx.hygiene(issues, pulls)
    check("hygiene", (hy["parented"], hy["linked"], hy["assigned"]), (1 / 3, 1.0, 0.0))

    # --- Claude ------------------------------------------------------------------
    sessions = [
        {"feature": "12-price", "sub": False, "step": "code", "start": iso(0.5), "end": iso(1),
         "prompts": 3, "tools": {"Bash": 20, "AskUserQuestion": 2, "Agent": 1},
         "denials": {"user-rejected": 1}, "api_ms": 1800_000, "tool_ms": 0},
        {"feature": "12-price", "sub": True, "tools": {"Read": 5}, "start": iso(0.6)},
        {"feature": "main", "sub": False, "step": "manual", "start": iso(10), "end": iso(10.5),
         "prompts": 2, "tools": {"Edit": 3}},
    ]
    records = [{"feature": "12-price", "outcome": "done", "issue": 12, "ended": iso(5),
                "deployed": ["prod"], "steps": {"code": {"seconds": 7200}}}]
    hist = {"authors": {"a": {"by_claude": 3}, "b": {"by_claude": 0}}}
    ai = mx.ai(sessions, records, issues, hist, when, at(-1), at(72))
    # Typed: 3 + 2, less the one prompt sclaude opened its session with; then
    # 2 questions answered and 1 action turned down.
    check("human inputs", ai["inputs"], 4 + 2 + 1)
    check("autonomy: tool calls per human input", ai["autonomy"], 31 / 7)
    check("flow efficiency: busy over cycle", ai["flow"], 0.25)
    check("time in the queue: issue to first session", ai["queue"], 48.5 * 3600)
    check("time to market: issue to production", ai["market"], 53 * 3600.0)
    check("adoption: authors with a signed commit", ai["adoption"], 0.5)
    check("feature use", dict(ai["uses"])["Subagents"], 0.5)
    check("sessions by hand", ai["manual"], 0.5)

    week = mx.weekly([dict(s, cost=1.0, tokens={"input": 1, "cache_read": 3}) for s in sessions],
                     [at(-1) - timedelta(days=1)], when)
    check("weekly: spend, cache hits, refusals per 100 calls, features",
          week[0][1:], (3.0, 0.75, 100 / 31, 1))

    path = os.path.join(root, "deferred.tsv")
    with open(path, "w") as fh:
        fh.write("2026-10-10\tx\n2026-10-20\ty\nno date\n")
    check("deferred age: median and oldest", mx.deferred_age([path], at(72)), (8.0, 13))

    # --- the person and Claude ----------------------------------------------------
    people = [
        {"feature": "1-a", "sub": False, "step": "code", "start": iso(0), "tools": {"Bash": 10},
         "api_ms": 3_000_000, "tool_ms": 600_000,
         "human": [[iso(0.5), 600, 4], [iso(1.5), 300, 6]]},
        {"feature": "1-a", "sub": False, "step": "review", "start": iso(2), "tools": {"Bash": 5},
         "api_ms": 1_800_000, "tool_ms": 0, "human": []},
        {"feature": "main", "sub": False, "step": "manual", "start": iso(3), "tools": {},
         "api_ms": 0, "tool_ms": 0, "human": [[iso(3.1), 60, 0]]},
    ]
    sized = {"1-a": {"unit": 2.0, "points": 22.0}}
    hm = mx.human_ai(people, [{"feature": "1-a", "outcome": "done"}], sized, [at(-1)], when)
    check("the person's time against Claude's", (hm["person_s"], hm["claude_s"]), (960, 5400.0))
    check("minutes of the person per hour of Claude", round(hm["minutes_per_hour"], 2), round(16 / 1.5, 2))
    check("a session sclaude started with no turn ran alone", (hm["unattended_n"], hm["started"]), (1, 2))
    check("Claude's run: its calls between turns", hm["run_calls"], 4)
    check("Claude's time alone: the gap less the person's wait", hm["run_time"], 3600 - 300.0)
    check("turns per feature, and per standard feature",
          (hm["turns_per_feature"], hm["turns_per_feature_norm"]), (2, 1.0))
    check("turns by step", dict(hm["steps"])["code"], [2, 900])

    # --- the bands as scores ---------------------------------------------------------
    import metrics_guide
    band = metrics_guide.lower(0.10, 0.20)
    check("a band scores 100 at the good mark, 50 at the watch mark, 0 a step on",
          [band.score(v) for v in (0.05, 0.10, 0.15, 0.20, 0.30, 0.5)], [100, 100, 75, 50, 0, 0])
    check("and still says which band", [band(v) for v in (0.1, 0.15, 0.3)], ["good", "watch", "poor"])
    up = metrics_guide.higher(0.8, 0.6)
    check("higher is better scores the other way", [up.score(v) for v in (0.9, 0.7, 0.4)], [100, 75, 0])

    # --- a feature's size ----------------------------------------------------------
    done = [{"feature": "1-a", "outcome": "done", "issue": 1},
            {"feature": "2-b", "outcome": "done", "issue": 2},
            {"feature": "3-c", "outcome": "done", "issue": 3},
            {"feature": "4-d", "outcome": "dropped", "issue": 4}]
    criteria = {"1": [0, 10], "2": [5, 20]}
    sized_pulls = {"1": {"branch": "feat/1-a", "additions": 900, "deletions": 100},
                   "2": {"branch": "feat/2-b", "additions": 3000, "deletions": 0},
                   "3": {"branch": "feat/3-c", "additions": 500, "deletions": 0},
                   "4": {"branch": "feat/3-c", "additions": 0, "deletions": 0}}
    sizes = mx.complexity(done, criteria, sized_pulls)
    check("sized by its criteria", (sizes["1-a"]["points"], sizes["1-a"]["source"]), (10.0, "criteria"))
    # 1-a: 100 lines a criterion, 2-b: 150; the median rate is 125.
    check("no criteria: sized by lines at the median rate",
          (sizes["3-c"]["points"], sizes["3-c"]["source"]), (4.0, "size"))
    check("the unit is the median feature", sizes["1-a"]["unit"], 1.0)
    check("a dropped feature has no size", "4-d" in sizes, False)
    check("per standard feature: value over size, the median",
          mx.per_unit([("1-a", 10), ("2-b", 10), ("9-z", 99)], sizes), (10 + 5) / 2)

    code = os.path.join(root, "code")
    os.makedirs(os.path.join(code, "tests"))
    with open(os.path.join(code, "a.py"), "w") as fh:
        fh.write("# a comment\nx = 1\n\n" + "y = 2\n" * 600)
    with open(os.path.join(code, "tests", "t.py"), "w") as fh:
        fh.write("assert True\n")
    subprocess.run(["git", "-C", code, "init", "-q"], check=True)
    subprocess.run(["git", "-C", code, "add", "."], check=True)
    health = mx.code_health(code)
    check("code health: lines, comments, large files, tests",
          (health["lines"], health["comments"], health["large"], health["tests"]),
          (603, 1 / 603, 1, 1 / 603))


if __name__ == "__main__":
    sys.exit(main())
