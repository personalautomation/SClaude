#!/usr/bin/env python3
#
# A test bench for the regression gate: which parts a stage runs, what command
# each part becomes, and how a run is summarised.
#
# These are the pure halves of sclaude/lib/regression.sh — the ones that decide
# what will be run before anything is. They are worth a bench precisely because
# a mistake in them is silent: a stage that quietly runs no parts reports itself
# green, and a gate that reports green is a gate that is not there.
#
# The shell is read as text rather than sourced. Sourcing would need bash, the
# whole module list, and the three output helpers that live in bin/sclaude
# rather than in lib/ — while what is checked here is the tables, and those are
# constants in the file.
#
# Run it with: python3 tests/regression.py
import json
import os
import re
import sys


def _cfg(path):
    """The path of a product's config, its .sclaude/ folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib"))

regression = open(os.path.join(ROOT, "sclaude", "lib", "regression.sh"),
                  encoding="utf-8").read()
github = open(os.path.join(ROOT, "sclaude", "lib", "github.sh"),
              encoding="utf-8").read()
# The prompt a fixing session is opened with. It is checked here rather than in
# a bench of its own because what it sanctions and what the gate does about it
# are one mechanism: the file tells the session it may end by writing a note,
# and regression.sh only means it if it reads that note back.
fail_prompt = open(os.path.join(ROOT, "sclaude", "prompts",
                                "_regression-fail.md"), encoding="utf-8").read()

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def shell_const(text, name):
    """The value of a top-level variable from a shell module."""
    found = re.search(r'^%s="([^"]*)"' % name, text, re.M)
    return found.group(1) if found else None


# --- the stages, which are now the project's to declare ----------------------
#
# These were two strings in regression.sh, and the assertions here were about
# them. They moved into `.sclaude/config.json` (project.sh), because a table inside the
# orchestrator that happened to match one product is exactly what "not tied to
# any project" was failing to be.
#
# So the checks move with them, and they change shape: what the orchestrator
# must do is read the config and refuse to invent one; what the *product* must
# declare is a complete local stage. The first is asserted here, the second
# against the real config where it is checked out.

# No table survives in the source. A reintroduced default would work silently in
# the wrong repository, which is the failure this whole change removes.
check_true("no-local-parts-table",
           shell_const(regression, "REGRESSION_LOCAL_PARTS") is None)
check_true("no-deployed-parts-table",
           shell_const(regression, "REGRESSION_DEPLOYED_PARTS") is None)
check_true("stages-come-from-the-project",
           "project_regression_parts" in regression)
# And no hardcoded production host: the address decides which database a
# write-capable suite reaches, so a literal fallback aimed one product's suite
# at another's production.
check_true("no-hardcoded-prod-host",
           re.search(r"https://[\w.-]+\.(?:vercel\.app|com|org|net)\b", regression) is None)
check_true("prod-url-comes-from-the-project", "project_prod_url" in regression)

# A stage the project does not describe is not a red run. `regression_run`
# answers 2 — "could not run" — and the gate must not spend a fixing session on
# it: no amount of editing the code conjures a suite nobody declared.
check_true("undeclared-stage-cannot-run",
           re.search(r'if \[\[ -z "\$parts" \]\]; then(?:.|\n){0,400}?return 2',
                     regression) is not None)
# Nor may it hold the cycle. A deployed stage with no address is a deploy that
# did not happen and the step waits; a stage nobody declared has nothing to wait
# for, and blocking there would mean a repository without a suite could never
# close a step at all.
check_true("undeclared-stage-does-not-block",
           re.search(r'\[\[ -z "\$\(regression_parts "\$stage" "\$wt"[^\n]*\]\] && return 0',
                     regression) is not None)

# The command for a part comes from the project too, and a part with no command
# is a failure rather than a skip — a suite that quietly drops one check reports
# green on work it never did.
check_true("commands-come-from-the-project", "project_command" in regression)
check_true("missing-command-is-fatal", "no command for this part" in regression)

# --- the board's columns ----------------------------------------------------
#
# They were literals here — "Backlog", "In progress", "In QA", "Done" — one
# team's board applied to every other team's. They are now `board` in the
# project's .sclaude/config.json, loaded by board_load (project.sh), and the literal
# spellings must not come back.
for name, text in (("github.sh", github),
                   ("sclaude-watch", open(os.path.join(ROOT, "bin", "sclaude-watch"),
                                          encoding="utf-8").read())):
    for const in ("PROGRESS_FROM", "PROGRESS_TO", "QA_FROM", "QA_TO", "QA_BACK",
                  "QA_DONE", "PROGRESS_DATE_FIELD", "PROGRESS_END_FIELD"):
        check("no-literal-%s-in-%s" % (const, name), shell_const(text, const), None)
check_true("no-literal-label", "--label Dev" not in github)
check_true("no-literal-type", "--type Feature" not in github)

import subprocess as _sp
import tempfile as _tf


def board(config, body):
    """Run a snippet with project.sh loaded against a repo holding `config`."""
    with _tf.TemporaryDirectory() as tmp:
        if config is not None:
            with open(_cfg(os.path.join(tmp, ".sclaude/config.json")), "w") as fh:
                json.dump(config, fh)
        script = 'REPO=%s\nsource %s/sclaude/lib/project.sh\nboard_load\n%s\n' % (
            tmp, ROOT, body)
        return _sp.run(["bash", "-c", script], capture_output=True,
                       text=True).stdout.strip()


VARS = 'echo "$PROGRESS_FROM|$PROGRESS_TO|$QA_FROM|$QA_TO|$QA_DONE|' \
       '$PROGRESS_DATE_FIELD|$PROGRESS_END_FIELD|$ISSUE_LABEL|$ISSUE_TYPE"'
FULL = {"board": {
    "columns": {"backlog": "Todo", "progress": "Doing", "qa": "Check",
                "done": "Shipped"},
    "dates": {"start": "Began", "end": "Ended"},
    "issue": {"label": "dev work", "type": "Task"}}}
check("board-loaded", board(FULL, VARS),
      "Todo|Doing|Doing|Check|Shipped|Began|Ended|dev work|Task")
check("board-absent-is-empty", board(None, VARS), "||||||||")
check("board-partial", board({"board": {"columns": {"qa": "Check"}}}, VARS),
      "|||Check|||||")

# An empty name is a move not made: no gh call at all. gh is a function here
# that would say so if it were reached.
check("board-empty-moves-nothing", board(None, """
info() { :; }; warn() { :; }
gh() { echo CALLED >> "$REPO/gh-calls"; }; gh_repo() { echo o/r; }
source %s/sclaude/lib/github.sh
issue_qa_ready 7
issue_start_progress 7
cat "$REPO/gh-calls" 2>/dev/null
""" % ROOT), "")

# A project with no `board` section at all is told once why nothing moved —
# before the names moved into .sclaude/config.json every project had the same four
# columns, and losing them silently is the failure. A section that leaves a
# column out is a choice and is not remarked on.
NOTICE = """
info() { echo "INFO $*"; }; warn() { :; }
gh() { :; }; gh_repo() { echo o/r; }
source %s/sclaude/lib/github.sh
issue_qa_ready 7
issue_start_progress 7
""" % ROOT
told = board({"commands": {}}, NOTICE)
check("no-board-section-told-once", told.count("has no `board`"), 1)
check("partial-board-not-remarked",
      "has no `board`" in board({"board": {"columns": {"qa": "Check"}}}, NOTICE), False)

# A watch armed before the names moved has no `columns`; it is read with the
# names every board was assumed to have then. Driven through the real watcher
# with gh answering "Done".
with _tf.TemporaryDirectory() as wtmp:
    watch_dir = os.path.join(wtmp, ".claude", "sclaude", "watch")
    os.makedirs(watch_dir)
    stubs = os.path.join(wtmp, "bin")
    os.makedirs(stubs)
    with open(os.path.join(stubs, "gh"), "w") as fh:
        fh.write("#!/usr/bin/env bash\n"
                 "echo \'{\"data\":{\"repository\":{\"issue\":{\"projectItems\":"
                 "{\"nodes\":[{\"fieldValueByName\":{\"name\":\"Done\"}}]}}}}}\'\n")
    os.chmod(os.path.join(stubs, "gh"), 0o755)

    def verdict(extra):
        path = os.path.join(watch_dir, "demo.json")
        data = {"feature": "demo", "issue": 7, "repo": "o/r", "status": "In QA",
                "since": "2026-09-22T12:00:00+00:00"}
        data.update(extra)
        with open(path, "w") as fh:
            json.dump(data, fh)
        _sp.run([os.path.join(ROOT, "bin", "sclaude-watch")], capture_output=True,
                env=dict(os.environ, HOME=wtmp, PATH=stubs + ":" + os.environ["PATH"]),
                timeout=60)
        return json.load(open(path)).get("verdict")

    check("old-watch-uses-old-names", verdict({}), "done")
    check("new-watch-uses-its-names",
          verdict({"columns": {"back": "Doing", "done": "Shipped"}}), "other")

# The watcher runs with no project in reach, so watch_start hands it the names.
watch_src = open(os.path.join(ROOT, "sclaude", "lib", "watch.sh"), encoding="utf-8").read()
check_true("watch-file-carries-back", 'state_set "$file" columns.back "$QA_FROM"' in watch_src)
check_true("watch-file-carries-done", 'state_set "$file" columns.done "$QA_DONE"' in watch_src)
watcher = open(os.path.join(ROOT, "bin", "sclaude-watch"), encoding="utf-8").read()
check_true("watcher-reads-back", 'field "$file" columns.back' in watcher)
check_true("watcher-reads-done", 'field "$file" columns.done' in watcher)
# Backlog is a hand-back as much as In progress is, for the timer too.
check_true("watch-file-carries-backlog",
           'state_set "$file" columns.backlog "$PROGRESS_FROM"' in watch_src)
check_true("watcher-reads-backlog", 'field "$file" columns.backlog' in watcher)
check_true("watcher-can-be-quiet", "SCLAUDE_WATCH_QUIET" in watcher)

# The watch must record the column the issue is actually in. It used to write
# QA_TO unconditionally, which made the watcher's first comparison a false alarm
# whenever the QA move had not gone through — the case this whole guard exists
# for. The literal spelling is what would reintroduce it.
watch_sh_early = open(os.path.join(ROOT, "sclaude", "lib", "watch.sh"), encoding="utf-8").read()
check_true("watch-status-not-assumed",
           'state_set "$file" status "$QA_TO"' not in watch_sh_early)

# The mark a comment is judged new against must be UTC. GitHub timestamps in
# UTC and sclaude-watch compares the two as strings, so a mark carrying a local
# offset is silently wrong by that offset — and wrong in the direction that
# drops comments rather than repeating them, which is the direction nobody
# notices. `date -Iseconds` is the spelling that would reintroduce it.
watch_sh = open(os.path.join(ROOT, "sclaude", "lib", "watch.sh"), encoding="utf-8").read()
since_line = re.search(r'state_set "\$file" since "(.*)"', watch_sh)
check_true("watch-since-exists", since_line is not None)
if since_line:
    check_true("watch-since-is-utc", "date -u" in since_line.group(1))
    check_true("watch-since-not-local", "date -Iseconds" not in since_line.group(1))


# --- the fix session --------------------------------------------------------

# A local failure is the code's, and code is written in step 2. A deployed one
# lands on a branch that is already a pull request, and review is the step that
# pushes to it.
fix_case = re.search(r"regression_fix_step\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("fix-step-exists", fix_case is not None)
if fix_case:
    body = fix_case.group(1)
    check_true("fix-local-is-code", re.search(r"local\)\s*printf 'code'", body) is not None)
    check_true("fix-default-is-review", re.search(r"\*\)\s*printf 'review'", body) is not None)

# The gate must return non-zero when a run fails, or a red regression closes the
# step anyway. The shape is run_friction's: callers write `if ! regression_gate`.
gate = re.search(r"regression_gate\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("gate-exists", gate is not None)
if gate:
    body = gate.group(1)
    check_true("gate-returns-1-on-failure", "return 1" in body)
    check_true("gate-calls-fix", "regression_fix" in body)
    # The loop: a red run is fixed and run again, rather than reported and
    # abandoned. Without the loop the gate is the dead end it used to be.
    check_true("gate-loops", "while" in body)
    check_true("gate-rewinds", "regression_rewind" in body)
    # "Could not run" must not be treated as "ran and failed": a missing
    # preview address means no deploy happened, and a fixing session has
    # nothing to repair. It used to burn both attempts on it.
    check_true("gate-distinguishes-cannot-run", "-eq 2" in body)

# The limit exists, is two, and is read from one named place rather than
# spelled inline where a second copy could drift.
check("max-attempts", shell_const(regression, "REGRESSION_MAX_ATTEMPTS"), "2")
check_true("gate-uses-the-constant",
           gate is not None and "REGRESSION_MAX_ATTEMPTS" in gate.group(1))
# The limit stops the machine, not the human. Reaching it used to return 1 with
# nothing but a warning, which left the feature with no way forward but
# `sclaude reset` — and the person who has just read the log is the one who
# knows whether a third session is worth it: they may have fixed the cause by
# hand, or changed the environment under it.
if gate is not None:
    exhausted = gate.group(1)
    check_true("limit-asks-rather-than-stopping", "ask " in exhausted)
    check_true("limit-clears-the-count-on-yes",
               re.search(r'is_yes.*\n(?:.*\n)*?.*regression\.\$stage\.attempts" 0',
                         exhausted) is not None)
    # And "yes" means another fixing session, NOT another run of the same
    # suite. The top of the loop is regression_run, so a `continue` here would
    # send the answer back to the one thing already known to be pointless: the
    # same specs against the same address with the same tree fail the same way.
    # The branch falls through to regression_fix below instead.
    # Only the limit branch: the orchestrator-fix path further down does go
    # round the loop on purpose, because there the code under the run changed.
    limit_branch = exhausted[exhausted.find('-ge "$REGRESSION_MAX_ATTEMPTS"'):
                             exhausted.find('regression_fix "$wt"')]
    check_true("limit-branch-found", "ask " in limit_branch)
    check_true("limit-does-not-rerun-on-yes", "continue" not in limit_branch)
    # Falling through is only worth anything if something follows: the branch
    # must not return on the way out of the yes side.
    check_true("limit-falls-through-to-the-fix",
               re.search(r'is_yes.*\n(?:(?!\bfi\b).*\n)*?\s*else\b', exhausted)
               is not None)

# A cause outside the worktree is a third outcome, neither "fixed" nor "failed
# to fix". Without it a session that correctly finds the deployment pointing at
# a different bucket has no sanctioned way to end: the prompt tells it to fix
# the cause and re-run, so it spends its last turns arguing to be let go, and
# the gate answers by counting the attempt and running the same suite again.
check_true("fail-prompt-sanctions-a-blocked-ending",
           "regression.blocked" in fail_prompt)
check_true("fail-prompt-forbids-faking-green",
           "change nothing" in fail_prompt)
check_true("fix-reports-blocked",
           re.search(r'regression\.blocked"?\s*\]\]\s*&&\s*return 3', regression)
           is not None)
if gate is not None:
    # Not `body`: that name is assigned by half a dozen blocks in this file,
    # and a module-level rebind here would hand the next one my value.
    blocked_body = gate.group(1)
    check_true("gate-handles-blocked", '-eq 3' in blocked_body)
    # The whole point of the third outcome: a conclusion that another session
    # would only repeat must not cost one of the two attempts.
    check_true("gate-refunds-the-blocked-attempt",
               re.search(r'-eq 3.*\n(?:.*\n)*?.*attempts" "\$attempts"',
                         blocked_body) is not None)
# The note is addressed to the human, so the run must not destroy it on its way
# to re-deriving it. An earlier version cleared it at the head of regression_run
# and so spent four minutes of suite plus a fixing session reproducing a
# conclusion that was already written down.
run_fn = re.search(r'\nregression_run\(\) \{\n(.*?)\n\}\n', regression, re.S)
check_true("run-found", run_fn is not None)
if run_fn is not None:
    check_true("run-keeps-the-blocked-note",
               "regression.blocked" not in run_fn.group(1))
if gate is not None:
    # Only the pre-flight, not the whole gate. The limit block further down has
    # an `ask` and an `else` of its own, and guards written against the whole
    # body matched those instead: dropping the pre-flight's question entirely
    # left them green. Two mutations passed that way before this was narrowed.
    preflight_m = re.search(r'\n  local note=(.*?)\n  local rc\b',
                            gate.group(1), re.S)
    check_true("preflight-found", preflight_m is not None)
    preflight = preflight_m.group(1) if preflight_m else ""
    # Before anything is spent: a note means the previous pass already learned
    # what this run would learn again.
    check_true("gate-asks-before-rerunning-a-blocked-stage",
               re.search(r'\bask\b', preflight) is not None)
    # Cleared where it is answered, and only there.
    check_true("gate-clears-the-note-on-yes",
               re.search(r'is_yes.*\n\s*rm -f "\$note"', preflight) is not None)
    # A "no" must not fall through into the run: that is the whole saving.
    check_true("gate-declines-to-run-while-blocked",
               re.search(r'\belse\b(?:.*\n)*?\s*return 1', preflight) is not None)
# The count survives an interrupted session, so it lives in the state file.
check_true("attempts-in-state", "regression.$stage.attempts" in regression)

# The rewind puts the cycle back on the step the fix belongs to.
rewind = re.search(r"regression_rewind\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("rewind-exists", rewind is not None)
if rewind:
    body = rewind.group(1)
    check_true("rewind-local-is-noop", re.search(r"local\)\s*return 0", body) is not None)
    check_true("rewind-preview-to-review", "rewind=(review)" in body)
    # Production rewinds to the review too, and deliberately NOT to step 3.
    # A merged pull request is closed on GitHub's side and cannot be reopened,
    # so the fix does need its own — but step 3 cannot tell a new one from the
    # merged one: capture_pr asks `gh pr view`, which on that branch still
    # answers with the old number, and the step's check is only that a number
    # exists. Rewinding into a step that closes itself on stale evidence buys
    # nothing; the review session opens the new pull request instead.
    check_true("rewind-prod-excludes-pr", "rewind=(pr review)" not in body)
    # The clearing itself moved into step_rewind_to (steps.sh): `cmd_replan` and
    # the QA hand-back want the same four lines, differing only in which steps
    # they name. What must hold is that the rewind still goes through it — and
    # that the helper still clears both fields, since a `finished` left from a
    # previous pass claims in the issue's summary a completeness that is gone.
    check_true("rewind-uses-the-shared-helper", "step_rewind_to" in body)
    steps_src = open(os.path.join(ROOT, "sclaude", "lib", "steps.sh"),
                     encoding="utf-8").read()
    helper = re.search(r"step_rewind_to\(\)\s*\{(.*?)\n\}", steps_src, re.S)
    check_true("shared-helper-found", helper is not None)
    if helper:
        hb = helper.group(1)
        check_true("rewind-clears-done", 'steps.$s.done" false' in hb)
        check_true("rewind-clears-finished", 'steps.$s.finished" null' in hb)
        # Only a step that had closed is cleared: writing `finished` as null for
        # one that never ran would put it into the state as a step that did.
        check_true("rewind-only-touches-closed-steps",
                   'steps.$s.done" 2>/dev/null || echo false)" == "true" ]] || continue' in hb)

# The gate is wired into after_step, and before the step is recorded done —
# otherwise it gates nothing.
run_sh = open(os.path.join(ROOT, "sclaude", "lib", "run.sh"), encoding="utf-8").read()
check_true("gate-wired-into-after-step", "regression_gate" in run_sh)
gate_at = run_sh.find("regression_gate")
done_at = run_sh.find('state_set "$state" "steps.$step.done" true')
check_true("gate-before-done", -1 < gate_at < done_at)

# The two deployed stages must not swallow the gate's verdict.
#
# Both used to: prod with a literal `|| true`, preview with an `else` that
# printed a line and carried on. That was harmless while the gate was a
# one-shot check, and is not now — a red deployed stage means the gate has
# already rewound the cycle to step 4, so continuing on to the merge, the
# clean-up and production offers to delete the worktree the next fixing
# session needs.
deploy = open(os.path.join(ROOT, "sclaude", "lib", "deploy.sh"), encoding="utf-8").read()
check_true("prod-gate-not-swallowed",
           re.search(r'regression_gate "\$wt" "\$slug" prod \|\| true', deploy) is None)
# Production does not go through the gate at all, and that is the point.
#
# The gate's loop is run → fix → run, up to two fixing sessions. On local and
# preview that is right: nobody is looking at the deployment, and the only cost
# of a red run is time. On prod it meant two Opus sessions against a live broken
# production while the label on the issue said so and nothing did anything about
# it.
#
# So the prod path runs the suite itself and, on red, restores production first.
# These three checks pin that order; a future edit that puts the gate back, or
# that slides a fixing session above the rollback, fails here.
check_true("prod-does-not-use-the-gate",
           re.search(r'regression_gate "\$wt" "\$slug" prod', deploy) is None)
check_true("prod-runs-the-suite-itself",
           re.search(r'regression_run "\$wt" "\$slug" prod', deploy) is not None)
run_at = deploy.find('regression_run "$wt" "$slug" prod')
rollback_at = deploy.find('rollback_prod "$wt" "$slug" --auto')
check_true("prod-rolls-back-after-its-own-run", -1 < run_at < rollback_at)

# And nothing that fixes may stand between the red run and the rollback. The
# window is counted over code rather than raw lines, as the preview check below
# does, because the branch carries the paragraph explaining why.
between = [ln for ln in deploy[run_at:rollback_at].splitlines()
           if ln.strip() and not ln.strip().startswith("#")]
check_true("nothing-fixes-before-the-rollback",
           not any("regression_fix" in ln or "regression_gate" in ln
                   for ln in between))

# The confirmation run is a stage of its own, never the gate. A red one must not
# open a fixing session: what failed is the release *before* this feature, and no
# session on this branch can mend it.
rollback_sh = open(os.path.join(ROOT, "sclaude", "lib", "rollback.sh"),
                   encoding="utf-8").read()
check_true("confirmation-is-its-own-stage",
           re.search(r'regression_run "\$wt" "\$slug" rollback', rollback_sh) is not None)
check_true("confirmation-never-gated",
           'regression_gate "$wt" "$slug" rollback' not in rollback_sh + deploy)
# A write, specifically: the incident report reads regression.prod.failed_at to
# say what broke, and the module's own comment names the field it is careful not
# to write. Matching the bare name would fail on both and teach the next reader
# that the check is noise.
check_true("confirmation-does-not-write-prod-status",
           re.search(r'state_set[^\n]*regression\.prod\.status', rollback_sh) is None)
check_true("confirmation-writes-no-prod-verdict-anywhere",
           re.search(r'state_set[^\n]*"regression\.prod\.', rollback_sh) is None)

# The three guards that keep a rollback's green from being read as the feature's.
# None of them needed changing when the stage was added — each already ignores an
# unknown stage — and that is exactly why they are pinned: a later widening of
# any one would silently turn "production works again" into "the feature works".
check_true("clear-mark-skips-unknown-stages",
           re.search(r'\[\[ "\$stage" == "preview" \|\| "\$stage" == "prod" \]\] \|\| return 0',
                     regression) is not None)
check_true("rewind-skips-unknown-stages",
           re.search(r'\*\)\s*return 0 ;;', regression) is not None)
github_sh = open(os.path.join(ROOT, "sclaude", "lib", "github.sh"), encoding="utf-8").read()
label_fn = github_sh[github_sh.index("regression_red_label() {"):]
label_fn = label_fn[:label_fn.index("\n}")]
check_true("no-red-label-for-the-rollback-stage", "rollback" not in label_fn)

# The preview stage still stops the epilogue rather than falling through: a red
# deployed stage has rewound the cycle to step 4, so carrying on to the merge and
# the clean-up would offer to delete the worktree the next fixing session needs.
for stage in ("preview",):
    tail = deploy.split('regression_gate "$wt" "$slug" %s' % stage, 1)
    check_true("%s-gate-present" % stage, len(tail) == 2)
    if len(tail) == 2:
        # Within the lines after the call, the red path returns. The window is
        # counted over code rather than raw lines: the red branch carries a
        # comment explaining why it claims no deploy label, and a raw count
        # turned that explanation into a failure — the check would be measuring
        # how much prose sits above the `return`, which is not what it is for.
        window = [ln for ln in tail[1].splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
        check_true("%s-red-path-returns" % stage, "return 0" in "\n".join(window[:16]))

# The prod path returns too, by each of its three exits.
prod_tail = deploy[run_at:]
check_true("prod-red-path-returns", prod_tail.count("return 0") >= 3)

# Entering step 4 must invalidate step 2's verdict.
#
# This one was found by review after the fact, and it mattered: without the
# reset the gate at the end of the review short-circuits on `passed` and runs
# nothing at all — which is precisely the case it was added for, since step 4
# pushes fixes to the branch and step 2's green run was about earlier code.
#
# Now narrowed: a verdict that names the tree it was about is kept, and the
# gate compares that tree with the worktree's, so a review that changed nothing
# does not run the suite twice. One without a tree is still cleared here, and
# a changed tree is cleared by the gate (tests/review-skip.py runs both).
check_true("review-entry-clears-local-status",
           re.search(r'if \[\[ "\$step" == "review" \]\]; then(?:.|\n)*?'
                     r'\|\| state_set "\$state" regression\.local\.status null',
                     run_sh) is not None)
check_true("gate-clears-a-verdict-about-another-tree",
           re.search(r'"\$was" == "\$now"(?:.|\n)*?state_set "\$state" regression\.local\.status null',
                     regression) is not None)

# An unhandled part stops the run rather than being skipped: a summary that
# reports green while quietly not running one of its checks is worse than a
# loud failure over a typo in the table.
check_true("unhandled-part-is-fatal",
           "no command for this part" in regression)
check_true("unhandled-part-not-skipped",
           'regression_command "$part" "$base")" || continue' not in regression)

# The notifier is addressed by path, not by PATH: a run from a systemd unit or
# any context without ~/.local/bin would otherwise lose every notification
# silently, since the calls are deliberately wrapped in `|| true`.
check_true("notifier-resolved-by-path",
           re.search(r'^\s*sclaude-notify ', regression, re.M) is None)
# Through notify_feature (io.sh), which sends it to the feature's topic and
# itself addresses the notifier by path.
check_true("notifier-uses-instruments",
           'notify_feature "$slug"' in regression
           and '"${INSTRUMENTS:-}/bin/sclaude-notify"'
           in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                "sclaude", "lib", "io.sh")).read())

# What the watcher found is consumed once. Left uncleared, the same QA
# comments were prepended to every later resume — and suppressed the accurate
# review_news message, because the QA branch is tested first.
watch_sh_2 = open(os.path.join(ROOT, "sclaude", "lib", "watch.sh"),
                  encoding="utf-8").read()
check_true("watch-seen-exists", re.search(r"^watch_seen\(\)", watch_sh_2, re.M) is not None)
check_true("watch-seen-clears-verdict", 'state_set "$file" verdict null' in watch_sh_2)
# Before after_step, not after it: after_step leads into the next step and does
# not return, so anything below it would run only once the whole remaining
# cycle had unwound.
seen_at = run_sh.find("watch_seen")
# The last call is the session's; the one before it closes a clean review
# that opened no session, and so had no QA comments to acknowledge.
after_at = run_sh.rfind('after_step "$wt" "$slug" "$step"')
seen_at = run_sh.find("watch_seen", run_sh.rfind("session_started", 0, after_at))
check_true("watch-seen-before-after-step", -1 < seen_at < after_at)

# A fixing session is recorded, or the issue's summary cannot name it. It goes
# beside its stage rather than into steps.<name>.session, which is the step's
# own conversation and the thing the orchestrator resumes by.
check_true("fix-session-recorded",
           re.search(r'regression\.\$stage\.fixes" "\$\{fixes', regression) is not None)
check_true("fix-session-not-in-steps-session",
           re.search(r'state_set "\$state" "steps\.\$step\.session"', regression) is None)

# Both lines reach the issue's summary: what the regression said, and which
# conversations were opened about it.
check_true("issue-shows-regression", 'out.append("Regression: %s"' in github)

# The verdict line stays underneath the table: a stage is not a step, and
# "preview red on e2e" wedged into a step's row would read as that step having
# failed. The fixing sessions, by contrast, are rows — they are sessions like
# the steps above them, and they belong in the same story.
table_at = github.find('"| Step | Status | Session | Started | Finished | Friction |"')
reg_at = github.find('out.append("Regression: %s"')
check_true("regression-line-below-table", -1 < table_at < reg_at)

# Six columns now, and the sixth is the friction review.
check_true("table-has-friction-column",
           "| Step | Status | Session | Started | Finished | Friction |" in github)
check_true("table-separator-matches", '"|---|---|---|---|---|---|"' in github)

# A fixing session is a row of its own, not a summary line. The one-line
# "Fixing sessions: ..." it replaced said the same thing twice once the rows
# existed.
check_true("fixes-are-rows", '"| %s (%d) | %s | `%s` |' in github
           and '"fix after regression" if stage == "local"' in github)
check_true("no-leftover-fixes-line", "Fixing session%s" not in github)

# Status says how the fixing session ended. It was a dash for every row once,
# which meant a stage with four sessions could not say which of them made it
# green — the same failure the Friction column was built to repair.
check_true("fix-row-has-status", "fix_status_cell(stage, number)" in github)

# The row's times are the fixing session's own. They were the friction
# review's, so a session whose review had nothing to read showed no times.
check_true("fix-times-recorded",
           'fix_word_set "$state" "$stage" fix_started' in regression
           and 'fix_word_set "$state" "$stage" fix_finished "$(date -Iseconds)"' in regression)
check_true("fix-times-rendered", 'stage_node.get("fix_started")' in github)

# A preview fix reopens the review and remind_prod carries it to the merge
# without returning there; the merge must close it, or the summary says
# "step 4/4 review · in progress" for good once the worktree is gone.
merge_at = deploy.find('issue_end_date "$(gh_repo)" "$issue"')
close_at = deploy.find('step_close_merged "$wt"', merge_at)
check_true("merge-closes-reopened-review", -1 < merge_at < close_at)
check_true("run-step-uses-shared-close", 'step_close_merged "$wt"' in run_sh)

# The outcomes are aligned with `fixes` by position, and read from the state
# rather than inferred from how the stage finally ended: a session that ran
# before the last one has a history of its own.
check_true("fix-status-read-by-position",
           'get("fix_status")' in github and "words[number - 1]" in github)

# Every value is written when it happens, by the gate that knows it.
check_true("fix-status-green-on-pass", 'fix_status_set "$state" "$stage" green' in regression)
check_true("fix-status-red-on-fail", 'fix_status_set "$state" "$stage" red' in regression)
check_true("fix-status-blocked-outside", 'fix_status_set "$state" "$stage" blocked' in regression)
check_true("fix-status-open-at-launch", 'fix_status_set "$state" "$stage" open' in regression)

# A session that never ran is not the same as one that left the stage red, and
# the transcript rather than the clock is what says so.
check_true("fix-status-stalled-by-transcript",
           re.search(r'session_started "\$wt" "\$session" \|\| fix_status_set', regression)
           is not None)

# The launch appends and an outcome rewrites the last word. Written as one
# call with a flag, and the flag is the thing that matters: without it the
# string never grows, every write lands on the same word, and a stage with
# three sessions ends up with one — so rows 1 and 2 lose their status and
# render as dashes. Caught by hand on a live sequence before this test existed.
check_true("fix-status-launch-appends",
           'fix_status_set "$state" "$stage" open append' in regression)
check_true("fix-status-outcome-does-not-append",
           re.search(r'fix_status_set "\$state" "\$stage" (green|red|blocked|stalled) append',
                     regression) is None)
check_true("fix-status-append-is-a-flag",
           re.search(r'local state="\$1" stage="\$2" field="\$3" value="\$4" append=', regression)
           is not None)

# The column reads the per-key reviews, so an open one is named and a closed
# one is reported without an id — closed reviews forget theirs.
check_true("friction-cell-exists", "def friction_cell(key):" in github)
check_true("friction-cell-names-an-open-review", '"`%s` open" % sid[:8]' in github)
check_true("friction-cell-reports-a-closed-one", '"reviewed"' in github)

# The preview address, so a reader can open what QA is looking at.
check_true("issue-shows-preview-url", 'out.append("Preview: %s"' in github)

# --- friction, kept per key -------------------------------------------------
#
# One flat slot could hold only the latest review: the one after step 3
# overwrote the one after step 2, and its session id was gone. Nothing read
# that id, so the loss stayed invisible — until the issue's summary wanted to
# name every review.
state_sh = open(os.path.join(ROOT, "sclaude", "lib", "state.sh"),
                encoding="utf-8").read()
actions_sh = open(os.path.join(ROOT, "sclaude", "lib", "actions.sh"),
                  encoding="utf-8").read()
sclaude = open(os.path.join(ROOT, "bin", "sclaude"), encoding="utf-8").read()

check_true("friction-pending-exists",
           re.search(r"^friction_pending\(\)", state_sh, re.M) is not None)
# The old flat shape is still recognised: a feature written by an older sclaude
# could be in flight, and losing its unfinished review would strand it.
check_true("friction-pending-reads-old-flat",
           'reviews.get("session")' in state_sh)

# Every reader asks through the helper. Five places used to test one key each,
# and five hand-written scans would be five chances to write it differently.
for name, text in (("run", run_sh), ("actions", actions_sh), ("sclaude", sclaude)):
    check_true("friction-%s-uses-helper" % name, "friction_pending" in text)

# No flat key survives anywhere: a single missed reader would write into a
# shape nothing else reads, and the review would be silently lost.
for name, text in (("run", run_sh), ("actions", actions_sh), ("sclaude", sclaude)):
    stray = re.findall(r'friction\.(?:session|done|after|started|finished)\b',
                       re.sub(r"#.*", "", text))
    check("friction-%s-no-flat-keys" % name, stray, [])

# friction.after is gone entirely: the key names what the review is about, so
# the field had nothing left to say.
check_true("friction-after-removed",
           re.search(r'state_set "\$state" friction\.after', run_sh) is None)

# --- the friction prompts, cut in two ---------------------------------------
#
# A step's review and a fixing session's differ in their opening and their
# ending and in nothing else. The middle — the log's shape, the four sources,
# what is worth fixing and what is a deliberate ban — lives in one file, or the
# two would drift the way two copies of anything drift.
PROMPTS = os.path.join(ROOT, "sclaude", "prompts")
# friction_body rather than body: `body` is already taken twice above, for the
# shell text of regression_fix_step and regression_rewind. Python would not
# complain — the earlier reads happen before this line runs — but the name
# would be shadowed, and the next edit to any of the three would break a
# neighbour silently.
friction_body = open(os.path.join(PROMPTS, "_friction-body.md"),
                     encoding="utf-8").read()
head_step = open(os.path.join(PROMPTS, "friction.md"), encoding="utf-8").read()
head_fix = open(os.path.join(PROMPTS, "friction-fix.md"), encoding="utf-8").read()

# Each header splices the body exactly once. Zero would leave the session with
# an opening and no instructions; twice would say everything twice.
for name, text in (("step", head_step), ("fix", head_fix)):
    check("friction-%s-splices-body-once" % name,
          len(re.findall(r"^<body>$", text, re.M)), 1)

# The shared middle is not duplicated into either header — that is the whole
# point of cutting it out.
for marker in ("**What to decide.**", "- The friction log", "`classifier` —"):
    check_true("body-owns-%s" % marker[:18].strip("*- `"), marker in friction_body)
    for name, text in (("step", head_step), ("fix", head_fix)):
        check_true("friction-%s-does-not-repeat-%s" % (name, marker[:14].strip("*- `")),
                   marker not in text)

# The substitution tags sit on both sides of the seam, so the splice has to
# happen before the substitutions run. Guarding where each tag lives keeps that
# ordering honest.
check_true("body-holds-log-and-transcript",
           "<log>" in friction_body and "<transcript>" in friction_body)
for name, text in (("step", head_step), ("fix", head_fix)):
    check_true("friction-%s-head-names-the-subject" % name,
               "<step>" in text and "<feature>" in text)

# `step_title` answers for a step and returns empty for a fixing key, so
# run_friction works out a label of its own. Without it the prompt read
# `the "" regression` and the terminal `after step ''`.
check_true("friction-label-not-step-title",
           re.search(r'label="\$\(step_title "\$step"\)"', run_sh) is not None)
check_true("friction-label-from-fixing-key",
           re.search(r'label="\$\{rest%-\*\}"', run_sh) is not None)
# Both files must exist before a session is opened: a missing one used to mean
# a silent return, and it still does.
check_true("friction-checks-both-prompts",
           '-f "$head_prompt" && -f "$PROMPTS/_friction-body.md"' in run_sh)

# --- a fixing session gets a review of its own ------------------------------
#
# It runs into missing tools exactly as a step does — it is reading a
# regression log and trying to reproduce a failure. Its entries had nowhere to
# go: the reviews after each step happen earlier in the cycle, and the deployed
# stages run inside remind_prod, after the last of them. Nothing would have
# picked these up before cmd_done removed the tree.
check_true("fix-session-gets-a-review",
           re.search(r'run_friction "\$wt" "\$slug" "fix-\$stage-\$number"',
                     regression) is not None)

# After the session, not before: a review that ran first would sweep the log
# into .reviewed and hand the fixing session's own obstacles to nobody.
fix_body = re.search(r"regression_fix\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("fix-review-exists", fix_body is not None)
if fix_body:
    inner = fix_body.group(1)
    check_true("fix-review-after-the-session",
               inner.find("claude --session-id") < inner.find("run_friction"))
    # `|| true`: a review that could not start must not turn a finished fixing
    # session into a failed one — the gate reads this function's exit code.
    check_true("fix-review-does-not-fail-the-fix",
               'run_friction "$wt" "$slug" "fix-$stage-$number" || true' in inner)

    # The key is the session's position in `fixes`, and NOT the attempts
    # counter. That counter is a limit, reset to zero in three places — a green
    # run, `sclaude reset`, and entering step 4 — while `fixes` only grows. Key
    # by the counter and a stage that goes red twice with a green in between
    # writes both reviews to `fix-<stage>-1`, while the summary looks up a `-2`
    # that never existed.
    check_true("fix-review-keyed-by-position",
               'regression.$stage.fixes' in inner and "wc -w" in inner)
    check_true("fix-review-not-keyed-by-attempts",
               'regression.$stage.attempts' not in inner)

# Writer and reader must derive the row's number from the same thing, or the id
# in a row and the review beside it belong to different sessions. The reader
# numbers by position in `fixes`; so does the writer above.
check_true("fix-rows-numbered-by-position",
           "enumerate(ids.split(), start=1)" in github)

# The transcript of a fixing session is findable. Its id is kept eight
# characters wide — that is what the issue's summary prints — while the file is
# named by the full UUID, so the lookup is a prefix match.
check_true("transcript-finds-fixing-sessions", 'saved.get("regression")' in run_sh)
check_true("transcript-matches-by-prefix", 'short + "*.jsonl"' in run_sh)
check_true("transcript-labels-the-stage", '"fix after regression" if stage == "local"' in run_sh
           and 'out.append("%s — %s" % (name, found[0]))' in run_sh)

# --- what a run shows while it is running ------------------------------------
#
# The first real run looked hung: the preview stage is one e2e part, ten
# minutes long, and a line was printed only once a part had finished. So the
# whole list goes up front with each part's expected time, the running one is
# marked, and its line is rewritten when it ends.
check_true("timings-kept-in-the-project",
           '"$common/sclaude/regression-timings.json"' in regression)
# Not under tests/artifacts/: that is Playwright's outputDir, emptied at the
# start of every e2e run, and the file was gone before each regression read it.
check_true("timings-not-in-playwright-output",
           'tests/artifacts/regression-timings' not in regression)
# In the project rather than the worktree: a worktree dies with the feature,
# and the point of these numbers is that the next feature starts with them.
check_true("timings-not-in-the-worktree",
           '.sclaude/local/feature/regression-timings' not in regression)

check_true("expected-time-read", "regression_expected()" in regression)
check_true("expected-total-for-the-header", "regression_expected_total()" in regression)
check_true("header-shows-expected-total",
           'expected $(regression_duration "$total_expected")' in regression)

# The whole list is printed before anything runs — that is the point of the
# change, and a guard on the header alone missed its removal entirely: the
# mutation that deleted this loop left the suite green.
# The run's parts are in regression_run_body; regression_run wraps it in the
# machine-wide queue.
run_body = re.search(r"regression_run_body\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("run-body-found", run_body is not None)
if run_body:
    rb = run_body.group(1)
    plan_at = rb.find("for part in $parts; do")
    loop_at = rb.find('cmd="$(regression_command "$part" "$base" "$wt" "$stage")"')
    check_true("parts-listed-before-the-run", -1 < plan_at < loop_at)
    check_true("listed-with-their-expected-times",
               re.search(r'printf .*%s%s.*\n\s*"\$part"', rb) is not None
               or 'expected $(regression_duration "$one")' in rb)

# Only successful parts are remembered: a failed part usually failed fast, and
# recording that would tell the next run to expect seconds for something that
# takes a minute.
#
# Counted rather than located. Comparing positions caught a *moved* call and
# missed an *added* one — a second regression_remember in the failing branch
# left the first where it was, and the guard stayed green while every failure
# began poisoning the estimates.
check("remembered-exactly-once",
      len(re.findall(r'regression_remember "\$wt" "\$stage" "\$part"', regression)), 1)
if run_body:
    rb = run_body.group(1)
    remember_at = rb.find('regression_remember "$wt" "$stage" "$part"')
    else_at = rb.find("\n    else\n")
    check_true("remembered-in-the-successful-branch",
               -1 < remember_at < else_at)

# The line is marked when the part starts, not only when it ends.
check_true("part-marked-as-started",
           re.search(r'regression_line "\$stage" "\$parts" "\$part" started', regression) is not None)
check_true("part-marked-as-done",
           re.search(r'regression_line "\$stage" "\$parts" "\$part" done', regression) is not None)

# Rewriting only with a terminal: escape codes in a piped log are rubbish.
line_body = re.search(r"regression_line\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("line-function-exists", line_body is not None)
if line_body:
    body = line_body.group(1)
    check_true("rewrite-only-on-a-terminal", '[[ -t 1 ]]' in body)
    check_true("rewrite-climbs-past-the-parts-below", '\\033[%dA\\033[2K' in body)
    # `say` files its text into ASK_CONTEXT for the next question; a line about
    # to be overwritten has no business there.
    check_true("in-progress-line-not-in-ask-context",
               '[[ "$what" != "started" ]] && ask_note' in body)

# --- progress inside a single long part --------------------------------------
#
# Printing the list of parts up front answers "how long is this" for the local
# stage's eight. A deployed stage has exactly one part — `e2e`, the ten-minute
# one — so that fix left a single line saying `Started` and then silence, which
# is what "looks hung" meant the second time it was reported.
if run_body:
    rb = run_body.group(1)
    check_true("part-runs-in-the-background", 'eval "$cmd" ) >> "$log" 2>&1 < /dev/null &' in rb)
    check_true("part-is-waited-for", 'wait "$part_pid"' in rb)
    # The exit code has to survive the move to `wait`, or a red regression
    # would report green — the worst regression this file could have.
    # part_wait_at rather than wait_at: the latter is taken further down for
    # the merge wait. Python would not complain — each is read right after it
    # is set — but the name would be shared across two unrelated checks, and an
    # edit between them would break the far one in silence.
    rc_at = rb.find("rc=$?")
    part_wait_at = rb.find('wait "$part_pid"')
    check_true("exit-code-taken-from-wait", -1 < part_wait_at < rc_at)
    check_true("progress-watches-the-log", "kill -0 \"$part_pid\"" in rb)
    check_true("progress-only-on-a-terminal", rb.find('[[ -t 1 ]]') < rb.find('kill -0 "$part_pid"'))

# `grep -c` prints 0 *and* exits 1 when nothing matches, so `|| echo 0` makes
# the variable "0\n0". A newline in the tail breaks the rewriting outright: the
# extra line moves the cursor and every later climb lands on the wrong row.
check_true("no-double-zero-from-grep-c",
           re.search(r"grep -cE[^\n]*\|\| echo 0", regression) is None)
check_true("counters-are-checked-for-digits",
           '[[ "$done_n" =~ ^[0-9]+$ ]] || done_n=0' in regression)

# The tail is an extra argument rather than a rebuilt line, so the three call
# sites keep their shape.
check_true("line-takes-a-tail", 'tail="${7:-}"' in regression)

# A part with no test count of its own — typecheck, lint — still gets a tail,
# just without the N/M: the substitution is guarded on `total`.
check_true("counter-optional",
           '${total:+ · $done_n/$total}' in regression)

# The previous run's finishing time is cleared at the start, or the state reads
# as a run that ended before it began: started 13:56, finished 09:21.
check_true("finished-cleared-at-start",
           re.search(r'regression\.\$stage\.finished" null', regression) is not None)

# --- a broken environment is not a failing test ------------------------------
#
# Preview answered 500 to every request because its Supabase variables were
# never set, all twenty specs timed out, and the gate opened a session to
# repair tests that were not broken.
broken = re.search(r"regression_environment_broken\(\)\s*\{(.*?)\n\}", regression, re.S)
check_true("environment-check-exists", broken is not None)
if broken:
    body = broken.group(1)
    # Both conditions, never one: a genuine regression nearly always leaves
    # something passing, and an address that serves says the fault is the
    # branch's.
    check_true("checks-the-whole-suite-failed",
               '"$ran" -eq $(( failed + ${cut:-0} + ${skipped:-0} ))' in body)
    check_true("checks-the-address-too", "http_code" in body)
    check_true("counts-a-dead-host-as-broken", '"$code" == "000"' in body)


def environment_broken(log_text, code="500"):
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "regression.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(log_text)
        script = ("curl() { printf %s; }\n" % code) + "regression_environment_broken" \
            + "() {" + broken.group(1) + "\n}\nregression_environment_broken \"$1\" https://x.test"
        return subprocess.run(["bash", "-c", script, "_", path]).returncode == 0


if broken:
    check_true("broken-when-everything-failed",
               environment_broken("Running 20 tests using 1 worker\n  20 failed\n"))
    # The cap stops a dead deployment's suite after ten; the rest did not run.
    check_true("broken-when-the-cap-left-the-rest-unrun",
               environment_broken("Running 105 tests using 4 workers\n"
                                  "  Testing stopped early after 10 maximum allowed failures.\n"
                                  "  10 failed\n  95 did not run\n"))
    # In several workers the specs still running when it stopped are their own line.
    check_true("broken-when-other-workers-were-cut-short",
               environment_broken("Running 120 tests using 4 workers\n"
                                  "  Testing stopped early after 10 maximum allowed failures.\n"
                                  "  10 failed\n  3 interrupted\n  107 did not run\n"))
    check("not-broken-when-something-passed",
          environment_broken("Running 105 tests using 4 workers\n  10 failed\n"
                             "  90 did not run\n  5 passed\n"), False)
    check("not-broken-when-the-host-serves",
          environment_broken("Running 20 tests using 1 worker\n  20 failed\n", code="200"), False)
check_true("broken-environment-returns-2",
           re.search(r'regression_environment_broken "\$log" "\$base"; then(?:.|\n)*?return 2',
                     regression) is not None)
# Only for a deployed stage: localhost has no deployment to be broken.
check_true("environment-check-skips-local",
           '"$stage" != "local" && -n "$base"' in regression)

# --- waiting for the merge ---------------------------------------------------
#
# The merge is the one part of the cycle that is a person's alone. Step 4 used
# to exit and leave them to remember `sclaude <feature>`; it waits instead.
steps_sh = open(os.path.join(ROOT, "sclaude", "lib", "steps.sh"),
                encoding="utf-8").read()
# Half a minute is the service value, and it is the default rather than a
# literal: the integration bench overrides it, because a whole `sclaude
# <feature>` would otherwise spend one poll per half minute waiting for a merge
# its stub will never report. What must hold is the default — an override that
# silently became the normal value would make the cycle ask GitHub every second.
check_true("merge-poll-defaults-to-half-a-minute",
           re.search(r'^MERGE_POLL="\$\{MERGE_POLL:-30\}"$', steps_sh, re.M) is not None)
check_true("qa-poll-defaults-to-a-minute",
           re.search(r'^QA_POLL="\$\{QA_POLL:-60\}"$', steps_sh, re.M) is not None)
check_true("qa-poll-is-validated",
           '[[ "$QA_POLL" =~ ^[1-9][0-9]*$ ]] || QA_POLL=60' in steps_sh)
# The wait is no longer in step 4: it closed the review only on a merge, which
# put the merge ahead of the preview and QA. remind_prod waits for QA, then for
# the merge, and both say so.
deploy_sh = open(os.path.join(ROOT, "sclaude", "lib", "deploy.sh"),
                 encoding="utf-8").read()
check_true("review-no-longer-waits-for-the-merge",
           re.search(r'while \[\[ "\$\(branch_pr_state "\$branch"\)" != "MERGED" \]\]', run_sh)
           is None)
check_true("deploy-waits-for-the-merge",
           re.search(r'while pr_state="\$\(branch_pr_state "\$branch"\)"; \[\[ "\$pr_state" != "MERGED" \]\]', deploy_sh)
           is not None)
# A pull request closed without a merge ends the wait instead of holding it
# for ever.
check_true("merge-wait-stops-on-closed",
           re.search(r'"\$pr_state" == "CLOSED"(?:.|\n)*?return 2', deploy_sh) is not None)
check_true("waiting-names-the-human", deploy_sh.count("Human in the loop") >= 2)
check_true("waiting-names-the-next-check", "next check in %ss" in deploy_sh)

# --- a fix to the orchestrator re-runs the stage ---------------------------
#
# Once the preview e2e was red because of how sclaude wired the
# environment, the friction review after the fixing session fixed exactly that
# — and the gate still stopped with "blocked, carry on with sclaude <feature>",
# and the next run walked past the red preview. A fix to the orchestrator now
# re-runs the stage, and the preview does so in a fresh process with the new
# code.
fix_body = regression[regression.find("regression_fix() {"):]
check_true("fix-reports-an-orchestrator-fix",
           'friction.fix-$stage-$number.fixed' in fix_body and "return 4" in fix_body)
check_true("fix-drops-the-stale-blocked-note",
           re.search(r'fixed" 2>/dev/null \|\| true\)" == "true" \]\]; then\n\s*rm -f "\$wt/.sclaude/local/feature/regression.blocked"\n\s*return 4',
                     fix_body) is not None)
gate_body = regression[regression.find("regression_gate() {"):regression.find("regression_rewind() {")]
check_true("gate-reruns-after-an-orchestrator-fix",
           re.search(r'if \[\[ "\$frc" -eq 4 \]\]; then(?:.|\n)*?continue\n', gate_body) is not None)
check_true("gate-restarts-for-the-preview",
           'exec "$INSTRUMENTS/bin/sclaude" "$slug"' in gate_body)
# Before the blocked branch: a fix is checked for first, or the note wins.
check_true("rewind-only-after-a-fix",
           '[[ "$fixed_here" -eq 1 ]] && regression_rewind' in gate_body
           and gate_body.count("regression_rewind") == 1)
check_true("orchestrator-fixes-are-limited",
           'orchestrator_fixes' in gate_body and '"$ofix" -lt "$REGRESSION_MAX_ATTEMPTS"' in gate_body)
run_step_body = run_sh[run_sh.find("run_step() {"):run_sh.find("\n}\n", run_sh.find("run_step() {"))]
check_true("review-skip-before-the-dev-server",
           -1 < run_step_body.find("review_skippable") < run_step_body.find('ensure_dev "$wt"'))
check_true("watcher-knows-in-qa", 'field "$file" columns.qa' in watcher)
check_true("orchestrator-fix-checked-before-blocked",
           -1 < gate_body.find('"$frc" -eq 4') < gate_body.find('"$frc" -eq 3'))

# The module has to be in the source list, or none of it loads.
# Starting a step over clears the regression's spent attempts, or an exhausted
# stage stays wedged: once both fixing sessions are used up, every later entry
# runs the whole suite again — minutes of it — only to refuse at the limit.
check_true("reset-clears-attempts",
           re.search(r'regression\.\$rs\.attempts" 0', sclaude) is not None)
check_true("module-sourced", re.search(r"for _module in .*\bregression\b", sclaude, re.S) is not None)

# The prompt the fixing session is given must exist: render_prompt raises on a
# missing include and the session never starts.
check_true("fail-prompt-exists",
           os.path.isfile(os.path.join(ROOT, "sclaude", "prompts", "_regression-fail.md")))

# Both prompts that can receive a fixing session carry the block; without it the
# session is told nothing about what failed.
for name in ("code", "review"):
    text = open(os.path.join(ROOT, "sclaude", "prompts", "%s.md" % name),
                encoding="utf-8").read()
    check_true("block-in-%s" % name, "<block:regression>" in text)



# --- the developer's name reaches every part ----------------------------------
#
# Run for real, unlike the rest of this file: what matters is the string the
# part is eval'ed from, and whether a chained command still sees the name all
# the way down. project_command is stubbed; developer.sh is the real one.
import shlex
import subprocess
import tempfile


def command_for(part, base, cmd, dev_env=None, email=None, stage=""):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q", tmp], check=True)
        if email:
            subprocess.run(["git", "-C", tmp, "config", "user.email", email],
                           check=True)
        script = """
