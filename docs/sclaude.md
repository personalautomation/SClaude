# How sclaude works, and why

The README says what sclaude does and how to use it. This is the other half:
how each part works, the decisions behind it, and what went wrong before them.
It is written for whoever changes sclaude, or wants to know why it behaves the
way it does.

## The command hook

The hook guards against accidents, not against a session set on getting
round it. It reads the command line it is shown. Subshells, brace groups,
`bash -c '…'`, `eval`, a merge through `gh api` (REST or GraphQL) and a push
whose destination is a variable, a substitution or `refs/heads/main` are all
read and refused; a code review found each of them going through, and
`tests/hooks.py` now holds them. What it cannot see is a command written to
a file and run from there (`python x.py`, `bash x.sh`), or a git alias. No
hook can.

## The project's config

**What it knows about a particular project lives in that project.** The
regression's parts and the commands behind them, the manuals' paths, the
production host, the migrations directory and how they are promoted — all of it
used to be written into the library, so the promise above was not true: a second
repository would have needed the orchestrator edited rather than a file of its
own.

It is now `.sclaude/config.json` in whichever repository sclaude is run
from, and `sclaude new` offers to write one. Most of the answers are already in
the repository — package.json's scripts, the directory layout, whatever the
project keeps about its environments — so the wizard proposes and the human
corrects, in prose rather than as JSON: what is being agreed to is "these
commands will run against production one day", and a wall of braces is not a
thing anybody reads before saying yes.

Every feature reads the main checkout's copy, key by key (`project_config`,
`project_get`), not the one its worktree's branch carries: a key set by hand
in the main checkout — `merge: auto`, committed or not — reaches each feature
at once. A worktree's copy answers only a key the main checkout has none of,
a feature adding it; the readers that take a whole section (the feature's
database, the board) take it from there too when the main checkout has none
of it (`project_config_with`). One key is the other way round:
`commands["e2e:server"]`, how the local e2e serves the run's build, comes from
the worktree's copy alone (`regression_serve_command`), because whether a
build can stand in for the dev server depends on the branch's code. A change
to that file left uncommitted in the main tree does not stop production
(`prod_main_unready`): it is sclaude's settings, not the product, and the pull
before `vercel --prod` carries it across with `--autostash`.

Every section is optional and **nothing is defaulted**. A repository with no
config still gets the cycle — seven steps, a worktree, an issue, a pull request —
and loses only what the config would have described: there is no regression to
gate on, no manuals in front of step 1, no production to ship to, and each of
those says so where it would have acted. A default would be one product's answer
applied silently to another's repository, which is the failure this removes
rather than a convenience it gives up. `sclaude/config.example.json` is the
shape, with every key explained.

That includes the team's GitHub board: which column a started feature moves to,
which one means ready for QA and which one QA ends in, the date fields the Gantt
chart reads, the label and type of a new issue. They were one team's names
written into the library; now they are `board` in `.sclaude/config.json`, the wizard
reads them off the repository's project board and shows them for confirmation,
and a column that is not named is a move that is not made.

The script itself holds the environment, the commands and the argument parsing;
the body is spread across `sclaude/lib/*.sh` and pulled in with `source`. That
is not only about readability: the friction review session edits `bin/sclaude`
while it is executing, and bash reads a script lazily, by offset — an edit in
place shifts everything the process has not read yet. A module pulled in with
`source` is read whole at that moment, and editing it is no longer dangerous to a
running process.

## Staying current, and the code's layout

**Keeping the orchestrator current, and whose branch it is on.** Every command
that is about to act (everything but `status`, `dev`, `news` and help) first
fetches `main` and brings it in: a fast-forward on `main`, a merge on a
developer's branch. A dirty tree or a conflict leaves the code as it was and
says so; no network is silent; afterwards the process re-executes itself so it
does not run old code over new files. `SCLAUDE_NO_SYNC=1` turns it off.
The same holds at the end of a step's session, which may have run for hours:
if `bin/sclaude` or a module changed on disk meanwhile, the process hands what
follows claude's exit to the current sclaude (`code_reload`), so an `/exit`
is handled by the new code. `SCLAUDE_NO_RELOAD=1` turns that off.
`MAINTAINERS` names who may commit the orchestrator straight to `main`. The
update leaves everybody on `main`; a branch of one's own, `dev/<name>` (the
name comes from `developer.sh`), is for proposing a change to sclaude, and a
non-maintainer's commits there go out as a pull request (see "Who changes the
orchestrator"). No session sclaude runs changes or pushes the checkout: what a
session changes in sclaude it makes in its tree's workshop, and sclaude
publishes it (see "The workshop" below).

| File | What is in it |
| --- | --- |
| `bin/sclaude` | the environment, the `cmd_*` commands, argument parsing |
| `sclaude/lib/ui.sh` | questions to the human, answers, colours |
| `sclaude/lib/io.sh` | the question-answer channel: the same question in the terminal and in Telegram |
| `sclaude/lib/steps.sh` | the table of steps and each one's permissions |
| `sclaude/lib/project.sh` | what the project says about itself, and the wizard that writes it |
| `sclaude/lib/environment.sh` | which database this machine's features work against |
| `sclaude/lib/developer.sh` | who is running it, and whether they maintain the orchestrator (`MAINTAINERS`) |
| `sclaude/lib/doctor.sh` | `sclaude doctor`: what this machine lacks, with the fix for each gap |
| `sclaude/lib/state.sh` | the repository, `.sclaude/local/feature/state.json` and the cycle's record |
| `sclaude/lib/branches.sh` | sorting out branches with nothing left to hold |
| `sclaude/lib/worktree.sh` | preparing a feature's tree and the dev server |
| `sclaude/lib/run.sh` | launching a step, the transitions, the friction review |
| `sclaude/lib/github.sh` | issues and pull requests through `gh` |
| `sclaude/lib/plan.sh` | step 1's plan from its session's transcript |
| `sclaude/lib/deploy.sh` | preview, prod and the cycle's epilogue |
| `sclaude/lib/rollback.sh` | putting production back: the deployment, the down blocks, the incident |
| `sclaude/lib/picker.sh` | choosing with arrow keys: issues, menus, actions |
| `sclaude/lib/abandon.sh` | abandoning a feature: the traces here and on GitHub |
| `sclaude/lib/actions.sh` | the list of actions on a single feature |
| `sclaude/lib/terminal.sh` | recording sclaude's terminal — what it printed, what the person typed — for reading back |
| `sclaude/lib/retro.sh` | the retrospective over a merged feature, right before `sclaude done` removes it |
| `sclaude/lib/workshop.sh`, `workshop.py` | the tree's workshop, where a session changes sclaude, and the publishing of what it made there |
| `sclaude/lib/*.py` | gathering an issue's context, chain and acceptance criteria, reading migrations' `-- down:` blocks, the cycle's record, and assembling prompts |
| `sclaude/hooks/*.py` | the steps' bans and the friction log |
| `sclaude/prompts/*.md` | the steps' prompts and the shared includes (`_*.md`) |
| `tests/*.py` | benches for the hooks, the prompts, the project's config, the acceptance criteria, the down blocks, the cycle's record, QA's hand-back, the choice of database, the functions whose failures are silent, choosing with arrow keys and the question channel |

## The menu and the action list

**The menu is driven with arrow keys, and a checkbox stands below the feature
list.** Cleared, Enter on a feature continues its current step, as it always
did. Set (with the space bar), Enter opens the list of everything that can be
done with that feature: the same commands as above, but without having to
remember their names.

That is how "drop the feature" left the top list. An action among features was
doubly out of place: first, it is not a feature; second, every subsequent action
would have to be added there too, and the menu would drown. The top list is now
features only, and everything else lives behind the checkbox.

The action list shows only what applies: "what is new in the PR" does not appear
while there is no PR, nor does "clean up after the merge" until the review has
been through. The hints next to the items carry gathered facts — how far the
branch has fallen behind `main`, how many entries are in the friction log, which
tree the dev server was started from — so the list answers questions rather than
asking them.

With no terminal there are no arrow keys either: from a phone the same list
arrives as buttons, one per item. The items' labels go into the question's
channel along with the form, and the bot draws them labelled rather than as the
digits "1 2 3": among the items there is sometimes "drop the feature", and there
is nothing to press blindly there. The numbered list above labelled buttons is
removed in doing so — it would repeat them — while the lines that explain the
question stay.

**The checkbox does not carry over into the chat: an inline keyboard has neither
a space bar nor a state that would survive a press.** What it does have is the
row's width, and the two purposes lay themselves out along it side by side with
no mode at all: in the feature list a feature's row is two buttons — the wide one
drives the step, the narrow one (⚙️) opens the list of actions on the same
feature.

```
┌───────────────────────┬───────────────────┐
│ 12-sample-one-and-…   │        ⚙️         │
└───────────────────────┴───────────────────┘
   └─ drives the step        └─ the action list
```

Buttons in a row always share its width evenly: the Bot API has no notion of a
button's width at all, and there is no making the cog narrow. Three cells instead
of two would give 2/3 and 1/3, but the feature's name would have to be cut in
half between two identical buttons — which would read as two different ones
leading to the same place. So it is split in half, and the name is trimmed to
forty characters so that half a row holds it.

