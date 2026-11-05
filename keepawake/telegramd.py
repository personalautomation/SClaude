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

import logging
import os
import signal
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keepawake import notices, review_keys
from keepawake.i18n import current, set_lang
from keepawake.state import read

from keepawake import asks, botapi, card_view, handling, holding, menus, phone_access, repos, sleep_warning, topics


log = logging.getLogger("keepawake")


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
    bot = botapi.Bot(token, chat)
    handler = handling.Handler(bot)

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
        sleep_warning.phone_off_after_boot()
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
    sleep_warning.PHONE_SEEN[0] = bool(phone_access.gate_origin())

    # If we were restarted by a button, report it into that same message. That
    # same message carries the reply keyboard: setting it with a separate "I have
    # started" means writing to the chat on every restart of the daemon, and it
    # restarts both by a button in the menu and after a reboot. Telegram has no
    # silent way of setting a keyboard — it only arrives with a message.
    try:
        if not menus.report_restart(bot):
            menus.ensure_anchor(bot)
    except Exception as exc:
        log.warning("the restart report: %s", exc)

    backoff = 1

    while not bot.stopped:
        try:
            out = bot.call("getUpdates", http_timeout=botapi.POLL_TIMEOUT + 10,
                           offset=bot.offset, timeout=botapi.POLL_TIMEOUT)
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
            backoff = min(backoff * 2, botapi.BACKOFF_MAX)
            continue
        except Exception as exc:
            log.warning("network: %s, pausing %d s", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, botapi.BACKOFF_MAX)
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
                    handling.remember_lang(msg.get("from"))
                    bot.thread = topics.message_thread(msg)
                    topics.remember_in_topic(bot.thread, msg.get("message_id"))
                    handler.message(msg)
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
                    if chat_id != bot.chat_id:
                        log.warning("a foreign chat in the callback: %s", chat_id)
                        continue
                    handling.remember_lang(cq.get("from"))
                    bot.thread = topics.message_thread(cq.get("message") or {})
                    handler.callback(cq)
            except Exception as exc:
                log.exception("handling the update: %s", exc)
            finally:
                bot.thread = 0

        try:
            sleep_warning.check_warning(bot)
        except Exception as exc:
            log.exception("checking the warning: %s", exc)

        try:
            sleep_warning.check_idle_hold(bot)
        except Exception as exc:
            log.exception("checking forgotten holders: %s", exc)

        # An orchestrator's question waits for the person, not the other way
        # round: the later it reaches the chat, the longer the step stands. A
        # turn here is the same 25 seconds of long-polling as everything else,
        # and that is an order of magnitude faster than walking to the laptop.
        try:
            asks.check_asks(bot)
        except Exception as exc:
            log.exception("checking sclaude's questions: %s", exc)

        # Where a feature's review stands, after each round: to its topic.
        try:
            notices.check(bot, [(os.path.basename(repo), slug, channel)
                                for repo in repos.known_repos()
                                for slug, channel in asks.ask_channels(repo) if slug],
                          lambda name, slug: card_view.note_topic(bot, name, slug), log,
                          at_terminal=lambda pid: asks.at_terminal({"pid": pid}),
                          shown=asks.channel_context,
                          lost=lambda name, slug: topics.topic_lost(bot)
                          and topics.feature_topic(bot, name, slug, renew=True),
                          keys=review_keys)
        except Exception as exc:
            log.exception("sending sclaude's notes: %s", exc)

        try:
            holding.check_awaiting(bot)
        except Exception as exc:
            log.exception("sweeping the time question: %s", exc)

        try:
            sleep_warning.check_phone(bot)
        except Exception as exc:
            log.exception("checking phone access: %s", exc)

        try:
            topics.check_topics(bot)
            topics.check_new_topics(bot)
        except Exception as exc:
            log.exception("checking the feature topics: %s", exc)

        try:
            card_view.check_card_states(bot)
        except Exception as exc:
            log.exception("checking the cards' sessions: %s", exc)

    log.info("the daemon has stopped")


if __name__ == "__main__":
    main()
