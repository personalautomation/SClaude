#!/usr/bin/env python3
#
# Whether another round of the automatic review is worth it: a report built
# from the pull request's review threads and the feature's state, with no model
# in the loop. `sclaude review-report <feature>` prints it, and sclaude prints
# it at the close of every review round, where the person decides whether the
# feature goes on being fixed.
#
#   review_report.py <worktree> <pr> <repo> [branch] [feature]
#
# What it measures is what reviews and test campaigns are usually judged by:
#
#   * findings per round — the discovery rate, a column the person reads the
#     trend off themselves: a sentence judging it had a corner case for every
#     shape of a few small numbers, and said "climbing" over 1, 2, 1;
#   * the share acted on — findings fixed against findings closed without a
#     fix. Field studies of review bots put acceptance near a third, and a
#     share acted on below 40% is the usual sign a reviewer has turned to
#     noise;
#   * fix-induced findings — new findings on lines an earlier round's fix
#     touched (imperfect debugging: a fix that brings the next finding with
#     it). Growing, it means the fixes are feeding the review;
#   * what it costs, in two parts: the review itself — each pass on this
#     machine, from Claude Code's own account in its transcript (claude_usage),
#     unknown for the workflow's review — and the fixing sessions' spend as the
#     status line reports it (run_cost); and their time;
#   * findings raised again after a decline — a finding that repeats one the
#     author closed without a fix: near it in the same file, or cited by the
#     reply that declined it again ("as on r<id>", sclaude/prompts/review.md).
#     The review workflow is told the declined ones; this shows whether it
#     listens.
#
# A thread is classified by what happened to it, never by reading it:
#
#   no fix     resolved, and the last decision reply is the author's "Left as
#              it is …" (DECLINE_PREFIX, the review workflow's own rule); or
#              open and written in review-yours (left for the person to
#              resolve);
#   fixed      resolved any other way: the resolver's "Resolved automatically:
#              …" reply, or none at all — a fixing session or a person closing
#              a fixed finding writes nothing;
#   open       everything else.
#
# A round is one run of the automatic review: a thread belongs to the last run
# that started before it was posted. Not the review id GitHub gives a comment —
# the review posts each inline comment as a review of its own, so that counted
# every finding as a round. A run that found nothing is a round with nothing.
# A round opens with its findings and
# goes on with their fix: the review session (state.json) whose launches began
# after the run and before the next one is the one that answered it. Its row
# reads in that order — find, fix, result — and a value that will come but has
# not yet is WAIT, never a zero.
#
# Silent on trouble, like pr_context.py: no gh, no network — it says what it
# could not read and prints the rest.
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from pr_context import (SKIP_SECONDS, decline_of, gh_json, is_claude_review,  # noqa: E402
                        moved_for, review_mode, still_open_reply, thread_line, yours)
from local_review import rows as journal_rows  # noqa: E402
import claude_usage  # noqa: E402

QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved path line originalLine
          comments(first: 50) {
            nodes { author { __typename } body createdAt url }
          }
        }
      }
    }
  }
}
"""

# How close a new finding has to sit to an earlier one, in lines, to count as
# about the same code. A fix moves a few lines around; a finding a screen away
# is about something else.
NEAR_LINES = 5

# Below this share acted on, the review is mostly asking for things nobody
# fixes (see the header).
ACTED_ON_FLOOR = 0.4

# How many settled findings, newest first, the share acted on is taken over.
ACTED_ON_SAMPLE = 10

# Without the runs (no gh run list), threads further apart than this start a
# new round: one run posts its findings within minutes.
ROUND_GAP = datetime.timedelta(minutes=10)

# A discussion id in a thread link, and one cited in a reply ("as on r123").
DISCUSSION = re.compile(r"discussion_r(\d+)")
CITED = re.compile(r"(?:discussion_|\b)r(\d{6,})\b")

# Colour on a terminal only: the report is also read back by tests and sent
# nowhere else in colour. NO_COLOR is honoured, as everywhere.
COLOUR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(text, code):
    return "\033[%sm%s\033[0m" % (code, text) if COLOUR and code else text


GREEN, YELLOW, RED, BOLD, DIM = "32", "33", "31", "1", "2"


def rule(title):
    """A section's heading, as sclaude's other sections are drawn."""
    return paint("── %s %s" % (title, "─" * max(3, 56 - len(title))), BOLD)


# A cell whose value will come but has not yet: a review run still going, a
# fix not begun, a launch whose cost is taken when it ends. "—" is for what
# will never be known (the workflow's review is not priced).
WAIT = "w"

# The table's columns after the round's number, in the cycle's order: what
# the review found, the fix that answered it, what became of the findings.
# (heading, format, group)
COLUMNS = (
    ("started", "%-11s", "find"), ("took", "%6s", "find"), ("cost", "%6s", "find"),
    ("found", "%5s", "find"), ("on fixes", "%8s", "find"), ("repeats", "%7s", "find"),
    ("session", "%8s", "fix"), ("took", "%6s", "fix"), ("cost", "%6s", "fix"),
    ("declined", "%8s", "fix"), ("fixed", "%5s", "result"), ("waiting", "%7s", "result"),
)
FIXED_COL, WAITING_COL = 10, 11


# The review block a round read, and its number among that block's rounds,
# when the pull request is read in review blocks (review_blocks.py): "3.7" is
# block 3's seventh round, as the review's map names it ("Block 3 · round 7",
# roundName in process_review.js); the pass over the seams after the last
# block is "seams.1" (SEAMS). The column is left out when no round read a
# block.
BLOCK_FMT = "%-8s"


def block_rounds(groups):
    """Each round's "<block>.<n>", "" for a round that read no block; None
    when none did."""
    if not any(g.get("block") for g in groups):
        return None
    seen, out = {}, []
    for g in groups:
        b = g.get("block")
        if b:
            seen[b] = seen.get(b, 0) + 1
            out.append("%s.%d" % (b, seen[b]))
        else:
            out.append("")
    return out


def heading(blocks=False):
    """The table's two heading lines: the groups over their columns, then the
    columns; <blocks> adds the block column after the round's number."""
    spans, widths = [], {}
    for name, fmt, group in COLUMNS:
        width = int(re.sub(r"\D", "", fmt))
        widths[group] = widths.get(group, -1) + width + 1
    for group in ("find", "fix", "result"):
        spans.append(("── %s " % group).ljust(widths[group], "─"))
    names = " ".join(fmt % name for name, fmt, _ in COLUMNS)
    lead = ("%-5s " + BLOCK_FMT) % ("", "") if blocks else "%-5s" % ""
    first = ("%-5s " + BLOCK_FMT) % ("round", "block") if blocks else "%-5s" % "round"
    return (paint("  %s %s" % (lead, " ".join(spans)), DIM),
            paint("  %s %s" % (first, names), DIM))


