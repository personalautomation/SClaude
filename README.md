# instruments

Machine-level Claude Code helper scripts and skills. Not tied to any project —
they live here, symlinked into `~/.local/bin` and `~/.claude/skills`.

| tool | what it is for |
|---|---|
| [`sclaude`](#binsclaude) | runs a feature from issue to production with Claude doing the work and a person making the decisions |
| [`skills/pr`](#skillspr) | a `/pr` skill: opens a pull request the way the team does it |
| [`sclaude-proxy`](#binsclaude-proxy) | one address per feature: `http://<feature>.localhost:3000` |
| [`chrome-debug`](#binchrome-debug) | the Chrome that Claude drives to check its work |
| [`wsl-update`](#binwsl-update) | the daily update of the tooling in WSL |
| [`keepawake`](#binkeepawake) | keeps the laptop awake while work goes on, and a Telegram bot to drive it all from a phone |
| [`statusline.py`](#statuslinepy) | Claude Code's status line |
| [`githooks/commit-msg`](#githookscommit-msg) | refuses a commit whose requirement footers would be lost |

How the parts work inside, and why they were built that way, is in
[`docs/sclaude.md`](docs/sclaude.md) and [`docs/keepawake.md`](docs/keepawake.md).

Everything written in this repository is in English; see `CLAUDE.md` for the
rule and its three deliberate exceptions.

## What this is, in the industry's words

`sclaude` is **spec-driven development** with an agent doing the typing, and
**the 3Cs** — contain, curate, control — as the safety model.

Neither label was chosen to sound current. SDD is the shape the industry
converged on during 2026, after vibe coding ran into multi-file drift and
constraints agreed in session one were forgotten by session three. The 3Cs are
Docker's framing of agent security: bound the blast radius, build the
environment the agent works in, enforce the rules as actions happen. This
repository was built to both shapes before either had a name.

### The loop: specify → clarify → plan → implement → verify

sclaude's cycle is made of steps, each a fresh Claude session, so nothing gets
lost in an overgrown conversation. SDD's five names fall across them unevenly:

| step | in SDD's words | what happens |
|---|---|---|
| **1. plan** | specify, clarify, plan | Claude reads the issue and the product's manuals, says what it thinks the scope is and waits for you to correct it, then writes a plan with acceptance criteria for you to approve |
| **2. code** | implement, verify | Claude builds it, checks it in a browser, and the product's tests must pass |
| **3. pr** | — | the pull request, and the manuals updated to match |
| **4. review** | verify | an automatic review of the pull request; Claude fixes what it finds; a preview deployment and its tests; then QA, the merge and production |
| **5. epilogue** | — | after production: the outcome written into the issue and its parents, so an epic shows where it stands |
| **6. retro** | — | before the feature is cleaned up: what you may have missed, how you could work better, what sclaude could do better |

When tests fail, a separate session fixes them. After every session a short
**friction review** looks at what sclaude's safety rules refused, and loosens a
rule that was in the way.

**Acceptance criteria are a gate, not a request.** Step 1 does not close until
the approved plan has them. They are written into the issue, every later step
works against them, and QA ticks them off there. Testable criteria before any
code exists is what shift-left asks for.

### A step closes on a result, never on a model saying "done"

| step | what actually closes it |
|---|---|
| plan | a plan you approved, with criteria |
| code | your yes **and** the product's tests passing |
| pr | a pull request that exists on GitHub |
| review | the tests passing on the preview; the pull request stays open for QA. No session at all when the automatic review found nothing |
| epilogue | the session actually ran; one that never started is offered again from the menu |
| retro | its session finished; one that was cut off is offered again |

Ctrl-C, a usage limit or a closed laptop closes nothing: sclaude remembers where
each feature is, and the conversation resumes. An interrupted run is never
mistaken for a finished one.

### Contain — the blast radius of a mistake

Every feature gets its own copy of the repository (a git worktree), its own dev
server at its own address, and, where the product supports it, **a database of
its own**. A migration written for one feature cannot reach another, and a
database reset wipes nobody else's data.

### Curate — what the agent can see and reach

The agent's world is set up before it runs. Each step has its own model and
permissions; in step 1 Claude cannot write code at all. What the product is —
its tests, its manuals, its environments, its board — the product describes in
`.sclaude/config.json`, so sclaude assumes nothing about anybody's repository.

### Control — the rules apply as the action happens

sclaude refuses these commands at the moment a session tries them:

- **merging a pull request** — that is a person's decision;
- **pushing to the product's `main`**, force-pushing, skipping the pre-push hook;
- **promoting migrations to production**, **switching to the production
  environment**;
- **writing code during planning**;
- **deploying to production** without asking: sclaude asks you, with no
  default, and words it "Ship to production **anyway**?" when QA never saw the
  feature.

These rules catch mistakes, not a session determined to get round them: a
command written to a file and run from there is beyond what they can see. If
your GitHub plan offers branch protection (free on public repositories, paid on
private ones), turn it on for `main` as well: require a pull request and allow
no direct pushes.

### Quality gates, in the Definition-of-Done sense

The product's tests run at up to four points: locally, on the preview, on
production, and once more after a production rollback. Each point runs what the
product declares. A failed run opens a fixing session, at most twice, and then
asks a person rather than looping for ever.

A branch that changes only files no test and no deployment reads skips the local
tests, the preview, QA and production: it goes through its pull request and
review, then the merge. These paths count as such in every product:

| path | why |
|---|---|
| `.github/` | CI workflows and bot settings; they first run on the pull request |
| `.sclaude/` | the orchestrator's own files |
| `.githooks/` | local git hooks |
| `docs/` | prose nothing builds |
| `*.md` in the root | `README.md`, `CLAUDE.md` and the like; Markdown deeper in the tree may be content, so it counts |

One file anywhere else and the branch goes the whole way. A product whose
`docs/` is built into its site is the case this assumption gets wrong.

### Production rollback that refuses to trample somebody else

If the tests fail on production, sclaude rolls production back to the release
before the feature and runs the tests again to confirm the old release works —
before anybody starts fixing. If somebody else deployed in the meantime, nothing
is rolled back: that release is not ours to remove. Migrations are undone only
where their undo instructions can actually be run, and sclaude shows the SQL and
asks first.

### The tool repairs itself, and says what a machine lacks

The friction review fixes the rules that got in the way. `sclaude doctor` lists
what a machine is missing and the command that fixes each gap, so onboarding is a
checklist. The retrospective at the end reads a recording of the whole run — what
sclaude printed and what you typed — and says what could go better.

### What is measured

One record per finished feature: time per step, test attempts, what failed, how
far it shipped, who ran it. Enough for the four DORA metrics from real cycles
rather than guesses.

### Two deliberate choices

**Review is an agent's, the merge is a person's.** This is Anthropic's own
division of labour for Claude Code Review — *"It won't approve PRs — that's
still a human call"* — and their reported effect is the argument for it: before,
16% of pull requests got substantive review comments; after, 54%.

What is left to you is the decision, and sclaude prepares it. Before asking
whether to merge, it shows the acceptance criteria as QA left them, the checks,
and the review's findings with what was done about each — including the case
where the review check is green but reviewed nothing. The question defaults to
*no*, and reads "Merge it **unchecked**?" when QA never saw the feature.

A product may hand either decision back to sclaude, in `.sclaude/config.json`
or from `sclaude config`. `qa` and `merge` each take `github` (a person does it
on GitHub; sclaude waits), `both` (the same, or a key in sclaude's wait — `a`
accepts, `m` merges) and `auto` (sclaude does it). By default QA is `github` and
the merge `both`. An acceptance given by sclaude says so in a comment on the
issue.

**No staging between preview and production.** Preview is the last stop.

### Where the claims come from

- [Vibe coding vs spec-driven development](https://www.augmentcode.com/guides/vibe-coding-vs-spec-driven-development) — what SDD is, and the 3–10× first-pass rate its adopters report.
- [Spec-driven development in 2026](https://devtoollab.com/blog/spec-driven-development-ai-agents) — the five-part loop, and Karpathy closing the vibe-coding era.
- [The 3Cs: a framework for AI agent security](https://www.docker.com/blog/the-3cs-a-framework-for-ai-agent-security/) — contain, curate, control. "Curation isn't approval. It is construction."
- [Code Review for Claude Code](https://claude.com/blog/code-review) — Anthropic on the same division of labour, and what it changed for them: substantive review comments on 16% of pull requests, then 54%.
- [Agent security and evaluation](https://github.com/war851/SDLC/blob/main/_foundation/google-agents-vibecoding-jun2026/day-4-vibe-coding-agent-security-and-evaluation/day-4-vibe-coding-agent-security-and-evaluation.md) — sandboxing, least privilege, human-in-the-loop for high-stakes actions, and the seven dimensions worth evaluating.
- [Git worktrees + Claude Code](https://www.developersdigest.tech/blog/git-worktrees-claude-code-parallel-agents-guide) — four to eight parallel worktrees per developer as the working norm.
- [DORA benchmarks](https://www.gitrecap.com/blog/dora-metrics-benchmarks) — what the records written here are meant to feed.
- [Coherence through orchestration](https://mikemason.ca/writing/ai-coding-agents-jan-2026/) — the warning worth reading first: alongside AI adoption, Google's DORA research found bug rates up 9%, review time up 91%, pull requests 154% larger. Gates on results and refused commands are the answer to exactly that.

## The environment it is built for

sclaude was built and is used every day on one stack: a Next.js app on Supabase,
shipped through Vercel, developed on Windows under WSL2. Nothing in it names a
particular product, but this is the stack where every part of it works, and the
further a product is from it, the more of sclaude it simply goes without.

**Required.** sclaude does not run without these:

| what | why |
|---|---|
| Linux or WSL2, with systemd | the commands are bash; the QA watch, the per-feature proxy and keepawake are systemd user units. macOS is not supported |
| git, python3 | everything sclaude does goes through them |
| the `claude` CLI, with auto mode and Bash allowed | every step is a Claude Code session; without those settings steps 2–4 stop on permission prompts |
| a GitHub repository and `gh`, logged in with the `project` scope | issues, pull requests, the board and QA's verdicts all live on GitHub |

**Recommended.** Each one turns on part of the cycle; without it that part is
skipped, and sclaude says so where it would have acted:

| what | what it gives you | without it |
|---|---|---|
| a Node app with `npm run dev` that listens on `PORT` (Next.js is what it is built on) | a dev server per feature at its own address, Claude checking its work in a browser | no dev server or browser check; the cycle still runs |
| a test suite the product names in `.sclaude/config.json` | the local, preview and production test gates | no test gates |
| an automatic Claude review on the product's pull requests (a `claude-code-review.yml` workflow) | the findings step 4 works through | step 4 has no findings to work from |
| a GitHub project board | the issue moving through `In progress`, `In QA`, `Done`; QA's hand-back | QA's verdict cannot be read from the board |
| Vercel (`vercel` CLI, logged in) | previews and production from sclaude, production rollback | no preview, QA on a deployment or production step |
| Supabase | per-environment databases, migrations promoted and rolled back with care | no database handling |
| Docker | a Supabase database of its own for every feature | features share the local database |
| Chrome from Playwright (`chrome-debug`) | Claude sees the feature in a real browser | Claude cannot look at what it built |
| `script` and `tmux` | the terminal recording the retrospective reads | the retrospective works without it |

**Optional.** For working away from the laptop: [Tailscale](https://tailscale.com)
to reach features and the machine from a phone, a Telegram bot of your own for
sclaude's questions and keepawake, Termius for SSH and code-server for an editor
in the phone's browser. On WSL, keepawake keeps Windows from sleeping while you
work from the phone.

`sclaude doctor` checks the required part, and inside a product the parts that
product uses.

## Installation

```bash
git clone git@github.com:personalautomation/SClaude.git ~/sclaude
cd ~/sclaude && ./install.sh
```

The checkout may live under any name. `install.sh` can be run as often as you
like: it links the commands into `~/.local/bin`, the skills into
`~/.claude/skills` and the status line into `~/.claude`, installs and enables
the systemd timers for WSL or plain Linux, and wires up this repository's git
hooks. Re-run it after pulling a change to a systemd unit. `~/.local/bin` has
to be in `PATH` (it usually is).

Then run `sclaude doctor`. It lists what the machine still lacks and the command
that fixes each gap. Run inside a product, it also runs the checks the product
asks for in `.sclaude/config.json`.

## For a team

instruments is meant to be installed as it is by a small team with a product of
its own — several developers, each on their own Linux or WSL machine, with no
server in between.

**Nobody forks it.** Everybody installs from this repository, and every sclaude
command that is about to act first pulls the latest `main`, so a fix reaches the
whole team at their next command. What is the team's own lives elsewhere:

| what | where |
|---|---|
| the orchestrator, its prompts, `MAINTAINERS` | here, one copy for everybody |
| the product and the team's process: tests, manuals, production, migrations, the GitHub board, its maintainers | `.sclaude/config.json` in the product's repository, committed |
| the team's sclaude rules for the product | `.sclaude/team/` in the product, committed, written by its maintainers |
| one developer's sclaude rules for the product | `.sclaude/people/<name>/` in the product, committed |
| what one machine keeps about the product: a feature's working files, terminal recordings | `.sclaude/local/` in the product, never committed, never deployed |
| the person: name, database choice, the Telegram bot, where records are gathered | `~/.config/sclaude/`, `~/.config/keepawake/env`, `~/.claude/sclaude/` |

In the product everything lives in one folder, `.sclaude/`. The one file at the
root is `.vercelignore`, because Vercel reads it nowhere else; sclaude keeps it
out of git.

**Joining a product that already uses it.** Clone the product; its
`.sclaude/config.json` is already there. The first feature asks once which of the
product's environments this machine works against. Your `.env*` files are yours
to fill; production credentials only for whoever ships. `sclaude doctor` inside
the product checks its part too.

**Setting a product up.** `sclaude new` in a repository without
`.sclaude/config.json` offers to write one. It reads the tests from
`package.json`, the manuals and migrations from the layout, and the board's
columns and date fields from the repository's GitHub project, and shows it all
for confirmation before anything is written. `sclaude/config.example.json`
explains every key, and `sclaude config` shows the same explanations beside your
values. Every section is optional and nothing is assumed: without a test suite
there is simply no test gate, and sclaude says so where it would have acted.

**Who changes the orchestrator.** `MAINTAINERS` lists the git addresses allowed
to commit sclaude straight to `main`. Everybody else commits by hand and runs
`sclaude propose`: the commits move to a branch of their own, `dev/<name>`, and
go out as a pull request — pushed here if you may push, otherwise through a fork
`gh` makes for you once. You keep using this repository; the fork is only how
the pull request travels. Without `MAINTAINERS` everybody is a maintainer, which
is what a copy used by one person wants.

sclaude's own review sessions — friction reviews, retrospectives, the monthly
review of deferred findings — never change this repository: they change the
product. A review that thinks one of sclaude's defaults is wrong for everybody
works around it in the product and leaves a note for the maintainers.

**Who keeps a product's rules.** `maintainers` in the product's
`.sclaude/config.json` lists who curates the shared rules in `.sclaude/team/`.
Anybody else's sessions write to `.sclaude/people/<name>/` instead. Both reach
`main` with the feature's pull request, where a maintainer can lift a personal
rule into `team/` once it proves itself. `sclaude doctor` says which folder is
yours.

**What a session may run.** Rules come in layers:

| layer | where | what it can do |
|---|---|---|
| sclaude's own rules | `sclaude/policy/core.json` | merging, pushing to the product's `main`, `--force`, `--no-verify`. Nobody lifts them |
| an integration's preset | `sclaude/policy/vercel.json`, `supabase.json` | the usual dangers of a stack: a deploy, a migration into a protected database. On when the product uses the integration |
| the product's team | `.sclaude/team/policy.json` | its own bans (say, `npm run db:promote`); an `allow` lifts an integration's ban |
| one developer | `.sclaude/people/<name>/policy.json` | bans and permissions of their own; lifts nothing the team or an integration bans |

Each file has `deny` and `allow` lists of commands with a reason, and the same
per step under `steps`.

A step may also get extra instructions from the product or from you:
`.sclaude/team/prompts/<step>.md` and `.sclaude/people/<name>/prompts/<step>.md`
are appended after sclaude's own prompt for that step.

**Who you are.** The part of your `git config user.email` before the `@`
(`SCLAUDE_DEV` overrides it). It names your branch, marks your records, and is
passed to the product's tests as `SCLAUDE_DEV`, so tests that create data on a
shared database can mark it as yours and clean up only their own.

**Everybody's own Telegram bot.** A bot token can be used by one machine only,
so each person makes their own with @BotFather. See [keepawake](#binkeepawake).

**Gathering the team's records.** Optional: name a git repository of the team's
in `~/.config/sclaude/metrics-remote`, and each person's cycle records are
published there as `<name>.jsonl`.

## bin/sclaude

One command that knows every feature in progress, remembers which step each is
on, and launches `claude` with the right model, permissions and prompt for it.

```bash
sclaude                 # the menu: features in progress, chosen with arrow keys
sclaude new [name]      # start a feature at step 1
sclaude <name>          # continue a feature from its current step
sclaude status          # every feature and its step
sclaude actions [name]  # everything you can do with one feature, in one list
sclaude doctor          # what this machine lacks, and how to fix it
sclaude config          # the product's settings, each one explained
sclaude dev [name]      # start a feature's dev server; --stop to stop it
sclaude sync <name>     # merge the latest main into a feature's branch
sclaude news <name>     # what has happened on the pull request
sclaude preview <name>  # deploy the branch to a preview
sclaude rollback <name> # put production back to the release before this feature
sclaude replan <name>   # take a feature back to step 1 and plan it again
sclaude return <name> [reason]  # send a finished feature back to step 4
sclaude reset <name>    # start the current step over, forgetting its conversation
sclaude done <name>     # clean up after the merge: worktree and branches
sclaude drop <name>     # abandon a feature and remove its traces, here and on GitHub
sclaude propose         # send your commits to sclaude as a pull request
```

`sclaude --help` has the rest. In the menu, tick "show actions after choosing" to
get every action for a feature in one list instead of remembering commands.

### A feature, start to finish

**Starting.** `sclaude new` offers the repository's open issues, yours first.
The chosen issue suggests a branch name, which you can edit. sclaude creates the
worktree, moves the issue to `In progress` on the board and fills in its start
date.

**Step 1, plan.** Claude gets the issue, its parent issues and the manuals'
contents up front. It tells you what it understood and waits; you correct it,
and only then does it plan. The plan ends with **acceptance criteria**: a
numbered list (`AC1`, `AC2`, …) of things a person can check on a deployment
without reading the code. When you approve, the criteria go into the issue as a
comment of their own. sclaude never edits an issue's description: the original
request, the criteria and the status are separate comments, so the task as it
was given stays readable.

**Step 2, code.** A fresh session builds it, with the approved plan as its
brief. Each commit names the criterion it serves in a `Requirement:` footer.
Claude checks its work in Chrome at the feature's address. The step closes when
you say it is done **and** the product's local tests pass.

**Step 3, pr.** The pull request, opened as a draft by the `pr` skill, with the
criteria copied in as an unticked checklist for QA, and the manuals updated in
the same pull request.

**Step 4, review.** The project's automatic review reads the pull request, and
a session fixes what it found, one round at a time. The step closes when the
review has nothing left open, the preview is deployed and its tests pass.

**QA, merge, production.** The issue moves to `In QA`, and sclaude waits — you
can close the terminal; a background timer keeps watching the board. QA checks
the criteria on the preview and ticks them in the issue.

- QA moves the issue to `Done`: the pull request is marked ready and gets a
  summary for whoever merges, and sclaude goes on to the merge.
- QA moves it back to `In progress`: their comments are collected word for word
  and a review session opens with them.

You can also send a finished feature back yourself with `sclaude return`.

The merge is yours (unless the product set it otherwise). After it sclaude
offers production, runs the tests there, and rolls back if they fail.

**Epilogue and retro.** A short session writes the outcome into the issue and
every parent issue, so an epic shows where it stands without opening each child.
The issue gets `deployed-preview` / `deployed-prod` labels, and its end date is
filled in. Then `sclaude done` runs the retrospective and asks before removing
the worktree and branches.

Each step's model and permissions:

| Step | Model | Permissions | What it does |
| --- | --- | --- | --- |
| 1. plan | opus / high | `plan` | Discussion; the only file it may write is the plan |
| 2. code | opus / medium | `auto` | Implementation, checking in Chrome, commits |
| 3. pr | sonnet / medium | `auto` | The manuals and the pull request — calls the `pr` skill |
| 4. review | opus / medium | `auto` | Fixing review findings, the preview deploy |
| 5. epilogue | sonnet / medium | `auto` | The outcome as one comment per issue, on the feature's issue and every parent; changes nothing in the repository |
| 6. retro | opus / medium | `auto` | What you missed, how to work better, what sclaude could do better. What it fixes goes on the feature's branch and sends the feature back to step 3 |

### Environments and databases

**Which database a feature uses is your machine's choice.** The product names
its environments in `.sclaude/config.json`, each as a `.env` file
(`"dev": {"env": ".env.dev"}`). sclaude asks once which one this machine works
against and remembers the answer; `SCLAUDE_ENV` overrides it. There is no
default, because a wrong guess is a quiet mistake. A feature is never pointed at
production.

**On a local database, every feature gets its own.** When the chosen
environment is the product's local Supabase, each feature gets a Supabase stack
of its own in Docker, filled from the main local database or the product's
seed. It is removed with the feature. If Docker is not running sclaude starts
it, and falls back to the shared local database, saying so, only when it cannot.

**Every feature has its own address**, `http://<feature>.localhost:3000`,
printed at the start of each step. A feature nobody has opened for half an hour
is stopped, database included (data kept), and starts again on the next visit.

### Switches

| variable | effect |
|---|---|
| `SCLAUDE_ENV` | the environment to use, instead of the remembered answer |
| `SCLAUDE_DEV` | your name, instead of the one from your git email |
| `SCLAUDE_NO_SYNC=1` | do not pull the latest sclaude before a command |
| `SCLAUDE_NO_RELOAD=1` | do not switch to newer sclaude code after a long session |
| `SCLAUDE_TERM=off` | do not record the terminal (recordings are kept 60 days) |
| `SCLAUDE_RETRO=off` | skip the retrospective |
| `SCLAUDE_DEV_IDLE` | how long an unused feature keeps running |
| `SCLAUDE_DOCKER_START=off` | never start Docker |
| `SCLAUDE_DOCKER_WAIT` | how long to wait for Docker to come up, in seconds (120) |
| `SCLAUDE_DOCKER_DESKTOP` | where Docker Desktop is, when it is somewhere unusual |

### What sclaude writes, and where

| what | for | where | in git | uploaded by a deploy |
|---|---|---|---|---|
| `.sclaude/config.json` | what the product is | the product | yes | no harm if it is |
| `.sclaude/team/`, `.sclaude/people/<name>/` | rules, prompt additions, deferred findings | the product | yes | no harm if it is |
| `.sclaude/local/feature/` | one feature's working state: the plan, logs, its database settings | the feature's worktree | never | never |
| `.sclaude/local/terminal/` | terminal recordings the retrospective reads | the product's main checkout | never | never |
| `.vercelignore` | keeps `.env*` and sclaude's files out of a deploy | each tree sclaude deploys | no, unless the product tracks its own | — |
| `~/.claude/sclaude/` | your cycle records, remembered choices, running dev servers | your home | never | — |
| `~/.config/sclaude/` | this machine's settings | your home | never | — |
| comments, labels, board moves, `Sclaude-Session` commit trailers | the feature's story where the team reads it | the product's GitHub and history | the trailers | — |

The cycle records are one JSON line per feature in `~/.claude/sclaude/cycles.jsonl`,
readable with `jq`:

```bash
jq -s '[.[] | select(.outcome == "done") | .steps.code.seconds] | add / length' \
  ~/.claude/sclaude/cycles.jsonl
```

## skills/pr

A Claude Code skill that finishes work through a pull request instead of a push
to `main`. Call it with `/pr`; sclaude's step 3 calls it too. Claude does not
run it on its own.

It works on a `feat/…` branch, checks that commits follow Conventional Commits,
runs the project's checks and opens the pull request. The description has
**Summary** — what changed; **Requested by the customer (for QA)** — what was
asked for, as observable behaviour, for QA to tick; then **How to verify** and
any **Notes**. It also updates the product's manuals. It never merges or
deploys.

## bin/sclaude-proxy

One address per feature: `http://<feature>.localhost:3000` reaches that
feature's dev server, whatever port it really uses. Chrome resolves every
`*.localhost` name by itself, so there is nothing to configure.

```bash
systemctl --user enable --now sclaude-proxy.socket   # install.sh does this
```

- `<feature>.localhost:3000` — that feature. One that is not running is started,
  with a page that waits for it.
- `localhost:3000`, or the machine's Tailscale address — the list of features.
  From another device, choosing a feature makes the bare address serve it from
  then on.

Different addresses rather than different ports keep features apart in one
browser: cookies ignore the port, so on ports alone signing in to one feature
would sign you out of another.

Only this machine and your Tailscale network are let in; anybody else on the
same Wi-Fi gets `403`. `SCLAUDE_PROXY_ALLOW` replaces the list with networks of
your own, comma-separated.

`sclaude dev` in the main checkout serves it at `main.localhost:3000`.

### A feature in Telegram, with no Tailscale on the phone

While phone access is on, the bot's chrome-debug card has a "📲 Phone" button for
the list of features and for each feature. It opens the feature full screen
inside Telegram, with an address bar of its own. The phone needs nothing but
Telegram.

It works through `tailscale funnel`, which publishes
`https://<node>.<tailnet>.ts.net:8443`. A gate in front lets in only your
Telegram account (the one in `KEEPAWAKE_CHAT_ID`), checked by Telegram's own
signature, and sends everyone else away with `403`.

Turn it on and off in the bot's Settings ("Phone access"). The first time needs,
once:

```bash
sudo tailscale set --operator=$USER    # lets the bot run `tailscale funnel`
```

Funnel also has to be allowed for the machine in your Tailscale policy; if it is
not, the bot shows Tailscale's answer with the link that turns it on. A product
that signs people in through a provider with a list of allowed redirect
addresses (Supabase Auth, OAuth apps) needs the funnel address in that list.

## bin/chrome-debug

Starts Chrome (Playwright's build) with the debugging port Claude Code's
chrome-devtools tools connect to. Under WSLg it also puts the window back on
the right monitor.

```bash
chrome-debug                     # bring the window forward, opening it if needed
chrome-debug http://localhost:3000/some/page   # the same, and go to that page
chrome-debug --stop              # close it
chrome-debug --keep              # skip the restart a misplaced window would need
chrome-debug --tab http://a.localhost:3000/   # open a background tab, leave the window alone
```

`CHROME_DEBUG_PORT` (9222) and `CHROME_DEBUG_PROFILE` change the port and the
profile. The log is at `~/.cache/chrome-devtools-mcp/chrome.log`.

You rarely need it by hand: sclaude opens the feature in a background tab before
each step, without pulling the window in front of whatever you are looking at.

## bin/wsl-update

The daily update of the tooling in WSL2: apt, nvm and Node, global npm packages,
Claude Code and its plugins, Playwright's Chromium, code-server. It also reports
outdated dependencies for the projects listed in `~/.config/sclaude/projects`
(one path per line) without touching them.

Local Supabase images are kept at the versions the Supabase CLI and production
use, and unused old ones are cleaned up. On the Windows side it only reports — a
newer WSL, applications `winget upgrade` lists — because updating those from
inside WSL would shut WSL down or need elevation.

It runs every day at 10:00 (and catches up after a missed day). Logs are in
`~/.local/state/wsl-update/`.

```bash
wsl-update                                  # run it now, in the terminal
systemctl --user status wsl-update.timer
journalctl --user -u wsl-update.service
```

## bin/keepawake

Keeps the machine awake while there is work going on, so it can continue from a
phone while the laptop stands closed. Under WSL it holds Windows awake; on plain
Linux it holds the machine itself (see [below](#keepawake-on-plain-linux)).

**What holds it.** A person at the machine — an SSH session, an open
code-server tab, traffic over Tailscale — holds it for as long as they are
there. Work that may be going on with nobody around — a busy `claude`, a dev
server — holds it for an hour at a time, and half an hour before the end the bot
asks whether to extend. With nothing holding it, the machine sleeps by its own
settings. If something holds it for an hour with no sign of anybody, the bot
asks whether a session was forgotten.

When in doubt it lets go: a laptop that sleeps too early costs a button press,
one that never sleeps costs a flat battery.

```bash
keepawake status          # why the laptop is (or is not) sleeping
keepawake extend 3600     # hold for another hour
keepawake release         # let go now
```

`keepawake status` prints two sections, `HOLD` and `HEALTH`.

**The Telegram bot.** Extend and status; a card for Chrome and the features (a
link for the phone, the address for the laptop, buttons to open or stop each);
code-server links; a sclaude section where you can start or continue a feature
and see what each step is doing (🟢 running, 🟡 waiting for you, ⚪ idle,
⚫ not started), with links to its issue and pull request; and "Docs" — how to
use and install all this. It answers in Russian to a Russian Telegram client and
in English to everyone else.

**Answering sclaude from the phone.** Every question sclaude asks goes to the
terminal and to the bot at once, and whichever you answer first counts. Start a
feature at the laptop, walk away, answer from the phone: the terminal carries on
by itself. While you are sitting at the terminal the question arrives silently,
so the phone does not buzz for something already on your screen. Claude's own
conversation in a step continues in the Claude mobile app.

**code-server starts on demand** — from a button in the bot, by following its
local link, or with `systemctl --user start code-server` — and stops itself
after an hour idle.

### keepawake on plain Linux

There is no Windows side, so `keepawake-linux.service` holds the machine itself
with `systemd-inhibit`. By default a background service may only stop the
machine sleeping *when idle*: a closed lid or an explicit suspend still sleeps
it, and the hold log says so once.

`install.sh` offers to change that on plain Linux, and only there. It explains
when the rule is worth having (a laptop you close while working from a phone),
shows the command that removes it, and asks. `./install.sh --polkit` adds it
without asking, `--no-polkit` skips the question. To remove it later:

```bash
sudo rm /etc/polkit-1/rules.d/49-keepawake.rules && systemctl --user restart keepawake-linux.service
```

By hand, the polkit rule is this:

```bash
sudo tee /etc/polkit-1/rules.d/49-keepawake.rules <<RULE
polkit.addRule(function(action, subject) {
  if ((action.id == "org.freedesktop.login1.inhibit-block-sleep" ||
       action.id == "org.freedesktop.login1.inhibit-handle-lid-switch") &&
      subject.user == "$USER") {
    return polkit.Result.YES;
  }
});
RULE
systemctl --user restart keepawake-linux.service
```

### Configuration

**Telegram.** Create a bot with `@BotFather`, find your `chat_id` (message the
bot and open `https://api.telegram.org/bot<TOKEN>/getUpdates`), and fill in
`~/.config/keepawake/env` from `keepawake/env.example`. The file must be mode
`600`, or the bot refuses to start.

```bash
cp keepawake/env.example ~/.config/keepawake/env
chmod 600 ~/.config/keepawake/env
$EDITOR ~/.config/keepawake/env
systemctl --user enable --now keepawake-telegram.service
```

**SSH for Termius** is the one part that needs `sudo`, which is why `install.sh`
does not do it:

```bash
sudo apt-get install -y openssh-server
sudo tee /etc/ssh/sshd_config.d/10-keepawake.conf <<'EOF'
ListenAddress <tailscale-ip>
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
EOF
sudo systemctl enable --now ssh
sudo loginctl enable-linger $USER
```

`ListenAddress` is your Tailscale address (`tailscale ip -4`), so SSH is not
reachable from a café's network. `enable-linger` is required: without it the bot
stops as soon as you close your last terminal — exactly when you need it.

Generate the key **on the phone** (Termius → Keychain → Generate) and copy only
the public half into `~/.ssh/authorized_keys`. In Termius: host
`<node>.<tailnet>.ts.net` (the name `tailscale status` shows), port 22, your
user name. No port forwarding or firewall rule is needed: Tailscale runs inside
WSL, so the phone reaches it directly.

code-server opens in the phone's browser at `http://<tailscale-ip>:8080`; the
password is in `~/.config/code-server/config.yaml`.

```bash
journalctl --user -u keepawake-telegram.service -f   # the bot's log
```

## statusline.py

Claude Code's status line. On the left, the sclaude session (`1-plan`,
`4-review(2)`, `4-fix-preview`, `5-epilogue`, …) and the path; in the middle the
branch, the feature's pull request, the session's name and the worktree; on the
right the model, the effort, how full the context is, and the usage limits. On a
narrow terminal the least important fields drop out first.

`install.sh` links it to `~/.claude/statusline.py`, which `settings.json` points
at.

## githooks/commit-msg

Refuses a commit whose `Requirement:` footers would not survive as git
trailers. Git only treats the last paragraph of a message as trailers, and only
if every line in it is one; a stray blank line, or a missing one, silently drops
them — and with them the QA section of the pull request the `pr` skill builds.
The hook asks git itself what it will see, and compares.

`install.sh` points this repository at it through `core.hooksPath`.
