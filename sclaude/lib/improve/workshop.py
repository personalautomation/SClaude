#!/usr/bin/env python3
#
# The workshop's record and the checks before what was made in it is published.
#
# A session never changes sclaude's live checkout: every other session runs
# from it (write-guard.py --readonly). A change to sclaude is made in the
# tree's workshop instead, a worktree of the checkout under
# .sclaude/local/instruments (workshop.sh), and sclaude publishes it once the
# session has reviewed it. This file keeps the record beside it,
# .sclaude/local/instruments.json, and does the parts that are easier in
# Python than in bash:
#
#   approve <record> <session>            the session may write in the workshop
#   approved <record> <session>           exit 0 when it may
#   get <record> <key>                    a value (dotted for a nested one), or exit 1
#   put <record> <key> <json>             set one, dotted too (null removes it)
#   ready <record> <session> <head> <how> the session finished and reviewed its
#                                         change at <head>, by <how>; publish it
#   pending <record> <session> <cwd> <args…>
#                                         remember a session that left its
#                                         change unfinished, to offer it back
#   pending-args <record>                 its cwd and arguments, NUL-separated
#   leaks <workshop> <base> <tree>        what in base..HEAD names the product
#   squash-message <workshop> <base>      one message for base..HEAD
#
# The record is read by write-guard.py too, which lets an approved session
# write in the workshop: `approved` there is a list of session ids.
import json
import os
import re
import subprocess
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def git(where, *args):
    done = subprocess.run(["git", "-C", where] + list(args), capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


# --- what would tell the product ----------------------------------------------
#
# sclaude's repository is public and the products it drives are not, so what a
# session writes there must not name one (CLAUDE.md, "Public repository,
# private projects"). Nothing can tell that for certain; this looks for what a
# product's details usually look like, in the lines the change adds and in its
# commit messages, and the person decides on whatever it finds.

# Numbers of pull requests and issues: the orchestrator's own text has no use
# for one. Not a digit that a redirection follows: `state_get "$state" pr
# 2>/dev/null` reads `pr`, then stderr, and is no pull request.
NUMBERED = re.compile(r"(?<![\w&$/{])#\d{1,6}\b|\b(?:PR|pull request|issue)s? #?\d{1,6}\b(?!>)"
                      r"|/(?:pull|issues)/\d+", re.I)
def product_terms(tree):
    """The words and paths that name the product the tree belongs to."""
    terms = set()
    url = git(tree, "remote", "get-url", "origin").strip()
    m = re.search(r"[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url)
    if m:
        terms.add("%s/%s" % (m.group(1), m.group(2)))
        terms.add(m.group(2))
    common = git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    if common:
        terms.add(os.path.basename(os.path.dirname(common)))
    state = load(os.path.join(tree, ".sclaude", "local", "feature", "state.json"))
    for key in ("slug", "branch"):
        if isinstance(state.get(key), str):
            terms.add(state[key])
    package = load(os.path.join(tree, "package.json"))
    if isinstance(package.get("name"), str):
        terms.add(package["name"])
    # A name shorter than four letters matches inside every other word.
    return {t for t in terms if len(t) >= 4}


def product_paths(tree, workshop):
    """The product's own files, by a path long enough to tell. sclaude's own
    folders in a product (.sclaude/, the review workflow it reads) are left
    out: the orchestrator names those by design."""
    out = set()
    for path in git(tree, "ls-files").splitlines():
        if "/" not in path or len(path) < 10 or path.startswith((".sclaude/", ".github/")):
            continue
        if os.path.exists(os.path.join(workshop, path)):
            continue
        out.add(path)
    return out


def leaks(workshop, base, tree):
    """Lines of the change that may name the product, as `where: text`."""
    terms = product_terms(tree)
    paths = product_paths(tree, workshop)
    words = [re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(t), re.I) for t in sorted(terms)]
    found = []

    def check(where, line):
        hits = [m.group(0) for m in NUMBERED.finditer(line)]
        hits += [w.pattern for w in words if w.search(line)]
        hits += [p for p in paths if p in line]
        if hits:
            found.append("%s: %s" % (where, line.strip()[:160]))

    for sha in git(workshop, "rev-list", "--reverse", "%s..HEAD" % base).split():
        # Every line, trailers too: a body line like `Seen in: …` reads as one,
        # and the session links real trailers carry name no product.
        for line in git(workshop, "log", "-1", "--format=%B", sha).splitlines():
            check("commit %s" % sha[:8], line)
    current = ""
    for line in git(workshop, "diff", "--unified=0", "%s..HEAD" % base).splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            check(current, line[1:])
    return found


# --- one commit for a publication ----------------------------------------------

def split_message(text):
    """A message as its subject, its body and its trailer lines."""
    lines = text.strip("\n").splitlines()
    subject = lines[0] if lines else ""
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    trailers = []
    # The trailer block is the last paragraph, when every line in it is one.
    paragraphs = "\n".join(rest).split("\n\n")
    if paragraphs and paragraphs[-1].strip() and all(
            TRAILER.match(l) for l in paragraphs[-1].strip().splitlines()):
        trailers = paragraphs[-1].strip().splitlines()
        paragraphs = paragraphs[:-1]
    return subject, "\n\n".join(paragraphs).strip(), trailers


# A line of a commit's trailer block.
TRAILER = re.compile(r"^[A-Za-z][\w-]*: \S")

# What sreview names its own rounds by: they fix the change, they are not it.
ROUND = re.compile(r"^fix(\([^)]*\))?: review iteration\b")


def squash_message(workshop, base):
    shas = git(workshop, "rev-list", "--reverse", "%s..HEAD" % base).split()
    messages = [split_message(git(workshop, "log", "-1", "--format=%B", s)) for s in shas]
    if not messages:
        return ""
    if len(messages) == 1:
        return git(workshop, "log", "-1", "--format=%B", shas[0]).strip() + "\n"
    lead = next((m for m in messages if not ROUND.match(m[0])), messages[0])
    others = [m[0] for m in messages if m is not lead]
    trailers = []
    for m in messages:
        for line in m[2]:
            if line not in trailers:
                trailers.append(line)
    parts = [lead[0]]
    if lead[1]:
        parts.append(lead[1])
    parts.append("Also in this change:\n" + "\n".join("- %s" % s for s in others))
    if trailers:
        parts.append("\n".join(trailers))
    return "\n\n".join(parts) + "\n"


def main(argv):
    if len(argv) < 2:
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "ready":
        data = load(args[0])
        data["ready"] = {"session": args[1], "head": args[2], "review": args[3]}
        save(args[0], data)
        return 0
    if cmd == "approve":
        data = load(args[0])
        approved = data.setdefault("approved", [])
        if args[1] not in approved:
            approved.append(args[1])
        save(args[0], data)
        return 0
    if cmd == "approved":
        return 0 if args[1] in (load(args[0]).get("approved") or []) else 1
    if cmd == "get":
        value = load(args[0])
        for key in args[1].split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if value is None:
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
        return 0
    if cmd == "put":
        data = load(args[0])
        value = json.loads(args[2])
        *path, last = args[1].split(".")
        node = data
        for key in path:
            if not isinstance(node.get(key), dict):
                node[key] = {}
            node = node[key]
        if value is None:
            node.pop(last, None)
        else:
            node[last] = value
        save(args[0], data)
        return 0
    if cmd == "pending":
        data = load(args[0])
        data["pending"] = {"session": args[1], "cwd": args[2], "args": args[3:]}
        save(args[0], data)
        return 0
    if cmd == "pending-args":
        pending = load(args[0]).get("pending") or {}
        if not pending.get("args"):
            return 1
        sys.stdout.write("\0".join([pending.get("cwd") or "."] + pending["args"]) + "\0")
        return 0
    if cmd == "leaks":
        found = leaks(*args[:3])
        for line in found:
            print(line)
        return 1 if found else 0
    if cmd == "squash-message":
        sys.stdout.write(squash_message(*args[:2]))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
