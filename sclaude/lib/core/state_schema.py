# Every field sclaude keeps in its JSON records, and what it means.
#
# Three records are read and written through state_get / state_set (state.sh)
# and state_file.py:
#
#   feature   .sclaude/local/feature/state.json in a feature's worktree:
#             where the feature's cycle stands, from the plan to the clean-up
#   epilogue  the epilogue's own record (epilogue_state in state.sh), which
#             outlives the worktree: the status the epilogue writes into the
#             issue, and the session that writes it
#   watch     ~/.claude/sclaude/watch/<slug>.json (watch_start in watch.sh):
#             what bin/sclaude-watch needs to follow QA from a timer, with no
#             project in reach
#
# A path is dotted. A part in angle brackets stands for any one name:
#
#   <step>   plan, code, pr, review
#   <stage>  local, preview, prod
#   <key>    a friction review's key (the step or stage it reviewed, `unread-N`,
#            `fix-<stage>-<n>`)
#   <field>  any field of the node, for code that walks them
#
# tests/state-file.py reads every state_get and state_set in the code and fails
# on a path that is not here, so a mistyped field — which reads as "not set",
# silently — is caught by the suite, and a field added to the code is added
# here in the same change.

FEATURE, EPILOGUE, WATCH = "feature", "epilogue", "watch"

