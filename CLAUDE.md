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

3. **Cyrillic characters that match keystrokes**, in `sclaude/lib/core/picker.sh`
   (the `q` key). On a Russian keyboard layout `q` types as `й`. Removing it
   means a quit typed with that layout stops counting.

   Yes/no answers are deliberately *not* in this list: `is_yes`/`is_no` in
   `sclaude/lib/core/ui.sh` take only `y`, `yes`, `n`, `no` in any case, and `ask`
   re-asks until it gets one. Do not add Cyrillic or a default back.

### Strings that are coupled across files

Some text is compared, grepped for or quoted elsewhere. Changing one side alone
breaks the other silently — grep before you edit:

- A feature built in parts (`sclaude/lib/tree/parts.sh`): the plan's
  `## Parts` section, its `### Part <n> — <title>` headings and a criterion's
  `[part <n>]` are spelled out for step 1 in `sclaude/prompts/plan.md` ("If I
  choose to split") and read by `plan_parts.py` (`SECTION`, `PART`, `TAG`),
  which `acceptance.py --part` filters each part's criteria by;
  `tests/plan-split.py` checks the shape the prompt shows is the one read.
  The `<if:in-parts>`/`<if:parts-built>`/`<if:parts-done>`/`<if:asks-accept>`/
  `<if:part-alone>` keys and `<part>`, `<parts>`, `<part-base>`, `<umbrella>`,
  `<base>` are set by `render_prompt` in `prompt.sh` for `code.md`, `pr.md`
  and `review.md`, by the phase `parts_building`/`parts_whole`/
  `parts_reviewing` in `parts.sh` and by `partAccept` (`project_part_accept`
  in `project.sh`, `CHOICES` in `config_menu.py`); `tests/parts.py` renders
  them. `parts built`, `parts accepted`, `parts merged` and `parts stop` rows
  are read by `_part_of` in `process_history.py`; `tests/process.py` plays them.
  A part's branch that does not take the part before it or the common
  branch in without conflicts goes to the sync session (`parts_merge_in` →
  `sync_with_main`) with `SYNC_FROM`/`SYNC_REF` set to it: the sync
  session's path in `sync.sh` reads it through `sync_source`
  (`merge_build_check`, about main alone, is not reached from there), and
  `sync.md` takes
  `<from>` and `<if:from-parts>` from it; `tests/parts.py` runs the
  hand-over.

  <!-- Changed by Claude on 2026-11-08 at the user's decision: a split
  feature stays one issue, one plan and one QA, built in parts inside step 2,
  a pull request for each into the feature's branch; before, the later parts
  became issues of their own. -->

  <!-- Changed by Claude on 2026-11-08 at the user's decision: the parts are
  built first and the whole accepted once; only then is each part's pull
  request opened and reviewed, one by one, in the order they were built — a
  review spent before the person has seen the feature is thrown away by their
  first large remark. -->

- `KeepAwake.ps1` writes hold-log lines that `bin/keepawake` greps for
  (`hold set|hold released|holding`).
- `keepawake status` prints the section headings `HOLD` and `HEALTH`; both
  halves of `docs.py` quote them, and `tests/keepawake.py` asserts on them.
- `OWN_MARKERS` in `sclaude/hooks/collect-denials.py` must match the text the
  hooks actually emit; `tests/hooks.py` guards this.
- The issue-comment markers (`REQUEST`, `AC_OPEN`/`AC_CLOSE`, `STATUS`) are
  declared once, in `sclaude/lib/github/issue_comments.py`, and imported elsewhere;
  `sclaude/prompts/plan.md` and `status.md` spell them out for the model.
  `tests/status.py` fails if a copy reappears in `github.sh` or the modules
  split from it (`issue_sync.sh`, `board.sh`, `outcome.sh`).
- `.sclaude/local/feature/review-yours` — the review threads the person decided to leave —
  is named by `YOURS_FILE` in `sclaude/lib/review/pr_context.py` and spelled out in
  `sclaude/prompts/review.md`, which tells the session its line format;
  `tests/parallel.py` checks the two agree.
- `NIGHT_MARK` in `sclaude/lib/review/pr_context.py` — what a night session's
  decision carries in `review-yours` — is spelled out in
  `sclaude/prompts/review.md`, which writes it at night and asks the person
  about such threads by day, and counted by `night_yours` for
  `review_night_offer` in `sclaude/lib/review/review_gate.sh`, which on the person's yes
  moves their lines to `NIGHT_FILE` (`review-night`, `night_take`) for the
  snapshot to mark them to be asked about; `tests/parallel.py` checks the
  sides agree. Reworded on one side alone, the morning offer never comes and
  the threads wait for the person's hand.

  <!-- Added by Claude on 2026-11-03 at the user's request: a night decision
  is confirmed by the person in the morning, and resolved by the session. -->
- `findings_explained` in `pr_context.py` reads the findings check that the
  project's `claude-code-review.yml` writes: its title ("N unresolved review
  findings", "posted as a comment, not as threads") and the `#discussion_r…`
  links in its summary. Change that workflow's wording and this reads every
  red check as real again.

- `closed/<id>.json` in a question channel (`.git/sclaude/` or a feature's
  `.git/sclaude/ask/<slug>/`) — how a question ended — is written by
  `ask_closed` in `sclaude/lib/core/io.sh` and read by `CLOSED_DIR`/`closed_asks` in
  `keepawake/asks.py`, which turns the question's message into the answer
  by it; without the record the message is deleted as unanswered.
  `tests/io.py` checks what is written, `tests/keepawake.py` what is read.
- The feature channel `.git/sclaude/ask/<slug>/` (`ask_channel` in `io.sh`,
  `ask_channels` in `asks.py`), the bot's record of a feature
  `telegram.json` and the clean-up's `ended` mark (`ask_record`,
  `ask_feature_end` in `io.sh`; `FEATURE_RECORD`, `ENDED_MARK` in
  `topics.py`) are named on both sides; `tests/io.py` and
  `tests/keepawake.py` check each side. `bin/sclaude-notify --in` reads the
  topic from that record's `thread` too; `tests/keepawake.py` checks it
  names the same file.
