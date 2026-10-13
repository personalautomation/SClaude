#!/usr/bin/env python3
#
# What the review sessions of a product cost, read from the log
# review_context_log writes (sclaude/lib/run.sh), for `sclaude review-stats`.
#
# REVIEW_CONTEXT_MAX_PCT decides when a review round stays in the session that
# closed the last one and when it goes to a fresh session. The figure was set
# by judgement; this is what lets it be set by data:
#
#   * the door — what a session holds before it has done anything;
#   * a round — what one round of fixing adds to a session;
#   * the share — where the sessions ended, against the threshold, and what
#     one per cent of the window is in tokens;
#   * reversals — findings a session declined because applying them would
#     undo a fix the pull request had already settled, per round, in a
#     session's first round against its later ones. A fresh session is the
#     one expected to undo what it never saw settled; if the later rounds of a
#     long session start to show more, its context has stopped helping.
#
#   review_stats.py <log>
#
# Each line of the log, tab-separated:
#
#   time feature session outcome tokens_now tokens_start pct window rounds comments reversals
#
# A "-" is a figure that was not known. Silent on lines it cannot read.
import statistics
import sys

FIELDS = ("time", "feature", "session", "outcome", "now", "start", "pct",
          "window", "rounds", "comments", "reversals")


def number(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def rows(path):
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 10:
                    continue
                row = dict(zip(FIELDS, parts))
                for key in FIELDS[4:]:
                    row[key] = number(row.get(key))
                out.append(row)
    except OSError:
        pass
    return out


def segment(row):
    """Which round of its session the stretch a row closes was.

    A row is written where a session stopped: at a round's end ("carried on",
    "fresh session"), where `rounds` counts that round, or at the session's
    end ("done", "exit"), where it counts the rounds closed before it.
    """
    rounds = row["rounds"] or 0
    return rounds if row["outcome"] in ("carried on", "fresh session") else rounds + 1


def median(values):
    values = [v for v in values if v is not None]
    return int(statistics.median(values)) if values else None


def tokens(n):
    return "-" if n is None else "%dk" % round(n / 1000)


def report(data):
    if not data:
        return "No review sessions logged yet."
    lines = []
    outcomes = {}
    for row in data:
        outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
    sessions = {row["session"] for row in data}
    lines.append("%d review sessions, %d rows: %s" % (
        len(sessions), len(data),
        ", ".join("%s %d" % (k, v) for k, v in sorted(outcomes.items()))))

    # The door is the same for every row of a session; one per session.
    door = {}
    for row in data:
        door.setdefault(row["session"], row["start"])
    lines.append("A session holds %s before it does anything (median)." % tokens(median(door.values())))

    per_round = [(row["now"] - row["start"]) / segment(row)
                 for row in data
                 if row["now"] is not None and row["start"] is not None and segment(row)]
    lines.append("A round adds %s (median, over %d rows)." % (tokens(median(per_round)), len(per_round)))

    for outcome in sorted(outcomes):
        pcts = [row["pct"] for row in data if row["outcome"] == outcome]
        known = [p for p in pcts if p is not None]
        if known:
            lines.append("  %-14s ended at %d%% median, %d%% at most" % (
                outcome, median(known), max(known)))

    ratio = [row["now"] / row["pct"] for row in data
             if row["now"] is not None and row["pct"]]
    windows = sorted({row["window"] for row in data if row["window"]})
    if ratio:
        lines.append("1%% of the window is %s (window: %s)." % (
            tokens(median(ratio)), ", ".join(tokens(w) for w in windows) or "unknown"))

    first = [row for row in data if row["reversals"] is not None and segment(row) <= 1]
    later = [row for row in data if row["reversals"] is not None and segment(row) > 1]
    for label, group in (("first round of a session", first), ("later rounds", later)):
        if group:
            total = sum(row["reversals"] for row in group)
            lines.append("Reversals declined, %s: %d over %d stretches (%.2f each)." % (
                label, total, len(group), total / len(group)))
    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("usage: review_stats.py <log>\n")
        return 2
    print(report(rows(sys.argv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
