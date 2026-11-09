# Limits in code, not in prompts

> **A prompt is a request. A hook is a lock.**

Many orchestrators are built out of the agent itself: a crew of agents, skills,
a tree of markdown instructions. Instructions are advice. A model under
pressure invents a status, skips a predefined option, switches language, and
the process drifts. SClaude puts the limits where the model cannot talk its way
past them: in hooks and scripts.

## Two real stories

**July 2025.** A founder told Replit's AI agent, in capitals: *code freeze,
don't change anything.* The agent ran database commands anyway and wiped the
production database. With a hook, that command would simply have been refused.

**October 2026.** Attackers planted a tampered tool on a Binance engineer's
laptop, then used the company's own internal AI tool to reach other engineers'
machines, found a production token and deployed their code. An AI tool does
what the conversation asks. In SClaude the conversation doesn't decide: each
step gets only the tools it needs, so nothing can touch the production database
or ship to production on its own.

**We lead the AI, not the other way round.**

## Contain, curate, control

SClaude applies Docker's three layers of agent security
([the 3Cs](https://www.docker.com/blog/the-3cs-a-framework-for-ai-agent-security/))
to the whole coding workflow.

### Contain — a mistake stays inside one feature

With an agent per feature, a developer runs several in parallel. In one shared
checkout they collide: one migration wipes another's data, signing in to one
signs you out of the next. So every feature gets:

| | |
|---|---|
| **its own code** | a git worktree on its own branch; edits meet only in the pull request |
| **its own address** | `feature.localhost`, a dev server per feature, so cookies and sign-ins stay apart |
| **its own database** | Supabase in Docker, filled from the main local database or the seed |
| **its own preview** | a Vercel deployment per branch; QA never shares a staging server |

A feature idle for half an hour is stopped, database included, and starts
again on the next visit. Production is never a feature's target, and a failed
release rolls back without touching anybody else's.

### Curate — the agent's world is built before it runs

For every step the orchestrator decides the context (only what this step
needs, nothing stale), the tools and permissions, the model and effort, and
the instructions: SClaude's, the team's, the developer's. In planning, Claude
cannot write code at all. *"Curation isn't approval. It is construction."*

### Control — rules apply as the action happens

Refused at the moment a session tries them:

- merging a pull request — a person's decision;
- pushing to the product's `main`, force-pushing, skipping the pre-push hook;
- promoting migrations to production, switching to the production environment;
- writing code during planning;
- resolving a person's review decision alone;
- deploying to production without asking — asked with **no default answer**,
  and worded *"Ship to production **anyway**?"* when QA never saw the feature.

These rules catch mistakes, not a session determined to get round them. Turn on
branch protection for `main` as well where your GitHub plan offers it.

## Rules come in layers

| layer | what it holds |
|---|---|
| **SClaude core** | merge, `main`, force-push, skipping hooks. Nobody lifts these |
| **Integration presets** | the usual dangers of Vercel and Supabase; on when the product uses them |
| **The product's team** | its own bans; may lift a preset's |
| **One developer** | personal additions; lifts nothing above |

## Start tight — on purpose

An agent with every tool open starts steering the work: it picks the scope,
merges what it likes, touches what it should not. Then the model controls
development, not us. But locks alone fail too: a ban that blocks real work
makes people fight the tool or switch it off. So every refusal is logged and
read by the [friction review](Feedback-Loops).

**Tight by default. Loosened by evidence, never by habit.**

## Read more

- [How the cycle is kept in line](https://github.com/personalautomation/SClaude/blob/main/docs/cycle.md) — the full list of refusals and gates
- [For a team](https://github.com/personalautomation/SClaude/blob/main/docs/team.md#for-a-team) — the policy files and where they live