INSTRUMENTS=%s
project_command() { printf '%%s' %s; }
source %s/sclaude/lib/developer.sh
source %s/sclaude/lib/regression.sh
regression_command %s %s '' %s
""" % (tmp, shlex.quote(cmd), ROOT, ROOT, part, shlex.quote(base), shlex.quote(stage))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") and k != "SCLAUDE_DEV"}
        env.update(HOME=tmp, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        if dev_env:
            env["SCLAUDE_DEV"] = dev_env
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, env=env).stdout


check("dev-absent-command-unchanged",
      command_for("e2e", "", "npm run test:e2e"), "npm run test:e2e")
check("dev-absent-deployed-keeps-base",
      command_for("e2e", "https://x.test", "npm run test:e2e"),
      "export E2E_BASE_URL=https://x.test; npm run test:e2e")
check("dev-from-email-every-part",
      command_for("lint", "", "npm run lint", email="Alice.B@example.com"),
      "export SCLAUDE_DEV=alice-b; npm run lint")
check("dev-from-env-with-base",
      command_for("e2e", "https://x.test", "npm run test:e2e", dev_env="bob"),
      "export SCLAUDE_DEV=bob; export E2E_BASE_URL=https://x.test; npm run test:e2e")
# The cap on failures goes to the e2e of the stages that run the suite, and to
# nothing else: production's look is seconds long, and a lint has no specs.
check("cap-on-local-e2e",
      command_for("e2e", "", "npm run test:e2e", stage="local"),
      "export E2E_MAX_FAILURES=10; npm run test:e2e")
check("cap-on-preview-e2e",
      command_for("e2e", "https://x.test", "npm run test:e2e", stage="preview"),
      "export E2E_MAX_FAILURES=10; export E2E_BASE_URL=https://x.test; npm run test:e2e")
check("no-cap-on-prod-e2e",
      command_for("e2e", "https://x.test", "npm run test:e2e", stage="prod"),
      "export E2E_BASE_URL=https://x.test; npm run test:e2e")
check("no-cap-on-other-parts",
      command_for("lint", "", "npm run lint", stage="local"), "npm run lint")
# The reason for export over a prefix: the second half of a chain sees it too.
chained = command_for("e2e", "", "true && echo \"seen=$SCLAUDE_DEV\"",
                      dev_env="carol")
# The same for the address: the second half of a chain is where the suite runs.
chained_base = command_for("e2e", "https://x.test", "true && echo \"base=$E2E_BASE_URL\"")
check("base-reaches-the-whole-chain",
      subprocess.run(["bash", "-c", chained_base], capture_output=True, text=True,
                     env={"PATH": os.environ["PATH"]}).stdout.strip(),
      "base=https://x.test")
check("dev-reaches-the-whole-chain",
      subprocess.run(["bash", "-c", chained], capture_output=True, text=True,
                     env={"PATH": os.environ["PATH"]}).stdout.strip(),
      "seen=carol")



# --- a deploy by somebody else during the production run ----------------------
#
# vercel_prod_deployments is stubbed with rows around a run that went from
# 12:00:00 to 12:10:00 UTC, as url, sha, state, createdAt, ready. What counts
# is going live (ready) inside the window, and only for a READY deployment.
def intruded(stage, started, finished):
    rows = "\\n".join([
        # this feature's own: created and live before the run
        "https://own.app\\tabc\\tREADY\\t1790078300000\\t1790078350000",
        # created a minute before the run, live in the middle of it
        "https://early.app\\tdef\\tREADY\\t1790078340000\\t1790078460000",
        # created and live inside, live exactly at the end
        "https://edge.app\\tghi\\tREADY\\t1790078900000\\t1790079000000",
        # a build that failed inside the window: it never served anything,
        # whatever timestamp the listing carries for it
        "https://broken.app\\tjkl\\tERROR\\t1790078500000\\t1790078520000",
        # live after the run
        "https://late.app\\tmno\\tREADY\\t1790079200000\\t1790079300000",
    ])
    script = """
