#!/usr/bin/env python3
#
# An accepted issue goes back to QA when the preview under it is replaced.
#
# An issue was moved to Done by QA; a fix for a red regression
# followed and the preview was deployed again, and the issue stayed in Done —
# the merge offered on a yes given to code that was no longer there.
#
# Guarded here, by running qa_retest with gh and the board stubbed:
#
#   * an issue in Done with the pull request open moves Done → In QA when the
#     preview commit differs from the one QA was sent (`qa.sha`); the PR
#     becomes a draft again, the hand-off is forgotten and `qa.sha` updated;
#   * the same commit leaves Done alone;
#   * with no record, only a fresh deploy counts as a change;
#   * a merged pull request leaves Done alone — `Closes #N` put it there;
#   * an issue not in Done is not touched (issue_qa_ready handles it);
#   * a PR already a draft is not converted twice;
#   * qa_retest runs inside the green branch of the preview gate, before
#     issue_qa_ready, and qa_sent records the commit after it;
#   * qa_wait checks Done with qa_retest before it says the merge is next.
#
# Run it with: python3 tests/retest.py
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DEPLOY = os.path.join(ROOT, "sclaude", "lib", "deploy.sh")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


deploy = open(DEPLOY, encoding="utf-8").read()
FUNC = ""
for name in ("qa_retest", "qa_sent", "pr_unhandoff"):
    match = re.search(r'^%s\(\) \{\n.*?^\}\n' % name, deploy, re.M | re.S)
    if not match:
        print("FAIL %s not found in deploy.sh" % name)
        sys.exit(1)
    FUNC += match.group(0)


def run(column, pr_state, draft, sent="aaa111", now="bbb222", fresh=""):
    with tempfile.TemporaryDirectory() as tmp:
        wt = os.path.join(tmp, "wt")
        os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
        state_file = os.path.join(wt, ".sclaude/local/feature", "state.json")
        with open(state_file, "w") as fh:
            st = {"handoff": "abc123", "deploy": {"preview": {"sha": now}}}
            if sent:
                st["qa"] = {"sha": sent}
            json.dump(st, fh)
        log = os.path.join(tmp, "log")
        body = "set -uo pipefail\n"
        body += 'BOLD=""; OFF=""\n'
        body += 'QA_TO="In QA"; QA_FROM="In progress"; PROGRESS_FROM="Backlog"; QA_DONE="Done"\n'
        body += 'source "%s/sclaude/lib/state.sh"\n' % ROOT
        body += 'source "%s/sclaude/lib/project.sh"\n' % ROOT
        body += ('warn() { echo "$*" >&2; }\n'
                 'info() { echo "$*"; }\n'
                 'say()  { echo "$*"; }\n'
                 'gh_repo() { echo o/r; }\n'
                 'issue_status_now() { echo "%s"; }\n'
                 'issue_move_status() { echo "MOVE $*" >> "%s"; }\n'
                 'gh() {\n'
                 '  case "$1 $2" in\n'
                 '    "pr view") printf "%%s\\t%%s\\n" "%s" "%s" ;;\n'
                 '    "pr ready") echo "GH $*" >> "%s" ;;\n'
                 '  esac\n'
                 '}\n') % (column, log, pr_state, draft, log)
        body += FUNC
        body += 'qa_retest "%s" 150 159 %s; echo "rc=$?"\n' % (wt, fresh)
        out = subprocess.run(["bash", "-c", body], capture_output=True, text=True,
                             timeout=30)
        moves = open(log).read().splitlines() if os.path.exists(log) else []
        with open(state_file) as fh:
            st = json.load(fh)
        out.qa_sha = (st.get("qa") or {}).get("sha")
        return out, moves, st.get("handoff")


out, moves, handoff = run("Done", "OPEN", "false")
check("done-open-rc", "rc=0" in out.stdout, True)
check("done-open-records-new-sha", out.qa_sha, "bbb222")
check("done-open-moves-back", "MOVE 150 Done In QA" in moves, True)
check("done-open-redrafts-pr",
      any(m.startswith("GH pr ready 159") and "--undo" in m for m in moves), True)
check("done-open-forgets-handoff", handoff, "")
check("done-open-says-why", "has changed since" in out.stdout, True)

out, moves, handoff = run("Done", "OPEN", "true")
check("already-draft-not-converted", any(m.startswith("GH") for m in moves), False)
check("already-draft-still-moves", "MOVE 150 Done In QA" in moves, True)

out, moves, handoff = run("Done", "MERGED", "false")
check("merged-left-in-done", moves, [])
check("merged-keeps-handoff", handoff, "abc123")

out, moves, handoff = run("In progress", "OPEN", "true")
check("not-done-untouched", moves, [])

out, moves, handoff = run("Done", "OPEN", "false", sent="bbb222")
check("same-sha-left-in-done", moves, [])
check("same-sha-rc", "rc=1" in out.stdout, True)
check("same-sha-keeps-handoff", handoff, "abc123")

out, moves, handoff = run("Done", "OPEN", "false", sent="")
check("no-record-not-fresh-left-alone", moves, [])

out, moves, handoff = run("Done", "OPEN", "false", sent="", fresh="fresh")
check("no-record-fresh-moves-back", "MOVE 150 Done In QA" in moves, True)
check("no-record-fresh-records-sha", out.qa_sha, "bbb222")

# The call sits in the green branch of the preview gate, before the move to In QA.
green = re.search(r'if regression_gate "\$wt" "\$slug" preview; then\n(.*?)\n\s*else\n',
                  deploy, re.S)
check("retest-in-green-branch",
      bool(green) and 'qa_retest "$wt" "$issue" "$pr"' in green.group(1), True)
check("retest-before-qa-ready",
      bool(green) and green.group(1).find("qa_retest")
      < green.group(1).find("issue_qa_ready")
      < green.group(1).find('qa_sent "$wt"'), True)

# qa_wait asks before the Done branch that announces the merge.
qa_wait = re.search(r'^qa_wait\(\) \{\n.*?^\}\n', deploy, re.M | re.S).group(0)
check("qa-wait-retests-before-merge-message",
      -1 < qa_wait.find('qa_retest "$wt" "$issue" "$pr"')
      < qa_wait.find("Now waiting for the merge"), True)
check("remind-passes-wt-to-qa-wait",
      'qa_wait "$slug" "$issue" "$pr" "$branch" "$wt"' in deploy, True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
