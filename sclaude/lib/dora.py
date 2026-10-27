#!/usr/bin/env python3
#
# What sclaude measures about a product, as one page in its own tree. First
# the four DORA metrics:
#
#   deployment frequency   production deploys per week
#   lead time for changes  a change's first commit to the deploy that shipped it
#   change failure rate    the share of production deploys that had to be undone
#   time to restore        a failed deploy to production serving again
#
# then the rest of DORA and a pull request's way (metrics_extra.py: rework and
# hotfix rates, lead time by stage, coding, pickup, review and merge time),
# delivery (features shipped, cycle time, time to market, flow efficiency),
# software quality (dev_quality.py and metrics_extra.py: regression first
# time, escaped defects, reopened issues, work by commit type, review threads,
# acceptance criteria, friction), code health and project hygiene, and
# Claude's own work and what it cost (claude_usage.py: sessions, autonomy,
# tool calls, tokens, dollars per result, weekly trends).
#
# The page is the product's, not the orchestrator's: its numbers, commits and
# feature names describe one team's work. So it is written into the product,
# at .sclaude/local/dora/index.html, beside the caches it is built from, and
# sclaude-proxy serves it under the `main` row of its list. local/ rather than
# the committed part of .sclaude/: the page is rebuilt every few hours, and a
# file that changes by itself in a tracked folder would dirty the main
# checkout — the one place where "uncommitted changes" must mean somebody's
# work.
#
# Read, never recorded anew. Every number comes from what already exists:
#
#   Vercel        the production deployments, with their commit and time —
#                 the one list of what actually reached production
#   git           which commits each deploy shipped first
#   GitHub        each merged pull request's first commit, and the incident
#                 comments rollback_incident writes on a feature's issue
#   cycles.jsonl  metrics.py's record of every finished feature: where its
#                 cycle time went, step by step, and a rollback as a fallback
#                 for an incident GitHub cannot be asked about
#   transcripts   Claude Code's record of every session in the product's trees
#
# What Vercel and GitHub answered is kept in the same folder and merged with
# every later answer, so history outlives Vercel's retention and a refresh with
# no network still draws the last known picture.
#
# Rebuilt rarely, in the background: `sclaude` starts it on every
# conversational run (dora_refresh in state.sh), and it does nothing unless the
# page is older than SCLAUDE_DORA_EVERY seconds (six hours). A finished feature
# forces it — that is when the numbers move. Two sclaudes starting together
# build it once: the second finds the lock taken and leaves.
#
#   dora.py refresh <repo> [--force]   rebuild if stale (or always), quietly
#   dora.py build <repo>               rebuild now and print the page's path
#
# Silent on any trouble, like metrics.py: a source that cannot be read leaves a
# hole on the page, which says which source it was, and never an error.
import fcntl
import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_usage  # noqa: E402
import dev_quality  # noqa: E402
import metrics_extra  # noqa: E402
import metrics_guide  # noqa: E402
from issue_comments import ROLLBACK as ROLLBACK_MARKER  # noqa: E402
from metrics import STAGES, STEPS, log_path  # noqa: E402

DIR = os.path.join(".sclaude", "local", "dora")
PAGE = "index.html"
EVERY = 6 * 3600
WINDOW = 30
WEEKS = 12

# What rollback_incident heads its comment with (rollback.sh): the marker
# (issue_comments.py) finds the comment among the thread, the heading is what
# GitHub's search can see — it does not index an HTML comment.
ROLLBACK_HEADING = "Production rolled back"

DAY = 86400


def out_dir(repo):
    return os.path.join(repo, DIR)


def run(args, cwd=None, timeout=60):
    """stdout of a command, or None when it is missing, fails or hangs."""
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL,
                              env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def when(value):
    """An aware datetime from an ISO string or epoch milliseconds, or None."""
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    if not value or not isinstance(value, str):
        return None
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# --- the sources --------------------------------------------------------------

def vercel_deployments(repo):
    """[{uid, url, sha, state, target, created, building, ready}] of every
    environment, newest first — production's are the deploys, the rest are
    the previews counted among the builds.

    The query vercel_prod_deployments in rollback.sh makes, every environment
    and a longer list: that one wants the release to go back to, this one the
    history. None when Vercel could not be asked, which is not the same as no
    deploys.
    """
    if not os.path.isfile(os.path.join(repo, ".vercel", "project.json")):
        return None
    raw = run(["vercel", "ls", "--json", "--limit", "100"], cwd=repo, timeout=90)
    if raw is None or raw.find("{") < 0:
        return None
    try:
        data = json.loads(raw[raw.find("{"):])
    except ValueError:
        return None
    out = []
    for item in data.get("deployments") or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        out.append({
            "uid": item.get("uid") or item.get("url"),
            "url": item.get("url") or "",
            "sha": (meta.get("githubCommitSha") or "")[:40],
            "state": (item.get("state") or "").upper(),
            "target": item.get("target") or "preview",
            "created": item.get("createdAt"),
            "building": item.get("buildingAt"),
            "ready": item.get("ready"),
        })
    return out


def gh_name(repo):
    raw = run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
              cwd=repo, timeout=30)
    name = (raw or "").strip()
    return name if "/" in name else None


PR_QUERY = """
query($owner: String!, $name: String!, $before: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, last: 40, before: $before,
                 orderBy: {field: UPDATED_AT, direction: ASC}) {
      pageInfo { hasPreviousPage startCursor }
      nodes {
        number headRefName createdAt mergedAt additions deletions changedFiles
        author { login }
        mergeCommit { oid }
        commits(first: 60) {
          nodes { commit { authoredDate } }
        }
        reviews(first: 30) { nodes { state submittedAt } }
        comments(first: 1) { nodes { createdAt } }
        reviewThreads(first: 60) {
          totalCount
          nodes { isResolved comments(first: 1) { nodes { createdAt } } }
        }
      }
    }
  }
}
"""


# The pull requests read each time: the most recently updated, which a cache
# kept beside the page adds to run by run.
PR_PAGES = 3


def earliest(values):
    found = [v for v in values if when(v)]
    return min(found, key=when) if found else None


def gh_pulls(repo, name):
    """{number: {...}} of the latest merged pull requests, or None.

    `first` is the first commit's author date — where DORA starts a change's
    clock. `reviewed` is the first answer the pull request got — a review, a
    thread or a comment, a bot's included: what a person waiting on it sees.
    `approved` is the first approving review."""
    owner, _, short = name.partition("/")
    # Pages of forty: a hundred pull requests with their commits and threads
    # in one query is more than GitHub answers before its gateway gives up.
    nodes, before = [], None
    for _ in range(PR_PAGES):
        args = ["gh", "api", "graphql", "-f", "query=" + PR_QUERY,
                "-F", "owner=" + owner, "-F", "name=" + short]
        if before:
            args += ["-F", "before=" + before]
        raw = run(args, cwd=repo, timeout=120)
        try:
            page = json.loads(raw)["data"]["repository"]["pullRequests"]
        except (TypeError, ValueError, KeyError):
            if not nodes:
                return None
            break
        nodes += page.get("nodes") or []
        info = page.get("pageInfo") or {}
        if not info.get("hasPreviousPage"):
            break
        before = info.get("startCursor")
    out = {}
    for node in nodes or []:
        commits = [(c or {}).get("commit") or {}
                   for c in (node.get("commits") or {}).get("nodes") or []]
        reviews = (node.get("reviews") or {}).get("nodes") or []
        threads = (node.get("reviewThreads") or {})
        answers = [r.get("submittedAt") for r in reviews] + \
            [((t.get("comments") or {}).get("nodes") or [{}])[0].get("createdAt")
             for t in threads.get("nodes") or []] + \
            [c.get("createdAt") for c in (node.get("comments") or {}).get("nodes") or []]
        out[str(node["number"])] = {
            "branch": node.get("headRefName") or "",
            "author": (node.get("author") or {}).get("login"),
            "created": node.get("createdAt"),
            "merged": node.get("mergedAt"),
            "merge": (node.get("mergeCommit") or {}).get("oid") or "",
            "first": earliest(c.get("authoredDate") for c in commits),
            "additions": node.get("additions"),
            "deletions": node.get("deletions"),
            "files": node.get("changedFiles"),
            "threads": threads.get("totalCount"),
            "resolved": sum(1 for t in threads.get("nodes") or [] if t.get("isResolved")),
            "reviewed": earliest(answers),
            "approved": earliest(r.get("submittedAt") for r in reviews if r.get("state") == "APPROVED"),
        }
    return out


def gh_maturity(repo, name, pulls, limit=100):
    """Adds `early` and `lines` to merged pull requests that lack them: the
    lines their commits changed before the pull request was opened, and in
    all — how finished it was when it was put up.

    A query of its own, ten pull requests at a time and only for the ones not
    yet measured: a commit's size is what makes GitHub slow, and a merged pull
    request's commits do not change. False when GitHub did not answer."""
    owner, _, short = name.partition("/")
    todo = [n for n, p in pulls.items() if "lines" not in p][:limit]
    for i in range(0, len(todo), 10):
        batch = todo[i:i + 10]
        fields = " ".join(
            "p%s: pullRequest(number: %s) { createdAt commits(first: 100) "
            "{ nodes { commit { committedDate additions deletions } } } }" % (n, n) for n in batch)
        raw = run(["gh", "api", "graphql", "-f",
                   "query=query { repository(owner: %s, name: %s) { %s } }"
                   % (json.dumps(owner), json.dumps(short), fields)], cwd=repo, timeout=60)
        try:
            found = json.loads(raw)["data"]["repository"]
        except (TypeError, ValueError, KeyError):
            return False
        for n in batch:
            node = found.get("p" + n) or {}
            created = when(node.get("createdAt"))
            commits = [(c or {}).get("commit") or {}
                       for c in (node.get("commits") or {}).get("nodes") or []]
            size = [((c.get("additions") or 0) + (c.get("deletions") or 0), when(c.get("committedDate")))
                    for c in commits]
            pulls[n]["lines"] = sum(x for x, _ in size)
            pulls[n]["early"] = sum(x for x, at in size if created and at and at <= created)
    return True


def gh_review_rounds(repo, name, pulls, features, cache_path, limit=40):
    """{feature: {prs, rounds, threads, fixed, declined, open}} for each
    finished feature, all its pull requests together, or what was kept when
    GitHub cannot be asked.

    A round is one run of the automatic review, as review_report.py counts
    it for the report at the close of every round — not a session: one
    session can carry several rounds, and a feature reopened after its merge
    has rounds on each of its pull requests. A thread's fate is the report's
    too: fixed, closed with no fix (the author's decline), or still open. A
    feature's figures are kept once read, until a pull request of it is added.
    """
    import review_report  # noqa: E402 — pulls pr_context in; only needed here
    kept = load(cache_path, {})
    branches = {}
    for number, pr in pulls.items():
        feature = feature_of_branch(pr.get("branch"))
        if feature in features:
            branches.setdefault(pr["branch"], []).append(number)
    done = 0
    for branch, numbers in sorted(branches.items()):
        feature = feature_of_branch(branch)
        numbers = sorted(numbers, key=int)
        if (kept.get(feature) or {}).get("prs") == numbers or done >= limit:
            continue
        found = []
        for number in numbers:
            threads = review_report.threads(repo, number, name)
            if threads is None:
                save(cache_path, kept)
                return kept
            found += threads
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        found.sort(key=lambda t: t["created"] or epoch)
        runs = review_report.review_runs(repo, branch) or []
        fates = [t["fate"] for t in found]
        kept[feature] = {"prs": numbers, "rounds": len(review_report.rounds(found, runs)),
                         "threads": len(found), "fixed": fates.count("fixed"),
                         "declined": fates.count("no fix"), "open": fates.count("open")}
        done += 1
    save(cache_path, kept)
    return kept


ISSUE_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(last: 100, orderBy: {field: UPDATED_AT, direction: ASC}) {
      nodes {
        number createdAt closedAt state
        issueType { name }
        labels(first: 20) { nodes { name } }
        assignees(first: 1) { totalCount }
        parent { number }
        timelineItems(itemTypes: [REOPENED_EVENT]) { totalCount }
      }
    }
  }
}
"""


def gh_issues(repo, name):
    """{number: {created, closed, open, bug, assigned, parent, reopened}} of
    the latest issues, or None. A bug is an issue of type Bug or labelled
    with the word."""
    owner, _, short = name.partition("/")
    raw = run(["gh", "api", "graphql", "-f", "query=" + ISSUE_QUERY,
               "-F", "owner=" + owner, "-F", "name=" + short], cwd=repo, timeout=60)
    try:
        nodes = json.loads(raw)["data"]["repository"]["issues"]["nodes"]
    except (TypeError, ValueError, KeyError):
        return None
    out = {}
    for node in nodes or []:
        labels = [(x or {}).get("name") or "" for x in (node.get("labels") or {}).get("nodes") or []]
        kind = ((node.get("issueType") or {}).get("name") or "")
        out[str(node["number"])] = {
            "created": node.get("createdAt"),
            "closed": node.get("closedAt"),
            "open": node.get("state") == "OPEN",
            "bug": kind.lower() == "bug" or any("bug" in x.lower() for x in labels),
            "assigned": bool((node.get("assignees") or {}).get("totalCount")),
            "parent": (node.get("parent") or {}).get("number"),
            "reopened": (node.get("timelineItems") or {}).get("totalCount") or 0,
        }
    return out


def gh_incidents(repo, name):
    """[{issue, at}] — every rollback comment on the product's issues, or None.

    Searched by the heading, then confirmed by the marker: the search is
    fuzzy, the marker is not."""
    raw = run(["gh", "api", "-X", "GET", "search/issues", "-f",
               'q=repo:%s "%s" in:comments' % (name, ROLLBACK_HEADING),
               "-q", "[.items[].number]"], cwd=repo, timeout=60)
    try:
        numbers = json.loads(raw)
    except (TypeError, ValueError):
        return None
    out = []
    for number in numbers:
        raw = run(["gh", "api", "--paginate", "repos/%s/issues/%s/comments" % (name, number),
                   "-q", ".[] | select(.body | contains(%s)) | .created_at"
                   % json.dumps(ROLLBACK_MARKER)], cwd=repo, timeout=60)
        if raw is None:
            return None
        out.extend({"issue": number, "at": line.strip()}
                   for line in raw.splitlines() if line.strip())
    return out


def cycles(repo, pulls):
    """metrics.py's records of this product's finished features.

    The older records carry no repo. One of those is this product's when its
    pull request is one of ours and was opened from the feature's branch: the
    numbers alone would claim another product's features."""
    try:
        with open(log_path(), encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("repo"):
            if os.path.realpath(rec["repo"]) != os.path.realpath(repo):
                continue
        else:
            pr = pulls.get(str(rec.get("pr")))
            if not pr or not rec.get("feature") or \
                    not pr["branch"].endswith(str(rec["feature"])):
                continue
        out.append(rec)
    return out


def commits_first_shipped(repo, deploys):
    """{deploy uid: [(sha, author date, subject)]} — the commits each deploy put on
    production for the first time.

    Each deploy against every one before it, not against the previous alone:
    after a rollback the next deploy follows an older release, and `prev..sha`
    would count the rolled-back commits a second time. The oldest deploy has
    nothing before it to tell its own changes from all of history, so it gets
    none."""
    out, before = {}, []
    for dep in deploys:
        sha = dep.get("sha")
        if not sha or run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=repo) is None:
            continue
        if before:
            raw = run(["git", "rev-list", "--format=%H %aI %s", "--no-commit-header", sha,
                       "--not"] + before, cwd=repo)
            if raw is not None:
                out[dep["uid"]] = [tuple((line.split(" ", 2) + [""])[:3]) for line in raw.splitlines()
                                   if " " in line]
        before.append(sha)
    return out


