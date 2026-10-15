#!/usr/bin/env python3
#
# A snapshot of a pull request's state for step 4 — the checks and the comments.
#
# Step 4 used to fetch this itself: `gh pr checks`, `gh pr view --comments`,
# `gh api .../pulls/N/comments`. Three calls and a paragraph of instructions for
# them, including an explanation that a non-zero exit code from checks means
# "there are red ones" rather than "the command did not work". All of that is
# work paid for in tokens, and it is the same from feature to feature.
#
# But the main thing is not the saving; it is what the session could not do. A
# green review check does not mean the review took place: the workflow
# can finish successfully having checked nothing — when the workflow file
# diverges from the default branch the action writes "Skipping action due to
# workflow validation" and exits with zero in about 13 seconds. That is what
# happened on one pull request: success in 14 seconds and zero comments in both streams.
# The prompt spent a paragraph explaining the difference between "the reviewer
# never got there" and "there are no complaints", and still left the step unable
# to see it. Here it is arithmetic: the duration, the output and the number of
# comments are known exactly.
#
# A snapshot, not a replacement: the data was gathered at the moment the session
# started, and changing it is exactly what step 4 is busy with. So the block
# names its own timestamp, and the prompt keeps the commands for re-reading.
#
# Silent on any trouble: no gh, no network, no permissions — empty output, and
# the prompt keeps its previous instruction. issue_sync and pr_milestone are
# built the same way.
import json
import os
import re
import subprocess
import sys

# A review run is never shorter than this: that is how long the action's refusal
# on workflow validation takes. The threshold has room to spare — a real review
# runs for minutes.
SKIP_SECONDS = 40

# How to investigate a failing check. This used to say "read the log
# (`gh run view <run-id> --log-failed`)" — and for the review job that advice
# leads the wrong way: the flag replays the reviewer's own streaming transcript
# rather than the error. Once it produced 10744 lines (1.5 MB) of JSON
# containing no cause at all. Step 4 obeyed and spent eight calls getting out:
# it downloaded the job's log to a file, downloaded it again with
# --allow-escape-sequences because of escape sequences, grepped for
# `##[error]`, and finally read the cause with `sed` from line 10600. The cause
# turned out to be in the run's final JSON: api_error_status 429, "You've hit
# your session limit".
#
# The text is one for all three places where a failing check is named — the
# snapshot at start-up and both branches of the summary on return: the advice is
# the same, and having diverged the copies would lie in different ways. In the
# branch "there are both new comments and failing checks" there used to be no
# advice at all, and that was forgotten silently: investigating a failed check
# there takes exactly the same work.
RED_CHECK_ADVICE = (
    "A failing check is a review comment like any other, only written by a "
    "machine: find the cause and fix it. Start with `gh run view <run-id> "
    "--json conclusion,jobs` to see which step failed.\n\n"
    "For the Claude review job, don't reach for `--log-failed`: it replays the "
    "reviewer's streamed transcript, which runs to megabytes of JSON with no "
    "error line in it. The cause is in the run's result — grep the job log "
    "for `##[error]` or `is_error:true` and read `api_error_status` and "
    "`result` next to it.\n\n"
    "`api_error_status: 429` with a `result` naming a session limit means the "
    "reviewer bot ran out of quota mid-run. Nothing in the diff caused it and "
    "no change to the diff will clear it: rerun after the reset "
    "(`gh run rerun <run-id> --failed`), and if the reset is hours away, say "
    "so plainly instead of hunting for a fault that isn't there."
)


def gh(args, cwd=None):
    """gh's output, or None. Errors are swallowed: a snapshot is not worth
    stopping the step for."""
    try:
        done = subprocess.run(["gh"] + args, cwd=cwd, capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def gh_json(args, cwd=None):
    out = gh(args, cwd)
    if out is None:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    # A project reviewed on this machine does not run its flow on GitHub
    # Actions at all — it chose that because the minutes ran out, and with
    # none left every workflow still starts and fails at once, red. So no
    # verdict of the cycle may rest on them: the checks are taken out of the
    # pull request as read here, its one door, and what is left is what does
    # not run on Actions (a Vercel deployment). What the Actions checks did
    # is the regression's `local` stage, which sclaude runs itself.
    if (args[:2] == ["pr", "view"] and isinstance(data, dict)
            and "statusCheckRollup" in data and review_mode(cwd) == "local"):
        data["statusCheckRollup"] = without_actions(data.get("statusCheckRollup") or [])
    return data


_MODES = {}


def review_mode(cwd):
    """`github`, `local` or `off`: `review` in .sclaude/config.json, read the
    way project_review_mode in project.sh reads it — the main checkout first,
    the tree only where the main checkout has no such key."""
    key = cwd or os.getcwd()
    if key in _MODES:
        return _MODES[key]
    roots = []
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], cwd=cwd, capture_output=True,
                                text=True, timeout=30).stdout.strip()
        if common:
            roots.append(os.path.dirname(common))
    except (OSError, subprocess.SubprocessError):
        pass
    roots.append(key)
    mode = "github"
    for root in roots:
        try:
            with open(os.path.join(root, ".sclaude", "config.json")) as fh:
                value = json.load(fh).get("review")
        except (OSError, ValueError, AttributeError):
            continue
        if value is not None:
            mode = value if value in ("local", "off") else "github"
            break
    _MODES[key] = mode
    return mode


def without_actions(rollup):
    """The rollup without what GitHub Actions wrote: its check runs, which
    name their workflow, and the findings status its review workflow posts."""
    return [c for c in rollup if isinstance(c, dict)
            and not c.get("workflowName")
            and (c.get("context") or "") != FINDINGS_CHECK]


def duration(started, finished):
    """The seconds between two ISO timestamps, or None."""
    if not started or not finished:
        return None
    import datetime
    try:
        a = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
        b = datetime.datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (b - a).total_seconds()


def checks_table(rollup):
    """The rows of the checks table."""
    rows = []
    for c in rollup:
        name = c.get("name") or c.get("context") or "?"
        state = (c.get("state") or c.get("conclusion") or "").upper()
        rows.append((name, state, c.get("startedAt"), c.get("completedAt"),
                     c.get("link") or c.get("detailsUrl") or "",
                     c.get("workflowName") or ""))
    return rows


def review_verdict(rows, inline_count, issue_count):
    """Whether the review took place — or the check is green while there was no
    review.

    Returns a string for the prompt, or None when there is nothing to judge.
    """
    for name, state, started, completed, _, workflow in rows:
        if not is_claude_review(name, workflow):
            continue
        if state not in ("SUCCESS", "PASS", "COMPLETED", "NEUTRAL"):
            # A failing check is a comment in its own right, and the prompt
            # already says so. There is nothing to judge here.
            return None
        seconds = duration(started, completed)
        if inline_count == 0 and issue_count == 0 and \
                seconds is not None and seconds < SKIP_SECONDS:
            return (
                "**Check `%s` is green, but no review happened.** It took %d "
                "seconds and left no comments — that's how long a workflow "
                "validation failure takes, not a code review. So the empty "
                "comment list below means \"the reviewer never ran\", not "
                "\"no objections\": don't mistake one for the other and don't "
                "treat the PR as reviewed. If there are no human comments "
                "either, say so plainly."
                % (name, round(seconds))
            )
        if inline_count == 0 and issue_count == 0:
            return (
                "Check `%s` is green and ran for %s, but left no comments. "
                "Probably no objections — but confirm the review actually ran "
                "before treating this as approval."
                % (name, "%ds" % round(seconds) if seconds else "an unknown time")
            )
    return None


