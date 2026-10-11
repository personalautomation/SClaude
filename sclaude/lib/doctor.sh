#!/usr/bin/env bash
#
# `sclaude doctor` — what this machine has and lacks, with the command that
# fixes each gap.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Everything here used to be learned by failing: a step that stalls because gh
# lacks the `project` scope, a board that never moves because the token cannot
# see it, a bot that stays silent because the env file has no token, a laptop
# that sleeps under a phone session because linger is off. One person learned
# each of those once; a team would learn every one of them per person. So the
# answers are collected in one place, and each ✗ carries the command that turns
# it into a ✓.
#
# It changes nothing. Where fixing would mean granting something — Bash for
# every step, a polkit rule — it says what is missing and why, and the decision
# stays with the person.
#
# Exit status: 0 when nothing is ✗, 1 otherwise. Warnings (!) do not fail it:
# they are things a person may reasonably go without.

DOCTOR_BAD=0

doctor_ok()   { echo "  ${GREEN}✓${OFF} $1"; }
doctor_warn() {
  echo "  ${YELLOW}!${OFF} $1"
  [[ -n "${2:-}" ]] && echo "      ${DIM}$2${OFF}"
  return 0
}
doctor_bad()  {
  echo "  ${RED}✗${OFF} $1"
  [[ -n "${2:-}" ]] && echo "      ${DIM}$2${OFF}"
  DOCTOR_BAD=1
}
doctor_section() { echo ""; echo "${BOLD}$1${OFF}"; }

doctor_tools() {
  doctor_section "Tools"
  local tool
  for tool in git python3 claude gh; do
    if command -v "$tool" >/dev/null 2>&1; then
      doctor_ok "$tool"
    else
      doctor_bad "$tool is not on PATH" "every step needs it"
    fi
  done
  command -v node >/dev/null 2>&1 && doctor_ok "node" \
    || doctor_warn "node is not on PATH" "needed by projects that run npm scripts in their regression"
  command -v script >/dev/null 2>&1 && doctor_ok "script" \
    || doctor_warn "script is not on PATH" "the terminal is not recorded for the retrospective before sclaude done: apt install bsdutils"
  command -v tmux >/dev/null 2>&1 && doctor_ok "tmux" \
    || doctor_warn "tmux is not on PATH" "the terminal recording cannot be read back for the retrospective: apt install tmux"
  command -v vercel >/dev/null 2>&1 && doctor_ok "vercel" \
    || doctor_warn "vercel is not on PATH" "needed only to ship previews and production: npm i -g vercel"
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) doctor_ok "~/.local/bin is on PATH" ;;
    *) doctor_bad "~/.local/bin is not on PATH" "add it in your shell rc; install.sh links everything there" ;;
  esac
}

doctor_github() {
  doctor_section "GitHub"
  command -v gh >/dev/null 2>&1 || { doctor_bad "no gh — nothing below can be checked"; return; }
  local status scopes
  if ! status="$(gh auth status 2>&1)"; then
    doctor_bad "gh is not logged in" "gh auth login"
    return
  fi
  doctor_ok "gh is logged in as $(gh api user --jq .login 2>/dev/null || echo '?')"
  scopes="$(grep -o "Token scopes:.*" <<< "$status" | head -1)"
  if [[ -z "$scopes" ]]; then
    doctor_warn "could not read the token's scopes"
  elif grep -q "'project'" <<< "$scopes"; then
    doctor_ok "the token can move issues on project boards"
  else
    doctor_bad "the token lacks the 'project' scope — the board will not move" \
      "gh auth refresh -s project"
  fi
}

