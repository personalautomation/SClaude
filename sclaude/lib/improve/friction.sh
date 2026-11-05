#!/usr/bin/env bash
#
# The friction review: a session that reads what got in the steps' way
# and proposes, then makes, the fix — in the product or in sclaude's workshop.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# The refusals Claude Code itself issued — into the friction log.
#
# The hook writes only its own: forbidden-commands.py calls note() from deny().
# But in auto mode a command is also judged by the built-in classifier, and its
# refusal is invisible to a hook — Claude Code has no "permission denied" event
# at all. Such a refusal stays only in the transcript, in the toolDenialKind
# field, and collect-denials.py takes it from there once the step has ended.
#
# The caller names the session rather than leaving it to be read from
# steps.<step>.session: a rotated review round has cleared that field by the
# time its review runs, and reading it gathered nothing — the classifier's
# refusals in every round but the last were never collected. The directory is
# the worktree's path with everything but letters and digits replaced by a
# hyphen; the same method as in capture_plan and in run_friction below.
collect_denials() {
  local wt="$1" step="$2" session="${3:-}"
  local transcript

  [[ -n "$session" ]] || return 0

  transcript="$(session_transcript "$wt" "$session")"
  [[ -f "$transcript" ]] || return 0

  # CLAUDE_PROJECT_DIR is the same thing the hook finds the log by: the feature
  # worktree's root. The silence on an error is deliberate, as in note() itself:
  # statistics that were not gathered are no reason to bring a feature's cycle
  # down.
  # A sync runs under the review step's rules (sync_session's step_settings),
  # so a ban those set on purpose is known as one.
  local rules=""
  [[ "$step" == sync ]] && rules=review
  CLAUDE_PROJECT_DIR="$wt" SCLAUDE_POLICY_PERSON="$(developer_name 2>/dev/null)" \
    SCLAUDE_POLICY_STEP="$rules" python3 "$HOOKS/collect-denials.py" \
    "$step" "$transcript" 2>/dev/null || true
}

