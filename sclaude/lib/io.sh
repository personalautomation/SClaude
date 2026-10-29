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
# launch, and always in the main repository's .git/sclaude/: the repository's
# channel, under the main repository's .git rather than in a worktree, since the
# question about the name is asked before the feature's tree exists. A feature's
# questions go to its own channel beside it (ask_channel).
ask_dir() {
  echo "${ASK_DIR:-}"
}

# The channel a question goes to: the feature's own, when the conversation is
# about one, or the repository's.
#
# Features run in parallel, each under its own orchestrator, and one channel per
# repository let only one of them reach the phone: the second found the channel
# busy and asked the terminal alone. So a function that works on a feature
# declares `local ASK_SLUG="$slug"`, and everything it calls asks in
# ask/<slug>/ — bash's dynamic scope ends the binding with the function, so a
# menu asked after it is the repository's again. The bot reads the feature
# from the directory's name and shows its questions in the feature's topic.
#
# Questions asked before there is a feature — its name, the start menu — stay
# in the repository's channel.
ask_channel() {
  local dir; dir="$(ask_dir)"
  [[ -n "$dir" ]] || return 0
  # A name that is not a plain slug stays in the repository's channel rather
  # than becoming a path: cmd_done takes its argument as typed.
  # A feature whose clean-up has ended asks in the repository's channel: an
  # outer function still bound to it (the action list `done` was chosen from)
  # would otherwise lay a question out where the bot is deleting everything.
  if [[ "${ASK_SLUG:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$ASK_SLUG" != "${ASK_ENDED:-}" ]]; then
    echo "$dir/ask/$ASK_SLUG"
  else
    echo "$dir"
  fi
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

# say, warn and alarm (bin/sclaude) for this terminal alone: kept for the next
# question as they are, and not said to the feature's topic (ask_feed). For a
# line the topic hears in a shape of its own — a session's start and end,
# a regression's or a deploy's (phase_line) — so that it does not hear it
# twice.
say_here()   { ask_note "$*"; echo "$*"; }
warn_here()  { ask_note "$*"; echo "${YELLOW:-}$*${OFF:-}" >&2; }
alarm_here() { ask_note "$*"; echo "${RED:-}$*${OFF:-}" >&2; }

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
  dir="$(ask_channel)"
  [[ -n "$dir" ]] || return 1
  mkdir -p "$dir" 2>/dev/null || return 1

  file="$dir/ask.json"

  # One channel may turn out to have two orchestrators — the repository's, or
  # one feature's: one started at the laptop, the other by a button in the bot.
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
#   ask_log <prompt> <from> <reply> <tty-still-read> [seconds it waited]
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
  # And in the feature's history, as one more time the person had to step in
  # (process.py counts them on its map) — from the terminal or the phone; a
  # reply piped in is a script's. The tree is looked up once per feature in
  # this process: the person waits on this line.
  if [[ -n "${ASK_SLUG:-}" && "$ASK_SLUG" != "${ASK_ENDED:-}" && "${2:-}" != stdin ]] \
     && declare -F history_add >/dev/null; then
    # Only a tree found is kept: one not there yet (sclaude new) is looked
    # for again on the next answer.
    local tree
    if [[ "${ASK_TREE_OF:-}" != "$ASK_SLUG" ]] \
       && tree="$(feature_worktree "$ASK_SLUG" quiet 2>/dev/null)"; then
      ASK_TREE="$tree" ASK_TREE_OF="$ASK_SLUG"
    fi
    [[ "${ASK_TREE_OF:-}" == "$ASK_SLUG" ]] \
      && history_add "$ASK_TREE/.sclaude/local/feature/state.json" ask answered from="${2:-none}" \
           ${5:+waited="$5"}
  fi
}

# Where to see that the feature this process asks about was ended by another: its
# channel holds the end mark, which only the clean-up writes. A question left
# waiting there — the action list opened from the phone, and the feature then
# dropped in the terminal — has nobody to answer it any more, and its open
# question keeps the bot from deleting the topic. The clean-up of this process
# itself is not it: ask_feature_end moved its questions to the repository.
#
# Prints the mark's path, nothing when no feature is bound: a question looks
# it up once and tests the file on each turn of its wait.
ask_ended_mark() {
  [[ -n "${ASK_SLUG:-}" && "$ASK_SLUG" != "${ASK_ENDED:-}" ]] || return 0
  local dir; dir="$(ask_channel)"
  [[ -n "$dir" ]] && printf '%s\n' "$dir/ended"
}

ask_retract() {
  local dir; dir="$(ask_channel)"
  [[ -n "$dir" ]] || return 0
  rm -f "$dir/ask.json" "$dir/answer.json"
}

