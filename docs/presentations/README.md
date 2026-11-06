# The decks and the process map, in detail

The decks listed under [See it](../../README.md#see-it) are for whoever decides whether a
team should adopt all this, rather than for the developer installing it.

`sclaude_full_story.html` is not one of them: `full_story.py` (run by
`build.py`) assembles it from the other three, and the file says so at its
top. It is a build product — nothing links to it, it is not shared or
attached, and it is never edited by hand; change the three decks in `src/`
and rebuild.

Each is one self-contained page: open it in a browser and page through with
the arrow keys; on a phone the slides stack into one column. They are published
on GitHub Pages, served from `docs/` on `main` (https://personalautomation.github.io/SClaude/presentations/),
next to the landing page `docs/index.html`; GitHub's own file view shows only
the source. The decks are built from
`docs/presentations/src/` by `python3 docs/presentations/build.py`; edit the
sources and rebuild rather than editing the built pages.

Beside them, [`bpmn_diagrams.html`](bpmn_diagrams.html)
is the process map: the cycle at a glance, the whole
process as BPMN with every lane and every way back, how a session changes
sclaude itself (the blocks marked W), the friction review that follows the
sessions marked F, and every command with the place it leads to. It is drawn
for `sclaude/config.example.json`; a project's own map, on its proxy, shows the
cycle its `.sclaude/config.json` runs — the review on CI or on this machine, QA
on a board or none, who merges — and nothing it does not. To print it, choose the paper and the scale on the
page itself, above the whole process (A4 landscape at 100% is recommended;
"Fit the width" puts the whole width on one sheet, the map going on down):
the large map is cut between lanes into overlapping sheets that glue
together, and the page tells how many; every printed page names its
section in its header and its number at the foot. The page names its paper, so the
print dialog shows no Layout or Paper size; its Scale would only shrink each
sheet. The same build draws it
from `sclaude/lib/flow/process.py`, which `tests/process.py` checks against the
code; a feature's own copy, with where it stands lit, is on the proxy (see
[bin/sclaude-proxy](../tools.md#binsclaude-proxy)).