# The friction review: the session that fixes the orchestrator after every step session.
#
# Steps run into bans, and some of those bans are unnecessary — they were
# configured blind. .sclaude/local/feature/friction.log accumulates the records of that; here a
# separate session reads them, proposes a fix and, with the human's agreement,
# makes it.
#
# Why a full session rather than a review in the script: deciding "is this ban
# deliberate or an obstacle" requires context — what the step was trying to do
# and what it cost. That is reading a transcript and reasoning, not a grep.
#
# The directory is the feature's worktree: what the review decides goes into the
# product, on the feature's branch, or into sclaude in the feature's workshop;
# sclaude's live checkout is read-only to it.
# That checkout is added with --add-dir, to read a restriction where it is
# written, and so are the transcripts, which lie outside both: without it the
# file tools will not go there.
# The fourth argument is "re-read what was reviewed": the log is empty and the
# human wants to go back to what has already been reviewed. We then skip both the
# gathering and the tidying — there is nothing to move, and the session reads
# .reviewed anyway.
#
# This used to be done differently: cmd_friction copied .reviewed back into log
# only to pass the emptiness check below, and the tidying then immediately
# appended a copy into .reviewed over the original. Every such round doubled the
# log — twelve entries became twenty-four, then forty-eight, and the review
# session paid for every copy as for a new entry.
run_friction() {
  local wt="$1" slug="$2" key="$3" reread="${4:-}"
  local log="$wt/.sclaude/local/feature/friction.log"
  local reviewed="$log.reviewed"
  # This review's own entries (see `reading` below), by its key.
  local batch="$wt/.sclaude/local/feature/friction-$key.log"
  local state="$wt/.sclaude/local/feature/state.json"
  # The key names what is reviewed: `review-3` is the third session of the
  # review step (step_run_key), `fix-preview-1` a fixing session, and a bare
  # step name the key a review had before it followed every session. The step
  # and the session number are read back out of it for the label and for
  # gathering that session's refusals.
  local step="$key" number=""
  if [[ "$key" =~ ^([a-z]+)-([0-9]+)$ ]]; then
    step="${BASH_REMATCH[1]}"
    number="${BASH_REMATCH[2]}"
  fi

  # An unclosed review is one that began and did not reach the end. It changes
  # the answer to "is there anything to review": the log in that case is empty by
  # construction (it was moved into .reviewed before that session), and the
  # emptiness check below would turn away the return into the interrupted
  # conversation.
  #
  # Strictly this review, by key. The question "is anything unclosed anywhere"
  # is a different one and is asked below: `pending` also decides whether the
  # fresh log is moved into .reviewed, and a review of some other key hanging
  # open must not stop this one's entries from being moved — they would never
  # be read.
  local pending=""
  [[ "$(friction_pending "$state" || true)" == "$key" ]] && pending=1

  # An unclosed review elsewhere holds the cycle all the same.
  #
  # It used to hold nothing. The gate above was the only reader of
  # friction_pending here, and it compares against this step's key — so a review
  # keyed `fix-preview-1` was never equal to the step `review`, never fired, and
  # the feature travelled on with it open. One feature carried one to the end
  # that way. cmd_resume and cmd_reset already ask the bare question; this makes
  # the three agree.
  #
  # We send the caller to that review rather than running this one: two open
  # reviews at once would be two conversations editing the orchestrator.
  local other; other="$(friction_pending "$state" || true)"
  if [[ -n "$other" && "$other" != "$key" ]]; then
    warn ""
    warn "  An earlier friction review is still open: $other."
    warn "  It holds the cycle — close it first: $SELF friction $slug"
    return 1
  fi

  # First we gather what the hook could not record: the refusals Claude Code
  # itself issued. There is no hook for such an event — PostToolUse fires only
  # after a successful call — so they are read from the finished step's
  # transcript. This goes BEFORE the emptiness check: a step obstructed by the
  # classifier alone leaves the log empty, and without the gathering the review
  # would not come up at all. That is exactly how three refusals in step 4 of
  # one feature were lost.
  # A key held under [g] had its session's refusals gathered when it was
  # held (friction_hold): gathered again they would be in the log twice.
  [[ -n "$reread" || "$(state_get "$state" steps.review.friction_held 2>/dev/null || true)" == "$key" ]] \
    || collect_denials "$wt" "$step" "$(step_run_session "$state" "$key")"

  # Empty means there is nothing to review and we do not start a session. When
  # re-reading we look at what was reviewed: there is no fresh log in that case by
  # definition. An unclosed review goes past both checks: it is returning to a
  # conversation rather than starting a new one, and the log is no longer needed
  # for that.
  #
  # An empty log is recorded rather than passed over in silence. Without that
  # the state says nothing at all, and nothing is what a feature abandoned
  # before this step says too — the issue's column could not tell "there was no
  # friction here" from "we never got this far", and printed the same dash for
  # both. One flag settles it, and it is the ordinary case: most steps run into
  # nothing.
  if [[ -n "$pending" ]]; then
    :
  elif [[ -n "$reread" ]]; then
    [[ -s "$reviewed" ]] || return 0
  else
    [[ -s "$log" ]] || {
      state_set "$state" "friction.$key.empty" true
      history_add "$state" "friction.$key" empty
      return 0
    }
  fi

  # No queue between reviews: each commits into its own feature's worktree, on
  # that feature's branch. They used to wait for each other because they all
  # edited the one sclaude checkout, which they no longer touch.
  # Proposals alone have nothing to decide: see friction_proposals.py. They are
  # put off here, into the product's deferred file on the feature's branch, and
  # the log moves into .reviewed as a reviewed one does.
  local deferred_from; deferred_from="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"
  # The person's "write them in now" outlives an interrupted review: a pending
  # one is not asked again, and a fresh session in its place would put the
  # rules off against the answer.
  FRICTION_APPLY_NOW=""
  if [[ -n "$pending" ]]; then
    [[ "$(state_get "$state" "friction.$key.apply_now" 2>/dev/null || true)" == "true" ]] && FRICTION_APPLY_NOW=1
  else
    state_set "$state" "friction.$key.apply_now" null 2>/dev/null || true
  fi
  if [[ -z "$reread" && -z "$pending" ]] \
     && friction_defer_proposals "$wt" "$slug" "$key" "$step"; then
    { cat "$log" >> "$reviewed" 2>/dev/null && rm -f "$log"; } || true
    # What [g] held was in that log, and went with it. Put off, the review
    # has ended here: owed for this key, it is owed no more.
    friction_log_read "$state" "$key"
    if [[ "$(state_get "$state" friction_owed 2>/dev/null || true)" == "$key" ]]; then
      state_set "$state" friction_owed null 2>/dev/null || true
      state_set "$state" friction_owed_told null 2>/dev/null || true
    fi
    history_add "$state" "friction.$key" deferred
    # Entries alone skip the pull request (deferred_to_main).
    deferred_to_main "$wt" "$deferred_from" || friction_push_project "$wt" "$deferred_from"
    return 0
  fi
  if [[ -z "$reread" && -z "$pending" ]] && friction_hold "$wt" "$key" "$step"; then
    return 0
  fi
  # A review that cannot be held — one cut off and resumed, a re-read —
  # waits for the terminal while [g] runs step 4: opened without one (a
  # timer, the bot off WSL; on WSL the bot opens a tab), it is a plan-mode
  # review nobody is there to answer. Owed still, as a review that did not take place is.
  if [[ -n "$reread" || -n "$pending" ]] && [[ -z "${FRICTION_NO_HOLD:-}" ]] \
     && ! [[ -t 0 && -t 1 ]] && declare -F review_go_on >/dev/null && review_go_on "$wt" \
     && [[ "$(state_get "$state" step 2>/dev/null || true)" == review ]]; then
    info "  The friction review $key waits for you at the terminal: $SELF friction $slug"
    return 1
  fi
  # What is being reviewed, and which prompt says so.
  #
  # A step's review and a fixing session's differ in their opening and their
  # ending and in nothing else — the log's shape, the four sources, what is
  # worth fixing and what is a deliberate ban are the same questions. So the
  # middle lives in _friction-body.md and the two prompts are a header and a
  # tail around it.
  #
  # The label matters in three places below, and `step_title` answers for none
  # of them on a fixing key: it looks up STEP_SPEC and returns empty for
  # `fix-preview-1`, which left the prompt reading `the "" regression` and the
  # terminal `after step ''`.
  local label head_prompt
  if [[ "$step" == fix-* ]]; then
    local rest="${step#fix-}"
    label="${rest%-*}"
    head_prompt="$PROMPTS/friction-fix.md"
  elif [[ "$step" == sync ]]; then
    # The sync with main, numbered as a step of the cycle but no step of
    # STEP_SPEC: step_title has no name for it.
    label="sync"
    head_prompt="$PROMPTS/friction.md"
  elif [[ "$step" == unread ]]; then
    # friction_before_retro: entries of any step that no review read.
    label="any, read before the retrospective"
    head_prompt="$PROMPTS/friction.md"
  else
    label="$(step_title "$step")"
    head_prompt="$PROMPTS/friction.md"
  fi
  [[ -f "$head_prompt" && -f "$PROMPTS/_friction-body.md" ]] || return 0

  # We move the log away BEFORE the session rather than after it: the line that
  # stands after the return from `claude` cannot be trusted. The review exists
  # precisely to edit this very file, and bash reads a script lazily, by offset
  # into an open descriptor — rewriting bin/sclaude in place shifts everything
  # below the point of the edit. A Ctrl-C in the session carries the script away
  # the same way. After the `code` step of the password-change feature the
  # tidying did not happen, and twelve reviewed entries came up for review a
  # second time, together with a session and its cost.
  #
  # What was reviewed lies next to it under .reviewed — going back to it is still
  # possible, and that is what `sclaude friction` lives on.
  #
  # We append rather than replace. `mv -f` destroyed the previous .reviewed
  # whenever there already was one: on one feature step 2's
  # entry about check:links was lost that way — 860 bytes that no longer exist.
  # The round trip through cmd_friction (which copies .reviewed back into log)
  # made that even more certain: it is enough for somebody to have added a line
  # between reviews.
  #
  # When re-reading there is nothing to move: the log is empty and .reviewed is
  # already in place — touching it would mean doubling it.
  # An unclosed review moves nothing here either: its log is already in
  # .reviewed, and a repeat would double the entries — precisely the trouble
  # described a paragraph above about the round trip through cmd_friction.
  [[ -n "$reread" || -n "$pending" ]] \
    || { cp "$log" "$batch" 2>/dev/null; cat "$log" >> "$reviewed" 2>/dev/null && rm -f "$log" || true; }
  # Whatever [g] held (friction_hold) was in that log: this review reads it,
  # and nothing is owed for the held keys any more, nor for an `unread-N` the
  # check before the retrospective waited on.
  [[ -n "$reread" || -n "$pending" ]] || friction_log_read "$state" "$key"
  # What this review reads: its own entries, kept apart as they were moved —
  # .reviewed holds every review's, and the review after step 2 read step 1's
  # again and deferred the same refusal twice. A re-read (`sclaude friction`)
  # is of everything; an unclosed review from before the batches, of .reviewed.
  local reading="$reviewed"
  [[ -z "$reread" && -s "$batch" ]] && reading="$batch"

  local transcript prompt count
  transcript="$(python3 - "$wt" "$wt/.sclaude/local/feature/state.json" "$LIB" <<'PYEOF'
import json, os, sys
wt, state = sys.argv[1], sys.argv[2]
sys.path.insert(0, sys.argv[3])
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
from session_end import chain
# The same method as in capture_plan: the sessions directory is the worktree's
# path with everything but letters and digits replaced by a hyphen.
encoded = "".join(c if c.isalnum() else "-" for c in wt)
base = os.path.expanduser(os.path.join("~/.claude/projects", encoded))
try:
    with open(state) as fh:
        saved = json.load(fh)
except (OSError, ValueError):
    saved = {}
steps = saved.get("steps") or {}
out = []
# Every session a step ran in, named as its row in the issue. The step's own
# `session` used to be the only one listed, and a rotated review round clears
# it — so the review that follows that round was handed every transcript but
# the one it was about.
for name, node in steps.items():
    node = node or {}
    runs = [r for r in (node.get("runs") or []) if isinstance(r, dict)]
    sids = [r.get("session") for r in runs] or [node.get("session")]
    for number, sid in enumerate(sids, start=1):
        if not sid:
            continue
        # The transcript the conversation went on in, which holds all of it.
        path = chain(os.path.join(base, sid + ".jsonl"))[-1]
        if os.path.exists(path):
            out.append("%s%s — %s" % (name, " (%d)" % number if len(sids) > 1 else "", path))

# The fixing sessions, which are not steps and are not in `steps`. Their ids
# are kept beside the stage that raised them, and only the first eight
# characters of each: that is what the issue's summary prints, and it is enough
# to find the file — the transcripts are named by the full UUID, so this is a
# prefix match. Forty files in a live directory collide on eight hex characters
# at a rate not worth the state it would take to store the rest; should two
# ever match, the first is no worse than the nothing this used to find.
import glob
for stage, node in (saved.get("regression") or {}).items():
    for short in ((node or {}).get("fixes") or "").split():
        found = sorted(glob.glob(os.path.join(base, short + "*.jsonl")))
        if found:
            # Named as its row in the issue (fix_name in issue_sync.sh).
            name = "fix after regression" if stage == "local" else "fix after %s regression" % stage
            out.append("%s — %s" % (name, chain(found[0])[-1]))

# The syncs with main, which are not steps either and have their own friction
# reviews (sync-N): named as their rows in the issue (run_rows in issue_sync.sh).
syncs = [r for r in ((saved.get("sync") or {}).get("runs") or []) if isinstance(r, dict)]
for number, run in enumerate(syncs, start=1):
    if run.get("session"):
        path = chain(os.path.join(base, run["session"] + ".jsonl"))[-1]
        if os.path.exists(path):
            out.append("sync with main%s — %s" % (" (%d)" % number if len(syncs) > 1 else "", path))

print("; ".join(out) if out else base)
PYEOF
)"

  # The body is spliced in where the header says `<body>`, then the
  # substitutions run over the whole thing — the tags live on both sides of the
  # seam, `<log>` and `<transcript>` in the body, `<step>` and `<feature>` in
  # the header. `r` reads the file in after the matching line; `d` removes the
  # marker itself, which would otherwise stay above it.
  # The review closes itself once its change is committed, or once it has
  # decided there is nothing to change: it writes this file before its report
  # (see session_watch_start). It runs in instruments, outside the feature's
  # worktree, so the marker is a path of its own, as the epilogue's is.
  local done_file="${TMPDIR:-/tmp}/sclaude-friction-$slug.done"

  # The deferred file the review may append to is the product's, in this
  # person's rules folder (deferred.sh). Only its folder is made here, which
  # git does not see: the file itself was created empty before every review,
  # most of which defer nothing, and it then stood in the worktree as
  # uncommitted work and rode into the next `git add -A`.
  # Asked once here, so the substitutions below find the answer kept rather
  # than asking main again in each of their subshells.
  product_maintainer "$wt" || true
  mkdir -p "$(dirname "$(deferred_file "$wt" "$slug")")" 2>/dev/null || true
  prompt="$(sed -e "/^<body>$/r $PROMPTS/_friction-body.md" -e "/^<body>$/d" \
    "$head_prompt" \
    | sed -e "s|<feature>|$slug|g" -e "s|<step>|$label|g" \
      -e "s|<deferred>|$(deferred_file "$wt" "$slug")|g" \
      -e "s|<rules>|$(product_rules_dir "$wt")|g" -e "s|<instruments>|$INSTRUMENTS|g" \
      -e "s|<log>|$reading|g" -e "s|<transcript>|$transcript|g" \
      -e "s|<done-marker>|$done_file|g" -e "s|<worktree>|$wt|g" \
      -e "s|<branch>|$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "the feature's branch")|g")"

  # The paragraph on changing sclaude in the feature's workshop (workshop.sh),
  # free here: the plan I approve is the yes. Put in whole, past sed, since it
  # runs to several lines.
  prompt="$(WORKSHOP_RULES="$(workshop_rules "$wt")" python3 -c '
