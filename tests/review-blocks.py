#!/usr/bin/env python3
#
# Review blocks (review_blocks.py, review_blocks.sh): a pull request too big
# for one review read in blocks, one after another, then the seams.
#
# Guarded here, with git real in a temporary directory:
#
#   * the size leaves generated files out;
#   * a cut is checked: every changed file in one block, every criterion in
#     one block or rule, no block past the size but a single file — each
#     fault said so that a second try can mend it; a model's answer is taken
#     from around a fence;
#   * the fallback cuts by the parts, each file to the part that changed most
#     of it, each criterion by its tag;
#   * a block's first read names its criteria, its files whole and its diff,
#     and the other blocks; a file the fixes added goes to the block read
#     next; the seams name what changed in a closed block after it closed;
#     a round's fixes name the closed blocks' files they touched;
#   * the journal counts a block's runs apart: its first read, its rounds,
#     its cache — the pull request's last head stays the one to read from;
#   * while blocks are read the review runs here, whatever the setting;
#   * blocks_next closes a block, begins step 4's record afresh, keeps the
#     old one under the block, and after the seams goes no further.
#
# Run it with: python3 tests/review-blocks.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401
import review_blocks  # noqa: E402
import local_review  # noqa: E402

failures = []
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(cwd, *args):
    return subprocess.run(GIT + list(args), cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def write(wt, path, text):
    full = os.path.join(wt, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as fh:
        fh.write(text)


def commit(wt, msg, **files):
    for path, text in files.items():
        write(wt, path.replace("__", "/"), text)
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", msg)
    return git(wt, "rev-parse", "HEAD")


PLAN = """# Plan

## Acceptance criteria

- [ ] AC1. [part 1] A person takes a ticket.
- [ ] AC2. [part 2] A person sees their tickets.
- [ ] AC3. Every refusal says why.
"""

tmp = tempfile.mkdtemp()
try:
    wt = os.path.join(tmp, "wt")
    os.makedirs(wt)
    git(wt, "init", "-q")
    base = commit(wt, "main", README="r\n")
    fdir = os.path.join(wt, ".sclaude", "local", "feature")
    os.makedirs(fdir)
    with open(os.path.join(wt, ".git", "info", "exclude"), "a") as fh:
        fh.write(".sclaude/\n")
    write(wt, ".sclaude/local/feature/plan.md", PLAN)
    p1 = commit(wt, "part 1", take__a="x\n" * 40, shared__s="one\n" * 10, **{"package-lock.json": "{}\n" * 500})
    p2 = commit(wt, "part 2", mine__b="y\n" * 30, shared__s="one\n" * 10 + "two\n" * 3)
    state = os.path.join(fdir, "state.json")
    with open(state, "w") as fh:
        json.dump({"parts": {"total": 2, "1": {"title": "Take", "range": "%s..%s" % (base, p1)},
                             "2": {"title": "Mine", "range": "%s..%s" % (p1, p2)}}}, fh)

    check("size-leaves-generated-out", review_blocks.size(wt, base), 40 + 13 + 30)
    listing = review_blocks.files(wt, base, state)
    check("listing-says-generated-and-parts", [l for l in listing if l.startswith("package-lock")],
          ["package-lock.json\t500\tgenerated\t1"])
    check("listing-says-every-part", [l.split("\t")[3] for l in listing if l.startswith("shared/")], ["1,2"])

    cut = os.path.join(fdir, "review-blocks.json")
    good = {"blocks": [
        {"title": "Taking a ticket", "criteria": ["AC1"], "files": ["take/a", "shared/s", "package-lock.json"],
         "why": "w", "contracts": ["with block 2: the ticket row"]},
        {"title": "My tickets", "criteria": ["AC2"], "files": ["mine/b"], "why": "w", "contracts": []}],
        "rules": [{"title": "Refusals say why", "criteria": ["AC3"], "where": ["take/a"]}]}
    answer = os.path.join(tmp, "answer.md")
    with open(answer, "w") as fh:
        fh.write("Here it is:\n```json\n%s\n```\n" % json.dumps(good))
    check("take-from-around-a-fence", review_blocks.take(answer, cut, base, p2), 0)
    check("take-records-base-and-source", {k: review_blocks.load(cut)[k] for k in ("base", "head", "source")},
          {"base": base, "head": p2, "source": "session"})
    check("a-good-cut-holds", review_blocks.validate(wt, base, cut, 3000), [])
    check("a-tight-size-splits", review_blocks.validate(wt, base, cut, 20),
          ["block 1 (Taking a ticket) has 53 changed lines, past 20: split it by behaviour"])

    def faults(change):
        bad = json.loads(json.dumps(good))
        change(bad)
        path = os.path.join(tmp, "bad.json")
        review_blocks.save(path, bad)
        return review_blocks.validate(wt, base, path, 3000)

    check("a-file-twice", faults(lambda d: d["blocks"][1]["files"].append("shared/s")),
          ["shared/s is in block 1 and block 2: a file has one owner"])
    check("a-file-nowhere", faults(lambda d: d["blocks"][1]["files"].clear()),
          ["block 2 (My tickets) owns no file: merge it into the block that owns its files",
           "mine/b is changed and in no block"])
    check("a-file-not-changed", faults(lambda d: d["blocks"][1]["files"].append("README")),
          ["README is in block 2 but this pull request does not change it"])
    check("a-criterion-nowhere", faults(lambda d: d["rules"].clear()), ["criterion AC3 is in no block and no rule"])
    check("a-criterion-twice", faults(lambda d: d["blocks"][1]["criteria"].append("AC1")),
          ["criterion AC1 is in block 1 and block 2: one place each"])
    check("a-criterion-made-up", faults(lambda d: d["blocks"][1]["criteria"].append("AC9")),
          ["criterion AC9 is not in the plan"])
    bad = os.path.join(tmp, "bad.json")
    review_blocks.save(bad, dict(good, rules=["permissions"]))
    said = subprocess.run(["python3", os.path.join(LIB, "review", "review_blocks.py"), "validate", wt, base, bad, "3000"],
                          capture_output=True, text=True)
    check("a-shape-not-asked-for-is-a-fault", (said.returncode, said.stdout.startswith("the cut does not have the shape")),
          (1, True))

    drafted = os.path.join(tmp, "draft.json")
    check("draft-ok", review_blocks.draft(wt, base, state, drafted), 0)
    d = review_blocks.load(drafted)
    check("draft-owner-changed-most", [b["files"] for b in d["blocks"]],
          [["package-lock.json", "shared/s", "take/a"], ["mine/b"]])
    check("draft-criteria-by-tag", ([b["criteria"] for b in d["blocks"]], d["rules"][0]["criteria"]),
          ([["AC1"], ["AC2"]], ["AC3"]))
    check("draft-holds", review_blocks.validate(wt, base, drafted, 3000), [])
    # A part that owns no file hands its criteria to the block before it.
    three = os.path.join(tmp, "three.json")
    p3 = commit(wt, "part 3", shared__s="one\n" * 10 + "two\n" * 3 + "three\n")
    with open(three, "w") as fh:
        json.dump({"parts": {"total": 3, "1": {"title": "Take", "range": "%s..%s" % (base, p1)},
                             "2": {"title": "Mine", "range": "%s..%s" % (p1, p2)},
                             "3": {"title": "Late", "range": "%s..%s" % (p2, p3)}}}, fh)
    write(wt, ".sclaude/local/feature/plan.md", PLAN + "- [ ] AC4. [part 3] A late rule.\n")
    check("draft-ownerless-part-hands-its-criteria",
          (review_blocks.draft(wt, base, three, drafted), [b["criteria"] for b in review_blocks.load(drafted)["blocks"]]),
          (0, [["AC1"], ["AC2", "AC4"]]))
    write(wt, ".sclaude/local/feature/plan.md", PLAN)
    git(wt, "reset", "-q", "--hard", p2)
    with open(os.path.join(tmp, "one.json"), "w") as fh:
        json.dump({"parts": {}}, fh)
    check("no-draft-without-parts", review_blocks.draft(wt, base, os.path.join(tmp, "one.json"), drafted), 1)

    check("summary", review_blocks.summary(cut),
          ["1. Taking a ticket — 3 files; AC1", "2. My tickets — 1 files; AC2",
           "3. The seams: the blocks together, and what changed in a closed block after it closed"])

    first = review_blocks.scope(wt, cut, 1, p2)
    check("first-read-names-its-block", first.startswith("block 1 of 2 of this pull request, read on its own: **Taking a ticket**"), True)
    check("first-read-quotes-its-criteria", "- AC1 — [part 1] A person takes a ticket." in first, True)
    check("first-read-names-the-rules", "- Refusals say why (AC3); built in take/a" in first, True)
    check("first-read-diffs-its-files", "`git diff %s..%s -- take/a shared/s package-lock.json`" % (base, p2) in first, True)
    check("first-read-names-the-others", "2. My tickets" in first and "do not review their code for its own sake" in first, True)

    # A fix of block 1 adds a file: block 2, read next, takes it.
    fix = commit(wt, "block 1 fix", take__a="x\n" * 41, mine__new="n\n")
    review_blocks.close(cut, 1, p2)
    check("closed-recorded", review_blocks.load(cut)["closed"], {"1": p2})
    second = review_blocks.scope(wt, cut, 2, fix)
    check("an-orphan-goes-to-the-block-read-next", review_blocks.load(cut)["blocks"][1]["files"], ["mine/b", "mine/new"])
    check("first-read-marks-the-closed", "1. Taking a ticket (read, closed)" in second, True)
    touched = review_blocks.touched(wt, cut, 2, p2, fix)
    check("a-round-names-the-closed-files-it-touched", "take/a — block 1, Taking a ticket, answers for AC1" in touched, True)
    check("nothing-closed-touched-says-nothing", review_blocks.touched(wt, cut, 2, fix, fix), "")
    # A block none of whose files is changed any more reads no diff as its own.
    gone = json.loads(json.dumps(review_blocks.load(cut)))
    gone["blocks"][1]["files"] = ["README"]
    gone["blocks"][0]["files"] += ["mine/b", "mine/new"]
    review_blocks.save(os.path.join(tmp, "gone.json"), gone)
    empty = review_blocks.scope(wt, os.path.join(tmp, "gone.json"), 2, fix)
    check("a-block-with-no-files-left-reads-no-diff", ("-- `" in empty or "-- ." in empty, "None of its files" in empty),
          (False, True))
    # A block whose files changed by a block's size since its whole read is
    # read whole again; generated files and other blocks' files count nothing.
    check("a-block-changed-past-the-limit-is-stale",
          (review_blocks.stale(wt, cut, 2, p2, fix, 1), review_blocks.stale(wt, cut, 2, p2, fix, 2),
           review_blocks.stale(wt, cut, 2, fix, fix, 1)), (True, False, False))
    seams = review_blocks.seams(wt, cut, fix)
    check("seams-name-a-closed-blocks-late-change",
          "block 1 (Taking a ticket, criteria AC1): `git diff %s..%s -- take/a`" % (p2, fix) in seams, True)
    check("seams-read-the-behaviours-together", "the behaviours together" in seams, True)

    # The journal counts a block's runs apart.
    j = os.path.join(tmp, "rounds.jsonl")
    rows = [{"at": "2026-11-12T10:00:00", "head": "h1", "base": "b0", "pr": "7", "block": "1", "read": "first"},
            {"at": "2026-11-12T11:00:00", "head": "h2", "base": "h1", "pr": "7", "block": "1", "read": "delta"},
            {"at": "2026-11-12T12:00:00", "head": "h2", "base": "b0", "pr": "7", "block": "2", "read": "first", "more": True}]
    with open(j, "w") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))

    def lr(block, *args):
        env = dict(os.environ, SCLAUDE_REVIEW_BLOCK=block)
        return subprocess.run(["python3", os.path.join(LIB, "review", "local_review.py")] + list(args),
                              capture_output=True, text=True, env=env)

    check("block-1-read-once", lr("1", "first", j, "h3", "7").returncode, 1)
    check("block-2-capped-reads-again", lr("2", "first", j, "h2", "7").returncode, 0)
    check("block-3-not-read-yet", lr("3", "first", j, "h2", "7").returncode, 0)
    check("rounds-per-block", (lr("1", "round", j, "h3", "7").stdout.strip(), lr("3", "round", j, "h2", "7").stdout.strip()),
          ("3", "1"))
    check("cached-per-block", (lr("1", "cached", j, "h2", "7").returncode, lr("3", "cached", j, "h2", "7").returncode), (0, 1))
    check("since-is-the-prs", lr("3", "since", j, "h9", "7").stdout.strip(), "h2")
    check("whole-is-the-blocks-last-first-read",
          (lr("1", "whole", j, "7").stdout.strip(), lr("3", "whole", j, "7").stdout.strip()), ("h1", ""))
    os.environ["SCLAUDE_REVIEW_BLOCK"] = "2"
    os.environ["SCLAUDE_REVIEW_READ"] = "first"
    row = {}
    local_review.tag(row)
    del os.environ["SCLAUDE_REVIEW_BLOCK"], os.environ["SCLAUDE_REVIEW_READ"]
    check("a-row-tagged-with-its-block", row, {"block": "2", "read": "first"})

    # The shell side: the mode, and blocks_next.
    def sh(script):
        body = ('set -uo pipefail\nBOLD=""; OFF=""; GREEN=""; REPO=%s; LIB=%s; SELF=sclaude\n' % (wt, LIB)
                + "".join('source "%s/%s.sh"\n' % (LIB, m) for m in ("core/io", "core/ui", "core/state", "core/project",
                                                                   "review/review_blocks"))
                + 'info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }; ask_feed() { :; }\n'
                + 'gh() { echo "GH $*" >> "%s/gh.log"; }\n' % tmp + script)
        out = subprocess.run(["bash", "-c", body], cwd=wt, capture_output=True, text=True, timeout=60)
        return out.stdout + out.stderr

    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "github"}, fh)
    import pr_context  # noqa: E402
    rollup = [{"name": "test", "workflowName": "CI", "conclusion": "FAILURE"},
              {"name": "claude-review", "workflowName": "Claude Code Review", "conclusion": "FAILURE"}]
    check("ci-counts-while-in-blocks", [c["name"] for c in pr_context.verdict_rollup(wt, rollup)], ["test"])
    # Moved here for want of Actions minutes: that rule holds, CI out.
    write(wt, ".sclaude/local/feature/review-fallback", "minutes\tx\n")
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "github-local"}, fh)
    pr_context._MODES.clear(); pr_context._TOPS.clear()
    check("a-move-for-minutes-keeps-ci-out", [c["name"] for c in pr_context.verdict_rollup(wt, rollup)], [])
    check("a-move-for-minutes-is-not-the-blocks", sh('project_review_in_blocks "%s" || echo NO' % wt).strip(), "NO")
    os.remove(os.path.join(fdir, "review-fallback"))
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "local"}, fh)
    check("a-local-setting-is-not-the-blocks", sh('project_review_in_blocks "%s" || echo NO' % wt).strip(), "NO")
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "github"}, fh)
    # The shell and the Python answer the same mode, and the same "CI counts".
    agree = []
    for setting, mark in (("github", False), ("github", True), ("github-local", False), ("github-local", True),
                          ("local", False), ("off", False)):
        with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
            json.dump({"review": setting}, fh)
        if mark:
            write(wt, ".sclaude/local/feature/review-fallback", "minutes\tx\n")
        pr_context._MODES.clear(); pr_context._TOPS.clear(); pr_context._SETTING.clear()
        said = sh('project_review_mode "%s"; project_review_in_blocks "%s" && echo yes || echo no' % (wt, wt)).split()
        if said != [pr_context.review_mode(wt), "yes" if pr_context.in_blocks(wt) else "no"]:
            agree.append((setting, mark, said, pr_context.review_mode(wt), pr_context.in_blocks(wt)))
        if mark:
            os.remove(os.path.join(fdir, "review-fallback"))
    check("shell-and-python-agree-while-in-blocks", agree, [])
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "github"}, fh)
    with open(os.path.join(LIB, "review", "local_review.sh")) as fh:
        src = fh.read()
    check("the-block-named-before-its-first-read-is-asked",
          src.index('SCLAUDE_REVIEW_BLOCK="$block"') < src.index('local_review.py" first'), True)
    check("a-stale-block-is-read-whole-before-the-read-is-tagged",
          src.index('blocks_stale "$wt" "$head"') < src.index('SCLAUDE_REVIEW_READ="${first:+first}"'), True)
    with open(state, "w") as fh:
        json.dump({"pr": 7, "blocks": {"total": 3, "current": 1, "pr": 7, "label_before": "no"},
                   "steps": {"review": {"runs": [{"session": "r1"}], "rounds": 4, "enough": "pass"}}}, fh)
    check("read-here-while-in-blocks", sh('project_review_mode "%s"' % wt).strip(), "local")
    # Ending the search mid-way, closing the review closes the block, and the
    # question says so rather than "close step 4".
    words = sh('source "%s/review/review_gate.sh"; blocks_now() { echo 1; }; blocks_total() { echo 3; }; '
               'review_close_words "%s"' % (LIB, wt)).splitlines()
    check("close-names-the-block", words, ["Close block 1/3 now and go on to block 2/3", "Close block 1/3"])
    words = sh('source "%s/review/review_gate.sh"; blocks_active() { return 1; }; '
               'review_close_words "%s"' % (LIB, wt)).splitlines()
    check("close-without-blocks-is-step-4", words, ["Close step 4 now", "Close step 4"])
    out = sh('blocks_active "%s" && echo ACTIVE; blocks_next "%s" t && echo NEXT' % (wt, wt))
    with open(state) as fh:
        st = json.load(fh)
    check("next-block-opens", ("ACTIVE" in out, "NEXT" in out, st["blocks"]["current"]), (True, True, 2))
    check("next-block-step-afresh", (st["steps"]["review"], st["blocks"]["1"]["steps"]["review"]["rounds"]),
          ({"runs": [{"session": "r1"}]}, 4))
    check("next-block-closed-head", review_blocks.load(cut)["closed"].get("1"), git(wt, "rev-parse", "HEAD"))
    sh('blocks_next "%s" t' % wt)
    out = sh('blocks_next "%s" t || echo LAST' % wt)
    with open(state) as fh:
        check("after-the-seams-no-further-and-the-cut-off", ("LAST" in out, json.load(fh)["blocks"]["current"],
                                                             os.path.exists(cut)), (True, 3, False))
    check("read-as-set-after-the-seams", sh('project_review_mode "%s"' % wt).strip(), "github")
    with open(os.path.join(tmp, "gh.log")) as fh:
        said = fh.read()
    check("no-draft-or-ready-pressed-and-the-label-off", ("pr ready" in said, "pr edit 7 --remove-label no-review" in said),
          (False, True))
    # A label the person put there stays: the cut did not put it on.
    review_blocks.save(cut, good)
    with open(state, "w") as fh:
        json.dump({"pr": 7, "blocks": {"total": 3, "current": 3, "pr": 7, "label_before": "yes"}}, fh)
    os.remove(os.path.join(tmp, "gh.log"))
    sh('blocks_next "%s" t' % wt)
    check("the-persons-label-stays", os.path.exists(os.path.join(tmp, "gh.log")), False)
    # Nobody could tell whether it was there: it comes off — a review too many
    # is better than none.
    review_blocks.save(cut, good)
    with open(state, "w") as fh:
        json.dump({"pr": 7, "blocks": {"total": 3, "current": 3, "pr": 7}}, fh)
    sh('blocks_next "%s" t' % wt)
    check("an-unknown-label-comes-off", os.path.exists(os.path.join(tmp, "gh.log"))
          and "--remove-label no-review" in open(os.path.join(tmp, "gh.log")).read(), True)
    # The cut keeps whether the pull request carried the label before it, as
    # GitHub said; one the person put there before is theirs.
    labels = os.path.join(tmp, "labels")
    stub = ('project_get() { case "$1" in reviewBlocks.from) echo 10;; *) echo 99999;; esac; }\n'
            'blocks_base() { echo %s; }; history_add() { :; }\n'
            'blocks_cut_session() { cp %s "$4"; }\n'
            'gh() { case "$1 $2" in "pr view") cat %s;; "pr edit") echo no-review >> %s;; esac; }\n'
            % (base, os.path.join(tmp, "good.json"), labels, labels))
    whole = json.loads(json.dumps(good))
    whole["blocks"][1]["files"].append("mine/new")
    review_blocks.save(os.path.join(tmp, "good.json"), dict(whole, base=base, head=p2, source="session", closed={}))
    for before, want in (("", "no"), ("no-review\n", "yes")):
        with open(labels, "w") as fh:
            fh.write(before)
        with open(state, "w") as fh:
            json.dump({"pr": 9}, fh)
        if os.path.exists(cut):
            os.remove(cut)
        sh('source "%s/review/local_review.sh"\n%sblocks_ensure "%s" 9' % (LIB, stub, wt))
        with open(state) as fh:
            check("the-cut-keeps-whether-the-label-was-there (%s)" % (before.strip() or "no label"),
                  json.load(fh).get("blocks", {}).get("label_before"), want)
    os.remove(cut)
    # A read of the labels that fails tells nothing: no label_before kept.
    failing = stub.replace('"pr view") cat %s;;' % labels, '"pr view") return 1;;')
    with open(state, "w") as fh:
        json.dump({"pr": 9}, fh)
    sh('source "%s/review/local_review.sh"\n%sblocks_ensure "%s" 9' % (LIB, failing, wt))
    with open(state) as fh:
        check("a-failed-read-keeps-nothing", "label_before" in json.load(fh).get("blocks", {}), False)
    # Emptying the node takes the cut on disk with it.
    review_blocks.save(cut, good)
    sh('blocks_clear "%s"' % wt)
    with open(state) as fh:
        check("blocks-clear-takes-the-cut", (os.path.exists(cut), json.load(fh).get("blocks")), (False, {}))
    # The base parts_join left belongs to the first pull request seen after
    # it, decided small or not; another one starts without it.
    small = 'project_get() { echo 99999; }; history_add() { :; }\n'
    with open(state, "w") as fh:
        json.dump({"pr": 10, "blocks": {"base": base}}, fh)
    sh(small + 'blocks_ensure "%s" 10' % wt)
    with open(state) as fh:
        check("the-joins-base-kept-for-the-first-pr", json.load(fh)["blocks"], {"base": base, "pr": 10, "total": 0})
    sh(small + 'blocks_ensure "%s" 11' % wt)
    with open(state) as fh:
        got = json.load(fh)["blocks"]
        check("another-pr-starts-without-it", (got.get("base"), got.get("pr")), (None, 11))
    # Review off: nothing decided, the pull request claimed all the same.
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "off"}, fh)
    with open(state, "w") as fh:
        json.dump({"pr": 12, "blocks": {"base": base}}, fh)
    sh(small + 'blocks_ensure "%s" 12; blocks_ensure "%s" 13' % (wt, wt))
    with open(state) as fh:
        check("review-off-still-claims-the-pr", json.load(fh)["blocks"], {"pr": 13})
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "github"}, fh)
    # A new pull request is decided afresh: the old one's cut does not hold it.
    with open(state, "w") as fh:
        json.dump({"pr": 8, "blocks": {"total": 3, "current": 3, "pr": 7, "base": base, "1": {"steps": {}}}}, fh)
    review_blocks.save(cut, good)
    out = sh('project_get() { echo 99999; }; blocks_base() { echo %s; }; blocks_ensure "%s" 8; echo DONE' % (base, wt))
    with open(state) as fh:
        st = json.load(fh)
    check("a-new-pr-decided-afresh", (st["blocks"], os.path.exists(cut)), ({"pr": 8, "total": 0}, False))
    # A block changed past a block's size since its whole read: read whole
    # on its next pass, and not closed before.
    review_blocks.save(cut, good)
    jj = os.path.join(tmp, "stale.jsonl")
    with open(jj, "w") as fh:
        fh.write(json.dumps({"at": "2026-11-12T10:00:00", "head": base, "pr": "9", "block": "1", "read": "first"}) + "\n")
    with open(state, "w") as fh:
        json.dump({"pr": 9, "blocks": {"total": 3, "current": 1, "pr": 9, "base": base}}, fh)
    stub = 'review_journal() { echo %s; }; review_enough() { :; }; ' % jj
    head = git(wt, "rev-parse", "HEAD")
    check("a-changed-block-is-stale",
          (sh(stub + 'project_get() { echo 1; }; blocks_stale "%s" %s && echo STALE' % (wt, head)).strip(),
           sh(stub + 'project_get() { echo 99999; }; blocks_stale "%s" %s || echo FRESH' % (wt, head)).strip()),
          ("STALE", "FRESH"))
    # Its pass on this head is still to come (the gate runs it before the
    # close), unless the person ended the search.
    # The head read as a diff already: cached, yet not done.
    with open(jj, "a") as fh:
        fh.write(json.dumps({"at": "2026-11-12T11:00:00", "head": head, "pr": "9", "block": "1", "read": "delta"}) + "\n")
    done = 'source "%s/review/local_review.sh"; project_get() { echo 1; }; blocks_active() { :; }; ' % LIB
    check("a-fresh-block-read-as-a-diff-is-done",
          sh(done.replace("echo 1;", "echo 99999;") + stub + 'local_review_done "%s" && echo DONE || echo PENDING' % wt).strip().splitlines()[-1], "DONE")
    check("a-stale-block-is-not-done-on-a-read-head",
          sh(done + stub + 'local_review_done "%s" && echo DONE || echo PENDING' % wt).strip().splitlines()[-1], "PENDING")
    feed = 'ask_feed() { echo "FEED $*"; }; history_add() { :; }; '
    with open(state, "w") as fh:
        json.dump({"pr": 9, "blocks": {"total": 3, "current": 1, "pr": 9, "base": base}}, fh)
    out = sh(stub + feed + 'project_get() { echo 99999; }; blocks_next "%s" t; echo END' % wt)
    check("a-fresh-block-closes-quietly", ("not read whole" in out, "FEED say 🧱 Block 1/3 of PR #9 reviewed." in out), (False, True))
    with open(state, "w") as fh:
        json.dump({"pr": 9, "blocks": {"total": 3, "current": 1, "pr": 9, "base": base}}, fh)
    review_blocks.save(cut, good)
    out = sh(stub + feed + 'project_get() { echo 1; }; blocks_next "%s" t; echo END' % wt)
    with open(state) as fh:
        check("a-stale-block-closing-says-it-was-not-read-whole",
              (out.count("not read whole"), "FEED say 🧱 Block 1/3 of PR #9 reviewed, its latest change not read whole" in out,
               json.load(fh)["blocks"]["current"]), (2, True, 2))
    # A merge brings no change of the block's own.
    git(wt, "checkout", "-q", "-b", "side", base)
    commit(wt, "on main", take__a="m\n" * 50)
    git(wt, "checkout", "-q", "-")
    git(wt, "merge", "-q", "--no-edit", "-X", "theirs", "side")
    merged = git(wt, "rev-parse", "HEAD")
    check("a-merge-is-no-change-of-the-block", review_blocks.stale(wt, cut, 1, head, merged, 1), False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    print("%d failed" % len(failures))
    sys.exit(1)
print("review-blocks: ok")
