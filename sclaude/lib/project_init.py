#!/usr/bin/env python3
#
# Working out what a project can tell us about itself, so the wizard asks as
# little as possible.
#
# The questions sclaude needs answered — which checks make up a regression,
# where the manuals live, what production's address is, where the migrations
# are — mostly have answers lying in the repository already: in package.json's
# scripts, in the directory layout, in whatever config the project keeps about
# its own environments. A wizard that asked all of them from scratch would be
# asking a person to retype what the machine can read.
#
# So this proposes, and the wizard confirms. Everything here is a guess offered
# for correction, never a decision: a wrong guess accepted in silence is worse
# than a question, and the shell side prints each one before it is taken.
#
# Prints a JSON object on stdout. Silent and `{}` on anything unknown — a
# project with no package.json is not an error, it is a project the wizard will
# have to ask about.
import json
import os
import re
import subprocess
import sys

# The regression parts sclaude understands, in the order they are worth running:
# the cheap and local first, so a typo fails in seconds rather than after a
# build. The names are sclaude's; the commands behind them are the project's.
#
# Each entry is (part, [candidate script names]). The first script a project
# actually has wins.
KNOWN_PARTS = [
    ("typecheck", ["typecheck", "type-check", "tsc"]),
    ("lint", ["lint"]),
    ("build", ["build"]),
    ("migrations", ["check:migrations"]),
    ("schema", ["db:schema"]),
    ("check:rls", ["check:rls"]),
    ("e2e", ["test:e2e", "e2e", "test:playwright"]),
]

# What a deployed stage runs, and it is a subset rather than a separate set: a
# preview or production stage asks what a browser sees and nothing more. The
# build of that commit has already happened on the host's side, and the checks
# that write to the database refuse a protected environment outright.
#
# The local stage runs these too — `e2e` against this machine's dev server is
# the whole point of having a suite — so a part named here appears in both
# lists rather than moving out of the first.
DEPLOYED_PARTS = ("e2e",)

# What runs when nothing but the manuals changed since the last green local
# run: the checks that read the code. A manual is code too — a typo in it breaks
# the build — but no browser suite visits it, and none of these needs the dev
# server or the database, which that shorter run does not bring up.
MANUAL_PARTS = ("typecheck", "lint", "build")

# Where a project might keep the two manuals. The pair is what step 1 reads
# before it guesses at the scope, and step 3 updates in the same pull request.
MANUAL_HINTS = [
    ("app/(app)/help/page.tsx", "user-facing — what a person can do"),
    ("app/(app)/help/technical/page.tsx", "technical — where things apply"),
    ("app/help/page.tsx", "user-facing — what a person can do"),
    ("app/help/technical/page.tsx", "technical — where things apply"),
    ("docs/help.md", "user-facing — what a person can do"),
    ("docs/technical.md", "technical — where things apply"),
]

# Directories a migration tool would use.
MIGRATION_HINTS = [
    "supabase/migrations",
    "prisma/migrations",
    "db/migrate",
    "migrations",
]

# Files that might name the production host, and the paths inside them to try.
# A project that keeps this somewhere else is asked.
PROD_HINTS = [
    ("config/environments.json", ("prod", "siteUrl")),
    ("config/environments.json", ("production", "siteUrl")),
    ("config/environments.json", ("prod", "url")),
]

def scripts(root):
    try:
        with open(os.path.join(root, "package.json"), encoding="utf-8") as fh:
            return json.load(fh).get("scripts") or {}
    except (OSError, ValueError):
        return {}


def guess_regression(root):
    """The parts this project has a script for, split by stage."""
    have = scripts(root)
    commands, local, deployed = {}, [], []
    for part, candidates in KNOWN_PARTS:
        for name in candidates:
            if name not in have:
                continue
            # `db:schema` writes the snapshot unless it is told to check, and a
            # regression that rewrote one would be reporting on a file it had
            # just changed. The flag is sclaude's, not the project's.
            if part == "schema":
                commands[part] = "npm run %s -- --check" % name
            elif part == "e2e":
                # The address is substituted by the caller for a deployed stage;
                # absent, it means this machine's dev server.
                commands[part] = "npm run %s" % name
            else:
                commands[part] = "npm run %s" % name
            local.append(part)
            if part in DEPLOYED_PARTS:
                deployed.append(part)
            break
    return commands, local, deployed


def guess_manuals(root):
    out = []
    for path, what in MANUAL_HINTS:
        if os.path.isfile(os.path.join(root, path)):
            out.append({"path": path, "what": what})
    return out


def guess_migrations(root):
    for path in MIGRATION_HINTS:
        full = os.path.join(root, path)
        if os.path.isdir(full):
            try:
                if any(name.endswith(".sql") for name in os.listdir(full)):
                    return path
            except OSError:
                continue
    return ""


def guess_prod_url(root):
    for path, keys in PROD_HINTS:
        try:
            with open(os.path.join(root, path), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        node = data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, str) and node.startswith("http"):
            return node
    return ""


# Where a schema snapshot might live. It is committed alongside the migrations
# that produced it, and a rollback regenerates it.
SCHEMA_HINTS = ["supabase/schema.sql", "db/schema.sql", "prisma/schema.prisma"]


