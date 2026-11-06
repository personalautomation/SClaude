#!/usr/bin/env python3
#
# refresh_main in worktree.sh: before a feature is branched off, the main
# checkout is fast-forwarded to origin/main and, when its lockfile moved, its
# node_modules is reinstalled with `npm ci` — a new tree links that
# node_modules, and check_deps compares lockfiles only, so a main checkout
# whose lockfile had moved without an install handed every new feature the old
# packages without a word.
#
# A bare origin and a clone stand for the project; npm is a stub that records
# its arguments. Run it with: python3 tests/main-refresh.py
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "sclaude", "lib"))
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True,
                          text=True, check=True).stdout.strip()


def refresh(root, repo):
    script = """
set -uo pipefail
info() { echo "INFO $*"; }
warn() { echo "WARN $*"; }
REPO="%s"
source "%s/core/state.sh"
source "%s/tree/worktree.sh"
refresh_main
""" % (repo, LIB, LIB)
    env = dict(os.environ)
    env["PATH"] = os.path.join(root, "stub") + os.pathsep + env["PATH"]
    env["HOME"] = root
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=env, timeout=60).stdout


def npm_runs(root):
    path = os.path.join(root, "npm-log")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return fh.read().split()


def lock(repo, text, message):
    with open(os.path.join(repo, "package-lock.json"), "w") as fh:
        fh.write(text)
    git(repo, "add", "package-lock.json")
    git(repo, "commit", "-qm", message)


