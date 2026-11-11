# keepawake's Telegram bot — a process sclaude runs, as a widget in its
# feature's topic (widget_html/proc.html).
#
# The feed (notices.py) sends what sclaude prints about a feature as one
# message a turn. A regression, a review pass or a session runs for minutes
# to hours, and its lines then pile up below its start. With widgets on, the
# line that starts one ("🧪 Regression started: …") opens a widget instead:
# its caption is that line, and it counts the time itself and shows the
# latest lines, which go into it — a silent edit — rather than below it. The
# line that ends it (a "✅", or a phase line of the same kind that does not
# start one: "finished", "failed"), or the start of the next one, takes the
# widget away and leaves one message with the whole account — the topic's
# history. The caption stands above the widget: what runs is read first. A
# warning while it runs needs the person: the widget is sent again,
# with sound, the old one deleted.
#
# A module of its own, handed to notices.check (procs), as review_keys is.

import json
import os
import time

from keepawake import notices, widgets


# The open process of a channel, in its notes/: one at a time, since a phase
# line opening the next one ends the last.
PROC_FILE = "process.json"
# How many of its lines the record keeps for the closing account; the rest
# are counted, as the feed counts them.
KEEP_LINES = 60
LABELS = {"o": "msg.stale"}
# How long a process whose printing processes are all gone stays open without
# a line: the one that prints a start is not always the one that runs it — a
# short command starts a regression and exits, and its lines come from others.
QUIET_END = 3600
# How long an end the network keeps refusing is tried, from its first refusal,
# before it is given up unsent: the feed's hour when its topic is gone, a day
# otherwise (a blocked bot, a chat gone).
GIVE_UP = 24 * 3600


def _path(channel):
    return os.path.join(channel, notices.NOTES_DIR, PROC_FILE)


