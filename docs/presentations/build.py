#!/usr/bin/env python3
"""Build the slide decks from src/ into self-contained HTML pages, and
the process map from sclaude/lib/process.py.

Each deck is src/head.html + the deck's slides + src/tail.html. The decks
link to each other: by default through their sibling file names, so the
pages work from a checkout; --stack-url and --sclaude-url replace those
links when the pages are published somewhere else. A screenshot a deck
shows is src/img/<name>, written {{IMG:<name>}} and inlined as a data URI.

    python3 docs/presentations/build.py
    python3 docs/presentations/build.py --out ~/decks --stack-url URL --sclaude-url URL
"""

import argparse
import base64
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
sys.path.insert(0, str(HERE.parent.parent / "sclaude" / "lib"))
import process  # noqa: E402

# The process map: drawn from the model the code is checked against, so it is
# rebuilt here rather than edited (tests/process.py fails on a stale copy).
PROCESS = "bpmn_diagrams.html"

DECKS = [
    # file, title, the mark at the foot of each slide, the link to another deck
    # (empty for a deck that stands on its own)
    ("sclaude_in_details.html", "sclaude in Depth", "sclaude · in depth",
     '<a href="{{STACK}}" target="_blank" rel="noopener">&larr; stack deck</a>'),
    ("sclaude_instruments.html", "Laptop-to-Phone AI Stack", "AI stack for PoC & MVP",
     '<a href="{{SCLAUDE}}" target="_blank" rel="noopener">sclaude deck &rarr;</a>'),
    ("vibe_coding_story.html", "Why sclaude Exists", "why sclaude exists", ""),
]


def inline_images(page):
    def data_uri(m):
        img = SRC / "img" / m.group(1)
        return "data:image/webp;base64," + base64.b64encode(img.read_bytes()).decode()
    return re.sub(r"\{\{IMG:([\w.-]+\.webp)\}\}", data_uri, page)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=HERE)
    ap.add_argument("--stack-url", default="sclaude_instruments.html")
    ap.add_argument("--sclaude-url", default="sclaude_in_details.html")
    args = ap.parse_args()

    head = (SRC / "head.html").read_text()
    tail = (SRC / "tail.html").read_text()
    links = {"{{STACK}}": args.stack_url, "{{SCLAUDE}}": args.sclaude_url}
    args.out.mkdir(parents=True, exist_ok=True)
    for name, title, mark, other in DECKS:
        page = (head.replace("{{TITLE}}", title)
                + (SRC / name).read_text()
                + tail.replace("{{MARK}}", mark).replace("{{OTHER}}", other))
        for key, url in links.items():
            page = page.replace(key, url)
        page = inline_images(page)
        (args.out / name).write_text(page)
        print(args.out / name)
    (args.out / PROCESS).write_text(process.doc())
    print(args.out / PROCESS)


if __name__ == "__main__":
    main()
