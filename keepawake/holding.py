# keepawake's Telegram bot — the hold: the awake screen, extending and
# releasing it, and the screens that wait for a typed time.
#
# Part of the bot that keepawake/telegramd.py runs.

import datetime
import logging
import re
import time

from keepawake import state
from keepawake.i18n import t
from keepawake.state import local_label, locked, read, touch
from keepawake import menus, status_report


log = logging.getLogger("keepawake")


# "Never sleep at all" is indefinite in words only: in the state it is an
# ordinary until_ts, merely a distant one. There is deliberately no separate
# "hold for ever" field — should_hold is duplicated in KeepAwake.ps1, and every
# new field would have to be created in two runtimes at once, at the risk of
# their diverging. A week is longer than any sensible session, and STALE_AFTER
# remains the insurance against a forgotten hold: a crashed WSL stops holding
# after fifteen minutes, however distant the deadline.
FOREVER_SECONDS = 7 * 24 * 3600


def awake_keyboard():
    return [
        [{"text": t("awake.h1"), "callback_data": "awake:3600"},
         {"text": t("awake.h2"), "callback_data": "awake:14400"},
         {"text": t("awake.h3"), "callback_data": "awake:86400"}],
        [{"text": t("awake.until"), "callback_data": "awake_until"}],
        [{"text": t("awake.forever"), "callback_data": "awake_forever"}],
        [{"text": t("awake.release"), "callback_data": "awake_release"}],
        [{"text": t("menu.back"), "callback_data": "menu_back"}],
    ]


def awake_text():
    # We show the current deadline: a person makes the "one hour or three"
    # choice knowing how much there already is, otherwise extending blind turns
    # into guesswork.
    data = read()
    now = int(time.time())
    until = data.get("until_ts") or 0
    if until <= now:
        return t("awake.title.free")
    text = t("awake.title", until=status_report.escape(status_report.local_for_lang(data.get("until_local") or "")))
    # We say the manual deadline outright: "holding until 23:00" with a single
    # live claude looks inexplicable otherwise, and the person is deciding
    # whether to extend further as well. We also answer at once what comes after
    # — the usual hour returns.
    if state.manual_until(data, now):
        text += t("awake.manual")
    return text


def keepawake_text():
    # The hold and, under it, the status that explains it: one screen for
    # deciding whether to extend.
    return awake_text() + "\n\n" + status_report.status_text()


def hold_for(seconds, now):
    # The shared tail of every extension: move the deadline, lift the previous
    # refusal and mark the heartbeat. We lift the refusal because the person has
    # just changed their mind — otherwise the detector would see "they asked for
    # sleep" a minute later and would not extend any further.
    with locked() as st:
        state.extend(st, now, seconds, manual=True)
        state.touch(st, now)
        st["decision"] = ""
        st["decision_ts"] = 0
        st["awaiting"] = ""
        return st["until_local"]


def release_hold(now):
    # A mirror of hold_for: that one moves the deadline forward, this one drops
    # the hold entirely — both the deadline and the hard one — and sets the
    # refusal. The refusal is essential: without it the detector would see a
    # live SSH session a minute later and extend back what the person has just
    # dropped. Windows counts the idling itself from then on.
    #
    # One place for all three entrances — the button in the sleep submenu, "let
    # it sleep" in the question about forgotten holders, and the /sleep command
    # — because the order of the fields here is not obvious, and copies that
    # diverged would give a hold released by halves.
    with locked() as st:
        st["until_ts"] = now
        st["until_local"] = local_label(now)
        st["hard_hold"] = False
        st["decision"] = "sleep"
        st["decision_ts"] = now
        state.drop_manual(st)
        touch(st, now)


# --- the bot's own questions ---------------------------------------------------
#
# Besides sclaude's questions the bot asks three of its own: the warning before
# sleep, the question about forgotten holders, and "until what time?" with its
# input box. Each outlives its point the same way — the person answered
# elsewhere, or the situation moved on — and is then settled like sclaude's:
# replaced by what happened, or deleted. The state keeps their message ids:
# warn_message_id, idle_message_id, and awaiting_ids for the time question,
# which is two messages (the "back" button and the input box).

def let_go(message_id):
    # A press edits the message it came from into something else — a menu, a
    # result — so it no longer shows the question it was tracked for, and the
    # loop must not delete it for that question's sake.
    if not message_id:
        return
    data = read()
    ids = data.get("awaiting_ids") or {}
    if message_id not in (data.get("warn_message_id"), data.get("idle_message_id")) \
            and message_id not in ids.values():
        return
    with locked() as st:
        for key in ("warn_message_id", "idle_message_id"):
            if st.get(key) == message_id:
                st[key] = 0
        st["awaiting_ids"] = {k: v for k, v in (st.get("awaiting_ids") or {}).items()
                              if v != message_id}


def settle_awaiting(bot, text=None, keyboard=None):
    # The time question has ended. With text it was answered: its message
    # becomes the answer and the input box goes. Without, it was left — by a
    # command, the menu, or a neighbouring button — and both go.
    with locked() as st:
        ids = st.get("awaiting_ids") or {}
        st["awaiting_ids"] = {}
    # Returns the message that carries the answer, if any.
    menu, prompt = ids.get("menu") or 0, ids.get("prompt") or 0
    said = 0
    if text and menu:
        bot.edit(menu, text, keyboard)
        # Answered, the menu it stood in is a line of history now (see
        # Handler.result), not a screen for the next one to replace.
        forget_screen(menu)
        said = menu
    elif text:
        said = bot.send(text, keyboard)
    else:
        forget_screen(menu)
        menus.retire(bot, menu)
    menus.retire(bot, prompt)
    return said


def forget_screen(message_id):
    # The screen has become a line of history: the next screen leaves it be.
    screens = read().get("screens") or {}
    places = [p for p, m in screens.items() if m == message_id]
    if places:
        with locked() as st:
            screens = st.get("screens") or {}
            for p in places:
                screens.pop(p, None)
            st["screens"] = screens


def forget_screen_place(thread):
    # A deleted topic's screen went with it.
    if str(thread) in (read().get("screens") or {}):
        with locked() as st:
            screens = st.get("screens") or {}
            screens.pop(str(thread), None)
            st["screens"] = screens


def check_awaiting(bot):
    # The wait is cleared in many places that have no bot at hand (hold_for,
    # release_hold, a command), so its messages are swept here, on the turn.
    data = read()
    if data.get("awaiting_ids") and not data.get("awaiting"):
        settle_awaiting(bot)


def parse_hhmm(text, now):
    # "until 23:30" is today's time; if it has already passed, tomorrow was
    # meant. Otherwise a "stay awake until 7:00" sent at night would mean a
    # deadline in the past, that is instant sleep.
    m = re.match(r"^(\d{1,2})[:.\s](\d{2})$", text.strip())
    if not m:
        return 0
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return 0
    now_dt = datetime.datetime.fromtimestamp(now)
    target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_dt:
        target += datetime.timedelta(days=1)
    return int(target.timestamp())


def warn_keyboard(until_ts):
    # The deadline stamp inside callback_data is what tells a fresh press from
    # a press on yesterday's message. Without it the "Extend" button from an old
    # notification would extend the hold at an arbitrary moment the next day.
    return [[
        {"text": t("sleep.extend"), "callback_data": "extend:%d" % until_ts},
        {"text": t("sleep.let"), "callback_data": "sleep:%d" % until_ts},
    ]]