Above the buttons is one line: the repository's name and the number of features.
There is deliberately no `sclaude status` table below it: a feature's name and
step stand on the buttons themselves, there is nothing on a phone to open a
worktree path with, and the branch breakdown is about branches without features,
that is about exactly what is not in this list.

The feature's card stopped being a stop along the way after that — but it has not
gone anywhere: both handlers end with it, showing the outcome, and it also stands
above the action list when that is opened with the cog. A link to the issue and
the PR, the step, the worktree, the session's state — all of it is needed exactly
where one chooses what to do with the feature.

The orchestrator cannot assemble the card: half of it — whether the step's
session is alive — is known to the bot rather than to it. So it does not assemble
but names: a `feature` field with the feature's name is put into the question,
and the bot builds the card from it. The mark lives until the next question and
is cleared with it — the following questions ("remove the worktree?", "merge main
in?") are not about the feature as a whole but about what the human is confirming
right now, and a card above them would be out of place.

In the terminal a line with the issue's and the PR's numbers is printed above the
same list: there is no card there, and half the list's items are about precisely
those.

## Starting from an issue

**The cycle starts from a choice rather than from a name thought up on the
spot.** The list's top item is to type a name by hand, and below it are the
repository's open issues: first those assigned to whoever `gh` is authenticated
as, then all the rest. The arrow keys move through the list, Enter chooses, `q`
cancels. The chosen issue suggests a branch name
(`34-sample-site-and-multiple`) — the suggestion is edited right in the input
line, and a title in a non-Latin script, of which nothing survives `slugify`,
comes down to `issue-27`.

The issue's number lives in `.sclaude/local/feature/state.json` until the cycle ends: step 1
gets the issue itself — the body, the comments, the parent and the links — in the
prompt already, and step 3 ends the pull request's body with a `Closes #N` line,
by which GitHub closes the issue on the merge. No network, no `gh`, no open
issues — there simply will be no list, and the old question about a name
remains.

The list and the suggestion are `sclaude/lib/issue_list.py`'s, which the bot's
Mini App uses too: it offers the same choice on a phone and starts
`sclaude new` with the answers as options — `--issue <n>` with the branch name,
`--blocked-ok` once the blockers were shown, `--create-issue` or `--no-issue`
for a name — so `cmd_new` asks none of it again (`new_from_args`).

## Acceptance criteria

**Step 1 agrees the acceptance criteria, and the rest of the cycle is measured
against them.** The plan says how the feature will be built; it is rewritten
whenever development deviates from it, and by the end it describes what was done
rather than what was asked for. The criteria are the other half: a numbered list
of statements about observable behaviour, each one checkable on a deployment by
somebody who has not read the code.

They are written before the implementation is worked out and they do not move
with it. That is the whole point — a definition of done that development can
edit is a definition of nothing.

The list lives in a comment of its own on the issue, between
`<!-- sclaude:ac -->` and `<!-- /sclaude:ac -->`, posted by the orchestrator once
the plan is approved. The pair of markers rather than one: the list has a heading
above it and a note below, and QA may add a line of their own under it. QA ticks
the boxes in that comment.

**sclaude never edits an issue's description.** It used to: step 1 kept a
`## User request` section in it, the approved criteria were appended to it, and
the epilogue appended a `Current status` block — to descriptions a human wrote
as well. A developer who opens such an issue cannot tell the task they were
given from what a tool made of it, and so cannot trust that it has not changed
under them. The request, the criteria and the status are three comments now,
each found again by its marker and rewritten in place rather than repeated; a
new issue gets a one-line body saying so. The markers are declared once, in
`issue_comments.py`. Issues from before the change keep their sections: the
criteria are still read from an old body, and nothing is written back to it.

Not a fifth artefact in `.sclaude/local/feature/`: the criteria have to outlive the worktree.
`sclaude done` removes the tree the moment the PR merges, and the question the
criteria answer — did this feature do what it was supposed to — is asked after
that. The plan carries a copy, at its head, so that a step with no network still
has the list; the issue is where a correction lands.

Each criterion is identified `AC1`, `AC2`, and the identifier is what the rest
of the cycle points at:

| Step | What it does with them |
| --- | --- |
| 1. plan | Agrees them with the human, writes them into the issue and puts them at the head of the plan |
| 2. code | Gets them in the prompt; commits name one in a `Requirement:` footer (`Requirement: AC2. <the criterion's text>`); the step's closing report goes through the list criterion by criterion |
| 3. pr | Copies them into the pull request's "Requested by the customer (for QA)" section as an unticked checklist, and uses the footers to find criteria nothing was committed for |
| 4. review, epilogue | Read them; neither writes to the section, and neither ticks a box |

The footer carries the identifier **and** the text. The `pr` skill's convention
is that a `Requirement:` line reads on its own — it is collected into a pull
request people read — and a bare `AC2` would send a reader off to find out what
it meant. The identifier is a prefix to it, not a replacement.

Nothing ticks a box except a person. A tick is the claim that somebody looked at
a deployment and it was right, and that is the one thing in this cycle no part
of it can establish for itself — the same reason `In QA` → `Done` is a human's
move. A step that could tick its own criteria would be marking its own homework.
The one exception is a product's own choice: with `qa` set to `both` or `auto`
sclaude ticks every box when it accepts the issue, and comments that it did.

A feature planned before any of this existed has no section and no criteria.
Every reader handles that by saying so rather than by inventing them: the block
is empty, its line drops out of the prompt, and the step is told to work from
the plan alone. The same holds when there is no issue at all — the criteria then
live only in the plan, and step 3 takes them from there.

## The board and its dates

**An issue taken into work leaves Backlog and gets a start date.** The board is
the only place that shows what a person is busy with right now and since which
day, and an issue lying untouched all that time while a feature runs on it lies
about exactly that. At the cycle's start sclaude moves it to `In progress` — on
every board it lies on, and only out of `Backlog`: `In review` is set by whoever
sent it for review, `Done` by whoever closed it, and out-arguing them would take
the board's meaning away. An issue in any other column stays where it is, and
that is said out loud. An empty `Start date` field gets today's date; a filled
one is never touched.

Once, at the start, rather than at every step transition: "the work has started"
is one moment of the cycle, and repeating the move would put back into progress
an issue the human had meanwhile moved on themselves.

**A merged pull request closes the bar on the chart.** In the cycle's epilogue,
in the same place where sclaude re-reads the PR's state and sees the merge, an
empty `Target date` field gets today's date. The moment is not chosen at random:
GitHub closes the issue itself by `Closes #N` while sclaude is not running, and
the epilogue is the first place the merge is visible from at all. Today's date is
set rather than the issue's `closedAt`: the bar must end when the work ended, and
those two dates diverge only if the human came back to a postponed epilogue the
next day.

`Target date` specifically, even though by its name it is a planned deadline.
Roadmap — GitHub's Gantt chart — draws a bar from a pair of DATE fields, and
there are exactly two in the repository: `Start date` and `Target date`. The
computed `Closed` that GitHub maintains itself does not enter that choice, so an
issue's closing date is not visible to the chart at all. That is how the field
was filled in by hand: on one issue `Target date` coincides with the day it was
closed. The price of the decision is that the field stops being a plan, and
"we overran" can no longer be seen from it.

The column and the dates are edited differently, although on the board they stand
side by side. `Status` is a project's field, while both dates are fields of the
issue itself (`repository.issueFields`, a mechanism newer than projects), and to
a write in the old way GitHub answers with a plain refusal: "Issue field values
cannot be updated using the updateProjectV2ItemFieldValue mutation". Hence the
different requests: the column on every board item, the dates once on the issue —
which means they will be set even on an issue that is on no board at all. The
`gh` token needs the `project` scope for all this
(`gh auth refresh -s project`); without it there is a warning with that same
line, and the cycle goes on, as it does with any other refusal from GitHub.

## What a step's session is given

**The orchestrator assembles a step's context, not the session.** What can be
gathered deterministically is gathered before the launch and embedded in the
prompt ready-made: for step 1 the issue and the manuals' tables of contents (a few dozen
headings instead of reading thousands of lines), for
step 3 a check on whether `.sclaude/local/feature/` got into the branch's commits, for step 4
the PR's checks and both streams of comments. The session pays tokens for
judgement rather than for gathering.

Step 4 also gets what it could not have worked out itself: a green
Claude review check does not mean the review happened. When the workflow file
diverges from the default branch the action exits with zero in seconds having
checked nothing — and the step once took such a tick for work done. The
orchestrator computes this from the duration and the number of comments and says
so outright.

All of it is a snapshot at the moment of launch, and the prompt says so while
leaving the commands for re-reading: changing the PR's state is exactly what step
4 is busy with. If the gathering did not work, the block is empty and the prompt
keeps its previous instruction inside itself.

