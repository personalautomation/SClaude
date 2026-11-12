# How the cycle is kept in line

The detail behind [What it solves](../README.md#what-it-solves): what closes each step, what
is refused, the gates, the rollback, what is counted and which decisions a
product may hand to sclaude.

## A step closes on a result, never on a model saying "done"

| step | what actually closes it |
|---|---|
| plan | a plan you approved, with criteria |
| code | your yes **and** the product's tests passing |
| pr | a pull request that exists on GitHub |
| review | the automatic review has nothing left open — no thread unresolved, no check running or red — **and** the product's local tests passing; the pull request stays open for QA. No session at all when the review found nothing. The preview and its tests come after the step: a red preview puts the feature back on it |
| fix after a regression | the same tests run again and pass. Two sessions that do not get them green stop the cycle for you. A session that finds the cause outside the branch changes nothing and leaves a note; the tests then run once more by themselves (a flaky test goes green), and a second such note stops the cycle with it for you. A note is kept in the feature's `regression.notes` once it is answered, for whatever it says would have to change |
| sync | sclaude's own check after the session: no merge left under way, nothing uncommitted, the branch merging cleanly with main, and pushed. Otherwise the session is offered again. Then the preview, its tests and QA run on what it pushed |
| epilogue | the session actually ran; one that never started is offered again from the menu |
| retro | its session finished. A later `sclaude done` goes back into the same conversation, told what ran since — a rollback, another round — and asked to check its report against it; with nothing run since, it asks first |

Ctrl-C, a usage limit or a closed laptop closes nothing: sclaude remembers where
each feature is, and the conversation resumes. An interrupted run is never
mistaken for a finished one. A step whose session has finished and which waits
only on its tests goes back to the tests, not into the finished conversation.


## Contain — the blast radius of a mistake

Every feature gets its own copy of the repository (a git worktree), its own dev
server at its own address, and, where the product supports it, **a database of
its own**. A migration written for one feature cannot reach another, and a
database reset wipes nobody else's data.

## Curate — what the agent can see and reach

The agent's world is set up before it runs. Each step has its own model and
permissions; in step 1 Claude cannot write code at all. What the product is —
its tests, its manuals, its environments, its board — the product describes in
`.sclaude/config.json`, so sclaude assumes nothing about anybody's repository.

## Control — the rules apply as the action happens

sclaude refuses these commands at the moment a session tries them:

- **merging a pull request** — that is a person's decision;
- **pushing to the product's `main`**, force-pushing, skipping the pre-push hook;
- **promoting migrations to production**, **switching to the production
  environment**;
- **writing code during planning**;
- **deploying to production** without asking: sclaude asks you, with no
  default, and words it "Ship to production **anyway**?" when QA never saw the
  feature.

These rules catch mistakes, not a session determined to get round them: a
command written to a file and run from there is beyond what they can see. If
your GitHub plan offers branch protection (free on public repositories, paid on
private ones), turn it on for `main` as well: require a pull request and allow
no direct pushes.


## Quality gates, in the Definition-of-Done sense

The product's tests run at up to four points: locally, on the preview, on
production, and once more after a production rollback. Each point runs what the
product declares. A failed run is run once more by itself, since the commonest
red is a flaky test; if it fails again, a fixing session opens, at most twice,
and then a person is asked rather than looping for ever.

A branch that changes only files no test and no deployment reads skips the local
tests, the preview, QA and production: it goes through its pull request and
review, then the merge. These paths count as such in every product:

| path | why |
|---|---|
| `.github/` | CI workflows and bot settings; they first run on the pull request |
| `.sclaude/` | the orchestrator's own files |
| `.githooks/` | local git hooks |
| `docs/` | prose nothing builds |
| `*.md` in the root | `README.md`, `CLAUDE.md` and the like; Markdown deeper in the tree may be content, so it counts |

One file anywhere else and the branch goes the whole way. A product whose
`docs/` is built into its site is the case this assumption gets wrong.

A feature too big to build and show in one go is built in parts, at the
person's word at step 1. The parts are built one after another, and each one,
once built, is shown to the person in a short demo of what it added, recorded
before the next part starts, so that a remark reaches the next part early. The
person accepts the whole once — the demo, built from the parts' own, and
Accept — before any review is spent: a review of code the person has not seen
is thrown away by the first large remark. Then the parts become one branch,
and the feature goes to main through one pull request, reviewed, previewed,
tested by QA and shipped once.

A pull request too big for one review is read in review blocks. Past 5,000
changed lines a review reads part of the diff and calls the rest clean, so
step 4 cuts it, once, from the finished code: each block a group of the plan's
criteria with the files that carry them — by behaviour, not by layer, since a
rule's bugs are where the database, the server and the screen meet — every
changed file in exactly one block. sclaude checks the cut; a cut that fails
twice gives way to the parts the feature was built in, or to a single read.
The blocks are read one after another, each to a clean verdict, every round
after a block's first read taking in the new commits across the whole pull
request; a last pass reads the seams between the blocks. While blocks are
read the review runs on the developer's machine; under a GitHub setting the
project's CI still counts.

## Production rollback that refuses to trample somebody else

If the tests fail on production, sclaude rolls production back to the release
before the feature and runs the tests again to confirm the old release works —
before anybody starts fixing. If somebody else deployed in the meantime, nothing
is rolled back: that release is not ours to remove. Migrations are undone only
where their undo instructions can actually be run, and sclaude shows the SQL and
asks first. The code is rolled back on Vercel, the hosting sclaude knows how to
ask for the previous release; on any other, production is rolled back by hand.

While production carries a feature whose last production tests were red — the
rollback failed, you declined it, another release sits on top, or the tests
could not run in a broken environment — sclaude holds the feature, and the menu shows it as
`steps done, production held`: nothing is shipped, closed or cleaned up, and it says which
way out fits. `sclaude regression <name> prod`
runs the production tests again and, green, lifts the hold — as it does when
the project has no production tests (`prodRegression` set to `none`, or no
list for production);
`sclaude rollback <name>` puts the previous release back and sends the fix to
the review step; `sclaude return <name>` sends the fix forward from the review
where going back is not possible. The bot's action list offers the production
tests again too.

## The tool repairs itself, and says what a machine lacks

The friction review fixes the rules that got in the way. When a session's log
holds only proposed CLAUDE.md rules, sclaude puts them off to the monthly
review itself, with no session and no question; `SCLAUDE_FRICTION_ASK=on`
asks first, and `n` then has a review session write them in now. A small model
first matches each to a class already put off, or to a rule CLAUDE.md already
states, and sclaude says how many times its class has come back this month. `sclaude doctor` lists
what a machine is missing and the command that fixes each gap, so onboarding is a
checklist. The retrospective at the end reads a recording of the whole run — what
sclaude printed and what you typed — and says what could go better and, when
the run points at one, a setting that would suit how you work. What a setting
you chose does by design (`qa: auto` ticking the criteria, say) it does not
report as something you missed. Where the feature's way left the process map,
sclaude hands it the places, and it says whether the map or the code is wrong
there and how to fix it. The monthly review
can add the same, and also finds lines in CLAUDE.md, other instructions and
Claude Code's memory that the tool's changes made untrue, and proposes tools to
install or remove — each only on evidence, with how sure it is. It weighs a
new rule against loosening or dropping one, and reads what was decided about
sclaude's code before proposing to change it.

## What is measured

One record per finished feature: time per step, test attempts, what failed, how
far it shipped, who ran it. Enough for the four DORA metrics from real cycles
rather than guesses — and sclaude draws them, with the rest of what it counts,
on a page under `main` at `http://localhost:3000/` ("main — DORA metrics"):
the four DORA keys with rework and hotfix rates and lead time by stage; a pull
request's way — coding, pickup, review, merge and deploy time, maturity;
features shipped, cycle time, time to market, flow efficiency; software
quality — escaped defects, reopened issues, work by commit type, regression
green first time, review threads, acceptance criteria; code health and
project hygiene; and Claude's own work — sessions, autonomy (tool calls per
human input), what of Claude Code is used, when the work happens, the share
of commits it wrote, and what a feature, a deploy or a pull request cost,
week by week. The review is counted per feature, over all its pull requests:
rounds (runs of the review, not sessions), threads, and the share closed
without a fix or still open. The requirements are read from each issue's
history: how many features had theirs change significantly after the plan was
approved, and how many started unclear — as many clarifying questions in
planning as the feature has acceptance criteria. How much a person had to
work for what Claude did is counted from every time they stepped in: Claude's
run between interventions, the sessions nobody stepped into, the person's
minutes per hour of Claude, week by week. One radar puts it together — eight
directions (speed, stability, quality, requirements, flow, autonomy, cost,
discipline), each its figures scored by their own bands — with a health index
and the imbalance between the best and the worst direction. A table of
contents on the left, which folds away, leads through the parts. With
`metricsTeam` set to `demo` (`sclaude config`, or `.sclaude/local/config.json`
for one machine only), a team part lays developers
side by side — output, speed, quality, AI adoption and effectiveness (Claude's
share of their commits, subagents, skills, plan mode, the prompt cache, how
often they step in or turn Claude down), cost, who holds what and who works on
what, and for each person their strong sides with Claude and what to work on,
with a habit to try — with three generated teammates drawn from the real figures, to
show the page with a team. Each figure is coloured good, watch or poor where
a standard band exists, and shows on hover (a tap on a phone) why it matters, what to aim for
and how it is counted. A switch at the top compares features of different
size: the figures marked ◆ — cycle time, time to market, review rounds and
threads, questions and spend per feature, and the weekly charts of what was
shipped, in work and spent — are divided by each feature's size, in standard
features (its acceptance criteria; the median finished feature is one). A
closing list names what such scorecards ask for and the page cannot measure,
and why.

