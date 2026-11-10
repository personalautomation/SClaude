#!/usr/bin/env bash
#
# The feature's demo, recorded again once the preview's regression is green:
# what changed, what is held and published, and the session that plays it.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The demo, recorded again after step 2 — only when the product's code changed
# since the last full one (`demo.py stale`); a demo costs minutes and a
# model's work. Step 2's is for the person accepting the work; this one is for
# whoever looks next:
#   preview   once the preview's regression is green, before the issue goes
#             to QA — where QA moves it on the board (qa: github, both): a
#             delta, only what changed for the user since the last full demo,
#             then the whole feature again;
#   epilogue  before the last epilogue, where nobody does QA (qa: auto): the
#             whole feature, for the issue's record, and no delta.
# The review may have changed what the feature does, not only how, so a
# model writes it again: a headless session with the sdemo skill, given the
# last full demo's script and what changed since. Nobody watches it, so it
# writes nowhere but the feature's demo directory: dontAsk refuses whatever
# the list does not name — the person's own permission mode would let it
# edit the tree it runs in — and an Edit rule on an absolute path (`//…`)
# covers every file-writing tool. Not the product's code, not sclaude's
# checkout, which every session sclaude runs may only read. Without claude, the old
# script is played as it is (`demo.py replay`). A feature that never had a
# demo gets none here. Breaks nothing: the pass goes on.
#
#   demo_refresh <wt> <preview|epilogue>
demo_refresh() {
  local wt="$1" stage="$2" tool="$INSTRUMENTS/skills/sdemo/demo.py" verdict head script log findings before kept
  [[ -f "$tool" ]] || return 0
  # A project that makes no demo videos (`demo: off`) has none to refresh.
  [[ "$(project_demo_mode "$wt")" == on ]] || return 0
  verdict="$(cd "$wt" && python3 "$tool" stale 2>/dev/null)" || return 0
  [[ "$verdict" == stale:* ]] || return 0
  head="$(cd "$wt" && python3 "$tool" last 2>/dev/null | sed -n 's/^head: //p')"
  script="$(cd "$wt" && python3 "$tool" last 2>/dev/null | sed -n 's/^script: //p')"
  log="$wt/.sclaude/local/demo/refresh.log"
  findings="$wt/.sclaude/local/demo/findings.md"
  echo ""
  # The headline in bold, the details under it grey: all grey, the one line
  # that says what is happening read like the file list beside it.
  if [[ "$stage" == preview ]]; then
    say "🎬 ${BOLD}The code changed since the feature's demo — recording what changed, and the whole of it, for QA.${OFF}"
  else
    say "🎬 ${BOLD}The code changed since the feature's demo — recording it again for the issue.${OFF}"
  fi
  info "  ${verdict#stale: }"
  # What the session finds wrong in the product while it records is written
  # there, and said below: its log goes with the tree, and a fault only the
  # log knows is one nobody hears of.
  : >"$findings" 2>/dev/null || true
  before="$(demo_history_count "$wt")"
  # As a step's session would: the links and the videos go to the feature's
  # topic and the issue's demo comment is replaced (demo.py publishes only
  # for sclaude), at this stage of the history. Held while the session plays
  # (SCLAUDE_DEMO_HOLD): it may play a script several times before it is
  # right, and without the hold each try would go out as it was recorded.
  # Its last delta and its last full recording are published after it, or
  # nothing when it ended on `demo.py keep` (demo_publish_held).
  if command -v claude >/dev/null 2>&1 && [[ -f "$script" && -n "$head" ]]; then
    info "  A session writes it again from the last one (sdemo skill); its log: $log"
    # A conversation like every other one sclaude starts, so it is named in
    # the state's `demo` runs and gets its row in the issue's sessions table
    # (issue_sync.sh); without the id it ran unseen there.
    local state="$wt/.sclaude/local/feature/state.json" session rc=0
    session="$(new_session_id)"
    [[ -f "$state" ]] && SCLAUDE_ABOUT="$stage" session_runs "$state" demo open "$session"
    # The feature's environment, as every session sclaude starts in a tree
    # gets it (dev_env_load): without it a script that reaches the feature's
    # own database directly had no address for it.
    # Its events as a stream, read by demo_progress.py: what it is at, and
    # which scenario of which recording plays, said as it goes — headless,
    # it ran for up to forty minutes with nothing on the screen.
    : >"$log"
    ( cd "$wt" && dev_env_load "$wt" && SCLAUDE_SESSION="${SCLAUDE_SESSION:-sclaude}" SCLAUDE_DEMO_STAGE="$stage" \
        SCLAUDE_DEMO_HOLD=1 timeout "$DEMO_REFRESH_LIMIT" \
        claude -p "$(demo_refresh_prompt "$wt" "$script" "$head" "$stage")" \
        --session-id "$session" --output-format stream-json --verbose \
        --model "$(step_model code)" --permission-mode dontAsk \
        --allowedTools "Read" "Grep" "Glob" "Skill" "Edit(/$wt/.sclaude/local/demo/**)" \
          "Bash(python3 $tool:*)" "Bash(python3 ~/.claude/skills/sdemo/demo.py:*)" \
          "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" \
        --disallowedTools "NotebookEdit" "Bash(gh:*)" "Bash(git push:*)" "Bash(git commit:*)" \
        2>&1 </dev/null ) | demo_progress "$wt" "$log"
    rc="${PIPESTATUS[0]}"
    if [[ -f "$state" ]]; then
      # Whether a conversation took place, by its transcript, as for the
      # epilogue: a claude that died at the door leaves no session to name.
      if ! session_started "$wt" "$session"; then
        session_runs "$state" demo drop "$session"
      elif (( rc == 0 )); then
        SCLAUDE_ABOUT="$stage" session_runs "$state" demo finish "$session"
      else
        SCLAUDE_ABOUT="$stage" session_runs "$state" demo end "$session" "exit $rc"
      fi
      # Its row goes into the issue now. Before QA the next rewrite of the
      # table may be a long way off; at the epilogue run_status follows, but
      # skips the table when the status already describes the head
      # (status_fingerprint knows nothing of the demo). Written twice there
      # at worst.
      declare -F issue_sync >/dev/null && issue_sync "$wt"
    fi
    say "🎬 ${BOLD}Publishing${OFF} the recordings"
    demo_publish_held "$wt" "$stage" "$tool" "$before" >>"$log" 2>&1
  else
    : >"$log"
    ( cd "$wt" && dev_env_load "$wt" && SCLAUDE_SESSION="${SCLAUDE_SESSION:-sclaude}" SCLAUDE_DEMO_STAGE="$stage" \
        python3 "$tool" replay </dev/null 2>&1 ) | demo_progress "$wt" "$log"
  fi
  demo_findings "$wt" "$findings" "$before"
  if [[ "$(cd "$wt" && python3 "$tool" stale 2>/dev/null)" == fresh:* ]]; then
    kept="$(demo_kept "$wt" "$before")"
    if [[ -n "$kept" ]]; then
      info "  Not recorded again: $kept"
    else
      info "  Recorded again; the feature's demo page and the issue's demo comment show it."
    fi
  else
    warn "  the demo was not recorded again ($log); the issue keeps the earlier one"
  fi
  return 0
}

