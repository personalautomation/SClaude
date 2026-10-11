#!/usr/bin/env python3
#
# What a production deploy carries besides the feature being shipped.
#
# `vercel --prod` ships main, all of it. When an earlier feature was merged and
# its production question answered no, its code and its migrations wait on main
# — and the next feature's ship takes them along. On 2026-10-09 #152 shipped
# #150 that way: `db:promote` applied 0084_events_say_activities.sql, #150's,
# beside #152's own 0085, while the question above it said only "The branch
# adds migrations". The ship was right; the person was not told what it was.
#
#   prod_riders.py <repo> <prod sha> <main ref> <own slug> [<migrations dir>]
#
# One line per thing riding along, tab-separated:
#
#   feature <TAB> <pr> <TAB> <issue or -> <TAB> <branch> <TAB> <migrations, comma-separated or ->
#   commit  <TAB> <short sha> <TAB> <subject>
#
# A feature is a pull request merged into main since the commit production
# serves, other than the one being shipped; its issue is the one the pull
# request closes, or the number its sclaude branch starts with. A commit is one
# pushed straight to main — a promote commit aside, which records migrations
# already in production. Nothing at all when it cannot be worked out: this is a
# note above a question, never a reason not to ask it.
import json
import re
import subprocess
import sys

MERGE = re.compile(r"^Merge pull request #(\d+) from [^/\s]+/(\S+)")
PROMOTE = re.compile(r"^chore\(db\): promote migrations\b")


def git(repo, *args):
    done = subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    return done.stdout


def closing_issue(repo, pr, branch):
    try:
        done = subprocess.run(["gh", "pr", "view", pr, "--json", "closingIssuesReferences"],
                              cwd=repo, capture_output=True, text=True, timeout=60)
        refs = json.loads(done.stdout).get("closingIssuesReferences") or []
        if refs:
            return ",".join(str(r.get("number")) for r in refs if r.get("number"))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    found = re.match(r"(?:[a-z]+/)?(\d+)-", branch)
    return found.group(1) if found else "-"


def riders(repo, prod, main, own, migrations_dir):
    out = []
    log = git(repo, "log", "--first-parent", "--format=%H%x09%s", "%s..%s" % (prod, main))
    for line in log.splitlines():
        sha, _, subject = line.partition("\t")
        merge = MERGE.match(subject)
        if merge:
            pr, branch = merge.groups()
            if branch.rstrip("/").split("/")[-1] == own or branch.endswith("/" + own):
                continue
            added = []
            if migrations_dir:
                added = [p.rsplit("/", 1)[-1] for p in git(
                    repo, "diff", "--name-only", "--diff-filter=A", sha + "^1", sha,
                    "--", migrations_dir).split()]
            out.append("feature\t%s\t%s\t%s\t%s" % (pr, closing_issue(repo, pr, branch),
                                                     branch, ",".join(added) or "-"))
        elif not PROMOTE.match(subject):
            out.append("commit\t%s\t%s" % (sha[:8], subject))
    return out


def main():
    if len(sys.argv) < 5:
        return 0
    repo, prod, main_ref, own = sys.argv[1:5]
    migrations_dir = sys.argv[5] if len(sys.argv) > 5 else ""
    try:
        lines = riders(repo, prod, main_ref, own, migrations_dir)
    except Exception:
        return 0
    for line in reversed(lines):
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
