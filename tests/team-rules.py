#!/usr/bin/env python3
#
# A product's shared sclaude rules belong to its maintainers.
#
#   * product_maintainer reads `maintainers` from the product's .sclaude.json
#     against the product repository's own git address; no list, or an empty
#     one, makes everybody a maintainer;
#   * product_rules_dir sends a maintainer to .sclaude/team/ and everybody else
#     to .sclaude/people/<name>/;
#   * team-rules.py refuses a write into .sclaude/team/, by a tool or through
#     Bash, and lets reading and every other path through;
#   * the hook is attached only to a non-maintainer's sessions: a step's
#     settings carry it, and so does the settings a friction review or a
#     retrospective is given.
#
# Run it with: python3 tests/team-rules.py
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
HOOK = os.path.join(ROOT, "sclaude", "hooks", "team-rules.py")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def hook(tool, **data):
    out = subprocess.run([sys.executable, HOOK], input=json.dumps(
        {"tool_name": tool, "tool_input": data}), capture_output=True, text=True)
    return "deny" if '"deny"' in out.stdout else "allow"


# --- the hook ------------------------------------------------------------------
for path, want in (("/r/.sclaude/team/policy.json", "deny"),
                   (".sclaude/team/x.md", "deny"),
                   ("/r/.sclaude/people/ann/policy.json", "allow"),
                   ("/r/.sclaude/local/terminal/x.log", "allow"),
                   ("/r/src/team/x.ts", "allow"),
                   ("/r/.sclaude/teams.md", "allow")):
    check("write %s" % path, hook("Write", file_path=path), want)
    check("edit %s" % path, hook("Edit", file_path=path), want)
check("notebook", hook("NotebookEdit", notebook_path="/r/.sclaude/team/n.ipynb"), "deny")

for command, want in (("echo x > .sclaude/team/a.md", "deny"),
                      ("echo x >>.sclaude/team/a.md", "deny"),
                      ("cat a | tee /r/.sclaude/team/a.md", "deny"),
                      ("cp mine.md .sclaude/team/", "deny"),
                      ("mv .sclaude/people/ann/r.md .sclaude/team/r.md", "deny"),
                      ("rm .sclaude/team/old.md", "deny"),
                      ("sed -i s/a/b/ .sclaude/team/a.md", "deny"),
                      ("git checkout main -- .sclaude/team", "deny"),
                      ("cat .sclaude/team/a.md", "allow"),
                      ("grep -r rule .sclaude/team", "allow"),
                      ("git log -- .sclaude/team", "allow"),
                      ("echo x > .sclaude/people/ann/a.md", "allow"),
                      ("npm test", "allow")):
    check("bash %s" % command, hook("Bash", command=command), want)


# --- who maintains, and where rules go -----------------------------------------
def sh(script, cwd, env=None):
    body = ('source "%s/developer.sh"; source "%s/steps.sh"; HOOKS=/hooks\n%s'
            % (LIB, LIB, script))
    full = dict(os.environ, **(env or {}))
    full.pop("SCLAUDE_DEV", None)
    if env:
        full.update(env)
    return subprocess.run(["bash", "-c", body], cwd=cwd, capture_output=True,
                          text=True, env=full).stdout.strip()


tmp = tempfile.mkdtemp()
try:
    repo = os.path.join(tmp, "product")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "Ann@X.test"], check=True)
    config = os.path.join(repo, ".sclaude.json")

    def setup(maintainers):
        with open(config, "w") as fh:
            json.dump({} if maintainers is None else {"maintainers": maintainers}, fh)

    ask = 'product_maintainer "%s" && echo yes || echo no' % repo
    setup(None)
    check("no-list-everybody", sh(ask, repo), "yes")
    setup([])
    check("empty-list-everybody", sh(ask, repo), "yes")
    setup(["ann@x.test"])
    check("listed-any-case", sh(ask, repo), "yes")
    setup(["lead@x.test"])
    check("not-listed", sh(ask, repo), "no")

    where = 'product_rules_dir "%s"' % repo
    setup(["ann@x.test"])
    check("maintainer-writes-team", sh(where, repo), os.path.join(repo, ".sclaude", "team"))
    setup(["lead@x.test"])
    check("others-write-their-own", sh(where, repo, {"SCLAUDE_DEV": "ann"}),
          os.path.join(repo, ".sclaude", "people", "ann"))

    # The hook goes only to a non-maintainer's sessions.
    setup(["ann@x.test"])
    check("maintainer-no-guard", sh('team_guard_settings "%s"' % repo, repo), "")
    setup(["lead@x.test"])
    guard = sh('team_guard_settings "%s"' % repo, repo).splitlines()
    check("guard-is-a-settings-flag", guard[:1], ["--settings"])
    if len(guard) > 1:
        entry = json.loads(guard[1])["hooks"]["PreToolUse"][0]
        check("guard-covers-tools-and-bash", entry["matcher"],
              "Write|Edit|MultiEdit|NotebookEdit|Bash")
        check("guard-runs-the-hook", "team-rules.py" in entry["hooks"][0]["command"], True)

    # A step's settings carry it next to forbidden-commands.py.
    flags = sh('BROWSER_ALLOW=x; step_settings code "%s"' % repo, repo).splitlines()
    settings = json.loads(flags[flags.index("--settings") + 1])
    commands = [h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]]
    check("step-has-both-hooks", [any("forbidden-commands" in c for c in commands),
                                  any("team-rules" in c for c in commands)], [True, True])
    setup(["ann@x.test"])
    flags = sh('BROWSER_ALLOW=x; step_settings code "%s"' % repo, repo).splitlines()
    settings = json.loads(flags[flags.index("--settings") + 1])
    check("maintainer-step-without-guard",
          any("team-rules" in h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]),
          False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
