#!/usr/bin/env python3
"""Night mode state for the /isleep skill, and the hooks that carry it.

The night lives in one machine-level file, so it reaches every session on the
machine and outlasts a compaction, a resume and a restart:

  $ISLEEP_STATE/night.json   (default ~/.local/state/isleep)
    started, until   ISO times; past `until` the night is over by itself
    log              the night's decision log, shared by every session
    before           logs of nights that ran out unsummarised before this
                     one began on another date: its summary covers them too
    all              every session takes part (the default); false with
                     `/isleep here`, and then only `sessions` do
    sessions         ids of the sessions that ran /isleep
    reminded         session id -> its claude pid, for those told it is on
    blocks           Stop nudges spent, per session

  $ISLEEP_STATE/over.json    after the night: the sessions it was announced to
    tell             session id -> pid, still to be told it is over (at their
                     next tool call), so that a reminder left in their
                     context does not go on deciding for the person; a
                     session whose process is gone is dropped from it
    until            when the list is dropped, told or not (OVER_HOURS)

  $ISLEEP_STATE/due.json     a night that ran out its hours: its log, for the
                     person's first prompt, whenever it comes, to be answered
                     with the summary. Only the prompt hook reads it.
  $ISLEEP_STATE/asleep.json  session id -> until: sessions told of a night
                     whose process was gone when it ended; one resumed later
                     is told it is over at its start. Only SessionStart
                     reads it.

The night ends at the person's first input in any session: a prompt typed
anywhere means they are back. What is not the person's is told apart — a
headless `claude -p`, the prompt sclaude launched a session with (on the
command line of a claude process that has SCLAUDE_SESSION — a prompt the
person gives `claude` on its command line counts as theirs), and a /loop
wakeup.
A /loop the person types is taken for a wakeup too: a wakeup repeats the
/loop input word for word, so the two cannot be told apart.

Hooks (registered globally by install.sh; with no night on, each does nothing):

  night.py hook prompt   UserPromptSubmit: `/isleep ...` starts the night,
                         `/isleep off` and any input of the person end it and
                         ask that session for the morning summary
  night.py hook start    SessionStart: the session is told the night is on —
                         a new one, and after a compaction or a resume; by
                         day, one closed during a night is told it ended
  night.py hook tool     PostToolUse: a session already running when the
                         night began is told, once, at its next tool call;
                         after the night, one it was told to is told it ended
  night.py hook ask      PreToolUse on AskUserQuestion: refused, with the
                         instruction to decide and log instead
  night.py hook stop     Stop: one nudge per turn to carry on if work is left
                         (not in a headless run: its last answer is its
                         output)

Commands, for the skill:

  night.py status        the night as JSON, or nothing
  night.py active        exits 0 while a night over every session is on — not
                         a `here` one: sclaude's [g] follows it under
                         `sleep_mode: auto` (review_go_on in
                         sclaude/lib/local_review.sh)
  night.py off           end the night
  night.py install FILE  register the hooks in a Claude settings file (install.sh)
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import sys
import tempfile
from pathlib import Path

HOURS = 12        # a night that nobody ends is over after this
STOP_NUDGES = 40  # Stop nudges per session per night: a bound on the cost
OVER_HOURS = 2    # how long sessions wait to be told the night is over
ASLEEP_DAYS = 7   # how long a closed session waits for its resume to be told
SKILL = "~/.claude/skills/isleep/SKILL.md"


def state_dir():
    return Path(os.environ.get("ISLEEP_STATE")
                or Path.home() / ".local/state/isleep")


def night_file():
    return state_dir() / "night.json"


def over_file():
    return state_dir() / "over.json"


def due_file():
    return state_dir() / "due.json"


def asleep_file():
    return state_dir() / "asleep.json"


def now():
    return dt.datetime.now().astimezone()


@contextlib.contextmanager
def locked():
    """Hooks of several sessions change the record at once: one at a time."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def past(record):
    try:
        return dt.datetime.fromisoformat(record["until"]) <= now()
    except (KeyError, ValueError, TypeError):
        return True


