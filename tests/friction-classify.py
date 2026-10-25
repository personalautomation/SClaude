#!/usr/bin/env python3
#
# friction_classify.py: proposed CLAUDE.md rules matched against the classes
# put off already and against CLAUDE.md, before sclaude puts them off itself,
# and each class counted since the last monthly review.
#
# The model is a stub on PATH that prints a canned answer: what is at stake is
# that the answer is checked rather than trusted, and that anything going
# wrong leaves the rows as they came.
#
# Run it with: python3 tests/friction-classify.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "sclaude", "lib", "friction_classify.py")

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


CLAUDE_MD = """# Rules

- **A condition is spelled out once, next to the code that checks it.** A comment
  elsewhere gives its gist and names that place.
"""


def row(date, feature, klass, text, step="review"):
    return "\t".join([date, "app", feature, step, klass, text])


def run(tmp, rows, answer, own_rows=(), main_rows=(), reviewed=None, rc=0):
    folder = os.path.join(tmp, "main", "deferred")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "other.tsv"), "w") as fh:
        fh.write("".join(r + "\n" for r in main_rows))
    if reviewed:
        with open(os.path.join(folder, "last-reviewed"), "w") as fh:
            fh.write(reviewed + "\n")
    own_dir = os.path.join(tmp, "tree", "deferred")
    os.makedirs(own_dir, exist_ok=True)
    own = os.path.join(own_dir, "feat.tsv")
    with open(own, "w") as fh:
        fh.write("".join(r + "\n" for r in own_rows))
    claude_md = os.path.join(tmp, "CLAUDE.md")
    with open(claude_md, "w") as fh:
        fh.write(CLAUDE_MD)
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    stub = os.path.join(bin_dir, "claude")
    with open(stub, "w") as fh:
        fh.write("#!/bin/sh\necho called >> %s/calls\ncat <<'EOF'\n%s\nEOF\nexit %d\n"
                 % (tmp, answer, rc))
    os.chmod(stub, 0o755)
    notes = os.path.join(tmp, "notes")
    done = subprocess.run([sys.executable, SCRIPT, "--notes", notes, "--own", own,
                           "--claude-md", claude_md, folder],
                          input="".join(r + "\n" for r in rows), capture_output=True, text=True,
                          env=dict(os.environ, PATH=bin_dir + ":/usr/bin:/bin"), timeout=60)
    out = [l.split("\t") for l in done.stdout.splitlines() if l]
    said = open(notes).read().splitlines() if os.path.exists(notes) else []
    return done.returncode, out, said


