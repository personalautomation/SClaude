#!/usr/bin/env python3
#
# A feature's own local Supabase: the rewritten config, the environment file,
# and ensure_db deciding when a feature gets a stack at all.
#
# The stack itself is a stub here — a script that records how it was called and
# answers `status` the way the CLI does. What is at stake is the orchestration:
# two features must never share a block of ports, the main repository's stack
# must never be the one rewritten, a feature on the cloud project must not keep
# sourcing a local address, and the seed runs once, not on every step.
#
# Run it with: python3 tests/feature_db.py
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "sclaude", "lib")
sys.path.insert(0, LIB)

import feature_db  # noqa: E402


def _cfg(path):
    """The path of a product's config, its .sclaude/ folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


CONFIG = """# a comment with port = 1
project_id = "myapp"

[api]
enabled = true
port = 54321

[db]
port = 54322
shadow_port = 54320

[db.pooler]
port = 54329

[studio]
port = 54323

[inbucket]
port = 54324
# smtp_port = 54325

[auth.email.smtp]
# port = 587

[edge_runtime]
inspector_port = 8083

[analytics]
port = 54327

[remotes.staging]
project_id = "should-stay"
"""


def config_cases():
    out = feature_db.rewrite_config(CONFIG, "myapp-a", 55010)
    lines = out.split("\n")
    check("project_id at the top", 'project_id = "myapp-a"' in lines, True)
    check("project_id in a section untouched", 'project_id = "should-stay"' in lines, True)
    for want in ("port = 55011", "port = 55012", "shadow_port = 55010", "port = 55019",
                 "port = 55013", "port = 55014", "inspector_port = 55018", "port = 55017"):
        check("rewritten: " + want, want in lines, True)
    check("comments untouched", "# a comment with port = 1" in lines
          and "# port = 587" in lines and "# smtp_port = 54325" in lines, True)
    check("no original port left", any("5432" in l and not l.startswith("#")
                                       for l in lines), False)


def env_cases():
    status = feature_db.parse_status('API_URL="http://127.0.0.1:55011"\n'
                                     'SECRET_KEY="a b$c"\nnoise\n')
    check("status parsed", status.get("API_URL"), "http://127.0.0.1:55011")
    lines = feature_db.env_lines({"URL": "API_URL", "SECRET": "SECRET_KEY"}, status, "/w d")
    check("workdir is always there", "SUPABASE_WORKDIR='/w d'" in lines, True)
    check("values are shell-quoted", "SECRET='a b$c'" in lines, True)
    check("a missing key fails", feature_db.env_lines({"X": "NOPE"}, status, "/w"), None)


STUB_CLI = r"""#!/usr/bin/env bash
# Records every call; answers `status` only once `start` has run.
echo "$*" >> "$STUB_LOG"
dir=""
while [[ $# -gt 0 ]]; do
  [[ "$1" == "--workdir" ]] && dir="$2"
  shift
done
case "$(tail -1 "$STUB_LOG")" in
  start*) touch "$dir/.started"; exit 0 ;;
  status*)
    [[ -f "$dir/.started" ]] || exit 1
    base=$(sed -n 's/^port = \(5[0-9]*1\)$/\1/p' "$dir/supabase/config.toml" | head -1)
    echo "API_URL=\"http://127.0.0.1:$base\""
    echo "SECRET_KEY=\"sb_secret_x\""
    exit 0 ;;
  "migration up"*)
    ls "$dir/supabase/migrations" 2>/dev/null | sed 's/^/  has /' >> "$STUB_LOG"
    exit 0 ;;
  stop*) rm -f "$dir/.started"; exit 0 ;;
esac
"""


def on_env(wt, name):
    """Put a tree on an environment: its .env.local points at that file."""
    link = os.path.join(wt, ".env.local")
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(".env." + name, link)


ENVIRONMENTS = {"localdb": {"env": ".env.localdb"}, "dev": {"env": ".env.dev"}}


def feature_tree(root, name, env="localdb"):
    wt = os.path.join(root, name)
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    os.makedirs(os.path.join(wt, "supabase", "migrations"))
    os.makedirs(os.path.join(wt, "supabase", ".temp"))
    with open(os.path.join(wt, "supabase", "config.toml"), "w") as fh:
        fh.write(CONFIG)
    for env_name in ("localdb", "dev"):
        with open(os.path.join(wt, ".env." + env_name), "w") as fh:
            fh.write("APP_ENV=%s\n" % env_name)
    on_env(wt, env)
    with open(os.path.join(wt, ".sclaude/local/feature", "state.json"), "w") as fh:
        json.dump({"feature": name, "dev": {"label": name, "port": 3100}}, fh)
    return wt


def write_config(wt, cli, setup):
    with open(_cfg(os.path.join(wt, ".sclaude/config.json")), "w") as fh:
        json.dump({"environments": ENVIRONMENTS,
                   "database": {"local": {
            "environment": "localdb",
            "exclude": ["studio", "realtime"],
            "setup": setup,
            "cli": cli,
            "env": {"NEXT_PUBLIC_SUPABASE_URL": "API_URL",
                    "SUPABASE_SECRET_KEY": "SECRET_KEY"},
        }}}, fh)


def bash(root, body, env=None):
    script = """
set -uo pipefail
info() { echo "INFO $*"; }
warn() { echo "WARN $*"; }
GREEN=""; OFF=""
LIB="%s"
REPO="%s/repo"
docker() { return 0; }
source "$LIB/state.sh"
source "$LIB/project.sh"
source "$LIB/environment.sh"
source "$LIB/worktree.sh"
source "$LIB/featuredb.sh"
%s
""" % (LIB, root, body)
    full = dict(os.environ)
    full.pop("DEV_PORT", None)
    full.update({"HOME": root, "SCLAUDE_DEV_REGISTRY": os.path.join(root, "registry"),
                 "STUB_LOG": os.path.join(root, "cli.log"),
                 # Not the machine's real proxy: nothing listens here, so the
                 # answers do not depend on whether it happens to be running.
                 "SCLAUDE_PROXY_PORT": "1"})
    full.update(env or {})
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=full, timeout=60)
    return done.stdout


def calls(root):
    try:
        with open(os.path.join(root, "cli.log")) as fh:
            return [l.strip() for l in fh]
    except OSError:
        return []


def state(wt):
    with open(os.path.join(wt, ".sclaude/local/feature", "state.json")) as fh:
        return json.load(fh)


def ensure_cases():
    root = tempfile.mkdtemp(prefix="sclaude-featuredb-")
    try:
        os.makedirs(os.path.join(root, "repo"))
        os.makedirs(os.path.join(root, "registry"))
        cli = os.path.join(root, "stub-supabase")
        with open(cli, "w") as fh:
            fh.write(STUB_CLI)
        os.chmod(cli, 0o755)
        seeded = os.path.join(root, "seeded")

        a = feature_tree(root, "a")
        write_config(a, cli, "echo run >> %s; test -n \"$NEXT_PUBLIC_SUPABASE_URL\"" % seeded)
        os.symlink(a, os.path.join(root, "registry", "a"))

        out = bash(root, 'ensure_db "%s"' % a)
        envf = os.path.join(a, ".sclaude/local/feature", "db.env")
        check("a feature on localdb gets a stack", os.path.isfile(envf), True)
        started = [c for c in calls(root) if c.startswith("start")]
        check("started once, with the exclusions",
              len(started) == 1 and "-x studio,realtime" in started[0], True)
        base = state(a).get("db", {}).get("base")
        check("a block is recorded", isinstance(base, int), True)
        text = open(envf).read() if os.path.isfile(envf) else ""
        check("the env points at the feature's API",
              "NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:%s" % ((base or 0) + 1) in text, True)
        check("the env carries the workdir", "SUPABASE_WORKDIR=" in text, True)
        workdir = os.path.join(a, ".sclaude/local/feature", "supabase", "supabase")
        check("the config is rewritten", 'project_id = "myapp-a"' in
              open(os.path.join(workdir, "config.toml")).read(), True)
        check("the tree's config is untouched", 'project_id = "myapp"' in
              open(os.path.join(a, "supabase", "config.toml")).read(), True)
        check("migrations are the tree's", os.path.realpath(os.path.join(workdir, "migrations")),
              os.path.realpath(os.path.join(a, "supabase", "migrations")))
        check("the CLI's .temp is not shared", os.path.exists(os.path.join(workdir, ".temp")), False)
        check("the setup ran, with the env loaded", open(seeded).read().count("run"), 1)
        check("ready is recorded", state(a).get("db", {}).get("ready"), True)

        bash(root, 'ensure_db "%s"' % a)
        check("a running stack is not started again",
              len([c for c in calls(root) if c.startswith("start")]), 1)
        check("the setup does not run twice", open(seeded).read().count("run"), 1)
        check("migrations are applied every time",
              len([c for c in calls(root) if c.startswith("migration up")]), 2)

        # The id kept to what the Supabase CLI keeps, 40 characters of
        # [a-zA-Z0-9_.-]: the containers carry that form, so a longer id names
        # a container that is not there. A longer one ends in a hash, so two
        # labels alike in their first 40 characters get two stacks.
        none = "docker() { return 1; }\n"
        one = feature_tree(root, "153-a-feature-label-long-enough/to-cut")
        two = feature_tree(root, "153-a-feature-label-long-enough/to-cut-too")
        first = bash(root, none + 'db_project_id "%s"' % one).strip()
        check("a long id fits the CLI's 40", len(first) <= 40 and
              re.fullmatch(r"[a-zA-Z0-9_.-]+", first) is not None, True)
        check("a long id keeps its start", first.startswith("myapp-153-a-feature-label"), True)
        check("labels alike in 40 characters get two ids",
              first != bash(root, none + 'db_project_id "%s"' % two).strip(), True)
        check("the id is recorded", state(one).get("db", {}).get("project_id"), first)
        check("a short id is left whole", bash(root, none + 'db_project_id "%s"' % a).strip(),
              "myapp-a")
        # A stack started under the plain cut keeps its name.
        old = feature_tree(root, "153-a-feature-label-long-enough-started-before")
        check("a stack under the plain cut keeps it",
              bash(root, 'db_project_id "%s"' % old).strip(),
              "myapp-153-a-feature-label-long-enough-started-before"[:40])

        # A second feature: another block.
        b = feature_tree(root, "b")
        write_config(b, cli, "")
        os.symlink(b, os.path.join(root, "registry", "b"))
        bash(root, 'ensure_db "%s"' % b)
        check("another feature, another block",
              state(b).get("db", {}).get("base") not in (None, base), True)

        # A block with something listening in it is skipped.
        c = feature_tree(root, "c")
        write_config(c, cli, "")
        os.symlink(c, os.path.join(root, "registry", "c"))
        held = socket.socket()
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        taken = None
        for guess in range(55000, 56000, 10):
            if guess in (base, state(b)["db"]["base"]):
                continue
            try:
                held.bind(("127.0.0.1", guess + 5))
                held.listen(1)
                taken = guess
                break
            except OSError:
                continue
        bash(root, 'db_base "%s" >/dev/null' % c)
        if shutil.which("ss") and taken is not None:
            check("a block in use is skipped", state(c)["db"]["base"] != taken, True)
        held.close()

        # Switched to the cloud project: the local address must go.
        on_env(a, "dev")
        bash(root, 'ensure_db "%s"' % a)
        check("a feature off localdb drops the env", os.path.exists(envf), False)

        # The main repository never gets a stack of its own.
        repo = os.path.join(root, "repo")
        shutil.rmtree(repo)
        shutil.copytree(b, repo, symlinks=True)
        before = len(calls(root))
        bash(root, 'ensure_db "%s"' % repo)
        check("the main repository is left alone", len(calls(root)), before)

        # A pinned port is the bench: no containers.
        d = feature_tree(root, "d")
        write_config(d, cli, "")
        before = len(calls(root))
        bash(root, 'ensure_db "%s"' % d, {"DEV_PORT": "4000"})
        check("a pinned port starts no stack", len(calls(root)), before)

        # No declaration, no stack. The main repository's config is the
        # fallback for a tree without one, so it goes too.
        os.remove(os.path.join(repo, ".sclaude/config.json"))
        e = feature_tree(root, "e")
        before = len(calls(root))
        bash(root, 'ensure_db "%s"' % e)
        check("an undeclared project starts no stack", len(calls(root)), before)

        # Docker down and nothing to start it with: loud, and no env file.
        out = bash(root, 'docker() { return 1; }; ensure_db "%s"' % b,
                   {"SCLAUDE_DOCKER_START": "off"})
        check("Docker down says so", "Docker is not running" in out, True)
        check("Docker down leaves no env",
              os.path.exists(os.path.join(b, ".sclaude/local/feature", "db.env")), False)

        # Docker down with Docker Desktop to hand: sclaude starts it and
        # waits. The fake launcher leaves the flag the fake docker answers by.
        flag = os.path.join(root, "docker-up")
        exe = os.path.join(root, "Docker Desktop.exe")
        with open(exe, "w") as fh:
            fh.write("#!/usr/bin/env bash\ntouch %s\n" % flag)
        os.chmod(exe, 0o755)
        out = bash(root, 'info() { echo "$*"; }; docker() { [[ -e %s ]]; }; '
                         'docker_ensure && echo ENSURED' % flag,
                   {"SCLAUDE_DOCKER_DESKTOP": exe})
        check("Docker Desktop is started", "starting Docker Desktop" in out, True)
        check("Docker is waited for", "ENSURED" in out and os.path.exists(flag), True)
        os.remove(flag)
        idle = os.path.join(root, "Idle Desktop.exe")
        with open(idle, "w") as fh:
            fh.write("#!/usr/bin/env bash\n")
        os.chmod(idle, 0o755)
        out = bash(root, 'docker() { return 1; }; docker_ensure || echo GAVE-UP',
                   {"SCLAUDE_DOCKER_DESKTOP": idle, "SCLAUDE_DOCKER_WAIT": "2"})
        check("a launcher that never brings it up is given up on",
              "GAVE-UP" in out or "still not up" in out, True)
        # And the failure is remembered: the next call does not wait again.
        out = bash(root, 'docker() { return 1; }; s=$SECONDS; docker_ensure; echo "TOOK $((SECONDS - s))"',
                   {"SCLAUDE_DOCKER_DESKTOP": idle, "SCLAUDE_DOCKER_WAIT": "6"})
        check("a recent failure is not waited for again",
              "not waiting for it again" in out and "TOOK 0" in out, True)
        os.remove(os.path.join(root, "registry", ".docker-failed"))
        # A limit that is not a number falls back to the default rather than
        # breaking the arithmetic and waiting for ever; checked in the source,
        # since the default is two minutes.
        with open(os.path.join(LIB, "featuredb.sh")) as fh:
            src = fh.read()
        check("a bad limit falls back", '[[ "$limit" =~ ^[0-9]+$ ]] || limit=120' in src, True)
        check("the probe is bounded", "timeout 20 docker info" in src, True)
        # Off means nothing was tried, and the warning does not say otherwise.
        out = bash(root, 'docker() { return 1; }; ensure_db "%s"' % b, {"SCLAUDE_DOCKER_START": "off"})
        check("off does not claim a failed start", "could not start it" in out, False)

        # Removing the tree removes the stack, data and all — after the
        # project's teardown, which is told who was copied and when.
        torn = os.path.join(root, "torn")
        with open(os.path.join(b, ".sclaude/config.json")) as fh:
            cfg = json.load(fh)
        cfg["database"]["local"]["teardown"] = (
            'echo "${SCLAUDE_DB_COPIED_USERS:-}|$SCLAUDE_DB_FILLED|$NEXT_PUBLIC_SUPABASE_URL" > %s'
            % torn)
        with open(_cfg(os.path.join(b, ".sclaude/config.json")), "w") as fh:
            json.dump(cfg, fh)
        bash(root, 'state_set "%s/.sclaude/local/feature/state.json" db.filled 2026-09-23T10:00:00Z; ensure_db "%s"'
             % (b, b))
        # A seeded stack: no list of copied people is named at all.
        bash(root, 'db_remove "%s"' % b)
        seen = open(torn).read().strip() if os.path.exists(torn) else ""
        check("a seeded stack's teardown is named no copied list",
              seen.startswith("|2026-09-23T10:00:00Z|http://127.0.0.1:"), True)
        # A copied one: the list is named.
        os.remove(torn)
        bash(root, 'state_set "%s/.sclaude/local/feature/state.json" db.copied true; ensure_db "%s"' % (b, b))
        before = len(calls(root))
        bash(root, 'db_remove "%s"' % b)
        seen = open(torn).read().strip() if os.path.exists(torn) else ""
        check("teardown runs with the copied people, the time and the feature's env",
              seen.startswith(os.path.join(b, ".sclaude/local/feature", "db-copied-users")
                              + "|2026-09-23T10:00:00Z|http://127.0.0.1:"), True)
        check("removal stops without a backup, after the teardown",
              any(c.startswith("stop --no-backup") for c in calls(root)[before:]), True)

        # The regression's local stage sources the file; a deployed one does not.
        write_config(a, cli, "")
        with open(envf, "w") as fh:
            fh.write("X=1\n")
        with open(os.path.join(a, ".sclaude/config.json")) as fh:
            cfg = json.load(fh)
        cfg["commands"] = {"e2e": "npm run test:e2e"}
        with open(_cfg(os.path.join(a, ".sclaude/config.json")), "w") as fh:
            json.dump(cfg, fh)
        local = bash(root, 'source "$LIB/developer.sh"; source "$LIB/regression.sh"; '
                           'regression_command e2e "" "%s"' % a)
        deployed = bash(root, 'source "$LIB/developer.sh"; source "$LIB/regression.sh"; '
                              'regression_command e2e https://x.example "%s"' % a)
        check("the local stage sources the feature's db", ". %s" % envf in local, True)
        check("a deployed stage does not", "db.env" in deployed, False)
        # With the proxy down (a port nothing listens on) the address is the
        # feature's own port, which the state already records as 3100.
        check("the local stage names the feature's server",
              "export E2E_LOCAL_URL=http://localhost:3100 PORT=3100 "
              "SCLAUDE_DEV_URL=http://localhost:3100 SCLAUDE_FEATURE=a;" in local, True)
        check("a deployed stage names no local server", "E2E_LOCAL_URL" in deployed, False)

        # The preview stage runs with the credentials the deployment reads, not
        # with .env.local, which is localdb for the dev server's sake.
        pvf = os.path.join(a, ".env.preview")
        with open(pvf, "w") as fh:
            fh.write("Y=1\n")
        preview = bash(root, 'source "$LIB/developer.sh"; source "$LIB/regression.sh"; '
                             'regression_command e2e https://x.example "%s" preview' % a)
        prod = bash(root, 'source "$LIB/developer.sh"; source "$LIB/regression.sh"; '
                          'regression_command e2e https://x.example "%s" prod' % a)
        local = bash(root, 'source "$LIB/developer.sh"; source "$LIB/regression.sh"; '
                           'regression_command e2e "" "%s" local' % a)
        check("the preview stage sources .env.preview", ". %s" % pvf in preview, True)
        check("production does not", ".env.preview" in prod, False)
        check("the local stage does not", ".env.preview" in local, False)
        check("the local stage still sources its db", ". %s" % envf in local, True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def copy_cases():
    """Filling from the main database, and falling back when that fails."""
    root = tempfile.mkdtemp(prefix="sclaude-copy-")
    try:
        os.makedirs(os.path.join(root, "repo"))
        os.makedirs(os.path.join(root, "registry"))
        cli = os.path.join(root, "stub-supabase")
        with open(cli, "w") as fh:
            fh.write(STUB_CLI)
        os.chmod(cli, 0o755)
        seeded = os.path.join(root, "seeded")
        docker = r"""
docker() {
  case "$1" in
    info) return 0 ;;
    inspect) echo true ;;
    exec)
      if [[ "$*" == *pg_dump* ]]; then
        [[ -f "$DUMP_FAILS" ]] && { echo "pg_dump: connection lost" >&2; return 1; }
        echo "INSERT INTO auth.users VALUES (1) ON CONFLICT DO NOTHING;"
      elif [[ "$*" == *"select id from auth.users"* ]]; then
        echo 11111111-1111-1111-1111-111111111111
      else
        cat >/dev/null
      fi ;;
  esac
}
"""
        for name, fails in (("ok", False), ("broken", True)):
            wt = feature_tree(root, name)
            write_config(wt, cli, "echo run >> %s" % seeded)
            with open(os.path.join(wt, ".sclaude/config.json")) as fh:
                cfg = json.load(fh)
            cfg["database"]["local"]["copyFromMain"] = True
            with open(_cfg(os.path.join(wt, ".sclaude/config.json")), "w") as fh:
                json.dump(cfg, fh)
            os.symlink(wt, os.path.join(root, "registry", name))
            flag = os.path.join(root, "dump-fails")
            if fails:
                open(flag, "w").close()
            elif os.path.exists(flag):
                os.remove(flag)
            bash(root, docker + 'ensure_db "%s"' % wt, {"DUMP_FAILS": flag})
        ok, broken = os.path.join(root, "ok"), os.path.join(root, "broken")
        check("a good copy is recorded", state(ok).get("db", {}).get("copied"), True)
        check("a good copy lists the people it brought",
              open(os.path.join(ok, ".sclaude/local/feature", "db-copied-users")).read().strip(),
              "11111111-1111-1111-1111-111111111111")
        check("a failed dump is not recorded as a copy",
              state(broken).get("db", {}).get("copied"), None)
        check("a failed dump falls back to the seed",
              os.path.exists(seeded) and open(seeded).read().count("run") == 1, True)
        check("and the database is ready from the seed",
              state(broken).get("db", {}).get("ready"), True)
        # Rows that do not fit: the warning names their tables and says the
        # main database is behind, when it is.
        unfit = r"""
docker() {
  case "$*" in
    *schema_migrations*)
      echo 0001; echo 0002
      [[ "$*" == *supabase_db_myapp\ * ]] || { echo 0003; echo 0004; } ;;
  esac
}
"""
        log = "\n".join(
            ['psql:<stdin>:1: ERROR:  null value in column "origin" of relation "activities" violates not-null constraint'] * 2
            + ['psql:<stdin>:9: ERROR:  new row for relation "tiers" violates check constraint "tiers_limits_shape"'])
        out = bash(root, unfit + 'db_error_tables <<<%s; echo; db_warn_main_behind supabase_db_myapp supabase_db_feature'
                   % shlex.quote(log))
        check("rows that did not fit are counted by table",
              out.splitlines()[0], "2 in public.activities, 1 in public.tiers")
        check("a main database behind the feature is named",
              "2 migration(s) behind this feature's (it stops at 0002)" in out, True)
        same = bash(root, 'docker() { echo 0001; }; db_warn_main_behind a b')
        check("a main database up to date is not warned about", same.strip(), "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def same_schema_cases():
    """A copy loads into main's schema, emptied, and the feature's migrations
    come after: reference rows with generated ids differ between two stacks,
    and kept, main's rows pointed at the feature's absent ones."""
    root = tempfile.mkdtemp(prefix="sclaude-schema-")
    try:
        os.makedirs(os.path.join(root, "repo"))
        os.makedirs(os.path.join(root, "registry"))
        cli = os.path.join(root, "stub-supabase")
        with open(cli, "w") as fh:
            fh.write(STUB_CLI)
        os.chmod(cli, 0o755)
        dlog = os.path.join(root, "docker.log")
        docker = r"""
docker() {
  echo "$*" >> "$DOCKER_LOG"
  case "$*" in
    info*) return 0 ;;
    inspect*) echo true ;;
    *pg_dump*) echo "INSERT INTO public.t VALUES (1) ON CONFLICT DO NOTHING;" ;;
    *schema_migrations*)
      if [[ "$*" == *supabase_db_myapp\ * ]]; then printf '%s\n' $MAIN_HAS
      else echo 0001; echo 0002; fi ;;
    *string_agg*) echo "public.a, public.b" ;;
    *"select id from auth.users"*) echo 11111111-1111-1111-1111-111111111111 ;;
    *) cat >/dev/null ;;
  esac
}
"""
        for name, main_has in (("behind", "0001"), ("foreign", "0001 0009")):
            wt = feature_tree(root, name)
            for f in ("0001_a.sql", "0002_b.sql"):
                open(os.path.join(wt, "supabase", "migrations", f), "w").close()
            write_config(wt, cli, "true")
            with open(os.path.join(wt, ".sclaude/config.json")) as fh:
                cfg = json.load(fh)
            cfg["database"]["local"]["copyFromMain"] = True
            with open(os.path.join(wt, ".sclaude/config.json"), "w") as fh:
                json.dump(cfg, fh)
            os.symlink(wt, os.path.join(root, "registry", name))
            for f in (dlog, os.path.join(root, "cli.log")):
                if os.path.exists(f):
                    os.remove(f)
            bash(root, docker + 'ensure_db "%s"' % wt, {"DOCKER_LOG": dlog, "MAIN_HAS": main_has})
            ran = [c for c in calls(root) if not c.startswith("has ")]
            loaded = open(dlog).read()
            if name == "behind":
                reset = [c for c in ran if c.startswith("db reset")]
                check("a feature ahead of main is set back to main's last migration",
                      len(reset) == 1 and "--version 0001 --no-seed" in reset[0], True)
                check("public's tables are emptied before main's rows go in",
                      "-c TRUNCATE public.a, public.b; -f -" in loaded, True)
                after = ran[ran.index(reset[0]) + 1:] if reset else []
                check("the feature's migrations apply after the load",
                      any(c.startswith("migration up") for c in after), True)
                check("and the copy is recorded", state(wt).get("db", {}).get("copied"), True)
            else:
                check("a main database with a migration the tree lacks is not reset to",
                      [c for c in ran if c.startswith("db reset")], [])
                check("nor its rows loaded over an emptied schema", "TRUNCATE" in loaded, False)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main_up_cases():
    """The main local stack takes main's migrations — what is on main, not
    what the main checkout has checked out."""
    root = tempfile.mkdtemp(prefix="sclaude-mainup-")
    try:
        repo = os.path.join(root, "repo")
        os.makedirs(os.path.join(repo, "supabase", "migrations"))
        cli = os.path.join(root, "stub-supabase")
        with open(cli, "w") as fh:
            fh.write(STUB_CLI)
        os.chmod(cli, 0o755)
        with open(os.path.join(repo, "supabase", "config.toml"), "w") as fh:
            fh.write(CONFIG)
        for f in ("0001_a.sql", "0002_b.sql"):
            open(os.path.join(repo, "supabase", "migrations", f), "w").close()
        with open(_cfg(os.path.join(repo, ".sclaude/config.json")), "w") as fh:
            json.dump({"database": {"local": {"environment": "localdb", "cli": cli}}}, fh)
        git = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.email=t@t",
                                         "-c", "user.name=t"] + list(a), capture_output=True)
        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-qm", "base")
        # The main tree on a branch with a migration main does not have.
        git("checkout", "-qb", "other")
        open(os.path.join(repo, "supabase", "migrations", "0003_c.sql"), "w").close()
        git("add", "-A")
        git("commit", "-qm", "other")
        docker = r"""
docker() {
  case "$*" in
    inspect*) echo "$RUNNING" ;;
    *schema_migrations*) printf '%s\n' $MAIN_HAS ;;
  esac
}
"""
        out = bash(root, docker + "db_main_up", {"RUNNING": "true", "MAIN_HAS": "0001"})
        ran = calls(root)
        check("main's new migration is applied to the main stack",
              any(c.startswith("migration up --workdir") for c in ran), True)
        check("it is said, with the count", "applying main's 1 new migration(s)" in out, True)
        check("the workdir holds main's migrations, not the checked-out branch's",
              [c for c in ran if c.startswith("has ")], ["has 0001_a.sql", "has 0002_b.sql"])
        os.remove(os.path.join(root, "cli.log"))
        bash(root, docker + "db_main_up", {"RUNNING": "true", "MAIN_HAS": "0001 0002"})
        check("a main stack up to date is left alone", calls(root), [])
        bash(root, docker + "db_main_up", {"RUNNING": "false", "MAIN_HAS": "0001"})
        check("a main stack that is not running is left alone", calls(root), [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def shared_cases():
    """The warning for schema work on a shared cloud project."""
    root = tempfile.mkdtemp(prefix="sclaude-shared-")
    try:
        os.makedirs(os.path.join(root, "repo"))
        wt = feature_tree(root, "s", env="dev")
        with open(_cfg(os.path.join(wt, ".sclaude/config.json")), "w") as fh:
            json.dump({"environments": ENVIRONMENTS,
                       "database": {"migrations": "supabase/migrations",
                                    "local": {"environment": "localdb"}}}, fh)
        git = lambda *a: subprocess.run(["git", "-C", wt] + list(a), capture_output=True)
        git("init", "-q", "-b", "main")
        git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        out = bash(root, 'db_shared_warning "%s"' % wt)
        check("no migration, no warning", out.strip(), "")
        with open(os.path.join(wt, "supabase", "migrations", "0062_x.sql"), "w") as fh:
            fh.write("select 1;\n")
        out = bash(root, 'db_shared_warning "%s"' % wt)
        check("a migration on the shared project is warned about",
              'against "dev"' in out and "SCLAUDE_ENV=localdb" in out, True)
        on_env(wt, "localdb")
        out = bash(root, 'db_shared_warning "%s"' % wt)
        check("the same migration on localdb is fine", out.strip(), "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    config_cases()
    env_cases()
    ensure_cases()
    copy_cases()
    same_schema_cases()
    main_up_cases()
    shared_cases()
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
