#!/usr/bin/env python3
# The files beside a feature's state (.sclaude/local/feature/) are listed in
# sclaude/lib/core/feature_files.py: every name the code writes out in full is
# there, and every entry there is named somewhere. A mistyped name reads as a
# file that is not there, without an error.
#
# Run it with: python3 tests/feature-files.py
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib", "core"))
import feature_files  # noqa: E402

failures = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SKIP_EXT = (".png", ".jpg", ".mp4", ".pyc", ".gif", ".webm")
OWN = os.path.join(ROOT, "sclaude", "lib", "core", "feature_files.py")


def sources(*tops):
    for top in tops:
        start = os.path.join(ROOT, top)
        if os.path.isfile(start):
            yield start
            continue
        for folder, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if not name.endswith(SKIP_EXT):
                    yield os.path.join(folder, name)


def text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


# A name written out in full: what follows the directory up to a quote, a
# space or the end of the word. A shell or Python variable in it stands for
# any part of a name.
NAME = re.compile(re.escape(feature_files.DIR) + r"/([A-Za-z0-9_.$*{}<>-]*[A-Za-z0-9_}>*])")
code = [p for p in sources("sclaude", "bin", "keepawake", "skills") if p != OWN]
named = {}
for path in code:
    for m in NAME.finditer(text(path)):
        name = re.sub(r"\$\{[^}]*\}|\$[A-Za-z0-9_]+|\{[a-z_]*\}|\*", "x", m.group(1))
        # A path that is a variable whole, or a placeholder in a comment, is
        # code for any file there (the logs' helpers), no name of its own.
        if name == "x" or name.startswith("<") or m.group(1).startswith("$"):
            continue
        named.setdefault(name, os.path.relpath(path, ROOT))

check("the code names many files there (the scan works)", len(named) > 30)
unknown = sorted("%s (%s)" % (n, w) for n, w in named.items() if not feature_files.describe(n))
check("every file named there is in feature_files.py: %s" % unknown, not unknown)

# Every entry is named somewhere — in full, or by its own name where a module
# builds the path from a directory it holds (state_file's lock, the local
# review's family, a log under logs/).
everything = "\n".join(text(p) for p in code + list(sources("docs", "tests")))
stale = []
for pattern, _ in feature_files.FILES:
    literal = pattern.split("<", 1)[0]
    if literal not in everything:
        stale.append(pattern)
check("every entry of feature_files.py is named somewhere: %s" % stale, not stale)
patterns = [p for p, _ in feature_files.FILES]
check("feature_files.py lists each name once", len(patterns) == len(set(patterns)))
check("a name in a listed directory is that directory's", feature_files.describe("logs/local-1.log") is not None)
check("a misspelt name is not taken for a listed one", feature_files.describe("sesion-done") is None)

if failures:
    print("%d failed" % len(failures))
    sys.exit(1)
print("feature-files: ok")
