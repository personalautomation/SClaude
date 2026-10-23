#!/usr/bin/env python3
#
# The bot's menu as a Telegram Mini App: what the page behind the Menu button
# shows and does. An experiment — the chat menus stay as they are.
#
# The page is served by the gate (`sclaude-proxy --gate`, behind the funnel),
# which checks Telegram's signed initData on every call and only then asks this
# module. The page has no screens of its own: a press is handed to the chat's
# own Handler.callback as though it came from a menu message, and PageBot
# catches what the handler would do to that message — the edit becomes the
# page's next screen, a reply becomes a note under it. One handler for both,
# so the page and the chat can never disagree about what a button does.
#
# The page's message has the id PAGE (0): every helper that tracks a message
# by its id already treats 0 as "none", so nothing about the page is
# remembered as a chat message. What is not about that message — the anchor,
# the profile, a card posted to a feature's topic — goes to Telegram as usual.
#
# The language is the bot's: a choice pinned in Settings, otherwise the
# client's language_code from initData, remembered as a message would be.
import os
import re
import subprocess
import threading
import time

from keepawake import telegramd
from keepawake.i18n import current, t

PAGE = 0

# i18n keeps the language in a module global, and the gate answers calls from
# threads; one call at a time keeps a screen in one language.
_LOCK = threading.Lock()

# Buttons the page leaves out.
HIDDEN = ()

# The bot's unit, which the page's restart restarts: the chat's restart
# restarts the process it runs in, and here that is the gate.
BOT_UNIT = os.environ.get("KEEPAWAKE_UNIT") or "keepawake-telegram.service"


class PageBot(telegramd.Bot):
    def __init__(self, token, chat_id):
        super(PageBot, self).__init__(token, chat_id)
        self.screen = None
        self.notes = []
        # What the press did, when it did something: the text of its result.
        self.done = None
        # The page has nothing left to show: it closes after this answer.
        self.close = False
        # The feature the page stands on, when this press changed it.
        self.home = None
        # A press that started nothing after all.
        self.untraced = False

    def edit(self, message_id, text, keyboard=None):
        if message_id != PAGE:
            return super(PageBot, self).edit(message_id, text, keyboard)
        self.screen = (text, keyboard or [])
        return True

    def send(self, text, keyboard=None, quiet=False, thread=None):
        # A reply to the press (no topic named) is the page's; a message to a
        # topic is the chat's.
        if thread is not None:
            return super(PageBot, self).send(text, keyboard, quiet, thread)
        self.notes.append(text)
        return PAGE

    def answer(self, callback_id, text=None, alert=False):
        if text:
            self.notes.append(telegramd.escape(text))

    def ask(self, text, placeholder):
        return PAGE


class PageHandler(telegramd.Handler):
    def result(self, message_id, text):
        # In the chat a press that did something turns its menu into the
        # line saying what; on the page that line is the screen, and it is
        # also what the chat keeps of the press (trace).
        if message_id != PAGE:
            return super(PageHandler, self).result(message_id, text)
        self.bot.screen = (text, [])
        self.bot.done = text


# The note under a screen, by the press that led to it. A press that ends in
# a result (extended, started) shows what was done and needs none.
HELP = (("menu_extend", "help.keepawake"), ("awake_until", "help.until"),
        ("menu_code", "help.code"), ("code_", "help.code"),
        ("menu_chrome", "help.chrome"), ("svc_sclaude", "help.sclaude"),
        ("repo:", "help.sclaude"), ("svc_repos", "help.repos"),
        ("topic:", "help.card"), ("feat:", "help.card"), ("fc:", "help.card"),
        ("menu_services", "help.settings"), ("svc_lang", "help.lang"),
        ("lang:", "help.lang"), ("svc_docs", "help.docs"))


def help_for(action, done):
    if done is not None and not action.startswith(("code_", "lang:")):
        return ""
    if not action or action == "menu_back":
        return t("help.menu")
    for prefix, key in HELP:
        if action.startswith(prefix):
            return t(key)
    return ""


