#!/usr/bin/env python3
#
# A test bench for the hooks: we feed JSON on stdin and look at deny/allow.
#
# There were no tests in the repository at all, and that is exactly why both
# holes in the bans survived to this revision: step 1 wrote files through
# `setsid rm`, and steps 2-4 let `timeout 5 gh pr merge` through — that is a
# merge, the human's step. And a hook is the most testable thing here: a pure
# function of the JSON on its input.
#
# Run it with: python3 tests/hooks.py
import ast
import io
import json
import os
import subprocess
import sys
import tempfile

HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "sclaude", "hooks")

DENY = "deny"
ALLOW = "allow"

# Claude Code's temp root, where every session keeps its scratchpad.
SCRATCH = "/tmp/claude-{}".format(os.getuid())


# A product for forbidden-commands.py to read its policy from: the shape a
# product on Vercel and Supabase writes in .sclaude/team/policy.json, with the
# product's own bans and the way it tells its environment.
PRODUCT = tempfile.mkdtemp(prefix="sclaude-hooks-product-")
os.makedirs(os.path.join(PRODUCT, ".sclaude", "team"))
with open(os.path.join(PRODUCT, ".sclaude", "team", "policy.json"), "w") as _fh:
    json.dump({
        "integrations": ["vercel", "supabase"],
        "deny": [
            {"command": "npm run db:promote", "why": "prod migrations, after the merge"},
            {"command": "npm run env:prod", "why": "moves the environment to prod"},
        ],
        "settings": {"supabase": {
            "environment": "node scripts/lib/env-guard.mjs settled",
            "environments": "config/environments.json",
        }},
    }, _fh)


def run(hook, command, step=None, tool="Bash", tool_input=None, env=None,
        cwd=None, root=None):
    """The hook's verdict in one word."""
    argv = [sys.executable, os.path.join(HOOKS, hook)]
    if step:
        argv += ["--step", step]
    if hook == "forbidden-commands.py":
        argv += ["--root", root or PRODUCT]
    payload = {"tool_name": tool,
               "tool_input": tool_input or {"command": command}}
    if cwd:
        payload["cwd"] = cwd
    full = dict(os.environ)
    full.pop("SUPABASE_WORKDIR", None)
    full.update(env or {})
    done = subprocess.run(argv, input=json.dumps(payload), text=True,
                          capture_output=True, timeout=20, env=full)
    if not done.stdout.strip():
        return ALLOW
    try:
        out = json.loads(done.stdout)
    except ValueError:
        return ALLOW
    decision = (out.get("hookSpecificOutput") or {}).get("permissionDecision")
    return DENY if decision == "deny" else ALLOW


