#!/usr/bin/env python3
#
# layout_migrate moves an older sclaude's .feature/ into .sclaude/local/feature/.
#
# A tree made by an older sclaude excludes only .feature from git, so the move
# must teach git to ignore the new place first: otherwise the state files are
# untracked and visible, and a step's `git add -A` puts them in its pull
# request. And while another sclaude runs, which reads its state from the old
# place, nothing moves.
#
# Run it with: python3 tests/layout-migrate.py
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def migrate(repo, others=""):
    stub = ('instruments_others() { echo "%s"; [[ -n "%s" ]]; }' % (others, others))
    script = ('for m in ui state scratch; do source "%s/$m.sh"; done\n'
              'info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }\n%s\n'
              'REPO="%s"; layout_migrate' % (LIB, stub, repo))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60).stdout


tmp = tempfile.mkdtemp()
try:
    repo = os.path.join(tmp, "myapp")
    subprocess.run(["git", "init", "-q", repo], check=True)
    with open(os.path.join(repo, ".git", "info", "exclude"), "w") as fh:
        fh.write(".feature\n")
    os.makedirs(os.path.join(repo, ".feature"))
    with open(os.path.join(repo, ".feature", "state.json"), "w") as fh:
        fh.write("{}\n")

    out = migrate(repo, others="pid 1: sclaude run, up 01:00")
    check("waits-for-others", os.path.isdir(os.path.join(repo, ".feature")), True)
    check("says-why", "another sclaude" in out, True)

    out = migrate(repo)
    check("moved", os.path.isfile(os.path.join(repo, ".sclaude", "local", "feature", "state.json")), True)
    status = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True).stdout
    check("hidden-from-git", status, "")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
