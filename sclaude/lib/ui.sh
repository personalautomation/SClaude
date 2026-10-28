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

# A prompt as readline is handed it: the colour codes in it marked as taking
# no room (\001 … \002). Unmarked, readline counts them as characters, and the
# cursor it moves with the arrows lands that many columns off.
rl_prompt() {
  printf '%s' "$1" | sed $'s/\x1b\\[[0-9;]*m/\x01&\x02/g'
}

# Erases a prompt line already printed, on every row it wrapped onto, and
# leaves the cursor at its start: \r and erase-line alone clear the last row
# only, and a prompt longer than the terminal is wide would show its first
# part twice once readline prints it again.
rl_unprint() {
  local plain cols rows=0
  plain="$(printf '%s' "$1" | sed $'s/\x1b\\[[0-9;]*m//g')"
  cols="$(stty size < /dev/tty 2>/dev/null)"; cols="${cols##* }"
  if [[ "$cols" =~ ^[0-9]+$ ]] && (( cols > 0 && ${#plain} > 0 )); then
    rows=$(( (${#plain} - 1) / cols ))
  fi
  printf '\r' >&2
  (( rows > 0 )) && printf '\033[%dA' "$rows" >&2
  printf '\033[J' >&2
}

# The feature this question belongs to is gone: the question goes, and so does
# this process — a caller handed an empty reply would only ask again. Called
# from ask_once and from the watch it keeps beside a line being typed, which is
# a subshell: $$ is the orchestrator either way.
ask_ended_quit() {
  printf '\n%s\n' "The feature $ASK_SLUG has ended elsewhere: nothing left to answer here." >&2
  ask_retract
  ask_forget
  kill -TERM "$$" 2>/dev/null
}

# A number typed for a pick:N list, in base 10: callers compare it with plain
# arithmetic, to which "08" is a bad octal number rather than option 8. Every
# path of ask_once hands its reply through here, with a channel or without.
# A number longer than nine digits after the zeros is 0, an option no list
# has: in 64-bit arithmetic it would wrap around into one that exists.
pick_norm() {
  if [[ "$1" == pick:* && "$2" =~ ^0*[0-9]{1,9}$ ]]; then
    echo "$((10#$2))"
  elif [[ "$1" == pick:* && "$2" =~ ^[0-9]+$ ]]; then
    echo 0
  else
    printf '%s\n' "$2"
  fi
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
      read -erp "$(rl_prompt "$__prompt")" __reply < /dev/tty || __rc=$?
    else
      read -rp "$__prompt" __reply || __rc=$?
    fi
    printf -v "$__var" '%s' "$(pick_norm "$__form" "$(clean_reply "$__reply")")"
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
      read -erp "$(rl_prompt "$__prompt")" __reply < /dev/tty || __rc=$?
    else
      read -rp "$__prompt" __reply || __rc=$?
    fi
    ask_forget
    printf -v "$__var" '%s' "$(pick_norm "$__form" "$(clean_reply "$__reply")")"
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
  local __in="" __from="" __key=""
  if ( exec < /dev/tty ) 2>/dev/null; then __in=/dev/tty; fi
  # So that Backspace erases a whole Cyrillic letter rather than its last
  # byte (see clean_reply).
  [[ -n "$__in" ]] && stty iutf8 < /dev/tty 2>/dev/null

  local __ended; __ended="$(ask_ended_mark)"
  while :; do
    if [[ -n "$__ended" && -f "$__ended" ]]; then
      ask_ended_quit
      exit 143
    fi
    if [[ -n "$__in" && -z "$__form" ]]; then
      # Free text is read with line editing, which read -t cannot give: a
      # readline read that times out drops what was typed so far, and the
      # wait times out every ASK_POLL. So the wait takes only the first key,
      # one character with no echo; once the human has begun to type, the
      # rest is theirs, and readline reads the line with that key already in
      # it and no time limit. Before, the arrows did not move the cursor: a
      # word inserted with them landed at the end, and their escape codes on
      # the screen.
      __rc=0
      # IFS emptied: read would otherwise strip a space or a tab and hand
      # back "", the same as Enter — an empty answer for a line just begun.
      IFS= read -rsn1 -t "$ASK_POLL" __key < "$__in" || __rc=$?
      if [[ "$__rc" -eq 0 ]]; then
        case "$__key" in
          "")    printf "\n" >&2; __reply=""; __from=tty; break ;;
          $'\e') # An arrow or another key with no text: dropped whole.
                 while IFS= read -rsn1 -t 0.05 __key < "$__in"; do :; done
                 continue ;;
          $'\x7f'|$'\b') continue ;;
        esac
        # The prompt laid out again, by readline, which has to know where its
        # line starts to redraw it: its last line, erased first on every row
        # it wrapped onto.
        rl_unprint "${__prompt##*$'\n'}"
        # The line has no time limit now, so the feature's end is watched
        # beside it: someone who pressed a key and left would otherwise hold
        # this process in readline after the feature was ended from the bot.
        local __watch=""
        if [[ -n "$__ended" ]]; then
          ( while sleep "$ASK_POLL"; do
              [[ -f "$__ended" ]] || continue
              stty sane < "$__in" 2>/dev/null
              ask_ended_quit
              exit 0
            done ) &
          __watch=$!
        fi
        read -erp "$(rl_prompt "${__prompt##*$'\n'}")" -i "$__key" __reply < "$__in" || __rc=$?
        if [[ -n "$__watch" ]]; then
          kill "$__watch" 2>/dev/null
          wait "$__watch" 2>/dev/null
        fi
        __from=tty; break
      fi
    elif [[ -n "$__in" ]]; then
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
  # A yes/no reply that is neither is not an answer: ask lays the same question
  # out again, and the chat must lose the old message rather than show it
  # answered with "maybe".
  # So is a number outside a pick:N list, which the caller refuses.
  local __clean __answered=1; __clean="$(clean_reply "$__reply")"
  if [[ "$__form" == yn* ]]; then
    is_yes "$__clean" || is_no "$__clean" || __answered=0
  elif [[ "$__form" =~ ^pick:([0-9]+)$ ]]; then
    # Kept before the next match, which overwrites BASH_REMATCH.
    local __n="${BASH_REMATCH[1]}"
    __clean="$(pick_norm "$__form" "$__clean")"
    # Only one of its options. An empty reply, which most lists refuse, is not
    # shown as an answer either; the one list that takes it ("Enter to leave
    # it out") then loses a line of history, not a decision.
    if [[ "$__clean" =~ ^[0-9]+$ ]]; then
      (( __clean >= 1 && __clean <= 10#$__n )) || __answered=0
    else
      __answered=0
    fi
  fi
  [[ "$__answered" -eq 1 ]] && ask_closed "$__id" "$__clean" "$__from"
  ask_retract
  ask_forget
  printf -v "$__var" '%s' "$__clean"
  return "$__rc"
}

# The pause between two looks of a wait for a person — QA, the merge, the
# review checks. Any key ends it early, so the look happens now.
#
#   poll_pause <seconds>
#
# A person who has just merged, or moved the issue to Done, should not sit out
# the rest of a minute to see sclaude notice. The key is read from the terminal
# without echo and swallowed together with whatever came with it — an arrow
# sends several bytes, a word typed by mistake many more — so none of it is
# left to answer the next question.
#
# Only with the status line on screen (stdout or stderr a terminal): without
# one nobody is told that a key does anything, and a test or a pipe must not
# block on the person's terminal. A terminal that cannot be read falls back to
# a plain sleep, as does the end of input, which would otherwise return at once
# and spin the loop.
#
# The first key pressed is left in POLL_KEY (empty after a plain timeout), for
# a wait that gives a key a meaning of its own: `a` in the QA wait, `m` in the
# merge wait.
poll_pause() {
  local secs="$1" key rest rc=0
  POLL_KEY=""
  if keys_usable; then
    read -rsn1 -t "$secs" key < /dev/tty || rc=$?
    if [[ "$rc" -eq 0 ]]; then
      POLL_KEY="$key"
      while read -rsn1 -t 0.05 rest < /dev/tty; do :; done
      return 0
    fi
    [[ "$rc" -gt 128 ]] && return 0
  fi
  sleep "$secs"
}

# Whether a wait can take keys: a status line on screen (stdout or stderr a
# terminal) and a terminal to read them from. Checked in a subshell, as in
# ask_once, so a missing terminal prints nothing.
keys_usable() {
  [[ -t 1 || -t 2 ]] && ( exec < /dev/tty ) 2>/dev/null
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
# merged, twice.
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
