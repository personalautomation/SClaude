Implement the feature "<feature>" following the plan in `.sclaude/local/feature/plan.md`. Read it first: it was written in the previous step specifically to hand off to you, and you have no other context from that conversation.

The plan is not binding. If it turns out to be wrong or incomplete, tell me before you deviate, and update `.sclaude/local/feature/plan.md` once we agree.

<if:in-parts>**This feature is built in parts, and this session builds part <part> of <parts>: <part-title>.** The plan's `## Parts` section says what it covers and where its line runs; build that and nothing of the parts after it. Their criteria are not in the list below — they belong to their own parts — and the earlier parts are already in this branch: the tree is on the part's own branch, made off `<part-base>`. No part has a pull request or a review: once every part is built I check the whole feature, and only then do the parts become one branch and one pull request, reviewed as a whole.

- **A migration an earlier part made is not edited:** your database ran it already. A change to what it made is a new migration on top.
- **When I ask for something, you decide where it goes, not me.** What is built already — this part or an earlier one — is changed now, here. What `## Parts` gives a later part is written into that part in the plan, and you tell me in one line ("goes into part 3, noted"). Unsure: now, and say where you put it.
- **Before the part closes, have it read with fresh eyes.** Start a subagent on this part's diff (`git diff <part-base>...HEAD`) with the plan, and ask it for what would cost more to fix later than now: design the next parts will build on (data, contracts between modules, where logic lives), bugs the tests miss, a criterion not really met. Not style or naming — the full review reads the whole feature after I accept. Fix what you agree with, in this part, earlier parts' code included; run the touched tests. If the fixes were more than small, run a fresh subagent on the new diff. Stop when a round brings nothing you would fix, three rounds at most. In the report, one line per round: found, fixed, left and why.
<if:part-alone>
**How this part's session ends.** Not with the question below: I check the whole feature once every part is built, and am not asked about a part. When the part is built, its tests green and its commits made, write the marker — `echo done > .sclaude/local/feature/session-done` — then your report as the last message, with no tool call after it. About thirty seconds after your turn ends `sclaude` closes the session, runs the regression, and starts the next part. If something needs my answer first, ask it with `AskUserQuestion` before the marker, as always.

