#!/usr/bin/env python3
#
# A friction review's fix on a feature whose pull request has merged.
#
# After a fix to a red production regression the feature's branch has merged
# already, and pushing the review's commits there carried them nowhere: no
# open pull request took them to main, and `sclaude done` deleted the branch.
# They go onto a branch of their own from main instead.
#
# When the review's deferred entries went to main ahead of the fix, each
# commit is carried without them.
#
# Run it with: python3 tests/friction-push.py
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failures = []
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
# A person's settings that would change a patch or refuse it: the carry must
# not read them.
ENV.update(GIT_CONFIG_COUNT="3", GIT_CONFIG_KEY_0="diff.noprefix", GIT_CONFIG_VALUE_0="true",
           GIT_CONFIG_KEY_1="color.diff", GIT_CONFIG_VALUE_1="always",
           GIT_CONFIG_KEY_2="apply.whitespace", GIT_CONFIG_VALUE_2="error")


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          env=ENV, check=True).stdout.strip()


def push(wt, frm, state, sent=""):
    script = ('for m in ui branches deferred run friction; do source "%s/$m.sh" 2>/dev/null; done\n'
              'info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }\n'
              'gh() { case "$1 $2" in "pr list") echo %s ;; "pr create") echo https://pr/9 ;; esac; }\n'
              'friction_push_project "%s" "%s" "%s"' % (LIB, state, wt, frm, sent))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout


tmp = tempfile.mkdtemp()
try:
    origin = os.path.join(tmp, "origin.git")
    wt = os.path.join(tmp, "myapp-12-x")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, wt], check=True, capture_output=True)
    git(wt, "commit", "-q", "--allow-empty", "-m", "base")
    git(wt, "push", "-q", "origin", "HEAD:main")
    git(wt, "switch", "-q", "-c", "feat/12-x")
    git(wt, "commit", "-q", "--allow-empty", "-m", "the feature")
    frm = git(wt, "rev-parse", "HEAD")
    with open(os.path.join(wt, "rule.json"), "w") as fh:
        fh.write("{}\n")
    # main moved on, and was merged into the feature before the fix: its
    # commit is in the range and must not be picked again.
    other = os.path.join(tmp, "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, capture_output=True)
    with open(os.path.join(other, "main.txt"), "w") as fh:
        fh.write("main\n")
    git(other, "add", "main.txt")
    git(other, "commit", "-q", "-m", "on main")
    git(other, "push", "-q", "origin", "HEAD:main")
    git(wt, "fetch", "-q", "origin")
    git(wt, "merge", "-q", "--no-edit", "origin/main")
    git(wt, "add", "rule.json")
    git(wt, "commit", "-q", "-m", "the review's fix")

    out = push(wt, frm, "MERGED")
    heads = git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    new = [h for h in heads.split("\n") if h.startswith("sclaude/friction-")]
    check("a branch of its own", len(new), 1)
    if new:
        log = git(origin, "log", "--format=%s", new[0])
        check("it carries the fix, on main", log.split("\n"), ["the review's fix", "on main", "base"])
    check("its pull request is named", "https://pr/9" in out, True)
    check("the merged branch is not pushed", "feat/12-x" in heads, False)

    out = push(wt, frm, "OPEN")
    check("an open pull request takes it as before",
          "feat/12-x" in git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/"), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# The fix and a deferred entry in one commit, the entry sent to main ahead of
# it (deferred_to_main) and a commit on the branch taking it back off. Picked
# whole, the first conflicts with main's copy of the entries and the second
# deletes it; carried without the deferred folders, the fix goes alone.
ROWS = ".sclaude/team/deferred/12-x.tsv"


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def world(tmp):
    origin = os.path.join(tmp, "origin.git")
    wt = os.path.join(tmp, "myapp-12-x")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, wt], check=True, capture_output=True)
    write(wt, ROWS, "earlier row\n")
    git(wt, "add", ROWS)
    git(wt, "commit", "-q", "-m", "base")
    git(wt, "push", "-q", "origin", "HEAD:main")
    git(wt, "switch", "-q", "-c", "feat/12-x")
    # Like a feature whose earlier rows went to main: the branch has none.
    git(wt, "rm", "-q", ROWS)
    git(wt, "commit", "-q", "-m", "the feature")
    frm = git(wt, "rev-parse", "HEAD")
    # A trailing space: an apply that judged whitespace by the person's
    # settings would refuse what a cherry-pick takes.
    write(wt, "prompt.md", "resolve what you fixed \n")
    write(wt, ROWS, "new row\n")
    git(wt, "add", "prompt.md", ROWS)
    git(wt, "commit", "-q", "-m", "the review's fix")
    other = os.path.join(tmp, "other")
    subprocess.run(["git", "clone", "-q", origin, other], check=True, capture_output=True)
    write(other, ROWS, "earlier row\nnew row\n")
    git(other, "commit", "-q", "-am", "carry deferred entries to main")
    git(other, "push", "-q", "origin", "HEAD:main")
    git(wt, "rm", "-q", ROWS)
    git(wt, "commit", "-q", "-m", "leave the deferred entries to main")
    return origin, wt, frm


