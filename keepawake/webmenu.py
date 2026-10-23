#!/usr/bin/env python3
#
# The bot's menu as a Telegram Mini App: what the page behind the Menu button
# shows and does. An experiment — the chat menus stay as they are.
#
# The page is served by the gate (`sclaude-proxy --gate`, behind the funnel),
# which checks Telegram's signed initData on every call and only then asks this
# module. The page has no screens of its own: a press is handed to the chat's
# own Handler.callback as though it came from a menu message, and PageBot
# catches what the handler would do to that message — the edit becomes the
# page's next screen, a reply becomes a note under it. One handler for both,
# so the page and the chat can never disagree about what a button does.
#
# The page's message has the id PAGE (0): every helper that tracks a message
# by its id already treats 0 as "none", so nothing about the page is
# remembered as a chat message. What is not about that message — the anchor,
# the profile, a card posted to a feature's topic — goes to Telegram as usual.
#
# The language is the bot's: a choice pinned in Settings, otherwise the
# client's language_code from initData, remembered as a message would be.
import os
import subprocess
import threading

from keepawake import telegramd
from keepawake.i18n import current, t

PAGE = 0

# i18n keeps the language in a module global, and the gate answers calls from
# threads; one call at a time keeps a screen in one language.
_LOCK = threading.Lock()

# Buttons the page leaves out.
HIDDEN = ()

# The bot's unit, which the page's restart restarts: the chat's restart
# restarts the process it runs in, and here that is the gate.
BOT_UNIT = os.environ.get("KEEPAWAKE_UNIT") or "keepawake-telegram.service"


class PageBot(telegramd.Bot):
    def __init__(self, token, chat_id):
        super(PageBot, self).__init__(token, chat_id)
        self.screen = None
        self.notes = []
        # What the press did, when it did something: the text of its result.
        self.done = None
        # The page has nothing left to show: it closes after this answer.
        self.close = False

    def edit(self, message_id, text, keyboard=None):
        if message_id != PAGE:
            return super(PageBot, self).edit(message_id, text, keyboard)
        self.screen = (text, keyboard or [])
        return True

    def send(self, text, keyboard=None, quiet=False, thread=None):
        # A reply to the press (no topic named) is the page's; a message to a
        # topic is the chat's.
        if thread is not None:
            return super(PageBot, self).send(text, keyboard, quiet, thread)
        self.notes.append(text)
        return PAGE

    def answer(self, callback_id, text=None, alert=False):
        if text:
            self.notes.append(telegramd.escape(text))

    def ask(self, text, placeholder):
        return PAGE


class PageHandler(telegramd.Handler):
    def result(self, message_id, text):
        # In the chat a press that did something turns its menu into the
        # line saying what; on the page that line is the screen, and it is
        # also what the chat keeps of the press (trace).
        if message_id != PAGE:
            return super(PageHandler, self).result(message_id, text)
        self.bot.screen = (text, [])
        self.bot.done = text


# The note under a screen, by the press that led to it. A press that ends in
# a result (extended, started) shows what was done and needs none.
HELP = (("menu_extend", "help.keepawake"), ("awake_until", "help.until"),
        ("menu_code", "help.code"), ("code_", "help.code"),
        ("menu_chrome", "help.chrome"), ("svc_sclaude", "help.sclaude"),
        ("repo:", "help.sclaude"), ("svc_repos", "help.repos"),
        ("topic:", "help.card"), ("feat:", "help.card"), ("fc:", "help.card"),
        ("menu_services", "help.settings"), ("svc_lang", "help.lang"),
        ("lang:", "help.lang"), ("svc_docs", "help.docs"))


def help_for(action, done):
    if done is not None and not action.startswith(("code_", "lang:")):
        return ""
    if not action or action == "menu_back":
        return t("help.menu")
    for prefix, key in HELP:
        if action.startswith(prefix):
            return t(key)
    return ""


def rows_for_page(rows, main):
    """The keyboard without what the page cannot do, and with a way back
    from every screen but the menu itself."""
    out = [[b for b in row if b.get("callback_data") not in HIDDEN] for row in rows]
    out = [row for row in out if row]
    # A screen's own "Back" may lead one level up rather than to the menu;
    # either way it is the way back, and a second one would only confuse.
    if not main and not any(b.get("callback_data") == "menu_back"
                            or b.get("text") == t("menu.back") for row in out for b in row):
        out.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return out


