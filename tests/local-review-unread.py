#!/usr/bin/env python3
"""What a pass over the commits since the last review left unopened
(local_review.py unread), and the run marked owing its follow-up (owed).

A pass reading a range picks what it opens; a fix's change to a file it
passed over was read by no pass after it. The files the branch's own
commits changed, still there at the head, less those any of the passes'
conversations opened — read from their transcripts as the review map reads
them — are read by one more short pass, the run marked as a capped one is
until it has."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "sclaude", "lib", "review", "local_review.py")
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t"] + list(args),
                          capture_output=True, text=True, check=True).stdout.strip()


def run(home, *args):
    env = dict(os.environ, HOME=home)
    out = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, env=env, timeout=60)
    return out.returncode, out.stdout


with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home")
    tree = os.path.join(tmp, "tree")
    os.makedirs(tree)
    git(tree, "init", "-q", "-b", "main")
    for name in ("a.ts", "b.ts", "c.ts", "gone.ts"):
        with open(os.path.join(tree, name), "w") as fh:
            fh.write("one\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "base")
    base = git(tree, "rev-parse", "HEAD")
    for name in ("a.ts", "b.ts", "c.ts"):
        with open(os.path.join(tree, name), "a") as fh:
            fh.write("two\n")
    os.remove(os.path.join(tree, "gone.ts"))
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "a fix")
    head = git(tree, "rev-parse", "HEAD")

    folder = os.path.join(home, ".claude", "projects", __import__("re").sub(r"[^A-Za-z0-9]", "-", tree))
    os.makedirs(folder)

    def transcript(sid, *entries):
        with open(os.path.join(folder, sid + ".jsonl"), "w") as fh:
            for e in entries:
                fh.write(json.dumps({"message": {"content": [e]}}) + "\n")

    # The first pass showed a.ts's diff; the second read b.ts.
    transcript("s1", {"type": "tool_use", "name": "Bash", "input": {"command": "git diff %s..%s -- a.ts" % (base, head)}},
               {"type": "tool_result", "content": "diff --git a/a.ts b/a.ts\n+two\n"})
    transcript("s2", {"type": "tool_use", "name": "Read", "input": {"file_path": os.path.join(tree, "b.ts")}})
    rc, out = run(home, "unread", tree, base, head, "s1,s2")
    check("unread: the file no pass opened, not one the commits removed", (rc, out.split()), (0, ["c.ts"]))
    rc, out = run(home, "unread", tree, base, head, "s1")
    check("unread: what each pass opened counts", out.split(), ["b.ts", "c.ts"])
    rc, out = run(home, "unread", tree, base, head, "nobody")
    check("unread: no transcript here, nothing claimed", (rc, out), (0, ""))
    rc, out = run(home, "unread", tree, head, head, "s1")
    check("unread: an empty range, nothing", out, "")

    journal = os.path.join(tmp, "review-rounds.jsonl")
    with open(journal, "w") as fh:
        fh.write(json.dumps({"at": "2026-01-01T10:00:00+00:00", "head": head, "base": base, "more": False}) + "\n")
        fh.write(json.dumps({"at": "2026-01-01T10:05:00+00:00", "head": head, "base": base, "spent": True}) + "\n")
    rc, _ = run(home, "owed", journal)
    with open(journal) as fh:
        rows = [json.loads(line) for line in fh]
    check("owed: the last run, not a spent pass, owes its follow-up",
          (rc, rows[0]["more"], "more" in rows[1]), (0, True, False))
    rc, out = run(home, "since", journal, head)
    check("owed: the next call reads the same range again until it is read", out.strip(), base)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
print("local-review-unread: %s" % ("ok" if not failures else "%d failed" % len(failures)))
sys.exit(1 if failures else 0)