- `.sclaude/local/feature/closing` — a worktree whose removal has begun — is
  written by `stop_dev` in `sclaude/lib/tree/worktree.sh` (and taken back off when
  git refuses the removal), and honoured by `sclaude-proxy` (no lazy start)
  and by `CLOSING_MARK` in `keepawake/topics.py` (the menu offers the
  feature no more); `tests/ports.py`, `tests/proxy.py` and
  `tests/keepawake.py` check each side.
- `notes/` in a feature's channel — messages that ask nothing, such as where
  the review stands after each round — is written by `ask_notice` in
  `sclaude/lib/core/io.sh` and read by `NOTES_DIR` in `keepawake/notices.py`;
  `tests/notices.py` runs both sides. So does `notes/feed.tsv` — what sclaude
  prints about a feature, one tab-separated line each — written by `ask_feed`
  in `io.sh` and read by `FEED_FILE` in `notices.py`. The text itself is the file that
  `SCLAUDE_REPORT_BRIEF` names to `sclaude/lib/review/review_report.py`
  (`review_report` in `review_gate.sh`).

- The record of a topic's messages, `~/.local/state/keepawake/topics/<thread>`
  (`KEEPAWAKE_TOPICS` in tests), is named once, by `topic_ledger` in
  `keepawake/state.py`. It is written by `remember_in_topic` in
  `keepawake/topics.py` and by `bin/sclaude-notify`, which sends past the
  bot and imports the function, and read by `clear_topic_messages`, which
  deletes them with the topic; `tests/keepawake.py` runs both writers.