def parse_ts(value):
    """An ISO timestamp as a timezone-aware datetime, or None."""
    if not value:
        return None
    import datetime
    try:
        stamp = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    # We treat a naive timestamp as local: `date -Iseconds` writes an offset,
    # but a feature's state also survives being edited by hand.
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    return stamp


def render_new(cwd, pr, repo, since):
    """The comments that appeared after the `since` mark — a block for returning
    to step 4.

    Returns an empty string when there is nothing new: the session remembers
    everything that was there when it started anyway, and retelling it means
    spending context on what is already in it.

    We judge by creation time rather than by the number of comments: a comment
    may have been deleted, and then the counter would stay the same alongside a
    new comment.

    The mark comes from the transcript's last entry rather than from the step's
    start. The difference is not cosmetic: step 4's session lives for hours and
    reads the PR all that time, so between its start and its exit comments have
    time both to appear and to be dealt with. On feature
    20-change-where-user-logouts the session started at 06:15Z and finished at
    06:48Z, and it dealt with a comment from 06:30Z itself — counting from the
    start would have shown it as new.
    """
    mark = parse_ts(since)
    if not pr or mark is None:
        return ""

    view = gh_json(["pr", "view", str(pr), "--json",
                    "statusCheckRollup,comments,headRefOid"], cwd=cwd)
    if view is None:
        return ""

    fresh = []
    for c in view.get("comments") or []:
        stamp = parse_ts(c.get("createdAt"))
        body = (c.get("body") or "").strip()
        if stamp is None or not body or stamp <= mark:
            continue
        author = ((c.get("author") or {}).get("login")) or "?"
        fresh.append(("**Discussion — %s:**" % author, body))

    inline = gh_json(["api", "repos/%s/pulls/%s/comments" % (repo, pr),
                      "--paginate"], cwd=cwd) if repo else None
    for c in inline if isinstance(inline, list) else []:
        stamp = parse_ts(c.get("created_at"))
        body = (c.get("body") or "").strip()
        if stamp is None or not body or stamp <= mark:
            continue
        author = ((c.get("user") or {}).get("login")) or "?"
        path = c.get("path") or "?"
        line = c.get("line") or c.get("original_line") or "?"
        fresh.append(("**`%s:%s` — %s:**" % (path, line, author), body))

    # Failing checks are a comment too, and on return they mean the same as a
    # new comment: the work is not finished. But unlike comments their state
    # does not accumulate, so we show the current one, without comparing against
    # the mark.
    rows = checks_table(view.get("statusCheckRollup") or [])
    red = [r for r in rows if r[1] not in ("SUCCESS", "PASS", "COMPLETED",
                                           "NEUTRAL", "SKIPPED", "")]
    # The findings check stays red after the person resolves by hand the
    # threads they kept: it is not run again for that. close_state already
    # lets step 4 close on such a red; told to a session as news, it woke the
    # review of a pull request only to comment `/review` and turn it green.
    if any(r[0] == FINDINGS_CHECK for r in red) and findings_red_explained(cwd, pr, repo, view):
        red = [r for r in red if r[0] != FINDINGS_CHECK]

    if not fresh and not red:
        return ""

    out = []
    if fresh:
        out.append("New review comments have appeared on PR #%s since this "
                   "session last looked. Handle them the same way as the "
                   "rest: fix what you agree with, and where you don't, "
                   "explain why to me and leave the decision to me."
                   % pr)
        out.append("")
        for head, body in fresh:
            out.append(head)
            out.append("")
            out.append(body)
            out.append("")
    if red:
        if fresh:
            out.append("Checks are red as well: %s.\n\n%s"
                       % (", ".join("`%s`" % r[0] for r in red),
                          RED_CHECK_ADVICE))
        else:
            out.append("No new comments on PR #%s, but its checks are red: "
                       "%s.\n\n%s"
                       % (pr, ", ".join("`%s`" % r[0] for r in red),
                          RED_CHECK_ADVICE))
        out.append("")

    return "\n".join(out).rstrip("\n")


# The pull request's review threads that are still open, each as its first
# comment followed by the replies, plus the resolved ones in short.
#
#   (threads, resolved) — threads as dicts with path, line, outdated and
#   comments [{author, body}]; resolved as dicts with path, line, finding and
#   resolution, one sentence each; (None, []) when GitHub cannot answer.
#
# Through GraphQL because only it knows a thread is resolved: the REST list of
# comments carries every comment ever left, and a fresh review session handed
# that list re-read every round already closed — once, dozens of findings
# and their "Resolved automatically" replies, ahead of the few still open. It
# was also read with `--paginate` alone, which prints one array per page, so
# past thirty comments the parse failed and the snapshot showed no inline
# comments at all.
THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved isOutdated path line originalLine
          comments(first: 50) { nodes { author { login } body createdAt url } }
        }
      }
    }
  }
}
"""


# A comment cut to its claim, for the list of resolved threads. A finding opens
# with the claim in bold and runs on in the same paragraph, so the bold span is
# the claim; the resolver answers "Resolved automatically: fixed in <sha>. <how>",
# and the prefix says nothing the arrow does not.
HEADLINE_CHARS = 200
RESOLVER_PREFIX = "Resolved automatically: "
# The author's decline: a reply starting so, from anyone but a Bot, counts the
# thread as declined. Which reply decides is FINDINGS_DECLINED's rule, in the
# project's .github/workflows/claude-code-review.yml; review_report.py follows it.
DECLINE_PREFIX = "Left as it is"
# The last line of every finding and resolving reply a review run on this
# machine posts (local_review.py): it posts under the person's account, and
# this is how its words are told from theirs.
LOCAL_SIGNATURE = "<sub>Local review"


def headline(body):
    line = next((l.strip() for l in (body or "").splitlines() if l.strip()), "")
    if line.startswith("**") and line.find("**", 2) > 2:
        line = line[:line.find("**", 2) + 2]
    if line.startswith(RESOLVER_PREFIX):
        line = line[len(RESOLVER_PREFIX):]
    return line if len(line) <= HEADLINE_CHARS else line[:HEADLINE_CHARS - 1] + "…"


def open_threads(cwd, pr, repo):
    if not repo or "/" not in repo:
        return None, []
    owner, name = repo.split("/", 1)
    threads, resolved, after = [], [], None
    while True:
        args = ["api", "graphql", "-f", "query=%s" % THREADS_QUERY,
                "-F", "owner=%s" % owner, "-F", "name=%s" % name,
                "-F", "number=%s" % pr]
        if after:
            args += ["-f", "after=%s" % after]
        data = gh_json(args, cwd=cwd)
        try:
            page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        except (TypeError, KeyError):
            return None, []
        for t in page.get("nodes") or []:
            comments = [{"author": ((c.get("author") or {}).get("login")) or "?",
                         "body": (c.get("body") or "").strip()}
                        for c in ((t.get("comments") or {}).get("nodes") or [])]
            path = t.get("path") or "?"
            line = t.get("line") or t.get("originalLine") or "?"
            if t.get("isResolved"):
                resolved.append({
                    "path": path, "line": line,
                    "finding": headline(comments[0]["body"] if comments else ""),
                    "resolution": headline(comments[-1]["body"]
                                           if len(comments) > 1 else ""),
                })
                continue
            first = ((t.get("comments") or {}).get("nodes") or [{}])[0] or {}
            threads.append({
                "path": path,
                "line": line,
                "outdated": bool(t.get("isOutdated")),
                "created": first.get("createdAt") or "",
                "url": first.get("url") or "",
                "comments": comments,
            })
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return threads, resolved
        after = info.get("endCursor")


# Threads the person decided to leave as they are.
#
# A finding the person declines stays open on GitHub: the review does not close
# what was not fixed, and resolving it is the person's own act. Every review
# session used to meet it again as an open thread and ask again — once the
# same `path:line` was put to the person in three rounds running, each
# answered "leave it", and each report said "you close the thread" somewhere in
# its middle, with no link.
#
# So the session that hears the decision writes it down, one line per thread:
#
#     <the thread's link>\t<the decision, in a line>
#
# and from then on the thread is the person's: the snapshot lists it apart and
# tells the session not to ask, a review is not reopened for it, and sclaude
# prints the links to resolve at the end of every review session
# (review_yours_report in run.sh). The link is the thread's first comment's
# url — `…/pull/161#discussion_r4218743695` — which is what both the snapshot
# and `gh api …/pulls/<pr>/comments` (as html_url) give.
YOURS_FILE = ".sclaude/local/feature/review-yours"


def yours(cwd):
    """{link: decision} from the worktree's review-yours file; {} when none."""
    import os
    out = {}
    try:
        with open(os.path.join(cwd, YOURS_FILE)) as fh:
            for line in fh:
                found = re.search(r"https://\S+#discussion_r\d+", line)
                if found:
                    note = line[found.end():].strip(" \t\n—-:")
                    out[found.group(0)] = note
    except OSError:
        pass
    return out


