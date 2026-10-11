#!/usr/bin/env python3
#
# A pull request from draft to merge: what sclaude does to it around QA.
#
#   * pr_handoff.py finds the PR's issues — the closing references, plus the
#     feature's own issue when GitHub has not linked it;
#   * the milestone comes from those issues: one is taken, an issue with none
#     is no candidate, two are asked about, and one already on the PR stays;
#   * pr_setup makes a new PR a draft assigned to its author, once per PR;
#   * pr_qa_handoff waits for every issue to be in Done, then marks the PR
#     ready, moves it to the backlog column, clears its assignees and posts the
#     summary — once per head;
#   * the summary says where the review did not finish, so zero findings is
#     not read as a clean review;
#   * remind_prod hands over after QA's yes and puts a merged PR in Done.
#
# Driven with a fake `gh` on PATH that answers from a table and logs each call.
#
# Run it with: python3 tests/pr-handoff.py
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


def functions(path, names):
    source = open(path, encoding="utf-8").read()
    out = []
    for name in names:
        m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
        if not m:
            failures.append(("function-present-" + name, True, False))
            continue
        out.append(m.group(0))
    return "\n".join(out)


# The fake gh: the first pattern matching the joined arguments answers.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, re, sys
args = " ".join(sys.argv[1:])
with open(os.environ["FAKE_LOG"], "a") as fh:
    fh.write(args + "\n")
for pattern, out, code in json.load(open(os.environ["FAKE_TABLE"])):
    if re.search(pattern, args):
        sys.stdout.write(out)
        sys.exit(code)