- The cycle's steps are one table, `sclaude/lib/core/cycle_steps.py`: their
  order, each one's launch and the icons sclaude's lines open with (the bot's
  words for the cycle's places stay in `i18n.py`, as `cycle.<name>`). The
  shell reads
  `cycle_steps.sh`, written from it (`python3 cycle_steps.py sh >
  cycle_steps.sh`) and committed — `STEPS`, `AFTER_STEPS`, `STEP_SPEC` and
  `PHASE_ICON` for `phase_icon` and `cycle_number` in `steps.sh`; the bot reads
  the table itself (`keepawake/cycle_table.py`) for `PHASE_ICONS` in
  `notices.py` and the order of `act.steps` in `i18n.py`; the process map for
  the steps' `SPEC`; the issue's summary gets `cycle_total` as
  `SCLAUDE_TOTAL`. `tests/session_names.py` fails when `cycle_steps.sh` is not
  what the table writes, or a place has no `cycle.<name>` in `i18n.py`. A step added there goes into `cycle_steps.sh` in the same change.
  `pane_icon` still maps a session's name to its kind by pattern.
  `feed_groups` in `notices.py` also reads `phase_words`' verbs: a line saying
  `started` or `resumed` opens a step's message and the `✅` of a step's
  `done` closes it, so a step's lines are not mixed with the next one's;
  `tests/notices.py` runs it on those lines.

  <!-- Changed by Claude on 2026-11-05 with the steps' table: the icons and
  the names were copies kept in step by a test; now there is one list. -->

  <!-- Added by Claude on 2026-10-24 with step 5, the sync with main: the
  steps after it moved up by one, and a list one short marks the wrong one. -->

- The sign-in link `<dev-url>/__sclaude/login?as=<email>&next=<path>` and
  `/__sclaude/users` are spelled out for the session in
  `sclaude/prompts/_dev-server.md` and served by `login_page`/`users_page` in
  `bin/sclaude-proxy` (`dev_login.py` issues the token), and built by
  `skills/sdemo/demo.py` (with `f=` on the phone's origin, `phone_origin` in
  `keepawake/phone_access.py`); `tests/dev-login.py` runs the proxy and checks
  the prompt and demo.py's links name the same.

  <!-- Added by Claude on 2026-10-31 with signing in as another user. -->

- A recorded demo, `.sclaude/local/demo/<id>/` in a feature's tree, is made
  by `DEMO_DIR` in `skills/sdemo/demo.py` and served by `DEMO_DIR` and
  `DEMO_PREFIX` (`demo_file`) in `bin/sclaude-proxy`; the files in it are
  named by `skills/sdemo/play.mjs`, and the page is `player.html` with its
  `/*DEMO*/` and `/*FEATURE*/` markers filled by play.mjs. `latest_demo` in
  the proxy reads the newest one's `demo.json` for the list of features and
  for the process map's link (`demo` of `page` in `sclaude/lib/flow/process_page.py`). The script's
  helpers (`d.say`, `d.click`…) are spelled out for the session in
  `skills/sdemo/SKILL.md`. `tests/dev-login.py` checks the two sides of the
  directory and the address.
- The demo's comment on the issue is headed by `DEMO`, declared in
  `sclaude/lib/github/issue_comments.py` and imported by `skills/sdemo/demo.py`,
  which writes it only for sclaude (`SCLAUDE_SESSION`, set by
  `session_git_env` in `sclaude/lib/cycle/run.sh` and by `demo_refresh`).
  `sclaude/prompts/code.md` tells step 2 to run `/sdemo`, and again after
  remarks when `demo.py stale` says the code changed;
  `demo_refresh` in `sclaude/lib/ship/demo.sh` asks `demo.py stale` (exit 0 with
  `stale:` — record again) once the preview's regression is green, before
  `issue_qa_ready`, where `project_flow_mode qa` is not `auto` (a delta and
  the whole demo), or before the last `run_status` where it is (the whole
  demo), with `SCLAUDE_DEMO_STAGE`, which `stage` in demo.py reads into the
  history (`history.json` beside the demos, the feature's page written from
  it and served by `demo_file` at `/__sclaude/demo/<feature>/`); it starts a
  session with the
  skill (`demo.py replay` without claude); the videos go through
  `bin/sclaude-notify --video` and `gh issue comment --attach`;
  `tests/dev-login.py` runs the comment, `stale` and `replay`. The ref
  `refs/sclaude/demo/<label>` (`DEMO_REF` in demo.py) holds the last full
  demo's tree and is deleted by `remove_worktree` in
  `sclaude/lib/tree/worktree.sh` once the tree is gone; `TEXT_ONLY` in demo.py is
  what `bin/sclaude-notify` says when the videos were refused and the text
  went, `SENT` the line `--ids` starts with: the message ids demo.py
  keeps in the history (`messages`), which a later full demo hands to
  `sclaude-notify --delete` (`withdraw_old`), and `STAYED` the line
  `--delete` names what stayed with, which `withdraw_old` keeps to try
  again, and `LEFT` what Telegram will never delete. `tests/dev-login.py`
  checks all five. `demo_refresh` holds what
  its session plays with `SCLAUDE_DEMO_HOLD=1` (read by `cmd_play`) and
  publishes its last delta and last full recording (none after `keep`) with
  `demo.py publish`, which clears their `held` mark, picked from
  `history.json` by `sclaude/lib/ship/demo_refresh.py`, which also reads the
  `kept` entry `demo.py keep` writes and the session's `findings.md` there;
  `tests/demo-refresh.py` runs both sides.

  How far a recording got is the player's `progress: {json}` lines
  (`progress` in `skills/sdemo/play.mjs`), which `play_watched` in demo.py
  (`PROGRESS`) keeps in the feature's state as `demo_progress` (in
  `state_schema.py`), cleared when the player ends; it is read by
  `demo_progress.py` in `sclaude/lib/ship` — which `demo_refresh` pipes the
  session's `--output-format stream-json` events into — and by
  `demo_progress` in `statusline.py`. `tests/demo-progress.py` runs each
  side.

  <!-- Added by Claude on 2026-11-10 at the user's request: a demo recorded
  with nobody watching showed nothing for up to forty minutes. -->

  <!-- Added by Claude on 2026-11-03, with the refresh held and kept, at the
  user's request after a retrospective: a name changed on one side alone
  would publish every try again, or none. -->

  <!-- Added by Claude on 2026-10-31 with the recorded demo of /sdemo; the
  issue comment and the steps' demo on 2026-11-01. -->

- Every state field the shell names — `state_get`, `state_set`, a
  `state_snapshot`'s `${snap[...]}` — is listed in
  `sclaude/lib/core/state_schema.py`, with its meaning; `tests/state-file.py`
  fails on one missing there and on an entry nothing names. A field added to
  the code goes into the schema in the same change.

  <!-- Added by Claude on 2026-11-05 with the state's schema: a mistyped
  field reads as "not set", without an error. -->

- Every file kept in a feature's `.sclaude/local/feature/` is listed in
  `sclaude/lib/core/feature_files.py` with what it is for;
  `tests/feature-files.py` fails on a name the code writes out in full
  (`.sclaude/local/feature/<name>`) that is not there, and on an entry
  nothing names. A file added goes there in the same change.

