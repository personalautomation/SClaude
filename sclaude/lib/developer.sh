#!/usr/bin/env bash
#
# Which person is running this, and whether they maintain the orchestrator.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# sclaude was written for one person at one machine, and that showed as an
# absence rather than an assumption: nothing anywhere asked who was at the
# keyboard. Everything was keyed by the feature or by the repository. That holds
# only while nobody shares anything — and a small team shares a database, a
# preview deployment and this repository.
#
# environment.sh does not answer this. It says which database; two people on
# the same shared database get the same answer from it and different answers
# from here.
#
#   $SCLAUDE_DEV         explicit, and beats everything.
#   git sclaude.developer
#                        explicit too, and seen by every process: a variable
#                        set in ~/.profile is not, so systemd units and the
#                        bot (which runs `sclaude status`, the watcher
#                        `sclaude _handoff`) named somebody else — with a
#                        noreply address, a number and a login.
#   git user.email       its local part. Already set on every machine that
#                        commits, so nothing new has to be configured.
#   nothing              an empty name, which is not an error.
#
# An empty name is today's behaviour exactly: no prefixes, no author field, the
# friction review on the current branch. Same principle as project.sh — what is
# absent is simply not done.
#
# Not cached. Callers take the name through $( ), and a command substitution is
# a subshell: an assignment made there never reaches the caller, so a cache
# would be refilled on every call anyway. `git config` costs a few milliseconds.

# The raw address, from the orchestrator's own repository when it is known, so
# a per-repository identity set there wins over the global one.
developer_email() {
  if [[ -n "${INSTRUMENTS:-}" && -d "$INSTRUMENTS" ]]; then
    git -C "$INSTRUMENTS" config user.email 2>/dev/null || true
  else
    git config user.email 2>/dev/null || true
  fi
}

# Reduces a name to what survives everywhere it is used: an email address
# (pwtest-<dev>-…@example.com), a git branch (dev/<dev>) and a JSON field. A dot
# or a slash from an address breaks the first two, so this is not cosmetic.
developer_sanitize() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9-]/-/g' -e 's/--*/-/g' -e 's/^-//' -e 's/-$//'
}

# The configured name, from the orchestrator's repository first, like the
# address: `git config --global sclaude.developer <name>` is the usual way.
developer_configured() {
  if [[ -n "${INSTRUMENTS:-}" && -d "$INSTRUMENTS" ]]; then
    git -C "$INSTRUMENTS" config sclaude.developer 2>/dev/null || true
  else
    git config sclaude.developer 2>/dev/null || true
  fi
}

# The name, or nothing.
developer_name() {
  local raw="${SCLAUDE_DEV:-}"
  [[ -n "$raw" ]] || raw="$(developer_configured)"
  if [[ -z "$raw" ]]; then
    raw="$(developer_email)"
    raw="${raw%%@*}"
  fi
  developer_sanitize "$raw"
}

# 0 when this person maintains the product: their git address is in
# `maintainers` in the product's .sclaude/config.json. The product's own address, from
# the product's repository, since that is the identity its commits carry. The
# same rule as MAINTAINERS for the orchestrator: no list, or an empty one, and
# everybody maintains it, which is what a product with one developer wants.
#
#   product_maintainer [root]   the current repository without one
#
# The list is read from main (envs.main_config), not from the tree: the tree
# is a session's to edit, and a session guarded by --team could write itself
# into `maintainers`, or empty the list, and the sessions after it would get
# no guard. A change to the list counts once it has merged.
# The answer is kept for this process, by root: a friction review asked it four
# times on the way in, a git process and two python ones each time.
declare -gA PRODUCT_MAINTAINER_SEEN=()
product_maintainer() {
  local root="${1:-${REPO:-.}}"
  if [[ -n "${PRODUCT_MAINTAINER_SEEN[$root]:-}" ]]; then
    return "${PRODUCT_MAINTAINER_SEEN[$root]}"
  fi
  local rc_
  product_maintainer_ask "$root"; rc_=$?
  PRODUCT_MAINTAINER_SEEN[$root]="$rc_"
  return "$rc_"
}

