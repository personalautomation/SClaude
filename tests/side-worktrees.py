#!/usr/bin/env python3
#
# `done` offers to remove a side pull request's worktree once it is merged.
#
# A review once opened a pull request from ~/myapp-review-dispatch-fix, a
# worktree sclaude never knew of; `done` removed the feature's own and left that
# one behind. Guarded here, with gh faked:
#
#   * a clean worktree with no .sclaude/local/feature whose branch has a merged pull request
#     is offered, and on "y" removed with its branch;
#   * a feature's worktree (it has .sclaude/local/feature), an unmerged branch, and one with
#     uncommitted work are not offered at all;
#   * `done` calls it.
#
# Run it with: python3 tests/side-worktrees.py
import os
import re
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


with open(os.path.join(LIB, "worktree.sh")) as fh:
    m = re.search(r"^side_worktrees_offer\(\) \{\n.*?^\}\n", fh.read(), re.S | re.M)
OFFER = m.group(0) if m else ""
check("function-present", bool(OFFER), True)

tmp = tempfile.mkdtemp()
try:
    repo = os.path.join(tmp, "myapp")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    subprocess.run(git + ["-C", repo, "commit", "-q", "--allow-empty", "-m", "a"], check=True)
    trees = {}
    for name in ("merged", "feature", "open", "dirty"):
        path = os.path.join(tmp, "myapp-" + name)
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b",
                        "fix/" + name, path], check=True)
        trees[name] = path
    os.makedirs(os.path.join(trees["feature"], ".sclaude/local/feature"))
    with open(os.path.join(trees["dirty"], "x"), "w") as fh:
        fh.write("work\n")

    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    with open(os.path.join(bin_dir, "gh"), "w") as fh:
        # Every branch but fix/open has a merged pull request.
        fh.write('#!/usr/bin/env bash\n'
                 'for a; do [[ "$prev" == --head ]] && b="$a"; prev="$a"; done\n'
                 '[[ "$b" == fix/open ]] || echo 164\n')
    os.chmod(os.path.join(bin_dir, "gh"), 0o755)

    script = ('REPO="%s"; asked=""\n'
              'say() { echo "SAY $*"; }; info() { :; }; warn() { echo "WARN $*"; }\n'
              'ask() { echo "ASK"; printf -v "$2" y; }; is_yes() { [[ "$1" == y ]]; }\n'
              '%s\nside_worktrees_offer' % (repo, OFFER))
    env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"])
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env=env).stdout
    said = [l for l in out.splitlines() if l.startswith("SAY")]
    check("offered-once", len(said), 1)
    check("offered-the-merged-one", trees["merged"] in (said[0] if said else ""), True)
    check("merged-removed", os.path.exists(trees["merged"]), False)
    branches = subprocess.run(["git", "-C", repo, "branch", "--format=%(refname:short)"],
                              capture_output=True, text=True).stdout.split()
    check("merged-branch-removed", "fix/merged" in branches, False)
    for name in ("feature", "open", "dirty"):
        check("kept-" + name, os.path.exists(trees[name]), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

with open(os.path.join(ROOT, "bin", "sclaude")) as fh:
    SCLAUDE = fh.read()
check("done-calls-it",
      "cleaned up.${OFF}\"\n  side_worktrees_offer\n}" in SCLAUDE, True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
