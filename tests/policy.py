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


def verdict(root, command, person="", step="review"):
    argv = [sys.executable, HOOK, "--step", step, "--root", root, "--person", person]
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
                  {"command": "npm run check:r2", "why": "dev bucket only"}],
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
          ["npm run check:r2", "npm run storybook", "vercel deploy"])
    check("supabase-tools-off", "mcp__plugin_supabase_supabase__apply_migration" in merged["tools"], True)

    # --- what .sclaude.json already names, banned from there ---
    conf = os.path.join(tmp, "conf")
    write(conf, ".sclaude.json", {"database": {"promote": "npm run db:promote",
                                               "envProd": "npm run env:prod"}})
    write(conf, ".sclaude/team/policy.json", {
        "deny": [{"command": "node scripts/env.mjs prod", "why": "the script under env:prod"}]})
    check("config-promote-banned", verdict(conf, "npm run db:promote"), "deny")
    check("config-envprod-banned", verdict(conf, "npx npm run env:prod"), "deny")
    check("path-rule-fires", verdict(conf, "node scripts/env.mjs prod"), "deny")
    check("path-rule-fires-dotted", verdict(conf, "node ./scripts/env.mjs prod --yes"), "deny")
    check("path-rule-narrow", verdict(conf, "node scripts/env.mjs dev"), "allow")
    write(conf, ".sclaude/team/policy.json", {"allow": [{"command": "npm run env:prod", "why": "ours"}]})
    check("config-ban-liftable-by-team", verdict(conf, "npm run env:prod"), "allow")

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
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
