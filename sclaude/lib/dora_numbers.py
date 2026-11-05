# The DORA page's numbers: the four keys over a window and by week, and the
# figures beyond them.
#
# Part of sclaude/lib/dora.py.

import os
from datetime import datetime, timedelta, timezone
from statistics import median

import claude_usage  # noqa: E402
import dev_quality  # noqa: E402
import metrics_extra  # noqa: E402
from metrics import STAGES, STEPS

import dora_sources, dora_store


WINDOW = 30
WEEKS = 12

DAY = 86400


# --- the numbers --------------------------------------------------------------

def deploy_time(dep):
    return dora_sources.when(dep.get("ready")) or dora_sources.when(dep.get("created"))


def changes(repo, deploys, pulls):
    """[{deploy, sha, pr, subject, start, shipped, seconds}] for every change
    shipped.

    A change from a pull request starts its clock at the pull request's first
    commit; a commit made on main directly starts at its own author date."""
    by_merge = {pr["merge"]: (num, pr) for num, pr in pulls.items() if pr.get("merge")}
    # A pull request merged with a merge commit brings its branch's commits
    # onto main as they were: each belongs to it as much as the merge does.
    # A squashed one is the merge commit alone.
    for sha, found in list(by_merge.items()):
        raw = dora_sources.run(["git", "rev-list", sha + "^1.." + sha + "^2"], cwd=repo)
        for line in (raw or "").split():
            by_merge.setdefault(line, found)
    out = []
    shipped = dora_sources.commits_first_shipped(repo, deploys)
    for dep in deploys:
        at = deploy_time(dep)
        for sha, authored, subject in shipped.get(dep["uid"], []):
            num, pr = by_merge.get(sha, (None, None))
            start = dora_sources.when((pr or {}).get("first")) or dora_sources.when(authored)
            if at is None or start is None:
                continue
            out.append({"deploy": dep["uid"], "sha": sha, "pr": num, "subject": subject,
                        "start": start, "shipped": at,
                        "seconds": max(0, (at - start).total_seconds())})
    return out


def incidents(gh_found, records):
    """[datetime] of every production rollback, oldest first.

    GitHub's comments first; a cycle record's rollback only where no comment
    lies within the hour — the same rollback seen twice is one incident. The
    record keeps only a rollback that was never followed by a fresh ship
    (deploy_remember clears it), so on its own it undercounts."""
    seen = sorted(t for t in (dora_sources.when(i.get("at")) for i in gh_found or []) if t)
    for rec in records:
        at = dora_sources.when((rec.get("rollback") or {}).get("at"))
        if at and all(abs((at - t).total_seconds()) > 3600 for t in seen):
            seen.append(at)
    return sorted(seen)


def failures(deploys, rollbacks):
    """[(failed deploy, restored at)] — each rollback against the deploy that
    was serving production just before it."""
    out = []
    for at in rollbacks:
        before = [d for d in deploys if deploy_time(d) and deploy_time(d) <= at]
        if before:
            out.append((before[-1], at))
    return out


def level(kind, value):
    """Elite / High / Medium / Low by the State of DevOps thresholds, or None."""
    if value is None:
        return None
    if kind == "frequency":     # deploys a day
        return "Elite" if value >= 1 else "High" if value >= 1 / 7 else \
            "Medium" if value >= 1 / 30 else "Low"
    if kind == "lead":          # seconds
        return "Elite" if value < DAY else "High" if value < 7 * DAY else \
            "Medium" if value < 30 * DAY else "Low"
    if kind == "failure":       # a share
        return "Elite" if value <= 0.05 else "High" if value <= 0.10 else \
            "Medium" if value <= 0.15 else "Low"
    if kind == "restore":       # seconds
        return "Elite" if value < 3600 else "High" if value < DAY else \
            "Medium" if value < 7 * DAY else "Low"
    return None


def window_metrics(deploys, shipped, failed, start, end):
    """The four numbers over [start, end)."""
    deps = [d for d in deploys if deploy_time(d) and start <= deploy_time(d) < end]
    days = max(1.0, (end - start).total_seconds() / DAY)
    leads = [c["seconds"] for c in shipped if start <= c["shipped"] < end]
    fails = [(d, at) for d, at in failed if start <= deploy_time(d) < end]
    failed_ids = {d["uid"] for d, _ in fails}
    restores = [(at - deploy_time(d)).total_seconds() for d, at in fails]
    return {
        "deploys": len(deps),
        "per_day": len(deps) / days,
        "lead": median(leads) if leads else None,
        "changes": len(leads),
        "failure": (len(failed_ids) / len(deps)) if deps else None,
        "failed": len(failed_ids),
        "restore": median(restores) if restores else None,
        "incidents": len(fails),
    }


