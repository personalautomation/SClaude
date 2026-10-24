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
notices.check(bot, [("shop", "feat-a", channel)], lambda name, slug: None, log)
check("no topic yet: the notes wait, not the main chat", (bot.sent, len(laid())), ([], 2))

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

# --- the feed: what sclaude prints, shorter, a message a turn ------------------------
def feed(level, text, slug="feat-a"):
    script = ('source "%s/io.sh"\nASK_DIR="%s"\nASK_SLUG="%s"\nASK_ENDED=""\n'
              'ask_feed "$1" "$2"' % (LIB, os.path.join(box, "sclaude"), slug))
    subprocess.run(["bash", "-c", script, "_", level, text], check=True, timeout=20)


feed("say", "\x1b[1mReview round closed\x1b[0m")
feed("info", "  its context is at 40%")
feed("info", "Local regression: running e2e")
feed("warn", "  ✗ e2e failed")
feed("say", "Check the fixes with a review pass?")
feed("say", "Feature name:", slug="")
check("the repository's own lines are not fed",
      os.path.exists(os.path.join(box, "sclaude", notices.NOTES_DIR)), False)
bot = FakeBot()
sounds = []
notices.check(bot, [("shop", "feat-a", channel)], topic, log,
              at_terminal=lambda pid: sounds.append(pid) or False,
              shown=lambda ch: "Check the fixes with a review pass? [y/n]")
check("one message for what gathered", len(bot.sent), 1)
text, thread, quiet = bot.sent[0]
check("headlines, not the indented detail, and no colour codes",
      text, "🖥 Review round closed\nLocal regression: running e2e\n⚠️ ✗ e2e failed")
check("a warning sounds when nobody is at the terminal", quiet, False)
check("and goes to the feature's topic", thread, 31)
check("the feed is taken: nothing is sent twice",
      os.path.exists(os.path.join(notes, notices.FEED_FILE)), False)

feed("warn", "✗ e2e failed")
bot = FakeBot()
notices.check(bot, [("shop", "feat-a", channel)], topic, log, at_terminal=lambda pid: True)
check("at the terminal nothing sounds", bot.sent[0][2], True)
feed("info", "Deploying the preview")
bot = FakeBot()
notices.check(bot, [("shop", "feat-a", channel)], topic, log, at_terminal=lambda pid: False)
check("progress is silent", bot.sent[0][2], True)
feed("info", "Deploying the preview")
bot = FakeBot()
notices.check(bot, [("shop", "feat-a", channel)], lambda name, slug: 0, log)
check("with no topic the feed stays out of the main chat", bot.sent, [])
check("a line only inside the question's context is still sent",
      notices.feed_message([("say", "1", "Done")], "PR 7 is Done, merged")[0], "🖥 Done")
# An empty note is dropped, not refused by Telegram every turn ahead of
# the rest.
with open(os.path.join(notes, "000-empty.txt"), "w") as fh:
    fh.write("  \n ")
bot = FakeBot()
notices.check(bot, [("shop", "feat-a", channel)], topic, log)
check("an empty note is dropped", (bot.sent, os.path.exists(os.path.join(notes, "000-empty.txt"))),
      ([], False))

# No topic yet: the lines wait for it. A send that fails: they go back.
feed("warn", "✗ e2e failed")
bot = FakeBot()
notices.check(bot, [("shop", "feat-a", channel)], lambda name, slug: None, log)
check("no topic yet: the feed waits in its file",
      (bot.sent, os.path.exists(os.path.join(notes, notices.FEED_FILE))), ([], True))
bot = FakeBot(fail=True)
notices.check(bot, [("shop", "feat-a", channel)], topic, log)
check("a feed not sent is kept for the next turn",
      [line[2] for line in notices.take_feed(channel)], ["✗ e2e failed"])
# Not sent for an hour: let go rather than kept for ever.
feed("warn", "old news")
check("lines put back past FEED_KEEP are let go",
      notices.take_feed(channel, now=time.time() + notices.FEED_KEEP + 60), [])
