Pull request #<pr> for the feature "<feature>" is open. Your job here is to get it to a mergeable state.

Feature context is in `.sclaude/local/feature/plan.md`: what we promised and why that way. Read it before agreeing to a comment that proposes changing behaviour.

The orchestrator captured the PR state as of the start of this step — checks and all comments:

<block:pr-context>

1. Handle each comment individually. Where you agree, fix it. Where you don't, explain why to me and leave the decision to me; don't argue with the reviewer in comments under your own name.

   **A thread you would leave as it is, you propose to resolve, and resolve it yourself once I say yes.** Don't change the code for it. Ask me through `AskUserQuestion`, one question per thread, in so many words: "I want to resolve this comment on GitHub: <link> — <the finding in a line>. Leaving it because <why>." The options are to resolve it (first, `(Recommended)` when it is your advice), to fix it after all, and to leave it open for me to resolve by hand. When the why does not fit in a question — a trade-off, more than one way to go — write it out in your message before the question: each option and what it means for the business and for the people who use the product (what they would see, what it costs, what risk stays), not only for the code. The question then stays short and points at that text.

   Only on my explicit yes: reply in the thread with my decision in a line, then resolve it — find its id and pass it to `resolveReviewThread`:

   ```
   gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){reviewThreads(first:100){nodes{id isResolved comments(first:1){nodes{url}}}}}}}' -F o={owner} -F r={repo} -F n=<pr> --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.comments.nodes[0].url | endswith("#discussion_r123")) | .id'
   gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -F id=<thread id>
   ```

   Do it before your next push, so the round that push starts does not count the thread as open. Anything short of a yes — no answer, "later", a question back — is not one: the thread stays open.

   **When I say I will resolve it by hand, or the call above fails, write it down.** Append one line to `.sclaude/local/feature/review-yours` — the thread's link (the snapshot gives it after each thread's author, `…/pull/<pr>#discussion_r…`; for a newer thread it is the `html_url` of its first comment in `gh api repos/{owner}/{repo}/pulls/<pr>/comments`), a tab, and my decision in a few words:

   ```
   printf '%s\t%s\n' 'https://github.com/…/pull/<pr>#discussion_r123' 'leave as it is: the fix would undo d60ca78' >> .sclaude/local/feature/review-yours
   ```

   From then on no session asks me about it again: the snapshot lists it apart, the orchestrator does not send the work back for it, and it prints the links for me to resolve. In your report, list each such thread under a heading **Resolve on GitHub yourself**, with its link and one line on what was decided — the first thing in the report after what was done, not inside "what is left open". Once one thread was put to me in three rounds running because none of this was written anywhere. The threads you resolved on my yes go into the report too, each with its link and the decision, among what was done.

   **Fix through subagents.** Give each finding — or a few that touch the same code — to a subagent (the Agent tool): the finding's text verbatim, its `path:line`, what you know about why it is right, and the brief below. It reads and edits in its own context and reports back what it changed. You read its diff, decide whether it does what the finding asks, and keep the coordination — the checks, the commit, the push — yourself. Your context is what carries the round; spending it on every file a fix had to read is what made one conversation run out over five rounds. Fix a finding yourself only when it is a line or two.

   **The brief: fix the finding and its class, not the one line it cites.** On one pull request most findings after the third round were the last fix repeated one place over: Restore guarded and Delete not, the light-theme hover pinned and the dark one not, four button variants out of eight, a function changed and its `comment on`, both manuals and its in-body comment still describing the old rule. Each of those cost a review round. So the subagent fixes:

   - the cause, where the finding points at one — a sweep that has to repeat a filter because the guard is wrong is fixed in the guard;
   - every other place in the pull request with the same pattern: search the pull request's diff (`git diff origin/main...HEAD`) and the code it touches, not only the cited line;
   - every comment, doc comment, SQL `comment on`, manual page and test label that describes the behaviour the fix changes;
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

2. If you changed code, run the checks the change calls for before pushing: `npm run typecheck`, `npm run lint`, plus whatever further checks the project's `CLAUDE.md` asks for after the kind of change you made. If you changed nothing, there's nothing to run: step 2 does not close until the full regression is green, and the code hasn't changed since.

3. Commit fixes to the same branch following the project's commit rules, and push. A review fix isn't something I asked for, so it usually needs no `Requirement:` footer — unless the comment exposed a real requirement we missed.

   When a fix changes something the pull request's description states — a mechanism, a list, a count of tests — rewrite that part of the description in the same round (`gh pr view <pr> --json body --jq .body`, edit, `gh pr edit <pr> --body-file <file>`). It was written at step 3, and the merge summary and the issue's status comment are written from it: once it said "16 cases" for the 52 the review rounds left, and the issue's status repeated it.

   A push reruns the PR checks, and a fix for a failure can break them again. Wait and look again: `gh pr checks <pr> --watch`. `--watch` returns by itself once every check has finished — that is the wait; run it in the background if it will take long, and do not write a polling loop of your own. `jq` is not installed on this machine: filter `gh` output with its own `--jq`. A background loop whose condition can never be true does not fail — it hangs, and the turn waits on it with nobody told. While a check is red the work isn't done, whatever is failing — your code, someone else's, or a flaky test. Flaky is a conclusion, not a guess: rerun (`gh run rerun <run-id> --failed`) and confirm.

