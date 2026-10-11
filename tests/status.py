#!/usr/bin/env python3
#
# A test bench for a feature's outcome: the "Current status" comment, the
# snapshots handed to the sessions that write our comments, and walking the
# chain of parents.
#
# The main thing here is that no description is edited any more — see
# issue_comments.py. A developer has to be able to trust that the task in an
# issue is the one they were given, so every writer of ours goes to a comment,
# and the checks below keep a writer of the body from coming back.
#
# Run it with: python3 tests/status.py
import io
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
import issue_chain
import issue_comments
import issue_context
from issue_chain import MAX_DEPTH, chain, chain_numbers, nodes, progress
from issue_comments import AC_OPEN, REQUEST, STATUS

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


URL = "https://github.com/o/r/issues/%s#issuecomment-%s"


def said(number, cid, text):
    """A comment on issue `number` as gh returns it."""
    return {"body": text, "url": URL % (number, cid),
            "author": {"login": "someone"}}


# --- the status comment -------------------------------------------------------

# No status comment yet: the session is told to create one, on that issue.
none_yet = issue_chain.status_comment({"number": 7, "comments": [
    said(7, 1, "Just discussion.")]})
check_true("status-create-when-missing",
           "gh issue comment 7 --body-file -" in "\n".join(none_yet))

# One exists: shown as it stands, with the command that rewrites it by its id.
existing = issue_chain.status_comment({"number": 7, "comments": [
    said(7, 1, "Just discussion."),
    said(7, 55, STATUS + "\n## Current status\n\nOn preview.")]})
joined = "\n".join(existing)
check_true("status-shows-current-text", "On preview." in joined)
check_true("status-edits-by-id", "issues/comments/55" in joined)
check_true("status-does-not-create-a-second", "gh issue comment" not in joined)

# The chain's snapshot shows the description for reading and says it is not
# edited, a legacy block included.
legacy = {"number": 7, "title": "T", "state": "OPEN", "labels": [],
          "body": "Task.\n\n%s\n## Current status\n\nOld.\n" % STATUS,
          "comments": []}
one = "\n".join(issue_chain.render_one(legacy, 0))
check_true("chain-body-is-read-only", "for reading only" in one)
check_true("chain-legacy-block-left-alone", "Leave it" in one)

# "Current behaviour" is judged from what the description did not say: every
# level shows its "User request" comment, and the feature alone its discussion
# — the QA hand-backs and decisions that moved it away from the description.
talk = {"number": 7, "title": "T", "state": "OPEN", "labels": [], "body": "",
        "comments": [said(7, 81, REQUEST + "\n## User request\n\nName required."),
                     said(7, 82, "Returned from QA: rename Details to General."),
                     said(7, 83, STATUS + "\n## Current status\n\nLive.")]}
feature = "\n".join(issue_chain.render_one(talk, 0))
parent = "\n".join(issue_chain.render_one(talk, 1))
check_true("chain-request-on-feature", "Name required." in feature)
check_true("chain-request-on-parent", "Name required." in parent)
check_true("chain-discussion-on-feature", "rename Details to General" in feature)
check_true("chain-no-discussion-on-parent",
           "rename Details to General" not in parent)
# Our own comments are not discussion: the status is shown once, as a status.
check("chain-discussion-skips-ours", feature.count("Live."), 1)

# Past the cap the newest comments are kept: a later decision overrides an
# earlier one, so those are the ones that say how the product behaves. The
# filler is Cyrillic on purpose: the limit is in bytes, and a cap in characters
# let a Russian thread through at twice the size.
chatty = {"number": 7, "comments": [
    said(7, n, "c%02d " % n + "я" * issue_chain.MAX_COMMENT) for n in range(20)]}
kept_talk = "\n".join(issue_chain.discussion(chatty))
check_true("discussion-keeps-newest", "c19 " in kept_talk)
check_true("discussion-drops-oldest", "c00 " not in kept_talk)
check_true("discussion-says-what-it-dropped", "oldest are left out" in kept_talk)
check_true("discussion-fits-in-bytes",
           issue_comments.size(kept_talk) < issue_chain.MAX_DISCUSSION + 2000)
# A cut comment says where the whole of it is, by its own id.
check_true("discussion-cut-points-at-the-rest",
           "issues/comments/19 --jq .body" in kept_talk)