root = tempfile.mkdtemp(prefix="sclaude-main-refresh-")
try:
    stub = os.path.join(root, "stub")
    os.makedirs(stub)
    # npm ci removes node_modules before it installs: so does the stub, which
    # is what keeps the files other trees hard-link untouched.
    with open(os.path.join(stub, "npm"), "w") as fh:
        fh.write('#!/bin/sh\necho "$1" >> "%s/npm-log"\n'
                 'rm -rf node_modules && mkdir -p node_modules\n'
                 'cp package-lock.json node_modules/.package-lock.json\n' % root)
    os.chmod(os.path.join(stub, "npm"), 0o755)
    for name, value in (("user.email", "t@example.com"), ("user.name", "t"),
                        ("init.defaultBranch", "main")):
        subprocess.run(["git", "config", "--file", os.path.join(root, ".gitconfig"),
                        name, value], check=True)
    os.environ["HOME"] = root

    origin = os.path.join(root, "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    seed = os.path.join(root, "seed")
    subprocess.run(["git", "clone", "-q", origin, seed], check=True,
                   capture_output=True)
    git(seed, "checkout", "-qb", "main")
    lock(seed, "one\n", "first")
    git(seed, "push", "-q", "origin", "main")

    repo = os.path.join(root, "repo")
    subprocess.run(["git", "clone", "-q", origin, repo], check=True)
    os.makedirs(os.path.join(repo, "node_modules"))
    with open(os.path.join(repo, "node_modules", "kept"), "w") as fh:
        fh.write("an installed package\n")
    # Installed after the lockfile was written: npm's own record is newer.
    time.sleep(0.01)
    with open(os.path.join(repo, "node_modules", ".package-lock.json"), "w") as fh:
        fh.write("one\n")

    # No mark yet, the install newer than the lockfile: current, marked, no ci.
    out = refresh(root, repo)
    check("current install: npm not run", npm_runs(root), [])
    check("current install: marked",
          os.path.exists(os.path.join(repo, "node_modules", ".sclaude-lock")), True)

    # origin/main moves the lockfile: the checkout follows and reinstalls.
    lock(seed, "two\n", "second")
    git(seed, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    out = refresh(root, repo)
    check("fast-forwarded to origin/main", git(repo, "rev-parse", "HEAD"),
          git(repo, "rev-parse", "origin/main"))
    check("moved lockfile: npm ci", npm_runs(root), ["ci"])
    check("and marked", open(os.path.join(repo, "node_modules", ".sclaude-lock")).read().strip(),
          subprocess.run(["sha256sum", os.path.join(repo, "package-lock.json")],
                         capture_output=True, text=True).stdout.split()[0])

    # Nothing moved since: no second install.
    refresh(root, repo)
    check("same lockfile: npm not run again", npm_runs(root), ["ci"])

    # A Node process working in the checkout (a server, a typecheck): left
    # alone, and said so. It need not listen anywhere; it is told by its
    # working directory and its name.
    lock(seed, "three\n", "third")
    git(seed, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    # Real node, whose thread title is never plain "node": the check goes by
    # the executable. Skipped where no node is installed.
    node = shutil.which("node")
    if node:
        worker = subprocess.Popen([node, "-e", "setTimeout(() => {}, 60000)"], cwd=repo)
        try:
            for _ in range(50):
                if os.path.exists("/proc/%d/exe" % worker.pid) and \
                        os.path.realpath("/proc/%d/exe" % worker.pid).endswith("/node"):
                    break
                time.sleep(0.05)
            out = refresh(root, repo)
            check("node process working: npm not run", npm_runs(root), ["ci"])
            check("node process working: said so", "a Node process works in it" in out, True)
        finally:
            worker.kill()
            worker.wait()
        # A Claude session's MCP server: `npm exec <server>` started by the
        # session itself, whose node lives as long as the session and reads
        # none of the checkout's packages, holds nothing off. The same
        # `npm exec` run through a shell is a tool like any other and counts.
        # The titles carry spaces, as npm's do, which the walk up reads past.
        spawner = os.path.join(root, "spawner.js")
        with open(spawner, "w") as fh:
            fh.write("process.title = 'npm exec some server';\n"
                     "require('child_process').spawn(process.execPath, ['-e', "
                     "\"process.title = 'some server'; setTimeout(() => {}, 60000)\"],"
                     " {stdio: 'inherit'});\nsetTimeout(() => {}, 60000);\n")
        fake = os.path.join(root, "bin-claude", "claude")
        os.makedirs(os.path.dirname(fake))
        os.symlink(shutil.which("bash"), fake)

        def tree_under(launcher):
            proc = subprocess.Popen([launcher, "-c", 'exec "$0" "$1"', node, spawner],
                                    cwd=repo, start_new_session=True) if launcher == "sh" else \
                subprocess.Popen([launcher, "-c", '"$0" "$1"; :', node, spawner],
                                 cwd=repo, start_new_session=True)
            for _ in range(100):
                kids = subprocess.run(["pgrep", "-s", str(proc.pid), "-f", "some server"],
                                      capture_output=True, text=True).stdout.split()
                if len(kids) >= 2:
                    break
                time.sleep(0.05)
            return proc

        def stop(proc):
            subprocess.run(["pkill", "-s", str(proc.pid)])
            proc.wait()

        under_claude = tree_under(fake)
        try:
            os.makedirs(os.path.join(repo, ".next", "dev"))
            out = refresh(root, repo)
            check("an MCP server the session started: npm ci all the same", npm_runs(root), ["ci", "ci"])
        finally:
            stop(under_claude)
        lock(seed, "three and a half\n", "between")
        git(seed, "push", "-q", "origin", "main")
        git(repo, "fetch", "-q", "origin")
        under_shell = tree_under("sh")
        try:
            out = refresh(root, repo)
            check("npm exec through a shell: held off", npm_runs(root), ["ci", "ci"])
            check("npm exec through a shell: said so", "a Node process works in it" in out, True)
        finally:
            stop(under_shell)
        # Under the shell of a session's Bash tool, whose command line names
        # a snapshot under ~/.claude: still a tool, still counts.
        bash_tool = subprocess.Popen(
            ["bash", "-c", '"$0" "$1"; : source %s/.claude/shell-snapshots/s.sh' % root,
             node, spawner], cwd=repo, start_new_session=True)
        try:
            for _ in range(100):
                if len(subprocess.run(["pgrep", "-s", str(bash_tool.pid), "-f", "some server"],
                                      capture_output=True, text=True).stdout.split()) >= 2:
                    break
                time.sleep(0.05)
            out = refresh(root, repo)
            check("npm exec under a Bash tool's shell: held off", npm_runs(root), ["ci", "ci"])
        finally:
            stop(bash_tool)
        refresh(root, repo)
        check("npm exec gone: npm ci", npm_runs(root), ["ci", "ci", "ci"])
        # A Claude Code plugin's hook or server, run from ~/.claude/plugins in
        # the session's directory, is Claude Code's own and holds nothing off.
        plugin = os.path.join(root, ".claude", "plugins", "p", "hooks", "hook.mjs")
        os.makedirs(os.path.dirname(plugin))
        with open(plugin, "w") as fh:
            fh.write("setTimeout(() => {}, 60000)\n")
        lock(seed, "plugins\n", "plugins")
        git(seed, "push", "-q", "origin", "main")
        git(repo, "fetch", "-q", "origin")
        hook = subprocess.Popen([node, plugin], cwd=repo)
        try:
            for _ in range(50):
                if os.path.realpath("/proc/%d/exe" % hook.pid).endswith("/node"):
                    break
                time.sleep(0.05)
            refresh(root, repo)
            check("a plugin's node: npm ci all the same", npm_runs(root), ["ci", "ci", "ci", "ci"])
        finally:
            hook.kill()
            hook.wait()
    else:
        os.makedirs(os.path.join(repo, ".next", "dev"))
        refresh(root, repo)
    check("process gone: npm ci", npm_runs(root)[:2], ["ci", "ci"])
    check("and the Turbopack cache of the old packages dropped",
          os.path.isdir(os.path.join(repo, ".next", "dev")), False)

    # An edit in the shared checkout that the fast-forward would overwrite:
    # git refuses, the edit stays where it was and nothing goes to the stash.
    lock(seed, "five\n", "fifth")
    git(seed, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    with open(os.path.join(repo, "package-lock.json"), "w") as fh:
        fh.write("somebody's edit\n")
    head = git(repo, "rev-parse", "HEAD")
    out = refresh(root, repo)
    check("edit in the way: not moved", git(repo, "rev-parse", "HEAD"), head)
    check("edit in the way: said so", "could not be fast-forwarded" in out, True)
    check("edit in the way: the edit kept",
          open(os.path.join(repo, "package-lock.json")).read(), "somebody's edit\n")
    check("edit in the way: nothing stashed", git(repo, "stash", "list"), "")
    git(repo, "checkout", "--", "package-lock.json")
    refresh(root, repo)
    npm_runs_before = npm_runs(root)

    # A tree links from the main checkout under the same lock, and gets it.
    wt = os.path.join(root, "wt")
    os.makedirs(wt)
    subprocess.run(["bash", "-c", 'set -uo pipefail\ninfo() { :; }\nwarn() { echo "WARN $*"; }\n'
                    'REPO="%s"\nsource "%s/core/state.sh"\nsource "%s/tree/worktree.sh"\n'
                    'link_node_modules "%s"\n' % (repo, LIB, LIB, wt)],
                   capture_output=True, text=True, timeout=60)
    check("a tree links the main node_modules", os.path.exists(os.path.join(wt, "node_modules", ".sclaude-lock")), True)

    # Another branch checked out in the shared checkout: not touched at all.
    git(repo, "checkout", "-qb", "somebody-else")
    lock(seed, "four\n", "fourth")
    git(seed, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    head = git(repo, "rev-parse", "HEAD")
    out = refresh(root, repo)
    check("other branch: not moved", git(repo, "rev-parse", "HEAD"), head)
    check("other branch: npm not run", npm_runs(root), npm_runs_before)
    check("other branch: said so", "not main: left as it is" in out, True)
finally:
    shutil.rmtree(root, ignore_errors=True)

if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.exit(1)
print("ok")
