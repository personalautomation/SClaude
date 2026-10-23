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

REAL_CARD = telegramd.card
from keepawake.i18n import STRINGS, t  # noqa: E402
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


def press(action, context="", label="", home=""):
    del CALLS[:]
    return webmenu.answer("t:k", 12345, USER, action, context, int(time.time()), label, home)


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
# The machine's own features are never looked at here.
webmenu.features = lambda: []
view = press("")
check("no press is the whole menu, and a way to stand on a feature", view["rows"],
      telegramd.menu_keyboard() + [[{"text": t("menu.choosehome"), "callback_data": "home_pick"}]])
check("the menu is the main screen", view["main"], True)
check("the menu explains itself", view["help"], t("help.menu"))
check("showing leaves nothing in the chat", sent(), [])
check("the back press is the whole menu too", press("menu_back")["rows"][:-1],
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

# The label as the button carries it, from i18n: the Russian half stays there.
RU_LABEL = STRINGS["lang.ru"][0]
press("lang:ru", label=RU_LABEL)
check("a language chosen leaves the choice in the chat, not its screen",
      [text for text, _ in sent() if text.startswith("📱")], ["📱 " + RU_LABEL])
press("lang:en", label="🇬🇧 English")

view = press("doc:why")
check("a docs section is a screen", view["rows"][-1][-1]["callback_data"], "svc_docs")
check("not a note", view["notes"], [])

# --- opened from a feature's topic: the page stands on that feature ------------------
telegramd.feature_dir = lambda repo, slug: slug == "alpha"
telegramd.feature_dev = lambda repo, slug: ("alpha", 3123, True)
telegramd.feature_wt = lambda repo, slug: "/nowhere/shop-" + slug
telegramd.port_open = lambda port: False
view = press("", home="shop/alpha")
check_true("the menu says which feature it stands on", "📍 alpha" in view["text"])
view = press("svc_sclaude", home="shop/alpha")
check("Sclaude is that feature's card, not every repository", view["text"], "card shop/alpha")
view = press("menu_chrome", home="shop/alpha")
datas = [b.get("callback_data") or b.get("web_app", {}).get("url") for row in view["rows"] for b in row]
check_true("Chrome opens that feature on the laptop", "fc:open:shop/alpha" in datas)
check_true("and here", "https://box.tail1.ts.net:8443/__sclaude/tg?f=alpha" in datas)
telegramd.port_open = lambda port: True
view = press("menu_chrome", home="shop/alpha")
check("Chrome: the laptop, closing it, then here, a row each; the dev server is the card's",
      [[b.get("callback_data") or "web_app" for b in row] for row in view["rows"]],
      [["fc:open:shop/alpha"], ["chrome_stop"], ["web_app"], ["menu_back"]])
telegramd.port_open = lambda port: False
check("a feature that is not there leaves the menu as it is",
      webmenu.home_feature("shop/gone"), None)
# Opened by the Menu button, which knows no topic: the feature sclaude
# worked on last, and a way to another.
webmenu.features = lambda: [("shop/alpha", "shop", "alpha", 2), ("shop/beta", "shop", "beta", 1)]
view = press("")
check("the Menu button's page stands on the latest feature", view["home"], "shop/alpha")
check("and says so", "📍 alpha" in view["text"], True)
view = press("home_pick")
check("another feature is one press away",
      [b["callback_data"] for row in view["rows"] for b in row][:3],
      ["home:shop/alpha", "home:shop/beta", "home:"])
view = press("home:", home="shop/alpha")
check("or the whole machine", (view["home"], "📍" in view["text"]), ("", False))
check("the menu after a choice is the menu, with no way back from it",
      any(b.get("callback_data") == "menu_back" for row in view["rows"] for b in row), False)

saved_card = telegramd.card
telegramd.card = lambda name, slug, note="", in_topic=True, feats=None, config=None: (
    "card", [[{"text": "▶️", "callback_data": "fc:go"}],
             [{"text": "‹ Repositories", "callback_data": "repo:" + name}]])
try:
    datas = [b["callback_data"] for row in press("topic:shop:alpha", home="shop/alpha")["rows"]
             for b in row]
    check("on the page's own feature there is no list to go back to",
          any(d.startswith("repo:") for d in datas), False)
    datas = [b["callback_data"] for row in press("topic:shop:beta", home="shop/alpha")["rows"]
             for b in row]
    check("browsing another one keeps it", "repo:shop" in datas, True)
    # Redrawn by its own Refresh, through the chat's handler, it stays so.
    saved_press = telegramd.Handler.card_press
    telegramd.Handler.card_press = lambda self, data, mid: self.bot.edit(mid, *telegramd.card("shop", "alpha"))
    try:
        datas = [b["callback_data"] for row in press("fc:refresh:shop/alpha", context="shop/alpha",
                                                     home="shop/alpha")["rows"] for b in row]
        check("a refreshed card of the page's feature has no way to the repositories",
              any(d.startswith("repo:") for d in datas), False)
    finally:
        telegramd.Handler.card_press = saved_press
finally:
    telegramd.card = saved_card

# Actions are a question of sclaude's: the page shows it and answers it.
started, answered = [], []
saved_start, saved_pending, saved_answer = (telegramd.start_sclaude, telegramd.pending_ask,
                                            telegramd.answer_ask)
QUESTION = {"id": "q1", "prompt": "What now?", "form": "pick:2", "options": ["Merge", "Drop"]}
telegramd.start_sclaude = lambda repo, args: started.append(args)
telegramd.answer_ask = lambda channel, reply, want=None: answered.append(reply) or True
webmenu.wait_question = lambda channel, after, seconds=6: None
try:
    telegramd.pending_ask = lambda channel: QUESTION
    view = press("fc:acts:shop/alpha")
    check("a question already waiting is shown, not asked again", started, [])
    check("and showing it leaves no line in the chat", sent(), [])
    check("with its own buttons, answering from the page",
          [b["callback_data"] for row in view["rows"] for b in row][:2], ["pa:q1:1", "pa:q1:2"])
    check("the page stays open", view["close"], False)
    view = press("pa:q1:2", context="shop/alpha")
    check("a press answers it", answered, ["2"])
    check("and says what was answered", view["text"], t("page.answered", reply="Drop"))
    view = press("pa:old:1", context="shop/alpha")
    check("an answer to a question already closed is not given", (answered, view["text"][:20]),
          (["2"], t("page.gone")[:20]))
    # The list of actions: grouped by where each leads, the current step marked.
    ACTIONS = {"id": "q2", "prompt": "Which one? [1-5] ", "form": "pick:5",
               "options": ["Finish up", "Return to development (return)", "Sync with main (sync)",
                           "Drop the feature (drop)", "Go back"],
               "context": "  1)   Finish up                        4/6 done — preview\n"
                          "  2)   Return to development (return)   back to step 2, with notes\n"
                          "  3)   Sync with main (sync)            up to date\n"
                          "  4)   Drop the feature (drop)          clear its traces\n  5)   Go back"}
    saved_feats = telegramd.features_of_name
    telegramd.features_of_name = lambda name: ([("alpha", "4/6 done, waiting for merge", "")], "")
    try:
        telegramd.pending_ask = lambda channel: ACTIONS
        view = press("fc:acts:shop/alpha")
        check("the actions are not a numbered question on the page", "[1-5]" in view["text"], False)
        check("the current step is marked", "📍<b>review</b>" in view["text"], True)
        flat = [(b.get("style") == "caption" and "§" + b["text"]) or b["callback_data"]
                for row in view["rows"] for b in row]
        check("grouped by where they lead: back, staying, forward, the end",
              flat, ["§" + t("act.back", n="2 · code"), "pa:q2:2", "§" + t("act.stay"), "pa:q2:3",
                     "§" + t("act.forward"), "pa:q2:1", "§" + t("act.end"), "pa:q2:4",
                     "pa:q2:5", "topic:shop:alpha"])
        check("each says what it does",
              [b.get("hint") for row in view["rows"] for b in row if b.get("callback_data") == "pa:q2:2"],
              ["back to step 2, with notes"])
    finally:
        telegramd.features_of_name = saved_feats
    telegramd.pending_ask = lambda channel: None
    saved_busy = telegramd.feature_busy
    telegramd.feature_busy = lambda repo, slug: True
    try:
        view = press("fc:acts:shop/alpha")
        check("a step at work gets no second sclaude from the page", started, [])
    finally:
        telegramd.feature_busy = saved_busy
    telegramd.feature_busy = lambda repo, slug: False
    try:
        view = press("fc:acts:shop/alpha")
    finally:
        telegramd.feature_busy = saved_busy
    check("no question yet: sclaude is started for the actions", started, [["actions", "alpha"]])
finally:
    telegramd.answer_ask = saved_answer
    telegramd.start_sclaude, telegramd.pending_ask = saved_start, saved_pending
telegramd.code_password = lambda: "pw<1>"
telegramd.code_running = lambda: True
view = press("menu_code", home="shop/alpha")
check_true("the page shows code-server's password", "pw&lt;1&gt;" in view["text"])
check_true("and opens it on the feature's worktree",
           any("folder%3D%2Fnowhere%2Fshop-alpha" in (b.get("web_app") or {}).get("url", "")
               for row in view["rows"] for b in row))
check_true("the chat's own screen never shows it",
           "pw&lt;1&gt;" not in telegramd.code_text() and "pw<1>" not in telegramd.code_text())

# A feature's card on the page: a button to a row, Continue named by the step.
saved_feats = telegramd.features_of_name
try:
    telegramd.ON_PAGE = True
    for step, first in (("2/6 coding", t("page.continuestep", step="2/6 coding")),
                        ("4/6 done, waiting for merge", t("page.finish"))):
        telegramd.features_of_name = lambda name, step=step: ([("alpha", step, "")], "")
        _text, rows = REAL_CARD("shop", "alpha", in_topic=False)
        check("Continue says what it does: %s" % step, rows[0][0]["text"], first)
    check("then the other actions, the places to open it, and its server apart",
          [[b.get("callback_data") or "web_app" for b in r] for r in rows][:5],
          [["fc:go:shop/alpha"], ["fc:acts:shop/alpha"], ["fc:open:shop/alpha"], ["web_app"],
           ["fc:stop:shop/alpha"]])
finally:
    telegramd.ON_PAGE = False
    telegramd.features_of_name = saved_feats

# A session past the four steps — the retrospective — is not under steps in
# the state: a live one working in the worktree is still the feature's.
saved_agents, saved_state, saved_wt = telegramd.agents, telegramd.feature_state, telegramd.feature_wt
try:
    telegramd.feature_state = lambda repo, slug: {"step": "done", "steps": {}}
    telegramd.feature_wt = lambda repo, slug: "/nowhere/shop-alpha"
    telegramd.agents = lambda: [{"sessionId": "s-retro", "cwd": "/nowhere/shop-alpha/app",
                                 "status": "idle"},
                                {"sessionId": "s-other", "cwd": "/nowhere/shop-beta"}]
    check("a session open in the feature's worktree is the feature's",
          telegramd.feature_session("/nowhere/shop", "alpha"), ("s-retro", "done"))
    telegramd.agents = lambda: [{"sessionId": "s-other", "cwd": "/nowhere/shop-alphabet"}]
    check("and only one there", telegramd.feature_session("/nowhere/shop", "alpha"), ("", "done"))
    # Claude Code says "waiting" of a session asking the person something:
    # open, and waiting for them — not "no session is open".
    saved_feats_of, saved_repo = telegramd.features_of_name, telegramd.repo_path
    telegramd.features_of_name = lambda name: ([("alpha", "1/6 planning", "/nowhere/shop-alpha")], "")
    telegramd.repo_path = lambda name: "/nowhere/shop"
    try:
        for status, want in (("waiting", "feat.blocked"), ("compacting", "feat.idle")):
            telegramd.agents = lambda: [{"sessionId": "s-plan", "cwd": "/nowhere/shop-alpha",
                                         "status": status}]
            check("a session %s is shown open" % status,
                  t(want).strip() in telegramd.feature_card("shop", "alpha"), True)
    finally:
        telegramd.features_of_name, telegramd.repo_path = saved_feats_of, saved_repo
finally:
    telegramd.agents, telegramd.feature_state, telegramd.feature_wt = saved_agents, saved_state, saved_wt

# A feature whose orchestrator waits on a question is at work, session or none.
saved_pa, saved_fs = telegramd.pending_ask, telegramd.feature_session
try:
    telegramd.feature_session = lambda repo, slug: ("", "review")
    telegramd.pending_ask = lambda channel: {"id": "q", "prompt": "Run the regression? "}
    check("an orchestrator waiting on a question is busy",
          telegramd.feature_busy("/nowhere/shop", "alpha"), True)
    telegramd.pending_ask = lambda channel: None
    check("and nothing at all is free", telegramd.feature_busy("/nowhere/shop", "alpha"), False)
finally:
    telegramd.pending_ask, telegramd.feature_session = saved_pa, saved_fs

# A topic's card follows its session: drawn again when the session changes,
# left alone while it does not.
names = ("agents", "known_repos", "feature_records", "feature_dir", "load_record", "save_record",
         "feature_session", "session_state", "features_of_name", "card")
saved = {n: getattr(telegramd, n) for n in names}
records = {"alpha": {"card": 55}}
states = {"now": ""}
edits = []
try:
    answered_agents = {"ok": True}
    telegramd.agents = lambda: telegramd._AGENTS.update(ok=answered_agents["ok"]) or []
    telegramd.known_repos = lambda: ["/nowhere/shop"]
    telegramd.feature_records = lambda repo: ["alpha"]
    telegramd.feature_dir = lambda repo, slug: "/nowhere/shop-alpha/.sclaude/local/feature"
    telegramd.load_record = lambda repo, slug: dict(records[slug])
    telegramd.save_record = lambda repo, slug, record: records.__setitem__(slug, record)
    telegramd.feature_session = lambda repo, slug: ("s1", "plan")
    telegramd.session_state = lambda session, cache=None: states["now"]
    telegramd.features_of_name = lambda name: ([], "")
    telegramd.card = lambda name, slug, **kw: ("card " + states["now"], [])

    class EditBot(object):
        def edit(self, msg, text, rows):
            edits.append((msg, text))
            return True
    telegramd.check_card_states(EditBot(), now=10 ** 9)
    check("a card whose session has not changed is left alone", edits, [])
    states["now"] = "waiting"
    telegramd.check_card_states(EditBot(), now=10 ** 9 + 30)
    check("and not looked at again within the minute", edits, [])
    answered_agents["ok"] = False
    telegramd.check_card_states(EditBot(), now=10 ** 9 + 45 + 60)
    check("Claude Code not answering redraws nothing", edits, [])
    answered_agents["ok"] = True
    telegramd._CARD_LOOKED[0] = 0.0
    telegramd.check_card_states(EditBot(), now=10 ** 9 + 61)
    check("a session that changed draws its card again", edits, [(55, "card waiting")])
    telegramd.check_card_states(EditBot(), now=10 ** 9 + 122)
    check("once", len(edits), 1)
    check("the state shown is recorded", records["alpha"].get("card_state"), "waiting")
finally:
    for n, f in saved.items():
        setattr(telegramd, n, f)
    telegramd._CARD_LOOKED[0] = 0.0

check("the screens are drawn for the page only while it asks", telegramd.ON_PAGE, False)

if failures:
    print("webmenu: FAILED: %d" % len(failures))
    for name, want, got in failures:
        print("  %s\n    expected: %r\n    got:      %r" % (name, want, got))
    sys.exit(1)
print("webmenu: all checks passed")
