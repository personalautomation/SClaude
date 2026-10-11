#!/usr/bin/env python3
#
# A product's shared sclaude rules belong to its maintainers.
#
#   * product_maintainer reads `maintainers` from the product's .sclaude/config.json
#     against the product repository's own git address; no list, or an empty
#     one, makes everybody a maintainer;
#   * product_rules_dir sends a maintainer to .sclaude/team/ and everybody else
#     to .sclaude/people/<name>/;
#   * write-guard.py refuses a write into .sclaude/team/, by a tool or through
#     Bash, and lets reading and every other path through;
#   * the hook is attached only to a non-maintainer's sessions: a step's
#     settings carry it, and so does the settings a friction review or a
#     retrospective is given.
#
# Run it with: python3 tests/write-guard.py
import json
import shlex
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
HOOK = os.path.join(ROOT, "sclaude", "hooks", "write-guard.py")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def hook(tool, args=("--team",), cwd="/r", **data):
    out = subprocess.run([sys.executable, HOOK] + list(args), input=json.dumps(
        {"tool_name": tool, "tool_input": data, "cwd": cwd}), capture_output=True, text=True)
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


# --- read-only: sclaude's own checkout, for the review sessions ---------------
RO = ("--readonly", "/home/u/sclaude")
for command, cwd, want in (
        ("echo x > sclaude/lib/run.sh", "/home/u/sclaude", "deny"),
        ("sed -i s/a/b/ sclaude/lib/run.sh", "/home/u/sclaude", "deny"),
        ("git commit -qm fix", "/home/u/sclaude", "deny"),
        ("git -C /home/u/sclaude add -A", "/home/u/myapp-1", "deny"),
        ("cd /home/u/sclaude && git reset --hard", "/home/u/myapp-1", "deny"),
        ("cp /tmp/x /home/u/sclaude/README.md", "/tmp", "deny"),
        # git's own options before the subcommand, and a wrapper in front: a
        # review got all of these past the guard while `git commit` alone
        # was refused.
        ("git -c user.name=x commit -m x", "/home/u/sclaude", "deny"),
        ("git -c core.hooksPath=/dev/null commit -am x", "/home/u/sclaude", "deny"),
        ("sudo git commit -m x", "/home/u/sclaude", "deny"),
        ("command git commit -m x", "/home/u/sclaude", "deny"),
        ("env GIT_X=1 git commit -m x", "/home/u/sclaude", "deny"),
        ("timeout 5 git -C . add -A", "/home/u/sclaude", "deny"),
        ("git --work-tree=/home/u/sclaude checkout -- .", "/tmp", "deny"),
        ("sudo rm sclaude/x", "/home/u/sclaude", "deny"),
        ("env X=1 cp /tmp/a sclaude/x", "/home/u/sclaude", "deny"),
        # Inside a group, an `if` or a loop.
        ("(git commit -am x)", "/home/u/sclaude", "deny"),
        ("{ git commit -am x; }", "/home/u/sclaude", "deny"),
        ("if true; then git commit -m y; fi", "/home/u/sclaude", "deny"),
        ("(cd /home/u/myapp-1) && git commit -m x", "/home/u/sclaude", "deny"),
        ("{ cd /home/u/myapp-1; } && git commit -m x", "/home/u/sclaude", "deny"),
        # The right target: past a redirection, after -t, stuck to `>`, and
        # in-place flags bundled with others.
        ("cp evil /home/u/sclaude/x > /tmp/log", "/tmp", "deny"),
        ("cp -t /home/u/sclaude a b", "/tmp", "deny"),
        ("echo hi>/home/u/sclaude/f", "/tmp", "deny"),
        ("perl -pi -e 's/a/b/' /home/u/sclaude/f", "/tmp", "deny"),
        ("sed -Ei 's/a/b/' /home/u/sclaude/f", "/tmp", "deny"),
        # git that changes the checkout without a commit: its remote, its refs.
        ("git -C /home/u/sclaude remote set-url origin x", "/tmp", "deny"),
        ("cd /home/u/sclaude && git fetch", "/tmp", "deny"),
        # A relative `cd` from an unknown place is still unknown.
        ('cd "$X" && cd sub && echo x > f', "/home/u/myapp-1", "deny"),
        # Reading it, and writing the product, from inside it or not.
        ("cat sclaude/lib/run.sh", "/home/u/sclaude", "allow"),
        ("git log --oneline -5", "/home/u/sclaude", "allow"),
        ("git diff HEAD~1", "/home/u/sclaude", "allow"),
        ("cd /home/u/myapp-1 && echo x > notes.md", "/home/u/sclaude", "allow"),
        ("cd /home/u/myapp-1 && git commit -qm fix", "/home/u/sclaude", "allow"),
        ("git -C /home/u/myapp-1 commit -qm fix", "/home/u/sclaude", "allow"),
        ("git -c user.name=x -C /home/u/myapp-1 commit -qm fix", "/home/u/sclaude", "allow"),
        ("sudo git -C /home/u/myapp-1 commit -qm fix", "/home/u/sclaude", "allow"),
        ("(cd /home/u/myapp-1 && git commit -m x)", "/home/u/sclaude", "allow"),
        ("cd /home/u/myapp-1 && (git commit -m x)", "/home/u/sclaude", "allow"),
        ("git -C /home/u/sclaude remote -v", "/tmp", "allow"),
        ("sed -n 1,5p /home/u/sclaude/lib/run.sh", "/tmp", "allow"),
        ("grep -n foo /home/u/sclaude/lib/run.sh", "/tmp", "allow"),
        ("cp /home/u/sclaude/a /tmp/b", "/tmp", "allow"),
        ("cp sclaude/policy/vercel.json /home/u/myapp-1/.sclaude/team/", "/home/u/sclaude", "allow"),
        ("echo x > /home/u/myapp-1/.sclaude/team/policy.json", "/home/u/sclaude", "allow")):
    check("readonly %s (in %s)" % (command, cwd), hook("Bash", RO, cwd, command=command), want)
