#!/usr/bin/env python3
#
# The metrics page's figures past the first four DORA keys (dora.py), each from
# data the page has already gathered — nothing here asks the network. Grouped
# the way engineering scorecards usually group them:
#
#   dora_more      rework rate (DORA's fifth key since 2024), lead time cut into
#                  coding, review and deploy, its 90th percentile, batch size,
#                  days with a deploy, the interval between deploys, hotfixes,
#                  and the production suite as a stand-in for reliability
#   devex          a pull request's way: coding, pickup, approve, merge,
#                  review and deploy time, aging, merge frequency, maturity
#   software       defects, escaped defects, reopened issues, the work's mix by
#                  commit type, planned against unplanned, changes through a
#                  pull request
#   code_health    comment lines, oversized files, tests in the code
#   hygiene        issues under a parent, branches named after an issue, open
#                  issues with an owner
#   ai             adoption, usage, autonomy, what features of Claude Code are
#                  used, how many features run at once, when work happens
#   weekly         spend, cache hits, refusals and features in work, by week
#   complexity     how big each finished feature was, so that figures per
#                  feature can be compared across features of different size
#
# Every function takes plain lists and dicts and returns plain numbers, None
# where a figure has nothing to stand on — "unknown" is never drawn as zero.
import os
import re
import subprocess
from datetime import timedelta
from statistics import median

DAY = 86400

# Conventional Commits' type, from a subject: `fix(scope)!: …` → fix.
COMMIT_TYPE = re.compile(r"^([a-z]+)(\([^)]*\))?!?:")
FIX_TYPES = {"fix", "hotfix", "revert"}
# Keeping the lights on, as against new work.
SUPPORT_TYPES = {"fix", "hotfix", "revert", "chore", "ci", "build", "deps"}

# Source files the code-health figures count, by extension, and what opens a
# comment line in each family.
SOURCE = {".py": "#", ".sh": "#", ".rb": "#", ".yml": "#", ".yaml": "#",
          ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//", ".mjs": "//", ".go": "//",
          ".java": "//", ".kt": "//", ".swift": "//", ".rs": "//", ".c": "//", ".cpp": "//",
          ".cs": "//", ".php": "//", ".css": "/*", ".scss": "//", ".sql": "--"}
LARGE_FILE = 500
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|e2e|spec|specs)/|\.(test|spec)\.[a-z]+$|_test\.[a-z]+$")


def secs(a, b):
    """b − a in seconds, or None when either is missing or b is earlier."""
    if a is None or b is None:
        return None
    d = (b - a).total_seconds()
    return d if d >= 0 else None


def med(values):
    values = [v for v in values if v is not None]
    return median(values) if values else None


def pct90(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(round(0.9 * (len(values) - 1))))]


def ratio(part, whole):
    return part / whole if whole else None


def commit_type(subject):
    if (subject or "").startswith("Revert"):
        return "revert"
    m = COMMIT_TYPE.match(subject or "")
    return m.group(1) if m else "other"


def issue_of_branch(branch):
    """`feat/12-price-field` → 12, or None."""
    m = re.search(r"(?:^|/)(\d+)-", branch or "")
    return int(m.group(1)) if m else None


# --- DORA, beyond the four ---------------------------------------------------