def case(fn):
    tmp = tempfile.mkdtemp(prefix="sclaude-classify-")
    try:
        fn(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


EARLIER = row("2026-10-20", "older", "claude-md-condition-spelled-once", "Proposal: a rule in one place")


def same(tmp):
    answer = json.dumps([{"n": 1, "verdict": "same", "class": "claude-md-condition-spelled-once"}])
    rc, out, said = run(tmp, [row("2026-10-24", "feat", "claude-md-check-skip-stated", "Proposal: x")],
                        answer, main_rows=[EARLIER])
    check("same: takes the existing class", [r[4] for r in out], ["claude-md-condition-spelled-once"])
    check("same: the note says which", any("the same rule as claude-md-condition-spelled-once" in n
                                           for n in said), True)
    check("same: counted with the earlier one",
          any("2nd time since the last monthly review, in 2 features" in n for n in said), True)


def covered(tmp):
    answer = json.dumps([{"n": 1, "verdict": "covered",
                          "quote": "A condition is spelled out once, next to the code that checks it."}])
    rc, out, said = run(tmp, [row("2026-10-24", "feat", "claude-md-new", "Proposal: y")], answer)
    check("covered: not put off", (rc, out), (0, []))
    check("covered: the note quotes CLAUDE.md", any("already in CLAUDE.md" in n for n in said), True)


def invented(tmp):
    answer = json.dumps([{"n": 1, "verdict": "same", "class": "claude-md-made-up"},
                         {"n": 2, "verdict": "covered", "quote": "a sentence CLAUDE.md does not have at all"}])
    rows = [row("2026-10-24", "feat", "claude-md-a", "Proposal: a"),
            row("2026-10-24", "feat", "claude-md-b", "Proposal: b")]
    rc, out, said = run(tmp, rows, answer, main_rows=[EARLIER])
    check("an invented class or quote counts as new", [r[4] for r in out], ["claude-md-a", "claude-md-b"])


def broken(tmp):
    rows = [row("2026-10-24", "feat", "claude-md-a", "Proposal: a")]
    for name, answer, rc in (("not JSON", "I think they are all new.", 0),
                             ("a failing claude", "[]", 1)):
        _, out, _ = run(tmp, rows, answer, rc=rc)
        check("%s leaves the rows as they came" % name, [r[4] for r in out], ["claude-md-a"])


def counted(tmp):
    # The feature's own rows are read from its tree and from main, counted
    # once; rows before the last monthly review are not counted.
    mine = row("2026-10-22", "feat", "claude-md-a", "Proposal: a, earlier")
    old = row("2026-09-01", "older", "claude-md-a", "Proposal: a, before the review")
    os.makedirs(os.path.join(tmp, "main", "deferred"))
    with open(os.path.join(tmp, "main", "deferred", "feat.tsv"), "w") as fh:
        fh.write(mine + "\n")
    rc, out, said = run(tmp, [row("2026-10-24", "feat", "claude-md-a", "Proposal: a again")],
                        "[]", own_rows=[mine], main_rows=[old], reviewed="2026-10-01")
    check("counted once across tree and main, since the review",
          any(n.startswith("claude-md-a: 2nd time") for n in said), True)


def no_material(tmp):
    # Nothing put off and no CLAUDE.md: nothing to match against, no call.
    folder = os.path.join(tmp, "empty")
    os.makedirs(folder)
    bin_dir = os.path.join(tmp, "bin")
    os.makedirs(bin_dir)
    with open(os.path.join(bin_dir, "claude"), "w") as fh:
        fh.write("#!/bin/sh\necho called >> %s/calls\n" % tmp)
    os.chmod(os.path.join(bin_dir, "claude"), 0o755)
    done = subprocess.run([sys.executable, SCRIPT, "--notes", os.path.join(tmp, "n"), folder],
                          input=row("2026-10-24", "f", "claude-md-a", "Proposal: a") + "\n",
                          capture_output=True, text=True,
                          env=dict(os.environ, PATH=bin_dir + ":/usr/bin:/bin"), timeout=60)
    check("nothing to match against: the model is not called",
          os.path.exists(os.path.join(tmp, "calls")), False)
    check("and the row goes through", done.stdout.split("\t")[4] if done.stdout else "", "claude-md-a")


def batch(tmp):
    # A proposal the same as an earlier one of its own batch goes where that
    # one went: to its class, or out with it when CLAUDE.md has it.
    answer = json.dumps([{"n": 2, "verdict": "same", "class": "claude-md-a"},
                         {"n": 3, "verdict": "covered",
                          "quote": "A condition is spelled out once, next to the code that checks it."},
                         {"n": 4, "verdict": "same", "class": "claude-md-c"}])
    rows = [row("2026-10-24", "feat", "claude-md-a", "Proposal: a"),
            row("2026-10-24", "feat", "claude-md-b", "Proposal: a, said again"),
            row("2026-10-24", "feat", "claude-md-c", "Proposal: in CLAUDE.md"),
            row("2026-10-24", "feat", "claude-md-d", "Proposal: in CLAUDE.md, said again")]
    rc, out, said = run(tmp, rows, answer)
    check("batch: the second takes the first's class", [r[4] for r in out], ["claude-md-a", "claude-md-a"])
    check("batch: counted together", any(n.startswith("claude-md-a: 2nd time") for n in said), True)
    check("batch: the same as a covered one goes too",
          sum(1 for n in said if n.startswith("already in CLAUDE.md")), 2)


def main():
    for fn in (same, covered, invented, broken, counted, no_material, batch):
        case(fn)
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