FIELDS = [
    # --- the feature itself ----------------------------------------------------
    ("feature", (FEATURE, EPILOGUE, WATCH), "the feature's slug"),
    ("branch", (FEATURE,), "its git branch"),
    ("worktree", (FEATURE, WATCH), "its worktree; the watch sends the timer's messages to its topic"),
    ("issue", (FEATURE, EPILOGUE), "the GitHub issue's number"),
    ("pr", (FEATURE, EPILOGUE, WATCH), "the pull request's number, once step 3 opened it"),
    ("pr_setup", (FEATURE,), "the pull request whose milestone and assignee were set (done once per PR)"),
    ("created", (FEATURE,), "the day `sclaude new` started it"),
    ("step", (FEATURE,), "the step it stands at: plan, code, pr, review, done"),
    ("cleaned", (FEATURE,), "true once the clean-up began; the summary is written before the tree goes"),
    ("no_change", (FEATURE,), "step 2 ended with nothing to change in the code"),
    ("no_change_product", (FEATURE,), "send or drop: sclaude's own commits that changed the product, at such an end"),
    ("acceptance.kept", (FEATURE,), "the warning about criteria the plan words otherwise, as last shown (a hash): not shown twice"),

    # --- the steps -------------------------------------------------------------
    ("steps.<step>.session", (FEATURE,), "the claude conversation the step runs in"),
    ("steps.<step>.started", (FEATURE,), "when the step's session started"),
    ("steps.<step>.finished", (FEATURE,), "when the step closed"),
    ("steps.<step>.done", (FEATURE,), "the step is closed"),
    ("steps.<step>.gate", (FEATURE,), "the session is over and only the step's closing checks are left"),
    ("steps.<step>.bg", (FEATURE,), "the step's session ran in the background (the issue shows it)"),
    ("steps.<step>.taken_at", (FEATURE,), "when [n] closed the session: its marker's time, to the fraction of a second"),
    ("steps.<step>.rounds", (FEATURE,), "review rounds the step's session closed (counted per session)"),
    ("steps.<step>.auto_returns", (FEATURE,), "automatic returns to the session used since the step last closed"),
    ("steps.<step>.runs", (FEATURE,), "one entry per conversation the step ran in (session_runs)"),
    ("steps.review.enough", (FEATURE,), "the person said \"enough\" in this round"),
    ("steps.review.go_on", (FEATURE,), "[g]: the review goes on by itself while the person is away"),
    ("steps.review.go_on_rounds", (FEATURE,), "rounds run under [g] in this review"),
    ("steps.review.go_on_ceiling", (FEATURE,), "the rounds [g] may run before asking again"),
    ("steps.review.friction_held", (FEATURE,), "the friction review held for the person ([g]), by its key"),
    ("steps.review.left_open", (FEATURE,), "review threads left open at the close"),
    ("steps.review.local_told", (FEATURE,), "the head the local review's result was last told for"),
    ("steps.review.round_head", (FEATURE,), "the head a review round began on"),
    ("steps.review.round_open", (FEATURE,), "a review round is under way"),
    ("steps.review.round_since", (FEATURE,), "when the open round began"),
    ("steps.review.stuck", (FEATURE,), "the verdict that keeps the review from closing by itself, when one does"),
    ("steps.review.stuck_pr", (FEATURE,), "the pull request the stuck review was about"),
    ("steps.review.stuck_said", (FEATURE,), "the pull request the person was last told was stuck"),
    ("review.local.running", (FEATURE,), "when the local review's passes began; null once they end"),

    # --- a reopened feature ----------------------------------------------------
    ("reopened", (FEATURE,), "the step the feature was sent back to after it closed"),
    ("reopened_by", (FEATURE,), "what sent it back: preview, prod, qa"),
    ("reopened_pr", (FEATURE,), "the pull request the return is fixed in"),
    ("reopened_since", (FEATURE,), "when it was sent back"),

    # --- regression, deploy, QA, rollback ------------------------------------
    ("regression.<stage>.status", (FEATURE,), "the last run's outcome: passed, failed, running"),
    ("regression.<stage>.started", (FEATURE,), "when the last run began"),
    ("regression.<stage>.finished", (FEATURE,), "when it ended"),
    ("regression.<stage>.failed_at", (FEATURE,), "the part of the suite that failed"),
    ("regression.<stage>.reason", (FEATURE,), "what the person said of the last red"),
    ("regression.<stage>.tree", (FEATURE,), "the tree the last run tested, so an unchanged tree is not run twice"),
    ("regression.<stage>.attempts", (FEATURE,), "fix sessions opened in this round"),
    ("regression.<stage>.orchestrator_fixes", (FEATURE,), "reruns before a session in this round (the first red is rerun once)"),
    ("regression.<stage>.fix_session", (FEATURE,), "the session fixing the last red"),
    ("regression.<stage>.fix_for", (FEATURE,), "the failure that session fixes"),
    ("regression.<stage>.fix_started", (FEATURE,), "when it started"),
    ("regression.<stage>.fix_status", (FEATURE,), "how each fix session ended, a word for each in `fixes`"),
    ("regression.<stage>.fixes", (FEATURE,), "the fix sessions so far, by short id"),
    ("regression.<stage>.unrunnable", (FEATURE,), "the suite could not run at all: asked again, not rolled back"),
    ("regression.<stage>.deploy_failed", (FEATURE,), "the deploy before the run failed, and the command that did"),
    ("regression.<stage>.after_failure", (FEATURE,), "production shipped while a red was held"),
    ("regression.<stage>.intruded", (FEATURE,), "another release went to production on top of this one"),
    ("regression.preview.url", (FEATURE,), "the preview's address"),
    ("deploy.<stage>.sha", (FEATURE,), "the commit deployed there"),
    ("deploy.prod.pr", (FEATURE,), "the pull request production shipped"),
    ("deploy.prod.url", (FEATURE,), "production's address"),
    ("deploy.prod.migrations", (FEATURE,), "the migrations production applied"),
    ("regression.<stage>.<field>", (FEATURE,), "any of the above, for code that appends to one"),
    ("prod_pass.shipping", (FEATURE,), "the ship question is pending (marked by the pass that asked it)"),
    ("prod_pass.ended", (FEATURE,), "what a pass through the epilogue left at the clean-up: the pull request and production, or nodeploy"),
    ("qa.accepted", (FEATURE,), "when QA accepted the work"),
    ("qa.sha", (FEATURE,), "the head QA accepted"),
    ("rollback.prod.code", (FEATURE,), "the code rollback's outcome"),
    ("rollback.prod.at", (FEATURE,), "when production was rolled back"),
    ("rollback.prod.sha", (FEATURE,), "the commit rolled back from"),
    ("rollback.prod.to_sha", (FEATURE,), "the commit rolled back to"),
    ("rollback.prod.url", (FEATURE,), "the deployment rolled back to"),
    ("rollback.prod.log", (FEATURE,), "where the rollback's log was kept"),
    ("rollback.db.status", (FEATURE,), "the database rollback's outcome"),
    ("status.preview_red", (FEATURE,), "the issue's status was written about a red preview: rewrite it when green"),
    ("status.fingerprint", (FEATURE,), "what the issue's status was last written from, to skip an unchanged one"),

    # --- the friction reviews --------------------------------------------------
    ("friction.<key>.session", (FEATURE,), "the review's conversation"),
    ("friction.<key>.was", (FEATURE,), "the conversation of a review closed, kept to be resumed"),
    ("friction.<key>.cwd", (FEATURE,), "where it ran"),
    ("friction.<key>.started", (FEATURE,), "when it started"),
    ("friction.<key>.finished", (FEATURE,), "when it ended"),
    ("friction.<key>.done", (FEATURE,), "it is closed"),
    ("friction.<key>.empty", (FEATURE,), "there was nothing to review"),
    ("friction.<key>.fixed", (FEATURE,), "the review changed sclaude"),
    ("friction.<key>.verdict", (FEATURE,), "what the review concluded"),
    ("friction.<key>.verdict_note", (FEATURE,), "the review's own words about it"),
    ("friction.<key>.held", (FEATURE,), "held for the person ([g]), to be read later"),
    ("friction.<key>.read_in", (FEATURE,), "the review a held one was read in"),
    ("friction.<key>.unread", (FEATURE,), "closed by hand with its entries unread"),
    ("friction.<key>.stalled", (FEATURE,), "its conversation stalled at the start"),
    ("friction.<key>.apply_now", (FEATURE,), "the person asked for its change to go in now"),
    ("friction.<key>.from", (FEATURE,), "sclaude's head before the review"),
    ("friction.<key>.to", (FEATURE,), "and after it"),
    ("friction.<key>.project_base", (FEATURE,), "the project's head the review started from"),
    ("friction.<key>.project_from", (FEATURE,), "the project's head before the review's changes"),
    ("friction.<key>.project_to", (FEATURE,), "and after them"),
    ("friction.<key>.runs", (FEATURE,), "one entry per conversation (session_runs)"),
    ("friction.<key>.<field>", (FEATURE,), "any of the above, for code that clears several"),
    ("friction_owed", (FEATURE,), "a friction review still owed before the next step"),
    ("friction_owed_told", (FEATURE,), "the person was told it is owed"),

    # --- the retrospective -----------------------------------------------------
    ("retro.head", (FEATURE,), "sclaude's head when the retrospective started"),
    ("retro.project_from", (FEATURE,), "the project's head before the retrospective's changes"),
    ("retro.project_to", (FEATURE,), "and after them"),

    # --- the dev server and the feature's database -----------------------------
    ("dev.label", (FEATURE,), "the dev server's host name: <label>.localhost"),
    ("dev.port", (FEATURE,), "its port"),
    ("db.base", (FEATURE,), "the first of the feature database's block of ports"),
    ("db.project_id", (FEATURE,), "the local Supabase project's id"),
    ("db.ready", (FEATURE,), "the database is up and migrated"),
    ("db.filled", (FEATURE,), "when it was filled with data"),
    ("db.copied", (FEATURE,), "it holds a copy of the main database's data"),

    # --- the epilogue's own record ---------------------------------------------
    ("session", (EPILOGUE,), "the epilogue's conversation"),
    ("started", (EPILOGUE,), "when it started"),
    ("done", (EPILOGUE,), "it wrote the status"),
    ("merged", (EPILOGUE,), "the pull request's state when it started"),
    ("preview", (EPILOGUE,), "the preview's outcome it writes about"),
    ("prod", (EPILOGUE,), "production's outcome it writes about"),
    ("preview_red", (EPILOGUE,), "it writes about a red preview (1)"),

    # --- the QA watch ----------------------------------------------------------
    ("repo", (WATCH,), "owner/name of the repository"),
    ("root", (WATCH,), "the project's checkout, where the timer runs `sclaude _handoff`"),
    ("since", (WATCH,), "UTC: comments after this are QA's notes"),
    ("status", (WATCH,), "the issue's column last seen"),
    ("verdict", (WATCH,), "what QA's move meant: accepted, returned"),
    ("handoff", (WATCH,), "the pull request's hand-over to the merger: done, gone, partial"),
    ("qa_returns", (WATCH, FEATURE), "how many times QA sent the feature back"),
    ("columns.qa", (WATCH,), "the board's In QA column"),
    ("columns.done", (WATCH,), "its Done column"),
    ("columns.back", (WATCH,), "the column a return goes to"),
    ("columns.backlog", (WATCH,), "the backlog, a hand-back too"),
]

