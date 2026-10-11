#!/usr/bin/env bash
#
# The question-answer channel: how sclaude asks the human when they are not at
# the terminal.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# A question lives in a file rather than in a process — that is the module's
# whole point. While a question was an ordinary `read` from the terminal, only
# whoever launched sclaude could answer it, and a feature's cycle was tied to the
# window it began in. Stepping away from the laptop in the middle of "Is step
# 'development' finished?" meant abandoning the step until you came back.
#
# A question laid out in a file is answered from anywhere: from the terminal that
# asked it, and from Telegram, which picked it up. Both sources are read at the
# same time and whoever arrives first wins — that is how switching between the
# laptop and the phone becomes hot, mid-conversation and without a restart.
#
# The terminal stays the leader in this: an answer from the phone arrives in the
# live process, and it carries on by itself, going on printing where it was
# printing. Nothing is "handed over" anywhere — one question simply has two
# inputs.
#
# A file rather than a socket: sclaude already talks to the bot through the
# filesystem (state.json, plan.md), the daemon survives restarts, and untangling
# a stuck session comes down to reading a file with your own eyes.
#
# How often to look for an answer from the other side. A second is a delay a
# human does not notice and one stat a second for the machine.
ASK_POLL=1

# --- where the channel lives -------------------------------------------------

# The channel's directory for the current question — the same as ASK_DIR.
#
# There is deliberately no guess of our own here. The channel is a promise that
# somebody will pick the question up and answer it, and only whoever launched us
# can make such a promise: by the look of the process, "a conversation with a
# human" and "`sclaude status` from the daemon" are indistinguishable, neither
# has a terminal. Having guessed, we would hang status on a question nobody will
# see.
#
# It is set by whoever opens the conversation — main in bin/sclaude, once per
# launch, and always in the main repository's .git/sclaude/. A feature's
# directory will not do for this, tempting as it is: the question about the name
# is asked before the feature's tree exists, and the bot looks for questions by
# repository without knowing about their worktrees. One channel per repository —
# and the live-owner check in
# ask_publish.
ask_dir() {
  echo "${ASK_DIR:-}"
}

# --- the accumulated context -------------------------------------------------
#
# A question without what was printed before it loses its meaning in a messenger,
# and sometimes becomes dangerous. "Publish?" is run_block, which has just shown
# a list of commands; "Restart it for this feature?" is ensure_dev, which
# explained that the port is taken by a server from another directory. A "Yes"
# button without those lines offers agreement to who knows what.
#
# So info and warn accumulate what they print here, and ask_publish attaches the
# accumulated text to the question. In the terminal both functions print as they
# always did: the human sees the same lines on the screen, the buffer merely
# duplicates them.

ASK_CONTEXT=""

ask_note() {
  ASK_CONTEXT+="$1"$'\n'
}

# The context lives until the next question and is cleared with it: the lines
# that explained the previous question have nothing to do with the next one.
ask_forget() {
  ASK_CONTEXT=""
}

