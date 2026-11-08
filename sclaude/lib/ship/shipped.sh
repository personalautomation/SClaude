#!/usr/bin/env bash
#
# What has already been shipped: the deploys remembered per head, production's
# mark of a passed suite or a red one held, and what rides along to
# production with a feature.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# --- what has already been shipped -------------------------------------------
#
# remind_prod has no memory of its own: preview_done and prod_done are locals,
# born and dying inside one call. So every return to a finished feature — from
# `sclaude <slug>`, from the menu's "Finish up", from cmd_resume — offered the
# whole cycle again: deploy a preview, ship to prod, write the status. Answering
# "no" three times is not a decision, it is a toll, and a question that is always
# answered the same way is the kind people stop reading.
#
# What makes the offer meaningless is not that a deploy happened but that
# nothing has changed since. So we remember the commit that went up, and compare.
# A commit rather than a timestamp: a time cannot tell "untouched" from "changed
# and changed back", which is exactly the question being asked here.
#
# In the feature's own state.json, beside the regression's record. It lives and
# dies with the worktree, and that is right: the only way into remind_prod is
# through feature_worktree, which dies without a tree. There is no reachable
# case of a cleaned-up feature asking what it deployed.

# The commit a stage would deploy right now: the worktree's HEAD for preview,
# since that is what `vercel <wt>` uploads; main's for prod, since that is what
# `vercel --prod` ships. Empty when it cannot be read — an unreadable HEAD means
# "unknown", and unknown must never read as "unchanged".
deploy_head() {
  local wt="$1" stage="$2"
  case "$stage" in
    preview) git -C "$wt" rev-parse HEAD 2>/dev/null ;;
    prod)    git -C "$REPO" rev-parse HEAD 2>/dev/null ;;
  esac
}

# Records what a successful deploy put on hosting. Silent on failure: a deploy
# that worked must not be reported as broken because a note could not be filed.
deploy_remember() {
  local wt="$1" stage="$2" sha url
  # Deployed, by whichever way: a failure recorded before is over
  # (regression_fix_block would tell a later session of it).
  state_set "$wt/.sclaude/local/feature/state.json" "regression.$stage.deploy_failed" null 2>/dev/null || true
  state_set "$wt/.sclaude/local/feature/state.json" "regression.$stage.after_failure" null 2>/dev/null || true
  sha="$(deploy_head "$wt" "$stage")" || return 0
  [[ -n "$sha" ]] || return 0
  state_set "$wt/.sclaude/local/feature/state.json" "deploy.$stage.sha" "$sha" 2>/dev/null || true
  # The pull request it was shipped for: the process map tells by it whether
  # production carries the feature (prod_held in process_position.py), with no GitHub.
  local pr
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr 2>/dev/null || true)"
  [[ "$stage" == "prod" && "$pr" =~ ^[0-9]+$ ]] \
    && state_set "$wt/.sclaude/local/feature/state.json" deploy.prod.pr "$pr" 2>/dev/null || true

  # For prod, the deployment's own address as well as the commit. `vercel
  # rollback` takes a url or an id and cannot be given a sha, so a record that
  # holds only the commit describes what we shipped without naming the thing
  # that could be moved away from. Asked of hosting rather than captured from
  # the deploy's output: `vercel --prod` runs inside run_block's subshell, which
  # hands back a pass or a fail and nothing else.
  if [[ "$stage" == "prod" ]]; then
    url="$(vercel_prod_current | cut -f1)" || url=""
    [[ -n "$url" ]] && state_set "$wt/.sclaude/local/feature/state.json" deploy.prod.url "$url" \
      2>/dev/null || true
    # A fresh ship ends the rolled-back state. The mark is what makes
    # deploy_unchanged answer "changed" while production serves an older
    # release than main's HEAD; leaving it set after the next deploy would make
    # that answer permanent, and the skip it exists to prevent would never
    # happen again.
    state_set "$wt/.sclaude/local/feature/state.json" rollback.prod.code null 2>/dev/null || true
  fi
}

