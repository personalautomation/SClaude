#!/usr/bin/env python3
#
# A test bench for the three functions that quietly did the wrong thing.
#
# All three were found by reading rather than by running, and that is the point
# of this file: none of them failed. No exception, no non-zero exit, nothing in
# a log. Each looked like a function doing its job.
#
#   abandon_traces      built the table that stands in front of an irreversible
#                       deletion, and built it from `/.feature/state.json` — so
#                       the branch, the pull request and the issue were simply
#                       absent from it. The worktree line was there, which is
#                       what made it look right.
#
#   write_vercelignore  checked for, and wrote, `/.vercelignore`. The write
#                       failed for want of permission on `/` and said nothing,
#                       so no worktree ever had the file and every preview went
#                       up carrying the `.env` symlinks it exists to exclude.
#
#   deploy_unchanged    compares what we shipped against main's HEAD. After a
#                       rollback the two still agree — git is untouched — so it
#                       answered "unchanged, skipping" while production served
#                       the release before, and the fix was never offered.
#
# The first two are one bash trap: `local a="$1" b="$a/x"` assigns left to right
# and does not expand a name from the same command, so `b` comes out as `/x`.
# Three other files in the library already carry a comment about it, which is the
# other half of the lesson — the knowledge was there and nothing applied it.
#
# So these run the real functions in a real git repository, and assert on what
# somebody would have seen. A regression here is a path silently losing its head
# again, which is exactly the failure that does not announce itself.
#
# Run it with: python3 tests/paths.py
import os
import re
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def run_bash(script, cwd, modules=("ui", "state"), env=None):
    """The real functions, in a real shell — the idiom tests/io.py uses.

    `gh` is shadowed by a function that answers nothing: these tests are about
    paths, and a bench that reaches GitHub would be testing the network.
    """
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
    for name in modules:
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    # Silence the reporting helpers and the network. gh_repo answering empty is
    # the "no network" path the functions are written to survive.
    body += "gh() { return 1; }\ngh_repo() { return 1; }\n"
    body += script
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, timeout=30, env=env)
    return out.stdout, out.stderr, out.returncode


def code_has(path, needle):
    """True when `needle` appears outside a comment.

    The two fixes left comments quoting the broken line verbatim — that is what
    makes them useful to the next reader — so a plain substring search finds the
    explanation and reports the bug as still present. The check is about code.
    """
    for line in open(path, encoding="utf-8"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if needle in stripped:
            return True
    return False


def git(*args, cwd):
    subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True,
                   check=False)


