#!/usr/bin/env bash
#
# `sclaude status` and the menu `sclaude` opens with no arguments.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

cmd_status() {
  require_repo
  local rows; rows="$(list_features)"
  if [[ -z "$rows" ]]; then
    echo "No features in progress. Start one with: $SELF new"
  else
    local table="FEATURE"$'\t'"STEP"$'\t'"WORKTREE"$'\n'
    while IFS=$'\t' read -r slug wt step; do
      table+="$slug"$'\t'"$(step_label "$step" "$wt")"$'\t'"$wt"$'\n'
    done <<< "$rows"
    align_columns "$table"
    echo ""
  fi
  review_branches
  prod_drift_report
}

# We align with python rather than printf: bash counts %-24s in bytes, and a
# non-ASCII step name is twice as long in bytes as on the screen — the columns
# drift apart.
align_columns() {
  # We assemble the output rather than printing at once: this table is the items
  # the human is about to choose from, and on a phone it is needed exactly as
  # much as in the terminal. Without it the choice buttons arrive as unlabelled
  # digits.
  local out
  out="$(printf '%s' "$1" | python3 -c '
import sys
rows = [line.split("\t") for line in sys.stdin.read().splitlines() if line]
if not rows:
    sys.exit()
# The last column is not aligned - it has nothing to catch up with on the right.
# The rows can be of different lengths: the "new feature" item in the menu is
# shorter than the rest.
width = max(len(row) for row in rows)
widths = [max((len(row[i]) for row in rows if len(row) > i + 1), default=0)
          for i in range(width - 1)]
for row in rows:
    head = "  ".join(c.ljust(w) for c, w in zip(row[:-1], widths))
    print((head + "  " + row[-1]).rstrip() if head else row[-1])
')"
  [[ -n "$out" ]] || return 0
  say "$out"
}

