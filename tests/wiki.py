#!/usr/bin/env python3
"""The wiki builds from docs/, and every link between its pages lands on one.

A heading renamed or a document moved in docs/ changes the wiki's page names;
a hand-written page in wiki/pages/ that still names the old one would link to
an empty page, without an error anywhere else."""

import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []

# An edit made on GitHub since the last rebuild stops the build, named, until
# --overwrite says it was read.
with tempfile.TemporaryDirectory() as clone:
    def git(*args):
        # A name with a space, as most are: the log's fields must not split on it.
        subprocess.run(["git", "-C", clone, "-c", "user.name=A Maintainer", "-c", "user.email=t@t", *args],
                       check=True, capture_output=True)
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "Rebuild from SClaude main abc")
    git("commit", "-q", "--allow-empty", "-m", "Fix a typo on Home")
    build_py = os.path.join(ROOT, "wiki", "build.py")
    stopped = subprocess.run([sys.executable, build_py, clone], capture_output=True, text=True)
    if stopped.returncode == 0 or "Fix a typo on Home" not in stopped.stderr:
        failures.append("an edit since the last rebuild did not stop the build")
    if "Rebuild from SClaude main abc" in stopped.stderr:
        failures.append("the last rebuild itself was listed as an edit")
    if subprocess.run([sys.executable, build_py, "--overwrite", clone],
                      capture_output=True, text=True).returncode:
        failures.append("--overwrite did not build")
    git("commit", "-q", "--allow-empty", "-m", "Rebuild from SClaude main def")
    if subprocess.run([sys.executable, build_py, clone], capture_output=True, text=True).returncode:
        failures.append("a clone ending in a rebuild did not build")
    # A clone behind its remote — an edit made on GitHub not pulled yet —
    # stops the build until it is pulled.
    side = tempfile.mkdtemp()   # the remote and a second clone, removed below
    try:
        remote = os.path.join(side, "remote.git")
        subprocess.run(["git", "clone", "-q", "--bare", clone, remote], check=True, capture_output=True)
        git("remote", "add", "origin", remote)
        git("fetch", "-q", "origin")
        # A remote, but a branch that follows nothing: whether it is behind
        # cannot be told, and the build stops rather than guess.
        untracked = subprocess.run([sys.executable, build_py, clone], capture_output=True, text=True)
        if untracked.returncode == 0 or "follows no remote branch" not in untracked.stderr:
            failures.append("a branch following no remote did not stop the build")
        git("branch", "-q", "--set-upstream-to", "origin/" + subprocess.run(
            ["git", "-C", clone, "branch", "--show-current"], capture_output=True, text=True).stdout.strip())
        other = os.path.join(side, "work")
        subprocess.run(["git", "clone", "-q", remote, other], check=True, capture_output=True)
        subprocess.run(["git", "-C", other, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-q",
                        "--allow-empty", "-m", "Edit made on GitHub"], check=True, capture_output=True)
        subprocess.run(["git", "-C", other, "push", "-q"], check=True, capture_output=True)
        behind = subprocess.run([sys.executable, build_py, clone], capture_output=True, text=True)
        if behind.returncode == 0 or "behind its remote" not in behind.stderr:
            failures.append("a clone behind its remote did not stop the build")
        git("pull", "-q", "--ff-only")
        pulled = subprocess.run([sys.executable, build_py, clone], capture_output=True, text=True)
        if pulled.returncode == 0 or "Edit made on GitHub" not in pulled.stderr:
            failures.append("an edit pulled from the remote was not listed")
        git("commit", "-q", "--allow-empty", "-m", "Rebuild from SClaude main ghi")
        git("push", "-q")
    finally:
        shutil.rmtree(side, ignore_errors=True)

    # A plain folder inside the clone is not the clone: built into, it reads
    # no history, its own or the enclosing one's.
    inner = os.path.join(clone, "inner")
    os.makedirs(inner)
    git("commit", "-q", "--allow-empty", "-m", "Fix a typo on Home")
    if subprocess.run([sys.executable, build_py, inner], capture_output=True, text=True).returncode:
        failures.append("a folder inside a clone read the clone's history")

# Named no clone, the build keeps its own in the checkout's git directory,
# cloned from origin's address with .wiki.git in place of .git.
with tempfile.TemporaryDirectory() as world:
    def sh(*args, cwd=world):
        subprocess.run(["git", "-c", "user.name=A", "-c", "user.email=t@t", *args],
                       cwd=cwd, check=True, capture_output=True)
    sh("init", "-q", "--bare", "SClaude.wiki.git")
    sh("clone", "-q", os.path.join(world, "SClaude.wiki.git"), "seed")
    sh("commit", "-q", "--allow-empty", "-m", "Rebuild from SClaude main 000", cwd=os.path.join(world, "seed"))
    sh("push", "-q", "origin", "HEAD", cwd=os.path.join(world, "seed"))
    checkout = os.path.join(world, "checkout")
    shutil.copytree(os.path.join(ROOT, "wiki"), os.path.join(checkout, "wiki"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for doc in ("docs", "CONTRIBUTING.md"):
        src = os.path.join(ROOT, doc)
        (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, os.path.join(checkout, doc))
    sh("init", "-q", cwd=checkout)
    sh("remote", "add", "origin", os.path.join(world, "SClaude.git"), cwd=checkout)
    run = subprocess.run([sys.executable, os.path.join(checkout, "wiki", "build.py")],
                         capture_output=True, text=True)
    own = os.path.join(checkout, ".git", "wiki")
    if run.returncode or not os.path.exists(os.path.join(own, "Home.md")):
        failures.append("with no clone named, the build did not clone the wiki into "
                        ".git/wiki and build there:\n" + run.stdout + run.stderr)
    elif subprocess.run([sys.executable, os.path.join(checkout, "wiki", "build.py")],
                        capture_output=True, text=True).returncode:
        failures.append("a second build into the kept clone failed")

with tempfile.TemporaryDirectory() as out:
    run = subprocess.run([sys.executable, os.path.join(ROOT, "wiki", "build.py"), out],
                         capture_output=True, text=True)
    if run.returncode:
        print(run.stdout + run.stderr)
        sys.exit("FAIL: wiki/build.py exited %d" % run.returncode)
    pages = {f[:-3] for f in os.listdir(out) if f.endswith(".md")}
    for need in ("Home", "_Sidebar", "Using-sclaude", "Tools", "Inside-sclaude"):
        if need not in pages:
            failures.append("no page %s" % need)
    for f in sorted(os.listdir(out)):
        text = open(os.path.join(out, f), encoding="utf-8").read()
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            page = target.split("#")[0]
            if page not in pages:
                failures.append("%s links to %s, which is no page" % (f, target))

for line in failures:
    print("FAIL:", line)
if failures:
    sys.exit(1)
print("ok: the wiki builds, and its links land on its pages")
