#!/usr/bin/env python3
#
# `sclaude checks`: step 4's wait after a push (wait_checks in pr_context.py).
#
# The review check registers last, and the findings check after it, so a wait
# that reads the checks it can see returns too soon; one with no limit hangs on
# a push that starts no review, and one that runs out quietly leaves the push
# unreviewed with nobody told. Guarded here:
#
#   * the wait returns only once the review check has appeared and every
#     check, the findings check included, has finished;
#   * no review check within the limit, and checks unfinished within the next
#     one, each end with a verdict and exit code of their own;
#   * the review check is the one names_review names: a word anywhere in the
#     name, not "Preview", not the findings check;
#   * a pull request with no review on any commit does not wait for one;
#   * unpushed commits and an unreadable GitHub are said at once, never green;
#   * the step 4 prompt names the command and every verdict with its code, and
#     carries no polling loop of its own.
#
# Run it with: python3 tests/checks-wait.py
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
PROMPT = os.path.join(ROOT, "sclaude", "prompts", "review.md")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, check=False).stdout.strip()


spec = importlib.util.spec_from_file_location("pr_context", os.path.join(LIB, "pr_context.py"))
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)

REVIEW_JOB = "Review — delta, whole PR once all fixed (Opus)"
LIMIT, PERIOD = 600, 15

BUILD = {"name": "checks", "status": "COMPLETED", "conclusion": "SUCCESS"}
BUILD_RUNNING = {"name": "checks", "status": "IN_PROGRESS", "conclusion": ""}
REVIEW_DONE = {"name": REVIEW_JOB, "status": "COMPLETED", "conclusion": "SUCCESS"}
REVIEW_RUNNING = {"name": REVIEW_JOB, "status": "IN_PROGRESS", "conclusion": ""}
REVIEW_QUEUED = {"name": REVIEW_JOB, "status": "QUEUED", "conclusion": ""}
REVIEW_SKIPPED = {"name": REVIEW_JOB, "status": "COMPLETED", "conclusion": "SKIPPED"}
FINDINGS_STATUS = {"context": ctx.FINDINGS_CHECK, "state": "SUCCESS"}
FINDINGS_DONE = {"name": ctx.FINDINGS_CHECK, "status": "completed", "conclusion": "success"}
FINDINGS_RED = {"name": ctx.FINDINGS_CHECK, "status": "completed", "conclusion": "failure"}

