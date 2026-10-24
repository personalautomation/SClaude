#!/usr/bin/env bash
#
# Choosing the issue a feature starts from.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- choosing an issue -------------------------------------------------------
#
# A feature's cycle starts either from a name thought up on the spot or from an
# open issue. We draw the list ourselves: one picture for the whole choice is
# cheaper than question after question, and it shows at once what is in progress
# at all.

# The owner/name of the repository the issues and pull requests belong to.
gh_repo() {
  git -C "${REPO:-.}" remote get-url origin 2>/dev/null \
    | sed -E -e 's|\.git$||' -e 's|^.*[:/]([^/]+/[^/]+)$|\1|'
}

# The repository's open issues, one line each:
#
#   <mine?>\t<number>\t<title>\t<labels, comma-separated>\t<open blockers>
#
# issue_list.py makes them: the bot's Mini App offers the same list.
fetch_issues() {
  command -v gh >/dev/null 2>&1 || return 1
  # -R rather than the current directory: the issues live in the feature's
  # repository, while sclaude is launched both from the main worktree and from a
  # feature's worktree.
  python3 "$(dirname "${BASH_SOURCE[0]}")/issue_list.py" rows "$(gh_repo)"
}

# One key. An arrow arrives as ESC [ A — we gather the tail and return a
# meaningful name; anything unrecognised is handed back as it is, and the caller
# silently ignores it. That way a change of keyboard layout, which sends an
# escape sequence of its own, cannot choose anything by mistake.
read_key() {
  local key rest
  IFS= read -rsn1 key < /dev/tty || return 1
  case "$key" in
    '')     echo "enter"; return 0 ;;
    $'\e')  ;;
    *)      printf '%s' "$key"; return 0 ;;
  esac
  IFS= read -rsn2 -t 0.05 rest < /dev/tty
  case "$rest" in
    '[A') echo "up" ;;
    '[B') echo "down" ;;
    '')   echo "esc" ;;
    # A longer tail — something like ^[[?1;2c from a change of layout: we read
    # off whatever is left so that it does not drop out on the next key, and say
    # nothing.
    *)    IFS= read -rsn8 -t 0.02 rest < /dev/tty; echo "skip" ;;
  esac
}

# Draws the list and returns the choice on one line:
#   manual                  — type a name by hand
#   issue<TAB><N><TAB><title>
# Empty output and exit code 1 mean the human declined.
pick_start() {
  local issues rows_n visible top=0 cur=0 drawn=0 key cols lines

  # The terminal is needed whole: with none there is nowhere to draw and nowhere
  # to read keys from. We look at /dev/tty rather than the descriptors:
  # pick_start is called from $( ), where stdout is a pipe whatever the terminal
  # may be.
  if ! ( exec < /dev/tty ) 2>/dev/null; then
    echo "manual"
    return 0
  fi

  issues="$(fetch_issues)" || issues=""
  if [[ -z "$issues" ]]; then
    # To stderr rather than through info: this function's return value is read
    # by $( ), and everything printed to stdout becomes part of it. Through info
    # the message went straight into choice — "Could not fetch…\nmanual" instead
    # of "manual" — case recognised no branch, and sclaude ended silently instead
    # of asking for the feature's name. A repository with no reachable gh issues
    # could not start a feature at all that way.
    command -v gh >/dev/null 2>&1 \
      && echo "${DIM}Could not fetch the issue list — starting the feature by name.${OFF}" >&2
    echo "manual"
    return 0
  fi

  mapfile -t ISSUE_ROWS <<< "$issues"
  rows_n=$(( ${#ISSUE_ROWS[@]} + 1 ))          # +1 for the "type a name" item

  # We ask the terminal itself for the size: COLUMNS and LINES are set only by
  # an interactive bash, and here we are already inside a command
  # substitution.
  read -r lines cols < <(stty size < /dev/tty 2>/dev/null || echo "24 80")
  # stty can be successful and meaningless at once: under a pty with no size
  # set it answers "0 0", and `${cols:-80}` does not catch that — zero is not an
  # empty string. The zero then spreads through the whole drawing: a line's width
  # goes negative, and every hint is trimmed to a single ellipsis. So we check
  # not for emptiness but for meaningfulness.
  [[ "$cols" =~ ^[0-9]+$ ]] && [[ "$cols" -ge 40 ]] || cols=80
  [[ "$lines" =~ ^[0-9]+$ ]] && [[ "$lines" -ge 10 ]] || lines=24
  PICKER_COLS="$cols"
  # -8 for the frame (blank lines, the hint, the shell's prompt) and another -2
  # for the block headings: they take up rows inside the window but are not
  # items.
  visible=$(( ${lines:-24} - 10 ))
  [[ "$visible" -lt 5 ]] && visible=5
  [[ "$visible" -gt "$rows_n" ]] && visible="$rows_n"

  while :; do
    # The erasing goes to the screen rather than stdout: stdout here goes to
    # the caller.
    [[ "$drawn" -gt 0 ]] && printf '\033[%dA\033[J' "$drawn" > /dev/tty
    drawn="$(draw_picker "$top" "$cur" "$visible")"
    key="$(read_key)" || key="esc"
    case "$key" in
      up)    [[ "$cur" -gt 0 ]] && cur=$((cur - 1)) ;;
      down)  [[ "$cur" -lt $((rows_n - 1)) ]] && cur=$((cur + 1)) ;;
      enter)
        printf '\033[%dA\033[J' "$drawn" > /dev/tty
        if [[ "$cur" -eq 0 ]]; then
          echo "manual"
        else
          local row="${ISSUE_ROWS[$((cur - 1))]}"
          printf 'issue\t%s\t%s\n' \
            "$(cut -f2 <<< "$row")" "$(cut -f3 <<< "$row")"
        fi
        return 0 ;;
      q|Q|й|Й|esc)
        printf '\033[%dA\033[J' "$drawn" > /dev/tty
        return 1 ;;
    esac
    # The cursor drags the window along with it.
    [[ "$cur" -lt "$top" ]] && top="$cur"
    [[ "$cur" -ge $((top + visible)) ]] && top=$((cur - visible + 1))
  done
}