lost_calls = []
feed("warn", "✗ e2e failed")
notices.check(FakeBot(fail=True), [("shop", "feat-a", channel)], topic, log,
              lost=lambda name, slug: lost_calls.append((name, slug)))
check("a failed send asks for the topic again", lost_calls, [("shop", "feat-a")])
notices.take_feed(channel)

# Cut to fit a message, never through an entity: Telegram refuses the markup.
# A line that opens with its kind's icon (phase_line) leads with it; the
# laptop's goes on the rest, a box-drawing rule included.
check("own-icon-leads",
      notices.feed_message([("say", "1", "🛠 Step 4/7 review: fix session 1 resumed")])[0],
      "🛠 Step 4/7 review: fix session 1 resumed")
check("own-icon-loud", notices.feed_message([("alarm", "1", "🚀 Deploy failed: preview")])[0],
      "⚠️ 🚀 Deploy failed: preview")
check("rule-is-no-icon", notices.feed_message([("say", "1", "── 12/12 green")])[0],
      "🖥 ── 12/12 green")
# One step's lines are not mixed with the next one's: a step done ends the
# message, and a start begins a new one once the message holds another
# phase's line; a warning printed while the next step is set up goes with it.
_batch = [("say", "1", "📝 Step 1/7 planning: session 1 finished"), ("say", "1", "Plan approved"),
          ("say", "1", "✅ Step 1/7 done: planning"), ("warn", "1", "database: migrations did not apply"),
          ("say", "1", "💻 Step 2/7 development: session 1 started")]
check("one-step-a-message",
      [notices.feed_message(g)[0] for g in notices.feed_groups(_batch)],
      ["📝 Step 1/7 planning: session 1 finished\nPlan approved\n✅ Step 1/7 done: planning",
       "🖥 ⚠️ database: migrations did not apply\n💻 Step 2/7 development: session 1 started"])
# The step's ✅ comes after its session's friction review, and is not its end.
check("done-after-friction-goes-alone",
      [notices.feed_message(g)[0] for g in notices.feed_groups([
          ("say", "1", "💻 Step 2/7 development: session 1 finished"),
          ("say", "1", "🧱 Friction review started: after step 2/7 development, session 1 · 2 entries"),
          ("say", "1", "🧱 Friction review finished: after step 2/7 development, session 1"),
          ("say", "1", "✅ Step 2/7 done: development")])],
      ["💻 Step 2/7 development: session 1 finished",
       "🧱 Friction review started: after step 2/7 development, session 1 · 2 entries\n"
       "🧱 Friction review finished: after step 2/7 development, session 1",
       "✅ Step 2/7 done: development"])
check("a-start-alone-is-not-cut",
      len(notices.feed_groups([("warn", "1", "x"), ("say", "1", "💻 Step 2/7 development: session 1 started")])), 1)

long_text, _ = notices.feed_message([("say", "1", "&" * 1000)] * 13)
check("a long feed fits a message", len(long_text) <= notices.NOTE_MAX, True)
check("cut between entities, the rest counted",
      (long_text.split("\n")[-2].endswith("&amp;…"), long_text.endswith("<i>… 12 more</i>")),
      (True, True))
check("long runs are counted, not sent whole",
      notices.feed_message([("info", "1", "line %d" % i) for i in range(20)])[0].splitlines()[-1],
      "<i>… 8 more</i>")

# A feature ended elsewhere gets no feed: its channel is being deleted.
open(os.path.join(channel, "ended"), "w").close()
os.remove(os.path.join(notes, notices.FEED_FILE)) if os.path.exists(
    os.path.join(notes, notices.FEED_FILE)) else None
feed("info", "removed the worktree")
check("an ended feature's channel gets no feed",
      os.path.exists(os.path.join(notes, notices.FEED_FILE)), False)