def load():
    """The night, or None. One past its hours is ended here, as if the
    person had written: its sessions are told, and the summary waits."""
    night = read(night_file())
    if night is None:
        return None
    if past(night):
        log = end_night(night=night)
        if log:
            save({"log": log}, due_file())
        return None
    return night


def save(night, path=None):
    fd, tmp = tempfile.mkstemp(dir=state_dir(), prefix=".night-")
    with os.fdopen(fd, "w") as f:
        json.dump(night, f, indent=1)
    os.replace(tmp, path or night_file())


def drop(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def alive(pid):
    return pid is None or Path(f"/proc/{pid}").exists()


def load_over():
    over = read(over_file())
    if over and not past(over):
        over["tell"] = {s: p for s, p in over.get("tell", {}).items() if alive(p)}
        if over["tell"]:
            return over
    drop(over_file())
    return None


def member(night, sid):
    return night.get("all", True) or sid in night.get("sessions", [])


def emit(event, **fields):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}))


def reminder(night):
    return (
        f"{ON_MARK} {night['until'][11:16]}: the person is asleep. Decide instead of "
        "asking, go on instead of stopping to ask whether to continue, and "
        "log each decision that mattered, as you take it, in "
        f"{night['log']} (shared by every session of the night; head each "
        "entry with the repository and the time). A push, merge, deploy, "
        "deletion, message to others or spending still waits for the person: "
        "leave it ready and log it under Waiting for you. The night ends "
        f"when the person writes in any session. The rules in full: {SKILL}.")


def morning(log, why):
    return (
        f"{why} {OVER_MARK}: the person is back. In this reply, give them "
        f"the morning summary of the night from {log}, as {SKILL} says under "
        "'The morning summary' — every session's sections, not only this "
        "one's — and answer their message, if it asks anything. The night "
        "ending does not end the work: do not stop for the summary — carry on "
        "with whatever you were doing in the same turn. Only questions change: "
        "they go to the person again from now on.")


def start_night(args, sid):
    # First: a night it finds run out writes its summary and its "over" list.
    # The summary waiting is folded into the new night's, which covers its log
    # too; the list stays: a session left out of a `here` night is still owed
    # the word.
    night = load()
    due = (read(due_file()) or {}).get("log")
    drop(due_file())
    t = now()
    if night is None:
        night = {
            "started": t.isoformat(timespec="minutes"),
            "log": str(state_dir() / f"{t.date().isoformat()}.md"),
            "before": [], "all": False, "sessions": [], "reminded": {}, "blocks": {},
        }
    if due and due != night["log"] and due not in night.setdefault("before", []):
        night["before"].append(due)
    # `here` only keeps a night it starts to one session: narrowing a night
    # others were already told of would leave them told, and unguarded.
    night["all"] = night["all"] or "here" not in args
    hours = HOURS
    for word in args:
        if word.endswith("h") and word[:-1].isdigit():
            hours = int(word[:-1])
    night["until"] = (t + dt.timedelta(hours=hours)).isoformat(timespec="minutes")
    if sid:
        if sid not in night["sessions"]:
            night["sessions"].append(sid)
        night["reminded"][sid] = claude_pid()
    save(night)


def end_night(sid=None, night=None):
    """Ends the night; returns its log, or None when there was none.

    The sessions it was announced to, but `sid` — the one the person wrote in,
    which is told by the prompt hook — and those whose process is gone, are
    left to be told it is over."""
    night = night or load()
    drop(night_file())
    if night is None:
        return None
    reminded = {s: p for s, p in night.get("reminded", {}).items() if s != sid}
    tell = {s: p for s, p in reminded.items() if alive(p)}
    if tell:
        until = now() + dt.timedelta(hours=OVER_HOURS)
        tell = {**(load_over() or {}).get("tell", {}), **tell}
        save({"tell": tell, "until": until.isoformat(timespec="minutes")},
             over_file())
    gone = [s for s in reminded if s not in tell]
    if gone:
        asleep = read(asleep_file()) or {}
        until = (now() + dt.timedelta(days=ASLEEP_DAYS)).isoformat(timespec="minutes")
        asleep.update({s: until for s in gone})
        save(asleep, asleep_file())
    return " and ".join(night.get("before", []) + [night["log"]])