# With no room at all, nothing is kept and the session is told so.
none_kept = "\n".join(issue_chain.discussion(chatty, 0))
check_true("discussion-no-room", "All of them are left out" in none_kept)

# A rollback incident is ours, but the epilogue reads it as discussion: what
# was rolled back is part of how the feature behaves.
rolled = "\n".join(issue_chain.discussion({"number": 7, "comments": [
    said(7, 1, issue_comments.ROLLBACK + "\n## Production rolled back"),
    said(7, 2, "<!-- sclaude:my-feature -->\n| Step |")]}))
check_true("discussion-keeps-rollback", "Production rolled back" in rolled)
check_true("discussion-skips-summary", "| Step |" not in rolled)

# The request is cut too: it comes from every level, and step 2 keeps growing it.
long_request = "\n".join(issue_chain.render_one({"number": 3, "comments": [
    said(3, 81, REQUEST + "\n" + "я" * 2 * issue_chain.MAX_COMMENT)]}, 1))
check_true("request-cut", issue_comments.size(long_request)
           < issue_chain.MAX_COMMENT + 2000)

# The whole snapshot stays within its budget however long the thread: the
# discussion gets only the room the rest of the chain leaves.
big = {n: {"number": n, "title": "T", "state": "OPEN", "labels": [],
           "body": "я" * 5000,
           "parent": {"number": n + 1} if n < 4 else None,
           "comments": [said(n, 80 + n, REQUEST + "\n" + "я" * 20000)]
           + ([said(n, 100 + k, "я" * 20000) for k in range(30)] if n == 1 else [])}
       for n in range(1, 5)}
real_chain_fetch = issue_chain.fetch
issue_chain.fetch = lambda number, cwd=None: big.get(int(number))
try:
    snapshot = issue_chain.render(1)
finally:
    issue_chain.fetch = real_chain_fetch
check_true("snapshot-within-budget",
           issue_comments.size(snapshot) <= issue_chain.MAX_SNAPSHOT + 2000)
check_true("snapshot-keeps-some-discussion", "<<<COMMENT" in snapshot)


# --- the snapshot for step 1 ---------------------------------------------------

def context(body, comments):
    return "\n".join(issue_context.own_comments(
        {"number": 7, "body": body, "comments": comments}))


fresh = context("Please add drafts.", [])
check_true("request-create-when-missing", "gh issue comment 7" in fresh)
check_true("context-says-description-not-yours",
           "The description is not yours" in fresh)

kept = context("Please add drafts.", [
    said(7, 81, REQUEST + "\n## User request\n\nDrafts, author only.")])
check_true("request-shown", "Drafts, author only." in kept)
check_true("request-edits-by-id", "issues/comments/81" in kept)

criteria = context("Please.", [
    said(7, 90, "## Acceptance criteria\n\n%s\n- [ ] AC1. X.\n%s\n"
         % (AC_OPEN, issue_comments.AC_CLOSE))])
check_true("criteria-shown", "AC1. X." in criteria)
check_true("criteria-not-yours", "Not yours" in criteria)

# Our comments are not the discussion: they are shown under what they are, and
# the "Comments" heading counts only the people.
issue_context.fetch = lambda number, cwd=None: {
    "number": 7, "title": "T", "body": "Please.", "comments": [
        said(7, 1, "A real question."),
        said(7, 81, REQUEST + "\n## User request\n\nX."),
        said(7, 90, "## Acceptance criteria\n\n%s\n- [ ] AC1. X.\n%s\n"
             % (AC_OPEN, issue_comments.AC_CLOSE)),
        said(7, 99, "<!-- sclaude:my-feature -->\n| Step | ... |")]}
check_true("context-counts-people-only",
           "#### Comments (1)" in issue_context.render(7))


# The same block for step 2, which adds what was asked during development.
real_fetch = issue_context.issue_comments.fetch
issue_context.issue_comments.fetch = lambda number, cwd=None: {
    "body": "Please.", "comments": [
        said(7, 81, REQUEST + "\n## User request\n\nDrafts.")]}
step2 = issue_context.request(7)
check_true("step2-request-shown", "Drafts." in step2)
check_true("step2-request-edits-by-id", "issues/comments/81" in step2)
issue_context.issue_comments.fetch = lambda number, cwd=None: None
check("step2-request-no-gh", issue_context.request(7), "")
issue_context.issue_comments.fetch = real_fetch