def week_start(at):
    local = at.astimezone()
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def weekly(deploys, shipped, now):
    """[(monday, deploys, median lead seconds or None)] for the last WEEKS,
    or from the first deploy's week when the history is shorter: weeks
    before anything was ever deployed are not weeks with no deploys."""
    first = week_start(now) - timedelta(weeks=WEEKS - 1)
    if deploys and deploy_time(deploys[0]):
        first = max(first, week_start(deploy_time(deploys[0])))
    out = []
    for i in range((week_start(now) - first).days // 7 + 1):
        a = first + timedelta(weeks=i)
        b = a + timedelta(weeks=1)
        n = sum(1 for d in deploys if deploy_time(d) and a <= deploy_time(d) < b)
        leads = [c["seconds"] for c in shipped if a <= c["shipped"] < b]
        out.append((a, n, median(leads) if leads else None))
    return out


# Where a feature's time went, in the cycle's own terms: the four steps, then
# the regression's three stages taken together.
PARTS = STEPS + ("regression",)
PART_NAMES = {"plan": "Plan", "code": "Code", "pr": "Pull request",
              "review": "Review", "regression": "Regression"}


def cycle_parts(rec):
    steps = rec.get("steps") or {}
    out = {s: (steps.get(s) or {}).get("seconds") or 0 for s in STEPS}
    out["regression"] = sum(((rec.get("regression") or {}).get(s) or {}).get("seconds") or 0
                            for s in STAGES)
    return out


def collect(repo):
    """Every source, merged with what the earlier runs kept."""
    folder = dora_store.out_dir(repo)
    os.makedirs(folder, exist_ok=True)
    notes = []

    kept = {d["uid"]: d for d in dora_store.load(os.path.join(folder, "deployments.json"), [])
            if isinstance(d, dict) and d.get("uid")}
    fresh = dora_sources.vercel_deployments(repo)
    if fresh is None:
        notes.append("Vercel could not be asked; production deploys are the ones kept from earlier runs.")
    else:
        kept.update({d["uid"]: d for d in fresh if d.get("uid")})
        dora_store.save(os.path.join(folder, "deployments.json"), list(kept.values()))

    pulls = dora_store.load(os.path.join(folder, "pulls.json"), {})
    found = dora_store.load(os.path.join(folder, "incidents.json"), [])
    issue_rows = dora_store.load(os.path.join(folder, "issues.json"), {})
    name = dora_sources.gh_name(repo)
    if name is None:
        notes.append("GitHub could not be asked; pull requests and incidents are the ones kept from earlier runs.")
    else:
        got = dora_sources.gh_pulls(repo, name)
        if got is not None:
            for number, pr in got.items():
                pulls[number] = dict(pulls.get(number) or {}, **pr)
            dora_sources.gh_maturity(repo, name, pulls)
            dora_store.save(os.path.join(folder, "pulls.json"), pulls)
        else:
            notes.append("GitHub did not list the pull requests this time.")
        got = dora_sources.gh_issues(repo, name)
        if got is not None:
            issue_rows.update(got)
            dora_store.save(os.path.join(folder, "issues.json"), issue_rows)
        else:
            notes.append("GitHub did not list the issues this time.")
        got = dora_sources.gh_incidents(repo, name)
        if got is not None:
            found = got
            dora_store.save(os.path.join(folder, "incidents.json"), found)
        else:
            notes.append("GitHub did not list the rollback comments this time.")

    records = dora_sources.cycles(repo, pulls)
    # A deploy kept before previews were kept too has no target: it was
    # production's.
    builds = [d for d in kept.values() if deploy_time(d)]
    deploys = sorted((d for d in builds if d.get("state") == "READY"
                      and d.get("target", "production") == "production"),
                     key=deploy_time)
    if not deploys:
        # A product Vercel does not deploy: a finished feature that says it
        # reached production stands for the deploy, at the moment it ended.
        deploys = [{"uid": "cycle:%s:%s" % (r.get("feature"), r.get("ended")),
                    "url": "", "sha": "", "state": "READY", "created": r.get("ended"),
                    "ready": r.get("ended"), "feature": r.get("feature")}
                   for r in records if "prod" in (r.get("deployed") or []) and dora_sources.when(r.get("ended"))]
        deploys.sort(key=deploy_time)
        if deploys:
            notes.append("No Vercel deployments: each feature that reached production stands for one deploy, "
                         "and lead time cannot be measured.")
    sessions = claude_usage.sessions(repo, os.path.join(folder, "sessions.json"))
    issues = sorted({r["issue"] for r in records if r.get("outcome") == "done"
                     and isinstance(r.get("issue"), int)})
    criteria = dev_quality.acceptance(repo, name, issues, os.path.join(folder, "acceptance.json"))
    finished = {r.get("feature") for r in records if r.get("outcome") == "done"}
    moves = dev_quality.requirements(repo, name, issues, os.path.join(folder, "requirements.json"))
    review_rounds = dora_sources.gh_review_rounds(repo, name, pulls, finished,
                                     os.path.join(folder, "review-rounds.json")) \
        if name else dora_store.load(os.path.join(folder, "review-rounds.json"), {})
    return {"deploys": deploys, "pulls": pulls, "incidents": found,
            "records": records, "notes": notes, "github": name, "builds": builds,
            "sessions": sessions, "criteria": criteria, "issues": issue_rows,
            "review_rounds": review_rounds, "requirements": moves}


def compute(repo, data, now=None):
    now = now or datetime.now(timezone.utc)
    deploys = data["deploys"]
    shipped = changes(repo, deploys, data["pulls"])
    failed = failures(deploys, incidents(data["incidents"], data["records"]))
    cur = window_metrics(deploys, shipped, failed, now - timedelta(days=WINDOW), now)
    prev = window_metrics(deploys, shipped, failed, now - timedelta(days=2 * WINDOW),
                          now - timedelta(days=WINDOW))
    lead_by_deploy = {}
    for c in shipped:
        lead_by_deploy.setdefault(c["deploy"], []).append(c["seconds"])
    failed_ids = {d["uid"]: at for d, at in failed}
    recent = []
    for dep in reversed(deploys[-20:]):
        leads = lead_by_deploy.get(dep["uid"]) or []
        recent.append({"at": deploy_time(dep), "sha": dep.get("sha") or "",
                       "url": dep.get("url") or "", "feature": dep.get("feature"),
                       "changes": len(leads), "lead": median(leads) if leads else None,
                       "restored": failed_ids.get(dep["uid"])})
    done = [r for r in data["records"] if r.get("outcome") == "done"]
    return {
        "more": more(repo, data, deploys, now, shipped, failed),
        "now": now, "current": cur, "previous": prev,
        "weeks": weekly(deploys, shipped, now),
        "recent": recent,
        "features": [(r.get("feature") or "?", cycle_parts(r), dora_sources.when(r.get("ended")))
                     for r in done[-10:]],
        "failed": [(deploy_time(d), at) for d, at in failed],
        "total_deploys": len(deploys),
        "since": deploy_time(deploys[0]) if deploys else None,
    }


# --- beyond DORA ----------------------------------------------------------------
#
# Everything else the page shows: delivery, quality, and what Claude did and
# what it cost. Each figure is over the same 30 days as DORA's unless it says
# "all time"; the hero strip counts everything ever recorded.

def ratio(part, whole):
    return part / whole if whole else None


def feature_of_branch(branch):
    """`feat/12-price-field` → `12-price-field`."""
    return branch.rsplit("/", 1)[-1] if branch else ""


def more(repo, data, deploys, now, shipped=(), failed=()):
    since = now - timedelta(days=WINDOW)
    records = data.get("records") or []
    pulls = data.get("pulls") or {}
    sessions = data.get("sessions") or []
    builds = data.get("builds") or []
    mains = [s for s in sessions if not s.get("sub")]

    def started(s):
        return dora_sources.when(s.get("start"))

    recent = [s for s in sessions if started(s) and started(s) >= since]
    recent_mains = [s for s in recent if not s.get("sub")]

    def tokens(items):
        out = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0}
        for s in items:
            for k in out:
                out[k] += (s.get("tokens") or {}).get(k) or 0
        return out

    def cost(items):
        return sum(s.get("cost") or 0 for s in items)

    def counter(items, key):
        out = {}
        for s in items:
            for k, v in (s.get(key) or {}).items():
                out[k] = out.get(k, 0) + v
        return out

    tok_all, tok_recent = tokens(sessions), tokens(recent)
    tools_all = counter(sessions, "tools")
    by_step, by_feature = {}, {}
    for s in mains:
        by_step[s["step"]] = by_step.get(s["step"], 0) + (s.get("cost") or 0)
        by_feature[s["feature"]] = by_feature.get(s["feature"], 0) + (s.get("cost") or 0)

    done = [r for r in records if r.get("outcome") == "done"]
    dropped = [r for r in records if r.get("outcome") == "dropped"]
    done_names = {r.get("feature") for r in done}
    feature_costs = [by_feature[f] for f in done_names if by_feature.get(f)]

    merged = [p for p in pulls.values() if dora_sources.when(p.get("merged")) and dora_sources.when(p["merged"]) >= since]
    sizes = [(p.get("additions") or 0) + (p.get("deletions") or 0) for p in merged
             if p.get("additions") is not None]
    threads = [p.get("threads") for p in merged if p.get("threads") is not None]
    prs_per_feature = {}
    for p in pulls.values():
        f = feature_of_branch(p.get("branch"))
        if f in done_names:
            prs_per_feature[f] = prs_per_feature.get(f, 0) + 1

    window_deploys = [d for d in deploys if deploy_time(d) and deploy_time(d) >= since]
    window_builds = [b for b in builds if deploy_time(b) and deploy_time(b) >= since]
    build_secs = [(dora_sources.when(b.get("ready")) - dora_sources.when(b.get("building"))).total_seconds()
                  for b in window_builds if dora_sources.when(b.get("ready")) and dora_sources.when(b.get("building"))]

    hist = dev_quality.history(repo, since)
    first = min((started(s) for s in mains if started(s)), default=None)
    hist_all = dev_quality.history(repo, first) if first else None
    window_cost = cost(recent)
    changed = ((hist or {}).get("added", 0) + (hist or {}).get("removed", 0))

    shipped_weeks = []
    for monday, _, _ in weekly(deploys, [], now):
        n = sum(1 for r in done if "prod" in (r.get("deployed") or [])
                and dora_sources.when(r.get("ended")) and monday <= dora_sources.when(r["ended"]) < monday + timedelta(weeks=1))
        shipped_weeks.append((monday, n, None))

    ai_figures = metrics_extra.ai(sessions, records, data.get("issues") or {}, hist, dora_sources.when, since, now)
    reviews = dev_quality.review_log(repo)
    # The review per finished feature, every pull request of it together
    # (gh_review_rounds): newest first, as the cycle records end.
    per_feature = data.get("review_rounds") or {}
    order = [r.get("feature") for r in done]
    reviewed = [(f, per_feature[f]) for f in order if f in per_feature]
    all_threads = sum(v["threads"] for _, v in reviewed)
    criteria = data.get("criteria") or {}
    cycles_secs = [sum(cycle_parts(r).values()) for r in done]
    cycles_secs = [x for x in cycles_secs if x]

    return {
        "since": first,
        "sessions": len(mains), "subagents": len(sessions) - len(mains),
        "sessions_recent": len(recent_mains),
        "cost": cost(sessions), "cost_recent": window_cost,
        "tokens": tok_all, "tokens_recent": tok_recent,
        "tool_calls": sum(tools_all.values()),
        "tools": sorted(tools_all.items(), key=lambda kv: -kv[1])[:8],
        "lines_by_claude": sum(s.get("lines_added") or 0 for s in sessions),
        "by_step": sorted(((k, v) for k, v in by_step.items() if v > 0), key=lambda kv: -kv[1]),
        "by_feature": sorted(((f, by_feature[f]) for f in done_names if by_feature.get(f)),
                             key=lambda kv: -kv[1])[:10],
        "models": counter(sessions, "models"),
        "cache_hit": ratio(tok_all["cache_read"],
                           tok_all["input"] + tok_all["cache_read"] + tok_all["cache_write"]),
        "thinking_share": ratio(tok_all["thinking"], tok_all["output"]),
        "per_feature": median(feature_costs) if feature_costs else None,
        "per_deploy": ratio(window_cost, len(window_deploys)),
        "per_pr": ratio(window_cost, len(merged)),
        "per_kloc": ratio(window_cost, changed / 1000) if changed else None,
        "calls_per_session": median([sum((s.get("tools") or {}).values()) for s in mains])
        if mains else None,
        "output_per_call": ratio(tok_all["output"], sum(tools_all.values())),
        "api_share": ratio(sum(s.get("api_ms") or 0 for s in mains),
                           sum((s.get("api_ms") or 0) + (s.get("tool_ms") or 0) for s in mains)),
        "denials": counter(sessions, "denials"),
        "compactions": sum(s.get("compactions") or 0 for s in sessions),
        "api_errors": sum(s.get("api_errors") or 0 for s in sessions),
        # Delivery.
        "shipped": sum(1 for r in done if "prod" in (r.get("deployed") or [])
                       and dora_sources.when(r.get("ended")) and dora_sources.when(r["ended"]) >= since),
        "shipped_weeks": shipped_weeks,
        "done": len(done), "dropped": len(dropped),
        "cycle": median(cycles_secs) if cycles_secs else None,
        "merged": len(merged),
        "pr_size": median(sizes) if sizes else None,
        "prs_per_feature": ratio(sum(prs_per_feature.values()), len(prs_per_feature)),
        "reworked": sum(1 for n in prs_per_feature.values() if n > 1),
        "previews": sum(1 for b in window_builds if b.get("target", "production") != "production"),
        "build_errors": sum(1 for b in window_builds if b.get("state") == "ERROR"),
        "builds": len(window_builds),
        "build_time": median(build_secs) if build_secs else None,
        # Quality.
        "regression": dev_quality.regression(done),
        "friction": dev_quality.friction(records),
        "deferred": dev_quality.deferred(repo),
        "review_sessions": reviews["sessions"],
        "review_rounds": reviews["rounds"],
        "review_comments": reviews["comments"],
        "reversals": reviews["reversals"],
        "threads_per_pr": median(threads) if threads else None,
        "threads": sum(threads),
        "criteria": sum(t for _, t in criteria.values()),
        "criteria_ticked": sum(x for x, _ in criteria.values()),
        "criteria_issues": sum(1 for _, t in criteria.values() if t),
        "history": hist, "history_all": hist_all,
        "review_door": reviews.get("door"), "review_end_pct": reviews.get("end_pct"),
        "norm": normalised(done, data.get("criteria") or {}, pulls, sessions, by_feature, reviewed,
                           weekly(deploys, [], now), since, ai_figures),
        "requirements": requirement_figures(done, data.get("requirements") or {}, sessions,
                                            metrics_extra.complexity(done, data.get("criteria") or {}, pulls)),
        "human": metrics_extra.human_ai(sessions, records,
                                        metrics_extra.complexity(done, data.get("criteria") or {}, pulls),
                                        [w for w, _, _ in weekly(deploys, [], now)], dora_sources.when),
        "rounds_per_feature": metrics_extra.med([v["rounds"] for _, v in reviewed]),
        "threads_per_feature": metrics_extra.med([v["threads"] for _, v in reviewed]),
        "declined_share": ratio(sum(v["declined"] for _, v in reviewed), all_threads),
        "open_share": ratio(sum(v["open"] for _, v in reviewed), all_threads),
        "reviewed_features": reviewed[-10:], "reviewed_n": len(reviewed),
        "review_threads_all": all_threads,
        "dora": metrics_extra.dora_more(deploys, list(shipped), pulls, done, dora_sources.when, deploy_time,
                                        since, now),
        "devex": metrics_extra.devex(pulls, list(shipped), dora_sources.when, since, now),
        "software": metrics_extra.software(data.get("issues") or {}, list(shipped), pulls, done,
                                           list(failed), dora_sources.when, since,
                                           (hist_all or {}).get("added", 0) + (hist_all or {}).get("removed", 0)),
        "code": metrics_extra.code_health(repo),
        "hygiene": metrics_extra.hygiene(data.get("issues") or {}, pulls),
        "ai": ai_figures,
        "weekly": metrics_extra.weekly(sessions, [w for w, _, _ in weekly(deploys, [], now)], dora_sources.when),
        "deferred_age": metrics_extra.deferred_age(dev_quality.deferred_files(repo), now),
    }


