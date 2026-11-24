---
name: sreview
description: Run iterations of code review and fixing on the current branch until the review finds nothing substantive, stopping every N iterations (default 5) to ask whether to go on. Each review is a fresh subagent; questions to the user are asked per class of finding, and the answers are kept as policies that settle similar findings now and in later runs. Works in any repository; in a project run by sclaude it follows sclaude's review settings and rules. Runs only when the user invokes /sreview, when /scontrib (invoked by the user) runs it over a contributor's pull request, or when a sclaude session's instructions tell it to review the change it made in sclaude's workshop.
argument-hint: "[iterations before asking, default 5]"
---

# sreview — review and fix, round after round

`/sreview [N]` — N is how many iterations run before you stop and ask whether
to go on; 5 when not given. One iteration is: a fresh review, triage, questions,
fixes, checks, one commit.

You are the **orchestrator**. You do not review, and you fix only what is a line
or two. You keep the decisions, the checks, the commits and the count. Talk to
the user in the language they write in.

## 0. Before the first iteration

1. **Branch.** If HEAD is the default branch (`main`, `master`), stop and ask:
   review fixes are never committed to it.
2. **Uncommitted work.** If the tree is dirty, ask whether to commit it first,
   stash it, or stop — never fold someone's unfinished work into a review commit.
3. **State directory**, shared by every worktree of the repository and outside
   git: `S="$(git rev-parse --path-format=absolute --git-common-dir)/sreview"`.
   - `$S/policies.md` — the project's stances and the user's policies (below).
   - `$S/branches/<branch>.md` — this branch's log: each iteration's findings and
     what became of each (fixed in `<sha>`, declined by policy P-n, declined as
     not a bug, waiting). Create it on first use; on a later run, read it — it is
     how the reviewer knows what was settled and how you see a reversal.
4. **Stances.** If `policies.md` has no `## Stances` section, ask before the
   first review, in one `AskUserQuestion`, the questions whose answers change
   most decisions: how risky are breaking changes, migrations and downtime right
   now; does code cleanliness and size outrank compatibility shims; anything the
   review must never touch. Write the answers as stances. Read them on every
   run; they decide trade-offs before any question is asked.
5. **Mode** — see below. Say in one line which mode you are in and why.
6. **Scope: this session's work only.** Parallel sessions may share the branch
   or the checkout; two reviews of the same code, or two sessions fixing it,
   race and undo each other. So the scope is what the session that invoked
   `/sreview` produced:
   - the commits on the branch carrying this session's `Claude-Session:`
     trailer (its URL is in the commit attribution this session was given;
     `git log --format='%H %(trailers:key=Claude-Session,valueonly)'`);
   - the uncommitted changes to files this session edited, and only those.

   Under `/scontrib` the scope is the whole pull request instead —
   `git diff <base>...HEAD`, the contributor's commits and ours — as that
   skill says; nothing of it is another session's.

   Say the scope in a line (commits, files). If the session cannot tell its own
   work apart — no trailer, nothing it remembers editing — ask the user for the
   scope rather than taking the whole branch.

## Other sessions' code

A finding on code this session did not write is not fixed here — except an
outside contributor's pull request taken in with `/scontrib`, whose code is
this session's to fix and whose scope is the whole pull request. Find its owner:
`git blame` the lines → the commit → its `Claude-Session:` trailer. If that
session is active (`ListAgents`), send it the finding verbatim with
`path:line` and the failure scenario (`SendMessage`) and leave it to it; say
so in the report. If it is not active, or has no trailer, list the finding in
the report under **Not ours**, with the commit, for the user. Fix it here only
when your own fix cannot be made without it — and then say which and why.

Committing: stage by path the files of this session's fixes, never
`git add -A`; if the branch moved under you since the iteration began (another
session committed), rebase nothing and stop to tell the user.

## Modes

**sclaude project** — `.sclaude/config.json` exists. sclaude's files are in the
checkout this skill is installed from, wherever that is:
`I="$(cd "$(readlink -f ~/.claude/skills/sreview)/../.." && pwd)"`. Take:
- the check commands: `commands` (`typecheck`, `lint`, and whatever the
  project's `CLAUDE.md` asks for after the kind of change made);
- `review`: `local` / `github` / `github-local` / `off` — `github-local` is
  `github` until the feature's review moved to this machine (the mark
  `.sclaude/local/feature/review-fallback` in its tree), and `local` after;
