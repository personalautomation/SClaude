# The process model: every map's lanes, nodes, edges and details, the places
# a feature can stand on, and the specs of the sessions.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import contextlib

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_config
import cycle_steps


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
    "plan_check": ("sclaude", 5, "gate", "Approved plan found?",
                   "the approved text found in the transcript", ""),
    "ac": ("github", 5, "task", "Criteria on the issue",
           "a comment of their own, AC1, AC2, …", ""),
    # step 2
    "code": ("session", 6, "session", "2 · code",
             "builds it, checks it in Chrome, commits with Requirement: ACn, records a demo", "FRS"),
    "works": ("person", 7, "gate", "Accept the work?",
              "the demo's link, then Accept in the session's dialog, or remarks to it", ""),
    # step 3
    "pr": ("session", 9, "session", "3 · pr",
           "manuals updated, a draft PR by the pr skill, the criteria for QA", "FS"),
    "pr_check": ("sclaude", 10, "gate", "PR ready?",
                 "a pull request on GitHub carrying every commit", ""),
    # step 4. One block, one lane and one line wherever the review runs —
    # in Actions or on this machine, it ends as threads on the pull request;
    # the setting only changes the arrows (NEEDS) and the details say where.
    "review_run": ("github", 11, "task", "Review",
                   "reads the pull request and posts its findings as threads on it", "S"),
    # Step 4 opens on its gate and each of its sessions ends on it.
    "review_close": ("sclaude", 12, "gate", "Anything left open?",
                     "on the way in and after each session: threads, red or running checks; then the local suite", "R"),
    "review": ("session", 13, "session", "4 · fix-review",
               "fixes the findings through subagents, pushes, one round, stops", "FRS"),
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
    "retro_fix": ("sclaude", 33, "gate", "Code changed by the retro?",
                  "yes — its commits go out from step 3", ""),
    "cleanup": ("person", 34, "gate", "Clean up?",
                "remove the worktree, branches, database; the record stays", ""),
    "end": ("sclaude", 35, "end", "Done", "", ""),
    "kept": ("person", 35, "end", "Kept", "later: sclaude done <name>", ""),
}

# How each session runs: model · effort · permission mode. Shown in the note
# under the pointer rather than on the block. The four steps' come from their
# table (cycle_steps.py); tests/process.py reads the rest against SYNC_MODEL
# and the epilogue's and the retro's launches.
SPEC = {
    **{s["name"]: (s["model"], s["effort"], s["mode"]) for s in cycle_steps.STEPS},
    "fix_local": ("opus", "medium", "auto"),      # step 2's
    "fix_preview": ("opus", "medium", "auto"),    # step 4's
    "fix_prod": ("opus", "medium", "auto"),       # step 4's
    "sync": ("sonnet", "medium", "auto"),
    "epilogue": ("sonnet", "medium", "auto"),
    "retro": ("opus", "medium", "plan"),
    "review_run": ("opus", "default", "read-only, claude -p"),
    "f_review": ("opus", "medium", "plan"),
    "f_monthly": ("opus", "medium", "plan"),
    "f_classify": ("haiku", "default", "claude -p, no tools"),
    # A part's sessions are the steps' own, launched the same way.
    **{"p_" + s["name"]: (s["model"], s["effort"], s["mode"]) for s in cycle_steps.STEPS
       if s["name"] in ("code", "pr", "review")},
    "p_whole": next((s["model"], s["effort"], s["mode"]) for s in cycle_steps.STEPS if s["name"] == "code"),
}

