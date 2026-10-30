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
#   local_review.py since <journal> <head>        the commit the next run starts from
#   local_review.py round <journal> <head>        which round reviewing <head> is: one
#                                                 more than the other heads reviewed
#   local_review.py prompt <cwd> <pr> <repo> <journal>  the part of the review's prompt
#                                                 about earlier findings
#   local_review.py record <cwd> <pr> <repo> <answer> <base> <head> <seconds> <journal> [cap] [verify]
#                                                 post the run's new findings, resolve
#                                                 the ones it judged fixed, print how
#                                                 many are open, how many it posted,
#                                                 and 1 when it found the cap (more left);
#                                                 exit 1 when the answer
#                                                 has no count or nothing could be posted
#   local_review.py open <cwd> <pr> <repo> <journal>  post what waits to be posted,
#                                                 then say how many are open
#
# The journal (local-review-rounds.jsonl) is one line per run: when, how long,
# which range, how many new and resolved. It is what the report counts rounds
# by, as it counts the workflow's runs on GitHub; the findings are on GitHub.
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pr_context import (LOCAL_SIGNATURE, OUTSIDE_DIFF, RESOLVER_PREFIX,  # noqa: E402
                        decline_of, gh, headline, review_threads, signed_locally,
                        split_yours, thread_line, yours)

# A finding's heading as the prompt asks for it, `### <path>:<line> — <title>`,
# and the ways a model drifts from it: the path in backticks, a range of
# lines, a hyphen or en dash for the em dash.
HEADING = re.compile(r"^###\s+`?(.+?):(\d+)(?:[-–]\d+)?`?\s+[—–-]\s+(.*)$")
RESOLVED = re.compile(r"^\s*RESOLVED:\s*(r\d+)\s*(?:—|-|:)?\s*(.*)$")
COUNT = re.compile(r"^\s*FINDINGS:\s*(\d+)\s*$")


