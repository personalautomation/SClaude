# Working from the phone

> **Step away from the desk. The work keeps going.**

In a startup, the laptop is the server. It was never built to be reached from
outside, which leaves three problems: **reaching it**, **keeping it awake**,
and **using it from six inches**. Almost every developer had already built
their own answer, each paid for in time and tokens. SClaude ships one.

## Most phone moments are look, tap, done

| share | what | how |
|---|---|---|
| **~80%** | look at the result or press a button: open the feature, restart something, answer "is the step done?", extend the laptop's awake time | the Telegram bot |
| **~15%** | talk to the agent: correct a plan, give the next instruction | the Claude app |
| **~5%** | something stuck or unusual | Tailscale + Termius, the spare key |

*Shares are a working estimate from daily use, not a measured benchmark.*

## The Telegram bot: a channel to the orchestrator

- **Answers SClaude.** Every question goes to the terminal and the bot at
  once; whichever you answer first counts, and the laptop carries on.
- **Web preview on the phone.** One tap opens the feature running on the
  laptop full screen inside Telegram, with no Tailscale on the phone. Only your
  account gets in.
- **The right context with it.** A "Publish?" arrives with what it would run;
  agreeing to an unseen action is not an option.
- **Shows every feature**, with links to its issue and pull request, and
  starts and stops dev servers, the browser and code-server from buttons.
- **Live widgets instead of a pile of messages.** What is active is a widget
  that updates itself in place: a question with every option a button, paged,
  however long the list; a running regression, review pass or session with
  its timer and latest lines, which leaves one message with the whole account
  when it ends; the countdown to sleep with **Extend** and **Let it sleep**;
  the feature's card with where it stands in the cycle; and the whole menu,
  which works with phone access off. Settings → Sending
  chooses widgets + messages, or messages only.
- Answers in the language of your Telegram client.

| the moment | the classic way: VPN + SSH | with the bot |
|---|---|---|
| see the feature | turn on the VPN, recall the IP and port, open the browser | tap **Open on phone** |
| restart the dev server | SSH in, find the terminal, stop it, start it again | tap **Stop**, then **Open** |
| "is the step done?" | SSH in, attach to the session, type the answer | tap **Yes** |
| the laptop is about to sleep | walk back to it, or lose the session | the bot asks 30 minutes ahead; tap **Extend** |
| where is everything? | check each terminal tab in turn | one card per feature: running, waiting, idle |
| something odd | the classic way | still the classic way — kept as the spare key |

## keepawake: awake while there is work, asleep when there is none

- **A person is there** (SSH, an editor tab, traffic over Tailscale) — the
  laptop stays awake for as long as it lasts.
- **Work with nobody watching** (a busy agent, a dev server) — held an hour at
  a time; 30 minutes before the end the bot asks whether to extend.
- **Probably forgotten** — an hour with no sign of anybody, and the bot asks.

When in doubt, it lets go: an early sleep costs one tap, a laptop that never
sleeps costs a battery. It lets a six-year-old laptop do the job of a paid VPS,
three features in parallel included.

## Also

- **Night mode** (`/isleep`): go to sleep; Claude carries on, decides instead
  of asking, and gives you a summary of its decisions in the morning.
- **Demo videos**, recorded by the agent: each feature clicked through as its
  users, on a desktop and a phone, with captions; the video lands on the issue
  for QA.

## Read more

- [The tools: keepawake, the bot, the per-feature proxy](https://github.com/personalautomation/SClaude/blob/main/docs/tools.md)
- [The deck: Build on a laptop, run it from a phone](https://personalautomation.github.io/SClaude/presentations/sclaude_instruments.html)