## Two deliberate choices

**Review is an agent's, the merge is a person's.** This is Anthropic's own
division of labour for [Claude Code Review](https://claude.com/blog/code-review) — *"It won't approve PRs — that's
still a human call"* — and their reported effect is the argument for it: before,
16% of pull requests got substantive review comments; after, 54%.

What is left to you is the decision, and sclaude prepares it. Before asking
whether to merge, it shows the acceptance criteria as QA left them, the checks,
and the review's findings with what was done about each — including the case
where the review check is green but reviewed nothing. The question has no
default: it waits for a yes or a no, and reads "Merge it **unchecked**?" when
QA never saw the feature.

A product may hand either decision back to sclaude, in `.sclaude/config.json`
or from `sclaude config`. The committed file is what the project recommends; a
choice made in `sclaude config` (or the bot's 🧩) is your machine's and goes to
`.sclaude/local/config.json` beside it, outside git, where it wins key by key.
Setting a choice back to the recommended value removes it from there. The main
checkout's copy is read for every feature. A hand edit of the committed file
left uncommitted there holds production up until it is what origin holds: the
stop lists where the two differ, and you commit and push the change, or take
origin's copy and set your own choice with `sclaude config`. `qa` and `merge` each take `github` (a person does it
on GitHub; sclaude waits), `both` (the same, or a key in sclaude's wait — `a`
accepts, `m` merges) and `auto` (sclaude does it). By default QA is `github` and
the merge `both`. An acceptance given by sclaude says so in a comment on the
issue.

Production and the suites against the deployments are set the same way.
`ship` takes `ask` (the default: "Ship to production? [y/n]" after the merge),
`auto` (shipped without that question; it is still asked where QA or a check
was passed over on the way, or where other features' code not yet in
production would go out with it) and `off` (sclaude never deploys production; the
issue closes as merged and accepted, and you ship it by hand). Nobody
answering the question — the terminal closed, the phone silent — is not a
no: nothing is closed or cleaned up, and the next `sclaude <name>` asks again.
`previewRegression` and `prodRegression` each take `full` (the stage's list in
`regression`, the default), `smoke` and `none` (no suite there, and no gate).
Smoke is the product's few vital paths, and the product says what they are:
their parts in `regression.smoke`, their command in `commands` — a part called
`smoke` runs against the deployment the way `e2e` does, so
`"smoke": "npx playwright test --grep @smoke"` over the same suite, with the
vital specs tagged `@smoke`, is the usual setup. Step 2's session tags the one
spec that walks a new path people depend on. A product that chose `smoke` and
declares no smoke list gets its full list, said in the run's heading.
`demo` takes `on` (the default: step 2 records a demo video of the feature
before its question, and it is recorded again when the code changed since —
before QA, or before the last epilogue with `qa: auto`) and `off` (no demo videos anywhere in the cycle; the report and the
criteria are the check).
`demoVoice` takes `on` (the default: the demo's videos are spoken, in English,
by a model run on the machine's CPU — see [skills/sdemo](tools.md#skillssdemo))
and `off` (silent videos, the captions alone).
`reviewBlocks` takes `from`, the changed lines past which step 4 reads a pull
request in review blocks (5000), and `size`, the lines a block holds at most
(3000).
`partAccept` takes `whole` (the default: a feature built in parts is accepted
once, whole, when every part is built; each part before the last is shown in a
demo of what it added, which asks nothing) and `each` (every part's
session ends on its demo and the Accept question too, and the whole is
accepted again at the end).

Before sclaude merges, or asks to, it builds what the merge would put on main
when main has moved past the branch: the branch merged with the newer main, in
a throwaway worktree, through the `regression.manual` parts as that merge's
own config names them. Red is not merged from sclaude at all: `auto` says it is
held, and tries again once the branch or main moves. When it cannot be built
`auto` asks instead. GitHub calls a merge without conflicts clean, and nothing else would
notice a rename on main that the branch still calls.

**No staging between preview and production.** Preview is the last stop.