source %s/sclaude/lib/regression.sh
vercel_prod_deployments() { printf '%s\\n'; }
regression_deploy_intruded %s %s %s && echo YES || echo NO
""" % (ROOT, rows, stage, shlex.quote(started), shlex.quote(finished))
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True).stdout.strip()


START, END = "2026-09-22T12:00:00+00:00", "2026-09-22T12:10:00+00:00"
check("intruded-inside-window", intruded("prod", START, END),
      "https://early.app\t1790078460000\nhttps://edge.app\t1790079000000\nYES")
check("intruded-created-before-live-during",
      intruded("prod", START, "2026-09-22T12:02:00+00:00"),
      "https://early.app\t1790078460000\nYES")
check("intruded-failed-build-is-not",
      intruded("prod", "2026-09-22T12:07:00+00:00", "2026-09-22T12:09:00+00:00"), "NO")
check("intruded-own-deploy-before-is-not",
      intruded("prod", START, "2026-09-22T12:00:30+00:00"), "NO")
check("intruded-after-window-is-not",
      intruded("prod", "2026-09-22T12:10:30+00:00", "2026-09-22T12:12:00+00:00"), "NO")
check("intruded-local-offset",
      intruded("prod", "2026-09-22T15:00:30+03:00", "2026-09-22T15:02:00+03:00"),
      "https://early.app\t1790078460000\nYES")
check("intruded-preview-never", intruded("preview", START, END), "NO")
check("intruded-no-times", intruded("prod", "", ""), "NO")

deploy_src = open(os.path.join(ROOT, "sclaude", "lib", "deploy.sh"), encoding="utf-8").read()
check_true("intrusion-checked-before-rollback",
           -1 < deploy_src.find("regression_deploy_intruded prod")
           < deploy_src.find("rollback_prod \"$wt\" \"$slug\" --auto"))



# --- a change to the manuals alone runs the static parts ----------------------
#
# The manuals are written in step 3, after step 2's green run, and each such
# feature paid a second full regression at the end of the review for a page of
# prose. Run for real against a repository: the answer depends on git's view of
# what changed since the tested commit.
def manual_parts(config, edit, ancestor=True):
    """The parts regression_manual_parts names after `edit`, or NONE."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(HOME=tmp, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        git = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True,
                                        capture_output=True, text=True, env=env).stdout.strip()
        git("init", "-q")
        os.makedirs(os.path.join(tmp, "help"))
        os.makedirs(os.path.join(tmp, ".sclaude"))
        for name in ("help/page.tsx", "app.ts", ".sclaude/config.json"):
            with open(os.path.join(tmp, name), "w") as fh:
                fh.write(json.dumps(config) if name == ".sclaude/config.json" else "x\n")
        git("add", "-A")
        git("commit", "-qm", "base")
        was = git("rev-parse", "HEAD")
        if not ancestor:
            git("checkout", "-q", "--orphan", "other")
        for name in edit:
            if isinstance(name, tuple):
                os.makedirs(os.path.dirname(os.path.join(tmp, name[1])), exist_ok=True)
                git("mv", name[0], name[1])
                continue
            with open(os.path.join(tmp, name), "a") as fh:
                fh.write("y\n")
        git("add", "-A")
        git("commit", "-qm", "edit")
        now = git("rev-parse", "HEAD")
        script = """
source %s/sclaude/lib/project.sh
source %s/sclaude/lib/regression.sh
regression_manual_parts %s %s %s || echo NONE
""" % (ROOT, ROOT, tmp, was, now)
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, env=env).stdout.strip()


