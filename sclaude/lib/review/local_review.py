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
#   local_review.py cached <journal> <head> [pr]  exit 0 when <head> is the last reviewed
#   local_review.py base <journal> [pr]           the last reviewed head, or nothing
#   local_review.py since <journal> <head> [pr]   the commit the next run starts from
#   local_review.py round <journal> <head> [pr]   which round reviewing <head> is: one
#                                                 more than the other heads reviewed
#
#   local_review.py first <journal> <head> <pr>   exit 0 when the review block's first
#                                                 read is still to come
#   local_review.py whole <journal> <pr>          the head the block was last read whole at
#
# With [pr], only that pull request's runs count: one journal may hold
# several, a pull request closed and another opened. While a pull request is read in review blocks
# (review_blocks.sh) SCLAUDE_REVIEW_BLOCK names the block: `cached`, `round`
# and `first` count its runs alone, and a run recorded then carries `block`
# and `read` (tag); `since` stays the pull request's own. A row from before
# the journal kept the number counts for every one.
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
#   local_review.py unread <cwd> <base> <head> <sessions>  the files the branch's own
#                                                 commits changed in <base>..<head> that
#                                                 none of the passes' conversations (ids,
#                                                 comma-separated) opened,
#                                                 one a line; nothing when it cannot tell
#   local_review.py owed <journal>                mark the last run left with more to
#                                                 read, as a capped one is
#
# The journal (JOURNAL, review-rounds.jsonl) is one line per review run,
# wherever it ran: when, how long, which head. A pass here adds the range and
# how many it posted and resolved; a run of the workflow in Actions is added
# by github_runs once it finished, `source: github`. The report, the process
# map and where the next pass starts all read it, and nothing else; the
# findings are on GitHub.
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from pr_context import fits, pr_file, pr_folder, write_pr_file  # noqa: E402
from pr_context import (LOCAL_SIGNATURE, MINOR_KINDS, OUTSIDE_DIFF, RESOLVER_PREFIX,  # noqa: E402
                        QUOTA_LIMIT, decline_of, gh, headline, quota_reset,
                        minor_mark, review_threads, signed_locally, split_yours, thread_line, yours)

JOURNAL = ".sclaude/local/feature/review-rounds.jsonl"


# A finding's heading as the prompt asks for it, `### <path>:<line> —
# [<severity>] <title>`, and the ways a model drifts from it: the path in
# backticks, a range of lines, a hyphen or en dash for the em dash, the
# severity left out (important) or in another case.
HEADING = re.compile(r"^###\s+`?(.+?):(\d+)(?:[-–]\d+)?`?\s+[—–-]\s+(.*)$")
# The severity `/code-review` gives a finding, as the prompt asks it at the
# head of the title; nit and pre-existing are posted minor (MINOR_MARK in
# pr_context.py), open work all the same, weighed by the fix session.
SEVERITY = re.compile(r"^\[\s*(important|nit|pre[-_ ]existing)\s*\]\s*", re.I)
RESOLVED = re.compile(r"^\s*RESOLVED:\s*(r\d+)\s*(?:—|-|:)?\s*(.*)$")
COUNT = re.compile(r"^\s*FINDINGS:\s*(\d+)\s*$")
# The files a reviewer read in full (sreview asks for it): ends the finding
# above it, as FINDINGS does, and is no part of any.
COVERED = re.compile(r"^\s*COVERED:")
# The line a review's answer ends with once the code-review skill and every
# agent it started are done (local_review_prompt in local_review.sh asks for
# it): a session that hands back an interim answer — "FINDINGS: 0" before its
# agents report — would otherwise record a head as clean.
DONE = "REVIEW: complete"
# How each reason `record` refuses an answer begins, on its stderr: the
# shell takes the line after it into its warning, the feature's topic and
# the journal's spent row (`refused`), which the review's report counts —
# by its words, so a reason carries no number (the details go on a line of
# their own).
REFUSED = "refused: "
# An answer that is Claude's usage limit ("You've hit your weekly limit ·
# resets 3am (Europe/Lisbon)") is not refused but told apart, on a line of
# its own with the reset (seconds since the epoch, 0 when it did not say):
# the shell neither runs the pass again at once nor counts it refused, and
# the gate waits for the reset (review_limit_wait in local_review.sh).
LIMIT = "limit: "


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


