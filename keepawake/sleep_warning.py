# keepawake's Telegram bot — the warning before sleep: forgotten hard holders,
# the phone after a boot, the trail of messages said about sleep, and the
# warning itself.
#
# Part of the bot that keepawake/telegramd.py runs.

import html
import logging
import re
import shutil
import time

from keepawake.i18n import t
from keepawake.state import local_label, locked, needs_warning, read
from keepawake import card_view, holding, menus, phone_access, services, shell, status_report, widgets


log = logging.getLogger("keepawake")


# --- forgotten hard holders --------------------------------------------------

# Once an hour, no more often: the question about a forgotten session is not
# urgent, and repeating it every half hour teaches people not to read it.
IDLE_ASK_EVERY = 3600


def human_span(seconds):
    if seconds >= 3600:
        h, m = divmod(int(seconds) // 60, 60)
        return t("span.hours", h=h, m=m)
    return t("span.minutes", m=int(seconds) // 60)


def idle_keyboard():
    # "Stop them" used to be here, but it shut down only code-server and the
    # dev server and did not touch the manual deadline — on a day when it was
    # precisely an indefinite hold doing the holding, the press would have
    # changed nothing. In its place is an entrance to the menu, where any hold
    # can be released; the frequent answers stay where they were.
    return [
        [{"text": t("idle.keep"), "callback_data": "idle_keep"}],
        [{"text": t("menu.extend"), "callback_data": "menu_extend"}],
        [{"text": t("idle.sleep"), "callback_data": "idle_sleep"}],
    ]


def check_idle_hold(bot):
    # There are hard holders but no traces of work — it looks as though a
    # session was left open. We ask, but only when the machine really is busy
    # with nothing: a long build without a single keystroke is work, and
    # interrupting it with a question is not the thing to do.
    now = int(time.time())
    data = read()
    idle = data.get("idle_seconds") or 0
    # The previous question is moot once nothing holds, or somebody typed —
    # the session was not forgotten after all — or no session is left to have
    # forgotten. It goes rather than wait for a press that would change
    # nothing.
    asked_msg = data.get("idle_message_id") or 0
    if asked_msg and (not data.get("hard_hold") or idle < services.IDLE_SECONDS_THRESHOLD
                      or idle >= services.IDLE_UNKNOWN):
        menus.retire(bot, asked_msg)
        with locked() as st:
            if st.get("idle_message_id") == asked_msg:
                st["idle_message_id"] = 0
    if not data.get("hard_hold"):
        return
    if data.get("busy"):
        return
    if idle < services.IDLE_SECONDS_THRESHOLD:
        return
    # 999999 is the detector's placeholder for "no interactive sessions at
    # all". Idling cannot be judged by it: it produced "277 hours without input"
    # on a machine that had been working since yesterday. No sessions means no
    # input to wait for either, and something else is holding then (a code-server
    # tab, tailnet traffic), so a question about a forgotten terminal is out of
    # place here.
    if idle >= services.IDLE_UNKNOWN:
        return
    asked = data.get("idle_asked_ts") or 0
    if now - asked < IDLE_ASK_EVERY:
        return

    since = data.get("hard_since") or 0
    if not since:
        # We are holding but do not know since when — writing "it has not slept
        # for 0 minutes" is worse than writing nothing at all: the number is the
        # first thing people read.
        return
    # An hour on the same question is asked again: the earlier one goes, so
    # the chat holds it once.
    menus.retire(bot, read().get("idle_message_id") or 0)
    msg = bot.send(t("idle.warn", since=local_label(since),
                     held=human_span(now - since), idle=human_span(idle),
                     who=status_report.reasons_lines(status_report.hold_reasons(data, now))), idle_keyboard())
    with locked() as st:
        st["idle_asked_ts"] = now
        st["idle_message_id"] = msg
    log.info("asked about forgotten hard holders (idle %d s)", idle)


# --- the warning -------------------------------------------------------------

def sleep_reason(data, now):
    # Why things are heading for sleep. On its own "it will sleep in 30
    # minutes" does not tell a person what has happened and what they can do:
    # the holders are gone, only soft ones are left, or they asked for sleep
    # themselves — the cases differ, and the decision made by button depends on
    # them.
    from keepawake.state import refuses
    if refuses(data, now):
        return t("why.refused", who=status_report.holders_line(data))
    soft = status_report.holders_line(data, "soft")
    if soft != t("hold.nobody"):
        return t("why.soft", who=soft)
    return t("why.nobody")


# Whether phone access was on when this process last looked; None before the
# first look.
PHONE_SEEN = [None]


def phone_changed(bot, on):
    # Everything that offers the app follows phone access: the Menu button,
    # the list of commands, the menu screens, the feature cards.
    PHONE_SEEN[0] = on
    if on:
        # Turned on from the terminal too: it counts as asked for.
        with locked() as st:
            st["phone_on_at"] = max(st.get("phone_on_at") or 0, boot_time())
    bot.menu_button()
    bot.commands(online=on)
    card_view.redraw_screens(bot)
    card_view.redraw_cards(bot)
    log.info("phone access is %s: the menu, the commands and the cards follow",
             "on" if on else "off")


def boot_time():
    """When this machine (for WSL, its VM) started, by the kernel."""
    with open("/proc/stat") as fh:
        for line in fh:
            if line.startswith("btime "):
                return int(line.split()[1])
    return 0


# Whether tailscale has answered since this process started: until it has,
# a funnel kept from before the boot cannot be told from none. The second
# item counts the tries.
BOOT_LOOKED = [False, 0]
BOOT_TRIES = 40


def phone_off_after_boot():
    # Phone access is off unless asked for since the machine started:
    # Tailscale keeps a funnel across reboots, and a door to the internet
    # nobody remembers opening is one to close. A restart of the bot alone
    # leaves it as it was. Tried at start and on the loop's turns until
    # tailscale answers: the bot may start before tailscaled does, and a
    # funnel first seen later would pass for one asked for.
    if BOOT_LOOKED[0]:
        return
    BOOT_LOOKED[1] += 1
    # No tailscale, or one silent for some forty turns (a quarter of an
    # hour): nothing to close, and two processes a turn for ever otherwise.
    if not shutil.which("tailscale") or BOOT_LOOKED[1] > BOOT_TRIES:
        BOOT_LOOKED[0] = True
        log.info("phone access after boot: tailscale did not answer, not looked at")
        return
    out = shell.run("tailscale serve status --json", timeout=10)
    # Answered means JSON: run() gives the error's text or its own words
    # for one that failed — tailscaled not up yet — never an empty string.
    config = phone_access.json_in(out)
    if config is None:
        return
    BOOT_LOOKED[0] = True
    if not phone_access.gate_origin(config, False):
        return
    if (read().get("phone_on_at") or 0) >= boot_time():
        return
    shell.run(phone_access.FUNNEL_OFF, timeout=30)
    log.info("phone access was on from before the machine started: turned off")


def wait_for_phone(message_id):
    # The message saying phone access is coming: check_phone turns it into
    # "it is on" once a phone can reach it.
    with locked() as st:
        st["phone_wait"] = {"msg": message_id or 0, "since": int(time.time())}


def check_phone(bot):
    # Phone access changes from the chat, from the menu page (another
    # process) and from the terminal; the loop catches every one of them.
    phone_off_after_boot()
    config = phone_access.serve_config()
    on = bool(phone_access.gate_origin(config, True, True))
    if PHONE_SEEN[0] is None:
        PHONE_SEEN[0] = on
    elif on != PHONE_SEEN[0]:
        phone_changed(bot, on)
    wait = read().get("phone_wait")
    if wait and (on or not phone_access.gate_origin(config, False)):
        # Ready — or turned off again before it was.
        with locked() as st:
            st["phone_wait"] = None
        if on and wait.get("msg"):
            bot.edit(wait["msg"], t("svc.phoneready"))


# How long "the hold is released, it will sleep" stays: Windows sleeps after
# its own idle time, and by then the line is history.
IDLE_SLEPT_KEEP = 1800
# The longest a line about sleep is kept: deleted inside Telegram's 48 hours.
TRAIL_MAX = 40 * 3600


def trail(message_id, expires):
    # A message about sleep that has become an answer — "extended until",
    # "will sleep" — stays only while it is true: until its deadline, or until
    # the next warning, whichever is first (sweep_trail). Kept in the state as
    # sleep_trail: [message id, expiry].
    # Within Telegram's 48 hours, past which a message can no longer be
    # deleted, only edited into a dead line.
    if not message_id:
        return
    expires = min(int(expires), int(time.time()) + TRAIL_MAX)
    with locked() as st:
        kept = [e for e in st.get("sleep_trail") or [] if e[0] != message_id]
        st["sleep_trail"] = kept + [[message_id, expires]]


def said_sleep(bot, message_id, expires):
    # A reply that moved the deadline or let it go: it is what holds now, and
    # every earlier line about sleep is no longer true — the open warning
    # included, which would otherwise be settled into a second such line.
    # Not sent, it replaces nothing.
    if not message_id:
        return
    sweep_trail(bot, int(time.time()), everything=True)
    warn = read().get("warn_message_id") or 0
    if warn and warn != message_id:
        if not menus.retire(bot, warn):
            trail(warn, 0)
        with locked() as st:
            if st.get("warn_message_id") == warn:
                st["warn_message_id"] = 0
    trail(message_id, expires)


def said_elsewhere(bot):
    """A reply about sleep that has no line of its own — the menu widget
    shows it: every earlier line about sleep goes, the open warning too, as
    after any other reply."""
    sweep_trail(bot, int(time.time()), everything=True)
    warn = read().get("warn_message_id") or 0
    if warn:
        if not menus.retire(bot, warn):
            trail(warn, 0)
        with locked() as st:
            if st.get("warn_message_id") == warn:
                st["warn_message_id"] = 0


def sweep_trail(bot, now, everything=False):
    # The chat holds no message about sleep that is no longer true: those past
    # their deadline go, and with a new warning every earlier one goes.
    trail_now = read().get("sleep_trail") or []
    gone = [e for e in trail_now if everything or e[1] <= now]
    if not gone:
        return
    # One the network kept is tried again on the next turn.
    done = [e for e in gone if menus.retire(bot, e[0])]
    if not done:
        return
    with locked() as st:
        st["sleep_trail"] = [e for e in st.get("sleep_trail") or [] if e not in done]


def settle_warning(bot, data, now):
    # The warning's message once its deadline has moved without a press on it:
    # extended from elsewhere (a command, the menu, the detector seeing work)
    # becomes "extended until", released becomes "will sleep" — the answers its
    # own buttons would have given — and both stay only while true (trail).
    # Left alone, it goes once its deadline has passed: it is no longer true.
    msg = data.get("warn_message_id") or 0
    if not msg:
        return
    warned = data.get("warned_for_ts") or 0
    until = data.get("until_ts") or 0
    # Past its deadline it is no longer true, whatever happened since: a later
    # move is a fresh hold after the laptop slept and woke, and the warning was
    # simply not answered.
    if now >= warned:
        if not menus.retire(bot, msg):
            trail(msg, now)     # the network's: tried again next turn
    elif until == warned:
        return
    elif until > warned:
        say_settled(bot, msg, data, "x", now)
        trail(msg, until)
    elif data.get("decision") == "sleep":
        say_settled(bot, msg, data, "z", now)
        trail(msg, now + IDLE_SLEPT_KEEP)
    elif not menus.retire(bot, msg):
        trail(msg, now)
    with locked() as st:
        if st.get("warn_message_id") == msg:
            st["warn_message_id"] = 0
            st["warn_widget"] = False


# --- the warning as a widget (widget_html/hold.html) ------------------------
#
# The same warning, its countdown counted by the widget itself and its answers
# taps in it. A change of the deadline from elsewhere changes the widget's
# state rather than its text; a press on one whose window is over is answered
# with "out of date" and the widget goes, as the message's button did.

HOLD_LABELS = {"l": "widget.hold.left", "n": "widget.hold.now", "nx": "widget.hold.next",
               "o": "msg.stale",
               "ext": "sleep.extend", "let": "sleep.let",
               "busy": "widget.busy", "fail": "widget.failed"}
# The widget's answers, by the letter its buttons send.
HOLD_ACTIONS = {"x": "extend", "z": "sleep"}


def plain(text):
    """The bot's HTML as the text a widget sets."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


def hold_state(data, now, status=""):
    """The widget's state: the deadline, its label, why it is coming, and
    what happened ("" while it waits for an answer)."""
    at = status_report.escape(status_report.local_for_lang(data.get("until_local")) or "?")
    return widgets.state({"u": data.get("until_ts") or 0, "a": at, "s": status,
                          "w": "" if status else plain(sleep_reason(data, now))}, trim="w")


def settled_text(data, status):
    return (t("sleep.extended", at=status_report.local_for_lang(data.get("until_local")))
            if status == "x" else t("sleep.accepted"))


def say_settled(bot, msg, data, status, now):
    # The warning answered — "x" extended, "z" let sleep: a widget's state
    # and caption, or a message's text.
    if data.get("warn_widget"):
        bot.widget_data(msg, hold_state(data, now, status))
        bot.caption(msg, settled_text(data, status))
    else:
        bot.edit(msg, settled_text(data, status))


def send_hold(bot, data, now):
    at = status_report.local_for_lang(data.get("until_local")) or "?"
    return bot.send_widget(widgets.code("hold", HOLD_LABELS), hold_state(data, now),
                           t("widget.hold.caption", at=status_report.escape(at)))


def hold_press(bot, raw, message_id, now):
    """A tap in the hold widget, hold:<x|z>:<deadline>: the state to answer
    it with, and what is done after the answer (None for nothing)."""
    _hold, key, ts = (raw.split(":") + ["", ""])[:3]
    action = HOLD_ACTIONS.get(key)
    stamp = int(ts) if ts.isdigit() else None
    if not action:
        return widgets.state(widgets.STALE), None
    kind, _until, until_ts = holding.decide(action, stamp, now)
    if kind == "stale":
        def gone():
            if not menus.retire(bot, message_id):
                trail(message_id, now)
        return widgets.state(widgets.STALE), gone
    # Answered: the loop no longer settles this message; after() does.
    holding.let_go(message_id)
    status = "x" if kind == "extend" else "z"
    data = read()
    answer = hold_state(data, now, status)
    expires = until_ts if kind == "extend" else now + IDLE_SLEPT_KEEP

    def after():
        # The state stays with the message: a widget drawn again later (the
        # app restarted, scrolled back) shows the answer, not the question.
        # Not kept, the widget would ask again with the old deadline: it goes.
        # Either way the deadline did move, and earlier lines about sleep go
        # with said_sleep; a widget the network kept is tried again next turn.
        kept = bot.widget_data(message_id, answer)
        if kept:
            bot.caption(message_id, settled_text(data, status))
        said_sleep(bot, message_id, expires)
        if not kept and not menus.retire(bot, message_id):
            trail(message_id, now)
    return answer, after


def check_warning(bot):
    now = int(time.time())
    data = read()
    # The old warning is settled first: the next one may be about to go out for
    # the new deadline, and the old must not stand above it with live buttons.
    settle_warning(bot, data, now)
    sweep_trail(bot, now)
    data = read()
    if not needs_warning(data, now):
        return
    until = data["until_ts"]
    left = max(0, (until - now) // 60)
    text = t("sleep.warn", at=status_report.local_for_lang(data.get("until_local")) or "?",
             min=left, why=sleep_reason(data, now))
    widget = widgets.enabled()
    msg_id = send_hold(bot, data, now) if widget else bot.send(text, holding.warn_keyboard(until))
    if not msg_id:
        # The send failed — there is no network, and on a laptop it drops
        # regularly. We do not set the mark: otherwise the warning for this
        # deadline would never repeat and the laptop would sleep silently. The
        # loop's next turn will try again in 25 seconds, which fits comfortably
        # within half an hour.
        log.warning("the warning did not send — we will retry on the next turn")
        return
    # The warning is the one message about sleep: every earlier one goes.
    sweep_trail(bot, now, everything=True)
    with locked() as st:
        # We record the deadline the warning was for. Extending will move
        # until_ts, the mark will stop matching — and the next warning will come
        # for the new deadline, by itself.
        st["warned_for_ts"] = until
        st["warn_message_id"] = msg_id
        st["warn_widget"] = widget
    log.info("the warning was sent for %s", data.get("until_local"))