def row(cells, base="", rnd="", blk=None):
    """A table row, its waiting findings red and its fixes green once padded:
    the colour codes would otherwise count in the widths. <base> colours the
    rest of the row, cell by cell, so that red and green keep theirs; WAIT is
    dim. <blk>, when not None, is the block column's cell."""
    out = [paint("%-5s" % rnd, base) if base and rnd else "%-5s" % rnd]
    if blk is not None:
        out.append(paint(BLOCK_FMT % blk, base) if base and blk else BLOCK_FMT % blk)
    for i, ((_, f, _), c) in enumerate(zip(COLUMNS, cells)):
        text = f % c
        if i == WAITING_COL and isinstance(c, int) and c:
            text = paint(text, RED)
        elif i == FIXED_COL and isinstance(c, int) and c:
            text = paint(text, GREEN)
        elif c == WAIT:
            text = paint(text, DIM)
        elif base and text.strip():
            text = paint(text, base)
        out.append(text)
    return ("  " + " ".join(out)).rstrip()


def dollars(amount):
    return "$%.2f" % amount


def review_cost(gs):
    """The review's part of the cost of review runs <gs>: the sum of what could
    be priced; "—" when nothing could (the workflow's review, passes from
    before passes were priced); nothing when there is no run."""
    known = [g["cost"] for g in gs if g.get("cost") is not None]
    if not gs:
        return ""
    return dollars(sum(known)) if known else "—"


def timed(s):
    """Whether session <s> has a start time for each of its launches."""
    ats = s.get("cost_at") or []
    return bool(s["costs"]) and len(ats) == len(s["costs"]) and all(ats)


def fixes_per_round(s, gs, mine=None):
    """The fixing cost of each review run in <gs>, from session <s>: each
    launch goes on the last run that started before the launch began
    (`cost_at`, run_cost in steps.sh) — the run whose findings it fixed. On
    GitHub a launch waits inside for the run of its own push and ends after
    it, but it began on the findings of the run before. A launch which pushed
    nothing (reopened, resumed after a crash) adds to its run instead of
    shifting every later one; one begun before every run goes on the first. A
    state from before launches had a time is matched by position, one launch
    to each of the runs the session answered (<mine>, indexes into <gs>), the
    launches left over on the last of them; [] when nothing matches."""
    costs = s["costs"] if s else []
    if not gs or not costs:
        return []
    per = [None] * len(gs)
    if not timed(s):
        mine = list(mine if mine is not None else range(len(gs)))
        if not mine:
            return []
        for k, cost in enumerate(costs):
            j = mine[min(k, len(mine) - 1)]
            per[j] = round((per[j] or 0) + cost, 4)
        return per
    for cost, at in zip(costs, s["cost_at"]):
        j = 0
        for i, g in enumerate(gs):
            if g["at"] and g["at"] <= at:
                j = i
        per[j] = round((per[j] or 0) + cost, 4)
    return per


def verdict_colour(said):
    if FEEDING in said:
        return RED
    if said.startswith("Under "):
        return YELLOW
    return GREEN


def parse(ts):
    try:
        d = datetime.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def declined(replies):
    """Whether the thread's last decision reply is the author's decline
    (pr_context.decline_of, the one copy of the rule)."""
    return decline_of(replies) is not None


def threads(cwd, pr, repo):
    """Every review thread as a dict, oldest first, or None when unreadable."""
    if not repo or "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    left = yours(cwd)
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
            first = comments[0]
            # The review's "Still open:" reply cites nothing: it says what a
            # fix left out, and may name another thread while it does.
            replies = [c.get("body") or "" for c in comments[1:]
                       if not still_open_reply(c.get("body"))]
            if t.get("isResolved"):
                fate = "no fix" if declined(comments[1:]) else "fixed"
            else:
                fate = "no fix" if first.get("url") in left else "open"
            # Where the pull request's head has it now, on purpose: a finding
            # on the fixes, or a repeat, is told by its distance from earlier
            # ones in today's code. A finished round's counts of those two may
            # then shift between reports as later commits move lines; its
            # found, fixed and declined do not. The person chose today's
            # accuracy over still past numbers (2026-11-22).
            line = thread_line(t)
            own = DISCUSSION.search(first.get("url") or "")
            own = own.group(1) if own else None
            out.append({
                "id": own,
                "cites": {m for b in replies for m in CITED.findall(b)} - {own},
                "path": t.get("path") or "?",
                "line": line if isinstance(line, int) else None,
                "created": parse(first.get("createdAt")),
                "round": None,
                "fate": fate,
                "left_open": not t.get("isResolved") and first.get("url") in left,
            })
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    epoch = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    out.sort(key=lambda t: t["created"] or epoch)
    return out


# The feature's state, relative to its worktree.
STATE = ".sclaude/local/feature/state.json"


def pr_created(cwd, pr):
    """When the pull request was opened, or None when unreadable. A feature
    reopened after its merge (a retrospective's fixes, a rollback) goes on
    under a new pull request, in the same state and journal: what the review
    did before this one opened was the earlier one's."""
    data = gh_json(["pr", "view", str(pr), "--json", "createdAt"], cwd=cwd)
    at = parse(data.get("createdAt")) if isinstance(data, dict) else None
    # Less a margin: the journal and the sessions are stamped by this
    # machine's clock, which may lag GitHub's, and a pass begun seconds after
    # the opening would be left out.
    return at - CLOCK_SKEW if at else None


CLOCK_SKEW = datetime.timedelta(minutes=2)


def feature_state(cwd):
    """The feature's state, {} when it cannot be read or is not an object."""
    try:
        with open(os.path.join(cwd, STATE)) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def reopened(cwd):
    """Whether the feature went on after a merged pull request: when the
    opening of the new one is unknown, its rounds are mixed with the old."""
    return feature_state(cwd).get("reopened_pr") not in (None, "", "null")


def polish_head(cwd):
    """The head the clean pass read when the polish round was owed
    (`polish_head`, written by review_polish_owe), or None — only once the
    polish was taken (`polished`) or while it is under way (`due` with the
    feature at step 4): a polish owed and then dropped (closed anyway, a
    rewind, a block's close, a step closed past it) leaves the head behind
    with no /simplify run."""
    return polish_of(feature_state(cwd))


def polish_of(state):
    """polish_head from a feature's state, as polish_head reads it; the
    review's map reads it by this too."""
    # `due` is a polish under way only while step 4 is where the feature
    # stands: a step closed past it (the pull request merged or closed) can
    # leave `due` behind with no /simplify run.
    due = ((state.get("steps") or {}).get("review") or {}).get("polish") == "due" and state.get("step") == "review"
    return (state.get("polish_head") or None) if state.get("polished") or due else None


