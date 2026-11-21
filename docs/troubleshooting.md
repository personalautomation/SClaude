# When something goes wrong

What you see, what it means and what to do, for the cases people meet most. The
quoted lines are the beginning of what sclaude prints. Run `sclaude doctor`
first whenever something looks wrong with the machine: it lists every gap it
knows of, with the command that fixes it.

## Installing and the machine

**`error: systemd's user manager does not answer (systemctl --user).`** — WSL
without systemd. Put `[boot]` and `systemd=true` in `/etc/wsl.conf`, run
`wsl --shutdown` from Windows, open the distribution again and run
`./install.sh` again.

**`note: run 'sudo loginctl enable-linger $USER'`**, or doctor's *linger is
off* — without it the background units, the bot among them, stop when you close
your last terminal. Run the command once.

**`note: ~/.local/bin is not on PATH`** — add
`export PATH="$HOME/.local/bin:$PATH"` to your shell's startup file.

**`note: sclaude-proxy.socket did not start — something holds :3000`** (or the
gate on `127.0.0.1:3001`; on macOS *holds :3000 — sclaude.proxy is not
installed*) — an old dev server or a hand-started proxy has the port. Stop it,
then run `./install.sh` again.

**doctor's warnings (`!`)** — each names something the machine lacks, and the
dim line under it is the fix: `vercel login`, `chmod 600` on an `.env` file
others can read, `./install.sh` for a unit that is not running, an environment
not chosen yet. Warnings do not fail doctor; only ✗ does.

## Updates of sclaude

**`instruments: N commit(s) behind main, not updated —`** followed by *has
uncommitted changes*, or *main has diverged from origin/main* — your own edits
or commits in sclaude's checkout stand in the way. Commit or stash an edit and
run `sclaude update`; move commits of your own to a branch with `sclaude
propose`, which also sends them as a pull request.