# --- the numbers --------------------------------------------------------------

def deploy_time(dep):
    return when(dep.get("ready")) or when(dep.get("created"))


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
        raw = run(["git", "rev-list", sha + "^1.." + sha + "^2"], cwd=repo)
        for line in (raw or "").split():
            by_merge.setdefault(line, found)
    out = []
    shipped = commits_first_shipped(repo, deploys)
    for dep in deploys:
        at = deploy_time(dep)
        for sha, authored, subject in shipped.get(dep["uid"], []):
            num, pr = by_merge.get(sha, (None, None))
            start = when((pr or {}).get("first")) or when(authored)
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
    seen = sorted(t for t in (when(i.get("at")) for i in gh_found or []) if t)
    for rec in records:
        at = when((rec.get("rollback") or {}).get("at"))
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
    folder = out_dir(repo)
    os.makedirs(folder, exist_ok=True)
    notes = []

    kept = {d["uid"]: d for d in load(os.path.join(folder, "deployments.json"), [])
            if isinstance(d, dict) and d.get("uid")}
    fresh = vercel_deployments(repo)
    if fresh is None:
        notes.append("Vercel could not be asked; production deploys are the ones kept from earlier runs.")
    else:
        kept.update({d["uid"]: d for d in fresh if d.get("uid")})
        save(os.path.join(folder, "deployments.json"), list(kept.values()))

    pulls = load(os.path.join(folder, "pulls.json"), {})
    found = load(os.path.join(folder, "incidents.json"), [])
    issue_rows = load(os.path.join(folder, "issues.json"), {})
    name = gh_name(repo)
    if name is None:
        notes.append("GitHub could not be asked; pull requests and incidents are the ones kept from earlier runs.")
    else:
        got = gh_pulls(repo, name)
        if got is not None:
            for number, pr in got.items():
                pulls[number] = dict(pulls.get(number) or {}, **pr)
            gh_maturity(repo, name, pulls)
            save(os.path.join(folder, "pulls.json"), pulls)
        else:
            notes.append("GitHub did not list the pull requests this time.")
        got = gh_issues(repo, name)
        if got is not None:
            issue_rows.update(got)
            save(os.path.join(folder, "issues.json"), issue_rows)
        else:
            notes.append("GitHub did not list the issues this time.")
        got = gh_incidents(repo, name)
        if got is not None:
            found = got
            save(os.path.join(folder, "incidents.json"), found)
        else:
            notes.append("GitHub did not list the rollback comments this time.")

    records = cycles(repo, pulls)
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
                   for r in records if "prod" in (r.get("deployed") or []) and when(r.get("ended"))]
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
    review_rounds = gh_review_rounds(repo, name, pulls, finished,
                                     os.path.join(folder, "review-rounds.json")) \
        if name else load(os.path.join(folder, "review-rounds.json"), {})
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
        "features": [(r.get("feature") or "?", cycle_parts(r), when(r.get("ended")))
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
        return when(s.get("start"))

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

    merged = [p for p in pulls.values() if when(p.get("merged")) and when(p["merged"]) >= since]
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
    build_secs = [(when(b.get("ready")) - when(b.get("building"))).total_seconds()
                  for b in window_builds if when(b.get("ready")) and when(b.get("building"))]

    hist = dev_quality.history(repo, since)
    first = min((started(s) for s in mains if started(s)), default=None)
    hist_all = dev_quality.history(repo, first) if first else None
    window_cost = cost(recent)
    changed = ((hist or {}).get("added", 0) + (hist or {}).get("removed", 0))

    shipped_weeks = []
    for monday, _, _ in weekly(deploys, [], now):
        n = sum(1 for r in done if "prod" in (r.get("deployed") or [])
                and when(r.get("ended")) and monday <= when(r["ended"]) < monday + timedelta(weeks=1))
        shipped_weeks.append((monday, n, None))

    ai_figures = metrics_extra.ai(sessions, records, data.get("issues") or {}, hist, when, since, now)
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
                       and when(r.get("ended")) and when(r["ended"]) >= since),
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
                                        [w for w, _, _ in weekly(deploys, [], now)], when),
        "rounds_per_feature": metrics_extra.med([v["rounds"] for _, v in reviewed]),
        "threads_per_feature": metrics_extra.med([v["threads"] for _, v in reviewed]),
        "declined_share": ratio(sum(v["declined"] for _, v in reviewed), all_threads),
        "open_share": ratio(sum(v["open"] for _, v in reviewed), all_threads),
        "reviewed_features": reviewed[-10:], "reviewed_n": len(reviewed),
        "review_threads_all": all_threads,
        "dora": metrics_extra.dora_more(deploys, list(shipped), pulls, done, when, deploy_time,
                                        since, now),
        "devex": metrics_extra.devex(pulls, list(shipped), when, since, now),
        "software": metrics_extra.software(data.get("issues") or {}, list(shipped), pulls, done,
                                           list(failed), when, since,
                                           (hist_all or {}).get("added", 0) + (hist_all or {}).get("removed", 0)),
        "code": metrics_extra.code_health(repo),
        "hygiene": metrics_extra.hygiene(data.get("issues") or {}, pulls),
        "ai": ai_figures,
        "weekly": metrics_extra.weekly(sessions, [w for w, _, _ in weekly(deploys, [], now)], when),
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
        return when(r.get("ended"))
    shipped = [r for r in done if "prod" in (r.get("deployed") or []) and ended(r)]
    weekly_shipped, weekly_work, weekly_spend = [], [], []
    for monday, _, _ in weeks:
        end = monday + timedelta(weeks=1)
        units = sum(unit(r["feature"]) or 0 for r in shipped if monday <= ended(r) < end)
        active = {s.get("feature") for s in sessions
                  if when(s.get("start")) and monday <= when(s["start"]) < end}
        spend = sum(s.get("cost") or 0 for s in sessions
                    if when(s.get("start")) and monday <= when(s["start"]) < end)
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


# --- the page -----------------------------------------------------------------

def span(seconds):
    if seconds is None:
        return "—"
    if seconds < 3600:
        return "%d min" % max(1, round(seconds / 60))
    if seconds < 2 * DAY:
        return "%.1f h" % (seconds / 3600)
    return "%.1f days" % (seconds / DAY)


def esc(value):
    return html.escape(str(value), quote=True)


def stamp(at):
    return at.astimezone().strftime("%Y-%m-%d %H:%M") if at else "—"




STATUS_WORD = {"good": "Good", "watch": "Watch", "poor": "Poor"}
STATUS_ICON = {"good": "▲", "watch": "■", "poor": "▼"}
LEVEL_STATUS = {"Elite": "good", "High": "good", "Medium": "watch", "Low": "poor"}


SCALES = ("Scales with the feature's size. Per complexity divides it by the feature's "
          "size in standard features — its acceptance criteria, or its lines where it has "
          "none; 1 is the median finished feature.")


def tile(label, value, sub, lvl, delta, raw=None, mode="", scales=False):
    """One figure: its value, what it is, its colour — DORA's level where it
    has one, the guide's bands otherwise — and, on hover, why it matters,
    what to aim for and how it is counted (metrics_guide.py)."""
    status = LEVEL_STATUS.get(lvl) if lvl else metrics_guide.judge(label, raw)
    badge = ""
    if status:
        badge = "<span class='lvl %s'><i>%s</i>%s</span>" % (
            status, STATUS_ICON[status], lvl or STATUS_WORD[status])
    note = ""
    entry = metrics_guide.lookup(label)
    if entry:
        # Not shown in the tile: the page's script shows it on hover over the
        # tile, and on a tap where there is no hover.
        note = ("<div class=note hidden>"
                "<p><b>Why</b> %s</p><p><b>Aim</b> %s</p><p><b>How</b> %s</p>%s</div>"
                % (esc(entry[0]), esc(entry[1]), esc(entry[2]),
                   "<p><b>◆</b> %s</p>" % esc(SCALES) if scales else ""))
    mark = " <span class=scales title='%s'>◆</span>" % esc(SCALES) if scales else ""
    return ("<div class='tile%s%s'><div class=label>%s%s</div><div class=value>%s</div>"
            "<div class=sub>%s</div><div class=foot>%s<span class=delta>%s</span></div>%s</div>"
            % (" " + status if status else "", " " + mode if mode else "", esc(label), mark,
               esc(value), esc(sub), badge, esc(delta), note))


def delta_text(cur, prev, fmt):
    if cur is None or prev is None:
        return "no earlier 30 days to compare" if prev is None else ""
    if abs(cur - prev) < 1e-9:
        return "same as the 30 days before"
    word = "down" if cur < prev else "up"
    return "%s from %s the 30 days before" % (word, fmt(prev))


def short_span(seconds):
    """A duration for an axis tick, where there is room for four characters."""
    if seconds < 3600:
        return "%dm" % round(seconds / 60)
    if seconds < 2 * DAY:
        return "%dh" % round(seconds / 3600)
    return "%dd" % round(seconds / DAY)


def columns(weeks, pick, fmt, title):
    """Weekly columns as inline SVG, one series: the title names it."""
    # Drawn about as wide as it is shown, half a page, so its text keeps the
    # page's size rather than shrinking with the drawing.
    w, h, left, bottom, top = 440, 200, 44, 24, 16
    vals = [pick(wk) for wk in weeks]
    peak = max([v for v in vals if v is not None] or [0]) or 1
    step = nice_step(peak, fmt is span)
    peak = step * max(1, -(-peak // step))
    # Durations get a short tick; the bars' own labels keep the long form.
    tick_text = short_span if fmt is span else fmt
    band = (w - left - 8) / len(weeks)
    bar = min(24, band * 0.6)
    plot_h = h - bottom - top
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>" % (w, h, esc(title))]
    tick = 0
    while tick <= peak + 1e-9:
        y = top + plot_h - plot_h * tick / peak
        parts.append("<line class=grid x1=%d x2=%d y1=%.1f y2=%.1f />" % (left, w - 8, y, y))
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>"
                     % (left - 6, y + 4, esc(tick_text(tick) if tick else "0")))
        tick += step
    biggest = max(range(len(vals)), key=lambda i: vals[i] or 0)
    for i, (wk, v) in enumerate(zip(weeks, vals)):
        x = left + band * i + (band - bar) / 2
        label = wk[0].strftime("%d %b")
        if len(weeks) <= 6 or (len(weeks) - 1 - i) % 2 == 0:
            parts.append("<text class=tick x=%.1f y=%d text-anchor=middle>%s</text>"
                         % (x + bar / 2, h - 6, esc(label)))
        tip = "Week of %s · %s" % (label, fmt(v) if v is not None else "nothing shipped")
        parts.append("<rect class=hit x=%.1f y=%d width=%.1f height=%d data-tip='%s' tabindex=0 />"
                     % (left + band * i, top, band, plot_h, esc(tip)))
        if not v:
            continue
        bh = max(2, plot_h * v / peak)
        y = top + plot_h - bh
        r = min(4, bh / 2)
        parts.append("<path class=bar d='M%.1f %.1f v%.1f h%.1f v-%.1f a%.1f %.1f 0 0 0 -%.1f -%.1f "
                     "h-%.1f a%.1f %.1f 0 0 0 -%.1f %.1f z' />"
                     % (x, y + r, bh - r, bar, bh - r, r, r, r, r, bar - 2 * r, r, r, r, r))
        if i == biggest or i == len(weeks) - 1:
            parts.append("<text class=val x=%.1f y=%.1f text-anchor=middle>%s</text>"
                         % (x + bar / 2, y - 5, esc(fmt(v))))
    parts.append("<line class=axis x1=%d x2=%d y1=%d y2=%d /></svg>"
                 % (left, w - 8, top + plot_h, top + plot_h))
    return "".join(parts)


def nice_step(peak, duration=False):
    """A round tick step that splits `peak` into about four."""
    raw = peak / 4
    if raw <= 0:
        return 1
    if duration and peak > 3600:
        # Durations: hours, half-days, days, weeks.
        for s in (3600, 2 * 3600, 6 * 3600, 12 * 3600, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY):
            if raw <= s:
                return s
        return 30 * DAY
    if raw < 1:
        # A share or a small rate: tenths, quarters, halves.
        for m in (0.05, 0.1, 0.25, 0.5, 1):
            if raw <= m:
                return m
    mag = 10 ** len(str(int(raw))) / 10
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return max(1, int(m * mag))
    return max(1, int(raw))


def stacked(features):
    """One horizontal bar per finished feature, cut by where its time went."""
    if not features:
        return "<p class=empty>No finished feature of this product in sclaude's records yet.</p>"
    return stacked_rows([(name, part) for name, part, _ in reversed(features)],
                        PARTS, PART_NAMES, span, "Cycle time by step")


def stacked_rows(rows, keys, names, fmt, label):
    """One horizontal bar per (name, {key: value}) row, cut by `keys` in the
    categorical order, its total at the end."""
    if not rows:
        return "<p class=empty>Nothing recorded yet.</p>"
    w, left, right, rh = 900, 190, 80, 28
    h = len(rows) * rh + 8
    peak = max(sum(p.get(k) or 0 for k in keys) for _, p in rows) or 1
    plot = w - left - right
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>" % (w, h, esc(label))]
    for i, (name, part) in enumerate(rows):
        y = 4 + i * rh
        text = name if len(name) <= 24 else name[:23] + "…"
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>"
                     % (left - 8, y + 16, esc(text)))
        x = left
        for k, key in enumerate(keys):
            value = part.get(key) or 0
            if value <= 0:
                continue
            bw = plot * value / peak
            gap = 2 if bw > 3 else 0
            parts.append("<rect class='seg s%d' x=%.1f y=%d width=%.1f height=18 rx=%s "
                         "data-tip='%s' tabindex=0 />"
                         % (k + 1, x, y + 4, max(1, bw - gap), "2" if bw > 6 else "0",
                            esc("%s · %s: %s" % (name, names[key], fmt(value)))))
            x += bw
        parts.append("<text class=val x=%.1f y=%.1f>%s</text>"
                     % (x + 6, y + 17, esc(fmt(sum(part.get(k) or 0 for k in keys)))))
    parts.append("</svg>")
    legend = "".join("<span><i class='key s%d'></i>%s</span>" % (k + 1, esc(names[key]))
                     for k, key in enumerate(keys))
    return "<div class=legend>%s</div>%s" % (legend, "".join(parts))


