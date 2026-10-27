#!/usr/bin/env python3
"""sclaude's process as a model, and the maps drawn from it.

One description of the cycle — who does what, in which order, where it goes
back, and which commands lead where — serves two pages:

  the printed one, docs/presentations/bpmn_diagrams.html, built by
      python3 sclaude/lib/process.py doc <out.html>
  and a feature's own, which sclaude-proxy serves at /__sclaude/flow?f=<label>
      with the feature's place lit and the actions open to it now
      (`sclaude _flow <name>` says both; `position` below reads the state).

The model is checked against the code by tests/process.py: the commands
against bin/sclaude's dispatch, the actions against actions.sh, the step
numbers against cycle_number, every place `position` can answer against the
nodes. A change to the cycle that is not made here fails there.

Layout: BPMN with vertical lanes, the flow running down. Each node sits in a
lane and a row; an edge running down bends in the gap above its target, and
one running back up goes round by a channel on the right, so no line crosses
a node. Vertical lanes keep the width to a page's, and the length is what
splits across pages.

    process.py doc <out.html>
    process.py position <state.json> [pr-state] [epilogue.json]
    process.py page <label>              a feature's page shell, for a check
"""

import datetime
import html
import json
import os
import sys

# --- the model ---------------------------------------------------------------

# Lanes of the detailed map, left to right.
LANES = [
    ("person", "You"),
    ("qa", "QA"),
    ("sclaude", "sclaude"),
    ("session", "Claude session"),
    ("github", "GitHub"),
    ("watch", "Timer & bot"),
]

# A node: id -> (lane, row, kind, title, text, flags).
# kind: start, end, task, session, gate, wait, hold, user.
# flags: "F" a friction review follows the session; "W" it may change sclaude
# in its tree's workshop.
NODES = {
    # start
    "new": ("person", 0, "start", "sclaude new",
            "choose an issue, or type a name", ""),
    "prepare": ("sclaude", 1, "task", "Prepare the feature",
                "worktree from origin/main, branch feat/<slug>, its own dev server and database", ""),
    "board_start": ("github", 1, "task", "Issue taken",
                    "Backlog → In progress, Start date", ""),
    "main_in": ("sclaude", 2, "task", "Main merged in",
                "before every step, without asking; a conflict goes to the sync (5)", ""),
    # step 1
    "plan": ("session", 3, "session", "1 · plan",
             "the issue, its parents and the manuals; scope first, then a plan with acceptance criteria", "FW"),
    "approve": ("person", 4, "user", "Correct and approve",
                "the scope, then the plan with its criteria", ""),
    "plan_check": ("sclaude", 5, "gate", "Plan read back?",
                   "the approved text found in the transcript", ""),
    "ac": ("github", 5, "task", "Criteria on the issue",
           "a comment of their own, AC1, AC2, …", ""),
    # step 2
    "code": ("session", 6, "session", "2 · code",
             "builds it, checks it in Chrome, commits with Requirement: ACn", "FW"),
    "works": ("person", 7, "gate", "Does it work?",
              "your yes; a no goes back with what is wrong", ""),
    "reg_local": ("sclaude", 8, "gate", "Local regression green?",
                  "the project's suite against the feature's server", ""),
    "fix_local": ("session", 8, "session", "Fix after regression",
                  "makes the red tests green — two sessions at most, then it stops for you", "F"),
    # step 3
    "pr": ("session", 9, "session", "3 · pr",
           "manuals updated, a draft PR by the pr skill, the criteria as QA's checklist", "FW"),
    "pr_check": ("sclaude", 10, "gate", "PR there, all pushed?",
                 "a pull request on GitHub carrying every commit", ""),
    "draft_pr": ("github", 10, "task", "Draft PR",
                 "the review workflow reads it (review: github)", ""),
    # step 4
    "local_pass": ("session", 11, "task", "Local review passes",
                   "review: local — read-only passes; findings posted on the PR", ""),
    "review_found": ("sclaude", 12, "gate", "Anything to answer?",
                     "findings, comments, red checks; none — no session at all", ""),
    "review": ("session", 13, "session", "4 · review",
               "fixes the findings through subagents, pushes, one round, stops", "FW"),
    "round": ("sclaude", 14, "gate", "Round closed: context under 40%?",
              "yes — the same session takes the new findings; no — a fresh one", ""),
    "review_close": ("sclaude", 15, "gate", "Nothing open, local regression green?",
                     "no thread, no red or running check; then step 4 is done", ""),
    # end of the cycle
    "hold": ("sclaude", 16, "gate", "Production red and carrying it?",
             "a red last run, a failed or refused rollback — the cycle holds", ""),
    "hold_ways": ("person", 16, "hold", "Held",
                  "regression <name> prod · rollback · return", ""),
    "merge_check": ("sclaude", 17, "gate", "Merges with main?",
                    "git merge-tree, no session; before the preview, after QA, while waiting", ""),
    "sync": ("session", 17, "session", "5 · sync",
             "merges origin/main in, resolves the conflicts, checks, pushes", "W"),
    "preview": ("sclaude", 18, "task", "Preview",
                "deployed (three tries), the preview regression run against it", ""),
    "preview_ok": ("sclaude", 19, "gate", "Preview green?",
                   "red — the fix goes on from step 4", ""),
    "fix_preview": ("session", 19, "session", "Fix after preview",
                    "makes the preview's tests green, from step 4", "F"),
    "in_qa": ("github", 20, "task", "Issue → In QA",
              "the preview is what QA looks at", ""),
    "watch": ("watch", 20, "wait", "QA watched",
              "sclaude-watch polls the column, tells the feature's topic", ""),
    "qa_check": ("qa", 21, "user", "QA checks the criteria",
                 "on the preview, ticking them in the issue", ""),
    "qa_verdict": ("qa", 22, "gate", "Done, or back?",
                   "Done — on to the merge; In progress — a hand-back", ""),
    "handoff": ("sclaude", 23, "task", "PR handed over",
                "ready for review, Backlog, a summary for whoever merges", ""),
    "merge": ("person", 24, "gate", "Merge?",
              "offered, or done by sclaude when the project says merge: auto", ""),
    "merge_wait": ("sclaude", 24, "wait", "Waiting for the merge",
                   "polls every 30 s; main checked every 2 min", ""),
    "merged": ("github", 25, "task", "Merged",
               "Closes #N closes the issue; Target date; PR → Done", ""),
    "ship": ("person", 26, "gate", "Ship to production?",
             "asked after the merge", ""),
    "prod": ("sclaude", 27, "task", "Production",
             "the promote of migrations, vercel --prod, the production regression", ""),
    "prod_ok": ("sclaude", 28, "gate", "Production green?",
                "red — rolled back before anything is fixed", ""),
    "rollback": ("sclaude", 29, "task", "Rollback",
                 "the previous deployment, the down blocks, a check, the incident on the issue", ""),
    "fix_prod": ("session", 29, "session", "Fix after production",
                 "told what failed and that production runs the old release", "F"),
    "epilogue": ("session", 30, "session", "6 · epilogue",
                 "Current status on the issue and every parent; deployed-* labels", ""),
    "done_cmd": ("person", 31, "user", "sclaude done",
                 "offered at the end; the clean-up after the merge", ""),
    "retro": ("session", 32, "session", "7 · retro",
              "what was missed, what could work better, what sclaude could do better", "W"),
    "retro_fix": ("sclaude", 33, "gate", "The retro changed the code?",
                  "yes — its commits go out from step 3", ""),
    "cleanup": ("sclaude", 34, "task", "Clean-up",
                "the cycle's record; asks, then removes the worktree, branches and database", ""),
    "end": ("sclaude", 35, "end", "Done", "", ""),
}

# How each session runs: model · effort · permission mode. Shown in the note
# under the pointer rather than on the block; tests/process.py reads them
# against STEP_SPEC, SYNC_MODEL and the epilogue's and the retro's launches.
SPEC = {
    "plan": ("opus", "high", "plan"),
    "code": ("opus", "medium", "auto"),
    "pr": ("sonnet", "medium", "auto"),
    "review": ("opus", "medium", "auto"),
    "fix_local": ("opus", "medium", "auto"),      # step 2's
    "fix_preview": ("opus", "medium", "auto"),    # step 4's
    "fix_prod": ("opus", "medium", "auto"),       # step 4's
    "sync": ("sonnet", "medium", "auto"),
    "epilogue": ("sonnet", "medium", "auto"),
    "retro": ("opus", "medium", "auto"),
    "local_pass": ("opus", "default", "read-only, claude -p"),
    "f_review": ("opus", "medium", "plan"),
    "f_monthly": ("opus", "medium", "plan"),
    "f_classify": ("haiku", "default", "claude -p, no tools"),
}