# A commit the person asked for during the review — a `feat` commit
# (Conventional Commits) or one carrying a `Requirement:` trailer — is the
# development going on, no fix (review.md: a fix needs no Requirement
# footer); the review's map tells its lines apart by the same test.
ASKED_SUBJECT = re.compile(r"feat(\(|!|:)")


def asked_commit(subject, requirement):
    return bool(ASKED_SUBJECT.match(subject or "") or (requirement or "").strip())


def own_places(cwd, base, head):
    """How many places of the code the feature's own commits from base to
    head changed, the person's asks left out (asked_commit): first-parent and
    no merges, each hunk of each commit one place, a deletion as much as a
    write. 0 for the same head; None when git cannot tell (a rewritten branch
    too, as fixed_lines reads it)."""
    if not base or not head:
        return None
    if base == head:
        return 0
    # Records open with a NUL, which no text diff holds (git shows such a
    # file as binary).
    log = own_log(cwd, base, head, "%x00%s%x02%(trailers:key=Requirement,valueonly,separator=;)")
    if log is None:
        return None
    places = 0
    for rec in log.split("\x00")[1:]:
        first, _, rest = rec.partition("\n")
        subject, _, req = first.partition("\x02")
        if not asked_commit(subject, req):
            # A hunk is a place; a binary file changed is one too.
            places += sum(1 for line in rest.splitlines() if line.startswith("@@") or line.startswith("Binary files "))
    return places


def polish_index(head, runs):
    """The last of the runs (the report's groups, the map's rounds) that read
    <head>, or None: the round whose fixing was step 4's polish round. The
    one rule the report (polish_round) and the map (review_map.py's
    polish_round) name it by."""
    found = [i for i, r in enumerate(runs) if head and r.get("head") == head]
    return found[-1] if found else None


def polish_round(cwd, groups):
    """The report's polish round, by the head sclaude recorded when it owed
    the polish (polish_head); None with no record."""
    return polish_index(polish_head(cwd), groups)


def polish_places(cwd, groups, i):
    """How many places of the code the polish round changed, as own_places
    counts them up to the next run's head (HEAD after the last)."""
    nxt = groups[i + 1].get("head") if i + 1 < len(groups) else None
    if not nxt:
        try:
            nxt = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                                 text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    return own_places(cwd, groups[i].get("head"), nxt)


def after(at, since):
    """Whether a run that started at <at> belongs to the pull request opened
    at <since>; every run does when <since> is unknown."""
    return since is None or (at is not None and at >= since)


def review_runs(cwd, branch, since=None):
    """The automatic review's runs on the branch since <since>, oldest first:
    [{start, seconds, running}], or None when unreadable. A run shorter than
    SKIP_SECONDS reviewed nothing (pr_context.py) and is left out."""
    if not branch:
        return None
    # The limit is high on purpose: every comment starts the @mention
    # workflow, and at 200 those runs pushed the review's own off the list.
    data = gh_json(["run", "list", "--branch", branch, "--limit", "1000", "--json",
                    "workflowName,createdAt,startedAt,updatedAt,status,conclusion,headSha,databaseId,attempt"], cwd=cwd)
    if not isinstance(data, list):
        return None
    out = []
    for r in data:
        name = r.get("workflowName") or ""
        if not is_claude_review(name, name):
            continue
        a, b = parse(r.get("createdAt")), parse(r.get("updatedAt"))
        if not a or not after(a, since):
            continue
        running = (r.get("status") or "completed") != "completed"
        # Timed from its last attempt's start: a run re-run after a usage
        # limit keeps the hour it was created at, and read from there its
        # wait for the limit counted as the review's time.
        began = parse(r.get("startedAt"))
        began = began if began and began >= a else a
        seconds = (b - began).total_seconds() if b and b > began else 0.0
        if running or seconds >= SKIP_SECONDS:
            out.append({"start": a, "began": began, "seconds": seconds, "running": running,
                        "head": r.get("headSha") or None, "id": r.get("databaseId"),
                        "attempt": r.get("attempt") or 1, "conclusion": r.get("conclusion") or "",
                        "source": "github"})
    out.sort(key=lambda r: r["start"])
    return out


# A review run on this machine (`review: local`, local_review.py) posts its
# findings as threads, read above like the workflow's; its runs are not
# workflow runs, so they are read from its journal instead.
from local_review import JOURNAL, github_runs  # noqa: E402


def pass_cost(cwd, session, root=None):
    """What one pass on this machine cost, in dollars: the account Claude Code
    keeps in the pass's transcript, its subagents included; None when there
    is no session or no account to read. The pass runs in the worktree, so its
    transcript is under the worktree's directory in ~/.claude/projects."""
    if not session:
        return None
    path = os.path.join(root or claude_usage.ROOT,
                        claude_usage.project_name(os.path.abspath(cwd)), session + ".jsonl")
    summary = claude_usage.read(path) if os.path.exists(path) else None
    return summary.get("cost") if summary else None


def local_runs(cwd, since=None, root=None, pr=None):
    """The review's runs since <since> from the journal, wherever they ran
    (the workflow's, `source: github`, carry no cost here), oldest first,
    shaped as review_runs gives them (journal_runs); None when the feature has
    no journal. Each carries the cost of its passes (pass_cost), None when none of them
    has one to read."""
    path = os.path.join(cwd, JOURNAL)
    if not os.path.exists(path):
        return None
    out = journal_runs(path, since, pr)
    for r in out:
        # A pass that ran and was not recorded (spent) is priced too: on the
        # run of its range, or as a run of its own, with nothing found.
        costs = [c for c in (pass_cost(cwd, s, root) for s in r.pop("sessions")) if c is not None]
        r["cost"] = sum(costs) if costs else None
        # Findings a run on GitHub could only post as a comment: found all
        # the same, with no thread to count them by.
        # A rerun's attempt counts in place of the one before it.
        last = {}
        for row in r["rows"]:
            key = row.get("run") if row.get("source") == "github" else id(row)
            if key not in last or (row.get("attempt") or 1) >= (last[key].get("attempt") or 1):
                last[key] = row
        r["unthreaded"] = sum(int(row.get("unthreaded") or 0) for row in last.values())
        del r["rows"]
    return out


