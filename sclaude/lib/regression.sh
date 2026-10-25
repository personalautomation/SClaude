#!/usr/bin/env bash
#
# The regression run: the trace in the world that step 2 was missing.
#
# Part of sclaude; pulled in with source from bin/sclaude.
# It does not run on its own.
#
# Three of the four steps close on something that exists outside the
# conversation — an approved plan, a pull request's number, a merged PR — and
# `code` closes on a human saying so. "The code is ready" is a judgement; a
# green test run is the evidence, and this is where it comes from.
#
# The same run is repeated after each deploy, where it answers a different
# question. Locally it asks whether the code is right; on preview and on
# production it asks whether the environment is — the build that was deployed,
# the database it reached, the keys it was given.
#
# No tokens are spent here. This is bash, npm and npx; Claude appears only when
# something fails, and the prompt for that is prompts/_regression-fail.md.

# Which stage runs what.
#
# The parts are named rather than listed as commands so the summary can print a
# short label next to a duration, and so a failure can say which part failed
# without quoting a command line back at the human.
#
# The suite is not given a list of specs per stage, and that is deliberate: the
# project's own playwright.config.ts drops specs/account and specs/reading
# wherever accounts may not be created (testIgnore on target.canWrite). Naming
# them here would restate a rule that already exists in the one place that can
# enforce it, and the two copies would drift the first time a group is added.
#
# What the stages really differ by is one variable. E2E_BASE_URL absent means
# the dev server on this machine; set, it names a deployed host, and the suite
# works out the rest — which database the credentials reach, and whether it may
# write there.
#
# A second variable differs by person rather than by stage: SCLAUDE_DEV, the
# name from developer.sh. Two people running the suite against one shared
# database — `dev`, or the preview stage, which always does — each create and
# sweep test accounts there, and a sweep that cannot tell whose accounts are
# whose deletes the other person's in the middle of their run. The project
# decides what to do with the name; sclaude only makes sure every part sees it.
#
# Which parts each stage runs is the project's answer rather than ours, and it
# lives in `.sclaude/config.json` (project.sh). It used to be two strings here, and
# they were this one product's: a second repository would have needed the
# orchestrator edited rather than a file of its own. A project that describes no
# regression simply has none, and the gate says so instead of running a table
# that belongs to somebody else.

# How many fixing attempts one stage gets before the feature is handed back to
# the human. Two, because a test that does not come right in two goes usually
# means the wrong thing is being repaired — and because an unbounded loop
# spends sessions all night on a spec nobody is watching.
REGRESSION_MAX_ATTEMPTS="2"

# The command behind a named part, from the project's own config.
#
# The parts are named rather than listed as commands for the reason above — a
# summary prints `lint` beside a duration, not a command line — and the mapping
# from a name to a command is the project's to declare. `.sclaude/config.json` holds
# it under `commands`.
#
# `e2e` is the odd one: it takes the address. A deployed stage gives the
# project's own command E2E_BASE_URL rather than having a second command
# declared for it, because the two would drift and the difference between them
# is exactly one variable.
#
# A part with no command is a failure rather than a skip: regression_run stops
# loudly on it. A stage that lists a part the project does not describe is a
# config that disagrees with itself, and running the rest while quietly
# dropping one check is how a suite reports green on work it never did.
#
# Both variables are exported rather than prefixed: a project's command may be
# a chain (`npm run build:e2e && playwright test`), and `VAR=x a && b` gives the
# variable to `a` alone — for the address that meant the suite in the second
# half ran against localhost and reported a deployment green without looking at
# it. The export lives in the subshell the part runs in, and it is written into
# the command so the log's `$ …` line reproduces the run.
regression_command() {
  local part="$1" base="${2:-}" wt="${3:-}" stage="${4:-}" cmd dev
  cmd="$(project_command "$part" "$wt")" || return 1
  [[ -n "$cmd" ]] || return 1
  if [[ "$part" == "e2e" && -n "$base" ]]; then
    cmd="export E2E_BASE_URL=$base; $cmd"
  fi
  dev="$(developer_name 2>/dev/null || true)"
  if [[ -n "$dev" ]]; then
    cmd="export SCLAUDE_DEV=$dev; $cmd"
  fi
  # The local stage runs against this feature's own database when it has one
  # (featuredb.sh). Sourced rather than exported by name, so the `$ …` line in
  # the log names the file a person can read, not a row of values.
  if [[ -z "$base" && -n "$wt" && -f "$wt/.sclaude/local/feature/db.env" ]]; then
    cmd="set -a; . $(printf '%q' "$wt/.sclaude/local/feature/db.env"); set +a; $cmd"
  fi
  # The preview stage runs against the credentials the deployment itself reads.
  # A feature on the local stack has .env.local pointing at localdb — for its
  # dev server's sake — and a suite seeding that database while it looks at a
  # deployed preview checks nothing: the project's fixtures refuse to start on
  # that combination. Switching .env.local would pull the dev server off its
  # stack, so the preview file is sourced instead, the way db.env is above; a
  # project's dotenv loading lets an already-set variable win. Only preview:
  # production is read-only by its host, and its credentials are never loaded.
  if [[ "$part" == "e2e" && "$stage" == "preview" && -n "$wt" && -f "$wt/.env.preview" ]]; then
    cmd="set -a; . $(printf '%q' "$wt/.env.preview"); set +a; $cmd"
  fi
  # And against this feature's own dev server. E2E_LOCAL_URL is where the
  # suite looks for it — localhost:3000 is the proxy's list of features now —
  # and PORT with SCLAUDE_DEV_URL are what a suite that starts the server
  # itself (Playwright's webServer, when the server is down) must start it
  # with, or it would come up on another port than the one it is looked for
  # at. SCLAUDE_FEATURE lets a suite on a shared database keep its test data
  # apart from the same developer's other features.
  if [[ -z "$base" && -n "$wt" && -f "$wt/.sclaude/local/feature/state.json" ]]; then
    local port url label
    if port="$(feature_port "$wt")" && url="$(dev_address "$wt")"; then
      label="$(state_get "$wt/.sclaude/local/feature/state.json" dev.label 2>/dev/null || true)"
      cmd="export E2E_LOCAL_URL=$url PORT=$port SCLAUDE_DEV_URL=$url${label:+ SCLAUDE_FEATURE=$label}; $cmd"
    fi
  fi
  printf '%s' "$cmd"
}

# Which parts a stage runs.
#
# Only the local stage builds and checks the database and the bucket: a
# project's database checks refuse a protected environment outright, both
# create and delete real rows, and a build of a deployed
# commit has already happened on Vercel's side. What is left to ask a deployed
# host is what a browser sees.
#
# `migrations` and `schema` are in the local list although .githooks/pre-push
# runs both: `--no-verify` skips the hook entirely, and they cost seconds. Both
# fail open by construction — no CLI, no credentials, no network and they pass —
# so "this machine cannot answer" never turns into a red regression.
#
# What is deliberately NOT repeated here is the rest of checks.yml — check:bio,
# check:links, check:migrations:style. Those run on every pull request from the
# repository alone, and a second copy in the regression would cost minutes
# without answering anything new. typecheck, lint and build stay because they
# catch before the pull request exists, which is the whole point of a gate on
# step 2, and because this repository is private: Actions minutes come out of a
# monthly quota.
regression_parts() {
  local stage="$1" wt="${2:-}"
  case "$stage" in
    local|preview|prod) ;;
    # `rollback` is the confirmation run that follows a rollback: the same suite
    # against the same production host, asking a different question — whether
    # the release we went back to is serving properly. It is a stage of its own
    # rather than a second `prod` run so that its result cannot be mistaken for
    # the feature's: regression_status "$wt" prod goes on answering about the
    # feature, regression_gate's `passed` short-circuit cannot be tripped by it,
    # regression_red_label mints nothing for it, and regression_clear_mark and
    # regression_rewind leave it alone. Those four are guarded by tests, because
    # widening any of them would quietly turn a rollback's green into the
    # feature's.
    #
    # It borrows prod's list: the host is the same and so is the question's
    # shape, and a project declaring the two separately would be declaring the
    # same thing twice.
    rollback) stage="prod" ;;
    *) return 1 ;;
  esac
  project_regression_parts "$stage" "$wt"
}

# The parts worth running when nothing but the manuals changed since the tree
# last passed locally, or nothing when the whole suite is owed.
#
# The manuals are written in step 3, after step 2's green run, so every feature
# whose pull request touched them paid for a second full regression at the end
# of the review — four and a half minutes, nearly all of it e2e, for a page of
# prose. Skipping it outright would not do: a manual is TSX, and a typo in it
# breaks the build on its way to the preview deploy. So the checks that read
# the code run, and the suite that clicks through the product does not — no
# spec visits the manuals.
#
# The subset is the project's `regression.manual`, and there is no default: the
# names of a project's checks are its own, and a guess here would be one
# product's answer applied to another's repository. Absent or empty, the full
# suite runs, as it always did.
#
# Only a change that stands on top of the tested tree counts: `was` must be an
# ancestor of `now`, or the diff between them says nothing about what was run.
# And every changed path must be a declared manual — a regression test added in
# step 3 is not one, and it is exactly what the full suite is for. Renames are
# listed as their two paths: detected, a code file moved onto a manual's path
# would show only the manual, and the page it used to be would go untested.
regression_manual_parts() {
  local wt="$1" was="$2" now="$3" file changed parts
  [[ -n "$was" && "$was" != "null" && -n "$now" ]] || return 1
  git -C "$wt" merge-base --is-ancestor "$was" "$now" 2>/dev/null || return 1
  changed="$(git -C "$wt" diff --name-only --no-renames "$was" "$now" 2>/dev/null)" || return 1
  [[ -n "$changed" ]] || return 1
  # Through project_get, key by key as the parts below are read: a feature
  # adding `manuals` has them before the main checkout does.
  file="$(project_get manuals "$wt")" || return 1
  python3 - "$file" "$changed" <<'PY' 2>/dev/null || return 1
import json, sys
manuals = []
for line in sys.argv[1].splitlines():
    try:
        manuals.append(json.loads(line))
    except ValueError:
        pass
paths = {m.get("path") for m in manuals if isinstance(m, dict)}
changed = [line for line in sys.argv[2].splitlines() if line]
sys.exit(0 if paths and all(c in paths for c in changed) else 1)
PY
  parts="$(project_regression_parts manual "$wt")"
  [[ -n "$parts" ]] || return 1
  printf '%s' "$parts"
}

