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
#   * findings per round — the discovery rate. A process that converges finds
#     fewer each round; one that holds level or climbs is not converging;
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
# every finding as a round. A run that found nothing is a round with nothing,
# which is what convergence looks like. A round opens with its findings and
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
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from pr_context import (SKIP_SECONDS, decline_of, gh_json, is_claude_review,  # noqa: E402
                        review_mode, thread_line, yours)
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
    ("session", "%7s", "fix"), ("took", "%6s", "fix"), ("cost", "%6s", "fix"),
    ("declined", "%8s", "fix"), ("fixed", "%5s", "result"), ("waiting", "%7s", "result"),
)
FIXED_COL, WAITING_COL = 10, 11


def heading():
    """The table's two heading lines: the groups over their columns, then the
    columns."""
    spans, widths = [], {}
    for name, fmt, group in COLUMNS:
        width = int(re.sub(r"\D", "", fmt))
        widths[group] = widths.get(group, -1) + width + 1
    for group in ("find", "fix", "result"):
        spans.append(("── %s " % group).ljust(widths[group], "─"))
    names = " ".join(fmt % name for name, fmt, _ in COLUMNS)
    return (paint("  %-5s %s" % ("", " ".join(spans)), DIM),
            paint("  %-5s %s" % ("round", names), DIM))


def row(cells, base="", rnd=""):
    """A table row, its waiting findings red and its fixes green once padded:
    the colour codes would otherwise count in the widths. <base> colours the
    rest of the row, cell by cell, so that red and green keep theirs; WAIT is
    dim."""
    out = [paint("%-5s" % rnd, base) if base and rnd else "%-5s" % rnd]
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
    if said.startswith("Not converging") or FEEDING in said:
        return RED
    if said.startswith("Converging slowly") or said.startswith("Too few"):
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
            replies = [c.get("body") or "" for c in comments[1:]]
            if t.get("isResolved"):
                fate = "no fix" if declined(comments[1:]) else "fixed"
            else:
                fate = "no fix" if first.get("url") in left else "open"
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


def reopened(cwd):
    """Whether the feature went on after a merged pull request: when the
    opening of the new one is unknown, its rounds are mixed with the old."""
    try:
        with open(os.path.join(cwd, STATE)) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return False
    return state.get("reopened_pr") not in (None, "", "null")


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
                    "workflowName,createdAt,updatedAt,status"], cwd=cwd)
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
        seconds = (b - a).total_seconds() if b and b > a else 0.0
        if running or seconds >= SKIP_SECONDS:
            out.append({"start": a, "seconds": seconds, "running": running})
    out.sort(key=lambda r: r["start"])
    return out


# A review run on this machine (`review: local`, local_review.py) posts its
# findings as threads, read above like the workflow's; its runs are not
# workflow runs, so they are read from its journal instead.
LOCAL_JOURNAL = ".sclaude/local/feature/local-review-rounds.jsonl"


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


def local_runs(cwd, since=None, root=None):
    """The local review's runs since <since>, oldest first, shaped as
    review_runs gives the workflow's; None when the feature has no journal.
    Read by the journal's own reader (local_review.rows), so both agree on
    what a run is. Each carries the cost of its passes (pass_cost), None when
    none of them has one to read."""
    path = os.path.join(cwd, LOCAL_JOURNAL)
    if not os.path.exists(path):
        return None
    # The passes over one range — a capped pass and the ones that follow it
    # for the rest — are one review, as the workflow's run is one however
    # many findings it brings: one run, from the first pass's start.
    out, last = [], None
    # A pass that ran and was not recorded (spent) is priced too: on the run
    # of its range, or as a run of its own, with nothing found.
    for row in journal_rows(path, with_spent=True):
        if not after(parse(row.get("at")), since):
            continue
        key = (row.get("base"), row.get("head"))
        cost = pass_cost(cwd, row.get("session"), root)
        if out and key == last:
            out[-1]["seconds"] += float(row.get("seconds") or 0)
            if cost is not None:
                out[-1]["cost"] = (out[-1]["cost"] or 0) + cost
            continue
        out.append({"start": parse(row["at"]), "seconds": float(row.get("seconds") or 0),
                    "running": False, "cost": cost})
        last = key
    return out


