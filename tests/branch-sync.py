#!/usr/bin/env python3
#
# "Merge origin/main into <branch>?" is asked once for each state of main.
#
# On one pull request every review round opened a fresh session through
# run_step, and every one stopped on the same question the human had already
# answered "n". A "no" is now remembered against origin/main's commit.
#
# Guarded here, on a scratch repository whose feature branch has a commit of
# its own and is behind main:
#
#   * the first start asks; "n" leaves the branch as it is;
#   * the next start does not ask, and says how to merge;
#   * once main moves, it asks again;
#   * "y" merges, as before.
#
# Run it with: python3 tests/branch-sync.py
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


tmp = tempfile.mkdtemp()
try:
    def git(*a, cwd=None):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True).stdout.strip()

    origin = os.path.join(tmp, "origin.git")
    repo = os.path.join(tmp, "repo")
    git("init", "-q", "--bare", "-b", "main", origin)
    git("clone", "-q", origin, repo)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        git("config", k, v, cwd=repo)
    git("commit", "-q", "--allow-empty", "-m", "a", cwd=repo)
    git("push", "-q", "origin", "HEAD:main", cwd=repo)
    git("switch", "-q", "-c", "feat/x", cwd=repo)
    git("commit", "-q", "--allow-empty", "-m", "mine", cwd=repo)

    def main_moves():
        other = os.path.join(tmp, "other")
        shutil.rmtree(other, ignore_errors=True)
        git("clone", "-q", origin, other)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            git("config", k, v, cwd=other)
        git("commit", "-q", "--allow-empty", "-m", "main moves", cwd=other)
        git("push", "-q", "origin", "HEAD:main", cwd=other)

    os.makedirs(os.path.join(repo, ".sclaude/local/feature"))
    with open(os.path.join(repo, ".git", "info", "exclude"), "a") as fh:
        fh.write(".sclaude/local/feature\n")
    with open(os.path.join(repo, ".sclaude/local/feature", "state.json"), "w") as fh:
        fh.write('{"branch": "feat/x", "feature": "x"}\n')

    def start(answer, **env):
        script = ('BOLD=""; OFF=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""\n'
                  'REPO=%s\nsource %s/io.sh; source %s/ui.sh; source %s/state.sh; source %s/worktree.sh; source %s/deferred.sh; source %s/sync.sh\n'
                  'warn(){ echo "$*"; }; info(){ echo "$*"; }; unset ASK_DIR\n'
                  'ask() { echo "ASKED $1"; printf -v "$2" %%s "$ANSWER"; }\n'
                  'sync_with_main() { echo "SYNC $2 $3"; return "${SYNC_RC:-3}"; }\n'
                  'sync_branch %s\n' % (repo, LIB, LIB, LIB, LIB, LIB, LIB, repo))
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              env=dict(os.environ, ANSWER=answer, **env)).stdout

    main_moves()
    out = start("n")
    check("first-start-asks", "ASKED" in out, True)
    check("n-leaves-it", git("log", "-1", "--format=%s", cwd=repo), "mine")
    out = start("n")
    check("second-start-does-not-ask", "ASKED" in out, False)
    check("second-start-says-how", "sclaude sync x" in out, True)
    main_moves()
    out = start("y")
    check("main-moved-asks-again", "ASKED" in out, True)
    check("y-merges", git("log", "-1", "--format=%P", cwd=repo).count(" "), 1)

    # A merge that would conflict is not left half-done for the person: the
    # question says a session resolves it, and the sync with main does.
    git("push", "-q", "origin", "feat/x", cwd=repo)
    other = os.path.join(tmp, "other")
    with open(os.path.join(other, "f.txt"), "w") as fh:
        fh.write("main\n")
    git("pull", "-q", "origin", "main", cwd=other)
    with open(os.path.join(other, "f.txt"), "w") as fh:
        fh.write("main\n")
    git("add", "f.txt", cwd=other)
    git("commit", "-q", "-m", "main's f", cwd=other)
    git("push", "-q", "origin", "HEAD:main", cwd=other)
    with open(os.path.join(repo, "f.txt"), "w") as fh:
        fh.write("mine\n")
    git("add", "f.txt", cwd=repo)
    git("commit", "-q", "-m", "my f", cwd=repo)
    git("push", "-q", "origin", "feat/x", cwd=repo)
    out = start("y")
    check("conflict: the question names the session", "with a session resolving them" in out, True)
    check("conflict: the sync takes it", "SYNC x nofetch" in out, True)
    check("conflict: no half-merged tree", git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=repo), "")
    out = start("y", SYNC_RC="1")
    check("conflict: a sync that fails holds the step", "has not been started" in out, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
