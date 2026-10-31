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
lane and a row; an edge running down turns in the gap under its block, one
running back up goes round by a channel on the right and one with a node in
its way by one on the left — on the right, inside the ways back, between
lanes right of the middle — so no line crosses a node. The ways round by a
channel into one block share it, a trunk: one carries it in, the others
join it with a small arrow, a chevron on the trunk past each. The arrows follow
three rules: out — on each side of a block the
way reaching farthest leaves from that side's corner along its row, the
others from below, each turning on its own level right under the block,
the farthest first, labelled there; in — several ways into a block enter
its top apart, in the order they come from, the ways back nested; the
channels — nested by how far they go, each turning above its target's row
by how near its channel is (Diagram.corners, levels, entries). Each gap
between rows is as tall as what runs in it, and where nothing turns in it
the lower row rises into the upper one's height (Diagram._rows). Vertical lanes keep the width to a page's, and the length is what
splits across pages.

    process.py doc <out.html>
    process.py position <state.json> [pr-state] [epilogue.json]
    process.py history <state.json> [node]   the feature's way, for its page to play
    process.py page <label>              a feature's page shell, for a check
"""

import contextlib
import datetime
import html
import json
import os
import sys
import time

# --- the model ---------------------------------------------------------------

# Lanes of the detailed map, left to right.
LANES = [
    ("person", "You"),
    ("qa", "QA"),
    ("sclaude", "sclaude"),
    ("session", "Claude session"),
    ("github", "GitHub"),
]

# A node: id -> (lane, row, kind, title, text, flags).
# kind: start, end, task, session, gate, wait, hold, user.
# flags: "F" a friction review follows the session; "W" it may change sclaude
# in its tree's workshop itself — its prompt carries <block:workshop>: the
# retrospective; a step's findings reach sclaude through its friction review.
NODES = {
    # start
    "new": ("person", 0, "start", "sclaude new",
            "choose an issue, or type a name", ""),
    "prepare": ("sclaude", 1, "task", "Prepare the feature",
                "worktree from origin/main, branch feat/<slug>, its own dev server and database", ""),
    "board_start": ("github", 1, "task", "Issue taken",
                    "Backlog → In progress, Start date", ""),
    # step 1
    "plan": ("session", 3, "session", "1 · plan",
             "the issue, its parents and the manuals; scope first, then a plan with acceptance criteria", "FS"),
    "approve": ("person", 4, "user", "Correct and approve",
                "the scope, then the plan with its criteria", ""),
    "plan_check": ("sclaude", 5, "gate", "Plan read back?",
                   "the approved text found in the transcript", ""),
    "ac": ("github", 5, "task", "Criteria on the issue",
           "a comment of their own, AC1, AC2, …", ""),
    # step 2
    "code": ("session", 6, "session", "2 · code",
             "builds it, checks it in Chrome, commits with Requirement: ACn", "FRS"),
    "works": ("person", 7, "gate", "Does it work?",
              "your yes; a no goes back with what is wrong", ""),
    # step 3
    "pr": ("session", 9, "session", "3 · pr",
           "manuals updated, a draft PR by the pr skill, the criteria for QA", "FS"),
    "pr_check": ("sclaude", 10, "gate", "PR there, all pushed?",
                 "a pull request on GitHub carrying every commit", ""),
    "draft_pr": ("github", 10, "task", "Draft PR",
                 "assigned to its author, in the issue's milestone", ""),
    "ci_review": ("github", 11, "task", "Review on CI",
                  "the project's review workflow reads each push; sclaude waits for its check", ""),
    # step 4
    "local_pass": ("session", 11, "task", "Local review passes",
                   "review: local — read-only passes; findings posted on the PR", "S"),
    "review_found": ("sclaude", 12, "gate", "Anything to answer?",
                     "findings, comments, red checks; none — no session at all", ""),
    "review": ("session", 13, "session", "4 · review",
               "fixes the findings through subagents, pushes, one round, stops", "FRS"),
    "round": ("sclaude", 14, "gate", "Round closed: context under 40%?",
              "yes — the same session takes the new findings; no — a fresh one", ""),
    "review_close": ("sclaude", 15, "gate", "Nothing open, local regression green?",
                     "no thread, no red or running check; then step 4 is done", "R"),
    # end of the cycle
    "preview": ("sclaude", 17, "task", "Preview",
                "deployed (three tries), the preview regression run against it", "RS"),
    # The QA watch is folded in: a timer of its own lane, it only watched.
    "in_qa": ("github", 19, "task", "Issue → In QA",
              "the preview is what QA looks at; a timer watches the column", ""),
    "qa_check": ("qa", 20, "user", "QA checks the criteria",
                 "on the preview, ticking them in the issue", ""),
    "qa_verdict": ("qa", 21, "gate", "Done, or back?",
                   "Done — on to the merge; In progress — a hand-back", ""),
    "handoff": ("sclaude", 22, "task", "PR handed over",
                "ready for review, Backlog, a summary for whoever merges", "S"),
    "merge": ("person", 23, "gate", "Merge?",
              "offered, or done by sclaude when the project says merge: auto", ""),
    "merge_wait": ("sclaude", 23, "wait", "Waiting for the merge",
                   "polls every 30 s; main checked every 2 min", "S"),
    "merged": ("github", 24, "task", "Merged",
               "Target date; PR → Done; the issue held open to the end", ""),
    "ship": ("person", 25, "gate", "Ship to production?",
             "asked after the merge", ""),
    "prod": ("sclaude", 26, "task", "Production",
             "the promote of migrations, vercel --prod, the production regression", "R"),
    # The same status session where the run stops at a red preview, drawn
    # beside it rather than reached across the map.
    "epi_preview": ("session", 17, "session", "6 · epilogue", "the status: preview red, or green after red", ""),
    "epilogue": ("session", 29, "session", "6 · epilogue",
                 "Current status on the issue and every parent; deployed-* labels", ""),
    "done_cmd": ("sclaude", 30, "task", "sclaude done",
                 "called by the run after the epilogue; by hand later", ""),
    "friction_left": ("session", 31, "session", "Friction check",
                      "always: every friction review still owed runs here", "F"),
    "retro": ("session", 32, "session", "7 · retro",
              "what was missed, what could work better, what sclaude could do better", "W"),
    "retro_fix": ("sclaude", 33, "gate", "The retro changed the code?",
                  "yes — its commits go out from step 3", ""),
    "cleanup": ("person", 34, "gate", "Clean up?",
                "remove the worktree, branches, database; the record stays", ""),
    "end": ("sclaude", 35, "end", "Done", "", ""),
    "kept": ("person", 35, "end", "Kept", "later: sclaude done <name>", ""),
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
    "retro": ("opus", "medium", "plan"),
    "local_pass": ("opus", "default", "read-only, claude -p"),
    "f_review": ("opus", "medium", "plan"),
    "f_monthly": ("opus", "medium", "plan"),
    "f_classify": ("haiku", "default", "claude -p, no tools"),
}

# What each block does, at more length than fits on it: the note under the
# pointer. The overview's blocks borrow these (ALIAS).
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
    "pr": "Updates the manuals the change touches and opens a draft pull request through the pr skill, with the criteria copied in as a plain list (QA ticks them in the issue) and Closes #N for the issue.",
    "pr_check": "sclaude looks for the pull request on GitHub and for commits it does not carry. Missing either: the session is sent back to finish, at most twice.",
    "draft_pr": "The draft is assigned to its author and put in the issue's milestone. Who reviews it is the project's review setting.",
    "ci_review": "With review set to github, the project's review workflow in Actions reviews the pull request on every push and posts its findings as threads. sclaude waits for its check before step 4 opens a session, and each round's next findings come from its run on the round's push.",
    "local_pass": "With review set to local, read-only claude -p passes review the pull request here and post their findings as threads signed by this machine. A key in the terminal or in the topic ends the search; another, in the terminal, lets the review go on by itself, past the questions after it — a box of three states going round auto → on → off: auto follows the project's sleep_mode (on, off, or by default an /isleep night over every session, not an /isleep here one).",
    "review_found": "Findings, unresolved threads, comments and red checks are gathered before any session. Nothing to answer: step 4 closes with no session at all.",
    "review": "The session fixes the findings through subagents, keeping only the coordination, pushes, and stops once the automatic review has confirmed the fixes and posted the next round. While it works in its own tab, the terminal takes the review's boxes, [s] and [g].",
    "round": "A watcher ends the session when the round closes. Under 40% context the same conversation takes the new findings; above it a fresh one does, after the round's friction review. Rounds that stop converging are said once.",
    "review_close": "Leaving step 4 closes it only when nothing is open — no unresolved thread, no running or red check — and the local regression is green again. Otherwise sclaude waits, says what is open, and offers the session back. With [g] on it asks nothing: what is open goes back to a session by itself (30 rounds a step 4, then it asks), a pass that did not run is tried again ten times with growing pauses, and after the search ended the fixes are checked.",
    "hold_ways": "Production carries this feature and its regression there was not green, with nothing rolled back: the rollback failed or was refused, another release landed on top and the repeated run was red too, or the suite could not run in a broken environment (a project with no production suite or address is not held). A red run made by hand lands here as well. Every later pass of sclaude <name> checks this first and stops on it, so nothing is shipped, closed or cleaned up. The ways out: sclaude regression <name> prod runs production's suite again, and green goes on to the epilogue; sclaude rollback puts the previous release back and sends the fix to step 4; sclaude return fixes forward from step 4.",
    "merge_check": "git merge-tree tells in memory whether the branch merges cleanly with main — no session, no GitHub call. Asked before the preview, after QA's yes, and every two minutes while waiting for the merge.",
    "sync": "Merges origin/main into the branch (never a rebase), resolves each conflict keeping both sides' intent, checks the result as the project's CLAUDE.md says and pushes. sclaude then checks it settled; a pull request handed over goes back to a draft.",
    "preview": "Deploys the worktree to a preview from the main repository (up to three tries), applies the branch's migrations there, and runs the preview regression against the deployment. An unchanged tree already green is not deployed again. A deploy that fails three times goes to the fixing session as a red run does — the command that failed named — and deploys again; after two such sessions it is yours.",
    "preview_ok": "Green: the issue goes to In QA. Red: no label is claimed, the cycle goes back to step 4 and a fixing session opens there.",
    "fix_preview": "A fixing session in step 4, where the pull request is open and pushes reach the branch, with the failing run's log. The fix goes the whole way round again.",
    "in_qa": "The issue moves to In QA only after the preview's tests passed, so the column says something true. The QA watch starts: a systemd timer looks at the issue's column every few minutes and tells the feature's topic; it hands the pull request over when QA says Done, even with nobody at the terminal. It changes nothing else.",
    "qa_check": "QA opens the preview, checks each acceptance criterion and ticks it in the issue's comment. Nothing ticks a box but a person, unless the project's qa setting says so.",
    "qa_verdict": "Done goes on to the merge. In progress or Backlog is a hand-back: everything said since on the issue and the pull request is collected word for word and opens step 4 with it.",
    "handoff": "The draft is marked ready, moved to Backlog, its assignees cleared, and a summary for whoever merges is posted: the preview, QA's verdict, the criteria, the review's findings, the checks.",
    "merge": "The merge is yours unless the project's config says merge: auto. sclaude offers it once QA passed, GitHub says the way is clear and the pull request, merged with the newer main, builds and passes its checks; declined, or that check red, it waits.",
    "merge_wait": "Polls GitHub every 30 seconds for the merge and checks every two minutes whether main moved into a conflict. Ctrl-C leaves the wait and loses nothing.",
    "merged": "sclaude fills Target date with today so the roadmap's bar ends when the work did, and moves the pull request to Done. GitHub closes the issue by Closes #N, and sclaude reopens it: it closes it itself when the cycle ends — shipped once production is green, declined after a no to production.",
    "ship": "Asked once the merge is in. The deployment production runs now is recorded first, for a rollback. A no closes the issue as declined and goes on to the epilogue; shipping later is vercel --prod from the repository.",
    "prod": "The project's promote of migrations if the branch has any, then vercel --prod from the main repository, then the production regression against production. A ship that fails reopens step 4 at once, its session told which command failed; production's suite runs first when the promote began, since the old code may stand on the new migrations.",
    "prod_ok": "Green: deployed-prod is labelled, the issue closes and the cycle goes on. Red: production is rolled back before anything is fixed. A red that is not rolled back holds the cycle: when the rollback fails or is refused, when another release landed on top during the run and the repeated run is red too, and when the suite could not run in a broken environment.",
    "rollback": "vercel rollback to the recorded deployment, the migrations' down blocks only when every one is runnable, a check that the old release serves, and an incident comment on the issue.",
    "fix_prod": "Opens in step 4 with the failing run's log, told that production runs the previous release and that the local suite is the check that matters. The fix goes round again: local, merge, preview, production.",
    "epilogue": "A short session writes a Current status comment on the issue and on every parent up the chain, and Current behaviour where the product now differs from a description. Labels deployed-preview and deployed-prod are set by how each stage ended.",
    "done_cmd": "Called by the run itself once production is settled, with no question of its own; by hand from the menu or the terminal later, after a no to the clean-up. It checks the merge with GitHub, runs the retrospective, then asks once before removing anything.",
    "friction_left": "Before the retrospective, always, as a safety net — with nothing owed it is a check that passes at once: every friction review still owed — one held while [g] ran step 4's rounds, one cut off and never finished, a log with entries no review read. The retrospective reads the logs and the clean-up removes them, so this is their last reader; with nobody at the terminal the retrospective and the clean-up wait for it.",
    "retro": "Reads the plan, the friction logs and the terminal's record of the cycle: what you may have missed, how the work could go better, what sclaude could do better. It may fix sclaude in its workshop.",
    "retro_fix": "Commits the retrospective made on the feature's branch go out the way the feature's own did: back to step 3 for their pull request and the review.",
    "cleanup": "Shows what would go and asks once: Remove all of it? Yes appends the cycle's record to ~/.claude/sclaude/cycles.jsonl and removes the worktree, the branches and the feature's database; no keeps all of it.",
    "kept": "A no to the clean-up keeps everything: the worktree, the branches, the database. sclaude done <name> asks again.",
    "end": "The feature is done: merged, shipped or postponed, its outcome written into the issues. sclaude drop ends it here too, from any step: the worktree, the branches, the pull request and the issue (closed as not planned), each asked about.",
    "f_trip": "During any step or fixing session, a hook refuses a command, a rule of --disallowed-tools fires, Claude Code's auto-mode classifier refuses, or the session itself notes what got in its way, or proposes a rule for the project's CLAUDE.md.",
    "f_log": "The hooks append each refusal to .sclaude/local/feature/friction.log as it happens: the time, the step, the source, the subject, the reason. The classifier's refusals leave no event, so they are gathered from the transcript once the session ends.",
    "f_empty": "Asked after every step's session, every review round that goes to a fresh session, every sync with main and every fixing session. An empty log needs no session: the issue's Friction column says nothing for it — the ordinary case.",
    "f_none": "Nothing got in the session's way that a rule refused: the cycle goes straight on.",
    "f_rules": "A log of nothing but proposed CLAUDE.md rules needs no session: they are put off to the monthly review, where how often a class comes back decides it. With SCLAUDE_FRICTION_ASK=on you are asked first, and now hands them to a review told to write them in.",
    "f_classify": "One call of a small model reads the proposals, the classes already put off and CLAUDE.md, and says of each: the same as a class already there, a rule CLAUDE.md already states, or new. Checked, not trusted; a failure leaves the rows as they came.",
    "f_review": "A session in plan mode, in the feature's tree, reads this session's entries and its transcript and decides each one. It may change the product's rules on the feature's branch, and sclaude itself in the workshop. It ends with a verdict line.",
    "f_away": "With [g] ticked in step 4 the review goes on by itself, and a friction review would stop it waiting for its plan's approval. So the log is kept, every later session's entries added to it, and the first friction review after the box comes off reads them all — at the latest the one sclaude done runs before the retrospective, which waits for it.",
    "f_hold": "A review interrupted, or one that never started, stays open: after a step's session, a review round or a sync the run waits until sclaude friction finishes it or sclaude reset closes it; after a fixing session the stage goes on, and the next review waits for it.",
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
    "w_find": "The retrospective, a friction review or the monthly review finds something to fix in sclaude itself. A step's session does not change sclaude: it logs what got in its way, and its friction review brings it here. sclaude's live checkout is read-only to all of them.",
    "w_ask": "The retrospective and the friction and monthly reviews start in plan mode: the plan you approve, with the change to sclaude in it, is the yes, and sclaude core-open opens without a question.",
    "w_open": "Makes the tree's workshop, a worktree of sclaude from origin/main at .sclaude/local/instruments, shared by every session of the tree, and lets this session write there.",
    "w_change": "The session commits in the workshop and reviews its change: /sreview for a maintainer of sclaude, whatever review they choose for anybody else.",
    "w_ready": "Refuses uncommitted work and records the head as ready; for a maintainer it wants sreview's mark of a finished run at that head.",
    "w_exit": "Publishing starts from claude_launch once the session exits, whatever step it was in.",
    "w_ready_gate": "A change uncommitted, unreviewed at its head or never marked ready is not published.",
    "w_pending": "The change waits in the workshop: it is offered again whenever the tree is opened, and later sessions' changes wait behind it.",
    "w_held": "A no to the product's details keeps the change unpublished at the head it was shown; it goes on once a new commit is marked ready.",
    "w_back": "The same conversation is offered back, told what is missing. A no records it as pending: it is offered again when the feature is next opened, and later sessions' changes wait behind it.",
    "w_leaks": "sclaude is public and the product is not: the added lines and the commit messages are searched for the product's repository and folder names, the feature's slug and branch, issue and pull-request numbers, and paths of the product's own files.",
    "w_leak_ask": "A hit is shown to you, in the terminal and in the topic when it is short. A yes is kept for the lines it was shown; a no holds the change at its head until a new commit is marked ready.",
    "w_tests": "The tests the change touches run in a clean environment, each in a session of its own with no terminal. Red tests, no network, a refused push or a conflict with main stop the publication; it is tried again whenever the tree is opened.",
    "w_who": "MAINTAINERS lists who may commit sclaude's core straight to main; with no file everybody is a maintainer.",
    "w_main": "Rebased onto origin/main, squashed into one commit, pushed to main; the live checkout is fast-forwarded when nothing runs from it, so the next session runs the fix.",
    "w_pr": "Pushed unsquashed to the workshop's own dev/<name>-<time> branch, never named after the feature, as one pull request per tree; the maintainer's review of it is the gate.",
}
# The epilogue's copies beside the stops are its session.
DETAILS["epi_preview"] = DETAILS["epilogue"]
ALIAS = {
    "o_new": "new", "o_plan": "plan", "o_approve": "approve", "o_code": "code", "o_works": "works",
    "o_pr": "pr", "o_review": "review", "o_ghreview": "draft_pr",
    "o_preview": "preview", "o_qa": "qa_check", "o_merge": "merge", "o_prod": "prod",
    "o_epilogue": "epilogue", "o_epi_preview": "epi_preview", "o_retro": "retro", "o_end": "cleanup",
}

# An edge: (from, to, label, kind). kind: "" the flow, "back" a return, "msg"
# a message between lanes, "cmd" a command a person runs.
EDGES = [
    ("new", "prepare", "", ""),
    ("prepare", "board_start", "", "msg"),
    ("prepare", "plan", "", ""),
    ("plan", "approve", "", ""),
    # Your corrections go back into the plan's session, until you approve.
    ("approve", "plan", "corrections", "back"),
    ("approve", "plan_check", "approved", ""),
    ("plan_check", "plan", "not found — sent back (≤2)", "back"),
    ("plan_check", "ac", "", "msg"),
    ("plan_check", "code", "yes", ""),
    ("code", "works", "", ""),
    ("works", "code", "no — what is wrong", "back"),
    ("works", "pr", "yes", ""),
    ("pr", "pr_check", "", ""),
    ("pr_check", "pr", "no — sent back (≤2)", "back"),
    ("pr_check", "draft_pr", "", "msg"),
    ("draft_pr", "ci_review", "", ""),
    ("draft_pr", "local_pass", "", ""),
    ("draft_pr", "review_found", "", ""),
    ("ci_review", "review_found", "", ""),
    ("local_pass", "review_found", "", ""),
    ("review_found", "review", "yes", ""),
    ("review_found", "review_close", "nothing — step closes", ""),
    ("review", "round", "", ""),
    ("round", "review", "next round", "back"),
    ("round", "review_close", "session left", ""),
    ("review_close", "review", "no", "back"),
    ("review_close", "preview", "yes", ""),
    ("preview", "in_qa", "green", "msg"),
    ("preview", "review", "red, or the deploy failed: fixed from step 4", "back"),
    ("in_qa", "qa_check", "", ""),
    ("qa_check", "qa_verdict", "", ""),
    ("qa_verdict", "review", "hand-back: their words open step 4", "back"),
    ("qa_verdict", "handoff", "Done (main checked again)", ""),
    ("handoff", "merge", "", ""),
    ("merge", "merged", "yes", ""),
    ("merge", "merge_wait", "not now", ""),
    ("merge_wait", "merged", "merged on GitHub", ""),
    # The branch moved — a sync after a conflict with main, or commits from
    # elsewhere — and the run starts over on the new code (remind_prod).
    ("handoff", "preview", "the branch moved", "back"),
    ("merge_wait", "preview", "the branch moved", "back"),
    ("merged", "ship", "", ""),
    # Where the run stops at a red preview and has the issue's status written
    # (run_status in remind_prod), and where it goes green after a red status
    # and has it written again: the epilogue's session, drawn beside it.
    ("preview", "epi_preview", "red; green after red", "msg"),
    ("ship", "prod", "yes", ""),
    # One way each into the epilogue: the status is written there for the
    # production block's stops too — main not ready (asked after the yes),
    # production red (whose fix goes back to step 4 by its own way).
    ("ship", "epilogue", "no", ""),
    ("prod", "epilogue", "green, red, or main not ready", ""),
    ("prod", "review", "red: rolled back, or held; the ship failed", "back"),
    ("epilogue", "done_cmd", "", ""),
    ("done_cmd", "friction_left", "", ""),
    ("friction_left", "retro", "", ""),
    ("retro", "retro_fix", "", ""),
    ("retro_fix", "pr", "yes — step 3 again", "back"),
    ("retro_fix", "cleanup", "no", ""),
    ("cleanup", "end", "yes", ""), ("cleanup", "kept", "no", ""),
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
    "o_pr": ("session", 4, "session", "3 · pr", "manuals, draft PR", "F"),
    "o_review": ("session", 5, "session", "4 · review", "round after round", "F"),
    "o_ghreview": ("github", 5, "task", "Automatic review", "findings on the PR", ""),
    # The sync with main is no block of its own: it runs ahead of most of
    # them, and S on each says so (SYNC_NODES has its map). QA's and the
    # merge's are their own: the sync there is sclaude's, after QA's yes and
    # during the wait, not the person's.
    "o_preview": ("sclaude", 6, "gate", "Preview", "deployed and tested", ""),
    "o_qa": ("person", 7, "gate", "QA", "Done or back", "S"),
    "o_merge": ("person", 8, "user", "Merge", "yours, or auto", "S"),
    "o_prod": ("sclaude", 9, "gate", "Production", "shipped on your yes, tested; red, not rolled back: held here", ""),
    "o_epi_preview": ("session", 6, "session", "6 · epilogue", "the status: red, or green after red", ""),
    "o_epilogue": ("session", 10, "session", "6 · epilogue", "status up the issue chain", ""),
    "o_retro": ("session", 11, "session", "7 · retro", "lessons, sclaude's fixes", ""),
    "o_end": ("sclaude", 12, "end", "Clean-up", "", ""),
}
OVERVIEW_EDGES = [
    ("o_new", "o_plan", "", ""), ("o_plan", "o_approve", "", ""),
    # Your corrections go back to the plan's session, until you approve.
    ("o_approve", "o_plan", "corrections", "back"),
    ("o_approve", "o_code", "approved", ""), ("o_code", "o_works", "", ""),
    ("o_works", "o_pr", "yes", ""), ("o_works", "o_code", "no", "back"),
    ("o_pr", "o_ghreview", "", "msg"),
    ("o_ghreview", "o_review", "findings", "msg"),
    # A round: the session pushes its fixes, the review reads the push and
    # brings the next findings — until sclaude finds nothing open.
    ("o_review", "o_ghreview", "push", "msg"),
    ("o_review", "o_preview", "nothing open, tests green", ""),
    ("o_preview", "o_qa", "green", ""),
    ("o_preview", "o_review", "red, or the deploy failed", "back"),
    ("o_preview", "o_epi_preview", "red; green after red", "msg"),
    ("o_qa", "o_review", "back", "back"), ("o_qa", "o_merge", "Done", ""),
    # A sync after QA's yes or during the merge's wait changes the code QA
    # passed: the preview, its regression and QA again.
    ("o_qa", "o_preview", "the branch moved", "back"),
    ("o_merge", "o_preview", "the branch moved", "back"),
    ("o_merge", "o_prod", "", ""),
    # Held, production stays where it is, waiting on the person: no way out.
    ("o_prod", "o_review", "red, rolled back; or the ship failed", "back"),
    # The ship is asked here (ship): a no goes on as a green run does.
    ("o_prod", "o_epilogue", "green, red, or not shipped", ""), ("o_epilogue", "o_retro", "", ""),
    ("o_retro", "o_pr", "it fixed code", "back"), ("o_retro", "o_end", "", ""),
]

# How a session changes sclaude itself: in its tree's workshop, published by
# sclaude once the session ends (sclaude/lib/workshop.sh). Any session with W
# on the maps may take this way.
WORKSHOP_LANES = [("person", "You"), ("sclaude", "sclaude"), ("session", "Claude session"),
                  ("github", "GitHub")]
WORKSHOP_NODES = {
    "w_find": ("session", 0, "start", "A fix for sclaude", "found by the retro or a review", ""),
    "w_ask": ("person", 1, "user", "The plan you approve", "the retro's or a review's, the change in it", ""),
    "w_open": ("session", 2, "session", "sclaude core-open", "opens the tree's workshop for this session", ""),
    "w_change": ("session", 3, "session", "Commit and review", "in the workshop; sreview for a maintainer", ""),
    "w_ready": ("session", 4, "session", "sclaude core-ready", "the head marked ready to publish", ""),
    "w_exit": ("session", 5, "session", "The session ends", "publishing begins", ""),
    "w_ready_gate": ("sclaude", 6, "gate", "Finished at its head?", "committed, reviewed, marked ready", ""),
    "w_back": ("person", 6, "gate", "Back to the session?", "told what is missing; no keeps it pending", ""),
    "w_pending": ("session", 7, "end", "Pending", "offered again when the tree is next opened", ""),
    "w_leaks": ("sclaude", 7, "gate", "The product's details in it?", "names, numbers, paths of the product", ""),
    "w_leak_ask": ("person", 7, "gate", "Publish anyway?", "a no holds the change at its head", ""),
    "w_held": ("person", 8, "end", "Held at its head", "until a new commit is marked ready", ""),
    "w_tests": ("sclaude", 8, "task", "The tests it touches", "a clean environment, no terminal; red — tried again later", ""),
    "w_who": ("sclaude", 9, "gate", "A maintainer?", "MAINTAINERS", ""),
    "w_main": ("github", 9, "task", "Pushed to main", "one squashed commit; the live checkout updated", ""),
    "w_pr": ("github", 10, "task", "A pull request", "from dev/<name>-<time>, one per tree", ""),
}
WORKSHOP_EDGES = [
    ("w_find", "w_ask", "", ""),
    ("w_ask", "w_open", "approved", ""),
    ("w_open", "w_change", "", ""),
    ("w_change", "w_ready", "", ""),
    ("w_ready", "w_exit", "", ""),
    ("w_exit", "w_ready_gate", "", ""),
    ("w_ready_gate", "w_back", "no", ""),
    ("w_back", "w_change", "yes — same conversation", "back"),
    ("w_back", "w_pending", "no", ""),
    ("w_ready_gate", "w_leaks", "yes", ""),
    ("w_leaks", "w_leak_ask", "a hit", ""),
    ("w_leak_ask", "w_tests", "yes", ""),
    ("w_leak_ask", "w_held", "no", ""),
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
    "f_empty": ("sclaude", 2, "gate", "Anything logged?", "after every step, round, sync and fix session", ""),
    "f_none": ("session", 2, "end", "No review", "the ordinary case", ""),
    "f_rules": ("sclaude", 3, "gate", "Only proposed rules?", "rules for the project's CLAUDE.md, nothing else", ""),
    "f_classify": ("monthly", 3, "task", "Matched, no session", "a small model names each one's class", ""),
    "f_review": ("review", 4, "session", "Friction review", "reads the log and the transcript, plans a change for each entry", "W"),
    "f_away": ("sclaude", 5, "hold", "Kept for you", "[g] ticked: read before the retro at the latest", ""),
    "f_hold": ("sclaude", 4, "hold", "Held", "an open review holds the next step", ""),
    "f_plan": ("person", 5, "user", "Approve its plan", "which file each change goes to", ""),
    "f_decide": ("review", 6, "gate", "Each entry: which kind?", "in the way, as intended, unsure, or a bug", ""),
    "f_bug": ("review", 8, "task", "A bug in sclaude", "the review fixes it in the workshop", ""),
    "f_deliberate": ("review", 7, "task", "Left as it is", "explained; a recurring one gets a deny entry", ""),
    "f_lift": ("branch", 7, "task", "The product's rules", "policy allow or deny, CLAUDE.md, a step's prompt", ""),
    "f_defer": ("monthly", 7, "task", "A deferred row", "in the feature's own file, sent to main", ""),
    "f_verdict": ("sclaude", 8, "task", "Verdict recorded", "lifted, deliberate or mixed — in the issue", ""),
    "f_push": ("sclaude", 9, "task", "Pushed", "with the feature's PR; after the merge, a PR of its own", ""),
    "f_next": ("session", 10, "end", "The next session", "the next step, round or fix", ""),
    "f_monthly": ("monthly", 10, "session", "Monthly review", "sclaude deferred: every feature's rows, by class", "W"),
}
FRICTION_EDGES = [
    ("f_trip", "f_log", "", "msg"),
    ("f_log", "f_empty", "the session ends", ""),
    ("f_empty", "f_none", "empty", ""),
    ("f_empty", "f_rules", "entries", ""),
    ("f_rules", "f_classify", "yes", "msg"),
    ("f_rules", "f_review", "no", ""),
    ("f_rules", "f_away", "no, [g] in step 4", ""),
    ("f_away", "f_review", "the box off, or before the retro", "back"),
    ("f_review", "f_hold", "cut off", ""),
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

# A stage's regression, out of the detailed map: there an R marks where one
# runs. The local suite closes steps 2 and 4, the preview's comes before QA,
# production's after the ship (regression.sh, deploy.sh).
REGRESSION_LANES = [("person", "You"), ("sclaude", "sclaude"), ("session", "Claude session")]
REGRESSION_NODES = {
    "r_local": ("sclaude", 0, "start", "Local suite", "after step 2's yes, and as step 4 closes", ""),
    "reg_local": ('sclaude', 1, 'gate', 'Local regression green?',
        "the project's suite against the feature's server", ''),
    "fix_local": ('session', 1, 'session', 'Fix after regression',
        'makes the red tests green — two sessions at most, then it stops for you', 'F'),
    "r_stop": ("person", 2, "hold", "Stopped for you", "two fixing sessions and still red", ""),
    "r_preview": ("sclaude", 3, "start", "Preview suite", "against the preview, before QA", ""),
    "preview_ok": ('sclaude', 4, 'gate', 'Preview green?',
        'red — the fix goes on from step 4', ''),
    "fix_preview": ('session', 4, 'session', 'Fix after preview',
        "makes the preview's tests green, from step 4", 'F'),
    "r_prod": ("sclaude", 5, "start", "Production suite", "against production, after the ship", ""),
    "prod_ok": ('sclaude', 6, 'gate', 'Production green?',
        'red — rolled back before anything is fixed, or held', ''),
    "rollback": ('sclaude', 7, 'task', 'Rollback',
        'the previous deployment, the down blocks, a check, the incident on the issue', ''),
    "hold_ways": ('person', 7, 'hold', 'Held',
        'production red and not rolled back: regression <name> prod · rollback · return', ''),
    "fix_prod": ('session', 8, 'session', 'Fix after production',
        'told what failed and that production runs the old release', 'F'),
    "r_step4": ("session", 9, "end", "Step 4 reopened", "the fix goes the whole way round", ""),
    "r_on": ("sclaude", 9, "end", "The cycle goes on", "", ""),
}
REGRESSION_EDGES = [
    ("r_local", "reg_local", "", ""),
    ("reg_local", "fix_local", "red", ""),
    ("fix_local", "reg_local", "again", "back"),
    ("reg_local", "r_stop", "red after two", ""),
    ("r_stop", "reg_local", "sclaude regression", "back"),
    ("reg_local", "r_on", "green", ""),
    ("r_preview", "preview_ok", "", ""),
    ("preview_ok", "fix_preview", "red", ""),
    ("fix_preview", "r_step4", "", ""),
    ("preview_ok", "r_on", "green", ""),
    ("r_prod", "prod_ok", "", ""),
    ("prod_ok", "rollback", "red", ""),
    ("prod_ok", "hold_ways", "red, not rolled back", ""),
    ("rollback", "hold_ways", "failed", ""),
    ("hold_ways", "rollback", "rollback", ""),
    ("rollback", "fix_prod", "", ""),
    ("fix_prod", "r_step4", "", ""),
    ("hold_ways", "r_on", "regression prod: green", ""),
    ("hold_ways", "r_step4", "return", ""),
    ("prod_ok", "r_on", "green", ""),
]

# Main and the branch, out of the detailed map: there an S marks where main
# is checked (worktree.sh before each step, deploy.sh before the preview and
# during the merge wait, sync.sh).
SYNC_LANES = [("sclaude", "sclaude"), ("session", "Claude session")]
SYNC_NODES = {
    "y_when": ("sclaude", 0, "start", "Main checked",
               "before each step and the preview, after QA, every 2 min while the merge waits", ""),
    "merge_check": ('sclaude', 1, 'gate', 'Merges with main?',
        'git merge-tree, no session; before the preview, after QA, while waiting', ''),
    "main_in": ('sclaude', 2, 'task', 'Main merged in',
        "at a step's start, without asking; elsewhere a clean check changes nothing", ''),
    "y_stop": ("session", 3, "end", "The run stops",
               "not settled: sclaude <feature> takes it up", ""),
    "sync": ('session', 2, 'session', '5 · sync',
        'merges origin/main in, resolves the conflicts, checks, pushes', 'F'),
    "y_on": ("sclaude", 3, "end", "The cycle goes on", "", ""),
}
SYNC_EDGES = [
    ("y_when", "merge_check", "", ""),
    ("merge_check", "main_in", "clean", ""),
    ("merge_check", "sync", "conflict", ""),
    ("sync", "merge_check", "settled", "back"),
    ("sync", "y_stop", "not settled", ""),
    ("main_in", "y_on", "", ""),
]

# Where a feature can stand (what `position` answers): the detailed node, and
# the overview's block lit with it.
POSITIONS = {
    "plan": "o_plan",
    "code": "o_code",
    "reg_local": "o_code",
    "fix_local": "o_code",
    "pr": "o_pr",
    "review": "o_review",
    "fix_preview": "o_review",
    "fix_prod": "o_review",
    "handoff": "o_qa",
    "preview": "o_preview",
    "qa_check": "o_qa",
    "merge_wait": "o_merge",
    "hold_ways": "o_prod",
    "prod": "o_prod",
    "ship": "o_prod",
    "local_pass": "o_review",
    "epilogue": "o_epilogue",
    "done_cmd": "o_retro",
    "friction_left": "o_retro",
    "retro": "o_retro",
    "cleanup": "o_end",
    "end": "o_end",
}

# --- the map a project's config draws ---------------------------------------
#
# A project's map shows its own cycle, not every one sclaude can run: the
# review on CI or on this machine, QA on a board or none, a merge by a
# person or by sclaude. The model above holds them all; for_config takes out
# what a config does not run (NEEDS), carries the flow past a block taken
# out (PASS), and puts in the words a setting changes (VARIANTS). A block or
# an arrow not in NEEDS is on every project's map.

# A block, or an arrow by (from, to), and the setting it needs: (name,
# values). An arrow named here is not carried past a block taken out — it
# is one way of a choice, and the choice drops it.
NEEDS = {
    "ci_review": ("review", {"github"}),
    "local_pass": ("review", {"local"}),
    ("draft_pr", "ci_review"): ("review", {"github"}),
    ("draft_pr", "local_pass"): ("review", {"local"}),
    "f_away": ("review", {"local"}),
    ("f_rules", "f_away"): ("review", {"local"}),
    ("f_away", "f_review"): ("review", {"local"}),
    ("draft_pr", "review_found"): ("review", {"off"}),
    "r_local": ("regression.local", {True}),
    "r_stop": ("regression.local", {True}),
    "r_preview": ("regression.preview", {True}),
    "r_prod": ("regression.prod", {True}),
    # A badge by (block, letter): R only where that stage has a suite.
    ("code", "R"): ("regression.local", {True}),
    ("review", "R"): ("regression.local", {True}),
    ("review_close", "R"): ("regression.local", {True}),
    ("preview", "R"): ("regression.preview", {True}),
    ("prod", "R"): ("regression.prod", {True}),
    "reg_local": ("regression.local", {True}),
    "fix_local": ("regression.local", {True}),
    "preview_ok": ("regression.preview", {True}),
    "fix_preview": ("regression.preview", {True}),
    "prod_ok": ("regression.prod", {True}),
    "rollback": ("regression.prod", {True}),
    "fix_prod": ("regression.prod", {True}),
    "hold_ways": ("regression.prod", {True}),
    "in_qa": ("board.qa", {True}),
    "qa_check": ("board.done", {True}),
    "qa_verdict": ("board.done", {True}),
    "merge": ("merge", {"both", "auto"}),
    "o_ghreview": ("review", {"github", "local"}),
    "o_qa": ("board.done", {True}),
}

# Where the flow goes on when a block is taken out: an arrow into it is
# carried to this one, and on down the chain while that one is out too.
PASS = {
    "ci_review": "review_found", "local_pass": "review_found",
    "reg_local": "pr", "preview_ok": "in_qa", "in_qa": "qa_check",
    "qa_check": "qa_verdict", "qa_verdict": "handoff", "prod_ok": "epilogue",
    "merge": "merge_wait",
    "o_ghreview": "o_review", "o_qa": "o_merge",
}

# The words, and for a few the lane, a setting changes: block -> [(name,
# values, {field: value})], the first that matches taken. Fields: lane,
# row, kind, title, text, details. A block moved to another lane takes a row
# of its own there when the one it had is taken.
VARIANTS = {
    "merge": [("merge", {"auto"}, {
        "lane": "sclaude", "row": 22.5, "title": "Merged by sclaude",
        "text": "merge: auto — once QA passed and GitHub says the way is clear",
        "details": "With merge set to auto, sclaude merges the pull request itself once QA passed and GitHub says the way is clear; a red check of the merge with main holds it until the branch or main moves."}),
              ("merge", {"both"}, {"text": "offered here once QA passed, or merge it on GitHub"})],
    "merge_wait": [("merge", {"github"}, {
        "text": "merge it on GitHub; polled every 30 s, main checked every 2 min"})],
    "qa_check": [("qa", {"auto"}, {
        "lane": "sclaude", "title": "Accepted by sclaude",
        "text": "qa: auto — moved to Done once the preview regression is green",
        "details": "With qa set to auto, sclaude moves the issue to Done itself once the preview regression is green; a person can still hand it back from the board."}),
                 ("qa", {"both"}, {
        "text": "on the preview, ticking them in the issue — or a key in sclaude's wait"})],
    "prepare": [("database.local", {False}, {
        "text": "worktree from origin/main, branch feat/<slug>, its own dev server"})],
    "prod": [("database.promote", {False}, {
        "text": "vercel --prod, then the production regression"})],
    "o_ghreview": [("review", {"local"}, {
        "lane": "sclaude", "title": "Local review", "text": "passes on this machine"})],
    "o_qa": [("qa", {"auto"}, {"lane": "sclaude", "title": "QA: auto", "text": "accepted when the preview is green"})],
    "o_prod": [("regression.prod", {False}, {"kind": "task", "text": "shipped on your yes"})],
    "o_preview": [("regression.preview", {False}, {"kind": "task", "text": "deployed"})],
    "o_merge": [("merge", {"auto"}, {"lane": "sclaude", "text": "by sclaude: merge auto"}),
                ("merge", {"github"}, {"text": "yours, on GitHub"})],
}


def setting(cfg, name):
    """A setting the map depends on, read as sclaude reads it
    (project_review_mode, project_flow_mode, project_regression_parts, the
    board's columns in project.sh)."""
    cfg = cfg or {}
    if name == "review":
        return cfg.get("review") if cfg.get("review") in ("local", "off") else "github"
    if name in ("qa", "merge"):
        mode = cfg.get(name)
        return mode if mode in ("github", "both", "auto") else ("both" if name == "merge" else "github")
    if name.startswith("regression."):
        return bool((cfg.get("regression") or {}).get(name.split(".", 1)[1]))
    if name in ("board.qa", "board.done"):
        # done is what QA is waited for by (qa_wait); qa only where the issue
        # is moved to before it (issue_qa_ready).
        columns = (cfg.get("board") or {}).get("columns") or {}
        return bool(columns.get("done") and (name == "board.done" or columns.get("qa")))
    if name.startswith("database."):
        return bool((cfg.get("database") or {}).get(name.split(".", 1)[1]))
    return None


def _needs(cfg, key):
    need = NEEDS.get(key)
    return not need or setting(cfg, need[0]) in need[1]


def for_config(cfg, nodes, edges):
    """One map as cfg runs it: the blocks it needs, the arrows carried past
    the ones it does not, the words it changes; rows left empty closed up."""
    kept = {}
    for nid, node in nodes.items():
        if not _needs(cfg, nid):
            continue
        lane, row, kind, title, text, flags = node
        for name, values, fields in VARIANTS.get(nid, []):
            if setting(cfg, name) in values:
                lane, kind = fields.get("lane", lane), fields.get("kind", kind)
                row = fields.get("row", row)
                title, text = fields.get("title", title), fields.get("text", text)
                break
        flags = "".join(f for f in flags if _needs(cfg, (nid, f)))
        kept[nid] = (lane, row, kind, title, text, flags)
    out, seen = [], set()
    for a, b, label, kind in edges:
        if a not in kept or not _needs(cfg, (a, b)):
            continue
        if b not in kept:
            if (a, b) in NEEDS:
                continue
            hops = 0
            while b not in kept and b in PASS and hops < len(PASS):
                b, hops = PASS[b], hops + 1
            if b not in kept or b == a:
                continue
            kind = "" if kind == "msg" else kind
        if (a, b) in seen:
            continue
        seen.add((a, b))
        out.append((a, b, label, kind))
    rows = {r: i for i, r in enumerate(sorted({n[1] for n in kept.values()}))}
    kept = {nid: (n[0], rows[n[1]]) + n[2:] for nid, n in kept.items()}
    return kept, out


def _variant_details(cfg):
    details = dict(DETAILS)
    for nid, variants in VARIANTS.items():
        for name, values, fields in variants:
            if setting(cfg, name) in values:
                if "details" in fields:
                    details[nid] = fields["details"]
                break
    return details


def config_of(tree):
    """The project's config as sclaude reads it for a tree (project_config,
    project_get): the main checkout's, with a key it lacks taken from the
    tree's own copy. {} when neither can be read."""
    main = tree
    try:
        with open(os.path.join(tree, ".git")) as fh:
            line = fh.read().strip()
        if line.startswith("gitdir:"):
            gitdir = line.split(":", 1)[1].strip()
            main = os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(gitdir))))
    except OSError:
        pass
    def read(where):
        try:
            with open(os.path.join(where, ".sclaude", "config.json")) as fh:
                got = json.load(fh)
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def fill(first, second):
        # Key by key down every path, as project_get falls back: the first's
        # value, the second's where the first has none (null is none).
        out = dict(second)
        for key, value in first.items():
            if value is None:
                continue
            if isinstance(value, dict) and isinstance(second.get(key), dict):
                out[key] = fill(value, second[key])
            else:
                out[key] = value
        return out
    first, second = read(main), (read(tree) if main != tree else {})
    cfg = fill(first, second)
    # A section read whole (project_config_with): the board's, from the file
    # that has it.
    if "board" in first or "board" in second:
        cfg["board"] = first.get("board") if first.get("board") is not None else second.get("board")
    return cfg


