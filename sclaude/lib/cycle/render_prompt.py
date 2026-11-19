#!/usr/bin/env python3
#
# Assembling a step's prompt from a template file.
#
# The prompts are kept outside the script: they are edited more often than the
# logic, and keeping them as strings in bash would mean rebuilding the
# orchestrator for the sake of a comma.
#
# Substitution used to go through `sed s|<feature>|...|`, and that was a mistake
# waiting to happen. In sed's replacement `&` means "the whole matched text" and
# `|` is the delimiter itself: a value with an ampersand was silently corrupted,
# a value with a bar broke the command. Through <feature> that is unreachable
# (slugify leaves only [a-z0-9-]), but <transcript> substitutes unsanitised
# paths, and embedding gathered data — the issue, the PR's checks, the manuals'
# tables of contents — brings in text of any kind at all. So substitution here is
# literal, str.replace: it has no metacharacters whatsoever.
#
# There are exactly four forms, with no expressions and no loops. No template
# engine is needed here: if a prompt requires more, that is a question about the
# prompt.
#
#   <include:name>           insert sclaude/prompts/_name.md
#   <if:key>…</if:key>       keep if the key is non-empty, otherwise drop
#   <feature> <pr> <issue>   literal substitution of the value
#   <block:name>             embed a computed block; empty drops the line
#
# The values arrive as environment variables rather than argv: an issue's body
# and a PR's list of comments run to kilobytes, and ARG_MAX does not stretch.
# The blocks arrive as files in SCLAUDE_BLOCKS_DIR, one per block named as its
# variable would be: a variable is held to 128 KiB too (MAX_ARG_STRLEN), and
# a long feature's blocks outgrow it.
#
# A block over BLOCK_INLINE_MAX does not go into the prompt: it is written to
# .sclaude/local/feature/prompt-<name>.md under SCLAUDE_SPILL_ROOT (the
# feature's tree) and the prompt says where, with its size. The prompt goes to
# claude as one argument, held to the same limit, and what it carries is read
# at every turn: instructions stay in it whole, gathered text is read from a
# file once, as much of it as the session needs.
import os
import re
import sys

# The includes are prefixed with an underscore so that the search for a step's
# prompt ($PROMPTS/<step>.md) cannot stumble on them by a step's name.
INCLUDE = re.compile(r"<include:([a-z0-9-]+)>")
BLOCK = re.compile(r"^[ \t]*<block:([a-z0-9-]+)>[ \t]*\n?", re.M)
CONDITIONAL = re.compile(r"<if:([a-z0-9-]+)>(.*?)</if:\1>(\n*)", re.S)
# Any remaining tag of the form <something> from our vocabulary.
LEFTOVER = re.compile(r"<(include|if|block):[a-z0-9-]*>")


BLOCK_INLINE_MAX = 32000
SPILL = ".sclaude/local/feature/prompt-{}.md"


# The parts of the pull request's snapshot that pr_context.py writes to files
# when they are too long for the prompt, by the key that tells the prompt so.
PR_FILES = {"pr-threads-file": ".sclaude/local/feature/pr/threads.md",
            "pr-resolved-file": ".sclaude/local/feature/pr/resolved.md"}


def spills(body, root):
    return bool(root) and len(body.encode("utf-8")) > BLOCK_INLINE_MAX


def placed(text, blocks, spill_root):
    """Each block the template names, as it goes into the prompt — itself, or
    where it was written (spilled) — and the keys the prompt's conditionals
    read about it: `<block>-shown` for one not empty, then `<block>-in-file`
    for one in a file or `<block>-inline` for one in the prompt, and
    PR_FILES' keys for the parts of the pull request's snapshot that it
    points to files for. Decided before the conditionals, which read them."""
    bodies, keys = {}, {}
    for name in set(BLOCK.findall(text)):
        body = (blocks.get(name) or "").strip("\n")
        if not body:
            continue
        bodies[name] = spilled(name, body, spill_root)
        keys[name + "-shown"] = "1"
        keys[name + ("-inline" if bodies[name] == body else "-in-file")] = "1"
    snapshot = blocks.get("pr-context") or ""
    for key, path in PR_FILES.items():
        if path in snapshot:
            keys[key] = "1"
    return bodies, keys