# What each block does, at more length than fits on it: the note under the
# pointer. The overview's blocks borrow these (ALIAS).
DETAILS = {
    "new": "Lists the repository's open issues, yours first, and suggests a branch name from the chosen one; or takes a name typed by hand. From the phone the Mini App asks the same and starts it with the answers.",
    "prepare": "Brings the main checkout up to origin/main when it is on main (a fast-forward, with npm ci there if its lockfile moved, not while a Node process works in it), branches feat/<slug> from a fresh origin/main into a worktree of its own, links the environment and hard-links the main checkout's node_modules, claims a port and a <feature>.localhost address, and on a local database starts a Supabase stack for this feature alone.",
    "board_start": "Moves the issue out of Backlog to In progress on every board it is on, and fills an empty Start date with today. Once, at the start; a column moved by hand is left alone.",
    "main_in": "Before each step sclaude merges origin/main into the branch without asking, so every session works on what will merge. A merge that would conflict goes to the sync session (5); only the deferred logs it merges itself.",
    "plan": "The session reads the issue with its parents and comments and the manuals' tables of contents, says what it understood the scope to be and waits for corrections, then plans. The plan ends with numbered acceptance criteria, each checkable on a deployment without reading code. A feature too big for one review is split at the person's word into parts: one issue, one plan and one QA, a section ## Parts, and each criterion naming its part — built in step 2, a pull request for each (A feature built in parts).",
    "approve": "You correct the scope, then approve the plan in Claude Code's plan dialog. The criteria are what QA will tick later, so this is where a missing one costs least. Or press n twice in sclaude's tab while the dialog is open: the session is closed and the plan on screen counts as approved, which saves the turn Claude would take to read your approval; N twice does the same and stops before step 2, which the next sclaude <name> starts.",
    "plan_check": "sclaude reads the approved plan back from the session's transcript into .sclaude/local/feature/plan.md, the bridge to step 2. Not found: the same session is sent back to present it again, at most twice.",
    "ac": "The criteria go into a comment of their own on the issue, between sclaude's markers; the issue's description is never edited. QA ticks them there.",
    "code": "A fresh session builds from the plan, checks the result in Chrome at the feature's own address, and commits with a Requirement: ACn footer naming the criterion each commit serves. It closes with a report criterion by criterion. Before its question it records a demo of the feature (/sdemo), desktop and phone; when fixing remarks changed the code, a delta of what changed for the user and the whole demo again before asking again: the link goes first in the report, and with the videos to the feature's topic and into a demo comment on the issue.",
    "works": "The session ends on one question in its own dialog: Accept, and it closes and sclaude goes on without asking; Remarks, and you say what is wrong and it carries on. A session you leave with /exit gets the question in sclaude's terminal instead: a no takes what is wrong back to the same session as your message, Enter alone leaves the step for later. In sclaude's tab, n pressed twice is the same Accept; N twice accepts, runs what follows and stops before step 3; R twice closes it as /exit would and stops, and the next sclaude <name> opens the same conversation again.",
    "reg_local": "The project's suite (its config's regression parts) against the feature's own server and database. An unpublished branch is put on top of main first. Green closes step 2; at step 4 it runs again before the step closes.",
    "fix_local": "A separate session gets the failing log and fixes the cause, then the suite runs again. Two sessions that do not make it green stop the cycle and tell you: a third guess at the same failure rarely helps.",
    "pr": "Updates the manuals the change touches and opens a draft pull request through the pr skill, with the criteria copied in as a plain list (QA ticks them in the issue) and Closes #N for the issue.",
    "pr_check": "sclaude looks for the pull request on GitHub and for commits it does not carry. Missing either: the session is sent back to finish, at most twice.",
    "review_run": "Reads the pull request and posts its findings as threads. A pull request past reviewBlocks.from changed lines (5000 by default) is cut first, once, into review blocks: a session groups the plan's criteria with the files that carry them, every changed file in one block, sclaude checks the cut (twice, then the parts it was built in, else the whole), and says the blocks in the topic. While blocks are read the review runs here whatever the setting, the project's CI still counting: a block's first pass reads its files whole and follows its criteria end to end, later passes read the new commits across the whole pull request with the closed blocks' files they touched, and the last block is the seams between them. Where it runs is the review setting: github — the project's review workflow in Actions reads every push, and sclaude waits for its check; local — read-only claude -p passes here, before each session and on each head a session leaves, signed by this machine; github-local — Actions, and this machine once a feature's job could not run there. A job that stopped on Claude's usage limit is run again on GitHub two minutes past the reset its log names; before that, or with no Actions minutes, or a runner that could not reach the network, github stops step 4 and says why and github-local moves the feature here for the rest of its life (other features for a while after). Here a key in the terminal or in the topic ends the search; another, in the terminal, lets the review go on by itself, past the questions after it — a box of three states going round auto → on → off: auto follows the project's sleep_mode (on, off, or by default an /isleep night over every session, not an /isleep here one).",
    "review": "The session fixes the findings through subagents, keeping only the coordination, pushes, and stops once the automatic review has confirmed the fixes and posted the next round. While it works in its own tab, the terminal takes the review's boxes, [s] and [g].",
    "review_close": "Step 4 opens on this gate, and every session of it ends on it. Read in blocks, nothing open closes the block rather than the step: the next block opens with its rounds counted afresh, and after the seams the cut is taken off and the step closes. On the way in, before any session, it asks more: a person's comment anywhere on the pull request is open too, and a pull request it cannot read opens a session; with nothing open and nothing waiting for a session (one interrupted, a review sent back) the step closes with no session at all. Leaving step 4 closes it only when nothing is open — no unresolved thread, no running or red check — and the local regression is green again. Otherwise sclaude waits and what is open goes back to a session without a question; [s] or ⏭ makes the next session the last for new findings. A session you left yourself (/exit, Ctrl-C) with [g] off holds step 4 open until the next sclaude <name>. A session sclaude closed on its done marker — the review is waited for, or run here, only after it — goes back by whose work is open: threads from before it, or a red check, to the same session; only new ones to the same session while its context is under 40% and its last request under 55 minutes old, else to a fresh one. With [g] on the rounds go on even then (30 a step 4, then it asks), a pass that did not run is tried again ten times with growing pauses, and after the search ended the fixes are checked. A night session itself resolves a minor finding the review posted, with no reply under it yet, and replies saying so; the others it leaves for you to confirm: sclaude asks whether to go through them now, and on your yes they go back to a fresh session that asks about each and, on your yes, replies and resolves them; the rest of your threads wait for your hand on GitHub.",
    "hold_ways": "Production carries this feature and its regression there was not green, with nothing rolled back: the rollback failed or was refused, another release landed on top and the repeated run was red too, or the suite could not run in a broken environment (a project with no production suite or address is not held after its ship). A red run made by hand lands here as well. Every later pass of sclaude <name> checks this first and stops on it, so nothing is shipped, closed or cleaned up. The ways out: sclaude regression <name> prod runs production's suite again, and green goes on to the epilogue — as it does when the project has had no production suite since the red (prodRegression none, or no list), which lifts the hold; sclaude rollback puts the previous release back and sends the fix to step 4; sclaude return fixes forward from step 4.",
    "merge_check": "git merge-tree tells in memory whether the branch merges cleanly with main — no session, no GitHub call. Asked before the preview, after QA's yes, and every two minutes while waiting for the merge.",
    "p_split": "Step 1 proposed building a feature too big to build and show in one go in parts, and the person said yes: the plan keeps a ## Parts section, a ### Part n — title heading for each, and every acceptance criterion names the part that makes it true, AC7. [part 2]. It stays one issue, one plan, one pull request and one QA. sclaude reads the parts when the plan is approved, or when a plan is split after step 2 began.",
    "p_enter": "Before a part's session the tree goes onto the part's own branch, <branch>-<n>, made off the part before it — part 1 off the feature's branch, which stays where it left main while the parts are built. Work begun on the feature's branch before the split becomes part 1, and the feature's branch goes back where it left main, while GitHub has not got it past that point. Never over uncommitted work.",
    "p_code": "A step-2 session for this part alone, handed only its criteria and the feature's. Before it closes, a fresh subagent reads the part's diff for what would cost more later — the design the next parts build on, bugs the tests miss, a criterion not met — and the session fixes what it agrees with, up to three rounds. A request the person makes goes where the session puts it: now when it touches what is built, into a later part in the plan otherwise. Nobody is asked whether it works — that is the whole feature's question; the session ends on its own marker, and the local regression follows. No pull request yet.",
    "p_built": "Another part to build: back to its branch and its session — but first, a headless session with the sdemo skill records what the part just built added for a user — only that, on a desktop and a phone — and sclaude sends it to the feature's Telegram topic and prints its page, with the recording's progress in the terminal as it goes: the earlier the person sees a part, the less the next one builds on what they would have said no to. It asks nothing; the person's remarks go to the next part's session, which changes what is built already and writes into the plan what a later part should. Nothing is recorded when the part changed nothing a user sees, with demo: off, or with partAccept: each, where the part's own session shows it. The last part built, or the person ended the parts with sclaude parts <name> stop: step 2 checks the whole, its demo written from the parts' scenarios.",
    "p_whole": "With every part built, a step-2 session on the last part's branch checks the whole feature as one, end to end against every criterion, and fixes the seams; it records the demo and ends on Accept, as any feature's step 2 does. Its fixes are commits on the last part's branch. Only now, with the whole accepted, do the parts become one branch and one pull request.",
    "p_join": "Accepted, the parts become one branch, the feature's: the parts are stacked, so it moves to the last part's branch. Each part's commits are kept as a range for the review's cut. Where the feature's branch took commits of its own since the parts left it — parts merged there one by one under the scheme before — it is merged into the last part first, a conflict going to the sync session, and the review reads from where it stood.",
    "p_stop": "The feature's branch does not merge into the last part, and the sync session did not settle it: sclaude says what to do, and the parts wait.",
    "p_on": "Step 3 opens one pull request into main for the whole feature, its description listing the parts. Step 4 reads it as any pull request — a feature this size in review blocks — and the rest of the cycle runs once for all of it.",
    "sync": "Merges origin/main into the branch (never a rebase), resolves each conflict keeping both sides' intent, checks the result as the project's CLAUDE.md says and pushes. sclaude then checks it settled; a pull request handed over goes back to a draft.",
    "preview": "Deploys the worktree to a preview from the main repository (up to three tries), applies the branch's migrations there, and runs the preview regression against the deployment. An unchanged tree already green is not deployed again, nor, once merged, one whose preview QA accepted. A deploy that fails three times goes to the fixing session as a red run does — the command that failed named — and deploys again; after two such sessions it is yours.",
    "preview_ok": "Green: when the product's code changed since the last demo, a headless session records a delta of what changed for the user and the whole demo again, published once it ends with the issue's demo comment replaced, or keeps the demo there is, comment and all, when nothing a user meets changed — QA sees the feature as it is and what changed; then the issue goes to In QA. Red: no label is claimed, the cycle goes back to step 4 and a fixing session opens there.",
    "fix_preview": "A fixing session in step 4, where the pull request is open and pushes reach the branch, with the failing run's log. The fix goes the whole way round again.",
    "in_qa": "The issue moves to In QA only after the preview's tests passed, so the column says something true. The QA watch starts: a systemd timer looks at the issue's column every few minutes and tells the feature's topic; it hands the pull request over when QA says Done, even with nobody at the terminal. It changes nothing else.",
    "qa_check": "QA opens the preview, checks each acceptance criterion and ticks it in the issue's comment. Nothing ticks a box but a person, unless the project's qa setting says so.",
    "qa_verdict": "Done goes on to the merge. In progress or Backlog is a hand-back: everything said since on the issue and the pull request is collected word for word and opens step 4 with it.",
    "handoff": "The draft is marked ready, moved to Backlog, its assignees cleared, and a summary for whoever merges is posted: the preview, QA's verdict, the criteria, the review's findings, the checks.",
    "merge": "The merge is yours unless the project's config says merge: auto. sclaude offers it once QA passed, GitHub says the way is clear and the pull request, merged with the newer main, builds and passes its checks; declined, or that check red, it waits.",
    "merge_wait": "Polls GitHub every 30 seconds for the merge and checks every two minutes whether main moved into a conflict. Ctrl-C leaves the wait and loses nothing.",
    "merged": "sclaude fills Target date with today so the roadmap's bar ends when the work did, and moves the pull request to Done. GitHub closes the issue by Closes #N, and sclaude reopens it: it closes it itself when the cycle ends — shipped once production is green, or once it is live where the project runs no production suite; declined after a no to production.",
    "ship": "Asked once the merge is in. The deployment production runs now is recorded first, for a rollback. A no closes the issue as declined and goes on to the epilogue; shipping later is vercel --prod from the repository. No answer at all closes nothing: the feature stays here, and it is asked again at the next sclaude <feature>.",
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
    "w_open": "Makes the tree's workshop, a worktree of sclaude from origin/main at .sclaude/local/instruments, shared by every session of the tree, and lets this session write there. Where the machine's sclaude.contribute is off it is refused, and the session's prompt says the workshop is closed: what it found goes to the friction log.",
    "w_change": "The session commits in the workshop and reviews its change: /sreview for a maintainer of sclaude, whatever review they choose for anybody else.",
    "w_ready": "Refuses uncommitted work and records the head as ready; for a maintainer it wants sreview's mark of a finished run at that head.",
    "w_exit": "Publishing starts from claude_launch once the session exits, whatever step it was in.",
    "w_ready_gate": "A change uncommitted, unreviewed at its head or never marked ready is not published: you are asked to reopen the session that made it, told what is missing, or to drop the change. So is one whose sclaude main is out of reach, or which conflicts with it.",
    "w_leaks": "sclaude is public and the product is not: the added lines and the commit messages are searched for the product's repository and folder names, the feature's slug and branch, issue and pull-request numbers, and paths of the product's own files. What is found is shown with the question after the tests; under sclaude.leaks auto it goes out unasked, and a send is kept for the lines it was shown.",
    "w_tests": "The tests the change touches run in a clean environment, each in a session of its own with no terminal. Red right after the session that made the change, that session is reopened unasked, told which tests and where their output is — twice at most; then it is your question.",
    "w_clear": "You are asked when the tests are red, when a line may name the product, or when this machine shows what goes public before it goes (sclaude.contribute ask; off asks too). Otherwise, under sclaude.contribute send, it goes on unasked.",
    "w_decide": "One question for every stop, with what stopped it shown: the red tests and their output, the lines that may name the product, the commits and files that would go public. Send publishes it as it is — your yes overrides sclaude.leaks and sclaude.contribute, since you saw what goes; after red tests, a refused push or a preparation that failed (main out of reach, a conflict) a send checks it again from the start — a maintainer's on the main it goes onto — and pushes it. Reopen sends the same conversation back, told what stopped it. Drop empties the workshop and keeps the change under refs/sclaude/dropped in sclaude's checkout. Unanswered, or while you are away, nothing is decided for you: it is asked again whenever the tree is opened, a ready change checked again first, and sclaude done waits for the answer before the clean-up. sclaude core-send is a send typed by hand: the checks run again without showing the commits, and lines that may name the product, red tests, a failed preparation or a failed push still ask.",
    "w_drop": "The workshop is back where it started; the change stays under refs/sclaude/dropped/<time> in sclaude's checkout, named in the history.",
    "w_who": "MAINTAINERS lists who may commit sclaude's core straight to main; with no file everybody is a maintainer.",
    "w_main": "Rebased onto origin/main, squashed into one commit, pushed to main; where sclaude.update is auto the live checkout is fast-forwarded when nothing runs from it, so the next session runs the fix, and elsewhere sclaude update takes it.",
    "w_pr": "Pushed unsquashed to the workshop's own dev/<name>-<time> branch, never named after the feature, as one pull request per tree; the maintainer's review of it is the gate.",
    "w_done": "The change is in sclaude's main, or in its pull request for a maintainer to review and merge; the workshop is empty for the tree's next change.",
}
# The epilogue's copies beside the stops are its session.
DETAILS["epi_preview"] = DETAILS["epilogue"]
ALIAS = {
    "o_new": "new", "o_plan": "plan", "o_approve": "approve", "o_code": "code", "o_works": "works",
    "o_pr": "pr", "o_review": "review", "o_ghreview": "review_run",
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
    ("approve", "plan_check", "approved, or [n]", ""),
    ("plan_check", "plan", "not found — sent back (≤2)", "back"),
    ("plan_check", "ac", "", "msg"),
    ("plan_check", "code", "yes", ""),
    ("code", "works", "", ""),
    ("works", "code", "remarks — what is wrong", "back"),
    ("works", "pr", "accept, or [n]", ""),
    ("pr", "pr_check", "", ""),
    ("pr_check", "pr", "no — sent back (≤2)", "back"),
    ("pr_check", "review_run", "", "msg"),
    ("pr_check", "review_close", "", "msg"),
    ("review_close", "review_run", "the review runs again: here, on GitHub once Claude's limit reset, or the next review block", "back"),
    ("review_run", "review_close", "the review answered, or the gate took it on", ""),
    ("review_close", "review", "open — a session, unasked; held if you left it, [g] off; threads left at night, at your yes", ""),
    ("review", "review_run", "the session ended: the review reads its push", "back"),
    ("review", "review_close", "the session ended", "back"),
    ("review_close", "preview", "nothing open — step 4 closes", ""),
    ("preview", "in_qa", "green", "msg"),
    ("preview", "review", "red, or the deploy failed: fixed from step 4", "back"),
    ("in_qa", "qa_check", "", ""),
    ("qa_check", "qa_verdict", "", ""),
    ("qa_verdict", "review", "hand-back: their words open step 4", "back"),
    ("qa_verdict", "handoff", "Done (main checked again)", ""),
    ("handoff", "merge", "", ""),
    ("qa_verdict", "preview", "Done, but the code moved: QA again", "back"),
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
    # production block's stops too — main not ready, found before the
    # question; production red and not rolled back, or its suite not run (a
    # red rolled back goes back to step 4 by its own way).
    ("ship", "epilogue", "no; no answer; main not ready — the status, then asked again", ""),
    ("prod", "epilogue", "green; red, not rolled back; no suite run", ""),
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
# sclaude once the session ends (sclaude/lib/improve/workshop.sh). Any session with W
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
    "w_ready_gate": ("sclaude", 6, "gate", "Committed, reviewed, marked ready?", "short of any of them, nothing is published", ""),
    "w_leaks": ("sclaude", 7, "task", "Product details", "names, numbers, paths of the product, looked for", ""),
    "w_tests": ("sclaude", 8, "task", "The tests it touches", "a clean environment, no terminal", ""),
    "w_clear": ("sclaude", 9, "gate", "Anything to ask?", "a hit, red tests, sclaude.contribute not send", ""),
    "w_decide": ("person", 10, "gate", "Send, reopen or drop?", "what stopped it shown; unanswered, asked at the next opening", ""),
    "w_who": ("sclaude", 11, "gate", "Made by a maintainer?", "MAINTAINERS", ""),
    "w_main": ("github", 11, "task", "Pushed to main", "one squashed commit", ""),
    "w_pr": ("github", 12, "task", "A pull request", "from dev/<name>-<time>, one per tree", ""),
    "w_done": ("github", 13, "end", "Published", "the workshop empty again", ""),
    "w_drop": ("sclaude", 12, "end", "Dropped", "the workshop empty again; kept under refs/sclaude/dropped", ""),
}
# Every stop is one question, the person's (workshop_decide): send it as it
# is, reopen the session that made it, or drop it. Nothing waits without it:
# unanswered, it is asked again when the tree is next opened, and the
# feature's clean-up waits for the answer.
WORKSHOP_EDGES = [
    ("w_find", "w_ask", "", ""),
    ("w_ask", "w_open", "approved", ""),
    ("w_open", "w_change", "", ""),
    ("w_change", "w_ready", "", ""),
    ("w_change", "w_exit", "ended before core-ready", ""),
    ("w_ready", "w_exit", "", ""),
    ("w_exit", "w_ready_gate", "", ""),
    ("w_ready_gate", "w_leaks", "yes; or opened again, or core-send, with nothing asked", ""),
    ("w_ready_gate", "w_decide", "no; main out of reach or in conflict", ""),
    ("w_leaks", "w_tests", "", ""),
    ("w_tests", "w_change", "red — same conversation, twice at most", "back"),
    ("w_tests", "w_clear", "", ""),
    ("w_clear", "w_who", "no", ""),
    ("w_clear", "w_decide", "yes", ""),
    ("w_decide", "w_who", "send", ""),
    ("w_decide", "w_leaks", "checked again: a send, or the tree opened on an open question", "back"),
    ("w_decide", "w_change", "reopen — same conversation", "back"),
    ("w_decide", "w_drop", "drop", ""),
    ("w_who", "w_main", "yes", "msg"),
    ("w_who", "w_pr", "no", "msg"),
    ("w_who", "w_decide", "the push or the pull request failed", "back"),
    ("w_main", "w_done", "", ""),
    ("w_pr", "w_done", "", ""),
]

