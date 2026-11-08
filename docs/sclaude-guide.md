# bin/sclaude

One command that knows every feature in progress, remembers which step each is
on, and launches `claude` with the right model, permissions and prompt for it.

```bash
sclaude                 # the menu: features in progress, chosen with arrow keys
                        # (none in progress: the issue list, with config last)
sclaude new [name]      # start a feature at step 1 (--issue <n>, --create-issue, --no-issue)
sclaude <name>          # continue a feature from its current step
sclaude status          # every feature and its step
sclaude actions [name]  # everything you can do with one feature, in one list
sclaude doctor          # what this machine lacks, and how to fix it
sclaude config          # the product's settings, each one explained; set <key> <value>
sclaude dev [name]      # start a feature's dev server; --stop to stop it
sclaude sync <name>     # merge the latest main into a feature's branch
sclaude news <name>     # what has happened on the pull request
sclaude preview <name>  # deploy the branch to a preview
sclaude rollback <name> # put production back to the release before this feature
sclaude regression <name> prod  # run the production tests again; green (or no production tests) lifts a hold
sclaude replan <name>   # take a feature back to step 1 and plan it again
sclaude parts <name> stop  # a feature built in parts ships with the parts built so far
sclaude return <name> [reason]  # send a finished feature back to step 4
sclaude reset <name>    # start the current step over, forgetting its conversation
sclaude done <name>     # clean up after the merge: worktree and branches
sclaude drop <name>     # abandon a feature and remove its traces, here and on GitHub
sclaude propose         # send your commits to sclaude as a pull request
sclaude workshop        # a session that changes sclaude with you, in a worktree of its own
sclaude update          # take sclaude's latest main (updates on notify or off)
sclaude core-send       # in a feature's tree: send the workshop change you held back
sclaude core-open       # run by a session: open the feature's workshop to change sclaude
sclaude core-ready      # run by a session: its change there is reviewed; publish it at the end
```

The tab sclaude runs in is named for the feature it is on, as its Telegram
topic is: `<slug> · <repo>`.

`sclaude --help` has the rest. In the menu, tick "show actions after choosing" to
get every action for a feature in one list instead of remembering commands.

## A feature, start to finish

**Starting.** `sclaude new` offers the repository's open issues, yours first;
in the terminal each one shows its column on the GitHub board in yellow, last
on its line.
The chosen issue suggests a branch name, which you can edit. sclaude moves the
issue to `In progress` on the board and fills in its start date. Before it
creates the worktree, it brings the main checkout up to `origin/main` (a
fast-forward, and only when it is on `main`) and, if its lockfile moved, runs
`npm ci` there: the new worktree links the main checkout's `node_modules`.
An edit in the way of the fast-forward, or a Node process working in the main
checkout (a dev server, a typecheck, a test run), leaves it as it is, with a
warning that says what to run once it is out of the way.

**Closing a session from sclaude's terminal.** Under Windows Terminal in WSL a
session runs in a tab of its own, and while it works the tab sclaude waits in
takes keys of its own; they are listed, a word each, on one line under the
line that says the first session started (the same keys are not listed
again for the next ones), and `k` is a box on the status line. Every session sclaude starts closes by itself once its work is done;
these give you the word instead, and change nothing else: going forward is
the session's own end, going again is your `/exit`. The letter says which, the
case says when — lower case goes on now, upper case stops sclaude until the
next `sclaude <feature>`. Every key is pressed twice in a row, so a stray one
does nothing: the first press shows the key and what it does in yellow on the
status line, and the second press or any other key clears it:

| key | what happens |
|---|---|
| `n` | forward, now: closed as if it had ended itself — its marker written, the plan on screen counted as approved, step 2's work as accepted, so you skip the turn Claude would spend reading your approval; its friction review and the step's checks run, then the next step |
| `N` | forward, later: the same, and sclaude stops before the next step's session (after step 4, before the preview) |
| `r` | again, now: closed as `/exit` closes it, and the same conversation opens again at once, with no message to it |
| `R` | again, later: closed as `/exit` closes it, and sclaude stops; the next `sclaude <feature>` opens this conversation again. A step's session has its friction review first |
| `k` | keep it open: it does not close by itself when its work is done, and you leave it with `/exit`; twice again, and it closes as usual |

