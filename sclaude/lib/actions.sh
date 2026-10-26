#!/usr/bin/env bash
#
# The actions on a single feature: the list of what can be done with it.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- the action list ---------------------------------------------------------
#
# The top-level menu is the feature list and nothing besides. Everything that can
# be done with a feature lives here, behind the checkbox: continue, sync with
# main, replan, link an issue, look at what is new in the PR, ship a preview,
# start the server, review the friction, clean up after the merge, abandon.
#
# Ten items is a lot, and exactly one rule saves the list: we show only what
# applies. "What is new in the PR" before a PR exists is not an item but a
# puzzle; "clean up after the merge" at step 1 is an offer to do something that
# will refuse to be done. A feature's state is known exactly, so this is a
# computation rather than a question — and the list shrinks by itself to three or
# four lines at the start of a cycle.
#
# The hints carry gathered facts: how far the branch has fallen behind, how many
# entries are in the friction log, which tree the server was started from. The
# list then answers questions rather than asking them.

# How far the branch has fallen behind origin/main. Prints a number (zero
# included) or nothing if it could not be worked out.
#
# Zero and "could not work it out" are different answers and must not be added
# together: an empty string would mean "all is well" even where origin/main
# simply did not resolve. The action list says "up to date with origin/main" — a
# statement rather than an excuse, and it must be a verified one.
#
# There is deliberately no fetch of origin here, but no silent reliance on
# someone else's either: the caller reports how fresh the information is. From
# the menu classify_branches (branches.sh) provided it — it pulls origin before
# any choice; from `sclaude actions <feature>`, that is from a button on a phone,
# nobody pulled, and while that was an implicit assumption a branch a dozen
# commits behind was shown as up to date.
branch_behind() {
  local branch="$1" n
  [[ -n "$branch" ]] || return 1
  # Both sides must exist: without origin/main there is nothing to count from,
  # and rev-list on a non-existent ref is as silent as on matching ones.
  git -C "$REPO" rev-parse --verify --quiet "origin/main" >/dev/null || return 1
  git -C "$REPO" rev-parse --verify --quiet "$branch" >/dev/null || return 1
  # Deferred entries alone do not make a branch stale (deferred_to_main).
  n="$(deferred_rev_count "$REPO" "$branch..origin/main")" || return 1
  [[ "$n" =~ ^[0-9]+$ ]] || return 1
  echo "$n"
}

# How many entries there are in the friction log: our own, the orchestrator's.
# We do not count the prose the session writes itself — it has no date at the
# start of the line, and counting by it would drift. The same method as in
# run_friction.
friction_count() {
  # Two declarations rather than one: in `local a="$1" b="$a/x"` bash expands
  # both right-hand sides before binding a single name — and $wt in them is not
  # the parameter yet. This worked only by accident: all three callers happened
  # to have a local of their own with the same name, and dynamic scoping
  # substituted it. A call from any other would give "/.sclaude/local/feature/friction.log" and
  # a silent "no entries". The same trap is described in github.sh at
  # issue_sync.
  local wt="$1"
  local log="$wt/.sclaude/local/feature/friction.log"
  [[ -s "$log" ]] || return 1
  grep -cE '^20[0-9]{2}-' "$log" 2>/dev/null || true
}

