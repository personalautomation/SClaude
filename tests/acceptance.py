#!/usr/bin/env python3
#
# A test bench for the acceptance criteria: posting them on an issue as a
# comment, and reading them back out of it — or out of the body of an issue
# from before they moved to a comment.
#
# The parsing is what everything downstream rests on: the hook refuses a plan
# by it, the orchestrator copies the plan's list into the issue by it, step 2 is
# told what to build from it, and the merge question shows QA's ticks by it. The failures worth guarding against are the quiet ones — a section
# that reads as empty when it has content, or as having content when it holds
# the template's placeholder — because neither raises anything. The step simply
# runs with no criteria, and nothing says so.
#
# Run it with: python3 tests/acceptance.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
from acceptance import (AC_CLOSE, AC_OPEN, NOTE, PLACEHOLDER, merge_section,
                        parse, plan_content, plan_section, plan_verdict,
                        render, section, status, sync, unticked, extend,
                        tick_all)
import issue_comments  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def body(inner, before="## User request\n\nWhatever.\n\n"
                       "<!-- sclaude:user-request -->\n\n"
                       "## Acceptance criteria\n\n"):
    return "%s%s\n%s\n%s\n" % (before, AC_OPEN, inner, AC_CLOSE)


# --- the section itself ------------------------------------------------------

THREE = ("- [ ] AC1. A guest opening /events sees only published ones.\n"
         "- [ ] AC2. A draft opens by direct link for its author.\n"
         "- [ ] AC3. An empty list shows the invitation to create one.")

check("section-reads-between-markers", section(body(THREE)), THREE)
check("section-missing-is-empty", section("no markers here at all"), "")
check("section-empty-body", section(""), "")

# A body with an opening marker and no closing one: the pair was broken by a
# hand edit. We read nothing rather than reading to the end — everything below
# the break belongs to somebody else, and handing it to a step as a requirement
# is worse than handing it nothing.
torn = "## Acceptance criteria\n\n%s\n- [ ] AC1. Something.\n\nA note I added.\n" % AC_OPEN
check("torn-pair-reads-nothing", section(torn), "")

# The closing marker before the opening one — the body was reordered by hand.
# `find` from the opening marker never reaches it, so the pair is incomplete.
check("reversed-pair-reads-nothing",
      section("%s\n- [ ] AC1. X.\n%s\n" % (AC_CLOSE, AC_OPEN)), "")


# --- parsing the criteria ----------------------------------------------------

got = parse(body(THREE))
check("parse-count", len(got), 3)
check("parse-first-id", got[0][0], "AC1")
check("parse-first-text", got[0][1],
      "A guest opening /events sees only published ones.")
check("parse-first-undone", got[0][2], False)
check("parse-third-id", got[2][0], "AC3")

# The template's placeholder is not a criterion. This is the case that would
# otherwise pass silently all the way into a pull request: the section exists,
# it has text, and the text is an instruction to fill it in.
check("placeholder-is-not-a-criterion", parse(body(PLACEHOLDER)), [])

# A ticked box still parses — whether QA has confirmed a criterion is not a
# reason to hide it from a step that has to know what the feature must do.
ticked = parse(body("- [x] AC1. Done and checked.\n- [ ] AC2. Not yet."))
check("ticked-count", len(ticked), 2)
check("ticked-first-done", ticked[0][2], True)
check("ticked-second-undone", ticked[1][2], False)
check("ticked-uppercase", parse(body("- [X] AC1. Done."))[0][2], True)

# Prose around the list is ignored rather than rejected: step 1 may leave a
# sentence of context above the criteria, and a criterion is recognised by its
# shape, not by being the only thing in the section.
mixed = parse(body("These are about the public list only.\n\n"
                   "- [ ] AC1. A guest sees published ones.\n"
                   "\n"
                   "Drafts are covered by #72.\n"))
check("prose-ignored", len(mixed), 1)
check("prose-keeps-the-criterion", mixed[0][0], "AC1")

# The identifier is required. A plain task list with no ACn is somebody's
# checklist, not our criteria, and reading it as criteria would put arbitrary
# text in front of step 2 as a requirement.
check("unnumbered-item-ignored", parse(body("- [ ] Just a task.")), [])

