#!/usr/bin/env python3
#
# The sync with main (sclaude/lib/sync.sh), on real repositories: an origin,
# its main, and a feature's branch in a clone of it.
#
#   * merge_conflicts says whether the branch merges with origin/main, and
#     names the files that would conflict, without merging;
#   * a conflict in the deferred logs alone is merged by sclaude itself —
#     main's rows, then the branch's — committed and pushed, with no session;
#   * any other conflict opens a session; the sync counts as done only when
#     the branch then merges cleanly and is pushed, and a session that left
#     it otherwise is a sync broken off;
#   * a merge under way here is never clean, and commits here that origin's
#     tip lacks are asked about with it;
#   * sync_gate takes back a hand-off for the merge whenever origin's branch
#     moved, even when the sync stopped short;
#   * merge_wait stops waiting once main moves into a conflict (3);
#   * a pull request merged before the feature came back (reopened_pr) is
#     not named: the branch is, unless GitHub says that number is open.
#
# Run it with: python3 tests/main-sync.py
import json
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failed = 0
LOG = ".sclaude/team/deferred/9-x.tsv"


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s: want %r, got %r" % (name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          check=True).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def commit(cwd, path, text, message):
    write(os.path.join(cwd, path), text)
    git(cwd, "add", path)
    git(cwd, "commit", "-q", "-m", message)


# Stand-ins for what a session needs and a test has none of: the session
# itself is CLAUDE_DOES, a shell line run in the worktree.
STUBS = r'''
BOLD=''; DIM=''; RED=''; GREEN=''; YELLOW=''; BLUE=''; OFF=''
warn() { echo "$*"; }
info() { echo "$*"; }
alarm() { echo "$*"; }
say() { echo "$*"; }
step_settings() { echo --strict-mcp-config; }
session_watch_start() { :; }
session_watch_stop() { :; }
session_started() { [[ -z "${NO_SESSION:-}" ]]; }
live_session() { return 1; }
dev_env_load() { :; }
render_prompt() { echo "prompt for $1"; }
ask_feed() { printf '%s\n' "$2" >> "$FEED"; }
session_closed() { rm -f "$1"; ask_feed say "$(phase_line finished sync "${7:-}")"; }
claude_launch() { echo "$*" > "$LAUNCHED"; bash -c "$CLAUDE_DOES"; }
# The friction review after the sync (run.sh): done, or with FRICTION_FAILS
# not finished.
run_friction() { [[ -z "${FRICTION_FAILS:-}" ]]; }
'''


