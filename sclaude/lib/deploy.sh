#!/usr/bin/env bash
#
# Preview, prod and the cycle's epilogue.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# ` --project <name>` from the main repository's link, or empty. Without it
# `vercel <path>` does not find .vercel/ in a worktree and creates a new project
# instead of deploying to the existing one — verified, and the spare project had
# to be deleted by hand.
vercel_project_flag() {
  local name
  # The path goes as an argument rather than into the source: an apostrophe in
  # it would otherwise close the literal, and that was the only way of
  # substituting anything here.
  name="$(python3 -c '
import json, sys
try:
    with open(sys.argv[1]) as fh:
        print(json.load(fh)["projectName"])
except Exception:
    pass' "$REPO/.vercel/project.json" 2>/dev/null)"
  [[ -n "$name" ]] && printf ' --project %s' "$name"
}

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
  sha="$(deploy_head "$wt" "$stage")" || return 0
  [[ -n "$sha" ]] || return 0
  state_set "$wt/.sclaude/local/feature/state.json" "deploy.$stage.sha" "$sha" 2>/dev/null || true

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
# Prod ships what was pushed, so main's HEAD alone answers for it.
#
# False on everything unknown — no record, no git, an unreadable HEAD. The
# question is "do we know this is pointless", and not knowing is not a yes.
deploy_unchanged() {
  local wt="$1" stage="$2" was now
  was="$(state_get "$wt/.sclaude/local/feature/state.json" "deploy.$stage.sha" 2>/dev/null || true)"
  [[ -n "$was" && "$was" != "null" ]] || return 1

  # A rolled-back production is never unchanged, whatever the commits say.
  #
  # This compares what we shipped against main's HEAD, and after a rollback the
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
  [[ -n "$now" && "$was" == "$now" ]] || return 1
  [[ "$stage" != "preview" || -z "$(worktree_dirt "$wt")" ]]
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
    n="$(git -C "$REPO" rev-list --count origin/main..main 2>/dev/null || echo 0)"
    if [[ "$n" =~ ^[0-9]+$ && "$n" -gt 0 ]]; then
      echo ""
      warn "main has $n commit(s) that were never pushed to origin:"
      git -C "$REPO" log --format='  %h %s' origin/main..main 2>/dev/null | head -10 \
        | while IFS= read -r line; do info "$line"; done
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

  n="$(git -C "$REPO" rev-list --count "$sha..$main" 2>/dev/null || echo 0)"
  [[ "$n" =~ ^[0-9]+$ && "$n" -gt 0 ]] || return 0
  echo ""
  warn "Production is $n commit(s) behind origin/main — pushed, never shipped:"
  git -C "$REPO" log --format='  %h %s' "$sha..$main" 2>/dev/null | head -10 \
    | while IFS= read -r line; do info "$line"; done
  [[ "$n" -gt 10 ]] && info "  … and $((n - 10)) more"
  migrations_dir="$(project_migrations_dir "$REPO" || true)"
  if [[ -n "$migrations_dir" ]] \
     && [[ -n "$(git -C "$REPO" diff --name-only "$sha" "$main" -- "$migrations_dir" 2>/dev/null)" ]]; then
    promote="$(project_get database.promote "$REPO" || true)"
    warn "  They include migrations${promote:+: $promote comes first}."
  fi
  info "  To ship them: cd $REPO && ${promote:+$promote && }vercel --prod"
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
  python3 "$LIB/prod_riders.py" "$REPO" "$sha" "$main" "$slug" "$dir" 2>/dev/null || true
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

# Runs vercel so that the URL and the result remain while the tail of
# suggestions does not — "To deploy to production…" and the "Next steps" section
# with six commands to choose from. The next block asks about prod, and the rest
# is beside the point.
#
# A plain pipeline will not do here: vercel, on seeing a non-tty stdout, stops
# redrawing the progress line and dumps the whole build log — a hundred lines
# instead of three. So `script` gives it a real pseudo-terminal, and it is
# script's output that gets filtered. Erasing the tail with the cursor would not
# do either: vercel sets the number of lines, and it changes from version to
# version.
#
# We compare against a line stripped of colours and \r — without that
# "Next steps:" does not match the pattern — while printing the original so as
# not to lose the formatting.
run_vercel() {
  local cmd="$1" out err rc spin=0 pid label="deploying"
  local frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  [[ "$cmd" == *--prod* ]] && label="shipping to production"
  out="$(mktemp)"

  # `--json` is the only mode where vercel prints no tail of suggestions and
  # does not depend on whether its output is a terminal. At the cost of progress:
  # in this mode it stays silent until the end, so we draw progress of our own.
  #
  # stdin is closed: otherwise vercel reads ahead what was typed, and the next
  # question is left unanswered. The project and the path are given as flags, it
  # needs no input.
  # stdout and stderr are separated: the JSON goes to stdout while progress and
  # errors go to stderr, and mixing them means getting unparsable JSON.
  err="$(mktemp)"
  ( eval "$cmd --json" > "$out" 2> "$err" < /dev/null ) &
  pid=$!

  # The indicator only when there is a terminal: under a pipeline it would turn
  # into a thousand lines of rubbish.
  if [[ -t 1 ]]; then
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r  %s %s…' "${frames:spin:1}" "$label"
      spin=$(( (spin + 1) % 10 ))
      sleep 0.1
    done
    printf '\r\033[2K'
  else
    echo "  $label…"
  fi

  wait "$pid"; rc=$?

  # Two things are needed from the JSON: the address and how it all ended. The
  # rest is suggestions and internal fields, which is what we set out to hide.
  python3 - "$out" "$rc" "$err" <<'PY'
import json, os, re, sys
path, rc = sys.argv[1], int(sys.argv[2])
err_text = open(sys.argv[3], errors='replace').read() if len(sys.argv) > 3 else ''
raw = open(path, errors='replace').read()
try:
    data = json.loads(raw)
except ValueError:
    # Not JSON means vercel did not reach a result. We show what it said itself,
    # stripped of the progress animation.
    text = (raw + '\n' + err_text).strip()
    text = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z~]', '', text)
    lines = [l.strip() for l in re.split(r'[\r\n]+', text) if l.strip()]
    for line in lines[-8:]:
        print('  ' + line)
    sys.exit()
message = data.get('message') or ''
deployment = data.get('deployment') if isinstance(data.get('deployment'), dict) else {}
url = data.get('url') or deployment.get('url') or ''
if not url:
    # message reads as "Deployment <address> ready." — the address there has no
    # scheme.
    found = re.search(r'[a-z0-9][a-z0-9.-]*\.vercel\.app', message)
    url = found.group(0) if found else ''
if url:
    url = url if url.startswith('http') else 'https://' + url
    print('  %s' % url)
    # The address is the one thing a caller cannot get back afterwards: it is
    # printed inside run_block's subshell, which returns only pass or fail. The
    # preview regression needs it to aim the suite, so when a path is named we
    # write it there as well as printing it. Silent on failure — a deploy that
    # worked must not be reported as broken because a scratch file would not
    # open.
    out_path = os.environ.get("SCLAUDE_VERCEL_URL_FILE", "")
    if out_path and rc == 0:
        try:
            with open(out_path, "w") as fh:
                fh.write(url + "\n")
        except OSError:
            pass
if rc == 0:
    print('  done')
else:
    print((data.get('error') or {}).get('message') or message or 'the deploy failed')
PY

  rm -f "$out" "$err"
  return "$rc"
}

# Shows a block of commands and offers to run them. The commands arrive one per
# argument, each a ready line for the shell.
#
# Showing exactly what will be run and then running exactly that is the whole
# point: a list that diverges from the deed is worse than no list at all.
#
# An empty prompt runs the block without asking. The preview is that case: it
# is the deployment QA looks at, so a feature cannot reach QA or the merge
# without one, and a question whose only sensible answer is yes only teaches
# people to answer without reading. The commands are still printed first.
run_block() {
  local title="$1" note="$2" prompt="$3"; shift 3
  local cmd answer

  echo ""
  say "${BOLD}$title${OFF}"
  [[ -n "$note" ]] && say "${DIM}$note${OFF}"
  echo ""
  # The list of commands is the very context without which "Publish?" is
  # meaningless: the human agrees to what they see, and on a phone they must see
  # the same thing.
  for cmd in "$@"; do
    say "  $cmd"
  done

  # We read the answer straight from the terminal rather than the script's
  # stdin: before the question gh and other external commands get their turn, and
  # what they do with an inherited stdin is not our business. When there is no
  # terminal, we read as before.
  if [[ -n "$prompt" ]]; then
    echo ""
    ask "${BOLD}$prompt [y/n] ${OFF}" answer yn
    is_yes "$answer" || { info "→ $title: skipped."; return 1; }
  fi

  # One subshell for the whole block: otherwise the `cd` from the first line
  # does not survive to the second. We stop at the first error — after a failed
  # promote there is nothing to ship. The commands need a terminal so that vercel
  # does not go into machine mode and prints a URL rather than JSON.
  (
    # We check openability rather than existence: under a pipeline /dev/tty
    # exists but does not open, and a bare exec would print the error itself.
    if : < /dev/tty 2>/dev/null; then exec < /dev/tty; fi
    for cmd in "$@"; do
      echo ""
      echo "${BLUE}\$ $cmd${OFF}"
      if [[ "$cmd" == vercel\ * ]]; then
        run_vercel "$cmd" || exit 1
      else
        eval "$cmd" || exit 1
      fi
    done
  )
  if [[ $? -ne 0 ]]; then
    warn ""
    warn "  ✗ $title — a command failed, stopping here."
    warn "    The rest of this block did not run."
    return 1
  fi
  # The outcome is printed afterwards: `vercel` ends its output with escape
  # sequences that erase the previous lines, and without this separator no trace
  # is left on the screen either of the question or of how it ended.
  echo ""
  echo "${GREEN}✓ $title — done.${OFF}"
  return 0
}