# Indentation and a missing full stop after the identifier: both occur in
# hand-edited lists, and neither changes what the line means.
loose = parse(body("  - [ ] AC1 No full stop after the identifier.\n"
                   "* [ ] AC2. A star instead of a hyphen."))
check("indented-parses", loose[0][0], "AC1")
check("indented-text", loose[0][1], "No full stop after the identifier.")
# A star is not matched: the list marker is a hyphen in everything we write, and
# widening the pattern to bullets in general would start catching ordinary
# prose. Recorded as a decision rather than an omission.
check("star-bullet-ignored", len(loose), 1)

# Two digits, because a feature with ten criteria is not a reason to lose the
# tenth.
many = parse(body("- [ ] AC9. Nine.\n- [ ] AC10. Ten."))
check("two-digit-ids", [c[0] for c in many], ["AC9", "AC10"])

# A criterion with an identifier and no text is not a criterion. It happens when
# a line is half-written, and an empty requirement in front of step 2 is worse
# than one criterion fewer.
check("empty-text-ignored", parse(body("- [ ] AC1.")), [])


# --- the rendered block ------------------------------------------------------
#
# render() calls gh, so the fetch is stubbed out. What is under test is the
# shape of what reaches a prompt, not the network.

import acceptance  # noqa: E402

URL = "https://github.com/o/r/issues/71#issuecomment-%s"


def issue(body_text="", *comments):
    """An issue as fetch() returns it: a body and (id, text) comments."""
    return {"body": body_text,
            "comments": [{"body": text, "url": URL % cid}
                         for cid, text in comments]}


def comment(inner):
    """Our criteria comment, holding `inner` between the markers."""
    return merge_section("", inner.splitlines() or [""])


def stub(value):
    acceptance.fetch = lambda number, cwd=None: value


# Read from our comment.
stub(issue("A human wrote this.", (5, "Looks good."), (6, comment(THREE))))

plain = render("71")
check_true("render-has-heading", "#### Acceptance criteria" in plain)
check_true("render-names-the-issue", "issue #71" in plain)
check_true("render-plain-is-not-a-checklist", "- [ ]" not in plain)
check_true("render-plain-has-the-id", "**AC1.**" in plain)
check_true("render-has-all-three", plain.count("AC") >= 3)

# The ticks never reach a prompt: they are QA's, in the issue, and a list with
# boxes pasted into the pull request is a second place for a tick to land.
stub(issue("", (6, comment("- [x] AC1. Confirmed.\n- [ ] AC2. Not yet."))))
ticked_render = render("71")
check_true("render-no-boxes-even-when-ticked",
           "[x]" not in ticked_render and "[ ]" not in ticked_render)
check_true("render-keeps-both", "**AC1.**" in ticked_render
           and "**AC2.**" in ticked_render)

# Nothing to show means no block at all, not a heading over emptiness: the
# prompt drops an empty block's line entirely, and a heading with nothing under
# it is worse than no heading.
stub(issue(body(PLACEHOLDER)))
check("render-placeholder-is-empty", render("71"), "")

stub(issue("A human wrote this.", (5, "- [ ] AC1. Somebody's remark.")))
check("render-no-section-is-empty", render("71"), "")

# An issue from before the move: the criteria are in its body, and they are
# still read from there.
stub(issue(body(THREE)))
check_true("render-reads-an-old-body", "**AC3.**" in render("71"))

# Our comment wins over an old body: it is the later of the two, written when
# the body was no longer written to.
stub(issue(body("- [ ] AC1. The old wording."),
           (6, comment("- [ ] AC1. The comment's wording."))))
check_true("render-comment-beats-body", "comment's wording" in render("71"))

# gh could not answer at all. Best-effort like every other block: empty output,
# and the prompt keeps what it says without it.
stub(None)
check("render-no-gh-is-empty", render("71"), "")



# --- the plan's section ------------------------------------------------------

PLAN = ("# Events list\n\n"
        "## Acceptance criteria\n\n"
        "- [ ] AC1. A guest sees only published events.\n"
        "- [ ] AC2. A draft 404s for anyone but its author.\n\n"
        "## How\n\n"
        "- [ ] AC9. Not a criterion: it is under another heading.\n")