**I see each part as soon as it is built.** Between two parts `sclaude` records a demo of what the part just built added and sends it to me, so a remark about an earlier part may reach this session while you build this one. It is a request like any other: placed by the rule above, and what it changes in an earlier part's code is committed here.
</if:part-alone></if:in-parts><if:parts-built>**Every part of this feature is built, and the tree is on the last part's branch, which carries them all.** This session is where the whole feature is checked as one: run it end to end against the plan and every acceptance criterion below, the parts together, and fix what does not hold — a seam between two parts, a criterion two parts each assumed the other made true. Your fixes are commits on this branch: they go into the feature's pull request with the parts. After my Accept the parts become one branch, `<umbrella>`, and one pull request into main.
<if:demo>
**The whole feature's demo starts from the parts' own.** `python3 ~/.claude/skills/sdemo/demo.py parts` lists the demo recorded for each part between the parts, with its script. Write the whole feature's script from them, not from scratch: keep the scenarios that still show the feature as it is, rewrite what a later part or my remarks changed, and add what only the parts together show. `none:` means no part has one: write it as usual.
</if:demo><if:parts-dropped>
**I ended the parts early: parts <parts-dropped> (by number, in the plan's `## Parts`) are left out of this feature.** Before anything else: strike their criteria in the plan with the identifier inside the strike, `- [ ] ~~AC7. …~~`, never renumbering; file what they were to build as one issue of its own — their scope from `## Parts`, and what it builds on here (`gh issue create --title … --body-file -`)<if:issue>, made a sub-issue of #<issue> (`gh api repos/{owner}/{repo}/issues/<issue>/sub_issues -F sub_issue_id=<id>`, the `id` from `gh api repos/{owner}/{repo}/issues/<new number> --jq .id`)</if:issue>; and take their lines out of the acceptance criteria comment on the issue, between its markers, so QA tests what is built. Name the new issue in your report.
</if:parts-dropped></if:parts-built>

Ask me business-level questions, not technical ones: I care about what the user gets and how it behaves, not which files you touch.

Verify your work with the tools you have — primarily chrome-devtools MCP against the local dev server.

<include:dev-server>

If something is missing — the server isn't responding, the browser won't attach — say so instead of calling the step verified.

**Run only the tests this feature touches**: the specs you wrote or changed and the ones covering the code you changed, picked by file or by name through the project's own runner, plus checks that take seconds, such as typecheck. Don't run the whole suite here, e2e least of all. When this session closes, `sclaude` runs the full regression itself before the step can end, and a red run opens a fixing session with its log. A full run inside the session costs minutes of waiting and finds nothing that run won't.

**Tests.** Rather than a new test, prefer extending one that already walks the path — a case, an assertion, a rename if its scope grows: every new spec, e2e above all, adds fixtures and minutes to each regression after it. See each test you wrote or changed fail once, on the code before your change: one never red may pass whatever the code does, as `toBeVisible()` did on a screen-reader-only element, which Playwright counts as visible.

**Smoke.** Where `.sclaude/config.json` has `commands.smoke`, that command picks the product's few vital paths out of its suite — by a tag such as `@smoke`, as the command shows — and a deployed stage may run only those. When this feature adds a path a person depends on to get their work done, tag the one spec that walks it end to end, and no more: the smoke set stays short enough to run in a minute.

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

- **A new criterion:** add it to the `## Acceptance criteria` section of `.sclaude/local/feature/plan.md` under the next free identifier, worded as the others are — observable behaviour, checkable on a deployment.<if:in-parts> It names this part after its identifier, `AC<next>. [part <part>] …`.</if:in-parts><if:part-again> It names this part after its identifier, `AC<next>. [part <part>] …`.</if:part-again> Never renumber or reword an existing one; if one has to change, tell me, and I'll edit it in the issue. Its commits get the footer with the identifier. When this session ends, the orchestrator appends the new criteria to the list in the issue, where QA ticks them.
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

<if:demo>**Before the report, show me the work: run the `sdemo` skill, `/sdemo`.** It records the feature's main functionality — signed in as the users each scenario needs, clicking through, with captions on what to look at, on a desktop and on a phone — and sends the page's link with the videos to the feature's Telegram topic and to a comment of its own on the issue. Put that link first in the report, so I can watch before I answer. After fixing my remarks, record again before asking again — but only when the code changed since the last demo: `python3 ~/.claude/skills/sdemo/demo.py stale` exits 0 with `stale:` when it did, and 1 with `fresh:` when the demo still shows the code as it is; a demo costs minutes and a model's work. Then first `/sdemo delta` — a short recording of only what changed for me since the last demo, so I need not watch the whole one again; none when nothing changed for a user — and then `/sdemo`, the whole feature again. Put both links first in the report. If no demo can be made — nobody in the feature's database to sign in as, the player failing twice on the same step — say why in one line and ask all the same: the demo is a way to check the work, not a condition for accepting it.
</if:demo>

<if:demo><include:demo-link></if:demo>

<if:asks-accept>**When the work is done, I accept it here, in this session.** In this step the report above is not the last message: write it in full, then — with no tool call between the two — put one question to me with `AskUserQuestion` — this question and no other, its header and both option labels exactly as written here, in English, with no `(Recommended)` mark, whatever language we speak; the question text and the descriptions are yours, in my language. `sclaude` prints the report given before the question, so after `Accept` nothing but the one line below follows it — no second report:

- header: `Accept work`;
- question: whether I accept the work — everything works as it should, and the step can close;
- option `Accept` — everything works: the session closes and `sclaude` goes on to step 3 without asking again;
- option `Remarks` — something is wrong or missing: I write it in the notes or as my own answer, and we carry on here.

**On `Accept`** with no notes: write the marker — `echo accepted > .sclaude/local/feature/session-done` — then one short line that the step is accepted, with no tool call after it. `sclaude` closes the session a few seconds later and continues by itself: the regression, then step 3.

**On anything else** — `Remarks`, my own answer, notes beside `Accept`, the dialog dismissed — write no marker. Take what I said as the next thing to fix; if I chose `Remarks` without saying what, ask me what is wrong. When it is fixed, report again and ask the same question again. Typing to you after `Accept` takes it back too: the marker is removed, and you ask again when you are done again.

Leave the question out when something needs my answer before the work can be called done — a proposal, a decision only I can make: then put that to me instead, and I close the session myself with `/exit`; `sclaude` asks me then whether everything works, and a no brings me back to this same conversation with what is wrong.
</if:asks-accept>

The report, before the question — in your own words, but cover all of it:

<if:demo>- the demo's link (above), or why there is none;
</if:demo>- the work in this session is done — what's ready, and what's left open;
- **each acceptance criterion by identifier, and where it stands**: done and verified how, done but unverified, or not done and why. Go through the list rather than summarising it — a criterion you don't mention reads as one you forgot, and this is the last moment it's cheap to fix. If there were no criteria, say that instead;
<if:asks-accept>- that on `Accept` `sclaude` closes this session itself and goes on<if:in-parts> to the next part</if:in-parts>; without the question, that I should now close Claude with `/exit`.
</if:asks-accept><if:in-parts>- the fresh-eyes rounds, a line each;
- what the next part will find in place from this one, and anything it has to know.
</if:in-parts>

Don't offer to open a pull request and don't ask whether to: the next step starts when this session closes.
