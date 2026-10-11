#!/usr/bin/env python3
#
# The manuals' tables of contents — for step 1.
#
# The manuals describe the product as a person sees it: business context that is
# not in the code, and always fresh — by the project's rule both pages are
# edited in the same PR as the feature. They cannot be read whole, there are
# over four thousand lines of TSX there, so the prompt taught the session to go
# in through the SECTIONS array.
#
# Parsing that array is deterministic, and there is no reason for a session to
# do it: two reads of large files for the sake of thirty lines the orchestrator
# gets with a grep. The session chooses the sections — that is judgement and
# stays with it; the orchestrator finds them.
import json
import os
import re
import sys

# { id: "account", title: "Creating an account" } — the order of the fields is
# not fixed, so we search by name rather than by position.
ENTRY = re.compile(
    r"\{\s*(?:id:\s*[\"'](?P<id>[^\"']+)[\"']\s*,\s*title:\s*[\"'](?P<title>[^\"']+)[\"']"
    r"|title:\s*[\"'](?P<title2>[^\"']+)[\"']\s*,\s*id:\s*[\"'](?P<id2>[^\"']+)[\"'])")

def pages(root):
    """The manuals this project has, from `.sclaude.json`.

    They were two paths written here, and they were one product's: a repository
    that kept its manuals anywhere else got an empty block and no explanation.
    A project that declares none has none, and the block drops out of step 1's
    prompt by itself — which is the honest outcome rather than a heading over
    emptiness.
    """
    try:
        with open(os.path.join(root, ".sclaude.json"), encoding="utf-8") as fh:
            declared = json.load(fh).get("manuals") or []
    except (OSError, ValueError):
        return []
    out = []
    for entry in declared:
        if isinstance(entry, dict) and entry.get("path"):
            out.append((entry["path"], entry.get("what") or ""))
        elif isinstance(entry, str):
            out.append((entry, ""))
    return out


def sections(path):
    """The (id, title) pairs from the SECTIONS array, or an empty list."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    start = text.find("const SECTIONS")
    if start < 0:
        return []
    # To the array's end: the closing bracket at the declaration's level.
    end = text.find("]", start)
    if end < 0:
        return []
    out = []
    for m in ENTRY.finditer(text[start:end]):
        ident = m.group("id") or m.group("id2")
        title = m.group("title") or m.group("title2")
        if ident and title:
            out.append((ident, title))
    return out


def render(root):
    blocks = []
    for rel, caption in pages(root):
        path = os.path.join(root, rel)
        rows = sections(path)
        if not rows:
            continue
        blocks.append("**`%s`**%s:" % (rel, " — %s" % caption if caption else ""))
        blocks.append("")
        for ident, title in rows:
            blocks.append("- `%s` — %s" % (ident, title))
        blocks.append("")
    if not blocks:
        return ""
    # The prompt supplies the section's heading — only the content is here.
    out = []
    out.append("All sections of the manuals. The pages themselves run to "
               "thousands of lines — don't read them whole. Pick the "
               "sections the feature touches and open **only those**, by "
               "grepping for the section `id`.")
    out.append("")
    out.extend(blocks)
    return "\n".join(out).rstrip("\n")


def main():
    if len(sys.argv) < 2:
        return 0
    try:
        sys.stdout.write(render(sys.argv[1]))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
