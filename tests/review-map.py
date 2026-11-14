#!/usr/bin/env python3
"""The review's map (sclaude/lib/review/review_map.py) read from a tree:
the rounds from the journal, the fixes between their heads, the threads and
how they ended, the person's answers from a transcript and the history, and
the page that draws it (process_review.js) wired into the process map."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "sclaude", "lib", "review", "review_map.py")
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib"))
import _path  # noqa: E402,F401
import claude_usage  # noqa: E402
import pr_context  # noqa: E402
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
        fh.write(url % 4 + "\tundoes the guard\n")

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
    check("two rounds: a head read twice is one; a missing commit, another PR and a pass stopped on a read head left out",
          [r["head"] for r in d["rounds"]] == [first, second] and not any(r["stopped"] for r in d["rounds"]))
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
    check("a round with no transcript here does not say what it read", all(r["seen"] is None for r in d["rounds"]))
    out_by = {t["rid"]: t["outcome"] for t in d["threads"] if t["rid"] != "r6"}
    check("thread outcomes: fixed, declined, night, reversal, open",
          out_by == {"r1": "fixed", "r2": "declined", "r3": "night", "r4": "reversal", "r5": "open"})
    by = {t["rid"]: t for t in d["threads"]}
    check("a thread with no commit falls in the round of its time", by["r5"]["r"] == 1
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
    check("a file read by its absolute path counts as opened",
          review_map.seen_files(tree, ["p1"], ["app.py", "notes.md"]) == ["notes.md"])
    with open(sess, "a") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r2",
             "content": "   394\tdiff --git a/app.py b/app.py\n   395\tindex 1..2"}]}}) + "\n")
    check("a diff a Read showed, its lines numbered, counts as opened",
          review_map.seen_files(tree, ["p1"], ["app.py", "notes.md"]) == ["app.py", "notes.md"])
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

sys.exit(1 if failures else 0)