parse_plan = plan_content(PLAN)
check("plan-section-stops-at-next-heading", len(parse_plan), 2)
check("plan-section-first-line", parse_plan[0],
      "- [ ] AC1. A guest sees only published events.")
check("plan-verdict-criteria", plan_verdict(PLAN), "criteria")

# A deeper heading inside the section belongs to it; a heading of the same
# level ends it.
nested = ("## Acceptance criteria\n\n### Public\n\n- [ ] AC1. One.\n\n"
          "### Drafts\n\n- [ ] AC2. Two.\n\n## Next\n")
check("plan-section-keeps-subheadings",
      plan_content(nested), ["- [ ] AC1. One.", "- [ ] AC2. Two."])

# The heading at any of the top three levels, with or without a colon.
check("plan-heading-level-three",
      plan_verdict("# T\n\n### Acceptance criteria\n\n- [ ] AC1. X.\n"), "criteria")
check("plan-heading-level-one",
      plan_verdict("# Acceptance criteria\n\n- [ ] AC1. X.\n"), "criteria")
check("plan-heading-colon",
      plan_verdict("## Acceptance criteria:\n\n- [ ] AC1. X.\n"), "criteria")
check("plan-heading-case", plan_verdict("## acceptance Criteria\n- [ ] AC1. X.\n"),
      "criteria")
# Under a `#` heading the section still ends at the next `##`: the plan's
# implementation is not part of its criteria.
check("plan-level-one-ends-at-two",
      plan_content("# Acceptance criteria\n\n- [ ] AC1. X.\n\n## How\n\n- [ ] AC9. Y.\n"),
      ["- [ ] AC1. X."])

# The plan is a model's prose, and any list shape with an identifier counts.
# Each comes out in the issue's one shape.
for name, line in (("star", "* [ ] AC1. X."), ("plus", "+ AC1. X."),
                   ("no-box", "- AC1. X."), ("numbered", "1. AC1. X."),
                   ("numbered-paren", "1) [ ] AC1: X."), ("bold-id", "- **AC1.** X."),
                   ("ticked", "- [x] AC1. X.")):
    check("plan-shape-%s" % name,
          plan_content("## Acceptance criteria\n\n%s\n" % line), ["- [ ] AC1. X."])
# But prose that merely mentions an identifier is not a criterion.
check("plan-prose-mention-is-not-a-criterion",
      plan_verdict("## Acceptance criteria\n\nAC1 is covered below.\n"), "empty")

# No heading and an empty heading are told apart: the refusal for each says a
# different thing.
check("plan-no-heading-is-missing",
      plan_verdict("## Plan\n\n- [ ] AC1. Somewhere else.\n"), "missing")
check("plan-empty-heading-is-empty",
      plan_verdict("## Acceptance criteria\n\n## Plan\n\n- [ ] AC1. Below.\n"),
      "empty")
check("plan-placeholder-is-empty",
      plan_verdict("## Acceptance criteria\n\n- [ ] AC1. %s\n" % PLACEHOLDER),
      "empty")
check("plan-empty-criterion-is-empty",
      plan_verdict("## Acceptance criteria\n\n- [ ] AC1.\n"), "empty")
check("plan-empty-text-is-missing", plan_verdict(""), "missing")

# Fenced text before the section is a quotation: a heading inside one is not
# where the section starts. Inside the section a fence is part of it, and a
# heading within the fence does not end it.
fenced_heading = ("```\n## Acceptance criteria\n- [ ] AC1. Quoted.\n```\n")
check("plan-fenced-heading-ignored", plan_verdict(fenced_heading), "missing")
fenced_end = ("## Acceptance criteria\n\n```md\n## Not an end\n```\n\n"
              "- [ ] AC1. After the fence.\n")
check("plan-fence-does-not-end-section", plan_verdict(fenced_end), "criteria")
# The prompt shows the no-change line in a fence; a model copying the example
# copies the fence too.
check("plan-fenced-none-declared",
      plan_verdict("## Acceptance criteria\n\n```\nNo observable change: rename.\n```\n"),
      "none-declared")

