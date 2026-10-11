#!/usr/bin/env python3
#
# A test bench for assembling prompts. The main thing here is the values sed
# broke on: it expanded `&` into the matched text, and a `|` brought the whole
# command down.
#
# Run it with: python3 tests/render.py
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
from render_prompt import RenderError, render

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def main():
    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "_shared.md"), "w", encoding="utf-8") as fh:
            fh.write("shared text\n")

        # The substitution is literal: exactly what sed tripped over.
        check("ampersand",
              render("PR <pr>", tmp, {"pr": "a&b"}, {}),
              "PR a&b")
        check("pipe",
              render("PR <pr>", tmp, {"pr": "a|b"}, {}),
              "PR a|b")
        check("backslash",
              render("PR <pr>", tmp, {"pr": r"a\1b"}, {}),
              r"PR a\1b")
        check("newline",
              render("X <pr> Y", tmp, {"pr": "one\ntwo"}, {}),
              "X one\ntwo Y")
        # Non-ASCII data on purpose: this check guards the fact that a literal
        # str.replace does not care what alphabet the value is in.
        check("cyrillic",
              render("<feature>", tmp, {"feature": "фича-раз"}, {}),
              "фича-раз")

        # Includes.
        check("include",
              render("before\n<include:shared>\nafter", tmp, {}, {}),
              "before\nshared text\nafter")

        # Conditionals.
        check("if-set",
              render("a<if:issue>-yes-</if:issue>b", tmp, {"issue": "75"}, {}),
              "a-yes-b")
        check("if-empty",
              render("a<if:issue>-yes-</if:issue>b", tmp, {"issue": ""}, {}),
              "ab")
        check("if-missing",
              render("a<if:issue>-yes-</if:issue>b", tmp, {}, {}),
              "ab")

        # Computed blocks: an empty one takes its line away.
        check("block-filled",
              render("before\n<block:checks>\nafter", tmp, {}, {"checks": "a table"}),
              "before\na table\nafter")
        check("block-empty",
              render("before\n<block:checks>\nafter", tmp, {}, {"checks": ""}),
              "before\nafter")
        check("block-absent",
              render("before\n<block:checks>\nafter", tmp, {}, {}),
              "before\nafter")

        # A block with arbitrary content — what the whole thing was for.
        body = "| a | b |\n| & | \\1 |"
        check("block-arbitrary",
              render("<block:x>", tmp, {}, {"x": body}),
              body + "\n")

        # An unrecognised tag is an error rather than text for the model.
        try:
            render("<include:missing>", tmp, {}, {})
            failures.append(("unknown-include", "RenderError", "no error"))
        except RenderError:
            pass

        try:
            render("<if:a>x</if:b>", tmp, {}, {})
            failures.append(("mismatched-if", "RenderError", "no error"))
        except RenderError:
            pass

        # The real step and epilogue prompts. What is checked is not the text
        # but that they assemble at all: a typo in a tag (<block:issue-chan>) has
        # until now been discovered by launching a session, and that costs as
        # much as the session itself.
        prompts = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "sclaude", "prompts")
        values = {"feature": "test", "pr": "1", "issue": "68",
                  "labels": "deployed-preview",
                  "dev-url": "http://test.localhost:3000", "dev-port": "3100",
                  "db-api": "http://127.0.0.1:55001", "shared-db": "dev"}
        blocks = {"issue-context": "the issue", "manual-toc": "the contents",
                  "pr-context": "the checks", "feature-in-history": "history",
                  "issue-chain": "the chain", "deploy-outcome": "shipped",
                  "acceptance": "the criteria"}
        for name in ("plan", "code", "pr", "review", "status"):
            path = os.path.join(prompts, "%s.md" % name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            try:
                out = render(text, prompts, values, blocks)
                if not out.strip():
                    failures.append(("real-%s" % name, "a non-empty prompt", ""))
            except RenderError as exc:
                failures.append(("real-%s" % name, "assembly without an error", str(exc)))

        # The same prompts with every block empty. This is the ordinary case for
        # the acceptance block — no issue, no gh, a feature planned before the
        # criteria existed — and the prompts have to read as prose without it,
        # not as a reference to something that isn't there.
        for name in ("plan", "code", "pr", "review", "status"):
            path = os.path.join(prompts, "%s.md" % name)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            try:
                out = render(text, prompts, values,
                             dict((key, "") for key in blocks))
            except RenderError as exc:
                failures.append(("bare-%s" % name, "assembly without an error",
                                 str(exc)))
                continue
            if "<block:" in out:
                failures.append(("bare-%s" % name, "no block tags left", out))

        # An empty block must not leave a heading hanging: a promise of "here it
        # is in full" with emptiness below it is worse than no promise.
        with open(os.path.join(prompts, "status.md"), encoding="utf-8") as fh:
            bare = render(fh.read(), prompts, values,
                          dict(blocks, **{"issue-chain": "", "deploy-outcome": ""}))
        check("status-no-dangling-block", "<block:" in bare, False)

        # Five assemblies with the blocks filled, five with them empty, and the
        # rest are the checks above.
        total = 27
        for name, want, got in failures:
            print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
        print("%d/%d passed" % (total - len(failures), total))
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