def journal_runs(path, since=None, pr=None):
    """The journal's runs since <since> (and of pull request <pr>), oldest
    first, unpriced, each with the journal rows of its passes (`rows`).
    Read by the journal's own reader (local_review.rows), so both agree on
    what a pass is. The one grouping of the journal: the report's rows are
    these, and so are the review map's rounds (rounds_of in review_map.py),
    so a round there and a row here carry one number."""
    rows = [r for r in journal_rows(path, with_spent=True, pr=pr)
            if parse(r.get("at")) is not None and after(parse(r.get("at")), since)]
    # The passes over one range — a capped pass and the ones that follow it
    # for the rest — are one review, as the workflow's run is one however
    # many findings it brings: one run, from the first pass's start. Unless
    # the review block changed: every block's first read starts from the
    # same base, and a block read on the head the last one left is a run of
    # its own (a pass with no block changes none).
    out, last = [], None
    for row in rows:
        key = (row.get("base"), row.get("head"), row.get("run"))
        block = row.get("block")
        sessions = [row["session"]] if row.get("session") else []
        if out and key == last and (out[-1]["block"] == block or None in (out[-1]["block"], block)):
            out[-1]["seconds"] += float(row.get("seconds") or 0)
            out[-1]["stopped"] = out[-1]["stopped"] and bool(row.get("spent"))
            out[-1]["refused"] += [row["refused"]] if row.get("refused") else []
            out[-1]["sessions"] += sessions
            out[-1]["rows"].append(row)
            # From its earliest pass, whichever the journal wrote first.
            out[-1]["start"] = min(out[-1]["start"], parse(row["at"]))
            out[-1]["block"] = out[-1]["block"] or block
            continue
        out.append({"start": parse(row["at"]), "seconds": float(row.get("seconds") or 0),
                    "running": False, "sessions": sessions, "rows": [row], "head": row.get("head"),
                    "source": row.get("source") or "local",
                    # The review block the run read (SCLAUDE_REVIEW_BLOCK),
                    # None when the pull request is read whole.
                    "block": block,
                    # No pass of it left a recorded answer — stopped, or its
                    # answer not recorded: no round that found nothing.
                    "stopped": bool(row.get("spent")),
                    # Why a pass's answer was not taken (local_review.py's
                    # REFUSED, journaled by spent), one each.
                    "refused": [row["refused"]] if row.get("refused") else []})
        last = key
    # The pass over the seams has no block id: the journal names it by its
    # place, the blocks' count plus one, which no block of the cut is called.
    seams = seams_place(path)
    for r in out:
        if seams and r["block"] == seams:
            r["block"] = SEAMS
    # Grouped in the journal's order, where one review's passes follow one
    # another; then in order of time: a workflow's run is written when the
    # report learns of it (github_runs), after local passes that began later.
    return sorted(out, key=lambda r: r["start"])


# What a round over the seams between review blocks is called, in the
# report's block column ("seams.2") and on the review's map (roundName in
# process_review.js, "Seams · round 2").
SEAMS = "seams"


def seams_place(journal):
    """The block the journal beside <journal> names the seams by: the state's
    `blocks.total` (blocks_id in review_blocks.sh falls back to the place,
    and the seams' place is the last). A block's id is its first place or a
    split's letter-and-digit name, never that number. None when the pull
    request is not read in blocks."""
    try:
        with open(os.path.join(os.path.dirname(journal), "state.json")) as fh:
            total = (json.load(fh).get("blocks") or {}).get("total")
    except (OSError, ValueError, AttributeError):
        return None
    return str(total) if isinstance(total, int) and total >= 2 else None


def rounds(found, runs):
    """[{at, seconds, running, cost, threads}] — one per review run, empty
    ones included; sets each thread's "round" to its index. Without runs,
    threads are split where ROUND_GAP passes between two of them."""
    if runs:
        out = [{"at": r["start"], "seconds": r.get("seconds"), "running": r["running"],
                "cost": r.get("cost"), "head": r.get("head"), "threads": [],
                "stopped": bool(r.get("stopped")), "block": r.get("block"),
                "unthreaded": r.get("unthreaded") or 0}
               for r in runs]
        for t in found:
            i = 0
            for j, r in enumerate(runs):
                if t["created"] and r["start"] <= t["created"]:
                    i = j
            t["round"] = i
            out[i]["threads"].append(t)
        return out
    out, last = [], None
    for t in found:
        if not out or not (t["created"] and last and t["created"] - last <= ROUND_GAP):
            out.append({"at": t["created"], "seconds": None, "running": False, "cost": None,
                        "threads": []})
        t["round"] = len(out) - 1
        out[-1]["threads"].append(t)
        last = t["created"] or last
    return out


def near(a, b):
    return (a["path"] == b["path"] and a["line"] is not None and b["line"] is not None
            and abs(a["line"] - b["line"]) <= NEAR_LINES)


