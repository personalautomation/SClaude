#!/usr/bin/env python3
"""The wiki builds from docs/, and every link between its pages lands on one.

A heading renamed or a document moved in docs/ changes the wiki's page names;
a hand-written page in wiki/pages/ that still names the old one would link to
an empty page, without an error anywhere else."""

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []

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
