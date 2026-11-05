#!/usr/bin/env python3
#
# What sclaude measures about a product, as one page in its own tree. First
# the four DORA metrics:
#
#   deployment frequency   production deploys per week
#   lead time for changes  a change's first commit to the deploy that shipped it
#   change failure rate    the share of production deploys that had to be undone
#   time to restore        a failed deploy to production serving again
#
# then the rest of DORA and a pull request's way (metrics_extra.py: rework and
# hotfix rates, lead time by stage, coding, pickup, review and merge time),
# delivery (features shipped, cycle time, time to market, flow efficiency),
# software quality (dev_quality.py and metrics_extra.py: regression first
# time, escaped defects, reopened issues, work by commit type, review threads,
# acceptance criteria, friction), code health and project hygiene, and
# Claude's own work and what it cost (claude_usage.py: sessions, autonomy,
# tool calls, tokens, dollars per result, weekly trends).
#
# The page is the product's, not the orchestrator's: its numbers, commits and
# feature names describe one team's work. So it is written into the product,
# at .sclaude/local/dora/index.html, beside the caches it is built from, and
# sclaude-proxy serves it under the `main` row of its list. local/ rather than
# the committed part of .sclaude/: the page is rebuilt every few hours, and a
# file that changes by itself in a tracked folder would dirty the main
# checkout — the one place where "uncommitted changes" must mean somebody's
# work.
#
# Read, never recorded anew. Every number comes from what already exists:
#
#   Vercel        the production deployments, with their commit and time —
#                 the one list of what actually reached production
#   git           which commits each deploy shipped first
#   GitHub        each merged pull request's first commit, and the incident
#                 comments rollback_incident writes on a feature's issue
#   cycles.jsonl  metrics.py's record of every finished feature: where its
#                 cycle time went, step by step, and a rollback as a fallback
#                 for an incident GitHub cannot be asked about
#   transcripts   Claude Code's record of every session in the product's trees
#
# What Vercel and GitHub answered is kept in the same folder and merged with
# every later answer, so history outlives Vercel's retention and a refresh with
# no network still draws the last known picture.
#
# Rebuilt rarely, in the background: `sclaude` starts it on every
# conversational run (dora_refresh in state.sh), and it does nothing unless the
# page is older than SCLAUDE_DORA_EVERY seconds (six hours). A finished feature
# forces it — that is when the numbers move. Two sclaudes starting together
# build it once: the second finds the lock taken and leaves.
#
#   dora.py refresh <repo> [--force]   rebuild if stale (or always), quietly
#   dora.py build <repo>               rebuild now and print the page's path
#
# Silent on any trouble, like metrics.py: a source that cannot be read leaves a
# hole on the page, which says which source it was, and never an error.

import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import dora_numbers, dora_page, dora_store


EVERY = 6 * 3600


# --- building -----------------------------------------------------------------

def build(repo, now=None):
    data = dora_numbers.collect(repo)
    page = dora_page.render(repo, data, dora_numbers.compute(repo, data, now))
    target = os.path.join(dora_store.out_dir(repo), dora_store.PAGE)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(page)
    os.replace(tmp, target)
    return target


def stale(repo, every=None):
    if every is None:
        try:
            every = int(os.environ.get("SCLAUDE_DORA_EVERY") or EVERY)
        except ValueError:
            every = EVERY
    try:
        return time.time() - os.path.getmtime(os.path.join(dora_store.out_dir(repo), dora_store.PAGE)) >= every
    except OSError:
        return True


def refresh(repo, force=False):
    """Build when stale or forced, once however many ask at the same time.
    True when it built."""
    if not os.path.isdir(os.path.join(repo, ".git")):
        return False
    if not force and not stale(repo):
        return False
    try:
        os.makedirs(dora_store.out_dir(repo), exist_ok=True)
        lock = open(os.path.join(dora_store.out_dir(repo), ".lock"), "w")
    except OSError:
        return False
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        # Looked at again under the lock: the one that held it may have just
        # built the page this run was about to.
        if not force and not stale(repo):
            return False
        try:
            build(repo)
        except (OSError, ValueError, TypeError, KeyError):
            return False
    return True


def main():
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "refresh":
        return 0 if refresh(args[1], "--force" in args[2:]) else 1
    if len(args) >= 2 and args[0] == "build":
        print(build(args[1]))
        return 0
    print("usage: dora.py refresh <repo> [--force] | build <repo>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
