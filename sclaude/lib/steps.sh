#!/usr/bin/env bash
#
# The cycle's definition: the sequence of steps and each one's launch
# parameters.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- the steps ---------------------------------------------------------------
#
# The order here is the cycle's definition: STEPS sets the sequence, STEP_SPEC
# the launch parameters. Adding a step means adding a line to both.

STEPS=(plan code pr review)

# How often to ask GitHub whether the pull request has been merged, in seconds.
#
# The merge is the one part of the cycle that is a person's alone, and step 4
# waits for it rather than exiting and being run again. Half a minute: the wait
# itself is measured in minutes or hours, while somebody who has just pressed
# merge should not sit through a long pause before the cycle notices.
#
# Overridable from the environment for one reader only: the integration bench,
# which drives a whole `sclaude <feature>` and would otherwise spend half a
# minute per poll waiting for a merge its stub will never report. Nothing in
# service sets it, and a shorter interval there costs nothing — the wait is a
# `gh` call, not work.
MERGE_POLL="${MERGE_POLL:-30}"
# Validated, because the value reaches arithmetic. `$((waited + MERGE_POLL))`
# under this script's `set -u` treats a non-numeric value as a name and dies —
# "bash: abc: unbound variable", in the middle of a wait that may have been
# running for hours. A zero is the other way to get it wrong: the loop then asks
# GitHub with no delay at all, which is a rate limit spent on a wait measured in
# hours. Anything that is not a positive integer falls back to the default.
[[ "$MERGE_POLL" =~ ^[1-9][0-9]*$ ]] || MERGE_POLL=30

# How often to look at the issue's column while QA has it, in seconds.
#
# Slower than the merge: QA reads acceptance criteria and clicks through a
# deployment, which is a wait of hours, and each look walks every board the
# issue is on. A minute is still quick enough that moving the card to Done and
# glancing back at the terminal finds the next question already asked.
#
# Overridable and validated for exactly the reasons MERGE_POLL is.
QA_POLL="${QA_POLL:-60}"
[[ "$QA_POLL" =~ ^[1-9][0-9]*$ ]] || QA_POLL=60

# How long step 4 waits for the automatic review before opening its session
# anyway, in seconds. A review takes a few minutes; a check that is still
# running after half an hour is stuck, and the session is where a person looks
# at why.
REVIEW_WAIT_MAX="${REVIEW_WAIT_MAX:-1800}"
[[ "$REVIEW_WAIT_MAX" =~ ^[0-9]+$ ]] || REVIEW_WAIT_MAX=1800

# How many times the preview deploy is tried before the run gives up, and the
# pause between tries in seconds.
#
# The preview is not optional — QA and the merge both wait on it — so a failed
# deploy is tried again rather than handed to the human as an errand. Most
# failures are transient (a Vercel hiccup, a network blip) and a second try a
# few seconds later goes through. Three, because a failure that survives three
# tries is not transient and needs a person to read the log.
#
# The pause is overridable for the benches, where it would only cost time; zero
# is allowed there, unlike the poll intervals, because it is not a loop that
# runs for hours.
PREVIEW_TRIES="${PREVIEW_TRIES:-3}"
[[ "$PREVIEW_TRIES" =~ ^[1-9][0-9]*$ ]] || PREVIEW_TRIES=3
PREVIEW_RETRY_PAUSE="${PREVIEW_RETRY_PAUSE:-15}"
[[ "$PREVIEW_RETRY_PAUSE" =~ ^[0-9]+$ ]] || PREVIEW_RETRY_PAUSE=15

# A step's parameters on one line: model, effort, permission mode, name. As
# four separate case tables this drifted apart, and the name additionally lived
# as a fifth copy inside issue_sync's python block.
declare -A STEP_SPEC=(
  [plan]="opus high plan planning"
  [code]="opus medium auto development"
  [pr]="sonnet medium auto|pull request"
  [review]="opus medium auto review"
)

# A step's parameter field by number: 1 model, 2 effort, 3 mode, 4 name. The
# name is sometimes two words, so a `|` rather than a space separates it from
# the mode: splitting on spaces would break on "pull request".
step_field() {
  local spec="${STEP_SPEC[$1]:-}" head tail
  [[ -n "$spec" ]] || return 1
  head="${spec%%|*}"
  tail="${spec#*|}"
  [[ "$tail" == "$spec" ]] && tail=""
  local -a words=($head)
  case "$2" in
    1) echo "${words[0]}" ;;
    2) echo "${words[1]}" ;;
    3) echo "${words[2]}" ;;
    4) echo "${tail:-${words[3]:-}}" ;;
  esac
}