import os, sys
sys.stdout.write(sys.stdin.read().replace("<workshop-rules>", os.environ["WORKSHOP_RULES"]))' <<< "$prompt")"

  # The person asked for the proposals in CLAUDE.md now (friction_defer_proposals):
  # the body puts every proposal off, and is told otherwise for this review.
  if [[ -n "${FRICTION_APPLY_NOW:-}" ]]; then
    prompt+=$'\n\n'"**I asked for this log's proposals in the project's CLAUDE.md now, not put off.** Write each \`proposal\` entry's rule into CLAUDE.md in this review, as any other change you make here, and leave it out of the deferred file: a decision of this cycle rests on it, and a month without it is a month of sessions that do not know it."
  fi

  # The entries begin with a date; "^2" also caught any line of prose starting
  # with a two — on a live log of three entries it gave one.
  # grep -c prints its 0 and fails with it: `|| echo 0` made it two lines.
  count="$(grep -cE '^20[0-9]{2}-' "$reading" 2>/dev/null)" || count="${count:-0}"

  echo ""
  echo "${BOLD}${BLUE}── $slug · $(phase_title friction "$key") ──${OFF}"
  info "   opus / medium / plan · $wt"
  info "   $count entries · $(basename "$reading")"
  echo ""

  # A review is as much a session as a step, and it is interrupted the same way:
  # by a limit, by a closed terminal, by Ctrl-C. The difference was that a step
  # has somewhere to return to while a review did not: the id was recorded
  # nowhere, the log had already been moved into .reviewed — and the next attempt
  # started the review afresh, paying for the same entries a second time. So it
  # now has a place of its own in the state, next to steps, and it is written
  # BEFORE the launch.
  #
  # We name the session ourselves, as in a step: there is no --bg here (a review
  # runs in the terminal), so --session-id is available, and a UUID generated in
  # advance survives any way of leaving.
  #
  # The review works in the feature's tree, as the retrospective and the
  # deferred review do: it changes the product, sclaude's checkout is
  # read-only to it, and started there every relative write and bare git
  # commit resolved into that checkout and was refused, with sclaude's
  # CLAUDE.md loaded rather than the product's. The transcript lies by the
  # directory a session was started in, recorded with it; one started before
  # the record is sclaude's checkout's.
  local session where
  session="$(state_get "$state" "friction.$key.session" || true)"
  where="$(state_get "$state" "friction.$key.cwd" || true)"
  [[ -n "$session" && -z "$where" ]] && where="$INSTRUMENTS"
  if [[ -n "$session" ]] && ! live_session "$where" "$session" >/dev/null; then
    session=""
  fi
  [[ -n "$session" ]] || where="$wt"

  # An open session cannot be opened a second time — the same trouble as with a
  # step: claude exits immediately, printing "Resume this session with…". The
  # five-second threshold below will catch that and leave the review unclosed,
  # but it will tell the human "it did not start" rather than "it is already
  # open" — and they will look for the culprit themselves. So we check here and
  # name it.
  if [[ -n "$session" ]]; then
    local fholder; fholder="$(session_holder "$session" "$where")"
    if [[ -n "$fholder" ]]; then
      warn ""
      warn "  This friction review is already open elsewhere ($fholder)."
      warn "  Close it there and try again — or just carry on where it is open."
      warn "  To drop it and move on: $SELF reset $slug"
      return 1
    fi
  fi

  # The review changes the product on the feature's branch — its policy, its
  # deferred file, its code — and sclaude only in the feature's workshop,
  # which sclaude publishes itself (workshop.sh): there is no orchestrator
  # range to record here.
  # Where the feature's branch stood when this review began, kept with it: a
  # resumed review starts on top of what its interrupted run committed, and
  # taking HEAD again here made that work invisible, never pushed or counted.
  local project_before project_after
  project_before=""
  [[ -n "$session" ]] && project_before="$(state_get "$state" "friction.$key.project_base" || true)"
  # Only while HEAD still descends from it: a branch that moved elsewhere in
  # between (rebased, reset) would credit the review with commits not its own.
  if [[ -n "$project_before" ]] && ! git -C "$wt" merge-base --is-ancestor "$project_before" HEAD 2>/dev/null; then
    project_before=""
  fi
  if [[ -z "$project_before" ]]; then
    project_before="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"
    state_set "$state" "friction.$key.project_base" "$project_before" 2>/dev/null || true
  fi

  # A stall belongs to the conversation that stalled, which its run keeps.
  # Left on the node, it would name this one stalled while it runs — resumed
  # or new: a stalled transcript can exist, so a stall is often resumed.
  state_set "$state" "friction.$key.stalled" null 2>/dev/null || true

  # sclaude's live checkout is read-only to it (review_guard_settings).
  local -a guard=()
  local guard_out
  guard_out="$(review_guard_settings "$wt")" \
    || { warn "  The friction review was not started: sclaude could not read its rules (see above)."; return 1; }
  mapfile -t guard <<< "$guard_out"
  # Here, past every reason not to start: the topic hears of a start that
  # happens. How much there is to review is the one detail it gets.
  ask_feed say "$(phase_line "$([[ -n "$session" ]] && echo resumed || echo started)" friction "$key") · $count $([[ "$count" == 1 ]] && echo entry || echo entries)"
  local before_instruments; before_instruments="$(instruments_state)"
  if [[ -n "$session" ]]; then
    # Returning to an interrupted review. The log does not need moving — it is
    # already in .reviewed, and that is what the session was reading; the prompt
    # is the same as it was.
    info "   resuming the interrupted friction review"
    session_runs "$state" "friction.$key" open "$session"
    session_watch_start "" "$session" "$done_file" "$where"
    ( cd "$where" && claude_launch --resume "$session" --model opus --effort medium \
        "${guard[@]}" \
        --permission-mode plan --add-dir "$HOME/.claude/projects" --add-dir "$INSTRUMENTS" \
        -n "$(session_label friction "$key")/$slug" \
        "Back in the friction review for feature '$slug'. Pick up where the conversation left off; re-read $reading if you need to." )
  else
    session="$(new_session_id)"
    # Keyed by what the review is about. `friction.after` used to carry that,
    # because the slot itself was nameless; now the name is the key and the
    # field has nothing left to say.
    state_set "$state" "friction.$key.session" "$session"
    state_set "$state" "friction.$key.cwd" "$where"
    state_set "$state" "friction.$key.started" "$(date -Iseconds)"
    state_set "$state" "friction.$key.done" false
    # What an earlier review of this key came to belongs to that review, which
    # its run keeps. Left on the node, latest_friction_cell reads them first
    # and gives this new review the old one's answer.
    local flag
    for flag in empty fixed unread verdict verdict_note; do
      state_set "$state" "friction.$key.$flag" null 2>/dev/null || true
    done
    session_runs "$state" "friction.$key" open "$session"
    session_watch_start "" "$session" "$done_file" "$where"
    ( cd "$where" && claude_launch --session-id "$session" --model opus --effort medium \
        "${guard[@]}" \
        --permission-mode plan --add-dir "$HOME/.claude/projects" --add-dir "$INSTRUMENTS" \
        -n "$(session_label friction "$key")/$slug" "$prompt" )
  fi
  session_watch_stop
  instruments_unchanged "$before_instruments" "friction review" || true
  session_closed "$done_file" "$where" "$session" "" "" friction "$key" || true

  local changed=""
  # What the review changed is the product's, committed on the feature's branch
  # (_friction-body.md). Pushed here, with the project's own hooks, so the pull
  # request carries the fix.
  project_after="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "$project_before" && -n "$project_after" && "$project_before" != "$project_after" ]]; then
    changed=1
    # Entries the review put off go to main by themselves (deferred_to_main);
    # what else it committed follows them to the pull request. Whether they
    # went is passed on: a merged branch's fix is then carried without them.
    local entries_sent=""
    deferred_to_main "$wt" "$project_before" && entries_sent=1
    [[ "$(git -C "$wt" rev-parse HEAD 2>/dev/null)" == "$project_before" ]] \
      || friction_push_project "$wt" "$project_before" "$entries_sent"
  fi

  # A session that never got going did not review anything — it refused to
  # start or hit a limit right at the entrance. Marking such a review closed
  # means losing it silently: the log is already in .reviewed, and nobody will
  # offer it a second time. The same witness by which run_step tells a step that
  # never happened.
  if ! session_started "$where" "$session"; then
    # Marked so the issue can say which kind of open this is. An interrupted
    # review has a conversation to return to; one that never started has
    # nothing, and telling a human to go back to it sends them to an empty
    # transcript.
    state_set "$state" "friction.$key.stalled" true
    # Kept rather than dropped: a stalled review is a row the Friction column
    # already names, and the next attempt opens a new conversation beside it.
    session_runs "$state" "friction.$key" stall "$session"
    warn ""
    warn "  The friction review did not start — it stays open."
    warn "  Come back to it with: $SELF friction $slug"
    return 1
  fi

  session_runs "$state" "friction.$key" finish "$session" \
    "$([[ -n "$changed" ]] && echo fixed || echo reviewed)"
  state_set "$state" "friction.$key.done" true
  state_set "$state" "friction.$key.finished" "$(date -Iseconds)"
  # Owed before the retrospective (friction_before_retro), and now read.
  if [[ "$(state_get "$state" friction_owed 2>/dev/null || true)" == "$key" ]]; then
    state_set "$state" friction_owed null 2>/dev/null
    state_set "$state" friction_owed_told null 2>/dev/null
  fi
  # And we forget the id: the review took place, and there is nowhere left to
  # return to. Left behind, it is as poisonous as a step's dead id, only the
  # other way round — it is alive. The next step's review reads this same field,
  # the closed conversation's transcript is in place, live_session says "alive",
  # and the return branch opens the CLOSED review instead of a new one: the
  # fresh entries are not reviewed at all. Per-key storage narrows that to one
  # step rather than to whatever was reviewed last, but it does not remove it —
  # the id still has to go.
  state_set "$state" "friction.$key.was" "$session"
  # Whether the review changed anything. The HEAD comparison above already knows
  # — it is what decides the push — and throwing the answer away left the column
  # unable to tell a review that fixed the orchestrator from one that read the
  # entries and concluded every ban was deliberate. Both are proper outcomes;
  # they are not the same outcome.
  [[ -n "$changed" ]] && state_set "$state" "friction.$key.fixed" true
  # And which commits it was. The boolean above says a fix happened; the range
  # says what the fix was, and the issue's second table is rendered from it by
  # `git log` in the worktree. A review commits into the product, on the
  # feature's branch, and never into sclaude (write-guard.py --readonly), so
  # the product's range is the whole of it.
  if [[ -n "$changed" ]]; then
    state_set "$state" "friction.$key.project_from" "$project_before"
    state_set "$state" "friction.$key.project_to" "$project_after"
  fi
  # And what the review decided, in its own words.
  #
  # The range above says what changed; it cannot say that nothing changed on
  # purpose. A review that read every entry and found each ban working as
  # intended commits nothing, so it has no range, so the issue's table had no
  # row for it at all — and that is the ordinary outcome, not a rare one. The
  # verdict is the only place it can be recorded.
  #
  # Read from the transcript rather than written by the session: see
  # friction_verdict. A review that never printed the line leaves the fields
  # unset and the table falls back to naming the commits, which is what it did
  # before this existed.
  local verdict
  verdict="$(friction_verdict "$where" "$session" || true)"
  if [[ -n "$verdict" ]]; then
    state_set "$state" "friction.$key.verdict" "${verdict%%$'\t'*}"
    history_add "$state" "friction.$key" verdict verdict="${verdict%%$'\t'*}"
    local note="${verdict#*$'\t'}"
    [[ -n "$note" && "$note" != "$verdict" ]] \
      && state_set "$state" "friction.$key.verdict_note" "$note"
  fi
  state_set "$state" "friction.$key.session" null
  return 0
}