check("readonly write tool", hook("Write", RO, "/x", file_path="/home/u/sclaude/a.py"), "deny")
check("readonly relative write tool", hook("Edit", RO, "/home/u/sclaude", file_path="sclaude/a.py"), "deny")
check("readonly product write", hook("Write", RO, "/home/u/sclaude", file_path="/home/u/myapp-1/x.ts"), "allow")
# Both together: a non-maintainer's review.
check("both team", hook("Bash", RO + ("--team",), "/home/u/sclaude",
                        command="echo x > /home/u/myapp-1/.sclaude/team/p.json"), "deny")


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
    config = os.path.join(repo, ".sclaude/config.json")
    os.makedirs(os.path.dirname(config))

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

    # A step's team guard goes only to a non-maintainer; a review's read-only
    # guard goes to everybody, with --team added for a non-maintainer.
    setup(["ann@x.test"])
    check("maintainer-no-step-guard", sh('team_guard_entry "%s"' % repo, repo), "")
    for maintainer, team in ((["ann@x.test"], False), (["lead@x.test"], True)):
        setup(maintainer)
        guard = sh('INSTRUMENTS=/opt/sclaude; review_guard_settings "%s"' % repo, repo).splitlines()
        check("review-guard-is-a-settings-flag-%s" % team, guard[:1], ["--settings"])
        if len(guard) > 1:
            entry = json.loads(guard[1])["hooks"]["PreToolUse"][0]
            command = entry["hooks"][0]["command"]
            check("review-guard-matcher-%s" % team, entry["matcher"],
                  "Write|Edit|MultiEdit|NotebookEdit|Bash")
            check("review-guard-readonly-%s" % team, "--readonly /opt/sclaude" in command, True)
            check("review-guard-team-%s" % team, "--team" in command, team)
    setup(["lead@x.test"])

    # A step's settings carry it next to forbidden-commands.py.
    flags = sh('BROWSER_ALLOW=x; step_settings code "%s"' % repo, repo).splitlines()
    settings = json.loads(flags[flags.index("--settings") + 1])
    commands = [h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]]
    check("step-has-both-hooks", [any("forbidden-commands" in c for c in commands),
                                  any("write-guard" in c for c in commands)], [True, True])
    setup(["ann@x.test"])
    flags = sh('BROWSER_ALLOW=x; step_settings code "%s"' % repo, repo).splitlines()
    settings = json.loads(flags[flags.index("--settings") + 1])
    check("maintainer-step-without-guard",
          any("write-guard" in h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]),
          False)
    # A checkout whose path has a space: Claude Code runs the hook through a
    # shell, and the unquoted path split there.
    entry = json.loads(sh('HOOKS="/opt/my tools/hooks"; guard_entry --readonly /x', repo))
    words = shlex.split(entry["hooks"][0]["command"])
    check("guard-path-with-space", words[:2], ["python3", "/opt/my tools/hooks/write-guard.py"])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