def on_map(nid):
    """A place on the map drawn now: the block itself, or the one the flow
    goes on to when this config draws none (PASS). "" when neither."""
    drawn = all_nodes()
    hops = 0
    while nid and nid not in drawn and hops < len(PASS):
        nid, hops = PASS.get(nid, ""), hops + 1
    return nid if nid in drawn else ""


EXAMPLE_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.example.json")


def example_config():
    try:
        with open(EXAMPLE_CONFIG) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def configured(cfg):
    """The maps as cfg draws them, for what is drawn, lit or played inside:
    the model's tables stand in for the config's own meanwhile."""
    global NODES, EDGES, OVERVIEW_NODES, OVERVIEW_EDGES
    global DETAILS, POSITIONS, ALIAS, REGRESSION_NODES, REGRESSION_EDGES, SYNC_NODES, SYNC_EDGES
    saved = (NODES, EDGES, OVERVIEW_NODES, OVERVIEW_EDGES,
             DETAILS, POSITIONS, ALIAS, REGRESSION_NODES, REGRESSION_EDGES, SYNC_NODES, SYNC_EDGES)
    try:
        NODES, EDGES = for_config(cfg, NODES, EDGES)
        REGRESSION_NODES, REGRESSION_EDGES = for_config(cfg, REGRESSION_NODES, REGRESSION_EDGES)
        OVERVIEW_NODES, OVERVIEW_EDGES = for_config(cfg, OVERVIEW_NODES, OVERVIEW_EDGES)
        DETAILS = _variant_details(cfg)

        def on(nid, nodes):
            hops = 0
            while nid and nid not in nodes and hops < len(PASS):
                nid, hops = PASS.get(nid, ""), hops + 1
            return nid if nid in nodes else ""
        POSITIONS = {k: on(o, OVERVIEW_NODES) for k, o in saved[5].items()}
        ALIAS = {k: v for k, v in saved[6].items() if k in OVERVIEW_NODES}
        # A block of the glance carries the letters of the step
        # it stands for: what happens inside it shows outside too.
        drawn = all_nodes()
        for nid, n in list(OVERVIEW_NODES.items()):
            big = drawn.get(ALIAS.get(nid, ""))
            if big:
                flags = "".join(f for f in "FWRS" if f in n[5] + big[5])
                OVERVIEW_NODES[nid] = n[:5] + (flags,)
        yield
    finally:
        (NODES, EDGES, OVERVIEW_NODES, OVERVIEW_EDGES,
         DETAILS, POSITIONS, ALIAS, REGRESSION_NODES, REGRESSION_EDGES, SYNC_NODES, SYNC_EDGES) = saved


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


