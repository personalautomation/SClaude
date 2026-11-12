**The sync with <if:from-main>main</if:from-main><if:from-parts>the feature's branch</if:from-parts><if:reviewed>, step 5 of the cycle</if:reviewed>.** <if:reviewed>The feature "<feature>" is reviewed, and its pull request #<pr><if:issue> for issue #<issue></if:issue> is open on the branch `<branch>` — but it does not merge:</if:reviewed><if:unreviewed>The feature "<feature>"<if:issue> (issue #<issue>)</if:issue> is being built on the branch `<branch>`, and main is to be brought into it — but it does not merge cleanly:</if:unreviewed><if:from-parts>The feature "<feature>"<if:issue> (issue #<issue>)</if:issue> was built in parts, and I've accepted the whole; the parts now become one branch, the feature's, and one pull request into main opens from it. `<branch>`, the branch this tree is on, is the last part's and carries every part; before the feature's branch is moved to it, it has to take in `<from>` — a branch or a commit as it stands in this worktree, not necessarily on origin — but it does not merge cleanly:</if:from-parts><if:from-main> `origin/main` has moved since the branch left it</if:from-main><if:from-parts> `<from>` is the feature's common branch, holding what the parts do not: main synced there, or something put there by hand</if:from-parts><if:conflicts>, and merging the two leaves conflicts in

```
<conflicts>
```

`sclaude` checked that with `git merge-tree`, without merging.</if:conflicts><if:unfinished>, and a merge of the two is under way in this worktree: nothing is left unmerged, but it is not committed, and nobody has checked it.</if:unfinished> <if:reviewed>Until the branch merges cleanly there is nothing to send to QA and nothing to merge, so make</if:reviewed><if:unreviewed>Make</if:unreviewed><if:from-parts>Make</if:from-parts> it merge, here in this worktree:

1. `git fetch origin`, then `git merge <from>` into `<branch>` — or, when a merge is already under way here (`git status` says so), carry that one on rather than starting another. A merge, not a rebase: a pushed branch's history is not rewritten — on review it strands the discussion — and a force push is refused anyway.
2. Resolve every conflict so that both sides' intent survives: what `<from>` brought, as it has it, and what this <if:from-main>feature</if:from-main><if:from-parts>feature's parts</if:from-parts> change, on top of it. Read the commits on both sides (`git log --oneline --left-right HEAD...<from> -- the/file`) before deciding a hunk, rather than picking one side whole. Where the two cannot both stand — `<from>` removed or reshaped what the <if:from-main>feature</if:from-main><if:from-parts>parts</if:from-parts> build<if:from-main>s</if:from-main> on — do the smallest adaptation that keeps it working, and say so in the report.
3. Check the result the way the project checks a change — its `CLAUDE.md` says how: the build, the type check, the tests that touch the files you resolved.<if:db-api> This feature has a local database of its own, and `SUPABASE_WORKDIR` in your environment already points the CLI at it: `<db-cli> migration up` applies a migration the merge brought to this feature alone. Don't pass `--workdir`: it would reach another stack.</if:db-api> `<from>`'s own changes may need this code adapted even where git saw no conflict; fix that too, in the same merge or in a commit after it.
4. Commit the merge, and push `<branch>` (`git push origin <branch>`)<if:unreviewed> if it is on origin already; a branch that is not stays local, as it was</if:unreviewed>. Nothing else: no new features, no review fixes, no edits outside what the merge needs.

When you are done, `git merge-tree --write-tree HEAD <from>` must exit 0 and `git status` must be clean — `sclaude` checks both<if:reviewed>, and then sends the new code to the preview, the regression and QA again</if:reviewed>.

<include:questions>

<include:friction>

<include:report>

The report also names **each conflicted file and how you resolved it**, and anything `<from>` changed that the code had to be adapted to.

**When the branch merges cleanly<if:reviewed> and is pushed</if:reviewed>, `sclaude` closes this session itself.** Write the marker first — `echo done > .sclaude/local/feature/session-done` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed; write it again when you are done again. Leave the marker out when a conflict needs my decision — then say what the choice is, and I close the session myself.
