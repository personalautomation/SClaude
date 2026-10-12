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

# The name, or nothing.
developer_name() {
  local raw="${SCLAUDE_DEV:-}"
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
product_maintainer() {
  local root="${1:-${REPO:-.}}" email content rc
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
