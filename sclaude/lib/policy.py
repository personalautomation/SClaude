#!/usr/bin/env python3
#
# What a session may run, assembled from sclaude's presets and the product's
# own choices.
#
# sclaude ships presets: sclaude/policy/core.json, the rules no product or
# person can lift, and one file per integration (vercel.json, supabase.json),
# the stack's usual dangers. A product picks its integrations and adds its own
# rules in .sclaude/team/policy.json; a developer adds theirs in
# .sclaude/people/<name>/policy.json. Every layer has the same shape:
#
#   {
#     "integrations": ["vercel", "supabase"],          team only
#     "deny":  [{"command": "npm run db:promote", "why": "..."}],
#     "allow": [{"command": "npm run check:r2", "why": "..."}],
#     "steps": {"code": {"deny": [...], "allow": [...]}},
#     "tools": {"deny": ["mcp__…"]},                   integrations only
#     "rules": ["vercel-deploy"],                      integrations only
#     "settings": {"supabase": {...}}                  team only
#   }
#
# A command is matched by its first words, after the wrappers and package
# runners are stripped (_shell.py), so `npm run db:promote` catches
# `timeout 5 npx --yes npm run db:promote -- --dry`. `allow` adds the command
# to the session's permissions, so it is not asked about. The team's `allow`
# also lifts a deny that came from an integration, rules included: a product
# may decide that `vercel --prod` is its sessions' to run. Nothing lifts what
# core.json says, and a person's `allow` lifts nothing: what the team bans
# stays banned for everybody in it.
#
# Used by forbidden-commands.py, and by steps.sh for --disallowed-tools and
# permissions.allow:
#
#   policy.py json <product root> <person> [step]   the merged policy
#   policy.py flags <product root> <person> [step]  disallowed, then allowed,
#                                                   one Claude rule per line,
#                                                   a blank line between
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(HERE, "..", "policy")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def entries(layer, key, step):
    """(words, why) pairs of one list in a layer, for the step if named."""
    out = []
    lists = [layer.get(key)]
    if step:
        lists.append(((layer.get("steps") or {}).get(step) or {}).get(key))
    for items in lists:
        for item in items or []:
            command = item.get("command") if isinstance(item, dict) else item
            if not isinstance(command, str) or not command.strip():
                continue
            try:
                words = tuple(shlex.split(command))
            except ValueError:
                continue
            why = item.get("why", "") if isinstance(item, dict) else ""
            out.append((words, why))
    return out


def detected_integrations(root):
    """What a product with no `integrations` of its own evidently uses.

    Only for a product that has not said: once the team's policy names its
    integrations, that list is the answer, an empty one included.
    """
    found = []
    if os.path.isdir(os.path.join(root, ".vercel")) or os.path.isfile(
            os.path.join(root, "vercel.json")):
        found.append("vercel")
    if os.path.isdir(os.path.join(root, "supabase")):
        found.append("supabase")
    return found


def merged(root, person="", step=""):
    """The policy a session in this product, run by this person, works under."""
    core = read(os.path.join(PRESETS, "core.json"))
    team = read(os.path.join(root, ".sclaude", "team", "policy.json")) if root else {}
    mine = read(os.path.join(root, ".sclaude", "people", person, "policy.json")) \
        if root and person else {}

    names = team.get("integrations")
    if not isinstance(names, list):
        names = detected_integrations(root) if root else []
    integrations = {n: read(os.path.join(PRESETS, "%s.json" % n))
                    for n in names if isinstance(n, str) and n.replace("-", "").isalnum()}

    def with_source(layer, key, source):
        return [(w, why, source) for w, why in entries(layer, key, step)]

    hard = with_source(core, "deny", "core")
    lifts = [w for w, _ in entries(team, "allow", step)]

    def lifted(words):
        return any(words[:len(l)] == l for l in lifts)

    deny = list(hard)
    rules, tools = [], []
    for name, layer in integrations.items():
        deny += [d for d in with_source(layer, "deny", name) if not lifted(d[0])]
        rules += [r for r in layer.get("rules") or [] if isinstance(r, str)]
        tools += [t for t in (layer.get("tools") or {}).get("deny") or [] if isinstance(t, str)]
    deny += with_source(team, "deny", "team")
    deny += with_source(mine, "deny", "person")

    allow = with_source(team, "allow", "team") + with_source(mine, "allow", "person")
    # An allow never undoes a deny in a layer it cannot lift.
    blocked = [d[0] for d in deny]
    allow = [a for a in allow if not any(a[0][:len(b)] == b for b in blocked)]

    return {
        "deny": [{"words": list(w), "why": why, "from": src} for w, why, src in deny],
        "allow": [{"words": list(w), "why": why, "from": src} for w, why, src in allow],
        "rules": sorted(set(rules)),
        "lifted": [list(l) for l in lifts],
        "tools": sorted(set(tools)),
        "integrations": sorted(integrations),
        "settings": team.get("settings") if isinstance(team.get("settings"), dict) else {},
    }


def claude_rule(words):
    return "Bash(%s:*)" % " ".join(words)


def main(argv):
    if len(argv) < 3 or argv[0] not in ("json", "flags"):
        sys.stderr.write(__doc__ or "")
        return 2
    root, person = argv[1], argv[2]
    step = argv[3] if len(argv) > 3 else ""
    policy = merged(root, person, step)
    if argv[0] == "json":
        print(json.dumps(policy, ensure_ascii=False))
        return 0
    for d in policy["deny"]:
        print(claude_rule(d["words"]))
    for t in policy["tools"]:
        print(t)
    print("")
    for a in policy["allow"]:
        print(claude_rule(a["words"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
