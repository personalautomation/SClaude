#!/usr/bin/env bash
#
# The deferred friction, and its monthly review.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# A friction review decides each entry: lift the restriction, or keep it as a
# deliberate ban. Some entries are neither — one feature's worth of evidence
# is not enough to call them, and the rules sessions propose for a project's
# CLAUDE.md are of that kind too. Decided one at a time, after the session
# that met them, such things were either applied on one data point or lost in
# a report nobody answered. So the reviews put them off into a permanent file,
# and once a month the file is read as a whole: a class that came back ten
# times is a different decision from one seen once.
#
# The entries are the product's: what friction teaches is how the product
# customises sclaude, and it belongs with the rest of that. They live in the
# person's rules folder (product_rules_dir), `.sclaude/team/deferred/` for the
# product's maintainers and `.sclaude/people/<name>/deferred/` for everybody
# else, one file per feature, `<feature>.tsv`, written in that feature's
# worktree and committed on its branch. One file per feature because two
# features' branches appending to one shared file conflicted at every second
# merge; and the review's own state, the date of the last review, is a file
# of its own, `last-reviewed`, that only the monthly review writes. A
# maintainer's monthly review reads every folder of the product; anybody
# else's, their own.
#
# A line, tab-separated: date, project, feature, step, class, what happened.
# No field holds a tab, and step and class are single words. Class
# `sclaude-default` marks something about sclaude itself — a preset wrong for
# every product, or a bug in its code: the product works around it, and
# changing sclaude is a deliberate pull request to it.
#
# No timer starts the review: it is a conversation, and a conversation needs
# a person at a terminal. sclaude offers it when it is opened in a product and
# a month has passed since `last-reviewed`, or since the oldest entry.

DEFERRED_DAYS=30

# This person's deferred file for a feature, in a tree of the product: the
# feature's worktree while it runs, the main tree otherwise.
#
#   deferred_file <tree> [feature]
deferred_file() {
  local tree="${1:-${REPO:-.}}" feature="${2:-general}"
  echo "$(product_rules_dir "$tree")/deferred/${feature}.tsv"
}

# Creates the folder for the file, and the file, empty, if they are not there
# yet: no header, so a reader of tab-separated lines meets nothing but
# entries. The format is the one this file's head describes. Silent; returns 1
# when it could not.
#
#   deferred_ensure <tree> [feature]
deferred_ensure() {
  local file; file="$(deferred_file "${1:-}" "${2:-}")"
  [[ -f "$file" ]] && return 0
  mkdir -p "$(dirname "$file")" 2>/dev/null || return 1
  : > "$file" 2>/dev/null || return 1
}

