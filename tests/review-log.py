#!/usr/bin/env python3
#
# A review run on GitHub read back from its job's log (review_log.py):
#
#   * the stream's messages are found in the log as the action prints them —
#     a time on every line, each message a JSON object from "{" to "}" —
#     and a log without the stream's result is not taken (not whole yet);
#   * fetch keeps them as a transcript, and says the run's own answer;
#     GitHub's 404 on a run long ended is "gone", not "try later";
#   * the journal's GitHub rows get their base, `log`, `new`, `resolved` and
#     `read` (github_logs), once;
#   * what the run did not open of the files its delta changed is told as
#     a pass here is (github_unread), and a follow-up pass on that head is
#     known (followed);
#   * the review map's round reads the run's opened files from that log.
#
# Run it with: python3 tests/review-log.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import local_review  # noqa: E402
import review_log  # noqa: E402
import review_map  # noqa: E402

failures = []
RUNNER = "/home/runner/work/app/app"


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def printed(records, stamp="2026-11-21T07:11:52.8904532Z"):
    """A job's log as the action writes it: noise, then each record pretty
    printed, a time before every line."""
    lines = ["﻿%s Current runner version: '2.338.2'" % stamp, "%s ##[group]Run action" % stamp,
             "%s {not json at all" % stamp]
    for r in records:
        for line in json.dumps(r, indent=2).splitlines():
            lines.append("%s %s" % (stamp, line))
    lines.append("%s ##[endgroup]" % stamp)
    return "\n".join(lines) + "\n"


def stream(read, diffed=(), result=True, given=None):
    recs = [{"type": "system", "subtype": "init", "cwd": RUNNER, "session_id": "s"}]
    if given is not None:
        # The reference workflow's open-findings.json, read first.
        recs.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "content": json.dumps(dict(given, findings=[]), indent=2)}]}})
    for p in read:
        recs.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "%s/%s" % (RUNNER, p)}}]}})
    if diffed:
        recs.append({"type": "user", "parent_tool_use_id": "toolu_1", "message": {"content": [
            {"type": "tool_result", "content": "\n".join("diff --git a/%s b/%s" % (p, p) for p in diffed)}]}})
    if result:
        recs.append({"type": "result", "subtype": "success", "structured_output": {
            "resolved": [{"thread_id": "x", "commit": "c", "reason": "r"}], "found": 2,
            "unthreaded": 0, "full_rerun": False, "complete": True}})
    return recs


# --- the log's messages ---------------------------------------------------------
recs = review_log.records(printed(stream(["a.py"], ["b.py"])))
check("records-kinds", [r["type"] for r in recs], ["system", "assistant", "user", "result"])
check("records-nested-kept", recs[2]["message"]["content"][0]["type"], "tool_result")
check("summary", review_log.summary(recs),
      {"root": RUNNER, "found": 2, "resolved": 1, "unthreaded": 0, "full_rerun": False, "complete": True})
check("base-from-the-log", review_log.summary(review_log.records(printed(stream(
    ["a.py"], given={"head_sha": "a" * 40, "base_sha": "b" * 40})))).get("base"), "b" * 40)
check("whole-from-the-log", review_log.summary(review_log.records(printed(stream(
    ["a.py"], given={"head_sha": "a" * 40, "base_sha": None})))), {"base": None, "root": RUNNER, "found": 2,
                                                              "resolved": 1, "unthreaded": 0, "full_rerun": False,
                                                              "complete": True})
# Read gives the file a number before every line.
numbered = "\n".join("%6d\t%s" % (i + 1, line) for i, line in enumerate(
    json.dumps({"head_sha": "a" * 40, "base_sha": "c" * 40, "findings": []}, indent=2).splitlines()))
recs = review_log.records(printed(stream(["a.py"])))
recs.insert(1, {"type": "user", "message": {"content": [{"type": "tool_result", "content": numbered}]}})
check("base-from-a-read", review_log.summary(recs).get("base"), "c" * 40)
check("no-result-not-whole", review_log.summary(review_log.records(printed(stream(["a.py"], result=False)))), None)


# --- a tree, a journal and a stub gh ------------------------------------------------
def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


