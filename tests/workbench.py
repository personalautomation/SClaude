#!/usr/bin/env python3
#
# `sclaude workshop` (sclaude/lib/improve/workbench.sh), the bot's 🛠 button:
#
#   * it makes a worktree of sclaude's checkout from origin's main, beside it,
#     and starts the session there in plan mode with the live checkout
#     read-only, its prompt (sclaude/prompts/workbench.md) filled in;
#   * when the session ends, the worktree goes if what it holds is on main,
#     and stays, with the way back, while it is not;
#   * with no terminal it starts nothing.
#
# The session itself is a stand-in: claude_launch records what it was given
# and does what the case asks of it.
#
# Run it with: python3 tests/workbench.py
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    print(("PASS  " if got == want else "FAIL  ") + name)
    if got != want:
        failures.append(name)
        print("  want: %r\n  got:  %r" % (want, got))


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


tmp = tempfile.mkdtemp()
try:
    origin = os.path.join(tmp, "origin.git")
    live = os.path.join(tmp, "instruments")
    git("init", "-q", "--bare", "-b", "main", origin)
    git("clone", "-q", origin, live)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        git("config", k, v, cwd=live)
    open(os.path.join(live, "a.txt"), "w").write("a\n")
    git("add", ".", cwd=live)
    git("commit", "-qm", "init", cwd=live)
    git("push", "-q", "origin", "main", cwd=live)

    def run(session_does):
        log = os.path.join(tmp, "launch.log")
        script = r'''
set -uo pipefail
INSTRUMENTS=%(live)s PROMPTS=%(prompts)s SELF=sclaude
BOLD= BLUE= OFF=
info() { echo "INFO $*"; }; warn() { echo "WARN $*"; }; die() { echo "DIE $*"; exit 1; }
developer_is_maintainer() { return 0; }; developer_name() { echo dev; }
contribute_mode() { echo "${CONTRIB:-ask}"; }; session_latest() { echo sess-latest; }
sclaude_guard_args() { printf '%%s\n' --readonly "$INSTRUMENTS"; }
new_session_id() { echo sess-1; }
guard_entry() { printf '{"guard": "%%s"}' "$*"; }
claude_launch() { printf '%%s\n' "$PWD" "$@" > %(log)s; %(does)s; }
source %(lib)s/improve/workbench.sh
cmd_workshop
''' % {"live": live, "prompts": os.path.join(ROOT, "sclaude", "prompts"), "log": log,
           "lib": LIB, "does": session_does}
        out = subprocess.run(["script", "-qec", "bash -c %s" % shlex.quote(script),
                              "/dev/null"], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL).stdout
        launched = open(log).read().split("\n") if os.path.exists(log) else []
        if os.path.exists(log):
            os.unlink(log)
        return out, launched

    def workshops():
        return sorted(p for p in os.listdir(tmp) if p.startswith("sclaude-workshop-"))

    # A session that changes nothing: the worktree goes.
    out, launched = run(":")
    wt = launched[0] if launched else ""
    check("made beside the checkout", os.path.dirname(wt) == tmp
          and os.path.basename(wt).startswith("sclaude-workshop-"), True)
    check("its path does not begin with the checkout's", wt.startswith(live), False)
    check("plan mode", "plan" in launched[launched.index("--permission-mode") + 1:][:1], True)
    check("the live checkout read-only", any("--readonly %s" % live in a for a in launched), True)
    check("leniently, as a step's guard", any("--lenient" in a for a in launched), True)
    prompt = "\n".join(launched[launched.index("sclaude workshop") + 1:]) \
        if "sclaude workshop" in launched else ""
    check("the prompt names the worktree", wt in prompt, True)
    check("no placeholder left in the prompt",
          any(p in prompt for p in ("<workshop>", "<branch>", "<live>", "<maintainer>")), False)
    check("nothing changed: the worktree goes", workshops(), [])
    check("nothing changed: its branch goes", "workshop/" in git("branch", cwd=live), False)

    # A session that committed and did not publish: it stays, with the way back.
    out, launched = run("echo b > b.txt && git add b.txt && git -c user.email=t@e -c user.name=t "
                        "commit -qm b")
    check("unpublished: the worktree stays", len(workshops()), 1)
    check("unpublished: the way back is the conversation it went on in",
          "claude --resume sess-latest" in out, True)

    # A session that published (pushed its HEAD to main): it goes.
    out, launched = run("echo c > c.txt && git add c.txt && git -c user.email=t@e -c user.name=t "
                        "commit -qm c && git push -q origin HEAD:main")
    check("published: the worktree goes", len(workshops()), 1)  # the earlier one stays

    # Main moving on under a session that changed nothing: it still goes.
    other = os.path.join(tmp, "other")
    git("clone", "-q", origin, other)
    before = workshops()
    out, launched = run("git -C %s pull -q --rebase && cd %s && echo d > d.txt && git add d.txt && "
                        "git -c user.email=o@e -c user.name=o commit -qm d && git push -q origin HEAD:main; cd -"
                        % (other, other))
    check("main moved, nothing changed here: the worktree goes", workshops(), before)

    # The earlier unpublished one, its change merged since as a squash by
    # somebody else and then edited on main: not provable, so it is kept.
    kept = os.path.join(tmp, before[0])
    for name in os.listdir(kept):
        if name.endswith(".txt") and name not in os.listdir(other):
            open(os.path.join(other, name), "w").write(open(os.path.join(kept, name)).read())
            git("add", name, cwd=other)
    git("-c", "user.email=o@e", "-c", "user.name=o", "commit", "-qm", "squashed", cwd=other)
    # And main edits that file again before the next press.
    edited = git("show", "--name-only", "--format=", "HEAD", cwd=other).split()[0]
    open(os.path.join(other, edited), "a").write("later\n")
    git("-c", "user.email=o@e", "-c", "user.name=o", "commit", "-qam", "later", cwd=other)
    git("push", "-q", "origin", "HEAD:main", cwd=other)
    out, launched = run(":")
    check("an earlier workshop squash-merged, then edited on main: kept (not provable)",
          os.path.exists(kept), True)

    # With origin/main unknown, nothing counts as published.
    lone = os.path.join(tmp, "lone")
    git("init", "-q", "-b", "main", lone)
    open(os.path.join(lone, "x"), "w").write("x")
    git("add", "x", cwd=lone)
    git("-c", "user.email=o@e", "-c", "user.name=o", "commit", "-qm", "x", cwd=lone)
    rc = subprocess.run(["bash", "-c", 'source %s/improve/workbench.sh; workbench_published %s'
                         % (LIB, lone)]).returncode
    check("no origin/main: not published", rc, 1)

    # workbench_published on hand-made workshops, beside a checkout of their own.
    def published(setup):
        base_dir = tempfile.mkdtemp(dir=tmp)
        chk = os.path.join(base_dir, "instruments")
        ws = os.path.join(base_dir, "sclaude-workshop-1")
        sh = lambda cmd, cwd: subprocess.run(["bash", "-c", cmd], cwd=cwd, check=True,
                                             capture_output=True)
        id_ = "-c user.email=t@e -c user.name=t"
        sh("git init -q --bare -b main o.git && git clone -q o.git instruments", base_dir)
        sh("echo a > a && git add a && git %s commit -qm a && git push -q origin main" % id_, chk)
        sh("git worktree add -q -b workshop/1 %s origin/main" % ws, chk)
        sh(setup.replace("ID", id_), ws)
        sh("git fetch -q origin", ws)
        return subprocess.run(["bash", "-c", 'INSTRUMENTS=%s; source %s/improve/workbench.sh;'
                               ' workbench_published %s' % (chk, LIB, ws)]).returncode == 0

    check("work on the branch, HEAD moved to main: not published",
          published("echo b > b && git add b && git ID commit -qm b && git switch -q --detach origin/main"),
          False)
    # A rebase merge: main moved on first, and the commits reach it anew.
    REBASED = ("echo b > b && git add b && git ID commit -qm b && echo c > c && git add c && "
               "git ID commit -qm c && git clone -q ../o.git ../o2 && cd ../o2 && echo z > z && "
               "git add z && git ID commit -qm z && git fetch -q ../sclaude-workshop-1 workshop/1 && "
               "git ID cherry-pick FETCH_HEAD~1 FETCH_HEAD >/dev/null && git push -q origin main")
    check("several commits rebase-merged: published", published(REBASED), True)
    check("merged main in with edits of its own, commits rebase-merged: not published",
          published(REBASED.replace(" && git push -q origin main", " && git push -q origin main"
                                    " && cd ../sclaude-workshop-1 && git fetch -q origin && "
                                    "git ID merge -q --no-ff --no-commit origin/main && echo n > n && "
                                    "git add n && git ID commit -qm merge && "
                                    "git rev-parse -q --verify HEAD^2 >/dev/null")), False)
    check("several commits rebase-merged, then edited on main: kept (not provable)",
          published(REBASED + " && echo later >> b && git ID commit -qam later && git push -q origin main"),
          False)
    check("a commit differing from main only in indentation: not published",
          published("printf 'def f():\\n    return 1\\n' > p.py && git add p.py && git ID commit -qm p && "
                    "git clone -q ../o.git ../o3 && cd ../o3 && printf 'def f():\\n  return 1\\n' > p.py && "
                    "git add p.py && git ID commit -qm p && git push -q origin main"), False)
    check("committed and reverted: published",
          published("echo b > b && git add b && git ID commit -qm b && git ID revert --no-edit HEAD"),
          True)
    check("committed, not pushed: not published",
          published("echo b > b && git add b && git ID commit -qm b"), False)

    # sclaude.contribute off: nothing made.
    out = subprocess.run(["script", "-qec", "bash -c %s" % shlex.quote(
        'INSTRUMENTS=%s; SELF=sclaude; die() { echo "DIE $*"; exit 1; };'
        ' contribute_mode() { echo off; }; source %s/improve/workbench.sh; cmd_workshop' % (live, LIB)),
        "/dev/null"], capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    check("contribute off: refused", "changing sclaude is off" in out, True)

    # No terminal: nothing made.
    before = workshops()
    out = subprocess.run(["bash", "-c", 'INSTRUMENTS=%s; SELF=sclaude; die() { echo "DIE $*"; exit 1; };'
                          ' source %s/improve/workbench.sh; cmd_workshop' % (live, LIB)],
                         capture_output=True, text=True, start_new_session=True,
                         stdin=subprocess.DEVNULL).stdout
    check("no terminal: refused", "needs a terminal" in out, True)
    check("no terminal: nothing made", workshops(), before)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    print("FAILED: %d" % len(failures))
    sys.exit(1)
print("all good")
