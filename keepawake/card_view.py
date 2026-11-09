# keepawake's Telegram bot — the feature's card in its topic: what it shows,
# posting and redrawing it when the feature's state changes.
#
# Part of the bot that keepawake/telegramd.py runs.

import logging
import os
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request

from keepawake.i18n import t
from keepawake.state import read
from keepawake import asks, menus, phone_access, repos, services, sessions, shell, topics


log = logging.getLogger("keepawake")


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
        shell.run("chrome-debug " + shlex.quote("http://%s.localhost:%d/" % (label, services.DEV_PORT)),
            timeout=60)
    elif action == "start":
        phone_access.proxy_start(label)
    elif action == "stop":
        shell.run("cd " + shlex.quote(wt) + " && sclaude dev --stop", timeout=90)


def feature_dev(repo, slug):
    """(label, port, running) of the feature's dev server, or None."""
    real = os.path.realpath(topics.feature_wt(repo, slug))
    for label, wt, port, running in services.dev_features():
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
    if menus.ON_PAGE and feats is None:
        # Read once: the page's Continue is named by the step.
        feats, _ = repos.features_of_name(name)
    text = sessions.feature_card(name, slug, feats)
    if in_topic and not menus.ON_PAGE:
        # Whatever draws the topic's card — the loop, /menu, a press — says
        # which session state it shows, for check_card_states to compare.
        shown_state(name, slug)
    key = asks.channel_key(name, slug)
    serve = phone_access.serve_config() if config is None else config
    origin = phone_access.gate_origin(serve)
    # On the page the buttons stand alone, and say what they act on: one to
    # a row, Continue first and named by where the feature is.
    named = (lambda chat, page: t(page) if menus.ON_PAGE else t(chat))
    if menus.ON_PAGE:
        step = next((r[1] for r in feats or [] if r[0] == slug), "")
        go = (t("page.finish") if " done" in step or step.startswith("all done")
              else t("page.continuestep", step=step) if step else t("page.continue"))
        rows = [[{"text": go, "callback_data": card_data("go", key)}],
                [{"text": t("page.actions"), "callback_data": card_data("acts", key)}]]
    else:
        rows = [[{"text": t("feat.continue"), "callback_data": card_data("go", key)},
                 {"text": t("feat.actions"), "callback_data": card_data("acts", key)}]]
    repo = repos.repo_path(name)
    if repo and topics.feature_dir(repo, slug):
        dev = feature_dev(repo, slug)
        if dev:
            label, _port, running = dev
            text += t("card.devpage", state=t("chrome.running") if running
                      else t("chrome.stopped")) if menus.ON_PAGE else t("card.dev",
                      state=t("chrome.running") if running else t("chrome.stopped"),
                      link='<a href="%s/__sclaude/select?f=%s">%s</a>' % (
                          phone_access.phone_origin(serve), label, t("card.phonelink")),
                      local="http://%s.localhost:%d" % (label, services.DEV_PORT))
            row = [{"text": named("chrome.open", "page.onlaptop"),
                    "callback_data": card_data("open", key)}]
            here = phone_access.phone_button(origin, label)
            if menus.ON_PAGE:
                for b in here:
                    b["text"] = t("page.onphone")
            row += here
            switch = ({"text": named("chrome.featstop", "page.devstop"),
                       "callback_data": card_data("stop", key)} if running else
                      {"text": named("chrome.start", "page.devstart"),
                       "callback_data": card_data("start", key)})
            if menus.ON_PAGE:
                # A row each: where to open it, and starting or stopping it.
                rows += [[b] for b in row] + [[switch]]
                rows += [phone_access.map_button(origin, key, dev)] if origin else []
            else:
                rows.append(row + [switch])
        else:
            text += t("card.nodev")
            if menus.ON_PAGE and origin:
                rows.append(phone_access.map_button(origin, key, None))
        # code-server opens the worktree itself with ?folder=, whichever
        # project it was started on.
        folder = "/?folder=" + urllib.parse.quote(topics.feature_wt(repo, slug))
        last = []
        if menus.ON_PAGE:
            # The page has code-server's own screen, on this feature's
            # worktree: nothing of it on the card.
            pass
        elif services.code_running():
            text += t("card.code", url=services.code_url() + folder, local="http://127.0.0.1:8080" + folder)
            last += services.code_app_button(origin, topics.feature_wt(repo, slug))
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
    repo = repos.repo_path(name)
    if not repo:
        return 0
    record = topics.load_record(repo, slug)
    thread = record.get("thread") or 0
    if not thread:
        return 0
    text, keyboard = card(name, slug)
    msg = bot.send(text, keyboard, quiet=True, thread=thread)
    if not msg:
        return 0
    menus.retire(bot, record.get("card") or 0)
    # Read again: card() has just written the state it shows.
    record = topics.load_record(repo, slug)
    record["card"] = msg
    topics.save_record(repo, slug, record)
    return msg


