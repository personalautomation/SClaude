#!/usr/bin/env python3
"""Build the GitHub wiki from the repository's documentation.

The wiki has two kinds of pages:

- the hand-written ones in wiki/pages/ — the front page, the concepts, the
  sidebar — copied as they are;
- the detailed ones, generated from docs/*.md: a long document becomes an
  index page and one page per `## ` section, a short one a single page.

docs/ stays the source of truth: the generated pages say which file they come
from, and are rebuilt rather than edited. Links between the documents are
rewritten to the wiki pages that now hold their targets; links to anything
else in the repository go to its file on GitHub.

    python3 wiki/build.py [--overwrite] [OUT_DIR]

OUT_DIR is a clone of SClaude.wiki.git. Without it the build uses the clone
kept in the checkout's git directory (.git/wiki), cloning it there from
origin's address the first time, so no machine lacks one.

Every .md file in OUT_DIR is removed first: the wiki is all built from here.
So before that, a clone's commits since the last rebuild — anybody's edit on
GitHub, whose subject does not start with REBUILD — are listed and the build
stops: the person reads them before they are overwritten (what is worth
keeping goes into docs/ or wiki/pages/), then runs it with --overwrite. A
rebuild is committed with a subject starting with REBUILD.
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join(ROOT, "wiki", "pages")
BLOB = "https://github.com/personalautomation/SClaude/blob/main/"
# How a rebuild's commit in the wiki's clone begins; anything after the last
# one is an edit made on GitHub.
REBUILD = "Rebuild from"

# (source, wiki page, title, split into a page per section, prefix of those pages)
DOCS = [
    ("docs/setup.md", "Setup", "Setting up", False, ""),
    ("docs/sclaude-guide.md", "Using-sclaude", "Using sclaude", True, "Using-"),
    ("docs/cycle.md", "Gates-and-Rules", "How the cycle is kept in line", False, ""),
    ("docs/team.md", "Team-Setup", "For a team, in detail", False, ""),
    ("docs/privacy.md", "Privacy-in-Full", "Privacy: what leaves your machine", False, ""),
    ("docs/tools.md", "Tools", "The tools", True, "Tool-"),
    ("docs/presentations/README.md", "Decks-and-Map", "The decks and the process map", False, ""),
    ("CONTRIBUTING.md", "Contributing", "Contributing", False, ""),
    ("docs/sclaude.md", "Inside-sclaude", "How sclaude works, and why", True, "Inside-"),
    ("docs/keepawake.md", "Inside-keepawake", "How keepawake works, and why", True, "Keepawake-"),
]


def slug(text):
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def page_name(prefix, heading):
    name = re.sub(r"[`*]", "", heading)
    name = re.sub(r"[^\w]+", "-", name).strip("-")
    return prefix + name


def sections(text):
    """Split a document into (heading, lines) at `## ` outside code fences.
    The first item is the text before the first section, heading None."""
    out, heading, lines, fence = [], None, [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            out.append((heading, lines))
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    out.append((heading, lines))
    return out


def headings(lines):
    fence = False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        elif not fence:
            m = re.match(r"#{1,6} (.*)", line)
            if m:
                yield m.group(1)


def plan():
    """Every generated page, and where each heading of each source landed:
    pages = [(name, title, source, lines, children)],
    anchors[source][slug] = (page, whether the heading is the page's title)."""
    pages, anchors, first = [], {}, {}
    for src, name, title, split, prefix in DOCS:
        text = open(os.path.join(ROOT, src), encoding="utf-8").read()
        anchors[src] = {}
        first[src] = name
        parts = sections(text)
        if not split:
            pages.append((name, title, src, text.splitlines(), []))
            for i, h in enumerate(headings(text.splitlines())):
                anchors[src].setdefault(slug(h), (name, i == 0))
            continue
        intro = parts[0][1]
        children = []
        for heading, lines in parts[1:]:
            child = page_name(prefix, heading)
            children.append((child, heading))
            anchors[src][slug(heading)] = (child, True)
            for h in headings(lines):
                anchors[src].setdefault(slug(h), (child, False))
            pages.append((child, heading, src, lines, []))
        for i, h in enumerate(headings(intro)):
            anchors[src].setdefault(slug(h), (name, i == 0))
        pages.append((name, title, src, intro, children))
    return pages, anchors, first


def rewrite(text, src, anchors, first):
    def link(m):
        label, target = m.group(1), m.group(2)
        if re.match(r"[a-z]+:", target):
            return m.group(0)
        path, _, anchor = target.partition("#")
        if path:
            path = os.path.normpath(os.path.join(os.path.dirname(src), path))
        else:
            path = src
        if path in anchors:
            page, top = anchors[path].get(anchor, (first[path], True))
            return "[%s](%s%s)" % (label, page, "" if top else "#" + anchor)
        if path == "README.md":
            return "[%s](Home)" % label
        if path.startswith("docs/") and path.endswith(".html"):
            return "[%s](https://personalautomation.github.io/SClaude/%s)" % (label, path[5:])
        return "[%s](%s%s%s)" % (label, BLOB, path, "#" + anchor if anchor else "")

    return re.sub(r"\[([^\]]*)\]\(([^)\s]+)\)", link, text)


def body(lines, src, anchors, first):
    out, fence = [], False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        if not fence:
            if re.match(r"# ", line):
                continue  # the wiki shows the page's title itself
            if re.match(r"#{3,6} ", line):
                line = line[1:]  # a section's ### is its page's ##
        out.append(line)
    # links are rewritten on the whole text, since a label may wrap a line;
    # the odd chunks between fences are code and stay as they are
    chunks = re.split(r"(^```.*?^```)", "\n".join(out), flags=re.S | re.M)
    for i in range(0, len(chunks), 2):
        chunks[i] = rewrite(chunks[i], src, anchors, first)
    return "".join(chunks).strip("\n")


def build(out):
    for f in os.listdir(out):
        if f.endswith(".md"):
            os.remove(os.path.join(out, f))
    pages, anchors, first = plan()
    for f in os.listdir(PAGES):
        # a hand-written page links a document by its address on GitHub;
        # in the wiki that link goes to the page the document became
        text = open(os.path.join(PAGES, f), encoding="utf-8").read()
        text = re.sub(r"\[[^\]]*\]\(%s[^)\s]+\)" % re.escape(BLOB),
                      lambda m: rewrite(m.group(0).replace(BLOB, ""), "README.md",
                                        anchors, first), text)
        with open(os.path.join(out, f), "w", encoding="utf-8") as fh:
            fh.write(text)
    for name, title, src, lines, children in pages:
        text = body(lines, src, anchors, first)
        if children:
            text += "\n\n## Pages\n\n" + "\n".join(
                "- [%s](%s)" % (re.sub(r"`", "", h), c) for c, h in children)
        note = ("*Generated from [`%s`](%s%s); edit it there, then rebuild "
                "with `wiki/build.py`.*" % (src, BLOB, src))
        with open(os.path.join(out, name + ".md"), "w", encoding="utf-8") as f:
            f.write(text + "\n\n---\n\n" + note + "\n")
    return len(pages)


def edits_since_rebuild(out):
    """The clone's commits after its last rebuild, newest first, as
    "<sha> <author> <date> <subject>"; [] for a directory that is not a clone
    itself — asked of its own .git only, so a folder inside some other
    checkout never reads that one's history. Any other failure of git stops
    the build: a guard that turns itself off would overwrite edits unseen."""
    if not os.path.exists(os.path.join(out, ".git")):
        return []
    # An edit made on GitHub since the clone was last pulled is in no local
    # history: a clone behind its remote stops the build until it is pulled.
    remotes = subprocess.run(["git", "-C", out, "remote"], capture_output=True, text=True).stdout.split()
    if remotes:
        fetched = subprocess.run(["git", "-C", out, "fetch", "-q"], capture_output=True, text=True)
        if fetched.returncode:
            sys.exit("wiki/build.py: could not fetch %s:\n%s" % (out, fetched.stderr.strip()))
        counted = subprocess.run(["git", "-C", out, "rev-list", "--count", "HEAD..@{u}"],
                                 capture_output=True, text=True)
        if counted.returncode:
            sys.exit("wiki/build.py: whether %s is behind its remote cannot be told — its "
                     "branch follows no remote branch (git -C %s branch -u origin/<branch>), "
                     "or there is no branch:\n%s" % (out, out, counted.stderr.strip()))
        behind = counted.stdout.strip()
        if behind != "0":
            sys.exit("wiki/build.py: %s is %s commit(s) behind its remote; pull it first "
                     "(git -C %s pull --ff-only), then build again." % (out, behind, out))
    # Fields split by NUL: an author's name holds spaces.
    done = subprocess.run(["git", "-C", out, "log", "--format=%h%x00%an%x00%ad%x00%s",
                           "--date=short"], capture_output=True, text=True)
    if done.returncode:
        sys.exit("wiki/build.py: git could not read %s's history:\n%s"
                 % (out, done.stderr.strip()))
    edits = []
    for line in done.stdout.splitlines():
        fields = line.split("\0")
        if fields[-1].startswith(REBUILD):
            break
        edits.append(" ".join(fields))
    return edits

def own_clone():
    """The wiki's clone kept in this checkout's git directory, cloned there
    from origin's address (SClaude.git -> SClaude.wiki.git) when missing."""
    common = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, text=True)
    if common.returncode:
        sys.exit("wiki/build.py: %s is not a git checkout; name the clone: "
                 "wiki/build.py OUT_DIR" % ROOT)
    out = os.path.join(common.stdout.strip(), "wiki")
    if os.path.isdir(os.path.join(out, ".git")):
        return out
    origin = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"],
                            capture_output=True, text=True).stdout.strip()
    if not origin:
        sys.exit("wiki/build.py: no origin to find the wiki by; name the clone: "
                 "wiki/build.py OUT_DIR")
    url = re.sub(r"(\.git)?/?$", ".wiki.git", origin, count=1)
    cloned = subprocess.run(["git", "clone", "-q", url, out], capture_output=True, text=True)
    if cloned.returncode:
        sys.exit("wiki/build.py: could not clone %s into %s:\n%s"
                 % (url, out, cloned.stderr.strip()))
    print("cloned %s into %s" % (url, out))
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    overwrite = "--overwrite" in args
    args = [a for a in args if a != "--overwrite"]
    if not args:
        args = [own_clone()]
    if len(args) != 1 or not os.path.isdir(args[0]):
        sys.exit("usage: wiki/build.py [--overwrite] [OUT_DIR]")
    edits = edits_since_rebuild(args[0])
    if edits and not overwrite:
        sys.exit("The wiki was edited since its last rebuild; read these before they are\n"
                 "overwritten, then run again with --overwrite:\n  " + "\n  ".join(edits))
    sys.argv[1:] = args
    n = build(sys.argv[1])
    print("%d generated pages, %d hand-written, in %s"
          % (n, len(os.listdir(PAGES)), sys.argv[1]))
