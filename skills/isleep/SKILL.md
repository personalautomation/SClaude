---
name: isleep
description: Night mode. The person has gone to sleep and the work in this session has to go on without them. Claude answers its own questions by its best judgement instead of asking, keeps going where it would otherwise stop to ask whether to continue (another review round, the next item, a retry), keeps a log of every decision it took, and gives the person a morning summary of those decisions when they come back. Runs only when the user invokes /isleep.
argument-hint: "[here] [<N>h] [what to carry on with] | report | off"
---

# isleep — carry on while the person sleeps

`/isleep [task]` — the person is going to sleep. Whatever this session was
doing goes on without them until it is done; `task`, when given, says what to
carry on with or how far to go. The night covers every Claude session on the
machine — those already running, and those started during it (an
orchestrator's next step, a fresh session after a crash); `here`, on the
`/isleep` that starts the night, keeps it to this session — a night already
over every session stays so. `<N>h` sets how long the night lasts, 12 hours by default.
`/isleep report` writes the morning summary and the night goes on;
`/isleep off` ends it with the summary.

The night also ends at the person's first input in **any** session: whatever
they type means they are back.

## The night outlives the session

Night mode is not only these instructions: it is a machine-level record,
`~/.local/state/isleep/night.json`, kept by `night.py` beside this file and
read by hooks that every session runs (`install.sh` registers them; each does
nothing while no night is on). When the person types `/isleep …`, the prompt
hook has already started the night before you read this. From then on, until
the person writes, `/isleep off`, or the night's hours run out, in every
session of the night:

- a new session, a compaction, a `--resume` or a restart brings the night
  into context (SessionStart), so do not treat a summary that lost these
  rules as the end of night mode — the hook's reminder is the rule;
- a session already running when the night began is told at its next tool
  call (PostToolUse) — a session idle at its prompt stays idle;
- `AskUserQuestion` is refused with the instruction to decide;
- a turn that tries to end is asked once whether work is left;
- a prompt from the person, in any session, ends the night, and that
  session is told to give the morning summary first. Prompts that are not the
  person's are told apart and keep the night: a headless `claude -p`, the
  prompt sclaude launched a step's session with (a prompt the person gives
  `claude` on its command line is theirs), a `/loop` wakeup — and so also a `/loop` the person types,
  which reads the same; a headless run is not nudged at its stop either,
  since its last answer is its output;
- a night that runs out its hours ends the same way: its sessions are told,
  and the person's first prompt, whenever it comes, gets the summary;
- after the night, each session it was announced to is told, once, at its
  next tool call — or, closed meanwhile, when it is resumed — that it is over — so its reminder does not go on
  deciding for the person. A session told so asks again as by day and gives
  no summary.

A session started before the hooks were installed does not run them; only
these rules reach it, and only if it ran `/isleep` itself.

`python3 ~/.claude/skills/isleep/night.py status` shows the night;
`… night.py off` ends it. If `status` prints nothing right after `/isleep`,
the hooks are not installed: say so in a line (re-running `install.sh` adds
them) and go on by these rules alone.

Talk to the person in the language they write in. The log and the summary are
in that language too — they are written for them.

## Before the night: fewer permission prompts

A question can be decided; a permission prompt cannot — the session stands
on it until morning. So the first thing `/isleep` does, before the task, is
run the `fewer-permission-prompts` skill once for this project: it reads the
past sessions' transcripts and allows the read-only commands that kept being
asked for. Tell it to write them to `.claude/settings.local.json` — personal
and kept out of git — not to the project's shared `.claude/settings.json`.

This is the one change to permissions night mode makes itself: the person
asked for it by typing `/isleep`, and the skill allows only commands that
change nothing. Take its recommended list without asking. If the write is
refused, or the skill is not there, note it under **Waiting for you** — the
person can run `/fewer-permission-prompts` before the next night — and go on
with the task. Skip this step on a second `/isleep` the same night.

## sclaude's review goes on by itself

In a project sclaude runs, its `[g]` "go on by itself" follows the night by
itself under the project's `sleep_mode: auto` (the default): while a night
over every session is on — not a `here` one — step 4's review rounds retry a failed pass, check the fixes and go back
to a review session without asking. Nothing is to be done for it, before the
night or after. Mention in the summary which features went through review
rounds that way.

## What changes

You have time. Nobody is waiting for a quick answer, nobody is there to answer
a question, and a stop that waits for the person waits all night. So:

1. **Do not ask — decide.** Wherever you would ask the person (`AskUserQuestion`,
   a question in the text, a skill or prompt saying "ask the user"), take the
   answer you would have recommended and go on. When there is no clear
   favourite, take the option that is easiest to undo, keeps the most work, and
   stays closest to what the person asked for. Log the decision (below).