# (command, expectation). Every wrapper is checked both bare and with an
# argument: it was the wrapper's argument that threw the parsing off.
PLANNING = [
    # Writing is forbidden, in any wrapper.
    ("rm -rf /tmp/x", DENY),
    ("setsid rm -rf /tmp/x", DENY),
    ("command rm -rf /tmp/x", DENY),
    ("timeout 5 rm -rf /tmp/x", DENY),
    ("nice -n 5 npm install", DENY),
    ("stdbuf -o0 tee /tmp/f", DENY),
    ("xargs -n1 rm", DENY),
    ("FOO=1 rm -rf /tmp/x", DENY),
    ("env FOO=1 rm -rf /tmp/x", DENY),
    ("sudo /bin/rm -rf /tmp/x", DENY),
    ("git commit -m x", DENY),
    ("git -C /tmp commit -m x", DENY),
    ("echo hi > /tmp/f", DENY),
    ("cat f > g.ts", DENY),
    ("sed -i s/a/b/ f.ts", DENY),
    ("git log && git commit -m x", DENY),
    # `node` reads with a flag and writes without one. The bench had no node
    # case at all, and that is why the ban on the name survived to a live
    # feature: a planning session lost a version read to it.
    ("node scripts/seed.mjs", DENY),
    ("node -p \"1\" > f.js", DENY),
    ("node -p 1 && rm -rf /tmp/x", DENY),
    # `worktree` and `stash` write, except for their listing actions.
    ("git worktree add ../x", DENY),
    ("git worktree remove x", DENY),
    ("git stash", DENY),
    ("git stash pop", DENY),
    ("git stash -m list", DENY),
    ("git worktree list && git commit -m x", DENY),
    # The friction log is open to a single append, and only to that: the text
    # of the entry hides neither a chain nor a substitution.
    ("cat >> .feature/friction.log <<'EOF' && rm -rf x\nplain\nEOF", DENY),
    ("cat >> .feature/friction.log <<EOF\n$(rm -rf x)\nEOF", DENY),
    ("echo \"$(rm -rf x)\" >> .feature/friction.log", DENY),
    ("echo `rm -rf x` >> .feature/friction.log", DENY),
    ("echo x >> .feature/friction.log\nrm -rf x", DENY),
    ("echo a >> .feature/friction.log > other.ts", DENY),
    # A substitution is judged by what it runs: a reading one next to a
    # writing one, or one nested in another, still refuses.
    ("echo \"$(date) $(rm -rf x)\" >> .feature/friction.log", DENY),
    ("echo \"$(echo $(rm x))\" >> .feature/friction.log", DENY),
    ("echo \"`date` `rm x`\" >> .feature/friction.log", DENY),
    # `npx` reads only when it asks for help or a version.
    ("npx supabase db push", DENY),
    ("npx prettier --write .", DENY),
    ("npx foo -- --help", DENY),
    ("npx supabase db --help && rm -rf x", DENY),
    # Reading is allowed: finding its way around the repository is what step 1
    # is busy with.
    ("git log --oneline -5", ALLOW),
    ("gh issue view 75", ALLOW),
    ("grep -r install .", ALLOW),
    ("sed -n 1,130p f.ts", ALLOW),
    ("npm ls", ALLOW),
    ("cat package.json", ALLOW),
    ("node -p \"1+1\"", ALLOW),
    ("node -e \"console.log(1)\"", ALLOW),
    ("node --version", ALLOW),
    # A live planning session lost exactly this to the ban on `worktree`.
    ("git worktree list; git branch -r | head -20; grep -rn \"categories\" "
     "--include=*.ts app lib | grep -n \"select\\|from(\\\"event\" | head", ALLOW),
    ("git worktree list --porcelain", ALLOW),
    ("git stash list", ALLOW),
    ("git stash show -p", ALLOW),
    # An entry may describe a command. One that mentioned `;`, a pipe or an
    # arrow used to read as a chain, and the only file step 1 may write refused
    # the entries that matter most to it.
    ("echo 'x' >> .feature/friction.log", ALLOW),
    ("cat >> .feature/friction.log <<'EOF'\nneeded `git worktree list`; it "
     "only reads | nothing > else, it's fine\nEOF", ALLOW),
    ("printf '%s\\n' 'a; b' >> .feature/friction.log", ALLOW),
    ("echo \"git log | head; ok\" >> .feature/friction.log", ALLOW),
    # The exact entry a live planning session lost: a timestamp and an
    # escaped backtick, neither of which runs anything that writes.
    ("echo \"$(date -Iseconds) plan/145: a read was refused, since "
     "\\`supabase migration list\\` JSON carries versions only.\" "
     ">> .feature/friction.log", ALLOW),
    ("cat >> .feature/friction.log <<EOF\n$(date) refused\nEOF", ALLOW),
    # `npx` asking for help or a version only prints. The same session lost
    # both of these to the ban on the name.
    ("npx supabase db --help", ALLOW),
    ("npx supabase --version", ALLOW),
    ("url=$(grep -m1 '^POSTGRES_URL_NON_POOLING=' .env.dev | cut -d= -f2- | "
     "sed -e 's/^[\"'\"'\"']//' -e 's/[\"'\"'\"']$//'); psql \"$url\" -tAc "
     "\"select version, name from supabase_migrations.schema_migrations "
     "order by version desc limit 4;\" 2>&1 | grep -v -i \"postgres://\"; "
     "npx supabase db --help 2>/dev/null | grep -i -A1 \"query\\|^  [a-z]\" "
     "| head -20", ALLOW),
    ("ls -la .feature/; npx supabase db --help 2>/dev/null | "
     "sed -n '/Available Commands/,/^$/p'; sed -n 60,110p scripts/dump-schema.sh",
     ALLOW),
    # Redirection is judged by its target: the null device and the standard
    # streams write no file. Only `2>/dev/null` used to pass, and only because
    # the digit fell under the lookbehind.
    ("cmd >/dev/null 2>&1", ALLOW),
    ("echo hi >/dev/stdout", ALLOW),
    ("ls x 2>/dev/null", ALLOW),
    # A separator straight after the target, with no space. The target used to
    # be read as "/dev/null;" and the redirection stayed a write — the exact
    # shape of two entries in a live feature's friction log.
    ("echo hi >/dev/null; cat package.json", ALLOW),
    ("cat token >/dev/null 2>&1 && echo present", ALLOW),
    ("echo hi >/dev/null|cat", ALLOW),
    # An empty target is unknown, and unknown is not permission.
    ("echo hi >", DENY),
    # A heredoc body is data, not shell. The "User request" comment plan.md
    # asks for was refused in a live feature: the marker ends in `-->`, and the
    # redirection scan read it as `> ##`.
    ("gh issue comment 104 --body-file - <<'EOF'\n"
     "<!-- sclaude:user-request -->\n## User request\n\n"
     "The actions move out of the \"⋯\" menu.\nEOF", ALLOW),
    ("gh api -X PATCH repos/o/r/issues/comments/1 -F body=@- <<'EOF'\n"
     "<!-- sclaude:user-request -->\n## User request\nEOF", ALLOW),
    ("gh issue comment 1 --body-file - <<EOF\nit's a -> b\nEOF", ALLOW),
    # The heredoc line itself and whatever follows the delimiter are still
    # shell.
    ("cat <<'EOF' > f.ts\nexport {}\nEOF", DENY),
    ("gh issue comment 1 --body-file - <<'EOF'\n<!-- x -->\nEOF\n"
     "rm -rf /tmp/x", DENY),
    # The session scratchpad is Claude Code's own temp space, outside the
    # worktree. A live planning session saved an issue comment there to diff it
    # and was refused. Only the scratchpad: /tmp in general stays a write.
    ("gh api x --jq .body > " + SCRATCH + "/p/s/scratchpad/ur.md && "
     "diff <(cat " + SCRATCH + "/p/s/scratchpad/ur.md) - <<'EOF' ; "
     "echo rc=$?\nnew body\nEOF\nwc -l " + SCRATCH + "/p/s/scratchpad/ur.md",
     ALLOW),
    ("echo x > " + SCRATCH + "/../../home/u/myapp/f.ts", DENY),
    ("echo x > " + SCRATCH + "x/f", DENY),
    ("cat f > " + SCRATCH + "/p/x && rm -rf /tmp/x", DENY),
]

