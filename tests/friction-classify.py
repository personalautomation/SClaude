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
    folder = os.path.join(tmp, "main", "team", "deferred")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "other.tsv"), "w") as fh:
        fh.write("".join(r + "\n" for r in main_rows))
    if reviewed:
        with open(os.path.join(folder, "last-reviewed"), "w") as fh:
            fh.write(reviewed + "\n")
    own_dir = os.path.join(tmp, "tree", "team", "deferred")
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
    check("covered: put off under a class of its own, not dropped",
          [r[4] for r in out], ["claude-md-already-stated"])
    check("covered: the row quotes CLAUDE.md", out[0][5].startswith("Already in CLAUDE.md (") if out else False, True)
    check("covered: the note says so", any("already in CLAUDE.md" in n for n in said), True)


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
    os.makedirs(os.path.join(tmp, "main", "team", "deferred"))
    with open(os.path.join(tmp, "main", "team", "deferred", "feat.tsv"), "w") as fh:
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
    check("batch: the second takes the first's class, the covered ones theirs", [r[4] for r in out],
          ["claude-md-a", "claude-md-a", "claude-md-already-stated", "claude-md-already-stated"])
    check("batch: counted together", any(n.startswith("claude-md-a: 2nd time") for n in said), True)
    check("batch: the same as a covered one goes too",
          sum(1 for n in said if n.startswith("already in CLAUDE.md")), 2)


def other_person(tmp):
    # Another person's file of the same feature is theirs, and counts too.
    bob = os.path.join(tmp, "main", "people", "bob", "deferred")
    os.makedirs(bob)
    with open(os.path.join(bob, "feat.tsv"), "w") as fh:
        fh.write(row("2026-10-23", "feat", "claude-md-a", "Proposal: a, by bob") + "\n")
    folder = os.path.join(tmp, "main", "team", "deferred")
    os.makedirs(folder)
    own = os.path.join(tmp, "tree", "team", "deferred", "feat.tsv")
    os.makedirs(os.path.dirname(own))
    open(own, "w").close()
    notes = os.path.join(tmp, "notes")
    subprocess.run([sys.executable, SCRIPT, "--notes", notes, "--own", own, folder, bob],
                   input=row("2026-10-24", "feat", "claude-md-a", "Proposal: a") + "\n",
                   capture_output=True, text=True, env=dict(os.environ, PATH="/usr/bin:/bin"), timeout=60)
    check("another person's file of the feature counts",
          any(n.startswith("claude-md-a: 2nd time") for n in open(notes).read().splitlines()), True)


def not_a_rule(tmp):
    # "same" as the classes that are no rule is refused: the covered one (its
    # quote is the check) and the one a proposal naming no class gets.
    answer = json.dumps([{"n": 1, "verdict": "same", "class": "claude-md-already-stated"},
                         {"n": 2, "verdict": "same", "class": "claude-md-proposal"}])
    rows = [row("2026-10-24", "feat", "claude-md-x", "Proposal: x"),
            row("2026-10-24", "feat", "claude-md-y", "Proposal: y")]
    main_rows = [row("2026-10-20", "o", "claude-md-already-stated", "Already in CLAUDE.md: z"),
                 row("2026-10-20", "o", "claude-md-proposal", "Proposal: w")]
    rc, out, said = run(tmp, rows, answer, main_rows=main_rows)
    check("same as a class that is no rule is refused", [r[4] for r in out], ["claude-md-x", "claude-md-y"])


def follows_class(tmp):
    # A row with no verdict goes where an earlier one of its class went; and
    # classes that are no CLAUDE.md rule are not offered or taken.
    answer = json.dumps([{"n": 1, "verdict": "same", "class": "claude-md-b"},
                         {"n": 3, "verdict": "same", "class": "sclaude-default"}])
    rows = [row("2026-10-24", "feat", "claude-md-a", "Proposal: a"),
            row("2026-10-24", "feat", "claude-md-a", "Proposal: a, again"),
            row("2026-10-24", "feat", "claude-md-c", "Proposal: c")]
    main_rows = [row("2026-10-20", "o", "claude-md-b", "Proposal: b"),
                 row("2026-10-20", "o", "sclaude-default", "A default of sclaude's")]
    rc, out, said = run(tmp, rows, answer, main_rows=main_rows)
    check("a row with no verdict follows its class", [r[4] for r in out],
          ["claude-md-b", "claude-md-b", "claude-md-c"])