product_maintainer_ask() {
  local root="$1" email content rc
  content="$(python3 "${LIB:-$(dirname "${BASH_SOURCE[0]}")}/envs.py" main-config "$root" "$root" 2>/dev/null)"
  rc=$?
  # No config anywhere: everybody. One that cannot be read says nothing about
  # who maintains the product, and "everybody" is the answer that drops the
  # team guard: a trailing comma made every developer a maintainer. Nobody,
  # then, and said.
  [[ "$rc" -eq 3 ]] && return 0
  if [[ "$rc" -ne 0 ]]; then
    warn "  $root/.sclaude/config.json cannot be read; nobody counts as its maintainer" >&2
    return 1
  fi
  email="$(git -C "$root" config user.email 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  printf '%s' "$content" | python3 -c '
import json, sys
listed = json.load(sys.stdin).get("maintainers")
if not isinstance(listed, list) or not listed:
    sys.exit(0)
sys.exit(0 if sys.argv[1] and sys.argv[1] in [str(m).strip().lower() for m in listed] else 1)
' "$email"
}

# Where this person's sclaude rules for the product go: the team's folder for a
# maintainer, their own under people/ for everybody else.
#
#   product_rules_dir [root]
product_rules_dir() {
  local root="${1:-${REPO:-.}}" name
  if product_maintainer "$root"; then
    echo "$root/.sclaude/team"
  else
    name="$(developer_name)"
    echo "$root/.sclaude/people/${name:-unknown}"
  fi
}

# 0 when this person may commit the orchestrator straight to main.
#
# MAINTAINERS at the repository root lists addresses, one per line, `#` for
# comments. With no file at all everybody is a maintainer — a copy used by one
# person has nobody to be protected from. With the file present, an unknown or
# empty address is not a maintainer: guessing yes would put a stranger's
# friction fix on the main branch of everybody's orchestrator.
developer_is_maintainer() {
  local file="${INSTRUMENTS:-.}/MAINTAINERS" email
  [[ -f "$file" ]] || return 0
  email="$(developer_email | tr '[:upper:]' '[:lower:]')"
  [[ -n "$email" ]] || return 1
  sed -e 's/#.*//' -e 's/[[:space:]]//g' "$file" | tr '[:upper:]' '[:lower:]' \
    | grep -qxF -- "$email"
}

# --- what this machine lets sclaude do with the network -----------------------
#
# Two settings of the machine, not of a product, kept in the git config of
# sclaude's checkout beside sclaude.developer: install.sh asks them, and a
# worktree of the checkout (a workshop) reads the same file.
#
#   sclaude.update      auto     every sclaude start takes sclaude's main
#                       notify   a start says what main has; `sclaude update` takes it
#                       off      sclaude never fetches itself
#   sclaude.contribute  send     what a session fixed in sclaude goes out unasked
#                       ask      it is shown, and goes out on the person's yes
#                       off      no session changes sclaude here at all
#   sclaude.leaks       ask      a change that may name the product is shown,
#                                and goes out on the person's yes
#                       auto     it is shown, and goes out without the question
#                       off      it never goes out; a session rewords it
#
# Unset, or set to a word not listed: `ask`, for both. For the update that
# means the question itself, at the next start with a terminal
# (update_mode_choose); for the contribution, the question at each send.
# Coupled: install.sh writes these words, tests/install.py and
# tests/sync.py / tests/workshop.py read both sides.
UPDATE_MODES="auto notify off"
CONTRIBUTE_MODES="send ask off"
LEAKS_MODES="ask auto off"

# The raw value, lower-cased, or nothing.
#
#   sclaude_setting <update|contribute>
sclaude_setting() {
  local v
  if [[ -n "${INSTRUMENTS:-}" && -d "$INSTRUMENTS" ]]; then
    v="$(git -C "$INSTRUMENTS" config "sclaude.$1" 2>/dev/null)"
  else
    v="$(git config "sclaude.$1" 2>/dev/null)"
  fi
  printf '%s' "$v" | tr '[:upper:]' '[:lower:]'
}

# auto, notify, off, or ask when nothing valid is set.
update_mode() {
  local v; v="$(sclaude_setting update)"
  [[ -n "$v" && " $UPDATE_MODES " == *" $v "* ]] && echo "$v" || echo ask
}

# send, ask or off; ask when nothing valid is set.
contribute_mode() {
  local v; v="$(sclaude_setting contribute)"
  [[ -n "$v" && " $CONTRIBUTE_MODES " == *" $v "* ]] && echo "$v" || echo ask
}

