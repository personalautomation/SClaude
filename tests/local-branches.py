#!/usr/bin/env python3
#
# A bench for local_branches.py: which branches of sclaude's checkout exist on
# this machine alone, and whether their work is on main.
#
# A squash leaves none of a branch's commits on main, so git calls a squashed
# branch unmerged and work found nowhere else looks the same. The failures
# this guards against are quiet ones:
#
#   squashed read as lost    every start warns about clutter, and the warning
#                            that matters is lost among them.
#   lost read as squashed    a workshop's unpublished change is called done.
#   a busy branch listed     a workshop in use, or a feature being built in a
#                            worktree, is flagged while somebody is on it.
#   a pushed branch listed   work already on a remote is not at risk.
#   a deletion read as done  a branch that only removes code has no added line
#                            to find on main, and must not score as landed.
#   moved code read as done  lines a branch moves within a file are in main's
#                            copy already; only what main added counts.
#   a revert read as done    a branch that added work and reverted it has its
#                            base's tree; its work may exist nowhere else, so
#                            such a branch is unclear, never offered to delete.
#
# A bare repository plays origin; its clone plays sclaude's checkout.
#
# Run it with: python3 tests/local-branches.py
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib", "improve",
                      "local_branches.py")

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def write(repo, path, lines):
    with open(os.path.join(repo, path), "w") as f:
        f.write("\n".join(lines) + "\n")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def run(cmd, repo):
    return subprocess.run([sys.executable, SCRIPT, cmd, repo], capture_output=True, text=True).stdout


with tempfile.TemporaryDirectory() as tmp:
    origin, repo = os.path.join(tmp, "origin.git"), os.path.join(tmp, "checkout")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    subprocess.run(["git", "clone", "-q", origin, repo], check=True, capture_output=True)
    git(repo, "checkout", "-q", "-b", "main")
    write(repo, "a.sh", ["echo the first line of the orchestrator"])
    commit(repo, "start")
    git(repo, "push", "-q", "origin", "main")

    # Squashed: two commits on a branch, their sum committed once on main, and
    # main moving on in the same file afterwards.
    git(repo, "checkout", "-q", "-b", "feat/squashed")
    write(repo, "a.sh", ["echo the first line of the orchestrator", "echo a feature line one"])
    commit(repo, "one")
    write(repo, "a.sh", ["echo the first line of the orchestrator", "echo a feature line one",
                         "echo a feature line two"])
    commit(repo, "two")
    git(repo, "checkout", "-q", "main")
    write(repo, "a.sh", ["echo the first line of the orchestrator", "echo a feature line one",
                         "echo a feature line two"])
    commit(repo, "feat: the feature, squashed")
    write(repo, "a.sh", ["echo the first line of the orchestrator", "echo a feature line one",
                         "echo a feature line two", "echo main went on after the squash"])
    commit(repo, "later")
    git(repo, "push", "-q", "origin", "main")

    # Lost: a workshop's change that never reached main or a remote.
    git(repo, "checkout", "-q", "-b", "workshop/unpublished", "main")
    write(repo, "b.md", ["a change reviewed and never published", "with a second line of its own"])
    commit(repo, "the unpublished change")

    # Only deletions: nothing added to look for on main.
    git(repo, "checkout", "-q", "-b", "fix/only-deletes", "main")
    write(repo, "a.sh", ["echo the first line of the orchestrator"])
    commit(repo, "remove the feature lines")

    # Moved: the same lines in another order, plus one starting with "++".
    # Forked before main moved on, so main's whole file holds the moved lines
    # while main's own additions since the fork do not.
    git(repo, "checkout", "-q", "-b", "fix/moved", "main~1")
    write(repo, "a.sh", ["echo a feature line two", "echo a feature line one",
                         "echo the first line of the orchestrator",
                         "++ a line that starts like a file header"])
    commit(repo, "reorder")

    # Squashed, then main merged in: its base's tree.
    git(repo, "checkout", "-q", "-b", "dev/merged-up", "feat/squashed")
    git(repo, "merge", "-q", "--no-edit", "-X", "theirs", "main")

    # Added and reverted: its base's tree too.
    git(repo, "checkout", "-q", "-b", "workshop/reverted", "main")
    write(repo, "e.md", ["a fix tried and then reverted on the branch"])
    commit(repo, "try a fix")
    git(repo, "revert", "--no-edit", "HEAD")

    # Pushed: on a remote, so not at risk.
    git(repo, "checkout", "-q", "-b", "exp/pushed", "main")
    write(repo, "c.md", ["an experiment kept on origin on purpose"])
    commit(repo, "experiment")
    git(repo, "push", "-q", "origin", "exp/pushed")

    # Busy: checked out in another worktree.
    git(repo, "checkout", "-q", "main")
    git(repo, "worktree", "add", "-q", "-b", "workshop/in-use", os.path.join(tmp, "ws"))
    write(os.path.join(tmp, "ws"), "d.md", ["a workshop somebody is working in right now"])
    commit(os.path.join(tmp, "ws"), "in progress")
    git(repo, "fetch", "-q", "origin")

    rows = {line.split("\t")[0]: line.split("\t") for line in run("list", repo).splitlines()}
    check("squashed branch is listed", "feat/squashed" in rows, True)
    check("squashed branch's work is on main", rows.get("feat/squashed", [""] * 5)[4], "main")
    check("unpublished branch is listed", "workshop/unpublished" in rows, True)
    check("unpublished branch's work is here alone", rows.get("workshop/unpublished", [""] * 5)[4], "only-here")
    check("unpublished branch's commits counted", rows.get("workshop/unpublished", [""] * 5)[1], "1")
    check("a pushed branch is not listed", "exp/pushed" in rows, False)
    check("a branch in a worktree is not listed", "workshop/in-use" in rows, False)
    check("main is not listed", "main" in rows, False)
    check("a deletion-only branch is here alone", rows.get("fix/only-deletes", [""] * 5)[4], "only-here")
    check("a branch that moved lines is here alone", rows.get("fix/moved", [""] * 5)[4], "only-here")
    check("a branch that took main in after its squash is unclear", rows.get("dev/merged-up", [""] * 5)[3:], ["-", "unclear"])
    check("a branch that reverted its work is unclear", rows.get("workshop/reverted", [""] * 5)[3:], ["-", "unclear"])

    # An unclear branch is named at the start like lost work.
    git(repo, "branch", "-q", "-D", "fix/only-deletes", "fix/moved", "dev/merged-up")
    check("the start's note names an unclear branch", "workshop/reverted" in run("note", repo), True)
    # The note names three at most: keep one branch here alone, and the clutter.
    git(repo, "branch", "-q", "-D", "workshop/reverted")
    note = run("note", repo)
    check("the start's note names the unpublished branch", "workshop/unpublished" in note, True)
    check("the start's note leaves the squashed one out", "feat/squashed" in note, False)

    git(repo, "branch", "-q", "-D", "workshop/unpublished")
    check("no note when nothing is here alone", run("note", repo), "")

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
