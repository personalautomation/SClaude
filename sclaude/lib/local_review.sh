#!/usr/bin/env bash
#
# The review of a pull request when the project does not want it in Actions:
# `review` in .sclaude/config.json (project_review_mode).
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# The review workflow runs on a GitHub runner, and the runner is billed by the
# minute for the whole time it waits on the model, on top of the tokens. A
# private repository on the free plan has 2000 such minutes a month, and two
# weeks of reviews spent them. So a project can say where its review runs:
#
#   github  the workflow, as before; nothing here applies.
#   local   sclaude runs the same /code-review on this machine, headless, on
#           the head step 4 opens on and again on each head a review session
#           leaves, and posts its findings as threads on the pull request,
#           as the workflow does (local_review.py). Tokens only, no runner
#           minutes.
#   off     no review at all; step 4 answers only the checks and what people
#           wrote.
#
# Both of the last two put the `no-review` label on the pull request, the
# workflow's own switch: its jobs are then skipped by their condition, and a
# skipped job costs no minutes. The label is asked for at step 3 (pr.md) so the
# pull request is opened with it, and put on again here at step 4 for one
# opened before.

# How the headless review runs. The workflow's own choice: Opus at `medium`.
LOCAL_REVIEW_MODEL="${LOCAL_REVIEW_MODEL:-opus}"
LOCAL_REVIEW_LEVEL="${LOCAL_REVIEW_LEVEL:-medium}"
# A pass that posts this many new findings or more has likely stopped at the
# review's own cap with more left unsaid, so the same range is read again,
# told what was just posted, for the next batch — what the workflow does by
# leaving a capped run's commit unmarked. At most LOCAL_REVIEW_PASSES passes
# a head, so a review that keeps finding cannot hold the step for ever.
LOCAL_REVIEW_CAP="${LOCAL_REVIEW_CAP:-10}"
LOCAL_REVIEW_PASSES="${LOCAL_REVIEW_PASSES:-5}"

# The local review's own files, beside the feature's other scratch. The
# findings are not among them: they are threads on the pull request.
#
#   local-review-rounds.jsonl   one line per run: when, how long, the range,
#                               how many posted and resolved — the rounds the
#                               report counts, and the head last reviewed
#   local-review-unposted.json  findings GitHub would not take yet, posted on
#                               the next call and counted open until then
#   local-review-answer.md      the last run's answer, as the model gave it
#   local-review.log            the last run's stderr
local_review_file() {
  echo "$1/.sclaude/local/feature/local-review$2"
}

# Put the `no-review` label on the pull request when the project's review is
# not GitHub's. Silent and best-effort: a label that could not be put on costs
# one review's minutes, not the step.
#
#   review_label_sync <wt> <pr>
review_label_sync() {
  local wt="$1" pr="$2" mode
  [[ -n "$pr" && "$pr" != "null" ]] || return 0
  mode="$(project_review_mode "$wt")"
  [[ "$mode" == "github" ]] && return 0
  command -v gh >/dev/null 2>&1 || return 0
  ( cd "$wt" || exit 0
    gh pr view "$pr" --json labels --jq '.labels[].name' 2>/dev/null | grep -qx no-review && exit 0
    gh label create no-review --color d4c5f9 \
      --description "Skip the automatic Claude code review on this pull request" >/dev/null 2>&1 || true
    if gh pr edit "$pr" --add-label no-review >/dev/null 2>&1; then
      info "  PR #$pr labelled no-review: this project's review is \`$mode\`, not GitHub's."
    fi
  ) || true
  return 0
}