# The friction review: what the safety rules refused a session, read after it
# by a session of its own (run_friction in sclaude/lib/improve/friction.sh). Every session
# with F on the maps leads here.
FRICTION_LANES = [("session", "Step session"), ("sclaude", "sclaude"), ("review", "Friction review"),
                  ("person", "You"), ("branch", "Feature's branch"), ("monthly", "Put off")]
FRICTION_NODES = {
    "f_trip": ("session", 0, "start", "A refusal", "a hook, a rule, the classifier — or the session's own note", ""),
    "f_log": ("sclaude", 1, "task", "Friction log", "each refusal a paragraph; the classifier's gathered after the session", ""),
    "f_empty": ("sclaude", 2, "gate", "Anything logged?", "after every step, round, sync and fix session", ""),
    "f_none": ("session", 2, "end", "No review", "the ordinary case", ""),
    "f_rules": ("sclaude", 3, "gate", "Only rules proposed?", "rules for the project's CLAUDE.md, nothing else", ""),
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
    ("f_verdict", "f_next", "nothing to push", ""),
    ("f_defer", "f_monthly", "once a month", ""),
]

# A stage's regression, out of the detailed map: there an R marks where one
# runs. The local suite closes steps 2 and 4, the preview's comes before QA,
# production's after the ship (regression.sh, deploy.sh).
REGRESSION_LANES = [("person", "You"), ("sclaude", "sclaude"), ("session", "Claude session")]
REGRESSION_NODES = {
    "r_local": ("sclaude", 0, "start", "Local suite", "after step 2's yes, and as step 4 closes", ""),
    "reg_local": ('sclaude', 1, 'gate', 'Local tests passed?',
        "the project's suite against the feature's server", ''),
    "fix_local": ('session', 1, 'session', 'Fix after regression',
        'makes the red tests green — two sessions at most, then it stops for you', 'F'),
    "r_stop": ("person", 2, "hold", "Stopped for you", "two fixing sessions and still red", ""),
    "r_preview": ("sclaude", 3, "start", "Preview suite", "against the preview, before QA", ""),
    "preview_ok": ('sclaude', 4, 'gate', 'Preview tests passed?',
        'red — the fix goes on from step 4', ''),
    "fix_preview": ('session', 4, 'session', 'Fix after preview',
        "makes the preview's tests green, from step 4", 'F'),
    "r_prod": ("sclaude", 5, "start", "Production suite", "against production, after the ship", ""),
    "prod_ok": ('sclaude', 6, 'gate', 'Production tests passed?',
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
    ("hold_ways", "r_on", "regression prod: green, or no suite", ""),
    ("hold_ways", "r_step4", "return", ""),
    ("prod_ok", "r_on", "green", ""),
]

# Main and the branch, out of the detailed map: there an S marks where main
# is checked (worktree.sh before each step, _failsafe.py before the preview and
# during the merge wait, sync.sh).
SYNC_LANES = [("sclaude", "sclaude"), ("session", "Claude session")]
SYNC_NODES = {
    "y_when": ("sclaude", 0, "start", "Main checked",
               "before each step and the preview, after QA, every 2 min while the merge waits", ""),
    "merge_check": ('sclaude', 1, 'gate', 'Main merges cleanly?',
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

# A feature built in parts, out of the detailed map (parts.sh): its parts
# built one after another in step 2, the whole checked and accepted, then
# the parts made one branch; the detailed map goes on at step 3, with the
# feature's one pull request.
PARTS_LANES = [("sclaude", "sclaude"), ("session", "Claude session")]
PARTS_NODES = {
    "p_split": ("sclaude", 0, "start", "A plan in parts",
                "the plan's ## Parts; each criterion names its part", ""),
    "p_enter": ("sclaude", 1, "task", "On the part's branch",
                "<branch>-<n> off the part before it", ""),
    "p_code": ("session", 2, "session", "2 · code a part",
               "this part alone, read by a fresh subagent", "FR"),
    "p_built": ("sclaude", 3, "gate", "Another part to build?",
                "yes: the part's demo first, remarks to the next part", ""),
    "p_whole": ("session", 4, "session", "2 · code the whole",
                "every part built: checked as one, the demo, Accept", "FR"),
    "p_join": ("sclaude", 5, "task", "Parts made one branch",
               "the feature's branch moved to the last part", "S"),
    "p_stop": ("sclaude", 6, "end", "The parts wait",
               "the merge did not settle; what to do", ""),
    "p_on": ("sclaude", 7, "end", "On to step 3",
             "one pull request into main", ""),
}
PARTS_EDGES = [
    ("p_split", "p_enter", "", ""),
    ("p_enter", "p_code", "", ""),
    ("p_code", "p_built", "", ""),
    ("p_built", "p_enter", "yes — the next part", "back"),
    ("p_built", "p_whole", "no", ""),
    ("p_whole", "p_join", "accepted", ""),
    ("p_join", "p_stop", "a merge that did not settle", ""),
    ("p_join", "p_on", "", ""),
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
    "review_run": "o_review",
    "review_close": "o_review",
    "p_code": "o_code",
    "p_join": "o_pr",
    "epilogue": "o_epilogue",
    "done_cmd": "o_retro",
    "friction_left": "o_retro",
    "retro": "o_retro",
    "cleanup": "o_end",
    "end": "o_end",
}

# A place drawn only on a smaller map (the regression's, the parts') has no
# block of its own on the whole process: the one it happens inside is lit
# there with it, so that map does not stand blank while the feature is busy.
HOSTS = {
    "reg_local": "code",
    "fix_local": "code",
    "fix_preview": "review",
    "fix_prod": "review",
    "hold_ways": "prod",
    "p_code": "code",
    "p_join": "pr",
}


@contextlib.contextmanager
def configured(cfg):
    """The maps as cfg draws them, for what is drawn, lit or played inside:
    the model's tables stand in for the config's own meanwhile."""
    global NODES, EDGES, OVERVIEW_NODES, OVERVIEW_EDGES
    global DETAILS, POSITIONS, ALIAS, REGRESSION_NODES, REGRESSION_EDGES, SYNC_NODES, SYNC_EDGES
    saved = (NODES, EDGES, OVERVIEW_NODES, OVERVIEW_EDGES,
             DETAILS, POSITIONS, ALIAS, REGRESSION_NODES, REGRESSION_EDGES, SYNC_NODES, SYNC_EDGES)
    try:
        NODES, EDGES = process_config.for_config(cfg, NODES, EDGES)
        REGRESSION_NODES, REGRESSION_EDGES = process_config.for_config(cfg, REGRESSION_NODES, REGRESSION_EDGES)
        OVERVIEW_NODES, OVERVIEW_EDGES = process_config.for_config(cfg, OVERVIEW_NODES, OVERVIEW_EDGES)
        DETAILS = process_config._variant_details(cfg)

        def on(nid, nodes):
            hops = 0
            while nid and nid not in nodes and hops < len(process_config.PASS):
                nid, hops = process_config.PASS.get(nid, ""), hops + 1
            return nid if nid in nodes else ""
        POSITIONS = {k: on(o, OVERVIEW_NODES) for k, o in saved[5].items()}
        ALIAS = {k: v for k, v in saved[6].items() if k in OVERVIEW_NODES}
        # A block of the glance carries the letters of the step
        # it stands for: what happens inside it shows outside too.
        drawn = process_config.all_nodes()
        for nid, n in list(OVERVIEW_NODES.items()):
            big = drawn.get(ALIAS.get(nid, ""))
            if big:
                flags = "".join(f for f in "FWRS" if f in n[5] + big[5])
                OVERVIEW_NODES[nid] = n[:5] + (flags,)
        yield
    finally:
        (NODES, EDGES, OVERVIEW_NODES, OVERVIEW_EDGES,
         DETAILS, POSITIONS, ALIAS, REGRESSION_NODES, REGRESSION_EDGES, SYNC_NODES, SYNC_EDGES) = saved
