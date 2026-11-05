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

| Lines | Function | Where |
| ---: | --- | --- |
| 906 | `remind_prod` — the epilogue: preview, QA, merge, production | `ship/deploy.sh` |
| 682 | `issue_sync` — the issue's summary | `github/issue_sync.sh` |
| 528 | `run_friction` | `improve/friction.sh` |
| 466 | `run_step` | `cycle/run.sh` |
| 360 | `regression_gate` | `ship/regression_gate.sh` |
| 345 | `after_step` | `cycle/run.sh` |
| 336 | `run_status` | `github/outcome.sh` |
| 328 | `regression_run_body` | `ship/regression.sh` |
| 261 | `review_close_gate` | `review/review_gate.sh` |
| 257 | `cmd_done` | `commands/done.sh` |
| 240 | `cmd_abandon` | `commands/abandon.sh` |
| 226 | `feature_action_items` | `commands/actions.sh` |
| 218 | `session_ended` | `cycle/run.sh` |

`remind_prod`, `issue_sync` and `run_status` are mostly decisions over JSON
and GitHub's answers; they would read better in Python, called from the
shell as the other helpers are. Not done: a rewrite, not a move, and the
benches do not cover every branch.

`Handler` in `keepawake/handling.py` is one class of some 800 lines: every
command, every typed text and every button press. A dispatch table over
smaller handler modules (per screen: hold, phone, config, asks, cards) would
let one screen be read alone.

## Large files not split yet

| Lines | File | What holds it back |
| ---: | --- | --- |
| 1979 | `bin/sclaude-proxy` | one asyncio server; its parts (routing, the gate, the demo, the DORA page, sign-in) could become a package like keepawake's |
| 1737 | `review/pr_context.py` | the tests replace `gh_json`, `review_mode`, `recent` in it: a split needs a GitHub client module they patch instead; CLAUDE.md couples eight of its names |
| 1284 | `sclaude/hooks/forbidden-commands.py` | the rules, the parsing and the friction log in one hook |
| 1259 | `tree/worktree.sh` | the tree, its dev server and its ports |
| 1254 | `core/steps.sh` | the steps' table, names and icons, which several readers mirror |
| 1091 | `bin/keepawake` | the detector and `status` |
| 1057 | `metrics/metrics_guide.py` | mostly prose: a data file it reads |
| 1047 | `bin/wsl-update` | |
| 4471 | `tests/keepawake.py` | one bench for the whole bot; per-module benches would follow the split modules |
| 2072 | `tests/regression.py`, 1595 `tests/review-round.py` | the same |

## Web assets inside Python

The pages carry their scripts and styles as Python strings: `PLAY_SCRIPT`
(some 590 lines of JavaScript), `INTERACT_SCRIPT`, `LIVE_SCRIPT`,
`PRINT_SCRIPT` and the styles in `flow/process_page.py` and
`flow/process_doc.py`, `STYLE`, `TIP_JS` and `TEAM_JS` in
`metrics/dora_page.py` and `metrics/dora_team.py`. As `.js` and `.css` files
beside the module, read when the page is drawn, an editor would check them
and a diff would show them as code.

## Settings in code

Numbers that are policy rather than logic, each in its own module:
`REGRESSION_MAX_ATTEMPTS`, `REGRESSION_E2E_MAX_FAILURES`,
`REGRESSION_TIMINGS_KEPT` (`ship/regression.sh`), `AUTO_RETURNS`
(`cycle/run.sh`), `REVIEW_CONTEXT_MAX_PCT` (`core/steps.sh`), the bot's
`POLL_TIMEOUT`, `BACKOFF_MAX`, `AGENTS_FRESH`, `TOPIC_*`, `PUBLISH_*`,
`IDLE_*`. Candidates for `sclaude/config.example.json` where a project could
want its own value, or for one module of defaults where nobody should.

## Tests coupled to the file layout

Many benches read a module's text and cut a function out by regex
(`functions(RUN, [...])`), or source modules by path, or count a string in a
named file. Every function moved tonight meant editing such benches. A helper
outside the benches (a `tests/lib/` folder is not a bench to `tests/run`)
that finds a function in `sclaude/lib` by name and sources modules by bare
name would let a module move without touching its tests — while keeping each
bench naming the modules it guards, which `tests/run --changed` matches on.

`tests/pane.py` is timing-sensitive: under the parallel suite's load its
`[r]` checks fail about one run in three; alone it passes.

## Long-running processes and new code

The bot runs itself again in place when its code or sclaude's library
changes and the new code imports. The gate (`sclaude-proxy --gate`), which
serves the Mini App and imports keepawake's `webmenu` and sclaude's modules on
first use, does not: while the phone keeps the Mini App open it can serve old
`webmenu` code beside sclaude modules imported new. It idles out otherwise,
and this predates the refactoring. A re-exec like the bot's, tried on code
that loads, would close it; the main proxy, which loads neither, should not
take it on (a re-exec there drops its idle bookkeeping and live connections,
and leaves its spawned children unreaped).

## Smaller cleanups

- Python heredocs inside shell (some 80 `python3 -`/`python3 -c` sites):
  each is code without a bench of its own; the larger ones belong in modules.
- pyflakes warnings that predate the refactoring: unused `errno` in
  `keepawake/state.py`, `sys` and `urllib.parse` in `keepawake/webmenu.py`,
  `HARD_HOLDERS` in `keepawake/status_report.py`, the unused locals
  `started` in `keepawake/handling.py` and `_la` in `flow/process_diagram.py`.
- A CLI module that siblings also import (`pr_context.py` run as a script and
  imported by `review_report.py`) exists twice in that process, as
  `__main__` and by name. Harmless while neither keeps state the other reads.
- `_path.py` keeps bare-name imports working across the folders. Absolute
  imports (`from sclaude.lib.review import pr_context`, the way keepawake
  imports its modules) would make it unnecessary, at the price of rewriting
  every import once.