# Gathers the applicable actions and carries out the chosen one.
#
# The items are assembled in two linked parts: labels are what the human sees,
# verbs what will be carried out. Their index is shared, so the order in one
# place determines both the appearance and the meaning; they have no way of
# diverging.
feature_actions() {
  require_repo
  local slug="$1" wt state step pr issue branch behind fcount
  local ASK_SLUG="$slug"   # its questions go to its channel (ask_channel)
  wt="$(feature_worktree "$slug")" || die "no such feature: $slug"
  state="$wt/.sclaude/local/feature/state.json"
  step="$(state_get "$state" step || echo "?")"
  pr="$(state_get "$state" pr || true)";       [[ "$pr" == "null" ]] && pr=""
  issue="$(state_get "$state" issue || true)"; [[ "$issue" == "null" ]] && issue=""
  branch="$(state_get "$state" branch || true)"

  local -a labels=() verbs=()

  # Continue comes first, so that Enter all the way through matches what the
  # same menu does with the checkbox cleared. A closed feature has nothing to
  # continue: only the epilogue is left there, and cmd_resume calls that one
  # too.
  if [[ "$step" == "done" && "$(state_get "$state" no_change 2>/dev/null || true)" == "true" ]]; then
    labels+=("Finish up"$'\t'"no change to the code — cleanup")
  elif [[ "$step" == "done" ]]; then
    labels+=("Finish up"$'\t'"$(step_label "$step" "$wt") — preview, production, cleanup")
  else
    labels+=("Continue"$'\t'"step $(step_label "$step")")
  fi
  verbs+=(resume)

  # The branch information must be fresh by this point. From the menu
  # classify_branches refreshed it; people also arrive here directly — by command
  # and by a button on a phone — and then there is nobody to refresh it. We pull
  # it ourselves, quietly and without dying: there may be no network, and being
  # left without an action list because of that is not acceptable.
  git -C "$REPO" fetch origin --quiet 2>/dev/null || true

  behind="$(branch_behind "$branch" || true)"
  if [[ -z "$behind" ]]; then
    # We could not work it out, and we say so. "Up to date" here would be a
    # statement about something nobody checked.
    labels+=("Sync with main (sync)"$'\t'"could not compare with origin/main")
  elif [[ "$behind" == "0" ]]; then
    labels+=("Sync with main (sync)"$'\t'"up to date with origin/main")
  else
    # And whether the merge would stop on conflicts: then it is a session's
    # work (sync_with_main), which the person should know before choosing it.
    local conflicts="" crc=0
    [[ -n "$wt" ]] && { conflicts="$(merge_conflicts "$wt" nofetch)" || crc=$?; }
    if [[ "$crc" -eq 1 ]]; then
      # Only the deferred logs: sclaude's own merge, no session to pay for.
      local -a cfiles; mapfile -t cfiles <<< "$conflicts"
      local who="a session merges them"
      sync_deferred_only "$wt" "${cfiles[@]}" && who="sclaude merges them itself"
      labels+=("Sync with main (sync)"$'\t'"$behind commit(s) behind origin/main, ${#cfiles[@]} file(s) conflict — $who")
    else
      labels+=("Sync with main (sync)"$'\t'"$behind commit(s) behind origin/main")
    fi
  fi
  verbs+=(sync)

  # Replanning makes sense at any point while the cycle has not ended: both at
  # step 1 (the conversation reached a dead end) and later (the plan turned out
  # to be the wrong one).
  if [[ "$step" != "done" ]]; then
    labels+=("Re-plan from step 1 (replan)"$'\t'"a new conversation; the code stays")
    verbs+=(replan)
  fi

  # A finished feature can be sent back to development, for any reason — the
  # same return QA makes by moving the card. Only once it is finished: before
  # that it is still in development.
  if [[ "$step" == "done" ]]; then
    labels+=("Return to development (return)"$'\t'"back to step 4, with what was said since")
    verbs+=(return)
  fi

  if [[ -n "$issue" ]]; then
    labels+=("Re-link the issue (issue)"$'\t'"now #$issue")
  else
    labels+=("Link or create an issue (issue)"$'\t'"this feature has none")
  fi
  verbs+=(issue)

  # What is new in the PR only when there is a PR: before that it is an item
  # leading nowhere.
  if [[ -n "$pr" ]]; then
    labels+=("What's new on PR #$pr (news)"$'\t'"comments and checks since the last session")
    verbs+=(news)
  fi

  # Preview deploys the worktree's contents, so before step 2 there is nothing
  # to ship: the tree is still empty.
  if [[ "$step" != "plan" ]]; then
    labels+=("Deploy a preview (preview)"$'\t'"this branch on real hosting")
    verbs+=(preview)
  fi

  # The rollback, only once the feature has actually reached production. Before
  # that there is nothing to go back from, and an item offering to undo
  # something that never happened is the "puzzle" this list exists not to be.
  local dsha rbcode rbnote
  dsha="$(state_get "$state" deploy.prod.sha 2>/dev/null || true)"
  if [[ -n "$dsha" && "$dsha" != "null" ]]; then
    rbcode="$(state_get "$state" rollback.prod.code 2>/dev/null || true)"
    if [[ "$rbcode" == "done" ]]; then
      rbnote="already rolled back — production runs the release before this"
    elif [[ "$(regression_status "$wt" prod 2>/dev/null || true)" == "failed" ]]; then
      rbnote="the prod regression is red — this puts the previous release back"
    else
      rbnote="put the previous release back in production"
    fi
    labels+=("Roll production back (rollback)"$'\t'"$rbnote")
    verbs+=(rollback)
  fi

  # The server: we say what is going on with it — whether it is up, and where
  # to open it. Read from the state rather than claimed: looking at a menu
  # should not hand a feature a port it has never used.
  local pid cwd port
  port="$DEV_PORT_PINNED"
  [[ -n "$port" ]] || port="$(state_get "$wt/.sclaude/local/feature/state.json" dev.port 2>/dev/null || true)"
  pid="$(dev_pid "$port")"
  if [[ -n "$pid" ]]; then
    cwd="$(dev_cwd "$pid")"
    if [[ "$cwd" == "$wt" ]]; then
      labels+=("Dev server (dev)"$'\t'"running on $(dev_address "$wt")")
    else
      labels+=("Dev server (dev)"$'\t'"port $port held by $(basename "${cwd:-elsewhere}") — moves on start")
    fi
  else
    local where=""
    [[ -n "$DEV_PORT_PINNED" ]] || where="$(state_get "$wt/.sclaude/local/feature/state.json" dev.label 2>/dev/null || true)"
    labels+=("Dev server (dev)"$'\t'"not running${where:+ — opens at http://$where.localhost:$PROXY_PORT}")
  fi
  verbs+=(dev)

  fcount="$(friction_count "$wt" || true)"
  if [[ -n "$fcount" && "$fcount" != "0" ]]; then
    labels+=("Review friction (friction)"$'\t'"$fcount entry(ies) waiting")
    verbs+=(friction)
  elif [[ -s "$wt/.sclaude/local/feature/friction.log.reviewed" ]]; then
    labels+=("Review friction (friction)"$'\t'"nothing new; re-read what was reviewed")
    verbs+=(friction)
  fi

  # The regression, with what the state remembers of the last run. Offered on
  # every step rather than only on the ones that gate: a human who has just
  # changed something usually wants to know whether it still works, and that
  # question does not wait for a step to end.
  local rstatus rnote_r
  rstatus="$(regression_status "$wt" local)"
  case "$rstatus" in
    passed) rnote_r="green — it will not run again until something changes" ;;
    failed) rnote_r="red on $(state_get "$wt/.sclaude/local/feature/state.json" regression.local.failed_at 2>/dev/null || echo "a part")" ;;
    *)      rnote_r="not run yet for this feature" ;;
  esac
  labels+=("Run the regression (regression)"$'\t'"$rnote_r")
  verbs+=(regression)
  # Production's suite again, while production holds the feature red: the
  # one press that lifts the hold (prod_red_hold) without a terminal. Read
  # from the state alone — a menu does not ask GitHub; the command does.
  # On `done` only: back in development, its fix's pull request is the
  # state's, and production does not carry that yet.
  if [[ "$step" == "done" && "$(regression_status "$wt" prod)" == "failed" \
        && -n "${dsha:-}" && "$dsha" != "null" && "${rbcode:-}" != "done" ]]; then
    local pnote="red on production; green lifts the hold"
    [[ "$(state_get "$state" regression.prod.unrunnable 2>/dev/null || true)" == "true" ]] \
      && pnote="could not run on production last time; green lifts the hold"
    labels+=("Check production again (regression-prod)"$'\t'"$pnote")
    verbs+=(regression-prod)
  fi

  # The clean-up only when there is something to clean up: before the merge it
  # will refuse by itself, and offering it means offering a refusal.
  if [[ "$step" == "done" || "$step" == "review" ]]; then
    labels+=("Finish after the merge (done)"$'\t'"remove the worktree and the branches")
    verbs+=(done)
  fi

  # Restarting a step goes behind a separator, together with abandoning: both
  # are about something having gone wrong, and they should not stand right next
  # to "continue". The hint carries what people come here for — what exactly is
  # wrong with the step's conversation.
  #
  # A closed feature has nothing to restart: it no longer has a step.
  if [[ "$step" != "done" ]]; then
    labels+=($'\t')
    verbs+=(nothing)
    # We name an unclosed friction review first: it holds the step, and a human
    # arriving here with "the feature is not moving" has most often run into
    # exactly that. The item is the same one — cmd_reset will ask about the
    # review separately.
    local rsession rnote rtitle
    rtitle="Start this step over (reset)"
    local rkey; rkey="$(friction_pending "$state" || true)"
    rsession=""
    [[ -n "$rkey" ]] && rsession="$(state_get "$state" "friction.$rkey.session" || true)"
    if [[ -n "$rsession" && "$rsession" != "null" ]]; then
      rtitle="Unblock this feature (reset)"
      rnote="an unfinished friction review is holding the step"
    else
      rsession="$(state_get "$state" "steps.$step.session" || true)"
      if [[ -z "$rsession" || "$rsession" == "null" ]]; then
        rnote="this step has no conversation yet"
      elif ! live_session "$wt" "$rsession" >/dev/null; then
        rnote="its conversation never started — resuming will not work"
      else
        # We do not ask about "open in another window" here, pleasant as it
        # would be to know. `claude agents --json` answers that — up to fifteen
        # seconds of waiting, and every showing of the list would pay them for
        # the sake of one line of hint. run_step and run_friction call it right
        # before starting a session, where a refusal costs more than the delay;
        # here it does not.
        rnote="forget the conversation and begin it anew, from the same step"
      fi
    fi
    labels+=("$rtitle"$'\t'"$rnote")
    verbs+=(reset)
  fi

  # Abandoning comes last, behind a separator: an item that destroys work must
  # not stand right next to those the work is continued with. The same argument
  # by which it used to stand last in the top menu.
  labels+=($'\t')
  verbs+=(nothing)
  labels+=("Drop the feature (drop)"$'\t'"clear its traces here and on GitHub")
  verbs+=(drop)
  labels+=("Go back"$'\t'"")
  verbs+=(back)

  # The issue and the pull request as a line above the list. In the terminal
  # that is simply convenient: the list of actions on a feature has until now
  # named neither of them, even though half the items are about them.
  local head=""
  [[ -n "$issue" ]] && head+=" · issue #$issue"
  [[ -n "$pr" ]] && head+=" · PR #$pr"
  [[ -n "$head" ]] && say "${DIM}$slug$head${OFF}"

  # And in a messenger the feature's whole card is shown above this same list —
  # links, the step, the worktree, the session's state. There is nothing here to
  # assemble it with: half the card (whether the session is alive) is known to
  # the bot rather than the orchestrator. So we do not assemble it but name the
  # feature — from the name the bot builds the rest itself.
  export ASK_FEATURE="$slug"

  # A loop rather than recursion. The space bar toggles nothing in this list —
  # there is nothing to toggle — but nobody is stopped from pressing it, and the
  # previous version called feature_actions afresh: a frame on the stack and the
  # whole prologue over again, that is four state_get calls, git rev-list,
  # dev_pid and friction_count per press. Both neighbouring menus (cmd_menu,
  # actions_menu) spin a while in the same place.
  local choice rc
  while :; do
    choice="$(pick_list "$slug — what shall we do?" "${labels[@]}")"; rc=$?
    [[ "$rc" -eq 3 ]] || break
    PICK_LIST_START="$choice"
  done

  # The mark lives until the next question and is cleared with it — like the
  # accumulated context in ask_forget. Questions of their own follow: "delete all
  # this?", "merge main in?". The feature's card above them would be out of
  # place — they are not about the feature as a whole but about what the human is
  # confirming right now.
  #
  # In the terminal the question has already been asked, pick_list asked it: we
  # clear it at once. Without a terminal the question is still ahead — there the
  # mark is cleared right after ask.
  [[ "$rc" -eq 2 ]] || unset ASK_FEATURE


  if [[ "$rc" -eq 2 ]]; then
    # There is no terminal: the list as text, the choice as a number — the bot
    # will show that same thing as buttons. The items' names go to the channel,
    # so the buttons arrive labelled rather than as digits.
    local -a options=()
    local i=1 menu="" label
    for label in "${labels[@]}"; do
      # We do not take a separator into a numbered list: an empty item with a
      # number is an invitation to press into nowhere.
      [[ "$label" == $'\t' ]] && { i=$i; continue; }
      menu+="  $i)"$'\t'"$label"$'\n'
      options+=("$(cut -f1 <<< "$label")")
      i=$((i + 1))
    done
    echo ""
    echo "${BOLD}$slug — what shall we do?${OFF}"
    align_columns "$menu"
    echo ""
    ask "Which one? [1-$((i - 1))] " choice "pick:$((i - 1))" "${options[@]}"
    unset ASK_FEATURE
    # No answer, or an answer wide of the mark, is the same as "Go back": we
    # return a code rather than doing nothing silently. Whoever called knows
    # better whether there is anywhere to go back to.
    [[ "$choice" =~ ^[0-9]+$ ]] || { info "Not a number — nothing done."; return 10; }
    [[ "$choice" -ge 1 && "$choice" -lt "$i" ]] || { info "No such entry."; return 10; }
    # The number counts items without the separators, while verbs stores them
    # alongside the rest: we translate one into the other, skipping the
    # separators as the list skipped them.
    local seen=0 idx=0
    for idx in "${!labels[@]}"; do
      [[ "${labels[$idx]}" == $'\t' ]] && continue
      seen=$((seen + 1))
      [[ "$seen" -eq "$choice" ]] && break
    done
    choice="$idx"
  elif [[ "$rc" -ne 0 ]]; then
    # 1 means they left with a key. q and Esc mean the same as "Go back": the
    # human changed their mind and wants to go where they came from. We return
    # that as a code rather than an action — the caller decides, because "where
    # they came from" differs for each.
    return 10
  fi

  case "${verbs[$choice]}" in
    resume)   cmd_resume "$slug" ;;
    sync)     cmd_sync "$slug" ;;
    replan)   cmd_replan "$slug" ;;
    return)   cmd_return "$slug" ;;
    issue)    cmd_issue "$slug" ;;
    news)     cmd_news "$slug" ;;
    preview)  cmd_preview "$slug" ;;
    rollback) cmd_rollback "$slug" || true ;;
    dev)      cmd_dev "$slug" ;;
    friction) cmd_friction "$slug" ;;
    regression) cmd_regression "$slug" ;;
    regression-prod) cmd_regression "$slug" prod || true ;;
    reset)    cmd_reset "$slug" ;;
    done)     cmd_done "$slug" || true ;;
    drop)     cmd_abandon "$slug" ;;
    # Returning to the previous menu is not an action but the absence of one,
    # and there is nothing to carry out here. Whoever called us knows where to
    # return to: from the feature menu to the feature menu, from the picker to
    # the picker, and from a phone there is nowhere to return to at all, the list
    # is open on its own there.
    back|nothing) return 10 ;;
  esac
}