os.remove(os.path.join(channel, "ended"))

# --- the review's keys: buttons on the message a pass or fix session started ---------
from keepawake import review_keys  # noqa: E402


def phase(*args):
    """A phase line as sclaude prints it (phase_line in steps.sh)."""
    script = 'source "%s/steps.sh"; source "%s/regression.sh"; phase_line "$@"' % (LIB, LIB)
    return subprocess.run(["bash", "-c", script, "_"] + list(args), capture_output=True,
                          text=True, timeout=20).stdout.strip()


class KeyBot(FakeBot):
    def __init__(self):
        FakeBot.__init__(self)
        self.kb, self.marks = [], []

    def send(self, text, keyboard=None, quiet=False, thread=None):
        self.kb.append(keyboard)
        return FakeBot.send(self, text, keyboard, quiet, thread)

    def unbutton(self, message_id, keyboard=None):
        self.marks.append((message_id, keyboard and [b["callback_data"] for row in keyboard for b in row]))


def data_of(keyboard):
    return keyboard and [b["callback_data"] for row in keyboard for b in row]


me = str(os.getpid())
for line in (phase("started", "local-review", "7", "2"), phase("finished", "local-review", "7", "2"),
             phase("started", "local-review", "7", "3", "verify"),
             phase("started", "step", "review", "2"), phase("resumed", "step", "review", "2", "3"),
             phase("started", "step", "code", "1")):
    check("a phase line: %s" % line, bool(notices.OWN_ICON.match(line)), True)
check("a searching pass takes the keys",
      review_keys.kind_of([("say", me, phase("started", "local-review", "7", "2"))]), ("pass", me))
check("a check of the fixes takes none",
      review_keys.kind_of([("say", me, phase("started", "local-review", "7", "3", "verify"))]), ("", ""))
check("a fix session takes the last-round key",
      review_keys.kind_of([("say", me, phase("started", "step", "review", "2"))]), ("session", me))
check("a resumed one too",
      review_keys.kind_of([("say", me, phase("resumed", "step", "review", "2", "3"))])[0], "session")
check("another step takes none", review_keys.kind_of([("say", me, phase("started", "step", "code", "1"))])[0], "")
check("started and finished in one message: nothing left to press",
      review_keys.kind_of([("say", me, phase("started", "local-review", "7", "2")),
                           ("say", me, phase("finished", "local-review", "7", "2") + " · 0 open")])[0], "")

kbot = KeyBot()
feed("say", phase("started", "local-review", "7", "2"))
notices.check(kbot, [("shop", "feat-a", channel)], topic, log, keys=review_keys)
check("the start goes with the pass's keys", data_of(kbot.kb[-1]), ["rv:pass", "rv:stop"])
first = review_keys.load(channel)
check("and is remembered as the message that has them", first.get("message_id"), 100 + len(kbot.sent))

feed("warn", "  ✗ something printed during the pass")
notices.check(kbot, [("shop", "feat-a", channel)], topic, log, keys=review_keys)
check("a line that is no phase leaves them", (kbot.marks, review_keys.load(channel) == first), ([], True))

alive = lambda pid: True  # noqa: E731
press = lambda data: review_keys.press(kbot, [channel], first["message_id"], data, alive)  # noqa: E731
check("an unknown message is told it is over",
      (review_keys.press(kbot, [channel], 9999, "rv:pass", alive), kbot.marks[-1]), (telegramd.t("rv.gone"), (9999, None)))
toast = press("rv:pass")
said_path = os.path.join(channel, review_keys.SAID_FILE)
check("[s] from the phone: the word for sclaude", open(said_path).read(), "pass")
check("its button becomes the one taking it back", kbot.marks[-1], (first["message_id"], ["rv:back", "rv:stop"]))
check("and the toast says so", toast, telegramd.t("rv.pass.ok"))
press("rv:stop")
check("stop asks once more first", kbot.marks[-1], (first["message_id"], ["rv:now", "rv:carry"]))
check("and says nothing to sclaude yet", open(said_path).read(), "pass")
press("rv:carry")
check("carry on: back as it was", kbot.marks[-1], (first["message_id"], ["rv:back", "rv:stop"]))