# Links beyond the formal ones. The parent's children are listed with this one
# marked, a blocker comes with its body, and an issue the description points to
# is a link though GitHub does not know it as one.
ISSUES = {
    7: {"number": 7, "title": "Create", "state": "OPEN",
        "url": "https://github.com/o/r/issues/7",
        "body": "A button on the https://github.com/o/r/issues/24 page, see #30;"
                " not https://github.com/x/y/issues/31, nor #7 itself.",
        "parent": {"number": 3}, "comments": [],
        "blockedBy": {"nodes": [{"number": 5, "title": "Base",
                                 "state": "OPEN"}], "totalCount": 1}},
    3: {"number": 3, "title": "Epic", "state": "OPEN", "body": "The goal.",
        "subIssues": {"nodes": [{"number": 7, "title": "Create",
                                 "state": "OPEN"},
                                {"number": 30, "title": "View",
                                 "state": "OPEN"}], "totalCount": 2}},
    5: {"number": 5, "title": "Base", "state": "OPEN",
        "body": "Delivers the table."},
    24: {"number": 24, "title": "Manage page", "state": "OPEN"},
}
real_briefs = issue_context.briefs
issue_context.fetch = lambda number, cwd=None: ISSUES.get(number)
issue_context.briefs = lambda numbers, url, cwd=None, fields=None: [
    ISSUES[n] for n in numbers if n in ISSUES]
linked = issue_context.render(7)
check_true("context-parent-body", "The goal." in linked)
check_true("context-siblings-marked", "#7 Create (open)  \u2190 this issue"
           in linked)
check_true("context-blocker-body", "Delivers the table." in linked)
check_true("context-mention-by-url", "#24 Manage page (open)" in linked)
# Past the cap the open issues are kept and the rest counted.
many = [{"number": n, "title": "I%d" % n, "state": "CLOSED" if n < 5 else "OPEN"}
        for n in range(issue_context.MAX_LINKS + 5)]
cut, kept = issue_context.capped(many)
check("links-capped", len(cut), issue_context.MAX_LINKS + 1)
check("links-kept-matches-rows", len(kept), issue_context.MAX_LINKS)
# gh may send fewer nodes than exist; the count follows totalCount.
check_true("links-count-by-total",
           "7 more" in issue_context.capped(many[:3], total=10, limit=3)[0][-1])
check_true("links-closed-go-first-out", not any(" I3 " in r for r in cut))
check_true("links-count-the-rest", "5 more" in cut[-1])
check("context-mention-skips-shown-and-foreign",
      issue_context.mentions(ISSUES[7], {7, 3, 5, 30}), [24])

# The mentions: case-insensitive repository, nothing GraphQL cannot take.
check("mentions-repo-any-case", issue_context.mentions(
    {"url": "https://github.com/Owner/Repo/issues/7",
     "body": "https://github.com/owner/repo/issues/24 and #20240101123"},
    set()), [24])

# A blocker body is cut before it can overgrow the environment variable.
long_body = issue_context.cut("x" * (issue_context.MAX_BODY + 10), 5)
check_true("blocker-body-cut", len(long_body) < issue_context.MAX_BODY + 200
           and "gh issue view 5" in long_body)

# briefs() against a canned gh: plain -f fields, a null alias dropped, a
# partial `errors` array does not lose the rest.
issue_context.briefs = real_briefs
seen = {}


class Done:
    returncode = 1
    stdout = json.dumps({"data": {"repository": {
        "n24": {"number": 24, "title": "Manage", "state": "OPEN"},
        "n99": None}}, "errors": [{"message": "Could not resolve"}]})


def fake_run(argv, **kw):
    seen["argv"] = argv
    return Done()


real_run = subprocess.run
subprocess.run = fake_run
try:
    got = issue_context.briefs([24, 99], "https://github.com/o/2048/issues/7")
finally:
    subprocess.run = real_run
check("briefs-parsed", [it["number"] for it in got], [24])
check_true("briefs-untyped-fields", "-F" not in seen["argv"]
           and "name=2048" in seen["argv"])
check_true("briefs-asks-each", "n99: issueOrPullRequest(number: 99)"
           in " ".join(seen["argv"]))

