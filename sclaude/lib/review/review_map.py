#!/usr/bin/env python3
#
# The review's map of a feature: where in the code each review round sent
# the fixes, how the threads ended, and where the person stepped in. The
# process map's page draws it under the review step (process_review.js), from
# /__sclaude/flow/review?f=<label>, which runs this in the feature's tree.
#
#   review_map.py <tree>        one JSON object on stdout
#
# Nothing new is logged for it and no model reads anything: it is built from
# what is already there —
#
#   * the development: the pull request's diff up to its first round, per
#     file, and the time from its first commit to that round;
#   * the rounds: the review's journal (JOURNAL in local_review.py), a row a
#     pass, GitHub's runs among them, in order of time;
#   * the fixes: `git diff` from one round's head to the next one's (the last
#     to the tree's HEAD), each hunk placed by its line in the newer version,
#     so a place keeps its spot as the file grows around it;
#   * the threads: GitHub's review threads (path, line, the commit a comment
#     was posted on), and how each ended — fixed, declined ("Left as it is",
#     decline_of), the person's to decide (review-yours; one a night decided
#     is theirs too, the map does not tell it apart) or noted as undoing a settled fix (review-reversals: a reversal
#     for good, however it was resolved later);
#   * the person: each AskUserQuestion answered in the tree's transcripts —
#     how long it waited, whether the answer was the option marked
#     "(Recommended)", and the thread its question linked to — and the
#     answers to sclaude's own questions in the feature's history;
#   * which thread a fix answered: the fix session hands each finding to a
#     subagent with its path:line (review.md), and the subagent's transcript
#     beside the session's says which files it edited — the round's fixes in
#     those files answer that thread; a fix no subagent made (the session's
#     own, a line or two) takes the nearest thread of its round in its file;
#   * the blocks: the review blocks the pull request is cut into, if it is
#     (FEATURE_BLOCKS in review_blocks.py), each with its files and its id,
#     and the cuts that stood before a block was split (`earlier`);
#   * the cost: the conversations that started within a round.
#
# SCLAUDE_REVIEW_MAP_THREADS names a JSON file of thread nodes to read
# instead of asking GitHub (tests/review-map.py).
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import claude_usage  # noqa: E402
import cycle_steps  # noqa: E402
import pr_context  # noqa: E402
import review_report  # noqa: E402
from local_review import JOURNAL  # noqa: E402
import process_config  # noqa: E402
import review_blocks  # noqa: E402
from review_blocks import FEATURE_BLOCKS  # noqa: E402

STATE = ".sclaude/local/feature/state.json"
HISTORY = ".sclaude/local/feature/history.jsonl"
REVERSALS = ".sclaude/local/feature/review-reversals"  # reversals_file in review_round.sh

QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved isOutdated path line originalLine
          resolvedBy { login }
          comments(first: 50) { nodes { author { login __typename } body createdAt url
                                        originalCommit { oid } } }
        }
      }
    }
  }
}
"""

# A changed line that is a comment, by how it starts; a file of prose is all
# comment. Language-blind on purpose: sclaude knows no product's stack.
COMMENT_STARTS = ("#", "//", "/*", "*", "--", "<!--", '"""', "'''", ";", "%", "rem ")
PROSE = (".md", ".mdx", ".txt", ".rst", ".adoc")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
RID = re.compile(r"discussion_r(\d+)")
# How far, in lines, a fix may sit from a thread of its round to count as
# its answer.
NEAR = 15
# Code moved between files: the telling lines (MOVE_LINE characters or
# more) a hunk shares with another file's removal, at least MOVE_MIN.
MOVE_LINE = 6
MOVE_MIN = 3
# The share of a hunk's telling lines that must have moved for it to lose
# a thread found near it.
MOVE_ALL = 0.8


