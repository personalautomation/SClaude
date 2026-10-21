#!/usr/bin/env python3
#
# keepawake's state: reading, writing and the "should we hold it awake"
# decision.
#
# The module is shared by two writers — the detector (bin/keepawake, bash) and
# the telegram daemon. The detector is in bash, but it reads and writes JSON
# through this module rather than through sed/grep: there is no jq on the
# machine, and parsing JSON by hand in bash quietly corrupts the file. One
# module for two writers also guarantees that the flock and atomic-swap protocol
# is implemented once, rather than in two ways that will diverge one day.
#
# The state file lives on the Windows side (C:\Users\<user>\.keepawake) because
# PowerShell reads it, and it reads it at the very moment WSL may already have
# stopped. The other direction — reading from Windows over \\wsl$ — breaks
# exactly when it is needed.
#
# Time in the file is whole Unix-epoch UTC seconds only. Three runtimes (bash,
# python, powershell) give the same integer, and the now >= until comparison
# depends on neither the zone nor the switch to summer time. Local strings live
# in fields with the _local suffix and exist for the eye alone: nobody parses
# them.
#
#   python3 -m keepawake.state show            the whole file as JSON
#   python3 -m keepawake.state get <field>...  fields, one per line
#   python3 -m keepawake.state const <name>... thresholds, one per line
#   python3 -m keepawake.state extend <sec>    extend (max with the current)
#   python3 -m keepawake.state touch           heartbeat without extending
#   python3 -m keepawake.state holders k=1 s=2 record the holders
#   python3 -m keepawake.state decide sleep    the human's decision
import datetime
import errno
import fcntl
import json
import os
import sys
import time

VERSION = 1

# An hour of holding per live holder. Not cumulative: while even one is alive,
# the deadline is always "an hour from now". Accumulating would mean three short
# connections leave the laptop awake for three hours after all of them have
# closed.
HOLD_SECONDS = 3600

# Holders come in two kinds, and the difference between them is what they prove.
#
# Hard ones mean remote work: a live SSH session, an open terminal in
# code-server, traffic going through the tailnet. All three are ways of reaching
# the machine from a phone, and all three prove someone is at the other end
# right now. While such a holder exists, sleep does not come at all — the timer
# is not counted with them, and there is nothing to warn about: a sleeping
# laptop would cut the session off.
#
# Work at the laptop itself does not get in here and cannot: the Windows
# keyboard and screen are not visible from WSL. So "a person at the machine" is
# a wrong description of this class, tempting as it is: what is checked is not a
# person's presence but a live remote channel.
#
# Soft ones mean work is going on but there may be nobody around: a running
# claude, a started dev server. They give an hour, at the end of which a question
# arrives — and that is right, because a session left open would otherwise keep
# the laptop awake until morning.
#
# Which of them is alive is decided by the detector, and the rules there differ:
# a holder that proves only its own existence (the dev server, the code-server
# service) counts as alive only when there is someone alive at the machine. That
# difference is not visible here and must not be — already counted numbers
# arrive here.
#
# code-server is counted twice: "code" is a live session in the browser (hard),
# "codesrv" is just a running server with no tabs open (soft). The difference
# matters: the server lives for days on its own, while an open tab means a
# person.
HARD_HOLDERS = ("ssh", "code", "tailscale")
SOFT_HOLDERS = ("claude", "dev", "codesrv", "sclaude", "vscode")

# How long before the end we send the warning with buttons.
WARN_BEFORE = 1800

# How long the "Let it sleep" refusal lasts. Exactly the time in which Windows
# manages to fall asleep by its own idle timer: beyond that there is no reason
# to keep the refusal — either the laptop has slept or the person has come back
# to work, and new activity should extend the deadline again.
REFUSAL_HOLDS = 1200

# If the file has not been updated for this many seconds, we consider WSL dead
# and release the hold. The detector runs once a minute and updates updated_ts
# even when nothing has changed, so fifteen minutes of silence is a failure, not
# a lull. Without this threshold a crashed WSL would keep the laptop awake right
# up to until_ts, and with a corrupt entry for arbitrarily long.
STALE_AFTER = 900


