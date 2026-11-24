#!/usr/bin/env python3
#
# Where a project's review runs: `review` in .sclaude/config.json, and the
# review run on this machine when it says `local`.
#
# The review workflow in Actions bills its runner by the minute while it waits
# on the model, so a project may run the same /code-review here (`local`) or
# not at all (`off`). Guarded here:
#
#   * project_review_mode reads the key, and anything it does not know is
#     `github` — a typo must not switch off the review a project has;
#   * review_label_sync puts the `no-review` label on only when the review is
#     not GitHub's; the label is what makes the workflow skip itself;
#   * local_review keeps its findings where the workflow does, as threads on
#     the pull request: the first run reads the whole pull request and posts
#     its findings; a run on the same head runs nothing and reads the count
#     from GitHub; a later run reads only the new commits, is handed every
#     thread still open, resolves the ones it judges fixed with the
#     resolver's reply, and is told what the author declined. A thread left
#     open by an interrupted session stays open — nothing counts as fixed for
#     not being raised again. An answer with no count, or a head not pushed,
#     records nothing;
#   * the person's word that the search for findings is over: `s` during a
#     pass lets it be posted and sends no capped follow-up, `x` twice at the
#     terminal stops the pass with nothing of it posted or recorded, and
#     either way a later head is only checked against the open findings,
#     with nothing new posted;
#   * a finding GitHub took only on its file reaches the next run by the
#     line and the claim its body names;
#   * the step prompts render with the review's mode and without it.
#
# Run it with: python3 tests/local-review.py
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
PROMPTS = os.path.join(ROOT, "sclaude", "prompts")
sys.path.insert(0, LIB)
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import pr_context  # noqa: E402
import local_review  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def recorded(journal_text):
    """The journal's reviewed runs: a pass that ran and was not recorded is
    journaled as spent (for its cost), and is not one."""
    return "".join(line + "\n" for line in journal_text.splitlines()
                   if line.strip() and not json.loads(line).get("spent"))


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, check=False).stdout.strip()


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


# gh, standing in for GitHub: the pull request's review threads in a JSON
# file, the calls local_review.py makes, and a log of every call.
GH = r'''#!/usr/bin/env python3
import json, os, sys
world = os.environ["GH_WORLD"]
args = sys.argv[1:]
with open(world + ".log", "a") as fh:
    fh.write(" ".join(args) + "\n")
try:
    with open(world) as fh:
        data = json.load(fh)
except OSError:
    data = {"threads": [], "next": 1}
def save():
    with open(world, "w") as fh:
        json.dump(data, fh)
def field(name):
    for i, a in enumerate(args):
        if a in ("-f", "-F") and args[i + 1].startswith(name + "="):
            return args[i + 1][len(name) + 1:]
    return None
if args[:2] == ["api", "graphql"]:
    query = field("query") or ""
    if "addPullRequestReviewThreadReply" in query:
        for t in data["threads"]:
            if t["id"] == field("id"):
                t["comments"].append({"body": field("b"), "url": t["comments"][0]["url"] + "x"})
        save(); print("{}"); sys.exit(0)
    if "resolveReviewThread" in query:
        for t in data["threads"]:
            if t["id"] == field("id"):
                t["isResolved"] = True
        save(); print("{}"); sys.exit(0)
    nodes = [{"id": t["id"], "isResolved": t["isResolved"], "isOutdated": False,
              "path": t["path"], "line": t["line"], "originalLine": t["line"],
              "comments": {"nodes": t["comments"]}} for t in data["threads"]]
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": False}, "nodes": nodes}}}}}))
    sys.exit(0)
if args[:2] == ["api", "repos/{owner}/{repo}/actions/workflows"]:
    # What --jq leaves: the active ones under .github/workflows.
    print("11\tChecks\n12\tClaude Code Review")
    sys.exit(0)
if args[:1] == ["workflow"]:
    sys.exit(0)
if args[:2] == ["pr", "view"] and "headRefOid" in " ".join(args):
    import subprocess
    print(subprocess.run(["git", "rev-parse", "refs/remotes/origin/feature"],
                         capture_output=True, text=True).stdout.strip())
    sys.exit(0)
if args[:2] == ["pr", "comment"]:
    if "nowhere" in args[-1] and os.path.exists(world + ".down"):
        sys.exit(1)
    data.setdefault("conversation", []).append(args[-1])
    save(); sys.exit(0)
if args[:1] == ["api"] and args[1].endswith("/comments") and field("body"):
    path = field("path")
    # GitHub refuses a line outside the diff, or a file outside the pull
    # request, with a 422; "nowhere" while the world is down fails as a
    # network does, without one.
    if path == "nowhere" and os.path.exists(world + ".down"):
        sys.stderr.write("connection reset\n"); sys.exit(1)
    if path == "elsewhere" or (path == "fileonly" and field("line")):
        sys.stderr.write("HTTP 422: Validation Failed\n"); sys.exit(1)
    n = data["next"]; data["next"] += 1
    data["threads"].append({"id": "T%d" % n, "isResolved": False, "path": path,
                            "line": int(field("line")) if field("line") else None,
                            "comments": [{"body": field("body"),
                                          "url": "https://github.com/o/r/pull/7#discussion_r%d" % (100 + n)}]})
    save(); print("{}"); sys.exit(0)
sys.exit(0)
'''