# Switch the repository's own GitHub Actions workflows off for `review: local`,
# and back on for `github` — the ones this switched off, and no others.
#
#   review_actions_sync <repo root> <mode>
#
# `local` is for when the Actions minutes ran out, and with none left every
# workflow still starts on each push and fails at once — a red run and an
# email each time, about nothing in the code. A disabled workflow does not
# start. This is the repository's setting (`gh workflow disable`), not a
# change to the workflow files, which stay as the project keeps them. Only
# the ones in .github/workflows: what GitHub runs for itself (Dependabot) is
# not the project's to switch. Which ones were switched off is kept in the
# main tree's scratch, so `github` turns back on exactly those, not a
# workflow somebody disabled for a reason of their own. `off` changes
# nothing: no review is not no CI.
review_actions_sync() {
  local root="$1" mode="$2" list id name
  command -v gh >/dev/null 2>&1 || return 0
  list="$root/.sclaude/local/actions-disabled"
  case "$mode" in
    local)
      mkdir -p "$(dirname "$list")" 2>/dev/null || return 0
      while IFS=$'\t' read -r id name; do
        [[ -n "$id" ]] || continue
        if (cd "$root" && gh workflow disable "$id" >/dev/null 2>&1); then
          printf '%s\t%s\n' "$id" "$name" >> "$list"
          info "  GitHub Actions: \"$name\" switched off — it fails without minutes and mails about it."
        else
          warn "  GitHub Actions: could not switch \"$name\" off (gh workflow disable $id)."
        fi
      done < <(cd "$root" && gh api "repos/{owner}/{repo}/actions/workflows" --paginate \
                 --jq '.workflows[] | select(.state == "active" and (.path | startswith(".github/workflows/"))) | "\(.id)\t\(.name)"' 2>/dev/null)
      ;;
    github)
      [[ -s "$list" ]] || return 0
      while IFS=$'\t' read -r id name; do
        [[ -n "$id" ]] || continue
        if (cd "$root" && gh workflow enable "$id" >/dev/null 2>&1); then
          info "  GitHub Actions: \"$name\" switched back on."
        else
          warn "  GitHub Actions: could not switch \"$name\" back on (gh workflow enable $id)."
        fi
      done < "$list"
      rm -f "$list"
      ;;
  esac
  return 0
}

