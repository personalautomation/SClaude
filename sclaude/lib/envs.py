#!/usr/bin/env python3
#
# A product's environments, as .env files sclaude knows the place of.
#
# `environments` in the product's .sclaude/config.json names each environment
# and the file that holds it, relative to the main repository's root:
#
#   "environments": {
#     "localdb": {"env": ".env.localdb", "siteUrl": "http://localhost:3000"},
#     "dev":     {"env": ".env.dev"},
#     "prod":    {"env": ".env.prod", "protected": true, "siteUrl": "https://…"}
#   }
#
# That is the whole contract. A tree is on the environment whose file its
# .env.local points at; switching it is pointing .env.local elsewhere, and, for
# a product on Supabase, linking the CLI to the project that file names. The
# credentials stay in those files, in one place, and sclaude reads what it
# needs from them. It used to run four commands the product wrote for it
# (`current`, `settled`, `switch`, `status`), keep the protected names in a
# second file, and carry the production switch twice more in `database`.
#
#   protected   a database holding somebody's real data. A feature is never
#               pointed at it, and a session is not let switch a tree there.
#   siteUrl     where the environment answers. Production's is what the
#               deployed regression aims at. One that is not a loopback address
#               is not worked against from this machine.
#   deployed    the environment of deployments with no fixed address, such as
#               previews: perfectly safe to write to, and still not where a
#               local dev server and a local browser suite belong.
#
# The keys sclaude reads from a file are the Supabase ones by default and can
# be renamed with `envKeys` in the same config:
#
#   "envKeys": {"supabaseUrl": "SUPABASE_URL", "database": "DATABASE_URL"}
#
# Used by environment.sh through the command line below, and by
# forbidden-commands.py as a module.
#
#   envs.py names <root>                    every environment, one a line
#   envs.py protected <root> <name>         exit 0 when protected (or unknown)
#   envs.py runnable <root> <name>          exit 0 when a feature may run on it
#   envs.py file <root> <name>              its .env file, absolute
#   envs.py ref <root> <name>               its Supabase project ref, if hosted
#   envs.py value <root> <name> <key>       one value from its file
#   envs.py current <root> <tree>           the environment the tree is on
#   envs.py settled <root> <tree>           the same, only when the Supabase
#                                           CLI's link agrees with it
#   envs.py production <root>               production's name
#   envs.py site <root>                     production's siteUrl
#   envs.py old <root>                      why the config is of the old shape
import json
import os
import re
import sys

DEFAULT_KEYS = {"supabaseUrl": "NEXT_PUBLIC_SUPABASE_URL",
                "database": "POSTGRES_URL_NON_POOLING"}
HOSTED = re.compile(r"^https://([a-z0-9]{20})\.supabase\.co/?$")
LINKED_REF = os.path.join("supabase", ".temp", "project-ref")


