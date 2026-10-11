#!/usr/bin/env python3
#
# A bench for prod_drift_report (sclaude/lib/deploy.sh): the check that says
# when production is not serving what origin/main holds, and when main holds
# commits that never reached origin.
#
# What each feature shipped lives in its own state, so nothing used to look
# across features: a fix committed straight to main sat unshipped until some
# later feature happened to deploy it. Run for real against a throwaway
# repository and its bare origin; only the Vercel listing is a stub.
#
# Run it with: python3 tests/prod-drift.py
import os
import subprocess
import sys
import tempfile


def _cfg(path):
    """The path of a product's config, its .sclaude/ folder made first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, subject, path=None):
    if path:
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(subject + "\n")
        git(repo, "add", path)
        git(repo, "commit", "-q", "-m", subject)
    else:
        git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


def report(repo, prod_line, linked=True):
    vercel = os.path.join(repo, ".vercel")
    if linked:
        os.makedirs(vercel, exist_ok=True)
    elif os.path.isdir(vercel):
        os.rmdir(vercel)
    script = 'REPO="%s"\n' % repo
    for name in ("io", "project", "rollback", "deploy"):
        script += 'source "%s/sclaude/lib/%s.sh"\n' % (ROOT, name)
    script += 'warn() { echo "W $*"; }; info() { echo "I $*"; }\n'
    script += "vercel_prod_current() { printf '%%s' '%s'; }\n" % prod_line
    script += "prod_drift_report\necho rc=$?\n"
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True,
                          text=True, timeout=60).stdout


with tempfile.TemporaryDirectory() as tmp:
    origin = os.path.join(tmp, "origin.git")
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin],
                   env=env, check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], env=env, check=True)
    git(repo, "remote", "add", "origin", origin)
    with open(_cfg(os.path.join(repo, ".sclaude/config.json")), "w") as fh:
        fh.write('{"database": {"migrations": "db/migrations",'
                 ' "promote": "npm run db:promote"}}\n')
    git(repo, "add", ".sclaude/config.json")
    shipped = commit(repo, "feat: shipped")
    git(repo, "push", "-q", "origin", "main")

    def line(sha):
        return "https://x.test\t%s\tREADY\t1\t2" % sha

    out = report(repo, line(shipped))
    check("in-step-is-silent", out.strip(), "rc=0")

    fix = commit(repo, "fix: straight to main")
    git(repo, "push", "-q", "origin", "main")
    out = report(repo, line(shipped))
    check("behind-is-said", "Production is 1 commit(s) behind origin/main" in out, True)
    check("behind-names-the-commit", "%s fix: straight to main" % fix[:7] in out, True)
    check("behind-says-how-to-ship", "vercel --prod" in out, True)
    check("no-migrations-no-promote", "db:promote" in out, False)

    commit(repo, "feat(db): a table", "db/migrations/0001.sql")
    git(repo, "push", "-q", "origin", "main")
    out = report(repo, line(shipped))
    check("migrations-name-the-promote", "npm run db:promote comes first" in out, True)
    check("migrations-promote-before-ship",
          "npm run db:promote && vercel --prod" in out, True)

    # A deployment whose commit is not on main was shipped from elsewhere.
    git(repo, "checkout", "-q", "-b", "side")
    side = commit(repo, "wip: a branch")
    git(repo, "checkout", "-q", "main")
    out = report(repo, line(side))
    check("off-main-is-said", "which is not on origin/main" in out, True)

    # Unknown is silent: no link, no listing, no commit on the deployment.
    check("unlinked-is-silent", report(repo, line(shipped), linked=False).strip(), "rc=0")
    check("no-listing-is-silent", report(repo, "").strip(), "rc=0")
    check("no-sha-is-silent", report(repo, "https://x.test\t\tREADY\t1\t2").strip(), "rc=0")

    # Commits on main that never reached origin.
    head = git(repo, "rev-parse", "HEAD")
    commit(repo, "fix: not pushed")
    out = report(repo, line(head))
    check("unpushed-is-said", "main has 1 commit(s) that were never pushed" in out, True)
    check("unpushed-says-how-to-push", "push origin main" in out, True)

# Both places a person looks from run it, after review_branches has fetched.
sclaude_bin = open(os.path.join(ROOT, "bin", "sclaude"), encoding="utf-8").read()
for cmd in ("cmd_menu", "cmd_status"):
    start = sclaude_bin.find("\n%s() {" % cmd)
    body = sclaude_bin[start:sclaude_bin.find("\n}", start)]
    check("%s-runs-it-after-the-fetch" % cmd,
          -1 < body.find("review_branches") < body.find("prod_drift_report"), True)

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