# Review the tree's HEAD on this machine, unless that head has been reviewed
# already; print how many review threads are open.
#
#   local_review <wt> <pr>   → <count> on stdout; 1 when the review did not run
#
# The first run reads the whole pull request (origin/main...HEAD); later runs
# read only the commits since the last head reviewed, as the workflow's review
# reads a push, and check at the new head every thread still open — resolving
# the ones the code no longer has. The count is of every open thread, old and
# new, less the ones the person keeps to resolve by hand: a session that fixed
# half of them and was interrupted finds the other half open on GitHub.
# Everything it says goes to stderr: stdout is the count.
local_review() {
  # What it told the topic it started, for the end when it leaves early:
  # GitHub not answering, an answer it could not record. A pass the person
  # stopped with [x x] still ends as finished, with what is open; Ctrl-C is
  # told by the pass's own trap.
  local -a LOCAL_REVIEW_TOLD=()
  local rc=0
  local_review_run "$@" || rc=$?
  trap - INT TERM HUP
  [[ "$rc" -eq 0 || ${#LOCAL_REVIEW_TOLD[@]} -eq 0 ]] \
    || ask_feed say "$(phase_line ended local-review "${LOCAL_REVIEW_TOLD[@]}") · it did not finish, see the terminal"
  return "$rc"
}

local_review_run() {
  local wt="$1" pr="$2" head last base scope out count answer repo
  local journal; journal="$(local_review_file "$wt" -rounds.jsonl)"
  head="$(git -C "$wt" rev-parse HEAD 2>/dev/null)" || return 1
  repo="$(REPO="$wt" gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || { warn "  No GitHub repository for $wt: the local review did not run." >&2; return 1; }
  # A thread is posted on a commit of the pull request: a head it does not
  # carry yet cannot take one.
  if ! local_review_pushed "$wt" "$pr"; then
    warn "  ${head:0:7} is not the head of PR #$pr: the local review posts on what the pull request carries. Push, then run $SELF again." >&2
    return 1
  fi
  if python3 "$LIB/local_review.py" cached "$journal" "$head" 2>/dev/null; then
    python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null || return 1
    return 0
  fi
  # From the last head reviewed — or, when this head was left with more to
  # read (a capped pass whose follow-up never ran), over the same range again.
  last="$(python3 "$LIB/local_review.py" since "$journal" "$head" 2>/dev/null || true)"
  if [[ -n "$last" && "$last" != "$head" ]] && git -C "$wt" merge-base --is-ancestor "$last" "$head" 2>/dev/null; then
    base="$last"
    scope="the commits since the last review: \`git diff $base..$head\`"
  else
    base="$(git -C "$wt" merge-base origin/main "$head" 2>/dev/null)" || return 1
    scope="the whole pull request: \`git diff $base..$head\`"
  fi

  # Once the person said the search is over (review_enough), a head is only
  # checked: which open findings its commits fixed, nothing new looked for.
  local verify=""
  [[ -n "$(review_enough "$wt")" ]] && verify=1
  command -v claude >/dev/null 2>&1 || { warn "  No claude on this machine: the local review did not run." >&2; return 1; }
  if [[ -n "$verify" ]]; then
    info "  Checking the fixes on PR #${pr:-?} ($LOCAL_REVIEW_MODEL): ${base:0:7}..${head:0:7}." >&2
    info "  You ended the search for new findings, so this only resolves the ones the commits fixed." >&2
  else
    info "  Reviewing PR #${pr:-?} on this machine ($LOCAL_REVIEW_MODEL, $LOCAL_REVIEW_LEVEL): ${base:0:7}..${head:0:7}." >&2
    info "  It takes minutes; Ctrl-C leaves, and the next \`$SELF\` starts it again." >&2
    if keys_usable; then
      info "  It needs nothing from you. To step in, press a key while it runs — no Enter, nothing shows:" >&2
      info "    [s]    this pass is the last that looks for new findings (s again takes it back)" >&2
      info "    [x x]  stop it now, dropping only what this pass found so far" >&2
      info "  Either way what is open goes to the review session, and sclaude asks you before it checks the fixes." >&2
    fi
  fi

  local earlier began new more cap pass=1 round
  round="$(python3 "$LIB/local_review.py" round "$journal" "$head" 2>/dev/null || echo 1)"
  answer="$(local_review_file "$wt" -answer.md)"
  # The lines above are indented, and the topic leaves those out: it hears
  # of the review by these two, here and at the end.
  ask_feed say "$(phase_line started local-review "${pr:-?}" "$round" $verify)"
  history_add "$wt/.sclaude/local/feature/state.json" review.local start
  # An array: a "?" for a missing PR, split from a string, globbed.
  LOCAL_REVIEW_TOLD=("${pr:-?}" "$round" $verify)
  # Ctrl-C between passes too — while a pass's answer is recorded, or the
  # report printed — ends what the topic heard start: exit leaves the subshell
  # local_review runs in before its wrapper could say it.
  local between='ask_feed say "$(phase_line ended local-review "${LOCAL_REVIEW_TOLD[@]}") · stopped"; exit 130'
  trap "$between" INT TERM HUP
  while :; do
    if ! earlier="$(python3 "$LIB/local_review.py" prompt "$wt" "$pr" "$repo" "$journal" 2>>"$(local_review_file "$wt" .log)")"; then
      warn "  GitHub did not say which findings are open: the local review did not run pass $pass." >&2
      [[ "$pass" -gt 1 ]] || return 1
      count="$(python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null)" || return 1
      break
    fi
    # Nothing open to check: no model to ask, the head is recorded as read.
    # The open findings are the block local_review.py prompt heads "still
    # open"; the rest of what it says (declined, fixed) is no work here.
    if [[ -n "$verify" && "$earlier" != *"still open"* ]]; then
      printf 'FINDINGS: 0\n' > "$answer"
      read -r count new more < <(python3 "$LIB/local_review.py" record "$wt" "$pr" "$repo" "$answer" \
                                   "$base" "$head" 0 "$journal" 0 verify 2>>"$(local_review_file "$wt" .log)") \
        || count="$(python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null)" || return 1
      break
    fi
    local text
    if [[ -n "$verify" ]]; then text="$(local_review_verify_prompt "$pr" "$head" "$scope" "$earlier")"
    else text="$(local_review_prompt "$pr" "$head" "$scope" "$earlier")"
    fi
    began=$SECONDS
    # In the background, so that the wait can take the keys above: a review
    # that goes round after round is where the person decides it is enough.
    # A background job of a script ignores Ctrl-C, so the trap passes it on.
    # Into a file of its own until it ends: a pass stopped half-way leaves
    # the last whole answer where it was.
    ( cd "$wt" && exec claude -p "$text" \
             --model "$LOCAL_REVIEW_MODEL" \
             --allowedTools "Read" "Grep" "Glob" "Skill" "Agent" \
               "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git blame:*)" \
             --disallowedTools "Edit" "Write" "NotebookEdit" "Bash(gh:*)" \
               "Bash(git push:*)" "Bash(git commit:*)" \
             >"$answer.part" 2>"$(local_review_file "$wt" .log)" </dev/null ) &
    local pid=$!
    # The end told here too, the pass stopped first.
    trap 'kill -TERM "$pid" 2>/dev/null; stty echo < /dev/tty 2>/dev/null; printf '"'"'\033[?25h'"'"' >&2; ask_feed say "$(phase_line ended local-review "${LOCAL_REVIEW_TOLD[@]}") · stopped"; exit 130' INT TERM HUP
    local stopped=0
    local_review_wait "$wt" "$pid" "$pass" "$began" "$verify" "$round" || stopped=1
    trap "$between" INT TERM HUP
    if [[ "$stopped" -eq 1 ]]; then
      rm -f "$answer.part"
      warn "  Stopped pass $pass as you said; what earlier passes and rounds posted stays open on PR #$pr" >&2
      warn "  and goes to the review session." >&2
      count="$(python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null)" || return 1
      break
    fi
    mv -f "$answer.part" "$answer"
    # The last pass allowed records no "more": the head is done with what it
    # has, rather than read again on every later call.
    cap="$LOCAL_REVIEW_CAP"; [[ "$pass" -ge "$LOCAL_REVIEW_PASSES" || -n "$verify" ]] && cap=0
    if ! read -r count new more < <(python3 "$LIB/local_review.py" record "$wt" "$pr" "$repo" "$answer" \
                                      "$base" "$head" "$((SECONDS - began))" "$journal" "$cap" ${verify:+verify} \
                                      2>>"$(local_review_file "$wt" .log)") || [[ -z "${count:-}" ]]; then
      # A later pass that fails leaves the earlier ones recorded: the head
      # counts as reviewed with what they posted.
      if [[ "$pass" -gt 1 ]]; then
        warn "  Pass $pass of the local review was not recorded; the first $((pass - 1)) stand." >&2
        count="$(python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$journal" 2>/dev/null)" || return 1
        break
      fi
      warn "  The local review was not recorded: no findings count in its answer, or GitHub took none of them." >&2
      warn "  Its answer: $answer; the next \`$SELF\` reviews this head again." >&2
      return 1
    fi
    # By what the pass found, not what GitHub took: a capped pass with a
    # finding refused is still capped.
    if [[ "${more:-0}" == 1 && -n "$(review_enough "$wt")" ]]; then
      info "  That pass found the cap, but you ended the search: no pass $((pass + 1))." >&2
      break
    fi
    if [[ "${more:-0}" != 1 ]]; then
      [[ "$pass" -ge "$LOCAL_REVIEW_PASSES" && "$new" -ge "$LOCAL_REVIEW_CAP" ]] \
        && warn "  Pass $pass still found the cap; stopping at $LOCAL_REVIEW_PASSES passes — more may be left unsaid." >&2
      break
    fi
    pass=$((pass + 1))
    # Where the review stands with that pass posted, before the next one
    # reads on: to stderr, stdout being the count, and not to the topic,
    # which hears of the review once it ends.
    declare -F review_report >/dev/null \
      && REVIEW_REPORT_QUIET=1 review_report "$wt" "${ASK_SLUG:-}" >&2
    info "  That pass found the cap ($LOCAL_REVIEW_CAP): reading ${base:0:7}..${head:0:7} again for the rest, pass $pass." >&2
  done
  if [[ "$count" -eq 0 ]]; then
    info "  The local review leaves nothing open on PR #$pr." >&2
  else
    info "  The local review leaves $count thread(s) open on PR #$pr." >&2
  fi
  ask_feed say "$(phase_line finished local-review "${pr:-?}" "$round" $verify) · $count open"
  history_add "$wt/.sclaude/local/feature/state.json" review.local end open="$count"
  echo "$count"
}

# Wait for a pass of the local review, taking the person's keys meanwhile.
#
#   local_review_wait <wt> <pid> <pass> <began> [verify] [round]
#
# The keys end the search for new findings (review_enough): `s` lets this
# pass finish and be posted, and it is the last to look; pressed again it
# takes that back. `x` stops the pass now — what it had found is not posted,
# since a finding exists only in the answer the pass ends with — and so wants
# pressing twice. Either way what is open goes to the review session. Nothing
# here asks Telegram: a question every round would be noise on the phone —
# the topic's message that the pass started carries the same two as buttons
# instead (review_said_take), and a press is taken here as a key is. Without
# a terminal it is a wait for those. Everything goes to stderr: local_review answers on stdout.
# A check of the fixes (verify) takes no keys: the search is over already.
# Returns 1 when the person stopped the pass.
local_review_wait() {
  local wt="$1" pid="$2" pass="$3" began="$4" verify="${5:-}" round="${6:-1}" armed=0 armed_at=0 said hint t tty="" which said_file
  # The round counts heads reviewed; a pass is another read of this head,
  # after one that found the cap, so the first pass goes unsaid.
  which="round $round"; [[ "$pass" -gt 1 ]] && which+=", pass $pass"
  said="$(review_enough "$wt")"
  said_file="$(review_said_file)" || said_file=""
  # No echo while it waits: a key pressed between two reads would otherwise
  # land on the status line. No cursor either: blinking after the last key in
  # the hint, it read as that option being picked, or as a field to type in.
  if keys_usable; then
    tty=1
    stty -echo < /dev/tty 2>/dev/null
    printf '\033[?25l' >&2
  fi
  while kill -0 "$pid" 2>/dev/null; do
    # `x` once only arms the stop, for five seconds or until another key.
    [[ "$armed" -eq 1 && $((SECONDS - armed_at)) -ge 5 ]] && armed=0
    if [[ -n "$tty" ]]; then
      t=$((SECONDS - began))
      if [[ -n "$verify" ]]; then
        hint="checking the fixes only"
      elif [[ "$armed" -eq 1 ]]; then
        hint="press ${BOLD}[x]${OFF} again: stop now and drop this pass · any other key: carry on"
      elif [[ "$said" == pass ]]; then
        hint="the last pass for new findings · ${BOLD}[s]${OFF} takes it back · ${BOLD}[x x]${OFF} stop now"
      else
        hint="only if you want to step in: ${BOLD}[s]${OFF} last pass for new findings · ${BOLD}[x x]${OFF} stop now"
      fi
      # Not "Human in the loop", as the waits that need the person say: this
      # one goes on by itself, and the keys are there only to step in.
      printf '\r\033[2K  %sRunning by itself%s — local review, %s (%dm%02ds) · %s' \
        "$DIM" "$OFF" "$which" $((t / 60)) $((t % 60)) "$hint" >&2
    fi
    poll_pause 1
    # A press in the topic: as the keys, with no second press to wait for —
    # the phone asked for it already. A key pressed here in the same second
    # is still taken after it — the first x of a stop, say. Not an `s`: it
    # turns the last pass over, and would undo the word the phone just gave.
    if [[ -z "$verify" && -n "$said_file" && -f "$said_file" ]]; then
      case "$(review_said_take "$wt" wait)" in
        now)  POLL_KEY=x; armed=1 ;;
        pass) said=pass; [[ "$POLL_KEY" == [sS] ]] && POLL_KEY="" ;;
        back) said=""; [[ "$POLL_KEY" == [sS] ]] && POLL_KEY="" ;;
      esac
    fi
    [[ -n "$POLL_KEY" && -z "$verify" ]] || continue
    case "$POLL_KEY" in
      x|X)
        if [[ "$armed" -eq 1 ]]; then
          review_enough_set "$wt" now
          kill -TERM "$pid" 2>/dev/null
          wait "$pid" 2>/dev/null
          [[ -n "$tty" ]] && { printf '\r\033[2K\033[?25h' >&2; stty echo < /dev/tty 2>/dev/null; }
          return 1
        fi
        armed=1; armed_at=$SECONDS; continue ;;
      s|S)
        if [[ "$said" == pass ]]; then said=""; else said=pass; fi
        review_enough_set "$wt" "$said" ;;
    esac
    armed=0
  done
  wait "$pid" 2>/dev/null
  [[ -n "$tty" ]] && { printf '\r\033[2K\033[?25h' >&2; stty echo < /dev/tty 2>/dev/null; }
  return 0
}

