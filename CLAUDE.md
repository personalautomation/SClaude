# instruments

Machine-level Claude Code helper scripts and skills. Not tied to any project —
they live here, symlinked into `~/.local/bin` and `~/.claude/skills`.

## English only

**Everything written in this repository is in English.** Comments, docstrings,
commit-adjacent prose, prompts, terminal output, log lines, error messages,
identifiers, test descriptions — all of it.

This is not a style preference. These tools print to a terminal and to a
Telegram bot that other people read, and the bot picks its language from
Telegram's `language_code`. A Russian string in shared code reaches a reader who
did not ask for it, and there is no mechanism to translate it on the way.

The rule covers new code and any line you touch in old code. Do not leave a
Russian comment standing next to an English one you just wrote.

### The three exceptions

These are load-bearing. Do not "fix" them.

1. **`keepawake/i18n.py`** — key → (Russian, English) pairs. The bot is
   deliberately bilingual and chooses by the client's language. Both halves
   stay; comments *around* them are English.

2. **`keepawake/docs.py`** — the same, for the bot's long-form docs sections.

3. **Cyrillic characters that match keystrokes**, in `sclaude/lib/picker.sh`
   (the `q` key). On a Russian keyboard layout `q` types as `й`. Removing it
   means a quit typed with that layout stops counting.

   Yes/no answers are deliberately *not* in this list: `is_yes`/`is_no` in
   `sclaude/lib/ui.sh` take only `y`, `yes`, `n`, `no` in any case, and `ask`
   re-asks until it gets one. Do not add Cyrillic or a default back.

### Strings that are coupled across files

Some text is compared, grepped for or quoted elsewhere. Changing one side alone
breaks the other silently — grep before you edit:

- `KeepAwake.ps1` writes hold-log lines that `bin/keepawake` greps for
  (`hold set|hold released|holding`).
- `keepawake status` prints the section headings `HOLD` and `HEALTH`; both
  halves of `docs.py` quote them, and `tests/keepawake.py` asserts on them.
- `OWN_MARKERS` in `sclaude/hooks/collect-denials.py` must match the text the
  hooks actually emit; `tests/hooks.py` guards this.
- The issue-comment markers (`REQUEST`, `AC_OPEN`/`AC_CLOSE`, `STATUS`) are
  declared once, in `sclaude/lib/issue_comments.py`, and imported elsewhere;
  `sclaude/prompts/plan.md` and `status.md` spell them out for the model.
  `tests/status.py` fails if a copy reappears in `github.sh`.
- `.sclaude/local/feature/review-yours` — the review threads the person decided to leave —
  is named by `YOURS_FILE` in `sclaude/lib/pr_context.py` and spelled out in
  `sclaude/prompts/review.md`, which tells the session its line format;
  `tests/parallel.py` checks the two agree.
- `findings_explained` in `pr_context.py` reads the findings check that the
  project's `claude-code-review.yml` writes: its title ("N unresolved review
  findings", "posted as a comment, not as threads") and the `#discussion_r…`
  links in its summary. Change that workflow's wording and this reads every
  red check as real again.

- `closed/<id>.json` in a question channel (`.git/sclaude/` or a feature's
  `.git/sclaude/ask/<slug>/`) — how a question ended — is written by
  `ask_closed` in `sclaude/lib/io.sh` and read by `CLOSED_DIR`/`closed_asks` in
  `keepawake/telegramd.py`, which turns the question's message into the answer
  by it; without the record the message is deleted as unanswered.
  `tests/io.py` checks what is written, `tests/keepawake.py` what is read.
- The feature channel `.git/sclaude/ask/<slug>/` (`ask_channel` in `io.sh`,
  `ask_channels` in `telegramd.py`), the bot's record of a feature
  `telegram.json` and the clean-up's `ended` mark (`ask_record`,
  `ask_feature_end` in `io.sh`; `FEATURE_RECORD`, `ENDED_MARK` in
  `telegramd.py`) are named on both sides; `tests/io.py` and
  `tests/keepawake.py` check each side.
- `notes/` in a feature's channel — messages that ask nothing, such as where
  the review stands after each round — is written by `ask_notice` in
  `sclaude/lib/io.sh` and read by `NOTES_DIR` in `keepawake/notices.py`;
  `tests/notices.py` runs both sides. The text itself is the file that
  `SCLAUDE_REPORT_BRIEF` names to `sclaude/lib/review_report.py`
  (`review_report` in `run.sh`).

- `CONTEXT_FILE` in `statusline.py` (`/tmp/claude-statusline-context-<session>`)
  is read by `review_context` in `sclaude/lib/run.sh`, which decides by it
  whether a review round stays in the same session; `tests/review-round.py`
  runs both sides.
- `.sclaude/local/feature/review-reversals` is named by `reversals_file` in
  `run.sh` and spelled out in `sclaude/prompts/review.md`;
  `tests/review-round.py` checks the two agree.

- `as on r<id>`, the reply `sclaude/prompts/review.md` asks for when a
  declined thread repeats an earlier one, is read by `CITED` in
  `sclaude/lib/review_report.py`; `tests/review-report.py` checks both sides.

  <!-- The two entries above were added by Claude, not asked for line by line:
  they came with the parallel-features fixes of 2026-10-09, so that a later
  edit to one side does not silently break the other. -->

