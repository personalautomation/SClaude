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
#     (run_cost), their time, and the automatic review's own runs.
#
# A thread is classified by what happened to it, never by reading it:
#
#   fixed      resolved, with the resolver's "Resolved automatically: …" reply;
#   no fix     resolved any other way (the person's yes, or by hand), or open
#              and written in review-yours (left for the person to resolve);
#   open       everything else.
#
# A round is the automatic review that posted a thread, by its review id. A
# review that posted nothing has no threads and so no row; the runs line below
# counts every run.
#
# Silent on trouble, like pr_context.py: no gh, no network — it says what it
# could not read and prints the rest.
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pr_context import RESOLVER_PREFIX, gh_json, is_claude_review, yours  # noqa: E402

QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved path line originalLine
          comments(first: 50) {
            nodes { body createdAt url pullRequestReview { databaseId submittedAt } }
          }
        }
      }
    }
  }
}
"""

# How close a new finding has to sit to an earlier fixed one, in lines, to
# count as brought by that fix. A fix moves a few lines around; a finding a
# screen away is about something else.
NEAR_LINES = 5

# Below this share acted on, the review is mostly asking for things nobody
# fixes (see the header).
ACTED_ON_FLOOR = 0.4


def parse(ts):
    try:
        d = datetime.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


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
            review = first.get("pullRequestReview") or {}
            fixed = any((c.get("body") or "").lstrip().startswith(RESOLVER_PREFIX)
                        for c in comments[1:])
            if t.get("isResolved"):
                fate = "fixed" if fixed else "no fix"
            else:
                fate = "no fix" if first.get("url") in left else "open"
            line = t.get("line") or t.get("originalLine")
            out.append({
                "path": t.get("path") or "?",
                "line": line if isinstance(line, int) else None,
                "created": parse(first.get("createdAt")),
                "round": review.get("databaseId") or first.get("createdAt"),
                "round_at": parse(review.get("submittedAt") or first.get("createdAt")),
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


def mark_near_fixes(found):
    """Marks each thread posted near a line an earlier round's fixed thread
    sat on, in the same file."""
    for i, t in enumerate(found):
        t["near_fix"] = t["line"] is not None and any(
            e["fate"] == "fixed" and e["path"] == t["path"] and e["line"] is not None
            and e["round"] != t["round"] and abs(e["line"] - t["line"]) <= NEAR_LINES
            for e in found[:i])


def rounds(found):
    """[(when, [threads])] per automatic review that posted threads, in order."""
    groups, order = {}, []
    for t in found:
        if t["round"] not in groups:
            groups[t["round"]] = []
            order.append(t["round"])
        groups[t["round"]].append(t)
    return [(groups[k][0]["round_at"], groups[k]) for k in order]


def review_runs(cwd, branch):
    """(runs, minutes) of the automatic review on the branch, or None."""
    if not branch:
        return None
    data = gh_json(["run", "list", "--branch", branch, "--limit", "200", "--json",
                    "workflowName,createdAt,updatedAt,conclusion"], cwd=cwd)
    if not isinstance(data, list):
        return None
    runs = [r for r in data
            if is_claude_review(r.get("workflowName") or "", r.get("workflowName") or "")]
    seconds = 0.0
    for r in runs:
        a, b = parse(r.get("createdAt")), parse(r.get("updatedAt"))
        if a and b and b > a:
            seconds += (b - a).total_seconds()
    return len(runs), seconds / 60


def sessions(cwd):
    """The review sessions from the feature's state: [{rounds, comments, costs,
    seconds}], oldest first."""
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
        out.append({"rounds": r.get("rounds"), "comments": r.get("comments"), "costs": costs,
                    "seconds": (b - a).total_seconds() if a and b and b > a else None})
    return out


def hours(seconds):
    m = int(round(seconds / 60))
    return "%dh%02dm" % (m // 60, m % 60) if m >= 60 else "%dm" % m


def pct(part, whole):
    return "%d%%" % round(100.0 * part / whole) if whole else "-"


def verdict(per_round, acted, near_last, last_found, open_now):
    """The trend in a sentence, from the figures alone."""
    words = []
    if not per_round:
        return "No findings yet."
    if len(per_round) < 3:
        words.append("Too few rounds for a trend.")
    else:
        head = sum(per_round[:2]) / 2.0
        tail = sum(per_round[-2:]) / 2.0
        if per_round[-1] > per_round[-2] >= per_round[-3]:
            words.append("Not converging: findings per round are climbing.")
        elif tail <= head * 0.5:
            words.append("Converging: the last two rounds found half or less of the first two.")
        elif tail < head:
            words.append("Converging slowly.")
        else:
            words.append("Not converging: findings per round hold level.")
    if acted is not None and acted < ACTED_ON_FLOOR:
        words.append("Under %d%% of the last rounds' findings were fixed: the review is mostly "
                     "asking for what nobody fixes." % (ACTED_ON_FLOOR * 100))
    if last_found and near_last * 2 >= last_found:
        words.append("Half or more of the last round's findings sit on earlier fixes: "
                     "the fixes are feeding the review.")
    if open_now == 0:
        words.append("Nothing is open.")
    return " ".join(words)


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
    mark_near_fixes(found)
    groups = rounds(found)

    if groups:
        print("")
        print("  %-3s %-12s %6s %6s %7s %5s %10s" % ("#", "posted", "found", "fixed", "no fix",
                                                     "open", "near fix"))
        per_round = []
        for i, (when, ts) in enumerate(groups, start=1):
            count = lambda fate: sum(1 for t in ts if t["fate"] == fate)  # noqa: E731
            per_round.append(len(ts))
            print("  %-3d %-12s %6d %6d %7d %5d %10d" % (
                i, when.astimezone().strftime("%m-%d %H:%M") if when else "?",
                len(ts), count("fixed"), count("no fix"), count("open"),
                sum(1 for t in ts if t["near_fix"])))
        total = len(found)
        fixed = sum(1 for t in found if t["fate"] == "fixed")
        nofix = sum(1 for t in found if t["fate"] == "no fix")
        opened = sum(1 for t in found if t["fate"] == "open")
        near = sum(1 for t in found if t["near_fix"])
        print("  %-16s %6d %6d %7d %5d %10d" % ("total", total, fixed, nofix, opened, near))
        print("")
        print("  Findings per round: %s" % " → ".join(str(n) for n in per_round))
        left = sum(1 for t in found if t["left_open"])
        print("  Fixed: %d (%s). Closed without a fix: %d (%s)%s." % (
            fixed, pct(fixed, total), nofix, pct(nofix, total),
            ", %d of them waiting for you to resolve on GitHub" % left if left else ""))
        # The share acted on, over the last two rounds whose findings are
        # settled: an open finding has not been decided yet.
        settled = [t for _, ts in groups[-2:] for t in ts if t["fate"] != "open"]
        acted = (sum(1 for t in settled if t["fate"] == "fixed") / float(len(settled))
                 if settled else None)
        if acted is not None:
            print("  Acted on in the last two rounds: %d%% of what was settled." % round(acted * 100))
    else:
        per_round, opened, near, acted, fixed = [], 0, 0, None, 0
        print("  No review threads on the pull request.")

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
              "as undoing a settled fix." % (near, "" if near == 1 else "s", reversals))
        spots = {}
        for t in found:
            spots.setdefault(t["path"], set()).add(t["round"])
        hot = sorted(((len(r), p) for p, r in spots.items() if len(r) >= 3), reverse=True)[:3]
        for n, p in hot:
            print("    %s: findings in %d rounds" % (p, n))

    # What it cost.
    runs = sessions(cwd)
    if runs:
        costs = [c for r in runs for c in r["costs"]]
        seconds = sum(r["seconds"] or 0 for r in runs)
        worked = sum(r["rounds"] for r in runs if isinstance(r["rounds"], int))
        line = "  Sessions: %d, %d round%s worked, %s" % (
            len(runs), worked, "" if worked == 1 else "s", hours(seconds))
        if costs:
            line += ", $%.2f" % sum(costs)
            line += " (last round $%.2f)" % costs[-1]
            if fixed:
                line += ", $%.2f per fixed finding" % (sum(costs) / fixed)
        else:
            line += ", cost not recorded"
        print(line)
    bot = review_runs(cwd, branch)
    if bot:
        print("  Automatic review: %d run%s, %s of runner time" % (
            bot[0], "" if bot[0] == 1 else "s", hours(bot[1] * 60)))

    last = groups[-1][1] if groups else []
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