def node_sets_named():
    return {name: nodes for name, _lanes, nodes, _edges in node_sets()}


def node_sets():
    return [("detail", LANES, NODES, EDGES), ("overview", OVERVIEW_LANES, OVERVIEW_NODES, OVERVIEW_EDGES),
            ("workshop", WORKSHOP_LANES, WORKSHOP_NODES, WORKSHOP_EDGES),
            ("friction", FRICTION_LANES, FRICTION_NODES, FRICTION_EDGES),
            ("regression", REGRESSION_LANES, REGRESSION_NODES, REGRESSION_EDGES),
            ("sync", SYNC_LANES, SYNC_NODES, SYNC_EDGES)]


# --- where a feature stands --------------------------------------------------

def _runs(node):
    return [r for r in ((node or {}).get("runs") or []) if isinstance(r, dict)]


def _fix_open(state, stage):
    words = (((state.get("regression") or {}).get(stage) or {}).get("fix_status") or "").split()
    return bool(words) and words[-1] == "open"


def _when_iso(text):
    try:
        when = datetime.datetime.fromisoformat(text or "")
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else None


def _recent(when):
    """A start believed: less than three hours ago. One left by a run that
    was killed stays behind."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return bool(when) and (now - when).total_seconds() < 3 * 3600


def _fresh(text):
    return _recent(_when_iso(text))


def _running(state, stage):
    run = (state.get("regression") or {}).get(stage) or {}
    return run.get("status") == "running" and _fresh(run.get("started"))


def _going(run):
    """A session's run going now: not ended, or taken up again after its end
    (session_runs' resumed), and begun or taken up less than three hours
    ago. One left unfinished has an end, and is not going."""
    if not run or run.get("done"):
        return False
    began = _when_iso(run.get("resumed")) or _when_iso(run.get("started"))
    ended = _when_iso(run.get("finished"))
    return _recent(began) and (not ended or began > ended)


def _sync_in_step(state):
    """A sync with main going during a step: the sync before the step's
    session, or one asked for from the menu. One left unfinished is not where
    the feature stands — the step opens on the branch as it is
    (sync_broken_off)."""
    sync = _runs(state.get("sync"))
    return bool(sync) and _going(sync[-1])


def _friction_open(state):
    """A friction review open holds the next step (f_hold)."""
    return any(runs and not runs[-1].get("done")
               for runs in (_runs(v) for v in (state.get("friction") or {}).values() if isinstance(v, dict)))


def _open(run):
    """A run not ended, or taken up again after its end (session_runs'
    resumed): open however long ago it began, as the retrospective is."""
    if not run or run.get("done"):
        return False
    resumed, ended = _when_iso(run.get("resumed")), _when_iso(run.get("finished"))
    return not ended or bool(resumed and resumed > ended)


def _session_node(state, session):
    """The block of the session's run, while it is open."""
    places = [("steps.%s" % step, step) for step in ((state.get("steps") or {}))]
    places += [("retro", "retro"), ("sync", "sync"), ("epilogue", "epilogue")]
    for path, nid in places:
        node = state
        for part in path.split("."):
            node = (node or {}).get(part) if isinstance(node, dict) else None
        for run in _runs(node if isinstance(node, dict) else None):
            if run.get("session") == session and _open(run):
                return nid
    return ""


def busy(state, workshop=None):
    """The F and W badges at work now, {block: [flags]}: a friction review
    open behind the session it follows (its key is the step and a number,
    review-3, fix-local-1), and a session the workshop's record lets write
    sclaude (workshop, .sclaude/local/instruments.json) while its run is
    open."""
    out, drawn = {}, all_nodes()
    for key, node in (state.get("friction") or {}).items():
        runs = _runs(node) if isinstance(node, dict) else []
        nid = key.rsplit("-", 1)[0].replace("-", "_")
        if runs and not runs[-1].get("done") and "F" in drawn.get(nid, ("",) * 6)[5]:
            out.setdefault(nid, []).append("F")
    for session in (workshop or {}).get("approved") or []:
        nid = _session_node(state, session)
        if nid and "W" in drawn.get(nid, ("",) * 6)[5] and "W" not in out.get(nid, []):
            out.setdefault(nid, []).append("W")
    # R: a suite running, or a session fixing what it found, on the block the
    # stage runs from; S: a sync with main going, on the step it runs ahead
    # of, or on the preview once the steps are done.
    step = state.get("step") or "plan"
    at_step = step if step in NODES else "review"
    for stage, block in (("local", at_step), ("preview", "preview"), ("prod", "prod")):
        fixing = _fix_open(state, stage)
        if _running(state, stage) or fixing:
            nid = "review" if fixing and stage != "local" else block
            if "R" in NODES.get(nid, ("",) * 6)[5] and "R" not in out.get(nid, []):
                out.setdefault(nid, []).append("R")
    sync = _runs(state.get("sync"))
    if sync and _going(sync[-1]):
        nid = _sync_block(state)
        if "S" in NODES.get(nid, ("",) * 6)[5]:
            out.setdefault(nid, []).append("S")
    return out


def _sync_block(state):
    """The block a sync with main runs ahead of: the step's, or once the steps
    are done the preview, the hand-over after QA's yes, the merge's wait."""
    step = state.get("step") or "plan"
    if step in NODES and step != "done":
        return step
    if state.get("handoff"):
        return "merge_wait"
    return "handoff" if (state.get("qa") or {}).get("accepted") else "preview"


def stalled(state, pr_state=""):
    """A sync with main broken off once the steps are done, its pull request
    open, {block: {"S": text}}: the feature stands there until the person runs
    it again (_past_steps). One broken off in a step is not: the step opens on
    the branch as it is (_sync_in_step); nor once the pull request is merged
    or closed, when there is nothing left to sync."""
    sync = _runs(state.get("sync"))
    if (state.get("step") != "done" or pr_state != "OPEN" or state.get("no_change")
            or not sync or sync[-1].get("done") or _going(sync[-1])):
        return {}
    nid = _sync_block(state)
    if "S" not in NODES.get(nid, ("",) * 6)[5]:
        return {}
    return {nid: {"S": "broken off — `sclaude sync %s` takes it up again" % (state.get("feature") or "<name>")}}


# Why a letter stands on a block: (block, letter) -> a sentence, else the
# letter's own words (FLAG_WORDS). The glance's blocks borrow
# their step's (ALIAS).
BADGE_WHY = {
    ("plan", "S"): "S — main is merged into the branch before the plan's session opens; a conflict goes to the sync first.",
    ("code", "S"): "S — main is merged in before step 2's session opens; a conflict goes to the sync first.",
    ("pr", "S"): "S — main is merged in before step 3, so the pull request carries what will merge.",
    ("review", "S"): "S — main is merged in before each review round.",
    ("preview", "S"): "S — the branch must merge with main before its preview is deployed.",
    ("merge_wait", "S"): "S — every 2 min the wait checks whether main moved into a conflict; one goes to the sync, the PR back to a draft, and the run to the preview again.",
    ("handoff", "S"): "S — before the hand-over main is checked; a conflict goes to the sync, and the run to the preview and QA again, as do commits that reached the branch from elsewhere.",
    # The glance's QA and merge, which carry their own S (OVERVIEW_NODES).
    ("qa_check", "S"): "S — once QA accepted, main is checked before the hand-over; a conflict goes to the sync, and the run to the preview and QA again, as do commits that reached the branch from elsewhere.",
    ("merge", "S"): "S — while the merge waits, main is checked every 2 min; a conflict goes to the sync, the PR back to a draft, and the run to the preview again.",
    ("code", "R"): "R — after your yes the local suite runs against this feature's server; red opens a fixing session, two at most.",
    ("review", "R"): "R — a red preview or production comes back here to be fixed.",
    ("review_close", "R"): "R — the local suite runs again before step 4 closes; red opens a fixing session, two at most.",
    ("local_pass", "S"): "S — main is merged in when step 4 starts or is taken up again, before the local review's pass; a conflict goes to the sync first.",
    ("preview", "R"): "R — the preview suite runs against this deployment; green sends the issue to QA, red back to step 4.",
    ("prod", "R"): "R — production's suite runs after the ship; red is rolled back first, then fixed from step 4 — or held.",
    ("plan", "F"): "F — what the safety rules refused the plan's session is reviewed once it ends.",
    ("code", "F"): "F — what the safety rules refused step 2's session is reviewed once it ends.",
    ("pr", "F"): "F — what the safety rules refused step 3's session is reviewed once it ends.",
    ("friction_left", "F"): "F — the friction reviews still owed run here, one after another, before the retrospective.",
    ("review", "F"): "F — what the safety rules refused a review round is reviewed when the round goes to a fresh session.",
    ("retro", "W"): "W — the retrospective may fix what it found in sclaude, in the workshop; its approved plan is the yes.",
    ("f_review", "W"): "W — a bug in sclaude the review finds it fixes in the workshop; its approved plan is the yes.",
    ("f_monthly", "W"): "W — the monthly review makes a change to sclaude it decides on in the workshop; its approved plan is the yes.",
    ("sync", "F"): "F — what got in the sync session's way is reviewed once it ends, as after a step's session.",
}


def badge_why(nid, flag):
    base = ALIAS.get(nid, nid)
    return BADGE_WHY.get((base, flag)) or "%s — %s" % (flag, FLAG_WORDS.get(flag, ""))


def _hhmm(text):
    when = _when_iso(text)
    return when.astimezone().strftime("%H:%M") if when else ""


def busy_notes(state, workshop=None):
    """How the work behind each turning letter goes, {block: {letter: text}},
    from what the state holds: since when, which attempt, what is open."""
    out = {}
    for nid, flags in busy(state, workshop).items():
        for flag in flags:
            text = ""
            if flag == "R":
                for stage in ("local", "preview", "prod"):
                    run = (state.get("regression") or {}).get(stage) or {}
                    if _running(state, stage):
                        tries = str(run.get("attempts") or 0)
                        # attempts: the fixing attempts the stage has used of
                        # its two (regression.sh), given back after a yes to
                        # another or a session that spent nothing.
                        text = "now: the %s suite, running since %s%s" % (
                            stage, _hhmm(run.get("started")),
                            "" if tries == "0" else " (fixing attempts used: %s)" % tries)
                    elif _fix_open(state, stage):
                        text = "now: a session fixing the red %s suite" % stage
            elif flag == "S":
                sync = _runs(state.get("sync"))
                text = "now: a sync with main, since %s" % _hhmm((sync[-1].get("resumed") or sync[-1].get("started"))) \
                    if sync else ""
            elif flag == "F":
                open_ = [(k, _runs(v)[-1]) for k, v in (state.get("friction") or {}).items()
                         if isinstance(v, dict) and _runs(v) and not _runs(v)[-1].get("done")
                         and k.rsplit("-", 1)[0].replace("-", "_") == nid]
                if open_:
                    key, run = open_[-1]
                    text = "now: friction review %s open since %s — it holds the next step" % (key, _hhmm(run.get("started")))
            elif flag == "W":
                ready = (workshop or {}).get("ready") or {}
                text = "now: changing sclaude" + (
                    "; ready at %s, published when the session ends" % str(ready.get("head", ""))[:7]
                    if ready.get("head") else "; not marked ready yet")
            if text:
                out.setdefault(nid, {})[flag] = text
    return out


def prod_held(state):
    """As prod_red_hold's condition: production carries the feature and its
    last run there was not green, and it was not rolled back. Carried is read
    from the state, not from GitHub as prod_carries_feature does it: the
    pull request production was shipped for is the feature's pull request now
    — a fix sent forward in a new one is not in that release — and with no
    pull request nothing is carried. A ship recorded before deploy.prod.pr was
    kept counts as carried."""
    reg = (state.get("regression") or {}).get("prod") or {}
    prod = (state.get("deploy") or {}).get("prod") or {}
    rolled = ((state.get("rollback") or {}).get("prod") or {}).get("code") == "done"
    pr = state.get("pr")
    carried = bool(prod.get("sha")) and bool(pr) and prod.get("pr") in (None, pr)
    # failed alone, as regression_status reads it: a run that could not run
    # is recorded failed too, and one cut off midway is not a hold.
    return carried and not rolled and reg.get("status") == "failed"


def position(state, pr_state="", epilogue=None):
    """The detailed node a feature stands on, and a line saying why.

    pr_state is GitHub's word for the branch's pull request (OPEN, MERGED,
    CLOSED, or "" when it did not answer); epilogue the epilogue's own record
    (~/.claude/sclaude/epilogue/<feature>.json), when there is one."""
    step = state.get("step") or "plan"
    if step != "done":
        node, why = _in_step(state, step)
        if _friction_open(state):
            why += "; an open friction review holds the next step"
        return node, why
    return _past_steps(state, pr_state, epilogue)


def _in_step(state, step):
    if _sync_in_step(state):
        return "sync", "a sync with main is open, ahead of the step"
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
        if _fresh(((state.get("review") or {}).get("local") or {}).get("running")):
            return "local_pass", "the local review is reading the pull request"
    return (step if step in NODES else "plan"), "step %s" % step


def _past_steps(state, pr_state, epilogue):
    if state.get("no_change"):
        if state.get("friction_owed"):
            return "friction_left", "a friction review still owed waits before the retrospective: sclaude done at the terminal"
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
        # A run going on is said first: one started from the hold leaves its
        # unrunnable mark until it ends.
        if _running(state, "prod"):
            return "prod", "the production regression is running"
        # Not bounded in time: the answer may take a night (remind_prod).
        if (state.get("prod_pass") or {}).get("shipping"):
            return "ship", "asked whether to ship to production, or shipping"
        if prod_held(state):
            return "hold_ways", "production carries the feature, and its last run was not green"
        retro = _runs(state.get("retro"))
        if not retro and ((state.get("steps") or {}).get("review") or {}).get("friction_held"):
            return "friction_left", "a friction review held in step 4 comes before the retrospective"
        if state.get("friction_owed"):
            return "friction_left", "a friction review still owed waits before the retrospective: sclaude done at the terminal"
        last = retro[-1] if retro else {}
        # Resumed, a retrospective keeps the end it had (session_runs): it is
        # open again while taken up after that end.
        resumed, ended = _when_iso(last.get("resumed")), _when_iso(last.get("finished"))
        again = bool(resumed and ended and resumed > ended)
        # The tree is still here, so the clean-up was not done: not asked yet,
        # or declined (kept) — sclaude done asks it again.
        if retro and last.get("done") and not again:
            return "cleanup", "the retrospective ran; the clean-up is left: sclaude done asks it"
        if retro:
            return "retro", "the retrospective is open: running, or broken off"
        epi = epilogue or {}
        if epi.get("session") and not epi.get("done"):
            return "epilogue", "the epilogue broke off"
        return "done_cmd", "merged: the retrospective and the clean-up are next"
    if pr_state == "CLOSED":
        return "cleanup", "the pull request was closed without a merge"
    return "preview", "past step 4; GitHub did not say where the pull request is"


# --- how a feature went ------------------------------------------------------
#
# The feature's history, history_add's and session_runs' lines (state.sh) in
# the file beside its state, played back on the map: each place it stood on,
# how long, and the way it went on. The file lives in the worktree's
# .sclaude/local, which git never carries and the clean-up removes with the
# tree; a feature begun before it has no history to play.
#
# What it gives the page: `visits`, the detailed map's places in order —
# those the history names, with the places between them filled in along the
# map's shortest way, and the time between two places given to the first
# check or person on the way — and `passes`, the friction reviews and the
# workshop's publications, each a way through its own map. A visit
# {"pass": [map, i]} is where the feature went off to one of those.

HISTORY_FILE = "history.jsonl"
# What the transcripts said of each conversation, kept beside the history.
TRANSCRIPT_CACHE = "transcripts.json"
TRANSCRIPT_FRESH = 60

# A step closed: the check it closes on.
STEP_CLOSE = {"plan": "plan_check", "pr": "pr_check", "review": "review_close"}
STAGE_NODE = {"local": "reg_local", "preview": "preview", "prod": "prod"}
# Who the gap before the next place is spent on: a check, a person, a wait.
WAITS_ON = ("user", "gate", "wait", "hold")
# The most places filled in between two the history names.
FILL_MAX = 5


def _when(text):
    try:
        at = datetime.datetime.fromisoformat(str(text or ""))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)


