The feature "<feature>" has been through the whole cycle, and I've already answered all the deployment questions. Your job is to record the outcome in issue **#<issue>** and in all of its parents, so the state of an epic is visible at a glance without walking its children one by one — and, where the product no longer does what an issue's description says, how it actually behaves.

This is the last session for this feature, and there's no code in it: the worktree was deleted along with the branch, and you're in the main repository. All you do is write at most one comment per issue via `gh` — never the issue's description. You may read code to check what the product does (see **Current behaviour** below), but you change nothing in the repository.

## What actually happened

<block:deploy-outcome>

Labels the orchestrator already applied across the chain: <labels>

It applies them because there's nothing to decide: a preview on hosting whose suite passed means `deployed-preview`, and production means `deployed-prod` on top.

Two of them work differently, and it changes what you write. `deployed-preview` was withheld when the preview's own regression came back red — the fixing session pushes again, so the label would name a commit already on its way out. `deployed-prod` is **not** withheld that way: production really is live, which is all that label claims. A red production instead carries `prod-regression-red`, and a red preview `preview-regression-red`; those come off by themselves when the stage next passes, so don't describe them as permanent.

So: a red stage is never something the labels alone tell a reader, and it is always something your words must. "Production is live and broken" is exactly what the reader of an epic needs, and exactly what no label says on its own.

The commits that are on hosting: <deploy-shas>

When the feature gets a comment (see **When the issue already says it** below), name the production one in it — "In production as of `a3f19c2`" — and the preview one when there was no prod deploy. One short sha, not a list of commits: the pull request already holds those, and the point is that somebody can check later which commit was live. Skip it entirely when the value above is "not recorded", and never put a sha in a parent's comment — an epic is read for where the epic stands.

Your job is the words. Don't add or remove labels yourself.

## The issue chain

The orchestrator walked it bottom-up and read each issue for you — here it is in full, as of the start of this session:

<block:issue-chain>

## What to write

Every issue in the chain may get a **Current status** comment: a short answer to "what's the state of this right now" — unless the issue already gives that answer without it. Write it in English, as the rest of the issue is.

The comment differs by level, and that's the main thing to understand:

- **The feature itself** (level 0) — what was done and where it is: in production, on preview, awaiting merge. Two or three sentences. Don't retell the plan or list commits: both are already in the pull request, and this comment exists precisely so nobody has to open it.
- **Parent and above** — not about the feature, but about itself: how many children are closed, what reached production, what's left. That's the whole point. Mention the closed feature in one line, but don't make it the content of the comment: in a month the reader cares about the epic, not which of ten issues closed last.

**Write what happened, not what was planned.** No production deploy — say so: the work is on preview and awaiting merge. The temptation to write "deployed" is strong because the cycle did finish, but a status you can't trust is worse than no status: people will go check behind it, every time.

**Don't rewrite an existing comment from scratch.** Read what's there: replace what's stale, keep what's right. The previous one was written by a session like yours for a different feature, or corrected by me — and it didn't stop being true because one more issue closed.

**A status in the description stays where it is.** A description may hold a `Current status` of its own — a human's paragraph, or a `<!-- sclaude:status -->` block from before the status moved to comments. Don't touch it; take what's still true from it into your comment.

**Don't invent progress you didn't see.** Take the numbers about children from the snapshot above ("9 of 10 closed"), not from your head. If it's unclear how some child ended, say so in a line instead of filling it in.

### When the issue already says it

A reader who opens an issue sees, before any comment: whether it is open or closed, its labels, its sub-issues with GitHub's "N of M" progress, and in the timeline the pull request that closed it. The header line of each issue in the snapshot above — state, labels, sub-issues — is that view. A status that only repeats it is noise: one more comment to read in order to learn nothing. So write none when everything it would say is already there. Two common cases:

