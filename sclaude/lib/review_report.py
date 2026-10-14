#!/usr/bin/env python3
#
# Whether another round of the automatic review is worth it: a report built
# from the pull request's review threads and the feature's state, with no model
# in the loop. `sclaude review-report <feature>` prints it, and sclaude prints
# it at the close of every review round, where the person decides whether the
# feature goes on being fixed.
#
#   review_report.py <worktree> <pr> <repo> [branch] [feature] [review-context.log]
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
#     it), and the reversals the sessions declined (review-reversals). Both
#     growing means the fixes are feeding the review;
#   * what it costs — the review sessions' spend as the status line reports it
#     (run_cost), their time, and the automatic review's own runs;
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pr_context import (DECLINE_PREFIX, RESOLVER_PREFIX, SKIP_SECONDS, gh_json,  # noqa: E402
                        is_claude_review, yours)

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

# The per-run chain is cut to its two ends past this many runs.
CHAIN_MAX = 30


def parse(ts):
    try:
        d = datetime.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def declined(replies):
    """Whether the thread's last decision reply is the author's decline."""
    last = None
    for c in replies:
        body = (c.get("body") or "").lstrip()
        if body.startswith(RESOLVER_PREFIX):
            last = "fixed"
        elif (body.startswith(DECLINE_PREFIX)
              and ((c.get("author") or {}).get("__typename")) != "Bot"):
            last = "declined"
    return last == "declined"


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
            line = t.get("line") or t.get("originalLine")
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


