# Fewer tokens: pay for thinking only

> **If a script can do it, the model shouldn't.**

## The model handles judgement; the orchestrator handles the rest

The orchestrator, at zero tokens and the same way every run:

- remembers which step every feature is on, and resumes after any interruption;
- gathers the context for each step and renders its prompt;
- sets up a sandbox per feature: worktree, dev server, database;
- runs the tests locally, on the preview and on production;
- deploys, and rolls production back when it goes red;
- keeps the issue, the pull request and the board up to date.

The token budget goes to planning, writing and reviewing code — where a model
is actually better than a script. The more work moves into the orchestrator,
the cheaper each feature gets.

## Six habits that cut the bill

Know-how that used to live in one person's head. Most of it is built into the
flow; the rest is shared as team practice.

| habit | why it saves | |
|---|---|---|
| **The cache lives an hour** | a subscription keeps the prompt cache for an hour (five minutes on credits or an API key). Warm, the context is re-read at a tenth of the price or less; cold, it is paid in full. Take on no more parallel features than you can answer within the hour | team habit |
| **A fresh session per step** | stale context is paid for on every message; starting clean costs nothing, while compacting a long conversation is itself a large request | built in |
| **The right model per step** | the strongest model where judgement matters, a cheaper one for the pull request and the write-up, none for deploys and gates | built in |
| **Scripts before tokens** | deterministic work runs as scripts; a hook can cut a ten-thousand-line log to its failures before the model reads it | built in |
| **Lean always-on context** | CLI tools rather than MCP servers, workflow instructions as skills that load on demand, CLAUDE.md under 200 lines | team habit |
| **Delegate the noisy parts** | sub-agents keep long outputs out of the main context; agent teams cost about seven times a single session | built in |

## Context managed for you

- A review round stays in the same session while its prompt cache is warm, and
  moves to a fresh one when that is cheaper.
- Noisy work goes to sub-agents.
- The review does not chase every finding: *"Chasing every finding leads to
  over-engineering."* (Anthropic, Claude Code best practices)
- Big features are built in [parts](Big-Features-in-Parts), each in a small
  context.
- What each feature, step and review pass cost is counted, and the cache hit
  rate is on the [metrics page](Metrics-and-Replay).

## Read more

- [Claude Code docs: managing costs](https://code.claude.com/docs/en/costs)
- [What is measured](https://github.com/personalautomation/SClaude/blob/main/docs/cycle.md#what-is-measured)