step_model()  { step_field "$1" 1; }

step_effort() { step_field "$1" 2; }

step_mode()   { step_field "$1" 3; }

# Extra launch flags — one line per argument, because the caller reads them
# through mapfile.
#
# Step 1 gets a hook that rejects writing. Plan mode forbids it too, but exactly
# until the human approves the plan: the approval switches the session into a
# mode where Claude writes code. That must not happen here — development is
# carried out by step 2, with a clean context, and everything written now would
# reach it not as intent but as an unexpected edit in the worktree.
#
# The hook looks at Bash too — and lets reading commands through while forbidding
# writing ones. Verified: with Write blocked the model calmly appends to a file
# through printf, not considering that a way around. And without git log and
# gh issue view step 1 is blind.
#
# A second hook hangs on ExitPlanMode. It puts the plan into .sclaude/local/feature/plan.md
# and reminds about Ctrl+O: the dialogue unfolds over the plan and covers it,
# so it has to be read from the file or in the transcript view. It decides one
# thing only — a plan with no acceptance criteria is denied, which cancels the
# dialogue and sends the plan back to the model with the reason. It never
# allows: that would approve the plan on the human's behalf.
#
# Steps 2-4 get bans: merging, prod and opening a PR before its time are the
# human's steps, and until now only the prompt's text held them back. It held
# them badly through no fault of its own: this machine's
# ~/.claude/settings.json allows Bash entirely and sets auto mode, so every
# command in a step is pre-approved.
#
# The bans are divided by what each mechanism can do — verified live rather than
# taken from the documentation:
#
#   * --disallowed-tools catches a command's direct form and is visible in the
#     command line. A double space does not trouble it, nor does a colon in a
#     script's name.
#   * A rule with a `*` in the middle (`Bash(git push * main)`) silently does not
#     fire, and the rule lets the form with a path (`/usr/bin/vercel`) through.
#
# So "push is allowed, but not to main", --force, --no-verify and all the same
# written through a path are handled by the hook. The overlap is deliberate: the
# flag is read by a human, the hook closes the way around.
#
# The settings are passed as a string rather than a file: that way no temporary
# rubbish appears and neither the project's .claude/settings.json nor the user's
# is touched.
#
# autoMode.environment is passed to steps 2-4 the same way. Auto mode judges
# commands with a classifier, and that one, knowing nothing about worktrees,
# considered a feature's tree a foreign repository: the user's environment has
# one trusted path written into it, hardcoded (~/myapp), while a step works in
# ~/myapp-<feature>. The Local Operations rule calls going into "other repos" a
# step outside the project's boundaries, and ordinary reading fell under
# suspicion. One feature's step 4 got three refusals in a row
# that way — a `gh run view | grep` over another run's log and a `python3 -c`
# parsing YAML for validity — and went around them by downloading the whole log
# into a temporary directory and rewriting the one-line check as a file.
#
# The second thing the classifier does not work out for itself is the
# reversibility of restoring from a revision. The Irreversible Local Destruction
# rule lists `git checkout -- .` and `git reset --hard` and tells itself to
# "presume the tree is dirty": it does not see the tools' output and assumes the
# restore will overwrite unsaved work. The per-file form with a revision fell
# under that. A step 2 was refused on a
# `git checkout <sha> -- <three manual paths>` with which it meant to render the
# pre-merge pages and compare the rendering with the post-change one; without it
# it compared the sources through `git diff` and a normaliser of its own — it
# proved the prose was intact, but not that the rendering was. Tellingly, the
# form without a revision, `git checkout -- <paths>`, passed in the same step: it
# was precisely the revision that was in the way.
#
# The lines below tell the classifier what it will not work out for itself: a
# worktree is the same tree with the same remote, and restoring the named paths
# from this same repository's history is reversible. That is context, not
# permission: not one of the soft_deny rules is switched off,
# `git checkout -- .`, `git restore .`, `git reset --hard` and `git clean` are
# not named and stay under the rule, and prod (Sensitive remote targets) stays
# outside the trust. The step's bans do not depend on them at all — both the flag
# and the hook fire before the classifier.
#
# Every step is also given `mcp__chrome-devtools` as an allow rule. Every step's
# prompt tells it to look at the work in the browser — step 1 through the
# dev-server-read include — yet step 1 runs in plan mode, where each tool not
# marked read-only asks first, and nearly all of that server's tools are such:
# navigate_page, emulate, evaluate_script. Planning 138-fix-responsive-overflow
# stopped on a dialogue for each of them, and the human answered yes every
# time. The dialogue guarded nothing: nothing reaches the repository through
# the browser — evaluate_script changes the DOM until the next reload — and the
# write ban of step 1 is the hook, which does not look at MCP tools at all. In
# steps 2-4 auto mode let the calls through already; the rule only spares the
# classifier a look at each one. The deny list and the hooks still come first.
BROWSER_ALLOW='mcp__chrome-devtools'

