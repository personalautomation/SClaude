#!/usr/bin/env python3
#
# A test bench for a dead session id in a step's state.
#
# The id is written before claude is launched, and a launch does not always
# survive to a conversation. The state is then left with the id of a session that
# does not exist — and it is poison: the resume branch is chosen by a non-empty
# id, a `--resume` on it exits with "No conversation found with session ID", and
# the step never starts again. That is how feature 71-email-edit-and-show got
# stuck: step 2 could not begin for a day.
#
# The boundary here is the transcript file: every conversation that took place
# has one, and only those do. The checks below hold both sides: a dead id is
# forgotten, a live one is left untouched.
#
# claude is not called: the bench needs the state parsed rather than a session.
#
# Run it with: python3 tests/stale-session.py
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def guard(worktree, session, transcript_exists):
    """Runs the guard from run.sh itself and prints the id it left behind.

    live_session from state.sh decides it — one for all three places where a
    session is started: a step, the friction review, the epilogue. It is checked
    here in the same form run_step calls it in.

    We put the transcript in the directory transcript_dir names — that way the
    bench checks the path rule itself rather than only the branching.
    """
    state_dir = os.path.join(worktree, ".feature")
    os.makedirs(state_dir, exist_ok=True)
    state = os.path.join(state_dir, "state.json")
    with open(state, "w") as fh:
        json.dump({"steps": {"code": {"session": session}}}, fh)

    script = r'''
      set -euo pipefail
      source "%s/state.sh"
      info() { :; }
      wt="%s"; state="$wt/.feature/state.json"; step=code
      session="$(state_get "$state" "steps.$step.session" || true)"
      if [[ -n "$session" ]] && ! live_session "$wt" "$session" >/dev/null; then
        session=""
      fi
      printf '%%s' "$session"
    ''' % (LIB, worktree)

    if transcript_exists:
        d = subprocess.run(["bash", "-c",
                            'source "%s/state.sh"; transcript_dir "%s"'
                            % (LIB, worktree)],
                           capture_output=True, text=True).stdout.strip()
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, session + ".jsonl"), "w").close()

    return subprocess.run(["bash", "-c", script],
                          capture_output=True, text=True).stdout


def main():
    home = tempfile.mkdtemp(prefix="sclaude-stale-")
    env_home = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        wt = os.path.join(home, "myapp-71-email-edit-and-show")
        dead = "3e7f13e6-4f88-4eab-99d4-452e9b89e208"
        live = "86ea3d09-3f9f-43ef-ab6a-419b6b9f284f"

        # A session with no transcript never began — the id is forgotten, and an
        # empty one leads into the first-launch branch.
        check("a dead id is forgotten", guard(wt, dead, False), "")

        # A conversation that took place must not be touched: forgetting its id
        # means starting the step afresh over work already done.
        check("a live id is kept", guard(wt, live, True), live)

        # An empty state stays empty rather than turning into an error.
        check("an empty id passes", guard(wt, "", False), "")
    finally:
        if env_home is not None:
            os.environ["HOME"] = env_home
        subprocess.run(["rm", "-rf", home])

    for name, want, got in failures:
        print("FAILED: %s\n  expected: %r\n  got:      %r" % (name, want, got))
    total = 3
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
