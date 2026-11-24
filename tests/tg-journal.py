#!/usr/bin/env python3
#
# keepawake's journal of a feature's topic (keepawake/tg_journal.py): every
# call the bot makes about the topic, and every update from it, is one line
# in the feature's directory — what was said and done, with none of how
# sclaude talks to Telegram.
#
# Run it with: python3 tests/tg-journal.py
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_TMP = tempfile.mkdtemp(prefix="tg-journal-test-")
os.environ["KEEPAWAKE_STATE"] = os.path.join(_TMP, "state.json")
os.environ["KEEPAWAKE_LOCK"] = os.path.join(_TMP, ".lock")
os.environ["KEEPAWAKE_TOPICS"] = os.path.join(_TMP, "topics")

from keepawake import botapi, tg_journal, topics  # noqa: E402

failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s: got %r, want %r" % (name, got, want))


FEATURE = os.path.join(_TMP, "wt", ".sclaude", "local", "feature")
os.makedirs(FEATURE)
JOURNAL = os.path.join(FEATURE, tg_journal.FILE)
# Topic 7 is the feature's; any other topic is nobody's.
tg_journal.feature_of = lambda thread: FEATURE if thread == 7 else ""


def lines():
    if not os.path.exists(JOURNAL):
        return []
    with open(JOURNAL) as fh:
        return [json.loads(l) for l in fh]


def drop_at(entries):
    return [{k: v for k, v in e.items() if k != "at"} for e in entries]


# --- what a line keeps, and what it leaves out ---------------------------------
check("a secret field is dropped, a token in a string hidden",
      tg_journal.clean({"chat_data": {"state": "on", "auth_key": "x", "nested": {"hash": "y", "n": 1}},
                        "why": "POST https://api.telegram.org/bot123456789:%s/sendMessage" % ("A" * 35)}),
      {"chat_data": {"state": "on", "nested": {"n": 1}},
       "why": "POST https://api.telegram.org/bot<token>/sendMessage"})
check("a widget keeps its data and its size, not its code",
      tg_journal.outgoing("sendWidget", {"chat_id": 1, "html": "<p>x</p>", "chat_data": '{"on": true, "token": "s"}',
                                        "caption": "Hold", "message_thread_id": 7},
                          {"ok": True, "result": {"message_id": 9}}),
      {"dir": "out", "method": "sendWidget", "thread": 7, "sent": 9, "caption": "Hold",
       "data": {"on": True}, "html_chars": 8, "ok": True})
check("buttons are kept by their labels",
      tg_journal.buttons('{"inline_keyboard": [[{"text": "Yes", "callback_data": "a:1"}, {"text": "No"}]]}'),
      [["Yes", "No"]])

# --- the bot's calls, through Bot.call -------------------------------------------
_calls = []
_refuse = set()


class _Reply(object):
    def __init__(self, body):
        self.body = body

    def read(self, *a):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(req, timeout=None):
    import urllib.parse as parse
    method = req.full_url.rsplit("/", 1)[1]
    _calls.append((method, dict(parse.parse_qsl(req.data.decode()))))
    if method in _refuse:
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"description": "message to edit not found"}'))
    return _Reply(json.dumps({"ok": True, "result": {"message_id": 40 + len(_calls)}}).encode())


saved = urllib.request.urlopen
urllib.request.urlopen = fake_urlopen
try:
    bot = botapi.Bot("123456789:%s" % ("B" * 35), 1)
    first = bot.send("Review round 1 closed", keyboard=[[{"text": "Go on", "callback_data": "g"}]], thread=7)
    bot.send("in the main chat", thread=0)
    bot.send("another feature's", thread=8)
    bot.edit(first, "Review round 1 closed — 3 found")
    _refuse.add("deleteMessage")
    try:
        bot.call("deleteMessage", chat_id=1, message_id=first)
    except urllib.error.HTTPError:
        pass
    got = drop_at(lines())
    check("only the feature's topic is journalled, an edit and a refusal by the message they name",
          [(e["method"], e.get("thread"), e.get("sent"), e.get("message"), e.get("ok")) for e in got],
          [("sendMessage", 7, first, None, True), ("editMessageText", None, None, first, True),
           ("deleteMessage", None, None, first, False)])
    check("the send keeps its text and buttons", (got[0]["text"], got[0]["buttons"]),
          ("Review round 1 closed", [["Go on"]]))
    check("the refusal keeps what Telegram said", "message to edit not found" in got[-1]["error"], True)
    check("no token, chat id or address in the journal",
          [w for w in ("B" * 35, "chat_id", "api.telegram") if w in open(JOURNAL).read()], [])
finally:
    urllib.request.urlopen = saved