# write-guard.py as a PreToolUse entry in JSON, with the arguments given, or
# nothing when there are none.
guard_entry() {
  [[ $# -gt 0 ]] || return 0
  local args; args="$(printf ' %q' "$@")"
  # The path quoted for the shell Claude Code runs the command in: a checkout
  # under a name with a space in it broke the guard.
  python3 -c 'import json, shlex, sys; print(json.dumps({"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash", "hooks": [{"type": "command", "command": "python3 " + shlex.quote(sys.argv[1]) + sys.argv[2], "timeout": 10}]}))' \
    "$HOOKS/write-guard.py" "$args"
}

# For a step: a product's shared rules (.sclaude/team/) are not a step's to
# write, a maintainer's included. Its allow lifts bans, the hook reads the
# tree's copy on every call, and a step that wrote {"allow": [{"command":
# "vercel"}]} there deployed on its next call. Rules are changed by the
# reviews, which a person approves (review_guard_settings), never by the step
# they would free.
team_guard_entry() {
  guard_entry --team
}

# For the sessions that review the work rather than do it: the friction
# review, the retrospective, the monthly deferred review. They read sclaude's
# checkout and change the product, never sclaude itself (write-guard.py
# --readonly), and the team's rules stay the maintainers'. A whole --settings
# value: these sessions have no settings of their own.
review_guard_settings() {
  local -a args=(--readonly "$INSTRUMENTS")
  product_maintainer "${1:-${REPO:-.}}" || args+=(--team)
  printf '%s\n' --settings "{\"hooks\": {\"PreToolUse\": [$(guard_entry "${args[@]}")]}}"
}

# sclaude's checkout as it stands: its HEAD and what is uncommitted, in one
# line. Taken before and after a review session (instruments_unchanged).
instruments_state() {
  printf '%s %s\n' "$(git -C "$INSTRUMENTS" rev-parse HEAD 2>/dev/null)" \
    "$( { git -C "$INSTRUMENTS" status --porcelain; git -C "$INSTRUMENTS" diff HEAD; } 2>/dev/null \
        | md5sum | cut -c1-12)"
}

# Says so, loudly, when a review session changed sclaude's checkout after all.
# The write guard refuses the writes it can name, and a list of commands can
# never name them all — rsync, tar -C, unzip -d, patch, awk -i inplace — so
# what the checkout looks like afterwards is the check that holds for every
# one of them. Nothing is reverted: what changed is for a person to look at.
#
#   instruments_unchanged <state before> <who>
instruments_unchanged() {
  [[ "$(instruments_state)" == "$1" ]] && return 0
  warn ""
  warn "  The $2 changed sclaude's own checkout ($INSTRUMENTS), which it may only read."
  warn "  Look before anything else runs from it: git -C $INSTRUMENTS status; git -C $INSTRUMENTS log -3"
  return 1
}

# The rules the policy layers give a session (sclaude/lib/policy.py): the
# commands and tools it may not use, one Claude rule per line, into the array
# named by $1; the commands it may run without being asked into the one named
# by $2. The product is the main repository, the person this developer.
#
# The feature's tree, when there is one, counts too: a friction review commits
# its rule there, and main's copy will not have it until the merge.
#
# Returns 1, and says why, when the policy cannot be read: a session started
# then would have no --disallowed-tools but the fixed few, the integrations'
# and the product's bans gone without a word.
#
#   policy_rules <deny-array> <allow-array> <step> [tree]
policy_rules() {
  local -n _deny="$1" _allow="$2"
  local step="$3" tree="${4:-}" out line seen="" err
  err="$(mktemp)"
  if ! out="$(python3 "$LIB/policy.py" flags "${REPO:-}" "$(developer_name 2>/dev/null)" "$step" "$tree" 2>"$err")"; then
    warn "  sclaude could not read the session's rules: $(tail -n 1 "$err")" >&2
    rm -f "$err"
    return 1
  fi
  # Read, but not whole: a product's or a person's file that broke the merge
  # was dropped, and the session runs on sclaude's presets alone. Said, since
  # the product's bans are not there.
  [[ -s "$err" ]] && warn "  $(tail -n 1 "$err")" >&2
  rm -f "$err"
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then seen=1; continue; fi
    if [[ -z "$seen" ]]; then _deny+=("$line"); else _allow+=("$line"); fi
  done <<< "$out"
}

# The hook's own arguments: which product's policy, for whom, in which tree.
#
#   policy_hook_args [tree]
policy_hook_args() {
  printf -- '--root %q --person %q' "${REPO:-}" "$(developer_name 2>/dev/null)"
  [[ -n "${1:-}" ]] && printf -- ' --tree %q' "$1"
  return 0
}

step_settings() {
  local step="$1" wt="$2" hook trusted origin

  if [[ "$step" == "plan" ]]; then
    hook="$HOOKS/no-code-in-planning.py"
    # There is no tool allowlist here, and that is a decision rather than an
    # oversight. --tools takes away everything not named in it, and what step 1
    # is busy with is finding its way around the repository: with subagents
    # (Agent), web search, ToolSearch for deferred tools. The list took that
    # away, and the step tripped over "No such tool available" in the middle of
    # its reconnaissance.
    #
    # It gave nothing in return: the only thing it closed off was Write, Edit
    # and NotebookEdit, and the hook below rejects those anyway. And the hook can
    # do what --tools cannot do at all — it sees writing through Bash (printf,
    # tee), which is what the model uses when Write is closed.
    printf '%s\n' --settings "$(python3 - "$hook" "$HOOKS/plan-on-disk.py" "$BROWSER_ALLOW" <<'PY'
import json, shlex, sys


def entry(matcher, script):
    return {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": "python3 " + shlex.quote(script), "timeout": 10}],
    }


print(json.dumps({
    "permissions": {"allow": [sys.argv[3]]},
    "hooks": {"PreToolUse": [
        entry("Write|Edit|NotebookEdit|Bash", sys.argv[1]),
        entry("ExitPlanMode", sys.argv[2]),
    ]},
}))
PY
)"
    return 0
  fi

  hook="$HOOKS/forbidden-commands.py"

  # Supabase MCP's writing tools: schema changes go as migrations through files,
  # as CLAUDE.md requires, rather than through a tool around git. The reading
  # ones (list_tables, execute_sql, get_advisors) stay — the step checks its work
  # with them. Here the rule matches by tool name, and there is no way around it
  # with a string.
  #
  # `vercel` is deliberately not in this list, though it was until a fixing
  # session tripped over it. The flag can only ban the name, and the name covers
  # both `vercel --prod` — a deploy, the human's step — and `vercel env ls`,
  # which reads a value and changes nothing. A session repairing a red preview
  # regression needed the second to tell "wrong bucket" from "wrong keys", was
  # refused, and the human had to run the command by hand while the feature
  # stood. The hook decides it instead: it sees the subcommand, and it also sees
  # the form with a path and the form behind `npx`, which the flag never caught.
  # The commands and tools come from the policy: sclaude's presets (core.json,
  # and the integrations the product uses, Supabase's MCP writing tools among
  # them) and the product's and the person's own rules.
  local -a allow=()
  local -a deny=(
    # The orchestrator brought the step into the feature's tree, and the step
    # has nowhere to go from it: state.json, the dev server and the branch are
    # tied to that directory. This does not break entering it — that goes past
    # the tool: `git worktree add` creates the tree, and the session starts
    # inside it already, through the `cd "$wt"` before claude is called.
    'EnterWorktree'
    'ExitWorktree'
  )
  policy_rules deny allow "$step" "$wt" || return 1

  # Without a path to the tree there is nothing to compose the trust line from;
  # the step then runs as before, with the hooks alone. The orchestrator always
  # passes the path — it is empty only for a call from outside.
  trusted=""
  if [[ -n "$wt" ]]; then
    origin="$(git -C "$wt" remote get-url origin 2>/dev/null)" || origin=""
    trusted="**Trusted repo**: $wt is a linked git worktree of the same"
    trusted+=" repository as ${origin:-the main tree}. The sclaude orchestrator"
    trusted+=" created it for a single feature: same codebase, same remote, a"
    trusted+=" separate directory — a detail of how the work is organised, not"
    trusted+=" a step outside the project. Reading and editing inside it are"
    trusted+=" ordinary local operations, and the repository's usual commands"
    trusted+=" are just as usual in it. Restoring tracked paths inside it from"
    trusted+=" a revision of this same repository (\`git checkout <ref> --"
    trusted+=" <path>\`, \`git restore --source=<ref> <path>\`) is an ordinary"
    trusted+=" reversible local operation here: the content comes from the"
    trusted+=" repo's own history, the paths are named explicitly, and a second"
    trusted+=" checkout undoes it."
  fi

  printf '%s\n' --disallowed-tools "${deny[*]}" --settings "$(python3 - "$hook" "$step" "$trusted" "$BROWSER_ALLOW" "$(team_guard_entry "$wt")" "$(policy_hook_args "$wt")" "${allow[@]}" <<'PY'
import json, shlex, sys

# The path quoted, as in guard_entry: a checkout under a name with a space in it
# made the hook fail to start, and a hook that fails lets everything through.
settings = {"permissions": {"allow": [sys.argv[4]] + sys.argv[7:]}, "hooks": {"PreToolUse": [{
    "matcher": "Bash",
    "hooks": [{"type": "command",
               "command": "python3 %s --step %s %s" % (shlex.quote(sys.argv[1]), shlex.quote(sys.argv[2]), sys.argv[6]),
               "timeout": 10}],
}]}}
# A product's shared rules are not a step's to write (team_guard_entry).
if len(sys.argv) > 5 and sys.argv[5]:
    settings["hooks"]["PreToolUse"].append(json.loads(sys.argv[5]))
# The line about the worktree is context for auto mode's classifier, not
# permission. It arrives empty when the path to the tree is unknown.
if len(sys.argv) > 3 and sys.argv[3]:
    settings["autoMode"] = {"environment": [sys.argv[3]]}
print(json.dumps(settings, ensure_ascii=False))
PY
)"
}

