#!/usr/bin/env bash
#
# The terminal sclaude runs in, recorded: what sclaude printed and what the
# person typed.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Nothing kept it before. The session transcripts hold the conversations, but
# not what sclaude itself said between them — the review's news, a red
# regression, a warning scrolled past, the question asked and the answer
# given, a session's last message and a changed plan as session_report and
# plan_report print them — and that is exactly what a retrospective over a feature
# needs (retro.sh). Windows Terminal's scrollback cannot be read from a script,
# so the recording is made as it happens, by script(1), which sits between the
# program and the terminal and copies every byte both ways.
#
# The sessions themselves are not recorded: what they showed is in their
# transcripts. A session in a tab of its own (pane.sh) never reaches this
# terminal; one that runs in place does, and term_skip marks it off so the
# playback leaves a line naming it instead of its screen.
#
# One recording per sclaude run, in the main repository it was started in:
# .sclaude/local/terminal, the machine's part of sclaude's folder there
# (scratch.sh), kept out of git
# and out of every Vercel upload with the rest of what sclaude writes into a
# project. Nothing to configure. Outside a repository the recording goes to
# ~/.claude/sclaude/terminal/.
#
# A feature learns which runs touched it: feature_worktree and run_step add the
# run's recording to .feature/terminal, one path per line. A run that went
# through the menu to two features is listed by both — it is one stretch of
# terminal, and cutting it apart would need sclaude to say where each feature's
# part begins.
#
#   SCLAUDE_TERM=off   record nothing.

TERM_DIR="$HOME/.claude/sclaude/terminal"
# A recording outlives its feature by this many days, then goes.
TERM_KEEP_DAYS=60

# Where a run started here is recorded: .sclaude/local/terminal in the main
# repository of the current directory — the recording starts before any
# feature is known, and a worktree's files go when the feature does — or
# TERM_DIR outside a repository.
term_dir() {
  local common
  if common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; then
    echo "$(dirname "$common")/.sclaude/local/terminal"
  else
    echo "$TERM_DIR"
  fi
}

# Run the rest of this sclaude under script(1), recording it. Called by main
# before anything is printed, with main's own arguments; returns only when
# there is nothing to record — no terminal, no script, switched off, or this
# run is already the recorded one — and replaces the process otherwise.
#
# SCLAUDE_TERM names the recording for everything below: the run itself, and
# sclaude re-executing itself after an update (instruments_sync, code_reload),
# which must go on in the same recording rather than nest another.
term_record() {
  [[ "${SCLAUDE_TERM:-}" == "off" ]] && return 0
  [[ -z "${SCLAUDE_TERM:-}" ]] || return 0
  [[ -t 0 && -t 1 ]] || return 0
  command -v script >/dev/null 2>&1 || return 0
  local dir; dir="$(term_dir)"
  # Excluded before the folder exists, so there is no moment git could see it.
  declare -F scratch_hide >/dev/null && scratch_hide
  mkdir -p "$dir" 2>/dev/null || return 0
  # Private, whatever the umask: a recording holds everything the run showed
  # and echoed, a pasted token included, for two months. The directory is
  # closed, and recordings made before it was are closed too.
  chmod 700 "$dir" 2>/dev/null || true
  find "$dir" -maxdepth 1 -name '*.log' -mtime +"$TERM_KEEP_DAYS" -delete 2>/dev/null || true
  find "$dir" -maxdepth 1 -name '*.log' -perm /077 -exec chmod 600 {} + 2>/dev/null || true

  local file; file="$dir/$(date +%Y%m%d-%H%M%S)-$$.log"
  # Created here, 0600, and only then handed to script, which truncates it and
  # keeps its mode. A umask around the exec would reach every file sclaude
  # itself writes afterwards.
  ( umask 077; : > "$file" ) 2>/dev/null || return 0
  # The command line through a file, as pane.sh does. script hands -c to
  # $SHELL, which need not be bash, and printf %q quotes for bash: under fish
  # an argument with a space or a quote in it would arrive in pieces. So the
  # quoted line goes into a file bash runs, and $SHELL is given only its path,
  # in single quotes every shell reads alike. The file removes itself before
  # sclaude starts.
  local launcher
  launcher="$(mktemp "${TMPDIR:-/tmp}/sclaude-term.XXXXXX")" || return 0
  {
    echo 'rm -f -- "$0"'
    printf 'exec'
    printf ' %q' "$(readlink -f "$0")" "$@"
    printf '\n'
  } > "$launcher"
  export SCLAUDE_TERM="$file"
  # -e: sclaude's own exit status, not script's. -f: written as it comes, so
  # a run still going can be read — the retrospective reads the very run it
  # is part of.
  exec script -q -e -f -c "bash '${launcher//\'/\'\\\'\'}'" "$file"
}

# Add this run's recording to a feature's list. Silent and never fatal.
term_attach() {
  local wt="$1" list
  [[ -n "${SCLAUDE_TERM:-}" && "$SCLAUDE_TERM" != "off" && -d "$wt/.feature" ]] || return 0
  list="$wt/.feature/terminal"
  grep -qxF -- "$SCLAUDE_TERM" "$list" 2>/dev/null && return 0
  echo "$SCLAUDE_TERM" >> "$list" 2>/dev/null || true
}

# The marks around a Claude session running in place, in a recorded run.
#
#   term_skip begin <claude args…>
#   term_skip end
#
# An OSC sequence of no meaning to any terminal, which every terminal drops
# unseen; term_render.py cuts from one to the other. The session id goes into
# the opening mark, so the line left in its place can name the transcript.
term_skip() {
  [[ -n "${SCLAUDE_TERM:-}" && "$SCLAUDE_TERM" != "off" && -t 1 ]] || return 0
  local what="$1" session="" i next
  shift
  for ((i = 1; i < $#; i++)); do
    case "${!i}" in
      --session-id|--resume) next=$((i + 1)); session="${!next}"; break ;;
    esac
  done
  if [[ "$what" == "begin" ]]; then
    printf '\033]7771;sclaude-skip;begin;%s\007' "$(printf '%s' "$session" | tr -cd '0-9a-f-')"
  else
    printf '\033]7771;sclaude-skip;end\007'
  fi
}

# Every recording a feature has, played back into one text file. Prints the
# file's path; returns 1 when there is nothing.
term_render() {
  local wt="$1" out="$1/.feature/terminal.txt" list="$1/.feature/terminal"
  [[ -s "$list" ]] || return 1
  local -a files=()
  local run
  while IFS= read -r run; do
    [[ -f "$run" ]] && files+=("$run")
  done < "$list"
  (( ${#files[@]} )) || return 1
  python3 "$LIB/term_render.py" "$out" "${files[@]}" >/dev/null 2>&1 || return 1
  echo "$out"
}