def open_card(bot, name, slug):
    # The feature's card in its topic, the topic made if need be. Returns
    # whether it is there — False without Threaded Mode or a worktree.
    # A topic made just now already opens with its card.
    # None when the topic is to be had but the network failed: the card is
    # not drawn outside the topic for that.
    repo = repos.repo_path(name)
    had = bool(repo and topics.load_record(repo, slug).get("thread"))

    key = asks.channel_key(name, slug)

    def missed():
        return None if topics.topic_pending(repo, slug, topics.CARD_TRIED, key) else False

    if not topics.feature_topic(bot, name, slug):
        return missed()
    topics.CARD_TRIED.pop(key, None)
    # A new topic opens with its card — unless that send failed.
    if not had and topics.load_record(repo, slug).get("card"):
        return True
    if post_card(bot, name, slug):
        return True
    if not topics.topic_lost(bot):
        return None
    # The topic was deleted by hand: a new one, which opens with its card.
    if not topics.feature_topic(bot, name, slug, renew=True):
        return missed()
    return True if topics.load_record(repo, slug).get("card") else None


def note_topic(bot, name, slug):
    """Where a feature's notes go: its topic; the main chat (0) only when
    no topic is to be had for it — the chat has no topics, or Telegram's
    refusal holds the chat or this feature (topics.held); None while
    neither — a topic not made yet, the network, a feature whose worktree
    has gone."""
    repo = repos.repo_path(name)
    if not repo or not topics.feature_dir(repo, slug):
        return None
    thread = topics.feature_topic(bot, name, slug)
    if thread:
        return thread
    return 0 if topics.held(name, slug) else None


def redraw_cards(bot):
    # Every card in a feature's topic, drawn again: what it offers depends on
    # phone access (one button to the app, or the actions themselves), and a
    # card left as it was offers what does not work.
    serve = phone_access.serve_config()
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        feats = None
        for slug in topics.feature_records(repo):
            msg = topics.load_record(repo, slug).get("card") or 0
            if not msg or not topics.feature_dir(repo, slug):
                continue
            if feats is None:
                feats, _ = repos.features_of_name(name)
            bot.edit(msg, *card(name, slug, feats=feats, config=serve))


def shown_state(name, slug, state=None):
    """Record the session state a chat card of the feature now shows."""
    repo = repos.repo_path(name)
    if not repo or not topics.feature_dir(repo, slug):
        return
    if state is None:
        state = sessions.session_state(sessions.feature_session(repo, slug)[0])
    record = topics.load_record(repo, slug)
    if (record.get("card_state") or "") != state:
        record["card_state"] = state
        topics.save_record(repo, slug, record)


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
    sessions.agents()
    if not sessions._AGENTS["ok"]:
        return
    # The one answer serves the whole pass: a later call past AGENTS_FRESH,
    # mid-way, could fail and read every session as none.
    sessions._AGENTS["at"] = float("inf")
    try:
        redraw_changed_cards(bot)
    finally:
        sessions._AGENTS["at"] = time.time()


def redraw_changed_cards(bot):
    serve = None              # tailscale's, read once, and only if a card is drawn
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        feats = None
        for slug in topics.feature_records(repo):
            if not topics.feature_dir(repo, slug):
                continue
            record = topics.load_record(repo, slug)
            msg = record.get("card") or 0
            if not msg:
                continue
            session, _step = sessions.feature_session(repo, slug)
            state = sessions.session_state(session)
            if state == (record.get("card_state") or ""):
                continue
            if feats is None:
                feats, _ = repos.features_of_name(name)
            if serve is None:
                serve = phone_access.serve_config()
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
            bot.edit(msg, *menus.chat_menu(int(place)))