- **The feature**, closed, labelled `deployed-prod`, no red label, its criteria ticked or absent: "it's in production" is what the closed issue and the label already say. The production sha alone is no reason for a comment — the pull request in the timeline leads to the merged commits.
- **A parent** whose comment would come down to "3 of 5 children closed, the rest open": that is GitHub's own counter beside the list of sub-issues.

A comment earns its place when it says something that view does not, for example:

- a red stage — labels never say it alone (see above);
- state and labels that mislead: the feature's issue closed without a production deploy, a merge still awaited while nothing on the issue shows it, a production rollback;
- unticked acceptance criteria on a merged feature;
- on a parent, what the counter hides: which closed children reached production and which only preview, a child whose outcome is unclear, what is left in words when the open children's titles do not say it;
- a **Current behaviour** section the issue needs, or already has: the section stays, and the status heads it as always.

When in doubt, write it: a superfluous comment costs a reader a few seconds, a missing one sends them through the children.

**An existing comment that has become obvious** is stale or redundant either way. Read it **now** first (`gh api repos/{owner}/{repo}/issues/comments/<id> --jq .body`: a sibling's epilogue or I may have added to it since the snapshot). If it holds nothing beyond that view — no Current behaviour, nothing a human added that is still true — delete it with the command the snapshot gives for it, rather than rewrite it into a restatement of the labels. Otherwise rewrite it as below, keeping what is still worth saying.

## Current behaviour

**Current status** is the management view: where the work stands. **Current behaviour** is the product view: how the thing actually behaves. It is a second section of the same comment, and it exists only where the description no longer tells the truth — a reader who trusts the description should never be misled by it, and a reader of an issue whose description still holds should not have to read a second copy of it.

An issue's description is never edited, so this section is the only place where its drift is recorded. Once a section exists it must stay correct: every later epilogue that touches the issue reads it, and rewrites it when the product has moved again.

### On the feature itself (level 0)

Compare the description with what was actually built. The feature drifts from its description through:

- the `User request` comment — the whole request as agreed while scoping it, marking where it narrows or changes the description;
- the discussion in the snapshot — QA hand-backs ("Returned from QA"), answers to questions, decisions taken during review; a later decision overrides an earlier one;
- the pull request<if:pr-number> (#<pr-number>: `gh pr view <pr-number> --json body` and `gh pr view <pr-number> --comments`)</if:pr-number> — what the review changed;
- the code itself, when the sources above disagree or leave it open.

When any of it **contradicts** the description, or settles something the description leaves to be decided in a way a reader needs to know, write the section: the behaviour as it is now, whole, structured by area of the product — not a log of what changed when, and not a retelling of the parts of the description that still hold. Say at the top in one line that it supersedes the description where they differ.

### On a parent (level 1 and above)

The feature may be a change request to its parent: say a child regroups the fields of the form its parent describes and makes five of them share the event's privacy instead of having a picker each — the parent's description stops being true. Read the parent's description and its existing Current behaviour (in its status comment), and decide whether **this feature's** behaviour contradicts them.

- **It contradicts** — a field that's gone or renamed, a rule that now works differently, a default that changed: rewrite the parent's Current behaviour so it describes the product as it is now. Start from the existing section, keep what other children established there, and fold this feature in. Where the parent's section and this feature's disagree, the newer one — this feature — wins, but check the code when it is not obvious.
- **It only adds** — more detail, a new field, extra functionality, while every sentence of the parent's description is still true: write nothing about behaviour on the parent. Don't create a section to announce an addition; the status already names the closed child.

Go up the chain only as far as the contradiction reaches. That child changes how the form behaves, which is what its parent is about; an epic above them that never describes the form's fields gets no behaviour section from it. A parent with no section and no contradiction gets none.

### For both

**Check the code when in doubt, and only on what the section claims.** You're in the main repository, whose working tree may be in use: don't check out, pull or switch branches. `git fetch origin` and then `git grep <word> origin/main`, `git show origin/main:<path>` read the merged code without touching anything.<if:pr-number> A feature that is not merged yet is in its pull request: `gh pr diff <pr-number>`.</if:pr-number> A count or a mechanism taken from the pull request's description counts as in doubt: the description was written before the review rounds, and one status repeated its "16 cases" when 52 had been merged.

**Describe what is on `main`.** Behaviour that is still waiting for its merge is not current: on the feature itself say in one line that it takes effect on merge; on a parent, leave the parent's section as it is and say in its status which child will change it.

**Write it for a product reader**, not a developer: what a user sees and can do, the rules and defaults — not tables, routes or function names, unless the description itself is written that way.

## How to write the comment

**The description is not yours, on any issue in the chain, whoever wrote it.** Not one character of it changes: a developer reading an issue has to be able to trust that its description is the task as it was set. Everything you write goes into the status comment.

The comment is yours alone, and it looks like this:

```
<!-- sclaude:status -->
## Current status

…text…

## Current behaviour

…text, only where the issue needs it…
```

The marker on the first line is how the next session finds it. Current status always comes first; Current behaviour follows it when the issue has one. A section that's already in the comment stays in it unless the description has become true again. The snapshot above gives, for each issue, either the status comment as it stands with the commands that rewrite or delete it, or the command that creates it.

For each issue that needs a comment (see **When the issue already says it**):

1. If the comment exists, read it **now**, not from the snapshot: `gh api repos/{owner}/{repo}/issues/comments/<id> --jq .body`. The snapshot was taken at session start, and a sibling feature's epilogue or I could have changed it since.
2. Write the whole comment — both sections, the one you didn't change included — and feed it on stdin to the command from the snapshot — the `gh api -X PATCH …` one rewrites it in place, `gh issue comment <N> --body-file -` creates it. Never post a second status comment on an issue that has one.

Don't use `--comments` with `gh issue view`: it replaces the body with the comments rather than appending them, and the snapshot above already has what you need.

The acceptance criteria are worth reading before you write — they're in the snapshot where the issue has them, in a comment of their own (or, on an older issue, in the description between `<!-- sclaude:ac -->` and `<!-- /sclaude:ac -->`). They say what the feature was supposed to do, and the boxes say whether anybody confirmed it — an unticked list on a merged feature is a fact about where this stands, and the comment you're writing is about exactly that. Report what you see; don't tick a box, and don't treat an unticked one as a failure: plenty of features merge before anyone gets to the list. The criteria comment isn't yours, and neither is the `User request` comment the planning step keeps.

At most one status comment per issue, and no other comments. The orchestrator keeps its own progress summary in a comment of its own; yours exists because it's singular and says where things stand without reading the thread.

**When it doesn't work.** An issue won't open, `gh` errors, you lack edit rights — tell me in words and move on down the chain. One inaccessible issue is no reason to abandon the rest.

**How this session ends.** You're not a step of the cycle but its epilogue: the steps are over, <if:pr-number>the pull request is closed, </if:pr-number>the worktree is gone, and the orchestrator launches nothing after you.

<include:report>

**When the comments are written, `sclaude` closes this session itself.** Write the marker first — `echo done > <done-marker>` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed — write it again when you are done again. Leave the marker out only when something here needs my answer before the feature can be left: then I close the session myself.

When the comments are written, tell me in that one message — in your own words, but cover all of it:

- the work in this session is done — one line per issue, the number and the gist of what you wrote in it (or that it got no comment, or had its comment deleted, because its state and labels already say it — name what they say), whether it has a Current behaviour section and why (written, rewritten, left as it was, not needed), and anything you couldn't update;
- that `sclaude` closes this session itself — or, when you left the marker out, that I should close Claude with `/exit`;
- after that this feature is closed out: the `sclaude` orchestrator launches nothing more, and the next work starts with a new feature.

Then stop. Don't propose a continuation: there isn't one from here.
