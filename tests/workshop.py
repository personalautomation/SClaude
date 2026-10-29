#!/usr/bin/env python3
#
# The workshop (sclaude/lib/workshop.sh, workshop.py): where a session changes
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
PY = os.path.join(LIB, "workshop.py")

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
    ws_py("pending", rec, "s1", "/some/cwd", "--session-id", "s1", "-n", "x", "the prompt")
    out = ws_py("pending-args", rec).stdout.split("\0")
    check("pending-args", out[:5], ["/some/cwd", "--session-id", "s1", "-n", "x"])

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
INSTRUMENTS=%(live)s; LIB=%(lib)s; PROMPTS=%(root)s/sclaude/prompts
source "$LIB/ui.sh"; source "$LIB/pane.sh"; source "$LIB/workshop.sh"; source "$LIB/run.sh"
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
    check("state-none", sh('workshop_state "%s" s1' % tree).strip(), "none")
    check("after-nothing", sh('workshop_after_session s1 --session-id s1 -n x p').strip(), "")

    # Made and not ready: the session is offered back; a "no" leaves it pending.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("echo more\n")
    check("ready-refuses-dirty", "DIE" in sh("cmd_core_ready"), True)
    git(ws, "commit", "-qam", "feat(sclaude): the tool says more")
    check("ready-refuses-without-sreview", "sreview has not finished" in sh("cmd_core_ready"), True)
    check("state-unready", sh('workshop_state "%s" s1' % tree).strip(), "unready")
    out = sh('workshop_after_session s1 --session-id s1 --model opus -n x "the prompt"', answer="n")
    check("after-unready-asks", "ASK" in out and "RELAUNCH" not in out, True)
    check("after-unready-names-the-mark", "sreview's mark" in out, True)
    check("after-unready-pending", ws_py("get", record, "pending.session").stdout.strip(), "s1")
    check("state-pending-for-other", sh('workshop_state "%s" s2' % tree).strip(), "pending")
    # A "yes" resumes the same session, with its arguments and a new word.
    out = sh('workshop_after_session s1 --session-id s1 --model opus -n x "the prompt"', answer="y n")
    check("after-yes-resumes", "RELAUNCH --resume s1 --model opus -n x" in out, True)
    check("after-yes-says-what-is-missing", "What is missing: sreview's mark" in out, True)
    check("after-yes-asks-again", out.count("ASK"), 2)

    # Sent back from the next opening, the record stays until it is finished:
    # a run cut off after the session would otherwise forget it.
    out = sh('claude_launch() { echo "LAUNCH $*"; }; workshop_pending "%s"' % tree, answer="y")
    check("pending-resumed", "LAUNCH --resume s1" in out and "Missing:" in out, True)
    check("pending-kept-while-resumed", ws_py("get", record, "pending.session").stdout.strip(), "s1")
    # A session whose directory is gone cannot be sent back: said, and dropped.
    ws_py("pending", record, "s1", "/no/such/dir", "--session-id", "s1", "-n", "x", "p")
    out = sh('claude_launch() { echo "LAUNCH $*"; }; workshop_pending "%s"' % tree, answer="n")
    check("pending-gone-dir-said", "is gone" in out and "LAUNCH" not in out and "ASK" not in out, True)
    check("pending-gone-dir-dropped", ws_py("get", record, "pending.session").returncode, 1)
    # Unfinished with no session recorded is still said.
    ws_py("put", record, "pending", "null")
    out = sh('workshop_pending "%s"' % tree)
    check("unfinished-without-record-said", "no session is" in out and "Missing:" in out, True)
    ws_py("pending", record, "s1", "/some/cwd", "--session-id", "s1", "-n", "x", "p")

    # sreview's mark at the head makes it ready for a maintainer.
    common = git(ws, "rev-parse", "--path-format=absolute", "--git-common-dir")
    branch = git(ws, "rev-parse", "--abbrev-ref", "HEAD")
    mark = os.path.join(common, "sreview", "branches", branch + ".reviewed")
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    with open(mark, "w") as fh:
        fh.write(git(ws, "rev-parse", "HEAD") + "\n")
    ws_py("put", record, "pending", "null")
    out = sh("cmd_core_ready")
    check("ready-with-mark", "Ready" in out, True)
    check("state-ready", sh('workshop_state "%s" s1' % tree).strip(), "ready")

    # A second commit: squashed into one on publication, and the tests the
    # change touches run.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("echo again\n")
    git(ws, "commit", "-qam", "fix(sclaude): review iteration 1 — say it again\n\nCo-Authored-By: X <x@x>")
    with open(mark, "w") as fh:
        fh.write(git(ws, "rev-parse", "HEAD") + "\n")
    sh("cmd_core_ready")
    out = sh('workshop_after_session s1 --session-id s1 -n x p')
    check("published-to-main", "Published to sclaude's main" in out, True)
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
    check("state-none-after", sh('workshop_state "%s" s1' % tree).strip(), "none")

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
    out = sh('workshop_after_session s1 --session-id s1 -n x p', answer="n")
    check("leak-asked", "may name the product" in out and "ASK" in out, True)
    check("leak-not-published", git(origin, "rev-parse", "main"), before)
    # A "yes" holds for the same change: a retry does not ask it again.
    out = sh('workshop_leaks "%s" origin/main "%s" && echo PASSED' % (ws, tree), answer="y")
    check("leak-yes-asked", "ASK" in out and "PASSED" in out, True)
    out = sh('workshop_leaks "%s" origin/main "%s" && echo PASSED' % (ws, tree), answer="n")
    check("leak-yes-remembered", "ASK" not in out and "PASSED" in out, True)
    # A new line naming the product is asked about, though the diff is the same.
    git(ws, "commit", "-q", "--allow-empty", "-m", "fix(sclaude): as seen in issue #77")
    out = sh('workshop_leaks "%s" origin/main "%s" && echo PASSED' % (ws, tree), answer="n")
    check("leak-new-line-asked", "ASK" in out and "PASSED" not in out, True)
    git(ws, "reset", "-q", "--hard", "HEAD~1")
    ws_py("put", record, "leaks_ok", "null")
    # A list too long for a question on the phone is asked at the terminal
    # alone; nobody there is no answer, and nothing is held.
    git(ws, "commit", "-q", "--allow-empty", "-m", "fix(sclaude): long",
        "-m", "\n".join("seen in issue #%d of myshop, %s" % (n, "x" * 60) for n in range(40)))
    out = sh('ASK_DIR=/somewhere; ask() { echo "ASK dir=[$ASK_DIR]"; return 1; }; '
             'workshop_leaks "%s" origin/main "%s"; echo "rc=$?"' % (ws, tree))
    check("long-list-at-terminal", "ASK dir=[]" in out and "answer it here" in out, True)
    check("long-list-unanswered-not-held", "rc=2" in out, True)
    git(ws, "reset", "-q", "--hard", "HEAD~1")
    # The person's "no" holds it: asking again on every opening would not help.
    check("leak-no-held", sh('workshop_state "%s" ""' % tree).strip(), "blocked")
    out = sh('workshop_pending "%s"' % tree)
    check("leak-no-not-asked-again", "waits" in out and "ASK" not in out, True)

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
    # A push that failed is not taken for sent: the change stays ready.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("# and once more\n")
    git(ws, "commit", "-qam", "fix(sclaude): once more")
    start = ws_py("get", record, "start").stdout.strip()
    ws_py("ready", record, "s1", git(ws, "rev-parse", "HEAD"), "a read")
    out = sh('instruments_propose() { return 2; }; workshop_publish "%s"' % tree, maintainer=False)
    check("failed-push-not-sent", ws_py("get", record, "start").stdout.strip(), start)
    check("failed-push-stopped-on-the-way", ws_py("get", record, "stopped").stdout.strip(), "on the way")
    check("failed-push-stays-ready", sh('workshop_state "%s" ""' % tree).strip(), "ready")
    check("failed-push-unpublished", sh('workshop_unpublished "%s" && echo yes' % tree).strip(), "yes")
    # And it is tried again when the tree is next opened.
    out = sh('workshop_pending "%s"' % tree, maintainer=False)
    check("ready-retried-on-entry", "PROPOSE" in out, True)
    # No gh, or no login, is tried again too: it may be fixed meanwhile.
    with open(os.path.join(ws, "sclaude", "lib", "tool.sh"), "a") as fh:
        fh.write("# and again\n")
    git(ws, "commit", "-qam", "fix(sclaude): and again")
    ws_py("ready", record, "s1", git(ws, "rev-parse", "HEAD"), "a read")
    out = sh('instruments_propose() { return 1; }; workshop_publish "%s"' % tree, maintainer=False)
    check("no-gh-stays-ready", sh('workshop_state "%s" ""' % tree).strip(), "ready")
    check("no-gh-said", "tried again" in out, True)

    # A maintainer's publication stopped by red tests after the squash leaves
    # the squashed head ready, to be tried again rather than taken for an
    # unfinished change.
    git(ws, "reset", "-q", "--hard", "origin/main")
    ws_py("put", record, "start", json.dumps(git(ws, "rev-parse", "HEAD")))
    for n in (1, 2):
        with open(os.path.join(ws, "tests", "tool.py"), "w") as fh:
            fh.write("# checks tool\nimport sys\nsys.exit(%d)\n" % n)
        git(ws, "commit", "-qam", "fix(sclaude): tool test %d" % n)
    ws_py("ready", record, "s1", git(ws, "rev-parse", "HEAD"), "sreview")
    out = sh('workshop_publish "%s"' % tree)
    check("red-not-published", "Red:" in out and "Published" not in out, True)
    check("red-test-named", "✗ tool.py" in out, True)
    check("red-squashed-head-ready", ws_py("get", record, "ready.head").stdout.strip(),
          git(ws, "rev-parse", "HEAD"))
    check("red-stays-ready", sh('workshop_state "%s" ""' % tree).strip(), "ready")
    check("red-not-on-the-way", ws_py("get", record, "stopped").returncode, 1)
    out = sh('workshop_pending "%s"' % tree)
    check("red-retried-on-entry", "Testing sclaude itself" in out, True)
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
    out = sh('source "$LIB/steps.sh"; a="$(instruments_state)"; '
             'git -C "%s" config branch.dev/ann-1.remote origin; git -C "%s" remote add fork /tmp/f; '
             'b="$(instruments_state)"; [[ "$a" == "$b" ]] && echo same' % (ws, ws))
    check("config-workshop-records-ignored", out.strip().endswith("same"), True)
    # Where origin points is still sclaude's own business.
    out = sh('source "$LIB/steps.sh"; a="$(instruments_state)"; '
             'git -C "%s" remote set-url origin /tmp/elsewhere; '
             'b="$(instruments_state)"; [[ "$a" == "$b" ]] && echo same || echo moved' % live)
    check("config-origin-counted", out.strip().endswith("moved"), True)
    git(live, "remote", "set-url", "origin", origin)

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
