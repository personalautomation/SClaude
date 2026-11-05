# Refactoring candidates

What the structural refactoring of 2026-11-05 found and left for later: each
item says what it is, why it is worth doing, and what holds it back. The
refactoring itself split the largest modules by what each part does and laid
`sclaude/lib` out in folders (see "Where things live in sclaude/lib" in
`CLAUDE.md`). Strike an item when it is done; add one when a change runs into
it.

## Long functions

Bash functions too long to read whole. Their phases share locals, so cutting
them is a rewrite rather than a move: phases as functions over an explicit
state (a state file or named globals), each with a bench.

| Lines | Ran | Function | Where |
| ---: | ---: | --- | --- |
| 906 | 29% | `remind_prod` — the epilogue: preview, QA, merge, production | `ship/deploy.sh` |
| 682 | 11% | `issue_sync` — the issue's summary (mostly a Python heredoc) | `github/issue_sync.sh` |
| 528 | 12% | `run_friction` | `improve/friction.sh` |
| 466 | 70% | `run_step` | `cycle/run.sh` |
| 360 | 49% | `regression_gate` | `ship/regression_gate.sh` |
| 345 | 53% | `after_step` | `cycle/run.sh` |
| 336 | 4% | `run_status` | `github/outcome.sh` |
| 328 | 0% | `regression_run_body` | `ship/regression.sh` |
| 261 | 71% | `review_close_gate` | `review/review_gate.sh` |
| 257 | 44% | `cmd_done` | `commands/done.sh` |
| 240 | 0% | `cmd_abandon` | `commands/abandon.sh` |
| 229 | 0% | `feature_action_items` | `commands/actions.sh` |
| 218 | 44% | `session_ended` | `cycle/run.sh` |

"Ran" is the share of a function's command lines the suite runs, from
`tests/coverage` (2026-11-05). A rewrite starts by raising it: the lines no
bench reaches are what a rewrite breaks unseen. `tests/coverage --show
<function>` lists them. The 0% ones are only searched as text by the benches,
never run.

`remind_prod`, `issue_sync` and `run_status` are mostly decisions over JSON
and GitHub's answers; they would read better in Python, called from the
shell as the other helpers are. Not done: a rewrite, not a move, and the
benches do not cover every branch.

`Handler` in `keepawake/handling.py` (some 800 lines) was looked at for a
dispatch table over per-screen modules and decided against, 2026-11-05:
`callback` is one flat chain of some 35 short branches, each found by its
button's data (`"svc_lang"`, `"cfg:"`), and `message` reads its typed text in
order. A table would move the branches without removing a line, and modules
would pass `self`, the press, its message and `now` across every boundary.

## Large files not split yet

