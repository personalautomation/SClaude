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
source "%s/environment.sh"
%s%s
""" % (os.path.dirname(LIB), LIB, extra, body)
    full = dict(os.environ)
    full.pop("SCLAUDE_ENV", None)
    if home:
        full["HOME"] = home
    if env:
        full.update(env)
    done = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env=full, cwd=cwd)
    return done.stdout.strip()


def project(tmp, environments):
    """A worktree with a config/environments.json and nothing else.

    `tmp` is the directory the worktree is made *in*, so two fixtures in one
    run need two of them — they would otherwise be the same tree, and the
    second would quietly rewrite the first's config.
    """
    wt = os.path.join(tmp, "wt")
    os.makedirs(os.path.join(wt, "config"), exist_ok=True)
    with open(os.path.join(wt, "config", "environments.json"), "w") as fh:
        json.dump(environments, fh)
    return wt


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
        # "is this worktree somewhere alarming": a project with an env-guard and
        # no config/environments.json is one that does not do environments at
        # all. It used to warn that the tree was on a protected environment and
        # return 1 — which `ensure_dev` reads as `switched=1` and answers by
        # tearing down a healthy dev server on every single step.
        noconf = os.path.join(tmp, "noconf")
        os.makedirs(os.path.join(noconf, "scripts", "lib"), exist_ok=True)
        with open(os.path.join(noconf, "scripts", "env.mjs"), "w") as fh:
            fh.write("")
        with open(os.path.join(noconf, "scripts", "lib", "env-guard.mjs"), "w") as fh:
            fh.write('if (process.argv[2] === "name") console.log("dev");\n')

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

        # The hook asks the project where it is by running env-guard.mjs, so the
        # fixture needs one.
        #
        # The stand-in answers `settled` and refuses everything else, which is
        # what the real one does for an unknown subcommand. That distinction is
        # the point: the hook used to ask for `name`, which answers from
        # .env.local alone and says nothing about the Supabase CLI's own link —
        # so a tree on a local stack with the CLI still linked to prod was
        # allowed to `db push` straight into production. A stub that answered
        # anything it was asked would pass either way and prove nothing.
        guard_dir = os.path.join(wt, "scripts", "lib")
        os.makedirs(guard_dir, exist_ok=True)
        guard = os.path.join(guard_dir, "env-guard.mjs")

        def db_push_denied(env_name, subcommand="settled"):
            """Whether the hook refuses `supabase db push` on this environment.

            `subcommand` is the one the stub will answer; anything else exits
            non-zero. Passing "name" simulates an env-guard too old to know
            about `settled`.
            """
            with open(guard, "w") as fh:
                if env_name is None:
                    # No answer at all: the guard exits non-zero, which
                    # active_environment reports as None.
                    fh.write("process.exit(1);\n")
                else:
                    fh.write(
                        "const want = %s;\n"
                        "if (process.argv[2] !== want) process.exit(2);\n"
                        "console.log(%s);\n"
                        % (json.dumps(subcommand), json.dumps(env_name))
                    )
            payload = {"tool_name": "Bash",
                       "tool_input": {"command": "npx supabase db push"}}
            done = subprocess.run(
                [sys.executable, forbidden, "--step", "code"],
                input=json.dumps(payload), capture_output=True, text=True,
                cwd=wt, env={**os.environ, "CLAUDE_PROJECT_DIR": wt})
            # A refusal is a JSON decision on stdout, with exit 0 either way —
            # allowing is silence. Reading the exit code instead would call
            # every run an allow.
            if not done.stdout.strip():
                return False
            try:
                decision = json.loads(done.stdout)
            except ValueError:
                return False
            out = decision.get("hookSpecificOutput") or {}
            return out.get("permissionDecision") == "deny"

        # The stand-in is JavaScript, and without node the hook cannot ask the
        # project anything — so it refuses every push, which is the safe answer
        # and makes the "allowed" cases unprovable here. They are skipped on a
        # machine without node rather than reported as the hook's fault.
        have_node = shutil.which("node") is not None
        for name, want in [("dev", False), ("localdb", False),
                           ("preview", False), ("prod", True),
                           ("nosuch", True), (None, True)]:
            label = name if name else "unresolvable"
            if not want and not have_node:
                print("  SKIP  hook: db push on %s (no node)" % label)
                continue
            check("hook: db push on %s denied -> %s" % (label, want),
                  db_push_denied(name), want)

        # An env-guard that only knows `name` is one from before the link was
        # being checked at all. Its silence is not permission: the hook asks for
        # `settled`, gets a non-zero exit, and refuses — which is the same
        # answer it gives for an environment it cannot identify.
        check("hook: an env-guard without `settled` is refused",
              db_push_denied("localdb", subcommand="name"), True)

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