**Context is not carried between steps.** Every step is a new session, and
`.sclaude/local/feature/plan.md` serves as the bridge, written at step 1 specifically to be
handed over: compacting a long session costs more and preserves worse than a plan
written for that purpose. Returning to an unfinished step goes through
`--resume`, so an interrupted conversation inside a step is not lost — sessions
are named with a UUID generated in advance (`--session-id`) rather than fished
out after the fact.

The review meanwhile goes on at its own pace while the session is closed: a
reviewer adds a comment, a check turns red from somebody else's merge into
`main`. So the return to step 4 is the only one that does not stay silent: the
orchestrator looks at what has appeared on the PR since the step last worked and
passes it as a prompt to `--resume`. If there is nothing, the return goes
silently, as with the other steps.

The count runs from the transcript's last entry rather than from the step's
start. The difference is not cosmetic: step 4's session lives for hours and reads
the PR all that time, so a comment that arrived mid-work has already been dealt
with — from the start it would look new, and the session would be handed its own
context to work through.

A step is closed by the human rather than by a process that has ended: after
leaving `claude` the script asks whether the step is finished, and while the
answer is "no" the next launch returns to the same step. There is one exception:
**a merged PR closes steps 3 and 4 itself** — the work is in `main`, the review
took place, there is nothing left to check a preview on, and there is nothing to
ask about. So every prompt tells the session what it ends with: say that it is
done and stop — without offering the next step, because agreeing to it inside the
session is impossible anyway, as it begins when the session is left.

## The workshop

sclaude's live checkout is read-only to every session it runs —
`sclaude_guard_args` in `steps.sh` hands `write-guard.py` `--readonly
$INSTRUMENTS` for the steps, the reviews and the epilogue alike — and no
session pushes it or a worktree of it (`OWN_CHECKOUT` in
`forbidden-commands.py`). Every other session runs from that checkout, and a
hook edited there changes all of them on their next call; the repository is
public, and a session works from a private product. Steps used to commit and
push its `main` themselves, and the review sessions could not touch it at all,
so a clear bug in a hook waited a month in a deferred file.

A session changes sclaude in its tree's workshop instead (`workshop.sh`): a
worktree of the checkout at `<tree>/.sclaude/local/instruments`, made from
`origin/main` by the first `sclaude core-open` and shared by every session of
the tree — a feature's, or a monthly review's. Inside the product's tree,
since the session may already write there without a prompt, and under
`.sclaude/local`, which git, the product's tools and every upload leave
alone. A maintainer's workshop is on a branch nobody sees (`workshop/<time>`),
since what reaches `main` is one squashed commit; anybody else's is the branch
its pull request comes from, `dev/<name>-<time>` — never named after the
feature, since the repository is public.

**Who may write there.** `.sclaude/local/instruments.json`, the record beside
it (`workshop.py`), lists the sessions in `approved`. `write-guard.py
--workshop DIR` treats the workshop as read-only for any other session, and
the record as read-only for all. `sclaude core-open` adds the session that
runs it, which it knows by `SCLAUDE_SESSION` (`claude_launch` exports it).
`forbidden-commands.py` answers that call with "ask" in a step, so Claude Code
puts the question to the person — the model cannot answer it, in auto mode
too — every session anew; under `--step friction` (the retrospective, the
friction review, the monthly review) it lets it through, since the
retrospective is where the person expects changes and the other two start in
plan mode. The prompts say which by `workshop_rules` (`prompts/_workshop.md`).

Every session's write guard reads leniently (`--lenient`): a target it cannot
tell — a loop's `"$f"`, a `$( … )`, a directory in a variable — is refused
only when the command names the checkout or the workshop at all, and the
refusal says that the target could not be told. Steps write through
variables all day, and a review now runs the workshop's tests in loops; the
strict reading refused those for naming nothing. A plain `git fetch` in the
checkout is allowed — no refspec, and only the flags that read
(`FETCH_READS`) — since it only reads origin into the remote-tracking refs. sreview's state in the
checkout's git directory stays writable (`--allow`), since reviewing a
workshop's change writes it.

**Finished, and reviewed.** The session commits in the workshop, reviews its
change and runs `sclaude core-ready`, which refuses uncommitted work and
records the head as ready. For a maintainer of sclaude the review is sreview:
`core-ready` wants sreview's mark of a finished run at that head
(`$S/branches/<branch>.reviewed`, `workshop_sreview_mark`). For anybody else
it is whatever review they choose, named with `--review`, and the
maintainer's review of the pull request is the gate.

**Publishing**, from `claude_launch` once the session exits
(`workshop_after_session`): with the head ready, `workshop_publish` fetches
`origin/main`; for a maintainer it rebases onto it (a conflict leaves the
change where it is, said), checks it for the product's details
(`workshop.py leaks`: the product's repository and folder names, the
feature's slug and branch, the package's name, `#12`-like numbers and
pull-request or issue references, and paths of the product's own files, in
the added lines and the commit messages; a hit is the person's to wave
through), squashes it into one commit (`squash-message`: the first commit
that is not a review round leads, the rest are listed, the trailers merged),
runs the tests the change touches in a clean environment, and pushes
`HEAD:main`. Then the live checkout is fast-forwarded to it when nothing else
runs from it (`workshop_live_update`), so the next session runs the fix; the
next sclaude start does it otherwise, and a checkout holding commits of its
own that origin lacks is told to bring them on top (`pull --rebase`). Anybody else's goes through the same
check and tests, unsquashed, to its branch and its one pull request
(`instruments_propose` from the workshop; a push that failed is not taken
for sent). The rebase and the squash leave the head ready, so a publication
stopped short — red tests, no gh or no login, no network, a refused push, a
conflict with main — is tried again, silently, whenever the tree is opened
(`workshop_pending`, also at the `done` step, before `sclaude done` clears the
tree, and for a monthly review's kept trees). The person's own "no" to the
product's details is the one stop that holds the change at its head
(`workshop_block`): asking again would not help, and a session's new commit,
marked ready, lifts it. A "yes" to the same question is kept for the lines it
was shown, so a retry does not ask it again, and a line not shown then does.
In `sclaude done` the retry comes before the retrospective; when it moves
sclaude's code, the clean-up goes on in a fresh run, retrospective and all.
The retrospective's own change, stopped on the way (no network, a refused
push), gets one more try before the clean-up takes the workshop; one stopped
by its head — red tests, a conflict — would only stop again, and is kept on
its branch. The live checkout's state,
which the reviews compare before and after, leaves out what sending a
workshop's change records in the shared config: the `fork` remote and the
`dev/` and `workshop/` branches.

**Unfinished.** A change uncommitted, or not marked ready at its head, is not
published. The session is offered back at once — the same conversation, with
`WORKSHOP_RESUME` in place of its prompt (`claude_again_args`), and the
question and that prompt both name what is missing (`workshop_missing`):
uncommitted work, sreview's mark at the head, or `core-ready` not run (a
sreview the person stopped with "stop" marks the head too: a review they
called enough is finished, and without the mark the session was sent back
to review again and again). A "no" to that
question records the session's launch in the record's `pending`, which `workshop_pending` offers
again when the feature is next opened (and the monthly review on its next run
that day: its tree is kept while its workshop holds anything unpublished).
The record stays while the session is sent back, and goes when its
change is finished or held, or when the session cannot be sent back (where
it ran is gone), which is said once: cleared before the launch, it was lost to a run
cut off after the session. An unfinished workshop with no session recorded
is still said on every opening, with what is missing. While one is pending, what later sessions make waits behind it.
When the tree goes, `workshop_remove` takes the workshop with it: work never
published is committed as it was left and kept on its branch in the checkout,
and named.

The reviews' own refusals no longer reach the step's friction log
(`_friction.py` skips `--step friction`): a retrospective's refused push sat
there until the next step's review read it as that step's friction.

## The worktree

**The script creates the worktree, not `claude --worktree`.** The built-in flag
does not carry untracked files across, and without them the worktree does not
work: `.env.local` and `node_modules` are both in `.gitignore`. `sclaude`
branches from a fresh `origin/main`, names the branch `feat/<slug>` (as the `pr`
skill requires) and lays out the environment as symlinks to the main repository —
editing a key reaches every feature at once. `node_modules` is not a symlink but
hard links (`cp -al`): Turbopack refuses to work with a symlink that leads
outside the project, and `next dev` dies at start-up. Links to the same inodes do
not duplicate the data — some ten seconds and almost no space. The directory is
correct while the branch has not touched the dependencies; the script notices a
`package-lock.json` that has diverged and offers an `npm install`.

## Environments

**Which database a feature works against is the machine's answer, not the
script's.** It used to be the literal `dev`, written into `force_dev` three
times over, and that was right while everybody shared one database. It stopped
being right when a product could offer a Supabase stack running locally: a
developer applying migrations wants a database nobody else is reading, and a
developer working on the interface has no reason to install Docker for one.

So `environment.sh` asks, in order: `$SCLAUDE_ENV`, then the answer this machine
gave before (`~/.claude/sclaude/environment`), and only then the human — once,
with the project's own environment names as the choices. There is deliberately
**no default**: a guess would put somebody on a shared database believing they
were isolated, or on an empty local one believing they were looking at real
data, and both mistakes are quiet ones. A project that declares no environments
simply does not get asked, and keeps whatever its worktree had.

