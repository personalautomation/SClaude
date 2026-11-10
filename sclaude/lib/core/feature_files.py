#!/usr/bin/env python3
# What sclaude keeps beside a feature's state, in .sclaude/local/feature/ of
# its worktree, and what each file is for.
#
# The directory goes with the worktree at the clean-up, and git and every
# Vercel upload are kept out of it (scratch.sh). Its files are named in many
# places — the shell, the hooks, the proxy, the bot, the prompts — and a name
# mistyped on one side reads as a file that is not there, without an error.
# tests/feature-files.py fails on a name written in the code as
# `.sclaude/local/feature/<name>` that is not listed here, and on a listed one
# nothing names. A file added goes here in the same change.
#
# A part in angle brackets stands for any name: <key> a friction review's
# key, <suffix> the rest of a family's name.
#
#   python3 feature_files.py            the list
#   python3 feature_files.py <name>     what one is

DIR = ".sclaude/local/feature"

FILES = [
    # --- the cycle -------------------------------------------------------------
    ("state.json", "where the feature stands; its fields are in state_schema.py"),
    ("state.json.lock", "the state's lock: every writer changes it under it (state_file.py)"),
    ("history.jsonl", "one line per thing that began or ended (history_add) and per way taken on a map (history_edge); the process map plays it"),
    ("plan.md", "the plan step 1 wrote and the person approved"),
    ("plan.printed", "the plan as last printed, so a later session prints it only when it changed"),
    ("session-done", "a session's marker: its work is done (the session writes it, the watcher reads it)"),
    ("review-checked", "`sclaude checks` returned on a review run (its code, head, time): sclaude's tab prints the report by it"),
    ("closing", "the worktree's removal has begun: no lazy start, the menu offers it no more"),
    ("terminal", "the terminal recordings that touched the feature, one path a line"),
    ("terminal.txt", "those recordings played back into text"),
    ("main-config.json", "the project config as this machine reads it (the main checkout's, its local choices over it), copied where the retrospective reads it"),

    # --- friction --------------------------------------------------------------
    ("friction.log", "what got in a session's way, for its friction review"),
    ("friction.log.reviewed", "the entries a friction review has read"),
    ("friction-<key>.log", "one friction review's own entries, by its key"),

    # --- review ----------------------------------------------------------------
    ("review-yours", "review threads the person decided to leave (YOURS_FILE in pr_context.py)"),
    ("review-night", "the night's decisions on threads, to be confirmed in the morning (NIGHT_FILE)"),
    ("review-reversals", "threads a review session reversed (reversals_file in review_round.sh)"),
    ("review-fallback", "GitHub's review could not run (Claude's limit, no Actions minutes): the feature is reviewed on this machine (review_fallback_set, FALLBACK_FILE)"),
    ("review-rounds.jsonl", "the review's journal, one line per run wherever it ran (review_journal, JOURNAL in local_review.py)"),
    ("local-review<suffix>", "a review run on this machine: -unposted.json "
                             "findings GitHub would not take yet, -answer.md the last answer, .log its stderr"),

    # --- regression and deploy -------------------------------------------------
    ("regression.log", "the latest regression run's log: a link into logs/"),
    ("logs", "every run's log, named by its stage (log_new)"),
    ("regression.blocked", "a note that stops the next run until it is dealt with"),
    ("regression.notes", "blocked notes taken off, kept beside the state (blocked_note_keep)"),
    ("e2e-server.log", "the server the end-to-end part ran against"),
    ("serving-build", "a production build serves the dev port: the proxy starts no dev server meanwhile"),
    ("deploy.at", "the command a deploy failed at, for the session that fixes it"),
    ("preview.url", "the preview's address as the deploy printed it"),
    ("merge-check.log", "git merge-tree's output from the last merge check"),
    ("merge-ready.md", "the merge-ready comment posted for the merger"),
    ("handoff.lock", "one hand-over of the pull request at a time"),
    ("rollback", "a production rollback's files (down.sql)"),

    # --- the dev server, the browser, the database -----------------------------
    ("dev.log", "the dev server's log; the keepawake detector reads it as a sign of work"),
    ("chrome.log", "chrome-debug's log, when sclaude started it"),
    ("exposed-said", "the pid of the server last warned about for listening past loopback"),
    ("claude-tab.log", "what claude said on stderr in a tab, and how it exited"),
    ("db.env", "the feature database's connection, sourced by the regression's local stage"),
    ("db.log", "the feature database's start and migrations"),
    ("db-copy.sql", "main's rows, dumped for the copy into the feature's database"),
    ("db-copied-users", "the people copied from the main database, one id a line"),
    ("supabase", "the feature's own Supabase project"),
    ("telegram.json", "the bot's record of the feature's topic (FEATURE_RECORD in topics.py)"),
]


def _match(pattern, name):
    import re
    rx = "^" + re.sub(r"<[a-z]+>", ".+", re.escape(pattern).replace(r"\<", "<").replace(r"\>", ">")) + "$"
    return re.match(rx, name) is not None


def describe(name):
    """The entry a file name is, or None. A name in a directory listed here
    (logs/…) is that directory's."""
    head = name.split("/", 1)[0]
    for pattern, meaning in FILES:
        if _match(pattern, name) or _match(pattern, head):
            return pattern, meaning
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        found = describe(sys.argv[1])
        print("%s  %s" % found if found else "unknown")
        sys.exit(0 if found else 1)
    for pattern, meaning in FILES:
        print("%-24s %s" % (pattern, meaning))