# --- the same message twice is not sent twice (Bot.send, edit, caption) ------------
urllib.request.urlopen = fake_urlopen
_refuse.clear()
try:
    bot = botapi.Bot("123456789:%s" % ("B" * 35), 1)
    _calls[:] = []
    one = bot.send("🧪 Regression started: local, 1m 05s", thread=7)
    again = bot.send("🧪 Regression started: local, 2m 10s", thread=7)
    check("a plain message to a topic repeated, its times aside, is not sent again",
          (again, [m for m, _p in _calls]), (one, ["sendMessage"]))
    bot.send("🧪 Regression started: local", thread=8)
    check("another topic is another conversation", len(_calls), 2)
    keys = [[{"text": "Stop", "callback_data": "s"}]]
    bot.send("🧪 Regression started: local, 1m 05s", keyboard=keys, thread=7)
    bot.send("🧪 Regression started: local, 1m 05s", keyboard=keys, thread=7)
    check("a message with buttons always goes", len(_calls), 4)
    bot.send("ok")
    bot.send("ok")
    check("and so does a reply to the person, the topic not named", len(_calls), 6)
    bot.send("finished", thread=7)
    bot.send("started", thread=7)
    bot.send("finished", thread=7)
    check("a repeat after something else is new again", len(_calls), 9)
    last = bot.send("done", thread=7)
    bot.delete(last)
    bot.send("done", thread=7)
    check("and after the last one was deleted", [m for m, _p in _calls[-3:]],
          ["sendMessage", "deleteMessage", "sendMessage"])
    _calls[:] = []
    bot.send("waiting for checks", thread=9, quiet=True)
    bot.send("waiting for checks", thread=9, quiet=True)
    check("equal and as quiet within the window is skipped", len(_calls), 1)
    bot.send("waiting for checks", thread=9)
    check("equal text but louder is sent", len(_calls), 2)
    bot.said[9] = bot.said[9][:3] + (time.time() - botapi.SAID_WINDOW - 1,)
    bot.send("waiting for checks", thread=9)
    check("equal after the window is sent", len(_calls), 3)

    _calls[:] = []
    check("an edit goes", bot.edit(70, "card", keys), True)
    check("the same edit again is done without Telegram", (bot.edit(70, "card", keys), len(_calls)), (True, 1))
    bot.edit(70, "card", [[{"text": "Go", "callback_data": "g"}]])
    check("new buttons are an edit", len(_calls), 2)
    bot.caption(71, "caption")
    bot.caption(71, "caption")
    bot.widget_data(71, '{"w": 1}')
    bot.widget_data(71, '{"w": 1}')
    bot.widget_data(71, '{"w": 2}')
    check("a caption and a widget's state likewise",
          [m for m, _p in _calls[2:]], ["editMessageCaption", "editMessageWidgetData", "editMessageWidgetData"])
    bot.shown[70] = bot.shown[70][:2] + (0,)
    bot.edit(70, "card", [[{"text": "Go", "callback_data": "g"}]])
    check("an old memory is not trusted: another process may have edited since", len(_calls), 6)
finally:
    urllib.request.urlopen = saved

# --- updates from the topic ------------------------------------------------------
os.remove(JOURNAL)
tg_journal.bot_update({"message": {"message_id": 50, "text": "stop", "message_thread_id": 7}}, 7)
tg_journal.bot_update({"callback_query": {"id": "q1", "data": "ask:1:y", "message": {"message_id": 51}}}, 7)
tg_journal.bot_update({"message": {"message_id": 52, "text": "elsewhere"}}, 8)
topics.remember_in_topic(7, 60)
tg_journal.bot_update({"widget_query": {"id": "w1", "message_id": 60, "data": '{"press": "hold", "init_data": "z"}'}})
check("what the person typed, pressed and tapped in the topic",
      drop_at(lines()),
      [{"dir": "in", "kind": "message", "thread": 7, "message": 50, "text": "stop"},
       {"dir": "in", "kind": "callback_query", "thread": 7, "message": 51, "data": "ask:1:y"},
       {"dir": "in", "kind": "widget_query", "thread": 7, "message": 60, "data": {"press": "hold"}}])
check("an answer to a query lands with the feature it came from",
      tg_journal.call_feature("answerWidgetQuery", {"widget_query_id": "w1"}), FEATURE)
check("the poll itself is about no topic", tg_journal.call_feature("getUpdates", {}), "")

# --- the journal never stands in the way -----------------------------------------
tg_journal.note(os.path.join(_TMP, "gone"), {"dir": "out"})
check("no feature directory, no file and no error", os.path.exists(os.path.join(_TMP, "gone")), False)

if failed:
    print("%d check(s) failed" % failed)
    sys.exit(1)
print("All checks passed.")