tmp = tempfile.mkdtemp(prefix="sclaude-review-log-")
try:
    tree = os.path.join(tmp, "tree")
    os.makedirs(tree)
    sh(tree, "git", "init", "-q", "-b", "feat/x")
    sh(tree, "git", "config", "user.email", "t@example.com")
    sh(tree, "git", "config", "user.name", "t")
    sh(tree, "git", "remote", "add", "origin", "https://github.com/acme/app.git")
    for name in ("a.py", "b.py", "c.py"):
        with open(os.path.join(tree, name), "w") as fh:
            fh.write("x = 1\n")
    sh(tree, "git", "add", ".")
    sh(tree, "git", "commit", "-qm", "first")
    first = sh(tree, "git", "rev-parse", "HEAD")
    for name in ("a.py", "b.py"):
        with open(os.path.join(tree, name), "a") as fh:
            fh.write("y = 2\n")
    sh(tree, "git", "commit", "-qam", "fix")
    second = sh(tree, "git", "rev-parse", "HEAD")

    logs = os.path.join(tmp, "logs")
    os.makedirs(logs)
    # Run 11 read the whole PR; run 12, the delta, opened a.py alone; run 13's
    # log is not whole; run 14's GitHub no longer has.
    with open(os.path.join(logs, "11"), "w") as fh:
        fh.write(printed(stream(["a.py", "b.py", "c.py"])))
    with open(os.path.join(logs, "12"), "w") as fh:
        fh.write(printed(stream(["a.py"])))
    with open(os.path.join(logs, "13"), "w") as fh:
        fh.write(printed(stream(["a.py"], result=False)))
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    with open(os.path.join(bin_dir, "gh"), "w") as fh:
        fh.write("""#!/usr/bin/env python3
import json, os, re, sys
logs = %r
if os.environ.get("OLD_GH") and "--allow-escape-sequences" in sys.argv:
    sys.stderr.write("unknown flag: --allow-escape-sequences\\n"); sys.exit(1)
url = sys.argv[-1]
m = re.search(r"actions/runs/(\\d+)/attempts/\\d+/jobs$", url)
if m:
    run = m.group(1)
    if run == "14":
        sys.stderr.write("gh: Not Found (HTTP 404)\\n"); sys.exit(1)
    print(json.dumps({"jobs": [
        {"id": 1, "status": "completed", "conclusion": "success", "completed_at": "2026-11-21T07:00:00Z"},
        {"id": int(run) * 10, "status": "completed", "conclusion": "success", "completed_at": "2026-11-21T07:00:00Z"}]}))
    sys.exit(0)
m = re.search(r"actions/jobs/(\\d+)/logs$", url)
if m:
    job = int(m.group(1))
    if job == 1:
        print("2026-11-21T07:00:00Z nothing of the stream here"); sys.exit(0)
    sys.stdout.write(open(os.path.join(logs, str(job // 10))).read()); sys.exit(0)
sys.exit(1)
""" % logs)
    os.chmod(os.path.join(bin_dir, "gh"), 0o755)
    os.environ["PATH"] = bin_dir + ":" + os.environ["PATH"]

    said, code = review_log.fetch(tree, 12, 1)
    check("fetch-kept", code, 0)
    check("fetch-log-path", said and said["log"], ".sclaude/local/feature/review-logs/12-1.jsonl")
    check("fetch-transcript-lines", sum(1 for _ in open(os.path.join(tree, said["log"]))) if said else 0, 3)
    check("fetch-not-whole", review_log.fetch(tree, 13, 1)[1], 1)
    os.environ["OLD_GH"] = "1"
    check("fetch-old-gh", review_log.fetch(tree, 12, 1)[1], 0)
    del os.environ["OLD_GH"]
    check("fetch-gone", review_log.fetch(tree, 14, 1)[1], 3)

    journal = os.path.join(tree, local_review.JOURNAL)
    rows = [{"at": "2026-11-21T06:00:00+00:00", "seconds": 500, "head": first, "source": "github",
             "run": 11, "attempt": 1, "pr": "7"},
            {"at": "2026-11-21T07:00:00+00:00", "seconds": 500, "head": second, "source": "github",
             "run": 12, "attempt": 1, "pr": "7"},
            {"at": "2026-11-21T06:30:00+00:00", "seconds": 500, "head": second, "source": "github",
             "run": 13, "attempt": 1, "pr": "7"},
            {"at": "2026-11-21T06:40:00+00:00", "seconds": 500, "head": second, "source": "github",
             "run": 14, "attempt": 1, "pr": "7"}]
    with open(journal, "w") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    local_review.github_logs(journal)
    check("appended-only", [json.loads(line).get("run") for line in open(journal)][:4], [11, 12, 13, 14])
    got = local_review.rows(journal)
    check("first-run-reads-whole", (got[0].get("base"), got[0].get("read"), got[0].get("new")), (None, "first", 2))
    check("delta-run", (got[1].get("base"), got[1].get("read"), got[1].get("resolved")), (first, "delta", 1))
    check("delta-run-root", got[1].get("root"), RUNNER)
    check("not-whole-asked-again", "log" in got[2], False)
    check("gone-marked", got[3].get("log"), "gone")

    # Run 12 is the newest on the head (13 and 14 came before it).
    unread = local_review.github_unread(tree, journal, second, "7")
    check("unread-of-the-delta", unread and unread[0], ["b.py"])
    check("unread-base-and-run", unread and unread[1:], (first, 12, 1))
    check("whole-run-reads-nothing-more", local_review.github_unread(tree, journal, first, "7"), ([], "", 11, 1))
    check("filled-once", local_review.github_logs(journal) or sum(1 for _ in open(journal)), 7)
    check("not-followed-yet", local_review.followed(journal, second, "7"), False)
    with open(journal, "a") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:50:00+00:00", "seconds": 60, "head": second, "base": first,
                             "run": 12, "attempt": 1, "followup": True, "pr": "7", "new": 0}) + "\n")
    check("followed", local_review.followed(journal, second, "7"), True)

    # A follow-up pass stopped or refused is the run's too (tag, for spent).
    os.environ["SCLAUDE_REVIEW_FOLLOWS"] = "%s 12 1" % first
    local_review.spent(journal, first, second, 30, "sess", "7", "refused")
    del os.environ["SCLAUDE_REVIEW_FOLLOWS"]
    last = json.loads(open(journal).read().splitlines()[-1])
    check("spent-follow-up-is-the-runs", (last.get("run"), last.get("attempt"), last.get("base"), last.get("followup")),
          (12, 1, first, True))

    # The base is by time, not by the order the journal was written in: a
    # GitHub run is appended when the report learns of it.
    with open(os.path.join(logs, "15"), "w") as fh:
        fh.write(printed(stream(["a.py"])))
    late = os.path.join(tmp, "late.jsonl")
    with open(os.path.join(logs, "16"), "w") as fh:
        fh.write(printed(stream(["a.py"], given={"head_sha": second, "base_sha": first})))
    named = os.path.join(tree, ".sclaude/local/feature/named.jsonl")
    with open(named, "w") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:05:00+00:00", "seconds": 60, "head": "d" * 40,
                             "source": "github", "run": 11, "attempt": 1, "pr": "7"}) + "\n")
        fh.write(json.dumps({"at": "2026-11-21T07:10:00+00:00", "seconds": 60, "head": second,
                             "source": "github", "run": 16, "attempt": 1, "pr": "7"}) + "\n")
    local_review.github_logs(named)
    check("base-the-log-names", [r.get("base") for r in local_review.rows(named) if r.get("run") == 16], [first])
    # A log naming the run's own head as its base read nothing new: that is
    # its base, and nothing is to be read after it.
    with open(os.path.join(logs, "17"), "w") as fh:
        fh.write(printed(stream(["a.py"], given={"head_sha": second, "base_sha": second})))
    same = os.path.join(tree, ".sclaude/local/feature/same.jsonl")
    with open(same, "w") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:05:00+00:00", "seconds": 60, "head": first,
                             "source": "github", "run": 11, "attempt": 1, "pr": "7"}) + "\n")
        fh.write(json.dumps({"at": "2026-11-21T07:10:00+00:00", "seconds": 60, "head": second,
                             "source": "github", "run": 17, "attempt": 1, "pr": "7"}) + "\n")
    local_review.github_logs(same)
    check("base-equal-head-kept", [r.get("base") for r in local_review.rows(same) if r.get("run") == 17], [second])
    check("base-equal-head-no-follow-up", (local_review.github_unread(tree, same, second, "7") or [None])[0], [])
    # After a run that left b.py unopened, such a rerun leaves it owed.
    with open(same, "a") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:08:00+00:00", "seconds": 60, "head": second, "base": first,
                             "source": "github", "run": 12, "attempt": 1, "pr": "7", "read": "delta",
                             "log": got[1]["log"], "root": RUNNER, "unthreaded": 0}) + "\n")
    check("rerun-reading-nothing-keeps-the-owed", (local_review.github_unread(tree, same, second, "7") or [None])[0],
          ["b.py"])
    # A run told before `unthreaded` was kept is told again from its kept log.
    retold = os.path.join(tree, ".sclaude/local/feature/retold.jsonl")
    with open(retold, "w") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:10:00+00:00", "seconds": 60, "head": second,
                             "source": "github", "run": 12, "attempt": 1, "pr": "7"}) + "\n")
        fh.write(json.dumps({"told": True, "run": 12, "attempt": 1, "log": got[1]["log"], "root": RUNNER}) + "\n")
    local_review.github_logs(retold)
    check("told-again-from-the-kept-log", [r.get("unthreaded") for r in local_review.rows(retold)], [0])
    late_journal = os.path.join(tree, ".sclaude/local/feature/late.jsonl")
    with open(late_journal, "w") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:05:00+00:00", "seconds": 60, "head": second, "base": first,
                             "pr": "7", "new": 0}) + "\n")
        fh.write(json.dumps({"at": "2026-11-21T07:00:00+00:00", "seconds": 60, "head": first,
                             "source": "github", "run": 11, "attempt": 1, "pr": "7"}) + "\n")
        fh.write(json.dumps({"at": "2026-11-21T07:10:00+00:00", "seconds": 60, "head": "f" * 40,
                             "source": "github", "run": 15, "attempt": 1, "pr": "7"}) + "\n")
    local_review.github_logs(late_journal)
    check("base-by-time", [r.get("base") for r in local_review.rows(late_journal) if r.get("run") == 15], [second])
    del late

    # A branch rewritten since the run's base: nothing can be said.
    sh(tree, "git", "checkout", "-q", "-b", "other", first)
    with open(os.path.join(tree, "c.py"), "a") as fh:
        fh.write("z = 3\n")
    sh(tree, "git", "commit", "-qam", "rewritten")
    rewritten = sh(tree, "git", "rev-parse", "HEAD")
    with open(journal, "a") as fh:
        fh.write(json.dumps({"at": "2026-11-21T08:00:00+00:00", "seconds": 1, "head": rewritten, "base": second,
                             "source": "github", "run": 12, "attempt": 2, "pr": "7", "read": "delta",
                             "log": got[1]["log"], "root": RUNNER}) + "\n")
    check("rewritten-branch-unknown", local_review.github_unread(tree, journal, rewritten, "7"), local_review.UNKNOWN)
    check("no-run-on-head", local_review.github_unread(tree, journal, "e" * 40, "7"), None)
    # A rerun on the head whose log is not here — dated as its run, by the
    # run's creation: the older attempt's log says nothing of it.
    with open(journal, "a") as fh:
        fh.write(json.dumps({"at": "2026-11-21T07:00:00+00:00", "seconds": 1, "head": second,
                             "source": "github", "run": 12, "attempt": 3, "pr": "7"}) + "\n")
    check("newest-run-counts", local_review.github_unread(tree, journal, second, "7"), local_review.UNKNOWN)
    # An older run rerun after a newer one: its attempt began last.
    cross = os.path.join(tree, ".sclaude/local/feature/cross.jsonl")
    with open(cross, "w") as fh:
        for row in ({"at": "2026-11-21T06:30:00+00:00", "began": "2026-11-21T06:30:00+00:00", "head": second,
                     "source": "github", "run": 13, "attempt": 1, "pr": "7", "log": got[1]["log"], "root": RUNNER,
                     "read": "delta", "base": first},
                    {"at": "2026-11-21T07:00:00+00:00", "began": "2026-11-21T07:00:00+00:00", "head": second,
                     "source": "github", "run": 12, "attempt": 1, "pr": "7", "log": got[1]["log"], "root": RUNNER,
                     "read": "delta", "base": first},
                    {"at": "2026-11-21T06:30:00+00:00", "began": "2026-11-21T08:00:00+00:00", "head": second,
                     "source": "github", "run": 13, "attempt": 2, "pr": "7"}):
            fh.write(json.dumps(row) + "\n")
    check("rerun-of-older-run-counts", local_review.github_unread(tree, cross, second, "7"), local_review.UNKNOWN)

    # The map: the delta's round opened a.py by its log.
    seen = review_map.seen_files(tree, [], ["a.py", "b.py"], logs=[(got[1]["log"], RUNNER)])
    check("map-seen-from-log", seen, {"a.py": "whole"})
    check("map-no-log-unknown", review_map.seen_files(tree, [], ["a.py"], logs=[]), None)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)
print("ok")
