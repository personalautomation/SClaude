# Metrics and the replay

> **Not a single field to fill in.**

Metrics that cost developers work are metrics nobody keeps honestly. In
SClaude everyone follows one process, so the data is a by-product of a process
that helps the developer, not one that watches them.

## What is collected, automatically

![The metrics page: sessions, tokens, cost, the share of commits written by Claude, deploys, features finished, review threads answered](https://raw.githubusercontent.com/personalautomation/SClaude/main/docs/presentations/src/img/dora.webp)

- **DORA's four keys** from real cycles: deployment frequency, lead time,
  change failure rate (rollbacks are found by themselves), time to restore.
- **Per feature**: time per step, test attempts and what failed, friction and
  what each review decided, review findings and responses, how far it shipped.
- **Tokens and cost**: per feature, per step, per review pass, and the cache
  hit rate — the one that saves the most.
- **How autonomous Claude was**: how many manual interventions a feature
  needed, and the share of commits Claude wrote.

A lead reads a summary table in each issue, and sees cost, speed and quality
without a status meeting. Optionally, each person's records are gathered in a
team repository.

## The replay: gamified, by accident

One of the most exciting parts of vibe coding is watching code being written.
Replaying your own feature is even nicer. Every finished feature plays back as
an animation on the process map: each step in turn, its minutes, its prompts,
how long the AI waited for you, its cost.

▶ **Watch** → ↻ **Replay**, again and again → **?** **Think**: *why did this
feature take so many steps? Why so long? What can I do better?*

People start it as a game and end up thinking about how to improve.

## Why not a leaderboard

| others | SClaude |
|---|---|
| **Token leaderboards.** Meta took its board down; Amazon closed its own after people burned tokens to climb it | you replay **your own** feature. You compare yourself only with yourself |
| **Champions made to mentor.** For leaders it is not their real job, and those who get such feedback all the time become defensive | mentoring is somebody else's duty. Developers are not distracted, and knowledge is shared without anyone noticing |
| **Analytics for management** | data is a by-product of a process that helps the developer |

A senior's verdict from on high makes people defend themselves and hide from
oversight. Here you think about yourself, and nobody else is judging.

## Read more

- [What is measured](https://github.com/personalautomation/SClaude/blob/main/docs/cycle.md#what-is-measured)
- [The process map](https://personalautomation.github.io/SClaude/presentations/bpmn_diagrams.html)
- [Feedback loops](Feedback-Loops) — the retrospective that coaches you one-to-one