# Steps 2-4: merging and prod are the human's steps, and a wrapper must not open
# them up.
FORBIDDEN = [
    # The shapes a code review found going through: a subshell, a brace
    # group, a shell or eval given the command as a string, the merge through
    # the REST API or GraphQL, and a push whose destination is a variable, a
    # substitution or a full ref name.
    ("(gh pr merge 1)", DENY),
    ("{ gh pr merge 1; }", DENY),
    ("( cd /tmp && gh pr merge 1 )", DENY),
    ("bash -c 'gh pr merge 5'", DENY),
    ("sh -c \"git push origin HEAD:main\"", DENY),
    ("bash -lc 'vercel --prod'", DENY),
    ("eval gh pr merge 5", DENY),
    ("eval 'gh pr merge 5'", DENY),
    ("gh api -X PUT repos/o/r/pulls/5/merge", DENY),
    ("gh api --method PUT repos/o/r/pulls/5/merge -f merge_method=squash", DENY),
    ("gh api -XPUT /repos/o/r/pulls/5/merge", DENY),
    ("gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'", DENY),
    ("x=main; git push origin HEAD:$x", DENY),
    ("git push origin $(echo main)", DENY),
    ("git push origin HEAD:`echo main`", DENY),
    ("git push origin HEAD:refs/heads/main", DENY),
    ("git push origin +HEAD:main", DENY),
    # ...and what must still go through.
    ("gh api repos/o/r/pulls/5/merge", ALLOW),
    ("gh api repos/o/r/pulls/5", ALLOW),
    ("bash -c 'npm run lint'", ALLOW),
    ("(cd app && npm test)", ALLOW),
    ("b=feat/x; git push origin HEAD:$b", ALLOW),
    ("git push origin HEAD:refs/heads/feat/x", ALLOW),
    ("gh pr merge 82", DENY),
    ("timeout 5 gh pr merge 82", DENY),
    ("timeout -k 3 5 gh pr merge 82", DENY),
    ("xargs -n1 gh pr merge", DENY),
    ("stdbuf -o0 vercel --prod", DENY),
    ("nice -n 5 vercel --prod", DENY),
    ("setsid gh pr merge 82", DENY),
    ("sudo /usr/bin/gh pr merge 82", DENY),
    ("npm run db:promote", DENY),
    ("npm run env:prod", DENY),
    ("git push origin main", DENY),
    ("stdbuf -o0 git push origin main", DENY),
    ("timeout 5 git push origin main", DENY),
    ("git push origin HEAD:main", DENY),
    ("git push --force origin feat/x", DENY),
    ("git push --no-verify origin feat/x", DENY),
    # git's own options before the subcommand: every one of these went through,
    # found by a friction review.
    ("git -C /home/x/myapp push origin main", DENY),
    ("git -C ~/myapp push origin main", DENY),
    ("git --git-dir=/home/x/myapp/.git push origin main", DENY),
    ("git --git-dir /home/x/myapp/.git push origin main", DENY),
    ("git -c core.x=1 push origin main", DENY),
    ("git --no-pager -C x push origin HEAD:main", DENY),
    ("git -C /home/x/myapp push --force origin feat/x", DENY),
    ("git -C /home/x/myapp push --no-verify origin feat/x", DENY),
    ("git -C /home/x/myapp push origin feat/x", ALLOW),
    ("git -C /home/x/myapp log main", ALLOW),
    ("echo hi;gh pr merge 82", DENY),
    # A package runner is a wrapper like any other, and every one of these went
    # through until a fixing session found the shape by accident.
    ("npx vercel --prod", DENY),
    ("npx -y vercel deploy --prod", DENY),
    ("npx --yes vercel@59.17.0 --prod", DENY),
    ("npx --package vercel vercel --prod", DENY),
    ("bunx vercel --prod", DENY),
    ("pnpm dlx vercel --prod", DENY),
    ("yarn dlx vercel --prod", DENY),
    ("npx gh pr merge 82", DENY),
    # An assignment whose value is a command substitution spans several words.
    # Skipping only the first left `f)` as the command's name, and that bypassed
    # the whole table — a merge and a push to main among it.
    ("VERCEL_TOKEN=$(cat f) npx vercel --prod", DENY),
    ("TOKEN=$(cat f) gh pr merge 82", DENY),
    ("TOKEN=$(cat f) git push origin main", DENY),
    ("A=`cat f` gh pr merge 82", DENY),
    ("A=$(cat f) B=plain gh pr merge 82", DENY),
    # Reading Vercel deploys nothing, and a fixing session needs it: the preview
    # regression fails on an environment this tree cannot see otherwise.
    ("vercel env ls preview", ALLOW),
    ("npx vercel env ls preview", ALLOW),
    ("vercel inspect https://x.vercel.app", ALLOW),
    ("vercel ls agora", ALLOW),
    ("vercel logs https://x.vercel.app", ALLOW),
    ("vercel whoami", ALLOW),
    # `rollback status` answers whether a rollback is in flight and moves
    # nothing — the same class of read, and one a session investigating a red
    # production regression has a reason to make.
    ("vercel rollback status", ALLOW),
    ("vercel rollback status agora", ALLOW),
    # Writing to Vercel is still the human's step, subcommand or not.
    ("vercel", DENY),
    ("vercel --prod", DENY),
    ("vercel deploy", DENY),
    ("vercel env add R2_BUCKET", DENY),
    ("vercel env rm R2_BUCKET", DENY),
    ("vercel promote dpl_x", DENY),
    # Rolling production back is the orchestrator's, not a session's: it has the
    # deployment to go back to on record and classifies the branch's migrations
    # first. Every way round the plain form is closed too — the runner, the
    # path, and a flag standing before the subcommand.
    ("vercel rollback https://x.vercel.app", DENY),
    ("vercel rollback dpl_x", DENY),
    ("npx vercel rollback dpl_x", DENY),
    ("/usr/bin/vercel rollback dpl_x", DENY),
    ("vercel --yes rollback dpl_x", DENY),
    ("vercel rollback dpl_x", DENY),
    ("vercel link", DENY),
    # A step's own work is allowed.
    ("git push origin feat/x", ALLOW),
    ("git push -u origin feat/x", ALLOW),
    ("gh pr view 82", ALLOW),
    ("npm run typecheck", ALLOW),
    ("npm run lint", ALLOW),
    ("npx playwright test", ALLOW),
    ("npx tsc --noEmit", ALLOW),
]