# The deferred folders the monthly review reads in a tree: every one in the
# product for a maintainer, only one's own for anybody else. One a line.
#
#   deferred_dirs [tree]
deferred_dirs() {
  local tree="${1:-${REPO:-.}}" d
  if product_maintainer "$tree"; then
    for d in "$tree/.sclaude/team/deferred" "$tree"/.sclaude/people/*/deferred; do
      [[ -d "$d" ]] && echo "$d"
    done
  else
    d="$(product_rules_dir "$tree")/deferred"
    [[ -d "$d" ]] && echo "$d"
  fi
  return 0
}

# The deferred folders as git pathspecs, every person's: whatever is under
# them is a log of entries and nothing else.
DEFERRED_PATHSPECS=(':(glob).sclaude/team/deferred/**' ':(glob).sclaude/people/*/deferred/**')
DEFERRED_EXCLUDES=(':(exclude,glob).sclaude/team/deferred/**' ':(exclude,glob).sclaude/people/*/deferred/**')

# How many commits a range holds besides those that only touch the deferred
# folders: what a staleness or drift count should see, since entries alone ship
# nothing and are no reason to merge (deferred_to_main). Merges and empty
# commits count, as in a plain rev-list --count.
#
#   deferred_rev_count <git dir> <rev-list args...>
deferred_rev_count() {
  local dir="$1"; shift
  local total only
  total="$(git -C "$dir" rev-list --count "$@" 2>/dev/null)" || return 1
  only="$(deferred_only_revs "$dir" "$@" | grep -c .)"
  echo $(( total - ${only:-0} ))
}

# The commits of a range that only touch the deferred folders, one full sha a
# line: the ones deferred_rev_count leaves out, so that a list printed under
# the count can leave out the same ones.
#
#   deferred_only_revs <git dir> <rev-list args...>
deferred_only_revs() {
  local dir="$1"; shift
  grep -vxFf \
    <(git -C "$dir" rev-list --no-merges "$@" -- . "${DEFERRED_EXCLUDES[@]}" 2>/dev/null) \
    <(git -C "$dir" rev-list --no-merges "$@" -- "${DEFERRED_PATHSPECS[@]}" 2>/dev/null)
  return 0
}

# Two copies of one log as one: main's rows as they are, then each row of the
# branch's copy that main does not hold as many times. A row may come back on
# purpose (the monthly review counts the repeats), so it is counted, not
# looked up. Used by deferred_to_main and by the sync with main (sync.sh).
# The first file is told apart by its name, not by NR == FNR: an empty one
# would make every row of the second count as its own.
#
#   deferred_union <main's copy> <the branch's copy>   → the rows, on stdout
deferred_union() {
  awk 'FILENAME == ARGV[1] { seen[$0]++; print; next } seen[$0] > 0 { seen[$0]--; next } { print }' "$1" "$2"
}

# The rows of <after> beyond what <before> holds, counted the same way: what
# one side added to a log since an older copy of it.
#
#   deferred_minus <before> <after>   → the rows, on stdout
deferred_minus() {
  awk 'FILENAME == ARGV[1] { seen[$0]++; next } seen[$0] > 0 { seen[$0]--; next } { print }' "$1" "$2"
}

# Takes the deferred entries the commits <from>..HEAD of a feature's tree put
# on its branch, and sends them straight to origin's main.
#
# Entries reach the branch after its last review, or after its pull request
# has merged — the friction reviews and the retrospective write them then —
# and on the branch they cost a cycle each time: a merged branch went back to
# step 3 for three lines of log, and a push to an open pull request after its
# last round drew review findings nobody was left to answer. The entries are a
# log the monthly review reads from main, they change nothing that runs, and
# the person chose to let them skip the pull request: no review, and none of
# the project's push hooks, which check code and the database and have nothing
# to say about a log.
#
# The rows are merged into main's copy of each file rather than picked as
# commits: main's copy may hold rows the branch does not, or the other way
# round. The branch then drops what it sent: reset past the commits when they
# held nothing else, or a commit that puts the folders back the way <from> had
# them when they did. Either way the branch carries no change to the folders,
# and its own merge cannot meet main's rows in a conflict.
#
# Left to the caller (returns 1): no entries in the range, a commit in it that
# is already on origin, or an open pull request whose branch carried entries
# before <from> — those reach main with that pull request, and rows sent ahead
# of them would conflict with them at its merge.
#
#   deferred_to_main <tree> <from>  → 0 sent, 1 not for this, 2 failed
deferred_to_main() {
  local wt="$1" from="$2" branch head base files tmp sha="" only=1 n f
  [[ -n "$from" ]] || return 1
  head="$(git -C "$wt" rev-parse HEAD 2>/dev/null)" || return 1
  [[ "$head" != "$from" ]] || return 1
  files="$(git -C "$wt" diff --name-only "$from" "$head" -- "${DEFERRED_PATHSPECS[@]}" 2>/dev/null)"
  [[ -n "$files" ]] || return 1
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" && "$branch" != "main" ]] || return 1
  git -C "$wt" fetch -q origin 2>/dev/null || return 2
  n="$(git -C "$wt" rev-list --count "$from..$head" 2>/dev/null)" || return 1
  if git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$branch" >/dev/null; then
    [[ "$(git -C "$wt" rev-list --count "$from..$head" "^refs/remotes/origin/$branch" 2>/dev/null)" == "$n" ]] \
      || return 1
  fi
  if [[ "$( (cd "$wt" && branch_pr_state "$branch") )" != "MERGED" ]]; then
    base="$(git -C "$wt" merge-base origin/main "$from" 2>/dev/null)" || return 1
    [[ -z "$(git -C "$wt" diff --name-only "$base" "$from" -- "${DEFERRED_PATHSPECS[@]}" 2>/dev/null)" ]] \
      || return 1
  fi
  [[ -z "$(git -C "$wt" log --format=%H "$from..$head" -- . "${DEFERRED_EXCLUDES[@]}" 2>/dev/null)" ]] \
    || only=0

  tmp="$(mktemp -d)"
  local attempt sent=1
  for attempt in 1 2; do
    git -C "$wt" worktree remove --force "$tmp/tree" >/dev/null 2>&1 || true
    (( attempt == 1 )) || git -C "$wt" fetch -q origin main 2>/dev/null || true
    git -C "$wt" worktree add -q --detach "$tmp/tree" origin/main >/dev/null 2>&1 || break
    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      # Gone on the branch: nothing of it to send.
      git -C "$wt" cat-file -e "$head:$f" 2>/dev/null || continue
      mkdir -p "$(dirname "$tmp/tree/$f")"
      [[ -f "$tmp/tree/$f" ]] || : > "$tmp/tree/$f"
      git -C "$wt" show "$head:$f" > "$tmp/branch-copy"
      deferred_union "$tmp/tree/$f" "$tmp/branch-copy" > "$tmp/merged" && cat "$tmp/merged" > "$tmp/tree/$f"
      git -C "$tmp/tree" add -- "$f"
    done <<< "$files"
    if git -C "$tmp/tree" diff --cached --quiet; then
      sent=0; break                       # main holds every row already
    fi
    if [[ "$only" == 1 && "$n" == 1 ]]; then
      git -C "$tmp/tree" commit -q --no-verify -C "$head" >/dev/null 2>&1 || break
    else
      git -C "$tmp/tree" commit -q --no-verify \
        -m "chore(sclaude): carry deferred entries from $branch to main" \
        -m "Entries put off on $branch after its review go to main directly (deferred_to_main in sclaude)." \
        >/dev/null 2>&1 || break
    fi
    if GIT_TERMINAL_PROMPT=0 git -C "$tmp/tree" push -q --no-verify origin HEAD:main >/dev/null 2>&1; then
      sha="$(git -C "$tmp/tree" rev-parse --short HEAD)"
      sent=0; break
    fi
    # Somebody pushed to main meanwhile: once more, on top of theirs.
  done
  git -C "$wt" worktree remove --force "$tmp/tree" >/dev/null 2>&1 || true
  rm -rf "$tmp"
  if [[ "$sent" != 0 ]]; then
    warn "  could not send the deferred entries on $branch to main — they stay on the branch"
    return 2
  fi
  git -C "$wt" fetch -q origin main 2>/dev/null || true

  # The branch drops what it sent.
  if [[ "$only" == 1 ]]; then
    git -C "$wt" reset -q --keep "$from" 2>/dev/null \
      || warn "  the deferred entries are on main; $branch still carries them — reset it to ${from:0:8} by hand"
  else
    ( while IFS= read -r f; do
        if git -C "$wt" cat-file -e "$from:$f" 2>/dev/null; then
          git -C "$wt" checkout -q "$from" -- "$f"
        else
          git -C "$wt" rm -q -- "$f"
        fi || exit 1
      done <<< "$files"
      git -C "$wt" commit -q --no-verify \
           -m "chore(sclaude): leave the deferred entries to main" \
           -m "They went to main directly (deferred_to_main in sclaude); the branch carries no change to the deferred folders, so its merge cannot conflict with them."
    ) >/dev/null 2>&1 \
      || warn "  the deferred entries are on main; put $branch's deferred folders back to ${from:0:8} by hand"
  fi
  info "  the deferred entries went to main${sha:+ as $sha}, past the pull request"
  return 0
}

# Every entry file in those folders. One a line.
deferred_files() {
  local d f
  while IFS= read -r d; do
    for f in "$d"/*.tsv; do
      [[ -f "$f" ]] && echo "$f"
    done
  done < <(deferred_dirs "${1:-}")
  return 0
}

# Whether the monthly review is due: prints "<entries> <since>" and returns 0
# when it is, returns 1 otherwise. <since> is the oldest of the folders' last
# reviews, or of their first entries where a folder was never reviewed.
deferred_due() {
  local -a dirs=()
  mapfile -t dirs < <(deferred_dirs "${1:-}")
  (( ${#dirs[@]} )) || return 1
  python3 - "$DEFERRED_DAYS" "${dirs[@]}" <<'PY'
import datetime, glob, os, re, sys
days, dirs = int(sys.argv[1]), sys.argv[2:]
entries, since = 0, None
for folder in dirs:
    reviewed = None
    try:
        stamp = open(os.path.join(folder, "last-reviewed"), encoding="utf-8").read().strip()
        if re.match(r"\d{4}-\d{2}-\d{2}$", stamp):
            reviewed = stamp
    except OSError:
        pass
    first, count = None, 0
    for path in glob.glob(os.path.join(folder, "*.tsv")):
        for line in open(path, encoding="utf-8"):
            if not line.strip() or line.startswith("#"):
                continue
            count += 1
            date = line.split("\t", 1)[0].strip()[:10]
            if re.match(r"\d{4}-\d{2}-\d{2}$", date) and (first is None or date < first):
                first = date
    if not count:
        continue
    entries += count
    mark = reviewed or first
    if mark and (since is None or mark < since):
        since = mark
if not entries or not since:
    sys.exit(1)
if (datetime.date.today() - datetime.date.fromisoformat(since)).days < days:
    sys.exit(1)
print("%d %s" % (entries, since))
PY
}

# The machine-wide file the deferred friction was kept in before it moved into
# each product's .sclaude/. Nothing reads it any more, so its entries for this
# product are named, with where they go, rather than left there unseen: the
# review said "nothing deferred" over a month of them.
DEFERRED_LEGACY="${XDG_STATE_HOME:-$HOME/.local/state}/sclaude/friction-deferred.tsv"

deferred_legacy() {
  local root="$1" product count
  [[ -f "$DEFERRED_LEGACY" ]] || return 0
  product="$(basename "$root")"
  count="$(awk -F'\t' -v p="$product" '!/^#/ && $2 == p' "$DEFERRED_LEGACY" | grep -c .)"
  [[ "$count" -gt 0 ]] || return 0
  warn "  $count deferred entr$([[ "$count" == 1 ]] && echo y || echo ies) for $product are still in the old $DEFERRED_LEGACY,"
  warn "  which nothing reads now. Move the rows you still want to $(product_rules_dir "$root")/deferred/<name>.tsv"
  warn "  (one file per feature, the same columns) and commit them by the product's own pull request."
}

# The open pull request of an earlier review, if one waits. The review stamps
# last-reviewed on its own branch, so until that merges, main still reads as
# due: without this the review was offered again, and run again, over it.
deferred_pending() {
  local root="$1" pr
  command -v gh >/dev/null 2>&1 || return 1
  # This person's own: the folders are per person, and another's open
  # review held back the offer of this one.
  pr="$(cd "$root" && gh pr list --state open --author @me --json headRefName,url \
          --jq '[.[] | select(.headRefName | startswith("sclaude/deferred-"))][0].url // ""' 2>/dev/null)" \
    || return 1
  [[ -n "$pr" ]] && echo "$pr"
}

# Offered when sclaude is opened in a product: once a month, if anything waits.
deferred_offer() {
  local due entries since answer root pending main_copy
  root="$(main_repo 2>/dev/null)" || return 0
  deferred_legacy "$root"
  # Due by main as the remote has it, which is what the review runs on: the
  # main checkout is only fetched, and after a review's pull request merged
  # its working copy still read as due, and the review was offered and run
  # again over entries already reviewed.
  main_copy="$(mktemp -d)"
  if git -C "$root" archive origin/main .sclaude 2>/dev/null | tar -x -C "$main_copy" 2>/dev/null; then
    # Who maintains the product is the root's question, asked once.
    product_maintainer "$root"; PRODUCT_MAINTAINER_SEEN[$main_copy]=$?
    due="$(deferred_due "$main_copy" 2>/dev/null)" || { rm -rf "$main_copy"; return 0; }
  else
    due="$(deferred_due "$root" 2>/dev/null)" || { rm -rf "$main_copy"; return 0; }
  fi
  rm -rf "$main_copy"
  if pending="$(deferred_pending "$root")"; then
    info "  The last review of the deferred friction waits on its pull request: $pending"
    return 0
  fi
  read -r entries since <<< "$due"
  echo ""
  say "${BOLD}The deferred friction is due for its monthly review:${OFF} $entries entr$([[ "$entries" == 1 ]] && echo y || echo ies) since $since."
  info "  How often each class came back decides it: lift it, ban it for good, write the rule, or keep waiting."
  ask "${BOLD}Review it now? [y/n] ${OFF}" answer yn
  if is_yes "$answer"; then
    cmd_deferred
  else
    info "  Later, with: $SELF deferred"
  fi
}

# The review itself: a session in plan mode, in a worktree of the product's
# main on a branch of its own, since its result — the files trimmed, rules
# written into the policy or the product's CLAUDE.md — is a change to the
# product like any other and reaches main by a pull request. sclaude's
# checkout is read-only to it.
cmd_deferred() {
  local prompt session done_file root wt branch base
  [[ -f "$PROMPTS/friction-deferred.md" ]] || die "no prompt for the deferred review"
  root="$(main_repo 2>/dev/null)" || die "run it inside a product's repository"
  deferred_legacy "$root"

  # The person in the name: folders are per person, and two people reviewing
  # on the same day shared one branch, the second's commits going onto the
  # first's pull request.
  local who; who="$(developer_name 2>/dev/null)"; who="${who:-local}"
  branch="sclaude/deferred-$who-$(date +%F)"
  wt="$root-deferred-$who-$(date +%F)"
  git -C "$root" fetch -q origin main 2>/dev/null || true
  base="$(git -C "$root" rev-parse -q --verify origin/main 2>/dev/null || git -C "$root" rev-parse HEAD)"
  local made=""
  if [[ ! -d "$wt" ]]; then
    # A review run earlier the same day may have pushed this branch already:
    # it is continued, not reset to main, or the next push no longer fits
    # on top of what its pull request holds.
    if git -C "$root" show-ref --verify -q "refs/heads/$branch"; then
      git -C "$root" worktree add -q "$wt" "$branch" 2>/dev/null \
        || die "could not make the review's worktree at $wt"
    elif git -C "$root" show-ref --verify -q "refs/remotes/origin/$branch"; then
      git -C "$root" worktree add -q -b "$branch" "$wt" "origin/$branch" 2>/dev/null \
        || die "could not make the review's worktree at $wt"
    else
      git -C "$root" worktree add -q -B "$branch" "$wt" "$base" 2>/dev/null \
        || die "could not make the review's worktree at $wt"
    fi
    made=1
  fi
  # The files as they are in the review's tree, the one the review edits, made
  # from origin/main. Entries reach main by the features' pull requests, so
  # the main checkout's working copy can hold more or fewer than main does,
  # and a list read there named files the session then did not find.
  local -a files=()
  mapfile -t files < <(deferred_files "$wt")
  if (( ${#files[@]} == 0 )) || ! grep -qhvE '^(#|[[:space:]]*$)' "${files[@]}" 2>/dev/null; then
    [[ -n "$made" ]] && git -C "$root" worktree remove "$wt" >/dev/null 2>&1
    # Only a branch with no work on it: one continued from earlier today may
    # hold commits its push never sent.
    [[ -n "$made" && "$(git -C "$root" rev-list --count "$base..$branch" 2>/dev/null || echo 0)" -eq 0 ]] \
      && git -C "$root" branch -q -D "$branch" >/dev/null 2>&1
    info "Nothing deferred on main in $root."
    return 0
  fi
  local f list="" stamps=""
  for f in "${files[@]}"; do
    list+="- \`$f\`"$'\n'
  done
  while IFS= read -r f; do
    stamps+="- \`$f/last-reviewed\`"$'\n'
  done < <(deferred_dirs "$wt")

  done_file="${TMPDIR:-/tmp}/sclaude-deferred.done"
  prompt="$(D_FILES="${list%$'\n'}" D_STAMPS="${stamps%$'\n'}" D_WT="$wt" D_BRANCH="$branch" \
    D_RULES="$(product_rules_dir "$wt")" D_INSTRUMENTS="$INSTRUMENTS" \
    D_DONE="$done_file" D_TODAY="$(date +%F)" \
    python3 - "$PROMPTS/friction-deferred.md" <<'PY'
import os, sys
text = open(sys.argv[1], encoding="utf-8").read()
for key, env in (("<files>", "D_FILES"), ("<stamps>", "D_STAMPS"),
                 ("<worktree>", "D_WT"), ("<branch>", "D_BRANCH"),
                 ("<rules>", "D_RULES"), ("<instruments>", "D_INSTRUMENTS"),
                 ("<done-marker>", "D_DONE"), ("<today>", "D_TODAY")):
    text = text.replace(key, os.environ.get(env, ""))
print(text)
PY
)"
  session="$(new_session_id)"
  local -a guard=()
  local guard_out
  guard_out="$(review_guard_settings "$wt")" \
    || { warn "  The deferred review was not started: sclaude could not read its rules (see above)."; return 1; }
  mapfile -t guard <<< "$guard_out"

  echo ""
  echo "${BOLD}${BLUE}── $(phase_title deferred), monthly ──${OFF}"
  # About no feature, so no topic hears of it today; said for the day one does.
  ask_feed say "$(phase_line started deferred)"
  info "   opus / medium / plan · $wt ($branch)"
  echo ""
  # Where the branch stood before this session: one continued from earlier
  # the same day already holds commits, and they are not this session's work.
  local start; start="$(git -C "$wt" rev-parse HEAD 2>/dev/null)"
  session_watch_start "" "$session" "$done_file" "$wt" deferred
  local before_instruments; before_instruments="$(instruments_state)"
  ( cd "$wt" && claude_launch --session-id "$session" --model opus --effort medium \
      "${guard[@]}" --permission-mode plan --add-dir "$INSTRUMENTS" \
      --add-dir "$HOME/.claude/projects" -n "friction/deferred" "$prompt" )
  session_watch_stop
  instruments_unchanged "$before_instruments" "deferred review" || true
  session_closed "$done_file" "$wt" "$session" "" "" deferred || true

  # What the review committed goes to the product as a pull request, unless
  # the session opened one itself.
  local committed kept dirty
  committed="$(git -C "$wt" rev-list --count "${start:-$base}..HEAD" 2>/dev/null || echo 0)"
  kept="$(git -C "$wt" rev-list --count "$base..HEAD" 2>/dev/null || echo 0)"
  dirty="$(git -C "$wt" status --porcelain 2>/dev/null)"
  # What origin does not have yet, this session's or an earlier run's whose
  # push failed: that one was never pushed again, and read as "changed nothing".
  local unsent
  if git -C "$wt" rev-parse -q --verify "refs/remotes/origin/$branch" >/dev/null; then
    unsent="$(git -C "$wt" rev-list --count "origin/$branch..HEAD" 2>/dev/null || echo 0)"
  else
    unsent="$kept"
  fi
  if [[ "$committed" -gt 0 || "$unsent" -gt 0 ]]; then
    [[ "$committed" -gt 0 ]] || info "  sending what an earlier review today committed and did not push"
    if GIT_TERMINAL_PROMPT=0 git -C "$wt" push -q -u origin "$branch" >/dev/null 2>&1; then
      local pr
      pr="$(cd "$wt" && gh pr list --head "$branch" --state open --json url --jq '.[0].url // ""' 2>/dev/null)" || pr=""
      [[ -n "$pr" ]] || pr="$(cd "$wt" && gh pr create --base main --head "$branch" --fill 2>/dev/null)" || pr=""
      info "  the review's changes: ${pr:-pushed to $branch; open its pull request by hand}"
    else
      warn "  the review committed to $branch in $wt, and the push failed — push it by hand"
    fi
  elif [[ -z "$dirty" ]]; then
    info "  the review changed nothing"
  fi
  # Edits the session made and did not commit are its work too: "changed
  # nothing" over them was wrong, and the tree holding them is named, and kept.
  if [[ -n "$dirty" ]]; then
    warn "  the review left changes it did not commit in $wt — commit them there, or remove the tree"
    return 0
  fi
  # A clean worktree has nothing more to give: the branch keeps the work, and a
  # branch with none is not left behind for next month's review to trip on.
  git -C "$root" worktree remove "$wt" >/dev/null 2>&1 || true
  [[ "$kept" -gt 0 ]] || git -C "$root" branch -q -D "$branch" >/dev/null 2>&1 || true
}