# How long a refresh session may run, and so what its status line counts to.
DEMO_REFRESH_LIMIT=2400

# What a refresh is doing, said as it goes: demo_progress.py reads the
# session's events (or replay's output) on stdin and the recording's place
# in the feature's state (`demo_progress`, kept by demo.py play), redraws a
# status line, and prints a line for each change — `<level>\t<verb>\t<rest>`
# — which goes out here in bold, to the terminal and the feature's topic.
#
#   … | demo_progress <wt> <log>
demo_progress() {
  local level verb rest
  python3 "$INSTRUMENTS/sclaude/lib/ship/demo_progress.py" watch "$1" "$2" "$DEMO_REFRESH_LIMIT" \
    | while IFS=$'\t' read -r level verb rest; do
        [[ -n "$verb" ]] || continue
        # The status line off first, or the line lands after it.
        [[ -t 2 ]] && printf '\r\033[2K' >&2
        case "$level" in
          ok)   say "  ✅ ${BOLD}$verb${OFF} $rest" ;;
          warn) warn "  🎬 $verb $rest" ;;
          *)    say "  🎬 ${BOLD}$verb${OFF} $rest" ;;
        esac
      done
  return 0
}

# How many recordings the feature's demo history holds: what a refresh
# tells its own from.
#
#   demo_history_count <wt>
demo_history_count() {
  python3 "$INSTRUMENTS/sclaude/lib/ship/demo_refresh.py" count "$1"
}

