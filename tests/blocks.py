#!/usr/bin/env python3
#
# A test bench for six functions whose failures are silent.
#
# The rule that chose them is not coverage but this: does a mistake here
# announce itself? A function that dies with an error needs no bench — you find
# out. A function that quietly does the wrong thing is how `abandon_traces`
# showed an empty table before an irreversible deletion for months, and how
# `write_vercelignore` never once wrote its file.
#
#   run_block           the epilogue's contract — "what is shown is what runs",
#                       and the chain breaks at the first error. A divergence
#                       here is worse than no list at all, and nothing checked
#                       it.
#   worktree_dirt       decides whether the human is told "you are about to lose
#                       work". Same role as abandon_traces, same cost.
#   branch_has_migrations  decides whether prod gets a db:promote first. Wrong
#                       one way, a pointless promote; wrong the other, code
#                       shipped against a schema that was never pushed.
#   dev_cwd             which tree the server on the port belongs to. Wrong, and
#                       somebody is offered a restart of somebody else's server.
#   push_instruments    pushes after a friction review. Wrong, and a commit that
#                       is not ours rides along.
#   vercel_project_flag the `--project` for a preview. Empty once already, and
#                       it created a spare Vercel project that had to be deleted
#                       by hand.
#
# These run the real functions in a real repository. Where a function shells out
# to something that costs money or reaches the network — vercel, git push — the
# command is shadowed by a stub that records what it was asked to do, because
# the question is what the function decides, not what the world answers.
#
# Run it with: python3 tests/blocks.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")
ROOT_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "sclaude")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def run_bash(script, cwd, modules=("ui", "state", "project", "worktree", "deploy"),
             stdin="", env=None):
    """The real functions in a real shell, with the network shadowed out."""
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
    for name in modules:
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    # die/warn/info/say live in bin/sclaude rather than in a module, and the
    # modules call them freely. Declared here in the same shape — warn to
    # stderr, the rest to stdout — because a bench that let them default to
    # nothing would be exercising a shell the orchestrator never runs.
    body += ('die()  { echo "$*" >&2; exit 1; }\n'
             'warn() { echo "$*" >&2; }\n'
             'info() { echo "$*"; }\n'
             'say()  { echo "$*"; }\n')
    body += script
    out = subprocess.run(["bash", "-c", body], cwd=cwd, input=stdin,
                         capture_output=True, text=True, timeout=30,
                         env=env or dict(os.environ, SCLAUDE_ASK_TTY="0"))
    return out.stdout, out.stderr, out.returncode


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, check=False)