def review_runs(cwd, branch):
    """The automatic review's runs on the branch, oldest first: [{start,
    seconds, running}], or None when unreadable. A run shorter than
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
        if not a:
            continue
        running = (r.get("status") or "completed") != "completed"
        seconds = (b - a).total_seconds() if b and b > a else 0.0
        if running or seconds >= SKIP_SECONDS:
            out.append({"start": a, "seconds": seconds, "running": running})
    out.sort(key=lambda r: r["start"])
    return out


def rounds(found, runs):
    """[{at, running, threads}] — one per review run, empty ones included;
    sets each thread's "round" to its index. Without runs, threads are split
    where ROUND_GAP passes between two of them."""
    if runs:
        out = [{"at": r["start"], "running": r["running"], "threads": []} for r in runs]
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
            out.append({"at": t["created"], "running": False, "threads": []})
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


def sessions(cwd):
    """The review sessions from the feature's state, oldest first."""
    try:
        with open(os.path.join(cwd, ".sclaude/local/feature/state.json")) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return []
    runs = ((state.get("steps") or {}).get("review") or {}).get("runs") or []
    now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        a = parse(r.get("started"))
        b = parse(r.get("finished")) or (now if not r.get("done") and not r.get("outcome") else None)
        costs = [c for c in (r.get("costs") or []) if isinstance(c, (int, float))]
        out.append({"start": a, "rounds": r.get("rounds"), "costs": costs,
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


def chain(per_round):
    words = [str(n) for n in per_round]
    if len(words) > CHAIN_MAX:
        words = words[:5] + ["…"] + words[-(CHAIN_MAX - 5):]
    return " ".join(words)


def verdict(per_round, acted, near_last, last_found, open_now):
    """The trend in a sentence, from the figures alone."""
    words = []
    if not per_round:
        return "No findings yet."
    if len(per_round) < 3:
        words.append("Too few rounds for a trend.")
    else:
        # Two rounds at each end, three once there are enough to spare.
        k = 3 if len(per_round) >= 8 else 2
        head = sum(per_round[:k]) / float(k)
        tail = sum(per_round[-k:]) / float(k)
        if per_round[-1] > per_round[-2] >= per_round[-3]:
            words.append("Not converging: findings per round are climbing.")
        elif tail <= head * 0.5:
            words.append("Converging: the last rounds found half or less of the first.")
        elif tail < head:
            words.append("Converging slowly.")
        else:
            words.append("Not converging: findings per round hold level.")
    if acted is not None and acted < ACTED_ON_FLOOR:
        words.append("Under %d%% of the latest findings were fixed: the review is mostly "
                     "asking for what nobody fixes." % (ACTED_ON_FLOOR * 100))
    if last_found and near_last * 2 >= last_found:
        words.append("Half or more of the last round's findings sit on earlier fixes: "
                     "the fixes are feeding the review.")
    if open_now == 0:
        words.append("Nothing is open.")
    return " ".join(words)


def count(ts, fate):
    return sum(1 for t in ts if t["fate"] == fate)


def main():
    if len(sys.argv) < 4:
        print("usage: review_report.py <worktree> <pr> <repo> [branch] [feature] [log]",
              file=sys.stderr)
        return 2
    cwd, pr, repo = sys.argv[1:4]
    branch, slug, log = (sys.argv[4:7] + ["", "", ""])[:3]

    found = threads(cwd, pr, repo)
    print("Review report — PR #%s" % pr)
    if found is None:
        print("  The review threads could not be read (gh, network or permissions).")
        found = []
    bot = review_runs(cwd, branch)
    groups = rounds(found, bot)
    mark_near_fixes(found)
    mark_repeats(found)
    people = sessions(cwd)

    total = len(found)
    fixed, nofix, opened = count(found, "fixed"), count(found, "no fix"), count(found, "open")
    near_all = sum(1 for t in found if t["near_fix"])
    repeats = [t for t in found if t["repeat"]]
    # A round still running has not said all it will: left out of the trend.
    done = [g for g in groups if not g["running"]]
    per_round = [len(g["threads"]) for g in done]

    if groups:
        print("")
        print("  %-7s %-11s %6s %6s %4s %5s %5s %6s %4s %8s %7s" % (
            "session", "started", "time", "cost", "runs", "found", "fixed", "no fix", "open",
            "on fixes", "repeats"))
        for label, s, gs in by_session(groups, people):
            ts = [t for g in gs for t in g["threads"]]
            print("  %-7s %-11s %6s %6s %4d %5d %5d %6d %4d %8d %7d" % (
                label,
                s["start"].astimezone().strftime("%m-%d %H:%M") if s and s["start"] else "",
                hours(s["seconds"]) if s and s["seconds"] else "",
                "$%.2f" % sum(s["costs"]) if s and s["costs"] else "",
                len(gs), len(ts), count(ts, "fixed"), count(ts, "no fix"), count(ts, "open"),
                sum(1 for t in ts if t["near_fix"]), sum(1 for t in ts if t["repeat"])))
        seconds = sum(s["seconds"] or 0 for s in people)
        costs = [c for s in people for c in s["costs"]]
        print("  %-7s %-11s %6s %6s %4d %5d %5d %6d %4d %8d %7d" % (
            "total", "", hours(seconds) if seconds else "",
            "$%.2f" % sum(costs) if costs else "", len(groups), total, fixed, nofix, opened,
            near_all, len(repeats)))
        print("")
        print("  Findings per review run, oldest first: %s%s" % (
            chain(per_round), " (one more still running)" if len(done) < len(groups) else ""))
    else:
        print("  No review threads on the pull request.")

    if found:
        left = sum(1 for t in found if t["left_open"])
        print("  Fixed: %d (%s). Closed without a fix: %d (%s)%s." % (
            fixed, pct(fixed, total), nofix, pct(nofix, total),
            ", %d of them waiting for you to resolve on GitHub" % left if left else ""))
    # The share acted on, over the newest settled findings: an open finding
    # has not been decided yet.
    settled = [t for t in found if t["fate"] != "open"][-ACTED_ON_SAMPLE:]
    acted = (count(settled, "fixed") / float(len(settled))) if settled else None
    if acted is not None:
        print("  Acted on, of the last %d settled findings: %d%%." % (len(settled), round(acted * 100)))
    if found:
        again = sum(1 for t in repeats if t["fate"] == "no fix")
        cited = sum(1 for t in repeats if t["cites_declined"])
        print("  Raised again after a decline: %d finding%s (%d declined again, %d citing the "
              "earlier thread)." % (len(repeats), "" if len(repeats) == 1 else "s", again, cited))

    # Back and forth.
    reversals = 0
    try:
        with open(os.path.join(cwd, ".sclaude/local/feature/review-reversals")) as fh:
            reversals = sum(1 for line in fh if line.strip())
    except OSError:
        pass
    reversals += logged_reversals(log, slug) if slug and log else 0
    if found or reversals:
        print("  Back and forth: %d finding%s on lines an earlier round fixed; %d declined "
              "as undoing a settled fix." % (near_all, "" if near_all == 1 else "s", reversals))
        spots = {}
        for t in found:
            spots.setdefault(t["path"], set()).add(t["round"])
        hot = sorted(((len(r), p) for p, r in spots.items() if len(r) >= 3), reverse=True)[:3]
        for n, p in hot:
            print("    %s: findings in %d of %d rounds" % (p, n, len(groups)))

    # What it cost.
    if people:
        costs = [c for s in people for c in s["costs"]]
        priced = [i for i, s in enumerate(people, start=1) if s["costs"]]
        if costs:
            # Per fixed finding, over the sessions that have a cost: the
            # others were not priced, and their fixes would flatter it.
            fixed_priced = sum(count([t for g in gs for t in g["threads"]], "fixed")
                               for label, s, gs in by_session(groups, people)
                               if s is not None and s["costs"])
            line = "  Cost: $%.2f over %d of %d sessions, last launch $%.2f" % (
                sum(costs), len(priced), len(people), costs[-1])
            if fixed_priced:
                line += ", $%.2f per finding fixed from their runs" % (sum(costs) / fixed_priced)
            print(line + ".")
        else:
            print("  Cost: not recorded for any session.")
    if bot:
        print("  Automatic review: %d run%s, %s of runner time." % (
            len(bot), "" if len(bot) == 1 else "s", hours(sum(r["seconds"] for r in bot))))

    last = done[-1]["threads"] if done else []
    print("")
    print("  " + verdict(per_round, acted, sum(1 for t in last if t["near_fix"]), len(last), opened))
    return 0


def logged_reversals(log, slug):
    """Reversals already counted into the main tree's review-context.log for
    this feature: review_context_log empties review-reversals as it counts."""
    total = 0
    try:
        with open(log) as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 11 and parts[1] == slug and parts[10].isdigit():
                    total += int(parts[10])
    except (OSError, TypeError):
        pass
    return total


if __name__ == "__main__":
    sys.exit(main())
