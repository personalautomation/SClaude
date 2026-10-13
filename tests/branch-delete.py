#!/usr/bin/env python3
#
# `done` deletes a squash-merged branch.
#
# A squash merge leaves the branch's commits out of main, so `git branch -d`
# refused every such branch and `done` kept it, saying it carried commits not
# in main, which was false. branch_delete_merged forces it when the local tip
# is the head of the merged pull request, and keeps a branch with commits past
# it. Guarded here, with gh faked:
#
#   * merged into main the ordinary way: deleted by -d;
#   * squash-merged, tip at the pull request's head: deleted;
#   * a commit past the pull request's head: kept;
#   * no merged pull request: kept;
#   * `done` and the branch review both use it.
#
# Run it with: python3 tests/branch-delete.py
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
failures = []
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          env=ENV, check=True).stdout.strip()


def delete(repo, branch, head):
    script = ('REPO=%s; source "%s/branches.sh"\n'
              'merged_pr_head() { echo %s; }\n'
              'branch_delete_merged %s; echo "RC $?"' % (repo, LIB, head, branch))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout
    return out.strip(), branch in git(repo, "branch", "--format=%(refname:short)").split("\n")


def commit(repo, name):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(name + "\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


tmp = tempfile.mkdtemp()
try:
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    commit(repo, "base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    # Merged the ordinary way.
    git(repo, "switch", "-q", "-c", "feat/plain")
    commit(repo, "plain")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "feat/plain")
    check("plain merge: deleted", delete(repo, "feat/plain", ""), ("RC 0", False))

    # Squash-merged: main gets the content as a commit of its own.
    git(repo, "switch", "-q", "-c", "feat/squash")
    head = commit(repo, "squash")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/squash")
    git(repo, "commit", "-q", "-m", "squash (#1)")
    check("squash, tip at the head: deleted", delete(repo, "feat/squash", head), ("RC 2", False))

    # A commit past the merged head.
    git(repo, "switch", "-q", "-c", "feat/past", "main~1")
    head = commit(repo, "past")
    commit(repo, "after the merge")
    git(repo, "switch", "-q", "main")
    check("past the head: kept", delete(repo, "feat/past", head), ("RC 1", True))

    # No merged pull request.
    check("no pull request: kept", delete(repo, "feat/past", ""), ("RC 1", True))

    with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
        sclaude = fh.read()
    with open(os.path.join(LIB, "branches.sh")) as fh:
        branches = fh.read()
    done = sclaude[sclaude.index("cmd_done() {"):]
    done = done[:done.index("\n}\n")]
    check("done uses it", 'branch_delete_merged "$branch"' in done, True)
    check("done forces nothing itself", 'branch -D "$branch"' in done, False)
    check("the branch review uses it", 'branch_delete_merged "$branch"' in branches, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
