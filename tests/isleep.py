#!/usr/bin/env python3
#
# /isleep's night: the record in night.json and the hooks that read it.
#
# Every session on the machine runs these hooks, so the cheap ways to be wrong
# are a hook that acts with no night on — refusing a question, or keeping a
# session from ending, by day — and a night that a prompt not typed by the
# person ends: sclaude's launch prompt, a headless run, a /loop wakeup. The
# other way is a night that does not reach a session: a compacted one, a new
# one, or one already running when it began.
#
# Run it with: python3 tests/isleep.py
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
NIGHT = os.path.join(ROOT, "skills", "isleep", "night.py")

failures = []


def check(name, cond):
    if not cond:
        failures.append(name)
        print(f"FAIL {name}")


# Stand-ins for claude processes: the hook reads their command line.
person = subprocess.Popen(["sleep", "300"])
headless = subprocess.Popen(["bash", "-c", "sleep 300; :", "-p"])
LAUNCH = "Step 2: write the code"
launched = subprocess.Popen(["bash", "-c", "sleep 300; :", "claude", LAUNCH])


def run(state, *args, data=None, pid=None, env=None):
    e = {k: v for k, v in os.environ.items() if k != "SCLAUDE_SESSION"}
    e.update(ISLEEP_STATE=state, CLAUDE_PID=str(pid or person.pid), **(env or {}))
    p = subprocess.run([sys.executable, NIGHT, *args], env=e, text=True,
                       input=json.dumps(data) if data is not None else "",
                       capture_output=True)
    check(f"{args} exits 0: {p.stderr}", p.returncode == 0)
    return json.loads(p.stdout) if p.stdout.strip() else None


def hook(state, kind, sid, pid=None, env=None, **data):
    return run(state, "hook", kind, data={"session_id": sid, **data}, pid=pid, env=env)


SCLAUDE = {"SCLAUDE_SESSION": "feat-x"}


def context(out):
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


def on(state):
    return run(state, "status") is not None