# Where a stage points the suite. Empty for local — the absence of the variable
# is what names localhost, and an empty string would not be the same thing.
#
# Production's address is the project's to declare, in `.sclaude/config.json`. It was
# read out of the product's own file of environments before, with the
# address itself as a literal fallback — which meant a repository that kept the
# answer anywhere else had its suite aimed at somebody else's production. Being
# wrong about which host is production means running a write-capable suite
# against it, so there is no fallback: unknown is reported as unknown.
regression_base_url() {
  local wt="$1" stage="$2"
  case "$stage" in
    local)   printf '' ;;
    preview) state_get "$wt/.sclaude/local/feature/state.json" regression.preview.url 2>/dev/null || true ;;
    prod|rollback)
      # From the project's own config. It used to be read out of this one
      # product's file of environments, with its address as a literal
      # fallback — so a second repository would have had its suite aimed at
      # somebody else's production. There is no fallback now: an unknown
      # address means the stage cannot run, which regression_run reports as
      # "could not run" rather than as a failure, and that is the honest answer.
      project_prod_url "$wt"
      ;;
  esac
}

# Production deployments that went live while a stage was running, one per line
# as "<url>\t<ready ms>". Exit 0 when there was at least one.
#
# Only production can be intruded on. The preview stage runs against the one
# immutable URL of this branch's own deployment, and nobody else's deploy
# changes what that URL serves. Production's address is an alias, and a
# colleague's `vercel --prod` in the middle of the run moves it: the suite then
# checks half one release and half another, and a red verdict may not be this
# feature's at all.
#
# That matters more here than anywhere, because a red production run is
# answered with an automatic rollback to the release before this feature — and
# with somebody else's release on top, that rollback would take theirs away as
# well. deploy.sh asks this before rolling anything back.
#
# Went live, not was created: a production deployment takes the alias when its
# build finishes, minutes after `vercel --prod` was typed. One created just
# before the run and ready in the middle of it is exactly the case this is
# for, and createdAt would miss it. And only READY ones: a build that failed or
# was cancelled never served anything, and counting it would keep a broken
# production from its rollback for no reason.
#
# The window is (started, finished]: this feature's own deployment was ready
# before its run started and is not an intrusion. What this cannot see is an
# alias moved without a new deployment (`vercel rollback`, `vercel promote`);
# those leave no ready time in the window. Unknown — no vercel, no times —
# answers no, the same as everywhere a listing is silent.
regression_deploy_intruded() {
  local stage="$1" started="$2" finished="$3"
  [[ "$stage" == "prod" && -n "$started" && -n "$finished" ]] || return 1
  vercel_prod_deployments 2>/dev/null \
    | STARTED="$started" FINISHED="$finished" python3 -c '
import datetime, os, sys
def ms(iso):
    return int(datetime.datetime.fromisoformat(iso).timestamp() * 1000)
try:
    lo, hi = ms(os.environ["STARTED"]), ms(os.environ["FINISHED"])
except ValueError:
    sys.exit(1)
found = False
for line in sys.stdin:
    parts = line.rstrip("\n").split("\t")
    if len(parts) < 5 or parts[2] != "READY" or not parts[4].isdigit():
        continue
    if lo < int(parts[4]) <= hi:
        print("%s\t%s" % (parts[0], parts[4]))
        found = True
sys.exit(0 if found else 1)
' 2>/dev/null
}

# passed | failed | none — what the state remembers about a stage.
#
# `none` covers every way of not knowing: no state file, no run yet, a run that
# was killed before it could write its verdict. The gate treats all of those
# the same way, which is to run again.
regression_status() {
  local wt="$1" stage="$2" status
  status="$(state_get "$wt/.sclaude/local/feature/state.json" "regression.$stage.status" 2>/dev/null || true)"
  case "$status" in
    passed|failed) printf '%s' "$status" ;;
    *)             printf 'none' ;;
  esac
}

# Where the timings are kept, and why there.
#
# In the project rather than in the worktree: a worktree dies with the feature,
# and the whole value of these numbers is that the *next* feature starts with
# them. In the main repository's .git/sclaude/, next to the question channel,
# because nothing there is ever committed and nothing else writes to it.
#
# They used to live in tests/artifacts/, and were never there when wanted: that
# is Playwright's outputDir, which it empties at the start of every run. Every
# e2e — the regression's own, and each one a fixing session starts — deleted
# the file, so the next regression began with no estimates at all.
regression_timings_file() {
  local wt="$1" common
  common="$(git -C "${REPO:-$wt}" rev-parse --path-format=absolute \
    --git-common-dir 2>/dev/null)" || return 1
  [[ -n "$common" && -d "$common" ]] || return 1
  mkdir -p "$common/sclaude" 2>/dev/null || return 1
  echo "$common/sclaude/regression-timings.json"
}

# How many successful runs of a part the estimate is drawn from.
REGRESSION_TIMINGS_KEPT=5

# The expected seconds for one part of one stage, or nothing when it has never
# been timed. Silent on every kind of trouble: a missing file, bad JSON, a part
# that is new — an estimate is a courtesy, and a courtesy must not be able to
# stop a run.
#
# The median of the last few successful runs, not the last one alone. One cold
# build or one e2e that waited on a slow container would otherwise set the
# expectation for the whole next run; the median ignores a single outlier
# either way, where a mean is dragged by it. A bare number is the older format,
# one run long, and still reads.
regression_expected() {
  local wt="$1" stage="$2" part="$3" file
  file="$(regression_timings_file "$wt")" || return 1
  python3 - "$file" "$stage" "$part" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    sys.exit(1)
value = ((data.get(sys.argv[2]) or {}).get(sys.argv[3]))
runs = value if isinstance(value, list) else [value]
runs = sorted(v for v in runs if isinstance(v, (int, float)) and v > 0)
if not runs:
    sys.exit(1)
mid = len(runs) // 2
median = runs[mid] if len(runs) % 2 else (runs[mid - 1] + runs[mid]) / 2
print(int(round(median)))
PY
}

# Records what a part actually took, for the next runs to quote.
#
# Only successful parts: a part that failed usually failed fast — a typecheck
# error lands in seconds — and writing that down would tell the next run to
# expect three seconds for something that takes fifty.
regression_remember() {
  local wt="$1" stage="$2" part="$3" seconds="$4" file
  file="$(regression_timings_file "$wt")" || return 0
  python3 - "$file" "$stage" "$part" "$seconds" "$REGRESSION_TIMINGS_KEPT" <<'PY' 2>/dev/null || true
import json, os, sys
path, stage, part, seconds, kept = sys.argv[1:6]
try:
    with open(path) as fh:
        data = json.load(fh)
except (OSError, ValueError):
    data = {}
if not isinstance(data, dict):
    data = {}
runs = data.setdefault(stage, {}).get(part)
runs = runs if isinstance(runs, list) else ([runs] if isinstance(runs, int) else [])
runs.append(int(seconds))
data[stage][part] = runs[-int(kept):]
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(data, fh, indent=2, sort_keys=True)
    fh.write("\n")
os.replace(tmp, path)
PY
}

# The one-minute load average, or nothing where /proc has none.
regression_load() {
  local one _
  read -r one _ < /proc/loadavg 2>/dev/null || return 0
  printf '%s' "$one"
}

# The whole stage's expected seconds, summed from its parts. Empty when no part
# has a figure yet — the first run of a feature on a fresh machine says nothing
# rather than inventing a total out of the two parts it happens to know.
#
# `parts` is the list actually being run, when that is not the stage's own.
regression_expected_total() {
  local wt="$1" stage="$2" parts="${3:-}" part total=0 one known=0
  [[ -n "$parts" ]] || parts="$(regression_parts "$stage" "$wt" 2>/dev/null || true)"
  for part in $parts; do
    one="$(regression_expected "$wt" "$stage" "$part" || true)"
    [[ -n "$one" ]] || continue
    total=$((total + one))
    known=1
  done
  [[ "$known" -eq 1 ]] && printf '%s' "$total"
}

# Seconds as a human reads them. 56s, 4m 30s — never 270s, which has to be
# divided in the head at exactly the moment somebody is waiting.
regression_duration() {
  local total="$1"
  if [[ "$total" -lt 60 ]]; then
    printf '%ds' "$total"
  else
    printf '%dm %02ds' "$((total / 60))" "$((total % 60))"
  fi
}

# The specs that failed, from the log of the part's last attempt, for the line
# that says the run is red: "failed on e2e" alone names a ten-minute suite, and
# the title a spec was given is what tells a reader what broke.
#
# From the summary Playwright ends a run with, whichever reporter wrote the
# rest: it lists each spec that failed in the end, once, without its time, and
# keeps the flaky ones — failed, then passed on a retry — in a block of their
# own, which is not read:
#
#     2 failed
#       [chromium] › e2e/login.spec.ts:14:5 › Login › signs in ──────────
#       [chromium] › e2e/cart.spec.ts:8:3 › adds an item ────────────────
#     1 flaky
#
# A run cut off before its summary falls back to the `list` reporter's lines,
# "✘  12 [chromium] › e2e/login.spec.ts:14:5 › Login › signs in (3.2s)", minus
# those of a spec that passed on a retry after them. Either reads as
# "Login › signs in (login.spec.ts:14)": the first three, and how many more;
# nothing for a part whose log has neither.
#
#   regression_failed_specs <log> <first line of the attempt>
regression_failed_specs() {
  python3 - "$1" "${2:-1}" <<'PY' 2>/dev/null || true
import re, sys

path, start = sys.argv[1], int(sys.argv[2])
try:
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()[start - 1:]
except OSError:
    sys.exit(0)
lines = [re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line) for line in lines]

# "[project] › path:line:col › title", the project optional, the path ending
# at the first " › " so that a space inside it is the path's.
SPEC = re.compile(r"^(?:\[[^\]]*\] › )?(?:.*/)?([^/]+?):(\d+)(?::\d+)? › (.+)$")