- `CHECKS_VERDICTS` in `sclaude/lib/pr_context.py` — the exit codes and first
  words that `sclaude checks` ends on — is listed in `sclaude/prompts/review.md`,
  which tells step 4 what each one means; `tests/checks-wait.py` checks the two
  agree.

  <!-- Added by Claude on 2026-10-14, as the plan for the bounded step 4 wait
  asked: the prompt acts on the codes, so a code changed on one side alone
  would send a session the wrong way without an error. -->

- `LOCAL_SIGNATURE` in `sclaude/lib/pr_context.py` ends every finding and
  reply a review run on this machine posts (`local_review.py`), and is how
  `review_state` tells them from what the person wrote under the same
  account; `tests/review-skip.py` and `tests/local-review.py` check both
  sides. `local-review-rounds.jsonl` is named in `local_review.sh` and read
  by `LOCAL_JOURNAL` in `review_report.py`; `tests/local-review-report.py`
  reads what the other side wrote.

  <!-- Added by Claude on 2026-10-15 with the `review` key, so that a change to
  one side does not silently turn the review's words into a person's. -->

## Public repository, private projects

This repository is public (personalautomation/SClaude). The projects sclaude
drives are not. sclaude's review sessions — friction reviews, the monthly
deferred review, retrospectives — work from those projects' material and
change the product, never this checkout (`sclaude/hooks/write-guard.py
--readonly`). Whoever commits here by hand still works from what they saw in
a product, so nothing committed here names a project's details: no project names, no pull-request,
issue or feature numbers, no file paths, tables, services or infrastructure
of a product. Describe a problem in the orchestrator's own terms. What belongs
to a project's story goes to that project.

Data about projects that sclaude collects stays with the project: the
deferred friction and the session rules in the product's `.sclaude/`
(`sclaude/lib/deferred.sh`, `sclaude/lib/policy.py`), and terminal recordings
in its `.sclaude/local/`, which git and every Vercel upload are kept out of
(`sclaude/lib/scratch.sh`).

## Who commits the orchestrator to main

`MAINTAINERS` lists the git addresses allowed to commit sclaude's core straight
to `main`. Everybody else proposes a change on `dev/<name>` (the name comes
from `developer_name` in `sclaude/lib/developer.sh`), which reaches `main`
through a pull request. The review sessions do not commit here: they change
the product. A step session whose plan reaches into this checkout may commit
here and push to `main` (`OWN_CHECKOUT` in `sclaude/hooks/forbidden-commands.py`).

<!-- Provenance: changed by Claude at the owner's explicit decision on
2026-10-13, after a code step's push to this checkout's main was refused
twice and the person had to finish by hand. The old line said no session
commits here. -->

With `MAINTAINERS` absent everybody is a maintainer, which is what a copy used
by one person wants.

## Commit messages

English, like everything else in this repository — the rule above has no
exception for commit messages. Conventional Commits subject, a body explaining
*why*, and an unbroken trailer block at the end. `githooks/commit-msg` refuses
a message whose trailer block is broken.

## Tests

`python3 tests/<name>.py` — each file is standalone and exits non-zero on
failure.

Before a commit, run the tests that touch what changed: every test file that
names a changed file (a test sources or runs the modules it guards by name).
The whole suite takes minutes, most of it `tests/resume.py`, and a commit does
not need it:

```bash
for f in $(git diff --name-only HEAD; git diff --name-only --cached); do
  grep -l "$(basename "${f%.*}")" tests/*.py
done | sort -u | while read -r t; do python3 "$t" >/dev/null || echo "FAIL $t"; done
```

Run them all before a push, which is what reaches every machine (auto-sync
from `main`):

```bash
for t in tests/*.py; do python3 "$t" >/dev/null || echo "FAIL $t"; done
```

## The README before a push

Before every push, bring `README.md` up to date with what the push carries: a
new command, key, switch or behaviour a user meets goes in, and one that
changed or went away is corrected there. Read the commits being pushed
(`git log origin/main..HEAD`) against the README, and commit the update in the
same push. A push with nothing a user would notice needs no edit, but the check
is still made.

The README is for people using the tools: what each does, and what they do
with it. How a part works inside and why goes to `docs/sclaude.md` or
`docs/keepawake.md`, which are updated the same way when the push changes
something they describe.

Shell files have no test runner of their own; check them with `bash -n`.

## Editing shell scripts while they run

`bin/sclaude` and `bin/keepawake` are edited by sessions that are themselves
running them. bash reads a script lazily, by offset into an open descriptor, so
an in-place edit shifts everything the process has not read yet. Both files wrap
their bodies in `{ … }` so bash must parse to the closing brace before executing
anything, and end the block with `exit` so bash never reads past it — after
`}` it would resume at the old offset, now mid-line in a grown file. Keep both.

The same hazard is why `sclaude`'s body lives in `sclaude/lib/*.sh`: a module is
read whole at `source` time and is safe to edit afterwards.

## A trap when writing Python inside shell

Heredocs and `python3 -c '...'` blocks are single-quoted. An apostrophe in a
comment inside one closes the string literal and breaks the script. Write "the
menu's item" as "the item in the menu", or use a `<<'PY'` heredoc.
