#!/usr/bin/env python3
#
# What a session may run, assembled from sclaude's presets and the product's
# own choices.
#
# sclaude ships presets: sclaude/policy/core.json, the rules no product or
# person can lift, and one file per integration (vercel.json, supabase.json),
# the stack's usual dangers. The production command a product already names
# in .sclaude/config.json (database.promote) is banned from there, so the
# product does not write it twice. A product picks its integrations and adds its own
# rules in .sclaude/team/policy.json; a developer adds theirs in
# .sclaude/people/<name>/policy.json. Every layer has the same shape:
#
#   {
#     "integrations": ["vercel", "supabase"],          team only
#     "deny":  [{"command": "npm run db:promote", "why": "..."}],
#     "allow": [{"command": "npm run check:storage", "why": "..."}],
#     "steps": {"code": {"deny": [...], "allow": [...]}},
#     "tools": {"deny": ["mcp__…"]},                   integrations only
#     "rules": ["vercel-deploy"],                      integrations only
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
#   policy.py json <product root> <person> [step [tree]]   the merged policy
#   policy.py flags <product root> <person> [step [tree]]  disallowed, then allowed,
#                                                   one Claude rule per line,
#                                                   a blank line between
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PRESETS = os.path.join(HERE, "..", "policy")


def read(path):
    """A layer's file: {} when there is none. One that is there and is not
    JSON raises: read as {}, a trailing comma in the team's file dropped every
    product ban without a word, where merged() falls back and says so."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError:
        return {}
    except ValueError as exc:
        raise ValueError("%s is not valid JSON (%s)" % (path, exc))
    return data if isinstance(data, dict) else {}


def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def entries(layer, key, step):
    """(words, why, command) of one list in a layer, for the step if named.

    A value of the wrong shape counts as absent: `{"steps": ["code"]}` in a
    team's file used to raise here, and the hook died with every ban.
    """
    out = []
    layer = as_dict(layer)
    lists = [layer.get(key)]
    if step:
        lists.append(as_dict(as_dict(layer.get("steps")).get(step)).get(key))
    for items in lists:
        for item in as_list(items):
            command = item.get("command") if isinstance(item, dict) else item
            if not isinstance(command, str) or not command.strip():
                continue
            try:
                # Compared as the hook compares a call: each word by its last
                # path component, so `node scripts/tool.mjs run` matches
                # `node ./scripts/tool.mjs run` as well, and a rule written
                # with a path is not one that can never fire.
                words = tuple(w.rsplit("/", 1)[-1] for w in shlex.split(command))
            except ValueError:
                continue
            why = item.get("why", "") if isinstance(item, dict) else ""
            why = why if isinstance(why, str) else ""
            out.append((words, why, command.strip()))
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


# The commands a product names in .sclaude/config.json for moving production: they are
# the human's steps by what they are, so the product does not write them twice.
CONFIG_DENIES = (
    ("promote", "promoting migrations to production is the human's step, after the merge"),
)


def config_denies(root):
    """(words, why) for the production commands .sclaude/config.json names."""
    config = read(os.path.join(root, ".sclaude/config.json")) if root else {}
    database = config.get("database") if isinstance(config.get("database"), dict) else {}
    out = []
    for key, why in CONFIG_DENIES:
        command = database.get(key)
        if isinstance(command, str) and command.strip():
            out.append({"command": command, "why": why})
    return {"deny": out}


def merged(root, person="", step="", tree=""):
    """The policy a session in this product, run by this person, works under.

    `tree` is the feature's worktree, when the session works in one. A friction
    review commits its rule there, on the feature's branch, and the next
    session of that feature must see it, not only main's copy in the main
    checkout: the lifted ban fired again in every round until the merge. The
    bans of both copies apply, and the allows are the tree's, so a branch made
    before a rule reached main does not shed it. Integrations are still told
    from the main checkout, which holds the untracked .vercel link.

    A product's or a person's file that breaks the merge in a way entries()
    did not foresee is dropped, and the policy is built from sclaude's
    presets, the product's integrations and its config alone, with a line on
    stderr. What it raises is sclaude's own trouble, core.json unreadable
    among it: the hook refuses on it (_failsafe.py), and the step does not
    start (policy_rules).
    """
    try:
        return merge(root, person, step, layers=True, tree=tree)
    except CoreUnreadable:
        # The presets are what broke: nothing to fall back on, and the
        # message below would blame the product.
        raise
    except Exception as exc:  # noqa: BLE001 — any failure, the presets still hold
        sys.stderr.write("sclaude policy: the product's or the person's rules could "
                         "not be read (%s); working from sclaude's presets\n" % exc)
        return merge(root, person, step, layers=False, tree=tree)


def layered(root, tree, *parts):
    """One layer's file from the main checkout and the tree, as one layer:
    the bans of both, the rest from the tree's copy when it has one."""
    main = read(os.path.join(root, *parts))
    if not tree or os.path.realpath(tree) == os.path.realpath(root):
        return main
    path = os.path.join(tree, *parts)
    if not os.path.isfile(path):
        return main
    # The tree's copy is the session's to break, and a broken one is only its
    # own loss: main's copy holds. It used to fail the whole merge, and the
    # fallback to the presets threw main's team rules away with it.
    try:
        own = dict(read(path))
    except ValueError as exc:
        sys.stderr.write("sclaude policy: %s; this tree's copy is left out, main's holds\n" % exc)
        return main
    own["deny"] = as_list(main.get("deny")) + as_list(own.get("deny"))
    # An integration is a set of bans too: one main uses holds for a branch
    # made before main named it.
    # Where main names none, what it evidently uses counts as named: a tree's
    # `"integrations": []` otherwise turned the detected ones off.
    if isinstance(main.get("integrations"), list) or isinstance(own.get("integrations"), list):
        mains = main.get("integrations")
        mains = mains if isinstance(mains, list) else detected_integrations(root)
        names = as_list(mains) + as_list(own.get("integrations"))
        own["integrations"] = [n for i, n in enumerate(names) if n not in names[:i]]
    steps = dict(as_dict(own.get("steps")))
    for name, rules in as_dict(main.get("steps")).items():
        mine = dict(as_dict(steps.get(name)))
        mine["deny"] = as_list(as_dict(rules).get("deny")) + as_list(mine.get("deny"))
        steps[name] = mine
    if steps:
        own["steps"] = steps
    return own