MANUAL_CFG = {"regression": {"local": ["typecheck", "lint", "build", "schema", "e2e"],
                             "manual": ["typecheck", "lint", "build"]},
              "manuals": [{"path": "help/page.tsx", "what": "user"}]}
check("manual-only-runs-static-parts",
      manual_parts(MANUAL_CFG, ["help/page.tsx"]), "typecheck lint build")
# A code file moved onto a manual path: with rename detection the diff showed
# only the manual, and the page it used to be went untested.
check("code-moved-onto-a-manual-runs-everything",
      manual_parts(dict(MANUAL_CFG, manuals=[{"path": "doc/page.tsx"}]),
                   [("app.ts", "doc/page.tsx")]), "NONE")
# No default subset: the names of the checks are the project's own.
check("no-manual-parts-declared-runs-everything",
      manual_parts(dict(MANUAL_CFG, regression={"local": ["typecheck", "e2e"]}),
                   ["help/page.tsx"]), "NONE")
check("empty-manual-parts-runs-everything",
      manual_parts(dict(MANUAL_CFG, regression={"local": ["typecheck"], "manual": []}),
                   ["help/page.tsx"]), "NONE")
check("manual-and-code-runs-everything",
      manual_parts(MANUAL_CFG, ["help/page.tsx", "app.ts"]), "NONE")
