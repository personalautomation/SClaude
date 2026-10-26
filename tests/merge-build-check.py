#!/usr/bin/env python3
#
# A bench for merge_build_check: whether what a merge would put on main is
# built before sclaude merges it.
#
# GitHub calls a pull request clean when its merge has no textual conflict,
# and with `review: local` nothing else runs on it. The failures here are
# quiet ones:
#
#   built for nothing   a tip that already holds main is built again.
#   the branch alone    the branch is built, not its merge with the newer main,
#                       and a rename on main sails through.
#   built every poll    the merge wait builds the same pair every half minute.
#   a tree left behind  the throwaway worktree outlives the check.
#   main's config       the parts are read from the main checkout's config,
#                       not the merge's: a part the pull request dropped runs
#                       on a tree it no longer fits.
#
# A bare repository plays origin; the clone plays the feature's tree. The
# project's parts are stubs: `check` fails when a file named `broken` exists.
#
# Run it with: python3 tests/merge-build-check.py
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


ENV = {k: v for k, v in os.environ.items()
       if not k.startswith("GIT_") and not k.startswith("SCLAUDE_")}
ENV.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
           GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@x.test",
           GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@x.test")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, env=ENV).stdout.strip()


def commit(repo, name, text=None):
    path = os.path.join(repo, name)
    if text is None:
        os.remove(path)
    else:
        with open(path, "w") as fh:
            fh.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "edit " + name)


class World:
    def __init__(self, tmp):
        self.tmp = tmp
        self.origin = os.path.join(tmp, "origin.git")
        self.up = os.path.join(tmp, "upstream")
        self.wt = os.path.join(tmp, "feature")
        self.runs = os.path.join(tmp, "runs")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin],
                       env=ENV, check=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.up], env=ENV,
                       capture_output=True)
        commit(self.up, "a.txt", "one\n")
        git(self.up, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", self.origin, self.wt], env=ENV,
                       capture_output=True)
        git(self.wt, "checkout", "-qb", "feat/x")
        commit(self.wt, "f.txt", "feature\n")
        git(self.wt, "push", "-q", "origin", "feat/x")

    def main_moves(self, name="m.txt", text="main\n"):
        commit(self.up, name, text)
        git(self.up, "push", "-q", "origin", "main")

    def run(self):
        script = """
info() { :; }
warn() { :; }
link_env() { :; }
link_node_modules() { :; }
project_regression_parts() { echo "$REPO" >> %s.config; echo "check"; }
regression_command() { echo "$REPO" >> %s.config; echo "echo run >> %s; test ! -e broken"; }
source "%s/sync.sh"
merge_build_check "%s"
echo "rc=$?"
""" % (self.runs, self.runs, self.runs, LIB, self.wt)
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                             env=dict(ENV, TMPDIR=self.tmp)).stdout.strip()
        return out.splitlines()

    def built(self):
        if not os.path.exists(self.runs):
            return 0
        with open(self.runs) as fh:
            return len(fh.read().splitlines())


with tempfile.TemporaryDirectory() as tmp:
    w = World(tmp)
    check("tip-holding-main-is-not-built", w.run(), ["rc=0"])
    check("tip-holding-main-runs-nothing", w.built(), 0)

with tempfile.TemporaryDirectory() as tmp:
    w = World(tmp)
    w.main_moves()
    check("merge-with-newer-main-builds", w.run(), ["rc=0"])
    check("merge-with-newer-main-ran-the-parts", w.built(), 1)
    check("the-same-pair-is-not-built-again", w.run(), ["rc=0"])
    check("the-same-pair-ran-nothing-more", w.built(), 1)
    check("the-throwaway-tree-is-gone",
          os.path.exists(os.path.join(tmp, "sclaude-merge-check-feature")), False)
    check("the-throwaway-tree-is-unregistered",
          "sclaude-merge-check" in git(w.wt, "worktree", "list"), False)
    with open(w.runs + ".config") as fh:
        check("the-config-is-the-merge-s",
              set(fh.read().split()), {os.path.join(tmp, "sclaude-merge-check-feature")})

with tempfile.TemporaryDirectory() as tmp:
    # The branch alone is green; only main's newer commit breaks it, so a
    # check that built the branch instead of the merge would pass.
    w = World(tmp)
    w.main_moves("broken", "x\n")
    check("main-breaking-the-merge-is-red", w.run(), ["check", "rc=1"])
    check("a-red-pair-is-remembered", w.run(), ["check", "rc=1"])
    check("a-red-pair-is-built-once", w.built(), 1)
    # The verdict read back for the merge wait: red for this pair only.
    def red():
        return subprocess.run(["bash", "-c", 'source "%s/sync.sh"; merge_check_red "%s"'
                               % (LIB, w.wt)], capture_output=True, text=True,
                              env=ENV).stdout.strip()
    check("the-red-part-is-read-back", red(), "check")
    # A verdict the old reader cached, from the main checkout's config, is
    # not this check's: under its old name it is not read.
    feature = os.path.join(w.wt, ".sclaude", "local", "feature")
    os.rename(os.path.join(feature, "merge-verdict"), os.path.join(feature, "merge-check"))
    check("an-old-cache-is-not-read", red(), "")
    os.rename(os.path.join(feature, "merge-check"), os.path.join(feature, "merge-verdict"))
    # main fixed: a new pair, built again.
    w.main_moves("broken", None)
    check("main-moving-again-builds-again", w.run(), ["rc=0"])
    check("main-moving-again-ran-the-parts", w.built(), 2)
    check("a-moved-pair-is-not-red", red(), "")

if failures:
    print("\n%d check(s) failed." % len(failures))
    sys.exit(1)
print("\nall passed")