def dora_more(deploys, shipped, pulls, records, when, deploy_time, since, now):
    """`shipped` is dora.changes(): one row per change with its deploy, PR
    and subject."""
    window = [d for d in deploys if deploy_time(d) and deploy_time(d) >= since]
    by_deploy = {}
    for c in shipped:
        by_deploy.setdefault(c["deploy"], []).append(c)

    # A feature's later pull request, shipped after its first one reached
    # production, is a change made to what was already out: rework.
    first_out = {}
    for c in sorted(shipped, key=lambda c: c["shipped"]):
        branch = (pulls.get(c["pr"] or "") or {}).get("branch")
        if branch and branch not in first_out:
            first_out[branch] = c["shipped"]

    def reworks(change):
        """A fix to what production already had: a feature's pull request
        shipped after its first one, a pull request from a fix branch, or a
        fix committed to main directly. A `fix:` commit inside a new
        feature's own pull request is that feature's work, not rework."""
        branch = (pulls.get(change["pr"] or "") or {}).get("branch")
        if branch:
            return change["shipped"] > first_out.get(branch, change["shipped"]) \
                or branch.split("/", 1)[0] in ("fix", "hotfix")
        return commit_type(change.get("subject")) in FIX_TYPES

    with_changes = [d for d in window if by_deploy.get(d["uid"])]
    rework = [d for d in with_changes if all(reworks(c) for c in by_deploy[d["uid"]])]

    # A deploy followed within a day by one that ships rework needed a hotfix.
    hotfixed = 0
    for i, d in enumerate(window):
        later = [e for e in window[i + 1:] if secs(deploy_time(d), deploy_time(e)) is not None
                 and secs(deploy_time(d), deploy_time(e)) <= DAY]
        if any(reworks(c) for e in later for c in by_deploy.get(e["uid"], [])):
            hotfixed += 1

    recent = [c for c in shipped if c["shipped"] >= since]
    coding, review, deploy = [], [], []
    for c in recent:
        pr = pulls.get(c["pr"] or "")
        if not pr:
            continue
        created, merged = when(pr.get("created")), when(pr.get("merged"))
        coding.append(secs(when(pr.get("first")), created))
        review.append(secs(created, merged))
        deploy.append(secs(merged, c["shipped"]))
    times = sorted(deploy_time(d) for d in window)
    days = {t.astimezone().date() for t in times}
    stage = [((r.get("regression") or {}).get("prod") or {}).get("status") for r in records]
    stage = [s for s in stage if s]
    return {
        "rework": ratio(len(rework), len(with_changes)), "rework_n": len(rework),
        "hotfix": ratio(hotfixed, len(window)), "hotfix_n": hotfixed,
        "lead_p90": pct90([c["seconds"] for c in recent]),
        "lead_pr": med([c["seconds"] for c in recent if c["pr"]]),
        "lead_direct": med([c["seconds"] for c in recent if not c["pr"]]),
        "coding": med(coding), "review": med(review), "deploy": med(deploy),
        "batch": med([len(by_deploy.get(d["uid"], [])) for d in with_changes]),
        "deploy_days": ratio(len(days), max(1, (now - since).days)),
        "interval": med([secs(a, b) for a, b in zip(times, times[1:])]),
        "reliability": ratio(sum(1 for s in stage if s == "passed"), len(stage)),
        "reliability_n": len(stage),
    }


# --- a pull request's way ----------------------------------------------------

def devex(pulls, shipped, when, since, now):
    merged = [p for p in pulls.values() if when(p.get("merged")) and when(p["merged"]) >= since]
    shipped_at = {}
    for c in shipped:
        if c["pr"]:
            shipped_at[c["pr"]] = min(c["shipped"], shipped_at.get(c["pr"], c["shipped"]))
    number = {id(p): n for n, p in pulls.items()}
    rows = {"coding": [], "pickup": [], "approve": [], "merge": [], "review": [], "deploy": [],
            "aging": []}
    for p in merged:
        created, merged_at = when(p.get("created")), when(p.get("merged"))
        reviewed, approved = when(p.get("reviewed")), when(p.get("approved"))
        rows["coding"].append(secs(when(p.get("first")), created))
        rows["pickup"].append(secs(created, reviewed))
        rows["approve"].append(secs(reviewed, approved))
        rows["merge"].append(secs(approved or reviewed, merged_at))
        rows["review"].append(secs(created, approved or merged_at))
        rows["deploy"].append(secs(merged_at, shipped_at.get(number[id(p)])))
        rows["aging"].append(secs(created, merged_at))
    authors = {p.get("author") for p in merged if p.get("author")}
    weeks = max(1.0, (now - since).total_seconds() / (7 * DAY))
    measured = [p for p in merged if p.get("lines")]
    threads = sum(p.get("threads") or 0 for p in merged)
    out = {k: med(v) for k, v in rows.items()}
    out.update({
        "approvals": sum(1 for p in merged if p.get("approved")),
        "merged": len(merged),
        "merge_frequency": ratio(len(merged) / weeks, len(authors)),
        "authors": len(authors),
        "maturity": ratio(sum(p.get("early") or 0 for p in measured),
                          sum(p.get("lines") or 0 for p in measured)),
        "maturity_n": len(measured),
        "unreviewed": ratio(sum(1 for p in merged if not p.get("threads") and not p.get("reviewed")),
                            len(merged)),
        "resolved": ratio(sum(p.get("resolved") or 0 for p in merged), threads),
    })
    return out


