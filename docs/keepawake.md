# How keepawake works, and why

The README covers what keepawake does, its commands and its set-up. This is
how it decides, and the traps it was built around.

## Who holds the machine awake

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

## Files

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

## Between WSL and Windows

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

## Driving sclaude from the bot

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
the question, and the bot settles its message on the next turn.

**A question's message does not outlive the question.** Answered anywhere — by a
button, by text, in the terminal — the message becomes the question with its
answer and loses its buttons; a typed answer is deleted, since the question now
shows it. Closed unanswered — the session was killed, a yes/no reply was neither
and the question is asked again, a word a list refused, the repository is gone —
the message is deleted. A typed reply the bot cannot tell an answer (neither yes
nor no, a word for a list) goes on to the orchestrator, which judges it, and the
message is settled by the record; a number the list lacks is held back with a
note instead, since the orchestrator would refuse it out of sight.
The disappearance of `ask.json` says only that the question closed, so an
answered one leaves `.git/sclaude/closed/<id>.json` (reply and source) before it
goes; the bot reads and deletes those records, and the orchestrator clears any
older than a week for machines where the bot does not run. Telegram lets a bot
delete only for 48 hours; an older message is edited to "no longer relevant"
instead. The message id is dropped once the message is settled.

A press carries the repository, not the question, so a press on an older message
would answer whatever the repository asks now. The bot compares the message with
the one showing the open question and answers any other with "already closed".

