This is the monthly review of the deferred friction for this product, one file per feature:

<files>

and the date each folder was last reviewed:

<stamps>

You are in `<worktree>`, a worktree of the product's main on its own branch, `<branch>`, made for this review. `<instruments>` is sclaude's live checkout: read it if you need to understand a restriction, and never change it — a hook refuses writes there. A change to sclaude is made in this review's workshop, as the paragraph on sclaude below says.

Over the month the friction reviews put two kinds of things in these files rather than decide them one at a time: friction that was neither a restriction to lift nor a ban working as intended, and the rules sessions proposed for the product's `CLAUDE.md`. Each line is one occurrence — date, project, feature, step, class, what happened. The point of collecting them is the count: one occurrence is an anecdote, the same class in five features is a pattern.

**What to do.**

1. Read every file and group the entries by class. Where two classes are plainly the same problem under two names, say so and treat them as one. Class `claude-md-already-stated` holds proposals sclaude matched to a rule the product's `CLAUDE.md` already states, the line quoted and the class it was proposed as named in the text: group those by the rule quoted, not as one class — each is a rule sessions do not follow, or a match that was wrong.
2. Give me a table, most frequent class first: the class, how many times, over which features and steps, the first and the last date, and one line on what it is.
3. For each class, propose one of:
   - **lift** — a restriction that keeps getting in the way: an `allow` in `<rules>/policy.json`, or a fix to the product's code;
   - **ban for good** — it recurs, and it is my step every time: a `deny` in `<rules>/policy.json`, so its refusals stop reaching the log;
   - **write the rule** — a proposed `CLAUDE.md` line that keeps being needed: into the product's `CLAUDE.md`, by its own rules;
   - **relax the rule** — class `claude-md-relax-…`, a rule review sessions found too strict, redundant or out of date because it kept producing findings that fixed nothing real: loosen or remove that line of the product's `CLAUDE.md` (or the rule it names), by the product's own rules;
   - **change sclaude** — class `sclaude-default`, or anything that is plainly wrong for every product: say what sclaude's default or code should become, as an item of its own in the plan. Once I approve it, make it in the workshop (below), and remove the entries it settles; an entry whose change you do not make stays in the file;
   - **keep waiting** — too rare to decide; it stays in the file;
   - **drop** — no longer true (the code it was about has changed) or not worth a rule; it goes from the file.

   Base it on the count and on the cost each occurrence had, not on how convincing a single entry reads. If you are unsure, ask me.

Then up to three optional sections. Each is left out when you have no evidence for it, and the same holds for every idea in them: a point stands on entries, on the product's history of the month (`git log`, the pull requests) or on a file you quote, never on what is usually useful. Give each idea how sure you are that I need it, as a percentage, and sort them from the surest to the most doubtful. Proposing nothing is better than adding a tool or a rule I will not use: the measure is how I work, as the evidence shows it. An idea that needs more history than a month gives may keep its entries in the files for the next review — say which.

4. **Settings that would make me faster.** Which of `sclaude`'s settings suit the way I work: the project's choices in `<instruments>/sclaude/config.example.json` against `<config>`, a copy of the main checkout's `.sclaude/config.json` — and the personal `SCLAUDE_*` switches in the table in `<instruments>/README.md`. Each with how it is set (`sclaude config set` takes only `review`, `qa`, `merge`; the rest is edited in that file, not in the copy) and the entries or history that point at it. Set none of them yourself: the project's config is shared by everybody on it.
5. **Knowledge that went stale.** sclaude has lately been allowed and forbidden many things, and the product's `CLAUDE.md` and other `.md` instructions, the user-level `~/.claude/CLAUDE.md` and Claude Code's memory for this product (`<memory>`) may still describe workarounds or say that something does not work. Find the statements that are no longer true and correct or remove them. Aim to shorten: change a wrong line rather than add one, and when something new must be written, write it briefly. The product's files are committed on `<branch>`; the memory is outside it — name each change to it in the plan and in the report. `~/.claude/CLAUDE.md` serves every project on this machine, and this review sees one: propose its changes as lines for me to make, and make none.
6. **Tools.** Plugins, MCP servers, libraries or dependencies worth installing, and hotkeys, skills, hooks or instructions that would help — and, the other way, ones already installed that nothing shows me using. Name what each would replace or save, and how it is installed or removed. Install nothing yourself: the approved plan lists them, and I install what I choose.

<workshop-rules>

`<rules>` is where this person's rules go: `.sclaude/team/` for the product's maintainers, their own `.sclaude/people/<name>/` for everybody else — a hook keeps everybody else out of `team/`.

Present it as a plan, and once I approve it, make the changes in `<worktree>`: the policy and the rules, the stale lines you were approved, and the entry files themselves — remove the entries of every class that was decided (lifted, banned, written or dropped), keep those that keep waiting or wait for a change to sclaude not made here, delete a file left with no entries, and write `<today>` alone into each `last-reviewed` above, creating it if it is not there. Only this review writes those files: a feature's branch adds entries, never dates. Commit on `<branch>` by the product's commit rules. When this session ends, `sclaude` pushes the branch and opens its pull request into the product's main; don't push or open one yourself.

**How this ends.** When the changes are committed, write the marker — `echo done > <done-marker>` — and then the report as your last message, with no tool call after it: what was decided for each class and in each optional section, which commits were made — in the product and in sclaude's workshop — what waits for a change to sclaude, and what keeps waiting. About thirty seconds after your turn ends `sclaude` closes the session and prints the report; if I type anything in that time, the closing is called off. If something is left for me to answer, leave the marker out, and I close the session myself.
