# Why SClaude exists

*How a startup's fragmented team became one team again, and how the shared
tool it built became SClaude.*

## Some were ahead of the whole planet; others barely kept up

Friends of ours run a startup and launch at an astronomical pace. Then they
noticed their developers were nowhere near each other in vibe coding:

| some developers | others |
|---|---|
| **€200+** a month on AI: even a Claude Max plan was not enough | **less than ¼** of a €100 plan |

The surprise: those who paid the most were not the ones delivering the most
features. The ones ahead did not need an expensive plan. They simply
understood how AI thinks.

## The company became fragmented

The AI champions did not see why, or how, they should spend time sharing what
they knew. They grew their own expertise and their own speed. **And that is
normal: a developer's job is to develop, not to mentor.** Somebody else's
duties never take root.

So the idea came up that besides developers they needed a manager. Not one who
moves tickets in Jira; one who helps the team, who can read the team's tools as
code and run the team.

## Half their time went into tools

About **50% of the champions' time, and tokens**, went into tools to automate
how they develop features. That is normal too. What is not normal:

- each of them, independently, built **the same set of tools**: a way to reach
  the laptop from the phone, a way to keep it awake, their own AI review;
- each tripped over **the same holes** a neighbour had climbed out of long ago.

A zoo of bicycles, each just about coping with its owner's tasks.

## The first decision: all tools into the company's git, as is

People resisted: *"It's ugly in there. I'm ashamed to share it."* The answer:
put it out as it is. **If everyone is ashamed of the same thing, you get
support, not shame.** And it worked.

## Two months later

Did the champions stop spending half their time on tools? No. But instead of
reinventing bicycles they started seeing what others did: discussions,
exchanged ideas, questions to each other. *Why does your tool do it slightly
differently?*

1. **A company again** — not a set of individuals; knowledge started to flow.
2. **Company capital** — instead of a zoo of bicycles, Ferraris and
   Lamborghinis. The main one became SClaude, now open source by agreement.
3. **Standards, by themselves** — standard processes and scalability appeared
   on their own.
4. **Team spirit** — people said it had grown a lot: they felt the company
   shares with them and supports them.

## Why not a crew of agents?

The first attempt was elsewhere, in a large organisation with plenty of
budget: several models in one chat — one as architect, one as reviewer, one
writing tests — each checking the others. Pleasant to watch, of little use by
the end. Code and token cost grew faster than the value, and the agents
polished corner cases no user would ever reach. One idea survived: **manage
the context, and the tokens follow.**

The durable lesson: **do not make the model the process engine.** Prompts are
not guarantees. So the process moved into code, and the model was left with
what it is actually better at — planning, writing and reviewing code.

> "AI doesn't fix a team; it amplifies what's already there." — Google, 2025 DORA report

## Data needs a process; a process needs comfort

AI moves so fast that any book is outdated the moment it is published. The
only reliable source is your own data, and people you trust who work with the
same tools: your colleagues.

- No data about your process — no improvement, let alone AI agents and helpers.
- No process — no data.
- And no process survives unless it is **comfortable for the team**; otherwise
  people keep trying to avoid it.

So the process needs a feedback loop: change it quickly when something gets in
the way, and leave room for personal add-ons on top of the core. Not too
tight. Finding that balance is the know-how. See [Feedback Loops](Feedback-Loops).

## Next

- [Limits in code, not in prompts](Limits-in-Code) — the design principle
- [Metrics and the replay](Metrics-and-Replay) — how the team learns without being judged
- [The advice](Advice) — what to take away even without SClaude
- The deck behind this page: [vibe_coding_story.html](https://personalautomation.github.io/SClaude/presentations/vibe_coding_story.html)
