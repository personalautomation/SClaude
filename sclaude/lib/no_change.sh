# shellcheck shell=bash
#
# A feature whose work left nothing of its own in the repository.
#
# Some features are answered without a change: an investigation that ends in
# comments on the issue, a question settled by reading. Everything after step 2
# is about a change — the local regression tests it, the pull request carries
# it, the review reads it, the preview and production deploy it — and with no
# change each of those runs against main's own product. One such feature did
# exactly that: its plan said "no code, no pull request", and once its step 2
# closed the local regression spent minutes on typecheck, lint, build and e2e
# for a tree that differed from main in the orchestrator's files alone.
#
# The tree decides, not the plan. A plan that promised no code can still be
# followed by a session that wrote some, and the tree is what would ship.
#
# What the branch carries is sorted by who wrote it. sclaude commits onto a
# feature's branch itself: a friction review commits its fix there (its range
# is `friction.<key>.project_from..project_to` in the state), and the deferred
# entries, the policy and the rest of the orchestrator's files live under
# `.sclaude/`. Neither is the feature's work. A commit of any other kind is, and
# so is anything uncommitted — the feature then goes the ordinary way.
#
# What sclaude left on such a branch still has to reach main, or it goes with
# the branch at the clean-up:
#
#   * `.sclaude/` goes to main directly, as deferred entries do
#     (deferred_to_main): it changes nothing that runs;
#   * anything else is product a friction review changed, and the person says
#     whether it goes to main or is dropped. Sent, it is pushed with the
#     project's own hooks.

# The pathspec for everything outside the orchestrator's folder.
NO_CHANGE_PRODUCT=(. ':(exclude).sclaude')

# The commits on HEAD past <base> that are the feature's own, one a line:
# neither in a friction review's recorded range nor touching `.sclaude/` alone.
# Merges are left out: one of main into the branch brings main's work, and
# base is past it.
#
#   no_change_own <wt> <base>
no_change_own() {
  local wt="$1" base="$2" state="$1/.sclaude/local/feature/state.json" c from to
  local -A sclaude=()
  while IFS=$'\t' read -r from to; do
    [[ -n "$from" && -n "$to" ]] || continue
    while IFS= read -r c; do
      [[ -n "$c" ]] && sclaude[$c]=1
    done < <(git -C "$wt" rev-list "$from..$to" 2>/dev/null)
  done < <(python3 - "$state" <<'PY' 2>/dev/null
import json, sys
try:
    friction = json.load(open(sys.argv[1])).get("friction") or {}
except (OSError, ValueError):
    friction = {}
for node in friction.values():
    if isinstance(node, dict) and node.get("project_from") and node.get("project_to"):
        print("%s\t%s" % (node["project_from"], node["project_to"]))
PY
  )
  while IFS= read -r c; do
    [[ -n "$c" ]] || continue
    [[ -n "${sclaude[$c]:-}" ]] && continue
    [[ -z "$(git -C "$wt" diff-tree --no-commit-id --name-only -r "$c" -- "${NO_CHANGE_PRODUCT[@]}" 2>/dev/null)" ]] \
      && continue
    echo "$c"
  done < <(git -C "$wt" rev-list --no-merges "$base..HEAD" 2>/dev/null)
}

# Whether the feature changed nothing of its own. Prints the base it compared
# against — where the branch left origin/main — and returns 0 when so.
#
#   no_change_feature <wt>
no_change_feature() {
  local wt="$1" base
  [[ -z "$(worktree_dirt "$wt")" ]] || return 1
  git -C "$wt" fetch -q origin main 2>/dev/null || true
  base="$(git -C "$wt" merge-base HEAD origin/main 2>/dev/null)" || return 1
  [[ -z "$(no_change_own "$wt" "$base")" ]] || return 1
  echo "$base"
}