def _row(at, what, op, **extra):
    row = {"at": at, "what": what, "op": op}
    row.update({k: v for k, v in extra.items() if v})
    return row


def history_rows(lines):
    """The file's rows in the order they happened; one written in the same
    second as another stays after it."""
    rows = [r for r in lines if isinstance(r, dict) and _when(r.get("at")) and r.get("what")]
    return [r for _i, r in sorted(enumerate(rows), key=lambda p: (_when(p[1]["at"]), p[0]))]


# The epilogue's copy on the whole map, beside the preview: a status session
# run_status marked as the preview's (`about`), red or written again green.
# A step aside, from wherever the run or the menu wrote it before the merge,
# and never a deviation: the way on goes from the place before it.
COPIES = {"epi_preview"}

# Steps whose session, opened again right after one of its own, took up one
# that broke off: nothing ran between, and no way round is played. Each closes
# on a check of its own (STEP_CLOSE), entered when it finished; the code's
# "no" from you is not recorded, and the review's rounds do go round.
REOPENED = ("plan", "pr")


def _graph(edges):
    out = {}
    for a, b, _label, _kind in edges:
        out.setdefault(a, []).append(b)
    return out


def _way(graph, a, b):
    """The shortest way along the map from a to b, both ends included; from
    a place back to itself, the shortest way round. [a, b] when none."""
    queue, seen = [[a, x] for x in graph.get(a, [])], {a} if a != b else set()
    while queue:
        way = queue.pop(0)
        if way[-1] == b:
            return way
        if way[-1] in seen:
            continue
        seen.add(way[-1])
        queue += [way + [x] for x in graph.get(way[-1], []) if x not in seen or x == b]
    return [a, b]


def _seconds(a, b):
    ta, tb = _when(a), _when(b)
    return max(0, int((tb - ta).total_seconds())) if ta and tb else None


class _Places:
    """The detailed map's places, as the rows enter and leave them."""

    def __init__(self):
        self.list, self.open = [], {}
        # Where a stay left open by an interrupted run (a Ctrl-C writes no
        # end) is taken to have ended: the last line of the sclaude run that
        # opened it, or of any run where the lines name none.
        self.last, self.last_of, self.run = None, {}, None

    def enter(self, node, at, key=None, session=None):
        key = key or node
        place = self.open.get(key)
        if place:
            # A conversation opened with no end before it and nothing else
            # between: the review carrying on into its next round in the
            # same one, or one opened in place of a conversation that died
            # (the sync's). One stay, the new conversation a sitting of its
            # own, so that its drop takes back only what it added.
            if session and place.get("session") and self.list[-1] is place:
                place["sittings"][-1][1] = at
                place["sittings"].append([at, None])
                place.setdefault("before", []).append(place["session"])
                place["session"] = session
                return
            # Left open while the feature went elsewhere: it ended where
            # the next place began.
            after = self.list[self.list.index(place) + 1:]
            self.leave(key, next((p["from"] for p in after if p.get("from")),
                                 self.last_of.get(place.get("run")) or self.last or at))
        self.list.append({"n": node, "from": at, "to": None, "session": session, "sittings": [],
                          "run": self.run})
        self.open[key] = self.list[-1]
        self.list[-1]["sittings"].append([at, None])

    def leave(self, key, at):
        place = self.open.pop(key, None)
        if place:
            place["to"] = at
            place["sittings"][-1][1] = at

    def drop(self, key):
        """A conversation that never took place: no stay at all."""
        place = self.open.pop(key, None)
        if place:
            place["sittings"].pop()
            if not place["sittings"]:
                self.list.remove(place)
            else:
                place["session"] = place["before"].pop()
                place["to"] = place["sittings"][-1][1]

    def point(self, node, at):
        self.list.append({"n": node, "from": at, "to": at, "session": None, "sittings": []})

    def detour(self, kind, index, at):
        self.list.append({"pass": [kind, index], "from": at, "to": at})


def _friction_way(rows, workshop_sessions):
    """A friction review's way through its map, from its rows."""
    ops = [r["op"] for r in rows]
    if "deferred" in ops:
        return [{"n": n} for n in ("f_trip", "f_log", "f_empty", "f_rules", "f_classify", "f_defer")]
    way = [{"n": n} for n in ("f_trip", "f_log", "f_empty", "f_rules")]
    sitting, outcome, verdict, session = None, "", "", ""
    for r in rows:
        if r["op"] == "held" and way[-1]["n"] != "f_away":
            way.append({"n": "f_away", "from": r["at"]})
        if r["op"] == "open":
            if way[-1]["n"] == "f_review":
                way[-1]["k"] = way[-1].get("k", 1) + 1
            else:
                way.append({"n": "f_review", "s": 0, "from": r["at"]})
            sitting, session = r["at"], r.get("session") or session
        elif r["op"] in ("end", "stall", "finish") and sitting:
            way[-1]["s"] += _seconds(sitting, r["at"]) or 0
            way[-1]["to"] = r["at"]
            sitting = None
            if r["op"] == "stall":
                way.append({"n": "f_hold"})
        if r["op"] in ("finish", "end") and r.get("outcome"):
            outcome = r["outcome"]
        if r["op"] == "verdict":
            verdict = r.get("verdict", "")
    if not (outcome or verdict):
        return way
    if session in workshop_sessions:
        decided = "f_bug"
    elif verdict in ("lifted", "mixed") or outcome == "fixed":
        decided = "f_lift"
    else:
        decided = "f_deliberate"
    way += [{"n": "f_plan"}, {"n": "f_decide"}, {"n": decided}, {"n": "f_verdict"}]
    if outcome == "fixed":
        way.append({"n": "f_push"})
    way.append({"n": "f_next"})
    return way


def _timed(node, a, b):
    step = {"n": node, "from": a}
    if b:
        step.update({"to": b, "s": _seconds(a, b) or 0})
    return step


def _regression_way(stage, rows, cut=None):
    """A stage's run through the regression map, each place with its time,
    so what it took is counted there and not on the step it came from. A run
    cut off ends at cut: the last line of the sclaude run that started it."""
    gate = {"local": "reg_local", "preview": "preview_ok", "prod": "prod_ok"}[stage]
    way, run, fix = [{"n": "r_" + stage}], None, None
    for r in rows:
        what, op, at = r["what"], r["op"], r["at"]
        if what.startswith("regression."):
            if op == "start":
                run = at
            else:
                way.append(_timed(gate, run or at, at))
                run = None
                if op == "passed":
                    way.append({"n": "r_on"})
        elif what.startswith("fix."):
            node = "fix_" + stage
            if op == "start":
                fix = at
                way.append(dict(_timed(node, at, None), session=r.get("session")))
            elif way and way[-1]["n"] == node:
                way[-1].update(_timed(node, fix or at, at))
                if stage == "local":
                    way.append({"n": gate})
        elif what == "rollback.prod":
            way.append({"n": "rollback", "from": at, "to": at})
    if run:
        way.append(_timed(gate, run, cut if cut and _seconds(run, cut) else None))
    return way


def _sync_way(rows):
    """A sync with main through its map: the check, the session's sittings,
    and the merge in once it settled."""
    way = [{"n": "y_when"}, {"n": "merge_check"}]
    sitting = None
    for r in rows:
        if r["op"] == "open":
            if way[-1]["n"] == "sync":
                # One opened in place of a conversation that died: that one
                # ended here, and this is a sitting of the same stay.
                if sitting:
                    way[-1]["s"] += _seconds(sitting, r["at"]) or 0
                way[-1]["k"] = way[-1].get("k", 1) + 1
            else:
                way.append({"n": "sync", "from": r["at"], "s": 0})
            sitting = r["at"]
        elif r["op"] == "drop" and sitting:
            # A conversation that never took place: no time, no sitting.
            sitting = None
            if way[-1].get("k", 1) > 1:
                way[-1]["k"] -= 1
        elif r["op"] in ("end", "finish", "stall") and sitting:
            way[-1]["s"] += _seconds(sitting, r["at"]) or 0
            way[-1]["to"] = r["at"]
            sitting = None
        if r["op"] in ("finish", "close"):
            way += [{"n": "merge_check"}, {"n": "main_in"}, {"n": "y_on"}]
    return way


WORKSHOP_START = ("w_find", "w_ask", "w_open", "w_change", "w_ready", "w_exit", "w_ready_gate")
WORKSHOP_OUT = {
    "blocked": ("w_leaks", "w_leak_ask", "w_held"), "held": ("w_leaks", "w_leak_ask", "w_held"),
    "left": ("w_back", "w_pending"), "red": ("w_leaks", "w_tests"),
    "stopped": ("w_leaks", "w_tests", "w_who"),
    "main": ("w_leaks", "w_tests", "w_who", "w_main"), "pr": ("w_leaks", "w_tests", "w_who", "w_pr"),
}


def _workshop_way(rows):
    """A session's change to sclaude, from the session's end to how its
    publication went."""
    way = list(WORKSHOP_START)
    for r in rows:
        if way[-1] == "w_pending" and r["op"] != "left":
            way += ["w_change", "w_ready", "w_exit", "w_ready_gate"]
        for n in WORKSHOP_OUT.get(r["op"], ()):
            if n != way[-1]:
                way.append(n)
    return [{"n": n} for n in way]


def _session_names(state):
    """What each conversation was: "2 · code", "friction code-1", "retro"."""
    names = {}
    for step, node in (state.get("steps") or {}).items():
        for run in _runs(node):
            names[run.get("session")] = NODES.get(step, ("", "", "", step))[3]
    for key, node in (state.get("friction") or {}).items():
        for run in _runs(node):
            names[run.get("session")] = "friction review " + key
    for what in ("sync", "retro", "epilogue"):
        for run in _runs(state.get(what) if isinstance(state.get(what), dict) else None):
            names[run.get("session")] = all_nodes()[what][3]
    names.pop(None, None)
    return names


def _short(at):
    when = _when(at)
    return when.strftime("%d %b %H:%M") if when else ""