- the rules of sclaude's review step, `$I/sclaude/prompts/review.md`:
  read its step 1 and follow it — the fix brief, "a fix that would undo an earlier
  one is not a fix", findings on the review workflow file or on deferred files,
  the `Left as it is, at the author's decision:` reply. Where it speaks of one
  session per round and markers for the orchestrator, this skill replaces that:
  you run the rounds yourself.
- the reviewer's model and level: `LOCAL_REVIEW_MODEL` / `LOCAL_REVIEW_LEVEL` in
  `$I/sclaude/lib/review/local_review.sh` (today opus, medium).

With a pull request open for the branch (`gh pr view --json number`) and
`review` not `off`, this is **PR mode**: findings live as threads on the pull
request, as sclaude keeps them.
- `review: local` — the reviewer is your subagent (step 1). Before it runs, get
  what is already on the pull request:
  `python3 $I/sclaude/lib/review/local_review.py prompt <cwd> <pr> <owner/repo> <journal>`
  and add its output to the reviewer's scope verbatim. After it answers, save
  the answer and post it:
  `python3 $I/sclaude/lib/review/local_review.py record <cwd> <pr> <owner/repo> <answer> <base> <head> <seconds> <journal>`
  — it posts new threads and resolves the ones the reviewer marked `RESOLVED`.
  The journal is `.sclaude/local/feature/review-rounds.jsonl` when that
  directory exists (so sclaude counts these rounds), else `$S/branches/<branch>.rounds.jsonl`.
  `record` posts on the head the pull request carries: while HEAD is ahead of
  it (not pushed), keep the findings in the branch log and post them on the
  first iteration whose head the PR carries.
- `review: github` — the review workflow is the reviewer, and it reads only
  what was pushed: when the iteration's commit is on the PR, wait in the
  background for the review workflow's run on that head to finish
  (`gh run list --commit <sha> --json databaseId,workflowName,status`, then
  `gh run watch <id>` on the review's run; `sclaude checks <pr>` waits only
  for the other checks, never for the review) and take the open threads as
  the iteration's findings. No review run on the head within half an hour,
  or one that failed: the push was not reviewed — stop and tell the user.
  When the commit is not on the PR, review with your own subagent as in
  local mode.
- A thread you decline is answered and resolved as `review.md` describes. A
  decline that follows from a policy needs no new question: cite the policy in
  the reply (`Left as it is, at the author's decision: <policy in a line>`) and
  resolve it. Only a decline no policy covers goes to the user, as a class.

**Anything else** — no sclaude, no pull request, or `review: off`: **local mode**.
Findings live only in the branch log. Checks: the
project's `CLAUDE.md`, else the `typecheck` / `lint` / `test` scripts it has.

## 1. Review — a fresh subagent every iteration

Spawn a new subagent (Agent tool; the sclaude model when there is one) that has
not seen your fixes. It invokes the `code-review` skill at the level above with
`--max-findings all` (without it the skill stops at its default cap of 10 and the
rest of the scope goes unread), and changes no file and posts nothing. Its scope,
in plain words:

- iteration 1: this session's work (step 0.6) — its commits by SHA and its
  uncommitted files, or under `/scontrib` the whole pull request; the rest of
  the branch only as context, not to report on;
- later iterations: this session's commits since the last reviewed head —
  your fixes are where new bugs come from — **plus whatever the previous review
  may have left unread** (see "A review that may have stopped early" below);
- **what was settled**, verbatim, so it does not raise it again: every policy in
  `policies.md` (stances included), and from the branch log every finding
  declined, with its reason, and every finding fixed. Tell it: a finding that
  restates a declined one or contradicts a policy is not reported, reworded or
  on another line, unless the code it rests on changed so the reason no longer
  holds — then it says which change;
- **what describes the code**: when the repository's `CLAUDE.md` names
  documents that follow a change — a README, docs, a diagram or map built from
  a model — it reads them against the change, and a place that no longer
  describes the code is a finding like any other.

It answers in sclaude's format, so PR mode can post it unchanged:

```
### <path>:<line> — [<severity>] <the finding in one line>
<the failure scenario: concrete inputs or state, and the wrong result>
```

`<severity>` is the mark the `code-review` skill gave the finding —
`important`, `pre-existing` (a bug that was there before the change) or `nit` —
and `important` when it gave none. In PR mode a `nit` or `pre-existing` one is
posted as a minor finding, marked so for whoever weighs it.

then `RESOLVED: <id> — <how>` for each earlier open finding the code no longer
has (PR mode), then `COVERED: <the files of the scope it read in full>`, then
`FINDINGS: <n>`, and last the line `REVIEW: complete` —
written only once the `code-review` skill and every agent it started have
finished. Tell it so: it answers once, at the end, never with an interim list.

**Take the answer only when it is whole.** A reviewer can hand back before its
skill is done — "FINDINGS: 0" first, the real list after. So:

- wait for the subagent's task to be reported finished, not only for its
  message, and take its last report;
- an answer without `REVIEW: complete` is not an answer: ask the subagent to
  finish (`SendMessage`), or spawn the review again — never triage it, never
  call the round clean on it, never write the mark of a finished run on it;
- a report that comes after you acted on an earlier one replaces it: its
  findings join the iteration, and a mark already written comes off.

In PR mode `local_review.py record` refuses an answer without that line, as
it does sclaude's own headless review.

**A review that may have stopped early.** A whole answer can still be a partial
review: the reviewer or its skill stops at a cap and never reads the rest. Treat
the round as possibly truncated when it returned **10 or more findings** (the
`code-review` default cap, also when the flag was passed — it may not have been
honoured), when its `COVERED` line misses files of the scope, or when it has no
`COVERED` line. Then:

- the files of the scope it did not cover (all of the scope, without a `COVERED`
  line) go into the next iteration's scope next to your fixes, named as such, so
  the next reviewer reads them first;
- the round is never the last one: step 6 does not stop on it, and no mark of a
  finished run is written on it;
- say in the branch log and the report which files were carried over and why.

When the user says a review stopped short, run the next reviewer on the unread
part at once, without waiting for the iteration to end.

## 2. Triage — yours, not the subagent's

Read the code behind every finding before deciding; a finding is a claim.
The reviewer's mark is where you start, not the verdict: an `important` one is a
candidate for **substantive**, a `nit` for **nit**; a `pre-existing` bug is not
this change's — fix it when the fix is small and safe in code the change
touches, otherwise report it under **Not ours** for its own issue. Sort each
one:

- **not a bug** — the scenario cannot happen. Decline with the reason.
- **covered by a policy or stance** — apply it; no question.
- **would undo an earlier fix** (branch log, resolved threads) — never applied
  silently: it becomes a question, with both sides.
- **substantive** — a bug (one both unlikely and small in its consequences
  is a nit), something a user of the product would see, or
  something that would mislead whoever maintains the code next (a comment that
  says other than the code does, a wrong account of a function's dependencies
  or of the data model): fix.
- **nit** — grammar in a comment, a case both unlikely and small in its
  consequences, and the like: fix it when the fix leaves the code smaller or
  the same size; otherwise it goes to the iteration's question as part of a
  class.
- **disputed** — you would leave it, or the fix has a real trade-off: a question.

## 3. Questions — about the class, not the instance

All questions of an iteration go together, after triage, in `AskUserQuestion`
(up to four per call; more classes, more calls). Everything undisputed is being
fixed meanwhile — a question does not hold the iteration up.

Before asking, group the findings into classes and ask about the class: not
"may I leave the null check out at `a.ts:40`?" but "a guard for a state the
database already forbids — add it everywhere, or trust the constraint?". Name
the instances under it in your message, with `path:line`, and say what each
answer means for the product and its users, not only for the code. Options are
policies, phrased so they decide future cases too; your recommendation first,
marked `(Recommended)`.

Look one step wider than the findings in hand: if the class plainly has
neighbours (the same pattern elsewhere in the branch, the obvious next variant),
ask so the answer covers them too.