# Pushes the feature's branch after a friction review committed to it.
#
# Not a reason to stop: a failed push is about delivery, and the next step's
# push carries the commit as well.
#
# A branch whose pull request has merged already (a review after a fix to a
# red production regression) would carry the fix nowhere: no open pull request
# takes it to main, and `sclaude done` deletes the branch. Then the review's
# own commits, from <from>, go onto a new branch from main with a pull request
# of their own. <entries-sent> says deferred_to_main sent the deferred entries
# of that range to main already (friction_propose_project).
#
#   friction_push_project <wt> [from] [entries-sent]
friction_push_project() {
  local wt="$1" from="${2:-}" sent="${3:-}" branch
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" && "$branch" != "main" ]] || return 0
  if [[ -n "$from" && "$( (cd "$wt" && branch_pr_state "$branch") )" == "MERGED" ]]; then
    friction_propose_project "$wt" "$from" "$branch" "$sent"
    return 0
  fi
  if git -C "$wt" push -q origin "$branch" 2>/dev/null; then
    info "  the friction review's fix to the project is pushed to $branch"
  else
    warn "  could not push the friction review's fix to $branch — push it by hand:"
    warn "    git -C $wt push origin $branch"
  fi
}

# The friction review's commits, from..HEAD of the tree, on a branch of their
# own from origin/main, pushed with a pull request: the feature's branch has
# merged, and they would reach main no other way.
#
# With <entries-sent>, the range's deferred entries are on main already
# (deferred_to_main), and the branch holds a commit taking them back off it.
# Picked as they are, a commit that added them conflicts with the copy main
# holds, and the one taking them off would delete main's copy; so each commit
# is carried without the deferred folders, and one that touched nothing else
# is left out. Without it the entries are still the branch's alone, and are
# picked with the rest.
#
#   friction_propose_project <wt> <from> <branch> [entries-sent]
friction_propose_project() {
  local wt="$1" from="$2" branch="$3" sent="${4:-}" new tmp pr commits
  new="sclaude/friction-${branch##*/}-$(date +%Y%m%d-%H%M%S)"
  tmp="$(mktemp -d)"
  git -C "$wt" fetch -q origin main 2>/dev/null || true
  # The review's own commits only: a merge of main into the feature puts
  # main's commits in the range too, and picked onto main they come out empty
  # and stop the cherry-pick. With the entries sent, only those that change
  # something outside the deferred folders.
  # A list git could not make is not an empty one: it falls through to the
  # advice to carry them by hand, rather than to "nothing to carry".
  if [[ -n "$sent" ]]; then
    if commits="$(git -C "$wt" rev-list --reverse --no-merges HEAD "^$from" ^origin/main \
          -- . "${DEFERRED_EXCLUDES[@]}" 2>/dev/null)" && [[ -z "$commits" ]]; then
      info "  $branch has merged; the friction review's deferred entries are on main, and it holds nothing else to carry"
      rm -rf "$tmp"
      return 0
    fi
  else
    commits="$(git -C "$wt" rev-list --reverse --no-merges HEAD "^$from" ^origin/main 2>/dev/null)"
  fi
  if git -C "$wt" worktree add -q -b "$new" "$tmp/tree" origin/main 2>/dev/null \
      && [[ -n "$commits" ]] \
      && friction_carry "$wt" "$tmp/tree" "$sent" "$commits" \
      && git -C "$tmp/tree" push -q -u origin "$new" 2>/dev/null; then
    pr="$(cd "$tmp/tree" && gh pr create --base main --head "$new" --fill 2>/dev/null)" || pr=""
    info "  $branch has merged; the friction review's fix goes to main as ${pr:-$new (open its pull request by hand)}"
  else
    git -C "$tmp/tree" cherry-pick --abort >/dev/null 2>&1 || true
    warn "  $branch has merged, and the friction review's fix could not be put on a branch of its own."
    if [[ -n "$sent" ]]; then
      # Not the whole range: its deferred commits would undo main's entries.
      local named="$from..HEAD"
      # shellcheck disable=SC2086  # one word per commit
      [[ -n "$commits" ]] && named="$(git -C "$wt" rev-parse --short $commits | xargs)"
      warn "  Its commits are $named in $wt: carry them to main by hand,"
      warn "  leaving out the deferred folders — their entries are on main already."
    else
      warn "  Its commits are $from..HEAD in $wt: carry them to main by hand."
    fi
  fi
  git -C "$wt" worktree remove --force "$tmp/tree" >/dev/null 2>&1 || true
  # Pushed, or carried by hand from $wt: the local copy is of no use either way.
  git -C "$wt" branch -D "$new" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}

