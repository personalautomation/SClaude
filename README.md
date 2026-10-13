# instruments

Machine-level Claude Code helper scripts and skills. Not tied to any project —
they live here, symlinked into `~/.local/bin` and `~/.claude/skills`.

Everything written in this repository is in English; see `CLAUDE.md` for the
rule and its three deliberate exceptions.

## What this is, in the industry's words

`sclaude` is **spec-driven development** with an agent doing the typing, and
**the 3Cs** — contain, curate, control — as the safety model.

Neither label was chosen to sound current. SDD is the shape the industry
converged on during 2026, after vibe coding ran into multi-file drift and
constraints agreed in session one were forgotten by session three; Karpathy
called that era over a year after coining it. The 3Cs are Docker's framing of
agent security: bound the blast radius, build the environment the agent works
in, enforce the rules as actions happen. This repository was built to both
shapes before either had a name.

### The loop: specify → clarify → plan → implement → verify

One step per phase (`sclaude/lib/steps.sh:14`):

| phase | how it happens here |
|---|---|
| **specify** | the issue, its parents and the product's manuals are read before anything is guessed |
| **clarify** | step 1 stops on its guess about scope and waits to be corrected — planning around an unconfirmed guess means redoing the plan |
| **plan** | the approved plan goes to `.sclaude/local/feature/plan.md`, the only thing carried between steps |
| **implement** | a fresh session per step, so nothing rots in a context window |
| **verify** | a regression the step cannot close without |

**Acceptance criteria are a gate, not a request.** Step 1 does not close until
the approved plan carries them; they are written into the issue between
machine-readable markers, handed to every later step, and ticked by QA there
(`sclaude/lib/acceptance.py`, gate at `run.sh:480`). Testable criteria before
any code exists is what shift-left asks for.

### A step closes on an artefact, never on a model saying "done"

| step | what actually closes it |
|---|---|
| plan | an approved plan, with criteria, on disk |
| code | the human's yes **and** a green local regression |
| pr | a pull request number that exists on GitHub |
| review | a green regression, not re-run on a tree it already passed; the pull request stays open for QA. No session at all when the automatic review is clean |

Ctrl-C, a usage limit or a closed laptop closes nothing: state lives in
`.sclaude/local/feature/state.json` and the conversation resumes. An interrupted run cannot
be mistaken for a finished one — the failure mode most home-grown agent
pipelines ship with.

### Contain — the blast radius of a mistake

Every feature gets a git worktree, and with it a dev server on its own address
(`http://<feature>.localhost:3000` through `bin/sclaude-proxy` — different hosts
keep cookies apart, which different ports alone would not) and, where the
product supports it, **a database of its own**: a Supabase stack per feature
(`sclaude/lib/featuredb.sh`). A migration applied in one feature cannot reach
another; a `db reset` wipes nobody else's data.

Test accounts carry the developer's and the feature's name, so two suites
against one shared database do not sweep away each other's fixtures.

### Curate — what the agent can see and reach

The agent's world is built before it runs, not reviewed afterwards. Each step
gets its own model, effort and permission mode; step 1 runs in plan mode where
writing is refused outright. What the project is — its checks, its manuals, its
environments, its board columns — is declared by the product in `.sclaude/config.json`,
so the orchestrator carries no assumptions about anybody's repository.

### Control — the rules apply as the action happens

A PreToolUse hook refuses the command as the session tries it
(`sclaude/hooks/forbidden-commands.py`):

- **merging a pull request**: "they decide when a PR goes to main";
- **pushing to `main`** of the product (sclaude's own checkout goes to `main`
  without a pull request, so a push to its `main` passes), force-pushing,
  skipping the pre-push hook;
- **promoting migrations to production**, **switching the environment to prod**;
- **writing code during planning**: a separate hook, because a plan that has
  already edited files is not a plan;
- **deploying to production**: a question with no default, which re-asks until
  it gets yes or no, worded "Ship to production **anyway**?" when QA never saw
  the feature.

An agent that tries the ordinary spellings of a merge or a promote is stopped,
and every privileged action stays attributable to whoever answered the
question.

#### Why a hook, and not branch protection

The hook guards against accidents, not against a session set on getting
round it. It reads the command line it is shown. Subshells, brace groups,
`bash -c '…'`, `eval`, a merge through `gh api` (REST or GraphQL) and a push
whose destination is a variable, a substitution or `refs/heads/main` are all
read and refused; a code review found each of them going through, and
`tests/hooks.py` now holds them. What it cannot see is a command written to
a file and run from there (`python x.py`, `bash x.sh`), or a git alias. No
hook can.

Branch protection on GitHub is the guard that holds against that, because it
is enforced on the server. sclaude does not rely on it, because GitHub offers
it on private repositories only on paid plans (Pro, Team, Enterprise), and a
product on the free plan would be left with nothing. On a paid plan, or on a
public repository, where it is free, turn it on for `main` on top of the
hook: require a pull request, and allow no direct pushes.

### Quality gates, in the Definition-of-Done sense

Four regression stages (`local`, `preview`, `prod`, and a separate `rollback`
confirmation run), each declared by the product rather than the orchestrator. A
red run opens a fixing session, twice (`REGRESSION_MAX_ATTEMPTS=2`), then asks a
human instead of looping for ever.

### Production rollback that refuses to trample somebody else

A red production regression rolls the deployment back and re-runs the suite as a
**separate stage**, so a green confirmation can never be read as the feature's
own. Before any of it, `regression_deploy_intruded` asks whether somebody
deployed *during* the run; if they did and the retry is still red, **nothing is
rolled back** — the release on top is not ours to remove. Migration down-blocks
are classified rather than trusted, and one that cannot be executed is named,
not skipped.

### The tool repairs itself, and says what a machine lacks

After every session a **friction review** reads what the permission hooks refused and
decides whether each ban was right or in the way — then fixes the orchestrator.
`sclaude doctor` names every missing piece on a machine and the command that
fixes it, so onboarding is a checklist rather than a week of tribal knowledge.

**And once more at the end.** Every interactive run of `sclaude` is recorded by
`script(1)` — what it printed, sessions' last messages and plan changes
included, and what the person typed — under `~/.claude/sclaude/terminal/` (kept
60 days; `SCLAUDE_TERM=off` turns it off). The sessions themselves are not: they
have their transcripts, and one that runs in sclaude's own window is cut down
to a line naming it. Right before `sclaude done` asks to remove a
merged feature, a session reads that record played back as plain text (through
`tmux`), together with `.sclaude/local/feature/`, and answers three questions from facts alone:
what the person may have missed, how they could work better, and what
`sclaude` itself could do better. With nothing to act on in the first and the
third it closes by itself; otherwise it stays open to talk it through, while the
worktree is still there. `SCLAUDE_RETRO=off` skips it.

### What is measured

One record per finished feature: wall-clock per step, regression attempts per
stage, which part failed, how far it shipped, who ran it. Enough to build the
DORA four from real cycles rather than guesses.

### Two deliberate choices

**Review is an agent's, the merge is a person's.** This is Anthropic's own
division of labour for Claude Code Review — *"It won't approve PRs — that's
still a human call"* — and their reported effect is the argument for it: before,
16% of pull requests got substantive review comments; after, 54%. An agent
reviews every PR rather than a person reviewing whichever ones they get to.

What is left to the human is the decision, and the cycle prepares it. Before the
merge question it lays out the acceptance criteria as QA left them in the issue,
ticked and unticked; the checks with their outcomes; and the review's findings
with what was done about them — including the case a green tick hides, where the
workflow finished without reviewing anything (`sclaude/lib/pr_context.py`). The
question itself defaults to *no*, and reads "Merge it **unchecked**?" when QA
never saw the feature.

**No staging between preview and production.** Preview is the last stop.

### Where the claims come from

