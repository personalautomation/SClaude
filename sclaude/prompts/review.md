Pull request #<pr> for the feature "<feature>" is open. Your job here is to get it to a mergeable state.

Feature context is in `.sclaude/local/feature/plan.md`: what we promised and why that way. Read it before agreeing to a comment that proposes changing behaviour.
<if:in-parts>
**This pull request is part <part> of <parts> of a feature built in parts — <part-title> — and it goes into `<base>`, not main.** The person has accepted the whole feature already; its parts are reviewed one by one, in the order they were built. The earlier parts are merged into `<base>` after reviews of their own, and `<base>` was merged into this part's branch before its pull request opened, so this diff is this part alone; a merge commit in it is that merge, and conflicts resolved by hand in it are worth a look: the plan's `## Parts` says where its lines run, and its criteria are the ones marked `[part <part>]`. A finding about code this pull request does not change belongs to an earlier part: reply in the thread where that code came from, and treat it as one you would leave — ask me, as below. A fix that changes an earlier part's code still goes here, in this part, with a line in that part's pull request about where it was fixed. The orchestrator merges this pull request into `<base>` itself once the review closes, and the next part starts.
</if:in-parts><if:parts-done>
**This is the feature's pull request into main, and it carries parts already reviewed one by one** in pull requests of their own into `<umbrella>` (its description lists them). Its review reads what none of them could: the seams between the parts — what one part promises and another relies on, the same thing done twice, a manual or a migration out of step — and what came onto `<umbrella>` after the parts (the whole-feature check's fixes, a sync with main, QA's returns), each read in full. Threads left open on the parts' pull requests after they were merged are listed in the snapshot below: answer each in its own thread, and make the fix here, on `<umbrella>`.
</if:parts-done>
The orchestrator captured the PR state as of the start of this step — checks and all comments:

<block:pr-context>

**The review is sclaude's to wait for, not yours.** Wherever it runs — the project's workflow in GitHub Actions, or on this machine — it reads your pushes after this session ends. So do not wait for it, and do not run one yourself: fix or decide every thread, push the fixes, get the checks green, and finish as the end of this prompt says, marker included. sclaude then waits for the review of your last push (or runs it here), and brings back what is open: to this conversation while its context is light, to a fresh session otherwise.