def rows_for_page(rows, main):
    """The keyboard without what the page cannot do, and with a way back
    from every screen but the menu itself."""
    out = [[b for b in row if b.get("callback_data") not in HIDDEN] for row in rows]
    out = [row for row in out if row]
    # A screen's own "Back" may lead one level up rather than to the menu;
    # either way it is the way back, and a second one would only confuse.
    if not main and not any(b.get("callback_data") == "menu_back"
                            or b.get("text") in (t("menu.back"), t("page.tocard"))
                            for row in out for b in row):
        out.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return out


def features():
    """[(key, name, slug, activity)] of every feature with a worktree, the
    latest sclaude activity first: its state's last change."""
    found = []
    for repo in telegramd.known_repos():
        name = os.path.basename(repo)
        for slug in telegramd.feature_records(repo):
            if not telegramd.feature_dir(repo, slug) \
                    or telegramd.closing(telegramd.feature_wt(repo, slug)):
                continue
            try:
                at = os.path.getmtime(os.path.join(telegramd.feature_wt(repo, slug),
                                                   ".sclaude", "local", "feature", "state.json"))
            except OSError:
                at = 0
            found.append((telegramd.channel_key(name, slug), name, slug, at))
    return sorted(found, key=lambda f: -f[3])


def guess_home():
    """The feature a page opened without one stands on: the one sclaude
    worked on last. The Menu button is the bot's, the same in every topic,
    and tells the page nothing of where it was pressed."""
    found = features()
    return found[0][0] if found else ""


def home_feature(home):
    """(name, slug) of the feature the page was opened on — from its topic —
    or None. Sclaude, Chrome and Code-server then stand on it: in a
    feature's topic the feature is already chosen."""
    name, slug = telegramd.split_key(home or "")
    repo = telegramd.repo_path(name) if slug else None
    return ((name, slug) if repo and telegramd.feature_dir(repo, slug)
            and not telegramd.closing(telegramd.feature_wt(repo, slug)) else None)


def feature_chrome(name, slug):
    """Chrome's screen for one feature: the laptop's browser — open the
    feature there, or close it — and the feature here. Its dev server starts
    when it is opened, and is started and stopped on its card."""
    key = telegramd.channel_key(name, slug)
    browser_up = telegramd.port_open(telegramd.CHROME_PORT)
    dev = telegramd.feature_dev(telegramd.repo_path(name), slug)
    rows = []
    if dev:
        label, _port, running = dev
        rows.append([{"text": t("page.onlaptop"), "callback_data": telegramd.card_data("open", key)}])
        if browser_up:
            rows.append([{"text": t("page.closechrome"), "callback_data": "chrome_stop"}])
        here = telegramd.phone_button(telegramd.gate_origin(), label)
        for b in here:
            b["text"] = t("page.onphone")
        if here:
            rows.append(here)
        state = t("chrome.running") if running else t("chrome.stopped")
    else:
        state = t("chrome.featnodev")
        if browser_up:
            rows.append([{"text": t("page.closechrome"), "callback_data": "chrome_stop"}])
    return t("chrome.featpage", state=t("chrome.up") if browser_up else t("chrome.down"),
             slug=telegramd.escape(slug), dev=state), rows


def channel_of(key):
    """The question channel of a feature, by its key; "" when it is gone."""
    # A feature's only: the repository's own channel is not a feature's.
    return telegramd.channel_dir(key) if telegramd.split_key(key or "")[1] else ""


def wait_question(channel, after, seconds=6):
    """The question sclaude asks next, waited for a few seconds: a press on
    the page is answered by its next screen, and sclaude takes a moment to
    ask. after: the id of the question just answered."""
    for _ in range(int(seconds * 2)):
        question = telegramd.pending_ask(channel)
        if question and (question.get("id") or "") != (after or ""):
            return question
        time.sleep(0.5)
    return None


# The actions sclaude offers on a feature (sclaude/lib/actions.sh), by the key
# each carries in brackets: where it leads. The rest stay on the current step.
ACT_BACK = ("replan", "return")
ACT_FORWARD = ("preview",)
ACT_AFTER = ("done",)
ACT_END = ("drop", "rollback")
ACT_KEY = re.compile(r"\(([a-z-]+)\)\s*$")
ACT_LINE = re.compile(r"^\s*(\d+)\)\s+(.+?)\s{2,}(.+)$")
STEP_OF = re.compile(r"step (\d)")