def make_repo(root):
    """A repository with one commit on main and a feature branch beyond it."""
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "t@t", cwd=repo)
    git("config", "user.name", "T", cwd=repo)
    with open(os.path.join(repo, "README.md"), "w") as fh:
        fh.write("x\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "first", cwd=repo)

    # origin/main, so `origin/main..branch` resolves — abandon_traces counts the
    # branch's own commits with it.
    origin = os.path.join(root, "origin.git")
    subprocess.run(["git", "clone", "-q", "--bare", repo, origin],
                   capture_output=True, check=False)
    git("remote", "add", "origin", origin, cwd=repo)
    git("fetch", "-q", "origin", cwd=repo)

    git("checkout", "-q", "-b", "feat/demo", cwd=repo)
    with open(os.path.join(repo, "f.txt"), "w") as fh:
        fh.write("y\n")
    git("add", "-A", cwd=repo)
    git("commit", "-qm", "second", cwd=repo)
    git("push", "-q", "origin", "feat/demo", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)
    git("fetch", "-q", "origin", cwd=repo)
    return repo


def make_worktree(repo, root):
    """A feature's worktree with the state the orchestrator writes."""
    wt = os.path.join(root, "repo-demo")
    subprocess.run(["git", "worktree", "add", "-q", wt, "feat/demo"],
                   cwd=repo, capture_output=True, check=False)
    os.makedirs(os.path.join(wt, ".feature"), exist_ok=True)
    with open(os.path.join(wt, ".feature", "state.json"), "w") as fh:
        fh.write('{"feature": "demo", "branch": "feat/demo", '
                 '"issue": 71, "pr": 208, "step": "review"}\n')
    return wt


tmp = tempfile.mkdtemp()
try:
    REPO = make_repo(tmp)
    WT = make_worktree(REPO, tmp)

    # --- abandon_traces ------------------------------------------------------
    #
    # The table in front of `sclaude drop`. Its own comment says it exists so
    # that nobody agrees to an irreversible deletion without seeing what stands
    # behind it, and with the path broken it showed the worktree alone.

    out, _, _ = run_bash(
        'REPO=%s; abandon_traces %s' % (REPO, WT), tmp,
        modules=("ui", "state", "worktree", "actions", "abandon"))
    rows = {line.split("\t")[0]: line for line in out.splitlines() if "\t" in line}

    check_true("traces-has-worktree", "worktree" in rows)
    # The three that vanished. Each is a thing the human is about to destroy.
    check_true("traces-has-branch", "branch" in rows)
    check_true("traces-has-remote", "remote" in rows)
    check_true("traces-names-the-branch",
               "feat/demo" in rows.get("branch", ""))
    # And the count beside it: "4 commit(s) of its own" is the whole reason the
    # row is worth reading. A `?` there means the state was read but the branch
    # was not resolved, which is a different failure and also worth catching.
    check_true("traces-counts-the-commits",
               "1 commit(s) of its own" in rows.get("branch", ""))

    # The state really is read from the worktree, not from `/`. Asserted
    # directly, because every row above could in principle come from git alone.
    out, _, _ = run_bash(
        'REPO=%s; state_get %s/.feature/state.json branch' % (REPO, WT), tmp)
    check("state-read-from-the-worktree", out.strip(), "feat/demo")

    # The trap itself, pinned in the shape it had. A future edit that folds the
    # two declarations back into one reintroduces the bug, and this is the line
    # that says so.
    check_true("abandon-declares-state-separately",
               not code_has(os.path.join(LIB, "abandon.sh"),
                            'local wt="$1" state='))

    # --- write_vercelignore --------------------------------------------------
    #
    # The file that was never written. Two halves: it lands inside the worktree,
    # and it holds what it is for.

    ignore = os.path.join(WT, ".vercelignore")
    if os.path.exists(ignore):
        os.remove(ignore)
    run_bash('write_vercelignore %s' % WT, tmp,
             modules=("ui", "state", "worktree"))
    check_true("vercelignore-written-in-the-worktree", os.path.exists(ignore))
    if os.path.exists(ignore):
        body = open(ignore, encoding="utf-8").read()
        # The symlinks are the point: outside this machine they lead nowhere and
        # the build dies.
        check_true("vercelignore-excludes-env", ".env" in body)
        check_true("vercelignore-excludes-env-variants", ".env.*" in body)
        # sclaude's own working directory: the plan, the state, the logs and
        # the rendered terminal went up with every preview without it.
        check_true("vercelignore-excludes-feature", "/.feature/" in body.splitlines())

    # It must not write at the filesystem root, which is where it used to aim.
    # Checked by absence rather than by permissions: on a machine where `/` is
    # writable the old code would have created the file instead of failing.
    check_true("vercelignore-not-at-the-root", not os.path.exists("/.vercelignore"))


    # A file already there keeps what it has, a hand edit included, and gets
    # only the lines it lacks: an old worktree's file is brought up to date
    # before the next deploy, and calling it twice adds nothing.
    with open(ignore, "w") as fh:
        fh.write("# edited by hand\n.env\n")
    run_bash('write_vercelignore %s' % WT, tmp,
             modules=("ui", "state", "worktree"))
    run_bash('write_vercelignore %s' % WT, tmp,
             modules=("ui", "state", "worktree"))
    lines = open(ignore, encoding="utf-8").read().splitlines()
    check("vercelignore-hand-edit-kept", lines[:2], ["# edited by hand", ".env"])
    check("vercelignore-brought-up-to-date", sorted(lines[2:]), [".env.*", "/.feature/"])

    check_true("worktree-declares-the-path-separately",
               not code_has(os.path.join(LIB, "worktree.sh"), 'local wt="$1" f='))

    # And nowhere else in the library either. The trap is cheap to reintroduce
    # and silent when it happens, so the sweep is over every module rather than
    # over the two that had it.
    offenders = []
    for name in sorted(os.listdir(LIB)):
        if not name.endswith(".sh"):
            continue
        path = os.path.join(LIB, name)
        for number, line in enumerate(open(path, encoding="utf-8"), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "local " not in stripped:
                continue
            # A `local` list whose second name expands one declared beside it.
            found = re.match(r'local\s+([A-Za-z_][A-Za-z0-9_]*)=\S*\s+\S*=[^\n]*\$\{?\1\b',
                             stripped)
            if found:
                offenders.append("%s:%d" % (name, number))
    check("no-local-expands-its-own-neighbour", offenders, [])

    # --- deploy_unchanged ----------------------------------------------------
    #
    # "Do we know that deploying again would be pointless?" Everything unknown
    # answers no, and after a rollback the answer is no whatever the commits say.

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    state = os.path.join(WT, ".feature", "state.json")

    def unchanged(stage):
        _, _, rc = run_bash(
            'REPO=%s; deploy_unchanged %s %s' % (REPO, WT, stage), tmp,
            modules=("ui", "state", "worktree", "rollback", "deploy"))
        return rc == 0

    # Nothing recorded: not knowing is not a yes.
    check("unchanged-without-a-record", unchanged("prod"), False)

    run_bash('state_set %s deploy.prod.sha %s' % (state, head), tmp)
    check("unchanged-when-the-sha-matches", unchanged("prod"), True)

    # The rollback case. git is untouched by `vercel rollback`, so the sha and
    # main's HEAD still agree — and production is serving the release before.
    # Answering "unchanged" here is how the fix never gets offered.
    run_bash('state_set %s rollback.prod.code done' % state, tmp)
    check("unchanged-is-false-after-a-rollback", unchanged("prod"), False)

    # And the mark does not stick: the next prod deploy clears it, or the answer
    # would be "changed" for ever and the skip would never work again.
    run_bash('state_set %s rollback.prod.code null' % state, tmp)
    check("unchanged-again-once-the-mark-clears", unchanged("prod"), True)

    # Preview is unaffected by any of it — a different stage with a different
    # question.
    run_bash('state_set %s rollback.prod.code done' % state, tmp)
    wt_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT,
                             capture_output=True, text=True).stdout.strip()
    run_bash('state_set %s deploy.preview.sha %s' % (state, wt_head), tmp)
    check("preview-ignores-the-prod-rollback", unchanged("preview"), True)

    # A dirty tree is not "unchanged" for preview: vercel uploads the working
    # tree rather than the commit.
    with open(os.path.join(WT, "dirt.txt"), "w") as fh:
        fh.write("z\n")
    check("preview-dirty-is-changed", unchanged("preview"), False)
    os.remove(os.path.join(WT, "dirt.txt"))

finally:
    subprocess.run(["git", "worktree", "remove", "--force",
                    os.path.join(tmp, "repo-demo")],
                   cwd=os.path.join(tmp, "repo"), capture_output=True, check=False)
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
