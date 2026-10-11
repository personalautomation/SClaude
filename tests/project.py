#!/usr/bin/env python3
#
# A test bench for the project's own config.
#
# The orchestrator used to carry one product's answers inside it: the
# regression's parts and their npm scripts, the manuals' paths, production's
# address, the migrations directory. They now live in `.sclaude/config.json` at the
# root of whichever repository sclaude is run from, and what is guarded here is
# the property that made the move worth making — **no default is this product's
# answer**. A reintroduced fallback would work silently in the wrong repository,
# which is worse than refusing.
#
# The other half is the wizard. A repository with no config is offered one built
# from what is already there, and the guesses must be right for a project that
# is not this one: the bench builds a small foreign project — a different
# bundler, manuals as markdown, no database — and checks what comes back.
#
# Run it with: python3 tests/project.py
import json
import os
import shutil
import subprocess
import sys
import tempfile


def _cfg(path):
    """The path of a product's config, its .sclaude/ folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


def run_bash(script, cwd, modules=("io", "ui", "state", "project", "environment")):
    body = "set -uo pipefail\n"
    body += 'BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; OFF=""\n'
    for name in modules:
        body += 'source "%s/%s.sh"\n' % (LIB, name)
    body += ('die()  { echo "$*" >&2; exit 1; }\n'
             'warn() { echo "$*" >&2; }\n'
             'info() { echo "$*"; }\n'
             'say()  { echo "$*"; }\n'
             'LIB="%s"\n' % LIB)
    body += script
    out = subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                         text=True, timeout=30)
    return out.stdout, out.stderr, out.returncode


def detect(root):
    out = subprocess.run([sys.executable, os.path.join(LIB, "project_init.py"), root],
                         capture_output=True, text=True, timeout=30,
                         env=dict(os.environ, SCLAUDE_INIT_OFFLINE="1"))
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {}


tmp = tempfile.mkdtemp()
try:
    # --- reading a config ----------------------------------------------------

    proj = os.path.join(tmp, "proj")
    os.makedirs(proj)
    with open(_cfg(os.path.join(proj, ".sclaude/config.json")), "w") as fh:
        json.dump({
            "commands": {"typecheck": "pnpm typecheck", "e2e": "pnpm e2e"},
            "regression": {"local": ["typecheck", "e2e"], "preview": ["e2e"]},
            "manuals": [{"path": "docs/a.md", "what": "one"}],
            "environments": {"prod": {"env": ".env.prod", "protected": True,
                                      "siteUrl": "https://example.test"}},
            "database": {"migrations": "db/migrations"},
        }, fh)

    out, _, _ = run_bash('REPO=%s; project_regression_parts local' % proj, tmp)
    check("parts-local", out.strip(), "typecheck e2e")
    out, _, _ = run_bash('REPO=%s; project_regression_parts preview' % proj, tmp)
    check("parts-preview", out.strip(), "e2e")
    # A stage the project does not describe answers nothing rather than
    # borrowing another stage's list.
    out, _, _ = run_bash('REPO=%s; project_regression_parts prod' % proj, tmp)
    check("parts-undeclared-stage-is-empty", out.strip(), "")

    out, _, _ = run_bash('REPO=%s; project_command typecheck' % proj, tmp)
    check("command-read", out.strip(), "pnpm typecheck")
    out, _, _ = run_bash('REPO=%s; project_prod_url' % proj, tmp)
    check("prod-url-read", out.strip(), "https://example.test")
    out, _, _ = run_bash('REPO=%s; project_migrations_dir' % proj, tmp)
    check("migrations-dir-read", out.strip(), "db/migrations")

    # A key the project does not carry answers empty and non-zero — the callers
    # read that as "we do not know", which is never the same as a default.
    out, _, rc = run_bash('REPO=%s; project_command nosuch' % proj, tmp)
    check("unknown-command-is-empty", out.strip(), "")
    check("unknown-command-refuses", rc != 0, True)
    out, _, rc = run_bash('REPO=%s; project_db_url_var' % proj, tmp)
    check("unknown-section-is-empty", out.strip(), "")

    # A worktree's own copy wins: a feature in flight may be changing it.
    wt = os.path.join(tmp, "proj-feature")
    os.makedirs(wt)
    with open(_cfg(os.path.join(wt, ".sclaude/config.json")), "w") as fh:
        json.dump({"commands": {"typecheck": "from-the-worktree"}}, fh)
    out, _, _ = run_bash('REPO=%s; project_command typecheck %s' % (proj, wt), tmp)
    check("worktree-config-wins", out.strip(), "from-the-worktree")

    # --- no config at all ----------------------------------------------------
    #
    # The whole point of the move: absence, not this product's answers.

    bare = os.path.join(tmp, "bare")
    os.makedirs(bare)
    for call, name in (("project_regression_parts local", "parts"),
                       ("project_command typecheck", "command"),
                       ("project_prod_url", "prod-url"),
                       ("project_migrations_dir", "migrations"),
                       ("project_db_url_file", "db-file")):
        out, _, _ = run_bash('REPO=%s; %s' % (bare, call), tmp)
        check("bare-%s-is-empty" % name, out.strip(), "")

    # Nothing about this product may survive as a default anywhere in the
    # library. These are the exact strings that used to be written into it, and
    # a comment mentioning them is fine — a line of code is not.
    for module, needles in (
            ("regression.sh", ["agoramove", "REGRESSION_LOCAL_PARTS="]),
            ("deploy.sh", ["supabase/migrations"]),
            ("rollback.sh", ["POSTGRES_URL_NON_POOLING", ".env.prod"]),
    ):
        path = os.path.join(LIB, module)
        with open(path, encoding="utf-8") as fh:
            code = [line for line in fh
                    if not line.strip().startswith("#")]
        for needle in needles:
            check_true("no-default-%s-in-%s" % (needle[:18], module),
                       not any(needle in line for line in code))

    # --- the wizard's guesses ------------------------------------------------
    #
    # A project that is deliberately not this one: a different bundler, manuals
    # as markdown, no database, no environments file.

    foreign = os.path.join(tmp, "foreign")
    os.makedirs(os.path.join(foreign, "docs"))
    with open(os.path.join(foreign, "package.json"), "w") as fh:
        json.dump({"scripts": {"typecheck": "tsc --noEmit", "lint": "eslint",
                               "build": "vite build", "test:e2e": "playwright test"}}, fh)
    for name in ("help.md", "technical.md"):
        with open(os.path.join(foreign, "docs", name), "w") as fh:
            fh.write("# x\n")

    guess = detect(foreign)
    check("foreign-local-parts", guess["regression"]["local"],
          ["typecheck", "lint", "build", "e2e"])
    check("foreign-deployed-parts", guess["regression"]["preview"], ["e2e"])
    # The manual-only run is proposed only alongside manuals, and holds the
    # checks that read the code — not e2e, which needs the dev server.
    check("foreign-manual-parts", guess["regression"]["manual"],
          ["typecheck", "lint", "build"])
    check("foreign-command", guess["commands"]["build"], "npm run build")
    check("foreign-manuals",
          [m["path"] for m in guess["manuals"]],
          ["docs/help.md", "docs/technical.md"])
    # Nothing was invented for what this project does not have. An empty section
    # is dropped rather than written, so a reader is not invited to fill in
    # something whose honest answer is "there is none".
    check("foreign-no-database", "database" in guess, False)
    check("foreign-no-environments", "environments" in guess, False)

    # e2e belongs to both stages rather than moving out of the local one: a
    # suite against this machine's dev server is the point of having one.
    check_true("e2e-is-local-too", "e2e" in guess["regression"]["local"])

    # A project with nothing recognisable proposes nothing, and the wizard says
    # so rather than writing an empty file that looks configured.
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    check("nothing-recognised", detect(empty), {})

    # A schema part is always asked to check rather than to write: `db:schema`
    # rewrites the snapshot unless told otherwise, and a regression that
    # rewrote one would be reporting on a file it had just changed.
    withdb = os.path.join(tmp, "withdb")
    os.makedirs(os.path.join(withdb, "supabase", "migrations"))
    with open(os.path.join(withdb, "package.json"), "w") as fh:
        json.dump({"scripts": {"db:schema": "bash dump.sh",
                               "db:promote": "node promote.mjs",
                               "db:preview": "node apply.mjs preview"}}, fh)
    with open(os.path.join(withdb, "supabase", "migrations", "0001.sql"), "w") as fh:
        fh.write("create table t (id int);\n")
    guess = detect(withdb)
    check_true("schema-part-checks-only",
               "--check" in guess["commands"]["schema"])
    check("migrations-dir-guessed", guess["database"]["migrations"],
          "supabase/migrations")
    check_true("history-table-named-when-known",
               guess["database"].get("historyTable"))
    # The promote's own command is the project's, not a guess at npm's name.
    check("promote-guessed", guess["database"]["promote"], "npm run db:promote")
    # The preview apply is not guessed: it writes to a database, and a
    # `db:preview` may just as well be a dry run.
    check_true("apply-preview-never-guessed",
               "applyPreview" not in guess["database"])

    # --- the example file ----------------------------------------------------
    #
    # It is what the wizard points at when it cannot work anything out, so it
    # has to be valid and it has to parse into what the readers expect.

    with open(os.path.join(ROOT, "sclaude", "config.example.json"),
              encoding="utf-8") as fh:
        example = json.load(fh)
    for key in ("commands", "regression", "manuals", "environments", "database"):
        check_true("example-has-%s" % key, key in example)
    # Every part the example's stages name has a command, which is the rule the
    # run enforces at run time.
    for stage in ("local", "preview", "prod"):
        for part in example["regression"].get(stage, []):
            check_true("example-command-for-%s" % part,
                       bool(example["commands"].get(part)))
    # A manual entry is {path, what}: the reader takes `path` and would
    # otherwise put a dict where a string belongs.
    for entry in example["manuals"]:
        check_true("example-manual-has-a-path", bool(entry.get("path")))

    # The example must be copyable as it stands, so nothing inside the sections
    # the readers walk may be commentary. The prose lives in one top-level key.
    check_true("example-prose-is-top-level", isinstance(example.get("README"), list))
    for key in ("commands", "regression", "environments", "database"):
        check("example-%s-has-no-prose" % key,
              any(k.startswith("_") or k == "README" for k in example[key]), False)

    # --- the board guess -----------------------------------------------------
    #
    # gh is replaced by a canned answer: what is under test is which option is
    # taken for which role, and that a board with no such option leaves the
    # role out rather than inventing it.
    sys.path.insert(0, LIB)
    import project_init
    board_repo = os.path.join(tmp, "board")
    os.makedirs(board_repo)
    subprocess.run(["git", "init", "-q", board_repo], check=True)
    subprocess.run(["git", "-C", board_repo, "remote", "add", "origin",
                    "git@github.com:acme/app.git"], check=True)
    asked = []

    def canned(options, fields):
        def fake(args):
            asked.append(args)
            return {"data": {"repository": {
                "projectsV2": {"nodes": [{"field": None},
                                         {"field": {"options": [{"name": o} for o in options]}}]},
                "issueFields": {"nodes": [{"name": n, "dataType": t} for n, t in fields]}}}}
        return fake

    project_init.gh_json = canned(
        ["Todo", "Doing", "Testing", "Done"],
        [("Kickoff start", "DATE"), ("Due", "DATE"), ("Start", "TEXT")])
    check("board-guess-roles", project_init.guess_board(board_repo),
          {"columns": {"backlog": "Todo", "progress": "Doing", "qa": "Testing",
                       "done": "Done"},
           "dates": {"start": "Kickoff start", "end": "Due"}})
    check_true("board-guess-asks-the-origin-repo",
               any("owner=acme" in a and "name=app" in a for a in asked))
    project_init.gh_json = canned(["Inbox", "Doing"], [])
    check("board-guess-leaves-unknown-roles-out",
          project_init.guess_board(board_repo), {"columns": {"progress": "Doing"}})
    project_init.gh_json = lambda args: None
    check("board-guess-silent-without-gh", project_init.guess_board(board_repo), {})

finally:
    shutil.rmtree(tmp, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
