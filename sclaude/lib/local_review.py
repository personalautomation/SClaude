#!/usr/bin/env python3
#
# A review run on this machine (`review: local`) keeps its findings where the
# review in GitHub Actions keeps them: as threads on the pull request.
#
# So everything that reads a review reads this one the same way — step 4's
# snapshot of the open threads, the person's "Left as it is" decline and
# review-yours, the review report, the counts in the issue, the summary for
# QA — and nothing is lost when a run or a session is interrupted: a finding
# is open until a later run judges it fixed and resolves it, or the person
# declines it, exactly as with the workflow. Nothing here runs on Actions.
#
# What differs is only who writes: the threads are posted through `gh` under
# the account logged in here, each ending with LOCAL_SIGNATURE so that a
# reader can tell them from what a person wrote (pr_context.review_state).
#
#   local_review.py cached <journal> <head>       exit 0 when <head> is the last reviewed
#   local_review.py base <journal>                the last reviewed head, or nothing
#   local_review.py prompt <cwd> <pr> <repo>      the part of the review's prompt about
#                                                 earlier findings
#   local_review.py record <cwd> <pr> <repo> <answer> <base> <head> <seconds> <journal>
#                                                 post the run's new findings, resolve
#                                                 the ones it judged fixed, print how
#                                                 many are open; exit 1 when the answer
#                                                 has no count or nothing could be posted
#   local_review.py open <cwd> <pr> <repo>        how many threads are open now
#
# The journal (local-review-rounds.jsonl) is one line per run: when, how long,
# which range, how many new and resolved. It is what the report counts rounds
# by, as it counts the workflow's runs on GitHub; the findings are on GitHub.
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pr_context import (DECLINE_PREFIX, LOCAL_SIGNATURE, RESOLVER_PREFIX, gh,  # noqa: E402
                        gh_json, headline, split_yours)

HEADING = re.compile(r"^###\s+(.+?):(\d+)\s+—\s+(.*)$")
RESOLVED = re.compile(r"^\s*RESOLVED:\s*(r\d+)\s*(?:—|-|:)?\s*(.*)$")
COUNT = re.compile(r"^\s*FINDINGS:\s*(\d+)\s*$")

QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved path line originalLine
          comments(first: 50) { nodes { body url } }
        }
      }
    }
  }
}
"""


def threads(cwd, pr, repo):
    """Every review thread: {id, rid, resolved, path, line, url, bodies}; None
    when GitHub cannot be read."""
    owner, name = repo.split("/", 1)
    out, after = [], None
    while True:
        args = ["api", "graphql", "-f", "query=%s" % QUERY, "-F", "owner=%s" % owner,
                "-F", "name=%s" % name, "-F", "number=%s" % pr]
        if after:
            args += ["-f", "after=%s" % after]
        data = gh_json(args, cwd=cwd)
        try:
            page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        except (TypeError, KeyError):
            return None
        for t in page.get("nodes") or []:
            comments = ((t.get("comments") or {}).get("nodes")) or []
            if not comments:
                continue
            url = comments[0].get("url") or ""
            rid = re.search(r"discussion_r(\d+)", url)
            out.append({"id": t.get("id"), "rid": "r" + rid.group(1) if rid else "",
                        "resolved": bool(t.get("isResolved")), "path": t.get("path") or "?",
                        "line": t.get("line") or t.get("originalLine") or "?", "url": url,
                        "bodies": [c.get("body") or "" for c in comments]})
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return out
        after = info.get("endCursor")


def decline_of(t):
    """The author's decision on a declined thread, or None."""
    for body in reversed(t["bodies"][1:]):
        text = body.lstrip()
        if text.startswith(RESOLVER_PREFIX):
            return None
        if text.startswith(DECLINE_PREFIX):
            return text.split(":", 1)[-1].strip() or "left as it is"
    return None


def open_count(cwd, found):
    """Open threads, less the ones the person decided to resolve by hand:
    what close_state counts."""
    still = [{"url": t["url"]} for t in found if not t["resolved"]]
    return len(split_yours(cwd, still)[1])