SETTLED_INLINE_MAX = 12000


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
    # Settled findings pile up with a long review — hundreds, fixed — and
    # the run reads its prompt at every turn: past their budget they go to
    # settled.md beside the snapshot, by file, and the prompt says where.
    folder = pr_folder(cwd)
    # Written below only when something does not fit: one left from an
    # earlier run would sit there, out of date.
    if folder and os.path.exists(os.path.join(folder, "settled.md")):
        os.remove(os.path.join(folder, "settled.md"))
    fixed = [t for t, why in left if not why]
    settled = {}
    for t, why in declined:
        settled.setdefault(t["path"], []).append(
            "- :%s — %s (declined: %s)" % (t["line"], headline(t["bodies"][0]), why))
    for t in fixed:
        settled.setdefault(t["path"], []).append(
            "- :%s — %s (fixed)" % (t["line"], headline(t["bodies"][0])))
    lines = ["- %s:%s — %s (%s)" % (t["path"], t["line"], headline(t["bodies"][0]), why)
             for t, why in declined]
    spill = not fits(lines, SETTLED_INLINE_MAX, folder)
    if declined and not spill:
        out.append("Findings the author decided to leave as they are, with the reason — do not "
                   "report one of them again, reworded or on another line, unless the code it "
                   "rests on changed so that the reason no longer holds; then say which change:")
        out.append("")
        out += lines
        out.append("")
    # This pull request's alone: another's waits for it (flush).
    waiting = [f for f in pending_of(journal) if not f.get("pr") or str(f["pr"]) == str(pr)]
    if waiting:
        out.append("Findings already reported that are still waiting to be posted — do not "
                   "report them again: %s." % "; ".join(
                       "%s:%s — %s" % (f["path"], f["line"], f["title"]) for f in waiting))
        out.append("")
    listed = "; ".join("%s:%s — %s" % (t["path"], t["line"], headline(t["bodies"][0]))
                       for t in fixed)
    if fixed and not spill and fits([listed], SETTLED_INLINE_MAX, folder):
        out.append("Findings reported and fixed earlier, not to be reported again unless the "
                   "fix was undone: %s. A change in this range that undoes one of these fixes "
                   "is a finding: report it, naming the finding it undoes." % listed)
        out.append("")
    elif spill or fixed:
        # Here only when something did not fit, which needs a folder to go to;
        # the declined ones only when they are not inline above already.
        if not spill:
            settled = {}
            for t in fixed:
                settled.setdefault(t["path"], []).append(
                    "- :%s — %s (fixed)" % (t["line"], headline(t["bodies"][0])))
        md = ["# Findings settled on pull request #%s, by file" % pr, ""]
        for path in sorted(settled):
            md += ["## `%s`" % path, ""] + settled[path] + [""]
        write_pr_file(folder, "settled.md", md)
        what = ("%d the author decided to leave, with the reason, and %d fixed"
                % (len(declined), len(fixed)) if spill else "%d fixed" % len(fixed))
        out.append("Findings settled earlier on this pull request — %s — are in `%s`, under "
                   "a heading per file. Before you report a finding, read its file's section "
                   "there: one that repeats a settled finding, reworded or on another line, is "
                   "not reported, unless the code it rests on changed so that the reason no "
                   "longer holds (then say which change) or the fix was undone. A change in "
                   "this range that undoes a settled fix is a finding: report it, naming the "
                   "finding it undoes." % (what, pr_file("settled.md")))
        out.append("")

    sys.stdout.write("\n".join(out))
    return 0


