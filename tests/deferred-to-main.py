#!/usr/bin/env python3
#
# Deferred entries go to main directly, past the pull request.
#
# A retrospective put three lines of log into a merged feature's deferred file,
# and the feature went back to step 3 for them: a new pull request, a review,
# the preview, QA. The entries change nothing that runs, so deferred_to_main
# sends them to origin's main and takes them off the branch. Guarded here:
#
#   * entries alone, on a merged branch: main gets the rows, the branch is
#     reset past the commit, which keeps its message on main;
#   * rows main already holds are not added twice, and a repeated row the
#     branch holds more often than main is added;
#   * entries and code in one commit: the rows go to main, the code stays, and
#     a commit on the branch puts the deferred folder back;
#   * left alone: no entries, a commit already on origin, and an open pull
#     request whose branch carried entries before;
#   * the drift and staleness counts skip commits that only add entries.
#
# Run it with: python3 tests/deferred-to-main.py
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failures = []
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
DEFERRED = ".sclaude/team/deferred/12-x.tsv"


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          env=ENV, check=True).stdout.strip()


def write(path, text, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(text)


def send(wt, frm, state):
    script = ('for m in ui developer branches deferred; do source "%s/$m.sh"; done\n'
              'info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }\n'
              'gh() { echo %s; }\n'
              'deferred_to_main "%s" "%s"; echo "RC $?"' % (LIB, state, wt, frm))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout


def main_file(origin):
    try:
        return git(origin, "show", "main:" + DEFERRED).split("\n")
    except subprocess.CalledProcessError:
        return None


def setup(tmp, name, main_rows=None):
    origin = os.path.join(tmp, name + ".git")
    wt = os.path.join(tmp, name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, wt], check=True, capture_output=True)
    if main_rows is not None:
        write(os.path.join(wt, DEFERRED), main_rows)
        git(wt, "add", "-A")
    git(wt, "commit", "-q", "--allow-empty", "-m", "base")
    git(wt, "push", "-q", "origin", "HEAD:main")
    git(wt, "switch", "-q", "-c", "feat/12-x")
    write(os.path.join(wt, "app.txt"), "feature\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "the feature")
    git(wt, "push", "-q", "origin", "feat/12-x")
    return origin, wt


tmp = tempfile.mkdtemp()
try:
    # Entries alone, on a merged branch; main holds one of the rows already,
    # and a repeated row twice on the branch but once on main.
    origin, wt = setup(tmp, "merged", "a\tkept\nr\trepeat\n")
    frm = git(wt, "rev-parse", "HEAD")
    write(os.path.join(wt, DEFERRED), "r\trepeat\nnew\trow\n", "a")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "chore(sclaude): put off two")
    out = send(wt, frm, "MERGED")
    check("merged: sent", "RC 0" in out, True)
    check("merged: main has the rows once, the repeat counted",
          main_file(origin), ["a\tkept", "r\trepeat", "r\trepeat", "new\trow"])
    check("merged: the message is kept", git(origin, "log", "-1", "--format=%s", "main"),
          "chore(sclaude): put off two")
    check("merged: the branch is reset past it", git(wt, "rev-parse", "HEAD"), frm)
    check("merged: the feature is not on main", "app.txt" in git(origin, "ls-tree", "--name-only", "main"),
          False)

    # Again, with nothing new: nothing to do.
    check("nothing in range", "RC 1" in send(wt, frm, "MERGED"), True)

    # Entries and code in one commit, open pull request.
    origin, wt = setup(tmp, "mixed")
    frm = git(wt, "rev-parse", "HEAD")
    write(os.path.join(wt, DEFERRED), "m\trow\n")
    write(os.path.join(wt, "policy.json"), "{}\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "fix: policy, and a row")
    out = send(wt, frm, "OPEN")
    check("mixed: sent", "RC 0" in out, True)
    check("mixed: main has the row", main_file(origin), ["m\trow"])
    check("mixed: the code stays", os.path.exists(os.path.join(wt, "policy.json")), True)
    check("mixed: the branch carries no entries",
          git(wt, "diff", "--name-only", frm, "HEAD"), "policy.json")
    check("mixed: the tree is clean", git(wt, "status", "--porcelain"), "")

    # An open pull request whose branch carried entries before: left alone.
    origin, wt = setup(tmp, "carried")
    write(os.path.join(wt, DEFERRED), "old\trow\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "earlier row")
    git(wt, "push", "-q", "origin", "feat/12-x")
    frm = git(wt, "rev-parse", "HEAD")
    write(os.path.join(wt, DEFERRED), "new\trow\n", "a")
    git(wt, "commit", "-q", "-am", "later row")
    check("carried: left to the pull request", "RC 1" in send(wt, frm, "OPEN"), True)
    check("carried: main untouched", main_file(origin), None)

    # A commit already on origin: left alone.
    git(wt, "push", "-q", "origin", "feat/12-x")
    check("pushed: left alone", "RC 1" in send(wt, frm, "MERGED"), True)

    # The counts skip commits that only add entries.
    script = ('for m in ui developer branches deferred; do source "%s/$m.sh"; done\n'
              'deferred_rev_count "%s" main..origin/main'
              % (LIB, os.path.join(tmp, "merged")))
    git(os.path.join(tmp, "merged"), "fetch", "-q", "origin")
    git(os.path.join(tmp, "merged"), "branch", "-f", "main", git(os.path.join(tmp, "merged"), "rev-parse", "origin/main~1"))
    got = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout.strip()
    check("counts: an entries-only commit is not counted", got, "0")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
