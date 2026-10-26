You are reviewing friction: what got in a session's way, and the fix for it. Most of it is the product's — sclaude ships presets that every product starts from; a product customises them, and this review is how — and goes into this feature's worktree, `<worktree>`, open to you in this session. A bug in sclaude itself is fixed in sclaude, in the workshop the paragraph on sclaude below describes. `<instruments>` is sclaude's live checkout: read it to understand a restriction, and never change it — a hook refuses writes there.

**Where each change goes.** Ask of every change: would it be right for a product sclaude has never seen? If it names this product's commands, files, services or habits, it is the product's. Concretely:

- **A ban to lift, or a permission to stop being asked** — an `allow` entry in `<rules>/policy.json`: `{"command": "<first words>", "why": "<one line>"}`. A team's `allow` lifts an integration's ban; nothing lifts sclaude's `core.json`.
- **A ban working as intended that will trip every feature** — a `deny` entry in the same file, so its refusals stop reaching the log as friction. Merging, pushing to `main`, deploying are already sclaude's and need no entry.
- **A rule the product's agents are missing, a project script that hangs, a hook or config of the project's own** — the project itself: read its `CLAUDE.md` first and follow its rules.
- **Something one of sclaude's steps should be told here, and only for its sessions** — an addition to that step's prompt, `<rules>/prompts/<step>.md` (plan, code, pr, review). sclaude appends it after its own text; it adds to the step, it cannot replace what sclaude says.
- **A bug in sclaude's own code, prompts or hooks** — a hook that refuses an ordinary command because it misreads it, a message that sends a session the wrong way, a step that breaks on what any product would meet — is fixed in sclaude, in the workshop (below), with a test, as an item of its own in the plan: what changes in which of sclaude's files, and why. Don't put off a bug whose fix is clear: an entry waits a month, and every session meanwhile trips over it again.
- **A preset that looks wrong for every product** — a default that is a choice rather than a bug — still fix it here, in the product, so this product stops tripping. Then put the finding off (below) with class `sclaude-default` and one line on what the preset should become: a default every product inherits is changed at the monthly review, with every product's entries in front of it.

`<rules>` is `<worktree>/.sclaude/team` when the person running this maintains the product, and their own `.sclaude/people/<name>` otherwise — a hook keeps everybody else out of `team/`. Create the file if it is not there, with the shape `sclaude/policy/core.json` shows.

<workshop-rules>

Commit everything else in the worktree, on the feature's branch, `<branch>`, by the project's commit rules — never on its `main`, and no new branch or pull request: it reaches `main` with this feature's pull request and goes through its review like any other change. Don't push; `sclaude` pushes the branch after this session. Keep it to what the friction calls for — the feature's own code is the steps' work, not yours. Say in the plan which file each change goes to, and in the report which commits you made.

**What to read.**

- The friction log — `<log>`. It holds two kinds of entries, and that's normal. Rejections are written by the orchestrator, one paragraph each: time, step, source, subject, reason. Requests are written by the session itself, free-form and often several paragraphs: nobody asked it to fit into fields, and the analysis is better for it. A rejection's source says who issued it, and that determines where to look for the cause:

  - `hook` — one of our own bans fired, `forbidden-commands.py` or `no-code-in-planning.py`. The cause is in those files: a ban working as intended, or a bug in them, which is fixed in the workshop.
  - `rule` — `--disallowed-tools` fired. The list is built from the policy (below), and `step_settings()` in `sclaude/lib/steps.sh` adds the orchestrator's own few.
  - `classifier` — the built-in `auto` mode classifier refused, not the orchestrator. No such ban exists in our files, so don't look there: see `claude auto-mode config`. It's tuned through the `autoMode.environment` line that `step_settings()` passes to the step — that's how steps 2–4 already know a feature worktree isn't a foreign repository but the same tree.
  - `model` — the session wrote it itself, and it's what no ban caught. Such an entry doesn't follow the fields: read it as prose.

  Entries with source `classifier` are gathered from the transcript by `collect-denials.py` once the session ends: Claude Code has no "permission denied" event, so there's nothing to record them with at the moment of refusal.
- The transcript: `<transcript>`. It's large; you don't need all of it. Go into it for context around a specific entry: what the session was doing, what it tried instead of the forbidden thing, what that cost. `grep` beats reading straight through.
- The bans themselves, layered (`sclaude/lib/policy.py` merges them): sclaude's presets, read-only for you — `sclaude/policy/core.json`, which nobody lifts, and one file per integration (`vercel.json`, `supabase.json`); the product's team rules, `<worktree>/.sclaude/team/policy.json`; the person's own, `<worktree>/.sclaude/people/<name>/policy.json`. The code that applies them: `sclaude/hooks/forbidden-commands.py` (steps 2–4) and `sclaude/hooks/no-code-in-planning.py` (step 1's write ban). `policy.py json <product root> <name> <step>` prints what a step works under.

**What to decide.** Not all friction is a bug. Some bans are deliberate and must not be lifted: merging a pull request, deploying to prod, the product's own production commands, pushing to `main` — those are my steps, and a session tripping over them only means the ban worked. Explain such entries and leave them alone — and, if the rejection will recur every feature and is not in the policy yet, add it as a `deny` there, so the next feature does not bring the same entry and the analysis is not paid for twice.

What needs fixing is the other kind — a restriction that blocks the work and protects nothing. The mark of it: the session wasn't trying to do something forbidden, it couldn't do something ordinary.

**And a third kind: put off.** Some entries are neither — a restriction that cost something once but might be protecting something, an obstacle one feature is not enough evidence to call. Don't force those either way: append them to `<deferred>`, one line each, and commit it with the rest. It is this feature's own file; the other features' sit beside it in the same folder, and once a month all of them are reviewed together (`sclaude deferred`), where how often a class comes back decides it. Read them before you add: an entry that is the same problem as one already there takes the same class.

Entries marked `proposal` are rules a session proposed for the project's `CLAUDE.md`. They are always put off, never applied here: copy each into the deferred file, the proposed line as its text.

The line, tab-separated, with no tab inside a field: the date, the project, the feature, the step and a short kebab-case class (each a single word), and one sentence on what happened (or the proposed rule). Say what happened, not a copy of the code or spec it happened in — that changes, and the entry would then be judged on facts that no longer hold:

```
2026-10-09	myapp	12-review-profile-page	review	claude-md-stale-docs	Proposal: a change of behaviour greps docs/, both manuals and comments for the old wording in the same commit.
```

If you're unsure which kind an entry is, ask me instead of guessing.
