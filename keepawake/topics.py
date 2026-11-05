# keepawake's Telegram bot — a Telegram topic per feature: its record in the
# feature's tree, opening and naming it, the messages kept for deleting it, and
# the feature's end.
#
# Part of the bot that keepawake/telegramd.py runs.

import glob
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from keepawake import notices, state
from keepawake.i18n import t
from keepawake.state import locked, read
from keepawake import asks, card_view, holding, repos


log = logging.getLogger("keepawake")


# --- a topic per feature -------------------------------------------------------
#
# The bot runs in Threaded Mode (set in @BotFather), and each feature that asks
# something gets a topic of its own in the private chat; the menu, the sleep
# warning and the repository's own questions stay in the main chat. Without
# the mode creating a topic fails, and everything goes to the main chat as it
# did before.
#
# What the bot knows of a feature — its topic, the message showing its open
# question — is the feature's, and lives with it, in the worktree only: under
# .sclaude/local/feature/, which git and every upload leave out. A feature asks
# in its channel only while its worktree exists (ask_channel in io.sh).
#
# The topic goes with the worktree, everything in it included: remove_worktree
# reads the record before the worktree goes and leaves it in the channel's
# "ended" mark (ask_feature_end), and the bot deletes the topic named there and
# the channel. Telegram does not let a bot close a topic in a private chat —
# only delete it.

FEATURE_RECORD = "telegram.json"
ENDED_MARK = "ended"
# Set in the worktree by stop_dev (sclaude/lib/worktree.sh) when its removal
# begins, and honoured by sclaude-proxy too.
CLOSING_MARK = "closing"

# The name's length. Telegram allows 128 characters, but a phone shows a topic
# list and a topic's header in about thirty: the slug comes first so that its
# start is what shows, and the repository's name after it, dropped when the
# slug leaves it no room.
TOPIC_NAME_MAX = 48
# How long a question waits for its feature's topic before the main chat takes
# it: a refusal that is not "not a forum" may never pass, and a question that
# never shows stalls the step.
TOPIC_WAIT = 120
# A feature's failed tries to make or reach its topic: key → (first, last).
# In memory: a restart starts the wait afresh, which is all it should do.
TOPIC_TRIED = {}
# A pause in failures this long, and the next one starts a new wait.
TOPIC_QUIET = 600
# The same for a feature opened from the list, by its key.
CARD_TRIED = {}


def topic_pending(repo, slug, tried, tag):
    # A topic is to be had — the feature has a worktree, Threaded Mode is on —
    # but was not made or reached: the network or a rate limit. True for
    # TOPIC_WAIT from the first such try (kept in tried under tag); after that
    # a refusal that may never pass gives way to the main chat.
    #
    # The wait is the feature's, not each question's: a refusal that lasts
    # holds up its first question only. Tries stop counting after a quiet
    # spell, so a blip a day later waits afresh.
    now = int(time.time())
    # A try quiet this long is spent: its feature reached its topic, or went.
    for old in [k for k, (_, last) in tried.items() if now - last > TOPIC_QUIET]:
        tried.pop(old, None)
    if not (repo and feature_dir(repo, slug)) or now < (read().get("topics_off_until") or 0):
        return False
    first, _ = tried.get(tag) or (now, now)
    tried[tag] = (first, now)
    return now - first < TOPIC_WAIT


# Every message in a feature's topic, the bot's and the person's, one id a
# line in a file named by the topic (state.topic_ledger; bin/sclaude-notify
# appends to it as well). Deleting a topic in a private chat leaves its
# messages standing in the "All" view, so delete_topic deletes them first.
# Telegram lets a bot delete only what is under 48 hours old: older ones stay.
topic_ledger = state.topic_ledger
# deleteMessages takes at most this many ids a call.
DELETE_BATCH = 100


def remember_in_topic(thread, message_id):
    if not thread or not message_id:
        return
    try:
        path = topic_ledger(thread)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%d\n" % int(message_id))
    except (OSError, TypeError, ValueError) as exc:
        log.warning("a message of topic %s was not recorded: %s", thread, exc)


