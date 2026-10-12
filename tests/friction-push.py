#!/usr/bin/env python3
#
# A friction review's fix on a feature whose pull request has merged.
#
# After a fix to a red production regression the feature's branch has merged
# already, and pushing the review's commits there carried them nowhere: no
# open pull request took them to main, and `sclaude done` deleted the branch.
# They go onto a branch of their own from main instead.
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


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          env=ENV, check=True).stdout.strip()


def push(wt, frm, state):
    script = ('for m in ui branches run; do source "%s/$m.sh" 2>/dev/null; done\n'
              'info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }\n'
              'gh() { case "$1 $2" in "pr list") echo %s ;; "pr create") echo https://pr/9 ;; esac; }\n'
              'friction_push_project "%s" "%s"' % (LIB, state, wt, frm))
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
    git(wt, "add", "rule.json")
    git(wt, "commit", "-q", "-m", "the review's fix")

    out = push(wt, frm, "MERGED")
    heads = git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    new = [h for h in heads.split("\n") if h.startswith("sclaude/friction-")]
    check("a branch of its own", len(new), 1)
    if new:
        log = git(origin, "log", "--format=%s", new[0])
        check("it carries the fix, on main", log.split("\n"), ["the review's fix", "base"])
    check("its pull request is named", "https://pr/9" in out, True)
    check("the merged branch is not pushed", "feat/12-x" in heads, False)

    out = push(wt, frm, "OPEN")
    check("an open pull request takes it as before",
          "feat/12-x" in git(origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/"), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
