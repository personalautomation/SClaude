# Feedback loops

> **A process only works if it's comfortable. Otherwise people work around it.**

Locking the agent down is half the know-how. The other half is reading what
the locks caught, and changing the process from evidence. SClaude has three
loops on three horizons.

| loop | when | what it reads | what it decides | where the change goes |
|---|---|---|---|---|
| **Friction review** | after every step that hit a ban | each refusal, as it happened | lift the ban, keep it as deliberate, or defer it | the product's rules, on the feature's branch; the next step already runs with it |
| **Monthly review** | once a month | everything deferred, counted by class across features | lift, ban for good, write a rule, relax a rule, or keep waiting | team rules and the product's CLAUDE.md; a change for every product becomes a pull request to SClaude |
| **Retrospective** | each feature, before clean-up | the terminal recording of the whole run, the plan, the state | what was missed, how the person could work better, what SClaude could do better | missed work goes back through the cycle; lessons to the person, the team, the maintainers |

**One refusal is an anecdote. The same one in five features is a pattern.** The
monthly review decides on the count, not on the best story.

## The retrospective is how the team learns

Before a feature's sandbox is removed, a session reads everything the developer
saw and typed during the whole feature and answers:

1. **What you may have missed** — a warning that scrolled past, a promise a
   session did not keep, a follow-up never filed. Acted on while the sandbox
   still exists.
2. **How you could work better** — where you waited, where you went round the
   same loop, where a clearer answer would have saved a session.
3. **What SClaude could do better** — a misleading message, a stalled step,
   work a session did that a script could have done. Named down to the file.
4. **What went well** — across a team, that is how best practices surface:
   from real features, with evidence, without a meeting.

**Facts only.** Every point quotes a line from the recording or names a file.
An empty section is a fine answer. *That's how the ones behind catch up with
the leaders* — and nobody else is judging.

## Where a lesson ends up, and who decides

A lesson starts with one person and climbs only as far as it proves itself.

```
one developer          →   the product's team      →   every product
a personal rule            a team rule                 a SClaude default
decided by the developer   decided by a maintainer     decided by SClaude's maintainers
```

An add-on can stay yours alone. If it proves itself, it becomes your company's
rule. And if your company wants, it can contribute it back to SClaude, like in
any open-source project. That's your choice, not a rule.

**Nothing changes the process by accident. Everything that should change it, can.**

## The tool repairs itself

When a session runs into a flaw in SClaude, it does not edit the shared
checkout. It logs the friction; the friction review, the monthly review or the
retrospective fixes SClaude in a workshop of its own, reviews the change, and
SClaude publishes it — checked for your product's details first, and by
default only on your yes.

> "Whenever an issue happens multiple times, the feedforward and feedback controls should be improved." — Birgitta Böckeler, Harness engineering

## Read more

- [When a session finds a bug in sclaude](https://github.com/personalautomation/SClaude/blob/main/docs/team.md#for-a-team)
- [The tool repairs itself](https://github.com/personalautomation/SClaude/blob/main/docs/cycle.md#the-tool-repairs-itself-and-says-what-a-machine-lacks)