**Nothing new ever arrives** — the checkout may be a clone of a fork, which
takes updates only from the fork ([Where updates come
from](setup.md#where-updates-come-from)). `git -C <checkout> remote get-url
origin` says which.

## The product's config

**`Production — main in <repo> is not what origin holds:`** with the keys of
`.sclaude/config.json` that differ — the main checkout has an edit or a commit
origin lacks, often a hand edit of the committed config. Commit and push it, or
take origin's copy (`git -C <repo> checkout origin/main --
.sclaude/config.json`). A choice meant for your machine alone belongs in
`sclaude config` ([How the file works](config.md#how-the-file-works)).

**`✗ <part> — no command for this part.`** — a part named in `regression` has no
entry in `commands`. Add the command or take the part out of the list
([regression](config.md#regression)).

**`No preview deploy: the product names none`**, or **`Production: not offered
— the product names no deploy`** — the product does not use Vercel and names no
`deploy` command ([Hosting: deploy](config.md#hosting-deploy)). *Production:
not deployed — ship is off* means `ship: off`.

## A step and its session

**You left a session (Ctrl-C, `/exit`, a closed tab)** — nothing is lost:
sclaude remembers the step and the conversation. `sclaude <name>` opens it
again; `sclaude reset <name>` starts the step over without its conversation.

**A session stopped at Claude's usage limit** — sclaude says when the limit
resets and resumes the session where it stopped by itself.

**`A merge is under way in the tree; the step has not been started.`** — a merge
of main was left half done. Finish it with `sclaude sync <name>` or back it out
with `git -C <tree> merge --abort`.

**`the main checkout could not be fast-forwarded to origin/main`** at
`sclaude new` — an edit or a commit of its own in the main checkout. Clear it,
then run the `git merge --ff-only origin/main` the message shows.

## Step 4: the review

**`The automatic review of PR #N could not run on GitHub:`** with *step 4 stops
here* — the review workflow in Actions could not run: the Claude
subscription's limit, no Actions minutes, or a runner without network; the
message says which and when it resets. Wait and come back with `sclaude
<name>`, or set `review` to `github-local` or `local` in `sclaude config` to
review on this machine ([review](config.md#review)). With `github-local` the
move happens by itself and the message says so.

**`Step 4 is not done — red: …; N review thread(s) open.`** — step 4 closes only
with no open thread, no red or running check and green local tests. Let the
rounds run; `[s]` (⏭ in the feature's topic) makes the next pass the last that
looks for new findings, and `[g]` lets the rounds go on without asking
([A feature, start to finish](sclaude-guide.md#a-feature-start-to-finish)).

**`Yours to resolve on GitHub — you decided to leave these as they are:`** —
threads you chose to leave still count as open until resolved. Open each link,
press *Resolve conversation*, then answer `y`.

**`N review thread(s) were left at night for you to confirm.`** — during an
`/isleep` night these were held for your word. Answer `y` to go through them in
a session.

## Preview, QA and production

**The QA wait never ends** (*Waiting for QA on issue #N*) — nobody has moved the
issue to Done, or the column names in `board.columns` are not the board's.
Move the issue, or fix the names (case and spaces do not matter). Without
`board.columns.done` QA is not waited for at all
([The board](config.md#the-board-board), [qa](config.md#qa)).

**`Issue #N is in '<column>' — unexpected while waiting for QA.`** — the issue
went to a column that is neither a pass nor a hand-back. Put it in Done, or back
in In progress if it needs work.

**`could not read issue #N on the board; if the token lacks the right: gh auth
refresh -s project`** — `gh`'s token lacks the `project` scope. Run that
command.

**The menu says *steps done, production held*** — production's tests were red
and it was not rolled back. `sclaude regression <name> prod` runs them again
(green lifts the hold), `sclaude rollback <name>` puts production back, and
`sclaude return <name>` sends the feature back to step 4 ([Production
rollback](cycle.md#production-rollback-that-refuses-to-trample-somebody-else)).

## Databases and Docker

**`docker: not running — starting Docker Desktop…`**, then *still not up* or
**`database: Docker is not running and sclaude could not start it`** — the
feature falls back to the shared local database. Start Docker and run `sclaude
dev <name>` again; `SCLAUDE_DOCKER_WAIT` and `SCLAUDE_DOCKER_DESKTOP` adjust
the start ([Switches](sclaude-guide.md#switches)).

**`docker: this user may not use the Docker socket`** — add yourself to the
`docker` group (`sudo usermod -aG docker $USER`, then log in again).

**`database: supabase start failed — see .sclaude/local/feature/db.log`** — the
feature's own stack did not start; the log in its tree says why. `sclaude dev
--rebuild-db <name>` builds and fills it again. *Docker could not publish
ports* on Windows means a reserved port range: the message names the commands
that free it.

**`Which database should features on this machine work against?`** — asked once
per machine. A production environment is never offered for a feature, and
`SCLAUDE_ENV` naming one is ignored
([Environments and databases](sclaude-guide.md#environments-and-databases)).

## The feature's address and signing in

**`Starting <feature>…`** when you open its address — a feature nobody opened for
half an hour is stopped and starts again on the next visit, in about a minute.
*did not start*: run `sclaude dev <name>` in a terminal to see why.

**One-click sign-in says the config has no `devLogin`** — add the product's
sign-in route ([Signing in: devLogin](config.md#signing-in-devlogin)).

## The workshop and the bot

**`Send, reopen or drop?`** — a fix a session made to sclaude is ready to go out,
and something needs your word: lines that may name your product, red tests, an
unreviewed change, or sending set to `ask`. Read the lines and choose; the
question comes back every time you open the feature until you answer
([For a team](team.md)).

**The Telegram bot is silent** — read its log, `journalctl --user -u
keepawake-telegram.service -f`. *no KEEPAWAKE_BOT_TOKEN or KEEPAWAKE_CHAT_ID*:
fill `~/.config/keepawake/env`; *readable by the group or everyone*: `chmod 600`
it; *a second instance … (HTTP 409)*: the same token runs on another machine —
each machine needs its own bot ([Configuration](tools.md#configuration)). While
you are at the terminal, questions reach the chat silently, by design.