**Every answer is written down — in the narrowest place that holds it.** A
policy in `$S/policies.md` is read by every later review of the repository, so
it goes there only when it applies across it: to many files or parts, and to
work not yet written. An answer about one function, file, feature or prompt
goes beside what it governs instead — a comment at that code saying the rule
and why, or the doc or prompt of that part — where the next change to it reads
it, and the branch log names where it went. When unsure, the specific place:
a rule that turns out to be wider is moved up later more easily than a global
one nobody needs is noticed.

A policy for `$S/policies.md`:

```
### P-<n>: <the principle in one line>
- Why: <the user's reason, in their words where you have them>
- Applies to: <how to recognise a case>; not to: <the boundary, if the answer set one>
- Examples: <path:line — finding>, …
- Decided: <YYYY-MM-DD>, <branch>
```

Then apply it, wherever it was written, at once to every finding of this
iteration it covers. A later answer that contradicts a rule replaces it — edit
it where it stands, don't stack a second one.

## 4. Fix — through subagents where it pays

Give a subagent (Agent tool) a group of findings when the fix is more than a
line or two, or the class needs sweeping: the findings verbatim with
`path:line`, why they are right, the policies that bear on them, and this brief:

- fix the cause where the finding points at one, not the symptom;
- fix every other place in the branch's diff with the same pattern;
- update every comment, doc, schema description, manual and test label that
  describes the behaviour changed;
- pick the fix that leaves the least code; a new helper, cache or abstraction
  is new surface for the next round to read — and the stances say whether
  breaking, migrating or deleting is preferred over keeping compatibility;
- nothing that is not about the findings; report every place touched.

Subagents run in parallel only on disjoint files. Read each one's diff: does it
do what the finding asks, and no more? Fix one-liners yourself.

## 5. Check and commit

Run the checks of the mode. Red is not done: fix it, or, if the failure predates
the branch, say so with the output. Then one commit for the iteration, following
the project's commit rules (`CLAUDE.md`, memory), subject like
`fix: review iteration <k> — <what, in a few words>`. PR mode: answer and
resolve the declined threads.

**Pushing is outside this skill.** Push or not as the project's own rules say
(`CLAUDE.md`, memory, sclaude's step); where they say nothing, do not push.

Append the iteration to the branch log: findings, what became of each, the
commit, policies added.

## 6. Go on, or stop

- **Never stop on a possibly truncated round** (10+ findings, or files of the
  scope left out of `COVERED`): run the next iteration with the unread files.
- **Stop by itself** when an iteration's review found nothing substantive (only
  nits, or nothing) and everything it found is handled — after one more step,
  once a run: **simplify**. Run the `simplify` skill (`/simplify`) over this
  session's work (step 0.6's commits since the run began, and what is not
  committed), keep what it changes only where behaviour stays as it is, run the
  checks and commit it as an iteration of its own (`refactor: simplify after
  review`). `code-review` looks for bugs and leaves cleaning to `/simplify`.
  When it changed anything, one more fresh review iteration reads that commit
  alone, and the run stops after it by the same rule, without a second
  simplify. The mark of a finished run then names the head after it.
- **Ask** every N iterations: "N iterations done: <found / fixed / declined per
  iteration>. Go on for N more?" — options: go on, stop. A round that keeps
  finding the same class (third time) is said in that question, with what was
  tried; a decision from the user breaks that loop, another iteration does not.
- A question with no answer is not a yes: nothing it covers is declined.

## Report

**The mark of a finished run.** When the run stopped by itself (step 6: the
last review found nothing substantive and everything it found is handled), or
the user answered "stop" to step 6's question — their decision that the
review has gone far enough — write the head it finished on — the full SHA,
`git rev-parse HEAD` — as the only line of `$S/branches/<branch>.reviewed`,
making its folder if needed, and say in the branch log which of the two it
was. A run cut off any other way (interrupted, a question left unanswered)
writes nothing, and removes a mark left there from before. sclaude reads it before it publishes a change made in its workshop
(`sclaude core-ready`): no mark at the head, nothing goes out.

When it stops: iterations run, and per iteration what was found, fixed and
declined; the policies added this run, each in a line; commits;
what is left open and why; findings handed to other sessions, and **Not ours**;
in PR mode, threads the user has to resolve by hand,
with links. Do not open a pull request, merge or deploy — those are other steps.
