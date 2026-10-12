#!/usr/bin/env python3
#
# The product's manuals as its config names them, in one line for a prompt.
#
# The prompts used to name one product's two pages outright. A product names
# its own under `manuals` in .sclaude/config.json, and the prompts say those.
#
#   manual_names.py <tree>
import json
import os
import sys


def names(tree):
    try:
        with open(os.path.join(tree, ".sclaude", "config.json"), encoding="utf-8") as fh:
            manuals = json.load(fh).get("manuals") or []
    except (OSError, ValueError, AttributeError):
        manuals = []
    named = []
    for entry in manuals if isinstance(manuals, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            what = entry.get("what")
            named.append("`%s` (%s)" % (entry["path"], what) if isinstance(what, str) and what
                         else "`%s`" % entry["path"])
    if not named:
        return "none: the product names none under `manuals` in .sclaude/config.json"
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]


if __name__ == "__main__":
    print(names(sys.argv[1] if len(sys.argv) > 1 else "."))