# The honest alternative: a refactor, nothing a person could check.
NONE = "## Acceptance criteria\n\nNo observable change: a refactor of the loader.\n"
check("plan-none-declared", plan_verdict(NONE), "none-declared")
check("plan-none-declared-bold",
      plan_verdict("## Acceptance criteria\n\n**No observable change:** refactor.\n"),
      "none-declared")
check("plan-none-content", plan_content(NONE),
      ["No observable change: a refactor of the loader."])
# Without a reason it is the placeholder again, in other words.
check("plan-none-needs-a-reason",
      plan_verdict("## Acceptance criteria\n\nNo observable change:\n"), "empty")
# A criterion beside it wins: there is something to check after all.
check("plan-criteria-beat-none",
      plan_verdict(NONE + "- [ ] AC1. But this.\n"), "criteria")

check("plan-section-text", plan_section(NONE),
      "No observable change: a refactor of the loader.")
check("plan-section-none", plan_section("## How\n"), None)


# --- the comment ----------------------------------------------------------------

LINES = ["- [ ] AC1. One.", "- [ ] AC2. Two."]

# A new comment: a heading, the list between the markers, and a note saying
# what it is to whoever opens the issue.
fresh = merge_section("", LINES)
check_true("new-comment-has-heading", fresh.startswith("## Acceptance criteria\n"))
check("new-comment-reads-back", [c[0] for c in parse(fresh)], ["AC1", "AC2"])
check_true("new-comment-ends-with-note", fresh.endswith(NOTE))
check_true("new-comment-is-ours", issue_comments.is_ours(fresh))

# Our comment emptied by hand, with a line QA added below the list: only the
# span between the markers changes.
emptied = fresh.replace("- [ ] AC1. One.\n- [ ] AC2. Two.", "") + "QA: later.\n"
refilled = merge_section(emptied, LINES)
check("merge-replaces-between-markers", parse(refilled)[1][0], "AC2")
check("merge-keeps-before",
      refilled[:refilled.index(AC_OPEN)], emptied[:emptied.index(AC_OPEN)])
check("merge-keeps-after",
      refilled[refilled.index(AC_CLOSE):], emptied[emptied.index(AC_CLOSE):])
check("merge-idempotent", merge_section(refilled, LINES), refilled)

# A broken pair is left alone either way round.
check("merge-torn-open", merge_section("x\n%s\n- [ ] AC1. A.\n" % AC_OPEN, LINES), None)
check("merge-torn-close", merge_section("x\n%s\n" % AC_CLOSE, LINES), None)


# --- sync and status, with gh stubbed ----------------------------------------
#
# The one property above all: the description is never written. There is no
# stub for writing it, and none is needed — sync has no way to.

posted, edited = [], []
acceptance.issue_comments.post = \
    lambda number, text, cwd=None: posted.append(text) or True
acceptance.issue_comments.edit = \
    lambda cid, text, cwd=None: edited.append((cid, text)) or True

human = "Please add a drafts view.\n\nThanks!"

# A body a human wrote: the criteria are posted as a comment of their own.
stub(issue(human, (5, "Sounds good.")))
check("sync-human-body-written", sync("71", PLAN), ("written", []))
check("sync-posted-one", len(posted), 1)
check("sync-posted-criteria", len(parse(posted[-1])), 2)

# The body the old template seeded, with the placeholder in it: a comment too,
# and the body stays as it was — placeholder and all.
stub(issue(body(PLACEHOLDER)))
check("sync-old-placeholder-posts", sync("71", PLAN)[0], "written")
check("sync-old-placeholder-posted", len(posted), 2)

# Our comment, emptied: rewritten in place by its id rather than posted again.
stub(issue(human, (9, emptied)))
check("sync-empty-comment-written", sync("71", PLAN)[0], "written")
check("sync-empty-comment-edited-by-id", edited[-1][0], "9")
check("sync-empty-comment-not-reposted", len(posted), 2)