# --- laying out a question ---------------------------------------------------
#
# Puts a question in the channel. Prints the path to the question's file, or
# nothing if there is no channel.
#
# The answer's form is what turns a question into buttons on a phone:
#
#   yn        yes/no, no default        ([y/n] in the terminal; ask re-asks
#             until the reply is y, yes, n or no)
#   pick:N    a choice of N options      ([1-N])
#   empty     free text
#
# Which feature the question is about is told by ASK_FEATURE — an environment
# variable rather than an argument: it is set around the call where it is known,
# and all the other callers stay untouched.
#
# The options' labels may follow the form — one per option, in the same order the
# terminal printed them. They travel to the channel in an options field, and the
# reading side draws labelled buttons from them instead of bare digits. The
# contract does not change in doing so: the form stays "pick:N", the answer stays
# a number, and whoever does not know about options works exactly as before. An
# empty list means no field.
#
# The caller passes it rather than a parse of the prompt string guessing it:
# guessing would diverge from the code silently the moment the question's text is
# rewritten.
#
# We write through a temporary file and mv: the reading side must not have time
# to see half a question. mv within one directory is atomic.
ask_publish() {
  local prompt="$1" form="${2:-}" dir file tmp
  shift 2 2>/dev/null || shift $#
  local -a options=("$@")
  dir="$(ask_dir)"
  [[ -n "$dir" ]] || return 1
  mkdir -p "$dir" 2>/dev/null || return 1

  file="$dir/ask.json"

  # There is one channel per repository, and there may turn out to be two
  # orchestrators: one started at the laptop, the other by a button in the bot.
  # The second used to overwrite the first's question, and that one hung for
  # ever — the answer was no longer going to it. Verified live: two `sclaude new`
  # in a row, and the second's question stays in the channel.
  #
  # The later arrival gives way: the first already has a conversation going, and
  # cutting it off for the sake of a button just pressed is wrong. It will be
  # left without a channel and will ask the terminal — that is, behave as it did
  # before this whole undertaking.
  if [[ -f "$file" ]]; then
    local owner
    owner="$(python3 -c '
import json, sys
try:
    print((json.load(open(sys.argv[1])) or {}).get("pid") or "")
except Exception:
    pass' "$file" 2>/dev/null)"
    # We overwrite our own question calmly: it is the next question of the same
    # conversation. Someone else's, alive — we give way. Someone else's, dead
    # (the orchestrator was killed, the session dropped) — we take the channel:
    # there is no reason to hold it for the deceased.
    if [[ -n "$owner" && "$owner" != "$$" ]] && kill -0 "$owner" 2>/dev/null; then
      return 1
    fi
  fi

  tmp="$file.$$"

  ASK_PROMPT="$prompt" ASK_FORM="$form" ASK_BODY="$ASK_CONTEXT" \
  ASK_OPTIONS="$(printf '%s\n' "${options[@]}")" \
  ASK_FEATURE="${ASK_FEATURE:-}" \
  python3 - "$tmp" "$$" <<'PY' || return 1
import json, os, sys, time, uuid
path, pid = sys.argv[1], int(sys.argv[2])
# The question's text as it is, colours included: they must not be stripped here,
# as a human reads the same file. The reading side cleans them, it knows better
# where it is showing them.
question = {
    'prompt': os.environ.get('ASK_PROMPT', ''),
    'form': os.environ.get('ASK_FORM', ''),
    'context': os.environ.get('ASK_BODY', ''),
    'asked': int(time.time()),
    # The question's stamp, by which the reading side tells it from the next
    # one. Seconds will not do for this: two questions in a row — "Delete them?"
    # and "Force-delete it?" — fit into one, and the bot, comparing by time,
    # would consider the second already shown and would say nothing. The step
    # would stall, and from a phone that would look like "nothing is
    # happening".
    'id': uuid.uuid4().hex,
    'pid': pid,
}
# The options' labels only when there are any. An empty field in the file would
# mean "there are no buttons", and that is a different statement from "no labels
# were passed". We discard empty lines, and that imposes a condition on the
# caller: there must be no empty labels among the options. Otherwise the list
# shrinks, every following label moves up by one option, and a "Continue" button
# answers "Drop the feature" — the cost of that mistake is such that chance
# cannot be relied on here.
#
# Today it holds by itself (the labels are taken from the menu's non-empty
# lines) and, should it be broken, will do no harm: the length would diverge
# from the number of options, and the reading side draws labelled buttons only
# when the lengths matched — and falls back to digits. The check below does the
# same thing explicitly, on this side.
options = [o for o in os.environ.get('ASK_OPTIONS', '').split('\n') if o]
declared = os.environ.get('ASK_OPTIONS', '')
declared = [o for o in declared.split('\n')] if declared else []
# The last line from printf is always empty — it and only it is discarded.
if declared and declared[-1] == '':
    declared.pop()
if options and len(options) == len(declared):
    question['options'] = options
# The name of the feature the question is about — when it is about one. From it
# the reading side gathers what the orchestrator does not know about itself: the
# bot has a feature card with links and the session's state, and it can show that
# above the buttons itself. The terminal neither needs the field nor is troubled
# by it: it has already printed everything.
feature = os.environ.get('ASK_FEATURE', '').strip()
if feature:
    question['feature'] = feature
with open(path, 'w') as fh:
    json.dump(question, fh, indent=2, ensure_ascii=False)
    fh.write('\n')
PY

  # The order here is not a matter of taste but the only safe one.
  #
  # First the new question goes up, and only then the previous answer is
  # cleared. The other way round would be a window a whole python3 launch wide:
  # the old ask.json is still there, the answer has already been cleared, and the
  # bot, seeing a live old question, puts an answer to it into the channel. An
  # instant later mv replaces the question — and that answer goes to the new one,
  # which the human never saw.
  #
  # The case is not invented: branches.sh asks "Delete them?" and immediately
  # after it "Force-delete it (git branch -D)?" — and a "yes" said to the first
  # would tear down branches with unmerged commits.
  #
  # In the reverse order there is no such window: while the new question stands,
  # someone else's answer to the old one may still arrive, but the next line
  # clears it at once.
  mv -f "$tmp" "$file" 2>/dev/null || { rm -f "$tmp"; return 1; }
  rm -f "$dir/answer.json"
  echo "$file"
}