doctor_identity() {
  doctor_section "Who you are"
  local email name branch
  email="$(developer_email)"
  name="$(developer_name)"
  if [[ -n "$email" ]]; then
    doctor_ok "git user.email $email"
  else
    doctor_bad "no git user.email" "git config --global user.email you@example.com"
  fi
  if [[ -n "$name" ]]; then
    doctor_ok "developer name '$name' (prefixes test data, names your branch and records)"
  else
    doctor_warn "no developer name — test data and records are not marked as yours" \
      "set git user.email, or SCLAUDE_DEV"
  fi
  branch="$(git -C "$INSTRUMENTS" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if developer_is_maintainer; then
    doctor_ok "maintainer of the orchestrator (MAINTAINERS): fixes go to main"
  else
    doctor_ok "not in MAINTAINERS: fixes go to dev/${name:-local}, and to main through a pull request"
  fi
  [[ -n "$branch" ]] && doctor_ok "instruments is on $branch"

  # Bounded: a doctor that hangs on a dead network is a worse doctor than one
  # that says it could not look.
  if GIT_TERMINAL_PROMPT=0 timeout 15 git -C "$INSTRUMENTS" fetch -q origin main 2>/dev/null; then
    local behind
    behind="$(git -C "$INSTRUMENTS" rev-list --count HEAD..origin/main 2>/dev/null || echo 0)"
    if [[ "$behind" -gt 0 ]]; then
      doctor_warn "instruments is $behind commit(s) behind main" \
        "the next sclaude command brings them in (instruments_sync)"
    else
      doctor_ok "instruments is up to date with main"
    fi
  else
    doctor_warn "could not reach instruments' origin" \
      "no access? the repository must be readable to install from it"
  fi
}

doctor_claude() {
  doctor_section "Claude Code"
  local settings="$HOME/.claude/settings.json" posture
  posture="$(python3 - "$settings" <<'SETTINGS' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    print("none")
    sys.exit(0)
perms = data.get("permissions") or {}
bash = "Bash" in (perms.get("allow") or [])
auto = perms.get("defaultMode") == "auto"
print("both" if bash and auto else "bash" if bash else "auto" if auto else "neither")
SETTINGS
)"
  case "$posture" in
    both) doctor_ok "Bash is allowed and auto mode is on — steps 2-4 run without prompts" ;;
    *) doctor_warn "steps 2-4 will stop on permission prompts (settings: $posture)" \
         "sclaude's own bans assume permissions.allow [\"Bash\"] and defaultMode \"auto\" in ~/.claude/settings.json; granting them is your decision" ;;
  esac
  [[ -e "$HOME/.claude/skills/pr" ]] && doctor_ok "the pr skill is installed" \
    || doctor_bad "the pr skill is missing" "./install.sh"
  [[ -e "$HOME/.claude/statusline.py" ]] && doctor_ok "the status line is installed" \
    || doctor_warn "no status line" "./install.sh, then point statusLine in settings.json at ~/.claude/statusline.py"
}