tmp = tempfile.mkdtemp()
try:
    stubs = os.path.join(tmp, "bin")
    world = os.path.join(tmp, "world.json")
    calls = os.path.join(tmp, "claude.calls")
    write(os.path.join(stubs, "gh"), GH, 0o755)
    # claude: records its prompt (its argument, or stdin after -p), answers
    # with whatever the answer file holds.
    # With answers queued in answers/, one per call, oldest first.
    write(os.path.join(stubs, "claude"),
          '#!/bin/sh\ncase "$2" in -*) p="$(cat)" ;; *) p="$2" ;; esac\n'
          'printf "%%s\\n---\\n" "$p" >> "%s"\n'
          '[ -f "%s/during" ] && . "%s/during"\n'
          'q="%s/answers"; f=$(ls "$q" 2>/dev/null | head -n 1)\n'
          'if [ -n "$f" ]; then cat "$q/$f"; rm "$q/$f"; else cat "%s/answer"; fi\n'
          % (calls, tmp, tmp, tmp, tmp), 0o755)

    remote = os.path.join(tmp, "o", "r.git")
    os.makedirs(remote)
    git("init", "-q", "--bare", "-b", "main", cwd=remote)
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    git("remote", "add", "origin", remote, cwd=repo)
    write(os.path.join(repo, "a.txt"), "a\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "first", cwd=repo)
    git("push", "-q", "-u", "origin", "main", cwd=repo)
    base = git("rev-parse", "HEAD", cwd=repo)
    git("checkout", "-q", "-b", "feature", cwd=repo)
    write(os.path.join(repo, "a.txt"), "b\n")
    git("commit", "-qam", "change", cwd=repo)
    git("push", "-q", "-u", "origin", "feature", cwd=repo)
    head = git("rev-parse", "HEAD", cwd=repo)
    os.makedirs(os.path.join(repo, ".sclaude", "local", "feature"))
    config = os.path.join(repo, ".sclaude", "config.json")
    journal = os.path.join(repo, ".sclaude", "local", "feature", "review-rounds.jsonl")

    def run_bash(script, env_extra=None):
        body = "set -uo pipefail\n"
        body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""; SELF=sclaude\n'
        for name in ("core/io", "core/ui", "core/state", "core/steps", "core/project", "core/picker", "review/local_review"):
            body += 'source "%s/%s.sh"\n' % (LIB, name)
        body += 'LIB="%s"\nwarn() { echo "$*" >&2; }\ninfo() { echo "$*"; }\n' % LIB
        body += script
        env = dict(os.environ, PATH=stubs + os.pathsep + os.environ["PATH"], GH_WORLD=world,
                   **(env_extra or {}))
        out = subprocess.run(["bash", "-c", body], cwd=repo, capture_output=True,
                             text=True, timeout=60, env=env)
        return out.stdout, out.stderr, out.returncode

    def mode(value):
        write(config, json.dumps({} if value is None else {"review": value}))
        out, _, _ = run_bash('REPO=%s; project_review_mode' % repo)
        return out.strip()

    def gh_log():
        try:
            with open(world + ".log") as fh:
                return fh.read()
        except OSError:
            return ""
        finally:
            open(world + ".log", "w").close()

    # --- the mode -------------------------------------------------------------
    check("mode-absent", mode(None), "github")
    check("mode-local", mode("local"), "local")
    check("mode-off", mode("off"), "off")
    check("mode-github", mode("github"), "github")
    check("mode-typo-is-github", mode("locla"), "github")

    # --- the label ------------------------------------------------------------
    mode("github")
    run_bash('REPO=%s; review_label_sync %s 7' % (repo, repo))
    check("github-no-label", gh_log(), "")
    mode("off")
    run_bash('REPO=%s; review_label_sync %s 7' % (repo, repo))
    check_true("off-labels", "pr edit 7 --add-label no-review" in gh_log())
    run_bash('REPO=%s; review_label_sync %s null' % (repo, repo))
    check("no-pr-no-label", gh_log(), "")

    # --- Actions with the mode --------------------------------------------------
    #
    # `local` switches the repository's workflows off (they fail without
    # minutes and mail about it), `github` switches back on the ones it
    # switched off, `off` touches nothing.
    disabled = os.path.join(repo, ".sclaude", "local", "actions-disabled")
    gh_log()
    run_bash('review_actions_sync %s off' % repo)
    check("actions-off-mode-untouched", gh_log(), "")
    run_bash('review_actions_sync %s local' % repo)
    log = gh_log()
    check_true("actions-local-disables", "workflow disable 11" in log and "workflow disable 12" in log)
    check_true("actions-local-remembers", os.path.exists(disabled))
    run_bash('review_actions_sync %s github' % repo)
    log = gh_log()
    check_true("actions-github-enables-those", "workflow enable 11" in log and "workflow enable 12" in log)
    check("actions-github-forgets", os.path.exists(disabled), False)
    run_bash('review_actions_sync %s github' % repo)
    check("actions-github-nothing-to-enable", "workflow enable" in gh_log(), False)

    # --- the review -----------------------------------------------------------
    mode("local")

    # What the feature's topic is told, through the channel ask_feed writes.
    ask_dir = os.path.join(tmp, "ask")
    feed = os.path.join(ask_dir, "ask", "demo", "notes", "feed.tsv")

    # Every answer ends as the prompt asks, once the review is done; one
    # handed back before it is refused (an-unfinished-answer-is-refused).
    def review(answer):
        write(os.path.join(tmp, "answer"), answer + local_review.DONE + "\n")
        return run_bash('REPO=%s; local_review %s 7' % (repo, repo),
                        {"ASK_DIR": ask_dir, "ASK_SLUG": "demo"})

    def told():
        try:
            with open(feed) as fh:
                return [line.split("\t")[3].rstrip("\n") for line in fh]
        except OSError:
            return []
        finally:
            if os.path.exists(feed):
                os.unlink(feed)

    def prompts():
        try:
            with open(calls) as fh:
                return fh.read()
        except OSError:
            return ""
        finally:
            open(calls, "w").close()

    def threads():
        with open(world) as fh:
            return json.load(fh)["threads"]

    out, err, rc = review("### a.txt:1 — b is wrong\nWith a, b comes out.\n\n"
                          "### a.txt:1 — another\nAnd so on.\n\nFINDINGS: 2\n")
    check("first-count", (out.strip(), rc), ("2", 0))
    # The status line and the indented lines stay in the terminal; the topic
    # hears that the review started and how it ended.
    check("first-told", told(), ["🔍 Local review started: PR #7, round 1",
                                 "🔍 Local review finished: PR #7, round 1 · 2 open"])
    first = prompts()
    check_true("prompt-asks-the-end-line", local_review.DONE in first)
    check_true("prompt-forbids-waiting", "never end a turn to wait" in first)
    check_true("first-reads-whole-pr", "the whole pull request" in first
               and "git diff %s..%s" % (base, head) in first)
    check("first-posted", [t["comments"][0]["body"].splitlines()[0] for t in threads()],
          ["**b is wrong**", "**another**"])
    check_true("signed", all(pr_context.LOCAL_SIGNATURE in t["comments"][0]["body"]
                             for t in threads()))

    # The same head again: the count from GitHub, and no second run.
    out, _, rc = review("FINDINGS: 5\n")
    check("same-head-cached", (out.strip(), rc), ("2", 0))
    check("same-head-no-run", prompts(), "")

    # A session fixed one, declined the other on GitHub, and pushed: the next
    # run reads the new commit, is handed the open thread and told the
    # declined one, and resolves what it judges fixed.
    t = threads()
    with open(world) as fh:
        data = json.load(fh)
    data["threads"][1]["comments"].append({"body": "Left as it is, at the author's decision: keep it",
                                           "url": "u"})
    data["threads"][1]["isResolved"] = True
    with open(world, "w") as fh:
        json.dump(data, fh)
    write(os.path.join(repo, "a.txt"), "c\n")
    git("commit", "-qam", "fix", cwd=repo)
    git("push", "-q", cwd=repo)
    newer = git("rev-parse", "HEAD", cwd=repo)
    out, _, rc = review("RESOLVED: r101 — b now checked\n\nFINDINGS: 0\n")
    check("delta-count", (out.strip(), rc), ("0", 0))
    second = prompts()
    check_true("delta-reads-new-commits", "since the last review" in second
               and "git diff %s..%s" % (head, newer) in second)
    check_true("delta-handed-open", "r101 · a.txt:1 — **b is wrong**" in second)
    check_true("delta-told-declined", "keep it" in second)
    t = threads()
    check("resolved-thread", t[0]["isResolved"], True)
    check_true("resolver-reply", t[0]["comments"][-1]["body"].startswith(pr_context.RESOLVER_PREFIX)
               and pr_context.LOCAL_SIGNATURE in t[0]["comments"][-1]["body"])

    # An interrupted session: a commit that fixes nothing. The open thread
    # stays open, and so does the count.
    with open(world) as fh:
        data = json.load(fh)
    data["threads"][0]["isResolved"] = False
    with open(world, "w") as fh:
        json.dump(data, fh)
    write(os.path.join(repo, "a.txt"), "d\n")
    git("commit", "-qam", "half", cwd=repo)
    git("push", "-q", cwd=repo)
    out, _, rc = review("FINDINGS: 0\n")
    check("unfixed-stays-open", (out.strip(), rc), ("1", 0))
    prompts()

    # A finding GitHub will not take on its line goes on its file.
    write(os.path.join(repo, "a.txt"), "e\n")
    git("commit", "-qam", "more", cwd=repo)
    git("push", "-q", cwd=repo)
    out, _, rc = review("### fileonly:9 — on the file\nx\n\nFINDINGS: 1\n")
    check("file-level-count", (out.strip(), rc), ("2", 0))
    check("file-level-thread", threads()[-1]["path"], "fileonly")
    check_true("file-level-names-line",
               threads()[-1]["comments"][0]["body"].startswith("Line 9 (outside the diff)."))
    prompts()

    # A file the pull request does not change takes no review comment: the
    # finding goes to the conversation, and the run is recorded.
    write(os.path.join(repo, "a.txt"), "e2\n")
    git("commit", "-qam", "more2", cwd=repo)
    git("push", "-q", cwd=repo)
    open_before = sum(1 for t in threads() if not t["isResolved"])
    out, _, rc = review("### elsewhere:4 — a caller breaks\nx\n\nFINDINGS: 1\n")
    check("outside-pr-recorded", rc, 0)
    # It has no thread to count it, so this run counts it open: the step
    # must not close as if the review found nothing.
    check("outside-pr-counted-open", out.strip(), str(open_before + 1))
    with open(world) as fh:
        said = json.load(fh)["conversation"][-1]
    check_true("outside-pr-in-conversation", "`elsewhere:4` (not in this pull request's diff)" in said)
    check("outside-pr-not-signed", pr_context.signed_locally(said), False)
    # The thread on the file has no line of its own: the next run is handed
    # it by the line its body names and by its claim, not by that first line.
    check_true("file-level-handed-by-claim", "fileonly:9 — **on the file**" in prompts())
    # Step 4's snapshot reads the same line, open and resolved; a person's
    # comment that happens to open so is not the review's and names nothing.
    nodes = [{"path": t["path"], "line": t["line"], "originalLine": t["line"],
              "isResolved": t["isResolved"], "comments": {"nodes": t["comments"]}}
             for t in threads() if t["path"] == "fileonly"]
    still, gone = pr_context.open_threads(repo, 7, "o/r", nodes=nodes)
    check("snapshot-file-level-line", [t["line"] for t in still], [9])
    nodes[0]["isResolved"] = True
    check("snapshot-resolved-file-level-line",
          [t["line"] for t in pr_context.open_threads(repo, 7, "o/r", nodes=nodes)[1]], [9])
    check("person-names-no-line", pr_context.thread_line(
        {"comments": {"nodes": [{"body": "Line 4 (outside the diff).\n\nmine"}]}}), None)

    # Headings as models drift from the format are read all the same; a
    # count the headings do not add up to is refused, not half recorded.
    sys.path.insert(0, LIB)
    import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
    import local_review
    found, _, count = local_review.parse(
        "### `src/a.ts:12` — backticks\nx\n### src/b.ts:3-9 — a range\ny\n"
        "### src/c.ts:7 - a hyphen\nz\nFINDINGS: 3\n")
    check("headings-drift", [(f["path"], f["line"]) for f in found],
          [("src/a.ts", 12), ("src/b.ts", 3), ("src/c.ts", 7)])
    # The files a reviewer read in full (sreview's COVERED line) end the
    # finding above them and go into none.
    found, _, count = local_review.parse(
        "### src/a.ts:12 — one\nthe scenario\nCOVERED: src/a.ts, src/b.ts\nFINDINGS: 1\n")
    check("covered-not-in-a-finding", (found[0]["body"], count), ("the scenario", 1))
    write(os.path.join(repo, "a.txt"), "e3\n")
    git("commit", "-qam", "more3", cwd=repo)
    git("push", "-q", cwd=repo)
    with open(journal) as fh:
        before = fh.read()
    # A pass a model ran is a session sclaude named, and its row keeps the
    # name: the issue's summary lists it.
    named = json.loads(before.splitlines()[-1]).get("session") or ""
    check_true("pass-session-journaled",
               re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", named))
    _, _, rc = review("### a.txt:1 — one\nx\n\n## Something else\n\nFINDINGS: 2\n")
    check("count-mismatch-fails", rc, 1)
    with open(journal) as fh:
        check("count-mismatch-not-recorded", recorded(fh.read()), recorded(before))
    prompts()

    # A thread a person opened, and one the person keeps to resolve by hand,
    # are not the review's to judge: not handed to it, not resolved by it.
    with open(world) as fh:
        data = json.load(fh)
    data["threads"].append({"id": "TP", "isResolved": False, "path": "a.txt", "line": 1,
                            "comments": [{"body": "why this way?", "url":
                                          "https://github.com/o/r/pull/7#discussion_r900"}]})
    kept = data["threads"][0]["comments"][0]["url"]
    with open(world, "w") as fh:
        json.dump(data, fh)
    write(os.path.join(repo, ".sclaude", "local", "feature", "review-yours"), kept + "\tmine\n")
    out, _, rc = review("RESOLVED: r900 — answered\nRESOLVED: r101 — gone\n\nFINDINGS: 0\n")
    check("person-thread-rc", rc, 0)
    third = prompts()
    check_true("person-thread-not-handed", "r900" not in third and "r101 ·" not in third)
    check_true("kept-thread-told-declined", "(mine)" in third)
    t = {x["id"]: x for x in threads()}
    check("person-thread-not-resolved", t["TP"]["isResolved"], False)
    check("kept-thread-not-resolved", t["T1"]["isResolved"], False)
    os.remove(os.path.join(repo, ".sclaude", "local", "feature", "review-yours"))

    # Some findings posted, one refused: the run stands, the refused one
    # waits, counted open, and goes up on the next call.
    write(os.path.join(repo, "a.txt"), "e4\n")
    git("commit", "-qam", "more4", cwd=repo)
    git("push", "-q", cwd=repo)
    open(world + ".down", "w").close()
    open_before = sum(1 for t in threads() if not t["isResolved"])
    out, _, rc = review("### a.txt:1 — taken\nx\n\n### nowhere:2 — refused\ny\n\nFINDINGS: 2\n")
    check("partial-rc", rc, 0)
    check("partial-counts-waiting", out.strip(), str(open_before + 2))
    pending = os.path.join(repo, ".sclaude", "local", "feature", "local-review-unposted.json")
    check("partial-kept", os.path.exists(pending), True)
    # Waiting, it is not to be reported again by the next run.
    out_prompt = subprocess.run([sys.executable, os.path.join(LIB, "review", "local_review.py"), "prompt",
                                 repo, "7", "o/r", journal], cwd=repo, capture_output=True,
                                text=True, env=dict(os.environ, GH_WORLD=world,
                                                    PATH=stubs + os.pathsep + os.environ["PATH"])).stdout
    check_true("partial-told-waiting", "nowhere:2 — refused" in out_prompt)
    os.remove(world + ".down")
    out, _, rc = review("FINDINGS: 0\n")
    check("partial-posted-later", [t["path"] for t in threads()][-1:], ["nowhere"])
    check("partial-no-longer-waiting", os.path.exists(pending), False)
    # A post that timed out may have been taken: a finding whose thread is
    # there already is not posted a second time.
    write(pending, json.dumps([{"path": "nowhere", "line": 2, "title": "refused", "body": "y",
                                "head": git("rev-parse", "HEAD", cwd=repo)}]))
    before_n = len(threads())
    review("FINDINGS: 0\n")
    check("no-duplicate-thread", len(threads()), before_n)
    check("partial-cached-count", out.strip(), str(open_before + 2))
    prompts()

    # The severity /code-review gives a finding rides in its heading; a nit
    # or a pre-existing bug is posted with the minor mark, open work all the
    # same.
    found, _, _ = local_review.parse(
        "### a.ts:1 — [important] real\nx\n### b.ts:2 — [Nit] small\ny\n"
        "### c.ts:3 — [pre_existing] old\nz\n### d.ts:4 — untagged\nw\nFINDINGS: 4\n")
    check("severity-read", [(f["severity"], f["title"]) for f in found],
          [("important", "real"), ("nit", "small"), ("pre-existing", "old"), ("important", "untagged")])
    write(os.path.join(repo, "a.txt"), "e5\n")
    git("commit", "-qam", "more5", cwd=repo)
    git("push", "-q", cwd=repo)
    open_before = sum(1 for t in threads() if not t["isResolved"])
    out, _, rc = review("### a.txt:1 — [nit] a nit\nx\n\n### fileonly:9 — [pre-existing] older\ny\n\nFINDINGS: 2\n")
    check("minor-rc", rc, 0)
    check("minor-counted-open", out.strip(), str(open_before + 2))
    minor_threads = threads()[-2:]
    check("minor-marked", [pr_context.minor_of(t["comments"][0]["body"]) for t in minor_threads],
          ["nit", "pre-existing"])
    check("minor-headline", pr_context.headline(minor_threads[1]["comments"][0]["body"]), "**older**")
    check("minor-file-level-line", pr_context.outside_diff(minor_threads[1]["comments"][0]["body"]), 9)
    # They stay a review's own, for a later run to resolve.
    check("minor-checkable", all(pr_context.signed_locally(t["comments"][0]["body"]) for t in minor_threads), True)
    prompts()
    # The answer the stub falls back on, as the steps after this expect it.
    write(os.path.join(tmp, "answer"), "FINDINGS: 0\n" + local_review.DONE + "\n")

    # The journal dates a run by its start, as the workflow's runs are dated.
    with open(journal) as fh:
        last = json.loads(fh.read().splitlines()[-1])
    import datetime
    began = datetime.datetime.fromisoformat(last["at"])
    check_true("journal-dated-at-start",
               began <= datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(seconds=last["seconds"]) + datetime.timedelta(seconds=5))

    # A pass that posts the cap or more is followed by another over the same
    # range, told what was just posted, until one posts less — or the passes
    # run out.
    def queue(*answers):
        q = os.path.join(tmp, "answers")
        os.makedirs(q, exist_ok=True)
        for i, a in enumerate(answers):
            write(os.path.join(q, "%02d" % i), a)

    def batch(tag, n):
        return "".join("### a.txt:1 — %s %d\nx\n\n" % (tag, i) for i in range(n)) + "FINDINGS: %d\n" % n + local_review.DONE + "\n"

    for name, passes, answers, want_calls in (
            ("cap-reruns", "5", (batch("p1", 2), batch("p2", 2), batch("p3", 1)), 3),
            ("cap-passes-limit", "2", (batch("q1", 2), batch("q2", 2), batch("q3", 1)), 2)):
        write(os.path.join(repo, "a.txt"), name + "\n")
        git("commit", "-qam", name, cwd=repo)
        git("push", "-q", cwd=repo)
        shutil.rmtree(os.path.join(tmp, "answers"), ignore_errors=True)
        queue(*answers)
        posted_before = len(threads())
        out, err, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo),
                                {"LOCAL_REVIEW_CAP": "2", "LOCAL_REVIEW_PASSES": passes})
        sent = prompts()
        check(name + "-rc", rc, 0)
        check(name + "-passes", sent.count("---\n"), want_calls)
        check(name + "-posted", len(threads()) - posted_before, 5 if want_calls == 3 else 4)
        if want_calls == 3:
            # The second pass is told what the first just posted.
            check_true(name + "-told-first-pass", "p1 0" in sent.split("---\n")[1])
        else:
            check_true(name + "-warned", "stopping at 2 passes" in err)
    shutil.rmtree(os.path.join(tmp, "answers"), ignore_errors=True)

    # A capped pass whose follow-up was refused twice (run once more at once,
    # refused again): the review is not done — it fails, says why, in the
    # topic too, and journals the reason — and the next call reads the same
    # range again rather than nothing.
    write(os.path.join(repo, "a.txt"), "cut\n")
    git("commit", "-qam", "cut", cwd=repo)
    git("push", "-q", cwd=repo)
    prev = git("rev-parse", "HEAD~1", cwd=repo)
    cut = git("rev-parse", "HEAD", cwd=repo)
    queue(batch("c1", 2), "interrupted\n", "interrupted again\n")
    told()
    _, err, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo),
                          {"LOCAL_REVIEW_CAP": "2", "ASK_DIR": ask_dir, "ASK_SLUG": "demo"})
    prompts()
    check("cut-later-pass-refused-fails", rc, 1)
    check_true("cut-refusal-runs-once-more", "running it once more" in err)
    check_true("cut-refusal-says-why", "Pass 2 of the local review was refused twice" in err and "FINDINGS" in err)
    check_true("cut-refusal-in-topic", any("pass 2 refused twice" in line for line in told()))
    with open(journal) as fh:
        last_row = json.loads(fh.read().splitlines()[-1])
    check_true("cut-refusal-journaled", last_row.get("spent") and "FINDINGS" in (last_row.get("refused") or ""))
    _, _, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo), {"LOCAL_REVIEW_CAP": "2"})
    again = prompts()
    check("cut-not-cached", again.count("---\n"), 1)
    check_true("cut-same-range", "git diff %s..%s" % (prev, cut) in again)
    check_true("cut-told-first-pass", "c1 0" in again)
    shutil.rmtree(os.path.join(tmp, "answers"), ignore_errors=True)

    # Refused once, then answered: the pass run once more stands.
    write(os.path.join(repo, "a.txt"), "retry\n")
    git("commit", "-qam", "retry", cwd=repo)
    git("push", "-q", cwd=repo)
    queue("handed back early\n", batch("r1", 1))
    out, err, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo))
    check("refused-once-then-answered", rc, 0)
    check("refused-once-ran-twice", prompts().count("---\n"), 2)
    shutil.rmtree(os.path.join(tmp, "answers"), ignore_errors=True)

    # No count in the answer, or nothing GitHub would take: nothing recorded,
    # so the next run reviews the same head again.
    write(os.path.join(repo, "a.txt"), "f\n")
    git("commit", "-qam", "again", cwd=repo)
    git("push", "-q", cwd=repo)
    with open(journal) as fh:
        before = fh.read()
    prompts()
    _, _, rc = review("I could not finish.\n")
    check("no-count-fails", rc, 1)
    # The answer refused: run once more, and both answers kept for reading.
    check("no-count-ran-twice", prompts().count("---\n"), 2)
    with open(os.path.join(repo, ".sclaude", "local", "feature", "local-review-refused.md")) as fh:
        check("refused-answers-kept", fh.read().count("I could not finish."), 2)
    open(world + ".down", "w").close()
    _, _, rc = review("### nowhere:1 — lost\nx\n\nFINDINGS: 1\n")
    os.remove(world + ".down")
    check("nothing-posted-fails", rc, 1)
    # Refused by GitHub too: run once more, as every refusal is.
    check("github-refusal-run-again", prompts().count("---\n"), 2)
    with open(journal) as fh:
        check("failures-not-recorded", recorded(fh.read()), recorded(before))

    # Claude's usage limit as the answer: not refused, not run again at once;
    # journaled spent without a refused reason (the report's "Answers
    # refused" does not count it), the reset left for the gate, which waits
    # for it rather than asking (review_limit_wait).
    write(os.path.join(repo, "a.txt"), "limit\n")
    git("commit", "-qam", "limit", cwd=repo)
    git("push", "-q", cwd=repo)
    refused_md = os.path.join(repo, ".sclaude", "local", "feature", "local-review-refused.md")
    with open(refused_md) as fh:
        refused_before = fh.read()
    prompts()
    told()
    write(os.path.join(tmp, "answer"), "You've hit your weekly limit · resets 3am (Europe/Lisbon)\n")
    _, err, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo), {"ASK_DIR": ask_dir, "ASK_SLUG": "demo"})
    check("limit-fails", rc, 1)
    check("limit-not-run-again", prompts().count("---\n"), 1)
    check_true("limit-said", "Claude's usage limit — resets " in err and "refused" not in err)
    with open(journal) as fh:
        last_row = json.loads(fh.read().splitlines()[-1])
    check("limit-journaled-unrefused", (last_row.get("spent"), "refused" in last_row), (True, False))
    with open(refused_md) as fh:
        check("limit-not-kept-as-refused", fh.read(), refused_before)
    limit_file = os.path.join(repo, ".sclaude", "local", "feature", "local-review-limit")
    with open(limit_file) as fh:
        reset = int(fh.read())
    check_true("limit-reset-left", reset > time.time())
    why_file = os.path.join(repo, ".sclaude", "local", "feature", "local-review-why")
    with open(why_file) as fh:
        check_true("limit-why-left", "Claude's usage limit" in fh.read())
    # The topic hears the pass end, and the limit once — from the wait.
    ended = told()
    check_true("limit-pass-ends-in-topic", any("ended" in line for line in ended))
    check_true("limit-not-in-topic-twice", not any("Claude's usage limit" in line for line in ended))
    # The wait: told when, no question; an unknown reset is LIMIT_RETRY away.
    notified = os.path.join(tmp, "notified")
    out, err, rc = run_bash('REPO=%s; notify_feature() { echo "$*" > %s; }; LIMIT_RETRY=0 review_limit_wait %s 0 demo; echo RC=$?'
                            % (repo, notified, repo))
    with open(notified) as fh:
        check_true("limit-wait-told", "the review runs again by itself at" in err
                   and "demo" in fh.read() and "RC=0" in out)
    # A reset already past waits LIMIT_RETRY from now, not nothing: the
    # first tick of the wait says half an hour is left.
    out, err, rc = run_bash('REPO=%s; notify_feature() { :; }; keys_usable() { true; }; '
                            'poll_pause() { exit 7; }; review_limit_wait %s %d demo'
                            % (repo, repo, int(time.time()) - 600))
    check_true("limit-past-reset-waits-retry", rc == 7 and "(30m left)" in err)
    # The next call starts clean: neither file outlives it.
    write(os.path.join(tmp, "answer"), "FINDINGS: 0\n" + local_review.DONE + "\n")
    _, _, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo))
    check("limit-then-reviewed", (rc, os.path.exists(limit_file), os.path.exists(why_file)), (0, False, False))
    prompts()

    # A head GitHub does not have yet: no run.
    write(os.path.join(repo, "a.txt"), "g\n")
    git("commit", "-qam", "local only", cwd=repo)
    _, err, rc = review("FINDINGS: 0\n")
    check("unpushed-fails", rc, 1)
    check("unpushed-no-run", prompts(), "")

    # --- the person's word that the review has done enough ------------------
    # Said during a pass (the stub stands in for the `s` key): that pass is
    # posted, and the cap it found does not send the review round again.
    state = os.path.join(repo, ".sclaude", "local", "feature", "state.json")
    write(state, "{}\n")
    write(os.path.join(repo, "a.txt"), "enough\n")
    git("commit", "-qam", "enough", cwd=repo)
    git("push", "-q", cwd=repo)
    queue(batch("e1", 2), batch("e2", 1))
    write(os.path.join(tmp, "during"),
          'printf \'{"steps": {"review": {"enough": "pass"}}}\\n\' > "%s"\n' % state)
    posted_before = len(threads())
    out, err, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo), {"LOCAL_REVIEW_CAP": "2"})
    os.remove(os.path.join(tmp, "during"))
    check("enough-pass-rc", rc, 0)
    check("enough-pass-one-pass", prompts().count("---\n"), 1)
    check("enough-pass-posted", len(threads()) - posted_before, 2)
    check_true("enough-pass-said", "you ended the search" in err)
    # Once the search is over (`s` or `n n`), a new head is only checked:
    # the model is told not to run /code-review, a thread it judges fixed is
    # resolved, and whatever it reports as new anyway is not posted.
    # The capped follow-up the word above sent away left its answer queued.
    shutil.rmtree(os.path.join(tmp, "answers"), ignore_errors=True)
    for said in ("now", "pass"):
        write(state, '{"steps": {"review": {"enough": "%s"}}}\n' % said)
        write(os.path.join(repo, "a.txt"), "verify %s\n" % said)
        git("commit", "-qam", "verify " + said, cwd=repo)
        git("push", "-q", cwd=repo)
        # One of the review's own: a thread a person opened is not the
        # review's to resolve.
        first = [t for t in threads() if not t.get("isResolved")
                 and pr_context.signed_locally(t["comments"][0]["body"])][-1]
        rid = "r" + first["comments"][0]["url"].rsplit("_r", 1)[1]
        write(os.path.join(tmp, "answer"),
              "### a.txt:1 — sneaked in\nx\n\nRESOLVED: %s — fixed\nFINDINGS: 1\n" % rid)
        posted_before = len(threads())
        out, err, rc = run_bash('REPO=%s; local_review %s 7' % (repo, repo))
        sent = prompts()
        check("verify-%s-rc" % said, rc, 0)
        check("verify-%s-one-call" % said, sent.count("---\n"), 1)
        check_true("verify-%s-no-code-review" % said, "do not invoke the `code-review` skill" in sent)
        check_true("verify-%s-told-open" % said, rid in sent)
        check("verify-%s-nothing-new" % said, len(threads()) - posted_before, 0)
        check_true("verify-%s-resolved" % said,
                   [t for t in threads() if t["id"] == first["id"]][0]["isResolved"])
        check_true("verify-%s-count" % said, out.strip().isdigit())
    write(os.path.join(tmp, "answer"), "FINDINGS: 0\n" + local_review.DONE + "\n")

    # `x` twice at the terminal stops a pass now: nothing of it is posted or
    # recorded, the word is kept as `now`, and the count of what is open is
    # still answered — for the review session to take.
    import fcntl
    import pty
    import select
    import termios
    write(state, "{}\n")
    write(os.path.join(repo, "a.txt"), "stop now\n")
    git("commit", "-qam", "stop now", cwd=repo)
    git("push", "-q", cwd=repo)
    # Long enough that the pass cannot end by itself before the keys reach
    # it on a loaded machine: the stop kills it anyway.
    write(os.path.join(tmp, "during"), "sleep 120\n")
    write(os.path.join(tmp, "answer"), batch("never", 1))
    with open(journal) as fh:
        before = fh.read()
    posted_before = len(threads())
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""; SELF=sclaude\n'
    for name in ("core/io", "core/ui", "core/state", "core/steps", "core/project", "core/picker", "review/local_review"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += 'LIB="%s"\nwarn() { echo "$*" >&2; }\ninfo() { echo "$*"; }\n' % LIB
    # No real night reaches the box: auto draws as auto ☐ here.
    body += 'INSTRUMENTS=/nonexistent\n'
    body += 'REPO=%s; n="$(local_review %s 7)"; echo "COUNT=$n"\n' % (repo, repo)
    master, slave = pty.openpty()

    def own_tty():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    env = dict(os.environ, PATH=stubs + os.pathsep + os.environ["PATH"], GH_WORLD=world)
    proc = subprocess.Popen(["bash", "-c", body], cwd=repo, stdin=slave, stdout=slave,
                            stderr=slave, env=env, preexec_fn=own_tty, close_fds=True)
    os.close(slave)
    seen = b""

    def read_until(marker, secs):
        global seen
        end = time.time() + secs
        while marker not in seen and time.time() < end:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    seen += os.read(master, 4096)
                except OSError:
                    break
        return marker in seen

    import time
    check_true("stop-now-hint", read_until(b"[n n] stop, end the search", 60))
    # The boxes: [g] ticked shows ticked on the status line, and is kept.
    check_true("boxes-unticked", "☐ [s] last pass".encode() in seen and "auto ☐ [g] go on".encode() in seen)
    # g goes round auto → on → off; on is left for the checks below.
    os.write(master, b"g")
    check_true("go-on-ticked", read_until(" ☑ [g] go on".encode(), 5))
    os.write(master, b"n")
    # The second press only once the first has armed the stop: sent blind
    # after a fixed pause, it reached a loaded machine's loop too early.
    check_true("stop-now-armed", read_until(b"press [n] again", 15))
    os.write(master, b"n")
    check_true("stop-now-count", read_until(b"COUNT=", 15))
    proc.wait(timeout=15)
    os.close(master)
    os.remove(os.path.join(tmp, "during"))
    check_true("stop-now-said", b"Stopped pass 1 as you said" in seen)
    heads = {json.loads(line)["head"] for line in recorded(before).splitlines()}
    check_true("status-says-round", ("local review, round %d (" % (len(heads) + 1)).encode() in seen)
    check("status-no-first-pass", b"pass 1 (" in seen, False)
    check("stop-now-nothing-posted", len(threads()) - posted_before, 0)
    with open(journal) as fh:
        after = fh.read()
    check("stop-now-not-recorded", recorded(after), recorded(before))
    check_true("stop-now-spent-journaled", after.count('"spent": true') > before.count('"spent": true'))
    answer_file = os.path.join(repo, ".sclaude", "local", "feature", "local-review-answer.md")
    with open(answer_file) as fh:
        check_true("stop-now-keeps-last-answer", "never" not in fh.read())
    check("stop-now-no-part", os.path.exists(answer_file + ".part"), False)
    with open(state) as fh:
        left = json.load(fh)["steps"]["review"]
    check("stop-now-kept", left["enough"], "now")
    check("go-on-kept", left.get("go_on"), True)
    prompts()

    # The same stop pressed in the feature's topic, with no terminal at all:
    # the bot's word (review_keys.say) in the channel ends the pass at once.
    sys.path.insert(0, ROOT)
    from keepawake import review_keys
    write(state, "{}\n")
    write(os.path.join(repo, "a.txt"), "stop from the phone\n")
    git("commit", "-qam", "stop from the phone", cwd=repo)
    git("push", "-q", cwd=repo)
    write(os.path.join(tmp, "during"), "sleep 30\n")
    with open(journal) as fh:
        before = fh.read()
    ask_dir = os.path.join(tmp, "ask-dir")
    phone = os.path.join(ask_dir, "ask", "feat")
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""; SELF=sclaude\n'
    for name in ("core/io", "core/ui", "core/state", "core/steps", "core/project", "core/picker", "review/local_review"):
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += 'LIB="%s"\nwarn() { echo "$*" >&2; }\ninfo() { echo "$*"; }\n' % LIB
    body += 'ASK_DIR=%s; ASK_SLUG=feat\n' % ask_dir
    body += 'REPO=%s; n="$(local_review %s 7)"; echo "COUNT=$n"\n' % (repo, repo)
    began = time.time()
    proc = subprocess.Popen(["bash", "-c", body], cwd=repo, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=dict(os.environ, PATH=stubs + os.pathsep + os.environ["PATH"],
                                     GH_WORLD=world), start_new_session=True)
    feed_file = os.path.join(phone, "notes", "feed.tsv")
    while time.time() - began < 20:
        if os.path.exists(feed_file) and "Local review started" in open(feed_file).read():
            break
        time.sleep(0.2)
    lines = [line.split("\t", 3) for line in open(feed_file).read().splitlines()]
    check("phone-buttons-on-start", review_keys.kind_of([(lv, pid, text) for _, lv, pid, text in lines]),
          ("pass", lines[-1][2]))
    time.sleep(1)
    review_keys.say(phone, "now")
    out, err = proc.communicate(timeout=20)
    os.remove(os.path.join(tmp, "during"))
    check_true("phone-stop-quick", time.time() - began < 15)
    check_true("phone-stop-count", "COUNT=" in out)
    check_true("phone-stop-said", "Stopped pass 1 as you said" in err)
    check("phone-stop-taken", os.path.exists(os.path.join(phone, review_keys.SAID_FILE)), False)
    with open(journal) as fh:
        check("phone-stop-not-recorded", recorded(fh.read()), recorded(before))
    with open(state) as fh:
        check("phone-stop-kept", json.load(fh)["steps"]["review"]["enough"], "now")
    prompts()

    # A round is a head: two passes over one head count once, and the head
    # being reviewed is the next round whether or not a pass of it is in.
    rounds = os.path.join(tmp, "rounds.jsonl")
    write(rounds, "".join(json.dumps({"at": "t", "head": h}) + "\n" for h in ("a", "b", "b", "c")))

    def round_of(head):
        return subprocess.run([sys.executable, os.path.join(LIB, "review", "local_review.py"), "round",
                               rounds, head], capture_output=True, text=True).stdout.strip()
    check("round-new-head", round_of("d"), "4")
    check("round-capped-head", round_of("c"), "3")
    check("round-empty-journal", subprocess.run(
        [sys.executable, os.path.join(LIB, "review", "local_review.py"), "round", os.path.join(tmp, "none"), "a"],
        capture_output=True, text=True).stdout.strip(), "1")

    # --- the prompts ------------------------------------------------------------
    def render(step, **values):
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(("SCLAUDE_V_", "SCLAUDE_B_")):
                del env[key]
        env.update({"SCLAUDE_V_FEATURE": "f", "SCLAUDE_V_PR": "7", "SCLAUDE_V_ISSUE": "",
                    "SCLAUDE_V_MANUALS": "m", "SCLAUDE_V_DEV_URL": "u",
                    "SCLAUDE_V_DEV_PORT": "1", "SCLAUDE_V_DEFERRED": "d",
                    "SCLAUDE_V_DB_API": "", "SCLAUDE_V_SHARED_DB": "",
                    "SCLAUDE_V_NO_REVIEW": "", "SCLAUDE_V_REVIEW_LOCAL": "",
                    "SCLAUDE_V_REVIEW_MODE": "github"})
        env.update(values)
        out = subprocess.run([sys.executable, os.path.join(LIB, "cycle", "render_prompt.py"),
                              os.path.join(PROMPTS, step + ".md"), PROMPTS],
                             capture_output=True, text=True, env=env)
        return out.returncode, out.stdout + out.stderr

    rc, text = render("pr")
    check("pr-github-renders", rc, 0)
    check_true("pr-github-no-label", "/pr no-review" not in text)
    rc, text = render("pr", SCLAUDE_V_NO_REVIEW="1", SCLAUDE_V_REVIEW_MODE="local")
    check("pr-local-renders", rc, 0)
    check_true("pr-local-label", "/pr no-review" in text and "`local`" in text)
    rc, text = render("review")
    check("review-github-renders", rc, 0)
    check_true("review-github-no-local", "reviewed on this machine" not in text)
    rc, text = render("review", SCLAUDE_V_REVIEW_LOCAL="1", SCLAUDE_V_REVIEW_MODE="local",
                      SCLAUDE_V_ACTIONS_OFF="1")
    check("review-local-renders", rc, 0)
    check_true("review-local-told", "reviewed on this machine" in text
               and "GitHub Actions is out of this feature's verdict" in text)
    # Moved here for Claude's limit alone: the CI still runs, and counts.
    rc, text = render("review", SCLAUDE_V_REVIEW_LOCAL="1", SCLAUDE_V_REVIEW_MODE="local")
    check_true("review-moved-for-quota-keeps-ci", "reviewed on this machine" in text
               and "GitHub Actions is out of this feature's verdict" not in text)

    # `sclaude checks` returning in the session's tab prints the report in
    # sclaude's: once per new mark, and not for a mark left before the launch.
    checked = os.path.join(repo, ".sclaude", "local", "feature", "review-checked")
    write(checked, "1 aaa 1\n")
    out, err, _ = run_bash(
        'review_report_unshown() { echo "REPORT $2"; }; review_enough() { :; }; '
        'review_go_box() { :; }; review_box() { :; }; '
        'review_pane_keys "%s" slug ""; review_pane_keys "%s" slug ""; '
        'echo "0 bbb 2" > "%s"; review_pane_keys "%s" slug ""; review_pane_keys "%s" slug ""'
        % (repo, repo, checked, repo, repo))
    check("pane-report-once-per-mark", err.count("REPORT slug"), 1)
    # And asks for a table only when a round finished since the last one.
    out, err, _ = run_bash(
        'review_report_unshown() { echo "REPORT ${REVIEW_REPORT_ROUNDS_ONLY:-} $2"; }; review_enough() { :; }; '
        'review_go_box() { :; }; review_box() { :; }; '
        'review_pane_keys "%s" slug ""; echo "1 ccc 3" > "%s"; review_pane_keys "%s" slug ""'
        % (repo, checked, repo))
    check("pane-report-rounds-only", "REPORT 1 slug" in err, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# An answer handed back before the review was done — no end line — is not
# recorded: the head is not taken as reviewed and nothing is posted.
with tempfile.TemporaryDirectory() as tmp_done:
    early = os.path.join(tmp_done, "answer")
    with open(early, "w") as fh:
        fh.write("FINDINGS: 0\n")
    check("an-unfinished-answer-is-refused",
          local_review.record(tmp_done, "7", "o/r", early, "a", "b", "1", os.path.join(tmp_done, "j")), 1)
# A capped pass whose follow-up never finished: a run on the same head reads
# its range again; a head moved on starts from it.
with tempfile.TemporaryDirectory() as tmp_since:
    j = os.path.join(tmp_since, "j")
    with open(j, "w") as fh:
        fh.write(json.dumps({"at": "2026-01-01T10:00:00+00:00", "base": "B", "head": "H1", "more": True}) + "\n")
    since = lambda h: subprocess.run([sys.executable, os.path.join(LIB, "review", "local_review.py"), "since", j, h],
                                     capture_output=True, text=True).stdout.strip()
    check("since-a-capped-range", (since("H1"), since("H2")), ("B", "H1"))

# /sreview asks its reviewer for the same line, and records through `record`.
with open(os.path.join(ROOT, "skills", "sreview", "SKILL.md"), encoding="utf-8") as fh:
    check_true("sreview-asks-the-end-line", "`%s`" % local_review.DONE in fh.read())

# A stop kills the process the pass's $! names: claude itself, which a pipe
# into it would not be (it outlived the subshell and went on spending).
with open(os.path.join(LIB, "review", "local_review.sh"), encoding="utf-8") as fh:
    src = fh.read()
check_true("pass-claude-is-the-killed-process",
           "exec claude -p --session-id" in src and "| exec claude" not in src)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