def spilled(name, body, root):
    """The block, or where it was written when it is too long to be inlined."""
    size = len(body.encode("utf-8"))
    if not spills(body, root):
        return body
    rel = SPILL.format(name)
    try:
        with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
    except OSError:
        return body
    return ("**This part is in `%s`** — %d KB, %d lines, too long to sit in this "
            "prompt. Read it whole before you act on it, in parts with offset and "
            "limit if it does not come in one read."
            % (rel, (size + 1023) // 1024, body.count("\n") + 1))


class RenderError(Exception):
    pass


def read_include(prompts_dir, name):
    path = os.path.join(prompts_dir, "_%s.md" % name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        raise RenderError("no include file: %s" % path)


def render(text, prompts_dir, values, blocks, spill_root=""):
    """Assemble the prompt. values are substitutions, blocks embedded pieces;
    a block too long for the prompt goes to a file under spill_root."""
    # The includes first: they contain both conditionals and substitutions. One
    # level, without nesting — an include inside an include would mean the
    # prompts had acquired a structure that a template is not the thing to fix.
    def splice(match):
        return read_include(prompts_dir, match.group(1)).rstrip("\n")

    text = INCLUDE.sub(splice, text)
    bodies, keys = placed(text, blocks, spill_root)
    values = dict(keys, **values)

    # The conditionals go by whether a key is non-empty. An empty key takes the
    # whole block away along with the trailing newlines, otherwise a hole of
    # blank lines is left in its place.
    def choose(match):
        key, body, tail = match.group(1), match.group(2), match.group(3)
        if (values.get(key) or "").strip():
            # The trailing newlines are part of the prompt's layout, and when
            # the block stays they stay with it: otherwise the paragraph sticks
            # to the next one.
            return body + tail
        # A dropped block takes them with it, otherwise a hole gapes in its
        # place.
        return ""

    # In a loop: a conditional can expose a neighbouring one after an include
    # has been spliced in.
    for _ in range(5):
        new = CONDITIONAL.sub(choose, text)
        if new == text:
            break
        text = new

    # The computed blocks. An empty block removes its line entirely — a prompt
    # with a heading "here are the checks:" and emptiness below it is worse than
    # one without the heading.
    #
    # A block is gathered text — an issue body, a PR comment — and may quote our
    # own tags: an issue about these very prompts does. So each block is held
    # back as a placeholder and spliced in only after the substitutions and the
    # leftover check, which then see the template alone. Otherwise a quoted
    # `<if:issue>` stopped the step from starting, and a quoted `<issue>` was
    # silently rewritten into a number.
    held = []

    def inject(match):
        body = bodies.get(match.group(1)) or ""
        if not body:
            return ""
        held.append(body + "\n")
        return "\x00%d\x00" % (len(held) - 1)

    text = BLOCK.sub(inject, text)

    # The substitutions, literal.
    for key, value in values.items():
        text = text.replace("<%s>" % key, value)

    # A typo in a tag used to travel to the model as text. It is cheaper to
    # fail here, before the session starts, where it costs nothing.
    left = LEFTOVER.search(text)
    if left:
        raise RenderError("unresolved tag in the prompt: %s" % left.group(0))
    return re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], text)


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: render_prompt.py <prompt-file> <prompts-dir>\n")
        return 2
    path, prompts_dir = sys.argv[1], sys.argv[2]
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        sys.stderr.write("cannot read the prompt: %s\n" % exc)
        return 1

    # SCLAUDE_V_* are substitutions, SCLAUDE_B_* computed blocks.
    values, blocks = {}, {}
    for name, value in os.environ.items():
        if name.startswith("SCLAUDE_V_"):
            values[name[len("SCLAUDE_V_"):].lower().replace("_", "-")] = value
        elif name.startswith("SCLAUDE_B_"):
            blocks[name[len("SCLAUDE_B_"):].lower().replace("_", "-")] = value
    folder = os.environ.get("SCLAUDE_BLOCKS_DIR") or ""
    for name in (os.listdir(folder) if folder and os.path.isdir(folder) else []):
        # Not strict: a block is gathered text — a failing test's raw output
        # may hold a stray byte — and the environment it replaced decoded
        # such a byte rather than refuse the whole prompt.
        with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as fh:
            blocks[name.lower().replace("_", "-")] = fh.read()

    try:
        sys.stdout.write(render(text, prompts_dir, values, blocks,
                                os.environ.get("SCLAUDE_SPILL_ROOT") or ""))
    except RenderError as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