check("code-only-runs-everything", manual_parts(MANUAL_CFG, ["app.ts"]), "NONE")
check("unrelated-history-runs-everything",
      manual_parts(MANUAL_CFG, ["help/page.tsx"], ancestor=False), "NONE")
check("no-manuals-declared-runs-everything",
      manual_parts({"regression": MANUAL_CFG["regression"]}, ["help/page.tsx"]), "NONE")
check("manual-parts-declared-by-the-project",
      manual_parts(dict(MANUAL_CFG, regression=dict(MANUAL_CFG["regression"],
                                                     manual=["build", "e2e"])),
                   ["help/page.tsx"]), "build e2e")

# The subset is for the first run only: once a fixing session has edited the
# tree, the diff is no longer just the manuals.
gate_src = re.search(r"regression_gate\(\)\s*\{(.*?)\n\}", regression, re.S).group(1)
check_true("manual-subset-reaches-the-run",
           'regression_run "$wt" "$slug" "$stage" "$only"' in gate_src)
check_true("manual-subset-cleared-after-first-run",
           re.search(r'regression_run "\$wt" "\$slug" "\$stage" "\$only"\n\s*rc=\$\?\n\s*only=""',
                     gate_src) is not None)
# A run of the subset does not wait for a server and a database it never asks.
# The run is a wrapper that holds the machine-wide queue around its body.
run_src = (re.search(r"regression_run\(\)\s*\{(.*?)\n\}", regression, re.S).group(1)
           + re.search(r"regression_run_body\(\)\s*\{(.*?)\n\}", regression, re.S).group(1))