# A filled list is the issue's, and it is never written over. The same list,
# ticks and all, is "unchanged"; a different one is reported.
same = comment("- [x] AC1. A guest sees only published events.\n"
               "- [ ] AC2. A draft 404s for anyone but its author.")
stub(issue(human, (6, same)))
count = (len(posted), len(edited))
check("sync-same-list-unchanged", sync("71", PLAN), ("unchanged", []))

# The human reworded AC2 and added AC5 in GitHub; QA left a note under AC1. A
# replan whose plan still has the old list must not erase any of it.
reworded = comment("- [x] AC1. A guest sees only published events.\n"
                   "  QA: checked on staging.\n"
                   "- [ ] AC2. A draft 404s for everyone but its author and admins.\n"
                   "- [ ] AC5. Added in GitHub.")
stub(issue(human, (6, reworded)))
word, details = sync("71", PLAN)
check("sync-differs", word, "differs")
check("sync-differs-details", details,
      ["AC2 reads differently", "AC5 is only in the issue"])
check("sync-differs-writes-nothing", (len(posted), len(edited)), count)

# An old issue with a filled list in its body is compared the same way, and
# nothing is posted beside it.
stub(issue(body("- [ ] AC1. A guest sees only published events.\n"
                "- [ ] AC2. A draft 404s for everyone.")))
check("sync-old-body-differs", sync("71", PLAN)[0], "differs")
check("sync-old-body-writes-nothing", (len(posted), len(edited)), count)

stub(issue(human, (6, comment("- [ ] AC1. Something."))))
check("sync-none-declared-vs-list", sync("71", NONE)[0], "differs")
stub(issue(human, (6, comment("No observable change: a refactor of the loader."))))
check("sync-none-declared-same", sync("71", NONE)[0], "unchanged")

# A plan with nothing to copy leaves the issue as it is.
stub(issue(human))
check("sync-nothing", sync("71", "## Plan\n")[0], "nothing")
check("sync-nothing-writes-nothing", (len(posted), len(edited)), count)

stub(None)
check("sync-unreadable", sync("71", PLAN)[0], "unreadable")

# Our comment with its pair broken by a hand edit.
stub(issue(human, (6, "## Acceptance criteria\n\n%s\n" % AC_OPEN)))
check("sync-torn", sync("71", PLAN)[0], "torn")
check("sync-torn-writes-nothing", (len(posted), len(edited)), count)

# A human wrote a list under a heading of the same name, without our markers.
# A second list beside it would leave QA two called the same thing.
stub(issue("Please.\n\n## Acceptance criteria\n\n- works\n"))
check("sync-own-heading", sync("71", PLAN)[0], "own-heading")
check("sync-own-heading-writes-nothing", (len(posted), len(edited)), count)

stub(issue(human))
acceptance.issue_comments.post = lambda number, text, cwd=None: False
check("sync-refused", sync("71", PLAN)[0], "refused")

stub(issue(human, (6, comment("- [x] AC1. Confirmed.\n- [ ] AC2. Not yet.\n"
                               "- [ ] AC3. Nor this."))))
check("status-lines", status("71"),
      "✓ AC1. Confirmed.\n☐ AC2. Not yet.\n☐ AC3. Nor this.")
check("unticked-ids", unticked("71"), "AC2, AC3")
stub(issue(human, (6, comment("- [x] AC1. Confirmed."))))
check("unticked-none", unticked("71"), "")
stub(None)
check("status-no-gh", status("71"), "")
check("unticked-no-gh", unticked("71"), "")


# --- tick_all: QA accepted from sclaude ---------------------------------------
#
# Only the boxes change: the wording and a note QA left stay.
edited = []
acceptance.issue_comments.edit = \
    lambda cid, text, cwd=None: edited.append((cid, text)) or True
stub(issue(human, (6, comment("- [x] AC1. Confirmed.\n  QA: a note.\n"
                               "- [ ] AC2. Not yet."))))