# The recordings a refresh held back, published once it is over: the last
# delta it made, then the last full demo — each once, and only one that
# played. What the session tried before those stays held: in the history,
# on no page and in no message. A session that ended on `demo.py keep`
# publishes nothing.
#
#   demo_publish_held <wt> <stage> <tool> <count before>
demo_publish_held() {
  local wt="$1" stage="$2" tool="$3" before="$4" id ids
  ids="$(python3 "$INSTRUMENTS/sclaude/lib/ship/demo_refresh.py" held "$wt" "$before")"
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    ( cd "$wt" && SCLAUDE_SESSION="${SCLAUDE_SESSION:-sclaude}" SCLAUDE_DEMO_STAGE="$stage" \
        python3 "$tool" publish "$id" </dev/null )
  done <<<"$ids"
}

# What a refresh found wrong in the product, said in the terminal: the
# lines its session wrote, and the checks that did not see what they looked
# for in its last delta and its last full recording — published, or held
# after `demo.py keep`.
#
#   demo_findings <wt> <findings file> <count before>
demo_findings() {
  local said line
  said="$(python3 "$INSTRUMENTS/sclaude/lib/ship/demo_refresh.py" findings "$1" "$2" "$3")"
  [[ -n "$said" ]] || return 0
  warn "  The demo found something wrong in the product:"
  while IFS= read -r line; do warn "    - $line"; done <<<"$said"
}

# Why a refresh recorded nothing, when its session kept the last demo
# (`demo.py keep`); empty otherwise.
#
#   demo_kept <wt> <count before>
demo_kept() {
  python3 "$INSTRUMENTS/sclaude/lib/ship/demo_refresh.py" kept "$1" "$2"
}

# What that session is told: the skill does the work; this says where to
# start from, what to record at this stage, and that nobody is there to ask.
demo_refresh_prompt() {
  local wt="$1" script="$2" head="$3" stage="$4" what
  if [[ "$stage" == preview ]]; then
    what="Record two things, in this order, for QA: first a delta (/sdemo delta) — only what changed for the user since that demo, none if nothing did — then the whole feature again (/sdemo)."
  else
    what="Record the whole feature again (/sdemo), for the issue's record; no delta."
  fi
  cat <<EOF
Use the sdemo skill for the feature in this tree. Nobody is at the terminal: decide by yourself, ask nothing.

The last full demo was recorded on commit ${head:0:7}, from the script $script. The code has changed since — the review may have changed what the feature does, not only how. Read what changed (git diff $head, git log $head..HEAD) and the old script.

First decide whether any of it changes what a user sees or does, as the skill's delta step asks. If none does — every scenario of that script still shows the feature as it is, and nothing a user meets was added or taken away — record nothing: run python3 $INSTRUMENTS/skills/sdemo/demo.py keep "<why, in one line>" and stop there.

Otherwise start from that script: keep the scenarios that still show the feature as it is, rewrite the ones the change touched, add any the change added, and drop what no longer exists. Show the feature on a desktop and on a phone, as the skill says.

$what

Call demo.py by its full path, one command at a time and nothing chained to it — python3 $INSTRUMENTS/skills/sdemo/demo.py last, … play — since only that is allowed here. Check each recording's demo.json; fix a script that failed and play it again, twice at most. Nothing goes out while you play: once you end, sclaude publishes your last delta and your last full recording — or nothing, if you ended on keep.

Whatever you find wrong in the product itself while you record — a step that does not show what the feature promises, a scenario you had to take round a fault — write to $wt/.sclaude/local/demo/findings.md, one line each: what a user sees, and where. A fault you went round in the script and wrote down nowhere else is one nobody hears of.

End with one line: the feature's demo page, or why there is none.
EOF
}