def ts(text):
    """An ISO time, with Z or an offset, as epoch seconds; None."""
    import datetime
    try:
        return datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def git(tree, *args):
    try:
        out = subprocess.run(["git", "-C", tree] + list(args), capture_output=True,
                             text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    except OSError:
        pass
    return out


def repo_of(tree, state):
    if state.get("repo"):
        return state["repo"]
    url = (git(tree, "remote", "get-url", "origin") or "").strip()
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


# --- the rounds ----------------------------------------------------------------

def rounds_of(tree, pr):
    """The journal's passes on this pull request that reviewed a head the
    tree has, in order of time; a head read again (a retry, a rerun) is one
    round, unless the review block changed — the next block's first pass on
    a head the last one left clean is that block's round (a pass with no
    block, a GitHub run, changes none). A pass stopped or not taken
    (`spent`, spent() in local_review.py) on a head of its own is a round
    too, `stopped`, as the report counts it: it found and read nothing that
    counts, and the commits after it are its fixes."""
    rows = [r for r in jsonl(os.path.join(tree, JOURNAL))
            if r.get("head") and ts(r.get("at")) is not None and (not pr or str(r.get("pr") or pr) == str(pr))]
    rows.sort(key=lambda r: ts(r["at"]))
    out = []
    for r in rows:
        if out and out[-1]["head"] == r["head"] and (out[-1]["block"] == r.get("block")
                                                     or None in (out[-1]["block"], r.get("block"))):
            out[-1]["block"] = out[-1]["block"] or r.get("block")
            out[-1]["seconds"] += int(r.get("seconds") or 0)
            if r.get("session"):
                (out[-1]["spent"] if r.get("spent") else out[-1]["sessions"]).append(r["session"])
            if r.get("spent"):
                continue
            out[-1]["stopped"] = False
            # The head's last pass says whether the round said all it found:
            # `more` is a pass that stopped at its cap.
            out[-1]["more"] = bool(r.get("more"))
            if r.get("new") is not None:
                out[-1]["new"] = (out[-1].get("new") or 0) + r["new"]
            continue
        if git(tree, "cat-file", "-e", r["head"] + "^{commit}") is None:
            continue
        out.append({"at": r["at"], "t": ts(r["at"]), "head": r["head"], "seconds": int(r.get("seconds") or 0),
                    "source": r.get("source") or "local", "new": None if r.get("spent") else r.get("new"),
                    "resolved": r.get("resolved"), "block": r.get("block"), "read": r.get("read"),
                    "more": False if r.get("spent") else bool(r.get("more")), "stopped": bool(r.get("spent")),
                    "sessions": [r["session"]] if r.get("session") and not r.get("spent") else [],
                    "spent": [r["session"]] if r.get("session") and r.get("spent") else []})
    # A GitHub run on a head read the whole pull request: every round on
    # that head is GitHub's, whatever a local pass beside it opened.
    github = {r["head"] for r in rows if r.get("source") == "github" and not r.get("spent")}
    for r in out:
        if r["head"] in github:
            r["source"] = "github"
    return out


def comment_line(path, text):
    if path.lower().endswith(PROSE):
        return True
    s = text.strip().lower()
    return bool(s) and s.startswith(COMMENT_STARTS)


def hunks(tree, a, b, texts=False):
    """[{path, x, n, add, del, code, comment}] of `git diff a b`: x and n the
    hunk's first line and length in b. A file b no longer has keeps its
    path, and its hunk is the whole file removed (x and n 0, `removed`). With `texts`,
    each hunk keeps the lines it wrote and removed as `_plus`/`_minus`."""
    out = git(tree, "diff", "-U0", "--no-color", "--no-ext-diff", "-M", a, b)
    if out is None:
        return []
    # The `---`/`+++` lines are headers only between `diff --git` and the
    # first hunk: inside a hunk with -U0, a removed `-- note` (SQL) reads
    # `--- note`, an added `++ x` reads `+++ x`.
    found, path, old, cur, head, removed = [], None, None, None, False, False
    for line in out.splitlines():
        if line.startswith("diff --git"):
            path = old = cur = None
            head, removed = True, False
            continue
        if head and line.startswith("--- "):
            old = line[6:] if line.startswith("--- a/") else None
            continue
        if head and line.startswith("+++ "):
            removed = line == "+++ /dev/null"
            path = line[6:] if line.startswith("+++ b/") else old if removed else None
            continue
        m = HUNK.match(line)
        if m:
            head = False
            if path is None:
                cur = None
                continue
            cur = {"path": path, "x": int(m.group(3)),
                   "n": int(m.group(4)) if m.group(4) is not None else 1,
                   "ox": int(m.group(1)), "on": int(m.group(2)) if m.group(2) is not None else 1,
                   "add": 0, "del": 0, "code": 0, "comment": 0}
            if removed:
                cur["removed"] = True
            if texts:
                cur["_plus"], cur["_minus"] = [], []
            found.append(cur)
            continue
        if cur is None or not line or line[0] not in "+-":
            continue
        cur["add" if line[0] == "+" else "del"] += 1
        if texts:
            cur["_plus" if line[0] == "+" else "_minus"].append(line[1:].strip())
        if line[1:].strip():
            cur["comment" if comment_line(path, line[1:]) else "code"] += 1
    return found


# A line that says something on its own, for telling code moved between
# files from code written anew: not a brace, a keyword alone or a blank.
def telling(s):
    return len(s) >= MOVE_LINE and any(c.isalnum() for c in s)


def moves(hs):
    """Code one round moved from one file to another: a hunk whose telling
    added lines are mostly lines another file's hunk of the same round
    removed (at least MOVE_MIN of them, and half its own) keeps those hunks
    as `_moved_from`, and each of them keeps it in `_moved_to`; a removal
    half of whose telling lines went on so is `_moved_out`, code moved away
    rather than deleted. `_moved_share` is the part of a side's telling
    lines that moved, from or to the files it names. A removed line accounts
    for as many added ones in the whole round as it was removed, no more.
    Content alone says it — no blame follows a line across files."""
    gone, told, sent, left = {}, {}, {}, {}
    for k, h in enumerate(hs):
        for s in h.get("_minus", ()):
            if telling(s):
                at = gone.setdefault(s, {})
                at[k] = at.get(k, 0) + 1
                told[k] = told.get(k, 0) + 1
    for k, h in enumerate(hs):
        plus = [s for s in h.get("_plus", ()) if telling(s)]
        if len(plus) < MOVE_MIN:
            continue
        # The sources first, by every line each could give (what is left of
        # it this round); then each line goes to one of them only, so a hunk
        # that happens to share a line or two with the real source takes
        # none from it. Tried on a copy: only a move takes what it matched.
        can, held = {}, {}
        for s in plus:
            for j, n in gone.get(s, {}).items():
                if hs[j]["path"] != h["path"] and left.get((s, j), n) - held.get((s, j), 0) > 0:
                    held[s, j] = held.get((s, j), 0) + 1
                    can[j] = can.get(j, 0) + 1
        most = max(can.values(), default=0)
        srcs = {j for j, n in can.items() if n >= min(MOVE_MIN, most)}
        by, took = {}, {}
        for s in plus:
            for j, n in gone.get(s, {}).items():
                key = (s, j)
                if j in srcs and left.get(key, n) - took.get(key, 0) > 0:
                    took[key] = took.get(key, 0) + 1
                    by[j] = by.get(j, 0) + 1
                    break
        # The bar is on what a source could give, each removed copy once
        # (`held`): handed out, a line two sources share goes to one, and
        # the other keeps the lines only it removed.
        srcs = [j for j in srcs if by.get(j)]
        hit = sum(by[j] for j in srcs)
        if hit < MOVE_MIN or hit * 2 < len(plus):
            continue
        for (s, j), n in took.items():
            if j in srcs:
                left[s, j] = left.get((s, j), gone[s][j]) - n
        h["_moved_from"] = [hs[j] for j in sorted(srcs)]
        h["_moved_share"] = hit / len(plus)
        for j in srcs:
            hs[j].setdefault("_moved_to", []).append(h)
            sent[j] = sent.get(j, 0) + by[j]
    for j, n in sent.items():
        share = n / told[j]
        if share * 2 >= 1:
            hs[j]["_moved_out"] = True
            hs[j]["_moved_share"] = max(share, hs[j].get("_moved_share", 0))
    for h in hs:
        h.pop("_plus", None)
        h.pop("_minus", None)


def asked_lines(tree, a, b):
    """{path: lines in b} that the commits from a to b the person asked for
    wrote: a `feat` commit (Conventional Commits) or one carrying a
    `Requirement:` trailer — the development going on during the review, not
    a fix of a finding (review.md: a fix needs no Requirement footer). A
    blame of each file they touched says which lines are theirs."""
    log = git(tree, "log", "--first-parent", "--no-merges",
              "--format=%x01%H%x02%s%x02%(trailers:key=Requirement,valueonly,separator=;)", a + ".." + b) or ""
    mine = set()
    for rec in log.split("\x01")[1:]:
        sha, subject, req = (rec.strip("\n").split("\x02") + ["", ""])[:3]
        if re.match(r"feat(\(|!|:)", subject) or req.strip():
            mine.add(sha)
    out = {}
    for sha in mine:
        for path in (git(tree, "show", "--name-only", "--format=", sha) or "").split("\n"):
            if not path or path in out:
                continue
            got = set()
            for line in (git(tree, "blame", "-l", "-s", "--root", a + ".." + b, "--", path) or "").splitlines():
                m = re.match(r"\^?([0-9a-f]{40})\s+(\d+)\)", line) or re.match(r"\^?([0-9a-f]{40})\s+(?:\S+\s+)?(\d+)\)", line)
                if m and m.group(1) in mine:
                    got.add(int(m.group(2)))
            out[path] = got
    return out


def project(paths, rounds, fixes, threads, dev, final):
    """Each file's lines on one axis for the whole review: every line that
    was ever in it keeps a place — a line deleted keeps its place, the lines
    a fix wrote stand right after the ones it replaced — so a place is the
    same place in every round, and an icicle grows from the lines it
    changed. Sets p0/p1 on each fix (its place: the lines it removed and the
    lines it wrote), p on each thread, `proj` on each file of `dev` (its
    regions) and returns {path: length of its axis}. A file whose fixes do
    not add up to its next version (a rename, a binary) gets no axis, and
    the page places it by line numbers as before.

    A place is a line's identity, so the axis is also a blame: `writer`
    holds the fix that wrote each place. A fix of the review (one with an
    `i`) gets `_blame`, the fixes whose lines it rewrote (or, writing new
    lines only, the one fix whose lines it went in between), and a thread
    `_of`, the fix that wrote the line it was posted on: lineage() reads
    both."""
    lengths = {}
    by_spot = {}
    for h in fixes:
        by_spot.setdefault((h["r"], h["path"]), []).append(h)
    for f in paths:
        n0 = rounds[0]["lines"].get(f, 0)
        cur, axis, nxt = list(range(n0)), list(range(n0)), n0
        snaps, owned, ok, writer = [], [], True, {}
        for i, r in enumerate(rounds):
            snaps.append(list(cur))
            hs = sorted(by_spot.get((i, f), ()), key=lambda h: h["ox"])
            plans = []
            for h in hs:
                gone = cur[h["ox"] - 1:h["ox"] - 1 + h["on"]] if h["on"] else []
                anchor = gone[-1] if gone else (cur[h["ox"] - 1] if 1 <= h["ox"] <= len(cur) else None)
                new = list(range(nxt, nxt + h["n"] if h["add"] else nxt))
                nxt += len(new)
                plans.append((h, gone, anchor, new))
                # The person's asks are the development's lines: no fix of
                # the review wrote them, nor grows from them.
                if "i" in h and not h.get("asked"):
                    if gone:
                        by = {writer[s]["i"] for s in gone if "i" in writer.get(s, {})}
                    else:
                        after = cur[h["ox"]] if 0 <= h["ox"] < len(cur) else None
                        a, b = writer.get(anchor, {}), writer.get(after, {})
                        by = {a["i"]} if "i" in a and a is b else set()
                    h["_blame"] = sorted(by)
            for h, gone, anchor, new in plans:
                if not h.get("asked"):
                    for s in new:
                        writer[s] = h
            # Inserted from the end of the axis back, so the places found
            # once for the round still hold.
            where = {slot: k for k, slot in enumerate(axis)} if plans else {}
            for h, gone, anchor, new in sorted(plans, key=lambda p: where.get(p[2], -1), reverse=True):
                at = where[anchor] + 1 if anchor is not None else 0
                axis[at:at] = new
            owned += [(h, gone + new) for h, gone, anchor, new in plans]
            for h, gone, anchor, new in reversed(plans):
                start = h["ox"] - 1 if h["on"] else h["ox"]
                cur[start:start + h["on"]] = new
            nxt_lines = rounds[i + 1]["lines"].get(f, 0) if i + 1 < len(rounds) else final.get(f, 0)
            if len(cur) != nxt_lines:
                ok = False
                break
        if not ok:
            for h in fixes:
                if h["path"] == f:
                    h.pop("_blame", None)
            continue
        pos = {slot: k for k, slot in enumerate(axis)}
        lengths[f] = len(axis)
        for h, slots in owned:
            ps = [pos[s] for s in slots if s in pos]
            if ps:
                h["p0"], h["p1"] = min(ps), max(ps) + 1
        for t in threads:
            if t["path"] == f and t["r"] is not None and t["r"] < len(snaps):
                snap = snaps[t["r"]]
                if 1 <= (t["line"] or 0) <= len(snap):
                    t["p"] = pos[snap[t["line"] - 1]]
                    by = writer.get(snap[t["line"] - 1], {})
                    if "i" in by:
                        t["_of"] = by["i"]
        d = dev["files"].get(f)
        if d:
            d["proj"] = [[pos[snaps[0][x - 1]], pos[snaps[0][min(x + n - 1, len(snaps[0])) - 1]] + 1]
                         for x, n in d["regions"] if 1 <= x <= len(snaps[0])]
    return lengths


def line_counts(tree, rev, paths):
    """{path: lines} at rev, for the paths it has."""
    counts = {p: 0 for p in paths}
    if not paths:
        return counts
    out = git(tree, "grep", "-c", "-I", "--no-color", "", rev, "--", *paths) or ""
    for line in out.splitlines():
        # rev:path:count
        body = line[len(rev) + 1:] if line.startswith(rev + ":") else line
        path, _, n = body.rpartition(":")
        if path in counts and n.isdigit():
            counts[path] = int(n)
    return counts


def alive(tree, base, first, end, paths, moved=()):
    """{path: [dev, review, main]}: the lines of each file at `end` by who
    wrote them, by blame — the development (a commit before the first
    round, after `base`), the review's time (a commit of the branch after
    the first round's head: its fixes and the person's asks alike), or
    main (the rest: what was there before the pull request, or merged in:
    the review's commits are the branch's own, its first parents, so main's
    commits a sync brought in stay main's). Blame stops at `base`: older
    lines are main's whatever their commit. Once the feature is merged into
    main, `base` is the first round's head and the development counts for
    nothing here — as everywhere on the map, which reads a feature in review.
    What is left of the development's code, against what it wrote."""
    def listed(*args):
        return set((git(tree, "rev-list", *args) or "").split())
    dev = listed(first, "--not", base) if base else set()
    later = listed("--first-parent", end, "--not", first, *([base] if base else []))
    # A block file the review renamed is blamed under its name at the end;
    # re-indented code keeps its writer (-w), and in a file code was moved
    # into (`moved`, the map's movedFrom) so does code from another file
    # (-C) — costly, so there alone: the map counts a move apart from the
    # fixes.
    # -z: a path git would quote (a non-ASCII name) is read as it is. (A
    # path with a file of its own again at the end is no rename to git.)
    renamed = {}
    fields = (git(tree, "diff", "-z", "--name-status", "-M", "--diff-filter=R", first, end) or "").split("\0")
    for k in range(0, len(fields) - 2, 3):
        if fields[k].startswith("R"):
            renamed[fields[k + 1]] = fields[k + 2]
    out = {}
    for f in paths:
        n = [0, 0, 0]
        at = renamed.get(f, f)
        for line in (git(tree, "blame", "--porcelain", "-M", "-w", *(["-C"] if at in moved else []),
                         base + ".." + end if base else end, "--", at) or "").splitlines():
            p = line.split(" ")
            # A header line: the commit, its line there, its line here[, count].
            if len(p) >= 3 and len(p[0]) == 40 and p[1].isdigit() and p[2].isdigit():
                n[0 if p[0] in dev else 1 if p[0] in later else 2] += 1
        if any(n):
            out[f] = n
    return out


def absent_files(tree, rev, paths):
    """The paths rev does not have, sorted. The whole tree is listed rather
    than asked by pathspec, which would read `[id]` in a path as a glob."""
    have = set((git(tree, "ls-tree", "-r", "-z", "--name-only", rev) or "").split("\0"))
    return sorted(p for p in paths if p not in have)


# --- the threads ---------------------------------------------------------------

def thread_nodes(tree, pr, repo):
    fake = os.environ.get("SCLAUDE_REVIEW_MAP_THREADS")
    if fake:
        return read_json(fake, [])
    if not pr or "/" not in repo:
        return []
    owner, name = repo.split("/", 1)
    nodes, after = [], None
    while True:
        args = ["api", "graphql", "-f", "query=%s" % QUERY, "-F", "owner=%s" % owner,
                "-F", "name=%s" % name, "-F", "number=%s" % pr]
        if after:
            args += ["-f", "after=%s" % after]
        data = pr_context.gh_json(args, cwd=tree)
        try:
            page = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        except (TypeError, KeyError):
            return nodes
        nodes += page.get("nodes") or []
        info = page.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return nodes
        after = info.get("endCursor")


def tab_file(path):
    """{link: text} of a file of `link<TAB>text` lines; `#` lines are marks."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                link, _, text = line.rstrip("\n").partition("\t")
                if link.strip() and not link.startswith("#"):
                    out[link.strip()] = text
    except OSError:
        pass
    return out


def headline(body):
    m = re.search(r"\*\*(.+?)\*\*", body or "")
    text = m.group(1) if m else (body or "").strip().splitlines()[0] if (body or "").strip() else ""
    return text[:200]


def shifted(tree, a, b, path, line, cache):
    """Line `line` of path at commit a, as a line of it at b: moved by the
    hunks above it, the first line of the hunk that rewrote it."""
    if (a, b) not in cache:
        cache[a, b] = hunks(tree, a, b) if git(tree, "cat-file", "-e", a + "^{commit}") is not None else []
    delta = 0
    for h in sorted((h for h in cache[a, b] if h["path"] == path), key=lambda h: h["ox"]):
        if h["on"] == 0:
            if line <= h["ox"]:
                break
        elif line < h["ox"]:
            break
        elif line < h["ox"] + h["on"]:
            # The whole file removed: no line of b to move it to.
            return line if h.get("removed") else max(1, h["x"])
        delta += h["n"] - h["on"]
    return max(1, line + delta)


def threads_of(tree, nodes, rounds):
    yours = pr_context.yours(tree)
    reversed_ = tab_file(os.path.join(tree, REVERSALS))
    out, moves = [], {}
    for t in nodes:
        comments = ((t.get("comments") or {}).get("nodes")) or []
        if not comments:
            continue
        first = comments[0]
        url = first.get("url") or ""
        rid = RID.search(url)
        bot = ((first.get("author") or {}).get("__typename")) == "Bot" \
            or pr_context.signed_locally(first.get("body"))
        # A finding noted as undoing a settled fix is a reversal for good,
        # however it was resolved later: the colour says the review proposed
        # it, the tooltip how the thread ended. Decided by the user on
        # 2026-11-15: whether one resolved without a decline was applied
        # after all or left by hand cannot be told — a subagent's brief, a
        # reply's commit, a fix near its line each misread one case.
        if url in reversed_:
            outcome = "reversal"
        elif url in yours:
            # Decided at night or not, it waits for the person: one colour
            # (the user's word, 2026-11-17).
            outcome = "yours"
        elif pr_context.decline_of(comments[1:]):
            outcome = "declined"
        elif t.get("isResolved"):
            outcome = "fixed"
        else:
            outcome = "open"
        commit = ((first.get("originalCommit") or {}).get("oid")) or ""
        at = first.get("createdAt") or ""
        # Rounds of two blocks can share a head: the last of them started by
        # the thread's time.
        same = [i for i, x in enumerate(rounds) if x["head"] == commit]
        r = max([i for i in same if rounds[i]["t"] <= (ts(at) or 0)] or same[:1]) if same else None
        line = t.get("originalLine") or t.get("line") or 0
        if r is None:
            r = round_at(rounds, ts(at))
            # Posted on a commit between round heads: its line is carried to
            # the round's head, where the page places it.
            if r is not None and commit and line:
                line = shifted(tree, commit, rounds[r]["head"], t.get("path") or "", line, moves)
        out.append({"rid": "r" + rid.group(1) if rid else "", "url": url,
                    "t": ts(at), "path": t.get("path") or "", "line": line,
                    "at": at, "r": r, "outcome": outcome, "by": "review" if bot else "person",
                    "resolvedBy": ((t.get("resolvedBy") or {}).get("login")) or "",
                    # How a reversal's thread ended, for its hover: the
                    # outcome alone no longer says it.
                    "resolved": bool(t.get("isResolved")), "left": bool(pr_context.decline_of(comments[1:])),
                    "title": headline(first.get("body")),
                    "_replies": [c.get("body") or "" for c in comments[1:]]})
    return out


SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


def replied(tree, rounds, ends, threads, fixes):
    """A thread whose reply names the commit that fixed it — "Fixed in
    <sha>: …", sclaude's own "fixed in <sha>." — and, in its words, the file
    the fix landed in: the round's fixes in that file with no thread of
    their own answer this one (`via` reply), and the thread keeps the file
    (`fixedIn`), where the page lets its icicle slide when it is another
    file. A file is named by its name; by its stem when the stem is no plain
    word (a digit, _ or - in it); or by the stem's first part when that holds
    a digit and no other file of the commit shares it; a commit outside every
    round's range is no fix of the review, nor is a commit a thread left as
    it is names."""
    commits = {}
    spans = {}
    def changes(a, b, path):
        """{(ox, on, body)} of `git diff -U0 a b -- path`."""
        out, cur, body = set(), None, []
        for line in (git(tree, "diff", "-U0", "--no-color", "--no-ext-diff", a, b, "--", path) or "").splitlines() + ["@@"]:
            if line.startswith("@@"):
                if cur:
                    out.add(cur + ("\n".join(body),))
                m = HUNK.match(line)
                cur = (int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1) if m else None
                body = []
            elif cur and line[:1] in "+-":
                body.append(line)
        return out
    def wrote(full, r, h):
        """Whether commit `full` changed fix h's lines: the round's diff up
        to it against the one up to its parent, both from the round's head,
        so what it alone changed is in the head's lines as h is — a
        deletion too, and whatever a later commit of the round did there."""
        key = (full, r, h["path"])
        if key not in spans:
            head = rounds[r]["head"]
            spans[key] = [(ox, on) for ox, on, _ in changes(head, full, h["path"]) - changes(head, full + "^", h["path"])]
        lo, hi = h["ox"], h["ox"] + max(h["on"], 1) - 1
        return any(ox <= hi and lo <= ox + max(on, 1) - 1 for ox, on in spans[key])
    # Each round's commits: those after its head and up to its end on a line
    # of descent between them (`--ancestry-path`, so main's commits a merge
    # brought in are none of them) — one listing a round, not two ancestry
    # questions a round for every commit a reply names.
    member = {}
    def round_of(sha):
        if sha not in commits:
            full = (git(tree, "rev-parse", "--verify", "-q", sha + "^{commit}") or "").strip()
            commits[sha] = None
            if full and not member:
                for i, r in enumerate(rounds):
                    if r["head"] != ends[i]:
                        for c in (git(tree, "rev-list", "--ancestry-path", r["head"] + ".." + ends[i]) or "").split():
                            member.setdefault(c, i)
                member.setdefault("", None)
            if full and member.get(full) is not None:
                names = [n for n in (git(tree, "show", "--name-only", "--format=", full) or "").splitlines() if n]
                commits[sha] = (member[full], names, full)
        return commits[sha]
    for t in threads:
        # A thread left as it is names commits as its reasons — the fix it
        # would undo, the decision it stands on — not as its fix.
        if t["outcome"] in ("declined", "reversal", "yours"):
            continue
        text = "\n".join(t.get("_replies") or [])
        for sha in SHA.findall(text):
            found = round_of(sha)
            if not found:
                continue
            r, names, full = found
            def said(name):
                base = os.path.basename(name)
                stem = base.rsplit(".", 1)[0]
                if re.search(r"(?<![\w.-])" + re.escape(base) + r"(?![\w-])", text) \
                        or (re.search(r"[\d_-]", stem) and re.search(r"(?<![\w.-])" + re.escape(stem) + r"(?![\w-])", text)):
                    return 2
                lead = re.split(r"[_.-]", stem)[0]
                if re.search(r"\d", lead) and re.search(r"(?<![\w.-])" + re.escape(lead) + r"(?![\w-])", text):
                    return 1
                return 0
            scored = [(said(n), n) for n in names]
            best = [n for s, n in scored if s == 2]
            if not best:
                ones = [n for s, n in scored if s == 1]
                leads = {}
                for n in names:
                    lead = re.split(r"[_.-]", os.path.basename(n).rsplit(".", 1)[0])[0]
                    leads[lead] = leads.get(lead, 0) + 1
                best = [n for n in ones if leads[re.split(r"[_.-]", os.path.basename(n).rsplit(".", 1)[0])[0]] == 1]
            # The thread's own file needs no naming: "Fixed in <sha>" of a
            # commit that changed it is a fix there — of the round's fixes in
            # it that answer nothing else, only those whose lines that very
            # commit changed (wrote()), so the round's other work in a long
            # file is not taken for it — named in the reply or not.
            own = t["path"] in names
            if own and t["path"] not in best:
                best.append(t["path"])
            if not best:
                continue
            # Another file is where the page lets the icicle slide; its own
            # is where it grows anyway.
            away = [n for n in best if n != t["path"]]
            if away:
                t["fixedIn"] = {"r": r, "files": away}
            for h in fixes:
                if h["r"] == r and h["path"] in best and not h["thread"]:
                    if own and h["path"] == t["path"] and not wrote(full, r, h):
                        continue
                    h["thread"], h["outcome"], h["via"] = t["rid"], t["outcome"], "reply"
            break


def settled(t):
    """A thread with an outcome that needs nobody: fixed, declined, or a
    reversal left as it is or resolved — the page's settled()."""
    return t["outcome"] in ("fixed", "declined") or (t["outcome"] == "reversal" and (t["left"] or t["resolved"]))


def lineage(rounds, fixes, threads):
    """What each fix grows from — the icicle it continues — and which
    threads a check missed. An icicle is one problem's line of descent: a
    thread, the fix that answered it (`thread`), threads later posted on
    the lines that fix wrote (`_of`, project's blame), their fixes, and so
    on; a fix answering no thread grows from the fixes whose lines it
    rewrote (`_blame`). Nearness on the axis says nothing.

    A chain closes at the first round after its last fix or thread that
    read it whole and found nothing there: every thread of it settled, the
    round neither stopped nor cut short at its cap (`more`), all its files
    that are still there opened (a GitHub run, which leaves no transcript
    here, taken as read; a file the fixes removed asks no reading),
    and no thread of that round on its lines — unless that round's own
    fixing then lands on it, which keeps it going. After that a change there is
    something new and starts an icicle of its own — except a thread on the
    lines the chain wrote: that is a problem in the review's own fix which
    the closing round read and passed. The chain goes on through it, and
    the thread keeps `missed`, the round that closed the chain too early —
    when it was a problem: fixed, or still open or with the person; a
    declined one reopens the chain without the mark.
    Only a chain that fixed a thread can miss one: a closed chain of fixes
    answering none is code the review wrote unasked, and a thread there
    later is new, its `of` dropped. Writes `from` on each fix and `of`/`missed` on each thread."""
    root = list(range(len(fixes)))
    def find(k):
        while root[k] != k:
            root[k] = root[root[k]]
            k = root[k]
        return k
    chains = {}
    by_rid = {t["rid"]: t for t in threads if t["rid"]}
    for i, r in enumerate(rounds):
        on = {}
        for t in threads:
            if t.get("_of") is not None and t["r"] is not None and t["r"] <= i:
                on.setdefault(find(t["_of"]), []).append(t)
        if not r["stopped"] and not r["more"]:
            for c, ch in chains.items():
                if ch["closed"] is not None or ch["last"] >= i:
                    continue
                if any(t["r"] == i for t in on.get(c, [])):
                    continue
                # A file the fixes removed is read by nobody: what is left of
                # the chain is what the round has to open. All of it gone,
                # nothing is left to check but its threads.
                there = ch["files"] - set(r.get("absent") or ())
                if r["seen"] is not None and not there <= set(r["seen"]):
                    continue
                answered = [by_rid[fixes[k]["thread"]] for k in ch["members"] if fixes[k]["thread"] in by_rid]
                if all(settled(t) for t in answered + [t for t in on.get(c, []) if t["r"] < i]):
                    ch["closed"] = i
        for t in threads:
            if t["r"] != i or t.get("_of") is None:
                continue
            ch = chains.get(find(t["_of"]))
            if ch is None:
                continue
            if ch["closed"] is not None:
                if not any(fixes[k]["thread"] in by_rid for k in ch["members"]):
                    # Code the review wrote answering no thread — often
                    # pages of it — closed and later found wanting: no fix
                    # of a problem was passed, so this one is new.
                    t["_of"] = None
                    continue
                # A real problem found there, or one still waiting: the check
                # missed it. A declined one was no problem, and a reversal
                # is the review undoing its own fix, already told in red.
                if t["outcome"] in ("fixed", "open", "yours"):
                    t["missed"] = ch["closed"]
                ch["closed"] = None
            ch["last"] = max(ch["last"], i)
        for k, h in enumerate(fixes):
            if h["r"] != i:
                continue
            t = by_rid.get(h["thread"])
            raw = ([t["_of"]] if t.get("_of") is not None else []) if t else h.get("_blame", [])
            # The closing round's own fixing is not over yet: a fix of it
            # landing on the chain keeps it going (the page's `closing`).
            h["from"] = [p for p in raw if fixes[p]["r"] < i and chains[find(p)]["closed"] in (None, i)]
            for p in h["from"]:
                chains[find(p)]["closed"] = None
            chains[k] = {"members": [k], "files": {h["path"]}, "last": i, "closed": None}
            for p in h["from"]:
                a, b = find(p), find(k)
                if a == b:
                    continue
                root[b] = a
                ca, cb = chains[a], chains.pop(b)
                ca["members"] += cb["members"]
                ca["files"] |= cb["files"]
                ca["last"] = max(ca["last"], cb["last"])
    for h in fixes:
        h.pop("_blame", None)
        h.setdefault("from", [])
    for t in threads:
        t["of"] = t.pop("_of", None)


# A diff header at a line's start, or after the line number a Read of a
# saved diff puts before it.
DIFF_HEADER = re.compile(r"^(?:\s*\d+\t)?diff --git a/(\S+)", re.M)


def named(path, text):
    """Whether text names path itself, not a longer path ending in it
    (lib/x.js inside src/lib/x.js)."""
    return re.search(r"(?<![\w./-])" + re.escape(path) + r"(?![\w/-])", text) is not None


RANK = {"part": 1, "diff": 2, "whole": 3}
READ_WHOLE = 2000  # lines the Read tool gives without a limit


def seen_files(tree, sessions, paths, lines=None):
    """The files of the pull request a round's passes opened — read (Read,
    Grep), named in a command (git diff -- it, cat, sed), or shown as a diff
    header in a command's output — in the passes' transcripts and their
    subagents' (a saved long output counts once a Read shows it), each with
    how far: "whole" (a Read of all of it: no offset or limit, the file
    within what one Read gives, by `lines`), "diff" (its changes shown) or
    "part" (a slice, a search, a name in a command). None when no pass left
    a transcript here (a GitHub run): what it read is not known. A pass that
    found nothing in a file it never opened says nothing about it."""
    folder = os.path.join(claude_usage.ROOT, claude_usage.project_name(tree))
    found, any_read = {}, False
    wanted = set(paths)
    root = tree.rstrip("/") + "/"

    def saw(p, how):
        if RANK[how] > RANK.get(found.get(p), 0):
            found[p] = how
    for sid in sessions:
        files = [os.path.join(folder, sid + ".jsonl")]
        try:
            sub = os.path.join(folder, sid, "subagents")
            files += [os.path.join(sub, n) for n in os.listdir(sub) if n.endswith(".jsonl")]
        except OSError:
            pass
        for path in files:
            try:
                fh = open(path, encoding="utf-8")
            except OSError:
                continue
            any_read = True
            with fh:
                for line in fh:
                    if '"tool_use"' not in line and '"tool_result"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    content = (e.get("message") or {}).get("content")
                    if not isinstance(content, list):
                        continue
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_use":
                            # The file tools name a file by its absolute path.
                            inp = b.get("input") or {}
                            text = json.dumps(inp, ensure_ascii=False).replace(root, "")
                            whole = None
                            if b.get("name") == "Read" and not inp.get("offset") and not inp.get("limit"):
                                whole = str(inp.get("file_path") or "").replace(root, "")
                            for p in wanted:
                                if p in text and named(p, text):
                                    # Its change counts as read only where a diff of it
                                    # was shown (DIFF_HEADER, below): a command naming
                                    # git diff may print counts or names alone.
                                    saw(p, "whole" if p == whole and (lines or {}).get(p, 0) <= READ_WHOLE else "part")
                        elif b.get("type") == "tool_result":
                            c = b.get("content")
                            c = c if isinstance(c, str) else " ".join(
                                x.get("text") or "" for x in c or [] if isinstance(x, dict))
                            for p in DIFF_HEADER.findall(c):
                                if p in wanted:
                                    saw(p, "diff")
    return found if any_read else None


def round_at(rounds, at):
    """The round a moment falls in: the last one started at or before it;
    None before the first."""
    found = None
    if at is None:
        return None
    for i, r in enumerate(rounds):
        if r["t"] <= at:
            found = i
    return found


# --- the person ----------------------------------------------------------------

def transcripts(tree):
    folder = os.path.join(claude_usage.ROOT, claude_usage.project_name(tree))
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names if n.endswith(".jsonl")]