# The person's word that the review has found enough: the search for new
# findings is over. What is open still goes to a review session — those
# findings are paid for — but no review starts by itself after it: the gate
# asks the person whether to check the session's fixes, and that check only
# judges the open findings (local_review_verify_prompt), so the rounds end
# instead of finding something new each time. Kept in the feature's state
# until step 4 closes (after_step) or is rewound or closed by a merge, so a
# Ctrl-C or a session in between does not forget it.
#
#   pass  said with `s`: the pass running when it was said was the last;
#   now   said with `x x`: that pass was stopped. Otherwise the same.
#
review_enough() {
  local said
  review_said_take "$1" >/dev/null
  said="$(state_get "$1/.sclaude/local/feature/state.json" steps.review.enough 2>/dev/null || true)"
  [[ "$said" == pass || "$said" == now ]] && echo "$said"
  return 0
}

review_enough_set() {
  state_set "$1/.sclaude/local/feature/state.json" steps.review.enough "${2:-null}" 2>/dev/null || true
}

# The same word said from the phone: the buttons the bot puts on the topic's
# message that a review pass or a fix session started (keepawake/review_keys.py)
# write it into the feature's channel, and it is taken from there here.
#
#   pass  the last pass, or round, for new findings — the terminal's [s];
#   back  taken back — [s] again;
#   now   stop the running pass — [x x]. Taken outside a pass's wait (a press
#         that came as the pass ended) it is a pass: there is nothing to stop.
#
#   review_said_take <wt> [wait]   → the word taken, "" for none
#
# With `wait`, the caller is a pass's wait and does the stopping: the word is
# kept as it was said.
REVIEW_SAID_FILE=review-said

