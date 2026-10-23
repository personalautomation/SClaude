#!/usr/bin/env python3
#
# Messages from sclaude that ask nothing: where a feature's review stands
# after each round. sclaude lays each in notes/ of the feature's channel
# (ask_notice in sclaude/lib/io.sh); the bot sends them to the feature's
# topic in the order they came, each as a message of its own — the topic
# keeps them all, nothing is edited — and deletes the file once sent.
#
# A module of its own, with what it needs from the bot passed in: the bot's
# file is long, and edited by more than one line of work at a time.
import glob
import html
import os
import re
import time

NOTES_DIR = "notes"
# A note the bot could not send for this long is dropped: a status from a
# day ago says nothing true.
NOTE_KEEP = 24 * 3600
# Telegram's limit on a message, with room for the markup.
NOTE_MAX = 3800


def pending(channel):
    """The notes waiting in a channel, oldest first."""
    found = glob.glob(os.path.join(glob.escape(channel), NOTES_DIR, "*.txt"))
    return sorted(found, key=lambda path: (os.path.getmtime(path), path))


def clip(text, room):
    """text escaped for HTML, cut to room characters of the escaped form —
    never through an entity — with "…" where it was cut; "" when nothing
    fits."""
    out, used = [], 0
    for i, ch in enumerate(text):
        piece = html.escape(ch)
        if used + len(piece) > room - (1 if i < len(text) - 1 else 0):
            return "".join(out) + "…" if out else ""
        out.append(piece)
        used += len(piece)
    return "".join(out)


def text_of(path):
    """A note as a message: its first line in bold, as a title; "" for an
    empty one, which Telegram would refuse every turn."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        body = fh.read().strip()
    if not body:
        return ""
    title, _, rest = body.partition("\n")
    title = clip(title, NOTE_MAX // 4)
    return "<b>%s</b>%s" % (title, "\n" + clip(rest, NOTE_MAX - len(title)) if rest else "")


# What sclaude printed about the feature (ask_feed in sclaude/lib/io.sh):
# a line each, "<time>\t<level>\t<pid>\t<text>". The bot takes the file
# whole by renaming it — the next line printed starts a new one — and sends
# what gathered as one message a turn, shorter than the terminal: headlines,
# warnings and alarms, not the indented detail under them, and not the lines
# an open question already shows.
FEED_FILE = "feed.tsv"
# The most lines one message carries; the rest are counted.
FEED_MAX_LINES = 12
# Lines that matter to someone away from the laptop.
FEED_LOUD = ("warn", "alarm")
# How long lines that could not be sent are put back before they are let go.
FEED_KEEP = 3600
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def take_feed(channel, now=None):
    """The lines gathered since the last turn, [(level, pid, text, time)],
    the file taken for good."""
    now = time.time() if now is None else now
    path = os.path.join(channel, NOTES_DIR, FEED_FILE)
    taken = "%s.%d" % (path, os.getpid())
    try:
        os.rename(path, taken)
    except OSError:
        return []
    out = []
    try:
        with open(taken, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t", 3)
                if len(parts) != 4:
                    continue
                at = int(parts[0]) if parts[0].isdigit() else 0
                # Put back turn after turn and still not sent: let go.
                if at and now - at > FEED_KEEP:
                    continue
                out.append((parts[1], parts[2], ANSI.sub("", parts[3]), at or int(now)))
    finally:
        try:
            os.remove(taken)
        except OSError:
            pass
    return out


def put_back(channel, lines):
    """Lines taken but not sent, written back for the next turn: after any
    printed since, which a turn or two of disorder costs less than losing."""
    path = os.path.join(channel, NOTES_DIR, FEED_FILE)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            for level, pid, text, at in lines:
                fh.write("%d\t%s\t%s\t%s\n" % (at, level, pid, text))
    except OSError:
        pass


def feed_message(lines, shown=""):
    """The message for the gathered lines, and whether it should sound: (text,
    loud), or ("", False) when nothing is worth a message."""
    # Lines of what the question shows, matched from their start: a short
    # headline ("Done") is not shown just because those letters are somewhere
    # in the context.
    shown = {ANSI.sub("", ln).strip() for ln in (shown or "").splitlines()} - {""}
    kept = []
    for level, _pid, text, *_ in lines:
        # Indented lines are the detail under a headline; a line an open
        # question carries is already on the phone.
        if not text.strip() or (text[:1].isspace() and level not in FEED_LOUD):
            continue
        # The prompt is a line of its own that ends in its form ("[y/n]"):
        # the printed question is the start of that line.
        if any(ln == text.strip() or ln.startswith(text.strip() + " ") for ln in shown):
            continue
        kept.append((level, text.strip()))
    if not kept:
        return "", False
    # Cut by whole lines, each escaped within what is left: a cut through
    # "&amp;" or "<i>" is markup Telegram refuses, and the batch is gone.
    body, room = [], NOTE_MAX - 40
    for level, text in kept[:FEED_MAX_LINES]:
        line = clip(("⚠️ " if level in FEED_LOUD else "") + text, room)
        if not line:
            break
        body.append(line)
        room -= len(line) + 1
    if len(kept) > len(body):
        body.append("<i>… %d more</i>" % (len(kept) - len(body)))
    return "🖥 " + "\n".join(body), any(level in FEED_LOUD for level, _ in kept)


def check(bot, channels, topic, log, now=None, at_terminal=None, shown=None, lost=None):
    """Send every waiting note. channels: [(name, slug, directory)] of the
    features; topic(name, slug): the feature's topic, 0 for the main chat
    (no topics there), None for none yet — the notes then wait.
    at_terminal(pid): whether the person sits at the terminal that printed —
    then nothing sounds; shown(channel): the text an open question carries;
    lost(name, slug): called when a send failed — a topic deleted by hand is
    made again there, and what waits goes to the new one."""
    now = time.time() if now is None else now
    for name, slug, channel in channels:
        # Only to the feature's topic. The feed mirrors the terminal, and in
        # the main chat it would mix every feature's lines; the terminal still
        # has them. No topic yet (None): the lines wait for it. A chat with no
        # topics (0): they are let go.
        thread = None
        if os.path.exists(os.path.join(channel, NOTES_DIR, FEED_FILE)):
            thread = topic(name, slug)
        lines = take_feed(channel, now) if thread is not None else []
        text, loud = feed_message(lines, shown(channel) if shown else "") if lines else ("", False)
        if text and thread:
            pids = {line[1] for line in lines}
            if loud and at_terminal and any(at_terminal(pid) for pid in pids):
                loud = False
            if not bot.send(text, quiet=not loud, thread=thread):
                # The network: back to the file, for the next turn.
                put_back(channel, lines)
                log.warning("the feed of %s/%s waits: not sent", name, slug)
                if lost:
                    lost(name, slug)
        notes = pending(channel)
        if not notes:
            continue
        thread = None
        for path in notes:
            try:
                text = text_of(path)
                if not text or now - os.path.getmtime(path) > NOTE_KEEP:
                    os.remove(path)
                    continue
                if thread is None:
                    thread = topic(name, slug)
                    if thread is None:
                        # No topic yet, or the feature is going: the notes
                        # wait, and go with its channel if it ends.
                        break
                if not bot.send(text, quiet=True, thread=thread):
                    # The network, or a topic gone: the rest wait for the
                    # next turn, in order.
                    if lost:
                        lost(name, slug)
                    break
                os.remove(path)
            except OSError as exc:
                log.warning("the note %s of %s/%s: %s", os.path.basename(path), name, slug, exc)