def win_user():
    # The Windows user's name — to find the state directory on drive C.
    #
    # There are three sources, and the order matters. Under the systemd timer
    # PATH contains no Windows paths, and cmd.exe simply is not found there: the
    # detector died on every run even though it worked flawlessly from the
    # terminal. So first comes what depends on neither PATH nor interop at
    # all.
    env = os.environ.get("KEEPAWAKE_WIN_USER")
    if env:
        return env

    # The only profile in /mnt/c/Users apart from the service ones. Always
    # works while the drive is mounted, and costs nothing.
    try:
        skip = {"public", "default", "default user", "all users",
                "defaultaccount", "wdagutilityaccount"}
        names = [n for n in os.listdir("/mnt/c/Users")
                 if n.lower() not in skip
                 and os.path.isdir(os.path.join("/mnt/c/Users", n))]
        if len(names) == 1:
            return names[0]
    except OSError:
        names = []

    # There are several profiles — we ask Windows, by the full path to
    # cmd.exe, rather than hoping for PATH.
    import subprocess
    for exe in ("/mnt/c/Windows/System32/cmd.exe", "cmd.exe"):
        try:
            out = subprocess.run([exe, "/c", "echo %USERNAME%"],
                                 capture_output=True, text=True, timeout=10,
                                 cwd="/")
            name = out.stdout.strip().replace("\r", "")
            if name and "%" not in name:
                return name
        except Exception:
            continue

    # Several profiles and interop did not answer: we take the freshest by
    # modification time — that is almost certainly the one being worked in.
    if names:
        return max(names, key=lambda n: os.path.getmtime("/mnt/c/Users/" + n))
    return None


def is_wsl():
    # Which side holds the machine awake. Under WSL it is KeepAwake.ps1 on
    # Windows, reading the state from drive C; on a plain Linux machine it is
    # bin/keepawake-linux, reading it from the Linux filesystem. KEEPAWAKE_PLATFORM
    # is for the tests, which must be able to ask both questions on one machine.
    forced = os.environ.get("KEEPAWAKE_PLATFORM")
    if forced:
        return forced == "wsl"
    # The kernel alone is not enough: a Docker container on a WSL host runs the
    # same Microsoft kernel and has no Windows to hold. A Windows drive to write
    # the state to is what the WSL side actually needs.
    if not os.path.isdir("/mnt/c/Windows"):
        return False
    if os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"):
        return True
    try:
        with open("/proc/version") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def linux_state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "keepawake")


def state_path():
    # The override is for the tests: they must not touch the real file.
    env = os.environ.get("KEEPAWAKE_STATE")
    if env:
        return env
    if not is_wsl():
        # No Windows to read it from the other side: the holder is a process
        # on this machine, and the file lives beside the rest of our state.
        return os.path.join(linux_state_dir(), "state.json")
    user = win_user()
    if not user:
        raise RuntimeError("could not determine the Windows user's name")
    return "/mnt/c/Users/%s/.keepawake/state.json" % user


def hold_log_path():
    # The holder's own log, beside the state it reads: KeepAwake.ps1 writes
    # keepawake-ps.log on Windows, keepawake-linux writes hold.log. Both write
    # the same lines ("hold set", "hold released", "holding"), which is what
    # `keepawake status` greps for.
    env = os.environ.get("KEEPAWAKE_HOLD_LOG")
    if env:
        return env
    name = "keepawake-ps.log" if is_wsl() else "hold.log"
    return os.path.join(os.path.dirname(state_path()), name)


def lock_path():
    env = os.environ.get("KEEPAWAKE_LOCK")
    if env:
        return env
    # We keep the lock on the Linux filesystem rather than next to the state on
    # /mnt/c: locks on 9p/DrvFs are unreliable, and it is only needed between two
    # processes inside WSL. Windows does not take part in this race — it is a
    # reader only.
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "keepawake", ".lock")


