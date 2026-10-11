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
#   * lock_take makes a second holder wait for the first;
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
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIB, name + ".py"))
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
with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()


def functions(source, names):
    out = []
    for name in names:
        m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
        check("function-present-" + name, bool(m), True)
        if m:
            out.append(m.group(0))
    return "\n".join(out)


WATCH = 'source "%s/state.sh"\nLIB="%s"\n' % (LIB, LIB) + functions(
    RUN, ["round_marker", "done_marker", "session_watch_start", "session_watch_stop"])

wt = os.path.join(tmp, "wt")
os.makedirs(os.path.join(wt, ".feature"))
home = os.path.join(tmp, "home")
tdir = os.path.join(home, ".claude", "projects", re.sub(r"[^a-zA-Z0-9]", "-", wt))
os.makedirs(tdir)
session = "0f1e2d3c-aaaa-bbbb-cccc-00000000beef"
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
sleep %s
session_watch_stop
""" % (home, tmp, wt, session, wait)
    subprocess.run(["bash", "-c", script], timeout=30)
    time.sleep(0.2)
    closed = target.poll() is not None
    target.kill()
    return closed


check("reset-limit-closes-the-session", watch(int(time.time()) - 10), True)
check("reset-limit-tells-claude-launch", os.path.exists(limit_file), True)
os.remove(limit_file)
check("limit-not-yet-reset-leaves-it", watch(int(time.time()) + 3600), False)
check("no-word-before-the-reset", os.path.exists(limit_file), False)
check("limit-from-before-the-reopening-left-alone", watch(int(time.time()) - 10, offset=-60), False)
check("no-word-for-an-old-limit", os.path.exists(limit_file), False)

# --- claude_launch opens it again ----------------------------------------------
script = """
source "%s/pane.sh"
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
""" % (LIB, tmp, tmp, session, session)
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
source "%s/lock.sh"
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

# --- the reset in a review log -------------------------------------------------
now = datetime.datetime(2026, 10, 6, 17, 5, tzinfo=datetime.timezone.utc)
check("reset-today", ctx.quota_reset("hit your session limit · resets 6:50pm (Europe/Lisbon)", now),
      1791309000)
check("reset-tomorrow", ctx.quota_reset("resets 4am (Europe/Lisbon)", now), 1791342000)
check("reset-dated", ctx.quota_reset("resets Oct 10, 4am (Europe/Lisbon)", now), 1791601200)
check("reset-unreadable", ctx.quota_reset("no reset here", now), 0)
check("quota-in-log", bool(ctx.QUOTA_429.search('"api_error_status":429')), True)

# --- the person's threads ------------------------------------------------------
A = "https://github.com/o/r/pull/1#discussion_r1"
B = "https://github.com/o/r/pull/1#discussion_r2"
with open(os.path.join(wt, ".feature", "review-yours"), "w") as fh:
    fh.write("%s\tleave as it is: the fix would undo d60ca78\n" % A)
check("yours-read", ctx.yours(wt), {A: "leave as it is: the fix would undo d60ca78"})


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

# --- the prompts ---------------------------------------------------------------
PROMPTS = os.path.join(LIB, "..", "prompts")
report = open(os.path.join(PROMPTS, "_report.md")).read()
check("report-keeps-a-proposal-open", "A proposal keeps the session open" in report, True)
review = open(os.path.join(PROMPTS, "review.md")).read()
check("review-writes-yours", ".feature/review-yours" in review, True)
check("review-says-resolve-yourself", "Resolve on GitHub yourself" in review, True)
check("yours-file-name-agrees", ctx.YOURS_FILE in review, True)
body = open(os.path.join(PROMPTS, "_friction-body.md")).read()
check("friction-may-fix-the-project", "<worktree>" in body and "<branch>" in body, True)
check("friction-gets-the-worktree", RUN.count('--add-dir "$wt"'), 2)

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
merge_feature("feat/150-categories", 159, "0084_a.sql")
open(os.path.join(repo, "hotfix"), "w").write("h\n")
g("add", "-A")
g("commit", "-qm", "fix: a hotfix straight on main")
g("commit", "-q", "--allow-empty", "-m", "chore(db): promote migrations for 150-categories")
merge_feature("feat/152-profile", 161, "0085_b.sql")
out = subprocess.run([sys.executable, os.path.join(LIB, "prod_riders.py"), repo, prod, "main",
                      "152-profile", "supabase/migrations"],
                     capture_output=True, text=True, env=dict(os.environ, PATH="/usr/bin:/bin")).stdout
lines = out.strip().splitlines()
check("riders-name-the-other-feature",
      [l.split("\t")[:3] + l.split("\t")[4:] for l in lines if l.startswith("feature")],
      [["feature", "159", "150", "0084_a.sql"]])
check("riders-leave-out-the-feature-shipped", any("\t161\t" in l for l in lines), False)
check("riders-name-a-direct-commit",
      [l.split("\t")[2] for l in lines if l.startswith("commit")], ["fix: a hotfix straight on main"])
check("riders-skip-promote-commits", "promote" in out, False)

# --- the deferred friction ----------------------------------------------------
#
# The files are the product's, one per rules folder (deferred.sh): a
# maintainer's review reads them all, anybody else's their own.
product = os.path.join(tmp, "deferred-product")
subprocess.run(["git", "init", "-q", product], check=True)
subprocess.run(["git", "-C", product, "config", "user.email", "ann@x.test"], check=True)


def deferred_sh(script, dev="ann"):
    body = ('INSTRUMENTS="%s"; for m in developer deferred; do source "%s/$m.sh"; done\n%s'
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
entry = "%s\tmyapp\t152-x\treview\tclaude-md-stale-docs\tProposal: grep the docs.\n" % old_day
put(".sclaude/team/deferred/152-x.tsv", "# header\n" + entry)
check("deferred-due-after-a-month-unreviewed", due(), "1 %s" % old_day)
put(".sclaude/team/deferred/last-reviewed", today + "\n")
check("deferred-not-due-when-reviewed-today", due(), None)
os.remove(os.path.join(product, ".sclaude", "team", "deferred", "last-reviewed"))
put(".sclaude/team/deferred/152-x.tsv", "# header\n")
check("deferred-not-due-when-empty", due(), None)
# A maintainer counts everybody's folders; somebody else only their own.
put(".sclaude/people/bob/deferred/7-y.tsv", entry)
check("deferred-maintainer-reads-people", due(), "1 %s" % old_day)
with open(os.path.join(product, ".sclaude.json"), "w") as fh:
    json.dump({"maintainers": ["lead@x.test"]}, fh)
check("deferred-others-read-their-own", due(), None)
check("deferred-file-is-the-persons-per-feature",
      deferred_sh('deferred_file "%s" 9-z' % product).stdout.strip(),
      os.path.join(product, ".sclaude", "people", "ann", "deferred", "9-z.tsv"))
deferred_sh('deferred_ensure "%s" 9-z' % product)
with open(os.path.join(product, ".sclaude", "people", "ann", "deferred", "9-z.tsv")) as fh:
    check("deferred-file-starts-with-its-header", fh.readline().startswith("# Put off by sclaude"), True)
check("deferred-file-not-in-instruments",
      os.path.exists(os.path.join(ROOT, "sclaude", "friction-deferred.tsv")), False)

friction_note = open(os.path.join(PROMPTS, "_friction.md")).read()
# The shape friction_proposals.py reads, so a log of proposals alone is put
# off without a session.
check("steps-log-proposals", "proposal (<class>):" in friction_note, True)
check("review-logs-its-rule", "into `.feature/friction.log` as a proposal" in review, True)
check("friction-may-defer", "<deferred>" in body, True)
check("steps-told-the-deferred-path", "<deferred>" in friction_note, True)
check("verdict-knows-deferred", '"deferred"' in open(os.path.join(LIB, "state.sh")).read(), True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    print("\n%d failed" % len(failures))
    sys.exit(1)
print("all passed")