# Prints the picture and returns the number of lines printed — the next redraw
# knows from it how much to erase. We count ourselves rather than guess: the
# lines are ours, and their number is known exactly.
#
# Python returns everything in one piece with the counter as the last line; bash
# cuts it off.
draw_picker() {
  local top="$1" cur="$2" visible="$3" out
  out="$(PICKER_ROWS="$(printf '%s\n' "${ISSUE_ROWS[@]}")" \
    python3 - "$top" "$cur" "$visible" "${PICKER_COLS:-80}" \
             "$BOLD" "$DIM" "$GREEN" "$OFF" <<'PYDRAW'
import os, sys
top, cur, visible, cols = (int(a) for a in sys.argv[1:5])
BOLD, DIM, GREEN, OFF = sys.argv[5:9]
rows = [l.split('\t') for l in os.environ['PICKER_ROWS'].splitlines() if l]

out, section = [''], None
for idx in range(top, min(top + visible, len(rows) + 1)):
    mark = GREEN + '▸' + OFF if idx == cur else ' '
    if idx == 0:
        text = 'type a feature name'
        out.append('  %s %s' % (mark, BOLD + text + OFF if idx == cur else text))
        continue
    mine, number, title, labels, blocked = (rows[idx - 1] + [''] * 5)[:5]
    # The blockers go before the labels: they are the one fact here that
    # changes whether to pick the issue at all.
    if blocked:
        labels = 'blocked by ' + blocked + (' · ' + labels if labels else '')
    want = 'assigned to me' if mine == '1' else 'other open issues'
    if want != section:
        section = want
        out.append('%s  ── %s %s%s'
                   % (DIM, want, '─' * max(0, cols - len(want) - 9), OFF))
    tail = '  ' + DIM + labels + OFF if labels else ''
    room = cols - 12 - (len(labels) + 2 if labels else 0)
    shown = title if len(title) <= room else title[:max(0, room - 1)] + '…'
    line = '#%-4s %s' % (number, shown)
    out.append('  %s %s%s'
               % (mark, BOLD + line + OFF if idx == cur else line, tail))
out.append('')
out.append(DIM + '  ↑↓ move · Enter open · q cancel' + OFF)
print('\n'.join(out))
print(len(out))
PYDRAW
)"
  # The last line is the counter, everything before it is the picture.
  printf '%s\n' "${out%$'\n'*}" > /dev/tty
  printf '%s' "${out##*$'\n'}"
}

