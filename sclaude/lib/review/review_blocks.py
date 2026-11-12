#!/usr/bin/env python3
#
# Review blocks: a pull request too big for one review read in pieces.
#
# A review reads well what it can hold. Past a few thousand changed lines a
# pass reads a part of the diff and calls the rest clean, so step 4 cuts such
# a pull request into blocks, once, at its start, from the finished code
# (review_blocks.sh): each block a group of behaviours — the plan's
# acceptance criteria — with the files that carry them, read end to end, the
# rule from its criterion through every layer it passes. Not by layer: a
# rule's bugs are where the layers meet.
# Not by the parts a feature was built in: those were cut for building and
# showing, and the same central files run through every one of them.
#
# Each changed file has one owner, the block that reads it whole; a block
# opens another's files only to follow its own criteria or check a contract.
# The blocks are read one after another, each to a clean verdict, the fixes
# going on top of the whole branch; after the last a pass over the seams
# reads what no block could see (seams_scope). sclaude counts a block's rounds
# apart (the journal's `block`, local_review.py).
#
# The cut is a model's (blocks_cut_prompt in review_blocks.sh), checked here
# (validate):
# every changed file in exactly one block, every criterion in one block or
# one rule every behaviour follows, no block past the size but a single file.
# A cut that fails twice gives way to the parts the feature was built in
# (draft), or, for a feature built in one go, to a single read as before.
#
#   review_blocks.py size <wt> <base>                 changed lines, generated files left out
#   review_blocks.py files <wt> <base> <state>        a line a changed file, for the cut's session
#   review_blocks.py take <answer> <out> <base> <head>  the session's JSON into the cut
#   review_blocks.py draft <wt> <base> <state> <out>  the mechanical cut, by the parts
#   review_blocks.py validate <wt> <base> <file> <size>  the cut's faults, one a line; exit 1 on any
#   review_blocks.py summary <file>                   a line a block, for the person
#   review_blocks.py count <file>                     how many blocks the cut has
#   review_blocks.py scope <wt> <file> <k> <head>     what block <k>'s first read reads
#   review_blocks.py seams <wt> <file> <head>         what the pass over the seams reads
#   review_blocks.py touched <wt> <file> <k> <from> <head>
#                                                     closed blocks' files a later round changed
#   review_blocks.py close <file> <k> <head>          block <k> closed at <head>
#
# The file (FEATURE_BLOCKS, review-blocks.json beside the feature's state):
#   {"base": <commit the review reads from>, "head": <the head cut>,
#    "source": "session" | "parts" , "rules": [{"title", "criteria", "where"}],
#    "blocks": [{"title", "criteria": [ids], "files": [paths], "why",
#                "contracts": [text]}], "closed": {"<k>": <head>}}
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import acceptance  # noqa: E402

FEATURE_BLOCKS = os.path.join(".sclaude", "local", "feature", "review-blocks.json")

# Files a tool writes: owned like any other, never counted in a block's size
# — a regenerated lock file or snapshot is no reading.
GENERATED = re.compile(
    r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|"
    r"bun\.lockb?|Cargo\.lock|poetry\.lock|uv\.lock|Gemfile\.lock|composer\.lock|go\.sum)$"
    r"|\.(snap|min\.js|min\.css|map)$|(^|/)__snapshots__/")
MARKER = re.compile(r"@generated|auto-?generated|do not edit", re.IGNORECASE)


def git(wt, *args):
    return subprocess.run(["git", "-C", wt, *args], capture_output=True, text=True,
                          timeout=60).stdout


def changed(wt, base, head="HEAD"):
    """{path: lines changed} of <base>..<head>; a binary file counts 0."""
    out = {}
    for line in git(wt, "diff", "--numstat", "--no-renames", "%s..%s" % (base, head)).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, rem, path = parts
        out[path] = (int(add) if add.isdigit() else 0) + (int(rem) if rem.isdigit() else 0)
    return out


def generated(wt, path):
    if GENERATED.search(path):
        return True
    try:
        with open(os.path.join(wt, path), encoding="utf-8", errors="replace") as fh:
            head = fh.read(600)
    except OSError:
        return False
    return bool(MARKER.search(head))


def size(wt, base):
    return sum(n for p, n in changed(wt, base).items() if not generated(wt, p))