# Written whole from Python (start.sh's heredoc, session_runs) rather than
# through state_set, so no state_get/state_set names them.
WRITTEN_WHOLE = {"created", "steps.<step>.runs", "friction.<key>.runs"}

WILD = "<*>"


def _parts(path):
    return path.split(".")


# The names a placeholder stands for, where they are a closed list: a step or
# a stage misspelt is then caught too. <key> and <field> take any name.
VALUES = {
    "<step>": {"plan", "code", "pr", "review"},
    "<stage>": {"local", "preview", "prod"},
}


def _segment_ok(pattern_part, code_part):
    """A pattern part against a part of a path in the code: <name> takes any
    one of its names, and the code's <*> (a variable) fits anything."""
    if code_part == WILD:
        return True
    if pattern_part.startswith("<"):
        allowed = VALUES.get(pattern_part)
        return allowed is None or WILD in code_part or code_part in allowed
    # A name built around a variable, such as fix-<*>-<*>, fits a placeholder
    # (above) or a literal it could spell.
    if WILD in code_part:
        import re
        rx = "^" + ".*".join(re.escape(p) for p in code_part.split(WILD)) + "$"
        return re.match(rx, pattern_part) is not None
    return pattern_part == code_part


def known(path):
    """Whether a path — concrete, or from the code with <*> for a variable —
    is one of FIELDS."""
    parts = _parts(path)
    for pattern, _, _ in FIELDS:
        pp = _parts(pattern)
        if len(pp) == len(parts) and all(_segment_ok(a, b) for a, b in zip(pp, parts)):
            return True
    return False


def describe(path):
    parts = _parts(path)
    for pattern, records, meaning in FIELDS:
        pp = _parts(pattern)
        if len(pp) == len(parts) and all(_segment_ok(a, b) for a, b in zip(pp, parts)):
            return pattern, records, meaning
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        found = describe(sys.argv[1])
        print("%s  [%s]  %s" % (found[0], ", ".join(found[1]), found[2]) if found else "unknown")
        sys.exit(0 if found else 1)
    for pattern, records, meaning in FIELDS:
        print("%-36s %-24s %s" % (pattern, ",".join(records), meaning))
