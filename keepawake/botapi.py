# keepawake's Telegram bot — telegram's Bot API: the client with its retries,
# and the bot's profile.
#
# Part of the bot that keepawake/telegramd.py runs.

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from keepawake.i18n import STRINGS, current, t
from keepawake.state import locked, read
from keepawake import handling, menus, phone_access, topics, tg_journal, widgets


API = "https://api.telegram.org/bot%s/%s"

# A long getUpdates: it holds the connection while there are no updates and
# returns control as soon as something arrives.
POLL_TIMEOUT = 25

# The backoff ceiling. The network on a laptop drops regularly — that is normal,
# not a reason to die: restarting the daemon loses the offset and creates a
# spike of requests.
BACKOFF_MAX = 60

log = logging.getLogger("keepawake")

# The times a line counts ("4m 05s", "12s"): a message said again with only
# its time grown is the same message (Bot.send).
DURATION = re.compile(r"\b\d+m \d{2}s\b|\b\d+s\b")


# How long what a message was last edited to is trusted (Bot.unchanged):
# another process — the menu page, sclaude-notify — may have edited it
# since, and an edit back to this would then be skipped.
EDIT_TRUST = 600

# How long a plain message to a topic stands for a repeat of it (Bot.send):
# the same line twice in a burst is one, the same line an hour later is news.
SAID_WINDOW = 120