def rounds(found, runs):
    """[{at, seconds, running, cost, threads}] — one per review run, empty
    ones included; sets each thread's "round" to its index. Without runs,
    threads are split where ROUND_GAP passes between two of them."""
    if runs:
        out = [{"at": r["start"], "seconds": r.get("seconds"), "running": r["running"],
                "cost": r.get("cost"), "threads": []}
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


def mark_near_fixes(found):
    """Marks each thread posted near a line an earlier round's fixed thread
    sat on, in the same file."""
    for i, t in enumerate(found):
        t["near_fix"] = any(e["fate"] == "fixed" and e["round"] != t["round"] and near(e, t)
                            for e in found[:i])


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
    try:
        with open(os.path.join(cwd, STATE)) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return []
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
        # run.sh): run_cost dates the cost by the launch's start.
        if going and ats and ats[-1] and ats[-1] >= (resumed or a or ats[-1]):
            going = False
        out.append({"start": a, "end": b, "going": going, "resumed": resumed,
                    "took_up": [parse(t) for t in (r.get("took_up") or [])],
                    "rounds": r.get("rounds"),
                    "costs": costs, "cost_at": ats,
                    "seconds": (b - a).total_seconds() if a and b and b > a else None})
    return out


def launches(s, took=True):
    """When session <s>'s launches began: those that gave their cost
    (`cost_at`, when there is one for each), its start, the launch taken up
    again (`resumed`), whose cost comes when it ends, and — with <took> —
    each time a launch took up the next round itself (`took_up`, run_took_up
    in steps.sh)."""
    return [t for t in (s["cost_at"] if timed(s) else []) + [s["start"], s.get("resumed")]
            + ((s.get("took_up") or []) if took else []) if t]


def answering(i, groups, s):
    """Session <s>'s launches that answer run <i>: in its window, a launch
    taking the round up counted only where the run found something — a red
    deployment check on a run of nothing, fixed and waited on again, is no
    fix of that run."""
    return [t for t in launches(s, bool(groups[i].get("threads"))) if window(i, groups, t)]


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


# The verdict's moving average: the mean of the last TAIL_ROUNDS rounds,
# against the mean of the last WINDOW_ROUNDS (fewer while there are fewer).
TAIL_ROUNDS = 2
WINDOW_ROUNDS = 5


# The verdict's sentence for a last round whose findings sit mostly on earlier
# fixes; feeding_streak() applies the same test to each round, for stuck().
FEEDING = ("Half or more of the last round's findings sit on earlier fixes: "
           "the fixes are feeding the review.")


def verdict(per_round, acted, near_last, last_found, open_now):
    """The trend in a sentence, from the figures alone."""
    words = []
    if not per_round:
        return "No findings yet."
    if len(per_round) < 3:
        words.append("Too few rounds for a trend.")
    else:
        # A moving average: the last TAIL_ROUNDS rounds against the last
        # WINDOW_ROUNDS. Compared with the first rounds instead, the verdict
        # stayed "converging" while the findings rose again from 1 to 5: a
        # first pass over the whole pull request finds the most, and any
        # later stretch looks small beside it.
        tail = sum(per_round[-TAIL_ROUNDS:]) / float(TAIL_ROUNDS)
        window = per_round[-WINDOW_ROUNDS:]
        mean = sum(window) / float(len(window))
        if tail > mean:
            words.append("Not converging: findings per round are climbing.")
        elif tail <= mean * 0.5:
            words.append("Converging: the last %d rounds found half or less of the last %d's average."
                         % (TAIL_ROUNDS, len(window)))
        elif tail < mean:
            words.append("Converging slowly.")
        else:
            words.append("Not converging: findings per round hold level.")
    if acted is not None and acted < ACTED_ON_FLOOR:
        words.append("Under %d%% of the latest findings were fixed: the review is mostly "
                     "asking for what nobody fixes." % (ACTED_ON_FLOOR * 100))
    if last_found and near_last * 2 >= last_found:
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


def brief(pr, last, verdict_line, going=False):
    """The status update: <last> is (label, {measure: n}) or None; <going>,
    that a review run has begun and not finished."""
    if not last:
        return "Review — PR %s: %s\n%s\n" % (
            pr, "the first review run is going." if going else "no review run yet.", verdict_line)
    label, values = last
    # No "#": Telegram makes a hashtag of "#N".
    return "Review — PR %s, %s\n%s\n%s\n" % (
        pr, label, " · ".join("%s %d" % (row, values[row]) for row in BRIEF_ROWS),
        verdict_line)


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
    bot = (local_runs(cwd, since) or []) if local else None
    found = threads(cwd, pr, repo)
    threads_failed = found is None
    if found is None:
        found = []
    if not local:
        bot = review_runs(cwd, branch, since)
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
        return 0
    path = os.environ.get(OPEN_ENV, "")
    if path and shown is not None:
        try:
            with open(path, "w") as fh:
                fh.write(shown)
        except OSError:
            pass
    print("")
    print(rule("Review report · PR #%s%s" % (pr, " · reviewed on this machine" if local else "")))
    if threads_failed:
        print("  The review threads could not be read (gh, network or permissions).")
    mark_near_fixes(found)
    mark_repeats(found)
    people = sessions(cwd, since)

    total = len(found)
    fixed, nofix, opened = count(found, "fixed"), count(found, "no fix"), count(found, "open")
    near_all = sum(1 for t in found if t["near_fix"])
    repeats = [t for t in found if t["repeat"]]
    # A round still running has not said all it will: left out of the trend.
    done = [g for g in groups if not g["running"]]
    per_round = [len(g["threads"]) for g in done]
    columns = []

    if groups:
        print("")
        for line in heading():
            print(line)
        who = fixers(groups, people)
        # The fixing cost of each run, summed over the sessions that answered
        # it (fixes_per_round); a session still going has not given the cost
        # of the launch running now, which goes on the run its start falls
        # after, as fixes_per_round will put it.
        fix_cost = [None] * len(groups)
        pending, fixing = set(), set()
        for k, s in enumerate(people):
            mine = [i for i, m in enumerate(who) if k in m]
            for i, c in enumerate(fixes_per_round(s, groups, mine)):
                if c is not None:
                    fix_cost[i] = round((fix_cost[i] or 0) + c, 4)
            now_on = s.get("resumed") or s["start"]
            if s["going"] and now_on:
                pending.update(i for i in range(len(groups)) if window(i, groups, now_on))
                # The runs this launch took up since (took_up): fixed now too.
                fixing.update(i for i in range(len(groups)) for t in answering(i, groups, s)
                              if t >= now_on)
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
            counts = (len(ts), sum(1 for t in ts if t["near_fix"]), sum(1 for t in ts if t["repeat"]))
            # Declined is the fix's decision, as it reads the findings.
            result = (count(ts, "no fix"), count(ts, "fixed"), count(ts, "open"))
            columns.append(("round %d" % (i + 1), dict(zip(BRIEF_ROWS, counts + result)), g["running"]))
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
            if session == WAIT or i in fixing or i in pending:
                result = (WAIT,) * 3
            table.append((g["at"].astimezone().strftime("%m-%d %H:%M") if g["at"] else "",
                          ftook, fcost) + counts + (session, xtook, xcost) + result)
        # The last round is yellow while anything is open: it is where the
        # review stands, and review_close_gate says no more of it.
        last = len(table) - 1 if opened else None
        for i, cells in enumerate(table):
            print(row(cells, base=YELLOW + ";" + BOLD, rnd=str(i + 1)) if i == last
                  else row(cells, rnd=str(i + 1)))

        def column(key, show):
            """A column's sum of what is known now: the total is where the
            review stands, and a row still waiting adds when it comes."""
            cells = totals[key]
            known = [v for c, v in cells if c not in ("", "—", WAIT) and v]
            if key == "fcost":
                return review_cost([g for g, (c, _) in zip(groups, cells) if c != WAIT])
            return show(sum(known)) if known else ""
        print(row(("", column("ftook", hours), column("fcost", dollars), len(found), near_all,
                   len(repeats), "", column("xtook", hours), column("xcost", dollars),
                   nofix, fixed, opened), rnd="total"))
        print("")
    else:
        print("  No review threads on the pull request.")

    # The figures under the table, a line each, and only the ones that say
    # something: a line of zeros was read every round and meant nothing.
    unsettled = {t["round"] for t in found if t["fate"] == "open"}
    # The share acted on, over the newest settled findings: an open finding
    # has not been decided yet. Nor has its round: a decline is a reply posted
    # as the finding is read, a fix closes its thread only after the fixing
    # session has run, so a round still being worked settles its declines
    # first, and the report printed as its findings arrive read them as the
    # whole of it ("Fixed: 0", and the verdict below the floor).
    settled = [t for t in found
               if t["fate"] != "open" and t["round"] not in unsettled][-ACTED_ON_SAMPLE:]
    acted = (count(settled, "fixed") / float(len(settled))) if settled else None
    if found:
        left = sum(1 for t in found if t["left_open"])
        line = "  Fixed %d of %d (%s) · without a fix %d (%s)" % (
            fixed, total, pct(fixed, total), nofix, pct(nofix, total))
        if left:
            line += ", %d waiting for you to resolve on GitHub" % left
        if acted is not None:
            line += " · acted on %d%% of the last %d" % (round(acted * 100), len(settled))
        if len(done) < len(groups):
            line += " · one review run still running"
        print(line)

    last = done[-1]["threads"] if done else []
    said = verdict(per_round, acted, sum(1 for t in last if t["near_fix"]), len(last), opened)
    print("")
    print("  " + paint(said, verdict_colour(said) + ";" + BOLD))
    path = os.environ.get(BRIEF_ENV, "")
    # Zeros from threads nobody could read are not a status to send.
    if path and not threads_failed:
        try:
            with open(path, "w") as fh:
                fh.write(brief(pr, newest(columns), said, bool(columns)))
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
                fh.write(said if stuck(per_round, said, feeding_streak(done)) else "-")
        except OSError:
            pass
    return 0


# Whether the rounds have stopped converging, for sclaude to warn once and
# name the keys that end the search (review_stuck_say in review_round.sh): the verdict
# says so, over enough rounds that one bad round is not it. The report wrote
# "Not converging" eighteen rounds in a row on one feature, and each was
# followed by a fresh session, until the person stopped it by hand.
#
# Or that the fixes are feeding the review, FEEDING_ROUNDS rounds running:
# rounds can converge in count and still go on for ever on their own fixes. On
# one feature the report said so in four of the last six rounds, and four fresh
# sessions followed, each fixing the comments the last one wrote, with nobody
# told how to stop it. Running, because FEEDING itself reads the last round
# alone: one finding left, on an earlier fix, says it too.
STUCK_ENV = "SCLAUDE_REPORT_STUCK"
OPEN_ENV = "SCLAUDE_REPORT_OPEN"
UNLESS_ENV = "SCLAUDE_REPORT_UNLESS"
STUCK_ROUNDS = 4
FEEDING_ROUNDS = 2


def stuck(per_round, said, feeding=0):
    return len(per_round) >= STUCK_ROUNDS and (
        said.startswith("Not converging") or feeding >= FEEDING_ROUNDS)


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