review_said_file() {
  # As ask_channel: a plain slug, and not a feature whose clean-up has ended.
  [[ -n "${ASK_DIR:-}" && "${ASK_SLUG:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ \
     && "$ASK_SLUG" != "${ASK_ENDED:-}" ]] || return 1
  echo "$ASK_DIR/ask/$ASK_SLUG/$REVIEW_SAID_FILE"
}

# A press nobody took goes with the "enough" it would have set: wherever that
# is cleared — step 4 closed, the cycle sent back — a word left in the file
# would be taken by the next review, about a round it was not said in.
review_said_drop() {
  local file
  file="$(review_said_file)" && rm -f "$file"
  return 0
}

review_said_take() {
  local file word
  file="$(review_said_file)" && [[ -f "$file" ]] || return 0
  # Renamed before it is read: a press that lands meanwhile writes a file
  # of its own, taken next time, rather than one removed unread.
  mv -f "$file" "$file.$$" 2>/dev/null || return 0
  word="$(head -c 16 "$file.$$" 2>/dev/null)"
  rm -f "$file.$$"
  case "$word" in
    pass) review_enough_set "$1" pass ;;
    now)  if [[ "${2:-}" == wait ]]; then review_enough_set "$1" now; else review_enough_set "$1" pass; word=pass; fi ;;
    back) review_enough_set "$1" "" ;;
    *)    return 0 ;;
  esac
  echo "$word"
}