# --- nothing edits a description ---------------------------------------------

here = os.path.dirname(os.path.abspath(__file__))
lib = os.path.join(here, "..", "sclaude", "lib")
prompts = os.path.join(here, "..", "sclaude", "prompts")
for folder in (lib, prompts):
    for name in sorted(os.listdir(folder)):
        if not name.endswith((".py", ".sh", ".md")):
            continue
        text = io.open(os.path.join(folder, name), encoding="utf-8").read()
        # `gh issue edit` is still how labels are applied; a body is written
        # with --body or --body-file, and neither may appear beside it.
        check("no-body-edit-%s" % name,
              re.findall(r"gh issue edit[^\n]*--body", text), [])


# --- walking the chain -------------------------------------------------------

def stub(tree):
    """Substitutes fetch with a map of {number: issue}."""
    def fake(number, cwd=None):
        return tree.get(int(number))
    return fake


def issue(number, parent=None, **extra):
    node = {"number": number, "title": "T%s" % number, "state": "OPEN",
            "body": "", "labels": []}
    if parent is not None:
        node["parent"] = {"number": parent, "title": "T%s" % parent,
                          "state": "OPEN"}
    node.update(extra)
    return node


real_fetch = issue_chain.fetch
try:
    # With no parent, a chain of one issue.
    issue_chain.fetch = stub({1: issue(1)})
    check("chain-alone", [i["number"] for i in chain(1)], [1])

    # Three levels in a row.
    issue_chain.fetch = stub({1: issue(1, 2), 2: issue(2, 3), 3: issue(3)})
    check("chain-three", [i["number"] for i in chain(1)], [1, 2, 3])
    check("chain-numbers", chain_numbers(1), "1\n2\n3")

    # A loop A → B → A is broken off rather than spun.
    issue_chain.fetch = stub({1: issue(1, 2), 2: issue(2, 1)})
    check("chain-cycle", [i["number"] for i in chain(1)], [1, 2])

    # A pathological depth is cut off by the limit.
    deep = {n: issue(n, n + 1) for n in range(1, 16)}
    deep[15] = issue(15)
    issue_chain.fetch = stub(deep)
    check("chain-depth", len(chain(1)), MAX_DEPTH)

    # An issue that does not exist ends the chain without an exception.
    issue_chain.fetch = stub({1: issue(1, 99)})
    check("chain-missing-parent", [i["number"] for i in chain(1)], [1])
finally:
    issue_chain.fetch = real_fetch


# --- the shape of the links --------------------------------------------------
#
# gh returns subIssues as an object {"nodes": [...]} rather than a list.
# Iterating such an object as a list gives string keys and silently finds
# nothing — that is how the "Links" section never reached step 1. This case
# guards against it.
wrapped = {"subIssues": {"nodes": [{"number": 2}, {"number": 3}],
                         "totalCount": 2}}
check("nodes-unwraps", [c["number"] for c in nodes(wrapped, "subIssues")], [2, 3])
check("nodes-missing", nodes({}, "subIssues"), [])
check("nodes-empty", nodes({"subIssues": {"nodes": [], "totalCount": 0}},
                          "subIssues"), [])

check("progress-none", progress({}), None)
check("progress-zero",
      progress({"subIssuesSummary": {"completed": 0, "total": 0,
                                     "percentCompleted": 0}}), None)
check("progress-some",
      progress({"subIssuesSummary": {"completed": 9, "total": 10,
                                     "percentCompleted": 90}}),
      "9 of 10 closed (90%)")


# --- the markers --------------------------------------------------------------
#
# Declared once, in issue_comments.py, and imported everywhere else. They used
# to live in github.sh too, which seeded them into a new body; the body is no
# longer seeded, and a shell copy coming back would be a copy nothing checks.
shell = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "sclaude", "lib", "github.sh"),
                encoding="utf-8").read()


github = shell
deploy_sh = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "sclaude", "lib", "deploy.sh"),
                    encoding="utf-8").read()


def shell_const(name):
    """The value of a top-level variable from github.sh."""
    found = re.search(r'^%s="([^"]*)"' % name, shell, re.M)
    return found.group(1) if found else None


