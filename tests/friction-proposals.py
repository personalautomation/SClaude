#!/usr/bin/env python3
#
# A friction log of proposals alone is put off by sclaude itself.
#
# On feature 145 three friction reviews in a row were sessions whose whole work
# was one CLAUDE.md proposal appended to the deferred file — a decision the
# prompt makes in advance ("proposals always are" deferred). Guarded here:
#
#   * friction_proposals.py turns a log of proposals into deferred rows, class
#     included or defaulted, with their indented context;
#   * anything else in the log — a hook refusal, a free note — leaves it to a
#     session;
#   * friction_defer_proposals appends the rows to the deferred file — local
#     state outside instruments, created with its header when missing — and
#     records the review in the state; it commits nothing;
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
got = fp.rows(both, "social", "145-x", "review")
check("two-rows", len(got or []), 2)
check("row-default-class", got[0].split("\t"),
      ["2026-10-09", "social", "145-x", "review", "claude-md-proposal",
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
with open(os.path.join(LIB, "deferred.sh")) as fh:
    ENSURE = functions(fh.read(), ["deferred_ensure"])
tmp = tempfile.mkdtemp()
try:
    inst = os.path.join(tmp, "instruments")
    wt = os.path.join(tmp, "social-145-x")
    os.makedirs(os.path.join(inst, "sclaude"))
    os.makedirs(os.path.join(wt, ".feature"))
    git = ["git", "-C", inst, "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", inst], check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True)
    deferred = os.path.join(tmp, "state", "sclaude", "friction-deferred.tsv")
    state = os.path.join(wt, ".feature", "state.json")
    log = os.path.join(wt, ".feature", "friction.log")

    def defer():
        with open(state, "w") as fh:
            fh.write("{}")
        script = ('source "%s/state.sh"\nLIB="%s"; INSTRUMENTS="%s"; REPO="%s/social"\n'
                  'DEFERRED_FILE="%s"\ninfo() { :; }\n%s\n%s\n'
                  'friction_defer_proposals "%s" 145-x review-21 review; echo "rc=$?"'
                  % (LIB, LIB, inst, tmp, deferred, ENSURE, DEFER, wt))
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr

    def commits():
        return int(subprocess.run(["git", "-C", inst, "rev-list", "--count", "HEAD"],
                                  capture_output=True, text=True).stdout)

    def rows():
        with open(deferred) as fh:
            return len([l for l in fh if l.startswith("2026-")])

    with open(log, "w") as fh:
        fh.writelines(both)
    check("defer-done", defer(), "rc=0")
    check("defer-commits-nothing", commits(), 1)
    check("defer-file-outside-instruments", os.path.exists(deferred), True)
    with open(deferred) as fh:
        check("defer-file-has-header", fh.readline().startswith("# Friction"), True)
    check("defer-rows-written", rows(), 2)
    with open(state) as fh:
        node = (json.load(fh).get("friction") or {}).get("review-21") or {}
    check("defer-state-verdict", node.get("verdict"), "deferred")
    check("defer-state-done", node.get("done"), True)
    check("defer-state-no-range", node.get("from") or node.get("to"), None)

    check("defer-appends", defer(), "rc=0")
    check("defer-appended-rows", rows(), 4)

    with open(log, "a") as fh:
        fh.write("2026-10-09T05:00:00+01:00\treview\thook\tgit push origin main\n")
    check("defer-mixed-left-to-session", defer(), "rc=1")
    check("defer-mixed-writes-nothing", rows(), 4)
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
