#!/usr/bin/env python3
#
# A test bench for the merge offer: when sclaude may propose the merge, and
# what it does when it may not.
#
# The merge is the one part of the cycle that belongs to a person, and that
# does not change here — nothing merges without a yes, unless the project set
# `merge` to auto in its config. What is under test is
# the judgement around the question: offering a merge that GitHub would refuse
# wastes the answer, and offering one before QA has looked claims a check
# nobody performed. Both failures are silent, which is why they are worth a
# bench.
#
# The two classifiers are exercised for real rather than read as text: they are
# the whole decision, they are pure functions of one JSON document, and a table
# of documents against expected verdicts is the honest way to hold them. The
# shell around them is read as text, the way the other benches read it — see
# tests/regression.py for why sourcing is not worth its cost.
#
# Run it with: python3 tests/merge.py
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

deploy = open(os.path.join(ROOT, "sclaude", "lib", "deploy.sh"),
              encoding="utf-8").read()
run_sh = open(os.path.join(ROOT, "sclaude", "lib", "run.sh"),
              encoding="utf-8").read()
github = open(os.path.join(ROOT, "sclaude", "lib", "github.sh"),
              encoding="utf-8").read()

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def body_of(text, name):
    """A shell function's body, or None."""
    found = re.search(r"^%s\(\)\s*\{(.*?)^\}" % re.escape(name), text,
                      re.S | re.M)
    return found.group(1) if found else None


# --- the readiness classifier ------------------------------------------------
#
# The python inside merge_readiness, pulled out of the heredoc and run against
# a document per GitHub state. Extracting it by regex rather than copying it
# here is deliberate: a copy would pass this bench for ever while the shell
# said something else.
ready_src = re.search(r"<<'PYREADY'\n(.*?)\nPYREADY", deploy, re.S)
check_true("readiness-python-found", ready_src is not None)


def readiness(document):
    env = dict(os.environ, MERGE_JSON=document)
    out = subprocess.run([sys.executable, "-c", ready_src.group(1)],
                         env=env, capture_output=True, text=True)
    return out.stdout.strip()


def pr(**fields):
    import json
    base = {"state": "OPEN", "mergeable": "MERGEABLE",
            "mergeStateStatus": "CLEAN", "isDraft": False,
            "viewerCanUpdate": True}
    base.update(fields)
    return json.dumps(base)