for name in ("ISSUE_MARKER", "AC_OPEN", "AC_CLOSE", "STATUS_OPEN"):
    check("markers-no-shell-copy-%s" % name, shell_const(name), None)
check("markers-one-home-context", issue_context.REQUEST, issue_comments.REQUEST)
check("markers-one-home-chain", issue_chain.STATUS, issue_comments.STATUS)
# The rollback marker lives in the shell that writes it and here, where the
# epilogue tells it from our other comments; a drift loses the incident.
rollback_sh = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "sclaude", "lib", "rollback.sh"),
                      encoding="utf-8").read()
check("markers-rollback-agree",
      re.search(r'^ROLLBACK_MARKER="([^"]*)"', rollback_sh, re.M).group(1),
      issue_comments.ROLLBACK)

# The prompts spell two markers out for the model, which writes those comments
# itself. A prompt with a stale spelling makes a comment nothing finds again,
# and the next session posts a second one.
plan_md = io.open(os.path.join(prompts, "plan.md"), encoding="utf-8").read()
status_md = io.open(os.path.join(prompts, "status.md"), encoding="utf-8").read()
check_true("plan-prompt-spells-request-marker", REQUEST in plan_md)
check_true("status-prompt-spells-status-marker", STATUS in status_md)
# Both headings of the one comment are spelled in its template, so the next
# session finds the behaviour section where this one left it.
# Without a pull request the paragraphs about it drop: <pr> is never empty
# (render_prompt fills it with a dash), so they hang on a number of their own.
sys.path.insert(0, lib)
import render_prompt
no_pr = render_prompt.render(status_md, prompts,
                             {"pr": "\u2014", "pr-number": "", "feature": "f",
                              "issue": "1"}, {})
check_true("status-prompt-no-pr-no-commands",
           "gh pr diff" not in no_pr and "gh pr view" not in no_pr)
with_pr = render_prompt.render(status_md, prompts,
                               {"pr": "143", "pr-number": "143", "feature": "f",
                                "issue": "1"}, {})
check_true("status-prompt-names-the-pr", "gh pr diff 143" in with_pr)
check_true("status-prompt-spells-both-sections",
           "## Current status\n\n…text…\n\n## Current behaviour" in status_md)

# A new issue's body mentions none of our markers: nothing is ever spliced into
# it, so there is nothing for a marker to mark.
template = re.search(r"^issue_body\(\) \{.*?^\}", shell, re.M | re.S).group(0)
check_true("template-has-no-markers", "<!-- sclaude:" not in template)

# --- a red preview earns no label -------------------------------------------
#
# The label says "the code is on preview", and a reader takes that as "it is
# there and it works" — status.md words the rule as "preview passed means
# deployed-preview". It used to be applied off the deploy instead: remind_prod
# passed preview_done straight through, so a deploy whose regression came back
# red labelled the whole chain. The fixing session that follows a red run then
# pushes again, and the label is left describing a commit that has gone.
#
# Two halves, and both are needed. The call must not claim the preview, and
# status_outcome must still say the deploy happened — removing the label alone
# would leave the prose saying "nothing was deployed at all", which is a
# different lie for the same event.
red = re.search(r'The preview regression is red', deploy_sh)
red_call = re.search(
    r'run_status "\$slug" "\$issue" "\$pr" "\$\{merged:-\}" 0 0 "\$wt" 1 0\s*\n\s*echo ""\s*\n\s*warn "The preview regression is red',
    deploy_sh)
check_true("red-preview-claims-no-preview", red_call is not None)

# The eighth argument exists to keep the two apart: it reaches the prose and
# never the labels. If it ever reached the label line, the bug is back under a
# new name.
label_line = re.search(r'^\s*\[\[ "\$preview" == "1" \|\| "\$prod" == "1" \]\] && labels="deployed-preview"',
                       github, re.M)
check_true("labels-come-from-preview-only", label_line is not None)
check_true("labels-ignore-the-red-flag",
           "preview_red" not in (label_line.group(0) if label_line else "x"))


def outcome(pr, merged, preview, prod, preview_red="0", prod_red="0"):
    """status_outcome for real, in the shell it is written in."""
    script = (
        'set -o pipefail\n'
        + re.search(r'^status_outcome\(\) \{.*?^\}', github, re.M | re.S).group(0)
        + '\nstatus_outcome "%s" "%s" "%s" "%s" "%s" "%s"\n'
          % (pr, merged, preview, prod, preview_red, prod_red)
    )
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True).stdout.strip()