STYLE = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--link:#1d4ed8}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--link:#93c5fd}}
:root[data-theme=dark]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;
--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;
--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--link:#93c5fd}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 40px;background:var(--page);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto}
h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:0 0 4px}
p{color:var(--ink2);margin:0 0 12px}a{color:var(--link)}
.lead{color:var(--muted);font-size:13px;margin-bottom:20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.tile,.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px}
.card{margin-bottom:16px}
.label{font-size:13px;color:var(--ink2)}
.value{font-size:30px;font-weight:600;line-height:1.2;margin:4px 0 2px}
.sub,.delta,.empty{font-size:12px;color:var(--muted)}
.foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
.lvl{font-size:12px;font-weight:600;color:var(--ink);display:inline-flex;gap:5px;align-items:center}
.lvl i{font-style:normal;font-size:10px}
.lvl.good i{color:var(--good)}.lvl.watch i{color:var(--warning)}.lvl.poor i{color:var(--critical)}
.tile.good{border-top:3px solid var(--good)}.tile.watch{border-top:3px solid var(--warning)}
.tile.poor{border-top:3px solid var(--critical)}
.note[hidden]{display:none}
svg{width:100%;height:auto;display:block}
svg text{font:11px system-ui,sans-serif}
.tick{fill:var(--muted);font-variant-numeric:tabular-nums}.val{fill:var(--ink2)}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.bar{fill:var(--s1)}.hit{fill:transparent}.hit:hover+.bar,.hit:focus+.bar{opacity:.8}
.s1{fill:var(--s1);background:var(--s1)}.s2{fill:var(--s2);background:var(--s2)}
.s3{fill:var(--s3);background:var(--s3)}.s4{fill:var(--s4);background:var(--s4)}
.s5{fill:var(--s5);background:var(--s5)}
.seg:hover,.seg:focus{opacity:.8;outline:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0 8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.key{display:inline-block;width:10px;height:10px;border-radius:2px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.two .card{margin-bottom:0}.two{margin-bottom:16px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{text-align:left;color:var(--muted);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--axis)}
td{padding:6px 8px;border-top:1px solid var(--grid);white-space:nowrap}
code{font-size:12px}
.bad{font-weight:600}.bad i{color:var(--critical);font-style:normal;margin-right:4px}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);
border:1px solid var(--ring);border-radius:6px;padding:4px 8px;font-size:12px;
box-shadow:0 2px 8px rgba(0,0,0,.15);display:none;z-index:9}
#tip.note{max-width:340px;padding:10px 12px;font-size:12.5px;line-height:1.45}
#tip.note b{display:block;margin-bottom:2px}
#tip.note p{margin:6px 0 0;color:var(--ink2)}
#tip.note p b{display:inline;color:var(--ink);margin:0}
.tile{cursor:help}
ul.notes{font-size:12px;color:var(--muted);padding-left:18px;margin:0}
h2.part{font-size:19px;margin:32px 0 2px;padding-top:16px;border-top:1px solid var(--grid)}
h3{font-size:15px;margin:0 0 4px}
.card .sub{margin:0 0 6px}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
background:var(--surface);border:1px solid var(--ring);border-radius:10px;overflow:hidden;margin:8px 0 8px}
.hero div{padding:14px 16px;box-shadow:0 0 0 .5px var(--grid)}
.hero b{display:block;font-size:28px;font-weight:600;line-height:1.15}
.hero span{font-size:12px;color:var(--ink2)}
.cell{fill:var(--grid)}
.area{fill:var(--s1);fill-opacity:.12;stroke:var(--s1);stroke-width:2;stroke-linejoin:round}
.dot{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.axis-name{fill:var(--ink2);font-weight:600;font-size:13px}
.team-table td,.team-table th{white-space:normal;vertical-align:top}
.team-table tr.group td{font-weight:600;color:var(--ink);padding-top:14px;border-top:0}
.team-table td.metric{color:var(--ink2);min-width:180px}
.cellv{display:flex;gap:6px;align-items:center}
.track{height:6px;background:var(--grid);border-radius:3px;margin-top:4px;min-width:90px}
.fill{height:6px;border-radius:3px}
.fill.s1,.seg.s1{background:var(--s1)}.fill.s2,.seg.s2{background:var(--s2)}
.fill.s3,.seg.s3{background:var(--s3)}.fill.s4,.seg.s4{background:var(--s4)}
.coach{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.coach-card{border:1px solid var(--ring);border-radius:8px;padding:10px 12px;font-size:12.5px}
.coach-head{display:flex;align-items:center;gap:4px;margin-bottom:4px}
.coach-score{margin-left:auto;color:var(--ink2);font-weight:600}
.coach-sub{margin:8px 0 2px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.coach-line{margin:3px 0 0;color:var(--ink)}
.coach-tip{margin:2px 0 6px 16px;color:var(--ink2)}
.stackrow{display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;margin:8px 0;font-size:12px}
.stacklabel{color:var(--ink2);text-align:right}
.stack{display:flex;height:16px;border-radius:4px;overflow:hidden;gap:2px;background:var(--surface)}
.radar-wrap{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px;align-items:center}
@media (max-width:760px){.radar-wrap{grid-template-columns:1fr}}
body{padding-left:252px}
#toc{position:fixed;top:0;left:0;bottom:0;width:232px;overflow:auto;padding:12px 10px 24px;
background:var(--surface);border-right:1px solid var(--grid);z-index:6;font-size:13px}
#toc ol{list-style:none;margin:10px 0 0;padding:0}
#toc a{display:block;padding:6px 10px;border-radius:6px;color:var(--ink2);text-decoration:none}
#toc a:hover{background:var(--grid)}
#toc a.here{color:var(--ink);background:var(--grid);font-weight:600}
#toc-fold{border:1px solid var(--ring);background:var(--surface);color:var(--ink);border-radius:6px;
font-size:16px;width:36px;height:32px;cursor:pointer}
:root[data-toc=folded] #toc{bottom:auto;width:auto;border:0;background:transparent;padding:10px}
:root[data-toc=folded] #toc ol{display:none}
:root[data-toc=folded] body{padding-left:16px}
section{scroll-margin-top:96px}
@media (max-width:1100px){body{padding-left:16px}
#toc{box-shadow:0 0 24px rgba(0,0,0,.2)}}
.switch{position:sticky;top:0;z-index:5;background:var(--page);padding:10px 0 8px;margin:0 0 4px;
border-bottom:1px solid var(--grid)}
.switch .sub{margin:6px 0 0}
.modes{display:inline-flex;border:1px solid var(--ring);border-radius:999px;padding:4px;
background:var(--surface)}
.modes button{font:600 16px system-ui,sans-serif;border:0;background:transparent;color:var(--ink2);
padding:10px 22px;border-radius:999px;cursor:pointer}
.modes button[aria-pressed=true]{background:var(--s1);color:#fff}
.norm{display:none}
:root[data-mode=norm] .norm{display:block}
:root[data-mode=norm] .abs{display:none}
.scales{color:var(--s1);font-size:12px}
"""

TIP_JS = """
(function(){var root=document.documentElement,key='sclaude-metrics-toc',fold=document.getElementById('toc-fold');
if(!fold)return;var narrow=window.matchMedia('(max-width:1100px)');
function set(folded){root.setAttribute('data-toc',folded?'folded':'open');
fold.setAttribute('aria-expanded',String(!folded));fold.title=folded?'Show the contents':'Fold the contents'}
var saved=null;try{saved=localStorage.getItem(key)}catch(e){}
set(narrow.matches?true:saved==='folded');
fold.addEventListener('click',function(){var folded=root.getAttribute('data-toc')!=='folded';set(folded);
if(!narrow.matches){try{localStorage.setItem(key,folded?'folded':'open')}catch(e){}}});
var links={};document.querySelectorAll('#toc a').forEach(function(a){links[a.getAttribute('href').slice(1)]=a;
a.addEventListener('click',function(){if(narrow.matches)set(true)})});
if('IntersectionObserver' in window){var seen={};
var io=new IntersectionObserver(function(es){es.forEach(function(e){seen[e.target.id]=e.isIntersecting});
var first=null;document.querySelectorAll('main section').forEach(function(sec){if(!first&&seen[sec.id])first=sec.id});
Object.keys(links).forEach(function(k){links[k].classList.toggle('here',k===first)})},{rootMargin:'-90px 0px -55% 0px'});
document.querySelectorAll('main section').forEach(function(sec){io.observe(sec)})}})();
(function(){var root=document.documentElement,key='sclaude-metrics-mode';
var buttons=document.querySelectorAll('.modes button');
function set(mode){root.setAttribute('data-mode',mode);
buttons.forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-mode')===mode))});
try{localStorage.setItem(key,mode)}catch(e){}}
var saved=null;try{saved=localStorage.getItem(key)}catch(e){}
set(saved==='norm'?'norm':'abs');
buttons.forEach(function(b){b.addEventListener('click',function(){set(b.getAttribute('data-mode'))})})})();
(function(){var t=document.getElementById('tip');
function place(r){var x=Math.min(r.x+14,window.innerWidth-t.offsetWidth-8);
var y=r.y-t.offsetHeight-12;if(y<8)y=r.y+18;
if(y+t.offsetHeight>window.innerHeight-8)y=Math.max(8,window.innerHeight-t.offsetHeight-8);
t.style.left=Math.max(8,x)+'px';t.style.top=y+'px'}
function at(e,el){return e.clientX!==undefined?{x:e.clientX,y:e.clientY}:
(function(b){return{x:b.left+b.width/2,y:b.top}})(el.getBoundingClientRect())}
function hide(){t.style.display='none';t.classList.remove('note')}
document.querySelectorAll('[data-tip]').forEach(function(el){
function show(e){t.classList.remove('note');t.textContent=el.getAttribute('data-tip');
t.style.display='block';place(at(e,el))}
el.addEventListener('pointermove',show);el.addEventListener('focus',function(){show({})});
['pointerleave','blur'].forEach(function(n){el.addEventListener(n,hide)})});
// A figure's note — why, aim, how — follows the pointer over whatever holds
// it: a tile, or a row the team part's script draws later. Delegated, so
// what is drawn after this runs has its note too; a tap opens it where there
// is no hover.
var open=null,shown=null;
function host(e){var h=e.target.closest&&e.target.closest('.tile,.hasnote');
return h&&h.querySelector('.note')?h:null}
function note(el){var info=el.querySelector('.note');var box=document.createElement('div');
var head=document.createElement('b');head.textContent=info.getAttribute('data-title')||
(el.querySelector('.label')||el).textContent;box.appendChild(head);
info.querySelectorAll('p').forEach(function(p){box.appendChild(p.cloneNode(true))});return box}
function showNote(e,el){if(e.target.closest('[data-tip]'))return;if(shown!==el){t.textContent='';
t.appendChild(note(el));shown=el}t.classList.add('note');t.style.display='block';place(at(e,el))}
document.addEventListener('pointermove',function(e){if(e.pointerType==='touch'||open)return;
var el=host(e);if(el)showNote(e,el);else if(shown){hide();shown=null}});
document.addEventListener('click',function(e){var el=host(e);
if(el&&open!==el){showNote(e,el);open=el;return}if(open){hide();open=null;shown=null}})})();
"""


# The team part's script: draws the simulated teammates from the base, keeps
# the draw in the browser, and lays the developers side by side.
TEAM_JS = """(function(){
var holder=document.getElementById('team');if(!holder)return;
var data=JSON.parse(document.getElementById('team-data').textContent);
var KEY='sclaude-team-factors-v1';
function load(k){try{return localStorage.getItem(k)}catch(e){return null}}
function store(k,v){try{localStorage.setItem(k,v)}catch(e){}}
var factors={};try{factors=JSON.parse(load(KEY)||'{}')||{}}catch(e){factors={}}
// One draw per teammate and figure, kept: the page shows the same team on
// every load until someone asks for another.
function draw(){var changed=false;data.others.forEach(function(d){factors[d]=factors[d]||{};
data.metrics.forEach(function(m){var p=m.profiles[d];if(!p||factors[d][m.key]!==undefined)return;
factors[d][m.key]=p[1]+Math.random()*(p[2]-p[1]);changed=true})});
if(changed)store(KEY,JSON.stringify(factors))}
draw();
function value(dev,m){if(dev===data.me)return m.value;var p=m.profiles[dev];
if(!p)return m.value;if(p[0]==='none')return null;var f=factors[dev][m.key];
if(p[0]==='abs')return f;if(m.value===null||m.value===undefined)return null;
var v=m.value*f;if(m.cap!==undefined&&m.cap!==null)v=Math.min(m.cap,v);
return m.fmt==='int'?Math.round(v):v}
function span(s){if(s===null||s===undefined)return '—';if(s<3600)return Math.max(1,Math.round(s/60))+' min';
if(s<172800)return (s/3600).toFixed(1)+' h';return (s/86400).toFixed(1)+' days'}
function compact(n){if(n===null||n===undefined)return '—';var a=Math.abs(n);
if(a>=1e6)return (n/1e6).toFixed(1)+'M';if(a>=1e4)return (n/1e3).toFixed(1)+'K';return Math.round(n).toLocaleString('en')}
function fmt(m,v){if(v===null||v===undefined||isNaN(v))return '—';
switch(m.fmt){case 'share':return Math.round(v*100)+'%';case 'span':return span(v);
case 'money':return '$'+(v>=100?Math.round(v).toLocaleString('en'):v.toFixed(2));
case 'dec1':return v.toFixed(1);case 'dec2':return v.toFixed(2);default:return compact(v)}}
function band(m,v){var b=m.band;if(!b||v===null||v===undefined)return null;var d;
if(b.kind==='lower')d=(v-b.a)/((b.b-b.a)||1);else if(b.kind==='higher')d=(b.a-v)/((b.a-b.b)||1);
else d=Math.max(b.a[0]-v,v-b.a[1])/(b.b||1);return d<=0?'good':d<=1?'watch':'poor'}
var ICON={good:'▲',watch:'■',poor:'▼'};
function score(m,v){var b=m.band;var d;if(b.kind==='lower')d=(v-b.a)/((b.b-b.a)||1);
else if(b.kind==='higher')d=(b.a-v)/((b.a-b.b)||1);else d=Math.max(b.a[0]-v,v-b.a[1])/(b.b||1);
return d<=0?100:Math.max(0,100-50*d)}
// The note the page's hover shows: why, aim, how — and, for a figure per
// person, where the other developers' data comes from.
function attach(host,title,n){if(!n)return;var box=el('div','note');box.hidden=true;
box.setAttribute('data-title',title);
[['Why',n[0]],['Aim',n[1]],['How',n[2]+' '+data.sources]].forEach(function(p){var para=el('p');
para.appendChild(el('b',null,p[0]));para.appendChild(document.createTextNode(' '+p[1]));box.appendChild(para)});
host.appendChild(box);host.classList.add('hasnote')}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;
if(text!==undefined)e.textContent=text;return e}
function render(){
holder.textContent='';var devs=[data.me].concat(data.others);

var vals={};devs.forEach(function(d){vals[d]={};data.metrics.forEach(function(m){vals[d][m.key]=value(d,m)})});
// Derived, from the drawn figures.
devs.forEach(function(d){var v=vals[d];v.leverage=v.person_hours?v.features/v.person_hours:null;
v.merge_freq=v.prs!==null?v.prs/(30/7):null});
// The team in four figures.
var total=function(k){return devs.reduce(function(a,d){return a+(vals[d][k]||0)},0)};
var commits=devs.map(function(d){return [d,vals[d].commits||0]}).sort(function(a,b){return b[1]-a[1]});
var half=total('commits')/2,acc=0,bus=0;commits.forEach(function(c){if(acc<half){acc+=c[1];bus++}});
var tiles=el('div','tiles');
[['Features finished, team',compact(total('features')),'by '+devs.length+' developers'],
 ['Lines changed, team',compact(total('lines')),'last 30 days'],
 ['Bus factor',String(bus),'developers who hold half of the commits'],
 ['Spend, team','$'+Math.round(total('spend')).toLocaleString('en'),'last 30 days']].forEach(function(t,i){
var tile=el('div','tile');tile.appendChild(el('div','label',t[0]));tile.appendChild(el('div','value',t[1]));
tile.appendChild(el('div','sub',t[2]));
attach(tile,t[0],data.notes[['team_features','team_lines','bus','team_spend'][i]]);tiles.appendChild(tile)});
holder.appendChild(tiles);
// The scorecard: a row a figure, a column a developer, a bar against the row's best.
var card=el('div','card');card.appendChild(el('h3',null,'Developers side by side'));
card.appendChild(el('p','sub','Each bar is against the longest in its row; the mark is the figure\\'s own bands, as everywhere on the page.'));
var wrap=el('div','scroll'),table=el('table','team-table'),head=el('tr');head.appendChild(el('th',null,''));
devs.forEach(function(d,i){var th=el('th');var key=el('i','key s'+(i+1));th.appendChild(key);
th.appendChild(document.createTextNode(' '+d));head.appendChild(th)});table.appendChild(head);
var extra=[{key:'leverage',label:'Features per person-hour',group:'Claude',fmt:'dec2',band:null},
{key:'merge_freq',label:'Merge frequency, per week',group:'Output',fmt:'dec1',band:data.mergeBand}];
var rows=data.metrics.filter(function(m){return !m.mix}).concat(extra),group=null;
rows.forEach(function(m){if(m.group!==group){group=m.group;var gr=el('tr','group');var td=el('td',null,group);
td.colSpan=devs.length+1;gr.appendChild(td);table.appendChild(gr)}
var tr=el('tr');var name=el('td','metric',m.label);tr.appendChild(name);
attach(tr,m.label,m.note||data.notes[m.key]);
var nums=devs.map(function(d){return vals[d][m.key]}).filter(function(v){return v!==null&&v!==undefined});
var max=Math.max.apply(null,nums.concat([0]))||1;
devs.forEach(function(d,i){var v=vals[d][m.key];var td=el('td','cell');
var line=el('div','cellv');line.appendChild(document.createTextNode(fmt(m,v)));
var st=band(m,v);if(st){var mark=el('span','lvl '+st);var ic=el('i',null,ICON[st]);mark.appendChild(ic);line.appendChild(mark)}
td.appendChild(line);if(v!==null&&v!==undefined){var track=el('div','track');var fill=el('div','fill s'+(i+1));
fill.style.width=Math.max(2,100*v/max)+'%';track.appendChild(fill);td.appendChild(track)}
tr.appendChild(td)});table.appendChild(tr)});
wrap.appendChild(table);card.appendChild(wrap);holder.appendChild(card);
// Who holds what: each developer's share of commits, lines and features.
var two=el('div','two');
var share=el('div','card');share.appendChild(el('h3',null,'Who holds what'));
share.appendChild(el('p','sub','each developer\\'s share of the team\\'s output, last 30 days'));
var legend=el('div','legend');devs.forEach(function(d,i){var s=el('span');s.appendChild(el('i','key s'+(i+1)));
s.appendChild(document.createTextNode(d));legend.appendChild(s)});share.appendChild(legend);
[['commits','Commits'],['lines','Lines changed'],['features','Features'],['bugs','Bugs fixed'],['spend','Spend']].forEach(function(k){
var t=total(k[0]);var row=el('div','stackrow');row.appendChild(el('span','stacklabel',k[1]));var st=el('div','stack');
devs.forEach(function(d,i){var v=vals[d][k[0]]||0;if(!t||!v)return;var seg=el('div','seg s'+(i+1));
seg.style.width=(100*v/t)+'%';seg.title=d+' · '+Math.round(100*v/t)+'%';st.appendChild(seg)});
row.appendChild(st);share.appendChild(row)});two.appendChild(share);
// What each one works on: the mix of their changes by kind.
var mix=el('div','card');mix.appendChild(el('h3',null,'What each one works on'));
mix.appendChild(el('p','sub','changes by kind, per developer'));
var kinds=data.metrics.filter(function(m){return m.mix});var leg2=el('div','legend');
kinds.forEach(function(m,i){var s=el('span');s.appendChild(el('i','key s'+(i+1)));s.appendChild(document.createTextNode(m.label));leg2.appendChild(s)});
mix.appendChild(leg2);
devs.forEach(function(d){var parts=kinds.map(function(m){return Math.max(0,vals[d][m.key]||0)});
var sum=parts.reduce(function(a,b){return a+b},0)||1;var row=el('div','stackrow');row.appendChild(el('span','stacklabel',d));
var st=el('div','stack');parts.forEach(function(p,i){if(!p)return;var seg=el('div','seg s'+(i+1));seg.style.width=(100*p/sum)+'%';
seg.title=d+' · '+kinds[i].label+' '+Math.round(100*p/sum)+'%';st.appendChild(seg)});row.appendChild(st);mix.appendChild(row)});
two.appendChild(mix);holder.appendChild(two);
// Strong and weak sides with Claude: each person's figures scored by their
// own bands, the best three and the three to work on, with a habit for each.
var coach=el('div','card');coach.appendChild(el('h3',null,'Working with Claude: strong sides and what to work on'));
coach.appendChild(el('p','sub','the adoption and effectiveness figures above, each scored 0–100 by its bands as on the radar; the AI score is their mean, and every weak side has a habit to try'));
var grid=el('div','coach');
devs.forEach(function(d,i){var scored=[];
data.metrics.forEach(function(m){if(['AI adoption','AI effectiveness'].indexOf(m.group)<0)return;
var v=vals[d][m.key];if(v===null||v===undefined||!m.band)return;scored.push([m,score(m,v),v])});
var mean=scored.length?scored.reduce(function(a,b){return a+b[1]},0)/scored.length:null;
var box=el('div','coach-card');var h=el('div','coach-head');h.appendChild(el('i','key s'+(i+1)));
h.appendChild(el('b',null,' '+d));h.appendChild(el('span','coach-score',mean===null?'':'AI score '+Math.round(mean)));box.appendChild(h);
var best=scored.slice().sort(function(a,b){return b[1]-a[1]}).filter(function(s){return s[1]>=75}).slice(0,3);
var worst=scored.slice().sort(function(a,b){return a[1]-b[1]}).filter(function(s){return s[1]<75}).slice(0,3);
box.appendChild(el('div','coach-sub','Strong'));
if(!best.length)box.appendChild(el('p','sub','nothing at the mark yet'));
best.forEach(function(s){var p=el('p','coach-line');var mk=el('span','lvl good');mk.appendChild(el('i',null,'▲'));
p.appendChild(mk);p.appendChild(document.createTextNode(' '+s[0].label+' · '+fmt(s[0],s[2])));box.appendChild(p)});
box.appendChild(el('div','coach-sub','To work on'));
if(!worst.length)box.appendChild(el('p','sub','nothing below the mark'));
worst.forEach(function(s){var st=s[1]>=50?'watch':'poor';var p=el('p','coach-line');var mk=el('span','lvl '+st);
mk.appendChild(el('i',null,ICON[st]));p.appendChild(mk);p.appendChild(document.createTextNode(' '+s[0].label+' · '+fmt(s[0],s[2])));
box.appendChild(p);if(data.tips[s[0].key])box.appendChild(el('p','coach-tip',data.tips[s[0].key]))});
grid.appendChild(box)});coach.appendChild(grid);holder.appendChild(coach)}
render()})();
"""


STEP_NAMES = {"plan": "Plan", "code": "Code", "pr": "Pull request", "review": "Review",
              "fix": "Regression fixes", "friction": "Friction reviews", "epilogue": "Epilogue",
              "retro": "Retrospective", "sync": "Sync with main", "status": "Status",
              "deferred": "Deferred review", "regression": "Regression", "manual": "By hand",
              "workshop": "sclaude workshop", "other": "Other"}
VERDICT_NAMES = {"deliberate": "every ban deliberate", "lifted": "a ban lifted",
                 "deferred": "put off", "mixed": "mixed", "unsaid": "no verdict"}
DENIAL_NAMES = {"permission-rule": "a permission rule", "user-rejected": "the person",
                "automode-blocked": "auto mode's check", "automode-unavailable": "auto mode unavailable"}


def compact(n):
    """1,284 · 12.9K · 4.2M · 2.7B."""
    if n is None:
        return "—"
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size * 10 or (abs(n) >= size and unit != "K"):
            return "%.1f%s" % (n / size, unit)
    return "{:,}".format(int(round(n)))


def money(x):
    if x is None:
        return "—"
    return "${:,.0f}".format(x) if x >= 100 else "${:,.2f}".format(x)


def share(x):
    return "—" if x is None else "%d%%" % round(x * 100)


def hbars(items, fmt, label="", width=440):
    """One horizontal bar per item, a single series: the card's title names
    it. `items` is [(name, value)]."""
    items = [(n, v) for n, v in items if v is not None]
    if not items:
        return "<p class=empty>Nothing recorded yet.</p>"
    left, right, rh = 150, 70, 26
    peak = max(v for _, v in items) or 1
    plot = width - left - right
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>"
             % (width, len(items) * rh + 4, esc(label))]
    for i, (name, value) in enumerate(items):
        y = 2 + i * rh
        text = name if len(name) <= 24 else name[:23] + "…"
        bw = max(2, plot * value / peak) if value else 0
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>"
                     % (left - 8, y + 15, esc(text)))
        if bw:
            parts.append("<rect class=bar x=%d y=%d width=%.1f height=14 rx=%s data-tip='%s' tabindex=0 />"
                         % (left, y + 4, bw, "3" if bw > 6 else "0", esc("%s · %s" % (name, fmt(value)))))
        parts.append("<text class=val x=%.1f y=%.1f>%s</text>" % (left + bw + 6, y + 15, esc(fmt(value))))
    parts.append("</svg>")
    return "".join(parts)


# What engineering scorecards usually ask for and this page cannot say, and
# why — so that a missing figure reads as a decision rather than an oversight.
NOT_MEASURED = (
    "Sprint velocity, predictability, capacity accuracy: no story points or sprints.",
    "Code reliability, maintainability, security, duplication, complexity: needs a "
    "static analyser's report.",
    "Code coverage: needs the test runner's coverage report.",
    "Technical debt in hours, estimation of issues: nothing is estimated.",
    "Uptime and MTTR of incidents outside a deploy: needs monitoring.",
    "Support, onboarding, SLA and compliance metrics: outside the development cycle.",
    "QA hand-backs: not yet recorded past the feature's life.",
)


def heatmap(grid):
    """Weekday × hour counts as a grid of one hue, deeper for more."""
    peak = max(max(row) for row in grid) or 1
    left, top, cw, ch = 40, 16, 35, 18
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='Sessions by weekday and hour'>"
             % (left + 24 * cw + 4, top + 7 * ch + 4)]
    for h in range(0, 24, 3):
        parts.append("<text class=tick x=%.1f y=11 text-anchor=middle>%02d</text>" % (left + h * cw + cw / 2, h))
    for d, row in enumerate(grid):
        y = top + d * ch
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>" % (left - 6, y + 13, days[d]))
        for h, n in enumerate(row):
            level = 0 if not n else 0.2 + 0.8 * n / peak
            parts.append("<rect x=%d y=%d width=%d height=%d rx=2 class='%s' style='opacity:%.2f' "
                         "data-tip='%s' tabindex=0 />"
                         % (left + h * cw + 1, y + 1, cw - 2, ch - 2, "bar" if n else "cell",
                            level or 1, esc("%s %02d:00 · %d sessions" % (days[d], h, n))))
    parts.append("</svg>")
    return "".join(parts)


def radar(axes, label):
    """The health radar: one spoke per axis, its score 0–100 out from the
    centre, the polygon the shape of the whole. `axes` is [(name, score or
    None, [(metric, score), …])]; an axis with nothing to stand on sits at the
    centre, named as such."""
    import math
    w, h, cx, cy, r = 660, 470, 330, 235, 165
    n = len(axes)

    def point(i, value, turn=0.0):
        angle = -math.pi / 2 + 2 * math.pi * (i + turn) / n
        return cx + r * value / 100 * math.cos(angle), cy + r * value / 100 * math.sin(angle)
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>" % (w, h, esc(label))]
    for ring in (25, 50, 75, 100):
        pts = " ".join("%.1f,%.1f" % point(i, ring) for i in range(n))
        parts.append("<polygon class=grid points='%s' fill=none />" % pts)
        # The ring's value between the first two spokes, clear of both.
        x, y = point(0, ring, 0.5)
        parts.append("<text class=tick x=%.1f y=%.1f text-anchor=middle>%d</text>" % (x, y + 3, ring))
    for i in range(n):
        x, y = point(i, 100)
        parts.append("<line class=grid x1=%d y1=%d x2=%.1f y2=%.1f />" % (cx, cy, x, y))
    shape = " ".join("%.1f,%.1f" % point(i, a[1] or 0) for i, a in enumerate(axes))
    parts.append("<polygon class=area points='%s' />" % shape)
    for i, (name, value, metrics) in enumerate(axes):
        x, y = point(i, value or 0)
        tip = "%s · %s — %s" % (name, "no data" if value is None else "%d of 100" % round(value),
                                "; ".join("%s %d" % (m, round(v)) for m, v in metrics) or "nothing measured")
        parts.append("<circle class=dot cx=%.1f cy=%.1f r=5 data-tip='%s' tabindex=0 />" % (x, y, esc(tip)))
        lx, ly = point(i, 118)
        anchor = "middle" if abs(lx - cx) < 20 else ("start" if lx > cx else "end")
        parts.append("<text class=axis-name x=%.1f y=%.1f text-anchor=%s>%s</text>"
                     % (lx, ly + 4, anchor, esc(name)))
        parts.append("<text class=tick x=%.1f y=%.1f text-anchor=%s>%s</text>"
                     % (lx, ly + 18, anchor, "no data" if value is None else "%d" % round(value)))
    parts.append("</svg>")
    return "".join(parts)


def health_of(axes):
    """The index — the mean of the axes — and the imbalance between the best
    and the worst, over the axes that have a score."""
    scored = [(n, v) for n, v, _ in axes if v is not None]
    if not scored:
        return None, None, None, None
    best = max(scored, key=lambda a: a[1])
    worst = min(scored, key=lambda a: a[1])
    return sum(v for _, v in scored) / len(scored), best[1] - worst[1], best, worst


def axis(name, metrics, mode):
    """One axis from [(label, absolute raw, per-complexity raw)]: the mean of
    its metrics' scores in the mode."""
    scored = []
    for label, raw_abs, raw_norm in metrics:
        raw = raw_norm if mode == "norm" else raw_abs
        value = metrics_guide.score(label, raw)
        if value is not None:
            scored.append((label, value))
    return (name, sum(v for _, v in scored) / len(scored) if scored else None, scored)


# The teammates the team part simulates, and how each differs from the one real
# developer: [mode, low, high] per figure — "x" multiplies the real figure by a
# draw between low and high, "abs" draws the figure itself, "none" has none.
# Alex and Anastasia write far more code than the base, Anastasia cleaner;
# Kris only fixes bugs.
SIMULATED = ("Alex", "Anastasia", "Kris")
PROFILES = {
    "features": {"Alex": ["x", 1.6, 2.2], "Anastasia": ["x", 1.4, 2.0], "Kris": ["abs", 0, 0]},
    "prs": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.5, 2.2], "Kris": ["x", 0.8, 1.4]},
    "commits": {"Alex": ["x", 2.0, 3.0], "Anastasia": ["x", 1.8, 2.6], "Kris": ["x", 0.6, 1.0]},
    "lines": {"Alex": ["x", 2.5, 4.0], "Anastasia": ["x", 2.0, 3.5], "Kris": ["x", 0.1, 0.25]},
    "bugs": {"Alex": ["x", 0.5, 0.9], "Anastasia": ["x", 0.4, 0.8], "Kris": ["x", 1.2, 1.8]},
    "cycle": {"Alex": ["x", 0.9, 1.3], "Anastasia": ["x", 0.8, 1.1], "Kris": ["none", 0, 0]},
    "lead": {"Alex": ["x", 1.0, 1.4], "Anastasia": ["x", 0.8, 1.1], "Kris": ["x", 0.3, 0.6]},
    "aging": {"Alex": ["x", 1.1, 1.5], "Anastasia": ["x", 0.8, 1.1], "Kris": ["x", 0.3, 0.6]},
    "pr_size": {"Alex": ["x", 1.8, 2.8], "Anastasia": ["x", 1.3, 2.0], "Kris": ["x", 0.1, 0.25]},
    "green": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.05, 1.3], "Kris": ["x", 0.9, 1.2]},
    "rounds": {"Alex": ["x", 1.2, 1.6], "Anastasia": ["x", 0.6, 0.9], "Kris": ["abs", 1, 3]},
    "threads": {"Alex": ["x", 1.3, 1.8], "Anastasia": ["x", 0.7, 1.0], "Kris": ["abs", 2, 8]},
    "escaped": {"Alex": ["abs", 0.05, 0.15], "Anastasia": ["abs", 0, 0.05], "Kris": ["abs", 0, 0.03]},
    "reopened": {"Alex": ["x", 1.0, 1.5], "Anastasia": ["x", 0.5, 0.9], "Kris": ["x", 0.6, 1.2]},
    "run": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 1.2, 1.6], "Kris": ["x", 0.6, 0.9]},
    "person_share": {"Alex": ["x", 0.8, 1.1], "Anastasia": ["x", 0.7, 0.95], "Kris": ["x", 1.1, 1.4]},
    "interventions": {"Alex": ["x", 1.1, 1.5], "Anastasia": ["x", 0.7, 1.0], "Kris": ["none", 0, 0]},
    "questions": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 0.6, 0.9], "Kris": ["none", 0, 0]},
    "sessions": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.6, 2.2], "Kris": ["x", 0.8, 1.2]},
    "person_hours": {"Alex": ["x", 1.6, 2.4], "Anastasia": ["x", 1.2, 1.8], "Kris": ["x", 0.8, 1.2]},
    "spend": {"Alex": ["x", 2.0, 3.0], "Anastasia": ["x", 1.6, 2.4], "Kris": ["x", 0.4, 0.7]},
    "spend_feature": {"Alex": ["x", 1.0, 1.4], "Anastasia": ["x", 0.8, 1.1], "Kris": ["none", 0, 0]},
    # Working with Claude. Alex uses it heavily and loosely; Anastasia is the
    # practised one; Kris is still taking it up.
    "ai_commits": {"Alex": ["x", 0.9, 1.05], "Anastasia": ["x", 0.95, 1.1], "Kris": ["x", 0.3, 0.5]},
    "sessions_week": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.6, 2.2], "Kris": ["x", 0.4, 0.7]},
    "tokens_week": {"Alex": ["x", 2.2, 3.2], "Anastasia": ["x", 1.4, 2.0], "Kris": ["x", 0.2, 0.4]},
    "subagents": {"Alex": ["x", 1.2, 1.8], "Anastasia": ["x", 1.5, 2.2], "Kris": ["x", 0.2, 0.5]},
    "skills": {"Alex": ["x", 0.5, 0.9], "Anastasia": ["x", 1.3, 2.0], "Kris": ["x", 0.3, 0.6]},
    "plan": {"Alex": ["x", 0.3, 0.7], "Anastasia": ["x", 1.5, 2.5], "Kris": ["abs", 0, 0.03]},
    "mcp": {"Alex": ["x", 0.8, 1.3], "Anastasia": ["x", 1.4, 2.2], "Kris": ["x", 0.5, 1.0]},
    "top_model": {"Alex": ["abs", 0.92, 0.99], "Anastasia": ["abs", 0.55, 0.75], "Kris": ["abs", 0.8, 0.95]},
    "cache": {"Alex": ["x", 0.85, 0.95], "Anastasia": ["x", 1.0, 1.03], "Kris": ["x", 0.75, 0.9]},
    "unattended": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.1, 1.3], "Kris": ["x", 0.5, 0.8]},
    "minutes_hour": {"Alex": ["x", 0.9, 1.2], "Anastasia": ["x", 0.6, 0.85], "Kris": ["x", 1.3, 1.8]},
    "rejected": {"Alex": ["x", 1.5, 2.5], "Anastasia": ["x", 0.4, 0.8], "Kris": ["x", 0.8, 1.2]},
    "refusals": {"Alex": ["x", 1.2, 1.8], "Anastasia": ["x", 0.6, 0.9], "Kris": ["x", 0.9, 1.4]},
    "compactions": {"Alex": ["x", 1.5, 2.5], "Anastasia": ["x", 0.6, 1.0], "Kris": ["x", 0.3, 0.7]},
    "thinking": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.0, 1.2], "Kris": ["x", 0.9, 1.1]},
    "kloc": {"Alex": ["x", 0.7, 1.0], "Anastasia": ["x", 0.6, 0.9], "Kris": ["x", 1.5, 2.5]},
    "mix_feat": {"Alex": ["x", 1.3, 1.6], "Anastasia": ["x", 1.2, 1.5], "Kris": ["abs", 0, 0.03]},
    "mix_fix": {"Alex": ["x", 0.6, 0.9], "Anastasia": ["x", 0.6, 0.9], "Kris": ["abs", 0.8, 0.9]},
    "mix_refactor": {"Alex": ["x", 0.8, 1.5], "Anastasia": ["x", 1.5, 2.5], "Kris": ["abs", 0.02, 0.06]},
    "mix_other": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 0.8, 1.2], "Kris": ["abs", 0.05, 0.1]},
}