check_true("manual-subset-skips-the-dev-environment",
           '[[ "$stage" == "local" && -z "$only" ]] && declare -F ensure_dev' in run_src)
check_true("manual-subset-replaces-the-parts", 'parts="$only"' in run_src)
# A full local run restarts the server rather than trusting one up for hours.
check_true("full-local-run-restarts-the-dev-server",
           -1 < run_src.find('stop_own_dev "$wt"') < run_src.find('ensure_dev "$wt"'))


# --- a preview run is about what is deployed ----------------------------------
#
# A fixing session commits to the branch, and the loop used to go round and
# run the suite again against the preview that still served the commit before
# the fix — then record a green verdict against a tree nobody deployed. Run for
# real: the gate, deploy_unchanged and the state are the real ones; the deploy,
# the suite and the session are stubs that say what they did.
def preview_gate(deployed, runs, fix_commits=True, ship_ok=True, verdict=None):
    with tempfile.TemporaryDirectory() as wt:
        git = lambda *a: subprocess.run(["git", "-C", wt, *a], check=True,
                                        capture_output=True)
        git("init", "-q")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
            "--allow-empty", "-m", "base")
        head = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
        with open(os.path.join(wt, ".git", "info", "exclude"), "a") as fh:
            fh.write(".sclaude/local/feature\n")
        blob = {"deploy": {"preview": {
            "sha": head if deployed == "head" else deployed}}}
        if verdict:
            blob["regression"] = {"preview": {
                "status": "passed", "tree": head if verdict == "head" else verdict}}
        with open(os.path.join(wt, ".sclaude/local/feature", "state.json"), "w") as fh:
            json.dump(blob, fh)
        body = "set -uo pipefail\n"
        body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
        body += 'REGRESSION_MAX_ATTEMPTS=2; SELF=sclaude\n'
        for name in ("io", "ui", "steps", "state", "worktree", "regression", "deploy"):
            body += 'source "%s/sclaude/lib/%s.sh"\n' % (ROOT, name)
        body += """
warn() { :; }; info() { :; }; say() { :; }; alarm() { :; }
regression_rewind() { :; }; regression_clear_mark() { :; }
preview_apply_migrations() { :; }
RUNS=(%s)
N=0
regression_run() {
  echo RAN
  local rc="${RUNS[$N]:-0}"; N=$((N + 1)); return "$rc"
}
regression_fix() {
  echo FIX
  %s
  return 0
}
preview_ship() {
  echo SHIP
  %s
}
regression_gate "%s" demo preview
echo "rc=$?"
""" % (" ".join(str(r) for r in runs),
       'git -C "%s" -c user.email=t@t -c user.name=t commit -q --allow-empty -m fix'
       % wt if fix_commits else ":",
       'deploy_remember "%s" preview' % wt if ship_ok else "return 1",
       wt)
        return subprocess.run(["bash", "-c", body], capture_output=True,
                              text=True, timeout=60).stdout.split()