The retrospective has no marker written for it by `n`: its own marker means
"nothing to act on", so `n` closes it as its `/exit` would. With no tab (over
ssh, or inside code-server), claude has the terminal to itself and there are
no keys.

**Step 1, plan.** Claude gets the issue, its parent issues and the manuals'
contents up front. It tells you what it understood and waits; you correct it,
and only then does it plan. The plan ends with **acceptance criteria**: a
numbered list (`AC1`, `AC2`, …) of things a person can check on a deployment
without reading the code. When you approve, the criteria go into the issue as a
comment of their own. sclaude never edits an issue's description: the original
request, the criteria and the status are separate comments, so the task as it
was given stays readable.

A feature too large for one review (about 10,000 changed lines) is offered as
a split. If you take it, it stays **one feature: one issue, one plan, one QA**,
built in parts. The plan gets a `## Parts` section (`### Part 1 — …`) and each
criterion names its part (`AC7. [part 2] …`). Step 2 then builds the parts one
after another, each in a session of its own on its own branch
(`feat/<slug>-1`, `-2`, …) over the part before it. No pull request and no
review yet: before a part closes, a fresh subagent reads its diff for what
would cost more to fix later — the design the next parts build on, bugs the
tests miss — and the session fixes what it agrees with. Ask for something
while a part is built and the session decides where it goes: now, when it
touches what is built; into a later part of the plan, when that part covers
it. Nobody is asked whether a part works, and no demo is recorded for one —
unless the project sets `partAccept` to `each` (`sclaude config`), and then
each part ends on its demo and your Accept too. When every part is built,
step 2 closes on the last part's branch as for any feature: the whole thing
checked as one, the demo, your Accept.

Only then are the parts reviewed, one by one, in the order they were built:
for each, its branch takes in the part before it as its review left it and
the feature's branch, step 3 opens its pull request into the feature's
branch, step 4 reviews that part alone, and sclaude merges it there. After
the last part, step 3 opens the feature's pull request into main, listing the
parts' pull requests and closing the issue, and step 4 reads the seams
between the parts. Preview, QA, the merge and production happen once, for the
whole feature. The menu shows where the parts are: `2/7 development · part
2/3` while they are built, `4/7 review · part 2/3` while they are reviewed.

Before each part's pull request and each merge, sclaude checks that GitHub still
holds the parts as it left them. A base changed by hand, a part's pull request
merged or marked ready before its review closed, or a part's branch rewritten
on GitHub stops the cycle with what to do. A part whose branch does not take
the feature's branch in without conflicts — an earlier part's review fix
meeting this part's code — gets the sync session, as a conflict with main
does: it merges the feature's branch, keeps what the reviews decided and
adapts the part to it. A part merged early is asked about: take it as the
part's end, or leave it to you.

To ship a split feature with the parts built so far, `sclaude parts <name>
stop`, while the parts are built, leaves out the part at work and the ones
after it: step 2 closes on the parts kept, and its session strikes the left-out parts' criteria, files them
as an issue of their own and takes them off the issue's list.

