#!/usr/bin/env bash
#
# Questions to the human, answers and colours — what the script talks to them
# with.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# A question to the human. We read straight from the terminal: between questions
# gh, vercel and claude get their turn, and what they do with an inherited stdin
# is not our business.
#
# The third argument is the answer's form: yn, pick:N, or nothing for
# free text (see ask_publish in io.sh). It is needed not by the terminal but by
# whoever will show the question as buttons, and the caller declares it: it knows
# the answer's type anyway — an is_yes or a check for a number stands on it — so
# this moves knowledge to where it is needed rather than being new knowledge.
#
# The question goes to the channel and is read from the terminal at the same
# time. Whoever answers first has answered: that way a question asked at the
# laptop can be answered from a phone without interrupting the step. With no
# channel (sclaude outside a repository) exactly the previous read remains.
#
# A yes/no question (form yn) has no default: it is asked again until the reply
# is y, yes, n or no (see is_yes). An empty line is not an answer — it is what a
# stale Enter, left in the terminal during a long wait, looks like. Only the end
# of input stops the asking, with nobody left to answer: the reply is then empty
# and the exit code non-zero, and every caller reads that as "no".
ask() {
  local __ask_form="${3:-}" __ask_rc=0 __ask_ctx="${ASK_CONTEXT:-}"
  if [[ "$__ask_form" != yn* ]]; then
    ask_once "$@"
    return
  fi
  while :; do
    __ask_rc=0
    ask_once "$@" || __ask_rc=$?
    is_yes "${!2}" || is_no "${!2}" && return 0
    [[ "$__ask_rc" -ne 0 ]] && return "$__ask_rc"
    # Straight to stderr rather than through warn: warn would add this line to
    # the context, and the question laid out again must carry the lines that
    # explained it — the commands of a run_block — not this reminder.
    printf '%s\n' "  Answer y or n." >&2
    ASK_CONTEXT="$__ask_ctx"
  done
}

ask_once() {
  local __prompt="$1" __var="$2" __form="${3:-}" __rc=0 __reply="" __outside=""
  local __published=""
  # Everything after the form is the options' labels, one per option. The
  # terminal has no use for them (it has already printed the list itself), while
  # a messenger needs them badly: without them the buttons arrive as the digits
  # "1 2 3", and "3" is pressed blind where the third option is "drop the
  # feature". An empty list means the previous behaviour.
  shift 3 2>/dev/null || shift $#
  local -a __options=("$@")

  # Waiting for an answer is only possible when there is somebody to answer,
  # and that is not established by inspection. Neither a launch from the bot nor
  # `sclaude status`, which that same bot calls with a 25-second timeout, has a
  # terminal; /dev/tty does not open in either case, and a question that waits
  # for ever would hang the whole Sclaude section.
  #
  # So whether to wait is decided not by a guess but by whoever launched us: the
  # channel is opened by ASK_DIR. The orchestrator sets it when it knows somebody
  # is holding the conversation; status and other "just find out" calls do not
  # have it, and the previous behaviour remains there — an empty answer and exit
  # code 1.
  if [[ -z "${ASK_DIR:-}" ]]; then
    ask_forget
    if ( exec < /dev/tty ) 2>/dev/null; then
      read -rp "$__prompt" __reply < /dev/tty || __rc=$?
    else
      read -rp "$__prompt" __reply || __rc=$?
    fi
    printf -v "$__var" '%s' "$(clean_reply "$__reply")"
    return "$__rc"
  fi

  __published="$(ask_publish "$__prompt" "$__form" "${__options[@]}")" || __published=""

  # The id of the question we have just laid out. Every answer read below is
  # checked against it: an answer to the previous question must not be taken for
  # an answer to this one — see ask_answer in io.sh for what that cost.
  local __id=""
  [[ -n "$__published" ]] && __id="$(ask_id)"

  if [[ -z "$__published" ]]; then
    if ( exec < /dev/tty ) 2>/dev/null; then
      read -rp "$__prompt" __reply < /dev/tty || __rc=$?
    else
      read -rp "$__prompt" __reply || __rc=$?
    fi
    ask_forget
    printf -v "$__var" '%s' "$(clean_reply "$__reply")"
    return "$__rc"
  fi

  # We print the prompt ourselves: read -t would print it afresh on every turn.
  #
  # To stderr rather than stdout — the way `read -rp` itself does it. The
  # difference is not cosmetic: issue_offer is called as
  # `issue="$(issue_offer …)"`, and a prompt that went to stdout becomes part of
  # the issue number. $issue is then "Create a GitHub issue? [y/n] 1234", and it
  # passes the non-empty check, prints as a number, lands in state.json and
  # travels to gh on every step transition. The same trap as was in pick_start,
  # only one level lower: everything a function prints inside $( ) has to go to
  # stderr.
  printf '%s' "$__prompt" >&2

  # Where we read hand-typed input from is established once for the whole wait
  # rather than on every turn: there are as many turns as the human spends
  # thinking about the answer, and probing /dev/tty in the loop would print
  # "No such device or address" once a second.
  #
  # The terminal is preferable to an inherited stdin for the same reason as in
  # the ordinary ask: between questions gh, vercel and claude get their turn, and
  # what they did with the shared stdin is not our business. But when there is no
  # terminal, stdin is the only input left and must not be closed: everything
  # that launches sclaude through a pipe answers through it.
  #
  # We check openability in a subshell. A bare `: < /dev/tty 2>/dev/null` prints
  # "No such device or address" past the suppression when there is no controlling
  # terminal at all — that is under setsid, that is when launched from the daemon:
  # bash reports the open error before the redirection takes effect. Around a
  # subshell the suppression covers that too. The same device stands in
  # pick_start.
  local __in="" __from=""
  if ( exec < /dev/tty ) 2>/dev/null; then __in=/dev/tty; fi
  # So that Backspace erases a whole Cyrillic letter rather than its last
  # byte (see clean_reply).
  [[ -n "$__in" ]] && stty iutf8 < /dev/tty 2>/dev/null

  while :; do
    if [[ -n "$__in" ]]; then
      # read holds the pause itself: -t returns control after exactly ASK_POLL
      # if the human has typed nothing.
      read -rt "$ASK_POLL" __reply < "$__in" && { __from=tty; break; } || __rc=$?
    else
      read -rt "$ASK_POLL" __reply && { __from=stdin; break; } || __rc=$?
    fi
    # Exactly 128+SIGALRM is read's expired wait. Anything below 128 is the end
    # of input: there is nobody left to type, the input has ended or there never
    # was any — but the channel remains, and the question waits for an answer
    # from there.
    #
    # There is nothing more to read, so we hold the pause ourselves: read on an
    # exhausted input returns instantly and would spin the loop idle, eating a
    # core for nothing.
    if [[ "$__rc" -lt 128 ]]; then
      __in=""
      __rc=0
      if __outside="$(ask_answer "$__id")"; then
        # Printed here too: with the terminal gone quiet, a key typed into it is
        # still echoed, and without this line the screen shows that key beside
        # a result the channel's answer produced.
        printf '%s\n' "$__outside" >&2
        __reply="$__outside"; __from=channel; break
      fi
      sleep "$ASK_POLL"
      continue
    fi
    __rc=0
    if __outside="$(ask_answer "$__id")"; then
      # The answer came from outside — we print it after the prompt so that a
      # whole "question — answer" line stays in the terminal rather than a
      # cut-off question with no telling who answered what. To stderr, where the
      # prompt went: in stdout this would spoil the capture of the result.
      printf '%s\n' "$__outside" >&2
      __reply="$__outside"; __from=channel
      break
    fi
  done

  ask_log "$__prompt" "$__from" "$__reply" "$__in"
  ask_retract
  ask_forget
  printf -v "$__var" '%s' "$(clean_reply "$__reply")"
  return "$__rc"
}