# A feature whose planning needed at least as many clarifying questions as it
# ended with acceptance criteria started from requirements that did not say
# enough. Relative to its size, because questions grow with it: a fixed count
# would only pick out the large features.
QUESTIONS_PER_CRITERION = 1.0


def requirement_figures(done, moves, sessions, sizes):
    """How the requirements of finished features held: changed after the plan
    was approved (dev_quality.requirements), and how many clarifying
    questions planning needed — each question of an AskUserQuestion call in
    the feature's plan sessions."""
    asked = {}
    for s in sessions:
        if not s.get("sub") and s.get("step") == "plan":
            asked[s.get("feature")] = asked.get(s.get("feature"), 0) + (s.get("questions") or 0)
    rows = []
    for r in done:
        f = r.get("feature")
        move = moves.get(str(r.get("issue")))
        rows.append((f, move, asked.get(f)))
    moved = [m for _, m, _ in rows if m]
    planned = [(f, q) for f, _, q in rows if q is not None]
    measured = [(f, q / sizes[f]["points"]) for f, q in planned if f in sizes]
    unclear = [f for f, rate in measured if rate >= QUESTIONS_PER_CRITERION]
    growth = [m["request_words"] / m["description_words"] for m in moved
              if m.get("request_words") and m.get("description_words")]
    return {
        "rows": rows[-10:],
        "covered": len(moved),
        "significant": metrics_extra.ratio(sum(1 for m in moved if m["significant"]), len(moved)),
        "significant_n": sum(1 for m in moved if m["significant"]),
        "changed": metrics_extra.ratio(sum(1 for m in moved if m["changed"]), len(moved)),
        "added": sum(m["added"] for m in moved),
        "added_median": metrics_extra.med([m["added"] for m in moved]),
        "unclear": metrics_extra.ratio(len(unclear), len(measured)),
        "unclear_n": len(unclear), "planned": len(measured),
        "per_criterion": metrics_extra.med([rate for _, rate in measured]),
        "questions": metrics_extra.med([q for _, q in planned]),
        "questions_norm": metrics_extra.per_unit(planned, sizes),
        "questions_by": planned[-10:],
        "growth": metrics_extra.med(growth),
    }