# The deployment is the tree: nothing is deployed, the suite runs.
check("preview-gate-deployed-tree-runs",
      preview_gate("head", [0]), ["RAN", "rc=0"])
# The tree moved since the deploy: it is deployed first.
check("preview-gate-moved-tree-deploys-first",
      preview_gate("f" * 40, [0]), ["SHIP", "RAN", "rc=0"])
# The case that went wrong: a red run, a session that commits a fix, and the
# rerun — which now runs against a deployment of the fix.
check("preview-gate-fix-is-deployed-before-the-rerun",
      preview_gate("head", [1, 0]), ["RAN", "FIX", "SHIP", "RAN", "rc=0"])
# A session that committed nothing leaves the deployment as it was.
check("preview-gate-no-commit-no-deploy",
      preview_gate("head", [1, 0], fix_commits=False), ["RAN", "FIX", "RAN", "rc=0"])
# A redeploy that fails ends the gate rather than running the old address.
check("preview-gate-failed-redeploy-stops",
      preview_gate("f" * 40, [0], ship_ok=False), ["SHIP", "rc=1"])
# A green verdict holds for the tree it ran on, and for no other: after a
# production rollback the fix comes round with the old verdict still recorded,
# and the gate used to return on it without running the suite.
check("preview-gate-green-on-this-tree-holds",
      preview_gate("head", [0], verdict="head"), ["rc=0"])
check("preview-gate-green-on-another-tree-runs",
      preview_gate("head", [0], verdict="e" * 40), ["RAN", "rc=0"])


# --- who reopened the review ----------------------------------------------------
#
# run_step lets a merge close a review a preview fix reopened, and holds one a
# production rollback reopened; it can only tell them apart by the mark.
def rewound(stage):
    with tempfile.TemporaryDirectory() as wt:
        os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
        state = os.path.join(wt, ".sclaude/local/feature", "state.json")
        with open(state, "w") as fh:
            json.dump({"pr": 7, "regression": {"preview": {"status": "passed"}}}, fh)
        body = "set -uo pipefail\n"
        for name in ("io", "ui", "steps", "state", "regression"):
            body += 'source "%s/sclaude/lib/%s.sh"\n' % (ROOT, name)
        body += ('info() { :; }; issue_sync() { :; }; step_rewind_to() { :; }\n'
                 'regression_rewind "%s" demo %s\n' % (wt, stage))
        subprocess.run(["bash", "-c", body], capture_output=True, text=True, timeout=30)
        with open(state) as fh:
            return json.load(fh)


after = rewound("preview")
check("rewind-preview-marks-who", after.get("reopened_by"), "preview")
check("rewind-preview-keeps-its-verdict",
      after["regression"]["preview"].get("status"), "passed")
after = rewound("prod")
check("rewind-prod-marks-who", after.get("reopened_by"), "prod")
check("rewind-prod-clears-the-preview-verdict",
      after["regression"]["preview"].get("status"), None)

# --- a dev server that wedged during the local e2e -----------------------------
#
# On 2026-10-09 a feature's server, restarted right before the run, stopped finishing
# /_next/image requests halfway through it, and a fixing session spent a quarter
# of an hour on code nothing was wrong with. The run now tries e2e once more on
# a fresh server — but only on that signature, or a real failure would be run
# twice and maybe waved through.
wedged = re.search(r"^regression_server_wedged\(\) \{.*?^\}", regression, re.S | re.M)
check_true("server-wedged-check-exists", wedged is not None)

GOTO = ("  ✘  1 [chromium] › a.spec.ts:1:1 › a (30.1s)\n"
        "    Error: page.goto: Test timeout of 30000ms exceeded.\n"
        "    Error Context: tests/artifacts/a/error-context.md\n")
EXPECT = ("  ✘  2 [chromium] › b.spec.ts:1:1 › b (5.0s)\n"
          "    Error: expect(locator).toBeVisible() failed\n")


def server_wedged(log_text):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "regression.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(log_text)
        script = wedged.group(0) + '\nregression_server_wedged "$1"'
        return subprocess.run(["bash", "-c", script, "_", path]).returncode == 0


if wedged:
    check_true("wedged-when-every-failure-is-a-goto-timeout",
               server_wedged("=== build ===\nok\n=== e2e ===\n" + GOTO + GOTO
                             + "  2 failed\n  59 passed (7.2m)\n"))
    check("not-wedged-on-a-failed-assertion-beside-it",
          server_wedged("=== e2e ===\n" + GOTO + EXPECT + "  2 failed\n"), False)
    check("not-wedged-on-an-earlier-attempt",
          server_wedged("=== e2e ===\n" + GOTO + "  1 failed\n"
                        "=== e2e (again, on a fresh server) ===\n" + EXPECT
                        + "  1 failed\n"), False)
    check("not-wedged-when-nothing-failed",
          server_wedged("=== e2e ===\n  61 passed (7.0m)\n"), False)

