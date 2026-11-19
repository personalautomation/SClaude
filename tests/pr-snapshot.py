#!/usr/bin/env python3
#
# The pull request's snapshot for a review session, however many threads the
# pull request has. It goes into the prompt, which goes to claude as one
# argument (128 KiB at most) and is read at every turn; once its resolved
# threads alone, repeated on the files still open, came to 48 KB and the
# prompt to more than the limit, and the session never started.
#
# Guarded here, with GitHub stubbed:
#
#   * few threads: everything inline, as before, and files written beside;
#   * many open threads: an index inline, each thread whole in threads.md
#     under its number; more still: a count per file;
#   * many resolved threads on the open files: a count per file and the lines
#     of its section in resolved.md, which are where the section is;
#   * outside a feature's tree: everything inline, no files;
#   * the local review's prompt: settled findings past their budget go to
#     settled.md by file, and the prompt says where.
#
# Run it with: python3 tests/pr-snapshot.py
import io
import os
import shutil
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import pr_context  # noqa: E402
import local_review  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def thread(k, path, size=200):
    return {"path": path, "line": k, "outdated": False, "created": "",
            "url": "https://github.com/o/r/pull/1#discussion_r%d" % k,
            "comments": [{"author": "bot", "body": "**finding %d**\n\n%s" % (k, "x" * size)},
                         {"author": "me", "body": "a reply to %d" % k}]}


def resolved(k, path):
    return {"path": path, "line": k, "finding": "**old finding %d** %s" % (k, "y" * 300),
            "resolution": "fixed in abc"}


STATE = {}
pr_context.pr_view = lambda cwd, pr, fields: {"statusCheckRollup": [], "comments": [],
                                              "headRefOid": "abc"}
pr_context.open_threads = lambda cwd, pr, repo, nodes=None: (STATE["open"], STATE["resolved"])
pr_context.yours = lambda cwd: {}
pr_context.night = lambda cwd: {}
pr_context.unposted_findings = lambda *a: None


def snapshot(tree, open_, resolved_):
    STATE["open"], STATE["resolved"] = open_, resolved_
    return pr_context.render(tree, 1, "o/r")


def read(tree, name):
    with open(os.path.join(tree, pr_context.PR_DIR, name), encoding="utf-8") as fh:
        return fh.read()


