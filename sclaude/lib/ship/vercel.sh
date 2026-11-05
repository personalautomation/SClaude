#!/usr/bin/env bash
#
# Running a deploy: vercel and the project's own deploy command, a preview with
# its migrations, and whether main is ready for production.
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

  # Kept for the question (ask_note) rather than said to the feature's topic:
  # a deploy tells the topic itself when it starts and ends (phase_line), and
  # a question carries what it rests on to the phone anyway.
  echo ""
  say_here "${BOLD}$title${OFF}"
  [[ -n "$note" ]] && say_here "${DIM}$note${OFF}"
  echo ""
  # The list of commands is the very context without which "Publish?" is
  # meaningless: the human agrees to what they see, and on a phone they must see
  # the same thing.
  for cmd in "$@"; do
    say_here "  $cmd"
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
      # Which command is at work, for a caller that names what failed to the
      # session fixing it (preview_ship, remind_prod): the block's own output
      # stays in the terminal.
      [[ -n "${SCLAUDE_BLOCK_AT:-}" ]] && printf '%s\n' "$cmd" > "$SCLAUDE_BLOCK_AT"
      if [[ "$cmd" == vercel\ * ]]; then
        run_vercel "$cmd" || exit 1
      else
        eval "$cmd" || exit 1
      fi
    done
  )
  # 2, not the 1 of a "no": a caller tells the topic a deploy failed by it
  # (phase_line), so these lines stay in the terminal.
  if [[ $? -ne 0 ]]; then
    warn_here ""
    warn_here "  ✗ $title — a command failed, stopping here."
    warn_here "    The rest of this block did not run."
    return 2
  fi
  # The outcome is printed afterwards: `vercel` ends its output with escape
  # sequences that erase the previous lines, and without this separator no trace
  # is left on the screen either of the question or of how it ended.
  echo ""
  echo "${GREEN}✓ $title — done.${OFF}"
  return 0
}

# The commits main holds in the main tree that origin does not, as
# "<sha> <subject>" lines; nothing when main is level with origin or only
# behind it.
#
# No fetch. A commit made here is missing from every older origin/main, so a
# stale ref hides none of them; a fetch would only hold the production
# question up, and empty the origin/main...HEAD ranges a later run reads (the
# branch's migrations among them).
main_unpushed() {
  git -C "$1" log --format='%h %s' origin/main..main 2>/dev/null
}

# Lines for the person, ten at most, each through info so that a question
# relayed elsewhere carries them too.
#
#   say_lines <lines>
say_lines() {
  local lines="$1" n line
  [[ -n "$lines" ]] || return 0
  n="$(wc -l <<< "$lines")"
  head -10 <<< "$lines" | while IFS= read -r line; do info "    $line"; done
  [[ "$n" -gt 10 ]] && info "    … and $((n - 10)) more"
  return 0
}

# Whether production must stop because main in the main tree is not what
# origin holds, said; silent, and 1, when it can go.
#
#   prod_main_unready <repo>
#
# `vercel --prod` uploads that tree. A commit origin lacks, or a change not
# committed at all, would ship unpushed and unreviewed, and either can stop
# the block's pull halfway through a yes. Neither is pushed, rebased, stashed
# or dropped on the person's behalf: whether it belongs on origin is theirs to
# say.
#
# sclaude's own config is held to the same: the settings every feature reads
# from this tree (project_config), edited here by hand or through `sclaude
# config`, must be what origin holds before production goes. An edit here and
# not on origin is a setting nobody else has, and one the pull would bury in a
# stash when origin changes the file too. Where the two copies differ is
# listed key by key (config_diff.py), and making them equal is the person's:
# commit and push the edit, or take origin's copy.
prod_main_unready() {
  local repo="$1" commits dirt config=".sclaude/config.json" cfgdiff=""
  commits="$(main_unpushed "$repo")"
  dirt="$(worktree_dirt "$repo" "$config")"
  if [[ -n "$(git -C "$repo" status --porcelain -- "$config" 2>/dev/null)" ]]; then
    cfgdiff="$(prod_config_diff "$repo")"
  fi
  [[ -n "$commits$dirt$cfgdiff" ]] || return 1
  echo ""
  alarm "Production — main in $repo is not what origin holds:"
  if [[ -n "$commits" ]]; then
    info "  Commits origin does not have:"
    say_lines "$commits"
    info "  Push them (git -C $repo push origin main), or drop them — whether they"
    info "  belong on origin is yours to say. If origin has moved on as well, bring"
    info "  main level with it first, as you would any branch."
  fi
  if [[ -n "$dirt" ]]; then
    info "  Changes not committed:"
    say_lines "$dirt"
    info "  Commit and push them, or put them away (git -C $repo stash)."
  fi
  if [[ -n "$cfgdiff" ]]; then
    info "  $config here is not origin's — where they differ (here · origin):"
    local key here theirs
    while IFS=$'\t' read -r key here theirs; do
      [[ -n "$key" ]] && info "    $key: $here · $theirs"
    done <<< "$cfgdiff"
    info "  Make them equal: commit and push your edit (bring main level with"
    info "  origin first if it is behind), or take origin's copy"
    info "  (git -C $repo checkout origin/main -- $config)."
  fi
  return 0
}

