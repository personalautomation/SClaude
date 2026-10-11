#!/usr/bin/env bash
#
# The deferred friction, and its monthly review.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# A friction review decides each entry: lift the restriction, or keep it as a
# deliberate ban. Some entries are neither — one feature's worth of evidence
# is not enough to call them, and the rules sessions propose for a project's
# CLAUDE.md are of that kind too. Decided one at a time, after the session
# that met them, such things were either applied on one data point or lost in
# a report nobody answered. So the reviews put them off into one permanent
# file, and once a month the file is read as a whole: a class that came back
# ten times is a different decision from one seen once.
#
# The file is local state, outside any repository. It used to live in
# instruments as sclaude/friction-deferred.tsv, committed and pushed with the
# orchestrator — and every entry describes a project: its pull requests, its
# files, its infrastructure. instruments is public; the projects need not be.
# One file still serves every project, so a class is counted across all of
# them.
#
# The month is counted from the `# last reviewed:` line the review writes into
# the file. No timer starts the review: it is a conversation, and a
# conversation needs a person at a terminal. sclaude offers it when it is
# opened and the month is up.

DEFERRED_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/sclaude/friction-deferred.tsv"
DEFERRED_DAYS=30

# Creates the file with its header if it is not there yet. Silent; returns 1
# when it could not.
deferred_ensure() {
  [[ -f "$DEFERRED_FILE" ]] && return 0
  mkdir -p "$(dirname "$DEFERRED_FILE")" 2>/dev/null || return 1
  cat > "$DEFERRED_FILE" 2>/dev/null <<'HEADER' || return 1
# Friction that was neither lifted nor kept as a deliberate ban, but put off —
# and the rules sessions proposed for a project's CLAUDE.md. Collected here by
# the friction reviews, and reviewed together once a month (`sclaude deferred`),
# where how often a class comes back is what decides it.
#
# One entry per line, tab-separated:
#
#   date  project  feature  step  class  what happened, or the proposed rule
#
# `class` is a short kebab-case name for the problem. An entry that is the same
# problem as one above reuses its class, so the monthly review can count them.
#
# last reviewed: never
HEADER
}

# Whether the monthly review is due: prints "<entries> <since>" and returns 0
# when it is, returns 1 otherwise. <since> is the last review's date, or the
# first entry's when there was none.
deferred_due() {
  [[ -s "$DEFERRED_FILE" ]] || return 1
  python3 - "$DEFERRED_FILE" "$DEFERRED_DAYS" <<'PY'
import datetime, re, sys
path, days = sys.argv[1], int(sys.argv[2])
entries, reviewed, first = 0, None, None
for line in open(path, encoding="utf-8"):
    found = re.match(r"#\s*last reviewed:\s*(\d{4}-\d{2}-\d{2})", line)
    if found:
        reviewed = found.group(1)
        continue
    if not line.strip() or line.startswith("#"):
        continue
    entries += 1
    stamp = line.split("\t", 1)[0].strip()[:10]
    if re.match(r"\d{4}-\d{2}-\d{2}$", stamp) and (first is None or stamp < first):
        first = stamp
since = reviewed or first
if not entries or not since:
    sys.exit(1)
age = (datetime.date.today() - datetime.date.fromisoformat(since)).days
if age < days:
    sys.exit(1)
print("%d %s" % (entries, since))
PY
}

# Offered when sclaude is opened: once a month, if anything waits.
deferred_offer() {
  local due entries since answer
  due="$(deferred_due 2>/dev/null)" || return 0
  read -r entries since <<< "$due"
  echo ""
  say "${BOLD}The deferred friction is due for its monthly review:${OFF} $entries entr$([[ "$entries" == 1 ]] && echo y || echo ies) since $since."
  info "  How often each class came back decides it: lift it, ban it for good, write the rule, or keep waiting."
  ask "${BOLD}Review it now? [y/n] ${OFF}" answer yn
  if is_yes "$answer"; then
    cmd_deferred
  else
    info "  Later, with: $SELF deferred"
  fi
}

# The review itself: a session in instruments, in plan mode, over the file.
cmd_deferred() {
  local prompt session before after done_file
  [[ -f "$PROMPTS/friction-deferred.md" ]] || die "no prompt for the deferred review"
  if [[ ! -s "$DEFERRED_FILE" ]] || ! grep -qvE '^(#|[[:space:]]*$)' "$DEFERRED_FILE"; then
    info "Nothing deferred — $DEFERRED_FILE has no entries."
    return 0
  fi
  # The same net as run_friction: a non-maintainer's review must not commit
  # the orchestrator to main.
  if ! developer_is_maintainer \
     && [[ "$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null)" == "main" ]]; then
    warn "  The review would commit the orchestrator to main, and MAINTAINERS"
    warn "  does not list you. Switch $INSTRUMENTS to dev/<your name> and run it"
    warn "  again: $SELF deferred"
    return 1
  fi
  local repo; repo="$(main_repo 2>/dev/null || true)"
  done_file="${TMPDIR:-/tmp}/sclaude-deferred.done"
  prompt="$(sed -e "s|<file>|$DEFERRED_FILE|g" -e "s|<repo>|${repo:-the project repository}|g" \
    -e "s|<done-marker>|$done_file|g" -e "s|<today>|$(date +%F)|g" \
    "$PROMPTS/friction-deferred.md")"
  # It edits and commits the instruments tree, so it waits in the friction
  # queue like any friction review (see run_friction).
  FRICTION_LOCK=""
  FRICTION_LOCK_FILE="$(git -C "$INSTRUMENTS" rev-parse --path-format=absolute \
    --git-common-dir 2>/dev/null)/sclaude-friction.lock"
  if declare -F lock_take >/dev/null && [[ "$FRICTION_LOCK_FILE" == /* ]]; then
    lock_take FRICTION_LOCK "$FRICTION_LOCK_FILE" "the monthly deferred review" "a friction review"
  fi
  session="$(new_session_id)"
  before="$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null || true)"

  echo ""
  echo "${BOLD}${BLUE}── the deferred friction · monthly review ──${OFF}"
  info "   opus / medium / plan · $INSTRUMENTS"
  echo ""
  local -a dirs=(--add-dir "$HOME/.claude/projects" --add-dir "$(dirname "$DEFERRED_FILE")")
  [[ -n "$repo" ]] && dirs+=(--add-dir "$repo")
  session_watch_start "" "$session" "$done_file" "$INSTRUMENTS" deferred
  ( cd "$INSTRUMENTS" && claude_launch --session-id "$session" --model opus --effort medium \
      --permission-mode plan "${dirs[@]}" -n "friction/deferred" "$prompt" )
  session_watch_stop
  session_closed "$done_file" "$INSTRUMENTS" "$session" \
    "The deferred review reported its work done, and sclaude closed it." || true

  after="$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null || true)"
  if [[ -n "$before" && -n "$after" && "$before" != "$after" ]]; then
    push_instruments
  fi
  friction_unlock
}
