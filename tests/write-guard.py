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
check("write through ..", hook("Write", file_path="/r/.sclaude/people/../team/policy.json"), "deny")

for command, want in (("echo x > .sclaude/team/a.md", "deny"),
                      ("echo x >>.sclaude/team/a.md", "deny"),
                      ("cat a | tee /r/.sclaude/team/a.md", "deny"),
                      ("cp mine.md .sclaude/team/", "deny"),
                      ("mv .sclaude/people/ann/r.md .sclaude/team/r.md", "deny"),
                      ("rm .sclaude/team/old.md", "deny"),
                      ("sed -i s/a/b/ .sclaude/team/a.md", "deny"),
                      ("git checkout main -- .sclaude/team", "deny"),
                      # From the directory it runs in, and through git.
                      ("cd .sclaude/team && echo x > policy.json", "deny"),
                      ("cd /r/.sclaude && rm team/policy.json", "deny"),
                      ("git rm .sclaude/team/policy.json", "deny"),
                      ("git mv .sclaude/team/a.md .sclaude/people/ann/a.md", "deny"),
                      ("git -C /r rm .sclaude/team/policy.json", "deny"),
                      ("git -C .sclaude/team checkout -- policy.json", "deny"),
                      ("git -C .sclaude/team rm policy.json", "deny"),
                      ("git -C .sclaude/people/ann rm old.md", "allow"),
                      ("cd .sclaude/people/ann && echo x > policy.json", "allow"),
                      ("git rm .sclaude/people/ann/old.md", "allow"),
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
        # The read-only forms of subcommands that otherwise write.
        ("git stash list", "/home/u/sclaude", "allow"),
        ("git stash show -p", "/home/u/sclaude", "allow"),
        ("git branch --list", "/home/u/sclaude", "allow"),
        ("git branch -a", "/home/u/sclaude", "allow"),
        ("git branch --show-current", "/home/u/sclaude", "allow"),
        ("git config user.email", "/home/u/sclaude", "allow"),
        ("git config --get remote.origin.url", "/home/u/sclaude", "allow"),
        ("git config -l", "/home/u/sclaude", "allow"),
        ("git tag -l", "/home/u/sclaude", "allow"),
        ("git tag", "/home/u/sclaude", "allow"),
        ("git worktree list", "/home/u/sclaude", "allow"),
        ("git stash", "/home/u/sclaude", "deny"),
        ("git stash pop", "/home/u/sclaude", "deny"),
        ("git branch x", "/home/u/sclaude", "deny"),
        ("git branch -D x", "/home/u/sclaude", "deny"),
        ("git branch -l -d x", "/home/u/sclaude", "deny"),
        ("git config user.email a@b", "/home/u/sclaude", "deny"),
        ("git config --unset user.email", "/home/u/sclaude", "deny"),
        ("git tag v1", "/home/u/sclaude", "deny"),
        ("git worktree add ../x", "/home/u/sclaude", "deny"),
        # Writes it used to miss: what mv moves away, dd's of=, and a
        # redirection with no command in front.
        ("mv /home/u/sclaude/file /tmp/", "/tmp", "deny"),
        ("dd if=/dev/zero of=/home/u/sclaude/f", "/tmp", "deny"),
        ("> /home/u/sclaude/f", "/tmp", "deny"),
        ("echo hi && >/home/u/sclaude/f", "/tmp", "deny"),
        ("dd if=/home/u/sclaude/f of=/tmp/x", "/tmp", "allow"),
        # Reads it used to refuse.
        ("perl -Mstrict -ne print /home/u/sclaude/f", "/tmp", "allow"),
        ("perl -Ilib -e 1 /home/u/sclaude/f", "/tmp", "allow"),
        ("perl -pi -e 's/a/b/' /home/u/sclaude/f", "/tmp", "deny"),
        ("perl -0777pi.bak -e 1 /home/u/sclaude/f", "/tmp", "deny"),
        ("git -C /home/u/sclaude branch --contains HEAD", "/tmp", "allow"),
        ("git -C /home/u/sclaude branch --merged main", "/tmp", "allow"),
        ("git -C /home/u/sclaude tag --points-at HEAD", "/tmp", "allow"),
        ("git -C /home/u/sclaude tag --contains HEAD", "/tmp", "allow"),
        ("(cd /home/u/sclaude; ls) > out.txt", "/home/u/myapp-1", "allow"),
        ("(cd /home/u/myapp-1; ls) > out.txt", "/home/u/sclaude", "deny"),
        ("(x=$(cat f); ls) > out.txt", "/home/u/myapp-1", "allow"),
        # Inside a shell string, eval and a substitution, writes still count.
        ('bash -c "echo x > /home/u/sclaude/f"', "/tmp", "deny"),
        ("sh -c 'rm /home/u/sclaude/f'", "/tmp", "deny"),
        ("eval rm /home/u/sclaude/f", "/tmp", "deny"),
        ("echo $(tee /home/u/sclaude/f </dev/null)", "/tmp", "deny"),
        ("x=`rm /home/u/sclaude/f`", "/tmp", "deny"),
        ('bash -c "cat /home/u/sclaude/f"', "/tmp", "allow"),
        ("echo $(git -C /home/u/sclaude log -1)", "/tmp", "allow"),
        # A substitution after a cd runs where the cd went.
        ("cd /home/u/sclaude && out=$(git pull 2>&1)", "/home/u/myapp-1", "deny"),
        ("cd /home/u/sclaude && x=$(echo hi > f)", "/home/u/myapp-1", "deny"),
        ("cd /home/u/myapp-1 && x=$(echo hi > f)", "/home/u/sclaude", "deny"),
        ("cd /home/u/myapp-1 && x=$(git rev-parse HEAD)", "/home/u/myapp-1", "allow"),
        # pushd leaves the directory unknown, and unknown is the checkout.
        ("pushd /home/u/sclaude && echo x > f", "/home/u/myapp-1", "deny"),
        # Git that rewrites the tree or makes a new one there.
        ("git -C /home/u/sclaude bisect start", "/tmp", "deny"),
        ("git -C /home/u/sclaude read-tree -u HEAD~1", "/tmp", "deny"),
        ("cd /home/u/sclaude && git checkout-index -a -f", "/tmp", "deny"),
        ("git clone https://x/r /home/u/sclaude/new", "/tmp", "deny"),
        ("git clone https://x/r /tmp/new", "/tmp", "allow"),
        # Writes this guard used to miss: a clobbering redirection, the
        # repository named in the environment, sed's long script flag.
        ("echo x >| /home/u/sclaude/f", "/tmp", "deny"),
        ("GIT_DIR=/home/u/sclaude/.git git commit -m x", "/tmp", "deny"),
        ("env GIT_DIR=/home/u/sclaude/.git git add .", "/tmp", "deny"),
        ("GIT_DIR=/home/u/myapp-1/.git git commit -m x", "/tmp", "allow"),
        ("GIT_DIR=/home/u/sclaude/.git git log", "/tmp", "allow"),
        ("sed -i --expression=s/a/b/ /home/u/sclaude/f", "/tmp", "deny"),
        # Every place a git call changes, and cd's options.
        ("git --git-dir=/home/u/sclaude/.git --work-tree=/tmp commit -am x", "/tmp", "deny"),
        ("GIT_DIR=/home/u/sclaude/.git git -C /tmp commit -am x", "/tmp", "deny"),
        ("GIT_DIR=/home/u/sclaude/.git git -c a=b commit -am x", "/tmp", "deny"),
        ("cd -P /home/u/sclaude && echo x > f", "/home/u/myapp-1", "deny"),
        ("cd -- /home/u/sclaude && echo x > f", "/home/u/myapp-1", "deny"),
        ("cd - && echo x > f", "/home/u/myapp-1", "deny"),
        ("cd -P /home/u/myapp-1 && echo x > f", "/home/u/sclaude", "allow"),
        # A function's body and a case branch are judged as well.
        ("f() { rm /home/u/sclaude/README.md; }; f", "/tmp", "deny"),
        ("function f { rm /home/u/sclaude/README.md; }", "/tmp", "deny"),
        ("case x in x) rm /home/u/sclaude/README.md;; esac", "/tmp", "deny"),
        ("f() { cat /home/u/sclaude/README.md; }; f", "/tmp", "allow"),
        ("if true; then f() { rm /home/u/sclaude/R; }; fi", "/tmp", "deny"),
        ("{ f() { rm /home/u/sclaude/R; }; }", "/tmp", "deny"),
        ("f () { rm /home/u/sclaude/R; }", "/tmp", "deny"),
        # A subshell closing inside a case branch still ends its cd.
        ("case x in x) (cd /home/u/myapp-1; true); echo x > f;; esac", "/home/u/sclaude", "deny"),
        # A target with a variable: set in the line, from the environment,
        # or unknown, which counts as inside.
        ("RO=/home/u/sclaude; echo x > $RO/f", "/tmp", "deny"),
        ("echo x > ${UNSET_ANYWHERE_X}/f", "/tmp", "deny"),
        ("for f in /home/u/sclaude/*.md; do rm \"$f\"; done", "/tmp", "deny"),
        ("D=/home/u/myapp-1; echo x > $D/f", "/tmp", "allow"),
        ("f(){ rm /home/u/sclaude/x; }; f", "/tmp", "deny"),
        ("git -C /home/u/sclaude branch --sort=refname newb", "/tmp", "deny"),
        ("bash -c -- \"rm /home/u/sclaude/x\"", "/tmp", "deny"),
        # A bracket in quotes closes no group.
        ('echo "a)" > notes.txt', "/home/u/myapp-1", "allow"),
        ("echo '(x' && echo y > notes.txt", "/home/u/myapp-1", "allow"),
        # A `>` in quotes is text, not a redirection.
        ('cd /home/u/myapp-1 && git commit -m "a -> b"', "/home/u/sclaude", "allow"),
        ("git log --format='%h>%s'", "/home/u/sclaude", "allow"),
        ('echo "a -> b" > /home/u/sclaude/f', "/tmp", "deny"),
        ('echo x > "/home/u/sclaude/a>b"', "/tmp", "deny"),
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
    body = ('source "%s/developer.sh"; source "%s/steps.sh"; HOOKS=/hooks; LIB="%s"\n'
            'warn() { echo "WARN $*" >&2; }\n%s' % (LIB, LIB, LIB, script))
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
    # A config that cannot be read makes nobody a maintainer, not everybody.
    with open(config, "w") as fh:
        fh.write('{"maintainers": ["ann@x.test"],}')
    check("broken-config-nobody", sh(ask, repo), "no")
    with open(config, "w") as fh:
        fh.write('["ann@x.test"]')
    check("non-object-config-nobody", sh(ask, repo), "no")
    # The list is main's, not the tree's: a session editing its tree's copy
    # does not make itself a maintainer.
    setup(["lead@x.test"])
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "commit", "-qm", "config"], check=True)
    origin = os.path.join(tmp, "origin.git")
    subprocess.run(["git", "clone", "-q", "--bare", repo, origin], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", origin], check=True)
    subprocess.run(["git", "-C", repo, "fetch", "-q", "origin"], check=True)
    subprocess.run(["git", "-C", repo, "update-ref", "refs/remotes/origin/main",
                    subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True,
                                   text=True).stdout.strip()], check=True)
    setup(["ann@x.test"])
    check("tree-edit-not-a-maintainer", sh(ask, repo), "no")
    setup([])
    check("tree-emptied-not-everybody", sh(ask, repo), "no")
    subprocess.run(["git", "-C", repo, "remote", "remove", "origin"], check=True)

    where = 'product_rules_dir "%s"' % repo
    setup(["ann@x.test"])
    check("maintainer-writes-team", sh(where, repo), os.path.join(repo, ".sclaude", "team"))
    setup(["lead@x.test"])
    check("others-write-their-own", sh(where, repo, {"SCLAUDE_DEV": "ann"}),
          os.path.join(repo, ".sclaude", "people", "ann"))

    # A step's team guard goes to everybody, a maintainer included: a step that
    # wrote an allow into the team's rules freed itself. A review's read-only
    # guard goes to everybody too, with --team added for a non-maintainer.
    setup(["ann@x.test"])
    check("maintainer-step-guard", "--team" in sh('team_guard_entry "%s"' % repo, repo), True)
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
            # The step bans hold in a review too: it runs in the product's tree.
            hooks = json.loads(guard[1])["hooks"]["PreToolUse"]
            check("review-guard-has-the-bans-%s" % team,
                  any("forbidden-commands.py" in h["hooks"][0]["command"] for h in hooks), True)
            check("review-guard-flags-the-merge-%s" % team,
                  "--disallowed-tools" in guard and "Bash(gh pr merge:*)" in guard[guard.index("--disallowed-tools") + 1],
                  True)
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
    check("maintainer-step-guarded",
          any("write-guard" in h["hooks"][0]["command"] for h in settings["hooks"]["PreToolUse"]),
          True)
    # Whatever a review session did to sclaude's checkout is noticed after
    # it, by every command the guard cannot name.
    inst = os.path.join(tmp, "inst")
    subprocess.run(["git", "init", "-q", inst], check=True)
    with open(os.path.join(inst, "a"), "w") as fh:
        fh.write("1\n")
    subprocess.run(["git", "-C", inst, "add", "a"], check=True)
    subprocess.run(["git", "-C", inst, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a"],
                   check=True)
    unchanged = sh('INSTRUMENTS="%s"; s="$(instruments_state)"; instruments_unchanged "$s" review '
                   '&& echo same' % inst, repo)
    check("instruments-unchanged", unchanged, "same")
    changed = sh('INSTRUMENTS="%s"; s="$(instruments_state)"; echo 2 > "%s/a"; '
                 'instruments_unchanged "$s" review 2>&1 || echo changed' % (inst, inst), repo)
    check("instruments-changed-said", "changed sclaude's own checkout" in changed and "changed" in changed, True)
    # Untracked content and the repository's config count too.
    with open(os.path.join(inst, "loose"), "w") as fh:
        fh.write("1\n")
    for change in ('echo 2 > "%s/loose"' % inst, 'git -C "%s" config core.hooksPath x' % inst,
                   'ln -s /tmp/x "%s/.git/hooks/pre-push"' % inst):
        out = sh('INSTRUMENTS="%s"; s="$(instruments_state)"; %s; '
                 'instruments_unchanged "$s" review 2>/dev/null || echo changed' % (inst, change), repo)
        check("instruments-changed %s" % change.split()[0], out, "changed")
    # A checkout whose path has a space: Claude Code runs the hook through a
    # shell, and the unquoted path split there.
    entry = json.loads(sh('HOOKS="/opt/my tools/hooks"; guard_entry --readonly /x', repo))
    words = shlex.split(entry["hooks"][0]["command"])
    check("guard-path-with-space", words[:2], ["python3", "/opt/my tools/hooks/write-guard.py"])
    # And every other hook a session gets: the step's, the plan's, the status's.
    for call, name in (("step_settings code \"%s\"" % repo, "forbidden-commands.py"),
                       ("step_settings plan \"%s\"" % repo, "no-code-in-planning.py"),
                       ("step_settings plan \"%s\"" % repo, "plan-on-disk.py"),
                       ("status_settings", "forbidden-commands.py")):
        flags = sh('HOOKS="/opt/my tools/hooks"; BROWSER_ALLOW=x; %s' % call, repo).splitlines()
        settings = json.loads(flags[flags.index("--settings") + 1])
        firsts = [shlex.split(h["hooks"][0]["command"])[1] for h in settings["hooks"]["PreToolUse"]]
        check("hook-path-with-space %s %s" % (call.split()[0], name),
              "/opt/my tools/hooks/" + name in firsts, True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("ok")
