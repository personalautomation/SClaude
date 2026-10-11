#!/usr/bin/env python3
#
# A test bench for QA handing a feature back.
#
# The watcher already did the hard half well: it sees the column leave "In QA",
# collects what was said since the watch began, and saves the comments verbatim
# so the step's session can answer a person rather than a summary of one. What
# was missing was the other half — the cycle actually going back.
#
# And it failed in the main case rather than an edge one. `watch_start` is
# called from remind_prod, so a feature waiting on QA always sits at
# `step: done`; `cmd_resume` returns for a done feature before it reads the
# verdict, so the one state the block was written for was the one state it could
# not be reached in. The comments were saved, no session was opened to hand them
# to, and the human was shown the production reminder as though QA had said
# nothing.
#
# So what is guarded here is an ordering in a source file and a handful of state
# transitions — nothing that raises when it goes wrong, which is why it went
# unnoticed.
#
# Run it with: python3 tests/qa-return.py
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


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def code_lines(text):
    """The file's code, with whole-line comments dropped.

    Three checks in this session's benches passed against a mutation because the
    string they looked for survived in the comment explaining the fix. A test
    that reads prose cannot see the code go.
    """
    return [ln for ln in text.splitlines() if not ln.strip().startswith("#")]


def run_bash(script, cwd, modules=("io", "ui", "steps", "state", "watch")):
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
    for name in modules:
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('die()  { echo "$*" >&2; exit 1; }\n'
             'warn() { echo "$*" >&2; }\n'
             'info() { echo "$*"; }\n'
             'say()  { echo "$*"; }\n'
             # issue_sync lives in github.sh and reaches the network; what is
             # under test is the state, not GitHub.
             'issue_sync() { :; }\n')
    body += script
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, timeout=30)
    return out.stdout, out.stderr, out.returncode


def feature(root, step="done", review_done=True):
    """A worktree whose feature has been through every step."""
    wt = os.path.join(root, "wt")
    os.makedirs(os.path.join(wt, ".feature"), exist_ok=True)
    state = {
        "feature": "demo", "branch": "feat/demo", "issue": 71, "pr": 208,
        "step": step,
        "steps": {
            "plan": {"done": True, "finished": "2026-09-10T09:00:00+03:00"},
            "code": {"done": True, "finished": "2026-09-10T14:00:00+03:00"},
            "pr": {"done": True, "finished": "2026-09-10T15:00:00+03:00"},
            "review": {"done": review_done,
                       "finished": "2026-09-11T11:00:00+03:00" if review_done else None},
        },
        "regression": {
            "preview": {"status": "passed", "attempts": 0},
            "prod": {"status": "passed"},
        },
    }
    with open(os.path.join(wt, ".feature", "state.json"), "w") as fh:
        json.dump(state, fh)
    return wt


def read(wt, path):
    out, _, rc = run_bash('state_get %s/.feature/state.json %s' % (wt, path),
                          os.path.dirname(wt))
    return out.strip() if rc == 0 else None


