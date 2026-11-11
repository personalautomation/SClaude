# keepawake's Telegram bot — HTML widgets (Bot API 10.4): the code they are
# sent with, the state they are drawn from, and the switch between them and
# the plain messages they replace.
#
# A widget is fixed code plus a state of at most 1024 bytes that only the bot
# changes (editMessageWidgetData). So the code is generic and everything it
# shows comes from the state; the words it needs in the person's language go
# into the code when it is sent (the /*L*/ marker), since a new layout means a
# new message anyway.
#
# Part of the bot that keepawake/telegramd.py runs.

import json
import os
import zlib

from keepawake.i18n import t
from keepawake.state import read


HTML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widget_html")

# Telegram's limits: the code in UTF-8, the same code after zlib at level 9
# (counted as the server counts it), and each state.
CODE_MAX = 32768
PACKED_MAX = 4096
DATA_MAX = 1024

# Where the labels go in a template.
LABELS = "/*L*/{}"

# The state every widget draws as "out of date", buttons gone: what a message
# that can no longer be deleted is turned into (menus.retire), and the answer
# to a press the bot no longer has a place for.
STALE = {"s": "o"}


def enabled():
    """Whether active things go to the chat as widgets: the settings' switch,
    on unless turned off. The old path stays while moving over, frozen."""
    return read().get("widgets", True) is not False


def code(name, labels):
    """The widget's HTML: the template with its labels, {key: i18n key}, in
    the language of this moment."""
    with open(os.path.join(HTML_DIR, name + ".html"), encoding="utf-8") as fh:
        src = fh.read()
    words = json.dumps({k: t(v) for k, v in labels.items()}, ensure_ascii=False)
    # "</script>" inside a label would end the script early.
    return src.replace(LABELS, words.replace("</", "<\\/"), 1)


def fits(html):
    """Whether Telegram takes this code."""
    raw = html.encode("utf-8")
    return len(raw) <= CODE_MAX and len(zlib.compress(raw, 9)) <= PACKED_MAX


def state(obj, trim=None, tail=False):
    """The state as the text Telegram keeps, within its 1024 bytes: the field
    named by trim is cut short as far as needed (with an ellipsis) — its
    start rather than its end with tail, for lines whose latest matter; with
    nothing to cut, a state too large is refused here rather than by
    Telegram."""
    obj = dict(obj)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > DATA_MAX and obj.get(trim):
        long = obj[trim]
        # What the rest takes, the field emptied; the field gets what is left,
        # counted in its JSON form (escapes count) and whole characters.
        obj[trim] = ""
        room = DATA_MAX - len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) - 3
        kept, used = [], 0
        for ch in (reversed(long) if tail else long):
            size = len(json.dumps(ch, ensure_ascii=False).encode("utf-8")) - 2
            if used + size > room:
                break
            kept.append(ch)
            used += size
        cut = "".join(reversed(kept) if tail else kept)
        obj[trim] = ("…" + cut.lstrip()) if tail else (cut.rstrip() + "…")
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > DATA_MAX:
        raise ValueError("a widget state over %d bytes: %s" % (DATA_MAX, text[:80]))
    return text