try:
    with tempfile.TemporaryDirectory() as state:
        # By day every hook is silent, and a prompt starts nothing.
        for kind in ("start", "tool", "ask", "stop"):
            check(f"day: {kind} silent", hook(state, kind, "a") is None)
        check("day: a prompt is silent", hook(state, "prompt", "a", prompt="hi") is None)
        check("day: no night", not on(state))

        # /isleep starts it, for every session by default.
        check("/isleep itself injects nothing",
              hook(state, "prompt", "a", prompt="/isleep 8h finish the review") is None)
        night = run(state, "status")
        check("night recorded for all", night and night["all"] and night["sessions"] == ["a"])
        active = lambda: subprocess.run([sys.executable, NIGHT, "active"],
                                        env=dict(os.environ, ISLEEP_STATE=state)).returncode
        check("active: 0 while the night is on", active() == 0)
        check("log is the evening's file", night and night["log"].startswith(state))

        check("own session: AskUserQuestion refused",
              (hook(state, "ask", "a") or {}).get("hookSpecificOutput", {})
              .get("permissionDecision") == "deny")
        check("compaction brings the night back",
              "Night mode" in context(hook(state, "start", "a", source="compact")))
        check("stop nudged once", (hook(state, "stop", "a") or {}).get("decision") == "block")
        check("the nudged turn may end",
              hook(state, "stop", "a", stop_hook_active=True) is None)

        # A session that was already running is told once, at a tool call.
        check("running session told at its next tool",
              "Night mode" in context(hook(state, "tool", "b")))
        check("...once", hook(state, "tool", "b") is None)
        check("the session that ran /isleep is not told again", hook(state, "tool", "a") is None)
        check("a new session is told", "Night mode" in context(hook(state, "start", "c")))
        check("other session: ask refused too", hook(state, "ask", "b") is not None)

        # Prompts that are not the person keep the night.
        hook(state, "prompt", "d", pid=headless.pid, prompt="review this diff")
        check("headless claude -p does not end it", on(state))
        check("a headless run is not nudged at its stop: its answer is its output",
              hook(state, "stop", "d", pid=headless.pid) is None)
        hook(state, "prompt", "e", pid=launched.pid, env=SCLAUDE, prompt=LAUNCH)
        check("the prompt sclaude launched a session with does not end it", on(state))
        hook(state, "prompt", "c", prompt="<<autonomous-loop-dynamic>>")
        check("a loop wakeup does not end it", on(state))
        check("/isleep report keeps it",
              hook(state, "prompt", "a", prompt="/isleep report") is None and on(state))

        # The bound on nudges.
        spent = 0
        while hook(state, "stop", "c") is not None and spent < 100:
            spent += 1
        check(f"stop nudges bounded ({spent})", 0 < spent < 100)

        # A session whose process is gone is not left waiting to be told.
        gone = subprocess.Popen(["sleep", "300"])
        hook(state, "tool", "w", pid=gone.pid)
        gone.kill()
        gone.wait()

        # The person typing in a launched session, past its launch prompt, ends it.
        out = hook(state, "prompt", "e", pid=launched.pid, env=SCLAUDE,
                   prompt="why did you pick that?")
        check("the person in a sclaude session ends it", not on(state))
        check("...and is given the morning summary", "morning summary" in context(out))
        check("...and told to carry on, not stop", "carry on" in context(out))
        check("off: ask allowed again", hook(state, "ask", "a") is None)
        over = json.load(open(os.path.join(state, "over.json")))
        check("a session whose process is gone is not kept to be told", "w" not in over["tell"])

        # Sessions the night was announced to are told it is over, once, and
        # the one the person wrote in is not (it was given the summary).
        out = hook(state, "tool", "b")
        check("a told session learns the night is over", "is over" in context(out))
        check("...once", hook(state, "tool", "b") is None)
        check("...at a resume too", "is over" in context(hook(state, "start", "c")))
        check("the session written in is not told again", hook(state, "tool", "e") is None)
        check("a session never told is not told", hook(state, "tool", "q") is None)

        # A session closed during the night is told at its resume, by day.
        check("a closed session is told at its resume",
              "is over" in context(hook(state, "start", "w", source="resume")))
        check("...once", hook(state, "start", "w", source="resume") is None)

        # The person giving claude a prompt on its command line is the person.
        hook(state, "prompt", "a", prompt="/isleep")
        hook(state, "prompt", "n", pid=launched.pid, prompt=LAUNCH)
        check("a prompt the person launched claude with ends it", not on(state))

        # Any input in any session — one that never took part too.
        hook(state, "prompt", "a", prompt="/isleep")
        out = hook(state, "prompt", "z", prompt="good morning")
        check("input in another session ends it", not on(state))
        check("...with the night's log named", night["log"] in context(out))

        # A new night drops what was left to tell of the old one.
        hook(state, "prompt", "a", prompt="/isleep")
        hook(state, "tool", "y")
        hook(state, "prompt", "a", prompt="morning")
        hook(state, "prompt", "a", prompt="/isleep")
        check("a new night is not announced as over",
              "is over" not in context(hook(state, "tool", "y")))
        run(state, "off")
        hook(state, "tool", "y")

        # /isleep off ends it with the summary asked for.
        hook(state, "prompt", "a", prompt="/isleep")
        out = hook(state, "prompt", "a", prompt="/isleep off")
        check("/isleep off ends it", not on(state) and "morning summary" in context(out))

        # `here` keeps the night to the session that asked.
        hook(state, "prompt", "a", prompt="/isleep here")
        check("here: other session untouched", hook(state, "ask", "b") is None)
        check("here: own session refused", hook(state, "ask", "a") is not None)
        check("here: not active for sclaude's [g]", active() == 1)
        hook(state, "prompt", "b", prompt="/isleep")
        check("a plain /isleep widens it to all", hook(state, "ask", "c") is not None)
        hook(state, "prompt", "b", prompt="/isleep here")
        check("here does not narrow a night all were told of",
              hook(state, "ask", "c") is not None)
        run(state, "off")
        check("night.py off", not on(state))
        check("active: 1 by day", active() == 1)
        fresh = os.path.join(state, "never-used")
        rc = subprocess.run([sys.executable, NIGHT, "active"],
                            env=dict(os.environ, ISLEEP_STATE=fresh)).returncode
        check("active where /isleep never ran: 1, and makes nothing",
              rc == 1 and not os.path.exists(fresh))

        # A night past its hours is over by itself.
        hook(state, "prompt", "a", prompt="/isleep")
        path = os.path.join(state, "night.json")
        night = json.load(open(path))
        night["until"] = "2000-01-01T00:00+00:00"
        json.dump(night, open(path, "w"))
        check("expired: ask allowed", hook(state, "ask", "a") is None)
        check("expired: night.json gone, so the day guard holds again",
              not os.path.exists(path))
        check("expired: its sessions are told it is over",
              "is over" in context(hook(state, "tool", "a")))
        out = hook(state, "prompt", "z", prompt="morning")
        check("expired: the first prompt after it gets the summary",
              "morning summary" in context(out) and "ran out" in context(out))
        check("expired: the session written in is not told 'no summary'",
              hook(state, "tool", "z") is None)
        check("...once", hook(state, "prompt", "z", prompt="and?") is None)
        hook(state, "prompt", "a", prompt="/isleep")
        night = json.load(open(path))
        night["until"] = "2000-01-01T00:00+00:00"
        json.dump(night, open(path, "w"))
        check("expired, then /isleep off: the summary still",
              "morning summary" in context(hook(state, "prompt", "a", prompt="/isleep off")))
        check("...and that session is not told 'no summary'", hook(state, "tool", "a") is None)

        # A run-out night found by a new /isleep leaves nothing of itself.
        hook(state, "prompt", "a", prompt="/isleep")
        hook(state, "tool", "k")
        night = json.load(open(path))
        night["until"] = "2000-01-01T00:00+00:00"
        json.dump(night, open(path, "w"))
        hook(state, "prompt", "a", prompt="/isleep")
        check("a new night over a run-out one: no old summary waits",
              not os.path.exists(os.path.join(state, "due.json")))
        check("...and no old 'over' is told", "is over" not in context(hook(state, "tool", "k")))
        run(state, "off")

        # A session owed the word that the person writes in first gets it then.
        hook(state, "prompt", "a", prompt="/isleep")
        hook(state, "tool", "B")
        hook(state, "prompt", "a", prompt="morning")
        check("an owed session written in is told with the prompt",
              "is over" in context(hook(state, "prompt", "B", prompt="hi")))
        check("...once", hook(state, "tool", "B") is None)

        # An "over" list past its hours is dropped at the first hook that
        # looks, so the day guard holds again.
        hook(state, "prompt", "a", prompt="/isleep")
        hook(state, "tool", "S")
        hook(state, "prompt", "a", prompt="morning")
        over_path = os.path.join(state, "over.json")
        over = json.load(open(over_path))
        over["until"] = "2000-01-01T00:00+00:00"
        json.dump(over, open(over_path, "w"))
        check("a stale over list tells nobody", hook(state, "tool", "Q") is None)
        check("...and is gone", not os.path.exists(over_path))

        # A conversation resumed under a new id is told by its transcript.
        tr = os.path.join(state, "t.jsonl")
        open(tr, "w").write('{"x": "Night mode (/isleep) is on until 07:00: ..."}\n')
        check("a resume whose transcript holds a night's reminder is told",
              "is over" in context(hook(state, "start", "K2", source="resume",
                                        transcript_path=tr)))
        open(tr, "a").write('{"x": "Night mode (/isleep) is over: ..."}\n')
        check("...not when the transcript already says it ended",
              hook(state, "start", "K3", source="resume", transcript_path=tr) is None)

        # `/isleep here` over a run-out night keeps the old night's "over" list.
        hook(state, "prompt", "a", prompt="/isleep")
        hook(state, "tool", "H")
        night = json.load(open(path))
        night["until"] = "2000-01-01T00:00+00:00"
        json.dump(night, open(path, "w"))
        hook(state, "prompt", "a", prompt="/isleep here")
        check("a session left out of a here night is still told the old one ended",
              "is over" in context(hook(state, "tool", "H")))
        hook(state, "prompt", "a", prompt="morning")

        # A run-out night's summary is not lost to a new /isleep on another
        # date: the new night's summary covers its log too.
        due = os.path.join(state, "due.json")
        json.dump({"log": os.path.join(state, "1999-12-31.md")}, open(due, "w"))
        hook(state, "prompt", "a", prompt="/isleep")
        out = hook(state, "prompt", "a", prompt="morning")
        check("a new night's summary covers the run-out one before it",
              "1999-12-31.md and " in context(out))

        # The summary of a run-out night waits however long the person sleeps.
        hook(state, "prompt", "a", prompt="/isleep")
        night = json.load(open(path))
        night["until"] = "2000-01-01T00:00+00:00"
        json.dump(night, open(path, "w"))
        hook(state, "ask", "a")
        due = os.path.join(state, "due.json")
        json.dump({**json.load(open(due)), "until": "2000-01-01T00:00+00:00"}, open(due, "w"))
        check("a summary due days later is still given",
              "morning summary" in context(hook(state, "prompt", "z", prompt="hi")))

        # install adds each hook once and keeps what was there.
        settings = os.path.join(state, "settings.json")
        other = {"type": "command", "command": "echo mine"}
        json.dump({"hooks": {"Stop": [{"hooks": [other]}]}, "model": "x"},
                  open(settings, "w"))
        run(state, "install", settings)
        run(state, "install", settings)
        got = json.load(open(settings))
        check("install keeps other keys", got.get("model") == "x")
        check("install keeps other hooks", got["hooks"]["Stop"][0]["hooks"] == [other])
        mine = {}
        for event in ("UserPromptSubmit", "SessionStart", "PostToolUse", "PreToolUse", "Stop"):
            found = [g for g in got["hooks"][event]
                     if "isleep/night.py" in g["hooks"][0]["command"]]
            check(f"install: {event} once", len(found) == 1)
            mine[event] = found[0] if found else {}
        check("install: ask only on AskUserQuestion",
              mine["PreToolUse"].get("matcher") == "AskUserQuestion")

        # A hook the person put in the same group as ours stays.
        mine["Stop"]["hooks"].append(other)
        json.dump(got, open(settings, "w"))
        run(state, "install", settings)
        got = json.load(open(settings))
        stop = [h for g in got["hooks"]["Stop"] for h in g["hooks"]]
        check("install keeps a hook sharing our group", stop.count(other) == 2)
        check("...and ours once", sum("isleep/night.py" in h["command"] for h in stop) == 1)

        # A settings file that does not read is left alone, with a word.
        open(settings, "w").write("{ broken,")
        p = subprocess.run([sys.executable, NIGHT, "install", settings],
                           capture_output=True, text=True)
        check("install: bad JSON fails with a word",
              p.returncode != 0 and "not valid JSON" in p.stderr)
        check("install: bad JSON untouched", open(settings).read() == "{ broken,")

        # By day the guarded hooks stop at the file test, before python.
        for event in ("PostToolUse", "PreToolUse", "Stop"):
            cmd = mine[event]["hooks"][0]["command"].replace(
                "python3", "echo RAN")
            day = os.path.join(state, "day")
            p = subprocess.run(["bash", "-c", cmd], env=dict(os.environ, ISLEEP_STATE=day),
                               capture_output=True, text=True)
            check(f"{event}: by day nothing runs", p.returncode == 0 and "RAN" not in p.stdout)
            os.makedirs(day, exist_ok=True)
            open(os.path.join(day, "over.json"), "w").close()
            p = subprocess.run(["bash", "-c", cmd], env=dict(os.environ, ISLEEP_STATE=day),
                               capture_output=True, text=True)
            check(f"{event}: runs while sessions wait to be told", "RAN" in p.stdout)
            os.remove(os.path.join(day, "over.json"))
        for event in ("UserPromptSubmit", "SessionStart"):
            cmd = mine[event]["hooks"][0]["command"]
            check(f"{event} runs by day", "|| exit 0" not in cmd)
    # sclaude's [g] follows the night under sleep_mode: the real review_go_on,
    # project_sleep_mode and night.py active, end to end.
    with tempfile.TemporaryDirectory() as tmp:
        state, wt, repo = (os.path.join(tmp, d) for d in ("st", "wt", "repo"))
        os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
        os.makedirs(os.path.join(repo, ".sclaude"))
        feature = os.path.join(wt, ".sclaude/local/feature/state.json")
        lib = os.path.join(ROOT, "sclaude", "lib")
        script = (f'INSTRUMENTS="{ROOT}"; LIB="{lib}"; REPO="{repo}"; '
                  f'source "$LIB/state.sh"; source "$LIB/project.sh"; '
                  f'source "$LIB/local_review.sh"; review_go_on "{wt}"')

        def go_on(mode, box=None):
            json.dump({} if mode is None else {"sleep_mode": mode},
                      open(os.path.join(repo, ".sclaude/config.json"), "w"))
            json.dump({"step": "review", "steps": {"review": {"go_on": box}}}, open(feature, "w"))
            return subprocess.run(["bash", "-c", script], env=dict(os.environ, ISLEEP_STATE=state),
                                  capture_output=True).returncode == 0

        check("[g] by day under auto: off", not go_on(None))
        check("[g] by day under on: on", go_on("on"))
        hook(state, "prompt", "a", prompt="/isleep")
        check("[g] at night under auto: on", go_on("auto"))
        check("[g] at night under off: off", not go_on("off"))
        check("[g] taken off by hand stays off at night", not go_on("auto", box=False))
        run(state, "off")
        check("[g] ticked by hand stays on by day", go_on("auto", box=True))

finally:
    for proc in (person, headless, launched):
        proc.kill()

if failures:
    print(f"{len(failures)} failed")
    sys.exit(1)
print("isleep: ok")
