# The DORA page's sources: Vercel's deployments, GitHub's pull requests,
# issues and incidents, and the cycle's record.
#
# Part of sclaude/lib/metrics/dora.py.

import json
import os
import subprocess
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from issue_comments import ROLLBACK as ROLLBACK_MARKER  # noqa: E402
from metrics import log_path

import dora_numbers, dora_store


# What rollback_incident heads its comment with (rollback.sh): the marker
# (issue_comments.py) finds the comment among the thread, the heading is what
# GitHub's search can see — it does not index an HTML comment.
ROLLBACK_HEADING = "Production rolled back"


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
    kept = dora_store.load(cache_path, {})
    branches = {}
    for number, pr in pulls.items():
        feature = dora_numbers.feature_of_branch(pr.get("branch"))
        if feature in features:
            branches.setdefault(pr["branch"], []).append(number)
    done = 0
    for branch, numbers in sorted(branches.items()):
        feature = dora_numbers.feature_of_branch(branch)
        numbers = sorted(numbers, key=int)
        if (kept.get(feature) or {}).get("prs") == numbers or done >= limit:
            continue
        found = []
        for number in numbers:
            threads = review_report.threads(repo, number, name)
            if threads is None:
                dora_store.save(cache_path, kept)
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
    dora_store.save(cache_path, kept)
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
