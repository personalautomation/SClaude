#!/usr/bin/env python3
#
# Two features at once, and what they share.
#
# On 2026-10-06 two features ran side by side for the first time,
# and the trouble was all in what the two sclaude processes shared: the Claude
# quota, the machine, the instruments tree, and the person's attention.
#
# Guarded here:
#
#   * session_end.py finds the usage limit a session stopped on, with its
#     reset, and forgets it once the conversation goes on;
#   * session_watch_start closes a session standing on a limit once the limit
#     has reset, and says so to claude_launch through a file;
#   * claude_launch opens that session again with `--resume`, its name, and a
#     word to carry on — not the opening prompt;
#   * lock_take makes a second holder wait for the first, and the queue
#     given up is free at once, with nobody named as holding it;
#   * pr_context.py reads a "resets 4am (Europe/Lisbon)" from a review log;
#   * the threads a person decided to leave are kept apart: the snapshot lists
#     them separately, close_state answers `yours`, and a findings check left
#     red only by them, or by threads resolved by hand, holds nothing up;
#   * a review report that proposes something keeps its session open.
#
# Run it with: python3 tests/parallel.py
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import benchlib  # noqa: E402 — shell functions found by name


def _cfg(path):
    """The path of a product's config, its .sclaude/ folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIB, "review" if name == "pr_context" else "cycle", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


end = load("session_end")
ctx = load("pr_context")
tmp = tempfile.mkdtemp(prefix="sclaude-parallel-")


def stamp(offset=0.0):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + offset)) + ".000Z"


def limit_entry(uuid, resets, offset=0.0):
    return {"type": "assistant", "uuid": uuid, "timestamp": stamp(offset), "error": "rate_limit",
            "apiErrorStatus": 429, "isApiErrorMessage": True,
            "quotaLimits": {"resetsAt": resets, "rateLimitType": "five_hour"},
            "message": {"stop_reason": "stop_sequence", "content": [
                {"type": "text", "text": "You've hit your session limit · resets 6:50pm"}]}}


def ordinary(text="On it."):
    return {"type": "assistant", "timestamp": stamp(),
            "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}}


def typed(text):
    return {"type": "user", "timestamp": stamp(), "origin": {"kind": "human"},
            "message": {"content": text}}


def notification():
    return {"type": "user", "timestamp": stamp(), "message": {"content": "<task-notification/>"}}


def write(path, entries):
    with open(path, "w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


# --- session_end.py limit ------------------------------------------------------
t = os.path.join(tmp, "t.jsonl")
write(t, [ordinary(), limit_entry("u1", 1791309000)])
check("limit-found", end.limit(t), ("u1", 1791309000, "five_hour"))
write(t, [ordinary(), limit_entry("u1", 1791309000), notification()])
check("limit-survives-a-notification", end.limit(t), ("u1", 1791309000, "five_hour"))
write(t, [limit_entry("u1", 1791309000), typed("go")])
check("limit-cleared-by-a-person", end.limit(t), None)
write(t, [limit_entry("u1", 1791309000), ordinary()])
check("limit-cleared-by-the-turn-going-on", end.limit(t), None)
write(t, [ordinary()])
check("no-limit", end.limit(t), None)

# --- the watcher closes a session on a reset limit -----------------------------
RUN = "".join(open(os.path.join(LIB, m), encoding="utf-8").read()
          for m in ("cycle/run.sh", "cycle/session_watch.sh", "review/review_round.sh", "improve/friction.sh"))


def functions(names):
    """The named shell functions, found by name in the whole library."""
    return benchlib.functions(names, missing=lambda name: check("function-present-" + name, False, True))



WATCH = 'source "%s/core/state.sh"\nLIB="%s"\n' % (LIB, LIB) + functions(
    ["done_marker", "session_ctl_file", "session_keep_file", "session_watched_file",
     "wait_note", "session_watch_start", "session_watch_stop"])

wt = os.path.join(tmp, "wt")
os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
home = os.path.join(tmp, "home")
tdir = os.path.join(home, ".claude", "projects", re.sub(r"[^a-zA-Z0-9]", "-", wt))
os.makedirs(tdir)
# A fresh id for each run, as in review-round.py: the watcher ends a session
# by `pkill -f "--resume <id>"`, and a second copy of this test running at the
# same time would end this one's stand-ins.
session = str(uuid.uuid4())
transcript = os.path.join(tdir, session + ".jsonl")
limit_file = os.path.join(tmp, "sclaude-limit-" + session)


def watch(resets, wait=1.5, offset=1.0):
    """The limit is met `offset` seconds after the watcher starts; a negative
    one is a limit already standing when the session was reopened."""
    target = subprocess.Popen(["bash", "-c", 'exec -a "claude --resume %s" sleep 60' % session])
    write(transcript, [ordinary(), limit_entry("u-%d" % resets, resets, offset)])
    script = WATCH + """
