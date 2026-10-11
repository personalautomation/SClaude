#!/usr/bin/env python3
#
# The monthly deferred review reads the entries main has, not the main
# checkout's working copy.
#
# Entries reach main through the features' pull requests, so the checkout a
# person runs `sclaude deferred` in can hold more or fewer than main. The list
# was read there while the session worked in a worktree made from origin/main,
# so it named files the session did not find, or missed some it did. The
# session itself is a stub here: what is checked is what it would be told.
#
# Run it with: python3 tests/deferred-review.py
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
PROMPTS = os.path.join(ROOT, "sclaude", "prompts")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True,
                          text=True, env=env, check=True).stdout


def review(repo, prompt_out, dirty=False):
    """Run cmd_deferred with the session stubbed; its output."""
    script = r'''
set -uo pipefail
BOLD=""; BLUE=""; OFF=""; DIM=""; GREEN=""; YELLOW=""; RED=""
for m in state project developer deferred; do source "%(lib)s/$m.sh"; done
LIB="%(lib)s"; PROMPTS="%(prompts)s"; INSTRUMENTS="%(root)s"
info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }; die() { echo "DIE $*"; exit 1; }
new_session_id() { echo 00000000-0000-0000-0000-000000000000; }
review_guard_settings() { :; }
session_watch_start() { :; }; session_watch_stop() { :; }; session_closed() { return 0; }
claude_launch() { printf '%%s' "${@: -1}" > "%(out)s"; [[ -z "${DIRTY:-}" ]] || echo x > dirty.txt; }
cmd_deferred
''' % {"lib": LIB, "prompts": PROMPTS, "root": ROOT, "out": prompt_out}
    env = dict(os.environ, DIRTY="1" if dirty else "")
    return subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True,
                          text=True, timeout=60, env=env).stdout


def trees(tmp):
    return [w for w in os.listdir(tmp) if w.startswith("myapp-deferred-")]


def branches(repo):
    return [b.strip(" *+") for b in git(repo, "branch").splitlines() if "sclaude/deferred-" in b]


tmp = tempfile.mkdtemp()
try:
    origin = os.path.join(tmp, "origin.git")
    repo = os.path.join(tmp, "myapp")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, repo], check=True, capture_output=True)
    d = os.path.join(repo, ".sclaude", "team", "deferred")
    os.makedirs(d)
    with open(os.path.join(d, "12-a.tsv"), "w") as fh:
        fh.write("2026-09-01\tmyapp\t12-a\treview\tclass-a\tOn main.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "an entry on main")
    git(repo, "push", "-q", "origin", "HEAD:main")

    # The working copy loses main's file and gains one main does not have.
    os.remove(os.path.join(d, "12-a.tsv"))
    with open(os.path.join(d, "13-b.tsv"), "w") as fh:
        fh.write("2026-09-02\tmyapp\t13-b\treview\tclass-b\tOnly here.\n")

    out_file = os.path.join(tmp, "prompt.txt")
    out = review(repo, out_file)
    prompt = open(out_file).read() if os.path.exists(out_file) else ""
    check("review-ran", "DIE" in out, False)
    check("names-mains-file", "deferred/12-a.tsv" in prompt, True)
    check("not-the-working-copys", "deferred/13-b.tsv" in prompt, False)
    # A review that changed nothing says so and leaves no tree or branch.
    check("nothing-says-so", "the review changed nothing" in out, True)
    check("nothing-no-tree", trees(tmp), [])
    check("nothing-no-branch", branches(repo), [])

    # Edits it did not commit are named, and the tree holding them stays.
    out = review(repo, out_file, dirty=True)
    check("dirty-not-nothing", "the review changed nothing" in out, False)
    check("dirty-named", "did not commit" in out and trees(tmp)[0] in out if trees(tmp) else False, True)
    for w in trees(tmp):
        git(repo, "worktree", "remove", "--force", os.path.join(tmp, w))
    for b in branches(repo):
        git(repo, "branch", "-q", "-D", b)

    # Main with nothing deferred: no session, and no worktree left behind.
    git(repo, "rm", "-q", "--cached", ".sclaude/team/deferred/12-a.tsv")
    git(repo, "commit", "-qm", "reviewed")
    git(repo, "push", "-q", "origin", "HEAD:main")
    os.remove(out_file)
    out = review(repo, out_file)
    check("empty-main-says-so", "Nothing deferred on main" in out, True)
    check("empty-main-no-session", os.path.exists(out_file), False)
    check("empty-main-no-worktree", [w for w in os.listdir(tmp) if w.startswith("myapp-deferred-")], [])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
