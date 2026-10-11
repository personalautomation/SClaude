This is the monthly review of the deferred friction for this product:

<files>

You are in `<worktree>`, a worktree of the product's main on its own branch, `<branch>`, made for this review. `<instruments>` is sclaude's own checkout: read it if you need to understand a restriction, and change nothing in it — a hook refuses writes there.

Over the month the friction reviews put two kinds of things in these files rather than decide them one at a time: friction that was neither a restriction to lift nor a ban working as intended, and the rules sessions proposed for the product's `CLAUDE.md`. Each line is one occurrence — date, project, feature, step, class, what happened. The point of collecting them is the count: one occurrence is an anecdote, the same class in five features is a pattern.

**What to do.**

1. Read every file and group the entries by class. Where two classes are plainly the same problem under two names, say so and treat them as one.
2. Give me a table, most frequent class first: the class, how many times, over which features and steps, the first and the last date, and one line on what it is.
3. For each class, propose one of:
   - **lift** — a restriction that keeps getting in the way: an `allow` in `<rules>/policy.json`, or a fix to the product's code;
   - **ban for good** — it recurs, and it is my step every time: a `deny` in `<rules>/policy.json`, so its refusals stop reaching the log;
   - **write the rule** — a proposed `CLAUDE.md` line that keeps being needed: into the product's `CLAUDE.md`, by its own rules;
   - **change sclaude's default** — class `sclaude-default`, or anything that is plainly wrong for every product: say what the preset should become. That is not done here: it is a deliberate pull request to sclaude, and the entry stays in the file until it is made;
   - **keep waiting** — too rare to decide; it stays in the file;
   - **drop** — no longer true (the code it was about has changed) or not worth a rule; it goes from the file.

   Base it on the count and on the cost each occurrence had, not on how convincing a single entry reads. If you are unsure, ask me.

`<rules>` is where this person's rules go: `.sclaude/team/` for the product's maintainers, their own `.sclaude/people/<name>/` for everybody else — a hook keeps everybody else out of `team/`.

Present it as a plan, and once I approve it, make the changes in `<worktree>`: the policy and the rules, and the files themselves — remove the entries of every class that was decided (lifted, banned, written or dropped), keep those that keep waiting or wait for a change to sclaude, and set each file's `# last reviewed:` line to `<today>`. Commit on `<branch>` by the product's commit rules. When this session ends, `sclaude` pushes the branch and opens its pull request into the product's main; don't push or open one yourself.

**How this ends.** When the changes are committed, write the marker — `echo done > <done-marker>` — and then the report as your last message, with no tool call after it: what was decided for each class, which commits were made, what waits for a change to sclaude's defaults, and what keeps waiting. About thirty seconds after your turn ends `sclaude` closes the session and prints the report; if I type anything in that time, the closing is called off. If something is left for me to answer, leave the marker out, and I close the session myself.
