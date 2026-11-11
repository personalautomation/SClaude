# keepawake's Telegram bot — sclaude's question-answer channel on the phone:
# the pending question, its message and keyboard, the answer written back, and
# what becomes of the message once the question is closed.
#
# Part of the bot that keepawake/telegramd.py runs.

import glob
import html
import json
import logging
import os
import re
import time

from keepawake.i18n import STRINGS, t
from keepawake.state import locked, read
from keepawake import menus, repos, sessions, status_report, topics, widgets


log = logging.getLogger("keepawake")


# --- sclaude's question-answer channel ---------------------------------------
#
# The orchestrator lays the question out as a file and waits for an answer from
# two places at once: the terminal where it was asked, and here. Whoever answers
# first has answered — which is why a step begun at the laptop continues from a
# phone without a restart, and the other way round.
#
# The channels live in the repository's .git/sclaude/: one for all worktrees, so
# a question is found even before the feature is created. The repository's own
# channel is that directory; each feature in progress has its own below it, in
# ask/<slug>/, so that features running in parallel can all ask at once. The
# format is in sclaude/lib/core/io.sh (ask_channel).
#
# A channel is named in the state by its key: the repository's name for the
# repository's channel, "<repository>/<slug>" for a feature's.


def ask_dir(repo):
    return os.path.join(repo, ".git", "sclaude")


def ask_channels(repo):
    """[(slug, directory)] — the repository's channel first, slug empty."""
    root = ask_dir(repo)
    found = [("", root)]
    try:
        names = sorted(os.listdir(os.path.join(root, "ask")))
    except OSError:
        return found
    for slug in names:
        path = os.path.join(root, "ask", slug)
        if not slug.startswith(".") and os.path.isdir(path):
            found.append((slug, path))
    return found


def feature_channels():
    """Every feature's channel directory, of every known repository."""
    return [channel for repo in repos.known_repos() for slug, channel in ask_channels(repo) if slug]


def channel_key(name, slug):
    return "%s/%s" % (name, slug) if slug else name


def split_key(key):
    name, _, slug = key.partition("/")
    return name, slug


def channel_dir(key):
    # The directory behind a key, or "" when the repository is not known.
    name, slug = split_key(key)
    repo = repos.repo_path(name)
    if not repo:
        return ""
    return os.path.join(ask_dir(repo), "ask", slug) if slug else ask_dir(repo)


