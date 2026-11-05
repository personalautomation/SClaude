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


class RenderError(Exception):
    pass


def read_include(prompts_dir, name):
    path = os.path.join(prompts_dir, "_%s.md" % name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        raise RenderError("no include file: %s" % path)


def render(text, prompts_dir, values, blocks):
    """Assemble the prompt. values are substitutions, blocks embedded pieces."""
    # The includes first: they contain both conditionals and substitutions. One
    # level, without nesting — an include inside an include would mean the
    # prompts had acquired a structure that a template is not the thing to fix.
    def splice(match):
        return read_include(prompts_dir, match.group(1)).rstrip("\n")

    text = INCLUDE.sub(splice, text)

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
        body = blocks.get(match.group(1)) or ""
        body = body.strip("\n")
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

    try:
        sys.stdout.write(render(text, prompts_dir, values, blocks))
    except RenderError as exc:
        sys.stderr.write("%s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
