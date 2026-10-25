#!/usr/bin/env python3
"""Proposed CLAUDE.md rules, matched against what is already put off and
what CLAUDE.md already says, before sclaude puts them off itself.

A friction log of proposals alone is put off without a session
(friction_defer_proposals in run.sh), and each step's session names its
proposal's class itself. On one feature four sessions proposed the same rule
under four classes, one of them a rule the project's CLAUDE.md already
stated: the monthly review, which decides by how often a class comes back,
would have read one rule seen four times as four rules seen once. A friction
review session merges its entry into a class that is there; this path had
nobody to do that.

So one call of a small model reads the proposals, the classes already put
off (one example each) and CLAUDE.md, and says of each proposal:

    same     the rule of an existing class in other words: it takes that class
    covered  a rule CLAUDE.md already states: it is put off under one class,
             COVERED, with the line quoted, for the monthly review to drop
             or to read as a rule nobody follows
    new      neither: it keeps its own class

The answer is checked, not trusted: a "same" must name a class that is there,
and a "covered" must quote CLAUDE.md word for word; either one that does not
counts as "new". No row is dropped: a quote can match a sentence that only
looks like the rule, and a row left out would be one the monthly review never
counts. Anything going wrong — no claude, a timeout, an answer that is not the
JSON asked for — leaves every row as it came.

Each row that is put off is also counted: how many entries of its class the
deferred files hold since the last monthly review, this one included, and in
which features. The count is worked out from the rows, not kept in a field:
each feature has a file of its own so that two branches never edit the same
lines, and a counter two branches raise would conflict at every merge.

    friction_classify.py --notes <file> [--own <this feature's file>]
                         [--claude-md <path>] <deferred folder>...

Rows on stdin, six tab-separated fields (friction_proposals.py); the rows to
put off on stdout; one line per proposal for the person in --notes.
SCLAUDE_CLASSIFY_MODEL picks the model (haiku).
"""
import collections
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

MODEL = os.environ.get("SCLAUDE_CLASSIFY_MODEL", "haiku")
# The call stands between a fix session and the review of its fixes: a minute
# at most, and then the rows go as they came.
TIMEOUT = 60
COVERED = "claude-md-already-stated"
CLAUDE_MD_MAX = 60000
QUOTE_MIN = 20


def squash(text):
    return " ".join(text.split())