# A suite that stopped at its cap of failures is run once more on a fresh
# server, whatever the failures were: on 2026-10-26 a server answering 404 under
# /pro failed 91 specs on missing headings, with no page.goto among them.
early = re.search(r"^regression_stopped_early\(\) \{.*?^\}", regression, re.S | re.M)
check_true("stopped-early-check-exists", early is not None)
STOPPED = "  Testing stopped early after 10 maximum allowed failures.\n  10 failed\n  95 did not run\n"


def stopped_early(log_text):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "regression.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(log_text)
        script = early.group(0) + '\nregression_stopped_early "$1"'
        return subprocess.run(["bash", "-c", script, "_", path]).returncode == 0


if early:
    check_true("stopped-early-at-the-cap",
               stopped_early("=== build ===\nok\n=== e2e ===\n" + EXPECT * 10 + STOPPED))
    check("not-stopped-early-below-the-cap",
          stopped_early("=== e2e ===\n" + EXPECT + "  1 failed\n  60 passed\n"), False)
    check("not-stopped-early-on-an-earlier-attempt",
          stopped_early("=== e2e ===\n" + STOPPED
                        + "=== e2e (again, on a fresh server) ===\n" + EXPECT
                        + "  1 failed\n"), False)
# The local e2e runs against the run's own build when the project says how to
# serve it, and the dev server comes back however the suite ended.
check_true("serves-the-build-only-after-a-build",
           '" $parts " == *" build "*' in regression
           and 'regression_serve_command "$wt"' in regression)
# How the build is served comes from the tree's config alone: a key in the
# main checkout's would reach a branch whose code cannot serve its build.
serve_fn = re.search(r"^regression_serve_command\(\) \{.*?^\}", regression, re.S | re.M)
check_true("serve-command-helper-exists", serve_fn is not None)


def serve_command(main_cmds, tree_cmds):
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, wt = os.path.join(tmp, "repo"), os.path.join(tmp, "wt")
        for root, cmds in ((repo, main_cmds), (wt, tree_cmds)):
            if cmds is not None:
                with open(_cfg(os.path.join(root, ".sclaude", "config.json")), "w") as fh:
                    json.dump({"commands": cmds}, fh)
        os.makedirs(wt, exist_ok=True)
        # `set -e` up to the call and a mark after it: an empty answer counts
        # only from a script that ran, or a broken source would pass as "".
        script = ('set -e\nREPO=%s\nsource %s/sclaude/lib/project.sh\n%s\nset +e\n'
                  'regression_serve_command %s\necho ran\n') % (repo, ROOT, serve_fn.group(0), wt)
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        lines = out.stdout.strip().split("\n")
        if out.stderr or lines[-1] != "ran":
            return "did not run: " + out.stderr.strip()
        return "\n".join(lines[:-1]).strip()


if serve_fn:
    check("serve-command-not-from-main",
          serve_command({"e2e:server": "from-main"}, {"build": "b"}), "")
    check("serve-command-from-the-tree",
          serve_command({"e2e:server": "from-main"}, {"e2e:server": "from-tree"}), "from-tree")
    check("serve-command-tree-without-main-key",
          serve_command({"build": "b"}, {"e2e:server": "from-tree"}), "from-tree")
    check("serve-command-no-tree-config",
          serve_command({"e2e:server": "from-main"}, None), "")

check_true("dev-server-back-after-e2e",
           '[[ -n "$served" ]] && regression_serve_dev "$wt"' in regression)
check_true("mark-names-what-the-proxy-reads",
           'REGRESSION_SERVING_MARK=".sclaude/local/feature/serving-build"' in regression
           and '"serving-build"' in open(os.path.join(ROOT, "bin", "sclaude-proxy"),
                                         encoding="utf-8").read())

# The running line counts the failures as they come, beside the finished specs.
check_true("progress-counts-failures",
           "${failed_n:+ · $failed_n failed}" in regression
           and "grep -cE '^[[:space:]]+✘[[:space:]]+[0-9]+'" in regression)
check_true("retry-asks-both-signatures",
           re.search(r'regression_server_wedged "\$log".*?regression_stopped_early "\$log"',
                     regression, re.S) is not None)

# The red line names the specs that failed, by their titles.
specs_fn = re.search(r"^regression_failed_specs\(\) \{.*?^\}", regression, re.S | re.M)
check_true("failed-specs-helper-exists", specs_fn is not None)


def failed_specs(log_text, start=1):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "regression.log")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(log_text)
        script = specs_fn.group(0) + '\nregression_failed_specs "$1" "$2"'
        return subprocess.run(["bash", "-c", script, "_", path, str(start)],
                              capture_output=True, text=True).stdout


if specs_fn:
    SUMMARY = ("  ✘  2 [chromium] › e2e/login.spec.ts:14:5 › Login › signs in (1.5m)\n"
               "  ✘  5 [chromium] › e2e/flaky.spec.ts:1:1 › flaky (2.1s)\n"
               "  ✓  6 [chromium] › e2e/flaky.spec.ts:1:1 › flaky (retry #1) (1.0s)\n"
               "  2 failed\n"
               "    [chromium] › e2e/login.spec.ts:14:5 › Login › signs in ─────────\n"
               "    [chromium] › e2e/my dir/cart.spec.ts:8:3 › a; b ──────\n"
               "  1 flaky\n"
               "    [chromium] › e2e/flaky.spec.ts:1:1 › flaky ─────\n"
               "  59 passed (7.2m)\n")
    check("failed-specs-from-the-summary", failed_specs(SUMMARY),
          "Login › signs in (login.spec.ts:14); a; b (cart.spec.ts:8)\n")
    check("failed-specs-through-colours",
          failed_specs("  \x1b[31m2 failed\x1b[39m\n"
                       "    \x1b[31m[chromium] › a.spec.ts:3:1 › red\x1b[39m\n"), "red (a.spec.ts:3)\n")
    check("failed-specs-counts-the-rest",
          failed_specs("  5 failed\n" + "".join("    [chromium] › s.spec.ts:%d:1 › t%d\n" % (i, i)
                                                 for i in range(1, 6))),
          "t1 (s.spec.ts:1); t2 (s.spec.ts:2); t3 (s.spec.ts:3) (+2 more)\n")
    # Cut off before the summary: the list lines, a spec retried green left out.
    check("failed-specs-without-a-summary", failed_specs(SUMMARY[:SUMMARY.index("  2 failed")]),
          "Login › signs in (login.spec.ts:14)\n")
    check("failed-specs-only-this-attempt",
          failed_specs("  1 failed\n    a.spec.ts:1:1 › early\n=== again ===\n"
                       "  1 failed\n    b.spec.ts:2:1 › late\n", start=4),
          "late (b.spec.ts:2)\n")
    check("failed-specs-silent-without-playwright", failed_specs("error TS2304\n"), "")
check_true("red-line-names-the-specs",
           "failed on $failed${failed_specs:+: $failed_specs}" in regression)

# The topic's account of a run: one line at its start and one at its end, in
# the shape every session takes; a sound only when red, and no log tail.
notify_fns = "\n".join(re.search(r"^%s\(\) \{.*?^\}" % n, regression, re.S | re.M).group(0)
                       for n in ("regression_duration", "regression_notify_start", "regression_notify_done"))


def notified(call):
    script = ('source "%s/steps.sh"\n'
              'notify_feature() { local slug="$1"; shift; printf "%%s|%%s\\n" "$slug" "$*"; }\n'
              % os.path.join(ROOT, "sclaude", "lib")) + notify_fns + "\n" + call
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          timeout=30).stdout.strip()


check("notify-start", notified('regression_notify_start demo local "" 12 720'),
      "demo|--quiet 🧪 Regression started: local · 12 parts, expected 12m 00s")
check("notify-start-deployed", notified('regression_notify_start demo preview https://p.example 1'),
      "demo|--quiet 🧪 Regression started: preview (https://p.example) · 1 part")
check("notify-green", notified('regression_notify_done demo local "" 12 12 820'),
      "demo|--quiet 🧪 Regression finished: local, green · 12/12, 13m 40s")
check("notify-red", notified('regression_notify_done demo local e2e 11 12 843 "Login › signs in (login.spec.ts:14)"'),
      "demo|🧪 Regression failed: local, on e2e: Login › signs in (login.spec.ts:14) · 11/12, 14m 03s")
_tail_log = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
_tail_log.write("=== typecheck ===\n\nsrc/a.ts(3,1): error TS2304\nFound 1 error.\n")
_tail_log.close()
check("notify-red-without-specs-brings-the-tail",
      notified('regression_notify_done demo local typecheck 0 3 9 "" "" %s' % _tail_log.name),
      "demo|🧪 Regression failed: local, on typecheck · 0/3, 9s\n=== typecheck ===\n"
      "src/a.ts(3,1): error TS2304\nFound 1 error.")
os.unlink(_tail_log.name)
check("notify-broken", notified('regression_notify_done demo preview e2e 0 1 60 "" https://p.example'),
      "demo|🧪 Regression could not run: preview · every spec failed and https://p.example is not serving"
      " — the environment, not the code")

# Once, local, e2e — and a retried part's time is not the suite's.
check_true("retry-only-local-e2e-once",
           '"$stage" == "local" && "$part" == "e2e" && -z "$retried"' in regression)
check_true("retry-restarts-the-server",
           re.search(r'retried=1(?:.|\n)*?stop_own_dev(?:.|\n)*?ensure_dev(?:.|\n)*?continue',
                     regression) is not None)
check_true("retried-time-not-remembered",
           '[[ -n "$retried" ]] || regression_remember' in regression)

# The production block stops at its first failure, so putting the main tree's
# environment back cannot be one of its commands: a promote that failed halfway
# left the tree on production.
prod_block = deploy[deploy.index('"${prod_note:-The branch adds migrations'):]
check_true("prod-restore-after-the-block",
           re.search(r'^\s+fi\n\s+if \[\[ -n "\$snapshot" \]\]; then\n\s+environment_restore',
                     prod_block, re.M) is not None)
check_true("prod-restore-not-a-block-command", "prod_cmds+=(\"environment_restore" not in deploy)

# --in with no value after it: an option loop that cannot shift spins for ever.
notify_run = subprocess.run(
    [os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "sclaude-notify"),
     "--in"], input="text", capture_output=True, text=True, timeout=10,
    env=dict(os.environ, HOME=tempfile.mkdtemp()))
check_true("notify-in-without-value-returns", notify_run.returncode == 0)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  expected: %r\n  got:      %r" % (name, want, got))
    print("\n%d check(s) failed." % len(failures))
    sys.exit(1)
print("All checks passed.")