# What each block does, at more length than fits on it: the note under the
# pointer. The overview's and the states' blocks borrow these (ALIAS).
DETAILS = {
    "new": "Lists the repository's open issues, yours first, and suggests a branch name from the chosen one; or takes a name typed by hand. From the phone the Mini App asks the same and starts it with the answers.",
    "prepare": "Branches feat/<slug> from a fresh origin/main into a worktree of its own, links the environment and hard-links node_modules, claims a port and a <feature>.localhost address, and on a local database starts a Supabase stack for this feature alone.",
    "board_start": "Moves the issue out of Backlog to In progress on every board it is on, and fills an empty Start date with today. Once, at the start; a column moved by hand is left alone.",
    "main_in": "Before each step sclaude merges origin/main into the branch without asking, so every session works on what will merge. A merge that would conflict goes to the sync session (5); only the deferred logs it merges itself.",
    "plan": "The session reads the issue with its parents and comments and the manuals' tables of contents, says what it understood the scope to be and waits for corrections, then plans. The plan ends with numbered acceptance criteria, each checkable on a deployment without reading code.",
    "approve": "You correct the scope, then approve the plan in Claude Code's plan dialog. The criteria are what QA will tick later, so this is where a missing one costs least.",
    "plan_check": "sclaude reads the approved plan back from the session's transcript into .sclaude/local/feature/plan.md, the bridge to step 2. Not found: the same session is sent back to present it again, at most twice.",
    "ac": "The criteria go into a comment of their own on the issue, between sclaude's markers; the issue's description is never edited. QA ticks them there.",
    "code": "A fresh session builds from the plan, checks the result in Chrome at the feature's own address, and commits with a Requirement: ACn footer naming the criterion each commit serves. It closes with a report criterion by criterion.",
    "works": "sclaude asks whether everything works as it should. A no takes what is wrong back to the same session as your message; Enter alone leaves the step for later.",
    "reg_local": "The project's suite (its config's regression parts) against the feature's own server and database. An unpublished branch is put on top of main first. Green closes step 2; at step 4 it runs again before the step closes.",
    "fix_local": "A separate session gets the failing log and fixes the cause, then the suite runs again. Two sessions that do not make it green stop the cycle and tell you: a third guess at the same failure rarely helps.",
    "pr": "Updates the manuals the change touches and opens a draft pull request through the pr skill, with the criteria copied in as QA's unticked checklist and Closes #N for the issue.",
    "pr_check": "sclaude looks for the pull request on GitHub and for commits it does not carry. Missing either: the session is sent back to finish, at most twice.",
    "draft_pr": "The draft is assigned to its author and put in the issue's milestone. The project's review workflow reads it, unless the review runs on this machine or is off.",
    "local_pass": "With review set to local, read-only claude -p passes review the pull request here and post their findings as threads signed by this machine. A key in the terminal or in the topic ends the search.",
    "review_found": "Findings, unresolved threads, comments and red checks are gathered before any session. Nothing to answer: step 4 closes with no session at all.",
    "review": "The session fixes the findings through subagents, keeping only the coordination, pushes, and stops once the automatic review has confirmed the fixes and posted the next round.",
    "round": "A watcher ends the session when the round closes. Under 40% context the same conversation takes the new findings; above it a fresh one does, after the round's friction review. Rounds that stop converging are said once.",
    "review_close": "Leaving step 4 closes it only when nothing is open — no unresolved thread, no running or red check — and the local regression is green again. Otherwise sclaude waits, says what is open, and offers the session back.",
    "hold": "Production carries this feature and its last run there was red, could not run, or has another release on top. The cycle ships, closes and cleans up nothing until a person chooses a way out.",
    "hold_ways": "sclaude regression <name> prod runs production's suite again (green lifts the hold); sclaude rollback puts the previous release back and sends the fix to step 4; sclaude return fixes forward from step 4.",
    "merge_check": "git merge-tree tells in memory whether the branch merges cleanly with main — no session, no GitHub call. Asked before the preview, after QA's yes, and every two minutes while waiting for the merge.",
    "sync": "Merges origin/main into the branch (never a rebase), resolves each conflict keeping both sides' intent, checks the result as the project's CLAUDE.md says and pushes. sclaude then checks it settled; a pull request handed over goes back to a draft.",
    "preview": "Deploys the worktree to a preview from the main repository (up to three tries), applies the branch's migrations there, and runs the preview regression against the deployment. An unchanged tree already green is not deployed again.",
    "preview_ok": "Green: the issue goes to In QA. Red: no label is claimed, the cycle goes back to step 4 and a fixing session opens there.",
    "fix_preview": "A fixing session in step 4, where the pull request is open and pushes reach the branch, with the failing run's log. The fix goes the whole way round again.",
    "in_qa": "The issue moves to In QA only after the preview's tests passed, so the column says something true. The QA watch starts.",
    "watch": "A systemd timer looks at the issue's column every few minutes and tells the feature's topic; it hands the pull request over when QA says Done, even with nobody at the terminal. It changes nothing else.",
    "qa_check": "QA opens the preview, checks each acceptance criterion and ticks it in the issue's comment. Nothing ticks a box but a person, unless the project's qa setting says so.",
    "qa_verdict": "Done goes on to the merge. In progress or Backlog is a hand-back: everything said since on the issue and the pull request is collected word for word and opens step 4 with it.",
    "handoff": "The draft is marked ready, moved to Backlog, its assignees cleared, and a summary for whoever merges is posted: the preview, QA's verdict, the criteria, the review's findings, the checks.",
    "merge": "The merge is yours unless the project's config says merge: auto. sclaude offers it once QA passed and GitHub says the way is clear; declined, it waits.",
    "merge_wait": "Polls GitHub every 30 seconds for the merge and checks every two minutes whether main moved into a conflict. Ctrl-C leaves the wait and loses nothing.",
    "merged": "GitHub closes the issue by Closes #N; sclaude fills Target date with today so the roadmap's bar ends when the work did, and moves the pull request to Done.",
    "ship": "Asked once the merge is in. The deployment production runs now is recorded first, for a rollback. A no goes on to the epilogue with production postponed.",
    "prod": "The project's promote of migrations if the branch has any, then vercel --prod from the main repository, then the production regression against production.",
    "prod_ok": "Green: deployed-prod is labelled and the cycle goes on. Red: production is rolled back before anything is fixed.",
    "rollback": "vercel rollback to the recorded deployment, the migrations' down blocks only when every one is runnable, a check that the old release serves, and an incident comment on the issue.",
    "fix_prod": "Opens in step 4 with the failing run's log, told that production runs the previous release and that the local suite is the check that matters. The fix goes round again: local, merge, preview, production.",
    "epilogue": "A short session writes a Current status comment on the issue and on every parent up the chain, and Current behaviour where the product now differs from a description. Labels deployed-preview and deployed-prod are set by how each stage ended.",
    "done_cmd": "Offered at the end of the cycle; also from the menu. It checks the merge with GitHub, runs the retrospective, then asks before removing anything.",
    "retro": "Reads the plan, the friction logs and the terminal's record of the cycle: what you may have missed, how the work could go better, what sclaude could do better. It may fix sclaude in its workshop.",
    "retro_fix": "Commits the retrospective made on the feature's branch go out the way the feature's own did: back to step 3 for their pull request and the review.",
    "cleanup": "Appends the cycle's record to ~/.claude/sclaude/cycles.jsonl, then asks before removing the worktree, the branches and the feature's database.",
    "end": "The feature is done: merged, shipped or postponed, its outcome written into the issues. sclaude drop ends it here too, from any step: the worktree, the branches, the pull request and the issue (closed as not planned), each asked about.",
    "f_trip": "During any step or fixing session, a hook refuses a command, a rule of --disallowed-tools fires, Claude Code's auto-mode classifier refuses, or the session itself notes what got in its way, or proposes a rule for the project's CLAUDE.md.",
    "f_log": "The hooks append each refusal to .sclaude/local/feature/friction.log as it happens: the time, the step, the source, the subject, the reason. The classifier's refusals leave no event, so they are gathered from the transcript once the session ends.",
    "f_empty": "Asked after every step's session, every review round that goes to a fresh session and every fixing session. An empty log needs no session: the issue's Friction column says nothing for it — the ordinary case.",
    "f_none": "Nothing got in the session's way that a rule refused: the cycle goes straight on.",
    "f_rules": "A log of nothing but proposed CLAUDE.md rules needs no session: they are put off to the monthly review, where how often a class comes back decides it. With SCLAUDE_FRICTION_ASK=on you are asked first, and now hands them to a review told to write them in.",
    "f_classify": "One call of a small model reads the proposals, the classes already put off and CLAUDE.md, and says of each: the same as a class already there, a rule CLAUDE.md already states, or new. Checked, not trusted; a failure leaves the rows as they came.",
    "f_review": "A session in plan mode, in the feature's tree, reads this session's entries and its transcript and decides each one. It may change the product's rules on the feature's branch, and sclaude itself in the workshop. It ends with a verdict line.",
    "f_hold": "A review interrupted, or one that never started, stays open and holds the cycle: the next step waits until sclaude friction finishes it or sclaude reset closes it.",
    "f_plan": "The review starts in plan mode, so nothing changes before you approve its plan: which file each change goes to, and why.",
    "f_decide": "A restriction that blocked ordinary work and protects nothing is lifted; one working as intended is explained; one a single feature is not enough evidence for is put off; a bug in sclaude's own code is fixed in sclaude.",
    "f_lift": "An allow or deny entry in the product's policy.json (the team's, or the person's own), a rule in the project's CLAUDE.md, or an addition to a step's prompt — committed on the feature's branch, to reach main with its pull request.",
    "f_deliberate": "Merging, deploying, pushing to main and the product's production commands are sclaude's steps: a session tripping over them only means the ban worked. One that will recur every feature gets a deny entry, so it stops reaching the log.",
    "f_bug": "A hook that misreads an ordinary command, a message that sends a session the wrong way: fixed in sclaude, with a test, in the tree's workshop, and published when the review ends — see How a session changes sclaude.",
    "f_defer": "A tab-separated row in the feature's own file under .sclaude/…/deferred/: the date, the project, the feature, the step, a class and one sentence. The rows go to main by themselves, ahead of the feature.",
    "f_verdict": "sclaude reads the review's last line, sclaude-verdict: lifted, deliberate or mixed, from its transcript, and keeps which commits it made: the issue's Friction column and its table of what the friction reviews changed.",
    "f_push": "The review's commits are pushed to the feature's branch and go through its pull request's review. A feature already merged gets a pull request of their own.",
    "f_next": "The cycle goes on: the next step, the next review round, or the next fixing session.",
    "f_monthly": "sclaude deferred, offered once a month: every feature's put-off rows together. A class that keeps coming back is decided — a rule lifted, a preset changed, a CLAUDE.md line written — and its rows removed.",
    "w_find": "Any session sclaude runs may find something to fix in sclaude itself: a step, a fixing session, the retrospective, a friction review, the monthly review. sclaude's live checkout is read-only to all of them.",
    "w_ask": "In a step Claude Code asks you, every session anew: the model cannot answer it, in auto mode too. The retrospective and the friction and monthly reviews start in plan mode, so their approved plan is the yes.",
    "w_open": "Makes the tree's workshop, a worktree of sclaude from origin/main at .sclaude/local/instruments, shared by every session of the tree, and lets this session write there.",
    "w_change": "The session commits in the workshop and reviews its change: /sreview for a maintainer of sclaude, whatever review they choose for anybody else.",
    "w_ready": "Refuses uncommitted work and records the head as ready; for a maintainer it wants sreview's mark of a finished run at that head.",
    "w_exit": "Publishing starts from claude_launch once the session exits, whatever step it was in.",
    "w_ready_gate": "A change uncommitted, unreviewed at its head or never marked ready is not published.",
    "w_back": "The same conversation is offered back, told what is missing. A no records it as pending: it is offered again when the feature is next opened, and later sessions' changes wait behind it.",
    "w_leaks": "sclaude is public and the product is not: the added lines and the commit messages are searched for the product's repository and folder names, the feature's slug and branch, issue and pull-request numbers, and paths of the product's own files.",
    "w_leak_ask": "A hit is shown to you, in the terminal and in the topic when it is short. A yes is kept for the lines it was shown; a no holds the change at its head until a new commit is marked ready.",
    "w_tests": "The tests the change touches run in a clean environment, each in a session of its own with no terminal. Red tests, no network, a refused push or a conflict with main stop the publication; it is tried again whenever the tree is opened.",
    "w_who": "MAINTAINERS lists who may commit sclaude's core straight to main; with no file everybody is a maintainer.",
    "w_main": "Rebased onto origin/main, squashed into one commit, pushed to main; the live checkout is fast-forwarded when nothing runs from it, so the next session runs the fix.",
    "w_pr": "Pushed unsquashed to the workshop's own dev/<name>-<time> branch, never named after the feature, as one pull request per tree; the maintainer's review of it is the gate.",
}
ALIAS = {
    "o_new": "new", "o_plan": "plan", "o_approve": "approve", "o_code": "code", "o_works": "works",
    "o_reg": "reg_local", "o_pr": "pr", "o_review": "review", "o_ghreview": "draft_pr",
    "o_sync": "sync", "o_preview": "preview", "o_qa": "qa_check", "o_merge": "merge", "o_prod": "prod",
    "o_epilogue": "epilogue", "o_retro": "retro", "o_end": "cleanup",
    "s_plan": "plan", "s_code": "code", "s_pr": "pr", "s_review": "review", "s_sync": "sync",
    "s_preview": "preview", "s_qa": "qa_check", "s_merge": "merge_wait", "s_hold": "hold_ways",
    "s_epilogue": "epilogue", "s_retro": "retro", "s_done": "end",
}