# Removes the question from the channel: it has been answered, and the second
# source must learn of it. It learns by the file's disappearance — no separate
# "cancelled" is needed.
# Every answer a published question got, where from, and its bytes as read.
#
#   ask_log <prompt> <from> <reply> <tty-still-read>
#
# Once an "n" typed at "Merge origin/main into …? [y/N]" was
# followed by the merge, and neither the terminal nor the bot could say what
# had answered: the same code with the same key, replayed, says no. The next
# time, .git/sclaude/answers.log says which input it was — the terminal, stdin
# or the channel — and what exactly it carried.
ask_log() {
  local dir; dir="$(ask_dir)"
  [[ -n "$dir" ]] || return 0
  local q; q="$(clean_reply "$1")"
  printf '%s pid=%s from=%s tty=%s reply=%q prompt=%q\n' \
    "$(date -Iseconds)" "$$" "${2:-none}" "${4:-closed}" "$3" "$q" \
    >> "$dir/answers.log" 2>/dev/null || true
}

ask_retract() {
  local dir; dir="$(ask_dir)"
  [[ -n "$dir" ]] || return 0
  rm -f "$dir/ask.json" "$dir/answer.json"
}

# The id of the question standing in the channel right now. Empty when there is
# no question, or when it was laid out by a version that did not stamp one.
ask_id() {
  local dir file; dir="$(ask_dir)"
  [[ -n "$dir" ]] || return 0
  file="$dir/ask.json"
  [[ -f "$file" ]] || return 0
  python3 - "$file" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)
print((data or {}).get('id') or '')
PY
}

# The answer, if one came from the channel's side. Prints the answer's text and
# returns 0; when there is no answer it returns 1 and prints nothing.
#
# The first argument is the id of the question we are waiting for an answer to.
# An answer stamped with another id belongs to a question that has already
# closed, and it is discarded rather than taken. Clearing the channel before a
# new question is not enough on its own: the answering side checks that a
# question is open, and only then writes, and the question can close and the
# next one open in between. That window cost a worktree — a "no" to "Ship to
# production?" was still on its way when "Remove all of it?" was asked, and it
# passed for an answer to that.
#
# An answer with no stamp at all comes from a version that did not set one, and
# is accepted: otherwise updating one half would silence the other.
ask_answer() {
  local want="${1:-}"
  local dir file; dir="$(ask_dir)"
  [[ -n "$dir" ]] || return 1
  file="$dir/answer.json"
  [[ -f "$file" ]] || return 1
  python3 - "$file" "$want" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)          # being written right now — we will read it next turn
reply = data.get('reply')
if reply is None:
    sys.exit(1)
want, got = sys.argv[2], data.get('id') or ''
if want and got and got != want:
    sys.exit(1)
print(reply)
PY
}