4. **When the automatic review closes everything you fixed, this session's round is over.** After your push the automatic review reads the fixes, closes the threads they fixed (each with a reply "Resolved automatically: …") and may post new findings — from the fixes, or from reading the whole pull request again once the fixing looks done. When it has finished:

   - **some thread you were fixing is still open** — keep going here, however long this conversation has run: it is still yours, and this conversation knows why;
   - **a new finding is on your own fixes** — code a commit of yours in this conversation wrote or changed: a bug the fix brought in, or the fix left half done — keep going here and fix those, the same way as the others, however long this conversation has run. They are your work, and only this conversation knows what the fix was for and what was tried before it; a fresh session would read them cold and could undo what you settled. Once you push, they are threads you were fixing like the rest. Four such passes at most: when the review finds your fixes of your fixes wrong a fifth time, stop and put it to me — what keeps breaking, what you tried each time, and the ways out you see — with no marker, so the session stays open for my answer. A fresh session would not break that loop; a decision from me can. Once a round ended with "two new findings, both in my fixes — I left them, the next session takes them", and the next session started from nothing on code this one had just written;
   - **every thread you were fixing is resolved, and every new one is on code you did not touch** — stop here. Unless your report proposes something for me to decide (see the report rules below: then no marker, and I close the session), write one line to `.sclaude/local/feature/review-round`: the head commit and how many new findings are open (`echo "a1b2c3d: 4 new findings open" > .sclaude/local/feature/review-round`), give the report described at the end — what this round fixed, and how many new findings are open — and end your turn. Do not start on the new findings yourself: who takes them is the orchestrator's call, by a figure only it can see. It ends this session and looks at how full its context is: while it is light, it resumes this same conversation with the new findings, and they are then yours like the rest; once it is heavy, it records this session in the issue and opens a fresh one for them, without this conversation.
   - **every thread is resolved and nothing new is open** — the work is done; finish as below, marker included. Threads written in `.sclaude/local/feature/review-yours` count as resolved for this: they wait for my hand, not for a session.

<include:dev-server>

<block:regression>

<include:questions>

<include:friction>

**How this session ends.** You are step 4, the last one; the `sclaude` orchestrator drives the steps from outside. There are no further sessions: merge, migration promote and `vercel --prod` I do by hand, and the orchestrator reminds me of them when I exit.

The preview deploy isn't yours: the orchestrator offers it when I exit. It can do what you can't from here — the project link lives in `.vercel/` of the main repo, not in this worktree, and `vercel` run here would create a new project instead of deploying to ours.

The orchestrator runs this step with restrictions: merge, deploy, `--no-verify` and anything leading to production simply won't run here. A rejection is the step's boundary, not a failure; `git push` of fixes to the branch is allowed.

<include:report>

**When the review has closed everything and nothing new is open, `sclaude` closes this session itself.** Write the marker first — `echo done > .sclaude/local/feature/session-done` — and then the report, with no tool call after it. About thirty seconds after your turn ends the orchestrator closes the session, prints the report, and checks the pull request itself: if anything is open after all, it sends the work back — to this conversation when a thread you were fixing is still open, to a fresh one when the review posted new findings after you finished. So do not write the marker until the review has finished with your last push — `gh pr checks <pr> --watch` returns when it has: findings on your fixes are yours to take, as above. If I type anything in those thirty seconds, the closing is called off and the marker removed; write it again when you are done again.

Leave the marker out when something is left for me to decide — a red check you could not fix, a comment you disagree with that I have not answered yet. Then I have to answer you, and I close the session myself. A thread I already decided to leave, written in `.sclaude/local/feature/review-yours`, is not one of those: it counts as handled here, and the orchestrator waits for me to resolve it on GitHub.

Once the comments are handled and the PR checks are green, tell me in that one message — in your own words, but cover all of it:

- the work in this session is done — the pull request is ready to merge, and what's left open. If something didn't come together — a red check, a comment you disagree with — say exactly what's left rather than passing it off as ready;
- with the marker written, that `sclaude` closes this session itself; without it, that I should now close Claude with `/exit`;
- after that the `sclaude` orchestrator continues: it offers the preview deploy and reminds me of merge, migration promote and prod.

Then stop. Don't offer merge or deploy — I can't say yes anyway.
