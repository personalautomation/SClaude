#!/usr/bin/env python3
#
# What the QA watcher saves when a feature is handed back.
#
# notes_since (bin/sclaude-watch) gathers everything said since the watch began:
# the issue, and the pull request's conversation and the comments on its lines.
# The pull request is there because a return can be made over the automatic
# review's findings rather than over QA's own words — PR #143 in social — and a
# file that held only the issue would hand the session a return that points
# nowhere.
#
# Guarded here, with a fake `gh` on PATH:
#
#   * every page is read — `--paginate` alone prints one array per page and the
#     parser used to give up on the second, so past 30 comments it saw none;
#   * only what came after the mark counts;
#   * a comment on a line says which file and line;
#   * a feature with no pull request reads the issue alone.
#
# Run it with: python3 tests/qa-notes.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
WATCH = os.path.join(ROOT, "bin", "sclaude-watch")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def functions(source, names):
    """The named shell functions, cut out of the script whole."""
    out = []
    for name in names:
        m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), source, re.S | re.M)
        if not m:
            failures.append(("function-present-" + name, True, False))
            continue
        out.append(m.group(0))
    return "\n".join(out)


def row(login, when, body, **extra):
    r = {"user": {"login": login}, "created_at": when, "body": body}
    r.update(extra)
    return r


SINCE = "2026-10-01T18:55:52+00:00"
BEFORE = "2026-10-01T10:00:00Z"
AFTER = "2026-10-02T03:00:00Z"

# What each endpoint answers, as `--slurp` prints it: a list of pages.
ANSWERS = {
    "repos/o/r/issues/125/comments": [
        [row("qa", BEFORE, "an old remark, already seen")],
        [row("qa", AFTER, "Returned: fix the ten findings")],
    ],
    "repos/o/r/issues/143/comments": [
        [row("claude[bot]", AFTER, "## Code review\n\n1. closeAllDialogs can leave the app")],
    ],
    "repos/o/r/pulls/143/comments": [
        [row("claude[bot]", AFTER, "the sweep can starve",
             path="app/api/cron/nightly/route.ts", line=158),
         row("claude[bot]", AFTER, "an outdated one",
             path="lib/a.ts", line=None, original_line=7),
         row("claude[bot]", BEFORE, "before the mark", path="lib/b.ts", line=1)],
    ],
}

tmp = tempfile.mkdtemp()
try:
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    with open(os.path.join(tmp, "answers.json"), "w") as fh:
        json.dump(ANSWERS, fh)
    # `gh api <path>?per_page=100 --paginate --slurp`: answered from the table,
    # and only when the flags that make paging work are there.
    with open(os.path.join(bindir, "gh"), "w") as fh:
        fh.write("""#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:1] != ["api"] or "--paginate" not in args or "--slurp" not in args:
    sys.exit(1)
path = args[1].split("?")[0]
answers = json.load(open(%r))
if path not in answers:
    sys.exit(1)
print(json.dumps(answers[path]))
""" % os.path.join(tmp, "answers.json"))
    os.chmod(os.path.join(bindir, "gh"), 0o755)

    with open(WATCH) as fh:
        body = functions(fh.read(), ["comments_since", "notes_since"])

    def notes(issue, pr):
        script = body + '\nnotes_since o/r %s "%s" %s\n' % (issue, pr, SINCE)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"])
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, env=env, timeout=30).stdout

    out = notes(125, 143)
    check("issue-heading", "### On issue #125" in out, True)
    check("second-page-read", "Returned: fix the ten findings" in out, True)
    check("before-the-mark-dropped", "an old remark" in out, False)
    check("pr-conversation", "### On pull request #143" in out
          and "closeAllDialogs can leave the app" in out, True)
    check("pr-lines-heading", "### On the lines of pull request #143" in out, True)
    check("inline-says-where",
          "**claude[bot]** on `app/api/cron/nightly/route.ts:158`" in out, True)
    check("outdated-inline-uses-original-line", "`lib/a.ts:7`" in out, True)
    check("inline-before-the-mark-dropped", "before the mark" in out, False)

    out = notes(125, "null")
    check("no-pr-reads-the-issue", "Returned: fix the ten findings" in out, True)
    check("no-pr-reads-no-pr", "pull request" in out, False)

    out = notes(999, 998)
    check("nothing-said-is-empty", out.strip(), "")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