def named(text):
    m = SPEC.match(text.strip())
    return "%s (%s:%s)" % (m.group(3), m.group(1), m.group(2)) if m else text.strip()


names = []
summary = None
for i, line in enumerate(lines):
    if re.match(r"^\s+\d+ failed\s*$", line):
        summary = i
if summary is not None:
    for line in lines[summary + 1:]:
        if not re.match(r"^\s{4,}\S", line):
            break
        names.append(named(re.sub(r"\s*─+\s*$", "", line)))
else:
    MARK = re.compile(r"^\s+([✓✘])\s+\d+\s+(.*?)(?:\s+\(retry #\d+\))?(?:\s+\([\d.]+(?:ms|s|m|h)\))?\s*$")
    last = {}
    for line in lines:
        m = MARK.match(line)
        if m:
            spec = named(m.group(2))
            last.pop(spec, None)
            last[spec] = m.group(1)
    names = [spec for spec, mark in last.items() if mark == "✘"]

seen = []
for name in names:
    if name not in seen:
        seen.append(name)
if seen:
    more = " (+%d more)" % (len(seen) - 3) if len(seen) > 3 else ""
    print("; ".join(seen[:3]) + more)
PY
}

# Rewrites one part's line in the list printed at the start of a run.
#
# The list stands above the cursor: the part being marked is as many lines up
# as there are parts after it, plus one. So the cursor climbs, clears, writes,
# and comes back down — which is the only way to show "this one is running now"
# without either reprinting the whole table or leaving the terminal silent.
#
# Without a terminal none of that is possible or wanted: escape codes in a
# piped log are rubbish, so the line is printed plainly and the list above it
# simply stays as it was.
#
# `say` is deliberately not used for the in-progress line: it also files the
# text into ASK_CONTEXT for the next question, and a line that is about to be
# overwritten has no business in the context a human is shown.
regression_line() {
  local stage="$1" parts="$2" part="$3" what="$4" seconds="$5" wt="${6:-}" tail="${7:-}"
  local text expected after=0 seen=0 p

  for p in $parts; do
    [[ "$seen" -eq 1 ]] && after=$((after + 1))
    [[ "$p" == "$part" ]] && seen=1
  done

  expected="$(regression_expected "$wt" "$stage" "$part" || true)"
  case "$what" in
    started)
      text="  ${BOLD}$part${OFF}${expected:+ ${DIM}(expected $(regression_duration "$expected"))${OFF}} → ${BLUE}Started${OFF}${tail:+ ${DIM}$tail${OFF}}"
      ;;
    done)
      text="  $part${expected:+ ${DIM}(expected $(regression_duration "$expected"))${OFF}} → ${GREEN}✓ Done${OFF} ${DIM}(took $(regression_duration "$seconds"))${OFF}"
      ;;
    failed)
      text="  $part${expected:+ ${DIM}(expected $(regression_duration "$expected"))${OFF}} → ${RED}✗ Failed${OFF} ${DIM}(after $(regression_duration "$seconds"))${OFF}"
      ;;
  esac

  if [[ -t 1 ]]; then
    # Up past the parts below this one, clear, write, and back down.
    printf '\033[%dA\033[2K%s\n' "$((after + 1))" "$text"
    [[ "$after" -gt 0 ]] && printf '\033[%dB' "$after"
  else
    printf '%s\n' "$text"
  fi
  # The finished line is what a question shown in a messenger should carry —
  # the one that is still running is not.
  [[ "$what" != "started" ]] && ask_note "$text"
  return 0
}

# Whether a deployed stage failed because the deployment is not serving.
#
# Two things have to hold, and neither alone is enough. The suite must have
# failed *entirely* — Playwright prints "Running N tests" and "N failed", and
# those two numbers matching is what "everything" means; a genuine regression
# nearly always leaves something passing. And the address must answer with a
# server error or not answer at all, which is the part that says the fault is
# the deployment's rather than the branch's.
#
# Silent and false on anything unclear: no curl, no numbers in the log, a shape
# that does not parse. Calling a real failure "the environment" would send a
# red regression past the gate, which is worse than the session this saves.
regression_environment_broken() {
  local log="$1" base="$2" ran failed code

  command -v curl >/dev/null 2>&1 || return 1

  ran="$(grep -oE 'Running ([0-9]+) tests' "$log" 2>/dev/null | grep -oE '[0-9]+' | head -1)"
  failed="$(grep -oE '^ *([0-9]+) failed' "$log" 2>/dev/null | grep -oE '[0-9]+' | head -1)"
  [[ "$ran" =~ ^[0-9]+$ && "$failed" =~ ^[0-9]+$ ]] || return 1
  [[ "$ran" -gt 0 && "$ran" -eq "$failed" ]] || return 1

  # 000 is curl's own "no answer at all" — a host that does not resolve or
  # refuses the connection is as broken as one returning 500.
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$base/" 2>/dev/null || echo 000)"
  [[ "$code" == "000" || "$code" =~ ^5 ]]
}

# Whether a local e2e failed because the dev server stopped finishing pages.
#
# On 2026-10-09 a feature's local e2e failed on two specs that open `/`: nine
# /_next/image requests hung inside `next dev`, `load` never fired, and both
# timed out in page.goto. The server had been restarted right before the run —
# regression_run does that — and wedged during it. The fixing session spent a
# quarter of an hour finding that, restarted the server, and the whole suite
# passed with no change to the code.
#
# So the signature is narrow on purpose: every failure is page.goto running out
# of time, and nothing else failed. A failed assertion, a mix of the two, or a
# suite run with retries (each retry prints its own error, so the counts stop
# matching) is the branch's business, and the fixing session gets it as before.
#
# Only the last `=== e2e ===` section is read: the log holds every part of the
# run, and an earlier attempt must not answer for this one.
regression_server_wedged() {
  local log="$1" section failed errors gotos
  section="$(awk '/^=== e2e/ { buf = "" } { buf = buf $0 "\n" } END { printf "%s", buf }' \
    "$log" 2>/dev/null)" || return 1
  failed="$(grep -oE '^ *[0-9]+ failed' <<< "$section" | grep -oE '[0-9]+' | head -1)"
  [[ "$failed" =~ ^[0-9]+$ && "$failed" -gt 0 ]] || return 1
  errors="$(grep -cE '^ *Error: ' <<< "$section")"
  gotos="$(grep -cE '^ *Error: page\.goto: (Test timeout|Timeout) ' <<< "$section")"
  [[ "$errors" -eq "$failed" && "$gotos" -eq "$failed" ]]
}

# One run of one stage. Returns 0 when every part passed.
#
# The log is .sclaude/local/feature/regression.log, beside dev.log and friction.log, and it is
# truncated at the start of each run: what matters is why this run failed, and
# the previous run's output under the same headings is what makes a log unusable
# in a hurry. The worktree outlives production now — remind_prod cleans up last
# — so this file is still there when a prod failure has to be read.
#
# The phase within a run is not remembered anywhere. A killed run starts again
# from the first part: the parts are minutes each, and resuming into the middle
# of a suite whose earlier half may no longer hold is a guess about state that
# cannot be checked.
#
# `only` replaces the stage's list for this one run — regression_gate passes
# the project's `regression.manual` when nothing but the manuals changed.
#
# One run on the machine at a time, whichever feature it belongs to: see
# lock.sh. On 2026-10-06 one feature's local e2e timed out while another's work loaded the
# machine beside it, and a fixing session went on proving the code innocent.
#
# The dev server is restarted inside the queue, right before the parts: a
# restart is a compile, and another feature's suite running meanwhile is what
# the queue is for.
#
# Only the runs that load the machine wait: a full local run and a preview's
# e2e. A run of `only` is a few seconds of reading the code; production and
# the check after a rollback are about a live site, and must not stand behind
# another feature's ten-minute suite; and a stage with nothing to run has
# nothing to queue for.
regression_run() {
  local wt="$1" slug="$2" stage="$3" only="${4:-}" rc lock_pid=""
  local lock_file="${DEV_REGISTRY:-}/.regression.lock"

  if [[ -n "${DEV_REGISTRY:-}" && -z "$only" ]] && declare -F lock_take >/dev/null \
     && [[ "$stage" == "local" || "$stage" == "preview" ]] \
     && [[ -n "$(regression_parts "$stage" "$wt" 2>/dev/null)" ]]; then
    lock_take lock_pid "$lock_file" "$slug, the $stage regression" "a regression"
  fi

  # The local stage checks this feature's own server and database, and either
  # may have been stopped for idling while the session worked (sclaude-proxy).
  # Brought up here rather than left to the suite: Playwright's webServer would
  # race the proxy's own start for the same port, and nothing would bring the
  # database back for check:rls at all. A no-op when both are already up.
  #
  # Not for a run of `only`: those are the checks that read the code, and
  # waiting for a server and a database nobody will ask would spend part of
  # the time the shorter run exists to save.
  #
  # And restarted first, not merely found running. A server that has been up
  # through hours of step work is not the one the suite should judge the code
  # by: one `next dev` had wedged its /_next/image optimiser for a single width,
  # every request for those images hung, `load` never fired, and two landing
  # specs timed out on code nothing was wrong with. A whole fixing session went
  # on finding that and restarting the server by hand — without dev_env_load,
  # which this also replaces. A restart costs under a second, and the suite
  # compiles its pages on first hit either way.
  #
  # A restart before the run does not cover a server that wedges during it —
  # one did, on 2026-10-09, minutes after this one. That case is
  # regression_server_wedged's, and regression_run_body retries e2e on it.
  if [[ "$stage" == "local" && -z "$only" ]] && declare -F ensure_dev >/dev/null; then
    declare -F stop_own_dev >/dev/null && stop_own_dev "$wt" \
      && info "  dev server: stopped, so the suite meets a fresh one"
    ensure_dev "$wt"
  fi

  regression_run_body "$wt" "$slug" "$stage" "$only"
  rc=$?
  declare -F lock_release >/dev/null && lock_release "$lock_pid" "$lock_file"
  return "$rc"
}