# True when this stage's last deploy is still what the tree holds — that is,
# when deploying again would upload byte-for-byte what is already up there.
#
# Two conditions, and both are needed. The commit must match, and for preview
# the tree must also be clean: the same HEAD with uncommitted edits is not
# "nothing changed", and vercel uploads the working tree rather than the commit.
# Prod has its own conditions, in the code below.
#
# False on everything unknown — no record, no git, an unreadable HEAD. The
# question is "do we know this is pointless", and not knowing is not a yes.
deploy_unchanged() {
  local wt="$1" stage="$2" was now
  was="$(state_get "$wt/.sclaude/local/feature/state.json" "deploy.$stage.sha" 2>/dev/null || true)"
  [[ -n "$was" && "$was" != "null" ]] || return 1

  # A rolled-back production is never unchanged, whatever the commits say.
  #
  # This compares what we shipped against main, and after a rollback the
  # two still agree — main holds the commit, and production serves the release
  # before it. Without this the next pass would print "Production already at
  # abc1234 — unchanged, skipping" and never offer to ship the fix, which is the
  # one thing that has to happen next.
  #
  # Cleared by the deploy that follows: deploy_remember writes a new sha, and
  # the code below stops matching until the fix is itself shipped.
  if [[ "$stage" == "prod" ]] \
     && [[ "$(state_get "$wt/.sclaude/local/feature/state.json" rollback.prod.code 2>/dev/null || true)" == "done" ]]; then
    return 1
  fi

  now="$(deploy_head "$wt" "$stage")" || return 1
  [[ -n "$now" ]] || return 1
  if [[ "$stage" != "prod" ]]; then
    [[ "$was" == "$now" ]] || return 1
  else
    # The main checkout's main, which `vercel --prod` uploads — a commit made
    # there and not pushed is something new, and prod_main_unready says so.
    deploy_prod_same "$was" "$now" || return 1
    # And main on origin as it is now: the checkout's branch lags whenever
    # the merge was made on GitHub — by sclaude's auto merge, or by hand — and
    # read from there alone, a merged pull request looked shipped already,
    # production was skipped with nobody asked, and the feature closed as
    # declined. Asked with ls-remote, which moves no ref: a fetch here moved
    # origin/main past the branch before rollback_remember_migrations read
    # `origin/main...HEAD`, and a merge that brings a migration recorded none.
    # A head not here yet is something new.
    local remote
    remote="$(GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$REPO" ls-remote origin refs/heads/main 2>/dev/null | cut -f1)"
    if [[ -n "$remote" ]]; then
      git -C "$REPO" cat-file -e "$remote^{commit}" 2>/dev/null || return 1
      deploy_prod_same "$was" "$remote" || return 1
    fi
  fi
  [[ "$stage" != "preview" || -z "$(worktree_dirt "$wt")" ]]
}

# Whether main at <now> is what production got at <was>: the same commit, or
# one past it by deferred entries alone, which ship nothing — sclaude puts
# them on main itself after a ship, and production read as changed, the issue
# was reopened, and the status said the feature was not there.
#
#   deploy_prod_same <was> <now>
deploy_prod_same() {
  local was="$1" now="$2"
  [[ "$was" == "$now" ]] && return 0
  git -C "$REPO" merge-base --is-ancestor "$was" "$now" 2>/dev/null \
    && [[ "$(deferred_rev_count "$REPO" "$was..$now" 2>/dev/null)" == "0" ]]
}

# A production that carries the feature with its last regression not green
# — a rollback that failed or was refused, a red with another release on
# top, a run that could not start, a red run by hand — holds the cycle where
# it is. It went by as "unchanged, skipping" once: the issue closed as
# shipped, the epilogue said so, and the clean-up offered to remove the tree
# production was to be mended from. Nothing is shipped or rolled back from
# here, since what serves production now, and whose it is, is not known to
# this pass: the person checks again (`regression <slug> prod`, which lifts
# the hold when green), rolls back (`rollback`, which puts the cycle back on
# the review), or sends the fix forward from the review (`return`).
#
#   prod_red_hold <wt> <slug>
prod_red_hold() {
  local wt="$1" slug="$2" state="$1/.sclaude/local/feature/state.json" why
  # alarm, not warn: the topic hears it with a sound, as the red it is.
  echo ""
  if [[ "$(state_get "$state" regression.prod.unrunnable 2>/dev/null || true)" == "true" ]]; then
    why="its last regression could not run"
    alarm "Production carries this feature, and $why."
    info "  A suite that did not run says nothing about production. Run it again:"
    info "    $SELF regression $slug prod"
    info "  or, if what it found broken is the feature's, fix it from the review:"
    info "    $SELF return $slug"
  elif [[ -n "$(state_get "$state" regression.prod.intruded 2>/dev/null | grep -v '^null$')" ]]; then
    why="its last regression was red with another release on top"
    alarm "Production carries this feature, and $why."
    info "  Rolling back would take that release away too. Once whoever deployed"
    info "  it has had a look, run the suite again:"
    info "    $SELF regression $slug prod"
    info "  or, if the red is this feature's, roll it back:"
    info "    $SELF rollback $slug"
    info "  or fix it forward, from the review:"
    info "    $SELF return $slug"
  else
    why="its last regression was red"
    alarm "Production carries this feature, and $why."
    info "  Mended by hand? Run the suite again:"
    info "    $SELF regression $slug prod"
    info "  Or roll it back, and the fix goes on from the review:"
    info "    $SELF rollback $slug"
    info "  Or, where it cannot go back (a migration, no release to go to), fix it"
    info "  forward from the review:"
    info "    $SELF return $slug"
  fi
  info "  Nothing is shipped, closed or cleaned up meanwhile. The worktree: $wt"
}