def press(bot, user, action, context, now):
    """Run one press; the card it leaves, if any, for the next one."""
    if not action or action == "menu_back":
        # The whole menu: the chat's own is only the way here.
        bot.screen = (telegramd.menu_title(), telegramd.menu_keyboard())
        return ""
    if action == "awake_until":
        # The chat asks with a second message and a reply box; the page has a
        # time field of its own, and the chat waits for nothing.
        bot.screen = (t("awake.askpage"), [])
        return ""
    if action.startswith("until:"):
        until_ts = telegramd.parse_hhmm(action[6:], now)
        if not until_ts:
            bot.screen = (t("awake.badtimepage"), [])
            return ""
        until = telegramd.hold_for(until_ts - now, now)
        telegramd.log.info("the menu page: until %s", until)
        bot.screen = (t("extended.plain", at=telegramd.local_for_lang(until)), [])
        bot.done = bot.screen[0]
        return ""
    if action == "phone_toggle" and telegramd.gate_origin(None, False):
        # Turning phone access off from the page closes the page with it.
        bot.screen = (t("svc.phoneoffask"), [
            [{"text": t("svc.phoneoffyes"), "callback_data": "phone_off"}],
            [{"text": t("menu.back"), "callback_data": "menu_services"}]])
        return ""
    if action == "phone_off":
        # The answer goes through the funnel being turned off: it has to
        # leave first. The funnel goes a moment later, and the page closes
        # itself; the Menu button is plain again at once.
        subprocess.Popen(["bash", "-c", "sleep 2; " + telegramd.FUNNEL_OFF],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for target in ({}, {"chat_id": bot.chat_id}):
            try:
                bot.call("setChatMenuButton", menu_button=telegramd.MENU_COMMANDS, **target)
            except Exception as exc:
                telegramd.log.warning("setChatMenuButton: %s", exc)
        # The commands follow: the funnel is about to go.
        bot.commands(online=False)
        telegramd.log.info("the menu page: phone access turned off")
        bot.screen = (t("chrome.gatedown"), [])
        bot.done = bot.screen[0]
        bot.close = True
        return ""
    if action == "svc_restart":
        # The chat's restart edits its message into "back online" from the
        # new process; the page's line in the chat is that message.
        said = telegramd.Bot(bot.token, bot.chat_id).send("📱 " + t("svc.restarting"),
                                                         thread=0)
        with telegramd.locked() as st:
            st["restart_notify"] = said
            st["restart_from_pid"] = 0
            st["restart_page"] = True
        subprocess.Popen(["bash", "-c", "sleep 1; systemctl --user restart " + BOT_UNIT],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        bot.screen = (t("svc.restarting"), [])
        return ""
    if action.startswith("doc:"):
        # The chat sends a section as a message of its own; the page shows it
        # as a screen, with the way back to the list.
        body = telegramd.docs.section(action[4:], current())
        if body:
            bot.screen = (body, [[{"text": t("menu.back"), "callback_data": "svc_docs"}]])
            return ""
    if action.startswith(("topic:", "feat:")):
        # The chat posts the card to the feature's topic; the page shows it.
        _, name, slug = action.split(":", 2)
        name = name or os.path.basename(telegramd.repo_choice())
        bot.screen = telegramd.card(name, slug, in_topic=False)
        return telegramd.channel_key(name, slug)
    if action.startswith("fc:") and action.count(":") == 1 and context:
        # A card button whose data had no room for the feature: the page
        # knows which card it stands on.
        action = "%s:%s" % (action, context)
    telegramd.log.info("the menu page: %s", action)
    PageHandler(bot).callback({"id": "", "data": action, "from": user,
                                     "message": {"message_id": PAGE}})
    if action.startswith("fc:"):
        return action.split(":", 2)[2] if action.count(":") == 2 else context
    return ""


# The card buttons that start something; the rest of a card's only redraw it.
CARD_ACTS = ("go", "acts", "open", "start", "stop", "code")
# A result longer than this is a screen (Chrome's, code-server's), and the
# chat keeps the button's name instead.
TRACE_MAX = 300
# Presses whose result is a screen however short: the language's shows what
# can be chosen, and the chat keeps the choice.
TRACE_LABEL = ("lang:",)


def trace(token, chat_id, action, label, done, context, now):
    """What the chat keeps of a press on the page: one line, marked 📱, in the
    main chat or in the topic of the feature the press was about. Nothing for
    a press that only showed something."""
    thread, text = 0, None
    if action.startswith("fc:") and action.split(":")[1] in CARD_ACTS:
        name, slug = telegramd.split_key(context)
        repo = telegramd.repo_path(name) if slug else None
        if repo:
            thread = telegramd.load_record(repo, slug).get("thread") or 0
        text = telegramd.escape(label) + ("" if thread else " — " + telegramd.escape(slug))
    elif done is not None:
        text = (done if len(done) <= TRACE_MAX and not action.startswith(TRACE_LABEL)
                else telegramd.escape(label))
        # A new feature's line goes where its questions will.
        if action.startswith("newfeat:"):
            thread = telegramd.new_topic_of(action.split(":", 1)[1])
    if not text:
        return
    bot = telegramd.Bot(token, chat_id)
    said = bot.send("📱 " + text, thread=thread)
    # A line about the hold is what holds now: the earlier ones about sleep
    # go, as they do after a press in the chat.
    if action.startswith(("awake:", "until:", "awake_forever")):
        telegramd.said_sleep(bot, said, telegramd.read().get("until_ts") or 0)
    elif action == "awake_release":
        telegramd.said_sleep(bot, said, now + telegramd.IDLE_SLEPT_KEEP)


def answer(token, chat_id, user, action, context, now, label=""):
    """The page's one call: the screen after the press, as JSON-ready data."""
    with _LOCK:
        telegramd.remember_lang(user)
        bot = PageBot(token, chat_id)
        pressed_on = context
        telegramd.ON_PAGE = True
        try:
            context = press(bot, user, action, context, now)
        finally:
            telegramd.ON_PAGE = False
        trace(token, chat_id, action, label, bot.done,
              context or pressed_on, now)
        text, rows = bot.screen or (None, None)
        main = not action or action == "menu_back"
        return {
            "lang": current(),
            "main": main,
            # A press that changed nothing on its message leaves the screen.
            "text": text,
            "rows": rows_for_page(rows, main) if text is not None else None,
            "time": action == "awake_until" or text == t("awake.badtimepage"),
            "notes": bot.notes,
            "context": context,
            "close": bot.close,
            "help": help_for(action, bot.done) if text is not None else "",
        }
