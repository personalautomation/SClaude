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
| Linux or WSL2, with systemd | the commands are bash; the QA watch and the per-feature proxy are systemd user units. On WSL, systemd has to be switched on (`systemd=true` in `/etc/wsl.conf`); `install.sh` says how if it is not. macOS is not supported |
| git, python3 | everything sclaude does goes through them |
| the `claude` CLI, with auto mode and Bash allowed | every step is a Claude Code session; without those settings steps 2–4 stop on permission prompts |
| a GitHub repository and `gh`, logged in with the `project` scope | issues, pull requests, the board and QA's verdicts all live on GitHub |

**Recommended.** Each one turns on part of the cycle; without it that part is
skipped, and sclaude says so where it would have acted:

| what | what it gives you | without it |
|---|---|---|
| a Node app with `npm run dev` that listens on `PORT` (Next.js is what it is built on); on WSL, Node through nvm, which `wsl-update` keeps current | a dev server per feature at its own address, Claude checking its work in a browser | no dev server or browser check; the cycle still runs |
| a test suite the product names in `.sclaude/config.json` | the local, preview and production test gates | no test gates |
| an automatic Claude review on the product's pull requests (a `claude-code-review.yml` workflow) | the findings step 4 works through | step 4 has no findings to work from |
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

## Installation

```bash
git clone git@github.com:personalautomation/SClaude.git ~/sclaude
cd ~/sclaude && ./install.sh
```

The checkout may live under any name. `install.sh` can be run as often as you
like: it links sclaude's commands into `~/.local/bin`, the skills into
`~/.claude/skills` and the status line into `~/.claude`, installs and enables
sclaude's systemd units, and wires up this repository's git hooks. Re-run it
after pulling a change to a systemd unit. `~/.local/bin` has to be in `PATH`
(it usually is). Without a working systemd it lays out the links, enables
nothing, says what to do, and exits with an error.

By default that is sclaude alone. The machine tools that grew up next to it —
[keepawake](tools.md#binkeepawake) and its Telegram bot, code-server,
[wsl-update](tools.md#binwsl-update) — come with `./install.sh --extras`. A machine
that already has them keeps them on a plain re-run.

It asks three questions about this machine, once (a re-run keeps the answers):

- **Updates of sclaude.** `notify` (recommended): each start lists what is new
  on this repository's `main`, and `sclaude update` takes it once you have read
  it. `auto`: each start takes it by itself. `off`: sclaude never fetches
  itself.
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