def gh_try(args, cwd):
    """(gh's output or None, whether GitHub refused the request as invalid).
    A refusal (422) is an answer about the request — a line outside the
    diff, a file outside the pull request — and the next form is tried; any
    other failure (a timeout, a 5xx, no network) may have been taken after
    all, so nothing else is posted for it now."""
    try:
        done = subprocess.run(["gh"] + args, cwd=cwd, capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, False
    if done.returncode == 0:
        return done.stdout, False
    text = (done.stderr or "") + (done.stdout or "")
    return None, ("422" in text or "Validation Failed" in text or "Unprocessable" in text)


def already(found, f):
    """Whether a thread for this finding is there already: on its file, with
    its title. A post that timed out may have been taken."""
    mark = "**%s**" % f["title"]
    return any(t["path"] == f["path"] and mark in (t["bodies"][0] if t["bodies"] else "")
               for t in found or [])


def threads(cwd, pr, repo):
    """Every review thread: {id, rid, resolved, review, path, line, url,
    bodies}; None when GitHub cannot be read. `review` marks a thread a
    review opened — the workflow's bot or a local run, by its signature —
    as against one a person opened, which no review may resolve."""
    nodes = review_threads(cwd, pr, repo)
    if nodes is None:
        return None
    out = []
    for t in nodes:
        comments = ((t.get("comments") or {}).get("nodes")) or []
        if not comments:
            continue
        first = comments[0]
        url = first.get("url") or ""
        rid = re.search(r"discussion_r(\d+)", url)
        out.append({"id": t.get("id"), "rid": "r" + rid.group(1) if rid else "",
                    "resolved": bool(t.get("isResolved")),
                    "review": (((first.get("author") or {}).get("__typename")) == "Bot"
                               or signed_locally(first.get("body"))),
                    "path": t.get("path") or "?",
                    "line": thread_line(t) or "?", "url": url,
                    "bodies": [c.get("body") or "" for c in comments],
                    "decision": decline_of(comments[1:])})
    return out


def checkable(cwd, found):
    """The open threads a review run may judge and resolve: a review's own,
    less the ones the person keeps to resolve by hand (review-yours)."""
    kept = yours(cwd)
    return [t for t in found if not t["resolved"] and t["review"] and t["url"] not in kept]


def open_count(cwd, found):
    """Open threads, less the ones the person decided to resolve by hand:
    what close_state counts."""
    still = [{"url": t["url"]} for t in found if not t["resolved"]]
    return len(split_yours(cwd, still)[1])


def prompt(cwd, pr, repo, journal):
    found = threads(cwd, pr, repo)
    if found is None:
        # Without the earlier findings the run would post the declined ones
        # again as new: better not to run at all.
        sys.stderr.write("GitHub could not be read: the review threads are unknown\n")
        return 1
    out = []
    still = checkable(cwd, found)
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
    # Declined: resolved with the author's decision, or still open and kept
    # in review-yours for the person to resolve by hand — not handed to the
    # run above, so said here, or it would raise them again.
    kept = yours(cwd)
    declined = [(t, t["decision"]) for t in found
                if t["review"] and t["resolved"] and t["decision"]]
    declined += [(t, kept[t["url"]] or t["decision"] or "left as it is") for t in found
                 if t["review"] and not t["resolved"] and t["url"] in kept]
    left = [(t, t["decision"]) for t in found if t["resolved"] and t["review"]]
    if declined:
        out.append("Findings the author decided to leave as they are, with the reason — do not "
                   "report one of them again, reworded or on another line, unless the code it "
                   "rests on changed so that the reason no longer holds; then say which change:")
        out.append("")
        for t, why in declined:
            out.append("- %s:%s — %s (%s)" % (t["path"], t["line"], headline(t["bodies"][0]), why))
        out.append("")
    waiting = pending_of(journal)
    if waiting:
        out.append("Findings already reported that are still waiting to be posted — do not "
                   "report them again: %s." % "; ".join(
                       "%s:%s — %s" % (f["path"], f["line"], f["title"]) for f in waiting))
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
    """One finding as a thread on its line, else on its file, else in the
    conversation: "thread", "conversation", or None when GitHub took none."""
    body = "**%s**\n\n%s\n\n%s · %s</sub>" % (f["title"], f["body"], LOCAL_SIGNATURE, head[:7])
    base = ["api", "repos/%s/pulls/%s/comments" % (repo, pr), "-f", "body=%s" % body,
            "-f", "commit_id=%s" % head, "-f", "path=%s" % f["path"]]
    out, refused = gh_try(base + ["-F", "line=%d" % f["line"], "-f", "side=RIGHT"], cwd)
    if out is not None:
        return "thread"
    if not refused:
        return None
    # GitHub takes a line only inside the diff's hunks, and a finding often
    # points at unchanged code beside them. On the file the thread has no
    # line of its own, so the body names it.
    body = (OUTSIDE_DIFF + "\n\n%s") % (f["line"], body)
    base[base.index("-f") + 1] = "body=%s" % body
    out, refused = gh_try(base + ["-f", "subject_type=file"], cwd)
    if out is not None:
        return "thread"
    if not refused:
        return None
    # A file the pull request does not change takes no review comment at all.
    # In the conversation it has no thread to resolve, so it is not signed as
    # the review's own: there it is a comment to answer, what people said,
    # and step 4 does not close past it.
    text = ("`%s:%d` (not in this pull request's diff) — **%s**\n\n%s\n\n"
            "_From the review run on this machine, on %s._"
            % (f["path"], f["line"], f["title"], f["body"], head[:7]))
    if gh(["pr", "comment", str(pr), "--body", text], cwd) is not None:
        return "conversation"
    return None


def unposted_file(journal):
    """Findings GitHub would not take, kept to be posted on the next call."""
    return os.path.join(os.path.dirname(journal), "local-review-unposted.json")


def flush(cwd, pr, repo, journal):
    """Post what an earlier run could not, on the head it was found on.
    (posted, still pending)."""
    path = unposted_file(journal)
    try:
        with open(path, encoding="utf-8") as fh:
            pending = json.load(fh)
    except (OSError, ValueError):
        return 0, 0
    found = threads(cwd, pr, repo)
    if found is None:
        return 0, len(pending)
    left = [f for f in pending
            if not already(found, f) and not post(cwd, pr, repo, f["head"], f)]
    keep(path, left)
    return len(pending) - len(left), len(left)


def pending_of(journal):
    try:
        with open(unposted_file(journal), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def keep(path, pending):
    if not pending:
        if os.path.exists(path):
            os.remove(path)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(pending, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def resolve(cwd, t, how, head):
    reply = "%s%s\n\n%s · %s</sub>" % (RESOLVER_PREFIX, how or "fixed in %s." % head[:7],
                                       LOCAL_SIGNATURE, head[:7])
    gh(["api", "graphql", "-f", "query=mutation($id:ID!,$b:String!){"
        "addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$b})"
        "{comment{url}}}", "-F", "id=%s" % t["id"], "-f", "b=%s" % reply], cwd)
    return gh(["api", "graphql", "-f", "query=mutation($id:ID!){resolveReviewThread("
               "input:{threadId:$id}){thread{isResolved}}}", "-F", "id=%s" % t["id"]],
              cwd) is not None


def record(cwd, pr, repo, answer_path, base, head, seconds, journal, cap="0", mode=""):
    with open(answer_path, encoding="utf-8") as fh:
        found, resolved, count = parse(fh.read())
    if count is None:
        return 1
    if mode == "verify":
        # A check of the fixes after the search was ended: whatever it
        # reports as new anyway is not posted — the person said the search
        # is over, and a new thread would start the rounds again.
        found, count = [], 0
    if count != len(found):
        # Headings the parser did not take would be findings dropped without
        # a word, and the head recorded as reviewed: refuse the answer.
        sys.stderr.write("the answer counts %d finding(s) but %d heading(s) were read\n"
                         % (count, len(found)))
        return 1
    before = threads(cwd, pr, repo)
    if before is None:
        sys.stderr.write("GitHub could not be read; nothing posted\n")
        return 1
    posted = talked = 0
    lost = []
    for f in found:
        if already(before, f):
            continue
        where = post(cwd, pr, repo, head, f)
        if where:
            posted += 1
            talked += where == "conversation"
        else:
            lost.append(dict(f, head=head))
            sys.stderr.write("could not post %s:%s — %s\n" % (f["path"], f["line"], f["title"]))
    if lost and not posted:
        # Nothing reached GitHub: the run is not recorded, so the next one
        # reviews the same head again rather than losing what this one found.
        return 1
    # Some did: the run stands, and the rest wait in a file of their own, to
    # be posted on the next call (flush) and counted open until they are.
    _, waiting = flush(cwd, pr, repo, journal)
    keep(unposted_file(journal), pending_of(journal) + lost)
    closed = 0
    by_rid = {t["rid"]: t for t in checkable(cwd, before)}
    for rid, how in resolved.items():
        if rid in by_rid and resolve(cwd, by_rid[rid], how, head):
            closed += 1
    # When the run started, as the workflow's runs are dated: the report puts
    # a thread in the last run started before it was posted.
    began = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=int(seconds))
    row = {"at": began.isoformat(timespec="seconds"),
           "seconds": int(seconds), "base": base, "head": head,
           "new": posted, "lost": len(lost), "resolved": closed,
           # Found as many as the cap: likely stopped with more unsaid, so this
           # head is not done — the next call reads the same range again.
           "more": int(cap) > 0 and count >= int(cap)}
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    after = threads(cwd, pr, repo)
    # Open: the threads, the findings still waiting to be posted, and the ones
    # posted to the conversation now, which have no thread to count them.
    still = open_count(cwd, after if after is not None else before)
    print("%d %d %d" % (still + waiting + len(lost) + talked, posted, 1 if row["more"] else 0))
    return 0


def rows(journal):
    """The journal's runs, oldest first: each a dict with at least `at` (the
    run's start, ISO) and `head`. The one reader of the file; the report
    reads it through here."""
    out = []
    try:
        with open(journal, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("head") and row.get("at"):
                    out.append(row)
    except OSError:
        pass
    return out


def main(argv):
    if not argv:
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "cached" and len(args) == 2:
        # Reviewed, and not left with more to read (a capped pass that the
        # next one never followed, an interrupted review).
        last = rows(args[0])
        return 0 if last and last[-1]["head"] == args[1] and not last[-1].get("more") else 1
    if cmd == "base" and len(args) == 1:
        last = rows(args[0])
        print(last[-1]["head"] if last else "")
        return 0
    if cmd == "since" and len(args) == 2:
        # Where the next run starts: the last head reviewed, or — when that
        # head is this one and was left with more — the same range again.
        last = rows(args[0])
        if not last:
            print("")
        elif last[-1]["head"] == args[1] and last[-1].get("more"):
            print(last[-1].get("base") or "")
        else:
            print(last[-1]["head"])
        return 0
    if cmd == "round" and len(args) == 2:
        # A round is a head: the passes over one head, and a capped head read
        # again later, are the same round.
        print(len({r["head"] for r in rows(args[0]) if r["head"] != args[1]}) + 1)
        return 0
    if cmd == "prompt" and len(args) == 4:
        return prompt(*args)
    if cmd in ("record",) and len(args) in (8, 9, 10):
        return record(*args)
    if cmd == "open" and len(args) == 4:
        # Waiting findings first: posted now, they are threads below.
        _, waiting = flush(args[0], args[1], args[2], args[3])
        found = threads(*args[:3])
        if found is None:
            return 1
        print(open_count(args[0], found) + waiting)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