# The red run: deployed, broken, unmerged. Neither "nothing was deployed" nor a
# sentence claiming a working preview.
red_text = outcome("7", "", "0", "0", "1")
check_true("red-outcome-names-the-deploy", "Preview deployed" in red_text)
check_true("red-outcome-names-the-regression", "red" in red_text)
check_true("red-outcome-does-not-claim-nothing",
           "Nothing was deployed at all" not in red_text)
check_true("red-outcome-offers-no-prod", "no prod deploy" in red_text)

# And the flag changes nothing anywhere else: the same arguments without it are
# the sentence that was always there.
check("unset-flag-is-the-old-sentence",
      outcome("7", "", "0", "0"),
      "Pull request #7 is not merged yet — the merge is mine to do. "
      "Nothing was deployed at all: the work is awaiting merge.")
check_true("green-preview-unchanged",
           "Preview deployed; there was no prod deploy" in outcome("7", "", "1", "0"))
check_true("prod-unchanged",
           "the feature is in production" in outcome("7", "MERGED", "1", "1"))


# --- a red production keeps its label and gains a mark -----------------------
#
# The preview fix above stopped a red run claiming `deployed-preview`, and the
# same bug was left standing for production, where it was worse: the chain was
# labelled "Live in production" at the moment production was known to be broken.
#
# The fix is deliberately not symmetrical. `deployed-prod` stays, because it
# claims only that the code reached production — true whatever the suite then
# found — and what says the deployment is broken is a mark of its own, which
# comes off again when the stage passes.
# The call is anchored by its arguments rather than by the warning beside it:
# the prose moved when production learned to roll itself back, and the invariant
# — a red prod marks the stage and keeps its label — did not.
prod_red_call = re.search(
    r'run_status "\$slug" "\$issue" "\$pr" "\$\{merged:-\}" "\$preview_live" "\$prod_done" "\$wt" 0 1',
    deploy_sh)
check_true("red-prod-marks-the-stage", prod_red_call is not None)
# Not zeroed like the preview one: the label is earned and stays. `deployed-prod`
# claims only that the code reached production, which stays true after a
# rollback; what says production is not serving it is the red mark beside it.
check_true("red-prod-keeps-the-prod-label",
           prod_red_call is not None and '"$prod_done" "$wt" 0 1' in prod_red_call.group(0))
# Every red-prod exit marks the stage — the suite that could not run, the
# red after somebody else deployed on top (nothing rolled back), and the red
# that goes on to a rollback, whether that rollback then works or not.
check("red-prod-marks-on-every-exit",
      len(re.findall(
          r'run_status "\$slug" "\$issue" "\$pr" "\$\{merged:-\}" "\$preview_live" "\$prod_done" "\$wt" 0 1',
          deploy_sh)), 3)

# Both `deployed-*` lines stay driven by preview/prod alone. These pass on a
# revert — they are a guard, not a proof — and exist to catch the "simplification"
# that folds a red flag into the label decision and brings the bug back.
prod_label_line = re.search(
    r'^\s*\[\[ "\$prod" == "1" \]\] && labels="\$\{labels:\+\$labels \}deployed-prod"',
    github, re.M)
check_true("prod-label-comes-from-prod-only", prod_label_line is not None)
check_true("prod-label-ignores-the-red-flag",
           "prod_red" not in (prod_label_line.group(0) if prod_label_line else "x"))

# The ordinary red prod: a green preview behind it, production live and broken.
prod_red_text = outcome("7", "MERGED", "1", "0", "0", "1")
check_true("prod-red-names-the-prod-deploy",
           "prod deployed, but the regression" in prod_red_text)
check_true("prod-red-says-it-is-broken", "live and broken" in prod_red_text)
check_true("prod-red-keeps-the-green-preview",
           "Preview deployed and green" in prod_red_text)
# The branch ordering is the whole of this case: left below the preview ones it
# would come out as "prod postponed", which is the lie being removed.
check_true("prod-red-outranks-the-postponed-branch",
           "postponed" not in prod_red_text)