# The run itself, inside the queue regression_run holds.
regression_run_body() {
  local wt="$1" slug="$2" stage="$3" only="${4:-}"
  local state="$wt/.sclaude/local/feature/state.json"
  local log="$wt/.sclaude/local/feature/regression.log"
  local base parts part cmd failed="" failed_specs="" passed=0
  local started part_started part_total rc retried from
  # The tree under test, taken before the run rather than after it: a change
  # made while the suite ran was not tested, and must not be called green.
  local tree; tree="$(regression_tree "$wt")"

  parts="$(regression_parts "$stage" "$wt")" || { warn "  unknown regression stage: $stage"; return 1; }
  if [[ -n "$only" ]]; then parts="$only"; fi
  base="$(regression_base_url "$wt" "$stage")"

  # A project that describes no regression for this stage has none, and that is
  # a fact about the project rather than a failure of the branch. 2 is the code
  # for "could not run": the gate spends no fixing session on it, because there
  # is nothing for a session to repair — no amount of editing the code conjures
  # a suite nobody has declared.
  if [[ -z "$parts" ]]; then
    echo ""
    info "  No $stage regression: .sclaude/config.json describes none for this project."
    [[ -f "${REPO:-$wt}/.sclaude/config.json" ]] \
      || info "  There is no .sclaude/config.json at all — \`$SELF new\` offers to write one."
    return 2
  fi

  # A deployed stage with no address is not a failed regression — it is a
  # regression that cannot be run at all, and saying "failed" would send a
  # session off to fix the tests. Preview writes its address in remind_prod; if
  # it is missing, the deploy is what did not happen.
  if [[ "$stage" != "local" && -z "$base" ]]; then
    warn "  no address for the $stage regression — skipping it."
    [[ "$stage" == "preview" ]] && info "  It is written by the preview deploy; deploy first."
    # 2, not 1: "could not run" is not "ran and failed". The gate tells them
    # apart because only the second is worth a fixing session — a missing
    # address means the deploy did not happen, and no amount of editing the
    # code will conjure one. Returning 1 here sent Claude off to repair a
    # deployment that was never made.
    return 2
  fi

  # The plan, before anything runs.
  #
  # A regression takes minutes, and until now it said so only in hindsight: a
  # line appeared once a part had finished, so the terminal sat silent through
  # the longest one and looked hung. The preview stage made that plain — its
  # single e2e part ran ten minutes with nothing on screen.
  #
  # So the whole list is printed up front with what each part is expected to
  # take, the current one is marked as it starts, and its line is rewritten
  # when it ends. Timings are the median of this project's last successful runs.
  # The dev server was restarted by regression_run, before the queue.
  local total_expected; total_expected="$(regression_expected_total "$wt" "$stage" "$only" || true)"
  echo ""
  echo "${BOLD}${BLUE}── $(phase_title regression "$stage")${total_expected:+ (expected $(regression_duration "$total_expected"))} ──${OFF}"
  [[ -n "$base" ]] && info "   $base"

  local one
  for part in $parts; do
    one="$(regression_expected "$wt" "$stage" "$part" || true)"
    printf '  %s%s\n' "$part" \
      "${one:+ ${DIM}(expected $(regression_duration "$one"))${OFF}}"
  done

  : > "$log"
  state_set "$state" "regression.$stage.status" running
  state_set "$state" "regression.$stage.started" "$(date -Iseconds)"
  state_set "$state" "regression.$stage.failed_at" null
  # And the previous run's finishing time, or the state reads as a run that
  # ended before it began: started 13:56, finished 09:21.
  state_set "$state" "regression.$stage.finished" null
  # The blocked note is deliberately NOT cleared here, though an earlier version
  # of this did exactly that. It is addressed to the human, and clearing it at
  # the head of the run meant the gate destroyed the message on its way to
  # re-deriving it: four minutes of suite, a fixing session, the same paragraph
  # written again. It is cleared where it is answered — by the gate, once the
  # human says the cause has been dealt with.

  regression_notify_start "$slug" "$stage" "$base" "$(wc -w <<< "$parts")" "$total_expected"

  started="$(date +%s)"
  for part in $parts; do
    # A part in the table with no command arm is a typo, and skipping it
    # silently is the worst of the answers: the run reports green having
    # quietly not made one of its checks. So it stops, loudly — a table and a
    # case statement that disagree is a thing to fix now rather than to
    # discover in a month by noticing the arithmetic never added up.
    if ! cmd="$(regression_command "$part" "$base" "$wt" "$stage")"; then
      warn "  ✗ $part — no command for this part."
      warn "    It is named in the stage's list but has no arm in"
      warn "    regression_command; the run stops rather than reporting green"
      warn "    on a check it never made."
      state_set "$state" "regression.$stage.status" failed
      state_set "$state" "regression.$stage.failed_at" "$part"
      state_set "$state" "regression.$stage.finished" "$(date -Iseconds)"
      return 1
    fi
    part_started="$(date +%s)"

    # The part's line is rewritten in place: it was printed in the list above,
    # and now it says which one is running. Only with a terminal — under a pipe
    # the escape codes would be rubbish in a file, so there the line is simply
    # printed again.
    #
    # `regression_line` counts how far up this part's line is: the parts after
    # it are still below, so the cursor climbs past them.
    regression_line "$stage" "$parts" "$part" started "" "$wt"

    {
      echo ""
      echo "=== $part ==="
      echo "\$ $cmd"
      echo ""
    } >> "$log"

    # The whole run in the worktree, with the output going to the log and
    # nowhere else: a Playwright run prints hundreds of lines, and the point of
    # the table above is that it does not.
    #
    # In the background, so the line can be kept alive while it runs. The first
    # fix printed the list of parts up front, which answers "how long is this"
    # for the local stage's eight — but a deployed stage has exactly one part,
    # `e2e`, and it is the ten-minute one. One line saying `Started` and then
    # silence is what "looks hung" meant the second time.
    #
    # So the log is watched while the part runs. Playwright's `list` reporter
    # writes a line per finished spec and announces the total up front, so the
    # count is a grep over the growing file — five milliseconds, cheap enough
    # for a tick a second.
    #
    # At most twice, for e2e on the local stage alone: once more on a fresh dev
    # server when every failure was a page that never finished loading — see
    # regression_server_wedged. The second attempt runs the whole command again
    # rather than only the failed specs: a project may declare it as a chain,
    # and a whole green suite is what the fixing session would have proved.
    retried=""
    while :; do
      from=$(( $(wc -l < "$log") + 1 ))
      ( cd "$wt" && eval "$cmd" ) >> "$log" 2>&1 < /dev/null &
      local part_pid=$!
      if [[ -t 1 ]]; then
        local total done_n spin=0 frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        while kill -0 "$part_pid" 2>/dev/null; do
          # `grep -c` prints 0 and exits 1 when nothing matches, so `|| echo 0`
          # appends a second zero and the variable becomes "0\n0". A newline in
          # the tail breaks the rewriting outright: the extra line moves the
          # cursor and every later `\033[NA` climbs to the wrong row.
          #
          # Read from where this attempt began, or a retry counts the first
          # attempt's specs as its own.
          total="$(tail -n +"$from" "$log" 2>/dev/null | grep -oE 'Running ([0-9]+) test' \
            | grep -oE '[0-9]+' | head -1)" || total=""
          done_n="$(tail -n +"$from" "$log" 2>/dev/null \
            | grep -cE '^[[:space:]]+[✓✘][[:space:]]+[0-9]+' | head -1)"
          [[ "$total" =~ ^[0-9]+$ ]] || total=""
          [[ "$done_n" =~ ^[0-9]+$ ]] || done_n=0
          regression_line "$stage" "$parts" "$part" started "" "$wt" \
            "${frames:spin:1} $(regression_duration $(( $(date +%s) - part_started )))${total:+ · $done_n/$total}"
          spin=$(( (spin + 1) % 10 ))
          sleep 1
        done
      fi
      wait "$part_pid"
      rc=$?
      if [[ "$rc" -ne 0 && "$stage" == "local" && "$part" == "e2e" && -z "$retried" ]] \
         && regression_server_wedged "$log" \
         && declare -F ensure_dev >/dev/null; then
        retried=1
        {
          echo "--- e2e: every failure was a page that never loaded; restarting the dev server and running e2e again"
          echo ""
          echo "=== e2e (again, on a fresh dev server) ==="
          echo "\$ $cmd"
          echo ""
        } >> "$log"
        regression_line "$stage" "$parts" "$part" started "" "$wt" \
          "pages stopped loading — restarting the dev server, running again"
        declare -F stop_own_dev >/dev/null && stop_own_dev "$wt" >/dev/null 2>&1
        ensure_dev "$wt" >/dev/null 2>&1
        continue
      fi
      break
    done
    part_total=$(( $(date +%s) - part_started ))
    local load_after; load_after="$(regression_load)"
    echo "--- $part: $(regression_duration "$part_total"), load ${load_after:-?} on $(nproc 2>/dev/null || echo ?) CPUs" >> "$log"

    if [[ "$rc" -eq 0 ]]; then
      passed=$((passed + 1))
      regression_line "$stage" "$parts" "$part" done "$part_total" "$wt"
      # Only a successful part is remembered. A failed one usually failed fast
      # — a typecheck error lands in seconds — and writing that down would tell
      # the next run to expect three seconds for something that takes fifty.
      #
      # Two features' runs no longer overlap (the queue in regression_run), and
      # the load each part leaves in the log says what else the machine was
      # doing; the median of the last runs takes care of a single slow one.
      #
      # Not a retried one either: its time is two runs of the suite.
      [[ -n "$retried" ]] || regression_remember "$wt" "$stage" "$part" "$part_total"
    else
      regression_line "$stage" "$parts" "$part" failed "$part_total" "$wt"
      failed="$part"
      failed_specs="$(regression_failed_specs "$log" "$from")"
      # We stop at the first failure. The parts are ordered cheapest first, and
      # a failing typecheck makes everything after it noise — the session that
      # comes next has one thing to fix, not a page of consequences.
      break
    fi
  done

  local elapsed; elapsed=$(( $(date +%s) - started ))
  local count; count="$(wc -w <<< "$parts")"

  # "Everything failed" on a deployed stage is a statement about the deployment,
  # not about the code.
  #
  # This happened on the first real run: preview answered 500 to every request
  # because the project's Supabase variables were never set for that
  # environment, and all twenty specs timed out. The gate called it a red
  # regression and opened a session to repair the tests — which could not have
  # helped, since nothing was wrong with them.
  #
  # So: a deployed stage whose whole suite failed, against an address that is
  # not serving, is reported as "could not run" rather than "ran and failed".
  # Return 2 is the same answer a missing address gives, and the gate already
  # knows not to spend a fixing session on it.
  if [[ -n "$failed" && "$stage" != "local" && -n "$base" ]] \
     && regression_environment_broken "$log" "$base"; then
    state_set "$state" "regression.$stage.status" failed
    state_set "$state" "regression.$stage.failed_at" "$failed"
    state_set "$state" "regression.$stage.finished" "$(date -Iseconds)"
    echo ""
    # Said to the phone by regression_notify_done, in a line of its own.
    warn_here "  Every spec failed and $base is not serving."
    warn_here "  That is the environment, not the code — no fixing session will help."
    info "     log: .sclaude/local/feature/regression.log"
    regression_notify_done "$slug" "$stage" "$failed" "$passed" "$count" "$elapsed" "" "$base"
    return 2
  fi

  echo ""
  if [[ -n "$failed" ]]; then
    state_set "$state" "regression.$stage.status" failed
    state_set "$state" "regression.$stage.failed_at" "$failed"
    state_set "$state" "regression.$stage.finished" "$(date -Iseconds)"
    # The terminal's line; the topic hears it from regression_notify_done,
    # once, with a sound — through the feed too it came twice.
    warn_here "  ── $passed/$count, $(regression_duration "$elapsed") · failed on $failed${failed_specs:+: $failed_specs}"
    info "     log: .sclaude/local/feature/regression.log"
    regression_notify_done "$slug" "$stage" "$failed" "$passed" "$count" "$elapsed" "$failed_specs" "" "$log"
    return 1
  fi

  state_set "$state" "regression.$stage.status" passed
  state_set "$state" "regression.$stage.failed_at" null
  state_set "$state" "regression.$stage.tree" "${tree:-null}"
  state_set "$state" "regression.$stage.finished" "$(date -Iseconds)"
  echo "  ${GREEN}── $passed/$count, $(regression_duration "$elapsed") — green.${OFF}"
  regression_notify_done "$slug" "$stage" "" "$passed" "$count" "$elapsed"
  return 0
}

# The two messages a run sends, one line each in the shape every session's
# start and end take (phase_line): the start quiet, the end quiet when green
# and with a sound when red. Silent by construction when there are no
# credentials — sclaude-notify exits zero without them — so nothing here has to
# ask whether Telegram is set up. They are the topic's one account of the run:
# the terminal's own lines about it stay there.
#
#   regression_notify_start <slug> <stage> <base> <parts> [<expected seconds>]
#   regression_notify_done <slug> <stage> <failed part> <passed> <count> <seconds> [<specs> [<base> [<log>]]]
#
# The failed part empty is green; a base given is a stage that could not run,
# its address not serving. A red part that names no specs — a typecheck, a
# build — brings the last lines of its log instead, the one thing that says
# whether it needs looking at now.
regression_notify_start() {
  local slug="$1" stage="$2" base="$3" parts="$4" expected="${5:-}"
  notify_feature "$slug" --quiet \
    "$(phase_line started regression "$stage")${base:+ ($base)} · $parts $([[ "$parts" == 1 ]] && echo part || echo parts)${expected:+, expected $(regression_duration "$expected")}" \
    2>/dev/null || true
}

regression_notify_done() {
  local slug="$1" stage="$2" failed="$3" passed="$4" count="$5" elapsed="$6" specs="${7:-}" base="${8:-}" log="${9:-}"
  local took; took="$passed/$count, $(regression_duration "$elapsed")"
  if [[ -n "$base" ]]; then
    notify_feature "$slug" \
      "$(phase_line "could not run" regression "$stage") · every spec failed and $base is not serving — the environment, not the code" \
      2>/dev/null || true
  elif [[ -n "$failed" ]]; then
    local tail=""
    [[ -z "$specs" && -n "$log" ]] && tail="$(grep -v '^[[:space:]]*$' "$log" 2>/dev/null | tail -5)"
    notify_feature "$slug" "$(phase_line failed regression "$stage"), on $failed${specs:+: $specs} · $took${tail:+
$tail}" 2>/dev/null || true
  else
    notify_feature "$slug" --quiet "$(phase_line finished regression "$stage"), green · $took" \
      2>/dev/null || true
  fi
}

# The gate: run the stage, and if it is red, fix it and run it again.
#
# The shape is run_friction's, deliberately: a caller writes
#
#   if ! regression_gate "$wt" "$slug" local; then … return 0; fi
#
# and the step stays where it is. A gate that returned "true, but" would be a
# gate in name only.
#
# But a red run is not the end of the road. Stopping there would leave the
# human with a broken feature and a log, which is the situation the gate exists
# to prevent — so a failure opens a fixing session, and when that session ends
# the same stage runs again. Green means the cycle carries on by itself; red
# means one more attempt, and then the feature is handed back.
#
# A stage already green is not run again. The state is per stage and is reset by
# the run itself, so this is not a cache to go stale: `code` closing means the
# tree was green at that moment, and the next thing that can invalidate it is a
# commit, which starts the step over anyway.
# Take the stage's red mark off the issue chain, now that it is green.
#
# Here rather than in the epilogue, and that is the point of it: the epilogue
# runs once at the end of the cycle, while a stage can go red and green again
# several times before then — and between those two moments the mark is the only
# thing telling a reader of the epic that the deployment is broken. Left until
# the end it would be a mark nobody could trust, because it would lag the truth
# by however long the fix took.
#
# Unconditional rather than guarded by "was it red before". The state that would
# answer that is the same state a fixing session may have rewritten, and asking
# costs a request we are already making; removing a label that is not there is a
# no-op on GitHub's side and silent on ours.
#
# Quiet on everything unknown — no issue, no gh, no chain. A green regression is
# not worth failing over a label, and the caller has already recorded the pass.
regression_clear_mark() {
  local wt="$1" stage="$2" issue repo numbers

  [[ "$stage" == "preview" || "$stage" == "prod" ]] || return 0
  issue="$(state_get "$wt/.sclaude/local/feature/state.json" issue 2>/dev/null || true)"
  [[ -n "$issue" && "$issue" != "null" ]] || return 0
  command -v gh >/dev/null 2>&1 || return 0
  repo="$(gh_repo)" || return 0
  [[ -n "$repo" ]] || return 0

  # The same walk run_status makes, for the same reason: the mark went on to the
  # whole chain, so it has to come off the whole chain. A walk that fails leaves
  # us the issue itself, which is better than leaving the mark everywhere.
  numbers="$(python3 "$LIB/issue_chain.py" --numbers "$issue" "$REPO" 2>/dev/null)" \
    || numbers=""
  [[ -n "$numbers" ]] || numbers="$issue"

  clear_regression_label "$repo" "$stage" "$numbers"
}

regression_gate() {
  local wt="$1" slug="$2" stage="$3"
  local state="$wt/.sclaude/local/feature/state.json"
  local attempts

  # A local verdict is about a tree, and it stays true exactly as long as the
  # tree does. After a review that left no comments nothing in the tree has
  # moved since step 2 ran the suite, and running it again would spend minutes
  # to learn what is already known. Any change — a commit, an edit not yet
  # committed, a verdict recorded before trees were — and it runs.
  #
  # Only local: a deployed verdict is about a deployment, which remind_prod
  # compares on its own terms (deploy_unchanged).
  local only=""
  # Judged against main as it is now, when the branch can be moved there
  # without a question (sync_unpublished).
  [[ "$stage" == "local" ]] && declare -F sync_unpublished >/dev/null && sync_unpublished "$wt"
  if [[ "$stage" == "local" && "$(regression_status "$wt" local)" == "passed" ]]; then
    local was now
    was="$(state_get "$state" regression.local.tree 2>/dev/null || true)"
    now="$(regression_tree "$wt")"
    if [[ -n "$now" && "$was" == "$now" ]]; then
      echo ""
      info "  Local regression already green on this exact tree (${now:0:8}) — not run again."
      return 0
    fi
    # Only the manuals moved since the green run: the checks that read the
    # code, not the whole suite. For the first run only — once a fixing session
    # has touched the tree, the diff is no longer just the manuals.
    only="$(regression_manual_parts "$wt" "$was" "$now" || true)"
    state_set "$state" regression.local.status null
  fi

  # Already green: nothing ran now and nothing was fixed now, so nothing is
  # rewound. A rewind belongs to the green run that followed a fix, and that
  # run did it at the time.
  # A preview verdict is about the tree that was deployed and run, and the
  # tree moves: a production rollback sends the fix round again, and a green
  # recorded before it would let the new tree past without its suite. So a
  # recorded tree that is not this one — or none, or a dirty one — is no
  # verdict at all, the same rule the local stage keeps above.
  if [[ "$stage" == "preview" && "$(regression_status "$wt" preview)" == "passed" ]]; then
    local ran_on; ran_on="$(state_get "$state" regression.preview.tree 2>/dev/null || true)"
    local tree_now; tree_now="$(regression_tree "$wt")"
    if [[ -z "$tree_now" || "$ran_on" != "$tree_now" ]]; then
      state_set "$state" regression.preview.status null
    fi
  fi

  if [[ "$(regression_status "$wt" "$stage")" == "passed" ]]; then
    return 0
  fi

  # A note from the previous pass is a question to the human that nothing used
  # to ask. The session that wrote it found the cause outside this worktree and
  # named what had to change and who could change it — and then the next
  # `sclaude` ran the same suite for four minutes, failed the same way, and
  # opened a session to reach the same conclusion. The note was a message with
  # no delivery.
  #
  # So it is read back here, before anything is spent. If the cause has been
  # addressed the note goes and the run proceeds; if it has not, there is
  # nothing to learn from running, and saying so costs a second rather than
  # minutes.
  local note="$wt/.sclaude/local/feature/regression.blocked"
  if [[ -s "$note" ]]; then
    echo ""
    warn "  The last $stage run was blocked by a cause outside this branch:"
    while IFS= read -r line; do
      info "  $line"
    done < "$note"
    echo ""
    local fixed=""
    ask "${BOLD}  Has that been dealt with? [y/n] ${OFF}" fixed yn || true
    if is_yes "$fixed"; then
      rm -f "$note"
      info "  Running $stage again."
    else
      info "  Leaving it: the run would fail the same way."
      info "  The note is .sclaude/local/feature/regression.blocked; carry on with: $SELF $slug"
      return 1
    fi
  fi

  local rc fixed_here=0
  if [[ -n "$only" ]]; then
    echo ""
    info "  Only the manuals changed since the last green run — running $only."
  fi
  while :; do
    # A preview run is about the deployment, so the deployment must be the
    # tree. A fixing session commits to the branch and the loop comes round
    # here while the preview still serves the commit before the fix: the rerun
    # would check code that is gone, stay red on a fix that works, or go green
    # on a loosened test with the fix never deployed, and record that verdict
    # against a tree nobody deployed. So a moved tree is deployed first.
    #
    # Unknown counts as moved (deploy_unchanged is false on no record), and a
    # redeploy that fails ends the gate: a run against the old address answers
    # a question nobody asked.
    if [[ "$stage" == "preview" ]] && ! deploy_unchanged "$wt" preview; then
      echo ""
      info "  The branch moved since its preview was deployed — deploying it again."
      preview_apply_migrations "$wt" || true
      if ! preview_ship "$wt"; then
        alarm "  The preview could not be redeployed, so the $stage regression was not run again."
        info "  Carry on when it can be deployed with: $SELF $slug"
        return 1
      fi
    fi
    regression_run "$wt" "$slug" "$stage" "$only"
    rc=$?
    only=""

    if [[ "$rc" -eq 0 ]]; then
      # Green, and if a session preceded this run it is the one that did it.
      # `fix_status_set` rewrites the last word, which is that session; a stage
      # that went green with no fixing session at all has an empty string and
      # gets nothing.
      [[ -n "$(state_get "$state" "regression.$stage.fix_status" 2>/dev/null || true)" ]] \
        && fix_status_set "$state" "$stage" green
      state_set "$state" "regression.$stage.attempts" 0
      regression_clear_mark "$wt" "$stage"
      state_set "$state" "regression.$stage.orchestrator_fixes" 0
      # A later red is a new problem, even on the same part: it gets a fresh
      # session rather than the one whose fix has just gone green.
      state_set "$state" "regression.$stage.fix_session" null
      state_set "$state" "regression.$stage.fix_for" null
      # The cycle goes back to the step the fix belongs to only when there was
      # a fix. It used to go back on every green run, so a preview that simply
      # passed put a finished feature back on step 4, marked as reopened.
      [[ "$fixed_here" -eq 1 ]] && regression_rewind "$wt" "$slug" "$stage"
      return 0
    fi

    # 2 means the stage could not run at all. There is nothing for a session to
    # fix, so we stop without spending one and without counting it against the
    # two attempts a real failure gets.
    #
    # But "could not run" has two shapes and they must not share an answer. A
    # deployed stage with no address is a deploy that did not happen, and the
    # step is right to wait. A project that declares no regression for this
    # stage has none to wait for — holding the cycle there would mean a
    # repository without a suite could never close a step at all, which is the
    # opposite of what making the config optional was for.
    if [[ "$rc" -eq 2 ]]; then
      [[ -z "$(regression_parts "$stage" "$wt" 2>/dev/null || true)" ]] && return 0
      return 1
    fi

    # The count lives in the state rather than in a variable here: a session
    # closed halfway through would otherwise reset it, and a limit that resets
    # is not a limit. It is cleared by a green run above.
    attempts="$(state_get "$state" "regression.$stage.attempts" 2>/dev/null || echo 0)"
    [[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0

    if [[ "$attempts" -ge "$REGRESSION_MAX_ATTEMPTS" ]]; then
      echo ""
      warn "  The $stage regression is still red after $attempts fixing session(s)."
      info "  A test that does not come right in two goes usually means the wrong"
      info "  thing is being fixed — which is why the limit stops here rather than"
      info "  spending a third session on the same guess."
      local failed_part
      failed_part="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
      [[ -n "$failed_part" && "$failed_part" != "null" ]] || failed_part="a part"
      info "  Failed on: $failed_part. The log is .sclaude/local/feature/regression.log"
      notify_feature "$slug" "Regression still red on $stage
$attempts fixing session(s) did not help — it needs you.
Log: .sclaude/local/feature/regression.log" 2>/dev/null || true

      # The limit stops the machine, not the human. Stopping silently would hand
      # back a feature with no way forward but `sclaude reset`, and the person
      # who has just read the log is exactly the one who knows whether a third
      # session is worth it — they may have fixed the cause by hand, or changed
      # the environment under it, which is the common case on a deployed stage.
      #
      # Asked rather than assumed: two failed goes are evidence against a third,
      # but only the person who read the log knows. ask takes only an explicit
      # y or n, so a reflex Enter at the end of a long run settles nothing.
      echo ""
      local again=""
      ask "${BOLD}  Open another fixing session? [y/n] ${OFF}" again yn || true
      if is_yes "$again"; then
        # Clearing the count and falling through to the fix below, rather than
        # going round to the top of the loop. The top is regression_run, and a
        # re-run is the one thing known to be pointless here: the same suite
        # against the same address with the same tree answers the same way. The
        # human who says yes is asking for another look at the failure, not for
        # a fourth confirmation that it fails.
        state_set "$state" "regression.$stage.attempts" 0
        attempts=0
        info "  Opening another session on $stage."
      else
        info "  Carry on when you are ready with: $SELF $slug"
        return 1
      fi
    fi

    state_set "$state" "regression.$stage.attempts" "$((attempts + 1))"
    regression_fix "$wt" "$slug" "$stage"
    local frc=$?
    if [[ "$frc" -eq 5 ]]; then
      state_set "$state" "regression.$stage.attempts" "$attempts"
      info "  Nothing was spent on $stage. Repair sclaude's rules, then: $SELF $slug"
      return 1
    fi

    # 4 means the friction review after the session fixed the orchestrator.
    # The stage is run again rather than reported: a red run must never be
    # something the cycle walks past, and "carry on with sclaude <feature>" was
    # exactly that. The attempt is given back — it was not the branch that was
    # wrong.
    #
    # With the new code, not the old. bash has every function of this process
    # in memory already, so a loop round here would run the regression exactly
    # as it ran before the fix. The preview re-enters through remind_prod,
    # which redeploys a preview whose last run was red, so the process is
    # replaced by a fresh `sclaude <feature>` that reads the fixed modules. The
    # other stages have no such clean re-entry — local goes back through its
    # step's session, prod through a deploy of an unchanged main — so they go
    # round here, in-process: the fixes a review makes are to hooks and prompts
    # far more often than to regression.sh itself.
    #
    # Not without end. Each pass spends a fixing session and a friction review,
    # and a review can always find something to change; after
    # REGRESSION_MAX_ATTEMPTS such passes the attempt is counted like any other,
    # so the ordinary limit stops the machine and asks the person.
    if [[ "$frc" -eq 4 ]]; then
      fixed_here=1
      fix_status_set "$state" "$stage" orchestrator-fixed
      local ofix
      ofix="$(state_get "$state" "regression.$stage.orchestrator_fixes" 2>/dev/null || echo 0)"
      [[ "$ofix" =~ ^[0-9]+$ ]] || ofix=0
      state_set "$state" "regression.$stage.orchestrator_fixes" "$((ofix + 1))"
      if [[ "$ofix" -lt "$REGRESSION_MAX_ATTEMPTS" ]]; then
        state_set "$state" "regression.$stage.attempts" "$attempts"
      fi
      echo ""
      info "  The friction review fixed the orchestrator — running $stage again."
      if [[ "$stage" == "preview" ]]; then
        info "  Restarting sclaude so the run uses the fixed code."
        exec "$INSTRUMENTS/bin/sclaude" "$slug"
      fi
      continue
    fi

    # 3 means the session found the cause outside this worktree and wrote it
    # down instead of editing code to make a red run go green. Another session
    # would reach the same conclusion, and a re-run would confirm the same
    # failure, so we do neither: the attempt is given back and the note is put
    # in front of the human, who is the only one who can change a deployment's
    # environment.
    if [[ "$frc" -eq 3 ]]; then
      # Neither "fixed" nor "failed to fix": the third outcome, and the attempt
      # is given back. It stays distinct from `red` because the attempt is not
      # counted — merging the two would put the row numbers at odds with
      # `attempts`.
      fix_status_set "$state" "$stage" blocked
      state_set "$state" "regression.$stage.attempts" "$attempts"
      echo ""
      warn "  The $stage regression is red for a reason outside this branch."
      while IFS= read -r line; do
        info "  $line"
      done < "$wt/.sclaude/local/feature/regression.blocked"
      echo ""
      info "  Nothing was changed, and the attempt was not counted."
      info "  The note is .sclaude/local/feature/regression.blocked; carry on with: $SELF $slug"
      notify_feature "$slug" "${stage^} regression blocked from outside
The fixing session found the cause outside the branch and changed nothing.
Note: .sclaude/local/feature/regression.blocked" 2>/dev/null || true
      return 1
    fi

    [[ "$frc" -eq 0 ]] || return 1
    fixed_here=1

    # The session finished and the loop goes round to run the stage again. If
    # that run is green the branch at the top rewrites this to `green`; if it
    # is red again, `red` is what this session came to. Recording it here rather
    # than inferring it at render time is the rule the Friction column follows:
    # every value is written at the moment it happens.
    #
    # `stalled` is not overwritten: a session that never ran did not leave the
    # stage red, it left nothing at all, and the row should keep saying so.
    [[ "$(state_get "$state" "regression.$stage.fix_status" 2>/dev/null || true)" \
       == *stalled ]] || fix_status_set "$state" "$stage" red
  done
}

# The tree a run is about: HEAD's commit when the working tree is clean, and
# nothing when it is not. An uncommitted edit has no name, so a dirty tree never
# matches a recorded one and the suite always runs on it.
#
# worktree_dirt rather than a bare `git status`: it leaves out sclaude's own
# scratch paths (.sclaude/local/feature, .vercelignore), which are untracked wherever the
# exclude was never written — and then no tree would ever match. It is the
# same question deploy_unchanged asks, and the two must not disagree.
regression_tree() {
  local wt="$1"
  git -C "$wt" rev-parse HEAD >/dev/null 2>&1 || return 0
  [[ -z "$(worktree_dirt "$wt")" ]] || return 0
  git -C "$wt" rev-parse HEAD 2>/dev/null || true
}

# Puts the cycle back on the step the fix belongs to, once the stage is green.
#
# After the green run rather than before the fix, and that ordering is the
# whole of it. Rewinding first would mean a state that lies the moment a
# session is interrupted: the step stands open with no work done in it. Doing
# it here describes what actually happened — there are changes, they have been
# checked, and the cycle honestly returns to the step they belong to.
#
# The idiom is cmd_replan's (bin/sclaude): clear `done` and `finished`, set
# `step`, and let the caller's own run_step carry it forward.
regression_rewind() {
  local wt="$1" slug="$2" stage="$3"
  local -a rewind=()

  case "$stage" in
    # Step 2 is already the current one — there is nothing to rewind into.
    local) return 0 ;;
    # The pull request is open and pushes still reach the branch, so the review
    # is where the fix belongs.
    preview) rewind=(review) ;;
    # Production also rewinds to the review, and deliberately not to step 3 as
    # well. A merged pull request is `closed` on GitHub's side and cannot be
    # reopened, so the fix does need a pull request of its own — but step 3
    # cannot tell a new one from the merged one: capture_pr asks `gh pr view`,
    # which on that branch still answers with the old number, and the step's
    # check is only that a number exists. Rewinding into a step that closes
    # itself on stale evidence buys nothing. The review session opens the new
    # pull request instead, carrying `Closes #N` for the same issue — one
    # business task, two pull requests, which is the only shape that ships.
    prod) rewind=(review) ;;
    *) return 0 ;;
  esac

  # The four lines this used to spell out live in step_rewind_to (steps.sh):
  # `cmd_replan` and the QA hand-back want the same ones, differing only in
  # which steps they name.
  step_rewind_to "$wt" "${rewind[0]}" "${rewind[@]}"
  # The same two marks the QA hand-back writes, and for the same reason: by the
  # time a deployed stage goes red the pull request is merged — production ships
  # after the merge — so `run_step` would treat the review as having nothing left
  # to do, and `after_step` would close it again the moment the session exited.
  # Only one of the two reopeners used to write them, which left this path with
  # exactly the bug the other one had fixed.
  local state="$wt/.sclaude/local/feature/state.json" pr
  state_set "$state" reopened "${rewind[0]}" 2>/dev/null || true
  # And who reopened it. A preview fix is already green on the preview and goes
  # on to QA and the merge in the same run: once merged, the mark has nothing
  # left to hold, and run_step lets the merge close the review. A production
  # one holds until a new pull request arrives, and render_prompt hands that
  # review the failure. QA's hand-back writes its own (watch_rewind).
  state_set "$state" reopened_by "$stage" 2>/dev/null || true
  # A production fix goes the whole way round, preview suite included — and the
  # preview gate short-circuits on a verdict it already holds. The tree check
  # there would catch it too; clearing it here says so where it happens.
  [[ "$stage" == "prod" ]] \
    && state_set "$state" regression.preview.status null 2>/dev/null || true
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  [[ -n "$pr" && "$pr" != "null" ]] \
    && state_set "$state" reopened_pr "$pr" 2>/dev/null || true
  issue_sync "$wt"
  info "  The cycle returns to step '$(step_title "${rewind[0]}")'."
  return 0
}

# Which step fixes a stage's failure.
#
# Local means the code is wrong and step 2 is where code is written. A deployed
# stage means the branch is already a pull request, and review is the step that
# pushes to it — including after production, because the worktree and the branch
# now outlive the prod deploy (remind_prod cleans up last). What that session
# must not do is commit to main: the feature's PR is merged by then, so a fix
# branches from a fresh main and opens a new pull request of its own. The prompt
# says so; the step's own bans already refuse a merge.
regression_fix_step() {
  case "$1" in
    local) printf 'code' ;;
    *)     printf 'review' ;;
  esac
}

# What became of one fixing session, kept beside its id.
#
# A space-joined string aligned with `fixes`, position for position, because
# state_set writes scalars and a list is not among the shapes it can carry —
# the same constraint that made `fixes` a string. The reader numbers rows by
# position in `fixes`, so both sides derive the row from the same thing.
#
# Two operations, and keeping them apart is the whole of it. A launch appends a
# word — that is what makes the string grow in step with `fixes`. An outcome
# rewrites the last word, which is the session that was just launched; every
# earlier word is settled history.
#
# Written as one function with an append flag rather than two, because the two
# must agree on the shape of the string, and a second function is a second
# place for that agreement to rot.
fix_status_set() {
  fix_word_set "$1" "$2" fix_status "$3" "${4:-}"
}

# The same shape for any field aligned with `fixes`: fix_status, and the
# session's own start and end times (fix_started, fix_finished).
fix_word_set() {
  local state="$1" stage="$2" field="$3" value="$4" append="${5:-}"
  local current
  current="$(state_get "$state" "regression.$stage.$field" 2>/dev/null || true)"
  if [[ "$append" == "append" || -z "$current" ]]; then
    state_set "$state" "regression.$stage.$field" "${current:+$current }$value"
  else
    state_set "$state" "regression.$stage.$field" \
      "$(printf '%s' "$current" | awk -v v="$value" '{ $NF = v; print }')"
  fi
}

# The block a fixing prompt embeds (`<block:regression>`): which stage failed,
# on which part, the tail of its log, and what the session must know about the
# pull request and about a rollback.
#
# Two callers. regression_fix, for a session the gate opens, passes `gate` and
# gets _regression-fail.md as well: that file speaks of the gate's rerun and of
# the note the gate reads back. run.sh, for the review session that follows a
# production rollback, passes nothing — no gate runs after that session, and a
# note it wrote would be read by nobody.
#
# `merged` is the pull request's state when the caller knows it; prod implies
# it, since production ships only after the merge.
regression_fix_block() {
  local wt="$1" stage="$2" merged="${3:-}" mode="${4:-}"
  local state="$wt/.sclaude/local/feature/state.json" log="$wt/.sclaude/local/feature/regression.log"
  local failed pr issue
  failed="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
  [[ "$failed" == "null" ]] && failed=""
  pr="$(state_get "$state" pr 2>/dev/null || true)"
  issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ "$issue" == "null" ]] && issue=""

  # The block the prompt embeds: which stage, which part, and the tail of the
  # log. The tail rather than the whole file — the session can open the file
  # itself, and the prompt's job is to say where to look, not to be the log.
  # Which log to quote. After a rollback it is not the one at the usual path:
  # regression_run opens with `: > "$log"`, and the confirmation run that
  # follows a rollback is a regression_run — so by the time this session opens,
  # `.sclaude/local/feature/regression.log` describes the *previous release passing*. That is
  # the opposite of the evidence this session needs and plausible enough that
  # nobody would question it, which is why rollback_keep_log copies the failing
  # run aside and records where.
  local rolled kept
  rolled="$(state_get "$state" rollback.prod.code 2>/dev/null || true)"
  kept="$(state_get "$state" rollback.prod.log 2>/dev/null || true)"
  [[ "$kept" == "null" ]] && kept=""
  [[ -n "$kept" && -s "$kept" ]] || kept="$log"

  printf '**The %s regression failed on `%s`.**\n\n' "$stage" "${failed:-a part}"
  if [[ "$rolled" == "done" && "$kept" != "$log" ]]; then
    printf 'That run'"'"'s full output is kept at `%s` — read it rather than\n' "${kept#$wt/}"
    printf '`.sclaude/local/feature/regression.log`, which now holds the check made *after* the\n'
    printf 'rollback, against the previous release. Its last lines:\n\n'
  else
    printf 'The full output is in `.sclaude/local/feature/regression.log`; its last lines:\n\n'
  fi
  printf '```\n%s\n```\n\n' "$(tail -30 "$kept" 2>/dev/null)"
  # A merged pull request cannot be reopened, so the fix needs a new one — from
  # this same branch. sclaude follows the feature by the branch its state
  # names: the PR it records, whether that PR is merged, what the preview
  # deploys. A fix on a branch of another name is one it never sees, and it
  # reads the old branch as merged and walks the fix past preview and QA.
  # after_step refuses a review that ends on another branch.
  if [[ "$stage" == "prod" || "$merged" == "MERGED" ]]; then
    if [[ "$stage" == "prod" ]]; then
      printf 'This failed against production, and the feature'"'"'s pull request #%s is already merged. ' "$pr"
    else
      # A preview can go red after the merge: the human may merge while the
      # review step is still open. The review prompt below then describes the
      # pull request as open, and a session believing it pushes to a dead branch.
      printf 'The feature'"'"'s pull request #%s is already merged, whatever the step prompt below says about it being open. ' "$pr"
    fi
    printf 'Do not commit to `main`, and stay on this branch: merge a fresh `origin/main` into it, '
    printf 'commit the fix, push, and open a new pull request from this same branch%s. ' \
      "${issue:+ carrying \`Closes #$issue\`}"
    printf 'The merged one cannot be reopened, and the orchestrator follows the feature by '
    printf 'this branch'"'"'s name — a fix on a branch of another name is one it never sees.\n\n'
  fi
  if [[ "$rolled" == "done" ]]; then
    cat "$PROMPTS/_rollback-fix.md" 2>/dev/null
    printf '\n'
  fi
  [[ "$mode" == "gate" ]] && cat "$PROMPTS/_regression-fail.md" 2>/dev/null
  return 0
}

# Raises the session that fixes a failed run.
#
# A new session every time rather than a resume: a failure is a fresh task with
# a log to read, and resuming the step's own conversation would drop it into a
# context that believes it has already finished. The step's session id in the
# state is deliberately left alone — this session is not the step.
#
# No question before it. The human has just watched the run fail; asking
# "shall I fix it?" is asking whether they meant what the gate already decided.
regression_fix() {
  local wt="$1" slug="$2" stage="$3"
  local state="$wt/.sclaude/local/feature/state.json"
  local step model effort mode session prompt pr issue
  local -a extra

  step="$(regression_fix_step "$stage")"
  [[ -f "$PROMPTS/$step.md" ]] || return 1

  pr="$(state_get "$state" pr 2>/dev/null || true)"
  issue="$(state_get "$state" issue 2>/dev/null || true)"
  [[ "$issue" == "null" ]] && issue=""
  # Asked rather than inferred from the stage: regression_fix_block tells the
  # session what a merged pull request means for where the fix goes.
  local merged=""
  if [[ "$stage" != "prod" && -n "$pr" && "$pr" != "null" ]]; then
    merged="$(cd "$wt" && gh pr view "$pr" --json state -q .state 2>/dev/null || true)"
  fi

  model="$(step_model "$step")"
  effort="$(step_effort "$step")"
  mode="$(step_mode "$step")"

  local -x SCLAUDE_B_REGRESSION
  SCLAUDE_B_REGRESSION="$(regression_fix_block "$wt" "$stage" "$merged" gate)"

  local settings
  # 5: not started, for sclaude's own trouble rather than the branch's, so the
  # caller neither counts it as an attempt nor reports a failed fix.
  settings="$(step_settings "$step" "$wt")" \
    || { warn "  The fix was not started: sclaude could not read its rules (see above)."; return 5; }
  mapfile -t extra <<< "$settings"

  # The same part red again after a fix goes back to the session that made the
  # fix: it has just learnt that its guess was wrong, and with its context it
  # knows what it already tried rather than trying it a second time. Another
  # part red is another problem, and gets a session of its own. The limit on
  # attempts is what stops a session from circling one wrong idea — after it
  # the person is asked.
  local failed resume=""
  failed="$(state_get "$state" "regression.$stage.failed_at" 2>/dev/null || true)"
  session="$(state_get "$state" "regression.$stage.fix_session" 2>/dev/null || true)"
  if [[ -n "$failed" && "$failed" != "null" \
        && "$(state_get "$state" "regression.$stage.fix_for" 2>/dev/null || true)" == "$failed" ]] \
     && live_session "$wt" "$session" >/dev/null; then
    resume=1
    echo ""
    info "  Still red on $failed — back to the session that fixed it."
    ask_feed say "$(phase_line resumed fix "$stage" "$failed") · still red after its fix"
  else
    session="$(new_session_id)"
    echo ""
    info "  Opening a session in step '$(step_title "$step")' to fix it."
    ask_feed say "$(phase_line started fix "$stage" "$([[ "$failed" != "null" ]] && echo "$failed")")"
  fi
  state_set "$state" "regression.$stage.fix_session" "$session"
  state_set "$state" "regression.$stage.fix_for" "${failed:-null}"

  # The fixing session's id, recorded so the issue's summary can name it.
  #
  # Deliberately not in `steps.<name>.session`: that field is the step's own
  # conversation, and the orchestrator resumes by it. A fix is a separate
  # conversation about the same step, so it goes beside the stage it belongs
  # to — and the summary prints it as a line of its own rather than in the
  # table, where it would read as though the step had been restarted.
  #
  # Space-joined rather than a JSON list: state_set writes scalars, coercing
  # digits and true/false/null, and a list is not among the shapes it can put
  # in. A string of ids is the representation it can carry unharmed.
  local fixes
  fixes="$(state_get "$state" "regression.$stage.fixes" 2>/dev/null || true)"
  state_set "$state" "regression.$stage.fixes" "${fixes:+$fixes }${session:0:8}"
  # Its name: the row it takes in `fixes`, the number run_friction keys by.
  local name
  name="$(session_label fix "fix-$stage-$(( $(printf '%s' "$fixes" | wc -w) + 1 ))")/$slug"

  # And an outcome beside the id, opened as `open`.
  #
  # Written before the session runs rather than after it, for the same reason
  # the id is: a session interrupted halfway leaves the row saying what is true
  # of it — there is a conversation to return to — instead of nothing. The
  # endings below overwrite it.
  fix_status_set "$state" "$stage" open append
  # And the session's own times, in the same shape. The summary used to show
  # the friction review's times on this row, which left a session whose review
  # had nothing to read with no times at all. `-` holds the end's place until
  # the session exits, so an interrupted one keeps the words aligned.
  # A feature that already had sessions before these fields existed gets a
  # `-` for each, so the words stay aligned with `fixes` by position.
  if [[ -z "$(state_get "$state" "regression.$stage.fix_started" 2>/dev/null || true)" ]]; then
    local older
    older="$(( $(printf '%s' "$fixes" | wc -w) ))"
    while [[ "$older" -gt 0 ]]; do
      fix_word_set "$state" "$stage" fix_started - append
      fix_word_set "$state" "$stage" fix_finished - append
      older=$((older - 1))
    done
  fi
  fix_word_set "$state" "$stage" fix_started "$(date -Iseconds)" append
  fix_word_set "$state" "$stage" fix_finished - append
  session_watch_start "$wt" "$session"
  if [[ -n "$resume" ]]; then
    prompt="$(printf '**Your fix did not make the %s regression green.** It ran again and failed on the same part.\n\n%s\n' \
      "$stage" "$SCLAUDE_B_REGRESSION")"
    ( cd "$wt" && dev_env_load "$wt" && claude_launch --resume "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$name" "$prompt" )
  else
    prompt="$(render_prompt "$step" "$slug" "$pr" "$issue" "$wt")"
    ( cd "$wt" && dev_env_load "$wt" && claude_launch --session-id "$session" \
        --model "$model" --effort "$effort" \
        --permission-mode "$mode" "${extra[@]}" -n "$name" "$prompt" )
  fi
  session_watch_stop
  fix_word_set "$state" "$stage" fix_finished "$(date -Iseconds)"

  # The session said its fix is in and the watcher closed it; the gate's next
  # run is the judge. Its report is printed here, since claude's screen went
  # with it. See done_marker.
  session_closed "$(done_marker "$wt")" "$wt" "$session" "" "" \
    fix "$stage" "$([[ "$failed" != "null" ]] && echo "$failed")" || true

  # A session that exited at the door leaves no assistant record, and the row
  # should say so rather than carry an id nobody can resume. The wall clock is
  # not asked: it times the wrapper, and a session that died on entry can spend
  # seven seconds doing it — which is how this feature got a `fix-preview-3` of
  # 0.2 seconds marked done. The transcript is the honest witness.
  session_started "$wt" "$session" || fix_status_set "$state" "$stage" stalled

  # And the friction review for the session that has just ended.
  #
  # A fixing session runs into missing tools exactly as a step does — it is
  # reading a regression log and trying to reproduce a failure, which is the
  # kind of work a ban gets in the way of. Its entries used to have nowhere to
  # go: the reviews after each step all happen earlier in the cycle, and the
  # deployed stages run inside remind_prod, after the last of them. Nothing
  # would have picked these up before cmd_done removed the tree.
  #
  # One review per fixing session, keyed by that session's place in `fixes`.
  #
  # NOT by `regression.<stage>.attempts`, which is what this did first and got
  # wrong. That counter is a limit, not an identifier: it is reset to zero in
  # three places — by a green run (regression_gate), by `sclaude reset`, and on
  # entering step 4, which clears the local stage's. `fixes` only ever grows.
  # So a stage that went red, was fixed, went green and went red again wrote
  # both reviews to `fix-<stage>-1`: the second overwrote the first, and the
  # summary — which numbers the rows by position in `fixes` — then looked up a
  # `fix-<stage>-2` that did not exist. Row one showed the second review's
  # times against the first session's id, and row two claimed no review had
  # happened when one had.
  #
  # Counting the position here makes the writer and the reader derive the key
  # from the same thing, so no reset of the counter can pull them apart.
  #
  # An empty log means no session, by run_friction's own emptiness check: a
  # fixing session that hit no obstacle is the ordinary case, and a review with
  # nothing to read costs a launch for nothing.
  local number
  number="$(state_get "$state" "regression.$stage.fixes" 2>/dev/null || true)"
  number="$(printf '%s' "$number" | wc -w)"
  [[ "$number" =~ ^[0-9]+$ && "$number" -ge 1 ]] || number=1
  run_friction "$wt" "$slug" "fix-$stage-$number" || true

  # The friction review changed the orchestrator. A cause "outside this branch"
  # is very often the orchestrator itself — once a preview e2e ran with
  # the worktree's local database because of how sclaude wired the environment,
  # and the review right here fixed exactly that. Stopping with "blocked" and
  # "carry on with sclaude <feature>" then hands the human an errand the machine
  # can do: the note's cause may be gone, and the only way to know is to run the
  # stage again. 4 says so to the gate, which re-runs with the new code.
  #
  # The note goes: it described the state before the fix, and left in place it
  # would stop the next run with "has that been dealt with?" about a cause the
  # fix was for. If the fix did not help, the next red run writes a new one.
  if [[ "$(state_get "$state" "friction.fix-$stage-$number.fixed" 2>/dev/null || true)" == "true" ]]; then
    rm -f "$wt/.sclaude/local/feature/regression.blocked"
    return 4
  fi

  # A session that found the cause outside this tree leaves a note rather than a
  # commit, and that is a third outcome — neither "fixed" nor "failed to fix".
  #
  # Without it such a session has no sanctioned way to end: the prompt above
  # tells it to fix the cause and re-run, so a session that correctly concludes
  # "the deployment points at a different bucket, nothing here to change" spends
  # its last turns arguing that it should be allowed to close. Then the gate
  # counts the attempt and answers the argument with an identical run.
  #
  # 3 says so to the gate, which stops without spending the attempt.
  [[ -s "$wt/.sclaude/local/feature/regression.blocked" ]] && return 3
  return 0
}