# The epilogue's permissions — the session that writes the "Current status"
# comment on the issue and its parents. Separate from step_settings: that one assembles a cycle
# step's parameters, and this is not a step, so half its work is meaningless
# here — there is nothing to write the worktree trust line about, the feature's
# tree is gone.
#
# Nothing beyond the usual is needed: the session writes comments —
# `gh issue comment` and a `gh api` PATCH on its own comment — and neither is
# banned anywhere. It no longer edits a description at all. To check what the
# product does before writing "Current behaviour" it reads code — `git fetch`,
# `git grep` and `git show` against origin/main, `gh pr diff` — and none of
# those is banned either.
#
# `gh pr merge` is banned here too (core.json), and not out of inertia: the session is tasked, among
# other things, with honestly writing "waiting for the merge", and it must not
# have the means to fix that itself. `git push` is banned entirely rather than
# as for steps 2-4: the feature's branch is deleted, there is nothing to push,
# and the only push available is to main.
status_settings() {
  local hook="$HOOKS/forbidden-commands.py"
  local -a deny=(
    'Bash(vercel:*)'
    'Bash(npx vercel:*)'
    'Bash(gh pr create:*)'
    'Bash(git push:*)'
    'EnterWorktree'
    'ExitWorktree'
  ) allow=()
  # And the product's own bans, from its policy: a status session runs nothing
  # the product forbids a step to run. The hook is called with --step status,
  # a step no policy names, so only the shared rules and the push parsing apply.
  policy_rules deny allow status || return 1
  printf '%s\n' --disallowed-tools "${deny[*]}" --settings "$(python3 - "$hook" "$(policy_hook_args)" <<'PYSTATUS'
import json, shlex, sys

print(json.dumps({"hooks": {"PreToolUse": [{
    "matcher": "Bash",
    "hooks": [{"type": "command",
               "command": "python3 %s --step status %s" % (shlex.quote(sys.argv[1]), sys.argv[2]),
               "timeout": 10}],
}]}}))
PYSTATUS
)"
}