# --- the end of a feature ----------------------------------------------------
#
# The bot keeps what it knows of a feature — its Telegram topic, the message
# showing its open question — in the feature's worktree, in
# .sclaude/local/feature/telegram.json, which git and every upload leave out,
# and nowhere else. The topic goes with the worktree: remove_worktree reads the
# record while it is still there and, once the worktree is gone, hands it to the
# bot in the channel's "ended" mark — the one moment anything of it leaves the
# worktree. The bot deletes the topic, everything in it, and the channel.
#
# So a feature asks nothing once its worktree is removed: `done` and `drop` ask
# all their questions first. ask_feature_end also ends the binding, so a
# question that slips in after it goes to the repository's channel rather than
# to a topic that is being deleted.
#
# The names are read by FEATURE_RECORD and ENDED_MARK in keepawake/telegramd.py.
ask_record() {
  # The channel is touched as well: the bot counts a worktree gone without a
  # clean-up from the channel's last change, and the removal about to start
  # is a clean-up whose mark comes after it.
  local dir; dir="$(ask_channel)"
  [[ -n "$dir" && "$dir" != "$(ask_dir)" && -d "$dir" ]] && touch "$dir" 2>/dev/null
  cat "$1/.sclaude/local/feature/telegram.json" 2>/dev/null || true
}

# A feature begins: a mark left by an earlier feature of the same name, which
# the bot has not come to yet, is that one's, and must not end this one. It is
# set aside rather than dropped — it holds the only copy of the old topic's id,
# and the bot still deletes that topic by it.
ask_feature_begin() {
  # The ended name is cleared first: ask_channel would otherwise give the
  # repository's channel for a feature that ended earlier in this process.
  [[ -n "${ASK_SLUG:-}" && "${ASK_ENDED:-}" == "$ASK_SLUG" ]] && ASK_ENDED=""
  local dir; dir="$(ask_channel)"
  [[ -n "$dir" && "$dir" != "$(ask_dir)" ]] || return 0
  # Touched once set aside: mv keeps the old time, and the week-old sweep
  # would take a mark from a feature that ended long ago before the bot came.
  local aside; aside="$dir/ended-$(date +%s)"
  [[ -f "$dir/ended" ]] && mv -f "$dir/ended" "$aside" 2>/dev/null && touch "$aside"
  return 0
}

ask_feature_end() {
  local record="${1:-}" dir; dir="$(ask_channel)"
  [[ -n "$dir" && "$dir" != "$(ask_dir)" ]] || return 0
  # Whole or not at all, as every file the bot reads here: an empty mark read
  # mid-write would end the feature with no topic to delete.
  mkdir -p "$dir" 2>/dev/null && printf '%s' "$record" > "$dir/.ended.$$" 2>/dev/null \
    && mv -f "$dir/.ended.$$" "$dir/ended" 2>/dev/null
  # Global, not local: every binding to this feature up the call stack ends
  # with it (ask_channel), not only the innermost one.
  ASK_ENDED="$ASK_SLUG"
  ASK_SLUG=""
  return 0
}

# How a question ended, left for whoever showed it elsewhere.
#
#   ask_closed <id> <reply> <from>
#
# The bot shows the question in a chat, and once it closes, the message there
# must change: an answered question is replaced by its answer, one that died
# unanswered is deleted. The disappearance of ask.json says only that it closed,
# not how — and the answer itself is gone with answer.json. So an answered
# question leaves a record in closed/<id>.json, written before ask_retract, so
# that the reading side never sees the question gone without it. No record
# means no answer: the session was killed, or the reply was refused and the
# question is about to be asked again.
#
# One file per question rather than one shared file: two questions in a row
# ("Delete them?", "Force-delete it?") can both close between two turns of the
# bot, and each needs its own answer. The bot deletes the records it has read.
#
# A machine without the bot would keep every record for ever, so each new one
# also clears those older than a week. A day was too short: a bot stopped over
# a long weekend would come back to find the answers gone and delete questions
# that had been answered.
ask_closed() {
  local id="$1" dir root; dir="$(ask_channel)"; root="$(ask_dir)"
  [[ -n "$dir" && "$id" =~ ^[A-Za-z0-9]+$ ]] || return 0
  # Every channel's, the features' too. Empty directories stay: `mkdir -p`
  # does not refresh an old one's time, so no age tells one about to be
  # written into from one left behind, and an empty directory costs nothing.
  # Once a day is enough for a week-old sweep, not once per answer.
  if [[ -z "$(find "$root/.swept" -mmin -1440 2>/dev/null)" ]]; then
  touch "$root/.swept" 2>/dev/null
  find "$root" -path '*/closed/*' -type f -mmin +10080 -delete 2>/dev/null
  [[ -d "$root/ask" ]] && find "$root/ask" -mindepth 2 -maxdepth 2 -name 'ended-*' \
    -mmin +10080 -delete 2>/dev/null
  # A finished feature's channel the bot never came to clear (it was not
  # running) goes a week after the clean-up.
  # Never one with a question open: that is a feature asking again under the
  # same name.
  local ended
  while IFS= read -r -d '' ended; do
    [[ -e "$ended/ask.json" ]] || rm -rf -- "$ended"
  done < <([[ -d "$root/ask" ]] && find "$root/ask" -mindepth 2 -maxdepth 2 -name ended \
             -mmin +10080 -printf '%h\0' 2>/dev/null)
  fi
  mkdir -p "$dir/closed" 2>/dev/null || return 0
  ASK_REPLY="$2" ASK_FROM="$3" python3 - "$dir/closed" "$id" <<'PY' || true
import json, os, sys, time
d, qid = sys.argv[1], sys.argv[2]
tmp = os.path.join(d, '.%s.%d' % (qid, os.getpid()))
with open(tmp, 'w') as fh:
    json.dump({'id': qid, 'reply': os.environ.get('ASK_REPLY', ''),
               'from': os.environ.get('ASK_FROM', ''), 'at': int(time.time())},
              fh, ensure_ascii=False)
os.replace(tmp, os.path.join(d, qid + '.json'))
PY
}