**An environment is a `.env` file.** The product names each one in
`.sclaude/config.json` — `"dev": {"env": ".env.dev"}`, `"prod": {"env":
".env.prod", "protected": true, "siteUrl": "https://…"}` — and that is all
sclaude needs to know (`sclaude/lib/envs.py`). A tree is on the environment
whose file its `.env.local` points at. sclaude switches it itself: `.env.local`
to the file, and on Supabase the CLI linked to the project that file's URL
names, or unlinked for a local stack, since `supabase db push` obeys the link
and not `.env.local`. A build made on the old file is removed with it,
because `NEXT_PUBLIC_*` is inlined. The credentials stay in those files: a
rollback reads production's database URL from production's file, and
whatever sclaude needs and no file holds it asks for at the terminal, every
time, saying that naming the file once spares the question.

**Not every environment is a choice.** A `protected` one is production. A
`deployed` one names deployments rather than a machine — a preview, perfectly
safe to write to, but not somewhere a local dev server and a local browser
suite belong; offered as a choice, it sent the cycle into a regression whose
e2e stage refuses to start. Nor is one whose `siteUrl` is not a loopback
address.

Two things survive from the old behaviour unchanged. A feature is still never
left pointed at production — that is why the function acts rather than reporting,
and protected environments are excluded from the choices, refused from
`$SCLAUDE_ENV`, and refused from a saved answer somebody edited by hand. And an
environment we cannot identify is still treated as protected: the hook that
governs `supabase db push` allows it only on an environment the project does
not protect, and only when `.env.local` and the CLI's link agree — silence is
not permission. A session may not point `.env.local` at production's file
either; a product's own switch script is banned in its policy.

## A dev server and a database per feature

**The orchestrator runs the dev server, not the session.** A `next dev` started
from a claude session stays in its process group and will not let it exit — and
exiting is what a step ends with. `setsid` takes the server into a session of its
own, where it outlives both claude and sclaude itself; it is shut down by
`sclaude done` or by hand through `sclaude dev --stop <feature>`. Chrome, by comparison,
detaches itself — `chrome-debug` leaves it with `PPID=1`, and it holds no
session.