def team_mode(repo):
    """`metricsTeam` for this machine: its own .sclaude/local/config.json
    first — outside git, so turning the demo on for one laptop does not turn
    it on for the team — then the product's committed config."""
    for path in (os.path.join(repo, ".sclaude", "local", "config.json"),
                 os.path.join(repo, ".sclaude", "config.json")):
        found = load(path, {})
        if isinstance(found, dict) and found.get("metricsTeam"):
            return found["metricsTeam"]
    return "real"


def team_section(x, cur, dv, sw, hm, ai, first_time, hist):
    """Developers side by side, for `metricsTeam: demo`: the real developer's
    figures are the product's — on one developer's product they are the same
    thing — and the generated teammates are drawn from them in the browser
    (TEAM_JS) by PROFILES, the draw kept per browser."""
    authors = sorted((hist.get("authors") or {}).items(), key=lambda kv: -kv[1]["commits"])
    me = authors[0][0] if authors else "You"
    types = dict(sw["types"])
    changes = sum(types.values()) or 1
    uses = dict(ai["uses"])
    spend_by_model = x["models"] or {}
    top_model = ratio(sum(v for k, v in spend_by_model.items() if "opus" in k.lower()),
                      sum(spend_by_model.values()))

    def kind(*names):
        return sum(types.get(n, 0) for n in names) / changes
    rows = [
        ("features", "Features finished", "Output", "int", x["done"], None),
        ("prs", "Pull requests merged", "Output", "int", x["merged"], None),
        ("commits", "Commits", "Output", "int", hist.get("commits"), None),
        ("lines", "Lines changed", "Output", "int", (hist.get("added") or 0) + (hist.get("removed") or 0), None),
        ("bugs", "Bugs fixed", "Output", "int", types.get("fix", 0), None),
        ("cycle", "Feature cycle time", "Speed", "span", x["cycle"], None),
        ("lead", "Lead time for changes", "Speed", "span", cur["lead"], None),
        ("aging", "PR aging", "Speed", "span", dv["aging"], None),
        ("pr_size", "Pull request size", "Speed", "int", x["pr_size"], None),
        ("green", "Regression green first time", "Quality", "share", first_time, 1.0),
        ("rounds", "Review rounds per feature", "Quality", "dec1", x["rounds_per_feature"], None),
        ("threads", "Review threads per feature", "Quality", "int", x["threads_per_feature"], None),
        ("escaped", "Escaped defects", "Quality", "share", sw["escaped"], 1.0),
        ("reopened", "Reopened issues", "Quality", "share", sw["reopened"], 1.0),
        ("ai_commits", "Commits written by Claude", "AI adoption", "share",
         ratio(hist.get("by_claude"), hist.get("commits")), 1.0),
        ("sessions", "Sessions, last 30 days", "AI adoption", "int", x["sessions_recent"], None),
        ("sessions_week", "Sessions per week", "AI adoption", "dec1", ai["sessions_per_week"], None),
        ("tokens_week", "Tokens per week", "AI adoption", "int", ai["tokens_per_week"], None),
        ("person_hours", "Person's hours with Claude", "AI adoption", "dec1", hm["person_s"] / 3600, None),
        ("subagents", "Subagent use", "AI adoption", "share", uses.get("Subagents"), 1.0),
        ("skills", "Skill use", "AI adoption", "share", uses.get("Skills"), 1.0),
        ("plan", "Plan mode use", "AI adoption", "share", uses.get("Plan mode"), 1.0),
        ("mcp", "MCP tool use", "AI adoption", "share", uses.get("MCP tools"), 1.0),
        ("top_model", "Top-model share of spend", "AI adoption", "share", top_model, 1.0),
        ("cache", "Cache hit rate", "AI effectiveness", "share", x["cache_hit"], 0.995),
        ("run", "Claude's run between interventions", "AI effectiveness", "dec1", hm["run_calls"], None),
        ("unattended", "Sessions with no one stepping in", "AI effectiveness", "share", hm["unattended"], 0.98),
        ("person_share", "Person's share of the time", "AI effectiveness", "share", hm["person_share"], 0.95),
        ("minutes_hour", "Person's minutes per hour of Claude", "AI effectiveness", "dec1",
         hm["minutes_per_hour"], None),
        ("interventions", "Interventions per feature", "AI effectiveness", "dec1", hm["turns_per_feature"], None),
        ("questions", "Questions per feature", "AI effectiveness", "dec1", ai["questions_per_feature"], None),
        ("rejected", "Actions turned down per 100 calls", "AI effectiveness", "dec2",
         ratio(100 * x["denials"].get("user-rejected", 0), x["tool_calls"]), None),
        ("refusals", "Refusals per 100 calls", "AI effectiveness", "dec2",
         ratio(100 * sum(x["denials"].values()), x["tool_calls"]), None),
        ("compactions", "Compactions per 100 sessions", "AI effectiveness", "dec1",
         ratio(100 * x["compactions"], x["sessions"]), None),
        ("thinking", "Thinking", "AI effectiveness", "share", x["thinking_share"], 1.0),
        ("spend", "Spend, last 30 days", "Cost", "money", x["cost_recent"], None),
        ("spend_feature", "Spend per feature", "Cost", "money", x["per_feature"], None),
        ("kloc", "Per 1,000 lines changed", "Cost", "money", x["per_kloc"], None),
    ]
    metrics = [{"key": k, "label": label, "group": group, "fmt": f, "value": v, "cap": cap,
                "band": metrics_guide.spec(label), "profiles": PROFILES.get(k, {})}
               for k, label, group, f, v, cap in rows]
    for key, label, share_ in (("mix_feat", "Features", kind("feat", "perf")),
                               ("mix_fix", "Fixes", kind("fix", "hotfix", "revert")),
                               ("mix_refactor", "Refactoring", kind("refactor")),
                               ("mix_other", "Everything else", 1 - kind("feat", "perf", "fix", "hotfix",
                                                                        "revert", "refactor"))):
        metrics.append({"key": key, "label": label, "group": "Mix", "fmt": "share", "value": share_,
                        "cap": None, "band": None, "profiles": PROFILES[key], "mix": True})
    for m in metrics:
        m["note"] = metrics_guide.TEAM_GUIDE.get(m["key"])
    data = json.dumps({"me": me, "others": list(SIMULATED), "metrics": metrics,
                       "mergeBand": metrics_guide.spec("Merge frequency"),
                       "notes": metrics_guide.TEAM_GUIDE, "sources": metrics_guide.TEAM_SOURCES,
                       "tips": metrics_guide.TEAM_TIPS}).replace("</", "<\\/")
    return section(
        "team", "Team", "Developers side by side, over the last %d days." % WINDOW,
        "<div id=team></div><script type=application/json id=team-data>%s</script>" % data)


