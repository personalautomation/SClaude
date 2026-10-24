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
# The icons sclaude's phase_line opens every session's start and end with
# (phase_icon in sclaude/lib/steps.sh): a line that opens with one names its
# kind, and the message then opens with that icon rather than the laptop's.
# These and no others — a "✓ passed" or a "⚠ careful" of sclaude's own is
# still the laptop's.
PHASE_ICONS = ("📝", "💻", "📤", "🛠", "▶️", "✅", "🧱", "🔧", "🔍", "🧪", "🚀", "🔀", "🏁", "🔁")
OWN_ICON = re.compile("^(?:%s) " % "|".join(re.escape(i) for i in PHASE_ICONS))
# The first five are the steps' own sessions, whose step's ✅ belongs with them.
STEP_ICONS = PHASE_ICONS[:5]


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


# A step's lines and the next one's are not one message: a line closing a
# step ("✅ Step 1/7 done") ends the message, and one opening a session or a
# run ("... started", "... resumed") begins a new one once the message holds
# another's phase line already. What stands between — a warning printed while
# the next step is set up — goes with the start it leads to.
OPENS = re.compile(r"\b(started|resumed)\b")
CLOSES = "✅ "


def feed_groups(lines):
    """The gathered lines cut where one step's account ends and another's
    begins, oldest first: [[line, ...], ...]."""
    groups, current, lead = [], [], None
    for line in lines:
        text = ANSI.sub("", line[2] or "").strip()
        own = OWN_ICON.match(text)
        # A step's ✅ comes after the friction review of its last session:
        # it is not that review's end, and goes on its own.
        if lead and (own and OPENS.search(text)
                     or text.startswith(CLOSES) and lead not in STEP_ICONS):
            groups.append(current)
            current, lead = [], None
        current.append(line)
        lead = lead or (own and own.group(0).strip())
        if text.startswith(CLOSES):
            groups.append(current)
            current, lead = [], None
    if current:
        groups.append(current)
    return groups


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
    # A message that opens with a phase line is about that phase — the batch
    # is cut so (feed_groups) — and leads with its icon, not the laptop's.
    head = "" if OWN_ICON.match(kept[0][1]) else "🖥 "
    return head + "\n".join(body), any(level in FEED_LOUD for level, _ in kept)


def check(bot, channels, topic, log, now=None, at_terminal=None, shown=None, lost=None,
          keys=None):
    """Send every waiting note. channels: [(name, slug, directory)] of the
    features; topic(name, slug): the feature's topic, 0 for the main chat
    (no topics there), None for none yet — the notes then wait.
    at_terminal(pid): whether the person sits at the terminal that printed —
    then nothing sounds; shown(channel): the text an open question carries;
    lost(name, slug): called when a send failed — a topic deleted by hand is
    made again there, and what waits goes to the new one. keys: the review's
    buttons (review_keys.py) — a message that a review pass or fix session
    started carries them, and the next phase line takes them off."""
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
        context = shown(channel) if shown and lines else ""
        groups = feed_groups(lines) if lines else []
        for i, group in enumerate(groups):
            text, loud = feed_message(group, context)
            if not (text and thread):
                continue
            pids = {line[1] for line in group}
            if loud and at_terminal and any(at_terminal(pid) for pid in pids):
                loud = False
            # A phase line means what had the buttons is over, whatever this
            # message is about.
            if keys and keys.has_phase(group):
                keys.drop(bot, channel)
            sent = bot.send(text, keyboard=keys.buttons_for(group) if keys else None,
                            quiet=not loud, thread=thread)
            if sent and keys:
                keys.sent(channel, group, sent)
            if not sent:
                # The network: back to the file, this group and the rest,
                # for the next turn.
                put_back(channel, [line for g in groups[i:] for line in g])
                log.warning("the feed of %s/%s waits: not sent", name, slug)
                if lost:
                    lost(name, slug)
                break
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
