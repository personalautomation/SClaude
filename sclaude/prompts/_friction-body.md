You're editing `~/instruments` — the `sclaude` orchestrator, not the product. The feature cycle (plan → code → PR → review) doesn't apply here: this repo commits to the branch it is already on — `main` for the orchestrator's maintainers, `dev/<name>` for everybody else — and sclaude put you on the right one before this session opened. Commit where you are: no new branch, no checkout, no pull request. You're already in it.

**instruments is public; the projects are not.** Whatever you commit here — code, comments, commit messages, prompts, tests — is published on GitHub the moment `sclaude` pushes it. Describe the problem in the orchestrator's own terms, never the project's: no project names, no pull-request, issue or feature numbers, no file paths, table names, services or infrastructure of the product. "A review round after a merge conflict", not the pull request and the project it happened in. What the project's own story needs goes to the project — its branch, its pull request, its issue.

**The fix may belong to the project instead — or to both.** Friction is not always the orchestrator's: a project script that hangs, a rule missing from the project's `CLAUDE.md`, a hook or a config of the project's own. You may edit the project too, in this feature's worktree, `<worktree>` — it is open to you in this session. There the project's own rules apply: read its `CLAUDE.md` first, and commit on the feature's branch, `<branch>`, by the project's commit rules — never on its `main`, and no new branch or pull request: the fix reaches `main` with this feature's pull request, and goes through its review like any other change. Don't push; `sclaude` pushes the branch after this session. Keep it to what the friction calls for — the feature's own code is the steps' work, not yours. Say in the plan which repository each change goes to, and in the report which commits you made where.

**What to read.**

- The friction log — `<log>`. It holds two kinds of entries, and that's normal. Rejections are written by the orchestrator, one paragraph each: time, step, source, subject, reason. Requests are written by the session itself, free-form and often several paragraphs: nobody asked it to fit into fields, and the analysis is better for it. A rejection's source says who issued it, and that determines where to look for the cause:

  - `hook` — one of our own bans fired, `forbidden-commands.py` or `no-code-in-planning.py`. The cause is in those files.
  - `rule` — `--disallowed-tools` fired. The cause is the `deny` list inside `step_settings()`.
  - `classifier` — the built-in `auto` mode classifier refused, not the orchestrator. No such ban exists in our files, so don't look there: see `claude auto-mode config`. It's tuned through the `autoMode.environment` line that `step_settings()` passes to the step — that's how steps 2–4 already know a feature worktree isn't a foreign repository but the same tree.
  - `model` — the session wrote it itself, and it's what no ban caught. Such an entry doesn't follow the fields: read it as prose.

  Entries with source `classifier` are gathered from the transcript by `collect-denials.py` once the session ends: Claude Code has no "permission denied" event, so there's nothing to record them with at the moment of refusal.
- The transcript: `<transcript>`. It's large; you don't need all of it. Go into it for context around a specific entry: what the session was doing, what it tried instead of the forbidden thing, what that cost. `grep` beats reading straight through.
- The bans themselves: `sclaude/lib/steps.sh`, function `step_settings()` — the `deny` list and the `--disallowed-tools` flag; `sclaude/hooks/forbidden-commands.py` — command-parsing bans for steps 2–4; `sclaude/hooks/no-code-in-planning.py` — the write ban in step 1.

**What to decide.** Not all friction is a bug. Some bans are deliberate and must not be lifted: merging a pull request, deploying to prod, `db:promote`, `env:prod`, pushing to `main` — those are my steps, and a session tripping over them only means the ban worked. Explain such entries and leave them alone — and, in the same commit, add the command as a line in `sclaude/known-denials.txt` if the rejection will recur every feature. The log lives in the worktree and dies with it: without that line, the next feature brings the same entry, and the analysis is paid for twice for the same conclusion.

Only what's permanent by construction goes on that list — what will always remain my step: merge, deploy, prod. A one-off obstacle you fixed by editing the orchestrator doesn't: it won't recur anyway, and a line in the list would hide it if it did.

What needs fixing is the other kind — a restriction that blocks the work and protects nothing. That's how a `--tools` allowlist once took subagents away from step 1 and left planning without reconnaissance (it has since been removed). The mark of it: the session wasn't trying to do something forbidden, it couldn't do something ordinary.

**And a third kind: put off.** Some entries are neither — a restriction that cost something once but might be protecting something, an obstacle one feature is not enough evidence to call. Don't force those either way: append them to `<deferred>`, one line each. That file is local state outside any repository — it describes projects, and instruments is public — so it is not committed; your commit holds the rest. The file is reviewed as a whole once a month (`sclaude deferred`), where how often a class comes back decides it. Read the file before you add to it: an entry that is the same problem as one already there takes the same class.

Entries marked `proposal` are rules a session proposed for the project's `CLAUDE.md`. They are always put off, never applied here: copy each into the deferred file, the proposed line as its text.

The line, tab-separated: the date, the project, the feature, the step, a short kebab-case class, and one sentence on what happened (or the proposed rule):

```
2026-10-09	myapp	12-review-profile-page	review	claude-md-stale-docs	Proposal: a change of behaviour greps docs/, both manuals and comments for the old wording in the same commit.
```

If you're unsure which kind an entry is, ask me instead of guessing.
