#!/usr/bin/env python3
"""The review's map (sclaude/lib/review/review_map.py) read from a tree:
the rounds from the journal, the fixes between their heads, the threads and
how they ended, the person's answers from a transcript and the history, and
the page that draws it (process_review.js) wired into the process map."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "sclaude", "lib", "review", "review_map.py")
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib"))
import _path  # noqa: E402,F401
import claude_usage  # noqa: E402
import pr_context  # noqa: E402
import review_report  # noqa: E402
from local_review import JOURNAL  # noqa: E402

failures = []


def check(what, ok):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        failures.append(what)


def git(tree, *args):
    return subprocess.run(["git", "-C", tree] + list(args), check=True, capture_output=True,
                          text=True).stdout.strip()


with tempfile.TemporaryDirectory() as tmp:
    tree = os.path.join(tmp, "tree")
    os.makedirs(tree)
    git(tree, "init", "-q", "-b", "main")
    git(tree, "config", "user.email", "t@example.com")
    git(tree, "config", "user.name", "t")
    with open(os.path.join(tree, "app.py"), "w") as fh:
        fh.write("".join("x%d = %d\n" % (i, i) for i in range(1, 41)))
    git(tree, "add", "app.py")
    git(tree, "commit", "-qm", "base")
    git(tree, "update-ref", "refs/remotes/origin/HEAD", "HEAD")
    with open(os.path.join(tree, "notes.md"), "w") as fh:
        fh.write("# notes\n")
    git(tree, "add", "notes.md")
    git(tree, "commit", "-qm", "feature")
    first = git(tree, "rev-parse", "HEAD")
    # Round 1's fixes: code at line 10, a comment and two new lines at 30.
    lines = open(os.path.join(tree, "app.py")).read().splitlines()
    lines[9] = "x10 = 100"
    lines[29:30] = ["# why thirty", "x30 = 30", "y30 = 31", "z30 = 32"]
    with open(os.path.join(tree, "app.py"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(tree, "notes.md"), "a") as fh:
        fh.write("the guard, explained\n")
    git(tree, "commit", "-qam", "fix round 1")
    second = git(tree, "rev-parse", "HEAD")

    feature = os.path.join(tree, ".sclaude", "local", "feature")
    os.makedirs(feature)
    with open(os.path.join(feature, "state.json"), "w") as fh:
        json.dump({"pr": "7", "repo": "o/r"}, fh)
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "seconds": 60, "head": first, "pr": "7", "new": 3},
                    {"at": "2026-01-01T10:05:00+00:00", "seconds": 30, "head": first, "pr": "7"},
                    {"at": "2026-01-01T12:00:00+00:00", "seconds": 90, "head": second, "pr": "7",
                     "source": "github", "run": 1},
                    {"at": "2026-01-01T09:00:00+00:00", "seconds": 5, "head": "0" * 40, "pr": "7"},
                    {"at": "2026-01-01T09:30:00+00:00", "seconds": 5, "head": first, "pr": "6"},
                    {"at": "2026-01-01T12:30:00+00:00", "seconds": 9, "head": second, "pr": "7", "spent": True}):
            fh.write(json.dumps(row) + "\n")
    with open(os.path.join(feature, "history.jsonl"), "w") as fh:
        fh.write(json.dumps({"at": "2026-01-01T11:00:00+00:00", "what": "ask", "op": "answered",
                             "waited": "12"}) + "\n")
        fh.write(json.dumps({"at": "2026-01-01T08:00:00+00:00", "what": "ask", "op": "answered"}) + "\n")

    def thread(rid, path, line, commit, at, replies=(), resolved=False, bot=True):
        first_c = {"author": {"login": "bot", "__typename": "Bot" if bot else "User"},
                   "body": "**claim %s** more" % rid, "createdAt": at,
                   "url": "https://github.com/o/r/pull/7#discussion_r%s" % rid,
                   "originalCommit": {"oid": commit}}
        return {"isResolved": resolved, "path": path, "line": None, "originalLine": line,
                "resolvedBy": {"login": "me"} if resolved else None,
                "comments": {"nodes": [first_c] + [{"author": {"__typename": "User"}, "body": b}
                                                   for b in replies]}}
    url = "https://github.com/o/r/pull/7#discussion_r%s"
    nodes = [thread(1, "app.py", 10, first, "2026-01-01T10:01:00Z", resolved=True),
             thread(2, "app.py", 30, first, "2026-01-01T10:01:00Z",
                    replies=[pr_context.DECLINE_PREFIX + ": not needed"], resolved=True),
             thread(3, "app.py", 5, first, "2026-01-01T10:02:00Z"),
             thread(4, "app.py", 20, first, "2026-01-01T10:02:00Z"),
             # Noted as a reversal, then resolved without a decline: still
             # a reversal, whatever became of it.
             thread(7, "app.py", 24, first, "2026-01-01T10:02:00Z", resolved=True),
             # Noted as a reversal, given to a subagent later and resolved,
             # a reply naming a commit: a reversal, and no fix of that commit
             # is taken for it.
             thread(8, "app.py", 27, first, "2026-01-01T10:02:00Z", resolved=True,
                    replies=["Would undo the fix in %s, app.py" % second[:7]]),
             thread(5, "notes.md", 1, "", "2026-01-01T12:30:00Z", bot=False),
             # Fixed in another file, the reply says: the commit and the file.
             thread(6, "app.py", 38, first, "2026-01-01T10:03:00Z",
                    replies=["Fixed in %s: notes.md now says why, in plain words." % second[:7]], resolved=True)]
    fake = os.path.join(tmp, "threads.json")
    with open(fake, "w") as fh:
        json.dump(nodes, fh)
    with open(os.path.join(tree, pr_context.YOURS_FILE), "w") as fh:
        fh.write(url % 3 + "\tkeep it " + pr_context.NIGHT_MARK + ")\n")
    with open(os.path.join(feature, "review-reversals"), "w") as fh:
        fh.write(url % 4 + "\tundoes the guard\n# counted 2026-01-01T11:00:00+00:00\n" + url % 7 + "\tundoes the flag\n" + url % 8 + "\tundoes the cap\n")

    # A transcript of the fix session: one question about thread 2,
    # answered with the recommended option eight seconds later.
    home = os.path.join(tmp, "home")
    folder = os.path.join(home, ".claude", "projects", claude_usage.project_name(tree))
    os.makedirs(folder)
    q = "Leave %s as it is?" % (url % 2)
    # A subagent of that session given the finding at app.py:10, which also
    # edited notes.md: the notes' fix answers thread 1 too.
    agents = os.path.join(folder, "s1", "subagents")
    os.makedirs(agents)
    with open(os.path.join(agents, "agent-a1.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": "2026-01-01T10:40:00.000Z",
                             "message": {"content": "Fix the finding at `app.py` (~line 10): the guard is wrong."}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "timestamp": "2026-01-01T10:41:00.000Z",
                             "message": {"content": [{"type": "tool_use", "id": "e1", "name": "Edit",
                                                      "input": {"file_path": os.path.join(tree, "app.py")}},
                                                     {"type": "tool_use", "id": "e2", "name": "Edit",
                                                      "input": {"file_path": os.path.join(tree, "notes.md")}}]}}) + "\n")
    with open(os.path.join(agents, "agent-a2.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": "2026-01-01T10:42:00.000Z",
                             "message": {"content": "Apply %s after all." % (url % 8)}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "timestamp": "2026-01-01T10:43:00.000Z",
                             "message": {"content": [{"type": "tool_use", "id": "e3", "name": "Edit",
                                                      "input": {"file_path": os.path.join(tree, "cap.txt")}}]}}) + "\n")
    with open(os.path.join(folder, "s1.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "assistant", "timestamp": "2026-01-01T10:30:00.000Z",
                             "message": {"content": [{"type": "tool_use", "id": "t1", "name": "AskUserQuestion",
                                                      "input": {"questions": [{"question": q, "options": [
                                                          {"label": "Leave it (Recommended)"}, {"label": "Fix it"}]}]}}]}}) + "\n")
        fh.write(json.dumps({"type": "user", "timestamp": "2026-01-01T10:30:08.000Z",
                             "toolUseResult": {"answers": {q: "Leave it (Recommended)"}},
                             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}}) + "\n")

    env = dict(os.environ, HOME=home, SCLAUDE_REVIEW_MAP_THREADS=fake)
    out = subprocess.run([sys.executable, MAP, tree], capture_output=True, text=True, env=env)
    check("review_map.py exits 0 (%s)" % out.stderr.strip()[-200:], out.returncode == 0)
    d = json.loads(out.stdout)
    # A cut whose first block was split: the blocks by their ids, the cut
    # before kept for the page to play (review_blocks.py split).
    cutfile = os.path.join(tree, ".sclaude", "local", "feature", "review-blocks.json")
    with open(cutfile, "w") as fh:
        json.dump({"base": "x", "blocks": [{"id": "1a", "title": "A", "files": ["app.py"]},
                                           {"id": "1b", "title": "B", "files": ["notes.md"]}, {"title": "C", "files": []}],
                   "earlier": [{"until": "2026-01-01T10:10:00+00:00", "split": "1",
                                "blocks": [{"id": "1", "title": "AB", "files": ["app.py", "notes.md"]}]}]}, fh)
    cut = json.loads(subprocess.run([sys.executable, MAP, tree], capture_output=True, text=True, env=env).stdout)
    os.remove(cutfile)
    check("the blocks carry their criteria", cut["blocks"][0]["criteria"] == [])
    check("the blocks carry their ids, a block without one its place",
          [(b["n"], b["id"]) for b in cut["blocks"]] == [(1, "1a"), (2, "1b"), (3, "3")])
    check("the cut before a split is kept, by its time",
          [(e["split"], [b["id"] for b in e["blocks"]]) for e in cut["earlier"]] == [("1", ["1"])]
          and cut["earlier"][0]["until"] == 1767262200.0)
    check("the rounds are the report's rows: a head read twice in one range is one; a missing commit undrawn, its number kept; another PR left out; a pass stopped on a read head a round of its own",
          [(r["head"], r["seq"], r["stopped"]) for r in d["rounds"]] == [(first, 2, False), (second, 3, False), (second, 4, True)])
    check("a round read twice adds its time", d["rounds"][0]["seconds"] == 90)
    check("the files are what the PR changed and what its fixes touched",
          [f["path"] for f in d["files"]] == ["app.py", "notes.md"])
    check("lines per round", d["rounds"][0]["lines"]["app.py"] == 40 and d["final"]["app.py"] == 43)
    check("the development: what the PR wrote by its first round, and since when",
          d["dev"]["files"].get("notes.md", {}).get("add") == 1 and d["dev"]["files"]["notes.md"]["comment"] == 1
          and isinstance(d["dev"]["t"], int))
    notes = [x for x in d["hunks"] if x["path"] == "notes.md"]
    check("a fix in a file the subagent edited for a thread answers that thread",
          len(notes) == 1 and notes[0]["thread"] == "r1" and notes[0]["via"] == "agent"
          and notes[0]["outcome"] == "fixed" and notes[0]["agent"] == "agent-a1")
    fixes = sorted([x for x in d["hunks"] if x["path"] == "app.py"], key=lambda x: x["x"])
    check("round 1's fixes, git's hunks", len(fixes) == 3 and all(x["r"] == 0 for x in fixes))
    check("a fix at its line in the newer version", [x["x"] for x in fixes] == [10, 30, 32])
    check("code and comment lines counted", fixes[1]["comment"] == 1 and fixes[1]["code"] == 0
          and fixes[2]["code"] == 2 and fixes[0]["code"] == 2)
    check("a fix takes its thread's outcome", fixes[0]["outcome"] == "fixed"
          and fixes[1]["outcome"] == "declined" and fixes[1]["thread"] == "r2")
    check("a fix near a thread takes it, whoever edited the file",
          fixes[0]["thread"] == "r1" and fixes[1]["thread"] == "r2" and fixes[1]["via"] == "near")
    axis = {f["path"]: f.get("axis") for f in d["files"]}
    check("the projected axis keeps every line ever in the file: the first round's and all a fix wrote",
          axis["app.py"] == 40 + sum(x["add"] for x in fixes))
    check("a fix's place on the axis follows its line, and a thread sits at its own",
          [x["p0"] for x in fixes] == sorted(x["p0"] for x in fixes)
          and next(t for t in d["threads"] if t["rid"] == "r1")["p"] == 9
          and fixes[0]["p0"] <= 9 < fixes[0]["p1"])
    six = next(t for t in d["threads"] if t["rid"] == "r6")
    check("a reply naming the commit and the file says where the thread was fixed",
          six.get("fixedIn") == {"r": 0, "files": ["notes.md"]} and "_replies" not in six)
    check("a round with no transcript here does not say what it read, and a stopped one read nothing",
          [r["seen"] for r in d["rounds"]] == [None, None, []])
    out_by = {t["rid"]: t["outcome"] for t in d["threads"] if t["rid"] != "r6"}
    check("thread outcomes: fixed, declined, left to the person (a night's too), reversal, open",
          out_by == {"r1": "fixed", "r2": "declined", "r3": "yours", "r4": "reversal", "r5": "open", "r7": "reversal", "r8": "reversal"})
    flags = {t["rid"]: (t["resolved"], t["left"]) for t in d["threads"]}
    check("threads carry whether they are resolved and whether a reply left them",
          (flags["r2"], flags["r4"], flags["r7"], flags["r8"]) == ((True, True), (False, False), (True, False), (True, False)))
    check("a reversal's reply naming a commit takes no fix of it",
          not any(h["thread"] == "r8" for h in d["hunks"]))
    by = {t["rid"]: t for t in d["threads"]}
    check("a thread with no commit falls in the round of its time", by["r5"]["r"] == 2
          and by["r5"]["by"] == "person")
    asks = [h for h in d["hands"] if h["kind"] == "question"]
    check("the question answered: recommended, its wait and its thread",
          len(asks) == 1 and asks[0]["rec"] is True and asks[0]["waited"] == 8
          and asks[0]["path"] == "app.py" and asks[0]["line"] == 30 and asks[0]["r"] == 0)
    said = [h for h in d["hands"] if h["kind"] == "sclaude"]
    check("sclaude's answer from the history, the one before the review left out",
          len(said) == 1 and said[0]["waited"] == 12)
    check("a person's thread is their hand", any(h["kind"] == "thread" and h["rid"] == "r5" for h in d["hands"]))

    # A pass stopped on a head of its own is a round, stopped; a recorded
    # pass on that head after it makes it a round like any other.
    sys.path.insert(0, os.path.dirname(MAP))
    import review_map  # noqa: E402
    with open(os.path.join(tree, JOURNAL)) as fh:
        kept = fh.read()
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "head": first, "pr": "7"},
                    {"at": "2026-01-01T11:00:00+00:00", "head": second, "pr": "7", "spent": True, "session": "x"}):
            fh.write(json.dumps(row) + "\n")
    got = review_map.rounds_of(tree, "7")
    check("a pass stopped on a head of its own is a stopped round, its session apart",
          [(r["head"], r["stopped"], r["spent"]) for r in got] == [(first, False, []), (second, True, ["x"])])
    with open(os.path.join(tree, JOURNAL), "a") as fh:
        fh.write(json.dumps({"at": "2026-01-01T11:30:00+00:00", "head": second, "pr": "7", "new": 2}) + "\n")
    check("a recorded pass after it makes the round a round", [r["stopped"] for r in review_map.rounds_of(tree, "7")] == [False, False])
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        fh.write(kept)
    # main merged in after the last round: its files are no fix.
    git(tree, "checkout", "-qb", "side", first)
    with open(os.path.join(tree, "main.py"), "w") as fh:
        fh.write("m = 1\n")
    git(tree, "add", "main.py")
    git(tree, "commit", "-qm", "on main")
    git(tree, "checkout", "-q", "-")
    git(tree, "merge", "-q", "--no-edit", "side")
    out = subprocess.run([sys.executable, MAP, tree], capture_output=True, text=True, env=env)
    d = json.loads(out.stdout)
    check("a merge between rounds brings no fix and no column",
          "main.py" not in [f["path"] for f in d["files"]] and all(x["path"] != "main.py" for x in d["hunks"]))

    # A thread posted on a commit between round heads, carried to the head.
    sys.path.insert(0, os.path.dirname(MAP))
    import review_map  # noqa: E402
    lines = open(os.path.join(tree, "app.py")).read().splitlines()
    lines[0:0] = ["top%d = 0" % i for i in range(5)]
    with open(os.path.join(tree, "app.py"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    git(tree, "commit", "-qam", "five lines on top")
    later = git(tree, "rev-parse", "HEAD")
    check("a line of a later commit carried back to a round head",
          review_map.shifted(tree, later, second, "app.py", 20, {}) == 15
          and review_map.shifted(tree, later, second, "app.py", 3, {}) == 1)
    with open(os.path.join(tree, "app.py"), "a") as fh:
        fh.write("asked1 = 1\nasked2 = 2\n")
    git(tree, "commit", "-qam", "feat: what the person asked for")
    with open(os.path.join(tree, "app.py"), "a") as fh:
        fh.write("fixed1 = 1\n")
    git(tree, "commit", "-qam", "fix: a finding")
    with open(os.path.join(tree, "app.py"), "a") as fh:
        fh.write("asked3 = 3\n")
    git(tree, "commit", "-qam", "test: more\n\nRequirement: the person said so")
    got = review_map.asked_lines(tree, later, git(tree, "rev-parse", "HEAD"))
    n = len(lines)
    check("lines of a feat commit or one with a Requirement are the person's, a fix's are not",
          got == {"app.py": {n + 1, n + 2, n + 4}})
    check("a path named is not a longer path ending in it",
          review_map.named("lib/x.js", "Read src/lib/x.js") is False
          and review_map.named("lib/x.js", '{"file_path": "lib/x.js"}') is True)
    # A round's pass that opened a file by its absolute path read it.
    sess = os.path.join(folder, "p1.jsonl")
    with open(sess, "w") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": os.path.join(tree, "notes.md")}}]}}) + "\n")
    old_home = claude_usage.ROOT
    claude_usage.ROOT = os.path.join(home, ".claude", "projects")
    check("a file read by its absolute path, all of it, was read whole",
          review_map.seen_files(tree, ["p1"], ["app.py", "notes.md"], {"notes.md": 40}) == {"notes.md": "whole"})
    check("one longer than a Read gives was read in part",
          review_map.seen_files(tree, ["p1"], ["app.py", "notes.md"], {"notes.md": 4000}) == {"notes.md": "part"})
    with open(sess, "a") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r2",
             "content": "   394\tdiff --git a/app.py b/app.py\n   395\tindex 1..2"}]}}) + "\n")
    with open(sess, "a") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r4", "name": "Bash",
             "input": {"command": "git diff --stat main -- other.py", "description": "check other.py"}}]}}) + "\n")
    check("a command naming git diff without showing one is a part looked at",
          review_map.seen_files(tree, ["p1"], ["other.py"], {}) == {"other.py": "part"})
    check("a diff a Read showed, its lines numbered, counts as its changes seen",
          review_map.seen_files(tree, ["p1"], ["app.py", "notes.md"], {"notes.md": 40}) == {"app.py": "diff", "notes.md": "whole"})
    with open(sess, "a") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "r3", "name": "Read",
             "input": {"file_path": os.path.join(tree, "app.py"), "offset": 10, "limit": 5}}]}}) + "\n")
    check("a slice read after the diff keeps the most seen",
          review_map.seen_files(tree, ["p1"], ["app.py"], {})["app.py"] == "diff")
    claude_usage.ROOT = old_home
    # The names the map reads are its owners'.
    check("review-reversals is reversals_file's name",
          review_map.REVERSALS.endswith("/review-reversals")
          and 'echo "$1/' + review_map.REVERSALS + '"' in open(os.path.join(
              ROOT, "sclaude", "lib", "review", "review_round.sh")).read())
    import process_history  # noqa: E402
    check("the history is process_history's", review_map.HISTORY.endswith("/" + process_history.HISTORY_FILE))

    # Two blocks on one head: block 2's first pass is its own round.
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "head": first, "pr": "7", "block": 1},
                    {"at": "2026-01-01T10:05:00+00:00", "head": first, "pr": "7", "block": 2}):
            fh.write(json.dumps(row) + "\n")
    check("a block's first pass on the head the last block left is a round of its own",
          [r["block"] for r in review_map.rounds_of(tree, "7")] == [1, 2])
    rounds = review_map.rounds_of(tree, "7")
    # The map's rounds are the report's rows, numbered alike.
    check("the report's runs split where the block changes, as the map's rounds do",
          [r["block"] for r in review_report.journal_runs(os.path.join(tree, JOURNAL))] == [1, 2])
    check("each round carries the report's numbers", [(r["seq"], r["bseq"]) for r in rounds] == [(1, 1), (2, 1)])
    # The seams after the last block: the journal names them by their place,
    # the blocks' count plus one; the report and the map call them seams.
    state_path = os.path.join(tree, ".sclaude", "local", "feature", "state.json")
    state_before = open(state_path).read() if os.path.exists(state_path) else None
    journal_before = open(os.path.join(tree, JOURNAL)).read()
    with open(state_path, "w") as fh:
        json.dump({"blocks": {"total": 3, "current": 3}}, fh)
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "head": first, "pr": "7", "block": "1"},
                    {"at": "2026-01-01T10:05:00+00:00", "head": first, "pr": "7", "block": "2a"},
                    {"at": "2026-01-01T10:10:00+00:00", "head": first, "pr": "7", "block": "3"}):
            fh.write(json.dumps(row) + "\n")
    check("the pass over the seams is named seams, in the report and on the map alike",
          [r["block"] for r in review_report.journal_runs(os.path.join(tree, JOURNAL))] == ["1", "2a", "seams"]
          and [(r["block"], r["bseq"]) for r in review_map.rounds_of(tree, "7")][-1] == ("seams", 1))
    _js = open(os.path.join(ROOT, "sclaude", "lib", "flow", "process_review.js")).read()
    _summary = _js[_js.index("function summary("):_js.index("function draw()")]
    check("the header counts the review's fixes as the icicles draw them: a stopped pass's apart",
          "own.filter((x) => !stopped(x))" in _summary and "after a stopped pass" in _summary
          and "!(d.rounds[x.r] || {}).stopped" in _js)
    check("the map names the seams' rounds as the report does",
          "r.block === '" + review_report.SEAMS + "'" in open(os.path.join(
              ROOT, "sclaude", "lib", "flow", "process_review.js")).read())
    if state_before is None:
        os.remove(state_path)
    else:
        with open(state_path, "w") as fh:
            fh.write(state_before)
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        fh.write(journal_before)
    # A GitHub run on another head, written after the local passes but begun
    # between them: both sides put it in its place in time.
    with open(os.path.join(tree, JOURNAL), "a") as fh:
        fh.write(json.dumps({"at": "2026-01-01T10:02:00+00:00", "head": second, "pr": "7", "source": "github", "run": 5}) + "\n")
    check("a run written late takes its place in time, in the report and on the map alike",
          [(r["head"], r["seq"]) for r in review_map.rounds_of(tree, "7")] == [(first, 1), (second, 2), (first, 3)]
          and [r["head"] for r in review_report.journal_runs(os.path.join(tree, JOURNAL))] == [first, second, first])
    # A capped pass and the one that goes on with its range are one run,
    # though a GitHub run written later began between them.
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "base": "b", "head": first, "pr": "7", "more": True},
                    {"at": "2026-01-01T10:06:00+00:00", "base": "b", "head": first, "pr": "7"},
                    {"at": "2026-01-01T10:03:00+00:00", "head": second, "pr": "7", "source": "github", "run": 5}):
            fh.write(json.dumps(row) + "\n")
    check("one review's passes stay one run, a run written late between them in time",
          [r["head"] for r in review_report.journal_runs(os.path.join(tree, JOURNAL))] == [first, second])
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "head": first, "pr": "7", "block": 1},
                    {"at": "2026-01-01T10:05:00+00:00", "head": first, "pr": "7", "block": 2},
                    {"at": "2026-01-01T10:02:00+00:00", "head": second, "pr": "7", "source": "github", "run": 5}):
            fh.write(json.dumps(row) + "\n")
    # A round on a head gone from the tree is not drawn and keeps its number.
    with open(os.path.join(tree, JOURNAL), "a") as fh:
        fh.write(json.dumps({"at": "2026-01-01T10:01:00+00:00", "head": "0" * 40, "pr": "7", "block": 1}) + "\n")
    check("a head gone from the tree keeps its number taken",
          [(r["block"], r["seq"], r["bseq"]) for r in review_map.rounds_of(tree, "7")] == [(1, 1, 1), (None, 3, None), (2, 4, 1)])
    with open(os.path.join(tree, JOURNAL), "w") as fh:
        for row in ({"at": "2026-01-01T10:00:00+00:00", "head": first, "pr": "7", "block": 1},
                    {"at": "2026-01-01T10:05:00+00:00", "head": first, "pr": "7", "block": 2}):
            fh.write(json.dumps(row) + "\n")
    rounds = review_map.rounds_of(tree, "7")
    got = review_map.threads_of(tree, [thread(9, "app.py", 3, first, "2026-01-01T10:02:00Z"),
                                       thread(10, "app.py", 3, first, "2026-01-01T10:07:00Z")], rounds)
    check("a thread on a head two blocks share is the round of its time", [t["r"] for t in got] == [0, 1])
    for at in ("09:00", "10:10"):
        with open(os.path.join(tree, JOURNAL), "w") as fh:
            for row in ({"at": "2026-01-01T%s:00+00:00" % at, "head": first, "pr": "7", "source": "github"},
                        {"at": "2026-01-01T10:05:00+00:00", "head": first, "pr": "7", "block": 1, "session": "s1"},
                        {"at": "2026-01-01T10:07:00+00:00", "head": first, "pr": "7", "block": 2, "session": "s2"}):
                fh.write(json.dumps(row) + "\n")
        got = review_map.rounds_of(tree, "7")
        check("a GitHub run on a head makes every round on it GitHub's, whenever it ran (%s)" % at,
              [(r["block"], r["source"]) for r in got] == [(1, "github"), (2, "github")])

    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    git(empty, "init", "-q")
    out = subprocess.run([sys.executable, MAP, empty], capture_output=True, text=True, env=env)
    check("a tree with no review: no rounds", out.returncode == 0 and json.loads(out.stdout)["rounds"] == [])

# One problem's line of descent (review_map.py's project blame and lineage),
# on rounds made up for it: no git needed.
import review_map  # noqa: E402

rounds = [{"lines": {"f": 10}}, {"lines": {"f": 11}}]
a = {"i": 0, "r": 0, "path": "f", "x": 5, "n": 2, "ox": 5, "on": 1, "add": 2, "del": 1}
b = {"i": 1, "r": 1, "path": "f", "x": 5, "n": 1, "ox": 5, "on": 1, "add": 1, "del": 1}
c = {"i": 2, "r": 1, "path": "f", "x": 11, "n": 1, "ox": 10, "on": 0, "add": 1, "del": 0}
on_a = {"path": "f", "r": 1, "line": 6}
on_dev = {"path": "f", "r": 1, "line": 9}
review_map.project(["f"], rounds, [a, b, c], [on_a, on_dev], {"files": {}}, {"f": 12})
check("blame on the axis: a fix rewriting another's lines grows from it, one writing among the development's from none",
      b["_blame"] == [0] and a["_blame"] == [] and c["_blame"] == [])
check("blame on the axis: a thread knows the fix that wrote its line", on_a.get("_of") == 0 and "_of" not in on_dev)

asked = {"i": 0, "r": 0, "path": "f", "x": 5, "n": 2, "ox": 5, "on": 1, "add": 2, "del": 1, "asked": True}
later = {"i": 1, "r": 1, "path": "f", "x": 5, "n": 1, "ox": 5, "on": 1, "add": 1, "del": 1}
on_asked = {"path": "f", "r": 1, "line": 6}
review_map.project(["f"], [{"lines": {"f": 10}}, {"lines": {"f": 11}}], [asked, later], [on_asked], {"files": {}}, {"f": 11})
check("the lines the person asked for are the development's: no fix wrote them",
      later["_blame"] == [] and "_of" not in on_asked)


# "Fixed in <sha>" in the thread's own file credits only what that commit
# changed: a deletion too, and even after a later commit of the round
# edited the same spot — not the round's other work in the file.
with tempfile.TemporaryDirectory() as tmp2:
    t2 = os.path.join(tmp2, "t")
    os.makedirs(t2)
    git(t2, "init", "-q")
    git(t2, "config", "user.email", "t@t")
    git(t2, "config", "user.name", "t")
    lines = ["l%d" % i for i in range(1, 61)]
    def put(ls, msg):
        with open(os.path.join(t2, "f"), "w") as fh:
            fh.write("\n".join(ls) + "\n")
        git(t2, "add", "f")
        git(t2, "commit", "-qm", msg)
        return git(t2, "rev-parse", "HEAD")
    head = put(lines, "base")
    lines = lines[:9] + lines[12:]           # A: delete l10..l12
    a_sha = put(lines, "A")
    lines[8] = "l9 edited"                   # B: edit beside A's deletion
    lines[49] = "far away"                   # and far from it
    end = put(lines, "B")
    fx = review_map.hunks(t2, head, end)
    for h in fx:
        h.update({"r": 0, "thread": "", "outcome": "side", "via": ""})
    th = [{"rid": "r1", "path": "f", "outcome": "fixed", "_replies": ["Fixed in %s: dropped." % a_sha[:7]]}]
    review_map.replied(t2, [{"head": head}], [end], th, fx)
    got = sorted((h["ox"], h["thread"]) for h in fx)
    check("an own-file reply credits the commit's own change, a deletion or one edited after, not the round's other work (%s)" % got,
          [t for _, t in got] == ["r1", ""] and "fixedIn" not in th[0])


def citing():
    """A reply naming an earlier thread, as review.md asks ("as on r<id>"),
    or by its link, links them; one naming itself or a thread not in the
    pull request does not."""
    import review_map  # noqa: E402
    th = [{"rid": "r1234567", "_replies": []},
          {"rid": "r2345678", "_replies": ["Left as it is: as on r1234567, the cap stays."]},
          {"rid": "r3456789", "_replies": ["See https://github.com/o/r/pull/7#discussion_r2345678 and r9999999, r3456789"]}]
    review_map.cites(th)
    check("a reply citing an earlier thread links it, by `as on r<id>` or its link (%s)" % [t.get("cites") for t in th],
          "cites" not in th[0] and th[1]["cites"] == ["r1234567"] and th[2]["cites"] == ["r2345678"])


def conversing():
    """A finding the review put in the conversation (local_review.py's post,
    its file not in the diff) is read back as a thread on its file and line,
    in the round that posted it; a later comment leaving it as it is and
    naming its place declines it; anything else in the conversation is not
    a finding."""
    import review_map  # noqa: E402
    from local_review import FROM_LOCAL, NOT_IN_DIFF  # noqa: E402
    body = ("`lib/a.py:12` " + NOT_IN_DIFF + " — (nit) **The guard is gone**\n\nbody\n\n" + FROM_LOCAL) % "abc1234"
    cs = [{"id": 1, "body": "a person's word", "created_at": "2026-01-01T10:00:00Z", "user": {"type": "User"}},
          {"id": 2, "body": body, "html_url": "u2", "created_at": "2026-01-01T11:00:00Z", "user": {"type": "User"}},
          {"id": 3, "body": body.replace("12", "30"), "html_url": "u3", "created_at": "2026-01-01T12:30:00Z", "user": {"type": "User"}},
          {"id": 4, "body": "Left as it is: `lib/a.py:30` stays.", "created_at": "2026-01-01T13:00:00Z", "user": {"type": "User"}}]
    rounds = [{"t": review_map.ts("2026-01-01T10:30:00Z")}, {"t": review_map.ts("2026-01-01T12:00:00Z")}]
    got = review_map.conversation_findings(rounds, cs)
    check("a finding in the conversation is a thread on its file and line, in its round, declined when left (%s)"
          % [(t["rid"], t["r"], t["line"], t["outcome"]) for t in got],
          [(t["rid"], t["r"], t["path"], t["line"], t["outcome"], t["title"], t["conv"]) for t in got]
          == [("c2", 0, "lib/a.py", 12, "open", "The guard is gone", True), ("c3", 1, "lib/a.py", 30, "declined", "The guard is gone", True)])
    # The review on GitHub, posting findings in an ordinary comment: the
    # Claude app's comments, a row with no file; nobody else's.
    app = [{"id": 5, "body": "Two more findings, outside the diff", "html_url": "u5", "created_at": "2026-01-01T12:10:00Z",
            "user": {"type": "Bot", "login": "claude[bot]"}},
           {"id": 6, "body": "deployed", "created_at": "2026-01-01T12:20:00Z", "user": {"type": "Bot", "login": "vercel[bot]"}}]
    loose = review_map.loose_findings(rounds, cs + app)
    check("the review's comments of findings not on a line are read by round, no one else's (%s)" % loose,
          [(x["id"], x["r"]) for x in loose] == [(5, 1)])


def polishing():
    """The polish round is the last round that read the head sclaude
    recorded when it owed the polish; none without the record, nor when the
    polish was owed and dropped (neither taken nor under way)."""
    import review_map  # noqa: E402
    rounds = [{"head": "a"}, {"head": "b"}, {"head": "b"}, {"head": "c"}]
    review_map.polish_round({}, rounds)
    unmarked = [r.get("polish") for r in rounds]
    review_map.polish_round({"polish_head": "b"}, rounds)
    dropped = [r.get("polish") for r in rounds]
    review_map.polish_round({"polish_head": "b", "step": "done", "steps": {"review": {"polish": "due"}}}, rounds)
    dropped += [r.get("polish") for r in rounds]
    review_map.polish_round({"polish_head": "b", "step": "review", "steps": {"review": {"polish": "due"}}}, rounds)
    going = [r.get("polish") for r in rounds]
    for r in rounds:
        r.pop("polish", None)
    review_map.polish_round({"polish_head": "b", "polished": True}, rounds)
    check("the polish round is the last that read the recorded head, none unrecorded (%s)" % [r.get("polish") for r in rounds],
          unmarked == [None] * 4 and dropped == [None] * 8 and going == [None, None, True, None]
          and [r.get("polish") for r in rounds] == [None, None, True, None])
    # The map's git reads take a commit's non-UTF-8 text.
    g = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q", g], check=True)
        with open(os.path.join(g, "a.txt"), "wb") as fh:
            fh.write(b"caf\xe9\n")
        subprocess.run(["git", "-C", g, "-c", "user.name=t", "-c", "user.email=t@t", "add", "."], check=True)
        subprocess.run(["git", "-C", g, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "latin"], check=True)
        check("the map reads a commit with non-UTF-8 text", "caf" in (review_map.git(g, "show", "HEAD") or ""))
    finally:
        shutil.rmtree(g, ignore_errors=True)


def made(n, seen=None):
    return [{"stopped": False, "more": False, "seen": seen} for _ in range(n)]


def fix(i, r, thread="", blame=()):
    return {"i": i, "r": r, "path": "f", "thread": thread, "_blame": list(blame)}


def finding(rid, r, of=None, outcome="fixed"):
    return {"rid": rid, "r": r, "path": "f", "outcome": outcome, "left": False, "resolved": outcome == "fixed", "_of": of}


# Round 0 finds t1 and fixes it; round 1 reads the fix and finds nothing:
# closed. Round 2's fix rewriting those lines with no thread is new; a
# thread there in round 3 is a check that missed, and its fix goes on.
fx = [fix(0, 0, "t1"), fix(1, 2, blame=[0]), fix(2, 3, "t2")]
th = [finding("t1", 0), finding("t2", 3, of=0)]
review_map.lineage(made(4), fx, th)
check("a round that read a fixed chain and found nothing closes it: a fix there after is new",
      fx[1]["from"] == [])
check("a thread on the closed chain's own lines was missed by the round that closed it, and its fix goes on",
      th[1]["missed"] == 1 and fx[2]["from"] == [0] and th[1]["of"] == 0 and "missed" not in th[0])

# The closing round's own fixing landing on the chain keeps it going.
fx = [fix(0, 0, "t1"), fix(1, 1, blame=[0])]
review_map.lineage(made(2), fx, [finding("t1", 0)])
check("a fix of the round that read the chain clean, landing on it, keeps it going", fx[1]["from"] == [0])

# A declined thread on a closed chain's lines was no problem: no mark.
th = [finding("t1", 0), finding("t2", 2, of=0, outcome="declined")]
review_map.lineage(made(3), [fix(0, 0, "t1")], th)
check("a declined thread on a closed chain is no check that missed", "missed" not in th[1])

# A round that never opened the file closes nothing: the fix after it goes on.
fx = [fix(0, 0, "t1"), fix(1, 1, blame=[0])]
review_map.lineage(made(2, seen=[]), fx, [finding("t1", 0)])
check("a round that did not open the file closes nothing", fx[1]["from"] == [0])

# An open thread holds the chain open: the next fix there goes on.
fx = [fix(0, 0, "t1"), fix(1, 2, blame=[0])]
review_map.lineage(made(3), fx, [finding("t1", 0, outcome="open")])
check("a chain with a thread still open does not close", fx[1]["from"] == [0])

# A round that stopped at its cap said not all it found: no close.
rs = made(2)
rs[1]["more"] = True
fx = [fix(0, 0, "t1"), fix(1, 1, blame=[0])]
review_map.lineage(rs, fx, [finding("t1", 0)])
check("a round cut short at its cap closes nothing", fx[1]["from"] == [0])

# Code the review wrote answering no thread, closed: a thread there later is
# new, not a check that missed.
fx = [fix(0, 0), fix(1, 3, "t9")]
th = [finding("t9", 3, of=0)]
review_map.lineage(made(4), fx, th)
check("a closed chain that fixed no thread misses none: the thread there starts anew",
      "missed" not in th[0] and th[0]["of"] is None and fx[1]["from"] == [])

# A chain whose file its own round's fixes removed is read by nobody: the
# next round closes it without opening the file, once its threads settled.
rs = made(3, seen=[])
for r in rs[1:]:
    r["absent"] = ["f"]
fx = [fix(0, 0, "t1"), fix(1, 2, blame=[0])]
review_map.lineage(rs, fx, [finding("t1", 0)])
check("a chain whose file was removed closes without a reading", fx[1]["from"] == [])

# A removed file keeps its path, and code moved to another file in the same
# round is told by its lines: both sides know it.
with tempfile.TemporaryDirectory() as tmp3:
    t3 = os.path.join(tmp3, "t")
    os.makedirs(t3)
    git(t3, "init", "-q")
    git(t3, "config", "user.email", "t@t")
    git(t3, "config", "user.name", "t")
    body = ["select value_%d from things where id = %d;" % (i, i) for i in range(8)]
    with open(os.path.join(t3, "old.sql"), "w") as fh:
        fh.write("\n".join(body) + "\n")
    with open(os.path.join(t3, "new.sql"), "w") as fh:
        fh.write("-- head\n")
    git(t3, "add", ".")
    git(t3, "commit", "-qm", "base")
    base = git(t3, "rev-parse", "HEAD")
    os.remove(os.path.join(t3, "old.sql"))
    with open(os.path.join(t3, "new.sql"), "a") as fh:
        fh.write("\n".join(body) + "\nend;\n")
    git(t3, "add", "-A")
    git(t3, "commit", "-qm", "fold")
    end = git(t3, "rev-parse", "HEAD")
    hs = review_map.hunks(t3, base, end, texts=True)
    old = [h for h in hs if h["path"] == "old.sql"]
    check("a removed file keeps its path: its hunk removes it whole (%s)" % old,
          len(old) == 1 and old[0]["del"] == 8 and old[0]["n"] == 0 and old[0]["x"] == 0)
    review_map.moves(hs)
    new = [h for h in hs if h["path"] == "new.sql"]
    check("code moved between files in one round is known on both sides",
          new and new[0].get("_moved_from") == old and old[0].get("_moved_to") == new and old[0].get("_moved_out")
          and "_plus" not in new[0] and "_minus" not in old[0])
    present = review_map.absent_files(t3, end, ["old.sql", "new.sql"])
    check("the files a round no longer has are listed", present == ["old.sql"])
    check("a thread's line in a file removed after it stays as it was",
          review_map.shifted(t3, base, end, "old.sql", 5, {}) == 5)

    # A removed SQL comment reads `--- …` inside a hunk: still a line, not a header.
    with open(os.path.join(t3, "new.sql")) as fh:
        ls = fh.read().splitlines()
    with open(os.path.join(t3, "new.sql"), "w") as fh:
        fh.write("\n".join(["-- note"] + ls) + "\n")
    git(t3, "commit", "-qam", "note")
    noted = git(t3, "rev-parse", "HEAD")
    with open(os.path.join(t3, "new.sql"), "w") as fh:
        fh.write("\n".join(ls) + "\n")
    git(t3, "commit", "-qam", "drop note")
    hs = review_map.hunks(t3, noted, git(t3, "rev-parse", "HEAD"))
    check("a removed `-- note` inside a hunk counts as a removed line (%s)" % hs,
          len(hs) == 1 and hs[0]["path"] == "new.sql" and hs[0]["del"] == 1)

# What is left of the development: blame on the end, by who wrote each line.
with tempfile.TemporaryDirectory() as tmp4:
    t4 = os.path.join(tmp4, "t")
    os.makedirs(t4)
    git(t4, "init", "-q")
    git(t4, "config", "user.email", "t@t")
    git(t4, "config", "user.name", "t")
    def wrote(ls, msg):
        with open(os.path.join(t4, "f.py"), "w") as fh:
            fh.write("\n".join(ls) + "\n")
        git(t4, "add", "f.py")
        git(t4, "commit", "-qm", msg)
        return git(t4, "rev-parse", "HEAD")
    base = wrote(["main_%d = 0" % i for i in range(3)], "main")
    first = wrote(["main_%d = 0" % i for i in range(3)] + ["dev_%d = 1" % i for i in range(4)], "dev")
    end = wrote(["main_%d = 0" % i for i in range(3)] + ["dev_0 = 1", "dev_1 = 1", "fix_0 = 2"], "fix")
    check("blame counts the development's lines left, the review's and main's",
          review_map.alive(t4, base, first, end, ["f.py"]) == {"f.py": [2, 1, 3]})
    # Main moves on after the first round and a sync merges it in: its new
    # line is main's, not the review's.
    work = git(t4, "rev-parse", "--abbrev-ref", "HEAD")
    git(t4, "checkout", "-qb", "trunk", base)
    wrote(["main_0 = 9", "main_1 = 0", "main_2 = 0"], "main moves on")
    git(t4, "checkout", "-q", work)
    git(t4, "merge", "-q", "--no-edit", "trunk")
    synced = git(t4, "rev-parse", "HEAD")
    check("main merged in after the first round stays main's",
          review_map.alive(t4, base, first, synced, ["f.py"]) == {"f.py": [2, 1, 3]})
    # Renamed under a name git would quote: followed all the same.
    git(t4, "mv", "f.py", "ü.py")
    git(t4, "commit", "-qm", "rename")
    check("a block file renamed to a non-ASCII name is blamed under its new name",
          review_map.alive(t4, base, first, git(t4, "rev-parse", "HEAD"), ["f.py"]) == {"f.py": [2, 1, 3]})

# One removed line accounts for one added line, not for every copy of it.
line = "return value_from_cache;"
a = {"path": "a", "_minus": [line], "_plus": []}
b = {"path": "b", "_minus": [], "_plus": [line] * 4}
review_map.moves([a, b])
check("a line removed once does not make four copies of it moved", "_moved_from" not in b and "_moved_out" not in a)
three = ["first_moved_line();", "second_moved_line();", "third_moved_line();"]
a = {"path": "a", "_minus": list(three), "_plus": []}
bs = [{"path": p, "_minus": [], "_plus": list(three)} for p in ("b", "c", "d")]
review_map.moves([a] + bs)
six = ["moved_line_%d();" % i for i in range(6)]
by_chance = {"path": "a", "_minus": six[:2], "_plus": []}
source = {"path": "b", "_minus": list(six), "_plus": []}
target = {"path": "c", "_minus": [], "_plus": list(six)}
review_map.moves([by_chance, source, target])
check("a file sharing a line or two with the real source takes none of the move from it",
      target.get("_moved_from") == [source] and source.get("_moved_out") and "_moved_to" not in by_chance)
once = {"path": "x", "_minus": ["self.assertTrue(result_ok)"], "_plus": []}
source = {"path": "b", "_minus": list(six), "_plus": []}
target = {"path": "c", "_minus": [], "_plus": list(six) + ["self.assertTrue(result_ok)"] * 3}
review_map.moves([once, source, target])
check("a line removed once and added three times is no source of a move",
      target.get("_moved_from") == [source] and "_moved_out" not in once)
p_ = {"path": "p", "_minus": ["shared_a1();", "only_p_a2();", "only_p_a3();"], "_plus": []}
q_ = {"path": "q", "_minus": ["shared_a1();", "only_q_b1();", "only_q_b2();"], "_plus": []}
t_ = {"path": "t", "_minus": [], "_plus": ["shared_a1();", "only_p_a2();", "only_p_a3();", "only_q_b1();", "only_q_b2();", "new_n1();", "new_n2();"]}
review_map.moves([p_, q_, t_])
check("two sources sharing a line both keep the lines only they removed",
      t_.get("_moved_from") == [p_, q_] and p_.get("_moved_out") and q_.get("_moved_out"))
check("lines removed once move into one file of the round, not into each that has them",
      [("_moved_from" in x) for x in bs] == [True, False, False] and len(a.get("_moved_to", [])) == 1)

# The page carries the panel, its script, and the player's and the poll's hooks.
page = subprocess.run([sys.executable, os.path.join(ROOT, "sclaude", "lib", "flow", "process.py"),
                       "page", "x"], capture_output=True, text=True).stdout
check("the page has the panel and its chip", 'id="rv"' in page and 'id="rv-chip"' in page)
check("the panel asks the proxy's address", "/__sclaude/flow/review?f=" in page)
proxy = open(os.path.join(ROOT, "bin", "sclaude-proxy")).read()
check("the proxy serves that address with review_map.py",
      '"/__sclaude/flow/review"' in proxy and '"review_map.py"' in proxy)
check("the player tells the panel each place", page.count("'pl-step'") >= 3)
check("the poll tells the panel where the feature stands", "reviewMap.live(here)" in page)
check("a jump's two marks link each other, and a column goes on in the next file",
      "data-go" in page and "rvj-" in page and "rv-next" in page)
check("the page hangs a place from its lineage and marks a check that missed",
      "x.from" in page and "t.missed" in page and "rv-missed" in page)
check("the page ends an icicle at a removed file and follows moved code",
      "rv-gone" in page and "d.absentEnd" in page and "x.movedFrom" in page and "joutMoved" in page)
check("a place's hover links the same finding's fixes in other files",
      "function alsoIn" in page and "t-go" in page)
check("the page draws thin lines over every fill",
      "...thins" in page and "data-body" in page)

# A minor finding's mark is its first line, not its title.
import review_map  # noqa: E402
check("a minor finding is titled by its text, not its mark",
      review_map.headline("<!-- sclaude:minor nit -->\n\nUnused variable x in foo()") == "Unused variable x in foo()"
      and review_map.headline("<!-- sclaude:minor nit -->\n\n**Bold title**\n\nbody") == "Bold title")

citing()
conversing()
polishing()

sys.exit(1 if failures else 0)