# What prod_pass.ended holds for a pass through remind_prod that reached the
# clean-up: the pull request, and the production it left, or `nodeploy`.
# Written by remind_prod and compared with by cmd_resume, from here alone.
#
#   prod_pass_mark <wt> [nodeploy]
prod_pass_mark() {
  local state="$1/.sclaude/local/feature/state.json"
  printf '%s %s' "$(state_get "$state" pr 2>/dev/null || true)" \
    "${2:-$(state_get "$state" deploy.prod.sha 2>/dev/null || true)}"
}

# Whether production carries this feature: sclaude shipped it (a production
# sha is recorded, by deploy_remember after the merge), did not roll it back,
# and that ship holds the merge of the feature's pull request now — a feature
# handed back after one ship carries its fix in a second pull request, which
# the earlier ship does not hold. Every later ship is of a main that holds it
# too. Not deploy_unchanged: that asks whether production is still the release
# this feature shipped, and any commit on main since — another feature's
# merge, a hotfix — made it read as not in production, the issue reopened and
# its status saying so. Unknown (gh cannot say) is 2: "not
# carried" to every caller that tests it with && or !, and told apart where a
# red production is at stake — remind_prod's hold and `sclaude return`, which
# must not ship past it or take it for a QA hand-back on GitHub's silence.
prod_carries_feature() {
  local state="$1/.sclaude/local/feature/state.json" was pr merge
  was="$(state_get "$state" deploy.prod.sha 2>/dev/null || true)"
  [[ -n "$was" && "$was" != "null" ]] || return 1
  [[ "$(state_get "$state" rollback.prod.code 2>/dev/null || true)" != "done" ]] || return 1
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" ]] || return 1
  merge="$(cd "$REPO" && timeout 30 gh pr view "$pr" --json mergeCommit --jq '.mergeCommit.oid // ""' 2>/dev/null)" || return 2
  [[ -n "$merge" ]] || return 1
  # A merge not fetched here cannot be in the release shipped from here (every
  # ancestor of it is local): git's 128 for it is "not carried" too.
  git -C "$REPO" merge-base --is-ancestor "$merge" "$was" 2>/dev/null
}

# Says out loud when production is not what main holds, and when main holds
# commits that never reached origin. Silent when all three agree.
#
# What each feature shipped is written in its own state.json, and nothing looks
# across features: a fix committed straight to main, or a merge nobody shipped,
# sat there until the next feature happened to deploy it, and sclaude never said
# a word. This is the check that looks, and the menu and `status` both run it,
# after review_branches has fetched origin.
#
# It reports rather than decides. Not every commit on main needs shipping (a
# test or a manual changes nothing that users see), so the commits are listed
# and the person judges. Silent on everything unknown: no Vercel link, no
# listing, no commit on the deployment, no origin/main.
prod_drift_report() {
  local main line url sha n migrations_dir promote=""
  if git -C "$REPO" rev-parse --verify --quiet main >/dev/null \
     && git -C "$REPO" rev-parse --verify --quiet origin/main >/dev/null; then
    line="$(main_unpushed "$REPO")"
    if [[ -n "$line" ]]; then
      echo ""
      warn "main has $(wc -l <<< "$line") commit(s) that were never pushed to origin:"
      say_lines "$line"
      info "  To push them: git -C $REPO push origin main"
    fi
  fi

  [[ -d "$REPO/.vercel" ]] || return 0
  main="$(git -C "$REPO" rev-parse --verify --quiet origin/main 2>/dev/null)" || return 0
  line="$(vercel_prod_current 2>/dev/null)" || return 0
  [[ -n "$line" ]] || return 0
  url="$(printf '%s' "$line" | cut -f1)"
  sha="$(printf '%s' "$line" | cut -f2)"
  [[ -n "$sha" && "$sha" != "$main" ]] || return 0

  if ! git -C "$REPO" merge-base --is-ancestor "$sha" "$main" 2>/dev/null; then
    echo ""
    warn "Production serves ${sha:0:8}, which is not on origin/main."
    info "  It was shipped from somewhere else — a branch or an unpushed tree: $url"
    return 0
  fi

  # Commits that only add deferred entries ship nothing (deferred_to_main).
  n="$(deferred_rev_count "$REPO" "$sha..$main" || echo 0)"
  [[ "$n" =~ ^[0-9]+$ && "$n" -gt 0 ]] || return 0
  echo ""
  warn "Production is $n commit(s) behind origin/main — pushed, never shipped:"
  # The list leaves out the same commits the count does, or it shows more
  # commits than the line above says there are.
  git -C "$REPO" log --format='%H  %h %s' "$sha..$main" 2>/dev/null \
    | awk -v only="$(deferred_only_revs "$REPO" "$sha..$main")" '
        BEGIN { n = split(only, a, "\n"); for (i = 1; i <= n; i++) skip[a[i]] }
        !($1 in skip) { sub(/^[^ ]+ /, ""); print }' \
    | head -10 | while IFS= read -r line; do info "$line"; done
  [[ "$n" -gt 10 ]] && info "  … and $((n - 10)) more"
  migrations_dir="$(project_migrations_dir "$REPO" || true)"
  if [[ -n "$migrations_dir" ]] \
     && [[ -n "$(git -C "$REPO" diff --name-only "$sha" "$main" -- "$migrations_dir" 2>/dev/null)" ]]; then
    promote="$(project_get database.promote "$REPO" || true)"
    warn "  They include migrations${promote:+: $promote comes first}."
  fi
  # The pull first: `vercel --prod` uploads the checkout as it is, and one
  # behind origin's main would ship the old commit and leave this notice up.
  info "  To ship them: cd $REPO && git pull --ff-only && ${promote:+$promote && }vercel --prod"
}