# A file in a brief, and the line a finding sits at when it says one —
# `path:12`, `path` (~line 12), path line 12.
LOCATION = re.compile(r"([\w./@()\[\]+-]+\.[A-Za-z0-9]+)`?(?::(\d+)|[^\n]{0,24}?\bline\s*~?(\d+))?")
EDITS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


def agents_of(tree, rounds, threads):
    """The fix sessions' subagents that edited files, each with the threads
    its brief names — a discussion_r link, or a file with the line of a
    finding within ten lines of one of its round's threads — its round (when it started) and the files it
    edited: [{r, threads, files}]. Subagents whose brief names no thread are
    left out."""
    folder = os.path.join(claude_usage.ROOT, claude_usage.project_name(tree))
    try:
        sessions = [os.path.join(folder, n, "subagents") for n in os.listdir(folder)]
    except OSError:
        return []
    by_rid = {t["rid"]: t for t in threads if t["rid"]}
    out = []
    for where in sessions:
        try:
            names = [n for n in os.listdir(where) if n.endswith(".jsonl")]
        except OSError:
            continue
        for name in names:
            brief, start, files = None, None, set()
            path = os.path.join(where, name)
            try:
                # Last written before the first round: no fix of the review.
                if os.path.getmtime(path) < rounds[0]["t"]:
                    continue
                fh = open(path, encoding="utf-8")
            except OSError:
                continue
            with fh:
                for line in fh:
                    if brief is not None and '"tool_use"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    content = (e.get("message") or {}).get("content")
                    if brief is None and e.get("type") == "user":
                        brief = content if isinstance(content, str) else " ".join(
                            b.get("text") or "" for b in content or [] if isinstance(b, dict))
                        start = e.get("timestamp")
                    if e.get("type") == "assistant" and isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in EDITS:
                                p = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                                if p:
                                    files.add(os.path.relpath(p, tree) if os.path.isabs(p) else p)
            if not files or not brief:
                continue
            r = round_at(rounds, ts(start))
            if r is None:
                continue
            ours = [t for t in threads if t["r"] == r]
            named = [by_rid["r" + m] for m in RID.findall(brief) if "r" + m in by_rid]
            for path, a, b in LOCATION.findall(brief):
                on = [t for t in ours if t["path"] == path or t["path"].endswith("/" + path)]
                # A file named with no line is not a finding: a brief that
                # builds something names files without one.
                line = a or b
                if line:
                    # The thread nearest the line, within ten: a brief's line
                    # is the finding's, give or take what moved since.
                    gaps = [(abs((t["line"] or 0) - int(line)), i) for i, t in enumerate(on)]
                    gaps = [g for g in gaps if g[0] <= 10]
                    if gaps:
                        named.append(on[min(gaps)[1]])
            seen = []
            for t in named:
                if t not in seen:
                    seen.append(t)
            if seen:
                out.append({"r": r, "threads": seen, "files": files, "id": name[:-6]})
    return out


