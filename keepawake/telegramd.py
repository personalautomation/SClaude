#!/usr/bin/env python3
#
# The keepawake Telegram bot: extending the hold and service commands from a
# phone.
#
# One process does both things — sends the warning half an hour before sleep and
# receives button presses. There is no reason to separate them: the warning is
# the sending of a message rather than a computation, and everything needed to
# send it (the token, chat_id, HTTP with retries, the message id for a later
# edit) exists only here. A separate warning script would be a second instance
# of the same machinery and would still write warn_message_id to a shared
# file.
#
# The loop comes from getUpdates: with timeout=25 it returns control at least
# once every 25 seconds even in complete silence, which is an order of magnitude
# more precise than a thirty-minute threshold needs.
#
# Interactive things (sclaude, claude) are not brought in here and cannot be:
# they require a live TTY — they read arrow keys character by character from
# /dev/tty and draw the screen with ANSI codes. Termius and code-server are
# there for those, where the terminal is real. Only what fits into a command
# without a dialogue belongs here.
import collections
import datetime
import glob
import json
import logging
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keepawake import docs, notices, state
import statusline
from keepawake.i18n import DEFAULT, STRINGS, current, set_lang, ssh_holders, t
from keepawake.state import (HOLD_SECONDS, local_label, locked, needs_warning,
                             read, touch)

API = "https://api.telegram.org/bot%s/%s"

# A long getUpdates: it holds the connection while there are no updates and
# returns control as soon as something arrives.
POLL_TIMEOUT = 25

# The backoff ceiling. The network on a laptop drops regularly — that is normal,
# not a reason to die: restarting the daemon loses the offset and creates a
# spike of requests.
BACKOFF_MAX = 60

log = logging.getLogger("keepawake")



def profile_halves():
    # Which half of an i18n pair goes into each language slot of the profile
    # of the bot — its description and its commands. Telegram picks the slot
    # by the language of the app, which the bot cannot see past; the bot has
    # one reader, though. A language pinned in the settings therefore fills both
    # slots, or a Russian app kept showing Russian to a person who had chosen
    # English. None is the default slot, every language without its own.
    halves = {"ru": 0, None: 1}
    if read().get("lang_pinned"):
        halves = dict.fromkeys(halves, 0 if current() == "ru" else 1)
    return halves


# The Menu button as the list of commands.
MENU_COMMANDS = {"type": "commands"}


