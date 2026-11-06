#!/usr/bin/env bash
#
# The project's .sclaude/config.json as a screen: `sclaude config`, and the
# last row of the menu.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Every section is listed with what it holds now and what it is for, in the
# words of sclaude/config.example.json (config_menu.py reads them from there).
# A section with fixed choices — `review`, `qa`, `merge`, `sleep_mode`,
# `metricsTeam` — is set here; the rest are structures the screen shows and
# the person edits in the file, which the last row opens.
#
# The committed file is what the project recommends. A choice made here is
# this machine's: it goes to .sclaude/local/config.json beside it, outside
# git, and wins over the committed one (set_value in config_menu.py,
# project_get in project.sh) — so main's tree stays what origin holds and
# production is not stopped by a person's taste (prod_main_unready). The
# structures are still edited in the committed file, the last row's.

# The config's path in the main checkout: a value set here is the project's,
# not one feature's.
config_file() {
  echo "$REPO/.sclaude/config.json"
}

cmd_config() {
  require_repo
  local file example choice rc key
  file="$(config_file)"
  example="$INSTRUMENTS/sclaude/config.example.json"

  # `sclaude config set <key> <value>`: the same as choosing it on the screen,
  # for the bot's menu, which shows the screen itself.
  if [[ "${1:-}" == "set" ]]; then
    [[ $# -eq 3 ]] || die "usage: $SELF config set <key> <value>"
    config_set "$file" "$2" "$3"
    return
  fi

  while :; do
    local -a keys=() items=()
    local row
    while IFS= read -r row; do
      [[ -n "$row" ]] || continue
      keys+=("${row%%$'\t'*}")
      items+=("$row")
    done < <(python3 "$LIB/core/config_menu.py" rows "$file" "$example" 2>/dev/null)
    items+=($'\t')
    items+=("edit the file"$'\t'"${file#"$REPO"/} in ${EDITOR:-nano}")

    PICK_LIST_HINT="  ↑↓ move · Enter open · q back"
    choice="$(pick_list "Project config — ${file#"$REPO"/}:" "${items[@]}")"; rc=$?
    PICK_LIST_HINT=""
    case "$rc" in
      1) return 0 ;;
      2)
        # No terminal: the screen as text. Setting a value takes a choice the
        # numbered ask could make, but nothing here is urgent enough to need it
        # from a phone.
        echo ""
        echo "${BOLD}Project config — $file${OFF}"
        align_columns "$(printf '  %s\n' "${items[@]::${#keys[@]}}")"
        return 0 ;;
      3) PICK_LIST_START="$choice"; continue ;;
    esac
    PICK_LIST_START="$choice"

    if [[ "$choice" -lt "${#keys[@]}" ]]; then
      config_section "$file" "$example" "${keys[$choice]}"
    elif [[ "$choice" -eq $(( ${#keys[@]} + 1 )) ]]; then
      "${EDITOR:-nano}" "$file" < /dev/tty > /dev/tty
    fi
  done
}

# One section: its explanation and value, and its choices when it has them.
#
#   config_section <file> <example> <key>
config_section() {
  local file="$1" example="$2" key="$3" choice rc now
  local -a values=() items=()
  local value meaning
  while IFS=$'\t' read -r value meaning; do
    [[ -n "$value" ]] || continue
    values+=("$value")
    items+=("$value"$'\t'"$meaning")
  done < <(python3 "$LIB/core/config_menu.py" choices "$key")

  echo ""
  echo "${BOLD}$key${OFF}"
  python3 "$LIB/core/config_menu.py" show "$file" "$example" "$key" | fold -s -w "$(tput cols 2>/dev/null || echo 80)"
  echo ""

  if [[ "${#values[@]}" -eq 0 ]]; then
    info "  Edited in the file: the last row of the list opens it."
    config_pause
    return 0
  fi

  now="$(project_get "$key" 2>/dev/null || python3 "$LIB/core/config_menu.py" default "$key")"
  local start=0 i
  for i in "${!values[@]}"; do
    [[ "${values[$i]}" == "$now" ]] && start="$i"
  done
  PICK_LIST_START="$start"
  PICK_LIST_HINT="  ↑↓ move · Enter set · q leave as it is"
  choice="$(pick_list "$key:" "${items[@]}")"; rc=$?
  PICK_LIST_HINT=""
  PICK_LIST_START=0
  [[ "$rc" -eq 0 ]] || return 0
  [[ "${values[$choice]}" == "$now" ]] && return 0

  config_set "$file" "$key" "${values[$choice]}" || true
  config_pause
}

# Write one value with fixed choices, and do what it implies.
#
#   config_set <file> <key> <value>
config_set() {
  local file="$1" key="$2" value="$3"
  # Hidden from git before the local file is made: on a product no feature
  # has started in yet, nothing else has, and a `git add -A` in main would
  # publish this machine's choice to the team.
  scratch_hide "$REPO"
  if python3 "$LIB/core/config_menu.py" set "$file" "$key" "$value"; then
    say "${GREEN}✓ $key: $value${OFF} — on this machine"
    if [[ "$value" == "$(python3 "$LIB/core/config_menu.py" mine "$file" "$key" 2>/dev/null)" ]]; then
      info "  In ${file%/config.json}/local/config.json, outside git; the project"
      info "  recommends $(python3 "$LIB/core/config_menu.py" recommended "$file" "$key") (${file#"$REPO"/})."
    else
      info "  That is what the project recommends (${file#"$REPO"/}): nothing of this machine's own is left."
    fi
    if [[ "$key" == "review" ]]; then review_actions_sync "$REPO" "$value"; fi
  else
    warn "  Not changed."
    return 1
  fi
}

# Wait for Enter before the list is drawn over what was just printed.
config_pause() {
  local _
  read -rsp "  Enter to go back" _ < /dev/tty 2>/dev/null || true
  echo ""
}