def parse(answer):
    """(new findings, {rid: how}, count or None) from a run's answer."""
    found, resolved, count, current = [], {}, None, None
    for line in answer.splitlines():
        m = HEADING.match(line)
        if m:
            title = m.group(3).strip()
            tag = SEVERITY.match(title)
            severity = "important"
            if tag:
                severity = re.sub(r"[-_ ]", "-", tag.group(1).lower())
                title = title[tag.end():].strip()
            current = {"path": m.group(1), "line": int(m.group(2)),
                       "title": title, "severity": severity, "body": []}
            found.append(current)
            continue
        r = RESOLVED.match(line)
        if r:
            resolved[r.group(1)] = r.group(2).strip()
            current = None
            continue
        if COVERED.match(line):
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
    # A minor finding's marker goes first, above the outside-the-diff line.
    minor = f.get("severity") if f.get("severity") in MINOR_KINDS else ""

    def marked(text):
        return "%s\n\n%s" % (minor_mark(minor), text) if minor else text

    core = "**%s**\n\n%s\n\n%s · %s</sub>" % (f["title"], f["body"], LOCAL_SIGNATURE, head[:7])
    body = marked(core)
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
    body = marked((OUTSIDE_DIFF + "\n\n%s") % (f["line"], core))
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
    text = ("`%s:%d` (not in this pull request's diff) — %s**%s**\n\n%s\n\n"
            "_From the review run on this machine, on %s._"
            % (f["path"], f["line"], "(%s) " % minor if minor else "", f["title"], f["body"], head[:7]))
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
    # Another pull request's findings stay for it: a feature built in parts
    # has one for each part, and a finding is about the diff it was found in.
    others = [f for f in pending if f.get("pr") and str(f["pr"]) != str(pr)]
    pending = [f for f in pending if f not in others]
    if not pending:
        return 0, 0
    found = threads(cwd, pr, repo)
    if found is None:
        return 0, len(pending)
    left = [f for f in pending
            if not already(found, f) and not post(cwd, pr, repo, f["head"], f)]
    keep(path, others + left)
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
        text = fh.read()
    found, resolved, count = parse(text)
    if count is None and QUOTA_LIMIT.search(text):
        sys.stderr.write("%s%d\n" % (LIMIT, quota_reset(text)))
        return 1
    if count is None:
        sys.stderr.write(REFUSED + "the answer has no `FINDINGS: <n>` line it could read (an error, no answer, or the line in another form)\n")
        return 1
    if mode != "verify" and DONE not in [line.strip() for line in text.splitlines()]:
        sys.stderr.write(REFUSED + "the answer has no %r line: the review handed back before it was done\n" % DONE)
        return 1
    if mode == "verify":
        # A check of the fixes after the search was ended: whatever it
        # reports as new anyway is not posted — the person said the search
        # is over, and a new thread would start the rounds again.
        found, count = [], 0
    if count != len(found):
        # Headings the parser did not take would be findings dropped without
        # a word, and the head recorded as reviewed: refuse the answer.
        sys.stderr.write(REFUSED + "the answer's count does not match its headings\n"
                         "the answer counts %d finding(s) but %d heading(s) were read\n"
                         % (count, len(found)))
        return 1
    before = threads(cwd, pr, repo)
    if before is None:
        sys.stderr.write(REFUSED + "GitHub could not be read; nothing posted\n")
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
        sys.stderr.write(REFUSED + "GitHub took none of its findings\n")
        return 1
    # Some did: the run stands, and the rest wait in a file of their own, to
    # be posted on the next call (flush) and counted open until they are.
    _, waiting = flush(cwd, pr, repo, journal)
    keep(unposted_file(journal), pending_of(journal) + [dict(f, pr=str(pr)) for f in lost])
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
           "new": posted, "lost": len(lost), "resolved": closed, "pr": str(pr),
           # Found as many as the cap: likely stopped with more unsaid, so this
           # head is not done — the next call reads the same range again.
           "more": int(cap) > 0 and count >= int(cap)}
    # The pass's own conversation, when a model ran it (local_review.sh): the
    # issue's summary lists it among the feature's sessions.
    if os.environ.get("SCLAUDE_REVIEW_SESSION"):
        row["session"] = os.environ["SCLAUDE_REVIEW_SESSION"]

    tag(row)
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    after = threads(cwd, pr, repo)
    # Open: the threads, the findings still waiting to be posted, and the ones
    # posted to the conversation now, which have no thread to count them.
    still = open_count(cwd, after if after is not None else before)
    print("%d %d %d" % (still + waiting + len(lost) + talked, posted, 1 if row["more"] else 0))
    return 0


