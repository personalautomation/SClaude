#!/usr/bin/env bash
#
# What sclaude's bash entry points do first on macOS: Homebrew's bash 5 in
# place of the system's 3.2, and the GNU tools ahead of the BSD ones.
#
# sclaude is written for bash 4 and later (mapfile, associative arrays,
# ${x,,}) and for the GNU userland: coreutils (timeout, stat -c, date -d,
# readlink -f, cp -al), sed and grep (\+, -P), awk, find, and util-linux's
# setsid and flock. Rather than a second spelling of each, a Mac puts
# Homebrew's GNU builds first on PATH — for sclaude and for everything it
# starts, so a session's hooks and the commands they run see the same tools.
# Only the directories that hold those builds go first, not Homebrew's bin as
# a whole: a node from nvm stays ahead of Homebrew's node, as the person set
# it. install.sh installs the formulae (MACOS_FORMULAE).
#
# Not one of the modules bin/sclaude loads: it runs as it is read, at the top
# of an entry point, before anything else and with no arguments of its own,
# so that re-executing under bash 5 hands the script its own "$@":
#
#   [[ "${OSTYPE:-}" == darwin* ]] && source "<repo>/sclaude/lib/core/macos.sh"
#
# Written for bash 3.2 too: that is the bash that reads it first.

MACOS_FORMULAE="bash coreutils gnu-sed grep gawk findutils util-linux"

# Homebrew's prefix, or 1 when there is no Homebrew.
macos_brew() {
  local p
  for p in "${HOMEBREW_PREFIX:-}" /opt/homebrew /usr/local; do
    [[ -n "$p" && -x "$p/bin/brew" ]] && { echo "$p"; return 0; }
  done
  return 1
}

# The directory of each formula's GNU build: `bash` holds bash alone,
# util-linux is keg-only and holds its own tools.
macos_tool_dir() {
  case "$2" in
    bash)       echo "$1/opt/bash/bin" ;;
    util-linux) echo "$1/opt/util-linux/bin" ;;
    *)          echo "$1/opt/$2/libexec/gnubin" ;;
  esac
}

# The formulae not installed, space-separated; nothing when all are.
macos_missing() {
  local brew f missing=""
  brew="$(macos_brew)" || { echo "$MACOS_FORMULAE"; return 0; }
  for f in $MACOS_FORMULAE; do
    [[ -d "$(macos_tool_dir "$brew" "$f")" ]] || missing="$missing $f"
  done
  echo "${missing# }"
}

# PATH with the GNU builds ahead of everything else, each once.
macos_gnu_path() {
  local brew f dir path=":${PATH:-}:"
  brew="$(macos_brew)" || { printf '%s' "${PATH:-}"; return 0; }
  for f in $MACOS_FORMULAE; do
    dir="$(macos_tool_dir "$brew" "$f")"
    [[ -d "$dir" ]] || continue
    path="${path//:$dir:/:}"
    path=":$dir$path"
  done
  path="${path#:}"
  printf '%s' "${path%:}"
}

# MACOS_FUNCTIONS_ONLY: the functions alone, for install.sh to see what is
# missing before anything is re-executed.
if [[ "${OSTYPE:-}" == darwin* && -z "${MACOS_FUNCTIONS_ONLY:-}" ]]; then
  PATH="$(macos_gnu_path)"
  export PATH
  if (( BASH_VERSINFO[0] < 4 )); then
    if _macos_brew="$(macos_brew)" && [[ -x "$_macos_brew/opt/bash/bin/bash" ]]; then
      exec "$_macos_brew/opt/bash/bin/bash" "$0" "$@"
    fi
    echo "$(basename "$0"): sclaude on macOS needs Homebrew's bash and GNU tools:" >&2
    echo "  brew install $MACOS_FORMULAE" >&2
    echo "  (./install.sh offers to run it)" >&2
    exit 1
  fi
fi

# Run rather than sourced (`bash macos.sh path`): the PATH it sets, for a
# program that is not bash — tests/run, install.sh's launchd agents.
if [[ "${BASH_SOURCE[0]}" == "$0" && "${1:-}" == path ]]; then
  printf '%s\n' "$PATH"
fi