# How many review threads are open on the pull request, read from it: no
# pass runs.
#
#   local_review_count <wt> <pr>   → <count>; 1 when GitHub cannot be read
local_review_count() {
  local wt="$1" pr="$2" repo
  repo="$(REPO="$wt" gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || return 1
  python3 "$LIB/local_review.py" open "$wt" "$pr" "$repo" "$(local_review_file "$wt" -rounds.jsonl)" 2>/dev/null
}

# Whether the tree's HEAD has had its local review already: a call to
# local_review would then run nothing.
local_review_done() {
  local head
  head="$(git -C "$1" rev-parse HEAD 2>/dev/null)" || return 1
  python3 "$LIB/local_review.py" cached "$(local_review_file "$1" -rounds.jsonl)" "$head" 2>/dev/null
}

# What the headless check is told once the search for new findings is over:
# only the open findings, against the commits since the last review — no
# /code-review, so a round of fixes costs a read of its diff, not a review.
#
#   local_review_verify_prompt <pr> <head> <scope> <earlier>
local_review_verify_prompt() {
  local pr="$1" head="$2" scope="$3" earlier="$4"
  cat <<TEXT
You are checking fixes on pull request #${pr:-?} unattended, on the developer's machine. Nobody will answer a question and nothing will wake you: when you end your turn the run is over.

The search for new findings on this pull request is over. Do not review the code for anything else, and do not invoke the \`code-review\` skill. Your one job: read $scope (the tree is checked out at $head), then judge each finding below against the code as it is here.

$earlier

Post nothing to GitHub and change no file: sclaude resolves the threads from your answer. Answer with nothing else: a \`RESOLVED: <id> — <how, in a sentence>\` line for each finding the code no longer has, and last a line of its own, \`FINDINGS: 0\`.
TEXT
}

# What the headless review is told. The scope sentence follows the workflow's
# own, so that a local review reads what an Actions one would; what it is told
# about earlier findings is read from the pull request (local_review.py prompt).
#
#   local_review_prompt <pr> <head> <scope> <earlier>
local_review_prompt() {
  local pr="$1" head="$2" scope="$3" earlier="$4"
  cat <<TEXT
You are reviewing pull request #${pr:-?} unattended, on the developer's machine. Nobody will answer a question and nothing will wake you: when you end your turn the run is over, so collect every agent's result within this turn.

Invoke the \`code-review\` skill with the Skill tool, with these arguments on one line:

    $LOCAL_REVIEW_LEVEL <scope>

where <scope> is plain words saying: review $scope; review every changed file in it, none left out as unimportant, generated files may be skimmed; the tree is checked out at $head, so read the code as it is here; do not run the app, or any build or test.${earlier:+ Add to the scope, verbatim, what follows about earlier findings.}
TEXT
  [[ -n "$earlier" ]] && printf '\n%s\n' "$earlier"
  cat <<TEXT

Post nothing to GitHub and change no file: sclaude posts your findings from your answer.

When the skill is done, answer with nothing else. First the new findings, one per section:

### <path>:<line> — <the finding in one line>
<the failure scenario: concrete inputs or state, and the wrong result>

then a \`RESOLVED: <id> — <how, in a sentence>\` line for each earlier open finding the code no longer has, and last a line of its own, \`FINDINGS: <n>\`, the number of new findings above — \`FINDINGS: 0\` when there are none.
TEXT
}

# One more round handed to a resumed review session, for its row in the
# issue: the threads it was given are counted by run_comments, as on GitHub;
# the rounds are the reviews it worked through, the first counted when it
# opened (run_rounds), one more for each local review that brought it back.
#
#   run_local_round <wt> <session>
run_local_round() {
  local wt="$1" session="$2"
  [[ -n "$session" ]] || return 0
  python3 - "$wt/.sclaude/local/feature/state.json" "$session" <<'PY' 2>/dev/null || true
import json, sys
path, session = sys.argv[1:3]
with open(path) as fh:
    data = json.load(fh)
runs = ((data.get("steps") or {}).get("review") or {}).get("runs") or []
mine = [r for r in runs if isinstance(r, dict) and r.get("session") == session]
if not mine:
    sys.exit(0)
run = mine[-1]
run["rounds"] = (run.get("rounds") if isinstance(run.get("rounds"), int) else 0) + 1
with open(path, "w") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

# Whether the tree's HEAD is the head of the pull request: what a thread can
# be posted on. Asked of GitHub rather than of the upstream, which a branch
# made from origin/main keeps pointing at until somebody pushes with -u.
#
#   local_review_pushed <wt> <pr>
local_review_pushed() {
  local wt="$1" pr="$2" remote
  remote="$(cd "$wt" && gh pr view "$pr" --json headRefOid --jq .headRefOid 2>/dev/null)" || return 1
  [[ -n "$remote" && "$remote" == "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" ]]
}

# The head the last local review covered, or nothing.
local_review_head() {
  python3 "$LIB/local_review.py" base "$(local_review_file "$1" -rounds.jsonl)" 2>/dev/null || true
}