ON_MARK = "Night mode (/isleep) is on until"
OVER_MARK = "Night mode (/isleep) is over"


def owed(sid, data=None):
    """Whether this session is still to be told the night is over; it is
    taken off every list that says so. Listed in over.json (alive), or in
    asleep.json (closed during the night); on a resume, also a conversation
    whose transcript has a night's reminder and no word of its end after it —
    a resumed conversation may come back under a new id."""
    found = False
    over = load_over()  # drops one past its hours or with nobody alive left
    if over and sid in over["tell"]:
        del over["tell"][sid]
        save(over, over_file()) if over["tell"] else drop(over_file())
        found = True
    asleep = read(asleep_file())
    if asleep and sid in asleep:
        found = found or not past({"until": asleep.pop(sid)})
        asleep = {s: u for s, u in asleep.items() if not past({"until": u})}
        save(asleep, asleep_file()) if asleep else drop(asleep_file())
    if not found and data and data.get("source") == "resume":
        try:
            text = Path(data.get("transcript_path") or "").read_bytes()
        except OSError:
            text = b""
        found = text.rfind(ON_MARK.encode()) > text.rfind(OVER_MARK.encode())
    return found


def argv_of(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return raw.decode(errors="replace").split("\0")


def claude_pid():
    """The claude process this hook runs under: CLAUDE_PID, else the nearest
    ancestor that is claude — by its name, or, run through node, its script."""
    env = os.environ.get("CLAUDE_PID", "")
    if env.isdigit():
        return int(env)
    p = os.getppid()
    for _ in range(8):
        try:
            comm = Path(f"/proc/{p}/comm").read_text().strip()
            if comm == "claude" or any(
                    os.path.basename(a) in ("claude", "cli.js") for a in argv_of(p)[:2]):
                return p
            p = int(Path(f"/proc/{p}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return None
    return None


def headless(argv):
    return "-p" in argv or "--print" in argv


def from_person(prompt):
    """False for a prompt that is not the person typing (see the head)."""
    if prompt.startswith(("<<autonomous-loop", "/loop")):
        return False
    pid = claude_pid()
    argv = argv_of(pid) if pid else []
    if headless(argv):
        return False
    return not (os.environ.get("SCLAUDE_SESSION")
                and any(a.strip() == prompt for a in argv[1:]))


def hook(kind):
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    sid = data.get("session_id", "")
    with locked():
        hook_locked(kind, data, sid)


def hook_locked(kind, data, sid):
    if kind == "prompt":
        prompt = (data.get("prompt") or "").strip()
        words = prompt.split()
        if words[:1] == ["/isleep"]:
            if words[1:2] == ["off"]:
                log = end_night(sid) or (read(due_file()) or {}).get("log")
                drop(due_file())
                if owed(sid) or log:
                    emit("UserPromptSubmit", additionalContext=morning(
                        log, "The person ended the night with /isleep off.")
                        if log else OVER)
            elif words[1:2] != ["report"]:
                start_night(words[1:], sid)
            return
        night = load()
        if not from_person(prompt):
            return
        was_owed = owed(sid)
        if night is not None:
            log = end_night(sid)
            emit("UserPromptSubmit", additionalContext=morning(
                log, "The person has just written, in this session."))
            return
        due = read(due_file())
        if due:
            drop(due_file())
            emit("UserPromptSubmit", additionalContext=morning(
                due["log"], "The night ran out its hours before the "
                "person came back, and they have just written."))
        elif was_owed:
            emit("UserPromptSubmit", additionalContext=OVER)
        return

    night = load()
    if night is None or not member(night, sid):
        # A session outside a `here` night may still owe the word of the last.
        if kind in ("start", "tool") and owed(sid, data):
            emit("SessionStart" if kind == "start" else "PostToolUse",
                 additionalContext=OVER)
        return

    if kind in ("start", "tool"):
        if kind == "tool" and sid in night["reminded"]:
            return
        night["reminded"][sid] = claude_pid()
        save(night)
        emit("SessionStart" if kind == "start" else "PostToolUse",
             additionalContext=reminder(night))
        return

    if kind == "ask":
        emit("PreToolUse", permissionDecision="deny", permissionDecisionReason=(
            "Night mode (/isleep): the person is asleep and nobody will "
            "answer. Take the option you would recommend — or, with no clear "
            "favourite, the one easiest to undo — log it in "
            f"{night['log']}, and go on."))
        return

    if kind == "stop":
        # One nudge per turn: the turn the nudge itself caused may end freely.
        if data.get("stop_hook_active") or headless(argv_of(claude_pid())):
            return
        spent = night["blocks"].get(sid, 0)
        if spent >= STOP_NUDGES:
            return
        night["blocks"][sid] = spent + 1
        save(night)
        print(json.dumps({"decision": "block", "reason": (
            "Night mode (/isleep): before you stop — is anything of the task "
            "left that does not wait for the person? If so, carry on with it "
            "(wait for long jobs with Monitor or a background command, not by "
            "ending the turn). If the work is done or only waits for the person, make "
            f"sure {night['log']} says so, and stop.")}))


OVER = (
    f"{OVER_MARK}: the person is back. The night's "
    "reminder earlier in this conversation no longer holds — questions "
    "go to the person again, with AskUserQuestion as usual. Give no "
    "morning summary here; the session they wrote in gives it.")


# event: (matcher, kind, runs by day). The prompt hook runs with no night on —
# it starts one, and gives the summary of one that ran out — and so does
# SessionStart, rare enough, for a session closed during a night; the rest
# stop at a test of the file, so a day costs every tool call nothing but that.
HOOKS = {
    "UserPromptSubmit": (None, "prompt", True),
    "SessionStart": (None, "start", True),
    "PostToolUse": (None, "tool", False),
    "PreToolUse": ("AskUserQuestion", "ask", False),
    "Stop": (None, "stop", False),
}


def install(path):
    """Add the hooks to a settings file, once; other hooks are left alone."""
    path = Path(path)
    try:
        settings = json.loads(path.read_text())
    except FileNotFoundError:
        settings = {}
    except ValueError as e:
        sys.exit(f"{path} is not valid JSON ({e}); the /isleep hooks were not added")
    me = "~/.claude/skills/isleep/night.py"
    state = "${ISLEEP_STATE:-$HOME/.local/state/isleep}"
    guard = f'[ -e "{state}/night.json" ] || [ -e "{state}/over.json" ] || exit 0; '
    hooks = settings.setdefault("hooks", {})
    for event, (matcher, kind, by_day) in HOOKS.items():
        groups = hooks.setdefault(event, [])
        command = ("" if by_day else guard) + f"python3 {me} hook {kind}"
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if me not in h.get("command", "")]
        groups[:] = [g for g in groups if g["hooks"]]
        group = {"hooks": [{"type": "command", "command": command, "timeout": 10}]}
        if matcher:
            group["matcher"] = matcher
        groups.append(group)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-")
    with os.fdopen(fd, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main(argv):
    if argv[:1] == ["hook"] and len(argv) == 2:
        hook(argv[1])
    elif argv == ["status"]:
        with locked():
            night = load()
        if night:
            print(json.dumps(night, indent=1))
    elif argv == ["active"]:
        # Asked several times a review round: no night, no lock, nothing made.
        if not night_file().exists():
            sys.exit(1)
        with locked():
            night = load()
            sys.exit(0 if night and night.get("all") else 1)
    elif argv == ["off"]:
        with locked():
            end_night(os.environ.get("CLAUDE_CODE_SESSION_ID"))
    elif argv[:1] == ["install"] and len(argv) == 2:
        install(argv[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
