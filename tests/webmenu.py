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
REAL_POPEN = webmenu.subprocess.Popen
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
check_true("the page asks again by itself", view["follow"].startswith("restart_wait:"))
wait = view["follow"]
view = press(wait)
check("until the bot is back it still waits", (view["text"], view["follow"]),
      (t("svc.restarting"), wait))
check("and the chat hears nothing of the waiting", sent(), [])
# The new process: its line in the chat changes, and the mark goes with it.
telegramd.report_restart(telegramd.Bot("t:k", 12345))
check("the bot back takes the mark off", read().get("restart_page"), False)
view = press(wait)
check("then the page says so, and stops asking", (view["text"], view["follow"]),
      (t("svc.restarted"), None))
check_true("with Settings under it",
           any(b.get("callback_data") == "svc_restart" for row in view["rows"] for b in row))
with telegramd.locked() as st:
    st["restart_page"] = True
view = press("restart_wait:%d" % (time.time() - webmenu.RESTART_WAIT - 5))
check("a bot not back in time is said to be so",
      (view["text"], view["follow"]), (t("svc.notback", unit=webmenu.BOT_UNIT), None))
with telegramd.locked() as st:
    st["restart_page"] = False
# A restart whose line never reached the chat still ends the page's wait.
with telegramd.locked() as st:
    st["restart_page"], st["restart_notify"] = True, 0
check("without a line to change", telegramd.report_restart(telegramd.Bot("t:k", 12345)), False)
check("the mark still goes", read().get("restart_page"), False)

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
# Opened by the Menu button, which knows no topic: no guess — the latest
# feature was another topic's — but the question which one.
webmenu.features = lambda: [("shop/alpha", "shop", "alpha", 2), ("shop/beta", "shop", "beta", 1)]
view = press("")
check("the Menu button's page stands on no feature", view["home"] or "", "")
check("and asks which", view["text"], t("menu.pickhome"))
check("listing them", [b["callback_data"] for row in view["rows"] for b in row][:2],
      ["home:shop/alpha", "home:shop/beta"])
view = press("home:shop/alpha")
check("the one chosen is the one", (view["home"], "📍 alpha" in view["text"]), ("shop/alpha", True))
webmenu.features = lambda: []
check("with no feature at all, the menu itself", press("")["main"], True)
webmenu.features = lambda: [("shop/alpha", "shop", "alpha", 2), ("shop/beta", "shop", "beta", 1)]
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
               "context": "  1)   Finish up                        4/7 done — preview\n"
                          "  2)   Return to development (return)   back to step 2, with notes\n"
                          "  3)   Sync with main (sync)            up to date\n"
                          "  4)   Drop the feature (drop)          clear its traces\n  5)   Go back"}
    saved_feats, saved_dev, saved_origin = (telegramd.features_of_name, telegramd.feature_dev,
                                            telegramd.gate_origin)
    telegramd.features_of_name = lambda name: ([("alpha", "4/7 done, waiting for merge", "")], "")
    telegramd.feature_dev = lambda repo, slug: ("alpha", 3101, True)
    telegramd.gate_origin = lambda *a: "https://box.tail1.ts.net:8443"
    try:
        telegramd.pending_ask = lambda channel: ACTIONS
        view = press("fc:acts:shop/alpha")
        check("the actions are not a numbered question on the page", "[1-5]" in view["text"], False)
        check("the current step is marked", "📍<b>review</b>" in view["text"], True)
        flat = [(b.get("style") == "caption" and "§" + b["text"])
                or b.get("callback_data") or (b.get("web_app") and "map")
                for row in view["rows"] for b in row]
        expected = ["§" + t("act.back", n="2 · code"), "pa:q2:2", "§" + t("act.stay"), "pa:q2:3",
                    "§" + t("act.forward"), "pa:q2:1", "§" + t("act.end"), "pa:q2:4",
                    "pa:q2:5", "topic:shop:alpha"]
        # The process map, through the gate, when the feature has a dev label.
        maps = [b["web_app"]["url"] for row in view["rows"] for b in row if b.get("web_app")]
        check("the map is offered", len(maps), 1)
        if maps:
            expected.insert(expected.index("pa:q2:5"), "map")
            check("the map opens through the gate",
                  "/__sclaude/tg?f=" in maps[0] and "p=%2F__sclaude%2Fflow%3Ff%3D" in maps[0], True)
        check("grouped by where they lead: back, staying, forward, the end", flat, expected)
        check("each says what it does",
              [b.get("hint") for row in view["rows"] for b in row if b.get("callback_data") == "pa:q2:2"],
              ["back to step 2, with notes"])
        # A feature with no dev server yet: the button starts one first.
        telegramd.feature_dev = lambda repo, slug: None
        view = press("fc:acts:shop/alpha")
        check("with no dev server the map starts one",
              [b.get("callback_data") for row in view["rows"] for b in row
               if b.get("text") == t("act.map")], [telegramd.card_data("map", "shop/alpha")])
    finally:
        telegramd.features_of_name = saved_feats
        telegramd.feature_dev, telegramd.gate_origin = saved_dev, saved_origin
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
    for step, first in (("2/7 coding", t("page.continuestep", step="2/7 coding")),
                        ("4/7 done, waiting for merge", t("page.finish"))):
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
    telegramd.features_of_name = lambda name: ([("alpha", "1/7 planning", "/nowhere/shop-alpha")], "")
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
names = ("agents", "serve_config", "known_repos", "feature_records", "feature_dir", "load_record", "save_record",
         "feature_session", "session_state", "features_of_name", "card")
