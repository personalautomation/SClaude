# keepawake's Telegram bot — the journal of what went to a feature's topic
# and what came back from it.
#
# Telegram keeps no history the machine can read back, and neither did
# sclaude: a message's text was gone once sent, its edits and deletions left
# no trace, and a retrospective could not tell a message sent twice from one
# sent once. So every call the bot or bin/sclaude-notify makes about a
# feature's topic, and every update that comes from it, is one JSON line in
# the feature's own directory (FILE, `.sclaude/local/feature/telegram-log.jsonl`,
# beside its telegram.json): in the
# worktree, never in git (.sclaude/local is kept out of it), and gone with
# the worktree.
#
# What a line keeps is what the person saw and did — the text, the buttons'
# labels, a widget's data, the files' names, which message was edited or
# deleted, whether Telegram took it — and none of how sclaude talks to
# Telegram: no token, no address, no chat id, no key or signature a payload
# carries (clean), no widget's HTML, no file's bytes.
#
# The journal never stands in a send's way: whatever fails here is dropped.

import datetime
import json
import os
import re

FILE = "telegram-log.jsonl"

# A field by any of these names is left out of a widget's or a query's data,
# whatever it holds.
SECRET_FIELD = re.compile(r"token|secret|key|hash|sign|auth|init_?data|passw|cookie", re.I)
# A bot token written into any string — an error that names the address.
BOT_TOKEN = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")
# A text longer than Telegram takes is not a message; cut, it still says
# what it was.
TEXT_MAX = 4096

# Calls that are about no topic: asking them for one would only cost a look.
NOT_A_TOPIC = {"getUpdates", "getMe", "setMyCommands", "setMyDescription",
               "setMyShortDescription", "setChatMenuButton", "deleteWebhook"}

# The feature a query came from, by its id, for the answer that names only
# the id (answerCallbackQuery, answerWidgetQuery). Kept for the bot's life,
# and only the last few hundred.
_QUERIES = {}
QUERIES_KEPT = 300


def clean(value):
    """A value as it may be kept: no field named like a secret, no token in
    a string, a long string cut."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not SECRET_FIELD.search(str(k))}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, str):
        value = BOT_TOKEN.sub("<token>", value)
        return value if len(value) <= TEXT_MAX else value[:TEXT_MAX] + "…"
    return value


def _json(value):
    """A parameter that went as JSON text, back as what it says."""
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def buttons(markup):
    """The labels of a keyboard, row by row, or None."""
    markup = _json(markup)
    rows = markup.get("inline_keyboard") if isinstance(markup, dict) else None
    if not rows:
        return None
    return [[clean(b.get("text", "")) for b in row if isinstance(b, dict)] for row in rows]


def _sent_ids(out):
    res = (out or {}).get("result")
    ids = [m.get("message_id") for m in (res if isinstance(res, list) else [res])
           if isinstance(m, dict) and m.get("message_id")]
    return ids[0] if len(ids) == 1 else (ids or None)


def outgoing(method, params, out=None, error=None, files=None):
    """The line for one call to Telegram."""
    params = params or {}
    entry = {"dir": "out", "method": method}
    res = (out or {}).get("result")
    thread = params.get("message_thread_id") or (
        res.get("message_thread_id") if isinstance(res, dict) else None)
    if thread:
        entry["thread"] = int(thread)
    target = params.get("message_id") or _json(params.get("message_ids"))
    if target:
        entry["message"] = target
    sent = _sent_ids(out) if method.startswith("send") else None
    if sent:
        entry["sent"] = sent
    for field in ("text", "caption", "name"):
        if params.get(field):
            entry[field] = clean(str(params[field]))
    media = _json(params.get("media"))
    if isinstance(media, list) and not params.get("caption"):
        first = next((m.get("caption") for m in media if isinstance(m, dict) and m.get("caption")), None)
        if first:
            entry["caption"] = clean(first)
    keys = buttons(params.get("reply_markup"))
    if keys:
        entry["buttons"] = keys
    for field in ("chat_data", "data"):
        if params.get(field) is not None:
            entry["data"] = clean(_json(params[field]))
    if params.get("html"):
        # The widget's code is not what anybody saw; its size says it changed.
        entry["html_chars"] = len(params["html"])
    if params.get("disable_notification"):
        entry["quiet"] = True
    if files:
        entry["files"] = [os.path.basename(f) for f in files]
    if error is not None:
        entry["ok"] = False
        entry["error"] = clean(str(error))[:500]
    else:
        entry["ok"] = bool((out or {}).get("ok", True))
    return entry


def incoming(kind, obj, thread=0):
    """The line for one update from a feature's topic: a message typed, a
    button pressed, a widget's query."""
    obj = obj or {}
    entry = {"dir": "in", "kind": kind}
    if thread:
        entry["thread"] = int(thread)
    if kind == "message":
        entry["message"] = obj.get("message_id")
        entry["text"] = clean(obj.get("text") or obj.get("caption") or "")
        reply = (obj.get("reply_to_message") or {}).get("message_id")
        if reply:
            entry["reply_to"] = reply
    elif kind == "callback_query":
        entry["message"] = (obj.get("message") or {}).get("message_id")
        entry["data"] = clean(obj.get("data") or "")
    else:
        entry["message"] = obj.get("message_id")
        entry["data"] = clean(_json(obj.get("data") or ""))
    return {k: v for k, v in entry.items() if v not in (None, "")}