tmp = tempfile.mkdtemp()
try:
    tree = os.path.join(tmp, "tree")
    os.makedirs(os.path.join(tree, ".sclaude", "local", "feature"))

    # Few: inline as before.
    out = snapshot(tree, [thread(1, "a.ts"), thread(2, "b.ts")], [resolved(9, "a.ts")])
    check("few-inline", ("finding 1" in out, "a reply to 2" in out, "old finding 9" in out,
                         "threads.md" in out), (True, True, True, False))
    check("few-files-written", "## 2. `b.ts:2`" in read(tree, "threads.md"), True)

    # Many open threads: an index, each whole in threads.md.
    many = [thread(k, "f%d.ts" % (k % 7)) for k in range(1, 81)]
    out = snapshot(tree, many, [])
    text = read(tree, "threads.md")
    check("many-index", ("80 open review threads" in out, "- 57. `f1.ts:57` — **finding 57**" in out,
                         "x" * 200 in out, len(out.encode()) < 20000), (True, True, False, True))
    check("many-whole-in-file", ("## 57. `f1.ts:57`" in text, "a reply to 57" in text,
                                 text.count("\n## ")), (True, True, 80))

    # More still: a count per file.
    lots = [thread(k, "dir/file%02d.ts" % (k % 40)) for k in range(1, 801)]
    out = snapshot(tree, lots, [])
    check("lots-per-file", ("800 open review threads on 40 files" in out,
                            "- `dir/file07.ts` — 20" in out, len(out.encode()) < 8000), (True, True, True))

    # A thread a night left for the person comes whole and first, whatever
    # the layout; the threads the person left go to left.md when many.
    pr_context.night = lambda cwd: {lots[4]["url"]: "keep it, a guard the schema has"}
    out = snapshot(tree, lots, [])
    check("night-thread-whole-and-first", (out.find("a guard the schema has") < out.find("799 other open"),
                                           "Ask them about it first" in out, "x" * 200 in out,
                                           "Ask them about it first" in read(tree, "threads.md")),
          (True, True, True, True))
    # Night threads and the rest share one budget: together they do not take
    # more of the prompt than one layout did.
    mid = [thread(k, "m.ts", 1500) for k in range(1, 18)]
    pr_context.night = lambda cwd: {mid[0]["url"]: "keep", mid[1]["url"]: "keep"}
    out = snapshot(tree, mid, [])
    check("night-and-rest-share-the-budget", ("15 other open review threads" in out,
                                              len(out.encode()) < pr_context.THREADS_INLINE_MAX + 4000),
          (True, True))
    # Night threads past half the budget still leave the others their index
    # when it fits in what is left.
    big = [thread(k, "n.ts", 4400) for k in range(1, 3)] + [thread(k, "o.ts", 600) for k in range(3, 15)]
    pr_context.night = lambda cwd: {big[0]["url"]: "keep", big[1]["url"]: "keep"}
    out = snapshot(tree, big, [])
    check("index-after-a-big-night-lead", ("12 other open review threads, too many to show" in out,
                                           "- 14. `o.ts:14`" in out), (True, True))
    few = [thread(k, "a.ts") for k in range(1, 6)]
    pr_context.night = lambda cwd: {few[3]["url"]: "keep it"}
    out = snapshot(tree, few, [])
    check("night-first-inline-too", out.find("finding 4") < out.find("finding 1"), True)
    pr_context.night = lambda cwd: {}
    left = {t["url"]: "leave it" for t in lots[:300]}
    pr_context.yours = lambda cwd: left
    out = snapshot(tree, lots, [])
    check("left-many-to-file", ("300 threads left as they are" in out, lots[5]["url"] in out,
                                lots[5]["url"] in read(tree, "left.md"),
                                read(tree, "left.md").startswith("# ")), (True, False, True, True))
    pr_context.yours = lambda cwd: {}
    snapshot(tree, lots, [])
    check("left-gone-when-not-needed",
          os.path.exists(os.path.join(tree, pr_context.PR_DIR, "left.md")), False)

    # A discussion too long even for its index: the latest headlines.
    talk = [{"author": {"login": "p"}, "body": "**request %d** %s" % (k, "w" * 150)}
            for k in range(1, 301)]
    pr_context.pr_view = lambda cwd, pr, fields: {"statusCheckRollup": [], "comments": talk,
                                                  "headRefOid": "abc"}
    out = snapshot(tree, [], [])
    check("discussion-latest", ("300. p — **request 300**" in out, "1. p — **request 1**" in out,
                                "the " in out and "are in the file only" in out), (True, False, True))
    pr_context.pr_view = lambda cwd, pr, fields: {"statusCheckRollup": [], "comments": [],
                                                  "headRefOid": "abc"}

    # Resolved on the open files: a count and the lines of its section.
    olds = [resolved(k, "big.sql") for k in range(1, 201)] + [resolved(k, "z.ts") for k in range(1, 4)]
    out = snapshot(tree, [thread(1, "big.sql")], olds)
    pointer = [l for l in out.splitlines() if l.startswith("- `big.sql` — 200, lines ")]
    lines = read(tree, "resolved.md").splitlines()
    first, last = (int(n) for n in pointer[0].rsplit(" ", 1)[1].split("–")) if pointer else (0, 0)
    check("resolved-pointer", (bool(pointer), "old finding 5" in out, "z.ts" in out), (True, False, False))
    check("resolved-lines-are-the-section", (lines[first - 1], lines[last - 1].startswith("- `:200`")),
          ("## `big.sql`", True))

    # The threads unread (GitHub failed): no file written over the last
    # good one; the narrow refresh says it did nothing.
    before = read(tree, "resolved.md")
    pr_context.open_threads = lambda cwd, pr, repo, nodes=None: (None, [])
    pr_context.pr_view = lambda cwd, pr, fields: {"statusCheckRollup": [], "headRefOid": "abc",
                                                  "comments": [{"author": {"login": "p"},
                                                                "body": "the latest word"}]}
    snapshot(tree, [], [])
    check("unread-keeps-the-files", read(tree, "resolved.md"), before)
    check("unread-still-writes-the-discussion", "the latest word" in read(tree, "discussion.md"), True)
    pr_context.pr_view = lambda cwd, pr, fields: {"statusCheckRollup": [], "comments": [],
                                                  "headRefOid": "abc"}
    check("refresh-unread", (pr_context.refresh_resolved(tree, 1, "o/r"), read(tree, "resolved.md")),
          (False, before))
    pr_context.open_threads = lambda cwd, pr, repo, nodes=None: (STATE["open"], STATE["resolved"])
    # The narrow refresh writes resolved.md alone.
    threads_before = read(tree, "threads.md")
    STATE["open"], STATE["resolved"] = [thread(1, "q.ts")], [resolved(3, "new.ts")]
    check("refresh-resolved-alone", (pr_context.refresh_resolved(tree, 1, "o/r"),
                                     "## `new.ts`" in read(tree, "resolved.md"),
                                     read(tree, "threads.md") == threads_before), (True, True, True))

    # Outside a feature's tree: inline, nothing written.
    plain = os.path.join(tmp, "plain")
    os.makedirs(plain)
    out = snapshot(plain, many, olds)
    check("no-tree-inline", ("x" * 200 in out, os.path.exists(os.path.join(plain, ".sclaude"))),
          (True, False))

    # The local review's settled findings.
    def found(k, path, resolved_, decision=""):
        return {"id": "T%d" % k, "rid": "r%d" % k, "resolved": resolved_, "review": True,
                "path": path, "line": k, "url": "u%d" % k, "decision": decision,
                "bodies": ["**settled %d %s**" % (k, "z" * 60)]}
    local_review.yours = lambda cwd: {}
    local_review.pending_of = lambda journal: []
    local_review.threads = lambda cwd, pr, repo: STATE["found"]
    STATE["found"] = [found(1, "a.ts", True), found(2, "a.ts", True, "a reason")]
    def prompt_text():
        buf, real = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            local_review.prompt(tree, 1, "o/r", "j")
        finally:
            sys.stdout = real
        return buf.getvalue()

    out = prompt_text()
    check("settled-few-inline", ("settled 1" in out, "a reason" in out, "settled.md" in out),
          (True, True, False))
    # Declined alone, nothing fixed: inline once, no file — and outside a
    # feature's tree no crash.
    STATE["found"] = [found(2, "a.ts", True, "a reason")]
    out = prompt_text()
    check("declined-alone-once", ("a reason" in out, "settled.md" in out), (True, False))
    tree, saved = plain, tree
    out = prompt_text()
    check("declined-alone-no-tree", "a reason" in out, True)
    tree = saved
    STATE["found"] = [found(k, "f%d.ts" % (k % 5), True, "why %d" % k if k % 10 == 0 else "")
                      for k in range(1, 401)]
    out = prompt_text()
    settled = read(tree, "settled.md")
    # 40 declined fit inline, 360 fixed do not: the fixed go to the file,
    # the declined are said once, inline.
    check("settled-many-to-file", ("360 fixed" in out, "the author decided to leave" in out,
                                   "settled 7 z" in out, "settled 70 z" in out, len(out) < 8000),
          (True, True, False, True, True))
    check("settled-file-by-path", ("## `f2.ts`" in settled, "- :7 — **settled 7 z" in settled,
                                   "(declined" in settled), (True, True, False))
    # Many declined too: all in the file, none inline.
    STATE["found"] = [found(k, "f%d.ts" % (k % 5), True, "why %d" % k) for k in range(1, 401)]
    out = prompt_text()
    check("settled-declined-spilled", ("400 the author decided to leave" in out, "why 7)" in out,
                                       "(declined: why 7)" in read(tree, "settled.md")),
          (True, False, True))
    STATE["found"] = [found(1, "a.ts", True)]
    prompt_text()
    check("settled-gone-when-not-needed",
          os.path.exists(os.path.join(tree, pr_context.PR_DIR, "settled.md")), False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