export HOME="%s" TMPDIR="%s"
SESSION_POLL=0.2 LIMIT_MARGIN=0
session_watch_start "%s" "%s" "" "" review
# Until the stand-in is gone or `wait` runs out: under the whole suite in
# parallel the watcher's first look comes late, and a fixed second and a
# half failed a close that was only slow.
# Gone or a zombie (this test reaps it later) counts as gone.
for _ in $(seq %d); do ps -o stat= -p %d 2>/dev/null | grep -qv Z || break; sleep 0.1; done
session_watch_stop
""" % (home, tmp, wt, session, int(wait * 10), target.pid)
    subprocess.run(["bash", "-c", script], timeout=30)
    time.sleep(0.2)
    closed = target.poll() is not None
    target.kill()
    return closed


check("reset-limit-closes-the-session", watch(int(time.time()) - 10, wait=10), True)
check("reset-limit-tells-claude-launch", os.path.exists(limit_file), True)
if os.path.exists(limit_file):
    os.remove(limit_file)
check("limit-not-yet-reset-leaves-it", watch(int(time.time()) + 3600), False)
check("no-word-before-the-reset", os.path.exists(limit_file), False)
check("limit-from-before-the-reopening-left-alone", watch(int(time.time()) - 10, offset=-60), False)
check("no-word-for-an-old-limit", os.path.exists(limit_file), False)

# --- claude_launch opens it again ----------------------------------------------
script = """
source "%s/core/steps.sh"
source "%s/core/pane.sh"
export TMPDIR="%s"
info() { :; }
pane_available() { return 1; }
calls=0
claude() {
  calls=$((calls + 1))
  printf '%%s\\n' "$*" >> "%s/calls"
  [[ $calls -eq 1 ]] && echo u > "$TMPDIR/sclaude-limit-%s"
  return 0
}
claude_launch --session-id %s --model opus -n "demo/review" "the opening prompt"
echo "rc=$?"
""" % (LIB, LIB, tmp, tmp, session, session)
out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
calls = open(os.path.join(tmp, "calls")).read().splitlines()
check("relaunched-once", len(calls), 2)
if len(calls) == 2:
    check("first-launch-as-given", calls[0],
          "--session-id %s --model opus -n demo/review the opening prompt" % session)
    check("second-launch-resumes", calls[1].startswith(
        "--resume %s --model opus -n demo/review The usage limit" % session), True)
    check("opening-prompt-not-repeated", "the opening prompt" in calls[1], False)
check("limit-file-consumed", os.path.exists(os.path.join(tmp, "sclaude-limit-" + session)), False)

# --- the queue -----------------------------------------------------------------
lock = os.path.join(tmp, "q.lock")
holder = """
source "%s/core/lock.sh"
warn() { echo "WARN $*"; }; info() { echo "INFO $*"; }
lock_take fd "%s" "%s" "a regression"
echo "took $(date +%%s.%%N)"
sleep %s
lock_release "$fd" "%s"
"""
first = subprocess.Popen(["bash", "-c", holder % (LIB, lock, "feature-a, local", 1.5, lock)],
                         stdout=subprocess.PIPE, text=True)
time.sleep(0.4)
second = subprocess.run(["bash", "-c", holder % (LIB, lock, "feature-b, local", 0, lock)],
                        capture_output=True, text=True, timeout=30)
first_out = first.communicate(timeout=30)[0]
check("second-waits-and-names-the-first", "feature-a, local" in second.stdout, True)
t1 = float(re.search(r"took (\S+)", first_out).group(1))
t2 = float(re.search(r"took (\S+)", second.stdout).group(1))
check("second-starts-after-the-first", t2 - t1 >= 1.0, True)
check("holder-note-gone", os.path.exists(lock + ".holder"), False)

# The same shell takes the queue again right after giving it up, as a stage
# run again after a red run does: nobody else holds it, so nobody is named.
again = subprocess.run(["bash", "-c", """
source "%s/core/lock.sh"
warn() { echo "WARN $*"; }; info() { echo "INFO $*"; }
lock_take fd "%s" "feature-a, local" "a regression"
echo "took ${fd:-nothing}"
lock_release "$fd" "%s"
lock_take fd "%s" "feature-a, local" "a regression"
echo "took ${fd:-nothing}"
lock_release "$fd" "%s"
""" % (LIB, lock, lock, lock, lock)], capture_output=True, text=True, timeout=30)
check("retake-takes-twice", len(re.findall(r"^took \d+$", again.stdout, re.M)), 2)
check("retake-says-nothing", again.stdout.replace("took", "").strip(" \n0123456789"), "")

# --- the reset in a review log -------------------------------------------------
now = datetime.datetime(2026, 10, 6, 17, 5, tzinfo=datetime.timezone.utc)
check("reset-today", ctx.quota_reset("hit your session limit · resets 6:50pm (Europe/Lisbon)", now),
      1791309000)
check("reset-tomorrow", ctx.quota_reset("resets 4am (Europe/Lisbon)", now), 1791342000)
check("reset-dated", ctx.quota_reset("resets Oct 10, 4am (Europe/Lisbon)", now), 1791601200)
check("reset-unreadable", ctx.quota_reset("no reset here", now), 0)
check("quota-in-log", bool(ctx.QUOTA_429.search('"api_error_status":429')), True)

# --- a review that could not run on GitHub -------------------------------------
# Claude's limit in the log, an API key's credit, or a job GitHub never started
# for the account's minutes — said only in the check run's annotations.
saved = (ctx.gh_json, ctx.job_log)
rollup = {"statusCheckRollup": [{"name": "claude-review", "workflowName": "Claude Code Review",
                                 "conclusion": "FAILURE", "completedAt": "2026-10-06T17:05:00Z",
                                 "detailsUrl": "https://github.com/o/r/actions/runs/7/job/9"}]}
def fake(annotations, log):
    ctx.gh_json = lambda args, cwd=None: annotations if "annotations" in args[1] else rollup
    ctx.job_log = lambda cwd, repo, job: log
fake([], 'is_error:true api_error_status:429 hit your session limit · resets 6:50pm (Europe/Lisbon)')
check("fallback-quota", ctx.review_fallback(None, 1, "o/r"), ("quota", 1791309000, "7"))
fake([], "Credit balance is too low")
check("fallback-credit", ctx.review_fallback(None, 1, "o/r"), ("quota", 0, "7"))
fake([{"message": "The job was not started because recent account payments have failed or your "
                  "spending limit needs to be increased."}], None)
check("fallback-minutes", ctx.review_fallback(None, 1, "o/r"), ("minutes", 0, "7"))
fake([], 'api_error_status:429 rate limited, try again')
check("fallback-bare-429-stays", ctx.review_fallback(None, 1, "o/r"), None)
fake([], 'api_error_status: 429 · resets 12pm (UTC)')
check("fallback-429-with-reset", ctx.review_fallback(None, 1, "o/r")[0], "quota")
fake([], "W: Failed to fetch InRelease  Temporary failure resolving 'azure.archive.ubuntu.com'\n"
         "E: Unable to fetch some archives, maybe run apt-get update")
check("fallback-runner", ctx.review_fallback(None, 1, "o/r"), ("runner", 0, "7"))
fake([], "W: Failed to fetch InRelease  Temporary failure resolving 'x'\nCould not resolve host: example.com\n"
         "TypeError: the code is wrong")
check("fallback-network-words-in-a-red-job-stay", ctx.review_fallback(None, 1, "o/r"), None)
fake([], "TypeError: the code is wrong")
check("fallback-code-red", ctx.review_fallback(None, 1, "o/r"), None)
ctx.gh_json, ctx.job_log = saved

# The gate waits for the review on the head (review_finished): a finished
# green review with its findings check run is finished; one still running,
# or with its findings check not run yet, is not; a failed one is finished
# at once (its red is the gate's); nothing on the head, in a pull request
# that had a review, is not; unreadable is finished.
saved = (ctx.reviewed_before, ctx.findings_run)
green = {"name": "claude-review", "workflowName": "Claude Code Review", "status": "COMPLETED",
         "conclusion": "SUCCESS"}
ctx.reviewed_before = lambda cwd, pr, repo: (True, True)
ctx.findings_run = lambda cwd, repo, head: {"status": "completed"}
check("review-finished-green", ctx.review_finished(None, 1, "o/r", "h", [green]), True)
ctx.findings_run = lambda cwd, repo, head: {}
check("review-finished-awaits-findings", ctx.review_finished(None, 1, "o/r", "h", [green]), False)
check("review-finished-running", ctx.review_finished(None, 1, "o/r", "h",
                                                     [dict(green, status="IN_PROGRESS", conclusion="")]), False)
check("review-finished-failed", ctx.review_finished(None, 1, "o/r", "h", [dict(green, conclusion="FAILURE")]), True)
check("review-finished-not-cancelled", ctx.review_finished(None, 1, "o/r", "h",
                                                           [dict(green, conclusion="CANCELLED")]), False)
check("review-finished-red-not-failed", ctx.review_finished(None, 1, "o/r", "h",
                                                            [dict(green, conclusion="ACTION_REQUIRED")]), True)
cancelled = dict(green, conclusion="CANCELLED", startedAt="2026-11-10T10:00:00Z")
green = dict(green, startedAt="2026-11-10T10:05:00Z")
check("superseded-by-green", ctx.superseded([cancelled, green]), [green])
check("superseded-by-skipped", ctx.superseded([cancelled, dict(green, conclusion="SKIPPED")]),
      [dict(green, conclusion="SKIPPED")])
check("two-cancelled-stay", len(ctx.superseded([cancelled, dict(cancelled)])), 2)
check("cancelled-newer-than-green-stays",
      len(ctx.superseded([dict(cancelled, startedAt="2026-11-10T10:09:00Z"), green])), 2)
check("cancelled-without-start-stays", len(ctx.superseded([dict(cancelled, startedAt=None), green])), 2)
check("cancelled-zero-start-stays",
      len(ctx.superseded([dict(cancelled, startedAt="0001-01-01T00:00:00Z"), green])), 2)
check("other-workflow-not-superseding",
      len(ctx.superseded([cancelled, dict(green, workflowName="CI")])), 2)
check("review-finished-not-on-head", ctx.review_finished(None, 1, "o/r", "h", []), False)
ctx.reviewed_before = lambda cwd, pr, repo: None
check("review-finished-unreadable", ctx.review_finished(None, 1, "o/r", "h", []), True)
ctx.reviewed_before, ctx.findings_run = saved

# The mark in a feature's tree makes `github-local` local, on both sides;
# `github` alone, `off` and `local` stay what they are.
fb = tempfile.mkdtemp()
subprocess.run(["git", "init", "-q", fb], check=True)
os.makedirs(os.path.join(fb, ".sclaude", "local", "feature"))
def review_config(path, word):
    with open(os.path.join(path, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": word}, fh)
    ctx._MODES.clear()
    ctx._TOPS.clear()
def shell_mode(path):
    return subprocess.run(["bash", "-c", 'source "%s/core/project.sh"; REPO="%s" project_review_mode "%s"'
                           % (LIB, path, path)], capture_output=True, text=True, timeout=30).stdout.strip()
review_config(fb, "github-local")
check("mode-github-local-no-mark", ctx.review_mode(fb), "github")
with open(os.path.join(fb, ctx.FALLBACK_FILE), "w") as fh:
    fh.write("quota\tnow\tseen\n")
review_config(fb, "github-local")
check("mode-mark-local", ctx.review_mode(fb), "local")
check("moved-for", ctx.moved_for(fb), "quota")
check("shell-mode-mark-local", shell_mode(fb), "local")
review_config(fb, "github")
check("mode-github-ignores-mark", (ctx.review_mode(fb), shell_mode(fb)), ("github", "github"))
review_config(fb, "off")
check("mode-mark-keeps-off", ctx.review_mode(fb), "off")
review_config(fb, "github-local")

# Moved for Claude's limit alone, only the review's checks leave the verdict;
# moved for the minutes, every Actions check does.
ci = {"name": "Checks", "workflowName": "CI", "conclusion": "FAILURE",
      "detailsUrl": "https://github.com/o/r/actions/runs/1/job/2"}
rv = {"name": "claude-review", "workflowName": "Claude Code Review", "conclusion": "FAILURE",
      "detailsUrl": "https://github.com/o/r/actions/runs/1/job/3"}
mention = {"name": "claude", "workflowName": "Claude Code", "conclusion": "FAILURE"}
schema = {"name": "Schema review", "workflowName": "CI", "conclusion": "FAILURE"}
check("quota-keeps-ci", [c["name"] for c in ctx.verdict_rollup(fb, [ci, rv, mention, schema])],
      ["Checks", "Schema review"])
with open(os.path.join(fb, ctx.FALLBACK_FILE), "w") as fh:
    fh.write("minutes\tnow\tseen\n")
review_config(fb, "github-local")
check("minutes-drops-actions", ctx.verdict_rollup(fb, [ci, rv]), [])
os.remove(os.path.join(fb, ctx.FALLBACK_FILE))
review_config(fb, "github-local")

# Switched once, the machine is marked: the next github-local feature
# reaching step 4 in the window is reviewed here at once; past it, it tries
# GitHub again. A later, shorter window does not shorten it; a reset that
# has passed marks nothing.
other = tempfile.mkdtemp()
subprocess.run(["git", "init", "-q", other], check=True)
os.makedirs(os.path.join(other, ".sclaude"))
review_config(other, "github-local")
inherit = """
source "%s/core/project.sh"; source "%s/review/review_round.sh"
info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }
REPO="%s"
review_fallback_set "%s" quota 0
cut -f2 "$REPO/.sclaude/local/review-fallback"
review_fallback_inherit "%s"
project_review_mode "%s"
""" % (LIB, LIB, fb, fb, other, other)
got = subprocess.run(["bash", "-c", inherit], capture_output=True, text=True, timeout=30).stdout
check("fallback-machine-mark", "quota" in got.splitlines()[0], True)
check("fallback-inherited", got.strip().splitlines()[-1], "local")
with open(os.path.join(other, ctx.FALLBACK_FILE)) as fh:
    check("fallback-inherited-says-so", fh.read().strip().endswith("inherited"), True)
os.remove(os.path.join(other, ".sclaude", "local", "feature", "review-fallback"))
mark = os.path.join(fb, ".sclaude", "local", "review-fallback")
far = int(time.time()) + 20 * 3600
with open(mark, "w") as fh:
    fh.write("%d\tminutes\n" % far)
subprocess.run(["bash", "-c", 'source "%s/review/review_round.sh"; REPO="%s"; review_fallback_set "%s" quota %d'
                % (LIB, fb, fb, int(time.time()) + 600)], timeout=30)
with open(mark) as fh:
    check("fallback-longer-window-kept", fh.read(), "%d\tminutes\n" % far)
os.remove(mark)
subprocess.run(["bash", "-c", 'source "%s/review/review_round.sh"; REPO="%s"; review_fallback_set "%s" quota %d'
                % (LIB, fb, fb, int(time.time()) - 600)], timeout=30)
check("fallback-past-reset-no-mark", os.path.exists(mark), False)
# A runner without network holds the machine off GitHub for an hour, not a day.
subprocess.run(["bash", "-c", 'source "%s/review/review_round.sh"; REPO="%s"; review_fallback_set "%s" runner'
                % (LIB, fb, fb)], timeout=30)
with open(mark) as fh:
    until, why = fh.read().split()
check("fallback-runner-an-hour", (why, abs(int(until) - time.time() - 3600) < 60), ("runner", True))
os.remove(mark)
# A reset already passed neither moves nor stops: the job is run again; a
# rerun GitHub refuses leaves the red to the stop or the move.
def rerun(refused, ago=600):
    return subprocess.run(["bash", "-c", 'source "%s/review/review_round.sh"; LIB="%s"; MERGE_POLL=0\n'
                           'info() { :; }\npython3() { echo "quota %d 7"; }\n'
                           'gh() { [[ "$2" == view ]] && { echo completed; return 0; }; echo RERUN >&3; return %d; }\nexec 3>&1\n'
                           'review_reset_rerun "$PWD" 1 o/r; echo "rc=$?"'
                           % (LIB, LIB, int(time.time()) - ago, 1 if refused else 0)],
                          capture_output=True, text=True, timeout=60).stdout.split()
check("fallback-past-reset-reruns", rerun(False), ["RERUN", "rc=0"])
check("fallback-refused-rerun-falls-through", rerun(True), ["RERUN", "rc=1"])
with open(os.path.join(fb, ".sclaude", "local", "review-fallback"), "w") as fh:
    fh.write("1\tquota\n")
got = subprocess.run(["bash", "-c", inherit.replace('review_fallback_set "%s" quota 0\n' % fb, "")],
                     capture_output=True, text=True, timeout=30).stdout
check("fallback-expired-github", got.strip().splitlines()[-1], "github")

# --- the person's threads ------------------------------------------------------
A = "https://github.com/o/r/pull/1#discussion_r1"
B = "https://github.com/o/r/pull/1#discussion_r2"
with open(os.path.join(wt, ".sclaude/local/feature", "review-yours"), "w") as fh:
    fh.write("%s\tleave as it is: the fix would undo d60ca78\n" % A)
check("yours-read", ctx.yours(wt), {A: "leave as it is: the fix would undo d60ca78"})

# A decision a night session took is the person's to confirm in the morning:
# only the open threads whose decision carries NIGHT_MARK are counted.
C = "https://github.com/o/r/pull/1#discussion_r3"
with open(os.path.join(wt, ".sclaude/local/feature", "review-yours"), "a") as fh:
    fh.write("%s\tleave as it is %s; no reply posted)\n" % (B, ctx.NIGHT_MARK))
    fh.write("%s\tleave as it is %s; no reply posted)\n" % (C, ctx.NIGHT_MARK))
saved_open = ctx.open_threads
ctx.open_threads = lambda cwd, pr, repo, nodes=None: ([
    {"path": "a.tsx", "line": 1, "url": u} for u in (A, B)], [])
check("night-yours-counts-open-night-decisions-only", ctx.night_yours(wt, "1", "o/r"), 1)
ctx.open_threads = saved_open
with open(os.path.join(wt, ".sclaude/local/feature", "review-yours"), "w") as fh:
    fh.write("%s\tleave as it is: the fix would undo d60ca78\n" % A)


def thread(url, path="a.tsx"):
    return {"path": path, "line": 1, "outdated": False, "created": "", "url": url,
            "comments": [{"author": "claude", "body": "**A finding.** More."}]}


rollup = [{"name": "build", "conclusion": "SUCCESS", "status": "COMPLETED"},
          {"name": ctx.FINDINGS_CHECK, "conclusion": "FAILURE", "status": "COMPLETED"}]


def close_with(threads, title, summary):
    ctx.open_threads = lambda cwd, pr, repo: (threads, [])
    ctx.unpushed = lambda cwd, view: 0

    def fake(args, cwd=None):
        if args[:2] == ["pr", "view"]:
            return {"state": "OPEN", "headRefOid": "abc", "statusCheckRollup": rollup,
                    "createdAt": "2026-01-01T00:00:00Z"}
        return {"check_runs": [{"name": ctx.FINDINGS_CHECK,
                                "output": {"title": title, "summary": summary}}]}
    ctx.gh_json = fake
    return ctx.close_state(wt, 1, "o/r")


both = "- [`a.tsx:1`](%s) — x\n- [`b.tsx:2`](%s) — y\n" % (A, B)
check("only-yours-open", close_with([thread(A)], "2 unresolved review findings in the whole PR", both),
      "yours: 1")
check("yours-and-another",
      close_with([thread(A), thread(B)], "2 unresolved review findings in the whole PR", both),
      "open: red: %s; 1 review thread(s) open" % ctx.FINDINGS_CHECK)
check("all-resolved-by-hand", close_with([], "2 unresolved review findings in the whole PR", both), "ok")
check("unthreaded-findings-stay-red",
      close_with([], "2 review findings posted as a comment, not as threads", ""),
      "open: red: %s" % ctx.FINDINGS_CHECK)
check("count-short-of-links-stays-red",
      close_with([], "3 unresolved review findings in the whole PR", both),
      "open: red: %s" % ctx.FINDINGS_CHECK)

# The snapshot lists the person's thread apart, with its decision, and the
# rest with their links.
ctx.open_threads = lambda cwd, pr, repo: ([thread(A), thread(B, "b.tsx")], [])
ctx.gh_json = lambda args, cwd=None: {"statusCheckRollup": [], "comments": []}
snap = ctx.render(wt, 1, "o/r")
check("snapshot-names-yours-apart", "Left as they are by the person" in snap, True)
check("snapshot-gives-the-decision", "the fix would undo d60ca78" in snap, True)
check("snapshot-links-the-rest", B in snap, True)
check("yours-not-in-the-work-list", snap.count("**A finding.**"), 1)
check("open-since-skips-yours", ctx.open_since(wt, 1, "o/r", ""), (1, 0))
# A night decision stays the person's until they take it back; taken back
# (night_take), the thread is open work again with the night's proposal beside
# it, to be asked about.
yours_path = os.path.join(wt, ".sclaude/local/feature", "review-yours")
with open(yours_path, "a") as fh:
    fh.write("%s\tleave it %s; no reply posted)\n" % (B, ctx.NIGHT_MARK))
check("night-decision-still-the-persons", B in ctx.yours(wt), True)
snap = ctx.render(wt, 1, "o/r")
kept_part = snap.split("**Left as they are by the person", 1)[-1]
check("snapshot-lists-night-proposals-apart",
      ("**Left at night for the person to confirm.**" in snap, B in kept_part, A in kept_part),
      (True, False, True))
check("night-take-moves-the-night-lines", ctx.night_take(wt), 1)
check("night-take-leaves-the-persons-own", (list(ctx.yours(wt)), list(ctx.night(wt))), ([A], [B]))
snap = ctx.render(wt, 1, "o/r")
check("snapshot-asks-about-a-taken-back-thread",
      ("Left at night for the person to confirm** — a night session proposed: leave it" in snap,
       snap.count("**A finding.**")), (True, 1))
check("night-take-again-moves-nothing", ctx.night_take(wt), 0)
os.remove(os.path.join(wt, ctx.NIGHT_FILE))
with open(yours_path, "w") as fh:
    fh.write("%s\tleave as it is: the fix would undo d60ca78\n" % A)

# --- the prompts ---------------------------------------------------------------
PROMPTS = os.path.join(LIB, "..", "prompts")
report = open(os.path.join(PROMPTS, "_report.md")).read()
check("report-keeps-a-proposal-open", "A proposal keeps the session open" in report, True)
review = open(os.path.join(PROMPTS, "review.md")).read()
check("review-writes-yours", ".sclaude/local/feature/review-yours" in review, True)
check("review-says-resolve-yourself", "Resolve on GitHub yourself" in review, True)
check("yours-file-name-agrees", ctx.YOURS_FILE in review, True)
# The night mark is written by the prompt and counted by review_night_offer.
check("night-mark-agrees", ctx.NIGHT_MARK in review, True)
check("night-file-agrees", ctx.NIGHT_FILE.rsplit("/", 1)[-1] in review, True)
check("night-heading-agrees", "Left at night for the person to confirm" in review
      and "Left at night for the person to confirm" in open(os.path.join(LIB, "review", "pr_context.py")).read(), True)
check("snapshot-names-the-prompt-paragraph", "the threads left at night" in review, True)
check("night-offer-asks-before-the-wait",
      "--night-yours" in open(os.path.join(LIB, "review", "review_gate.sh")).read(), True)
# A thread left as it is is proposed in so many words and, on a yes, resolved
# by the session itself; review-yours is for the person's own hand only.
check("review-proposes-resolving", "I want to resolve this comment on GitHub" in review, True)
check("review-resolves-on-yes", "resolveReviewThread" in review, True)
# A finding on a deferred file goes to review-yours, never to a fix: the prompt
# names the folders deferred.sh treats as entries, and only those.
deferred_sh = open(os.path.join(LIB, "improve", "deferred.sh")).read()
for folder in (".sclaude/team/deferred/", ".sclaude/people/*/deferred/"):
    check("review-names-" + folder, folder in review and "(glob)%s**" % folder in deferred_sh, True)
body = open(os.path.join(PROMPTS, "_friction-body.md")).read()
check("friction-may-fix-the-project", "<worktree>" in body and "<branch>" in body, True)
# The review runs in the feature's tree, with sclaude's checkout added to read.
check("friction-runs-in-the-worktree", RUN.count('( cd "$where" && claude_launch'), 2)
check("friction-reads-sclaude", RUN.count('--add-dir "$INSTRUMENTS" \\'), 2)

# --- what rides along to production -------------------------------------------
repo = os.path.join(tmp, "riders")
os.makedirs(os.path.join(repo, "supabase", "migrations"))


def g(*args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                          env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                                   GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@b",
                                   GIT_COMMITTER_NAME="a", GIT_COMMITTER_EMAIL="a@b")).stdout.strip()


def merge_feature(branch, pr, migration=None):
    g("checkout", "-q", "-b", branch, "main")
    name = migration or (branch.replace("/", "-") + ".txt")
    path = os.path.join(repo, "supabase", "migrations", name) if migration else os.path.join(repo, name)
    open(path, "w").write("x\n")
    g("add", "-A")
    g("commit", "-qm", "work on " + branch)
    g("checkout", "-q", "main")
    g("merge", "-q", "--no-ff", branch, "-m", "Merge pull request #%d from o/%s" % (pr, branch))


g("init", "-q", "-b", "main")
open(os.path.join(repo, "README"), "w").write("r\n")
g("add", "-A")
g("commit", "-qm", "start")
prod = g("rev-parse", "HEAD")
merge_feature("feat/40-alpha", 901, "0084_a.sql")
open(os.path.join(repo, "hotfix"), "w").write("h\n")
g("add", "-A")
g("commit", "-qm", "fix: a hotfix straight on main")
g("commit", "-q", "--allow-empty", "-m", "chore(db): promote migrations for 40-alpha")
merge_feature("feat/41-beta", 902, "0085_b.sql")
out = subprocess.run([sys.executable, os.path.join(LIB, "ship", "prod_riders.py"), repo, prod, "main",
                      "41-beta", "supabase/migrations"],
                     capture_output=True, text=True, env=dict(os.environ, PATH="/usr/bin:/bin")).stdout
lines = out.strip().splitlines()
check("riders-name-the-other-feature",
      [l.split("\t")[:3] + l.split("\t")[4:] for l in lines if l.startswith("feature")],
      [["feature", "901", "40", "0084_a.sql"]])
check("riders-leave-out-the-feature-shipped", any("\t161\t" in l for l in lines), False)
check("riders-name-a-direct-commit",
      [l.split("\t")[2] for l in lines if l.startswith("commit")], ["fix: a hotfix straight on main"])
check("riders-skip-promote-commits", "promote" in out, False)

# Squashed merges are features too, the one shipped among them; and commits
# the caller names (deferred entries alone) are left out.
open(os.path.join(repo, "squash-own"), "w").write("s\n")
g("add", "-A")
g("commit", "-qm", "feat(x): the feature being shipped (#903)")
own_squash = g("rev-parse", "HEAD")
# gh, as GitHub answers: the pull request merged as that very commit.
gh_bin = os.path.join(tmp, "gh-bin")
os.makedirs(gh_bin, exist_ok=True)
with open(os.path.join(gh_bin, "gh"), "w") as fh:
    fh.write("#!/bin/sh\necho '%s'\n" % json.dumps(
        [{"number": 903, "headRefName": "feat/41-beta", "closingIssuesReferences": [],
          "mergeCommit": {"oid": own_squash}}]))
os.chmod(os.path.join(gh_bin, "gh"), 0o755)
open(os.path.join(repo, "deferred.tsv"), "w").write("d\n")
g("add", "-A")
g("commit", "-qm", "chore(sclaude): put off 1 proposal")
skip_file = os.path.join(tmp, "riders-skip")
open(skip_file, "w").write(g("rev-parse", "HEAD") + "\n")
out = subprocess.run([sys.executable, os.path.join(LIB, "ship", "prod_riders.py"), repo, prod, "main",
                      "41-beta", "supabase/migrations", "903", skip_file],
                     capture_output=True, text=True,
                     env=dict(os.environ, PATH=gh_bin + ":/usr/bin:/bin")).stdout
check("riders-own-squash-left-out", "(#903)" in out, False)
check("riders-named-commits-left-out", "put off" in out, False)
check("riders-still-name-the-hotfix", "fix: a hotfix straight on main" in out, True)
# A "(#N)" gh cannot confirm as a pull request is a commit, its fields whole.
open(os.path.join(repo, "issue-ref"), "w").write("i\n")
g("add", "-A")
g("commit", "-qm", "fix: typo in the footer (#77)")
git_only = os.path.join(tmp, "git-only")
os.makedirs(git_only, exist_ok=True)
os.symlink(shutil.which("git"), os.path.join(git_only, "git"))
out = subprocess.run([sys.executable, os.path.join(LIB, "ship", "prod_riders.py"), repo, prod, "main",
                      "41-beta", "supabase/migrations", "903"],
                     capture_output=True, text=True, env=dict(os.environ, PATH=git_only)).stdout
check("riders-unconfirmed-squash-is-a-commit",
      any(l.startswith("commit\t") and l.endswith("(#77)") for l in out.splitlines()), True)
check("riders-no-empty-field", all("\t\t" not in l for l in out.splitlines()), True)
# A commit pushed straight to main that cites the shipped pull request is no
# merge of it: it rides along, and is said.
open(os.path.join(repo, "follow-up"), "w").write("f\n")
g("add", "-A")
g("commit", "-qm", "fix: a follow-up to the feature (#903)")
out = subprocess.run([sys.executable, os.path.join(LIB, "ship", "prod_riders.py"), repo, prod, "main",
                      "41-beta", "supabase/migrations", "903"],
                     capture_output=True, text=True,
                     env=dict(os.environ, PATH=gh_bin + ":/usr/bin:/bin")).stdout
# gh unable to say: the shipped one's squash is still left out by its number.
out_no_gh = subprocess.run([sys.executable, os.path.join(LIB, "ship", "prod_riders.py"), repo, prod, "main",
                            "41-beta", "supabase/migrations", "903"],
                           capture_output=True, text=True, env=dict(os.environ, PATH=git_only)).stdout
check("riders-own-squash-left-out-without-gh",
      any("the feature being shipped" in l for l in out_no_gh.splitlines()), False)
check("riders-a-commit-citing-the-shipped-pr-is-said",
      any(l.startswith("commit\t") and "follow-up" in l for l in out.splitlines()), True)

# --- the deferred friction ----------------------------------------------------
#
# The files are the product's, one per rules folder (deferred.sh): a
# maintainer's review reads them all, anybody else's their own.
product = os.path.join(tmp, "deferred-product")
subprocess.run(["git", "init", "-q", product], check=True)
subprocess.run(["git", "-C", product, "config", "user.email", "ann@x.test"], check=True)


def deferred_sh(script, dev="ann"):
    body = ('INSTRUMENTS="%s"; for m in core/developer improve/deferred; do source "%s/$m.sh"; done\n%s'
            % (ROOT, LIB, script))
    return subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                          env=dict(os.environ, SCLAUDE_DEV=dev))


def put(rel, text):
    path = os.path.join(product, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def due():
    done = deferred_sh('deferred_due "%s"' % product)
    return done.stdout.strip() if done.returncode == 0 else None


old_day = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
today = datetime.date.today().isoformat()
entry = "%s\tmyapp\t52-x\treview\tclaude-md-stale-docs\tProposal: grep the docs.\n" % old_day
put(".sclaude/team/deferred/52-x.tsv", "# header\n" + entry)
check("deferred-due-after-a-month-unreviewed", due(), "1 %s" % old_day)
put(".sclaude/team/deferred/last-reviewed", today + "\n")
check("deferred-not-due-when-reviewed-today", due(), None)
os.remove(os.path.join(product, ".sclaude", "team", "deferred", "last-reviewed"))
put(".sclaude/team/deferred/52-x.tsv", "# header\n")
check("deferred-not-due-when-empty", due(), None)
# A maintainer counts everybody's folders; somebody else only their own.
put(".sclaude/people/bob/deferred/7-y.tsv", entry)
check("deferred-maintainer-reads-people", due(), "1 %s" % old_day)
with open(_cfg(os.path.join(product, ".sclaude/config.json")), "w") as fh:
    json.dump({"maintainers": ["lead@x.test"]}, fh)
check("deferred-others-read-their-own", due(), None)
check("deferred-file-is-the-persons-per-feature",
      deferred_sh('deferred_file "%s" 9-z' % product).stdout.strip(),
      os.path.join(product, ".sclaude", "people", "ann", "deferred", "9-z.tsv"))
deferred_sh('deferred_ensure "%s" 9-z' % product)
with open(os.path.join(product, ".sclaude", "people", "ann", "deferred", "9-z.tsv")) as fh:
    check("deferred-file-starts-empty", fh.read(), "")
check("deferred-file-not-in-instruments",
      os.path.exists(os.path.join(ROOT, "sclaude", "friction-deferred.tsv")), False)

friction_note = open(os.path.join(PROMPTS, "_friction.md")).read()
# The shape friction_proposals.py reads, so a log of proposals alone is put
# off without a session.
check("steps-log-proposals", "proposal (<class>):" in friction_note, True)
check("review-logs-its-rule", "into `.sclaude/local/feature/friction.log` as a proposal" in review, True)
check("friction-may-defer", "<deferred>" in body, True)
check("steps-told-the-deferred-path", "<deferred>" in friction_note, True)
check("verdict-knows-deferred", '"deferred"' in open(os.path.join(LIB, "core", "state.sh")).read(), True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    print("\n%d failed" % len(failures))
    sys.exit(1)
print("all passed")