saved = {n: getattr(telegramd, n) for n in names}
records = {"alpha": {"card": 55}}
states = {"now": ""}
edits = []
try:
    answered_agents = {"ok": True}
    telegramd.agents = lambda: telegramd._AGENTS.update(ok=answered_agents["ok"]) or []
    serve_reads = []
    telegramd.serve_config = lambda: serve_reads.append(1) or {}
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
    check("tailscale read once for the pass", serve_reads, [1])
    telegramd.check_card_states(EditBot(), now=10 ** 9 + 122)
    check("once", len(edits), 1)
    check("the state shown is recorded", records["alpha"].get("card_state"), "waiting")
finally:
    for n, f in saved.items():
        setattr(telegramd, n, f)
    telegramd._CARD_LOOKED[0] = 0.0

# A wait inside a press lets other calls in, and keeps its own language and
# ON_PAGE when it resumes.
import threading  # noqa: E402
got_in = []
with webmenu.held():
    telegramd.ON_PAGE = True
    other = threading.Thread(target=lambda: webmenu._LOCK.acquire() and (
        got_in.append(1), setattr(telegramd, "ON_PAGE", False), webmenu._LOCK.release()))
    other.start()
    webmenu.pause(0.3)
    other.join(2)
    check("another call ran during the wait", got_in, [1])
    check("and the waiting call is still on the page", telegramd.ON_PAGE, True)
telegramd.ON_PAGE = False

# Only the call that holds the lock lets it go: another thread's unlocked()
# runs its function with the lock still held.
seen = []
with webmenu.held():
    stranger = threading.Thread(target=lambda: webmenu.unlocked(
        lambda: seen.append(webmenu._LOCK.locked())))
    stranger.start()
    stranger.join(2)
check("a thread that does not hold the lock does not release it", seen, [True])

check("the screens are drawn for the page only while it asks", telegramd.ON_PAGE, False)

# --- a new feature: the terminal's picker, on the page -------------------------
import subprocess  # noqa: E402
# git is run for real here: the branch a start would collide with.
subprocess.Popen = REAL_POPEN
shop = os.path.join(box, "shop")
os.makedirs(shop)
subprocess.run(["git", "init", "-q", shop], check=True)
subprocess.run(["git", "-C", shop, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q",
                "--allow-empty", "-m", "x"], check=True)
