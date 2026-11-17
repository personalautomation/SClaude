#!/usr/bin/env python3
#
# `done` deletes a squash-merged branch.
#
# A squash merge leaves the branch's commits out of main, so `git branch -d`
# refused every such branch and `done` kept it, saying it carried commits not
# in main, which was false. branch_delete_merged forces it when the local tip
# is the head of the merged pull request, or when its commits past that head
# change nothing main lacks. Guarded here, with gh faked:
#
#   * merged into main the ordinary way: deleted by -d;
#   * squash-merged, tip at the pull request's head: deleted;
#   * a commit past the pull request's head: kept;
#   * a tip behind the pull request's head: deleted;
#   * commits past the head whose change main already holds: deleted;
#   * commits past the head that main lacks, or that conflict with it: kept;
#   * no merged pull request: kept;
#   * `done` and the branch review both use it;
#   * the branch review keeps a feature's part branches, and says a pushed
#     branch is pushed without guessing at its pull request;
#   * `done` deletes the parts' branches the feature's branch holds;
#   * a tree opened by hand (no .sclaude/local) whose merged pull request
#     main holds is offered with its branch when clean, kept when it has
#     changes, past the merged head or sclaude's own; the review removes the
#     tree before the branch.
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
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
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
busy = None
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

    # Past the head, but main already holds the change: a commit carried to
    # main by hand, and one added and taken back on the branch.
    git(repo, "switch", "-q", "-c", "feat/sq2")
    head = commit(repo, "sq2")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/sq2")
    git(repo, "commit", "-q", "-m", "sq2 (#2)")
    git(repo, "switch", "-q", "feat/sq2")
    commit(repo, "carried")
    commit(repo, "noise")
    git(repo, "rm", "-q", "noise")
    git(repo, "commit", "-q", "-m", "noise taken back")
    git(repo, "switch", "-q", "main")
    commit(repo, "carried")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    check("past the head, on main already: deleted", delete(repo, "feat/sq2", head),
          ("RC 2", False))

    # The same, but main lacks what the branch added after the merge.
    git(repo, "switch", "-q", "-c", "feat/sq3")
    head = commit(repo, "sq3")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/sq3")
    git(repo, "commit", "-q", "-m", "sq3 (#3)")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "feat/sq3")
    commit(repo, "only on the branch")
    git(repo, "switch", "-q", "main")
    check("past the head, not on main: kept", delete(repo, "feat/sq3", head), ("RC 1", True))

    # Past the head, a deletion that conflicts with main: main edits the file,
    # the branch deletes it. merge-tree leaves main's version and prints main's
    # own tree first, so only its exit code keeps the branch.
    git(repo, "switch", "-q", "-c", "feat/sq4")
    head = commit(repo, "sq4")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/sq4")
    git(repo, "commit", "-q", "-m", "sq4 (#4)")
    with open(os.path.join(repo, "sq4"), "w") as fh:
        fh.write("main's\n")
    git(repo, "commit", "-q", "-am", "sq4 on main")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "feat/sq4")
    git(repo, "rm", "-q", "sq4")
    git(repo, "commit", "-q", "-m", "sq4 gone on the branch")
    git(repo, "switch", "-q", "main")
    check("past the head, conflicting: kept", delete(repo, "feat/sq4", head), ("RC 1", True))

    # The tip behind the merged head: the PR got a commit this clone never
    # fetched. Everything the branch has went in.
    git(repo, "switch", "-q", "-c", "feat/behind", "main")
    commit(repo, "behind-1")
    head = commit(repo, "behind-2")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feat/behind")
    git(repo, "commit", "-q", "-m", "behind (#5)")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "branch", "-f", "feat/behind", "feat/behind~1")
    check("tip behind the merged head: deleted", delete(repo, "feat/behind", head), ("RC 2", False))

    # No merged pull request.
    check("no pull request: kept", delete(repo, "feat/past", ""), ("RC 1", True))

    # The branch review: a part's branch of a feature in progress is the
    # feature's, whatever it holds — one not yet given a commit or a push
    # used to be offered for deletion — and a pushed branch with commits says
    # so, not "PR still open" by guess.
    git(repo, "switch", "-q", "-c", "feat/p", "main")
    git(repo, "switch", "-q", "-c", "feat/p-1")
    commit(repo, "p1")
    git(repo, "switch", "-q", "-c", "feat/p-2", "main")
    git(repo, "switch", "-q", "main")
    wt = os.path.join(tmp, "wt")
    git(repo, "worktree", "add", "-q", wt, "feat/p")
    os.makedirs(os.path.join(wt, ".sclaude", "local", "feature"))
    open(os.path.join(wt, ".sclaude", "local", "feature", "state.json"), "w").write("{}")
    for name in ("pushed", "open"):
        git(repo, "switch", "-q", "-c", "feat/" + name, "main")
        commit(repo, name)
        git(repo, "update-ref", "refs/remotes/origin/feat/" + name, "HEAD")
    git(repo, "switch", "-q", "main")
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
              'state_get() { echo feat/p; }\n'
              'parts_branches() { printf "feat/p-1\\nfeat/p-2\\n"; }\n'
              'branch_pr_state() { [[ "$1" == feat/open ]] && echo OPEN; true; }\n'
              'classify_branches' % (repo, LIB))
    rows = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout
    said = {r.split("\t")[1]: (r.split("\t")[0], r.split("\t")[2]) for r in rows.splitlines() if r.count("\t") == 2}
    check("a part with commits is the feature's", said.get("feat/p-1"), ("keep", "a part of feat/p, deleted with it"))
    check("a part with none yet is the feature's", said.get("feat/p-2"), ("keep", "a part of feat/p, deleted with it"))
    check("pushed, said without asking", (said.get("feat/pushed"), said.get("feat/open")),
          (("keep", "has commits, pushed"), ("keep", "has commits, pushed")))

    # `done` deletes the parts' branches with the feature's: the ones the
    # feature's branch holds go, one carrying more stays.
    git(repo, "switch", "-q", "-c", "feat/q-1", "main")
    commit(repo, "q1")
    git(repo, "switch", "-q", "-c", "feat/q-2")
    commit(repo, "q2")
    feature_tip = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "-c", "feat/q-3")
    commit(repo, "q3 after the join")
    git(repo, "switch", "-q", "main")
    script = ('REPO=%s; source "%s/tree/branches.sh"\nwarn() { echo "WARN $*"; }\n'
              'printf "feat/q-1\\nfeat/q-2\\nfeat/q-3\\n" | branches_parts_delete %s' % (repo, LIB, feature_tip))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout
    left = git(repo, "branch", "--format=%(refname:short)").split("\n")
    check("parts held by the feature go", [b for b in ("feat/q-1", "feat/q-2", "feat/q-3") if b in left], ["feat/q-3"])
    check("a part carrying more is said", "local branch feat/q-3 kept" in out, True)

    # A tree opened by hand, its pull request merged: a clean one goes with
    # its branch, the tree first; one with changes is kept. A feature's tree
    # (feat/p above has a state) is never asked about. A commit past the merged head that main lacks keeps the tree, and so
    # does sclaude's own .sclaude/local in it (a deferred review's tree, its
    # workshop inside).
    heads = {}
    for name in ("hand", "dirty", "past", "ours", "busy", "gone"):
        git(repo, "switch", "-q", "-c", "fix/" + name, "main")
        heads["fix/" + name] = commit(repo, "h-" + name)
        if name == "past":
            commit(repo, "after the merge, not on main")
        git(repo, "switch", "-q", "main")
        # The busy one has a space in its path: compared whole.
        git(repo, "worktree", "add", "-q", os.path.join(tmp, "busy tree" if name == "busy" else name), "fix/" + name)
    os.makedirs(os.path.join(tmp, "ours", ".sclaude", "local", "instruments"))
    with open(os.path.join(repo, ".git", "info", "exclude"), "a") as fh:
        fh.write(".sclaude/local/\n")
    hand = os.path.join(tmp, "hand")
    with open(os.path.join(hand, ".gitignore"), "w") as fh:
        fh.write(".next/\n")
    git(hand, "add", ".gitignore")
    git(hand, "commit", "-q", "-m", "ignore .next")
    os.makedirs(os.path.join(hand, ".next"))
    open(os.path.join(hand, ".next", "cache"), "w").close()   # ignored: still clean
    open(os.path.join(tmp, "dirty", "wip"), "w").close()
    heads["fix/hand"] = git(repo, "rev-parse", "fix/hand")
    # A process at work in a clean tree (a session going on after the merge).
    busy = subprocess.Popen(["sleep", "60"], cwd=os.path.join(tmp, "busy tree"))
    # A tree deleted by hand and never pruned: git still names it.
    shutil.rmtree(os.path.join(tmp, "gone"))
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
              'state_get() { echo feat/p; }\n'
              'parts_branches() { printf "feat/p-1\\nfeat/p-2\\n"; }\n'
              'branch_pr_state() { true; }\n'
              'merged_pr_head() { case "$1" in %s esac; }\n'
              'classify_branches' % (repo, LIB, " ".join("%s) echo %s ;;" % kv for kv in heads.items())))
    rows = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV).stdout
    said = {r.split("\t")[1]: (r.split("\t")[0], r.split("\t")[2]) for r in rows.splitlines() if r.count("\t") == 2}
    check("a tree a process works in: kept", said.get("fix/busy"),
          ("keep", "PR merged, but its worktree is in use or not clean (%s)" % os.path.join(tmp, "busy tree")))
    check("a tree that is not there: said, not offered", said.get("fix/gone"),
          ("keep", "its worktree is missing (deleted, or not mounted) — if it is gone: "
           "git worktree remove %s" % os.path.join(tmp, "gone")))
    # Offered, then gone before the yes: kept.
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
              'classify_branches() { printf "drop\\tfix/gone\\tx\\n"; }\n'
              'align_columns() { :; }\nask() { printf -v "$2" y; }\nis_yes() { true; }\n'
              'warn() { echo "WARN $*"; }\nmerged_pr_head() { echo %s; }\n'
              'review_branches' % (repo, LIB, heads["fix/gone"]))
    said_gone = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV,
                               stdin=subprocess.DEVNULL).stdout
    check("a tree gone before the yes keeps its branch",
          ("fix/gone" in git(repo, "branch", "--format=%(refname:short)").split("\n"),
           "is missing now" in said_gone), (True, True))
    check("a clean tree by hand, merged: offered", said.get("fix/hand"),
          ("drop", "PR merged, its worktree left behind (%s)" % hand))
    check("a tree by hand with changes: kept", said.get("fix/dirty"),
          ("keep", "PR merged, but its worktree is in use or not clean (%s)" % os.path.join(tmp, "dirty")))
    check("a feature's tree is not asked about", (said.get("feat/p") or ("",))[0], "keep")
    check("past the merged head, not on main: kept", (said.get("fix/past") or ("",))[0], "keep")
    check("sclaude's own tree: kept", (said.get("fix/ours") or ("",))[0], "keep")
    git(repo, "config", "branch.fix/hand.remote", "origin")
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
              'classify_branches() { printf "drop\\tfix/hand\\tx\\n"; }\n'
              'align_columns() { :; }\nask() { printf -v "$2" y; }\nis_yes() { true; }\n'
              'warn() { echo "WARN $*"; }\nmerged_pr_head() { echo %s; }\n'
              'review_branches' % (repo, LIB, heads["fix/hand"]))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV,
                         stdin=subprocess.DEVNULL).stdout
    left = git(repo, "branch", "--format=%(refname:short)").split("\n")
    # A process that came into the tree while the question waited keeps it.
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
              'classify_branches() { printf "drop\\tfix/busy\\tx\\n"; }\n'
              'align_columns() { :; }\nask() { printf -v "$2" y; }\nis_yes() { true; }\n'
              'warn() { echo "WARN $*"; }\nmerged_pr_head() { echo %s; }\n'
              'review_branches' % (repo, LIB, heads["fix/busy"]))
    said_busy = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV,
                               stdin=subprocess.DEVNULL).stdout
    check("a process in the tree when asked keeps it",
          (os.path.exists(os.path.join(tmp, "busy tree")), "something works in its worktree" in said_busy),
          (True, True))

    # Asked again before the tree goes: a commit made in it while the
    # question waited keeps both.
    commit(os.path.join(tmp, "dirty"), "wip")
    script = ('REPO=%s; source "%s/tree/branches.sh"\n'
              'classify_branches() { printf "drop\\tfix/dirty\\tx\\n"; }\n'
              'align_columns() { :; }\nask() { printf -v "$2" y; }\nis_yes() { true; }\n'
              'warn() { echo "WARN $*"; }\nmerged_pr_head() { echo %s; }\n'
              'review_branches' % (repo, LIB, heads["fix/dirty"]))
    kept = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=ENV,
                          stdin=subprocess.DEVNULL).stdout
    check("a commit made while asked keeps the tree and the branch",
          (os.path.exists(os.path.join(tmp, "dirty")),
           "fix/dirty" in git(repo, "branch", "--format=%(refname:short)").split("\n"),
           "could not confirm main holds all of it" in kept), (True, True, True))
    check("the branch's config section goes with it",
          subprocess.run(["git", "-C", repo, "config", "--get-regexp", r"^branch\.fix/hand\."],
                         capture_output=True, text=True).stdout, "")
    check("the review removes the tree, then the branch",
          (os.path.exists(hand), "fix/hand" in left, out.count("deleted")), (False, False, 1))

    sclaude = "".join(open(os.path.join(ROOT, _p)).read()
        for _p in ("bin/sclaude", "sclaude/lib/commands/start.sh", "sclaude/lib/commands/menu.sh", "sclaude/lib/commands/step_commands.sh", "sclaude/lib/commands/done.sh", "sclaude/lib/commands/feature_commands.sh"))
    with open(os.path.join(LIB, "tree", "branches.sh")) as fh:
        branches = fh.read()
    done = sclaude[sclaude.index("cmd_done() {"):]
    done = done[:done.index("\n}\n")]
    check("done uses it", 'branch_delete_merged "$branch"' in done, True)
    check("done forces nothing itself", 'branch -D "$branch"' in done, False)
    check("the branch review uses it", 'branch_delete_merged "$branch"' in branches, True)
finally:
    if busy:
        busy.kill()
        busy.wait()
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
