#!/usr/bin/env python3
#
# The review's keys on the phone. While a review pass runs, the terminal
# takes [s] (the last pass for new findings, again to take it back) and
# [x x] (stop the pass now); the topic's message that the pass started gets
# the same as buttons, and so does the message that a fix session started —
# whose [s] means that no new search follows it, only a check of its fixes.
#
# A press writes its word into the feature's channel (SAID_FILE), where
# review_said_take in sclaude/lib/local_review.sh takes it. The buttons go
# once the topic hears the next phase line — the pass or session ended, or
# another began — so they do not pile up on old messages.
#
# A module of its own, as notices.py, which is handed it (check's keys): the
# bot's file is long.
import json
import os
import re

from keepawake.i18n import t
from keepawake.notices import OWN_ICON

# Named on sclaude's side too: REVIEW_SAID_FILE in sclaude/lib/local_review.sh.
SAID_FILE = "review-said"
# Which message carries the buttons now, in the channel's notes/: one at a
# time, since a feature runs one review phase at a time.
BUTTONS_FILE = "review-buttons.json"

# The start lines phase_words in sclaude/lib/steps.sh prints, as notices.py
# reads them: a pass that searches (not one that checks the fixes only, which
# takes no keys) and a fix session of the review step.
PASS_START = re.compile(r"^🔍 Local review (?:started|resumed): PR #\S+, round \d+$")
SESSION_START = re.compile(r"^🛠 Step \d+/\d+ [^:]+: fix session \d+(?:, round \d+)? (?:started|resumed)\b")


def kind_of(lines):
    """What a group of feed lines leaves running: ("pass" | "session", pid)
    when its last phase line starts one, ("", "") otherwise."""
    kind, pid = "", ""
    for _level, line_pid, text, *_ in lines:
        text = (text or "").strip()
        if not OWN_ICON.match(text):
            continue
        if PASS_START.match(text):
            kind, pid = "pass", line_pid
        elif SESSION_START.match(text):
            kind, pid = "session", line_pid
        else:
            kind, pid = "", ""
    return kind, pid


def has_phase(lines):
    return any(OWN_ICON.match((text or "").strip()) for _l, _p, text, *_ in lines)


def keyboard(kind, said="", confirm=False):
    if confirm:
        return [[{"text": t("rv.stop.yes"), "callback_data": "rv:now"}],
                [{"text": t("rv.stop.no"), "callback_data": "rv:carry"}]]
    if kind == "pass":
        first = ({"text": t("rv.back"), "callback_data": "rv:back"} if said == "pass"
                 else {"text": t("rv.last.pass"), "callback_data": "rv:pass"})
        return [[first], [{"text": t("rv.stop"), "callback_data": "rv:stop"}]]
    if said == "pass":
        return [[{"text": t("rv.back"), "callback_data": "rv:back"}]]
    return [[{"text": t("rv.last.round"), "callback_data": "rv:pass"}]]


def _path(channel):
    return os.path.join(channel, "notes", BUTTONS_FILE)


def load(channel):
    try:
        with open(_path(channel), encoding="utf-8") as fh:
            rec = json.load(fh)
        return rec if isinstance(rec, dict) and rec.get("message_id") else {}
    except (OSError, ValueError):
        return {}


def save(channel, rec):
    path = _path(channel)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".new", "w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        os.replace(path + ".new", path)
    except OSError:
        pass


def drop(bot, channel):
    """The buttons off the message that carries them, if any."""
    rec = load(channel)
    if not rec:
        return
    bot.unbutton(rec["message_id"])
    try:
        os.remove(_path(channel))
    except OSError:
        pass


def sent(channel, lines, message_id):
    """Record the message just sent for lines as the one with the buttons."""
    kind, pid = kind_of(lines)
    if kind and message_id:
        save(channel, {"message_id": message_id, "kind": kind, "pid": pid, "said": ""})


def buttons_for(lines):
    """The keyboard a group's message goes with, None for none."""
    kind, _pid = kind_of(lines)
    return keyboard(kind) if kind else None


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, TypeError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def say(channel, word):
    """The word for sclaude, whole or not at all."""
    path = os.path.join(channel, SAID_FILE)
    try:
        with open(path + ".new", "w", encoding="utf-8") as fh:
            fh.write(word)
        os.replace(path + ".new", path)
        return True
    except OSError:
        return False


def press(bot, channels, message_id, data, is_alive=alive):
    """A press on a review button: the toast to answer it with. channels:
    the features' channel directories."""
    channel = next((ch for ch in channels if load(ch).get("message_id") == message_id), "")
    rec = load(channel) if channel else {}
    # Not the message with the buttons now, or sclaude is gone: whatever
    # they were for has ended.
    if not rec or not is_alive(rec.get("pid")):
        if channel:
            drop(bot, channel)
        else:
            bot.unbutton(message_id)
        return t("rv.gone")
    action = data.partition(":")[2]
    kind = rec.get("kind")
    if action == "stop" and kind == "pass":
        bot.unbutton(message_id, keyboard(kind, confirm=True))
        return ""
    if action == "carry":
        bot.unbutton(message_id, keyboard(kind, rec.get("said", "")))
        return ""
    if action not in ("pass", "back", "now") or (action == "now" and kind != "pass"):
        return ""
    if not say(channel, action):
        return t("rv.failed")
    if action == "now":
        drop(bot, channel)
        return t("rv.now")
    rec["said"] = "pass" if action == "pass" else ""
    save(channel, rec)
    bot.unbutton(message_id, keyboard(kind, rec["said"]))
    if action == "back":
        return t("rv.back.ok")
    return t("rv.pass.ok") if kind == "pass" else t("rv.round.ok")