**Step 2, code.** A fresh session builds it, with the approved plan as its
brief. Each commit names the criterion it serves in a `Requirement:` footer.
Claude checks its work in Chrome at the feature's address. Before it asks, it
records a demo of the feature, on a desktop and on a phone
([skills/sdemo](tools.md#skillssdemo)) — after your remarks that changed the code, a
short delta of only what changed for a user, then the whole demo again — and
gives the link first in its report; the link
and the videos go to the feature's topic and to a demo comment on the issue,
where QA finds them; a new full demo takes the earlier one out of both, and
the feature's demo page keeps every version as its history. It ends on one question in its own dialog: **Accept**, and the session closes and sclaude goes
on with no question of its own; **Remarks**, and you say what is wrong and the
session carries on. The step closes when you accept the work **and** the
product's local tests pass. A branch not
pushed yet is put on top of main before those tests, without a question, when
it rebases cleanly.

**Step 3, pr.** The pull request, opened as a draft by the `pr` skill, with the
criteria copied in as a plain list for QA, who ticks them in the issue, and the
manuals updated in the same pull request.

**Step 4, review.** The project's automatic review reads the pull request, and
a session fixes what it found, one round at a time. The step closes when the
review has nothing left open, the preview is deployed and its tests pass.
Once the preview's tests pass, before the issue goes to QA, when the
product's code changed since the last demo — the review may have changed what
the feature does — a headless session records a delta of what changed for the
user and the whole demo again, starting from the last script and what changed,
and the issue's demo comment is replaced: step 2's demo is for you accepting
the work, this one for QA to see what the feature is and what changed. Only
where a person does QA (`qa: github` or `both`); with `qa: auto` the whole demo
is recorded again before the last epilogue instead, and no delta. Where
nothing a user meets changed — tests, a refactoring, a fix nobody sees — that
session records nothing and keeps the demo there is (`demo.py keep`), and
sclaude says why. Nothing it records goes out while it works: the last delta
and the last full recording it made are sent to the topic and the issue after
it, once each — none when it ended by keeping the demo — and a try it fixed is
sent nowhere. What it found wrong
in the product while recording — a check that failed, a fault it had to go
round — is printed in sclaude's terminal. At night (`/isleep`) a finding the
session would leave as it is does not hold the step till morning. A minor one the
review posted, with no reply under it yet — nothing at risk for users, data or security, nothing promised changed, no check
weakened — the session resolves itself, with a reply saying it was resolved at
night without you, and lists it in its report; unresolve it on GitHub to make it
open work again. Any other waits for you, and in the morning sclaude offers a
session that asks you about each such thread and, on your yes, replies and
resolves it on GitHub itself. The
report after each round has a row per review run, in the order of the cycle:
`find` — what the run found and what it cost, the pass on this machine as
Claude Code accounts for it (`—` for GitHub's review, which sclaude cannot
price); `fix` — the session that fixed those findings, its time and cost, and
what it declined; and `result` — fixed, waiting. A `w` is a value not known yet: a run
still going, findings no session has started on, a launch whose cost comes
when it ends. When the
report says the rounds stopped converging, or that the fixes are feeding the review two rounds running, its verdict is red, and the
feature's topic is told once, with the keys that end the search for new findings. What a round leaves open goes back
to a review session without a question: `s` (⏭ on the topic) is how the rounds
end, `n` and `r` in sclaude's tab act at once. Leaving the session yourself
(`/exit`) stops them there, unless `[g]` is ticked: the step stays open until
the next `sclaude <feature>`. A round goes back to the same session while
its context is under 40% and its last request is under 55 minutes old, so its
prompt cache is still warm; otherwise a fresh session takes it, which costs
less than resending a cold context. Once you end the search, one
question with three answers settles the rest: check the fixes, close the step,
or leave it.

With the review on this machine, its status line shows two boxes while a pass
runs, ticked until they apply: `[s]` makes the pass the last that looks for
new findings, and `[g]` lets the review go on by itself — no question after
it: a pass that failed runs again after a pause that grows by a minute each
time (ten times in a row, then you are asked), the fixes are
checked and what is open goes back to a review session, for 30 rounds at
most, then it is off for that step 4 and you are asked (a press of `[g]` then
turns it on). In a project whose review runs in Actions, the wait for it shows
`[g]` too. The friction review, which
waits for you to approve its plan, is not opened after step 4's sessions (a
review round's, a sync's, a regression fix's) — unless you typed `sclaude
friction` or `sclaude sync` at the terminal yourself: their
log is kept for the next friction review after the box comes off, and at the
latest for the one before the retrospective; step 4 itself goes on. Each key pressed again
takes its box back. `[g]` has three values, in turn on each press: `auto`
(the default — the project's `sleep_mode` decides: by default, an /isleep night
over every session, not an `/isleep here` one —
and the box shows `auto ☑ (night)` or `auto ☐`), `on` (☑) and `off` (☐); on
and off are yours and stay for the whole review, step 4 reopened included. `[n n]` (forward, now — the letter of the session keys below) stops the pass at once. A pass that did not run
asks whether to go on with the head unreviewed, and `n` reviews it again
rather than leaving sclaude. While a review session works in its own tab, the
terminal sclaude waits in shows the same two boxes and takes `[s]` and `[g]`
too; `[s]` said then ends the search, so after that session sclaude asks
whether to check its fixes — or checks them, with `[g]` ticked.

**QA, merge, production.** The issue moves to `In QA`, and sclaude waits — you
can close the terminal; a background timer keeps watching the board. QA checks
the criteria on the preview and ticks them in the issue.

- QA moves the issue to `Done`: the pull request is marked ready and gets a
  summary for whoever merges, and sclaude goes on to the merge.
- QA moves it back to `In progress`: their comments are collected word for word
  and a review session opens with them.

You can also send a finished feature back yourself with `sclaude return`.

**A branch that does not merge with main is synced first.** Before the
preview, again after QA's yes, and every two minutes while it
waits for the merge, sclaude asks git whether the branch still merges with
main — no session and no tokens for that. When it does not, step 5 merges
main in, resolves the conflicts, checks the result and pushes; the preview,
its tests and QA then run again on that code — QA only when the branch's own
product changed: what main brought in and files that are not the product
(`.sclaude`, `docs`, `.github`, `.githooks`, `*.md`) leave QA's yes
standing. A conflict only in the deferred logs sclaude merges itself, with
both sides' rows. A pull request already
handed over for the merge goes back to a draft when a sync changes its code.
Every step starts on a branch carrying the latest main, too: sclaude merges
it in without asking, and a merge that would conflict goes to the same sync
first. With uncommitted work in the tree it merges nothing and says so; the
merge is then `sclaude sync <name>`, which goes the same way — the menu's
line says beforehand whether a session will be needed. A merge left half-done in the tree holds the step until it is
finished (`sclaude sync <name>`) or backed out (`git merge --abort`).

The merge is yours (unless the product set it otherwise). After it sclaude
offers production, runs the tests there, and rolls back if they fail.

**Epilogue and retro.** A short session writes the outcome into the issue and
every parent issue, so an epic shows where it stands without opening each child.
The issue gets `deployed-preview` / `deployed-prod` labels, and its end date is
filled in. Then `sclaude done` first runs every friction review still owed — one
held under `[g]`, one cut off, a log no review read — then the retrospective,
and asks before removing the worktree and branches.

Every Claude session sclaude starts, its model and permissions, and where the
issue's summary table shows it:

| Session | Model | Permissions | What it does | In the issue |
| --- | --- | --- | --- | --- |
| 1. plan | opus / high | `plan` | Discussion; the only file it may write is the plan | a row |
| 2. code | opus / medium | `auto` | Implementation, checking in Chrome, commits | a row |
| 3. pr | sonnet / medium | `auto` | The manuals and the pull request — calls the `pr` skill | a row |
| 4. review | opus / medium | `auto` | Fixing review findings, one round at a time; a QA hand-back or a production rollback reopens it | a row per session, with its rounds |
| fix after a regression | as step 2 for the local tests, as step 4 for the preview's and production's | `auto` | Makes red tests green; after a rollback it is told what failed on production | a row per session, with how it ended |
| 5. sync | sonnet / medium | `auto` | Only on a conflict with main: the merge of main into the branch, its conflicts resolved, checked and pushed | a row per session |
| 6. epilogue | sonnet / medium | `auto` | The outcome as one comment per issue, on the feature's issue and every parent; changes nothing in the repository | a row |
| 7. retro | opus / medium | `plan` | What you missed, how to work better, what sclaude could do better. What it fixes goes on the feature's branch and sends the feature back to step 3 | a row |
| friction review | opus / medium | `plan` | After each step and fix session: reads what the safety rules refused, and loosens a rule that was in the way | the Friction column of that row |
| local review pass | opus, `claude -p` | read-only | With the project's review set to `local`: finds problems in the pull request before step 4's session | a row per pass the journal recorded, with the findings it posted; the findings land on the pull request, the report in the feature's Telegram topic |
| friction matching | haiku, `claude -p` | no tools | One call that matches proposed rules to the ones already put off | not in the table: it is not a session |
| monthly friction review | opus / medium | `plan` | `sclaude deferred`: the rules put off across features | not on a feature's issue: it belongs to none |
| sclaude's workshop | opus / medium | `plan` | `sclaude workshop` (the bot's 🛠): changes sclaude with you in a worktree of its own, reviews it and publishes it on your word | not on an issue: it belongs to no product |

## Environments and databases

**Which database a feature uses is your machine's choice.** The product names
its environments in `.sclaude/config.json`, each as a `.env` file
(`"dev": {"env": ".env.dev"}`). sclaude asks once which one this machine works
against and remembers the answer; `SCLAUDE_ENV` overrides it. There is no
default, because a wrong guess is a quiet mistake. A feature is never pointed at
production.

**On a local database, every feature gets its own.** When the chosen
environment is the product's local Supabase, each feature gets a Supabase stack
of its own in Docker, filled from the main local database or the product's
seed. It is removed with the feature. If Docker is not running sclaude starts
it, and falls back to the shared local database, saying so, only when it cannot.
The main local database is kept on main's migrations: sclaude applies what a
merge brought at the end of the cycle and before each copy, and says so.

**Every feature has its own address**, `http://<feature>.localhost:3000`,
printed at the start of each step. A feature nobody has opened for half an hour
is stopped, database included (data kept), and starts again on the next visit.

## Switches

| variable | effect |
|---|---|
| `SCLAUDE_ENV` | the environment to use, instead of the remembered answer |
| `SCLAUDE_DEV` | your name, instead of `sclaude.developer` or the one from your git email |
| `SCLAUDE_NO_SYNC=1` | do not pull the latest sclaude before a command |
| `SCLAUDE_NO_RELOAD=1` | do not switch to newer sclaude code after a long session |
| `SCLAUDE_PANE_FOCUS=follow` | let a session's new tab take the focus; by default it stays on the tab you were in |
| `SCLAUDE_TERM=off` | do not record the terminal (recordings are kept 60 days) |
| `SCLAUDE_RETRO=off` | skip the retrospective |
| `SCLAUDE_FRICTION_ASK=on` | ask before putting proposed CLAUDE.md rules off to the monthly review |
| `SCLAUDE_FRICTION_CLASSIFY=off` | put proposed rules off as they come, without matching them to the classes already there and to CLAUDE.md |
| `SCLAUDE_DEV_IDLE` | how long an unused feature keeps running |
| `SCLAUDE_DOCKER_START=off` | never start Docker |
| `SCLAUDE_DOCKER_WAIT` | how long to wait for Docker to come up, in seconds (120) |
| `SCLAUDE_DOCKER_DESKTOP` | where Docker Desktop is, when it is somewhere unusual |
| `SCLAUDE_DB_WAIT` | how long a feature's own database may take to answer after its start reported a failure, in seconds (120) |

## What sclaude writes, and where

| what | for | where | in git | uploaded by a deploy |
|---|---|---|---|---|
| `.sclaude/config.json` | what the product is, and the settings it recommends | the product | yes | no harm if it is |
| `.sclaude/local/config.json` | the settings you chose in `sclaude config` or the bot, over the recommended ones | the product's main checkout | never | never |
| `.sclaude/team/`, `.sclaude/people/<name>/` | rules, prompt additions, deferred findings | the product | yes | no harm if it is |
| `.sclaude/local/feature/` | one feature's working state: the plan, logs, its database settings | the feature's worktree | never | never |
| `.sclaude/local/demo/` | the feature's recorded demos: videos, steps, the page | the feature's worktree | never | never |
| `.sclaude/local/terminal/` | terminal recordings the retrospective reads | the product's main checkout | never | never |
| `.sclaude/local/dora/` | the product's DORA page and what it was built from | the product's main checkout | never | never |
| `.vercelignore` | keeps `.env*` and sclaude's files out of a deploy | each tree sclaude deploys | no, unless the product tracks its own | — |
| `~/.claude/sclaude/` | your cycle records, remembered choices, running dev servers | your home | never | — |
| `~/.config/sclaude/` | this machine's settings | your home | never | — |
| comments, labels, board moves, `Sclaude-Session` commit trailers | the feature's story where the team reads it | the product's GitHub and history | the trailers | — |

The cycle records are one JSON line per feature in `~/.claude/sclaude/cycles.jsonl`,
readable with `jq`:

```bash
jq -s '[.[] | select(.outcome == "done") | .steps.code.seconds] | add / length' \
  ~/.claude/sclaude/cycles.jsonl
```