# Puts <commits> onto <tree>, in order: picked whole, or with <entries-sent>
# each one's change outside the deferred folders, under its own message
# (friction_propose_project).
#
#   friction_carry <wt> <tree> <entries-sent> <commits>
friction_carry() {
  local wt="$1" tree="$2" sent="$3" commits="$4" c
  if [[ -z "$sent" ]]; then
    # shellcheck disable=SC2086  # one word per commit
    git -C "$tree" cherry-pick $commits >/dev/null 2>&1
    return
  fi
  for c in $commits; do
    # Plumbing, with its format spelled out, and an apply that judges no
    # whitespace: a person's diff and apply settings (no prefixes, colour, an
    # external diff, whitespace errors) would refuse what a cherry-pick takes.
    git -C "$wt" diff-tree -p --binary --no-ext-diff --no-textconv --no-color \
        --src-prefix=a/ --dst-prefix=b/ "$c^" "$c" -- . "${DEFERRED_EXCLUDES[@]}" \
      | git -C "$tree" apply --index --3way --whitespace=nowarn >/dev/null 2>&1 || return 1
    git -C "$tree" commit -q --no-verify -C "$c" >/dev/null 2>&1 || return 1
  done
}

# Holds a review session's friction review while the review goes on by
# itself (review_go_on): the review is a session in plan mode, waiting for
# the person to approve its plan, and with them away it would stop the
# rounds [g] was ticked to keep going — a review session's, and any other
# step 4 runs: a sync with main, a regression's fixing session. Nothing is lost: the entries stay in
# the log, each later session's added to them, and the first friction review
# after the box comes off reads them all — the next session's, or at the
# latest friction_before_retro's. Not a plan approved for them: that is the
# person's yes to loosening a rule, and nobody is there to give it.
#
#   friction_hold <wt> <key> <step>   → 0 when held
friction_hold() {
  local wt="$1" key="$2" step="$3" state="$1/.sclaude/local/feature/state.json" n
  [[ -z "${FRICTION_NO_HOLD:-}" && "$(state_get "$state" step 2>/dev/null || true)" == review ]] \
    && declare -F review_go_on >/dev/null && review_go_on "$wt" || return 1
  state_set "$state" steps.review.friction_held "$key" 2>/dev/null || return 1
  # For the issue's Friction column: held, not "never got this far".
  state_set "$state" "friction.$key.held" true 2>/dev/null || true
  state_set "$state" "friction.$key.read_in" null 2>/dev/null || true
  history_add "$state" "friction.$key" held
  n="$(grep -cE '^20[0-9]{2}-' "$wt/.sclaude/local/feature/friction.log" 2>/dev/null)" || n="${n:-0}"
  info "  [g] go on by itself is ticked: the friction review waits for you, $n entr$([[ "$n" == 1 ]] && echo y || echo ies) kept;"
  info "  the next friction review reads them, and whatever later sessions add — at the latest, before the retrospective."
  ask_feed say "Friction review held for you ([g]): $n entr$([[ "$n" == 1 ]] && echo y || echo ies) kept, read before the retrospective at the latest."
  return 0
}