- [Vibe coding vs spec-driven development](https://www.augmentcode.com/guides/vibe-coding-vs-spec-driven-development) — what SDD is, and the 3–10× first-pass rate its adopters report.
- [Spec-driven development in 2026](https://devtoollab.com/blog/spec-driven-development-ai-agents) — the five-part loop, and Karpathy closing the vibe-coding era.
- [The 3Cs: a framework for AI agent security](https://www.docker.com/blog/the-3cs-a-framework-for-ai-agent-security/) — contain, curate, control. "Curation isn't approval. It is construction."
- [Code Review for Claude Code](https://claude.com/blog/code-review) — Anthropic on the same division of labour, and what it changed for them: substantive review comments on 16% of pull requests, then 54%.
- [Agent security and evaluation](https://github.com/war851/SDLC/blob/main/_foundation/google-agents-vibecoding-jun2026/day-4-vibe-coding-agent-security-and-evaluation/day-4-vibe-coding-agent-security-and-evaluation.md) — sandboxing, least privilege, human-in-the-loop for high-stakes actions, and the seven dimensions worth evaluating.
- [Git worktrees + Claude Code](https://www.developersdigest.tech/blog/git-worktrees-claude-code-parallel-agents-guide) — four to eight parallel worktrees per developer as the working norm.
- [DORA benchmarks](https://www.gitrecap.com/blog/dora-metrics-benchmarks) — what the records written here are meant to feed.
- [Coherence through orchestration](https://mikemason.ca/writing/ai-coding-agents-jan-2026/) — the warning worth reading first: alongside AI adoption, Google's DORA research found bug rates up 9%, review time up 91%, pull requests 154% larger. Gates on artefacts and refused commands are the answer to exactly that.

## Installation

```bash
git clone git@github.com:personalautomation/SClaude.git ~/sclaude
cd ~/sclaude && ./install.sh
```

The checkout may live under any name: nothing refers to `~/sclaude` by path.
`install.sh` is idempotent: it creates symlinks in `~/.local/bin`,
`~/.claude/skills` and `~/.claude` (the status line), writes the systemd units
into `~/.config/systemd/user` with the checkout's path filled in (re-run it
after a unit changes),
enables the timers for the platform it finds (WSL or plain Linux) and wires up
this repository's hooks. `~/.local/bin` has to be in `PATH` (it usually already
is, through `~/.profile` / `~/.bashrc`). Then run `sclaude doctor`: it lists
what this machine still lacks and the command that fixes each gap. Run inside a
product, it also runs the checks the product declares in `.sclaude/config.json` under
`doctor` — for example, whether your tailnet is admitted to the auth
provider's redirect URLs.

## For a team

instruments is written to be installed as it is by a small team with a product
of its own — several developers, each on their own Linux or WSL machine, with
no server of ours in between.

**Requirements.** git, python3, the `claude` CLI, `gh` logged in with the
`project` scope (`gh auth refresh -s project`), and `node`/`vercel` if the
product ships through them. `sclaude doctor` checks all of it.

**Nobody forks it.** Everybody installs from this repository, and every
command that is about to act first brings in `main` (`instruments_sync`), so a
fix reaches the whole team at their next command. Whatever is the team's own
lives elsewhere:

| what | where |
|---|---|
| the orchestrator, its prompts, `MAINTAINERS` | here, one copy for everybody |
| the product and the team's process: regression, manuals, production, migrations, the GitHub board, its maintainers | `.sclaude/config.json` in the product's repository, committed |
| the team's sclaude rules for the product | `.sclaude/team/` in the product, committed, written by its maintainers |
| one developer's sclaude rules for the product | `.sclaude/people/<name>/` in the product, committed |
| what one machine keeps about the product: terminal recordings | `.sclaude/local/` in the product, never committed, never deployed |
| the person: name, database, projects for `wsl-update`, the Telegram bot, where records are gathered | `~/.config/sclaude/`, `~/.config/keepawake/env`, `~/.claude/sclaude/` |

**Who changes the orchestrator.** Not the review sessions: friction reviews,
retrospectives and the monthly deferred review read sclaude's checkout and
change the product (a hook keeps the checkout read-only to them). A step
session whose plan reaches into sclaude may commit there and push to its
`main` — the ban on pushing to `main` is the product's, and sclaude's checkout
has no pull requests of its own. A change to sclaude's out-of-the-box
behaviour is made deliberately. `MAINTAINERS` lists
the git addresses allowed to commit it straight to `main`. Everybody else
commits by hand, then runs `sclaude propose`: the commits move from `main` to
a branch of their own, `dev/<name>`, and sclaude sends it as a pull request
into `main` by itself: pushed here if you may push, and otherwise to a
fork of yours, which it makes once with `gh` as the remote `fork`. The pull request is opened once, and every later push updates it.
Run from a product, `sclaude propose` first lists the product's deferred
entries of class `sclaude-default`, the findings that asked for a change.
`origin` stays this repository, so updates keep arriving at your next command
as before. You use this repository, not your fork; the fork is only how a pull
request travels. Without `gh`, the push failure prints the commands instead.

**Who keeps a product's rules.** The same idea, one level down, in folders
rather than branches, because a rule only applies once it is on the product's
`main`. `maintainers` in the product's `.sclaude/config.json` lists the git
addresses of the people who curate the product's shared sclaude rules in
`.sclaude/team/`. A session run by anybody else writes its rules to
`.sclaude/people/<name>/` instead, and a hook (`sclaude/hooks/write-guard.py`)
refuses its writes into `team/`. Both reach `main` with the feature's pull
request, where a maintainer sees them, and a maintainer lifts a personal rule
into `team/` when it proves itself. No `maintainers` means everybody keeps
them, as with one developer. `sclaude doctor` says which folder is yours.

**What a session may run.** sclaude ships presets, and the product decides
the rest (`sclaude/lib/policy.py`):

| layer | where | what it can do |
|---|---|---|
| sclaude's own rules | `sclaude/policy/core.json` | merging, pushing to the product's `main` (sclaude's own `main` takes a push), `--force`, `--no-verify`, a pull request from step 2. Nobody lifts them |
| an integration's preset | `sclaude/policy/vercel.json`, `supabase.json` | the stack's usual dangers: a deploy, a migration into a protected database, Supabase's MCP writing tools. On when the product lists the integration, or, while it lists none, evidently uses it |
| the product's team | `.sclaude/team/policy.json` | its own bans (`npm run db:promote`), its integrations, their settings (how to tell which database the tree is on); an `allow` lifts an integration's ban and stops the question |
| one developer | `.sclaude/people/<name>/policy.json` | bans and permissions of their own; lifts nothing the team or an integration bans |

Every file has the same shape: `deny` and `allow` lists of commands with a
reason, matched by their first words however they are wrapped, and the same
per step under `steps`. The hook and the step's `--disallowed-tools` are both
built from the merged result, so no product's command is named in sclaude
itself.

**What sclaude writes, and where.** Everything it produces, who changes it,
and whether git or a deploy ever sees it:

| artefact | what it is for | where | who changes it | in git | uploaded by a deploy |
|---|---|---|---|---|---|
| sclaude itself: code, prompts, presets (`sclaude/policy/`), `MAINTAINERS`, `known-denials.txt` | the orchestrator and what it offers out of the box | this repository | its maintainers; anybody else by pull request | yes, here | — |
| `.sclaude/config.json` | what the product is: checks, manuals, environments, production, board, maintainers | the product's `.sclaude/` | the product's team; `sclaude new` proposes it, a person confirms | yes, the product's | no harm if it is |
| `.sclaude/team/policy.json` | the team's rules for sessions | product | the product's maintainers, through the product's pull requests | yes, the product's | no harm if it is |
| `.sclaude/people/<name>/policy.json` | one developer's rules for sessions | product | that developer | yes, the product's | no harm if it is |
| `.sclaude/team/prompts/<step>.md`, `.sclaude/people/<name>/prompts/<step>.md` | what the product, then the person, add to a step's prompt; appended after sclaude's text, never in its place | product | the maintainers; that developer | yes, the product's | no harm if it is |
| `.sclaude/local/feature/`: `plan.md`, `state.json`, `friction.log`, `regression.log`, `dev.log`, `db.env`, `review-yours`, `terminal.txt`, … | one feature's working state: the agreed plan, the cycle's state, logs, the feature's local database | the feature's worktree | sclaude and the feature's sessions | never (`.git/info/exclude`) | never (`.vercelignore`) |
| `.sclaude/local/terminal/*.log` | the recorded terminal, which the retrospective reads | the product's main tree | sclaude | never | never |
| `.vercelignore` | what a deploy must not upload | each tree sclaude deploys | sclaude, appending what is missing; a project that tracks its own keeps it | no, unless the project tracks one | — |
| lines in `.git/info/exclude` | hide sclaude's own paths from git | the product's `.git` | sclaude | — (not versioned) | — |
| `deferred/<feature>.tsv`, `deferred/last-reviewed` | findings put off for the monthly review, one file per feature so two features' branches never edit one file; the date of the last review | the person's rules folder in the product: `.sclaude/team/` or `.sclaude/people/<name>/` | friction reviews add entries on the feature's branch; only the monthly review, on a branch and pull request of its own, removes them and writes the date | yes, the product's | no harm if it is |
| `cycles.jsonl` | one record per finished feature: durations, attempts, verdicts | `~/.claude/sclaude/` | sclaude | never; published as `<name>.jsonl` only if `metrics-remote` names a team repository | — |
| `environment`, `epilogue`, `watch`, `dev` | the environment you chose per product, the status epilogue's state, the QA watcher, the dev servers the proxy routes to | `~/.claude/sclaude/` | sclaude | never | — |
| `terminal/` | recordings of runs started outside any repository | `~/.claude/sclaude/` | sclaude | never | — |
| session transcripts | what each session did; friction reviews and the retrospective read them | `~/.claude/projects/`, Claude Code's own | Claude Code | never | — |
| issue status comments, pull-request bodies, board columns, `Sclaude-Session` trailers | the feature's story where the team reads it | the product's GitHub, and its commits | sclaude and the feature's sessions | the trailers, in the product's history | — |
| `~/.config/sclaude/` | this machine's settings: `projects` for wsl-update, `metrics-remote`, the polkit mark | your home directory | you | never | — |

In the product, all of it lives in one folder, `.sclaude/`, so the product's
root does not grow: `config.json`, `team/` and `people/` are committed;
`local/` (a feature's working directory, the recordings) never is. The one
file at the root is `.vercelignore`, because Vercel reads it nowhere else, and
sclaude keeps it out of git.

Nothing a product produces goes into this repository. The review sessions
write the product's `.sclaude/` and its code, and a hook keeps sclaude's own
checkout read-only to them. A change to sclaude's out-of-the-box behaviour
reaches it only as a deliberate pull request; a review that thinks a preset is
wrong for every product works around it in the product and leaves a deferred
entry of class `sclaude-default` for that decision.

**Who you are.** The local part of `git config user.email`, reduced to
`[a-z0-9-]` (`SCLAUDE_DEV` overrides it). It names your branch, marks your
metrics records, and is exported to every regression part as `SCLAUDE_DEV`, so
a product whose suite creates data on a shared database can mark that data as
yours and sweep only its own. Two people running the suite on one database
then never delete each other's test accounts mid-run.

**Joining a product that already uses it.** Clone the product; its
`.sclaude/config.json` is already there. The first feature asks once which of the
product's environments this machine works against. Your own `.env*` files are
yours to fill; production credentials only for whoever ships. `sclaude doctor`
run inside the product checks the project half too.

**Setting a product up.** `sclaude new` in a repository without `.sclaude/config.json`
offers to write one, reading the regression from `package.json`, the manuals and
migrations from the layout, and the board's columns and date fields from the
repository's GitHub project — shown for confirmation before anything is written.
The issue label and type are the team's to add under `board.issue`.

**Everybody's own Telegram bot.** A bot token can be read by one machine only,
so there is no shared bot: each person makes one with @BotFather and puts it in
`~/.config/keepawake/env`. See `bin/keepawake` below.

**Gathering the team's records.** Optional: name a git repository of the team's
in `~/.config/sclaude/metrics-remote`, and each person's cycle records are
published there as `<name>.jsonl`.

## bin/sclaude

The orchestrator of a feature's development cycle on top of `claude`. One
command knows about every feature in progress, remembers which step each is on,
and launches `claude` with the right model, permissions and prompt.

**What it knows about a particular project lives in that project.** The
regression's parts and the commands behind them, the manuals' paths, the
production host, the migrations directory and how they are promoted — all of it
used to be written into the library, so the promise above was not true: a second
repository would have needed the orchestrator edited rather than a file of its
own.

It is now `.sclaude/config.json` in whichever repository sclaude is run
from, and `sclaude new` offers to write one. Most of the answers are already in
the repository — package.json's scripts, the directory layout, whatever the
project keeps about its environments — so the wizard proposes and the human
corrects, in prose rather than as JSON: what is being agreed to is "these
commands will run against production one day", and a wall of braces is not a
thing anybody reads before saying yes.

Every section is optional and **nothing is defaulted**. A repository with no
config still gets the cycle — four steps, a worktree, an issue, a pull request —
and loses only what the config would have described: there is no regression to
gate on, no manuals in front of step 1, no production to ship to, and each of
those says so where it would have acted. A default would be one product's answer
applied silently to another's repository, which is the failure this removes
rather than a convenience it gives up. `sclaude/config.example.json` is the
shape, with every key explained.

That includes the team's GitHub board: which column a started feature moves to,
which one means ready for QA and which one QA ends in, the date fields the Gantt
chart reads, the label and type of a new issue. They were one team's names
written into the library; now they are `board` in `.sclaude/config.json`, the wizard
reads them off the repository's project board and shows them for confirmation,
and a column that is not named is a move that is not made.

The script itself holds the environment, the commands and the argument parsing;
the body is spread across `sclaude/lib/*.sh` and pulled in with `source`. That
is not only about readability: the friction review session edits `bin/sclaude`
while it is executing, and bash reads a script lazily, by offset — an edit in
place shifts everything the process has not read yet. A module pulled in with
`source` is read whole at that moment, and editing it is no longer dangerous to a
running process.

**Keeping the orchestrator current, and whose branch it is on.** Every command
that is about to act (everything but `status`, `dev`, `news` and help) first
fetches `main` and brings it in: a fast-forward on `main`, a merge on a
developer's branch. A dirty tree or a conflict leaves the code as it was and
says so; no network is silent; afterwards the process re-executes itself so it
does not run old code over new files. `SCLAUDE_NO_SYNC=1` turns it off.
The same holds at the end of a step's session, which may have run for hours:
if `bin/sclaude` or a module changed on disk meanwhile, the process hands what
follows claude's exit to the current sclaude (`code_reload`), so an `/exit`
is handled by the new code. `SCLAUDE_NO_RELOAD=1` turns that off.
`MAINTAINERS` names who may commit the orchestrator straight to `main`. The
update leaves everybody on `main`; a branch of one's own, `dev/<name>` (the
name comes from `developer.sh`), is for proposing a change to sclaude, and a
non-maintainer's commits there go out as a pull request (see "Who changes the
orchestrator"). sclaude never pushes its own checkout otherwise: the review
sessions do not commit to it, and a step session that commits there pushes on its own.

| File | What is in it |
| --- | --- |
| `bin/sclaude` | the environment, the `cmd_*` commands, argument parsing |
| `sclaude/lib/ui.sh` | questions to the human, answers, colours |
| `sclaude/lib/io.sh` | the question-answer channel: the same question in the terminal and in Telegram |
| `sclaude/lib/steps.sh` | the table of steps and each one's permissions |
| `sclaude/lib/project.sh` | what the project says about itself, and the wizard that writes it |
| `sclaude/lib/environment.sh` | which database this machine's features work against |
| `sclaude/lib/developer.sh` | who is running it, and whether they maintain the orchestrator (`MAINTAINERS`) |
| `sclaude/lib/doctor.sh` | `sclaude doctor`: what this machine lacks, with the fix for each gap |
| `sclaude/lib/state.sh` | the repository, `.sclaude/local/feature/state.json` and the cycle's record |
| `sclaude/lib/branches.sh` | sorting out branches with nothing left to hold |
| `sclaude/lib/worktree.sh` | preparing a feature's tree and the dev server |
| `sclaude/lib/run.sh` | launching a step, the transitions, the friction review |
| `sclaude/lib/github.sh` | issues and pull requests through `gh` |
| `sclaude/lib/plan.sh` | step 1's plan from its session's transcript |
| `sclaude/lib/deploy.sh` | preview, prod and the cycle's epilogue |
| `sclaude/lib/rollback.sh` | putting production back: the deployment, the down blocks, the incident |
| `sclaude/lib/picker.sh` | choosing with arrow keys: issues, menus, actions |
| `sclaude/lib/abandon.sh` | abandoning a feature: the traces here and on GitHub |
| `sclaude/lib/actions.sh` | the list of actions on a single feature |
| `sclaude/lib/terminal.sh` | recording sclaude's terminal — what it printed, what the person typed — for reading back |
| `sclaude/lib/retro.sh` | the retrospective over a merged feature, right before `sclaude done` removes it |
| `sclaude/lib/*.py` | gathering an issue's context, chain and acceptance criteria, reading migrations' `-- down:` blocks, the cycle's record, and assembling prompts |
| `sclaude/hooks/*.py` | the steps' bans and the friction log |
| `sclaude/prompts/*.md` | the steps' prompts and the shared includes (`_*.md`) |
| `tests/*.py` | benches for the hooks, the prompts, the project's config, the acceptance criteria, the down blocks, the cycle's record, QA's hand-back, the choice of database, the functions whose failures are silent, choosing with arrow keys and the question channel |

```bash
sclaude                 # the menu: features in progress, chosen with arrow keys
sclaude new [name]      # start a feature at step 1
sclaude <name>          # continue a feature from its current step
sclaude status          # a table of every feature and its step
sclaude actions [name]  # every action on one feature in a single list
sclaude dev [name]      # start the dev server (without a name, for the current directory)
sclaude dev --stop [name]  # stop a feature's dev server (without a name, this directory's)
sclaude sync <name>     # merge origin/main into a feature's branch
sclaude news <name>     # what has changed on the pull request
sclaude preview <name>  # ship the branch to preview
sclaude rollback <name> # put production back to the release before this feature
sclaude issue <name>    # create an issue for a feature that has none
sclaude replan <name>   # return a feature to step 1 and plan it afresh
sclaude return <name> [reason]  # send a finished feature back to development (step 4)
sclaude done <name>     # remove the worktree and branches after the merge
sclaude drop <name>     # abandon a feature and remove its traces
sclaude friction <name> # review what got in a step's way and fix the orchestrator
```

**The menu is driven with arrow keys, and a checkbox stands below the feature
list.** Cleared, Enter on a feature continues its current step, as it always
did. Set (with the space bar), Enter opens the list of everything that can be
done with that feature: the same commands as above, but without having to
remember their names.

That is how "drop the feature" left the top list. An action among features was
doubly out of place: first, it is not a feature; second, every subsequent action
would have to be added there too, and the menu would drown. The top list is now
features only, and everything else lives behind the checkbox.

The action list shows only what applies: "what is new in the PR" does not appear
while there is no PR, nor does "clean up after the merge" until the review has
been through. The hints next to the items carry gathered facts — how far the
branch has fallen behind `main`, how many entries are in the friction log, which
tree the dev server was started from — so the list answers questions rather than
asking them.

With no terminal there are no arrow keys either: from a phone the same list
arrives as buttons, one per item. The items' labels go into the question's
channel along with the form, and the bot draws them labelled rather than as the
digits "1 2 3": among the items there is sometimes "drop the feature", and there
is nothing to press blindly there. The numbered list above labelled buttons is
removed in doing so — it would repeat them — while the lines that explain the
question stay.

**The checkbox does not carry over into the chat: an inline keyboard has neither
a space bar nor a state that would survive a press.** What it does have is the
row's width, and the two purposes lay themselves out along it side by side with
no mode at all: in the feature list a feature's row is two buttons — the wide one
drives the step, the narrow one (⚙️) opens the list of actions on the same
feature.

```
┌───────────────────────┬───────────────────┐
│ 12-sample-one-and-…   │        ⚙️         │
└───────────────────────┴───────────────────┘
   └─ drives the step        └─ the action list
```

Buttons in a row always share its width evenly: the Bot API has no notion of a
button's width at all, and there is no making the cog narrow. Three cells instead
of two would give 2/3 and 1/3, but the feature's name would have to be cut in
half between two identical buttons — which would read as two different ones
leading to the same place. So it is split in half, and the name is trimmed to
forty characters so that half a row holds it.

Above the buttons is one line: the repository's name and the number of features.
There is deliberately no `sclaude status` table below it: a feature's name and
step stand on the buttons themselves, there is nothing on a phone to open a
worktree path with, and the branch breakdown is about branches without features,
that is about exactly what is not in this list.

The feature's card stopped being a stop along the way after that — but it has not
gone anywhere: both handlers end with it, showing the outcome, and it also stands
above the action list when that is opened with the cog. A link to the issue and
the PR, the step, the worktree, the session's state — all of it is needed exactly
where one chooses what to do with the feature.

The orchestrator cannot assemble the card: half of it — whether the step's
session is alive — is known to the bot rather than to it. So it does not assemble
but names: a `feature` field with the feature's name is put into the question,
and the bot builds the card from it. The mark lives until the next question and
is cleared with it — the following questions ("remove the worktree?", "merge main
in?") are not about the feature as a whole but about what the human is confirming
right now, and a card above them would be out of place.

In the terminal a line with the issue's and the PR's numbers is printed above the
same list: there is no card there, and half the list's items are about precisely
those.

Four steps, each with its own model, permissions and prompt
(`sclaude/prompts/*.md`):

| Step | Model | Permissions | What it does |
| --- | --- | --- | --- |
| 1. plan | opus / high | `plan` | Discussion; the only writable file is `.sclaude/local/feature/plan.md` |
| 2. code | opus / medium | `auto` | Implementation, checking through chrome-devtools, commits |
| 3. pr | sonnet / medium | `auto` | The manuals and the pull request — calls the `pr` skill |
| 4. review | opus / medium | `auto` | Fixing review comments, the preview deploy |

**The cycle starts from a choice rather than from a name thought up on the
spot.** The list's top item is to type a name by hand, and below it are the
repository's open issues: first those assigned to whoever `gh` is authenticated
as, then all the rest. The arrow keys move through the list, Enter chooses, `q`
cancels. The chosen issue suggests a branch name
(`34-sample-site-and-multiple`) — the suggestion is edited right in the input
line, and a title in a non-Latin script, of which nothing survives `slugify`,
comes down to `issue-27`.

The issue's number lives in `.sclaude/local/feature/state.json` until the cycle ends: step 1
gets the issue itself — the body, the comments, the parent and the links — in the
prompt already, and step 3 ends the pull request's body with a `Closes #N` line,
by which GitHub closes the issue on the merge. No network, no `gh`, no open
issues — there simply will be no list, and the old question about a name
remains.

**Step 1 agrees the acceptance criteria, and the rest of the cycle is measured
against them.** The plan says how the feature will be built; it is rewritten
whenever development deviates from it, and by the end it describes what was done
rather than what was asked for. The criteria are the other half: a numbered list
of statements about observable behaviour, each one checkable on a deployment by
somebody who has not read the code.

They are written before the implementation is worked out and they do not move
with it. That is the whole point — a definition of done that development can
edit is a definition of nothing.

The list lives in a comment of its own on the issue, between
`<!-- sclaude:ac -->` and `<!-- /sclaude:ac -->`, posted by the orchestrator once
the plan is approved. The pair of markers rather than one: the list has a heading
above it and a note below, and QA may add a line of their own under it. QA ticks
the boxes in that comment.

**sclaude never edits an issue's description.** It used to: step 1 kept a
`## User request` section in it, the approved criteria were appended to it, and
the epilogue appended a `Current status` block — to descriptions a human wrote
as well. A developer who opens such an issue cannot tell the task they were
given from what a tool made of it, and so cannot trust that it has not changed
under them. The request, the criteria and the status are three comments now,
each found again by its marker and rewritten in place rather than repeated; a
new issue gets a one-line body saying so. The markers are declared once, in
`issue_comments.py`. Issues from before the change keep their sections: the
criteria are still read from an old body, and nothing is written back to it.

Not a fifth artefact in `.sclaude/local/feature/`: the criteria have to outlive the worktree.
`sclaude done` removes the tree the moment the PR merges, and the question the
criteria answer — did this feature do what it was supposed to — is asked after
that. The plan carries a copy, at its head, so that a step with no network still
has the list; the issue is where a correction lands.

Each criterion is identified `AC1`, `AC2`, and the identifier is what the rest
of the cycle points at:

| Step | What it does with them |
| --- | --- |
| 1. plan | Agrees them with the human, writes them into the issue and puts them at the head of the plan |
| 2. code | Gets them in the prompt; commits name one in a `Requirement:` footer (`Requirement: AC2. <the criterion's text>`); the step's closing report goes through the list criterion by criterion |
| 3. pr | Copies them into the pull request's "Requested by the customer (for QA)" section as an unticked checklist, and uses the footers to find criteria nothing was committed for |
| 4. review, epilogue | Read them; neither writes to the section, and neither ticks a box |

The footer carries the identifier **and** the text. The `pr` skill's convention
is that a `Requirement:` line reads on its own — it is collected into a pull
request people read — and a bare `AC2` would send a reader off to find out what
it meant. The identifier is a prefix to it, not a replacement.

Nothing ticks a box except a person. A tick is the claim that somebody looked at
a deployment and it was right, and that is the one thing in this cycle no part
of it can establish for itself — the same reason `In QA` → `Done` is a human's
move. A step that could tick its own criteria would be marking its own homework.

A feature planned before any of this existed has no section and no criteria.
Every reader handles that by saying so rather than by inventing them: the block
is empty, its line drops out of the prompt, and the step is told to work from
the plan alone. The same holds when there is no issue at all — the criteria then
live only in the plan, and step 3 takes them from there.

**An issue taken into work leaves Backlog and gets a start date.** The board is
the only place that shows what a person is busy with right now and since which
day, and an issue lying untouched all that time while a feature runs on it lies
about exactly that. At the cycle's start sclaude moves it to `In progress` — on
every board it lies on, and only out of `Backlog`: `In review` is set by whoever
sent it for review, `Done` by whoever closed it, and out-arguing them would take
the board's meaning away. An issue in any other column stays where it is, and
that is said out loud. An empty `Start date` field gets today's date; a filled
one is never touched.

Once, at the start, rather than at every step transition: "the work has started"
is one moment of the cycle, and repeating the move would put back into progress
an issue the human had meanwhile moved on themselves.

**A merged pull request closes the bar on the chart.** In the cycle's epilogue,
in the same place where sclaude re-reads the PR's state and sees the merge, an
empty `Target date` field gets today's date. The moment is not chosen at random:
GitHub closes the issue itself by `Closes #N` while sclaude is not running, and
the epilogue is the first place the merge is visible from at all. Today's date is
set rather than the issue's `closedAt`: the bar must end when the work ended, and
those two dates diverge only if the human came back to a postponed epilogue the
next day.

`Target date` specifically, even though by its name it is a planned deadline.
Roadmap — GitHub's Gantt chart — draws a bar from a pair of DATE fields, and
there are exactly two in the repository: `Start date` and `Target date`. The
computed `Closed` that GitHub maintains itself does not enter that choice, so an
issue's closing date is not visible to the chart at all. That is how the field
was filled in by hand: on one issue `Target date` coincides with the day it was
closed. The price of the decision is that the field stops being a plan, and
"we overran" can no longer be seen from it.

The column and the dates are edited differently, although on the board they stand
side by side. `Status` is a project's field, while both dates are fields of the
issue itself (`repository.issueFields`, a mechanism newer than projects), and to
a write in the old way GitHub answers with a plain refusal: "Issue field values
cannot be updated using the updateProjectV2ItemFieldValue mutation". Hence the
different requests: the column on every board item, the dates once on the issue —
which means they will be set even on an issue that is on no board at all. The
`gh` token needs the `project` scope for all this
(`gh auth refresh -s project`); without it there is a warning with that same
line, and the cycle goes on, as it does with any other refusal from GitHub.

**The orchestrator assembles a step's context, not the session.** What can be
gathered deterministically is gathered before the launch and embedded in the
prompt ready-made: for step 1 the issue and both manuals' tables of contents (35
sections instead of two reads of a couple of thousand lines of TSX each), for
step 3 a check on whether `.sclaude/local/feature/` got into the branch's commits, for step 4
the PR's checks and both streams of comments. The session pays tokens for
judgement rather than for gathering.

Step 4 also gets what it could not have worked out itself: a green
Claude review check does not mean the review happened. When the workflow file
diverges from the default branch the action exits with zero in seconds having
checked nothing — and the step once took such a tick for work done. The
orchestrator computes this from the duration and the number of comments and says
so outright.

All of it is a snapshot at the moment of launch, and the prompt says so while
leaving the commands for re-reading: changing the PR's state is exactly what step
4 is busy with. If the gathering did not work, the block is empty and the prompt
keeps its previous instruction inside itself.

**Context is not carried between steps.** Every step is a new session, and
`.sclaude/local/feature/plan.md` serves as the bridge, written at step 1 specifically to be
handed over: compacting a long session costs more and preserves worse than a plan
written for that purpose. Returning to an unfinished step goes through
`--resume`, so an interrupted conversation inside a step is not lost — sessions
are named with a UUID generated in advance (`--session-id`) rather than fished
out after the fact.

The review meanwhile goes on at its own pace while the session is closed: a
reviewer adds a comment, a check turns red from somebody else's merge into
`main`. So the return to step 4 is the only one that does not stay silent: the
orchestrator looks at what has appeared on the PR since the step last worked and
passes it as a prompt to `--resume`. If there is nothing, the return goes
silently, as with the other steps.

The count runs from the transcript's last entry rather than from the step's
start. The difference is not cosmetic: step 4's session lives for hours and reads
the PR all that time, so a comment that arrived mid-work has already been dealt
with — from the start it would look new, and the session would be handed its own
context to work through.

A step is closed by the human rather than by a process that has ended: after
leaving `claude` the script asks whether the step is finished, and while the
answer is "no" the next launch returns to the same step. There is one exception:
**a merged PR closes steps 3 and 4 itself** — the work is in `main`, the review
took place, there is nothing left to check a preview on, and there is nothing to
ask about. So every prompt tells the session what it ends with: say that it is
done and stop — without offering the next step, because agreeing to it inside the
session is impossible anyway, as it begins when the session is left.

**The script creates the worktree, not `claude --worktree`.** The built-in flag
does not carry untracked files across, and without them the worktree does not
work: `.env.local` and `node_modules` are both in `.gitignore`. `sclaude`
branches from a fresh `origin/main`, names the branch `feat/<slug>` (as the `pr`
skill requires) and lays out the environment as symlinks to the main repository —
editing a key reaches every feature at once. `node_modules` is not a symlink but
hard links (`cp -al`): Turbopack refuses to work with a symlink that leads
outside the project, and `next dev` dies at start-up. Links to the same inodes do
not duplicate the data — some ten seconds and almost no space. The directory is
correct while the branch has not touched the dependencies; the script notices a
`package-lock.json` that has diverged and offers an `npm install`.

**Which database a feature works against is the machine's answer, not the
script's.** It used to be the literal `dev`, written into `force_dev` three
times over, and that was right while everybody shared one database. It stopped
being right when a product could offer a Supabase stack running locally: a
developer applying migrations wants a database nobody else is reading, and a
developer working on the interface has no reason to install Docker for one.

So `environment.sh` asks, in order: `$SCLAUDE_ENV`, then the answer this machine
gave before (`~/.claude/sclaude/environment`), and only then the human — once,
with the project's own environment names as the choices. There is deliberately
**no default**: a guess would put somebody on a shared database believing they
were isolated, or on an empty local one believing they were looking at real
data, and both mistakes are quiet ones. A project that declares no environments
simply does not get asked, and keeps whatever its worktree had.

**An environment is a `.env` file.** The product names each one in
`.sclaude/config.json` — `"dev": {"env": ".env.dev"}`, `"prod": {"env":
".env.prod", "protected": true, "siteUrl": "https://…"}` — and that is all
sclaude needs to know (`sclaude/lib/envs.py`). A tree is on the environment
whose file its `.env.local` points at. sclaude switches it itself: `.env.local`
to the file, and on Supabase the CLI linked to the project that file's URL
names, or unlinked for a local stack, since `supabase db push` obeys the link
and not `.env.local`. A build made on the old file is removed with it,
because `NEXT_PUBLIC_*` is inlined. The credentials stay in those files: a
rollback reads production's database URL from production's file, and
whatever sclaude needs and no file holds it asks for at the terminal, every
time, saying that naming the file once spares the question.

**Not every environment is a choice.** A `protected` one is production. A
`deployed` one names deployments rather than a machine — a preview, perfectly
safe to write to, but not somewhere a local dev server and a local browser
suite belong; offered as a choice, it sent the cycle into a regression whose
e2e stage refuses to start. Nor is one whose `siteUrl` is not a loopback
address.

Two things survive from the old behaviour unchanged. A feature is still never
left pointed at production — that is why the function acts rather than reporting,
and protected environments are excluded from the choices, refused from
`$SCLAUDE_ENV`, and refused from a saved answer somebody edited by hand. And an
environment we cannot identify is still treated as protected: the hook that
governs `supabase db push` allows it only on an environment the project does
not protect, and only when `.env.local` and the CLI's link agree — silence is
not permission. A session may not point `.env.local` at production's file
either; a product's own switch script is banned in its policy.

**The orchestrator runs the dev server, not the session.** A `next dev` started
from a claude session stays in its process group and will not let it exit — and
exiting is what a step ends with. `setsid` takes the server into a session of its
own, where it outlives both claude and sclaude itself; it is shut down by
`sclaude done` or by hand through `sclaude dev --stop <feature>`. Chrome, by comparison,
detaches itself — `chrome-debug` leaves it with `PPID=1`, and it holds no
session.

**Every feature has a dev server of its own**, and opens at
`http://<feature>.localhost:3000`. The first start claims a port from
3100–3199 and records it in `.sclaude/local/feature/state.json`, so a feature keeps its port
and its address between runs; a lock keeps two features started together from
claiming the same one. Nobody needs to know the ports: `sclaude-proxy` holds
:3000 and hands each connection to the server its host names (see
[bin/sclaude-proxy](#binsclaude-proxy)). The host rather than only the port is
what keeps two features apart in one browser — cookies ignore the port, so on
bare ports a sign-in on one feature would sign the other one out.

The server is started with `PORT` (where to listen) and `SCLAUDE_DEV_URL` (where
it is reached from). The second is for the app: it cannot see the proxy's name
from where it stands, and an app that builds its sign-in redirects and email
links from its own address would otherwise send them to `localhost:3000`, the
list of features. What the project does with it is its own business — a Next.js
app might turn it into `NEXT_PUBLIC_SITE_URL` in its dev script.

The local regression hands the suite the same address in `E2E_LOCAL_URL`,
with `PORT` and `SCLAUDE_DEV_URL` in case the suite has to start the server
itself, and the feature's name in `SCLAUDE_FEATURE`. One thing to know when a
project's suite talks to that address from Node rather than from the browser:
Chrome resolves `*.localhost` by itself, but Node asks the system resolver,
and a stock WSL Ubuntu answers ENOTFOUND. The suite then has to answer those
names itself, in a test fixture.

Every step starts by printing the address — `Open it at
http://<feature>.localhost:3000` under the step's header — and the feature's
menu shows it beside the dev server's state.

A port found held by a process from another directory is not ours to take back:
the feature moves to another port and says so, rather than offering to kill
somebody else's server.

**Every feature on the local database has a Supabase of its own.** Two features
on one local stack see each other's schema — a migration written in one lands
under the other — and a `db reset` in one wipes the other's data. So when a
feature's environment is the project's local one, `ensure_dev` first starts a
stack for it alone: its own `project_id` (Docker names containers and volumes
after it), its own block of ten ports from 55000, only the containers the
project needs. For a typical web app that is a handful of containers and a
few hundred MB, up in under a minute the first time. It is filled once: with a copy of the main local
database's data when the project sets `copyFromMain` and the main stack is up —
the same people with the same ids, so the objects they own in the bucket are
already there — and with the project's seed otherwise.

The stack runs from `.sclaude/local/feature/supabase/`: a rewritten copy of the tree's
`supabase/config.toml` — the tracked one is never touched, or the ports would
ride into a commit — and symlinks for everything else, so the migrations the
feature writes are the ones its stack applies. Pending migrations, the
feature's and main's after a sync, are applied on every start.

`.sclaude/local/feature/db.env` points the feature at it, and every process sclaude starts
there sources it — the dev server, the local regression, the claude session.
It carries `SUPABASE_WORKDIR`, so a bare `npx supabase db reset` typed in the
session rebuilds this feature's database and no other; a hook refuses
`--workdir` pointing anywhere else. The project decides the rest in
`.sclaude/config.json` under `database.local` (see `sclaude/config.example.json`), and
its own dotenv loading must let an exported value win over `.env.local`.

**Nothing runs that nobody uses.** `sclaude-proxy` starts a stopped feature on
the first request for it — a page says it is starting and reloads until the
feature answers, under a minute with its database — and stops one nobody has
opened for half an hour (`SCLAUDE_DEV_IDLE`), its database with it, data
kept. It never stops a feature while anything is working in its tree: a claude
session, a regression, a shell. The start goes through `sclaude dev
--no-browser` and the stop through `sclaude dev --stop`, so the proxy decides
only when; the PATH they need — nvm's node among it, which systemd does not
have — is the one sclaude last ran with, left in the registry. A start that
fails shows its log and waits for "Try again" rather than looping. The local
regression brings the feature up itself before its parts run.

The stack is removed with its data when the feature is merged or abandoned,
after the project's `teardown` — for example, deleting from object storage
what the feature's people uploaded and the main database does not reference; it is told
which people were copied and when, since their objects are partly the main
database's.
The main repository keeps its own stack, and a feature on the shared cloud
project has none. With Docker down sclaude starts it — Docker Desktop from WSL,
or `docker.service` where sudo needs no password — and waits up to
`SCLAUDE_DOCKER_WAIT` seconds (120); `SCLAUDE_DOCKER_DESKTOP` names the
launcher when it is somewhere unusual. A start that fails is not retried for
ten minutes. Only when Docker stays down does the feature fall back to the
shared local database, and it says so. `SCLAUDE_DOCKER_START=off` starts
nothing.

**The branches are sorted out at every launch** — in the menu and in
`sclaude status`, before choosing what to do. Deletion is offered only for what
has nothing left to hold: a branch with a merged PR and a branch whose remote
copy is gone (GitHub removes it after the merge). Everything else is shown as a
list with no offer — unpushed commits, a PR closed without a merge, a feature
with a live worktree. A `fetch --prune` is done before the sorting, otherwise the
local `origin/*` outlives branches that have long been gone and the check lies.

Once every step has been through, the script prints what is left, separating
**preview** from **prod**. The commands come ready to copy — one per line, with
full paths — while the explanations go on their own line above the block rather
than inside a command.

Preview is deployed **from the main repository with a path to the worktree**:

```bash
cd ~/myapp
vercel ~/myapp-<feature> --project <name>
```

That way rather than a `cd` into the worktree, for two reasons. The link to the
Vercel project lives in the main repository's `.vercel/`, and the worktree has
none — a `vercel` launched from there will create a **new project** instead of
deploying to the existing one (verified; the spare project had to be deleted by
hand). And a `cd` into a directory that is about to be offered for deletion is
contradictory advice.

Prod is `vercel --prod` from the main repository, and if the branch added
migrations, then a `db:promote` first with the whole procedure from the project's
README. Whether a promote is needed the script determines itself — by whether the
branch touches `supabase/migrations`.

**A red production regression rolls production back, before anything is fixed.**
Until now prod went through the same gate as local and preview, and that gate's
loop is run → fix → run: up to two sessions, minutes each, against a live broken
production. The label said production was broken and nothing did anything about
it.

So prod does not use the gate. It runs the suite itself, and on red the order is
reversed: `vercel rollback` first, to the deployment this feature displaced, then
the database as far as it honestly goes, then a check, then the record — and only
then does the cycle return to step 4, where the fixing session now runs against a
production that works.

Which deployment to go back to is **recorded before the ship**, not worked out
after. Afterwards the question is ambiguous and the answer would be a row's
position in a list; before, it is exactly whatever is serving production at that
moment. If the record is missing the rollback says so and names
`vercel ls --environment production` rather than guessing. It also says what else
leaves production with us — main takes several merges a day, so a rollback
routinely carries somebody else's work back out, and that is a thing to be told
before rather than discovered after.

**The schema is the half that cannot be made exact, and it is not pretended
otherwise.** Migrations here are forward-only, production has neither PITR nor
physical backups (`pitr_enabled: false`), and the way back is a commented
`-- down:` block that the project's own documentation calls "comments, not a
mechanism: nothing runs them, somebody reads them". Of the 61 migrations in the
product, 24 have no block at all.

`sclaude/lib/down_blocks.py` reads those blocks and sorts them into four
verdicts, and the two interesting ones are what the file exists for:

| verdict | what it means |
|---|---|
| `runnable` | statements that can be executed as they stand |
| `destructive` | runnable, and it deletes rows somebody will miss |
| `prose` | it looks like SQL and is a note to a human |
| `absent` | no block at all — the loudest of the four |

`prose` is the one that matters. A real block read `drop view if exists
public.v;`, then — inside a comment — "...recreate from the previous schema
snapshot...", then two `grant` lines. Strip the
comments and what is left parses, runs, and leaves production without the view.
An ellipsis where statements should be, a function body in `$$` this reader
cannot split, an English sentence among the statements: any of them refuses the
whole block. The classifier is a heuristic over prose and is written to fail
towards refusing.

The table names every migration, `absent` included — a migration skipped in
silence is how a schema reaches a state nobody can describe. Only the fully
runnable set is offered, all of it or none, with the SQL shown first and the
default **N**: the code half's default is yes because a deploy is undone by
deploying again, and this half's is no because a `delete from` is undone by
nothing. Each reversed migration takes its row out of
`supabase_migrations.schema_migrations` with it — `supabase db push` put it
there, and a row left behind makes every future `db:promote` refuse. The
environment goes back to wherever the tree was whatever happens, including
halfway through a failure: a tree left pointing at production is a machine
whose next `npm run dev` talks to it.

Where the blocks cannot be run the schema stays ahead of the code, and that is
said in those words. One case overrides the "no question asked" rule: a migration
that *took something away* whose block is prose or absent. Then the previous
build would meet a schema it was never written for, and the rollback asks first.

**The check afterwards is a stage of its own, and deliberately not a green
light.** It runs the same suite against the same host, asking whether the release
we went back to is serving properly — never whether the feature is good. That
separation is structural rather than a convention: `regression.prod.status` goes
on describing the feature, so the gate's short-circuit cannot be tripped by it,
`regression_clear_mark` leaves `prod-regression-red` alone, and
`regression_red_label` mints nothing for it. Those three needed no editing when
the stage was added — each already ignores a stage it does not know — and all
three are pinned by tests, because widening any one would quietly turn
"production works again" into "the feature works".

**The incident goes on the feature's own issue, as a comment.** Not a new Bug
issue: `state.json` holds one `issue`, read in nine places, and the labels and
the status section go on the whole chain of parents that number walks — a second
issue has no parents, so the epic above would never learn production broke, and
the fix would be split across two `Closes #N` targets. A new comment each time
rather than an edit, unlike the rolling summary beside it: a rollback is an event
with a time, and a feature rolled back twice has two of them.

The comment says what failed, which deployment is serving now, what became of
each migration, whether the check passed — and that main still holds the commit
that broke this, so the next production deploy ships it again unless the fix
lands first.

**The fixing session is told all of it.** It gets the log of the run that caused
the rollback, which is not the one at the usual path: `regression_run` opens with
`: > "$log"`, and the check after the rollback is a `regression_run`, so by then
`.sclaude/local/feature/regression.log` describes the *previous release passing* — plausible
enough that nobody would question it. The failing run is copied aside first and
the prompt points there. It is also told that the local suite is the check that
matters (production is not serving this branch, so a run against it says nothing
about the fix), that the fix goes the whole way round again — local suite, merge,
preview and its suite, then production — and to close the incident with a second
comment once production is green on the feature again.

By hand the same thing is `sclaude rollback <name>`, and it stands in the action
list once the feature has actually reached production. Sessions cannot do it:
`VERCEL_READS` in the hook is an allowlist and `rollback` is not in it, so it was
already refused — `rollback status` was added beside the other reads, because a
session looking at a red production has a reason to ask whether one is in flight.

**Returning a feature to development is a transition, not a message.** Once the
preview regression is green the issue goes to `In QA` and a systemd timer takes
over: `sclaude-watch` polls the column every few minutes and changes nothing
itself — it looks and it tells. When the column leaves `In QA`, it collects what
was written since the watch began — on the issue, on the pull request, and on
the pull request's lines — and saves it **verbatim** beside the watch file.
Verbatim rather than summarised, because the session is answering a person, and
a paraphrase of a complaint is a poor thing to answer.

Acting on it is `sclaude`'s when the human comes back, and this is where the
mechanism used to stop half-finished. The finding was delivered and ignored:
the watch is armed from `remind_prod`, so a feature waiting on QA always sits at
`step: done` — and `cmd_resume` returned for a done feature *before* it read the
verdict. The one state the block existed for was the one state it could not be
reached in. The comments sat in their file, no session was opened to hand them
to, and the human was shown the production reminder as though nothing had been
said.

Now the verdict is read first, and `returned` puts the cycle back on step 4 in
the same worktree, with the complaint as the session's opening prompt. No
question is asked: QA moving an issue out of that column is a judgement already
made, and "back to the review?" would be asking whether they meant it — the same
reason a rolled-back production is not put to a vote.

The preview's verdict goes back with it, and only the preview's. Entering the
review step already clears the local stage and deliberately spares the deployed
ones, because "a preview verdict that is still true" is worth keeping — after a
hand-back that reasoning inverts, since the preview is exactly what QA looked at
and rejected. Left `passed`, the gate short-circuits on it and the fix returns
to QA without the deployment ever being checked again. Production's verdict is
left alone: if it shipped, that run was about a deployment the comment did not
concern.

Nothing moves the column back. It returns to `In QA` the ordinary way, when the
fix's own preview regression goes green — doing it "helpfully" here would be
fighting the board with the person who just moved it.

**Step 4 runs one review round per session.** On one pull request five rounds of
fixes ran in one conversation, and every file each fix read stayed in its
context. The session now fixes through subagents and keeps only the
coordination; and once the automatic review closes every thread it fixed and
posts new ones, it writes `.sclaude/local/feature/review-round` and stops. A session cannot
clear its own context, so the orchestrator does: a watcher started beside every
review session sees the file and ends the `claude` process (found by
`--session-id`/`--resume` and its id), the run is recorded in the issue as
"fixes confirmed", and a fresh session opens. Its snapshot of the pull request
lists only the review threads still open — the resolved ones are counted, not
repeated — so the new round starts with the new findings and nothing else.

**Leaving step 4's session does not close it on its own.** After the session exits, the step closes only once the automatic review has finished with the pushed head and left nothing open: no check running or red (the findings check among them) and no unresolved review thread (`pr_context.py --close`). Otherwise sclaude waits for a running review, says what is open, and offers the session back; closing anyway is a second, explicit answer.

**Every commit a step's session makes names it.** sclaude launches claude with `core.hooksPath` pointed at `sclaude/githooks` through `GIT_CONFIG_*` in that process's environment only; its `commit-msg` adds `Sclaude-Session: <id>` — the id the issue's table and `claude --resume` use — at the end of the trailer block, and every hook there then runs the project's own hook of the same name. A row in the issue finds its commits with `git log --grep=<id>`. Commits made by hand are untouched.

**QA is one reason to return a feature, not the only one.** One pull request
reached `done` on an automatic review that had read a third of it; the ten real
findings a second review found could only be sent back by moving the card as
though QA had. `sclaude return <name> [reason]` is that same return under its
own name: it saves the notes (the reason first), moves the card from `In QA` to
`In progress` so the board does not claim QA has a feature being fixed, records
that column so the timer does not announce the move, and leaves the `returned`
verdict for `cmd_resume` to act on — the board path and this one meet there.
Either way the state says `reopened_by: returned` and `reopened_since`, and the
session is told to read the issue and the pull request for itself from that
moment: the notes are a copy, and a reply added since is part of what it has to
answer. Only a finished feature can be returned; one still on a step is told to
say what is wrong where its session reads it.

The four lines that put a step back — clear its `done`, clear its `finished`,
name the new current step — are now `step_rewind_to` in `steps.sh`, shared by
this, by the regression's rewind after a red deployed stage, and by
`sclaude replan`. They differ only in which steps they name: one, one, and all
four.

Each is offered as a question, and on a "yes" the script runs the commands it
showed itself, one at a time, printing each before running it. What is shown and
what is run are the same list: a divergence here would be worse than no hint at
all. The chain breaks off at the first error, so that a promote that did not go
through does not drag a deploy along with it.

The order is **preview → QA → merge → prod → the outcome into the issue →
clean-up**, and none of it is arbitrary. The preview and its regression come
first because they are what make the branch worth merging at all; offering the
merge before them would be offering to merge something nobody has checked. QA
comes next and before the merge, because a verdict given after the merge can no
longer hold anything back. The merge is the human's step, so it is offered
rather than taken, and only once QA has passed the issue and GitHub says the way
is clear. Production follows the merge because `vercel --prod` ships what is in
main.

Step 4 used to close only on a merged pull request, and that ran this order
backwards: the preview and "In QA" live after step 4, so the branch was merged
first and QA looked at main afterwards. Step 4 now closes on a green regression
with the pull request open, and sclaude waits in two stages, each saying which
event it is waiting for:

- **Waiting for QA** (`qa_wait`, every `QA_POLL` seconds). QA checks the
  acceptance criteria in the issue and moves it to `Done`. `Done` moves on to
  the merge. `In progress` or `Backlog` is a hand-back: QA's comments are
  collected and the review session opens with them, in the same run. Any other
  column is unexpected, and sclaude asks for the status to be set properly and
  keeps waiting. Unticked criteria do not block `Done` (GitHub Projects cannot
  refuse a status change); sclaude names them, and the merge question names
  them again.
- **Waiting for the merge** (`merge_wait`, every `MERGE_POLL` seconds), after
  the merge question was declined or GitHub named something in the way.

**The pull request carries the same story on the board.** Step 3 opens it as a
draft, and sclaude assigns it to its author and puts it in the milestone of the
issues it closes. An issue with no milestone has no say. If two issues are in
different milestones, sclaude asks which one to use (`pr_setup`, `pr_milestone`).
It stays a draft until QA has moved *every* issue it closes to `Done`. Then
`pr_qa_handoff` marks it ready, moves it to `Backlog`, clears its assignees and
posts a `<!-- sclaude:merge-ready -->` summary. The summary holds what the merger
needs without opening the issue: the preview, QA's verdict, how often the work
came back, the acceptance criteria, how many review findings were found and how
many are still open, whether the review finished on this head (zero findings
mean nothing if it did not), the checks and the regressions. This happens once
per head; a later accepted head rewrites the summary in place. After the merge
the pull request goes to `Done` (`pr_board_set`).

The hand-off does not need anybody at a terminal. sclaude runs it while it
waits for QA. The QA timer runs it too, through `sclaude _handoff <feature>` in
the project, whenever it finds the issue in `Done`. It keeps trying on every
sweep until the hand-off succeeds, because a PR that closes two issues becomes
ready when the second issue reaches `Done`, and that issue is not the one the
timer watches. It stops trying once the PR is merged, closed or gone. A
lock on the feature keeps the two from handing over the same PR twice. The
timer acts on the hand-off's exit code, not on its wording. Telegram reports the
outcome: the PR is ready, it is still waiting on a named issue, or a step
failed and will be retried. A hand-off that fails partway records nothing, so
the next try repeats every step; each step is safe to repeat. This is the one thing the timer changes; everything
else it only reports.

Ctrl-C leaves either wait and loses nothing: `sclaude <feature>` comes back to
the same place, and the QA watch keeps looking in the meantime.

The clean-up is last, and it moved there deliberately: it removes the worktree,
and everything above it may still need one. A red production regression opens a
fixing session in that tree; a rollback records the failing log inside it; the
section written into the issue is assembled from `state.json`, which lives
there. So the tree survives until there is nothing left that could want it — and
even then the script does not advise the clean-up but asks, because the worktree
and the branches disappear irreversibly.

**The last thing the cycle does is write the outcome into the issue — and into
all of its parents.** A closed sub-issue changes an epic's state, but the epic
says nothing about it: to understand where it stands, the children had to be
opened one by one. Now every level of the chain has a `Current status` comment
headed by `<!-- sclaude:status -->`, and a separate session writes it — "where this epic stands now" is a judgement, not a
substitution. The chain is walked upwards up to ten levels, with protection
against a loop: `parent` comes from GitHub rather than from our own state.

The same comment may carry a second section, `Current behaviour`: how the
product actually behaves where that is no longer what the description says.
`Current status` is the management view, `Current behaviour` the product one,
and a description is never edited, so this section is the only place its drift
is recorded. On the feature itself it is written when the build left the
description behind — through the `User request` comment, a QA hand-back, a
review decision — and for that the feature's discussion goes into the session
along with the chain. On a parent it is written when the feature is a change
request to it: a child that renames or regroups the fields the parent
describes. A child that only adds — more detail, a field more — leaves the
parent without one, and the rewrite climbs the chain only as far as the
contradiction reaches. An existing section is read and rewritten, never
started over, so what earlier children established in it stays; and it
describes what is on `main`, which the session checks with `git grep` and
`git show` against `origin/main` rather than by touching the working tree.

The `deployed-preview` and `deployed-prod` labels appear alongside — the script
sets them itself, by how the preview and prod blocks ended, and sets them on the
whole chain. By how they *ended*, which means the regression and not the upload.

The two stages are not symmetrical, and the asymmetry is the point. A preview
that deployed and then failed its suite gets **no** `deployed-preview`: it would
be read as "it is there and it works", and the fixing session that follows a red
run pushes again, so the label would name a commit that is already leaving. A
production that failed its suite keeps `deployed-prod`, because that label claims
only that the code reached production — and it did, which stays true whatever the
suite then found.

What says a stage is broken is a mark of its own: `preview-regression-red` and
`prod-regression-red`. These are the only labels here that come off again — the
regression gate removes the stage's mark the next time that stage passes, from
the whole chain it went on to. They can, where `deployed-*` cannot, because
nobody writes them by hand: the script sets them from a suite result and clears
them from a suite result. A mark saying "broken" that could never be cleared
would be sitting on the epic a year after the fix shipped.

`deployed-preview` follows what is true rather than what happened today: a
preview already on hosting from an earlier run, with a suite that has passed,
carries the label even though nothing was deployed this time. It used to be read
off "did we deploy in this run", which cost the label outright whenever a red run
was followed by a redeploy by hand.

The section says the rest in words, which is the one place a qualifier fits — and
it names the deployed commit, so that a claim outlives the worktree that recorded
it. The labels are created on demand if the repository does not have
them yet. If prod is postponed there will be no `deployed-prod` label, and the
section will say the feature is waiting for the merge: a section that cannot be
trusted is worse than none. `deployed-locally` is deliberately absent: it would
be true of every issue while `next dev` is alive and false the moment the laptop
is closed — and besides, nobody but the machine's owner can open such a
deployment.

The summary's **Friction** column says what became of the review for each step
and each fixing session. Six answers, because one dash used to stand for four
different things and a reader could not tell them apart — a step nobody had
reached yet looked exactly like a step that ran into nothing. Each value is
written by the orchestrator at the moment it happens; none is inferred when the
comment is assembled:

| Value | What it means |
|---|---|
| `queued` | The cycle has not reached this step. Nobody has looked yet — not "there was no friction". |
| `nothing` | The log was empty, so no session was launched. The ordinary case: most steps run into no ban worth reporting. |
| `` `id` open `` | Interrupted, with a conversation to return to. It holds the cycle until `sclaude friction` or `sclaude reset` closes it. |
| `` `id` stalled `` | `claude` exited at the door. The id names a transcript with nothing in it, so there is nothing to resume — clear it rather than return to it. |
| `` `id` fixed `` | The review ran and committed to the orchestrator: `HEAD` moved while it was open. |
| `` `id` reviewed `` | The review ran and changed nothing — it read the entries and found every ban deliberate. |
| `` `id` unread `` | Closed by hand through `sclaude reset`. The entries stayed in `.reviewed` with nobody reading them. |

The **Status** column says how each fixing session ended. It was a dash for
every one of them until it became clear what that cost: a stage with four
sessions showed four identical cells, and one of those four was the one that
made it green. A fixing session has no step status — it is not a step — but it
does have an outcome, and the orchestrator knows it exactly:

| Value | What it means |
|---|---|
| `green` | The re-run passed after this session. It is the one that fixed the stage. |
| `red` | The session finished and the stage failed again. The attempt was counted. |
| `blocked` | The cause was outside the branch. Nothing was changed and the attempt was given back — deliberately not `red`, or the row numbers would disagree with `attempts`. |
| `stalled` | `claude` exited at the door, leaving no assistant record. Nothing ran, so the stage was not left red by it. |
| `open` | Interrupted, with a conversation to return to. |
| `—` | No record: the feature predates the field. Nothing is guessed backwards from how the stage ended. |

The outcomes live in `regression.<stage>.fix_status`, space-joined and aligned
with `fixes` position for position — `state_set` writes scalars, which is what
made `fixes` a string too. Writer and reader derive the row from the same place.

The id is the review's own session, kept under `was` once the review closes, and
`claude --resume <id>` in sclaude's checkout opens it again. It is a separate field
from `session` on purpose: `run_friction` reads `session` to decide whether to
resume, and an id left there would send the next review into the closed
conversation instead of starting a new one.

A line under the table appears when a step ran in the background. By design that
cannot happen — a step with no terminal is refused — so it only shows on
features started by an earlier `sclaude`, and it explains why the cycle stopped
there: a backgrounded step never reaches `after_step`, so it got no next step
and no friction review.

**Underneath stands a second table: what the friction reviews actually changed.**
The column above says *that* a review fixed the orchestrator; it cannot say what
the fix was, and a reader was left to open sclaude's checkout and work out which
commits fell between two steps of a feature. So `run_friction` keeps the
instruments `HEAD` from either side of a review that committed — it already
compared the two to decide whether to push — and the summary turns that range
into commit subjects with `git log`. The range is honest by construction:
while a review is open, the only things running in that tree are the review's
own session and read-only git calls.

A row is one commit, and the step is named once per review, so a review with
four commits reads as one piece of work rather than four unrelated ones.

| Verdict | What it means |
|---|---|
| `lifted` | A restriction was loosened or removed. |
| `deliberate` | Nothing changed, on purpose: every entry was a ban working as intended. |
| `mixed` | Both happened in the same review. |

The verdict is the one thing no amount of reading the commits recovers. `git
log` describes a lift and is silent about the opposite — a review that read
every entry, found each ban correct and changed nothing leaves no commit at
all, and so had no row here. The review therefore says it in words: the two
prompts ask for a last line, `sclaude-verdict: <kind> — <clause>`, and
`friction_verdict` reads it back out of the review's transcript once the
session exits. It is read rather than written by the session on purpose — the
review works in sclaude's checkout with the feature's tree outside its scope, and
widening that scope so it could write one bookkeeping file would hand the one
session that edits the orchestrator a writable path into the product.

Only the kinds in the table are accepted, so a model quoting the instruction
back cannot land a word in the issue as though it were a decision; the last
line wins, so a review interrupted and resumed reports what it finally left
behind. A review that printed no line keeps its commits and shows a dash — the
table behaves as it did before the verdict existed.

The section is absent entirely when no review has committed or left a verdict,
which is what every feature already in flight will show: their reviews recorded
neither. That is accepted rather than repaired, for the same reason the
`queued` back-fill was: inferring the values now would put back exactly the
guessing this removes.

The status is a comment, not a part of the description, on every issue in the
chain — whoever wrote it. There used to be one concession to the rule "we do not
touch somebody else's body": this section was appended to it. It is gone; a
`Current status` a human wrote into a description stays there, and the session
takes what is still true from it into its comment.

It is deliberately not done as a fifth step: by that minute the worktree and
`state.json` have been removed by the clean-up, there is nowhere to record a
step's completion, and a `cd` into the feature's tree would not work. In its
construction this is closest to the friction review — a session outside `STEPS`,
with a prompt of its own, launched from the main repository.

The state lives in `.sclaude/local/feature/state.json` in the feature's worktree. Vercel's CLI
never reads `.gitignore`, so before every deploy (a preview from the worktree,
production from the main repository) sclaude makes sure that tree's
`.vercelignore` names `.env`, `.env.*` and everything sclaude writes into the
project: `.sclaude/local/feature`, `.vercelignore` itself, and `.sclaude`, where the terminal
recordings are kept. It only appends what is missing, and a `.vercelignore`
the project tracks itself is left to the project, with a warning for what it
lacks; `sclaude doctor` checks the same in advance. One list in
`sclaude/lib/scratch.sh` serves git and Vercel both, and there is nothing to
configure. These are the script's internal files: they do not outlive the
feature and have no business in the repository — the script hides them through
`.git/info/exclude`, which is machine-local and shared by every worktree, rather
than through a rule in `.gitignore` that would have to go through a PR. They are
not shown in the clean-up: the question "there are uncommitted changes in the
worktree" must mean you are losing work rather than that the script left its own
rubbish.

The directory goes away with the worktree on `sclaude done`, which checks the
fact of the merge with GitHub and asks before every deletion.

**One line survives it: the cycle's own record.** Everything the cycle measures
about itself is in that `state.json` — when each step started and finished, how
many fixing sessions a red regression needed, which friction reviews committed
and which found every ban deliberate — and all of it used to die with the tree.
So the questions the record answers could not be asked at all: is the cycle
getting faster, which step actually holds it up, are two fixing attempts enough
or generous.

Just before the clean-up, and before the worktree in `sclaude drop` too, the
state is flattened into one record and appended to
`~/.claude/sclaude/cycles.jsonl`. Outside every repository, for the reason the
epilogue's state and the QA watch are: `$REPO` is the product's tree, where
steps 2-4 work and `git add -A` is an everyday thing, and a service file with
timings would ride into somebody else's commit.

Append-only, JSON Lines. A finished feature is a fact, and in a format where the
last line is the only writable one a machine dying mid-write cannot corrupt the
nineteen above it. Each line parses on its own, so the file is read with `jq`
without loading all of it:

```bash
jq -s '[.[] | select(.outcome == "done") | .steps.code.seconds] | add / length' \
  ~/.claude/sclaude/cycles.jsonl
```

Deliberately not aggregated by sclaude and deliberately not a database. Twenty
lines of JSON answer a question in one command; a schema would have to be
decided now, before anybody has looked at the data, and that is the wrong order.

Each record names who ran the cycle (`developer`, from `developer.sh`; `null`
where nobody could be named). A team that wants its cycles in one place names a
git repository of its own in `~/.config/sclaude/metrics-remote`; each
developer's records are then published there as `<developer>.jsonl` after every
record — one file per person, so publishing never conflicts, and a second
machine of the same person adds its lines rather than replacing the first's.
Not this repository, on purpose: the records carry the team's feature names and
paths, and instruments is shared by everybody who installs it. No file, no
publishing.

`outcome` is what keeps a finished feature and an abandoned one apart — `done`
against `dropped` — and they must never be averaged together: an abandoned
feature's timings describe a decision to stop, not a cycle that ran its course.
It is recorded rather than inferred, because a feature dropped at step 4 looks
exactly like one that finished.

Throughout, a value that is not known is `null` rather than zero. A step nobody
reached and a step that took no time are different facts, and the second is what
a zero would average in as. The whole call is best-effort down to the `|| true`:
a record that cannot be written is one measurement lost, and losing it must not
stand in the way of cleaning up a merged feature.

**Work that was decided against is cleared away by `sclaude drop`.** `done` is
the clean-up after success: the PR is merged, the code is in main, all that is
left is sweeping. Here it is the opposite, and an abandoned feature has five
traces: the worktree, the local branch, the branch in `origin`, the pull request,
the issue. Forgetting any of them means leaving rubbish that will be remembered
in a month and not understood.

One command for all five — but not one question for all five, as in `done`. There
the human agrees to a clean-up after the merge, where there is nothing to lose;
here every "yes" destroys something nobody asked to have destroyed, and their
costs differ: a worktree with uncommitted work cannot be recovered by anything,
whereas a closed issue can be reopened. So each action is asked about separately,
in order from the irreversible to the reversible, and refusing one does not
cancel the rest: sometimes the branches need tearing down while the issue stays.

What exactly the feature has, the script works out before the first question and
shows as a table: asking "remove the worktree?" without showing that a branch, a
PR and an issue stand behind it means leading the person blind. It asks GitHub
about the PR's and the issue's state rather than trusting `state.json`: they may
have been closed by hand, and offering to close what is closed is noise people
learn to answer without looking. The PR and the issue are not deleted but closed:
deleting a PR through the API is not possible at all, and a closed pair remains
the history of the decision not to do this work. The issue is closed as "not
planned" — in a milestone's report what was abandoned must not look like what was
done.

In the menu it is the third item, after "new feature", and it deletes nothing
itself — it drops into a separate list where the feature is chosen once more,
with a "none, go back" item last. Adjacent numbers, one of which continues the
work while the other destroys it, are a mistake waiting for its chance; the
submenu is the protection against a finger that missed.

## skills/pr

A Claude Code skill: it closes work through a pull request by GitHub flow rather
than by pushing to `main`. It is symlinked into `~/.claude/skills/pr` and called
by hand — `/pr` — or programmatically at sclaude's step 3, whose prompt tells it
outright to run it. Claude does not pick it up by itself on finishing work: that
is written in the skill's description rather than forbidden by a flag.

A `feat/…` branch, commits in Conventional Commits format (the type is
mandatory — commits that reached the branch from elsewhere are checked too), the
project's checks, then `gh pr create`. The PR's body: **Summary** — what changed;
**Requested by the customer (for QA)** — an aggregated list of what the customer
asked for, in terms of requirements and observable behaviour, with no
implementation details and only what this PR closes; then **How to verify** and,
if there is anything to say, **Notes**.

The manuals (`manuals` in `.sclaude/config.json`) are updated here too, in one step after
the feature is approved, rather than as development goes. The skill does not
merge the PR or deploy.

## bin/sclaude-proxy

One address per feature: `http://<feature>.localhost:3000` reaches that
feature's dev server, whatever port it really listens on. Chrome resolves every
`*.localhost` name to the loopback by itself, so there is nothing to configure
in DNS or a hosts file.

```bash
systemctl --user enable --now sclaude-proxy.socket   # install.sh does this
```

- `<feature>.localhost:3000` — that feature's server; a server that is not
  running gets a page saying how to start it.
- `localhost:3000`, or the machine's tailnet address — the list of features.
  From another device, where there is no `*.localhost`, choosing one sets a
  cookie and the bare address serves that feature from then on.
- `/__sclaude/` on any host — the list again.

It keeps no state. sclaude links `~/.claude/sclaude/dev/<feature>` to the
worktree, and the worktree's `.sclaude/local/feature/state.json` holds the port. Routing is
decided once per connection, by its first request, and after that bytes are
only copied — which is also why Next's HMR WebSocket works through it with no
code of its own. Next 16 already trusts `*.localhost` as a dev origin, so a
project needs no `allowedDevOrigins` for it.

The socket listens on every address, as the `next dev` that used to hold :3000
did: the Windows browser reaches it through WSL's localhost forwarding and the
phone through the tailnet. Those are the only two it answers. The proxy checks
each connection's address and lets in loopback (the forwarded Windows browser
arrives as `::1`) and Tailscale's ranges, `100.64.0.0/10` and
`fd7a:115c:a1e0::/48`. Anyone else who can reach the port, on a café's Wi-Fi or
on a LAN under WSL's mirrored networking, gets `403` and cannot list, open or
start a feature. `SCLAUDE_PROXY_ALLOW` replaces the list with comma-separated
networks of your own.

A `npm run dev` started by hand in the main repository finds :3000 taken and
moves to another port. `sclaude dev` in the main repository gives it a port of
its own and the address `main.localhost:3000` instead.

## bin/chrome-debug

Starts Chrome (from the Playwright build in `~/.cache/ms-playwright/`) with a
remote-debugging port that Claude Code's chrome-devtools MCP server connects to.
Under WSLg it also brings the window back to the right monitor.

```bash
chrome-debug                     # bring the window forward, opening it if needed
chrome-debug http://localhost:3000/some/page   # the same, and go to that URL
chrome-debug --stop              # close it
chrome-debug --keep              # skip the restart a misplaced window would need
chrome-debug --tab http://a.localhost:3000/   # a background tab, window left alone
```

Variables: `CHROME_DEBUG_PORT` (9222 by default), `CHROME_DEBUG_PROFILE`
(`~/.cache/chrome-devtools-mcp/visible-profile` by default). The log is at
`~/.cache/chrome-devtools-mcp/chrome.log`.

This command is rarely typed by hand now: before a step `sclaude` starts the
browser itself, along with the dev server (`ensure_chrome`), opened at the
feature's address. A browser that is already up is never brought forward —
otherwise every start of a step would yank the window from under whoever is
looking at another feature. It gets the feature in a background tab
(`--tab`), and not even that when a tab of the feature is already open.

## bin/wsl-update

The daily update of the tooling in WSL2: apt (unattended-upgrades), nvm/Node,
the npm globals, Claude Code with its plugins, Playwright's Chromium,
code-server; and a report on outdated dependencies for the projects listed in
`~/.config/sclaude/projects`, one path per line (a report only, it does not
touch the repositories; no file, no report).

The local Supabase stacks, when Docker is running (it is never started for
this): their images are pinned by the Supabase CLI — and for a linked project
postgres, gotrue, postgrest and storage are pinned to what production runs — so
they are not bumped past it. A stack created before the CLI moved on is reported
with the command that restarts it; images no container uses and no CLI pins are
removed once they were pulled more than 30 days ago (a stopped stack has no
containers, and its images must survive the night). The stacks sclaude starts
for a feature are left to sclaude.

The Windows side is reported, never updated: a newer stable WSL than the one
installed (`wsl --update` shuts the VM down, this script with it, so it is run
from Windows by hand), and the applications `winget upgrade` lists (an installer
may ask for elevation or close an application in use).

Started by the `wsl-update.timer` timer (10:00 local time, `Persistent=true`
catches up on what was missed). To run it by hand: `wsl-update`. The logs are in
`~/.local/state/wsl-update/`.

```bash
systemctl --user status wsl-update.timer
systemctl --user start wsl-update.service   # run it now
journalctl --user -u wsl-update.service
```

## bin/keepawake

Keeps the machine from sleeping while there is someone to work — so that work
can carry on from a phone while the laptop stands closed. Under WSL the machine
is Windows, held by `KeepAwake.ps1` on the Windows side; on plain Linux it is
this machine, held by `keepawake-linux` (see "keepawake on plain Linux" below).
Deciding is the same on both; only the holding differs.

**Holders come in two kinds, and the difference is what they prove.**

*Hard* ones mean a person is at the machine right now: a live SSH session, an
open code-server tab, traffic going through the tailnet. Sleep does not come at
all, the timer is not counted with them, and no questions are asked.

*Soft* ones mean work is going on but there may be nobody around: a busy
`claude`, a running dev server, a running code-server service. They give an hour,
and half an hour before the end the bot asks whether to extend.

**Soft ones divide in two again, and that is not a formality.** `claude`,
`sclaude` and VS Code prove work: the transcript, the step's state and the edit
journal grow because somebody — a person or an agent — is doing something. The
dev server and the code-server service prove only their own existence: the dev
server's log grows from the requests of a forgotten open tab (an HMR reconnect,
the page polling its own API), and the service is alive simply because it was
switched on once. Their sign never goes out, so the deadline moved an hour
forward every minute: the laptop did not sleep for days, the "it will sleep in
half an hour" warning never had time to reach the threshold, and the question
about forgotten holders is asked only about hard ones. Such holders now hold only
when there is somebody alive at the machine — recent input in a terminal or a
code-server tab, or noticeable load. This does not lose the person: at the laptop
itself Windows does not sleep because of the mouse and keyboard, while from a
phone the hard holders hold — tailnet traffic, an SSH session, a code-server tab.

With nobody there, Windows sleeps by its own settings.

Extending does not accumulate: while a single holder is alive, the deadline is
always "an hour from now". Otherwise three short connections would leave the
laptop awake for three hours after all of them had closed.

Once an hour, if hard holders are holding while there are no traces of work — an
hour without a single keystroke and an unoccupied machine — the bot asks whether
a session has been forgotten and offers to stop the services or to sleep.

**"An hour without a single keystroke" is counted by both of a terminal's
stamps.** A tty has two, and neither can be trusted on its own: `mtime` is moved
by a program's **output**, so a forgotten tab with `tail -f` or a dev server
prints into the void and looks like work — because of which the question about a
forgotten session was never asked at all, in exactly the case it was created for.
`atime` is moved by reading from the terminal, that is by what a person typed,
but an automaton feeding input into a pty moves it too. So the smaller of the
stamps is taken: nobody is there only when both are silent. This does not lose a
live session — what is typed moves `atime`, and the shell's echo immediately
moves `mtime`, so for a person at work both are fresh at once. The rule does not
extend to code-server's heartbeat: that is an ordinary file, and `mtime` there
means exactly what it says.

| File | What is in it |
| --- | --- |
| `bin/keepawake` | the holder detector, `status`, manual extension |
| `keepawake/state.py` | the state under `flock`, atomic writes, the "should we hold" decision |
| `keepawake/telegramd.py` | the bot: the menu, the half-hour warning, the commands |
| `keepawake/i18n.py` | the bot's strings in Russian and English |
| `keepawake/docs.py` | the docs the bot prints on a button |
| `bin/code-server-start` | opens the repository chosen in the bot |
| `bin/code-server-proxy` | the localhost forward, address from code-server's config |
| `windows/KeepAwake.ps1` | `SetThreadExecutionState` and the polling loop on the Windows side |
| `windows/KeepAwake.vbs` | a hidden manual start, should it be needed |
| `bin/keepawake-windows` | starts and stops the Windows side from WSL |
| `systemd/keepawake.timer` | the minute-by-minute polling of holders |
| `systemd/keepawake-telegram.service` | the bot's daemon |
| `systemd/code-server.service` | VS Code in the browser, tailnet only, on demand |
| `systemd/code-server-local.socket` | the same server for the Windows browser |

```bash
keepawake status          # why the laptop is (not) sleeping — the whole picture
keepawake extend 3600     # extend by hand
keepawake release         # let go immediately
```

**The counting happens in WSL, the executing in Windows.** The state file lies on
the Windows drive (`C:\Users\<user>\.keepawake\state.json`) because PowerShell
reads it — and reads it at the moment WSL may already have stopped. The other
direction, reading from Windows over `\\wsl$`, breaks exactly when it is needed.

Time in the file is whole Unix-epoch UTC seconds only. `date +%s`, `time.time()`
and `[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()` give the same integer, and the
comparison does not depend on the switch to summer time — otherwise on the last
Sunday of October, when the local hour repeats twice, the system would be an hour
out.

**Fail-safe everywhere.** The Windows side keeps the system awake only if the
file was read, the schema's version is its own, the deadline is in the future and
`updated_ts` is younger than fifteen minutes. The last is the protection against
"WSL died and the file remained": the detector runs once a minute and refreshes
the stamp even when nothing has changed. Any failure means "release": failing to
sleep is a battery flattened overnight, sleeping too early is pressing a
button.

**A button carries the deadline it was sent for** (`extend:1757000000`). Without
that, a press on yesterday's notification would extend the hold at an arbitrary
moment the next day; the window is now checked, and a stale button answers with
an alert.

**The `sclaude` cycle can be driven from the bot too.** Not by emulating a
terminal but by dividing the roles: the orchestrator stays the orchestrator, the
bot shows its questions and passes the answers on, and the step's own
conversation goes to the Claude mobile app.

A question lives in a file rather than in a process (`sclaude/lib/io.sh`): the
orchestrator lays it out in `.git/sclaude/ask.json` and waits for an answer from
two places at once — the terminal where the question was asked, and the channel.
Whoever answers first has answered. Hence **hot switching**: a feature was begun
at the laptop, reached "Is step 'development' finished?", was left — and answered
from a phone; the live process in the terminal prints the answer after the prompt
and carries on by itself. The same in reverse: an answer in the terminal clears
the question, and the bot removes the buttons on the next turn.

**At the laptop a question arrives silently.** It is sent anyway — one can step
away mid-step, and then the message is already waiting in the chat — but while
the person is sitting at that very terminal it does not buzz the phone
(`disable_notification`): the question is on the screen as it is, and that is
where it is answered.

Presence is measured by the terminal of the process that asked the question: its
`pid` already travels in the channel, and the controlling terminal is found from
it. Not "the freshest terminal of all", as in the `bin/keepawake` detector — a
forgotten neighbouring tab has nothing to do with this question. We look at
`atime` rather than `mtime`, and that is not pedantry: a tty's `mtime` is moved
by a program's **output**, so `ask` itself, having printed the prompt, would
declare the person present — every question in a row would go out silent, those
asked from the bot included. `atime` is moved only by a successful read from the
terminal, that is by what was really typed, and idle turns of `read -t` do not
touch it. The threshold is five minutes: reading a long question or thinking over
an answer, a person stays silent for a minute or two without going anywhere. Any
uncertainty is resolved in favour of sound: no `pid`, no terminal (a launch from
the bot goes through `setsid`), `/proc` will not read — the message arrives as
usual.

The question declares the answer's form itself — as `ask`'s third argument
rather than by parsing the prompt: guessing from `[y/N]` would diverge from the
code at the first edit to the text. `yn` and `yn:yes` give two buttons (the first
being the one Enter gives in the terminal), `pick:N` gives a button per option
and for a large N asks for a number as text, as in the terminal; with no form the
answer arrives as an ordinary message. What was printed before the question
travels with it: a "Publish?" without the list of commands `run_block` shows in
the terminal would be agreement to who knows what.

A step with no terminal is refused. It used to go into the background instead
(`claude --bg`, the conversation continuing in the Claude app over Remote
Control), and that was written for an entrance nobody uses: ssh through Termius
gives a real tty, so does the terminal inside code-server, and nothing
automated starts a step at all — `sclaude-watch` only polls GitHub and prints
`sclaude <slug>` for a human to run, while the Telegram bot is read-only by its
own documentation. So no terminal means `sclaude` was invoked by something that
was never meant to invoke it: `ssh host sclaude <feature>` without `-t`, a
systemd unit, a cron line, a pipe. Carrying on there is worse than stopping —
the step runs where nobody is watching, `after_step` is never reached, and the
next step and the friction review never happen, while the orchestrator returns
as though it had done its work. It now says all of that and starts nothing.

The two entrances do not get in each other's way. An open step session cannot be
opened a second time — the check asks `claude agents --json` rather than looking
for a process in `ps`: a session started without arguments does not show its UUID
in the command line, and the old `pgrep` did not see it at all. The channel is
also occupied by one orchestrator: whoever comes second gives way and asks the
terminal, otherwise it would overwrite the first's question and that one would
hang, waiting for an answer that would no longer go to it. A question that
outlived its owner (killed with Ctrl-C, an ssh session dropped) is not shown by
the bot — it checks the `pid` and removes it.

Termius and code-server have not gone anywhere: a full-screen `claude` is real
there, and for long stretches of work by hand that is still more convenient.

**The bot's menu** — extending and status, a card for `chrome-debug` and the
features (each with a link for the phone, its address for the laptop, and
buttons to open it in the laptop's Chrome or stop it), a code-server card with
links, the `sclaude` section (repository →
features → feature, with the chosen repository remembered) and "Docs": seven
sections on what each tool is for, how to use all this, how to install it from
scratch and what to do when something fails.

The `sclaude` section has "New feature" and "Continue", and a feature's card
shows what its step is busy with right now: 🟢 running, 🟡 waiting for an answer,
⚪ idle, ⚫ not started. There are GitHub links there too: for a feature, the
issue and the pull request from its `state.json`; for a repository with no
features, those parsed from the last commit. A merge commit names only the PR
("Merge pull request #N"), while the issue hides a line deeper, in its body
(`Closes #N`) — the card fetches both, because the question "why was this done"
leads to the issue more often than to the diff. The state is asked of
`claude agents --json`, so "waiting for an answer" is a real `blocked`, that is
the step is stalled and will not move without a person. The "Continue" button on
a running step does not start a second conversation but says where the first is
open. The language is taken from the interlocutor's `language_code` — Russian for
a Russian client, English for everyone else.

**code-server starts on demand.** It does not start at boot and goes out by
itself after 59 minutes of idling (`idle-timeout-seconds`), because autostart
would bring back to life what had just been deliberately shut down. It is started
by a button in the bot, by following the local link (the socket will wake it) or
by `systemctl --user start code-server`.

It has two addresses, and that is not duplication: Tailscale runs inside WSL, so
the phone sees the tailnet address while Windows itself does not — it is not in
the tailnet. For Windows there is the forward to localhost.

### keepawake on plain Linux

There is no Windows side to read the state from drive C, so the state lives in
`~/.local/state/keepawake/state.json` and `keepawake-linux.service` holds the
machine itself: every 30 seconds it asks the same `should_hold` KeepAwake.ps1
mirrors, and while the answer is yes it keeps a `systemd-inhibit` lock. Its log
is `hold.log` beside the state, in the same words the Windows side uses, so
`keepawake status` reads either.

logind's default policy lets a service outside a login session — which a user
service under linger is — block **idle only**. That already stops the idle
timer from suspending the machine under remote work; a closed lid or an
explicit suspend still sleeps, and the hold log says so once.

`install.sh` offers to fix that on plain Linux, and only there: it explains
when the rule is worth having (a laptop you close while working from a phone),
shows the command that removes it, and asks. `./install.sh --polkit` adds it
without asking, `--no-polkit` skips the question. To turn it off later:

```bash
sudo rm /etc/polkit-1/rules.d/49-keepawake.rules && systemctl --user restart keepawake-linux.service
```

By hand, the rule is this (it needs sudo, like the SSH setup below):

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

### Two Windows traps

Both cost debugging and both are pinned down in the code.

`schtasks` refuses with "Access is denied" on any logon trigger: `ONLOGON` counts
as privileged, while PowerShell started from WSL is unprivileged. So systemd
inside WSL brings the Windows side up (`keepawake-windows`) — and shuts it down
when the distribution stops: while WSL is not running there is nobody to hold
for, and there must be no deviation from Windows' own rules.

PowerShell 5.1 reads UTF-8 **without a BOM** as ANSI. Any non-ASCII byte then
decodes to something else, string lengths drift apart, the parser loses block
boundaries, and the script dies on `Missing closing '}'` at a spot where
everything is written correctly. `install.sh` copies the file with a BOM — do not
change that to a plain `cp`.

### Configuration

Telegram: create a bot with `@BotFather`, find your `chat_id` (message the bot
and open `https://api.telegram.org/bot<TOKEN>/getUpdates`), fill in
`~/.config/keepawake/env` following the `keepawake/env.example` sample and set
mode `600` — the daemon refuses to work if the file is readable by the group or
by everyone.

```bash
cp keepawake/env.example ~/.config/keepawake/env
chmod 600 ~/.config/keepawake/env
$EDITOR ~/.config/keepawake/env
systemctl --user enable --now keepawake-telegram.service
```

SSH for Termius is the only part that needs `sudo`, which is why it is not in
`install.sh`:

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

`ListenAddress` is the tailnet address (`tailscale ip -4`) rather than `0.0.0.0`: it is stable, and
binding to it rules out accidental reachability from a café's network.
`enable-linger` is mandatory: without it `systemctl --user` stops along with the
last session, that is the daemon dies as soon as you close the local terminal —
in exactly the scenario all this was made for.

Generate the key **on the phone** (Termius → Keychain → Generate) and carry only
the public half into `~/.ssh/authorized_keys`; the private one must not leave the
phone. In Termius: host `<node>.<tailnet>.ts.net` (the MagicDNS name `tailscale
status` shows), port 22, your user name.

Port forwarding and a firewall rule are not needed: Tailscale runs inside WSL, it
has an address of its own in the tailnet, and traffic from the phone arrives
straight at `tailscale0`, bypassing the Windows network stack. `netsh portproxy`
is needed in the opposite case — when a client knocks on the Windows address.

code-server opens in the phone's browser at `http://<tailscale-ip>:8080` (the
password is in `~/.config/code-server/config.yaml`).

```bash
python3 tests/keepawake.py          # the test bench
journalctl --user -u keepawake-telegram.service -f
```

## statusline.py

Claude Code's status line. Three zones: on the left the sclaude session and
the path, in the middle the branch, the session's name and the worktree, on the
right the model, the effort, the context fill and the limits.

The first element is the name sclaude gave the session, without its slug:
`1-plan`, `2-code`, `3-pr`, `4-review`, a later round as `4-review(2)`, a fixing
session as `4-fix-preview`, then `4-friction`, `5-epilogue`, `6-retro`. The
round always comes last, and the first has none (`session_label` in
`sclaude/lib/steps.sh`). The slug is left out because the folder or the branch
shows it already. Any other session keeps its name in the middle zone, and
shows nothing on the left.

The terminal's width is handled by a ladder of degradation: first the weekly
limit goes, then the worktree, the session's name, the icons, the bars. In the
narrowest variant the sclaude session and the path remain — which kind of work
the session is busy with matters more than the directory.
Once the fields are chosen, the gaps between them widen as far as the width
allows, so on a wide terminal the slack is spread out rather than all left in
the middle. Spacing never costs a field.

`settings.json` points at `~/.claude/statusline.py`; `install.sh` puts a symlink
there, and that symlink is what makes the setting work after the machine is
reinstalled.

## githooks/commit-msg

Rejects a commit whose `Requirement:` footers will not reach git as trailers.

Git gathers trailers only from a message's last paragraph, and only if every line
in it is itself a trailer. There are two ways to break that, and both have
happened: a blank line inside the block (only what comes after it then becomes
trailers) and, conversely, no blank line before the block (a line of the body
then ends up in the paragraph, and git discards the paragraph entirely). In both
cases the commit goes through, `git log` looks right, and the requirements
disappear — and the PR the `pr` skill assembles from them is left without its QA
section.

The hook does not parse the format itself but asks git what git will see:
`git interpret-trailers --parse` — the same code path as `%(trailers:…)` — and
compares the number of footers written with the number that survived.

`install.sh` points at this directory through `core.hooksPath` (a project can
have `npm install` do the same).
