# Big features, built in parts (v1.1)

Some features are simply big: ten thousand changed lines or more. That is
exactly where AI coding starts to hurt.

1. **Context.** A big feature fills Claude Code's context window, the session
   gets compacted, and earlier decisions get lost.
2. **Cost.** Every step re-reads everything in the context, so the longer the
   session, the more each step costs.
3. **Review.** Nobody really reviews a ten-thousand-line pull request — not a
   person, not an AI. Quality drops, bugs slip through.

The usual advice is to split the feature by business requirements into
smaller features, each shipped on its own. We still recommend it when it makes
sense. But some features are one natural whole: cut one only so it fits a
session, and you keep the boundary in your head in every review and test,
preview and release each piece separately. Today a person's time and focus
matter most, and that is exactly where things get missed.

**In SClaude we try to remove the complexity, not move it.** A big feature
stays one feature: **one issue, one plan, one pull request, one QA**, built
in parts.

## How it works

**Step 1 offers the split.** When the plan is over about 10,000 changed lines,
step 1 offers to build it in parts, and you decide. Parts are **slices across
the feature, not layers**: not "the schema, then the API, then the screens",
but working pieces of behaviour. Each part works on top of the ones before it,
with green tests.

**Step 2 builds the parts one by one.** Each part gets a fresh session with a
small context, on its own branch, stacked on the part before it. Small context
means lower cost and sharper code: no compaction, no lost decisions. Before a
part closes, a fresh subagent reads its diff and looks for what would cost
more to fix later. Ask for a change meanwhile, and the session decides where it
belongs: now, or in a later part.

**You see each part as soon as it is built.** Before the next part starts,
SClaude records a short demo of what the part just added and sends it to
Telegram and the terminal. Nothing waits for your answer: tell the next part's
session what to change. The earlier a remark arrives, the less the next part
builds on what you would have said no to.

**You check the whole feature once.** One demo, built from the parts'
scenarios, one Accept. Only then does
review start. Why after Accept? Because a demo often brings changes, and after
any change every review has to be done again.

**Then the parts become one branch, and one pull request.** The parts are
stacked, so the last part's branch carries them all: the feature's branch
moves to it, and step 3 opens one pull request into `main`. Preview, QA and
production happen once, for the whole feature.

**The review reads the finished feature, in blocks.** A pull request this big
is too much for one review, so step 4 cuts it once, from the finished code —
not along the parts, which were drawn for building and showing before the
code existed. Each block is a group of the plan's criteria with the files
that carry them, so a rule is read end to end, from the database to the
screen. The blocks are read one by one, each to a clean verdict, and their
fixes go on top of the whole feature, so the tests check every part at once.
A last pass reads the seams between the blocks.

```
feat/<slug>-1 ◄── -2 ◄── -3        (built and shown one by one)
                          │ accepted
                          ▼
main ◄── one pull request: block 1 → block 2 → … → the seams
```

**The result:** small contexts, lower cost, a review that reads every line
of the finished feature — and for you, still one feature to test.

## Controls

- The menu shows where the parts are: `2/7 development · part 2/3` while they
  are built, and the review's block: `4/7 review · block 2/5`.
- `partAccept: each` in `sclaude config` ends each part on its own demo and
  Accept, if you want to see every part.
- `sclaude parts <name> stop` ships the feature with the parts built so far;
  the rest become an issue of their own.
- `reviewBlocks` in the project's config sets when a pull request is read
  in blocks (`from`, 5000 changed lines) and how big a block is (`size`,
  3000). Any big pull request is read in blocks, built in parts or not.

## Read more

- [The v1.1 release](https://github.com/personalautomation/SClaude/releases/tag/v1.1)
- [Step 1 and the split, in the guide](https://github.com/personalautomation/SClaude/blob/main/docs/sclaude-guide.md#a-feature-start-to-finish)