tmp = tempfile.mkdtemp()
try:
    REPO = os.path.join(tmp, "repo")
    os.makedirs(REPO)
    git("init", "-q", "-b", "main", cwd=REPO)
    git("config", "user.email", "t@t", cwd=REPO)
    git("config", "user.name", "T", cwd=REPO)
    os.makedirs(os.path.join(REPO, "supabase", "migrations"))
    with open(os.path.join(REPO, "supabase", "migrations", "0001_a.sql"), "w") as fh:
        fh.write("create table t (id int);\n")
    # The project's own config. branch_has_migrations asks it where migrations
    # live rather than assuming, so a repository that does not say has none —
    # which is the case a few lines further down.
    with open(os.path.join(REPO, ".sclaude.json"), "w") as fh:
        json.dump({"database": {"migrations": "supabase/migrations"}}, fh)
    git("add", "-A", cwd=REPO)
    git("commit", "-qm", "first", cwd=REPO)

    origin = os.path.join(tmp, "origin.git")
    subprocess.run(["git", "clone", "-q", "--bare", REPO, origin],
                   capture_output=True, check=False)
    git("remote", "add", "origin", origin, cwd=REPO)
    git("fetch", "-q", "origin", cwd=REPO)

    # --- run_block -----------------------------------------------------------
    #
    # Its own comment states the contract: "Showing exactly what will be run and
    # then running exactly that is the whole point: a list that diverges from
    # the deed is worse than no list at all." Nothing held it to that.

    marks = os.path.join(tmp, "marks")

    def block(commands, answer="y"):
        """Runs run_block with the given commands and returns (output, rc)."""
        if os.path.exists(marks):
            os.remove(marks)
        quoted = " ".join('"%s"' % c for c in commands)
        out, err, rc = run_bash(
            'ask() { printf -v "$2" %%s "%s"; }\n'
            'run_block "T" "note" "Go?" %s' % (answer, quoted),
            tmp, stdin="")
        # Both streams: `warn` goes to stderr and `say` to stdout, and what is
        # under test is what reaches the person in front of the terminal.
        return out + err, rc

    # Every command is shown, and shown before the question. The human agrees to
    # what they can see.
    out, rc = block(['echo one >> %s' % marks, 'echo two >> %s' % marks])
    check("block-shows-every-command",
          out.count("echo one") + out.count("echo two") >= 2, True)
    check("block-runs-them-all",
          open(marks).read().split(), ["one", "two"])
    check("block-reports-success", rc, 0)
    check_true("block-says-done", "T — done." in out)

    # A refusal runs nothing and is not a failure of the block — it is an
    # answer, and remind_prod reads the code to decide what to offer next.
    out, rc = block(['echo one >> %s' % marks], answer="n")
    check("block-refusal-runs-nothing", os.path.exists(marks), False)
    check("block-refusal-returns-one", rc, 1)
    check_true("block-refusal-says-skipped", "skipped" in out)

    # The chain stops at the first error. This is the one that matters: after a
    # failed `db:promote` there is nothing to ship, and carrying on would deploy
    # code against a schema that was never pushed.
    out, rc = block(['echo one >> %s' % marks, 'false',
                     'echo three >> %s' % marks])
    check("block-stops-at-the-first-error",
          open(marks).read().split(), ["one"])
    check("block-error-returns-nonzero", rc != 0, True)
    check_true("block-error-says-the-rest-did-not-run",
               "The rest of this block did not run" in out)

    # `cd` from the first line survives into the second. The whole block runs in
    # one subshell for this reason, and the prod block leans on it: `cd $REPO`,
    # then `git pull`, then `vercel --prod`.
    out, rc = block(['cd %s' % REPO, 'pwd >> %s' % marks])
    check("block-cd-survives", open(marks).read().strip(), REPO)

    # And it does not leak: the caller's directory is unchanged afterwards.
    out, _, _ = run_bash(
        'ask() { printf -v "$2" %%s y; }\n'
        'run_block "T" "" "Go?" "cd %s" >/dev/null; pwd' % REPO, tmp)
    check("block-cd-does-not-leak", out.strip().split("\n")[-1], tmp)

    # --- worktree_dirt -------------------------------------------------------
    #
    # What the human is shown before the worktree is destroyed. The orchestrator's
    # own files must not appear there: the question has to mean "you are losing
    # work", not "the script left its rubbish".

    with open(os.path.join(REPO, "real.txt"), "w") as fh:
        fh.write("work\n")
    os.makedirs(os.path.join(REPO, ".feature"), exist_ok=True)
    with open(os.path.join(REPO, ".feature", "state.json"), "w") as fh:
        fh.write("{}\n")
    with open(os.path.join(REPO, ".vercelignore"), "w") as fh:
        fh.write(".env\n")

    out, _, _ = run_bash('worktree_dirt %s' % REPO, tmp)
    lines = [l for l in out.splitlines() if l.strip()]
    check_true("dirt-reports-real-work", any("real.txt" in l for l in lines))
    check("dirt-hides-the-feature-dir",
          any(".feature" in l for l in lines), False)
    check("dirt-hides-vercelignore",
          any(".vercelignore" in l for l in lines), False)

    # A clean tree says nothing at all — that is what makes the caller's `if`
    # meaningful.
    os.remove(os.path.join(REPO, "real.txt"))
    out, _, _ = run_bash('worktree_dirt %s' % REPO, tmp)
    check("dirt-silent-when-clean", out.strip(), "")

    # A path that merely starts with a hidden one is not hidden: `.featurex` is
    # somebody's file, and swallowing it would hide real work.
    with open(os.path.join(REPO, ".featurex"), "w") as fh:
        fh.write("mine\n")
    out, _, _ = run_bash('worktree_dirt %s' % REPO, tmp)
    check_true("dirt-does-not-swallow-a-prefix-match", ".featurex" in out)
    os.remove(os.path.join(REPO, ".featurex"))

    # --- branch_has_migrations ----------------------------------------------
    #
    # Decides whether production is offered a db:promote. It compares against
    # origin/main, so a migration already in main is not this branch's.

    git("checkout", "-q", "-b", "feat/plain", cwd=REPO)
    with open(os.path.join(REPO, "code.ts"), "w") as fh:
        fh.write("x\n")
    git("add", "-A", cwd=REPO)
    git("commit", "-qm", "code only", cwd=REPO)
    _, _, rc = run_bash('branch_has_migrations %s' % REPO, tmp)
    check("migrations-false-without-any", rc != 0, True)

    with open(os.path.join(REPO, "supabase", "migrations", "0002_b.sql"), "w") as fh:
        fh.write("alter table t add column c int;\n")
    git("add", "-A", cwd=REPO)
    git("commit", "-qm", "a migration", cwd=REPO)
    _, _, rc = run_bash('REPO=%s; branch_has_migrations %s' % (REPO, REPO), tmp,
                        modules=("ui", "state", "project", "worktree", "deploy"))
    check("migrations-true-when-the-branch-adds-one", rc, 0)

    # --- preview_apply_migrations -------------------------------------------
    #
    # Runs the project's apply from the tree, and never stops the preview: the
    # database is shared, so a refusal there may be another branch's doing.
    alarm_fn = 'alarm() { echo "$*" >&2; }\n'
    cfg = os.path.join(REPO, ".sclaude.json")
    with open(cfg) as fh:
        plain_cfg = fh.read()

    def with_apply(cmd):
        data = json.loads(plain_cfg)
        if cmd is not None:
            data["database"]["applyPreview"] = cmd
        with open(cfg, "w") as fh:
            json.dump(data, fh)

    with_apply(None)
    _, err, rc = run_bash(alarm_fn + 'REPO=%s; preview_apply_migrations %s' % (REPO, REPO), tmp)
    check("apply-without-a-command-does-not-stop-the-preview", rc, 0)
    check_true("apply-without-a-command-says-so", "no applyPreview" in err)

    where = os.path.join(tmp, "applied-from")
    with_apply("pwd > %s" % where)
    _, _, rc = run_bash(alarm_fn + 'REPO=%s; preview_apply_migrations %s' % (REPO, REPO), tmp)
    check("apply-runs-the-command", rc, 0)
    with open(where) as fh:
        check("apply-runs-in-the-tree", os.path.realpath(fh.read().strip()),
              os.path.realpath(REPO))

    with_apply("false")
    _, err, rc = run_bash(alarm_fn + 'REPO=%s; preview_apply_migrations %s' % (REPO, REPO), tmp)
    check("a-failed-apply-is-reported", rc, 1)
    check_true("a-failed-apply-says-the-preview-goes-anyway", "deployed anyway" in err)
    with open(cfg, "w") as fh:
        fh.write(plain_cfg)

    # A project that does not say where migrations live has none as far as the
    # cycle is concerned: no promote is offered and no rollback looks for down
    # blocks. Silence is the answer rather than a guessed directory, which would
    # be this one product's layout applied to somebody else's repository.
    os.rename(os.path.join(REPO, ".sclaude.json"),
              os.path.join(REPO, ".sclaude.json.off"))
    _, _, rc = run_bash('REPO=%s; branch_has_migrations %s' % (REPO, REPO), tmp,
                        modules=("ui", "state", "project", "worktree", "deploy"))
    check("migrations-false-without-a-config", rc != 0, True)
    os.rename(os.path.join(REPO, ".sclaude.json.off"),
              os.path.join(REPO, ".sclaude.json"))

    # A migration that is already in main is not the branch's — otherwise every
    # feature would be offered a promote for somebody else's work.
    git("checkout", "-q", "main", cwd=REPO)
    _, _, rc = run_bash('branch_has_migrations %s' % REPO, tmp)
    check("migrations-false-on-main-itself", rc != 0, True)

    # --- vercel_project_flag -------------------------------------------------
    #
    # Empty once already, and a `vercel` without it created a second project on
    # hosting that had to be deleted by hand.

    os.makedirs(os.path.join(REPO, ".vercel"), exist_ok=True)
    with open(os.path.join(REPO, ".vercel", "project.json"), "w") as fh:
        json.dump({"projectId": "x", "projectName": "agora"}, fh)
    out, _, _ = run_bash('REPO=%s; vercel_project_flag' % REPO, tmp)
    check("project-flag-from-the-link", out, " --project agora")

    # Nothing readable means nothing printed rather than a broken flag: a
    # ` --project ` with no name would make vercel fail on a flag instead of
    # deploying.
    with open(os.path.join(REPO, ".vercel", "project.json"), "w") as fh:
        fh.write("{not json")
    out, _, _ = run_bash('REPO=%s; vercel_project_flag' % REPO, tmp)
    check("project-flag-empty-when-unreadable", out, "")

    os.remove(os.path.join(REPO, ".vercel", "project.json"))
    out, _, _ = run_bash('REPO=%s; vercel_project_flag' % REPO, tmp)
    check("project-flag-empty-without-a-link", out, "")

    # An apostrophe in the path is why this reads the file through an argument
    # rather than through the source. The check is that it survives at all.
    odd = os.path.join(tmp, "it's")
    os.makedirs(os.path.join(odd, ".vercel"))
    with open(os.path.join(odd, ".vercel", "project.json"), "w") as fh:
        json.dump({"projectName": "agora"}, fh)
    out, _, _ = run_bash('REPO="%s"; vercel_project_flag' % odd, tmp)
    check("project-flag-survives-an-apostrophe", out, " --project agora")

    # --- dev_cwd -------------------------------------------------------------
    #
    # Which tree a running server belongs to. The port is shared, so this is what
    # decides whether the human is told "another feature's server is on 3000".

    sleeper = subprocess.Popen(["sleep", "20"], cwd=REPO)
    try:
        out, _, _ = run_bash('dev_cwd %d' % sleeper.pid, tmp)
        check("dev-cwd-names-the-directory", out.strip(), os.path.realpath(REPO))
    finally:
        sleeper.kill()
        sleeper.wait()

    # A pid that is gone answers nothing rather than guessing, and an empty
    # argument is refused: `readlink /proc//cwd` would otherwise resolve to
    # something.
    out, _, rc = run_bash('dev_cwd 999999', tmp)
    check("dev-cwd-silent-for-a-dead-pid", out.strip(), "")
    out, _, rc = run_bash('dev_cwd ""', tmp)
    check("dev-cwd-refuses-an-empty-pid", rc != 0, True)

    # --- push_instruments ----------------------------------------------------
    #
    # Pushes the friction review's commits. `git push` is stubbed: what is under
    # test is when it decides to push, not whether GitHub accepts it.

    INST = os.path.join(tmp, "inst")
    os.makedirs(INST)
    git("init", "-q", "-b", "main", cwd=INST)
    git("config", "user.email", "t@t", cwd=INST)
    git("config", "user.name", "T", cwd=INST)
    with open(os.path.join(INST, "a"), "w") as fh:
        fh.write("1\n")
    git("add", "-A", cwd=INST)
    git("commit", "-qm", "first", cwd=INST)
    inst_origin = os.path.join(tmp, "inst-origin.git")
    subprocess.run(["git", "clone", "-q", "--bare", INST, inst_origin],
                   capture_output=True, check=False)
    git("remote", "add", "origin", inst_origin, cwd=INST)
    git("fetch", "-q", "origin", cwd=INST)

    pushlog = os.path.join(tmp, "pushed")

    def push(inst=INST):
        if os.path.exists(pushlog):
            os.remove(pushlog)
        out, _, _ = run_bash(
            'INSTRUMENTS=%s\n'
            'git() { if [[ "$*" == *" push "* ]]; then echo "$*" >> %s; return 0; fi; '
            'command git "$@"; }\n'
            'push_instruments' % (inst, pushlog),
            tmp, modules=("ui", "state", "run"))
        return out

    # Nothing ahead of origin: silent, and no push. This is the ordinary case —
    # the function is called on the way into a feature too.
    out = push()
    check("push-silent-with-nothing-to-send", out.strip(), "")
    check("push-does-not-push-nothing", os.path.exists(pushlog), False)

    # One commit ahead: it pushes, and says how many.
    with open(os.path.join(INST, "a"), "w") as fh:
        fh.write("2\n")
    git("commit", "-qam", "second", cwd=INST)
    out = push()
    check_true("push-sends-when-ahead", os.path.exists(pushlog))
    check_true("push-counts-the-commits", "1 commit(s)" in out)
    if os.path.exists(pushlog):
        check_true("push-names-the-branch", "origin main" in open(pushlog).read())

    # A detached HEAD is not a branch, and pushing from one would send a commit
    # to whatever name happened to resolve. Two things stop it — the explicit
    # `!= "HEAD"` and, behind it, `rev-list origin/HEAD..HEAD` failing — so this
    # asserts on the guard itself as well as on the outcome. Without that, a
    # removed guard still passes on the accident of the second one, which is how
    # a test comes to describe a defence that is no longer there.
    sha = git("rev-parse", "HEAD", cwd=INST).stdout.strip()
    git("checkout", "-q", sha, cwd=INST)
    out = push()
    check("push-refuses-a-detached-head", os.path.exists(pushlog), False)
    run_src = open(os.path.join(LIB, "run.sh"), encoding="utf-8").read()
    check_true("push-names-the-detached-head-explicitly",
               '"$branch" != "HEAD"' in run_src)
    git("checkout", "-q", "main", cwd=INST)

    # No origin at all: counting what origin lacks would count every commit,
    # and the function must answer nothing rather than push somewhere.
    lone = os.path.join(tmp, "lone")
    os.makedirs(lone)
    git("init", "-q", "-b", "main", cwd=lone)
    git("config", "user.email", "t@t", cwd=lone)
    git("config", "user.name", "T", cwd=lone)
    with open(os.path.join(lone, "a"), "w") as fh:
        fh.write("1\n")
    git("add", "-A", cwd=lone)
    git("commit", "-qm", "only", cwd=lone)
    out = push(lone)
    check("push-silent-without-an-upstream", out.strip(), "")
    check("push-does-not-push-without-an-upstream", os.path.exists(pushlog), False)

    # --- the rollback's own silent failures ----------------------------------
    #
    # Three findings from a review of this work, each the same shape as the bugs
    # the bench above exists for: nothing failed, and the wrong thing was
    # reported.

    rollback_src = open(os.path.join(LIB, "rollback.sh"), encoding="utf-8").read()

    # A failed psql was reported as a successful schema revert. `rc=1` is itself
    # a command, so it resets PIPESTATUS to (0), and `${PIPESTATUS[0]:-$rc}`
    # found a set, non-empty zero and never fell back. The `partial` branch was
    # unreachable: production was half-reverted, the operator was told it was
    # back, `reverted` went into the incident and the metrics, and the schema
    # dump ran against a half-reverted database.
    # Read as code: the fix leaves a comment quoting the broken line verbatim,
    # which is what makes it useful to the next reader — and a plain substring
    # search would find the explanation and call the bug present.
    def code_lines(text):
        return [ln for ln in text.splitlines() if not ln.strip().startswith("#")]

    check_true("psql-status-is-not-read-from-PIPESTATUS",
               not any("PIPESTATUS[0]:-$rc" in ln for ln in code_lines(rollback_src)))
    check_true("psql-status-is-rc",
               re.search(r'-f "\$sql"(?:.|\n){0,200}?if \[\[ "\$rc" -eq 0 \]\]',
                         rollback_src) is not None)

    # The shape itself, run for real: this is what made the bug invisible.
    out, _, _ = run_bash(
        'if (exit 3) | sed "s/^/  /"; then rc=0; else rc=1; fi\n'
        'echo "rc=$rc pipestatus=${PIPESTATUS[0]}"', tmp, modules=())
    check("assignment-resets-pipestatus", out.strip(), "rc=1 pipestatus=0")

    # The confirmation run must tell "could not run" from "red". Every other
    # caller in the cycle does; this one reported a suite that never ran as
    # production still being broken, and paged somebody about it.
    # Inside the function, not merely somewhere in the file: the first version
    # of this check searched the whole source, and a mutation that deleted the
    # guard from rollback_confirm still passed on another function's copy. A
    # test that greps the file for a defence is a test that cannot tell where
    # the defence is.
    confirm_body = rollback_src[rollback_src.index("rollback_confirm() {"):]
    confirm_body = confirm_body[:confirm_body.index("\n}")]
    check_true("confirmation-separates-could-not-run",
               '"$rc" -eq 2' in confirm_body)
    check_true("confirmation-does-not-page-on-could-not-run",
               '"$rc" -eq 2' in confirm_body
               and confirm_body.index('"$rc" -eq 2') < confirm_body.index("sclaude-notify"))

    # The poll is what decides, as the function's own comment always claimed.
    # Throwing it away meant a rollback that landed after `--timeout` expired
    # was reported as a failure — and then nothing downstream ran: no
    # confirmation, no incident, no rewind, and no mark to stop the next pass
    # skipping the fix.
    check_true("poll-result-is-kept", "settled=1" in rollback_src)
    check_true("poll-result-decides",
               re.search(r'\$settled" -eq 1 && "\$waited" -gt 0', rollback_src) is not None)

    # And the progress line only where somebody is watching: under a pipe it
    # would write raw escape codes into a log that nothing ever clears.
    check_true("rollback-progress-line-guarded",
               re.search(r'\[\[ -t 1 \]\] && printf .\\r\\033\[2K  waiting',
                         rollback_src) is not None)

    # The typed command gates on having shipped, as the action list does.
    sclaude_src = open(os.path.join(ROOT_BIN), encoding="utf-8").read()
    cmd_body = sclaude_src[sclaude_src.index("cmd_rollback() {"):]
    cmd_body = cmd_body[:cmd_body.index("\n}")]
    # Code only, again — and this one earned the rule a third time. The comment
    # explaining the gate names `deploy.prod.sha`, so a mutation that deleted
    # the gate itself left the string behind and the check passed. Three
    # findings in this bench have now had the same shape: a test that reads
    # prose is a test that cannot see the code go.
    cmd_code = "\n".join(code_lines(cmd_body))
    check_true("cmd-rollback-gates-on-a-shipped-feature",
               "deploy.prod.sha" in cmd_code)
    check_true("cmd-rollback-gates-before-acting",
               "deploy.prod.sha" in cmd_code
               and cmd_code.index("deploy.prod.sha") < cmd_code.index("rollback_prod"))

finally:
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