def friction_branch(origin):
    heads = git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    return [h for h in heads.split("\n") if h.startswith("sclaude/friction-")]


tmp = tempfile.mkdtemp()
try:
    origin, wt, frm = world(tmp)
    out = push(wt, frm, "MERGED", "1")
    new = friction_branch(origin)
    check("entries on main: a branch of its own", len(new), 1)
    if new:
        log = git(origin, "log", "--format=%s", new[0])
        check("entries on main: the fix alone, on main",
              log.split("\n"), ["the review's fix", "carry deferred entries to main", "base"])
        check("entries on main: the fix is carried",
              git(origin, "show", new[0] + ":prompt.md"), "resolve what you fixed")
        check("entries on main: main's rows are kept",
              git(origin, "show", new[0] + ":" + ROWS), "earlier row\nnew row")
    check("entries on main: its pull request is named", "https://pr/9" in out, True)
    check("entries on main: not left by hand", "by hand" in out, False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    # The same commits with nothing beside the entries: nothing to carry.
    origin, wt, frm = world(tmp)
    git(wt, "reset", "-q", "--hard", frm)
    write(wt, ROWS, "new row\n")
    git(wt, "add", ROWS)
    git(wt, "commit", "-q", "-m", "put off a proposal")
    git(wt, "rm", "-q", ROWS)
    git(wt, "commit", "-q", "-m", "leave the deferred entries to main")
    out = push(wt, frm, "MERGED", "1")
    check("entries alone: no branch", friction_branch(origin), [])
    check("entries alone: said so, not by hand",
          ("nothing else to carry" in out, "by hand" in out), (True, False))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    # The fix itself conflicts with main: by hand, but the advice names only
    # the carried commit and keeps the deferred folders out of it.
    origin, wt, frm = world(tmp)
    other = os.path.join(tmp, "other")
    git(other, "pull", "-q", "origin", "main")
    write(other, "prompt.md", "main wrote this first\n")
    git(other, "add", "prompt.md")
    git(other, "commit", "-q", "-m", "main's own prompt")
    git(other, "push", "-q", "origin", "HEAD:main")
    fix = git(wt, "rev-parse", "--short", "HEAD~1")
    out = push(wt, frm, "MERGED", "1")
    check("fix conflicts: no branch", friction_branch(origin), [])
    check("fix conflicts: names the carried commit alone",
          ("Its commits are %s in" % fix in out, "..HEAD" in out), (True, False))
    check("fix conflicts: says to leave the deferred folders out", "leaving out the deferred folders" in out, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    # A range git cannot list (its start is no commit there) is not an empty
    # one: by hand, not "nothing to carry".
    origin, wt, frm = world(tmp)
    out = push(wt, "0" * 40, "MERGED", "1")
    check("unlisted range: no branch", friction_branch(origin), [])
    check("unlisted range: by hand, not nothing to carry",
          ("carry them to main by hand" in out, "nothing else to carry" in out), (True, False))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    # The entries never reached main: picked whole as before, and a conflict
    # leaves them to be carried by hand rather than dropped.
    origin, wt, frm = world(tmp)
    out = push(wt, frm, "MERGED", "")
    check("entries not sent: no branch", friction_branch(origin), [])
    check("entries not sent: carried by hand", "carry them to main by hand" in out, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