def hero(items):
    return "<div class=hero>%s</div>" % "".join(
        "<div><b>%s</b><span>%s</span></div>" % (esc(v), esc(k)) for v, k in items)


def section(key, title, lead, *blocks):
    """A part of the page, with the id the table of contents links to."""
    return "<section id='%s'><h2 class=part>%s</h2><p>%s</p>%s</section>" % (
        esc(key), esc(title), esc(lead), "".join(blocks))


def contents(parts):
    """The table of contents: [(id, title)], folded away with its button."""
    return ("<nav id=toc aria-label='Contents'><button type=button id=toc-fold "
            "aria-expanded=true title='Fold the contents'>☰</button><ol>%s</ol></nav>"
            % "".join("<li><a href='#%s'>%s</a></li>" % (esc(k), esc(t)) for k, t in parts))


def card(title, body, note="", mode=""):
    mark = " <span class=scales title='%s'>◆</span>" % esc(SCALES) if mode else ""
    return "<div class='card%s'><h3>%s%s</h3>%s%s</div>" % (
        " " + mode if mode else "", esc(title), mark, "<p class=sub>%s</p>" % esc(note) if note else "", body)


def dual(absolute, normalised):
    """A chart drawn both ways: (title, body, note) each, the switch showing
    one."""
    return card(*absolute, mode="abs") + card(*normalised, mode="norm")


