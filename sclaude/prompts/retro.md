The feature "<feature>" <if:pr-number>is merged</if:pr-number><if:no-change>has ended without a change of its own in this repository, so it has no pull request</if:no-change>, and `sclaude` is about to remove its worktree, its branch and everything in `.sclaude/local/feature/`. Before it asks me, hold a retrospective of the whole feature with me while all of it is still on disk.

**What to read.**

<if:terminal>- `<terminal>` — the `sclaude` terminal as I saw it, from its first run on this feature to this one: everything `sclaude` printed — each session's last message and every change to the plan among it — and everything I typed. The sessions' own screens are not in it; a session that ran in this same window is one bracketed line naming it. Runs are separated by `=====` headings saying when each started. A run that went through the menu to another feature is included whole; skip the parts about other features. This is your main source — read all of it, in chunks if it is long.
</if:terminal>- `<worktree>/.sclaude/local/feature/` — `state.json` (steps, sessions, regression attempts, friction verdicts), `plan.md`, the friction logs, `review-yours` and `regression.notes` (what a regression fixing session found outside the branch, and what it said would have to change) if present.
- <if:pr-number>The pull request #<pr-number><if:issue> and the issue #<issue></if:issue></if:pr-number><if:no-change>The issue #<issue></if:no-change>, with `gh`, if you need what was said there.
- The session transcripts, only when you need what happened inside a session or there is no recording of the terminal — they are large: `<transcripts>/<session id>.jsonl`, the ids are in `state.json`. The raw terminal recordings are listed in `<terminal-raw>`.

**What to answer.** Three sections, in this order, and a fourth when you have something for it:

1. **What I may have missed.** Warnings that scrolled past, a question I answered without the information under it, a review thread left unanswered, something a session promised and did not do, a follow-up mentioned and never filed, uncommitted work, anything that exists only in this worktree. The worktree is still here, so this is the section to act on now.
2. **How I could work better.** Recommendations about how I drove this feature: where I waited, where I went round the same loop, where an earlier or a clearer answer would have saved a session.
3. **What `sclaude` could do better.** What this feature ran into in the orchestrator itself: a message that misled, a step that stalled, a question asked at the wrong moment, work a session did that `sclaude` could have done. Its source is in `<instruments>`; name the file and the function when you can.

4. **Settings that would make me faster** — optional. Which of `sclaude`'s settings would suit the way I worked on this feature: the project's choices in `<instruments>/sclaude/config.example.json` against `<config>`, a copy of the main checkout's `.sclaude/config.json` — shared by everybody on the project, so say so — and the personal `SCLAUDE_*` switches in the table in `<instruments>/README.md`. Each one with how it is set (`sclaude config set` takes only `review`, `qa`, `merge`; the rest is edited in that file, not in the copy), the moment in this feature it would have saved, and how sure you are, as a percentage. Offer only a setting you are at least 70% sure of, and leave out the rest without a word. Leave the whole section out, heading and all, when no setting is left — nothing in this feature points at one, or none reaches 70%; it does not keep the session open.

Also say, in a line or two, what went well and is worth keeping.

**The rule for all of them: facts only.** Every point stands on something you read — quote the line from the terminal or name the file and field. If you cannot point at it, leave it out. An empty section among the first three is a fine answer; write "nothing" under it. Do not pad a section to make it look useful.

This session is in plan mode. Change nothing while you look: no edits, no commits, no comments, no messages. Afterwards, do only what I ask for in this conversation, and each time as a plan first: what changes, in which file or where, and why. Once I approve it, make it; the plan I approve is my yes, also for opening `sclaude`'s workshop.

<include:retro-rules>

<block:workshop>

**How this ends.** Give the sections as your last message.

- **If sections 1 and 3 are both "nothing"**, `sclaude` closes this session itself, with nothing for me to approve. Say in the report that `sclaude` then asks about the clean-up, and end it on this line, alone, as its very last line: `<nothing-said>`. That line is the signal; no tool call after it. End this turn on that message rather than on a plan or a question, though plan mode asks for one: there is nothing to plan. Should you give the report itself as a plan all the same, that plan carries every section in full, not a summary: it is what `sclaude` prints as your report. The plans for changes I ask for later are only the changes. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off.
- **Otherwise** give them as a message, not as a plan, and without that line: the session stays open so we can talk it through, and I close it with `/exit` when we are done. End the report by saying so, and that `sclaude` asks about the clean-up after that.