# Whether the human answered "yes", and whether "no". Exactly y, yes, n or no,
# in any case — nothing else counts as either.
#
# These used to match any reply that began with a yes-ish or no-ish letter,
# Cyrillic ones included, and a yes/no question had a default an empty reply
# took. Both cost answers: a stale Enter left in the terminal during a six-hour
# wait for QA was read as "no" at "Ship to production?", and the Cyrillic
# letters were not even the keys they were meant to be — on a Russian layout
# the "y" key types "н", which is_no took for a no. So ask re-asks a yes/no
# question until one of these matches, and there is no default left to fall
# into.
is_yes() {
  case "$1" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *)                 return 1 ;;
  esac
}

is_no() {
  case "$1" in
    [nN]|[nN][oO]) return 0 ;;
    *)             return 1 ;;
  esac
}

# Brings the answer to what the human meant.
#
# Switching the keyboard layout (Ctrl+Shift, Win+Space) makes the terminal send
# an escape sequence — `^[[?1;2c`, for instance, the reply to an identification
# request — and it lands in read as part of the line. The answer becomes
# "^[[?1;2cy", and `== [yY]*` does not fire on that: the human pressed "y", the
# script heard "no". That is exactly how the answer to the preview question was
# lost.
#
# Spaces are stripped along the way. Letters are not substituted here: a
# feature's name and an option's number also pass through ask.
#
# And bytes that are not UTF-8 are dropped. A Cyrillic letter typed and erased
# with Backspace on a terminal without `iutf8` loses only its last byte: the
# first, \320 or \321, stays in the line, invisible. Bash then matched that
# lone byte against the first byte of "д" or "у" in is_yes, so "\321n" — an
# "n" on screen — was a yes. That is how "Merge origin/main into …? [y/N] n"
# merged on #143 in social, twice.
clean_reply() {
  local valid="$1"
  if command -v iconv >/dev/null 2>&1; then
    valid="$(printf '%s' "$1" | iconv -f UTF-8 -t UTF-8 -c 2>/dev/null)"
  fi
  printf '%s' "$valid" | sed -E '
    s/\x1b\[[0-9;?]*[a-zA-Z~]//g;  # CSI: ^[[?1;2c, ^[[200~ (bracketed paste)
    s/\x1b[]()#][0-9A-Za-z]?//g;   # short sequences
    s/[[:cntrl:]]//g;              # whatever is left of the control characters
    s/^[[:space:]]+//; s/[[:space:]]+$//
  '
}
