#!/usr/bin/env python3
#
# A test bench for the cycle's record — the one line per feature that outlives
# the worktree.
#
# What is guarded here is mostly the difference between "unknown" and "zero".
# The record is written to be averaged over twenty features, and a missing
# timestamp that comes out as 0 does not look wrong in a log: it looks like a
# step that took no time, and it drags every average it lands in. Every case
# below where a value is absent checks for None rather than for a falsy value.
#
# The other half is that nothing here may raise. A state written by an older
# sclaude, one interrupted mid-write, one edited by hand — each must come back
# as a record with holes in it, because the alternative is a cleanup that dies
# on the way to removing a merged feature's worktree.
#
# Run it with: python3 tests/metrics.py
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "sclaude", "lib"))
from metrics import append, record, seconds_between, stage_record, step_record

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


# A state in the shape sclaude really writes: the keys come from the state_set
# calls in run.sh, regression.sh and deploy.sh.
FULL = {
    "feature": "71-email-edit",
    "repo": "/home/x/myapp",
    "issue": 71,
    "pr": 208,
    "step": "done",
    "started": "2026-09-10T09:00:00+03:00",
    "steps": {
        "plan": {"session": "a", "started": "2026-09-10T09:00:00+03:00",
                 "finished": "2026-09-10T09:30:00+03:00", "done": True},
        "code": {"session": "b", "started": "2026-09-10T10:00:00+03:00",
                 "finished": "2026-09-10T14:00:00+03:00", "done": True},
        "pr": {"session": "c", "started": "2026-09-10T14:10:00+03:00",
               "finished": "2026-09-10T14:40:00+03:00", "done": True},
        "review": {"session": "d", "started": "2026-09-10T15:00:00+03:00",
                   "finished": "2026-09-11T11:00:00+03:00", "done": True},
    },
    "friction": {
        "plan": {"empty": True},
        "code": {"session": None, "was": "e", "fixed": True,
                 "verdict": "lifted",
                 "started": "2026-09-10T14:00:00+03:00",
                 "finished": "2026-09-10T14:08:00+03:00"},
        "review": {"was": "f", "fixed": False, "verdict": "deliberate",
                   "started": "2026-09-11T11:00:00+03:00",
                   "finished": "2026-09-11T11:05:00+03:00"},
    },
    "regression": {
        "local": {"status": "passed", "attempts": 0,
                  "started": "2026-09-10T13:40:00+03:00",
                  "finished": "2026-09-10T13:55:00+03:00"},
        "preview": {"status": "passed", "attempts": 0, "failed_at": None,
                    "fixes": "1a2b3c4d 5e6f7a8b",
                    "fix_status": "red green",
                    "started": "2026-09-11T11:30:00+03:00",
                    "finished": "2026-09-11T11:50:00+03:00"},
    },
    "deploy": {"preview": {"sha": "abc123"}, "prod": {"sha": "def456"}},
}


# --- durations ---------------------------------------------------------------

check("seconds-plain",
      seconds_between("2026-09-10T09:00:00+03:00", "2026-09-10T09:30:00+03:00"),
      1800)
# Across an offset: both sides carry their own, and the arithmetic is absolute.
check("seconds-across-offsets",
      seconds_between("2026-09-10T09:00:00+03:00", "2026-09-10T07:30:00+01:00"),
      1800)
check("seconds-missing-start", seconds_between(None, "2026-09-10T09:30:00+03:00"), None)
check("seconds-missing-finish", seconds_between("2026-09-10T09:00:00+03:00", None), None)
check("seconds-unparseable", seconds_between("yesterday", "today"), None)
# A clock that moved backwards between the two writes — a suspend, an NTP
# correction. None rather than a negative number: a negative duration in the log
# would be read as data rather than as the artefact it is.
check("seconds-negative-is-unknown",
      seconds_between("2026-09-10T09:30:00+03:00", "2026-09-10T09:00:00+03:00"),
      None)


# --- one step ----------------------------------------------------------------

got = step_record(FULL, "code")
check("step-seconds", got["seconds"], 4 * 3600)
check("step-done", got["done"], True)
check("step-friction-fixed", got["friction"]["fixed"], True)
check("step-friction-verdict", got["friction"]["verdict"], "lifted")
check("step-friction-seconds", got["friction"]["seconds"], 8 * 60)