tmp = tempfile.mkdtemp()
try:
    # --- the ordering that was the whole bug --------------------------------

    sclaude = open(os.path.join(ROOT, "bin", "sclaude"), encoding="utf-8").read()
    code = "\n".join(code_lines(sclaude))
    verdict_at = code.find('case "$(watch_verdict "$slug")" in')
    done_at = code.find('if [[ "$step" == "done" ]]; then')
    check_true("verdict-block-found", verdict_at > 0)
    check_true("done-return-found", done_at > 0)
    # The positional guard, the same shape tests/regression.py uses to pin the
    # rollback ahead of any fixing session. Below the return, the block is
    # unreachable for exactly the features it exists for.
    check_true("verdict-read-before-the-done-return",
               0 < verdict_at < done_at)

    # --- the rewind ----------------------------------------------------------

    wt = feature(tmp)
    check("before-step", read(wt, "step"), "done")
    check("before-review-done", read(wt, "steps.review.done"), "true")
    check("before-preview", read(wt, "regression.preview.status"), "passed")

    run_bash('watch_rewind %s demo' % wt, tmp)

    check("after-step", read(wt, "step"), "review")
    check("after-review-done", read(wt, "steps.review.done"), "false")
    # A closing time from the previous pass would claim, in the issue's summary,
    # a completeness that is gone.
    check("after-review-finished-cleared", read(wt, "steps.review.finished"), None)

    # The preview's verdict goes with it, and only the preview's. Left `passed`,
    # regression_gate short-circuits on it and the fix returns to QA without the
    # deployment ever being checked again.
    check("after-preview-cleared", read(wt, "regression.preview.status"), None)
    check("after-preview-attempts-reset", read(wt, "regression.preview.attempts"), "0")
    # prod is not cleared: if production shipped, that verdict is about a
    # deployment QA's comment did not concern.
    check("after-prod-kept", read(wt, "regression.prod.status"), "passed")

    # Only the review is rewound. The earlier steps were passed and stay passed
    # — a hand-back is not a replan.
    check("after-code-still-done", read(wt, "steps.code.done"), "true")
    check("after-code-finished-kept", read(wt, "steps.code.finished"),
          "2026-09-10T14:00:00+03:00")
    check("after-plan-still-done", read(wt, "steps.plan.done"), "true")

    # Rewinding twice is harmless: the second pass finds `review.done` already
    # false and leaves it, rather than writing `finished` as null for a step
    # that is already open.
    run_bash('watch_rewind %s demo' % wt, tmp)
    check("second-rewind-step", read(wt, "step"), "review")
    check("second-rewind-code-intact", read(wt, "steps.code.done"), "true")

    # A worktree with no state is not an error: the function answers nothing.
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    _, _, rc = run_bash('watch_rewind %s demo' % empty, tmp)
    check("rewind-without-a-state-is-quiet", rc, 0)

    # --- only `returned` rewinds ---------------------------------------------
    #
    # `done` means QA passed it and production is next; `other` means somebody
    # moved the column themselves. A rewind on either would undo a finished
    # cycle.
    # The rewind goes through qa_take_back, which remind_prod shares for a
    # hand-back it sees live; the helper itself is what calls watch_rewind.
    returned_at = code.find("      qa_take_back")
    check_true("rewind-called-from-the-verdict-block", returned_at > verdict_at)
    branch = code[code.find("    returned)"):code.find("  esac", verdict_at)]
    check_true("rewind-is-in-the-returned-branch", "qa_take_back" in branch)
    watch_code = "\n".join(code_lines(open(os.path.join(LIB, "watch.sh"),
                                            encoding="utf-8").read()))
    take_back = watch_code[watch_code.find("qa_take_back() {"):]
    take_back = take_back[:take_back.find("\n}")]
    check_true("take-back-rewinds", "watch_rewind" in take_back)
    done_branch = code[code.find("    done)", verdict_at):code.find("    returned)")]
    check_true("done-branch-does-not-rewind", "watch_rewind" not in done_branch)

    # --- the verdict is cleared after delivery -------------------------------
    #
    # Otherwise the same comments are prepended to every later resume, and a
    # second `sclaude <slug>` rewinds a feature that has moved on.
    watch_dir = os.path.join(tmp, "home", ".claude", "sclaude", "watch")
    os.makedirs(watch_dir)
    with open(os.path.join(watch_dir, "demo.json"), "w") as fh:
        json.dump({"feature": "demo", "verdict": "returned"}, fh)
    with open(os.path.join(watch_dir, "demo.qa.md"), "w") as fh:
        fh.write("the avatar does not load on iOS\n")

    out, _, _ = run_bash(
        'HOME=%s; watch_seen demo; echo "verdict=[$(watch_verdict demo)]"'
        % os.path.join(tmp, "home"), tmp)
    check("verdict-cleared-after-delivery", out.strip(), "verdict=[]")
    check("notes-moved-aside",
          os.path.exists(os.path.join(watch_dir, "demo.qa.md")), False)
    # Moved rather than deleted: they were written by a person and are the only
    # copy outside GitHub.
    check_true("notes-kept-for-later",
               os.path.exists(os.path.join(watch_dir, "demo.qa.md.seen")))

    # --- the shared helper ---------------------------------------------------
    #
    # Three callers wanted the same four lines; they now share one.
    steps_src = open(os.path.join(LIB, "steps.sh"), encoding="utf-8").read()
    check_true("helper-exists", "step_rewind_to()" in steps_src)
    for caller, path in (("regression_rewind", os.path.join(LIB, "regression.sh")),
                         ("watch_rewind", os.path.join(LIB, "watch.sh")),
                         ("cmd_replan", os.path.join(ROOT, "bin", "sclaude"))):
        src = "\n".join(code_lines(open(path, encoding="utf-8").read()))
        check_true("%s-uses-the-helper" % caller, "step_rewind_to" in src)

    # The helper leaves a step that never closed alone.
    #
    # The case has to be a step that is open *and* carries a time — which is the
    # real shape of an interrupted one, since `steps.<s>.started` and a stale
    # `finished` can both be present while `done` is false. A fixture whose
    # `finished` was already null could not tell the guard from its absence:
    # the first version of this check passed against a mutation that removed it.
    open_wt = os.path.join(tmp, "open", "wt")
    os.makedirs(os.path.join(open_wt, ".feature"))
    with open(os.path.join(open_wt, ".feature", "state.json"), "w") as fh:
        json.dump({"feature": "demo", "step": "review",
                   "steps": {"review": {"done": False,
                                        "finished": "2026-09-11T11:00:00+03:00"}}}, fh)
    run_bash('step_rewind_to %s review review' % open_wt, tmp)
    check("helper-leaves-an-open-step", read(open_wt, "steps.review.done"), "false")
    check("helper-does-not-touch-an-open-steps-time",
          read(open_wt, "steps.review.finished"), "2026-09-11T11:00:00+03:00")

    # --- the rewind must survive run_step ------------------------------------
    #
    # A review's own finding, and the sharpest one here: the rewind was undone
    # in the same breath it was made. run_step opens by treating a merged PR as
    # "nothing left to do" — it marks pr and review passed, sets step back to
    # done and goes to the production reminder. A feature waiting on QA is
    # almost always merged (the watch is armed in remind_prod, the merge offered
    # later in the same pass), so this was the ordinary path, not a corner: the
    # banner printed, the state was reverted, and the preview verdict was
    # destroyed on the way.
    #
    # The bench above could not see it — it exercises watch_rewind alone — so
    # these assertions are about the two of them agreeing.

    # These used to grep run.sh for the guard's text, and a review showed what
    # that is worth: adding one line — `reopened=""` right after the read, every
    # grepped substring still in place — left the guard doing nothing and the
    # bench still said `ok`. So they run the guard instead. The condition is
    # lifted out of run_step verbatim and evaluated against a real state file,
    # which a disabling edit cannot survive.
    run_sh = open(os.path.join(LIB, "run.sh"), encoding="utf-8").read()
    run_code = "\n".join(code_lines(run_sh))

    wt2 = feature(os.path.join(tmp, "marked"))
    run_bash('watch_rewind %s demo' % wt2, tmp)
    check("rewind-sets-reopened", read(wt2, "reopened"), "review")
    # And the pull request QA looked at, so after_step can tell the fix's own
    # from the one already merged.
    check("rewind-records-the-pr", read(wt2, "reopened_pr"), "208")
    # And that it was a return to development — one name whoever sent it: a
    # merge closes a review a preview fix reopened, and must not close this one.
    check("rewind-says-it-was-returned", read(wt2, "reopened_by"), "returned")

    # The guard's own lines, lifted out of run_step rather than rewritten here.
    #
    # A rewritten copy is what the first version of this check was, and it could
    # not see the guard die: disabling it in run.sh left the copy untouched and
    # the bench green. Extracting the real lines means a mutation to them is a
    # mutation to what runs here.
    # Everything from the declaration down to the `if` that uses it — not just
    # the two lines that read the state. A mutation disabling the guard puts its
    # line *between* them, and a capture that stopped at the read would miss it
    # exactly as the first version of this check did.
    guard = re.search(
        r'(  local reopened\n(?:.*\n)*?)  if \[\[ "\$reopened" != "\$step" \]\]',
        run_sh)
    check_true("guard-lines-found", guard is not None)

    def shortcut_fires(wt, step):
        """Does run_step's merged-PR shortcut still close this step?

        Zero means it fires and the merge would close the step.
        """
        if not guard:
            return None
        _, _, rc = run_bash(
            'state="%s/.feature/state.json"\n%s'
            '[[ "$reopened" != "%s" ]]' % (wt, guard.group(1), step), tmp)
        return rc == 0

    check("shortcut-blocked-after-a-rewind", shortcut_fires(wt2, "review"), False)
    # And not blocked for a step nobody reopened — step 3 closing on a merge is
    # what the shortcut is for, and `review.done` is false there for the
    # ordinary reason.
    check("shortcut-open-for-another-step", shortcut_fires(wt2, "pr"), True)

    # Cleared when the step closes for real, or a merged PR could never close
    # that step again.
    run_bash('state_set %s/.feature/state.json reopened null' % wt2, tmp)
    check("shortcut-open-once-the-mark-clears",
          shortcut_fires(wt2, "review"), True)

    # --- the verdict is acknowledged on every path it is shown ---------------
    #
    # watch_seen is called from inside run_step. A feature QA *passed* never
    # gets there — it goes to remind_prod — so before this the banner printed on
    # every `sclaude <slug>` until the clean-up. That was introduced by moving
    # the block above the done-return, where it had been unreachable.
    done_branch2 = code[code.find("    done)", verdict_at):code.find("    returned)")]
    check_true("done-verdict-acknowledged", "watch_seen" in done_branch2)
    # The returned branch must NOT acknowledge: the comments have not been
    # delivered yet, and watch_seen files them away.
    returned_branch = code[code.find("    returned)"):code.find("  esac", verdict_at)]
    check_true("returned-verdict-not-acknowledged-early",
               "watch_seen" not in returned_branch)

    # --- the comments reach a session that is not a resume -------------------
    #
    # watch_notes was read only on the resume path. A hand-back arriving after
    # the recorded session had gone — which is exactly when a transcript is most
    # likely to have been cleaned up — built a prompt without them, and then
    # watch_seen filed them aside at the end of the same function: consumed
    # without ever having been shown.
    fresh = run_code[run_code.index('session="$(new_session_id)'):]
    fresh = fresh[:fresh.index("claude ")] if "claude " in fresh else fresh
    check_true("fresh-session-gets-the-qa-notes", "watch_notes" in fresh)

    # --- the line does not name an empty step --------------------------------
    check_true("return-line-guarded", '[[ "$step" == "review" ]]' in take_back)

finally:
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