# An edge: (from, to, label, kind). kind: "" the flow, "back" a return, "msg"
# a message between lanes, "cmd" a command a person runs.
EDGES = [
    ("new", "prepare", "", ""),
    ("prepare", "board_start", "", "msg"),
    ("prepare", "main_in", "", ""),
    ("main_in", "plan", "", ""),
    ("plan", "approve", "", ""),
    ("approve", "plan_check", "approved", ""),
    ("plan_check", "plan", "not found — sent back (≤2)", "back"),
    ("plan_check", "ac", "", "msg"),
    ("plan_check", "code", "yes", ""),
    ("code", "works", "", ""),
    ("works", "code", "no — what is wrong", "back"),
    ("works", "reg_local", "yes", ""),
    ("reg_local", "fix_local", "red", ""),
    ("fix_local", "reg_local", "again", "back"),
    ("reg_local", "pr", "green", ""),
    ("pr", "pr_check", "", ""),
    ("pr_check", "pr", "no — sent back (≤2)", "back"),
    ("pr_check", "draft_pr", "", "msg"),
    ("draft_pr", "local_pass", "review: local", ""),
    ("draft_pr", "review_found", "", ""),
    ("local_pass", "review_found", "", ""),
    ("review_found", "review", "yes", ""),
    ("review_found", "review_close", "nothing — step closes", ""),
    ("review", "round", "", ""),
    ("round", "review", "next round", "back"),
    ("round", "review_close", "session left", ""),
    ("review_close", "review", "no", "back"),
    ("review_close", "hold", "yes", ""),
    ("hold", "hold_ways", "yes", ""),
    ("hold", "merge_check", "no", ""),
    ("merge_check", "sync", "conflict", ""),
    ("sync", "merge_check", "settled", "back"),
    ("merge_check", "preview", "clean", ""),
    ("preview", "preview_ok", "", ""),
    ("preview_ok", "fix_preview", "red", ""),
    ("fix_preview", "review", "step 4 reopened", "back"),
    ("preview_ok", "in_qa", "green", "msg"),
    ("in_qa", "watch", "", "msg"),
    ("in_qa", "qa_check", "", ""),
    ("qa_check", "qa_verdict", "", ""),
    ("qa_verdict", "review", "hand-back: their words open step 4", "back"),
    ("qa_verdict", "handoff", "Done (main checked again)", ""),
    ("handoff", "merge", "", ""),
    ("merge", "merged", "yes", ""),
    ("merge", "merge_wait", "not now", ""),
    ("merge_wait", "merged", "merged on GitHub", ""),
    ("merge_wait", "sync", "main moved into a conflict", "back"),
    ("merged", "ship", "", ""),
    ("ship", "prod", "yes", ""),
    ("ship", "epilogue", "no", ""),
    ("prod", "prod_ok", "", ""),
    ("prod_ok", "rollback", "red", ""),
    ("rollback", "fix_prod", "", ""),
    ("fix_prod", "review", "step 4 reopened", "back"),
    ("prod_ok", "epilogue", "green", ""),
    ("epilogue", "done_cmd", "", ""),
    ("done_cmd", "retro", "", ""),
    ("retro", "retro_fix", "", ""),
    ("retro_fix", "pr", "yes — step 3 again", "back"),
    ("retro_fix", "cleanup", "no", ""),
    ("cleanup", "end", "", ""),
]

# The overview: the cycle at a glance.
OVERVIEW_LANES = [("person", "You and QA"), ("sclaude", "sclaude"),
                  ("session", "Claude session"), ("github", "GitHub")]
OVERVIEW_NODES = {
    "o_new": ("person", 0, "start", "sclaude new", "an issue or a name", ""),
    "o_plan": ("session", 1, "session", "1 · plan", "plan and acceptance criteria", "F"),
    "o_approve": ("person", 1, "user", "Approve", "the plan and its criteria", ""),
    "o_code": ("session", 2, "session", "2 · code", "build, check, commit", "F"),
    "o_works": ("person", 2, "gate", "Works?", "your yes", ""),
    "o_reg": ("sclaude", 3, "gate", "Tests green?", "a fix session if not", ""),
    "o_pr": ("session", 4, "session", "3 · pr", "manuals, draft PR", "F"),
    "o_review": ("session", 5, "session", "4 · review", "round after round", "F"),
    "o_ghreview": ("github", 5, "task", "Automatic review", "findings on the PR", ""),
    "o_sync": ("session", 6, "session", "5 · sync", "only on a conflict with main", ""),
    "o_preview": ("sclaude", 6, "task", "Preview", "deployed and tested", ""),
    "o_qa": ("person", 7, "gate", "QA", "Done or back", ""),
    "o_merge": ("person", 8, "user", "Merge", "yours, or auto", ""),
    "o_prod": ("sclaude", 9, "gate", "Production", "shipped and tested", ""),
    "o_epilogue": ("session", 10, "session", "6 · epilogue", "status up the issue chain", ""),
    "o_retro": ("session", 11, "session", "7 · retro", "lessons, sclaude's fixes", ""),
    "o_end": ("sclaude", 12, "end", "Clean-up", "", ""),
}
OVERVIEW_EDGES = [
    ("o_new", "o_plan", "", ""), ("o_plan", "o_approve", "", ""),
    ("o_approve", "o_code", "", ""), ("o_code", "o_works", "", ""),
    ("o_works", "o_reg", "yes", ""), ("o_works", "o_code", "no", "back"),
    ("o_reg", "o_pr", "green", ""), ("o_pr", "o_ghreview", "", "msg"),
    ("o_ghreview", "o_review", "", "msg"),
    ("o_review", "o_preview", "nothing open", ""),
    ("o_preview", "o_sync", "conflict", ""), ("o_sync", "o_preview", "", "back"),
    ("o_preview", "o_qa", "green", ""),
    ("o_preview", "o_review", "red", "back"),
    ("o_qa", "o_review", "back", "back"), ("o_qa", "o_merge", "Done", ""),
    ("o_merge", "o_prod", "", ""), ("o_prod", "o_review", "red: rollback", "back"),
    ("o_prod", "o_epilogue", "green", ""), ("o_epilogue", "o_retro", "", ""),
    ("o_retro", "o_pr", "it fixed code", "back"), ("o_retro", "o_end", "", ""),
]

# How a session changes sclaude itself: in its tree's workshop, published by
# sclaude once the session ends (sclaude/lib/workshop.sh). Any session with W
# on the maps may take this way.
WORKSHOP_LANES = [("person", "You"), ("sclaude", "sclaude"), ("session", "Claude session"),
                  ("github", "GitHub")]
WORKSHOP_NODES = {
    "w_find": ("session", 0, "start", "A fix for sclaude", "found by any session", ""),
    "w_ask": ("person", 1, "gate", "Let it write sclaude?", "asked in a step; a review's approved plan is the yes", ""),
    "w_open": ("session", 2, "session", "sclaude core-open", "opens the tree's workshop for this session", ""),
    "w_change": ("session", 3, "session", "Commit and review", "in the workshop; sreview for a maintainer", ""),
    "w_ready": ("session", 4, "session", "sclaude core-ready", "the head marked ready to publish", ""),
    "w_exit": ("session", 5, "session", "The session ends", "publishing begins", ""),
    "w_ready_gate": ("sclaude", 6, "gate", "Finished at its head?", "committed, reviewed, marked ready", ""),
    "w_back": ("person", 6, "gate", "Back to the session?", "told what is missing; no keeps it pending", ""),
    "w_leaks": ("sclaude", 7, "gate", "The product's details in it?", "names, numbers, paths of the product", ""),
    "w_leak_ask": ("person", 7, "gate", "Publish anyway?", "a no holds the change at its head", ""),
    "w_tests": ("sclaude", 8, "task", "The tests it touches", "a clean environment, no terminal; red — tried again later", ""),
    "w_who": ("sclaude", 9, "gate", "A maintainer?", "MAINTAINERS", ""),
    "w_main": ("github", 9, "task", "Pushed to main", "one squashed commit; the live checkout updated", ""),
    "w_pr": ("github", 10, "task", "A pull request", "from dev/<name>-<time>, one per tree", ""),
}
WORKSHOP_EDGES = [
    ("w_find", "w_ask", "", ""),
    ("w_ask", "w_open", "yes", ""),
    ("w_open", "w_change", "", ""),
    ("w_change", "w_ready", "", ""),
    ("w_ready", "w_exit", "", ""),
    ("w_exit", "w_ready_gate", "", ""),
    ("w_ready_gate", "w_back", "no", ""),
    ("w_back", "w_change", "yes — same conversation", "back"),
    ("w_ready_gate", "w_leaks", "yes", ""),
    ("w_leaks", "w_leak_ask", "a hit", ""),
    ("w_leak_ask", "w_tests", "yes", ""),
    ("w_leaks", "w_tests", "none", ""),
    ("w_tests", "w_who", "green", ""),
    ("w_who", "w_main", "yes", "msg"),
    ("w_who", "w_pr", "no", "msg"),
]

# The friction review: what the safety rules refused a session, read after it
# by a session of its own (run_friction in sclaude/lib/run.sh). Every session
# with F on the maps leads here.
FRICTION_LANES = [("session", "Step session"), ("sclaude", "sclaude"), ("review", "Friction review"),
                  ("person", "You"), ("branch", "Feature's branch"), ("monthly", "Put off")]
FRICTION_NODES = {
    "f_trip": ("session", 0, "start", "A refusal", "a hook, a rule, the classifier — or the session's own note", ""),
    "f_log": ("sclaude", 1, "task", "Friction log", "each refusal a paragraph; the classifier's gathered after the session", ""),
    "f_empty": ("sclaude", 2, "gate", "Anything logged?", "after every step, round and fix session", ""),
    "f_none": ("session", 2, "end", "No review", "the ordinary case", ""),
    "f_rules": ("sclaude", 3, "gate", "Only proposed rules?", "rules for the project's CLAUDE.md, nothing else", ""),
    "f_classify": ("monthly", 3, "task", "Matched, no session", "a small model names each one's class", ""),
    "f_review": ("review", 4, "session", "Friction review", "reads the log and the transcript, plans a change for each entry", ""),
    "f_hold": ("sclaude", 4, "hold", "Held", "an open review holds the next step", ""),
    "f_plan": ("person", 5, "user", "Approve its plan", "which file each change goes to", ""),
    "f_decide": ("review", 6, "gate", "Each entry: which kind?", "in the way, as intended, unsure, or a bug", ""),
    "f_bug": ("sclaude", 7, "task", "A bug in sclaude", "fixed in the workshop", "W"),
    "f_deliberate": ("review", 7, "task", "Left as it is", "explained; a recurring one gets a deny entry", ""),
    "f_lift": ("branch", 7, "task", "The product's rules", "policy allow or deny, CLAUDE.md, a step's prompt", ""),
    "f_defer": ("monthly", 7, "task", "A deferred row", "in the feature's own file, sent to main", ""),
    "f_verdict": ("sclaude", 8, "task", "Verdict recorded", "lifted, deliberate or mixed — in the issue", ""),
    "f_push": ("sclaude", 9, "task", "Pushed", "with the feature's PR; after the merge, a PR of its own", ""),
    "f_next": ("session", 10, "end", "The next session", "the next step, round or fix", ""),
    "f_monthly": ("monthly", 10, "session", "Monthly review", "sclaude deferred: every feature's rows, by class", ""),
}
FRICTION_EDGES = [
    ("f_trip", "f_log", "", "msg"),
    ("f_log", "f_empty", "the session ends", ""),
    ("f_empty", "f_none", "empty", ""),
    ("f_empty", "f_rules", "entries", ""),
    ("f_rules", "f_classify", "yes", "msg"),
    ("f_rules", "f_review", "no", ""),
    ("f_review", "f_hold", "interrupted", ""),
    ("f_hold", "f_review", "friction", "back"),
    ("f_review", "f_plan", "", ""),
    ("f_plan", "f_decide", "approved", ""),
    ("f_decide", "f_bug", "a bug", ""),
    ("f_decide", "f_deliberate", "as intended", ""),
    ("f_decide", "f_lift", "in the way", ""),
    ("f_decide", "f_defer", "unsure", ""),
    ("f_classify", "f_defer", "its rows", ""),
    ("f_bug", "f_verdict", "", ""),
    ("f_deliberate", "f_verdict", "", ""),
    ("f_lift", "f_verdict", "", ""),
    ("f_verdict", "f_push", "", ""),
    ("f_push", "f_next", "", ""),
    ("f_defer", "f_monthly", "once a month", ""),
]

# The feature's states, as the menu names them ("2/7 code").
STATE_LANES = [("dev", "In development"), ("wait", "Waiting on others"),
               ("after", "After the merge")]