def run(wt, script, **env):
    body = "set -uo pipefail\n" + "".join('source "%s/%s.sh"\n' % (LIB, m)
                                          for m in ("io", "ui", "steps", "state", "deferred", "sync")) \
        + STUBS + script
    e = dict(os.environ, **env)
    p = subprocess.run(["bash", "-c", body], cwd=wt, capture_output=True, text=True,
                       env=e, timeout=60, stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout


def setup(tmp, name):
    origin = os.path.join(tmp, name + "-origin.git")
    seed = os.path.join(tmp, name + "-seed")
    wt = os.path.join(tmp, name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, seed], check=True, capture_output=True)
    for d in (seed,):
        git(d, "config", "user.email", "t@example.com")
        git(d, "config", "user.name", "t")
    commit(seed, "app.txt", "one\ntwo\nthree\n", "seed")
    commit(seed, LOG, "row1\n", "seed log")
    git(seed, "push", "-q", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "-q", origin, wt], check=True, capture_output=True)
    git(wt, "config", "user.email", "t@example.com")
    git(wt, "config", "user.name", "t")
    git(wt, "checkout", "-q", "-b", "feat/9-x")
    git(wt, "push", "-q", "-u", "origin", "feat/9-x")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    write(os.path.join(wt, ".git/info/exclude"), ".sclaude/local/\n")
    with open(os.path.join(wt, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump({"feature": "9-x", "branch": "feat/9-x", "pr": 7, "issue": 9}, fh)
    return seed, wt


def pushed(wt):
    git(wt, "fetch", "-q", "origin")
    return git(wt, "rev-parse", "HEAD") == git(wt, "rev-parse", "origin/feat/9-x")


def sync_runs(wt):
    with open(os.path.join(wt, ".sclaude/local/feature/state.json")) as fh:
        return (json.load(fh).get("sync") or {}).get("runs") or []


with tempfile.TemporaryDirectory() as tmp:
    feed = os.path.join(tmp, "feed")
    launched = os.path.join(tmp, "launched")
    env = {"FEED": feed, "LAUNCHED": launched, "SELF": "sclaude", "CLAUDE_DOES": "true"}

    # Main moved elsewhere: the branch merges, nothing is done.
    seed, wt = setup(tmp, "clean")
    commit(seed, "other.txt", "x\n", "main moves")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nTWO\nthree\n", "feature")
    check("clean: merges", run(wt, 'merge_conflicts "$PWD"', **env), (0, ""))
    check("clean: no sync", run(wt, 'sync_with_main "$PWD" 9-x >/dev/null', **env)[0], 0)
    check("clean: no session", os.path.exists(launched), False)

    # Both sides wrote rows into one deferred log: merged by sclaude.
    seed, wt = setup(tmp, "logs")
    commit(seed, LOG, "row1\nrow-main\n", "main's row")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, LOG, "row1\nrow-branch\n", "branch's row")
    git(wt, "push", "-q")
    check("logs: the conflict is named", run(wt, 'merge_conflicts "$PWD"', **env), (1, LOG + "\n"))
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **env)
    check("logs: synced", rc, 3)
    check("logs: no session", os.path.exists(launched), False)
    with open(os.path.join(wt, LOG)) as fh:
        check("logs: both sides' rows, main's first", fh.read(), "row1\nrow-main\nrow-branch\n")
    check("logs: pushed", pushed(wt), True)
    check("logs: a merge commit", len(git(wt, "log", "-1", "--format=%P").split()), 2)
    check("logs: merges now", run(wt, 'merge_conflicts "$PWD"', **env)[0], 0)
    with open(feed) as fh:
        check("logs: the topic hears it", "🔀 Step 5/7 finished: sync with main" in fh.read(), True)

    # Its friction review not finished holds the run, as after a step.
    seed, wt = setup(tmp, "friction")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    resolve = ("git merge -q origin/main >/dev/null 2>&1; printf 'one\\nboth\\nthree\\n' > app.txt; "
               "git add app.txt; git commit -q --no-edit; git push -q origin feat/9-x; "
               "echo done > .sclaude/local/feature/session-done")
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **dict(env, CLAUDE_DOES=resolve, FRICTION_FAILS="1"))
    check("friction: an unfinished review stops the run", (rc, "waits for it" in out), (1, True))

    # A conflict in the code: a session merges, resolves, pushes.
    seed, wt = setup(tmp, "code")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    resolve = ("git merge -q origin/main >/dev/null 2>&1; printf 'one\\nboth\\nthree\\n' > app.txt; "
               "git add app.txt; git commit -q --no-edit; git push -q origin feat/9-x; "
               "echo done > .sclaude/local/feature/session-done")
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **dict(env, CLAUDE_DOES=resolve))
    check("code: synced", rc, 3)
    with open(launched) as fh:
        args = fh.read()
    check("code: the session is named 5-sync", "-n 5-sync/9-x" in args, True)
    check("code: with the sync prompt", "prompt for sync" in args, True)
    check("code: pushed", pushed(wt), True)
    runs = sync_runs(wt)
    check("code: one run, closed", [bool(r.get("done")) for r in runs], [True])
    check("code: not broken off", run(wt, 'sync_broken_off .sclaude/local/feature/state.json', **env)[0], 1)
    with open(feed) as fh:
        check("code: the start names the conflict",
              "🔀 Step 5/7 started: sync with main, session 1 · 1 file(s) conflict" in fh.read(), True)

    # The session gave up: still apart from main, the run stops, and the
    # sync stands broken off; the next one is session 2.
    commit(seed, "app.txt", "one\nmain again\nthree\n", "main again")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature again\nthree\n", "feature again")
    git(wt, "push", "-q")
    os.remove(launched)
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **env)
    check("gave up: stops", rc, 1)
    check("gave up: says so", "does not merge cleanly" in out, True)
    check("gave up: broken off", run(wt, 'sync_broken_off .sclaude/local/feature/state.json', **env)[0], 0)
    check("gave up: the second session", "-n 5-sync(2)/9-x" in open(launched).read(), True)

    # Pushed nothing: a merge resolved here only is not a sync.
    local_only = ("git merge -q origin/main >/dev/null 2>&1; printf 'one\\nboth\\nthree\\n' > app.txt; "
                  "git add app.txt; git commit -q --no-edit; echo done > .sclaude/local/feature/session-done")
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **dict(env, CLAUDE_DOES=local_only))
    check("unpushed: not done", rc, 1)

    # Resolved on GitHub ("Update branch", the conflict editor): origin's tip
    # of the branch merges, the tree's does not. That is no conflict; the
    # sync catches the tree up, and a sync left open before is over.
    seed, wt = setup(tmp, "github")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    other = os.path.join(tmp, "github-web")
    subprocess.run(["git", "clone", "-q", "-b", "feat/9-x", os.path.join(tmp, "github-origin.git"), other],
                   check=True, capture_output=True)
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    subprocess.run(["git", "-C", other, "merge", "-q", "origin/main"], capture_output=True)
    write(os.path.join(other, "app.txt"), "one\nboth\nthree\n")
    git(other, "commit", "-q", "-am", "resolved on GitHub")
    git(other, "push", "-q")
    with open(os.path.join(wt, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump({"feature": "9-x", "branch": "feat/9-x", "pr": 7, "step": "done",
                   "sync": {"runs": [{"session": "s1", "started": "x"}]}}, fh)
    check("github: merges, by origin's tip", run(wt, 'merge_conflicts "$PWD"', **env)[0], 0)
    check("github: no sync", run(wt, 'sync_with_main "$PWD" 9-x >/dev/null', **env)[0], 0)
    check("github: the open sync closed", [bool(r.get("done")) for r in sync_runs(wt)], [True])

    # Only the logs, on a branch origin does not have: merged, kept local.
    seed, wt = setup(tmp, "logs-local")
    git(wt, "push", "-q", "origin", "--delete", "feat/9-x")
    commit(seed, LOG, "row1\nrow-main\n", "main's row")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, LOG, "row1\nrow-branch\n", "branch's row")
    check("logs-local: synced", run(wt, 'sync_with_main "$PWD" 9-x >/dev/null', **env)[0], 3)
    check("logs-local: not published", git(wt, "ls-remote", "--heads", "origin", "feat/9-x"), "")

    # From the menu, before step 3: a branch origin does not have yet. The
    # sync merges it locally and counts as done without a push.
    seed, wt = setup(tmp, "local")
    git(wt, "push", "-q", "origin", "--delete", "feat/9-x")
    git(wt, "branch", "-q", "--unset-upstream")
    with open(os.path.join(wt, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump({"feature": "9-x", "branch": "feat/9-x", "pr": None, "issue": 9, "step": "code"}, fh)
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    local_merge = ("git merge -q origin/main >/dev/null 2>&1; printf 'one\\nboth\\nthree\\n' > app.txt; "
                   "git add app.txt; git commit -q --no-edit; echo done > .sclaude/local/feature/session-done")
    os.remove(launched)
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **dict(env, CLAUDE_DOES=local_merge))
    check("local: synced without a push", rc, 3)
    check("local: still not on origin", git(wt, "ls-remote", "--heads", "origin", "feat/9-x"), "")
    check("local: no PR to name", "The branch does not merge with main" in out, True)

    # Sent back after its merge (retro_reopen): the state still carries the
    # merged pull request until step 3 opens the next one. It is not named.
    seed, wt = setup(tmp, "reopened")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    # An executable rather than a function: the call runs under `timeout`.
    bindir = os.path.join(tmp, "reopened-bin")
    os.makedirs(bindir)
    write(os.path.join(bindir, "gh"), '#!/bin/bash\n'
          '[[ "$*" == "pr view 7 --repo o/r --json state --jq .state" ]] && echo "$GH_STATE"\n')
    os.chmod(os.path.join(bindir, "gh"), 0o755)
    stub_gh = 'gh_repo() { echo o/r; }; PATH="%s:$PATH"\n' % bindir
    # No answer from GitHub (no network) keeps the number, as before.
    for gh_state, named in (("MERGED", False), ("CLOSED", False), ("OPEN", True), ("", True)):
        with open(os.path.join(wt, ".sclaude/local/feature/state.json"), "w") as fh:
            json.dump({"feature": "9-x", "branch": "feat/9-x", "pr": 7, "reopened_pr": 7,
                       "issue": 9, "step": "pr"}, fh)
        rc, out = run(wt, stub_gh + 'sync_with_main "$PWD" 9-x', **dict(env, GH_STATE=gh_state, NO_SESSION="1"))
        check("reopened, %s: PR #7 named" % gh_state, "PR #7 does not merge with main" in out, named)
        check("reopened, %s: the branch named" % gh_state,
              "The branch does not merge with main" in out, not named)

    # The prompt, for a reviewed feature and for one still being built.
    def prompt(**values):
        e = dict(os.environ, **{"SCLAUDE_V_" + k.upper(): v for k, v in values.items()})
        p = subprocess.run(["python3", os.path.join(LIB, "render_prompt.py"),
                            os.path.join(LIB, "..", "prompts", "sync.md"),
                            os.path.join(LIB, "..", "prompts")],
                           capture_output=True, text=True, env=e, timeout=30)
        return p.returncode, p.stdout
    base = dict(feature="9-x", pr="7", issue="9", branch="feat/9-x", conflicts="app.txt")
    rc, text = prompt(reviewed="1", **base)
    check("prompt reviewed: renders", rc, 0)
    check("prompt reviewed: step 5, PR open", "step 5 of the cycle" in text and "pull request #7" in text, True)
    check("prompt reviewed: QA again", "QA again" in text, True)
    rc, text = prompt(unreviewed="1", **dict(base, pr="—"))
    check("prompt unreviewed: renders", rc, 0)
    check("prompt unreviewed: no PR, no QA", "pull request #" in text or "QA again" in text, False)
    check("prompt unreviewed: names the conflicts", "app.txt" in text, True)

    # A merge made here and never pushed: the pull request still conflicts,
    # so it is no "merges cleanly" — the sync pushes it, with no session.
    seed, wt = setup(tmp, "unpushed")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    git(wt, "fetch", "-q", "origin")
    subprocess.run(["git", "-C", wt, "merge", "-q", "origin/main"], capture_output=True)
    write(os.path.join(wt, "app.txt"), "one\nboth\nthree\n")
    git(wt, "commit", "-q", "-am", "merged here")
    check("unpushed: still a conflict for the pull request", run(wt, 'merge_conflicts "$PWD"', **env)[0], 1)
    if os.path.exists(launched):
        os.remove(launched)
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **env)
    check("unpushed: pushed", (rc, pushed(wt)), (3, True))
    check("unpushed: no session", os.path.exists(launched), False)

    # Apart both ways — a commit here and another on origin: no merge here,
    # since origin would refuse its push; the person is told what to do.
    seed, wt = setup(tmp, "apart")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    other = os.path.join(tmp, "apart-other")
    subprocess.run(["git", "clone", "-q", "-b", "feat/9-x", os.path.join(tmp, "apart-origin.git"), other],
                   check=True, capture_output=True)
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    commit(other, "elsewhere.txt", "x\n", "pushed from elsewhere")
    git(other, "push", "-q")
    commit(wt, "here.txt", "y\n", "made here")
    if os.path.exists(launched):
        os.remove(launched)
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **env)
    check("apart: stops", rc, 1)
    check("apart: says how", "pull --no-rebase" in out, True)
    check("apart: no session", os.path.exists(launched), False)

    # A merge under way here, while origin's tip merges cleanly: not clean —
    # the tree holds conflict markers — so the session finishes it.
    seed, wt = setup(tmp, "under-way")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change, not pushed")
    git(wt, "fetch", "-q", "origin")
    subprocess.run(["git", "-C", wt, "merge", "-q", "origin/main"], capture_output=True)
    if os.path.exists(launched):
        os.remove(launched)
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **env)
    check("under way: not clean", rc, 1)
    check("under way: a session took it", os.path.exists(launched), True)
    check("under way: names the unmerged file", "    app.txt" in out, True)
    # Resolved and not committed: nothing unmerged, said as such rather than
    # as a file in conflict.
    write(os.path.join(wt, "app.txt"), "one\nboth\nthree\n")
    git(wt, "add", "app.txt")
    os.remove(launched)
    rc, out = run(wt, 'sync_with_main "$PWD" 9-x', **env)
    check("resolved, uncommitted: not clean", rc, 1)
    check("resolved, uncommitted: a session took it", os.path.exists(launched), True)
    check("resolved, uncommitted: said in words", ("under way here" in out, "file(s) conflict" in out),
          (True, False))

    # Commits here that origin lacks conflict, origin's tip does not: they
    # are merged too by whoever merges here, so the conflict is named.
    seed, wt = setup(tmp, "ahead")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change, not pushed")
    check("ahead: the local commit conflicts", run(wt, 'merge_conflicts "$PWD"', **env), (1, "app.txt\n"))

    # The logs once more, after main removed rows the branch took from it at
    # an earlier merge (the monthly review removes what it decided): they
    # stay removed, and the branch's own new row comes in.
    seed, wt = setup(tmp, "removed")
    commit(seed, LOG, "row1\nrow-old\n", "main's row")
    git(seed, "push", "-q", "origin", "HEAD:main")
    git(wt, "fetch", "-q", "origin")
    git(wt, "merge", "-q", "--no-edit", "origin/main")
    git(wt, "push", "-q")
    commit(seed, LOG, "row1\nrow-main\n", "the review decided row-old")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, LOG, "row1\nrow-old\nrow-new\n", "branch's row")
    git(wt, "push", "-q")
    check("removed: a conflict in the log", run(wt, 'merge_conflicts "$PWD"', **env), (1, LOG + "\n"))
    check("removed: synced", run(wt, 'sync_with_main "$PWD" 9-x >/dev/null', **env)[0], 3)
    with open(os.path.join(wt, LOG)) as fh:
        check("removed: the decided row stays out", fh.read(), "row1\nrow-main\nrow-new\n")
    # A row the branch repeats on purpose stays repeated, and a row both sides
    # added — deferred_to_main sent it to main — comes once. Main's copy ends
    # without a newline, and its last row still stays a row of its own.
    seed, wt = setup(tmp, "repeat")
    commit(seed, LOG, "row1\nsent\nrow-main", "main's rows")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, LOG, "row1\nsent\nrow1\n", "the branch repeats row1")
    git(wt, "push", "-q")
    check("repeat: a conflict in the log", run(wt, 'merge_conflicts "$PWD"', **env), (1, LOG + "\n"))
    check("repeat: synced", run(wt, 'sync_with_main "$PWD" 9-x >/dev/null', **env)[0], 3)
    with open(os.path.join(wt, LOG)) as fh:
        check("repeat: the repeat stays, the sent row comes once", fh.read(),
              "row1\nsent\nrow-main\nrow1\n")
    check("minus: an empty older copy takes nothing away",
          run(wt, 'printf "a\\nb\\n" > "$TMPDIR_T/b"; : > "$TMPDIR_T/a"; '
                  'deferred_minus "$TMPDIR_T/a" "$TMPDIR_T/b"', TMPDIR_T=tmp, **env), (0, "a\nb\n"))

    # A session that pushed the merge and stopped short of the sync — a
    # change left uncommitted: the run stops, but what it pushed is code
    # nobody checked, and the hand-off for the merge is taken back.
    seed, wt = setup(tmp, "gate")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    def handed_over(wt, rev):
        path = os.path.join(wt, ".sclaude/local/feature/state.json")
        data = json.load(open(path)) if os.path.exists(path) else {}
        data["handoff"] = git(wt, "rev-parse", rev)
        with open(path, "w") as fh:
            json.dump(data, fh)

    handed_over(wt, "HEAD")
    pushed_dirty = ("git merge -q origin/main >/dev/null 2>&1; printf 'one\\nboth\\nthree\\n' > app.txt; "
                    "git add app.txt; git commit -q --no-edit; git push -q origin feat/9-x; "
                    "echo stray >> app.txt")
    rc, out = run(wt, 'sync_withdraw() { echo "WITHDRAWN $2"; }\nsync_gate "$PWD" 9-x 7',
                  **dict(env, CLAUDE_DOES=pushed_dirty))
    check("gate: stops", rc, 1)
    check("gate: the hand-off taken back", "WITHDRAWN 7" in out, True)
    git(wt, "checkout", "-q", "--", "app.txt")
    handed_over(wt, "origin/feat/9-x")
    rc, out = run(wt, 'sync_withdraw() { echo "WITHDRAWN $2"; }\nsync_gate "$PWD" 9-x 7', **env)
    check("gate: clean, nothing taken back", (rc, "WITHDRAWN" in out), (0, False))
    # origin's branch moved on another machine: nothing was synced, but its
    # commits are unchecked code all the same, and the hand-off goes back.
    other = os.path.join(tmp, "gate-other")
    subprocess.run(["git", "clone", "-q", "-b", "feat/9-x", os.path.join(tmp, "gate-origin.git"), other],
                   check=True, capture_output=True)
    git(other, "config", "user.email", "t@example.com")
    git(other, "config", "user.name", "t")
    commit(other, "elsewhere.txt", "x\n", "pushed from elsewhere")
    git(other, "push", "-q")
    # Fetched before the gate looks, as the menu and a step's start do: the
    # commits are measured against the head handed over, not the ref.
    git(wt, "fetch", "-q", "origin")
    rc, out = run(wt, 'sync_withdraw() { echo "WITHDRAWN $2 $3"; }\nsync_gate "$PWD" 9-x 7 nofetch', **env)
    # And 5: the code QA passed has changed, and the run starts over on it as
    # for a sync (3) rather than handing it over again at once, but nothing
    # was merged, and nobody is told so.
    check("gate: commits from elsewhere take it back too", (rc, "WITHDRAWN 7" in out), (5, True))

    # The merge wait: main moves into a conflict while it waits.
    seed, wt = setup(tmp, "wait")
    commit(seed, "app.txt", "one\nmain\nthree\n", "main's change")
    git(seed, "push", "-q", "origin", "HEAD:main")
    commit(wt, "app.txt", "one\nfeature\nthree\n", "feature's change")
    git(wt, "push", "-q")
    wait = ('source "%s/deploy.sh"\nbranch_pr_state() { echo OPEN; }\npoll_pause() { POLL_KEY=""; sleep 1; }\n'
            'project_flow_mode() { echo github; }\nregression_duration() { echo 1s; }\n'
            'SYNC_POLL=1\nmerge_wait 9-x 9 7 feat/9-x "" "$PWD"' % LIB)
    rc, out = run(wt, wait, **env)
    check("wait: stops on the conflict", rc, 3)
    check("wait: says why", "no longer merges" in out, True)

sys.exit(1 if failed else 0)