def blank():
    return {
        "version": VERSION,
        "until_ts": 0,
        "until_local": "",
        "updated_ts": 0,
        "holders": {
            "claude": {"count": 0, "seen_ts": 0},
            "ssh": {"count": 0, "seen_ts": 0},
            "code": {"count": 0, "seen_ts": 0},
            "dev": {"count": 0, "seen_ts": 0},
            "codesrv": {"count": 0, "seen_ts": 0},
            "sclaude": {"count": 0, "seen_ts": 0},
            "vscode": {"count": 0, "seen_ts": 0},
            "tailscale": {"count": 0, "seen_ts": 0},
            "manual": {"until_ts": 0},
        },
        # Whether there is a hard holder right now. A separate field rather
        # than something derived from holders: PowerShell reads it, and it has
        # no reason to parse a nested object — it needs one answer, hold or
        # not.
        "hard_hold": False,
        "warned_for_ts": 0,
        "warn_message_id": 0,
        "decision": "",
        "decision_ts": 0,
        # The "report the restart" errand: the daemon kills itself, and only
        # the next process can say "I am back" — it has nowhere else to remember
        # that.
        "restart_notify": 0,
        "restart_from_pid": 0,
        # Which repository the sclaude status button shows. Empty or "*" means
        # all at once. The choice survives the daemon's restarts, hence it lives
        # here.
        "sclaude_repo": "",
        # The interlocutor's language, from Telegram. Stored because the sleep
        # warning goes out without an incoming update — there is nobody to ask
        # at that moment.
        "lang": "",
        # The language was chosen by the human in the settings rather than
        # taken from Telegram. The flag is needed because language_code arrives
        # in every update and without it would overwrite the choice on the very
        # first press — that is, the switch would work exactly until the next
        # button.
        "lang_pinned": False,
        # How many seconds nobody has typed anything, and whether the machine
        # is busy with something. The detector counts it — it has /proc and the
        # counters; the daemon reads.
        "idle_seconds": 0,
        "busy": 0,
        # When we last asked about forgotten hard holders.
        "idle_asked_ts": 0,
        # The message that asked it, so a moot question can be taken back.
        "idle_message_id": 0,
        # Since when a hard holder has been holding without a break — so the
        # question can honestly say "it has not slept for this long".
        "hard_since": 0,
        # What the bot expects from the next message. Empty means nothing,
        # "awake_until" means a time for "stay awake until". It lives in the
        # state rather than in the process's memory: the daemon is restarted by
        # a button in that same menu, and a question asked before the restart
        # would otherwise stay unanswered for ever.
        "awaiting": "",
        # The messages that ask for it: "menu" carries the "back" button,
        # "prompt" the input box. Both go once the wait ends.
        "awaiting_ids": {},
        # The topic the wait was asked in, 0 for the main chat: text typed in
        # another topic is not the time.
        "awaiting_thread": 0,
        # The menu screen each place holds — "0" the main chat, a topic's
        # thread id otherwise; a new one sent there replaces it.
        "screens": {},
        # Cards shown outside topics (Threaded Mode off): message id → feature
        # key, for buttons whose data had no room for it.
        "main_cards": {},
        # Until when a refusal to make a feature topic stands (Threaded Mode
        # off in @BotFather); topics are not asked for before then.
        "topics_off_until": 0,
        # The profile texts last set (Bot.describe): set again only when they
        # change.
        "described": "",
        # Messages about sleep that became answers, kept while true:
        # [[message id, expiry]] (telegramd.trail).
        "sleep_trail": [],
        # Which language the keyboard below the input box is set in. Empty
        # means it is not set at all. It cannot be set at every start: it only
        # arrives together with a message, and the daemon restarts both by
        # button and with the system — that would be noise in the chat on every
        # restart.
        "anchor_lang": "",
    }


def local_label(ts):
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M %d.%m")


def read(path=None):
    # We show the reader no errors here: any failure is blank(), that is
    # "nobody is holding". The fail-safe is the same for all readers, and the
    # should_hold decision below will reject an empty state anyway.
    path = path or state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return blank()
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return blank()
    base = blank()
    base.update(data)
    # holders may have arrived incomplete — we fill it in so that readers do
    # not have to check for every key.
    holders = blank()["holders"]
    holders.update(base.get("holders") or {})
    base["holders"] = holders
    return base


def write(data, path=None):
    # temp + rename only. state.json must never be opened for writing
    # directly: PowerShell will one day read half a file. The temporary name
    # contains the pid so that two writers do not fight over one temp.
    path = path or state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