# The main menu: the features in progress, "new feature" and the checkbox below
# them.
#
# The choice is made with arrow keys, by the same pick_list that draws the issue
# list. The numbered question stayed as a fallback path and comes into play by
# itself when there is no terminal: that is how the menu opens from a phone,
# where arrow keys do not exist and the bot draws the buttons.
#
# The checkbox is the last row, and it changes the meaning of Enter rather than
# the list of items. Cleared (the usual state), Enter on a feature continues its
# current step, exactly as before. Set, Enter opens the list of actions on that
# feature.
#
# That is how "drop the feature" left the top list. An action among features was
# doubly out of place: first, it is not a feature; second, every subsequent
# action (sync with main, link an issue, preview) would have to be added here
# too, and the menu would drown. Now they all live behind the checkbox, and the
# top list stays what it was — a list of features.
#
# The checkbox lives for this one function. It is deliberately not put on disk:
# the same key must not do different things depending on what the human pressed a
# week ago.
cmd_menu() {
  require_repo
  local rows; rows="$(list_features)"

  # We sort the branches out before the choice: a clean-up is done before the
  # work rather than in the middle of it.
  review_branches
  # After the branches, which fetched origin: what main holds that production
  # does not, and what main holds that origin does not.
  prod_drift_report

  # And an interrupted epilogue on the same occasion and in the same place.
  # Necessarily BEFORE the "no features" branch: a closed feature has left the
  # list, and an empty menu is precisely the most frequent case where an epilogue
  # is waiting.
  offer_epilogues

  # Nothing to continue means we start a new one. There is nothing to ask here:
  # whoever launched sclaude has already answered by launching it, and declining
  # is possible in the choice itself, with the q key.
  if [[ -z "$rows" ]]; then
    echo ""
    info "No features in progress."
    # The menu with its `config` row is skipped, so the picker carries it.
    # Local rather than a prefix, which would export it to every process the
    # feature's start launches.
    local PICK_START_CONFIG=1
    start_feature
    return 0
  fi

  local -a slugs=() labels=() issues=()
  local slug wt step issue
  while IFS=$'\t' read -r slug wt step; do
    [[ -z "$slug" ]] && continue
    issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue 2>/dev/null)" || issue=""
    [[ "$issue" =~ ^[0-9]+$ ]] && issues+=("$issue")
  done <<< "$rows"

  # A feature whose issue is still blocked says so next to its step: its plan
  # leans on work that has not landed, and that is worth seeing before choosing
  # which one to continue. One request for all of them, after the list is read.
  local -A blocked=()
  local number by
  while IFS=$'\t' read -r number by; do
    [[ -n "$number" ]] && blocked[$number]="$by"
  done <<< "$(features_blockers "${issues[@]}")"

  local hint
  while IFS=$'\t' read -r slug wt step; do
    [[ -z "$slug" ]] && continue
    slugs+=("$slug")
    hint="$(step_label "$step" "$wt")"
    issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue 2>/dev/null)" || issue=""
    [[ -n "$issue" && -n "${blocked[$issue]:-}" ]] && hint+=" · blocked by ${blocked[$issue]}"
    labels+=("$slug"$'\t'"$hint")
  done <<< "$rows"

  local n="${#slugs[@]}"
  local extra=0            # the checkbox's state: 0 cleared, 1 set
  local choice rc

  while :; do
    local -a items=("${labels[@]}")
    items+=("new feature"$'\t'"start one from an issue or a name")
    items+=($'\t')        # a blank line, the separator before the checkbox
    if [[ "$extra" -eq 1 ]]; then
      items+=("[x] show actions after choosing"$'\t'"Enter on a feature opens its actions")
    else
      items+=("[ ] show actions after choosing"$'\t'"Enter on a feature continues it")
    fi
    # The project's settings, last: visited rarely, and never in the way of
    # the feature the menu is mostly opened for.
    items+=("config"$'\t'"the project's .sclaude/config.json, explained")

    PICK_LIST_HINT="  ↑↓ move · Space toggle · Enter open · q cancel"
    choice="$(pick_list "Features in progress:" "${items[@]}")"; rc=$?
    PICK_LIST_HINT=""

    case "$rc" in
      1) info "Cancelled."; return 0 ;;
      2) break ;;          # no terminal — we leave for the numbered question
      3)
        # The space bar. We toggle only on the checkbox itself: on a feature it
        # means nothing, and a silent toggle from somebody else's row would be
        # confusing.
        [[ "$choice" -eq $((n + 2)) ]] && extra=$((1 - extra))
        # We come back where we stood: otherwise setting the checkbox would mean
        # walking down to it again first, and every press would throw us back to
        # the top.
        PICK_LIST_START="$choice"
        continue ;;
    esac

    # Enter. Something of its own opens next, and the requested cursor has
    # nothing to do with it: it is about this picture rather than the next one.
    # Without clearing it, the action list would open with the cursor on a row
    # nobody chose in it.
    PICK_LIST_START=0

    # The items come in the same order they were assembled in above.
    if [[ "$choice" -lt "$n" ]]; then
      if [[ "$extra" -eq 1 ]]; then
        # Exit code 10 is "back": the human chose "Go back" or left with a key.
        # We come back here, to the feature list, and put the cursor on the
        # feature they left: a return to a menu where everything has been reset
        # is not a return. The checkbox stays set in doing so, otherwise the next
        # Enter would behave differently from the previous one.
        local arc
        feature_actions "${slugs[$choice]}"; arc=$?
        [[ "$arc" -eq 10 ]] || return 0
        PICK_LIST_START="$choice"
        continue
      else
        cmd_resume "${slugs[$choice]}"
        return 0
      fi
    elif [[ "$choice" -eq "$n" ]]; then
      start_feature
      return 0
    elif [[ "$choice" -eq $((n + 3)) ]]; then
      cmd_config
      PICK_LIST_START="$choice"
      continue
    elif [[ "$choice" -eq $((n + 2)) ]]; then
      # Enter on the checkbox toggles it — the second natural key for the same
      # action. It destroys nothing, and so it does not ask.
      extra=$((1 - extra))
      PICK_LIST_START="$choice"
      continue
    fi
    # A separator is an item without meaning; Enter on it does nothing, but
    # there is no reason to lose the cursor either.
    PICK_LIST_START="$choice"
  done

  # The fallback path: there is no terminal. We print the list as text and ask
  # for the choice as a number — the bot will see that same thing as buttons.
  # There is no checkbox here: on a phone there is nothing to toggle it with, and
  # a button of its own opens the actions on a feature.
  echo ""
  echo "${BOLD}Features in progress:${OFF}"
  local -a options=()
  local i=1 menu=""
  for slug in "${slugs[@]}"; do
    menu+="  $i)"$'\t'"${labels[$((i - 1))]}"$'\n'
    options+=("$slug")
    i=$((i + 1))
  done
  menu+="  $i)"$'\t'"new feature"$'\n'
  options+=("new feature")
  local acts=$((i + 1)) conf=$((i + 2))
  menu+="  $acts)"$'\t'"actions for a feature"$'\n'
  options+=("actions for a feature")
  menu+="  $conf)"$'\t'"config"$'\n'
  options+=("config")
  align_columns "$menu"

  echo ""
  ask "What are we doing? [1-$conf] " choice "pick:$conf" "${options[@]}"
  [[ "$choice" =~ ^[0-9]+$ ]] || die "a number, please"
  if [[ "$choice" -eq "$conf" ]]; then
    cmd_config
  elif [[ "$choice" -eq "$acts" ]]; then
    actions_menu "$rows"
  elif [[ "$choice" -eq "$i" ]]; then
    start_feature
  elif [[ "$choice" -ge 1 && "$choice" -lt "$i" ]]; then
    cmd_resume "${slugs[$((choice - 1))]}"
  else
    die "no such entry: $choice"
  fi
}
