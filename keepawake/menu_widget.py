# keepawake's Telegram bot — the menu as a widget in the main chat
# (widget_html/menu.html).
#
# The Mini App (webmenu.py) is the full menu, but it opens only while phone
# access is on. The widget needs no network: a tap is a request to the bot,
# which runs it through webmenu.answer — the Mini App's own screens, so the
# two never disagree about what a button does — and answers with the next
# screen. What a widget cannot do stays with the app: its own buttons
# (web_app) are left out, and a screen that wants typing says to use the app
# or the chat.
#
# Part of the bot that keepawake/telegramd.py runs.

import html
import json
import logging
import re
import time

from keepawake import status_report, widgets
from keepawake.i18n import current, t
from keepawake.state import locked, read


log = logging.getLogger("keepawake")

LABELS = {"o": "msg.stale", "busy": "widget.busy", "fail": "widget.failed"}
# A label's bytes: the screen must fit the state's 1024 bytes with its text
# (fit).
LABEL_MAX = 40


def record():
    """The menu widget the main chat holds: its message, the actions of its
    buttons by row and place, and the context and feature the screen stands
    on — what webmenu.answer needs for the next tap."""
    return read().get("menu_widget") or {}


def remember(rec):
    with locked() as st:
        st["menu_widget"] = rec


def screen(answer):
    """(state, actions) of a screen webmenu.answer gave."""
    from keepawake import asks
    rows, actions = [], []
    for row in answer.get("rows") or []:
        labels, acts = [], []
        for b in row:
            label = asks.clip_bytes(status_report.strip_ansi(b.get("text") or ""), LABEL_MAX)
            if b.get("callback_data"):
                labels.append(label)
                acts.append(b["callback_data"])
            elif (b.get("url") or "").startswith("https://"):
                labels.append([label, b["url"]])
                acts.append("")
            else:
                continue
        if labels:
            rows.append(labels)
            actions.append(acts)
    text = answer.get("text") or ""
    for note in answer.get("notes") or []:
        text += "\n\n<i>%s</i>" % note
    if answer.get("time") or answer.get("input"):
        text += "\n\n<i>%s</i>" % t("widget.typing")
    return fit(text, rows, actions)


