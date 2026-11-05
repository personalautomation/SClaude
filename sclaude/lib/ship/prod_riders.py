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


MERGED = {}


def merged_prs(repo):
    """Merged pull requests by number: (head branch, issues they close). One
    call for all of them, made once: a call per commit that cites a number,
    one after another before the production question, could add up to
    minutes. Empty when gh cannot say."""
    if repo not in MERGED:
        found = {}
        try:
            done = subprocess.run(["gh", "pr", "list", "--state", "merged", "--limit", "300",
                                   "--json", "number,headRefName,closingIssuesReferences,mergeCommit"],
                                  cwd=repo, capture_output=True, text=True, timeout=60)
            for pr in (json.loads(done.stdout) if done.returncode == 0 else []):
                refs = pr.get("closingIssuesReferences") or []
                found[str(pr.get("number"))] = (
                    pr.get("headRefName") or "",
                    ",".join(str(r.get("number")) for r in refs if r.get("number")),
                    (pr.get("mergeCommit") or {}).get("oid") or "")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        MERGED[repo] = found
    return MERGED[repo]


def pr_info(repo, pr, sha=None):
    """The pull request's head branch and the issues it closes: ("", "") when
    gh does not know it as a merged pull request — or, given the commit, when
    that commit is not its merge — and then a squashed subject's "(#N)" is not
    taken for one: an issue number, or a later commit citing the pull
    request, reads the same."""
    head, issues, merge = merged_prs(repo).get(pr, ("", "", ""))
    if sha is not None and merge != sha:
        return "", ""
    return head, issues


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
        if merge and pr == own_pr:
            continue
        if pr and not (merge and is_own(branch, own)):
            # A squash is its pull request only as that pull request's merge.
            head, issues = pr_info(repo, pr, None if merge else sha)
            branch = branch or head
            # The shipped one: as its merge when gh can say; by its number
            # alone when gh cannot, rather than list it as a commit of its own.
            if squash and pr == own_pr and (head or not merged_prs(repo)):
                continue
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
