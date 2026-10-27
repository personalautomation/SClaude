#!/usr/bin/env python3
#
# How well a product's work is done, from what sclaude already keeps — for
# the metrics page (dora.py).
#
#   cycles.jsonl          each regression stage's runs and fixing sessions,
#                         each step's friction review and its verdict
#   review-context.log    every review session's rounds and the findings it
#                         answered (review_context_log in run.sh)
#   .sclaude/*/deferred/  friction put off for the monthly review (deferred.sh)
#   the issue             the acceptance criteria and how many were ticked
#                         (AC_OPEN … AC_CLOSE, issue_comments.py), and how
#                         the requirements moved once development began: the
#                         description, the User request comment (REQUEST) and
#                         the criteria, version by version
#   git                   commits, the ones a Claude session made (by
#                         their trailers), reverts,
#                         lines, the share of them in tests
#
# Nothing here asks the network except for the acceptance criteria, and those
# are kept per issue: a finished feature's criteria do not change.
import glob
import json
import os
import re
import subprocess

from difflib import SequenceMatcher

from issue_comments import AC_CLOSE, AC_OPEN, REQUEST
from metrics import STAGES, STEPS

REVIEW_LOG = os.path.join(".sclaude", "local", "review-context.log")
DEFERRED_GLOBS = (os.path.join(".sclaude", "team", "deferred", "*.tsv"),
                  os.path.join(".sclaude", "people", "*", "deferred", "*.tsv"))
# A commit Claude wrote: a step's session signs it with sclaude's trailer
# (sclaude/githooks), any other Claude Code session with its own two.
BY_CLAUDE = re.compile(r"^(Sclaude-Session:|Claude-Session:|Co-Authored-By: Claude)", re.M | re.I)
# A path that is a test by any of the usual conventions.
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|e2e|spec|specs)/|\.(test|spec)\.[a-z]+$|_test\.[a-z]+$")
MIGRATION_PATH = re.compile(r"(^|/)migrations/")


def git(repo, *args):
    try:
        done = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                              timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def regression(records):
    """{stage: {runs, first_pass, fixes, red_fixes}} over finished features.

    A stage passed first time when it passed with no fixing session at all.
    """
    out = {s: {"runs": 0, "first_pass": 0, "fixes": 0, "red_fixes": 0} for s in STAGES}
    for rec in records:
        for stage in STAGES:
            node = (rec.get("regression") or {}).get(stage)
            if not node or not node.get("status"):
                continue
            row = out[stage]
            row["runs"] += 1
            fixes = node.get("fixes") or []
            row["fixes"] += len(fixes)
            row["red_fixes"] += sum(1 for f in fixes if f.get("status") == "red")
            if node.get("status") == "passed" and not fixes:
                row["first_pass"] += 1
    return out


def friction(records):
    """How the friction reviews ended: {verdict: count}, and how many
    committed a fix to the product's rules."""
    verdicts, reviews, fixed = {}, 0, 0
    for rec in records:
        for step in STEPS:
            node = ((rec.get("steps") or {}).get(step) or {}).get("friction")
            if not node or node.get("empty"):
                continue
            reviews += 1
            fixed += 1 if node.get("fixed") else 0
            v = node.get("verdict") or "unsaid"
            verdicts[v] = verdicts.get(v, 0) + 1
    return {"reviews": reviews, "fixed": fixed, "verdicts": verdicts}


def deferred_files(repo):
    return [path for pattern in DEFERRED_GLOBS for path in glob.glob(os.path.join(repo, pattern))]


def deferred(repo):
    n = 0
    for path in deferred_files(repo):
        try:
            with open(path, encoding="utf-8") as fh:
                n += sum(1 for line in fh if line.strip())
        except OSError:
            pass
    return n


def review_log(repo):
    """{sessions, rounds, comments, reversals, door, end_pct} from the review
    log. `door` is the median context a session held before its first round,
    `end_pct` the median share of the window it had used when it handed back.

    review_context_log writes a row each time a review session hands its
    round back — carried on into the next, done, or left — with the threads
    that round was handed and the findings it declined since the row before.
    So a row is a round, and both counts add up across rows."""
    sessions, rounds, comments, reversals = set(), 0, 0, 0
    doors, ends = {}, []
    try:
        with open(os.path.join(repo, REVIEW_LOG), encoding="utf-8") as fh:
            for line in fh:
                cols = line.rstrip("\n").split("\t")
                if len(cols) < 10:
                    continue
                sessions.add(cols[2])
                if cols[5].isdigit():
                    doors[cols[2]] = int(cols[5])
                if cols[6].isdigit():
                    ends.append(int(cols[6]))
                rounds += 1
                comments += int(cols[9]) if cols[9].isdigit() else 0
                reversals += int(cols[10]) if len(cols) > 10 and cols[10].isdigit() else 0
    except OSError:
        pass
    door = sorted(doors.values())
    ends.sort()
    return {"sessions": len(sessions), "rounds": rounds, "comments": comments,
            "reversals": reversals,
            "door": door[len(door) // 2] if door else None,
            "end_pct": ends[len(ends) // 2] / 100 if ends else None}


def acceptance(repo, name, issues, cache_path):
    """{issue: [ticked, total]} for each issue, from its criteria comment."""
    try:
        with open(cache_path, encoding="utf-8") as fh:
            kept = json.load(fh)
    except (OSError, ValueError):
        kept = {}
    for issue in issues:
        key = str(issue)
        if key in kept or not name:
            continue
        try:
            done = subprocess.run(
                ["gh", "api", "repos/%s/issues/%s/comments" % (name, issue), "--paginate",
                 "-q", ".[] | select(.body | contains(%s)) | .body" % json.dumps(AC_OPEN)],
                cwd=repo, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            break
        if done.returncode != 0:
            break
        body = done.stdout
        block = body.split(AC_OPEN, 1)[1].split(AC_CLOSE, 1)[0] if AC_OPEN in body else ""
        ticked = len(re.findall(r"^\s*[-*] \[[xX]\]", block, re.M))
        total = ticked + len(re.findall(r"^\s*[-*] \[ \]", block, re.M))
        kept[key] = [ticked, total]
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(kept, fh)
        os.replace(tmp, cache_path)
    except OSError:
        pass
    return {k: v for k, v in kept.items() if k in {str(i) for i in issues}}


def history(repo, since):
    """What main's history says since `since`: commits, the share a Claude
    session made, reverts, lines, tests and migrations."""
    raw = git(repo, "log", "--since=" + since.isoformat(), "--no-merges",
              "--format=@@%H%x09%an%x09%s", "--numstat")
    out = {"commits": 0, "by_claude": 0, "reverts": 0, "added": 0, "removed": 0,
           "test_added": 0, "migrations": 0, "authors": {}}
    if raw is None:
        return None
    author = None
    for line in raw.splitlines():
        if line.startswith("@@"):
            out["commits"] += 1
            _, name, subject = (line.split("\t", 2) + ["", ""])[:3]
            author = out["authors"].setdefault(name, {"commits": 0, "lines": 0, "by_claude": 0})
            author["commits"] += 1
            if subject.startswith("Revert"):
                out["reverts"] += 1
            continue
        cols = line.split("\t")
        if len(cols) != 3 or not cols[0].isdigit():
            continue
        added, removed, path = int(cols[0]), int(cols[1]), cols[2]
        out["added"] += added
        out["removed"] += removed
        if author is not None:
            author["lines"] += added + removed
        if TEST_PATH.search(path):
            out["test_added"] += added
    # Read from the body rather than as git trailers: a squashed pull request
    # carries its commits' trailers in the middle of its message, where git
    # does not look for them.
    bodies = git(repo, "log", "--since=" + since.isoformat(), "--no-merges",
                 "--format=%an%x01%B%x00")
    if bodies is not None:
        for part in bodies.split("\x00"):
            name, _, body = part.lstrip("\n").partition("\x01")
            if BY_CLAUDE.search(body):
                out["by_claude"] += 1
                if name in out["authors"]:
                    out["authors"][name]["by_claude"] += 1
    created = git(repo, "log", "--since=" + since.isoformat(), "--no-merges",
                  "--diff-filter=A", "--name-only", "--format=")
    if created is not None:
        out["migrations"] = sum(1 for p in created.splitlines() if MIGRATION_PATH.search(p))
    return out


# --- how the requirements moved ----------------------------------------------
#
# Development begins when the plan is approved, and that is the moment the
# orchestrator posts the acceptance criteria (AC_OPEN): what the issue said
# then is what the work set out to build. Every later edit of the description,
# of the User request comment — which the code step extends under "Added during
# development" with each new thing the person asks for (prompts/code.md) — and
# of the criteria moved the target. GitHub keeps each version of an edited
# body whole, so the issue as it stood at that moment and as it ended can be
# laid side by side.
#
# A tick in a criterion's box is QA's verdict, not a change of requirement:
# boxes are read unticked on both sides.
ADDED_HEADING = "### Added during development"
# What counts as a significant change: a fifth of the text, a criterion
# added or dropped, or two requirements added during development.
SIGNIFICANT_SHARE = 0.2
SIGNIFICANT_ADDED = 2
TICK = re.compile(r"^(\s*[-*] )\[[xX]\]", re.M)

ISSUE_FIELDS = """
  i%(n)s: issue(number: %(n)s) {
    body
    userContentEdits(first: 50) { nodes { editedAt diff } }
    comments(first: 100) {
      nodes { createdAt body userContentEdits(first: 50) { nodes { editedAt diff } } }
    }
  }"""


def versions(node, created=None):
    """[(time, text)] of a body, oldest first: GitHub's edits, each holding
    the whole text as it stood, or the body alone when it never changed."""
    edits = [(e.get("editedAt"), e.get("diff") or "")
             for e in (node.get("userContentEdits") or {}).get("nodes") or [] if e.get("editedAt")]
    if not edits:
        return [(created or "", node.get("body") or "")]
    return sorted(edits)


def at(history, moment):
    """The text as it stood at `moment` (ISO), or None if it did not exist."""
    found = None
    for when_, text in history:
        if when_ <= moment:
            found = text
    return found


def words(text):
    return len(re.findall(r"\w+", text or ""))


def criteria_of(text):
    return len(re.findall(r"^\s*[-*] \[[ xX]\]", text or "", re.M))


def requirement_moves(node):
    """How one issue's requirements moved after its plan was approved, or
    None where nothing marks the start (no criteria comment)."""
    comments = (node.get("comments") or {}).get("nodes") or []
    ac = next((c for c in comments if AC_OPEN in (c.get("body") or "")), None)
    if not ac:
        return None
    start = ac.get("createdAt") or ""
    request = next((c for c in comments if REQUEST in (c.get("body") or "")), None)
    parts = [versions(node), versions(ac, start)]
    if request:
        parts.append(versions(request, request.get("createdAt")))

    def whole(moment):
        texts = [at(h, moment) if moment else h[-1][1] for h in parts]
        return TICK.sub(r"\1[ ]", "\n\n".join(t for t in texts if t))
    before, after = whole(start), whole(None)
    ac_before, ac_after = at(parts[1], start) or "", parts[1][-1][1]
    final_request = parts[2][-1][1] if request else ""
    added = 0
    if ADDED_HEADING in final_request:
        tail = final_request.split(ADDED_HEADING, 1)[1].split("\n#", 1)[0]
        added = len(re.findall(r"^\s*[-*] ", tail, re.M))
    change = 1 - SequenceMatcher(None, before, after, autojunk=False).ratio() if before != after else 0.0
    criteria = (criteria_of(ac_before), criteria_of(ac_after))
    first_request = parts[2][0][1] if request else ""
    return {
        "start": start, "change": round(change, 4), "criteria": list(criteria), "added": added,
        "significant": change >= SIGNIFICANT_SHARE or criteria[0] != criteria[1]
        or added >= SIGNIFICANT_ADDED,
        "changed": change > 0 or added > 0 or criteria[0] != criteria[1],
        "description_words": words(node.get("body")),
        "request_words": words(final_request.split(ADDED_HEADING, 1)[0]) if request else None,
        "first_request_words": words(first_request) if request else None,
    }


def requirements(repo, name, issues, cache_path, limit=60):
    """{issue: requirement_moves} for each issue, ten asked of GitHub at a time
    and each kept once read: a finished feature's history does not move."""
    try:
        with open(cache_path, encoding="utf-8") as fh:
            kept = json.load(fh)
    except (OSError, ValueError):
        kept = {}
    todo = [str(i) for i in issues if str(i) not in kept][:limit]
    if name and todo:
        owner, _, short = name.partition("/")
        for i in range(0, len(todo), 10):
            batch = todo[i:i + 10]
            query = "query { repository(owner: %s, name: %s) { %s } }" % (
                json.dumps(owner), json.dumps(short), "".join(ISSUE_FIELDS % {"n": n} for n in batch))
            try:
                done = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query], cwd=repo,
                                      capture_output=True, text=True, timeout=90,
                                      stdin=subprocess.DEVNULL)
                found = json.loads(done.stdout)["data"]["repository"] if done.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
                found = None
            if not found:
                break
            for n in batch:
                node = found.get("i" + n)
                kept[n] = requirement_moves(node) if node else None
    try:
        tmp = cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(kept, fh)
        os.replace(tmp, cache_path)
    except OSError:
        pass
    return {k: v for k, v in kept.items() if v and k in {str(i) for i in issues}}
