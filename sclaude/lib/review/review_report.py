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
# which is what convergence looks like. The rounds are summed per review
# session (state.json), the run going to the session last started before it:
# a session's push is what starts the run its findings come from.
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


def row(cells, open_col=9, fixed_col=7, base="", rnd=""):
    """A table row, its open findings red and its fixes green once padded:
    the colour codes would otherwise count in the widths. <base> colours the
    rest of the row, cell by cell, so that red and green keep theirs."""
    out = [paint("%-5s" % rnd, base) if base and rnd else "%-5s" % rnd]
    fmt = ("%-7s", "%-11s", "%6s", "%7s", "%6s", "%4s", "%5s", "%5s", "%6s", "%4s", "%8s", "%7s")
    for i, (f, c) in enumerate(zip(fmt, cells)):
        text = f % c
        if i == open_col and isinstance(c, int) and c:
            text = paint(text, RED)
        elif i == fixed_col and isinstance(c, int) and c:
            text = paint(text, GREEN)
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


def fixes_per_round(s, gs):
    """The fixing cost of each review run in <gs>, from session <s>: each
    launch goes on the first run that started after the launch began
    (`cost_at`, run_cost in steps.sh) — on this machine the pass follows the
    launch, on GitHub the launch waits inside for the run of its own push —
    so that a launch which pushed nothing (reopened, resumed after a crash)
    adds to its run instead of shifting every later one. A launch begun after
    the last run is the fix going on now: in the total, not on a round. A
    state from before launches had a time is matched by position, one launch
    a run; [] when nothing matches."""
    costs = s["costs"] if s else []
    ats = s.get("cost_at") or [] if s else []
    if not gs or not costs:
        return []
    if len(ats) != len(costs) or not all(ats):
        return costs[:len(gs)] if len(costs) >= len(gs) else []
    per = [None] * len(gs)
    for cost, at in zip(costs, ats):
        j = next((i for i, g in enumerate(gs) if g["at"] and at <= g["at"]), None)
        if j is not None:
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
    """[{at, running, threads}] — one per review run, empty ones included;
    sets each thread's "round" to its index. Without runs, threads are split
    where ROUND_GAP passes between two of them."""
    if runs:
        out = [{"at": r["start"], "running": r["running"], "cost": r.get("cost"), "threads": []}
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
            out.append({"at": t["created"], "running": False, "cost": None, "threads": []})
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
        # every hour the step ran after it.
        going = i == len(runs) - 1 and not r.get("done") and not r.get("outcome")
        b = parse(r.get("finished")) or (now if going else None)
        costs = [c for c in (r.get("costs") or []) if isinstance(c, (int, float))]
        ats = [parse(t) for t in (r.get("cost_at") or [])]
        out.append({"start": a, "rounds": r.get("rounds"), "costs": costs, "cost_at": ats,
                    "seconds": (b - a).total_seconds() if a and b and b > a else None})
    return out


def by_session(groups, runs):
    """[(label, session or None, [rounds])]: each round goes to the session
    last started before it; rounds before the first go to "before"."""
    rows = [("before", None, [])] + [(str(i), s, []) for i, s in enumerate(runs, start=1)]
    for g in groups:
        k = 0
        for i, s in enumerate(runs, start=1):
            if s["start"] and g["at"] and s["start"] <= g["at"]:
                k = i
        rows[k][2].append(g)
    return [r for r in rows if r[1] is not None or r[2]]


def hours(seconds):
    m = int(round(seconds / 60))
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


# Where review stands, for a phone: the newest session's numbers, written to
# the file this names when it is set. sclaude sends it to the feature's topic
# in Telegram after every round (review_report in review_gate.sh), each round a
# message of its own: the topic keeps the history, each message says only
# what is new.
BRIEF_ENV = "SCLAUDE_REPORT_BRIEF"
BRIEF_ROWS = ("runs", "found", "fixed", "no fix", "open", "on fixes", "repeats")


def newest(columns):
    """The last session that ran: one just opened has no run yet, and its
    zeros would say nothing."""
    ran = [c for c in columns if c[1]["runs"]]
    return ran[-1] if ran else None


def brief(pr, session, verdict_line):
    """The status update: session is (label, {measure: n}) or None."""
    if not session:
        return "Review — PR %s: no review run yet.\n%s\n" % (pr, verdict_line)
    label, values = session
    # No "#": Telegram makes a hashtag of "#N". The findings from before the
    # first session have the label "before" in the table.
    return "Review — PR %s, %s\n%s\n%s\n" % (
        pr, "before the sessions" if label == "before" else "session " + label, " · ".join("%s %d" % (row, values[row]) for row in BRIEF_ROWS),
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
        table = []
        print("")
        print(paint("  %-5s %-7s %-11s %6s %7s %6s %4s %5s %5s %6s %4s %8s %7s" % (
            "round", "session", "started", "time", "review", "fixes", "runs", "found", "fixed",
            "no fix", "open", "on fixes", "repeats"), DIM))
        for label, s, gs in by_session(groups, people):
            ts = [t for g in gs for t in g["threads"]]
            values = (len(gs), len(ts), count(ts, "fixed"), count(ts, "no fix"),
                      count(ts, "open"), sum(1 for t in ts if t["near_fix"]),
                      sum(1 for t in ts if t["repeat"]))
            columns.append((label, dict(zip(BRIEF_ROWS, values))))
            # A session that went several rounds has a row per round and none
            # of its own: the session's row was their sum, read as a round
            # of its own. A row's cost is in two parts: the review run it
            # counts (review_cost), and the fixing launches that run read
            # (fixes_per_round). Launches that cannot be matched to rounds
            # give the session's whole on its first round. The first round
            # runs from the session's start, each to the next review run,
            # the last to the session's end: the rows add up to the session.
            fixes = (s["costs"] if s else [])
            per = fixes_per_round(s, gs)
            if s is None or len(gs) <= 1:
                fix = per[0] if gs and per else (sum(fixes) if fixes else None)
                table.append((
                    label,
                    s["start"].astimezone().strftime("%m-%d %H:%M") if s and s["start"] else "",
                    hours(s["seconds"]) if s and s["seconds"] else "",
                    review_cost(gs), dollars(fix) if fix is not None else "") + values)
                continue
            end = (s["start"] + datetime.timedelta(seconds=s["seconds"])
                   if s["start"] and s["seconds"] else None)
            for j, g in enumerate(gs, start=1):
                rt = g["threads"]
                began = (s["start"] or g["at"]) if j == 1 else g["at"]
                until = gs[j]["at"] if j < len(gs) else end
                took = (until - began).total_seconds() if began and until and until > began else 0
                cost = per[j - 1] if per else (sum(fixes) if j == 1 and fixes else None)
                table.append((
                    "%s.%d" % (label, j),
                    began.astimezone().strftime("%m-%d %H:%M") if began else "",
                    hours(took) if took else "", review_cost([g]),
                    dollars(cost) if cost is not None else "",
                    1, len(rt), count(rt, "fixed"), count(rt, "no fix"), count(rt, "open"),
                    sum(1 for t in rt if t["near_fix"]), sum(1 for t in rt if t["repeat"])))
        # The last round that ran is yellow while anything is open: it is
        # where the review stands, and review_close_gate says no more of it.
        # A session just opened, with no run yet, is not that round.
        ran = [i for i, cells in enumerate(table) if cells[5]]
        last = ran[-1] if ran and opened else None
        # The review run's number, first: what the verdict and the topic
        # call a round, which a session's label (2.1, 2.2…) does not count.
        n = 0
        for i, cells in enumerate(table):
            runs = cells[5]
            rnd = "" if not runs else str(n + 1) if runs == 1 else "%d-%d" % (n + 1, n + runs)
            n += runs or 0
            # A session no review run has followed yet — the one fixing now —
            # has no findings to count: its zeros read as a round that found
            # nothing. Its time and cost stay, the total counts them.
            if not cells[5]:
                cells = cells[:5] + ("",) * (len(cells) - 5)
            print(row(cells, base=YELLOW + ";" + BOLD, rnd=rnd) if i == last else row(cells, rnd=rnd))
        seconds = sum(s["seconds"] or 0 for s in people)
        costs = [c for s in people for c in s["costs"]]
        values = (len(groups), total, fixed, nofix, opened, near_all, len(repeats))
        print(row(("total", "", hours(seconds) if seconds else "", review_cost(groups),
                   dollars(sum(costs)) if costs else "") + values))
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
                fh.write(brief(pr, newest(columns), said))
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
