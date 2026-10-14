#!/usr/bin/env python3
#
# A bench for instruments_sync and instruments_propose: how the orchestrator
# keeps itself up to date and how a change to it is proposed.
#
# Everybody installs instruments from one repository, so this is the only way a
# fix reaches a team; and MAINTAINERS decides who may commit the orchestrator
# to main. The failures are all quiet ones:
#
#   no update             every machine runs whatever it cloned months ago.
#   a merge into dirt     somebody's hand edit is mixed with upstream's.
#   a conflict left open  the orchestrator is left half-merged and cannot load.
#   a stranger on main    their friction fix lands on everybody's main.
#   a new branch unpushed dev/<name> never leaves the machine, because a count
#                         against a missing origin/<branch> read as "nothing".
#
# A bare repository plays origin; the clone plays $INSTRUMENTS. $0 is a stub
# that records the re-execution instead of performing it.
#
# Run it with: python3 tests/sync.py
import os
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib")

failures = []


def check(name, got, want):
    if got == want:
        print("  PASS  %s" % name)
    else:
        failures.append(name)
        print("  FAIL  %s" % name)
        print("        want: %r" % (want,))
        print("        got:  %r" % (got,))


ENV = {k: v for k, v in os.environ.items()
       if not k.startswith("GIT_") and not k.startswith("SCLAUDE_")}
ENV.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                          text=True, env=ENV).stdout.strip()


def commit(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "edit " + name)


class World:
    def __init__(self, tmp, email="me@x.test", maintainers=None):
        self.origin = os.path.join(tmp, "origin.git")
        self.up = os.path.join(tmp, "upstream")   # somebody else's clone
        self.me = os.path.join(tmp, "instruments")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin],
                       env=ENV, check=True)
        subprocess.run(["git", "clone", "-q", self.origin, self.up], env=ENV,
                       capture_output=True)
        git(self.up, "config", "user.email", "up@x.test")
        git(self.up, "config", "user.name", "Up")
        if maintainers is not None:
            with open(os.path.join(self.up, "MAINTAINERS"), "w") as fh:
                fh.write("".join(m + "\n" for m in maintainers))
        commit(self.up, "a.txt", "one\n")
        git(self.up, "push", "-q", "origin", "main")
        subprocess.run(["git", "clone", "-q", self.origin, self.me], env=ENV,
                       capture_output=True)
        git(self.me, "config", "user.email", email)
        git(self.me, "config", "user.name", "Me")
        self.reexec = os.path.join(tmp, "reexec")
        with open(self.reexec, "w") as fh:
            fh.write('#!/usr/bin/env bash\necho "REEXEC $SCLAUDE_SYNCED $*"\n')
        os.chmod(self.reexec, 0o755)

    def upstream_commit(self, name="b.txt", text="two\n"):
        commit(self.up, name, text)
        git(self.up, "push", "-q", "origin", "main")

    def run(self, fn="instruments_sync", env=None):
        script = """
info() { echo "INFO $*"; }
warn() { echo "WARN $*"; }
INSTRUMENTS=%s
SELF=sclaude
source %s/developer.sh
source %s/run.sh
# Other sclaude processes on the real machine must not decide this bench.
[[ -n "${OTHERS:-}" ]] && instruments_others() { echo 4242; } || instruments_others() { return 1; }
%s one two
echo "RETURNED"
""" % (self.me, LIB, LIB, fn)
        full = dict(ENV)
        if env:
            full.update(env)
        done = subprocess.run(["bash", "-c", script, self.reexec],
                              capture_output=True, text=True, env=full)
        return done.stdout

    def branch(self):
        return git(self.me, "rev-parse", "--abbrev-ref", "HEAD")