# Choosing a feature and then the actions on it. Needed where the feature has
# not been named yet: the main menu's fallback path, where there is no checkbox.
#
# Returning from the action list leads back here: this list is the "previous
# menu" for whoever came from it. Hence a loop rather than a single pass.
actions_menu() {
  local rows="$1"
  local -a slugs=() labels=()
  local slug wt step choice rc arc

  while IFS=$'\t' read -r slug wt step; do
    [[ -z "$slug" ]] && continue
    slugs+=("$slug")
    labels+=("$slug"$'\t'"$(step_label "$step" "$wt")")
  done <<< "$rows"

  local n="${#slugs[@]}"
  [[ "$n" -gt 0 ]] || { info "No features in progress."; return 0; }

  labels+=("Go back"$'\t'"")

  while :; do
    choice="$(pick_list "Which feature?" "${labels[@]}")"; rc=$?

    if [[ "$rc" -eq 2 ]]; then
      local -a options=()
      local i=1 menu=""
      for slug in "${slugs[@]}"; do
        menu+="  $i)"$'\t'"${labels[$((i - 1))]}"$'\n'
        options+=("$slug")
        i=$((i + 1))
      done
      menu+="  $i)"$'\t'"none, go back"$'\n'
      options+=("none, go back")
      echo ""
      echo "${BOLD}Which feature?${OFF}"
      align_columns "$menu"
      echo ""
      ask "Which one? [1-$i] " choice "pick:$i" "${options[@]}"
      [[ "$choice" =~ ^[0-9]+$ ]] || { info "Not a number — nothing done."; return 0; }
      choice=$((choice - 1))
      # Without a terminal there is nowhere to return to: there is nothing to
      # redraw the list with, and asking again means looping the conversation in
      # the messenger.
      [[ "$choice" -ge 0 && "$choice" -lt "$n" ]] || { info "Nothing done."; return 0; }
      feature_actions "${slugs[$choice]}"
      return 0
    elif [[ "$rc" -ne 0 ]]; then
      # 3 is the space bar: there is nothing to toggle here.
      [[ "$rc" -eq 3 ]] && { PICK_LIST_START="$choice"; continue; }
      # 1 means they left with a key: from here there is nowhere further up to
      # go.
      info "Nothing done."
      return 0
    fi

    # "Go back" as the last row is the way out of this list.
    [[ "$choice" -ge 0 && "$choice" -lt "$n" ]] || { info "Nothing done."; return 0; }

    PICK_LIST_START=0
    feature_actions "${slugs[$choice]}"; arc=$?
    # Not a "back" — the action took place, and the menu has done its job.
    [[ "$arc" -eq 10 ]] || return 0
    # A "back" comes here again, with the cursor on the feature we left.
    PICK_LIST_START="$choice"
  done
}
