#!/usr/bin/env python3
#
# One line per finished feature, kept after the worktree is gone.
#
# Everything the cycle learns about itself — how long each step took, how many
# fixing sessions a red regression needed, which friction reviews committed and
# which found every ban deliberate — is written into `.sclaude/local/feature/state.json`, and
# `sclaude done` removes that file along with the worktree the moment the pull
# request merges. So the questions the record could answer have never been
# askable: whether the cycle is getting faster, which step actually holds it up,
# whether the regression's two attempts are enough or generous.
#
# This turns the state into one flat record and appends it to a file outside
# every repository. Append-only, JSON Lines: a finished feature is a fact, and a
# format where the last line is the only writable one cannot corrupt the
# nineteen above it if the machine dies mid-write.
#
# It is deliberately not a database and deliberately not aggregated here. Twenty
# lines of JSON answer a question with `jq` in one command; a schema would have
# to be decided now, before anybody has looked at the data, and that is the
# wrong order.
#
# Silent on any trouble, like every other best-effort part of the cycle: an
# unreadable state, a directory that cannot be created, a disk that is full —
# nothing is written and nothing is said beyond the return code. Losing a
# measurement must never stand in the way of cleaning up a merged feature.
import json
import os
import subprocess
import sys
from datetime import datetime

# Where the file lives, and why not in the repository: $REPO is the product's
# tree, where steps 2-4 work and `git add -A` is an everyday thing. A service
# file with timings would ride into somebody else's commit. The same reasoning
# put epilogue_state and the QA watch here.
#
# One file for every feature of every repository, with the repo named in each
# record. The alternative — a file per repository — would answer "how is this
# project going" a little more directly and "how is the cycle going" not at all,
# and the second is the question this exists for.
LOG = "~/.claude/sclaude/cycles.jsonl"

# The steps, in the cycle's order. Restated here rather than read from steps.sh:
# this file is read by a person looking at old data, where a step that has since
# been renamed or removed still has to come out in the order it ran in.
STEPS = ("plan", "code", "pr", "review")

# The regression's stages, in the order they run.
STAGES = ("local", "preview", "prod")


def log_path():
    return os.path.expanduser(LOG)