def is_actions(question):
    """Whether a question is sclaude's list of a feature's actions: a pick
    whose options carry their keys in brackets."""
    options = question.get("options") or []
    return sum(1 for o in options if ACT_KEY.search(str(o))) >= 3


def actions_screen(key, question):
    """The list of actions as a page screen: where the feature is, and the
    actions grouped by where each leads — back, staying, forward, after the
    merge, the end — each button saying what it does under its name."""
    name, slug = telegramd.split_key(key)
    qid = question.get("id") or ""
    hints = {}
    for line in (question.get("context") or "").splitlines():
        m = ACT_LINE.match(telegramd.strip_ansi(line))
        if m:
            hints[int(m.group(1))] = m.group(3).strip()
    feats, _ = telegramd.features_of_name(name)
    step = next((r[1] for r in feats if r[0] == slug), "")
    groups = {"back": [], "stay": [], "forward": [], "after": [], "end": []}
    first, cancel = None, None
    options = question.get("options") or []
    for i, label in enumerate(options, 1):
        label = telegramd.strip_ansi(str(label)).strip()
        m = ACT_KEY.search(label)
        verb = m.group(1) if m else ""
        b = {"text": ACT_KEY.sub("", label).strip(), "callback_data": "pa:%s:%d" % (qid, i)}
        if hints.get(i):
            b["hint"] = hints[i]
        if not verb and i == 1:
            first = b
        elif not verb and i == len(options):
            cancel = b
        elif verb in ACT_BACK:
            n = STEP_OF.search(hints.get(i, "") + " " + label)
            groups["back"].append((int(n.group(1)) if n else 0, b))
        elif verb in ACT_END:
            groups["end"].append((0, b))
        elif verb in ACT_AFTER:
            groups["after"].append((0, b))
        elif verb in ACT_FORWARD:
            groups["forward"].append((0, b))
        else:
            groups["stay"].append((0, b))
    if first:
        groups["forward"].insert(0, (0, first))
    rows = []
    current = int(re.match(r"(\d)", step).group(1)) if re.match(r"\d", step or "") else 0
    names = t("act.steps").split(" · ")
    for n, b in sorted(groups["back"], key=lambda g: g[0]):
        named = "%s · %s" % (n, names[n - 1]) if 1 <= n <= len(names) else str(n or "?")
        rows.append([{"text": t("act.reopen" if n and n == current else "act.back", n=named),
                      "style": "caption"}])
        rows.append([b])
    for group, caption in (("stay", "act.stay"), ("forward", "act.forward"),
                           ("after", "act.after"), ("end", "act.end")):
        if groups[group]:
            rows.append([{"text": t(caption), "style": "caption"}])
            rows += [[b] for _n, b in groups[group]]
    if cancel:
        rows.append([dict(cancel, text=t("act.cancel"))])
    # The six steps in a line, the feature's own marked: "4/6 done, …" is
    # step 4.
    at = re.match(r"(\d)/\d", step or "")
    names = list(names)
    if at and 1 <= int(at.group(1)) <= len(names):
        i = int(at.group(1)) - 1
        names[i] = "📍<b>%s</b>" % names[i]
    text = "%s\n%s\n%s" % (t("act.title", slug=telegramd.escape(slug)), " → ".join(names),
                           t("act.now", step=telegramd.escape(step)) if step else "")
    return text.strip(), rows