**A channel and a topic per feature.** Features run in parallel, each under its
own orchestrator, and one channel per repository let only one of them reach the
phone: the second found it busy and asked the terminal alone. A function working
on a feature declares `local ASK_SLUG="$slug"`, and its questions go to
`.git/sclaude/ask/<slug>/` (`ask_channel` in `sclaude/lib/io.sh`); bash's dynamic
scope ends the binding with the function. The binding begins only once the
feature's worktree exists: the name and the GitHub issue `sclaude new` asks about
go to the repository's channel. The bot reads the feature from the
directory's name and, with Threaded Mode on in @BotFather, shows its questions in
a topic of its own (`createForumTopic` in the private chat), named slug first —
a phone shows about thirty characters of it — and the repository after it while
the name stays within 48. A press is routed by the message it came from, and text
typed in a topic answers that topic's feature; in the main chat text answers the
question it replies to (Telegram's Reply), or the one question shown there —
with several and no reply, the bot asks which. Replies to a command typed in a topic go back
to that topic.

What the bot knows of a feature — its topic and the message showing its open
question — lives in the feature's worktree and nowhere else, in
`.sclaude/local/feature/telegram.json`, which git and uploads leave out. The
topic goes with the worktree: `remove_worktree` reads the record while the
worktree is there and, once it is gone, leaves it in the channel's `ended` mark
(`ask_record`, `ask_feature_end`), which also ends the binding. The bot deletes
the topic — Telegram deletes every message in it with it — and the channel. So a
feature asks nothing once its worktree is removed: `done` makes its offer about
side worktrees first, and `drop` asks all its questions (worktree, branches, pull
request, issue) before it does any of it. A worktree removed by hand takes the
topic's id with it: its channel goes ten minutes later, and the topic is left to
delete by hand. Telegram does not let a bot close a topic in a private chat, only
delete it. The daemon's state keeps the repository channels' messages, and a
feature channel's only while it has no worktree.

**Notes: what the topic is told without being asked.** After each review round
sclaude also says where the review stands: `review_report` in `run.sh` has
`review_report.py` write the numbers of the last session that ran a review to the file
`SCLAUDE_REPORT_BRIEF` names, and `ask_notice` (`sclaude/lib/io.sh`) lays that
text in the feature channel's `notes/`, skipping a text the same as the last one
— the report is printed at more than one point of a round. The bot sends every
note to the feature's topic in the order they came, each a message of its own and
without a sound, and deletes it once sent (`keepawake/notices.py`); a message is
never edited, so the topic keeps the history. A note the network kept back waits
for the next turn, one older than a day is dropped, and the notes go with the
channel when the feature ends. The module is separate from `telegramd.py`, which
passes it the channels and the way to a topic.

**The menu, split by where it is.** In a feature's topic there is nothing to
choose: the topic is the feature, so the menu there is the feature's card —
step, session, links, dev server, code-server (`?folder=` opens the worktree,
whichever project the server started on) — with buttons that act on it
directly. The card is the topic's first message; "Menu", `/menu` or text that
answered nothing bring a fresh one, and the old goes. It is not pinned: a pin in
a topic of a private chat announces itself in the main chat. A card's buttons
name the feature in their data when it fits 64 bytes and leave it to the topic
otherwise. The main chat keeps what is not about one feature: sleep, status,
Chrome and the list of features, code-server, the repositories and their
features — a press on one opens its topic — and Settings. Without Threaded Mode
the card stands where the feature list was, with a way back to it. With phone
access on all of this lives in the menu app (below), and the chat's menu and a
topic's card are each one button to it.

The main chat holds one menu at a time, and so does each topic (`screens`, by
thread): a menu sent anew —
by a command, "Menu", or a word the bot did not know — replaces the last, and the
typed command goes. A menu that did something rather than lead elsewhere is
edited into what it did, without buttons, and stays as a line of history, as an
answered question does.

The bot's own questions are settled the same way: the sleep warning becomes
"extended until" or "will sleep" when the deadline moved, by a press or without
one, and goes once its deadline has passed. No message about sleep outlives its
truth: each answer — to the warning, /extend, /sleep, the keepawake menu, the
question about forgotten holders — is kept with its expiry (`sleep_trail` in the
state) and goes when it passes, within Telegram's 48 hours for deleting; a new
answer or warning takes every earlier one away, so the chat shows at most the
one that holds now. A line the network kept is tried again on the next turn. The question about forgotten holders goes
once nothing holds, someone typed, or no session is left; the "until what time?"
prompt becomes the answer, or goes with its input box when the person leaves it.

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

## The menu as an app in Telegram

**What the person starts is in the app; what the bot asks stays in the chat.**
With phone access on, "☰ Menu" (`setChatMenuButton`, set for the chat as well
as for the bot: the chat's own setting changes at once, the bot's only when a
chat is reopened) opens a Mini App served by the gate. The chat keeps the
bot's questions as buttons that become their answers, and a line, marked 📱,
of everything started from the app — in the feature's topic when it was about
a feature. What only showed something leaves nothing. Without phone access the
app cannot open, so the chat's `/menu` keeps what must work without it: the
hold and turning access on; the command list (`setMyCommands`) follows the same
split.

**The page has no screens of its own** (`keepawake/webmenu.py`). A press is
handed to the chat's own `Handler.callback` as though it came from a menu
message with the id 0, and `PageBot` catches what the handler does to that
message: an edit becomes the page's next screen, a reply its note, a result
(`Handler.result`) both the screen and the chat's 📱 line. One handler for both,
so the app and the chat cannot disagree about what a button does. Where the two
must differ — a time typed into the page's own field instead of a second message
with a reply box, a docs section as a screen, a confirmation before access goes
off — `press` takes the action before the handler does, and `ON_PAGE` tells the
screens to leave out links that only work on the tailnet. Each screen has a line
under it saying what it is for (`HELP`).

**The gate** (`sclaude-proxy --gate`, on 127.0.0.1:3001 behind `tailscale
funnel` on :8443) lets in only the bot's owner. Every call of the menu carries
Telegram's signed `initData` and is checked by itself; a feature's page and
code-server (`/__code/`, its own paths under a prefix only the gate knows) are
reached with a cookie the gate signs once `initData` checked out. Telegram Web
shows a Mini App in a frame inside web.telegram.org, where a browser keeps no
`SameSite=Lax` cookie, so every cookie on the gate's way — its own and the
product's — is made `SameSite=None; Partitioned`: kept for that frame and keyed
to the site around it. What Lax did against a forged request the gate does
itself: a request another site made the browser send (`Sec-Fetch-Site`, or
`Origin` from an older browser) is refused, a plain link followed is not.

**Phone access waits for the address.** A funnel just turned on is not reachable
at once: while it was off its name left public DNS, and it comes back only after
minutes (five, once). A phone that asks too early is told the name does not
exist and keeps that answer five minutes more. So `gate_origin` counts the
funnel only once the name is published — asked of the zone's own nameserver,
which keeps no answer, with DNS over HTTPS when that fails — and until then
nothing offers the app. The bot says it is waiting (`phone_wait`) and turns that
message into "phone access is on" when it is ready; past fifteen minutes it
offers the app anyway and logs why. The loop (`check_phone`) notices every
change, made from the chat, the app (another process) or the terminal, and
redraws what offers the app: the Menu button, the commands, the menu screens
and the cards in the topics.

**Off unless asked for.** Tailscale keeps a funnel across reboots, and a door to
the internet nobody remembers opening is one to close: at start the bot turns
phone access off if it was turned on before the machine started (`phone_on_at`
against the kernel's boot time). A restart of the bot alone leaves it as it was.

**A new feature has its topic from the start.** "✨ New feature" opens a topic
at once, so the questions about the name already go there (`new_feature_topic`);
when a worktree appears that is newer than the topic, the topic is that
feature's and is renamed for it. One left unclaimed for twelve hours is deleted.

## Two Windows traps

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