# A review that read every entry and changed nothing. `fixed` false and a
# verdict of `deliberate` are different facts and both are kept: the first says
# no commit was made, the second says that was the finding rather than a
# session that died.
review = step_record(FULL, "review")
check("step-friction-deliberate", review["friction"]["fixed"], False)
check("step-friction-deliberate-verdict", review["friction"]["verdict"], "deliberate")

# An empty log means no session was launched at all. That is the ordinary case,
# and it must not look like a review that ran and found nothing.
plan = step_record(FULL, "plan")
check("step-friction-empty", plan["friction"]["empty"], True)
check("step-friction-empty-not-fixed", plan["friction"]["fixed"], False)

# Reviews kept per session (`<step>-<n>`) fold into the step's record: one
# lifted and one deliberate is `mixed`, any fix is a fix, the time is summed,
# and the log counts as empty only if every session's was.
PER_RUN = {"steps": {"review": {"started": "2026-09-11T09:00:00+03:00"}},
           "friction": {
               "review-1": {"empty": True},
               "review-2": {"fixed": True, "verdict": "lifted",
                            "started": "2026-09-11T10:00:00+03:00",
                            "finished": "2026-09-11T10:04:00+03:00"},
               "review-3": {"verdict": "deliberate",
                            "started": "2026-09-11T11:00:00+03:00",
                            "finished": "2026-09-11T11:02:00+03:00"},
               "reviewer": {"fixed": False},
           }}
folded = step_record(PER_RUN, "review")["friction"]
check("per-run-folded-verdict", folded["verdict"], "mixed")
check("per-run-folded-fixed", folded["fixed"], True)
check("per-run-folded-seconds", folded["seconds"], 6 * 60)
check("per-run-folded-not-empty", folded["empty"], False)

# A step nobody reached. None, not a record of zeroes: "did not run" and "ran
# instantly" are different facts, and zero would average in as the second.
check("step-never-started", step_record({"steps": {}}, "code"), None)
check("step-no-steps-at-all", step_record({}, "code"), None)

# Started and not finished — the cycle was interrupted inside the step. The
# record exists, its duration is unknown.
half = step_record({"steps": {"code": {"started": "2026-09-10T10:00:00+03:00"}}},
                   "code")
check("step-unfinished-exists", half is not None, True)
check("step-unfinished-seconds", half["seconds"], None)
check("step-unfinished-not-done", half["done"], False)


# --- one regression stage ----------------------------------------------------

prev = stage_record(FULL, "preview")
check("stage-status", prev["status"], "passed")
check("stage-seconds", prev["seconds"], 20 * 60)
check("stage-fix-count", len(prev["fixes"]), 2)
check("stage-fix-first", prev["fixes"][0], {"session": "1a2b3c4d", "status": "red"})
check("stage-fix-second", prev["fixes"][1], {"session": "5e6f7a8b", "status": "green"})

# A stage that never ran. None rather than an empty shell: prod is simply
# absent from a feature that was not shipped, and a zeroed record would say it
# ran and passed instantly.
check("stage-never-ran", stage_record(FULL, "prod"), None)

# The two strings out of step. A fixing session is recorded when it starts and
# its outcome only when it ends, so a cycle interrupted mid-fix has one more
# fix than statuses. zip would silently drop precisely the interrupted session
# — the one worth seeing.
ragged = stage_record({"regression": {"local": {
    "status": "failed", "fixes": "aaa bbb ccc", "fix_status": "red red"}}},
    "local")
check("stage-ragged-keeps-all", len(ragged["fixes"]), 3)
check("stage-ragged-last-unknown", ragged["fixes"][2]["status"], None)

# No fixing sessions at all: an empty list, not a list holding an empty string.
clean = stage_record({"regression": {"local": {"status": "passed"}}}, "local")
check("stage-no-fixes", clean["fixes"], [])
check("stage-no-attempts", clean["attempts"], 0)


# --- the whole record --------------------------------------------------------

full = record(FULL, "done")
check("record-feature", full["feature"], "71-email-edit")
check("record-issue", full["issue"], 71)
check("record-outcome", full["outcome"], "done")
check("record-step-count", len(full["steps"]), 4)
check("record-stage-count", len(full["regression"]), 2)
check("record-deployed", full["deployed"], ["preview", "prod"])
check_true("record-has-ended", bool(full["ended"]))
check_true("record-total-seconds", full["seconds"] is not None)