# Step 2 does not open the pull request — that is step 3's work.
BY_STEP = [
    ("gh pr create --base main", "code", DENY),
    ("timeout 5 gh pr create --base main", "code", DENY),
    ("gh pr create --base main", "pr", ALLOW),
]


def const(name, constant):
    """A top-level constant from a hook's file, without running it."""
    tree = ast.parse(io.open(os.path.join(HOOKS, name), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == constant:
                    return ast.literal_eval(node.value)
    raise AssertionError("no %s in %s" % (constant, name))


def main():
    failures = []

    for command, want in PLANNING:
        got = run("no-code-in-planning.py", command)
        if got != want:
            failures.append(("plan", command, want, got))

    for command, want in FORBIDDEN:
        got = run("forbidden-commands.py", command, step="review")
        if got != want:
            failures.append(("review", command, want, got))

    # A push to `main` in a throwaway repository under the temp root is not the
    # push the ban is about; anything that could reach a network remote still is.
    import tempfile, shutil
    scratch = tempfile.mkdtemp(prefix="hooks-push-")
    try:
        clone = os.path.join(scratch, "clone")
        subprocess.run(["git", "init", "-q", clone], check=True)
        subprocess.run(["git", "-C", clone, "remote", "add", "origin",
                        "https://github.com/o/r.git"], check=True)
        home = os.path.expanduser("~")
        push_cases = [
            # The exact command a review subagent once lost.
            ("cd " + scratch + " && rm -rf exp && mkdir exp && cd exp && "
             "export GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=a "
             "GIT_AUTHOR_EMAIL=a@b; git init -q --bare -b main o.git; "
             "git init -q -b main w; cd w; git remote add origin ../o.git; "
             "echo 1>f; git add f; git commit -qm 1; git push -q origin main; "
             "cd ..; git clone -q o.git x; cd x; git push -q origin main; "
             "echo ls=$?", home, ALLOW),
            ("cd " + scratch + " && git push ../o.git main", home, ALLOW),
            ("git push origin main", scratch + "/new", ALLOW),
            # A review session: the scratch path in a variable.
            ("S=" + scratch + "; cd $S/w && git remote add origin ../o.git "
             "&& git push -q origin HEAD:main", home, ALLOW),
            ("export S=" + scratch + "; cd ${S}/w && git push ../o.git main",
             home, ALLOW),
            # A review session: --git-dir in a heredoc after the push.
            ("cd " + scratch + " && rm -rf t && mkdir t && cd t && "
             "git init -q --bare -b main o.git && git init -q -b main w && "
             "cd w && git commit -q --allow-empty -m a && "
             "git push -q ../o.git main && cd .. && cat > up.sh <<'EOF'\n"
             "git --git-dir=\"$1\" update-ref -d refs/heads/x\n"
             "exec git upload-pack \"$1\"\nEOF\necho done", home, ALLOW),
            ("cd " + scratch + " && git --git-dir=o.git log && "
             "git push ../o.git main", home, ALLOW),
            ("cd " + scratch + " && export GIT_DIR=" + home + "/myapp/.git "
             "&& git push origin main", home, DENY),
            # `-C` is a `cd` for that one call: into a scratch repository it
            # passes, out of one it does not, and the next call is not moved.
            ("git -C " + scratch + " push ../o.git main", home, ALLOW),
            ("git -C " + home + "/myapp push origin main", scratch, DENY),
            ("git -C " + scratch + " status && git push origin main", home,
             DENY),
            ("cd " + scratch + " && git --git-dir=" + home + "/myapp/.git "
             "push origin main", home, DENY),
            ("cd " + scratch + " && git -c remote.o.url=$U push o main",
             home, DENY),
            ("S=$(pwd); cd $S && git push ../o.git main", home, DENY),
            ("S=" + scratch + "; S=$HOME; cd $S && git push ../o.git main",
             home, DENY),
            ("S=" + scratch + " true; cd $S && git push ../o.git main",
             home, DENY),
            ("S=" + scratch + "; cd '$S' && git push ../o.git main",
             home, DENY),
            # Still the project, or not provably a scratch repository.
            ("git push origin main", home, DENY),
            ("cd " + scratch + " && git clone https://github.com/o/r x && "
             "cd x && git push origin main", home, DENY),
            ("cd " + scratch + " && git push git@github.com:o/r.git main",
             home, DENY),
            ("cd " + clone + " && git push origin main", home, DENY),
            ("git push origin main", clone, DENY),
            ("cd " + scratch + " && git remote add origin \"$U\" && "
             "git push origin main", home, DENY),
            ("cd " + scratch + " && GIT_DIR=" + home + "/myapp/.git "
             "git push origin main", home, DENY),
            ("cd ~/myapp && git push origin main", scratch, DENY),
            ("cd $HOME/x && git push origin main", scratch, DENY),
            ("cd " + scratch + "; cd -; git push origin main", home, DENY),
            ("(cd " + scratch + "); git push origin main", home, DENY),
            ("cd " + scratch + "/../.." + home + " && git push origin main",
             home, DENY),
            ("cd " + scratch + " && git push --force origin feat/x", home, DENY),
        ]
        for command, cwd, want in push_cases:
            got = run("forbidden-commands.py", command, step="review", cwd=cwd)
            if got != want:
                failures.append(("push", command, want, got))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    for command, step, want in BY_STEP:
        got = run("forbidden-commands.py", command, step=step)
        if got != want:
            failures.append((step, command, want, got))

    # Writing with the file tools at step 1 — past the command parsing.
    for path, want in ((os.path.expanduser("~/.claude/plans/x.md"), ALLOW),
                       (SCRATCH + "/p/s/scratchpad/ur.md", ALLOW),
                       ("/home/u/myapp/app/page.tsx", DENY)):
        got = run("no-code-in-planning.py", None, tool="Write",
                  tool_input={"file_path": path})
        if got != want:
            failures.append(("plan", "Write " + path, want, got))

    # A feature with a database of its own: the CLI already points at it, and
    # --workdir is the one way past that, to somebody else's stack.
    own = "/tmp/feature-x/.feature/supabase"
    workdir_cases = [
        ("npx supabase db reset", {"SUPABASE_WORKDIR": own}, ALLOW),
        ("npx supabase migration up --workdir " + own, {"SUPABASE_WORKDIR": own}, ALLOW),
        ("npx --yes supabase db reset --workdir /home/u/myapp",
         {"SUPABASE_WORKDIR": own}, DENY),
        ("supabase db reset --workdir=/elsewhere", {"SUPABASE_WORKDIR": own}, DENY),
        # No stack of its own — the flag is nobody's business here.
        ("supabase db reset --workdir /elsewhere", {}, ALLOW),
    ]
    for command, env, want in workdir_cases:
        got = run("forbidden-commands.py", command, step="code", env=env)
        if got != want:
            failures.append(("workdir", command, want, got))

    # A schema change aimed at a shared cloud project is asked about, not
    # refused: the person may mean it, but database work belongs on the local
    # environment. A tree whose guard says "dev", in a project whose local
    # environment is "localdb".
    import tempfile, shutil
    tree = tempfile.mkdtemp(prefix="hooks-shared-")
    try:
        os.makedirs(os.path.join(tree, "scripts", "lib"))
        os.makedirs(os.path.join(tree, "config"))
        with open(os.path.join(tree, ".sclaude.json"), "w") as fh:
            json.dump({"database": {"local": {"environment": "localdb"}}}, fh)
        with open(os.path.join(tree, "config", "environments.json"), "w") as fh:
            json.dump({"dev": {"confirm": False}, "localdb": {"confirm": False},
                       "prod": {"confirm": True}}, fh)

        def guard(name):
            with open(os.path.join(tree, "scripts", "lib", "env-guard.mjs"), "w") as fh:
                fh.write("console.log(%s);\n" % json.dumps(name))

        def verdict(command):
            argv = [sys.executable, os.path.join(HOOKS, "forbidden-commands.py"), "--step", "code",
                    "--root", PRODUCT]
            full = dict(os.environ, CLAUDE_PROJECT_DIR=tree)
            full.pop("SUPABASE_WORKDIR", None)
            out = subprocess.run(argv, input=json.dumps({"tool_name": "Bash",
                                 "tool_input": {"command": command}}),
                                 text=True, capture_output=True, timeout=20, env=full).stdout
            try:
                return (json.loads(out).get("hookSpecificOutput") or {}).get(
                    "permissionDecision") or "allow"
            except ValueError:
                return "allow"

        guard("dev")
        shared_cases = [
            ("npx supabase db push", "ask"),
            ("supabase migration up --linked", "ask"),
            ("supabase db reset --linked", "ask"),
            ("supabase migration up", "allow"),     # the local stack
            ("supabase db reset", "allow"),
            ("supabase migration list", "allow"),
        ]
        for command, want in shared_cases:
            got = verdict(command)
            if got != want:
                failures.append(("shared", command, want, got))
        guard("localdb")
        if verdict("npx supabase db push") != "allow":
            failures.append(("shared", "db push on localdb", "allow", verdict("npx supabase db push")))
    finally:
        shutil.rmtree(tree, ignore_errors=True)

    # A plan is not shown for approval without its acceptance criteria. Only
    # inside a feature: the hook must not get in the way of someone else's
    # planning. The tree carries a `.feature/` of its own, and the session's
    # directory is a level below it, as a step's may be.
    feature = tempfile.mkdtemp(prefix="hooks-plan-")
    try:
        os.makedirs(os.path.join(feature, ".feature"))
        inside = os.path.join(feature, "app")
        os.makedirs(inside)
        plan_file = os.path.join(feature, "drafted.md")
        with open(plan_file, "w") as fh:
            fh.write("# P\n\nNo criteria in this one.\n")
        with_ac = "# P\n\n## Acceptance criteria\n\n- [ ] AC1. A guest sees it.\n"
        refactor = "# P\n\n## Acceptance criteria\n\nNo observable change: a rename.\n"
        bare = "# P\n\n## How\n\nJust do it.\n"
        plan_cases = [
            ("no criteria", {"plan": bare}, inside, DENY),
            ("criteria", {"plan": with_ac}, inside, ALLOW),
            ("declared none", {"plan": refactor}, inside, ALLOW),
            ("from planFilePath", {"planFilePath": plan_file}, inside, DENY),
            ("outside a feature", {"plan": bare}, tempfile.gettempdir(), ALLOW),
            ("unreadable file", {"planFilePath": plan_file + ".gone"}, inside, ALLOW),
            ("empty section", {"plan": "# P\n\n## Acceptance criteria\n\nTBD.\n"},
             inside, DENY),
            ("fenced no-change line", {"plan": "## Acceptance criteria\n\n```\n"
                                       "No observable change: a rename.\n```\n"},
             inside, ALLOW),
        ]
        for name, tool_input, cwd, want in plan_cases:
            got = run("plan-on-disk.py", None, tool="ExitPlanMode",
                      tool_input=tool_input, cwd=cwd)
            if got != want:
                failures.append(("criteria", name, want, got))

        # A refused plan is still saved — it is the last of what was drafted —
        # and the two refusals say different things: "add a section" to a plan
        # that has one sends the model off to write a second.
        def reason(plan):
            out = subprocess.run(
                [sys.executable, os.path.join(HOOKS, "plan-on-disk.py")],
                input=json.dumps({"tool_name": "ExitPlanMode", "cwd": inside,
                                  "tool_input": {"plan": plan}}),
                text=True, capture_output=True, timeout=20).stdout
            return (json.loads(out).get("hookSpecificOutput") or {}).get(
                "permissionDecisionReason") or ""
        no_section = reason(bare)
        with open(os.path.join(feature, ".feature", "plan.md")) as fh:
            plan_saved = "Just do it." in fh.read()
        empty_section = reason("## Acceptance criteria\n\nTBD.\n")
        for name, ok in (("refused plan is saved", plan_saved),
                         ("missing says add a section", "Add a section" in no_section),
                         ("empty says keep the section",
                          "Keep that one section" in empty_section)):
            if not ok:
                failures.append(("criteria", name, "true", "false"))
    finally:
        shutil.rmtree(feature, ignore_errors=True)

    # The markers by which collect-denials.py recognises our own hooks' refusals
    # and does not write them into the log a second time. The comparison goes
    # through the transcript's text, so a marker is a copy of the tail the hook
    # prints: let them diverge and the deduplication silently stops working. One
    # of the two stood exactly like that, matching nothing.
    for marker in const("collect-denials.py", "OWN_MARKERS"):
        if not any(marker in tail for tail in (
                const("forbidden-commands.py", "TAIL"),
                const("no-code-in-planning.py", "REASON"),
                const("plan-on-disk.py", "TAIL"),
                const("team-rules.py", "REASON"))):
            failures.append(("markers", marker, "a hook's tail", "matched nothing"))

    total = len(PLANNING) + len(FORBIDDEN) + len(BY_STEP) + 2 + len(workdir_cases) + \
        len(shared_cases) + 1 + len(plan_cases) + 3 + \
        len(const("collect-denials.py", "OWN_MARKERS"))
    for step, command, want, got in failures:
        print("FAIL [%s] %s — expected %s, got %s" % (step, command, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