class Bot(object):
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = int(chat_id)
        self.offset = 0
        self.stopped = False
        # The topic the update being handled came from. Replies go back there:
        # a /status typed in a feature's topic is answered in that topic rather
        # than in the main chat. 0 outside handling — what the loop sends by
        # itself names its topic explicitly.
        self.thread = 0
        # What Telegram said to the last send that failed, lowercased; "" after
        # one that went through.
        self.last_error = ""

    # --- transport ----------------------------------------------------------

    def call(self, method, http_timeout=15, **params):
        # http_timeout is the ceiling for the socket, params["timeout"] is how
        # long Telegram holds the long poll. The values differ and must not be
        # confused: the socket has to outlive the long poll, otherwise every
        # empty poll would look like a dropped connection.
        try:
            return self._post(method, http_timeout, params)
        except urllib.error.HTTPError as exc:
            # A button's colour (`style`) is recent in the Bot API. Should
            # Telegram refuse it, the same message goes again without colours
            # rather than not at all.
            # Only a refusal that names the button: "message is not modified"
            # is a 400 as well, and taking it for this one stripped the colour
            # off a card that had simply not changed.
            styled = json.dumps(params.get("reply_markup") or {})
            try:
                reason = exc.read().decode("utf-8", "replace").lower()
            except Exception:
                reason = ""
            # Kept on the error: the caller may need to know what exactly was
            # refused — "message thread not found" is not a network failure.
            exc.telegram = reason
            if exc.code != 400 or '"style"' not in styled \
                    or not any(w in reason for w in ("style", "button")):
                raise
            log.warning("%s refused a styled keyboard; sending it plain", method)
            params["reply_markup"] = unstyled(params["reply_markup"])
            try:
                return self._post(method, http_timeout, params)
            except urllib.error.HTTPError as again:
                try:
                    again.telegram = again.read().decode("utf-8", "replace").lower()
                except Exception:
                    again.telegram = ""
                raise

    def _post(self, method, http_timeout, params):
        url = API % (self.token, method)
        data = urllib.parse.urlencode(
            {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
             for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            return json.load(resp)

    # --- messages -----------------------------------------------------------

    def send(self, text, keyboard=None, quiet=False, thread=None):
        # quiet is a message without a sound. Not "do not send": it arrives and
        # sits in the chat, it simply does not buzz the phone. Needed where the
        # person is already looking at the same thing in the terminal — see
        # at_terminal.
        #
        # The string "true" rather than True: urlencode prints Python's bool
        # capitalised. The Bot API accepts that, but the documented form is
        # lower case, and there is no reason to rely on the parser's leniency.
        # When a sound is wanted we put None — call does not send such
        # parameters at all, so the request stays exactly as it was.
        try:
            out = self.call("sendMessage", chat_id=self.chat_id, text=text,
                            parse_mode="HTML",
                            # None: where the update being handled came from;
                            # 0: the main chat, whatever is being handled.
                            message_thread_id=(self.thread if thread is None
                                               else thread) or None,
                            disable_notification="true" if quiet else None,
                            reply_markup={"inline_keyboard": keyboard} if keyboard else None)
            self.last_error = ""
            return (out.get("result") or {}).get("message_id", 0)
        except Exception as exc:
            self.last_error = getattr(exc, "telegram", "") or str(exc).lower()
            log.warning("did not send: %s", exc)
            return 0

    def ask(self, text, placeholder):
        # A question that expects text. The input box in a chat with a bot is
        # always there — the Bot API does not allow removing it — but usually a
        # person has no use for it here: everything is done with buttons.
        # ForceReply turns it from "sitting empty" into "type right here": the
        # cursor places itself, the phone's keyboard opens, and the placeholder
        # shows the expected format — that is, the box becomes visible exactly
        # when we have turned to it.
        #
        # A separate message rather than an edit of the previous one:
        # editMessageText's reply_markup is inline only, and ForceReply cannot go
        # there.
        try:
            out = self.call("sendMessage", chat_id=self.chat_id, text=text,
                            parse_mode="HTML",
                            message_thread_id=self.thread or None,
                            reply_markup={"force_reply": True,
                                          "input_field_placeholder": placeholder})
            return (out.get("result") or {}).get("message_id", 0)
        except Exception as exc:
            log.warning("the question did not send: %s", exc)
            return 0

    def anchor(self, text):
        # A separate message with a reply keyboard — the one that lives below
        # the input box rather than inside a message. Inline buttons ride up
        # with their message as soon as a couple of imminent-sleep notifications
        # arrive; this one stays on the screen always, however much history
        # piles up.
        #
        # They cannot be combined in one message: a message has one
        # reply_markup, and it is either an inline_keyboard or a keyboard. So
        # the keyboard is set by its own message once at start-up and is then
        # held by the chat itself — Telegram remembers it until a replace or a
        # ReplyKeyboardRemove.
        try:
            self.call("sendMessage", chat_id=self.chat_id, text=text,
                      parse_mode="HTML",
                      reply_markup={"keyboard": [[{"text": t("menu.button")}]],
                                    "resize_keyboard": True,
                                    "is_persistent": True})
        except Exception as exc:
            log.warning("the keyboard did not appear: %s", exc)

    def commands(self, online=None):
        # The bot's commands: a second route to the menu, in case the reply
        # keyboard has been hidden. The button in the input box that Telegram
        # creates for them is removed by menu_button. Not critical — they must
        # not be a reason to die.
        # Per language, like the profile texts: written once in the language of
        # the start, they listed Russian under an English bot.
        #
        # Only what the chat's menu offers at the moment: without phone
        # access that is the hold and turning access on (chat_menu); with it,
        # everything but /phone, the sections leading to the app.
        if online is None:
            online = bool(gate_origin())
        shown = OFFLINE_COMMANDS if not online else [
            name for name in COMMANDS if name != "phone"]
        for code, half in profile_halves().items():
            try:
                self.call("setMyCommands", language_code=code, commands=[
                    {"command": name, "description": STRINGS[key][half]}
                    for name, (_method, key) in COMMANDS.items()
                    if name != "start" and name in shown])
            except Exception as exc:
                log.warning("setMyCommands: %s", exc)

    def describe(self):
        # The profile's texts, from i18n in both languages: Russian for a
        # Russian client, English for everyone else, as the bot answers.
        # Set here rather than by hand in @BotFather, where they went stale.
        # Not critical, like the commands.
        # Only when they changed: four calls at every start hold up the first
        # poll when the network is slow.
        # By bot too: a new token is a bot with an empty profile.
        data = read()
        pinned = current() if data.get("lang_pinned") else None
        halves = profile_halves()
        texts = repr([self.token.split(":")[0], pinned,
                      STRINGS["bot.description"], STRINGS["bot.short"]])
        if data.get("described") == texts:
            return
        done = True
        for code, half in halves.items():
            for method, field, key in (
                    ("setMyDescription", "description", "bot.description"),
                    ("setMyShortDescription", "short_description", "bot.short")):
                # Each on its own: one refused leaves the other to be set.
                try:
                    self.call(method, language_code=code, **{field: STRINGS[key][half]})
                except Exception as exc:
                    done = False
                    log.warning("%s: %s", method, exc)
        if done:
            with locked() as st:
                st["described"] = texts

    def menu_button(self):
        # Create commands and Telegram puts a blue button with their list on
        # the left of the input box by itself. The chat then had two entrances
        # to one menu: that button and the big one below the box. We give the
        # box its usual look back — "default" — and one menu is left. The
        # commands live on: /menu and /status are typed by hand and are
        # suggested when typing "/".
        #
        # A language mismatch goes away with it: Telegram takes the blue
        # button's caption from the phone's locale rather than from our strings,
        # and a Russian "Menu" caption used to hang over an English menu.
        #
        # While phone access is on, the button opens the menu as a Mini App
        # instead (webmenu.py, behind the gate) — an experiment. Its caption
        # is ours then, in the language of this moment. Without access it is
        # the list of commands, said outright: "default" means "no value of
        # its own", and a chat or a bot with none kept showing the app that
        # could no longer open.
        origin = gate_origin()
        button = ({"type": "web_app", "text": t("menu.button"),
                   "web_app": {"url": origin + "/__sclaude/menu"}}
                  if origin else MENU_COMMANDS)
        # Set for this chat as well as for all: a change of the default
        # reaches an open Telegram app only when it opens the chat anew,
        # while one made for the chat is sent to it at once.
        for target in ({}, {"chat_id": self.chat_id}):
            try:
                self.call("setChatMenuButton", menu_button=button, **target)
            except Exception as exc:
                log.warning("setChatMenuButton: %s", exc)

    def edit(self, message_id, text, keyboard=None):
        # Whether the edit went through.
        try:
            self.call("editMessageText", chat_id=self.chat_id,
                      message_id=message_id, text=text, parse_mode="HTML",
                      reply_markup={"inline_keyboard": keyboard} if keyboard else None)
            return True
        except Exception as exc:
            # The message already shows that text: it is as asked. Telegram's
            # own words are on the error (call), not in its str().
            if "not modified" in (getattr(exc, "telegram", "") or str(exc)).lower():
                return True
            log.warning("did not edit: %s", exc)
            return False

    # --- topics -------------------------------------------------------------
    #
    # Editing and deleting a message need no topic: a message id is unique in
    # the whole chat, whichever topic the message is in. Only what is sent
    # names one.

    def create_topic(self, name):
        try:
            out = self.call("createForumTopic", chat_id=self.chat_id, name=name)
            self.last_error = ""
            return (out.get("result") or {}).get("message_thread_id", 0)
        except Exception as exc:
            self.last_error = getattr(exc, "telegram", "") or str(exc).lower()
            log.warning("no topic was made: %s", exc)
            return 0

    def rename_topic(self, thread, name):
        try:
            self.call("editForumTopic", chat_id=self.chat_id,
                      message_thread_id=thread, name=name)
            return True
        except Exception as exc:
            log.warning("the topic was not renamed: %s", exc)
            return False

    def delete_topic(self, thread):
        # Whether the topic is gone — deleted now, or before, by hand. False
        # only when it may still be there: the network, Telegram's limits.
        try:
            self.call("deleteForumTopic", chat_id=self.chat_id,
                      message_thread_id=thread)
            return True
        except Exception as exc:
            log.warning("the topic was not deleted: %s", exc)
            # Gone already, by hand, or topics are off: nothing left to
            # delete. Any other failure is tried again on the next turn; the
            # orchestrator clears a mark left a week (io.sh).
            reason = getattr(exc, "telegram", "")
            return any(w in reason for w in TOPIC_GONE)

    def unbutton(self, message_id):
        # The message's text stays, its buttons go.
        try:
            self.call("editMessageReplyMarkup", chat_id=self.chat_id,
                      message_id=message_id)
        except Exception as exc:
            log.warning("the buttons stayed: %s", exc)

    def delete(self, message_id):
        # Returns whether the message is gone. Telegram refuses a bot's delete
        # once the message is 48 hours old — see retire for what happens then.
        if not message_id:
            return False
        try:
            out = self.call("deleteMessage", chat_id=self.chat_id,
                            message_id=message_id)
            return bool(out.get("result"))
        except Exception as exc:
            # Already gone — deleted by hand, or with its topic — is gone.
            if "not found" in (getattr(exc, "telegram", "") or str(exc).lower()):
                return True
            log.warning("did not delete: %s", exc)
            return False

    def answer(self, callback_id, text=None, alert=False):
        # We answer first thing: Telegram gives about ten seconds for this,
        # otherwise a spinner hangs on the person's phone until the timeout.
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id,
                      text=text, show_alert=alert, http_timeout=10)
        except Exception as exc:
            log.warning("answerCallbackQuery: %s", exc)


# --- keyboards --------------------------------------------------------------

def retire(bot, message_id):
    # A message whose question died without an answer: it is deleted, so the
    # chat keeps only what is still waiting for the person. Telegram lets a bot
    # delete only for 48 hours; past that the message is edited instead, and
    # the edit takes its buttons away — a press on a dead question must not be
    # possible.
    # Returns whether the message is gone or edited: False is the network's,
    # and a caller that keeps the id can try again.
    if not message_id:
        return True
    return bool(bot.delete(message_id) or bot.edit(message_id, t("msg.stale")))


def unstyled(markup):
    """The same reply_markup with every button's colour taken off."""
    rows = [[{k: v for k, v in b.items() if k != "style"} for b in row]
            for row in markup.get("inline_keyboard") or []]
    return dict(markup, inline_keyboard=rows) if "inline_keyboard" in markup else markup


def menu_keyboard():
    # Each thing in one place. The status is on the Keepawake screen, under
    # the hold it explains; the repository is chosen in Sclaude; a feature's
    # dev server and code-server folder are on its card.
    return [
        [{"text": t("menu.extend"), "callback_data": "menu_extend"},
         {"text": t("menu.sclaude"), "callback_data": "svc_sclaude"}],
        [{"text": t("menu.code"), "callback_data": "menu_code"},
         {"text": t("menu.chrome"), "callback_data": "menu_chrome"}],
        [{"text": t("menu.settings"), "callback_data": "menu_services"}],
    ]


# "Never sleep at all" is indefinite in words only: in the state it is an
# ordinary until_ts, merely a distant one. There is deliberately no separate
# "hold for ever" field — should_hold is duplicated in KeepAwake.ps1, and every
# new field would have to be created in two runtimes at once, at the risk of
# their diverging. A week is longer than any sensible session, and STALE_AFTER
# remains the insurance against a forgotten hold: a crashed WSL stops holding
# after fifteen minutes, however distant the deadline.
FOREVER_SECONDS = 7 * 24 * 3600


def host_name():
    # The machine's name in the menu header: the bot may have more than one
    # laptop, and the first thing to know before pressing "sleep" is which of
    # them will answer. We take the Windows machine's name (hostname in WSL
    # returns exactly that) rather than the node's name in the tailnet: they
    # have different names, and a person recognises their own hardware by the
    # first.
    try:
        import socket
        return socket.gethostname() or "keepawake"
    except Exception:
        return "keepawake"


def is_menu_button(text):
    # The keyboard below the input box was set once and labelled in the
    # language of that moment. The language may have changed since — Telegram
    # reports it in every update — while the person's old button stayed as it
    # was. So we compare against both variants rather than the current one.
    return text in STRINGS["menu.button"]


def menu_title():
    return t("menu.title", host=escape(host_name()))


def chat_menu(thread=0):
    """(text, keyboard) of the menu in the chat. The menu itself is the Mini
    App (webmenu.py); the chat offers the way there. While phone access is
    off the app cannot open, so the chat keeps what must work without it:
    the hold, and turning phone access on. In a feature's topic the app
    opens on that feature."""
    origin = gate_origin()
    if not origin:
        return t("menu.offline", host=escape(host_name())), [
            [{"text": t("menu.extend"), "callback_data": "menu_extend"}],
            [{"text": t("svc.phoneoff"), "callback_data": "phone_toggle"}]]
    key = topic_channel(thread)
    url = origin + "/__sclaude/menu" + (
        "?f=" + urllib.parse.quote(key, safe="") if key else "")
    return t("menu.inapp", host=escape(host_name())), [
        [{"text": t("menu.open"), "web_app": {"url": url}}]]


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
    text = t("awake.title", until=escape(local_for_lang(data.get("until_local") or "")))
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
    return awake_text() + "\n\n" + status_text()


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
        retire(bot, menu)
    retire(bot, prompt)
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


def phone_button(origin, label):
    # The Mini App, green so it reads apart from the laptop's button. Only
    # while phone access is on (Settings); off, there is none.
    return [{"text": t("chrome.phoneopen"), "style": "success",
             "web_app": {"url": "%s/__sclaude/tg?f=%s" % (origin, label)}}] if origin else []


def code_app_button(origin, folder=""):
    # code-server inside the Mini App, through the gate's /__code/ (an
    # experiment). Only while phone access is on and code-server is up: the
    # gate starts nothing.
    if not origin or not code_running():
        return []
    # Always a folder: without one code-server reopens whatever was open in
    # it last, not the repository the screen names (code_folder).
    folder = folder or repo_choice() or os.path.expanduser("~")
    path = "/__code/?folder=" + urllib.parse.quote(folder)
    return [{"text": t("code.app"), "style": "success", "web_app": {
        "url": "%s/__sclaude/tg?p=%s" % (origin, urllib.parse.quote(path, safe=""))}}]


def chrome_keyboard(config=None):
    # The laptop's browser and every feature at once. A feature's own
    # buttons — open, phone, start, stop — are on its card in its topic.
    browser_up = port_open(CHROME_PORT)
    origin = gate_origin(config)

    # The list of every feature first, laid out like a feature: a caption,
    # then where to open it. 🌐 is the laptop's Chrome at localhost:3000,
    # started if it is down; ⏹ closes that Chrome, and only while it runs.
    rows = [[{"text": t("chrome.all"), "callback_data": "noop"}]]
    first = [{"text": t("chrome.open"), "callback_data": "chrome_start"}] + phone_button(origin, "")
    if browser_up:
        first.append({"text": t("chrome.stopbrowser"), "callback_data": "chrome_stop"})
    rows.append(first)
    # A feature's own buttons — open, phone, start, stop — are on its card in
    # its topic now; here the browser and the list of every feature remain.
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


def services_keyboard():
    return [
        [{"text": t("svc.lang"), "callback_data": "svc_lang"},
         {"text": t("svc.docs"), "callback_data": "svc_docs"}],
        [{"text": t("svc.restart"), "callback_data": "svc_restart"}],
        # On and off in one button, its caption the current state.
        [{"text": t("svc.phoneon") if gate_origin(None, False) else t("svc.phoneoff"),
          "callback_data": "phone_toggle"}],
        [{"text": t("menu.back"), "callback_data": "menu_back"}],
    ]


def lang_keyboard():
    # We mark the current choice with a dot — the same as the selected
    # repository.
    data = read()
    pinned = bool(data.get("lang_pinned"))
    now = current()
    def mark(on, text):
        return ("● " if on else "") + text
    return [
        [{"text": mark(pinned and now == "ru", t("lang.ru")),
          "callback_data": "lang:ru"},
         {"text": mark(pinned and now == "en", t("lang.en")),
          "callback_data": "lang:en"}],
        [{"text": mark(not pinned, t("lang.auto")), "callback_data": "lang:auto"}],
        [{"text": t("menu.back"), "callback_data": "menu_services"}],
    ]


def lang_text():
    data = read()
    name = t("lang.name." + current())
    if data.get("lang_pinned"):
        now = name
    else:
        now = t("lang.auto.now", what=name)
    return t("lang.title", now=now)


def code_running():
    out = run("systemctl --user is-active code-server.service")
    return out.strip() == "active"


def code_url():
    # We take the address from the config rather than a constant: it is tied to
    # the address in the tailnet, and if that changes the message must change it
    # too.
    path = os.path.expanduser("~/.config/code-server/config.yaml")
    try:
        for line in open(path):
            if line.strip().startswith("bind-addr:"):
                return "http://" + line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "http://localhost:8080"


# The port sclaude-proxy holds (bin/sclaude-proxy): every feature is
# http://<feature>.localhost:3000 through it, and a bare localhost:3000 is the
# list of features. chrome-debug opens that by default.
DEV_PORT = 3000
CHROME_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
# Where sclaude registers each feature's tree for the proxy: one symlink per
# feature, the tree's .sclaude/local/feature/state.json holding its port.
DEV_REGISTRY = os.path.expanduser("~/.claude/sclaude/dev")


def dev_features():
    """[(label, worktree, port, running)] for every registered feature.

    Read the way the proxy reads it — the registry and each tree's state —
    so the card and the proxy cannot disagree about what exists."""
    out = []
    try:
        names = sorted(os.listdir(DEV_REGISTRY))
    except OSError:
        return out
    for name in names:
        link = os.path.join(DEV_REGISTRY, name)
        if name.startswith(".") or not os.path.islink(link):
            continue
        wt = os.path.realpath(link)
        try:
            with open(state_path(wt)) as fh:
                port = (json.load(fh).get("dev") or {}).get("port")
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(port, int):
            continue
        out.append((name, wt, port, port_open(port)))
    return out

# This much silence counts as "the person left without closing the session".
# The value must match IDLE_AFTER in bin/keepawake, which measures it.
IDLE_SECONDS_THRESHOLD = 3600

# The value with which the detector marks "no interactive sessions at all".
# Must match the placeholder in idle_seconds() from bin/keepawake.
IDLE_UNKNOWN = 999999


def port_open(port, host="127.0.0.1"):
    import socket
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def wsl_ip():
    # WSL's address in the Windows network. It changes on every restart of WSL,
    # so it is read afresh each time the card is shown rather than
    # remembered.
    out = run("ip -4 -o addr show eth0")
    for part in out.split():
        if part.count(".") == 3 and "/" in part:
            return part.split("/")[0]
    return ""


def json_in(out):
    """The JSON object in a command's output, None when there is none. run()
    gives stderr with stdout, and a warning beside the answer — tailscale's
    after an upgrade, before tailscaled restarts — is not a failed answer."""
    start = (out or "").find("{")
    if start < 0:
        return None
    try:
        found, _end = json.JSONDecoder().raw_decode(out[start:])
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def serve_config():
    """`tailscale serve status`, parsed; {} when it does not answer."""
    return json_in(run("tailscale serve status --json", timeout=10)) or {}


def phone_origin(config=None):
    """Where a phone opens features: the `tailscale serve` HTTPS name when it
    fronts the proxy's port, the node's tailnet address otherwise.

    The name is worth preferring, not merely nicer. The page opens on either,
    but only the name survives a sign-in: in development the app sends a person
    back to the address they came from, and Supabase Auth refuses to redirect
    to an IP whatever its allow-list says. HTTPS also makes the page a secure
    context, which push notifications need."""
    if config is None:
        config = serve_config()
    for hostport, web in (config.get("Web") or {}).items():
        handler = ((web or {}).get("Handlers") or {}).get("/") or {}
        if str(handler.get("Proxy", "")).rstrip("/").endswith(":%d" % DEV_PORT):
            host, _, port = hostport.rpartition(":")
            return "https://%s" % host if port == "443" else "https://%s:%s" % (host, port)
    # The node's address, from code-server's config as everywhere in this bot.
    host = code_url().split("//")[1].split(":")[0]
    return "http://%s:%d" % (host, DEV_PORT)


# The phone's entry from the internet, for a phone without Tailscale: the
# gate (`sclaude-proxy --gate`, socket-activated on 127.0.0.1:3001) behind
# `tailscale funnel` on :8443. The funnel stays on: Tailscale's relays take
# minutes to carry a funnel that has just been turned on — its name leaves the
# public DNS while it is off, and comes back only after a while (five minutes
# once) — and a phone that pressed the button met "connection closed" every time. What
# stands at the door instead is the gate, which lets in only the bot's owner.
GATE_PORT = 3001
GATE_LOCAL = "http://127.0.0.1:%d" % GATE_PORT
GATE_FUNNEL_PORT = 8443
FUNNEL_ON = "tailscale funnel --bg --https=%d %s" % (GATE_FUNNEL_PORT, GATE_LOCAL)
FUNNEL_OFF = "tailscale funnel --https=%d off" % GATE_FUNNEL_PORT


def phone_on():
    """Turn phone access on: (on, what the commands said). The gate's
    socket is started unless something already answers on its port — the
    gate itself, run by hand — which would make the socket fail to bind.
    On means the funnel is set up; the app opens once the address is
    published (gate_origin)."""
    PUBLISHED.update(host="", ok=False)
    start = "" if port_open(GATE_PORT) else "systemctl --user start sclaude-gate.socket && "
    out = run(start + FUNNEL_ON, timeout=60)
    with locked() as st:
        st["phone_on_at"] = int(time.time())
        st.pop("published", None)
    return bool(gate_origin(None, False)), out


# A funnel just turned on is not reachable at once: Tailscale publishes its
# name in public DNS only after a while (five minutes once), and a phone that
# asks before then is told the name does not exist — and keeps that answer for
# five minutes more. So nothing offers the app until the name is there: the
# chat says it is waiting, and changes that message when it is ready.
#
# The name is asked of the zone's own nameserver, which keeps no answer: a
# resolver asked too early would itself remember "no such name" for minutes.
# DNS over HTTPS stands in when that fails.
PUBLISHED = {"host": "", "at": 0.0, "ok": False, "since": 0.0}
# How often a name not yet published is asked again.
PUBLISH_RECHECK = 10
# Past this the app is offered anyway, and the log says so.
PUBLISH_WAIT_MAX = 900


def doh(name, rtype):
    """The answers of DNS over HTTPS for a name, as data strings."""
    url = "https://dns.google/resolve?name=%s&type=%s" % (urllib.parse.quote(name), rtype)
    with urllib.request.urlopen(url, timeout=3) as resp:
        data = json.load(resp)
    return [a.get("data", "") for a in data.get("Answer") or []]


def dns_addresses(server, name):
    """The A records the nameserver at server has for name: one question over
    UDP, no recursion asked."""
    import socket
    qid = os.urandom(2)
    query = (qid + b"\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
             + b"".join(bytes([len(p)]) + p.encode() for p in name.split("."))
             + b"\x00\x00\x01\x00\x01")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.sendto(query, (server, 53))
        data = sock.recv(4096)
    if data[:2] != qid or len(data) < 12:
        raise OSError("not the answer to this question")
    if data[3] & 0x0F:
        return []

    def skip_name(i):
        while data[i]:
            if data[i] & 0xC0 == 0xC0:
                return i + 2
            i += data[i] + 1
        return i + 1

    i = skip_name(12) + 4
    found = []
    for _ in range(int.from_bytes(data[6:8], "big")):
        i = skip_name(i)
        rtype, rlen = int.from_bytes(data[i:i + 2], "big"), int.from_bytes(data[i + 8:i + 10], "big")
        i += 10
        if rtype == 1 and rlen == 4:
            found.append(".".join(str(b) for b in data[i:i + 4]))
        i += rlen
    return found


def funnel_answers(host, port, address):
    """True when the funnel at address carries a request to the gate: TLS
    under the funnel's name, and an HTTP answer back. A relay that has not
    taken the funnel up yet accepts the connection and drops the handshake."""
    import socket
    import ssl
    try:
        context = ssl.create_default_context()
        with socket.create_connection((address, port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                tls.settimeout(5)
                tls.sendall(("GET /__sclaude/menu HTTP/1.1\r\nHost: %s:%d\r\n"
                             "Connection: close\r\n\r\n" % (host, port)).encode())
                return tls.recv(16).startswith(b"HTTP/")
    except (OSError, ssl.SSLError):
        return False


def name_published(host, port=None):
    """Whether a phone can reach the funnel now: its name in public DNS, and
    the relay at that address carrying it. The name alone is not enough — a
    funnel off for a few minutes keeps its name, and the relay takes a minute
    or more to carry it again."""
    import socket
    port = port or GATE_FUNNEL_PORT
    zone = ".".join(host.split(".")[-2:])
    try:
        server = socket.gethostbyname(doh(zone, "NS")[0].rstrip("."))
        addresses = dns_addresses(server, host)
    except (OSError, ValueError, IndexError):
        addresses = []
    if not addresses:
        # No answer from the zone's own server — an error, or a referral or
        # an empty answer, which raise nothing: a public resolver then.
        try:
            addresses = [a for a in doh(host, "A") if a.count(".") == 3]
        except (OSError, ValueError):
            addresses = []
    return any(funnel_answers(host, port, a) for a in addresses[:2])


# The loop's probe, run in a thread: {host: None while running, else the
# answer not yet taken}. Off in tests, which want the answer at once.
PROBE = {}
PROBE_ASYNC = True


def probe_published(host):
    """The loop's probe, in its thread. Whatever it raises is a "not yet":
    an answer never left would hold the wait on "still probing" for good."""
    try:
        ok = name_published(host)
    except Exception as exc:
        log.warning("the probe of %s failed: %s", host, exc)
        ok = False
    PROBE[host] = ok


def published(host, look=False):
    """Whether a phone can find the funnel's name: asked again every
    PUBLISH_RECHECK seconds until it can, then remembered while it lasts.
    Only the loop asks (look): a lookup is seconds of network, and a button
    or a menu takes the loop's last answer — the first one in a process
    excepted, which has none to take."""
    if not look:
        # The loop's answer, from the state where it leaves it: the gate
        # serving the menu page is another process, and its own first answer
        # would otherwise stand for the life of that process.
        shared = read().get("published") or {}
        if shared.get("host") == host:
            return bool(shared.get("ok"))
    if PUBLISHED["host"] == host and PUBLISHED["ok"]:
        return True
    now = time.time()
    if PUBLISHED["host"] == host and (not look or now - PUBLISHED["at"] < PUBLISH_RECHECK):
        return False
    if look and PROBE_ASYNC:
        # Off the loop: the probes take up to some fifteen seconds, and
        # every press would wait on them. The answer is taken on a later turn.
        # Meanwhile the last answer stands — the previous process's too, so
        # a restart does not read as access turned off for a turn.
        shared = read().get("published") or {}
        meanwhile = shared.get("host") == host and bool(shared.get("ok"))
        if host not in PROBE:
            PROBE[host] = None
            threading.Thread(target=probe_published, args=(host,), daemon=True).start()
            return meanwhile
        if PROBE[host] is None:
            return meanwhile          # still probing
        ok = PROBE.pop(host)
    else:
        ok = name_published(host)
    # Counted from the wait the chat showed, or else from this process's
    # first look that found the name not yet reachable — access turned on
    # from the terminal shows no wait, and would otherwise never be offered.
    if PUBLISHED["host"] != host or PUBLISHED["ok"]:
        PUBLISHED["since"] = now
    since = (read().get("phone_wait") or {}).get("since") or PUBLISHED["since"]
    if not ok and since and now - since > PUBLISH_WAIT_MAX:
        log.warning("%s is still not in public DNS after %d s: offering the app anyway",
                    host, PUBLISH_WAIT_MAX)
        ok = True
    PUBLISHED.update(host=host, at=now, ok=ok)
    if look:
        with locked() as st:
            st["published"] = {"host": host, "ok": ok}
    return ok


def gate_origin(config=None, ready=True, look=False):
    """https://<node>.<tailnet>.ts.net:8443 while the funnel carries the gate,
    "" while it does not — read from Tailscale, never remembered. With
    ready, also "" until a phone can find the name (published); without,
    the funnel's set-up alone counts, as for turning it off."""
    if config is None:
        config = serve_config()
    for hostport, allowed in (config.get("AllowFunnel") or {}).items():
        host, _, port = hostport.rpartition(":")
        if not allowed or port != str(GATE_FUNNEL_PORT):
            continue
        web = (config.get("Web") or {}).get(hostport) or {}
        proxy = str((((web.get("Handlers") or {}).get("/")) or {}).get("Proxy", ""))
        if proxy.rstrip("/").endswith(":3001"):
            if ready and not published(host, look):
                return ""
            return "https://%s:%s" % (host, port)
    PUBLISHED.update(host="", ok=False)
    # The funnel is off: the loop's last answer goes too, or a funnel set up
    # again by hand would read as published before it is.
    if read().get("published"):
        with locked() as st:
            st.pop("published", None)
    return ""


def proxy_start(label):
    """Ask the proxy to start the feature now — for ▶️, and for 📱 while the
    phone is still opening, where the first request would, but later. It goes
    through the proxy rather than `sclaude dev` so that the proxy knows it is
    starting and shows that page meanwhile. Not followed: the answer is
    a redirect to <label>.localhost, which is nothing to fetch from here."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", DEV_PORT, timeout=5)
        conn.request("GET", "/__sclaude/start?f=" + urllib.parse.quote(label))
        conn.getresponse().read()
        conn.close()
    except (OSError, http.client.HTTPException):
        pass


def chrome_screen():
    """(text, keyboard) of the Chrome screen, from one look at tailscale."""
    config = serve_config()
    return chrome_text(config), chrome_keyboard(config)


def chrome_text(config=None):
    # The laptop's browser and the proxy it opens features through. Each
    # feature's addresses and dev server are on its card, and phone access
    # in Settings. config is kept for the callers that look at tailscale once.
    state_label = t("chrome.up") if port_open(CHROME_PORT) else t("chrome.down")
    proxy_label = t("chrome.proxyup") if port_open(DEV_PORT) else t("chrome.proxydown")
    return t("chrome.title", state=state_label, proxy=proxy_label, port=CHROME_PORT)


# True while a screen is drawn for the Mini App (webmenu.py). There the
# tailnet's addresses lead nowhere — the phone has no Tailscale — and the
# gate's buttons on the same screen stand in for them.
ON_PAGE = False


def code_folder():
    # Which directory the server will open at its next start — the same choice
    # as sclaude's: keeping two different "current projects" would confuse a
    # person who has switched one and expects the second to have switched
    # too.
    choice = repo_choice()
    return os.path.basename(choice) if choice else "~"


def code_password():
    """code-server's password from its config, or ""."""
    path = os.path.expanduser("~/.config/code-server/config.yaml")
    try:
        for line in open(path):
            if line.strip().startswith("password:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def code_keyboard(folder=""):
    # folder: the worktree the 📲 button opens, when the menu page stands on
    # a feature.
    running = code_running()
    row = []
    if running:
        row.append({"text": t("code.restart"), "callback_data": "code_restart"})
        row.append({"text": t("code.stop"), "callback_data": "code_stop"})
    else:
        row.append({"text": t("code.start"), "callback_data": "code_start"})
    rows = [row]
    app = code_app_button(gate_origin(), folder)
    if app:
        rows.append(app)
    return rows + [[{"text": t("menu.back"), "callback_data": "menu_back"}]]


def code_text(folder_name=""):
    state_label = (t("code.running") if code_running()
                   else t("code.stoppedpage") if ON_PAGE else t("code.stopped"))
    # There are two addresses, and that is not duplication. Tailscale runs
    # inside WSL, so the tailnet address lives on its interface: a phone reaches
    # it through the tunnel, while Windows itself does not — it is not in the
    # tailnet. For Windows there is localhost, which WSL2 forwards into Windows
    # by itself.
    # We do not put the password here: it would settle in the chat's history
    # and on Telegram's servers for ever, while the browser remembers it anyway
    # after the first login.
    # 127.0.0.1 rather than localhost: Telegram makes a link of what looks like
    # a domain or an IP, and localhost does not qualify — it stays text even
    # inside an explicit <a href>, which is additionally rejected with a 400
    # error. To the Windows browser the addresses are equivalent, and only this
    # one is clickable.
    if ON_PAGE:
        # The page is not kept in the chat's history, and is let in for the
        # owner only: the password can be shown where it is typed.
        pw = code_password()
        return t("code.titlepage", state=state_label,
                 folder=t("code.folder", name=escape(folder_name or code_folder())),
                 password=t("code.password", pw=escape(pw)) if pw else t("code.nopassword"))
    return t("code.title", state=state_label,
             folder=t("code.folder", name=escape(code_folder())),
             url=code_url(), local="http://127.0.0.1:8080")


def warn_keyboard(until_ts):
    # The deadline stamp inside callback_data is what tells a fresh press from
    # a press on yesterday's message. Without it the "Extend" button from an old
    # notification would extend the hold at an arbitrary moment the next day.
    return [[
        {"text": t("sleep.extend"), "callback_data": "extend:%d" % until_ts},
        {"text": t("sleep.let"), "callback_data": "sleep:%d" % until_ts},
    ]]


# --- commands ---------------------------------------------------------------

# ~/.local/bin, where keepawake, chrome-debug and sclaude live, is not in the
# daemon's PATH: systemd gives a bare system PATH rather than the one an
# interactive shell assembles from ~/.profile. From the terminal the commands
# were found, from under the service they were not, and every button answered
# "not found".
LOCAL_BIN = os.path.expanduser("~/.local/bin")


def nvm_bin():
    # npm and node live in the directory of nvm's active version, which is not
    # in the service's PATH: an interactive shell assembles it from
    # ~/.nvm/nvm.sh. Without this `sclaude dev` died with "setsid: failed to
    # execute npm".
    #
    # We read the version from ~/.nvm/alias/default rather than hardcoding it:
    # otherwise updating Node would quietly break the button until the next edit
    # of the code.
    base = os.path.expanduser("~/.nvm/versions/node")
    alias = os.path.expanduser("~/.nvm/alias/default")
    try:
        want = open(alias).read().strip()
    except OSError:
        want = ""
    try:
        candidates = os.listdir(base)
    except OSError:
        return ""
    if not candidates:
        return ""

    def version_key(name):
        # By numbers rather than by letters: sorted() puts "v9.11.2" above
        # "v24.20.0", and the fallback branch would silently pick an ancient
        # Node. That branch is not hypothetical — here alias/default equals
        # "lts/*", which matches no directory by prefix.
        parts = []
        for chunk in name.lstrip("v").split("."):
            parts.append(int(chunk) if chunk.isdigit() else 0)
        return parts

    # We resolve "lts/*" and other aliases through ~/.nvm/alias/, otherwise
    # they would never match a directory name.
    if want.startswith("lts/"):
        try:
            want = open(os.path.expanduser("~/.nvm/alias/" + want)).read().strip()
        except OSError:
            want = ""

    for name in sorted(candidates, key=version_key, reverse=True):
        if want and (name == want or name.lstrip("v").startswith(want.lstrip("v"))):
            return os.path.join(base, name, "bin")
    return os.path.join(base, max(candidates, key=version_key), "bin")


def run(cmd, timeout=25):
    # The bot's commands are short and free of dialogue; anything longer has no
    # place here.
    env = dict(os.environ)
    parts = [LOCAL_BIN]
    nvm = nvm_bin()
    if nvm:
        parts.append(nvm)
    env["PATH"] = ":".join(parts) + ":" + env.get("PATH", "")
    # In a session of its own, and the whole group killed on a timeout:
    # subprocess.run kills only the shell it started, and whatever the shell
    # was running (`cd … && sclaude status`) lived on as an orphan, still
    # counted as "another sclaude" by every later run.
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env,
                                start_new_session=True)
    except Exception as exc:
        return t("cmd.error", err=exc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return t("cmd.timeout", sec=timeout)
    except Exception as exc:
        return t("cmd.error", err=exc)
    text = (stdout or "") + (stderr or "")
    return text.strip() or t("cmd.empty")


def uptime_of(pid):
    try:
        with open("/proc/%d/stat" % pid) as fh:
            # Field 22 (starttime) is in ticks since the system booted. The
            # command's name in brackets may contain spaces, so we cut at ")".
            fields = fh.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])
        hz = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as fh:
            up = float(fh.read().split()[0])
        return max(0, int(up - ticks / hz))
    except Exception:
        return 0


def report_restart(bot):
    # After a restart, report into the same message that the daemon is alive
    # again. It is a new process that does this, so it reads the errand from the
    # state. Returns True if the report happened: the caller judges by that
    # whether to write to the chat for the keyboard's sake as well.
    data = read()
    mid = data.get("restart_notify") or 0
    if not mid:
        return False
    old = data.get("restart_from_pid") or 0
    if old == os.getpid():
        return False    # the same process: the restart has not happened yet
    with locked() as st:
        st["restart_notify"] = 0
        st["restart_from_pid"] = 0
    if data.get("restart_page"):
        # Asked for from the menu page: the line in the chat is its trace,
        # and a Settings menu under it would be a second menu to keep true.
        with locked() as st:
            st["restart_page"] = False
        bot.edit(mid, "📱 " + t("svc.restarted"))
    else:
        bot.edit(mid, t("svc.restarted"), services_keyboard())
    log.info("reported the restart in message %s", mid)
    # Editing an old message does not set the keyboard below the input box:
    # editMessageText's reply_markup is inline only. We set it separately.
    ensure_anchor(bot)
    return True


def ensure_anchor(bot):
    # We set the keyboard once per chat rather than at every start: the daemon
    # restarts both by a button in the menu and with the system, and an "I have
    # started" on every restart is noise in the chat, which the bot was built not
    # to create. We keep the mark in the state alongside everything else that
    # survives a restart.
    if read().get("anchor_lang") == current():
        return
    # In two messages, because a message has one reply_markup: the first
    # carries the keyboard below the input box, the second the menu itself.
    # Showing a bare header without buttons and making someone press "Menu" for
    # what is already on the screen is an extra step in exactly the place where
    # the person came for the menu anyway.
    bot.anchor(t("anchor.hint"))
    # A screen like any other: what it offers follows phone access
    # (redraw_screens).
    msg = bot.send(*chat_menu())
    if msg:
        Handler(bot).adopt(msg)
    with locked() as st:
        st["anchor_lang"] = current()
    log.info("the menu keyboard is set, language=%s", current())


def relabel_anchor(bot):
    # Relabel the keyboard after a change of language — in one message rather
    # than two: the person can see the menu anyway, they have just pressed a
    # button in it. It cannot be replaced silently, a keyboard only arrives with
    # a message.
    if read().get("anchor_lang") == current():
        return
    bot.anchor(t("anchor.hint"))
    with locked() as st:
        st["anchor_lang"] = current()
    log.info("the keyboard was relabelled, language=%s", current())


# The repositories whose features the bot can show. We search once per call:
# there are not many directories in $HOME, and projects do not lie deeper than
# the first level.
def known_repos():
    home = os.path.expanduser("~")
    found = []
    try:
        names = sorted(os.listdir(home))
    except OSError:
        return found
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(home, name)
        if os.path.isdir(os.path.join(path, ".git")):
            found.append(path)
    return found


def repo_choice():
    # The choice lives in the state: the daemon survives restarts, and it has
    # nowhere else to remember which project the person looked at last.
    data = read()
    choice = data.get("sclaude_repo") or ""
    # The repository may have been renamed or deleted — the choice is then
    # invalid.
    if choice and os.path.isdir(os.path.join(choice, ".git")):
        return choice
    return ""


def repo_path(name):
    # Only a name from the list of known repositories. The name arrives in
    # callback_data and, although shlex.quote below stops it from executing as a
    # command, relying on escaping alone is unwise: checking against the list
    # closes off both directory traversal ("../..") and any future places this
    # name may end up in.
    for repo in known_repos():
        if os.path.basename(repo) == name:
            return repo
    return ""


def features_of_name(name):
    path = repo_path(name)
    if not path:
        return [], ""
    return features_of(path)


def features_of(repo):
    # A repository's features as parsed rows of the sclaude status table. We
    # parse them ourselves, because the menu's second level is buttons onto
    # features rather than text.
    out = strip_ansi(run("cd %s && sclaude status" % shlex.quote(repo)))
    # git complains on stderr about repositories without origin/main — that has
    # nothing to do with features and must not get into the report.
    out = "\n".join(ln for ln in out.split("\n")
                    if not ln.startswith("fatal:")).strip()
    if not out or "No features in progress" in out:
        return [], out
    rows = []
    for line in out.split("\n"):
        line = line.rstrip()
        if line.startswith("FEATURE"):
            continue          # a table header will not do as a button
        if not line:
            # A blank line ends the feature table: below it sclaude prints the
            # branch breakdown ("Branches in progress"), and its rows are not
            # features. Without this a branch arrived in the menu as a separate
            # button leading nowhere.
            break
        # We split on two spaces — that is how align_columns separates the
        # columns. One will not do: a step's name is sometimes two words ("3/6
        # pull request"), and splitting on spaces returned "3/6 pull" as the step
        # and "request" as the path to the worktree. That is exactly how it
        # looked in the card.
        parts = [c for c in re.split(r" {2,}", line.strip()) if c]
        if len(parts) >= 2:
            # The columns: name, step, worktree. The path is not needed on the
            # button — it is long and eats the whole width on a phone, while the
            # table is there in full in the text below the buttons.
            wt = parts[2] if len(parts) > 2 else ""
            if wt and closing(wt):
                continue
            rows.append((parts[0], parts[1], wt))
    return rows, out


def closing(wt):
    """Whether a feature's worktree is being removed: stop_dev marks it before
    the minute git takes to delete it, and from then on the feature is gone
    for the menu — a card offered then leads into a tree half deleted."""
    return os.path.exists(os.path.join(wt, ".sclaude", "local", "feature", CLOSING_MARK))


def docs_keyboard():
    # The order runs from "what is this" to "how to fix it": someone opening
    # the docs for the first time does not start with the system's design.
    return [
        [{"text": t("docs.why"), "callback_data": "doc:why"},
         {"text": t("docs.usage"), "callback_data": "doc:usage"}],
        [{"text": t("docs.arch"), "callback_data": "doc:arch"},
         {"text": t("docs.holders"), "callback_data": "doc:holders"}],
        [{"text": t("docs.install"), "callback_data": "doc:install"},
         {"text": t("docs.files"), "callback_data": "doc:files"}],
        [{"text": t("docs.trouble"), "callback_data": "doc:trouble"}],
        [{"text": t("menu.back"), "callback_data": "menu_services"}],
    ]


def repos_keyboard():
    # The first level: repositories. There is no "all at once" item here — a
    # report on all of them almost always came down to a single "no features"
    # line, whereas usually one project is wanted, and it is that one that has
    # to be remembered between visits.
    rows = []
    chosen = repo_choice()
    for repo in known_repos():
        name = os.path.basename(repo)
        mark = "● " if chosen == repo else ""
        rows.append([{"text": mark + name, "callback_data": "repo:" + name}])
    # To the main menu rather than to Settings: people arrive here both by the
    # Sclaude button in the main menu and from Settings, and a "back" into a
    # branch the person never opened is the worse of the two options.
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


# --- sclaude's question-answer channel ---------------------------------------
#
# The orchestrator lays the question out as a file and waits for an answer from
# two places at once: the terminal where it was asked, and here. Whoever answers
# first has answered — which is why a step begun at the laptop continues from a
# phone without a restart, and the other way round.
#
# The channels live in the repository's .git/sclaude/: one for all worktrees, so
# a question is found even before the feature is created. The repository's own
# channel is that directory; each feature in progress has its own below it, in
# ask/<slug>/, so that features running in parallel can all ask at once. The
# format is in sclaude/lib/io.sh (ask_channel).
#
# A channel is named in the state by its key: the repository's name for the
# repository's channel, "<repository>/<slug>" for a feature's.


def ask_dir(repo):
    return os.path.join(repo, ".git", "sclaude")


def ask_channels(repo):
    """[(slug, directory)] — the repository's channel first, slug empty."""
    root = ask_dir(repo)
    found = [("", root)]
    try:
        names = sorted(os.listdir(os.path.join(root, "ask")))
    except OSError:
        return found
    for slug in names:
        path = os.path.join(root, "ask", slug)
        if not slug.startswith(".") and os.path.isdir(path):
            found.append((slug, path))
    return found


def channel_key(name, slug):
    return "%s/%s" % (name, slug) if slug else name


def split_key(key):
    name, _, slug = key.partition("/")
    return name, slug


def channel_dir(key):
    # The directory behind a key, or "" when the repository is not known.
    name, slug = split_key(key)
    repo = repo_path(name)
    if not repo:
        return ""
    return os.path.join(ask_dir(repo), "ask", slug) if slug else ask_dir(repo)


def pending_ask(channel):
    # The channel's open question, or None. We read without locks: the file
    # is written through mv, that is it appears whole. JSON that will not parse
    # means "it is being rewritten right now" — we will come back on the next
    # turn.
    path = os.path.join(channel, "ask.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("prompt"):
        return None
    # A question outlives the one who asked it: sclaude was killed with Ctrl-C,
    # an ssh session dropped, the power went out — the file stays lying there.
    # Showing such a question means offering to answer where nobody is
    # listening: the answer lands in the channel and stays there for ever, while
    # the person waits for the step to have moved.
    #
    # So we ask whether the owner is alive. The orchestrator puts its own pid
    # into the question itself — for exactly this. Signal 0 does nothing, it only
    # checks that the process exists and is ours.
    pid = data.get("pid") or 0
    if pid:
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError, TypeError):
            log.info("an orphaned question in %s (pid %s is dead) — removing it",
                     channel, pid)
            try:
                os.unlink(path)
            except OSError:
                pass
            return None
    return data


# The labels of the options that mean a refusal, from i18n: "Go back" in the
# action list, "none, go back" in the feature picker. We match on the start of
# the string and in both languages — the list is drawn in English, but
# translations of it are still to come.
BACK_OPTIONS = tuple(text for key in ("option.back", "option.none")
                     for text in reversed(STRINGS[key]))


def is_back_option(label):
    if not label:
        return False
    low = label.strip().lower().lstrip("‹ ").strip()
    return any(low.startswith(b) for b in BACK_OPTIONS)


# The replies is_yes and is_no take in sclaude/lib/ui.sh, in any case.
YES_WORDS = ("y", "yes")
NO_WORDS = ("n", "no")


def option_in_range(question, reply):
    # Whether a reply to a pick:N question is one ask_once takes as an answer:
    # one of its N options in ASCII digits (int() would also take "+2", "1_0"
    # and other scripts' digits).
    reply = str(reply).strip()
    return bool(re.fullmatch(r"[0-9]+", reply)) and 1 <= int(reply) <= _pick_n(question)


def option_label(options, reply):
    options = options or []
    try:
        i = int(str(reply).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= i <= len(options):
        return str(options[i - 1])
    return ""


def answer_ask(channel, reply, want=None):
    # The answer to the orchestrator. We write through a temporary file and
    # rename: the reading side must not see half an answer.
    #
    # Returns False if the question is gone — it was answered in the terminal
    # while the person was looking at the buttons. Staying silent here will not
    # do: otherwise it is unclear why the press changed nothing.
    #
    # The answer carries the id of the question it answers. Without it an answer
    # is a bare "y" that fits any question, and the check above does not make it
    # one: between it and os.replace the terminal can answer, the question can
    # close and the next one can open. That window cost a worktree — "n" to
    # "Ship to production?" was still travelling when "Remove all of it?" was
    # asked, and the orchestrator took the stale reply for an answer to it. The
    # reading side compares the ids and drops what was meant for another
    # question.
    #
    # want: the id of the question the caller checked. The question read here
    # can already be the next one, and the answer is then refused rather than
    # stamped with that one's id.
    question = pending_ask(channel)
    if not question or (want and (question.get("id") or "") != want):
        return False
    d = channel
    tmp = os.path.join(d, "answer.json.%d" % os.getpid())
    try:
        os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"reply": reply, "id": question.get("id") or ""},
                      fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(d, "answer.json"))
    except OSError as exc:
        log.warning("the answer was not written to the channel: %s", exc)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


# --- what happens to a question's message ------------------------------------
#
# A question's message must not outlive the question with its buttons still on
# it. Once the question closes, the message becomes its answer — whether it was
# answered here, in the terminal, or by text — or, when nobody answered (the
# session died, the reply was refused and the question asked again), it is
# deleted. The state remembers which message shows which question under
# "ask_shown": the repository's name → the question's stamp, the message id, and
# what is needed to write the answer once the question itself is gone.
#
# How the question ended is told by the orchestrator in closed/<id>.json (see
# ask_closed in sclaude/lib/io.sh).

CLOSED_DIR = "closed"

# The question's prompt in its answered message. The context is not repeated
# there: it explained the question, and the answer no longer needs it.
ASK_PROMPT_MAX = 300


def closed_asks(channel):
    # The records of closed questions: id → (path, record).
    d = os.path.join(channel, CLOSED_DIR)
    found = {}
    try:
        names = os.listdir(d)
    except OSError:
        return found
    for name in names:
        # A leading dot is a record still being written.
        if name.startswith(".") or not name.endswith(".json"):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("id"):
            found[record["id"]] = (path, record)
    return found


def shown_asks():
    # Before the message id was kept the value was the bare stamp. Such a
    # question is still known as shown — it must not be sent twice — but its
    # message cannot be reached.
    found = {}
    for name, value in (read().get("ask_shown") or {}).items():
        found[name] = value if isinstance(value, dict) \
            else {"id": value, "msg": 0, "legacy": True}
    return found


# Where the message showing a channel's question is remembered. A feature's
# keeps it in the feature's record in its worktree (load_record), with its
# topic. The repository's own channel keeps it in the daemon's state
# ("ask_shown"), and so does a feature channel with no worktree — one removed by
# hand while a question was open — since otherwise the question would be sent
# again on every turn.

def in_worktree(key, repo=None):
    # repo when the caller has it: finding it again is a scan of $HOME.
    name, slug = split_key(key)
    if slug and repo is None:
        repo = repo_path(name)
    return (repo, slug) if slug and repo and feature_dir(repo, slug) else (None, None)


def get_shown(key, repo=None):
    repo, slug = in_worktree(key, repo)
    if repo:
        return load_record(repo, slug).get("shown") or None
    return shown_asks().get(key)


def put_shown(key, entry, repo=None):
    # entry None forgets the channel's message.
    repo, slug = in_worktree(key, repo)
    if repo:
        record = load_record(repo, slug)
        if entry:
            record["shown"] = entry
        else:
            record.pop("shown", None)
        save_record(repo, slug, record)
        return
    with locked() as st:
        shown = st.get("ask_shown") or {}
        if entry:
            shown[key] = entry
        else:
            shown.pop(key, None)
        st["ask_shown"] = shown


def repo_keys(name, repo=None):
    """Every channel key of the repository: its own and its features'."""
    repo = repo or repo_path(name)
    if not repo:
        return [name]
    return [channel_key(name, slug) for slug, _ in ask_channels(repo)]


def forget_ask(key, message_id, repo=None):
    # The question's message has been dealt with by whoever is calling: it was
    # edited into its answer here. The stamp stays — the question lingers in
    # the channel for up to a second, and without the stamp the next turn would
    # send it again — only the message is let go. Returns the entry, or None
    # when this message no longer shows the channel's question.
    entry = get_shown(key, repo)
    if not isinstance(entry, dict) or not message_id \
            or entry.get("msg") != message_id:
        return None
    put_shown(key, dict(entry, msg=0, answered=message_id), repo)
    return entry


def answered_text(repo_name, question, reply, source=""):
    # The question and the answer it got, for the question's own message.
    # A number is shown as the option it chose and y/n as the buttons say it:
    # "3" says nothing a day later.
    question = question or {}
    reply = str(reply or "").strip()
    # The yes/no buttons' labels carry their own mark (✅ / ❌); any other
    # answer gets the ✅ of "answered".
    shown = option_label(question.get("options"), reply)
    marked = False
    if not shown and (question.get("form") or "").startswith("yn"):
        if reply.lower() in YES_WORDS:
            shown, marked = t("ask.yes"), True
        elif reply.lower() in NO_WORDS:
            shown, marked = t("ask.no"), True
    prompt = clip(strip_ansi(question.get("prompt") or "").strip(), ASK_PROMPT_MAX)
    text = t("ask.answered", repo=escape(repo_name), prompt=escape(prompt),
             reply=escape(shown or reply or "—") if marked
             else "✅ " + escape(shown or reply or "—"))
    if source in ("tty", "stdin"):
        text += "\n<i>%s</i>" % t("ask.by.terminal")
    # What was printed before the question is what happened on the laptop;
    # it stays, folded, rather than going with the buttons.
    context = strip_ansi(question.get("context") or "").strip()
    if context:
        text += "\n<blockquote expandable>%s</blockquote>" % escape(clip(context, ANSWER_CONTEXT_MAX))
    return text


# How much of a question's context its answered message keeps.
ANSWER_CONTEXT_MAX = 1500


def settle_ask(bot, name, entry, record):
    # The question in entry has closed: its message becomes the answer, or
    # goes. An edit makes no sound, so a question that went out silently is
    # answered silently too.
    msg = entry.get("msg") or 0
    if not msg:
        return
    if record and record.get("reply") is not None:
        bot.edit(msg, answered_text(name, entry, record.get("reply"),
                                    record.get("from") or ""))
    else:
        retire(bot, msg)


def ask_keyboard(repo_name, question):
    # Buttons by the answer's form, which the question itself declared (see ask
    # in ui.sh). There is no need to guess from the prompt's text: the caller
    # passes the form, and it arrives in the channel next to the question.
    form = (question.get("form") or "").strip()
    if form.startswith("yn"):
        # No first, so the button under a blind thumb is the one that
        # changes nothing. A yes/no question has no default any more (see ask
        # in ui.sh); "yn:yes" from an older sclaude gets the same order.
        yes = {"text": t("ask.yes"), "callback_data": "answer:%s:y" % repo_name}
        no = {"text": t("ask.no"), "callback_data": "answer:%s:n" % repo_name}
        return [[no, yes]]
    if form.startswith("pick:"):
        try:
            n = int(form.split(":", 1)[1])
        except ValueError:
            n = 0
        # The options' labels, if the question passed them (see ask_publish in
        # io.sh). With them a button says what it will do; without them, only
        # its number. The difference is not cosmetic: among the options there is
        # sometimes "drop the feature", and there is nothing to press blindly
        # there.
        options = question.get("options") or []

        # The ceiling differs for labelled and unlabelled buttons, and that is
        # not inconsistency but two different things.
        #
        # Eight is the limit for digits: they have to be checked against the
        # list in the text above the buttons, and by the ninth that check costs
        # more than typing the number by hand. A labelled button forces no
        # checking, it reads by itself, and one per line three times as many are
        # read comfortably.
        #
        # Verified in the field: the list of actions on a feature is nine
        # options, and with the old shared threshold it got no buttons at all —
        # the very thing it was all started for. Twenty-four leaves room both
        # beyond that and beyond the task list in pick_start, which stays text
        # (fifty-odd lines there).
        if 1 <= n <= 24 and len(options) == n:
            rows = []
            for i, label in enumerate(options, 1):
                text = strip_ansi(str(label)).strip()
                # An empty label is no label: better a number than an empty
                # button with nothing for the eye to land on.
                # We cut the tail rather than the middle as clip does: an
                # option's label carries its meaning at the start, and
                # "Drop the fea…" is clearer than
                # «Drop…ture».
                text = clip_bytes(text, 60)
                rows.append([{"text": text or str(i),
                              "callback_data": "answer:%s:%d"
                                               % (repo_name, i)}])
            return rows

        # Unlabelled ones are digits only, and only while they can be taken in
        # at a glance.
        if 1 <= n <= 8:
            rows, row = [], []
            for i in range(1, n + 1):
                row.append({"text": str(i),
                            "callback_data": "answer:%s:%d" % (repo_name, i)})
                if len(row) == 4:
                    rows.append(row); row = []
            if row:
                rows.append(row)
            return rows
    return []


# How much context we show above the question. Telegram's ceiling is 4096 bytes
# per message, and exceeding it is not a truncation but a refusal with a 400
# error: the question would not arrive at all, the step would stall, and the
# reason would not be visible from a phone. So we cut it ourselves, leaving room
# for the question itself and the markup.
ASK_CONTEXT_MAX = 2000


def clip(text, limit):
    # We cut the middle rather than the tail: both ends of a long output matter
    # — the start says what is going on, and the last lines stand right above
    # the question and most often are its reason.
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return text[:head] + "\n…\n" + text[-tail:]


# A numbered list's line: "  3)  Deploy a preview   this branch on…". Such lines
# are printed by align_columns, and in the terminal they are the list one chooses
# from. Next to labelled buttons they are the same list a second time.
NUMBERED = re.compile(r"^\s*\d+\)\s")


def clip_bytes(text, limit):
    # Telegram's ceiling on a button's text is in bytes, not characters.
    # Counting in characters works exactly up to the first non-ASCII one: 59
    # characters is 110 bytes, twice the ceiling. The labels are English today,
    # but BACK_OPTIONS already matches Russian, and translations of the list are
    # still to come.
    #
    # We cut by code points rather than by slicing bytes: a slice tears a
    # multi-byte character in half and hands back a broken string.
    if len(text.encode("utf-8")) <= limit:
        return text
    out = ""
    # -3 for the ellipsis: in UTF-8 it takes three bytes.
    for ch in text:
        if len((out + ch).encode("utf-8")) > limit - 3:
            break
        out += ch
    return out + "…"


def _pick_n(question):
    # How many options the form declared. Not a number means not a choice
    # either: there is then nothing to compare the label list's length against,
    # and zero honestly will not match.
    form = (question.get("form") or "").strip()
    if not form.startswith("pick:"):
        return -1
    try:
        return int(form.split(":", 1)[1])
    except ValueError:
        return -1


def ask_text(repo_name, question, in_topic=False, slug=""):
    body = ""

    # A question about a particular feature is shown with its card — the very
    # one that used to open on pressing a feature: links to the issue and the
    # PR, the step, the worktree, the session's state. There is nothing in the
    # orchestrator to assemble that with — whether the session is alive is known
    # to the bot, not to it — so the orchestrator only names the feature (the
    # feature field, see ask_publish in io.sh) and we build the card here.
    #
    # The usual "<repository> is asking" line is then unnecessary: the card starts
    # with the repository's and the feature's name, and repeating them means
    # pushing the buttons further down.
    # In the feature's topic the card is already there, just above.
    # slug is the channel's: a feature's question sent to the main chat for
    # want of a topic names its feature too.
    slug = "" if in_topic else ((question.get("feature") or "").strip() or slug)
    if slug:
        body += feature_card(repo_name, slug) + "\n\n"

    context = (question.get("context") or "").strip()
    # When the buttons are labelled, the numbered list above them is
    # redundant: it repeats them in digits and pushes down the very thing the
    # context is attached for — the lines that explain the question. We remove
    # the list specifically, not the whole context: above the action list stands
    # the line with the issue and the PR, and it is needed precisely because the
    # feature's card has stopped being a stop along the way.
    #
    # Without buttons the list stays: the answer is then a number, and there
    # would be nothing to check it against if the list were removed.
    #
    # Labelled ones, not just any: numeric buttons without the list are
    # meaningless — "3" says nothing until it is written next to it what the
    # third option is.
    named = len(question.get("options") or "") == _pick_n(question)
    if context and named and ask_keyboard(repo_name, question):
        kept = [ln for ln in context.splitlines() if not NUMBERED.match(ln)]
        context = "\n".join(kept).strip()
    # The "feature · issue #N · PR #N" line is printed by the orchestrator
    # itself — it is for the terminal, where there is no card. Here there is a
    # card, and the same line stands below it as a second, more poorly set copy
    # of the same thing.
    if slug and context.startswith(slug):
        context = "\n".join(context.splitlines()[1:]).strip()
    if context:
        body += t("ask.context",
                  body=escape(clip(strip_ansi(context), ASK_CONTEXT_MAX)))
    if slug:
        # The prompt itself in italics and without "<repository> is asking": the
        # repository and the feature are already named by the card a line
        # above.
        body += "<i>%s</i>" % escape(strip_ansi(question.get("prompt") or "").strip())
    else:
        body += t("ask.title", repo=escape(repo_name),
                  prompt=escape(strip_ansi(question.get("prompt") or "")))
    form = (question.get("form") or "").strip()
    if not form:
        body += "\n\n<i>%s</i>" % t("ask.text")
    elif form.startswith("pick:") and not ask_keyboard(repo_name, question):
        body += "\n\n<i>%s</i>" % t("ask.pick")
    return body


# --- the person at the terminal ----------------------------------------------
#
# A question always goes to the chat, but a sound is not always wanted. Working
# at the laptop itself, a person sees the question in the terminal and answers
# there — a notification at that moment only distracts from the very work the
# question was asked for.
#
# This much silence from the terminal counts as "the person has stepped away".
# Five minutes rather than half a minute: reading a long question with attached
# context or thinking over an answer, a person types nothing for a minute or two
# — and sits in front of the screen all that time. A mistake here costs
# differently in the two directions: a needless silent message will be seen when
# they pick up the phone, whereas a needless sound in the middle of the work is
# exactly what we are getting away from.
ASK_QUIET_AFTER = 300


def tty_of_pid(pid):
    # The process's controlling terminal, or None.
    #
    # Through tty_nr from /proc/<pid>/stat rather than `ps -o tty=`: that is one
    # file read without spawning a process, and the daemon comes here every
    # turn.
    #
    # tty_nr is exactly the device's st_rdev, so we compare the numbers
    # directly rather than assembling a name from major/minor: minor in Linux is
    # cut into two non-adjacent pieces, and unpacking it by hand lies.
    #
    # The process's name in stat sits in brackets and may itself contain
    # brackets and spaces, so we cut at the last ')' rather than the first.
    try:
        with open("/proc/%d/stat" % int(pid)) as fh:
            raw = fh.read()
        rdev = int(raw[raw.rindex(")") + 2:].split()[4])
    except (OSError, ValueError, IndexError, TypeError):
        return None
    if not rdev:
        return None          # started without a terminal: from the bot, from systemd
    try:
        names = os.listdir("/dev/pts")
    except OSError:
        return None
    for name in names:
        path = os.path.join("/dev/pts", name)
        try:
            if os.stat(path).st_rdev == rdev:
                return path
        except OSError:
            continue
    return None


def at_terminal(question):
    # Whether the person is sitting right now at the terminal that asked the
    # question.
    #
    # We look at atime, not mtime. That is not pedantry but the only variant
    # that works: a tty's mtime is moved by a program's output rather than a
    # person's input — and ask() itself, having printed the prompt (ui.sh, the
    # printf right after ask_publish), would immediately report "they were just
    # typing". Every question in a row would go out silent, those asked from the
    # bot included, that is the sign would work inside out. atime is moved only
    # by a successful read from the terminal, that is by what was really typed;
    # idle turns of `read -t "$ASK_POLL"` do not touch it, so while the person
    # is silent the sign honestly ages.
    #
    # We take not "the freshest of all" terminals, as the detector in
    # bin/keepawake does, but precisely the one where this conversation is
    # happening: a forgotten neighbouring tab and code-server's heartbeat have
    # nothing to do with this question, and a maximum over them would declare
    # the person present.
    #
    # Every non-answer here means "with sound": a missed notification is worse
    # than a needless one. No pid, stat will not read, there is no terminal at
    # all (tty_nr == 0 — started from the bot through setsid), the device is
    # already closed — in every case we do not see the person at a terminal,
    # which means they can only answer from the phone.
    tty = tty_of_pid(question.get("pid") or 0)
    if not tty:
        return False
    try:
        return time.time() - os.stat(tty).st_atime < ASK_QUIET_AFTER
    except OSError:
        return False


# --- the state of steps' sessions --------------------------------------------


# One answer serves a press: a card asks for the sessions several times over
# (its session, the one in its worktree, its state), and each ask is a Node
# process.
AGENTS_FRESH = 3
_AGENTS = {"at": 0.0, "list": [], "ok": False}


def agents():
    # Live claude sessions, interactive and background. It needs no terminal, so
    # it is available to the daemon too. Empty on any trouble: no claude, no
    # answer, broken JSON — the card simply will not show the state.
    now = time.time()
    if now - _AGENTS["at"] < AGENTS_FRESH:
        return _AGENTS["list"]
    out = run("claude agents --json", timeout=20)
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    # ok: whether Claude Code answered — an empty list is then no sessions,
    # not a call that failed.
    _AGENTS.update(at=time.time(), list=data if isinstance(data, list) else [],
                   ok=isinstance(data, list))
    return _AGENTS["list"]


def session_state(session_id, cache=None):
    # What a step's session is busy with: working / blocked / idle, or empty if
    # there is none.
    #
    # cache is a list already obtained from agents(): the call shells out with a
    # timeout, and there is no reason to ask once per feature where there are
    # several. Whoever iterates the list passes it; for a single question it can
    # be left out.
    if not session_id:
        return ""
    for a in (agents() if cache is None else cache):
        if isinstance(a, dict) and a.get("sessionId") == session_id:
            return a.get("state") or a.get("status") or "idle"
    return ""


# Where Claude Code keeps each session's transcript, a directory per project.
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")


def feature_busy(repo, slug):
    """Whether the feature is at work: its session in any state but idle, or
    its orchestrator alive and waiting on a question — between steps there
    is no session, and a second orchestrator would be two conversations
    about one thing all the same."""
    if pending_ask(os.path.join(ask_dir(repo), "ask", slug)):
        return True
    session, _step = feature_session(repo, slug)
    return bool(session) and session_state(session) not in ("", "idle")


def cache_left(session_id, now=None):
    """Seconds the session's prompt cache has left — 0 once it has expired —
    or None when its transcript says nothing. The same reckoning as the
    status line's: the last request's time plus the TTL it was written with."""
    if not session_id:
        return None
    paths = glob.glob(os.path.join(CLAUDE_PROJECTS, "*",
                                   glob.escape(session_id) + ".jsonl"))
    last = statusline.last_request(paths[0]) if paths else None
    if not last:
        return None
    when, _usage, ttl = last
    return max(0, when + ttl - (time.time() if now is None else now))


def cache_note(session_id):
    """The card's line on the session's cache, "" when nothing is known."""
    left = cache_left(session_id)
    if left is None:
        return ""
    if not left:
        return t("feat.cachegone")
    return t("feat.cache", m=int((left + 59) // 60))


def state_path(wt):
    """A feature's state.json, in the old .feature/ when an older sclaude
    still runs the tree: layout_migrate leaves it there until that sclaude is
    done, and the feature went missing from the bot meanwhile."""
    new = os.path.join(wt, ".sclaude/local/feature", "state.json")
    old = os.path.join(wt, ".feature", "state.json")
    return new if os.path.exists(new) or not os.path.exists(old) else old


def feature_state(repo, slug):
    # A feature's whole state — the very file with which the orchestrator ties
    # the steps together. An empty dictionary if there is no feature: the card
    # will then show what it knows from the table.
    path = state_path(feature_wt(repo, slug))
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def feature_session(repo, slug):
    # The session id of the feature's current step, and the step itself.
    #
    # Past the four steps — the epilogue, the retrospective — a session is
    # kept elsewhere than under steps, and a feature with one open read as
    # having none: "not running", and Continue free to open a second
    # conversation beside it. A live Claude session working in the feature's
    # worktree is the feature's, whatever the state names.
    data = feature_state(repo, slug)
    step = data.get("step") or ""
    node = (data.get("steps") or {}).get(step) or {}
    session = node.get("session") or ""
    if not session or not session_state(session):
        live = session_in(feature_wt(repo, slug))
        session = live or session
    return session, step


def session_in(wt):
    """The id of a live Claude session working in the worktree, or ""."""
    if not wt:
        return ""
    root = os.path.realpath(wt)
    for a in agents():
        cwd = os.path.realpath(a.get("cwd") or "") if isinstance(a, dict) else ""
        if cwd == root or cwd.startswith(root + os.sep):
            return a.get("sessionId") or ""
    return ""


def feature_links(repo, slug):
    # The feature's issue and pull request. The numbers here are exact — the
    # orchestrator put them there itself — so there is no need to parse a
    # commit's text as in the repository's card.
    #
    # The issue first: it holds the statement of what all this is being done
    # for, whereas the PR appears only at the third step and until then simply
    # does not exist.
    data = feature_state(repo, slug)
    slug_gh = gh_slug(repo)
    if not slug_gh:
        return []
    links = []
    issue = data.get("issue")
    if issue:
        links.append((t("repo.issue", n=issue),
                      "https://github.com/%s/issues/%s" % (slug_gh, issue)))
    pr = data.get("pr")
    if pr:
        links.append((t("repo.pr", n=pr),
                      "https://github.com/%s/pull/%s" % (slug_gh, pr)))
    return links


def start_sclaude(repo, args):
    # Starting the orchestrator in the background.
    #
    # We detach through setsid and do not wait: sclaude lives as long as the
    # conversation does — minutes and hours — while the bot has to be back at
    # getUpdates within seconds. Waiting for it here would mean hanging the
    # whole chat for the duration of the step.
    #
    # The conversation goes on through the channel: the bot will pick the
    # questions up on the loop's turns.
    cmd = "cd %s && setsid sclaude %s < /dev/null > /dev/null 2>&1 &" % (
        shlex.quote(repo), " ".join(shlex.quote(a) for a in args))
    run(cmd, timeout=15)
    log.info("started sclaude %s in %s", " ".join(args), repo)


def feature_card(name, slug, feats=None):
    if feats is None:
        feats, _ = features_of_name(name)
    row = next((r for r in feats if r[0] == slug), None)
    if not row:
        return t("feat.gone", slug=escape(slug))
    repo = repo_path(name)
    session, _step = feature_session(repo, slug) if repo else ("", "")
    state = session_state(session)
    # Claude Code names the states its own way and adds to them: "waiting" is
    # a session that asks the person something. A state not known here is
    # still an open session, never "none is open".
    if not state:
        note = (t("feat.nosessiondone") if " done" in row[1] or row[1].startswith("all done")
                else t("feat.nosession"))
    else:
        note = {"working": t("feat.working"), "busy": t("feat.working"),
                "blocked": t("feat.blocked"), "waiting": t("feat.blocked")}.get(
                    state, t("feat.idle"))
        # How long the open session stays cheap to go on with: on the page,
        # drawn anew at each press. A card in the chat would keep the minutes
        # it was drawn with.
        if ON_PAGE:
            note += cache_note(session)
    return t("feat.card", repo=escape(name), slug=escape(slug),
             step=escape(row[1]), wt=escape(row[2] or "—"), session=note,
             links=links_line(feature_links(repo, slug)) if repo else "")


# How many features get buttons. Eight: more rows do not fit on a phone's
# screen, and below them there are still "new feature" and three exits. Those
# that did not fit are named in a line in repo_text — they must not disappear
# from the chat.
FEATURE_BUTTONS = 8


def features_keyboard(name):
    # The second level: the selected repository's features, a button each.
    # The step and the actions on a feature are on its card, in its topic, and
    # the button takes it there (the topic: callback).
    rows = []
    feats, _ = features_of_name(name)
    for slug, step, _wt in feats[:FEATURE_BUTTONS]:
        label = "%s — %s" % (slug, step)
        # We cut shorter than before. Telegram splits a row between buttons
        # evenly by their number rather than by the text's length, so a lone cog
        # will take half the row however briefly it is labelled. A short label on
        # the left does not change that — but it does stop the label being
        # truncated beyond recognition at half width.
        # Telegram refuses the whole keyboard for one button over 64 bytes.
        # The remembered repository may be left out of the data — the press
        # finds it again; any other, and a feature longer still, get a button
        # that does nothing rather than vanish from a list that counts them.
        data = "topic:%s:%s" % (name, slug)
        if len(data.encode("utf-8")) > 64 and name == os.path.basename(repo_choice()):
            data = "topic::" + slug
        if len(data.encode("utf-8")) > 64:
            # Still listed, as the header counts it: open it from the terminal.
            data = "noop"
        rows.append([{"text": label[:60], "callback_data": data}])
    rows.append([{"text": t("feat.new"), "callback_data": "newfeat:" + name}])
    # Two exits, not one. "To the repositories" is a step one level up within
    # the section; "Back" goes to the main menu, which is where people arrive
    # here from with the Sclaude button. Without the second the way out was
    # roundabout: features → repositories → Settings, that is into a neighbouring
    # branch rather than back where they came from.
    rows.append([{"text": t("repo.refresh"), "callback_data": "repo:" + name},
                 {"text": t("repo.torepos"), "callback_data": "svc_repos"}])
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


def gh_slug(repo):
    # The repository's owner/name from origin's address. We parse it ourselves
    # rather than asking `gh repo view`: that is a network call for the sake of a
    # string that sits in the config.
    url = run("git -C %s remote get-url origin" % shlex.quote(repo)).strip()
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def commit_links(repo, commit):
    # GitHub links from the last commit.
    #
    # The number in a merge commit is the PR, not the issue: "Merge pull
    # request #89" leads to the pull request. The issue itself hides a line
    # deeper, in that same PR's body ("Closes #20") — that is, where sclaude's
    # step 3 puts it. The branch's name (feat/20-change-…) holds the same number
    # and will do when the body is not to hand.
    #
    # Hence two different questions and two different links: "what change has
    # arrived" and "why it was needed". The second is the more valuable — the
    # statement lies in the issue — and without it the card made people look for
    # it by hand.
    #
    # All best-effort: no gh, no network, the number was not found — there will
    # simply be no link. A repository's card is not the place to fall over.
    slug = gh_slug(repo)
    if not slug:
        return []

    m = re.search(r"#(\d+)", commit or "")
    if not m:
        return []
    pr = m.group(1)
    links = [(t("repo.pr", n=pr), "https://github.com/%s/pull/%s" % (slug, pr))]

    body = run("gh pr view %s -R %s --json body -q .body" % (shlex.quote(pr), shlex.quote(slug)),
               timeout=20)
    issue = ""
    found = re.search(r"(?:clos(?:e|es|ed)|fix(?:e|es|ed)?|resolv(?:e|es|ed))\s+#(\d+)",
                      body or "", re.I)
    if found:
        issue = found.group(1)
    else:
        # The fallback is the PR's branch name: sclaude names it after the
        # issue's number, so the number is there even for a PR with an empty
        # body.
        head = run("gh pr view %s -R %s --json headRefName -q .headRefName"
                   % (shlex.quote(pr), shlex.quote(slug)), timeout=20)
        m2 = re.match(r"^[a-z]+/(\d+)-", (head or "").strip())
        if m2:
            issue = m2.group(1)
    if issue:
        links.append((t("repo.issue", n=issue),
                      "https://github.com/%s/issues/%s" % (slug, issue)))
    return links


def links_line(links):
    # The links as a line under the commit. Telegram makes a link of an
    # <a href>, and the caption "#20" is shorter than a bare address — on a phone
    # that is the difference between one line and three.
    if not links:
        return ""
    return "\n" + " · ".join('<a href="%s">%s</a>' % (url, escape(label))
                             for label, url in links)


def main_branch_state(repo):
    # When there are no features there is no reason to show emptiness: the
    # person opened the repository to learn something about it. The main branch
    # is the little that can always be said, and it answers the question "what
    # state is the project in".
    q = shlex.quote(repo)
    branch = run("git -C " + q + " rev-parse --abbrev-ref HEAD").strip()
    commit = run("git -C " + q + " log -1 --format='%h %s'").strip()
    when = run("git -C " + q + " log -1 --format=%cr").strip()
    dirty = run("git -C " + q + " status --porcelain")
    dirty_n = 0 if dirty == t("cmd.empty") else len([l for l in dirty.split("\n") if l.strip()])
    ahead = run("git -C " + q + " rev-list --count @{u}..HEAD 2>/dev/null").strip()
    try:
        ahead_n = int(ahead)
    except ValueError:
        ahead_n = 0          # no upstream — nothing to compare against

    # A fresh repository with no commits: git answers with a complaint on
    # stderr, and there is no reason to show it to a person — "there are no
    # commits yet" is not an error but a state that can be put in words.
    empty = ("fatal:" in commit) or ("fatal:" in branch) or ("fatal:" in when)

    extra = []
    if dirty_n:
        extra.append(t("repo.dirty", n=dirty_n))
    if ahead_n:
        extra.append(t("repo.ahead", n=ahead_n))
    if not extra:
        extra.append(t("repo.clean"))
    return {"branch": branch or "?", "commit": commit or "?",
            "when": when or "", "extra": "\n".join(extra), "empty": empty,
            "links": "" if empty else links_line(commit_links(repo, commit))}


def repo_text(name):
    # raw is the whole sclaude status table; it is no longer needed here, but
    # features_of_name returns it along with the rows, and it has to be parsed
    # for the buttons' sake anyway.
    feats, _raw = features_of_name(name)
    if not feats:
        path = repo_path(name)
        if not path:
            return t("repo.norepos")
        st = main_branch_state(path)
        if st["empty"]:
            return t("repo.nocommits", name=escape(name), extra=st["extra"])
        return t("repo.none", name=escape(name),
                 branch=escape(st["branch"]), commit=escape(st["commit"]),
                 when=escape(st["when"]), extra=st["extra"],
                 links=st["links"])
    body = t("repo.count", name=escape(name), n=len(feats))
    # A button goes to the first eight (see features_keyboard). The rest are
    # not visible in the chat at all — neither as a button nor as a line — so a
    # counter over emptiness would only mislead: "features in progress: 9" with
    # eight of them there. We name them.
    rest = [r[0] for r in feats[FEATURE_BUTTONS:]]
    if rest:
        body += t("repo.rest", rest=escape(", ".join(rest)))
    return body



def strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


def hard_hold_text(data):
    # When a hard holder is holding there is no deadline at all — and showing
    # "this much left" would be a lie.
    return t("hold.hard", who=holders_line(data, "hard"))


# The markers with which keepawake status marks a link inside a name:
# \x01 address \x02 caption \x03. Control characters rather than markup, because
# the script's output is escaped as a whole — letting ready HTML through
# escape() would mean putting holes in the escaping for cosmetics' sake.
STATUS_LINK = re.compile("\x01([^\x02]*)\x02([^\x03]*)\x03")


def status_text():
    # --raw: what is wanted from the script is the form with markers rather than
    # the one already unfolded for the terminal. Without it "dev server
    # (http://…) — none" would arrive here.
    body = strip_ansi(run("keepawake status --raw"))
    # We escape earlier and mark up later: by this moment the caption and the
    # address are already safe, and the tags are put in by us.
    body = STATUS_LINK.sub(r'<a href="\1">\2</a>', escape(body))
    return t("status.title", body=body)


def escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def local_for_lang(label):
    # state.py writes "HH:MM dd.mm" — the order a Russian reader is used to.
    # For English we swap the day and the month; we do not touch the format in
    # the state itself, it is part of the schema and more than the bot reads
    # it.
    if current() == "ru" or not label:
        return label
    parts = label.split()
    if len(parts) == 2 and "." in parts[1]:
        day, month = parts[1].split(".", 1)
        return "%s %s/%s" % (parts[0], month, day)
    return label


def holders_line(data, kind=None):
    # kind=None means all holders, "hard"/"soft" only those of that kind.
    from keepawake.state import HARD_HOLDERS, SOFT_HOLDERS
    # codesrv is essential here: without it the state "the code-server service
    # is up, nobody else" was shown as "holders: nobody" — in the very warning
    # about imminent sleep where a person needs to understand what exactly is
    # holding the machine.
    labels = {"ssh": None, "code": t("hold.code"), "tailscale": t("hold.tailnet"),
              "claude": t("hold.claude"), "dev": t("hold.dev"),
              "codesrv": t("hold.codesrv"), "sclaude": t("hold.sclaude"),
              "vscode": t("hold.vscode")}
    wanted = {"hard": HARD_HOLDERS, "soft": SOFT_HOLDERS}.get(kind)
    names = []
    counts = data.get("holders") or {}
    for name, label in labels.items():
        if wanted and name not in wanted:
            continue
        n = (counts.get(name) or {}).get("count") or 0
        if not n:
            continue
        # For SSH the number of sessions is meaningful, for the others it is
        # not.
        names.append(ssh_holders(n) if name == "ssh" else label)
    return ", ".join(names) or t("hold.nobody")


def hold_reasons(data, now):
    # Every reason the machine is not sleeping, from the longest-running to the
    # rest. The question about a forgotten session used to show hard holders
    # only, and on a day when the hold was set by the "stay awake" button until
    # the following week, the message named a third-rate tailnet and advised
    # stopping the services — advice useless by construction, as the deadline
    # would outlive them all.
    #
    # Returns a list of pairs (how much longer it will hold, text). The number
    # is for sorting only: for a manual deadline it is the remainder, for holders
    # there is nowhere to learn it from, and they follow in the order they
    # appeared.
    from keepawake.state import HARD_HOLDERS, manual_until
    reasons = []
    left = manual_until(data, now)
    if left:
        reasons.append((left, t("hold.manual", at=local_label(left))))
    counts = data.get("holders") or {}
    labels = [("ssh", None), ("code", t("hold.code")), ("tailscale", t("hold.tailnet")),
              ("claude", t("hold.claude")), ("dev", t("hold.dev")),
              ("codesrv", t("hold.codesrv")), ("sclaude", t("hold.sclaude")),
              ("vscode", t("hold.vscode"))]
    for name, label in labels:
        n = (counts.get(name) or {}).get("count") or 0
        if not n:
            continue
        text = ssh_holders(n) if name == "ssh" else label
        # Hard ones hold while they are alive, soft ones for an hour beyond
        # their last appearance. Nothing more precise can be said, and the order
        # between them is set by the list anyway.
        reasons.append((0, text))
    # The manual deadline always comes first: it is the only one whose duration
    # we know, and it is the one that outlives everything else.
    reasons.sort(key=lambda r: -r[0])
    return reasons


def reasons_lines(reasons):
    # As a list, with the main reason in bold: that is what to aim at, the rest
    # are not what is preventing sleep.
    if not reasons:
        return "• " + t("hold.nobody")
    out = []
    for i, (_, text) in enumerate(reasons):
        out.append("• <b>%s</b>" % text if i == 0 else "• " + text)
    return "\n".join(out)


# --- handling ---------------------------------------------------------------

def remember_lang(frm):
    # The client's language arrives in every message and press. We remember it
    # in the state, because the daemon sends the warning about imminent sleep by
    # itself, without an incoming update: at that moment there is nobody to ask,
    # and the last known value is the only thing it has.
    data = read()
    # A choice from the settings beats the client's. Otherwise the switch would
    # live until the very first press: language_code arrives in every update, and
    # an unconditional overwrite would bring the client's language straight
    # back.
    if data.get("lang_pinned"):
        return set_lang(data.get("lang") or DEFAULT)
    code = (frm or {}).get("language_code")
    lang = set_lang(code)
    if data.get("lang") != lang:
        with locked() as st:
            st["lang"] = lang
        log.info("the interlocutor's language: %s (language_code=%r)", lang, code)
    return lang


# The bot's commands: name → a Handler method and a description key in i18n. One
# table for both uses — parsing an incoming "/chrome" and the list in
# setMyCommands — because having diverged they would give the worst of all
# outcomes: a suggestion for a command that answers "unknown command".
#
# /start is deliberately not in the list: Telegram sends it itself when the chat
# is first opened, and there is no reason to show it to a person as one of the
# ways to open the menu.
COMMANDS = collections.OrderedDict([
    ("menu",     ("cmd_menu",     "cmd.menu")),
    # Second: without phone access it is the way back to the app.
    ("phone",    ("cmd_phone",    "cmd.phone")),
    ("status",   ("cmd_status",   "cmd.status")),
    ("awake",    ("cmd_awake",    "cmd.awake")),
    ("extend",   ("cmd_extend",   "cmd.extend")),
    ("sleep",    ("cmd_sleep",    "cmd.sleep")),
    ("chrome",   ("cmd_chrome",   "cmd.chrome")),
    ("code",     ("cmd_code",     "cmd.code")),
    ("sclaude",  ("cmd_sclaude",  "cmd.sclaude")),
    ("settings", ("cmd_settings", "cmd.settings")),
])
COMMANDS["start"] = COMMANDS["menu"]
# The commands listed while phone access is off. The rest still answer when
# typed, with the same short menu.
OFFLINE_COMMANDS = ("menu", "phone", "status", "awake", "extend", "sleep")


class Handler(object):
    def __init__(self, bot):
        self.bot = bot

    def message(self, msg):
        text = (msg.get("text") or "").strip()
        now = int(time.time())
        # The topic it was typed in, and the feature that topic is, looked up
        # once: the lookup reads every worktree's record.
        thread = message_thread(msg)
        fkey = topic_channel(thread) if thread else ""

        # We are waiting for a time for "stay awake until" — but a command
        # always beats the wait, otherwise there would be no way out of a
        # dialogue begun by mistake except the right answer. And only where it
        # was asked: text typed in a feature's topic meanwhile is that
        # feature's, an answer to its question.
        data = read()
        if (text and data.get("awaiting") == "awake_until"
                and (data.get("awaiting_thread") or 0) == thread
                and not text.startswith("/") and not is_menu_button(text)):
            until_ts = parse_hhmm(text, now)
            if not until_ts:
                log.warning("\"stay awake until\": the time was not parsed (%r)", text)
                # We ask again with the box ready too: the person has already
                # missed the format, and making them open the keyboard by hand a
                # second time is exactly what the buttons save them from.
                #
                # The previous box goes: two prompts for one time is the same
                # question twice.
                retire(self.bot, (read().get("awaiting_ids") or {}).get("prompt"))
                self.bot.delete(msg.get("message_id") or 0)
                prompt = self.bot.ask(t("awake.badtime"), t("awake.hint"))
                with locked() as st:
                    st["awaiting_ids"] = dict(st.get("awaiting_ids") or {}, prompt=prompt)
                return
            until = hold_for(until_ts - now, now)
            log.info("\"stay awake until\" %s: deadline until %s", text, until)
            # The question becomes its answer, and the typed time goes with the
            # input box, as an answer to sclaude's question does.
            said = settle_awaiting(self.bot, t("extended.plain", at=local_for_lang(until)))
            said_sleep(self.bot, said, read().get("until_ts") or 0)
            self.bot.delete(msg.get("message_id") or 0)
            return

        # An answer to an orchestrator's question that expects text rather than
        # a button: a feature's name, a branch's name, an option's number from a
        # long list.
        #
        # We do not set up a separate wait here: the open question is the wait,
        # it lies as a file in the channel. That also removes the perennial
        # problem of such modes — the question may have closed in the terminal
        # while the person was typing, and answer_ask will then honestly say
        # there is nothing left to answer.
        #
        # Commands and the "Menu" button do not get in here: one must be able
        # to leave a conversation begun by mistake without answering the
        # question.
        if text and not text.startswith("/") and not is_menu_button(text):
            # Typed in a feature's topic, the text answers that feature's
            # question; typed in the main chat, it answers when one question in
            # all is open — with two, there is no telling which was meant.
            # In the main chat, only the questions shown in it: a feature's
            # question in its topic is not what text typed here answers.
            opened = open_channels()
            if thread:
                # The feature's own, or a question shown in this topic: the
                # repository's new-feature topic has no feature key, and its
                # "Feature name:" is answered there.
                waiting = [(k, d) for k, d in opened if (fkey and k == fkey)
                           or (get_shown(k) or {}).get("thread") == thread]
            else:
                # The repository's own questions, and a feature's only once
                # shown here (no topic to be had): one not shown yet is on its
                # way to its topic.
                waiting = []
                for k, d in opened:
                    entry_k = get_shown(k)
                    # Shown in a topic — the repository's own too, in its
                    # new-feature topic — it is answered there.
                    if entry_k and entry_k.get("thread"):
                        continue
                    if not split_key(k)[1] or entry_k:
                        waiting.append((k, d))
            # The question the text replies to, if it replies to one of them;
            # otherwise, with several, the one on screen here — a question not
            # shown yet, or answered by a button, is not one the person sees.
            to = (msg.get("reply_to_message") or {}).get("message_id") or 0
            replied = [(k, d) for k, d in waiting
                       if to and (get_shown(k) or {}).get("msg") == to]
            if replied:
                waiting = replied
            elif len(waiting) > 1:
                on_screen = [(k, d) for k, d in waiting if (get_shown(k) or {}).get("msg")]
                # A reply to some other message names none of them: which?
                if len(on_screen) != 1 or to:
                    # None on screen: closed by a button, unless one is still
                    # on its way.
                    coming = any(not get_shown(k) for k, _ in waiting)
                    self.bot.send(t("ask.which" if on_screen
                                    else "ask.notyet" if coming else "ask.gone"))
                    return
                waiting = on_screen
            if not thread and not waiting and opened:
                # Pointed to a topic only when a question is shown in one: one
                # not shown yet may still come here, if no topic is to be had.
                intopic = any((get_shown(k) or {}).get("thread") for k, _ in opened)
                self.bot.send(t("ask.intopic" if intopic else "ask.notyet"))
                return
            if len(waiting) == 1:
                key, channel = waiting[0]
                name = split_key(key)[0]
                question = pending_ask(channel)
                # As with a press: the text answers the question the chat
                # shows, not one laid out since that the bot has not shown yet.
                # And only a shown one: before the bot's turn shows a question,
                # nobody has seen it to answer it.
                entry = get_shown(key) or {}
                mark = (question.get("id") or question.get("asked") or 0) if question else None
                if question and (not entry or (not entry.get("legacy")
                                                and entry.get("id") != mark)):
                    # Open, but not on screen yet: the bot shows it on its turn.
                    self.bot.send(t("ask.notyet"))
                    return
                if entry.get("answered"):
                    # Answered by a button a moment ago: the orchestrator is
                    # taking that answer, and this text must not replace it.
                    self.bot.send(t("ask.gone"))
                    return
                # A number the list does not have: the orchestrator would
                # refuse it in the terminal, out of sight, and the question
                # would go. It stays here, and the person picks again. A word
                # goes on: a list may take one ("Enter to leave it out" is
                # anything but a number, and Telegram sends no empty text).
                if ((question or {}).get("form") or "").startswith("pick:") \
                        and text.strip().isdigit() and not option_in_range(question, text):
                    self.bot.delete(msg.get("message_id") or 0)
                    self.bot.send(t("ask.nooption"))
                    return
                if not answer_ask(channel, text, (question or {}).get("id")):
                    self.bot.send(t("ask.gone"))
                    return
                # The answer takes the question's place, as a press does, and
                # the typed message goes: otherwise the chat holds the question
                # with its buttons, the reply below it and a confirmation below
                # that. A bot may delete incoming messages in a private chat.
                # A reply that is not one of the question's answers — neither
                # yes nor no, a word for a list — is the orchestrator's to
                # judge: it asks again, takes the word ("Enter to leave it
                # out"), or refuses. The loop settles the message by its
                # record then (settle_ask); the typed reply goes now. Shown as
                # answered at once, a refused one would keep "✅ maybe".
                form = ((question or {}).get("form") or "")
                if (form.startswith("yn") and text.strip().lower() not in YES_WORDS + NO_WORDS) \
                        or (form.startswith("pick:") and not option_in_range(question, text)):
                    self.bot.delete(msg.get("message_id") or 0)
                    return
                answered = answered_text(name, question, text)
                entry = forget_ask(key, (get_shown(key) or {}).get("msg"))
                if entry:
                    self.bot.edit(entry["msg"], answered)
                    self.bot.delete(msg.get("message_id") or 0)
                else:
                    self.bot.send(answered)
                return

        # Any command clears an open question about the time: the person has
        # gone elsewhere, and there is no longer anything to expect a "23:30"
        # from them for. The "Menu" button ranks with the commands here — it is
        # the declared way to cancel.
        if (text.startswith("/") or is_menu_button(text)) and read().get("awaiting"):
            with locked() as st:
                st["awaiting"] = ""

        # We cut off both the arguments and the @bot_name: Telegram appends it
        # itself when a command is chosen from the suggestions in a group.
        name = text.split()[0].split("@")[0].lstrip("/").lower() if text else ""

        # In a feature's topic the menu is the feature's card: "Menu", /menu
        # and text that answered nothing bring a fresh one to the bottom of the
        # topic, and what was typed goes. Other commands answer as anywhere.
        # Without text — a photo, a file, a voice note — a message is not
        # addressed to the bot at all, and stays.
        if not text:
            return
        if fkey and (is_menu_button(text) or not text.startswith("/")
                     or name in ("menu", "start")):
            if post_card(self.bot, *split_key(fkey)):
                self.bot.delete(msg.get("message_id") or 0)
                return

        # A command or "Menu" has done its job once its screen is up; left in
        # the chat, each is one more line between the screens.
        if is_menu_button(text) or text.startswith("/"):
            self.bot.delete(msg.get("message_id") or 0)
        if is_menu_button(text):
            return self.cmd_menu()
        if not text.startswith("/"):
            self.screen(t("cmd.unknown"), chat_menu(self.bot.thread)[1])
            return
        found = COMMANDS.get(name)
        if not found:
            self.screen(t("cmd.unknown"), chat_menu(self.bot.thread)[1])
            return
        getattr(self, found[0])(now)

    # --- commands -----------------------------------------------------------
    #
    # Every section reachable by buttons has a command too: for a person with a
    # keyboard in their hands that is shorter than two or three presses through
    # the menu. The command sends the very same screen with the same buttons —
    # from there the person goes on pressing as though they had come through the
    # menu.

    def screen(self, text, keyboard=None):
        # A menu screen sent anew — by a command, "Menu", or a word the bot
        # did not know. The chat keeps one: the previous screen goes once the
        # new one is there, so a day of /menu does not stack a dozen menus.
        # Screens move by edits from there; only these sends make new ones.
        # One per place: a command typed in a feature's topic answers there,
        # and replaces that topic's screen, not the main chat's.
        msg = self.bot.send(text, keyboard)
        if msg:
            self.adopt(msg)
        return msg

    def adopt(self, message_id):
        # A message that has become a menu screen where it stands: the screen
        # of its place, replacing the previous one, as a sent screen does.
        place = str(self.bot.thread or 0)
        with locked() as st:
            screens = st.get("screens") or {}
            old = screens.get(place) or 0
            screens[place] = message_id
            st["screens"] = screens
            # The screen replaced asked "until what time?": the question goes
            # with it, as a command leaves it.
            asking = old and (st.get("awaiting_ids") or {}).get("menu") == old
            if asking:
                st["awaiting"] = ""
        if asking:
            settle_awaiting(self.bot)
        elif old and old != message_id:
            retire(self.bot, old)

    def result(self, message_id, text):
        # A menu has been answered: a button did something rather than lead
        # elsewhere. The screen becomes what was done, without buttons — a
        # line of history, as an answered question is — and the next screen
        # leaves it be.
        self.bot.edit(message_id, text)
        forget_screen(message_id)

    def cmd_menu(self, now=0):
        self.screen(*chat_menu(self.bot.thread))

    def cmd_status(self, now=0):
        self.bot.send(status_text())

    def cmd_extend(self, now=0):
        until = hold_for(HOLD_SECONDS, now or int(time.time()))
        log.info("the /extend command: deadline until %s", until)
        said_sleep(self.bot, self.bot.send(t("extended.plain", at=local_for_lang(until))),
                   read().get("until_ts") or 0)

    def cmd_sleep(self, now=0):
        release_hold(now or int(time.time()))
        log.info("the /sleep command: hold released, refusal for %d min",
                 state.REFUSAL_HOLDS // 60)
        said_sleep(self.bot, self.bot.send(t("awake.released")),
                   (now or int(time.time())) + IDLE_SLEPT_KEEP)

    def cmd_awake(self, now=0):
        self.screen(keepawake_text(), awake_keyboard())

    # The sections live in the Mini App; their commands lead there, as /menu
    # does, and without phone access to what the chat keeps.
    def cmd_chrome(self, now=0):
        self.cmd_menu(now)

    def cmd_code(self, now=0):
        self.cmd_menu(now)

    def cmd_sclaude(self, now=0):
        self.cmd_menu(now)

    def cmd_settings(self, now=0):
        self.cmd_menu(now)

    def cmd_phone(self, now=0):
        # The way back to the app when phone access is off: typed, as the
        # chat's short menu offers it by a button.
        if gate_origin():
            return self.cmd_menu(now)
        if gate_origin(None, False):
            # Already on, the address not yet published: the waiting
            # message changes when it is.
            self.bot.send(t("svc.phonestill"))
            return
        on, out = phone_on()
        if not on:
            self.bot.send(t("chrome.gatefail", log=escape(out[-1500:])))
            return
        log.info("phone access turned on by /phone")
        wait_for_phone(self.bot.send(t("svc.phonewait")))

    def callback(self, cq):
        cid = cq.get("id")
        data_raw = cq.get("data") or ""
        message_id = ((cq.get("message") or {}).get("message_id")) or 0
        now = int(time.time())

        # An answer to an orchestrator's question answers the press itself:
        # when the question is gone the press says so in a toast, and a press
        # can be answered only once. Writing the answer is a file and a rename,
        # well inside the ten seconds Telegram gives.
        if data_raw.startswith("answer:"):
            return self.answer_button(cid, data_raw, message_id)

        # The sleep buttons only, and by an explicit prefix. A check for "has a
        # colon" would intercept repo: and feat: as well — they appeared later,
        # and a press on a repository answered "the message is out of date"
        # because the decision handler found no deadline stamp in it. They
        # answer the press themselves: a stale one says why in an alert, and
        # a press takes one answer only.
        if data_raw.startswith(("extend:", "sleep:")):
            let_go(message_id)
            return self.decision(data_raw, message_id, cid, now)

        # The answer first thing, otherwise a spinner turns on the phone.
        self.bot.answer(cid)
        let_go(message_id)

        if data_raw == "menu_extend":
            self.bot.edit(message_id, keepawake_text(), awake_keyboard())
        elif data_raw.startswith("awake:"):
            seconds = int(data_raw.split(":", 1)[1])
            until = hold_for(seconds, now)
            log.info("the extend button for %d min: deadline until %s", seconds // 60, until)
            # The menu has done its job: it becomes the line saying so.
            self.result(message_id, t("extended.plain", at=local_for_lang(until)))
            said_sleep(self.bot, message_id, read().get("until_ts") or 0)
        elif data_raw == "awake_forever":
            until = hold_for(FOREVER_SECONDS, now)
            log.info("the \"stay awake\" button: indefinite, deadline until %s", until)
            self.result(message_id, t("awake.forever.ok"))
            said_sleep(self.bot, message_id, read().get("until_ts") or 0)
        elif data_raw == "awake_until":
            with locked() as st:
                st["awaiting"] = "awake_until"
                st["awaiting_thread"] = self.bot.thread
            log.info("the \"stay awake until\" button: waiting for a time")
            # We leave the "back" button: having changed their mind, people
            # leave the question with one press rather than by typing /menu —
            # which will also do for it and is named in the question itself.
            self.bot.edit(message_id, t("awake.ask"),
                          [[{"text": t("menu.back"), "callback_data": "menu_back"}]])
            # We raise the input box itself with a second message: "back" is
            # inline, and ForceReply cannot be put into inline markup, a message
            # has one reply_markup. Splitting was unavoidable, but leaving with
            # one press is preserved.
            #
            # The messages of an earlier press go: the question is asked anew.
            for old in (read().get("awaiting_ids") or {}).values():
                retire(self.bot, old)
            prompt = self.bot.ask(t("awake.ask.now"), t("awake.hint"))
            with locked() as st:
                st["awaiting_ids"] = {"menu": message_id, "prompt": prompt}
        elif data_raw == "awake_release":
            # The same as "Let it sleep" in the warning.
            release_hold(now)
            # We clear an open question about the time: the person has left it
            # for a neighbouring button, and there is nothing left to expect an
            # answer for.
            if read().get("awaiting"):
                with locked() as st:
                    st["awaiting"] = ""
            log.info("the \"let it sleep\" button: hold released, refusal for %d min",
                     state.REFUSAL_HOLDS // 60)
            self.result(message_id, t("awake.released"))
            said_sleep(self.bot, message_id, now + IDLE_SLEPT_KEEP)
        elif data_raw == "menu_status":
            self.result(message_id, status_text())
        elif data_raw == "menu_chrome":
            self.bot.edit(message_id, *chrome_screen())
        elif data_raw == "menu_code":
            self.bot.edit(message_id, code_text(), code_keyboard())
        elif data_raw in ("code_start", "code_restart", "code_stop"):
            verb = {"code_start": "start", "code_restart": "restart",
                    "code_stop": "stop"}[data_raw]
            run("systemctl --user %s code-server.service" % verb)
            self.result(message_id, code_text())
        elif data_raw == "menu_services":
            self.bot.edit(message_id, t("svc.title"), services_keyboard())
        elif data_raw == "menu_back":
            # Returning to the menu also cancels an open question about the
            # time: otherwise the bot would silently swallow the next ordinary
            # message, taking it for an answer.
            if read().get("awaiting"):
                with locked() as st:
                    st["awaiting"] = ""
            self.bot.edit(message_id, *chat_menu(self.bot.thread))
        elif data_raw == "noop":
            pass          # a row caption, not a button
        elif data_raw == "idle_keep":
            # We do nothing — but mark that we asked, so that the next question
            # comes in an hour rather than at once.
            with locked() as st:
                st["idle_asked_ts"] = now
            self.bot.edit(message_id, t("idle.kept"))
        elif data_raw == "idle_sleep":
            release_hold(now)
            # We mark that we asked: otherwise the next question about
            # forgotten holders would come immediately rather than in an hour.
            with locked() as st:
                st["idle_asked_ts"] = now
            log.info("forgotten holders: let it sleep, hold released")
            self.bot.edit(message_id, t("idle.slept"))
            # About sleep too: it goes once Windows has had its idle time.
            said_sleep(self.bot, message_id, now + IDLE_SLEPT_KEEP)
        elif data_raw in ("chrome_start", "chrome_restart", "chrome_stop"):
            if data_raw == "chrome_stop":
                run("chrome-debug --stop")
            else:
                if data_raw == "chrome_restart":
                    run("chrome-debug --stop")
                # The list of features rather than any one of them: which one
                # is wanted is the next button's question, and the list is
                # where each of them is a click away.
                run("chrome-debug http://localhost:%d/" % DEV_PORT, timeout=60)
            # We show the state rather than the command's output:
            # chrome-debug's output is written for a terminal and reads badly in
            # a messenger, while the person has one question — did it start and
            # where to look.
            self.result(message_id, chrome_text())
        elif data_raw == "phone_toggle":
            if gate_origin(None, False):
                run(FUNNEL_OFF, timeout=30)
                log.info("phone access turned off")
                phone_changed(self.bot, False)
                self.result(message_id, t("chrome.gatedown"))
                return
            on, out = phone_on()
            if not on:
                # Most often: funnel not allowed for this node in the tailnet
                # policy, or this user is not Tailscale's operator.
                self.bot.edit(message_id, t("chrome.gatefail", log=escape(out[-1500:])),
                              services_keyboard())
                return
            log.info("phone access turned on")
            self.result(message_id, t("svc.phonewait"))
            wait_for_phone(message_id)
        elif data_raw.startswith("devphone:") or data_raw == "gate_stop":
            # Buttons of a card drawn before phone access moved to Settings.
            self.bot.edit(message_id, *chrome_screen())
        elif data_raw.startswith(("devopen:", "devstop:", "devstart:")):
            action, _, label = data_raw.partition(":")
            found = [f for f in dev_features() if f[0] == label]
            if not found:
                # Merged or abandoned since the card was drawn.
                self.bot.edit(message_id, *chrome_screen())
                return
            _label, wt, _port, _running = found[0]
            dev_act(action[3:], label, wt)
            self.result(message_id, chrome_text())
        elif data_raw == "svc_sclaude":
            # We open straight on the remembered repository: most often a
            # person comes back to the same project, and a needless choice is no
            # use to them.
            chosen = repo_choice()
            if chosen:
                name = os.path.basename(chosen)
                self.bot.edit(message_id, repo_text(name), features_keyboard(name))
            else:
                self.bot.edit(message_id, t("repo.pick"), repos_keyboard())
        elif data_raw == "svc_lang":
            self.bot.edit(message_id, lang_text(), lang_keyboard())
        elif data_raw.startswith("lang:"):
            choice = data_raw.split(":", 1)[1]
            with locked() as st:
                if choice == "auto":
                    # We unpin and take the language from this very press at
                    # once: it carries language_code, and there is no reason to
                    # wait for the next one to show the result.
                    st["lang_pinned"] = False
                    lang = set_lang((cq.get("from") or {}).get("language_code"))
                else:
                    st["lang_pinned"] = True
                    lang = set_lang(choice)
                st["lang"] = lang
            log.info("the language was switched: %s (pinned: %s)",
                     lang, choice != "auto")
            # The keyboard below the input box is labelled in the previous
            # language — we replace it, otherwise its caption would diverge from
            # the rest of the interface.
            relabel_anchor(self.bot)
            # And the profile texts and commands, which follow a pinned language.
            self.bot.commands()
            self.bot.describe()
            self.result(message_id, lang_text())
        elif data_raw == "svc_docs":
            self.bot.edit(message_id, t("docs.menu"), docs_keyboard())
        elif data_raw.startswith("doc:"):
            body = docs.section(data_raw.split(":", 1)[1], current())
            if body:
                # A separate message rather than an edit of the current one:
                # the sections are long, and paging through them while losing the
                # previous one is awkward. The menu stays in place so the next
                # section opens with one press.
                self.bot.send(body)
            else:
                self.bot.edit(message_id, t("docs.menu"), docs_keyboard())
        elif data_raw == "svc_repos":
            self.bot.edit(message_id, t("repo.pick"), repos_keyboard())
        elif data_raw.startswith("repo:"):
            name = data_raw.split(":", 1)[1]
            path = repo_path(name)
            if not path:
                # A name not from the list: either the repository is gone or the
                # callback was forged. Both are a reason to show the list
                # again.
                log.warning("unknown repository in the callback: %r", name)
                self.bot.edit(message_id, t("repo.pick"), repos_keyboard())
                return
            was = repo_choice()
            with locked() as st:
                st["sclaude_repo"] = path
            # code-server opens a directory at start-up, so a change of choice
            # reaches it only through a restart. We do that ourselves and only
            # with a live server: nobody asked to bring it up for the sake of a
            # changed choice.
            if was != path and code_running():
                run("systemctl --user restart code-server.service")
            self.bot.edit(message_id, repo_text(name), features_keyboard(name))
        elif data_raw.startswith(("topic:", "feat:")):
            # A feature from the list: its card goes to its topic, made if
            # need be, and the list says where it went. Without Threaded Mode
            # the card takes the list's place, as it did before topics.
            # feat: is the same press from a list drawn before topics.
            _, name, slug = data_raw.split(":", 2)
            # topic::<slug> — the remembered repository, too long for the
            # data (features_keyboard).
            name = name or os.path.basename(repo_choice())
            opened = open_card(self.bot, name, slug)
            if opened:
                self.result(message_id, t("feat.opened", slug=escape(slug)))
            elif opened is None:
                # The network's: the list stays, for a press once it is back.
                self.bot.edit(message_id, repo_text(name) + t("feat.topiclater"),
                              features_keyboard(name))
            else:
                # A card outside a topic: a button whose data could not carry
                # the feature finds it by this message (card_press).
                with locked() as st:
                    cards = st.get("main_cards") or {}
                    cards.pop(str(message_id), None)
                    cards[str(message_id)] = channel_key(name, slug)
                    # The last few: older cards have long scrolled away.
                    st["main_cards"] = dict(list(cards.items())[-MAIN_CARDS:])
                self.bot.edit(message_id, *card(name, slug, in_topic=False))
        elif data_raw.startswith("fc:"):
            self.card_press(data_raw, message_id)
        elif data_raw.startswith(("go:", "acts:")):
            # A card or list drawn before topics.
            verb, name, slug = data_raw.split(":", 2)
            self.card_press("fc:%s:%s" % (verb, channel_key(name, slug)), message_id)
        elif data_raw.startswith("newfeat:"):
            # A new feature: the conversation goes on through the channel from
            # here — the orchestrator will ask for a name (or offer issues), and
            # the bot will show the question on a turn of the loop.
            name = data_raw.split(":", 1)[1]
            repo = repo_path(name)
            if not repo:
                self.bot.edit(message_id, t("repo.norepos"), repos_keyboard())
                return
            thread = new_feature_topic(self.bot, name)
            start_sclaude(repo, ["new"])
            self.result(message_id, t("feat.newtopicat" if thread else "feat.newstarted",
                                      repo=escape(name)))
        elif data_raw == "svc_restart":
            self.restart(message_id)
        else:
            log.warning("unknown callback: %s", data_raw)

    def card_press(self, data_raw, message_id):
        # A button on a feature's card. The feature is named in the data, or,
        # when its name did not fit, by the topic the card stands in.
        parts = data_raw.split(":", 2)
        action = parts[1]
        key = parts[2] if len(parts) > 2 else topic_channel(self.bot.thread)
        if not key:
            key = (read().get("main_cards") or {}).get(str(message_id), "")
        name, slug = split_key(key)
        repo = repo_path(name) if slug else None
        if not repo or not feature_dir(repo, slug):
            self.bot.edit(message_id, t("feat.gone", slug=escape(slug or "?")))
            return
        note, feats = "", None
        if action in ("go", "acts"):
            # We do not touch a busy feature: a second orchestrator on the same
            # feature is two conversations about one thing. busy belongs here
            # too: the card shows it as running (🟢). So does any state but
            # idle: one Claude Code adds later is not a free feature.
            if feature_busy(repo, slug):
                note = t("feat.busy")
            elif action == "go":
                # The orchestrator decides what to do itself: `sclaude <feature>`
                # returns to the current step.
                start_sclaude(repo, [slug])
                # Once, for the note and the card both: it is `sclaude status`.
                feats, _ = features_of_name(name)
                row = next((r for r in feats if r[0] == slug), None)
                note = t("feat.started", step=escape(row[1] if row else slug))
            else:
                # The list of actions arrives as a question in this topic.
                start_sclaude(repo, ["actions", slug])
        elif action in ("open", "start", "stop"):
            dev = feature_dev(repo, slug)
            if dev:
                dev_act(action, dev[0], feature_wt(repo, slug))
            # The proxy starts the server on its own time: the card redrawn
            # at once would still call it stopped.
            for _ in range(20 if dev and action == "start" else 0):
                if (feature_dev(repo, slug) or (0, 0, False))[2]:
                    break
                time.sleep(0.5)
        elif action == "code":
            run("systemctl --user start code-server.service")
            # The card redrawn at once would still call it stopped.
            for _ in range(10):
                if code_running():
                    break
                time.sleep(0.5)
        self.bot.edit(message_id, *card(name, slug, note, in_topic=bool(self.bot.thread),
                                        feats=feats))

    def answer_button(self, cid, data_raw, message_id):
        # An answer to an orchestrator's question. Three fields rather than
        # two: we separate the repository's name from the answer at the first
        # colon from the left — the answer itself may contain anything.
        _, name, reply = data_raw.split(":", 2)
        repo = repo_path(name)
        if not repo:
            self.bot.answer(cid)
            self.bot.edit(message_id, t("repo.norepos"), repos_keyboard())
            return
        # The press carries the repository, not the question or the feature:
        # the message it came from says which. Each open question is shown by
        # one message, and a press on any other is a press on a closed one —
        # without this a button on an old message would answer whatever the
        # repository asks now.
        if press_answered(name, message_id, repo):
            self.bot.answer(cid)
            return
        key = press_channel(name, message_id, repo)
        channel = channel_dir(key) if key else ""
        # We learn what exactly was chosen before sending: afterwards the
        # question is cleared, and there will be nowhere left to read it from.
        question = pending_ask(channel) if channel else None
        chosen = option_label((question or {}).get("options"), reply)
        # The message shows one question; the channel may hold the next one
        # by now — answered at the laptop, "Delete them?" is followed at once
        # by "Force-delete it?", and the bot learns of it only on its turn. A
        # press must not answer a question it was not shown.
        entry = get_shown(key, repo) if key else None
        mark = (question.get("id") or question.get("asked") or 0) if question else None
        if not channel or (entry and not entry.get("legacy") and entry.get("id") != mark) \
                or not answer_ask(channel, reply, (question or {}).get("id")):
            self.bot.answer(cid, t("ask.gone"))
            # A message the loop knows of is settled by it — into the answer
            # given at the laptop. Only one it has no record of goes now.
            if not key:
                retire(self.bot, message_id)
            return
        self.bot.answer(cid)
        forget_ask(key, message_id, repo)
        # "1" is honest but useless where the answer was an exit. The person
        # pressed "back" and has a right to see what they were leaving: the
        # repository's feature list. The other answers replace the question
        # — work follows them, and its output will come in due course.
        if is_back_option(chosen) and not self.bot.thread:
            self.bot.edit(message_id, repo_text(name), features_keyboard(name))
            # A menu now, and the main chat keeps one.
            self.adopt(message_id)
        else:
            self.bot.edit(message_id, answered_text(name, question, reply))

    def restart(self, message_id):
        # The daemon restarts itself, and this is the case where the order
        # matters more than the return code: systemctl kills us right in the
        # middle of handling, and there is nobody else to report the restart —
        # the process is already gone.
        #
        # So first the "restarting" message and only then the command itself:
        # detached from us (start-new-session) and with a pause, so that
        # sendMessage has time to go out over the network. Otherwise systemd
        # kills the whole process group along with the answer not yet sent.
        pid = os.getpid()
        started = uptime_of(pid)
        self.bot.edit(message_id,
                      t("svc.restarting"), None)
        # We put the mark in the state: after the restart it is a different
        # process, and it can remember the errand only through a file.
        with locked() as st:
            st["restart_notify"] = message_id
            st["restart_from_pid"] = pid
            st["restart_page"] = False
        subprocess.Popen(
            ["bash", "-c",
             "sleep 2; systemctl --user restart keepawake-telegram.service"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def decision(self, raw, message_id, cid, now):
        action, _, ts = raw.partition(":")
        try:
            stamp = int(ts)
        except ValueError:
            stamp = None

        with locked() as st:
            live_until = st.get("until_ts") or 0
            if stamp is None or stamp != live_until:
                # The window is a different one now: it was extended
                # differently, or the laptop managed to sleep and the cycle
                # started again.
                log.warning("the decision %r is stale: stamp %s, in the state %s",
                            action, stamp, live_until)
                # The alert says why; the message goes at once (after the
                # lock), being about a window that is over.
                self.bot.answer(cid, t("sleep.stale"), alert=True)
                stale = True
            else:
                stale = False
                self.bot.answer(cid)
                if action == "extend":
                    state.extend(st, now, manual=True)
                    state.touch(st, now)
                    st["decision"] = "extend"
                    st["decision_ts"] = now
                    until = st["until_local"]
                    text = t("sleep.extended", at=local_for_lang(until))
                else:
                    # Not "sleep now" but "stop holding": Windows will count its
                    # own fifteen minutes of idling as usual. Released by
                    # release_hold, after the lock, so no copy of its fields
                    # drifts from it.
                    until = None
                    text = t("sleep.accepted")
                expires = (now + IDLE_SLEPT_KEEP) if until is None else st["until_ts"]
        if stale:
            if not retire(self.bot, message_id):
                trail(message_id, now)
            return
        if until is None:
            release_hold(now)
        # We write after the lock: there is no reason to hold a flock on the
        # state file for the sake of a log entry.
        if until is None:
            log.info("the warning: let it sleep, hold released")
        else:
            log.info("the warning: extend, deadline until %s", until)
        # We remove the keyboard: there will be nothing left to press a second
        # time. The answer stays while true: until the new deadline, or, let
        # go, while Windows counts its idle time.
        self.bot.edit(message_id, text)
        said_sleep(self.bot, message_id, expires)


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
    if asked_msg and (not data.get("hard_hold") or idle < IDLE_SECONDS_THRESHOLD
                      or idle >= IDLE_UNKNOWN):
        retire(bot, asked_msg)
        with locked() as st:
            if st.get("idle_message_id") == asked_msg:
                st["idle_message_id"] = 0
    if not data.get("hard_hold"):
        return
    if data.get("busy"):
        return
    if idle < IDLE_SECONDS_THRESHOLD:
        return
    # 999999 is the detector's placeholder for "no interactive sessions at
    # all". Idling cannot be judged by it: it produced "277 hours without input"
    # on a machine that had been working since yesterday. No sessions means no
    # input to wait for either, and something else is holding then (a code-server
    # tab, tailnet traffic), so a question about a forgotten terminal is out of
    # place here.
    if idle >= IDLE_UNKNOWN:
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
    retire(bot, read().get("idle_message_id") or 0)
    msg = bot.send(t("idle.warn", since=local_label(since),
                     held=human_span(now - since), idle=human_span(idle),
                     who=reasons_lines(hold_reasons(data, now))), idle_keyboard())
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
        return t("why.refused", who=holders_line(data))
    soft = holders_line(data, "soft")
    if soft != t("hold.nobody"):
        return t("why.soft", who=soft)
    return t("why.nobody")


def channel_context(channel):
    """The lines an open question in the channel carries with it."""
    try:
        with open(os.path.join(channel, "ask.json")) as fh:
            ask = json.load(fh) or {}
    except (OSError, ValueError):
        return ""
    return "%s\n%s" % (ask.get("context") or "", ask.get("prompt") or "")


def check_asks(bot):
    # An orchestrator's open question is exactly what hot switching is.
    #
    # We look at every known repository rather than only the selected one: a
    # feature may have been started at the laptop in any of them, and a question
    # shown only in the "current" project would be half a promise.
    #
    # We show a question once: we check the stamp the orchestrator puts into
    # the question itself. The stamp is unique to each — comparing by time will
    # not do: two questions in a row fit into one second (branches.sh asks
    # "Delete them?" and immediately "Force-delete it?"), and we would consider
    # the second already shown. The step would stall silently, and from a phone
    # that looks like "the bot is not sending anything".
    #
    # It can be answered both from here and in the terminal: the first answer
    # clears the question, and the second source learns of it by the file's
    # disappearance. Its message then changes — see settle_ask.
    #
    # A feature's questions go to the feature's topic (feature_topic), so that
    # features running in parallel do not ask over one another in one stream.
    present = set()
    for repo in known_repos():
        name = os.path.basename(repo)
        for slug, channel in ask_channels(repo):
            key = channel_key(name, slug)
            present.add(key)
            check_channel(bot, key, name, slug, channel, repo)
    # A feature gone while it waited for its topic leaves its try behind: the
    # daemon runs for weeks.
    for tried in [k for k in TOPIC_TRIED if k not in present]:
        TOPIC_TRIED.pop(tried, None)
    # A repository deleted or renamed will never close its question the usual
    # way. (A feature's message goes with its topic — see check_topics.)
    # Also a feature's entry kept in the state while it had no worktree: once a
    # worktree of that name exists, its record is read instead, and the state's
    # entry would never be settled.
    state_shown = shown_asks()
    stale = [k for k in state_shown if k not in present
             or (split_key(k)[1] and in_worktree(k)[0])]
    for key in stale:
        retire(bot, state_shown[key].get("msg") or 0)
    if stale:
        # From the state directly: put_shown would write to a worktree that
        # has since appeared under the same name.
        with locked() as st:
            shown = st.get("ask_shown") or {}
            for key in stale:
                shown.pop(key, None)
            st["ask_shown"] = shown


def check_channel(bot, key, name, slug, channel, repo):
    # Marks of an earlier feature of the same name, set aside when the new one
    # began (ask_feature_begin): their topics go first — before the records
    # below are read, one of which may be that feature's last answer.
    if slug:
        for old in glob.glob(os.path.join(glob.escape(channel), ENDED_MARK + "-*")):
            if end_feature(bot, name, slug, channel, old):
                try:
                    os.unlink(old)
                except OSError:
                    pass
    question = pending_ask(channel)
    # A feature whose clean-up is through, or whose worktree is going: its
    # last message and its records are end_feature's (check_topics), which
    # settles them with the topic. The worktree goes before the mark is
    # written, and records read in between would be lost to it.
    if slug and not question and (os.path.exists(os.path.join(channel, ENDED_MARK))
                                  or (not feature_dir(repo, slug)
                                      and not shown_asks().get(key))):
        return
    # id is on questions laid out by this version; asked is the fallback key
    # for a question left over from the previous one (the daemon and the
    # orchestrator are updated separately, and they can diverge by one
    # restart).
    mark = (question.get("id") or question.get("asked") or 0) if question else None
    closed = closed_asks(channel)
    entry = get_shown(key, repo)
    # The shown question has closed — or another has taken its place between
    # two turns, as in "Delete them?" followed at once by "Force-delete it?".
    # Either way its message is settled before the next question goes out, so
    # the answer stands above the question that follows from it.
    if entry and entry.get("id") != mark:
        settle_ask(bot, name, entry, closed.get(entry.get("id"), (None, None))[1])
        put_shown(key, None, repo)
        entry = None
    # Every record is read once. The open question's own record stays: it is
    # written a moment before the question leaves the channel.
    for qid, (path, _) in closed.items():
        if qid != mark:
            try:
                os.unlink(path)
            except OSError:
                pass
    if not question or entry:
        return
    # Silent if the person is right now at the terminal where the question was
    # asked: they can already see it on the screen and will answer there. The
    # message goes out anyway — one can step away mid-step, and then it is
    # already waiting in the chat.
    # The repository's own questions while a feature is being started from the
    # bot are that feature's first ones: they go to its new topic.
    # Only a start from the bot: one at a terminal asks there, and its
    # repository's questions stay in the main chat. And only `sclaude new`'s:
    # the topic outlives a start given up, and another orchestrator's
    # question ("Which feature?") is the main chat's.
    thread = (feature_topic(bot, name, slug) if slug
              else 0 if tty_of_pid(question.get("pid")) or not asks_for_new(question.get("pid"))
              else new_topic_of(name))
    # No topic though the feature has a worktree and topics are on: the
    # network or a rate limit. The next turn tries again — sent to the main
    # chat now, the question would stay there, mixed with other features'.
    if slug and not thread and topic_pending(repo, slug, TOPIC_TRIED, key):
        return
    if thread:
        TOPIC_TRIED.pop(key, None)
    text = ask_text(name, question, in_topic=bool(thread), slug=slug)
    keyboard = ask_keyboard(name, question)
    quiet = at_terminal(question)
    msg = bot.send(text, keyboard, quiet=quiet, thread=thread)
    if not msg and thread and topic_lost(bot):
        # The topic is gone — the person deleted it by hand. A new one is
        # made once; failing that the question goes to the main chat, since a
        # question that does not arrive stalls the step. Any other failure is
        # the network's: the topic is still there, and the next turn retries.
        if slug:
            thread = feature_topic(bot, name, slug, renew=True)
        else:
            drop_new_topic(name)
            thread = 0
        if thread:
            msg = bot.send(text, keyboard, quiet=quiet, thread=thread)
        if not msg:
            # The main chat, with the card that names the feature.
            thread = 0
            msg = bot.send(ask_text(name, question, slug=slug), keyboard, quiet=quiet, thread=0)
    if not msg:
        return
    put_shown(key, {"id": mark, "msg": msg, "thread": thread,
                    "prompt": question.get("prompt") or "",
                    "form": question.get("form") or "",
                    "options": question.get("options") or []}, repo)
    log.info("showed the sclaude question from %s: %r", key,
             (question.get("prompt") or "")[:60])


# --- a topic per feature -------------------------------------------------------
#
# The bot runs in Threaded Mode (set in @BotFather), and each feature that asks
# something gets a topic of its own in the private chat; the menu, the sleep
# warning and the repository's own questions stay in the main chat. Without
# the mode creating a topic fails, and everything goes to the main chat as it
# did before.
#
# What the bot knows of a feature — its topic, the message showing its open
# question — is the feature's, and lives with it, in the worktree only: under
# .sclaude/local/feature/, which git and every upload leave out. A feature asks
# in its channel only while its worktree exists (ask_channel in io.sh).
#
# The topic goes with the worktree, everything in it included: remove_worktree
# reads the record before the worktree goes and leaves it in the channel's
# "ended" mark (ask_feature_end), and the bot deletes the topic named there and
# the channel. Telegram does not let a bot close a topic in a private chat —
# only delete it.

FEATURE_RECORD = "telegram.json"
ENDED_MARK = "ended"
# Set in the worktree by stop_dev (sclaude/lib/worktree.sh) when its removal
# begins, and honoured by sclaude-proxy too.
CLOSING_MARK = "closing"

# The name's length. Telegram allows 128 characters, but a phone shows a topic
# list and a topic's header in about thirty: the slug comes first so that its
# start is what shows, and the repository's name after it, dropped when the
# slug leaves it no room.
TOPIC_NAME_MAX = 48
# How long a question waits for its feature's topic before the main chat takes
# it: a refusal that is not "not a forum" may never pass, and a question that
# never shows stalls the step.
TOPIC_WAIT = 120
# A feature's failed tries to make or reach its topic: key → (first, last).
# In memory: a restart starts the wait afresh, which is all it should do.
TOPIC_TRIED = {}
# A pause in failures this long, and the next one starts a new wait.
TOPIC_QUIET = 600
# The same for a feature opened from the list, by its key.
CARD_TRIED = {}


def topic_pending(repo, slug, tried, tag):
    # A topic is to be had — the feature has a worktree, Threaded Mode is on —
    # but was not made or reached: the network or a rate limit. True for
    # TOPIC_WAIT from the first such try (kept in tried under tag); after that
    # a refusal that may never pass gives way to the main chat.
    #
    # The wait is the feature's, not each question's: a refusal that lasts
    # holds up its first question only. Tries stop counting after a quiet
    # spell, so a blip a day later waits afresh.
    now = int(time.time())
    # A try quiet this long is spent: its feature reached its topic, or went.
    for old in [k for k, (_, last) in tried.items() if now - last > TOPIC_QUIET]:
        tried.pop(old, None)
    if not (repo and feature_dir(repo, slug)) or now < (read().get("topics_off_until") or 0):
        return False
    first, _ = tried.get(tag) or (now, now)
    tried[tag] = (first, now)
    return now - first < TOPIC_WAIT


# How long a topic delete is retried before its end mark is let go.
TOPIC_DELETE_FOR = 86400
# Telegram's refusals that mean a topic is not there to delete.
TOPIC_GONE = ("thread not found", "topic_id_invalid", "topic_deleted", "not a forum")
# How many cards outside topics (Threaded Mode off) keep their feature known.
MAIN_CARDS = 20
# How long a refusal to make a topic ("the chat is not a forum") is believed.
TOPICS_OFF_RETRY = 600
TOPIC_NAME_SLUG_MIN = 16
# A feature whose worktree is gone without the clean-up saying so — removed by
# hand — loses its channel this long after it last changed. Its topic stays: its
# id went with the worktree. Not at once, so that a channel being written while
# the worktree is created is not taken for one.
TOPIC_GRACE = 600


def topic_lost(bot):
    # The last call failed because its topic is gone, not for the network.
    return any(w in (bot.last_error or "") for w in TOPIC_GONE)


def topic_name(name, slug):
    tail = " · " + name
    room = TOPIC_NAME_MAX - len(tail)
    if room < TOPIC_NAME_SLUG_MIN or len(slug) > room:
        tail = ""
        room = TOPIC_NAME_MAX
    if len(slug) > room:
        slug = slug[:room - 1].rstrip("-_.") + "…"
    return slug + tail


def feature_wt(repo, slug):
    return os.path.join(os.path.dirname(repo), "%s-%s" % (os.path.basename(repo), slug))


def feature_dir(repo, slug):
    # The feature's own directory in its worktree, "" while there is none.
    # Only the current layout: io.sh keeps the record there alone, and a tree
    # still on the old .feature/ asks in the main chat until it moves.
    d = os.path.join(feature_wt(repo, slug), ".sclaude/local/feature")
    return d if os.path.isdir(d) else ""


def record_path(repo, slug):
    # "" while the feature has no worktree: there is then nowhere to keep it.
    d = feature_dir(repo, slug)
    return os.path.join(d, FEATURE_RECORD) if d else ""


def load_record(repo, slug):
    path = record_path(repo, slug)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_record(repo, slug, record):
    _TOPIC_KEYS.clear()       # a thread may have just been written
    path = record_path(repo, slug)
    if not path:
        return
    tmp = "%s.%d" % (path, os.getpid())
    # No makedirs: record_path has just found the directory, and making it
    # again would bring back a worktree that remove_worktree is deleting this
    # very moment — `sclaude new` would then find the path taken.
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("the record of %s was not written: %s", slug, exc)


def feature_topic(bot, name, slug, renew=False):
    # The feature's topic, made on its first question. 0 when there is none
    # to be had: Threaded Mode is off, or the network failed. renew drops a
    # topic the person deleted by hand.
    repo = repo_path(name)
    if not repo or not feature_dir(repo, slug):
        return 0
    record = load_record(repo, slug)
    thread = 0 if renew else (record.get("thread") or 0)
    if renew and (record.get("shown") or {}).get("thread"):
        # The question shown in the lost topic went with it: forgotten, it is
        # sent again into the new one on the loop's next turn. One shown in
        # the main chat is still there, and stays the loop's to settle.
        record.pop("shown", None)
    if not thread:
        # Threaded Mode off: Telegram says the chat is not a forum. That is
        # remembered for a while rather than asked again for every question
        # and every press.
        now = int(time.time())
        if now < (read().get("topics_off_until") or 0):
            return 0
        thread = adopt_new_topic(bot, name, slug)
        if thread:
            record.pop("card", None)
            record["thread"] = thread
            save_record(repo, slug, record)
            post_card(bot, name, slug)
            return thread
        thread = bot.create_topic(topic_name(name, slug))
        if not thread:
            if "not a forum" in bot.last_error:
                with locked() as st:
                    st["topics_off_until"] = now + TOPICS_OFF_RETRY
            return 0
        log.info("a topic for %s/%s: %s", name, slug, thread)
        record.pop("card", None)
        record["thread"] = thread
        save_record(repo, slug, record)
        # A topic opens with its feature's card (post_card).
        post_card(bot, name, slug)
    return thread


# A new feature's topic, made when it is started from the bot. Its first
# questions — the name, the issue — come before the feature has a name, from
# the repository's own channel, and would otherwise land in the main chat. They
# go to this topic instead, and the first feature of that repository to need a
# topic afterwards takes it over, renamed. One per repository, in the state:
# {name: {"thread": id, "since": ts}}. One nobody took over goes after
# NEW_TOPIC_KEEP, unless a question is still open in it.
NEW_TOPIC_KEEP = 12 * 3600


def asks_for_new(pid):
    """Whether the process asking is `sclaude new` — the start the new-feature
    topic was made for."""
    try:
        with open("/proc/%d/cmdline" % int(pid or 0), "rb") as fh:
            args = fh.read().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(os.path.basename(a) == b"sclaude" for a in args) and b"new" in args


def new_feature_topic(bot, name):
    """The new-feature topic of this repository, made now; 0 without topics."""
    old = (read().get("new_topics") or {}).get(name)
    if old and old.get("thread"):
        return old["thread"]
    if int(time.time()) < (read().get("topics_off_until") or 0):
        return 0
    thread = bot.create_topic(t("feat.newtopic", repo=name)[:TOPIC_NAME_MAX])
    if thread:
        with locked() as st:
            topics = st.get("new_topics") or {}
            topics[name] = {"thread": thread, "since": int(time.time())}
            st["new_topics"] = topics
        log.info("a new-feature topic for %s: %s", name, thread)
    return thread


def new_topic_of(name):
    return ((read().get("new_topics") or {}).get(name) or {}).get("thread") or 0


def drop_new_topic(name):
    with locked() as st:
        topics = st.get("new_topics") or {}
        entry = topics.pop(name, None)
        st["new_topics"] = topics
    return entry


def adopt_new_topic(bot, name, slug):
    """The repository's new-feature topic, renamed for this feature, when the
    feature is the one it was made for: its worktree appeared after the topic.
    0 otherwise."""
    entry = (read().get("new_topics") or {}).get(name) or {}
    repo = repo_path(name)
    # A worktree's .git is a file written once, when the worktree is made;
    # the directories in it change with every write.
    try:
        born = os.stat(os.path.join(feature_wt(repo, slug), ".git")).st_mtime if repo else 0
    except OSError:
        born = 0
    if not entry.get("thread") or born < (entry.get("since") or 0) - 60:
        return 0
    drop_new_topic(name)
    bot.rename_topic(entry["thread"], topic_name(name, slug))
    log.info("the new-feature topic %s is %s/%s's now", entry["thread"], name, slug)
    return entry["thread"]


def new_worktrees(repo, since):
    """Slugs of the repository's features whose worktree appeared after since."""
    prefix = os.path.basename(repo) + "-"
    out = []
    for git in glob.glob(os.path.join(glob.escape(os.path.dirname(repo)),
                                      glob.escape(prefix) + "*", ".git")):
        slug = os.path.basename(os.path.dirname(git))[len(prefix):]
        try:
            born = os.stat(git).st_mtime
        except OSError:
            continue
        if born >= since - 60 and feature_dir(repo, slug):
            out.append(slug)
    return out


def check_new_topics(bot):
    # The feature a topic was made for takes it as soon as its worktree is
    # there, not at its first question: a start may ask nothing after the
    # name, and the topic would go on calling it "new feature".
    #
    # A start abandoned before the feature got a name leaves its topic: it
    # goes once nothing is asked in it any more.
    now = int(time.time())
    for name, entry in list((read().get("new_topics") or {}).items()):
        repo = repo_path(name)
        # A feature that already has a topic is not the one this was made for.
        born = [slug for slug in (new_worktrees(repo, entry.get("since") or 0) if repo else [])
                if not load_record(repo, slug).get("thread")]
        if born:
            feature_topic(bot, name, born[0])
            continue
        if now - (entry.get("since") or 0) < NEW_TOPIC_KEEP:
            continue
        if repo and pending_ask(ask_dir(repo)):
            continue
        if bot.delete_topic(entry.get("thread") or 0):
            drop_new_topic(name)
            log.info("the unused new-feature topic of %s is gone", name)


def open_channels():
    """[(key, directory)] of every channel with an open question."""
    found = []
    for repo in known_repos():
        name = os.path.basename(repo)
        for slug, channel in ask_channels(repo):
            if pending_ask(channel):
                found.append((channel_key(name, slug), channel))
    return found


def press_channel(name, message_id, repo=None):
    # The channel key a press on a question's message answers, or "" when the
    # message shows no open question. A question remembered before message ids
    # were kept has none to match, and a press then answers the repository's
    # channel, as every press did before.
    for key in repo_keys(name, repo):
        entry = get_shown(key, repo) or {}
        if message_id and entry.get("msg") == message_id:
            return key
    if (get_shown(name) or {}).get("legacy"):
        return name
    return ""


def press_answered(name, message_id, repo=None):
    # Whether the press is a second one on a question just answered here: its
    # message already shows the answer, and must neither be answered again nor
    # deleted as closed.
    return any(message_id and (get_shown(k, repo) or {}).get("answered") == message_id
               for k in repo_keys(name, repo))


def message_thread(msg):
    # The topic a message is in, 0 for the main chat. A message in the main
    # chat may carry a thread id too — that of the message it replies to — so
    # only is_topic_message counts.
    return (msg.get("message_thread_id") or 0) if msg.get("is_topic_message") else 0


def feature_records(repo, record=FEATURE_RECORD):
    """[slug] of the repository's features that have a record of the bot's —
    or, with record="state.json", every feature sclaude keeps a state for.

    By the name alone "app-admin-x" is as much feature "admin-x" of "app" as
    feature "x" of "app-admin"; the worktree's .git file, which names the
    repository it belongs to, settles it."""
    name = os.path.basename(repo)
    prefix = name + "-"
    own = os.path.join(os.path.realpath(repo), ".git", "worktrees") + os.sep
    found = []
    pattern = os.path.join(glob.escape(os.path.dirname(repo)), glob.escape(prefix) + "*",
                           ".sclaude", "local", "feature", record)
    for path in sorted(glob.glob(pattern)):
        tree = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        try:
            with open(os.path.join(tree, ".git"), encoding="utf-8") as fh:
                gitdir = fh.read().strip().partition("gitdir:")[2].strip()
        except OSError:
            continue
        # git 2.48+ may write it relative to the worktree.
        if not os.path.realpath(os.path.join(tree, gitdir)).startswith(own):
            continue
        found.append(os.path.basename(tree)[len(prefix):])
    return found


# One search serves a message: it reads every worktree's record, and one
# message asks for its topic several times (the text, the menu it draws).
TOPIC_FRESH = 5
_TOPIC_KEYS = {}


def topic_channel(thread):
    # The feature key whose topic this is, or "". A topic made from the menu
    # has no channel until the feature asks something, so the records in the
    # worktrees are what is searched.
    if not thread:
        return ""
    now = time.time()
    at, key = _TOPIC_KEYS.get(thread, (0.0, ""))
    if now - at < TOPIC_FRESH:
        return key
    key = ""
    for repo in known_repos():
        name = os.path.basename(repo)
        for slug in feature_records(repo):
            if load_record(repo, slug).get("thread") == thread:
                key = channel_key(name, slug)
                break
        if key:
            break
    # Kept found or not: save_record forgets it all, so a topic just adopted
    # is not missed for the seconds a "none" would stand.
    _TOPIC_KEYS[thread] = (now, key)
    return key


def check_topics(bot):
    # A finished feature's topic goes, with everything in it, and its channel
    # with it: at once when its worktree's removal left the mark. A channel whose
    # worktree went without one (removed by hand) goes after TOPIC_GRACE; its
    # topic cannot, its id having gone with the worktree.
    now = int(time.time())
    for repo in known_repos():
        name = os.path.basename(repo)
        for slug, channel in ask_channels(repo):
            if not slug:
                continue
            if pending_ask(channel):
                continue
            mark = os.path.join(channel, ENDED_MARK)
            if os.path.exists(mark):
                if feature_dir(repo, slug):
                    # A new feature under the same name, made before the bot
                    # came to the old one's mark: the old topic goes, the
                    # channel stays.
                    if end_feature(bot, name, slug, channel, mark):
                        try:
                            os.unlink(mark)
                        except OSError:
                            pass
                    continue
                if not end_feature(bot, name, slug, channel, mark):
                    continue
            elif feature_dir(repo, slug):
                continue
            else:
                try:
                    if now - os.stat(channel).st_mtime < TOPIC_GRACE:
                        continue
                except OSError:
                    continue
                log.warning("the worktree of %s/%s went without a clean-up — "
                            "its topic is left for deleting by hand", name, slug)
            if clear_channel(channel):
                log.info("the feature %s/%s is gone — its channel removed", name, slug)


def clear_channel(channel):
    # File by file rather than rmtree: a feature of the same name may have
    # begun while the topic was being deleted, and its question laid out here
    # (ask.json, and a mark set aside) keeps the directory. Everything else
    # goes, temporary leftovers of a killed writer included. Returns whether
    # the directory is gone.
    keep = ("ask.json",)
    closed = os.path.join(channel, CLOSED_DIR)
    # Notes not yet sent go with the feature: their topic is going too.
    notes = os.path.join(channel, notices.NOTES_DIR)
    for d in (closed, notes, channel):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            path = os.path.join(d, name)
            if d == channel and (name in keep or name.startswith(ENDED_MARK + "-")):
                continue
            if os.path.isfile(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
    for d in (closed, notes, channel):
        try:
            os.rmdir(d)
        except OSError:
            pass
    return not os.path.exists(channel)


def end_feature(bot, name, slug, channel, mark):
    # The worktree's removal left the record in the mark. Its last question's
    # message is settled first — it may stand in the main chat, where no topic
    # takes it away — then the topic goes. False while the topic may still be
    # there: the mark stays, and the next turn tries again.
    try:
        with open(mark, encoding="utf-8") as fh:
            record = json.load(fh) or {}
    except (OSError, ValueError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    entry = record.get("shown")
    if isinstance(entry, dict) and entry.get("msg") and not entry.get("thread"):
        # In the main chat only: one in the topic goes with it, below.
        # Only with its closed record: the mark is a copy taken when the
        # worktree went, and the bot may have settled that message since —
        # consuming the record — in which case it is history now, not to be
        # deleted.
        closed = closed_asks(channel).get(entry.get("id"))
        if closed:
            settle_ask(bot, name, entry, closed[1])
        else:
            # Without the record there is no telling whether the message is
            # still the question or already its answer: its text stays, its
            # buttons go — they would answer nothing either way.
            bot.unbutton(entry["msg"])
    if isinstance(entry, dict):
        record.pop("shown")
        # Whole or not at all: the mark holds the only copy of the topic id.
        tmp = "%s.%d" % (mark, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(record, fh)
            os.replace(tmp, mark)
        except OSError:
            pass
    thread = record.get("thread") or 0
    if thread and not bot.delete_topic(thread):
        try:
            age = time.time() - os.stat(mark).st_mtime
        except OSError:
            age = 0
        if age < TOPIC_DELETE_FOR:
            return False
        log.warning("the topic %s of %s/%s would not go for a day — left for "
                    "deleting by hand", thread, name, slug)
    if thread:
        forget_screen_place(thread)
    return True


# --- the feature's card ---------------------------------------------------------
#
# In a feature's topic there is nothing to choose: the topic is the feature. So
# the topic carries one card with everything about the feature — its step, its
# session, its links, its dev server and code-server — and the buttons act on it
# with no "which feature?" in between. The card is the topic's first message;
# "Menu" or /menu typed in the topic brings a fresh one to the bottom and the
# old one goes, so the topic holds one. It is not pinned: a pin in a topic of a
# private chat announces itself in the main chat, once per topic.
#
# Its buttons carry the feature's key when it fits Telegram's 64 bytes, and
# the topic they were pressed in otherwise, or the main chat's record of the
# card (card_data, card_press).

def dev_act(action, label, wt):
    # open, start or stop a feature's dev server.
    if action == "open":
        # A tab in the laptop's Chrome, which starts the browser if it is down.
        # A stopped feature needs nothing more: the request itself makes
        # sclaude-proxy start it.
        run("chrome-debug " + shlex.quote("http://%s.localhost:%d/" % (label, DEV_PORT)),
            timeout=60)
    elif action == "start":
        proxy_start(label)
    elif action == "stop":
        run("cd " + shlex.quote(wt) + " && sclaude dev --stop", timeout=90)


def feature_dev(repo, slug):
    """(label, port, running) of the feature's dev server, or None."""
    real = os.path.realpath(feature_wt(repo, slug))
    for label, wt, port, running in dev_features():
        if os.path.realpath(wt) == real:
            return label, port, running
    return None


def card_data(action, key):
    data = "fc:%s:%s" % (action, key)
    return data if len(data.encode("utf-8")) <= 64 else "fc:" + action


def card(name, slug, note="", in_topic=True, feats=None, config=None):
    """(text, keyboard) of the feature's card. The dev server, code-server and
    the phone gate are each looked at once: every look is a process or a
    socket, on the loop that answers getUpdates. config: tailscale's, when
    the caller draws several cards."""
    if ON_PAGE and feats is None:
        # Read once: the page's Continue is named by the step.
        feats, _ = features_of_name(name)
    text = feature_card(name, slug, feats)
    if in_topic and not ON_PAGE:
        # Whatever draws the topic's card — the loop, /menu, a press — says
        # which session state it shows, for check_card_states to compare.
        shown_state(name, slug)
    key = channel_key(name, slug)
    serve = serve_config() if config is None else config
    origin = gate_origin(serve)
    # On the page the buttons stand alone, and say what they act on: one to
    # a row, Continue first and named by where the feature is.
    named = (lambda chat, page: t(page) if ON_PAGE else t(chat))
    if ON_PAGE:
        step = next((r[1] for r in feats or [] if r[0] == slug), "")
        go = (t("page.finish") if " done" in step or step.startswith("all done")
              else t("page.continuestep", step=step) if step else t("page.continue"))
        rows = [[{"text": go, "callback_data": card_data("go", key)}],
                [{"text": t("page.actions"), "callback_data": card_data("acts", key)}]]
    else:
        rows = [[{"text": t("feat.continue"), "callback_data": card_data("go", key)},
                 {"text": t("feat.actions"), "callback_data": card_data("acts", key)}]]
    repo = repo_path(name)
    if repo and feature_dir(repo, slug):
        dev = feature_dev(repo, slug)
        if dev:
            label, _port, running = dev
            text += t("card.devpage", state=t("chrome.running") if running
                      else t("chrome.stopped")) if ON_PAGE else t("card.dev",
                      state=t("chrome.running") if running else t("chrome.stopped"),
                      link='<a href="%s/__sclaude/select?f=%s">%s</a>' % (
                          phone_origin(serve), label, t("card.phonelink")),
                      local="http://%s.localhost:%d" % (label, DEV_PORT))
            row = [{"text": named("chrome.open", "page.onlaptop"),
                    "callback_data": card_data("open", key)}]
            here = phone_button(origin, label)
            if ON_PAGE:
                for b in here:
                    b["text"] = t("page.onphone")
            row += here
            switch = ({"text": named("chrome.featstop", "page.devstop"),
                       "callback_data": card_data("stop", key)} if running else
                      {"text": named("chrome.start", "page.devstart"),
                       "callback_data": card_data("start", key)})
            if ON_PAGE:
                # A row each: where to open it, and starting or stopping it.
                rows += [[b] for b in row] + [[switch]]
            else:
                rows.append(row + [switch])
        else:
            text += t("card.nodev")
        # code-server opens the worktree itself with ?folder=, whichever
        # project it was started on.
        folder = "/?folder=" + urllib.parse.quote(feature_wt(repo, slug))
        last = []
        if ON_PAGE:
            # The page has code-server's own screen, on this feature's
            # worktree: nothing of it on the card.
            pass
        elif code_running():
            text += t("card.code", url=code_url() + folder, local="http://127.0.0.1:8080" + folder)
            last += code_app_button(origin, feature_wt(repo, slug))
        else:
            text += t("card.nocode")
            # In a topic the card is the topic's one message: starting it
            # there keeps the card in place.
            last.append({"text": t("card.codestart"), "callback_data": card_data("code", key)})
        last.append({"text": named("repo.refresh", "page.refresh"),
                     "callback_data": card_data("refresh", key)})
        rows.append(last)
    if note:
        text += "\n\n" + note
    # In a topic, with phone access on, the card's actions live in the Mini
    # App (an experiment): one button opens the menu page on this feature,
    # and what is done there leaves its line here.
    if in_topic and origin:
        return text, [[{"text": t("card.app"), "web_app": {
            "url": "%s/__sclaude/menu?f=%s" % (origin, urllib.parse.quote(key, safe=""))}}]]
    # Outside a topic — Threaded Mode off — the card stands where the feature
    # list was, and the way back to the list is needed.
    if not in_topic:
        rows.append([{"text": t("repo.torepos"), "callback_data": "repo:" + name}])
    return text, rows


def post_card(bot, name, slug):
    # A fresh card at the bottom of the feature's topic; the previous one
    # goes. Returns the card's message id, 0 when there is no topic.
    repo = repo_path(name)
    if not repo:
        return 0
    record = load_record(repo, slug)
    thread = record.get("thread") or 0
    if not thread:
        return 0
    text, keyboard = card(name, slug)
    msg = bot.send(text, keyboard, quiet=True, thread=thread)
    if not msg:
        return 0
    retire(bot, record.get("card") or 0)
    # Read again: card() has just written the state it shows.
    record = load_record(repo, slug)
    record["card"] = msg
    save_record(repo, slug, record)
    return msg


def open_card(bot, name, slug):
    # The feature's card in its topic, the topic made if need be. Returns
    # whether it is there — False without Threaded Mode or a worktree.
    # A topic made just now already opens with its card.
    # None when the topic is to be had but the network failed: the card is
    # not drawn outside the topic for that.
    repo = repo_path(name)
    had = bool(repo and load_record(repo, slug).get("thread"))

    key = channel_key(name, slug)

    def missed():
        return None if topic_pending(repo, slug, CARD_TRIED, key) else False

    if not feature_topic(bot, name, slug):
        return missed()
    CARD_TRIED.pop(key, None)
    # A new topic opens with its card — unless that send failed.
    if not had and load_record(repo, slug).get("card"):
        return True
    if post_card(bot, name, slug):
        return True
    if not topic_lost(bot):
        return None
    # The topic was deleted by hand: a new one, which opens with its card.
    if not feature_topic(bot, name, slug, renew=True):
        return missed()
    return True if load_record(repo, slug).get("card") else None


def note_topic(bot, name, slug):
    """Where a feature's notes go: its topic; the main chat (0) only when
    the chat has no topics; None while neither — a topic not made yet, the
    network, a feature whose worktree has gone."""
    repo = repo_path(name)
    if not repo or not feature_dir(repo, slug):
        return None
    thread = feature_topic(bot, name, slug)
    if thread:
        return thread
    return 0 if time.time() < (read().get("topics_off_until") or 0) else None


def redraw_cards(bot):
    # Every card in a feature's topic, drawn again: what it offers depends on
    # phone access (one button to the app, or the actions themselves), and a
    # card left as it was offers what does not work.
    serve = serve_config()
    for repo in known_repos():
        name = os.path.basename(repo)
        feats = None
        for slug in feature_records(repo):
            msg = load_record(repo, slug).get("card") or 0
            if not msg or not feature_dir(repo, slug):
                continue
            if feats is None:
                feats, _ = features_of_name(name)
            bot.edit(msg, *card(name, slug, feats=feats, config=serve))


def shown_state(name, slug, state=None):
    """Record the session state a chat card of the feature now shows."""
    repo = repo_path(name)
    if not repo or not feature_dir(repo, slug):
        return
    if state is None:
        state = session_state(feature_session(repo, slug)[0])
    record = load_record(repo, slug)
    if (record.get("card_state") or "") != state:
        record["card_state"] = state
        save_record(repo, slug, record)


# How often the cards in the topics are checked against their sessions.
CARD_LOOK = 60
_CARD_LOOKED = [0.0]


def check_card_states(bot, now=None):
    """A topic's card drawn again when its session changed: none, running,
    waiting for the person, idle. A card is a message, drawn once; left as
    it was it says "no session is open" beside one working."""
    now = time.time() if now is None else now
    if now - _CARD_LOOKED[0] < CARD_LOOK:
        return
    _CARD_LOOKED[0] = now
    # Unanswered, every session would read as none and every card turn to
    # "no session is open" for a minute.
    agents()
    if not _AGENTS["ok"]:
        return
    # The one answer serves the whole pass: a later call past AGENTS_FRESH,
    # mid-way, could fail and read every session as none.
    _AGENTS["at"] = float("inf")
    try:
        redraw_changed_cards(bot)
    finally:
        _AGENTS["at"] = time.time()


def redraw_changed_cards(bot):
    serve = None              # tailscale's, read once, and only if a card is drawn
    for repo in known_repos():
        name = os.path.basename(repo)
        feats = None
        for slug in feature_records(repo):
            if not feature_dir(repo, slug):
                continue
            record = load_record(repo, slug)
            msg = record.get("card") or 0
            if not msg:
                continue
            session, _step = feature_session(repo, slug)
            state = session_state(session)
            if state == (record.get("card_state") or ""):
                continue
            if feats is None:
                feats, _ = features_of_name(name)
            if serve is None:
                serve = serve_config()
            if not bot.edit(msg, *card(name, slug, feats=feats, config=serve)):
                # Not drawn: what the card shows is still the old state, and
                # the next look tries again.
                shown_state(name, slug, record.get("card_state") or "")
            else:
                shown_state(name, slug, state)


def redraw_screens(bot):
    # The menu screen of each place, drawn again as the chat's menu: offline
    # it is the hold and the way to turn access on, online the way to the
    # app — and an old one would offer the other.
    for place, msg in (read().get("screens") or {}).items():
        if msg:
            bot.edit(msg, *chat_menu(int(place)))


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
    redraw_screens(bot)
    redraw_cards(bot)
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
    out = run("tailscale serve status --json", timeout=10)
    # Answered means JSON: run() gives the error's text or its own words
    # for one that failed — tailscaled not up yet — never an empty string.
    config = json_in(out)
    if config is None:
        return
    BOOT_LOOKED[0] = True
    if not gate_origin(config, False):
        return
    if (read().get("phone_on_at") or 0) >= boot_time():
        return
    run(FUNNEL_OFF, timeout=30)
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
    config = serve_config()
    on = bool(gate_origin(config, True, True))
    if PHONE_SEEN[0] is None:
        PHONE_SEEN[0] = on
    elif on != PHONE_SEEN[0]:
        phone_changed(bot, on)
    wait = read().get("phone_wait")
    if wait and (on or not gate_origin(config, False)):
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
        if not retire(bot, warn):
            trail(warn, 0)
        with locked() as st:
            if st.get("warn_message_id") == warn:
                st["warn_message_id"] = 0
    trail(message_id, expires)


def sweep_trail(bot, now, everything=False):
    # The chat holds no message about sleep that is no longer true: those past
    # their deadline go, and with a new warning every earlier one goes.
    trail_now = read().get("sleep_trail") or []
    gone = [e for e in trail_now if everything or e[1] <= now]
    if not gone:
        return
    # One the network kept is tried again on the next turn.
    done = [e for e in gone if retire(bot, e[0])]
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
        if not retire(bot, msg):
            trail(msg, now)     # the network's: tried again next turn
    elif until == warned:
        return
    elif until > warned:
        bot.edit(msg, t("sleep.extended", at=local_for_lang(data.get("until_local"))))
        trail(msg, until)
    elif data.get("decision") == "sleep":
        bot.edit(msg, t("sleep.accepted"))
        trail(msg, now + IDLE_SLEPT_KEEP)
    elif not retire(bot, msg):
        trail(msg, now)
    with locked() as st:
        if st.get("warn_message_id") == msg:
            st["warn_message_id"] = 0


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
    text = t("sleep.warn", at=local_for_lang(data.get("until_local")) or "?",
             min=left, why=sleep_reason(data, now))
    msg_id = bot.send(text, warn_keyboard(until))
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
    log.info("the warning was sent for %s", data.get("until_local"))


# --- start-up ----------------------------------------------------------------

def load_env():
    token = os.environ.get("KEEPAWAKE_BOT_TOKEN", "").strip()
    chat = os.environ.get("KEEPAWAKE_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit("keepawake: no KEEPAWAKE_BOT_TOKEN or KEEPAWAKE_CHAT_ID "
                 "(see ~/.config/keepawake/env)")

    # A bot's token is full access to the bot. Working silently with loose
    # permissions on the secrets file is unwise.
    env_file = os.path.expanduser("~/.config/keepawake/env")
    if os.path.exists(env_file):
        mode = os.stat(env_file).st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            sys.exit("keepawake: %s is readable by the group or everyone — chmod 600" % env_file)
    return token, chat


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    token, chat = load_env()
    bot = Bot(token, chat)
    handler = Handler(bot)

    def stop(signum, frame):
        # Without this a systemctl restart would leave a long getUpdates
        # hanging.
        bot.stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    saved = read().get("lang")
    if saved:
        set_lang(saved)
    log.info("the daemon has started, chat_id=%s, language=%s", chat, current())

    try:
        phone_off_after_boot()
    except Exception as exc:
        log.warning("phone access after a boot: %s", exc)

    # The commands are a cheap second route to the menu: typed by hand when the
    # buttons are out of reach. They do not occupy the button in the input box
    # while doing so.
    bot.commands()
    bot.menu_button()
    bot.describe()
    # What they were set up for: a change from here on is check_phone's,
    # even one made before the loop's first look.
    PHONE_SEEN[0] = bool(gate_origin())

    # If we were restarted by a button, report it into that same message. That
    # same message carries the reply keyboard: setting it with a separate "I have
    # started" means writing to the chat on every restart of the daemon, and it
    # restarts both by a button in the menu and after a reboot. Telegram has no
    # silent way of setting a keyboard — it only arrives with a message.
    try:
        if not report_restart(bot):
            ensure_anchor(bot)
    except Exception as exc:
        log.warning("the restart report: %s", exc)

    backoff = 1

    while not bot.stopped:
        try:
            out = bot.call("getUpdates", http_timeout=POLL_TIMEOUT + 10,
                           offset=bot.offset, timeout=POLL_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                # A second instance on the same token: two daemons would for
                # ever intercept each other's updates, and carrying on quietly
                # will not do.
                sys.exit("keepawake: a second instance of the daemon is running (HTTP 409)")
            if exc.code == 401:
                sys.exit("keepawake: wrong token (HTTP 401)")
            log.warning("HTTP %s, pausing %d s", exc.code, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue
        except Exception as exc:
            log.warning("network: %s, pausing %d s", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue

        backoff = 1
        for upd in out.get("result") or []:
            # We move the offset BEFORE handling: otherwise the update the
            # handler died on would arrive for ever and bring the daemon down for
            # ever. Losing one press is better than looping.
            bot.offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    msg = upd["message"]
                    if (msg.get("chat") or {}).get("id") != bot.chat_id:
                        log.warning("a foreign chat: %s", (msg.get("chat") or {}).get("id"))
                        continue
                    remember_lang(msg.get("from"))
                    bot.thread = message_thread(msg)
                    handler.message(msg)
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
                    if chat_id != bot.chat_id:
                        log.warning("a foreign chat in the callback: %s", chat_id)
                        continue
                    remember_lang(cq.get("from"))
                    bot.thread = message_thread(cq.get("message") or {})
                    handler.callback(cq)
            except Exception as exc:
                log.exception("handling the update: %s", exc)
            finally:
                bot.thread = 0

        try:
            check_warning(bot)
        except Exception as exc:
            log.exception("checking the warning: %s", exc)

        try:
            check_idle_hold(bot)
        except Exception as exc:
            log.exception("checking forgotten holders: %s", exc)

        # An orchestrator's question waits for the person, not the other way
        # round: the later it reaches the chat, the longer the step stands. A
        # turn here is the same 25 seconds of long-polling as everything else,
        # and that is an order of magnitude faster than walking to the laptop.
        try:
            check_asks(bot)
        except Exception as exc:
            log.exception("checking sclaude's questions: %s", exc)

        # Where a feature's review stands, after each round: to its topic.
        try:
            notices.check(bot, [(os.path.basename(repo), slug, channel)
                                for repo in known_repos()
                                for slug, channel in ask_channels(repo) if slug],
                          lambda name, slug: note_topic(bot, name, slug), log,
                          at_terminal=lambda pid: at_terminal({"pid": pid}),
                          shown=channel_context,
                          lost=lambda name, slug: topic_lost(bot)
                          and feature_topic(bot, name, slug, renew=True))
        except Exception as exc:
            log.exception("sending sclaude's notes: %s", exc)

        try:
            check_awaiting(bot)
        except Exception as exc:
            log.exception("sweeping the time question: %s", exc)

        try:
            check_phone(bot)
        except Exception as exc:
            log.exception("checking phone access: %s", exc)

        try:
            check_topics(bot)
            check_new_topics(bot)
        except Exception as exc:
            log.exception("checking the feature topics: %s", exc)

        try:
            check_card_states(bot)
        except Exception as exc:
            log.exception("checking the cards' sessions: %s", exc)

    log.info("the daemon has stopped")


if __name__ == "__main__":
    main()