# --- software quality --------------------------------------------------------

def software(issues, shipped, pulls, records, failures, when, since, lines_all):
    bugs = [i for i in issues.values() if i.get("bug")]
    fixed = [secs(when(i.get("created")), when(i.get("closed"))) for i in bugs]
    closed = [i for i in issues.values() if i.get("closed")]
    # Where the regression found something to fix, stage by stage; production's
    # are the ones that escaped every earlier gate.
    found = {"local": 0, "preview": 0, "prod": len(failures)}
    for r in records:
        for stage in ("local", "preview"):
            fixes = ((r.get("regression") or {}).get(stage) or {}).get("fixes") or []
            found[stage] += 1 if fixes else 0
    recent = [c for c in shipped if c["shipped"] >= since]
    types = {}
    for c in recent:
        t = commit_type(c.get("subject"))
        types[t] = types.get(t, 0) + 1
    planned = [c for c in recent if c["pr"]
               and issue_of_branch((pulls.get(c["pr"]) or {}).get("branch"))]
    return {
        "bugs": len(bugs),
        "defect_density": ratio(len(bugs), lines_all / 1000) if lines_all else None,
        "bug_resolution": med(fixed),
        "reopened": ratio(sum(1 for i in issues.values() if i.get("reopened")), len(closed)),
        "reopened_n": sum(1 for i in issues.values() if i.get("reopened")),
        "escaped": ratio(found["prod"], sum(found.values())),
        "found": found,
        "types": sorted(types.items(), key=lambda kv: -kv[1]),
        "refactor": ratio(types.get("refactor", 0), len(recent)),
        "support": ratio(sum(n for t, n in types.items() if t in SUPPORT_TYPES), len(recent)),
        "planned": ratio(len(planned), len(recent)),
        "through_pr": ratio(sum(1 for c in recent if c["pr"]), len(recent)),
        "changes": len(recent),
    }