def size(obj):
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def fit(text, rows, actions):
    """(state, actions) within the state's 1024 bytes, room left for the
    press counter. Rows go from the bottom, above the last one — the way
    back, which always stays — then labels shorten; then the text loses whole
    lines from its end, and a text that had to be cut loses its markup too,
    since an element across lines would be left open."""
    rows, actions = [list(r) for r in rows], [list(a) for a in actions]
    room = widgets.DATA_MAX - 24
    while len(rows) > 1 and size({"t": "", "r": rows}) > room - 120:
        rows.pop(-2)
        actions.pop(-2)
        text = text if text.endswith(MORE) else text + MORE
    for limit in (24, 12):
        if size({"t": "", "r": rows}) <= room - 60:
            break
        rows = [[short(b, limit) for b in row] for row in rows]
    if size({"t": "", "r": rows}) > room - 60:
        rows, actions = [rows[-1][:1]], [actions[-1][:1]]
    if size({"t": "", "r": rows}) > room - 60:
        # Even that one (a link too long): no buttons, the app has them.
        rows, actions = [], []
    if size({"t": text, "r": rows}) > room:
        plain = html.unescape(re.sub(r"<[^>]+>", "", text))
        lines = plain.split("\n")
        while len(lines) > 1 and size({"t": html.escape("\n".join(lines + ["…"])), "r": rows}) > room:
            lines.pop()
        text = html.escape("\n".join(lines + ["…"]))
        plain = html.unescape(text)
        while size({"t": text, "r": rows}) > room and len(plain) > 1:
            # One line still too long: cut by characters, never in an entity,
            # and said to be cut.
            plain = plain[:-max(2, (size({"t": text, "r": rows}) - room) // 2)].rstrip("…")
            text = html.escape(plain) + "…"
    return {"t": text, "r": rows}, actions


def short(button, limit):
    from keepawake import asks
    if isinstance(button, list):
        return [asks.clip_bytes(button[0], limit), button[1]]
    return asks.clip_bytes(button, limit)


# Said under a screen whose buttons did not all fit.
MORE = "\n\n<i>…</i>"


def stamped(rec, screen_obj, **extra):
    """The state to send: the screen with the press counter, which differs
    from every earlier state, so the widget always hears it and stops
    waiting."""
    return widgets.state(dict(screen_obj, n=(rec.get("n") or 0) + 1, **extra))


def run(bot, user, action, rec, now):
    # Untraced: the widget shows what a press did; a "📱" line in the chat
    # under it would say the app did it, and push the menu up.
    from keepawake import webmenu
    return webmenu.answer(bot.token, bot.chat_id, user, action, rec.get("ctx") or "", now,
                          home=rec.get("home") or "", traced=False, chat_bot=bot)


def open_menu(bot, now=None):
    """The menu sent to the main chat as a widget, replacing the last one."""
    from keepawake import menus
    now = now or int(time.time())
    # The person's language, as the chat knows it: the press that asked for
    # the menu has set it already.
    answer = run(bot, {"language_code": current()}, "menu_back", {}, now)
    screen_obj, actions = screen(answer)
    data = stamped({}, screen_obj)
    # The caption names it for the chat list; the screen's own title is in
    # the widget, and a second copy would stand under it.
    msg = bot.send_widget(widgets.code("menu", LABELS), data, t("menu.button"), thread=0)
    if not msg:
        return 0
    old = record().get("msg")
    remember({"msg": msg, "actions": actions, "ctx": answer.get("context") or "",
              "home": answer.get("home") or "", "state": data, "n": 1})
    if old:
        menus.retire(bot, old)
    return msg


def press(bot, wq, now):
    """A tap in the menu widget, m:<counter>:<row>.<place>: (state to answer
    with, what to do after the answer). A press may take longer than the 15
    seconds a query is answered in (a session started, a setting written,
    issues fetched): the query is answered at once, and the press runs right
    after, in the loop as every press in the chat does, its screen sent as
    the widget's state. The rare long press (code-server, a session started,
    issues fetched) holds the loop for those seconds: decided so on
    2026-11-11 — a thread of its own raced the loop for the record, the
    language and the page flag. A tap on a screen that is no longer the widget's —
    the counter says which it drew — is answered with the current one."""
    rec = record()
    message_id = wq.get("message_id") or 0
    if not message_id or rec.get("msg") != message_id:
        return widgets.state(widgets.STALE), None
    try:
        seen, at = (wq.get("data") or "")[2:].split(":", 1)
        row, place = (int(x) for x in at.split("."))
        if int(seen) != (rec.get("n") or 0):
            return current_state(rec), None
        action = rec["actions"][row][place]
    except (ValueError, IndexError, KeyError):
        return current_state(rec), None
    if not action:
        return current_state(rec), None
    user = wq.get("from")

    def work():
        try:
            answer = run(bot, user, action, rec, now)
            if answer.get("text") is None:
                # Nothing changed on the screen: the same screen again,
                # which the widget hears and stops waiting.
                screen_obj, actions = json.loads(current_state(rec)), rec.get("actions") or []
                screen_obj.pop("n", None)
                screen_obj.pop("x", None)
            else:
                screen_obj, actions = screen(answer)
            data = stamped(rec, screen_obj)
        except Exception as exc:
            # Whatever failed, the widget hears it: the screen it had, marked.
            log.exception("the menu widget's press %s: %s", action, exc)
            answer, actions = {}, rec.get("actions") or []
            screen_obj = json.loads(current_state(rec))
            screen_obj.pop("n", None)
            screen_obj.pop("x", None)
            data = stamped(rec, dict(screen_obj, x=1))
        # Kept whether or not the edit was answered: one that timed out may
        # have been applied, and a tap on the screen it left — the counter
        # says which — is answered with this one rather than run against it.
        # Not applied, the widget gives up waiting itself.
        bot.widget_data(message_id, data)
        new = dict(rec, actions=actions, state=data, n=json.loads(data)["n"])
        if answer.get("context") is not None:
            new["ctx"] = answer["context"]
        if answer.get("home") is not None:
            new["home"] = answer["home"]
        remember(new)
        log.info("the menu widget: %s", action)
    return None, work


def current_state(rec):
    return rec.get("state") or widgets.state({"t": "", "r": []})
