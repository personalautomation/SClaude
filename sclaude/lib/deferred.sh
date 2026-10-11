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
# The file is the product's: what friction teaches is how the product
# customises sclaude, and it belongs with the rest of that. It lives in the
# person's rules folder, `.sclaude/team/deferred.tsv` for the product's
# maintainers and `.sclaude/people/<name>/deferred.tsv` for everybody else
# (product_rules_dir), written in a feature's worktree and committed on its
# branch, so it reaches the product's main with the feature. A maintainer's
# monthly review reads every file of the product; anybody else's, their own.
#
# The month is counted from the `# last reviewed:` line the review writes into
# a file. No timer starts the review: it is a conversation, and a conversation
# needs a person at a terminal. sclaude offers it when it is opened in a
# product and the month is up.

DEFERRED_DAYS=30

# This person's deferred file in a tree of the product: a feature's worktree
# while a feature runs, the main tree otherwise.
#
#   deferred_file [tree]
deferred_file() {
  echo "$(product_rules_dir "${1:-${REPO:-.}}")/deferred.tsv"
}

# Creates the file with its header if it is not there yet. Silent; returns 1
# when it could not.
#
#   deferred_ensure [tree]
deferred_ensure() {
  local file; file="$(deferred_file "${1:-}")"
  [[ -f "$file" ]] && return 0
  mkdir -p "$(dirname "$file")" 2>/dev/null || return 1
  cat > "$file" 2>/dev/null <<'HEADER' || return 1
# Friction that was neither lifted nor kept as a deliberate ban, but put off —
# and the rules sessions proposed for a project's CLAUDE.md. Collected here by
# the friction reviews, and reviewed together once a month (`sclaude deferred`),
# where how often a class comes back is what decides it.
#
# One entry per line, tab-separated:
#
#   date  project  feature  step  class  what happened, or the proposed rule
#
# `class` is a short kebab-case name for the problem. An entry that is the same
# problem as one above reuses its class, so the monthly review can count them.
# Class `sclaude-default` marks a preset of sclaude's that looks wrong for every
# product: the product works around it, and changing sclaude is a deliberate
# pull request to it.
#
# last reviewed: never
HEADER
}

