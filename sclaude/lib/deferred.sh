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
  echo "${BOLD}${BLUE}── the deferred friction · monthly review ──${OFF}"
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
  session_closed "$done_file" "$wt" "$session" \
    "The deferred review reported its work done, and sclaude closed it." || true

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
