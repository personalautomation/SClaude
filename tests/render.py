#!/usr/bin/env python3
#
# A test bench for assembling prompts. The main thing here is the values sed
# broke on: it expanded `&` into the matched text, and a `|` brought the whole
# command down.
#
# Run it with: python3 tests/render.py
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
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
                  "db-api": "http://127.0.0.1:55001", "shared-db": "dev",
                  "db-cli": "npx --yes supabase", "dev-cmd": "npm run dev"}
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

        # A block too long for the prompt goes to a file in the feature's tree,
        # and the prompt says where; a short one, or one with no tree to go
        # to, stays inline.
        root = os.path.join(tmp, "tree")
        os.makedirs(os.path.join(root, ".sclaude", "local", "feature"))
        big = "".join("a line of the block, %06d — ё\n" % i for i in range(3000))
        got = render("before\n<block:user-request>\nafter", tmp, {}, {"user-request": big}, root)
        rel = ".sclaude/local/feature/prompt-user-request.md"
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            spilt = fh.read()
        check("long-block-spilled", (rel in got, len(got) < 1000, spilt), (True, True, big))
        check("short-block-inline", render("<block:x>", tmp, {}, {"x": "short"}, root), "short\n")
        check("no-tree-inline", render("<block:x>", tmp, {}, {"x": big}), big)

        # The blocks reach render_prompt.py as files (SCLAUDE_BLOCKS_DIR): a
        # variable over 128 KiB would not start it at all.
        bdir = os.path.join(tmp, "blocks")
        os.makedirs(bdir)
        with open(os.path.join(bdir, "PR_CONTEXT"), "w", encoding="utf-8") as fh:
            fh.write(big * 5)
        with open(os.path.join(tmp, "step.md"), "w", encoding="utf-8") as fh:
            fh.write("head\n<block:pr-context>\ntail\n")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude",
                              "lib", "cycle", "render_prompt.py")
        res = subprocess.run([sys.executable, script, os.path.join(tmp, "step.md"), tmp],
                             env=dict(os.environ, SCLAUDE_BLOCKS_DIR=bdir, SCLAUDE_SPILL_ROOT=root),
                             capture_output=True, text=True)
        # A stray byte in gathered text (a test's raw output) does not stop
        # the step from starting.
        with open(os.path.join(bdir, "REGRESSION"), "wb") as fh:
            fh.write(b"failed \xff here")
        with open(os.path.join(tmp, "fix.md"), "w", encoding="utf-8") as fh:
            fh.write("<block:regression>\n")
        bad = subprocess.run([sys.executable, script, os.path.join(tmp, "fix.md"), tmp],
                             env=dict(os.environ, SCLAUDE_BLOCKS_DIR=bdir),
                             capture_output=True, text=True)
        check("stray-byte", (bad.returncode, "failed" in bad.stdout), (0, True))
        check("blocks-from-files", (res.returncode, ".sclaude/local/feature/prompt-pr-context.md"
                                    in res.stdout, res.stdout.startswith("head\n")), (0, True, True))

        # Step 4's checklist before the first edit follows where the gathered
        # text is: the threads and resolved threads in files only when the
        # snapshot points there, the request comment in its file or below.
        with open(os.path.join(prompts, "review.md"), encoding="utf-8") as fh:
            review = fh.read()
        import pr_context
        import render_prompt
        threads_md = pr_context.pr_file("threads.md")
        resolved_md = pr_context.pr_file("resolved.md")
        gate = "Before your first edit"

        def review_with(pr_ctx, request, root=""):
            out = render(review, prompts, values, dict(blocks, **{"pr-context": pr_ctx,
                                                                  "user-request": request}), root)
            return out[out.find(gate):out.find("1. Handle each comment")]
        small = review_with("the checks", "the request")
        # The inline request comment is where the checklist says: after it.
        whole = render(review, prompts, values, dict(blocks, **{"user-request": "THE REQUEST"}))
        check("request-quoted-below", whole.find(gate) < whole.find("THE REQUEST"), True)
        check("gate-inline", (gate in small, "threads.md" in small, "resolved.md" in small,
                              "quoted below where recording" in small, "prompt-user-request" in small,
                              "read the threads already resolved on it" in small),
              (True, False, False, True, False, True))
        files = review_with("see `%s` and `%s`" % (threads_md, resolved_md), big, root)
        check("gate-files", (threads_md in files, resolved_md in files,
                             render_prompt.SPILL.format("user-request") in files,
                             "quoted below where recording" in files), (True, True, True, False))
        bare = review_with("", "")
        check("gate-bare", (gate in bare, "open thread" in bare, "User request" in bare,
                            "plan.md" in bare), (True, False, False, True))
        # The paths render_prompt.py looks for are the ones pr_context.py writes.
        check("pr-files-agree", sorted(render_prompt.PR_FILES.values()),
              sorted([resolved_md, threads_md]))

        # The retrospective reads the journal of the feature's Telegram topic
        # when there is one, and is told to look in it for what was said twice
        # or for nothing; without one it is not named.
        with open(os.path.join(prompts, "retro.md"), encoding="utf-8") as fh:
            retro = fh.read()
        kept = render(retro, prompts, {"telegram-log": "/wt/.sclaude/local/feature/telegram-log.jsonl",
                                       "terminal": "/wt/terminal.txt"}, {})
        none = render(retro, prompts, {"telegram-log": "", "terminal": "/wt/terminal.txt"}, {})
        check("retro-reads-the-journal",
              ("`/wt/.sclaude/local/feature/telegram-log.jsonl`" in kept, "and the Telegram journal" in kept,
               "the same thing said twice or more" in kept),
              (True, True, True))
        check("retro-without-a-journal", ("Telegram journal" in none, "telegram-log" in none,
                                          "the same thing said twice or more" in none),
              (False, False, True))

        # Five assemblies with the blocks filled, five with them empty, and the
        # rest are the checks above.
        total = 39
        for name, want, got in failures:
            print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
        print("%d/%d passed" % (total - len(failures), total))
        return 1 if failures else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