def guess_promote(root):
    """The commands that put migrations into production, if the project has them."""
    have = scripts(root)
    out = {}
    # The table a migration tool keeps its record in. Named only when the tool
    # is recognised: a guessed table that a rollback then deletes from is worse
    # than no deletion at all.
    if os.path.isdir(os.path.join(root, "supabase")):
        out["historyTable"] = "supabase_migrations.schema_migrations"
    for path in SCHEMA_HINTS:
        if os.path.isfile(os.path.join(root, path)):
            out["schemaFile"] = path
            break
    for key, names in (("promote", ["db:promote"]),
                       ("schemaDump", ["db:schema"])):
        for name in names:
            if name in have:
                out[key] = "npm run %s" % name
                break
    return out


# The product's environments, one for each .env.<name> file at its root: the
# file is the environment (envs.py). `prod` and `production` are proposed
# protected, with the address guess_prod_url finds; everything else is for the
# person to confirm, like the rest of the proposal.
PROTECTED_NAMES = ("prod", "production")


def guess_environments(root):
    out = {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for file in names:
        if not file.startswith(".env.") or file.endswith(".example") \
                or file in (".env.local", ".env.example") or file.endswith(".local"):
            continue
        name = file[len(".env."):]
        if not name or not os.path.isfile(os.path.join(root, file)):
            continue
        entry = {"env": file}
        if name == "preview":
            # Deployments with no fixed address: not where a local server runs.
            entry["deployed"] = True
        if name in PROTECTED_NAMES:
            entry["protected"] = True
            url = guess_prod_url(root)
            if url:
                entry["siteUrl"] = url
        out[name] = entry
    return out


# Which of a board's columns plays which part, by the words people use for
# them. The first option matching a role wins; a board with none of them simply
# leaves that role out, which means sclaude will not make that move.
BOARD_ROLES = [
    ("backlog", re.compile(r"backlog|to ?do|todo|new|ready", re.I)),
    ("progress", re.compile(r"in ?progress|doing|started|active", re.I)),
    ("qa", re.compile(r"\bqa\b|testing|to verify|verif", re.I)),
    ("done", re.compile(r"^done$|complete|closed|shipped", re.I)),
]
DATE_ROLES = [
    ("start", re.compile(r"start", re.I)),
    ("end", re.compile(r"target|end|due|finish", re.I)),
]


def gh_json(args):
    try:
        done = subprocess.run(["gh"] + args, capture_output=True, text=True,
                              timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return None


def guess_board(root):
    """The board's column and date names, read from GitHub through gh.

    Only the names that match a role are proposed, and all of it is shown before
    it is written: a board is a team's own vocabulary, and a wrong guess here
    would move issues into a column nobody meant.
    """
    try:
        url = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    found = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?\s*$", url)
    if not found:
        return {}
    owner, name = found.groups()
    data = gh_json(["api", "graphql", "-f", "owner=" + owner, "-f", "name=" + name,
                    "-f", "query="
                    "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){"
                    "projectsV2(first:5){nodes{field(name:\"Status\"){"
                    "... on ProjectV2SingleSelectField{options{name}}}}}"
                    "issueFields(first:50){nodes{... on IssueFieldDate{name dataType}}}}}"])
    repo = ((data or {}).get("data") or {}).get("repository") or {}
    board = {}

    options = []
    for project in (repo.get("projectsV2") or {}).get("nodes") or []:
        options = [o["name"] for o in ((project or {}).get("field") or {}).get("options") or []]
        if options:
            break
    columns = {}
    for role, pattern in BOARD_ROLES:
        match = next((o for o in options if pattern.search(o)
                      and o not in columns.values()), None)
        if match:
            columns[role] = match
    if columns:
        board["columns"] = columns

    dates = {}
    fields = [f.get("name") for f in (repo.get("issueFields") or {}).get("nodes") or []
              if (f or {}).get("dataType") == "DATE"]
    for role, pattern in DATE_ROLES:
        match = next((f for f in fields if f and pattern.search(f)
                      and f not in dates.values()), None)
        if match:
            dates[role] = match
    if dates:
        board["dates"] = dates
    return board


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    commands, local, deployed = guess_regression(root)

    proposal = {
        "commands": commands,
        "regression": {},
        "manuals": guess_manuals(root),
        "database": {},
    }
    if local:
        proposal["regression"]["local"] = local
    if deployed:
        proposal["regression"]["preview"] = list(deployed)
        proposal["regression"]["prod"] = list(deployed)
    manual = [p for p in local or [] if p in MANUAL_PARTS]
    if manual and proposal["manuals"]:
        proposal["regression"]["manual"] = manual

    environments = guess_environments(root)
    if environments:
        proposal["environments"] = environments

    migrations = guess_migrations(root)
    if migrations:
        proposal["database"]["migrations"] = migrations
    promote = guess_promote(root)
    if promote:
        proposal["database"].update(promote)

    # SCLAUDE_INIT_OFFLINE is for benches: the guess asks GitHub, and a test of
    # the rest of the wizard has no business on the network.
    if not os.environ.get("SCLAUDE_INIT_OFFLINE"):
        board = guess_board(root)
        if board:
            proposal["board"] = board

    # Empty sections are dropped rather than written as `{}`: a config should
    # say what the project has, and an empty object invites somebody to fill it
    # in when the honest answer may be that there is nothing to fill.
    for key in ("regression", "database", "commands"):
        if not proposal.get(key):
            proposal.pop(key, None)
    if not proposal.get("manuals"):
        proposal.pop("manuals", None)

    sys.stdout.write(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