with tempfile.TemporaryDirectory() as tmp:
    print("maintainer on main (no MAINTAINERS file)")
    os.makedirs(os.path.join(tmp, "1"))
    w = World(os.path.join(tmp, "1"))
    out = w.run()
    check("nothing-to-do-returns", "RETURNED" in out and "REEXEC" not in out, True)
    w.upstream_commit()
    out = w.run()
    check("behind-fast-forwards", os.path.isfile(os.path.join(w.me, "b.txt")), True)
    check("behind-reexecutes-with-args", "REEXEC 1 one two" in out, True)
    check("reexec-guard", "REEXEC" in w.run(env={"SCLAUDE_SYNCED": "1"}), False)
    w.upstream_commit("c.txt")
    out = w.run(env={"SCLAUDE_NO_SYNC": "1"})
    check("no-sync-switch", os.path.isfile(os.path.join(w.me, "c.txt")), False)

    print("dirty tree")
    with open(os.path.join(w.me, "a.txt"), "w") as fh:
        fh.write("hand edit\n")
    out = w.run()
    check("dirty-not-updated", os.path.isfile(os.path.join(w.me, "c.txt")), False)
    check("dirty-said", "uncommitted changes" in out, True)
    check("dirty-edit-kept", open(os.path.join(w.me, "a.txt")).read(), "hand edit\n")

    print("offline")
    git(w.me, "checkout", "--", "a.txt")
    git(w.me, "remote", "set-url", "origin", os.path.join(tmp, "nowhere.git"))
    out = w.run()
    check("offline-silent", ("RETURNED" in out, "WARN" in out), (True, False))

    print("non-maintainer")
    os.makedirs(os.path.join(tmp, "2"))
    w = World(os.path.join(tmp, "2"), email="Alice.B@x.test",
              maintainers=["boss@x.test"])
    out = w.run()
    # Nobody is moved off main any more: the review sessions do not commit to
    # sclaude. A branch of one's own is made deliberately, to propose a change.
    check("non-maintainer-stays-on-main", w.branch(), "main")
    check("nothing-to-reexecute", "REEXEC" in out, False)
    git(w.me, "switch", "-q", "-c", "dev/alice-b")

    # Upstream moves; the developer's branch has a commit of its own.
    commit(w.me, "mine.txt", "mine\n")
    w.upstream_commit()
    out = w.run()
    check("main-merged-into-own-branch",
          (os.path.isfile(os.path.join(w.me, "b.txt")),
           os.path.isfile(os.path.join(w.me, "mine.txt")), w.branch()),
          (True, True, "dev/alice-b"))

    print("a second proposal's branch")
    git(w.me, "switch", "-q", "-c", "dev/alice-b-20261012-1400")
    w.upstream_commit("second.txt")
    out = w.run()
    check("timestamped-branch-merged", os.path.isfile(os.path.join(w.me, "second.txt")), True)
    git(w.me, "switch", "-q", "dev/alice-b")
    git(w.me, "branch", "-q", "-D", "dev/alice-b-20261012-1400")

    print("conflict")
    commit(w.me, "a.txt", "mine\n")
    w.upstream_commit("a.txt", "theirs\n")
    out = w.run()
    check("conflict-aborted", (git(w.me, "status", "--porcelain"),
                               open(os.path.join(w.me, "a.txt")).read()),
          ("", "mine\n"))
    check("conflict-said", "conflicts" in out, True)


    print("somebody else is running from it")
    w.upstream_commit("d.txt")
    out = w.run(env={"OTHERS": "1"})
    check("others-not-updated", (os.path.isfile(os.path.join(w.me, "d.txt")),
                                 "another sclaude" in out), (False, True))

    print("a branch that is not sclaude's")
    git(w.me, "merge", "--abort")
    git(w.me, "checkout", "-q", "-B", "wip/idea", "HEAD")
    commit(w.me, "idea.txt", "idea\n")
    out = w.run()
    check("wip-not-merged", (os.path.isfile(os.path.join(w.me, "d.txt")),
                             "not" in out and "sclaude's to merge into" in out), (False, True))

    print("a merge that fails without a conflict")
    git(w.me, "switch", "-q", "dev/alice-b")
    git(w.me, "reset", "-q", "--hard", "HEAD")
    w.upstream_commit("untracked.txt", "theirs\n")
    with open(os.path.join(w.me, "untracked.txt"), "w") as fh:
        fh.write("mine, untracked\n")
    out = w.run()
    check("non-conflict-failure-said-as-such",
          ("could not merge" in out, "conflicts" in out), (True, False))
    check("untracked-file-kept", open(os.path.join(w.me, "untracked.txt")).read(),
          "mine, untracked\n")


# --- a non-maintainer's pull request (instruments_propose) -------------------
#
# gh is a stub: it says who the repository is, whether this person may push,
# makes the "fork" as a second bare repository, and records the pull requests
# it is asked to open.
GH_STUB = r"""
gh() {
  case "$1 $2" in
    "repo view") echo boss/sclaude ;;
    "api repos/boss/sclaude") echo "$CAN_PUSH" ;;
    "api user") echo alice ;;
    "repo fork") git init -q --bare "$FORK" && git remote add fork "$FORK"; echo fork >> "$GH_LOG" ;;
    "pr list") [[ -s "$PR_OPEN" ]] && cat "$PR_OPEN" || true ;;
    "pr create") echo "create $*" >> "$GH_LOG"; echo https://pr/1 | tee "$PR_OPEN" ;;
  esac
}
"""