# The keys where the main tree's config differs from origin's main, as
# config_diff.py lists them; nothing when they are equal. One fetch, short and
# silent: a stale origin/main is compared when it fails.
#
#   prod_config_diff <repo>
prod_config_diff() {
  local repo="$1" config=".sclaude/config.json" theirs
  GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$repo" fetch -q origin main 2>/dev/null || true
  theirs="$(mktemp)"
  git -C "$repo" show "origin/main:$config" > "$theirs" 2>/dev/null || : > "$theirs"
  python3 "$LIB/ship/config_diff.py" "$repo/$config" "$theirs"
  rm -f "$theirs"
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
  local wt="$1" url_file try state="$1/.sclaude/local/feature/state.json"
  local at="$1/.sclaude/local/feature/deploy.at"
  url_file="$wt/.sclaude/local/feature/preview.url"
  rm -f "$url_file"
  ask_feed say "$(phase_line started deploy preview)"
  history_add "$wt/.sclaude/local/feature/state.json" deploy.preview start
  for ((try = 1; try <= PREVIEW_TRIES; try++)); do
    if SCLAUDE_BLOCK_AT="$at" SCLAUDE_VERCEL_URL_FILE="$url_file" preview_deploy "$wt"; then
      deploy_remember "$wt" preview
      if [[ -s "$url_file" ]]; then
        state_set "$wt/.sclaude/local/feature/state.json" regression.preview.url "$(< "$url_file")"
      fi
      history_add "$wt/.sclaude/local/feature/state.json" deploy.preview done
      ask_feed say "$(phase_line finished deploy preview)$([[ -s "$url_file" ]] && printf ' · %s' "$(< "$url_file")")"
      rm -f "$url_file" "$at"
      return 0
    fi
    if [[ "$try" -lt "$PREVIEW_TRIES" ]]; then
      # The terminal's alone: a retry that works is no news to a phone, and
      # one that does not ends in the failed line below.
      warn_here "  The preview deploy failed — trying again in ${PREVIEW_RETRY_PAUSE}s ($((try + 1))/$PREVIEW_TRIES)."
      sleep "$PREVIEW_RETRY_PAUSE"
    else
      # The topic's line is the phase's, with a sound; the terminal's names
      # the log right above it.
      alarm_here "  The preview deploy failed $PREVIEW_TRIES times — the log is above."
      history_add "$wt/.sclaude/local/feature/state.json" deploy.preview failed
      ask_feed alarm "$(phase_line failed deploy preview) · $PREVIEW_TRIES tries, the log is in the terminal"
    fi
  done
  # The command that failed, for the session the gate opens on it
  # (regression_fix_block): the block's output stays in the terminal.
  state_set "$state" regression.preview.deploy_failed "$(cat "$at" 2>/dev/null || echo the deploy)" 2>/dev/null || true
  # What the preview serves is not what was meant to go up: the gate deploys
  # again rather than run the suite against it (deploy_unchanged).
  state_set "$state" deploy.preview.sha null 2>/dev/null || true
  rm -f "$url_file" "$at"
  return 1
}
