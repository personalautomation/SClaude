#!/usr/bin/env bash
#
# sclaude's own checkout: taking the public main, proposing a change to
# it, and refreshing the systemd units (launchd agents on macOS) it installs.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.

# macOS's launchd agents, which take the units' place there.
source "$(dirname "${BASH_SOURCE[0]}")/../core/launchd.sh"

# A non-maintainer's dev/<name>, sent as a pull request into origin's main.
#
# The repository is public, and most people who use it cannot push to it. They
# were left with a failed push and three commands to type. Now the branch goes
# to origin when they can push there, and to a fork of theirs otherwise:
# sclaude makes the fork once, as the remote `fork`, with gh, and never moves
# origin, so updates go on coming from origin as before and the fork is only
# the way a pull request travels. The pull request is opened once and every
# later push updates it; a closed or merged one makes way for a new one.
# Returns 1 to leave the push to the plain path: no gh, an origin gh cannot
# place on GitHub, or a fork that could not be made; 2 when the push itself
# failed, which it has said how to finish.
#
#   [PROPOSE_DIR=<checkout>] [PROPOSE_INTRO=<text>] instruments_propose <branch> <commits>
#
# PROPOSE_DIR is where the branch is, $INSTRUMENTS by default; a workshop
# (workshop.sh) is a worktree of it with the same remotes. PROPOSE_INTRO opens
# the pull request's description.
instruments_propose() {
  local branch="$1" ahead="$2" dir="${PROPOSE_DIR:-$INSTRUMENTS}" slug remote=origin login head pr title body
  local intro="${PROPOSE_INTRO:-Changes to sclaude from \`$branch\`, made by hand by this developer and proposed with \`sclaude propose\`. Later pushes to the branch update this pull request.}"
  command -v gh >/dev/null 2>&1 || return 1
  slug="$(cd "$dir" && GH_PROMPT_DISABLED=1 gh repo view \
            --json nameWithOwner --jq .nameWithOwner 2>/dev/null)" || return 1
  [[ "$slug" == */* ]] || return 1
  if [[ "$(GH_PROMPT_DISABLED=1 gh api "repos/$slug" --jq .permissions.push 2>/dev/null)" != "true" ]]; then
    if ! git -C "$dir" remote get-url fork >/dev/null 2>&1; then
      info "  instruments: you cannot push to $slug; making your fork of it, once"
      ( cd "$dir" && GH_PROMPT_DISABLED=1 gh repo fork \
          --remote --remote-name fork >/dev/null 2>&1 ) || return 1
      git -C "$dir" remote get-url fork >/dev/null 2>&1 || return 1
    fi
    remote=fork
  fi

  info "  instruments: pushing $ahead commit(s) to $remote/$branch"
  local push_out
  if ! push_out="$(GIT_TERMINAL_PROMPT=0 git -C "$dir" push -q -u "$remote" "$branch" 2>&1)"; then
    warn "  instruments: push failed — the work is committed but not sent"
    warn "  finish it by hand: git -C $dir push $remote $branch"
    [[ -z "$push_out" ]] || warn "$(tail -n 12 <<< "$push_out" | sed 's/^/     /')"
    return 2
  fi

  head="$branch"
  if [[ "$remote" == fork ]]; then
    login="$(GH_PROMPT_DISABLED=1 gh api user --jq .login 2>/dev/null)" || login=""
    [[ -n "$login" ]] && head="$login:$branch"
  fi
  pr="$(GH_PROMPT_DISABLED=1 gh pr list --repo "$slug" --head "$branch" \
          --state open --json url --jq '.[0].url // ""' 2>/dev/null)" || pr=""
  if [[ -n "$pr" ]]; then
    info "✓ instruments: pushed; your pull request has it: $pr"
    return 0
  fi

  # Named by its one commit, or by whose fixes they are.
  if [[ "$(git -C "$dir" rev-list --count origin/main..HEAD 2>/dev/null)" == 1 ]]; then
    title="$(git -C "$dir" log -1 --format=%s 2>/dev/null)"
  else
    title="sclaude: fixes from $(developer_name 2>/dev/null || echo "$branch")"
  fi
  body="$(printf '%s\n\n%s\n' "$intro" \
    "$(git -C "$dir" log origin/main..HEAD --format='- %s' 2>/dev/null)")"
  if pr="$(GH_PROMPT_DISABLED=1 gh pr create --repo "$slug" --base main \
             --head "$head" --title "$title" --body "$body" 2>/dev/null)"; then
    info "✓ instruments: pushed, and opened a pull request: $pr"
  else
    warn "instruments: pushed to $remote/$branch, but the pull request did not open — open it by hand: gh pr create --repo $slug --base main --head $head --fill"
  fi
  return 0
}

# sclaude propose: a change to sclaude's out-of-the-box behaviour, sent to it
# deliberately as a pull request. The change is commits in this checkout,
# made by hand; sessions never make them. Commits on main are moved to a
# branch of their own, dev/<name> (or dev/<name>-<time> when that is taken), and
# main goes back to origin's: the person stays on the branch, which
# instruments_sync keeps merging main into, so they go on running their change
# until it is merged. The branch then goes out by instruments_propose. Run from
# a product, it first lists the product's deferred entries of class
# sclaude-default: the findings that asked for such a change.
cmd_propose() {
  local root branch name ahead new
  root="$(main_repo 2>/dev/null || true)"
  if [[ -n "$root" && "$(cd "$root" && pwd -P)" != "$(cd "$INSTRUMENTS" && pwd -P)" ]]; then
    local f found=""
    while IFS= read -r f; do
      while IFS= read -r line; do
        [[ -n "$found" ]] || { echo ""; info "  Findings in this product that asked for a change to sclaude:"; found=1; }
        info "    ${f#"$root"/}: $(cut -f6 <<< "$line")"
      done < <(awk -F'\t' '$5 == "sclaude-default"' "$f" 2>/dev/null)
    done < <(deferred_files "$root")
  fi
  if [[ -n "$(git -C "$INSTRUMENTS" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    warn "  $INSTRUMENTS has uncommitted changes. Commit the change you mean to propose,"
    warn "  by this repository's rules, and run it again: $SELF propose"
    return 1
  fi
  GIT_TERMINAL_PROMPT=0 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null || true
  ahead="$(git -C "$INSTRUMENTS" rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
  if [[ ! "$ahead" =~ ^[1-9][0-9]*$ ]]; then
    info "  Nothing to propose: $INSTRUMENTS has no commits beyond origin/main."
    return 0
  fi
  branch="$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [[ "$branch" == "main" ]]; then
    name="$(developer_name 2>/dev/null)"
    new="dev/${name:-local}"
    git -C "$INSTRUMENTS" show-ref --verify -q "refs/heads/$new" && new="$new-$(date +%Y%m%d-%H%M)"
    git -C "$INSTRUMENTS" switch -q -c "$new" 2>/dev/null || { warn "  could not make $new"; return 1; }
    git -C "$INSTRUMENTS" branch -q -f main origin/main 2>/dev/null || true
    info "  $ahead commit(s) moved from main to $new; main is origin's again"
    branch="$new"
  fi
  local sent=0
  instruments_propose "$branch" "$ahead" || sent=$?
  (( sent == 0 )) && return 0
  (( sent == 2 )) && return 1
  warn "  could not send it as a pull request (gh missing, or origin is not on GitHub)."
  warn "  The commits are on $branch: push it and open the pull request by hand."
  return 1
}

# Brings this machine's installed systemd units up to the repository's
# (launchd's agents on macOS).
#
# install.sh writes them with the checkout's path put in for @REPO@, and
# nothing wrote them again when an update changed one: a unit installed as a
# link into the repository, as an older install.sh made them, came to say
# ExecStart=… @REPO@/… and the Telegram bot crash-looped on it; a written one
# kept its old lines (KillMode). Only units already installed are touched, and
# only when they differ; systemd is told once when any did.
#
#   units_refresh
units_refresh() {
  # macOS has launchd's agents instead (sclaude/lib/core/launchd.sh).
  # SCLAUDE_OS (linux or macos) overrides what the system says, for the tests.
  local os="${SCLAUDE_OS:-}"
  [[ -n "$os" ]] || { [[ "${OSTYPE:-}" == darwin* ]] && os=macos; }
  if [[ "$os" == macos ]]; then
    launchd_refresh
    return 0
  fi
  # Where install.sh writes them, which does not read XDG_CONFIG_HOME.
  local units="$HOME/.config/systemd/user" src name want link
  local -a changed=()
  [[ -d "$units" && -d "$INSTRUMENTS/systemd" ]] || return 0
  for src in "$INSTRUMENTS"/systemd/*; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    [[ -e "$units/$name" || -L "$units/$name" ]] || continue
    want="$(sed "s|@REPO@|$INSTRUMENTS|g" "$src")"
    # Only a link an older install made, into this checkout or one since
    # moved, is replaced: a mask (a link to /dev/null) or a unit of the
    # person's own linked in stays theirs.
    if [[ -L "$units/$name" ]]; then
      link="$(readlink "$units/$name" 2>/dev/null || true)"
      [[ "$link" == */systemd/"$name" ]] || continue
    elif [[ "$(cat "$units/$name" 2>/dev/null)" == "$want" ]]; then
      continue
    fi
    rm -f "$units/$name"
    printf '%s\n' "$want" > "$units/$name" && changed+=("$name")
  done
  (( ${#changed[@]} )) && command -v systemctl >/dev/null 2>&1 || return 0
  systemctl --user daemon-reload >/dev/null 2>&1 || return 0
  # A unit that crash-looped on the old file has failed for good, and is
  # brought back: through its socket when it has one (the proxy, which has no
  # [Install] of its own), or started when it is enabled. Nothing running is
  # restarted — the bot or the editor restarted from here would take this
  # very sclaude down with its cgroup — and a static unit (a timer's oneshot)
  # is not started by hand. A running one is named, for the person to restart.
  local socket enabled stale=""
  for name in "${changed[@]}"; do
    if systemctl --user is-active -q "$name" 2>/dev/null; then
      stale+=" $name"
      continue
    fi
    systemctl --user is-failed -q "$name" 2>/dev/null || continue
    socket="${name%.service}.socket"
    systemctl --user reset-failed "$name" >/dev/null 2>&1 || true
    if [[ "$name" == *.service && -e "$units/$socket" ]]; then
      systemctl --user reset-failed "$socket" >/dev/null 2>&1 || true
      systemctl --user start --no-block "$socket" >/dev/null 2>&1 || true
      continue
    fi
    enabled="$(systemctl --user is-enabled "$name" 2>/dev/null || true)"
    case "$enabled" in
      enabled|enabled-runtime|indirect)
        systemctl --user start --no-block "$name" >/dev/null 2>&1 || true ;;
    esac
  done
  [[ -n "$stale" ]] && info "  updated, and running on the old file until restarted:${stale} (systemctl --user restart${stale})"
  return 0
}

# The branches sclaude may push and merge main into: main, and this person's
# dev/<name>, with the time cmd_propose may add. Anything else in sclaude's
# checkout is somebody's own work in progress.
instruments_own_branch() {
  local branch="$1" name
  [[ "$branch" == "main" ]] && return 0
  name="$(developer_name 2>/dev/null || true)"
  # And the dev/<name>-<time> cmd_propose makes when dev/<name> exists already:
  # not merging main into it left its owner on an orchestrator that never moved.
  [[ "$branch" == "dev/${name:-local}" || "$branch" == "dev/${name:-local}-"[0-9]* ]]
}

# Whether another sclaude is running from this checkout, in another terminal.
#
# Its bash has sourced the modules already, but its claude sessions read hooks
# and prompts from disk when they use them, and it calls the python helpers by
# path with the arguments of the code it loaded. Updating the files under it is
# the in-place-edit hazard CLAUDE.md describes, spread across processes — so the
# update waits for a moment when nobody else is running.
#
# Another terminal, not this one: a process in our own session is this run and
# its subshells. The bot's short `sclaude status` calls count too, and only cost
# an update deferred to the next command.
#
# Nor our own ancestors. term_record runs this sclaude under script(1), which
# starts it in a session of its own, and script's command line names sclaude:
# every recorded run read its own recorder as "another sclaude (pid N)" — N being
# the pid in the name of its own recording — and never updated.
#
# Every one of them is named, one per session, with what it runs and for how
# long: naming the first alone sent the person to close it only to meet the
# next, and a bare pid says nothing about a process with no terminal of its own.
#
# sclaude is the command, not a word anywhere in the line: `sclaude …` itself or
# `bash …/sclaude …`. A step session is `claude --resume … <prompt>`, and its
# prompt names sclaude — matched by the word, every running step of another
# feature read as a sclaude, and the tail of its prompt was printed as what it
# runs. A recorder (`script -c sclaude …`) is left out the same way; the sclaude
# it records is found under its own pid.
instruments_others() {
  local mysid pid sid etime args cmd rest up=$$ ancestors=" " seen=" " found=""
  mysid="$(ps -o sid= -p $$ 2>/dev/null | tr -d ' ')"
  while up="$(ps -o ppid= -p "$up" 2>/dev/null | tr -d ' ')" \
        && [[ "$up" =~ ^[0-9]+$ && "$up" -gt 1 ]]; do
    ancestors+="$up "
  done
  while read -r pid sid etime args; do
    [[ -n "$mysid" && "$sid" == "$mysid" ]] && continue
    [[ "$ancestors" == *" $pid "* ]] && continue
    [[ "$seen" == *" $sid "* ]] && continue
    read -r cmd rest <<<"$args"
    [[ "${cmd##*/}" == bash || "${cmd##*/}" == sh ]] && read -r cmd rest <<<"$rest"
    [[ "${cmd##*/}" == sclaude ]] || continue
    (( ${#rest} > 60 )) && rest="${rest:0:60}…"
    seen+="$sid "
    found+="${found:+, }pid $pid: sclaude${rest:+ $rest}, up $etime"
  done < <(ps -eo pid=,sid=,etime=,args= 2>/dev/null)
  [[ -n "$found" ]] || return 1
  echo "$found"
}

# Brings the orchestrator up to date before anything runs, as far as the
# machine lets it (sclaude.update in developer.sh): `auto` takes main here,
# `notify` only says what main has (instruments_notify) and leaves it to
# `sclaude update`, `off` does not fetch. Unset, the person is asked once.
#
# Everybody installs instruments from one repository rather than keeping a fork,
# so the only way a fix reaches a team is this: at the start of a command that
# is about to act, fetch main and bring it in. Without it each machine runs
# whatever it happened to clone, and a copy used from two machines runs two
# orchestrators.
#
# The branch comes first. MAINTAINERS says who may commit the orchestrator to
# main; for anybody else the friction review has to commit somewhere else, and
# switching branches under a running review would change the prompts and hooks
# it reads from disk mid-session. So it happens here, before any step, and the
# process restarts on the result.
#
# What is deliberately left alone:
#
#   a dirty tree       somebody is editing the orchestrator by hand; a merge
#                      would mix into their work. Said, not done.
#   a conflict         aborted, said, and the run continues on the code as it
#                      was — a broken merge is worse than a stale orchestrator.
#   no network         silent; the fetch is bounded so it cannot hang a start.
#   SCLAUDE_NO_SYNC    set by benches, which run the real bin/sclaude from this
#                      repository and must not fetch or merge anything.
#   another sclaude    running from this checkout in another terminal: its
#                      sessions read the files being replaced (see
#                      instruments_others). The update waits for a free moment.
#   another branch     anything but main and dev/<name> is somebody's own work,
#                      and main is not merged into it — unless its own commits
#                      are all in main already (instruments_taken_in): then it
#                      is left for main, kept as it is.
#
# After a change the process re-executes itself: bash has already read this
# file and sourced every module, and carrying on would run the old code over
# the new files. SCLAUDE_SYNCED stops the second run from doing it again.
instruments_sync() {
  [[ -z "${SCLAUDE_NO_SYNC:-}" && -z "${SCLAUDE_SYNCED:-}" ]] || return 0
  git -C "$INSTRUMENTS" remote get-url origin >/dev/null 2>&1 || return 0

  # The machine's say (sclaude.update, developer.sh): code from the public
  # main runs here only where the person chose it.
  local mode; mode="$(update_mode)"
  if [[ "$mode" == ask ]]; then
    update_mode_choose
    mode="$UPDATE_CHOSEN"
  fi
  case "$mode" in
    off)    return 0 ;;
    notify) instruments_notify; return 0 ;;
  esac
  instruments_take || return 0
  export SCLAUDE_SYNCED=1
  exec "$0" "$@"
}

# What sclaude's main has that this checkout does not, said rather than taken
# (sclaude.update notify): the commits in full when main moved since they were
# last listed, a line otherwise, so that a start is not a page of the same
# list every time.
instruments_notify() {
  local behind head seen mark
  GIT_TERMINAL_PROMPT=0 timeout 20 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null || return 0
  behind="$(git -C "$INSTRUMENTS" rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  [[ "$behind" =~ ^[1-9][0-9]*$ ]] || return 0
  head="$(git -C "$INSTRUMENTS" rev-parse origin/main 2>/dev/null)"
  mark="$(git -C "$INSTRUMENTS" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/sclaude-notified"
  seen="$(cat "$mark" 2>/dev/null || true)"
  if [[ "$seen" == "$head" ]]; then
    info "  instruments: $behind commit(s) on sclaude's main not taken yet — $SELF update"
    return 0
  fi
  info "  instruments: $behind new commit(s) on sclaude's main:"
  local line
  while IFS= read -r line; do info "    $line"; done \
    < <(git -C "$INSTRUMENTS" log --format='%h %s' -n 10 HEAD..origin/main 2>/dev/null)
  (( behind > 10 )) && info "    … and $((behind - 10)) more: git -C $INSTRUMENTS log HEAD..origin/main"
  info "  Take them with: $SELF update"
  printf '%s\n' "$head" > "$mark" 2>/dev/null || true
}

# Said at a start, and the run goes on: branches of sclaude's checkout whose
# work is found nowhere else (local_branches.py). The one warning such work
# had before, workshop_remove's, was printed once at a tree's removal and
# scrolled away; a change reviewed four times lay unpublished for weeks.
# `sclaude doctor` lists every local branch with what to do about it.
#
# The terminal alone, not info: the line is about this machine's checkout, and
# info hands what it prints to the feature's topic, which others read. Once
# per run: sclaude re-executes itself at a session's end and between steps,
# and the line would come again each time.
instruments_local_note() {
  [[ -z "${SCLAUDE_NO_SYNC:-}" && -z "${SCLAUDE_LOCAL_NOTED:-}" ]] || return 0
  export SCLAUDE_LOCAL_NOTED=1
  local line
  if line="$(timeout 10 python3 "$INSTRUMENTS/sclaude/lib/improve/local_branches.py" note "$INSTRUMENTS" 2>/dev/null)"; then
    [[ -z "$line" ]] || echo "${DIM}  $line${OFF}" >&2
  elif [[ $? -eq 124 ]]; then
    echo "${DIM}  instruments: the look for local branches took too long — sclaude doctor lists them${OFF}" >&2
  fi
}

# sclaude update: takes sclaude's main now, whatever sclaude.update says.
cmd_update() {
  git -C "$INSTRUMENTS" remote get-url origin >/dev/null 2>&1 \
    || die "$INSTRUMENTS has no origin to update from"
  if ! GIT_TERMINAL_PROMPT=0 timeout 30 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null; then
    warn "  Could not reach sclaude's repository: not updated."
    return 1
  fi
  local behind line
  behind="$(git -C "$INSTRUMENTS" rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
  if [[ ! "$behind" =~ ^[1-9][0-9]*$ ]]; then
    info "  instruments: up to date with sclaude's main."
    return 0
  fi
  while IFS= read -r line; do info "    $line"; done \
    < <(git -C "$INSTRUMENTS" log --format='%h %s' -n 20 HEAD..origin/main 2>/dev/null)
  if [[ "$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null)" == HEAD ]]; then
    warn "  instruments: not updated — $INSTRUMENTS is on no branch; switch it to main first."
    return 1
  fi
  INSTRUMENTS_SAY=1 instruments_take || return 1
  units_refresh
  info "  The next sclaude command runs it."
}

# Whether everything HEAD has is in sclaude's main already — a change taken
# in as a squashed pull request, under commits of another name: merging the
# two gives main's own tree. Such commits are nothing to keep; left, they
# hold the checkout off main for good. A HEAD with no commits of its own —
# only behind, as a branch kept on an older sclaude on purpose — is not one.
instruments_taken_in() {
  local merged main
  ! git -C "$INSTRUMENTS" merge-base --is-ancestor HEAD origin/main 2>/dev/null || return 1
  merged="$(git -C "$INSTRUMENTS" merge-tree --write-tree HEAD origin/main 2>/dev/null)" || return 1
  main="$(git -C "$INSTRUMENTS" rev-parse 'origin/main^{tree}' 2>/dev/null)" || return 1
  [[ -n "$main" && "${merged%%$'\n'*}" == "$main" ]]
}

# Whether moving this checkout onto sclaude's main is ours to do: the branch
# follows origin (or nothing), and origin is sclaude's own repository, not
# somebody's fork. A person who works through a fork keeps their checkout
# where they put it — told, never moved. Not known (no gh, no network) is not
# a yes.
instruments_follows_upstream() {
  local up url
  up="$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
  [[ -z "$up" || "$up" == origin/* ]] || return 1
  url="$(git -C "$INSTRUMENTS" remote get-url origin 2>/dev/null)" || return 1
  [[ "$(GH_PROMPT_DISABLED=1 timeout 10 gh repo view "$url" --json isFork --jq .isFork 2>/dev/null)" == false ]]
}

# Said at a start when main has a newer sclaude that could not be taken here:
# that there is one, and the command that takes it — a note, not a question:
# the run goes on, on the code it has.
#
# Every command stands alone on its line, to be pasted whole: what it does
# goes on the next, and a second command it calls for on a line of its own.
#
#   instruments_offer <commits behind> <command> [<what it does> [<then this>]]
instruments_offer() {
  info "  instruments: sclaude has a newer version on main ($1 commit(s)); consider taking it."
  info "  To take it: $2"
  [[ -z "${3:-}" ]] || info "  $3"
  [[ -z "${4:-}" ]] || info "    $4"
}

# Brings the checkout up to sclaude's main, as far as that is safe here and
# now; 0 when it changed and the process has to run again.
instruments_take() {
  local branch changed="" name own behind other
  branch="$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  [[ -n "$branch" && "$branch" != "HEAD" ]] || return 1

  if other="$(instruments_others)"; then
    info "  instruments: not updated — another sclaude is running from it ($other)"
    return 1
  fi

  # Everybody's checkout stays on main and follows it. A non-maintainer used to
  # be moved to dev/<name> first, because friction reviews committed their
  # fixes to sclaude; they change the product now, and a change to sclaude
  # itself is proposed deliberately, on a branch of its own.
  if ! GIT_TERMINAL_PROMPT=0 timeout 20 \
       git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null; then
    # Silent at a start (no network is no news); said when asked for.
    [[ -n "${INSTRUMENTS_SAY:-}" ]] && warn "  instruments: not updated — origin did not answer."
  else
    behind="$(git -C "$INSTRUMENTS" rev-list --count HEAD..origin/main 2>/dev/null || true)"
    if [[ "$behind" =~ ^[0-9]+$ && "$behind" -gt 0 ]]; then
      name="$(developer_name 2>/dev/null || true)"; name="${name:-local}"
      # The checkout's path as it is pasted back into a shell, spaces and all.
      local dir; printf -v dir '%q' "$INSTRUMENTS"
      if [[ -n "$(git -C "$INSTRUMENTS" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
        warn "  instruments: $behind commit(s) behind main, not updated —"
        warn "  $INSTRUMENTS has uncommitted changes"
        # In words, not a chain of git commands: pasted later, after the
        # person committed or reverted, a stash that saves nothing would pop
        # an older entry onto the work (decided by the user, 2026-11-17).
        # On main a commit of the edits would itself hold main back
        # (diverged): stash there; a branch of one's own takes a merge.
        if [[ "$branch" == main ]]; then
          instruments_offer "$behind" "$SELF update" "Stash your changes in $dir first, and git stash pop after."
        elif instruments_own_branch "$branch"; then
          instruments_offer "$behind" "$SELF update" "Commit or stash your changes in $dir first."
        else
          instruments_offer "$behind" "$SELF update" "Commit or stash your changes in $dir, and switch it to main, first."
        fi
      elif [[ "$branch" == "main" ]]; then
        own="$(git -C "$INSTRUMENTS" rev-parse --short HEAD 2>/dev/null)"
        if git -C "$INSTRUMENTS" merge -q --ff-only origin/main >/dev/null 2>&1; then
          info "  instruments: updated by $behind commit(s) from main"
          changed=1
        elif instruments_taken_in && instruments_follows_upstream \
             && git -C "$INSTRUMENTS" reset -q --keep origin/main >/dev/null 2>&1; then
          info "  instruments: your commits on main are in sclaude's main already (taken in"
          info "  as a pull request); main follows it again (they were $own)"
          changed=1
        else
          warn "  instruments: main has diverged from origin/main; not updated"
          # The move cmd_propose makes: onto dev/<name> (with the time when
          # that is taken), and main back to sclaude's; main is merged into
          # that branch at every start from then on.
          local keep="dev/$name"
          git -C "$INSTRUMENTS" rev-parse -q --verify "refs/heads/$keep" >/dev/null 2>&1 \
            && keep="dev/$name-$(date +%Y%m%d-%H%M)"
          instruments_offer "$behind" "git -C $dir switch -c $keep && git -C $dir branch -f main origin/main" \
            "Your commits go on with you on $keep, and main is merged into it at every start."
        fi
      elif ! instruments_own_branch "$branch"; then
        # Its main may hold the same commits (made there, then branched), so
        # main is taken the way main is above; neither works, and the branch
        # is switched back to as it was.
        if instruments_taken_in && instruments_follows_upstream \
           && git -C "$INSTRUMENTS" switch -q main >/dev/null 2>&1; then
          # main is asked again — its own upstream may be the person's fork.
          if instruments_follows_upstream \
             && { git -C "$INSTRUMENTS" merge -q --ff-only origin/main >/dev/null 2>&1 \
                  || { instruments_taken_in \
                       && git -C "$INSTRUMENTS" reset -q --keep origin/main >/dev/null 2>&1; }; }; then
            info "  instruments: $branch is in sclaude's main already (taken in as a pull"
            info "  request); switched to main, which follows it again"
            changed=1
          else
            git -C "$INSTRUMENTS" switch -q "$branch" >/dev/null 2>&1
          fi
        fi
        if [[ -z "$changed" ]]; then
          info "  instruments: $behind commit(s) behind main; $branch is not"
          info "  sclaude's to merge into (only main and dev/<name> are)"
          instruments_offer "$behind" "git -C $dir merge origin/main" "Or, to leave $branch for main:" "git -C $dir switch main"
        fi
      else
        local merge_out
        if merge_out="$(git -C "$INSTRUMENTS" merge -q --no-edit origin/main 2>&1)"; then
          info "  instruments: merged $behind commit(s) from main into $branch"
          changed=1
        elif [[ -n "$(git -C "$INSTRUMENTS" ls-files -u 2>/dev/null)" ]]; then
          # A real conflict: our merge stopped half-way, and only then is there
          # a merge of ours to abort. Aborting on any failure could abort
          # somebody else's merge — another process holding index.lock is also
          # a failure.
          git -C "$INSTRUMENTS" merge --abort >/dev/null 2>&1 || true
          warn "  instruments: merging main into $branch conflicts; left as it was"
          warn "  resolve it by hand: git -C $dir merge origin/main"
        else
          warn "  instruments: could not merge main into $branch; left as it was"
          warn "  git said: $(head -1 <<< "$merge_out")"
        fi
      fi
    fi
  fi

  [[ -n "$changed" ]]
}