# ask, auto or off; ask when nothing valid is set.
leaks_mode() {
  local v; v="$(sclaude_setting leaks)"
  [[ -n "$v" && " $LEAKS_MODES " == *" $v "* ]] && echo "$v" || echo ask
}

# What each word means, for the question at install and at a start.
update_modes_explain() {
  cat <<'TXT'
  How should sclaude update itself from its public repository's main?
    1 notify  each start says what is new there, with the commits; you take
              it with `sclaude update` once you have read them (recommended)
    2 auto    each start takes it by itself: what the maintainers merged runs
              here at the next start
    3 off     sclaude never fetches itself; you update the checkout by hand
TXT
}

contribute_modes_explain() {
  cat <<'TXT'
  sclaude's retrospective and friction reviews can fix sclaude itself, and
  send the fix to its public repository (main for a maintainer, a pull request
  from your fork for anybody else). Written while working in your product,
  such a change is checked for the product's details, but only by a heuristic.
    1 ask   you see the commits and the files, and nothing goes out without
            your yes
    2 send  it goes out by itself once it is reviewed and its tests are green
    3 off   no session changes sclaude on this machine; what got in its way
            stays in your product's friction log
TXT
}

leaks_modes_explain() {
  cat <<'TXT'
  Before a fix of sclaude is sent, it is searched for your product's details:
  its name, issue and pull-request numbers, paths of its files. When something
  matches, sclaude asks "Publish it anyway?".
    1 ask   the matching lines are shown, and nothing goes out without your yes
    2 auto  they are shown, and it goes out without the question
    3 off   a change that matches never goes out; a session rewords it first
TXT
}

# Writes one of them into the checkout's git config.
#
#   sclaude_setting_set <update|contribute|leaks> <word>
sclaude_setting_set() {
  git -C "${INSTRUMENTS:-.}" config "sclaude.$1" "$2"
}

# Whether there is a terminal to ask at, apart from the phone.
update_can_ask() { ( exec < /dev/tty ) 2>/dev/null; }

# One of <words>, by the number its line in the explanation carries: one key,
# no Enter and no word to type. Any other key is passed over. Reads from
# <source>, the terminal by default (install.sh gives its stdin); 1 at the
# end of input, or after <seconds> without a key.
#
#   setting_pick <var> "<words in the explanation's order>" [seconds] [source]
setting_pick() {
  local __var="$1" __secs="${3:-}" __src="${4:-/dev/tty}" __key
  local -a __words
  read -ra __words <<< "$2"
  printf '  Choose 1-%d: ' "${#__words[@]}" >&2
  while :; do
    IFS= read -rsn1 ${__secs:+-t "$__secs"} __key < "$__src" || { echo >&2; return 1; }
    # Ctrl-D: with the line mode off it arrives as a character, not as the
    # end of input, and is still the person leaving the question for later.
    [[ "$__key" == $'\x04' ]] && { echo >&2; return 1; }
    [[ "$__key" =~ ^[1-9]$ ]] && (( __key <= ${#__words[@]} )) && break
  done
  printf '%s\n' "${__words[__key - 1]}" >&2
  printf -v "$__var" '%s' "${__words[__key - 1]}"
}

# The update question, asked at a start while sclaude.update is unset, and
# saved. UPDATE_CHOSEN gets the answer; with nobody at the terminal it is
# notify for this start, and the question comes again at the next.
update_mode_choose() {
  UPDATE_CHOSEN=notify
  update_can_ask || return 0
  local answer
  echo "" >&2
  update_modes_explain >&2
  # At the terminal only, and not for long: this is a question of the
  # machine, not of a product's channel, and a start the bot or the menu made
  # in a pane has nobody at it. Unanswered, this start is notify and the next
  # one asks again.
  setting_pick answer "notify auto off" "${UPDATE_ASK_SECONDS:-60}" \
    || { printf '%s\n' "  No answer: notify for now; asked again at the next start." >&2; return 0; }
  sclaude_setting_set update "$answer"
  UPDATE_CHOSEN="$answer"
  printf '%s\n' "  Saved: git -C ${INSTRUMENTS:-.} config sclaude.update $answer (./install.sh --update=… changes it)" >&2
}
