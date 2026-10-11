#!/usr/bin/env python3
#
# A test bench for returning to step 4: what counts as a new comment and what
# does not.
#
# The main thing here is what the count runs from. Step 4's session lives for
# hours and reads the PR all that time, so a comment that arrived mid-work has
# already been dealt with. The count runs from the transcript's last entry rather
# than from the step's start; the checks below hold precisely that boundary.
#
# gh is not called: its answers are substituted, as the bench needs the data
# parsed rather than the network.
#
# Run it with: python3 tests/review-news.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
import pr_context

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def fake_gh(rollup=(), comments=(), inline=()):
    """Substitutes gh_json: pr answers with a snapshot, api with the inline
    list."""
    def gh_json(args, cwd=None):
        if args and args[0] == "pr":
            return {"statusCheckRollup": list(rollup),
                    "comments": list(comments)}
        return list(inline)
    return gh_json


GREEN = [{"name": "checks", "state": "SUCCESS",
          "startedAt": "2026-09-06T10:00:00Z",
          "completedAt": "2026-09-06T10:05:00Z"}]
RED = [{"name": "checks", "state": "FAILURE",
        "startedAt": "2026-09-06T10:00:00Z",
        "completedAt": "2026-09-06T10:02:00Z"}]

SINCE = "2026-09-06T10:00:00+00:00"
OLD = "2026-09-06T09:00:00Z"   # before the mark — the session saw this
NEW = "2026-09-06T11:00:00Z"   # after the mark — it did not


def discussion(created, body="a comment", login="ilia"):
    return {"author": {"login": login}, "body": body, "createdAt": created}


def inline_comment(created, body="a comment", login="claude[bot]"):
    return {"user": {"login": login}, "body": body, "created_at": created,
            "path": "app/page.tsx", "line": 10}


def main():
    original = pr_context.gh_json
    try:
        # Silence when there is nothing new. This is the main case: a return to
        # step 4 usually happens with no changes on the PR's side, and there is
        # no reason to retell the session its own context.
        pr_context.gh_json = fake_gh(GREEN, [], [])
        check("nothing-new", pr_context.render_new(".", 89, "o/r", SINCE), "")

        # The session has already dealt with a comment older than the mark.
        pr_context.gh_json = fake_gh(GREEN, [discussion(OLD)], [])
        check("older-discussion-ignored",
              pr_context.render_new(".", 89, "o/r", SINCE), "")
        pr_context.gh_json = fake_gh(GREEN, [], [inline_comment(OLD)])
        check("older-inline-ignored",
              pr_context.render_new(".", 89, "o/r", SINCE), "")

        # Newer than the mark — it reaches the prompt, through both streams.
        pr_context.gh_json = fake_gh(GREEN, [discussion(NEW, "fix this")], [])
        got = pr_context.render_new(".", 89, "o/r", SINCE)
        check("newer-discussion-shown", "fix this" in got, True)
        pr_context.gh_json = fake_gh(GREEN, [], [inline_comment(NEW, "and this")])
        got = pr_context.render_new(".", 89, "o/r", SINCE)
        check("newer-inline-shown", "and this" in got, True)
        check("newer-inline-names-file", "app/page.tsx:10" in got, True)

        # A mix: the old is filtered out and the new stays — in one answer.
        pr_context.gh_json = fake_gh(GREEN, [discussion(OLD, "the old one"),
                                             discussion(NEW, "the new one")], [])
        got = pr_context.render_new(".", 89, "o/r", SINCE)
        check("mixed-keeps-new", "the new one" in got, True)
        check("mixed-drops-old", "the old one" in got, False)

        # An empty body is not a comment: that happens with a comment made of
        # images alone.
        pr_context.gh_json = fake_gh(GREEN, [discussion(NEW, "   ")], [])
        check("empty-body-ignored",
              pr_context.render_new(".", 89, "o/r", SINCE), "")

        # A failing check is a reason to come back too, even with no
        # comments.
        pr_context.gh_json = fake_gh(RED, [], [])
        got = pr_context.render_new(".", 89, "o/r", SINCE)
        check("red-alone-reported", "checks are red" in got, True)

        # Together with a comment — as one summary rather than two.
        pr_context.gh_json = fake_gh(RED, [discussion(NEW, "fix it")], [])
        got = pr_context.render_new(".", 89, "o/r", SINCE)
        check("red-with-comment", "fix it" in got and "red as well" in got, True)

        # The findings check red only for threads resolved by hand or kept by
        # the person is nothing for a session (one was woken for it); red
        # with something behind it is still news.
        findings = [{"name": pr_context.FINDINGS_CHECK, "state": "FAILURE",
                     "startedAt": "2026-09-06T10:00:00Z",
                     "completedAt": "2026-09-06T10:02:00Z"}]
        explained = pr_context.findings_red_explained
        try:
            pr_context.gh_json = fake_gh(findings, [], [])
            pr_context.findings_red_explained = lambda *a: True
            check("explained-findings-silent",
                  pr_context.render_new(".", 89, "o/r", SINCE), "")
            pr_context.gh_json = fake_gh(findings + RED, [], [])
            got = pr_context.render_new(".", 89, "o/r", SINCE)
            check("explained-findings-other-red-kept",
                  "`checks`" in got and pr_context.FINDINGS_CHECK not in got, True)
            pr_context.gh_json = fake_gh(findings, [], [])
            pr_context.findings_red_explained = lambda *a: False
            got = pr_context.render_new(".", 89, "o/r", SINCE)
            check("unexplained-findings-reported", "checks are red" in got, True)
        finally:
            pr_context.findings_red_explained = explained

        # Silence on trouble: the snapshot is a side benefit and must not bring
        # a step down. Neither without gh nor without a parsable mark.
        pr_context.gh_json = lambda *a, **k: None
        check("gh-down-silent", pr_context.render_new(".", 89, "o/r", SINCE), "")
        pr_context.gh_json = fake_gh(GREEN, [discussion(NEW)], [])
        check("bad-mark-silent",
              pr_context.render_new(".", 89, "o/r", "not a date"), "")
        check("no-pr-silent", pr_context.render_new(".", "", "o/r", SINCE), "")

        # A naive mark is local time: `date -Iseconds` writes an offset, but the
        # state also survives being edited by hand.
        check("naive-mark-parsed",
              pr_context.parse_ts("2026-09-06T10:00:00") is not None, True)

        total = 18
        for name, want, got in failures:
            print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
        print("%d/%d passed" % (total - len(failures), total))
        return 1 if failures else 0
    finally:
        pr_context.gh_json = original


if __name__ == "__main__":
    sys.exit(main())