# --- a general-purpose list --------------------------------------------------
#
# The same choosing with arrow keys, but over anything rather than issues: menu
# items, actions on a feature. Born from pick_start, this function repeats every
# one of its decisions — they were bought dearly, and each is in its right place
# here:
#
#   * we check the terminal in a subshell. A bare `: < /dev/tty 2>/dev/null`
#     prints "No such device or address" past the suppression when there is no
#     controlling terminal at all — that is under setsid, that is when launched
#     from the daemon;
#   * we draw to /dev/tty rather than stdout: the result is read through $( ),
#     and everything printed to stdout would become part of it;
#   * we ask stty for the size: COLUMNS and LINES are set only by an interactive
#     bash, and we are already inside a command substitution;
#   * we erase the previous picture by the number of lines the drawing returned.
#
# The items arrive as "label<TAB>hint" lines, one per item. Prints the chosen
# item's number counting from zero; returns 1 when the human leaves with q or
# Esc.
#
# Exit code 2 has a special role: there is no terminal at all, nowhere to draw
# and nowhere to read from. That is not a refusal by the human but an absence of
# the conditions for a conversation, and the caller is obliged to tell them
# apart — it will fall back to the numbered `ask`, with which the same choice is
# made from a phone. pick_start retreats to "manual" in exactly the same way.
PICK_LIST_ROWS=()
PICK_LIST_TITLE=""
# The caption below the list — the caller changes it when the list has keys of
# its own.
PICK_LIST_HINT=""

# The cursor to open on. The caller sets it when calling the list again — after
# toggling the checkbox — so that the row under the cursor stays the same.
# Without this every press of the space bar would throw the cursor back to the
# top, and setting the checkbox would mean walking down to it again first.
PICK_LIST_START=0

pick_list() {
  local title="$1"; shift
  local rows_n visible top=0 cur="${PICK_LIST_START:-0}" drawn=0 key cols lines

  if ! ( exec < /dev/tty ) 2>/dev/null; then
    return 2
  fi

  mapfile -t PICK_LIST_ROWS < <(printf '%s\n' "$@")
  rows_n="${#PICK_LIST_ROWS[@]}"
  [[ "$rows_n" -gt 0 ]] || return 1
  PICK_LIST_TITLE="$title"
  # A requested cursor applies once: the next call, unless it is asked for
  # again, starts at the top, as a new list should.
  PICK_LIST_START=0
  [[ "$cur" -ge "$rows_n" ]] && cur=$((rows_n - 1))
  [[ "$cur" -lt 0 ]] && cur=0
  # A requested cursor may also point at a separator — the caller does not think
  # about those. We move down to the first real row, and if there are only
  # separators below, upwards: the cursor has to stand on something regardless.
  while [[ "$cur" -lt $((rows_n - 1)) ]] \
     && [[ -z "${PICK_LIST_ROWS[$cur]//[[:space:]]/}" ]]; do
    cur=$((cur + 1))
  done
  while [[ "$cur" -gt 0 ]] && [[ -z "${PICK_LIST_ROWS[$cur]//[[:space:]]/}" ]]; do
    cur=$((cur - 1))
  done

  read -r lines cols < <(stty size < /dev/tty 2>/dev/null || echo "24 80")
  # stty can be successful and meaningless at once: under a pty with no size
  # set it answers "0 0", and `${cols:-80}` does not catch that — zero is not an
  # empty string. The zero then spreads through the whole drawing: a line's width
  # goes negative, and every hint is trimmed to a single ellipsis. So we check
  # not for emptiness but for meaningfulness.
  [[ "$cols" =~ ^[0-9]+$ ]] && [[ "$cols" -ge 40 ]] || cols=80
  [[ "$lines" =~ ^[0-9]+$ ]] && [[ "$lines" -ge 10 ]] || lines=24
  PICKER_COLS="$cols"
  # -8 for the frame: blank lines, the title, the hint and the shell's
  # prompt.
  visible=$(( ${lines:-24} - 8 ))
  [[ "$visible" -lt 5 ]] && visible=5
  [[ "$visible" -gt "$rows_n" ]] && visible="$rows_n"
  # We pull the window to the requested cursor: the row may lie below the first
  # screen, and without this it would stay past its edge. This cannot be computed
  # earlier — the window's size is only known now.
  [[ "$cur" -ge "$visible" ]] && top=$((cur - visible + 1))

  while :; do
    [[ "$drawn" -gt 0 ]] && printf '\033[%dA\033[J' "$drawn" > /dev/tty
    drawn="$(draw_list "$top" "$cur" "$visible")"
    key="$(read_key)" || key="esc"
    case "$key" in
      # We step over a separator rather than onto it. The cursor does not draw
      # on one — a blank row has nothing to highlight — so stopping on it looks
      # like the cursor vanishing: the list freezes, the arrow key is pressed,
      # nothing happens. That is exactly how "drop the feature" came to look
      # unreachable — it stands right after a separator.
      #
      # We step in the direction we were going and do not go past the edge: a
      # separator as the last row leads nowhere.
      up)
        while [[ "$cur" -gt 0 ]]; do
          cur=$((cur - 1))
          [[ -n "${PICK_LIST_ROWS[$cur]//[[:space:]]/}" ]] && break
        done ;;
      down)
        while [[ "$cur" -lt $((rows_n - 1)) ]]; do
          cur=$((cur + 1))
          [[ -n "${PICK_LIST_ROWS[$cur]//[[:space:]]/}" ]] && break
        done ;;
      enter)
        printf '\033[%dA\033[J' "$drawn" > /dev/tty
        echo "$cur"
        return 0 ;;
      ' ')
        # We hand the space bar to the caller as a choice of item, but with
        # exit code 3: the list itself does not know what stands behind an item
        # and has nothing to toggle. A menu whose last row is a checkbox toggles
        # it on this code and calls pick_list again, now with a new label. The
        # separation is the same as everywhere here: the drawing apart, the
        # meaning of what is drawn apart.
        printf '\033[%dA\033[J' "$drawn" > /dev/tty
        echo "$cur"
        return 3 ;;
      q|Q|й|Й|esc)
        printf '\033[%dA\033[J' "$drawn" > /dev/tty
        return 1 ;;
    esac
    [[ "$cur" -lt "$top" ]] && top="$cur"
    [[ "$cur" -ge $((top + visible)) ]] && top=$((cur - visible + 1))
  done
}