def tiles(*items):
    """Each item is (label, value, sub), (label, value, sub, raw) — raw being
    the number the guide colours by — or DORA's (label, value, sub, level,
    delta); or a figure that scales with a feature's size, as
    {"abs": item, "norm": item}: both are drawn, and the page's switch shows
    one."""
    def one(i, mode="", scales=False):
        if len(i) == 5:
            return tile(*i, mode=mode, scales=scales)
        return tile(i[0], i[1], i[2], None, "", i[3] if len(i) > 3 else None, mode, scales)
    return "<div class=tiles>%s</div>" % "".join(
        one(i["abs"], "abs", True) + one(i["norm"], "norm", True) if isinstance(i, dict) else one(i)
        for i in items)


def render(repo, data, m):
    cur, prev = m["current"], m["previous"]
    x = m["more"]
    name = data.get("github") or os.path.basename(os.path.realpath(repo))
    per_week = cur["per_day"] * 7
    tok = x["tokens"]
    hist = x["history"] or {}
    hist_all = x["history_all"] or {}
    reg = x["regression"]
    fr = x["friction"]
    dm, dv, sw, ai, wk = x["dora"], x["devex"], x["software"], x["ai"], x["weekly"]
    nm = x["norm"]
    size_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%.1f</td><td>%s</td></tr>"
        % (esc(f), compact(v["criteria"]), compact(v["lines"]), v["unit"],
           "criteria" if v["source"] == "criteria" else "lines, at the median rate")
        for f, v in sorted(nm["sizes"].items(), key=lambda kv: -kv[1]["unit"]))
    sizes_card = card("How big each finished feature was", (
        "<div class=scroll><table><tr><th>Feature</th><th>Criteria</th><th>Lines</th>"
        "<th>Standard features</th><th>Sized by</th></tr>%s</table></div>" % size_rows)
        if size_rows else "<p class=empty>No finished feature could be sized yet.</p>",
        "A standard feature is the median: %s acceptance criteria. %d of %d finished features sized."
        % (compact(nm["standard"]), nm["sized"], nm["features"]))
    people_rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>"
        % (esc(n), a["commits"], compact(a["lines"]), share(ratio(a["by_claude"], a["commits"])))
        for n, a in sorted((hist.get("authors") or {}).items(), key=lambda kv: -kv[1]["commits"]))
    people = ("<div class=scroll><table><tr><th>Author</th><th>Commits</th><th>Lines</th>"
              "<th>By Claude</th></tr>%s</table></div>" % people_rows) if people_rows \
        else "<p class=empty>No commits in the last %d days.</p>" % WINDOW

    hm = x["human"]
    head = hero([
        (compact(x["sessions"]), "Claude sessions, and %s subagents" % compact(x["subagents"])),
        (compact(sum(tok.values()) - tok["thinking"]), "tokens processed"),
        (money(x["cost"]), "spent by Claude Code, as it counted"),
        (compact(x["tool_calls"]), "tool calls"),
        (share(ratio(hist_all.get("by_claude"), hist_all.get("commits"))), "of commits written by Claude"),
        (compact(x["lines_by_claude"]), "lines Claude edited"),
        ("—" if hm["run_calls"] is None else "%.0f" % hm["run_calls"],
         "actions Claude takes between a person's interventions"),
        (share(hm["unattended"]), "of sclaude's sessions ran with no one stepping in"),
        ("—" if hm["minutes_per_hour"] is None else "%.0f min" % hm["minutes_per_hour"],
         "of a person per hour of Claude's work"),
        (compact(m["total_deploys"]), "production deploys"),
        (compact(x["done"]), "features finished"),
        (compact(x["review_comments"]), "review threads answered"),
        (compact(x["criteria"]), "acceptance criteria written"),
        (compact(sum(r["runs"] for r in reg.values())), "regression stages run"),
        (compact(fr["reviews"] + x["deferred"]), "friction reviews and entries"),
        (share(x["cache_hit"]), "of input from the prompt cache"),
    ])
    overview = section("overview", "Overview", "What sclaude has counted for this product.", head)

    dora = section(
        "dora", "Delivery performance (DORA)",
        "The four keys of delivery performance, over the last %d days, and the rest of DORA's "
        "picture." % WINDOW,
        tiles(
            ("Deployment frequency", "%.1f / week" % per_week,
             "%d production deploys in the last %d days" % (cur["deploys"], WINDOW),
             level("frequency", cur["per_day"]) if cur["deploys"] else "Low",
             delta_text(per_week, prev["per_day"] * 7 if prev["deploys"] else None,
                        lambda v: "%.1f" % v)),
            ("Lead time for changes", span(cur["lead"]),
             "median, first commit to production · %d changes" % cur["changes"],
             level("lead", cur["lead"]), delta_text(cur["lead"], prev["lead"], span)),
            ("Change failure rate",
             "—" if cur["failure"] is None else "%d%%" % round(cur["failure"] * 100),
             "%d of %d deploys rolled back" % (cur["failed"], cur["deploys"]),
             level("failure", cur["failure"]),
             delta_text(cur["failure"], prev["failure"], lambda v: "%d%%" % round(v * 100))),
            ("Time to restore", span(cur["restore"]) if cur["incidents"] else "no failures",
             "median, failed deploy to rollback · %d incidents" % cur["incidents"],
             level("restore", cur["restore"]),
             delta_text(cur["restore"], prev["restore"], span) if cur["incidents"] else "")),
        tiles(
            ("Rework rate", share(dm["rework"]),
             "deploys that only fixed what was out · %d" % dm["rework_n"], dm["rework"]),
            ("Hotfix rate", share(dm["hotfix"]),
             "deploys followed within a day by a fix · %d" % dm["hotfix_n"], dm["hotfix"]),
            ("Lead time, 90th percentile", span(dm["lead_p90"]), "the slow tail of changes", dm["lead_p90"]),
            ("Batch size", compact(dm["batch"]), "median changes per deploy", dm["batch"]),
            ("Days with a deploy", share(dm["deploy_days"]), "of the last %d" % WINDOW, dm["deploy_days"]),
            ("Time between deploys", span(dm["interval"]), "median", dm["interval"]),
            ("Production suite green", share(dm["reliability"]),
             "after %d production deploys — reliability's stand-in" % dm["reliability_n"],
             dm["reliability"])),
        "<div class=two>%s%s</div>" % (
            card("Production deploys per week",
                 columns(m["weeks"], lambda w: w[1], lambda v: str(int(v)), "Production deploys per week")),
            card("Median lead time per week",
                 columns(m["weeks"], lambda w: w[2], span, "Median lead time per week"))),
        "<div class=two>%s%s</div>" % (
            card("Lead time, cut by stage",
                 hbars([("Coding", dm["coding"]), ("Review", dm["review"]), ("Deploy", dm["deploy"])],
                       span, "Lead time by stage"),
                 "median per change: first commit to PR, PR to merge, merge to production"),
            card("Lead time, by path",
                 hbars([("Through a pull request", dm["lead_pr"]), ("Straight to main", dm["lead_direct"])],
                       span, "Lead time by path"), "median per change")))

    flow = section(
        "flow", "Flow of work", "What the cycle turns out, how long a feature takes, and how much waits.",
        tiles(
            {"abs": ("Features shipped", compact(x["shipped"]), "reached production in the last %d days" % WINDOW),
             "norm": ("Features shipped", "%.1f" % nm["shipped"],
                      "standard features reached production in the last %d days" % WINDOW)},
            {"abs": ("Feature cycle time", span(x["cycle"]),
                     "median, plan to production, %d features" % x["done"], x["cycle"]),
             "norm": ("Feature cycle time", span(nm["cycle"]), "median per standard feature", nm["cycle"])},
            {"abs": ("Time to market", span(ai["market"]), "median, issue opened to production", ai["market"]),
             "norm": ("Time to market", span(nm["market"]), "median per standard feature", nm["market"])},
            ("Time in the queue", span(ai["queue"]), "median, issue opened to its first session", ai["queue"]),
            ("Flow efficiency", share(ai["flow"]), "of a feature's cycle with Claude at work", ai["flow"]),
            ("Features at once", compact(ai["concurrent_max"]),
             "most on one day · median %s" % compact(ai["concurrent_median"]), ai["concurrent_max"]),
            ("Pull requests per feature", "—" if x["prs_per_feature"] is None else "%.1f" % x["prs_per_feature"],
             "%d features needed more than one" % x["reworked"], x["prs_per_feature"]),
            ("Features dropped", share(ratio(x["dropped"], x["done"] + x["dropped"])),
             "%d of %d started, all time" % (x["dropped"], x["done"] + x["dropped"]),
             ratio(x["dropped"], x["done"] + x["dropped"]))),
        "<div class=two>%s%s</div>" % (
            dual(("Features shipped per week",
                  columns(x["shipped_weeks"], lambda w: w[1], lambda v: str(int(v)), "Features shipped per week"), ""),
                 ("Standard features shipped per week",
                  columns(nm["weekly_shipped"], lambda w: w[1], lambda v: "%.1f" % v,
                          "Standard features shipped per week"), "each feature weighted by its size")),
            dual(("Features in work per week",
                  columns(wk, lambda w: w[4], lambda v: str(int(v)), "Features in work per week"), ""),
                 ("Standard features in work per week",
                  columns(nm["weekly_work"], lambda w: w[1], lambda v: "%.1f" % v,
                          "Standard features in work per week"),
                  "finished features only: one in progress has no size yet"))),
        dual(("Where a feature's time goes", stacked(m["features"]),
              "The last finished features, by step. Review includes waiting for QA."),
             ("Where a feature's time goes, per standard feature", stacked(nm["features_time"]),
              "each feature's steps divided by its size")),
        sizes_card)

    prs = section(
        "prs", "Pull requests and builds", "Where a pull request waits, from first commit to production.",
        tiles(
            ("Coding time", span(dv["coding"]), "first commit to PR opened", dv["coding"]),
            ("Pickup time", span(dv["pickup"]), "PR opened to its first review answer", dv["pickup"]),
            ("Approve time", span(dv["approve"]) if dv["approvals"] else "—",
             "first answer to approval" if dv["approvals"]
             else "no approvals: the person merges after the review", dv["approve"]),
            ("Merge time", span(dv["merge"]), "approval, or first answer, to merge", dv["merge"]),
            ("Review time", span(dv["review"]), "PR opened to approval or merge", dv["review"]),
            ("Deploy time", span(dv["deploy"]), "merge to production", dv["deploy"]),
            ("PR aging", span(dv["aging"]), "PR opened to merged", dv["aging"]),
            ("Merge frequency", "—" if dv["merge_frequency"] is None else "%.1f / week" % dv["merge_frequency"],
             "merged PRs per author · %d authors" % dv["authors"], dv["merge_frequency"]),
            ("Pull request size", compact(x["pr_size"]), "median lines changed, %d merged" % x["merged"],
             x["pr_size"]),
            ("PR maturity", share(dv["maturity"]), "of its lines written before it was opened", dv["maturity"]),
            ("PRs without review", share(dv["unreviewed"]), "merged with no answer at all", dv["unreviewed"]),
            ("Builds", compact(x["builds"]), "%d previews · %d failed" % (x["previews"], x["build_errors"]),
             ratio(x["build_errors"], x["builds"])),
            ("Build time", span(x["build_time"]), "median, on Vercel", x["build_time"])),
        card("A pull request's way, median",
             hbars([("Coding", dv["coding"]), ("Pickup", dv["pickup"]), ("Approve", dv["approve"]),
                    ("Merge", dv["merge"]), ("Deploy", dv["deploy"])], span, "PR stages", width=900),
             "over the %d pull requests merged in the last %d days" % (dv["merged"], WINDOW)))

    rq = x["requirements"]
    sizes = nm["sizes"]
    requirements = section(
        "requirements", "Requirements", "Whether features started from requirements that said enough, and held.",
        tiles(
            ("Requirements changed in development", share(rq["significant"]),
             "%d of %d features · any change in %s" % (rq["significant_n"], rq["covered"], share(rq["changed"])),
             rq["significant"]),
            ("Requirements added in development", compact(rq["added"]),
             "median %s per feature, under the request's \"Added during development\""
             % compact(rq["added_median"])),
            ("Requirements unclear at the start", share(rq["unclear"]),
             "%d of %d features needed a question per criterion or more in planning"
             % (rq["unclear_n"], rq["planned"]), rq["unclear"]),
            ("Questions per criterion", "—" if rq["per_criterion"] is None else "%.2f" % rq["per_criterion"],
             "median, clarifying questions in planning over acceptance criteria", rq["per_criterion"]),
            {"abs": ("Clarifying questions in planning", compact(rq["questions"]), "median per feature",
                     rq["questions"]),
             "norm": ("Clarifying questions in planning",
                      "—" if rq["questions_norm"] is None else "%.1f" % rq["questions_norm"],
                      "median per standard feature", rq["questions_norm"])},
            ("Request grew in planning", "—" if rq["growth"] is None else "%.1f×" % rq["growth"],
             "the agreed request against the issue's description, in words", rq["growth"]),
            ("Acceptance criteria", compact(x["criteria"]),
             "on %d issues · %s ticked by QA" % (x["criteria_issues"],
                                                 share(ratio(x["criteria_ticked"], x["criteria"]))),
             ratio(x["criteria_ticked"], x["criteria"]))),
        "<div class=two>%s%s</div>" % (
            card("How much the requirements moved, per feature",
                 hbars([(f, mv["change"]) for f, mv, _ in reversed(rq["rows"]) if mv], share,
                       "Requirements moved"),
                 "share of the description, request and criteria rewritten after the plan was "
                 "approved; ticks in the criteria's boxes do not count"),
            dual(("Clarifying questions in planning, per feature",
                  hbars([(f, q) for f, q in reversed(rq["questions_by"])], compact, "Questions"),
                  "each question of Claude's AskUserQuestion in the feature's plan sessions"),
                 ("Clarifying questions in planning, per standard feature",
                  hbars([(f, q / sizes[f]["unit"]) for f, q in reversed(rq["questions_by"]) if f in sizes],
                        lambda v: "%.1f" % v, "Questions per standard feature"),
                  "each feature's questions divided by its size"))))

    stage_rates = [("%s · %d runs" % (st.capitalize(), r["runs"]), ratio(r["first_pass"], r["runs"]))
                   for st, r in reg.items() if r["runs"]]
    first_time = ratio(sum(r["first_pass"] for r in reg.values()), sum(r["runs"] for r in reg.values()))
    testing = section(
        "testing", "Testing", "Whether the code was right before the suite ran, and what got past it.",
        tiles(
            ("Regression green first time", share(first_time), "stages that passed with no fixing session",
             first_time),
            ("Fixing sessions", compact(sum(r["fixes"] for r in reg.values())),
             "%d of them left the suite red" % sum(r["red_fixes"] for r in reg.values())),
            ("Escaped defects", share(sw["escaped"]), "of what the regression found, found in production",
             sw["escaped"]),
            ("Tests in new lines", share(ratio(hist.get("test_added"), hist.get("added"))),
             "%s lines of tests added" % compact(hist.get("test_added")),
             ratio(hist.get("test_added"), hist.get("added")))),
        "<div class=two>%s%s</div>" % (
            card("Green first time, by regression stage", hbars(stage_rates, share, "First-pass rate")),
            card("Where the regression found something",
                 hbars([("Local", sw["found"]["local"]), ("Preview", sw["found"]["preview"]),
                        ("Production", sw["found"]["prod"])], compact, "Defects found by stage"),
                 "features whose stage needed a fix, and production rollbacks")))

    review = section(
        "review", "Code review", "How much the review found, how many rounds it took, and what became of it.",
        tiles(
            {"abs": ("Review rounds per feature", compact(x["rounds_per_feature"]),
                     "median · runs of the review, not sessions · %d features" % x["reviewed_n"],
                     x["rounds_per_feature"]),
             "norm": ("Review rounds per feature", "—" if nm["rounds"] is None else "%.1f" % nm["rounds"],
                      "median per standard feature", nm["rounds"])},
            {"abs": ("Review threads per feature", compact(x["threads_per_feature"]),
                     "median · %s threads in all" % compact(x["review_threads_all"]), x["threads_per_feature"]),
             "norm": ("Review threads per feature", "—" if nm["threads"] is None else "%.0f" % nm["threads"],
                      "median per standard feature", nm["threads"])},
            ("Review threads per PR", compact(x["threads_per_pr"]),
             "median · %s threads on %d merged PRs" % (compact(x["threads"]), x["merged"]), x["threads_per_pr"]),
            ("Threads closed without a fix", share(x["declined_share"]), "declined by the author",
             x["declined_share"]),
            ("Threads still open", share(x["open_share"]), "neither fixed nor declined", x["open_share"]),
            ("Review threads resolved", share(dv["resolved"]), "of %s threads" % compact(x["threads"]),
             dv["resolved"])),
        "<div class=two>%s%s</div>" % (
            dual(("Review rounds per feature",
                  hbars([(f, v["rounds"]) for f, v in reversed(x["reviewed_features"])], compact,
                        "Review rounds per feature"),
                  "runs of the automatic review over all the feature's pull requests"),
                 ("Review rounds per standard feature",
                  hbars([(f, v["rounds"]) for f, v in reversed(nm["reviewed"][-10:])], lambda v: "%.1f" % v,
                        "Review rounds per standard feature"), "each feature's rounds divided by its size")),
            card("Review sessions",
                 hbars([("Sessions", x["review_sessions"]), ("Rounds they handed back", x["review_rounds"]),
                        ("Findings declined as reversals", x["reversals"])], compact, "Review sessions"),
                 "from the review log: one session can carry several rounds")),
        dual(("Review threads per feature, by what became of them",
              stacked_rows([(f, {"fixed": v["fixed"], "declined": v["declined"], "open": v["open"]})
                            for f, v in reversed(x["reviewed_features"])],
                           ("fixed", "declined", "open"),
                           {"fixed": "Fixed", "declined": "Closed without a fix", "open": "Still open"},
                           compact, "Threads by fate"), ""),
             ("Review threads per standard feature, by what became of them",
              stacked_rows([(f, {k: v[k] for k in ("fixed", "declined", "open")})
                            for f, v in reversed(nm["reviewed"][-10:])],
                           ("fixed", "declined", "open"),
                           {"fixed": "Fixed", "declined": "Closed without a fix", "open": "Still open"},
                           lambda v: "%.0f" % v, "Threads by fate per standard feature"), "")))

    defects = section(
        "defects", "Defects and rework", "What broke, how fast it was mended, and what had to be done again.",
        tiles(
            ("Defect density", "—" if sw["defect_density"] is None else "%.2f" % sw["defect_density"],
             "bugs per 1,000 lines changed · %d bugs" % sw["bugs"], sw["defect_density"]),
            ("Bug resolution time", span(sw["bug_resolution"]), "median, opened to closed", sw["bug_resolution"]),
            ("Reopened issues", share(sw["reopened"]), "%d of the closed ones" % sw["reopened_n"], sw["reopened"]),
            ("Rollback ratio", "—" if cur["failure"] is None else "%d%%" % round(cur["failure"] * 100),
             "production deploys rolled back", cur["failure"]),
            ("Reverts", compact(hist.get("reverts")), "commits that undid one on main", hist.get("reverts"))))

    mix = section(
        "mix", "Work mix", "What the changes were: new value, upkeep or tidying, and whether they were planned.",
        tiles(
            ("Planned work", share(sw["planned"]), "changes from a PR of an issue", sw["planned"]),
            ("Changes through a PR", share(sw["through_pr"]), "change control: reviewed before main",
             sw["through_pr"]),
            ("Refactor work", share(sw["refactor"]), "of changes, by commit type", sw["refactor"]),
            ("Support work", share(sw["support"]), "fixes, chores, CI and dependencies", sw["support"]),
            ("Commits", compact(hist.get("commits")), "%s lines added, %s removed"
             % (compact(hist.get("added")), compact(hist.get("removed")))),
            ("Migrations", compact(hist.get("migrations")), "schema changes added")),
        "<div class=two>%s%s</div>" % (
            card("Work by commit type", hbars(sw["types"], compact, "Commit types"),
                 "the %d changes shipped in the last %d days" % (sw["changes"], WINDOW)),
            card("Throughput per person", people)))

    code = x["code"] or {}
    hy = x["hygiene"]
    health = section(
        "health", "Code and project health", "The tracked source as it stands, and how work traces from issue to branch.",
        tiles(
            ("Source lines", compact(code.get("lines")), "in %s files" % compact(code.get("files"))),
            ("Comment lines", share(code.get("comments")), "of source lines", code.get("comments")),
            ("Large files", compact(code.get("large")), "over %d lines" % metrics_extra.LARGE_FILE,
             ratio(code.get("large"), code.get("files"))),
            ("Tests", share(code.get("tests")), "of source lines", code.get("tests")),
            ("Issues under a parent", share(hy["parented"]), "of %d issues" % hy["issues"], hy["parented"]),
            ("Branches named after an issue", share(hy["linked"]), "of PR branches", hy["linked"]),
            ("Open issues with an owner", share(hy["assigned"]), "of %d open" % hy["open"], hy["assigned"])))

    human = section(
        "human", "The person and Claude",
        "How much a person had to work for what Claude did: every time they stepped in, and how long it took them.",
        tiles(
            ("Claude's run between interventions", "—" if hm["run_calls"] is None else "%.0f" % hm["run_calls"],
             "median tool calls before the person is needed", hm["run_calls"]),
            ("Time Claude runs alone", span(hm["run_time"]), "median, between two interventions",
             hm["run_time"]),
            ("Sessions with no one stepping in", share(hm["unattended"]),
             "%d of %d that sclaude started" % (hm["unattended_n"], hm["started"]), hm["unattended"]),
            ("Person's share of the time", share(hm["person_share"]),
             "%s of a person against %s of Claude" % (span(hm["person_s"]), span(hm["claude_s"])),
             hm["person_share"]),
            ("Person's minutes per hour of Claude",
             "—" if hm["minutes_per_hour"] is None else "%.0f min" % hm["minutes_per_hour"],
             "answering, reading, deciding", hm["minutes_per_hour"]),
            {"abs": ("Interventions per feature", compact(hm["turns_per_feature"]), "median per finished feature",
                     hm["turns_per_feature"]),
             "norm": ("Interventions per feature",
                      "—" if hm["turns_per_feature_norm"] is None else "%.1f" % hm["turns_per_feature_norm"],
                      "median per standard feature", hm["turns_per_feature_norm"])},
            {"abs": ("Person's time per feature",
                     "—" if hm["minutes_per_feature"] is None else "%.0f min" % hm["minutes_per_feature"],
                     "median per finished feature", hm["minutes_per_feature"]),
             "norm": ("Person's time per feature",
                      "—" if hm["minutes_per_feature_norm"] is None else "%.0f min" % hm["minutes_per_feature_norm"],
                      "median per standard feature", hm["minutes_per_feature_norm"])},
            ("Autonomy", "—" if ai["autonomy"] is None else "%.0f" % ai["autonomy"],
             "tool calls per human input · %d inputs" % ai["inputs"], ai["autonomy"]),
            {"abs": ("Questions per feature", compact(ai["questions_per_feature"]), "median, Claude asking the person"),
             "norm": ("Questions per feature", "—" if nm["questions"] is None else "%.1f" % nm["questions"],
                      "median per standard feature")},
            ("Sessions by hand", share(ai["manual"]), "the rest sclaude started", ai["manual"]),
            ("Adoption", share(ai["adoption"]), "of %d commit authors use Claude" % ai["developers"],
             ai["adoption"])),
        "<div class=two>%s%s</div>" % (
            card("Autonomy per week", columns(hm["weekly"], lambda w: w[1], lambda v: "%.0f" % v,
                                              "Tool calls per intervention per week"),
                 "tool calls per intervention: rising means Claude needs the person less"),
            card("Person's share of the time per week", columns(hm["weekly"], lambda w: w[2], share,
                                                                "Person's share per week"),
                 "falling means more of the work is Claude's")),
        "<div class=two>%s%s</div>" % (
            card("Interventions by step", hbars([(STEP_NAMES.get(k, k), v[0]) for k, v in hm["steps"]],
                                                compact, "Interventions by step"),
                 "where the person is needed most"),
            card("Person's time by step", hbars([(STEP_NAMES.get(k, k), v[1]) for k, v in hm["steps"]],
                                                span, "Person's time by step"),
                 "each wait capped at half an hour: longer, they were away")),
        dual(("Interventions per feature",
              hbars([(f, v[0]) for f, v in reversed(hm["features"])], compact, "Interventions per feature"),
              "the last finished features"),
             ("Interventions per standard feature",
              hbars([(f, v[0] / sizes[f]["unit"]) for f, v in reversed(hm["features"]) if f in sizes],
                    lambda v: "%.1f" % v, "Interventions per standard feature"),
              "each feature's interventions divided by its size")))

    claude = section(
        "claude", "Claude at work", "Every session sclaude ran for this product, and the ones run here by hand.",
        tiles(
            ("Sessions", compact(x["sessions"]), "%d in the last %d days" % (x["sessions_recent"], WINDOW)),
            ("Subagents", compact(x["subagents"]), "started by those sessions"),
            ("Tool calls", compact(x["tool_calls"]), "median %s per session" % compact(x["calls_per_session"])),
            ("Commits by Claude", share(ratio(hist.get("by_claude"), hist.get("commits"))),
             "%d of %d in the last %d days" % (hist.get("by_claude", 0), hist.get("commits", 0), WINDOW)),
            ("Subagents per session", "—" if ai["subagents_per_session"] is None
             else "%.1f" % ai["subagents_per_session"], "on average"),
            ("Sessions per week", "%.0f" % ai["sessions_per_week"], "last %d days" % WINDOW),
            ("Tokens per week", compact(ai["tokens_per_week"]), "last %d days" % WINDOW),
            ("Session length", "—" if ai["session_minutes"] is None else "%.0f min" % ai["session_minutes"],
             "median")),
        "<div class=two>%s%s</div>" % (
            # An MCP tool by its own name: `mcp__<server>__<tool>`.
            card("Most used tools", hbars([(k.rsplit("__", 1)[-1], v) for k, v in x["tools"]],
                                          compact, "Tool calls")),
            card("What of Claude Code is used", hbars(ai["uses"], share, "Feature use"),
                 "share of sessions that used each")),
        card("When the work happens", heatmap(ai["heat"]), "sessions started, by weekday and hour"))

    cost = section(
        "cost", "Cost and tokens", "What a result costs. Dollars are Claude Code's own account, not an estimate.",
        tiles(
            ("Spend, last %d days" % WINDOW, money(x["cost_recent"]), "%s all time" % money(x["cost"])),
            {"abs": ("Per finished feature", money(x["per_feature"]), "median of its sessions' spend"),
             "norm": ("Per finished feature", money(nm["cost"]), "median per standard feature")},
            ("Per production deploy", money(x["per_deploy"]), "last %d days" % WINDOW),
            ("Per merged pull request", money(x["per_pr"]), "last %d days" % WINDOW),
            ("Per 1,000 lines changed", money(x["per_kloc"]), "on main, last %d days" % WINDOW),
            ("Cache hit rate", share(x["cache_hit"]), "input read from the prompt cache", x["cache_hit"]),
            ("Thinking", share(x["thinking_share"]), "of output tokens"),
            ("Output per tool call", compact(x["output_per_call"]), "tokens"),
            ("Time in the model", share(x["api_share"]), "of session time, the rest in tools")),
        "<div class=two>%s%s</div>" % (
            dual(("Spend per week", columns(wk, lambda w: w[1], money, "Spend per week"), ""),
                 ("Spend per standard feature shipped, per week",
                  columns(nm["weekly_spend"], lambda w: w[1], money, "Spend per standard feature shipped"),
                  "the week's spend over the size of what it shipped")),
            card("Cache hit rate per week", columns(wk, lambda w: w[2], share, "Cache hit rate per week"))),
        "<div class=two>%s%s</div>" % (
            dual(("Spend per finished feature", hbars(x["by_feature"], money, "Spend per feature"), ""),
                 ("Spend per standard feature", hbars(nm["by_feature"], money, "Spend per standard feature"),
                  "each feature's spend divided by its size")),
            card("Spend by step", hbars([(STEP_NAMES.get(k, k), v) for k, v in x["by_step"]],
                                        money, "Spend by step"))),
        "<div class=two>%s%s</div>" % (
            card("Spend by model", hbars(sorted(x["models"].items(), key=lambda kv: -kv[1]),
                                         money, "Spend by model")),
            card("Review sessions' context",
                 hbars([("Held before round one", x["review_door"])], compact, "Context"),
                 "median tokens · %s of the window used when handed back" % share(x["review_end_pct"]))))

    process = section(
        "process", "Process learning", "Where the rules got in the way, and whether they have learnt from it.",
        tiles(
            ("Deferred friction age", "—" if x["deferred_age"][0] is None else "%d days" % x["deferred_age"][0],
             "median · oldest %s days" % compact(x["deferred_age"][1]), x["deferred_age"][0])),
        "<div class=two>%s%s</div>" % (
            card("Friction reviews, by verdict",
                 hbars([(VERDICT_NAMES.get(k, k), v) for k, v in
                        sorted(fr["verdicts"].items(), key=lambda kv: -kv[1])], compact, "Verdicts"),
                 "%d reviews · %d changed the rules · %d entries put off for the monthly review"
                 % (fr["reviews"], fr["fixed"], x["deferred"])),
            card("Refusals per 100 tool calls, per week",
                 columns(wk, lambda w: w[3], lambda v: "%.1f" % v, "Refusals per week"),
                 "falling means the rules have learnt")),
        "<div class=two>%s%s</div>" % (
            card("Tool calls refused, by whom",
                 hbars([(DENIAL_NAMES.get(k, k), v) for k, v in
                        sorted(x["denials"].items(), key=lambda kv: -kv[1])], compact, "Refusals"),
                 "out of %s calls" % compact(x["tool_calls"])),
            card("Session trouble",
                 hbars([("API errors", x["api_errors"]), ("Context compactions", x["compactions"])],
                       compact, "Session trouble"))))

    rows = []
    for d in m["recent"]:
        what = ("<code>%s</code>" % esc(d["sha"][:8])) if d["sha"] else esc(d.get("feature") or "")
        if d["url"]:
            what = "<a href='https://%s'>%s</a>" % (esc(d["url"].replace("https://", "")), what)
        status = ("<span class=bad><i>▼</i>rolled back after %s</span>"
                  % esc(span((d["restored"] - d["at"]).total_seconds()))) if d["restored"] else ""
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (esc(stamp(d["at"])), what, d["changes"] or "—", esc(span(d["lead"])), status))
    table = ("<div class=scroll><table><tr><th>Deployed</th><th>Commit</th><th>Changes</th>"
             "<th>Median lead time</th><th></th></tr>%s</table></div>" % "".join(rows)) \
        if rows else "<p class=empty>No production deploy found.</p>"
    weeks_rows = "".join("<tr><td>%s</td><td>%d</td><td>%s</td></tr>"
                         % (esc(wk[0].strftime("%Y-%m-%d")), wk[1], esc(span(wk[2])))
                         for wk in reversed(m["weeks"]))
    notes = "".join("<li>%s</li>" % esc(n) for n in data["notes"])
    since = (" Production history since %s." % stamp(m["since"])) if m["since"] else ""
    tables = section(
        "records", "Records and method", "The rows the figures above are counted from, and how.",
        card("Recent production deploys", table),
        card("By week", "<div class=scroll><table><tr><th>Week of</th><th>Deploys</th>"
                        "<th>Median lead time</th></tr>%s</table></div>" % weeks_rows),
        card("How this is counted", (
            "<ul class=notes>"
            "<li>A deploy is a READY production deployment on Vercel. A change is a commit that "
            "a deploy put on production for the first time; a squashed pull request counts from "
            "its first commit.</li>"
            "<li>A failure is a production rollback: the incident comment sclaude writes on the "
            "issue, or a rollback in sclaude's own record of the feature. Restore time runs from "
            "the failed deploy to that rollback.</li>"
            "<li>DORA levels follow the State of DevOps thresholds: daily, weekly and monthly "
            "deploys; lead time under a day, week and month; failure rate up to 5, 10 and 15%%; "
            "restore within an hour, a day and a week.</li>"
            "<li>Sessions, tokens and dollars are read from Claude Code's transcripts of this "
            "product's checkout and worktrees; its own cost record, not a price list. A commit "
            "is Claude's when a session signed it.</li>"
            "<li>Regression, friction and cycle times come from sclaude's record of each "
            "finished feature; review rounds from its review log; acceptance criteria from the "
            "issue.</li>%s</ul>" % notes)),
        card("Not measured here", "<ul class=notes>%s</ul>" % "".join(
            "<li>%s</li>" % esc(n) for n in NOT_MEASURED)))

    switch = (
        "<div class=switch><div class=modes role=group aria-label='How features are compared'>"
        "<button type=button data-mode=abs aria-pressed=true>Absolute</button>"
        "<button type=button data-mode=norm aria-pressed=false>Per complexity ◆</button></div>"
        "<p class=sub>◆ marks the figures that scale with a feature's size. Per complexity "
        "divides them by it, so features of different size compare: values are per standard "
        "feature — the median one, %s acceptance criteria — and the weekly charts weigh each "
        "week by the size of what it delivered.</p></div>" % compact(nm["standard"]))
    # The whole at a glance: each direction's figures, scored by their own
    # bands (metrics_guide.Band.score) and averaged into one spoke.
    spend = [w[1] for w in nm["weekly_spend"] if w[1]]
    trend = spend[-1] / metrics_extra.med(spend[:-1]) if len(spend) > 1 and metrics_extra.med(spend[:-1]) else None

    def same(label, raw):
        return (label, raw, raw)
    directions = (
        ("Speed", [same("Deployment frequency", cur["per_day"]), same("Lead time for changes", cur["lead"]),
                   ("Feature cycle time", x["cycle"], nm["cycle"]), ("Time to market", ai["market"], nm["market"]),
                   same("PR aging", dv["aging"])]),
        ("Stability", [same("Change failure rate", cur["failure"]), same("Time to restore", cur["restore"]),
                       same("Rework rate", dm["rework"]), same("Hotfix rate", dm["hotfix"]),
                       same("Escaped defects", sw["escaped"]), same("Production suite green", dm["reliability"])]),
        ("Quality", [
            same("Regression green first time", first_time),
            ("Review rounds per feature", x["rounds_per_feature"], nm["rounds"]),
            ("Review threads per feature", x["threads_per_feature"], nm["threads"]),
            same("Threads still open", x["open_share"]), same("Reopened issues", sw["reopened"]),
            same("Tests in new lines", ratio(hist.get("test_added"), hist.get("added")))]),
        ("Clear requirements", [same("Requirements changed in development", rq["significant"]),
                                same("Requirements unclear at the start", rq["unclear"]),
                                same("Questions per criterion", rq["per_criterion"]),
                                same("Request grew in planning", rq["growth"])]),
        ("Flow", [same("Flow efficiency", ai["flow"]), same("Time in the queue", ai["queue"]),
                  same("Pickup time", dv["pickup"]), same("Review time", dv["review"]),
                  same("Features at once", ai["concurrent_max"])]),
        ("Autonomy", [same("Claude's run between interventions", hm["run_calls"]),
                      same("Person's share of the time", hm["person_share"]),
                      same("Sessions with no one stepping in", hm["unattended"]),
                      ("Interventions per feature", hm["turns_per_feature"], hm["turns_per_feature_norm"]),
                      ("Person's time per feature", hm["minutes_per_feature"], hm["minutes_per_feature_norm"])]),
        ("Cost", [same("Cache hit rate", x["cache_hit"]), same("Spend trend", trend)]),
        ("Discipline", [same("Changes through a PR", sw["through_pr"]), same("Planned work", sw["planned"]),
                        same("PRs without review", dv["unreviewed"]),
                        same("Branches named after an issue", hy["linked"]),
                        same("Open issues with an owner", hy["assigned"])]),
    )

    def health_block(mode):
        axes = [axis(n, ms, mode) for n, ms in directions]
        index, spread, best, worst = health_of(axes)
        suffix = "" if mode == "abs" else ", per complexity"
        bars = hbars([(n, v) for n, v, _ in axes], lambda v: "%d" % round(v), "Directions", width=380)
        figures = tiles(
            ("Health index", "—" if index is None else "%d" % round(index),
             "out of 100, the mean of the %d directions%s" % (len(axes), suffix), index),
            ("Imbalance", "—" if spread is None else "%d" % round(spread),
             "points between %s and %s" % (best[0], worst[0]) if best else "", spread),
            ("Weakest direction", worst[0] if worst else "—",
             "%d of 100 — where to look first" % round(worst[1]) if worst else "", worst[1] if worst else None))
        return ("<div class='%s'>%s%s</div>" % (
            mode, figures,
            card("The shape of the whole",
                 "<div class=radar-wrap><div>%s</div><div>%s</div></div>" % (radar(axes, "Health radar"), bars),
                 "Each spoke is a direction's figures, each scored 0–100 by its own bands — 100 at the "
                 "good mark, 50 at the watch mark — and averaged. A round shape is balanced; a dent is "
                 "where to look. Point at a dot for its figures.")))
    glance = section(
        "health-index", "Health at a glance",
        "Many figures, one picture: eight directions of the work, and how even they are.",
        health_block("abs"), health_block("norm"))

    # Generated teammates only where the product's config asks for them
    # (`metricsTeam: demo`); otherwise the page has no team part, and the
    # real people's figures stay in the work mix's table.
    team = team_section(x, cur, dv, sw, hm, ai, first_time, hist) \
        if team_mode(repo) == "demo" else ""

    parts = (("overview", "Overview", overview), ("health-index", "Health at a glance", glance),
             ("dora", "Delivery performance", dora),
             ("flow", "Flow of work", flow), ("prs", "Pull requests and builds", prs),
             ("requirements", "Requirements", requirements), ("testing", "Testing", testing),
             ("review", "Code review", review), ("defects", "Defects and rework", defects),
             ("mix", "Work mix", mix), ("health", "Code and project health", health),
             ("human", "The person and Claude", human), ("claude", "Claude at work", claude),
             ("cost", "Cost and tokens", cost), ("team", "Team", team),
             ("process", "Process learning", process),
             ("records", "Records and method", tables))
    parts = tuple(p for p in parts if p[2])
    body = (
        "%s<main><h1>What sclaude measures</h1>"
        "<p class=lead>%s · built %s · the last %d days unless a figure says otherwise.%s "
        "Rebuilt in the background when sclaude starts, at most every few hours.</p>%s%s</main>"
        % (contents([(k, t) for k, t, _ in parts]), esc(name), esc(stamp(m["now"])), WINDOW, esc(since),
           switch, "".join(html_ for _, _, html_ in parts)))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            # An open tab follows the rebuilds by itself.
            "<meta http-equiv=refresh content=3600>"
            "<title>DORA metrics</title><style>%s</style></head><body>%s"
            "<div id=tip role=tooltip></div><script>%s</script><script>%s</script></body></html>"
            % (STYLE, body, TIP_JS, TEAM_JS))