def question_screen(key, question):
    """A feature's open question as a page screen: its text and its buttons,
    each answering it from here."""
    name, _slug = telegramd.split_key(key)
    back = [{"text": t("page.tocard"), "callback_data": "topic:%s:%s" % telegramd.split_key(key)}]
    if not question:
        return t("page.waiting"), [[{"text": t("page.question"), "callback_data": "page_question"}],
                                   back]
    if is_actions(question):
        text, rows = actions_screen(key, question)
        return text, rows + [back]
    qid = question.get("id") or ""
    rows = []
    for row in telegramd.ask_keyboard(name, question):
        rows.append([dict(b, callback_data="pa:%s:%s" % (qid, b["callback_data"].split(":", 2)[2]))
                     for b in row if (b.get("callback_data") or "").startswith("answer:")])
    rows = [r for r in rows if r]
    text = telegramd.ask_text(name, question, in_topic=True)
    if not rows:
        text += "\n\n" + t("page.typed")
    return text, rows + [back]


def answer_page(key, qid, reply):
    """Answer the feature's open question from the page, if it is still the
    one shown, and show what sclaude asks next."""
    channel = channel_of(key)
    question = telegramd.pending_ask(channel) if channel else None
    if not question or (question.get("id") or "") != qid:
        text, rows = question_screen(key, question)
        return t("page.gone") + ("\n\n" + text if question else ""), rows
    if not telegramd.answer_ask(channel, reply, qid):
        return question_screen(key, telegramd.pending_ask(channel))
    shown = telegramd.option_label(question.get("options"), reply) or reply
    telegramd.log.info("the menu page answered %s: %s", key, reply)
    following = wait_question(channel, qid)
    if following:
        text, rows = question_screen(key, following)
        return t("page.answered", reply=telegramd.escape(shown)) + "\n\n" + text, rows
    name, slug = telegramd.split_key(key)
    return (t("page.answered", reply=telegramd.escape(shown)),
            [[{"text": t("page.tocard"), "callback_data": "topic:%s:%s" % (name, slug)}]])


def code_screen(home):
    """code-server's screen, opening on the page's feature when it has one."""
    feature = home_feature(home)
    folder = telegramd.feature_wt(telegramd.repo_path(feature[0]), feature[1]) if feature else ""
    return (telegramd.code_text(feature[1] if feature else ""),
            telegramd.code_keyboard(folder))