# Whether the branch holds migrations that main does not: whether a db:promote
# is needed before shipping to prod depends on it.
branch_has_migrations() {
  local wt="$1" dir
  # The directory is the project's answer, from `.sclaude/config.json`. A project that
  # names none has no migrations to promote, and everything about promoting and
  # reverting them drops out of the cycle rather than being asked about.
  dir="$(project_migrations_dir "$wt")" || return 1
  [[ -n "$dir" ]] || return 1
  [[ -n "$(git -C "$wt" diff --name-only origin/main...HEAD -- "$dir" 2>/dev/null)" ]]
}

# What a production ship of this feature carries besides it: other features
# merged since the commit production serves, and commits pushed straight to
# main — the lines of prod_riders.py, or nothing when nothing rides along or
# it cannot be told.
#
#   prod_riders <wt> <slug>
#
# main is fetched first: the merge that is about to ship happened on GitHub.
prod_riders() {
  local wt="$1" slug="$2" line sha main dir
  [[ -d "$REPO/.vercel" ]] || return 0
  line="$(vercel_prod_current 2>/dev/null)" || return 0
  sha="$(cut -f2 <<< "$line")"
  [[ -n "$sha" ]] || return 0
  GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$REPO" fetch -q origin main 2>/dev/null || true
  main="$(git -C "$REPO" rev-parse --verify --quiet origin/main 2>/dev/null)" || return 0
  git -C "$REPO" merge-base --is-ancestor "$sha" "$main" 2>/dev/null || return 0
  dir="$(project_migrations_dir "$wt" || true)"
  # Commits that only add deferred entries ship nothing, as prod_drift_report
  # leaves them out; and the feature's own pull request, by its number, which
  # a squashed merge gives in its subject alone.
  local skip; skip="$(mktemp)"
  deferred_only_revs "$REPO" "$sha..$main" > "$skip" 2>/dev/null || true
  python3 "$LIB/ship/prod_riders.py" "$REPO" "$sha" "$main" "$slug" "$dir" \
    "$(state_get "$wt/.sclaude/local/feature/state.json" pr 2>/dev/null || true)" "$skip" 2>/dev/null || true
  rm -f "$skip"
}

# The riders, said above the production question — in this shell, so the
# question's context on Telegram carries them too.
prod_riders_say() {
  local lines="$1" kind a b c d
  [[ -n "$lines" ]] || return 0
  echo ""
  warn "Production is behind main by more than this feature — \`vercel --prod\` ships these too:"
  while IFS=$'\t' read -r kind a b c d; do
    if [[ "$kind" == "feature" ]]; then
      info "  $([[ "$b" != "-" ]] && printf '#%s ' "${b//,/, #}")${c##*/} (PR #$a)$([[ "$d" != "-" ]] && printf ' — migrations: %s' "${d//,/, }")"
    else
      info "  $a $b (pushed straight to main)"
    fi
  done <<< "$lines"
  info "  Their review and QA happened in their own cycles; this ship is what takes them to production."
}