| Lines | File | What holds it back |
| ---: | --- | --- |
| 1980 | `bin/sclaude-proxy` | one asyncio server sharing its state (`GATE`, `FLOW`, the map's reload) across what would be its parts; a package means passing that state, not just moving functions |
| 1737 | `review/pr_context.py` | see "pr_context: how to split it" below |
| 1284 | `sclaude/hooks/forbidden-commands.py` | its rules share `POLICY`/`rule_on` and `segments`, and `environments_data` and `project_dir` call each other: a split rebuilds the hook's frame, in the hook that enforces the bans — a session of its own, with the hooks bench as the judge |
| 1259 | `tree/worktree.sh` | the tree, its dev server and its ports |
| 1091 | `bin/keepawake` | the detector and `status` |
| 1047 | `bin/wsl-update` | |
| 4512 | `tests/keepawake.py` | one bench for the whole bot. Decided against splitting it (and `hooks`) for speed, 2026-11-05: the suite's benches take some 1210 s of CPU, about 150 s on eight cores, so the run is bound by the sum, not by its longest bench (105 s), and a split would gain no time |
| 2072 | `tests/regression.py`, 1595 `tests/review-round.py` | the same |

Decided against, 2026-11-05: `metrics/metrics_guide.py` as a data file. It is
data already — a dict of tuples and three small band helpers — and JSON would
put each paragraph on one line and `7 * DAY` as `604800`.

### pr_context: how to split it

The benches replace ten of its names on the module (`gh_json` in 22 places,
`recent`, `open_threads`, `review_mode`, `review_threads`…). Split as it is,
a function in one part would keep its own reference to another part's
function, the replacement would no longer reach it, and the bench would call
the real `gh` — which is signed in on this machine. In order:

1. a client module (`gh`, `gh_json`, `pr_view`) that every part calls through
   its module attribute (`gh_client.gh_json(...)`), and the benches replace
   there;
2. the parts call one another through module attributes too, never by a name
   imported from another part;
3. the names CLAUDE.md couples (`YOURS_FILE`, `NIGHT_MARK`, `NIGHT_FILE`,
   `CHECKS_VERDICTS`, `LOCAL_SIGNATURE`, `findings_explained`, `night_yours`,
   `night_take`) stay in `pr_context.py`, or CLAUDE.md and their benches move
   with them.

## Settings in code

Numbers that are policy rather than logic, each in its own module:
`REGRESSION_MAX_ATTEMPTS`, `REGRESSION_E2E_MAX_FAILURES`,
`REGRESSION_TIMINGS_KEPT` (`ship/regression.sh`), `AUTO_RETURNS`
(`cycle/run.sh`), `REVIEW_CONTEXT_MAX_PCT` (`core/steps.sh`), the bot's
`POLL_TIMEOUT`, `BACKOFF_MAX`, `AGENTS_FRESH`, `TOPIC_*`, `PUBLISH_*`,
`IDLE_*`. Candidates for `sclaude/config.example.json` where a project could
want its own value, or for one module of defaults where nobody should.

## The waits whose purpose is not written down

Some pauses are deliberate and their reason is not obvious from the code.
Removing one is a guess; a local log of what happened during it turns the
guess into a decision. Since 2026-11-05 `wait_note` (`core/ui.sh`) writes a
line of JSON per such wait to `SCLAUDE_WAITS_LOG`, which `bin/sclaude` sets to
`~/.local/state/sclaude/waits.jsonl` (never in git; past a megabyte it starts
again, the last one kept as `.1`). Unset — a bench running a function on its
own — nothing is written:

| `wait` | Where | `ended` / `arrived` |
| --- | --- | --- |
| `poll-swallow` | `poll_pause` swallowing the keys behind the first (`core/ui.sh`) | `escape` (an arrow's bytes), `text` or `other`; how many characters came after the first key. Written only when something was swallowed. |
| `tab-tee` | the tab waiting up to two seconds for `tee` (`core/pane.sh`) | `done` or `outlived`; `seconds` as `0.6`, claude's exit code |
| `session-grace` | `SESSION_GRACE` (30 s) and `SESSION_ACCEPT_GRACE` (3 s) after a turn ends with its marker (`cycle/session_watch.sh`) | `human` — the person spoke within it (not under [k]), after `seconds` — or `closed`; the session's kind and the grace it had |

To read it: `jq -s 'group_by(.wait,.ended) | map({wait:.[0].wait, ended:.[0].ended, n:length})'
~/.local/state/sclaude/waits.jsonl`. The suite writes its own in its
temporary directory. A wait is a candidate to shorten
when weeks of lines show nothing ever arriving in it: `poll-swallow` never
`text`, `tab-tee` always `done` within a fifth, no `session-grace` `human`.

Not a general log of everything: the project has its journals already
(history.jsonl, review-context.log, the rounds' journal, DORA), and a log
with no question behind it goes unread.

## Smaller cleanups

- Python heredocs inside shell (some 80 `python3 -`/`python3 -c` sites):
  each is code without a bench of its own; the larger ones belong in modules.
- A CLI module that siblings also import (`pr_context.py` run as a script and
  imported by `review_report.py`) exists twice in that process, as
  `__main__` and by name. Harmless while neither keeps state the other reads.
- `_path.py` keeps bare-name imports working across the folders. Absolute
  imports would make it unnecessary, at the price of rewriting every import
  once — decided against: no gain for the person using the tools.
- The benches' 641 folder-qualified module paths (`"%s/core/state.sh" % LIB`)
  break only when a folder moves; left as they are.

## Done on 2026-11-05

- The suite: 317 s to about two minutes (orphaned sleeps held the runner's
  pipe; three cases ran into product waits their stubs never satisfy).
- `state_set` and every other writer of `state.json` under a lock, written
  whole (`core/state_file.py`); a lost update reproduced on the old code.
- The flaky benches (pane, keepawake, review-round, answers, feature_db),
  with two product bugs found on the way: a Cyrillic letter cut by `ask`'s
  wait, and `session_watch_stop` removing [k]'s file before the watcher.
- `tests/lib/benchlib.py`: shell functions found by name.
- `core/state_schema.py` and its check; `state_snapshot` for the menu.
  The key reshuffle (`stages.*`, `cycle.*`, `feature.*`) was decided
  against: some 400 edits for a cosmetic gain.
- `core/cycle_steps.py`: the steps in one table.
- `core/feature_files.py` and its check, rather than path constants every
  reader would use.
- The gate closes on new code for its socket to start it again.
- The pages' scripts and styles as `.js` and `.css` files.
