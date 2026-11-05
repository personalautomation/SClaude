#!/usr/bin/env python3
#
# What the session keys in sclaude's tab leave behind for a step (session_keys
# in pane.sh), read after the session has closed:
#
#   * capture_plan takes the plan still on screen — an ExitPlanMode call with
#     no answer yet — only when the step's gate says [n] or [l] approved it;
#     a call the hook refused has its answer and is never taken, and an
#     approved call is taken as before;
#   * session_ctl_take hands over the word about the session's end once, and
#     not the ones that are no such word (restart, keep);
#   * the keys that need a watcher are offered only while its pid lives;
#   * session_ended: again, later ([R]) drops the marker, runs the friction
#     review and stops before the step's checks; forward ([n]) on a session
#     the watcher closed takes the plan on screen as approved, with the time
#     of the press, and goes on to the checks; a forward word on a session
#     no marker closed takes nothing;
#   * stop_asked stops once, and stands at the top of run_step and of
#     remind_prod.
#
# The keys themselves are run in tests/pane.py, the watcher's side of [n] and
# [k] in tests/review-round.py.
#
# Run it with: python3 tests/session-keys.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import benchlib  # noqa: E402 — shell functions found by name

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


tmp = tempfile.mkdtemp()
try:
    home = os.path.join(tmp, "home")
    wt = os.path.join(tmp, "wt")
    feature = os.path.join(wt, ".sclaude", "local", "feature")
    os.makedirs(feature)
    state = os.path.join(feature, "state.json")
    plan_md = os.path.join(feature, "plan.md")
    tdir = os.path.join(home, ".claude", "projects", re.sub(r"[^a-zA-Z0-9]", "-", wt))
    os.makedirs(tdir)
    session = "11111111-2222-3333-4444-555555555555"

    def presented(text):
        return {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "ExitPlanMode", "input": {"plan": text}}]}}

    def answered(text):
        return {"type": "user", "message": {"content": [
            {"type": "tool_result", "content": text}]}}

    def capture(entries, gate, taken_at=None):
        with open(os.path.join(tdir, session + ".jsonl"), "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        steps = {"plan": {"session": session}}
        if gate:
            steps["plan"]["gate"] = True
        if taken_at is not None:
            steps["plan"]["taken_at"] = taken_at
        with open(state, "w") as fh:
            json.dump({"steps": steps}, fh)
        if os.path.exists(plan_md):
            os.remove(plan_md)
        script = 'source "%s/core/state.sh"; source "%s/cycle/plan.sh"; LIB="%s"; capture_plan "%s"' % (
            LIB, LIB, LIB, wt)
        rc = subprocess.run(["bash", "-c", script], env=dict(os.environ, HOME=home),
                            capture_output=True, text=True).returncode
        text = None
        if os.path.exists(plan_md):
            with open(plan_md) as fh:
                text = fh.read()
        return rc, text

    # On screen, unanswered: not approved by itself...
    check("open-plan-without-word", capture([presented("A")], False), (1, None))
    # ...and approved by [n] or [l], which mark the gate.
    check("open-plan-taken-by-the-key", capture([presented("A")], True), (0, "A\n"))
    # The latest presented one is what is on screen.
    check("open-plan-latest", capture(
        [presented("A"), answered("User has approved your plan."), presented("B")], True),
        (0, "B\n"))
    # Refused by the hook: answered, so nothing is on screen to take.
    check("refused-plan-not-taken", capture(
        [presented("A"), answered("Error: the plan has no acceptance criteria")], True),
        (1, None))
    # Interrupted as the key closed it: an answer written after the press, in
    # the same second as the call, does not count.
    def at(entry, when):
        return dict(entry, timestamp=when)

    check("interrupted-after-the-press", capture(
        [at(presented("A"), "2026-11-02T12:00:07.100Z"),
         at(answered("The user doesn't want to proceed with this tool use."),
            "2026-11-02T12:00:07.900Z")],
        True, taken_at=1793620807.8), (0, "A\n"))
    check("refused-before-the-press", capture(
        [at(presented("A"), "2026-11-02T12:00:07.100Z"),
         at(answered("Error: no criteria"), "2026-11-02T12:00:07.200Z")],
        True, taken_at=1793620807.8), (1, None))

    # Approved in the dialog: as before, with or without the gate.
    check("approved-plan", capture(
        [presented("A"), answered("User has approved your plan.")], False), (0, "A\n"))

    # --- session_ctl_take ----------------------------------------------------
    def take(word):
        ctl = os.path.join(tmp, "sclaude-ctl-" + session)
        if word is not None:
            with open(ctl, "w") as fh:
                fh.write(word + "\n")
        script = 'source "%s/core/pane.sh"; session_ctl_take "%s"; echo "|"; session_ctl_take "%s"' % (
            LIB, session, session)
        out = subprocess.run(["bash", "-c", script], env=dict(os.environ, TMPDIR=tmp),
                             capture_output=True, text=True).stdout
        return out.strip(), os.path.exists(ctl)

    for word in ("next", "next-later", "later"):
        check("take-%s" % word, take(word), (word + "|", False))
    for word in ("restart", "keep"):
        check("take-not-%s" % word, take(word), ("|", False))
    check("take-nothing", take(None), ("|", False))

    # --- the watcher's mark names a live pid ---------------------------------
    def has(mark):
        path = os.path.join(tmp, "sclaude-watch-" + session)
        if mark is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "w") as fh:
                fh.write(mark + "\n")
        script = ('source "%s/core/pane.sh"; SESSION_KEYS_ID="%s"\n'
                  'for k in n N r R k; do session_key_has $k && printf %%s $k; done') % (LIB, session)
        p = subprocess.run(["bash", "-c", script], env=dict(os.environ, TMPDIR=tmp),
                           capture_output=True, text=True)
        # Asked every second: a missing mark says nothing on the terminal.
        if p.stderr:
            failures.append(("keys-quiet-" + str(mark), "", p.stderr))
        return p.stdout

    check("keys-with-a-live-watcher", has("plan %d" % os.getpid()), "nNrRk")
    check("keys-with-a-gone-watcher", has("plan 999999999"), "r")
    check("keys-with-no-watcher", has(None), "r")

    # --- session_ended's ways for the person's word --------------------------
    RUN = "".join(open(os.path.join(LIB, m), encoding="utf-8").read()
                  for m in ("cycle/run.sh", "cycle/session_watch.sh", "review/review_round.sh"))

    def functions(names):
        """The named shell functions, found by name in the whole library."""
        return benchlib.functions(names, missing=lambda name: failures.append(("function-present-" + name, True, False)))


    BODY = functions(["session_ended", "session_take_as_done", "session_closed",
                      "done_marker", "round_marker", "stop_file", "stop_asked"])
    log = os.path.join(tmp, "calls")

    def ended(step, said, marker, plan_ok=True):
        for f in (log,):
            if os.path.exists(f):
                os.remove(f)
        for name in ("session-done", "review-round"):
            path = os.path.join(feature, name)
            if os.path.exists(path):
                os.remove(path)
        if marker:
            with open(os.path.join(feature, "session-done"), "w") as fh:
                fh.write("closed from sclaude's terminal ([n])\n")
        with open(os.path.join(tmp, "sclaude-ctl-" + session), "w") as fh:
            fh.write(said + "\n")
        # Everything else is recorded: a command not found writes its words.
        script = ('source "%s/core/pane.sh"\n'
                  'command_not_found_handle() { echo "$*" >> "%s"; return 0; }\n'
                  'capture_plan() { echo "capture_plan" >> "%s"; return %d; }\n'
                  'SELF=sclaude\n%s\n'
                  'session_ended "%s" demo %s "%s"\n') % (
            LIB, log, log, 0 if plan_ok else 1, BODY, wt, step, session)
        out = subprocess.run(["bash", "-c", script], env=dict(os.environ, TMPDIR=tmp),
                             capture_output=True, text=True).stdout
        calls = []
        if os.path.exists(log):
            with open(log) as fh:
                calls = fh.read().splitlines()
        return out, calls

    out, calls = ended("code", "later", marker=True)
    check("R-drops-the-marker", os.path.exists(os.path.join(feature, "session-done")), False)
    check("R-runs-the-friction-review", any(c.startswith("run_friction ") for c in calls), True)
    check("R-stops-before-the-checks", any(c.startswith("after_step ") for c in calls), False)
    check("R-said", any("Closed at your word ([R])" in c for c in calls), True)
    check("R-takes-nothing-as-done",
          any("steps.code.gate true" in c for c in calls), False)

    out, calls = ended("plan", "next", marker=True)
    check("n-approves-the-plan", any(c.endswith("steps.plan.gate true") for c in calls), True)
    check("n-times-the-press",
          any(re.search(r"steps\.plan\.taken_at \d+(\.\d+)?$", c) for c in calls), True)
    check("n-reads-the-plan", "capture_plan" in calls, True)
    check("n-goes-on-to-the-checks", any(c.startswith("after_step ") for c in calls), True)

    out, calls = ended("plan", "next", marker=True, plan_ok=False)
    check("n-no-plan-takes-the-gate-back",
          [c.split()[-1] for c in calls if "steps.plan.gate" in c], ["true", "null"])

    out, calls = ended("plan", "next", marker=False)
    check("n-without-the-marker-takes-nothing",
          any("steps.plan.gate" in c for c in calls), False)

    # --- stop_asked ----------------------------------------------------------
    script = ('command_not_found_handle() { return 0; }\nSELF=sclaude\n%s\n'
              ': > "$(stop_file)"\n'
              'stop_asked "step x" demo && echo first\n'
              'stop_asked "step x" demo || echo second-no\n') % BODY
    out = subprocess.run(["bash", "-c", script], env=dict(os.environ, TMPDIR=tmp),
                         capture_output=True, text=True).stdout
    check("stop-once", ("first" in out, "second-no" in out), (True, True))
    run_step = re.search(r"^run_step\(\) \{\n(.*?)^\}\n", RUN, re.S | re.M).group(1)
    check("stop-at-run-step-top", "stop_asked" in run_step.split("\n  model=")[0], True)
    deploy = "".join(open(os.path.join(LIB, _m)).read()
        for _m in ("ship/deploy.sh", "ship/shipped.sh", "ship/vercel.sh", "ship/qa.sh", "ship/merge.sh", "ship/demo.sh"))
    remind = re.search(r"^remind_prod\(\) \{\n(.*?)\n\n", deploy, re.S | re.M)
    check("stop-at-remind-prod", bool(remind) and "stop_asked" in remind.group(1), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if failures:
    for name, want, got in failures:
        print("FAIL %s: want %r, got %r" % (name, want, got))
    sys.exit(1)
print("ok")