# What sclaude writes into the project, kept out of git and of Vercel uploads
# (scratch.sh). Warnings only: the gaps sclaude can close it closes itself on
# the next run or deploy; one in a .vercelignore the project tracks is the
# project's to fix, and the line to add is printed.
doctor_scratch() {
  local root="$1" exclude="$1/.git/info/exclude" p missing=()
  for p in "${SCRATCH_PATHS[@]}"; do
    grep -qxF "$p" "$exclude" 2>/dev/null || missing+=("$p")
  done
  if (( ${#missing[@]} )); then
    doctor_warn "git can still see ${missing[*]}" "the next sclaude run adds them to .git/info/exclude"
  else
    doctor_ok "sclaude's own files are hidden from git"
  fi
  [[ -d "$root/.vercel" ]] || return 0
  local lack; lack="$(vercelignore_missing "$root" | tr '\n' ' ' | sed 's/ $//')"
  if [[ -z "$lack" ]]; then
    doctor_ok ".vercelignore keeps sclaude's files out of a deploy"
  elif vercelignore_tracked "$root"; then
    doctor_warn "the project's .vercelignore lets a deploy upload: $lack" "add those lines to it"
  else
    doctor_ok ".vercelignore is sclaude's; the next deploy adds: $lack"
  fi
}

# The product's environments, each the .env file it names (envs.py): the
# shape of the config, the files themselves, and who else can read them. A
# file of credentials that every user of the machine can read is a warning,
# not a failure: whether others share the machine is the person's to know.
doctor_environments() {
  local root="$1" old name file mode
  if old="$(envs old "$root")"; then
    doctor_bad "environments are in the old shape" "$old"
    return
  fi
  [[ -n "$(environment_names "$root")" ]] || return 0
  if [[ -n "$(environment_site "$root")" ]]; then
    doctor_ok "production answers at $(environment_site "$root")"
  else
    doctor_warn "no production address: mark the production environment protected, with its siteUrl"
  fi
  while IFS= read -r name; do
    file="$(envs file "$root" "$name")"
    if [[ ! -f "$file" ]]; then
      doctor_warn "$name: ${file#"$root"/} does not exist" "create it, or leave $name out of environments"
      continue
    fi
    mode="$(stat -c %a "$(readlink -f "$file")" 2>/dev/null || echo 600)"
    if [[ "${mode: -1}" != 0 || "${mode: -2:1}" != 0 ]]; then
      doctor_warn "$name: ${file#"$root"/} can be read by others ($mode)" "chmod 600 ${file#"$root"/}"
    fi
  done < <(environment_names "$root")
}

doctor_project() {
  doctor_section "This project"
  local root
  root="$(main_repo 2>/dev/null || true)"
  if [[ -z "$root" ]]; then
    doctor_warn "not inside a git repository — run doctor from a product to check it"
    return
  fi
  REPO="$root"
  if [[ ! -f "$root/.sclaude/config.json" ]]; then
    if [[ -f "$root/.sclaude.json" ]]; then
      doctor_bad "$root has the old .sclaude.json, which sclaude no longer reads" \
        "git mv .sclaude.json .sclaude/config.json, then describe environments by their .env files (sclaude/config.example.json)"
    else
      doctor_warn "$root has no .sclaude/config.json" "sclaude new offers to write one"
    fi
    return
  fi
  doctor_ok "$root/.sclaude/config.json"
  local section what
  for section in regression manuals database board; do
    case "$section" in
      regression) what="no regression: nothing gates step 2" ;;
      manuals) what="no manuals: step 1 reads none, step 3 updates none" ;;
      database) what="no migrations described" ;;
      board) what="no board: issues are not moved between columns" ;;
    esac
    if project_has "$section" "$root"; then
      doctor_ok "$section"
    else
      doctor_warn "$what"
    fi
  done
  doctor_environments "$root"
  if [[ -n "$(environment_site "$root")" ]] && command -v vercel >/dev/null 2>&1; then
    if (cd "$root" && timeout 20 vercel whoami >/dev/null 2>&1); then
      doctor_ok "vercel is logged in"
    else
      doctor_warn "vercel is not logged in — previews and production cannot ship" "vercel login"
    fi
  fi
  doctor_project_checks "$root"
  doctor_scratch "$root"
  if product_maintainer "$root"; then
    doctor_ok "you maintain this product: sclaude rules go to .sclaude/team/"
  else
    local mine; mine="$(product_rules_dir "$root")"
    doctor_ok "sclaude rules from your sessions go to ${mine#"$root"/}/ (team/ is the maintainers')"
  fi
  local names
  names="$(environment_choices "$root" | tr '\n' ' ' | sed 's/ $//')"
  if [[ -n "$names" ]]; then
    local saved; saved="$(environment_saved "$root" 2>/dev/null || true)"
    if [[ -n "${SCLAUDE_ENV:-}" ]]; then
      doctor_ok "environment: $SCLAUDE_ENV (SCLAUDE_ENV)"
    elif [[ -n "$saved" ]]; then
      doctor_ok "environment: $saved (saved answer)"
    else
      doctor_warn "no environment chosen yet (one of: $names)" "the first feature asks, once"
    fi
  fi
}

