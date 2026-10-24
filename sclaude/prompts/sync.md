**The sync with main<if:reviewed>, step 5 of the cycle</if:reviewed>.** <if:reviewed>The feature "<feature>" is reviewed, and its pull request #<pr><if:issue> for issue #<issue></if:issue> is open on the branch `<branch>` — but it does not merge:</if:reviewed><if:unreviewed>The feature "<feature>"<if:issue> (issue #<issue>)</if:issue> is being built on the branch `<branch>`, and I asked to bring main into it — but it does not merge cleanly:</if:unreviewed> `origin/main` has moved since the branch left it, and merging the two leaves conflicts in

```
<conflicts>
```

`sclaude` checked that with `git merge-tree`, without merging. <if:reviewed>Until the branch merges cleanly there is nothing to send to QA and nothing to merge, so make</if:reviewed><if:unreviewed>Make</if:unreviewed> it merge, here in this worktree:

1. `git fetch origin main`, then `git merge origin/main` into `<branch>` — or, when a merge is already under way here (`git status` says so), carry that one on rather than starting another. A merge, not a rebase: a pushed branch's history is not rewritten — on review it strands the discussion — and a force push is refused anyway.
2. Resolve every conflict so that both sides' intent survives: what main brought, as main has it, and what this feature changes, on top of it. Read the commits on both sides (`git log --oneline --left-right HEAD...origin/main -- the/file`) before deciding a hunk, rather than picking one side whole. Where the two cannot both stand — main removed or reshaped what the feature builds on — do the smallest adaptation that keeps the feature working, and say so in the report.
3. Check the result the way the project checks a change — its `CLAUDE.md` says how: the build, the type check, the tests that touch the files you resolved. Main's own changes may need the feature's code adapted even where git saw no conflict; fix that too, in the same merge or in a commit after it.
4. Commit the merge, and push `<branch>` (`git push origin <branch>`)<if:unreviewed> if it is on origin already; a branch that is not stays local, as it was</if:unreviewed>. Nothing else: no new features, no review fixes, no edits outside what the merge needs.

When you are done, `git merge-tree --write-tree HEAD origin/main` must exit 0 and `git status` must be clean — `sclaude` checks both<if:reviewed>, and then sends the new code to the preview, the regression and QA again</if:reviewed>.

<include:questions>

<include:report>

The report also names **each conflicted file and how you resolved it**, and anything main changed that the feature had to be adapted to.

**When the branch merges cleanly<if:reviewed> and is pushed</if:reviewed>, `sclaude` closes this session itself.** Write the marker first — `echo done > .sclaude/local/feature/session-done` — and then the report, with no tool call after it. About thirty seconds after your turn ends the session is closed and the report printed in the orchestrator's terminal; if I type anything in those thirty seconds, the closing is called off and the marker removed; write it again when you are done again. Leave the marker out when a conflict needs my decision — then say what the choice is, and I close the session myself.
