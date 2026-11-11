# keepawake's Telegram bot — handling what the person sends: commands, typed
# text and button presses.
#
# Part of the bot that keepawake/telegramd.py runs.

import collections
import logging
import os
import shlex
import subprocess
import threading
import time

from keepawake import docs, review_keys, state
from keepawake.i18n import DEFAULT, current, set_lang, t
from keepawake.state import HOLD_SECONDS, locked, read
from keepawake import asks, card_view, holding, menus, phone_access, project_config, repos, services, sessions, shell, sleep_warning, status_report, topics, widgets
from keepawake import menu_widget


log = logging.getLogger("keepawake")


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


class _Unbuttons(object):
    # The keyboard edits a press makes, held until the press is answered.
    def __init__(self):
        self.edits = []

    def unbutton(self, message_id, keyboard=None):
        self.edits.append((message_id, keyboard))

    def flush(self, bot):
        for message_id, keyboard in self.edits:
            bot.unbutton(message_id, keyboard)


class Handler(object):
    def __init__(self, bot):
        self.bot = bot

    def message(self, msg):
        text = (msg.get("text") or "").strip()
        now = int(time.time())
        # The topic it was typed in, and the feature that topic is, looked up
        # once: the lookup reads every worktree's record.
        thread = topics.message_thread(msg)
        fkey = topics.topic_channel(thread) if thread else ""

        # We are waiting for a time for "stay awake until" — but a command
        # always beats the wait, otherwise there would be no way out of a
        # dialogue begun by mistake except the right answer. And only where it
        # was asked: text typed in a feature's topic meanwhile is that
        # feature's, an answer to its question.
        data = read()
        if (text and data.get("awaiting") == "awake_until"
                and (data.get("awaiting_thread") or 0) == thread
                and not text.startswith("/") and not menus.is_menu_button(text)):
            until_ts = holding.parse_hhmm(text, now)
            if not until_ts:
                log.warning("\"stay awake until\": the time was not parsed (%r)", text)
                # We ask again with the box ready too: the person has already
                # missed the format, and making them open the keyboard by hand a
                # second time is exactly what the buttons save them from.
                #
                # The previous box goes: two prompts for one time is the same
                # question twice.
                menus.retire(self.bot, (read().get("awaiting_ids") or {}).get("prompt"))
                self.bot.delete(msg.get("message_id") or 0)
                prompt = self.bot.ask(t("awake.badtime"), t("awake.hint"))
                with locked() as st:
                    st["awaiting_ids"] = dict(st.get("awaiting_ids") or {}, prompt=prompt)
                return
            until = holding.hold_for(until_ts - now, now)
            log.info("\"stay awake until\" %s: deadline until %s", text, until)
            # The question becomes its answer, and the typed time goes with the
            # input box, as an answer to sclaude's question does.
            said = holding.settle_awaiting(self.bot, t("extended.plain", at=status_report.local_for_lang(until)))
            sleep_warning.said_sleep(self.bot, said, read().get("until_ts") or 0)
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
        if text and not text.startswith("/") and not menus.is_menu_button(text):
            # Typed in a feature's topic, the text answers that feature's
            # question; typed in the main chat, it answers when one question in
            # all is open — with two, there is no telling which was meant.
            # In the main chat, only the questions shown in it: a feature's
            # question in its topic is not what text typed here answers.
            opened = topics.open_channels()
            if thread:
                # The feature's own, or a question shown in this topic: the
                # repository's new-feature topic has no feature key, and its
                # "Feature name:" is answered there.
                waiting = [(k, d) for k, d in opened if (fkey and k == fkey)
                           or (asks.get_shown(k) or {}).get("thread") == thread]
            else:
                # The repository's own questions, and a feature's only once
                # shown here (no topic to be had): one not shown yet is on its
                # way to its topic.
                waiting = []
                for k, d in opened:
                    entry_k = asks.get_shown(k)
                    # Shown in a topic — the repository's own too, in its
                    # new-feature topic — it is answered there.
                    if entry_k and entry_k.get("thread"):
                        continue
                    if not asks.split_key(k)[1] or entry_k:
                        waiting.append((k, d))
            # The question the text replies to, if it replies to one of them;
            # otherwise, with several, the one on screen here — a question not
            # shown yet, or answered by a button, is not one the person sees.
            to = (msg.get("reply_to_message") or {}).get("message_id") or 0
            replied = [(k, d) for k, d in waiting
                       if to and (asks.get_shown(k) or {}).get("msg") == to]
            if replied:
                waiting = replied
            elif len(waiting) > 1:
                on_screen = [(k, d) for k, d in waiting if (asks.get_shown(k) or {}).get("msg")]
                # A reply to some other message names none of them: which?
                if len(on_screen) != 1 or to:
                    # None on screen: closed by a button, unless one is still
                    # on its way.
                    coming = any(not asks.get_shown(k) for k, _ in waiting)
                    self.bot.send(t("ask.which" if on_screen
                                    else "ask.notyet" if coming else "ask.gone"))
                    return
                waiting = on_screen
            if not thread and not waiting and opened:
                # Pointed to a topic only when a question is shown in one: one
                # not shown yet may still come here, if no topic is to be had.
                intopic = any((asks.get_shown(k) or {}).get("thread") for k, _ in opened)
                self.bot.send(t("ask.intopic" if intopic else "ask.notyet"))
                return
            if len(waiting) == 1:
                key, channel = waiting[0]
                name = asks.split_key(key)[0]
                question = asks.pending_ask(channel)
                # As with a press: the text answers the question the chat
                # shows, not one laid out since that the bot has not shown yet.
                # And only a shown one: before the bot's turn shows a question,
                # nobody has seen it to answer it.
                entry = asks.get_shown(key) or {}
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
                        and text.strip().isdigit() and not asks.option_in_range(question, text):
                    self.bot.delete(msg.get("message_id") or 0)
                    self.bot.send(t("ask.nooption"))
                    return
                if not asks.answer_ask(channel, text, (question or {}).get("id")):
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
                if (form.startswith("yn") and text.strip().lower() not in asks.YES_WORDS + asks.NO_WORDS) \
                        or (form.startswith("pick:") and not asks.option_in_range(question, text)):
                    self.bot.delete(msg.get("message_id") or 0)
                    return
                entry = asks.forget_ask(key, (asks.get_shown(key) or {}).get("msg"))
                if entry:
                    asks.show_answered(self.bot, name, dict(question or {}, **entry), text)
                    self.bot.delete(msg.get("message_id") or 0)
                else:
                    self.bot.send(asks.answered_text(name, question, text))
                return

        # Any command clears an open question about the time: the person has
        # gone elsewhere, and there is no longer anything to expect a "23:30"
        # from them for. The "Menu" button ranks with the commands here — it is
        # the declared way to cancel.
        if (text.startswith("/") or menus.is_menu_button(text)) and read().get("awaiting"):
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
        if fkey and (menus.is_menu_button(text) or not text.startswith("/")
                     or name in ("menu", "start")):
            if card_view.post_card(self.bot, *asks.split_key(fkey)):
                self.bot.delete(msg.get("message_id") or 0)
                return

        # A command or "Menu" has done its job once its screen is up; left in
        # the chat, each is one more line between the screens.
        if menus.is_menu_button(text) or text.startswith("/"):
            self.bot.delete(msg.get("message_id") or 0)
        if menus.is_menu_button(text):
            return self.cmd_menu()
        if not text.startswith("/"):
            self.screen(t("cmd.unknown"), menus.chat_menu(self.bot.thread)[1])
            return
        found = COMMANDS.get(name)
        if not found:
            self.screen(t("cmd.unknown"), menus.chat_menu(self.bot.thread)[1])
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
            holding.settle_awaiting(self.bot)
        elif old and old != message_id:
            menus.retire(self.bot, old)

    def result(self, message_id, text):
        # A menu has been answered: a button did something rather than lead
        # elsewhere. The screen becomes what was done, without buttons — a
        # line of history, as an answered question is — and the next screen
        # leaves it be.
        self.bot.edit(message_id, text)
        holding.forget_screen(message_id)

    def cmd_menu(self, now=0):
        # In the main chat, with widgets on, the whole menu as a widget, which
        # works with phone access off; a topic's menu is its feature's card.
        if widgets.enabled() and not self.bot.thread:
            try:
                if menu_widget.open_menu(self.bot, now):
                    return
            except Exception as exc:
                log.exception("the menu widget: %s", exc)
        self.screen(*menus.chat_menu(self.bot.thread))

    def cmd_status(self, now=0):
        self.bot.send(status_report.status_text())

    def cmd_extend(self, now=0):
        until = holding.hold_for(HOLD_SECONDS, now or int(time.time()))
        log.info("the /extend command: deadline until %s", until)
        sleep_warning.said_sleep(self.bot, self.bot.send(t("extended.plain", at=status_report.local_for_lang(until))),
                   read().get("until_ts") or 0)

    def cmd_sleep(self, now=0):
        holding.release_hold(now or int(time.time()))
        log.info("the /sleep command: hold released, refusal for %d min",
                 state.REFUSAL_HOLDS // 60)
        sleep_warning.said_sleep(self.bot, self.bot.send(t("awake.released")),
                   (now or int(time.time())) + sleep_warning.IDLE_SLEPT_KEEP)

    def cmd_awake(self, now=0):
        self.screen(holding.keepawake_text(), holding.awake_keyboard())

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
        if phone_access.gate_origin():
            return self.cmd_menu(now)
        if phone_access.gate_origin(None, False):
            # Already on, the address not yet published: the waiting
            # message changes when it is.
            self.bot.send(t("svc.phonestill"))
            return
        on, out = phone_access.phone_on()
        if not on:
            self.bot.send(t("chrome.gatefail", log=status_report.escape(out[-1500:])))
            return
        log.info("phone access turned on by /phone")
        sleep_warning.wait_for_phone(self.bot.send(t("svc.phonewait")))

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
            holding.let_go(message_id)
            return self.decision(data_raw, message_id, cid, now)

        # The review's keys on a topic's message (review_keys.py): the toast
        # says what the press did, or that the review it was for has ended.
        # The answer goes before the message's buttons are redrawn, as every
        # answer here does: an edit on a slow network outlasts the seconds
        # Telegram gives the press, and the toast is then never shown.
        if data_raw.startswith("rv:"):
            later = _Unbuttons()
            toast = review_keys.press(later, asks.feature_channels(), message_id, data_raw)
            self.bot.answer(cid, toast or None)
            later.flush(self.bot)
            return

        # The answer first thing, otherwise a spinner turns on the phone.
        self.bot.answer(cid)
        holding.let_go(message_id)

        if data_raw == "menu_extend":
            self.bot.edit(message_id, holding.keepawake_text(), holding.awake_keyboard())
        elif data_raw.startswith("awake:"):
            seconds = int(data_raw.split(":", 1)[1])
            until = holding.hold_for(seconds, now)
            log.info("the extend button for %d min: deadline until %s", seconds // 60, until)
            # The menu has done its job: it becomes the line saying so.
            self.result(message_id, t("extended.plain", at=status_report.local_for_lang(until)))
            sleep_warning.said_sleep(self.bot, message_id, read().get("until_ts") or 0)
        elif data_raw == "awake_forever":
            until = holding.hold_for(holding.FOREVER_SECONDS, now)
            log.info("the \"stay awake\" button: indefinite, deadline until %s", until)
            self.result(message_id, t("awake.forever.ok"))
            sleep_warning.said_sleep(self.bot, message_id, read().get("until_ts") or 0)
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
                menus.retire(self.bot, old)
            prompt = self.bot.ask(t("awake.ask.now"), t("awake.hint"))
            with locked() as st:
                st["awaiting_ids"] = {"menu": message_id, "prompt": prompt}
        elif data_raw == "awake_release":
            # The same as "Let it sleep" in the warning.
            holding.release_hold(now)
            # We clear an open question about the time: the person has left it
            # for a neighbouring button, and there is nothing left to expect an
            # answer for.
            if read().get("awaiting"):
                with locked() as st:
                    st["awaiting"] = ""
            log.info("the \"let it sleep\" button: hold released, refusal for %d min",
                     state.REFUSAL_HOLDS // 60)
            self.result(message_id, t("awake.released"))
            sleep_warning.said_sleep(self.bot, message_id, now + sleep_warning.IDLE_SLEPT_KEEP)
        elif data_raw == "menu_status":
            self.result(message_id, status_report.status_text())
        elif data_raw == "menu_chrome":
            self.bot.edit(message_id, *services.chrome_screen())
        elif data_raw == "menu_code":
            self.bot.edit(message_id, services.code_text(), services.code_keyboard())
        elif data_raw in ("code_start", "code_restart", "code_stop"):
            verb = {"code_start": "start", "code_restart": "restart",
                    "code_stop": "stop"}[data_raw]
            shell.run("systemctl --user %s code-server.service" % verb)
            self.result(message_id, services.code_text())
        elif data_raw == "menu_services":
            self.bot.edit(message_id, t("svc.title"), menus.services_keyboard())
        elif data_raw == "menu_back":
            # Returning to the menu also cancels an open question about the
            # time: otherwise the bot would silently swallow the next ordinary
            # message, taking it for an answer.
            if read().get("awaiting"):
                with locked() as st:
                    st["awaiting"] = ""
            self.bot.edit(message_id, *menus.chat_menu(self.bot.thread))
        elif data_raw == "noop":
            pass          # a row caption, not a button
        elif data_raw == "idle_keep":
            # We do nothing — but mark that we asked, so that the next question
            # comes in an hour rather than at once.
            with locked() as st:
                st["idle_asked_ts"] = now
            self.bot.edit(message_id, t("idle.kept"))
        elif data_raw == "idle_sleep":
            holding.release_hold(now)
            # We mark that we asked: otherwise the next question about
            # forgotten holders would come immediately rather than in an hour.
            with locked() as st:
                st["idle_asked_ts"] = now
            log.info("forgotten holders: let it sleep, hold released")
            self.bot.edit(message_id, t("idle.slept"))
            # About sleep too: it goes once Windows has had its idle time.
            sleep_warning.said_sleep(self.bot, message_id, now + sleep_warning.IDLE_SLEPT_KEEP)
        elif data_raw in ("chrome_start", "chrome_restart", "chrome_stop"):
            if data_raw == "chrome_stop":
                shell.run("chrome-debug --stop")
            else:
                if data_raw == "chrome_restart":
                    shell.run("chrome-debug --stop")
                # The list of features rather than any one of them: which one
                # is wanted is the next button's question, and the list is
                # where each of them is a click away.
                shell.run("chrome-debug http://localhost:%d/" % services.DEV_PORT, timeout=60)
            # We show the state rather than the command's output:
            # chrome-debug's output is written for a terminal and reads badly in
            # a messenger, while the person has one question — did it start and
            # where to look.
            self.result(message_id, services.chrome_text())
        elif data_raw == "phone_toggle":
            if phone_access.gate_origin(None, False):
                shell.run(phone_access.FUNNEL_OFF, timeout=30)
                log.info("phone access turned off")
                sleep_warning.phone_changed(self.bot, False)
                self.result(message_id, t("chrome.gatedown"))
                return
            on, out = phone_access.phone_on()
            if not on:
                # Most often: funnel not allowed for this node in the tailnet
                # policy, or this user is not Tailscale's operator.
                self.bot.edit(message_id, t("chrome.gatefail", log=status_report.escape(out[-1500:])),
                              menus.services_keyboard())
                return
            log.info("phone access turned on")
            self.result(message_id, t("svc.phonewait"))
            sleep_warning.wait_for_phone(message_id)
        elif data_raw.startswith("devphone:") or data_raw == "gate_stop":
            # Buttons of a card drawn before phone access moved to Settings.
            self.bot.edit(message_id, *services.chrome_screen())
        elif data_raw.startswith(("devopen:", "devstop:", "devstart:")):
            action, _, label = data_raw.partition(":")
            found = [f for f in services.dev_features() if f[0] == label]
            if not found:
                # Merged or abandoned since the card was drawn.
                self.bot.edit(message_id, *services.chrome_screen())
                return
            _label, wt, _port, _running = found[0]
            card_view.dev_act(action[3:], label, wt)
            self.result(message_id, services.chrome_text())
        elif data_raw == "svc_sclaude":
            # We open straight on the remembered repository: most often a
            # person comes back to the same project, and a needless choice is no
            # use to them.
            chosen = repos.repo_choice()
            if chosen:
                name = os.path.basename(chosen)
                self.bot.edit(message_id, repos.repo_text(name), sessions.features_keyboard(name))
            else:
                self.bot.edit(message_id, t("repo.pick"), menus.repos_keyboard())
        elif data_raw == "svc_widgets":
            with locked() as st:
                st["widgets"] = st.get("widgets", True) is False
            log.info("widgets are %s", "on" if widgets.enabled() else "off")
            self.bot.edit(message_id, t("svc.title"), menus.services_keyboard())
        elif data_raw == "svc_lang":
            self.bot.edit(message_id, menus.lang_text(), menus.lang_keyboard())
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
            menus.relabel_anchor(self.bot)
            # And the profile texts and commands, which follow a pinned language.
            self.bot.commands()
            self.bot.describe()
            self.result(message_id, menus.lang_text())
        elif data_raw == "svc_docs":
            self.bot.edit(message_id, t("docs.menu"), menus.docs_keyboard())
        elif data_raw.startswith("doc:"):
            body = docs.section(data_raw.split(":", 1)[1], current())
            if body:
                # A separate message rather than an edit of the current one:
                # the sections are long, and paging through them while losing the
                # previous one is awkward. The menu stays in place so the next
                # section opens with one press.
                self.bot.send(body)
            else:
                self.bot.edit(message_id, t("docs.menu"), menus.docs_keyboard())
        elif data_raw == "svc_repos":
            self.bot.edit(message_id, t("repo.pick"), menus.repos_keyboard())
        elif data_raw.startswith("repo:"):
            name = data_raw.split(":", 1)[1]
            path = repos.repo_path(name)
            if not path:
                # A name not from the list: either the repository is gone or the
                # callback was forged. Both are a reason to show the list
                # again.
                log.warning("unknown repository in the callback: %r", name)
                self.bot.edit(message_id, t("repo.pick"), menus.repos_keyboard())
                return
            was = repos.repo_choice()
            with locked() as st:
                st["sclaude_repo"] = path
            # code-server opens a directory at start-up, so a change of choice
            # reaches it only through a restart. We do that ourselves and only
            # with a live server: nobody asked to bring it up for the sake of a
            # changed choice.
            if was != path and services.code_running():
                shell.run("systemctl --user restart code-server.service")
            self.bot.edit(message_id, repos.repo_text(name), sessions.features_keyboard(name))
        elif data_raw.startswith("cfgset:"):
            # sclaude, and for review gh on every workflow, take seconds: off
            # the loop, so no other press or question waits on them. The
            # screen is redrawn when they are done. One person speaks to the
            # bot, so the language the thread draws in is theirs.
            bot = self.bot
            bot.edit(message_id, t("cfg.setting"))
            threading.Thread(target=lambda: bot.edit(message_id, *project_config.config_press(data_raw)[:2]),
                             daemon=True).start()
        elif data_raw.startswith("cfg:"):
            self.bot.edit(message_id, *project_config.config_press(data_raw)[:2])
        elif data_raw.startswith(("topic:", "feat:")):
            # A feature from the list: its card goes to its topic, made if
            # need be, and the list says where it went. Without Threaded Mode
            # the card takes the list's place, as it did before topics.
            # feat: is the same press from a list drawn before topics.
            _, name, slug = data_raw.split(":", 2)
            # topic::<slug> — the remembered repository, too long for the
            # data (features_keyboard).
            name = name or os.path.basename(repos.repo_choice())
            opened = card_view.open_card(self.bot, name, slug)
            if opened:
                self.result(message_id, t("feat.opened", slug=status_report.escape(slug)))
            elif opened is None:
                # The network's: the list stays, for a press once it is back.
                self.bot.edit(message_id, repos.repo_text(name) + t("feat.topiclater"),
                              sessions.features_keyboard(name))
            else:
                # A card outside a topic: a button whose data could not carry
                # the feature finds it by this message (card_press).
                with locked() as st:
                    cards = st.get("main_cards") or {}
                    cards.pop(str(message_id), None)
                    cards[str(message_id)] = asks.channel_key(name, slug)
                    # The last few: older cards have long scrolled away.
                    st["main_cards"] = dict(list(cards.items())[-topics.MAIN_CARDS:])
                self.bot.edit(message_id, *card_view.card(name, slug, in_topic=False))
        elif data_raw.startswith("fc:"):
            self.card_press(data_raw, message_id)
        elif data_raw.startswith(("go:", "acts:")):
            # A card or list drawn before topics.
            verb, name, slug = data_raw.split(":", 2)
            self.card_press("fc:%s:%s" % (verb, asks.channel_key(name, slug)), message_id)
        elif data_raw.startswith("newfeat:"):
            # A new feature: the conversation goes on through the channel from
            # here — the orchestrator will ask for a name (or offer issues), and
            # the bot will show the question on a turn of the loop.
            name = data_raw.split(":", 1)[1]
            repo = repos.repo_path(name)
            if not repo:
                self.bot.edit(message_id, t("repo.norepos"), menus.repos_keyboard())
                return
            thread = topics.new_feature_topic(self.bot, name)
            sessions.start_sclaude(repo, ["new"])
            self.result(message_id, t("feat.newtopicat" if thread else "feat.newstarted",
                                      repo=status_report.escape(name)))
        elif data_raw == "workshop":
            # sclaude's own workshop: `sclaude workshop` in a tab on the
            # laptop, run from sclaude's checkout, the one this bot is in.
            sessions.start_sclaude(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   ["workshop"])
            self.result(message_id, t("workshop.started"))
        elif data_raw == "svc_restart":
            self.restart(message_id)
        else:
            log.warning("unknown callback: %s", data_raw)

    def card_press(self, data_raw, message_id):
        # A button on a feature's card. The feature is named in the data, or,
        # when its name did not fit, by the topic the card stands in.
        parts = data_raw.split(":", 2)
        action = parts[1]
        key = parts[2] if len(parts) > 2 else topics.topic_channel(self.bot.thread)
        if not key:
            key = (read().get("main_cards") or {}).get(str(message_id), "")
        name, slug = asks.split_key(key)
        repo = repos.repo_path(name) if slug else None
        if not repo or not topics.feature_dir(repo, slug):
            # A widget card has no text to edit: its caption says it, the
            # buttons go.
            gone = t("feat.gone", slug=status_report.escape(slug or "?"))
            if not self.bot.edit(message_id, gone):
                self.bot.caption(message_id, gone)
            return
        note, feats = "", None
        if action in ("go", "acts"):
            # We do not touch a busy feature: a second orchestrator on the same
            # feature is two conversations about one thing. busy belongs here
            # too: the card shows it as running (🟢). So does any state but
            # idle: one Claude Code adds later is not a free feature.
            if sessions.feature_busy(repo, slug):
                note = t("feat.busy")
            elif action == "go":
                # The orchestrator decides what to do itself: `sclaude <feature>`
                # returns to the current step.
                sessions.start_sclaude(repo, [slug])
                # Once, for the note and the card both: it is `sclaude status`.
                feats, _ = repos.features_of_name(name)
                row = next((r for r in feats if r[0] == slug), None)
                note = t("feat.started", step=status_report.escape(row[1] if row else slug))
            else:
                # The list of actions arrives as a question in this topic.
                sessions.start_sclaude(repo, ["actions", slug])
        elif action in ("open", "start", "stop"):
            dev = card_view.feature_dev(repo, slug)
            if dev:
                card_view.dev_act(action, dev[0], topics.feature_wt(repo, slug))
            # The proxy starts the server on its own time: the card redrawn
            # at once would still call it stopped.
            for _ in range(20 if dev and action == "start" else 0):
                if (card_view.feature_dev(repo, slug) or (0, 0, False))[2]:
                    break
                time.sleep(0.5)
        elif action == "map":
            # A feature with no dev server yet has no address for its map:
            # `sclaude dev` gives it one and starts it. Left to run on its
            # own — a first build takes minutes, and this handler answers
            # every other press — while the card waits only for the address,
            # which comes first, and comes back with the map's own button.
            shell.run("cd " + shlex.quote(topics.feature_wt(repo, slug))
                + " && setsid nohup sclaude dev --no-browser >/dev/null 2>&1 &", timeout=10)
            for _ in range(20):
                if card_view.feature_dev(repo, slug):
                    break
                time.sleep(0.5)
            note = t("card.mapready") if card_view.feature_dev(repo, slug) else t("card.mapfailed")
        elif action == "code":
            shell.run("systemctl --user start code-server.service")
            # The card redrawn at once would still call it stopped.
            for _ in range(10):
                if services.code_running():
                    break
                time.sleep(0.5)
        card_view.redraw(self.bot, message_id, name, slug, note, in_topic=bool(self.bot.thread),
                         feats=feats)

    def answer_button(self, cid, data_raw, message_id):
        # An answer to an orchestrator's question. Three fields rather than
        # two: we separate the repository's name from the answer at the first
        # colon from the left — the answer itself may contain anything.
        _, name, reply = data_raw.split(":", 2)
        repo = repos.repo_path(name)
        if not repo:
            self.bot.answer(cid)
            self.bot.edit(message_id, t("repo.norepos"), menus.repos_keyboard())
            return
        # The press carries the repository, not the question or the feature:
        # the message it came from says which. Each open question is shown by
        # one message, and a press on any other is a press on a closed one —
        # without this a button on an old message would answer whatever the
        # repository asks now.
        if topics.press_answered(name, message_id, repo):
            self.bot.answer(cid)
            return
        key = topics.press_channel(name, message_id, repo)
        channel = asks.channel_dir(key) if key else ""
        # We learn what exactly was chosen before sending: afterwards the
        # question is cleared, and there will be nowhere left to read it from.
        question = asks.pending_ask(channel) if channel else None
        chosen = asks.option_label((question or {}).get("options"), reply)
        # The message shows one question; the channel may hold the next one
        # by now — answered at the laptop, "Delete them?" is followed at once
        # by "Force-delete it?", and the bot learns of it only on its turn. A
        # press must not answer a question it was not shown.
        entry = asks.get_shown(key, repo) if key else None
        mark = (question.get("id") or question.get("asked") or 0) if question else None
        if not channel or (entry and not entry.get("legacy") and entry.get("id") != mark) \
                or not asks.answer_ask(channel, reply, (question or {}).get("id")):
            self.bot.answer(cid, t("ask.gone"))
            # A message the loop knows of is settled by it — into the answer
            # given at the laptop. Only one it has no record of goes now.
            if not key:
                menus.retire(self.bot, message_id)
            return
        self.bot.answer(cid)
        asks.forget_ask(key, message_id, repo)
        # "1" is honest but useless where the answer was an exit. The person
        # pressed "back" and has a right to see what they were leaving: the
        # repository's feature list. The other answers replace the question
        # — work follows them, and its output will come in due course.
        if asks.is_back_option(chosen) and not self.bot.thread:
            self.bot.edit(message_id, repos.repo_text(name), sessions.features_keyboard(name))
            # A menu now, and the main chat keeps one.
            self.adopt(message_id)
        else:
            self.bot.edit(message_id, asks.answered_text(name, question, reply))

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
             "sleep 2; systemctl --user restart " + state.BOT_UNIT],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def decision(self, raw, message_id, cid, now):
        action, _, ts = raw.partition(":")
        try:
            stamp = int(ts)
        except ValueError:
            stamp = None
        kind, until, until_ts = holding.decide(action, stamp, now)
        if kind == "stale":
            # The alert says why; the message goes at once, being about a
            # window that is over.
            self.bot.answer(cid, t("sleep.stale"), alert=True)
            if not menus.retire(self.bot, message_id):
                sleep_warning.trail(message_id, now)
            return
        self.bot.answer(cid)
        if kind == "extend":
            text = t("sleep.extended", at=status_report.local_for_lang(until))
            expires = until_ts
        else:
            text = t("sleep.accepted")
            expires = now + sleep_warning.IDLE_SLEPT_KEEP
        # We remove the keyboard: there will be nothing left to press a second
        # time. The answer stays while true: until the new deadline, or, let
        # go, while Windows counts its idle time.
        self.bot.edit(message_id, text)
        sleep_warning.said_sleep(self.bot, message_id, expires)

    def widget_query(self, wq):
        # A tap in one of the bot's widgets (widgets.py). Every query is
        # answered, a failed one too, or the widget waits fifteen seconds for
        # a timeout; the answer goes first, the slower follow-up (edits,
        # deletes) after it.
        data_raw = wq.get("data") or ""
        message_id = wq.get("message_id") or 0
        now = int(time.time())
        answer, after = None, None
        try:
            if data_raw.startswith("hold:"):
                answer, after = sleep_warning.hold_press(self.bot, data_raw, message_id, now)
            elif data_raw.startswith("m:"):
                answer, after = menu_widget.press(self.bot, wq, now)
            elif data_raw.startswith("ask:"):
                answer, after = asks.widget_press(
                    self.bot, data_raw, message_id,
                    back=lambda name: self.screen(repos.repo_text(name), sessions.features_keyboard(name)))
            else:
                answer = widgets.state(widgets.STALE)
        finally:
            self.bot.answer_widget(wq.get("id"), answer)
        if after:
            after()