# What the project itself asks of a developer's machine, beyond what sclaude
# knows to look for: `.sclaude/config.json` → `doctor`, a list of
# { "what": "…", "check": "<command>", "fix": "<command>" }. The check runs in
# the project's root; exit 0 is a ✓, anything else a ! with the check's last
# line and the fix. Warnings, not failures: sclaude cannot know which of a
# project's extras a given developer needs — a phone sign-in, say.
doctor_project_checks() {
  local root="$1" item what check fix out rc
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    what="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("what",""))' "$item" 2>/dev/null)"
    check="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("check",""))' "$item" 2>/dev/null)"
    fix="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("fix",""))' "$item" 2>/dev/null)"
    [[ -n "$check" ]] || continue
    out="$(cd "$root" && timeout 60 bash -c "$check" 2>&1)"; rc=$?
    out="$(printf '%s\n' "$out" | sed '/^[[:space:]]*$/d' | tail -1 | sed 's/^ *//')"
    if [[ "$rc" -eq 0 ]]; then
      doctor_ok "${what:-$check}"
    else
      doctor_warn "${what:-$check}: ${out:-exit $rc}" "${fix:+$fix}"
    fi
  done < <(project_get doctor "$root" 2>/dev/null)
}

doctor_machine() {
  doctor_section "This machine"
  local platform unit
  platform="$(python3 "$INSTRUMENTS/keepawake/state.py" platform 2>/dev/null || echo "?")"
  doctor_ok "platform: $platform"

  if command -v systemctl >/dev/null 2>&1; then
    for unit in keepawake.timer sclaude-watch.timer keepawake-telegram.service \
                "keepawake-$([[ "$platform" == wsl ]] && echo windows || echo linux).service"; do
      if systemctl --user is-active --quiet "$unit" 2>/dev/null; then
        doctor_ok "$unit"
      else
        doctor_warn "$unit is not running" "./install.sh enables it (the bot only once its token is set)"
      fi
    done
    if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" == "yes" ]]; then
      doctor_ok "linger is on — the units outlive your last terminal"
    else
      doctor_warn "linger is off — the bot and the hold stop with your last terminal" \
        "sudo loginctl enable-linger $USER"
    fi
  else
    doctor_warn "no systemctl — keepawake and the QA watch cannot run"
  fi

  # The same test as install.sh's polkit_present: the rule itself where rules.d
  # can be read, the installer's note where it cannot (Fedora, Arch).
  local rule="${KEEPAWAKE_POLKIT_RULE:-/etc/polkit-1/rules.d/49-keepawake.rules}"
  local have_rule=0
  if [[ -f "$rule" ]] \
     || { [[ ! -r "$(dirname "$rule")" ]] && [[ -f "$HOME/.config/sclaude/polkit-rule" ]]; }; then
    have_rule=1
  fi
  if [[ "$platform" == linux && "$have_rule" -eq 0 ]]; then
    doctor_warn "keepawake holds idle only; a closed lid still sleeps" \
      "./install.sh --polkit adds the rule that allows it (asks for sudo)"
  fi

  local env="$HOME/.config/keepawake/env"
  if [[ ! -f "$env" ]]; then
    doctor_warn "no Telegram bot (~/.config/keepawake/env)" \
      "optional: your own bot from @BotFather; see keepawake/env.example"
    return
  fi
  if [[ "$(stat -c %a "$env" 2>/dev/null)" != "600" ]]; then
    doctor_bad "$env is readable by others" "chmod 600 $env"
  fi
  local token
  token="$(sed -n 's/^KEEPAWAKE_BOT_TOKEN=//p' "$env" | tail -1 | tr -d '"'"'"' ')"
  if [[ -z "$token" ]]; then
    doctor_bad "the bot has no token" "KEEPAWAKE_BOT_TOKEN in $env"
  elif curl -sf -m 10 "https://api.telegram.org/bot$token/getMe" >/dev/null 2>&1; then
    doctor_ok "the Telegram bot answers"
  else
    doctor_bad "Telegram does not accept the bot's token (or is unreachable)" \
      "check KEEPAWAKE_BOT_TOKEN in $env"
  fi
}

doctor_run() {
  echo "${BOLD}sclaude doctor${OFF} ${DIM}— what this machine has, and the command for each gap${OFF}"
  doctor_tools
  doctor_github
  doctor_identity
  doctor_claude
  doctor_project
  doctor_machine
  echo ""
  if [[ "$DOCTOR_BAD" -eq 0 ]]; then
    echo "${GREEN}Nothing is missing that sclaude needs.${OFF}"
  else
    echo "${RED}Something above is missing; each ✗ says how to fix it.${OFF}"
  fi
  return "$DOCTOR_BAD"
}
