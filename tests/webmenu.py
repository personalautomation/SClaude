#!/usr/bin/env python3
#
# keepawake/webmenu.py: the bot's menu as a Mini App. The page runs the chat's
# own handler; what is checked here is the seam — what the handler would have
# done to the menu message becomes the page's screen, what the person started
# leaves one line in the chat, and nothing that only showed something does.
#
# Telegram is never called: Bot.call records instead. keepawake's state is a
# file of the test's own.
#
# Run it with: python3 tests/webmenu.py
import json
import os
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

box = tempfile.mkdtemp(prefix="webmenu-test-")
os.environ["KEEPAWAKE_STATE"] = os.path.join(box, "state.json")
os.environ["KEEPAWAKE_LOCK"] = os.path.join(box, ".lock")

from keepawake import telegramd, webmenu  # noqa: E402
from keepawake.i18n import t  # noqa: E402
from keepawake.state import read  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


CALLS = []
MESSAGE = [500]


def fake_call(self, method, http_timeout=15, **params):
    CALLS.append((method, params))
    MESSAGE[0] += 1
    return {"result": {"message_id": MESSAGE[0]}}


telegramd.Bot.call = fake_call
# Nothing on this machine is looked at: no tailscale, no processes.
telegramd.run = lambda cmd, timeout=25: ""
telegramd.status_text = lambda: "<b>status</b>"
telegramd.gate_origin = lambda *a: ""
SPAWNED = []
webmenu.subprocess.Popen = lambda args, **kw: SPAWNED.append(args)
USER = {"id": 1, "language_code": "en"}


def press(action, context="", label=""):
    del CALLS[:]
    return webmenu.answer("t:k", 12345, USER, action, context, int(time.time()), label)


def sent():
    return [(p.get("text"), p.get("message_thread_id")) for m, p in CALLS if m == "sendMessage"]


# --- PageBot: the menu message is the page ------------------------------------
bot = webmenu.PageBot("t:k", 12345)
del CALLS[:]
bot.edit(webmenu.PAGE, "screen", [[{"text": "x", "callback_data": "y"}]])
check("an edit of the page's message is its screen", bot.screen[0], "screen")
check("and reaches no chat", CALLS, [])
bot.edit(42, "elsewhere")
check("an edit of a chat message goes to the chat", CALLS[-1][0], "editMessageText")
bot.send("reply")
check("a reply to the press is the page's", bot.notes, ["reply"])
bot.send("to a topic", thread=7)
check("a message to a topic is the chat's", CALLS[-1][1].get("message_thread_id"), 7)

# --- the menu and the way back -------------------------------------------------
view = press("")
check("no press is the whole menu", view["rows"], telegramd.menu_keyboard())
check("the menu is the main screen", view["main"], True)
check("the menu explains itself", view["help"], t("help.menu"))
check("showing leaves nothing in the chat", sent(), [])
check("the back press is the whole menu too", press("menu_back")["rows"],
      telegramd.menu_keyboard())

rows = webmenu.rows_for_page([[{"text": "a", "callback_data": "b"}]], False)
check("a screen without a way back gets one", rows[-1][0]["callback_data"], "menu_back")
rows = webmenu.rows_for_page([[{"text": t("menu.back"), "callback_data": "svc_docs"}]], False)
check("a screen with its own Back gets no second", len(rows), 1)
check("the menu gets none", webmenu.rows_for_page(telegramd.menu_keyboard(), True),
      telegramd.menu_keyboard())

# --- the hold -------------------------------------------------------------------
view = press("menu_extend")
datas = [b.get("callback_data") for row in view["rows"] for b in row]
check_true("the Keepawake screen offers the extensions", "awake:3600" in datas)
check("and explains them", view["help"], t("help.keepawake"))
check("showing it leaves nothing in the chat", sent(), [])

view = press("awake_until")
check("until a time asks with the page's own field", view["time"], True)
check("in words of the page's own", view["text"], t("awake.askpage"))
check("and the chat waits for nothing", read().get("awaiting") or "", "")
check("a time the page cannot read says so", press("until:99:99")["text"],
      t("awake.badtimepage"))

before = read().get("until_ts") or 0
view = press("awake:3600", label="☕ One hour")
check_true("an extension moves the deadline", (read().get("until_ts") or 0) > before)
check("its result is the screen", view["text"],
      t("extended.plain", at=telegramd.local_for_lang(read().get("until_local"))))
check("and it leaves one line in the main chat",
      [(text.startswith("📱 "), thread) for text, thread in sent()], [(True, None)])
check("a result needs no note", view["help"], "")

# --- a feature's card -------------------------------------------------------------
telegramd.card = lambda name, slug, note="", in_topic=True, feats=None: (
    "card %s/%s" % (name, slug), [[{"text": "▶️", "callback_data": "fc:go"}]])
view = press("topic:shop:alpha")
check("a feature opens its card on the page", view["text"], "card shop/alpha")
check("which the page remembers for its buttons", view["context"], "shop/alpha")
check("opening a card leaves nothing in the chat", sent(), [])

pressed = []
saved_card_press = telegramd.Handler.card_press
telegramd.Handler.card_press = lambda self, data, mid: pressed.append(data)
telegramd.repo_path = lambda name: "/nowhere/" + name
telegramd.load_record = lambda repo, slug: {"thread": 31}
try:
    press("fc:go", context="shop/alpha", label="▶️ Continue")
    check("a card button without the feature gets it from the page", pressed[-1],
          "fc:go:shop/alpha")
    check("a card's action leaves its line in the feature's topic",
          sent(), [("📱 ▶️ Continue", 31)])
    press("fc:refresh", context="shop/alpha", label="🔄")
    check("redrawing a card leaves nothing", sent(), [])
finally:
    telegramd.Handler.card_press = saved_card_press

# --- settings ---------------------------------------------------------------------
telegramd.gate_origin = lambda *a: "https://box.tail1.ts.net:8443"
view = press("phone_toggle")
check("turning phone access off asks first",
      [b["callback_data"] for row in view["rows"] for b in row], ["phone_off", "menu_services"])
check("asking changes nothing", SPAWNED, [])
view = press("phone_off")
check("the page closes after it", view["close"], True)
check_true("the funnel goes after the answer, not under it",
           SPAWNED and "sleep" in SPAWNED[-1][-1] and telegramd.FUNNEL_OFF in SPAWNED[-1][-1])
check_true("the Menu button is plain again",
           ("setChatMenuButton", {"menu_button": {"type": "commands"}, "chat_id": 12345}) in CALLS)

view = press("svc_restart")
check_true("the restart restarts the bot's unit", webmenu.BOT_UNIT in SPAWNED[-1][-1])
check("its line in the chat is reported on by the new process",
      read().get("restart_notify"), MESSAGE[0])
check("as a line, with no Settings menu under it", read().get("restart_page"), True)

press("lang:ru", label="🇷🇺 Русский")
check("a language chosen leaves the choice in the chat, not its screen",
      [text for text, _ in sent() if text.startswith("📱")], ["📱 🇷🇺 Русский"])
press("lang:en", label="🇬🇧 English")

view = press("doc:why")
check("a docs section is a screen", view["rows"][-1][-1]["callback_data"], "svc_docs")
check("not a note", view["notes"], [])

check("the screens are drawn for the page only while it asks", telegramd.ON_PAGE, False)

if failures:
    print("webmenu: FAILED: %d" % len(failures))
    for name, want, got in failures:
        print("  %s\n    expected: %r\n    got:      %r" % (name, want, got))
    sys.exit(1)
print("webmenu: all checks passed")