STATE_NODES = {
    "s_plan": ("dev", 0, "task", "1/7 plan", "", ""),
    "s_code": ("dev", 1, "task", "2/7 code", "", ""),
    "s_pr": ("dev", 2, "task", "3/7 pr", "", ""),
    "s_review": ("dev", 3, "task", "4/7 review", "", ""),
    "s_sync": ("wait", 3, "task", "5/7 sync", "a sync broken off", ""),
    "s_preview": ("wait", 4, "task", "4/7 done", "preview, its regression", ""),
    "s_qa": ("wait", 5, "wait", "In QA", "QA has the issue", ""),
    "s_merge": ("wait", 6, "wait", "Waiting for merge", "the PR handed over", ""),
    "s_hold": ("after", 6, "hold", "Held", "production red", ""),
    "s_epilogue": ("after", 7, "task", "6/7 epilogue", "", ""),
    "s_retro": ("after", 8, "task", "7/7 retro", "clean-up next", ""),
    "s_done": ("after", 9, "end", "all done", "", ""),
}
STATE_EDGES = [
    ("s_plan", "s_code", "", ""), ("s_code", "s_pr", "", ""),
    ("s_pr", "s_review", "", ""), ("s_review", "s_preview", "", ""),
    ("s_preview", "s_sync", "conflict", "back"), ("s_sync", "s_preview", "", ""),
    ("s_preview", "s_qa", "green", ""), ("s_preview", "s_review", "red", "back"),
    ("s_qa", "s_merge", "Done", ""), ("s_qa", "s_review", "hand-back", "back"),
    ("s_merge", "s_epilogue", "merged", ""), ("s_merge", "s_hold", "prod red", ""),
    ("s_hold", "s_review", "rollback / return", "back"),
    ("s_epilogue", "s_retro", "", ""), ("s_retro", "s_pr", "retro fixed code", "back"),
    ("s_retro", "s_done", "", ""),
]

# Where a feature can stand (what `position` answers): the detailed node, and
# the overview's and the states' nodes lit with it.
POSITIONS = {
    "plan": ("o_plan", "s_plan"),
    "code": ("o_code", "s_code"),
    "reg_local": ("o_reg", "s_code"),
    "fix_local": ("o_reg", "s_code"),
    "pr": ("o_pr", "s_pr"),
    "review": ("o_review", "s_review"),
    "fix_preview": ("o_review", "s_review"),
    "fix_prod": ("o_review", "s_review"),
    "sync": ("o_sync", "s_sync"),
    "preview": ("o_preview", "s_preview"),
    "qa_check": ("o_qa", "s_qa"),
    "merge_wait": ("o_merge", "s_merge"),
    "hold_ways": ("o_prod", "s_hold"),
    "prod": ("o_prod", "s_merge"),
    "epilogue": ("o_epilogue", "s_epilogue"),
    "done_cmd": ("o_retro", "s_retro"),
    "cleanup": ("o_end", "s_retro"),
    "end": ("o_end", "s_done"),
}

# Commands: (command, verb in the action list or "", when it applies, what it
# does, the node it leads to or "").
COMMANDS = [
    ("sclaude", "", "always", "the menu: features in progress", ""),
    ("sclaude new [name]", "", "always", "a new feature at step 1", "new"),
    ("sclaude <name>", "resume", "always", "continue: the current step, or the end of the cycle", "@here"),
    ("sclaude status", "", "always", "a table of every feature and its step", ""),
    ("sclaude doctor", "", "always", "what this machine lacks, with the fix", ""),
    ("sclaude config", "", "always", "the project's config, explained; the review mode", ""),
    ("sclaude actions [name]", "", "always", "the action list of one feature", ""),
    ("sclaude dev [name]", "dev", "always", "start the dev server (--stop stops it)", "prepare"),
    ("sclaude sync <name>", "sync", "always", "merge origin/main in; a conflict opens the sync session", "merge_check"),
    ("sclaude replan <name>", "replan", "before the cycle ends", "back to step 1 in a new conversation; the code stays", "plan"),
    ("sclaude return <name> [reason]", "return", "a finished feature", "back to step 4 with what was said since", "review"),
    ("sclaude issue <name>", "issue", "always", "link or create the feature's issue", "new"),
    ("sclaude news <name>", "news", "with a pull request", "what moved on the PR since the last session", "review_found"),
    ("sclaude preview <name>", "preview", "after step 1", "deploy a preview of the branch", "preview"),
    ("sclaude rollback <name>", "rollback", "once production carried it", "the previous release back; a red one sends the fix to step 4", "rollback"),
    ("sclaude regression <name>", "regression", "always", "the local regression, the one steps 2 and 4 close on", "reg_local"),
    ("sclaude regression <name> prod", "regression-prod", "production red and carrying it", "production's suite again; green lifts the hold", "prod_ok"),
    ("sclaude friction <name>", "friction", "with friction logged", "review what the safety rules refused", "f_review"),
    ("sclaude done <name>", "done", "at step 4 or done", "the retro, then the clean-up after the merge", "done_cmd"),
    ("sclaude reset <name>", "reset", "before the cycle ends", "start the step over, forgetting its conversation", "@here"),
    ("sclaude drop <name>", "drop", "always", "abandon the feature, each trace asked about", ("cleanup", "end")),
    ("sclaude epilogue [name]", "", "an epilogue broken off", "write the status into the issue", "epilogue"),
    ("sclaude deferred", "", "monthly, offered", "the review of the friction put off", "f_monthly"),
    ("sclaude review-stats", "", "always", "what review sessions cost in context", "round"),
    ("sclaude review-report <name>", "", "with review rounds", "is the review still worth it", "round"),
    ("sclaude checks [pr]", "", "in a session", "wait for the checks of the pushed head", "review_close"),
    ("sclaude core-open", "", "in a session", "let the session write sclaude in its workshop", "w_open"),
    ("sclaude core-ready", "", "in a session", "mark the workshop's change ready to publish", "w_ready"),
    ("sclaude propose", "", "a developer's branch", "send dev/<name>'s commits to sclaude as a PR", "w_pr"),
]

def places(target):
    """A command's places: its target is one node, several (a tuple), "@here"
    or nothing."""
    if not target:
        return []
    return list(target) if isinstance(target, tuple) else [target]


# Verbs in the action list with no command of their own.
ACTION_ONLY = {"back", "nothing"}


def all_nodes():
    return {nid: n for _name, _lanes, nodes, _edges in node_sets() for nid, n in nodes.items()}


def node_sets():
    return [("detail", LANES, NODES, EDGES), ("overview", OVERVIEW_LANES, OVERVIEW_NODES, OVERVIEW_EDGES),
            ("states", STATE_LANES, STATE_NODES, STATE_EDGES),
            ("workshop", WORKSHOP_LANES, WORKSHOP_NODES, WORKSHOP_EDGES),
            ("friction", FRICTION_LANES, FRICTION_NODES, FRICTION_EDGES)]


# --- where a feature stands --------------------------------------------------

def _runs(node):
    return [r for r in ((node or {}).get("runs") or []) if isinstance(r, dict)]


def _fix_open(state, stage):
    words = (((state.get("regression") or {}).get(stage) or {}).get("fix_status") or "").split()
    return bool(words) and words[-1] == "open"


def _running(state, stage):
    run = (state.get("regression") or {}).get(stage) or {}
    if run.get("status") != "running":
        return False
    try:
        started = datetime.datetime.fromisoformat(run.get("started") or "")
    except ValueError:
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    return bool(started.tzinfo) and (now - started).total_seconds() < 3 * 3600


def prod_held(state):
    """As prod_red_hold's condition: production carries the feature and its
    last run there was not green, and it was not rolled back."""
    reg = (state.get("regression") or {}).get("prod") or {}
    shipped = ((state.get("deploy") or {}).get("prod") or {}).get("sha")
    rolled = ((state.get("rollback") or {}).get("prod") or {}).get("code") == "done"
    return bool(shipped) and not rolled and (reg.get("status") == "failed" or reg.get("unrunnable") is True)


def position(state, pr_state="", epilogue=None):
    """The detailed node a feature stands on, and a line saying why.

    pr_state is GitHub's word for the branch's pull request (OPEN, MERGED,
    CLOSED, or "" when it did not answer); epilogue the epilogue's own record
    (~/.claude/sclaude/epilogue/<feature>.json), when there is one."""
    step = state.get("step") or "plan"
    if step != "done":
        if step in ("code", "review") and _running(state, "local"):
            return "reg_local", "the local regression is running"
        if step == "code" and _fix_open(state, "local"):
            return "fix_local", "a session is fixing the local regression"
        if step == "review":
            for stage in ("prod", "preview"):
                if _fix_open(state, stage):
                    return "fix_" + stage, "a session is fixing the %s regression" % stage
            if _fix_open(state, "local"):
                return "fix_local", "a session is fixing the local regression"
        return (step if step in NODES else "plan"), "step %s" % step
    if state.get("no_change"):
        return "cleanup", "no change to the code: only the clean-up is left"
    if pr_state == "OPEN":
        runs = _runs(state.get("sync"))
        if runs and not runs[-1].get("done"):
            return "sync", "a sync with main is open"
        if _running(state, "preview"):
            return "preview", "the preview regression is running"
        qa = state.get("qa") or {}
        if state.get("handoff") or qa.get("accepted"):
            return "merge_wait", "QA accepted it; the pull request waits for the merge"
        if qa.get("sha"):
            return "qa_check", "the preview is with QA"
        return "preview", "next: the preview, then QA"
    if pr_state == "MERGED":
        # As remind_prod holds: only once the pull request is merged. A fix
        # going round on a pull request of its own is not held, though the
        # red run it answers stays recorded until the next ship.
        if prod_held(state):
            return "hold_ways", "production carries the feature, and its last run was not green"
        if _running(state, "prod"):
            return "prod", "the production regression is running"
        retro = _runs(state.get("retro"))
        if retro and retro[-1].get("done"):
            return "end", "the retrospective ran; only the clean-up may be left"
        epi = epilogue or {}
        if epi.get("session") and not epi.get("done"):
            return "epilogue", "the epilogue broke off"
        return "done_cmd", "merged: the retrospective and the clean-up are next"
    if pr_state == "CLOSED":
        return "cleanup", "the pull request was closed without a merge"
    return "preview", "past step 4; GitHub did not say where the pull request is"


# --- drawing -----------------------------------------------------------------

LANE_W = 246
NODE_W = 198
NODE_H = 78
ROW_H = 112
TOP = 52
CHANNEL = 10


def wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines


def esc(text):
    return html.escape(text, quote=True)