def load(channel):
    """The channel's record: {"open": the running process, "gone": widgets
    not taken away yet}."""
    try:
        with open(_path(channel), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(channel, data):
    path = _path(channel)
    if not (data.get("open") or data.get("gone")):
        try:
            os.remove(path)
        except OSError:
            pass
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".new", "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(path + ".new", path)
    except OSError:
        pass


def phase(line):
    """The icon a phase line opens with, "" for any other line."""
    m = notices.OWN_ICON.match(notices.ANSI.sub("", line[2] or "").strip())
    return m.group(0).strip() if m else ""


def opening(group):
    """(index, icon) of the line that starts a process in the group, (-1, "")
    when none does. Not always the first: a warning printed while the next
    step is set up goes with the start it leads to (feed_groups)."""
    for i, line in enumerate(group):
        icon = phase(line)
        if icon and notices.OPENS.search(notices.ANSI.sub("", line[2] or "")):
            return i, icon
    return -1, ""


def ending(lines, icon):
    """Whether these lines end the process of icon."""
    for line in lines:
        text = notices.ANSI.sub("", line[2] or "").strip()
        if text.startswith(notices.CLOSES) or (phase(line) == icon and not notices.OPENS.search(text)):
            return True
    return False


def kept(line):
    """Whether the feed shows a line: headlines and warnings, not the indented
    detail under them. The record keeps only these, so what it counts as cut
    is what the account would have shown."""
    level, text = line[0], notices.ANSI.sub("", line[2] or "")
    return bool(text.strip()) and not (text[:1].isspace() and level not in notices.FEED_SOUND)


def shown(line):
    text = notices.ANSI.sub("", line[2] or "").strip()
    return ("⚠️ " if line[0] in notices.FEED_LOUD else "") + text


def body(lines):
    """The lines under the caption, without the first, the caption."""
    return "\n".join(shown(x) for x in lines[1:])


def view(rec):
    return widgets.state({"b": rec["since"], "l": body(rec["lines"])}, trim="l", tail=True)


def caption(line):
    return notices.clip(notices.ANSI.sub("", line[2] or "").strip(), 1000)


def add(rec, lines):
    """Lines into the record: the start stays first, the latest are kept, and
    what goes between them is counted."""
    # Who printed and when counts every line, the detail too: a run that
    # prints only detail is still running.
    rec["pids"] = sorted(set(rec.get("pids") or []) | {x[1] for x in lines})
    rec["last"] = max([rec.get("last") or 0] + [int(x[3]) for x in lines])
    # Printing again, it is not orphaned: a refusal counted before is over.
    rec.pop("refused", None)
    lines = rec["lines"] + [list(x) for x in lines if kept(x)]
    rec["cut"] = rec.get("cut", 0) + max(0, len(lines) - KEEP_LINES)
    rec["lines"] = lines[:1] + lines[1:][-(KEEP_LINES - 1):]


def account(rec):
    """The closing message: the start, then the latest lines — the result is
    the last of them — with how many between were left out. Built from the
    end, so the result is never what does not fit."""
    head, tail = rec["lines"][:1], rec["lines"][1:]
    budget = notices.NOTE_MAX - 80
    first = notices.clip(shown(head[0]), budget // 4) if head else ""
    budget -= len(first) + 1
    latest = []
    for line in reversed(tail[-(notices.FEED_MAX_LINES - 1):]):
        piece = notices.clip(shown(line), budget)
        if not piece:
            break
        latest.insert(0, piece)
        budget -= len(piece) + 1
    left = rec.get("cut", 0) + len(tail) - len(latest)
    return "\n".join([first] + (["<i>… %d more</i>" % left] if left else []) + latest)


def ended(bot, data, loud=False):
    """The open process is over: its account sent now, before anything that
    follows it, and its widget left for flush to take away. Whether the
    account went; not sent, nothing is changed — the caller returns 0, the
    group goes back, and a lost topic is made again."""
    rec = data["open"]
    if not bot.send(account(rec), quiet=not loud, thread=rec.get("thread") or 0):
        return False
    data.pop("open")
    data.setdefault("gone", []).append(rec["msg"])
    return True


def flush(bot, data):
    """Widgets an end or a resend left: away — deleted, or past Telegram's 48
    hours drawn out of date — and tried again every turn until they are."""
    from keepawake import menus
    data["gone"] = [msg for msg in data.get("gone") or [] if not menus.retire(bot, msg)]


def widget(bot, rec, keyboard, loud):
    return bot.send_widget(widgets.code("proc", LABELS), view(rec), rec["caption"],
                           keyboard=keyboard, quiet=not loud, thread=rec.get("thread") or 0,
                           above=True)


def take(bot, channel, group, thread, loud, keyboard, keys=None, context=""):
    """A group of feed lines, sent its way. Returns the id of the message
    that carries it; 0 when the network kept it — nothing is changed on disk
    then, and notices puts the whole group back; or None for notices to send
    the group as a plain message, as without widgets. keys: the review's
    buttons (review_keys), moved to a widget sent again. context: what an open
    question shows, which a message made here leaves out, as notices does."""
    data = load(channel)
    rec = data.get("open")
    if rec:
        # The topic now: one made again after the person deleted it.
        rec["thread"] = thread
    start, icon = opening(group)
    result = None
    if rec and start < 0:
        add(rec, group)
        if ending(group, rec["icon"]):
            if not ended(bot, data, loud):
                return 0
            result = rec["msg"]
        elif loud or (not bot.widget_data(rec["msg"], view(rec))
                      and "not found" in (bot.last_error or "")):
            # A warning sounds: the widget is sent again. So is one deleted
            # by hand; an edit that failed otherwise is carried by the next.
            held = keys.load(channel) if keys else {}
            held = held if held.get("message_id") == rec["msg"] else {}
            msg = widget(bot, rec, keys.keyboard(held["kind"], held.get("said", ""))
                         if held else keyboard, loud)
            if not msg:
                return 0
            data.setdefault("gone", []).append(rec["msg"])
            rec["msg"] = result = msg
            if held:
                keys.save(channel, dict(held, message_id=msg))
        else:
            result = rec["msg"]
    elif start >= 0:
        # Before a start: a warning goes with the start it leads to
        # (feed_groups); any other line is the open process's last.
        lead = group[:start]
        if rec:
            add(rec, [x for x in lead if x[0] not in notices.FEED_LOUD])
            lead = [x for x in lead if x[0] in notices.FEED_LOUD]
            # Its account first, so the topic's history keeps the order.
            if not ended(bot, data):
                return 0
            save(channel, data)
        rest = lead + group[start:]
        # Switched off, no new process opens; one begun and ended in this
        # turn is a message — what is left of the group once the open process
        # took its part, sent here, after that part's account.
        if not widgets.enabled() or ending(group[start + 1:], icon):
            if not rec:
                return None
            text, _loud = notices.feed_message(rest, context)
            result = bot.send(text, keyboard=keyboard, quiet=not loud, thread=thread) if text else -1
        else:
            new = {"icon": icon, "lines": [list(group[start])], "since": int(group[start][3]),
                   "thread": thread, "caption": caption(group[start]), "pids": []}
            add(new, lead + group[start + 1:])
            msg = widget(bot, new, keyboard, loud)
            if msg:
                new["msg"] = msg
                data["open"] = new
            elif rec:
                # The old process's account went already: put back whole, its
                # lead lines would be sent twice. This start goes as a message.
                text, _loud = notices.feed_message(rest, context)
                msg = bot.send(text, keyboard=keyboard, quiet=not loud, thread=thread) if text else -1
            result = msg
        if not result and rec:
            # The account went and is saved; only what is left of the group
            # goes back to the feed, after anything printed since.
            notices.put_back(channel, rest)
            result = -1
        if not result:
            return 0
    flush(bot, data)
    save(channel, data)
    return result


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def sweep(bot, channel, is_alive=alive):
    """What an end left to do, tried again; and a process whose sclaude is
    gone without its closing line — killed, the machine restarted — ended,
    rather than count for ever: every process that printed for it gone, and
    no line for QUIET_END. notices runs it after the turn's lines were all
    sent, so a closing line printed just before sclaude exited is taken
    first."""
    data = load(channel)
    if not data:
        return
    rec = data.get("open")
    now = time.time()
    quiet = now - ((rec or {}).get("last") or (rec or {}).get("since") or 0)
    from keepawake import topics
    if rec and not any(is_alive(pid) for pid in rec.get("pids") or []) and quiet > QUIET_END \
            and not ended(bot, data):
        # Refused: counted from the first refusal, not from the last line —
        # a machine back after a day off tries before its network is up.
        since = rec.setdefault("refused", int(now))
        if (topics.topic_lost(bot) and now - since > notices.FEED_KEEP) or now - since > GIVE_UP:
            # Its account refused past its time: let go, unsent, the
            # widget with it.
            data.pop("open")
            data.setdefault("gone", []).append(rec["msg"])
    flush(bot, data)
    save(channel, data)