# The log was read under <key>, by a review or by the put-off of proposals:
# every key [g] held is settled by it — its node says which review read it,
# for the issue's Friction column — and so is an owed key it read for (an
# `unread-N` or a held one), unless it is <key> itself.
#
#   friction_log_read <state> <key>
friction_log_read() {
  PYTHONPATH="${STATE_CORE:-${LIB:-}/core}" python3 - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
path, key = sys.argv[1:3]
import state_file
state_file.lock(path)
with open(path) as fh:
    data = json.load(fh)
review = (data.get("steps") or {}).get("review") or {}
held = {review.pop("friction_held", None)}
for k, node in (data.get("friction") or {}).items():
    if isinstance(node, dict) and node.get("held") and k != key:
        node.pop("held")
        node["read_in"] = key
        held.add(k)
# An owed key whose entries this review read: an unread-N, or one [g] held.
# Not the key running now — its own end clears it, and a review cut off
# leaves it owed.
owed = str(data.get("friction_owed") or "")
if owed and owed != key and (owed.startswith("unread-") or owed in held):
    data["friction_owed"] = None
    data["friction_owed_told"] = None
state_file.write(path, data)
PY
}

# Every friction review still owed, before the retrospective: one [g] held in
# step 4 (friction_hold), one left open — cut off, never finished — and a log
# with entries no review read. The retrospective reads the friction logs, and
# the clean-up after it takes the tree and the log with it, so this is the
# last place they can be read. Always run, with [g] or without: a hold is one
# way to leave entries unread, and not the only one. Returns 1 when one is
# still owed: the retrospective and the clean-up wait for it.
#
#   friction_before_retro <wt> <slug>
friction_before_retro() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json" key held n tried=" "
  local log="$1/.sclaude/local/feature/friction.log"
  # The rounds are over by the retrospective, and a review run here is never
  # held, whatever [g] says (friction_hold): the person's box is theirs to
  # keep, so it is not touched.
  local FRICTION_NO_HOLD=1
  # One review at a time, until nothing is owed: a pending review reads only
  # its own batch, so the log and a held key can still be owed after it.
  while :; do
    held="$(state_get "$state" steps.review.friction_held 2>/dev/null || true)"
    [[ "$held" == null ]] && held=""
    # A held key whose entries a later review already read owes nothing.
    if [[ -n "$held" && ! -s "$log" ]]; then
      state_set "$state" steps.review.friction_held null 2>/dev/null || true
      held=""
    fi
    key="$(friction_pending "$state" || true)"
    [[ -n "$key" ]] || key="$held"
    if [[ -z "$key" && -s "$log" ]]; then
      n="$(python3 -c 'import json, sys