class CoreUnreadable(RuntimeError):
    """core.json gave no rule: sclaude's own presets are broken."""


def merge(root, person, step, layers, tree=""):
    try:
        core = read(os.path.join(PRESETS, "core.json"))
    except ValueError as exc:
        raise CoreUnreadable(str(exc))
    # The rules nothing lifts are not optional: read as an empty layer, a
    # missing or broken core.json took the merge ban with it, silently. What
    # counts is the rules read from it, not that a list is there: an entry
    # with a misspelt key is skipped, and the ban with it.
    if not entries(core, "deny", step):
        raise CoreUnreadable("%s is missing, unreadable or gives no rule"
                             % os.path.join(PRESETS, "core.json"))
    team = layered(root, tree, ".sclaude", "team", "policy.json") if root and layers else {}
    # A person's own file breaks only that person's layer: it adds bans and
    # lifts nothing, so dropping it alone is safe, and the team's stays.
    try:
        mine = layered(root, tree, ".sclaude", "people", person, "policy.json") \
            if root and person and layers else {}
    except ValueError as exc:
        sys.stderr.write("sclaude policy: %s; your own rules are left out\n" % exc)
        mine = {}

    names = team.get("integrations")
    if not isinstance(names, list):
        names = detected_integrations(root) if root else []
    integrations = {n: read(os.path.join(PRESETS, "%s.json" % n))
                    for n in names if isinstance(n, str) and n.replace("-", "").isalnum()}

    def with_source(layer, key, source):
        return [(w, why, source, raw) for w, why, raw in entries(layer, key, step)]

    hard = with_source(core, "deny", "core")
    lifts = [w for w, _, _ in entries(team, "allow", step)]

    def lifted(words):
        return any(words[:len(l)] == l for l in lifts)

    deny = list(hard)
    rules, tools = [], []
    for name, layer in integrations.items():
        deny += [d for d in with_source(layer, "deny", name) if not lifted(d[0])]
        rules += [r for r in as_list(layer.get("rules")) if isinstance(r, str)]
        tools += [t for t in as_list(as_dict(layer.get("tools")).get("deny")) if isinstance(t, str)]
    # The production commands the product names in .sclaude/config.json, liftable by
    # the team like an integration's.
    for where in [root] + ([tree] if tree and os.path.realpath(tree) != os.path.realpath(root or tree) else []):
        try:
            named = config_denies(where)
        except ValueError as exc:
            # A config that is broken loses only its own production commands,
            # said here: raising failed the whole merge, and the fallback to
            # the presets threw away the team's and the person's rules, valid
            # as they were.
            sys.stderr.write("sclaude policy: %s; its production commands are not banned\n" % exc)
            continue
        deny += [d for d in with_source(named, "deny", "config") if not lifted(d[0])]
    deny += with_source(team, "deny", "team")
    deny += with_source(mine, "deny", "person")

    allow = with_source(team, "allow", "team") + with_source(mine, "allow", "person")
    # An allow never undoes a deny in a layer it cannot lift.
    blocked = [d[0] for d in deny]
    allow = [a for a in allow if not any(a[0][:len(b)] == b for b in blocked)]

    return {
        "deny": [{"words": list(w), "command": raw, "why": why, "from": src}
                 for w, why, src, raw in deny],
        "allow": [{"words": list(w), "command": raw, "why": why, "from": src}
                  for w, why, src, raw in allow],
        "rules": sorted(set(rules)),
        "lifted": [list(l) for l in lifts],
        "tools": sorted(set(tools)),
        "integrations": sorted(integrations),
    }


def claude_rule(command):
    """A Claude permission rule for the command as the policy writes it."""
    return "Bash(%s:*)" % command


def main(argv):
    if len(argv) < 3 or argv[0] not in ("json", "flags"):
        sys.stderr.write(__doc__ or "")
        return 2
    root, person = argv[1], argv[2]
    step = argv[3] if len(argv) > 3 else ""
    tree = argv[4] if len(argv) > 4 else ""
    policy = merged(root, person, step, tree)
    if argv[0] == "json":
        print(json.dumps(policy, ensure_ascii=False))
        return 0
    for d in policy["deny"]:
        print(claude_rule(d["command"]))
    for t in policy["tools"]:
        print(t)
    print("")
    for a in policy["allow"]:
        print(claude_rule(a["command"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
