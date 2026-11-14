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
#     decline_of), the person's to decide (review-yours, a night's mark among
#     them) or declined as undoing a settled fix (review-reversals);
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
#     (FEATURE_BLOCKS in review_blocks.py), each with its files;
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
                    "resolved": r.get("resolved"), "block": r.get("block"),
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


def hunks(tree, a, b):
    """[{path, x, n, add, del, code, comment}] of `git diff a b`: x and n the
    hunk's first line and length in b."""
    out = git(tree, "diff", "-U0", "--no-color", "--no-ext-diff", "-M", a, b)
    if out is None:
        return []
    found, path, cur = [], None, None
    for line in out.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            continue
        if line.startswith("--- ") or line.startswith("diff --git"):
            continue
        m = HUNK.match(line)
        if m:
            if path is None:
                cur = None
                continue
            cur = {"path": path, "x": int(m.group(3)),
                   "n": int(m.group(4)) if m.group(4) is not None else 1,
                   "ox": int(m.group(1)), "on": int(m.group(2)) if m.group(2) is not None else 1,
                   "add": 0, "del": 0, "code": 0, "comment": 0}
            found.append(cur)
            continue
        if cur is None or not line or line[0] not in "+-":
            continue
        cur["add" if line[0] == "+" else "del"] += 1
        if line[1:].strip():
            cur["comment" if comment_line(path, line[1:]) else "code"] += 1
    return found


def project(paths, rounds, fixes, threads, dev, final):
    """Each file's lines on one axis for the whole review: every line that
    was ever in it keeps a place — a line deleted keeps its place, the lines
    a fix wrote stand right after the ones it replaced — so a place is the
    same place in every round, and an icicle grows from the lines it
    changed. Sets p0/p1 on each fix (its place: the lines it removed and the
    lines it wrote), p on each thread, `proj` on each file of `dev` (its
    regions) and returns {path: length of its axis}. A file whose fixes do
    not add up to its next version (a rename, a binary) gets no axis, and
    the page places it by line numbers as before."""
    lengths = {}
    for f in paths:
        n0 = rounds[0]["lines"].get(f, 0)
        cur, axis, nxt = list(range(n0)), list(range(n0)), n0
        snaps, owned, ok = [], [], True
        for i, r in enumerate(rounds):
            snaps.append(list(cur))
            hs = sorted((h for h in fixes if h["r"] == i and h["path"] == f), key=lambda h: h["ox"])
            plans = []
            for h in hs:
                gone = cur[h["ox"] - 1:h["ox"] - 1 + h["on"]] if h["on"] else []
                anchor = gone[-1] if gone else (cur[h["ox"] - 1] if 1 <= h["ox"] <= len(cur) else None)
                new = list(range(nxt, nxt + h["n"] if h["add"] else nxt))
                nxt += len(new)
                plans.append((h, gone, anchor, new))
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
    """{link: text} of a file of `link<TAB>text` lines."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                link, _, text = line.rstrip("\n").partition("\t")
                if link.strip():
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
            return max(1, h["x"])
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
        if url in reversed_:
            outcome = "reversal"
        elif url in yours:
            outcome = "night" if pr_context.NIGHT_MARK in (yours[url] or "") else "yours"
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
    round's range is no fix of the review."""
    commits = {}
    def round_of(sha):
        if sha not in commits:
            full = (git(tree, "rev-parse", "--verify", "-q", sha + "^{commit}") or "").strip()
            commits[sha] = None
            if full:
                for i, r in enumerate(rounds):
                    if r["head"] != ends[i] \
                            and git(tree, "merge-base", "--is-ancestor", r["head"], full) is not None \
                            and git(tree, "merge-base", "--is-ancestor", full, ends[i]) is not None \
                            and full != r["head"]:
                        names = [n for n in (git(tree, "show", "--name-only", "--format=", full) or "").splitlines() if n]
                        commits[sha] = (i, names)
                        break
        return commits[sha]
    for t in threads:
        text = "\n".join(t.get("_replies") or [])
        for sha in SHA.findall(text):
            found = round_of(sha)
            if not found:
                continue
            r, names = found
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
            if not best:
                continue
            t["fixedIn"] = {"r": r, "files": best}
            for h in fixes:
                if h["r"] == r and h["path"] in best and not h["thread"]:
                    h["thread"], h["outcome"], h["via"] = t["rid"], t["outcome"], "reply"
            break


# A diff header at a line's start, or after the line number a Read of a
# saved diff puts before it.
DIFF_HEADER = re.compile(r"^(?:\s*\d+\t)?diff --git a/(\S+)", re.M)


def named(path, text):
    """Whether text names path itself, not a longer path ending in it
    (lib/x.js inside src/lib/x.js)."""
    return re.search(r"(?<![\w./-])" + re.escape(path) + r"(?![\w/-])", text) is not None


def seen_files(tree, sessions, paths):
    """The files of the pull request a round's passes opened: read (Read,
    Grep), named in a command (git diff -- it, cat, sed), or shown as a diff
    header in a command's output — in the passes' transcripts and their
    subagents' (a saved long output counts once a Read shows it). None when
    no pass left a transcript here (a GitHub run): what
    it read is not known. A pass that found nothing in a file it never
    opened says nothing about it."""
    folder = os.path.join(claude_usage.ROOT, claude_usage.project_name(tree))
    found, any_read = set(), False
    wanted = set(paths)
    root = tree.rstrip("/") + "/"
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
                            text = json.dumps(b.get("input") or {}, ensure_ascii=False).replace(root, "")
                            found.update(p for p in wanted if p in text and named(p, text))
                        elif b.get("type") == "tool_result":
                            c = b.get("content")
                            c = c if isinstance(c, str) else " ".join(
                                x.get("text") or "" for x in c or [] if isinstance(x, dict))
                            found.update(p for p in DIFF_HEADER.findall(c) if p in wanted)
    return sorted(found) if any_read else None


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
            for h in hunks(tree, r["head"], ends[i]):
                h["r"] = i
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
            f = dev["files"].setdefault(h["path"], {"add": 0, "code": 0, "comment": 0, "regions": []})
            f["add"] += h["add"]
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
    final = line_counts(tree, ends[-1], paths)
    for r in rounds:
        sessions = r["sessions"]
        # A stopped pass said nothing that counts: it read nothing either.
        r["seen"] = [] if r["stopped"] else seen_files(tree, sessions, paths) if r.get("source") != "github" else None
    axis = project(paths, rounds, fixes + carried, threads, dev, final)
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
    blocks = [{"n": i + 1, "title": b.get("title") or "", "files": b.get("files") or []}
              for i, b in enumerate(cut.get("blocks") or []) if isinstance(b, dict)]
    # Where the review stands: the block read now (none once the seams are
    # past), and whether step 4 is over — no round comes after the last,
    # whose fixing is then over too.
    places = cycle_steps.places()
    step = state.get("step") or ""
    closed = step == "done" or step in places and places.index(step) > places.index("review")
    now = (state.get("blocks") or {}).get("current")
    return {"pr": pr, "repo": repo, "head": head, "final": final, "dev": dev, "blocks": blocks,
            "blockNow": now if isinstance(now, int) and blocks and not closed else None, "closed": closed,
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