print(1 + sum(1 for k in (json.load(open(sys.argv[1])).get("friction") or {}) if k.startswith("unread-")))' "$state" 2>/dev/null || echo 1)"
      key="unread-$n"
    fi
    if [[ -z "$key" ]]; then
      state_set "$state" friction_owed null 2>/dev/null || true
      state_set "$state" friction_owed_told null 2>/dev/null || true
      return 0
    fi
    # Once each: a review that ran and still left its key owed would come
    # round for ever.
    [[ "$tried" == *" $key "* ]] && { warn "  The friction review $key ran and is still owed."; return 1; }
    tried+="$key "
    # Where the feature stands meanwhile, for the map and the menu (position).
    state_set "$state" friction_owed "$key" 2>/dev/null || true
    echo ""
    info "  Friction no review has read yet ($key): it comes before the retrospective and the clean-up."
    # A friction review is a conversation; the clean-up with no terminal (a
    # timer, the bot off WSL) has nobody to hold it, and must not remove the log unread. The topic is
    # told once a key, not on every call that finds it still owed.
    # Kept apart from friction_owed, which an attempt at the terminal sets
    # too: the topic must hear of it on the first wait without one.
    if ! [[ -t 0 && -t 1 ]]; then
      warn "  It needs you at the terminal."
      if [[ "$(state_get "$state" friction_owed_told 2>/dev/null || true)" != "$key" ]]; then
        ask_feed say "The retrospective and the clean-up wait for a friction review at the terminal: $SELF done $slug"
        state_set "$state" friction_owed_told "$key" 2>/dev/null || true
      fi
      return 1
    fi
    run_friction "$wt" "$slug" "$key" || return 1
  done
}