- `.sclaude/local/feature/review-fallback` — a feature whose review could not
  run on GitHub and moved to this machine — is written by
  `review_fallback_set`/`review_fallback_inherit` in
  `sclaude/lib/review/review_round.sh` and read by `project_review_mode` in
  `sclaude/lib/core/project.sh` and `FALLBACK_FILE` in
  `sclaude/lib/review/pr_context.py`; `MINUTES` and the `QUOTA_*` patterns
  there read the job's annotations and log for why. The setting `github-local`
  that allows the move is in `CHOICES` (`config_menu.py`), read by
  `project_review_setting` and `review_mode`, and drawn by the map
  (`NEEDS`, `setting` in `process_config.py`). `tests/parallel.py` runs
  both sides. Renamed on one side alone, the pass runs here while the
  verdict still counts the red review job in Actions.

  <!-- Added by Claude on 2026-11-10 at the user's request: the review moves
  to this machine when GitHub's runs out of Claude quota or Actions minutes. -->

- `CONTEXT_FILE` in `statusline.py` (`/tmp/claude-statusline-context-<session>`)
  is read by `review_context` in `sclaude/lib/review/review_round.sh`, which decides by it
  whether a review round stays in the same session; `tests/review-round.py`
  runs both sides.
- `.sclaude/local/feature/review-reversals` is named by `reversals_file` in
  `review_round.sh` and spelled out in `sclaude/prompts/review.md`;
  `tests/review-round.py` checks the two agree.

- Step 2's closing question — the header `Accept work`, the option `Accept`
  and the marker word `accepted` — is spelled out in `sclaude/prompts/code.md`
  and read by `ACCEPT_HEADER`/`ACCEPT_LABEL` in `sclaude/lib/cycle/session_end.py`
  (`code_accepted` in `session_watch.sh`) and the watcher's short grace in
  `session_watch_start`; `tests/code-accept.py` checks the sides agree.
  Reworded on one side alone, sclaude asks again in its terminal, or a
  session closes on half a report.

  <!-- Added by Claude on 2026-10-31 with step 2 accepted in its own dialog. -->

- `as on r<id>`, the reply `sclaude/prompts/review.md` asks for when a
  declined thread repeats an earlier one, is read by `CITED` in
  `sclaude/lib/review/review_report.py`; `tests/review-report.py` checks both sides.

  <!-- The two entries above were added by Claude, not asked for line by line:
  they came with the parallel-features fixes of 2026-10-09, so that a later
  edit to one side does not silently break the other. -->

- `CHECKS_VERDICTS` in `sclaude/lib/review/pr_context.py` — the exit codes and first
  words of the verdict line `sclaude checks` prints — is listed in `sclaude/prompts/review.md`,
  which tells step 4 what each one means; `tests/checks-wait.py` checks the two
  agree.

  <!-- Added by Claude on 2026-10-14, as the plan for the bounded step 4 wait
  asked: the prompt acts on the codes, so a code changed on one side alone
  would send a session the wrong way without an error. -->

- `review-checked`, which `cmd_checks` writes as it returns, is what
  `review_pane_keys` in `local_review.sh` prints the report by;
  `tests/local-review.py` runs it.

