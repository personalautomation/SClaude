**Production was rolled back before this session opened.** The release serving production now is the one *before* this feature; your code is not live. That is why nothing is on fire while you work — and it is also why "I re-ran the prod regression and it passed" would mean nothing here: it would be a check on somebody else's release.

Three things follow from it.

**The check that matters is the local suite.** Production is not serving this branch, so a run against it says nothing about your fix. Run the regression the way step 2 does — against the dev server — and treat that as the evidence. The orchestrator runs the deployed stages itself, later, when the fix has been merged and shipped.

**The fix goes the whole way round again.** When you are done, the cycle returns to the review step in this same worktree and runs exactly the gates the feature passed the first time: the local suite, then the merge, then a preview deploy and its suite, then production and its suite. There is no shortcut back to production and you should not look for one — a fix that reached production without passing the preview is how this incident happened.

**Close the incident when it is closed.** There is a comment on the issue recording what broke and what was rolled back, posted by the orchestrator and marked `<!-- sclaude:rollback -->`. Once your fix is merged and production is green on it again, add a **new** comment to the same issue saying what the cause turned out to be and that production is back on this feature. A new comment rather than an edit of that one: the incident happened, and a record rewritten to say it did not is worse than no record.

If the cause turns out to be the schema rather than the code — the rollback may have left it ahead of the code, and the incident comment says whether it did — say so plainly instead of writing code around it. A schema and a build that disagree is a thing for a person to decide about, not a thing to patch over.
