# The stack and the costs

A ready toolkit for startups, PoCs and MVPs: a stack chosen for speed, an
orchestrator that keeps AI development controlled and cheap, and a phone
channel so the work never waits for the desk.

## Five criteria

1. **Days to first user** — hosting, auth, database and deploys come ready-made.
2. **Near-zero cost until traction** — free tiers carry a PoC; the main line
   item is the AI subscription.
3. **No ops team** — managed platforms, rollback in one step, previews instead
   of staging.
4. **AI-native** — mainstream tools the models know well, so the agent's first
   pass is right more often.
5. **Easy to grow or throw away** — standard Postgres and React; no lock-in.

## Four managed services instead of an ops team

| | role | built for AI | free to start | no lock-in |
|---|---|---|---|---|
| **Next.js** | UI and API in one codebase | small files keep the agent's context clear; conventions tell the model where things live | open source | runs on any Node host |
| **Supabase** | Postgres, sign-in, storage, an API | plain SQL the models know; one local database per feature | a free tier that carries a product almost to production | standard Postgres: dump it and move |
| **Vercel** | previews, production, rollback | a deploy is a git push; each preview is where QA checks the agent's work | free tier for previews and a first production | any host that runs Next.js or a container |
| **GitHub** | issues, board, pull requests, CI | the agent works through the `gh` CLI, the most context-efficient way in | free for a small team | git is portable |

On the laptop: Claude Code driven by SClaude, a worktree, dev server and
database per feature, a real Chrome the agent checks its work in, keepawake.
From the phone: the Claude app, the Telegram bot, Tailscale + Termius as the
spare key. No servers of our own and no staging.

## What it costs to adopt

| | |
|---|---|
| **Infrastructure** | ≈ 0 — free tiers of Vercel, Supabase, GitHub, Tailscale and Telegram carry a PoC; the laptops are already paid for |
| **Main line item** | the Claude subscription per developer, kept in check by lean context per step |
| **Onboarding** | one script, then `sclaude doctor` |
| **Licence** | MIT — use it for anything, change it, keep your changes, ship it, sell it |

**Observed in the team that runs it:** a 10–20% productivity improvement and
about 5% fewer tokens in the first weeks — project observations, not
universal benchmarks.

## Know before you start

SClaude runs on Linux and Windows with WSL2 today. macOS is not supported yet.
Every section of the product's config is optional: without a test suite there
is simply no test gate, and SClaude says so where it would have acted.

## Read more

- [Setting up: the environment it is built for](https://github.com/personalautomation/SClaude/blob/main/docs/setup.md)