# A feature that never went back has no rollback key at all. Absent rather than
# a `false`: most features are this one, and a log where the ordinary case
# carries a field saying nothing happened is a log you read past.
check("record-no-rollback-key", "rollback" in full, False)

# One that did. The schema's fate is the number worth having over twenty
# features — how often it is anything but `reverted` is the price of
# forward-only migrations, measured rather than argued about.
rolled = record(dict(FULL,
                     rollback={"prod": {"code": "done",
                                        "at": "2026-09-11T12:00:00+03:00",
                                        "to_sha": "abc123"},
                               "db": {"status": "ahead"}},
                     regression=dict(FULL["regression"],
                                     rollback={"status": "passed"})),
                "done")
check_true("record-rollback-present", "rollback" in rolled)
check("record-rollback-schema", rolled["rollback"]["schema"], "ahead")
check("record-rollback-confirmed", rolled["rollback"]["confirmed"], "passed")
check("record-rollback-to", rolled["rollback"]["to_sha"], "abc123")

# A rollback that was refused or failed is not one that happened.
for code in ("refused", "failed"):
    partial = record(dict(FULL, rollback={"prod": {"code": code}}), "done")
    check("record-rollback-%s-absent" % code, "rollback" in partial, False)

# The confirmation run stays out of the feature's own regression record: it is
# its own stage, and a reader counting prod runs must not find it among them.
check("record-rollback-not-a-prod-stage",
      "rollback" in rolled["regression"], False)

# An abandoned feature. The outcome is what keeps the two apart, and it must
# never be inferred from how far the cycle got: a feature dropped at step 4
# looks exactly like one that finished, apart from this field.
dropped = record(FULL, "dropped")
check("record-dropped-outcome", dropped["outcome"], "dropped")

# A state from an older sclaude, with almost nothing in it. Holes, not an
# exception: this runs on the way to removing a merged feature's worktree.
bare = record({"feature": "old"}, "done")
check("record-bare-feature", bare["feature"], "old")
check("record-bare-steps", bare["steps"], {})
check("record-bare-regression", bare["regression"], {})
check("record-bare-deployed", bare["deployed"], [])
check("record-bare-seconds", bare["seconds"], None)

# Deployed reads the deploy notes, not the labels: the labels live on GitHub and
# say what is true now, this says what this cycle did.
one = record(dict(FULL, deploy={"preview": {"sha": "abc"}}), "done")
check("record-deployed-preview-only", one["deployed"], ["preview"])
# A stage that was recorded without a sha is not a deploy.
none = record(dict(FULL, deploy={"preview": {}}), "done")
check("record-deployed-empty-sha", none["deployed"], [])


# --- appending ---------------------------------------------------------------

tmp = tempfile.mkdtemp()
try:
    state = os.path.join(tmp, "state.json")
    with open(state, "w") as fh:
        json.dump(FULL, fh)
    log = os.path.join(tmp, "nested", "cycles.jsonl")

    check("append-writes", append(state, "done", log), True)
    check_true("append-created-the-dir", os.path.exists(log))

    # Append-only: a second feature adds a line and leaves the first alone.
    # This is the property the format was chosen for — the last line is the
    # only writable one, so a machine dying mid-write cannot corrupt what is
    # above it.
    append(state, "dropped", log)
    lines = open(log).read().strip().split("\n")
    check("append-two-lines", len(lines), 2)
    check("append-first-intact", json.loads(lines[0])["outcome"], "done")
    check("append-second", json.loads(lines[1])["outcome"], "dropped")
    check("append-one-line-each", any("\n" in line for line in lines), False)

    # Each line is valid JSON on its own — that is what makes the file readable
    # with jq without loading all of it.
    check("append-lines-parse",
          [json.loads(line)["feature"] for line in lines],
          ["71-email-edit", "71-email-edit"])

    # A state that cannot be read. False, and nothing written: losing a
    # measurement must not stand in the way of a cleanup.
    check("append-missing-state",
          append(os.path.join(tmp, "nope.json"), "done", log), False)

    with open(os.path.join(tmp, "broken.json"), "w") as fh:
        fh.write("{not json")
    check("append-broken-state",
          append(os.path.join(tmp, "broken.json"), "done", log), False)

    # A state holding something that is not an object at all.
    with open(os.path.join(tmp, "list.json"), "w") as fh:
        fh.write("[1, 2, 3]")
    check("append-non-object-state",
          append(os.path.join(tmp, "list.json"), "done", log), False)

    # None of those wrote anything.
    check("append-failures-wrote-nothing",
          len(open(log).read().strip().split("\n")), 2)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# --- who ran it ---------------------------------------------------------------