def tag(row):
    """The review block the run read (SCLAUDE_REVIEW_BLOCK), and whether it
    was the block's first read of its files (SCLAUDE_REVIEW_READ=first) or a
    round's new commits — local_review.sh sets both while blocks are read."""
    if os.environ.get("SCLAUDE_REVIEW_BLOCK"):
        row["block"] = os.environ["SCLAUDE_REVIEW_BLOCK"]
        row["read"] = os.environ.get("SCLAUDE_REVIEW_READ") or "delta"
    # A pass reading what a GitHub run left unopened (SCLAUDE_REVIEW_FOLLOWS,
    # "<base> <run> <attempt>"), recorded or spent: the same run's, one round
    # with it in the report and on the map, which group rows by base, head
    # and run.
    follows = os.environ.get("SCLAUDE_REVIEW_FOLLOWS", "").split()
    if len(follows) == 3 and follows[1].isdigit() and follows[2].isdigit():
        row.update({"base": follows[0], "run": int(follows[1]), "attempt": int(follows[2]), "followup": True})


def block_now():
    return os.environ.get("SCLAUDE_REVIEW_BLOCK") or None


def spent(journal, base, head, seconds, session, pr="", refused=""):
    """A pass that ran and was not recorded — stopped by the person, or its
    answer not taken — journaled all the same, marked `spent`, so that the
    report prices its conversation. rows() leaves it out unless asked: the
    head it read is not a reviewed one; `refused` says why its answer was
    not taken."""
    began = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=int(seconds))
    row = {"at": began.isoformat(timespec="seconds"), "seconds": int(seconds),
           "base": base, "head": head, "spent": True}
    if pr:
        row["pr"] = str(pr)
    if session:
        row["session"] = session
    # Why `record` refused the pass's answer (REFUSED), when it did; a pass
    # the person stopped has none.
    if refused:
        row["refused"] = refused
    tag(row)
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return 0


