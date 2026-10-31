#!/usr/bin/env python3
#
# check_next_types (sclaude/lib/worktree.sh) warns that a fresh worktree has no
# .next/types for its typecheck, and keeps quiet where the warning is wrong:
#
#   * a tsconfig.json that does not include .next/types needs no build;
#   * a .next/types already there is what the typecheck wants;
#   * a typecheck script that runs `next typegen` writes the types itself.
#
# Run it with: python3 tests/next-types.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


with open(os.path.join(LIB, "worktree.sh")) as fh:
    m = re.search(r"^check_next_types\(\) \{\n.*?^\}\n", fh.read(), re.S | re.M)
FUNC = m.group(0) if m else ""
check("function-present", bool(FUNC), True)


def warns(wt):
    out = subprocess.run(["bash", "-c", 'warn() { echo "$*"; }\n%s\ncheck_next_types "$1"'
                          % FUNC, "bash", wt], capture_output=True, text=True)
    return "no .next/types" in out.stdout


tmp = tempfile.mkdtemp()
try:
    for name, tsconfig, typecheck, types_dir, want in (
            ("no-tsconfig", None, None, False, False),
            ("tsconfig-without-types", {"include": ["**/*.ts"]}, "tsc --noEmit", False, False),
            ("fresh-worktree", {"include": [".next/types/**/*.ts"]}, "tsc --noEmit", False, True),
            ("no-package-json", {"include": [".next/types/**/*.ts"]}, None, False, True),
            ("types-already-there", {"include": [".next/types/**/*.ts"]}, "tsc --noEmit",
             True, False),
            ("typecheck-runs-typegen", {"include": [".next/types/**/*.ts"]},
             "next typegen && tsc --noEmit", False, False),
            ("typegen-after-cleanup", {"include": [".next/types/**/*.ts"]},
             "rm -rf .next/types && next typegen && tsc --noEmit", False, False),
            ("typegen-in-another-script", {"include": [".next/types/**/*.ts"]},
             "tsc --noEmit", False, True)):
        wt = os.path.join(tmp, name)
        os.makedirs(wt)
        if tsconfig is not None:
            with open(os.path.join(wt, "tsconfig.json"), "w") as fh:
                json.dump(tsconfig, fh)
        if typecheck is not None:
            scripts = {"typecheck": typecheck}
            if name == "typegen-in-another-script":
                scripts["types"] = "next typegen"
            with open(os.path.join(wt, "package.json"), "w") as fh:
                json.dump({"scripts": scripts}, fh, indent=2)
        if types_dir:
            os.makedirs(os.path.join(wt, ".next", "types"))
        check(name, warns(wt), want)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
