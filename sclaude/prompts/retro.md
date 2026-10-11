The feature "<feature>" is merged, and `sclaude` is about to remove its worktree, its branch and everything in `.sclaude/local/feature/`. Before it asks me, hold a retrospective of the whole feature with me while all of it is still on disk.

**What to read.**

<if:terminal>- `<terminal>` — the `sclaude` terminal as I saw it, from its first run on this feature to this one: everything `sclaude` printed — each session's last message and every change to the plan among it — and everything I typed. The sessions' own screens are not in it; a session that ran in this same window is one bracketed line naming it. Runs are separated by `=====` headings saying when each started. A run that went through the menu to another feature is included whole; skip the parts about other features. This is your main source — read all of it, in chunks if it is long.
</if:terminal>- `<worktree>/.sclaude/local/feature/` — `state.json` (steps, sessions, regression attempts, friction verdicts), `plan.md`, the friction logs, `review-yours` if present.
- The pull request #<pr><if:issue> and the issue #<issue></if:issue>, with `gh`, if you need what was said there.
- The session transcripts, only when you need what happened inside a session or there is no recording of the terminal — they are large: `<transcripts>/<session id>.jsonl`, the ids are in `state.json`. The raw terminal recordings are listed in `<terminal-raw>`.

**What to answer.** Three sections, in this order:

1. **What I may have missed.** Warnings that scrolled past, a question I answered without the information under it, a review thread left unanswered, something a session promised and did not do, a follow-up mentioned and never filed, uncommitted work, anything that exists only in this worktree. The worktree is still here, so this is the section to act on now.
2. **How I could work better.** Recommendations about how I drove this feature: where I waited, where I went round the same loop, where an earlier or a clearer answer would have saved a session.
3. **What `sclaude` could do better.** What this feature ran into in the orchestrator itself: a message that misled, a step that stalled, a question asked at the wrong moment, work a session did that `sclaude` could have done. Its source is in `<instruments>`; name the file and the function when you can.

Also say, in a line or two, what went well and is worth keeping.

**The rule for all three: facts only.** Every point stands on something you read — quote the line from the terminal or name the file and field. If you cannot point at it, leave it out. An empty section is a fine answer; write "nothing" under it. Do not pad a section to make it look useful.

Change nothing while you look: no edits, no commits, no comments, no messages. Afterwards, do only what I ask for in this conversation. Nothing you do changes `sclaude` itself: `<instruments>` is its checkout, read-only to you (a hook refuses writes there). What you find in section 3 is acted on in the product: a permission or ban the product should have goes into its policy (`.sclaude/team/policy.json` for its maintainers, `.sclaude/people/<name>/policy.json` for everybody else), and a preset of sclaude's that looks wrong for every product goes into the product's deferred file there, `deferred.tsv`, with class `sclaude-default` and one line on what it should become. Changing sclaude's defaults is a deliberate pull request to sclaude, never a side effect of this conversation.

A fix to the project is committed on this feature's own branch, `<branch>`, in `<worktree>` — no branch, worktree or pull request of your own for it. When this session ends, `sclaude` sees commits there that the merged pull request did not carry and sends the feature back to its pull-request step: that step opens the new pull request, the review step takes the automatic review's findings, and the preview, QA and the merge follow as for the feature itself. Once a fix went out from a branch of its own, and the review's findings on it sat with nothing in `sclaude` knowing the pull request existed.

**How this ends.** Give the three sections as your last message.

- **If sections 1 and 3 are both "nothing"**, `sclaude` closes this session itself. Write the marker first — `echo done > <done-marker>` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed. Say in the report that the session closes by itself, and that `sclaude` then asks about the clean-up.
- **Otherwise** leave the marker out: the session stays open so we can talk it through, and I close it with `/exit` when we are done. End the report by saying so, and that `sclaude` asks about the clean-up after that.
