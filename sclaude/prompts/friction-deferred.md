This is the monthly review of the deferred friction: `<file>`.

Over the month the friction reviews put two kinds of things there rather than decide them one at a time: friction that was neither a restriction to lift nor a ban working as intended, and the rules sessions proposed for a project's `CLAUDE.md`. Each line is one occurrence — date, project, feature, step, class, what happened. The point of collecting them is the count: one occurrence is an anecdote, the same class in five features is a pattern.

**What to do.**

1. Read the whole file and group the entries by class. Where two classes are plainly the same problem under two names, say so and treat them as one.
2. Give me a table, most frequent class first: the class, how many times, over which features and steps, the first and the last date, and one line on what it is.
3. For each class, propose one of:
   - **lift** — a restriction in the orchestrator that keeps getting in the way; say what changes in which file;
   - **ban for good** — it recurs, and it is my step every time: a line in `sclaude/known-denials.txt`;
   - **write the rule** — a proposed `CLAUDE.md` line that keeps being needed: for this repository's `CLAUDE.md`, a commit here; for a project's (`<repo>`), a pull request in that project by its own rules — never a commit on its `main`;
   - **keep waiting** — too rare to decide; it stays in the file;
   - **drop** — no longer true (the code it was about has changed) or not worth a rule; it goes from the file.

   Base it on the count and on the cost each occurrence had, not on how convincing a single entry reads. If you are unsure, ask me.

Present it as a plan, and once I approve it, make the changes: the fixes and rules, and the file itself — remove the entries of every class that was decided (lifted, banned, written or dropped), keep those that keep waiting, and set the `# last reviewed:` line to `<today>`. The file is local state outside any repository, so its edit is not committed. Commit the fixes and rules in this repository by its rules: a Conventional Commits subject, a body, an unbroken footer block. A project's pull request is opened from that project's repository.

**How this ends.** When the changes are made and the fixes committed, write the marker — `echo done > <done-marker>` — and then the report as your last message, with no tool call after it: what was decided for each class, which commits and pull requests were made, and what keeps waiting. About thirty seconds after your turn ends `sclaude` closes the session and prints the report; if I type anything in that time, the closing is called off. If something is left for me to answer, leave the marker out, and I close the session myself.