os.environ.pop("SCLAUDE_DEVELOPER", None)
check("developer-absent-is-none", record(FULL, "done").get("developer", "missing"), None)
os.environ["SCLAUDE_DEVELOPER"] = "alice"
check("developer-recorded", record(FULL, "done")["developer"], "alice")
os.environ.pop("SCLAUDE_DEVELOPER")

# --- publishing to the team's repository -------------------------------------
#
# A bare repository plays the team's; two machines publish into it. Each
# developer gets a file of their own, a second machine of the same developer
# adds its lines rather than replacing the first's, and publishing twice adds
# nothing.
import subprocess
from metrics import publish

pub = tempfile.mkdtemp()
try:
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1")
    team = os.path.join(pub, "team.git")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", team], check=True)
    seed = os.path.join(pub, "seed")
    subprocess.run(["git", "clone", "-q", team, seed], check=True, capture_output=True)
    for args in (["config", "user.email", "s@x"], ["config", "user.name", "S"],
                 ["commit", "-q", "--allow-empty", "-m", "start"],
                 ["push", "-q", "origin", "HEAD:main"]):
        subprocess.run(["git", "-C", seed] + args, check=True, capture_output=True)
    os.environ.setdefault("GIT_AUTHOR_NAME", "T")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "t@x")
    os.environ.setdefault("GIT_COMMITTER_NAME", "T")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "t@x")

    def machine(name, lines):
        path = os.path.join(pub, name + ".jsonl")
        with open(path, "w") as fh:
            fh.write("".join(line + "\n" for line in lines))
        return path

    def published(dev):
        out = subprocess.run(["git", "-C", team, "show", "main:%s.jsonl" % dev],
                             capture_output=True, text=True)
        return out.stdout.split()

    check("publish-nothing-configured",
          publish("alice", url="", log=machine("a1", ['{"n":1}']),
                  cache=os.path.join(pub, "c0")), True)
    check_true("publish-nothing-configured-no-clone",
               not os.path.exists(os.path.join(pub, "c0")))

    check("publish-alice", publish("alice", url=team, log=machine("a1", ['{"n":1}']),
                                   cache=os.path.join(pub, "ca")), True)
    check("publish-bob", publish("bob", url=team, log=machine("b1", ['{"n":9}']),
                                 cache=os.path.join(pub, "cb")), True)
    check("publish-files-per-developer", (published("alice"), published("bob")),
          (['{"n":1}'], ['{"n":9}']))
    # Alice's second machine, with its own cache and one record of its own.
    check("publish-second-machine", publish("alice", url=team,
                                            log=machine("a2", ['{"n":2}']),
                                            cache=os.path.join(pub, "ca2")), True)
    check("publish-union-in-order", published("alice"), ['{"n":1}', '{"n":2}'])
    before = subprocess.run(["git", "-C", team, "rev-parse", "main"],
                            capture_output=True, text=True).stdout
    publish("alice", url=team, log=machine("a1", ['{"n":1}']), cache=os.path.join(pub, "ca"))
    after = subprocess.run(["git", "-C", team, "rev-parse", "main"],
                           capture_output=True, text=True).stdout
    check("publish-idempotent", after, before)
    check("publish-no-developer", publish("", url=team, log=machine("x", ['{"n":5}']),
                                          cache=os.path.join(pub, "cx")), True)
    check_true("publish-no-developer-no-clone", not os.path.exists(os.path.join(pub, "cx")))
finally:
    shutil.rmtree(pub, ignore_errors=True)


if failures:
    for name, want, got in failures:
        sys.stderr.write("FAIL %s\n  want: %r\n  got:  %r\n" % (name, want, got))
    sys.stderr.write("\n%d failure(s)\n" % len(failures))
    sys.exit(1)

print("ok")