# The branch's migrations, onto the database the previews run on.
#
# From the worktree, because that is where they are: until the merge they are
# not in main. Without this a preview runs the branch's code on a schema that
# lacks the branch's tables, and one feature went through QA exactly so, with a
# green regression, because the suite never touched the new tables.
#
# Its own step, before the deploy block and outside its retries, and never a
# reason not to deploy. The previews share one database, so `db push` there can
# refuse for reasons that are not this branch's fault: another branch applied a
# migration this one does not have yet. Before this step existed such a branch
# still got its preview, only without its schema; it still does, and is told so
# loudly instead of being stopped until somebody else's work is merged. And a
# failed apply is not a failed deploy, so it is not retried as one.
#
# The command is the project's (database.applyPreview) and must be idempotent:
# it also runs for an unchanged tree whose deploy is skipped, which is how a
# preview deployed before this step existed gets its schema. Not asked about:
# the preview itself is not.
#
# Returns non-zero only when an apply ran and failed; callers ignore it.
preview_apply_migrations() {
  local wt="$1" cmd
  branch_has_migrations "$wt" || return 0
  cmd="$(project_get database.applyPreview "$wt" || true)"
  if [[ -z "$cmd" ]]; then
    echo ""
    warn "The branch adds migrations and the project names no applyPreview command."
    info "  The preview runs without the branch's schema; .sclaude/config.json"
    info "  describes it under database.applyPreview."
    return 0
  fi
  echo ""
  say "${BOLD}Preview database — the branch's migrations${OFF}"
  echo "${BLUE}\$ cd $(printf '%q' "$wt") && $cmd${OFF}"
  if ( if : < /dev/tty 2>/dev/null; then exec < /dev/tty; fi
       cd "$wt" && eval "$cmd" ); then
    return 0
  fi
  alarm "  Applying the branch's migrations to the preview database failed."
  alarm "  The preview is deployed anyway, without the branch's schema — pages"
  alarm "  that need its tables will fail there. Read the output above; a shared"
  alarm "  database holding another branch's migration is the usual cause."
  return 1
}

# The preview deploy block, the one both the cycle and `sclaude preview` run.
# One definition, because the two copies had already drifted apart once. The
# URL file, when the caller wants the address, is passed the way run_vercel
# reads it: SCLAUDE_VERCEL_URL_FILE in the environment.
#
# The note does not say which database the preview uses: that is the project's
# Vercel setting, which sclaude cannot see.
preview_deploy() {
  local wt="$1"
  write_vercelignore "$wt"
  run_block \
    "Preview — see the branch on real hosting" \
    "Its own URL for this build." \
    "" \
    "cd $REPO" \
    "vercel $wt$(vercel_project_flag)"
}

# Deploys the worktree to preview, trying again on failure, and writes down
# what went up: the commit (deploy_remember) and the address the preview
# regression aims at. Exit 0 when a deploy succeeded.
#
# Shared by the cycle and by the regression gate. The gate needs it because a
# fixing session commits to the branch while the preview still serves the
# commit before it: a rerun against that old address checks code that no
# longer exists, and a green verdict from it would be recorded against a tree
# that was never deployed.
#
# The URL goes through a file because run_block runs the deploy in a subshell
# and hands back only a pass or a fail. The state is the record the
# regression reads from.
preview_ship() {
  local wt="$1" url_file try
  url_file="$wt/.sclaude/local/feature/preview.url"
  rm -f "$url_file"
  for ((try = 1; try <= PREVIEW_TRIES; try++)); do
    if SCLAUDE_VERCEL_URL_FILE="$url_file" preview_deploy "$wt"; then
      deploy_remember "$wt" preview
      if [[ -s "$url_file" ]]; then
        state_set "$wt/.sclaude/local/feature/state.json" regression.preview.url "$(< "$url_file")"
      fi
      rm -f "$url_file"
      return 0
    fi
    if [[ "$try" -lt "$PREVIEW_TRIES" ]]; then
      warn "  The preview deploy failed — trying again in ${PREVIEW_RETRY_PAUSE}s ($((try + 1))/$PREVIEW_TRIES)."
      sleep "$PREVIEW_RETRY_PAUSE"
    else
      alarm "  The preview deploy failed $PREVIEW_TRIES times — this needs a person to read the log above."
    fi
  done
  rm -f "$url_file"
  return 1
}

# Did the issue miss QA entirely? Says so out loud, and answers by exit code.
#
# It misses when the branch was merged before the preview regression went green:
# `Closes #N` closes the issue at the merge, and a board with the "Item closed"
# workflow moves the item to Done in the same second. The QA move that runs just
# before this then finds the issue in a column it may not take it from, and the
# feature reaches production without anybody having looked at its deployment.
#
# A function rather than the dozen lines inline: the caller sits directly above
# the red-preview path, whose `return 0` tests/regression.py requires to be
# within sixteen lines of the gate call — a guard against exactly the kind of
# growth that would push it out of sight.
#
# Quiet and false on everything unknown: no issue, no gh, no board. The question
# is "do we know this went in unchecked", and not knowing is not a yes.
#
# Quiet as well when QA did accept the preview that is there now (qa_accepted).
# Every later run of a merged feature lands here with the issue in Done, and
# on one feature the second and third runs said "nobody checked the deployment" of a
# preview QA had accepted before the merge.
qa_missed() {
  local issue="$1" merged="${2:-}" wt="${3:-}" state sent accepted

  [[ -n "$issue" && "$issue" != "null" ]] || return 1
  if [[ -n "$wt" ]]; then
    state="$wt/.sclaude/local/feature/state.json"
    sent="$(state_get "$state" qa.sha 2>/dev/null || true)"
    accepted="$(state_get "$state" qa.accepted 2>/dev/null || true)"
    [[ -n "$sent" && "$sent" != "null" && "$accepted" == "$sent" ]] && return 1
  fi
  # Done with the pull request still open is the ordinary state now: QA comes
  # before the merge, and Done is how they say yes. Only a merge explains a
  # Done that nobody put there, so only a merged branch is asked about.
  [[ "$merged" == "MERGED" ]] || return 1
  # A board with no QA column declared has no "past QA" to have skipped.
  [[ -n "$QA_DONE" ]] || return 1
  column_is "$(issue_status_now "$issue" 2>/dev/null || true)" "$QA_DONE" || return 1

  echo ""
  warn "Issue #$issue is already '$QA_DONE' — it never passed through '$QA_TO'."
  info "  The branch was merged before this preview run went green, so nobody"
  info "  checked the deployment before it went in."
  return 0
}