2. **Do not stop to ask whether to go on — go on.** Another review round, the
   next item of a list, fixing what the last check found, a retry after a flaky
   failure: if the honest answer to "should I continue?" is "it would help", do
   it. `/sreview`'s "ask every N iterations" is answered *yes* until the review
   finds nothing substantive; its per-class questions are settled by your
   recommendation, and each policy made that way is written with
   `(isleep — to confirm)` after it, so a later run knows the person never said
   it.
3. **Do not end the turn while there is work.** A turn that ends is a session
   that sleeps too. Waiting for something — a CI run, a deploy, a long build —
   goes through `Monitor` or a background command, not through ending the turn with "I'll check later". Stop only when the work is done, or
   when everything left is blocked on the person (rule 4).
4. **What still waits for the person.** Night mode decides questions; it does
   not grant permissions. Anything hard to undo or seen outside this machine
   stays as it would by day — a push, a merge, a deploy, a release, deleting
   or overwriting what you did not make, a message, comment or post to other
   people, money (a paid service, a costly review level nobody asked for),
   anything a project rule or memory says needs the person's word. Leave such a
   step undone, write it under **Waiting for you** with exactly what is ready
   and the command that does it, and carry on with whatever does not depend on
   it. A step the person already approved for this task before going to sleep
   is not waiting — they said yes.
5. **When stuck, go round.** A step that fails the same way twice is not
   retried a third time the same way: try another approach, or set it aside,
   log why, and do the rest. One blocked item is never a reason to stop the
   others.

   A permission refused — by the auto mode classifier, a hook, or a rule — is
   the same: it is not a question to wait on. Do not look for another command
   that does the same thing past the refusal. Write the step under **Waiting
   for you** with the exact command and why it was needed, and carry on with
   what does not depend on it.
6. **Stay inside the task.** Time to spare is for finishing what was asked
   well — checks, tests, another review pass — not for new work nobody asked
   for. An idea worth doing goes in the summary under **Ideas**, not into the
   code.

## The log

Keep it in the file `night.py status` names as `log` —
`~/.local/state/isleep/<YYYY-MM-DD>.md`, the evening's date. It survives a
compaction, every session of the night writes to the same one, and the morning
summary covers them all. Only append to it (`>>` or an edit at the end): other
sessions write there too. Read it before the first decision — after a
compaction or in a session that joined, it says what was already settled.

Start it when night mode starts, if this session has no section there yet:

```markdown
# <repository or directory> — started <HH:MM>

Task: <what is being carried on, in a line or two>
Starting point: <branch and HEAD, or the state of the work>
```

Then add an entry **at the moment** you take each decision — not at the end
from memory:

```markdown
## <HH:MM> <repository>: <the question, in a line>

- Chosen: <what you did>
- Instead of: <the other options>
- Why: <a sentence>
- To undo: <how, if the person disagrees — a commit, a file, a command>
```

Log questions that mattered: one the person would have been asked, or would
want to know was settled — not every routine step. Also log what waits for the
person, and what was set aside and why, as they happen.

## The morning summary

Any message from the person, in any session, means they are back: the prompt
hook has already ended the night and tells that session to give the summary
in its reply — and to go on with what it was doing: the summary is shown, not
a stop. Write it then, on `/isleep off`, on `/isleep report`, or
when the work is done and nothing is left to do: at the end of the log file,
and in your reply. A session that only learns from a hook that the night is
over gives no summary — the one the person wrote in does — and asks the
person again from then on.

Without the hooks the night ends at the first message from the person in
this session, and `python3 ~/.claude/skills/isleep/night.py off` after the
summary makes sure of it.

1. **Result.** What was done, in a few lines: what got finished, what state the
   work is in (branch, HEAD, tests passing or not, review rounds and what they
   found).
2. **Decisions taken for you.** Each logged decision in one line — the question
   and what was chosen — the ones most worth a second look first. Point at the
   log file for the details and the way to undo each.
3. **Waiting for you.** What is ready but needs the person's word, each with
   the command that does it.
4. **Set aside.** What was not done, and why.
5. **Ideas**, if any.

Short — the person reads it with their first coffee. Give the full path of the
log file. If the session can send a file to the person's other device
(`SendUserFile`), send the log there too.

The summary covers every session's sections of the log, not only this one's;
say which repository each line is about.

After the summary the work goes on as it was — do not end the turn or wait
for the person because the night ended. Only questions change: they go back
to the person, including those listed under **Waiting for you**. `/isleep report` alone does not end the night — the
summary is written and the work goes on.
