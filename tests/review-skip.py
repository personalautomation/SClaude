#!/usr/bin/env python3
#
# Step 4 without work to do: a clean review opens no session, and an unchanged
# tree is not tested twice.
#
# Two decisions, each with a cheap way to be wrong:
#
#   * review_state (pr_context.py) says whether the automatic review left
#     anything to answer. A wrong "clean" skips the only look at review
#     comments the cycle has, so every doubt must answer something else.
#
#   * regression_gate skips the local run when the verdict names the tree
#     still in the worktree. A wrong skip calls untested code green, so any
#     change — a commit, an uncommitted edit — must run the suite.
#
# Run it with: python3 tests/review-skip.py
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, check=False).stdout.strip()


spec = importlib.util.spec_from_file_location("pr_context",
                                              os.path.join(LIB, "pr_context.py"))
pr_context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_context)

# The review job as the myapp workflow names it: "Review" without "Claude",
# which only its workflow name supplies.
REVIEW_JOB = "Review — delta, whole PR once all fixed (Opus)"

tmp = tempfile.mkdtemp()
try:
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    with open(os.path.join(repo, "a.txt"), "w") as fh:
        fh.write("a\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "first", cwd=repo)
    head = git("rev-parse", "HEAD", cwd=repo)

    bot = {"type": "Bot", "login": "claude[bot]"}
    person = {"type": "User", "login": "ilia"}
    green = [{"name": "checks", "status": "COMPLETED", "conclusion": "SUCCESS"},
             {"name": REVIEW_JOB, "workflowName": "Claude Code Review", "status": "COMPLETED", "conclusion": "SUCCESS"},
             {"name": pr_context.FINDINGS_CHECK, "status": "COMPLETED", "conclusion": "SUCCESS"}]

    def world(**over):
        w = {
            "head": head,
            "rollup": green,
            "findings": [{"name": pr_context.FINDINGS_CHECK, "status": "completed",
                          "conclusion": "success", "external_id": "reviewed"}],
            "comments": [{"user": bot, "body": "## Code review\n\nNo issues found."}],
            "inline": [],
            "reviews": [],
        }
        w.update(over)
        return w

    def state(w):
        def fake(args, cwd=None):
            if args[:2] == ["pr", "view"]:
                return {"headRefOid": w["head"], "statusCheckRollup": w["rollup"]}
            path = args[1] if args[0] == "api" else ""
            if "check-runs" in path:
                return {"check_runs": w["findings"]}
            if "/issues/" in path:
                return w["comments"]
            if path.endswith("/comments"):
                return w["inline"]
            if path.endswith("/reviews"):
                return w["reviews"]
            return None
        pr_context.gh_json = fake
        return pr_context.review_state(repo, "7", "o/r")

    # --- clean: the one case that skips the session -------------------------
    check("clean", state(world()), "clean")
    # The bot's own summary and its resolved findings are not a request.
    check("bot-inline-is-the-findings-check",
          state(world(inline=[{"user": bot, "body": "fixed now"}])), "clean")
    check("empty-person-approval-is-clean",
          state(world(reviews=[{"user": person, "state": "APPROVED", "body": ""}])),
          "clean")

    # The workflow posts the verdict as a commit status as well, which the
    # rollup names by `context`. It is the findings check, judged by its run
    # below, and not a red build: here the run says green, so it is clean.
    check("findings-status-is-the-findings-check",
          state(world(rollup=green + [{"context": pr_context.FINDINGS_CHECK,
                                       "state": "FAILURE"}])), "clean")

    # --- dirty: something to answer ------------------------------------------
    check("open-finding", state(world(findings=[{
        "name": pr_context.FINDINGS_CHECK, "status": "completed",
        "conclusion": "failure", "external_id": "reviewed"}])), "dirty")
    check("red-check", state(world(rollup=[dict(green[0], conclusion="FAILURE")]
                                   + green[1:])), "dirty")
    check("person-comment", state(world(comments=[{"user": person, "body": "why?"}])),
          "dirty")
    check("person-inline", state(world(inline=[{"user": person, "body": "nit"}])),
          "dirty")
    check("changes-requested",
          state(world(reviews=[{"user": person, "state": "CHANGES_REQUESTED",
                                "body": ""}])), "dirty")
    check("review-with-words",
          state(world(reviews=[{"user": person, "state": "COMMENTED",
                                "body": "one thing"}])), "dirty")

    # --- pending: ask again ---------------------------------------------------
    check("no-checks-yet", state(world(rollup=[])), "pending")
    check("running", state(world(rollup=[dict(green[1], status="IN_PROGRESS",
                                              conclusion="")])), "pending")
    check("findings-not-written-yet",
          state(world(findings=[], rollup=green[:2])), "pending")

    # --- unknown: open the session as before ---------------------------------
    check("head-not-pushed", state(world(head="0" * 40)), "unknown")
    check("no-review-workflow", state(world(findings=[], rollup=green[:1])), "unknown")
    # "Preview" contains the letters of "review"; it is not a review check.
    check("preview-check-is-not-a-review",
          state(world(findings=[], rollup=[green[0], {
              "name": "Vercel Preview Comments", "status": "COMPLETED",
              "conclusion": "SUCCESS"}])), "unknown")
    # A repository with no checks at all: pending only just after the push.
    saved = pr_context.recent
    pr_context.recent = lambda created, cwd: False
    check("no-checks-ever", state(world(rollup=[])), "unknown")
    pr_context.recent = saved
    # The workflow-validation skip: green in seconds, nothing read. Nothing for
    # a session to answer either — unless a person said something.
    skipped = [{"name": pr_context.FINDINGS_CHECK, "status": "completed",
                "conclusion": "success", "external_id": "not-reviewed"}]
    check("review-did-not-run", state(world(findings=skipped)), "unreviewed")
    check("review-did-not-run-person-spoke",
          state(world(findings=skipped, comments=[{"user": person, "body": "why?"}])),
          "dirty")
    check("review-no-mark", state(world(findings=[dict(skipped[0], external_id="")])),
          "unknown")
    # Skipped by the `no-review` label, as a project whose review is not
    # GitHub's has it: the review job is SKIPPED and no findings check comes.
    # Not "pending" — that waited the whole REVIEW_WAIT_MAX for nothing.
    labelled = [green[0], dict(green[1], conclusion="SKIPPED")]
    check("review-skipped-by-label", state(world(findings=[], rollup=labelled)),
          "unreviewed")
    check("review-skipped-by-label-person-spoke",
          state(world(findings=[], rollup=labelled,
                      comments=[{"user": person, "body": "why?"}])), "dirty")
    # Reviewed on this machine: GitHub Actions does not count at all, since
    # the mode exists for when its minutes ran out and every workflow fails
    # at once. Its checks are dropped as the pull request is read, and with
    # nothing else to wait for the people's word decides.
    actions_red = [dict(green[0], workflowName="Checks", conclusion="FAILURE"),
                   dict(green[1], conclusion="FAILURE"),
                   {"context": pr_context.FINDINGS_CHECK, "state": "FAILURE"}]
    check("without-actions", pr_context.without_actions(
        actions_red + [{"name": "Vercel", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
        [{"name": "Vercel", "status": "COMPLETED", "conclusion": "SUCCESS"}])
    saved_mode = pr_context.review_mode
    pr_context.review_mode = lambda cwd: "local"
    check("local-no-checks-is-unreviewed", state(world(findings=[], rollup=[])), "unreviewed")
    check("local-person-spoke", state(world(findings=[], rollup=[],
                                            comments=[{"user": person, "body": "why?"}])),
          "dirty")
    check("local-other-check-red", state(world(findings=[], rollup=[
        {"name": "Vercel", "status": "COMPLETED", "conclusion": "FAILURE"}])), "dirty")
    # Its findings and replies go out under the person's account, signed: they
    # are the review's words, not the person's. A thread still open is caught
    # by the threads, not here.
    signed = {"user": person, "body": "**x**\n\n%s · abc</sub>" % pr_context.LOCAL_SIGNATURE}
    check("local-signed-not-a-person", state(world(findings=[], rollup=[], inline=[signed])),
          "unreviewed")
    pr_context.review_mode = saved_mode
    check("review-skipped-by-label-red-check",
          state(world(findings=[], rollup=[dict(green[0], conclusion="FAILURE"),
                                           labelled[1]])), "dirty")

    # --- which check is the review --------------------------------------------
    # The job says "Review" and its workflow says "Claude"; the findings check
    # says "review" too, and is written by the review rather than being it — a
    # green one made in no time would read as a review that never ran.
    check("review-job-is-the-review",
          pr_context.is_claude_review(REVIEW_JOB, "Claude Code Review"), True)
    check("findings-check-is-not-the-review",
          pr_context.is_claude_review(pr_context.FINDINGS_CHECK, "Claude Code Review"), False)
    check("mention-job-is-not-the-review",
          pr_context.is_claude_review(
              "Task from @claude comment — repo on PR branch (Claude, model from comment or default)",
              "Claude on @mention"), False)
    check("preview-is-not-review", pr_context.names_review("Vercel Preview Comments"), False)
    rows = pr_context.checks_table([
        {"name": pr_context.FINDINGS_CHECK, "workflowName": "Claude Code Review",
         "conclusion": "SUCCESS", "startedAt": "2020-01-01T00:00:00Z",
         "completedAt": "2020-01-01T00:00:00Z"}])
    check("findings-check-is-not-judged", pr_context.review_verdict(rows, 0, 0), None)

    # --- the local regression is not run twice on one tree --------------------
    wt = repo
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    with open(os.path.join(wt, ".git", "info", "exclude"), "a") as fh:
        fh.write(".sclaude/local/feature\n")

    def gate(tree):
        with open(os.path.join(wt, ".sclaude/local/feature", "state.json"), "w") as fh:
            json.dump({"regression": {"local": {"status": "passed", "tree": tree}}}, fh)
        body = "set -uo pipefail\n"
        body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
        for name in ("io", "ui", "steps", "state", "worktree", "scratch", "regression"):
            body += 'source "%s/%s.sh"\n' % (LIB, name)
        body += ('warn() { echo "$*"; }\ninfo() { echo "$*"; }\nsay() { echo "$*"; }\n'
                 'regression_run() { echo RAN; return 0; }\n'
                 'regression_rewind() { :; }\nregression_clear_mark() { :; }\n'
                 'regression_gate "%s" demo local\n' % wt)
        return subprocess.run(["bash", "-c", body], capture_output=True,
                              text=True, timeout=30).stdout

    out = gate(head)
    check("same-tree-not-run-again", "RAN" in out, False)
    check("same-tree-says-so", "not run again" in out, True)

    out = gate("f" * 40)
    check("new-commit-runs", "RAN" in out, True)

    with open(os.path.join(wt, "a.txt"), "w") as fh:
        fh.write("edited\n")
    out = gate(head)
    check("uncommitted-edit-runs", "RAN" in out, True)
    git("checkout", "--", "a.txt", cwd=wt)

    out = gate(None)
    check("no-recorded-tree-runs", "RAN" in out, True)

    # sclaude's own scratch files are not a change to the tree, excluded or not.
    with open(os.path.join(wt, ".vercelignore"), "w") as fh:
        fh.write("x\n")
    out = gate(head)
    check("scratch-paths-do-not-count", "RAN" in out, False)
    os.remove(os.path.join(wt, ".vercelignore"))

    # --- a review sent back is never skipped ---------------------------------
    def skippable(state_blob, watch=None):
        home = os.path.join(tmp, "home")
        shutil.rmtree(home, ignore_errors=True)
        wdir = os.path.join(home, ".claude", "sclaude", "watch")
        os.makedirs(wdir)
        if watch is not None:
            with open(os.path.join(wdir, "demo.json"), "w") as fh:
                json.dump(watch, fh)
        with open(os.path.join(wt, ".sclaude/local/feature", "state.json"), "w") as fh:
            json.dump(state_blob, fh)
        body = "set -uo pipefail\n"
        for name in ("io", "ui", "steps", "state", "watch", "run"):
            body += 'source "%s/%s.sh"\n' % (LIB, name)
        body += 'review_skippable "%s" demo && echo YES || echo NO\n' % wt
        out = subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                             timeout=30, env=dict(os.environ, HOME=home)).stdout
        return out.strip().endswith("YES")

    check("first-entry-skippable", skippable({"step": "review"}), True)
    check("reopened-not-skippable",
          skippable({"step": "review", "reopened": "review"}), False)
    check("returned-verdict-not-skippable",
          skippable({"step": "review"}, watch={"verdict": "returned"}), False)

finally:
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