def clear_topic_messages(bot, thread):
    # Whether nothing recorded is left to delete. False only on a failure
    # worth another try (the network): a refusal — a message too old, gone
    # already — is retried id by id, and what still will not go is left.
    #
    # Taken aside by a rename before it is read: sclaude-notify may append to
    # the record meanwhile, and an id written between the read and the unlink
    # would be lost. What it writes after the rename starts the record anew,
    # and is read on the next turn. A copy taken aside and not cleared — the
    # network, a kill — is read again with it.
    path = topic_ledger(thread)
    try:
        os.replace(path, "%s.%d" % (path, time.time_ns()))
    except OSError:
        pass
    taken = glob.glob(glob.escape(path) + ".*")
    ids = set()
    for one in taken:
        try:
            with open(one, encoding="utf-8") as fh:
                ids.update(int(line) for line in fh if line.strip().isdigit())
        except OSError:
            pass
    ids = sorted(ids)
    for i in range(0, len(ids), DELETE_BATCH):
        batch = ids[i:i + DELETE_BATCH]
        try:
            bot.call("deleteMessages", chat_id=bot.chat_id, message_ids=batch)
        except urllib.error.HTTPError as exc:
            log.warning("deleteMessages refused (%s); deleting one by one",
                        getattr(exc, "telegram", "") or exc)
            for mid in batch:
                bot.delete(mid)
        except Exception as exc:
            log.warning("the messages of topic %s were not deleted: %s", thread, exc)
            return False
    for one in taken:
        try:
            os.unlink(one)
        except OSError:
            pass
    return not os.path.exists(path)


# How long a topic delete is retried before its end mark is let go.
TOPIC_DELETE_FOR = 86400
# Telegram's refusals that mean a topic is not there to delete.
TOPIC_GONE = ("thread not found", "topic_id_invalid", "topic_deleted", "not a forum")
# How many cards outside topics (Threaded Mode off) keep their feature known.
MAIN_CARDS = 20
# How long a refusal to make a topic ("the chat is not a forum") is believed.
TOPICS_OFF_RETRY = 600
TOPIC_NAME_SLUG_MIN = 16
# A feature whose worktree is gone without the clean-up saying so — removed by
# hand — loses its channel this long after it last changed. Its topic stays: its
# id went with the worktree. Not at once, so that a channel being written while
# the worktree is created is not taken for one.
TOPIC_GRACE = 600


def topic_lost(bot):
    # The last call failed because its topic is gone, not for the network.
    return any(w in (bot.last_error or "") for w in TOPIC_GONE)


def topic_name(name, slug):
    tail = " · " + name
    room = TOPIC_NAME_MAX - len(tail)
    if room < TOPIC_NAME_SLUG_MIN or len(slug) > room:
        tail = ""
        room = TOPIC_NAME_MAX
    if len(slug) > room:
        slug = slug[:room - 1].rstrip("-_.") + "…"
    return slug + tail


def feature_wt(repo, slug):
    return os.path.join(os.path.dirname(repo), "%s-%s" % (os.path.basename(repo), slug))


def feature_dir(repo, slug):
    # The feature's own directory in its worktree, "" while there is none.
    # Only the current layout: io.sh keeps the record there alone, and a tree
    # still on the old .feature/ asks in the main chat until it moves.
    d = os.path.join(feature_wt(repo, slug), ".sclaude/local/feature")
    return d if os.path.isdir(d) else ""


def record_path(repo, slug):
    # "" while the feature has no worktree: there is then nowhere to keep it.
    d = feature_dir(repo, slug)
    return os.path.join(d, FEATURE_RECORD) if d else ""


def load_record(repo, slug):
    path = record_path(repo, slug)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_record(repo, slug, record):
    _TOPIC_KEYS.clear()       # a thread may have just been written
    path = record_path(repo, slug)
    if not path:
        return
    tmp = "%s.%d" % (path, os.getpid())
    # No makedirs: record_path has just found the directory, and making it
    # again would bring back a worktree that remove_worktree is deleting this
    # very moment — `sclaude new` would then find the path taken.
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("the record of %s was not written: %s", slug, exc)