def part_ranges(state_path):
    """[(n, "from..tip")] of the parts, as the join recorded them."""
    try:
        with open(state_path, encoding="utf-8") as fh:
            parts = (json.load(fh).get("parts") or {})
    except (OSError, ValueError):
        return [], {}
    ranges = sorted((int(n), v["range"]) for n, v in parts.items()
                    if n.isdigit() and isinstance(v, dict) and v.get("range"))
    return ranges, parts


def files(wt, base, state_path):
    """A line a changed file for the cut's session: path, lines changed,
    `generated` or `-`, and the parts whose commits changed it."""
    ranges, _ = part_ranges(state_path)
    by_part = {n: changed(wt, *r.split("..", 1)) for n, r in ranges}
    out = []
    for path, n in sorted(changed(wt, base).items()):
        touched_by = [str(p) for p, _ in ranges if path in by_part[p]]
        out.append("%s\t%d\t%s\t%s" % (path, n, "generated" if generated(wt, path) else "-",
                                       ",".join(touched_by) or "-"))
    return out


def plan_criteria(wt):
    try:
        with open(os.path.join(wt, ".sclaude", "local", "feature", "plan.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    return acceptance.plan_criteria(acceptance.plan_section(text) or "")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)


def draft(wt, base, state_path, out):
    """The parts as blocks: each changed file owned by the part whose
    commits changed most of it (`parts.<n>.range`, written as the parts were
    joined), a file no part changed by the first block; a part's criteria by
    their `[part n]` tag, the untagged ones the feature's own rule. No cut
    when the feature was built in one go: nothing to fall back to."""
    ranges, parts = part_ranges(state_path)
    if len(ranges) < 2:
        return 1
    files = changed(wt, base)
    by_part = {n: changed(wt, *r.split("..", 1)) for n, r in ranges}
    blocks = {n: {"title": "Part %d — %s" % (n, parts[str(n)].get("title") or ""),
                  "criteria": [], "files": [], "why": "the part as it was built",
                  "contracts": []} for n, _ in ranges}
    first = ranges[0][0]
    for path in sorted(files):
        lines = {n: by_part[n].get(path, 0) for n, _ in ranges}
        owner = max(lines, key=lambda n: (lines[n], -n)) if any(lines.values()) else first
        blocks[owner]["files"].append(path)
    import plan_parts
    shared = []
    for cid, text in plan_criteria(wt):
        n = plan_parts.criterion_part(text)
        (blocks[n]["criteria"] if n in blocks else shared).append(cid)
    # A part that owns no file — the parts after it changed its files more —
    # hands its criteria to the block before it, or the first, so that every
    # criterion is still some block's.
    kept = [n for n, _ in ranges if blocks[n]["files"]]
    for n, _ in ranges:
        if not blocks[n]["files"] and blocks[n]["criteria"]:
            to = max([m for m in kept if m < n] or [kept[0]])
            blocks[to]["criteria"] += blocks[n]["criteria"]
            blocks[n]["criteria"] = []
    save(out, {"base": base, "head": git(wt, "rev-parse", "HEAD").strip(), "source": "parts",
               "rules": [{"title": "The feature as a whole", "criteria": shared, "where": []}]
               if shared else [],
               "blocks": [b for _, b in sorted(blocks.items()) if b["files"]], "closed": {}})
    return 0


def take(answer, out, base, head):
    """The cut's session answers with a JSON object and nothing else; a
    fence or a sentence around it is tolerated, the object kept."""
    try:
        with open(answer, encoding="utf-8") as fh:
            text = fh.read()
        data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except (OSError, ValueError) as e:
        sys.stderr.write("no JSON object in the answer: %s\n" % e)
        return 1
    if not isinstance(data, dict):
        return 1
    data.update({"base": base, "head": head, "source": "session", "closed": {}})
    save(out, data)
    return 0


def validate(wt, base, path, limit):
    """The cut's faults, each a sentence a second try can act on."""
    try:
        data = load(path)
    except (OSError, ValueError) as e:
        return ["the file is not JSON: %s" % e]
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return ["no `blocks` list"]
    files = changed(wt, base)
    faults, seen = [], {}
    for i, b in enumerate(blocks, 1):
        if not isinstance(b, dict) or not b.get("title"):
            faults.append("block %d has no title" % i)
            continue
        own = b.get("files") or []
        if not own:
            faults.append("block %d (%s) owns no file: merge it into the block that owns its files"
                          % (i, b["title"]))
        for f in own:
            if f in seen:
                faults.append("%s is in block %d and block %d: a file has one owner" % (f, seen[f], i))
            elif f not in files:
                faults.append("%s is in block %d but this pull request does not change it" % (f, i))
            seen.setdefault(f, i)
        lines = sum(files.get(f, 0) for f in own if not generated(wt, f))
        if len(own) > 1 and lines > limit:
            faults.append("block %d (%s) has %d changed lines, past %d: split it by behaviour"
                          % (i, b["title"], lines, limit))
    for f in sorted(set(files) - set(seen)):
        faults.append("%s is changed and in no block" % f)
    ids = [c for c, _ in plan_criteria(wt)]
    placed = {}
    for i, b in enumerate(blocks, 1):
        for c in (b.get("criteria") or []) if isinstance(b, dict) else []:
            placed.setdefault(c, []).append("block %d" % i)
    for r in data.get("rules") or []:
        for c in r.get("criteria") or []:
            placed.setdefault(c, []).append("rule %s" % r.get("title", "?"))
    for c in ids:
        if c not in placed:
            faults.append("criterion %s is in no block and no rule" % c)
        elif len(placed[c]) > 1:
            faults.append("criterion %s is in %s: one place each" % (c, " and ".join(placed[c])))
    for c in sorted(set(placed) - set(ids)):
        faults.append("criterion %s is not in the plan" % c)
    return faults


def summary(path):
    data = load(path)
    out = []
    for i, b in enumerate(data["blocks"], 1):
        crit = ", ".join(b.get("criteria") or []) or "no criterion of its own"
        out.append("%d. %s — %d files; %s" % (i, b["title"], len(b.get("files") or []), crit))
    out.append("%d. The seams: the blocks together, and what changed in a closed block after it closed"
               % (len(data["blocks"]) + 1))
    return out


def criteria_text(wt, ids):
    known = dict(plan_criteria(wt))
    return ["- %s — %s" % (c, known.get(c, "(not in the plan)")) for c in ids]


def scope(wt, path, k, head):
    """Block <k>'s first read, as the scope sentence local_review.sh hands
    the pass."""
    data = load(path)
    blocks, base = data["blocks"], data["base"]
    b = blocks[k - 1]
    files = changed(wt, base, head)
    # A file the fixes of earlier blocks added, owned by none: the block read
    # now takes it, so that every line is read whole once.
    owned = {f for o in blocks for f in o.get("files") or []}
    orphans = sorted(f for f in files if f not in owned)
    if orphans:
        b["files"] = list(b.get("files") or []) + orphans
        save(path, data)
    own = [f for f in b["files"] if f in files]
    if own:
        read = ("Its files, each read whole as it is at %s, and what this pull request changed in "
                "them: `git diff %s..%s -- %s`. The files: %s." % (
                    head[:7], base, head, " ".join(own),
                    ", ".join("%s (%d lines changed)" % (f, files[f]) for f in own)))
    else:
        read = ("None of its files is changed by this pull request any more (%s): an earlier "
                "block's fixes took them back. Check that its criteria hold in the code as it is "
                "at %s, and read no diff as its own." % (", ".join(b["files"]) or "none", head[:7]))
    lines = ["block %d of %d of this pull request, read on its own: **%s**%s"
             % (k, len(blocks), b["title"], " — %s" % b["why"] if b.get("why") else "")]
    if b.get("criteria"):
        lines += ["", "The behaviours it answers for, the plan's criteria "
                  "(.sclaude/local/feature/plan.md has the plan around them):"]
        lines += criteria_text(wt, b["criteria"])
    rules = [r for r in data.get("rules") or [] if r.get("criteria") or r.get("title")]
    if rules:
        lines += ["", "Rules every behaviour of the feature follows — check that this block's do:"]
        for r in rules:
            lines.append("- %s%s%s" % (r.get("title", ""),
                                       " (%s)" % ", ".join(r["criteria"]) if r.get("criteria") else "",
                                       "; built in %s" % ", ".join(r["where"]) if r.get("where") else ""))
    lines += ["", read]
    if b.get("contracts"):
        lines += ["", "Where it meets the other blocks:"] + ["- %s" % c for c in b["contracts"]]
    others = [(i, o["title"]) for i, o in enumerate(blocks, 1) if i != k]
    if others:
        lines += ["", "The rest of the pull request is the other blocks', each read in its turn: %s. "
                  "Open their files to follow this block's criteria end to end, through every layer "
                  "they pass, or to check a contract, and report what breaks this block's "
                  "behaviours wherever it is; do not review their code for its own sake." % "; ".join(
                      "%d. %s%s" % (i, t, " (read, closed)" if str(i) in data.get("closed", {}) else "")
                      for i, t in others)]
    return "\n".join(lines)


def seams(wt, path, head):
    data = load(path)
    blocks, base = data["blocks"], data["base"]
    lines = ["the seams of this pull request, read after each of its blocks was reviewed on its "
             "own: %s. Do not look for every bug again; look for what no block could see:" % "; ".join(
                 "%d. %s" % (i, b["title"]) for i, b in enumerate(blocks, 1)),
             "",
             "- the behaviours together: two blocks' criteria that share state, an order of "
             "events or a permission, run against each other;",
             "- what changed in a block's files after that block closed — read in later rounds, "
             "but never against that block's criteria as a whole:"]
    any_late = False
    for i, b in enumerate(blocks, 1):
        at = data.get("closed", {}).get(str(i))
        if not at:
            continue
        late = sorted(set(b["files"]) & set(changed(wt, at, head)))
        if late:
            any_late = True
            lines.append("  - block %d (%s, criteria %s): `git diff %s..%s -- %s`" % (
                i, b["title"], ", ".join(b.get("criteria") or []) or "none", at, head, " ".join(late)))
    if not any_late:
        lines.append("  - none: no block's files changed after it closed;")
    rules = data.get("rules") or []
    lines.append("- the rules across the whole feature%s: errors, permissions and the "
                 "manuals, migrations, tests and settings in step everywhere;" % (
                     " (%s)" % "; ".join(r.get("title", "") for r in rules) if rules else ""))
    lines.append("- the plan's criteria against the feature as a whole.")
    lines += ["", "The whole pull request, for reference: `git diff %s..%s`." % (base, head)]
    return "\n".join(lines)


def touched(wt, path, k, since, head):
    """The files of the blocks closed before <k> that <since>..<head>
    changed, with the criteria each answers for: a fix made for one block
    may break another's rule, and the diff alone does not say which."""
    data = load(path)
    hit = set(changed(wt, since, head))
    out = []
    for i, b in enumerate(data["blocks"], 1):
        if i >= k or str(i) not in data.get("closed", {}):
            continue
        late = sorted(hit & set(b["files"]))
        if late:
            out.append("%s — block %d, %s, answers for %s" % (
                ", ".join(late), i, b["title"], ", ".join(b.get("criteria") or []) or "no criterion"))
    if not out:
        return ""
    return (" These commits change files of blocks already reviewed; check each change keeps "
            "that block's criteria (the plan has their text): " + "; ".join(out))


def close(path, k, head):
    data = load(path)
    data.setdefault("closed", {})[str(k)] = head
    save(path, data)
    return 0


def main(argv):
    if not argv:
        return 2
    cmd, a = argv[0], argv[1:]
    if cmd == "size" and len(a) == 2:
        print(size(*a))
        return 0
    if cmd == "files" and len(a) == 3:
        print("\n".join(files(*a)))
        return 0
    if cmd == "take" and len(a) == 4:
        return take(*a)
    if cmd == "draft" and len(a) == 4:
        return draft(*a)
    if cmd == "validate" and len(a) == 4:
        try:
            faults = validate(a[0], a[1], a[2], int(a[3]))
        except (AttributeError, TypeError, KeyError) as e:
            # A shape the checks do not expect (a rule as a string, a file
            # list as a word): said as a fault, for the second try to mend.
            faults = ["the cut does not have the shape asked for (%s: %s)" % (type(e).__name__, e)]
        print("\n".join(faults))
        return 1 if faults else 0
    if cmd == "summary" and len(a) == 1:
        print("\n".join(summary(a[0])))
        return 0
    if cmd == "count" and len(a) == 1:
        print(len(load(a[0])["blocks"]))
        return 0
    if cmd == "scope" and len(a) == 4:
        print(scope(a[0], a[1], int(a[2]), a[3]))
        return 0
    if cmd == "seams" and len(a) == 3:
        print(seams(*a))
        return 0
    if cmd == "touched" and len(a) == 5:
        print(touched(a[0], a[1], int(a[2]), a[3], a[4]))
        return 0
    if cmd == "close" and len(a) == 3:
        return close(a[0], int(a[1]), a[2])
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
