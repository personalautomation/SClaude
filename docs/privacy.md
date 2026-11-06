# Privacy: what leaves your machine

sclaude has no telemetry. It sends nothing to its authors: no usage
statistics, no crash reports, no analytics. What it sends goes to services you
already use, under your own logins, with three exceptions that touch this
public repository, each a setting you choose when you install. Phone access,
which you turn on from the bot, adds the DNS lookups and the funnel that puts
the phone's gate on the internet, both described below.

**From this repository to you: updates** (`sclaude.update`). Code merged into
`main` here runs on your machine only as you choose: `notify` lists the new
commits at each start and waits for `sclaude update`, `auto` takes them at
each start, `off` never fetches.

**From you to this repository: fixes of sclaude** (`sclaude.contribute`).
The retrospective and the friction reviews may fix sclaude itself. Such a
fix is sent here as a commit on `main` (maintainers) or as a pull request from
a fork `gh` makes in your account. It carries the diff and its commit
messages, your git name and email, your developer name in the branch, and a
link to the Claude session that made it. All of it is public. `ask` shows
you the commits and the files and waits for your yes, `send` sends without
asking, and `off` keeps sessions from changing sclaude at all. `sclaude
propose` sends your own commits, only when you run it.

**Your product's details in such a fix** (`sclaude.leaks`). Before a fix is
sent, sclaude searches it for your product's name, issue and pull-request
numbers, and paths of its files. The search is a heuristic and will not
catch everything: a table name or business logic described in a commit
message can still get through. `ask` shows the matches and waits for your
yes, `auto` sends with them, and `off` holds the fix until a session
rewords it. A question about them that nobody answers holds nothing: it is
asked again when the tree is next opened.

**To your own services**, as part of the cycle:
- Anthropic: everything a Claude Code session reads, as with any Claude Code
  use.
- Your product's GitHub: issues, comments, pull requests, and demo videos
  attached to issues (`demo` in the product's config).
- Your deploy target: preview and production deploys (`ship`,
  `previewRegression` and `prodRegression`).
- Your team's metrics repository, if the product's config names one under
  `metrics`: your cycle records for that product.
- Telegram, only with `--extras` and a bot token you created: questions,
  their context, progress lines and demo videos go to your own bot's chat.
  With phone access turned on, the bot checks whether your machine's
  `ts.net` name is published yet: it asks Google's public DNS (`dns.google`)
  for the zone's nameserver and then that nameserver, which is Tailscale's,
  for your machine's name. When that one gives no answer it asks
  `dns.google` for the name itself, and when `dns.google` cannot be reached
  it asks the resolver of the network you are on. So the name reaches
  Tailscale, often Google, and sometimes your local network's resolver.

**What stays on your machine.** Session transcripts, terminal recordings,
each feature's history and its DORA page, and your cycle records
(`~/.claude/sclaude/`) when no `metrics` repository is set. The product's
`.sclaude/local/` is kept out of git and out of every Vercel upload; a
feature's friction log lives there and goes with its tree. What the reviews
keep from it — the deferred friction and the rules sclaude learns — goes to
the product's `.sclaude/` and is committed to the product, never to this
repository.

**What listens.** The proxy on `:3000` answers only this machine and your
tailnet. The phone's gate is on `127.0.0.1:3001` and is reachable from the
internet only through `tailscale funnel`, which the bot turns on when you
turn on phone access, and off with it. Each feature's dev server, and the
build its regression runs against, listens on `127.0.0.1`: sclaude moves a
Node server that would take every interface (`next dev`, `next start`) there,
so the proxy is the way in.

**Where the settings are.**
- This machine: the git config of this checkout. `./install.sh
  --update=… --contribute=… --leaks=…` changes them; `sclaude doctor` shows
  them.
- A product: its `.sclaude/config.json`, and `sclaude config`.
- The Telegram bot: `~/.config/keepawake/env`.