# The same event with no preview of our own this run — resumed after the merge,
# or a preview skipped because that tree is already up there.
lone_prod_red = outcome("7", "MERGED", "0", "0", "0", "1")
check_true("lone-prod-red-names-the-deploy",
           "Prod deployed, but the regression" in lone_prod_red)
check_true("lone-prod-red-invents-no-preview", "Preview" not in lone_prod_red)
check_true("lone-prod-red-does-not-claim-nothing",
           "Neither preview nor prod was deployed" not in lone_prod_red)

# A real prod deploy still outranks a stray flag, and the green path is untouched.
check_true("green-prod-unchanged",
           "the feature is in production" in outcome("7", "MERGED", "1", "1"))
check_true("a-green-prod-outranks-the-red-flag",
           "the feature is in production" in outcome("7", "MERGED", "1", "1", "0", "1"))


# --- the marks come off again ------------------------------------------------
#
# This is the only label in the repository that is ever removed, and the reason
# it may be is that nobody writes it by hand: the script sets it from a suite
# result and clears it from the same. `deployed-*` stay add-only, and the count
# below is what keeps that narrow — a second `--remove-label` appearing anywhere
# means the exception has started to spread.
regression_sh = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "sclaude", "lib", "regression.sh"),
                        encoding="utf-8").read()

check("remove-label-used-once", github.count("--remove-label"), 1)
check_true("clear-helper-exists",
           re.search(r'^clear_regression_label\(\) \{', github, re.M) is not None)
# Named in one place, so a mark cannot be set under one spelling and cleared
# under another — which would mean never cleared at all.
check_true("label-names-have-one-home",
           re.search(r'^regression_red_label\(\) \{', github, re.M) is not None)
check("preview-mark-name-not-duplicated",
      github.count("'preview-regression-red'"), 1)
check("prod-mark-name-not-duplicated",
      github.count("'prod-regression-red'"), 1)

# Cleared on the green run, inside the branch that records the pass — not at the
# end of the cycle, where it would lag the truth by however long the fix took.
green_clear = re.search(
    r'state_set "\$state" "regression\.\$stage\.attempts" 0\n\s*regression_clear_mark "\$wt" "\$stage"',
    regression_sh)
check_true("mark-cleared-on-green", green_clear is not None)
check_true("clear-walks-the-chain",
           re.search(r'regression_clear_mark\(\)(?:.|\n)*?issue_chain\.py', regression_sh)
           is not None)
check_true("clear-skips-the-local-stage",
           re.search(r'\[\[ "\$stage" == "preview" \|\| "\$stage" == "prod" \]\] \|\| return 0',
                     regression_sh) is not None)


# --- the label follows what is true, not what happened today -----------------
#
# `deployed-preview` used to be read off preview_done, which means "we shipped
# one in this run". That was the same thing until the red path stopped claiming
# the label, and then it was not: a red run, a fixing session that commits
# nothing because the cause was outside the branch, and a redeploy by hand leave
# deploy_unchanged true and preview_done 0 for ever after — so a green preview
# would never be labelled at all. The label is read from the two things it
# names instead.
check_true("preview-label-is-not-preview-done",
           '"$preview_done" 0 "$wt"' not in deploy_sh
           and '"$preview_done" "$prod_done" "$wt"' not in deploy_sh)
check_true("preview-live-declared",
           re.search(r'^\s*local preview_live=0', deploy_sh, re.M) is not None)
check_true("preview-live-set-on-green",
           re.search(r'if regression_gate "\$wt" "\$slug" preview; then\n\s*preview_live=1',
                     deploy_sh) is not None)
# The skipped deploy is the case that was losing the label: the tree is on
# hosting, so the only remaining question is what the suite said. The deploy is
# now skipped only when the suite said green, so the skip itself sets it.
check_true("preview-live-set-when-the-deploy-is-skipped",
           re.search(r'deploy_unchanged "\$wt" preview \\\n\s*&& '
                     r'\[\[ "\$\(regression_status "\$wt" preview\)" == "passed" \]\]; then'
                     r'(?:.|\n)*?preview_live=1\n\s*elif',
                     deploy_sh) is not None)


if failures:
    for name, want, got in failures:
        print("FAIL %s\n  expected: %r\n  got:      %r" % (name, want, got))
    print("\n%d check(s) failed." % len(failures))
    sys.exit(1)
print("All checks passed.")
