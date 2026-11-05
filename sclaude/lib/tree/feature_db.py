#!/usr/bin/env python3
#
# A feature's own local Supabase: the config its stack runs from, and the
# environment that points a feature's processes at it.
#
# Two features working against one local database see each other's schema: a
# migration written in one lands under the other, and a `db reset` in one wipes
# the other's data. So a feature whose environment is the local stack gets a
# stack of its own — its own project_id (Docker names its containers and
# volumes after it) and its own block of ports.
#
# The worktree's supabase/config.toml is not touched: it is a tracked file, and
# a port rewritten there would ride into the feature's commit. The stack runs
# from .sclaude/local/feature/supabase/ instead, where config.toml is a rewritten copy and
# everything else — the migrations first of all — is a symlink back into the
# tree, so a migration the feature writes is one the stack sees.
#
#   feature_db.py config <src config.toml> <dst config.toml> <project_id> <base>
#   feature_db.py envfile <.sclaude/config.json> <workdir>   < `supabase status -o env`
#
# Called from featuredb.sh; each subcommand is a function below, for the tests.
import json
import re
import shlex
import sys

# Where each port goes inside a feature's block of ten. Keyed by the TOML
# section and the key, because `port` alone means five different services.
# The mail catcher has been called both inbucket and local_smtp; both spellings
# map to the same slot, and only one of them is ever in a given config.
PORT_SLOTS = {
    ("db", "shadow_port"): 0,
    ("api", "port"): 1,
    ("db", "port"): 2,
    ("studio", "port"): 3,
    ("local_smtp", "port"): 4,
    ("inbucket", "port"): 4,
    ("analytics", "port"): 7,
    ("edge_runtime", "inspector_port"): 8,
    ("db.pooler", "port"): 9,
}

SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*(#.*)?$")
PORT_LINE = re.compile(r"^(\s*)(port|shadow_port|inspector_port)(\s*=\s*)\d+(.*)$")
PROJECT_ID = re.compile(r"^(\s*)project_id(\s*=\s*)\"[^\"]*\"(.*)$")


def rewrite_config(text, project_id, base):
    """The config with this feature's project_id and ports, all else untouched.

    Line by line rather than through a TOML library: the file is the project's,
    with its comments, and a round trip through a parser would drop them — and
    Python has no TOML writer to round-trip with anyway."""
    out, section = [], ""
    for line in text.split("\n"):
        match = SECTION.match(line)
        if match:
            section = match.group(1).strip()
        match = PORT_LINE.match(line)
        if match and (section, match.group(2)) in PORT_SLOTS:
            line = "%s%s%s%d%s" % (match.group(1), match.group(2), match.group(3),
                                   base + PORT_SLOTS[(section, match.group(2))],
                                   match.group(4))
        match = PROJECT_ID.match(line)
        if match and section == "":
            line = '%sproject_id%s"%s"%s' % (match.group(1), match.group(2),
                                            project_id, match.group(3))
        out.append(line)
    return "\n".join(out)


def parse_status(text):
    """`supabase status -o env` as a dict: KEY="value" per line."""
    values = {}
    for line in text.splitlines():
        match = re.match(r'^([A-Z0-9_]+)=(.*)$', line.strip())
        if not match:
            continue
        value = match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[match.group(1)] = value
    return values


def env_lines(mapping, status, workdir):
    """The lines of .sclaude/local/feature/db.env, or None when the stack did not answer.

    `mapping` is the project's: its variable name -> the status key that fills
    it. Every value is shell-quoted, because the file is sourced. The CLI's own
    SUPABASE_WORKDIR is always there: it is what makes a bare `supabase db
    reset` typed in the feature reach this stack and not the main one."""
    lines = ["# Written by sclaude: this feature's own local Supabase. Do not edit.",
             "SUPABASE_WORKDIR=%s" % shlex.quote(workdir)]
    for name, key in sorted(mapping.items()):
        if key not in status:
            return None
        lines.append("%s=%s" % (name, shlex.quote(status[key])))
    return lines


def main(argv):
    if len(argv) >= 5 and argv[0] == "config":
        src, dst, project_id, base = argv[1:5]
        with open(src) as fh:
            text = fh.read()
        with open(dst, "w") as fh:
            fh.write(rewrite_config(text, project_id, int(base)))
        return 0
    if len(argv) >= 3 and argv[0] == "envfile":
        with open(argv[1]) as fh:
            config = json.load(fh)
        mapping = ((config.get("database") or {}).get("local") or {}).get("env") or {}
        lines = env_lines(mapping, parse_status(sys.stdin.read()), argv[2])
        if lines is None:
            return 1
        sys.stdout.write("\n".join(lines) + "\n")
        return 0
    sys.stderr.write("usage: feature_db.py config|envfile …\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
