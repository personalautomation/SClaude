#!/usr/bin/env python3
#
# A friction log of proposals alone is put off by sclaude itself.
#
# On one feature three friction reviews in a row were sessions whose whole work
# was one CLAUDE.md proposal appended to the deferred file — a decision the
# prompt makes in advance ("proposals always are" deferred). Guarded here:
#
#   * friction_proposals.py turns a log of proposals into deferred rows, class
#     included or defaulted, with their indented context;
#   * anything else in the log — a hook refusal, a free note — leaves it to a
#     session;
#   * friction_defer_proposals appends the rows to the product's deferred file
#     in the feature's worktree, created with its header when missing, commits
#     it on the feature's branch, and records the review in the state;
#   * run_friction asks it before the log moves and before any session opens.
#
# Run it with: python3 tests/friction-proposals.py
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


spec = importlib.util.spec_from_file_location(
    "friction_proposals", os.path.join(LIB, "friction_proposals.py"))
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)

# --- parsing ---------------------------------------------------------------
both = [
    "2026-10-09 proposal: A git option names the git version.\n",
    "  Drawn from #160: --diff-merges= (2.31)\n",
    "  and --porcelain (2.41).\n",
    "\n",
    "2026-10-09 proposal (claude-md-fix-every-call-site): Fix every call.\n",
]
got = fp.rows(both, "myapp", "145-x", "review")
check("two-rows", len(got or []), 2)
check("row-default-class", got[0].split("\t"),
      ["2026-10-09", "myapp", "145-x", "review", "claude-md-proposal",
       "Proposal: A git option names the git version. "
       "(Drawn from #160: --diff-merges= (2.31) and --porcelain (2.41).)"])
check("row-own-class", got[1].split("\t")[4], "claude-md-fix-every-call-site")
check("hook-entry-is-not-a-proposal", fp.rows(both + [
    "2026-10-09T04:55:34+01:00\treview\thook\tgit push origin main\n",
    "\tmain moves only by merging a pull request\n"], "s", "f", "review"), None)
check("free-note-is-not-a-proposal", fp.rows(
    ["subagent (review fixes #160): a scratch push was refused\n"], "s", "f", "r"), None)
check("unindented-tail-is-not-context", fp.rows(
    both[:1] + ["Drawn from nowhere\n"], "s", "f", "r"), None)
check("empty-is-not-proposals", fp.rows(["\n"], "s", "f", "r"), None)

# --- the deferral itself ----------------------------------------------------
with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()


def functions(source, names):
    out = []
    for name in names:
        m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
        if not m:
            failures.append(("function-present-" + name, True, False))
            continue
        out.append(m.group(0))
    return "\n".join(out)


DEFER = functions(RUN, ["friction_defer_proposals"])
tmp = tempfile.mkdtemp()
try:
    wt = os.path.join(tmp, "myapp-145-x")
    os.makedirs(os.path.join(wt, ".feature"))
    git = ["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "feat/145-x", wt], check=True)
    with open(os.path.join(wt, ".gitignore"), "w") as fh:
        fh.write(".feature/\n")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    # No `maintainers` in the product: everybody keeps team/.
    deferred = os.path.join(wt, ".sclaude", "team", "deferred", "145-x.tsv")
    state = os.path.join(wt, ".feature", "state.json")
    log = os.path.join(wt, ".feature", "friction.log")

    def defer():
        with open(state, "w") as fh:
            fh.write("{}")
        script = ('for m in state developer deferred; do source "%s/$m.sh"; done\n'
                  'LIB="%s"; REPO="%s/myapp"\ninfo() { :; }\n%s\n'
                  'export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t '
                  'GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t\n'
                  'friction_defer_proposals "%s" 145-x review-21 review; echo "rc=$?"'
                  % (LIB, LIB, tmp, DEFER, wt))
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr

    def commits():
        return int(subprocess.run(["git", "-C", wt, "rev-list", "--count", "HEAD"],
                                  capture_output=True, text=True).stdout)

    def rows():
        with open(deferred) as fh:
            return len([l for l in fh if l.startswith("2026-")])

    with open(log, "w") as fh:
        fh.writelines(both)
    check("defer-done", defer(), "rc=0")
    check("defer-committed-on-the-branch", commits(), 2)
    check("defer-file-in-the-product", os.path.exists(deferred), True)
    with open(deferred) as fh:
        check("defer-file-has-header", fh.readline().startswith("# Put off by sclaude"), True)
    check("defer-rows-written", rows(), 2)
    tree = subprocess.run(["git", "-C", wt, "show", "--name-only", "--format=", "HEAD"],
                          capture_output=True, text=True).stdout.split()
    check("defer-commit-holds-the-file", tree, [".sclaude/team/deferred/145-x.tsv"])
    with open(state) as fh:
        node = (json.load(fh).get("friction") or {}).get("review-21") or {}
    check("defer-state-verdict", node.get("verdict"), "deferred")
    check("defer-state-done", node.get("done"), True)

    check("defer-appends", defer(), "rc=0")
    check("defer-appended-rows", rows(), 4)
    check("defer-appended-commit", commits(), 3)

    with open(log, "a") as fh:
        fh.write("2026-10-09T05:00:00+01:00\treview\thook\tgit push origin main\n")
    check("defer-mixed-left-to-session", defer(), "rc=1")
    check("defer-mixed-writes-nothing", (rows(), commits()), (4, 3))

    # Somebody editing the file by hand: left to a session rather than mixed in.
    with open(log, "w") as fh:
        fh.writelines(both)
    with open(deferred, "a") as fh:
        fh.write("somebody editing\n")
    check("defer-dirty-file-left-to-session", defer(), "rc=1")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- where run_friction asks ------------------------------------------------
rf = RUN[RUN.index("\nrun_friction() {"):]
rf = rf[:rf.index("\n}\n")]
asked = rf.index('friction_defer_proposals "$wt"')
check("asked-after-lock", rf.index("lock_take FRICTION_LOCK") < asked, True)
check("asked-before-log-moves", asked < rf.index('cat "$log" >> "$reviewed" 2>/dev/null && rm -f "$log" || true'), True)
check("asked-before-session", asked < rf.index("session_holder"), True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
