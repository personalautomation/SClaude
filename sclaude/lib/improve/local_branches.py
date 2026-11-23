#!/usr/bin/env python3
#
# The branches of sclaude's checkout that exist on this machine alone.
#
# Work in sclaude's checkout reaches everybody only through origin, and a
# branch that never got there is lost with the laptop. Some are kept on
# purpose; others are left by accident: a workshop whose change was never
# published (workshop_remove keeps it on its branch and says so once, in a
# terminal that scrolls on), a backup made before a squash, a feature branch
# whose squashed copy went to main. The last two are only clutter, and git
# cannot tell them from the first: a squash leaves none of a branch's commits
# on main, so `git branch --merged` and `git cherry` call every one unmerged.
#
# So a branch is judged by its lines instead: the share of the lines it adds
# (since it left origin/main) that origin/main added to the same file over the
# same time. A squashed branch scores high even after main moved on (88–99% on
# the branches this was written from); work found nowhere else scores near
# zero. Main's own additions, not its whole file: code a branch moved or
# copied within a file is already in main's copy and would read as landed.
# A branch with no line to judge by — one that only deletes, only adds binary
# files or short lines — is not known to be on main, so it counts as here alone.
# A branch whose tree is its base's (`unclear`) cannot be judged by lines: it
# may have taken main in after its work was squashed there, or added work and
# reverted it. Guessing from its commits failed three review rounds running —
# fixups read as lost work, reverted binary files as nothing — so, at the
# person's word (2026-11-23), it is named at the start like lost work, and
# doctor asks to read it rather than offering to delete it.
#
#   list <checkout>   one tab-separated line per branch: name, commits not on
#                     any remote, the last commit's date, the share in percent
#                     (`-` for `unclear`), and `main` (its work is on main),
#                     `unclear` (its tree is its base's), `partly` or `only-here`
#   note <checkout>   one line for a start, when a branch holds work found
#                     nowhere else; nothing otherwise
#
# Left out: main, a branch checked out in any worktree (somebody is on it: a
# workshop in use, a feature being built), and a branch whose commits are all
# on some remote. Read-only: it neither fetches nor deletes anything.
import subprocess
import sys

# A line shorter than this (a brace, `fi`, a blank) is found everywhere and
# says nothing about where the work went.
SHORTEST = 12
# At or above: the branch's work is on main; at or below: it is not.
ON_MAIN, NOT_ON_MAIN = 75, 25


def git(repo, *args):
    # errors="replace": a diff may carry bytes that are not UTF-8.
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, errors="replace")
    return out.stdout if out.returncode == 0 else ""


def checked_out(repo):
    return {line[len("branch refs/heads/"):] for line in git(repo, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("branch refs/heads/")}


def added(repo, old, new):
    """{path: set of stripped added lines} of old..new, lines of SHORTEST or more."""
    out, path, header = {}, None, False
    for line in git(repo, "-c", "core.quotePath=false", "diff", "--no-color", "--no-renames",
                    "-U0", old, new).splitlines():
        # A file's header runs from `diff --git` to its first hunk: a `+++`
        # inside a hunk is an added line that starts with "++".
        if line.startswith("diff --git "):
            path, header = None, True
        elif header and line.startswith("+++ "):
            path = line[len("+++ b/"):] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            header = False
        elif not header and path and line.startswith("+") and len(line[1:].strip()) >= SHORTEST:
            out.setdefault(path, set()).add(line[1:].strip())
    return out


def share(repo, branch, mains):
    """Percent of the branch's added lines that origin/main added to the same file since
    their base: 0 when there is no line to judge by, None when its tree is its base's
    (unclear). `mains` caches main's additions by base."""
    base = git(repo, "merge-base", "origin/main", branch).strip()
    if not base:
        return 0
    if not subprocess.run(["git", "-C", repo, "diff", "--quiet", base, branch]).returncode:
        return None
    if base not in mains:
        mains[base] = added(repo, base, "origin/main")
    main = mains[base]
    lines = [(path, text) for path, texts in added(repo, base, branch).items() for text in texts]
    if not lines:
        return 0
    return 100 * sum(text in main.get(path, ()) for path, text in lines) // len(lines)


def branches(repo):
    if not git(repo, "rev-parse", "--verify", "-q", "origin/main"):
        return []
    busy = checked_out(repo)
    rows, mains = [], {}
    # The full name, stripped: the short one is "heads/<name>" when a tag shares it.
    for ref in git(repo, "for-each-ref", "--format=%(refname)", "refs/heads").splitlines():
        name = ref[len("refs/heads/"):]
        if name == "main" or name in busy:
            continue
        ahead = len(git(repo, "rev-list", ref, "--not", "--remotes").split())
        if not ahead:
            continue
        date = git(repo, "log", "-1", "--format=%cs", ref).strip()
        pct = share(repo, ref, mains)
        if pct is None:
            pct, verdict = "-", "unclear"
        else:
            verdict = "main" if pct >= ON_MAIN else "only-here" if pct <= NOT_ON_MAIN else "partly"
        rows.append((name, ahead, date, pct, verdict))
    return rows


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("list", "note"):
        sys.exit("usage: local_branches.py list|note <checkout>")
    cmd, repo = sys.argv[1], sys.argv[2]
    rows = branches(repo)
    if cmd == "list":
        for row in rows:
            print("\t".join(map(str, row)))
        return
    alone = [r[0] for r in rows if r[4] != "main"]
    if alone:
        print(f"instruments: {len(alone)} local branch(es) hold work found nowhere else "
              f"({', '.join(alone[:3])}{', …' if len(alone) > 3 else ''}) — sclaude doctor says more")


if __name__ == "__main__":
    main()