def history(state, lines, here=None, transcripts=None):
    """The feature's way through the maps, for the page to play, and what
    each place took (`metrics`) when the sessions' transcripts are given:
    a function from a session id to claude_usage.read's summary, or None."""
    rows = history_rows(lines)
    places = _Places()
    friction, workshop, regression, syncs = {}, {}, {}, {}
    last_run = {}
    merged = qa_open = False
    first = rows[0]["at"] if rows else None
    if first:
        places.point("new", first)
    for r in rows:
        what, op, at = r["what"], r["op"], r["at"]
        head, _, rest = what.partition(".")
        places.run = r.get("run")
        if head == "steps" and rest in NODES:
            if op == "open":
                places.enter(rest, at, "steps." + rest, r.get("session"))
            elif op == "drop":
                places.drop("steps." + rest)
            elif op in ("end", "stall", "finish"):
                places.leave("steps." + rest, at)
            if op in ("close", "finish") and rest in STEP_CLOSE:
                places.point(STEP_CLOSE[rest], at)
        elif what == "sync":
            # A sync is a pass on its own map: where it ran, and what it took.
            key = last_run.get("sync")
            # A new pass once the last one settled or never took place; one
            # left unfinished and taken up again goes on in its own.
            if op == "open" and (key is None or any(x["op"] in ("finish", "close")
                                                    for x in syncs[key])
                                 or [x["op"] for x in syncs[key]][-1:] == ["drop"]):
                key = last_run["sync"] = str(len(syncs))
                syncs[key] = []
                places.detour("sync", key, at)
            if key is not None:
                syncs[key].append(r)
        elif what in ("retro", "epilogue"):
            if op == "open":
                places.enter("epi_preview" if r.get("about") == "preview" else what,
                             at, what, r.get("session"))
            elif op == "drop" and what != "retro":
                places.drop(what)
            elif op in ("end", "stall", "finish", "drop"):
                # A retrospective nobody answered is dropped (retro.sh), but
                # its conversation took place.
                places.leave(what, at)
        elif head == "friction" and rest:
            if rest not in friction:
                friction[rest] = []
                if op != "empty":
                    places.detour("friction", rest, at)
            friction[rest].append(r)
        elif head in ("regression", "fix") and rest in STAGE_NODE \
                or what == "rollback.prod":
            # A stage's run is a pass on the regression map, its fixing
            # sessions and a rollback with it.
            stage = "prod" if what == "rollback.prod" else rest
            key = last_run.get(stage)
            if (head, op) == ("regression", "start") or key is None:
                key = last_run[stage] = "%s-%d" % (stage, len(regression))
                regression[key] = []
                places.detour("regression", key, at)
            regression[key].append(r)
        elif what == "deploy.preview":
            if op == "start":
                places.enter("preview", at, what)
            else:
                places.leave(what, at)
        elif what == "deploy.prod" and op == "done":
            places.point("prod", at)
        elif what == "review.local":
            if op == "start":
                places.enter("local_pass", at, what)
            else:
                places.leave(what, at)
        elif what == "qa":
            # Done is seen again on every look before the merge: a verdict is
            # one only after QA was sent to look.
            if op == "in":
                places.point("in_qa", at)
                places.enter("qa_check", at, "qa")
                qa_open = True
            elif qa_open or op == "back":
                places.leave("qa", at)
                places.point("qa_verdict", at)
                qa_open = False
        elif what == "handoff":
            places.point("handoff", at)
        elif what == "merge":
            if op == "wait":
                places.enter("merge_wait", at, "merge")
            elif not merged:
                merged = True
                places.leave("merge", at)
                places.point("merged", at)
        elif what == "workshop" and op == "none" and r.get("session") not in workshop:
            pass  # let write there, and changed nothing: no pass
        elif what == "workshop":
            session = r.get("session") or (list(workshop)[-1] if workshop else "")
            if session not in workshop:
                workshop[session] = []
                places.detour("workshop", session, at)
            workshop[session].append(r)
        # A command is the next process's: it says nothing of when the run
        # before it left off.
        if what != "command":
            places.last = at
        if r.get("run"):
            places.last_of[r["run"]] = at

    # Merged into one: the same place entered again with nothing between, by
    # the same conversation — a session resumed, a deploy and its regression.
    visits = []
    for p in places.list:
        last = visits[-1] if visits else None
        if last and "n" in p and last.get("n") == p["n"] and p["n"] != "new" and (
                not p.get("session") or not last.get("session") or p["session"] == last["session"]):
            last["sittings"] += p["sittings"]
            last["to"] = p["to"] or last["to"]
            continue
        visits.append(p)
    aside = here and here not in NODES
    if here and not aside and (not visits or visits[-1].get("n") != here):
        visits.append({"n": here, "from": None, "to": None, "sittings": [], "here": True})
    elif visits and here:
        visits[-1]["here"] = True

    # The places between, along the map; the time between two places to the
    # first check or person on the way, who is what it waited on.
    graph = _graph(EDGES)
    out, prev, held, stray, after_copy = [], None, [], False, False
    for v in visits:
        if "pass" in v:
            # A regression run or a sync stands between two places of the
            # cycle (an R, an S on the way): it is played after the way that
            # led to it, which waited until it began.
            if (v["pass"][0] in ("regression", "sync") or held) and prev is not None:
                held.append(v)
            else:
                out.append({"pass": v["pass"]})
            continue
        copy = v["n"] in COPIES
        stop = prev
        if prev is not None and not copy:
            # Back where it was before a status copy: no way round.
            reopened = prev["n"] == v["n"] and (v["n"] in REOPENED or after_copy)
            full = [] if reopened else _way(graph, prev["n"], v["n"])
            way = full[1:-1]
            # The map has no way at all from the one to the other: the
            # feature went where the map does not go (deviations).
            stray = full == [prev["n"], v["n"]] and v["n"] not in graph.get(prev["n"], [])
            # A long way round is a guess, not a fill: a local review pass
            # after a round has no arrow of its own, and the shortest way
            # there runs through the merge and the retrospective.
            if len(way) > FILL_MAX:
                way = []
            until = held[0].get("from") if held else None
            until = until or v.get("from") or (v["sittings"][0][0] if v["sittings"] else None)
            gap = _seconds(prev.get("to"), until)
            waited = next((n for n in way if NODES[n][2] in WAITS_ON), None)
            for n in way:
                step = {"n": n}
                if n == waited and gap and gap >= 60:
                    step.update({"s": gap, "from": prev.get("to"), "to": until, "wait": True})
                out.append(step)
        out += [{"pass": h["pass"]} for h in held]
        held = []
        step = {"n": v["n"]}
        secs = [_seconds(a, b) for a, b in v["sittings"] if b]
        if secs:
            step["s"] = sum(secs)
        if len(v["sittings"]) > 1:
            step["k"] = len(v["sittings"])
        if v.get("from"):
            step["from"] = v["from"]
        if v.get("to"):
            step["to"] = v["to"]
        if v.get("here"):
            step["here"] = True
        if prev is not None and stray:
            step["off"] = "the map has no way from %s to %s" % (
                NODES.get(prev["n"], ("",) * 4)[3] or prev["n"], NODES.get(v["n"], ("",) * 4)[3] or v["n"])
        stray = False
        out.append(step)
        prev = dict(stop, to=v.get("to") or stop.get("to")) if copy else v
        after_copy = copy
    # The last passes, with no place after them yet.
    out += [{"pass": h["pass"]} for h in held]

    names = _session_names(state)
    workshop_sessions = set(workshop)
    passes = {"friction": [], "workshop": [], "regression": [], "sync": []}
    index = {}
    for key, rs in regression.items():
        index[("regression", key)] = len(passes["regression"])
        ends = [x["op"] for x in rs if x["what"].startswith("regression.") and x["op"] != "start"]
        passes["regression"].append({
            "label": "%s · %s%s" % (_short(rs[0]["at"]), key.split("-")[0], (" · " + ends[-1]) if ends else ""),
            "steps": _regression_way(key.split("-")[0], rs,
                                     places.last_of.get(rs[0].get("run")) if rs[0].get("run") else None)})
    for key, rs in syncs.items():
        index[("sync", key)] = len(passes["sync"])
        ends = [x["op"] for x in rs if x["op"] != "open"]
        passes["sync"].append({
            "label": "%s · sync%s" % (_short(rs[0]["at"]), (" · " + ends[-1]) if ends else ""),
            "steps": _sync_way(rs)})
    for key, rs in friction.items():
        if [r["op"] for r in rs] == ["empty"]:
            continue
        verdict = next((r.get("verdict") for r in rs if r["op"] == "verdict"), "")
        if any(r["op"] == "deferred" for r in rs):
            verdict = "put off, no session"
        index[("friction", key)] = len(passes["friction"])
        passes["friction"].append({
            "label": "%s · %s%s" % (_short(rs[0]["at"]), key, (" · " + verdict) if verdict else ""),
            "steps": _friction_way(rs, workshop_sessions)})
    for session, rs in workshop.items():
        ends = [r["op"] for r in rs if r["op"] in WORKSHOP_OUT or r["op"] in ("none", "ready")]
        index[("workshop", session)] = len(passes["workshop"])
        passes["workshop"].append({
            "label": "%s · after %s%s" % (_short(rs[0]["at"]), names.get(session, "a session"),
                                       (" · " + ends[-1]) if ends else ""),
            "steps": _workshop_way(rs)})
    if aside:
        # On a map of its own (a run, a sync): the last pass there that
        # reaches it stands there now.
        for name, ps in passes.items():
            if ps and here in node_sets_named().get(name, {}):
                last = ps[-1]["steps"]
                hit = [x for x in last if x.get("n") == here]
                (hit[-1] if hit else last.append({"n": here}) or last[-1])["here"] = True
    steps = []
    for s in out:
        if "pass" in s:
            i = index.get(tuple(s["pass"]))
            if i is not None:
                steps.append({"pass": [s["pass"][0], i]})
        else:
            steps.append(s)
    deviations(steps)
    return {"visits": steps, "passes": passes,
            "metrics": metrics(rows, steps, passes, transcripts),
            "now": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}


# A map of its own is reached from a block marked with its letter: a pass
# between two places neither of which carries it is the feature going where
# the map does not say.
PASS_LETTER = {"regression": "R", "sync": "S", "friction": "F", "workshop": "W"}


def deviations(steps):
    """Marks in place each pass the map does not lead to from where it ran
    (`off`, a sentence): the places before and after it carry no letter of
    its map. A jump with no way on the map is marked as it is played (history)."""
    for i, s in enumerate(steps):
        if "pass" not in s:
            continue
        letter = PASS_LETTER.get(s["pass"][0])
        # Its block may stand a gate or two back: a run after your yes on
        # step 2's work is played after "Does it work?" (history's fill).
        before = []
        for x in steps[:i][::-1]:
            if "n" in x:
                before.append(x["n"])
                if len(before) == 3 or NODES.get(x["n"], ("",) * 3)[2] not in WAITS_ON:
                    break
        near = before + [x["n"] for x in steps[i + 1:] if "n" in x][:1]
        # Or a pass beside it whose map has the letter: a fixing session's
        # friction review (F on the regression map), a review's change to
        # sclaude (W on the friction map).
        beside = [x["pass"][0] for x in steps[max(0, i - 1):i + 2] if "pass" in x and x is not s]
        if any(letter in n[5] for m in beside for n in node_sets_named().get(m, {}).values()):
            continue
        if letter and near and not any(letter in NODES.get(n, ("",) * 6)[5] for n in near):
            ends = [near[0]] + near[len(before):] if before else near
            names = " and ".join(NODES.get(n, ("",) * 4)[3] or n for n in ends)
            if len(ends) == 1:
                names = "here and " + names
            s["off"] = "%s ran between %s, and no block there carries %s" % (
                {"regression": "a regression", "sync": "a sync with main", "friction": "a friction review",
                 "workshop": "a change to sclaude"}[s["pass"][0]], names, letter)


# --- what each place took ----------------------------------------------------
#
# Shown on the maps by the checkboxes above them, never in the History:
#
#   input   each time the person stepped in — a message typed to Claude after
#           its turn or an answer to its question (claude_usage's `human`), an
#           answer to sclaude's own question (`ask answered`, io.sh) and a
#           command run on the feature at the terminal (`command`, state.sh) —
#           counted on the place the feature stood on at that moment;
#   cost    the dollars Claude Code's own account gives each conversation,
#           on the place the conversation ran;
#   wait    the seconds a question waited for the person's answer, counted
#           on the place the answer came in: Claude's, after its turn or its
#           question (claude_usage's `human`, not capped), and sclaude's own
#           (`ask answered waited=`, ask_once in ui.sh).
#
# Both as {map: {node: total}}, the friction review's over every review;
# each stay carries its own share as well ("m", {kind: n}), which the player
# adds up step by step. A workshop's work is done in the conversation of the
# step or the review that opened it, and counts there.

def _session_place(rows, opened=None):
    """Where each conversation ran, from the rows that opened it; with
    `opened`, a dict, when it was last opened there too."""
    out = {}
    for r in rows:
        if r["op"] not in ("open", "start") or not r.get("session"):
            continue
        head, _, rest = r["what"].partition(".")
        if head == "steps" and rest in NODES:
            out[r["session"]] = ("detail", rest)
        elif head == "fix" and rest in STAGE_NODE:
            out[r["session"]] = ("regression", "fix_" + rest)
        elif r["what"] == "sync":
            out[r["session"]] = ("sync", "sync")
        elif r["what"] in ("retro", "epilogue"):
            out[r["session"]] = ("detail", r["what"])
        elif head == "friction":
            out[r["session"]] = ("friction", "f_review")
        else:
            continue
        if opened is not None:
            opened[r["session"]] = r["at"]
    return out


def metrics(rows, steps, passes, transcripts):
    stays = [("detail", s) for s in steps if "n" in s]
    stays += [(m, s) for m, ps in passes.items() for p in ps for s in p["steps"]]
    timed = [(m, s["n"], _when(s["from"]), _when(s.get("to")) or _when(s["from"]), s)
             for m, s in stays if s.get("from")]

    def place(at, inside_only=False):
        when = _when(at)
        if not when:
            return None
        inside = [t for t in timed if t[2] <= when <= t[3]]
        if inside:
            return min(inside, key=lambda t: t[3] - t[2])[:2]
        if inside_only:
            return None
        before = [t for t in timed if t[0] == "detail" and t[2] <= when]
        return max(before, key=lambda t: t[2])[:2] if before else None

    def stay_of(where, at):
        """The stay at that place the moment falls in, else the last one
        begun before it, else the first, timed or not: where the player adds
        it up."""
        mine = [t for t in timed if t[:2] == where]
        if not mine:
            return next((st for m, st in stays if (m, st["n"]) == where), None)
        when = _when(at)
        inside = [t for t in mine if when and t[2] <= when <= t[3]]
        before = [t for t in mine if when and t[2] <= when]
        return (min(inside, key=lambda t: t[3] - t[2]) if inside else
                max(before, key=lambda t: t[2]) if before else mine[0])[4]

    out = {"input": {}, "cost": {}, "wait": {}}
    detail = [t for t in timed if t[0] == "detail"]

    def ahead(at):
        """The detailed block a sync at this moment ran ahead of, one marked
        S: the stay that holds it (the merge's wait), else the next one."""
        when = _when(at)
        marked = [t for t in detail if "S" in NODES.get(t[1], ("",) * 6)[5]]
        if not when or not marked:
            return None
        inside = [t for t in marked if t[2] <= when <= t[3]]
        later = [t for t in marked if t[2] > when]
        pick = min(inside, key=lambda t: t[3] - t[2]) if inside else \
            min(later, key=lambda t: t[2]) if later else max(marked, key=lambda t: t[2])
        return pick[1]

    def add(kind, where, n, at=None):
        if where and n:
            box = out[kind].setdefault(where[0], {})
            box[where[1]] = round(box.get(where[1], 0) + n, 4)
            # And on the stay itself, for the player's count step by step.
            stay = stay_of(where, at)
            if stay is not None:
                box = stay.setdefault("m", {})
                box[kind] = round(box.get(kind, 0) + n, 4)
            # The glance draws no sync: what one took counts under the block
            # it ran ahead of ("ahead", the page's totals for the overview),
            # by when its pass began: a pass broken off and resumed later is
            # still drawn ahead of that one.
            node = ahead((stay or {}).get("from") or at) if where[0] == "sync" else None
            if node:
                box = out[kind].setdefault("ahead", {})
                box[node] = round(box.get(node, 0) + n, 4)

    for r in rows:
        if (r["what"], r["op"]) == ("ask", "answered") or r["what"] == "command":
            add("input", place(r["at"]), 1, r["at"])
        if (r["what"], r["op"]) == ("ask", "answered") and str(r.get("waited", "")).isdigit():
            add("wait", place(r["at"]), int(r["waited"]), r["at"])
    counted, opened = set(), {}
    for session, where in _session_place(rows, opened).items():
        summary = transcripts(session) if transcripts else None
        # Two ids of one conversation carried on: its last transcript once.
        if not summary or summary.get("id", session) in counted:
            continue
        counted.add(summary.get("id", session))
        for turn in summary.get("human") or []:
            # Within its conversation: where the feature stood then, or
            # where the conversation ran when no stay holds the moment.
            at = place(turn[0], True) or where
            add("input", at, 1, turn[0])
            # How long Claude waited for the person, the whole of it: a
            # night left unanswered is a night (a summary older than the
            # field gives the capped time).
            add("wait", at, turn[3] if len(turn) > 3 else turn[1], turn[0])
        add("cost", where, summary.get("cost") or 0, opened.get(session))
    return out