# --- building -----------------------------------------------------------------

def build(repo, now=None):
    data = collect(repo)
    page = render(repo, data, compute(repo, data, now))
    target = os.path.join(out_dir(repo), PAGE)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(page)
    os.replace(tmp, target)
    return target


def stale(repo, every=None):
    if every is None:
        try:
            every = int(os.environ.get("SCLAUDE_DORA_EVERY") or EVERY)
        except ValueError:
            every = EVERY
    try:
        return time.time() - os.path.getmtime(os.path.join(out_dir(repo), PAGE)) >= every
    except OSError:
        return True


def refresh(repo, force=False):
    """Build when stale or forced, once however many ask at the same time.
    True when it built."""
    if not os.path.isdir(os.path.join(repo, ".git")):
        return False
    if not force and not stale(repo):
        return False
    try:
        os.makedirs(out_dir(repo), exist_ok=True)
        lock = open(os.path.join(out_dir(repo), ".lock"), "w")
    except OSError:
        return False
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        # Looked at again under the lock: the one that held it may have just
        # built the page this run was about to.
        if not force and not stale(repo):
            return False
        try:
            build(repo)
        except (OSError, ValueError, TypeError, KeyError):
            return False
    return True


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "refresh":
        return 0 if refresh(args[1], "--force" in args[2:]) else 1
    if len(args) >= 2 and args[0] == "build":
        print(build(args[1]))
        return 0
    print("usage: dora.py refresh <repo> [--force] | build <repo>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