def feature_topic(bot, name, slug, renew=False):
    # The feature's topic, made on its first question. 0 when there is none
    # to be had: Threaded Mode is off, or the network failed. renew drops a
    # topic the person deleted by hand.
    repo = repos.repo_path(name)
    if not repo or not feature_dir(repo, slug):
        return 0
    record = load_record(repo, slug)
    thread = 0 if renew else (record.get("thread") or 0)
    if renew and (record.get("shown") or {}).get("thread"):
        # The question shown in the lost topic went with it: forgotten, it is
        # sent again into the new one on the loop's next turn. One shown in
        # the main chat is still there, and stays the loop's to settle.
        record.pop("shown", None)
    if not thread:
        # Threaded Mode off: Telegram says the chat is not a forum. That is
        # remembered for a while rather than asked again for every question
        # and every press.
        now = int(time.time())
        if now < (read().get("topics_off_until") or 0):
            return 0
        thread = adopt_new_topic(bot, name, slug)
        if thread:
            record.pop("card", None)
            record["thread"] = thread
            save_record(repo, slug, record)
            card_view.post_card(bot, name, slug)
            return thread
        thread = bot.create_topic(topic_name(name, slug))
        if not thread:
            if "not a forum" in bot.last_error:
                with locked() as st:
                    st["topics_off_until"] = now + TOPICS_OFF_RETRY
            return 0
        log.info("a topic for %s/%s: %s", name, slug, thread)
        record.pop("card", None)
        record["thread"] = thread
        save_record(repo, slug, record)
        # A topic opens with its feature's card (post_card).
        card_view.post_card(bot, name, slug)
    return thread


# A new feature's topic, made when it is started from the bot. Its first
# questions — the name, the issue — come before the feature has a name, from
# the repository's own channel, and would otherwise land in the main chat. They
# go to this topic instead, and the first feature of that repository to need a
# topic afterwards takes it over, renamed. One per repository, in the state:
# {name: {"thread": id, "since": ts}}. One nobody took over goes after
# NEW_TOPIC_KEEP, unless a question is still open in it.
NEW_TOPIC_KEEP = 12 * 3600


def asks_for_new(pid):
    """Whether the process asking is `sclaude new` — the start the new-feature
    topic was made for."""
    try:
        with open("/proc/%d/cmdline" % int(pid or 0), "rb") as fh:
            args = fh.read().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(os.path.basename(a) == b"sclaude" for a in args) and b"new" in args


def new_feature_topic(bot, name):
    """The new-feature topic of this repository, made now; 0 without topics."""
    old = (read().get("new_topics") or {}).get(name)
    if old and old.get("thread"):
        return old["thread"]
    if int(time.time()) < (read().get("topics_off_until") or 0):
        return 0
    thread = bot.create_topic(t("feat.newtopic", repo=name)[:TOPIC_NAME_MAX])
    if thread:
        with locked() as st:
            topics = st.get("new_topics") or {}
            topics[name] = {"thread": thread, "since": int(time.time())}
            st["new_topics"] = topics
        log.info("a new-feature topic for %s: %s", name, thread)
    return thread


def new_topic_of(name):
    return ((read().get("new_topics") or {}).get(name) or {}).get("thread") or 0


def drop_new_topic(name):
    with locked() as st:
        topics = st.get("new_topics") or {}
        entry = topics.pop(name, None)
        st["new_topics"] = topics
    return entry


def adopt_new_topic(bot, name, slug):
    """The repository's new-feature topic, renamed for this feature, when the
    feature is the one it was made for: its worktree appeared after the topic.
    0 otherwise."""
    entry = (read().get("new_topics") or {}).get(name) or {}
    repo = repos.repo_path(name)
    # A worktree's .git is a file written once, when the worktree is made;
    # the directories in it change with every write.
    try:
        born = os.stat(os.path.join(feature_wt(repo, slug), ".git")).st_mtime if repo else 0
    except OSError:
        born = 0
    if not entry.get("thread") or born < (entry.get("since") or 0) - 60:
        return 0
    drop_new_topic(name)
    bot.rename_topic(entry["thread"], topic_name(name, slug))
    log.info("the new-feature topic %s is %s/%s's now", entry["thread"], name, slug)
    return entry["thread"]


def new_worktrees(repo, since):
    """Slugs of the repository's features whose worktree appeared after since."""
    prefix = os.path.basename(repo) + "-"
    out = []
    for git in glob.glob(os.path.join(glob.escape(os.path.dirname(repo)),
                                      glob.escape(prefix) + "*", ".git")):
        slug = os.path.basename(os.path.dirname(git))[len(prefix):]
        try:
            born = os.stat(git).st_mtime
        except OSError:
            continue
        if born >= since - 60 and feature_dir(repo, slug):
            out.append(slug)
    return out