def seconds_between(a, b):
    pa, pb = ts(a), ts(b)
    return None if pa is None or pb is None else max(0, int(pb - pa))


def asked(path, since):
    """Each question answered in one transcript at or after `since`:
    {at, waited, q, a, rec, rid}."""
    asks, out = {}, []
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return out
    with fh:
        for line in fh:
            if "AskUserQuestion" not in line and '"answers"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            msg = entry.get("message") or {}
            for block in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion":
                    asks[block.get("id")] = (entry.get("timestamp") or "",
                                             (block.get("input") or {}).get("questions") or [])
                elif block.get("type") == "tool_result" and block.get("tool_use_id") in asks:
                    when, questions = asks.pop(block["tool_use_id"])
                    result = entry.get("toolUseResult")
                    answers = result.get("answers") if isinstance(result, dict) else None
                    if not isinstance(answers, dict) or (ts(when) or 0) < since:
                        continue
                    waited = seconds_between(when, entry.get("timestamp") or "")
                    for q in questions:
                        text = q.get("question") or ""
                        answer = answers.get(text)
                        if answer is None:
                            continue
                        labels = [o.get("label") or "" for o in q.get("options") or []]
                        rec = [lb for lb in labels if "(Recommended)" in lb]
                        rid = RID.search(text + " " + json.dumps(q.get("options") or []))
                        out.append({"at": when, "t": ts(when), "waited": waited, "q": text[:400],
                                    "a": str(answer)[:200], "kind": "question",
                                    "rec": (answer in rec) if rec else None,
                                    "rid": "r" + rid.group(1) if rid else ""})
    return out