def parse_time(value):
    """An ISO timestamp as a datetime, or None for anything unparseable.

    `date -Iseconds` writes an offset as `+03:00`, which every Python since 3.7
    reads. A None, an empty string or a value from a state written by hand comes
    back as None rather than raising: a missing timestamp means one duration is
    unknown, not that the record is.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def seconds_between(start, finish):
    """Whole seconds from start to finish, or None when either is unknown.

    A negative result comes back as None too. It means the clock moved
    backwards between the two writes — a suspend, an NTP correction — and a
    negative duration in the log would be read as data rather than as the
    artefact it is.
    """
    a, b = parse_time(start), parse_time(finish)
    if a is None or b is None:
        return None
    delta = int((b - a).total_seconds())
    return delta if delta >= 0 else None


def step_record(state, step):
    """What one step cost: its duration, and how its friction review ended.

    A step nobody reached has no `started`, and comes back as None rather than
    as zero — "it did not run" and "it ran instantly" are different facts, and
    zero would average in as the second.
    """
    node = (state.get("steps") or {}).get(step) or {}
    started, finished = node.get("started"), node.get("finished")
    if not started:
        return None

    out = {
        "seconds": seconds_between(started, finished),
        "done": bool(node.get("done")),
    }

    # The friction reviews that followed the step's sessions. Their verdict is
    # the one thing here no amount of reading commits recovers: a review that
    # read every entry and found each ban correct changes nothing and leaves no
    # trace.
    #
    # One per session now, keyed `<step>-<n>`; a feature from before that has
    # one keyed by the step. The record stays one per step, so the reviews are
    # folded: empty only if every log was, fixed or stalled if any was, the
    # verdict `mixed` when they disagree, and the time spent summed.
    reviews = state.get("friction") or {}
    nodes = [node for key, node in reviews.items()
             if isinstance(node, dict)
             and (key == step or (key.startswith(step + "-")
                                  and key[len(step) + 1:].isdigit()))]
    if nodes:
        verdicts = {n.get("verdict") for n in nodes if n.get("verdict")}
        spent = [seconds_between(n.get("started"), n.get("finished")) for n in nodes]
        spent = [x for x in spent if x is not None]
        out["friction"] = {
            "empty": all(n.get("empty") for n in nodes),
            "fixed": any(n.get("fixed") for n in nodes),
            "stalled": any(n.get("stalled") for n in nodes),
            "verdict": verdicts.pop() if len(verdicts) == 1 else ("mixed" if verdicts else None),
            "seconds": sum(spent) if spent else None,
        }
    return out


def stage_record(state, stage):
    """What one regression stage cost: its outcome, attempts and fixing sessions.

    `fixes` and `fix_status` are space-joined strings that agree position for
    position — state_set writes scalars, which is what made them strings. They
    are split back into a list here: a reader counting fixing sessions should
    not have to know how they were stored.
    """
    node = (state.get("regression") or {}).get(stage) or {}
    if not node.get("status") and not node.get("started"):
        return None

    fixes = str(node.get("fixes") or "").split()
    statuses = str(node.get("fix_status") or "").split()
    return {
        "status": node.get("status"),
        "failed_at": node.get("failed_at"),
        "attempts": node.get("attempts") or 0,
        "seconds": seconds_between(node.get("started"), node.get("finished")),
        # Zipped rather than kept as two lists: they are already aligned, and
        # two lists in a log invite a reader to align them a second time and
        # get it wrong.
        #
        # Indexed rather than zipped, because zip stops at the shorter of the
        # two. The pair goes out of step in one real case — a session is
        # recorded when it starts and its outcome only when it ends, so a cycle
        # interrupted mid-fix has one more fix than statuses — and zip would
        # silently drop precisely the session that was interrupted.
        "fixes": [{"session": fix,
                   "status": statuses[i] if i < len(statuses) else None}
                  for i, fix in enumerate(fixes)],
    }


def record(state, outcome):
    """The whole cycle as one flat record.

    `outcome` is how the feature left: "done" for a merged one cleaned up by
    `sclaude done`, "dropped" for one abandoned by `sclaude drop`. Both are
    worth keeping and they must never be averaged together — an abandoned
    feature's timings describe a decision, not a cycle.
    """
    started = state.get("started")
    out = {
        "feature": state.get("feature"),
        "repo": state.get("repo"),
        # Who ran the cycle — developer.sh's name, handed over by
        # metrics_append. None rather than "" where nobody could be named, for
        # the same reason as every other absence in this record.
        "developer": os.environ.get("SCLAUDE_DEVELOPER") or None,
        "issue": state.get("issue"),
        "pr": state.get("pr"),
        "outcome": outcome,
        "started": started,
        "ended": datetime.now().astimezone().isoformat(timespec="seconds"),
        "step": state.get("step"),
    }
    out["seconds"] = seconds_between(started, out["ended"])

    steps = {}
    for step in STEPS:
        found = step_record(state, step)
        if found is not None:
            steps[step] = found
    out["steps"] = steps

    stages = {}
    for stage in STAGES:
        found = stage_record(state, stage)
        if found is not None:
            stages[stage] = found
    out["regression"] = stages

    # Whether the feature reached each stage of shipping. Read from the deploy
    # notes rather than from the labels: the labels live on GitHub and say what
    # is true now, while this says what this cycle did.
    deploy = state.get("deploy") or {}
    out["deployed"] = sorted(key for key in ("preview", "prod")
                             if (deploy.get(key) or {}).get("sha"))

    # Whether production had to be put back, and what the schema did about it.
    # Absent for the ordinary feature, which is most of them: a key that is there
    # only when something went wrong reads correctly in a log, where a `false`
    # would have to be counted past every time.
    rollback = state.get("rollback") or {}
    prod_rb = rollback.get("prod") or {}
    if prod_rb.get("code") == "done":
        out["rollback"] = {
            "at": prod_rb.get("at"),
            "to_sha": prod_rb.get("to_sha"),
            # What became of the schema: reverted, declined, partial, ahead or
            # none. The interesting number over twenty features is how often it
            # is anything but `reverted` — that is the cost of forward-only
            # migrations, measured rather than argued about.
            "schema": (rollback.get("db") or {}).get("status"),
            "confirmed": ((state.get("regression") or {})
                          .get("rollback") or {}).get("status"),
        }
    return out


def append(state_path, outcome, path=None):
    """Append one record. True when it was written, False on any trouble."""
    try:
        with open(state_path) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(state, dict):
        return False

    target = path or log_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        line = json.dumps(record(state, outcome), ensure_ascii=False)
        # One write of one line, opened for append. Short lines are written
        # atomically by the kernel, so a reader never sees half a record and a
        # second sclaude finishing a feature at the same moment cannot
        # interleave with this one.
        with open(target, "a") as fh:
            fh.write(line + "\n")
    except (OSError, ValueError, TypeError):
        return False
    return True


# --- a team's records in one place ------------------------------------------
#
# The log above is one machine's. A team that wants to look at its cycles
# together names a git repository of its own in this file; each developer's
# records are published there as <developer>.jsonl, one file per person, so two
# people publishing at once never touch the same lines and a merge never
# conflicts. One `jq` over the directory is the team's picture.
#
# Deliberately not the instruments repository: everybody installs from that
# one, and a record carries feature names and repository paths that belong to
# the team, not to everybody who can read the orchestrator. And deliberately
# nothing by default: no file, no publishing — the records stay on this
# machine, as they always did.
REMOTE_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or "~/.config",
                           "sclaude", "metrics-remote")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or "~/.cache",
                     "sclaude", "metrics")


def remote_url():
    try:
        with open(os.path.expanduser(REMOTE_FILE)) as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    return line
    except OSError:
        pass
    return ""


def git(cwd, *args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True,
                          text=True, timeout=60, env=env)


def publish(developer, url=None, log=None, cache=None):
    """Put this machine's records into <developer>.jsonl in the team's repo.

    The file there becomes the union of what it held and what this machine
    has, in order, without duplicates — so a developer on two machines keeps
    the records of both. True when there was nothing to do or it was pushed.
    """
    url = url if url is not None else remote_url()
    if not developer or not url:
        return True
    source = os.path.expanduser(log or log_path())
    try:
        with open(source, encoding="utf-8") as fh:
            mine = [line.rstrip("\n") for line in fh if line.strip()]
    except OSError:
        return True
    if not mine:
        return True

    cache = os.path.expanduser(cache or CACHE)
    try:
        if not os.path.isdir(os.path.join(cache, ".git")):
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            done = subprocess.run(["git", "clone", "-q", url, cache],
                                  capture_output=True, text=True, timeout=120,
                                  env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
            if done.returncode != 0:
                return False
        for _ in range(2):
            branch = git(cache, "symbolic-ref", "--short", "HEAD").stdout.strip() or "main"
            has_remote = git(cache, "ls-remote", "--exit-code", "origin", branch).returncode == 0
            if has_remote:
                git(cache, "fetch", "-q", "origin", branch)
                git(cache, "reset", "-q", "--hard", "origin/" + branch)
            target = os.path.join(cache, developer + ".jsonl")
            try:
                with open(target, encoding="utf-8") as fh:
                    theirs = [line.rstrip("\n") for line in fh if line.strip()]
            except OSError:
                theirs = []
            seen = set(theirs)
            merged = theirs + [line for line in mine if line not in seen]
            if merged == theirs:
                return True
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("\n".join(merged) + "\n")
            git(cache, "add", developer + ".jsonl")
            if git(cache, "commit", "-qm", "metrics: %s" % developer).returncode != 0:
                return False
            if git(cache, "push", "-q", "origin", "HEAD:" + branch).returncode == 0:
                return True
            # Somebody else published in between: their file, not ours, so
            # starting again from their commit always applies.
        return False
    except (OSError, subprocess.TimeoutExpired):
        return False


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "publish":
        return 0 if publish(sys.argv[2]) else 1
    if len(sys.argv) < 3:
        return 0
    return 0 if append(sys.argv[1], sys.argv[2],
                       sys.argv[3] if len(sys.argv) > 3 else None) else 1


if __name__ == "__main__":
    sys.exit(main())
