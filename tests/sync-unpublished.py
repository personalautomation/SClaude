#!/usr/bin/env python3
#
# sync_unpublished: before a local regression, a branch origin has never seen
# is put on top of main without a question, when it rebases cleanly. Main
# moved during a code step once, the suite failed on the branch's older copy
# of a file main had changed, and a fixing session was opened only to rebase.
#
# A pushed branch is not rewritten, and a rebase that would stop on a conflict
# is backed out: the tree is left as it was.
#
# Run it with: python3 tests/sync-unpublished.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


ENV = {k: v for k, v in os.environ.items()
       if not k.startswith("GIT_") and not k.startswith("SCLAUDE_")}
ENV.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, env=ENV).stdout.strip()


def commit(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "edit " + name)


def world(tmp, branch_file, main_file, pushed=False, pr=None):
    origin = os.path.join(tmp, "origin.git")
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True, env=ENV)
    subprocess.run(["git", "clone", "-q", origin, repo], check=True, env=ENV,
                   capture_output=True)
    git(repo, "checkout", "-qb", "main")
    commit(repo, "base", "1\n")
    git(repo, "push", "-q", "origin", "main")
    wt = os.path.join(tmp, "wt")
    git(repo, "worktree", "add", "-q", "-b", "feat/x", wt, "main")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    with open(os.path.join(wt, ".sclaude/local/feature/state.json"), "w") as fh:
        json.dump(dict({"branch": "feat/x", "feature": "x"}, **({"pr": pr} if pr else {})), fh)
    exclude = git(repo, "rev-parse", "--git-path", "info/exclude")
    with open(os.path.join(repo, exclude) if not os.path.isabs(exclude) else exclude, "a") as fh:
        fh.write(".sclaude/local/\n")
    commit(wt, branch_file, "feature\n")
    if pushed:
        git(wt, "push", "-q", "origin", "feat/x")
    # Main moves on, by another hand.
    other = os.path.join(tmp, "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, env=ENV,
                   capture_output=True)
    commit(other, main_file, "main\n")
    git(other, "push", "-q", "origin", "main")
    return repo, wt


def run(repo, wt):
    script = ('set -uo pipefail\ninfo() { echo "INFO $*"; }\nwarn() { echo "WARN $*"; }\n'
              'LIB="%s"; REPO="%s"\n'
              'for m in state project scratch deferred worktree; do source "$LIB/$m.sh"; done\n'
              'sync_unpublished "%s"; echo "rc=$?"' % (LIB, repo, wt))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=ENV, timeout=60).stdout


def main():
    cases = (
        ("unpublished", "feature.txt", "schema.txt", False),
        ("pushed", "feature.txt", "schema.txt", True),
        ("conflict", "same.txt", "same.txt", False),
        ("had a pr", "feature.txt", "schema.txt", False),
    )
    for name, bfile, mfile, pushed in cases:
        tmp = tempfile.mkdtemp(prefix="sclaude-unpub-")
        try:
            repo, wt = world(tmp, bfile, mfile, pushed, pr=57 if name == "had a pr" else None)
            before = git(wt, "rev-parse", "HEAD")
            out = run(repo, wt)
            on_main = subprocess.run(["git", "-C", wt, "merge-base", "--is-ancestor",
                                      "origin/main", "HEAD"], env=ENV).returncode == 0
            if name == "unpublished":
                check("an unpushed branch is put on top of main", on_main, True)
                check("and it is said", "put on top of origin/main" in out, True)
                check("its own commit is kept",
                      os.path.exists(os.path.join(wt, "feature.txt")), True)
            elif name == "pushed":
                check("a pushed branch is not rewritten", git(wt, "rev-parse", "HEAD"), before)
            elif name == "had a pr":
                check("a branch with a pull request recorded is not rewritten",
                      git(wt, "rev-parse", "HEAD"), before)
            else:
                check("a conflicting rebase is backed out", git(wt, "rev-parse", "HEAD"), before)
                check("and leaves no rebase under way",
                      os.path.exists(os.path.join(git(wt, "rev-parse", "--absolute-git-dir"),
                                                  "rebase-merge")), False)
            check("%s: returns 0" % name, out.strip().endswith("rc=0"), True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
