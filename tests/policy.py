#!/usr/bin/env python3
#
# The layers of what a session may run (sclaude/lib/policy.py), and the hook
# that enforces them.
#
#   * core.json's rules hold whatever a product or a person says;
#   * an integration's preset is on when the team lists it, or, while the team
#     lists nothing, when the product evidently uses it; off otherwise;
#   * the team's `allow` lifts an integration's deny or rule, and nothing of
#     core.json;
#   * a person adds bans and permissions of their own, and lifts nothing the
#     team or an integration denies;
#   * a product names its own commands: no product command is banned by sclaude
#     itself any more.
#
# Run it with: python3 tests/policy.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib"))
import policy  # noqa: E402

HOOK = os.path.join(ROOT, "sclaude", "hooks", "forbidden-commands.py")
failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def write(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh)


def verdict(root, command, person="", step="review", tree=""):
    argv = [sys.executable, HOOK, "--step", step, "--root", root, "--person", person]
    if tree:
        argv += ["--tree", tree]
    env = dict(os.environ)
    env.pop("SUPABASE_WORKDIR", None)
    out = subprocess.run(argv, input=json.dumps({"tool_name": "Bash",
                         "tool_input": {"command": command}}), text=True,
                         capture_output=True, env=env, cwd=root).stdout
    return "deny" if '"deny"' in out else "allow"