# Puts off a friction log that holds only proposed CLAUDE.md rules, without a
# session: the rows go into the product's deferred file in the worktree
# (deferred.sh) and are committed on the feature's branch, and the state
# records the review the way a session's deferral does. Returns 1 to leave the
# log to a session: anything but proposals in it, a deferred file that could
# not be written or committed — or the person wanting them in CLAUDE.md now.
#
# Put off without a question by default. The question stopped the cycle
# between a fix session and the review of its fixes until it was answered, and
# on one feature it was asked fourteen times, answered "put off" every time,
# and held the cycle for three hours once. SCLAUDE_FRICTION_ASK=on asks again:
# a rule the review's own decision rests on — a guard a fix put in, which the
# next session must not take out — put off for a month is a month of sessions
# that do not know it. "Now" leaves FRICTION_APPLY_NOW set, and the friction
# review that takes the log is told to write them in.
#
# Each put-off is a review of the key's own, in its runs: a fix session's key
# stands for all its rounds, and the state kept only the last one's.
#
# Once the rows are on the screen, a step that fails says which one before the
# log goes to a session: the screen said "put off" and a session opened all the
# same, with nothing to tell why.
#
#   friction_defer_proposals <wt> <slug> <key> <step>
friction_defer_proposals() {
  local wt="$1" slug="$2" key="$3" step="$4"
  local log="$wt/.sclaude/local/feature/friction.log" state="$wt/.sclaude/local/feature/state.json"
  local rows n now answer text
  [[ -s "$log" ]] || return 1
  rows="$(python3 "$LIB/improve/friction_proposals.py" "$log" "$(basename "$REPO")" \
            "$slug" "$step" 2>/dev/null)" || return 1
  [[ -n "$rows" ]] || return 1
  n="$(grep -c . <<< "$rows")"
  local file; file="$(deferred_file "$wt" "$slug")"
  # A file somebody is editing by hand goes to a session rather than being
  # mixed into: asked first, before anything is said or a model is called
  # for rows that would not be written.
  git -C "$wt" diff --quiet HEAD -- "$file" 2>/dev/null || return 1
  echo ""
  say "${BOLD}The friction log after '$key' holds only proposed CLAUDE.md rules:${OFF}"
  while IFS=$'\t' read -r _ _ _ _ _ text; do say "  - $text"; done <<< "$rows"
  # Only a "no" writes them in now. An ask that got no answer — the feature
  # ended elsewhere, no terminal — puts them off, as before the question.
  if [[ "${SCLAUDE_FRICTION_ASK:-off}" != "on" ]]; then
    info "  Put off to the monthly review (SCLAUDE_FRICTION_ASK=on asks first)."
  elif ask "${BOLD}Put them off to the monthly review? (n writes them into CLAUDE.md now) [y/n] ${OFF}" answer yn \
     && ! is_yes "$answer"; then
    FRICTION_APPLY_NOW=1
    state_set "$state" "friction.$key.apply_now" true 2>/dev/null || true
    return 1
  fi
  # Matched first against the classes put off already and against CLAUDE.md
  # (friction_classify.py): the same rule in other words takes its class, so
  # it counts as one rule seen again; one CLAUDE.md states goes under a class
  # of its own, for the monthly review to drop.
  # Each class is counted as it goes in. On any failure the rows stay as
  # they came. SCLAUDE_FRICTION_CLASSIFY=off skips it.
  if [[ "${SCLAUDE_FRICTION_CLASSIFY:-on}" != "off" ]]; then
    local notes classified note
    local -a folders=()
    notes="$(mktemp)"
    mapfile -t folders < <(deferred_dirs "$REPO")
    if classified="$(printf '%s\n' "$rows" | python3 "$LIB/improve/friction_classify.py" --notes "$notes" \
                       --own "$file" --claude-md "$wt/CLAUDE.md" "${folders[@]}" 2>/dev/null)"; then
      rows="$classified"
      while IFS= read -r note; do [[ -n "$note" ]] && info "  $note"; done < "$notes"
    fi
    rm -f "$notes"
  fi
  n="$(grep -c . <<< "$rows")"
  now="$(date -Iseconds)"
  # Its own id however close the last one was.
  local run_id; run_id="deferred-$(date +%s%N)"
  # How the file was before the rows, so a failed commit can put it back: from
  # HEAD when it is tracked, cut to its old size when it was there untracked,
  # gone when it was made just now. `git checkout HEAD` alone failed on a file
  # HEAD never had, the rows stayed, and the session that took over appended
  # them a second time.
  local existed=0 size=0
  [[ -f "$file" ]] && { existed=1; size="$(stat -c %s "$file" 2>/dev/null || echo 0)"; }
  deferred_ensure "$wt" "$slug" \
    || { friction_defer_failed "the deferred file $file could not be made"; return 1; }
  git -C "$wt" diff --quiet HEAD -- "$file" 2>/dev/null \
    || { friction_defer_failed "the deferred file $file has uncommitted changes"; return 1; }
  printf '%s\n' "$rows" >> "$file" 2>/dev/null \
    || { friction_defer_failed "the rows could not be written to $file"; return 1; }
  session_runs "$state" "friction.$key" open "$run_id"
  local nth
  nth="$(python3 -c 'import json,sys; print(len(((json.load(open(sys.argv[1])).get("friction") or {}).get(sys.argv[2]) or {}).get("runs") or []))' \
           "$state" "$key" 2>/dev/null || echo 1)"
  [[ "$nth" =~ ^[1-9][0-9]*$ ]] || nth=1
  local said
  if ! said="$( { git -C "$wt" add -- "$file" 2>/dev/null \
         && git -C "$wt" commit -q -m "chore(sclaude): put off $n CLAUDE.md proposal(s) from $key, review $nth" \
              -m "The friction log after '$key' held nothing but proposals, so sclaude put them off to the monthly review itself, with no session." \
              -- "$file" >/dev/null; } 2>&1)"; then
    said="$(grep -m1 . <<< "$said")"
    friction_defer_failed "the commit of the deferred file failed${said:+: $said}"
    git -C "$wt" reset -q -- "$file" 2>/dev/null || true
    local rel; rel="$(git -C "$wt" ls-files --full-name --error-unmatch -- "$file" 2>/dev/null)" || rel=""
    if [[ -n "$rel" ]] && git -C "$wt" cat-file -e "HEAD:$rel" 2>/dev/null; then
      git -C "$wt" checkout -q HEAD -- "$file" 2>/dev/null || true
    elif (( existed )); then
      truncate -s "$size" "$file" 2>/dev/null || true
    else
      rm -f "$file"
    fi
    session_runs "$state" "friction.$key" drop "$run_id"
    return 1
  fi
  session_runs "$state" "friction.$key" finish "$run_id"
  # An earlier review's answer belongs to its run, as for a session (run_friction).
  local flag
  for flag in empty fixed unread was; do
    state_set "$state" "friction.$key.$flag" null 2>/dev/null || true
  done
  state_set "$state" "friction.$key.started" "$now"
  state_set "$state" "friction.$key.finished" "$now"
  state_set "$state" "friction.$key.done" true
  state_set "$state" "friction.$key.verdict" deferred
  state_set "$state" "friction.$key.verdict_note" \
    "only CLAUDE.md proposals ($n), put off by sclaude without a session"
  # Nothing more said: "Put off to the monthly review" above already did.
  return 0
}

# The line friction_defer_proposals ends on when it leaves the log to a session
# after all.
#
#   friction_defer_failed <what failed>
friction_defer_failed() {
  info "  Not put off after all: $1 — a friction session takes the log."
}