tmp = tempfile.mkdtemp(prefix="sclaude-checks-")
try:
    origin = os.path.join(tmp, "origin.git")
    repo = os.path.join(tmp, "repo")
    git("init", "-q", "--bare", origin, cwd=tmp)
    os.makedirs(repo)
    git("init", "-q", "-b", "feat", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    git("remote", "add", "origin", origin, cwd=repo)
    for n in ("first", "second"):
        with open(os.path.join(repo, "a.txt"), "a") as fh:
            fh.write(n + "\n")
        git("add", "-A", cwd=repo)
        git("commit", "-qm", n, cwd=repo)
    git("push", "-q", "origin", "feat", cwd=repo)
    head = git("rev-parse", "HEAD", cwd=repo)
    before = git("rev-parse", "HEAD~1", cwd=repo)

    def wait(rollups, findings=None, history=None, heads=None, fail=False):
        """Run wait_checks against a pull request whose rollup is `rollups[i]`
        on the i-th read (the last one repeats), likewise `findings` for the
        findings run on the head and `heads` for the head GitHub names.
        `history` is the check names on the earlier commit. Returns (code,
        lines, reads, seconds waited)."""
        findings = findings or [FINDINGS_DONE]
        history = [REVIEW_JOB, ctx.FINDINGS_CHECK] if history is None else history
        heads = heads or [head]
        reads = {"view": 0, "findings": 0}
        now = [0.0]

        def nth(seq, i):
            return seq[min(i, len(seq) - 1)]

        def fake(args, cwd=None):
            if fail:
                return None
            if args[:2] == ["pr", "view"] and args[-1] == "commits":
                return {"commits": [{"oid": before}, {"oid": head}]}
            if args[:2] == ["pr", "view"]:
                i = reads["view"]
                reads["view"] += 1
                return {"headRefOid": nth(heads, i), "statusCheckRollup": nth(rollups, i),
                        "state": "OPEN", "createdAt": "2026-01-01T00:00:00Z"}
            path = args[1] if args[0] == "api" else ""
            if "check_name=" in path:
                i = reads["findings"]
                reads["findings"] += 1
                run = nth(findings, i)
                return {"check_runs": [run] if run else []}
            if "/check-runs" in path:
                names = history if before in path else []
                return {"check_runs": [{"name": n} for n in names]}
            return None

        def sleep(seconds):
            now[0] += seconds

        lines = []
        ctx.gh_json = fake
        code = ctx.wait_checks(repo, "7", "o/r", LIMIT, PERIOD, say=lines.append,
                               clock=lambda: now[0], sleep=sleep)
        return code, lines, reads["view"], now[0]

    # --- AC1: returns only once the review is there and everything finished --
    code, lines, reads, _ = wait(
        [[BUILD_RUNNING], [BUILD], [BUILD, REVIEW_RUNNING],
         [BUILD, REVIEW_DONE, FINDINGS_STATUS]])
    check("late-review: green", code, ctx.CHECKS_GREEN)
    check("late-review: waited for every read", reads, 4)
    check("late-review: verdict line", lines[-1].startswith("green: "), True)
    check("late-review: table printed", any(REVIEW_JOB in l for l in lines), True)

    # The rollup reads "all finished" before the findings check registers.
    code, lines, reads, _ = wait([[BUILD, REVIEW_DONE]],
                                 findings=[None, None, {"name": ctx.FINDINGS_CHECK,
                                                        "status": "in_progress"},
                                           FINDINGS_DONE])
    check("findings-late: green", code, ctx.CHECKS_GREEN)
    check("findings-late: not before the findings run completed", reads, 4)

    code, lines, _, _ = wait([[BUILD, REVIEW_DONE, dict(FINDINGS_STATUS, state="FAILURE")]],
                             findings=[FINDINGS_RED])
    check("red: code", code, ctx.CHECKS_RED)
    check("red: names the check", lines[-1].startswith("red: ") and ctx.FINDINGS_CHECK in lines[-1],
          True)

    # A review skipped on purpose writes no findings check: nothing to wait for.
    code, _, reads, _ = wait([[BUILD, REVIEW_SKIPPED]], findings=[None])
    check("skipped-review: no findings wait", (code, reads), (ctx.CHECKS_GREEN, 1))

    # --- AC2: no review check within the limit ---------------------------------
    code, lines, _, waited = wait([[BUILD]])
    check("no-review: code", code, ctx.CHECKS_NO_REVIEW)
    check("no-review: says so", lines[-1],
          "no review: No review started on %s within 10 min — this push is not reviewed."
          % head[:7])
    check("no-review: bounded by the limit", LIMIT <= waited < LIMIT + 2 * PERIOD, True)

    # --- AC3: the review is there, and stuck --------------------------------
    code, lines, _, waited = wait([[BUILD], [BUILD, REVIEW_QUEUED]])
    check("queued: code", code, ctx.CHECKS_NOT_DONE)
    check("queued: says so", "still running or queued" in lines[-1]
          and lines[-1].startswith("not finished: "), True)
    # The second limit counts from the review appearing, not from the start.
    check("queued: two limits at most", LIMIT + PERIOD <= waited < 2 * LIMIT + 2 * PERIOD, True)

    # --- AC5: what counts as the review check ---------------------------------
    preview = {"name": "Preview Comments", "status": "COMPLETED", "conclusion": "SUCCESS"}
    code, _, _, _ = wait([[BUILD, preview, FINDINGS_STATUS]])
    check("names: Preview and the findings check are not the review", code,
          ctx.CHECKS_NO_REVIEW)
    late_word = {"name": "Claude review of the delta", "status": "COMPLETED",
                 "conclusion": "SUCCESS"}
    code, _, _, _ = wait([[BUILD, late_word]], history=["Claude review of the delta"])
    check("names: the word anywhere in the name", code, ctx.CHECKS_GREEN)

    # --- a pull request no review ever ran on ---------------------------------
    code, lines, reads, _ = wait([[BUILD_RUNNING], [BUILD, preview]], history=["checks"],
                                 findings=[None])
    check("no-review-project: waits for the checks only", (code, reads),
          (ctx.CHECKS_GREEN, 2))

    # --- right after the push GitHub still names the commit before ------------
    code, _, reads, _ = wait([[BUILD, REVIEW_DONE], [BUILD], [BUILD, REVIEW_DONE]],
                             heads=[before, head])
    check("old-head: its finished review is not this push's", (code, reads),
          (ctx.CHECKS_GREEN, 3))

    # --- said at once, never green --------------------------------------------
    code, lines, _, waited = wait([[]], fail=True)
    check("unreadable: code", code, ctx.CHECKS_UNREADABLE)
    check("unreadable: gives up after the retries",
          waited, (ctx.CHECKS_READ_RETRIES - 1) * PERIOD)

    with open(os.path.join(repo, "a.txt"), "a") as fh:
        fh.write("third\n")
    git("commit", "-qam", "third", cwd=repo)
    code, lines, _, waited = wait([[BUILD, REVIEW_DONE]])
    check("unpushed: code", code, ctx.CHECKS_UNREADABLE)
    check("unpushed: at once", (waited, "not pushed" in lines[-1]), (0.0, True))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- AC6: the prompt and the command agree ------------------------------------
with open(PROMPT) as fh:
    prompt = fh.read()
check("prompt: names the command", "`sclaude checks <pr>`" in prompt, True)
for code, word in ctx.CHECKS_VERDICTS.items():
    check("prompt: verdict %d %s" % (code, word), "`%d` %s —" % (code, word) in prompt, True)
check("prompt: no loop of its own",
      re.search(r"\b(until|while)\b[^\n]*;\s*do\b[^\n]*sleep", prompt), None)
check("prompt: not --watch as the wait", "gh pr checks <pr> --watch" in prompt, False)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