subprocess.run(["git", "-C", shop, "branch", "feat/42-taken"], check=True)
ISSUES = [
    {"mine": True, "number": 61, "title": "Alpha <b>bold</b>", "labels": "Dev,ui",
     "blocked": "#37", "blockers": [(37, "the base")]},
    {"mine": False, "number": 59, "title": "Gamma", "labels": "", "blocked": "", "blockers": []},
]
fetched = []
lister = webmenu.issue_list()
saved_nf = dict(repo_path=telegramd.repo_path, gh_slug=telegramd.gh_slug,
                start_sclaude=telegramd.start_sclaude, new_feature_topic=telegramd.new_feature_topic,
                new_topic_of=telegramd.new_topic_of,
                run=telegramd.run, fetch=lister.fetch)
started = []
telegramd.repo_path = lambda name: shop if name == "shop" else ""
telegramd.gh_slug = lambda repo: "o/shop"
telegramd.start_sclaude = lambda repo, args: started.append((repo, args))
telegramd.new_feature_topic = lambda bot, name: 77
telegramd.new_topic_of = lambda name: 77
lister.fetch = lambda slug: fetched.append(slug) or [dict(i) for i in ISSUES]
webmenu._ISSUES.clear()
try:
    out = press("newfeat:shop")
    flat = [b for row in out["rows"] for b in row]
    check("the list is GitHub's", fetched, ["o/shop"])
    check("a name first, then mine, then the rest",
          [b["text"] for b in flat][:5],
          [t("nf.byname"), t("nf.mine"), "#61 Alpha <b>bold</b>", t("nf.other"), "#59 Gamma"])
    check("the blockers before the labels", flat[2].get("hint"),
          t("nf.blockedby", by="#37") + " · Dev, ui")
    check("no field on the list", out["input"], None)
    check("showing the list leaves nothing in the chat", sent(), [])
    press("nfi:shop:61")
    check("the issue screen reuses the list", fetched, ["o/shop"])
    out = press("nfi:shop:61")
    check_true("the blockers are named", "#37  the base" in out["text"])
    check_true("the title is escaped", "&lt;b&gt;bold" in out["text"])
    check("the branch is suggested", out["input"]["value"], "61-alpha-b-bold-b")
    check("a blocked one starts anyway", out["input"]["button"], t("nf.startanyway"))
    out = press(out["input"]["action"] + "61-alpha")
    check("started from the issue, the blockers seen",
          started, [(shop, ["new", "--issue", "61", "--blocked-ok", "--", "61-alpha"])])
    check("the page says so", out["text"],
          t("nf.startedtopic", slug="61-alpha", repo="shop"))
    check("and the chat keeps it in the new topic", sent(), [("📱 " + out["text"], 77)])
    del started[:]
    out = press("nfn:shop:1")
    check("a name gets an issue by default", out["input"]["action"], "nfgo:shop::1:")
    out = press("nfn:shop:0")
    check("the box unticked", out["input"]["action"], "nfgo:shop::0:")
    check("under the same name, so the text stays", out["input"]["name"], "nf-name:shop")
    out = press("nfgo:shop::1:Кириллица")
    check("a name with no Latin letter is refused", started, [])
    check_true("and says why", t("nf.badname") in out["text"])
    check("keeping what was typed", out["input"]["value"], "Кириллица")
    out = press("nfgo:shop:59:-:42-taken")
    check("an existing branch is refused before sclaude", started, [])
    check_true("by name", "42-taken" in out["text"] and out["input"] is not None)
    press("nfgo:shop::0:Dark  mode")
    check("a name, without an issue", started, [(shop, ["new", "--no-issue", "--", "Dark mode"])])
    del started[:]
    press("nfgo:shop::1:Dark mode")
    check("a name, with an issue", started, [(shop, ["new", "--create-issue", "--", "Dark mode"])])
    del started[:]
    press("nfgo:shop::0:-dash")
    check("a name with a dash first is still a name", started,
          [(shop, ["new", "--no-issue", "--", "-dash"])])

    # GitHub not answering is not "no issues" for two minutes.
    webmenu._ISSUES.clear()
    lister.fetch = lambda slug: None
    check("a failed fetch shows none", webmenu.open_issues("shop"), (None, True))
    out = press("nfi:shop:61")
    check("and an issue is not called closed for it", out["text"], t("nf.noanswer").strip())
    out = press("newfeat:shop")
    check_true("the list says GitHub did not answer", t("nf.noanswer") in out["text"])
    lister.fetch = lambda slug: fetched.append(slug) or [dict(i) for i in ISSUES]
    check("and is not kept", [i["number"] for i in webmenu.open_issues("shop")[0]], [61, 59])
    del fetched[:]
    webmenu._ISSUES.clear()
    press("nfi:shop:99")
    check("an issue missing from a list fetched for this press is not fetched again",
          fetched, ["o/shop"])

    # --- the project's config ------------------------------------------------
    # With no file a choice would write one of one key, which `sclaude new`
    # would take for the project's whole config.
    out = press("cfg:shop:qa")
    check("no file, no choice", [b["callback_data"] for row in out["rows"] for b in row],
          ["cfg:shop"])
    check_true("and why", t("cfg.writefirst") in out["text"])
    out = press("nfn:shop:1")
    check_true("a start without a config names the question still to come",
               t("nf.noconfig") in out["text"])
    os.makedirs(os.path.join(shop, ".sclaude"))
    with open(os.path.join(shop, ".sclaude", "config.json"), "w") as fh:
        json.dump({"review": "local", "commands": {"lint": "npm run lint"}}, fh)
    out = press("cfg:shop")
    labels = [b["text"] for row in out["rows"] for b in row]
    check("the sections with choices first", labels[:3],
          ["⚙️ review · local", "⚙️ qa · github (not set)", "⚙️ merge · both (not set)"])
    check_true("every section of the example", any(x.startswith("commands · lint") for x in labels))
    out = press("cfg:shop:review")
    check("the one in force is marked", [b["text"] for row in out["rows"] for b in row][:3],
          ["github", "✓ local", "off"])
    check_true("the explanation is sclaude's", "where the pull request" in out["text"])
    ran = []
    telegramd.run = lambda cmd, timeout=25: ran.append(cmd) or "✓ review: github\nrc=0"
    out = press("cfgset:shop:review:github")
    check("set through sclaude, so what it implies is done",
          ran, ["cd %s && sclaude config set review github 2>&1; echo \"rc=$?\"" % shop])
    check("the chat keeps the line", sent(), [("📱 " + t("cfg.set", section="review", value="github"), None)])
    del ran[:]
    out = press("cfgset:shop:review:local")
    check("the value in force is not set again", ran, [])
    check("nor traced", sent(), [])
    # Written, and the Actions after it cut short: set, and said so.
    def partly(cmd, timeout=25):
        with open(os.path.join(shop, ".sclaude", "config.json")) as fh:
            data = json.load(fh)
        data["qa"] = "auto"
        with open(os.path.join(shop, ".sclaude", "config.json"), "w") as fh:
            json.dump(data, fh)
        return "the command timed out"
    telegramd.run = partly
    out = press("cfgset:shop:qa:auto")
    check_true("a value written is not called unchanged",
               t("cfg.setpartly", section="qa", value="auto") in out["text"])
    telegramd.run = lambda cmd, timeout=25: ran.append(cmd) or "rc=0"
    out = press("cfgset:shop:commands:x")
    check("a structure is not set from here", ran, [])
    out = press("cfg:shop:commands")
    check_true("a structure is shown", "npm run lint" in out["text"])
    check("with only the way back", [b["callback_data"] for row in out["rows"] for b in row],
          ["cfg:shop"])
finally:
    for n, f in saved_nf.items():
        if n == "fetch":
            lister.fetch = f
        else:
            setattr(telegramd, n, f)
    subprocess.Popen = lambda args, **kw: SPAWNED.append(args)

if failures:
    print("webmenu: FAILED: %d" % len(failures))
    for name, want, got in failures:
        print("  %s\n    expected: %r\n    got:      %r" % (name, want, got))
    sys.exit(1)
print("webmenu: all checks passed")