**Every feature has a dev server of its own**, and opens at
`http://<feature>.localhost:3000`. The first start claims a port from
3100–3199 and records it in `.sclaude/local/feature/state.json`, so a feature keeps its port
and its address between runs; a lock keeps two features started together from
claiming the same one. Nobody needs to know the ports: `sclaude-proxy` holds
:3000 and hands each connection to the server its host names (see
[bin/sclaude-proxy](../README.md#binsclaude-proxy)). The host rather than only the port is
what keeps two features apart in one browser — cookies ignore the port, so on
bare ports a sign-in on one feature would sign the other one out.

The server is started with `PORT` (where to listen) and `SCLAUDE_DEV_URL` (where
it is reached from). The second is for the app: it cannot see the proxy's name
from where it stands, and an app that builds its sign-in redirects and email
links from its own address would otherwise send them to `localhost:3000`, the
list of features. What the project does with it is its own business — a Next.js
app might turn it into `NEXT_PUBLIC_SITE_URL` in its dev script.

The local regression hands the suite the same address in `E2E_LOCAL_URL`,
with `PORT` and `SCLAUDE_DEV_URL` in case the suite has to start the server
itself, and the feature's name in `SCLAUDE_FEATURE`. One thing to know when a
project's suite talks to that address from Node rather than from the browser:
Chrome resolves `*.localhost` by itself, but Node asks the system resolver,
and a stock WSL Ubuntu answers ENOTFOUND. The suite then has to answer those
names itself, in a test fixture.

Every step starts by printing the address — `Open it at
http://<feature>.localhost:3000` under the step's header — and the feature's
menu shows it beside the dev server's state.

A port found held by a process from another directory is not ours to take back:
the feature moves to another port and says so, rather than offering to kill
somebody else's server.

**Every feature on the local database has a Supabase of its own.** Two features
on one local stack see each other's schema — a migration written in one lands
under the other — and a `db reset` in one wipes the other's data. So when a
feature's environment is the project's local one, `ensure_dev` first starts a
stack for it alone: its own `project_id` (Docker names containers and volumes
after it — the project's id and the feature's label, kept to the 40
characters the Supabase CLI keeps, a longer one cut short and ending in a hash,
and recorded in the state as `db.project_id`), its own block of ten ports from 55000, only the containers the
project needs. For a typical web app that is a handful of containers and a
few hundred MB, up in under a minute the first time. It is filled once: with a copy of the main local
database's data when the project sets `copyFromMain` and the main stack is up —
the same people with the same ids, so the objects they own in the bucket are
already there — and with the project's seed otherwise.

The copy goes into main's schema, not the feature's. A migration that inserts
reference rows with generated ids gives them different ids in every stack, so
main's rows that point at them, loaded over the feature's own, pointed at
nothing — and a later migration that put a foreign key back failed on them.
So the feature's stack is set back to the main database's last migration
(`db reset --version`), public's tables are emptied, main's rows go in, and
the feature's own migrations then apply over them, as they will over
production's. Where the two cannot be made one schema — the main database has
a migration the tree lacks — the copy goes over the feature's schema as
before (`db_copy_main`).

The main local database is the source, so it is kept on main's migrations:
`db_main_up` applies the ones on `origin/main` that it lacks, from a workdir of
main's own (whatever the main checkout has checked out), at the end of every
cycle and before every copy. It is quiet when nothing is pending, leaves a
stopped stack stopped, and only warns when the migrations do not apply — the
main stack is the developer's, and sclaude does not rebuild it. Its log is
`.sclaude/local/db-main.log` in the main checkout.

The stack runs from `.sclaude/local/feature/supabase/`: a rewritten copy of the tree's
`supabase/config.toml` — the tracked one is never touched, or the ports would
ride into a commit — and symlinks for everything else, so the migrations the
feature writes are the ones its stack applies. Pending migrations, the
feature's and main's after a sync, are applied on every start.

`.sclaude/local/feature/db.env` points the feature at it, and every process sclaude starts
there sources it — the dev server, the local regression, the claude session.
It carries `SUPABASE_WORKDIR`, so a bare `npx supabase db reset` typed in the
session rebuilds this feature's database and no other; a hook refuses
`--workdir` pointing anywhere else. The project decides the rest in
`.sclaude/config.json` under `database.local` (see `sclaude/config.example.json`), and
its own dotenv loading must let an exported value win over `.env.local`.

**Nothing runs that nobody uses.** `sclaude-proxy` starts a stopped feature on
the first request for it — a page says it is starting and reloads until the
feature answers, under a minute with its database — and stops one nobody has
opened for half an hour (`SCLAUDE_DEV_IDLE`), its database with it, data
kept. It never stops a feature while anything is working in its tree: a claude
session, a regression, a shell. The start goes through `sclaude dev
--no-browser` and the stop through `sclaude dev --stop`, so the proxy decides
only when; the PATH they need — nvm's node among it, which systemd does not
have — is the one sclaude last ran with, left in the registry. A start that
fails shows its log and waits for "Try again" rather than looping. The local
regression brings the feature up itself before its parts run.

The stack is removed with its data when the feature is merged or abandoned,
after the project's `teardown` — for example, deleting from object storage
what the feature's people uploaded and the main database does not reference; it is told
which people were copied and when, since their objects are partly the main
database's.
The main repository keeps its own stack, and a feature on the shared cloud
project has none. With Docker down sclaude starts it — Docker Desktop from WSL,
or `docker.service` where sudo needs no password — and waits up to
`SCLAUDE_DOCKER_WAIT` seconds (120); `SCLAUDE_DOCKER_DESKTOP` names the
launcher when it is somewhere unusual. A start that fails is not retried for
ten minutes. Only when Docker stays down does the feature fall back to the
shared local database, and it says so. `SCLAUDE_DOCKER_START=off` starts
nothing.

## Branches

**The branches are sorted out at every launch** — in the menu and in
`sclaude status`, before choosing what to do. Deletion is offered only for what
has nothing left to hold: a branch with a merged PR and a branch whose remote
copy is gone (GitHub removes it after the merge). Everything else is shown as a
list with no offer — unpushed commits, a PR closed without a merge, a feature
with a live worktree. A `fetch --prune` is done before the sorting, otherwise the
local `origin/*` outlives branches that have long been gone and the check lies.

## Preview and production

Once every step has been through, the script prints what is left, separating
**preview** from **prod**. The commands come ready to copy — one per line, with
full paths — while the explanations go on their own line above the block rather
than inside a command.

Preview is deployed **from the main repository with a path to the worktree**:

```bash
cd ~/myapp
vercel ~/myapp-<feature> --project <name>
```

That way rather than a `cd` into the worktree, for two reasons. The link to the
Vercel project lives in the main repository's `.vercel/`, and the worktree has
none — a `vercel` launched from there will create a **new project** instead of
deploying to the existing one (verified; the spare project had to be deleted by
hand). And a `cd` into a directory that is about to be offered for deletion is
contradictory advice.

Prod is `vercel --prod` from the main repository, and if the branch added
migrations, then a `db:promote` first with the whole procedure from the project's
README. Whether a promote is needed the script determines itself — by whether the
branch touches `supabase/migrations`.

## Step 5: the sync with main

A reviewed branch whose pull request conflicted with main used to go on to the
preview, to QA and to the merge as if nothing were wrong, and then wait: the
merge offer said "it conflicts with main — resolve them and push", and the
merge wait asked GitHub every half minute, for hours, about a merge nobody
could make. The conflict is known long before that, and for nothing:
`git merge-tree --write-tree` merges in memory and names the files, with no
session and no GitHub call (`merge_conflicts` in `sclaude/lib/sync.sh`).

So `remind_prod` asks it at three points:

- **before the preview** — QA should look at the code that will merge, not at
  the branch alone;
- **after QA's yes, before the pull request is handed over** — main moves
  while QA works, and a hand-off taken back a moment later would flip the
  board, the pull request and its summary for nothing;
- **while the merge is waited for**, every `SYNC_POLL` seconds (two minutes),
  since the wait is a fetch — of an open pull request only: a merged one has
  its branch deleted on GitHub, and the stale ref left here could conflict
  with the main its merge moved.

The branch asked about is origin's tip, which is what the pull request
merges, and also the tree's own commits when origin lacks them: whoever
merges main here merges those too. A merge under way in the tree — a sync
broken off mid-way, or one by hand — is never clean, whatever origin's tip
says: its files may hold conflict markers, and the preview would deploy them.
Its unmerged files are the conflict, and the session finishes it.

A conflict opens the sync session, `5-sync/<slug>` (`5-sync(2)` for a second
one): the review step's model and rules, the prompt `sclaude/prompts/sync.md`.
It merges `origin/main` into the branch — a merge, never a rebase: the branch is
under review, and a force push is refused anyway — resolves each conflict
keeping both sides' intent, checks the result as the project's `CLAUDE.md`
says, and pushes. sclaude then checks for itself that no merge is under way,
the tree is clean, the branch merges cleanly with main and is pushed. Only then
does the run go on: from before the preview it simply continues, and the
changed tree is deployed; from after QA, or from the wait, it starts over, so
the preview, its regression and QA (`qa_retest`) see the new code. QA is not
asked again when the branch's own product is what they passed
(`qa_product_same`): each commit's change against the main it stands on, less
the paths that are not the product (`NO_DEPLOY`: `.sclaude`, `docs`, `.github`,
`.githooks`, `*.md`), compared as text — bytes, whitespace and binaries
included, renames found, only line numbers and blob ids dropped. Main's edits
to lines the branch does not touch leave the yes standing; a change of the
function header above the branch's lines does not, nor anything that cannot be
read: in doubt, QA looks again. A session
that ends otherwise stops the run, and the feature shows `5/7 sync` in the menu
until `sclaude <feature>` finishes it; its conversation is resumed then.

A pull request already handed over for the merge goes back to a draft
whenever origin's branch moved during a sync (`sync_gate`), even one that
stopped short after its push: origin then has code no preview and no QA has
seen. The hand-off is taken back the same way `qa_retest` takes it back
(`pr_unhandoff` in `deploy.sh`), from the run, from the menu's sync and from a
step's start.

One kind of conflict needs no session. The deferred logs
(`.sclaude/*/deferred/*.tsv`) are rows that both sides append to — a feature's
friction reviews on its branch, `deferred_to_main` on main — and their merge
is the rows of both. When they are the only files in conflict, sclaude merges
main in itself, with main's rows first and then the rows the branch added
since the two parted (against the merge base), less those main added since
then, and pushes (`sync_deferred`). Against the base, not the branch's whole
copy: rows the branch took from main at an earlier merge and main has since
removed — the monthly review removes what it decided — would otherwise come
back. Less main's additions, not all of main's copy: `deferred_to_main` sends
a branch's rows to main, and they come once, but a row the branch repeats on
purpose stays repeated. The menu's line about such a merge says so, rather
than naming a session.

The sync runs the same way at a step's start and from the menu
(`sync_offer`), and neither asks, even when a session resolves the
conflicts: the branch has to merge with main before its preview and its merge
whatever is answered, so a "no" only put the same session off. `sync_gate` holds origin's branch against the head the
hand-off was made on (`handoff` in the state): commits it lacks — the sync's,
or ones that came by other hands, a push from another machine, GitHub's
"Update branch" — are unchecked code, and the hand-off goes back for them,
said in those words. A ref here that only lags behind that head is not.

The menu's own "Sync with main" (`cmd_sync`), there at every step, uses the
same check: its line says how many files would conflict, and choosing it for a
merge that would conflict goes to the sync rather than leaving the tree
half-merged for the person to untangle — from a phone they could not. A plain
merge from either that stops anyway is backed out (`sync_plain_merge`). The merge with main
a step makes at its start (`sync_branch`) goes the same way, and asks
nothing: it once asked, a "no" was remembered for that state of main, and all
it bought was the same merge later, before the preview, after step 3 and the
review had worked on a branch that was not what merges; a plain merge there
that was backed out leaves the step to open on the branch as it stood. Before step 3 the
branch may not be on origin yet; the session then leaves it local, and the
prompt says nothing of a pull request or of QA.

A branch origin has never seen is put on top of main before every local
regression, with no question (`sync_unpublished`): rebased when it rebases
cleanly over a clean tree, left as it is otherwise. Main moving during step 2
once made the suite fail on the branch's older copy of a file main had changed,
and a fixing session was opened only to rebase. A pushed branch is not
rewritten; its merge with main stays the question above.

## Production rollback

**A red production regression rolls production back, before anything is fixed.**
Until now prod went through the same gate as local and preview, and that gate's
loop is run → fix → run: up to two sessions, minutes each, against a live broken
production. The label said production was broken and nothing did anything about
it.

So prod does not use the gate. It runs the suite itself, and on red the order is
reversed: `vercel rollback` first, to the deployment this feature displaced, then
the database as far as it honestly goes, then a check, then the record — and only
then does the cycle return to step 4, where the fixing session now runs against a
production that works.

Which deployment to go back to is **recorded before the ship**, not worked out
after. Afterwards the question is ambiguous and the answer would be a row's
position in a list; before, it is exactly whatever is serving production at that
moment. If the record is missing the rollback says so and names
`vercel ls --environment production` rather than guessing. It also says what else
leaves production with us — main takes several merges a day, so a rollback
routinely carries somebody else's work back out, and that is a thing to be told
before rather than discovered after.

**The schema is the half that cannot be made exact, and it is not pretended
otherwise.** Migrations are forward-only, a product may have no point-in-time recovery,
and the way back is a commented `-- down:` block: comments, not a mechanism —
nothing runs them, somebody reads them. Many migrations have no block at all.

`sclaude/lib/down_blocks.py` reads those blocks and sorts them into four
verdicts, and the two interesting ones are what the file exists for:

| verdict | what it means |
|---|---|
| `runnable` | statements that can be executed as they stand |
| `destructive` | runnable, and it deletes rows somebody will miss |
| `prose` | it looks like SQL and is a note to a human |
| `absent` | no block at all — the loudest of the four |

`prose` is the one that matters. A real block read `drop view if exists
public.v;`, then — inside a comment — "...recreate from the previous schema
snapshot...", then two `grant` lines. Strip the
comments and what is left parses, runs, and leaves production without the view.
An ellipsis where statements should be, a function body in `$$` this reader
cannot split, an English sentence among the statements: any of them refuses the
whole block. The classifier is a heuristic over prose and is written to fail
towards refusing.

The table names every migration, `absent` included — a migration skipped in
silence is how a schema reaches a state nobody can describe. Only the fully
runnable set is offered, all of it or none, with the SQL shown first and the
default **N**: the code half's default is yes because a deploy is undone by
deploying again, and this half's is no because a `delete from` is undone by
nothing. Each reversed migration takes its row out of
`supabase_migrations.schema_migrations` with it — `supabase db push` put it
there, and a row left behind makes every future `db:promote` refuse. The
environment goes back to wherever the tree was whatever happens, including
halfway through a failure: a tree left pointing at production is a machine
whose next `npm run dev` talks to it.

Where the blocks cannot be run the schema stays ahead of the code, and that is
said in those words. One case overrides the "no question asked" rule: a migration
that *took something away* whose block is prose or absent. Then the previous
build would meet a schema it was never written for, and the rollback asks first.

**The check afterwards is a stage of its own, and deliberately not a green
light.** It runs the same suite against the same host, asking whether the release
we went back to is serving properly — never whether the feature is good. That
separation is structural rather than a convention: `regression.prod.status` goes
on describing the feature, so the gate's short-circuit cannot be tripped by it,
`regression_clear_mark` leaves `prod-regression-red` alone, and
`regression_red_label` mints nothing for it. Those three needed no editing when
the stage was added — each already ignores a stage it does not know — and all
three are pinned by tests, because widening any one would quietly turn
"production works again" into "the feature works".

**The incident goes on the feature's own issue, as a comment.** Not a new Bug
issue: `state.json` holds one `issue`, read in nine places, and the labels and
the status section go on the whole chain of parents that number walks — a second
issue has no parents, so the epic above would never learn production broke, and
the fix would be split across two `Closes #N` targets. A new comment each time
rather than an edit, unlike the rolling summary beside it: a rollback is an event
with a time, and a feature rolled back twice has two of them.

The comment says what failed, which deployment is serving now, what became of
each migration, whether the check passed — and that main still holds the commit
that broke this, so the next production deploy ships it again unless the fix
lands first.

**The fixing session is told all of it.** It gets the log of the run that caused
the rollback, which is not the one at the usual path: `regression_run` opens with
`: > "$log"`, and the check after the rollback is a `regression_run`, so by then
`.sclaude/local/feature/regression.log` describes the *previous release passing* — plausible
enough that nobody would question it. The failing run is copied aside first and
the prompt points there. It is also told that the local suite is the check that
matters (production is not serving this branch, so a run against it says nothing
about the fix), that the fix goes the whole way round again — local suite, merge,
preview and its suite, then production — and to close the incident with a second
comment once production is green on the feature again.

By hand the same thing is `sclaude rollback <name>`, and it stands in the action
list once the feature has actually reached production. Sessions cannot do it:
`VERCEL_READS` in the hook is an allowlist and `rollback` is not in it, so it was
already refused — `rollback status` was added beside the other reads, because a
session looking at a red production has a reason to ask whether one is in flight.

## Hand-backs from QA

**Returning a feature to development is a transition, not a message.** Once the
preview regression is green the issue goes to `In QA` and a systemd timer takes
over: `sclaude-watch` polls the column every few minutes and changes nothing
itself — it looks and it tells, in the feature's topic (the watch keeps the
worktree for `sclaude-notify --in`). When the column leaves `In QA`, it collects what
was written since the watch began — on the issue, on the pull request, and on
the pull request's lines — and saves it **verbatim** beside the watch file.
Verbatim rather than summarised, because the session is answering a person, and
a paraphrase of a complaint is a poor thing to answer.

Acting on it is `sclaude`'s when the human comes back, and this is where the
mechanism used to stop half-finished. The finding was delivered and ignored:
the watch is armed from `remind_prod`, so a feature waiting on QA always sits at
`step: done` — and `cmd_resume` returned for a done feature *before* it read the
verdict. The one state the block existed for was the one state it could not be
reached in. The comments sat in their file, no session was opened to hand them
to, and the human was shown the production reminder as though nothing had been
said.

Now the verdict is read first, and `returned` puts the cycle back on step 4 in
the same worktree, with the complaint as the session's opening prompt. No
question is asked: QA moving an issue out of that column is a judgement already
made, and "back to the review?" would be asking whether they meant it — the same
reason a rolled-back production is not put to a vote.

The preview's verdict goes back with it, and only the preview's. Entering the
review step already clears the local stage and deliberately spares the deployed
ones, because "a preview verdict that is still true" is worth keeping — after a
hand-back that reasoning inverts, since the preview is exactly what QA looked at
and rejected. Left `passed`, the gate short-circuits on it and the fix returns
to QA without the deployment ever being checked again. Production's verdict is
left alone: if it shipped, that run was about a deployment the comment did not
concern.

Nothing moves the column back. It returns to `In QA` the ordinary way, when the
fix's own preview regression goes green — doing it "helpfully" here would be
fighting the board with the person who just moved it.

## Step 4: review rounds

**A regression's fix reaches the pull request before the review.** A fixing
session commits and is not told to push, and the review reads only what the
pull request carries: its threads hang on the pull request's lines. So
`run_step` pushes such commits (`regression_push_fix`) before the local
review of step 4's next session, as the step's close already did; four of
them once left the review saying it had not run, for a person to push.

**Step 4 runs one review round per session.** On one pull request five rounds of
fixes ran in one conversation, and every file each fix read stayed in its
context. The session now fixes through subagents and keeps only the
coordination; and once the automatic review closes every thread it fixed and
posts new ones, it writes `.sclaude/local/feature/review-round` and stops. A session cannot
clear its own context, so the orchestrator does: a watcher started beside every
review session sees the file and ends the `claude` process (found by
`--session-id`/`--resume` and its id), the run is recorded in the issue as
"fixes confirmed", and a fresh session opens. Its snapshot of the pull request
lists only the review threads still open — the resolved ones are counted, not
repeated — so the new round starts with the new findings and nothing else.

**Rounds that stop converging are said, once.** The report after each round
ends on a verdict from the findings per round. When it says "Not converging"
over four rounds or more (`stuck` in `review_report.py`), the next fresh
session is preceded by a warning that names the keys ending the search — `s`
while a review pass runs, ⏭ on the feature's topic (`review_stuck_say`). Said,
not asked: the session was closed by the orchestrator, nobody is bound to be
there, and a question would hold the rounds until somebody answered. On one
pull request the verdict said "Not converging" eighteen rounds in a row, each
followed by a fresh session, until the person stopped it by hand.

**Leaving step 4's session does not close it on its own.** After the session exits, the step closes only once the automatic review has finished with the pushed head and left nothing open: no check running or red (the findings check among them) and no unresolved review thread (`pr_context.py --close`). Otherwise sclaude waits for a running review, says what is open, and offers the session back; closing anyway is a second, explicit answer.

**Every commit a step's session makes names it.** sclaude launches claude with `core.hooksPath` pointed at `sclaude/githooks` through `GIT_CONFIG_*` in that process's environment only; its `commit-msg` adds `Sclaude-Session: <id>` — the id the issue's table and `claude --resume` use — at the end of the trailer block, and every hook there then runs the project's own hook of the same name. A row in the issue finds its commits with `git log --grep=<id>`. Commits made by hand are untouched.

## Returning a feature by hand

**QA is one reason to return a feature, not the only one.** One pull request
reached `done` on an automatic review that had read a third of it; the ten real
findings a second review found could only be sent back by moving the card as
though QA had. `sclaude return <name> [reason]` is that same return under its
own name: it saves the notes (the reason first), moves the card from `In QA` to
`In progress` so the board does not claim QA has a feature being fixed, records
that column so the timer does not announce the move, and leaves the `returned`
verdict for `cmd_resume` to act on — the board path and this one meet there.
Either way the state says `reopened_by: returned` and `reopened_since`, and the
session is told to read the issue and the pull request for itself from that
moment: the notes are a copy, and a reply added since is part of what it has to
answer. Only a finished feature can be returned; one still on a step is told to
say what is wrong where its session reads it.

The four lines that put a step back — clear its `done`, clear its `finished`,
name the new current step — are now `step_rewind_to` in `steps.sh`, shared by
this, by the regression's rewind after a red deployed stage, and by
`sclaude replan`. They differ only in which steps they name: one, one, and all
four.

Each is offered as a question, and on a "yes" the script runs the commands it
showed itself, one at a time, printing each before running it. What is shown and
what is run are the same list: a divergence here would be worse than no hint at
all. The chain breaks off at the first error, so that a promote that did not go
through does not drag a deploy along with it.

## The end of the cycle

The order is **preview → QA → merge → prod → the outcome into the issue →
clean-up**, and none of it is arbitrary. The preview and its regression come
first because they are what make the branch worth merging at all; offering the
merge before them would be offering to merge something nobody has checked. QA
comes next and before the merge, because a verdict given after the merge can no
longer hold anything back. The merge is the human's step, so it is offered
rather than taken, and only once QA has passed the issue and GitHub says the way
is clear. Production follows the merge because `vercel --prod` ships what is in
main.

Step 4 used to close only on a merged pull request, and that ran this order
backwards: the preview and "In QA" live after step 4, so the branch was merged
first and QA looked at main afterwards. Step 4 now closes on a green regression
with the pull request open, and sclaude waits in two stages, each saying which
event it is waiting for:

- **Waiting for QA** (`qa_wait`, every `QA_POLL` seconds). QA checks the
  acceptance criteria in the issue and moves it to `Done`. `Done` moves on to
  the merge. `In progress` or `Backlog` is a hand-back: QA's comments are
  collected and the review session opens with them, in the same run. Any other
  column is unexpected, and sclaude asks for the status to be set properly and
  keeps waiting. Unticked criteria do not block `Done` (GitHub Projects cannot
  refuse a status change); sclaude names them, and the merge question names
  them again.
- **Waiting for the merge** (`merge_wait`, every `MERGE_POLL` seconds), after
  the merge question was declined or GitHub named something in the way.

## The pull request on the board

**The pull request carries the same story on the board.** Step 3 opens it as a
draft, and sclaude assigns it to its author and puts it in the milestone of the
issues it closes. An issue with no milestone has no say. If two issues are in
different milestones, sclaude asks which one to use (`pr_setup`, `pr_milestone`).
It stays a draft until QA has moved *every* issue it closes to `Done`. Then
`pr_qa_handoff` marks it ready, moves it to `Backlog`, clears its assignees and
posts a `<!-- sclaude:merge-ready -->` summary. The summary holds what the merger
needs without opening the issue: the preview, QA's verdict, how often the work
came back, the acceptance criteria, how many review findings were found and how
many are still open, whether the review finished on this head (zero findings
mean nothing if it did not), the checks and the regressions. This happens once
per head; a later accepted head rewrites the summary in place. After the merge
the pull request goes to `Done` (`pr_board_set`).

The hand-off does not need anybody at a terminal. sclaude runs it while it
waits for QA. The QA timer runs it too, through `sclaude _handoff <feature>` in
the project, whenever it finds the issue in `Done`. It keeps trying on every
sweep until the hand-off succeeds, because a PR that closes two issues becomes
ready when the second issue reaches `Done`, and that issue is not the one the
timer watches. It stops trying once the PR is merged, closed or gone. A
lock on the feature keeps the two from handing over the same PR twice. The
timer acts on the hand-off's exit code, not on its wording. Telegram reports the
outcome: the PR is ready, it is still waiting on a named issue, or a step
failed and will be retried. A hand-off that fails partway records nothing, so
the next try repeats every step; each step is safe to repeat. This is the one thing the timer changes; everything
else it only reports.

Ctrl-C leaves either wait and loses nothing: `sclaude <feature>` comes back to
the same place, and the QA watch keeps looking in the meantime.

The clean-up is last, and it moved there deliberately: it removes the worktree,
and everything above it may still need one. A red production regression opens a
fixing session in that tree; a rollback records the failing log inside it; the
section written into the issue is assembled from `state.json`, which lives
there. So the tree survives until there is nothing left that could want it — and
even then the script does not advise the clean-up but asks, because the worktree
and the branches disappear irreversibly.

## The epilogue: the outcome in the issue

**The last thing the cycle does is write the outcome into the issue — and into
all of its parents.** A closed sub-issue changes an epic's state, but the epic
says nothing about it: to understand where it stands, the children had to be
opened one by one. Now every level of the chain has a `Current status` comment
headed by `<!-- sclaude:status -->`, and a separate session writes it — "where this epic stands now" is a judgement, not a
substitution. The chain is walked upwards up to ten levels, with protection
against a loop: `parent` comes from GitHub rather than from our own state.

The same comment may carry a second section, `Current behaviour`: how the
product actually behaves where that is no longer what the description says.
`Current status` is the management view, `Current behaviour` the product one,
and a description is never edited, so this section is the only place its drift
is recorded. On the feature itself it is written when the build left the
description behind — through the `User request` comment, a QA hand-back, a
review decision — and for that the feature's discussion goes into the session
along with the chain. On a parent it is written when the feature is a change
request to it: a child that renames or regroups the fields the parent
describes. A child that only adds — more detail, a field more — leaves the
parent without one, and the rewrite climbs the chain only as far as the
contradiction reaches. An existing section is read and rewritten, never
started over, so what earlier children established in it stays; and it
describes what is on `main`, which the session checks with `git grep` and
`git show` against `origin/main` rather than by touching the working tree.

The `deployed-preview` and `deployed-prod` labels appear alongside — the script
sets them itself, by how the preview and prod blocks ended, and sets them on the
whole chain. By how they *ended*, which means the regression and not the upload.

The two stages are not symmetrical, and the asymmetry is the point. A preview
that deployed and then failed its suite gets **no** `deployed-preview`: it would
be read as "it is there and it works", and the fixing session that follows a red
run pushes again, so the label would name a commit that is already leaving. A
production that failed its suite keeps `deployed-prod`, because that label claims
only that the code reached production — and it did, which stays true whatever the
suite then found.

What says a stage is broken is a mark of its own: `preview-regression-red` and
`prod-regression-red`. These are the only labels here that come off again — the
regression gate removes the stage's mark the next time that stage passes, from
the whole chain it went on to. They can, where `deployed-*` cannot, because
nobody writes them by hand: the script sets them from a suite result and clears
them from a suite result. A mark saying "broken" that could never be cleared
would be sitting on the epic a year after the fix shipped.

`deployed-preview` follows what is true rather than what happened today: a
preview already on hosting from an earlier run, with a suite that has passed,
carries the label even though nothing was deployed this time. It used to be read
off "did we deploy in this run", which cost the label outright whenever a red run
was followed by a redeploy by hand.

The section says the rest in words, which is the one place a qualifier fits — and
it names the deployed commit, so that a claim outlives the worktree that recorded
it. The labels are created on demand if the repository does not have
them yet. If prod is postponed there will be no `deployed-prod` label, and the
section will say the feature is waiting for the merge: a section that cannot be
trusted is worse than none. `deployed-locally` is deliberately absent: it would
be true of every issue while `next dev` is alive and false the moment the laptop
is closed — and besides, nobody but the machine's owner can open such a
deployment.

## The summary table in the issue

The summary's **Friction** column says what became of the review for each step
and each fixing session. Six answers, because one dash used to stand for four
different things and a reader could not tell them apart — a step nobody had
reached yet looked exactly like a step that ran into nothing. Each value is
written by the orchestrator at the moment it happens; none is inferred when the
comment is assembled:

| Value | What it means |
|---|---|
| `queued` | The cycle has not reached this step. Nobody has looked yet — not "there was no friction". |
| `nothing` | The log was empty, so no session was launched. The ordinary case: most steps run into no ban worth reporting. |
| `` `id` open `` | Interrupted, with a conversation to return to. It holds the cycle until `sclaude friction` or `sclaude reset` closes it. |
| `` `id` stalled `` | `claude` exited at the door. The id names a transcript with nothing in it, so there is nothing to resume — clear it rather than return to it. |
| `` `id` fixed `` | The review ran and committed to the orchestrator: `HEAD` moved while it was open. |
| `` `id` reviewed `` | The review ran and changed nothing — it read the entries and found every ban deliberate. |
| `` `id` unread `` | Closed by hand through `sclaude reset`. The entries stayed in `.reviewed` with nobody reading them. |

The **Status** column says how each fixing session ended. It was a dash for
every one of them until it became clear what that cost: a stage with four
sessions showed four identical cells, and one of those four was the one that
made it green. A fixing session has no step status — it is not a step — but it
does have an outcome, and the orchestrator knows it exactly:

| Value | What it means |
|---|---|
| `green` | The re-run passed after this session. It is the one that fixed the stage. |
| `red` | The session finished and the stage failed again. The attempt was counted. |
| `blocked` | The cause was outside the branch. Nothing was changed and the attempt was given back — deliberately not `red`, or the row numbers would disagree with `attempts`. |
| `stalled` | `claude` exited at the door, leaving no assistant record. Nothing ran, so the stage was not left red by it. |
| `open` | Interrupted, with a conversation to return to. |
| `—` | No record: the feature predates the field. Nothing is guessed backwards from how the stage ended. |

The outcomes live in `regression.<stage>.fix_status`, space-joined and aligned
with `fixes` position for position — `state_set` writes scalars, which is what
made `fixes` a string too. Writer and reader derive the row from the same place.

The id is the review's own session, kept under `was` once the review closes, and
`claude --resume <id>` in sclaude's checkout opens it again. It is a separate field
from `session` on purpose: `run_friction` reads `session` to decide whether to
resume, and an id left there would send the next review into the closed
conversation instead of starting a new one.

A line under the table appears when a step ran in the background. By design that
cannot happen — a step with no terminal is refused — so it only shows on
features started by an earlier `sclaude`, and it explains why the cycle stopped
there: a backgrounded step never reaches `after_step`, so it got no next step
and no friction review.

**Underneath stands a second table: what the friction reviews actually changed.**
The column above says *that* a review fixed the orchestrator; it cannot say what
the fix was, and a reader was left to open sclaude's checkout and work out which
commits fell between two steps of a feature. So `run_friction` keeps the
instruments `HEAD` from either side of a review that committed — it already
compared the two to decide whether to push — and the summary turns that range
into commit subjects with `git log`. The range is honest by construction:
while a review is open, the only things running in that tree are the review's
own session and read-only git calls.

A row is one commit, and the step is named once per review, so a review with
four commits reads as one piece of work rather than four unrelated ones.

| Verdict | What it means |
|---|---|
| `lifted` | A restriction was loosened or removed. |
| `deliberate` | Nothing changed, on purpose: every entry was a ban working as intended. |
| `mixed` | Both happened in the same review. |

The verdict is the one thing no amount of reading the commits recovers. `git
log` describes a lift and is silent about the opposite — a review that read
every entry, found each ban correct and changed nothing leaves no commit at
all, and so had no row here. The review therefore says it in words: the two
prompts ask for a last line, `sclaude-verdict: <kind> — <clause>`, and
`friction_verdict` reads it back out of the review's transcript once the
session exits. It is read rather than written by the session on purpose — the
review works in sclaude's checkout with the feature's tree outside its scope, and
widening that scope so it could write one bookkeeping file would hand the one
session that edits the orchestrator a writable path into the product.

Only the kinds in the table are accepted, so a model quoting the instruction
back cannot land a word in the issue as though it were a decision; the last
line wins, so a review interrupted and resumed reports what it finally left
behind. A review that printed no line keeps its commits and shows a dash — the
table behaves as it did before the verdict existed.

The section is absent entirely when no review has committed or left a verdict,
which is what every feature already in flight will show: their reviews recorded
neither. That is accepted rather than repaired, for the same reason the
`queued` back-fill was: inferring the values now would put back exactly the
guessing this removes.

The status is a comment, not a part of the description, on every issue in the
chain — whoever wrote it. There used to be one concession to the rule "we do not
touch somebody else's body": this section was appended to it. It is gone; a
`Current status` a human wrote into a description stays there, and the session
takes what is still true from it into its comment.

It is deliberately not one of the four steps the state tracks, although the
menu numbers it 5. It runs before the clean-up, while the worktree is still
there, but by then the feature is already `done`, and an epilogue that broke
off may be finished later with `sclaude epilogue` — after `sclaude done` has
removed the worktree and its `state.json`. So it keeps its own record outside
every repository, in `~/.claude/sclaude/epilogue/<feature>.json`, and the
session runs from the main repository. In its construction this is closest to
the friction review — a session outside `STEPS`, with a prompt of its own.

**A friction review reads its own entries.** Before it starts, the fresh log is
appended to `friction.log.reviewed` and kept apart as
`friction-<key>.log`, which is what the review is handed: `.reviewed` holds
every review's entries, and a review handed all of it read the earlier steps'
again and put the same refusal off twice. `sclaude friction`, a re-read, still
reads everything. A log of nothing but proposed `CLAUDE.md` rules needs no
session: sclaude puts them off to the monthly review itself. It no longer
asks by default: the question held the cycle between a fix session and the
review of its fixes until it was answered, and the answer was nearly always
"put off". `SCLAUDE_FRICTION_ASK=on` asks again, for a rule a decision of the
same cycle rests on that should not wait a month; a "no" hands the log to a
review told to write them in now.

**Before they are put off, they are matched** (`friction_classify.py`). Each
step's session names its proposal's class itself, and on one feature four
sessions proposed one rule under four classes, one of them a rule the
project's `CLAUDE.md` already stated: the monthly review, which decides by
how often a class comes back, would have read one rule seen four times as
four rules seen once. So one call of a small model (`SCLAUDE_CLASSIFY_MODEL`,
haiku) reads the proposals, the classes already put off and `CLAUDE.md`, and
says of each: the same rule as a class already there (it takes that class),
a rule `CLAUDE.md` states (put off under `claude-md-already-stated`, the line
quoted, for the monthly review to drop), or new. The answer is checked, not
trusted — a class must exist, a quote must be `CLAUDE.md`'s word for word —
no row is dropped, and any failure leaves the rows as they came. The call is
capped at a minute: it stands between a fix session and the review of its
fixes.

Each class is counted as it goes in: "2nd time since the last monthly
review, in 2 features". The count is worked out from the rows, one per
occurrence, rather than kept in a field: each feature has a file of its own
so that two branches never edit the same lines, and a counter two branches
raised would conflict at every merge. `SCLAUDE_FRICTION_CLASSIFY=off` skips
the matching. Each such put-off is
a review of the key's own, numbered in its commit and kept in the key's runs.

## sclaude's own files in a product

The state lives in `.sclaude/local/feature/state.json` in the feature's worktree. Vercel's CLI
never reads `.gitignore`, so before every deploy (a preview from the worktree,
production from the main repository) sclaude makes sure that tree's
`.vercelignore` names `.env`, `.env.*` and everything sclaude writes into the
project: `.sclaude/local/feature`, `.vercelignore` itself, and `.sclaude`, where the terminal
recordings are kept. It only appends what is missing, and a `.vercelignore`
the project tracks itself is left to the project, with a warning for what it
lacks; `sclaude doctor` checks the same in advance. One list in
`sclaude/lib/scratch.sh` serves git and Vercel both, and there is nothing to
configure. These are the script's internal files: they do not outlive the
feature and have no business in the repository — the script hides them through
`.git/info/exclude`, which is machine-local and shared by every worktree, rather
than through a rule in `.gitignore` that would have to go through a PR. They are
not shown in the clean-up: the question "there are uncommitted changes in the
worktree" must mean you are losing work rather than that the script left its own
rubbish.

The directory goes away with the worktree on `sclaude done`, which checks the
fact of the merge with GitHub and asks before every deletion.

## The cycle's record

**One line survives it: the cycle's own record.** Everything the cycle measures
about itself is in that `state.json` — when each step started and finished, how
many fixing sessions a red regression needed, which friction reviews committed
and which found every ban deliberate — and all of it used to die with the tree.
So the questions the record answers could not be asked at all: is the cycle
getting faster, which step actually holds it up, are two fixing attempts enough
or generous.

Just before the clean-up, and before the worktree in `sclaude drop` too, the
state is flattened into one record and appended to
`~/.claude/sclaude/cycles.jsonl`. Outside every repository, for the reason the
epilogue's state and the QA watch are: `$REPO` is the product's tree, where
steps 2-4 work and `git add -A` is an everyday thing, and a service file with
timings would ride into somebody else's commit.

Append-only, JSON Lines. A finished feature is a fact, and in a format where the
last line is the only writable one a machine dying mid-write cannot corrupt the
nineteen above it. Each line parses on its own, so the file is read with `jq`
without loading all of it:

```bash
jq -s '[.[] | select(.outcome == "done") | .steps.code.seconds] | add / length' \
  ~/.claude/sclaude/cycles.jsonl
```

Deliberately not aggregated by sclaude and deliberately not a database. Twenty
lines of JSON answer a question in one command; a schema would have to be
decided now, before anybody has looked at the data, and that is the wrong order.

Each record names who ran the cycle (`developer`, from `developer.sh`; `null`
where nobody could be named) and the product (`repo`, its main checkout). A
product whose team wants its cycles in one place names a git repository of its
own under `metrics` in its `.sclaude/config.json`; each developer's records of
that product — only that product's — are then published there as
`<developer>.jsonl` after every record. One file per person, so publishing never
conflicts, and a second machine of the same person adds its lines rather than
replacing the first's. A clone per remote is kept under `~/.cache/sclaude/metrics/`.

The remote used to be one file per person (`~/.config/sclaude/metrics-remote`),
and somebody working on two products published both into one team's
repository, where one team saw the other's feature names and paths. Now each
product's records go only where that product says. Not this repository, on
purpose: the records carry the team's feature names and paths, and instruments
is shared by everybody who installs it. No key, no publishing.

`outcome` is what keeps a finished feature and an abandoned one apart — `done`
against `dropped` — and they must never be averaged together: an abandoned
feature's timings describe a decision to stop, not a cycle that ran its course.
It is recorded rather than inferred, because a feature dropped at step 4 looks
exactly like one that finished.

Throughout, a value that is not known is `null` rather than zero. A step nobody
reached and a step that took no time are different facts, and the second is what
a zero would average in as. The whole call is best-effort down to the `|| true`:
a record that cannot be written is one measurement lost, and losing it must not
stand in the way of cleaning up a merged feature.

## Abandoning a feature

**Work that was decided against is cleared away by `sclaude drop`.** `done` is
the clean-up after success: the PR is merged, the code is in main, all that is
left is sweeping. Here it is the opposite, and an abandoned feature has five
traces: the worktree, the local branch, the branch in `origin`, the pull request,
the issue. Forgetting any of them means leaving rubbish that will be remembered
in a month and not understood.

One command for all five — but not one question for all five, as in `done`. There
the human agrees to a clean-up after the merge, where there is nothing to lose;
here every "yes" destroys something nobody asked to have destroyed, and their
costs differ: a worktree with uncommitted work cannot be recovered by anything,
whereas a closed issue can be reopened. So each action is asked about separately,
and refusing one does not cancel the rest: sometimes the branches need tearing
down while the issue stays. Every question comes first and the work after it, in
order from the irreversible to the reversible: the feature's questions go to its
Telegram topic, which goes with the worktree, and a person who changes their mind
halfway stops with everything still in place. The pull request is asked about
before the branch in `origin`, and closed before it is deleted: deleting a pull
request's head branch closes it on GitHub, so a pull request kept open keeps its
branch.

What exactly the feature has, the script works out before the first question and
shows as a table: asking "remove the worktree?" without showing that a branch, a
PR and an issue stand behind it means leading the person blind. It asks GitHub
about the PR's and the issue's state rather than trusting `state.json`: they may
have been closed by hand, and offering to close what is closed is noise people
learn to answer without looking. The PR and the issue are not deleted but closed:
deleting a PR through the API is not possible at all, and a closed pair remains
the history of the decision not to do this work. The issue is closed as "not
planned" — in a milestone's report what was abandoned must not look like what was
done.

In the menu it is the third item, after "new feature", and it deletes nothing
itself — it drops into a separate list where the feature is chosen once more,
with a "none, go back" item last. Adjacent numbers, one of which continues the
work while the other destroys it, are a mistake waiting for its chance; the
submenu is the protection against a finger that missed.