<if:review-local>**This feature is reviewed on this machine** (`review: local` in sclaude's config: `.sclaude/config.json`, or this machine's `.sclaude/local/config.json` over it — or `github-local`, and GitHub's review could not run for this feature). sclaude runs `/code-review` itself and posts its findings as threads on the pull request, under my account, each ending with a "Local review" line; they are review threads like any other, so everything below about them holds — fix, or propose to resolve, `Left as it is`, `review-yours`.

<if:actions-off>**Nothing in this project's flow runs on GitHub Actions.** It reviews here because the Actions minutes ran out, and with none left every workflow still starts and fails at once. So a red check GitHub Actions ran (`gh pr checks` lists them: the review, the build and lint checks, @claude) says nothing about the code: do not fix, rerun or report it. `sclaude checks` leaves them out and waits only for the others, such as a deployment. What those workflows checked you check here: before each push, run the checks the change calls for (step 2 below); sclaude runs the project's whole local regression itself before it closes this step.
</if:actions-off>
</if:review-local>1. Handle each comment individually. Where you agree, fix it. Where you don't, explain why to me and leave the decision to me; don't argue with the reviewer in comments under your own name.

   **A thread you would leave as it is, you propose to resolve, and resolve it yourself once I say yes.** Don't change the code for it. Ask me through `AskUserQuestion`, one question per thread, in so many words: "I want to resolve this comment on GitHub: <link> — <the finding in a line>. Leaving it because <why>." The options are to resolve it (first, `(Recommended)` when it is your advice), to fix it after all, and to leave it open for me to resolve by hand. When the why does not fit in a question — a trade-off, more than one way to go — write it out in your message before the question: each option and what it means for the business and for the people who use the product (what they would see, what it costs, what risk stays), not only for the code. The question then stays short and points at that text.

   Only on my explicit yes: reply in the thread with my decision in a line, then resolve it — find its id, post the reply with `addPullRequestReviewThreadReply`, and pass the id to `resolveReviewThread`. The reply **starts with `Left as it is, at the author's decision:`** and the decision follows the colon: the review workflow counts a thread as declined only by that opening, and tells the next review not to raise it again (`FINDINGS_DECLINED` in the project's `.github/workflows/claude-code-review.yml`); a thread resolved without it counts as fixed. When the thread repeats one I decided before, say so after the colon, `as on r<id>`, with the number from the earlier thread's link (`#discussion_r<id>`): `sclaude review-report` counts these to show how often the review raises what I already declined.

   ```
   gh api graphql --paginate -f query='query($o:String!,$r:String!,$n:Int!,$endCursor:String){repository(owner:$o,name:$r){pullRequest(number:$n){reviewThreads(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{id isResolved comments(first:1){nodes{url}}}}}}}' -F o={owner} -F r={repo} -F n=<pr> --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.comments.nodes[0].url | endswith("#discussion_r123")) | .id'
   gh api graphql -f query='mutation($id:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$b}){comment{url}}}' -F id=<thread id> -f b="Left as it is, at the author's decision: <the decision>"
   gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=<thread id>
   ```

   Do it before your next push, so the round that push starts does not count the thread as open. Anything short of a yes — no answer, "later", a question back — is not one: the thread stays open.

   **At night (`/isleep`) there is nobody to say yes, and a thread you would leave must not hold the step till morning.** First tell a minor thread from the rest. Only the review's finding alone can be minor, and you check it on GitHub right before you resolve, not from the snapshot, which may be hours old: a person's thread, and one with a reply from anybody — mine, a decision, a resolver's, including one I reopened after it — are mine to decide. A thread is minor when leaving it as it is puts nothing at risk for the people who use the product, for their data or for security, changes nothing the plan or its acceptance criteria promise, and weakens no check, test or guard; style, a duplicate, an optional refactor. When in doubt, it is not minor.

   **A minor thread you resolve yourself at night, without asking.** First read it fresh, by the thread id the query above finds:

   ```
   gh api graphql -f query='query($id:ID!){node(id:$id){... on PullRequestReviewThread{isResolved comments(first:2){nodes{author{__typename} body}}}}}' -F id=<thread id>
   ```

   It qualifies only when it is unresolved and has exactly one comment, whose author's `__typename` is `Bot` or whose last line begins with `<sub>Local review`; anything else takes the path of the next paragraph. Then reply in it and resolve it with the calls above, the reply starting `Left as it is, minor — resolved at night without the author:` and your reason after the colon, with `as on r<id>` when it repeats one I declined before, as by day (the `Left as it is` opening is what counts it as declined; the author did not decide, so the reply does not say they did). Log each one in the night's log as a decision you took, as the isleep skill asks of every decision. In your report, list each one under a heading **Resolved at night as minor**, with its link and the reason in a line, so I see them in the morning; a thread I disagree with I unresolve on GitHub, and it is open work again. This is the one thing a night session posts on GitHub. Once a minor thread put to the person as a question held a review round for most of an hour by day; at night the same wait lasts till morning.

   **Any other thread to leave waits for my yes in the morning.** Do not ask, and post nothing on GitHub: take the hand-resolving path below without its reply — the line in `review-yours`, the decision being your recommendation followed by `(isleep — to confirm; no reply posted — reply with the Left as it is opening before resolving)` (no apostrophe in it: the line goes through the single-quoted `printf` below), since sclaude prints that note beside the link and a thread resolved without that reply counts as fixed and is raised again — list the thread under **Resolve on GitHub yourself**, and finish the round as usual, marker included. In the morning sclaude offers me a session for these threads. A finding you would fix after all you fix, as by day. Once a thread waiting for a yes kept a session open from one in the night till morning, with the rounds that could have run in that time not run.

   **By day, start with the threads left at night.** A thread the snapshot lists or marks **Left at night for the person to confirm** — still in `review-yours`, or taken back from it to `review-night` at my word — is one to ask me about before anything else, unless it is night again: through `AskUserQuestion` exactly as the rule above asks by day — the link, the finding, why to leave it — with the same three options. Whatever I answer, first delete the thread's night line, from `review-yours` or `review-night`, so it is not put to me again. On my yes, reply with my decision and resolve the thread (the calls above). On "fix it after all", fix it as any finding. On "I resolve it by hand", post the reply without resolving and write its line to `review-yours` with my decision, as the next paragraph says. Report each among what was done. The night's decisions on these threads are only proposals: none is mine until I answer, and none is acted on without it.

   **When I say I will resolve it by hand, or the call above fails, write it down.** When I resolve it by hand, first post the same reply in the thread (the reply call above, without resolving), so I only press Resolve; if posting fails, say so next to that thread's link in the report, so I write the reply myself, starting with `Left as it is`. Then append one line to `.sclaude/local/feature/review-yours` — the thread's link (the snapshot gives it after each thread's author, `…/pull/<pr>#discussion_r…`; for a newer thread it is the `html_url` of its first comment in `gh api repos/{owner}/{repo}/pulls/<pr>/comments`), a tab, and my decision in a few words:

   ```
   printf '%s\t%s\n' 'https://github.com/…/pull/<pr>#discussion_r123' 'leave as it is: the fix would undo d60ca78' >> .sclaude/local/feature/review-yours
   ```

   From then on no session asks me about it again: the snapshot lists it apart, the orchestrator does not send the work back for it, and it prints the links for me to resolve. In your report, list each such thread under a heading **Resolve on GitHub yourself**, with its link and one line on what was decided — the first thing in the report after what was done, not inside "what is left open". Once one thread was put to me in three rounds running because none of this was written anywhere. The threads you resolved on my yes go into the report too, each with its link and the decision, among what was done.

   **Fix through subagents.** Give each finding — or a few that touch the same code — to a subagent (the Agent tool): the finding's text verbatim, its `path:line`, what you know about why it is right, and the brief below. It reads and edits in its own context and reports back what it changed. You read its diff, decide whether it does what the finding asks, and keep the coordination — the checks, the commit, the push — yourself. Your context is what carries the round; spending it on every file a fix had to read is what made one conversation run out over five rounds. Fix a finding yourself only when it is a line or two — or when the round's findings all sit in code you have already read, a few dozen lines in all: a subagent would read again what you already hold, and your context stays bounded anyway, since sclaude gives the next round a fresh session once yours is past its limit or its cache has gone cold. Fixing such a round yourself is not a deviation to report; the brief below holds for you then as it would for a subagent.

   **The brief: fix the finding and its class, not the one line it cites.** On one pull request most findings after the third round were the last fix repeated one place over: Restore guarded and Delete not, the light-theme hover pinned and the dark one not, four button variants out of eight, a function changed and its `comment on`, both manuals and its in-body comment still describing the old rule. Each of those cost a review round. So the subagent fixes:

   - the cause, where the finding points at one — a sweep that has to repeat a filter because the guard is wrong is fixed in the guard;
   - every other place in the pull request with the same pattern: search the pull request's diff (`git diff origin/<base>...HEAD`) and the code it touches, not only the cited line;
   - every comment, doc comment, SQL `comment on`, manual page and test label that describes the behaviour the fix changes;
   - a test where none pins the fix yet, preferably by extending an existing one, and each test it wrote or changed seen red once on the code before the fix;
   - and nothing that is not about the finding.

   It reports the other places it found and what it did with each, so you can see the class is covered. Where a finding proposes a fix, the subagent weighs it and picks the one that leaves the least new code to review: a suggested cache, helper or abstraction is new surface the next round will read, and once one suggested cache took five rounds of its own.

   **A fix that would undo an earlier one is not a fix.** The snapshot lists the resolved threads on the files that still have open ones. When applying a new finding would reverse what one of those settled — move a check back where it was, restore a flag that was removed — do not apply it: tell me both and leave the choice to me, as with any finding you disagree with. And note it, one line in `.sclaude/local/feature/review-reversals`: the thread's link, a tab, and what it would undo (`printf '%s\t%s\n' '<link>' 'moves the check back out of the guard, settled in d60ca78' >> .sclaude/local/feature/review-reversals`). The orchestrator counts these per round, to see whether a long conversation still holds on to what it settled. Once one filter moved from the sweep to the guard, to the action and back to the guard, and a hook flag went from `--silent` to `--loglevel=error` and back, each round in a session that could not see the last.

   **A finding that only a rule made — a candidate to relax.** Some findings point at nothing wrong with the code: a `CLAUDE.md` line, or a project rule the reviewer applies, is stricter than it needs to be, says again what another rule or a check already covers, or no longer fits the code. Fix such a finding as usual — this pull request is not where the rule is changed — and log the rule as a candidate to relax, in the shape the friction note below gives for proposals: `<date> proposal (claude-md-relax-<topic>): relax: <the rule, quoted or named by its file and heading>`, and on the indented lines after it the finding it produced and why it protects nothing here. The `claude-md-relax-` class keeps them apart from new rules; once a month they are read with the other proposals, and a rule that keeps producing such findings is loosened or dropped then, by the count rather than by one round's irritation. Not every finding you disagree with is one: a rule that caught a real slip is doing its job.

   **A finding on the review's own workflow file is never fixed in this pull request.** claude-code-action skips the review of a pull request whose copy of its workflow differs from `main`'s, so the fix silences every later round: once it was committed, reverted, and moved into a pull request of its own. When I am asked about such a finding, the choice to put to me is a separate pull request from `main`, or leaving it.

   **A finding on a deferred file is never fixed either.** The files under `.sclaude/team/deferred/` and `.sclaude/people/*/deferred/` are a log for the monthly review, not code: a row that repeats another is how that review counts how often a class comes back, so "duplicate row", "same proposal again" and the like point at the design, not a slip. The rows also go to `main` by themselves, past the pull request; one reaches this pull request only when its branch already carried entries. Do not edit, merge or drop rows for such a finding: propose to resolve the thread as above, with resolving as the recommended answer and "a repeated deferred row is a count the monthly review reads; dropping it loses the count, and nothing that runs changes either way" as the why. Once a deferral commit drew two such findings after the last round, and nobody was there to tell the reviewer the repeats were meant.

   **A class that comes back becomes a rule.** When a finding is the second of its class on this pull request — the same kind of place missed, a comment left describing old behaviour, a variant not covered — write one line for the project's `CLAUDE.md` that would have prevented both into `.sclaude/local/feature/friction.log` as a proposal (see the friction log below); do not write it into `CLAUDE.md` — that is mine to change, and the proposals are decided together, by how often they come back. A rule there reaches the step that writes the code, before any review sees it.

   The snapshot above was taken at launch, and a comment may have appeared since. Before treating the list as complete, re-read:

   ```
   gh pr checks <pr>
   gh pr view <pr> --comments
   gh api repos/{owner}/{repo}/pulls/<pr>/comments
   ```

   A non-zero exit from `gh pr checks` means "there are red checks", not "the command failed".

2. If you changed code, run the checks the change calls for before pushing: the project's own `typecheck` and `lint`, the commands named under `commands` in `.sclaude/config.json` (whichever of the two it names), plus whatever further checks the project's `CLAUDE.md` asks for after the kind of change you made. If you changed nothing, there's nothing to run: step 2 does not close until the full regression is green, and the code hasn't changed since.

3. Commit fixes to the same branch following the project's commit rules, and push. A review fix isn't something I asked for, so it usually needs no `Requirement:` footer — unless the comment exposed a real requirement we missed.

   When a fix changes something the pull request's description states — a mechanism, a list, a count of tests — rewrite that part of the description in the same round (`gh pr view <pr> --json body --jq .body`, edit, `gh pr edit <pr> --body-file <file>`). It was written at step 3, and the merge summary and the issue's status comment are written from it: once it said "16 cases" for the 52 the review rounds left, and the issue's status repeated it.

   **When a thread ends in a change of what the feature does, the record changes with the code.** A decision of mine that moves behaviour away from the plan — an acceptance criterion now worded wrong, a prompt, a route or a migration the plan said there would be none of — goes into `.sclaude/local/feature/plan.md` the same round: the change is noted under a `## Agreed during review` section at its end. Never reword or add an acceptance criterion on your own: ask me through `AskUserQuestion` with the wording you propose — for a new one, under the next free identifier. On my yes, put that wording into the plan's acceptance criteria under its identifier, in place of the old line (the old wording stays in `## Agreed during review`), and leave the issue to `sclaude`: as the review closes it adds a new criterion to the issue, shows me a reworded one beside the issue's text and writes it there at my yes — QA ticks the list there, and a box ticked against the old wording accepts what was never built. Once a criterion changed in review was left for me to carry into the issue by hand, nobody did, and the automatic QA ticked the old text.

<if:issue>   Record the decision in the `User request` comment on the issue too: a `### Added during review` section at the end of the comment (or extend it), one line per decision, what I asked for in my terms. Restate, don't extend or compress; don't touch what is above it. Re-read the comment before rewriting it — I may have edited it in GitHub — and rewrite it in place, never post a second one:

<block:user-request>
</if:issue>

   A push reruns the PR checks, and a fix for a failure can break them again. Wait and look again with `sclaude checks <pr>`, run from this worktree in the background (it can take up to an hour, longer than a command in the foreground may run). It returns by itself once every check of the pushed commit has finished — the build, the tests, a deployment; not the review, which sclaude waits for once you have finished. Do not use `gh pr checks --watch` for it, and do not write a polling loop of your own. It prints the checks and then one verdict line, whose first word and exit code say how it ended:

   - `0` green — every check finished green;
   - `1` red — every check finished, these are red: read them as below;
   - `3` not finished — the checks were still running or queued when the time ran out: say so in your report, with the line it printed, and write no marker — the session stays open for my answer;
   - `4` could not read — GitHub did not answer, the pull request is not open, or commits here are not pushed: the line says which; fix what it names and run it again.

   `jq` is not installed on this machine: filter `gh` output with its own `--jq`. A background loop whose condition can never be true does not fail — it hangs, and the turn waits on it with nobody told. While a check is red the work isn't done, whatever is failing — your code, someone else's, or a flaky test. Flaky is a conclusion, not a guess: rerun (`gh run rerun <run-id> --failed`) and confirm.

4. **This session's round ends with your last push.** Once every thread is fixed and pushed, or decided, and `sclaude checks` returned `0`, finish as below, marker included. When sclaude brings this conversation back with the review's answer to your push:

   - **a thread you were fixing is still open, or a new finding is on your own fixes** — code a commit of yours in this conversation wrote or changed: a bug the fix brought in, or the fix left half done — fix those first. They are your work, and only this conversation knows what the fix was for and what was tried before it. Four such returns at most: when the review finds your fixes of your fixes wrong a fifth time, stop and put it to me — what keeps breaking, what you tried each time, and the ways out you see — with no marker, so the session stays open for my answer. A fresh session would not break that loop; a decision from me can;
   - **new findings on code you did not touch** — they are yours now, like the rest: sclaude brought them here because this conversation still has room for them.

   Threads written in `.sclaude/local/feature/review-yours` count as resolved: they wait for my hand, not for a session.

<include:dev-server>

<block:regression>

<include:questions>

<include:friction>

**How this session ends.** You are step 4, the last one; the `sclaude` orchestrator drives the steps from outside. There are no further sessions: merge, migration promote and `vercel --prod` I do by hand, and the orchestrator reminds me of them when I exit.

The preview deploy isn't yours: the orchestrator offers it when I exit. It can do what you can't from here — the project link lives in `.vercel/` of the main repo, not in this worktree, and `vercel` run here would create a new project instead of deploying to ours.

The orchestrator runs this step with restrictions: merge, deploy, `--no-verify` and anything leading to production simply won't run here. A rejection is the step's boundary, not a failure; `git push` of fixes to the branch is allowed.

<include:report>

**When every thread is handled and your last push is green, `sclaude` closes this session itself.** Write the marker first — `echo done > .sclaude/local/feature/session-done` — and then the report, with no tool call after it. About thirty seconds after your turn ends the orchestrator closes the session, prints the report, waits for the review of your last push (or runs it here), and checks the pull request: if anything is open, it sends the work back — to this conversation while its context is light, to a fresh one otherwise. If I type anything in those thirty seconds, the closing is called off and the marker removed; write it again when you are done again.

Leave the marker out when something is left for me to decide — a red check you could not fix, a comment you disagree with that I have not answered yet. Then I have to answer you, and I close the session myself. A thread I already decided to leave, written in `.sclaude/local/feature/review-yours`, is not one of those: it counts as handled here, and the orchestrator waits for me to resolve it on GitHub.

Once the comments are handled and the PR checks are green, tell me in that one message — in your own words, but cover all of it:

- the work in this session is done — the pull request is ready to merge, and what's left open. If something didn't come together — a red check, a comment you disagree with — say exactly what's left rather than passing it off as ready;
- with the marker written, that `sclaude` closes this session itself; without it, that I should now close Claude with `/exit`;
- after that the `sclaude` orchestrator carries on by itself.

Then stop. Don't offer merge or deploy — I can't say yes anyway.
