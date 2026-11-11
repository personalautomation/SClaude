#!/usr/bin/env python3
#
# keepawake's widgets (Bot API 10.4): the code Telegram takes, the state that
# stays within its bytes, the warning before sleep as a widget, and a tap in
# it answered — always, a failed one too.
#
# Run it with: python3 tests/widgets.py
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_TMP = tempfile.mkdtemp(prefix="widgets-test-")
os.environ["KEEPAWAKE_STATE"] = os.path.join(_TMP, "state.json")
os.environ["KEEPAWAKE_LOCK"] = os.path.join(_TMP, ".lock")
os.environ["KEEPAWAKE_TOPICS"] = os.path.join(_TMP, "topics")

from keepawake import asks, card_view, handling, i18n, menu_widget, menus, notices, processes, repos, review_keys, sessions, sleep_warning, state, telegramd, topics, widgets  # noqa: E402
from keepawake.state import read  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def check_true(name, got):
    if not got:
        failures.append((name, "true", got))


class Bot(object):
    def __init__(self):
        self.chat_id = 12345
        self.thread = 0
        self.last_error = ""
        self.sent, self.widgets, self.data, self.captions = [], [], [], []
        self.edits, self.deletes, self.answers, self.widget_answers = [], [], [], []
        self.can_delete = self.can_edit = self.can_widget = True

    def send(self, text, kb=None, quiet=False, thread=None):
        self.sent.append((text, kb))
        return 700

    def send_widget(self, html, data, caption, keyboard=None, quiet=False, thread=None,
                    above=False):
        self.widgets.append((html, data, caption))
        self.above = above
        return 800 + len(self.widgets) - 1

    def widget_data(self, mid, data):
        self.data.append((mid, json.loads(data)))
        self.last_error = "" if self.can_widget else "bad request: message to edit not found"
        return self.can_widget

    def caption(self, mid, text, keyboard=None):
        self.captions.append((mid, text))
        return True

    def answer_widget(self, qid, data=None):
        self.widget_answers.append((qid, json.loads(data) if data else None))

    def edit(self, mid, text, kb=None):
        self.edits.append((mid, text))
        return self.can_edit

    def delete(self, mid):
        self.deletes.append(mid)
        return self.can_delete

    def answer(self, cid, text=None, alert=False):
        self.answers.append((text, alert))


