#!/usr/bin/env python3
#
# A test bench for an interrupted session: the friction review and the epilogue.
#
# A cycle's step survived interruption before too — its session's id lies in the
# state, and what closes a step is a trace in the world rather than a process
# that has ended. The two sessions outside STEPS did not survive:
#
#   * the friction review — the log is moved into .reviewed BEFORE the session,
#     and the id is recorded nowhere. Let it be interrupted by a limit and the
#     next attempt would find neither the log (empty) nor the conversation (the
#     id is unknown): the review would start afresh and pay for the same entries
#     a second time. Worse, after_step went on as though the review had taken
#     place — and the fix was late for exactly the step it was undertaken for.
#   * the epilogue — by its minute the feature's tree has been removed along with
#     state.json, and there is nowhere to write the state. An interruption was
#     lost silently: the feature is already done, and the menu will not show it.
#
# Both now write their state BEFORE launching: the review into
# .sclaude/local/feature/state.json next to steps, the epilogue into
# .sclaude/epilogue/<feature>.json in the main repository. The checks below hold
# three sides of each: an unclosed one is visible, a closed one is not, and an
# id's liveness is decided by the same live_session.
#
# claude is not called: the bench needs the state parsed rather than a session.
#
# Run it with: python3 tests/interrupted.py
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


def sh(script, **env):
    """Runs a piece of the orchestrator with state.sh sourced."""
    full = 'set -uo pipefail\nsource "%s/state.sh"\n%s' % (LIB, script)
    e = dict(os.environ)
    e.update(env)
    return subprocess.run(["bash", "-c", full],
                          capture_output=True, text=True, env=e).stdout


def write_state(wt, node, key="code"):
    """Writes a .sclaude/local/feature/state.json with a friction node (or without one).

    The node goes under its key — `friction.<step>` — because a review is kept
    per subject now. Pass key=None to write the node flat, the way an older
    sclaude did, and check that such a tree is still understood.
    """
    d = os.path.join(wt, ".sclaude/local/feature")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "state.json")
    data = {"feature": "71-email-edit-and-show", "step": "code",
            "steps": {"plan": {"done": True}, "code": {}}}
    if node is not None:
        data["friction"] = node if key is None else {key: node}
    with open(path, "w") as fh:
        json.dump(data, fh)
    return path


# The "is a review unfinished?" question, as every caller asks it. Five places
# used to test one key each; they ask friction_pending now, so the bench asks
# the same function rather than a copy of the condition — a copy is exactly how
# this bench went on passing while the code beneath it had moved on.
PENDING = r'''
  key="$(friction_pending "%s" || true)"
  printf '%%s' "${key:-none}"
'''