# Takes an accepted issue back to QA when the preview it was accepted on has
# been replaced.
#
#   qa_retest <wt> <issue> <pr> [fresh]   → 0 when it took the issue back
#
# Done with the pull request still open is QA's yes — but a yes to the
# deployment they looked at. When the preview now carries different code (a fix
# for a red regression, a review comment, anything pushed and deployed since),
# what they accepted is no longer what would be merged, so the issue goes back
# to In QA and the merge waits for a new yes.
#
# "Different" is measured, not assumed: qa_sent records in `qa.sha` the preview
# commit QA was sent to look at, and deploy.preview.sha is what is on preview
# now. Two callers ask:
#
#   * remind_prod, right after a fresh preview deploy went green, with `fresh`
#     set. A feature from before the record existed has none, and there a
#     deploy that just happened is the change.
#   * qa_wait, on seeing Done and before it says the merge is next. Without a
#     record it cannot tell and leaves the issue alone: bouncing every feature
#     already accepted on the day this shipped would be its own mistake.
#
# This is the one move out of Done sclaude makes, and the reason it may is the
# same as for In QA itself: the claim is checkable.
#
# Only with the pull request open. A merged one is in Done because `Closes #N`
# put it there, and qa_missed speaks about that case.
#
# The pull request goes back to a draft as well, and the recorded hand-off is
# forgotten: pr_qa_handoff marked it ready when QA said yes, and leaving it
# ready lets anybody merge what nobody has checked. Forgetting the head makes
# the next yes hand it over again.
#
# Breaks nothing: no gh, no board, no Done column — silence and 1.
qa_retest() {
  local wt="$1" issue="$2" pr="$3" fresh="${4:-}" state sent now repo view pr_state draft

  [[ -n "$issue" && "$issue" != "null" && -n "$QA_DONE" && -n "$QA_TO" ]] || return 1
  [[ "$pr" =~ ^[0-9]+$ && -d "$wt/.sclaude/local/feature" ]] || return 1
  state="$wt/.sclaude/local/feature/state.json"
  sent="$(state_get "$state" qa.sha 2>/dev/null || true)"
  now="$(state_get "$state" deploy.preview.sha 2>/dev/null || true)"
  [[ -n "$now" && "$now" != "null" ]] || return 1
  if [[ -n "$sent" && "$sent" != "null" ]]; then
    [[ "$sent" != "$now" ]] || return 1
  else
    [[ -n "$fresh" ]] || return 1
  fi
  column_is "$(issue_status_now "$issue" 2>/dev/null || true)" "$QA_DONE" || return 1
  command -v gh >/dev/null 2>&1 || return 1
  repo="$(gh_repo)" || return 1
  [[ -n "$repo" ]] || return 1
  view="$(gh pr view "$pr" --repo "$repo" --json state,isDraft \
            --jq '[.state, (.isDraft|tostring)] | @tsv' 2>/dev/null)" || return 1
  IFS=$'\t' read -r pr_state draft <<<"$view"
  [[ "$pr_state" == OPEN ]] || return 1

  echo ""
  say "${BOLD}Issue #$issue is in '$QA_DONE', but the code on preview has changed since QA looked.${OFF}"
  info "  Preview is at ${now:0:8}${sent:+, QA was sent ${sent:0:8}} — it goes back to '$QA_TO' to be checked again."
  issue_move_status "$issue" "$QA_DONE" "$QA_TO"
  if [[ "$draft" != true ]]; then
    if gh pr ready "$pr" --repo "$repo" --undo >/dev/null 2>&1; then
      info "PR #$pr is a draft again until QA accepts its issues."
    else
      warn "  could not make PR #$pr a draft — do it by hand (Convert to draft)"
    fi
  fi
  state_set "$state" handoff "" 2>/dev/null || true
  qa_sent "$wt"
  return 0
}

# Records which preview commit QA has been sent to look at — see qa_retest.
qa_sent() {
  local state="$1/.sclaude/local/feature/state.json" now
  now="$(state_get "$state" deploy.preview.sha 2>/dev/null || true)"
  [[ -n "$now" && "$now" != "null" ]] || return 0
  state_set "$state" qa.sha "$now" 2>/dev/null || true
}

# Records that QA accepted the preview commit they were sent (`qa.sha`), for
# qa_missed. A later qa_sent moves `qa.sha` on, and the record then no longer
# matches: a new preview is not accepted until QA says so again.
qa_accepted() {
  [[ -n "${1:-}" ]] || return 0
  local state="$1/.sclaude/local/feature/state.json" sent
  sent="$(state_get "$state" qa.sha 2>/dev/null || true)"
  [[ -n "$sent" && "$sent" != "null" ]] || return 0
  state_set "$state" qa.accepted "$sent" 2>/dev/null || true
}

# --- the merge, when QA has passed and nothing is in the way -----------------
#
# The merge is the human's step, and it stays theirs: nothing below merges on
# its own. What changes is where the decision is put in front of them. Until
# now the cycle reached this point and printed "Merge PR #N, then run: sclaude
# done" — a instruction to go elsewhere, do a thing, and come back. Whenever QA
# has already passed the issue and GitHub says the pull request is clean, that
# errand is one keystroke's worth of work standing between a finished feature
# and production, and sclaude is holding both ends of it.
#
# So the offer is made here and only here: after the preview deploy and after
# the preview regression, because those are what make the branch worth merging
# at all. Offering earlier would be offering to merge something nobody has
# checked.
#
# Three things have to hold before a question is worth asking, and each one
# that does not is a sentence saying so rather than silence — a feature that
# stands for a day because nobody said "waiting for a review" is the failure
# this replaces.

# What GitHub says about merging this pull request, as one word:
#
#   ready     — mergeable, clean, and ours to merge
#   dirty     — conflicts with main
#   blocked   — a required review or check is missing
#   behind    — main has moved and the branch must catch up
#   unstable  — checks are still running or one of them is red
#   draft     — still a draft
#   norights  — we cannot merge it: someone else's repository, or no push
#   unknown   — gh could not answer, or GitHub has not computed it yet
#
# `mergeable` is computed lazily on GitHub's side: the first ask on a freshly
# pushed branch answers UNKNOWN, and the answer arrives a second or two later.
# That is not a state to report to anybody — it is "ask again" — so the caller
# treats unknown as a reason to say nothing rather than a reason to complain.
merge_readiness() {
  local pr="$1" repo json
  [[ -n "$pr" && "$pr" != "null" ]] || { echo unknown; return 0; }
  command -v gh >/dev/null 2>&1 || { echo unknown; return 0; }
  repo="$(gh_repo)" || { echo unknown; return 0; }

  # viewerCanUpdate is the rights question. It is not the same as "can merge" —
  # GitHub has no field that answers that exactly — but it is the closest one
  # that exists: it is false for a fork's pull request opened against somebody
  # else's repository, which is the case this is guarding against. A protected
  # branch that refuses the merge for a reason of its own shows up as `blocked`
  # in mergeStateStatus, which is checked below.
  json="$(gh pr view "$pr" --repo "$repo" \
            --json mergeable,mergeStateStatus,isDraft,viewerCanUpdate,state \
            2>/dev/null)" || { echo unknown; return 0; }
  [[ -n "$json" ]] || { echo unknown; return 0; }

  MERGE_JSON="$json" python3 - <<'PYREADY'
import json, os

try:
    pr = json.loads(os.environ["MERGE_JSON"])
except Exception:
    print("unknown")
    raise SystemExit(0)

if pr.get("state") != "OPEN":
    print("unknown")
elif pr.get("isDraft"):
    print("draft")
elif not pr.get("viewerCanUpdate", True):
    print("norights")
else:
    # mergeStateStatus is the specific answer and mergeable the general one, so
    # the specific is read first: MERGEABLE with a BLOCKED state is a pull
    # request with no conflicts that still cannot be merged, and calling that
    # "ready" is exactly the mistake worth avoiding.
    state = (pr.get("mergeStateStatus") or "").upper()
    mergeable = (pr.get("mergeable") or "").upper()
    if mergeable == "CONFLICTING" or state == "DIRTY":
        print("dirty")
    elif state == "CLEAN" and mergeable == "MERGEABLE":
        print("ready")
    elif state == "BLOCKED":
        print("blocked")
    elif state == "BEHIND":
        print("behind")
    elif state == "UNSTABLE":
        print("unstable")
    else:
        # HAS_HOOKS and anything GitHub adds later. Not "ready" — we only claim
        # that for the one state we understand completely.
        print("unknown")
PYREADY
}

# Why a merge is not on offer, in a human's words. Empty for the states the
# caller says nothing about.
merge_obstacle() {
  case "$1" in
    dirty)    echo "it conflicts with main — resolve them and push" ;;
    blocked)  echo "GitHub is holding it: a required review or check is missing" ;;
    behind)   echo "main has moved on — the branch has to catch up first" ;;
    unstable) echo "its checks have not all gone green" ;;
    draft)    echo "it is still a draft" ;;
    norights) echo "we have no rights to merge it here" ;;
    *)        echo "" ;;
  esac
}

# The merge flag this repository allows, preferring squash.
#
# Asked rather than assumed: `gh pr merge --squash` fails outright in a
# repository where squash merging is switched off, and the failure arrives
# after the human has already said yes — the worst moment for it. The
# preference is squash because a feature branch is a cycle's worth of
# step-by-step commits and main wants one.
#
# Falls back to --squash when gh cannot answer: it is what this project uses,
# and a wrong guess here costs a refused command, not a bad merge.
merge_method() {
  local repo json
  repo="$(gh_repo)" || { echo "--squash"; return 0; }
  json="$(gh repo view "$repo" \
            --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed \
            2>/dev/null)" || { echo "--squash"; return 0; }
  [[ -n "$json" ]] || { echo "--squash"; return 0; }

  MERGE_REPO_JSON="$json" python3 - <<'PYMETHOD'
import json, os

try:
    repo = json.loads(os.environ["MERGE_REPO_JSON"])
except Exception:
    print("--squash")
    raise SystemExit(0)

for key, flag in (("squashMergeAllowed", "--squash"),
                  ("mergeCommitAllowed", "--merge"),
                  ("rebaseMergeAllowed", "--rebase")):
    if repo.get(key):
        print(flag)
        break
else:
    print("--squash")
PYMETHOD
}

