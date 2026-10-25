#!/usr/bin/env python3
#
# A step's start merges main into a branch that is behind it, without asking.
#
# It used to ask, "Merge origin/main into <branch>?", and a "no" was
# remembered against main's commit. The answer was nearly always yes, and a
# no only put the merge off: the sync before the preview makes it all the
# same, after step 3 and the review had worked on a branch that was not what
# merges.
#
# Guarded here, on a scratch repository whose feature branch has a commit of
# its own and is behind main:
#
#   * the start merges, and asks nothing;
#   * a state left with the old "no" mark is merged all the same;
#   * a merge that would conflict goes to the sync with main, unasked, and
#     leaves no half-merged tree; a sync that stops short opens the step,
#     unless it left a merge under way, which holds the step before anything
#     else is looked at;
#   * a plain merge that stops on conflicts the check could not foresee is
#     backed out, and the step opens;
#   * the menu's sync (sync_offer with the branch named) still asks first,
#     and a no starts nothing.
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

    def start(answer, call=None, **env):
        script = ('BOLD=""; OFF=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""\n'
                  'REPO=%s\nsource %s/io.sh; source %s/ui.sh; source %s/state.sh; source %s/worktree.sh; source %s/deferred.sh; source %s/sync.sh\n'
                  'warn(){ echo "$*"; }; info(){ echo "$*"; }; unset ASK_DIR\n'
                  'ask() { echo "ASKED $1"; printf -v "$2" %%s "$ANSWER"; }\n'
                  'sync_with_main() { echo "SYNC $2 $3"; eval "${SYNC_DOES:-}"; return "${SYNC_RC:-3}"; }\n'
                  '%s'
                  % (repo, LIB, LIB, LIB, LIB, LIB, LIB, env.pop("PRELUDE", ""))
                  + (call or 'sync_branch %s') % repo + '\n')
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                              env=dict(os.environ, ANSWER=answer, **env)).stdout

    main_moves()
    out = start("")
    check("start-does-not-ask", "ASKED" in out, False)
    check("start-merges", git("log", "-1", "--format=%P", cwd=repo).count(" "), 1)
    main_moves()
    git("fetch", "-q", "origin", cwd=repo)
    with open(os.path.join(repo, ".sclaude/local/feature", "state.json"), "w") as fh:
        fh.write('{"branch": "feat/x", "feature": "x", "sync": {"declined": "%s"}}\n'
                 % git("rev-parse", "origin/main", cwd=repo))
    out = start("")
    check("old-no-mark-merged-anyway",
          subprocess.run(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=repo).returncode, 0)

    # A merge that would conflict is not left half-done for the person: the
    # sync with main resolves it, and nobody is asked first.
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
    out = start("")
    check("conflict: nothing asked", "ASKED" in out, False)
    check("conflict: the sync takes it", "SYNC x nofetch" in out, True)
    check("conflict: no half-merged tree", git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=repo), "")
    out = start("", call='sync_branch %s; echo "RC $?"', SYNC_RC="1")
    check("conflict: a sync that stops short opens the step", "RC 0" in out, True)
    check("conflict: ... and says so", "Not merged" in out, True)
    out = start("", call='sync_branch %s; echo "RC $?"', SYNC_RC="1",
                SYNC_DOES='git -C "$1" merge -q origin/main >/dev/null 2>&1')
    check("conflict: a half-merged tree holds the step", "RC 1" in out and "has not been started" in out, True)
    # Left under way, its resolution staged: held at once, before the check on
    # uncommitted work its staged files would pass for, and no sync opened.
    out = start("", call='sync_branch %s; echo "RC $?"')
    check("under way: held", "RC 1" in out and "has not been started" in out, True)
    check("under way: no sync", "SYNC" in out, False)
    git("merge", "--abort", cwd=repo)
    out = start("", call='sync_branch %s; echo "RC $?"', SYNC_RC="0")
    check("conflict gone by the sync's look: the plain merge runs", "stopped on conflicts" in out, True)
    check("conflict gone: backed out, the step opens", "RC 0" in out, True)

    # The menu names the branch: asked first, and a no is 4 with no sync.
    out = start("n", call='sync_offer %s x 7 feat/x; echo "RC $?"')
    check("menu: asked first", "with a session resolving them" in out, True)
    check("menu: a no is 4", "RC 4" in out, True)
    check("menu: a no starts nothing", "SYNC" in out, False)
    out = start("y", call='sync_offer %s x 7 feat/x; echo "RC $?"')
    check("menu: a yes syncs", "SYNC x nofetch" in out, True)

    # The check could not tell, and the plain merge stops on conflicts: backed
    # out, and the step opens on the branch as it stood.
    out = start("", call='sync_branch %s; echo "RC $?"', PRELUDE="merge_conflicts() { return 2; }\n")
    check("unforeseen: nothing asked", "ASKED" in out, False)
    check("unforeseen: the step opens", "RC 0" in out, True)
    check("unforeseen: backed out", git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=repo), "")
    check("unforeseen: says how to merge", "sclaude sync x" in out, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