# Drawing the general-purpose list. Like draw_picker, it prints the picture to
# /dev/tty and returns the number of its lines.
draw_list() {
  local top="$1" cur="$2" visible="$3" out
  out="$(PICK_ROWS="$(printf '%s\n' "${PICK_LIST_ROWS[@]}")" \
         PICK_TITLE="$PICK_LIST_TITLE" \
         PICK_HINT="${PICK_LIST_HINT:-  ↑↓ move · Enter open · q cancel}" \
    python3 - "$top" "$cur" "$visible" "${PICKER_COLS:-80}" \
             "$BOLD" "$DIM" "$GREEN" "$OFF" <<'PYLIST'
import os, sys
top, cur, visible, cols = (int(a) for a in sys.argv[1:5])
BOLD, DIM, GREEN, OFF = sys.argv[5:9]
rows = [l.split('\t') for l in os.environ['PICK_ROWS'].splitlines() if l]

out = ['']
title = os.environ.get('PICK_TITLE', '')
if title:
    out.append('  ' + BOLD + title + OFF)

# We align the labels by the longest: the hints then stand in a column, and the
# list reads as a table rather than as ragged text. We measure the width across
# all the items rather than the visible ones — otherwise the column would shift
# while scrolling.
width = max((len(r[0]) for r in rows), default=0)

for idx in range(top, min(top + visible, len(rows))):
    row = rows[idx]
    label = row[0]
    hint = row[1] if len(row) > 1 else ''
    mark = GREEN + '▸' + OFF if idx == cur else ' '
    # An empty label is a separator: a blank line instead of an item.
    if not label and not hint:
        out.append('')
        continue
    shown = BOLD + label + OFF if idx == cur else label
    pad = ' ' * max(0, width - len(label))
    line = '  %s %s%s' % (mark, shown, pad)
    if hint:
        room = cols - width - 8
        clipped = hint if len(hint) <= room else hint[:max(0, room - 1)] + '…'
        line += '  ' + DIM + clipped + OFF
    out.append(line.rstrip())

out.append('')
out.append(DIM + os.environ.get('PICK_HINT', '') + OFF)
print('\n'.join(out))
print(len(out))
PYLIST
)"
  printf '%s\n' "${out%$'\n'*}" > /dev/tty
  printf '%s' "${out##*$'\n'}"
}
