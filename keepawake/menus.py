# keepawake's Telegram bot — the bot's menu in the chat: its keyboards, the
# anchor message, the language and the lists of repositories and docs.
#
# Part of the bot that keepawake/telegramd.py runs.

import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from keepawake.i18n import STRINGS, current, t
from keepawake.state import locked, read
from keepawake import handling, phone_access, repos, status_report, topics


log = logging.getLogger("keepawake")


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
        [{"text": t("menu.workshop"), "callback_data": "workshop"},
         {"text": t("menu.settings"), "callback_data": "menu_services"}],
    ]


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
    return t("menu.title", host=status_report.escape(host_name()))


def chat_menu(thread=0):
    """(text, keyboard) of the menu in the chat. The menu itself is the Mini
    App (webmenu.py); the chat offers the way there. While phone access is
    off the app cannot open, so the chat keeps what must work without it:
    the hold, and turning phone access on. In a feature's topic the app
    opens on that feature."""
    origin = phone_access.gate_origin()
    if not origin:
        return t("menu.offline", host=status_report.escape(host_name())), [
            [{"text": t("menu.extend"), "callback_data": "menu_extend"}],
            [{"text": t("svc.phoneoff"), "callback_data": "phone_toggle"}]]
    key = topics.topic_channel(thread)
    url = origin + "/__sclaude/menu" + (
        "?f=" + urllib.parse.quote(key, safe="") if key else "")
    return t("menu.inapp", host=status_report.escape(host_name())), [
        [{"text": t("menu.open"), "web_app": {"url": url}}]]


def services_keyboard():
    return [
        [{"text": t("svc.lang"), "callback_data": "svc_lang"},
         {"text": t("svc.docs"), "callback_data": "svc_docs"}],
        [{"text": t("svc.restart"), "callback_data": "svc_restart"}],
        # On and off in one button, its caption the current state.
        [{"text": t("svc.phoneon") if phone_access.gate_origin(None, False) else t("svc.phoneoff"),
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


# True while a screen is drawn for the Mini App (webmenu.py). There the
# tailnet's addresses lead nowhere — the phone has no Tailscale — and the
# gate's buttons on the same screen stand in for them.
ON_PAGE = False


def report_restart(bot):
    # After a restart, report into the same message that the daemon is alive
    # again. It is a new process that does this, so it reads the errand from the
    # state. Returns True if the report happened: the caller judges by that
    # whether to write to the chat for the keyboard's sake as well.
    data = read()
    mid = data.get("restart_notify") or 0
    old = data.get("restart_from_pid") or 0
    if old == os.getpid():
        return False    # the same process: the restart has not happened yet
    if data.get("restart_page"):
        # Asked for from the menu page, which waits for this mark to go
        # (restart_wait in webmenu.py) — whether or not its line in the chat
        # was sent.
        with locked() as st:
            st["restart_page"] = False
    if not mid:
        return False
    with locked() as st:
        st["restart_notify"] = 0
        st["restart_from_pid"] = 0
    if data.get("restart_page"):
        # The line in the chat is the page's trace, and a Settings menu under
        # it would be a second menu to keep true.
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
        handling.Handler(bot).adopt(msg)
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
    chosen = repos.repo_choice()
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        mark = "● " if chosen == repo else ""
        rows.append([{"text": mark + name, "callback_data": "repo:" + name}])
    # To the main menu rather than to Settings: people arrive here both by the
    # Sclaude button in the main menu and from Settings, and a "back" into a
    # branch the person never opened is the worse of the two options.
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows
