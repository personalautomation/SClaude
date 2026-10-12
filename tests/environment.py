#!/usr/bin/env python3
#
# A bench for the choice that replaced a hardcoded "dev".
#
# `force_dev` used to name one database three times over, and that was correct
# while every feature on every machine worked against the same shared project.
# It stopped being correct when the product grew a local Supabase stack: a
# developer applying migrations wants a database nobody else is reading, and a
# developer working on the interface has no reason to install Docker for one.
#
# What replaced it is environment.sh, and what makes it worth a bench is that
# most of its failures are quiet. A wrong answer here does not crash: it points
# a worktree at somebody else's database, or at production, and the dev server
# comes up looking exactly as it should. So these run the real functions against
# a real config/environments.json and assert on what they return.
#
# The cases that matter, and what each one would look like if it broke:
#
#   protected environments        prod offered as a choice, or accepted from
#                                 $SCLAUDE_ENV. A feature aimed at production.
#   an unknown saved name         a machine that worked on two products carries
#                                 one's answer into the other, silently.
#   no answer available           `sclaude status` (no terminal, 25s timeout in
#                                 the bot) hangs on a question nobody sees.
#   a ref-less environment        ensure_linked waits for a project-ref that is
#                                 never coming and warns about it for ever.
#
# Run it with: python3 tests/environment.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


def run(body, env=None, home=None, cwd=None, with_worktree=False):
    """Run a snippet with environment.sh and a stub ui.sh loaded.

    ui.sh is stubbed rather than sourced: `ask` reads a terminal, and the whole
    point of several cases below is that there isn't one.
    """
    # worktree.sh is sourced only where a case needs force_env: it pulls in
    # DEV_PORT and other module-level state that the environment-only cases
    # have no business carrying.
    extra = 'source "%s/worktree.sh"\n' % LIB if with_worktree else ""
    script = """
set -uo pipefail
info() { :; }
warn() { :; }
ask() { return 1; }
REPO="%s"
source "%s/project.sh"
source "%s/environment.sh"
%s%s
""" % (os.path.dirname(LIB), LIB, LIB, extra, body)
    full = dict(os.environ)
    full.pop("SCLAUDE_ENV", None)
    if home:
        full["HOME"] = home
    if env:
        full.update(env)
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=full, cwd=cwd)
    return done.stdout.strip()


# How a product tells sclaude about its environments (.sclaude/config.json).
def ref_of(name):
    """A 20-character project ref, as Supabase's are, made from a short name."""
    return (name + "0" * 20)[:20]


def env_url(spec):
    ref = spec.get("ref")
    return "https://%s.supabase.co" % ref_of(ref) if ref else "http://127.0.0.1:54321"


def project(tmp, environments):
    """A worktree whose .sclaude/config.json names each environment's .env file.

    The fixtures below are written as {name: {ref, confirm, siteUrl}}, the
    facts a product used to keep in a file of its own; here they become what
    sclaude reads now. `confirm` is `protected`, a siteUrl given as None is a
    `deployed` environment, and the ref becomes the Supabase URL in the
    environment's .env file.

    `tmp` is the directory the worktree is made *in*, so two fixtures in one
    run need two of them.
    """
    wt = os.path.join(tmp, "wt")
    os.makedirs(os.path.join(wt, ".sclaude"), exist_ok=True)
    config = {}
    for name, spec in environments.items():
        entry = {"env": ".env." + name}
        if spec.get("confirm"):
            entry["protected"] = True
        if "siteUrl" in spec:
            if spec["siteUrl"] is None:
                entry["deployed"] = True
            else:
                entry["siteUrl"] = spec["siteUrl"]
        config[name] = entry
        with open(os.path.join(wt, ".env." + name), "w") as fh:
            fh.write("NEXT_PUBLIC_SUPABASE_URL=%s\n" % env_url(spec))
    with open(os.path.join(wt, ".sclaude", "config.json"), "w") as fh:
        json.dump({"environments": config}, fh)
    return wt


def on_env(wt, name, linked=None):
    """Put a tree on an environment: .env.local, and the CLI's link."""
    link = os.path.join(wt, ".env.local")
    if os.path.lexists(link):
        os.remove(link)
    if name:
        os.symlink(".env." + name, link)
    ref = os.path.join(wt, "supabase", ".temp", "project-ref")
    os.makedirs(os.path.dirname(ref), exist_ok=True)
    if linked:
        with open(ref, "w") as fh:
            fh.write(linked)
    elif os.path.exists(ref):
        os.remove(ref)


# Shaped like the real config/environments.json, `siteUrl` included: it is what
# says whether a developer can work against an environment from here. `preview`
# having none is the case this fixture exists to carry — it is unprotected and
# perfectly writable, and it is still not somewhere a local dev server and a
# local browser suite belong, because it names deployments rather than a machine.
FOUR = {
    "prod": {"ref": "cloudprod", "confirm": True,
             "siteUrl": "https://example.com"},
    "preview": {"ref": "cloudshared", "confirm": False,
                "siteUrl": None},
    "dev": {"ref": "cloudshared", "confirm": False,
            "siteUrl": "http://localhost:3000"},
    "localdb": {"ref": None, "confirm": False,
                "siteUrl": "http://localhost:3000"},
}


def main():
    tmp = tempfile.mkdtemp(prefix="sclaude-env-")
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    try:
        wt = project(tmp, FOUR)

        # --- what the project offers -------------------------------------
        check("every declared name is listed",
              sorted(run('environment_names "%s"' % wt).split()),
              ["dev", "localdb", "preview", "prod"])

        # The two a feature may be pointed at, and the two reasons the others
        # are absent: prod is protected, preview is not somewhere a local dev
        # server and a browser suite can run. Offering preview would have sent
        # a cycle into a regression that refuses to start, reporting it as a
        # failed step rather than a wrong choice.
        check("only the locally runnable, unprotected names are offered",
              sorted(run('environment_choices "%s"' % wt).split()),
              ["dev", "localdb"])

        check("a deployed-only environment is not runnable here",
              run('environment_runnable "%s" preview && echo yes || echo no' % wt),
              "no")

        check("a loopback environment is runnable",
              run('environment_runnable "%s" localdb && echo yes || echo no' % wt),
              "yes")

        check("an unknown name is not runnable",
              run('environment_runnable "%s" nosuch && echo yes || echo no' % wt),
              "no")

        check("prod reads as protected",
              run('environment_protected "%s" prod && echo yes || echo no' % wt),
              "yes")

        check("dev reads as unprotected",
              run('environment_protected "%s" dev && echo yes || echo no' % wt),
              "no")

        # An unknown name is protected, not permitted. This is the direction
        # that matters: the other way round, a typo would aim a feature at a
        # database nobody has vetted.
        check("an unknown name reads as protected",
              run('environment_protected "%s" nosuch && echo yes || echo no' % wt),
              "yes")

        # A project that does not do environments at all: every answer is
        # silence, and no caller may read that as permission.
        bare = os.path.join(tmp, "bare")
        os.makedirs(bare, exist_ok=True)
        check("a project with no config offers nothing",
              run('environment_choices "%s"' % bare), "")
        check("a project with no config protects everything",
              run('environment_protected "%s" dev && echo yes || echo no' % bare),
              "yes")

        # ...and force_env must not turn that into a warning.
        #
        # `environment_protected` answering "protected" for an unreadable config
        # is the right direction for a permission check and the wrong one for
        # "is this worktree somewhere alarming": a project with an environments script and
        # no config/environments.json is one that does not do environments at
        # all. It used to warn that the tree was on a protected environment and
        # return 1 — which `ensure_dev` reads as `switched=1` and answers by
        # tearing down a healthy dev server on every single step.
        noconf = os.path.join(tmp, "noconf")
        os.makedirs(noconf, exist_ok=True)

        check("a project without environments is left alone, quietly",
              run('force_env "%s" >/dev/null 2>&1; echo "rc=$?"' % noconf,
                  home=home, with_worktree=True),
              "rc=0")

        # A project that declares environments but gives none of them a siteUrl
        # is not saying "none of these are runnable" — it is saying nothing
        # about addresses. Reading the absent field as a refusal emptied the
        # list, and force_env then stopped switching at all, including away from
        # a prod environment `db:promote` had left behind.
        nosite_dir = os.path.join(tmp, "nosite")
        os.makedirs(nosite_dir, exist_ok=True)
        nosite = project(nosite_dir,
                         {"dev": {"ref": "d", "confirm": False},
                          "prod": {"ref": "p", "confirm": True}})
        check("a config that never uses siteUrl still offers its environments",
              sorted(run('environment_choices "%s"' % nosite).split()),
              ["dev"])

        # --- which ones have a hosted project ----------------------------
        check("a cloud environment has a ref",
              run('environment_has_ref "%s" dev && echo yes || echo no' % wt),
              "yes")

        # The whole reason ensure_linked had to learn the difference: waiting
        # for a project-ref that is never coming.
        check("a local stack has no ref",
              run('environment_has_ref "%s" localdb && echo yes || echo no' % wt),
              "no")

        # --- $SCLAUDE_ENV -------------------------------------------------
        check("SCLAUDE_ENV is taken",
              run('environment_choose "%s"' % wt,
                  env={"SCLAUDE_ENV": "localdb"}, home=home),
              "localdb")

        # The one rule this file has, and the variable does not override it.
        check("SCLAUDE_ENV may not name prod",
              run('environment_choose "%s"' % wt,
                  env={"SCLAUDE_ENV": "prod"}, home=home),
              "")

        # The variable is a convenience, not a way round either rule. Set once
        # in a profile, it would otherwise point every feature on the machine at
        # an environment whose own regression will not run.
        check("SCLAUDE_ENV may not name a deployed-only environment",
              run('environment_choose "%s"' % wt,
                  env={"SCLAUDE_ENV": "preview"}, home=home),
              "")

        # An explicit name is not saved: it is a per-invocation override, and
        # writing it down would make a one-off `SCLAUDE_ENV=dev sclaude …`
        # change the machine's answer for good.
        saved = os.path.join(home, ".claude", "sclaude", "environment")
        check("SCLAUDE_ENV does not overwrite the saved answer",
              os.path.exists(saved), False)

        # --- the saved answer ---------------------------------------------
        os.makedirs(os.path.dirname(saved), exist_ok=True)
        with open(saved, "w") as fh:
            fh.write("localdb\n")

        check("a saved answer is used without asking",
              run('environment_choose "%s"' % wt, home=home), "localdb")

        # Every offered name, not just one — and this is why.
        #
        # The check inside environment_saved was once
        # `environment_choices | grep -qxF "$saved"`. `grep -q` exits on its
        # first match, the producer dies of SIGPIPE, and `set -o pipefail`
        # (bin/sclaude) turns that into a failed pipeline — so a saved answer
        # was accepted only when it was the *last* line of the list. Every
        # other name was silently discarded and the machine asked again on
        # every step, which is exactly the promise this file makes.
        #
        # The assertion above missed it: `localdb` is the last name the list
        # offers, which is the one case the broken version got right. `dev`
        # comes first and is the one that proves the fix.
        #
        # Only names the list actually offers belong here — `preview` is
        # excluded by environment_runnable, so a saved `preview` is *meant* to
        # be discarded and would be testing the wrong rule.
        for name in ("dev", "localdb"):
            with open(saved, "w") as fh:
                fh.write(name + "\n")
            check("a saved %s survives wherever it sits in the list" % name,
                  run('environment_choose "%s"' % wt, home=home), name)

        # A machine that worked on another product carries that product's
        # answer in this same file. It must not leak across.
        with open(saved, "w") as fh:
            fh.write("staging\n")
        check("a saved name this project lacks is discarded",
              run('environment_choose "%s"' % wt, home=home), "")

        # Nor may a saved answer smuggle in production — the file is editable
        # by hand, and environment_choices is what validates it.
        with open(saved, "w") as fh:
            fh.write("prod\n")
        check("a saved answer may not name prod",
              run('environment_choose "%s"' % wt, home=home), "")

        os.remove(saved)

        # --- nobody to ask -------------------------------------------------
        #
        # `ask` fails when there is no terminal and no channel. That is the
        # ordinary condition of `sclaude status`, which the bot runs with a
        # 25-second timeout: the answer has to be "nothing", promptly, rather
        # than a question nobody will ever see.
        check("no answer and no terminal yields nothing",
              run('environment_choose "%s"' % wt, home=home), "")

        # --- one choice is not a question ----------------------------------
        single = project(os.path.join(tmp, "single"),
                         {"prod": {"ref": "p", "confirm": True,
                                   "siteUrl": "https://example.com"},
                          "dev": {"ref": "d", "confirm": False,
                                  "siteUrl": "http://localhost:3000"}})
        check("a single unprotected environment is taken without asking",
              run('environment_choose "%s"' % single, home=home), "dev")
        check("and it is saved",
              open(saved).read().strip() if os.path.exists(saved) else "",
              "dev")

        # --- the hook's half ------------------------------------------------
        #
        # `supabase db push` used to be allowed on the literal "dev" and
        # nowhere else, so it refused the two environments that came later while
        # explaining itself in terms of prod — the same shape of mistake the
        # comment above DB_PUSH already records once.
        #
        # Driven through stdin like tests/hooks.py rather than by importing:
        # forbidden-commands.py runs at module level and exits, so there is no
        # importing it. That is the better test anyway — what matters is whether
        # the command is refused, not which function decided.
        hooks = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "sclaude", "hooks")
        forbidden = os.path.join(hooks, "forbidden-commands.py")

        # The hook reads where the tree is from its .env.local, and holds the
        # Supabase CLI's link to it: `supabase db push` obeys the link, so a tree
        # on a local stack with the CLI still linked to prod was once allowed
        # to push straight into production.
        os.makedirs(os.path.join(wt, ".sclaude", "team"), exist_ok=True)
        with open(os.path.join(wt, ".sclaude", "team", "policy.json"), "w") as fh:
            json.dump({"integrations": ["supabase"]}, fh)

        def db_push_denied(env_name, linked="own"):
            """Whether the hook refuses `supabase db push` on this environment.

            `linked` is the CLI's link: "own" for the environment's own project
            (none for a local one), or a ref of some other project.
            """
            spec = FOUR.get(env_name or "", {})
            own = ref_of(spec["ref"]) if spec.get("ref") else None
            on_env(wt, env_name if env_name in FOUR else None,
                   own if linked == "own" else linked)
            payload = {"tool_name": "Bash",
                       "tool_input": {"command": "npx supabase db push"}}
            done = subprocess.run(
                [sys.executable, forbidden, "--step", "code", "--root", wt],
                input=json.dumps(payload), capture_output=True, text=True,
                cwd=wt, env={**os.environ, "CLAUDE_PROJECT_DIR": wt})
            # A refusal is a JSON decision on stdout, with exit 0 either way —
            # allowing is silence.
            if not done.stdout.strip():
                return False
            try:
                decision = json.loads(done.stdout)
            except ValueError:
                return False
            out = decision.get("hookSpecificOutput") or {}
            return out.get("permissionDecision") == "deny"

        for name, want in [("dev", False), ("localdb", False),
                           ("preview", False), ("prod", True),
                           ("nosuch", True), (None, True)]:
            label = name if name else "unresolvable"
            check("hook: db push on %s denied -> %s" % (label, want),
                  db_push_denied(name), want)

        # The link and .env.local disagree: not settled, and refused.
        check("hook: localdb with the CLI linked to prod is refused",
              db_push_denied("localdb", linked=ref_of("cloudprod")), True)
        check("hook: dev with the CLI unlinked is refused",
              db_push_denied("dev", linked=None), True)
        on_env(wt, None)

        # --- a switch that fails leaves no server on production -----------
        #
        # The product's switch command failed and the tree stayed on prod.
        # force_env used to answer 1, "switched", and ensure_dev restarted the
        # dev server right there. It is 2 now, and no server runs.
        def failing(where, current):
            """force_env on a tree on `current`, told to be on dev, whose
            .env.dev is missing so the switch cannot happen."""
            wt_dir = project(where, {"dev": {"ref": "d", "confirm": False},
                                     "prod": {"ref": "p", "confirm": True}})
            on_env(wt_dir, current)
            os.remove(os.path.join(wt_dir, ".env.dev")) if current != "dev" else None
            return run('force_env "%s" >/dev/null 2>&1; echo "rc=$?"' % wt_dir,
                       env={"SCLAUDE_ENV": "dev"}, home=home, with_worktree=True)

        os.makedirs(os.path.join(tmp, "stuck"))
        check("a failed switch off prod keeps the server off", failing(os.path.join(tmp, "stuck"), "prod"),
              "rc=2")
        # A failing switch is never run for a tree already where it should be.
        os.makedirs(os.path.join(tmp, "landed"))
        check("a tree already on its environment is left alone", failing(os.path.join(tmp, "landed"), "dev"),
              "rc=0")
        # --- switching, and what is read from the files ------------------
        #
        # sclaude switches a tree itself now: .env.local to the file, and the
        # Supabase CLI linked to the project that file's URL names, with the
        # password from its database URL. A stub stands in for the CLI.
        sw = project(os.path.join(tmp, "sw"), {"localdb": {"ref": None},
                                                 "dev": {"ref": "cloudshared"}})
        os.makedirs(os.path.join(sw, "supabase", ".temp"))
        open(os.path.join(sw, "supabase", "config.toml"), "w").close()
        with open(os.path.join(sw, ".env.dev"), "a") as fh:
            fh.write("POSTGRES_URL_NON_POOLING=postgresql://u:s%40cret@db:5432/postgres\n")
        calls = os.path.join(tmp, "cli-calls")
        stub = os.path.join(tmp, "stub-cli")
        with open(stub, "w") as fh:
            fh.write('#!/bin/sh\necho "$*" >> %s\n'
                     '[ "$1" = link ] && mkdir -p supabase/.temp && echo "$3" > supabase/.temp/project-ref\n'
                     'exit 0\n' % calls)
        os.chmod(stub, 0o755)
        on_env(sw, "localdb")
        os.makedirs(os.path.join(sw, ".next"))
        out = run('db_cli() { echo %s; }; environment_switch "%s" dev && echo ok; '
                  'environment_current "%s"; environment_settled "%s"' % (stub, sw, sw, sw))
        check("switch: done and settled", out.split(), ["ok", "dev", "dev"])
        check("switch: the CLI was linked with the URL's password",
              open(calls).read().strip(), "link --project-ref %s -p s@cret" % ref_of("cloudshared"))
        check("switch: a build of the old file is gone", os.path.exists(os.path.join(sw, ".next")), False)
        out = run('db_cli() { echo %s; }; environment_switch "%s" localdb && echo ok; '
                  'environment_settled "%s"' % (stub, sw, sw))
        check("switch: a local one leaves no link behind", out.split(), ["ok", "localdb"])
        check("switch: to a file that is not there fails",
              run('environment_switch "%s" nosuch && echo ok || echo no' % sw), "no")

        # A snapshot puts a tree back exactly, including a .env.local that is
        # a plain file of the person's own: no name could switch back to that,
        # and a rollback left the tree on production.
        local = os.path.join(sw, ".env.local")
        os.remove(local)
        with open(local, "w") as fh:
            fh.write("MINE=1\n")
        with open(os.path.join(sw, "supabase", ".temp", "project-ref"), "w") as fh:
            fh.write("oldref\n")
        # A switch alone leaves a file of the person's own where it is.
        check("switch: a file of its own is left alone",
              (run('environment_switch "%s" dev >/dev/null 2>&1 && echo switched || echo kept' % sw),
               open(local).read()), ("kept", "MINE=1\n"))
        out = run('db_cli() { echo %s; }; s="$(environment_snapshot "%s")"; '
                  'environment_switch "%s" dev --over-file >/dev/null; environment_current "%s"; '
                  'environment_restore "%s" "$s" && echo restored; [ -e "$s" ] || echo gone'
                  % (stub, sw, sw, sw, sw))
        check("snapshot: switched, then restored", out.split(), ["dev", "restored", "gone"])
        check("snapshot: the own file is back",
              (os.path.islink(local), open(local).read()), (False, "MINE=1\n"))
        check("snapshot: the CLI link is back",
              open(os.path.join(sw, "supabase", ".temp", "project-ref")).read(), "oldref\n")
        on_env(sw, "localdb")
        out = run('s="$(environment_snapshot "%s")"; environment_switch "%s" dev >/dev/null 2>&1; '
                  'environment_restore "%s" "$s"; environment_current "%s"' % (sw, sw, sw, sw))
        check("snapshot: a link is back", out, "localdb")

        # The orchestrator reads protection from main as well: a tree that
        # drops "protected" from prod does not make it runnable. And
        # main-config tells no config (3) from one it cannot read (2).
        guarded = os.path.join(tmp, "guarded")
        os.makedirs(os.path.join(guarded, ".sclaude"))
        cfg = os.path.join(guarded, ".sclaude", "config.json")
        with open(cfg, "w") as fh:
            json.dump({"environments": {"prod": {"env": ".env.prod", "protected": True}}}, fh)
        genv = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q", "-b", "main", guarded], check=True)
        subprocess.run(["git", "-C", guarded, "add", "-A"], check=True)
        subprocess.run(["git", "-C", guarded, "commit", "-qm", "c"], check=True, env=genv)
        subprocess.run(["git", "-C", guarded, "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)
        with open(cfg, "w") as fh:
            json.dump({"environments": {"prod": {"env": ".env.prod"}}}, fh)
        envs_py = os.path.join(LIB, "envs.py")
        check("protected: read from main, not the tree",
              subprocess.run([sys.executable, envs_py, "protected", guarded, "prod"]).returncode, 0)
        # Nor does a tree that maps a name to production's file get it linked.
        with open(cfg, "w") as fh:
            json.dump({"environments": {"prod": {"env": ".env.prod", "protected": True},
                                        "dev": {"env": ".env.prod"}}}, fh)
        check("file: a name's file is main's",
              subprocess.run([sys.executable, envs_py, "file", guarded, "dev"],
                             capture_output=True, text=True).stdout.strip(), "")
        subprocess.run(["git", "-C", guarded, "update-ref", "-d", "refs/remotes/origin/main"], check=True)
        with open(cfg, "w") as fh:
            fh.write("{,")
        check("main-config: unreadable is 2",
              subprocess.run([sys.executable, envs_py, "main-config", guarded],
                             capture_output=True).returncode, 2)
        os.remove(cfg)
        check("main-config: none is 3",
              subprocess.run([sys.executable, envs_py, "main-config", guarded],
                             capture_output=True).returncode, 3)

        # Files that share a name in folders of their own: the exact path
        # decides, and production is not read as the first of them.
        same = os.path.join(tmp, "same")
        for env_name in ("dev", "prod"):
            os.makedirs(os.path.join(same, "envs", env_name))
            open(os.path.join(same, "envs", env_name, ".env"), "w").close()
        os.makedirs(os.path.join(same, ".sclaude"))
        with open(os.path.join(same, ".sclaude", "config.json"), "w") as fh:
            json.dump({"environments": {"dev": {"env": "envs/dev/.env"},
                                        "prod": {"env": "envs/prod/.env", "protected": True}}}, fh)
        os.symlink(os.path.join(same, "envs", "prod", ".env"), os.path.join(same, ".env.local"))
        check("current: a shared basename is told by its path",
              run('environment_current "%s"' % same), "prod")
        # A new worktree gets those files too: untracked, it would have none.
        linked = os.path.join(tmp, "same-wt")
        os.makedirs(linked)
        run('REPO="%s"; link_env "%s"' % (same, linked), with_worktree=True)
        check("link_env: files in folders are linked",
              [os.path.realpath(os.path.join(linked, "envs", n, ".env")) for n in ("dev", "prod")],
              [os.path.realpath(os.path.join(same, "envs", n, ".env")) for n in ("dev", "prod")])

        check("value: read from the environment's file",
              run('environment_value "%s" dev POSTGRES_URL_NON_POOLING' % sw),
              "postgresql://u:s%40cret@db:5432/postgres")
        # No file says, and no terminal to ask at: nothing, rather than a guess.
        check("value: none without a terminal",
              run('environment_value "%s" dev NOT_THERE || echo none' % sw), "none")

        wd = open(os.path.join(os.path.dirname(LIB), "lib", "worktree.sh")).read()
        ensure = wd[wd.index("\nensure_dev() {"):]
        check("ensure_dev starts nothing on rc 2",
              ensure.index("env_rc == 2") < ensure.index("feature_port"), True)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("%d failure(s)" % len(failures))
        return 1
    print("all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
