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


def text_of(path):
    """A note as a message: its first line in bold, as a title."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        body = fh.read().strip()[:NOTE_MAX]
    title, _, rest = body.partition("\n")
    return "<b>%s</b>%s" % (html.escape(title), "\n" + html.escape(rest) if rest else "")


def check(bot, channels, topic, log, now=None):
    """Send every waiting note. channels: [(name, slug, directory)] of the
    features; topic(name, slug): the feature's topic, 0 for the main chat."""
    now = time.time() if now is None else now
    for name, slug, channel in channels:
        notes = pending(channel)
        if not notes:
            continue
        thread = None
        for path in notes:
            try:
                if now - os.path.getmtime(path) > NOTE_KEEP:
                    os.remove(path)
                    continue
                if thread is None:
                    thread = topic(name, slug) or 0
                if not bot.send(text_of(path), quiet=True, thread=thread):
                    # The network: the rest wait for the next turn, in order.
                    break
                os.remove(path)
            except OSError as exc:
                log.warning("the note %s of %s/%s: %s", os.path.basename(path), name, slug, exc)
