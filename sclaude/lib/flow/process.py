#!/usr/bin/env python3
"""sclaude's process as a model, and the maps drawn from it.

One description of the cycle — who does what, in which order, where it goes
back, and which commands lead where — serves two pages:

  the printed one, docs/presentations/bpmn_diagrams.html, built by
      python3 sclaude/lib/flow/process.py doc <out.html>
  and a feature's own, which sclaude-proxy serves at /__sclaude/flow?f=<label>
      with the feature's place lit and the actions open to it now
      (`sclaude _flow <name>` says both; `position` below reads the state).

The model is checked against the code by tests/process.py: the commands
against bin/sclaude's dispatch, the actions against actions.sh, the step
numbers against cycle_number, every place `position` can answer against the
nodes. A change to the cycle that is not made here fails there.

Layout: BPMN with vertical lanes, the flow running down. Each node sits in a
lane and a row; an edge running down turns in the gap under its block, one
running back up goes round by a channel on the right and one with a node in
its way by one on the left — on the right, inside the ways back, between
lanes right of the middle — so no line crosses a node. The ways round by a
channel into one block share it, a trunk: one carries it in, the others
join it with a small arrow, a chevron on the trunk past each. The arrows follow
three rules: out — on each side of a block the
way reaching farthest leaves from that side's corner along its row, the
others from below, each turning on its own level right under the block,
the farthest first, labelled there; in — several ways into a block enter
its top apart, in the order they come from, the ways back nested; the
channels — nested by how far they go, each turning above its target's row
by how near its channel is (Diagram.corners, levels, entries). Each gap
between rows is as tall as what runs in it, and where nothing turns in it
the lower row rises into the upper one's height (Diagram._rows). Vertical lanes keep the width to a page's, and the length is what
splits across pages.

    process.py doc <out.html>
    process.py position <state.json> [pr-state] [epilogue.json]
    process.py history <state.json> [node]   the feature's way, for its page to play
    process.py off <state.json>          where that way left the map, one line each, for the retrospective
    process.py page <label>              a feature's page shell, for a check
"""

import json
import os
import sys

import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_config, process_costs, process_diagram, process_doc, process_history, \
    process_model, process_page, process_position
import cycle_steps

# The model's parts, in the order they are read again. Each lives in its own
# file; process.X reads X from the part that defines it at the moment it is
# asked for, so a table `configured` swaps in is the one every caller sees.
PARTS = (process_model, process_config, process_position, process_history, process_costs,
         process_diagram, process_doc, process_page)
# What the parts read from outside the map: the steps' table. Watched and read
# again with them, first, though process.X does not look names up there.
SOURCES = (cycle_steps,)


def __getattr__(name):
    for part in PARTS:
        if name in vars(part):
            return getattr(part, name)
    raise AttributeError("module 'process' has no attribute %r" % name)


def files():
    """Every file the model is read from: what a long-running reader watches.
    The page's scripts and styles too (process_*.js, process_*.css), which the
    parts read as they are imported."""
    here = os.path.dirname(os.path.abspath(__file__))
    assets = sorted(os.path.join(here, n) for n in os.listdir(here)
                    if n.startswith("process_") and n.endswith((".js", ".css")))
    return [os.path.abspath(__file__)] + [part.__file__ for part in SOURCES + PARTS] + assets


def reload_parts():
    """Read every part again, in order; the caller reloads this module after.

    A part that fails — a syntax error, or a name another part does not
    define yet — puts every part back as it was before raising, so that the
    model served stays the last good one whole rather than half new."""
    saved = [(part, dict(vars(part))) for part in SOURCES + PARTS]
    try:
        for part in SOURCES + PARTS:
            importlib.reload(part)
    except BaseException:
        for part, names in saved:
            vars(part).clear()
            vars(part).update(names)
        raise


# --- the command line --------------------------------------------------------

def main(argv):
    if len(argv) >= 2 and argv[0] == "doc":
        with open(argv[1], "w") as fh:
            fh.write(process_doc.doc())
        print(argv[1])
        return 0
    if len(argv) >= 2 and argv[0] == "position":
        try:
            with open(argv[1]) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        epilogue = None
        if len(argv) >= 4 and argv[3] and os.path.isfile(argv[3]):
            try:
                with open(argv[3]) as fh:
                    epilogue = json.load(fh)
            except (OSError, ValueError):
                epilogue = None
        node, why = process_position.position(state, argv[2] if len(argv) >= 3 else "", epilogue)
        print("%s\t%s\t%s" % (node, process_config.all_nodes()[node][3], why))
        return 0
    if len(argv) >= 2 and argv[0] == "history":
        print(json.dumps(process_history.played(argv[1], argv[2] if len(argv) >= 3 else None)[2],
                         ensure_ascii=False))
        return 0
    if len(argv) >= 2 and argv[0] == "off":
        sys.stdout.write(process_history.off_lines(process_history.played(argv[1], costs=False)[2]))
        return 0
    if len(argv) >= 2 and argv[0] == "page":
        sys.stdout.write(process_page.page(argv[1]))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
