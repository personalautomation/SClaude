# For a team

instruments is meant to be installed as it is by a small team with a product of
its own — several developers, each on their own Linux or WSL machine, with no
server in between.

**Nobody forks it.** Everybody installs from this repository, and every sclaude
command that is about to act first looks at the latest `main` — takes it, with
updates on `auto`, or lists it for `sclaude update`, with `notify` — so a fix
reaches the whole team at their next command, or their next update. What is the team's own lives elsewhere:

| what | where |
|---|---|
| the orchestrator, its prompts, `MAINTAINERS` | here, one copy for everybody |
| the product and the team's process: tests, manuals, production, migrations, the GitHub board, its maintainers, where its records are gathered | `.sclaude/config.json` in the product's repository, committed |
| the team's sclaude rules for the product | `.sclaude/team/` in the product, committed, written by its maintainers |
| one developer's sclaude rules for the product | `.sclaude/people/<name>/` in the product, committed |
| what one machine keeps about the product: a feature's working files, terminal recordings | `.sclaude/local/` in the product, never committed, never deployed |
| the person: name, database choice, the Telegram bot, their cycle records | `git config sclaude.developer`, `~/.config/sclaude/`, `~/.config/keepawake/env`, `~/.claude/sclaude/` |

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
values. The committed file is what the team recommends; a choice you make in
`sclaude config` stays on your machine, in `.sclaude/local/config.json` outside
git, so your `ship: auto` is not everybody's. Every section is optional and nothing is assumed: without a test suite
there is simply no test gate, and sclaude says so where it would have acted.

**Who changes the orchestrator.** `MAINTAINERS` lists the git addresses allowed
to commit sclaude straight to `main`. Everybody else commits by hand and runs
`sclaude propose`: the commits move to a branch of their own, `dev/<name>`, and
go out as a pull request — pushed here if you may push, otherwise through a fork
`gh` makes for you once. You keep using this repository; the fork is only how
the pull request travels. Without `MAINTAINERS` everybody is a maintainer, which
is what a copy used by one person wants.

**When a session finds a bug in sclaude.** No session sclaude runs changes
this checkout, which every other session runs from, and none pushes it on its
own — the one exception is the 🛠 workshop you open yourself (`sclaude
workshop`), which works in a worktree of its own and publishes on your word: the
repository is public and the session has read your project. It fixes sclaude
in the feature's workshop instead, a copy of the checkout at
`.sclaude/local/instruments` that every session of the feature shares:

- a step's session does not change sclaude: it writes what got in its way in
  the feature's friction log, and the friction review after it fixes sclaude;
- the retrospective and the friction and monthly reviews start in plan mode,
  so the plan you approve is your yes: they run `sclaude core-open` and open
  the workshop without a question;
- the session commits there, reviews its change — `/sreview` if you are a
  maintainer, any review you like otherwise — and runs `sclaude core-ready`.
  Answering "stop" to sreview's "go on?" counts as a finished review.

When the session ends, sclaude publishes the change itself. It looks for your
project's details in it — the project's name, issue or pull-request numbers,
paths of its files — and asks you before it sends anything that matches; it
runs the tests the change touches, a line on the screen for each as it
runs; with sending on `ask` (the default) it shows you the commits and the
files and waits for your yes, and while you are away it waits for you; then it pushes a maintainer's change to
`main` as one commit, and sends anybody else's as one pull request per
feature. A change left uncommitted or unreviewed is not published: sclaude
offers you the session back to finish it, at once and when you next open the
feature, and says what is missing. Red tests right after the session send
that session back by themselves, told which tests failed, twice at most. A publication that stops — red tests, no network, a refused push —
is tried again, quietly, every time you open the feature; only your own "no"
— to the project's details, or to sending it — holds it, until a session
rewords the change or you run `sclaude core-send` in the feature's tree.
With sending `off`, sessions do not open the workshop at all, and what they
found stays in the feature's friction log. A list
of matches too long for a phone question is asked at the terminal only. A
workshop goes with its feature; a change in it never published
stays on its branch in this checkout, and the clean-up names it. When the
retrospective's change reaches this checkout, `sclaude done` carries on with
the clean-up in a fresh run of the new code by itself.

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

**Who you are.** The part of your global `git config user.email` before the
`@` (an address set in sclaude's own checkout signs your commits to sclaude and
does not rename you; it counts only when no global one is set), or
the name you set with `git config --global sclaude.developer <name>` (and
`SCLAUDE_DEV` overrides both for one shell). Prefer the git setting to an
environment variable: the Telegram bot and the background units see it too. It names your branch, marks your records, and is
passed to the product's tests as `SCLAUDE_DEV`, so tests that create data on a
shared database can mark it as yours and clean up only their own.

**Everybody's own Telegram bot.** A bot token can be used by one machine only,
so each person makes their own with @BotFather. See [keepawake](tools.md#binkeepawake).

**Gathering the team's records.** Optional: name a git repository of the team's
under `metrics` in the product's `.sclaude/config.json`, and each person's cycle
records of that product are published there as `<name>.jsonl`. Only that
product's: somebody working on two products publishes each to its own team.