def rows(journal, with_spent=False, pr=None, local_only=False, block=None):
    """The journal's runs, oldest first: each a dict with at least `at` (the
    run's start, ISO) and `head`; with <with_spent>, the passes journaled by
    spent() too; with <pr>, that pull request's alone (and the rows from
    before the journal named one); with <local_only>, the passes here alone,
    each a conversation to price; with <block>, that review block's alone
    (review_blocks.py). The one reader of the file; the report reads it
    through here. A GitHub run's row takes what a later `told` row says of
    it (github_logs), which appends rather than rewrite a row another
    writer may be appending beside; owed() alone marks a row in place."""
    if str(pr) in ("", "null", "None"):
        pr = None
    out, told = [], {}
    try:
        with open(journal, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("told") and row.get("run"):
                    told[(row["run"], row.get("attempt") or 1)] = row
                    continue
                if isinstance(row, dict) and row.get("head") and row.get("at") \
                        and (with_spent or not row.get("spent")) \
                        and (not pr or not row.get("pr") or str(row["pr"]) == str(pr)) \
                        and not (local_only and row.get("source") == "github") \
                        and (not block or str(row.get("block") or "") == str(block)):
                    out.append(row)
    except OSError:
        pass
    for row in out:
        said = told.get((row.get("run"), row.get("attempt") or 1)) if row.get("source") == "github" else None
        if said:
            row.update({k: v for k, v in said.items() if k not in ("told", "run", "attempt")})
    return out


def github_runs(journal, runs, pr=""):
    """Add to the journal the workflow's runs (review_runs in
    review_report.py) that reviewed their head — finished, and green: one
    that stopped on Claude's limit or found no minutes reviewed nothing, and
    a local pass after a move would take its head as read — each attempt
    once (a rerun keeps the run's id)."""
    have = set()
    try:
        with open(journal, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("run"):
                    have.add((row["run"], row.get("attempt") or 1))
    except OSError:
        pass
    new = [r for r in runs if not r.get("running") and r.get("id") and r.get("head")
           and (r.get("conclusion") or "").lower() == "success"
           and (r["id"], r.get("attempt") or 1) not in have]
    if new:
        os.makedirs(os.path.dirname(journal), exist_ok=True)
        with open(journal, "a", encoding="utf-8") as fh:
            for r in new:
                row = {"at": r["start"].isoformat(timespec="seconds"), "seconds": int(r["seconds"]),
                       "head": r.get("head"), "source": "github", "run": r["id"],
                       "attempt": r.get("attempt") or 1}
                # The attempt's own start: a rerun keeps its run's `at`.
                if r.get("began"):
                    row["began"] = r["began"].isoformat(timespec="seconds")
                if pr:
                    row["pr"] = str(pr)
                fh.write(json.dumps(row) + "\n")
    github_logs(journal)


def github_logs(journal, tries=1):
    """The workflow's runs in the journal told what each did, from its job's
    log (review_log.py), in a `told` row after it that rows() reads into
    it: `log` and `root` for the review map's reads, the run's base (as its
    log names it, else the head of its pull request reviewed before it, by
    time), and its answer
    as a local pass records it — `new`, `resolved`, `unthreaded` (findings it
    could not post as threads, which the report counts), `read` (`first` for the
    pull request's first run and a whole rerun, `delta` otherwise),
    `complete`. Once a run: `log` is the kept file, or `gone` when GitHub
    no longer has it; a log not whole yet is asked again next time.
    Appended, never rewritten: a pass here appends its row meanwhile."""
    tree = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(journal)))))
    every = sorted(rows(journal), key=lambda e: e["at"])
    # A run told before `unthreaded` was kept is told again from the log it
    # kept, without asking GitHub.
    todo = [r for r in every if r.get("source") == "github" and r.get("run")
            and ("log" not in r or (r["log"] != "gone" and "unthreaded" not in r))]
    if not todo:
        return
    import review_log  # noqa: E402 — only when a run is to be read
    for row in todo:
        if "log" in row:
            try:
                with open(os.path.join(tree, row["log"]), encoding="utf-8") as fh:
                    said = review_log.summary([json.loads(line) for line in fh if line.strip()])
            except (OSError, ValueError):
                said = None
            if said is None:
                continue
            said["log"], code = row["log"], 0
        else:
            said, code = review_log.fetch(tree, row["run"], row.get("attempt") or 1, tries)
        if code == 3:
            told = {"log": "gone"}
        elif said is not None:
            # The run's own base when its log names it; else the head of
            # its pull request reviewed before it.
            # A base equal to the run's head is kept: the run read nothing new
            # (a rerun on a head already marked); github_unread passes it over
            # for the newest other run on the head, and alone it answers no paths.
            if "base" in said:
                base = said["base"]
            else:
                before = [e["head"] for e in every if e["at"] < row["at"] and e["head"] != row["head"]
                          and (not row.get("pr") or not e.get("pr") or str(e["pr"]) == str(row["pr"]))]
                base = before[-1] if before else None
            told = {"log": said["log"], "root": said["root"], "complete": said["complete"],
                    "read": "first" if said["full_rerun"] or not base else "delta"}
            if base:
                told["base"] = base
            if said["found"] is not None:
                told["new"] = said["found"]
            if said["resolved"] is not None:
                told["resolved"] = said["resolved"]
            told["unthreaded"] = said.get("unthreaded") or 0
        else:
            continue
        told.update({"told": True, "run": row["run"], "attempt": row.get("attempt") or 1})
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(told) + "\n")