def config(root):
    try:
        with open(os.path.join(root, ".sclaude", "config.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def environments(root, data=None):
    """{name: entry} for the entries that name a file; anything else is not one."""
    found = (data if data is not None else config(root)).get("environments")
    if not isinstance(found, dict):
        return {}
    return {name: entry for name, entry in found.items()
            if isinstance(name, str) and isinstance(entry, dict)
            and isinstance(entry.get("env"), str) and entry["env"].strip()}


def old_shape(root, data=None):
    """Why `environments` is of the shape sclaude no longer reads, or None."""
    found = (data if data is not None else config(root)).get("environments")
    if isinstance(found, dict) and any(k in found for k in ("current", "settled", "switch", "file")):
        return ("`environments` names commands and a file of its own; sclaude now reads "
                "each environment's .env file instead — see sclaude/config.example.json")
    return None


def keys(root, data=None):
    named = (data if data is not None else config(root)).get("envKeys")
    out = dict(DEFAULT_KEYS)
    if isinstance(named, dict):
        out.update({k: v for k, v in named.items() if isinstance(v, str) and v})
    return out


def protected(root, name, data=None):
    """Silence means protected: a name sclaude cannot resolve is not permission."""
    entry = environments(root, data).get(name)
    return not isinstance(entry, dict) or bool(entry.get("protected"))


def runnable(root, name, data=None):
    """Whether a feature on this machine may be pointed at this environment."""
    entry = environments(root, data).get(name)
    if not entry or entry.get("protected") or entry.get("deployed"):
        return False
    site = entry.get("siteUrl")
    return not isinstance(site, str) or not site or "localhost" in site or "127.0.0.1" in site


def env_file(root, name, data=None):
    entry = environments(root, data).get(name)
    if not entry:
        return None
    path = os.path.expanduser(entry["env"])
    return path if os.path.isabs(path) else os.path.join(root, path)


def read_env(path):
    """KEY=value pairs of a dotenv file: quotes taken off, comments skipped."""
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key] = value
    return out


def value(root, name, key, data=None):
    path = env_file(root, name, data)
    return read_env(path).get(key) if path else None


def ref(root, name, data=None):
    """The hosted Supabase project an environment's file names, or None."""
    url = value(root, name, keys(root, data)["supabaseUrl"], data) or ""
    found = HOSTED.match(url.strip())
    return found.group(1) if found else None


def current(root, tree, data=None):
    """The environment whose file the tree's .env.local points at, or None."""
    link = os.path.join(tree, ".env.local")
    try:
        target = os.path.realpath(link) if os.path.islink(link) else None
    except OSError:
        target = None
    if not target:
        return None
    files = {name: env_file(root, name, data) for name in environments(root, data)}
    for name, path in files.items():
        if path and os.path.realpath(path) == target:
            return name
    # A link made in another tree (a worktree's .env.local into the main
    # repository) names the same file by another path: the basename then,
    # but only when it singles one out. Environments in folders of their own
    # can share it (envs/dev/.env, envs/prod/.env), and the first of them was
    # taken, production read as dev.
    alike = [n for n, p in files.items() if p and os.path.basename(p) == os.path.basename(target)]
    return alike[0] if len(alike) == 1 else None


def settled(root, tree, data=None):
    """current(), but only when the Supabase CLI's link agrees with it.

    `supabase db push` obeys supabase/.temp/project-ref, not .env.local. A
    hosted environment must be linked to its own project; a local one to none,
    since a ref left over from an earlier switch would send the push to it.
    """
    name = current(root, tree, data)
    if not name:
        return None
    want = ref(root, name, data)
    try:
        with open(os.path.join(tree, LINKED_REF), encoding="utf-8") as fh:
            linked = fh.read().strip() or None
    except OSError:
        linked = None
    return name if linked == want else None


def production(root, data=None):
    """Production: the protected environment, or of several the one answering
    at a public address. None when that does not single one out."""
    guarded = [n for n, e in environments(root, data).items() if e.get("protected")]
    if len(guarded) == 1:
        return guarded[0]
    public = [n for n in guarded
              if isinstance(environments(root, data)[n].get("siteUrl"), str)
              and environments(root, data)[n]["siteUrl"].startswith("https://")]
    return public[0] if len(public) == 1 else None


def production_site(root, data=None):
    name = production(root, data)
    site = environments(root, data)[name].get("siteUrl") if name else None
    return site if isinstance(site, str) and site else None


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__ or "")
        return 2
    what, root = argv[0], argv[1]
    rest = argv[2:]
    if what == "names":
        for name in environments(root):
            print(name)
        return 0
    if what == "protected" and rest:
        return 0 if protected(root, rest[0]) else 1
    if what == "runnable" and rest:
        return 0 if runnable(root, rest[0]) else 1
    if what in ("file", "ref", "current", "settled") and rest:
        found = {"file": env_file, "ref": ref, "current": current, "settled": settled}[what](root, rest[0])
        if not found:
            return 1
        print(found)
        return 0
    if what == "value" and len(rest) >= 2:
        found = value(root, rest[0], rest[1])
        if found is None:
            return 1
        print(found)
        return 0
    if what == "production":
        found = production(root)
        if not found:
            return 1
        print(found)
        return 0
    if what == "site":
        found = production_site(root)
        if not found:
            return 1
        print(found)
        return 0
    if what == "old":
        found = old_shape(root)
        if not found:
            return 1
        print(found)
        return 0
    sys.stderr.write(__doc__ or "")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