def transcripts_of(state_path):
    """The sessions' summaries, read from Claude Code's transcripts of the
    feature's tree and kept beside its state by size and time, so a poll
    reads only the conversations that grew."""
    import claude_usage
    from session_end import SESSION_ID, next_link
    feature = os.path.dirname(state_path)
    tree = os.path.dirname(os.path.dirname(os.path.dirname(feature)))
    folder = os.path.join(claude_usage.ROOT, claude_usage.project_name(tree))
    cache_path = os.path.join(feature, TRANSCRIPT_CACHE)
    try:
        with open(cache_path) as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    changed = []

    def one(path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        stamp = [st.st_size, st.st_mtime_ns]
        held = cache.get(path)
        # A conversation still going grows between two polls: read again
        # at most once a minute, not its whole transcript every poll.
        if held and len(held) == 3 and (held[0] == stamp or time.time() - held[2] < TRANSCRIPT_FRESH):
            return held[1]
        whole = claude_usage.read(path)
        if whole is None:
            return None  # not read: tried again next time, not kept as empty
        summary = {"human": whole.get("human") or [], "cost": whole.get("cost")}
        cache[path] = [stamp, summary, time.time()]
        changed.append(path)
        return summary

    def after(path):
        """The transcript a conversation was carried on in, or None: one
        link of session_end.chain (next_link), kept as `one` keeps its
        summaries. A successor named but not on disk yet is looked for again
        next time."""
        st = os.stat(path)
        stamp, key = [st.st_size, st.st_mtime_ns], "next:" + path
        held = cache.get(key)
        if held and len(held) == 3 and (held[0] == stamp or time.time() - held[2] < TRANSCRIPT_FRESH):
            nxt = held[1]
        else:
            try:
                sid = next_link(path)
            except OSError:
                raise  # read again next time, not kept as "no link"
            nxt = os.path.join(folder, sid + ".jsonl") if sid else None
            cache[key] = [stamp, nxt, time.time()]
            changed.append(key)
        # The link is kept even before its transcript is there: a stat on
        # every poll, not a read of the whole file.
        return nxt if nxt and os.path.isfile(nxt) else None

    def read(session):
        """A conversation as its last transcript holds it whole: Claude Code
        carries one on under a new id by copying it, the rule
        session_end.chain reads it by."""
        if not SESSION_ID.match(session or ""):
            return None
        last = os.path.join(folder, session + ".jsonl")
        seen = set()
        while last not in seen:
            seen.add(last)
            # A link not read leaves the conversation unknown this time: an
            # earlier transcript taken for the last would count it twice.
            try:
                nxt = after(last)
            except OSError:
                return None
            if not nxt:
                break
            last = nxt
        summary = one(last)
        return dict(summary, id=last) if summary else None

    def done():
        if changed:
            # Transcripts gone (a tree cleaned up by hand) leave no keys.
            for key in [k for k in cache if not os.path.exists(k.replace("next:", "", 1))]:
                del cache[key]
            tmp = "%s.%d.tmp" % (cache_path, os.getpid())
            try:
                with open(tmp, "w") as fh:
                    json.dump(cache, fh)
                os.replace(tmp, cache_path)
            except OSError:
                pass
    read.done = done
    return read


def read_history(state_path):
    """The rows of the history file beside a state."""
    lines = []
    try:
        with open(os.path.join(os.path.dirname(state_path), HISTORY_FILE)) as fh:
            for line in fh:
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return lines


# --- drawing -----------------------------------------------------------------

LANE_W = 246
NODE_W = 198
NODE_H = 78
# The strip under a block the feature's page writes in: its metrics, the
# player's count (drawMetrics, the player's tag).
UNDER = 16
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
        # left (or the right, below), as edges running back take one on the
        # right — one for each block they go into (_route: the trunks).
        self.detours = [e for e in edges if not self.is_back(e) and self.blocked(e)]
        # One between two lanes right of the middle goes round on the right,
        # its runs the shorter, inside the ways back there.
        order = {lane: i for i, (lane, _) in enumerate(lanes)}
        self.east = [e for e in self.detours
                     if min(order[nodes[e[0]][0]], order[nodes[e[1]][0]]) > (len(lanes) - 1) / 2]
        west = {e[1] for e in self.detours if e not in self.east}
        # A channel per block the detours go into (body: the trunks).
        self.left = CHANNEL * (len(west) + 1) if west else 0
        self.lane_x = {lane: self.left + i * LANE_W for i, (lane, _) in enumerate(lanes)}
        # A channel per block the ways back go into (body: the trunks).
        backs = {e[1] for e in edges if self.is_back(e)} | {("east", e[1]) for e in self.east}
        self.right = self.left + len(lanes) * LANE_W
        self.width = self.right + CHANNEL * (len(backs) + 1) + 8
        # The ways routed first — across the map, and how far under or over a
        # block each turns — then each gap as tall as what turns in it
        # (_rows), and the turns put where the rows came out (_place).
        self.top = [0] * self.rows
        self._route()
        self._rows()
        self._place()

    def center(self, nid):
        lane, row = self.nodes[nid][0], self.nodes[nid][1]
        return self.lane_x[lane] + LANE_W / 2, self.top[row] + NODE_H / 2

    def is_back(self, edge):
        return self.nodes[edge[1]][1] < self.nodes[edge[0]][1]

    def blocked(self, edge):
        """Whether a node stands in an edge's way down: a way leaves its block
        right under it and goes down in the target's lane, so a node there
        between the two rows is in its way."""
        (_la, ra), (lb, rb) = self.nodes[edge[0]][:2], self.nodes[edge[1]][:2]
        return any(n[0] == lb and ra < n[1] < rb for nid, n in self.nodes.items() if nid not in edge[:2])

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
        badge = x + w - 6
        for flag in "FWRS":
            if flag in flags:
                # The ring turns while the review or the workshop is at work
                # (busy, lit by the feature's page).
                # Why the letter is on this block, shown on hover; the page
                # adds how the work is going while it is at work.
                why = badge_why(nid, flag)
                out.append('<g class="badge b-%s" data-why="%s"><title>%s</title>'
                           '<circle class="ring" cx="%.1f" cy="%.1f" r="13"/>'
                           '<circle class="dot" cx="%.1f" cy="%.1f" r="10"/>'
                           '<text x="%.1f" y="%.1f" text-anchor="middle">%s</text></g>'
                           % (flag, esc(why), esc(why), badge, y + 2, badge, y + 2, badge, y + 6.5, flag))
                badge -= 26
        out.append("</g>")
        return "\n".join(out)

    def edge(self, edge, index):
        """An arrow by the three rules (corners, levels, entries): out of a
        side's corner along its row, or from below turning on its level right
        under its block; into its target's top at its own point, a way from
        a channel turning above the target's row at its own height. A way
        round by a channel into a block others go round into too ends at
        their trunk, with a small arrow (_route: self.trunk)."""
        a, b, label, kind = edge
        ax, ay = self.center(a)
        bx, by = self.center(b)
        half = NODE_H / 2
        if self.nodes[a][1] == self.nodes[b][1]:
            side = 1 if bx > ax else -1
            dy = 9 if side > 0 else -9
            pts = [(ax + side * NODE_W / 2, ay + dy), (bx - side * NODE_W / 2, by + dy)]
            lx, ly, anchor = (ax + bx) / 2, (ay + dy - 4 if side < 0 else ay + dy + 13), "middle"
        else:
            ex, top = bx + self.entry.get(index, 0), by - half
            corner = self.corner.get(index)
            y = self.run_y(index)
            if corner:
                start = [(ax + corner * NODE_W / 2, ay)]
                lx, ly, anchor = ax + corner * (NODE_W / 2 + 6), ay - 5, "start" if corner > 0 else "end"
            else:
                start = [(ax, ay + half), (ax, y)]
                lx, ly, anchor = (ax - 6, y - 3, "end") if self.goes_left(edge) else (ax + 6, y - 3, "start")
                # A labelled way straight down has its label where this one's
                # would be: this one's goes out past the block's edge.
                if self.reach(edge) >= 1 and any(
                        e[0] == a and e[2] and e is not edge and self.reach(e) < 1 for e in self.edges):
                    lx += (-1 if anchor == "end" else 1) * NODE_W / 2
            if index in self.channel_x:
                cx, turn = self.channel_x[index], self.turn[index]
                pts = start + [(cx, y), (cx, turn), (ex, turn), (ex, top)]
            else:
                pts = start + [(ex, y), (ex, top)]
        path = "M" + " L".join("%.1f %.1f" % p for p in pts)
        # A wide transparent twin under the line: something to point at.
        out = ['<g class="edge e-%s" data-key="e:%s:%d">' % (kind or "flow", self.name, index),
               '<path class="hit" d="%s"/>' % path]
        if index in self.trunk:
            # Its own run ends at the trunk; the rest of its way, the trunk's,
            # shows only while it is lit.
            k = len(start) + 1
            out += ['<path class="line" d="M%s" marker-end="url(#join%s-%s)"/>'
                    % (" L".join("%.1f %.1f" % p for p in pts[:k]),
                       "-back" if self.is_back(edge) else "", self.name),
                    '<path class="line ride" d="M%s" marker-end="url(#arrow-%s)"/>'
                    % (" L".join("%.1f %.1f" % p for p in pts[k - 1:]), self.name)]
        else:
            out.append('<path class="line" d="%s" marker-end="url(#arrow-%s)"/>' % (path, self.name))
            # On a trunk, a chevron past each way joining it: the way on is up
            # a trunk back, down a detour's.
            cx = self.channel_x.get(index)
            up = -1 if self.is_back(edge) else 1
            for y in sorted(self.run_y(i) for i, j in self.trunk.items() if j == index):
                out.append('<path class="chev" d="M%.1f %.1f L%.1f %.1f L%.1f %.1f"/>'
                           % (cx - 3.5, y + up * 5, cx, y + up * 9, cx + 3.5, y + up * 5))
        if label:
            out.append('<text class="el" x="%.1f" y="%.1f" text-anchor="%s">%s</text>'
                       % (lx, ly, anchor, esc(label)))
        out.append("</g>")
        return "\n".join(out)

    def run_y(self, index):
        """The height a way runs across at, and meets a trunk at: its row's
        middle from a corner, its level under the block from below."""
        if index in self.corner:
            return self.center(self.edges[index][0])[1]
        return self.level[index]

    def goes_left(self, edge):
        """A detour round the left, or a way to a lane on the left; a way back
        goes right, as a detour round the right does."""
        if edge in self.east:
            return False
        return edge in self.detours or (not self.is_back(edge)
                                        and self.center(edge[1])[0] < self.center(edge[0])[0] - 1)

    def reach(self, edge):
        """How far across a way runs: a way to a channel, the farthest."""
        if self.is_back(edge) or edge in self.detours:
            return float("inf")
        return abs(self.center(edge[1])[0] - self.center(edge[0])[0])

    def corners(self):
        """Rule 1, the corners: on each side of a block, the way reaching
        farthest that side leaves from its corner and runs along the row —
        when the row is clear that far and no arrow to a block of the same
        row takes that side. {edge index: 1 right, -1 left}."""
        out, ways = {}, {}
        for i, e in enumerate(self.edges):
            ways.setdefault(e[0], []).append((i, e))
        for a, es in ways.items():
            ax, row = self.center(a)[0], self.nodes[a][1]
            for side in (1, -1):
                best, taken = None, False
                for i, e in es:
                    bx = self.center(e[1])[0]
                    if self.nodes[e[1]][1] == row:
                        taken = taken or (bx - ax) * side > 0
                        continue
                    reach = self.reach(e)
                    # A way straight down has no side to leave by.
                    if (side < 0) != self.goes_left(e) or reach < 1:
                        continue
                    if any(n[1] == row and 0 < (self.center(nid)[0] - ax) * side <= reach
                           for nid, n in self.nodes.items() if nid not in (a, e[1])):
                        continue
                    if best is None or reach > best[0]:
                        best = (reach, i)
                if best and not taken:
                    out[best[1]] = side
        return out

    def levels(self):
        """Rule 1, from below: the other ways turn right under their block,
        per side — left, or right and straight down — each on its own level,
        the farthest first, so none crosses another on its way. {index: how
        far under its block}."""
        out, sides = {}, {}
        for i, e in enumerate(self.edges):
            if i in self.corner or self.nodes[e[0]][1] == self.nodes[e[1]][1]:
                continue
            sides.setdefault((e[0], self.goes_left(e)), []).append((-self.reach(e), i))
        for (a, _left), ways in sides.items():
            # From 12 under it, so a label 3 above its line clears the block.
            step = min(12, 20 / (len(ways) - 1)) if len(ways) > 1 else 0
            for k, (_reach, i) in enumerate(sorted(ways)):
                out[i] = 12 + k * step
        # Ways from one row into one block would share their level and merge:
        # the nearer source's turns higher, so a farther one's drop does not
        # cross it.
        into = {}
        for i, e in enumerate(self.edges):
            if i in out and i not in self.channel_x:
                ax, bx = self.center(e[0])[0], self.center(e[1])[0]
                into.setdefault((e[1], self.nodes[e[0]][1]), []).append((self.reach(e), min(ax, bx), max(ax, bx), i))
        for ways in into.values():
            ways.sort()
            for k, (_reach, lo, hi, i) in enumerate(ways):
                # Moved by the nearer ways whose run shares a stretch with it.
                out[i] += 3 * sum(1 for _r, lo2, hi2, _i in ways[:k] if max(lo, lo2) < min(hi, hi2))
        return out

    def entries(self):
        """Rules 2 and 3, the way in: several ways into one block enter its
        top apart, left of its letters (BPMN asks no shared point), in the
        order they come from — the left channel and the blocks by x, then
        a detour round the right, then the way back, the farthest channel
        innermost, so their runs nest. The ways round by one channel into a
        block come in as one, by their trunk.
        A way from a channel turns above its target's row by how near its
        channel is, the nearest lowest. Returns ({index: x offset},
        {index: how far over its target's top it turns})."""
        entry, turn, into, rows = {}, {}, {}, {}
        for i, e in enumerate(self.edges):
            # A way into a trunk comes in where the trunk does.
            if self.nodes[e[0]][1] == self.nodes[e[1]][1] or i in self.trunk:
                continue
            came = self.channel_x.get(i, self.center(e[0])[0])
            back = self.is_back(e)
            east = back or e in self.east
            # From the right, a detour enters left of the ways back: it
            # turns above them, so their runs stop short of its drop.
            into.setdefault(e[1], []).append((2 if back else 1 if east else 0, -came if east else came, i))
            if i in self.channel_x:
                near = abs(self.channel_x[i] - (self.right if east else self.left))
                # A way back comes up its channel, the nearest turning lowest;
                # a detour comes down the left one, the farthest lowest. The
                # ways back take the lowest heights, the detours those above.
                rows.setdefault(self.nodes[e[1]][1], []).append((not back, near if back else -near, i))
        for b, ways in into.items():
            if len(ways) < 2:
                continue
            letters = len(self.nodes[b][5])
            lo, hi = -NODE_W / 2 + 16, (NODE_W / 2 - 16 if not letters else NODE_W / 2 - 22 - 26 * letters)
            step = min(22, (hi - lo) / (len(ways) - 1))
            for k, (_back, _came, i) in enumerate(sorted(ways)):
                entry[i] = (lo + hi) / 2 + (k - (len(ways) - 1) / 2) * step
        for row, ways in rows.items():
            # 12 px off the block, so the arrowhead has its drop, then 4
            # apart; the gap is made tall enough for them and the levels
            # under the row above (_rows).
            for k, (_detour, _near, i) in enumerate(sorted(ways)):
                turn[i] = 12 + k * 4
        for i, j in self.trunk.items():
            if j in entry:
                entry[i] = entry[j]
            turn[i] = turn[j]
        return entry, turn

    def _route(self):
        """The ways' channels, corners, levels and turns, by the rows' tops."""
        self.corner = self.corners()
        # Rule 3, the channels: the ways back on the right nested — one going
        # up fewer rows nearer, a longer one round it; of two as long, the
        # one into the block further right nearer — the detours on their side
        # nested too (nest).
        #
        # The ways round by a channel into one block share it, a trunk, one
        # per side — back on the right, round the right, round the left: each
        # runs along its row into it, and one carries it in, with the arrow
        # (self.trunk: a way -> the one carrying it). Where a way meets its
        # channel, down the map: its row, and in the row a corner's run (the
        # row's middle) above a level (under it). A way back is carried by the
        # one meeting it lowest, a detour by the one meeting it highest.
        def meets(i):
            return (self.nodes[self.edges[i][0]][1], 0 if i in self.corner else 1)

        def side(e):
            return "back" if self.is_back(e) else ("east" if e in self.east else "west") if e in self.detours else ""
        carrier = {}
        for i, e in enumerate(self.edges):
            if side(e):
                key, j = (side(e), e[1]), carrier.get((side(e), e[1]))
                if j is None or (meets(i) > meets(j) if key[0] == "back" else meets(i) < meets(j)):
                    carrier[key] = i
        self.trunk = {i: carrier[(side(e), e[1])] for i, e in enumerate(self.edges)
                      if side(e) and carrier[(side(e), e[1])] != i}

        # Nested: a detour into a higher row nearer; into one row, the one
        # reaching farther across nearer, turning higher (entries), so neither
        # crosses the other. The detours round the right run nearest the
        # lanes, the ways back past them.
        def nest(i, way):
            b = self.edges[i][1]
            return (self.nodes[b][1], -way * self.center(b)[0], i)
        east = sorted((c for (k, _b), c in carrier.items() if k == "east"), key=lambda i: nest(i, -1))
        backs = sorted((c for (k, _b), c in carrier.items() if k == "back"), key=lambda i: (
            self.nodes[self.edges[i][0]][1] - self.nodes[self.edges[i][1]][1],
            -self.center(self.edges[i][1])[0], i))
        west = sorted((c for (k, _b), c in carrier.items() if k == "west"), key=lambda i: nest(i, 1))
        self.channel_x = {i: self.right + CHANNEL * (k + 1) for k, i in enumerate(east + backs)}
        self.channel_x.update({i: self.left - CHANNEL * (k + 1) for k, i in enumerate(west)})
        self.channel_x.update({i: self.channel_x[j] for i, j in self.trunk.items()})
        self.level_off = self.levels()
        self.entry, self.turn_off = self.entries()

    def _place(self):
        """The levels and the turns where the rows came out."""
        self.level = {i: self.top[self.nodes[self.edges[i][0]][1]] + NODE_H + off
                      for i, off in self.level_off.items()}
        self.turn = {i: self.top[self.nodes[self.edges[i][1]][1]] - off for i, off in self.turn_off.items()}

    def _rows(self):
        """Each row's top, its gap above as tall as what runs in it: the
        levels the ways under the row above turn on and the turns of the ways
        into the row — 30 px where only a way straight down crosses it, room
        for its label and its arrowhead.

        Where no way turns under the upper row — they all leave from its
        blocks' middles — the lower row rises: under what is drawn above it in
        its own lanes, a drop for the arrowheads under the middles' runs, its
        own runs and their labels clear of the blocks above, and the turns of
        the ways coming into it by a channel under the middles' runs and
        clear of the blocks they pass."""
        lev, above = [0] * (self.rows + 1), [0] * (self.rows + 1)
        sides = [False] * (self.rows + 1)
        for i, e in enumerate(self.edges):
            ra = self.nodes[e[0]][1]
            if i in self.level_off:
                lev[ra] = max(lev[ra], self.level_off[i])
            if i in self.corner:
                sides[ra] = True
            if i in self.turn_off:
                rb = self.nodes[e[1]][1]
                above[rb] = max(above[rb], self.turn_off[i])
        drawn = {}
        for nid, (_lane, row, kind, _t, text, _f) in self.nodes.items():
            drawn[nid] = NODE_H
            if kind in ("start", "end"):
                # The words under the circle (shape): its title, then the text.
                lines = len(wrap(text, 30)[:2])
                drawn[nid] = 2 * 13 + 16 + (14 + 13 * (lines - 1) if lines else 0) + 4
        tops, y = [], TOP + max(above[0], 14) + 6
        for r in range(self.rows):
            tops.append(y)
            step = NODE_H + max(30, lev[r] + max(above[r + 1], 14) + 6)
            upper = {n[0]: drawn[nid] for nid, n in self.nodes.items() if n[1] == r}
            if r + 1 < self.rows and upper and not lev[r]:
                lower = [n[0] for n in self.nodes.values() if n[1] == r + 1]
                # Under every block the page writes a line of its own (its
                # metrics, the player's count, 13 px), and a block's letters
                # stand 13 px over its top: in one lane, both fit between.
                rise = [upper[lane] + UNDER + 14 for lane in lower if lane in upper]
                if sides[r]:
                    rise.append(NODE_H / 2 + 14)
                # Its own middles' runs, their labels 15 px above them, clear
                # of the blocks above and the line under them.
                rise.append(max(upper.values()) + UNDER + 15 - NODE_H / 2)
                # A way into the lower row from a channel turns over it: its
                # run under the upper row's middles, and clear of the line
                # under any block above that it passes.
                for i, off in self.turn_off.items():
                    e = self.edges[i]
                    if self.nodes[e[1]][1] != r + 1 or i in self.trunk:
                        continue
                    ends = sorted((self.channel_x[i], self.center(e[1])[0] + self.entry.get(i, 0)))
                    rise.append(NODE_H / 2 + 14 + off)
                    rise += [drawn[nid] + UNDER + off for nid, n in self.nodes.items() if n[1] == r
                             and ends[0] < self.center(nid)[0] + NODE_W / 2
                             and ends[1] > self.center(nid)[0] - NODE_W / 2]
                step = min(step, max(rise))
            y += step
        self.top = tops
        last = [drawn[nid] for nid, n in self.nodes.items() if n[1] == self.rows - 1]
        self.height = int(tops[-1] + max(last + [NODE_H]) + max(lev[self.rows - 1], 0) + 20)

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
        for i, e in enumerate(self.edges):
            parts.append(self.edge(e, i))
        for nid in self.nodes:
            parts.append(self.shape(nid))
        return "\n".join(parts)

    def svg(self, symbol=False):
        defs = ('<defs><marker id="arrow-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" '
                'markerHeight="10" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="ah"/>'
                '</marker>' % self.name
                # Half as large, where a way joins a trunk.
                + "".join('<marker id="join%s-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
                          'markerHeight="6" markerUnits="userSpaceOnUse" orient="auto">'
                          '<path d="M0 0 L10 5 L0 10 z" class="%s"/></marker>' % (kind, self.name, cls)
                          for kind, cls in (("", "ah"), ("-back", "ahb")))
                + '</defs>')
        if symbol:
            return ('<svg class="defs" width="0" height="0" aria-hidden="true">%s<symbol id="sym-%s" '
                    'viewBox="0 0 %d %d">%s</symbol></svg>' % (defs, self.name, self.width, self.height, self.body()))
        # Never wider than drawn, so every map is at one scale; narrower when
        # the window is (it scales down to fit), and on a phone no narrower
        # than 760 px — but a map narrower than that is not stretched to it.
        cap = ' style="max-width:%dpx;min-width:%dpx"' % (self.width, min(760, self.width))
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
/* A map's card hugs its map: no empty field round a narrow one. */
.card:has(> svg.map){width:fit-content;max-width:100%;margin-inline:auto}
svg.map{display:block;width:100%;height:auto;min-width:760px;margin:0 auto}
.lane{stroke:var(--line);stroke-width:1}
.lane{fill:var(--lane-a)}.lane.alt{fill:var(--lane-b)}.l-gutter{fill:var(--surface);stroke:none}
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
.badge .dot{stroke:none}.badge text{font:700 12px var(--body);fill:#fff}
.b-F .dot{fill:var(--signal)}.b-W .dot{fill:var(--cloud)}.b-R .dot{fill:var(--human)}.b-S .dot{fill:var(--auto)}
.badge .ring{fill:none;stroke-width:0;opacity:0}
.b-F .ring{stroke:var(--signal)}.b-W .ring{stroke:var(--cloud)}.b-R .ring{stroke:var(--human)}.b-S .ring{stroke:var(--auto)}
.badge.busy .ring{opacity:1;stroke-width:3;stroke-dasharray:21 6.2;
  animation:ring-turn 1.4s linear infinite,ring-beat 1.4s ease-in-out infinite}
@keyframes ring-turn{to{stroke-dashoffset:-81.7}}
@keyframes ring-beat{50%{stroke-width:5}}
@media (prefers-reduced-motion:reduce){.badge.busy .ring{animation:none;stroke-width:4}}
.badge.stalled .ring{opacity:1;stroke:var(--human);stroke-width:3}
.edge path{fill:none;stroke:var(--muted);stroke-width:1.4}
.e-back path{stroke:var(--human);stroke-dasharray:6 4}
.e-msg path{stroke:var(--cloud);stroke-dasharray:2 3}
.ah{fill:var(--muted)}.ahb{fill:var(--human)}
.edge path.chev{fill:none;stroke:var(--muted);stroke-width:1.6;stroke-dasharray:none}
.e-back path.chev{stroke:var(--human)}
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
.edge path.ride{opacity:0}
.edge.is-focus path.ride,.edge.is-lit path.ride,.edge.pl-go path.ride,.edge.pl-went path.ride{opacity:1}
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
.legend-maps{margin-top:6px}
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
</ul>
<ul class="legend legend-maps">
<li><span class="sw" style="background:var(--signal);border-color:var(--signal);border-radius:50%;width:14px"></span>F — a friction review follows (<a href="#map-friction">its own map</a>)</li>
<li><span class="sw" style="background:var(--cloud);border-color:var(--cloud);border-radius:50%;width:14px"></span>W — may change sclaude in its workshop (<a href="#map-workshop">its own map</a>)</li>
<li><span class="sw" style="background:var(--human);border-color:var(--human);border-radius:50%;width:14px"></span>R — a regression runs here (<a href="#map-regression">its own map</a>)</li>
<li><span class="sw" style="background:var(--auto);border-color:var(--auto);border-radius:50%;width:14px"></span>S — main is checked here (<a href="#map-sync">its own map</a>)</li>
<li>The issue's summary comment — sessions, rounds, reviews — is rewritten at every step, by sclaude itself</li>
</ul>"""


# Where each command is open, by the words of its "When": the detailed nodes
# a feature may stand on when it shows. Hovering a node lights the commands
# open there.
def _rows(lo, hi):
    return [nid for nid, n in NODES.items() if lo <= n[1] <= hi]


# A run and a sync come after step 1 and before the cycle ends; production's
# part of the regression map only once it shipped.
_SUB = list(REGRESSION_NODES) + list(SYNC_NODES)
_PROD = ["r_prod", "prod_ok", "rollback", "hold_ways", "fix_prod"]
WHEN = {
    "always": _rows(0, 34) + _SUB,
    "before the cycle ends": _rows(3, 15) + _SUB,
    "a finished feature": _rows(16, 34) + _PROD,
    "with a pull request": _rows(10, 34) + _SUB,
    "after step 1": _rows(6, 34) + _SUB,
    "once production carried it": _rows(26, 34) + _PROD,
    "production red and carrying it": ["hold_ways"],
    "with friction logged": [nid for nid, n in all_nodes().items() if "F" in n[5]],
    "at step 4 or done": _rows(11, 34) + _SUB,
    "an epilogue broken off": ["epilogue"],
    "monthly, offered": [],
    "in a session": [nid for nid, n in all_nodes().items() if n[2] == "session"],
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
              "W": "the session may change sclaude in its workshop",
              "R": "a regression runs here: its own map shows the run and its fixes",
              "S": "main is checked here: its own map shows the merge in and the sync"}


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
    # The overview's blocks that stand for a detailed one:
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
            "base": dict(ALIAS), "proj": projection()}


def projection():
    """Each detailed place as the overview draws it: the places a feature
    stands on (POSITIONS), and the blocks that borrow a detail (ALIAS). A
    place neither has is not on it."""
    out = {}
    for nid in all_nodes():
        o = POSITIONS.get(nid) or next((s for s, big in ALIAS.items() if big == nid), "")
        if o:
            out[nid] = o
    return out


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
            '<button type="button" class="pin" title="Unpin: the full list stays in section %d" aria-label="Unpin">📌</button>'
            '</div><ul>%s</ul></aside>' % (len(shown), len(SECTIONS), items))


def commands_table():
    rows = []
    for i, (cmd, _verb, when, what, target) in enumerate(COMMANDS):
        # A place this project's map does not draw is left out.
        shown = all_nodes()
        lead = ", ".join("where the feature stands" if t == "@here" else esc(shown[t][3])
                         for t in places(target) if t == "@here" or t in shown)
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
    + 'a page for the overview, and the commands';
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
SECTIONS = ["1. The cycle at a glance", "2. The whole process",
            "3. How a session changes sclaude", "4. The friction review",
            "5. A stage's regression", "6. Main and the branch",
            "7. Commands and where they lead"]


def running_heads():
    css = ['@page{@top-right{content:"sclaude — the process";font:9px sans-serif;color:#666}'
           '@bottom-right{content:"page " counter(page);font:9px sans-serif;color:#666}}']
    for n, title in enumerate(SECTIONS, start=1):
        # A CSS string, not JSON: json's \\uXXXX would print as "uXXXX".
        css.append('@page s%d{@top-left{content:"%s";font:600 10px sans-serif;color:#333}}'
                   % (n, title.replace("\\", "\\\\").replace('"', '\\"')))
    return "\n".join(css)


def doc(cfg=None):
    """The printed page: the maps as cfg draws them — a project's own, or,
    with none, the example config's (config.example.json), the cycle a
    typical project runs."""
    with configured(example_config() if cfg is None else cfg):
        return _doc()


def _doc():
    detail = Diagram(*node_sets()[0])
    overview = Diagram(*node_sets()[1])
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
<p class="muted">Every lane, every check and every way back.</p>
%s
<div class="card screen-only">%s</div>
%s
%s
</section><section style="page:s3" id="map-workshop">
<h2>%s</h2>
<p class="muted">Any session marked W may take this way: it changes sclaude in its tree's workshop, and sclaude
publishes the change once the session ends.</p>
<div class="card">%s</div>
</section><section style="page:s4" id="map-friction">
<h2>%s</h2>
<p class="muted">Every session marked F leads here once it ends: what the safety rules refused it is read by a
session of its own, which lifts a rule, leaves it, puts it off a month, or fixes sclaude.</p>
<div class="card">%s</div>
</section><section style="page:s5" id="map-regression">
<h2>%s</h2>
<p class="muted">Every block marked R runs a stage's suite here: the local one closes steps 2 and 4, the
preview's comes before QA, production's after the ship. Red goes to a fixing session, at most two, or back to
step 4; production is rolled back first.</p>
<div class="card">%s</div>
</section><section style="page:s6" id="map-sync">
<h2>%s</h2>
<p class="muted">Every block marked S checks main here: it is merged in without asking, and a conflict goes to
the sync session.</p>
<div class="card">%s</div>
</section><section style="page:s7">
<h2>%s <button type="button" class="pin pin-head screen-only">📌 Pin</button></h2>
<p class="muted">A feature's action list shows only those that apply to it now. A command lights the place it
leads to; a block lights the commands open there.</p>
%s
</section>
<button id="clear" class="screen-only" type="button" hidden>Clear the selection</button>
%s
</main><script>%s%s%s</script></body></html>
""" % (STYLE, running_heads(), LEGEND, esc(SECTIONS[0]), overview.svg(),
       esc(SECTIONS[1]), PRINT_BAR, detail.svg(), detail.svg(symbol=True), tiles(detail),
       esc(SECTIONS[2]), Diagram(*node_sets()[2]).svg(), esc(SECTIONS[3]), Diagram(*node_sets()[3]).svg(),
       esc(SECTIONS[4]), Diagram(*node_sets()[4]).svg(), esc(SECTIONS[5]), Diagram(*node_sets()[5]).svg(),
       esc(SECTIONS[6]), commands_table(),
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
  // F and W at work now: their rings turn.
  document.querySelectorAll('.badge.busy, .badge.stalled').forEach((b) => {
    b.classList.remove('busy', 'stalled');
    b.querySelector('title').textContent = b.dataset.why;
  });
  // The glance's blocks carry their step's letters (ALIAS):
  // they turn with it.
  Object.entries(v.busy || {}).forEach(([id, flags]) => flags.forEach((f) =>
    [id].concat(M.alias[id] || []).forEach((at) =>
    document.querySelectorAll('svg.map [data-node="' + at + '"] .b-' + f).forEach((b) => {
      b.classList.add('busy');
      // On hover, how it goes now, under why it is there.
      const note = ((v.notes || {})[id] || {})[f];
      b.querySelector('title').textContent = b.dataset.why + (note ? '\n' + note : '');
    }))));
  // A sync with main has no block on the glance: its S stands
  // on the block it runs ahead of, which is lit for it, the S turning — or,
  // broken off, standing still in the colour of a wait on the person.
  const syncAt = [];
  Object.entries(v.busy || {}).forEach(([id, flags]) => { if (flags.includes('S')) syncAt.push(id); });
  Object.entries(v.stalled || {}).forEach(([id, notes]) => {
    syncAt.push(id);
    [id].concat(M.alias[id] || [], POS[id] || []).forEach((at) =>
      document.querySelectorAll('svg.map [data-node="' + at + '"] .b-S').forEach((b) => {
        b.classList.add('stalled');
        b.querySelector('title').textContent = b.dataset.why + '\n' + notes.S;
      }));
  });
  (v.busy ? syncAt : []).forEach((id) => (POS[id] || []).forEach((at) =>
    document.querySelectorAll('svg.map [data-node="' + at + '"] .b-S').forEach((b) => {
      if (!b.classList.contains('stalled')) b.classList.add('busy');
    })));
  if (here) {
    [here].concat(POS[here] || (here === 'sync' ? syncAt.flatMap((id) => POS[id] || []) : [])).forEach((id) =>
      document.querySelectorAll('svg.map [data-node="' + id + '"]').forEach((n) => n.classList.add('here')));
  }
  if (here && here !== last) {
    // On the whole process, or on the map of its own a place has (R, S).
    const n = document.querySelector('svg.map-detail [data-node="' + here + '"]')
      || document.querySelector('svg.map [data-node="' + here + '"]');
    // Down to it only: centred across as well, the card scrolled the map's
    // first lanes off its left edge with no way to tell they were there.
    if (n && last === '') n.scrollIntoView({block: 'center', inline: 'nearest'});
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
  player.update(v.history);
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

# How the feature went, played on its maps (`history` above). ▶ by a map's
# heading plays the whole way on that map: a place lights with a clock
# counting the time it stood there, then the arrow it left by; a friction
# review or a workshop pass jumps to its own map and back. By the friction
# review's and the workshop's headings ▶ plays the pass chosen beside it.
# A place entered again keeps its count: "×2 · 3 h 10 min".
PLAY_SCRIPT = r"""
const player = (() => {
  let data = null, token = 0, paused = false, speed = 1;
  const bar = document.getElementById('player');
  const say = (t) => { bar.querySelector('.pl-text').textContent = t; };
  function dur(s) {
    if (s == null) return '';
    if (s < 60) return Math.round(s) + ' s';
    const m = Math.round(s / 60);
    if (m < 60) return m + ' min';
    const h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d) return d + ' d ' + (h % 24) + ' h';
    return h + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
  }
  function when(t) {
    if (!t) return '';
    const d = new Date(t);
    return d.toLocaleDateString(undefined, {day: 'numeric', month: 'short'}) + ' '
      + d.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'});
  }
  // A wait that stands still while paused and follows a change of speed.
  function sleep(ms, mine) {
    return new Promise((done) => {
      let left = ms, last = performance.now();
      const tick = () => {
        if (mine !== token) return done(false);
        const now = performance.now();
        if (!paused) left -= (now - last) * speed;
        last = now;
        if (left <= 0) return done(true);
        setTimeout(tick, 40);
      };
      setTimeout(tick, 40);
    });
  }
  function clear() {
    document.querySelectorAll('.pl-clock,.pl-tag,.pl-ghost').forEach((g) => g.remove());
    document.querySelectorAll('.pl-wrong').forEach((g) => g.classList.remove('pl-wrong'));
    document.getElementById('pl-off').hidden = true;
    document.querySelectorAll('.pl-now,.pl-seen,.pl-go,.pl-went').forEach((el) => {
      el.classList.remove('pl-now', 'pl-seen', 'pl-go', 'pl-went');
      delete el.__pl;
    });
    document.body.classList.remove('playing');
    played = null; current = null;
    drawMetrics();
  }
  function stop() {
    token++; paused = false; clear(); bar.hidden = true; playing = null;
    bar.querySelector('.pl-pause').textContent = '⏸';
    document.body.classList.remove('pl-paused');
    document.querySelectorAll('#hist li.on').forEach((li) => li.classList.remove('on'));
    document.querySelectorAll('.play').forEach((b) => { b.textContent = '▶'; b.classList.remove('on'); });
  }
  // What the person put in and Claude cost, by kind: {input, cost, wait}.
  function addUp(into, m) {
    Object.entries(m || {}).forEach(([k, v]) => { into[k] = (into[k] || 0) + v; });
    return into;
  }
  // While a play runs, the metrics under a block are what was played so far:
  // the stays done there (`played`, by map:node), and on the one playing now
  // its own share after a plus (`current`). A map the play does not go on
  // (`inPlay`) keeps its totals, and so does every map once it has played.
  let played = null, current = null, inPlay = new Set();
  // The detailed map's places as the overview draws them; one place
  // standing for several in a row is entered once, their times summed.
  function onMap(steps, map) {
    const out = [];
    steps.forEach((s) => {
      if (s.pass) { out.push(s); return; }
      const n = M.proj[s.n];
      if (!n) return;
      const last = out[out.length - 1];
      if (last && !last.pass && last.n === n) {
        last.off = last.off || s.off;
        if (s.s != null) last.s = (last.s || 0) + s.s;
        if (s.m) last.m = addUp(Object.assign({}, last.m), s.m);
        last.to = s.to || last.to; last.here = last.here || s.here;
        return;
      }
      out.push(Object.assign({}, s, {n: n}));
    });
    return out;
  }
  function edgeKey(map, a, b) {
    return Object.keys(M.edges).find((k) => k.startsWith(map + ':') && M.edges[k].f === a && M.edges[k].t === b);
  }
  function svgEl(map, sel) {
    const svg = document.querySelector('svg.map-' + map);
    return svg ? svg.querySelector(sel) : null;
  }
  function clock(g, s, ms, mine) {
    const box = g.querySelector('.shape').getBBox(), ns = 'http://www.w3.org/2000/svg';
    const c = document.createElementNS(ns, 'g');
    c.setAttribute('class', 'pl-clock');
    c.setAttribute('transform', 'translate(' + (box.x + 2) + ' ' + (box.y + 2) + ')');
    c.innerHTML = '<circle r="12"/><line class="pl-hand" x1="0" y1="0" x2="0" y2="-8"/>'
      + '<line x1="0" y1="0" x2="5" y2="0"/><text x="17" y="4"></text>';
    g.append(c);
    const text = c.querySelector('text'), hand = c.querySelector('.pl-hand');
    let gone = 0, last = performance.now();
    (function frame(t) {
      if (mine !== token || !c.isConnected) return;
      if (!paused) gone += (t - last) * speed;
      last = t;
      const f = Math.min(1, gone / ms);
      hand.setAttribute('transform', 'rotate(' + (f * 720) + ')');
      text.textContent = s != null ? dur(s * f) : '';
      if (f < 1) requestAnimationFrame(frame);
    })(last);
    return c;
  }
  function tag(g, n, s) {
    const seen = g.__pl || (g.__pl = {k: 0, s: 0});
    seen.k++; seen.s += s || 0;
    g.querySelectorAll('.pl-tag').forEach((t) => t.remove());
    if (!seen.s && seen.k < 2) return;
    const box = g.querySelector('.shape').getBBox(), ns = 'http://www.w3.org/2000/svg';
    const t = document.createElementNS(ns, 'text');
    t.setAttribute('class', 'pl-tag');
    t.setAttribute('x', box.x + 4); t.setAttribute('y', box.y + box.height + 12);
    t.textContent = [seen.k > 1 ? '×' + seen.k : '', seen.s ? dur(seen.s) : ''].filter(Boolean).join(' · ');
    g.append(t);
  }
  const TITLE = {friction: 'the friction review', workshop: 'how a session changes sclaude',
                 regression: "a stage's regression", sync: 'main and the branch'};
  // The maps a pass is played on, each a way of its own from the main one.
  const PASSES = Object.keys(TITLE);
  // What is being played, kept for the history list: a click there plays
  // from that place on.
  let playing = null;
  function arrow(prev, s) {
    if (!prev || prev.map !== s.map) return null;
    const k = edgeKey(s.map, prev.n, s.n);
    return k ? M.edges[k] : null;
  }
  // The places already passed, lit at once: a jump in the list lands with
  // what came before it as the play would have left it.
  function mark(steps, upto) {
    for (let i = 0; i < upto; i++) {
      const s = steps[i], g = svgEl(s.map, '[data-node="' + s.n + '"]');
      if (!g) continue;
      const k = i && steps[i - 1].map === s.map ? edgeKey(s.map, steps[i - 1].n, s.n) : null;
      const e = k && svgEl(s.map, '[data-key="e:' + k + '"]');
      if (e) e.classList.add('pl-went');
      g.classList.add('pl-seen');
      tag(g, s.n, s.s);
      done(s);
    }
    drawMetrics();
  }
  function done(s) {
    const key = s.map + ':' + s.n;
    played[key] = addUp(played[key] || {}, s.m);
  }
  async function run(steps, label, start) {
    stop();
    start = start || 0;
    const mine = ++token;
    playing = {steps: steps, label: label};
    played = {}; inPlay = new Set(steps.map((s) => s.map));
    document.body.classList.add('playing');
    bar.hidden = false;
    showTab('history');
    list(steps, label);
    mark(steps, start);
    let prev = start ? steps[start - 1] : null;
    for (let i = start; i < steps.length; i++) {
      const s = steps[i];
      pick(i);
      if (s.map !== (prev && prev.map) && prev) {
        say(label + ' · ' + (PASSES.includes(s.map)
          ? '↪ off to ' + TITLE[s.map] + (s.pass ? ': ' + s.pass : '') : '↩ back to the cycle'));
        if (!await sleep(1100, mine)) return;
      }
      const g = svgEl(s.map, '[data-node="' + s.n + '"]');
      if (s.off) deviate(prev, s, g);
      if (!g) { prev = s; continue; }
      g.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'smooth'});
      if (prev && prev.map === s.map) {
        const k = edgeKey(s.map, prev.n, s.n);
        const e = k && svgEl(s.map, '[data-key="e:' + k + '"]');
        if (e) {
          e.classList.add('pl-go');
          if (!await sleep(650, mine)) return;
          e.classList.remove('pl-go'); e.classList.add('pl-went');
        }
      }
      const n = M.nodes[s.n] || {};
      const ms = s.s != null ? Math.min(4200, 900 + 700 * Math.log10(1 + s.s / 60)) : 420;
      say(label + ' · ' + (i + 1) + '/' + steps.length + ' — ' + (n.t || s.n)
        + (s.s != null ? ' · ' + (s.wait ? 'waited ' : '') + dur(s.s) : '')
        + (s.k > 1 ? ' in ' + s.k + ' sittings' : '')
        + (s.from ? ' · ' + when(s.from) + (s.to && s.to !== s.from ? ' – ' + when(s.to) : '') : '')
        + (s.here ? ' · it is here now' : ''));
      g.classList.add('pl-now');
      current = {key: s.map + ':' + s.n, m: s.m || {}};
      drawMetrics();
      const c = clock(g, s.s, ms, mine);
      if (!await sleep(ms, mine)) return;
      c.remove();
      g.classList.remove('pl-now'); g.classList.add('pl-seen');
      tag(g, s.n, s.s);
      done(s); current = null;
      drawMetrics();
      prev = s;
    }
    say(label + ' · played' + (steps.length ? '' : ': nothing recorded yet'));
    played = null;
    drawMetrics();
    pick(-1);
    document.querySelectorAll('.play.on').forEach((b) => { b.textContent = '▶'; b.classList.remove('on'); });
  }
  // The feature went where the map does not go: the play pauses on it, the
  // places are ringed and joined by a ghost of the way it took, and a note
  // says what happened — where the map is wrong, or the code.
  function deviate(prev, s, g) {
    if (g) g.classList.add('pl-wrong');
    const p = g && prev && prev.map === s.map && svgEl(s.map, '[data-node="' + prev.n + '"]');
    if (p) {
      p.classList.add('pl-wrong');
      const a = p.querySelector('.shape').getBBox(), b = g.querySelector('.shape').getBBox();
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      line.setAttribute('class', 'pl-ghost');
      line.setAttribute('d', 'M' + (a.x + a.width / 2) + ' ' + (a.y + a.height / 2)
        + ' L' + (b.x + b.width / 2) + ' ' + (b.y + b.height / 2));
      g.ownerSVGElement.append(line);
    }
    const box = document.getElementById('pl-off');
    box.querySelector('.pl-off-what').textContent = s.off.charAt(0).toUpperCase() + s.off.slice(1) + '.';
    box.querySelector('.pl-off-when').textContent = s.from ? when(s.from) : '';
    box.hidden = false;
    paused = true;
    bar.querySelector('.pl-pause').textContent = '▶';
    document.body.classList.add('pl-paused');
  }
  document.querySelector('#pl-off .pl-off-go').addEventListener('click', () => {
    document.getElementById('pl-off').hidden = true;
    paused = false;
    bar.querySelector('.pl-pause').textContent = '⏸';
    document.body.classList.remove('pl-paused');
  });
  document.querySelector('#pl-off .pl-off-stop').addEventListener('click', () => stop());
  // The history beside the map: every place with when, how long and the
  // arrow it came by; the one playing is lit and kept in view.
  function list(steps, label) {
    const ul = document.getElementById('hist');
    ul.textContent = '';
    document.getElementById('hist-what').textContent = label;
    if (!steps.length) {
      const li = document.createElement('li');
      li.className = 'muted';
      li.textContent = 'Nothing recorded yet: the history starts with the sessions run since sclaude kept one.';
      ul.append(li);
      return;
    }
    const offs = steps.filter((s) => s.off).length;
    if (offs) {
      const li = document.createElement('li');
      li.className = 'h-offs';
      li.textContent = '⚠ ' + offs + (offs === 1 ? ' place' : ' places') + ' where the feature left the map';
      ul.append(li);
    }
    steps.forEach((s, i) => {
      const prev = steps[i - 1], li = document.createElement('li'), n = M.nodes[s.n] || {};
      li.dataset.i = i;
      if (s.off) {
        li.classList.add('h-wrong');
        li.title = s.off;
      }
      if (prev && prev.map !== s.map) {
        const off = document.createElement('div');
        off.className = 'h-off';
        off.textContent = PASSES.includes(s.map)
          ? '↪ ' + TITLE[s.map] + (s.pass ? ': ' + s.pass : '') : '↩ back to the cycle';
        li.append(off);
      }
      const e = arrow(prev, s);
      if (e && e.l) {
        const via = document.createElement('div');
        via.className = 'h-via' + (e.k === 'back' ? ' back' : '');
        via.textContent = '→ ' + e.l;
        li.append(via);
      }
      const head = document.createElement('div');
      head.className = 'h-t';
      head.textContent = n.t || s.n;
      li.append(head);
      const bits = [];
      if (s.from) bits.push(when(s.from) + (s.to && s.to !== s.from ? ' – ' + when(s.to) : ''));
      if (s.s != null) bits.push((s.wait ? 'waited ' : '') + dur(s.s));
      if (s.k > 1) bits.push(s.k + ' sittings');
      if (s.here) bits.push('here now');
      if (bits.length) {
        const m = document.createElement('div');
        m.className = 'h-m';
        m.textContent = bits.join(' · ');
        li.append(m);
      } else li.classList.add('h-pass');
      li.addEventListener('click', () => {
        const b = document.querySelector('.play.on');
        run(steps, label, i);
        if (b) { b.textContent = '■'; b.classList.add('on'); }
      });
      ul.append(li);
    });
  }
  function pick(i) {
    const panel = document.querySelector('.panel');
    document.querySelectorAll('#hist li.on').forEach((li) => li.classList.remove('on'));
    const li = document.querySelector('#hist li[data-i="' + i + '"]');
    if (!li) return;
    li.classList.add('on');
    panel.scrollTo({top: li.offsetTop - panel.clientHeight / 2 + li.offsetHeight / 2, behavior: 'smooth'});
  }
  function expand(map) {
    const h = data || {visits: [], passes: {}};
    if (PASSES.includes(map)) {
      const sel = document.querySelector('select.pass[data-pass="' + map + '"]');
      const p = (h.passes[map] || [])[+(sel && sel.value)];
      return p ? p.steps.map((s) => Object.assign({map: map}, s)) : [];
    }
    const out = [];
    (map === 'detail' ? h.visits : onMap(h.visits, map)).forEach((s) => {
      if (!s.pass) { out.push(Object.assign({map: map}, s)); return; }
      const p = (h.passes[s.pass[0]] || [])[s.pass[1]];
      if (p) p.steps.forEach((x, j) => out.push(Object.assign({map: s.pass[0], pass: p.label},
        x, j || !s.off ? {} : {off: s.off})));
    });
    return out;
  }
  document.querySelectorAll('.play').forEach((b) => b.addEventListener('click', () => {
    if (b.classList.contains('on')) { stop(); return; }
    run(expand(b.dataset.play), b.dataset.label);
    b.textContent = '■'; b.classList.add('on');
  }));
  bar.querySelector('.pl-pause').addEventListener('click', (ev) => {
    paused = !paused; ev.target.textContent = paused ? '▶' : '⏸';
    document.body.classList.toggle('pl-paused', paused);
  });
  bar.querySelector('.pl-speed').addEventListener('change', (ev) => { speed = +ev.target.value; });
  bar.querySelector('.pl-stop').addEventListener('click', stop);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !bar.hidden) stop(); });
  function update(h) {
    if (!h) return;
    data = h;
    PASSES.forEach((map) => {
      const sel = document.querySelector('select.pass[data-pass="' + map + '"]');
      if (!sel) return;
      const list = h.passes[map] || [], was = sel.value;
      const sig = JSON.stringify(list.map((p) => p.label));
      if (sel.dataset.sig === sig) return;
      sel.dataset.sig = sig;
      sel.textContent = '';
      list.forEach((p, i) => { const o = document.createElement('option'); o.value = i; o.textContent = p.label; sel.append(o); });
      if (!list.length) { const o = document.createElement('option'); o.textContent = 'no pass yet'; sel.append(o); }
      sel.disabled = !list.length;
      if (was && +was < list.length) sel.value = was;
      else if (list.length) sel.value = list.length - 1;
      document.querySelector('.play[data-play="' + map + '"]').disabled = !list.length;
    });
    document.querySelectorAll('.play').forEach((b) => {
      if (!PASSES.includes(b.dataset.play)) b.disabled = false;
    });
    if (bar.hidden) list(expand('detail'), 'The whole process');
  }
  // The panel's two faces: what can be done now, and how it went.
  function showTab(name) {
    document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
    document.querySelectorAll('.tab').forEach((t) => { t.hidden = t.id !== 'tab-' + name; });
  }
  document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  // What each place took, under its block, by the checkboxes above the maps.
  const took = (s) => s < 3600 ? Math.max(1, Math.round(s / 60)) + ' min'
    : s < 86400 ? Math.floor(s / 3600) + ' h' + (Math.round(s % 3600 / 60) ? ' ' + Math.round(s % 3600 / 60) + ' min' : '')
    : Math.floor(s / 86400) + ' d ' + Math.round(s % 86400 / 3600) + ' h';
  // With `more`, what a stay playing now adds to the count before it.
  const plus = (put, n, more) => more == null ? put(n) : (n ? put(n) : '') + '+' + put(more);
  const money = (n) => '$' + (n < 10 ? n.toFixed(2) : Math.round(n));
  const SHOW = {input: (n, more) => '✋ ' + plus(String, n, more),
                cost: (n, more) => plus(money, n, more),
                wait: (n, more) => '⏳ ' + plus(took, n, more)};
  function totals(kind, map) {
    const m = ((data || {}).metrics || {})[kind] || {};
    if (map !== 'overview') return m[map] || {};
    const out = {};
    // The whole process and the regressions' map project onto it; a sync,
    // which it does not draw, counts under the block it ran ahead of.
    ['detail', 'regression', 'ahead'].forEach((from) => Object.entries(m[from] || {}).forEach(([n, v]) => {
      const to = M.proj[n];
      if (to) out[to] = (out[to] || 0) + v;
    }));
    return out;
  }
  function drawMetrics() {
    // The whole feature beside each checkbox: every map the metrics name,
    // which share no place (the overview, drawn from the detailed map here,
    // is not among them).
    document.querySelectorAll('.mt-total').forEach((b) => {
      const m = ((data || {}).metrics || {})[b.dataset.kind] || {};
      // "ahead" repeats the sync's under the glance's blocks: not twice.
      const sum = Object.keys(m).filter((map) => map !== 'ahead').reduce((t, map) =>
        t + Object.values(m[map] || {}).reduce((a, v) => a + v, 0), 0);
      b.textContent = '· ' + (b.dataset.kind === 'cost' ? '$' + sum.toFixed(2)
        : b.dataset.kind === 'wait' ? (sum ? took(sum) : '0') : sum);
    });
    document.querySelectorAll('.mt').forEach((t) => t.remove());
    const on = [...document.querySelectorAll('.metrics input:checked')].map((c) => c.value);
    ['detail', 'overview'].concat(PASSES).forEach((map) => {
      const per = {};
      if (played && inPlay.has(map)) {
        // ✋3+2: three before this stay, two in it; a stay done shows 5.
        const keys = new Set(Object.keys(played).concat(current ? [current.key] : []));
        keys.forEach((key) => {
          if (!key.startsWith(map + ':')) return;
          const n = key.slice(map.length + 1), was = played[key] || {};
          const now = current && current.key === key ? current.m : null;
          on.forEach((kind) => {
            const a = was[kind] || 0, b = now ? now[kind] || 0 : 0;
            if (b) (per[n] = per[n] || []).push(SHOW[kind](a, b));
            else if (a) (per[n] = per[n] || []).push(SHOW[kind](a));
          });
        });
      } else on.forEach((kind) => Object.entries(totals(kind, map)).forEach(([n, v]) => {
        if (v) (per[n] = per[n] || []).push(SHOW[kind](v));
      }));
      Object.entries(per).forEach(([n, words]) => {
        const g = svgEl(map, '[data-node="' + n + '"]');
        if (!g) return;
        const box = g.querySelector('.shape').getBBox();
        const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('class', 'mt');
        t.setAttribute('x', box.x + box.width - 2); t.setAttribute('y', box.y + box.height + 13);
        t.setAttribute('text-anchor', 'end');
        t.textContent = words.join('  ');
        g.append(t);
        // No wider than its block: a block in the next lane may stand
        // beside this line (a row risen, _rows).
        if (t.getComputedTextLength() > box.width - 4) {
          t.setAttribute('textLength', box.width - 4);
          t.setAttribute('lengthAdjust', 'spacingAndGlyphs');
        }
      });
    });
    try { localStorage.setItem('process-metrics', JSON.stringify(on)); } catch (e) {}
  }
  try {
    const kept = JSON.parse(localStorage.getItem('process-metrics') || '[]');
    document.querySelectorAll('.metrics input').forEach((c) => { c.checked = kept.includes(c.value); });
  } catch (e) {}
  document.querySelectorAll('.metrics input').forEach((c) => c.addEventListener('change', drawMetrics));
  return {update: (h) => { update(h); if (h) drawMetrics(); }, stop: stop};
})();
"""

PLAY_STYLE = """
.pl-wrong .shape{stroke:var(--human)!important;stroke-width:3.5!important}
.pl-ghost{fill:none;stroke:var(--human);stroke-width:2.5;stroke-dasharray:5 4;pointer-events:none}
#pl-off{position:fixed;left:50%;top:18%;transform:translateX(-50%);z-index:30;max-width:min(460px,92vw);
background:var(--surface);border:2px solid var(--human);border-radius:12px;padding:14px 16px;
box-shadow:0 10px 30px rgba(0,0,0,.25)}
#pl-off h3{margin:0 0 6px;color:var(--human)}#pl-off p{margin:6px 0}
#pl-off button{font:600 13px var(--body);padding:5px 12px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer}
#hist li.h-wrong{border-left:3px solid var(--human)}#hist li.h-wrong .h-t::before{content:"⚠ "}
#hist li.h-offs{color:var(--human);font-weight:600}
.play{font:600 13px var(--body);width:30px;height:26px;margin-left:10px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--auto);cursor:pointer;vertical-align:middle}
.play:hover:not(:disabled){border-color:var(--auto)}.play.on{background:var(--auto);color:var(--surface)}
.play:disabled{opacity:.4;cursor:default}
select.pass{font:13px var(--body);margin-left:8px;padding:3px 6px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);vertical-align:middle;max-width:min(380px,60vw)}
#player{position:fixed;left:16px;bottom:16px;z-index:25;display:flex;align-items:center;gap:8px;max-width:calc(100vw - 32px);
padding:8px 10px;border-radius:12px;background:var(--surface);border:1px solid var(--line);
box-shadow:0 6px 20px rgba(0,0,0,.18);font-size:13.5px}
#player[hidden]{display:none}
#player button,#player select{font:inherit;padding:3px 8px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer}
.pl-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body.playing svg.map .node:not(.pl-now):not(.pl-seen){opacity:.4}
body.playing svg.map .edge:not(.pl-go):not(.pl-went){opacity:.3}
.node.pl-now .shape{stroke:var(--auto);stroke-width:5;filter:drop-shadow(0 0 10px var(--auto))}
.node.pl-seen .shape{stroke-width:2.8}
.edge.pl-go path.line{stroke:var(--auto);stroke-width:4;stroke-dasharray:10 6;animation:pl-flow .5s linear infinite}
.edge.pl-went path.line{stroke:var(--auto);stroke-width:2.4}
@keyframes pl-flow{to{stroke-dashoffset:-16}}
body.pl-paused .edge.pl-go path.line{animation-play-state:paused}
.pl-clock circle{fill:var(--surface);stroke:var(--auto);stroke-width:2}
.pl-clock line{stroke:var(--ink);stroke-width:2;stroke-linecap:round}
.pl-clock text,.pl-tag{font:700 12px var(--body);fill:var(--auto);paint-order:stroke;stroke:var(--paper);
stroke-width:4px;stroke-linejoin:round}
.pl-tag{font-size:11px}
.metrics{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;margin:10px 0 0;font-size:13.5px}
.metrics label{display:flex;align-items:center;gap:5px;cursor:pointer}
.mt{font:700 11.5px var(--body);fill:var(--violet);paint-order:stroke;stroke:var(--paper);stroke-width:4px;
stroke-linejoin:round;pointer-events:none}
.panel{position:sticky}
.tabs{display:flex;gap:4px;margin:-4px 0 10px;padding:3px;border-radius:10px;background:var(--lane-b)}
.tabs button{flex:1;font:600 13px var(--body);padding:6px 8px;border:0;border-radius:8px;background:none;
color:var(--muted);cursor:pointer}
.tabs button.on{background:var(--surface);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12)}
#hist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px}
#hist li{padding:5px 8px;border-radius:8px;cursor:pointer;border-left:3px solid transparent}
#hist li:hover{background:var(--lane-b)}
#hist li.on{background:var(--auto-soft);border-left-color:var(--auto)}
#hist li.h-pass .h-t{font-weight:500;color:var(--muted)}
.h-t{font-weight:600;font-size:14px}.h-m{color:var(--muted);font-size:12.5px}
.h-via{color:var(--muted);font-size:12px}.h-via.back{color:var(--human)}
.h-off{font:600 12px var(--body);color:var(--cloud);margin:6px 0 2px}
"""


def play_head(map_name, label, passes=False):
    """▶ beside a map's heading; for a map of passes, the choice of one."""
    out = '<button type="button" class="play" data-play="%s" data-label="%s" title="Play how the feature went" disabled>▶</button>' \
        % (map_name, esc(label))
    if passes:
        out += '<select class="pass" data-pass="%s" aria-label="Which pass" disabled><option>no pass yet</option></select>' \
            % map_name
    return out


PLAYER_BAR = """<div id="player" hidden><button type="button" class="pl-pause" title="Pause">⏸</button>
<select class="pl-speed" aria-label="Speed"><option value="0.5">×0.5</option><option value="1" selected>×1</option><option value="2">×2</option>
<option value="4">×4</option></select><span class="pl-text"></span>
<button type="button" class="pl-stop" title="Stop (Esc)">✕</button></div>
<div id="pl-off" role="dialog" aria-labelledby="pl-off-h" hidden><h3 id="pl-off-h">⚠ The feature left the map here</h3>
<p class="pl-off-what"></p><p class="pl-off-when muted"></p>
<p class="muted">The way it took is not drawn: the map, or the code, is wrong here.</p>
<button type="button" class="pl-off-go">Play on</button> <button type="button" class="pl-off-stop">Stop</button></div>"""


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
h2.first-map{margin-top:0}
@media (max-width:900px){.live{grid-template-columns:1fr}.panel{position:static;max-height:none}}
"""


def page(label, cfg=None):
    """A feature's map: the same drawing as its project's config draws it,
    with its place lit and its actions, kept current by polling
    /__sclaude/flow/state."""
    with configured(example_config() if cfg is None else cfg):
        return _page(label)


def _page(label):
    detail = Diagram(*node_sets()[0])
    overview = Diagram(*node_sets()[1])
    script = LIVE_SCRIPT % {
        "label": json.dumps(label),
        "positions": json.dumps({k: [v] if v else [] for k, v in POSITIONS.items()}),
    }
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s — sclaude map</title>
<style>%s%s</style></head><body><main>
<p class="muted"><a href="/__sclaude/">features</a> · <a href="/__sclaude/select?f=%s">open the feature</a></p>
<h1>%s</h1>
%s
<div class="metrics"><span class="muted">Show on the maps:</span>
<label title="Each time you stepped in: a message to Claude after its turn, an answer to its question or to sclaude's, a command run on the feature"><input type="checkbox" value="input"> ✋ your input <b class="mt-total" data-kind="input"></b></label>
<label title="What Claude Code's own account says each conversation cost"><input type="checkbox" value="cost"> $ Claude's cost <b class="mt-total" data-kind="cost"></b></label>
<label title="How long a question waited for your answer — Claude's, after its turn or its question, and sclaude's own — the whole of it, nights included"><input type="checkbox" value="wait"> ⏳ waiting for you <b class="mt-total" data-kind="wait"></b></label></div>
<div class="live" style="margin-top:14px">
<div>
<h2 class="first-map">The whole process%s</h2>
<div class="card detail-card">%s</div>
<h2>The cycle at a glance%s</h2><div class="card mini">%s</div>
<h2 id="map-workshop">How a session changes sclaude%s</h2><div class="card mini">%s</div>
<h2 id="map-friction">The friction review%s</h2><div class="card mini">%s</div>
<h2 id="map-regression">A stage's regression%s</h2><div class="card mini">%s</div>
<h2 id="map-sync">Main and the branch%s</h2><div class="card mini">%s</div>
<h2>Every command</h2>%s
</div>
<aside class="panel">
<div class="tabs" role="tablist"><button type="button" data-tab="actions" class="on">Actions</button><button type="button" data-tab="history">History</button></div>
<div class="tab" id="tab-actions">
<div class="muted" id="stamp">…</div>
<h3>Where it stands</h3><div id="where">…</div><div class="muted" id="why"></div>
<h3>What you can do now</h3><ul id="acts"></ul>
<p id="err"></p>
</div>
<div class="tab" id="tab-history" hidden>
<p class="muted">Played: <b id="hist-what">The whole process</b>. Click a place to play from it.</p>
<ul id="hist"></ul>
</div>
</aside>
</div>
<button id="clear" type="button" hidden>Clear the selection</button>
%s
</main><script>%s%s%s</script></body></html>
""" % (esc(label), STYLE, LIVE_STYLE + PLAY_STYLE, esc(label), esc(label), LEGEND,
       play_head("detail", "The whole process"), detail.svg(),
       play_head("overview", "The cycle at a glance"), overview.svg(),
       play_head("workshop", "How a session changes sclaude", passes=True), Diagram(*node_sets()[2]).svg(),
       play_head("friction", "The friction review", passes=True), Diagram(*node_sets()[3]).svg(),
       play_head("regression", "A stage's regression", passes=True), Diagram(*node_sets()[4]).svg(),
       play_head("sync", "Main and the branch", passes=True), Diagram(*node_sets()[5]).svg(),
       commands_table(), PLAYER_BAR,
       INTERACT_SCRIPT % {"model": json.dumps(client_model())}, PLAY_SCRIPT, script)


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
        print("%s\t%s\t%s" % (node, all_nodes()[node][3], why))
        return 0
    if len(argv) >= 2 and argv[0] == "history":
        try:
            with open(argv[1]) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            state = {}
        here = argv[2] if len(argv) >= 3 and argv[2] in NODES else None
        read = transcripts_of(argv[1])
        print(json.dumps(history(state, read_history(argv[1]), here, read), ensure_ascii=False))
        read.done()
        return 0
    if len(argv) >= 2 and argv[0] == "page":
        sys.stdout.write(page(argv[1]))
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
