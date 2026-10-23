#!/usr/bin/env python3
#
# Notes: messages from sclaude that ask nothing, such as where a feature's
# review stands after each round. Both sides of the channel are checked here
# — ask_notice in sclaude/lib/io.sh lays them in notes/ (NOTES_DIR), and
# keepawake/notices.py sends them to the feature's topic and deletes them —
# so that a name changed on one side alone fails here.
#
# Telegram is never called: a fake bot records what it was given.
#
# Run it with: python3 tests/notices.py
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, ROOT)

box = tempfile.mkdtemp(prefix="notices-test-")
os.environ["KEEPAWAKE_STATE"] = os.path.join(box, "state.json")
os.environ["KEEPAWAKE_LOCK"] = os.path.join(box, ".lock")

from keepawake import notices, telegramd  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def notice(text, slug="feat-a", ended=""):
    """ask_notice as sclaude calls it, in a real bash."""
    script = ('source "%s/io.sh"\nASK_DIR="%s"\nASK_SLUG="%s"\nASK_ENDED="%s"\n'
              'ask_notice "$1"' % (LIB, os.path.join(box, "sclaude"), slug, ended))
    subprocess.run(["bash", "-c", script, "_", text], check=True, timeout=20)


channel = os.path.join(box, "sclaude", "ask", "feat-a")
notes = os.path.join(channel, notices.NOTES_DIR)


def laid():
    return [open(p).read() for p in notices.pending(channel)]


# --- sclaude's side --------------------------------------------------------------
notice("Review — PR #7, session 1\nruns 1 · found 3")
check("a note is laid in the feature's channel", laid(), ["Review — PR #7, session 1\nruns 1 · found 3"])
notice("Review — PR #7, session 1\nruns 1 · found 3")
check("the same text again is not laid twice", len(laid()), 1)
time.sleep(1.1)
notice("Review — PR #7, session 2\nruns 1 · found 1")
check("a new one is laid after it", len(laid()), 2)
notice("Review — PR #7, session 9", slug="")
check("no feature, no note: the repository's channel asks only",
      os.path.isdir(os.path.join(box, "sclaude", notices.NOTES_DIR)), False)
notice("Review — PR #7, session 9", slug="feat-b", ended="feat-b")
check("nor for a feature already ended", os.path.isdir(os.path.join(box, "sclaude", "ask", "feat-b")),
      False)


# --- the bot's side ---------------------------------------------------------------
class FakeBot(object):
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, text, keyboard=None, quiet=False, thread=None):
        if self.fail:
            return 0
        self.sent.append((text, thread, quiet))
        return 100 + len(self.sent)


log = logging.getLogger("notices-test")
topics = []


def topic(name, slug):
    topics.append((name, slug))
    return 31


bot = FakeBot(fail=True)
notices.check(bot, [("shop", "feat-a", channel)], topic, log)
check("a note not sent stays for the next turn", len(laid()), 2)

bot = FakeBot()
del topics[:]
notices.check(bot, [("shop", "feat-a", channel)], topic, log)
check("the notes go to the feature's topic, oldest first, each a message",
      [(t.split("\n")[0], th) for t, th, _ in bot.sent],
      [("<b>Review — PR #7, session 1</b>", 31), ("<b>Review — PR #7, session 2</b>", 31)])
check("without a sound: they ask nothing", [q for _, _, q in bot.sent], [True, True])
check("and are gone once sent", laid(), [])
check("the topic is looked up once a turn", topics, [("shop", "feat-a")])

notice("Review — PR #7, session 3 <b>")
check("text is escaped, not markup",
      notices.text_of(notices.pending(channel)[0]), "<b>Review — PR #7, session 3 &lt;b&gt;</b>")
old = notices.pending(channel)[0]
os.utime(old, (time.time() - notices.NOTE_KEEP - 60,) * 2)
bot = FakeBot()
notices.check(bot, [("shop", "feat-a", channel)], topic, log)
check("a note older than a day is dropped, not sent", (bot.sent, laid()), ([], []))

# A feature's channel is removed whole when it ends, its notes with it.
notice("Review — PR #7, session 4")
check("notes do not keep an ended feature's channel", telegramd.clear_channel(channel), True)

shutil.rmtree(box, ignore_errors=True)
if failures:
    print("notices: FAILED: %d" % len(failures))
    for name, want, got in failures:
        print("  %s\n    expected: %r\n    got:      %r" % (name, want, got))
    sys.exit(1)
print("notices: all checks passed")