class Diagram:
    def __init__(self, name, lanes, nodes, edges):
        self.name, self.lanes, self.nodes, self.edges = name, lanes, nodes, edges
        self.rows = max(n[1] for n in nodes.values()) + 1
        self.lane_x = {lane: 0 for lane, _ in lanes}
        # Edges running down past a node in their way take a channel on the
        # left, as edges running back take one on the right.
        self.detours = [e for e in edges if not self.is_back(e) and self.blocked(e)]
        self.left = CHANNEL * (len(self.detours) + 1) if self.detours else 0
        self.lane_x = {lane: self.left + i * LANE_W for i, (lane, _) in enumerate(lanes)}
        backs = [e for e in edges if self.is_back(e)]
        self.right = self.left + len(lanes) * LANE_W
        self.width = self.right + CHANNEL * (len(backs) + 1) + 8
        self.height = TOP + self.rows * ROW_H + 16

    def center(self, nid):
        lane, row = self.nodes[nid][0], self.nodes[nid][1]
        return self.lane_x[lane] + LANE_W / 2, TOP + row * ROW_H + ROW_H / 2

    def is_back(self, edge):
        return self.nodes[edge[1]][1] < self.nodes[edge[0]][1]

    def blocked(self, edge):
        """Whether a node stands in the straight way down of an edge: in the
        source's lane below it, or in the target's above it."""
        (la, ra), (lb, rb) = self.nodes[edge[0]][:2], self.nodes[edge[1]][:2]
        if rb - ra < 2:
            return False
        for nid, n in self.nodes.items():
            if nid in edge[:2]:
                continue
            if n[0] == la and ra < n[1] < rb and la != lb:
                return True
            if n[0] == lb and (ra < n[1] < rb if la == lb else ra <= n[1] < rb):
                return True
        return False

    def shape(self, nid):
        lane, row, kind, title, text, flags = self.nodes[nid]
        cx, cy = self.center(nid)
        x, y, w, h = cx - NODE_W / 2, cy - NODE_H / 2, NODE_W, NODE_H
        out = ['<g class="node k-%s" data-node="%s" data-key="n:%s">' % (kind, nid, nid)]
        if kind in ("start", "end"):
            r = 13
            out.append('<circle class="shape" cx="%.1f" cy="%.1f" r="%d"/>' % (cx, y + r + 2, r))
            ty = y + 2 * r + 16
            out.append('<text class="t" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (cx, ty, esc(title)))
            for i, line in enumerate(wrap(text, 30)[:2]):
                out.append('<text class="s" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                           % (cx, ty + 14 + i * 13, esc(line)))
        else:
            if kind == "gate":
                d = 14
                pts = [(x, cy), (x + d, y), (x + w - d, y), (x + w, cy), (x + w - d, y + h), (x + d, y + h)]
                out.append('<polygon class="shape" points="%s"/>' % " ".join("%.1f,%.1f" % p for p in pts))
            else:
                out.append('<rect class="shape" x="%.1f" y="%.1f" width="%d" height="%d" rx="%d"/>'
                           % (x, y, w, h, 12 if kind != "hold" else 4))
                if kind == "wait":
                    out.append('<circle class="clock" cx="%.1f" cy="%.1f" r="7"/>' % (x + 12, y + 12))
            heads = wrap(title, 22 if kind == "gate" else 28)
            lines = wrap(text, 30 if kind == "gate" else 33)
            room = (4 if kind != "gate" else 3) - (len(heads) - 1)
            shown = min(len(lines), room)
            ty = cy - (len(heads) * 14 + shown * 12) / 2 + 10
            for i, line in enumerate(heads):
                out.append('<text class="t" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                           % (cx, ty + i * 14, esc(line)))
            ty += len(heads) * 14
            for i, line in enumerate(lines[:room]):
                last = i == room - 1 and len(lines) > room
                out.append('<text class="s" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                           % (cx, ty + i * 12 - 1, esc(line + (" …" if last else ""))))
        badge = x + w - 4
        for flag, word in (("F", "friction review after it"), ("W", "may change sclaude in its workshop")):
            if flag in flags:
                out.append('<g class="badge b-%s"><circle cx="%.1f" cy="%.1f" r="8"/>'
                           '<text x="%.1f" y="%.1f" text-anchor="middle">%s</text></g>'
                           % (flag, badge, y + 2, badge, y + 5.5, flag))
                badge -= 19
        out.append("</g>")
        return "\n".join(out)

    def edge(self, edge, index, back_index, detour_index=0, nth=0):
        a, b, label, kind = edge
        ax, ay = self.center(a)
        bx, by = self.center(b)
        ra, rb = self.nodes[a][1], self.nodes[b][1]
        half = NODE_H / 2
        lane_shift = (index % 5) * 3
        anchor = "start"
        if self.is_back(edge) or edge in self.detours:
            back = self.is_back(edge)
            cx = (self.right + CHANNEL * (back_index + 1) if back
                  else self.left - CHANNEL * (detour_index + 1))
            y1 = ay + half + 10 + lane_shift
            y2 = by - half - 12 - lane_shift
            pts = [(ax, ay + half), (ax, y1), (cx, y1), (cx, y2), (bx, y2), (bx, by - half)]
            # Several ways back from one node: their labels side by side.
            lx, ly = ax + 7 + nth * 78, y1 + (-3 if back else 11)
        elif ra == rb:
            side = 1 if bx > ax else -1
            dy = 9 if side > 0 else -9
            pts = [(ax + side * NODE_W / 2, ay + dy), (bx - side * NODE_W / 2, by + dy)]
            lx, ly, anchor = (ax + bx) / 2, (ay + dy - 4 if side < 0 else ay + dy + 13), "middle"
        else:
            gap = by - half - 14 - lane_shift
            if abs(ax - bx) < 1:
                pts = [(ax, ay + half), (bx, by - half)]
                lx, ly, anchor = ax - 6, ay + half + 12, "end"
            else:
                pts = [(ax, ay + half), (ax, gap), (bx, gap), (bx, by - half)]
                # By the arrow's end: several leaving one block would pile
                # their labels up at its foot.
                lx, ly, anchor = bx + 6, by - half - 4, "start"
        path = "M" + " L".join("%.1f %.1f" % p for p in pts)
        # A wide transparent twin under the line: something to point at.
        out = ['<g class="edge e-%s" data-key="e:%s:%d">' % (kind or "flow", self.name, index),
               '<path class="hit" d="%s"/>' % path,
               '<path class="line" d="%s" marker-end="url(#arrow-%s)"/>' % (path, self.name)]
        if label:
            out.append('<text class="el" x="%.1f" y="%.1f" text-anchor="%s">%s</text>'
                       % (lx, ly, anchor, esc(label)))
        out.append("</g>")
        return "\n".join(out)

    def body(self):
        parts = []
        if self.left:
            parts.append('<rect class="lane l-gutter" x="0" y="0" width="%d" height="%d"/>'
                         % (self.left, self.height))
        for i, (lane, title) in enumerate(self.lanes):
            x = self.lane_x[lane]
            parts.append('<rect class="lane l-%s%s" x="%d" y="0" width="%d" height="%d"/>'
                         % (lane, " alt" if i % 2 else "", x, LANE_W, self.height))
            parts.append('<text class="lt" x="%.1f" y="30" text-anchor="middle">%s</text>'
                         % (x + LANE_W / 2, esc(title)))
        parts.append('<line class="lh" x1="0" y1="%d" x2="%d" y2="%d"/>' % (TOP - 8, self.width, TOP - 8))
        back = detour = 0
        outgoing = {}
        for i, e in enumerate(self.edges):
            nth = 0
            if self.is_back(e) or e in self.detours:
                nth = outgoing.get(e[0], 0)
                outgoing[e[0]] = nth + 1
            parts.append(self.edge(e, i, back, detour, nth))
            if self.is_back(e):
                back += 1
            elif e in self.detours:
                detour += 1
        for nid in self.nodes:
            parts.append(self.shape(nid))
        return "\n".join(parts)

    def svg(self, symbol=False):
        defs = ('<defs><marker id="arrow-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" '
                'markerHeight="10" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="ah"/>'
                '</marker></defs>' % self.name)
        if symbol:
            return ('<svg class="defs" width="0" height="0" aria-hidden="true">%s<symbol id="sym-%s" '
                    'viewBox="0 0 %d %d">%s</symbol></svg>' % (defs, self.name, self.width, self.height, self.body()))
        # Never wider than drawn; narrower when the window is (the detailed
        # map scales down to fit rather than run off the screen).
        cap = ' style="max-width:%dpx"' % self.width if self.name == "detail" else ""
        return ('<svg class="map map-%s" viewBox="0 0 %d %d" width="%d" height="%d"%s '
                'role="img" aria-label="%s">%s%s</svg>'
                % (self.name, self.width, self.height, self.width, self.height, cap, esc(self.name),
                   defs, self.body()))


STYLE = """
:root{--paper:#EEF1F5;--surface:#FFFFFF;--ink:#131B2C;--muted:#586379;--line:#C9D1DE;
--signal:#C97A0A;--signal-soft:#FBEFD9;--auto:#0C7A6B;--auto-soft:#DDF1EC;--human:#C2452F;
--human-soft:#FBE4DE;--cloud:#2F57C9;--cloud-soft:#E2E9FB;--violet:#7A4CC2;--violet-soft:#EEE4FB;
--lane-a:#F7F9FC;--lane-b:#EFF3F8;--here:#E8A400;
--body:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
--paper:#0D1320;--surface:#161F31;--ink:#E7EBF2;--muted:#9AA5BA;--line:#33415E;--signal:#F0A93B;
--signal-soft:#3A2C14;--auto:#4CC7B4;--auto-soft:#11332F;--human:#F07F69;--human-soft:#3B1F1A;
--cloud:#86A4F5;--cloud-soft:#1A2647;--violet:#B89AF0;--violet-soft:#2A1F45;--lane-a:#121A2A;
--lane-b:#0F1624;--here:#FFC53D;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#0D1320;--surface:#161F31;--ink:#E7EBF2;--muted:#9AA5BA;--line:#33415E;
--signal:#F0A93B;--signal-soft:#3A2C14;--auto:#4CC7B4;--auto-soft:#11332F;--human:#F07F69;
--human-soft:#3B1F1A;--cloud:#86A4F5;--cloud-soft:#1A2647;--violet:#B89AF0;--violet-soft:#2A1F45;
--lane-a:#121A2A;--lane-b:#0F1624;--here:#FFC53D;color-scheme:dark}
*{box-sizing:border-box}
html,body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 var(--body)}
main{max-width:1760px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:36px 0 8px}
p.lead,.muted{color:var(--muted)}
code{font-family:var(--mono);font-size:.92em}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px;overflow-x:auto}
svg.map{display:block;width:100%;height:auto;min-width:760px}
.lane{stroke:var(--line);stroke-width:1}
.lane{fill:var(--lane-a)}.lane.alt{fill:var(--lane-b)}.l-gutter{fill:var(--surface);stroke:none}
svg.map-overview,svg.map-states,svg.map-workshop,svg.map-friction{max-width:1100px;margin:0 auto}
svg.map-detail{width:100%;height:auto;margin:0 auto}
.lt{font:600 14px var(--body);fill:var(--muted);letter-spacing:.02em}
.lh{stroke:var(--line)}
.node .shape{stroke-width:1.6;fill:var(--surface);stroke:var(--muted)}
.node .t{font:600 12.5px var(--body);fill:var(--ink)}
.node .s{font:11px var(--body);fill:var(--muted)}
.k-session .shape{fill:var(--violet-soft);stroke:var(--violet);stroke-width:2.2}
.k-task .shape{fill:var(--auto-soft);stroke:var(--auto)}
.k-gate .shape{fill:var(--signal-soft);stroke:var(--signal)}
.k-user .shape{fill:var(--human-soft);stroke:var(--human)}
.k-wait .shape{fill:var(--cloud-soft);stroke:var(--cloud);stroke-dasharray:5 3}
.k-wait .clock{fill:none;stroke:var(--cloud);stroke-width:1.4}
.k-hold .shape{fill:var(--human-soft);stroke:var(--human);stroke-width:2.4;stroke-dasharray:6 3}
.k-start .shape{fill:var(--auto-soft);stroke:var(--auto);stroke-width:2}
.k-end .shape{fill:var(--surface);stroke:var(--ink);stroke-width:4}
.badge circle{stroke:none}.badge text{font:700 10px var(--body);fill:#fff}
.b-F circle{fill:var(--signal)}.b-W circle{fill:var(--cloud)}
.edge path{fill:none;stroke:var(--muted);stroke-width:1.4}
.e-back path{stroke:var(--human);stroke-dasharray:6 4}
.e-msg path{stroke:var(--cloud);stroke-dasharray:2 3}
.ah{fill:var(--muted)}
.el{font:10.5px var(--body);fill:var(--muted);paint-order:stroke;stroke:var(--paper);stroke-width:4px;
stroke-linejoin:round}
.e-back .el{fill:var(--human)}
.node.here .shape{stroke:var(--here);stroke-width:5;filter:drop-shadow(0 0 8px var(--here))}
.node.here .t{fill:var(--ink)}
[data-key]{cursor:pointer}
.edge path.hit{fill:none;stroke:transparent!important;stroke-width:14;stroke-dasharray:none!important}
.map .node,.map .edge,tr[data-key],#acts li{transition:opacity .12s}
body.dimming svg.map .node:not(.is-focus):not(.is-lit),
body.dimming svg.map .edge:not(.is-focus):not(.is-lit),
body.dimming tr[data-key]:not(.is-focus):not(.is-lit),
body.dimming #acts li[data-key]:not(.is-focus):not(.is-lit),
body.dimming #dock li[data-key]:not(.is-focus):not(.is-lit){opacity:.18}
#dock{position:fixed;top:8px;right:6px;z-index:15;width:max-content;max-height:calc(100vh - 16px);overflow:auto;
font-size:clamp(9px,calc((100vh - 64px) / var(--n,29) / 1.5),12px);
background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:6px;
box-shadow:0 6px 20px rgba(0,0,0,.12)}
#dock .dock-head{display:flex;align-items:center;gap:4px;margin:0 2px 4px;font-size:13px}
#dock .pin{margin:0;padding:1px 5px}
#dock ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0}
#dock li{padding:1px 5px;border-radius:5px;line-height:1.35;transition:opacity .12s}
#dock li code{font-size:1em}
#dock li:hover{background:var(--lane-b)}
#dock li.is-focus{background:var(--signal-soft);box-shadow:inset 3px 0 0 var(--signal)}
#dock li.is-lit{background:var(--lane-b)}
#dock li.is-picked{box-shadow:inset 3px 0 0 var(--ink)}
.pin{font:500 12px var(--body);padding:3px 8px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer;vertical-align:middle;margin-left:8px}
body.pinned main{max-width:none;margin:0;padding-right:calc(var(--dockw,130px) + 14px)}
body.pinned #clear{right:calc(var(--dockw,130px) + 20px)}
body.dimming svg.map .node.here:not(.is-focus):not(.is-lit){opacity:.6}
.node.is-focus .shape{stroke-width:4.2;filter:saturate(1.5) drop-shadow(0 0 6px var(--cloud-soft))}
.node.is-lit .shape{stroke-width:2.8}
.node.is-picked .shape{stroke-dasharray:none}
.edge.is-focus path.line{stroke-width:3.4}
.edge.is-focus .el{font-weight:700;fill:var(--ink)}
.edge.e-back.is-focus .el{fill:var(--human)}
tr.is-focus td{background:var(--signal-soft)}tr.is-lit td{background:var(--lane-b)}
tr.is-picked td:first-child{box-shadow:inset 4px 0 0 var(--signal)}
#clear{position:fixed;right:20px;bottom:20px;z-index:20;border:0;border-radius:999px;padding:10px 16px;
font:600 14px var(--body);background:var(--ink);color:var(--paper);box-shadow:0 6px 20px rgba(0,0,0,.25);cursor:pointer}
#tip{position:fixed;z-index:30;max-width:340px;padding:10px 12px;border-radius:10px;background:var(--surface);
color:var(--ink);border:1px solid var(--line);box-shadow:0 8px 24px rgba(0,0,0,.18);font-size:13px;
line-height:1.4;pointer-events:none}
#tip p{margin:4px 0}#tip .spec{font:600 12px var(--mono);color:var(--violet);margin-top:2px}#tip .tk{color:var(--muted);font-size:12px}#tip i{color:var(--muted);font-style:normal}
.printbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;margin:6px 0 12px;font-size:14px}
.printbar select,.printbar button{font:inherit;padding:5px 8px;border-radius:8px;border:1px solid var(--line);
background:var(--surface);color:var(--ink)}
.printbar button{background:var(--ink);color:var(--paper);border-color:var(--ink);cursor:pointer}
.printbar p{flex-basis:100%;margin:0;font-size:13px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin:10px 0 0;padding:0;list-style:none;font-size:13px}
.legend li{display:flex;align-items:center;gap:6px}
.sw{width:22px;height:14px;border-radius:4px;border:2px solid}
table{border-collapse:collapse;width:100%;background:var(--surface);border-radius:12px;overflow:hidden}
th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line);font-size:13.5px}
th{background:var(--lane-b);font-weight:600}
td code{white-space:nowrap}
a{color:var(--cloud)}
.print-only{display:none}
@media print{
 html,body{background:#fff}
 main{max-width:none;padding:0}
 .card{border:0;padding:0;overflow:visible}
 .screen-only{display:none!important}.print-only{display:block}
 h2{break-before:page;margin-top:0}
 h2.first{break-before:auto}
 svg.map{min-width:0;max-height:180mm}
 .sheet{break-after:page;position:relative}
 .sheet:last-child{break-after:auto}
 .sheet svg{width:100%;height:auto;display:block}
 .sheet .mark{font:9px var(--body);color:#555;display:flex;justify-content:space-between}
 .cut line{stroke:#888;stroke-width:1;stroke-dasharray:4 4}
 table{break-inside:auto}tr{break-inside:avoid}
}
"""

LEGEND = """<ul class="legend">
<li><span class="sw" style="background:var(--violet-soft);border-color:var(--violet)"></span>a Claude session</li>
<li><span class="sw" style="background:var(--auto-soft);border-color:var(--auto)"></span>sclaude does it</li>
<li><span class="sw" style="background:var(--signal-soft);border-color:var(--signal)"></span>a check or a choice</li>
<li><span class="sw" style="background:var(--human-soft);border-color:var(--human)"></span>a person</li>
<li><span class="sw" style="background:var(--cloud-soft);border-color:var(--cloud);border-style:dashed"></span>waiting</li>
<li><svg width="34" height="10"><path d="M0 5 H34" stroke="var(--human)" stroke-dasharray="6 4" stroke-width="2"/></svg>goes back</li>
<li><svg width="34" height="10"><path d="M0 5 H34" stroke="var(--cloud)" stroke-dasharray="2 3" stroke-width="2"/></svg>a message to another lane</li>
<li><span class="sw" style="background:var(--signal);border-color:var(--signal);border-radius:50%;width:14px"></span>F — a friction review follows</li>
<li><span class="sw" style="background:var(--cloud);border-color:var(--cloud);border-radius:50%;width:14px"></span>W — may change sclaude in its workshop</li>
</ul>"""


# Where each command is open, by the words of its "When": the detailed nodes
# a feature may stand on when it shows. Hovering a node lights the commands
# open there.
def _rows(lo, hi):
    return [nid for nid, n in NODES.items() if lo <= n[1] <= hi]


WHEN = {
    "always": _rows(0, 35),
    "before the cycle ends": _rows(3, 15),
    "a finished feature": _rows(16, 35),
    "with a pull request": _rows(10, 35),
    "after step 1": _rows(6, 35),
    "once production carried it": _rows(27, 35) + ["hold_ways"],
    "production red and carrying it": ["hold", "hold_ways"],
    "with friction logged": [nid for nid, n in NODES.items() if "F" in n[5]],
    "at step 4 or done": _rows(11, 35),
    "an epilogue broken off": ["epilogue"],
    "monthly, offered": [],
    "in a session": [nid for nid, n in NODES.items() if n[2] == "session"],
    "with review rounds": ["review", "round"],
    "a developer's branch": [],
}

KIND_WORDS = {
    "start": "where the cycle begins", "end": "where it ends",
    "task": "sclaude does it, no model involved", "session": "the model works here",
    "gate": "a check or a choice: the way on depends on its answer",
    "user": "a person does it", "wait": "waiting for somebody else",
    "hold": "the cycle holds until a person acts",
}
EDGE_WORDS = {
    "": "the flow goes on", "back": "goes back: the work returns to an earlier place",
    "msg": "a message to another lane: one side tells the other", "cmd": "a command a person runs",
}
FLAG_WORDS = {"F": "a friction review follows the session",
              "W": "the session may change sclaude in its workshop"}


def client_model():
    """What the page's script needs to light and explain: every node and
    edge of the three maps, the commands, and the print sheets' geometry."""
    nodes, edges = {}, {}
    for name, lanes, set_nodes, set_edges in node_sets():
        lane_names = dict(lanes)
        for nid, (lane, _row, kind, title, text, flags) in set_nodes.items():
            base = ALIAS.get(nid, nid)
            spec = SPEC.get(base)
            nodes[nid] = {"t": title, "x": text, "lane": lane_names[lane],
                          "kind": KIND_WORDS.get(kind, kind),
                          "d": DETAILS.get(base, ""),
                          "spec": " · ".join(spec) if spec else "",
                          "flags": [FLAG_WORDS[f] for f in flags if f in FLAG_WORDS]}
        for i, (a, b, label, kind) in enumerate(set_edges):
            edges["%s:%d" % (name, i)] = {"f": a, "t": b, "l": label, "k": kind,
                                          "w": EDGE_WORDS.get(kind, "")}
    # The overview's and the states' blocks that stand for a detailed one:
    # a place lit on one map is lit on every map that has it.
    alias = {}
    for small, big in ALIAS.items():
        alias.setdefault(big, []).append(small)
    cmds = [{"c": cmd, "v": verb, "w": when, "x": what, "to": places(target),
             "at": WHEN.get(when, [])} for cmd, verb, when, what, target in COMMANDS]
    detail = Diagram(*node_sets()[0])
    sheets = {"w": detail.width, "h": detail.height,
              "cuts": sorted(set([detail.lane_x[lane] for lane, _ in detail.lanes] + [detail.width]))}
    return {"nodes": nodes, "edges": edges, "cmds": cmds, "sheets": sheets, "alias": alias,
            "base": dict(ALIAS)}


def tiles(diagram, page_w=1010, page_h=640, overlap=36):
    """The detailed map cut into sheets for print, each a window on the one
    drawing (a <use> of its symbol). Neighbouring sheets share a strip of
    `overlap` px: cut one along its dashed line and glue it over the next.
    The page's script cuts them again for the paper and scale chosen; these
    are A4 landscape at 100%, for a page printed with no script."""
    # Columns are cut between lanes, never through one.
    edges = sorted(set([diagram.lane_x[lane] for lane, _ in diagram.lanes] + [diagram.width]))
    starts, start = [], 0
    while True:
        starts.append(start)
        fits = [e for e in edges if start < e <= start + page_w]
        end = fits[-1] if fits else start + page_w
        if end >= diagram.width:
            break
        start = max(end - overlap, start + 1)
    cols = len(starts)
    rows = max(1, -(-(diagram.height - overlap) // (page_h - overlap)))
    out = []
    for r in range(rows):
        for c in range(cols):
            x, y = starts[c], r * (page_h - overlap)
            cuts = []
            if c < cols - 1:
                cut = starts[c + 1] + overlap
                cuts.append('<line x1="%d" y1="%d" x2="%d" y2="%d"/>' % (cut, y, cut, y + page_h))
            if r < rows - 1:
                cuts.append('<line x1="%d" y1="%d" x2="%d" y2="%d"/>'
                            % (x, y + page_h - overlap, x + page_w, y + page_h - overlap))
            glue = []
            if c < cols - 1:
                glue.append("right edge under sheet %d" % (r * cols + c + 2))
            if r < rows - 1:
                glue.append("bottom edge under sheet %d" % ((r + 1) * cols + c + 1))
            out.append(
                '<div class="sheet"><div class="mark"><span>Detailed process — sheet %d of %d '
                '(row %d, column %d)</span><span>%s</span></div>'
                '<svg viewBox="%d %d %d %d"><use href="#sym-%s" width="%d" height="%d"/>'
                '<g class="cut">%s</g></svg></div>'
                % (r * cols + c + 1, rows * cols, r + 1, c + 1,
                   ("glue the " + ", the ".join(glue) + "; the dashed line is the edge of the overlap")
                   if glue else "the last sheet",
                   x, y, page_w, page_h, diagram.name, diagram.width, diagram.height, "".join(cuts)))
    return '<div id="sheets" class="print-only">%s</div>' % "\n".join(out)


def short_command(cmd):
    """A command's name alone, for the pinned list: `sclaude sync <name>` is
    `sync`, `sclaude regression <name> prod` is `regression prod`."""
    words = [w for w in cmd.split()[1:] if not w.startswith(("<", "["))]
    if words:
        return " ".join(words)
    return "continue" if len(cmd.split()) > 1 else "menu"


def commands_dock():
    """The commands' names in a floating list beside the maps, pinned by
    default, so the map and the commands can be read together; they light
    and select as the table's rows do. Only those with a place on a map:
    the menu, the reports and the doctor are in the table alone."""
    shown = [(i, cmd) for i, (cmd, _v, _w, _x, target) in enumerate(COMMANDS) if target]
    items = "".join('<li data-key="c:%d"><code>%s</code></li>' % (i, esc(short_command(cmd)))
                    for i, cmd in shown)
    return ('<aside id="dock" class="screen-only" style="--n:%d" hidden><div class="dock-head"><b>Commands</b>'
            '<button type="button" class="pin" title="Unpin: the full list stays in section 6" aria-label="Unpin">📌</button>'
            '</div><ul>%s</ul></aside>' % (len(shown), items))


def commands_table():
    rows = []
    for i, (cmd, _verb, when, what, target) in enumerate(COMMANDS):
        lead = ", ".join("where the feature stands" if t == "@here" else esc(all_nodes()[t][3])
                         for t in places(target))
        rows.append('<tr data-key="c:%d"><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (i, esc(cmd), esc(when), esc(what), lead))
    return ('<table class="cmds"><thead><tr><th>Command</th><th>When</th><th>What it does</th>'
            '<th>Leads to</th></tr></thead><tbody>%s</tbody></table>' % "".join(rows))


# Hover and select, shared by the printed page and a feature's page.
#
# Everything with a data-key takes part: a node ("n:<id>"), an edge
# ("e:<map>:<n>"), a command ("c:<n>", a row of the table or an action of a
# feature's page). What is hovered and what is selected are lit together, a
# union: each lights itself and what it touches — a node its edges and their
# other ends, an edge its two ends, a command the place it leads to, and a
# node the commands open there or leading to it. While anything is lit, the
# rest fades. A click selects; Ctrl (or Cmd) adds to the selection or takes
# away; a click on the one thing selected, Esc or the floating button clears.
INTERACT_SCRIPT = r"""
const M = %(model)s;
const byNode = {};
Object.entries(M.edges).forEach(([k, e]) => {
  (byNode[e.f] = byNode[e.f] || []).push(k);
  (byNode[e.t] = byNode[e.t] || []).push(k);
});
const sel = new Set();
let hover = null;
const scope = (el) => !el.closest('svg.defs') && !el.closest('#sheets');
function parts(k) { const i = k.indexOf(':'); return [k.slice(0, i), k.slice(i + 1)]; }
function light(k, focus, lit) {
  const [t, id] = parts(k);
  focus.add(k);
  if (t === 'n') {
    (byNode[id] || []).forEach((e) => { focus.add('e:' + e); lit.add('n:' + M.edges[e].f); lit.add('n:' + M.edges[e].t); });
    const b = M.base[id] || id;
    M.cmds.forEach((c, i) => { if (c.to.includes(b) || c.at.includes(b)) lit.add('c:' + i); });
  } else if (t === 'e') {
    const e = M.edges[id];
    if (e) { focus.add('n:' + e.f); focus.add('n:' + e.t); }
  } else if (t === 'c') {
    const c = M.cmds[+id];
    (c ? c.to : []).filter((to) => to !== '@here').forEach((to) => {
      // The place on every map that has it.
      [to].concat(M.alias[to] || []).forEach((n) => {
        focus.add('n:' + n);
        (byNode[n] || []).forEach((e) => { if (M.edges[e].t === n) lit.add('e:' + e); });
      });
    });
  }
}
function paint() {
  const focus = new Set(), lit = new Set();
  sel.forEach((k) => light(k, focus, lit));
  if (hover) light(hover, focus, lit);
  document.body.classList.toggle('dimming', focus.size > 0);
  document.querySelectorAll('[data-key]').forEach((el) => {
    if (!scope(el)) return;
    const k = el.dataset.key;
    el.classList.toggle('is-focus', focus.has(k));
    el.classList.toggle('is-lit', !focus.has(k) && lit.has(k));
    el.classList.toggle('is-picked', sel.has(k));
  });
  const b = document.getElementById('clear');
  if (b) { b.hidden = sel.size === 0; b.textContent = 'Clear the selection (' + sel.size + ')'; }
}
function name(id) { const n = M.nodes[id]; return n ? n.t : id; }
function tipFor(k) {
  const [t, id] = parts(k);
  const h = (s) => s.replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
  if (t === 'n') {
    const n = M.nodes[id]; if (!n) return '';
    const cmds = M.cmds.filter((c) => c.to.includes(M.base[id] || id)).map((c) => c.c);
    return '<b>' + h(n.t) + '</b><div class="tk">' + h(n.lane) + ' · ' + h(n.kind) + '</div>'
      + (n.spec ? '<div class="spec">' + h(n.spec) + '</div>' : '')
      + '<p>' + h(n.d || n.x) + '</p>'
      + n.flags.map((f) => '<div class="tk">• ' + h(f) + '</div>').join('')
      + (cmds.length ? '<div><i>commands that lead here</i> ' + h(cmds.join(', ')) + '</div>' : '');
  }
  if (t === 'e') {
    const e = M.edges[id]; if (!e) return '';
    return '<b>' + h(name(e.f)) + ' → ' + h(name(e.t)) + '</b>'
      + (e.l ? '<p>' + h(e.l) + '</p>' : '') + '<div class="tk">' + h(e.w) + '</div>'
      + '<div><i>to</i> ' + h((M.nodes[e.t] || {}).x || '') + '</div>';
  }
  if (t === 'c') {
    const c = M.cmds[+id]; if (!c) return '';
    return '<b>' + h(c.c) + '</b><p>' + h(c.x) + '</p><div class="tk">when: ' + h(c.w) + '</div>'
      + (c.to.length ? '<div><i>leads to</i> ' + h(c.to.map((to) => to === '@here'
          ? 'where the feature stands' : name(to)).join(', ')) + '</div>' : '');
  }
  return '';
}
const tip = document.createElement('div');
tip.id = 'tip'; tip.hidden = true; document.body.append(tip);
document.addEventListener('mouseover', (ev) => {
  const el = ev.target.closest('[data-key]');
  const k = el && scope(el) ? el.dataset.key : null;
  if (k === hover) return;
  hover = k; paint();
  tip.innerHTML = k ? tipFor(k) : ''; tip.hidden = !tip.innerHTML;
});
document.addEventListener('mousemove', (ev) => {
  if (tip.hidden) return;
  const pad = 16, w = tip.offsetWidth, hh = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + hh > innerHeight - 8) y = ev.clientY - hh - pad;
  tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
});
document.addEventListener('click', (ev) => {
  if (ev.target.closest('#clear')) { sel.clear(); paint(); return; }
  const el = ev.target.closest('[data-key]');
  if (!el || !scope(el)) return;
  const k = el.dataset.key;
  if (ev.ctrlKey || ev.metaKey) { if (sel.has(k)) sel.delete(k); else sel.add(k); }
  else if (sel.size === 1 && sel.has(k)) sel.clear();
  else { sel.clear(); sel.add(k); }
  paint();
  // A command clicked brings the place it leads to into view, if it is not.
  const [t, id] = parts(k);
  const to = t === 'c' && M.cmds[+id] ? M.cmds[+id].to.filter((x) => x !== '@here')[0] : '';
  const n = to && document.querySelector('svg.map [data-key="n:' + to + '"]');
  if (n && sel.has(k)) {
    const r = n.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth)
      n.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'center'});
  }
});
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { sel.clear(); paint(); } });
window.processMap = {paint: paint, model: M};
"""

# The pinned commands: shown unless unpinned, a choice the browser keeps.
DOCK_SCRIPT = r"""
function dockWidth() {
  const d = document.getElementById('dock');
  if (!d.hidden) document.body.style.setProperty('--dockw', d.offsetWidth + 'px');
}
addEventListener('resize', dockWidth);
function pin(on) {
  document.getElementById('dock').hidden = !on;
  document.body.classList.toggle('pinned', on);
  dockWidth();
  document.querySelectorAll('.pin-head').forEach((b) => { b.textContent = on ? '📌 Unpin' : '📌 Pin'; });
  try { localStorage.setItem('process-pinned', on ? '1' : '0'); } catch (e) {}
}
let pinned = true;
try { pinned = localStorage.getItem('process-pinned') !== '0'; } catch (e) {}
document.querySelectorAll('.pin').forEach((b) => b.addEventListener('click', () =>
  pin(document.getElementById('dock').hidden)));
pin(pinned);
"""

# The printed page's own choice of paper and scale: the sheets are cut again
# for it, and @page is set to match. The page names the paper itself, so a
# browser's print dialog hides Layout and Paper size: they are chosen here.
PRINT_SCRIPT = r"""
const PAPER = {'a4-landscape': [297, 210, 'A4 landscape'], 'a4-portrait': [210, 297, 'A4 portrait'],
  'a3-landscape': [420, 297, 'A3 landscape'], 'a3-portrait': [297, 420, 'A3 portrait']};
const MARGIN = 9, TOP = 12, MARK = 6, OVERLAP = 36, PX = 96 / 25.4;
function cutSheets(paper, scale) {
  const [pw, ph] = PAPER[paper];
  const S = M.sheets;
  // "fit": the whole width on one sheet, the map going on down only.
  if (scale === 'fit') scale = Math.min(1, (pw - 2 * MARGIN) * PX / S.w);
  const w = Math.floor((pw - 2 * MARGIN) * PX / scale), h = Math.floor((ph - TOP - MARGIN - MARK) * PX / scale);
  const starts = []; let start = 0;
  for (;;) {
    starts.push(start);
    const fits = S.cuts.filter((e) => e > start && e <= start + w);
    const end = fits.length ? fits[fits.length - 1] : start + w;
    if (end >= S.w) break;
    start = Math.max(end - OVERLAP, start + 1);
  }
  const cols = starts.length, rows = Math.max(1, Math.ceil((S.h - OVERLAP) / (h - OVERLAP)));
  let out = '';
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = starts[c], y = r * (h - OVERLAP), n = r * cols + c + 1;
    let cuts = '';
    const glue = [];
    if (c < cols - 1) { const cx = starts[c + 1] + OVERLAP;
      cuts += '<line x1="' + cx + '" y1="' + y + '" x2="' + cx + '" y2="' + (y + h) + '"/>';
      glue.push('right edge under sheet ' + (n + 1)); }
    if (r < rows - 1) { cuts += '<line x1="' + x + '" y1="' + (y + h - OVERLAP) + '" x2="' + (x + w) + '" y2="' + (y + h - OVERLAP) + '"/>';
      glue.push('bottom edge under sheet ' + (n + cols)); }
    out += '<div class="sheet"><div class="mark"><span>Detailed process — sheet ' + n + ' of ' + rows * cols
      + ' (row ' + (r + 1) + ', column ' + (c + 1) + ')</span><span>'
      + (glue.length ? 'glue the ' + glue.join(', the ') + '; the dashed line is the edge of the overlap' : 'the last sheet')
      + '</span></div><svg viewBox="' + x + ' ' + y + ' ' + w + ' ' + h + '"><use href="#sym-detail" width="'
      + S.w + '" height="' + S.h + '"/><g class="cut">' + cuts + '</g></svg></div>';
  }
  document.getElementById('sheets').innerHTML = out;
  // A deeper top margin: the running header names the section there.
  document.getElementById('pagesize').textContent = '@page{size:' + PAPER[paper][2] + ';margin:' + TOP + 'mm '
    + MARGIN + 'mm ' + MARGIN + 'mm}';
  return rows * cols;
}
function choosePrint() {
  const paper = document.getElementById('paper').value, chosen = document.getElementById('scale').value;
  const scale = chosen === 'fit' ? 'fit' : +chosen;
  const n = cutSheets(paper, scale);
  document.getElementById('count').textContent = n + (n === 1 ? ' sheet' : ' sheets') + ' for the whole process, plus '
    + 'a page each for the overview and the states, and the commands';
  try { localStorage.setItem('process-print', JSON.stringify([paper, scale])); } catch (e) {}
}
try { const saved = JSON.parse(localStorage.getItem('process-print') || 'null');
  if (saved) { document.getElementById('paper').value = saved[0]; document.getElementById('scale').value = saved[1]; } } catch (e) {}
document.getElementById('paper').onchange = choosePrint;
document.getElementById('scale').onchange = choosePrint;
document.getElementById('print').onclick = () => window.print();
choosePrint();
"""

PRINT_BAR = """<div class="printbar screen-only">
<label>Paper <select id="paper"><option value="a4-landscape">A4 landscape</option>
<option value="a4-portrait">A4 portrait</option><option value="a3-landscape">A3 landscape</option>
<option value="a3-portrait">A3 portrait</option></select></label>
<label>Scale <select id="scale"><option value="1">100% — as on screen</option>
<option value="fit">Fit the width — one column of sheets</option><option value="0.85">85%</option>
<option value="0.7">70%</option><option value="0.55">55%</option></select></label>
<button id="print" type="button">Print…</button>
<span class="muted" id="count"></span>
<p class="muted">Recommended: <b>A4 landscape at 100%</b> — the text is as large as on screen and the sheet
is cut between lanes, so each lane stays whole on one sheet; <b>A3 landscape</b>, if a printer takes it, or
<b>70%</b> on A4 need fewer sheets (the count is beside the button), 70% with smaller text. Choose the paper and the scale here: the
page names its paper, so the browser's dialog has no Layout or Paper size, and its own Scale (under More settings)
would only shrink each sheet without making fewer of them. Leave the dialog's margins at Default.</p>
</div>"""


# The printed page's sections, in order: each is a named page (`page: sN`)
# whose running header names it, so a loose sheet says where it belongs.
SECTIONS = ["1. The cycle at a glance", "2. A feature's states", "3. The whole process",
            "4. How a session changes sclaude", "5. The friction review",
            "6. Commands and where they lead"]


def running_heads():
    css = ['@page{@top-right{content:"sclaude — the process";font:9px sans-serif;color:#666}'
           '@bottom-right{content:"page " counter(page);font:9px sans-serif;color:#666}}']
    for n, title in enumerate(SECTIONS, start=1):
        # A CSS string, not JSON: json's \\uXXXX would print as "uXXXX".
        css.append('@page s%d{@top-left{content:"%s";font:600 10px sans-serif;color:#333}}'
                   % (n, title.replace("\\", "\\\\").replace('"', '\\"')))
    return "\n".join(css)


def doc():
    detail = Diagram(*node_sets()[0])
    overview = Diagram(*node_sets()[1])
    states = Diagram(*node_sets()[2])
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sclaude Process Map</title>
<style>%s
%s</style><style id="pagesize">@page{size:A4 landscape;margin:12mm 9mm 9mm}</style></head><body><main>
<section style="page:s1">
<h1>sclaude — the process</h1>
<p class="lead">The feature cycle as BPMN: who does what, in which order, and every way back.
Drawn from <code>sclaude/lib/process.py</code>, which tests check against the code; a feature's own copy,
with where it stands lit and its actions, is at <code>http://localhost:3000/__sclaude/flow?f=&lt;feature&gt;</code>.</p>
%s
<p class="muted screen-only">Point at a block, an arrow or a command to see what it is and what it touches;
click to keep it lit, Ctrl-click to add more, Esc to clear.</p>
<h2 class="first">%s</h2>
<div class="card">%s</div>
</section><section style="page:s2">
<h2>%s</h2>
<p class="muted">What the menu and the issue's summary say a feature is at.</p>
<div class="card">%s</div>
</section><section style="page:s3">
<h2>%s</h2>
<p class="muted">Every lane, every check and every way back.</p>
%s
<div class="card screen-only">%s</div>
%s
%s
</section><section style="page:s4">
<h2>%s</h2>
<p class="muted">Any session marked W may take this way: it changes sclaude in its tree's workshop, and sclaude
publishes the change once the session ends.</p>
<div class="card">%s</div>
</section><section style="page:s5">
<h2>%s</h2>
<p class="muted">Every session marked F leads here once it ends: what the safety rules refused it is read by a
session of its own, which lifts a rule, leaves it, puts it off a month, or fixes sclaude.</p>
<div class="card">%s</div>
</section><section style="page:s6">
<h2>%s <button type="button" class="pin pin-head screen-only">📌 Pin</button></h2>
<p class="muted">A feature's action list shows only those that apply to it now. A command lights the place it
leads to; a block lights the commands open there.</p>
%s
</section>
<button id="clear" class="screen-only" type="button" hidden>Clear the selection</button>
%s
</main><script>%s%s%s</script></body></html>
""" % (STYLE, running_heads(), LEGEND, esc(SECTIONS[0]), overview.svg(), esc(SECTIONS[1]), states.svg(),
       esc(SECTIONS[2]), PRINT_BAR, detail.svg(), detail.svg(symbol=True), tiles(detail),
       esc(SECTIONS[3]), Diagram(*node_sets()[3]).svg(), esc(SECTIONS[4]), Diagram(*node_sets()[4]).svg(),
       esc(SECTIONS[5]), commands_table(),
       commands_dock(), INTERACT_SCRIPT % {"model": json.dumps(client_model())}, PRINT_SCRIPT, DOCK_SCRIPT)


# --- a feature's page --------------------------------------------------------

LIVE_SCRIPT = r"""
const label = %(label)s;
const POS = %(positions)s;
let last = '';
function render(v) {
  document.getElementById('where').textContent = v.where || '—';
  document.getElementById('why').textContent = v.why || '';
  document.getElementById('stamp').textContent = 'updated ' + new Date().toLocaleTimeString();
  const here = v.node || '';
  document.querySelectorAll('.node.here').forEach((n) => n.classList.remove('here'));
  if (here) {
    [here].concat(POS[here] || []).forEach((id) =>
      document.querySelectorAll('svg.map [data-node="' + id + '"]').forEach((n) => n.classList.add('here')));
  }
  if (here && here !== last) {
    const n = document.querySelector('svg.map-detail [data-node="' + here + '"]');
    if (n && last === '') n.scrollIntoView({block: 'center', inline: 'center'});
    last = here;
  }
  const ul = document.getElementById('acts');
  ul.textContent = '';
  (v.actions || []).forEach((a) => {
    const li = document.createElement('li');
    const i = M.cmds.findIndex((c) => c.v === a.verb);
    if (i >= 0) li.dataset.key = 'c:' + i;
    const head = document.createElement('div');
    head.className = 'an';
    head.textContent = a.label;
    li.append(head);
    if (a.hint) { const h = document.createElement('div'); h.className = 'ah2'; h.textContent = a.hint; li.append(h); }
    if (i >= 0) {
      const c = document.createElement('code');
      c.textContent = M.cmds[i].c.replace('<name>', v.feature || label).replace('[name]', v.feature || label);
      li.append(c);
      const to = M.cmds[i].to.map((x) => x === '@here' ? here : x).filter(Boolean);
      if (to.length) {
        const g = document.createElement('div');
        g.className = 'leads';
        g.textContent = '→ ' + to.map((x) => (M.nodes[x] || {}).t || x).join(', ');
        li.append(g);
      }
    }
    ul.append(li);
  });
  window.processMap.paint();
  document.getElementById('err').textContent = v.error || '';
}
function poll() {
  fetch('/__sclaude/flow/state?f=' + encodeURIComponent(label), {cache: 'no-store'})
    .then((r) => r.ok ? r.json() : Promise.reject(r.status))
    .then(render)
    .catch((e) => { document.getElementById('err').textContent = 'sclaude did not answer (' + e + ')'; })
    .finally(() => setTimeout(poll, document.hidden ? 60000 : 15000));
}
poll();
"""

LIVE_STYLE = """
.live{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px;align-items:start}
.panel{position:sticky;top:12px;background:var(--surface);border:1px solid var(--line);border-radius:14px;
padding:14px;max-height:calc(100vh - 24px);overflow:auto}
.panel h3{margin:14px 0 6px;font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
#where{font-size:20px;font-weight:700}
#acts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
#acts li{border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:var(--lane-a);cursor:pointer}
#acts li:hover{border-color:var(--cloud)}
#acts li.is-focus{border-color:var(--cloud);border-width:2px;background:var(--cloud-soft)}
.an{font-weight:600}.ah2{color:var(--muted);font-size:13px}
#acts code{display:block;margin-top:4px;font-size:12px;color:var(--ink)}
.leads{color:var(--cloud);font-size:13px;margin-top:2px}
#err{color:var(--human)}
.mini{margin-top:12px}
.mini svg.map{min-width:0}
.detail-card{max-height:calc(100vh - 120px);overflow:auto}
.detail-card svg.map{width:auto;max-width:none}
@media (max-width:900px){.live{grid-template-columns:1fr}.panel{position:static;max-height:none}}
"""


def page(label):
    """A feature's map: the same drawing, with its place lit and its actions,
    kept current by polling /__sclaude/flow/state."""
    detail = Diagram(*node_sets()[0])
    overview = Diagram(*node_sets()[1])
    states = Diagram(*node_sets()[2])
    script = LIVE_SCRIPT % {
        "label": json.dumps(label),
        "positions": json.dumps({k: list(v) for k, v in POSITIONS.items()}),
    }
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s — sclaude map</title>
<style>%s%s</style></head><body><main>
<p class="muted"><a href="/__sclaude/">features</a> · <a href="/__sclaude/select?f=%s">open the feature</a></p>
<h1>%s</h1>
%s
<div class="live" style="margin-top:14px">
<div>
<div class="card detail-card">%s</div>
<h2>The cycle at a glance</h2><div class="card mini">%s</div>
<h2>States</h2><div class="card mini">%s</div>
<h2>How a session changes sclaude</h2><div class="card mini">%s</div>
<h2>The friction review</h2><div class="card mini">%s</div>
<h2>Every command</h2>%s
</div>
<aside class="panel">
<div class="muted" id="stamp">…</div>
<h3>Where it stands</h3><div id="where">…</div><div class="muted" id="why"></div>
<h3>What you can do now</h3><ul id="acts"></ul>
<p id="err"></p>
</aside>
</div>
<button id="clear" type="button" hidden>Clear the selection</button>
</main><script>%s%s</script></body></html>
""" % (esc(label), STYLE, LIVE_STYLE, esc(label), esc(label), LEGEND, detail.svg(), overview.svg(),
       states.svg(), Diagram(*node_sets()[3]).svg(), Diagram(*node_sets()[4]).svg(), commands_table(),
       INTERACT_SCRIPT % {"model": json.dumps(client_model())}, script)


# --- the command line --------------------------------------------------------

def main(argv):
    if len(argv) >= 2 and argv[0] == "doc":
        with open(argv[1], "w") as fh:
            fh.write(doc())
        print(argv[1])
        return 0
    if len(argv) >= 2 and argv[0] == "position":
        try:
            with open(argv[1]) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        epilogue = None
        if len(argv) >= 4 and argv[3] and os.path.isfile(argv[3]):
            try:
                with open(argv[3]) as fh:
                    epilogue = json.load(fh)
            except (OSError, ValueError):
                epilogue = None
        node, why = position(state, argv[2] if len(argv) >= 3 else "", epilogue)
        print("%s\t%s\t%s" % (node, NODES[node][3], why))
        return 0
    if len(argv) >= 2 and argv[0] == "page":
        sys.stdout.write(page(argv[1]))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
