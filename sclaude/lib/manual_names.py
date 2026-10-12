#!/usr/bin/env python3
#
# The product's manuals as its config names them, in one line for a prompt.
#
# The prompts used to name one product's two pages outright. A product names
# its own under `manuals` in .sclaude/config.json, read by manual_toc.pages,
# the same reading step 1's table of contents uses.
#
#   manual_names.py <tree>
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from manual_toc import pages  # noqa: E402


def names(tree):
    named = ["`%s` (%s)" % (path, what) if what else "`%s`" % path for path, what in pages(tree)]
    if not named:
        return "none: the product names none under `manuals` in .sclaude/config.json"
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]


if __name__ == "__main__":
    print(names(sys.argv[1] if len(sys.argv) > 1 else "."))