# The deferred files the monthly review reads in a tree: every one in the
# product for a maintainer, only one's own for anybody else. One path a line.
#
#   deferred_files [tree]
deferred_files() {
  local tree="${1:-${REPO:-.}}" f
  if product_maintainer "$tree"; then
    for f in "$tree/.sclaude/team/deferred.tsv" "$tree"/.sclaude/people/*/deferred.tsv; do
      [[ -f "$f" ]] && echo "$f"
    done
  else
    f="$(deferred_file "$tree")"
    [[ -f "$f" ]] && echo "$f"
  fi
  return 0
}

# Whether the monthly review is due: prints "<entries> <since>" and returns 0
# when it is, returns 1 otherwise. <since> is the oldest of the files' last
# reviews, or of their first entries where there was none.
deferred_due() {
  local -a files=()
  mapfile -t files < <(deferred_files "${1:-}")
  (( ${#files[@]} )) || return 1
  python3 - "$DEFERRED_DAYS" "${files[@]}" <<'PY'
import datetime, re, sys
days, paths = int(sys.argv[1]), sys.argv[2:]
entries, since = 0, None
for path in paths:
    reviewed, first, count = None, None, 0
    for line in open(path, encoding="utf-8"):
        found = re.match(r"#\s*last reviewed:\s*(\d{4}-\d{2}-\d{2})", line)
        if found:
            reviewed = found.group(1)
            continue
        if not line.strip() or line.startswith("#"):
            continue
        count += 1
        stamp = line.split("\t", 1)[0].strip()[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}$", stamp) and (first is None or stamp < first):
            first = stamp
    if not count:
        continue
    entries += count
    mark = reviewed or first
    if mark and (since is None or mark < since):
        since = mark
if not entries or not since:
    sys.exit(1)
age = (datetime.date.today() - datetime.date.fromisoformat(since)).days
if age < days:
    sys.exit(1)
print("%d %s" % (entries, since))
PY
}

# Offered when sclaude is opened in a product: once a month, if anything waits.
deferred_offer() {
  local due entries since answer root
  root="$(main_repo 2>/dev/null)" || return 0
  due="$(deferred_due "$root" 2>/dev/null)" || return 0
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
  local -a files=()
  mapfile -t files < <(deferred_files "$root")
  if (( ${#files[@]} == 0 )) || ! grep -qhvE '^(#|[[:space:]]*$)' "${files[@]}" 2>/dev/null; then
    info "Nothing deferred in $root."
    return 0
  fi

  branch="sclaude/deferred-$(date +%F)"
  wt="$root-deferred-$(date +%F)"
  git -C "$root" fetch -q origin main 2>/dev/null || true
  base="$(git -C "$root" rev-parse -q --verify origin/main 2>/dev/null || git -C "$root" rev-parse HEAD)"
  if [[ ! -d "$wt" ]]; then
    git -C "$root" worktree add -q -B "$branch" "$wt" "$base" 2>/dev/null \
      || die "could not make the review's worktree at $wt"
  fi
  # The files as they are in the review's tree: the one the review edits.
  local f rel list=""
  for f in "${files[@]}"; do
    rel="${f#"$root"/}"
    list+="- \`$wt/$rel\`"$'\n'
  done

  done_file="${TMPDIR:-/tmp}/sclaude-deferred.done"
  prompt="$(D_FILES="${list%$'\n'}" D_WT="$wt" D_BRANCH="$branch" \
    D_RULES="$(product_rules_dir "$wt")" D_INSTRUMENTS="$INSTRUMENTS" \
    D_DONE="$done_file" D_TODAY="$(date +%F)" \
    python3 - "$PROMPTS/friction-deferred.md" <<'PY'
import os, sys
text = open(sys.argv[1], encoding="utf-8").read()
for key, env in (("<files>", "D_FILES"), ("<worktree>", "D_WT"), ("<branch>", "D_BRANCH"),
                 ("<rules>", "D_RULES"), ("<instruments>", "D_INSTRUMENTS"),
                 ("<done-marker>", "D_DONE"), ("<today>", "D_TODAY")):
    text = text.replace(key, os.environ.get(env, ""))
print(text)
PY
)"
  session="$(new_session_id)"
  local -a guard=()
  mapfile -t guard < <(review_guard_settings "$wt")

  echo ""
  echo "${BOLD}${BLUE}── the deferred friction · monthly review ──${OFF}"
  info "   opus / medium / plan · $wt ($branch)"
  echo ""
  session_watch_start "" "$session" "$done_file" "$wt" deferred
  ( cd "$wt" && claude_launch --session-id "$session" --model opus --effort medium \
      "${guard[@]}" --permission-mode plan --add-dir "$INSTRUMENTS" \
      --add-dir "$HOME/.claude/projects" -n "friction/deferred" "$prompt" )
  session_watch_stop
  session_closed "$done_file" "$wt" "$session" \
    "The deferred review reported its work done, and sclaude closed it." || true

  # What the review committed goes to the product as a pull request, unless
  # the session opened one itself.
  if [[ "$(git -C "$wt" rev-list --count "$base..HEAD" 2>/dev/null || echo 0)" -gt 0 ]]; then
    if GIT_TERMINAL_PROMPT=0 git -C "$wt" push -q -u origin "$branch" >/dev/null 2>&1; then
      local pr
      pr="$(cd "$wt" && gh pr list --head "$branch" --state open --json url --jq '.[0].url // ""' 2>/dev/null)" || pr=""
      [[ -n "$pr" ]] || pr="$(cd "$wt" && gh pr create --base main --head "$branch" --fill 2>/dev/null)" || pr=""
      info "  the review's changes: ${pr:-pushed to $branch; open its pull request by hand}"
    else
      warn "  the review committed to $branch in $wt, and the push failed — push it by hand"
    fi
  else
    info "  the review changed nothing"
  fi
  # A clean worktree has nothing more to give: the branch keeps the work.
  [[ -z "$(git -C "$wt" status --porcelain 2>/dev/null)" ]] \
    && git -C "$root" worktree remove "$wt" >/dev/null 2>&1 || true
}