def check_new_topics(bot):
    # The feature a topic was made for takes it as soon as its worktree is
    # there, not at its first question: a start may ask nothing after the
    # name, and the topic would go on calling it "new feature".
    #
    # A start abandoned before the feature got a name leaves its topic: it
    # goes once nothing is asked in it any more.
    now = int(time.time())
    for name, entry in list((read().get("new_topics") or {}).items()):
        repo = repos.repo_path(name)
        # A feature that already has a topic is not the one this was made for.
        born = [slug for slug in (new_worktrees(repo, entry.get("since") or 0) if repo else [])
                if not load_record(repo, slug).get("thread")]
        if born:
            feature_topic(bot, name, born[0])
            continue
        if now - (entry.get("since") or 0) < NEW_TOPIC_KEEP:
            continue
        if repo and asks.pending_ask(asks.ask_dir(repo)):
            continue
        if bot.delete_topic(entry.get("thread") or 0):
            drop_new_topic(name)
            log.info("the unused new-feature topic of %s is gone", name)


def open_channels():
    """[(key, directory)] of every channel with an open question."""
    found = []
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        for slug, channel in asks.ask_channels(repo):
            if asks.pending_ask(channel):
                found.append((asks.channel_key(name, slug), channel))
    return found


def press_channel(name, message_id, repo=None):
    # The channel key a press on a question's message answers, or "" when the
    # message shows no open question. A question remembered before message ids
    # were kept has none to match, and a press then answers the repository's
    # channel, as every press did before.
    for key in asks.repo_keys(name, repo):
        entry = asks.get_shown(key, repo) or {}
        if message_id and entry.get("msg") == message_id:
            return key
    if (asks.get_shown(name) or {}).get("legacy"):
        return name
    return ""


def press_answered(name, message_id, repo=None):
    # Whether the press is a second one on a question just answered here: its
    # message already shows the answer, and must neither be answered again nor
    # deleted as closed.
    return any(message_id and (asks.get_shown(k, repo) or {}).get("answered") == message_id
               for k in asks.repo_keys(name, repo))


def message_thread(msg):
    # The topic a message is in, 0 for the main chat. A message in the main
    # chat may carry a thread id too — that of the message it replies to — so
    # only is_topic_message counts.
    return (msg.get("message_thread_id") or 0) if msg.get("is_topic_message") else 0


def feature_records(repo, record=FEATURE_RECORD):
    """[slug] of the repository's features that have a record of the bot's —
    or, with record="state.json", every feature sclaude keeps a state for.

    By the name alone "app-admin-x" is as much feature "admin-x" of "app" as
    feature "x" of "app-admin"; the worktree's .git file, which names the
    repository it belongs to, settles it."""
    name = os.path.basename(repo)
    prefix = name + "-"
    own = os.path.join(os.path.realpath(repo), ".git", "worktrees") + os.sep
    found = []
    pattern = os.path.join(glob.escape(os.path.dirname(repo)), glob.escape(prefix) + "*",
                           ".sclaude", "local", "feature", record)
    for path in sorted(glob.glob(pattern)):
        tree = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        try:
            with open(os.path.join(tree, ".git"), encoding="utf-8") as fh:
                gitdir = fh.read().strip().partition("gitdir:")[2].strip()
        except OSError:
            continue
        # git 2.48+ may write it relative to the worktree.
        if not os.path.realpath(os.path.join(tree, gitdir)).startswith(own):
            continue
        found.append(os.path.basename(tree)[len(prefix):])
    return found


# One search serves a message: it reads every worktree's record, and one
# message asks for its topic several times (the text, the menu it draws).
TOPIC_FRESH = 5
_TOPIC_KEYS = {}


def topic_channel(thread):
    # The feature key whose topic this is, or "". A topic made from the menu
    # has no channel until the feature asks something, so the records in the
    # worktrees are what is searched.
    if not thread:
        return ""
    now = time.time()
    at, key = _TOPIC_KEYS.get(thread, (0.0, ""))
    if now - at < TOPIC_FRESH:
        return key
    key = ""
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        for slug in feature_records(repo):
            if load_record(repo, slug).get("thread") == thread:
                key = asks.channel_key(name, slug)
                break
        if key:
            break
    # Kept found or not: save_record forgets it all, so a topic just adopted
    # is not missed for the seconds a "none" would stand.
    _TOPIC_KEYS[thread] = (now, key)
    return key