def followed(journal, head, pr=""):
    """Whether the files a GitHub run on <head> did not open were read
    here already (a pass with `followup`)."""
    return any(r["head"] == head and r.get("followup") for r in rows(journal, pr=pr or None))


UNKNOWN = "unknown"


def github_unread(cwd, journal, head, pr=""):
    """The files the commits since the last review changed that the
    newest workflow run on <head> other than a rerun that read nothing (one
    alone answers no paths) did not open, as unread() tells them of a pass
    here, with the run's base and its id: (paths, base, run, attempt), no
    paths for a run that read the whole pull request. None when no run of
    the workflow reviewed <head>; UNKNOWN when one did and it cannot be said
    — its log is not kept here, or the branch was rewritten since its base."""
    ran = [r for r in rows(journal, pr=pr or None) if r["head"] == head and r.get("source") == "github"]
    if not ran:
        return None
    # A run that read nothing (its base its head: a rerun on a head already
    # marked) settles nothing an earlier run on the head left unopened.
    read = [r for r in ran if r.get("base") != head]
    if not read:
        return [], "", ran[-1]["run"], ran[-1].get("attempt") or 1
    ran = read
    # The newest run on the head other than one that read nothing counts —
    # a whole rerun among them: an older attempt's log says nothing of what
    # a rerun opened. A rerun keeps its run's `at`
    # (review_runs dates a run by its creation): by the attempt's own start,
    # `began`, and the attempt for rows written before it was kept.
    r = max(ran, key=lambda x: (x.get("began") or x["at"], x.get("attempt") or 1))
    if r.get("log") in (None, "gone"):
        return UNKNOWN
    if r.get("read") != "delta" or not r.get("base"):
        return [], "", r["run"], r.get("attempt") or 1
    # A branch rewritten since: the range is not the run's delta any more.
    try:
        if subprocess.run(["git", "-C", cwd, "merge-base", "--is-ancestor", r["base"], head],
                          capture_output=True, timeout=30).returncode != 0:
            return UNKNOWN
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    return unread(cwd, r["base"], head, "", [(r["log"], r.get("root"))]), r["base"], r["run"], r.get("attempt") or 1