# Sends the branch's change to <pathspec> since <base> to origin's main, as one
# commit on top of main. Applied three-way rather than picked: main may have
# moved under the same files, and a change main already holds applies to
# nothing — which is also what makes a second attempt after a failure safe.
# <verify> 1 pushes through the project's hooks, 0 past them.
#
#   no_change_send <wt> <base> <verify> <subject> <pathspec...>  → 0 sent or nothing to send, 1 failed
no_change_send() {
  local wt="$1" base="$2" verify="$3" subject="$4"; shift 4
  local branch tmp attempt sent=1 sha="" log line
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "the branch")"
  tmp="$(mktemp -d)"
  git -C "$wt" diff --full-index --binary "$base" HEAD -- "$@" > "$tmp/patch" 2>/dev/null
  if [[ ! -s "$tmp/patch" ]]; then
    rm -rf "$tmp"
    return 0
  fi
  log="$(git -C "$wt" log --no-merges --format='- %s' "$base..HEAD" -- "$@" 2>/dev/null)"
  local -a push=(push -q)
  [[ "$verify" == 1 ]] || push+=(--no-verify)
  for attempt in 1 2; do
    git -C "$wt" worktree remove --force "$tmp/tree" >/dev/null 2>&1 || true
    git -C "$wt" fetch -q origin main 2>/dev/null || true
    git -C "$wt" worktree add -q --detach "$tmp/tree" origin/main >/dev/null 2>&1 || break
    git -C "$tmp/tree" apply --3way --index "$tmp/patch" >/dev/null 2>&1 || break
    # The project's hooks run in this tree, and a bare checkout of main has
    # neither its dependencies nor its .env files: the hooks then refused the
    # push for want of a package and of an environment's name. They get the
    # main repository's, as a feature's tree does (link_env) — a symlink for
    # node_modules, since nothing here builds.
    if [[ "$verify" == 1 && -n "${REPO:-}" ]]; then
      [[ -d "$REPO/node_modules" ]] && ln -s "$REPO/node_modules" "$tmp/tree/node_modules"
      link_env "$tmp/tree" >/dev/null 2>&1 || true
    fi
    if git -C "$tmp/tree" diff --cached --quiet; then
      sent=0; break                       # main holds all of it already
    fi
    git -C "$tmp/tree" commit -q --no-verify -m "$subject" \
      -m "$branch carries no change of its own, so it has no pull request (no_change.sh in sclaude); what sclaude committed on it goes to main this way:" \
      -m "$log" >/dev/null 2>&1 || break
    if GIT_TERMINAL_PROMPT=0 git -C "$tmp/tree" "${push[@]}" origin HEAD:main >"$tmp/push.log" 2>&1; then
      sha="$(git -C "$tmp/tree" rev-parse --short HEAD)"
      sent=0; break
    fi
    # Somebody pushed to main meanwhile, or a hook refused: once more, on top.
  done
  git -C "$wt" worktree remove --force "$tmp/tree" >/dev/null 2>&1 || true
  # Why the push was refused, when it was: a hook says so in its last lines.
  if [[ "$sent" != 0 && -s "$tmp/push.log" ]]; then
    warn "  the push to main was refused; its last words:"
    tail -n 8 "$tmp/push.log" | while IFS= read -r line; do warn "    $line"; done
  fi
  rm -rf "$tmp"
  [[ "$sent" == 0 ]] || return 1
  [[ -n "$sha" ]] && info "  sent to main as $sha: $subject"
  return 0
}