def sh(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git"] + list(args), cwd=cwd, env=env, check=True, capture_output=True)


def pushed(tmp, rows, stamp=None):
    """A checkout at tmp/main whose origin/main holds team/deferred/feat.tsv
    with these rows (and last-reviewed), its own tree without them."""
    repo = os.path.join(tmp, "main")
    sh(tmp, "init", "-q", "--bare", "origin.git")
    sh(tmp, "init", "-q", "-b", "main", "main")
    sh(repo, "remote", "add", "origin", os.path.join(tmp, "origin.git"))
    sh(repo, "commit", "-q", "--allow-empty", "-m", "start")
    folder = os.path.join(repo, "team", "deferred")
    os.makedirs(folder)
    with open(os.path.join(folder, "feat.tsv"), "w") as fh:
        fh.write("".join(r + "\n" for r in rows))
    if stamp:
        with open(os.path.join(folder, "last-reviewed"), "w") as fh:
            fh.write(stamp + "\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "put off")
    sh(repo, "push", "-q", "origin", "HEAD:main")
    sh(repo, "reset", "-q", "--hard", "HEAD~1")
    return folder


SENT = row("2026-10-22", "feat", "claude-md-a", "Proposal: a, sent to main")
AGAIN = [row("2026-10-24", "feat", "claude-md-a", "Proposal: a again")]


def upstream(tmp):
    # Rows put off after a review go to main from a tree of their own and
    # leave the branch; the checkout the folders are read in is not pulled.
    # Read from trees alone, a rule put off twice in a feature was the first
    # time both times.
    folder = pushed(tmp, [SENT])
    rc, out, said = run(tmp, AGAIN, "[]")
    check("a row only on origin/main is counted",
          any(n.startswith("claude-md-a: 2nd time") for n in said), True)
    with open(os.path.join(folder, "feat.tsv"), "w") as fh:
        fh.write(SENT + "\n")
    rc, out, said = run(tmp, AGAIN, "[]", own_rows=[SENT])
    check("a row in the tree, on main and in the feature's file is counted once",
          any(n.startswith("claude-md-a: 2nd time") for n in said), True)


def upstream_no_folder(tmp):
    # A product's first rows: sent to main, the folder gone from the checkout,
    # so no folder is given — the feature's own folder is read on main.
    folder = pushed(tmp, [SENT])
    shutil.rmtree(os.path.join(tmp, "main", "team"), ignore_errors=True)
    notes = os.path.join(tmp, "notes")
    subprocess.run([sys.executable, SCRIPT, "--notes", notes, "--own", os.path.join(folder, "feat.tsv")],
                   input=AGAIN[0] + "\n", capture_output=True, text=True,
                   env=dict(os.environ, PATH="/usr/bin:/bin"), timeout=60)
    check("a folder only on origin/main is read for the feature's file",
          any(n.startswith("claude-md-a: 2nd time") for n in open(notes).read().splitlines()), True)


def upstream_stamp(tmp):
    # The monthly review's stamp is on main, the checkout has an older one:
    # the rows main holds from before it are not counted.
    old = row("2026-10-10", "older", "claude-md-a", "Proposal: a, reviewed already")
    pushed(tmp, [old], stamp="2026-10-20")
    rc, out, said = run(tmp, AGAIN, "[]", reviewed="2026-10-01")
    check("the later stamp, main's, bounds the count",
          any(n.startswith("claude-md-a: 1st time") for n in said), True)


def upstream_stamp_branch_rows(tmp):
    # Main's stamp bounds main's rows: a row the branch holds and main does
    # not was never in front of that review.
    pushed(tmp, [], stamp="2026-10-20")
    mine = row("2026-10-15", "feat", "claude-md-a", "Proposal: a, on the branch only")
    rc, out, said = run(tmp, AGAIN, "[]", own_rows=[mine])
    check("a branch row before main's stamp still counts",
          any(n.startswith("claude-md-a: 2nd time") for n in said), True)


def glob_in_path(tmp):
    # A folder whose path a glob would read as a pattern.
    base = os.path.join(tmp, "a[1]")
    os.makedirs(base)
    mine = row("2026-10-22", "feat", "claude-md-a", "Proposal: a, earlier")
    other = row("2026-10-21", "other", "claude-md-a", "Proposal: a, another feature's")
    rc, out, said = run(base, AGAIN, "[]", own_rows=[mine], main_rows=[other])
    check("a path with [ ] in it is read, other features' files too",
          any(n.startswith("claude-md-a: 3rd time") for n in said), True)


def upstream_stamp_tree_rows(tmp):
    # A row the unpulled tree holds and main does not — not on main yet, or
    # taken out by the review there — is counted: one too many costs nothing,
    # one too few hides a rule that came back.
    pushed(tmp, [], stamp="2026-10-20")
    other = row("2026-10-15", "other", "claude-md-a", "Proposal: a, not on main")
    rc, out, said = run(tmp, AGAIN, "[]", main_rows=[other])
    check("a row only the tree holds counts under main's later stamp",
          any(n.startswith("claude-md-a: 2nd time") for n in said), True)


def main():
    for fn in (same, covered, invented, broken, counted, no_material, batch, other_person, not_a_rule,
               follows_class, upstream, upstream_no_folder, upstream_stamp,
               upstream_stamp_branch_rows, glob_in_path,
               upstream_stamp_tree_rows):
        case(fn)
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