check("tick-word", tick_all("71"), "ticked")
check("tick-edits-our-comment", edited[-1][0], "6")
check("tick-all-ticked", [d for _, _, d in parse(edited[-1][1])], [True, True])
check_true("tick-keeps-the-note", "QA: a note." in edited[-1][1])
check_true("tick-keeps-the-wording", "AC2. Not yet." in edited[-1][1])
stub(issue(human, (6, comment("- [x] AC1. Confirmed."))))
check("tick-already", tick_all("71"), "already")
stub(issue(human))
check("tick-nothing", tick_all("71"), "nothing")
stub(issue(body("- [ ] AC1. In the old body.")))
check("tick-never-writes-a-body", tick_all("71"), "body")
stub(None)
check("tick-no-gh", tick_all("71"), "unreadable")
stub(issue(human, (6, comment("- [ ] AC1. Not yet."))))
acceptance.issue_comments.edit = lambda cid, text, cwd=None: False
check("tick-refused", tick_all("71"), "refused")

# --- extend: criteria step 2 added, appended after the session ----------------
#
# Only additions are written. What the issue already holds — the wording, the
# ticks, a note QA left — stays exactly as it is.

posted, edited = [], []
acceptance.issue_comments.post = \
    lambda number, text, cwd=None: posted.append(text) or True
acceptance.issue_comments.edit = \
    lambda cid, text, cwd=None: edited.append((cid, text)) or True

GROWN = PLAN.replace(
    "- [ ] AC2. A draft 404s for anyone but its author.\n",
    "- [ ] AC2. A draft 404s for anyone but its author.\n"
    "- [ ] AC3. A shared event never asks to confirm participants.\n")

ticked = comment("- [x] AC1. A guest sees only published events.\n"
                 "  QA: checked on staging.\n"
                 "- [ ] AC2. A draft 404s for anyone but its author.")
stub(issue(human, (6, ticked)))
word, details = extend("71", GROWN)
check("extend-word", word, "extended")
check("extend-details", details, ["AC3 added"])
check("extend-edits-in-place", edited[-1][0], "6")
check("extend-posts-nothing", posted, [])
grown = parse(edited[-1][1])
check("extend-appends-last", [c for c, _, _ in grown], ["AC1", "AC2", "AC3"])
check("extend-keeps-tick", grown[0][2], True)
check("extend-new-unticked", grown[2][2], False)
check_true("extend-keeps-qa-note", "QA: checked on staging." in edited[-1][1])

# Nothing new: nothing written.
stub(issue(human, (6, ticked)))
check("extend-same-unchanged", extend("71", PLAN), ("unchanged", []))
check("extend-same-writes-nothing", len(edited), 1)

# A reworded criterion is reported, never rewritten — and a new one still lands.
reworded2 = comment("- [ ] AC1. A guest sees only published events.\n"
                    "- [ ] AC2. A draft 404s for everyone but admins.")
stub(issue(human, (6, reworded2)))
word, details = extend("71", GROWN)
check("extend-reworded-word", word, "extended")
check("extend-reworded-details", details, ["AC3 added", "AC2 reads differently"])
check_true("extend-reworded-kept", "everyone but admins" in edited[-1][1])

# An empty issue list is filled the way sync() fills it.
stub(issue(human))
check("extend-empty-writes", extend("71", GROWN)[0], "written")
check("extend-empty-posted", len(parse(posted[-1])), 3)

# Criteria in an old description: never written, the additions reported.
stub(issue(body("- [ ] AC1. A guest sees only published events.\n"
                "- [ ] AC2. A draft 404s for anyone but its author.")))
count = len(edited)
check("extend-old-body", extend("71", GROWN), ("differs", ["AC3 is only in the plan"]))
check("extend-old-body-writes-nothing", len(edited), count)

# A criterion added in GitHub and absent from the plan is not reported.
stub(issue(human, (6, comment("- [ ] AC1. A guest sees only published events.\n"
                               "- [ ] AC2. A draft 404s for anyone but its author.\n"
                               "- [ ] AC7. Added in GitHub."))))
check("extend-issue-only-quiet", extend("71", PLAN), ("unchanged", []))

stub(None)
check("extend-unreadable", extend("71", GROWN)[0], "unreadable")


# --- the comment id ------------------------------------------------------------

check("comment-id-from-url", issue_comments.comment_id({"url": URL % 42}), "42")
check("comment-id-missing", issue_comments.comment_id({"url": ""}), None)

if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
