#!/usr/bin/env python3
#
# issue_create's milestone: the earliest open one by due date, over every
# page GitHub answers with, its title passed to `gh issue create` as GitHub
# spells it. And issue_sync's summary comment, found by its marker over every
# page: patched when found, posted when not, left alone when GitHub could not
# be read — a second summary was posted then.
#
# The lookup was read once per page (`--paginate --jq` runs its filter on each
# page), then with `--slurp` beside `--jq`, which gh refuses — every issue went
# without a milestone and nothing said so. The stub gh here refuses that pair
# as the real one does.
#
# Run it with: python3 tests/issue-create.py
import json
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def milestone(pages, fails=False):
    """Run issue_create against a stub gh; the --milestone it was given, or None."""
    wt = tempfile.mkdtemp()
    answer = os.path.join(wt, "pages.json")
    with open(answer, "w") as f:
        json.dump(pages, f)
    log = os.path.join(wt, "created")
    script = f"""
set -uo pipefail
BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""
source "{LIB}/core/ui.sh"; source "{LIB}/core/state.sh"; source "{LIB}/github/github.sh"
info() {{ :; }}; warn() {{ echo "$*" >&2; }}
gh_repo() {{ echo o/r; }}
issue_body() {{ echo body; }}
gh() {{
  case "$1 $2" in
    "api repos/o/r/milestones"*)
      # Every page read whole; gh refuses --slurp beside --jq.
      [[ " $* " == *" --slurp "* && " $* " != *" --jq "* ]] || return 1
      {"return 1" if fails else 'cat "' + answer + '"'} ;;
    "issue create")
      shift 2
      while (( $# )); do [[ "$1" == --milestone ]] && printf '%s' "$2" > "{log}"; shift; done
      echo https://github.com/o/r/issues/7 ;;
  esac
}}
issue_create "A feature"
"""
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    check("created " + str(pages)[:40], out.stdout.strip(), "7")
    return open(log).read() if os.path.exists(log) else None


def ms(title, due=None):
    return {"title": title, "due_on": due, "state": "open"}


# The earliest due across pages, an undated one last.
check("earliest-on-page-two",
      milestone([[ms("later", "2026-12-01T00:00:00Z"), ms("undated")],
                 [ms("first", "2026-11-01T00:00:00Z")]]), "first")
check("undated-only", milestone([[ms("undated")]]), "undated")
# A title as GitHub spells it, not jq's @tsv escape of it.
check("backslash-and-tab", milestone([[ms("v1\\beta\tx", "2026-11-01T00:00:00Z")]]),
      "v1\\beta\tx")
# None open, or GitHub not read: no milestone, the issue all the same.
check("none-open", milestone([[]]), None)
check("read-failed", milestone([], fails=True), None)

def sync(answer, status):
    """Run issue_sync with a gh whose comment lookup prints `answer` and
    exits `status`; the summary's write, as `-X <verb> <path>`, or ""."""
    wt = tempfile.mkdtemp()
    feature = os.path.join(wt, ".sclaude/local/feature")
    os.makedirs(feature)
    with open(os.path.join(feature, "state.json"), "w") as f:
        json.dump({"issue": 7, "feature": "my-feature", "steps": {}}, f)
    log = os.path.join(wt, "written")
    script = f"""
set -uo pipefail
BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""
source "{LIB}/core/ui.sh"; source "{LIB}/core/state.sh"; source "{LIB}/core/steps.sh"
source "{LIB}/github/github.sh"; source "{LIB}/github/issue_sync.sh"
info() {{ :; }}; warn() {{ :; }}
gh_repo() {{ echo o/r; }}
gh() {{
  case "$*" in
    "api repos/o/r/issues/7/comments?per_page=100 --paginate --jq "*)
      printf '{answer}'; return {status} ;;
    *"-X PATCH"*|*"-X POST"*) echo "$*" | head -1 | cut -d" " -f3-5 > "{log}" ;;
  esac
}}
issue_sync "{wt}"
"""
    subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return open(log).read().strip() if os.path.exists(log) else ""


check("sync-none-posts", sync("", 0), "-X POST repos/o/r/issues/7/comments")
check("sync-found-patches", sync("123\\n", 0), "-X PATCH repos/o/r/issues/comments/123")
# GitHub not read: nothing written, rather than a second summary.
check("sync-unread-waits", sync("", 1), "")
# Found, then a later page failed or gh died on a closed pipe: still ours.
check("sync-found-then-failed", sync("123\\n456\\n", 1),
      "-X PATCH repos/o/r/issues/comments/123")


if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("\n%d failure(s)" % len(failures))
    sys.exit(1)
print("ok")