# Offers the merge when QA has passed and GitHub says the way is clear; says
# what is in the way when it is not. Returns 0 if the merge happened.
#
# The QA condition is the whole point of the timing. "In Done" is a person's
# statement that they looked at the deployment and it was good — the one thing
# sclaude cannot establish for itself and will not claim. Until that statement
# exists there is nothing to offer: the branch is deployed and green, and the
# checking has not been done. So an issue anywhere else, or no issue at all,
# gets the reminder it always got.
#
# --delete-branch is not passed. `sclaude done` removes the worktree, the local
# branch and the remote one together, and it is what the human is told to run
# next; deleting the remote here would leave that command tearing down half of
# a thing it no longer recognises.
merge_offer() {
  local slug="$1" pr="$2" issue="$3"
  local column ready obstacle method answer

  [[ -n "$pr" && "$pr" != "null" ]] || return 1
  command -v gh >/dev/null 2>&1 || return 1

  # QA's word, where there is a board to carry it.
  #
  # "In Done" is a person saying they looked at the deployment, and it is the
  # one thing sclaude cannot establish for itself. Where an issue exists and
  # has not reached that column, there is nothing to offer yet: the checking is
  # still ahead, and asking now would be asking somebody to skip it.
  #
  # A feature started from a name alone has no issue and never will. Treating
  # that as "QA has not passed" would mean it never gets an offer however green
  # it is — punishing the absence of a board rather than the absence of a
  # check, and leaving the one kind of feature where nobody else is watching to
  # the errand this replaces. So the offer stands, and the question carries the
  # difference instead: qa_checked decides which of the two is asked.
  #
  # The same shape as the production question above, and for the same reason —
  # one question, with the warning inside it. A second prompt about the same
  # decision is answered the way repeated prompts always are.
  local qa_checked=0
  # No `board.columns.done` in the project means no column will ever carry
  # QA's word — the same as an issue on no board, and treated the same.
  if [[ -n "$issue" && "$issue" != "null" && -n "$QA_DONE" ]]; then
    column="$(issue_status_now "$issue" 2>/dev/null || true)"
    if column_is "$column" "$QA_DONE"; then
      qa_checked=1
    elif [[ -n "$column" ]]; then
      # The issue is on a board and sits somewhere before Done: the board is
      # being kept, so its answer is worth waiting for. The caller's reminder
      # stands, and this is the one case that stays silent.
      return 1
    fi
    # An empty answer is not a column before Done. issue_status_now says
    # nothing for three different situations — the issue is on no board at
    # all, gh is silent, the network is down — and none of them is QA still
    # working. Reading them as "not yet" would hold the offer back for ever on
    # a repository with no project board, which is the same mistake as
    # demanding an issue that will never exist. So it falls through with
    # qa_checked at 0 and is asked the unchecked question.
  fi

  ready="$(merge_readiness "$pr")"

  if [[ "$ready" != "ready" ]]; then
    obstacle="$(merge_obstacle "$ready")"
    # `unknown` says nothing: gh was silent, or GitHub has not finished
    # computing mergeability. Naming a state we do not know is how a tool
    # teaches people to stop reading it.
    [[ -n "$obstacle" ]] || return 1
    echo ""
    if [[ "$qa_checked" -eq 1 ]]; then
      warn "QA passed issue #$issue, but PR #$pr cannot be merged yet:"
    else
      warn "PR #$pr cannot be merged yet:"
    fi
    info "  $obstacle."
    return 1
  fi

  method="$(merge_method)"

  # The question, and what it rests on. Two headings and two wordings, because
  # they are two different things to agree to: one is backed by a person's
  # sign-off, the other by the suite alone. Saying so is the whole protection
  # available here — the repository is private on a free plan, where branch
  # protection is refused, so nothing but the wording stands between a green
  # preview and main.
  local prompt
  echo ""
  if [[ "$qa_checked" -eq 1 ]]; then
    say "${BOLD}QA passed issue #$issue — it is in '$QA_DONE'.${OFF}"
    say "${DIM}PR #$pr is clean: no conflicts, nothing GitHub is holding it for.${OFF}"
    prompt="Merge it now?"
  else
    # Two ways to arrive here, and they are worth telling apart: a feature with
    # no issue at all, and an issue that is on no board. Both mean the same
    # thing for the decision — no column will ever say QA looked — but a person
    # reading "no issue" about a feature that plainly has one stops trusting
    # the line.
    if [[ -n "$issue" && "$issue" != "null" ]]; then
      say "${BOLD}Issue #$issue is on no board — nothing will say whether QA looked.${OFF}"
    else
      say "${BOLD}No issue on GitHub for this one — nobody signed off on the deployment.${OFF}"
    fi
    say "${DIM}The preview regression is green and PR #$pr is clean, and that is all${OFF}"
    say "${DIM}this rests on.${OFF}"
    prompt="Merge it unchecked?"
  fi

  # The acceptance criteria as QA left them in the issue — the business record
  # of the feature, and where QA works. Shown inside this question rather than
  # asked about in a second one: with the issue in Done a person has already
  # signed off, and a separate "some boxes are empty, merge anyway?" would be
  # two prompts for one decision. The boxes are not a gate either — an empty one
  # may mean "not looked at yet" as easily as "does not work" — so the most they
  # do is put their own names into the question, beside what it already says:
  # "unchecked" stays when nobody signed off, because that word is the warning.
  local criteria="" unticked="" line
  if [[ -n "$issue" && "$issue" != "null" ]]; then
    criteria="$(python3 "$LIB/acceptance.py" --status "$issue" "${REPO:-.}" 2>/dev/null || true)"
  fi
  if [[ -n "$criteria" ]]; then
    echo ""
    say "Acceptance criteria in issue #$issue:"
    while IFS= read -r line; do say "  $line"; done <<<"$criteria"
    unticked="$(python3 "$LIB/acceptance.py" --unticked "$issue" "${REPO:-.}" 2>/dev/null || true)"
    if [[ -n "$unticked" && "$qa_checked" -eq 1 ]]; then
      prompt="QA passed it, but not ticked in issue #$issue: $unticked. Merge anyway?"
    elif [[ -n "$unticked" ]]; then
      prompt="Merge it unchecked? Not ticked in issue #$issue either: $unticked."
    fi
  fi
  echo ""
  say "  gh pr merge $pr $method"
  echo ""
  ask "${BOLD}$prompt [y/n] ${OFF}" answer yn
  if ! is_yes "$answer"; then
    info "→ Merge: skipped. It stays yours to do."
    return 1
  fi

  if ! gh pr merge "$pr" --repo "$(gh_repo)" "$method"; then
    echo ""
    warn "  ✗ The merge did not go through — GitHub refused it."
    info "  Nothing here changed; merge it on GitHub and carry on with: $SELF $slug"
    return 1
  fi

  echo ""
  echo "${GREEN}✓ PR #$pr merged.${OFF}"
  return 0
}

# --- waiting for QA, then for the merge ---------------------------------------
#
# The order at the end of the cycle is review → preview → QA → merge →
# production. The first two are sclaude's; QA and the merge are people's, and
# sclaude waits for each with the session it already has rather than exiting
# and leaving a person to remember `sclaude <feature>`. Each wait says which
# event it is waiting for, and moves on the moment that event happens.
#
# Ctrl-C leaves either wait and loses nothing: the feature sits at `step: done`
# and `sclaude <feature>` comes back into remind_prod, where an unchanged
# preview is skipped and the wait picks up where it was. The QA watch keeps
# looking in the meantime, so Telegram still says when the column moves.

# Is this column one QA hands a feature back with?
#
# In progress (`columns.progress`) and Backlog (`columns.backlog`) both mean
# "not accepted, needs work" — one says "now", the other "later", and neither
# is a pass. A column the project does not name is never a match: an empty name
# compared against an empty status would otherwise be.
qa_back_column() {
  local column="$1"
  [[ -n "$column" ]] || return 1
  column_is "$column" "$QA_FROM" && return 0
  column_is "$column" "$PROGRESS_FROM" && return 0
  return 1
}