class locked(object):
    # The whole read-modify-write under the lock: without it the daemon
    # overwrites an extension the detector wrote a second earlier.
    def __init__(self, path=None):
        self.path = path
        self.fh = None

    def __enter__(self):
        lock = lock_path()
        os.makedirs(os.path.dirname(lock), exist_ok=True)
        self.fh = open(lock, "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        self.data = read(self.path)
        return self.data

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            write(self.data, self.path)
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()
        return False


def should_hold(data, now):
    # The single function answering the question "should we hold it awake". Its
    # word-for-word twin lives in KeepAwake.ps1, and a divergence between them is
    # a laptop that sleeps at the wrong moment. The tests hold this table.
    if not data:
        return False
    if data.get("version") != VERSION:
        return False
    updated = data.get("updated_ts") or 0
    if not isinstance(updated, int):
        return False
    # A stale heartbeat cancels everything, hard holds included: a WSL that has
    # been silent for fifteen minutes cannot confirm anything, and its last word
    # must not keep the laptop awake for ever.
    if updated <= now - STALE_AFTER:
        return False
    # A hard holder does not look at the deadline at all: remote work is going
    # on, and there is no reason to put the machine to sleep under it — sleep
    # would cut the session off.
    if data.get("hard_hold"):
        return True
    until = data.get("until_ts") or 0
    if not isinstance(until, int):
        return False
    return until > now


def refuses(data, now):
    # The human pressed "Let it sleep" — the detector does not extend, but not
    # for ever.
    #
    # We count from the moment of the decision itself rather than from until_ts.
    # The window used to be counted from the deadline — and "Let it sleep" reset
    # until_ts to the current moment, because of which the window's start moved
    # into the past for good and the refusal became indefinite: one press of a
    # button and automatic extension never worked again, even with a live
    # session.
    if data.get("decision") != "sleep":
        return False
    return now - (data.get("decision_ts") or 0) < REFUSAL_HOLDS


def extend(data, now, seconds=HOLD_SECONDS, manual=False):
    # max() rather than assignment: a manual extension from Telegram must not
    # be shortened by the detector that arrives a minute later.
    target = now + seconds
    if target > (data.get("until_ts") or 0):
        data["until_ts"] = target
        data["until_local"] = local_label(target)
        # We mark the manual deadline separately from the general until_ts.
        # Without it status could not tell "an hour because claude is running"
        # from "three hours because the human asked for it": from the outside
        # both are simply a until_ts in the future, and the difference shows
        # only in a magnitude one would have to remember. It lasts exactly to
        # its own end and does not get in the automation's way: the "hold"
        # decision is still made by should_hold from until_ts.
        if manual:
            data.setdefault("holders", {})["manual"] = {"until_ts": target}
    return data


def drop_manual(data):
    # Forget the manual extension. Called by everyone who lowers until_ts to
    # "sleep now": the mark must not outlive lights-out.
    data.setdefault("holders", {})["manual"] = {"until_ts": 0}
    return data


def manual_until(data, now):
    # How long the manual extension still applies, 0 if there is none or it has
    # expired. The mark is not cleaned on a timer: comparing with now is
    # cheaper, and the cleaning would fall to someone who may well not be
    # running at that moment.
    until = ((data.get("holders") or {}).get("manual") or {}).get("until_ts") or 0
    if not isinstance(until, int) or until <= now:
        return 0
    # The manual deadline cannot outlive until_ts: "release the holds" from the
    # bot lowers the general deadline without touching the mark, and without
    # this check status would talk about an extension that no longer holds
    # anything.
    if until > (data.get("until_ts") or 0):
        return 0
    return until


def touch(data, now):
    data["updated_ts"] = now
    # We erase a stale decision. It belongs to its own holding cycle rather
    # than to the system in general: status showed "decision: sleep" a day after
    # the laptop had, by that decision, gone to sleep, woken up and started a
    # new day. Yesterday's press of a button is no answer to "why are we
    # holding".
    #
    # Each decision has its own lifetime, because they mean different things.
    # "Let it sleep" lives while the refusal to extend (refuses) applies; beyond
    # that it affects nothing. "Extend" lives while the deadline it asked for
    # runs: until holders.manual.until_ts, or without one until the general
    # until_ts.
    decision = data.get("decision")
    if decision == "sleep":
        expired = not refuses(data, now)
    elif decision:
        manual = (data.get("holders", {}).get("manual") or {}).get("until_ts")
        expired = now >= (manual or data.get("until_ts") or 0)
    else:
        expired = False
    if expired:
        data["decision"] = ""
        data["decision_ts"] = 0
    return data


def needs_warning(data, now):
    # With a hard holder there is nothing to warn about: sleep will not come
    # while it is there, and an "extend?" question would be pointless.
    if data.get("hard_hold"):
        return False
    # warned_for_ts holds the until_ts for which a warning has already been
    # sent. The mechanism is self-cleaning: extending changes until_ts, and the
    # next warning will come for the new deadline — there is no need to reset
    # the flag separately.
    until = data.get("until_ts") or 0
    if until <= now:
        return False
    if now < until - WARN_BEFORE:
        return False
    return data.get("warned_for_ts") != until


def _cli(argv):
    now = int(time.time())
    if not argv:
        print(json.dumps(read(), ensure_ascii=False, indent=2))
        return 0
    cmd = argv[0]
    if cmd == "show":
        print(json.dumps(read(), ensure_ascii=False, indent=2))
        return 0
    if cmd == "const":
        # The thresholds live here, and status in bash merely asks about them:
        # duplicating 900 in two languages means letting them diverge one
        # day.
        for name in argv[1:]:
            print(globals().get(name, ""))
        return 0
    if cmd == "get":
        # Fields are asked for in a batch: status reads fifteen or so, and
        # every call is a python3 launch and a read of a file from the Windows
        # drive.
        data = read()
        for key in argv[1:]:
            value = data
            for part in key.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            print("" if value is None else value)
        return 0
    if cmd == "hold":
        return 0 if should_hold(read(), now) else 1
    if cmd == "platform":
        print("wsl" if is_wsl() else "linux")
        return 0
    if cmd == "holdlog":
        print(hold_log_path())
        return 0
    if cmd == "touch":
        with locked() as data:
            touch(data, now)
        return 0
    if cmd == "extend":
        seconds = int(argv[1]) if len(argv) > 1 else HOLD_SECONDS
        with locked() as data:
            extend(data, now, seconds, manual=True)
            touch(data, now)
            # A manual extension lifts the previous refusal: the human has
            # changed their mind.
            data["decision"] = ""
            data["decision_ts"] = 0
        return 0
    if cmd == "release":
        with locked() as data:
            data["until_ts"] = now
            data["until_local"] = local_label(now)
            data["decision"] = "sleep"
            data["decision_ts"] = now
            # We drop the manual mark too: otherwise status would go on
            # talking about an extension the human has just taken away from
            # themselves.
            drop_manual(data)
            touch(data, now)
        return 0
    if cmd == "set":
        # Write a single top-level field. Needed by the detector: it counts
        # idling and busyness, while the daemon only reads them.
        key, raw = argv[1], argv[2]
        try:
            value = int(raw)
        except ValueError:
            value = raw
        with locked() as data:
            data[key] = value
        return 0
    if cmd == "decide":
        with locked() as data:
            data["decision"] = argv[1]
            data["decision_ts"] = now
            touch(data, now)
        return 0
    if cmd == "holders":
        # holders claude=1 ssh=2 code=0 — records the counters and extends if
        # anyone at all is alive and the human has not refused.
        counts = {}
        for arg in argv[1:]:
            name, _, value = arg.partition("=")
            counts[name] = int(value or 0)
        with locked() as data:
            hard = soft = 0
            for name, count in counts.items():
                slot = data["holders"].setdefault(name, {"count": 0, "seen_ts": 0})
                slot["count"] = count
                if count:
                    slot["seen_ts"] = now
                if name in HARD_HOLDERS:
                    hard += count
                elif name in SOFT_HOLDERS:
                    soft += count
            # The human's refusal suppresses a hard hold too: they pressed
            # "sleep" with a live SSH session, knowing about it — and the hold
            # they have just released must not come back by itself a minute
            # later.
            refused = refuses(data, now)
            data["hard_hold"] = bool(hard) and not refused
            # Soft holders move the deadline; hard ones move it too, so that
            # after they leave the usual hour remains rather than instant
            # sleep.
            if (hard or soft) and not refused:
                extend(data, now)
            touch(data, now)
            # The start of an uninterrupted hold — of any kind, not only a
            # hard one. It used to be counted by hard_hold, and the mark reset
            # the moment hard holders disappeared even for a minute: a flickering
            # tailscale reset the count every few minutes, and the question about
            # a forgotten session reported "it has not slept for 53 min" about a
            # machine that had been awake since the night. Whether anything is
            # holding right now is known by should_hold — the same function
            # decides it for Windows too, so the mark matches reality.
            if should_hold(data, now):
                data.setdefault("hard_since", 0)
                if not data["hard_since"]:
                    data["hard_since"] = now
            else:
                data["hard_since"] = 0
            print(data["until_ts"])
        return 0
    sys.stderr.write("keepawake.state: unknown command %s\n" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