with tempfile.TemporaryDirectory() as tmp:
    for can_push in ("false", "true"):
        print("propose, can push: %s" % can_push)
        base = os.path.join(tmp, can_push)
        os.makedirs(base)
        w = World(base, email="Alice.B@x.test", maintainers=["boss@x.test"])
        git(w.me, "switch", "-q", "-c", "dev/alice-b")
        commit(w.me, "fix.txt", "fix\n")
        log, opened = os.path.join(base, "gh.log"), os.path.join(base, "pr")
        env = {"CAN_PUSH": can_push, "FORK": os.path.join(base, "fork.git"),
               "GH_LOG": log, "PR_OPEN": opened}
        out = w.run(GH_STUB + "instruments_propose dev/alice-b 1", env=env)
        calls = open(log).read() if os.path.exists(log) else ""
        target = os.path.join(base, "fork.git") if can_push == "false" else w.origin
        check("propose-%s-pushed" % can_push,
              git(target, "rev-parse", "--verify", "-q", "refs/heads/dev/alice-b") != "", True)
        check("propose-%s-forked" % can_push, "fork" in calls.split("\n"), can_push == "false")
        check("propose-%s-origin-kept" % can_push, git(w.me, "remote", "get-url", "origin"), w.origin)
        check("propose-%s-pr-opened" % can_push, sum(l.startswith("create ") for l in calls.splitlines()), 1)
        check("propose-%s-pr-head" % can_push,
              ("--head alice:dev/alice-b" if can_push == "false" else "--head dev/alice-b") in calls, True)
        check("propose-%s-said" % can_push, "opened a pull request: https://pr/1" in out, True)
        # The next push updates the same pull request rather than opening another.
        commit(w.me, "fix2.txt", "more\n")
        out = w.run(GH_STUB + "instruments_propose dev/alice-b 1", env=env)
        calls = open(log).read()
        check("propose-%s-one-fork" % can_push, calls.split("\n").count("fork"), 1 if can_push == "false" else 0)
        check("propose-%s-one-pr" % can_push, sum(l.startswith("create ") for l in calls.splitlines()), 1)
        check("propose-%s-pr-updated" % can_push, "your pull request has it" in out, True)

# --- sclaude propose: commits on main become a branch and a pull request ------
with tempfile.TemporaryDirectory() as tmp:
    print("propose from main")
    w = World(tmp, email="Alice.B@x.test", maintainers=["boss@x.test"])
    log, opened = os.path.join(tmp, "gh.log"), os.path.join(tmp, "pr")
    env = {"CAN_PUSH": "false", "FORK": os.path.join(tmp, "fork.git"), "GH_LOG": log, "PR_OPEN": opened}
    stub = GH_STUB + "main_repo() { echo \"$INSTRUMENTS\"; }\ndeferred_files() { :; }\n"
    out = w.run(stub + "cmd_propose", env=env)
    check("propose-nothing", "Nothing to propose" in out, True)
    with open(os.path.join(w.me, "a.txt"), "w") as fh:
        fh.write("edited, not committed\n")
    out = w.run(stub + "cmd_propose", env=env)
    check("propose-dirty-refused", "uncommitted changes" in out, True)
    git(w.me, "checkout", "--", "a.txt")
    commit(w.me, "better.txt", "a better default\n")
    head = git(w.me, "rev-parse", "HEAD")
    out = w.run(stub + "cmd_propose", env=env)
    check("propose-on-own-branch", w.branch(), "dev/alice-b")
    check("propose-branch-has-it", git(w.me, "rev-parse", "dev/alice-b"), head)
    check("propose-main-is-origins", git(w.me, "rev-parse", "main"), git(w.origin, "rev-parse", "main"))
    check("propose-pushed-to-fork", git(env["FORK"], "rev-parse", "--verify", "-q", "refs/heads/dev/alice-b"), head)
    check("propose-opened", "opened a pull request" in out, True)

# --- the net under the switch, and what the prompts tell the session ---------
#
# Read as text: driving run_friction for real needs a feature, a log and a
# claude, and what matters is only that the refusal comes before the session.
RUN = open(os.path.join(LIB, "run.sh"), encoding="utf-8").read()
friction = RUN[RUN.index("run_friction() {"):]
friction = friction[:friction.index("\n}\n")]
# The review no longer commits to sclaude, so there is no branch to guard: its
# checkout is read-only to the session instead, set up before the launch.
guard = friction.find("review_guard_settings")
first_claude = friction.find("claude_launch --")
check("friction-guard-before-session", -1 < guard < first_claude, True)
check("friction-no-maintainers-net", "MAINTAINERS does not list you" in friction, False)

PROMPTS = os.path.join(LIB, "..", "prompts")
for name in ("_friction-body.md", "friction.md", "friction-fix.md"):
    text = open(os.path.join(PROMPTS, name), encoding="utf-8").read()
    check("prompt-names-no-main-target-%s" % name,
          [p for p in ("commit it to `main`", "commits straight to `main`")
           if p in text], [])

print("another sclaude is the command, not a word in a prompt")
FAKE_PS = r"""
ps() {
  case "$*" in
    *-eo*) cat <<'ROWS'
  100   100 01:00 claude --resume abc --model opus run the sclaude review and fix the findings
  200   200 02:00 script -q -c sclaude feat /tmp/rec
  201   201 02:00 /bin/bash /home/x/.local/bin/sclaude feat
  300   300 03:00 sclaude status
  400   400 04:00 vim notes-about-sclaude.md
ROWS
    ;;
    *-o\ sid=*) echo 1 ;;
    *) return 1 ;;
  esac
}
"""
done = subprocess.run(
    ["bash", "-c", "source %s/run.sh\n%s\ninstruments_others" % (LIB, FAKE_PS)],
    capture_output=True, text=True, env=ENV)
check("others-only-sclaude-commands", done.stdout.strip(),
      "pid 201: sclaude feat, up 02:00, pid 300: sclaude status, up 03:00")

if failures:
    print("\n%d failed: %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("\nall passed")