# Wait until QA has decided about the issue.
#
#   qa_wait <slug> <issue> <pr> [branch] [wt]
#
# Done is checked against the preview before it counts: when the code there
# changed since QA was sent to look, qa_retest takes the issue back to In QA
# and the wait goes on. With no worktree given that check is skipped.
#
# Returns 0 when the issue is in Done — or when there is nothing to wait for:
# no issue, no Done column declared, the issue on no board or gh silent. The
# merge question that follows reads the column itself and words itself for
# each of those, so this does not need to tell them apart.
#
# Returns 2 when the feature was returned to development: the issue left In QA for In
# progress or Backlog. The caller puts the cycle back on the review step.
#
# Returns 3 when the pull request was merged while QA still had it — on
# GitHub, by hand. A merge settles the two conditions it can (merged, and Done
# on a board that closes issues with `Closes #N`), so the wait ends there; the
# caller says out loud that QA was skipped.
#
# Any other column is unexpected while QA has the feature: nobody's verdict
# lives there. This says so once per column, asks for the status to be set
# properly, and keeps waiting — the board is a person's to fix, not ours to
# guess about.
#
# The acceptance criteria do not gate Done. GitHub Projects cannot refuse a
# status change, so a gate would have to undo a person's move after the fact;
# it names the unticked ones instead, and the merge question names them again.
qa_wait() {
  local slug="$1" issue="$2" pr="$3" branch="${4:-}" wt="${5:-}"
  local now prev said="" waited=0 logged=0 announced=0 unticked

  [[ -n "$issue" && "$issue" != "null" && -n "$QA_DONE" ]] || return 0
  now="$(issue_status_now "$issue" 2>/dev/null || true)"
  [[ -n "$now" ]] || return 0

  # The timer may have seen the hand-back before this session did. Its verdict
  # is the record of that, and the column it recorded then is where the issue
  # still is — so without this the move would look like one that never left a
  # back column.
  [[ "$(watch_verdict "$slug")" == "returned" ]] && return 2

  # The column before this look, which is what tells a hand-back from an issue
  # that never reached QA at all. The watch file holds the one observed when QA
  # was asked to look; without one, In QA is what issue_qa_ready claimed.
  prev="$(state_get "$(watch_dir)/$slug.json" status 2>/dev/null || true)"
  [[ -n "$prev" && "$prev" != "null" ]] || prev="$QA_TO"

  while :; do
    if [[ -n "$now" ]]; then
      if column_is "$now" "$QA_DONE" && qa_retest "$wt" "$issue" "$pr"; then
        # Accepted, but on code that is no longer on preview: back in QA, and
        # the wait announces itself again.
        now="$QA_TO"
        watch_mark "$slug" "$now"
        announced=0
      elif column_is "$now" "$QA_DONE"; then
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        watch_mark "$slug" "$now"
        qa_accepted "$wt"
        # Said only after a wait. An issue already in Done on arrival is
        # announced by the merge question itself, and two headings saying the
        # same thing is how people learn to skip both.
        if [[ "$announced" -eq 1 ]]; then
          echo ""
          say "${BOLD}QA accepted issue #$issue — it is in '$QA_DONE'.${OFF}"
          unticked="$(python3 "$LIB/acceptance.py" --unticked "$issue" "${REPO:-.}" 2>/dev/null || true)"
          [[ -n "$unticked" ]] \
            && warn "  QA moved #$issue to '$QA_DONE', but not ticked: $unticked."
          info "  Now waiting for the merge of PR #$pr."
        fi
        return 0
      elif qa_back_column "$now" && ! qa_back_column "$prev"; then
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        return 2
      elif ! column_is "$now" "$QA_TO" && ! column_is "$now" "$said"; then
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        echo ""
        warn "  Issue #$issue is in '$now' — unexpected while waiting for QA."
        info "  Please set the ticket status: '$QA_DONE' if it is accepted,"
        info "  '$QA_FROM'${PROGRESS_FROM:+ or '$PROGRESS_FROM'} if it needs work."
        said="$now"
        # Said here; the timer need not say it again on Telegram.
        watch_mark "$slug" "$now"
      elif column_is "$now" "$QA_TO" && [[ -n "$said" ]]; then
        # Put back into QA: the unexpected column is no longer the news.
        [[ -t 1 && "$announced" -eq 1 ]] && printf '\r\033[2K'
        info "  Issue #$issue is back in '$QA_TO'."
        said=""
        watch_mark "$slug" "$now"
      fi
      prev="$now"
    fi

    if [[ "$announced" -eq 0 ]]; then
      announced=1
      echo ""
      say "${BOLD}Waiting for QA on issue #$issue.${OFF}"
      info "  QA checks the acceptance criteria in the issue and moves it to '$QA_DONE'."
      info "  The merge of PR #$pr comes after that."
      info "  Ctrl-C to leave — the QA watch keeps looking, and Telegram will say when"
      info "  the column moves. Resume with: $SELF $slug"
      echo ""
    fi
    if [[ -t 1 ]]; then
      printf '\r\033[2K  %sHuman in the loop%s — waiting for QA (%s so far, next check in %ss)' \
        "$DIM" "$OFF" "$(regression_duration "$waited")" "$QA_POLL"
    elif [[ $((waited - logged)) -ge 300 || "$waited" -eq 0 ]]; then
      # Without a terminal, a line every five minutes: this ends up in a log
      # somebody reads later.
      info "  waiting for QA on issue #$issue ($(regression_duration "$waited"))"
      logged="$waited"
    fi
    sleep "$QA_POLL"
    waited=$((waited + QA_POLL))
    if [[ -n "$branch" && "$(branch_pr_state "$branch")" == "MERGED" ]]; then
      [[ -t 1 ]] && printf '\r\033[2K'
      return 3
    fi
    now="$(issue_status_now "$issue" 2>/dev/null || true)"
  done
}

# Wait until the pull request is merged.
#
#   merge_wait <slug> <issue> <pr> <branch>
#
# The merge is the one step of the cycle that is a person's alone. This comes
# after merge_offer: either the person said no to merging from here, or GitHub
# named something in the way, and either way the merge happens on GitHub and
# this notices it. A `gh` call every MERGE_POLL seconds costs nothing.
#
# Returns 0 once merged, 1 with no branch to ask about, 2 when the pull request
# was closed without a merge — it can never be merged then, and waiting on it
# would last for ever.
merge_wait() {
  local slug="$1" issue="$2" pr="$3" branch="$4" waited=0 logged=0

  [[ -n "$branch" ]] || return 1
  echo ""
  info "Waiting for the merge of PR #$pr${issue:+ (issue #$issue)}; merge it on GitHub."
  info "  Ctrl-C to leave — the feature resumes here with: $SELF $slug"
  echo ""
  local pr_state
  while pr_state="$(branch_pr_state "$branch")"; [[ "$pr_state" != "MERGED" ]]; do
    if [[ "$pr_state" == "CLOSED" ]]; then
      [[ -t 1 ]] && printf '\r\033[2K'
      echo ""
      alarm "PR #$pr was closed without being merged — nothing to wait for."
      info "  Reopen it, or open a new one from the branch; then: $SELF $slug"
      return 2
    fi
    if [[ -t 1 ]]; then
      printf '\r\033[2K  %sHuman in the loop%s — waiting for the merge (%s so far, next check in %ss)' \
        "$DIM" "$OFF" "$(regression_duration "$waited")" "$MERGE_POLL"
    elif [[ $((waited - logged)) -ge 300 || "$waited" -eq 0 ]]; then
      info "  waiting for the merge of PR #$pr${issue:+ (issue #$issue)} ($(regression_duration "$waited"))"
      logged="$waited"
    fi
    sleep "$MERGE_POLL"
    waited=$((waited + MERGE_POLL))
  done
  [[ -t 1 ]] && printf '\r\033[2K'
  echo "${GREEN}✓ PR #$pr merged.${OFF}"
  return 0
}