step_title() { step_field "$1" 4; }

# "step 2/4 — development", or "all steps done" for a closed feature.
step_label() {
  if [[ "$1" == "done" ]]; then
    echo "all steps done"
  else
    echo "$(($(step_index "$1") + 1))/${#STEPS[@]} $(step_title "$1")"
  fi
}

step_index() {
  local want="$1" i=0
  for s in "${STEPS[@]}"; do
    [[ "$s" == "$want" ]] && { echo "$i"; return 0; }
    i=$((i + 1))
  done
  echo "-1"
}

step_next() {
  local i; i="$(step_index "$1")"
  [[ "$i" -lt 0 ]] && return 1
  i=$((i + 1))
  [[ "$i" -ge "${#STEPS[@]}" ]] && return 1
  echo "${STEPS[$i]}"
}

# --- going back a step -------------------------------------------------------

# Puts the cycle back on a step, clearing what the steps named after it recorded.
#
#   step_rewind_to <wt> <target> [step...]
#
# The target becomes the current step; each step named after it has its `done`
# and `finished` cleared. A closing time from a previous pass is the thing that
# must not be left behind: in the issue's summary it claims a completeness that
# no longer exists.
#
# Three callers wanted these same four lines and each wrote them out: the
# regression's rewind after a red deployed stage, `cmd_replan` taking a feature
# back to planning, and the QA hand-back. They differ only in which steps they
# name — one, all four, one — so that is the argument rather than three copies
# of the body.
#
# The `done` check before clearing is not tidiness: without it a step that had
# never closed would have `finished` written as null and appear in the state as
# a step that ran, which is a different lie from the one being fixed.
#
# Silent about the move itself. Each caller has its own sentence for why the
# cycle went back, and a line here would either repeat it or contradict it.
step_rewind_to() {
  local wt="$1" target="$2"; shift 2
  local state="$wt/.sclaude/local/feature/state.json" s

  for s in "$@"; do
    [[ "$(state_get "$state" "steps.$s.done" 2>/dev/null || echo false)" == "true" ]] || continue
    state_set "$state" "steps.$s.done" false
    state_set "$state" "steps.$s.finished" null
  done

  state_set "$state" step "$target"
}