def note(feature_dir, entry):
    """One line into the feature's journal; nothing when there is no
    feature or the write fails."""
    if not feature_dir or not os.path.isdir(feature_dir) or not entry:
        return
    try:
        line = dict({"at": datetime.datetime.now(datetime.timezone.utc)
                     .isoformat(timespec="seconds")}, **entry)
        with open(os.path.join(feature_dir, FILE), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def ledger_thread(message_id):
    """The topic a message is in, from the bot's records of its topics
    (state.topic_ledger), or 0: an edit or a deletion names only the
    message."""
    if not message_id:
        return 0
    try:
        from keepawake.state import topic_ledger
        base = os.path.dirname(topic_ledger(0))
        want = "%d" % int(message_id)
        for name in os.listdir(base):
            if not name.isdigit():
                continue
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                if want in (line.strip() for line in fh):
                    return int(name)
    except (OSError, ValueError, TypeError, ImportError):
        pass
    return 0


def feature_of(thread):
    """The feature directory whose topic this is, or ""."""
    if not thread:
        return ""
    try:
        from keepawake import asks, repos, topics
        key = topics.topic_channel(int(thread))
        if not key:
            return ""
        name, slug = asks.split_key(key)
        repo = repos.repo_path(name)
        return topics.feature_dir(repo, slug) if repo and slug else ""
    except Exception:
        return ""


def remember_query(query_id, feature_dir):
    if query_id and feature_dir:
        _QUERIES[str(query_id)] = feature_dir
        while len(_QUERIES) > QUERIES_KEPT:
            _QUERIES.pop(next(iter(_QUERIES)))


def call_feature(method, params, out=None):
    """The feature a call to Telegram is about, or "": by its topic, by the
    message it edits or deletes, or by the query it answers."""
    if method in NOT_A_TOPIC:
        return ""
    params = params or {}
    for query in ("callback_query_id", "widget_query_id"):
        if params.get(query):
            return _QUERIES.get(str(params[query]), "")
    thread = params.get("message_thread_id")
    res = (out or {}).get("result")
    if not thread and isinstance(res, dict):
        thread = res.get("message_thread_id")
    if not thread:
        target = params.get("message_id") or _json(params.get("message_ids"))
        if isinstance(target, list):
            target = target[0] if target else 0
        thread = ledger_thread(target)
    return feature_of(thread)


def bot_call(method, params, out=None, error=None):
    """What the bot's every call writes (botapi.Bot.call)."""
    try:
        where = call_feature(method, params, out)
        if where:
            note(where, outgoing(method, params, out, error))
    except Exception:
        pass


def bot_update(upd, thread=0):
    """What the bot writes for an update it took from its chat
    (telegramd's loop)."""
    try:
        for kind in ("message", "callback_query", "widget_query"):
            if kind not in upd:
                continue
            obj = upd[kind] or {}
            if not thread and kind == "widget_query":
                thread = ledger_thread(obj.get("message_id"))
            where = feature_of(thread)
            if where:
                if kind != "message":
                    remember_query(obj.get("id"), where)
                note(where, incoming(kind, obj, thread))
    except Exception:
        pass
