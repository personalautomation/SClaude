#!/usr/bin/env python3
#
# What a production deploy carries besides the feature being shipped.
#
# `vercel --prod` ships main, all of it. When an earlier feature was merged and
# its production question answered no, its code and its migrations wait on main
# — and the next feature's ship takes them along. On 2026-10-09 one feature
# shipped another that way: the promotion applied the other's migration
# beside its own, while the question above it said only "The branch
# adds migrations". The ship was right; the person was not told what it was.
#
#   prod_riders.py <repo> <prod sha> <main ref> <own slug> [<migrations dir>
#                  [<own pr> [<file of shas to leave out>]]]
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
# already in production, and the ones the caller names in the file (commits
# that only add deferred entries, which ship nothing). Nothing at all when it
# cannot be worked out: this is a note above a question, never a reason not to
# ask it.
#
# A pull request squashed into one commit is a feature too, told by the
# "(#<pr>)" GitHub ends its subject with, when GitHub confirms that number is
# a pull request (an issue number in a commit's subject reads the same): read
# as a commit, a feature's own squashed merge was listed as pushed straight
# to main, above the question that ships it, among nineteen commits of
# deferred entries. The shipped one is known by its number (<own pr>).
import json
import re
import subprocess
import sys

MERGE = re.compile(r"^Merge pull request #(\d+) from [^/\s]+/(\S+)")
SQUASH = re.compile(r"\(#(\d+)\)$")
PROMOTE = re.compile(r"^chore\(db\): promote migrations\b")


def git(repo, *args):
    done = subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr)
    return done.stdout


def pr_info(repo, pr):
    """The pull request's head branch and the issues it closes, in one call:
    ("", "") when gh cannot say, and then a squashed subject's "(#N)" is not
    taken for a pull request — an issue number reads the same."""
    try:
        done = subprocess.run(["gh", "pr", "view", pr, "--json", "headRefName,closingIssuesReferences"],
                              cwd=repo, capture_output=True, text=True, timeout=60)
        data = json.loads(done.stdout) if done.returncode == 0 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        data = {}
    refs = data.get("closingIssuesReferences") or []
    issues = ",".join(str(r.get("number")) for r in refs if r.get("number"))
    return data.get("headRefName") or "", issues


def issue_of(issues, branch):
    if issues:
        return issues
    found = re.match(r"(?:[a-z]+/)?(\d+)-", branch)
    return found.group(1) if found else "-"


def is_own(branch, own):
    return bool(branch) and (branch.rstrip("/").split("/")[-1] == own or branch.endswith("/" + own))


def riders(repo, prod, main, own, migrations_dir, own_pr="", skip=()):
    out = []
    log = git(repo, "log", "--first-parent", "--format=%H%x09%s", "%s..%s" % (prod, main))
    for line in log.splitlines():
        sha, _, subject = line.partition("\t")
        if sha in skip:
            continue
        merge = MERGE.match(subject)
        squash = None if merge else SQUASH.search(subject)
        if PROMOTE.match(subject):
            continue
        pr = branch = issues = ""
        if merge:
            pr, branch = merge.groups()
        elif squash:
            pr = squash.group(1)
        if pr and pr == own_pr:
            continue
        if pr and not (merge and is_own(branch, own)):
            head, issues = pr_info(repo, pr)
            branch = branch or head
        if (merge or (squash and branch)) and not is_own(branch, own):
            added = []
            if migrations_dir:
                added = [p.rsplit("/", 1)[-1] for p in git(
                    repo, "diff", "--name-only", "--diff-filter=A", sha + "^1", sha,
                    "--", migrations_dir).split()]
            # No field empty: the shell reads the line with IFS=tab, and an
            # empty field there vanishes and moves the next ones left.
            out.append("feature\t%s\t%s\t%s\t%s" % (pr, issue_of(issues, branch),
                                                     branch or "-", ",".join(added) or "-"))
        elif merge or (squash and is_own(branch, own)):
            continue
        else:
            out.append("commit\t%s\t%s" % (sha[:8], subject or "-"))
    return out


def main():
    if len(sys.argv) < 5:
        return 0
    repo, prod, main_ref, own = sys.argv[1:5]
    migrations_dir = sys.argv[5] if len(sys.argv) > 5 else ""
    own_pr = sys.argv[6] if len(sys.argv) > 6 else ""
    skip = set()
    if len(sys.argv) > 7:
        try:
            with open(sys.argv[7]) as fh:
                skip = {l.strip() for l in fh if l.strip()}
        except OSError:
            pass
    try:
        lines = riders(repo, prod, main_ref, own, migrations_dir, own_pr, skip)
    except Exception:
        return 0
    for line in reversed(lines):
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