tmp = tempfile.mkdtemp()
try:
    # --- a product that says nothing and uses nothing ---
    bare = os.path.join(tmp, "bare")
    os.makedirs(bare)
    check("bare-merge-banned", verdict(bare, "gh pr merge 1"), "deny")
    check("bare-no-vercel-preset", verdict(bare, "vercel --prod"), "allow")
    check("bare-no-product-bans", verdict(bare, "npm run db:promote"), "allow")
    check("bare-code-step-no-pr", verdict(bare, "gh pr create", step="code"), "deny")
    check("bare-review-step-pr", verdict(bare, "gh pr create"), "allow")

    # --- detected while the team lists nothing ---
    detected = os.path.join(tmp, "detected")
    os.makedirs(os.path.join(detected, ".vercel"))
    check("detected-vercel", policy.merged(detected)["integrations"], ["vercel"])
    check("detected-vercel-deploy-banned", verdict(detected, "vercel --prod"), "deny")
    check("detected-vercel-read-allowed", verdict(detected, "vercel env ls"), "allow")
    # ...and once the team names its integrations, that list is the answer.
    write(detected, ".sclaude/team/policy.json", {"integrations": []})
    check("declared-none", policy.merged(detected)["integrations"], [])
    check("declared-none-deploys", verdict(detected, "vercel --prod"), "allow")

    # --- a team's rules, a person's rules ---
    team = os.path.join(tmp, "team")
    write(team, ".sclaude/team/policy.json", {
        "integrations": ["vercel", "supabase"],
        "deny": [{"command": "npm run db:promote", "why": "prod migrations"}],
        "allow": [{"command": "vercel deploy", "why": "previews are ours"},
                  {"command": "gh pr merge", "why": "trying to lift core"},
                  {"command": "npm run check:storage", "why": "dev bucket only"}],
    })
    write(team, ".sclaude/people/ann/policy.json", {
        "deny": [{"command": "npm run seed", "why": "I keep my data"}],
        "allow": [{"command": "npm run db:promote", "why": "trying to lift the team"},
                  {"command": "npm run storybook", "why": "mine"}],
    })
    check("team-ban", verdict(team, "npm run db:promote"), "deny")
    check("team-ban-wrapped", verdict(team, "timeout 5 npx npm run db:promote"), "deny")
    check("team-lifts-integration", verdict(team, "vercel deploy --prebuilt"), "allow")
    check("team-lift-is-narrow", verdict(team, "vercel --prod"), "deny")
    check("team-cannot-lift-core", verdict(team, "gh pr merge 3"), "deny")
    check("person-cannot-lift-team", verdict(team, "npm run db:promote", person="ann"), "deny")
    check("person-adds-a-ban", verdict(team, "npm run seed", person="ann"), "deny")
    check("person-ban-is-theirs", verdict(team, "npm run seed", person="bob"), "allow")
    merged = policy.merged(team, "ann")
    allowed = [" ".join(a["words"]) for a in merged["allow"]]
    check("allow-becomes-permission", sorted(allowed),
          ["npm run check:storage", "npm run storybook", "vercel deploy"])
    check("supabase-tools-off", "mcp__plugin_supabase_supabase__apply_migration" in merged["tools"], True)

    # --- what .sclaude/config.json already names, banned from there ---
    conf = os.path.join(tmp, "conf")
    write(conf, ".sclaude/config.json", {"database": {"promote": "npm run db:promote"}})
    write(conf, ".sclaude/team/policy.json", {
        "deny": [{"command": "node scripts/tool.mjs prod", "why": "the script under env:prod"}]})
    check("config-promote-banned", verdict(conf, "npm run db:promote"), "deny")
    # A package script however it is spelled: a review found `npm --silent run
    # x`, `npm run --silent x` and `pnpm run x` past a ban on `npm run x`.
    for spelled in ("npm --silent run db:promote", "npm run --silent db:promote",
                    "pnpm run db:promote", "yarn run db:promote", "bun run db:promote",
                    "npm --prefix . run db:promote", "npm run db:promote -- --yes",
                    "pnpm db:promote", "yarn db:promote", "bun db:promote",
                    "yarn --silent db:promote"):
        check("config-promote-banned-as-%s" % spelled, verdict(conf, spelled), "deny")
    check("other-scripts-still-run", verdict(conf, "npm --silent run lint"), "allow")
    for other in ("pnpm lint", "yarn install", "pnpm dlx tsc", "npm db:promote"):
        check("not-the-promote-%s" % other, verdict(conf, other), "allow")
    check("path-rule-fires", verdict(conf, "node scripts/tool.mjs prod"), "deny")
    check("path-rule-fires-dotted", verdict(conf, "node ./scripts/tool.mjs prod --yes"), "deny")
    check("path-rule-narrow", verdict(conf, "node scripts/tool.mjs dev"), "allow")
    write(conf, ".sclaude/team/policy.json", {"allow": [{"command": "npm run env:prod", "why": "ours"}]})
    check("config-ban-liftable-by-team", verdict(conf, "npm run env:prod"), "allow")

    # --- a feature's tree: its rules count before main has them ---
    #
    # A friction review lifts a ban in the tree and commits it on the branch;
    # the next session of that feature must not meet the ban again. A ban main
    # has and the tree's copy lacks still holds.
    main = os.path.join(tmp, "main")
    tree = os.path.join(tmp, "main-feat")
    write(main, ".sclaude/team/policy.json", {"integrations": ["vercel"], "deny": [
        {"command": "npm run seed", "why": "main's"}]})
    write(tree, ".sclaude/team/policy.json", {"integrations": ["vercel"], "allow": [
        {"command": "vercel --prod", "why": "lifted by a review"}],
        "deny": [{"command": "npm run wipe", "why": "the tree's"}]})
    check("tree-lift-applies", verdict(main, "vercel --prod", tree=tree), "allow")
    check("tree-lift-not-without-tree", verdict(main, "vercel --prod"), "deny")
    check("tree-ban-applies", verdict(main, "npm run wipe", tree=tree), "deny")
    check("main-ban-still-applies", verdict(main, "npm run seed", tree=tree), "deny")
    out = subprocess.run([sys.executable, os.path.join(ROOT, "sclaude", "lib", "policy.py"),
                          "flags", main, "", "code", tree], capture_output=True, text=True).stdout
    check("tree-flags", "Bash(npm run wipe:*)" in out.splitlines(), True)
    # An integration main names and the branch's older copy does not still holds.
    write(main, ".sclaude/team/policy.json", {"integrations": ["vercel", "supabase"]})
    write(tree, ".sclaude/team/policy.json", {"integrations": ["vercel"]})
    merged_tree = policy.merged(main, "", "code", tree)
    check("tree-keeps-mains-integrations", merged_tree["integrations"], ["supabase", "vercel"])
    check("tree-keeps-mains-rules", "supabase-db-push" in merged_tree["rules"], True)
    # Nor does an empty list in the tree turn off what main evidently uses.
    found = os.path.join(tmp, "found-supabase")
    os.makedirs(os.path.join(found, "supabase"))
    write(found, ".sclaude/team/policy.json", {})
    write(tree, ".sclaude/team/policy.json", {"integrations": []})
    check("tree-keeps-detected", policy.merged(found, "", "code", tree)["integrations"], ["supabase"])

    # --- the flags a step is launched with ---
    out = subprocess.run([sys.executable, os.path.join(ROOT, "sclaude", "lib", "policy.py"),
                          "flags", team, "ann", "code"], capture_output=True, text=True).stdout
    denied, _, allowed_rules = out.partition("\n\n")
    check("flags-deny", "Bash(npm run db:promote:*)" in denied.splitlines(), True)
    check("flags-step", "Bash(gh pr create:*)" in denied.splitlines(), True)
    check("flags-tools", "mcp__plugin_supabase_supabase__apply_migration" in denied.splitlines(), True)
    check("flags-allow", "Bash(npm run storybook:*)" in allowed_rules.splitlines(), True)

    # --- no product command left in sclaude itself ---
    presets = " ".join(open(os.path.join(ROOT, "sclaude", "policy", n)).read()
                       for n in os.listdir(os.path.join(ROOT, "sclaude", "policy")))
    steps = open(os.path.join(ROOT, "sclaude", "lib", "steps.sh")).read()
    hook = open(HOOK).read()
    for name in ("db:promote", "env:prod", "env-guard.mjs", "environments.json"):
        check("no-%s-in-presets" % name, name in presets, False)
        check("no-%s-in-hook" % name, name in hook, False)
    for name in ("db:promote", "env:prod"):
        check("no-%s-in-steps" % name, name in steps, False)
    # --- a team file of the wrong shape keeps every ban ---
    #
    # `{"steps": ["code"]}` raised inside the merge, the hook died, Claude
    # Code ran the command, and --disallowed-tools came out empty too.
    broken = os.path.join(tmp, "broken")
    os.makedirs(os.path.join(broken, ".vercel"))
    for i, bad in enumerate(({"steps": ["code"]}, {"steps": {"code": ["x"]}},
                             {"deny": "gh"}, {"integrations": "vercel"},
                             {"tools": ["x"]}, {"deny": [{"command": "x", "why": 5}]})):
        write(broken, ".sclaude/team/policy.json", bad)
        check("broken-%d-merge-banned" % i, verdict(broken, "gh pr merge 1", step="code"), "deny")
        flags = subprocess.run([sys.executable, os.path.join(ROOT, "sclaude", "lib", "policy.py"), "flags",
                                broken, "", "code"], capture_output=True, text=True)
        check("broken-%d-flags-keep-merge" % i, "Bash(gh pr merge:*)" in flags.stdout, True)
    # Dropping the broken layer keeps what the product evidently uses.
    check("broken-keeps-integrations", policy.merge(broken, "", "code", layers=False)["integrations"],
          ["vercel"])

    # A team file that is not JSON is said, not read as an empty layer: the
    # product's bans go, and the person must hear it.
    bad = os.path.join(tmp, "bad-json")
    write(bad, ".sclaude/config.json", {})
    os.makedirs(os.path.join(bad, ".sclaude", "team"), exist_ok=True)
    with open(os.path.join(bad, ".sclaude", "team", "policy.json"), "w") as fh:
        fh.write('{"deny": [{"command": "npm run seed"}],}')
    done = subprocess.run([sys.executable, os.path.join(ROOT, "sclaude", "lib", "policy.py"),
                           "flags", bad, "", "code"], capture_output=True, text=True)
    check("bad-json-said", "not valid JSON" in done.stderr, True)
    check("bad-json-presets-hold", "Bash(gh pr merge:*)" in done.stdout, True)

    # A broken file in the session's tree, or a person's own, drops only that
    # layer: main's team rules hold.
    hold = os.path.join(tmp, "hold")
    hold_tree = os.path.join(tmp, "hold-feat")
    write(hold, ".sclaude/team/policy.json", {"deny": [{"command": "npm run seed", "why": "team"}]})
    os.makedirs(os.path.join(hold_tree, ".sclaude", "team"))
    with open(os.path.join(hold_tree, ".sclaude", "team", "policy.json"), "w") as fh:
        fh.write("{,")
    os.makedirs(os.path.join(hold_tree, ".sclaude", "people", "ann"))
    with open(os.path.join(hold_tree, ".sclaude", "people", "ann", "policy.json"), "w") as fh:
        fh.write("{,")
    with open(os.path.join(hold_tree, ".sclaude", "config.json"), "w") as fh:
        fh.write("{,")
    held = [" ".join(d["words"]) for d in policy.merged(hold, "ann", "code", hold_tree)["deny"]]
    check("broken-tree-keeps-team", "npm run seed" in held, True)
    # Nor does a broken config of the main checkout's.
    with open(os.path.join(hold, ".sclaude", "config.json"), "w") as fh:
        fh.write("{,")
    held = [" ".join(d["words"]) for d in policy.merged(hold, "", "code")["deny"]]
    check("broken-config-keeps-team", "npm run seed" in held, True)

    # A core.json that gives no rule is sclaude's own breakage: raised, not
    # read as an empty layer, and not blamed on the product.
    saved = policy.PRESETS
    for i, text in enumerate(('{"deny": [{"cmd": "gh pr merge"}]}', '{"deny": [""]}', "{")):
        presets = os.path.join(tmp, "presets-%d" % i)
        os.makedirs(presets)
        with open(os.path.join(presets, "core.json"), "w") as fh:
            fh.write(text)
        policy.PRESETS = presets
        try:
            policy.merged(bare, "", "code")
            raised = None
        except policy.CoreUnreadable as exc:
            raised = str(exc)
        check("core-unreadable-%d" % i, bool(raised) and "core.json" in raised, True)
    policy.PRESETS = saved
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