if ready_src:
    # The one state that earns a question. Both fields have to agree: a
    # MERGEABLE pull request in a BLOCKED state has no conflicts and still
    # cannot be merged, and calling that ready is the mistake this pairing
    # exists to prevent.
    check("ready-when-clean-and-mergeable", readiness(pr()), "ready")
    check("blocked-is-not-ready",
          readiness(pr(mergeStateStatus="BLOCKED")), "blocked")
    check("conflicts-by-state",
          readiness(pr(mergeStateStatus="DIRTY")), "dirty")
    # Either field alone is enough to call it dirty: they are computed
    # separately on GitHub's side and have been seen to disagree.
    check("conflicts-by-mergeable",
          readiness(pr(mergeable="CONFLICTING")), "dirty")
    check("behind-main", readiness(pr(mergeStateStatus="BEHIND")), "behind")
    check("checks-unstable",
          readiness(pr(mergeStateStatus="UNSTABLE")), "unstable")
    check("draft-is-not-ready", readiness(pr(isDraft=True)), "draft")
    check("no-rights-is-not-ready",
          readiness(pr(viewerCanUpdate=False)), "norights")

    # A pull request that is not open is not a thing to report on: the caller
    # has already established the branch is unmerged, so this is a race, and
    # "unknown" makes it say nothing rather than something wrong.
    check("closed-pr-says-nothing", readiness(pr(state="MERGED")), "unknown")

    # mergeable is computed lazily: the first ask after a push answers UNKNOWN
    # and the real answer lands a second later. Reporting that as an obstacle
    # would put a sentence on the screen every time somebody pushed.
    check("lazy-mergeability-says-nothing",
          readiness(pr(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")),
          "unknown")

    # A state GitHub adds later must not fall into "ready" — the default has to
    # be the cautious one, because the failure mode of the other default is
    # offering to merge something nobody understands.
    check("unfamiliar-state-is-not-ready",
          readiness(pr(mergeStateStatus="HAS_HOOKS")), "unknown")

    # gh silent, or answering something that is not JSON at all.
    check("garbage-says-nothing", readiness("not json"), "unknown")
    check("empty-says-nothing", readiness(""), "unknown")


# --- the merge method --------------------------------------------------------
#
# `gh pr merge --squash` fails outright where squash merging is switched off,
# and it fails after the human has already agreed — so the flag is asked for
# rather than assumed.
method_src = re.search(r"<<'PYMETHOD'\n(.*?)\nPYMETHOD", deploy, re.S)
check_true("method-python-found", method_src is not None)


def method(document):
    env = dict(os.environ, MERGE_REPO_JSON=document)
    out = subprocess.run([sys.executable, "-c", method_src.group(1)],
                         env=env, capture_output=True, text=True)
    return out.stdout.strip()


if method_src:
    import json
    check("prefers-squash",
          method(json.dumps({"squashMergeAllowed": True,
                             "mergeCommitAllowed": True,
                             "rebaseMergeAllowed": True})), "--squash")
    check("falls-back-to-merge-commit",
          method(json.dumps({"squashMergeAllowed": False,
                             "mergeCommitAllowed": True,
                             "rebaseMergeAllowed": True})), "--merge")
    check("falls-back-to-rebase",
          method(json.dumps({"squashMergeAllowed": False,
                             "mergeCommitAllowed": False,
                             "rebaseMergeAllowed": True})), "--rebase")
    # A repository that allows nothing, and a gh that said nothing, both end at
    # squash: a wrong guess here costs a refused command, not a bad merge.
    check("nothing-allowed-still-answers",
          method(json.dumps({"squashMergeAllowed": False,
                             "mergeCommitAllowed": False,
                             "rebaseMergeAllowed": False})), "--squash")
    check("garbage-still-answers", method("nope"), "--squash")


# --- what the offer requires -------------------------------------------------
offer = body_of(deploy, "merge_offer")
check_true("merge-offer-exists", offer is not None)

if offer:
    # QA's word, where there is a board to carry it. An issue that exists and
    # sits anywhere but Done means the checking is still ahead: the board is
    # being kept, so its answer is worth waiting for, and the caller's reminder
    # stands.
    # Through column_is: the board and .sclaude/config.json are typed apart, and case
    # must not decide whether QA's word counts.
    check_true("offer-requires-the-qa-column", 'column_is "$column" "$QA_DONE"' in offer)
    check_true("a-waiting-issue-blocks-the-offer",
               re.search(r'if column_is "\$column" "\$QA_DONE"; then\s*\n\s*qa_checked=1\s*\n\s*elif \[\[ -n "\$column" \]\]; then(?:.|\n)*?return 1',
                         offer) is not None)
    # And only a column that exists blocks it. issue_status_now answers empty
    # for an issue on no board, for a silent gh and for a dead network — none
    # of which is QA still working, and reading them as "not yet" would hold
    # the offer back for ever on a repository with no project board.
    check_true("an-empty-column-does-not-block-the-offer",
               re.search(r'elif \[\[ -n "\$column" \]\]; then', offer) is not None)
    # The unchecked wording tells the two apart: a feature with no issue, and
    # an issue that is on no board. Both skip QA, but calling the second one
    # "no issue" is how a line stops being trusted.
    # Asserted as the branch, not as a loose string: the same sentence sitting
    # in both arms would satisfy a substring check while saying "no issue"
    # about a feature that plainly has one.
    check_true("no-board-is-worded-separately",
               re.search(r'if \[\[ -n "\$issue" && "\$issue" != "null" \]\]; then\s*\n\s*say[^\n]*is on no board[^\n]*\n\s*else\s*\n\s*say[^\n]*No issue on GitHub',
                         offer) is not None)
    # Read now, not remembered: the preview deploy and the regression above
    # take minutes, and QA may have answered during them.
    check_true("offer-reads-the-column-now", "issue_status_now" in offer)

    # A feature started from a name alone has no issue and never will.
    # Treating that as "QA has not passed" would mean it never gets an offer
    # however green it is — punishing the absence of a board rather than the
    # absence of a check. So the offer stands and the question carries the
    # difference.
    check_true("no-issue-does-not-block-the-offer",
               re.search(r'\[\[ -n "\$issue" && "\$issue" != "null" \]\] \|\| return 1',
                         offer) is None)
    check_true("qa-checked-is-tracked", "qa_checked=0" in offer and "qa_checked=1" in offer)
    # Two wordings, because they are two different things to agree to. The
    # unchecked one has to say so in the question itself: it is the only
    # protection available, the repository being private on a free plan where
    # branch protection is refused.
    check_true("unchecked-merge-says-so", "Merge it unchecked?" in offer)
    check_true("unchecked-merge-names-the-gap",
               "nobody signed off on the deployment" in offer)
    check_true("checked-merge-keeps-its-wording", "Merge it now?" in offer)
    # And the obstacle line must not claim a QA pass that never happened.
    check_true("obstacle-does-not-invent-a-qa-pass",
               re.search(r'if \[\[ "\$qa_checked" -eq 1 \]\]; then\s*\n\s*warn "QA passed issue',
                         offer) is not None)

    check_true("offer-needs-a-pr",
               re.search(r'\[\[ -n "\$pr" && "\$pr" != "null" \]\] \|\| return 1',
                         offer) is not None)
    check_true("offer-needs-gh", "command -v gh" in offer)

    # Only `ready` reaches the question.
    check_true("only-ready-is-offered", '"$ready" != "ready"' in offer)
    # And an obstacle we have no words for is not announced: merge_obstacle
    # answers empty for `unknown`, and that empty is what keeps a lazily
    # computed mergeability off the screen.
    check_true("silent-without-words-for-it",
               re.search(r'\[\[ -n "\$obstacle" \]\] \|\| return 1', offer)
               is not None)

    # The question defaults to no, like every other question that changes the
    # world in this repository.
    check_true("offer-asks", "ask " in offer and "[y/n]" in offer)
    check_true("offer-defaults-to-no", "is_yes" in offer)
    # The command is shown before it is run: the human agrees to what they see.
    check_true("offer-shows-the-command",
               re.search(r'say "  gh pr merge \$pr \$method"', offer) is not None)

    # A refusal is an answer, not a failure — it returns non-zero so the caller
    # falls through to the reminder, and it says so rather than going quiet.
    check_true("refusal-is-reported", "Merge: skipped" in offer)
    # A merge gh refused must not be reported as done, or the cycle carries on
    # into production off an unmerged branch.
    check_true("failed-merge-returns-nonzero",
               re.search(r"if ! gh pr merge(?:.|\n)*?return 1", offer) is not None)

    # --delete-branch is deliberately absent: `sclaude done` removes the
    # worktree, the local branch and the remote one together, and it is what
    # the human is sent to next.
    check_true("no-delete-branch", "--delete-branch" not in offer)

    # `merge`: github keeps the question out of sclaude; auto answers it, on
    # the same conditions — after QA's column and GitHub's readiness.
    check_true("offer-reads-the-merge-mode", 'project_flow_mode merge' in offer)
    check_true("github-mode-never-asks",
               re.search(r'\[\[ "\$who" != github \]\] \|\| return 1', offer) is not None
               and offer.find('!= github ]] || return 1') < offer.find("issue_status_now"))
    check_true("auto-merges-after-readiness",
               offer.find('"$ready" != "ready"') < offer.find('"$who" == auto'))
    check_true("auto-does-not-ask",
               re.search(r'if \[\[ "\$who" == auto \]\]; then\s*\n\s*say[^\n]*\n\s*else\s*\n\s*ask ',
                         offer) is not None)

mwait = body_of(deploy, "merge_wait") or ""
check_true("merge-wait-m-merges-from-here",
           '"$mode" == both && "$POLL_KEY" == [mM]' in mwait and "merge_offer" in mwait)
check_true("merge-wait-auto-tries-once", "auto_tried=1" in mwait)
check_true("merge-wait-gets-the-offer-mode",
           'merge_wait "$slug" "$issue" "$pr" "$branch" "$offer_mode"' in deploy)


# --- one preview block, two callers -----------------------------------------
#
# `sclaude preview` and the cycle once built the block separately and drifted:
# the typed command deployed without the branch's migrations and recorded the
# deploy, which the cycle then skipped as unchanged.
sclaude_bin = open(os.path.join(ROOT, "bin", "sclaude"), encoding="utf-8").read()
cmd_preview = body_of(sclaude_bin, "cmd_preview")
check_true("cmd-preview-exists", cmd_preview is not None)
if cmd_preview:
    check_true("cmd-preview-applies-migrations", "preview_apply_migrations" in cmd_preview)
    check_true("cmd-preview-uses-the-shared-block", 'preview_deploy "$wt"' in cmd_preview)
    check_true("cmd-preview-builds-no-block-of-its-own", "run_block" not in cmd_preview)


# --- where the offer is made -------------------------------------------------
remind = body_of(deploy, "remind_prod")
check_true("remind-prod-exists", remind is not None)

if remind:
    call_at = remind.find("merge_offer ")
    check_true("remind-prod-offers-the-merge", call_at > -1)

    # After the preview deploy and after the regression gate: those are what
    # make the branch worth merging, and offering earlier would be offering to
    # merge something nobody has checked.
    preview_at = remind.find('preview_ship "$wt"')
    gate_at = remind.find('regression_gate "$wt" "$slug" preview')
    check_true("offer-comes-after-the-preview", -1 < preview_at < call_at)
    check_true("offer-comes-after-the-regression", -1 < gate_at < call_at)

    # The branch's migrations reach the preview database before the deploy,
    # outside the retry loop (which lives in preview_ship), and on the skipped
    # path too: an unchanged tree deployed without them would otherwise stay
    # without them.
    apply_at = remind.find('preview_apply_migrations "$wt" || true\n    if preview_ship "$wt"')
    check_true("preview-applies-migrations-before-the-retries", apply_at > -1)
    check_true("migrations-stay-outside-the-retries",
               "preview_apply_migrations" not in (body_of(deploy, "preview_ship") or ""))
    skip_at = remind.find("unchanged and green, skipping")
    check_true("preview-applies-migrations-when-skipped",
               -1 < skip_at < remind.find('preview_apply_migrations', skip_at) < apply_at)

    # A red preview returns before the offer is reached — the gate's own path
    # says production is not offered, and neither is the merge.
    red_at = remind.find("The preview regression is red")
    check_true("red-preview-returns-first", -1 < red_at < call_at)

    # And before the consequences: a merge agreed to here has to carry on into
    # the same run rather than ending the cycle with an errand.
    end_date_at = remind.find("issue_end_date")
    prod_at = remind.find("Ship to production")
    check_true("offer-comes-before-the-end-date", call_at < end_date_at)
    check_true("offer-comes-before-production", call_at < prod_at)

    # Which is only true if a successful offer updates the variable the rest of
    # the function branches on.
    check_true("a-merge-here-counts-as-merged",
               re.search(r'merge_offer "\$slug" "\$pr" "\$issue"( "\$offer_mode")?; then\n\s*merged="MERGED"',
                         remind) is not None)
    # Not asked at all when the branch is already in main.
    check_true("offer-skipped-when-already-merged",
               re.search(r'\[\[ "\$\{merged:-\}" != "MERGED" \]\] && merge_offer',
                         remind) is not None)

    # The fallback names the ticket, not only the pull request: a person tracks
    # the work by the issue's number and answers QA in it.
    check_true("reminder-names-the-ticket",
               'Waiting for the merge of PR #$pr${issue:+ (issue #$issue)}' in remind)

    # --- "In QA" comes after the regression, never before --------------------
    #
    # The column is the one sclaude writes itself, and it is allowed to only
    # because what it claims is checkable: the branch is deployed and every
    # test passed against that deployment. Moving the issue before the suite
    # runs turns a statement of fact back into a request, and sends QA to look
    # at something that may be broken.
    #
    # The order is one line's worth of fragility — issue_qa_ready sits inside
    # the gate's `then`, and lifting it out would still run, still pass every
    # other check, and quietly move the issue on a red run.
    # The call, not the mention: a comment further up names issue_qa_ready
    # while explaining why a skipped preview does not need it, and a plain
    # find() would measure that sentence instead of the code.
    qa_move = re.search(r'^\s*\[\[ -n "\$issue" \]\] && issue_qa_ready "\$issue"',
                        remind, re.M)
    gate_call_at = remind.find('regression_gate "$wt" "$slug" preview')
    check_true("qa-move-exists", qa_move is not None)
    check_true("qa-move-comes-after-the-gate",
               qa_move is not None and -1 < gate_call_at < qa_move.start())
    # Inside the green branch, not merely after the call: `gate; issue_qa_ready`
    # would satisfy an ordering check and still move the issue on a red run.
    #
    # The match allows lines between the `then` and the move, but none of them
    # may open a block or end one — that is what keeps it a proof of being
    # *inside* the branch rather than merely below it. It used to demand the two
    # be adjacent, which read the same until the green branch grew a line of its
    # own (preview_live, which the label depends on) and the check failed over
    # placement rather than over meaning.
    check_true("qa-move-is-inside-the-green-branch",
               re.search(r'if regression_gate "\$wt" "\$slug" preview; then\n'
                         r'(?:[ \t]*(?!.*\b(?:if|then|else|fi|while|do|done)\b)\S[^\n]*\n)*?'
                         r'[ \t]*\[\[ -n "\$issue" \]\] && issue_qa_ready "\$issue"',
                         remind) is not None)
    # And the red path says so and leaves the board alone.
    check_true("red-preview-leaves-the-issue",
               "The issue stays where it is" in remind)
    check_true("red-preview-returns-before-the-qa-move",
               -1 < red_at and remind.find("The issue stays where it is") > gate_call_at)


# --- the obstacles have words ------------------------------------------------
obstacle = body_of(deploy, "merge_obstacle")
check_true("merge-obstacle-exists", obstacle is not None)

if obstacle:
    # Every state the classifier can return except the two that say nothing.
    for state in ("dirty", "blocked", "behind", "unstable", "draft", "norights"):
        check_true("obstacle-covers-%s" % state,
                   re.search(r"^\s*%s\)" % state, obstacle, re.M) is not None)
    # `unknown` deliberately has none: it means "ask again", not "something is
    # wrong", and a sentence for it would appear on every freshly pushed branch.
    check_true("unknown-has-no-words",
               re.search(r"^\s*unknown\)", obstacle, re.M) is None)


# --- QA, then the merge --------------------------------------------------------
#
# Step 4 used to wait for the merge, and that ran the back half of the cycle in
# the wrong order: the preview, "In QA" and the QA watch are in remind_prod,
# which only runs once step 4 has closed — so the branch was merged first and QA
# looked at main afterwards (it happened once). Step 4 now closes with
# the pull request open, and remind_prod waits for QA and then for the merge.
after_step = body_of(run_sh, "after_step") or ""
review_branch = after_step[after_step.find("    review)"):
                           after_step.find("    *)", after_step.find("    review)"))]
check_true("review-branch-found", "regression_gate" in review_branch)
check_true("review-step-does-not-poll-the-merge",
           "while [[" not in review_branch and "sleep" not in review_branch)
check_true("review-step-says-the-pr-stays-open", "stays open" in review_branch)

if remind:
    qa_at = remind.find('qa_wait "$slug" "$issue" "$pr"')
    offer_at = remind.find("merge_offer ")
    wait_at = remind.find('merge_wait "$slug" "$issue" "$pr" "$branch"')
    gate_at = remind.find('regression_gate "$wt" "$slug" preview')
    # QA looks at the preview, so the wait comes after the gate; nothing is
    # offered for merging before QA has decided; the wait for the merge
    # follows the offer the person declined.
    check_true("qa-wait-after-the-preview", -1 < gate_at < qa_at)
    check_true("qa-wait-before-the-offer", -1 < qa_at < offer_at)
    check_true("merge-wait-after-the-offer", -1 < offer_at < wait_at)
    # A hand-back goes into the review session in the same run.
    check_true("hand-back-reopens-the-review",
               re.search(r'qa_take_back "\$wt" "\$slug" \|\| return 0\n\s*run_step "\$wt" "\$slug" review',
                         remind) is not None)
    # With no green preview up the issue never went to QA, and In progress
    # would read as a hand-back that never happened.
    check_true("waits-need-a-live-preview",
               remind.count('"$preview_live" -eq 1') >= 2)

if remind:
    # The preview is not asked about, and a failed deploy is tried again.
    ship = body_of(deploy, "preview_ship") or ""
    check_true("preview-retries", "PREVIEW_TRIES" in ship
               and 'sleep "$PREVIEW_RETRY_PAUSE"' in ship)
    # It records what it deployed and where, for the regression to aim at.
    check_true("preview-ship-remembers",
               'deploy_remember "$wt" preview' in ship
               and "regression.preview.url" in ship)
    # Skipped only when unchanged *and* green: an unchanged tree whose last run
    # was red is deployed again.
    check_true("unchanged-red-preview-is-redeployed",
               re.search(r'deploy_unchanged "\$wt" preview \\\n\s*&& \[\[ "\$\(regression_status',
                         remind) is not None)
    # A merged pull request skips the preview, and says so in red: it is an
    # exception to the flow, not a routine skip.
    merged_at = remind.find('elif [[ "${merged:-}" == "MERGED" ]]; then')
    deploy_at = remind.find('preview_ship "$wt"')
    check_true("merged-skips-the-preview", -1 < merged_at < deploy_at)
    check_true("merged-skip-is-red",
               'alarm "PR #$pr is already merged — the preview and QA are skipped."' in remind)

# Done with the pull request still open is how QA says yes now; only a merged
# branch can have skipped QA.
qa_missed = body_of(deploy, "qa_missed") or ""
check_true("qa-missed-needs-a-merge", '[[ "$merged" == "MERGED" ]] || return 1' in qa_missed)
check_true("qa-missed-callers-pass-the-merge",
           deploy.count('qa_missed "$issue" "${merged:-}" "$wt"') == 2)
# Quiet on a preview QA accepted: later runs of a merged feature said "nobody
# checked" of one QA had.
check_true("qa-missed-quiet-when-accepted", "qa.accepted" in qa_missed)
check_true("qa-wait-records-acceptance", 'qa_accepted "$wt"' in (body_of(deploy, "qa_wait") or ""))
# A merge while QA has it ends the wait, and says so in red.
check_true("qa-wait-notices-a-merge",
           'qa_wait "$slug" "$issue" "$pr" "$branch"' in deploy
           and "was merged while QA still had issue" in deploy)
github = open(os.path.join(ROOT, "sclaude", "lib", "github.sh"), encoding="utf-8").read()
check_true("qa-ready-from-backlog-too",
           'issue_move_status "$1" "$QA_FROM" "$QA_TO" "$PROGRESS_FROM"' in github)

qa_wait = body_of(deploy, "qa_wait")
check_true("qa-wait-exists", qa_wait is not None)
if qa_wait:
    check_true("qa-wait-names-the-criteria", "acceptance criteria" in qa_wait)
    check_true("qa-wait-returns-two-on-a-hand-back", "return 2" in qa_wait)
    check_true("qa-wait-asks-to-fix-an-unexpected-column",
               "Please set the ticket status" in qa_wait)
    check_true("qa-wait-warns-about-unticked-criteria", "--unticked" in qa_wait)
    check_true("qa-wait-announces-the-merge-next", "Now waiting for the merge" in qa_wait)
    check_true("qa-wait-polls-at-qa-poll", 'poll_pause "$QA_POLL"' in qa_wait)

merge_wait = body_of(deploy, "merge_wait")
check_true("merge-wait-exists", merge_wait is not None)
if merge_wait:
    # The ticket beside the pull request: a person tracks the work by the
    # issue's number and answers QA in it.
    check_true("merge-wait-names-the-ticket",
               'PR #$pr${issue:+ (issue #$issue)}' in merge_wait)
    check_true("merge-wait-polls-at-merge-poll", 'poll_pause "$MERGE_POLL"' in merge_wait)


# --- the constant is shared --------------------------------------------------
#
# merge_offer compares against QA_DONE, which is now the project's
# (`board.columns.done`, loaded by board_load). A project that declares none has
# no column that could ever carry QA's word, so it must not be waited on: the
# guard has to be on the branch that reads the board.
check_true("qa-done-guarded-in-offer",
           re.search(r'if \[\[ -n "\$issue" && "\$issue" != "null" && -n "\$QA_DONE" \]\]; then',
                     offer or "") is not None)


# --- a key cuts the wait short ----------------------------------------------
#
# Someone who has just merged, or moved the issue to Done, presses a key and
# the look happens now rather than at the end of the minute. Run for real, in
# a pseudo-terminal: the key is read from /dev/tty, which a pipe does not have.
# The arrow after the first key must be swallowed too, or it would answer the
# next question.
check_true("review-wait-polls-with-poll-pause",
           'poll_pause "$MERGE_POLL"' in (body_of(run_sh, "review_wait_state") or ""))


def pause_in_pty(keys):
    import pty
    import select
    import time
    lib = os.path.join(ROOT, "sclaude", "lib")
    script = ('source "%s/ui.sh"; s=$SECONDS; poll_pause 20; '
              'echo "PAUSED $((SECONDS - s))"; '
              'read -rsn1 -t 1 left < /dev/tty && echo "LEFT" || echo "CLEAN"' % lib)
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("bash", ["bash", "--norc", "-c", script])
    out = b""
    time.sleep(0.5)
    if keys:
        os.write(fd, keys)
    deadline = time.time() + 30
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 1024)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
        if b"CLEAN" in out or b"LEFT" in out:
            break
    os.waitpid(pid, 0)
    return out.decode("utf-8", "replace")


pressed = pause_in_pty(b"x\x1b[A")
m = re.search(r"PAUSED (\d+)", pressed)
check_true("a-key-ends-the-pause", m is not None and int(m.group(1)) < 5)
check_true("the-rest-of-the-key-is-swallowed", "CLEAN" in pressed)

# Without a terminal on stdout or stderr it is a plain sleep: nothing on
# screen says a key would do anything, and a pipe must not block on a tty.
piped = subprocess.run(
    ["bash", "-c", 'source "%s/sclaude/lib/ui.sh"; sleep() { echo "slept $1"; }; '
                   'poll_pause 7' % ROOT],
    capture_output=True, text=True, stdin=subprocess.DEVNULL)
check("no-terminal-sleeps", piped.stdout.strip(), "slept 7")


if failures:
    for name, want, got in failures:
        print("FAIL %s\n  expected: %r\n  got:      %r" % (name, want, got))
    print("\n%d check(s) failed." % len(failures))
    sys.exit(1)
print("All checks passed.")
