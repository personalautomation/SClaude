Implement the feature "<feature>" following the plan in `.sclaude/local/feature/plan.md`. Read it first: it was written in the previous step specifically to hand off to you, and you have no other context from that conversation.

The plan is not binding. If it turns out to be wrong or incomplete, tell me before you deviate, and update `.sclaude/local/feature/plan.md` once we agree.

Ask me business-level questions, not technical ones: I care about what the user gets and how it behaves, not which files you touch.

Verify your work with the tools you have — primarily chrome-devtools MCP against the local dev server.

<include:dev-server>

If something is missing — the server isn't responding, the browser won't attach — say so instead of calling the step verified.

**Run only the tests this feature touches**: the specs you wrote or changed and the ones covering the code you changed, picked by file or by name through the project's own runner, plus checks that take seconds, such as typecheck. Don't run the whole suite here, e2e least of all. When this session closes, `sclaude` runs the full regression itself before the step can end, and a red run opens a fixing session with its log. A full run inside the session costs minutes of waiting and finds nothing that run won't.

<block:acceptance>

If there's no acceptance criteria block above, look for an `## Acceptance criteria` heading in `.sclaude/local/feature/plan.md` — step 1 writes the same list there. A feature that has neither was planned before criteria existed; work from the plan alone and don't invent them now.

Commit as soon as each piece works, following the project's commit rules, with `Requirement:` footers.

**Where a commit answers an acceptance criterion, its footer says so by identifier and by text:**

```
Requirement: AC2. A draft opens by direct link for its author and 404s for anyone else.
```

The identifier is a prefix, not a replacement: the wording stays because the footers are read by people and collected into the pull request, where `AC2` alone would send a reader off to find out what it meant. Copy the criterion's text as it stands in the list rather than paraphrasing it — a footer that drifts from the criterion it names is worse than one that doesn't name it. A footer is one line: a criterion with a list under its first line goes on it whole, its first line and then each item, separated by `; ` — `Requirement: AC6. The total shows:; for one order, its sum; a dash otherwise.`

A commit nobody asked for carries no `Requirement:` footer.

### When I ask for something new

A requirement that appears after planning is either a criterion we missed or a change of scope, and both are mine to decide — **so ask at once, through `AskUserQuestion`, before building it**, not in the report at the end: "a new criterion `AC<next>`" (recommended when it is something a tester would check) or "outside the criteria". A question at the end of a long report is a question I miss.

- **A new criterion:** add it to the `## Acceptance criteria` section of `.sclaude/local/feature/plan.md` under the next free identifier, worded as the others are — observable behaviour, checkable on a deployment. Never renumber or reword an existing one; if one has to change, tell me, and I'll edit it in the issue. Its commits get the footer with the identifier. When this session ends, the orchestrator appends the new criteria to the list in the issue, where QA ticks them.
- **Outside the criteria:** the footer without an identifier.

<if:issue>Either way, **record it in the `User request` comment** on the issue, the same session you hear it. What I want is known only from talking to me; a requirement that lives only in a commit footer leaves the issue describing a scope that is no longer the one being built. Add a `### Added during development` section at the end of the comment (or extend it), one line per request: what I asked for in my terms, and `(AC<n>)` where it became a criterion. Restate, don't extend or compress; don't touch what step 1 wrote above it. Re-read the comment before rewriting it — I may have edited it in GitHub — and rewrite it in place, never post a second one:

<block:user-request>
</if:issue>
Don't touch the product's manuals: <manuals>. It's written in the next step, after the feature is accepted: a manual written during development gets rewritten with every change.

<block:regression>

<include:questions>

<include:friction>

**How this session ends.** You are step 2 of four; the `sclaude` orchestrator drives the steps from outside. The pull request is step 3 — a separate session with a different model and prompt, launched by the orchestrator once I say development is done.

The orchestrator runs this step with restrictions: `gh pr create`, merge, deploy and anything leading to production simply won't run here. A rejection is the step's boundary, not a failure.

<include:report>

**When the work is done, `sclaude` closes this session itself.** Write the marker first — `echo done > .sclaude/local/feature/session-done` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed; write it again when you are done again. After the session closes, sclaude asks me whether everything works; if I say no, I come back to this same conversation with what is wrong. Leave the marker out when something needs my answer before the work can be called done — then I close the session myself.

Once the work is done, tell me in that one message — in your own words, but cover all of it:

- the work in this session is done — what's ready, and what's left open;
- **each acceptance criterion by identifier, and where it stands**: done and verified how, done but unverified, or not done and why. Go through the list rather than summarising it — a criterion you don't mention reads as one you forgot, and this is the last moment it's cheap to fix. If there were no criteria, say that instead;
- with the marker written, that `sclaude` closes this session itself; without it, that I should now close Claude with `/exit`;
- after that the `sclaude` orchestrator continues — it asks me to confirm the work, then launches step 3 itself.

Then stop. Don't offer to open a pull request and don't ask whether to: I can't say yes anyway, since the next step starts when this session closes.