# A message for the feature's topic that asks nothing — the review's numbers
# after a round. Laid in notes/ of the feature's channel, one file each; the
# bot sends them in order, each as a message of its own, and deletes the file
# (NOTES_DIR in keepawake/notices.py). The same text as the last one is not
# laid again: the report is printed at more than one point of a round.
#
#   ask_notice <text>
ask_notice() {
  local text="$1" dir notes sum
  dir="$(ask_channel)"
  [[ -n "$dir" && "$dir" != "$(ask_dir)" && -n "$text" ]] || return 0
  notes="$dir/notes"
  mkdir -p "$notes" 2>/dev/null || return 0
  sum="$(printf '%s' "$text" | sha1sum | cut -c1-40)"
  [[ "$(cat "$notes/.last" 2>/dev/null)" == "$sum" ]] && return 0
  # Whole or not at all, as every file the bot reads here.
  printf '%s' "$text" > "$notes/.new.$$" 2>/dev/null \
    && mv -f "$notes/.new.$$" "$notes/$(date +%s)-$$-$RANDOM.txt" 2>/dev/null \
    && printf '%s' "$sum" > "$notes/.last"
  return 0
}

# What sclaude prints about a feature, for its topic: every line said, warned
# or noted while bound to a feature (ASK_SLUG) is appended to
# notes/feed.tsv, and the bot sends what gathered
# as one shorter message a turn (keepawake/notices.py, FEED_FILE). One line
# per call — the time, the level, the printing process, the text — written
# without a process of its own: sclaude prints hundreds of lines.
#
#   ask_feed <level> <text>      level: say, info, warn, alarm
ask_feed() {
  local level="$1" text="$2" dir
  # Unbound, or bound to a feature this process has ended: no forks for it.
  [[ -n "$text" && -n "${ASK_SLUG:-}" && "$ASK_SLUG" != "${ASK_ENDED:-}" ]] || return 0
  # The path as ask_channel makes it, written out: a subshell per printed
  # line is what this function exists to avoid.
  [[ -n "${ASK_DIR:-}" && "$ASK_SLUG" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 0
  dir="$ASK_DIR/ask/$ASK_SLUG"
  # A feature ended elsewhere: its channel is the bot's to delete, and lines
  # written into it now would bring it back.
  [[ -e "$dir/ended" ]] && return 0
  [[ -d "$dir/notes" ]] || mkdir -p "$dir/notes" 2>/dev/null || return 0
  text="${text//$'\t'/ }"
  printf '%s\t%s\t%s\t%s\n' "${EPOCHSECONDS:-0}" "$level" "$$" "${text//$'\n'/ ⏎ }" \
    >> "$dir/notes/feed.tsv" 2>/dev/null
  return 0
}

# A line to the phone about a feature, in the feature's topic
# (sclaude-notify --in its worktree); the main chat when it has none.
# The worktree from list_features rather than feature_worktree, which also
# attaches the terminal.
#
#   notify_feature <slug> [--wt <worktree>] [--quiet] <text>   or the text on stdin
#
# The text does not name the feature: the topic is the feature, and in the
# main chat sclaude-notify puts the name before it (--as). A caller that has
# the worktree passes it, and it is not looked for again.
notify_feature() {
  local slug="$1" wt=""
  shift
  if [[ "${1:-}" == --wt ]]; then
    wt="${2:-}"
    shift 2
  else
    wt="$(list_features 2>/dev/null | awk -F'\t' -v want="$slug" '$1 == want { print $2; exit }')"
  fi
  "${INSTRUMENTS:-}/bin/sclaude-notify" ${wt:+--in "$wt"} --as "$slug" "$@"
}

# The id of the question standing in the channel right now. Empty when there is
# no question, or when it was laid out by a version that did not stamp one.
ask_id() {
  local dir file; dir="$(ask_channel)"
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
  local dir file; dir="$(ask_channel)"
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
