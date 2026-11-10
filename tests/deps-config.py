#!/usr/bin/env python3
#
# What sclaude runs to install a product's dependencies and start its dev
# server is the product's to say (`deps`, `commands.dev` in its config); the
# npm spellings are only presets for a config that names none.
#
# Run it with: python3 tests/deps-config.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.abspath(os.path.join(HERE, "..", "sclaude", "lib"))
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def bash(repo, body):
    script = """
set -uo pipefail
info() { echo "INFO $*"; }
warn() { echo "WARN $*"; }
REPO="%s"
source "%s/core/state.sh"
source "%s/core/project.sh"
source "%s/tree/worktree.sh"
%s
""" % (repo, LIB, LIB, LIB, body)
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=60, stdin=subprocess.DEVNULL).stdout.strip()


def config(repo, data):
    os.makedirs(os.path.join(repo, ".sclaude"), exist_ok=True)
    with open(os.path.join(repo, ".sclaude", "config.json"), "w") as fh:
        json.dump(data, fh)


root = tempfile.mkdtemp(prefix="sclaude-deps-")
try:
    plain = os.path.join(root, "plain")
    config(plain, {})
    check("presets: npm's",
          bash(plain, 'for k in dir lockfile install ci cache; do deps_get $k "$REPO"; done; '
                      'dev_command "$REPO"').splitlines(),
          ["node_modules", "package-lock.json", "npm install", "npm ci", ".next/dev", "npm run dev"])

    own = os.path.join(root, "own")
    config(own, {"commands": {"dev": "make serve"},
                 "deps": {"dir": "vendor", "lockfile": "deps.lock", "install": "make deps",
                          "ci": "make deps-clean", "cache": ""}})
    check("a product's own: read from its config",
          bash(own, 'for k in dir lockfile install ci cache; do echo "[$(deps_get $k "$REPO")]"; done; '
                    'dev_command "$REPO"').splitlines(),
          ["[vendor]", "[deps.lock]", "[make deps]", "[make deps-clean]", "[]", "make serve"])

    # A folder named "" is no dependencies at all: nothing is linked, asked or
    # removed — and above all not the tree, which "$wt/" would be.
    none = os.path.join(root, "none")
    config(none, {"deps": {"dir": "", "lockfile": ""}})
    check("none: no dependencies handled",
          bash(none, 'deps_named "$REPO" && echo yes || echo no; check_deps "$REPO"; echo "[$(ls -A "$REPO")]"'),
          "no\n[.sclaude]")

    # An install is the product's command, and its mark lands in its folder.
    os.makedirs(os.path.join(own, "vendor"))
    with open(os.path.join(own, "deps.lock"), "w") as fh:
        fh.write("v1\n")
    config(own, {"deps": {"dir": "vendor", "lockfile": "deps.lock",
                          "install": "echo ran > installed", "cache": ""}})
    bash(own, 'deps_install "$REPO"')
    check("install: the product's command ran", os.path.exists(os.path.join(own, "installed")), True)
    check("install: the mark is in the product's folder",
          os.path.exists(os.path.join(own, "vendor", ".sclaude-lock")), True)
    # No cache named: nothing is removed.
    os.makedirs(os.path.join(own, ".next", "dev"))
    bash(own, 'deps_drop_cache "$REPO"')
    check("cache: none named, none removed", os.path.isdir(os.path.join(own, ".next", "dev")), True)

    # A dev server is known alive by the mark in its environment, whatever it
    # runs: a process sclaude did not start in this tree is not it.
    mark = subprocess.Popen(["sleep", "30"], env=dict(os.environ, SCLAUDE_DEV_TREE=own))
    try:
        check("alive: a process carrying the tree's mark",
              bash(own, 'dev_alive "$REPO" && echo yes || echo no'), "yes")
        check("alive: another tree's mark is not this one's",
              bash(plain, 'dev_alive "$REPO" && echo yes || echo no'), "no")
    finally:
        mark.kill()
        mark.wait()
finally:
    shutil.rmtree(root, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