remind_prod() {
  local wt="$1" slug="$2" pr branch merged migrations=""
  local issue preview_done=0 prod_done=0 qa_skipped=0
  # What `deployed-preview` is actually about, which is not preview_done.
  #
  # preview_done means "we shipped one in this run", and it is right for what it
  # is used for — the questions, the QA move, watch_start. The label means
  # something else: a preview is on hosting and its suite passed against it. The
  # two came apart when the red path stopped claiming the label. Consider a run
  # that goes red, a fixing session that commits nothing because the cause was
  # outside the branch, and a person who redeploys by hand: on the next pass
  # deploy_unchanged is true, so preview_done stays 0, the gate short-circuits
  # on the `passed` it recorded — and a green preview would never be labelled at
  # all. So the label is read from the two things it names, and both are already
  # written down.
  local preview_live=0
  pr="$(state_get "$wt/.sclaude/local/feature/state.json" pr || echo "?")"
  branch="$(state_get "$wt/.sclaude/local/feature/state.json" branch || true)"
  # The issue's number, the branch and the PR are read here, once, and the rest
  # of the function works from them. The clean-up that used to remove the tree
  # in the middle of this function now stands at its end, so the state no longer
  # vanishes underfoot — but a single snapshot is still what this wants: the
  # values are asked for in several places below, and re-reading them would mean
  # a function whose behaviour changes depending on when each line ran.
  issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue || true)"
  [[ "$issue" == "null" ]] && issue=""
  [[ -n "$branch" ]] && merged="$(branch_pr_state "$branch")"
  branch_has_migrations "$wt" && migrations=1
  # Named once here: the prod block adds it to a commit, and the rollback reads
  # the same answer from the same place.
  local migrations_dir; migrations_dir="$(project_migrations_dir "$wt" || true)"

  echo ""
  if [[ "${merged:-}" == "MERGED" ]]; then
    echo "${BOLD}Feature $slug: PR #$pr is merged.${OFF}"
  else
    echo "${BOLD}Feature $slug: PR #$pr is open.${OFF}"
    echo "${DIM}Next: the preview, then QA, then the merge — the merge is yours to do.${OFF}"
  fi

  # The order is not arbitrary: preview deploys the worktree's contents, so it
  # is asked about before the clean-up that removes that worktree.
  #
  # Preview is launched from the main repository with a path to the worktree: the
  # project's link lies in its .vercel/, and the worktree has none — a `vercel`
  # launched from there would create a new project instead of deploying to this
  # one.
  #
  # We remember the block's outcome: the labels will be set from it and the
  # session will learn from it what to write. The preview is not asked about —
  # it is the deployment QA looks at, and nothing after it can happen without
  # one — so run_block returns zero exactly when every command succeeded: the
  # label means "shipped", and a failed deploy has not shipped.
  #
  # Through an `if` rather than `&& preview_done=1`: under `set -o pipefail` a
  # trailing `&&` at the end of a function would make its status one on an
  # ordinary refusal.
  # The deployment's address is captured rather than only printed (preview_ship
  # does it): run_block runs its commands in a subshell and returns pass or
  # fail, so a caller has no other way to learn it, and the preview regression
  # below has to aim the suite somewhere. run_vercel writes it only on a
  # successful deploy.
  #
  # Unless this very tree is already up there. Then there is nothing to ask: the
  # answer is known, and we say it as a statement rather than a question. The
  # deploy stays available on purpose — `sclaude preview <slug>` and the menu's
  # own "Deploy a preview" item both reach run_block directly — because a
  # deliberate re-deploy of an unchanged tree is a real thing to want, just not
  # a thing to be asked about every time.
  #
  # preview_done stays 0 here, and that is deliberate: it means "shipped in this
  # run", the labels and the epilogue's outcome are built from it, and nothing
  # was shipped. What is already on hosting the issue learned when it went there.
  #
  # Skipped only when this very tree is on hosting and its run was green. An
  # unchanged tree whose last run was red is deployed again: the fix that
  # followed may have been outside the tree (an environment variable, a
  # setting on Vercel), and the only way to learn whether it worked is a fresh
  # deployment and a fresh run.
  #
  # And skipped, loudly, when the pull request is already merged. The preview
  # exists so that QA can look before the merge; after it there is nothing left
  # for that look to hold back, and a red run would send a feature that is
  # already in main back into review. A merged branch whose preview was never
  # green is an exception to the flow — somebody merged before QA — and it is
  # said in red rather than in passing.
  #
  # The one exception to "nothing goes on past a red or missing regression".
  # Production needs three things: a green preview regression, the issue in
  # Done, and the merge. A merge satisfies the last two by itself (`Closes #N`
  # moves the issue to Done), and for this case alone production is offered
  # without the first. Everywhere else it is unreachable without all three:
  # an open pull request stops at the fallback below, and a red preview
  # returns before it.
  if deploy_unchanged "$wt" preview \
     && [[ "$(regression_status "$wt" preview)" == "passed" ]]; then
    echo ""
    info "Preview already deployed at $(deploy_head "$wt" preview | cut -c1-8) — unchanged and green, skipping."
    info "  To send it again anyway: $SELF preview $slug"
    preview_apply_migrations "$wt" || true
    preview_live=1
  elif [[ "${merged:-}" == "MERGED" ]]; then
    echo ""
    alarm "PR #$pr is already merged — the preview and QA are skipped."
    alarm "  This is an exception to the flow: QA comes before the merge, and this"
    alarm "  feature went into main without a green preview${issue:+ or QA on issue #$issue}."
    alarm "  Production is offered without the preview regression — only in this case."
    qa_skipped=1
  else
    preview_apply_migrations "$wt" || true
    if preview_ship "$wt"; then
      preview_done=1
    fi
  fi

  # The preview regression, and the board's column behind it.
  #
  # This is the one place where "it works" can be said about a deployment rather
  # than about a tree: the branch is on real hosting, and the suite runs against
  # that hosting. A green run here is what makes "In QA" a statement of fact
  # rather than a request — see QA_TO in github.sh.
  #
  # A red one opens a fixing session in step 4, where the pull request is still
  # open and pushes still reach the branch — and when two of those have not
  # made it green, the gate hands the feature back. Everything below this line
  # depends on that: the merge, the clean-up and production all assume the
  # branch is worth shipping, and a red preview is the statement that it is not
  # yet. So we stop here rather than carrying on to offer them.
  #
  # The gate has already put the cycle back on step 4 by this point, so there is
  # somewhere to carry on to — `sclaude <slug>` resumes into the review.
  #
  # A skipped preview does not come in here, and nothing inside is lost by that:
  # the gate short-circuits on a `passed` it already recorded, the issue is
  # already in the column issue_qa_ready would move it to, and watch_start was
  # called when the deploy actually happened. The one thing that does not belong
  # to the deploy is the QA question below — whether anybody looked at this
  # before it was merged is a fact about the issue, true or false regardless of
  # who deployed what today. So it is asked either way.
  if [[ "$preview_done" -eq 1 ]]; then
    if regression_gate "$wt" "$slug" preview; then
      preview_live=1
      qa_retest "$wt" "$issue" "$pr" fresh || true
      [[ -n "$issue" ]] && issue_qa_ready "$issue"
      qa_sent "$wt"
      qa_missed "$issue" "${merged:-}" "$wt" && qa_skipped=1
      watch_start "$wt" "$slug" "$issue" "$pr"
    else
      # Zero for preview, although the deploy did happen: the label says the
      # code is on preview, and a reader takes that as "it is there and it
      # works" — the epilogue's own prompt words it as "preview passed means
      # deployed-preview". A red run is the statement that it does not work
      # yet, and the fixing session in step 4 will push again, so the commit
      # the label would be about is already on its way out. The section still
      # gets written, and it is where the deploy is named: prose can say "on
      # preview, regression red", a label cannot.
      run_status "$slug" "$issue" "$pr" "${merged:-}" 0 0 "$wt" 1 0
      echo ""
      warn "The preview regression is red — the feature is not ready to merge."
      info "  The issue stays where it is, and production is not offered."
      info "  Carry on with: $SELF $slug"
      return 0
    fi
  elif qa_missed "$issue" "${merged:-}" "$wt"; then
    qa_skipped=1
  fi

  # We re-read the PR's state here rather than using what was read at the start:
  # between that read and this line came the preview deploy and minutes of
  # waiting — precisely the window in which the merge happens. Everything below
  # depends on the merge, and being wrong in that direction costs more than one
  # request to gh.
  if [[ -n "$branch" && "${merged:-}" != "MERGED" ]]; then
    merged="$(branch_pr_state "$branch")"
    if [[ "${merged:-}" == "MERGED" ]]; then
      echo ""
      echo "${BOLD}PR #$pr has been merged since we started.${OFF}"
    fi
  fi

  # The merge itself, offered rather than only asked for.
  #
  # Here, and not a line earlier: everything above is what makes the branch
  # worth merging — it is deployed to preview, the suite ran against that
  # deployment, and a red run returned long before this point. And not a line
  # later either: the whole of the rest of this function is the merge's
  # consequences, so a merge agreed to here carries straight on into them
  # within the same run — the issue's end date below, then the clean-up and
  # production — instead of ending the cycle with an errand.
  #
  # The column is read at this moment rather than remembered from earlier. QA
  # takes hours, and the deploy and the regression above take minutes of them:
  # an issue that reached Done while they ran is a merge to offer now.
  #
  # QA first. The preview above is what they look at, and until they have
  # decided there is nothing to offer: merging now would be merging something
  # nobody has accepted. A hand-back goes straight into the review session with
  # QA's comments, in this same run.
  #
  # Both waits need a preview that is up and green. Without one — a deploy
  # that failed every try — there is nothing for QA to look at and the
  # issue never went to In QA, so a column of In progress would read as a
  # hand-back that never happened. That run ends with the reminder below, as it
  # always did.
  if [[ "${merged:-}" != "MERGED" && "$preview_live" -eq 1 ]]; then
    local qa_verdict=0
    qa_wait "$slug" "$issue" "$pr" "$branch" "$wt" || qa_verdict=$?
    if [[ "$qa_verdict" -eq 3 ]]; then
      merged="MERGED"
      qa_skipped=1
      echo ""
      alarm "PR #$pr was merged while QA still had issue #$issue."
      alarm "  This is an exception to the flow: QA comes before the merge."
    fi
    if [[ "$qa_verdict" -eq 2 ]]; then
      echo ""
      say "${BOLD}Issue #$issue left '$QA_TO': the feature returns to development.${OFF}"
      info "  What was said since — on the issue and on the pull request — goes into"
      info "  the review session below."
      # The comments are collected by the watcher, verbatim, into the file
      # run_step hands to the session — asked to look now rather than at its
      # next sweep.
      watch_look_now "$slug"
      qa_take_back "$wt" "$slug" || return 0
      run_step "$wt" "$slug" review
      return 0
    fi
    # QA said yes — to this issue. The pull request is handed over only when
    # every issue it closes is in Done, and until then it stays a draft, which
    # is what holds the merge offer below back (see pr_qa_handoff).
    if [[ "$qa_verdict" -eq 0 ]]; then
      local handed=0
      pr_qa_handoff "$wt" "$pr" "$issue" || handed=$?
      # Done before — by an earlier run, or by the QA timer while this one
      # waited, whose words went to Telegram rather than here.
      [[ "$handed" -eq 3 ]] \
        && info "PR #$pr was already handed over for the merge: ready, in the backlog, with its summary."
    fi
  fi
  if [[ "${merged:-}" != "MERGED" ]] && merge_offer "$slug" "$pr" "$issue"; then
    merged="MERGED"
  fi
  # Declined, or GitHub named something in the way: the merge is then done on
  # GitHub, and this notices it rather than ending the run with an errand.
  if [[ "${merged:-}" != "MERGED" && "$preview_live" -eq 1 ]]; then
    local wait_rc=0
    merge_wait "$slug" "$issue" "$pr" "$branch" || wait_rc=$?
    [[ "$wait_rc" -eq 0 ]] && merged="MERGED"
    # Closed without a merge: there is nothing left to wait for, and the
    # reminder below would tell the person to merge a pull request that no
    # longer can be.
    if [[ "$wait_rc" -eq 2 ]]; then
      run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" 0 "$wt"
      return 0
    fi
  fi

  # The work has ended — that is visible here and only here. GitHub closes the
  # issue itself by `Closes #N`, at the moment of the merge, when sclaude is not
  # running; this line is the first thing it does on learning of the merge, and
  # it does not matter whether that happened a minute ago or last week.
  # Symmetrical to the cycle's start, which fills in the empty start field the
  # same way.
  if [[ "${merged:-}" == "MERGED" && -n "$issue" ]]; then
    issue_end_date "$(gh_repo)" "$issue"
  fi
  # The pull request's own column follows the merge to Done. The hand-off put
  # it in the backlog to wait for the merger, and a board whose workflow moves
  # merged PRs does this by itself — but not every board has that workflow
  # switched on, and a merged PR left waiting in the backlog is a lie on it.
  [[ "${merged:-}" == "MERGED" ]] && { pr_board_set "$pr" "$QA_DONE" "$issue" || true; }

  # And the cycle ends with it. A preview fix put the cycle back on the review
  # and this run carried it on to the merge without ever returning there, so
  # the review is still open — closed now, by the merge, as run_step would.
  # Only that reopening, by the same rule run_step follows: QA's hand-back and
  # production's wait for a session, and a merge must not swallow them.
  if [[ "${merged:-}" == "MERGED" ]] \
     && [[ "$(state_get "$wt/.sclaude/local/feature/state.json" step 2>/dev/null || true)" == "review" ]] \
     && [[ "$(state_get "$wt/.sclaude/local/feature/state.json" reopened_by 2>/dev/null || true)" == "preview" ]]; then
    step_close_merged "$wt"
    issue_sync "$wt"
  fi
  # Whatever closed it by now — QA's Done through the board's auto-close, or
  # the merge — came before production. See issue_hold_open (github.sh).
  issue_hold_open "$issue"

  # Neither the clean-up nor production has anything to do before the merge: the
  # worktree still holds the only copy of the work, while `vercel --prod` and
  # `db:promote` look at main, where the feature's code is not yet — the promote
  # would run idle and the deploy would ship a prod without it. So we go further
  # only when merged, and otherwise say what this will continue with and where
  # exactly we stopped.
  if [[ "${merged:-}" != "MERGED" ]]; then
    echo ""
    # Which ticket is being waited on, not only which pull request. The PR's
    # number is what the merge is done to; the issue's is what a person tracks
    # the work by and what QA answers in — and by the time this line is read
    # the two have often been apart for days. merge_offer has already said its
    # piece when it had one, so this is the plain case: nobody has passed the
    # feature yet, or GitHub named an obstacle just above.
    #
    # Reached with no green preview up — the waits above need one — or with
    # no branch for merge_wait to ask about. Without a preview the next thing
    # is not the merge but the preview itself, since QA has nothing to look at.
    if [[ "$preview_live" -ne 1 ]]; then
      info "No green preview is up, so QA has nothing to look at yet."
      info "  QA and the merge come after it. Once the cause is fixed: $SELF $slug"
    else
      info "Waiting for the merge of PR #$pr${issue:+ (issue #$issue)}."
      info "  Merge it, then run: $SELF done $slug"
      info "  It removes the worktree and the branches. Production comes after"
      local promote_cmd; promote_cmd="$(project_get database.promote "$wt" 2>/dev/null || true)"
      info "  that, from $REPO: ${migrations:+${promote_cmd:-the promote command}, then }vercel --prod."
    fi
    # We write the outcome here too: the feature is not in prod, but it exists,
    # it is on preview and waiting for the merge — and that is exactly what an
    # epic's reader needs to know today rather than in a week. The section will
    # be rewritten later by the next session, of this feature or another.
    run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" 0 "$wt"
    return 0
  fi

  # The clean-up used to stand here, before production. It now stands at the
  # end, and the reason is the regression that follows the prod deploy: a red
  # run there needs the worktree it would have removed — the log to read, the
  # state to record, and a tree to open a fixing session in. Nothing required
  # the order that was: preview had to come before the clean-up because it
  # deploys the worktree's contents, and production had to come after the merge
  # because it looks at main. Both still hold.

  # The production question, sharpened when nobody passed the branch through QA.
  #
  # One question, not two: the human is already being asked whether to ship, and
  # a second prompt about the same decision would be answered the way repeated
  # prompts always are. So the warning goes into the note run_block already
  # prints and the question itself says what is being agreed to — the same
  # argument the clean-up makes for having no question of its own.
  #
  # Only an explicit y ships — ask re-asks until it gets y or n, so neither an
  # unattended Enter nor one left over from the wait can. This is the whole of
  # the protection available: the repository is private on a free plan, where
  # branch protection and rulesets are refused, so the merge itself cannot be
  # held back — only the deploy that would follow it.
  local prod_note prod_ask
  if [[ "$qa_skipped" -eq 1 ]]; then
    prod_note="Merged before this preview run went green — nobody passed it through '$QA_TO'."
    prod_ask="Ship to production anyway?"
  else
    prod_note=""
    prod_ask="Ship to production?"
  fi

  # As with preview: main's HEAD is what `vercel --prod` ships, so when it is
  # the commit already in production there is nothing here to decide. Said and
  # not asked — and unlike preview there is no second door, by design: shipping
  # an unchanged main to prod is not a thing anybody needs a shortcut for, and
  # `vercel --prod` from $REPO is the honest way to do it deliberately.
  # What a rollback would need, recorded while it can still be worked out.
  #
  # Both answers move the moment the block below runs. The deployment now
  # serving production is exactly the one this ship is about to displace —
  # afterwards, telling it from ours means picking a row by position, which is
  # how a rollback goes to the wrong release. And the branch's migrations are
  # `origin/main...HEAD`, a range that empties the instant `git pull` brings the
  # merge down: a rollback asking it later is told there is nothing to reverse,
  # confidently and every time.
  #
  # Both are best-effort and silent: a note that could not be filed costs a
  # rollback its certainty, never the deploy.
  if ! deploy_unchanged "$wt" prod; then
    rollback_remember_previous "$wt"
    [[ -n "$migrations" ]] && rollback_remember_migrations "$wt"
  fi

  # What rides along. After the two notes above: fetching main empties the
  # range rollback_remember_migrations reads. See prod_riders.py — on
  # 2026-10-09 one feature shipped another's migration without a word about it.
  local riders="" rider_issues=""
  if ! deploy_unchanged "$wt" prod; then
    riders="$(prod_riders "$wt" "$slug")"
    prod_riders_say "$riders"
    rider_issues="$(awk -F'\t' '$1 == "feature" && $3 != "-" { gsub(",", " ", $3); print $3 }' \
      <<< "$riders" | tr '\n' ' ')"
    # Their migrations go to production with the code that needs them: a ship
    # that only this branch would have done without a promote still needs one.
    if [[ -z "$migrations" ]] \
       && awk -F'\t' '$1 == "feature" && $5 != "-" { found = 1 } END { exit !found }' <<< "$riders"; then
      migrations=1
      prod_note="${prod_note:-The branch adds no migrations, but what ships with it does: promote first, then ship.}"
    fi
  fi

  if deploy_unchanged "$wt" prod; then
    echo ""
    info "Production already at $(deploy_head "$wt" prod | cut -c1-8) — unchanged, skipping."
  elif [[ -n "$migrations" ]]; then
    # The promote's own commands come from the project: which script applies
    # migrations to production, which paths hold them and the schema snapshot,
    # and how the tree is put back on dev afterwards. They were this product's
    # npm scripts written into the orchestrator, so a repository that promoted
    # differently could not be shipped from here at all.
    #
    # A project with migrations and no promote command is a gap worth saying out
    # loud rather than papering over with a guess: the block is assembled from
    # what is declared, and a missing promote leaves the migrations unshipped
    # where a guessed one would run something nobody named.
    local -a prod_cmds=("cd $REPO" "git pull")
    local promote_cmd schema_path env_dev
    promote_cmd="$(project_get database.promote "$wt" || true)"
    schema_path="$(project_get database.schemaFile "$wt" || true)"
    env_dev="$(project_get database.envDev "$wt" || true)"
    if [[ -n "$promote_cmd" ]]; then
      prod_cmds+=("$promote_cmd")
      prod_cmds+=("git add $migrations_dir${schema_path:+ $schema_path}")
      prod_cmds+=("git commit -m 'chore(db): promote migrations for $slug'")
      prod_cmds+=("git push")
    else
      warn "  The branch adds migrations and the project names no promote command."
      info "  They will not be applied to production by this block; .sclaude/config.json"
      info "  describes it under database.promote."
    fi
    prod_cmds+=("vercel --prod")
    # What production uploads is the main tree, and sclaude keeps its own
    # folder there (scratch.sh).
    write_vercelignore "$REPO"
    [[ -n "$env_dev" ]] && prod_cmds+=("$env_dev")

    if run_block \
      "Production" \
      "${prod_note:-The branch adds migrations: promote first, then ship.}" \
      "$prod_ask" \
      "${prod_cmds[@]}"; then
      prod_done=1
      deploy_remember "$wt" prod
    fi
  else
    write_vercelignore "$REPO"
    if run_block \
      "Production" \
      "${prod_note:-The branch adds no migrations.}" \
      "$prod_ask" \
      "cd $REPO" \
      "git pull" \
      "vercel --prod"; then
      prod_done=1
      deploy_remember "$wt" prod
    fi
  fi

  # The features that went out with this one are in production too, and their
  # issues say so. Labels only: their issues were closed by their own cycles.
  if [[ "$prod_done" -eq 1 && -n "${rider_issues// /}" ]]; then
    local rider_repo; rider_repo="$(gh_repo 2>/dev/null || true)"
    if [[ -n "$rider_repo" ]]; then
      ensure_deploy_label "$rider_repo" deployed-prod 0e8a16 "Live in production"
      apply_deploy_labels "$rider_repo" "deployed-preview deployed-prod" "$rider_issues"
      info "  Marked deployed-prod as well, shipped with this one:$(printf ' #%s' $rider_issues)"
    fi
  fi

  # The production regression: read-only, against the address the project itself
  # calls production. It runs before the clean-up so that a failure still has a
  # worktree to be fixed in — and after the deploy, because what it checks is
  # the deployment.
  if [[ "$prod_done" -eq 1 ]]; then
    # `regression_run`, not `regression_gate`, and this is the whole of the
    # difference between prod and every other stage.
    #
    # The gate's loop is: run, and on red open a fixing session, up to two of
    # them, then run again. That is right for local and preview, where nobody is
    # looking at the deployment and the only cost of a red run is time. Here it
    # meant two Opus sessions — minutes each — against a live broken production,
    # with the mark on the issue saying so and nothing doing anything about it.
    #
    # So the order is reversed: production is restored first, and only then is
    # anything fixed. regression_rewind at the end puts the cycle back on the
    # review step, where the fixing session belongs — and by then it runs against
    # a production that works.
    regression_run "$wt" "$slug" prod
    local prod_rc=$?

    # Red, but was it this feature? A production deploy made by somebody else
    # during the run means the suite was looking at a moving target, and the
    # rollback below would take their release away too (see
    # regression_deploy_intruded). So the run is repeated once against what is
    # serving now, and if it is still red nothing is rolled back automatically:
    # the release on top is not ours to remove.
    local intruders="" intruded=0
    if [[ "$prod_rc" -eq 1 ]]; then
      intruders="$(regression_deploy_intruded prod \
        "$(state_get "$wt/.sclaude/local/feature/state.json" regression.prod.started 2>/dev/null || true)" \
        "$(state_get "$wt/.sclaude/local/feature/state.json" regression.prod.finished 2>/dev/null || true)")" \
        && intruded=1
    fi
    if [[ "$intruded" -eq 1 ]]; then
      state_set "$wt/.sclaude/local/feature/state.json" regression.prod.intruded \
        "$(cut -f1 <<< "$intruders" | paste -sd' ')" 2>/dev/null || true
      echo ""
      warn "Production was deployed again while its regression was running:"
      while IFS=$'\t' read -r url created; do
        info "  $url"
      done <<< "$intruders"
      info "  The red may not be this feature's. Running the suite once more"
      info "  against what production serves now."
      regression_run "$wt" "$slug" prod
      prod_rc=$?
      if [[ "$prod_rc" -eq 1 ]]; then
        run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt" 0 1
        echo ""
        warn "Production is still red, and another release now sits on top of this one."
        info "  Nothing was rolled back: going back to the release before this"
        info "  feature would remove that one too. Look at the log, talk to whoever"
        info "  deployed it, and roll back by hand if it is this feature's:"
        info "    $SELF rollback $slug"
        info "  The worktree stays: $wt"
        return 0
      fi
    fi

    if [[ "$prod_rc" -eq 0 ]]; then
      state_set "$wt/.sclaude/local/feature/state.json" regression.prod.attempts 0 2>/dev/null || true
      regression_clear_mark "$wt" prod
    elif [[ "$prod_rc" -eq 2 ]]; then
      # The stage could not run at all — no address to aim at, nothing served.
      # A rollback is not the answer to a suite that never ran: the deployment
      # we would go back to may be the one that is not answering.
      run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt" 0 1
      echo ""
      warn "The production regression could not run — see above."
      info "  Nothing was rolled back: a suite that did not run says nothing"
      info "  about what is serving production."
      info "  The worktree stays: $wt"
      info "  Carry on with: $SELF $slug"
      return 0
    else
      # Red. Production goes back before anything else happens.
      rollback_prod "$wt" "$slug" --auto
      local rb_rc=$?

      # prod_done stays 1 and `deployed-prod` goes on: the code did reach
      # production, which is the whole of what that label says, and it is true
      # whatever the suite then found. What the label cannot say is that
      # production is broken right now — so the red mark says it, and
      # clear_regression_label takes it off when the stage next comes back
      # green. The preview keeps its own value: its suite passed in this same
      # run, and withdrawing a label it earned would be a second inaccuracy
      # covering the first.
      run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt" 0 1

      if [[ "$rb_rc" -ne 0 ]]; then
        echo ""
        warn "Production is broken and could not be rolled back."
        info "  Read what it said above and put it back by hand; the worktree and"
        info "  the branch stay where they are."
        info "  The worktree: $wt"
        info "  Carry on with: $SELF $slug"
        return 0
      fi

      rollback_confirm "$wt" "$slug"
      rollback_incident "$wt" "$slug" "$issue"

      echo ""
      warn "Production regression was red — production has been rolled back."
      info "  The feature is not in production; the release before it is."
      info "  The fix carries on from the review step, in this same tree, and"
      info "  goes the whole way round again: local suite, merge, preview and"
      info "  its suite, then production."
      info "  The worktree stays: $wt"
      info "  Carry on with: $SELF $slug"
      regression_rewind "$wt" "$slug" prod
      return 0
    fi
  fi

  # The outcome into the issue and its parents, before the clean-up: until this
  # line it is not known whether the feature made it to prod, and "where it is
  # now" is half of what the section exists for.
  run_status "$slug" "$issue" "$pr" "${merged:-}" "$preview_live" "$prod_done" "$wt"

  # The cycle is over here: every red or unrunnable production regression
  # returned above. So the issue closes — whether production carries the
  # feature or the human declined to ship it. A declined production used to
  # leave the issue open, and nothing ever came back to close it: one issue
  # stayed open, merged and accepted, after its production question was
  # answered no. Shipping later is `vercel --prod` from the repository, which
  # needs no open issue.
  if [[ "$prod_done" -eq 1 ]] || deploy_unchanged "$wt" prod; then
    issue_close_done "$issue" shipped
  else
    issue_close_done "$issue" declined
  fi

  # And only now the clean-up. It checks the merge against GitHub, shows what
  # exactly will disappear, and asks — once. There is deliberately no question
  # of our own here: asking before it would mean asking twice about the same
  # thing, and only it shows the list of what will be deleted, so its question
  # is the informed one. A refusal differs from agreement by the exit code —
  # only so as to hint at what this will continue with.
  #
  # A feature whose production regression failed keeps its tree either way: the
  # human answering "no" here is what the fixing session needs, and the hint
  # below is the way back.
  if ! cmd_done "$slug"; then
    info "Later: $SELF done $slug"
  fi
}
