#!/usr/bin/env python3
"""What a review run on GitHub did, read back from its job's log.

A review on this machine leaves its conversation here, and the review's map
reads from it which files a pass opened (seen_files in review_map.py), and
the journal keeps how many findings it posted. A run in the project's
workflow leaves nothing here, so its round showed no reads, no count, and
was taken as having read every file. Its conversation is in the job's log
all the same: the workflow runs the action with `show_full_output: true`,
which prints every message of the stream, the subagents' among them, each
as a JSON object over many lines (docs/setup.md, "What sclaude reads from
your review workflow").

    review_log.py fetch <tree> <run> <attempt> [<tries>]

finds the run's job that holds the stream, keeps its messages one per line
in LOG_DIR/<run>-<attempt>.jsonl (the shape of a Claude Code transcript,
which seen_files reads), and prints one JSON object: the checkout the run
read from (`root`, to take paths relative), where its delta began (`base`,
when the review read the reference workflow's open-findings.json: null for
the whole pull request) and the review's own answer from its last `result`
— `found`, `resolved`, `unthreaded`, `full_rerun`, `complete`. Exit 0
with it; 1 when the log is not there yet, or not whole (no `result`: a job
still writing, or a log GitHub has not finished storing) — try later; 3
when GitHub no longer has it (logs are kept 90 days) or the run printed no
stream. A log is taken only whole: half a conversation would read as files
never opened.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time

LOG_DIR = ".sclaude/local/feature/review-logs"
# Kinds of record a transcript has, and the result the stream ends with.
KINDS = ("system", "assistant", "user", "result")
STAMP = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
# A run that ended longer ago than this and whose log GitHub cannot give
# will not give it later.
GONE_AFTER = datetime.timedelta(days=1)
PAUSE = 10
HEAD_SHA = re.compile(r'"head_sha"\s*:\s*"[0-9a-f]{7,40}"')
BASE_SHA = re.compile(r'"base_sha"\s*:\s*(?:null|"([0-9a-f]{7,40})")')


def repo_of(tree):
    try:
        url = subprocess.run(["git", "-C", tree, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def gh(args, tree):
    """(stdout, missing): missing when GitHub answered 404 or 410. A log
    carries the terminal's colours, which gh refuses to print unless told
    to; a gh older than the flag prints them without it."""
    try:
        done = subprocess.run(["gh", "api", "--allow-escape-sequences"] + args, cwd=tree,
                              capture_output=True, text=True, timeout=120)
        if done.returncode != 0 and "unknown flag" in done.stderr:
            done = subprocess.run(["gh", "api"] + args, cwd=tree,
                                  capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None, False
    if done.returncode != 0:
        said = done.stdout + done.stderr
        return None, "HTTP 404" in said or "HTTP 410" in said
    return done.stdout, False


def records(text):
    """The stream's messages in a job's log: each line opens with its time,
    and a message is printed as JSON from a line "{" to a line "}"."""
    out, buf = [], None
    for raw in text.splitlines():
        line = STAMP.sub("", raw, count=1)
        if buf is None:
            if line == "{":
                buf = [line]
            continue
        buf.append(line)
        if line == "}":
            try:
                rec = json.loads("\n".join(buf))
            except ValueError:
                rec = None
            buf = None
            if isinstance(rec, dict) and rec.get("type") in KINDS:
                out.append(rec)
    return out


def summary(recs):
    """What the stream says of itself, or None when it has no result: the
    checkout's path from its start, the answer from its end."""
    results = [r for r in recs if r.get("type") == "result"]
    if not results:
        return None
    root = next((r.get("cwd") for r in recs
                 if r.get("type") == "system" and r.get("subtype") == "init" and r.get("cwd")), "")
    said = results[-1].get("structured_output")
    said = said if isinstance(said, dict) else {}
    found = said.get("found")
    resolved = said.get("resolved")
    unthreaded = said.get("unthreaded")
    out = {}
    # Where the run's delta began: the reference workflow hands the review
    # `.claude-review/open-findings.json` with `head_sha` and `base_sha` (null
    # for the whole pull request), and the review reads it first. A head it
    # did not mark reviewed is no base for the next run, so the journal's
    # previous head may not be this.
    # Matched, not parsed: the file read with Read comes back with a number
    # before every line, cat with none.
    for r in recs:
        if r.get("type") != "user":
            continue
        for b in (r.get("message") or {}).get("content") or []:
            c = b.get("content") if isinstance(b, dict) and b.get("type") == "tool_result" else None
            if isinstance(c, list):
                c = " ".join(x.get("text") or "" for x in c if isinstance(x, dict))
            base = BASE_SHA.search(c) if isinstance(c, str) and HEAD_SHA.search(c) else None
            if base:
                out["base"] = base.group(1)
                break
        if "base" in out:
            break
    return dict(out, **{"root": root,
            "found": found if isinstance(found, int) else None,
            "resolved": len(resolved) if isinstance(resolved, list) else None,
            "unthreaded": unthreaded if isinstance(unthreaded, int) else None,
            "full_rerun": said.get("full_rerun") is True,
            "complete": said.get("complete") is True})


def ended(job):
    try:
        return datetime.datetime.fromisoformat((job.get("completed_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_once(tree, repo, run, attempt):
    """(summary, code): code 0 kept, 1 not yet, 3 never."""
    out, missing = gh(["repos/%s/actions/runs/%s/attempts/%s/jobs" % (repo, run, attempt)], tree)
    if out is None:
        return None, 3 if missing else 1
    try:
        jobs = json.loads(out).get("jobs") or []
    except (ValueError, AttributeError):
        return None, 1
    later = False
    now = datetime.datetime.now(datetime.timezone.utc)
    for job in jobs:
        if job.get("status") != "completed" or job.get("conclusion") == "skipped":
            later = later or job.get("status") != "completed"
            continue
        text, missing = gh(["repos/%s/actions/jobs/%s/logs" % (repo, job.get("id"))], tree)
        if text is None:
            t = ended(job)
            later = later or not (missing and t and now - t > GONE_AFTER)
            continue
        recs = records(text)
        if not any(r.get("type") == "system" for r in recs):
            continue
        said = summary(recs)
        if said is None:
            # The stream is here and has no end yet: not whole.
            return None, 1
        path = os.path.join(tree, LOG_DIR, "%s-%s.jsonl" % (run, attempt))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(path + ".part", path)
        said["log"] = os.path.relpath(path, tree)
        return said, 0
    return None, 1 if later else 3


def fetch(tree, run, attempt, tries=1, repo=None):
    repo = repo or repo_of(tree)
    if not repo:
        return None, 1
    for k in range(max(1, tries)):
        said, code = fetch_once(tree, repo, run, attempt)
        if code != 1 or k + 1 >= tries:
            return said, code
        time.sleep(PAUSE)
    return None, 1


def main(argv):
    if len(argv) not in (4, 5) or argv[0] != "fetch":
        print(__doc__, file=sys.stderr)
        return 2
    said, code = fetch(argv[1], argv[2], argv[3], int(argv[4]) if len(argv) > 4 else 1)
    if said is not None:
        print(json.dumps(said))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