def press(bot, user, action, context, now, home=""):
    """Run one press; the card it leaves, if any, for the next one."""
    if action == "home_pick":
        # Which feature the menu stands on, or the whole machine.
        rows = [[{"text": "📍 " + slug, "callback_data": "home:" + key}]
                for key, _name, slug, _at in features()[:8]]
        rows.append([{"text": t("menu.machine"), "callback_data": "home:"}])
        bot.screen = (t("menu.pickhome"), rows)
        return ""
    if action.startswith("home:"):
        bot.home = home = action[5:]
        action = ""
    feature = home_feature(home)
    if not action or action == "menu_back":
        # The whole menu: the chat's own is only the way here.
        title = telegramd.menu_title()
        rows = telegramd.menu_keyboard()
        if feature:
            title += t("menu.here", slug=telegramd.escape(feature[1]))
        rows = rows + [[{"text": t("menu.otherhome") if feature else t("menu.choosehome"),
                         "callback_data": "home_pick"}]]
        bot.screen = (title, rows)
        return ""
    if feature and action == "svc_sclaude":
        # The topic's feature is the one: its card, not every repository.
        action = "topic:%s:%s" % feature
    if feature and action == "menu_chrome":
        bot.screen = feature_chrome(*feature)
        return telegramd.channel_key(*feature)
    if action == "menu_code":
        bot.screen = code_screen(home)
        return ""
    if action in ("code_start", "code_restart", "code_stop"):
        # The chat answers with a line; the page stays on the screen, which
        # once the server is up has its 📲 button.
        verb = action[5:]
        telegramd.run("systemctl --user %s code-server.service" % verb)
        for _ in range(10 if verb != "stop" else 0):
            if telegramd.code_running():
                break
            time.sleep(0.5)
        telegramd.log.info("the menu page: code-server %s", verb)
        bot.screen = code_screen(home)
        bot.done = bot.screen[0]
        return ""
    if action == "awake_until":
        # The chat asks with a second message and a reply box; the page has a
        # time field of its own, and the chat waits for nothing.
        bot.screen = (t("awake.askpage"), [])
        return ""
    if action.startswith("until:"):
        until_ts = telegramd.parse_hhmm(action[6:], now)
        if not until_ts:
            bot.screen = (t("awake.badtimepage"), [])
            return ""
        until = telegramd.hold_for(until_ts - now, now)
        telegramd.log.info("the menu page: until %s", until)
        bot.screen = (t("extended.plain", at=telegramd.local_for_lang(until)), [])
        bot.done = bot.screen[0]
        return ""
    if action == "phone_toggle" and telegramd.gate_origin(None, False):
        # Turning phone access off from the page closes the page with it.
        bot.screen = (t("svc.phoneoffask"), [
            [{"text": t("svc.phoneoffyes"), "callback_data": "phone_off"}],
            [{"text": t("menu.back"), "callback_data": "menu_services"}]])
        return ""
    if action == "phone_off":
        # The answer goes through the funnel being turned off: it has to
        # leave first. The funnel goes a moment later, and the page closes
        # itself; the Menu button is plain again at once.
        subprocess.Popen(["bash", "-c", "sleep 2; " + telegramd.FUNNEL_OFF],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for target in ({}, {"chat_id": bot.chat_id}):
            try:
                bot.call("setChatMenuButton", menu_button=telegramd.MENU_COMMANDS, **target)
            except Exception as exc:
                telegramd.log.warning("setChatMenuButton: %s", exc)
        # The commands follow: the funnel is about to go.
        bot.commands(online=False)
        telegramd.log.info("the menu page: phone access turned off")
        bot.screen = (t("chrome.gatedown"), [])
        bot.done = bot.screen[0]
        bot.close = True
        return ""
    if action == "svc_restart":
        # The chat's restart edits its message into "back online" from the
        # new process; the page's line in the chat is that message.
        said = telegramd.Bot(bot.token, bot.chat_id).send("📱 " + t("svc.restarting"),
                                                         thread=0)
        with telegramd.locked() as st:
            st["restart_notify"] = said
            st["restart_from_pid"] = 0
            st["restart_page"] = True
        subprocess.Popen(["bash", "-c", "sleep 1; systemctl --user restart " + BOT_UNIT],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        bot.screen = (t("svc.restarting"), [])
        return ""
    if action.startswith("doc:"):
        # The chat sends a section as a message of its own; the page shows it
        # as a screen, with the way back to the list.
        body = telegramd.docs.section(action[4:], current())
        if body:
            bot.screen = (body, [[{"text": t("menu.back"), "callback_data": "svc_docs"}]])
            return ""
    if action.startswith(("topic:", "feat:")):
        # The chat posts the card to the feature's topic; the page shows it.
        # On the feature the page stands on there is no list to go back to.
        _, name, slug = action.split(":", 2)
        name = name or os.path.basename(telegramd.repo_choice())
        bot.screen = telegramd.card(name, slug, in_topic=False)
        return telegramd.channel_key(name, slug)
    if action.startswith("fc:acts") or action == "page_question":
        # The actions are a question of sclaude's, and so is what follows
        # them: the page shows the feature's open question with its buttons
        # and answers it itself (answer_page), as the chat's buttons do.
        key = action.split(":", 2)[2] if action.count(":") == 2 else context
        channel = channel_of(key)
        name, slug = telegramd.split_key(key)
        if action.startswith("fc:acts") and channel and not telegramd.pending_ask(channel) \
                and telegramd.feature_busy(telegramd.repo_path(name), slug):
            # The step is at work: a second orchestrator is not started, as
            # the chat's card does not start one.
            bot.untraced = True
            bot.screen = telegramd.card(name, slug, note=t("feat.busy"), in_topic=False)
            return key
        if action.startswith("fc:acts") and channel and not telegramd.pending_ask(channel):
            telegramd.start_sclaude(telegramd.repo_path(telegramd.split_key(key)[0]),
                                    ["actions", telegramd.split_key(key)[1]])
            wait_question(channel, None)
        else:
            # Only shown: nothing was started, and the chat keeps no line.
            bot.untraced = True
        bot.screen = question_screen(key, telegramd.pending_ask(channel) if channel else None)
        return key
    if action.startswith("pa:"):
        _, qid, reply = action.split(":", 2)
        bot.screen = answer_page(context, qid, reply)
        return context
    if action.startswith("fc:") and action.count(":") == 1 and context:
        # A card button whose data had no room for the feature: the page
        # knows which card it stands on.
        action = "%s:%s" % (action, context)
    telegramd.log.info("the menu page: %s", action)
    PageHandler(bot).callback({"id": "", "data": action, "from": user,
                                     "message": {"message_id": PAGE}})
    if action.startswith("fc:"):
        return action.split(":", 2)[2] if action.count(":") == 2 else context
    return ""


# The card buttons that start something; the rest of a card's only redraw it.
CARD_ACTS = ("go", "acts", "open", "start", "stop", "code")
# A result longer than this is a screen (Chrome's, code-server's), and the
# chat keeps the button's name instead.
TRACE_MAX = 300
# Presses whose result is a screen however short: the language's shows what
# can be chosen, and the chat keeps the choice.
TRACE_LABEL = ("lang:",)


def trace(token, chat_id, action, label, done, context, now):
    """What the chat keeps of a press on the page: one line, marked 📱, in the
    main chat or in the topic of the feature the press was about. Nothing for
    a press that only showed something."""
    thread, text = 0, None
    if action.startswith("fc:") and action.split(":")[1] in CARD_ACTS:
        name, slug = telegramd.split_key(context)
        repo = telegramd.repo_path(name) if slug else None
        if repo:
            thread = telegramd.load_record(repo, slug).get("thread") or 0
        text = telegramd.escape(label) + ("" if thread else " — " + telegramd.escape(slug))
    elif done is not None:
        text = (done if len(done) <= TRACE_MAX and not action.startswith(TRACE_LABEL)
                else telegramd.escape(label))
        # A new feature's line goes where its questions will.
        if action.startswith("newfeat:"):
            thread = telegramd.new_topic_of(action.split(":", 1)[1])
    if not text:
        return
    bot = telegramd.Bot(token, chat_id)
    said = bot.send("📱 " + text, thread=thread)
    # A line about the hold is what holds now: the earlier ones about sleep
    # go, as they do after a press in the chat.
    if action.startswith(("awake:", "until:", "awake_forever")):
        telegramd.said_sleep(bot, said, telegramd.read().get("until_ts") or 0)
    elif action == "awake_release":
        telegramd.said_sleep(bot, said, now + telegramd.IDLE_SLEPT_KEEP)


def answer(token, chat_id, user, action, context, now, label="", home=""):
    """The page's one call: the screen after the press, as JSON-ready data."""
    with _LOCK:
        telegramd.remember_lang(user)
        bot = PageBot(token, chat_id)
        if not home and not action:
            # Opened by the Menu button, which does not know the topic.
            bot.home = home = guess_home()
        pressed_on = context
        telegramd.ON_PAGE = True
        try:
            context = press(bot, user, action, context, now, home)
        finally:
            telegramd.ON_PAGE = False
        if not bot.untraced:
            trace(token, chat_id, action, label, bot.done, context or pressed_on, now)
        # The card of the feature the page stands on — drawn by any of its
        # buttons, Refresh too — has no list of repositories to go back to.
        if bot.screen and context and home_feature(bot.home if bot.home is not None else home) \
                and context == (bot.home if bot.home is not None else home):
            bot.screen = (bot.screen[0], [r for r in bot.screen[1] if not any(
                (b.get("callback_data") or "").startswith("repo:") for b in r)])
        text, rows = bot.screen or (None, None)
        main = not action or action == "menu_back" or action.startswith("home:")
        return {
            "lang": current(),
            "main": main,
            # A press that changed nothing on its message leaves the screen.
            "text": text,
            "rows": rows_for_page(rows, main) if text is not None else None,
            "time": action == "awake_until" or text == t("awake.badtimepage"),
            "notes": bot.notes,
            "context": context,
            "close": bot.close,
            "help": help_for(action, bot.done) if text is not None else "",
            "home": bot.home,
        }