def normalised(done, criteria, pulls, sessions, by_feature, reviewed, weeks, since, ai):
    """The figures that scale with a feature's size, divided by it
    (metrics_extra.complexity): per standard feature rather than per feature,
    and the weekly slices weighted by the size of what each week delivered or
    had in work. Features that cannot be sized are left out, and counted."""
    sizes = metrics_extra.complexity(done, criteria, pulls)

    def unit(feature):
        return (sizes.get(feature) or {}).get("unit")

    def ended(r):
        return dora_sources.when(r.get("ended"))
    shipped = [r for r in done if "prod" in (r.get("deployed") or []) and ended(r)]
    weekly_shipped, weekly_work, weekly_spend = [], [], []
    for monday, _, _ in weeks:
        end = monday + timedelta(weeks=1)
        units = sum(unit(r["feature"]) or 0 for r in shipped if monday <= ended(r) < end)
        active = {s.get("feature") for s in sessions
                  if dora_sources.when(s.get("start")) and monday <= dora_sources.when(s["start"]) < end}
        spend = sum(s.get("cost") or 0 for s in sessions
                    if dora_sources.when(s.get("start")) and monday <= dora_sources.when(s["start"]) < end)
        weekly_shipped.append((monday, units or None, None))
        weekly_work.append((monday, sum(unit(f) or 0 for f in active) or None, None))
        weekly_spend.append((monday, spend / units if units else None, None))
    cycles = [(r.get("feature"), sum(cycle_parts(r).values()) or None) for r in done]
    return {
        "sizes": sizes, "sized": len(sizes), "features": len(done),
        "standard": metrics_extra.med([v["points"] for v in sizes.values()]),
        "cycle": metrics_extra.per_unit(cycles, sizes),
        "market": metrics_extra.per_unit(list(ai["market_by"].items()), sizes),
        "questions": metrics_extra.per_unit(list(ai["questions_by"].items()), sizes),
        "rounds": metrics_extra.per_unit([(f, v["rounds"]) for f, v in reviewed], sizes),
        "threads": metrics_extra.per_unit([(f, v["threads"]) for f, v in reviewed], sizes),
        "cost": metrics_extra.per_unit([(f, by_feature.get(f)) for f in sizes if by_feature.get(f)], sizes),
        "shipped": sum(unit(r["feature"]) or 0 for r in shipped if ended(r) >= since),
        "weekly_shipped": weekly_shipped, "weekly_work": weekly_work, "weekly_spend": weekly_spend,
        "by_feature": sorted(((f, c / unit(f)) for f, c in by_feature.items() if unit(f) and c),
                             key=lambda kv: -kv[1])[:10],
        "reviewed": [(f, {k: v[k] / unit(f) for k in ("rounds", "threads", "fixed", "declined", "open")})
                     for f, v in reviewed if unit(f)],
        "features_time": [(r.get("feature") or "?", {k: v / unit(r.get("feature")) for k, v in
                                                     cycle_parts(r).items()}, ended(r))
                          for r in done[-10:] if unit(r.get("feature"))],
    }