# Puts what sclaude left on the branch where it belongs: `.sclaude/` to main,
# the rest to main or nowhere, as the person says. The answer is kept in the
# state, so a second pass after a failed push does not ask again. Returns 1
# when something could not be sent: the branch then still holds it, and must
# not be deleted.
#
#   no_change_settle <wt>
no_change_settle() {
  local wt="$1" state="$1/.sclaude/local/feature/state.json" base branch files choice answer line failed=0
  branch="$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "the branch")"
  # Asked again: between step 2 and the clean-up somebody may have committed
  # the feature's own work here, and the branch is deleted after this.
  if ! base="$(no_change_feature "$wt")"; then
    warn "  $branch now carries work of the feature's own, or uncommitted changes — it is not deleted"
    return 1
  fi

  if ! no_change_send "$wt" "$base" 0 \
       "chore(sclaude): carry the orchestrator's files from $branch to main" .sclaude; then
    warn "  could not send the .sclaude changes on $branch to main — they stay on the branch"
    info "    what they are: git -C $wt diff $base HEAD -- .sclaude"
    failed=1
  fi

  files="$(git -C "$wt" diff --name-only "$base" HEAD -- "${NO_CHANGE_PRODUCT[@]}" 2>/dev/null)"
  if [[ -n "$files" ]]; then
    choice="$(state_get "$state" no_change_product 2>/dev/null || true)"
    if [[ "$choice" != send && "$choice" != drop ]]; then
      echo ""
      info "  sclaude's own commits on $branch changed the product here:"
      while IFS= read -r line; do info "    $line"; done <<< "$files"
      while IFS= read -r line; do info "    $line"; done \
        < <(git -C "$wt" log --no-merges --format='%h %s' "$base..HEAD" -- "${NO_CHANGE_PRODUCT[@]}" 2>/dev/null)
      ask "${BOLD}Send them to main? n drops them with the branch. [y/n] ${OFF}" answer yn
      if is_yes "$answer"; then choice=send; else choice=drop; fi
      state_set "$state" no_change_product "$choice"
    fi
    if [[ "$choice" == send ]]; then
      if ! no_change_send "$wt" "$base" 1 \
           "chore(sclaude): carry the friction fixes from $branch to main" "${NO_CHANGE_PRODUCT[@]}"; then
        warn "  could not send the product changes on $branch to main — they stay on the branch"
        info "    what they are: git -C $wt diff $base HEAD -- . ':(exclude).sclaude'"
        failed=1
      fi
    else
      info "  The product changes on $branch are dropped with it."
    fi
  fi
  return "$failed"
}

# Ends the cycle of a feature with no change of its own. With `code` it closes
# step 2 as well, which is where the check stands; without it the feature is
# arriving at step 3 with step 2 already closed — closed before the check
# existed, or by a hand that skipped it — and nothing is closed but the cycle.
#
#   no_change_finish <wt> <slug> [code]
no_change_finish() {
  local wt="$1" slug="$2" closing="${3:-}" state="$1/.sclaude/local/feature/state.json"
  echo ""
  info "  Nothing on this branch is the feature's own work: the product here is main's."
  if [[ "$closing" == code ]]; then
    info "  No local regression, pull request, review, preview or production to go through."
    step_run "$wt" code close
    state_set "$state" steps.code.auto_returns null 2>/dev/null || true
    state_set "$state" steps.code.done true
    state_set "$state" steps.code.finished "$(date -Iseconds)"
  else
    info "  No pull request, review, preview or production to go through."
  fi
  state_set "$state" no_change true
  state_set "$state" step "done"

  # The cycle's end, said where a merged feature says it: the status in the
  # issue and its parents, and the end date on the board. A feature with no
  # change here may still have done real work, in comments or in another
  # checkout; once one did all of its work in sclaude's own, and its issue
  # closed with neither.
  local issue; issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ "$issue" == "null" ]] && issue=""
  # Closed before the epilogue reads it, as a merged feature's is (remind_prod).
  issue_close_done "$issue" unchanged
  run_status "$slug" "$issue" "" "" 0 0 "$wt" || true
  [[ -n "$issue" ]] && { issue_end_date "$(gh_repo)" "$issue" || true; }

  issue_sync "$wt"
  echo ""
  echo "${GREEN}Feature '$slug' is complete without a change to the code.${OFF}"
  cmd_done "$slug" || true
}

# Deletes the local branch of a settled feature with no change. A plain -D:
# with no pull request there is no merged head for branch_delete_merged to
# compare with, and no_change_settle has just put everything the branch held
# on main or dropped it at the person's word.
#
#   no_change_branch_delete <branch>
no_change_branch_delete() {
  git -C "$REPO" branch -D "$1" >/dev/null 2>&1
}