# The sessions a step ran in. See session_runs (state.sh).
# How many review threads the automatic review handed a review session: those
# open when it began, plus every one opened while it ran. A session can live
# through several rounds — it pushes, the review closes some and opens others,
# and it carries on — so a count taken at the door alone undersells it.
#
#   run_comments <wt> <session> <pr>
#
# Called when the session opens (the first time it fixes the starting count:
# open then, less any opened since the session's start) and again when it
# ends or is resumed: then it is that starting count plus every thread opened
# since the session's start. Shown beside its row in the issue
# ("review (4) - 5 comments").
run_comments() {
  local wt="$1" session="$2" pr="$3" repo
  [[ -n "$pr" && "$pr" != "null" && -n "$session" ]] || return 0
  repo="$(gh_repo 2>/dev/null || true)"
  [[ -n "$repo" ]] || return 0
  python3 - "$wt/.sclaude/local/feature/state.json" "$session" "$LIB/pr_context.py" "$wt" "$pr" "$repo" <<'PY' 2>/dev/null || true
import json, subprocess, sys
path, session, ctx, wt, pr, repo = sys.argv[1:7]
with open(path) as fh:
    data = json.load(fh)
runs = ((data.get("steps") or {}).get("review") or {}).get("runs") or []
mine = [r for r in runs if r.get("session") == session]
if not mine:
    sys.exit(0)
run = mine[-1]
out = subprocess.run([sys.executable, ctx, "--threads", wt, pr, repo, run.get("started") or ""],
                     capture_output=True, text=True, timeout=120).stdout.split()
if len(out) != 2 or not all(x.isdigit() for x in out):
    sys.exit(0)
opened, new = int(out[0]), int(out[1])
if "comments_start" not in run:
    run["comments_start"] = max(opened - new, 0)
run["comments"] = run["comments_start"] + new
with open(path, "w") as fh:
    json.dump(data, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
}

step_run() {
  session_runs "$1/.sclaude/local/feature/state.json" "steps.$2" "$3" "${4:-}" "${5:-}"
}

# The friction review's key for one session of a step: `<step>-<n>`, where n is
# the session's row in the issue — its position in steps.<step>.runs.
#
#   step_run_key <state> <step> [session]
#
# A review follows every session rather than every step, so the key has to
# name the session: keyed by the step alone, the review step's six rotated
# rounds shared one node, and the issue could show it on one row only. The
# shape is the fixing sessions' (`fix-preview-1`), and it is derived from the
# same thing the table counts, so writer and reader cannot drift apart.
#
# Without a session, the step's latest run. A step with no runs at all — a
# feature from before them — answers with its bare name, the old key.
step_run_key() {
  python3 - "$1" "$2" "${3:-}" <<'PY' 2>/dev/null || echo "$2"
import json, sys
path, step, session = sys.argv[1:4]
with open(path) as fh:
    runs = ((json.load(fh).get("steps") or {}).get(step) or {}).get("runs") or []
runs = [r for r in runs if isinstance(r, dict)]
number = len(runs)
if session:
    mine = [i for i, r in enumerate(runs, start=1) if r.get("session") == session]
    number = mine[-1] if mine else 0
print("%s-%d" % (step, number) if number else step)
PY
}

# The key of the latest step session of the feature, by start: what a review
# asked for by hand (`sclaude friction`) is about. The current step is the
# wrong answer once a step has closed — its successor has no session yet —
# and falls out only when no step has runs.
last_run_key() {
  python3 - "$1" <<'PY' 2>/dev/null || true
import json, sys
with open(sys.argv[1]) as fh:
    steps = json.load(fh).get("steps") or {}
best = None
for name, node in steps.items():
    runs = [r for r in ((node or {}).get("runs") or []) if isinstance(r, dict)]
    for number, run in enumerate(runs, start=1):
        started = run.get("started") or ""
        if best is None or started >= best[0]:
            best = (started, "%s-%d" % (name, number))
if best:
    print(best[1])
PY
}

# The step session a friction key names, or nothing: `review-3` is the third
# run of `review`; a bare step name is that step's recorded session. A fixing
# session's key (`fix-preview-1`) names no step session and answers nothing.
step_run_session() {
  python3 - "$1" "$2" <<'PY' 2>/dev/null || true
import json, re, sys
path, key = sys.argv[1:3]
with open(path) as fh:
    steps = json.load(fh).get("steps") or {}
m = re.fullmatch(r"([a-z]+)-([0-9]+)", key)
if m and m.group(1) in steps:
    runs = [r for r in (steps[m.group(1)].get("runs") or []) if isinstance(r, dict)]
    n = int(m.group(2))
    if 0 < n <= len(runs):
        print(runs[n - 1].get("session") or "")
elif key in steps:
    print((steps[key] or {}).get("session") or "")
PY
}

# Closes the steps a merged pull request leaves with nothing to do.
#
#   step_close_merged <wt>
#
# The mirror of step_rewind_to: `pr` and `review` are marked done, the cycle is
# put on `done`, and the reopening marks go. A time already set is kept — step 3
# has its own, and it is not today's.
#
# Two callers. run_step, entering either step on a merged branch; and
# remind_prod, which carries a preview fix on to QA and the merge in the same
# run and never comes back to the review that fix reopened. Without the second
# the issue's summary kept "step 4/4 review · in progress" and no finishing
# time for good — the worktree went, and with it any run that could close it.
step_close_merged() {
  local wt="$1"
  local state="$wt/.sclaude/local/feature/state.json" s now
  now="$(date -Iseconds)"
  for s in pr review; do
    [[ "$(state_get "$state" "steps.$s.done" 2>/dev/null || true)" == "true" ]] \
      || step_run "$wt" "$s" close
    state_set "$state" "steps.$s.done" true
    if [[ "$(state_get "$state" "steps.$s.finished" || true)" =~ ^(|null)$ ]]; then
      state_set "$state" "steps.$s.finished" "$now"
    fi
  done
  state_set "$state" step "done"
  state_set "$state" reopened null 2>/dev/null || true
  state_set "$state" reopened_pr null 2>/dev/null || true
  state_set "$state" reopened_by null 2>/dev/null || true
}
