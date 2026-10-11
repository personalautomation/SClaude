#!/usr/bin/env python3
#
# A step's commits name the session that wrote them.
#
# The issue's table names sessions by claude's local id; the commits carried
# only Claude-Session, claude.ai's id for the same conversation, and nothing
# joined the two but the transcripts on one machine. A session's git now runs
# its hooks through sclaude/githooks, which add `Sclaude-Session: <id>`.
#
# Guarded here, on a scratch repository with hooks of its own in .githooks —
# as social has — and a linked worktree, as a feature has:
#
#   * a commit made under session_git_env carries the trailer, inside the
#     trailer block the message already had;
#   * the project's own commit-msg still runs, after it, and can refuse;
#   * its other hooks run too, with their arguments (pre-push here);
#   * outside the session nothing changes: no trailer;
#   * GIT_CONFIG_* already set is kept;
#   * run_step launches both kinds of session with it.
#
# Run it with: python3 tests/session-trailer.py
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


with open(os.path.join(LIB, "run.sh")) as fh:
    RUN = fh.read()
m = re.search(r"^session_git_env\(\) \{\n.*?^\}\n", RUN, re.S | re.M)
ENV_FN = m.group(0) if m else ""
check("function-present", bool(ENV_FN), True)

tmp = tempfile.mkdtemp()
try:
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, ".githooks"))
    git = lambda *a, cwd=repo, env=None: subprocess.run(
        ["git", *a], cwd=cwd, capture_output=True, text=True, env=env)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("config", "core.hooksPath", ".githooks")
    log = os.path.join(tmp, "hooks.log")
    with open(os.path.join(repo, ".githooks", "commit-msg"), "w") as fh:
        fh.write('#!/usr/bin/env bash\necho "commit-msg $(tail -1 "$1")" >> %s\n'
                 'grep -q REFUSE "$1" && exit 1\nexit 0\n' % log)
    with open(os.path.join(repo, ".githooks", "pre-push"), "w") as fh:
        fh.write('#!/usr/bin/env bash\necho "pre-push $1" >> %s\n' % log)
    for h in ("commit-msg", "pre-push"):
        os.chmod(os.path.join(repo, ".githooks", h), 0o755)
    git("add", ".")
    git("commit", "-q", "-m", "init")
    wt = os.path.join(tmp, "wt")
    git("worktree", "add", "-q", "-b", "feat", wt)

    def commit(msg, session=True, extra=""):
        body = 'INSTRUMENTS=%s\n%s\n%s\n' % (ROOT, ENV_FN, extra)
        if session:
            body += 'session_git_env 0f1e2d3c-aaaa-bbbb-cccc-000000000001\n'
        body += 'git commit -q --allow-empty -F - <<"MSG"\n%s\nMSG\necho rc=$?\n' % msg
        body += 'echo "count=$GIT_CONFIG_COUNT key0=${GIT_CONFIG_KEY_0:-} key1=${GIT_CONFIG_KEY_1:-}"\n'
        out = subprocess.run(["bash", "-c", body], cwd=wt, capture_output=True, text=True)
        return out.stdout, git("log", "-1", "--format=%B", cwd=wt).stdout

    msg = "fix: a thing\n\nWhy.\n\nRequirement: it works.\nCo-Authored-By: C <c@c>"
    out, body = commit(msg)
    trailers = body.strip().split("\n\n")[-1].splitlines()
    check("trailer-added",
          "Sclaude-Session: 0f1e2d3c-aaaa-bbbb-cccc-000000000001" in trailers, True)
    check("trailer-block-unbroken", trailers[:2], ["Requirement: it works.", "Co-Authored-By: C <c@c>"])
    with open(log) as fh:
        seen = fh.read()
    check("project-commit-msg-ran-after",
          "commit-msg Sclaude-Session: 0f1e2d3c-aaaa-bbbb-cccc-000000000001" in seen, True)

    out, _ = commit("fix: REFUSE this")
    check("project-hook-can-refuse", "rc=1" in out, True)

    out, body = commit("fix: by hand", session=False)
    check("outside-the-session-no-trailer", "Sclaude-Session" in body, False)

    out, _ = commit("fix: kept", extra="export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=user.name GIT_CONFIG_VALUE_0=x")
    check("existing-git-config-kept", "count=2 key0=user.name key1=core.hooksPath" in out, True)

    # pre-push, through the same dispatcher, with its arguments.
    bare = os.path.join(tmp, "origin.git")
    git("init", "-q", "--bare", bare)
    git("remote", "add", "origin", bare)
    body = 'INSTRUMENTS=%s\n%s\nsession_git_env s1\ngit push -q origin feat 2>&1\n' % (ROOT, ENV_FN)
    subprocess.run(["bash", "-c", body], cwd=wt, capture_output=True, text=True)
    with open(log) as fh:
        check("project-pre-push-ran", "pre-push origin" in fh.read(), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

check("both-launches-carry-it", RUN.count('session_git_env "$session" && claude'), 2)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