def unread(cwd, base, head, sessions, logs=()):
    """What a pass over the commits since the last review was to read and
    did not open: the files the branch's own commits changed in the range
    (merges brought the rest, reviewed elsewhere), still there at the head,
    less those its conversations read, showed as a diff or named
    (review_map.seen_files, as the review map tells a file read). A pass
    reading a range picks what it opens, and a fix's change to a file it
    passes over would go unread by every pass after it. Nothing when the
    conversation left no transcript here: what it read is not known. A
    GitHub run's is read from its job's log (`logs`, as seen_files takes)."""
    try:
        listed = subprocess.run(["git", "-C", cwd, "log", "--first-parent", "--no-merges", "--name-only",
                                 "--format=", "%s..%s" % (base, head)],
                                capture_output=True, text=True, timeout=60)
        there = subprocess.run(["git", "-C", cwd, "ls-tree", "-r", "--name-only", head],
                               capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if listed.returncode or there.returncode:
        return []
    alive = set(there.stdout.split("\n"))
    changed = sorted({p for p in listed.stdout.split("\n") if p and p in alive})
    if not changed:
        return []
    import review_map  # noqa: E402 — the map's own reader, only when needed
    seen = review_map.seen_files(cwd, [x for x in sessions.split(",") if x], changed, logs=logs)
    if seen is None:
        return []
    return [p for p in changed if p not in seen]


def owed(journal):
    """The last run is not done with its head: its follow-up reads what it
    left (a pass that did not open every file it was to read). Marked as a
    capped run is, so that the next call reads the same range again if the
    follow-up never runs, and the report counts the two as one round."""
    try:
        with open(journal, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return 1
    for i in range(len(lines) - 1, -1, -1):
        try:
            row = json.loads(lines[i])
        except ValueError:
            continue
        # A spent pass reviewed nothing; a `told` row is a GitHub run's.
        if "spent" in row or row.get("told"):
            continue
        row["more"] = True
        lines[i] = json.dumps(row, ensure_ascii=False)
        with open(journal, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return 0
    return 1


def main(argv):
    if not argv:
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "cached" and len(args) in (2, 3):
        # Reviewed, and not left with more to read (a capped pass that the
        # next one never followed, an interrupted review).
        last = rows(args[0], pr=args[2] if len(args) > 2 else None, block=block_now())
        return 0 if last and last[-1]["head"] == args[1] and not last[-1].get("more") else 1
    if cmd == "first" and len(args) == 3:
        # The block's first read is still to come: none of its runs yet, or
        # the last a first read of this head that found the cap.
        mine = rows(args[0], pr=args[2], block=block_now())
        return 0 if not mine or (mine[-1]["head"] == args[1] and mine[-1].get("more")
                                 and mine[-1].get("read") == "first") else 1
    if cmd == "whole" and len(args) == 2:
        mine = [r for r in rows(args[0], pr=args[1], block=block_now()) if r.get("read") == "first"]
        print(mine[-1]["head"] if mine else "")
        return 0
    if cmd == "base" and len(args) in (1, 2):
        last = rows(args[0], pr=args[1] if len(args) > 1 else None)
        print(last[-1]["head"] if last else "")
        return 0
    if cmd == "since" and len(args) in (2, 3):
        # Where the next run starts: the last head reviewed, or — when that
        # head is this one and was left with more — the same range again.
        last = rows(args[0], pr=args[2] if len(args) > 2 else None)
        if not last:
            print("")
        elif last[-1]["head"] == args[1] and last[-1].get("more"):
            print(last[-1].get("base") or "")
        else:
            print(last[-1]["head"])
        return 0
    if cmd == "round" and len(args) in (2, 3):
        # A round is a head: the passes over one head, and a capped head read
        # again later, are the same round.
        mine = rows(args[0], pr=args[2] if len(args) > 2 else None, block=block_now())
        print(len({r["head"] for r in mine if r["head"] != args[1]}) + 1)
        return 0
    if cmd == "prompt" and len(args) == 4:
        return prompt(*args)
    if cmd in ("record",) and len(args) in (8, 9, 10):
        return record(*args)
    if cmd == "spent" and len(args) in (5, 6, 7):
        return spent(*args)
    if cmd == "followed" and len(args) in (2, 3):
        return 0 if followed(*args) else 1
    if cmd == "github-unread" and len(args) in (3, 4):
        # The paths, one a line, after a line "<base> <run> <attempt>";
        # exit 4 when no run reviewed the head, 3 when one did and what it
        # opened is not known (1 is a crash's).
        got = github_unread(*args)
        if got is None:
            return 4
        if got == UNKNOWN:
            return 3
        paths, base, run, attempt = got
        print("%s %s %s" % (base, run, attempt))
        for path in paths:
            print(path)
        return 0
    if cmd == "github-sync" and len(args) == 3:
        # The workflow's finished runs on <branch> into the journal, as the
        # report adds them, each told from its log — waiting up to <tries>
        # looks for one not whole yet (review_github_followup).
        cwd, pr, tries = args
        import review_report  # noqa: E402 — the report's reader of the runs
        branch = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        runs = review_report.review_runs(cwd, branch, review_report.pr_created(cwd, pr))
        if runs is None:
            return 1
        journal = os.path.join(cwd, JOURNAL)
        github_runs(journal, runs, pr)
        github_logs(journal, int(tries))
        return 0
    if cmd == "unread" and len(args) == 4:
        for path in unread(*args):
            print(path)
        return 0
    if cmd == "owed" and len(args) == 1:
        return owed(args[0])
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