try:
    # --- the code ----------------------------------------------------------
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        code = widgets.code("hold", sleep_warning.HOLD_LABELS)
        check_true("the hold widget is within Telegram's limits (%s)" % lang, widgets.fits(code))
        check("its labels are filled (%s)" % lang, "/*L*/" in code, False)
        used = set(re.findall(r"\bL\.(\w+)", code))
        check("every label it reads is given (%s)" % lang,
              sorted(used - set(sleep_warning.HOLD_LABELS)), [])
    check("a label cannot end the script early",
          "</script>" in widgets.code("hold", {"l": "msg.stale"}).split("<script>")[1][:-12], False)
    # Its script parses, where node is at hand to say so.
    if shutil.which("node"):
        script = widgets.code("hold", sleep_warning.HOLD_LABELS).split("<script>")[1].split("</script>")[0]
        path = os.path.join(_TMP, "hold.js")
        with open(path, "w") as fh:
            fh.write(script)
        out = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        check("the hold widget's script parses", out.returncode, 0)

    # --- the state ---------------------------------------------------------
    long = widgets.state({"u": 1, "w": "я" * 2000}, trim="w")
    check_true("a long field is cut to fit", len(long.encode()) <= widgets.DATA_MAX)
    check_true("with an ellipsis", json.loads(long)["w"].endswith("…"))
    check_true("and keeps nearly all the room, Cyrillic too", len(long.encode()) > widgets.DATA_MAX - 10)
    escaped = widgets.state({"w": '"\\' * 600}, trim="w")
    check_true("escapes are counted as JSON writes them", len(escaped.encode()) <= widgets.DATA_MAX)
    try:
        widgets.state({"w": "я" * 2000})
        check("a state over the limit with nothing to cut is refused", "accepted", "refused")
    except ValueError:
        pass
    check("the switch is on unless turned off", widgets.enabled(), True)

    # --- the warning as a widget -------------------------------------------
    i18n.set_lang("en")
    now = int(time.time())

    def window(**kw):
        with state.locked() as st:
            st.update(dict(until_ts=now + 1200, until_local="21:00", warned_for_ts=0,
                           warn_message_id=0, warn_widget=False, decision="",
                           updated_ts=now, sleep_trail=[]))
            st.update(kw)

    real_needs = sleep_warning.needs_warning
    sleep_warning.needs_warning = lambda data, now: True
    try:
        window()
        bot = Bot()
        sleep_warning.check_warning(bot)
        check("the warning goes as a widget", (len(bot.widgets), bot.sent), (1, []))
        shown = json.loads(bot.widgets[0][1])
        check("drawn from the deadline", (shown["u"], shown["s"]), (now + 1200, ""))
        check_true("with why it is coming", shown["w"])
        check_true("and what comes next", i18n.t("widget.hold.next") in json.dumps(
            json.loads(bot.widgets[0][0].split("const W = window.TelegramWidget, L = ")[1].split(";")[0]),
            ensure_ascii=False))
        check_true("its caption says when", "21:00" in bot.widgets[0][2])
        check("and is remembered as a widget",
              (read()["warn_message_id"], read()["warn_widget"]), (800, True))

        with state.locked() as st:
            st["widgets"] = False
        window()
        bot = Bot()
        sleep_warning.check_warning(bot)
        check("switched off, it is a message again", (len(bot.sent), bot.widgets), (1, []))
        check("not remembered as a widget", read()["warn_widget"], False)
        with state.locked() as st:
            st["widgets"] = True
    finally:
        sleep_warning.needs_warning = real_needs

    # A tap on "add an hour": answered with the new state, then the state and
    # the caption stay with the message.
    window(warned_for_ts=now + 1200, warn_message_id=800, warn_widget=True)
    bot = Bot()
    handling.Handler(bot).widget_query({"id": "q1", "data": "hold:x:%d" % (now + 1200),
                                        "message_id": 800, "chat": {"id": 12345}})
    check("a tap is answered", [q for q, _ in bot.widget_answers], ["q1"])
    answer = bot.widget_answers[0][1]
    check("with the widget's new state", answer["s"], "x")
    check_true("the deadline moved", read()["until_ts"] >= now + state.HOLD_SECONDS)
    check("the state stays with the message", bot.data, [(800, answer)])
    check_true("and so does the caption", bot.captions and bot.captions[0][0] == 800)
    check("the warning is let go", read()["warn_message_id"], 0)
    check("its answer is kept while true", [e[0] for e in read()["sleep_trail"]], [800])

    # "Let it sleep".
    window(warned_for_ts=now + 1200, warn_message_id=800, warn_widget=True, hard_hold=True)
    bot = Bot()
    handling.Handler(bot).widget_query({"id": "q2", "data": "hold:z:%d" % (now + 1200),
                                        "message_id": 800})
    check("let sleep: the widget says so", bot.widget_answers[0][1]["s"], "z")
    check("and the hold is released", (read()["decision"], read()["hard_hold"]), ("sleep", False))

    # A tap on a window that is over: out of date, and the widget goes.
    window(warned_for_ts=now + 1200, warn_message_id=800, warn_widget=True)
    bot = Bot()
    handling.Handler(bot).widget_query({"id": "q3", "data": "hold:x:%d" % (now + 5),
                                        "message_id": 800})
    check("a stale tap is answered as out of date", bot.widget_answers, [("q3", widgets.STALE)])
    check("the deadline did not move", read()["until_ts"], now + 1200)
    check("and the widget goes", bot.deletes, [800])

    # Nonsense, and a handler that fails, are still answered.
    bot = Bot()
    handling.Handler(bot).widget_query({"id": "q4", "data": "what", "message_id": 800})
    check("an unknown tap is answered as out of date", bot.widget_answers, [("q4", widgets.STALE)])
    bot = Bot()
    real_press = sleep_warning.hold_press
    sleep_warning.hold_press = lambda *a: 1 / 0
    try:
        handling.Handler(bot).widget_query({"id": "q5", "data": "hold:x:1", "message_id": 800})
    except ZeroDivisionError:
        pass
    finally:
        sleep_warning.hold_press = real_press
    check("a failed tap is answered all the same", bot.widget_answers, [("q5", None)])

    # Extended from elsewhere: the widget's state and caption say so, its text
    # is not touched.
    window(until_ts=now + 7200, until_local="22:00", warned_for_ts=now + 1200,
           warn_message_id=800, warn_widget=True)
    bot = Bot()
    sleep_warning.settle_warning(bot, read(), now)
    check("extended elsewhere — the widget says so",
          ([m for m, _ in bot.data], bot.data[0][1]["s"], bot.edits), ([800], "x", []))
    check_true("its caption too", "22:00" in bot.captions[0][1])
    # The same for a message: its text.
    window(until_ts=now + 7200, until_local="22:00", warned_for_ts=now + 1200,
           warn_message_id=700, warn_widget=False)
    bot = Bot()
    sleep_warning.settle_warning(bot, read(), now)
    check("a message is edited as before", ([m for m, _ in bot.edits], bot.data), ([700], []))

    # A widget that can no longer be deleted is turned into "out of date".
    bot = Bot()
    bot.can_delete = bot.can_edit = False
    menus.retire(bot, 800)
    check("an old widget is drawn out of date", bot.data, [(800, widgets.STALE)])
    check("and its caption says so", bot.captions, [(800, i18n.t("msg.stale"))])

    # A tap answered but its state not kept: the widget would ask again with
    # the old deadline, so it goes.
    window(warned_for_ts=now + 1200, warn_message_id=800, warn_widget=True)
    bot = Bot()
    bot.can_widget = False
    handling.Handler(bot).widget_query({"id": "q9", "data": "hold:x:%d" % (now + 1200),
                                        "message_id": 800})
    check("a widget whose answer was not kept goes", (bot.deletes, bot.captions), ([800], []))
    check("and is kept in the trail until its expiry", [e[0] for e in read()["sleep_trail"]], [800])
    window(warned_for_ts=now + 1200, warn_message_id=800, warn_widget=True,
           sleep_trail=[[700, now + 600]])
    bot = Bot()
    bot.can_widget = bot.can_delete = bot.can_edit = False
    handling.Handler(bot).widget_query({"id": "q10", "data": "hold:x:%d" % (now + 1200),
                                        "message_id": 800})
    # Compared by id and expiry, not the bench's own clock: the press reads
    # its own, a second later on a loaded machine.
    kept = dict(read()["sleep_trail"])
    check_true("with the network down, every line is kept to be tried next turn",
               sorted(kept) == [700, 800] and kept[800] <= time.time() < kept[700])

    # The switch in the settings.
    bot = Bot()
    handling.Handler(bot).callback({"id": "c", "data": "svc_widgets", "message": {"message_id": 5}})
    check("the settings turn widgets off", widgets.enabled(), False)
    check_true("and show it", "messages only" in json.dumps(menus.services_keyboard()))
    handling.Handler(bot).callback({"id": "c", "data": "svc_widgets", "message": {"message_id": 5}})
    check("and on again", widgets.enabled(), True)

    # --- a session's question as a widget --------------------------------
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        check_true("the question widget is within Telegram's limits (%s)" % lang,
                   widgets.fits(widgets.code("ask", asks.ASK_LABELS)))
        code = widgets.code("ask", asks.ASK_LABELS)
        check("every label it reads is given (%s)" % lang,
              sorted(set(re.findall(r"\bL\.(\w+)", code)) - set(asks.ASK_LABELS)), [])
    if shutil.which("node"):
        path = os.path.join(_TMP, "ask.js")
        with open(path, "w") as fh:
            fh.write(widgets.code("ask", asks.ASK_LABELS).split("<script>")[1].split("</script>")[0])
        check("the question widget's script parses",
              subprocess.run(["node", "--check", path], capture_output=True).returncode, 0)
    i18n.set_lang("en")

    repo = os.path.join(_TMP, "repo")
    channel = os.path.join(repo, ".git", "sclaude")
    os.makedirs(os.path.join(channel, "closed"))
    saved_repos = repos.known_repos, repos.repo_path
    repos.known_repos = lambda: [repo]
    repos.repo_path = lambda name: repo if name == "repo" else ""

    def lay(qid, form, options=None, context="", prompt="Ship it?"):
        q = {"prompt": prompt, "form": form, "context": context, "id": qid, "pid": os.getpid()}
        if options:
            q["options"] = options
        with open(os.path.join(channel, "ask.json"), "w") as fh:
            json.dump(q, fh)

    def close(qid, reply=None, source="tty"):
        if reply is not None:
            with open(os.path.join(channel, "closed", qid + ".json"), "w") as fh:
                json.dump({"id": qid, "reply": reply, "from": source}, fh)
        os.unlink(os.path.join(channel, "ask.json"))

    def answer_file():
        try:
            with open(os.path.join(channel, "answer.json")) as fh:
                return json.load(fh)
        except OSError:
            return None
        finally:
            try:
                os.unlink(os.path.join(channel, "answer.json"))
            except OSError:
                pass

    def tap(bot, data, mid):
        handling.Handler(bot).widget_query({"id": "t", "data": data, "message_id": mid})
        return bot.widget_answers[-1][1]

    try:
        # Yes or no.
        lay("q1", "yn")
        bot = Bot()
        asks.check_asks(bot)
        check("a yes/no question goes as a widget", (len(bot.widgets), bot.sent), (1, []))
        check("with its two answers", json.loads(bot.widgets[0][1]), {"y": 1})
        check_true("the question is the caption above it", "Ship it?" in bot.widgets[0][2] and bot.above)
        check("remembered as a widget", asks.get_shown("repo").get("widget"), True)
        got = tap(bot, "ask:y", 800)
        check("a tap answers sclaude", answer_file(), {"reply": "y", "id": "q1"})
        check("and the widget shows the answer", (got["s"], got["r"]), ("a", i18n.t("ask.yes")))
        check("which stays with the message", bot.data[-1], (800, got))
        check("a second tap changes nothing", (tap(bot, "ask:n", 800), answer_file()), (None, None))
        close("q1", "y", "telegram")
        asks.check_asks(bot)

        # A long list: every option a button, paged.
        labels = ["Option %d" % i for i in range(1, 13)]
        lay("q2", "pick:12", labels)
        bot = Bot()
        asks.check_asks(bot)
        shown = json.loads(bot.widgets[0][1])
        check("a list's first page is in the state", (shown["o"], shown["t"]), (labels[:8], 12))
        check("the next page comes in an answer", tap(bot, "ask:p1", 800), {"q": 1, "o": labels[8:]})
        check("a number off the list is refused", (tap(bot, "ask:13", 800), answer_file()), (None, None))
        got = tap(bot, "ask:11", 800)
        check("a later page's option answers by its number", answer_file(), {"reply": "11", "id": "q2"})
        check("shown by its label", got["r"], "✅ Option 11")
        close("q2", "11", "telegram")
        asks.check_asks(bot)

        # Labels found in the numbered list printed above the question.
        listed = "\n".join("  %d)  Task %d   on the board" % (i, i) for i in range(1, 31))
        lay("q3", "pick:30", None, "Pick a task:\n" + listed)
        bot = Bot()
        asks.check_asks(bot)
        shown = json.loads(bot.widgets[0][1])
        check("thirty options without labels take them from the list",
              (shown["o"][0], shown["t"]), ("Task 1 — on the board", 30))
        check("and the list leaves the caption", "1)" in bot.widgets[0][2], False)
        close("q3")
        asks.check_asks(bot)
        check("an unanswered question's widget goes", bot.deletes, [800])

        # Digits when nothing names the options.
        lay("q4", "pick:5")
        bot = Bot()
        asks.check_asks(bot)
        check("digits otherwise", json.loads(bot.widgets[0][1]), {"t": 5})
        # Answered at the terminal: the widget says so.
        close("q4", "2", "tty")
        asks.check_asks(bot)
        check("answered at the terminal", (bot.data[-1][1]["r"], bot.data[-1][1]["f"]), ("✅ 2", 1))

        # A question that wants typed text stays a message.
        lay("q5", "")
        bot = Bot()
        asks.check_asks(bot)
        check("a typed answer's question is a message", (len(bot.sent), bot.widgets), (1, []))
        close("q5")
        asks.check_asks(bot)

        # A typed answer with a suggestion: the suggestion is a button.
        lay("q8", "", None, "", "Branch name [add-search]: ")
        bot = Bot()
        asks.check_asks(bot)
        check("a suggested name is a widget's button", json.loads(bot.widgets[0][1]), {"d": "add-search"})
        check_true("and typing still answers it", i18n.t("ask.text") in bot.widgets[0][2])
        got = tap(bot, "ask:d", 800)
        check("the button answers with the suggestion", answer_file(), {"reply": "add-search", "id": "q8"})
        check("shown as answered", got["r"], "✅ add-search")
        close("q8", "add-search", "telegram")
        asks.check_asks(bot)

        # A long context is cut until the caption fits.
        lay("q6", "yn", None, "x" * 5000)
        bot = Bot()
        asks.check_asks(bot)
        check_true("the caption fits Telegram's 1024", asks.visible_length(bot.widgets[0][2]) <= 1024)
        close("q6")
        asks.check_asks(bot)

        # "Back" in the main chat leads back to the repository's features.
        lay("q7", "pick:2", ["Ship it", "Go back"])
        bot = Bot()
        asks.check_asks(bot)
        tap(bot, "ask:2", 800)
        check("a back answer brings the features back", len(bot.sent), 1)
        close("q7", "2", "telegram")
        asks.check_asks(bot)

        # An answer too long for the state is cut, not refused.
        check_true("a long answer fits the state", len(widgets.state(
            asks.answered_state({"options": ["я" * 900]}, "1")).encode()) <= widgets.DATA_MAX)

        # A tap on a message that shows no question.
        bot = Bot()
        check("a tap on no question is out of date", tap(bot, "ask:y", 999), widgets.STALE)
    finally:
        repos.known_repos, repos.repo_path = saved_repos

    # --- a process as a widget ---------------------------------------------
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        check_true("the process widget is within Telegram's limits (%s)" % lang,
                   widgets.fits(widgets.code("proc", processes.LABELS)))
    if shutil.which("node"):
        path = os.path.join(_TMP, "proc.js")
        with open(path, "w") as fh:
            fh.write(widgets.code("proc", processes.LABELS).split("<script>")[1].split("</script>")[0])
        check("the process widget's script parses",
              subprocess.run(["node", "--check", path], capture_output=True).returncode, 0)
    i18n.set_lang("en")

    feat = os.path.join(_TMP, "feat")
    os.makedirs(os.path.join(feat, "notes"))
    me = str(os.getpid())

    def printed(*lines):
        # As ask_feed writes them: time, level, pid, text.
        with open(os.path.join(feat, "notes", "feed.tsv"), "a") as fh:
            for level, text in lines:
                fh.write("%d\t%s\t%s\t%s\n" % (time.time(), level, me, text))

    class TopicBot(Bot):
        def send(self, text, keyboard=None, quiet=False, thread=None):
            return Bot.send(self, text, keyboard)

        def unbutton(self, mid, kb=None):
            pass

    class Log(object):
        def warning(self, *a):
            pass

    def turn(bot):
        notices.check(bot, [("repo", "feat", feat)], lambda n, s: 901, Log(),
                      keys=review_keys, procs=processes)

    bot = TopicBot()
    printed(("info", "🧪 Regression started: local · 13 parts"))
    turn(bot)
    check("a process's start opens a widget", (len(bot.widgets), bot.sent), (1, []))
    check_true("its caption is the start line", "Regression started" in bot.widgets[0][2])
    printed(("info", "part 3/13 passed"), ("info", "part 4/13 passed"))
    turn(bot)
    check("its lines go into it, not below it", (bot.sent, len(bot.widgets)), ([], 1))
    check_true("drawn as its latest lines", "part 4/13 passed" in bot.data[-1][1]["l"])
    printed(("warn", "part 5/13 failed"))
    turn(bot)
    check("a warning sends the widget again, and the old one goes",
          (len(bot.widgets), bot.deletes), (2, [800]))
    printed(("info", "🧪 Regression finished: local, green · 13/13"))
    turn(bot)
    check("its end leaves one message with the account", len(bot.sent), 1)
    check_true("which has the whole account",
               "Regression started" in bot.sent[0][0] and "part 5/13 failed" in bot.sent[0][0])
    check("and the widget goes", bot.deletes, [800, 801])
    check("nothing is left open", processes.load(feat), {})

    # A start and its end in one turn: a message, as before.
    bot = TopicBot()
    printed(("info", "🔧 Regression fix started: local"), ("info", "🔧 Regression fix finished: local"))
    turn(bot)
    check("a process begun and ended in one turn is a message", (len(bot.sent), bot.widgets), (1, []))

    # A warning that leads to the next start opens it with the start as its caption.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    printed(("warn", "the dev server restarted"), ("info", "🔍 Local review started: PR #1, round 2"))
    turn(bot)
    check("the next start ends the last process", len(bot.sent), 1)
    check_true("and opens its own widget, captioned by its start",
               len(bot.widgets) == 2 and "Local review started" in bot.widgets[1][2])
    check_true("the review's keys go under it", processes.load(feat)["open"]["msg"] == review_keys.load(feat).get("message_id"))
    # Its sclaude is gone: the widget does not count for ever.
    processes.sweep(bot, feat, is_alive=lambda pid: False)
    check_true("a process whose printer exited but which printed lately stays open",
               processes.load(feat).get("open"))
    quiet, processes.QUIET_END = processes.QUIET_END, -1
    processes.sweep(bot, feat, is_alive=lambda pid: False)
    processes.QUIET_END = quiet
    check("a process whose sclaude died ends", (processes.load(feat), len(bot.sent)), ({}, 2))

    # Switched off: no new widget.
    with state.locked() as st:
        st["widgets"] = False
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    check("with widgets off a start is a message", (len(bot.sent), bot.widgets), (1, []))
    with state.locked() as st:
        st["widgets"] = True

    # A long run's account ends with its result.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    printed(*[("info", "part %d passed" % i) for i in range(1, 16)])
    turn(bot)
    printed(("info", "  detail under a headline"), ("info", "🧪 Regression failed: local, part 16"))
    turn(bot)
    account = bot.sent[-1][0]
    check_true("a long account keeps its result", "Regression failed" in account and "Regression started" in account)
    check_true("and counts what it left out, once", account.count("more") == 1 and "… 5 more" in account)
    check_true("the indented detail is not in it", "detail under" not in account)

    # Lines before a new start are the open process's last.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    printed(("info", "part 13/13 passed"), ("info", "🔍 Local review started: PR #1, round 3"))
    turn(bot)
    check_true("the open process takes the lines before the next start",
               "part 13/13" in bot.sent[-1][0] and "part 13/13" not in json.loads(processes.view(processes.load(feat)["open"]))["l"])
    # Its sclaude prints its end and exits in the same turn: one account, with the end.
    printed(("info", "🔍 Local review finished: PR #1, round 3, 0 findings"))
    notices.check(bot, [("repo", "feat", feat)], lambda n, s: 901, Log(), keys=review_keys,
                  procs=type("P", (), {"take": staticmethod(processes.take),
                                       "sweep": staticmethod(lambda b, c: processes.sweep(b, c, is_alive=lambda p: False))}))
    check_true("an end printed before sclaude exited is in the account",
               "Local review finished" in bot.sent[-1][0] and processes.load(feat) == {})

    # A widget the network will not delete stays recorded until it goes.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    bot.can_delete = bot.can_edit = bot.can_widget = False
    printed(("info", "🧪 Regression finished: local"))
    turn(bot)
    check("its account went, its widget is kept to be taken away", (bool(processes.load(feat).get("gone")), "open" in processes.load(feat)), (True, False))
    bot.can_delete = True
    sent_before = len(bot.sent)
    turn(bot)
    check("and goes on the next turn, with no second account", (processes.load(feat), len(bot.sent)), ({}, sent_before))

    # The widget deleted by hand: the next lines send it again, quietly.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    bot.can_widget = False
    printed(("info", "part 1/13 passed"))
    turn(bot)
    check("a widget whose edit fails is sent again", (len(bot.widgets), processes.load(feat)["open"]["msg"]), (2, 801))
    bot.can_widget = True
    # An edit refused for another reason (a timeout) is carried by the next.
    real_edit = bot.widget_data
    bot.widget_data = lambda mid, data: setattr(bot, "last_error", "timed out") or False
    printed(("info", "part 1b/13 passed"))
    turn(bot)
    check("a timed-out edit sends nothing new", len(bot.widgets), 2)
    bot.widget_data = real_edit
    # A start and its end after a line of the open process: that line is in
    # the process's account only.
    printed(("info", "part 2/13 passed"), ("info", "🔧 Regression fix started: local"),
            ("info", "🔧 Regression fix finished: local"))
    turn(bot)
    check_true("a line before a start is not sent twice",
               sum("part 2/13" in m[0] for m in bot.sent) == 1 and "Regression fix finished" in bot.sent[-1][0])

    # The account goes before the next process's widget, and a failed
    # account keeps everything for the next turn.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    order = []
    real_send, real_widget = bot.send, bot.send_widget
    bot.send = lambda *a, **k: order.append("account") or real_send(*a, **k)
    bot.send_widget = lambda *a, **k: order.append("widget") or real_widget(*a, **k)
    printed(("info", "🔍 Local review started: PR #1, round 6"))
    turn(bot)
    check("the old account goes before the new widget", order, ["account", "widget"])
    bot.send, bot.send_widget = real_send, real_widget
    bot.send = lambda *a, **k: 0
    printed(("info", "🔍 Local review finished: PR #1, round 6"))
    turn(bot)
    check_true("an account not sent leaves the process open, its end put back",
               processes.load(feat).get("open") and "finished" in open(os.path.join(feat, "notes", "feed.tsv")).read())
    bot.send = real_send
    turn(bot)
    check("and goes on the next turn", (processes.load(feat), "round 6" in bot.sent[-1][0]), ({}, True))

    # A warning before the next start goes with that start.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    printed(("warn", "the database was reset"), ("info", "🔍 Local review started: PR #1, round 4"))
    turn(bot)
    check_true("a warning before a start is in the new widget, not the old account",
               "database was reset" not in bot.sent[-1][0]
               and "database was reset" in json.loads(bot.widgets[-1][1])["l"])
    printed(("info", "🔍 Local review finished: PR #1, round 4"))
    turn(bot)

    # A widget Telegram will not take away, and a new start after it: its id
    # is kept until it goes.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    bot.can_delete = bot.can_edit = bot.can_widget = False
    printed(("info", "🔍 Local review started: PR #1, round 5"))
    turn(bot)
    check_true("a widget not yet away is kept beside the new process",
               processes.load(feat).get("gone") and processes.load(feat)["open"]["msg"] != processes.load(feat)["gone"][0])
    bot.can_delete = bot.can_edit = bot.can_widget = True
    printed(("info", "🔍 Local review finished: PR #1, round 5"))
    turn(bot)
    check("and both go once Telegram lets them", processes.load(feat), {})

    # A long account keeps its result even when its lines are long.
    rec = {"lines": [["info", me, "🧪 x started " + "s" * 900, 1]]
           + [["info", me, "line %d " % i + "l" * 340, 1] for i in range(20)]
           + [["warn", me, "🧪 x failed", 1]]}
    text = processes.account(rec)
    check_true("a long account keeps its result", text.endswith("🧪 x failed") and len(text) <= notices.NOTE_MAX)

    # Switched off while a process runs: the next start is a message.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    with state.locked() as st:
        st["widgets"] = False
    printed(("info", "🔧 Regression fix started: local"))
    turn(bot)
    check("switched off, the next start ends the widget and is a message",
          (len(bot.widgets), len(bot.sent), processes.load(feat)), (1, 2, {}))
    with state.locked() as st:
        st["widgets"] = True

    # A regression's phase line through bin/sclaude-notify goes into the
    # feature's feed while widgets are on, so its widget takes it.
    home = os.path.join(_TMP, "home")
    os.makedirs(os.path.join(home, ".config", "keepawake"), exist_ok=True)
    with open(os.path.join(home, ".config", "keepawake", "env"), "w") as fh:
        fh.write("KEEPAWAKE_BOT_TOKEN=1:test\nKEEPAWAKE_CHAT_ID=1\n")
    os.chmod(os.path.join(home, ".config", "keepawake", "env"), 0o600)
    repo2 = os.path.join(_TMP, "repo2")
    tree = os.path.join(_TMP, "repo2-feat")
    os.makedirs(os.path.join(repo2, ".git", "worktrees", "repo2-feat"))
    os.makedirs(os.path.join(repo2, ".git", "sclaude", "ask", "feat"))
    os.makedirs(os.path.join(tree, ".sclaude", "local", "feature"))
    with open(os.path.join(tree, ".git"), "w") as fh:
        fh.write("gitdir: %s/.git/worktrees/repo2-feat\n" % repo2)
    with open(os.path.join(tree, ".sclaude", "local", "feature", "state.json"), "w") as fh:
        json.dump({"feature": "feat"}, fh)
    with open(os.path.join(tree, ".sclaude", "local", "feature", "telegram.json"), "w") as fh:
        json.dump({"thread": 901}, fh)
    notify = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "sclaude-notify")
    nenv = dict(os.environ, HOME=home, KEEPAWAKE_BOT_ALIVE="1")
    subprocess.run([notify, "--in", tree, "--quiet", "🧪 Regression started: local · 3 parts"], env=nenv, timeout=30)
    subprocess.run([notify, "--in", tree, "🧪 Regression failed: local, on e2e\nspec a failed"], env=nenv, timeout=30)
    with open(os.path.join(repo2, ".git", "sclaude", "ask", "feat", "notes", "feed.tsv")) as fh:
        fed = [line.rstrip("\n").split("\t") for line in fh]
    check("a phase line to a topic goes into the feature's feed",
          [(x[1], x[3]) for x in fed],
          [("info", "🧪 Regression started: local · 3 parts"), ("ring", "🧪 Regression failed: local, on e2e"),
           ("ring", "spec a failed")])
    # With the bot down the line is sent as before, not left in the feed.
    os.remove(os.path.join(repo2, ".git", "sclaude", "ask", "feat", "notes", "feed.tsv"))
    subprocess.run([notify, "--in", tree, "🧪 Regression started: local"],
                   env=dict(nenv, KEEPAWAKE_BOT_ALIVE="0"), timeout=30, capture_output=True)
    check("with the bot down a phase line is not left in the feed",
          os.path.exists(os.path.join(repo2, ".git", "sclaude", "ask", "feat", "notes", "feed.tsv")), False)
    check_true("a ring line sounds, unmarked",
               notices.feed_message([tuple(x[1:3]) + (x[3], 0) for x in fed[1:]])[1]
               and "⚠️" not in notices.feed_message([tuple(x[1:3]) + (x[3], 0) for x in fed[1:]])[0])

    # An orphaned end refused by the network is given up a day from its
    # first refusal, not from its last line.
    bot = TopicBot()
    printed(("info", "🧪 Regression started: local"))
    turn(bot)
    data = processes.load(feat)
    data["open"]["last"] = int(time.time()) - 3 * 24 * 3600
    processes.save(feat, data)
    real_send = bot.send
    bot.send = lambda *a, **k: setattr(bot, "last_error", "timed out") or 0
    processes.sweep(bot, feat, is_alive=lambda pid: False)
    check_true("a first refusal after days off keeps the process", processes.load(feat).get("open", {}).get("refused"))
    data = processes.load(feat)
    data["open"]["refused"] -= processes.GIVE_UP + 1
    processes.save(feat, data)
    processes.sweep(bot, feat, is_alive=lambda pid: False)
    check("a day of refusals gives it up", "open" in processes.load(feat), False)
    rec = {"lines": [["info", "1", "🧪 x started", 1]], "refused": 5}
    processes.add(rec, [("info", "1", "part 1 passed", int(time.time()))])
    check("a line again clears an earlier refusal", "refused" in rec, False)
    bot.send = real_send
    processes.sweep(bot, feat, is_alive=lambda pid: False)

    # A long run's lines keep the latest within the state.
    rec = {"since": 1, "lines": [["info", me, "🧪 x started", 1]]
           + [["info", me, "line %d " % i + "я" * 40, 1] for i in range(60)]}
    view = json.loads(processes.view(rec))
    check_true("a long run keeps its latest lines", view["l"].endswith("я") and "line 59" in view["l"])

    # --- the menu as a widget ----------------------------------------------
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        check_true("the menu widget is within Telegram's limits (%s)" % lang,
                   widgets.fits(widgets.code("menu", menu_widget.LABELS)))
    if shutil.which("node"):
        path = os.path.join(_TMP, "menu.js")
        with open(path, "w") as fh:
            fh.write(widgets.code("menu", menu_widget.LABELS).split("<script>")[1].split("</script>")[0])
        check("the menu widget's script parses",
              subprocess.run(["node", "--check", path], capture_output=True).returncode, 0)
    i18n.set_lang("en")
    saved_repos = repos.known_repos
    repos.known_repos = lambda: []
    try:
        bot = Bot()
        bot.token = "1:test"
        handling.Handler(bot).cmd_menu()
        check("/menu in the main chat is a widget", (len(bot.widgets), bot.sent), (1, []))
        shown = json.loads(bot.widgets[0][1])
        check_true("drawn from the menu's own screen",
                   any(i18n.t("menu.extend") in label for row in shown["r"] for label in row
                       if isinstance(label, str)))
        at = next("%d.%d" % (i, j) for i, row in enumerate(menu_widget.record()["actions"])
                  for j, a in enumerate(row) if a == "menu_extend")
        handling.Handler(bot).widget_query({"id": "m1", "data": "m:%d:%s" % (menu_widget.record()["n"], at), "message_id": 800})
        check("a tap is answered at once", bot.widget_answers[-1], ("m1", None))
        screen = bot.data[-1][1]
        check_true("and the next screen comes as the widget's state",
                   bot.data[-1][0] == 800 and screen["t"] and screen["r"])
        # A screen too large keeps its way back and fits the state.
        rows = [["Issue #%d — %s" % (i, "я" * 15)] for i in range(30)] + [["‹ Back"]]
        acts = [["nfi:%d" % i] for i in range(30)] + [["menu_back"]]
        data, kept_acts = menu_widget.fit("<b>New feature</b>\n" + "line\n" * 200, rows, acts)
        check_true("a large screen fits the state", len(widgets.state(dict(data, n=999)).encode()) <= widgets.DATA_MAX)
        check("and keeps its way back", (data["r"][-1], kept_acts[-1]), (["‹ Back"], ["menu_back"]))
        check_true("its text is cut by whole lines", "New feature" in data["t"] and "<b" not in data["t"])
        huge, _a = menu_widget.fit("x", [["я" * 600, "ю" * 600]], [["a", "b"]])
        check_true("one huge row still fits", len(widgets.state(huge).encode()) <= widgets.DATA_MAX)
        # The same screen again is still heard: the counter differs.
        before = bot.data[-1][1]["n"]
        handling.Handler(bot).widget_query({"id": "m4", "data": "m:%d:%s" % (before, at), "message_id": 800})
        check("a press that redraws the same screen still changes the state", bot.data[-1][1]["n"], before + 1)
        handling.Handler(bot).widget_query({"id": "m2", "data": "m:1:0.0", "message_id": 799})
        check("a tap on an older menu is out of date", bot.widget_answers[-1], ("m2", widgets.STALE))
        # A tap made on an earlier screen is answered with the current one.
        stale_n = before
        handling.Handler(bot).widget_query({"id": "m5", "data": "m:%d:0.0" % stale_n, "message_id": 800})
        check("a tap on an earlier screen is answered with the current one",
              bot.widget_answers[-1][1]["n"], before + 1)
        handling.Handler(bot).widget_query({"id": "m3", "data": "m:%d:99.0" % (before + 1), "message_id": 800})
        check("a tap off the screen answers with the screen as it is",
              bot.widget_answers[-1][1]["n"], bot.data[-1][1]["n"])
        handling.Handler(bot).cmd_menu()
        check("a new menu takes the last one away", bot.deletes[-1:], [800])
    finally:
        repos.known_repos = saved_repos

    # --- the feature's card as a widget ------------------------------------
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        check_true("the card widget is within Telegram's limits (%s)" % lang,
                   widgets.fits(widgets.code("card", card_view.CARD_LABELS)))
    if shutil.which("node"):
        path = os.path.join(_TMP, "card.js")
        with open(path, "w") as fh:
            fh.write(widgets.code("card", card_view.CARD_LABELS).split("<script>")[1].split("</script>")[0])
        check("the card widget's script parses",
              subprocess.run(["node", "--check", path], capture_output=True).returncode, 0)
    i18n.set_lang("en")
    saved = (repos.repo_path, repos.features_of_name, sessions.feature_state, sessions.feature_session,
             sessions.session_state, topics.load_record, topics.save_record, card_view.card)
    records = {"thread": 901}
    try:
        repos.repo_path = lambda name: "/nowhere/shop"
        repos.features_of_name = lambda name: ([("alpha", "2/7 development", "/nowhere/shop-alpha")], None)
        sessions.feature_state = lambda repo, slug: {"step": "code"}
        sessions.feature_session = lambda repo, slug: ("s1", "code")
        sessions.session_state = lambda session, cache=None: "working"
        topics.load_record = lambda repo, slug: dict(records)
        topics.save_record = lambda repo, slug, rec: records.update(rec)
        drawn = []
        card_view.card = lambda name, slug, note="", in_topic=True, feats=None, config=None, slim=False: (
            drawn.append(slim) or ("<b>shop</b> / <b>alpha</b>" + ("\n\n" + note if note else ""),
                                   [[{"text": "▶️", "callback_data": "fc:go:k"}]]))
        state_now = json.loads(card_view.card_state("shop", "alpha", state="working"))
        check("the card shows where the feature stands", (state_now["c"], state_now["n"]), (1, "2/7 development"))
        for label, place in (("4/7 done, waiting for merge", 4), ("6/7 epilogue", 5), ("all done", 7),
                             ("steps done, shipping to production", 5)):
            repos.features_of_name = lambda name, label=label: ([("alpha", label, "/w")], None)
            check("the place of %r" % label, json.loads(card_view.card_state("shop", "alpha"))["c"], place)
        repos.features_of_name = lambda name: ([("alpha", "2/7 development", "/nowhere/shop-alpha")], None)
        check_true("and what its session does", "running" in state_now["w"])
        bot = Bot()
        msg = card_view.post_card(bot, "shop", "alpha")
        check("the topic's card is a widget", (msg, len(bot.widgets), bot.sent), (800, 1, []))
        check("its words are the slim caption", (drawn[-1], records.get("card_widget")), (True, True))
        # What the card recorded drawing its words is what the widget shows.
        records["card_state"] = "waiting"
        card_view.redraw(bot, 800, "shop", "alpha", note="how the press ended")
        check_true("a redraw changes its state", "waiting" in bot.data[-1][1]["w"])
        check_true("and its caption keeps the press's note", bot.captions[-1][1].endswith("how the press ended"))
        card_view.redraw(bot, 800, "shop", "alpha", note="😀" * 900)
        check_true("a caption never outgrows Telegram's 1024", asks.visible_length(bot.captions[-1][1]) <= 1024)
        with state.locked() as st:
            st["widgets"] = False
        bot = Bot()
        card_view.post_card(bot, "shop", "alpha")
        check("with messages only, the card is a message", (len(bot.sent), bot.widgets, records["card_widget"]),
              (1, [], False))
        with state.locked() as st:
            st["widgets"] = True
    finally:
        (repos.repo_path, repos.features_of_name, sessions.feature_state, sessions.feature_session,
         sessions.session_state, topics.load_record, topics.save_record, card_view.card) = saved

    # The daemon asks Telegram for the widgets' queries.
    check_true("the daemon reads widget queries", "widget_query" in telegramd.UPDATES)
finally:
    shutil.rmtree(_TMP, ignore_errors=True)

if failures:
    print("FAILED: %d" % len(failures))
    for name, want, got in failures:
        print("  %s\n    expected: %r\n    got:      %r" % (name, want, got))
    sys.exit(1)

print("widgets: all checks passed")