def prompt(cwd, pr, repo):
    found = threads(cwd, pr, repo) or []
    out = []
    still = [t for t in found if not t["resolved"]]
    if still:
        out.append("Findings on this pull request that are still open — check each against "
                   "the code as it is now, and for every one the code no longer has (the fix "
                   "is in, or the code is gone) write a line `RESOLVED: <id> — <how, in a "
                   "sentence>` in your answer; do not report any of them again as a new "
                   "finding:")
        out.append("")
        for t in still:
            out.append("- %s · %s:%s — %s" % (t["rid"], t["path"], t["line"],
                                              headline(t["bodies"][0])))
        out.append("")
    left = [(t, decline_of(t)) for t in found if t["resolved"]]
    declined = [(t, why) for t, why in left if why]
    if declined:
        out.append("Findings the author decided to leave as they are, with the reason — do not "
                   "report one of them again, reworded or on another line, unless the code it "
                   "rests on changed so that the reason no longer holds; then say which change:")
        out.append("")
        for t, why in declined:
            out.append("- %s:%s — %s (%s)" % (t["path"], t["line"], headline(t["bodies"][0]), why))
        out.append("")
    fixed = [t for t, why in left if not why]
    if fixed:
        out.append("Findings reported and fixed earlier, not to be reported again unless the "
                   "fix was undone: %s." % "; ".join(
                       "%s:%s — %s" % (t["path"], t["line"], headline(t["bodies"][0]))
                       for t in fixed))
    sys.stdout.write("\n".join(out))
    return 0


def parse(answer):
    """(new findings, {rid: how}, count or None) from a run's answer."""
    found, resolved, count, current = [], {}, None, None
    for line in answer.splitlines():
        m = HEADING.match(line)
        if m:
            current = {"path": m.group(1), "line": int(m.group(2)),
                       "title": m.group(3).strip(), "body": []}
            found.append(current)
            continue
        r = RESOLVED.match(line)
        if r:
            resolved[r.group(1)] = r.group(2).strip()
            current = None
            continue
        c = COUNT.match(line)
        if c:
            count = int(c.group(1))
            current = None
            continue
        if current is not None:
            current["body"].append(line)
    for f in found:
        f["body"] = "\n".join(f["body"]).strip()
    return found, resolved, count


def post(cwd, pr, repo, head, f):
    """One finding as a thread on its line, else on its file; False when
    GitHub would take neither."""
    body = "**%s**\n\n%s\n\n%s · %s</sub>" % (f["title"], f["body"], LOCAL_SIGNATURE, head[:7])
    base = ["api", "repos/%s/pulls/%s/comments" % (repo, pr), "-f", "body=%s" % body,
            "-f", "commit_id=%s" % head, "-f", "path=%s" % f["path"]]
    if gh(base + ["-F", "line=%d" % f["line"], "-f", "side=RIGHT"], cwd) is not None:
        return True
    return gh(base + ["-f", "subject_type=file"], cwd) is not None


def resolve(cwd, t, how, head):
    reply = "%s%s\n\n%s · %s</sub>" % (RESOLVER_PREFIX, how or "fixed in %s." % head[:7],
                                       LOCAL_SIGNATURE, head[:7])
    gh(["api", "graphql", "-f", "query=mutation($id:ID!,$b:String!){"
        "addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$b})"
        "{comment{url}}}", "-F", "id=%s" % t["id"], "-f", "b=%s" % reply], cwd)
    return gh(["api", "graphql", "-f", "query=mutation($id:ID!){resolveReviewThread("
               "input:{threadId:$id}){thread{isResolved}}}", "-F", "id=%s" % t["id"]],
              cwd) is not None


def record(cwd, pr, repo, answer_path, base, head, seconds, journal):
    with open(answer_path, encoding="utf-8") as fh:
        found, resolved, count = parse(fh.read())
    if count is None:
        return 1
    before = threads(cwd, pr, repo)
    if before is None:
        sys.stderr.write("GitHub could not be read; nothing posted\n")
        return 1
    posted = lost = 0
    for f in found:
        if post(cwd, pr, repo, head, f):
            posted += 1
        else:
            lost += 1
            sys.stderr.write("could not post %s:%s — %s\n" % (f["path"], f["line"], f["title"]))
    if lost and not posted:
        # Nothing reached GitHub: the run is not recorded, so the next one
        # reviews the same head again rather than losing what this one found.
        return 1
    closed = 0
    by_rid = {t["rid"]: t for t in before if not t["resolved"]}
    for rid, how in resolved.items():
        if rid in by_rid and resolve(cwd, by_rid[rid], how, head):
            closed += 1
    row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "seconds": int(seconds), "base": base, "head": head,
           "new": posted, "lost": lost, "resolved": closed}
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    after = threads(cwd, pr, repo)
    print(open_count(cwd, after if after is not None else before))
    return 0


def rows(journal):
    out = []
    try:
        with open(journal, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("head"):
                    out.append(row)
    except OSError:
        pass
    return out


def main(argv):
    if not argv:
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "cached" and len(args) == 2:
        last = rows(args[0])
        return 0 if last and last[-1]["head"] == args[1] else 1
    if cmd == "base" and len(args) == 1:
        last = rows(args[0])
        print(last[-1]["head"] if last else "")
        return 0
    if cmd == "prompt" and len(args) == 3:
        return prompt(*args)
    if cmd == "record" and len(args) == 8:
        return record(*args)
    if cmd == "open" and len(args) == 3:
        found = threads(*args)
        if found is None:
            return 1
        print(open_count(args[0], found))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