- `LOCAL_SIGNATURE` in `sclaude/lib/review/pr_context.py` ends every finding and
  reply a review run on this machine posts (`local_review.py`), and is how
  `review_state` tells them from what the person wrote under the same
  account; `tests/review-skip.py` and `tests/local-review.py` check both
  sides. `sclaude/prompts/review.md` spells it out for the night check of a
  minor thread, which takes only a bot's finding or one ending with it;
  `tests/review-report.py` checks the prompt names it. `review-rounds.jsonl`, the review's one journal wherever it
  ran, is named by `review_journal` in `local_review.sh`, `JOURNAL` in
  `local_review.py` (whose `github_runs` adds the workflow's runs, `source:
  github`), `LOCAL_JOURNAL` in `process_history.py` and `review_pass_rows` in
  `issue_sync.sh`; the report reads its rounds from it alone, and the map and
  the issue price each local pass by its `session`, the unrecorded ones
  (`spent`) included; `tests/local-review-report.py` reads what the other
  side wrote.

  <!-- Extended by Claude on 2026-11-04 at the user's request: the review
  passes are priced in the report and on the process map from the journal. -->

  <!-- Extended by Claude on 2026-11-06 at the user's request, in a
  retrospective: a night session resolves a minor finding of the review's own
  after reading the thread fresh, and the prompt names the signature. -->



  <!-- Added by Claude on 2026-10-15 with the `review` key, so that a change to
  one side does not silently turn the review's words into a person's. -->

- `review-said` in a feature's channel — the review's keys pressed in its
  topic — is written by `SAID_FILE` in `keepawake/review_keys.py` and taken by
  `review_said_take` (`REVIEW_SAID_FILE`) in `sclaude/lib/review/local_review.sh`;
  the buttons go on the lines `phase_words` in `steps.sh` prints for a local
  review pass and a fix session starting, which `PASS_START` and
  `SESSION_START` there match. `tests/notices.py` runs both sides on
  `phase_line`'s own output, `tests/local-review.py` a stop from the phone.

  <!-- Added by Claude on 2026-10-24 with the review's keys in Telegram: a
  word or a start line changed on one side alone would leave the buttons
  doing nothing, or missing. -->

- The workshop's record, `.sclaude/local/instruments.json` beside the
  workshop (`workshop_record` in `sclaude/lib/improve/workshop.sh`), lists in
  `approved` the sessions that may write there; `sclaude/lib/improve/workshop.py`
  writes it and `approved` in `sclaude/hooks/write-guard.py` reads it, and
  `--workshop DIR` names the record as `DIR.json`. `tests/write-guard.py` and
  `tests/workshop.py` check each side.
- `sclaude core-open` is refused a step's session and let through for the
  reviews by `core_open_refused` and `CORE_OPEN_FREE` (`--step friction`) in
  `sclaude/hooks/forbidden-commands.py`, and refused step 1 with core-ready
  and core-send by `SUBCOMMANDS["sclaude"]` in `no-code-in-planning.py`
  (`SCLAUDE_REASON`); `core_send_refused` refuses core-send at every other
  step. Only the retrospective's prompt and
  the friction and deferred reviews' carry `prompts/_workshop.md`
  (`workshop_rules` in `workshop.sh`, `render_prompt` in `prompt.sh`), and the
  process map's W follows the prompts. `tests/hooks.py` and
  `tests/process.py` check each side.
- sreview's mark of a finished run, `$S/branches/<branch>.reviewed` holding
  the head it finished on, is written by `skills/sreview/SKILL.md` ("Report")
  and read by `workshop_sreview_mark` in `workshop.sh` before `core-ready`
  lets a maintainer's change go out; `tests/workshop.py` reads it.
- `WORKSHOP_PHONE_MAX` in `workshop.sh` stays under `ASK_CONTEXT_MAX` in
  `keepawake/asks.py`, which clips a question's context in the middle: a
  leak question longer than that is asked at the terminal alone, so that a
  "yes" from the phone never covers lines it did not show.
- `<workshop-rules>` in `sclaude/prompts/_friction-body.md` and
  `friction-deferred.md` is filled by `run_friction` in `sclaude/lib/improve/friction.sh`
  and `cmd_deferred` in `sclaude/lib/improve/deferred.sh`; `<block:workshop>` in the
  step and retrospective prompts by `render_prompt` in `prompt.sh`.

  <!-- Added by Claude on 2026-10-26 with the workshop: a name changed on one
  side alone would leave a session unable to write where it was let, or a
  maintainer's change published unreviewed. -->

- The `**Committing.**` lead in `sclaude/prompts/_friction-body.md` is what
  the endings of `friction.md` and `friction-fix.md` send the session to by
  name; `tests/regression.py` checks the lead and that both name it below
  `<body>`.

  <!-- Added by Claude on 2026-10-30 during review of the change that put the
  friction commits' footer exception there: renamed on one side alone, the
  endings would point at nothing. -->

- The process map, `sclaude/lib/flow/process.py` and its parts
  (`process_*.py`, listed in `PARTS`), names every command
  `bin/sclaude` dispatches (`COMMANDS`), every verb of the action list in
  `sclaude/lib/commands/actions.sh`, the steps as `STEPS` and `cycle_number` number
  them, and reads `state.json`'s fields to say where a feature stands
  (`position`, called by `cmd_flow`); `bin/sclaude-proxy` serves it at
  `/__sclaude/flow`, the Mini App opens it through the gate (`FLOW_PREFIX`,
  `map_button` in `keepawake/phone_access.py`), and
  `docs/presentations/bpmn_diagrams.html` is built from it.
  `tests/process.py` checks each side and fails on a stale built page: a
  command, a step or a way back added to the code goes on the map in the
  same change.

  <!-- Added by Claude on 2026-10-26 with the process map: a map that
  disagrees with the code is worse than none. -->

- A feature's history, `.sclaude/local/feature/history.jsonl` beside its
  state, is written by `session_runs` and `history_add` in
  `sclaude/lib/core/state.sh` and read by `HISTORY_FILE`/`history` in
  `sclaude/lib/flow/process_history.py`, which knows the `what` and `op` words the
  writers use (`regression.<stage>`, `fix.<stage>`, `qa in`, `workshop
  main`, `ask answered` from `ask_log` in `io.sh`, `command` from
  `history_command`…); a word changed on one side alone drops that place
  from the played history, or an input from its count, without an error.
  `tests/process.py` runs both sides. An `edge` row (`history_edge`) names
  two places of a map by their ids in `process_model.py`: the test fails on
  a pair no map draws, and on an arrow of a map in `RECORDED` that no code
  writes and `UNWRITTEN` does not explain.

  <!-- Added by Claude on 2026-10-28 with the played history of a feature. -->

- The DORA page, `.sclaude/local/dora/index.html` in the product's main
  checkout, is written by `DIR`/`PAGE` in `sclaude/lib/metrics/dora_store.py` and served by
  `DORA_PAGE` in `bin/sclaude-proxy`; `tests/dora.py` and `tests/proxy.py`
  check each side. dora.py finds rollbacks by the heading and the marker
  `rollback_incident` in `sclaude/lib/ship/rollback.sh` writes (`ROLLBACK_HEADING`
  in dora_sources.py, `ROLLBACK` in `issue_comments.py`); reword that comment and failures stop being counted. The page
  also reads the names `session_label` in `sclaude/lib/core/steps.sh` gives a
  session (`step_of` in `sclaude/lib/metrics/claude_usage.py`; `tests/session_names.py`
  feeds it every kind) and the columns of `review-context.log` that
  `review_context_log` in `review_round.sh` writes (`review_log` in
  `sclaude/lib/metrics/dev_quality.py`; `tests/metrics-page.py`).

  <!-- Added by Claude on 2026-10-27 with the DORA page: a path or a heading
  changed on one side alone leaves the page missing or every failure unseen. -->

- `night.py active` (`skills/isleep/night.py`) is what `review_go_on` in
  `sclaude/lib/review/local_review.sh` asks, under `sleep_mode: auto`
  (`project_sleep_mode` in `sclaude/lib/core/project.sh`, `CHOICES` in
  `config_menu.py`), whether a night over every session is on; `tests/isleep.py` runs it and
  `tests/config-menu.py` the setting. Renamed on one side alone, the night's
  review rounds stop going on by themselves, without an error.
  `review_night_offer` in `sclaude/lib/review/review_gate.sh` asks `night.py active` too, and
  ends the night with `night.py off --away <why>` on the person's yes, so the session it
  opens asks rather than decides.

  <!-- Added by Claude on 2026-10-31 with sleep_mode, at the user's word. -->

- The machine's settings, `sclaude.update` (`auto`, `notify`, `off`),
  `sclaude.contribute` (`send`, `ask`, `off`) and `sclaude.leaks` (`ask`,
  `auto`, `off`) in the checkout's git config, are read by
  `update_mode`/`contribute_mode`/`leaks_mode` in `sclaude/lib/core/developer.sh` and
  written by `install.sh` (`--update=`, `--contribute=`, `--leaks=`, its questions) and
  `update_mode_choose`; unset is `ask` on both sides. `tests/install.py`
  checks what the installer writes, `tests/sync.py` and `tests/workshop.py`
  what is read. A word changed on one side alone leaves a machine taking or
  sending what its person said not to, or asking at every start.

  <!-- Added by Claude on 2026-11-03 at the user's request: a newcomer's
  machine neither takes the public main nor sends to it unasked. -->

- The project settings `ship` (`ask`, `auto`, `off`), `previewRegression` and
  `prodRegression` (`full`, `smoke`, `none`) and `demo` (`on`, `off`, read by
  `project_demo_mode`, which `<if:demo>` in `sclaude/prompts/code.md` and
  `demo_refresh` in `demo.sh` follow) are listed in `CHOICES` in
  `sclaude/lib/core/config_menu.py`, explained in `sclaude/config.example.json`,
  read by `project_ship_mode`/`project_stage_regression` in
  `sclaude/lib/core/project.sh` and by `setting` in `sclaude/lib/flow/process_config.py`. The
  part name `smoke` is treated as `e2e` by `regression_command` and is what
  `sclaude/prompts/code.md` tells step 2 to tag for. `tests/project.py`,
  `tests/regression.py`, `tests/merge.py` and `tests/process.py` check each
  side. A word changed on one side alone ships what was set to be asked, or
  runs a suite the map says is gone.
  A choice set from `sclaude config` or the bot is this machine's, in
  `.sclaude/local/config.json` beside the committed file (`local_path`,
  `overrides` in `config_menu.py`), and is read first by `project_get`,
  `review_mode` in `pr_context.py`, `config_of` in `process_config.py` and
  `team_mode` in `dora_team.py`; `tests/config-menu.py` checks the writer
  and `project_get`. A reader that skips it acts on the project's
  recommendation while the screen shows the person's choice.

  <!-- Added by Claude on 2026-11-03 at the user's request, with the deploy
  settings. -->

- `sclaude new`'s options (`--issue`, `--blocked-ok`, `--create-issue`,
  `--no-issue`; `new_from_args` in `sclaude/lib/commands/start.sh`) and `sclaude config set` are
  what the bot's menu runs (`new_start` in `keepawake/webmenu.py`, `config_set`
  in `keepawake/project_config.py`); `tests/new-feature.py` and
  `tests/config-menu.py` check sclaude's side, `tests/webmenu.py` the bot's.

  <!-- Added by Claude on 2026-10-24 with the new-feature picker and the config
  in the Mini App: an option renamed on one side would start a feature that
  asks again, or dies, with nobody at the terminal. -->

## Public repository, private projects

This repository is public (personalautomation/SClaude). The projects sclaude
drives are not. So no session sclaude runs changes this checkout, and none
pushes it on its own (the workshop opened by hand, below, publishes on the
person's word): the live checkout is read-only to every one of them
(`sclaude_guard_args` in `sclaude/lib/core/steps.sh`, `sclaude/hooks/write-guard.py
--readonly`), and a push from it or from a worktree of it is refused
(`OWN_CHECKOUT` in `sclaude/hooks/forbidden-commands.py`). A step's
session that runs into something to fix in sclaude logs it in the friction
log; the retrospective and the friction and deferred reviews fix sclaude, in
the tree's workshop, a worktree of this checkout at
`.sclaude/local/instruments` (`sclaude/lib/improve/workshop.sh`):

- `sclaude core-open` lets such a session write there, without a question:
  they start in plan mode, so the approved plan is the yes; a step's session
  is refused it, and the refusal reaches the friction log too;

  <!-- Changed by Claude on 2026-10-29 at the user's decision: only the
  retrospective and the friction and deferred reviews change sclaude; a
  step's session logs what got in its way, and its friction review fixes
  it. Before, a step's session could open the workshop at the person's yes. -->
- it commits there and reviews its change — `/sreview` for a maintainer of
  sclaude (`MAINTAINERS`), whatever review they choose for anybody else — and
  runs `sclaude core-ready`;
- when the session ends, sclaude publishes it: a check for the product's
  details (`leaks` in `sclaude/lib/improve/workshop.py`), which asks the person on a
  hit, the tests the change touches, then `main` for a maintainer, squashed
  into one commit, or one pull request per tree for anybody else. A change
  left unfinished is not published, and its session is offered back.

The one session that publishes sclaude itself is the workshop the person
opens by hand — `sclaude workshop`, the bot's 🛠 button
(`sclaude/lib/improve/workbench.sh`): it works in a worktree of this checkout
beside it, with the live checkout read-only and without the hook that
refuses a push from a worktree of it (`OWN_CHECKOUT`), and its prompt
(`sclaude/prompts/workbench.md`) has it review the change and push it — or
open its pull request — only on the person's word. It is about no product,
so nothing a product's session saw is in it unless the person puts it there.

<!-- Added by Claude on 2026-11-05 at the user's request: a button that
opens a session to change sclaude, picked up over Remote Control. -->

Whoever commits here, by hand or from a workshop, still works from what they
saw in a product, so nothing committed here names a project's details: no
project names, no pull-request, issue or feature numbers, no file paths,
tables, services or infrastructure of a product. Describe a problem in the
orchestrator's own terms. What belongs to a project's story goes to that
project.

Data about projects that sclaude collects stays with the project: the
deferred friction and the session rules in the product's `.sclaude/`
(`sclaude/lib/improve/deferred.sh`, `sclaude/lib/improve/policy.py`), and terminal recordings
in its `.sclaude/local/`, which git and every Vercel upload are kept out of
(`sclaude/lib/core/scratch.sh`).

## Who commits the orchestrator to main

`MAINTAINERS` lists the git addresses allowed to commit sclaude's core straight
to `main`. Everybody else proposes a change on `dev/<name>` (the name comes
from `developer_name` in `sclaude/lib/core/developer.sh`), which reaches `main`
through a pull request. The same holds for what a session made in a workshop:
sclaude sends a maintainer's to `main` and anybody else's as a pull request
from the workshop's own `dev/<name>-<time>` branch.

With `MAINTAINERS` absent everybody is a maintainer, which is what a copy used
by one person wants.

## Commit messages

English, like everything else in this repository — the rule above has no
exception for commit messages. Conventional Commits subject, a body explaining
*why*, and an unbroken trailer block at the end. `githooks/commit-msg` refuses
a message whose trailer block is broken.

## Where things live in sclaude/lib

`sclaude/lib` keeps its modules in folders by what they do — `core`,
`cycle`, `commands`, `review`, `github`, `ship`, `tree`, `improve`,
`metrics`, `flow` (`docs/sclaude.md` says what each holds). Shell and Python
for one job sit side by side. A new module goes into the folder of its job;
bin/sclaude sources a shell module by `<folder>/<name>`, and a Python module
that imports another starts with the two lines every entry point has:

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # every folder of sclaude/lib on the path
```

Names stay unique across the folders and clear of the standard library's;
`tests/paths.py` checks it.

## Tests

`python3 tests/<name>.py` — each file is standalone and exits non-zero on
failure. `tests/run` runs several side by side, the longest first (the times
of the last run are kept in the git directory), with stdin closed, and prints
the output of the ones that fail.

Before a commit, run the tests that touch what changed: every test file that
names a changed file (a test sources or runs the modules it guards by name).
A commit does not need the whole suite:

```bash
tests/run --changed
```

Run them all before a push, which is what reaches every machine (auto-sync
from `main`) — about two minutes in parallel, twelve one after another:

```bash
tests/run
```

The benches build their own temporary worlds and share nothing, which is what
lets them run together; a new one keeps to that — no fixed port it listens on,
no fixed path outside its own temporary directory.

**A test that is red without your change is still yours to fix when the
session that broke it is gone.** Red alone on the base or in the live
checkout, or red only when the suite runs in parallel, counts. First find
whose it is: the test's `git log` (the `Claude-Session:` trailer), the
sessions running now (`ListAgents`) and the features sclaude has in work.
One still running gets the failure and its output with `SendMessage`, and
you agree who fixes it. Nobody left to ask: fix it yourself, in a commit of
its own, and say so in the report. "Not mine" without that look leaves the
suite red for every session after you.

<!-- Added by Claude on 2026-11-03 at the user's word, after two tests red
only under the parallel run were passed over as nobody's. -->

## The README, the wiki and the guides before a push

Before every push, bring the user documentation up to date with what the push
carries: a new command, key, switch or behaviour a user meets goes in, and one
that changed or went away is corrected there. Read the commits being pushed
(`git log origin/main..HEAD`) against it, and commit the update in the same
push. A push with nothing a user would notice needs no edit, but the check is
still made.

The user documentation is in two layers. `README.md` is the front page: what
sclaude solves and why a team would adopt it, the decks, the process map and
the video, who it fits, a four-line start, and the table of the guides. It
names nothing technical beyond that — no command reference, no settings, no
paths. How to use the tools is in the guides it lists: `docs/setup.md`
(environment, installation), `docs/sclaude-guide.md` (the commands, a feature
start to finish), `docs/cycle.md` (gates, refusals, rollback, metrics, the
decisions a product hands to sclaude), `docs/team.md`, `docs/privacy.md`,
`docs/tools.md` (the skills and the other tools) and
`docs/presentations/README.md`. A change a user meets goes into the guide that
describes it; the README changes when what sclaude offers changes — every new
feature of the tools does (below) — and then so does `docs/index.html` — the landing page GitHub Pages serves from
`docs/` on `main`, which tells the same story with the decks' material. How a
part works inside and why goes to `docs/sclaude.md` or `docs/keepawake.md`,
which are updated the same way when the push changes something they describe.

<!-- Changed by Claude on 2026-11-06 at the user's request: the README became
a front page that draws people in, and everything technical moved to the
guides under docs/. -->

The GitHub wiki is built from the same material: `wiki/pages/` holds its
front page, its concept pages and its sidebar, written by hand and kept in step
with the README the same way, and `python3 wiki/build.py <clone of
SClaude.wiki.git>` turns every guide and `docs/sclaude.md`/`docs/keepawake.md`
into its detailed pages. A heading renamed in `docs/` renames a wiki page;
`tests/wiki.py` fails on a link of `wiki/pages/` left pointing at the old
name.

**A significant new feature of the tools updates the README and the wiki** —
one that changes what sclaude offers a team, not every `feat`: it is not done
until the README names what it gives and the wiki's concept page it belongs
to in `wiki/pages/` carries it (a page of its own, linked from Home and
`_Sidebar.md`, when it is a story of its own). A maintainer who pushes `main`
then rebuilds the wiki into its clone and pushes it; nobody else can push the
wiki.

<!-- Added by Claude on 2026-11-09 at the user's request: a significant new
feature of the tools updates the README and the wiki, not only the guides. -->

The process map is read the same way. A change to the cycle's path — a way
back, a hold, a gate's outcomes, a question asked, where a feature stands and
what the menu calls it, what happens to the issue — is checked against the
whole model in `sclaude/lib/flow/process.py` and its parts: every map's nodes, edges and
details, `POSITIONS`, the commands' places and `WHEN`, and `position`; the
map is corrected in the same push. A block, an arrow or a word that only
some configs run goes in `NEEDS`, `PASS` and `VARIANTS`, not into every
project's map. `tests/process.py` checks that the model
agrees with the code's names — commands, steps, the places `position` answers
— and that the built page is current, not what the map says: a block drawn in
the wrong place, or a way out never drawn, passes it.

A review of a change here — `/sreview`, or whatever review is used — reads
the README, the guides, the docs and the process map against the change as part of it: a
place they no longer describe the code is a finding.

<!-- Both paragraphs above were added by Claude on 2026-10-29 at the user's
request ("if nothing in the instructions would update the process map, add
it"): the map drew the production hold between the review and the merge
check, with no way out, and no test or review could see it. -->

Shell files have no test runner of their own; check them with `bash -n`.
`tests/lint.py` runs ruff's pyflakes rules over the Python and shellcheck's
errors over the shell (both through `uvx`, skipped when it has not fetched
them); `tests/run --changed` takes it on any change.
`tests/coverage` runs benches with every bash traced and says how much of
each long shell function they ran (`--show <function>` for the lines that
never did) — the first look before rewriting one.

## Editing shell scripts while they run

`bin/sclaude` and `bin/keepawake` are edited by sessions that are themselves
running them. bash reads a script lazily, by offset into an open descriptor, so
an in-place edit shifts everything the process has not read yet. Both files wrap
their bodies in `{ … }` so bash must parse to the closing brace before executing
anything, and end the block with `exit` so bash never reads past it — after
`}` it would resume at the old offset, now mid-line in a grown file. Keep both.

The same hazard is why `sclaude`'s body lives in `sclaude/lib/*/*.sh`: a module is
read whole at `source` time and is safe to edit afterwards.

## A trap when writing Python inside shell

Heredocs and `python3 -c '...'` blocks are single-quoted. An apostrophe in a
comment inside one closes the string literal and breaks the script. Write "the
menu's item" as "the item in the menu", or use a `<<'PY'` heredoc.