def main():
    home = tempfile.mkdtemp(prefix="sclaude-interrupted-")
    env_home = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        wt = os.path.join(home, "myapp-71-email-edit-and-show")
        sid = "86ea3d09-3f9f-43ef-ab6a-419b6b9f284f"

        # --- the friction review ------------------------------------------

        # One that was begun and not closed is what all this is for. It must be
        # visible even with an empty log: the log in that case is empty by
        # construction, having been moved into .reviewed before that very
        # session.
        st = write_state(wt, {"session": sid, "done": False})
        check("an unclosed review is visible", sh(PENDING % st), "code")

        # We do not start a closed one a second time: the entries have been
        # reviewed, and a repeat would cost exactly as much as the first
        # attempt.
        st = write_state(wt, {"session": sid, "done": True})
        check("a closed review is not visible", sh(PENDING % st), "none")

        # There was no review at all — the ordinary state of a feature whose
        # step passed without friction.
        st = write_state(wt, None)
        check("there was no review", sh(PENDING % st), "none")

        # The node is there but the id is not: writing it began and did not
        # finish. Such a thing must not count as an unclosed review — there is
        # nothing to return to.
        st = write_state(wt, {"done": False})
        check("a node without an id does not count", sh(PENDING % st), "none")

        # The review after step 3 no longer erases the one after step 2. That
        # overwrite is what the per-key shape exists to remove, and a bench for
        # interruption is where it belongs: the id it erased was the one an
        # interrupted review would have been resumed by.
        st = write_state(wt, {"session": sid, "done": True})
        sh('state_set "%s" "friction.pr.session" "bbbb"; '
           'state_set "%s" "friction.pr.done" false' % (st, st))
        check("a later review keeps the earlier one",
              sh('state_get "%s" friction.code.session' % st).strip(), sid)
        check("and the later one is the unfinished one", sh(PENDING % st), "pr")

        # A tree written by an older sclaude carries the flat shape. Losing its
        # unfinished review would strand a feature in flight, so it is still
        # understood — reported under the step from friction.after.
        st = write_state(wt, {"session": sid, "after": "code", "done": False},
                         key=None)
        check("the old flat shape is still understood", sh(PENDING % st), "code")

        # live_session decides an id's liveness, and a review's directory is not
        # a step's: it works in ~/instruments rather than in the feature's tree.
        # There is no transcript there — so there is nowhere to return to, and
        # the review will go as a new conversation.
        inst = os.path.join(home, "instruments")
        os.makedirs(inst, exist_ok=True)
        check("a review id with no transcript is dead",
              sh('live_session "%s" "%s" || printf dead' % (inst, sid)), "dead")

        d = sh('transcript_dir "%s"' % inst).strip()
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, sid + ".jsonl"), "w").close()
        check("a review id with a transcript is alive",
              sh('live_session "%s" "%s"' % (inst, sid)).strip(), sid)

        # --- the epilogue -------------------------------------------------

        # Its own storage is in the main repository: by this minute the feature's
        # tree is gone. The file is created by itself, as an empty object.
        repo = os.path.join(home, "myapp")
        os.makedirs(repo, exist_ok=True)
        path = sh('epilogue_state 71-email').strip()
        check("the epilogue's file is created", os.path.isfile(path), True)

        # Outside the repositories altogether. It has no place inside the
        # product's tree: steps work next to it where a `git add -A` is an
        # everyday thing, and an internal file with session ids would ride into
        # somebody else's commit.
        check("it is outside the feature's tree", path.startswith(repo), False)
        check("it is in the home directory",
              path.startswith(os.path.join(home, ".claude", "sclaude")), True)

        # An unclosed epilogue is found by the feature's name — the only way
        # back to it: a closed feature is not in the menu.
        sh('state_set "%s" session "%s"' % (path, sid))
        sh('state_set "%s" done false' % (path))
        rows = sh('pending_epilogues')
        check("an unclosed epilogue is in the list", rows.split("\t")[0], "71-email")

        # A closed one leaves the list.
        sh('state_set "%s" done true' % (path))
        check("a closed epilogue is not in the list",
              sh('pending_epilogues'), "")

        # An epilogue without an id — a state begun and not finished — is not
        # offered either: there is nothing to return to, as with a review.
        p2 = sh('epilogue_state 72-other').strip()
        sh('state_set "%s" done false' % (p2))
        check("an epilogue without an id is not in the list",
              sh('pending_epilogues'), "")

        # --- clearing a stuck review --------------------------------------
        #
        # A review holds the step, and there was no way out of it but editing
        # state.json by hand. Reset closes it — and closes it precisely rather
        # than erasing it: the entries have long been in .reviewed, and they must
        # not count as "unreviewed" any more, otherwise the next attempt would
        # offer them again.
        st = write_state(wt, {"session": sid, "done": False})
        sh('state_set "%s" "friction.code.done" true; '
           'state_set "%s" "friction.code.session" null' % (st, st))
        check("a cleared review does not hold the step", sh(PENDING % st), "none")
        check("a cleared review is marked reviewed",
              sh('state_get "%s" friction.code.done' % st).strip(), "true")

        # Which step the review was about needs no flag of its own any more: it
        # is the key. friction.after existed only because the slot was nameless,
        # and a tree written by this sclaude must not carry it — otherwise two
        # places would claim to say the same thing, and one of them would go
        # stale first.
        check("no after-flag is written any more",
              sh('state_get "%s" friction.code.after || printf absent' % st).strip(),
              "absent")

        # --- the interruption's age ---------------------------------------
        #
        # An interruption a minute ago and one last week are different news, and
        # are decided differently. So the offer to finish names the age rather
        # than the feature's name alone.
        check("age in minutes",
              sh('epilogue_age "$(date -d "-20 minutes" -Iseconds)"').strip(),
              "20m ago")
        check("age in hours",
              sh('epilogue_age "$(date -d "-3 hours" -Iseconds)"').strip(),
              "3h ago")
        check("age in days",
              sh('epilogue_age "$(date -d "-2 days" -Iseconds)"').strip(),
              "2d ago")

        # There is no time, or it will not parse — we say so outright rather
        # than inventing a number: a "0m ago" about an unknown moment would be a
        # lie.
        check("age unknown", sh('epilogue_age ""').strip(),
              "at an unknown time")
        check("age did not parse", sh('epilogue_age "not a time"').strip(),
              "at an unknown time")

        # --- clearing up after the epilogue -------------------------------
        #
        # The file's whole point is to survive an interruption. It has survived —
        # or was not needed — and there is no reason to keep it: nobody reads a
        # closed record, while it would accumulate a file per completed feature
        # for ever. Two callers do the clearing: run_status on success and
        # cmd_abandon.
        p3 = sh('epilogue_state 73-forget').strip()
        check("the file is created", os.path.isfile(p3), True)
        sh('epilogue_forget 73-forget')
        check("the file is removed", os.path.isfile(p3), False)

        # What is removed leaves the list — and the list stays an honest
        # "everything that lies in the directory", without filtering what has
        # accumulated.
        check("what was removed is not in the list",
              sh('pending_epilogues'), "")

        # Nothing to remove is not an error: the epilogue may have run without
        # state if the directory was not created. The end of a successful cycle
        # must not be brought down by that.
        check("removing something non-existent is not an error",
              sh('epilogue_forget 74-never-was; printf ok'), "ok")
        check("an empty name does not touch the directory",
              sh('epilogue_forget ""; printf ok'), "ok")

        # --- a closed review forgets its id -------------------------------
        #
        # An id left behind is poisonous the other way round: not dead but alive.
        # The next step's review reads the same field, the closed conversation's
        # transcript is in place, live_session says "alive" — and the return
        # branch would open the CLOSED review of the previous step instead of a
        # new one. Nobody would review the fresh entries.
        st = write_state(wt, {"session": sid, "done": False})
        sh('state_set "%s" "friction.code.done" true; '
           'state_set "%s" "friction.code.finished" x; '
           'state_set "%s" "friction.code.session" null' % (st, st, st))
        check("a closed review forgot its id",
              sh('state_get "%s" friction.code.session || printf empty' % st).strip(),
              "empty")

        # --- a broken state is repaired -----------------------------------
        #
        # Writing is not atomic: python truncates the file and writes it afresh.
        # An interruption at exactly that instant leaves an empty file, and from
        # then on it is dead — state_set dies parsing the JSON, the id is not
        # written, and the epilogue is unrecoverable again. That is precisely
        # what the file was created against.
        broken = os.path.join(sh('epilogue_dir').strip(), "75-broken.json")
        os.makedirs(os.path.dirname(broken), exist_ok=True)
        open(broken, "w").close()                    # empty, as after an interruption
        sh('epilogue_state 75-broken')
        check("an empty state is repaired", open(broken).read().strip(), "{}")

        open(broken, "w").write('{"session": "abc"')  # truncated JSON
        sh('epilogue_state 75-broken')
        check("a truncated state is repaired", open(broken).read().strip(), "{}")

        # We do not touch an intact one: the repair must not erase what
        # parses.
        sh('state_set "%s" session keep-me' % broken)
        sh('epilogue_state 75-broken')
        check("an intact state is untouched",
              sh('state_get "%s" session' % broken).strip(), "keep-me")
    finally:
        if env_home is not None:
            os.environ["HOME"] = env_home
        subprocess.run(["rm", "-rf", home])

    for name, want, got in failures:
        print("FAILED: %s\n  expected: %r\n  got:      %r" % (name, want, got))
    total = 33
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