def code_health(repo):
    """A snapshot of the tracked source: comment lines, oversized files, and
    how much of it is tests. None outside a repository."""
    try:
        listed = subprocess.run(["git", "-C", repo, "ls-files", "-z"], capture_output=True,
                                timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listed.returncode != 0:
        return None
    total = comments = tests = files = large = 0
    for raw in listed.stdout.split(b"\0"):
        path = raw.decode("utf-8", "replace")
        mark = SOURCE.get(os.path.splitext(path)[1].lower())
        if not mark or "/vendor/" in path or path.startswith("vendor/"):
            continue
        full = os.path.join(repo, path)
        try:
            if os.path.getsize(full) > 1_000_000:
                continue
            with open(full, encoding="utf-8", errors="replace") as fh:
                lines = [line.strip() for line in fh]
        except OSError:
            continue
        code = [line for line in lines if line]
        files += 1
        total += len(code)
        comments += sum(1 for line in code if line.startswith((mark, "*", "/*", "<!--")))
        large += 1 if len(lines) > LARGE_FILE else 0
        tests += len(code) if TEST_PATH.search(path) else 0
    return {"files": files, "lines": total, "comments": ratio(comments, total),
            "large": large, "tests": ratio(tests, total)}


# --- project hygiene ---------------------------------------------------------

def hygiene(issues, pulls):
    branches = [p.get("branch") for p in pulls.values() if p.get("branch")]
    open_ = [i for i in issues.values() if i.get("open")]
    return {
        "parented": ratio(sum(1 for i in issues.values() if i.get("parent")), len(issues)),
        "linked": ratio(sum(1 for b in branches if issue_of_branch(b)), len(branches)),
        "assigned": ratio(sum(1 for i in open_ if i.get("assigned")), len(open_)),
        "issues": len(issues), "open": len(open_),
    }


# --- Claude ------------------------------------------------------------------

USES = (("Subagents", lambda t: t in ("Agent", "Task")),
        ("Skills", lambda t: t == "Skill"),
        ("MCP tools", lambda t: t.startswith("mcp__")),
        ("Web search and fetch", lambda t: t in ("WebSearch", "WebFetch")),
        ("Questions to the person", lambda t: t == "AskUserQuestion"),
        ("Plan mode", lambda t: t in ("ExitPlanMode", "EnterPlanMode")))


def ai(sessions, records, issues, history, when, since, now):
    mains = [s for s in sessions if not s.get("sub")]
    recent = [s for s in mains if when(s.get("start")) and when(s["start"]) >= since]
    calls = sum(sum((s.get("tools") or {}).values()) for s in sessions)
    # What the person put in: what they typed, the questions Claude asked them
    # and the actions they turned down. sclaude opens each of its sessions
    # with a prompt of its own, which is not the person's.
    started = sum(1 for s in mains if s.get("step") not in ("manual", "other"))
    asked = sum((s.get("tools") or {}).get("AskUserQuestion", 0) for s in sessions)
    rejected = sum((s.get("denials") or {}).get("user-rejected", 0) for s in sessions)
    inputs = max(0, sum(s.get("prompts") or 0 for s in mains) - started) + asked + rejected

    by_feature = {}
    for s in sessions:
        f = s.get("feature")
        by_feature.setdefault(f, []).append(s)
    done = [r for r in records if r.get("outcome") == "done"]
    questions_by = {r.get("feature"): sum((s.get("tools") or {}).get("AskUserQuestion", 0)
                                          for s in by_feature.get(r.get("feature"), []))
                    for r in done if by_feature.get(r.get("feature"))}
    questions = list(questions_by.values())

    # Flow efficiency: the time Claude was busy on a feature, in the model or
    # in tools, against its cycle.
    flow, queue, market, market_by = [], [], [], {}
    for r in done:
        own = [s for s in by_feature.get(r.get("feature"), []) if not s.get("sub")]
        cycle = sum(((r.get("steps") or {}).get(k) or {}).get("seconds") or 0
                    for k in ("plan", "code", "pr", "review"))
        busy = sum((s.get("api_ms") or 0) + (s.get("tool_ms") or 0) for s in own) / 1000
        if cycle and busy:
            flow.append(min(1.0, busy / cycle))
        issue = issues.get(str(r.get("issue")))
        opened = when((issue or {}).get("created"))
        first = min((when(s["start"]) for s in own if when(s.get("start"))), default=None)
        queue.append(secs(opened, first))
        market.append(secs(opened, when(r.get("ended"))) if "prod" in (r.get("deployed") or []) else None)
        market_by[r.get("feature")] = market[-1]

    # How many features had a session on the same day.
    per_day = {}
    for s in mains:
        at = when(s.get("start"))
        if at and s.get("feature") != "main":
            per_day.setdefault(at.astimezone().date(), set()).add(s["feature"])
    weeks = max(1.0, (now - since).total_seconds() / (7 * DAY))
    durations = [secs(when(s.get("start")), when(s.get("end"))) for s in mains]
    authors = (history or {}).get("authors") or {}
    using = sum(1 for a in authors.values() if a.get("by_claude"))

    uses = []
    for name, test in USES:
        n = sum(1 for s in mains if any(test(t) for t in (s.get("tools") or {})))
        uses.append((name, ratio(n, len(mains))))

    heat = [[0] * 24 for _ in range(7)]
    for s in mains:
        at = when(s.get("start"))
        if at:
            local = at.astimezone()
            heat[local.weekday()][local.hour] += 1
    return {
        "autonomy": ratio(calls, inputs), "inputs": inputs, "asked": asked,
        "questions_per_feature": med(questions),
        "manual": ratio(sum(1 for s in mains if s.get("step") == "manual"), len(mains)),
        "subagents_per_session": ratio(len(sessions) - len(mains), len(mains)),
        "concurrent_max": max((len(v) for v in per_day.values()), default=None),
        "concurrent_median": med([len(v) for v in per_day.values()]),
        "flow": med(flow), "queue": med(queue), "market": med(market),
        "adoption": ratio(using, len(authors)), "developers": len(authors),
        "sessions_per_week": len(recent) / weeks,
        "tokens_per_week": sum(sum((s.get("tokens") or {}).values()) - (s.get("tokens") or {}).get("thinking", 0)
                               for s in sessions if when(s.get("start")) and when(s["start"]) >= since) / weeks,
        "session_minutes": (med(durations) or 0) / 60 if med(durations) is not None else None,
        "uses": uses, "heat": heat, "market_by": market_by, "questions_by": questions_by,
        "workshop": sum(1 for s in mains if s.get("step") == "workshop"),
    }


def weekly(sessions, weeks, when):
    """[(monday, spend, cache hit, refusals per 100 calls, features in work)]."""
    out = []
    for monday in weeks:
        end = monday + timedelta(weeks=1)
        mine = [s for s in sessions if when(s.get("start")) and monday <= when(s["start"]) < end]
        tok = {"input": 0, "cache_read": 0, "cache_write": 0}
        for s in mine:
            for k in tok:
                tok[k] += (s.get("tokens") or {}).get(k) or 0
        calls = sum(sum((s.get("tools") or {}).values()) for s in mine)
        refused = sum(sum((s.get("denials") or {}).values()) for s in mine)
        features = {s.get("feature") for s in mine if not s.get("sub") and s.get("feature") != "main"}
        out.append((monday,
                    sum(s.get("cost") or 0 for s in mine) or None,
                    ratio(tok["cache_read"], sum(tok.values())),
                    ratio(refused * 100, calls),
                    len(features) or None))
    return out


def deferred_age(paths, now):
    """Median and oldest age in days of the deferred friction entries, read
    from each line's leading date."""
    ages = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", line)
                    if m:
                        y, mo, d = (int(x) for x in m.groups())
                        ages.append((now.date() - now.date().replace(year=y, month=mo, day=d)).days)
        except (OSError, ValueError):
            continue
    return med(ages), (max(ages) if ages else None)


# --- a feature's complexity --------------------------------------------------
#
# Features differ in size, so a figure per feature — its cycle time, its
# review rounds, what it cost — compares a small one with a large one unless it
# is divided by how much was asked. There are no story points here; what there
# is, is the acceptance criteria the plan wrote into the issue before any code:
# the scope as it was asked for, which the implementation cannot inflate. A
# feature with none is sized by the lines its pull requests changed, turned
# into criteria at the median rate of the features that have both. The unit is
# the median finished feature — "a standard feature" — so a normalised figure
# reads in its usual units: hours, rounds, dollars per standard feature.

def complexity(records, criteria, pulls):
    """{feature: {criteria, lines, points, unit, source}} for each finished
    feature that can be sized; `unit` is its points over the median's."""
    lines = {}
    for p in pulls.values():
        branch = p.get("branch") or ""
        feature = branch.rsplit("/", 1)[-1]
        if feature:
            lines[feature] = lines.get(feature, 0) + (p.get("additions") or 0) + (p.get("deletions") or 0)
    rows = {}
    for r in records:
        feature = r.get("feature")
        if not feature or r.get("outcome") != "done":
            continue
        total = (criteria.get(str(r.get("issue"))) or [0, 0])[1]
        rows[feature] = {"criteria": total or None, "lines": lines.get(feature) or None}
    rate = med([v["lines"] / v["criteria"] for v in rows.values() if v["criteria"] and v["lines"]])
    for v in rows.values():
        if v["criteria"]:
            v["points"], v["source"] = float(v["criteria"]), "criteria"
        elif v["lines"] and rate:
            v["points"], v["source"] = max(1.0, v["lines"] / rate), "size"
        else:
            v["points"], v["source"] = None, None
    standard = med([v["points"] for v in rows.values() if v["points"]])
    out = {}
    for feature, v in rows.items():
        if v["points"] and standard:
            v["unit"] = v["points"] / standard
            out[feature] = v
    return out


def per_unit(pairs, sizes):
    """The median of value ÷ the feature's size in standard features, over
    [(feature, value)]; features that cannot be sized are left out."""
    return med([v / sizes[f]["unit"] for f, v in pairs if v is not None and f in sizes])


# --- the person and Claude ---------------------------------------------------
#
# How much a person had to work for what Claude did. Every time they stepped in
# — a message typed after Claude's turn, an answer to Claude's question — is in
# the transcript with how long it took them (claude_usage.py, capped where they
# had plainly walked away) and how many tool calls Claude made before it. Claude's
# own time is its cost record's time in the model and in tools. The opening
# prompt sclaude gives a session is not the person's.

def human_ai(sessions, records, sizes, weeks, when):
    mains = [s for s in sessions if not s.get("sub")]
    started = [s for s in mains if s.get("step") not in ("manual", "other")]
    turns = [t for s in mains for t in s.get("human") or []]
    person = sum(t[1] for t in turns)
    claude = sum((s.get("api_ms") or 0) + (s.get("tool_ms") or 0) for s in mains) / 1000

    # Claude's run between two of the person's turns, in its own time: the
    # clock between them, less the time the person took over the second.
    runs = []
    for s in mains:
        mine = [t for t in s.get("human") or [] if when(t[0])]
        for a, b in zip(mine, mine[1:]):
            gap = secs(when(a[0]), when(b[0]))
            if gap is not None:
                runs.append(max(0.0, gap - b[1]))

    by_feature = {}
    for s in mains:
        row = by_feature.setdefault(s.get("feature"), [0, 0])
        row[0] += len(s.get("human") or [])
        row[1] += sum(t[1] for t in s.get("human") or [])
    done = [r.get("feature") for r in records if r.get("outcome") == "done"]
    feats = [(f, by_feature[f]) for f in done if f in by_feature]

    steps = {}
    for s in mains:
        row = steps.setdefault(s.get("step"), [0, 0])
        row[0] += len(s.get("human") or [])
        row[1] += sum(t[1] for t in s.get("human") or [])

    weekly_rows = []
    for monday in weeks:
        end = monday + timedelta(weeks=1)
        mine = [s for s in mains if when(s.get("start")) and monday <= when(s["start"]) < end]
        n = sum(len(s.get("human") or []) for s in mine)
        calls = sum(sum((s.get("tools") or {}).values()) for s in mine)
        p = sum(t[1] for s in mine for t in s.get("human") or [])
        c = sum((s.get("api_ms") or 0) + (s.get("tool_ms") or 0) for s in mine) / 1000
        weekly_rows.append((monday, ratio(calls, n), ratio(p, p + c)))
    return {
        "turns": len(turns), "person_s": person, "claude_s": claude,
        "person_share": ratio(person, person + claude),
        "minutes_per_hour": ratio(person / 60, claude / 3600),
        "unattended": ratio(sum(1 for s in started if not s.get("human")), len(started)),
        "unattended_n": sum(1 for s in started if not s.get("human")), "started": len(started),
        "run_calls": med([t[2] for t in turns]),
        "run_time": med(runs),
        "turns_per_feature": med([v[0] for _, v in feats]),
        "turns_per_feature_norm": per_unit([(f, v[0]) for f, v in feats], sizes),
        "minutes_per_feature": med([v[1] / 60 for _, v in feats]),
        "minutes_per_feature_norm": per_unit([(f, v[1] / 60) for f, v in feats], sizes),
        "steps": sorted(((k, v) for k, v in steps.items() if v[0]), key=lambda kv: -kv[1][0]),
        "features": feats[-10:],
        "weekly": weekly_rows,
    }