# --- a change nothing deploys --------------------------------------------------
#
# A branch whose change is all in files that neither the suite nor a deployment
# reads (NO_DEPLOY, the README's "Quality gates" names them for people). It still
# goes through a pull request and a review, since that is where somebody reads
# the change and where a workflow first runs. It skips the rest. One such
# branch changed a single workflow file, and the local regression spent ten
# minutes on typecheck, build and e2e over what was main's product; the
# preview, QA on it and production would have shipped main's product again.
#
# The tree decides, as in no_change_feature: commits and uncommitted work
# alike, and a friction review's product fix counts here, since it ships with
# the branch. It is asked again at every gate rather than remembered, because
# the review may fix things outside these paths: the step-4 regression then
# runs, and so do the preview, QA and production. After the merge the pull
# request's own files are checked as well (no_deploy_merged).

# Git glob pathspecs from the top of the tree: CI, the orchestrator's folder,
# local git hooks, prose. `*.md` is the root's own Markdown only; one deeper
# may be content the product renders. Fixed here rather than per project: a
# product whose docs/ is built into the site is the exception to say so for.
NO_DEPLOY=(.github .sclaude .githooks docs '*.md')

# The pathspec for what does deploy or what the suite reads, one item a line.
no_deploy_pathspec() {
  local p
  echo .
  for p in "${NO_DEPLOY[@]}"; do printf ':(exclude,glob)%s\n' "$p"; done
}

# Whether everything the branch changed is in files nothing deploys. A git that
# cannot answer is a no: the ordinary way is the safe one.
#
#   no_deploy_feature <wt>
no_deploy_feature() {
  local wt="$1" base changed untracked
  local -a spec
  mapfile -t spec < <(no_deploy_pathspec)
  git -C "$wt" fetch -q origin main 2>/dev/null || true
  base="$(git -C "$wt" merge-base HEAD origin/main 2>/dev/null)" || return 1
  changed="$(git -C "$wt" diff --name-only "$base" -- "${spec[@]}" 2>/dev/null)" || return 1
  untracked="$(git -C "$wt" ls-files --others --exclude-standard -- "${spec[@]}" 2>/dev/null)" || return 1
  [[ -z "$changed" && -z "$untracked" ]]
}

# Whether one path, as GitHub lists a pull request's files, is in NO_DEPLOY:
# the same globs as no_deploy_pathspec, read by bash.
no_deploy_path() {
  local f="$1" p
  for p in "${NO_DEPLOY[@]}"; do
    if [[ "$p" == *'*'* ]]; then
      # shellcheck disable=SC2053  # the glob is the point
      [[ "$f" != */* && "$f" == $p ]] && return 0
    else
      [[ "$f" == "$p" || "$f" == "$p/"* ]] && return 0
    fi
  done
  return 1
}

# Whether what the merged pull request carried is in NO_DEPLOY too. The tree
# answered before the merge, but a review round may still have pushed code to
# the branch from somewhere else, and the merge took it. GitHub silent is a no.
#
#   no_deploy_merged <pr>
no_deploy_merged() {
  local pr="$1" repo files f
  [[ "$pr" =~ ^[0-9]+$ ]] || return 1
  repo="$(gh_repo)" || return 1
  files="$(gh pr view "$pr" --repo "$repo" --json files --jq '.files[].path' 2>/dev/null)" || return 1
  [[ -n "$files" ]] || return 1
  while IFS= read -r f; do
    no_deploy_path "$f" || return 1
  done <<< "$files"
}

# What the skipped part was, said once where it is skipped.
#
#   no_deploy_say <what is skipped>
no_deploy_say() {
  echo ""
  info "  Nothing on this branch is deployed or read by the suite: it changes only"
  info "  ${NO_DEPLOY[*]} (the last is the root's own Markdown)."
  info "  $1"
}
