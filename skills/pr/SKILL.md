---
name: pr
description: Open a pull request for the current work using GitHub flow. Use this instead of pushing to main. Runs only when opening a PR is what was asked for — by the user, or by the orchestrated step whose prompt says to run it — never on your own initiative after finishing a piece of work. The pull request is reviewed by default; the argument `no-review` labels it so the automatic review skips it, and only the user may ask for that.
model: sonnet
effort: medium
---

# pr — ship the work as a pull request

This replaces `git push` to `main`. **`main` is never committed to or pushed
directly.** It only moves when a pull request is merged, and merging is the
user's step, not yours.

Run this only when opening a pull request is the task you were handed — the user
asked for it, or the `sclaude` PR step's prompt told you to run this skill.
Finishing a piece of work is not that ask: it means committing to the feature
branch and saying that no PR is open yet. Never open one unasked.

## The argument: `no-review`

**Invoked with no argument, the pull request is reviewed.** That is the default
and it stays the default: the automatic review is what catches what the author
stopped being able to see, and an unreviewed PR costs nothing until the day it
does.

`/pr no-review` opens the same pull request with the `no-review` label on it, and
the repository's review workflow skips itself for as long as that label is there.
Everything else in this skill is unchanged — the same branch, the same commits,
the same checks, the same body. Only the reading is skipped.

**It is the user's call, never yours.** Open a PR without review only when the
argument said so, or when the user asked in the same breath. "This change looks
safe to me" is not that; judging a diff safe is the thing the review exists to
second-guess, and it is precisely the diff you are most sure about that you are
worst placed to judge.

Say plainly in your report which of the two you did.

Two things to know when you use it:

- **The label must exist in the repository.** `gh pr create --label` fails
  outright on an unknown label, and the failure comes after the push — so the
  branch is up and the PR is not. If it is missing, create it once
  (`gh label create no-review --description "Skip the automatic Claude code
  review on this pull request" --color d4c5f9`) and say that you did.
- **Removing the label later does not start a review.** The workflow triggers on
  commits, not on labels. To get a review after the fact: push to the branch, or
  dispatch the review workflow from `main` with the PR number.

**This is for product repositories, not for tooling.** sclaude's own checkout — the
user's own scripts and skills — is committed and pushed straight to `main` every
time, without a branch, a PR, or asking. A change to this very skill ships that
way.

## GitHub flow

### 1. Account for everything uncommitted — before anything else

The working tree is the one thing that never survives being guessed at. A PR
assembled over a dirty tree either swallows changes the user did not mean to
ship, or leaves behind changes they thought they had shipped. So this comes
first, before the fetch, before the branch, before reading the diff for a name.

```bash
git status --porcelain=v1 --untracked-files=all
git stash list
```

If that output is empty, say so in one line and go to step 2.

If it is not empty, **stop and ask the user, one question per group of changes,
and wait for the answer.** Do not decide yourself, and do not fold the question
into a later step: no `git add`, no commit, no branch switch, no push until
every path is accounted for.

Read the changes before asking — `git diff`, `git diff --staged`, and `cat` for
anything untracked — and present them grouped by intent, not file by file:

- **part of this work** → it goes into the PR, in the commit it belongs to
  (step 5 says how to group them);
- **unrelated but wanted** → it stays uncommitted, and the PR must not carry it;
  say plainly that it will still be sitting there afterwards;
- **generated or accidental** → name it as such and ask whether to discard it —
  never discard anything on your own judgement, and never `git checkout --`,
  `git restore`, `git clean` or `git stash` without the user having said so
  about that specific path.

Three cases worth naming, because they look like noise and are not:

- **`AGENTS.md` rewritten by `next dev`** — the project's own instructions say
  removing it from the diff only re-creates the change, and committing it with
  the work keeps the tree clean. Still say you are doing it.
- **A stash that is not empty** — `git stash list` output is uncommitted work
  too. Ask whether it is meant to be in this PR rather than leaving it silently
  behind.