HUNK = re.compile(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@")


def own_log(cwd, base, head, fmt):
    """`git log -p -U0` of the feature's own commits from base to head, each
    opened by <fmt>: first-parent and no merges, so main merged in on the way
    is no change of the feature's; text that is not UTF-8 replaced. None when
    git cannot tell — a branch rebased or force-pushed between the two, where
    base..head would be every commit of the feature again."""
    try:
        if subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=cwd,
                          capture_output=True, timeout=30).returncode != 0:
            return None
        out = subprocess.run(["git", "log", "--first-parent", "--no-merges", "--format=" + fmt, "-p",
                              "-U0", "%s..%s" % (base, head)],
                             cwd=cwd, capture_output=True, text=True, errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def fixed_lines(cwd, base, head):
    """{path: [(first, last)]} — the lines the feature's own commits between
    two reviewed heads wrote: first-parent and no merges, so main merged in
    on the way is not taken for a fix. Each range is where its commit put it,
    which later commits of the same stretch may have moved a little; NEAR_LINES
    absorbs that. {} when git cannot tell."""
    if not base or not head or base == head:
        return {}
    log = own_log(cwd, base, head, "")
    if log is None:
        return {}
    lines, path = {}, None
    for text in log.splitlines():
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else None
        elif path and text.startswith("@@"):
            m = HUNK.match(text)
            if m:
                first, count = int(m.group(1)), int(m.group(2) or 1)
                if count:
                    lines.setdefault(path, []).append((first, first + count - 1))
    return lines


def mark_near_fixes(found, groups=None, cwd=None):
    """Marks each thread posted on the fixes: near a line an earlier round's
    fixed thread sat on, in the same file, or on lines the feature's commits
    since the run before wrote (fixed_lines). The first alone missed every
    finding on code a fix added somewhere else — a new function, the guide,
    a migration — and read a round of findings on the fixes as none."""
    wrote = {}
    for i, g in enumerate(groups or []):
        if i and cwd and g.get("head") and groups[i - 1].get("head"):
            wrote[i] = fixed_lines(cwd, groups[i - 1]["head"], g["head"])
    for i, t in enumerate(found):
        spans = wrote.get(t["round"], {}).get(t["path"], []) if t["line"] is not None else []
        t["near_fix"] = any(e["fate"] == "fixed" and e["round"] != t["round"] and near(e, t)
                            for e in found[:i]) \
            or any(a - NEAR_LINES <= t["line"] <= b + NEAR_LINES for a, b in spans)


def mark_repeats(found):
    """Marks each thread that repeats an earlier declined one: cited by its
    reply, or near it in the same file in a later round."""
    for i, t in enumerate(found):
        earlier = [e for e in found[:i] if e["fate"] == "no fix" and e["round"] != t["round"]]
        t["cites_declined"] = any(e["id"] in t["cites"] for e in earlier if e["id"])
        t["repeat"] = t["cites_declined"] or any(near(e, t) for e in earlier)


def sessions(cwd, since=None):
    """The review sessions from the feature's state, oldest first: those that
    were still going when the pull request opened at <since> — the one that
    opened it included."""
    state = feature_state(cwd)
    runs = ((state.get("steps") or {}).get("review") or {}).get("runs") or []
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    runs = [r for r in runs if isinstance(r, dict)]
    # Placed by its end; one without an end is going only when it is the
    # last, and an earlier one, which never ended properly, by its start.
    runs = [r for i, r in enumerate(runs)
            if (r.get("finished") is None and i == len(runs) - 1)
            or after(parse(r.get("finished") or r.get("started")), since)]
    for i, r in enumerate(runs):
        a = parse(r.get("started"))
        # Only the last run can still be going: an earlier one without an end
        # is one that never ended properly, and counted until now it grew by
        # every hour the step ran after it. Going means a launch is on now:
        # one not ended, or taken up again after its end (session_runs keeps
        # the end and sets `resumed`, as process_position reads it). A session
        # between its launches has given every launch's cost so far.
        ended, resumed = parse(r.get("finished")), parse(r.get("resumed"))
        going = i == len(runs) - 1 and not r.get("done") and (
            (ended is None and not r.get("outcome")) or bool(resumed and ended and resumed > ended))
        b = now if going else ended
        costs = [c for c in (r.get("costs") or []) if isinstance(c, (int, float))]
        ats = [parse(t) for t in (r.get("cost_at") or [])]
        # A launch that gave its cost has ended, though its end is written
        # after the report the session's close prints (session_ended in
        # run.sh): run_cost marks it with the launch's start (`costed`).
        costed = parse(r.get("costed"))
        if going and costed and costed >= (resumed or a or costed):
            going = False
        out.append({"start": a, "end": b, "going": going, "resumed": resumed,
                    "rounds": r.get("rounds"),
                    "costs": costs, "cost_at": ats,
                    "seconds": (b - a).total_seconds() if a and b and b > a else None})
    return out


def launches(s):
    """When session <s>'s launches began: those that gave their cost
    (`cost_at`, when there is one for each), its start, and the launch taken
    up again (`resumed`), whose cost comes when it ends."""
    return [t for t in (s["cost_at"] if timed(s) else []) + [s["start"], s.get("resumed")] if t]


def answering(i, groups, s):
    """Session <s>'s launches that answer run <i>: those in its window."""
    return [t for t in launches(s) if window(i, groups, t)]


def window(i, groups, t):
    """Whether a launch begun at <t> answers run <i>: after the run began and
    before the next one did — the first run's window open to the past, for a
    launch begun before any run."""
    lo = groups[i]["at"] if i else None
    hi = groups[i + 1]["at"] if i + 1 < len(groups) else None
    return (lo is None or t >= lo) and (hi is None or t < hi)


def fixers(groups, people):
    """For each review run in <groups>, the indexes into <people> of the
    sessions with a launch in its window (window), the first one first: the
    sessions that answered its findings; one session can answer several runs.
    [] for a run nobody has begun to answer — never the session that was
    going when it ran: on GitHub that is the launch waiting for the run of its
    own push, which fixed the run before."""
    out = []
    for i in range(len(groups)):
        events = sorted((t, k) for k, s in enumerate(people) for t in answering(i, groups, s))
        mine = []
        for _, k in events:
            if k not in mine:
                mine.append(k)
        out.append(mine)
    return out


def polish_apart(who, polish, people=None, owed=None, taken=False):
    """/simplify's place among the fixers of the polish round <polish>:
    (who, polish, k). Its session is the first of the round's fixers begun at
    or after <owed>, when the polish was owed (review_polish_owe opens a fresh
    one); with no such time recorded, the last of them once the polish is
    <taken>. Not begun yet, the round is an ordinary one: polish comes back
    None, and nothing of it is /simplify's — no label, no places. Alone on the
    round, its fix is /simplify's whole: k is None. With sessions besides it,
    those keep the round's row and k is /simplify's, taken out of <who> for a
    row of its own."""
    if polish is None or not who[polish]:
        return who, None, None
    mine = who[polish]
    if owed:
        k = next((k for k in mine if people and people[k]["start"] and people[k]["start"] >= owed), None)
        if k is None:
            return who, None, None
    elif taken:
        k = mine[-1]
    else:
        return who, None, None
    if mine == [k]:
        return who, polish, None
    who = [list(m) for m in who]
    who[polish] = [x for x in mine if x != k]
    return who, polish, k


def fix_window(i, groups, people, mine):
    """How long the fix of run <i> took, in seconds: from the first launch of
    its sessions <mine> in its window to the next run, or to the last of them
    ending (now, for one still going); None when it cannot be told."""
    starts = [t for k in mine for t in answering(i, groups, people[k])]
    ends = [people[k]["end"] for k in mine]
    until = max(ends) if ends and all(ends) else None
    if i + 1 < len(groups) and groups[i + 1]["at"]:
        until = min(until, groups[i + 1]["at"]) if until else groups[i + 1]["at"]
    if not starts or not until or until <= min(starts):
        return None
    return (until - min(starts)).total_seconds()


def hours(seconds):
    """A span in six characters at most: a session left going for days must
    not push the columns after it out of line."""
    m = int(round(seconds / 60))
    if m >= 24 * 60:
        return "%dd%02dh" % (m // (24 * 60), m // 60 % 24)
    return "%dh%02dm" % (m // 60, m % 60) if m >= 60 else "%dm" % m


def pct(part, whole):
    return "%d%%" % round(100.0 * part / whole) if whole else "-"


# The verdict's sentence for a last round whose findings sit mostly on earlier
# fixes; feeding_streak() applies the same test to each round, for stuck().
FEEDING = ("Half or more of the last round's findings sit on earlier fixes: "
           "the fixes are feeding the review.")


def verdict(acted, near_last, last_found, open_now):
    """What the figures say that the table does not show at a glance, in a
    sentence or none. No trend of the findings per round: the person reads it
    off the column, and a rule for it misread a few small numbers."""
    words = []
    if acted is not None and acted < ACTED_ON_FLOOR:
        words.append("Under %d%% of the latest findings were fixed: the review is mostly "
                     "asking for what nobody fixes." % (ACTED_ON_FLOOR * 100))
    # Not once nothing is open — no thread, no pass still running: the warning
    # is there to stop the rounds ([s], the topic's button), and then there
    # are none left to stop.
    if last_found and near_last * 2 >= last_found and open_now != 0:
        words.append(FEEDING)
    if open_now == 0:
        words.append("Nothing is open.")
    return " ".join(words)


def count(ts, fate):
    return sum(1 for t in ts if t["fate"] == fate)


# Where review stands, for a phone: the last finished round's numbers, written to
# the file this names when it is set. sclaude sends it to the feature's topic
# in Telegram after every round (review_report in review_gate.sh), each round a
# message of its own: the topic keeps the history, each message says only
# what is new.
BRIEF_ENV = "SCLAUDE_REPORT_BRIEF"
BRIEF_ROWS = ("found", "on fixes", "repeats", "declined", "fixed", "waiting")


def newest(columns):
    """The last round that has finished, as (label, {measure: n}), from
    [(label, {measure: n}, running)]: one still running has not said what it
    found, and its zeros would say nothing. None when no round has finished."""
    done = [c[:2] for c in columns if not c[2]]
    return done[-1] if done else None


def brief(pr, last, verdict_line, going=False, ran=False):
    """The status update: <last> is (label, {measure: n}) or None; <going>,
    that a review run has begun and not finished; <ran>, that runs before it
    left no recorded answer (stopped, or their answers not recorded)."""
    # No empty last line when the verdict has nothing to say (verdict).
    tail = verdict_line + "\n" if verdict_line else ""
    if not last:
        said = ("a review run is going." if going and ran
                else "the first review run is going." if going
                else "no review run has answered yet." if ran else "no review run yet.")
        return "Review — PR %s: %s\n%s" % (pr, said, tail)
    label, values = last
    # No "#": Telegram makes a hashtag of "#N".
    return "Review — PR %s, %s\n%s\n%s" % (
        pr, label, " · ".join("%s %d" % (row, values[row]) for row in BRIEF_ROWS), tail)


def main():
    if len(sys.argv) < 4:
        print("usage: review_report.py <worktree> <pr> <repo> [branch] [feature]",
              file=sys.stderr)
        return 2
    cwd, pr, repo = sys.argv[1:4]
    branch = (sys.argv[4:5] + [""])[0]

    # By the project's mode, as the summary for QA decides (pr_handoff.py),
    # not by whether a journal is left over from an earlier mode.
    local = review_mode(cwd) == "local"
    since = pr_created(cwd, pr)
    found = threads(cwd, pr, repo)
    threads_failed = found is None
    if found is None:
        found = []
    # The runs from the one journal (JOURNAL), wherever they ran: the
    # workflow's finished runs are added to it first, and one still going is
    # shown beside them. Reviewed only here, GitHub is not asked.
    running = []
    if not local or moved_for(cwd):
        on_github = review_runs(cwd, branch, since) or []
        github_runs(os.path.join(cwd, JOURNAL), on_github, pr)
        running = [r for r in on_github if r["running"]]
    # The pull request's rows, from its opening on (a row from before the
    # journal named its pull request carries none): the review map reads the
    # same (rounds_of), so a round there and a row here carry one number.
    bot = (local_runs(cwd, since, pr=pr) or []) + running
    sources = {r.get("source") or "local" for r in bot}
    moved = sources == {"github", "local"}
    groups = rounds(found, bot)
    # What the report shows, for step 4's gate (review_close_gate): a report
    # showing the open findings and the rounds the terminal was last shown,
    # on the same head, is not printed or sent again. The open findings by
    # their threads, not their count — one resolved and another posted is
    # the same count; the rounds, finished and running — a run that ended
    # with nothing new still changes the table, the topic's numbers and the
    # verdict.
    shown = None if threads_failed else "open:%s rounds:%d/%d" % (
        ",".join(sorted(str(t["id"]) for t in found if t["fate"] == "open")),
        sum(1 for g in groups if not g["running"]), len(groups))
    if shown is not None and os.environ.get(UNLESS_ENV) == shown:
        # Seen already, as it stands: said to the caller as shown, so a
        # table a session's end left owed is paid (REVIEW_REPORT_OWED).
        path = os.environ.get(OPEN_ENV, "")
        if path:
            try:
                with open(path, "w") as fh:
                    fh.write(shown)
            except OSError:
                pass
        return 0
    # Asked while a fix session works (review_pane_keys): its resolved
    # threads and its commits change the open findings and the head, not
    # the rounds — the table again then showed one row with its fix still
    # under way. Only a round finished since is worth printing there.
    unless = os.environ.get(UNLESS_ENV) or ""
    if shown is not None and unless and os.environ.get(ROUNDS_ONLY_ENV) \
            and unless.rpartition(" rounds:")[2] == shown.rpartition(" rounds:")[2]:
        return 0
    path = os.environ.get(OPEN_ENV, "")
    if path and shown is not None:
        try:
            with open(path, "w") as fh:
                fh.write(shown)
        except OSError:
            pass
    print("")
    print(rule("Review report · PR #%s%s" % (pr, " · on GitHub, then on this machine" if moved
                                             else " · reviewed on this machine" if local else "")))
    if threads_failed:
        # Every count in the table is a thread's: unread, the table would be
        # a column of zeros that reads as a clean review, and the rounds
        # beside them may be another pull request's. Nothing is shown.
        print("  The review threads could not be read (gh, network or permissions): no report this time,")
        print("  every count in it being a thread's.")
        return 0
    mark_near_fixes(found, groups, cwd)
    mark_repeats(found)
    people = sessions(cwd, since)

    total = len(found)
    unthreaded = sum(g.get("unthreaded", 0) for g in groups)
    fixed, nofix, opened = count(found, "fixed"), count(found, "no fix"), count(found, "open")
    # A review pass still going: open as a thread is, for the verdict and the
    # row that says where the review stands.
    running = any(g["running"] for g in groups)
    near_all = sum(1 for t in found if t["near_fix"])
    repeats = [t for t in found if t["repeat"]]
    # A round still running has not said all it will, and one with no
    # recorded answer said nothing: both left out of the rounds counted for
    # stuck() — a stopped pass read as "the last round found nothing".
    done = [g for g in groups if not g["running"] and not g.get("stopped")]
    columns = []
    # The runs whose findings are still being decided: a fix going on them,
    # or findings nobody has begun. Read for the share acted on below.
    busy = set()
    # What /simplify changed in the polish round: counted as found and fixed,
    # alike with the review's findings, in its row and in the totals.
    polished = 0

    if groups:
        print("")
        blocks = block_rounds(groups)
        for line in heading(blocks is not None):
            print(line)
        who = fixers(groups, people)
        # The polish round's fixing is /simplify's: named so in the session
        # column, and each place it changed counted as a finding found and
        # fixed, in its row and in the totals.
        polish = polish_round(cwd, groups)
        fstate = feature_state(cwd)
        # /simplify's session is the first begun on the polish round after the
        # polish was owed (review_polish_owe). When the round had findings of its own, fixed
        # by sessions before it, those keep the round's row, and /simplify's
        # gets a row of its own under it: put together, the round's fix read
        # as /simplify's, its findings counted with the places changed.
        who, polish, polish_k = polish_apart(who, polish, people, parse(fstate.get("polish_owed_at")),
                                             bool(fstate.get("polished")))
        polish_cost = None
        polish_pending = False
        # The fixing cost of each run, summed over the sessions that answered
        # it (fixes_per_round); a session still going has not given the cost
        # of the launch running now, which goes on the run its start falls
        # after, as fixes_per_round will put it.
        fix_cost = [None] * len(groups)
        pending = set()
        for k, s in enumerate(people):
            mine = [i for i, m in enumerate(who) if k in m]
            if k == polish_k:
                mine = sorted(mine + [polish])
            for i, c in enumerate(fixes_per_round(s, groups, mine)):
                if c is None:
                    continue
                if k == polish_k and i == polish:
                    polish_cost = c
                else:
                    fix_cost[i] = round((fix_cost[i] or 0) + c, 4)
            # What the launch going now spends waits for its end: the run it
            # answers is priced then.
            now_on = s.get("resumed") or s["start"]
            if s["going"] and now_on:
                on = {i for i in range(len(groups)) if window(i, groups, now_on)}
                if k == polish_k and polish in on:
                    polish_pending = True
                    on.discard(polish)
                pending.update(on)
        busy = pending | {i for i, m in enumerate(who) if not m and groups[i]["threads"]}
        # The polish round in its two shapes: /simplify's the whole round's
        # fix, or a row of its own under the round (apart).
        whole = polish if polish_k is None else None
        apart = polish if polish_k is not None else None
        # Counted once /simplify's session has ended: while it goes on, the
        # places it has changed so far are a figure that moves under the reader.
        polish_busy = polish_pending if apart is not None else polish in pending
        if polish is not None and not polish_busy:
            polished = polish_places(cwd, groups, polish) or 0
        # Found and fixed like the review's own, in the totals and the shares.
        total += polished
        fixed += polished
        # A session that answered several runs labels each N.1, N.2…: the
        # session's sum, as a row of its own, read as one more round.
        answered = {}
        for m in who:
            if m:
                answered[m[0]] = answered.get(m[0], 0) + 1
        seen = {}
        table, totals = [], {"ftook": [], "fcost": [], "xtook": [], "xcost": []}
        for i, g in enumerate(groups):
            ts = g["threads"]
            # Found is every finding, a thread or not: one posted as a comment
            # (unthreaded) was found as much as one on a line.
            # /simplify's places, on the polish round: in the brief always, in
            # the round's own row only when /simplify has no row of its own.
            add = polished if i == polish else 0
            extra = add if i == whole else 0
            counts = (len(ts) + g.get("unthreaded", 0) + extra, sum(1 for t in ts if t["near_fix"]),
                      sum(1 for t in ts if t["repeat"]))
            # Declined is the fix's decision, as it reads the findings.
            result = (count(ts, "no fix"), count(ts, "fixed") + extra, count(ts, "open"))
            # A stopped round is no finished one for the phone's brief either:
            # its zeros would say "found nothing" there too (newest).
            # The phone's brief takes the round whole, /simplify's places with
            # it, as the totals do: its row of its own is the terminal's.
            told = (len(ts) + g.get("unthreaded", 0) + add,) + counts[1:] + (result[0], count(ts, "fixed") + add, result[2])
            columns.append(("round %d" % (i + 1), dict(zip(BRIEF_ROWS, told)),
                            g["running"] or g.get("stopped")))
            if g["running"]:
                ftook = fcost = WAIT
            else:
                ftook = hours(g["seconds"]) if g["seconds"] else ""
                fcost = review_cost([g])
            mine = who[i]
            if mine:
                k = mine[0]
                seen[k] = seen.get(k, 0) + 1
                session = str(k + 1) if answered[k] <= 1 else "%d.%d" % (k + 1, seen[k])
                took = fix_window(i, groups, people, mine)
                xtook = hours(took) if took else ""
                xcost = WAIT if i in pending else dollars(fix_cost[i]) if fix_cost[i] is not None else ""
                columns[-1] = ("%s, session %s" % (columns[-1][0], session),) + columns[-1][1:]
            elif g["running"] or ts:
                # Findings nobody has begun to fix, or a run that has not
                # said yet what it found.
                session = xtook = xcost = WAIT
            else:
                session = xtook = xcost = ""
            for key, value in (("ftook", (ftook, g["seconds"])), ("fcost", (fcost, g.get("cost"))),
                               ("xtook", (xtook, took if mine else None)),
                               ("xcost", (xcost, fix_cost[i] if mine else None))):
                totals[key].append(value)
            # What became of the findings is not told while their fix has not
            # ended — not begun, or its launch still running: zeros there
            # read as a fix that fixed nothing. The total says where every
            # thread stands now.
            if session == WAIT or i in pending:
                result = (WAIT,) * 3
            elif i == whole:
                session = "simplify"
            # A run still going has not said what it found: what it posted so
            # far, or nothing yet, read as its count — zeros as "found
            # nothing". The total counts every thread there is.
            shown = (WAIT,) * 3 if g["running"] else counts
            table.append((str(i + 1), i, (g["at"].astimezone().strftime("%m-%d %H:%M") if g["at"] else "",
                          ftook, fcost) + shown + (session, xtook, xcost) + result))
            if i == apart:
                # /simplify's own row: no review ran for it, the places it
                # changed found and fixed alike, its own time and cost.
                took = fix_window(i, groups, people, [polish_k])
                ptook = hours(took) if took else ""
                pcost = WAIT if polish_pending else dollars(polish_cost) if polish_cost is not None else ""
                totals["xtook"].append((ptook, took))
                totals["xcost"].append((pcost, polish_cost))
                table.append(("", i, ("", "", "") + (WAIT if polish_pending else polished, 0, 0)
                              + ("simplify", ptook, pcost)
                              + ((WAIT,) * 3 if polish_pending else (0, polished, 0))))
        # The last round is yellow while anything is open: it is where the
        # review stands, and review_close_gate says no more of it.
        # The last round's row, not /simplify's under it; a pass still running
        # is something open too, as the verdict reads it.
        last = max(n for n, (rnd, _, _) in enumerate(table) if rnd) if opened or running else None
        for n, (rnd, i, cells) in enumerate(table):
            # The block column marks a round, not /simplify's row under it.
            blk = (blocks[i] if rnd else "") if blocks else None
            print(row(cells, base=YELLOW + ";" + BOLD, rnd=rnd, blk=blk) if n == last
                  else row(cells, rnd=rnd, blk=blk))
        stopped = [str(i + 1) for i, g in enumerate(groups) if g.get("stopped") and not g["threads"]]
        if stopped:
            print("  Round%s %s left no recorded answer (stopped, or its answer not recorded): "
                  "not a round that found nothing."
                  % ("s" if len(stopped) > 1 else "", ", ".join(stopped)))
        # Every answer refused, by why: a reason that keeps coming back is
        # how the person learns the answer's format is failing.
        why = {}
        for r in bot:
            for w in r.get("refused") or []:
                why[w] = why.get(w, 0) + 1
        if why:
            print(paint("  Answers refused: %d — %s" % (sum(why.values()), "; ".join(
                "%s (%d)" % (w, n) if n > 1 else w for w, n in sorted(why.items(), key=lambda x: -x[1]))), YELLOW))

        def column(key, show):
            """A column's sum of what is known now: the total is where the
            review stands, and a row still waiting adds when it comes."""
            cells = totals[key]
            known = [v for c, v in cells if c not in ("", "—", WAIT) and v]
            if key == "fcost":
                return review_cost([g for g, (c, _) in zip(groups, cells) if c != WAIT])
            return show(sum(known)) if known else ""
        print(row(("", column("ftook", hours), column("fcost", dollars), total + unthreaded,
                   near_all, len(repeats), "", column("xtook", hours), column("xcost", dollars),
                   nofix, fixed, opened), rnd="total", blk="" if blocks else None))
        print("")
    else:
        print("  No review threads on the pull request.")

    # The figures under the table, a line each, and only the ones that say
    # something: a line of zeros was read every round and meant nothing.
    # A run whose fix has ended, and that a later run has finished reading
    # after, is settled though threads of it stay open: what that run did not
    # close was left to somebody else. Leaving the whole run out read "the
    # last 9" off the first run while the second waited on two such threads.
    # Before a later run has finished, an open thread may be a fix the review
    # has yet to confirm, and the run waits as it did.
    read_after = max([i for i, g in enumerate(groups) if not g["running"]], default=-1)
    unsettled = {t["round"] for t in found if t["fate"] == "open"
                 and (t["round"] in busy or t["round"] >= read_after)}
    # The share acted on, over the newest settled findings: an open finding
    # has not been decided yet. Nor has its round: a decline is a reply posted
    # as the finding is read, a fix closes its thread only after the fixing
    # session has run, so a round still being worked settles its declines
    # first, and the report printed as its findings arrive read them as the
    # whole of it ("Fixed: 0", and the verdict below the floor).
    settled = [t for t in found
               if t["fate"] != "open" and t["round"] not in unsettled][-ACTED_ON_SAMPLE:]
    acted = (count(settled, "fixed") / float(len(settled))) if settled else None
    if total or unthreaded:
        left = sum(1 for t in found if t["left_open"])
        line = "  Fixed %d of %d (%s) · without a fix %d (%s)" % (
            fixed, total, pct(fixed, total), nofix, pct(nofix, total))
        if left:
            line += ", %d waiting for you to resolve on GitHub" % left
        if unthreaded:
            # Their fix is the session's, with no thread to tell how it ended.
            line += " · %d more posted as a comment, outside these shares" % unthreaded
        if acted is not None:
            line += " · acted on %d%% of the last %d" % (round(acted * 100), len(settled))
        if running:
            line += " · one review run still running"
        print(line)

    last = done[-1]["threads"] if done else []
    # A pass still running is something open: the warning is there to stop it.
    said = verdict(acted, sum(1 for t in last if t["near_fix"]), len(last), opened or int(running))
    if said:
        print("")
        print("  " + paint(said, verdict_colour(said) + ";" + BOLD))
    path = os.environ.get(BRIEF_ENV, "")
    # Zeros from threads nobody could read are not a status to send.
    if path and not threads_failed:
        try:
            with open(path, "w") as fh:
                fh.write(brief(pr, newest(columns), said, running,
                                 any(g.get("stopped") for g in groups)))
        except OSError:
            pass
    path = os.environ.get(STUCK_ENV, "")
    # Nor when the rounds may be two pull requests': a verdict on them would
    # be said about the new one.
    if path and not threads_failed and not (since is None and reopened(cwd)):
        try:
            with open(path, "w") as fh:
                # "-" for "not stuck", so that a file left empty — threads
                # nobody could read, a report that stopped early — tells
                # sclaude to keep the verdict it had, not to clear it.
                # Nor with nothing open and no pass running: no round left to stop.
                fh.write(said if (opened or running) and stuck(len(done), feeding_streak(done)) else "-")
        except OSError:
            pass
    return 0


# Whether the rounds are going on for ever, for sclaude to warn once and name
# the keys that end the search (review_stuck_say in review_round.sh), over
# enough rounds that one bad round is not it: the fixes feeding the review,
# FEEDING_ROUNDS rounds running. Rounds can shrink in count and still go on for
# ever on their own fixes. On
# one feature the report said so in four of the last six rounds, and four fresh
# sessions followed, each fixing the comments the last one wrote, with nobody
# told how to stop it. Running, because FEEDING itself reads the last round
# alone: one finding left, on an earlier fix, says it too.
STUCK_ENV = "SCLAUDE_REPORT_STUCK"
OPEN_ENV = "SCLAUDE_REPORT_OPEN"
UNLESS_ENV = "SCLAUDE_REPORT_UNLESS"
ROUNDS_ONLY_ENV = "SCLAUDE_REPORT_ROUNDS_ONLY"
STUCK_ROUNDS = 4
FEEDING_ROUNDS = 2


def stuck(rounds, feeding):
    """<rounds> finished, <feeding> of the last of them running fed by fixes."""
    return rounds >= STUCK_ROUNDS and feeding >= FEEDING_ROUNDS


def feeding_streak(rounds):
    """How many rounds running, back from the last, had half or more of their
    findings on earlier fixes — FEEDING's test, round by round."""
    streak = 0
    for group in reversed(rounds):
        found = group["threads"]
        if not found or sum(1 for t in found if t["near_fix"]) * 2 < len(found):
            break
        streak += 1
    return streak


if __name__ == "__main__":
    sys.exit(main())