def pending_ask(channel):
    # The channel's open question, or None. We read without locks: the file
    # is written through mv, that is it appears whole. JSON that will not parse
    # means "it is being rewritten right now" — we will come back on the next
    # turn.
    path = os.path.join(channel, "ask.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("prompt"):
        return None
    # A question outlives the one who asked it: sclaude was killed with Ctrl-C,
    # an ssh session dropped, the power went out — the file stays lying there.
    # Showing such a question means offering to answer where nobody is
    # listening: the answer lands in the channel and stays there for ever, while
    # the person waits for the step to have moved.
    #
    # So we ask whether the owner is alive. The orchestrator puts its own pid
    # into the question itself — for exactly this. Signal 0 does nothing, it only
    # checks that the process exists and is ours.
    pid = data.get("pid") or 0
    if pid:
        try:
            os.kill(int(pid), 0)
        except (OSError, ValueError, TypeError):
            log.info("an orphaned question in %s (pid %s is dead) — removing it",
                     channel, pid)
            try:
                os.unlink(path)
            except OSError:
                pass
            return None
    return data


# The labels of the options that mean a refusal, from i18n: "Go back" in the
# action list, "none, go back" in the feature picker. We match on the start of
# the string and in both languages — the list is drawn in English, but
# translations of it are still to come.
BACK_OPTIONS = tuple(text for key in ("option.back", "option.none")
                     for text in reversed(STRINGS[key]))


def is_back_option(label):
    if not label:
        return False
    low = label.strip().lower().lstrip("‹ ").strip()
    return any(low.startswith(b) for b in BACK_OPTIONS)


# The replies is_yes and is_no take in sclaude/lib/core/ui.sh, in any case.
YES_WORDS = ("y", "yes")
NO_WORDS = ("n", "no")


def option_in_range(question, reply):
    # Whether a reply to a pick:N question is one ask_once takes as an answer:
    # one of its N options in ASCII digits (int() would also take "+2", "1_0"
    # and other scripts' digits).
    reply = str(reply).strip()
    return bool(re.fullmatch(r"[0-9]+", reply)) and 1 <= int(reply) <= _pick_n(question)


def option_label(options, reply):
    options = options or []
    try:
        i = int(str(reply).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= i <= len(options):
        return str(options[i - 1])
    return ""


def answer_ask(channel, reply, want=None):
    # The answer to the orchestrator. We write through a temporary file and
    # rename: the reading side must not see half an answer.
    #
    # Returns False if the question is gone — it was answered in the terminal
    # while the person was looking at the buttons. Staying silent here will not
    # do: otherwise it is unclear why the press changed nothing.
    #
    # The answer carries the id of the question it answers. Without it an answer
    # is a bare "y" that fits any question, and the check above does not make it
    # one: between it and os.replace the terminal can answer, the question can
    # close and the next one can open. That window cost a worktree — "n" to
    # "Ship to production?" was still travelling when "Remove all of it?" was
    # asked, and the orchestrator took the stale reply for an answer to it. The
    # reading side compares the ids and drops what was meant for another
    # question.
    #
    # want: the id of the question the caller checked. The question read here
    # can already be the next one, and the answer is then refused rather than
    # stamped with that one's id.
    question = pending_ask(channel)
    if not question or (want and (question.get("id") or "") != want):
        return False
    d = channel
    tmp = os.path.join(d, "answer.json.%d" % os.getpid())
    try:
        os.makedirs(d, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"reply": reply, "id": question.get("id") or ""},
                      fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(d, "answer.json"))
    except OSError as exc:
        log.warning("the answer was not written to the channel: %s", exc)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


# --- what happens to a question's message ------------------------------------
#
# A question's message must not outlive the question with its buttons still on
# it. Once the question closes, the message becomes its answer — whether it was
# answered here, in the terminal, or by text — or, when nobody answered (the
# session died, the reply was refused and the question asked again), it is
# deleted. The state remembers which message shows which question under
# "ask_shown": the repository's name → the question's stamp, the message id, and
# what is needed to write the answer once the question itself is gone.
#
# How the question ended is told by the orchestrator in closed/<id>.json (see
# ask_closed in sclaude/lib/core/io.sh).

CLOSED_DIR = "closed"

# The question's prompt in its answered message. The context is not repeated
# there: it explained the question, and the answer no longer needs it.
ASK_PROMPT_MAX = 300


def closed_asks(channel):
    # The records of closed questions: id → (path, record).
    d = os.path.join(channel, CLOSED_DIR)
    found = {}
    try:
        names = os.listdir(d)
    except OSError:
        return found
    for name in names:
        # A leading dot is a record still being written.
        if name.startswith(".") or not name.endswith(".json"):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("id"):
            found[record["id"]] = (path, record)
    return found


def shown_asks():
    # Before the message id was kept the value was the bare stamp. Such a
    # question is still known as shown — it must not be sent twice — but its
    # message cannot be reached.
    found = {}
    for name, value in (read().get("ask_shown") or {}).items():
        found[name] = value if isinstance(value, dict) \
            else {"id": value, "msg": 0, "legacy": True}
    return found


# Where the message showing a channel's question is remembered. A feature's
# keeps it in the feature's record in its worktree (load_record), with its
# topic. The repository's own channel keeps it in the daemon's state
# ("ask_shown"), and so does a feature channel with no worktree — one removed by
# hand while a question was open — since otherwise the question would be sent
# again on every turn.

def in_worktree(key, repo=None):
    # repo when the caller has it: finding it again is a scan of $HOME.
    name, slug = split_key(key)
    if slug and repo is None:
        repo = repos.repo_path(name)
    return (repo, slug) if slug and repo and topics.feature_dir(repo, slug) else (None, None)


def get_shown(key, repo=None):
    repo, slug = in_worktree(key, repo)
    if repo:
        return topics.load_record(repo, slug).get("shown") or None
    return shown_asks().get(key)


def put_shown(key, entry, repo=None):
    # entry None forgets the channel's message.
    repo, slug = in_worktree(key, repo)
    if repo:
        record = topics.load_record(repo, slug)
        if entry:
            record["shown"] = entry
        else:
            record.pop("shown", None)
        topics.save_record(repo, slug, record)
        return
    with locked() as st:
        shown = st.get("ask_shown") or {}
        if entry:
            shown[key] = entry
        else:
            shown.pop(key, None)
        st["ask_shown"] = shown


def repo_keys(name, repo=None):
    """Every channel key of the repository: its own and its features'."""
    repo = repo or repos.repo_path(name)
    if not repo:
        return [name]
    return [channel_key(name, slug) for slug, _ in ask_channels(repo)]


def forget_ask(key, message_id, repo=None):
    # The question's message has been dealt with by whoever is calling: it was
    # edited into its answer here. The stamp stays — the question lingers in
    # the channel for up to a second, and without the stamp the next turn would
    # send it again — only the message is let go. Returns the entry, or None
    # when this message no longer shows the channel's question.
    entry = get_shown(key, repo)
    if not isinstance(entry, dict) or not message_id \
            or entry.get("msg") != message_id:
        return None
    put_shown(key, dict(entry, msg=0, answered=message_id), repo)
    return entry


def answer_shown(question, reply):
    """The answer as the person reads it, marked: the yes/no buttons' labels
    carry their own mark (✅ / ❌); any other answer gets the ✅ of
    "answered"."""
    reply = str(reply or "").strip()
    shown = option_label((question or {}).get("options"), reply)
    if not shown and ((question or {}).get("form") or "").startswith("yn"):
        if reply.lower() in YES_WORDS:
            return t("ask.yes")
        if reply.lower() in NO_WORDS:
            return t("ask.no")
    return "✅ " + (shown or reply or "—")


def answered_text(repo_name, question, reply, source=""):
    # The question and the answer it got, for the question's own message.
    # A number is shown as the option it chose and y/n as the buttons say it:
    # "3" says nothing a day later.
    question = question or {}
    prompt = clip(status_report.strip_ansi(question.get("prompt") or "").strip(), ASK_PROMPT_MAX)
    text = t("ask.answered", repo=status_report.escape(repo_name), prompt=status_report.escape(prompt),
             reply=status_report.escape(answer_shown(question, reply)))
    if source in ("tty", "stdin"):
        text += "\n<i>%s</i>" % t("ask.by.terminal")
    # What was printed before the question is what happened on the laptop;
    # it stays, folded, rather than going with the buttons.
    context = status_report.strip_ansi(question.get("context") or "").strip()
    if context:
        text += "\n<blockquote expandable>%s</blockquote>" % status_report.escape(clip(context, ANSWER_CONTEXT_MAX))
    return text


# How much of a question's context its answered message keeps.
ANSWER_CONTEXT_MAX = 1500


def settle_ask(bot, name, entry, record):
    # The question in entry has closed: its message becomes the answer, or
    # goes. An edit makes no sound, so a question that went out silently is
    # answered silently too.
    msg = entry.get("msg") or 0
    if not msg:
        return
    if record and record.get("reply") is not None:
        show_answered(bot, name, entry, record.get("reply"), record.get("from") or "")
    else:
        menus.retire(bot, msg)


def show_answered(bot, name, entry, reply, source=""):
    # The question's message becomes its answer: a widget's state, or a
    # message's text. entry is what put_shown kept, with the options shown.
    if entry.get("widget"):
        bot.widget_data(entry["msg"], widgets.state(answered_state(entry, reply, source)))
    else:
        bot.edit(entry["msg"], answered_text(name, entry, reply, source))


def ask_keyboard(repo_name, question):
    # Buttons by the answer's form, which the question itself declared (see ask
    # in ui.sh). There is no need to guess from the prompt's text: the caller
    # passes the form, and it arrives in the channel next to the question.
    form = (question.get("form") or "").strip()
    if form.startswith("yn"):
        # No first, so the button under a blind thumb is the one that
        # changes nothing. A yes/no question has no default any more (see ask
        # in ui.sh); "yn:yes" from an older sclaude gets the same order.
        yes = {"text": t("ask.yes"), "callback_data": "answer:%s:y" % repo_name}
        no = {"text": t("ask.no"), "callback_data": "answer:%s:n" % repo_name}
        return [[no, yes]]
    if form.startswith("pick:"):
        try:
            n = int(form.split(":", 1)[1])
        except ValueError:
            n = 0
        # The options' labels, if the question passed them (see ask_publish in
        # io.sh). With them a button says what it will do; without them, only
        # its number. The difference is not cosmetic: among the options there is
        # sometimes "drop the feature", and there is nothing to press blindly
        # there.
        options = question.get("options") or []

        # The ceiling differs for labelled and unlabelled buttons, and that is
        # not inconsistency but two different things.
        #
        # Eight is the limit for digits: they have to be checked against the
        # list in the text above the buttons, and by the ninth that check costs
        # more than typing the number by hand. A labelled button forces no
        # checking, it reads by itself, and one per line three times as many are
        # read comfortably.
        #
        # Verified in the field: the list of actions on a feature is nine
        # options, and with the old shared threshold it got no buttons at all —
        # the very thing it was all started for. Twenty-four leaves room both
        # beyond that and beyond the task list in pick_start, which stays text
        # (fifty-odd lines there).
        if 1 <= n <= 24 and len(options) == n:
            rows = []
            for i, label in enumerate(options, 1):
                text = status_report.strip_ansi(str(label)).strip()
                # An empty label is no label: better a number than an empty
                # button with nothing for the eye to land on.
                # We cut the tail rather than the middle as clip does: an
                # option's label carries its meaning at the start, and
                # "Drop the fea…" is clearer than
                # «Drop…ture».
                text = clip_bytes(text, 60)
                rows.append([{"text": text or str(i),
                              "callback_data": "answer:%s:%d"
                                               % (repo_name, i)}])
            return rows

        # Unlabelled ones are digits only, and only while they can be taken in
        # at a glance.
        if 1 <= n <= 8:
            rows, row = [], []
            for i in range(1, n + 1):
                row.append({"text": str(i),
                            "callback_data": "answer:%s:%d" % (repo_name, i)})
                if len(row) == 4:
                    rows.append(row); row = []
            if row:
                rows.append(row)
            return rows
    return []


# How much context we show above the question. Telegram's ceiling is 4096 bytes
# per message, and exceeding it is not a truncation but a refusal with a 400
# error: the question would not arrive at all, the step would stall, and the
# reason would not be visible from a phone. So we cut it ourselves, leaving room
# for the question itself and the markup.
ASK_CONTEXT_MAX = 2000


def clip(text, limit):
    # We cut the middle rather than the tail: both ends of a long output matter
    # — the start says what is going on, and the last lines stand right above
    # the question and most often are its reason.
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return text[:head] + "\n…\n" + text[-tail:]


# A numbered list's line: "  3)  Deploy a preview   this branch on…". Such lines
# are printed by align_columns, and in the terminal they are the list one chooses
# from. Next to labelled buttons they are the same list a second time.
NUMBERED = re.compile(r"^\s*\d+\)\s")


def clip_bytes(text, limit):
    # Telegram's ceiling on a button's text is in bytes, not characters.
    # Counting in characters works exactly up to the first non-ASCII one: 59
    # characters is 110 bytes, twice the ceiling. The labels are English today,
    # but BACK_OPTIONS already matches Russian, and translations of the list are
    # still to come.
    #
    # We cut by code points rather than by slicing bytes: a slice tears a
    # multi-byte character in half and hands back a broken string.
    if len(text.encode("utf-8")) <= limit:
        return text
    out = ""
    # -3 for the ellipsis: in UTF-8 it takes three bytes.
    for ch in text:
        if len((out + ch).encode("utf-8")) > limit - 3:
            break
        out += ch
    return out + "…"


def _pick_n(question):
    # How many options the form declared. Not a number means not a choice
    # either: there is then nothing to compare the label list's length against,
    # and zero honestly will not match.
    form = (question.get("form") or "").strip()
    if not form.startswith("pick:"):
        return -1
    try:
        return int(form.split(":", 1)[1])
    except ValueError:
        return -1


def ask_text(repo_name, question, in_topic=False, slug="", widget=False,
             context_max=ASK_CONTEXT_MAX):
    # widget: the caption above a widget whose buttons are every option
    # (ask_caption), labelled whenever labels could be found.
    body = ""

    # A question about a particular feature is shown with its card — the very
    # one that used to open on pressing a feature: links to the issue and the
    # PR, the step, the worktree, the session's state. There is nothing in the
    # orchestrator to assemble that with — whether the session is alive is known
    # to the bot, not to it — so the orchestrator only names the feature (the
    # feature field, see ask_publish in io.sh) and we build the card here.
    #
    # The usual "<repository> is asking" line is then unnecessary: the card starts
    # with the repository's and the feature's name, and repeating them means
    # pushing the buttons further down.
    # In the feature's topic the card is already there, just above.
    # slug is the channel's: a feature's question sent to the main chat for
    # want of a topic names its feature too.
    slug = "" if in_topic else ((question.get("feature") or "").strip() or slug)
    if slug:
        body += sessions.feature_card(repo_name, slug) + "\n\n"

    context = (question.get("context") or "").strip()
    # When the buttons are labelled, the numbered list above them is
    # redundant: it repeats them in digits and pushes down the very thing the
    # context is attached for — the lines that explain the question. We remove
    # the list specifically, not the whole context: above the action list stands
    # the line with the issue and the PR, and it is needed precisely because the
    # feature's card has stopped being a stop along the way.
    #
    # Without buttons the list stays: the answer is then a number, and there
    # would be nothing to check it against if the list were removed.
    #
    # Labelled ones, not just any: numeric buttons without the list are
    # meaningless — "3" says nothing until it is written next to it what the
    # third option is.
    named = len(question.get("options") or "") == _pick_n(question)
    if widget:
        named = bool(listed_options(question))
    if context and named and (widget or ask_keyboard(repo_name, question)):
        kept = [ln for ln in context.splitlines() if not NUMBERED.match(ln)]
        context = "\n".join(kept).strip()
    # The "feature · issue #N · PR #N" line is printed by the orchestrator
    # itself — it is for the terminal, where there is no card. Here there is a
    # card, and the same line stands below it as a second, more poorly set copy
    # of the same thing.
    if slug and context.startswith(slug):
        context = "\n".join(context.splitlines()[1:]).strip()
    if context:
        body += t("ask.context",
                  body=status_report.escape(clip(status_report.strip_ansi(context), context_max)))
    if slug:
        # The prompt itself in italics and without "<repository> is asking": the
        # repository and the feature are already named by the card a line
        # above.
        body += "<i>%s</i>" % status_report.escape(status_report.strip_ansi(question.get("prompt") or "").strip())
    else:
        body += t("ask.title", repo=status_report.escape(repo_name),
                  prompt=status_report.escape(status_report.strip_ansi(question.get("prompt") or "")))
    form = (question.get("form") or "").strip()
    if not form:
        body += "\n\n<i>%s</i>" % t("ask.text")
    elif form.startswith("pick:") and not widget and not ask_keyboard(repo_name, question):
        body += "\n\n<i>%s</i>" % t("ask.pick")
    return body


# --- a question as a widget (widget_html/ask.html) ----------------------------
#
# Every option of a choice is a button there, however many — paged, eight
# labels or forty digits a page — so a long list needs no typed number. The
# question itself is the caption above it; answered, the widget shows the
# answer and its buttons go. A question that wants typed text stays a message.

ASK_LABELS = {"yes": "ask.yes", "no": "ask.no", "use": "ask.use", "g": "ask.gone", "o": "msg.stale",
              "term": "ask.by.terminal", "busy": "widget.busy", "fail": "widget.failed"}
# Labels a page; each is cut to a button's 60 bytes, so a page stays well
# inside the state's 1024.
ASK_PAGE = 8
# Telegram's ceiling on a caption, in characters after the markup is parsed.
CAPTION_MAX = 1024
# A numbered line's number and text, its columns apart by two spaces or more.
NUMBERED_LINE = re.compile(r"^\s*(\d+)\)\s+(.*\S)")


# A typed answer's suggestion, "Branch name [<suggested>]: " (start.sh): an
# empty answer takes it, and the widget offers it as a button.
SUGGESTED = re.compile(r"\[([^\[\]]+)\]:?\s*$")


def suggested(question):
    """What a typed answer's question suggests, "" for none."""
    question = question or {}
    if (question.get("form") or "").strip():
        return ""
    m = SUGGESTED.search(status_report.strip_ansi(question.get("prompt") or ""))
    return m.group(1).strip() if m else ""


def widget_form(question):
    """Whether a widget can take the answer: yes/no, a choice, or a typed
    answer with a suggestion — typed text still answers it as a message."""
    return ((question or {}).get("form") or "").strip().startswith("yn") \
        or _pick_n(question) >= 1 or bool(suggested(question))


def listed_options(question):
    """The options' labels, cut to fit a button: the question's own, or else
    the numbered list printed above it (align_columns) when it numbers
    exactly its options; [] when neither is there."""
    n = _pick_n(question)
    if n < 1:
        return []
    options = question.get("options") or []
    if len(options) != n:
        found = {}
        for line in status_report.strip_ansi(question.get("context") or "").splitlines():
            m = NUMBERED_LINE.match(line)
            if m:
                found[int(m.group(1))] = re.sub(r"\s{2,}", " — ", m.group(2))
        if sorted(found) != list(range(1, n + 1)):
            return []
        options = [found[i] for i in range(1, n + 1)]
    return [clip_bytes(status_report.strip_ansi(str(o)).strip(), 60) or str(i)
            for i, o in enumerate(options, 1)]


def visible_length(text):
    # As Telegram counts a caption: the text the markup leaves, in UTF-16.
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    return len(plain.encode("utf-16-le")) // 2


def ask_caption(repo_name, question, in_topic=False, slug=""):
    """The question as a widget's caption, its context cut until it fits; None
    when even without the context it does not (a long card) — the question
    then goes as a message."""
    limit = ASK_CONTEXT_MAX
    while True:
        text = ask_text(repo_name, question, in_topic, slug, widget=True, context_max=limit)
        over = visible_length(text) - CAPTION_MAX
        if over <= 0:
            return text
        if limit <= 50:
            return None
        limit = max(50, limit - over - 10)


def ask_state(question):
    if ((question.get("form") or "").strip()).startswith("yn"):
        return {"y": 1}
    if suggested(question):
        return {"d": clip_bytes(suggested(question), 60)}
    labels = listed_options(question)
    if labels:
        return {"o": labels[:ASK_PAGE], "t": len(labels), "k": ASK_PAGE}
    return {"t": _pick_n(question)}


def answered_state(entry, reply, source=""):
    # Cut like a button: an option passed without being cut (no labels found
    # for the widget) could take the state past its 1024 bytes.
    return {"s": "a", "r": clip_bytes(answer_shown(entry, reply), 200),
            "f": 1 if source in ("tty", "stdin") else 0}


def shown_by_message(message_id):
    """(name, key, repo, entry) of the question a message shows, or showed
    until answered here; None when it shows none."""
    if not message_id:
        return None
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        for key in repo_keys(name, repo):
            entry = get_shown(key, repo) or {}
            if message_id in (entry.get("msg"), entry.get("answered")):
                return name, key, repo, entry
    return None


def widget_press(bot, raw, message_id, back=None):
    """A tap in a question's widget — ask:<reply>, or ask:p<n> for a page of
    labels: what to answer it with, and what to do after the answer. back(name)
    shows the repository's features: an answer leaving a list in the main chat
    leads back to what the person was leaving, as the message's button did."""
    arg = raw.partition(":")[2]
    found = shown_by_message(message_id)
    if not found:
        return widgets.state(widgets.STALE), lambda: menus.retire(bot, message_id)
    name, key, repo, entry = found
    if arg.startswith("p") and arg[1:].isdigit():
        page = int(arg[1:])
        labels = entry.get("options") or []
        return json.dumps({"q": page, "o": labels[page * ASK_PAGE:(page + 1) * ASK_PAGE]},
                          ensure_ascii=False, separators=(",", ":")), None
    if entry.get("answered") == message_id:
        # A second tap on a question just answered here: its state says so.
        return None, None
    channel = channel_dir(key)
    question = pending_ask(channel)
    form = ((question or {}).get("form") or "").strip()
    mark = (question.get("id") or question.get("asked") or 0) if question else None
    if not question or (not entry.get("legacy") and entry.get("id") != mark):
        # Answered at the laptop, or another question asked since: the loop
        # settles this message into what happened.
        return widgets.state({"s": "g"}), None
    if arg == "d" and suggested(question):
        arg = suggested(question)
    elif not (form.startswith("yn") and arg in ("y", "n")) \
            and not (form.startswith("pick:") and option_in_range(question, arg)):
        return None, None
    if not answer_ask(channel, arg, question.get("id")):
        return widgets.state({"s": "g"}), None
    forget_ask(key, message_id, repo)
    answer = widgets.state(answered_state(entry, arg))
    log.info("a widget answered the sclaude question from %s: %r", key, arg)
    leaving = back and not entry.get("thread") \
        and is_back_option(option_label(entry.get("options"), arg))

    def after():
        bot.widget_data(message_id, answer)
        if leaving:
            back(name)
    return answer, after


# --- the person at the terminal ----------------------------------------------
#
# A question always goes to the chat, but a sound is not always wanted. Working
# at the laptop itself, a person sees the question in the terminal and answers
# there — a notification at that moment only distracts from the very work the
# question was asked for.
#
# This much silence from the terminal counts as "the person has stepped away".
# Five minutes rather than half a minute: reading a long question with attached
# context or thinking over an answer, a person types nothing for a minute or two
# — and sits in front of the screen all that time. A mistake here costs
# differently in the two directions: a needless silent message will be seen when
# they pick up the phone, whereas a needless sound in the middle of the work is
# exactly what we are getting away from.
ASK_QUIET_AFTER = 300


def tty_of_pid(pid):
    # The process's controlling terminal, or None.
    #
    # Through tty_nr from /proc/<pid>/stat rather than `ps -o tty=`: that is one
    # file read without spawning a process, and the daemon comes here every
    # turn.
    #
    # tty_nr is exactly the device's st_rdev, so we compare the numbers
    # directly rather than assembling a name from major/minor: minor in Linux is
    # cut into two non-adjacent pieces, and unpacking it by hand lies.
    #
    # The process's name in stat sits in brackets and may itself contain
    # brackets and spaces, so we cut at the last ')' rather than the first.
    try:
        with open("/proc/%d/stat" % int(pid)) as fh:
            raw = fh.read()
        rdev = int(raw[raw.rindex(")") + 2:].split()[4])
    except (OSError, ValueError, IndexError, TypeError):
        return None
    if not rdev:
        return None          # started without a terminal: from the bot, from systemd
    try:
        names = os.listdir("/dev/pts")
    except OSError:
        return None
    for name in names:
        path = os.path.join("/dev/pts", name)
        try:
            if os.stat(path).st_rdev == rdev:
                return path
        except OSError:
            continue
    return None


def from_phone(pid):
    """Whether the process was started by a press on the phone."""
    try:
        with open("/proc/%d/environ" % int(pid), "rb") as fh:
            return b"\0SCLAUDE_FROM_PHONE=1\0" in b"\0" + fh.read()
    except (OSError, ValueError, TypeError):
        return False


def at_terminal(question):
    # Whether the person is sitting right now at the terminal that asked the
    # question.
    #
    # We look at atime, not mtime. That is not pedantry but the only variant
    # that works: a tty's mtime is moved by a program's output rather than a
    # person's input — and ask() itself, having printed the prompt (ui.sh, the
    # printf right after ask_publish), would immediately report "they were just
    # typing". Every question in a row would go out silent, those asked from the
    # bot included, that is the sign would work inside out. atime is moved only
    # by a successful read from the terminal, that is by what was really typed;
    # idle turns of `read -t "$ASK_POLL"` do not touch it, so while the person
    # is silent the sign honestly ages.
    #
    # We take not "the freshest of all" terminals, as the detector in
    # bin/keepawake does, but precisely the one where this conversation is
    # happening: a forgotten neighbouring tab and code-server's heartbeat have
    # nothing to do with this question, and a maximum over them would declare
    # the person present.
    #
    # Every non-answer here means "with sound": a missed notification is worse
    # than a needless one. No pid, stat will not read, there is no terminal at
    # all (tty_nr == 0 — started from the bot through setsid), the device is
    # already closed — in every case we do not see the person at a terminal,
    # which means they can only answer from the phone.
    #
    # A tab a press on the phone opened (SCLAUDE_FROM_PHONE in the asker's
    # environment, start_sclaude in sessions.py) is never the person's
    # terminal: they are on the phone. Its age would not tell — a new pty's
    # atime is the moment it was made, five minutes of silence from the start.
    pid = question.get("pid") or 0
    if from_phone(pid):
        return False
    tty = tty_of_pid(pid)
    if not tty:
        return False
    try:
        return time.time() - os.stat(tty).st_atime < ASK_QUIET_AFTER
    except OSError:
        return False


def channel_context(channel):
    """The lines an open question in the channel carries with it."""
    try:
        with open(os.path.join(channel, "ask.json")) as fh:
            ask = json.load(fh) or {}
    except (OSError, ValueError):
        return ""
    return "%s\n%s" % (ask.get("context") or "", ask.get("prompt") or "")


def check_asks(bot):
    # An orchestrator's open question is exactly what hot switching is.
    #
    # We look at every known repository rather than only the selected one: a
    # feature may have been started at the laptop in any of them, and a question
    # shown only in the "current" project would be half a promise.
    #
    # We show a question once: we check the stamp the orchestrator puts into
    # the question itself. The stamp is unique to each — comparing by time will
    # not do: two questions in a row fit into one second (branches.sh asks
    # "Delete them?" and immediately "Force-delete it?"), and we would consider
    # the second already shown. The step would stall silently, and from a phone
    # that looks like "the bot is not sending anything".
    #
    # It can be answered both from here and in the terminal: the first answer
    # clears the question, and the second source learns of it by the file's
    # disappearance. Its message then changes — see settle_ask.
    #
    # A feature's questions go to the feature's topic (feature_topic), so that
    # features running in parallel do not ask over one another in one stream.
    present = set()
    for repo in repos.known_repos():
        name = os.path.basename(repo)
        for slug, channel in ask_channels(repo):
            key = channel_key(name, slug)
            present.add(key)
            check_channel(bot, key, name, slug, channel, repo)
    # A feature gone while it waited for its topic leaves its try behind: the
    # daemon runs for weeks.
    for tried in [k for k in topics.TOPIC_TRIED if k not in present]:
        topics.TOPIC_TRIED.pop(tried, None)
    # A repository deleted or renamed will never close its question the usual
    # way. (A feature's message goes with its topic — see check_topics.)
    # Also a feature's entry kept in the state while it had no worktree: once a
    # worktree of that name exists, its record is read instead, and the state's
    # entry would never be settled.
    state_shown = shown_asks()
    stale = [k for k in state_shown if k not in present
             or (split_key(k)[1] and in_worktree(k)[0])]
    for key in stale:
        menus.retire(bot, state_shown[key].get("msg") or 0)
    if stale:
        # From the state directly: put_shown would write to a worktree that
        # has since appeared under the same name.
        with locked() as st:
            shown = st.get("ask_shown") or {}
            for key in stale:
                shown.pop(key, None)
            st["ask_shown"] = shown


def check_channel(bot, key, name, slug, channel, repo):
    # Marks of an earlier feature of the same name, set aside when the new one
    # began (ask_feature_begin): their topics go first — before the records
    # below are read, one of which may be that feature's last answer.
    if slug:
        for old in glob.glob(os.path.join(glob.escape(channel), topics.ENDED_MARK + "-*")):
            if topics.end_feature(bot, name, slug, channel, old):
                try:
                    os.unlink(old)
                except OSError:
                    pass
    question = pending_ask(channel)
    # A feature whose clean-up is through, or whose worktree is going: its
    # last message and its records are end_feature's (check_topics), which
    # settles them with the topic. The worktree goes before the mark is
    # written, and records read in between would be lost to it.
    if slug and not question and (os.path.exists(os.path.join(channel, topics.ENDED_MARK))
                                  or (not topics.feature_dir(repo, slug)
                                      and not shown_asks().get(key))):
        return
    # id is on questions laid out by this version; asked is the fallback key
    # for a question left over from the previous one (the daemon and the
    # orchestrator are updated separately, and they can diverge by one
    # restart).
    mark = (question.get("id") or question.get("asked") or 0) if question else None
    closed = closed_asks(channel)
    entry = get_shown(key, repo)
    # The shown question has closed — or another has taken its place between
    # two turns, as in "Delete them?" followed at once by "Force-delete it?".
    # Either way its message is settled before the next question goes out, so
    # the answer stands above the question that follows from it.
    if entry and entry.get("id") != mark:
        settle_ask(bot, name, entry, closed.get(entry.get("id"), (None, None))[1])
        put_shown(key, None, repo)
        entry = None
    # Every record is read once. The open question's own record stays: it is
    # written a moment before the question leaves the channel.
    for qid, (path, _) in closed.items():
        if qid != mark:
            try:
                os.unlink(path)
            except OSError:
                pass
    if not question or entry:
        return
    # Silent if the person is right now at the terminal where the question was
    # asked: they can already see it on the screen and will answer there. The
    # message goes out anyway — one can step away mid-step, and then it is
    # already waiting in the chat.
    # The repository's own questions while a feature is being started from the
    # bot are that feature's first ones: they go to its new topic.
    # Only a start from the bot: one at a terminal asks there, and its
    # repository's questions stay in the main chat — a bot start's tab on the
    # laptop is not such a terminal (from_phone). And only `sclaude new`'s:
    # the topic outlives a start given up, and another orchestrator's
    # question ("Which feature?") is the main chat's.
    thread = (topics.feature_topic(bot, name, slug) if slug
              else 0 if (tty_of_pid(question.get("pid")) and not from_phone(question.get("pid")))
              or not topics.asks_for_new(question.get("pid"))
              else topics.new_topic_of(name))
    # No topic though the feature has a worktree and topics are on: the
    # network or a rate limit. The next turn tries again — sent to the main
    # chat now, the question would stay there, mixed with other features'.
    if slug and not thread and topics.topic_pending(repo, slug, topics.TOPIC_TRIED, key):
        return
    if thread:
        topics.TOPIC_TRIED.pop(key, None)
    quiet = at_terminal(question)
    widget = widgets.enabled() and widget_form(question) \
        and ask_caption(name, question, slug=slug) is not None
    keyboard = ask_keyboard(name, question)

    def post(thread, in_topic):
        if widget:
            return bot.send_widget(widgets.code("ask", ASK_LABELS), widgets.state(ask_state(question)),
                                   ask_caption(name, question, in_topic, slug),
                                   quiet=quiet, thread=thread, above=True)
        return bot.send(ask_text(name, question, in_topic=in_topic, slug=slug), keyboard,
                        quiet=quiet, thread=thread)
    msg = post(thread, bool(thread))
    if not msg and thread and topics.topic_lost(bot):
        # The topic is gone — the person deleted it by hand. A new one is
        # made once; failing that the question goes to the main chat, since a
        # question that does not arrive stalls the step. Any other failure is
        # the network's: the topic is still there, and the next turn retries.
        if slug:
            thread = topics.feature_topic(bot, name, slug, renew=True)
        else:
            topics.drop_new_topic(name)
            thread = 0
        if thread:
            msg = post(thread, True)
        if not msg:
            # The main chat, with the card that names the feature.
            thread = 0
            msg = post(0, False)
    if not msg:
        return
    put_shown(key, {"id": mark, "msg": msg, "thread": thread,
                    "prompt": question.get("prompt") or "",
                    "form": question.get("form") or "",
                    # The labels the widget shows, found in the context too.
                    "options": (listed_options(question) if widget else None)
                    or question.get("options") or [],
                    "widget": widget}, repo)
    log.info("showed the sclaude question from %s: %r", key,
             (question.get("prompt") or "")[:60])