def read_rows(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return [l.rstrip("\n") for l in fh if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def last_reviewed(folder):
    try:
        stamp = open(os.path.join(folder, "last-reviewed"), encoding="utf-8").read().strip()
    except OSError:
        return ""
    return stamp if re.match(r"\d{4}-\d{2}-\d{2}$", stamp) else ""


def tail(path):
    """A deferred file by its rules folder: `team/deferred/x.tsv`."""
    return "/".join(os.path.normpath(os.path.abspath(path)).split(os.sep)[-3:])


def deferred_rows(folders, own):
    """Every row the deferred files hold since each folder's last review. The
    feature's own file is read from its tree as well as from main, and an
    identical row counted as often as the fuller copy has it: rows sent to
    main leave the branch, and rows not sent yet are on the branch alone."""
    out = []
    own_rows = read_rows(own) if own else []
    seen_own = False
    for folder in folders:
        since = last_reviewed(folder)
        for path in sorted(glob.glob(os.path.join(folder, "*.tsv"))):
            rows = read_rows(path)
            # The same file is the same rules folder's: <folder>/deferred/<feature>.tsv.
            # Another person's file of the same feature is theirs, and counts.
            if own and not seen_own and tail(path) == tail(own):
                seen_own = True
                a, b = collections.Counter(rows), collections.Counter(own_rows)
                rows = list((a | b).elements())
            out.extend((since, r) for r in rows)
    if own and not seen_own:
        since = last_reviewed(os.path.dirname(own))
        out.extend((since, r) for r in own_rows)
    rows = []
    for since, r in out:
        f = r.split("\t")
        if len(f) < 6:
            continue
        if since and f[0][:10] < since:
            continue
        rows.append(f)
    return rows


def prompt(proposals, classes, claude_md):
    listing = "\n".join("- %s: %s" % (k, squash(v)[:300]) for k, v in sorted(classes.items()))
    asked = "\n".join("%d. [%s] %s" % (i, p[4], squash(p[5])[:600])
                      for i, p in enumerate(proposals, start=1))
    return (
        "You sort proposed rules for a project's CLAUDE.md. Answer with JSON only, "
        "no prose and no code fence.\n\n"
        "For each numbered proposal decide one verdict:\n"
        '- "same": it is the rule of one of the existing classes below, or of an earlier '
        'proposal in this list, in other words. Give that class in "class", spelled exactly '
        'as listed (an earlier proposal\'s class is the one in its brackets).\n'
        '- "covered": the CLAUDE.md below already states this rule. Give in "quote" the '
        "sentence of CLAUDE.md that states it, copied exactly, at least a few words long.\n"
        '- "new": neither. When unsure, choose "new".\n\n'
        'Answer: [{"n": 1, "verdict": "same|covered|new", "class": "...", "quote": "..."}, ...]\n\n'
        "Existing classes, each with one entry:\n%s\n\n"
        "CLAUDE.md:\n<<<\n%s\n>>>\n\n"
        "Proposals:\n%s\n" % (listing or "(none)", claude_md[:CLAUDE_MD_MAX] or "(empty)", asked))


def ask_model(text):
    """The model's answer as a list, or None."""
    with tempfile.TemporaryDirectory() as cwd:
        try:
            done = subprocess.run(
                ["claude", "-p", text, "--model", MODEL, "--tools", "",
                 "--no-session-persistence", "--output-format", "text"],
                cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
                stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
    if done.returncode != 0:
        return None
    body = done.stdout.strip()
    found = re.search(r"\[.*\]", body, re.S)
    if not found:
        return None
    try:
        answer = json.loads(found.group(0))
    except ValueError:
        return None
    return answer if isinstance(answer, list) else None


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def main():
    args = sys.argv[1:]
    notes_path = own = claude_md_path = ""
    folders = []
    while args:
        a = args.pop(0)
        if a == "--notes" and args:
            notes_path = args.pop(0)
        elif a == "--own" and args:
            own = args.pop(0)
        elif a == "--claude-md" and args:
            claude_md_path = args.pop(0)
        else:
            folders.append(a)
    proposals = [l.rstrip("\n").split("\t") for l in sys.stdin if l.strip()]
    proposals = [p for p in proposals if len(p) >= 6]
    if not proposals:
        return 1
    existing = deferred_rows(folders, own)
    classes = {}
    for f in existing:
        classes[f[4]] = f[5]
    try:
        claude_md = open(claude_md_path, encoding="utf-8").read() if claude_md_path else ""
    except OSError:
        claude_md = ""

    verdicts = {}
    if classes or claude_md or len(proposals) > 1:
        answer = ask_model(prompt(proposals, classes, claude_md)) or []
        flat = squash(claude_md)
        for item in answer:
            if not isinstance(item, dict) or not isinstance(item.get("n"), int):
                continue
            v = item.get("verdict")
            # An existing class, or one an earlier proposal of this batch has.
            earlier = {p[4] for p in proposals[:max(0, item["n"] - 1)]}
            if v == "same" and (item.get("class") in classes or item.get("class") in earlier):
                verdicts[item["n"]] = ("same", item["class"])
            elif v == "covered" and isinstance(item.get("quote"), str):
                quote = squash(item["quote"])
                if len(quote) >= QUOTE_MIN and quote in flat:
                    verdicts[item["n"]] = ("covered", quote)

    kept, notes = [], []
    counted = collections.Counter(f[4] for f in existing)
    features = collections.defaultdict(set)
    for f in existing:
        features[f[4]].add(f[2])
    # What became of each class this batch brought: a later proposal that is
    # the same rule as an earlier one goes where that one went.
    went = {}
    for i, p in enumerate(proposals, start=1):
        verdict = verdicts.get(i)
        if verdict and verdict[0] == "same" and verdict[1] not in classes:
            verdict = went.get(verdict[1], verdict)
        if verdict and verdict[0] == "covered":
            notes.append("already in CLAUDE.md, put off as %s: %s — \"%s\"" % (
                COVERED, p[4], verdict[1][:160]))
            went.setdefault(p[4], verdict)
            p = p[:4] + [COVERED, "Already in CLAUDE.md (\"%s\"): %s" % (verdict[1][:200], p[5])]
            counted[p[4]] += 1
            features[p[4]].add(p[2])
            kept.append(p)
            continue
        went.setdefault(p[4], verdict if verdict and verdict[0] == "same" else ("same", p[4]))
        if verdict and verdict[0] == "same" and verdict[1] != p[4]:
            notes.append("the same rule as %s (was %s)" % (verdict[1], p[4]))
            p = p[:4] + [verdict[1]] + p[5:]
        counted[p[4]] += 1
        features[p[4]].add(p[2])
        kept.append(p)
    for p in kept:
        n = counted[p[4]]
        line = "%s: %s time since the last monthly review" % (p[4], ordinal(n))
        if len(features[p[4]]) > 1:
            line += ", in %d features" % len(features[p[4]])
        if line not in notes:
            notes.append(line)
    sys.stdout.write("".join("\t".join(p) + "\n" for p in kept))
    if notes_path:
        try:
            with open(notes_path, "w", encoding="utf-8") as fh:
                fh.write("".join(n + "\n" for n in notes))
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
