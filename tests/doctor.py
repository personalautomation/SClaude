#!/usr/bin/env python3
#
# A bench for `sclaude doctor` on a machine that has nothing set up: an empty
# HOME, no git identity, outside any repository. It must not crash, must fail
# (exit 1), and every gap it finds must come with the command that fixes it —
# that is the whole of what it is for.
#
# Run it with: python3 tests/doctor.py
import json
import os
import subprocess
import sys
import tempfile


def _cfg(path):
    """The path of a product's config, its .sclaude/ folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


with tempfile.TemporaryDirectory() as home:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and not k.startswith("SCLAUDE_")}
    env.update(HOME=home, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               SCLAUDE_NO_SYNC="1", NO_COLOR="1")
    # The instruments repository's own config would still name a user.email;
    # an explicit empty one stands for a machine that never set it.
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "user.email"
    env["GIT_CONFIG_VALUE_0"] = ""
    done = subprocess.run([os.path.join(ROOT, "bin", "sclaude"), "doctor"],
                          cwd=home, env=env, capture_output=True, text=True,
                          timeout=120)
    out = done.stdout
    check("fails-when-something-is-missing", done.returncode, 1)
    check("no-traceback", "Traceback" in done.stderr + out, False)
    lines = out.splitlines()
    for gap, fix in (("no git user.email", "git config --global user.email"),
                     ("the pr skill is missing", "./install.sh")):
        at = next((i for i, line in enumerate(lines) if gap in line), None)
        check("reports-%s" % gap.replace(" ", "-"), at is not None, True)
        if at is not None:
            check("fix-for-%s" % gap.replace(" ", "-"),
                  fix in (lines[at + 1] if at + 1 < len(lines) else ""), True)
    check("outside-a-repo-said", "not inside a git repository" in out, True)

    # A node on PATH that dies at the loader is a gap, not a ✓, and the fix
    # names the package that carries the missing library.
    fake = os.path.join(home, "fake-bin")
    os.makedirs(fake)
    with open(os.path.join(fake, "node"), "w") as fh:
        fh.write("#!/bin/sh\necho 'node: error while loading shared libraries: "
                 "libatomic.so.1: cannot open shared object file: "
                 "No such file or directory' >&2\nexit 127\n")
    os.chmod(os.path.join(fake, "node"), 0o755)
    broken = dict(env, PATH=fake + os.pathsep + env["PATH"])
    done = subprocess.run([os.path.join(ROOT, "bin", "sclaude"), "doctor"],
                          cwd=home, env=broken, capture_output=True, text=True,
                          timeout=120)
    lines = done.stdout.splitlines()
    at = next((i for i, l in enumerate(lines)
               if "node does not start: libatomic.so.1 is missing" in l), None)
    check("broken-node-reported", at is not None, True)
    if at is not None:
        check("broken-node-names-the-package",
              "sudo apt install libatomic1" in (lines[at + 1] if at + 1 < len(lines) else ""), True)

    # A project's own checks: run in its root, a pass is a ✓, a failure a !
    # with the check's last line and the fix under it.
    repo = os.path.join(home, "product")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", repo], env=env, check=True)
    with open(_cfg(os.path.join(repo, ".sclaude/config.json")), "w") as fh:
        json.dump({"doctor": [
            {"what": "the thing that is there", "check": "test -f .sclaude/config.json"},
            {"what": "the thing that is not", "check": "echo noise; echo it is missing; exit 1",
             "fix": "make-it-so"},
        ]}, fh)
    done = subprocess.run([os.path.join(ROOT, "bin", "sclaude"), "doctor"],
                          cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    lines = done.stdout.splitlines()
    check("project-check-passes", any("✓ the thing that is there" in l for l in lines), True)
    at = next((i for i, l in enumerate(lines) if "! the thing that is not: it is missing" in l), None)
    check("project-check-fails-with-its-last-line", at is not None, True)
    if at is not None:
        check("project-check-names-its-fix",
              "make-it-so" in (lines[at + 1] if at + 1 < len(lines) else ""), True)

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