# sclaude takes the word as review_enough does, outside a pass's wait.
wt = os.path.join(box, "wt")
os.makedirs(os.path.join(wt, ".sclaude", "local", "feature"))
with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json"), "w") as fh:
    fh.write("{}\n")


def take(*extra):
    script = ('source "%s/io.sh"; source "%s/state.sh"; source "%s/local_review.sh"\n'
              'LIB="%s"; ASK_DIR="%s"; ASK_SLUG=feat-a\nreview_said_take "$@"; echo "|$(review_enough "$1")"'
              % (LIB, LIB, LIB, LIB, os.path.join(box, "sclaude")))
    return subprocess.run(["bash", "-c", script, "_", wt] + list(extra), capture_output=True,
                          text=True, timeout=20).stdout.strip()


check("sclaude takes the phone's [s]", take(), "pass\n|pass")
check("once", (take(), os.path.exists(said_path)), ("|pass", False))
press("rv:back")
check("taken back from the phone", take(), "back\n|")
review_keys.say(channel, "now")
check("a stop with no pass running is the last pass", take(), "pass\n|pass")
review_keys.say(channel, "now")
check("in a pass's wait it is kept a stop", take("wait"), "now\n|now")
review_keys.say(channel, "junk")
check("a word it does not know is dropped", (take(), os.path.exists(said_path)), ("|now", False))


# A press nobody took goes when step 4 closes, with the enough it would set:
# the next review must not start on a word said about this one.
def drop(ended=""):
    script = ('source "%s/io.sh"; source "%s/state.sh"; source "%s/local_review.sh"\n'
              'ASK_DIR="%s"; ASK_SLUG=feat-a; ASK_ENDED="%s"\nreview_said_drop'
              % (LIB, LIB, LIB, os.path.join(box, "sclaude"), ended))
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20).returncode


review_keys.say(channel, "pass")
check("a clean-up that ended leaves the channel alone", (drop("feat-a"), os.path.exists(said_path)), (0, True))
check("the press goes with step 4", (drop(), os.path.exists(said_path)), (0, False))

press("rv:now")
check("a stop takes the buttons off", (kbot.marks[-1], review_keys.load(channel)), ((first["message_id"], None), {}))

feed("say", phase("started", "step", "review", "2"))
notices.check(kbot, [("shop", "feat-a", channel)], topic, log, keys=review_keys)
check("a fix session's start has the last-round key", data_of(kbot.kb[-1]), ["rv:pass"])
session = review_keys.load(channel)
check("whose press says so", review_keys.press(kbot, [channel], session["message_id"], "rv:pass", alive),
      telegramd.t("rv.round.ok"))
check("a session has no stop", review_keys.press(kbot, [channel], session["message_id"], "rv:now", alive), "")
os.remove(said_path)
marks = len(kbot.marks)
feed("say", phase("finished", "step", "review", "2"))
notices.check(kbot, [("shop", "feat-a", channel)], topic, log, keys=review_keys)
check("its end takes the buttons off", kbot.marks[marks:], [(session["message_id"], None)])
check("and the end itself has none", (kbot.kb[-1], review_keys.load(channel)), (None, {}))

feed("say", phase("started", "local-review", "7", "3"))
notices.check(kbot, [("shop", "feat-a", channel)], topic, log, keys=review_keys)
gone = review_keys.load(channel)
check("sclaude gone: the press says so and the buttons go",
      (review_keys.press(kbot, [channel], gone["message_id"], "rv:pass", lambda pid: False),
       kbot.marks[-1], os.path.exists(said_path)),
      (telegramd.t("rv.gone"), (gone["message_id"], None), False))

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
