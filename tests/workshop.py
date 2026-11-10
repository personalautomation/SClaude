#!/usr/bin/env python3
#
# The workshop (sclaude/lib/improve/workshop.sh, workshop.py): where a session changes
# sclaude, and how what it made there is published.
#
# A sandbox stands for everything: a bare repository for sclaude's origin, a
# clone of it for the live checkout, a product with a feature's tree. The
# person's answers and the maintainer test are stubbed; git is real.
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "sclaude", "lib")
PY = os.path.join(LIB, "improve", "workshop.py")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, got, want))


def git(where, *args, check_=True):
    return subprocess.run(["git", "-C", where, "-c", "user.name=t", "-c", "user.email=t@t.test"]
                          + list(args), capture_output=True, text=True, check=check_).stdout.strip()


def ws_py(*args):
    return subprocess.run([sys.executable, PY] + list(args), capture_output=True, text=True)


tmp = tempfile.mkdtemp(prefix="sclaude-workshop-")
try:
    # --- the record ------------------------------------------------------------
    rec = os.path.join(tmp, "rec.json")
    check("not-approved-before", ws_py("approved", rec, "s1").returncode, 1)
    ws_py("approve", rec, "s1")
    ws_py("approve", rec, "s1")
    check("approved", ws_py("approved", rec, "s1").returncode, 0)
    check("approved-once", json.load(open(rec))["approved"], ["s1"])
    check("other-not-approved", ws_py("approved", rec, "s2").returncode, 1)
    ws_py("ready", rec, "s1", "abc", "sreview")
    check("ready-head", ws_py("get", rec, "ready.head").stdout.strip(), "abc")
    ws_py("put", rec, "ready", "null")
    check("ready-cleared", ws_py("get", rec, "ready.head").returncode, 1)
    ws_py("reopen", rec, "s1", "/some/cwd", "--session-id", "s1", "-n", "x", "the prompt")
    out = ws_py("reopen-args", rec).stdout.split("\0")
    check("reopen-args", out[:5], ["/some/cwd", "--session-id", "s1", "-n", "x"])

    # --- the sandbox -------------------------------------------------------------
    origin = os.path.join(tmp, "origin.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
    live = os.path.join(tmp, "instruments")
    subprocess.run(["git", "clone", "-q", origin, live], capture_output=True, check=True)
    os.makedirs(os.path.join(live, "tests"))
    os.makedirs(os.path.join(live, "sclaude", "lib"))
    with open(os.path.join(live, "sclaude", "lib", "tool.sh"), "w") as fh:
        fh.write("#!/usr/bin/env bash\necho tool\n")
    with open(os.path.join(live, "tests", "tool.py"), "w") as fh:
        fh.write("# checks tool\nimport sys\nsys.exit(0)\n")
    git(live, "add", "-A")
    git(live, "commit", "-qm", "init")
    git(live, "push", "-q", "origin", "HEAD:main")
    git(live, "fetch", "-q", "origin")
    # The machine's say, as an install that answered: sent, and taken. The
    # cases for the other answers come near the end.
    git(live, "config", "sclaude.contribute", "send")
    git(live, "config", "sclaude.update", "auto")

    product = os.path.join(tmp, "myshop")
    subprocess.run(["git", "init", "-q", "-b", "main", product], check=True)
    git(product, "remote", "add", "origin", "git@github.com:acme/myshop.git")
    os.makedirs(os.path.join(product, "app", "orders"))
    with open(os.path.join(product, "app", "orders", "checkout.tsx"), "w") as fh:
        fh.write("x\n")
    with open(os.path.join(product, ".gitignore"), "w") as fh:
        fh.write(".sclaude/local\n")
    git(product, "add", "-A")
    git(product, "commit", "-qm", "init")
    tree = os.path.join(tmp, "myshop-12-orders")
    git(product, "worktree", "add", "-q", "-b", "feat/12-orders", tree)
    os.makedirs(os.path.join(tree, ".sclaude", "local", "feature"))
    with open(os.path.join(tree, ".sclaude", "local", "feature", "state.json"), "w") as fh:
        json.dump({"slug": "12-orders", "branch": "feat/12-orders"}, fh)

    def sh(script, maintainer=True, answer="n", session="s1", cwd=None):
        body = """
INSTRUMENTS=%(live)s; LIB=%(lib)s; PROMPTS=%(root)s/sclaude/prompts; SELF=sclaude
source "$LIB/core/ui.sh"; source "$LIB/core/pane.sh"; source "$LIB/core/developer.sh"; source "$LIB/core/state.sh"; source "$LIB/improve/workshop.sh"; source "$LIB/cycle/run.sh"
info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }; say() { echo "SAY $*"; }
die() { echo "DIE $*"; exit 1; }
BOLD=; OFF=; GREEN=
developer_is_maintainer() { return %(maint)d; }
developer_name() { echo ann; }
instruments_others() { return 1; }
# The answers in turn, the last one for every question after.
ANSWERS=(%(answer)s); ASKED=0
ask() { local a="${ANSWERS[$ASKED]:-${ANSWERS[-1]}}"; ASKED=$((ASKED + 1)); printf -v "$2" '%%s' "$a"; echo "ASK $1"; }
instruments_propose() { echo "PROPOSE $1 $2 $PROPOSE_DIR"; echo "INTRO $PROPOSE_INTRO"; }
claude_launch_once() { echo "RELAUNCH $*"; }
export SCLAUDE_SESSION=%(session)s
%(script)s
""" % {"live": live, "lib": LIB, "root": ROOT, "maint": 0 if maintainer else 1,
       "answer": answer, "session": session, "script": script}
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_CONFIG", "ASK_"))}
        env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.test",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.test"})
        done = subprocess.run(["bash", "-c", body], cwd=cwd or tree, capture_output=True,
                              text=True, env=env, timeout=120)
        return done.stdout

    ws = os.path.join(tree, ".sclaude", "local", "instruments")
    record = ws + ".json"

    # core-open makes the workshop from origin's main and lets the session in.
    out = sh("cmd_core_open")
    check("open-made-worktree", os.path.isdir(os.path.join(ws, "tests")), True)
    check("open-approved", ws_py("approved", record, "s1").returncode, 0)
    check("open-branch-is-workshop", git(ws, "rev-parse", "--abbrev-ref", "HEAD").startswith("workshop/"), True)
    check("open-says-sreview", "/sreview" in out, True)
    check("open-without-session", "DIE" in sh("cmd_core_open", session=""), True)

    # Nothing made: nothing to publish, nothing asked.
    check("state-none", sh('workshop_state "%s"' % tree).strip(), "none")
    check("after-nothing", sh('workshop_after_session s1 --session-id s1 -n x p').strip(), "")

    # Made and not ready: the person is asked to reopen the session or drop
    # the change; unanswered, nothing is decided, and the session to reopen is
    # kept for the next opening.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("echo more\n")
    check("ready-refuses-dirty", "DIE" in sh("cmd_core_ready"), True)
    git(ws, "commit", "-qam", "feat(sclaude): the tool says more")
    check("ready-refuses-without-sreview", "sreview has not finished" in sh("cmd_core_ready"), True)
    check("state-unready", sh('workshop_state "%s"' % tree).strip(), "unready")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; ask() { echo "ASK $1 ${*:4}"; return 1; }; '
             'workshop_after_session s1 --session-id s1 --model opus -n x "the prompt"')
    check("after-unready-asks", "ASK" in out and "RELAUNCH" not in out, True)
    check("after-unready-unanswered-history", "HISTORY asked" in out, True)
    check("after-unready-offers-reopen-and-drop", ("Reopen" in out, "Drop" in out, "Send —" in out), (True, True, False))
    check("after-unready-names-the-mark", "sreview's mark" in out, True)
    check("after-unready-keeps-the-session", ws_py("get", record, "reopen.session").stdout.strip(), "s1")
    check("after-unready-stays", sh('workshop_state "%s"' % tree).strip(), "unready")
    # Reopen resumes the same session, with its arguments and what is missing.
    out = sh('workshop_after_session s1 --session-id s1 --model opus -n x "the prompt"', answer="1 0")
    check("after-reopen-resumes", "RELAUNCH --resume s1 --model opus -n x" in out, True)
    check("after-reopen-says-what-is-missing", "What is missing: sreview's mark" in out, True)
    check("after-reopen-asks-again", out.count("ASK") >= 2, True)
    # From the next opening, the same question; reopen launches the session.
    out = sh('claude_launch() { echo "LAUNCH $*"; }; workshop_pending "%s"' % tree, answer="1")
    check("pending-reopened", "LAUNCH --resume s1" in out and "What is missing:" in out, True)
    # A session whose directory is gone cannot be reopened: only drop is offered.
    ws_py("reopen", record, "s1", "/no/such/dir", "--session-id", "s1", "-n", "x", "p")
    out = sh('claude_launch() { echo "LAUNCH $*"; }; workshop_pending "%s"' % tree, answer="0")
    check("pending-gone-dir-drop-only", ("ASK" in out, "Reopen" in out, "Drop" in out, "LAUNCH" in out),
          (True, False, True, False))
    ws_py("reopen", record, "s1", "/some/cwd", "--session-id", "s1", "-n", "x", "p")

    # sreview's mark at the head makes it ready for a maintainer.
    common = git(ws, "rev-parse", "--path-format=absolute", "--git-common-dir")
    branch = git(ws, "rev-parse", "--abbrev-ref", "HEAD")
    mark = os.path.join(common, "sreview", "branches", branch + ".reviewed")
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    with open(mark, "w") as fh:
        fh.write(git(ws, "rev-parse", "HEAD") + "\n")
    out = sh("cmd_core_ready")
    check("ready-with-mark", "Ready" in out, True)
    check("state-ready", sh('workshop_state "%s"' % tree).strip(), "ready")

    # A second commit: squashed into one on publication, and the tests the
    # change touches run.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("echo again\n")
    git(ws, "commit", "-qam", "fix(sclaude): review iteration 1 — say it again\n\nCo-Authored-By: X <x@x>")
    with open(mark, "w") as fh:
        fh.write(git(ws, "rev-parse", "HEAD") + "\n")
    sh("cmd_core_ready")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_after_session s1 --session-id s1 -n x p')
    check("published-to-main", "Published to sclaude's main" in out, True)
    # Nothing to ask under sclaude.contribute send: past the question unasked.
    check("published-unasked-edge", ("HISTORY w_clear w_who by=setting" in out, "w_decide" in out), (True, False))
    check("published-checked", "1 test file(s)" in out, True)
    log = git(origin, "log", "--format=%s", "main")
    check("published-squashed", log.splitlines()[0], "feat(sclaude): the tool says more")
    body = git(origin, "log", "-1", "--format=%B", "main")
    check("squash-keeps-the-rest", "review iteration 1" in body and "Co-Authored-By: X <x@x>" in body, True)
    check("live-fast-forwarded", git(live, "rev-parse", "HEAD"), git(origin, "rev-parse", "main"))
    # A checkout with commits of its own is told how to follow, not left vague.
    git(live, "commit", "-q", "--allow-empty", "-m", "by hand, unpushed")
    out = sh("workshop_live_update")
    check("live-own-commits-said", "1 commit(s) of its own" in out and "pull --rebase" in out, True)
    git(live, "reset", "-q", "--hard", "origin/main")
    check("state-none-after", sh('workshop_state "%s"' % tree).strip(), "none")

    # The product's details hold it back unless the person says otherwise.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("# seen on app/orders/checkout.tsx in PR #12\n")
    git(ws, "commit", "-qam", "fix(sclaude): from myshop")
    hits = ws_py("leaks", ws, "origin/main", tree)
    check("leaks-found", hits.returncode, 1)
    check("leaks-name-path", "app/orders/checkout.tsx" in hits.stdout, True)
    check("leaks-name-repo", "from myshop" in hits.stdout, True)
    with open(mark, "w") as fh:
        fh.write(git(ws, "rev-parse", "HEAD") + "\n")
    sh("cmd_core_ready")
    before = git(origin, "rev-parse", "main")
    # Found lines are shown with the one question after the tests;
    # unanswered, nothing goes and nothing is decided.
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_after_session s1 --session-id s1 -n x p', answer="0")
    check("leak-asked-after-tests", ("may name the product" in out, "ASK" in out,
                                     out.find("Testing sclaude itself") < out.find("ASK")), (True, True, True))
    check("leak-shown-with-the-commits", ("which is public" in out, "app/orders/checkout.tsx" in out), (True, True))
    check("leak-not-published", git(origin, "rev-parse", "main"), before)
    check("leak-unanswered-stays-ready", sh('workshop_state "%s"' % tree).strip(), "ready")
    check("leak-unanswered-history", "HISTORY asked" in out, True)
    # The check itself asks nothing: it hands the lines on.
    out = sh('workshop_leaks "%s" origin/main "%s"; echo "HITS=[${WORKSHOP_HITS:0:5}]"' % (ws, tree))
    check("leaks-handed-on", ("ASK" in out, "HITS=[]" in out), (False, False))
    # A send is kept for the lines it was shown: a retry does not ask about them.
    out = sh('workshop_publish "%s"' % tree, maintainer=False, answer="1")
    check("leak-send-sent", "PROPOSE" in out, True)
    out = sh('workshop_leaks "%s" origin/main "%s"; echo "HITS=[$WORKSHOP_HITS]"' % (ws, tree))
    check("leak-send-remembered", "HITS=[]" in out, True)
    # A new line naming the product is asked about, though the diff is the same.
    git(ws, "commit", "-q", "--allow-empty", "-m", "fix(sclaude): as seen in issue #77")
    out = sh('workshop_leaks "%s" origin/main "%s"; echo "HITS=[$WORKSHOP_HITS]"' % (ws, tree))
    check("leak-new-line-asked", "HITS=[]" in out, False)
    git(ws, "reset", "-q", "--hard", "HEAD~1")
    ws_py("put", record, "leaks_ok", "null")
    # sclaude.leaks auto shows them and lets them go; off asks like ask — the
    # person who sends after seeing them takes the risk.
    git(live, "config", "sclaude.leaks", "auto")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_leaks "%s" origin/main "%s"; echo "HITS=[$WORKSHOP_HITS]"' % (ws, tree))
    check("leaks-auto-shown-unasked", ("go out unasked" in out, "HITS=[]" in out), (True, True))
    check("leaks-auto-edge", "HISTORY w_leaks w_tests by=setting" in out, True)
    git(live, "config", "sclaude.leaks", "off")
    out = sh('workshop_leaks "%s" origin/main "%s"; echo "HITS=[$WORKSHOP_HITS]"' % (ws, tree))
    check("leaks-off-asks", "HITS=[]" in out, False)
    git(live, "config", "--unset", "sclaude.leaks")
    # A context too long for a question on the phone is asked at the terminal
    # alone; nobody there is no answer.
    out = sh('ASK_DIR=/somewhere; ask() { echo "ASK dir=[$ASK_DIR]"; return 1; }; '
             'workshop_decide "%s" "long" "$(for n in $(seq 40); do echo "issue #$n of myshop $(printf x%%.0s $(seq 60))"; done)" send reopen drop; '
             'echo "choice=$WORKSHOP_CHOICE"' % tree)
    check("long-context-at-terminal", ("ASK dir=[]" in out, "answer it here" in out, "choice=none" in out), (True, True, True))
    # Drop empties the workshop and keeps the change under a ref of its own.
    head = git(ws, "rev-parse", "HEAD")
    ws_py("reopen", record, "s1", tree, "--session-id", "s1", "-n", "x", "p")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_decide "%s" "x" "" send reopen drop; echo "choice=$WORKSHOP_CHOICE"' % tree, answer="3")
    check("drop-chosen", ("choice=drop" in out, "HISTORY dropped" in out, "HISTORY w_decide w_drop by=person" in out),
          (True, True, True))
    dropped = git(live, "for-each-ref", "--format=%(objectname)", "refs/sclaude/dropped")
    check("drop-kept-under-a-ref", head in dropped.split(), True)
    check("drop-empties-the-workshop", sh('workshop_state "%s"' % tree).strip(), "none")

    # Clean text passes the check.
    git(ws, "reset", "-q", "--hard", "origin/main")
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("# a hook refused an ordinary read\n")
        fh.write('pr="$(state_get "$state" pr 2>/dev/null || true)"\n')
    git(ws, "commit", "-qam", "fix(sclaude): read what a hook refused")
    check("no-leaks", ws_py("leaks", ws, "origin/main", tree).returncode, 0)

    # A scope-less subject and a body line that looks like a trailer are read.
    git(ws, "commit", "-q", "--allow-empty", "-m", "fix: myshop made the hook refuse",
        "-m", "Seen in: PR #412")
    hits = ws_py("leaks", ws, "origin/main", tree).stdout
    check("leaks-scope-less-subject", "myshop made the hook refuse" in hits, True)
    check("leaks-trailer-like-body", "PR #412" in hits, True)
    git(ws, "reset", "-q", "--hard", "HEAD~1")

    # Anybody else's goes to its pull request, unsquashed, from the branch.
    out = sh('workshop_publish "%s"' % tree, maintainer=False)
    check("other-proposes", "PROPOSE" in out and ws in out, True)
    # A push that failed is the person's question too: unanswered, the change
    # stays ready, and the next opening goes through it again.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("# and once more\n")
    git(ws, "commit", "-qam", "fix(sclaude): once more")
    start = ws_py("get", record, "start").stdout.strip()
    ws_py("ready", record, "s1", git(ws, "rev-parse", "HEAD"), "a read")
    out = sh('instruments_propose() { return 2; }; workshop_publish "%s"' % tree, maintainer=False, answer="0")
    check("failed-push-asked", ("pull request was not sent" in out, "ASK" in out), (True, True))
    check("failed-push-not-sent", ws_py("get", record, "start").stdout.strip(), start)
    check("failed-push-stays-ready", sh('workshop_state "%s"' % tree).strip(), "ready")
    check("failed-push-unpublished", sh('workshop_unpublished "%s" && echo yes' % tree).strip(), "yes")
    # A send tries the push again.
    out = sh('history_add() { echo "HISTORY $3 $4"; }; n=0; instruments_propose() { n=$((n + 1)); (( n > 1 )) && echo PROPOSE; (( n > 1 )); }; '
             'workshop_publish "%s"' % tree, maintainer=False, answer="1")
    check("failed-push-send-retries", ("PROPOSE" in out, "HISTORY w_who w_decide" in out, "HISTORY w_decide w_leaks by=person" in out,
                                       out.count("Testing sclaude itself")), (True, True, True, 2))
    check("failed-push-then-sent", sh('workshop_state "%s"' % tree).strip(), "none")

    # A maintainer's publication stopped by red tests after the squash leaves
    # the squashed head ready, and asks the person.
    git(ws, "reset", "-q", "--hard", "origin/main")
    ws_py("put", record, "start", json.dumps(git(ws, "rev-parse", "HEAD")))
    for n in (1, 2):
        with open(os.path.join(ws, "tests", "tool.py"), "w") as fh:
            fh.write("# checks tool\nimport sys\nsys.exit(%d)\n" % n)
        git(ws, "commit", "-qam", "fix(sclaude): tool test %d" % n)
    ws_py("ready", record, "s1", git(ws, "rev-parse", "HEAD"), "sreview")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_publish "%s"' % tree, answer="0")
    check("red-not-published", "Red:" in out and "Published" not in out, True)
    check("red-asked", ("ASK" in out, "HISTORY red" in out, "HISTORY w_clear w_decide" in out), (True, True, True))
    check("red-test-named", "✗ tool.py" in out, True)
    check("red-squashed-head-ready", ws_py("get", record, "ready.head").stdout.strip(),
          git(ws, "rev-parse", "HEAD"))
    check("red-stays-ready", sh('workshop_state "%s"' % tree).strip(), "ready")
    out = sh('workshop_pending "%s"' % tree, answer="0")
    check("red-retried-on-entry", ("Testing sclaude itself" in out, "ASK" in out), (True, True))
    # A send after red runs the tests again.
    out = sh('workshop_publish "%s"' % tree, answer="1 0")
    check("red-send-tests-again", out.count("Testing sclaude itself"), 2)
    # A reopen from the question launches the session that made it.
    ws_py("reopen", record, "s1", tree, "--session-id", "s1", "-n", "x", "p")
    out = sh('claude_launch() { echo "LAUNCH $*"; }; workshop_pending "%s"' % tree, answer="2")
    check("red-reopen-launches", ("LAUNCH --resume s1" in out, "The person reopened this session" in out), (True, True))
    check("red-reopen-says-what-was-red", "What stopped it: red: tests/tool.py" in out, True)
    # No session to reopen: reopen is not offered.
    ws_py("put", record, "reopen", "null")
    out = sh('workshop_publish "%s"' % tree, answer="0")
    check("red-no-session-no-reopen", ("Send —" in out, "Reopen —" in out), (True, False))
    # Red right after the session that made it: that session is reopened
    # unasked, told which tests and where their output is — twice, and then
    # it is the person's question.
    fix = ('claude_launch_once() { echo "RELAUNCH $*"; git -C "%s" commit -q --allow-empty -m "fix: try"; '
           'workshop_py ready "%s" s1 "$(git -C "%s" rev-parse HEAD)" sreview; }; ' % (ws, record, ws))
    out = sh(fix + 'workshop_after_session s1 --session-id s1 -n x p', answer="0")
    check("red-reopens-the-session", "RELAUNCH --resume s1 -n x" in out, True)
    check("red-word-names-the-test", "Red: tests/tool.py. Their output: %s-tests.log" % ws in out, True)
    check("red-log-beside-the-workshop", os.path.exists(ws + "-tests.log"), True)
    check("red-twice-then-asked", (out.count("RELAUNCH"), "Send, reopen or drop?" in out), (2, True))
    check("red-then-stays-ready", sh('workshop_state "%s"' % tree).strip(), "ready")
    git(ws, "reset", "-q", "--hard", "origin/main")
    ws_py("put", record, "ready", "null")
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("# left for the removal\n")
    git(ws, "commit", "-qam", "fix(sclaude): left for the removal")

    # A deleted file still picks the tests that name it.
    out = sh('git -C "%s" rm -q sclaude/lib/tool.sh && git -C "%s" commit -qm gone && '
             'workshop_tests "%s" HEAD~1' % (ws, ws, ws))
    check("deleted-file-picks-its-test", "1 test file(s)" in out, True)
    # With no terminal no progress line is drawn, and the run ends on how it
    # went; a red test is named on a line of its own.
    check("tests-said-each", "[1/1]" not in out and "all 1 green" in out, True)
    git(ws, "reset", "-q", "--hard", "HEAD~1")

    # A remote or a branch recorded in the shared config is not a change of the
    # checkout's config.
    out = sh('source "$LIB/core/steps.sh"; a="$(instruments_state)"; '
             'git -C "%s" config branch.dev/ann-1.remote origin; git -C "%s" remote add fork /tmp/f; '
             'b="$(instruments_state)"; [[ "$a" == "$b" ]] && echo same' % (ws, ws))
    check("config-workshop-records-ignored", out.strip().endswith("same"), True)
    # Where origin points is still sclaude's own business.
    out = sh('source "$LIB/core/steps.sh"; a="$(instruments_state)"; '
             'git -C "%s" remote set-url origin /tmp/elsewhere; '
             'b="$(instruments_state)"; [[ "$a" == "$b" ]] && echo same || echo moved' % live)
    check("config-origin-counted", out.strip().endswith("moved"), True)
    git(live, "remote", "set-url", "origin", origin)

    # --- the machine's say in sending (sclaude.contribute) --------------------
    def ready_change(text):
        with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
            fh.write("# %s\n" % text)
        git(ws, "commit", "-qam", "fix(sclaude): %s" % text)
        ws_py("put", record, "asked", "null")
        ws_py("ready", record, "s1", git(ws, "rev-parse", "HEAD"), "a read")

    git(live, "config", "sclaude.contribute", "ask")
    ready_change("asked first")
    out = sh('workshop_publish "%s"' % tree, maintainer=False, answer="0")
    check("ask-shows-and-asks", ("Send, reopen or drop?" in out, "which is public" in out,
                                 "asked first" in out, "tool.sh" in out), (True, True, True, True))
    check("ask-unanswered-not-sent", "PROPOSE" in out, False)
    check("ask-unanswered-stays-ready", sh('workshop_state "%s"' % tree).strip(), "ready")
    out = sh("cmd_core_send", maintainer=False, answer="1")
    check("core-send-refused-to-a-session", ("DIE" in out, "PROPOSE" in out), (True, False))
    out = sh('history_add() { echo "HISTORY $3 $4"; }; cmd_core_send', maintainer=False, answer="0", session="")
    check("core-send-sends-unasked", ("PROPOSE" in out, "Send, reopen or drop?" in out), (True, False))
    check("core-send-edge", "HISTORY w_decide w_leaks by=person" in out, True)
    # Out of reach on core-send with no question open: from the ready gate
    # to the question, and no way into the checks.
    ready_change("sent while out of reach")
    git(live, "remote", "set-url", "origin", os.path.join(tmp, "nowhere.git"))
    out = sh('history_add() { echo "HISTORY $3 $4"; }; cmd_core_send', maintainer=False, answer="0", session="")
    git(live, "remote", "set-url", "origin", origin)
    check("core-send-out-of-reach-asks-from-the-gate", ("out of reach" in out, "HISTORY w_decide w_leaks" in out,
                                           "HISTORY w_ready_gate w_decide" in out), (True, False, True))
    # A send at the out-of-reach question goes back through the checks, its
    # way written once, after the preparation that then went through.
    ready_change("sent after out of reach")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; eval "real_$(declare -f workshop_prepare)"; n=0; '
             'workshop_prepare() { n=$((n + 1)); (( n > 1 )) && { real_workshop_prepare "$@"; return; }; '
             'WORKSHOP_WHY="out of reach"; return 1; }; workshop_publish "%s"' % tree, maintainer=False, answer="1 0")
    check("send-after-out-of-reach-checks-again", (out.count("HISTORY w_decide w_leaks by=person"), "Testing sclaude itself" in out),
          (1, True))
    # Opened again on a question nobody answered: checked again, by sclaude.
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_pending "%s"' % tree, maintainer=False, answer="0")
    check("reopened-tree-checks-again", "HISTORY w_decide w_leaks by=sclaude" in out, True)
    # A ready change with no question left open (a run cut off before it
    # asked) comes back from the ready gate.
    ws_py("put", record, "asked", "null")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_pending "%s"' % tree, maintainer=False, answer="0")
    check("cut-off-run-checks-from-the-gate", ("HISTORY w_ready_gate w_leaks by=sclaude" in out, "HISTORY w_decide w_leaks" in out),
          (True, False))
    # Lines that may name the product are still shown and asked about, once.
    ready_change("seen in issue #77 of myshop")
    out = sh("cmd_core_send", maintainer=False, answer="0", session="")
    check("core-send-asks-about-lines", ("PROPOSE" in out, "may name the product" in out, "issue #77" in out),
          (False, True, True))
    ws_py("reopen", record, "s1", tree, "--session-id", "s1", "-n", "x", "p")
    out = sh('claude_launch() { echo "LAUNCH send=[${WORKSHOP_SEND:-}] from=[${WORKSHOP_FROM:-}] $*"; }; cmd_core_send', maintainer=False, answer="2", session="")
    check("core-send-reopen-launches", ("LAUNCH send=[] from=[] --resume s1" in out, "may name the product" in out), (True, True))
    git(ws, "reset", "-q", "--hard", "HEAD~1")
    ready_change("asked and said send")
    out = sh('history_add() { echo "HISTORY $3 $4"; }; workshop_publish "%s"' % tree, maintainer=False, answer="1")
    check("ask-send-sent", ("Send, reopen or drop?" in out, "PROPOSE" in out), (True, True))
    check("ask-send-edges", ("HISTORY w_tests w_clear by=sclaude" in out, "HISTORY w_clear w_decide by=sclaude" in out,
                             "HISTORY w_decide w_who by=person" in out, "HISTORY w_who w_pr by=sclaude" in out,
                             "HISTORY w_pr w_done by=sclaude" in out), (True, True, True, True, True))
    ready_change("asked while away")
    out = sh('review_go_on() { return 0; }; workshop_publish "%s"' % tree, maintainer=False, answer="1")
    check("away-not-asked-not-sent", ("ASK" in out, "PROPOSE" in out, "You are away" in out), (False, False, True))
    check("away-stays-ready", sh('workshop_state "%s"' % tree).strip(), "ready")
    git(live, "config", "--unset", "sclaude.contribute")
    out = sh('workshop_publish "%s"' % tree, maintainer=False, answer="0")
    check("unset-is-ask", ("Send, reopen or drop?" in out, "PROPOSE" in out), (True, False))
    git(live, "config", "sclaude.contribute", "off")
    ready_change("made before it was off")
    out = sh('workshop_publish "%s"' % tree, maintainer=False, answer="0")
    check("off-asks-too", ("Send, reopen or drop?" in out, "PROPOSE" in out), (True, False))
    out = sh("cmd_core_open", session="s9")
    check("off-core-open-refused", ("DIE" in out, "is off" in out), (True, True))
    closed = sh('workshop_rules "%s"' % tree)
    check("off-rules-closed", ("is off on this machine" in closed, "core-open` first" in closed,
                               "<instruments>" in closed), (True, False, False))
    git(live, "config", "sclaude.contribute", "send")
    # A maintainer's publish moves the live checkout only where updates are
    # taken by themselves.
    git(live, "config", "sclaude.update", "notify")
    out = sh("workshop_live_update")
    check("live-update-notify-said", "sclaude update" in out and "is on it now" not in out, True)
    git(live, "config", "sclaude.update", "auto")

    # Removal keeps what was never published on its branch.
    head = git(ws, "rev-parse", "HEAD")
    ws_py("put", record, "start", json.dumps(git(origin, "rev-parse", "main")))
    out = sh('workshop_remove "%s"' % tree)
    check("removed", os.path.isdir(ws), False)
    check("record-removed", os.path.exists(record), False)
    check("kept-unpublished", "never published" in out, True)
    check("branch-kept", git(live, "rev-parse", "--verify", "-q", branch + "^{commit}", check_=False), head)

    # The prompt's paragraph, for the sessions that may: no question asked.
    mine = sh('workshop_rules "%s"' % tree)
    theirs = sh('workshop_rules "%s"' % tree, maintainer=False)
    check("rules-maintainer", "without a question" in mine and "/sreview" in mine, True)
    check("rules-other", "without a question" in theirs and "--review" in theirs, True)
    check("rules-no-tags", "<if:" in mine or "<if:" in theirs, False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

for name, got, want in failures:
    print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
print("ok" if not failures else "%d failed" % len(failures))
sys.exit(1 if failures else 0)