def check_topics(bot):
    # A finished feature's topic goes, with everything in it, and its channel
    # with it: at once when its worktree's removal left the mark. A channel whose
    # worktree went without one (removed by hand) goes after TOPIC_GRACE; its
    # topic cannot, its id having gone with the worktree.
    now = int(time.time())
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        for slug, channel in asks.ask_channels(repo):
            if not slug:
                continue
            if asks.pending_ask(channel):
                continue
            mark = os.path.join(channel, ENDED_MARK)
            if os.path.exists(mark):
                if feature_dir(repo, slug):
                    # A new feature under the same name, made before the bot
                    # came to the old one's mark: the old topic goes, the
                    # channel stays.
                    if end_feature(bot, name, slug, channel, mark):
                        try:
                            os.unlink(mark)
                        except OSError:
                            pass
                    continue
                if not end_feature(bot, name, slug, channel, mark):
                    continue
            elif feature_dir(repo, slug):
                continue
            else:
                try:
                    if now - os.stat(channel).st_mtime < TOPIC_GRACE:
                        continue
                except OSError:
                    continue
                log.warning("the worktree of %s/%s went without a clean-up — "
                            "its topic is left for deleting by hand", name, slug)
            if clear_channel(channel):
                log.info("the feature %s/%s is gone — its channel removed", name, slug)


def clear_channel(channel):
    # File by file rather than rmtree: a feature of the same name may have
    # begun while the topic was being deleted, and its question laid out here
    # (ask.json, and a mark set aside) keeps the directory. Everything else
    # goes, temporary leftovers of a killed writer included. Returns whether
    # the directory is gone.
    keep = ("ask.json",)
    closed = os.path.join(channel, asks.CLOSED_DIR)
    # Notes not yet sent go with the feature: their topic is going too.
    notes = os.path.join(channel, notices.NOTES_DIR)
    for d in (closed, notes, channel):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            path = os.path.join(d, name)
            if d == channel and (name in keep or name.startswith(ENDED_MARK + "-")):
                continue
            if os.path.isfile(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
    for d in (closed, notes, channel):
        try:
            os.rmdir(d)
        except OSError:
            pass
    return not os.path.exists(channel)


def end_feature(bot, name, slug, channel, mark):
    # The worktree's removal left the record in the mark. Its last question's
    # message is settled first — it may stand in the main chat, where no topic
    # takes it away — then the topic goes. False while the topic may still be
    # there: the mark stays, and the next turn tries again.
    try:
        with open(mark, encoding="utf-8") as fh:
            record = json.load(fh) or {}
    except (OSError, ValueError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    entry = record.get("shown")
    if isinstance(entry, dict) and entry.get("msg") and not entry.get("thread"):
        # In the main chat only: one in the topic goes with it, below.
        # Only with its closed record: the mark is a copy taken when the
        # worktree went, and the bot may have settled that message since —
        # consuming the record — in which case it is history now, not to be
        # deleted.
        closed = asks.closed_asks(channel).get(entry.get("id"))
        if closed:
            asks.settle_ask(bot, name, entry, closed[1])
        else:
            # Without the record there is no telling whether the message is
            # still the question or already its answer: its text stays, its
            # buttons go — they would answer nothing either way.
            bot.unbutton(entry["msg"])
    if isinstance(entry, dict):
        record.pop("shown")
        # Whole or not at all: the mark holds the only copy of the topic id.
        tmp = "%s.%d" % (mark, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(record, fh)
            os.replace(tmp, mark)
        except OSError:
            pass
    thread = record.get("thread") or 0
    if thread and not bot.delete_topic(thread):
        try:
            age = time.time() - os.stat(mark).st_mtime
        except OSError:
            age = 0
        if age < TOPIC_DELETE_FOR:
            return False
        log.warning("the topic %s of %s/%s would not go for a day — left for "
                    "deleting by hand", thread, name, slug)
    if thread:
        holding.forget_screen_place(thread)
    return True
