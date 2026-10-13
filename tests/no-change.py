#!/usr/bin/env python3
#
# A feature that changed nothing of its own ends at step 2 (no_change.sh).
#
# An investigation's plan said "no code, no pull request", and its step 2 still
# ran the whole local regression on a tree that was main's product. Guarded here:
#
#   * a branch carrying only sclaude's commits — `.sclaude/` alone, or a friction
#     review's recorded range — is a feature with no change;
#   * a commit of the feature's own, or uncommitted work, is not;
#   * `.sclaude/` goes to main past the hooks, even when main moved meanwhile;
#   * the product files a friction review changed go to main when the person
#     says so, and are left out when they said drop;
#   * a second pass sends nothing twice.
#
# Run it with: python3 tests/no-change.py
import json
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
failures = []
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
STATE = ".sclaude/local/feature/state.json"


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                          env=ENV, check=True).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def commit(wt, path, text, message):
    write(os.path.join(wt, path), text)
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", message)
    return git(wt, "rev-parse", "HEAD")


def run(wt, call, answer="n"):
    script = ('for m in io ui state scratch worktree no_change; do source "%s/$m.sh"; done\n'
              'info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }\n'
              'ask() { printf -v "$2" %%s "%s"; }\n'
              '%s; echo "RC $?"' % (LIB, answer, call))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=ENV, cwd=wt).stdout


def setup(tmp, name):
    origin = os.path.join(tmp, name + ".git")
    wt = os.path.join(tmp, name)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, wt], check=True, capture_output=True)
    write(os.path.join(wt, ".gitignore"), ".sclaude/local/\n")
    write(os.path.join(wt, "docs/a.md"), "one\n")
    write(os.path.join(wt, ".sclaude/team/policy.json"), '{"a": 1}\n')
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "base")
    git(wt, "push", "-q", "origin", "HEAD:main")
    git(wt, "switch", "-q", "-c", "feat/12-x")
    write(os.path.join(wt, STATE), json.dumps({"step": "code"}))
    return origin, wt


def state(wt, **values):
    path = os.path.join(wt, STATE)
    data = json.load(open(path))
    data.update(values)
    write(path, json.dumps(data))


def main_show(origin, path):
    try:
        return git(origin, "show", "main:" + path)
    except subprocess.CalledProcessError:
        return None


with tempfile.TemporaryDirectory() as tmp:
    # Only sclaude's commits: a policy change, and a friction fix to a doc
    # whose range the state records.
    origin, wt = setup(tmp, "only-sclaude")
    commit(wt, ".sclaude/team/policy.json", '{"a": 2}\n', "chore(sclaude): policy")
    frm = git(wt, "rev-parse", "HEAD")
    to = commit(wt, "docs/a.md", "one\ntwo\n", "docs: a friction fix")
    state(wt, friction={"plan-1": {"project_from": frm, "project_to": to}})
    out = run(wt, 'no_change_feature "%s" >/dev/null' % wt)
    check("only sclaude's commits is no change", "RC 0" in out, True)

    # Main moves under another file meanwhile.
    side = os.path.join(tmp, "side")
    subprocess.run(["git", "clone", "-q", origin, side], check=True, capture_output=True)
    commit(side, "other.txt", "x\n", "someone else")
    git(side, "push", "-q", "origin", "HEAD:main")

    # Dropped: .sclaude goes, the doc does not.
    out = run(wt, 'no_change_settle "%s"' % wt, answer="n")
    check("settle with drop succeeds", "RC 0" in out, True)
    check(".sclaude reaches main", main_show(origin, ".sclaude/team/policy.json"), '{"a": 2}')
    check("main keeps what moved meanwhile", main_show(origin, "other.txt"), "x")
    check("a dropped doc stays off main", main_show(origin, "docs/a.md"), "one")
    check("the answer is kept",
          json.load(open(os.path.join(wt, STATE))).get("no_change_product"), "drop")

    # Again: nothing new on main.
    before = git(origin, "rev-parse", "main")
    out = run(wt, 'no_change_settle "%s"' % wt, answer="y")
    check("second settle succeeds", "RC 0" in out, True)
    check("second settle sends nothing", git(origin, "rev-parse", "main"), before)

    # Sent: the doc reaches main as well.
    origin, wt = setup(tmp, "send")
    frm = git(wt, "rev-parse", "HEAD")
    to = commit(wt, "docs/a.md", "one\ntwo\n", "docs: a friction fix")
    state(wt, friction={"plan-1": {"project_from": frm, "project_to": to}})
    out = run(wt, 'no_change_settle "%s"' % wt, answer="y")
    check("settle with send succeeds", "RC 0" in out, True)
    check("a sent doc reaches main", main_show(origin, "docs/a.md"), "one\ntwo")

    # A commit of the feature's own.
    origin, wt = setup(tmp, "own")
    commit(wt, "app.txt", "feature\n", "feat: the feature")
    out = run(wt, 'no_change_feature "%s" >/dev/null' % wt)
    check("a commit of its own is a change", "RC 1" in out, True)

    # The same product file, outside any friction range, is the feature's.
    origin, wt = setup(tmp, "own-doc")
    commit(wt, "docs/a.md", "one\ntwo\n", "docs: the feature's doc")
    out = run(wt, 'no_change_feature "%s" >/dev/null' % wt)
    check("a doc outside a friction range is a change", "RC 1" in out, True)

    # Uncommitted work.
    origin, wt = setup(tmp, "dirty")
    write(os.path.join(wt, "app.txt"), "half done\n")
    out = run(wt, 'no_change_feature "%s" >/dev/null' % wt)
    check("uncommitted work is a change", "RC 1" in out, True)

    # The clean-up asks again: work of its own since step 2 keeps the branch.
    out = run(wt, 'no_change_settle "%s"' % wt, answer="y")
    check("settle refuses a branch with work of its own", "RC 1" in out, True)

    # An empty branch.
    origin, wt = setup(tmp, "empty")
    out = run(wt, 'no_change_feature "%s" >/dev/null' % wt)
    check("an empty branch is no change", "RC 0" in out, True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
