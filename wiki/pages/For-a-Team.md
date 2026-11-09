# For a team

> **A developer's job is to develop. Mentoring is done automatically.**

SClaude works for one developer and scales to a team. Alone, you get the whole
process from day one. In a team, it is the shared tool everyone uses and
everyone improves — instead of a zoo of private ones.

## One copy for everybody

**Nobody forks.** Everybody installs from the same repository, and every
command first looks at the latest `main`, so a fix reaches the whole team at
their next command (or their next `sclaude update`, if updates are set to
notify).

| what | where |
|---|---|
| the orchestrator, its prompts | SClaude's repository, one copy for everybody |
| the product and its process: tests, manuals, environments, board | `.sclaude/config.json` in the product, committed |
| the team's rules and prompts | `.sclaude/team/` in the product |
| one developer's rules and prompts | `.sclaude/people/<name>/` in the product |
| one machine's working files, recordings | `.sclaude/local/`, never committed, never deployed |

## Knowledge becomes company capital

Today each developer keeps their own prompts, workarounds and tricks, and the
tools change faster than anyone writes a tutorial. Here it all lives in git,
where it compounds instead of walking out of the door.

- **What is kept:** the process (stages, gates, prompts), the rules, the
  friction (every refusal, reviewed and decided), the lessons.
- **How it spreads:** a fix reaches every developer at their next command; a
  personal rule that proves itself becomes the team's; a new hire starts with
  everything the team has learned.
- **How it teaches:** each retrospective tells the developer, from their own
  run, how to work better; "what went well" surfaces best practices with
  evidence; whoever lags gets coached from facts, not in a meeting.

## You don't have to change how you work

Rules and prompts come in layers — SClaude's core, presets for the stack, the
team's, each developer's — with your prompts appended after SClaude's own for
each step. The committed config is what the team recommends; a choice you make
in `sclaude config` stays on your machine.

## Onboarding

Clone the product: its config is already there. One install script, then
`sclaude doctor` lists what the machine lacks and the command that fixes each
gap. A product without a config gets one written on the first `sclaude new`,
read from what is already in the repository and shown for confirmation.

## Who changes the orchestrator

`MAINTAINERS` lists who may commit SClaude straight to `main`. Everybody else
runs `sclaude propose`, and the change goes out as a pull request. A session
that finds a flaw in SClaude fixes it in a workshop of its own and sends it
back reviewed, on your word.

## For a startup, for an enterprise

- **A startup** needs features fast on a small budget: one path, lean
  sessions, people in charge.
- **An enterprise** has other worries: tokens across hundreds of developers,
  standardisation, process quality, hard limits on what AI may do, metrics
  nobody fills in — and above all knowledge sharing: lessons grow into company
  capital instead of leaving with the person who knew.

## Read more

- [For a team, in full](https://github.com/personalautomation/SClaude/blob/main/docs/team.md)
- [CONTRIBUTING.md](https://github.com/personalautomation/SClaude/blob/main/CONTRIBUTING.md)