def same_text(text):
    """text as Bot.send compares it with the last message sent to a topic."""
    return DURATION.sub("⌚", text or "")


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
        # The last plain message sent to each topic, {thread: (same_text,
        # quiet, message id, when)}, and what each message was last edited to, {message
        # id: (kind, what and keyboard, when)}: the same again is not sent
        # (send, edit, caption, widget_data). In memory: after a restart the
        # first edit goes, and Telegram's "message is not modified" answers
        # it.
        self.said = {}
        self.shown = {}

    # --- transport ----------------------------------------------------------

    def call(self, method, http_timeout=15, **params):
        # Every call about a feature's topic goes into its journal
        # (tg_journal), a refused one with what Telegram said.
        try:
            out = self._call(method, http_timeout, params)
        except Exception as exc:
            tg_journal.bot_call(method, params, error=getattr(exc, "telegram", "") or exc)
            raise
        tg_journal.bot_call(method, params, out)
        return out

    def _call(self, method, http_timeout, params):
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
            params["reply_markup"] = menus.unstyled(params["reply_markup"])
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
            out = json.load(resp)
        # Here rather than in send: every way a message reaches a topic passes
        # through, the retry without colours included.
        if method.startswith("send") and params.get("message_thread_id"):
            topics.remember_in_topic(params["message_thread_id"],
                              (out.get("result") or {}).get("message_id"))
        return out

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
        #
        # What the bot sends to a topic by itself (thread named), without
        # buttons, is not sent again when it says what the topic's last
        # such message said, its times aside, as quietly, within SAID_WINDOW:
        # the feed's lines came twice. A louder copy goes: a warning that
        # follows the quiet line it repeats must sound.
        # Not a reply to the person (thread None: they asked again), and not
        # a message with buttons — a card is sent anew before the old one is
        # deleted, and the old one's id would come back.
        plain = thread is not None and not keyboard
        if plain:
            last = self.said.get(thread)
            if (last and last[:2] == (same_text(text), bool(quiet))
                    and time.time() - last[3] < SAID_WINDOW):
                log.info("not sent again to topic %s: %s", thread, text[:80])
                return last[2]
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
            msg = (out.get("result") or {}).get("message_id", 0)
            target = self.thread if thread is None else thread
            # Anything else said in the topic since makes a repeat new again.
            if plain and msg:
                self.said[thread] = (same_text(text), bool(quiet), msg, time.time())
            else:
                self.said.pop(target, None)
            return msg
        except Exception as exc:
            self.last_error = getattr(exc, "telegram", "") or str(exc).lower()
            log.warning("did not send: %s %s", exc, getattr(exc, "telegram", ""))
            return 0

    # --- widgets (widgets.py) -----------------------------------------------

    def send_widget(self, html, data, caption, keyboard=None, quiet=False, thread=None,
                    above=False):
        # A message with an HTML widget, allowed to ask the bot. The caption
        # is what the chat list, a notification and a client without widgets
        # show. Telegram protects every widget's content by itself: no
        # forwarding, and on the phone no screenshots while one is on screen.
        try:
            out = self.call("sendWidget", chat_id=self.chat_id, html=html,
                            chat_data=data or None, caption=caption, parse_mode="HTML",
                            # above: the caption is what the widget answers,
                            # a question, read before the buttons.
                            show_caption_above_media="true" if above else None,
                            allow_queries="true",
                            message_thread_id=(self.thread if thread is None
                                               else thread) or None,
                            disable_notification="true" if quiet else None,
                            reply_markup={"inline_keyboard": keyboard} if keyboard else None)
            self.last_error = ""
            self.said.pop(self.thread if thread is None else thread, None)
            return (out.get("result") or {}).get("message_id", 0)
        except Exception as exc:
            self.last_error = getattr(exc, "telegram", "") or str(exc).lower()
            log.warning("the widget did not send: %s %s", exc, getattr(exc, "telegram", ""))
            if widgets.REFUSED in self.last_error:
                # Telegram does not take widgets from bots now: the switch
                # goes to messages only, so the caller's next try (the sleep
                # warning retries every turn) goes as a plain message rather
                # than failing for good. The person turns it back on in the
                # settings once Telegram allows widgets again.
                with locked() as st:
                    st["widgets"] = False
                log.warning("Telegram refuses widgets: sending messages only")
            return 0

    def widget_data(self, message_id, data):
        # The widget's new state: an open one redraws at once, silently.
        # Whether it went through; the same state again counts as done.
        if self.unchanged(message_id, "data", data):
            return True
        try:
            self.call("editMessageWidgetData", chat_id=self.chat_id,
                      message_id=message_id, chat_data=data)
            self.last_error = ""
            self.edited(message_id, "data", data)
            return True
        except Exception as exc:
            # Kept: "message to edit not found" says the widget is gone, which
            # a timeout does not (processes.py).
            self.last_error = getattr(exc, "telegram", "") or str(exc).lower()
            if "not modified" in self.last_error:
                return True
            log.warning("the widget's state did not change: %s %s", exc,
                        getattr(exc, "telegram", ""))
            return False

    def caption(self, message_id, text, keyboard=None):
        # A widget's caption, which a state change leaves as it was.
        if self.unchanged(message_id, "caption", text, keyboard):
            return True
        try:
            self.call("editMessageCaption", chat_id=self.chat_id,
                      message_id=message_id, caption=text, parse_mode="HTML",
                      reply_markup={"inline_keyboard": keyboard} if keyboard else None)
            self.edited(message_id, "caption", text, keyboard)
            return True
        except Exception as exc:
            if "not modified" in (getattr(exc, "telegram", "") or str(exc)).lower():
                return True
            log.warning("the caption did not change: %s", exc)
            return False

    def answer_widget(self, query_id, data=None):
        # Every query is answered, within 15 seconds, or the widget shows a
        # timeout; the data reaches only the widget that asked.
        try:
            self.call("answerWidgetQuery", widget_query_id=query_id, data=data,
                      http_timeout=10)
        except Exception as exc:
            log.warning("answerWidgetQuery: %s %s", exc, getattr(exc, "telegram", ""))

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
            self.said.pop(self.thread, None)
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
            online = bool(phone_access.gate_origin())
        shown = handling.OFFLINE_COMMANDS if not online else [
            name for name in handling.COMMANDS if name != "phone"]
        for code, half in profile_halves().items():
            try:
                self.call("setMyCommands", language_code=code, commands=[
                    {"command": name, "description": STRINGS[key][half]}
                    for name, (_method, key) in handling.COMMANDS.items()
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
        origin = phone_access.gate_origin()
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

    def unchanged(self, message_id, kind, what, keyboard=None):
        """Whether the message was last edited to exactly this (edited):
        then the edit is not sent — a card redrawn each minute as it was is
        a call for nothing."""
        last = self.shown.get(message_id) if message_id else None
        return bool(last) and time.time() - last[2] < EDIT_TRUST and last[:2] == (
            kind, json.dumps([what, keyboard], sort_keys=True, ensure_ascii=False))

    def edited(self, message_id, kind, what, keyboard=None):
        self.shown[message_id] = (kind, json.dumps([what, keyboard], sort_keys=True,
                                                   ensure_ascii=False), time.time())
        if len(self.shown) > 500:
            # The oldest go: a long-lived bot edits many messages.
            for old in sorted(self.shown, key=lambda m: self.shown[m][2])[:100]:
                del self.shown[old]

    def edit(self, message_id, text, keyboard=None):
        # Whether the edit went through.
        if self.unchanged(message_id, "text", text, keyboard):
            return True
        try:
            self.call("editMessageText", chat_id=self.chat_id,
                      message_id=message_id, text=text, parse_mode="HTML",
                      reply_markup={"inline_keyboard": keyboard} if keyboard else None)
            self.edited(message_id, "text", text, keyboard)
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
            # Telegram's own words, not only the status: a 400 alone does not
            # say whether the topic stayed unmade.
            log.warning("no topic was made: %s %s", exc, self.last_error)
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
        # Its messages first: in a private chat the topic goes, but what was
        # said in it stays in the chat's "All" view.
        if not topics.clear_topic_messages(self, thread):
            return False
        try:
            self.call("deleteForumTopic", chat_id=self.chat_id,
                      message_thread_id=thread)
            return True
        except Exception as exc:
            log.warning("the topic was not deleted: %s %s", exc, getattr(exc, "telegram", ""))
            # Gone already, by hand, or topics are off: nothing left to
            # delete. Any other failure is tried again on the next turn; the
            # orchestrator clears a mark left a week (io.sh).
            reason = getattr(exc, "telegram", "")
            return any(w in reason for w in topics.TOPIC_GONE)

    def unbutton(self, message_id, keyboard=None):
        # The message's text stays, its buttons go — or become keyboard.
        self.shown.pop(message_id, None)
        try:
            self.call("editMessageReplyMarkup", chat_id=self.chat_id,
                      message_id=message_id,
                      reply_markup={"inline_keyboard": keyboard} if keyboard else None)
        except Exception as exc:
            log.warning("the buttons stayed: %s", exc)

    def delete(self, message_id):
        # Returns whether the message is gone. Telegram refuses a bot's delete
        # once the message is 48 hours old — see retire for what happens then.
        if not message_id:
            return False
        # Gone, it is neither the topic's last message nor one to edit.
        self.shown.pop(message_id, None)
        for thread, last in list(self.said.items()):
            if last[2] == message_id:
                del self.said[thread]
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
