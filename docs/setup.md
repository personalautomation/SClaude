# Setting up

What a machine needs, and how sclaude is installed on it.

## The environment it is built for

sclaude was built and is used every day on one stack: a Next.js app on Supabase,
shipped through Vercel, developed on Windows under WSL2. Nothing in it names a
particular product, but this is the stack where every part of it works, and the
further a product is from it, the more of sclaude it simply goes without.

**Required.** sclaude does not run without these:

| what | why |
|---|---|
| Linux or WSL2 with systemd, or macOS with Homebrew | the commands are bash; the QA watch and the per-feature proxy are systemd user units, or launchd agents on macOS. On WSL, systemd has to be switched on (`systemd=true` in `/etc/wsl.conf`); `install.sh` says how if it is not. On macOS, see [below](#on-macos) |
| git, python3 | everything sclaude does goes through them |
| the `claude` CLI, with auto mode and Bash allowed | every step is a Claude Code session; without those settings steps 2–4 stop on permission prompts |
| a GitHub repository and `gh` 2.48 or newer, logged in with the `project` scope | issues, pull requests, the board and QA's verdicts all live on GitHub |

**Recommended.** Each one turns on part of the cycle; without it that part is
skipped, and sclaude says so where it would have acted:

| what | what it gives you | without it |
|---|---|---|
| a dev server that listens on `PORT` — `npm run dev` unless the product names its own in `.sclaude/config.json` (`commands.dev`); for a Node app on WSL, Node through nvm, which `wsl-update` keeps current | a dev server per feature at its own address, Claude checking its work in a browser | no dev server or browser check; the cycle still runs |
| a test suite the product names in `.sclaude/config.json` | the local, preview and production test gates | no test gates |
| an automatic Claude review on the product's pull requests (a `claude-code-review.yml` workflow — start from [sclaude's reference one](#what-sclaude-reads-from-your-review-workflow)) | the findings step 4 works through | step 4 has no findings to work from |
| a GitHub project board | the issue moving through `In progress`, `In QA`, `Done`; QA's hand-back | QA's verdict cannot be read from the board |
| Vercel (`vercel` CLI, logged in) | previews and production from sclaude, production rollback | no preview, QA on a deployment or production step |
| Supabase | per-environment databases, migrations promoted and rolled back with care | no database handling |
| Docker (on WSL, Docker Desktop: sclaude starts it itself when it is not running) | a Supabase database of its own for every feature | features share the local database |
| Chrome from Playwright (`chrome-debug`); on WSL its window comes up on the Windows desktop through WSLg | Claude sees the feature in a real browser | Claude cannot look at what it built |
| the chrome-devtools MCP server, attached to `chrome-debug` (below) | the tools Claude drives that Chrome with; sclaude allows them in every step, and step 2 checks its work through them | Claude cannot look at what it built |
| `script` and `tmux` | the terminal recording the retrospective reads | the retrospective works without it |

The MCP server is connected once, for every project, and attaches to the
browser `chrome-debug` opens rather than starting one of its own:

```bash
claude mcp add --scope user chrome-devtools -- npx -y chrome-devtools-mcp@latest --browserUrl http://127.0.0.1:9222
```

**Optional.** For working away from the laptop:

| where | what | what it gives you |
|---|---|---|
| the machine | [Tailscale](https://tailscale.com); on WSL, installed inside WSL, not on Windows | features, SSH and code-server reachable from the phone over your tailnet |
| the machine | a Telegram bot of your own | sclaude's questions and keepawake on the phone |
| the machine | code-server | an editor in the phone's browser |
| the phone | the Tailscale app, signed in to the same account | the phone in the tailnet: features at their addresses, SSH, code-server |
| the phone | [Termius](https://termius.com) | SSH into the machine, to run sclaude and Claude from the phone |
| the phone | Telegram | the bot: questions, status, the feature cards |

With Tailscale Funnel the bot's menu, a feature and code-server open as a
Telegram Mini App on a phone without Tailscale (see
[below](tools.md#the-bot-as-an-app-in-telegram-with-no-tailscale-on-the-phone)). On WSL,
keepawake keeps Windows from sleeping while you work from the phone.
`./install.sh --extras` sets up the machine's side of the bot, keepawake and
code-server; Tailscale, code-server itself and the phone's apps you install
yourself ([keepawake, Configuration](tools.md#configuration)).

Claude Code plugins are your own choice; sclaude needs none of them. The
Vercel plugin is handy in sessions, while sclaude itself deploys and rolls back
through the `vercel` CLI. The Supabase plugin may be installed too: sclaude's
Supabase rules (`sclaude/policy/supabase.json`) deny its tools that apply
migrations, deploy edge functions or create, pause, restore and delete
projects and branches: a schema change goes as a migration file, through the
cycle.

`sclaude doctor` checks the required part, and inside a product the parts that
product uses.

## What sclaude reads from your review workflow

Step 4 is driven by what the automatic review on GitHub leaves on a pull
request, and sclaude reads it by fixed names and phrases. Start from the
reference workflow, `sclaude/templates/claude-code-review.yml`: copy it to
`.github/workflows/claude-code-review.yml`, give the repository the
`CLAUDE_CODE_OAUTH_TOKEN` secret, and adapt the prompt, the model and the effort
to taste. Whatever you change, keep what this section lists; the strings in
quotes are matched verbatim, and the reference workflow marks each one
**Coupled**. A workflow that writes none of it still works with sclaude, only
blindly: step 4 then opens a session on every pull request, whatever the
review found.

**The review job.** Its check name contains the word "review", and its own name
or its workflow's contains "claude". That is how sclaude tells the review from
the build, and from Vercel's "Preview Comments". Skip the job by its condition
when the pull request carries the `no-review` label: sclaude puts that label on
for a project reviewed on this machine. Run it again on a `/review` comment, the
way to ask for a review by hand.

**The findings check**, written after every review run, under exactly this name:

    Counts Green/Red sign based on open review comments — whole PR (no AI)

Write it twice under that name: once as a check run, which is the record, and
once as a commit status, which is the signal (a check run may land in a suite
that GitHub hides). On the check run:

| field | what sclaude reads in it |
|---|---|
| `conclusion` | `success`: nothing of the review is open on the whole pull request. `failure`: findings are open, or the review did not finish |
| `external_id` | `reviewed` only on a head the review actually read; the next run reads from there. `not-reviewed` otherwise: green when the review skipped on purpose (step 4 then closes, saying the pull request was not reviewed), red when it did not finish |
| title, findings open | "N unresolved review finding(s)…", with one link per finding in the summary, to its thread (`…#discussion_r<id>`). Once every listed finding is resolved, by the review or by hand, sclaude knows the red is stale and asks for no session |
| title, findings not threaded | contains "posted as a comment, not as threads": findings no thread stands for. Always work for a session, and sclaude digs them out of the job log for it |
| title, review not finished | contains "review did not finish": the review handed back before the code-review skill and every agent it started had finished. sclaude runs the review again on that head once by itself, then asks whether to go on with the head unreviewed. It opens no session, since there is nothing to fix. Findings posted as a comment win over it: a title carrying both reads as findings not threaded, so write that one when both hold |

**Findings are review threads.** Each finding is an inline review comment
posted by a Bot account, on its file and line. sclaude counts the open threads,
hands them to the review session, and reads replies that begin with two marks:
"Resolved automatically: " (the review closed the thread as fixed) and
"Left as it is" from anyone but a Bot (the author declined the finding). A
review run on this machine may also reply "Still open: " on a thread it finds
fixed only in part; that reply decides nothing. A
finding the review could not post as a thread may go into one ordinary comment
by the login `claude`.

**Minor findings are marked.** A nit, or a bug that was there before the
change, is posted like any finding but opens with the line
"<!-- sclaude:minor nit -->" or "<!-- sclaude:minor pre-existing -->". It is
open work like any other; the mark tells step 4's session how much it weighs.
A workflow that marks nothing has every finding treated as important.

**The job log.** Keep the action's full output in the log (`show_full_output:
true`). sclaude reads it to tell why a review did not run: Claude's usage limit
and when it resets, Actions minutes or billing, a runner that could not reach
the network. Each of those reruns the review once the limit resets, stops step 4, or moves
the review to this machine — never to a fixing session. It also reads the code-review skill's own result line,
for findings that reached no thread.

Once a run has answered, sclaude keeps the review's conversation from its job's
log: it shows on the review map which files the run opened, and the files the
commits since the last review changed that the run never opened are read by
one short pass on this machine. Nothing more is needed for it than the full
output. The run's answer comes from its last result's structured output:
`found`, `resolved` (a list), `unthreaded`, `full_rerun` and `complete`, as the reference
workflow's JSON schema names them; where its delta began, from the
`base_sha` of the `.claude-review/open-findings.json` it hands the review
(the journal's previous head when there is none).

## Installation

```bash
git clone git@github.com:personalautomation/SClaude.git ~/sclaude
cd ~/sclaude && ./install.sh
```

The checkout may live under any name. `install.sh` can be run as often as you
like: it links sclaude's commands into `~/.local/bin`, the skills into
`~/.claude/skills` and the status line into `~/.claude`, installs and enables
sclaude's systemd units (launchd agents on macOS), and wires up this
repository's git hooks. A unit an update of sclaude changes is rewritten by the
next sclaude command by itself.
`~/.local/bin` has to be in `PATH` (it usually is). Without a working systemd
on Linux it lays out the links, enables nothing, says what to do, and exits
with an error.

By default that is sclaude alone. The machine tools that grew up next to it —
[keepawake](tools.md#binkeepawake) and its Telegram bot, code-server,
[wsl-update](tools.md#binwsl-update) — come with `./install.sh --extras`. A machine
that already has them keeps them on a plain re-run. A Mac takes all of them but
wsl-update and the Windows side, which are WSL's.

### On macOS

sclaude is written for bash 4 and the GNU tools, and a Mac has bash 3.2 and
BSD's. So on macOS it runs with Homebrew's builds ahead of the system's:
`install.sh` checks for them first and, at your yes, installs what is missing:

```bash
brew install bash coreutils gnu-sed grep gawk findutils util-linux
```

Homebrew itself has to be there already ([brew.sh](https://brew.sh)). The
`sclaude` commands put those builds first on `PATH` by themselves, for
everything they start, so your shell's `PATH` and its own `bash` stay as you
have them; only the GNU directories go first, never Homebrew's `bin` as a
whole, so a Node from nvm still wins over Homebrew's.

In place of the systemd units, launchd agents in your login session, written
into `~/Library/LaunchAgents` and loaded by `install.sh`:

| agent | what it does | Linux's |
|---|---|---|
| `sclaude.watch` | asks GitHub what QA has done, every five minutes | `sclaude-watch.timer` |
| `sclaude.proxy` | every feature's dev server at `<feature>.localhost:3000` | `sclaude-proxy.socket` |
| `sclaude.gate` | the phone's entry behind `tailscale funnel`: launchd listens on `127.0.0.1:3001` and starts the gate on the first connection | `sclaude-gate.socket` |

Their logs are in `~/Library/Logs/sclaude/`. `sclaude doctor` says whether
each is loaded and whether a formula is missing; `./install.sh` again loads
an agent that is not and reloads one whose file changed since it was loaded
(by itself, or by an update of sclaude), and leaves the rest running. An agent it keeps off — the proxy or the gate while another process
holds its port — is not left in `~/Library/LaunchAgents`, where launchd would
load it at the next login: the note says what holds the port, and
`./install.sh` once it is free installs the agent.

With `--extras`, more of them:

| agent | what it does | Linux's |
|---|---|---|
| `keepawake` | counts what holds the Mac awake, once a minute | `keepawake.timer` |
| `keepawake.hold` | holds it with a power assertion while there is work ([keepawake on macOS](tools.md#keepawake-on-macos)) | `keepawake-linux.service` |
| `keepawake.telegram` | the Telegram bot; written only once `~/.config/keepawake/env` has its token and your chat id ([Configuration](tools.md#configuration)) | `keepawake-telegram.service` |
| `keepawake.code-server` | code-server on the repository chosen in the bot; loaded, and started only by the bot's button | `code-server.service` |

A closed lid is held only with a sudoers rule for `pmset`, which `install.sh`
offers, shows the undo for, and adds at your yes (`--lid` without asking).

code-server comes from Homebrew (`brew install code-server`) or its standalone
install in `~/.local`, run by keepawake's own agent, which the bot starts and
stops — not with `brew services`, which neither the bot nor keepawake sees —
and configured in `~/.config/code-server/config.yaml` as on
Linux. A Mac has no `localhost:8080` forward: that one is for a Windows
browser outside the tailnet, and a Mac's browser opens code-server at its own
address. The bot's links and the funnel need the `tailscale` command on
`PATH`, which the Tailscale app installs from its settings (or
`brew install tailscale`). Docker Desktop is started when a feature's database
needs it, as on WSL.

It asks three questions about this machine, once (a re-run keeps the answers):

- **Updates of sclaude.** `notify` (recommended): each start lists what is new
  on this repository's `main`, and `sclaude update` takes it once you have read
  it. `auto`: each start takes it by itself; when your own commits or edits
  in the checkout stand in the way, the start says a newer version is there
  and the command that takes it, and goes on. Commits of yours that `main`
  already has — a pull request of yours taken in — no longer hold it back,
  unless you work through a fork. `off`: sclaude never fetches itself.
- **Sending fixes of sclaude back.** The retrospective and the friction reviews
  can fix sclaude itself and send the fix to this public repository (see "When
  a session finds a bug in sclaude"). `ask`: you see the commits and the files,
  and nothing goes out without your send ("Send, reopen or drop?"). `send`: it
  goes out by itself. `off`: no session changes sclaude on your machine.

- **When a fix may name your product.** Before a fix of sclaude is sent it is
  searched for your product's name, numbers and paths. `ask`: the matching
  lines are shown with "Send, reopen or drop?", and nothing goes out without
  your send. `auto`: they are shown, and it goes out without the question.
  `off`: the same as `ask` — your send, given after seeing them, is yours.

`./install.sh --update=notify|auto|off --contribute=ask|send|off
--leaks=ask|auto|off` answers them without asking. Run without a terminal, the installer leaves them unset, and
unset means "ask": the first start asks about updates, and every send asks.
The answers live in this checkout's git config (`sclaude.update`,
`sclaude.contribute`, `sclaude.leaks`). Apart from these, what sclaude sends goes to your own
services: your product's GitHub and deploys, and Telegram if you set the bot up.

Then run `sclaude doctor`. It lists what the machine still lacks and the command
that fixes each gap. Run inside a product, it also runs the checks the product
asks for in `.sclaude/config.json`.

## Updating and removing

### Where updates come from

sclaude updates itself from the `main` branch of **the repository your checkout
was cloned from** (its `origin`), by the rule you chose at installation
(`sclaude.update`: each start takes it, or says what is new for
`sclaude update`, or never looks).

> **Installed from a fork, sclaude takes nothing from this repository.** Your
> checkout's `origin` is then the fork, so every update comes from the fork's
> `main`: a fix or a new feature published here reaches you only once
> somebody brings it into the fork (GitHub's "Sync fork", or
> `git pull https://github.com/personalautomation/SClaude.git main` and a push
> to the fork). The fixes your sessions make to sclaude go to the fork too,
> not here. To stay on this repository's updates, clone this repository
> itself; `sclaude propose` makes a fork for your pull requests by itself when
> you cannot push here, and leaves `origin` where it is.

A unit or agent the update changed is rewritten by the next sclaude command by
itself.

### Removing sclaude from a machine

There is no uninstaller; these steps undo what `install.sh` did.

1. **Finish or drop the features in progress** — `sclaude done <name>` after a
   merge, `sclaude drop <name>` otherwise. Each removes the feature's worktree
   (beside the product, `<product>-<feature>`) and its own database stack in
   Docker.
2. **Stop the background units.** On Linux and WSL:

   ```bash
   systemctl --user disable --now sclaude-watch.timer sclaude-proxy.socket sclaude-gate.socket
   # with --extras, also:
   systemctl --user disable --now keepawake.timer keepawake-linux.service \
     keepawake-windows.service keepawake-telegram.service wsl-update.timer \
     code-server-local.socket code-server.service
   rm ~/.config/systemd/user/{sclaude,keepawake,wsl-update,code-server}*
   systemctl --user daemon-reload
   ```

   On macOS, for each agent in `~/Library/LaunchAgents` whose name starts with
   `sclaude.` or `keepawake`:

   ```bash
   launchctl bootout gui/$(id -u)/sclaude.watch   # and the others, by name
   rm ~/Library/LaunchAgents/sclaude.*.plist ~/Library/LaunchAgents/keepawake*.plist
   ```

3. **Remove the links.** The commands in `~/.local/bin` that point into the
   checkout (`sclaude`, `sclaude-notify`, `sclaude-watch`, `sclaude-proxy`,
   `chrome-debug`, and with the extras `keepawake*`, `code-server-*`,
   `wsl-update`), the skills in `~/.claude/skills` (`pr`, `sreview`,
   `scontrib`, `sdemo`, `isleep`) and `~/.claude/statusline.py`.
4. **Take sclaude out of Claude Code's settings.** In `~/.claude/settings.json`,
   remove the hooks that run `skills/isleep/night.py`, and the status line if
   you pointed it at `statusline.py`.
5. **Remove the lid rule, if you added one**: `sudo rm
   /etc/polkit-1/rules.d/49-keepawake.rules` on Linux, `sudo rm
   /etc/sudoers.d/keepawake` on macOS. On WSL with the extras, delete
   `C:\Users\<you>\.keepawake`.
6. **Delete what it kept**: `~/.claude/sclaude/` (your cycle records),
   `~/.config/sclaude/`, `~/.config/keepawake/` (the bot's token), and the
   checkout itself.

### Removing sclaude from a product

What sclaude left in a product's repository:

- the `.sclaude/` folder — `config.json`, `team/` and `people/` are committed,
  `local/` never is;
- `.vercelignore`, when sclaude wrote it;
- a few lines in `.git/info/exclude` marked "Written by sclaude";
- the refs `refs/sclaude/demo/*` and `refs/sclaude/dropped/*`;
- on GitHub, the labels it added (`no-review`, `deployed-preview`,
  `deployed-prod`) and the review workflow, if you added it from sclaude's
  template.

Commit the removal of the committed ones. The comments, board moves and commit
trailers it wrote stay in the product's history as its record.
