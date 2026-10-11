#!/usr/bin/env python3
#
# A product, and a person, add to the prompts sclaude ships, never replace them.
#
#   * .sclaude/team/prompts/<step>.md and .sclaude/people/<name>/prompts/<step>.md
#     are appended, in that order, each under a heading naming its file;
#   * another step's file, another person's, or an empty one adds nothing;
#   * render_prompt ends by calling it, so every step's prompt gets them.
#
# Run it with: python3 tests/prompt-additions.py
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


RUN = open(os.path.join(LIB, "run.sh"), encoding="utf-8").read()
body = re.search(r"^prompt_additions\(\) \{\n.*?^\}\n", RUN, re.S | re.M).group(0)

tmp = tempfile.mkdtemp()
try:
    def put(rel, text):
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def additions(step, name="ann"):
        script = 'developer_name() { echo %s; }\n%s\nprompt_additions %s "%s"' % (name, body, step, tmp)
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True).stdout

    check("nothing-to-add", additions("review"), "")
    put(".sclaude/team/prompts/review.md", "Run npm run check:storage after upload changes.\n")
    put(".sclaude/people/ann/prompts/review.md", "I like small commits.\n")
    put(".sclaude/people/bob/prompts/review.md", "Bob's own.\n")
    put(".sclaude/team/prompts/code.md", "")
    out = additions("review")
    check("team-then-person", out.index("check:storage") < out.index("small commits"), True)
    check("team-heading", "**This product adds** (`.sclaude/team/prompts/review.md`)" in out, True)
    check("person-heading", "**ann adds** (`.sclaude/people/ann/prompts/review.md`)" in out, True)
    check("not-another-persons", "Bob's own" in out, False)
    check("empty-adds-nothing", additions("code"), "")
    check("other-step-adds-nothing", "check:storage" in additions("plan"), False)
    check("no-name-team-only", "small commits" in additions("review", name=""), False)

    rp = re.search(r"^render_prompt\(\) \{\n.*?^\}\n", RUN, re.S | re.M).group(0)
    check("render-prompt-appends", 'prompt_additions "$step"' in rp, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