sys.exit(1)
'''

tmp = tempfile.mkdtemp()
bindir = os.path.join(tmp, "bin")
os.makedirs(bindir)
with open(os.path.join(bindir, "gh"), "w") as fh:
    fh.write(FAKE_GH)
os.chmod(os.path.join(bindir, "gh"), 0o755)
LOG = os.path.join(tmp, "gh.log")
TABLE = os.path.join(tmp, "table.json")
WT = os.path.join(tmp, "wt")
os.makedirs(os.path.join(WT, ".sclaude/local/feature"))
STATE = os.path.join(WT, ".sclaude/local/feature", "state.json")


def setup(table, state=None):
    with open(TABLE, "w") as fh:
        json.dump([[p, o if isinstance(o, str) else json.dumps(o), c]
                   for p, o, c in table], fh)
    open(LOG, "w").close()
    with open(STATE, "w") as fh:
        json.dump(state or {"issue": 7}, fh)


def calls():
    return open(LOG).read().splitlines()


ENV = dict(os.environ, PATH=bindir + ":" + os.environ["PATH"],
           FAKE_LOG=LOG, FAKE_TABLE=TABLE)


def py(*args):
    return subprocess.run([sys.executable, os.path.join(LIB, "pr_handoff.py")] + list(args),
                          capture_output=True, text=True, env=ENV, timeout=60).stdout


REPO = [r"^repo view", {"nameWithOwner": "o/r"}, 0]
CLOSES = [r"closingIssuesReferences", {"closingIssuesReferences": [{"number": 5}, {"number": 7}]}, 0]


def issue(n, milestone):
    return [r"^api repos/o/r/issues/%d$" % n,
            {"number": n, "milestone": {"title": milestone} if milestone else None}, 0]


# --- tickets -----------------------------------------------------------------
setup([CLOSES])
check("tickets-linked-own", py("tickets", WT, "40", "7").split(), ["5", "7"])
check("tickets-unlinked-own", py("tickets", WT, "40", "9").split(), ["5", "7", "9"])
setup([])
check("tickets-unreadable", py("tickets", WT, "40", "9").split(), ["9"])

# --- milestones --------------------------------------------------------------
setup([REPO, CLOSES, issue(5, "v1"), issue(7, "")])
check("milestone-empty-not-candidate", py("milestones", WT, "40", "7"), "v1\t#5\n")
setup([REPO, CLOSES, issue(5, "v1"), issue(7, "v2")])
check("milestones-disagree", py("milestones", WT, "40", "7"), "v1\t#5\nv2\t#7\n")

HARNESS = "\n".join([
    "set -u",
    "LIB=%s" % LIB,
    'BOLD="" DIM="" OFF="" GREEN=""',
    'say() { echo "SAY $*"; }; info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }',
    'ask() { echo "ASK $1"; printf -v "$2" "%s" "${FAKE_ANSWER:-}"; }',
    "gh_repo() { echo o/r; }",
    functions(os.path.join(LIB, "state.sh"), ["state_get", "state_set"]),
    functions(os.path.join(LIB, "project.sh"), ["column_is"]),
    functions(os.path.join(LIB, "github.sh"),
              ["pr_milestone", "pr_setup", "issue_status_items", "issue_status_now",
               "pr_board_set", "pr_qa_handoff", "pr_qa_handoff_now"]),
    'QA_DONE=Done PROGRESS_FROM=Backlog PROGRESS_TO="In progress"',
])


def sh(body, **extra):
    return subprocess.run(["bash", "-c", HARNESS + "\n" + body], capture_output=True,
                          text=True, env=dict(ENV, **extra), timeout=60).stdout


PR_MS_NONE = [r"^api repos/o/r/issues/40 --jq", "\n", 0]
EDIT_OK = [r"^pr edit", "", 0]

setup([REPO, CLOSES, issue(5, "v1"), issue(7, ""), PR_MS_NONE, EDIT_OK])
sh('pr_milestone "%s" 40' % WT)
check("milestone-one-set", [c for c in calls() if c.startswith("pr edit")],
      ["pr edit 40 --milestone v1"])

setup([REPO, CLOSES, issue(5, "v1"), issue(7, "v2"), PR_MS_NONE, EDIT_OK])
out = sh('pr_milestone "%s" 40' % WT, FAKE_ANSWER="2")
check("milestone-conflict-asked", "ASK Which milestone" in out, True)
check("milestone-conflict-chosen", [c for c in calls() if c.startswith("pr edit")],
      ["pr edit 40 --milestone v2"])

setup([REPO, CLOSES, issue(5, "v1"), issue(7, "v2"), PR_MS_NONE, EDIT_OK])
sh('pr_milestone "%s" 40' % WT, FAKE_ANSWER="")
check("milestone-conflict-unanswered", [c for c in calls() if c.startswith("pr edit")], [])

setup([REPO, CLOSES, issue(5, "v1"), [r"^api repos/o/r/issues/40 --jq", "kept\n", 0],
       issue(7, ""), EDIT_OK])
sh('pr_milestone "%s" 40' % WT)
check("milestone-own-kept", [c for c in calls() if c.startswith("pr edit")], [])

# --- pr_setup ----------------------------------------------------------------
setup([REPO, CLOSES, issue(5, ""), issue(7, ""), PR_MS_NONE, EDIT_OK,
       [r"^pr view 40 --repo o/r --json state,isDraft", "OPEN\tfalse\tdev1\t0\n", 0],
       [r"^pr ready", "", 0]])
sh('pr_setup "%s" 40' % WT)
check("setup-draft", "pr ready 40 --repo o/r --undo" in calls(), True)
check("setup-assignee", "pr edit 40 --repo o/r --add-assignee dev1" in calls(), True)
open(LOG, "w").close()
sh('pr_setup "%s" 40' % WT)
check("setup-once", calls(), [])

# --- pr_qa_handoff -----------------------------------------------------------


def board(status):
    return {"data": {"repository": {"issueOrPullRequest": {"projectItems": {"nodes": [{
        "id": "ITEM", "project": {"id": "PROJ", "title": "agoramove"},
        "fieldValueByName": {"name": status, "field": {"id": "F", "options": [
            {"id": "OB", "name": "Backlog"}, {"id": "OD", "name": "Done"}]}}}]}}}}}


def handoff_table(status5, status7):
    return [REPO, CLOSES,
            [r"^pr view 40 --repo o/r --json state,headRefOid", "OPEN\tabc123\ttrue\n", 0],
            [r"number=5 ", board(status5), 0],
            [r"number=7 ", board(status7), 0],
            [r"number=40 ", board("In progress"), 0],
            [r"^pr ready", "", 0], [r"^project item-edit", "", 0],
            [r"--json assignees", "dev1\n", 0], EDIT_OK,
            [r"^pr view 40 --json headRefOid,statusCheckRollup",
             {"headRefOid": "abc123", "statusCheckRollup": []}, 0],
            [r"^api --paginate repos/o/r/issues/40/comments", "", 0],
            [r"^api repos/o/r/issues/40/comments", "{}", 0]]


# gh graphql passes the number with -F; give the fake something to match on.
for_number = 'gh() { local a=("$@"); for i in "${!a[@]}"; do [[ "${a[$i]}" == number=* ]] && a[$i]="${a[$i]} "; done; command gh "${a[@]}"; }'

setup(handoff_table("Done", "In QA"))
out = sh(for_number + '\npr_qa_handoff "%s" 40 7; echo "rc=$?"' % WT)
check("handoff-waits-for-all", "rc=1" in out, True)
check("handoff-names-waiting", "#7 (In QA)" in out, True)
check("handoff-waiting-no-ready", any(c.startswith("pr ready") for c in calls()), False)

setup(handoff_table("Done", "Done"))
out = sh(for_number + '\npr_qa_handoff "%s" 40 7; echo "rc=$?"' % WT)
log = calls()
check("handoff-done", "rc=0" in out, True)
check("handoff-ready", "pr ready 40 --repo o/r" in log, True)
check("handoff-backlog", any(c.startswith("project item-edit") and "OB" in c for c in log), True)
check("handoff-unassign", "pr edit 40 --repo o/r --remove-assignee dev1" in log, True)
check("handoff-comment", any(c.startswith("api repos/o/r/issues/40/comments --input") for c in log), True)
check("handoff-head-recorded", json.load(open(STATE)).get("handoff"), "abc123")
open(LOG, "w").close()
sh(for_number + '\npr_qa_handoff "%s" 40 7' % WT)
check("handoff-once-per-head", [c for c in calls() if not c.startswith("pr view")], [])
out = sh(for_number + '\npr_qa_handoff "%s" 40 7; echo "rc=$?"' % WT)
check("handoff-before-is-3", "rc=3" in out, True)

# A step that warns leaves the head unrecorded, so the next look repeats it.
table = handoff_table("Done", "Done")
table.insert(0, [r"^project item-edit", "", 1])
setup(table)
out = sh(for_number + '\npr_qa_handoff "%s" 40 7; echo "rc=$?"' % WT)
check("handoff-partial-is-4", "rc=4" in out, True)
check("handoff-partial-not-recorded", json.load(open(STATE)).get("handoff"), None)

# A merged PR can never be handed over: 2, not "try again".
table = handoff_table("Done", "Done")
table.insert(0, [r"^pr view 40 --repo o/r --json state,headRefOid", "MERGED\tabc123\tfalse\n", 0])
setup(table)
out = sh(for_number + '\npr_qa_handoff "%s" 40 7; echo "rc=$?"' % WT)
check("handoff-merged-is-2", "rc=2" in out, True)

# --- the summary -------------------------------------------------------------
setup([REPO,
       [r"^pr view 40 --json headRefOid,statusCheckRollup",
        {"headRefOid": "abc1234567", "statusCheckRollup": [
            {"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "review", "status": "COMPLETED", "conclusion": "FAILURE"}]}, 0],
       [r"reviewThreads", {"data": {"repository": {"pullRequest": {"reviewThreads": {
           "pageInfo": {"hasNextPage": False},
           "nodes": [{"isResolved": True}, {"isResolved": True}, {"isResolved": False}]}}}}}, 0],
       [r"check-runs", {"check_runs": []}, 0],
       [r"^issue view", {"body": "", "comments": []}, 0]],
      {"issue": 7, "qa_returns": 2,
       "regression": {"local": {"status": "passed"},
                      "preview": {"status": "passed", "url": "https://pre.example"}}})
text = py("summary", WT, "40", STATE, "Done", "7")
check("summary-marker", text.startswith("<!-- sclaude:merge-ready -->"), True)
check("summary-preview", "https://pre.example" in text, True)
check("summary-returns", "| Returned to development | 2 times |" in text, True)
check("summary-findings", "3 found, 2 resolved, 1 open" in text, True)
check("summary-review-not-run", "never looked" in text, True)
check("summary-red-check", "red: review" in text, True)
check("summary-regression", "local ✓ passed · preview ✓ passed" in text, True)

# --- the timer ---------------------------------------------------------------
# A copy of the watcher beside a fake sclaude and sclaude-notify: it finds both
# next to itself.
wbin = os.path.join(tmp, "watchbin")
os.makedirs(wbin)
shutil.copy(os.path.join(ROOT, "bin", "sclaude-watch"), wbin)
with open(os.path.join(wbin, "sclaude"), "w") as fh:
    fh.write('#!/usr/bin/env bash\necho "$PWD $*" >> "$FAKE_SCLAUDE_LOG"\n'
             'echo "${FAKE_SCLAUDE_SAYS:-}"\nexit "${FAKE_SCLAUDE_RC:-0}"\n')
with open(os.path.join(wbin, "sclaude-notify"), "w") as fh:
    fh.write('#!/usr/bin/env bash\nprintf "%s\\n---\\n" "$*" >> "$FAKE_NOTIFY_LOG"\n')
for name in ("sclaude", "sclaude-notify"):
    os.chmod(os.path.join(wbin, name), 0o755)
home = os.path.join(tmp, "home")
wdir = os.path.join(home, ".claude", "sclaude", "watch")
os.makedirs(wdir)
WFILE = os.path.join(wdir, "demo.json")
SLOG, NLOG = os.path.join(tmp, "sclaude.log"), os.path.join(tmp, "notify.log")


def sweep(status, watch, rc=0, says=""):
    with open(WFILE, "w") as fh:
        json.dump(watch, fh)
    for f in (SLOG, NLOG):
        open(f, "w").close()
    setup([[r"graphql", {"data": {"repository": {"issue": {"projectItems": {"nodes": [
        {"fieldValueByName": {"name": status}}]}}}}}, 0], [r"comments", "[]", 0]])
    subprocess.run([os.path.join(wbin, "sclaude-watch")], capture_output=True, timeout=60,
                   env=dict(ENV, HOME=home, FAKE_SCLAUDE_LOG=SLOG, FAKE_NOTIFY_LOG=NLOG,
                            FAKE_SCLAUDE_RC=str(rc), FAKE_SCLAUDE_SAYS=says))
    return open(SLOG).read(), open(NLOG).read(), json.load(open(WFILE))


BASE = {"feature": "demo", "issue": 7, "pr": 40, "repo": "o/r", "root": tmp,
        "since": "2026-10-01T00:00:00+00:00",
        "columns": {"back": "In progress", "backlog": "Backlog", "done": "Done", "qa": "In QA"}}
ran, told, w = sweep("Done", dict(BASE, status="In QA"))
check("timer-hands-over", ran.strip(), "%s _handoff demo" % tmp)
check("timer-tells-handed", "out of draft" in told, True)
check("timer-records-handed", w.get("handoff"), "done")
ran, told, w = sweep("Done", dict(BASE, status="Done", handoff="done"))
check("timer-handed-once", (ran, told), ("", ""))
ran, told, w = sweep("Done", dict(BASE, status="Done"))
check("timer-retries-while-done", "ready to merge" in told, True)
ran, told, w = sweep("Done", dict(BASE, status="In QA"), rc=1, says="any words at all")
check("timer-says-why-waiting", "any words at all" in told, True)
check("timer-waiting-not-recorded", w.get("handoff"), None)
ran, told, w = sweep("Done", dict(BASE, status="Done"), rc=1, says="still waiting")
check("timer-waiting-not-repeated", told, "")
# Done before, by sclaude in a terminal: recorded, and not news.
ran, told, w = sweep("Done", dict(BASE, status="Done"), rc=3)
check("timer-before-quiet", told, "")
check("timer-before-recorded", w.get("handoff"), "done")
# Never possible: recorded, and not tried again.
ran, told, w = sweep("Done", dict(BASE, status="Done"), rc=2)
check("timer-gone-recorded", w.get("handoff"), "gone")
ran, told, w = sweep("Done", dict(BASE, status="Done", handoff="gone"))
check("timer-gone-not-retried", ran, "")
# In part: said once, tried again quietly.
ran, told, w = sweep("Done", dict(BASE, status="Done"), rc=4, says="WARN could not move PR #40")
check("timer-partial-told", "could not move PR #40" in told, True)
check("timer-partial-recorded", w.get("handoff"), "partial")
ran, told, w = sweep("Done", dict(BASE, status="Done", handoff="partial"), rc=4, says="WARN x")
check("timer-partial-retried", ran != "", True)
check("timer-partial-told-once", told, "")
ran, told, w = sweep("In progress", dict(BASE, status="Done", handoff="done"))
check("timer-return-resets", w.get("handoff"), None)
old_watch = dict(BASE, status="In QA")
del old_watch["root"]
ran, told, w = sweep("Done", old_watch)
check("timer-no-root-no-handoff", ran, "")

# --- the wiring --------------------------------------------------------------
deploy = open(os.path.join(LIB, "deploy.sh"), encoding="utf-8").read()
check("remind-hands-over", 'pr_qa_handoff "$wt" "$pr" "$issue" || handed=$?' in deploy, True)
check("remind-merged-done", 'pr_board_set "$pr" "$QA_DONE" "$issue"' in deploy, True)
github = open(os.path.join(LIB, "github.sh"), encoding="utf-8").read()
check("capture-sets-up", 'pr_setup "$wt" "$number"' in github, True)
watch = open(os.path.join(LIB, "watch.sh"), encoding="utf-8").read()
check("rewind-counts-returns", "qa_returns" in watch, True)
check("watch-records-root", 'state_set "$file" root "$REPO"' in watch, True)
check("watch-rearm-clears-handoff", 'state_set "$file" handoff null' in watch, True)
sclaude = open(os.path.join(ROOT, "bin", "sclaude"), encoding="utf-8").read()
check("handoff-command", '_handoff)      shift; cmd_handoff' in sclaude, True)
check("handoff-no-sync", "_handoff|-h|--help" in sclaude, True)
prompt = open(os.path.join(ROOT, "sclaude", "prompts", "pr.md"), encoding="utf-8").read()
check("prompt-draft", "--draft" in prompt, True)

shutil.rmtree(tmp)
for name, want, got in failures:
    print("FAIL %s: want %r, got %r" % (name, want, got))
if failures:
    sys.exit(1)
print("ok")