def split_yours(cwd, threads):
    """(the person's open threads, the rest)."""
    mine = yours(cwd)
    return ([t for t in threads if t.get("url") in mine],
            [t for t in threads if t.get("url") not in mine])


def open_since(cwd, pr, repo, since):
    """(open before `since`, open from `since` on) — None when unreadable.

    What a review session closed by the orchestrator left behind, split by
    whose it is: a thread open since before the session began was one it was
    fixing, and goes back to it; one opened after is a new round's, and goes to
    a fresh session. `since` is an ISO time; a thread with no readable date
    counts as old, where it is looked at again rather than dropped.
    """
    import datetime

    def parse(t):
        try:
            d = datetime.datetime.fromisoformat((t or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)

    threads, _ = open_threads(cwd, pr, repo)
    if threads is None:
        return None
    # The person's threads are nobody's work here: see YOURS_FILE.
    threads = split_yours(cwd, threads)[1]
    start = parse(since)
    newer = sum(1 for t in threads
                if start and parse(t["created"]) and parse(t["created"]) >= start)
    return len(threads) - newer, newer


def thread_counts(cwd, pr, repo, since=""):
    """(open now, opened at or after `since`) — None when unreadable.

    A thread is dated by its first comment. `since` is an ISO time with any
    offset; empty counts nothing as new.
    """
    import datetime

    def parse(t):
        try:
            d = datetime.datetime.fromisoformat((t or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)

    if not repo or "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    start = parse(since) if since else None
    opened, new, after = 0, 0, None
    while True:
        args = ["api", "graphql", "-f", "query=%s" % THREADS_QUERY,
                "-F", "owner=%s" % owner, "-F", "name=%s" % name,
                "-F", "number=%s" % pr]
        if after:
            args += ["-f", "after=%s" % after]
        data = gh_json(args, cwd=cwd)
        try:
            page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        except (TypeError, KeyError):
            return None
        for t in page.get("nodes") or []:
            if not t.get("isResolved"):
                opened += 1
            first = ((t.get("comments") or {}).get("nodes") or [{}])[0]
            when = parse(first.get("createdAt"))
            if start and when and when >= start:
                new += 1
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return opened, new
        after = info.get("endCursor")


def render(cwd, pr, repo):
    if not pr:
        return ""

    view = gh_json(["pr", "view", str(pr), "--json",
                    "statusCheckRollup,reviewDecision,mergeable,comments,"
                    "title,url,headRefOid"], cwd=cwd)
    if view is None:
        return ""

    rows = checks_table(view.get("statusCheckRollup") or [])
    issue_comments = view.get("comments") or []
    threads, resolved = open_threads(cwd, pr, repo)
    mine, threads = split_yours(cwd, threads or [])
    decided = yours(cwd)

    out = []
    red = [r for r in rows if r[1] not in ("SUCCESS", "PASS", "COMPLETED",
                                           "NEUTRAL", "SKIPPED", "")]

    if rows:
        out.append("### PR checks")
        out.append("")
        out.append("| Check | State |")
        out.append("|---|---|")
        for name, state, started, completed, *_ in rows:
            seconds = duration(started, completed)
            shown = state or "?"
            if seconds is not None:
                shown += " · %ds" % round(seconds)
            out.append("| `%s` | %s |" % (name, shown))
        out.append("")
        if red:
            out.append("Red: %s.\n\n%s"
                       % (", ".join("`%s`" % r[0] for r in red),
                          RED_CHECK_ADVICE))
            out.append("")

    verdict = review_verdict(rows, len(threads), len(issue_comments))
    if verdict:
        out.append(verdict)
        out.append("")

    out.append("### Comments")
    out.append("")
    if not threads and not issue_comments:
        out.append("No open review threads and no discussion as of this snapshot.")
        out.append("")
    # A resolved thread is shown only where a thread is still open on the same
    # file: there a new finding can undo an earlier fix. Once that happened
    # three times in one chain (sweep, guard, action, guard again), each round
    # in a fresh session that could not see what the last one settled.
    open_paths = {t["path"] for t in threads}
    nearby = [r for r in resolved if r["path"] in open_paths]
    if resolved:
        out.append("%d review thread%s already resolved: what they asked for is "
                   "done." % (len(resolved), "" if len(resolved) == 1 else "s"))
        out.append("")
    if nearby:
        out.append("Resolved on the files that still have open threads. A fix "
                   "that would undo one of these is a reversal, not a fix:")
        out.append("")
        for r in nearby:
            out.append("- `%s:%s` %s → %s" % (r["path"], r["line"], r["finding"],
                                              r["resolution"] or "closed with no reply"))
        out.append("")
    for c in issue_comments:
        author = ((c.get("author") or {}).get("login")) or "?"
        body = (c.get("body") or "").strip()
        if not body:
            continue
        out.append("**Discussion — %s:**" % author)
        out.append("")
        out.append(body)
        out.append("")
    if mine:
        out.append("**Left as they are by the person — theirs to resolve on GitHub.** "
                   "They decided these in an earlier session. Don't fix them and "
                   "don't ask about them again; list them, with their links, under "
                   "\"Resolve on GitHub yourself\" in your report:")
        out.append("")
        for t in mine:
            out.append("- `%s:%s` %s — %s" % (t["path"], t["line"], t["url"],
                                              decided.get(t["url"]) or "leave as it is"))
        out.append("")
    for t in threads:
        first, replies = (t["comments"] or [{"author": "?", "body": ""}])[0], t["comments"][1:]
        if not first["body"]:
            continue
        out.append("**`%s:%s`%s — %s:** %s" % (t["path"], t["line"],
                                               " (outdated position)" if t["outdated"] else "",
                                               first["author"], t.get("url") or ""))
        out.append("")
        out.append(first["body"])
        out.append("")
        for r in replies:
            if r["body"]:
                out.append("> **reply — %s:** %s" % (r["author"], r["body"].replace("\n", "\n> ")))
                out.append("")

    lost = unposted_findings(cwd, repo, view.get("headRefOid") or "",
                             view.get("statusCheckRollup") or [], issue_comments)
    if lost:
        run_id, reports = lost
        out.append("### Review findings that reached no thread")
        out.append("")
        out.append("The findings check counts these as posted in a comment, but the "
                   "review posted them nowhere: handed a commit range, the code-review "
                   "skill ignores --comment. This is its report, from the log of run "
                   "%s — no need to fetch it. Treat each finding in it like a review "
                   "thread: fix it, or say in your report why not. There is no thread "
                   "to reply in or resolve; the next review run reads the same range "
                   "again." % run_id)
        out.append("")
        for text in reports:
            out.append(text)
            out.append("")

    return "\n".join(out).rstrip("\n")


def feature_in_history(cwd):
    """Whether .sclaude/local/feature/ got into the branch's commits — a block for step 3, or
    empty.

    The check is deterministic and almost always clean, so the block appears
    only when there is something to talk about: a prompt with an "all clean"
    paragraph is bytes for nothing.
    """
    try:
        done = subprocess.run(
            ["git", "log", "origin/main..HEAD", "--name-only", "--format="],
            cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    hits = sorted({line for line in done.stdout.splitlines()
                   if line.startswith(".sclaude/local/feature/") or line == ".sclaude/local/feature"})
    if not hits:
        return ""
    return (
        "**The `.sclaude/local/feature/` directory got into the branch history** — here's "
        "what shows up in the commits:\n\n%s\n\nStrip it from the branch "
        "history before opening the pull request."
        % "\n".join("- `%s`" % h for h in hits)
    )


# The name of the check the review workflow writes after every run: `success`
# with no unresolved finding left on the pull request, `failure` otherwise. Its
# `external_id` is "reviewed" only when the review actually read the commits —
# the workflow-validation skip succeeds in seconds and is marked "not-reviewed".
#
# The workflow writes it twice under this one name: a check run, which is the
# record (the mark, the title and summary read below), and a commit status,
# which is the signal — the check run can land in a check suite the rollup
# hides. In the rollup the status carries the name as `context`, not `name`.
#
# Coupled with `FINDINGS_CHECK` in the project's claude-code-review.yml, which
# writes it and looks its own marks up by it: change both or neither.
FINDINGS_CHECK = "Counts Green/Red sign based on open review comments — whole PR (no AI)"


def names_review(name):
    """Whether a check's name has "review" in it as a word, the findings check
    aside: that one is written by the review, it is not the review.

    As a word: Vercel's "Preview Comments" check contains the letters, and
    matching them left a project with no review workflow waiting the full
    REVIEW_WAIT_MAX on every feature.
    """
    import re
    name = (name or "").lower()
    return (name != FINDINGS_CHECK.lower()
            and re.search(r"(^|[^a-z])review([^a-z]|$)", name) is not None)


def is_claude_review(name, workflow=""):
    """Whether a check is the Claude review job. The job's own name need not say
    "Claude" — "Review — delta, …" does not — so its workflow's name counts.
    """
    return names_review(name) and "claude" in ("%s %s" % (name, workflow)).lower()

GREEN = ("SUCCESS", "NEUTRAL", "SKIPPED")


def running(check):
    """Whether a rollup entry has not finished: a check run not completed, or
    a commit status still pending."""
    status = (check.get("status") or "").upper()
    state = (check.get("conclusion") or check.get("state") or "").upper()
    return bool(status and status != "COMPLETED") or state in ("PENDING", "EXPECTED", "")


def red_checks(rollup):
    """The names of the finished checks that are not green, in rollup order."""
    red = [c.get("name") or c.get("context") or "?" for c in rollup
           if (c.get("conclusion") or c.get("state") or "").upper() not in GREEN]
    # The findings verdict comes as a check run and a status: it is one check.
    return [r for i, r in enumerate(red) if r != FINDINGS_CHECK or FINDINGS_CHECK not in red[:i]]


# How long after a push GitHub may take to register a pull request's checks.
CHECKS_GRACE_SECONDS = 300


def recent(created, cwd):
    """Whether the PR was opened, or HEAD committed, within the grace period."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    stamps = []
    opened = parse_ts(created)
    if opened:
        stamps.append(opened)
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cI"], cwd=cwd,
                             capture_output=True, text=True, timeout=30).stdout.strip()
        committed = parse_ts(out)
        if committed:
            stamps.append(committed)
    except (OSError, subprocess.SubprocessError):
        pass
    if not stamps:
        return False
    return (now - max(stamps)).total_seconds() < CHECKS_GRACE_SECONDS


def review_state(cwd, pr, repo):
    """Whether step 4 has anything to answer, as one word.

    clean    the review ran on the pushed head, left nothing open, every check
             is green, and no person has said anything: no session is needed.
    unreviewed  as clean, except that the workflow skipped the review on
             purpose (marked "not-reviewed"): nothing to answer, and nothing a
             session could do to have it run.
    dirty    something to answer — a red check, an open finding, a comment.
    pending  checks are still running, or not registered yet: ask again later.
    unknown  this cannot be decided: the head is not pushed, the project has
             no findings check, or the review did not really run. The session
             opens, as it always did.

    Conservative on purpose. A wrong "clean" skips the only look at review
    comments the cycle has; a wrong "unknown" costs one session.
    """
    view = gh_json(["pr", "view", str(pr), "--json",
                    "headRefOid,statusCheckRollup,createdAt"], cwd=cwd)
    if view is None:
        return "unknown"
    head = view.get("headRefOid") or ""
    try:
        local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                               capture_output=True, text=True,
                               timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if not head or head != local:
        return "unknown"

    rollup = view.get("statusCheckRollup") or []
    # Right after the pull request opens, or the head is pushed, GitHub has not
    # registered its checks yet, and an empty list would read as "everything
    # green". But a repository with no checks at all has an empty list for
    # ever, and waiting on it would cost the whole REVIEW_WAIT_MAX on every
    # feature. So an empty list is "pending" only for a few minutes after the
    # latest of the two moments, and "unknown" after that.
    local = review_mode(cwd) == "local"
    if not rollup and not local:
        return "pending" if recent(view.get("createdAt"), cwd) else "unknown"
    if any(running(c) for c in rollup):
        return "pending"
    # Somebody's own review — a person writing a comment — is not in the
    # findings check, and neither is a red build. The findings check itself is
    # judged below, where it can be told whether its red is still true.
    for c in rollup:
        state = (c.get("conclusion") or c.get("state") or "").upper()
        if state not in GREEN and (c.get("name") or c.get("context") or "") != FINDINGS_CHECK:
            return "dirty"

    # Reviewed on this machine: sclaude ran that review before asking, and no
    # findings check is written on GitHub. With nothing to wait for and no
    # Actions check counted, only what people said is left to read below.
    latest = {} if local else findings_run(cwd, repo, head)
    if latest is None:
        return "unknown"
    reviews = [c for c in rollup if names_review(c.get("name"))]
    if local:
        mark = "not-reviewed"
    elif not latest and reviews and all(
            (c.get("conclusion") or c.get("state") or "").upper() == "SKIPPED" for c in reviews):
        # The workflow skipped the review by its condition — the `no-review`
        # label, which a project whose review is not GitHub's puts on every
        # pull request (local_review.sh). No findings check will come: waiting
        # for one cost the whole REVIEW_WAIT_MAX. What people said is still
        # read below; nothing else is, so it is "unreviewed" at best.
        mark = "not-reviewed"
    elif not latest:
        # The review job may still be about to write it; a project without the
        # workflow never will. A review check in the rollup tells them apart.
        return "pending" if reviews else "unknown"
    elif (latest.get("status") or "") != "completed":
        return "pending"
    elif (latest.get("conclusion") or "") != "success":
        # Red only for threads the person kept or resolved by hand is nothing
        # for a session: close_state answers for those (see YOURS_FILE).
        threads, _ = open_threads(cwd, pr, repo)
        rest = split_yours(cwd, threads or [])[1]
        if threads is None or rest or not findings_explained(
                cwd, repo, head, {t["url"] for t in rest}, latest):
            return "dirty"
    # Marked "not-reviewed": the workflow skipped the review on purpose (its own
    # file differs from main's). No session can make it run, and one opened for
    # it only says so — so this is "unreviewed", which closes the step the way
    # "clean" does, saying the pull request was not reviewed. Anything else
    # without "reviewed" (an older workflow, no mark) stays "unknown".
    if latest:
        mark = latest.get("external_id") or ""
    if mark not in ("reviewed", "not-reviewed"):
        return "unknown"

    # What people said. The bot's own words are covered by the findings check
    # above — its inline findings are what it counts, and its "No issues found"
    # summary is not a request for anything.
    # A review run on this machine posts under the person's own account; its
    # findings and replies carry LOCAL_SIGNATURE, and are the review's words.
    def human(rows):
        return [r for r in (rows or []) if isinstance(r, dict)
                and ((r.get("user") or {}).get("type") or "") != "Bot"
                and LOCAL_SIGNATURE not in (r.get("body") or "")]

    base = "repos/%s" % repo
    comments = gh_json(["api", "%s/issues/%s/comments" % (base, pr), "--paginate"], cwd=cwd)
    inline = gh_json(["api", "%s/pulls/%s/comments" % (base, pr), "--paginate"], cwd=cwd)
    reviews = gh_json(["api", "%s/pulls/%s/reviews" % (base, pr), "--paginate"], cwd=cwd)
    if comments is None or inline is None or reviews is None:
        return "unknown"
    if human(comments) or human(inline):
        return "dirty"
    for r in human(reviews):
        if (r.get("state") or "") == "CHANGES_REQUESTED" or (r.get("body") or "").strip():
            return "dirty"
    return "clean" if mark == "reviewed" else "unreviewed"


# The Claude review job that stopped on its quota: the subscription it runs
# under is the one the sessions on this machine spend, and two features' worth
# of sessions and reviews run it out (it has happened). Nothing in the
# diff caused that and no session can fix it — the job is to be run again once
# the limit resets, which sclaude does by itself (review_quota_rerun in
# run.sh). Read from the job's log, where the action leaves its result:
# `api_error_status: 429` and claude's own "You've hit your … limit ·
# resets 4am (Europe/Lisbon)".
QUOTA_429 = re.compile(r'api_error_status"?\s*[:=]\s*429')
QUOTA_LIMIT = re.compile(r"hit your (?:session |weekly |usage )?limit")
QUOTA_RESETS = re.compile(
    r"resets (?:([A-Z][a-z]{2}) (\d{1,2}), )?(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?: \(([^)]+)\))?")
JOB_LINK = re.compile(r"/actions/runs/(\d+)/job/(\d+)")


def job_log(cwd, repo, job):
    """An Actions job's log, or None.

    The review job's log is full of the reviewer's colour codes, and gh 2.102
    refuses to print such a response — "the response contains terminal escape
    sequences" — and exits 1 unless told --allow-escape-sequences. Without the
    flag every log read here came back None, silently. An older gh does not know
    the flag, so it is tried without it too.
    """
    path = "repos/%s/actions/jobs/%s/logs" % (repo, job)
    return (gh(["api", "--allow-escape-sequences", path], cwd=cwd)
            or gh(["api", path], cwd=cwd))


def quota_reset(text, now=None):
    """When a "resets 6:50pm (Europe/Lisbon)" in `text` comes: seconds since
    the epoch, or 0 when there is none or it cannot be read.

    Without a date it is the next such time after `now`; with one ("Oct 10,
    4am"), that day in the current year.
    """
    import datetime
    found = QUOTA_RESETS.search(text or "")
    if not found:
        return 0
    month, day, hour, minute, half, zone = found.groups()
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(zone or "UTC")
    except Exception:
        return 0
    hour = int(hour) % 12 + (12 if half == "pm" else 0)
    minute = int(minute or 0)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    local = now.astimezone(tz)
    if month:
        try:
            moment = datetime.datetime.strptime(
                "%d %s %s %d %d" % (local.year, month, day, hour, minute),
                "%Y %b %d %H %M").replace(tzinfo=tz)
        except ValueError:
            return 0
        # "resets Jan 2" read on Dec 30 is next year's.
        if moment < local - datetime.timedelta(days=1):
            moment = moment.replace(year=moment.year + 1)
    else:
        moment = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= local:
            moment += datetime.timedelta(days=1)
    return int(moment.timestamp())


def review_quota(cwd, pr, repo):
    """(run id, reset) for a Claude review job on the PR that failed on its
    quota, or None. `reset` is seconds since the epoch, 0 when unknown."""
    view = gh_json(["pr", "view", str(pr), "--json", "statusCheckRollup"], cwd=cwd)
    if view is None:
        return None
    for c in view.get("statusCheckRollup") or []:
        if not is_claude_review(c.get("name") or "", c.get("workflowName") or ""):
            continue
        if (c.get("conclusion") or c.get("state") or "").upper() not in ("FAILURE", "TIMED_OUT"):
            continue
        link = JOB_LINK.search(c.get("detailsUrl") or c.get("link") or "")
        if not link:
            continue
        log = job_log(cwd, repo, link.group(2))
        if not log or not (QUOTA_429.search(log) or QUOTA_LIMIT.search(log)):
            continue
        # Counted from when the job stopped, not from now: a "resets 4am" read
        # at five has reset already, and is not tomorrow's.
        return link.group(1), quota_reset(log, parse_ts(c.get("completedAt")))
    return None


def unpushed(cwd, view):
    """How many commits here an open pull request does not carry; 0 otherwise.

    The one definition of "the branch is pushed", for step 3's closing and
    step 4's. Commits on no remote branch, not "HEAD differs from the pull
    request's head": a head that moved ahead — GitHub's "Update branch", a
    push from another machine — differs too, and no push from here can fix
    that. A pull request that is closed or merged carries nothing more, and
    is not asked.
    """
    if view is None or (view.get("state") or "") != "OPEN":
        return 0
    try:
        out = subprocess.run(["git", "rev-list", "--count", "HEAD", "--not", "--remotes"],
                             cwd=cwd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 0
    count = out.stdout.strip()
    return int(count) if out.returncode == 0 and count.isdigit() else 0


def behind_head(cwd, head):
    """Whether `head` is an older commit of this branch: an ancestor of HEAD
    and not HEAD itself. A head this tree does not have, or one that moved
    ahead (GitHub's "Update branch"), is not."""
    try:
        local = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                               text=True, timeout=30).stdout.strip()
        if not local or local == head:
            return False
        return subprocess.run(["git", "merge-base", "--is-ancestor", head, "HEAD"], cwd=cwd,
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def close_state(cwd, pr, repo):
    """Whether step 4 may close, as one line: `ok`, `pending`, `open: <why>`,
    or `yours: <n>` when only threads the person decided to keep are open.

    Narrower than review_state, which asks whether a session is needed at all
    and counts any comment a person ever left. This asks only whether the
    review has finished with this head and left anything open: a check still
    running, a red one (the findings check among them), or a review thread not
    resolved. Whatever cannot be read is `ok` — the step closed on a human's
    word before this existed, and a network fault must not hold it shut.
    """
    view = gh_json(["pr", "view", str(pr), "--json",
                    "headRefOid,statusCheckRollup,state,createdAt"], cwd=cwd)
    if view is None or (view.get("state") or "") != "OPEN":
        return "ok"
    ahead = unpushed(cwd, view)
    if ahead:
        return "open: %d commit(s) here are not pushed, so the pull request does not carry them" % ahead
    # Pushed, and GitHub still names the commit before it as the head: for a
    # few seconds after a push the pull request answers with the old head, its
    # checks all green and its review long done. Once a friction review pushed
    # its commit after the last round, this read `ok` within the same minute,
    # step 4 closed, and the review of that push left two threads on a pull
    # request nobody was watching any more.
    head = view.get("headRefOid") or ""
    if head and behind_head(cwd, head):
        if recent(None, cwd):
            return "pending"
        return ("open: PR #%s still names %s as its head, behind this branch"
                % (pr, head[:8]))
    rollup = view.get("statusCheckRollup") or []
    if not rollup and review_mode(cwd) != "local":
        return "pending" if recent(view.get("createdAt"), cwd) else "ok"
    if any(running(c) for c in rollup):
        return "pending"
    red = red_checks(rollup)
    threads, _ = open_threads(cwd, pr, repo)
    mine, threads = split_yours(cwd, threads or [])
    if FINDINGS_CHECK in red and findings_explained(
            cwd, repo, view.get("headRefOid") or "", {t["url"] for t in threads}):
        red.remove(FINDINGS_CHECK)
    why = []
    if red:
        why.append("red: " + ", ".join(red))
    if threads:
        why.append("%d review thread(s) open" % len(threads))
    if why:
        return "open: " + "; ".join(why)
    # Only what the person decided to leave is open: nothing for a session,
    # and the step waits for their hand on GitHub. See YOURS_FILE.
    return "yours: %d" % len(mine) if mine else "ok"


def findings_run(cwd, repo, head):
    """The findings check's latest run on `head`: a dict, {} when there is
    none, None when GitHub cannot be read."""
    from urllib.parse import quote
    runs = gh_json(["api", "repos/%s/commits/%s/check-runs?check_name=%s"
                    % (repo, head, quote(FINDINGS_CHECK, safe=""))], cwd=cwd)
    if runs is None:
        return None
    found = [r for r in (runs.get("check_runs") or []) if r.get("name") == FINDINGS_CHECK]
    return found[0] if found else {}


# `sclaude checks`: the wait after a push in step 4, one command and bounded.
#
# The review check registers last: the review job waits for a gate job, so its
# check appears only once the gate has finished, and the findings check later
# still, from a job that waits for the review. `gh pr checks --watch` returns
# when the checks it can see have finished, which right after a push is often
# before either exists — and the session read the rest as final. A loop of the
# session's own waiting for the review fixed that and opened two worse faults:
# with no limit it waited for ever on a push that starts no review (`[skip
# ci]`, the workflow disabled), and with one it stopped quietly, read the
# checks it had as final, and the last push went unreviewed with nobody told.
#
# So the wait is two phases, each bounded by REVIEW_WAIT_MAX, and runs out
# aloud: the review check appears on the pull request's head; then every
# check has finished, the findings check among them. Its answer is a line
# starting with one of the words in CHECKS_VERDICTS, and the exit code next to
# it; sclaude/prompts/review.md tells the session what each means.
CHECKS_GREEN, CHECKS_RED, CHECKS_NO_REVIEW, CHECKS_NOT_DONE, CHECKS_UNREADABLE = range(5)
CHECKS_VERDICTS = {
    CHECKS_GREEN: "green",
    CHECKS_RED: "red",
    CHECKS_NO_REVIEW: "no review",
    CHECKS_NOT_DONE: "not finished",
    CHECKS_UNREADABLE: "could not read",
}
# Reads that may fail in a row before the wait gives up: one blip in half an
# hour of polling is not worth an answer, a network that stays down is.
CHECKS_READ_RETRIES = 4
# How many of the pull request's commits to look through for an earlier review.
CHECKS_HISTORY = 20


def reviewed_before(cwd, pr, repo):
    """(review, findings): whether any of the pull request's commits carries a
    review check, and a findings check. (True, True) when it cannot be read.

    This is what tells a project with a review workflow from one without: the
    head just pushed has no check yet in either, and waiting for a review that
    never comes would cost the full REVIEW_WAIT_MAX on every push — the trap
    names_review was once caught in. Step 4 answers a review, so its pull
    request has had one on an earlier commit. Unreadable counts as reviewed:
    the wait then still ends, and says no review came, where a wrong "no
    review here" would call an unreviewed push finished.
    """
    view = gh_json(["pr", "view", str(pr), "--json", "commits"], cwd=cwd)
    if view is None:
        return True, True
    oids = [c.get("oid") for c in (view.get("commits") or []) if c.get("oid")]
    review = findings = False
    for oid in reversed(oids[-CHECKS_HISTORY:]):
        runs = gh_json(["api", "repos/%s/commits/%s/check-runs?per_page=100" % (repo, oid)],
                       cwd=cwd)
        if runs is None:
            return True, True
        names = [r.get("name") or "" for r in runs.get("check_runs") or []]
        review = review or any(names_review(n) for n in names)
        findings = findings or FINDINGS_CHECK in names
        if review and findings:
            break
    return review, findings


def wait_checks(cwd, pr, repo, limit, period, say=None, clock=None, sleep=None):
    """Wait for the pull request's checks after a push; the exit code, and the
    verdict line printed last. See CHECKS_VERDICTS for the codes.

    Phase 1 waits up to `limit` seconds for a review check on the head
    (names_review decides what is one); phase 2 waits up to `limit` more for
    every check to finish and, where the project has one, for the findings
    check's run on the head — it is written by a job that registers only after
    the review, so the rollup alone can read "all finished" a minute too soon.
    A review check that finished as skipped has no findings check to wait for.
    """
    import time
    say = say or (lambda line: (sys.stdout.write(line + "\n"), sys.stdout.flush()))
    clock = clock or time.monotonic
    sleep = sleep or time.sleep

    def span(seconds):
        return "%d min" % round(seconds / 60) if seconds >= 60 else "%d s" % seconds

    def table(rollup):
        for name, state, *_rest in checks_table(rollup):
            say("  %-12s %s" % (state or "PENDING", name))

    def verdict(code, text, rollup=None):
        if rollup:
            table(rollup)
        say("%s: %s" % (CHECKS_VERDICTS[code], text))
        return code

    # Reviewed on this machine: no review check will come, and the checks
    # Actions would run are not read at all (gh_json); what is left is waited
    # for, and an empty list is finished rather than not registered yet.
    local = review_mode(cwd) == "local"
    expect_review, expect_findings = (False, False) if local else reviewed_before(cwd, pr, repo)
    phase, started, failures, rollup, head = 1 if expect_review else 2, clock(), 0, [], ""
    if local:
        say("This project reviews on this machine: GitHub Actions checks are not read, "
            "only the others are waited for.")
    elif expect_review:
        say("Waiting up to %s for the review check to appear…" % span(limit))
    else:
        say("No review check on this pull request's commits: waiting only for the checks.")
    while True:
        view = gh_json(["pr", "view", str(pr), "--json",
                        "headRefOid,statusCheckRollup,state,createdAt"], cwd=cwd)
        if view is None:
            failures += 1
            if failures >= CHECKS_READ_RETRIES:
                return verdict(CHECKS_UNREADABLE, "GitHub did not answer about PR #%s "
                               "%d times in a row; the checks are unknown." % (pr, failures),
                               rollup)
        else:
            failures = 0
            if (view.get("state") or "") != "OPEN":
                return verdict(CHECKS_UNREADABLE, "PR #%s is %s, not open."
                               % (pr, (view.get("state") or "unknown").lower()))
            ahead = unpushed(cwd, view)
            if ahead:
                return verdict(CHECKS_UNREADABLE, "%d commit(s) here are not pushed: "
                               "push first, then wait." % ahead)
            head = view.get("headRefOid") or ""
            rollup = view.get("statusCheckRollup") or []
            # For a few seconds after a push the pull request still names the
            # commit before it, its checks long finished: see close_state.
            stale = bool(head) and behind_head(cwd, head)
            if stale and not recent(None, cwd):
                return verdict(CHECKS_UNREADABLE, "PR #%s still names %s as its head, "
                               "behind this branch." % (pr, head[:7]))
            if not stale and phase == 1 and any(
                    names_review(c.get("name") or c.get("context")) for c in rollup):
                phase, started = 2, clock()
                say("The review check is on %s; waiting up to %s for every check "
                    "to finish…" % (head[:7], span(limit)))
            if not stale and phase == 2 and finished(cwd, repo, head, rollup,
                                                     expect_findings, view):
                red = red_checks(rollup)
                if red:
                    return verdict(CHECKS_RED, "on %s: %s." % (head[:7], ", ".join(red)),
                                   rollup)
                return verdict(CHECKS_GREEN, "every check on %s has finished green."
                               % head[:7], rollup)
        if clock() - started >= limit:
            sha = head[:7] or "the head"
            if phase == 1:
                return verdict(CHECKS_NO_REVIEW, "No review started on %s within %s — "
                               "this push is not reviewed." % (sha, span(limit)), rollup)
            return verdict(CHECKS_NOT_DONE, "The review on %s is still running or queued "
                           "after %s — this push is not reviewed yet." % (sha, span(limit)),
                           rollup)
        sleep(period)


def finished(cwd, repo, head, rollup, expect_findings, view):
    """Whether every check on `head` has finished, the findings check included
    where the project writes one."""
    if not rollup:
        # Not registered yet, or a project with no checks at all: see review_state.
        # Reviewed on this machine, nothing more is coming.
        return review_mode(cwd) == "local" or not recent(view.get("createdAt"), cwd)
    if any(running(c) for c in rollup):
        return False
    reviews = [c for c in rollup if names_review(c.get("name") or c.get("context"))]
    if not expect_findings or not reviews or all(
            (c.get("conclusion") or c.get("state") or "").upper() == "SKIPPED" for c in reviews):
        return True
    run = findings_run(cwd, repo, head)
    return bool(run) and (run.get("status") or "") == "completed"


def findings_red_explained(cwd, pr, repo, view):
    """Whether the red findings check on the pull request in `view` has nothing
    in it for a session — findings_explained, given the threads still open
    other than the ones the person kept. False on anything unreadable."""
    head = (view or {}).get("headRefOid") or ""
    if not head or not repo:
        return False
    threads, _ = open_threads(cwd, pr, repo)
    if threads is None:
        return False
    rest = split_yours(cwd, threads)[1]
    return findings_explained(cwd, repo, head, {t["url"] for t in rest})


def findings_explained(cwd, repo, head, open_urls, run=None):
    """Whether the red findings check has nothing in it for a session.

    The check counts open threads when the review runs and is not run again
    when a thread is resolved by hand — its own summary says so: "A thread
    resolved by hand does not refresh this check". So after the person
    resolves the threads they kept, it stays red on a head with nothing open,
    and read as "red", it sent the work back to a session with nothing to fix.

    Explained when every finding it lists is either resolved by now or the
    person's (not in `open_urls`, the other open threads), and it lists them
    all — its title counts them. A check whose findings could not be posted as
    threads ("posted as a comment, not as threads") is never explained: those
    are real findings no thread stands for.
    """
    if run is None:
        run = findings_run(cwd, repo, head)
    if not run:
        return False
    output = run.get("output") or {}
    title = output.get("title") or ""
    counted = re.match(r"(\d+) unresolved review finding", title)
    links = set(re.findall(r"https://[^\s)\]]+#discussion_r\d+", output.get("summary") or ""))
    if not counted or int(counted.group(1)) != len(links):
        return False
    return not (links & set(open_urls))


# The findings check's title when the review could not post some findings as
# threads. Coupled with the project's claude-code-review.yml, like FINDINGS_CHECK.
UNTHREADED_TITLE = "posted as a comment, not as threads"
# A line of the review job's log carrying what the code-review skill returned.
SKILL_RESULT = re.compile(r'"content": ("Skill \\"code-review\\" completed.*")\s*,?\s*$')
SKILL_PREAMBLE = re.compile(r'^Skill "code-review" completed[^\n]*\n+(?:Result:\n)?')
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def unposted_findings(cwd, repo, head, rollup, comments):
    """(run id, [the review's reports]) for findings that reached no thread, or None.

    The review job hands the code-review skill a commit range, and with that
    target the skill ignores --comment: its findings come back as text and are
    posted nowhere. The job counts them as `unthreaded` and the findings check
    goes red with "N review findings posted as a comment" — while no such
    comment exists. Once three review sessions in a row had to download the
    job log and grep it to learn what they were supposed to fix.

    Nothing when the fallback comment really was posted (a discussion comment by
    `claude`): it is already in the snapshot.
    """
    from urllib.parse import quote
    if not head or any(((c.get("author") or {}).get("login") or "") == "claude"
                       for c in comments):
        return None
    runs = gh_json(["api", "repos/%s/commits/%s/check-runs?check_name=%s"
                    % (repo, head, quote(FINDINGS_CHECK, safe=""))], cwd=cwd)
    found = [r for r in ((runs or {}).get("check_runs") or [])
             if r.get("name") == FINDINGS_CHECK]
    if not found or UNTHREADED_TITLE not in ((found[0].get("output") or {}).get("title") or ""):
        return None
    for c in rollup:
        if not is_claude_review(c.get("name") or "", c.get("workflowName") or ""):
            continue
        link = JOB_LINK.search(c.get("detailsUrl") or c.get("link") or "")
        log = link and job_log(cwd, repo, link.group(2))
        if not log:
            continue
        reports = []
        for line in log.splitlines():
            m = SKILL_RESULT.search(ANSI.sub("", line))
            if not m:
                continue
            try:
                text = json.loads(m.group(1))
            except ValueError:
                continue
            text = SKILL_PREAMBLE.sub("", text).strip()
            if text:
                reports.append(text)
        if reports:
            return link.group(1), reports
    return None


def yours_open(cwd, pr, repo):
    """The person's threads still open, as lines "link<TAB>path:line<TAB>decision"."""
    threads, _ = open_threads(cwd, pr, repo)
    decided = yours(cwd)
    return ["%s\t%s:%s\t%s" % (t["url"], t["path"], t["line"], decided.get(t["url"]) or "")
            for t in split_yours(cwd, threads or [])[0]]


def main():
    # `--threads <cwd> <pr> <repo> [since]`: "<open> <opened since>", or
    # nothing when it cannot be read. See thread_counts.
    if len(sys.argv) >= 5 and sys.argv[1] == "--threads":
        try:
            got = thread_counts(sys.argv[2], sys.argv[3], sys.argv[4],
                                sys.argv[5] if len(sys.argv) > 5 else "")
        except Exception:
            got = None
        if got is not None:
            sys.stdout.write("%d %d\n" % got)
        return 0
    # `--open-since <cwd> <pr> <repo> <since>`: "<older> <newer>", or nothing
    # when it cannot be read. See open_since.
    if len(sys.argv) >= 6 and sys.argv[1] == "--open-since":
        try:
            got = open_since(*sys.argv[2:6])
        except Exception:
            got = None
        if got is not None:
            sys.stdout.write("%d %d\n" % got)
        return 0
    # `--unpushed <cwd> <pr>`: a number, see unpushed; 0 when unreadable.
    if len(sys.argv) >= 4 and sys.argv[1] == "--unpushed":
        try:
            view = gh_json(["pr", "view", sys.argv[3], "--json", "state"], cwd=sys.argv[2])
            sys.stdout.write("%d\n" % unpushed(sys.argv[2], view))
        except Exception:
            sys.stdout.write("0\n")
        return 0
    # `--quota <cwd> <pr> <repo>`: "<run id> <reset>" for a review that ran
    # out of quota, or nothing. See review_quota.
    if len(sys.argv) >= 5 and sys.argv[1] == "--quota":
        try:
            got = review_quota(sys.argv[2], sys.argv[3], sys.argv[4])
        except Exception:
            got = None
        if got:
            sys.stdout.write("%s %d\n" % got)
        return 0
    # `--yours <cwd> <pr> <repo>`: the person's open threads, see yours_open.
    if len(sys.argv) >= 5 and sys.argv[1] == "--yours":
        try:
            for line in yours_open(sys.argv[2], sys.argv[3], sys.argv[4]):
                sys.stdout.write(line + "\n")
        except Exception:
            pass
        return 0
    # `--close <cwd> <pr> <repo>`: one line, see close_state.
    if len(sys.argv) >= 5 and sys.argv[1] == "--close":
        try:
            sys.stdout.write(close_state(sys.argv[2], sys.argv[3], sys.argv[4]) + "\n")
        except Exception:
            sys.stdout.write("ok\n")
        return 0
    # `--wait <cwd> <pr> <repo> <seconds>`: `sclaude checks`, see wait_checks.
    # SCLAUDE_CHECKS_PERIOD sets the seconds between reads.
    if len(sys.argv) >= 6 and sys.argv[1] == "--wait":
        import os
        try:
            period = float(os.environ.get("SCLAUDE_CHECKS_PERIOD") or 15)
            return wait_checks(sys.argv[2], sys.argv[3], sys.argv[4],
                               float(sys.argv[5]), period)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            sys.stdout.write("%s: the wait broke off (%s); the checks are unknown.\n"
                             % (CHECKS_VERDICTS[CHECKS_UNREADABLE], exc))
            return CHECKS_UNREADABLE
    # `--state <cwd> <pr> <repo>`: one word, see review_state.
    if len(sys.argv) >= 5 and sys.argv[1] == "--state":
        try:
            sys.stdout.write(review_state(sys.argv[2], sys.argv[3], sys.argv[4]) + "\n")
        except Exception:
            sys.stdout.write("unknown\n")
        return 0
    # The fourth argument is a timestamp: with it we assemble not the whole
    # snapshot but only what appeared after it. That is how step 4 returns to the
    # review without re-reading from scratch what it has already dealt with.
    if len(sys.argv) < 4:
        return 0
    cwd, pr, repo = sys.argv[1], sys.argv[2], sys.argv[3]
    since = sys.argv[4] if len(sys.argv) > 4 else ""
    try:
        if since:
            sys.stdout.write(render_new(cwd, pr, repo, since))
        else:
            sys.stdout.write(render(cwd, pr, repo))
    except Exception:
        # The snapshot is a side benefit. Bringing the step down for its sake
        # would mean trading a working cycle for a summary that was not
        # gathered.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