def hands_of(tree, rounds, threads):
    if not rounds:
        return []
    since = rounds[0]["t"]
    out = []
    for path in transcripts(tree):
        try:
            if os.path.getmtime(path) < since:
                continue
        except OSError:
            continue
        out += asked(path, since)
    for row in jsonl(os.path.join(tree, HISTORY)):
        if row.get("what") == "ask" and row.get("op") == "answered" and (ts(row.get("at")) or 0) >= since:
            out.append({"at": row.get("at"), "t": ts(row.get("at")), "waited": int(row["waited"]) if str(row.get("waited") or "").isdigit()
                        else None, "q": "", "a": "", "kind": "sclaude", "rec": None, "rid": ""})
    by_rid = {t["rid"]: t for t in threads if t["rid"]}
    for h in out:
        t = by_rid.get(h["rid"])
        h["path"], h["line"] = (t["path"], t["line"]) if t else ("", 0)
        h["r"] = round_at(rounds, h["t"])
    # A thread a person opened is their hand too.
    for t in threads:
        if t["by"] == "person":
            out.append({"at": t["at"], "t": t["t"], "waited": None, "q": t["title"], "a": "", "kind": "thread",
                        "rec": None, "rid": t["rid"], "path": t["path"], "line": t["line"], "r": t["r"]})
    out.sort(key=lambda h: h["t"] or 0)
    return out


