#!/usr/bin/env bash
#
# The repository and a feature's state: where the root is and which features are
# in progress.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- the repository ----------------------------------------------------------

# The repository's main worktree — the one all the others branch off. We look for
# it from the current directory so that sclaude works from inside a feature's
# worktree too.
main_repo() {
  local common
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  # The main worktree's .git lies inside the repository itself; for linked
  # worktrees git-common-dir points to the same place, so this is enough.
  dirname "$common"
}

# What an older sclaude left in a product, put where this one reads it.
#
# Everything sclaude keeps in a product moved into .sclaude/: a tree's working
# state from .feature/ to .sclaude/local/feature/, the config from
# .sclaude.json to .sclaude/config.json. The state is machine-local and moved
# here, in the main repository and every worktree, so a feature in flight is
# not lost. The config is tracked, and moving it is a change to the product,
# by its own pull request, so it is only said, every run, until it is done.
#
# Not while another sclaude runs: one started before the move reads its state
# from .feature/ and would lose it mid-step. And git is told to ignore the new
# place before anything lands there, since a tree made by an older sclaude
# excludes only .feature, and a step's `git add -A` would put the state files
# in its pull request.
layout_migrate() {
  local wt others=""
  while IFS= read -r wt; do
    [[ -d "$wt/.feature" && ! -e "$wt/.sclaude/local/feature" ]] || continue
    if [[ -z "$others" ]] && declare -F instruments_others >/dev/null; then
      others="$(instruments_others)" || others="none"
    fi
    if [[ -n "$others" && "$others" != "none" ]]; then
      info "  ${wt}/.feature stays where it is while another sclaude runs ($others)"
      continue
    fi
    declare -F scratch_hide >/dev/null && scratch_hide "$wt"
    mkdir -p "$wt/.sclaude/local" && mv "$wt/.feature" "$wt/.sclaude/local/feature" \
      && info "  moved ${wt}/.feature to .sclaude/local/feature (sclaude keeps its state there now)"
  done < <(git -C "$REPO" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')
  if [[ -f "$REPO/.sclaude.json" && ! -f "$REPO/.sclaude/config.json" ]]; then
    warn "  $REPO has the old .sclaude.json, which sclaude no longer reads: no"
    warn "  regression, board or environments apply until it is .sclaude/config.json"
    warn "  (git mv .sclaude.json .sclaude/config.json, by the product's own pull request)."
  fi
  local old
  if declare -F envs >/dev/null && old="$(envs old "$REPO")"; then
    warn "  $old"
  fi
  return 0
}

require_repo() {
  REPO="$(main_repo)" || die "not a git repository: $(pwd)"
  [[ -n "$REPO" ]] || die "could not find the repository root"
  layout_migrate
  # The board's column and field names are the project's (project.sh).
  board_load
}

# --- a feature's state -------------------------------------------------------
#
# We read JSON with python rather than grep: a field may move, and a wrong value
# read silently here means launching the wrong step.

state_get() {
  local file="$1" path="$2"
  python3 - "$file" "$path" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        node = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
for key in sys.argv[2].split('.'):
    if not isinstance(node, dict) or key not in node:
        sys.exit(1)
    node = node[key]
if node is None:
    sys.exit(1)
print(node if not isinstance(node, bool) else str(node).lower())
PY
}

state_set() {
  local file="$1" path="$2" value="$3"
  python3 - "$file" "$path" "$value" <<'PY'
import json, sys
path, keys, value = sys.argv[1], sys.argv[2].split('.'), sys.argv[3]
with open(path) as fh:
    data = json.load(fh)
node = data
for key in keys[:-1]:
    node = node.setdefault(key, {})
# Numbers as numbers: issue puts a number here, and cmd_new writes it as an int
# directly. As a string next to a number in the same field, the state would read
# differently depending on where the feature started from.
if value.isdigit():
    node[keys[-1]] = int(value)
else:
    node[keys[-1]] = {'true': True, 'false': False, 'null': None}.get(value, value)
with open(path, 'w') as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write('\n')
PY
}

# A new claude session id. Named in advance by every launch, so the id is in
# the state before the conversation exists and survives any way of leaving it.
new_session_id() {
  python3 -c 'import uuid; print(uuid.uuid4())'
}

# The claude conversations a step or a friction review ran in, for the summary
# in the issue.
#
#   session_runs <state> <node> open  <session>   before claude starts
#   session_runs <state> <node> end   <session>   after it exits
#   session_runs <state> <node> drop  <session>   it exited without a conversation
#   session_runs <state> <node> stall <session>   the same, kept as a record
#   session_runs <state> <node> close             the node closed; its last run did it
#   session_runs <state> <node> finish <session> [outcome]   end, then close
#
# <node> is a dotted path — `steps.review`, `friction.fix-preview-1` — and the
# list lives at <node>.runs, one entry per conversation. The same conversation
# entered several times is one entry: its start is the first entry, its end the
# last exit — `open` keeps a start it already has and `end` always overwrites.
# A new conversation is a new entry, and the summary shows each of them.
#
# JSON written directly rather than through state_set, which carries scalars
# only. The node's own `started`/`finished` stay as they were: metrics and the
# review's idle clock read them.
session_runs() {
  local file="$1" node="$2" op="$3" session="${4:-}" outcome="${5:-}"
  python3 - "$file" "$node" "$op" "$session" "$(date -Iseconds)" "$outcome" <<'PYRUN' 2>/dev/null || true
import json, sys
path, dotted, op, session, now, outcome = sys.argv[1:7]
with open(path) as fh:
    data = json.load(fh)
node = data
for key in dotted.split("."):
    node = node.setdefault(key, {})
runs = node.get("runs")
if not isinstance(runs, list):
    runs = []
    # A node that began before this field: its recorded session is the first
    # run, and it began when the node did.
    if op == "open" and session and node.get("session") == session and node.get("started"):
        runs.append({"session": session, "started": node["started"]})
mine = [r for r in runs if r.get("session") == session] if session else []
if op == "open":
    if not mine:
        runs.append({"session": session, "started": now})
    # Resumed after a stall or a close on its marker: the conversation is
    # going now, whatever it did at the door or how it ended the first time.
    for r in mine:
        r.pop("stalled", None)
        r.pop("outcome", None)
        # A step rewound (step_rewind_to writes its done as false) and its
        # session resumed: the run that closed it is open again. Only there:
        # a retrospective resumed without an answer keeps its last end, and
        # its node has no done of its own.
        if node.get("done") is False:
            r.pop("done", None)
if op in ("end", "finish"):
    for r in mine:
        r["finished"] = now
        # A session ended by the orchestrator rather than by a person says why
        # — the review step's rotation: "fixes confirmed". Shown in the issue
        # in place of "interrupted", which is what an earlier row would read.
        # An end without one clears an earlier reason: a session closed on
        # its marker and resumed, then left by the person, was interrupted.
        if op == "end":
            if outcome:
                r["outcome"] = outcome
            else:
                r.pop("outcome", None)
if op == "drop":
    runs = [r for r in runs if not (r.get("session") == session and not r.get("finished"))]
if op == "stall":
    for r in mine:
        r["stalled"] = True
if op in ("close", "finish"):
    if runs:
        runs[-1]["done"] = True
        # For a friction review, what it came to (fixed, reviewed): the node's
        # own fields describe only the latest review, and an earlier row
        # would otherwise lose its answer.
        if outcome:
            runs[-1]["outcome"] = outcome
node["runs"] = runs
with open(path, "w") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PYRUN
}

# The sessions directory in ~/.claude/projects: the worktree's path with
# everything but letters and digits replaced by a hyphen. Verified against every
# directory on this machine.
#
# This has already lived as three copies — in capture_plan, run_friction and
# collect_denials — and nothing stopped them diverging. Here we do without
# python: bash substitution does exactly the same, and no process is started per
# call.
transcript_dir() {
  local encoded="${1//[^a-zA-Z0-9]/-}"
  echo "$HOME/.claude/projects/$encoded"
}

# Whether a recorded session id is live: prints it if the conversation took
# place, and nothing if it did not.
#
# The id is written before claude is launched, and not every launch survives as
# far as a conversation: should claude refuse to start — or hit a limit at the
# very start — the state keeps the id of a session that does not exist. From
# then on it is poison: a `--resume` on it exits with "No conversation found
# with session ID", and the resume branch is chosen precisely by a non-empty id,
# so returning will never work again. That is how one feature
# stood idle for a day.
#
# The boundary is the transcript file: every conversation that took place has
# one, and only those do. No file means there was no session, and the id must be
# forgotten rather than repaired; an empty one leads the caller into the
# first-launch branch.
#
# A separate function rather than a line inside run_step, because there is now
# more than one place: the cycle's step, the friction review, the epilogue. Every
# new place written afresh would breed the same trouble — and it has already cost
# a day of standing still.
live_session() {
  local wt="$1" session="$2"
  [[ -n "$session" && "$session" != "null" ]] || return 1
  [[ -f "$(transcript_dir "$wt")/$session.jsonl" ]] || return 1
  echo "$session"
}

# Did the session actually run, or did claude exit at the door?
#
# Both callers used to ask this of the wall clock — "did it live five seconds?"
# — and the clock answers a different question. It times the wrapper: the
# launch, the prompt being assembled, the process winding down. A session that
# died on entry can spend seven seconds doing that, and seven is more than five,
# so the check passed and the caller went on to close a review that had read
# nothing. That is how one feature got `fix-preview-3`: 0.2 seconds of
# conversation, not one word from the model, marked `done`.
#
# The transcript is the honest witness. A session that ran leaves at least one
# `assistant` record; one that refused leaves only the scaffolding — the mode,
# the title, the attachments. So we count assistant records, and the answer
# does not depend on how long anything took.
#
# No transcript at all also means it never ran: --session-id writes the file as
# the conversation starts, so its absence is not a timing race.
session_started() {
  local wt="$1" session="$2"
  local file
  file="$(transcript_dir "$wt")/$session.jsonl"
  [[ -f "$file" ]] || return 1
  python3 - "$file" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as fh:
        for line in fh:
            try:
                if json.loads(line).get("type") == "assistant":
                    sys.exit(0)
            except ValueError:
                continue
except OSError:
    pass
sys.exit(1)
PY
}

# Which friction review is unfinished, if any: prints its key, or nothing.
#
# The reviews are kept per key — `friction.<step>` for a step's review,
# `friction.fix-<stage>-<n>` for a fixing session's — because one flat slot
# could hold only the latest: the review after step 3 overwrote the one after
# step 2, and its session id was gone. Nothing read that id afterwards, so the
# loss was invisible; it became visible the moment the issue's summary wanted
# to name every review.
#
# Five places ask "is something unfinished?" — run_friction, the action list,
# cmd_resume, cmd_friction, cmd_reset — and each of them used to read one key.
# Under the per-key shape that question is a scan, and a scan written five times
# is five chances to write it differently. Hence one function.
#
# Unfinished means: a session id was recorded and `done` is not true. That is
# the same pair the flat version tested, only now over every key.
friction_pending() {
  python3 - "$1" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        reviews = json.load(fh).get("friction") or {}
except (OSError, ValueError):
    sys.exit(1)
# A dict of dicts is the new shape. The old flat one had "session" as a direct
# key, and a feature written by an older sclaude could still be in flight — it
# is reported under its own name so the caller resumes it rather than losing it.
if isinstance(reviews.get("session"), str) and not reviews.get("done"):
    print(reviews.get("after") or "?")
    sys.exit(0)
for key, node in reviews.items():
    if not isinstance(node, dict):
        continue
    if node.get("session") and not node.get("done"):
        print(key)
        sys.exit(0)
sys.exit(1)
PY
}

# The verdict a friction review left behind: prints `kind<TAB>note`, or nothing.
#
# The review decides the one thing no amount of reading the commits recovers:
# whether a restriction was lifted or confirmed as deliberate. A `git log` over
# the review's commits answers the first and is silent about the second — a
# review that read every entry, found each ban working as intended and changed
# nothing leaves no commit at all, and so left no trace in the issue beyond the
# word `reviewed`.
#
# So the review says it in words, as the last line it prints, and we read that
# line back out of its transcript. Not a file it writes: the review runs in
# sclaude's checkout with the feature's tree outside its scope, and widening that
# scope to let it write one bookkeeping file would hand the session that edits
# the orchestrator a writable path into the product — the very confusion
# _friction.py's log_path docstring records as having happened once already.
#
# The transcript is the same witness session_started uses, read the same way:
# assistant records, `message.content[]` blocks of type `text`. We take the
# LAST such line, because a session that was interrupted and resumed may have
# printed one per attempt and only the final one describes what was actually
# left behind.
friction_verdict() {
  local wt="$1" session="$2" file
  [[ -n "$session" && "$session" != "null" ]] || return 1
  file="$(transcript_dir "$wt")/$session.jsonl"
  [[ -f "$file" ]] || return 1
  python3 - "$file" <<'PY' 2>/dev/null
import json, re, sys

# The kinds the prompts offer. Anything else is not a verdict: the model was
# quoting the instruction back, or writing about the line rather than printing
# it, and a wrong word here would reach the issue as though it were a decision.
KINDS = ("lifted", "deliberate", "deferred", "mixed")
PATTERN = re.compile(r"^\s*sclaude-verdict:\s*(\w+)\s*(?:[—:-]\s*(.*))?$")

found = None
try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # Cheap check before the parse, as in collect-denials.py: a review's
            # transcript is large and almost every line is not this one.
            if "sclaude-verdict" not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                for text_line in (block.get("text") or "").splitlines():
                    match = PATTERN.match(text_line)
                    if not match:
                        continue
                    kind = match.group(1).lower()
                    if kind in KINDS:
                        found = (kind, " ".join((match.group(2) or "").split()))
except OSError:
    sys.exit(1)

if not found:
    sys.exit(1)
print("%s\t%s" % found)
PY
}

# --- the epilogue's state ----------------------------------------------------
#
# The epilogue — the session that writes "Current status" to the issue and its
# parents — is the only thing with nowhere reliable to keep its state in the
# feature's tree. It runs before the cleanup, but one that broke off is finished
# later (`sclaude epilogue`), possibly after the cleanup has removed the tree
# along with state.json. And it can be interrupted exactly like everything else — and was
# interrupted silently: the feature is already `done`, the menu will not show
# it, and nobody learns that the section in the issue stayed as it was.
#
# So it has a file of its own — and that lies outside the repositories
# altogether: ~/.claude/sclaude/epilogue/<feature>.json.
#
# At first it lay in the repository itself, and that was a mistake. $REPO is the
# product's tree, foreign to sclaude: steps 2-4 work next to it, where a
# `git add -A` is an everyday thing, and a service directory with session ids
# would ride into somebody else's commit. A line in .gitignore would have to be
# kept in every repository sclaude looks after — and added there by us at that.
#
# In the home directory there is no such worry at all, and the place is right in
# meaning: this is one machine's state, exactly like the session transcripts that
# lie there too.
#
# The feature's name is in the file's name: it has already been through slugify,
# so it never contains a slash or dots — such a name will not lead out of the
# directory.
epilogue_dir() {
  echo "$HOME/.claude/sclaude/epilogue"
}

epilogue_state() {
  local slug="$1" dir; dir="$(epilogue_dir)"
  mkdir -p "$dir" 2>/dev/null || return 1
  local file="$dir/$slug.json"
  # We create not only a missing file but an unreadable one too. Writing the
  # state is not atomic — python truncates the file and writes it afresh — so an
  # interruption at exactly that instant leaves an empty or truncated file. From
  # then on it is dead: state_get says nothing, state_set dies parsing the JSON,
  # and the session id is not written at all — that is, the epilogue becomes
  # unrecoverable again, from the very trouble this file was created for.
  if [[ ! -s "$file" ]] || ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' \
       "$file" 2>/dev/null; then
    echo '{}' > "$file" || return 1
  fi
  echo "$file"
}

# Remove the epilogue's state: it has done its work.
#
# This file's whole point is to survive an interruption. It has survived — or
# was not needed at all — and there is no longer any reason to keep it: nobody
# reads a closed record, neither pending_epilogues nor the menu nor the issue.
# Leaving it "just in case" would mean accumulating a file per completed feature
# for ever.
#
# Two callers come here: run_status, having closed the epilogue, and
# cmd_abandon — an abandoned feature has no use for a waiting epilogue.
#
# Silently and without dying: the file may be absent (the epilogue ran without
# state — epilogue_state did not get created), and that is no reason to bring
# down either the end of a successful cycle or the abandoning of a feature.
epilogue_forget() {
  local slug="$1"
  [[ -n "$slug" ]] || return 0
  rm -f "$(epilogue_dir)/$slug.json" 2>/dev/null || true
}

# An unclosed epilogue's age as a human string: "2h ago", "3d ago". Needed in
# the offer to finish it: an interruption a minute ago and one last week are
# different news, and are decided differently.
epilogue_age() {
  local started="$1"
  [[ -n "$started" && "$started" != "null" ]] || { echo "at an unknown time"; return 0; }
  local then now delta
  then="$(date -d "$started" +%s 2>/dev/null)" || { echo "at an unknown time"; return 0; }
  now="$(date +%s)"
  delta=$((now - then))
  if   [[ "$delta" -lt 3600 ]];  then echo "$((delta / 60))m ago"
  elif [[ "$delta" -lt 86400 ]]; then echo "$((delta / 3600))h ago"
  else                                echo "$((delta / 86400))d ago"
  fi
}

# Every unclosed epilogue: prints "<slug>\t<file>", one per line.
# Empty output is normal: usually there are none at all.
pending_epilogues() {
  local dir file slug; dir="$(epilogue_dir)"
  [[ -d "$dir" ]] || return 0
  for file in "$dir"/*.json; do
    [[ -f "$file" ]] || continue
    # The file's very existence is the "waiting": a closed epilogue deletes its
    # own file. The check for done stays as insurance against a record left over
    # from the previous arrangement — it costs little, whereas working out later
    # "why the menu is offering something already done" costs a lot.
    [[ "$(state_get "$file" done || echo false)" == "true" ]] && continue
    [[ -n "$(state_get "$file" session || true)" ]] || continue
    slug="$(basename "$file" .json)"
    printf '%s\t%s\n' "$slug" "$file"
  done
}

# Every feature under sclaude's management: the worktrees that have a
# .sclaude/local/feature/state.json. Prints "<slug>\t<worktree>\t<step>", one line per
# feature.
list_features() {
  git -C "$REPO" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree /{print substr($0, 10)}' \
    | while read -r wt; do
        local_state="$wt/.sclaude/local/feature/state.json"
        [[ -f "$local_state" ]] || continue
        slug="$(state_get "$local_state" feature)" || continue
        step="$(state_get "$local_state" step)" || step="?"
        printf '%s\t%s\t%s\n' "$slug" "$wt" "$step"
      done
}

# Also where a recorded run (terminal.sh) is tied to the feature it works on,
# and its tab named for it: every command that names a feature comes through
# here.
#
#   feature_worktree <slug> [quiet]
feature_worktree() {
  local wt
  wt="$(list_features | awk -F'\t' -v want="$1" '$1 == want { print $2; found = 1 } END { exit !found }')" \
    || return 1
  # quiet: a report about the feature (cmd_flow), not work on it — the
  # terminal's record and the tab's title are left as they are.
  if [[ "${2:-}" != quiet ]]; then
    declare -F term_attach >/dev/null && term_attach "$wt"
    declare -F tab_title >/dev/null && tab_title "$1"
  fi
  printf '%s\n' "$wt"
}

# --- the cycle's record ------------------------------------------------------
#
# One line per finished feature, appended to ~/.claude/sclaude/cycles.jsonl
# before the worktree goes. Everything the cycle measured about itself lives in
# .sclaude/local/feature/state.json, and that file dies with the tree: until now no feature's
# timings, fixing attempts or friction verdicts outlived the clean-up, so the
# questions they answer — is the cycle getting faster, which step holds it up,
# are two fixing attempts enough — could not be asked at all.
#
# Outside every repository, for the reason epilogue_state and the QA watch are:
# $REPO is the product's tree, where steps 2-4 work and `git add -A` is an
# everyday thing, and a service file with timings would ride into somebody
# else's commit.
#
# Silent and never fatal. A record that cannot be written is a measurement lost,
# and losing one must not stand in the way of cleaning up a merged feature or
# abandoning a dead one. The whole call is best-effort down to the `|| true`.
#
# `outcome` says how the feature left — `done` for a merged one, `dropped` for
# an abandoned one. They are kept in the same file and must never be averaged
# together: an abandoned feature's timings describe a decision, not a cycle.
metrics_append() {
  local wt="$1" outcome="$2" state="$1/.sclaude/local/feature/state.json"
  [[ -f "$state" ]] || return 0
  # The product, named in the record: the state never carried it, and every
  # record said "repo": null — nothing to tell two products' records apart by.
  local repo="${REPO:-}"
  [[ -n "$repo" ]] || repo="$(cd "$wt" 2>/dev/null && main_repo)" || repo=""
  SCLAUDE_DEVELOPER="$(developer_name 2>/dev/null || true)" SCLAUDE_REPO="$repo" \
    python3 "$LIB/metrics.py" "$state" "$outcome" 2>/dev/null || true
  # To the product team's own repository, where its .sclaude/config.json names
  # one under `metrics` — this product's records only (metrics.py). In the
  # background: a push over the network has no business delaying the clean-up
  # of a merged feature, and a failure only means the next record carries this
  # one along with it.
  local dev url
  dev="$(developer_name 2>/dev/null || true)"
  url="$(project_get metrics "$repo" 2>/dev/null || true)"
  if [[ -n "$dev" && -n "$url" && -n "$repo" && -z "${SCLAUDE_NO_SYNC:-}" ]]; then
    ( python3 "$LIB/metrics.py" publish "$dev" "$url" "$repo" >/dev/null 2>&1 & )
  fi
  # A finished feature is when the DORA numbers move: rebuilt now, not at the
  # next stale start.
  dora_refresh "$repo" force
}

# The product's DORA page (dora.py), rebuilt in the background: `sclaude`
# asks on every conversational start, and dora.py does nothing while the page
# is younger than SCLAUDE_DORA_EVERY. `force` rebuilds whatever its age.
#
# Only where there is something to read it from — a Vercel link or a GitHub
# remote. A bench's repository has neither, and a process left running after
# the bench removed its tree is noise in every test that counts them.
# setsid, so neither the terminal closing nor a step's process group ending
# takes a minute of network calls down halfway.
dora_refresh() {
  local repo="$1" force="${2:-}"
  [[ -n "$repo" && -d "$repo/.git" && -z "${SCLAUDE_NO_SYNC:-}" ]] || return 0
  [[ -f "$repo/.vercel/project.json" ]] \
    || git -C "$repo" remote get-url origin 2>/dev/null | grep -q 'github\.com' \
    || return 0
  ( cd / && exec setsid python3 "$LIB/dora.py" refresh "$repo" ${force:+--force} \
      </dev/null >/dev/null 2>&1 & )
}
