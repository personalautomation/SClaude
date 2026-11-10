# The tools

The reference for the developer installing and running them. The
repository holds machine-level Claude Code helper scripts and skills, not tied
to any project: they live here, symlinked into `~/.local/bin` and
`~/.claude/skills`.

| tool | what it is for |
|---|---|
| [`sclaude`](sclaude-guide.md#binsclaude) | runs a feature from issue to production with Claude doing the work and a person making the decisions |
| [`skills/pr`](#skillspr) | a `/pr` skill: opens a pull request the way the team does it |
| [`skills/sreview`](#skillssreview) | a `/sreview` skill: review and fix in iterations until the review finds nothing substantive |
| [`skills/sdemo`](#skillssdemo) | a `/sdemo` skill: a recorded demo of a feature — clicked through as its users, with captions on what to look at, a step to take over from — or `live` in chrome-debug, or plain signed-in links; `/sdemo ac` by its acceptance criteria |
| [`skills/isleep`](#skillsisleep) | an `/isleep` skill: night mode — Claude carries on alone, decides instead of asking, and reports in the morning |
| [`sclaude-proxy`](#binsclaude-proxy) | one address per feature: `http://<feature>.localhost:3000` |
| [`chrome-debug`](#binchrome-debug) | the Chrome that Claude drives to check its work |
| [`wsl-update`](#binwsl-update) | the daily update of the tooling in WSL |
| [`keepawake`](#binkeepawake) | keeps the laptop awake while work goes on, and a Telegram bot to drive it all from a phone |
| [`statusline.py`](#statuslinepy) | Claude Code's status line |
| [`githooks/commit-msg`](#githookscommit-msg) | refuses a commit whose requirement footers would be lost |

How the parts work inside, and why they were built that way, is in
[`docs/sclaude.md`](sclaude.md) and [`docs/keepawake.md`](keepawake.md).
sclaude's cycle drawn as BPMN — every lane, every way back, every command and
where it leads, interactive and printable — is
[`docs/presentations/bpmn_diagrams.html`](presentations/bpmn_diagrams.html),
one page, [on GitHub Pages](https://personalautomation.github.io/SClaude/presentations/bpmn_diagrams.html) or from a checkout.

## skills/pr

A Claude Code skill that finishes work through a pull request instead of a push
to `main`. Call it with `/pr`; sclaude's step 3 calls it too. Claude does not
run it on its own.

It works on a `feat/…` branch, checks that commits follow Conventional Commits,
runs the project's checks and opens the pull request. The description has
**Summary** — what changed; **Requested by the customer (for QA)** — what was
asked for, as observable behaviour, for QA to check; then **How to verify** and
any **Notes**. It also updates the product's manuals. It never merges or
deploys.

## skills/sreview

`/sreview [N]` runs iterations of review and fixing on the current branch, in
any repository, and asks whether to go on every N iterations (5 by default). It
stops by itself once a review finds nothing substantive.

Each review is a fresh subagent that has not seen the fixes, told what was
already decided so it does not raise it again. Fixes go to subagents where they
are more than a line or two. Questions are asked once per iteration, about a
class of findings rather than one line, and each answer is kept where it
applies: one that holds across the repository as a policy in
`<git common dir>/sreview/policies.md` — outside git, shared by every worktree —
which settles similar findings in this run and later ones; one about a single
part of the code as a comment beside that code, or in its doc. In a project run by
sclaude it takes the check commands, the review mode and the review rules from
there, and with a pull request open keeps the findings as its threads. It
commits once per iteration; pushing is left to the project's own rules.

## skills/sdemo

`/sdemo [feature] [what to show]` shows you a feature working. Claude reads
what the feature changed, picks a few scenarios — each seen as the user it
should be seen as, from the feature's own database — and writes them as a
Playwright script; the player signs in as each user (see *Signed in without a
password* under [bin/sclaude-proxy](#binsclaude-proxy)), clicks and types
through the steps, and puts captions on the page as it goes: what each step
does, where to look, why it matters. You get one link to a page — run by
sclaude's steps, also sent with the videos to the feature's Telegram topic, as
📱 for the phone (the tailnet's address) and 💻 for the laptop, and kept with
the videos in a demo comment on the feature's issue; run by hand, given in the
terminal only — with:

- a video per scenario — on a desktop, and on a phone where the layout differs
  there — and what it shows, what to look at and why this case;
- its steps beside it, the one under way written out large under the video
  (and as the video's captions in full screen); tap a step to jump there;
- checks marked ✓ or ✗;
- **take over** on every step: that page, signed in as that user, to go on by
  hand.

Each feature has one demo page, `/__sclaude/demo/<feature>/`, with every demo
it ever had, as versions: a full demo and the deltas recorded before it — a
delta is a short recording of only what changed for a user, kept each time the
demo is recorded again after a change. On top the current version, marked
**CURRENT**: since when, what changed in it — between which stages
(`2-code → 2-code`, `2-code → preview`), by which commits, the change in a
sentence, its videos — and the whole feature. Below it the history, newest
first: each earlier version marked **OUTDATED**, with the time it was the
current one (from — to, and how long), its videos folded. The feature's
Telegram topic keeps only the current version: a new full demo deletes the
earlier ones there — all but a message older than 48 hours, which Telegram
does not let a bot delete. `/sdemo delta` records one
by hand; when nothing changed for a user, it records nothing. The page is
linked from the proxy's list of features, under the feature, and from its
process map.

`/sdemo ac` walks through the acceptance criteria in the issue instead, a
scenario per criterion (or a few together), and names the ones no page can
show. `/sdemo live` plays the same in the laptop's chrome-debug, a window per
user with cookies of its own: ⏸ on the page hands it to you, ▶ goes on, ⏭
goes to the next scenario, ⏹ ends the script and leaves the windows signed
in. `/sdemo links` gives plain
links instead — one per scenario, signed in, with what to check under it —
and `/sdemo links open` opens them in chrome-debug, a window per user, closing
the previous demo's windows.

The links are for where you are: on the laptop `http://<feature>.localhost:3000/…`;
when a device of your tailnet has traffic now — you are on the phone — the
address the bot opens features at on a phone (the `tailscale serve` name, or
the tailnet address). Say "I'm on the laptop" or "on the phone" and it follows
that instead; the other place's link is given at the end, when there is a
phone address at all (`tailscale serve` or the tailnet's).

The videos are H.264 when `ffmpeg` is installed (`sudo apt install ffmpeg`),
which every browser and Telegram play; without it, the recording's own WebM,
four times the size, which Safari before 17.4 does not play. A demo is kept in the feature's `.sclaude/local/demo/`.

`skills/sdemo/demo.py` does each part by hand: `play <script.mjs> [--live]`
plays a script, `replay` plays the last one again, `stale` says whether the
code changed since the last demo,
`link <email> <path>` makes one link, `open <email> <path>…`
opens links in chrome-debug, `users` lists who can sign in and `criteria`
prints the criteria.

## skills/isleep

`/isleep [task]` when you go to sleep and the session has to carry on. First
it runs `/fewer-permission-prompts` for the project, into
`.claude/settings.local.json`, so that a read-only command it asked about
before does not hold the session at a permission prompt all night. Then Claude
stops asking: each question it would have put to you it settles by the option
it would have recommended, and wherever it would stop to ask whether to go on
— another review round, the next item, a retry — it goes on. It does not end
its turn while work is left, and waits for CI and the like in the background.

It still does not do what it would need your word for by day — push, merge,
deploy, delete what is not its own, write to other people, spend money (one
exception: sclaude's review step answers and resolves a minor thread its own
review posted); such a step is left ready, with the command that does it. Every decision is logged as
it is taken, with what it was instead of and how to undo it, in
`~/.local/state/isleep/<date>.md` — one log for every session of the night.
Your first message in the morning gets the summary: the result, the decisions
taken for you, what waits for you, what was set aside. `/isleep report` writes
the summary without ending the night, `/isleep off` ends it.

In a project sclaude runs, its `[g]` "go on by itself" is on while a night
over every session is (not an `/isleep here` one), under `sleep_mode: auto`
(the default): step 4's review rounds go on without asking, and in the
morning they ask again. `on` keeps `[g]` on all the
time, `off` leaves it to the box alone; a box you set yourself wins either way.

The night is kept in `~/.local/state/isleep/night.json`, not only in the
conversation, and covers every Claude session on the machine — already
running or started during it, such as sclaude's next step; `/isleep here`
keeps a night it starts to one. Hooks that `install.sh` adds to `~/.claude/settings.json`
bring the rules into a new, compacted or resumed session and into a running
one at its next tool call, refuse `AskUserQuestion` with "decide and log", and
ask a turn that ends whether work is left (once per turn, at most 40 times a
night in each session). `/isleep 8h` sets how long the night lasts (12 hours by default).

The night ends when you type anything in any session: that session gives
you the summary, and every other session the night reached is told at its
next tool call that questions go to you again. A night that runs out its
hours ends the same way, and your first message after it gets the summary;
so does one ended outside any session — `night.py off` in a terminal, or your
yes, in its terminal or on the phone, when sclaude offers to go through the review threads left at night, which
ends the night so that the session asks you rather than deciding.
The prompt sclaude starts a step's session with, a headless
`claude -p` and a `/loop` wakeup do not count as you — nor does a `/loop` you
type, which reads the same. A session closed during the night is told when
you resume it. By day the hooks do
nothing; sessions started before the hooks were installed do not run them.

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
- Under each feature and main, a line for each web tool of its own: its
  Supabase Studio and Inbucket while its database stack runs, Code Server
  opened on its tree (started on the way when it is down; from this machine
  — the phone has its own through the gate), and its process map.
- `localhost:3000/__sclaude/flow?f=<feature>` — the feature's process map: the
  whole cycle as BPMN, with where the feature stands lit and, beside it, the
  actions open to it now, each with its command and the place on the map it
  leads to. It follows the feature as it moves (every few seconds). The list of
  features links it on a line of its own, "<feature> — Process map (BPMN)",
  and under main the same line opens the whole cycle with no feature on it
  (`/__sclaude/bpmn`). The panel beside it switches between **Actions** and
  **History**: every place the feature stood on, when and for how long, and
  the arrow it came in by — with who took it (you, a setting, sclaude's own
  check, the session, QA, GitHub, or nobody answering), how (the terminal or
  the phone, a key of sclaude's tab, the setting's value) and what was known
  then (findings, the tests that were red). ▶ by a map's heading plays how the feature went on
  that map — a clock on each place counting its time, then the arrow it took,
  a friction review or a change to sclaude jumping to its own map and back;
  by those two maps' headings a list chooses which pass to play. While it
  plays the History follows it, and a click on a line plays from there. The
  history starts with sessions run since sclaude keeps it. Checkboxes above
  the maps put in each block what it took: ✋ your input — each message to
  Claude after its turn, each answer to its question or to sclaude's, each
  command run on the feature at the terminal — Claude's cost in dollars, and
  ⏳ how long a question waited for your answer, Claude's or sclaude's, nights
  included, ♻ how many times Claude's prompt cache had expired and a
  conversation's context was written to it again (usually after a long
  pause), and ⏱ how long the feature stood on the block, every stay added
  up — what sclaude has going now (a step, a sync, a friction review, a
  regression, the wait for the merge or QA) counted up to now; ⚠ when
  something ended with no end written (a Ctrl-C, a terminal that died) and
  its time is a guess — with ×3
  when it was entered three
  times (not on the cycle at a glance, whose blocks stand for several
  places); a block with none shows none. They sit inside the block, in its
  corners (a start or an end, a small circle, has them in a line under its
  words): ✋ and ⏳ together at the bottom left, the cost at the bottom
  right, ⏱ at the top left; a block whose own text fills four lines gives up
  its last line of description to make room, and gets it back when the
  checkboxes are off. Each checkbox shows the whole feature's
  total beside it, and every map's heading its own — a map nothing was
  counted on, such as a friction review put off with no session, says its
  zeros. While a map plays, its blocks count up instead:
  what was played there so far, and on the place playing now its own share
  after a plus — ✋ 3+2 is three before it and two in it, its time on the
  player's clock; the totals come back when the play ends or is stopped. Off
  the play, the step going on now is shown the same way on its own
  map when it was entered before: what the earlier stays took, then its own after a plus. The player plays at ×0.5 to ×16;
  its "this map only" box keeps a play on the map it started from, the friction reviews,
  regressions and syncs left out rather than opened on their maps — a steady view to watch or
  record. The box is remembered, and ticking it during a play starts that play again.
  The page's address follows what you see, as you scroll and click: the
  section in view, the boxes ticked, the panel's tab, what is selected, and a
  play — which map, which pass, the place it is at, its speed, "this map
  only" and paused. Copy the address and it opens the page as it was, a play
  resumed at that place; the printable map (`/__sclaude/bpmn`,
  `bpmn_diagrams.html`) keeps its section, selection and pinned commands the
  same way.
- `localhost:3000/__sclaude/dora` — the product's metrics, linked under main
  as "main — DORA metrics": DORA, delivery, development quality, Claude's work
  and token efficiency. Production deploys and builds come from Vercel, each
  change's first commit from git and GitHub, failures from the rollback
  comments sclaude writes on an issue, sessions, tokens and dollars from
  Claude Code's transcripts (its own cost record), and the rest from the cycle
  records, the review log and the issues' acceptance criteria. It is rebuilt in the background whenever `sclaude` starts in
  the product and the page is over six hours old (`SCLAUDE_DORA_EVERY`, in
  seconds), and at once when a feature is finished; an open tab reloads
  itself hourly. Every step's header prints it under the feature's address,
  and in the Telegram Mini App it is "🗺 Process map" in a feature's actions and
  on its card, which starts the feature's dev server too (and gives it one
  first when it has never had one).

On either map, pointing at a block, an arrow or a command lights it and what
it touches — a block its arrows and their other ends, an arrow its two ends, a
command the place it leads to, a block the commands open there — and fades the
rest, with a note on what it is and does. A click keeps it lit, Ctrl-click adds
more (the lit things add up), and Esc or the floating button clears. On the
printed page the commands' names are also pinned beside the maps, so both are
read together; unpin them from the list itself or from the heading of the
commands' section.

Different addresses rather than different ports keep features apart in one
browser: cookies ignore the port, so on ports alone signing in to one feature
would sign you out of another.

**Signed in without a password.** When the product's `.sclaude/config.json`
names its route for email links (`"devLogin": {"path": "/auth/confirm"}`, the
route that verifies `token_hash`), a feature in the list opens signed in as
you: the first line of `~/.claude/sclaude/dev-login`, else your
`git user.email`. "without signing in" beside it opens it as it is.
On a feature with a local database of its own you can sign in as anybody in
it:

- "as another user" beside the feature (`/__sclaude/users?f=<feature>`) lists
  that database's users, a sign-in link each;
- `http://<feature>.localhost:3000/__sclaude/login?as=<email>&next=<path>`
  signs in as that user and opens `<path>`, dropping the session the browser
  had there. Both are URL-encoded: `qa%2Badmin%40example.com`, not
  `qa+admin@…`, whose `+` reads as a space. Ask a step's session for links to test a feature as some user
  and it gives you these.

Only users that exist are signed in, never created. On a shared environment
only your own address signs in, and on a protected one nothing does.

Only this machine and your Tailscale network are let in; anybody else on the
same Wi-Fi gets `403`. `SCLAUDE_PROXY_ALLOW` replaces the list with networks of
your own, comma-separated.

`sclaude dev` in the main checkout serves it at `main.localhost:3000`.

### The bot as an app in Telegram, with no Tailscale on the phone

While phone access is on, the bot's menu is a Telegram Mini App: "☰ Menu" by
the input box opens it, and "📲 Open in the app" on a feature's card opens it on
that feature. Inside it, a feature's "📲 Phone" opens the feature itself full
screen, with an address bar of its own, and code-server opens on the worktree
the same way. The phone needs nothing but Telegram; Telegram Web on a computer
works too.

Telegram does not tell the app which topic "☰ Menu" was pressed in, so that
button first asks which feature, or the whole machine. "📲 Open in the app" on
a feature's card opens the app on that feature: 📋 Sclaude is its
card, 🌐 Chrome and 💻 Code-server open it and its worktree (code-server's screen
shows its password), and "📍 Choose a feature" moves to another or to the whole
machine. The card in the app has a button to a row: ▶️ continue the step, named
by where the feature is; ⚙️ other feature actions, chosen right there and grouped
by the step each leads back or on to, with the current step marked; 🌐 open the
browser on the laptop; 📲 show the app here; and starting or stopping its dev
server. Under the session's state it says how many minutes its prompt cache has
left — going on with the session past them pays to write the whole conversation
into the cache again. Continue and the actions start nothing beside a step at
work or a question waiting for you.

It works through `tailscale funnel`, which publishes
`https://<node>.<tailnet>.ts.net:8443`. A gate in front lets in only your
Telegram account (the one in `KEEPAWAKE_CHAT_ID`), checked by Telegram's own
signature, and sends everyone else away with `403`.
After sclaude updates itself, the app picks up the new code on its own: the
gate closes once nothing is loading and starts again on the next request,
and you stay signed in.

Phone access is off until you turn it on, and off again after the machine
restarts. Turning it on takes a few minutes — sometimes five — before Tailscale
publishes the address; the bot says it is waiting, offers the app nowhere until
then, and changes that message when the app can open. Turning it off from the
app asks first and closes the app.

Turn it on with `/phone` or the chat's "Phone access" button, off in the app's
Settings. The first time needs, once:

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
chrome-debug --window URL...     # a new window with cookies of its own, the URLs as its tabs; prints its id
chrome-debug --close-window ID   # close such a window, its cookies with it
```

`CHROME_DEBUG_PORT` (9222) and `CHROME_DEBUG_PROFILE` change the port and the
profile. The log is at `~/.cache/chrome-devtools-mcp/chrome.log`.

You rarely need it by hand: sclaude opens the feature in a background tab before
each step, without pulling the window in front of whatever you are looking at.

## bin/wsl-update

Installed with `./install.sh --extras`, under WSL only.

The daily update of the tooling in WSL2: apt, nvm and Node, global npm packages,
Claude Code and its plugins, Playwright's Chromium, code-server. It also reports
outdated dependencies for the projects listed in `~/.config/sclaude/projects`
(one path per line) without touching them.

Local Supabase images are kept at the versions the Supabase CLI and production
use, and unused old ones are cleaned up. On the Windows side it only reports — a
newer WSL, applications `winget upgrade` lists — because updating those from
inside WSL would shut WSL down or need elevation.

A Node that does not start — a major that needs a system library WSL leaves
out, as Node 26 needs `libatomic1` — is named with the `sudo apt install` that
fixes it. When it is the node the run uses — the default follows `lts/*`,
which nvm moves to a new LTS as soon as it unpacks it — the steps that need
node are skipped rather than failing one by one. The fix is that package, not
the older version.
`sclaude doctor` names the same gap.

It runs every day at 10:00 (and catches up after a missed day). Logs are in
`~/.local/state/wsl-update/`.

```bash
wsl-update                                  # run it now, in the terminal
systemctl --user status wsl-update.timer
journalctl --user -u wsl-update.service
```

## bin/keepawake

Installed with `./install.sh --extras`.

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

**The Telegram bot.** With phone access on, the menu is an app inside Telegram
("☰ Menu" by the input box): 💤 Keepawake — extend, until a time, release, and
why the machine is or is not sleeping; 📋 Sclaude — the repositories, their
features with what each step is doing (🟢 running, 🟡 waiting for you, ⚪ idle,
⚫ not started), a new feature — from an open issue, yours first and marked
when something blocks it, with the branch name to correct, or from a name with
a tick for creating its issue, as `sclaude new` offers at the terminal — and 🧩
the project's config, every section explained, with `review`, `qa`, `merge`,
`ship`, `previewRegression`, `prodRegression`, `demo`, `partAccept` and `sleep_mode` set by a button; 💻 Code-server; 🌐 Chrome and the list of every
feature; 🛠 Workshop — `sclaude workshop` in a tab on the laptop, a session that
changes sclaude, picked up over Remote Control in the Claude app; ⚙️ Settings — language, docs, restarting the bot (the screen waits
and says when it is back), phone access. Each
screen says under it what it is for. What you start there leaves a 📱 line in
the chat — in the feature's topic when it is about a feature — and what only
shows something leaves nothing. sclaude's questions stay in the chat as buttons,
and an answered one becomes its answer. Without phone access `/menu` in the chat
keeps what works without it: the hold, and turning access on; the command list
follows. It answers in Russian to a Russian Telegram client and in English to
everyone else.

**Answering sclaude from the phone.** Every question sclaude asks goes to the
terminal and to the bot at once, and whichever you answer first counts. Start a
feature at the laptop, walk away, answer from the phone: the terminal carries on
by itself. While you are sitting at the terminal the question arrives silently,
so the phone does not buzz for something already on your screen. Claude's own
conversation in a step continues in the Claude mobile app.

Once a question is answered — by a button, by text or in the terminal — its
message becomes the question with the answer; one that closed unanswered is
deleted.

**A topic per feature.** With Threaded Mode on for your bot (the @BotFather mini
app: Bot Settings → Threads Settings; also turn on "Disallow users to create new
threads"), each feature has a topic of its own: pressing a feature in the sclaude
section opens it, and its questions go there, so features running in parallel do
not ask over one another. The topic starts with the feature's card — its step,
issue and pull request, ▶️ continue the step, ⚙️ actions, its dev server (open on
the laptop or the phone, start, stop) and 💻 code-server on its worktree; with
phone access on these are in the app, and the card has one button to it — and
"Menu" in the topic brings a fresh card. ✨ New feature, ▶️ and ⚙️ open sclaude
in a tab of Windows Terminal on the laptop, as if you had typed it there; its
questions still come to the topic. The card follows its session — within a
minute of it starting, waiting for you or going idle. A new feature gets its topic as soon as
it is started, and the topic takes the feature's name once it has one. After each review round the topic also
gets where the review stands: the last review session's runs, findings, fixed,
closed without a fix, still open, on earlier fixes and raised again, with the
report's verdict — a message of its own each round, so the topic keeps the
history. And it follows what sclaude is doing there — each session that
starts and ends, and each step once it is done; a review fix session with
what it is handed and what it leaves (findings not fixed yet, new, fixed,
declined, commits), and the review on this machine as it runs — its start
carries the keys its terminal takes, ⏭ the last pass for new findings and ⏹
stop now, and a fix session's start the first of them, so a review can be
ended from the phone; the buttons go once that pass or session ends; regressions
(a red one names the specs that failed, by their titles), deploys and QA's
moves on the board — in short messages, one step's lines apart from the next one's, silent unless something went wrong while you are
away from the laptop. Typing an answer inside a topic answers
that feature; in the main chat, with several questions open there, answer one
with Telegram's Reply on its message. The menu, the sleep warning and questions not about a feature stay
in the main chat. When `sclaude done` or `drop` cleans a feature up, it leaves the menus
as soon as its worktree starts going, and its topic is deleted, everything in it
included, so the chat's "All" view is cleared of it too (Telegram lets the bot
delete only messages under 48 hours old); `drop` therefore asks all its questions before it removes anything. A
question still open about it elsewhere — the action list opened from the phone —
is withdrawn, and its sclaude ends. Without Threaded Mode everything stays in one
chat, as before. If `getMe` still says `has_topics_enabled: false` after the
switch, change any classic setting (`/setjoingroups`) to refresh it.

**code-server starts on demand** — from a button in the bot, by following its
local link, or with `systemctl --user start code-server` — and stops itself
after an hour idle.

### keepawake on plain Linux

There is no Windows side, so `keepawake-linux.service` holds the machine itself
with `systemd-inhibit`. By default a background service may only stop the
machine sleeping *when idle*: a closed lid or an explicit suspend still sleeps
it, and the hold log says so once.

`install.sh --extras` offers to change that on plain Linux, and only there. It explains
when the rule is worth having (a laptop you close while working from a phone),
shows the command that removes it, and asks for a yes or a no.
`./install.sh --polkit` adds it without asking, `--no-polkit` skips the
question. To remove it later:

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
password is in `~/.config/code-server/config.yaml`. Put its `bind-addr` on the
Tailscale address: `install.sh` then also opens `localhost:8080` for the
laptop's browser. A code-server left on its default `127.0.0.1:8080` gets no
such forward — it already answers there.

```bash
journalctl --user -u keepawake-telegram.service -f   # the bot's log
```

## statusline.py

Claude Code's status line. On the left, the sclaude session (`1-plan`,
`4-fix-review(2)`, `4-fix-preview`, `5-sync`, `6-epilogue`, …) and the path; in the middle the
branch, the feature's pull request, the session's name and the worktree; on the
right the model, the effort, how full the context is, the prompt cache, and the
usage limits. On a narrow terminal the least important fields drop out first.

`💾 37m` is how long the prompt cache has left: past it, the next message pays
to write the whole context into the cache again. Once it has expired the field
says what that costs — `off ~4%` of the five-hour limit, or `off ~$0.80` until
the status line has seen enough spend to know what a percent is worth. That
rate is learnt across all sessions on the machine, and use outside Claude Code
moves the limit too, so the share is an estimate on the high side.

`install.sh` links it to `~/.claude/statusline.py`, which `settings.json` points
at.

## githooks/commit-msg

Refuses a commit whose `Requirement:` footers would not survive as git
trailers. Git only treats the last paragraph of a message as trailers, and only
if every line in it is one; a stray blank line, or a missing one, silently drops
them — and with them the QA section of the pull request the `pr` skill builds.
The hook asks git itself what it will see, and compares.

`install.sh` points this repository at it through `core.hooksPath`.