def costs_of(tree, rounds):
    """{round: dollars}, as the review's report prices it: each pass by its
    session (stopped ones too), and each launch of a fix session on the
    last round begun before the launch began (review_report.py, from the
    feature's state)."""
    out = {}
    if not rounds:
        return out
    for i, r in enumerate(rounds):
        for sid in r["sessions"] + r["spent"]:
            cost = review_report.pass_cost(tree, sid)
            if cost is not None:
                out[i] = out.get(i, 0.0) + cost
    groups = [{"at": datetime.datetime.fromtimestamp(r["t"], datetime.timezone.utc)} for r in rounds]
    people = review_report.sessions(tree, groups[0]["at"])
    who = review_report.fixers(groups, people)
    for k, person in enumerate(people):
        mine = [i for i, m in enumerate(who) if k in m]
        for i, cost in enumerate(review_report.fixes_per_round(person, groups, mine)):
            if cost is not None:
                out[i] = out.get(i, 0.0) + cost
    return out


# --- the whole -----------------------------------------------------------------

def build(tree):
    state = read_json(os.path.join(tree, STATE), {})
    pr = str(state.get("pr") or "")
    repo = repo_of(tree, state)
    rounds = rounds_of(tree, pr)
    if not rounds:
        return {"pr": pr, "rounds": [], "files": [], "hunks": [], "threads": [], "hands": []}
    head = (git(tree, "rev-parse", "HEAD") or "").strip()
    ends = [r["head"] for r in rounds[1:]] + [head or rounds[-1]["head"]]
    nodes = thread_nodes(tree, pr, repo)
    threads = threads_of(tree, nodes, rounds)
    fixes, carried = [], []
    for i, r in enumerate(rounds):
        r["end"] = ends[i]
        if ends[i] != r["head"]:
            # A merge between two rounds (main brought in, the parts joined)
            # is no fix: only the files the branch's own commits changed. The
            # rest still move the file's lines, so the axis takes them
            # (`carried`). Main's lines in a file a fix touched too count as
            # that round's: telling them apart needs a blame of each.
            own = set((git(tree, "log", "--first-parent", "--no-merges", "--name-only", "--format=",
                           r["head"] + ".." + ends[i]) or "").split("\n")) - {""}
            asked = asked_lines(tree, r["head"], ends[i])
            got = hunks(tree, r["head"], ends[i], texts=True)
            # Main's changes brought in by a merge are no side of a move.
            moves([h for h in got if h["path"] in own])
            for h in got:
                h.pop("_plus", None)
                h.pop("_minus", None)
            for h in got:
                h["r"] = i
                # Lines the person asked for are the development's, wherever
                # in the review they came: the page draws them as such.
                theirs = asked.get(h["path"])
                if theirs and h["add"] and sum(1 for k in range(h["x"], h["x"] + h["n"]) if k in theirs) * 2 > h["add"]:
                    h["asked"] = True
                (fixes if h["path"] in own else carried).append(h)
    # The files: what the pull request changed by its first round, and every
    # file a fix or a thread touched since.
    base = ""
    for main in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        base = (git(tree, "merge-base", main, rounds[0]["head"]) or "").strip()
        if base:
            break
    paths = []
    # The development before the review: the code the pull request wrote by
    # its first round, per file, and when its first commit was made.
    dev = {"t": None, "files": {}}
    if base:
        paths = [p for p in (git(tree, "diff", "--name-only", "--no-renames", base, rounds[0]["head"]) or "").splitlines() if p]
        for h in hunks(tree, base, rounds[0]["head"]):
            f = dev["files"].setdefault(h["path"], {"add": 0, "del": 0, "code": 0, "comment": 0, "regions": []})
            f["add"] += h["add"]
            f["del"] += h["del"]
            f["code"] += h["code"]
            f["comment"] += h["comment"]
            if h["add"]:
                f["regions"].append([h["x"], h["n"]])
        first = (git(tree, "log", "--reverse", "--format=%ct", base + ".." + rounds[0]["head"]) or "").split()
        dev["t"] = int(first[0]) if first else None
    for p in [h["path"] for h in fixes] + [t["path"] for t in threads]:
        if p and p not in paths:
            paths.append(p)
    paths.sort()
    for i, r in enumerate(rounds):
        r["lines"] = line_counts(tree, r["head"], paths)
        # A file not there at the round's head — not yet written, or removed
        # by the fixes before it: an empty file has no lines either, but is there.
        r["absent"] = absent_files(tree, r["head"], paths)
    final = line_counts(tree, ends[-1], paths)
    absent_end = absent_files(tree, ends[-1], paths)
    for r in rounds:
        sessions = r["sessions"]
        # A stopped pass said nothing that counts: it read nothing either.
        how = {} if r["stopped"] else seen_files(tree, sessions, paths, r["lines"]) if r.get("source") != "github" else None
        r["seen"] = None if how is None else sorted(how)
        r["how"] = how
    for k, h in enumerate(fixes):
        h["i"] = k
    axis = project(paths, rounds, fixes + carried, threads, dev, final)
    # Code moved from another file grows from the fixes that wrote it there:
    # the blame of the removal it came from.
    for h in fixes:
        srcs = h.get("_moved_from") or []
        if srcs and not h.get("asked"):
            h["_blame"] = sorted(set(h.get("_blame", [])) | {b for s in srcs for b in s.get("_blame", [])})
    # Each fix's answer: the nearest thread of its round in its file, within
    # NEAR lines; failing that, the thread a subagent of its round was given
    # when it edited the fix's file — one of the brief's threads in that file,
    # or the brief's one thread in a file of none (a test, a caller). With
    # more threads in the brief the fix keeps the subagent (`agent`) when it
    # named at most two, which the page joins by: one subagent's fix of one
    # or two findings.
    agents = agents_of(tree, rounds, threads)
    for h in fixes:
        h["thread"], h["outcome"], h["via"], h["agent"] = "", "side", "", ""
        best = None
        for t in threads:
            if t["r"] != h["r"] or t["path"] != h["path"]:
                continue
            # A thread's line is in the round's head, as is a fix's ox.
            d = abs((t["line"] or 0) - h["ox"])
            if d <= NEAR + h["on"] and (best is None or d < best[0]):
                best = (d, t)
        mine = [a for a in agents if a["r"] == h["r"] and h["path"] in a["files"]]
        if mine:
            def near(a):
                same = [abs((t["line"] or 0) - h["ox"]) for t in a["threads"] if t["path"] == h["path"]]
                return min(same) if same else 10 ** 9
            a = min(mine, key=near)
            if len(a["threads"]) <= 2:
                h["agent"] = a["id"]
            if not best:
                here = [t for t in a["threads"] if t["path"] == h["path"]]
                if here or len(a["threads"]) == 1:
                    t = min(here or a["threads"], key=lambda t: abs((t["line"] or 0) - h["ox"]))
                    h["outcome"], h["thread"], h["via"] = t["outcome"], t["rid"], "agent"
                    continue
        if best:
            h["outcome"], h["thread"], h["via"] = best[1]["outcome"], best[1]["rid"], "near"
    replied(tree, rounds, ends, threads, fixes)
    # Moved code is no answer to a thread found near it: only a reply or a
    # subagent's brief ties it to one. Each side names the other's files.
    for h in fixes + carried:
        to, frm = h.pop("_moved_to", None), h.pop("_moved_from", None)
        out = h.pop("_moved_out", False)
        if frm:
            h["movedFrom"] = sorted({s["path"] for s in frm})
        if to and out:
            h["movedTo"] = sorted({s["path"] for s in to})
        share = h.pop("_moved_share", 0)
        # A thread found near it gives way only to a hunk that is almost all
        # moved code: half moved, the other half may be the fix of that thread.
        if (frm or (to and out)) and not h.get("asked") and (h.get("via") == "" or (h.get("via") == "near" and share >= MOVE_ALL)):
            h["outcome"], h["thread"], h["via"] = "moved", "", "move"
    lineage(rounds, fixes, threads)
    for h in fixes:
        h.pop("i", None)
    for t in threads:
        t.pop("_replies", None)
    costs = costs_of(tree, rounds)
    for i, r in enumerate(rounds):
        r["cost"] = round(costs[i], 2) if i in costs else None
        r.pop("sessions", None)
        r.pop("spent", None)
    hands = hands_of(tree, rounds, threads)
    # The review blocks the pull request is read in, when it is: each
    # changed file is in one, and the page groups the columns by them.
    cut = read_json(os.path.join(tree, FEATURE_BLOCKS), {})
    def shown(bs):
        return [{"n": i + 1, "id": str(b.get("id") or i + 1), "title": b.get("title") or "",
                 "files": b.get("files") or [], "criteria": b.get("criteria") or []}
                for i, b in enumerate(bs or []) if isinstance(b, dict)]
    blocks = shown(cut.get("blocks"))
    # What is left of the development's code in every block's file, now.
    survive = alive(tree, base, rounds[0]["head"], ends[-1], sorted({f for b in blocks for f in b["files"]}),
                    {h["path"] for h in fixes if h.get("movedFrom")}) if blocks else {}
    # Each block's size now, as the split measures it (review_blocks.py
    # outgrown): its files' changed lines, generated ones left out, against
    # reviewBlocks.size.
    try:
        now_changed = review_blocks.changed(tree, cut["base"], head or "HEAD") if blocks and cut.get("base") else {}
    except subprocess.TimeoutExpired:
        now_changed = {}
    if now_changed:
        for b in blocks:
            gen = {f: review_blocks.generated(tree, f) for f in b["files"] if f in now_changed}
            b["lines"] = sum(now_changed[f] for f, g in gen.items() if not g)
            b["generated"] = sum(now_changed[f] for f, g in gen.items() if g)
    size = (process_config.config_of(tree).get("reviewBlocks") or {}).get("size")
    size = "" if size is None else str(size)
    # The cut as it stood before each split (review_blocks.py split): what
    # the rounds before it read under, for the page to show as it played.
    earlier = []
    for e in cut.get("earlier") or []:
        try:
            until = datetime.datetime.fromisoformat(e["until"]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        earlier.append({"until": until, "split": str(e.get("split") or ""), "blocks": shown(e.get("blocks"))})
    # Where the review stands: the block read now (none once the seams are
    # past), and whether step 4 is over — no round comes after the last,
    # whose fixing is then over too.
    places = cycle_steps.places()
    step = state.get("step") or ""
    closed = step == "done" or step in places and places.index(step) > places.index("review")
    now = (state.get("blocks") or {}).get("current")
    return {"pr": pr, "repo": repo, "head": head, "final": final, "absentEnd": absent_end, "alive": survive, "dev": dev, "blocks": blocks, "earlier": earlier,
            "blockNow": now if isinstance(now, int) and blocks and not closed else None, "closed": closed,
            "blockSize": int(size) if size.isdigit() else review_blocks.SIZE,
            "files": [dict({"path": p, "lines": rounds[0]["lines"].get(p, 0)},
                           **({"axis": axis[p]} if p in axis else {})) for p in paths],
            "rounds": rounds, "hunks": fixes, "threads": threads, "hands": hands}


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("usage: review_map.py <tree>\n")
        return 2
    sys.stdout.write(json.dumps(build(os.path.abspath(argv[0])), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
