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
got = fp.rows(both, "myapp", "45-x", "review")
check("two-rows", len(got or []), 2)
check("row-default-class", got[0].split("\t"),
      ["2026-10-09", "myapp", "45-x", "review", "claude-md-proposal",
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
    wt = os.path.join(tmp, "myapp-45-x")
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    git = ["git", "-C", wt, "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "feat/45-x", wt], check=True)
    with open(os.path.join(wt, ".gitignore"), "w") as fh:
        fh.write(".sclaude/local/feature/\n")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    # No `maintainers` in the product: everybody keeps team/.
    deferred = os.path.join(wt, ".sclaude", "team", "deferred", "45-x.tsv")
    state = os.path.join(wt, ".sclaude/local/feature", "state.json")
    log = os.path.join(wt, ".sclaude/local/feature", "friction.log")

    def defer(answer="y", fresh_state=True, ask=None, start="{}", asking=True, extra=None):
        if fresh_state:
            with open(state, "w") as fh:
                fh.write(start)
        ask = ask or 'ask() { printf -v "$2" %%s "%s"; }' % answer
        script = ('for m in state ui developer deferred; do source "%s/$m.sh"; done\n'
                  'LIB="%s"; REPO="%s/myapp"\ninfo() { :; }\nsay() { :; }\n'
                  '%s\n%s\n'
                  'export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t '
                  'GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t\n'
                  'friction_defer_proposals "%s" 45-x review-21 review; echo "rc=$? now=${FRICTION_APPLY_NOW:-}"'
                  % (LIB, LIB, tmp, ask, DEFER, wt))
        # The classification has a test of its own (friction-classify.py), with
        # a stub for the model; here it would call the real one.
        env = dict(os.environ, SCLAUDE_FRICTION_ASK="on" if asking else "off",
                   SCLAUDE_FRICTION_CLASSIFY="off")
        env.update(extra or {})
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr

    def commits():
        return int(subprocess.run(["git", "-C", wt, "rev-list", "--count", "HEAD"],
                                  capture_output=True, text=True).stdout)

    def rows():
        with open(deferred) as fh:
            return len([l for l in fh if l.startswith("2026-")])

    with open(log, "w") as fh:
        fh.writelines(both)
    # An earlier review's answer left on the node would be read as this one's.
    check("defer-done", defer(start='{"friction": {"review-21": {"empty": true, "was": "abcd1234"}}}').split()[0], "rc=0")
    check("defer-committed-on-the-branch", commits(), 2)
    check("defer-file-in-the-product", os.path.exists(deferred), True)
    with open(deferred) as fh:
        check("defer-file-only-entries", all(l.startswith("2026-") or l.startswith("\t")
                                             for l in fh if l.strip()), True)
    check("defer-rows-written", rows(), 2)
    tree = subprocess.run(["git", "-C", wt, "show", "--name-only", "--format=", "HEAD"],
                          capture_output=True, text=True).stdout.split()
    check("defer-commit-holds-the-file", tree, [".sclaude/team/deferred/45-x.tsv"])
    with open(state) as fh:
        node = (json.load(fh).get("friction") or {}).get("review-21") or {}
    check("defer-state-verdict", node.get("verdict"), "deferred")
    check("defer-state-done", node.get("done"), True)
    check("defer-clears-an-earlier-answer", (node.get("empty"), node.get("was")), (None, None))

    # Each put-off of the key is a review of its own: the key stands for every
    # round of a fix session, and its state kept only the last one.
    check("defer-appends", defer(fresh_state=False).split()[0], "rc=0")
    check("defer-appended-rows", rows(), 4)
    check("defer-appended-commit", commits(), 3)
    subjects = subprocess.run(["git", "-C", wt, "log", "-2", "--format=%s"],
                              capture_output=True, text=True).stdout.split("\n")[:2]
    check("defer-each-review-its-number", [x.rsplit(", ", 1)[-1] for x in subjects],
          ["review 2", "review 1"])
    with open(state) as fh:
        runs = ((json.load(fh).get("friction") or {}).get("review-21") or {}).get("runs") or []
    check("defer-each-review-a-run", [bool(r.get("done")) for r in runs], [True, True])

    # Asked first: "n" puts nothing off and leaves the log to a review that
    # writes the rules into CLAUDE.md now.
    with open(log, "w") as fh:
        fh.writelines(both)
    check("defer-declined-left-to-session", defer(answer="n"), "rc=1 now=1")
    check("defer-declined-writes-nothing", (rows(), commits()), (4, 3))
    # Kept for a review that is interrupted and opened again as a new session.
    with open(state) as fh:
        check("defer-declined-remembered",
              ((json.load(fh).get("friction") or {}).get("review-21") or {}).get("apply_now"), True)
    # No answer at all is not a "no": they are put off, as before the question.
    out = defer(ask="ask() { return 1; }")
    check("defer-unanswered-puts-off", out.split(), ["rc=0", "now="])
    check("defer-unanswered-rows", rows(), 6)
    with open(log, "w") as fh:
        fh.writelines(both)

    # Not asked by default: the question held the cycle until it was answered,
    # and the answer was always the same.
    out = defer(ask='ask() { echo ASKED; printf -v "$2" n; }', asking=False)
    check("defer-not-asked-by-default", out.split(), ["rc=0", "now="])
    check("defer-not-asked-rows", rows(), 8)
    with open(log, "w") as fh:
        fh.writelines(both)

    with open(log, "a") as fh:
        fh.write("2026-10-09T05:00:00+01:00\treview\thook\tgit push origin main\n")
    check("defer-mixed-left-to-session", defer().split()[0], "rc=1")
    check("defer-mixed-writes-nothing", (rows(), commits()), (8, 5))

    # Matched against CLAUDE.md first: proposals it already states are put off
    # under a class of their own, never dropped.
    with open(log, "w") as fh:
        fh.writelines(both)
    with open(os.path.join(wt, "CLAUDE.md"), "w") as fh:
        fh.write("- Main moves only by merging a pull request, never by a push.\n")
    stub_bin = os.path.join(tmp, "stub-bin")
    os.makedirs(stub_bin, exist_ok=True)
    with open(os.path.join(stub_bin, "claude"), "w") as fh:
        fh.write("#!/bin/sh\necho '%s'\n" % json.dumps(
            [{"n": i, "verdict": "covered", "quote": "Main moves only by merging a pull request"}
             for i in (1, 2, 3)]))
    os.chmod(os.path.join(stub_bin, "claude"), 0o755)
    out = defer(asking=False, extra={"SCLAUDE_FRICTION_CLASSIFY": "on",
                                     "PATH": stub_bin + ":" + os.environ["PATH"]})
    check("defer-covered-decided", out.split()[0], "rc=0")
    check("defer-covered-kept", (rows(), commits()), (10, 6))
    with open(deferred) as fh:
        check("defer-covered-class", sum(1 for l in fh if "\tclaude-md-already-stated\t" in l), 2)
    os.remove(os.path.join(wt, "CLAUDE.md"))

    # Somebody editing the file by hand: left to a session rather than mixed in.
    with open(log, "w") as fh:
        fh.writelines(both)
    with open(deferred, "a") as fh:
        fh.write("somebody editing\n")
    check("defer-dirty-file-left-to-session", defer().split()[0], "rc=1")
    subprocess.run(["git", "-C", wt, "checkout", "-q", "--", deferred], check=True)

    # The product's hooks refuse the commit. The file goes back to how it was,
    # or the session that takes over appends the same rows again.
    hooks = os.path.join(wt, ".git", "hooks")
    os.makedirs(hooks, exist_ok=True)
    refuse = os.path.join(hooks, "commit-msg")
    with open(refuse, "w") as fh:
        fh.write("#!/bin/sh\nexit 1\n")
    os.chmod(refuse, 0o755)
    before = open(deferred).read()
    check("refused-tracked-left-to-session", defer().split()[0], "rc=1")
    check("refused-tracked-restored", open(deferred).read(), before)
    # A feature with no file of its own yet: the file made for the rows goes.
    fresh = os.path.join(wt, ".sclaude", "team", "deferred", "146-y.tsv")
    script = ('for m in state developer deferred; do source "%s/$m.sh"; done\n'
              'LIB="%s"; REPO="%s/myapp"\ninfo() { :; }\n%s\n'
              'friction_defer_proposals "%s" 146-y review-3 review; echo "rc=$?"'
              % (LIB, LIB, tmp, DEFER, wt))
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                  GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
    check("refused-new-left-to-session", out.stdout.strip().splitlines()[-1:], ["rc=1"])
    check("refused-new-file-gone", os.path.exists(fresh), False)
    os.remove(refuse)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- where run_friction asks ------------------------------------------------
rf = RUN[RUN.index("\nrun_friction() {"):]
rf = rf[:rf.index("\n}\n")]
asked = rf.index('friction_defer_proposals "$wt"')
# Reviews no longer queue for sclaude's checkout: each works in its own
# feature's worktree.
check("no-friction-queue", "lock_take" in rf, False)
# Most reviews defer nothing, and a file made empty beforehand stood in the
# worktree as uncommitted work. Only its folder is made, which git ignores.
check("review-does-not-create-the-file", "deferred_ensure" in rf, False)
check("asked-before-log-moves", asked < rf.index('cat "$log" >> "$reviewed" 2>/dev/null && rm -f "$log" || true'), True)
check("asked-before-session", asked < rf.index("session_holder"), True)
# A review reads its own entries, kept apart as they were moved: .reviewed
# holds every review's, and the review after step 2 read step 1's again.
check("review-reads-its-own-batch",
      ('cp "$log" "$batch"' in rf, '-e "s|<log>|$reading|g"' in rf,
       'reading="$batch"' in rf, "<log>|$reviewed|" in rf), (True, True, True, False))
# Told to write the proposals in now when the person said so.
check("now-survives-an-interruption",
      'state_get "$state" "friction.$key.apply_now"' in rf
      and "re-read $reading if you need to" in rf, True)
check("now-told-to-the-review",
      rf.index('FRICTION_APPLY_NOW=""') < asked and "I asked for this log's proposals" in rf, True)

# A put-off has no session: the issue's column shows no id for it.
with open(os.path.join(LIB, "github.sh")) as fh:
    check("put-off-shown-without-an-id",
          '.startswith("deferred-"):\n            earlier.append("put off")' in fh.read(), True)
with open(os.path.join(LIB, "github.sh")) as fh:
    check("latest-put-off-says-so",
          'if node.get("verdict") == "deferred":\n            # Put off by sclaude with no session (friction_defer_proposals).\n            return "put off"' in fh.read(), True)
check("new-session-clears-the-verdict", "for flag in empty fixed unread verdict verdict_note; do" in rf, True)

# --- every variable run_friction reads, it sets -----------------------------
#
# bin/sclaude runs under `set -u`. A review that stopped committing to sclaude
# lost its `before`/`after` HEADs, and the line still reading them killed
# sclaude after every review that fixed something, before the review's result
# reached the state. Nothing runs run_friction whole, so this reads it: a
# lowercase name (a local, by this code's habit) read but never assigned.
code = "\n".join(l for l in rf.splitlines() if not l.lstrip().startswith("#"))
code = re.sub(r"<<'PY'.*?\nPY", "", code, flags=re.S)
read_names = set(re.findall(r"\$\{?([a-z_][a-z0-9_]*)", code))
set_names = set(re.findall(r"\b([a-z_][a-z0-9_]*)=", code))
for m in re.finditer(r"\blocal(?:\s+-\w+)?\s+([^\n;|&]+)", code):
    set_names |= set(re.findall(r"\b([a-z_][a-z0-9_]*)\b", m.group(1)))
set_names |= set(re.findall(r"\bfor\s+([a-z_][a-z0-9_]*)\s+in", code))
check("friction-reads-only-what-it-sets", sorted(read_names - set_names), [])

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