- **`.sclaude/local/feature/` under the `sclaude` orchestrator** — the working directory of
  the feature being developed: `plan.md`, and the orchestrator's own state. It
  belongs in the project's `.gitignore` and must never be committed, so it is
  not a question to bring to the user. Two things are worth checking rather
  than assuming: that no commit on the branch carries it
  (`git log origin/main..HEAD --name-only | grep .sclaude/local/feature`), and that it is
  ignored at all. Do not delete it — it outlives this step and goes away with
  the worktree.

The point is that the user consciously chooses, per change, whether it ships.
"The tree was dirty so I committed it all" and "the tree was dirty so I ignored
it" are both this step failing.

### 2. Check the ground

```bash
git status --short --branch
git fetch origin
gh auth status
```

Know what the change actually is before naming it: `git diff origin/main...HEAD`
and `git diff` for anything the previous step decided belongs here.

**Read `git status --short --branch` before trusting any branch name said
earlier in the conversation, including your own.** It prints the branch HEAD
is actually on and what it tracks — `## <branch>...<upstream> [ahead N,
behind M]` — which is the only source of truth here. A session that thinks it
is on `chore/foo` because it created that branch minutes ago, but whose HEAD
has since moved (a `switch` without `-c`, a detached checkout from an agent or
a worktree step, a name reused from an earlier turn) commits onto whatever
branch HEAD actually points at instead — silently, because `git commit` never
asks which branch it is committing to.

### 3. Get on a branch

**If the work already sits on its own branch, this step is a check, not a
move.** That is the normal case under the `sclaude` orchestrator, which branches
from a freshly fetched `origin/main` before development starts. Confirm the
branch is not `main` and that it is still based on an up-to-date `origin/main`
(`git fetch origin`, then `git log origin/main..HEAD` and
`git log HEAD..origin/main`), and go to step 4. A branch that has fallen behind
is worth saying out loud; it is the user's call whether to rebase. Under
`sclaude` that call is already made before the session opens: it offers the
person a merge of main, remembers a "no", and does not count commits that only
add deferred entries (a `deferred/` folder under `.sclaude/`) — often its own,
sent to main from this very branch. Say how far behind the branch is, if at
all, and do not ask again.

**Confirm the branch is not someone else's open pull request before adding to
it.** `git log origin/main..HEAD --format='%s'` printing commits you did not
just write is the sign — check it even when step 3 was "already on its own
branch" and looked fine. Cross-check with
`gh pr list --state open --json number,title,headRefName` for the branch
name: if it already has an open PR whose title and commits are about
something else, HEAD landed on the wrong branch, not a new commit on the
right one. Stop and tell the user rather than pushing — do not silently
retarget onto a fresh branch and hope the stray commit on the other one goes
unnoticed; say plainly that a commit reached the wrong branch, and ask
whether to force-push that branch back to its own tip (the safe fix: the
commit's content is not lost, it lives in your later cherry-pick) or to leave
it for them to sort out. Never force-push a branch backing someone else's
open PR without asking first — it rewrites history GitHub has already shown
them.

Otherwise, branch off an up-to-date `origin/main`, named for the change:
`feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`, `refactor/<slug>`.

If the work is already sitting as local commits on `main` — the old habit — move
them across and put `main` back where the remote has it:

```bash
git branch feat/<slug>
git reset --hard origin/main
git switch feat/<slug>
```

Never push a `main` that has drifted ahead of the remote.

### 4. Update the manuals — this is the moment

The manuals are **not** written during development; they are written here, once,
after the feature is approved. Rewriting them while the feature is still moving
means writing the same text twice.

When a `.sclaude/local/feature/plan.md` is present, that is what the manual is written from:
it states what was promised to the person using the product, in their terms,
agreed before any code was written. Reconstructing the same thing from the diff
gets you the implementation instead.

If the change is user-visible, update the manuals the project declares. Their
paths are the `manuals` list in `.sclaude/config.json` at the repository root, each
with a note on what it is for — read them from there rather than assuming a
layout, e.g. `python3 -c 'import json; [print(m["path"], "—", m.get("what","")) for m in json.load(open(".sclaude/config.json")).get("manuals", [])]'`.
A project with no `manuals` has none to update; say so in your report.
Usually there are two:

- the **user manual** says what a person can do and what will happen;
- the **technical manual** covers the same ground in full — where each rule is
  enforced, status codes, matrices, tiers.

Judge the split by audience: needed to *use* the feature → both; explains
only *why* or *where enforced* → the technical one is enough. Never restate a
limit as a literal — read the value from the module the feature itself reads it
from.

Commit this separately: `docs(help): …`.

If the change is not user-visible, say so explicitly in your report and leave the
manuals alone.

### 5. Commit

A commit message has three parts, in this order. The first is the spec, the
second is the customer's, the third is yours.

```
<type>[(scope)]: <description>      ← Conventional Commits

<body>                              ← what the customer asked for, then your own notes

Requirement: <one requirement>      ← footers, one per requirement
Requirement: <one requirement>
Co-Authored-By: …
```

#### 1. The subject — [Conventional Commits](https://www.conventionalcommits.org/)

- **`<type>` is mandatory** — there is no such thing as a bare summary line.
  `feat` for a new feature, `fix` for a bug fix; also `docs`, `refactor`, `perf`,
  `test`, `build`, `ci`, `chore`.
- **scope** is optional, a noun naming a section of the codebase, in parentheses.
- **description** follows `: ` immediately — imperative mood, lowercase, no
  trailing period.
- **body**, if any, starts one blank line after the description.
- **footers**, if any, start one blank line after the body. A footer token uses
  `-` for spaces (`Co-Authored-By:`, `Reviewed-by:`).
- a **breaking change** gets `!` before the colon (`feat(api)!: …`), or a
  `BREAKING CHANGE: …` footer — that token is the one thing that must be
  uppercase.

#### 2. The requirements — what the customer asked for

**Every commit that exists because the user asked for something carries one
`Requirement:` footer per thing they asked for.** English, one line each, in the
same register the PR will use: a requirement or an observable behaviour, no
implementation detail, phrased so somebody could test it.

```
Requirement: A pull request is opened only when explicitly asked for.
Requirement: Merging and deploying stay the customer's own steps.
```

Write them at the moment you make the change, while you still know which of their
sentences this commit answers. This is the whole point of the arrangement: at the
`pr` step these footers are collected instead of the conversation being combed
through from the start, and a requirement recorded next to the diff that
satisfies it cannot drift away from it.

Rules, same as the PR section they feed:

- **One line, one requirement.** Split a compound ask into two footers.
- **Requirements, not implementation.** No file, function, table or column names,
  no policy or migration detail, no library choices.
- **Theirs, not yours.** What you decided alone, or what follows from the
  codebase, is not a requirement — it goes in the body instead.
- **Latest wins.** If they changed their mind after an earlier commit, the new
  commit's footer states the final shape; the old commit keeps its history.

A commit nobody asked for — a refactor you judged necessary, a typo — carries no
`Requirement:` footer at all. That is normal, and better than inventing one.

#### Who and where — the authorship footers

Every commit you write ends with two more footers, after the `Requirement:` ones:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CLGjeqxyJyrW5RpBepHADE
```

- **`Co-Authored-By:` names the model that actually wrote the commit** — `Claude
  Opus 5`, `Claude Sonnet 5`, whichever is running — not a generic "Claude". The
  branch usually carries commits from more than one, and which one wrote a
  particular diff is the sort of thing nobody can reconstruct afterwards.
- **`Claude-Session:` is the URL of the session it was written in.** It is what
  turns a commit back into the conversation that produced it: what was asked,
  what was rejected, what the body had no room for. A commit body says why the
  code is shaped this way; the session says how it got there.

Both values come from the harness — the exact strings are in your system prompt,
already assembled. Copy them; never invent a session id, and never carry one over
from an older commit you happened to read. A commit written in a session that
gives you neither simply goes without.

#### 3. The body — yours

Free prose, before the footers. Why the change is shaped this way, what you
considered and rejected, what a reviewer would otherwise have to ask. This is
where the reasoning goes, and it is the part that usually reads best when it is
written at the time rather than reconstructed.

#### Checking the branch

Group the tree into coherent commits rather than one heap.

**Check every commit the PR will carry, not just the ones you wrote.** A branch
often picks up commits from elsewhere — work that was sitting on local `main`,
say. Run `git log origin/main..HEAD --format='%s'` and confirm each line parses
as `type(scope): description`. Rewrite any that does not (`git rebase -i`) —
these commits have not been merged, so the message is still yours to fix. Say in
your report that you did.

An inherited commit will have no `Requirement:` footers. Add them in the same
rebase if you know what was asked for; leave them out if you do not, rather than
guessing at somebody else's conversation.

### 6. Run the checks

Before opening the PR, run the project's own type check and lint. Their
commands are the project's, not this skill's: `commands.typecheck` and
`commands.lint` in `.sclaude/config.json` where the project has one, otherwise
the matching scripts in its `package.json` (for a Node project usually
`npm run typecheck` and `npm run lint`) or what its `CLAUDE.md` names. Run the
ones that exist; a project with neither has nothing to run here.

And whatever further checks the project's `CLAUDE.md` asks for after the kind
of change you made — they are the project's, not this skill's.

A project's own pre-push hook may run more checks on push by itself. Do not
bypass it with `--no-verify`.

Report failures rather than working around them.

### 7. Push and open the PR

```bash
git push -u origin <branch>
gh pr create --base main --title "<title>" --body-file <file>
```

With the `no-review` argument, and only then, the label goes on in the same
command — not in a `gh pr edit` afterwards, which leaves a window in which the
PR exists unlabelled and the review has already started:

```bash
gh pr create --base main --title "<title>" --body-file <file> --label no-review
```

Never `--force`. Never `gh pr merge`.

**If the PR closes an issue that sits in a milestone, put the PR in the same
one.** The issue and its PR are one piece of work, and a milestone that holds
only half of it under-reports what was done. `Closes #N` does not do this — it
links the two and closes the issue on merge, but carries no fields across.

Read the milestone from the issue rather than picking one, and only set it when
the PR has none of its own:

```bash
gh issue view <issue> --json milestone --jq '.milestone.title // ""'
gh pr edit <number> --milestone "<title>"
```

A milestone already on the PR stays — somebody put it there. Say so if it
differs from the issue's, and leave it to them.

Under the `sclaude` orchestrator this is done for you, from the feature's issue —
do not do it by hand there.

## What the PR says

**Title** — Conventional Commits, the same shape as step 5 and matching the
primary commit: `feat(profile): let a person close their profile`.

**Body** — English, in this order:

```markdown
## Summary

<What the change does, two to five sentences, in the register of the commit
message. What it is, and what it changes for someone using the product.>

## Requested by the customer (for QA)

- <requirement>
- <requirement>

## How to verify

<How somebody checks this, end to end.>

## Notes

<Anything a reviewer would otherwise have to ask about. Omit when there is
nothing.>

## Sessions

- <model> — <session URL>

Closes #<issue>
```

`Closes #N` goes last, on its own line, and only when the branch closes a
GitHub issue — GitHub then links the two and closes the issue on merge. Omit
the line entirely when there is no issue; a wrong number closes someone else's
work.

### Summary

What changed and why, in prose. Say plainly when a change is not user-visible.

### Requested by the customer (for QA)

This section is the point of this skill, and it is **written for the QA team**:
what the user asked for, as requirements and expected behaviour somebody can test
against.

**Start from the commits, not from the conversation.** Each commit already
carries its `Requirement:` footers, written when the change was made:

```bash
git log origin/main..HEAD --format='%(trailers:key=Requirement,valueonly)'
```

That output is the draft. Then edit it as a list:

- **De-duplicate and merge.** Two commits answering the same ask produce two
  identical or overlapping lines; keep one.
- **Latest wins.** Where a later commit's footer supersedes an earlier one — they
  changed their mind mid-branch — keep only the final shape.
- **Order by what a tester would do first**, not by commit order.
- **Scoped to this pull request.** The footers are already scoped, since they
  ride with their diff. Check anyway when the branch inherited commits or the
  work spanned repositories: a requirement this diff cannot be tested against
  does not belong, however clearly it was asked for. If that leaves the list
  nearly empty, the list is nearly empty.
- **Fill the gaps.** If a commit lacks footers it should have had, add the
  requirement here — and note that the commit was missing it, so the habit
  corrects itself.

The rules the footers were written under still hold for the assembled list:
requirements not implementation, theirs not yours, testable. If the user asked
for nothing beyond "fix this", say that plainly rather than inventing a list.

### How to verify

The steps somebody actually takes: what to click or run, and what they should
see. Name the checks you ran and their result (the type check, the lint, and any
further check the change called for, each by its command), and say when a check was *not*
needed and why. For a change that is not user-visible, say so here too.

### Notes

Only when there is something. What belongs here:

- **anything unusual about the branch** — commits inherited from elsewhere,
  messages you rewrote, a second unrelated concern that rode along;
- **known limitations, follow-ups, or things deliberately left out**;
- **anything that needs doing at merge time** — a migration to promote, an
  environment variable to set, a deploy that must follow.

Leave the section out entirely when none of that applies.

### Sessions

The conversations this branch was written in, one line each, so a reviewer
reading the diff can reach what was said while it was being made. Collect them
from the commits rather than from memory — the branch may carry work from several
sessions, and one of them may not be yours:

```bash
git log origin/main..HEAD \
  --format='%(trailers:key=Co-Authored-By,valueonly,separator=%x2C)%x09%(trailers:key=Claude-Session,valueonly,separator=%x2C)' \
  | grep . | sort -u
```

`separator=` is not decoration: without it `valueonly` puts each trailer on its
own line, and the model and the URL of one commit end up on separate rows. The
`grep .` drops the merge and third-party commits that carry neither.

De-duplicate by URL: a session that wrote six commits gets one line, named for
its model.

```markdown
## Sessions

- Claude Opus 5 — https://claude.ai/code/session_01CLGjeqxyJyrW5RpBepHADE
- Claude Sonnet 5 — https://claude.ai/code/session_01GBqMPAVHhjhEUirTmMY3wq
```

Leave the section out when no commit on the branch carries a session URL. Do not
fill it in from the conversation you are in now — the point is which session
wrote *these commits*, and a link that is merely plausible is worse than an
absent one.

## After it exists

Print the PR URL and stop. Do **not** merge it, and do **not** deploy — both are
the user's steps.

## After it is merged

**Under the `sclaude` orchestrator this is not your step at all.** `sclaude done
<feature>` checks the merge with GitHub, then removes the worktree and both
branches, asking before each. Say the branch is ready for it and stop.

Everywhere else, the old order holds. Merging is the user's step, so you learn
it happened by being told, or by looking:

```bash
gh pr view <number> --json state,mergedAt,headRefName
```

**Once a PR is merged, ask the user whether to delete its branch** — both the
remote one and the local one. Ask; never delete unprompted. A merged branch is
the one case where deleting is ordinary housekeeping rather than a loss, but it
is still theirs to decide: they may be holding it for a follow-up, a cherry-pick,
or a deploy that has not happened yet.

Ask only about a branch whose PR is actually merged. A closed-unmerged PR keeps
its branch — that is the only place the work still exists.

If they say yes:

```bash
git switch main
git pull
git branch -d <branch>          # -d, never -D: it refuses if the work is not merged
git push origin --delete <branch>
```

`git branch -d` is the check, not a formality — if it refuses, the branch holds
commits that never reached `main`, and that is a question to bring back to the
user rather than an obstacle to force past with `-D`.

If they say no, leave both branches alone and say nothing further about it.
