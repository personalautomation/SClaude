#!/usr/bin/env python3
#
# The keepawake Telegram bot: extending the hold and service commands from a
# phone.
#
# One process does both things — sends the warning half an hour before sleep and
# receives button presses. There is no reason to separate them: the warning is
# the sending of a message rather than a computation, and everything needed to
# send it (the token, chat_id, HTTP with retries, the message id for a later
# edit) exists only here. A separate warning script would be a second instance
# of the same machinery and would still write warn_message_id to a shared
# file.
#
# The loop comes from getUpdates: with timeout=25 it returns control at least
# once every 25 seconds even in complete silence, which is an order of magnitude
# more precise than a thirty-minute threshold needs.
#
# Interactive things (sclaude, claude) are not brought in here and cannot be:
# they require a live TTY — they read arrow keys character by character from
# /dev/tty and draw the screen with ANSI codes. Termius and code-server are
# there for those, where the terminal is real. Only what fits into a command
# without a dialogue belongs here.
import collections
import datetime
import json
import logging
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keepawake import docs, state
from keepawake.i18n import DEFAULT, current, set_lang, ssh_holders, t
from keepawake.state import (HOLD_SECONDS, local_label, locked, needs_warning,
                             read, touch)

API = "https://api.telegram.org/bot%s/%s"

# A long getUpdates: it holds the connection while there are no updates and
# returns control as soon as something arrives.
POLL_TIMEOUT = 25

# The backoff ceiling. The network on a laptop drops regularly — that is normal,
# not a reason to die: restarting the daemon loses the offset and creates a
# spike of requests.
BACKOFF_MAX = 60

log = logging.getLogger("keepawake")


class Bot(object):
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = int(chat_id)
        self.offset = 0
        self.stopped = False

    # --- transport ----------------------------------------------------------

    def call(self, method, http_timeout=15, **params):
        # http_timeout is the ceiling for the socket, params["timeout"] is how
        # long Telegram holds the long poll. The values differ and must not be
        # confused: the socket has to outlive the long poll, otherwise every
        # empty poll would look like a dropped connection.
        try:
            return self._post(method, http_timeout, params)
        except urllib.error.HTTPError as exc:
            # A button's colour (`style`) is recent in the Bot API. Should
            # Telegram refuse it, the same message goes again without colours
            # rather than not at all.
            # Only a refusal that names the button: "message is not modified"
            # is a 400 as well, and taking it for this one stripped the colour
            # off a card that had simply not changed.
            styled = json.dumps(params.get("reply_markup") or {})
            try:
                reason = exc.read().decode("utf-8", "replace").lower()
            except Exception:
                reason = ""
            if exc.code != 400 or '"style"' not in styled \
                    or not any(w in reason for w in ("style", "button")):
                raise
            log.warning("%s refused a styled keyboard; sending it plain", method)
            params["reply_markup"] = unstyled(params["reply_markup"])
            return self._post(method, http_timeout, params)

    def _post(self, method, http_timeout, params):
        url = API % (self.token, method)
        data = urllib.parse.urlencode(
            {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
             for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=http_timeout) as resp:
            return json.load(resp)

    # --- messages -----------------------------------------------------------

    def send(self, text, keyboard=None, quiet=False):
        # quiet is a message without a sound. Not "do not send": it arrives and
        # sits in the chat, it simply does not buzz the phone. Needed where the
        # person is already looking at the same thing in the terminal — see
        # at_terminal.
        #
        # The string "true" rather than True: urlencode prints Python's bool
        # capitalised. The Bot API accepts that, but the documented form is
        # lower case, and there is no reason to rely on the parser's leniency.
        # When a sound is wanted we put None — call does not send such
        # parameters at all, so the request stays exactly as it was.
        try:
            out = self.call("sendMessage", chat_id=self.chat_id, text=text,
                            parse_mode="HTML",
                            disable_notification="true" if quiet else None,
                            reply_markup={"inline_keyboard": keyboard} if keyboard else None)
            return (out.get("result") or {}).get("message_id", 0)
        except Exception as exc:
            log.warning("did not send: %s", exc)
            return 0

    def ask(self, text, placeholder):
        # A question that expects text. The input box in a chat with a bot is
        # always there — the Bot API does not allow removing it — but usually a
        # person has no use for it here: everything is done with buttons.
        # ForceReply turns it from "sitting empty" into "type right here": the
        # cursor places itself, the phone's keyboard opens, and the placeholder
        # shows the expected format — that is, the box becomes visible exactly
        # when we have turned to it.
        #
        # A separate message rather than an edit of the previous one:
        # editMessageText's reply_markup is inline only, and ForceReply cannot go
        # there.
        try:
            out = self.call("sendMessage", chat_id=self.chat_id, text=text,
                            parse_mode="HTML",
                            reply_markup={"force_reply": True,
                                          "input_field_placeholder": placeholder})
            return (out.get("result") or {}).get("message_id", 0)
        except Exception as exc:
            log.warning("the question did not send: %s", exc)
            return 0

    def anchor(self, text):
        # A separate message with a reply keyboard — the one that lives below
        # the input box rather than inside a message. Inline buttons ride up
        # with their message as soon as a couple of imminent-sleep notifications
        # arrive; this one stays on the screen always, however much history
        # piles up.
        #
        # They cannot be combined in one message: a message has one
        # reply_markup, and it is either an inline_keyboard or a keyboard. So
        # the keyboard is set by its own message once at start-up and is then
        # held by the chat itself — Telegram remembers it until a replace or a
        # ReplyKeyboardRemove.
        try:
            self.call("sendMessage", chat_id=self.chat_id, text=text,
                      parse_mode="HTML",
                      reply_markup={"keyboard": [[{"text": t("menu.button")}]],
                                    "resize_keyboard": True,
                                    "is_persistent": True})
        except Exception as exc:
            log.warning("the keyboard did not appear: %s", exc)

    def commands(self):
        # The bot's commands: a second route to the menu, in case the reply
        # keyboard has been hidden. The button in the input box that Telegram
        # creates for them is removed by menu_button. Not critical — they must
        # not be a reason to die.
        try:
            self.call("setMyCommands", commands=[
                {"command": name, "description": t(key)}
                for name, (_method, key) in COMMANDS.items()
                if name != "start"])
        except Exception as exc:
            log.warning("setMyCommands: %s", exc)

    def menu_button(self):
        # Create commands and Telegram puts a blue button with their list on
        # the left of the input box by itself. The chat then had two entrances
        # to one menu: that button and the big one below the box. We give the
        # box its usual look back — "default" — and one menu is left. The
        # commands live on: /menu and /status are typed by hand and are
        # suggested when typing "/".
        #
        # A language mismatch goes away with it: Telegram takes the blue
        # button's caption from the phone's locale rather than from our strings,
        # and a Russian "Menu" caption used to hang over an English menu.
        try:
            self.call("setChatMenuButton", menu_button={"type": "default"})
        except Exception as exc:
            log.warning("setChatMenuButton: %s", exc)

    def edit(self, message_id, text, keyboard=None):
        try:
            self.call("editMessageText", chat_id=self.chat_id,
                      message_id=message_id, text=text, parse_mode="HTML",
                      reply_markup={"inline_keyboard": keyboard} if keyboard else None)
        except Exception as exc:
            log.warning("did not edit: %s", exc)

    def answer(self, callback_id, text=None, alert=False):
        # We answer first thing: Telegram gives about ten seconds for this,
        # otherwise a spinner hangs on the person's phone until the timeout.
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id,
                      text=text, show_alert=alert, http_timeout=10)
        except Exception as exc:
            log.warning("answerCallbackQuery: %s", exc)


# --- keyboards --------------------------------------------------------------

def unstyled(markup):
    """The same reply_markup with every button's colour taken off."""
    rows = [[{k: v for k, v in b.items() if k != "style"} for b in row]
            for row in markup.get("inline_keyboard") or []]
    return dict(markup, inline_keyboard=rows) if "inline_keyboard" in markup else markup


def menu_keyboard():
    return [
        [{"text": t("menu.extend"), "callback_data": "menu_extend"},
         {"text": t("menu.status"), "callback_data": "menu_status"}],
        [{"text": t("menu.chrome"), "callback_data": "menu_chrome"},
         {"text": t("menu.code"), "callback_data": "menu_code"}],
        [{"text": t("menu.sclaude"), "callback_data": "svc_sclaude"},
         {"text": t("menu.settings"), "callback_data": "menu_services"}],
    ]


# "Never sleep at all" is indefinite in words only: in the state it is an
# ordinary until_ts, merely a distant one. There is deliberately no separate
# "hold for ever" field — should_hold is duplicated in KeepAwake.ps1, and every
# new field would have to be created in two runtimes at once, at the risk of
# their diverging. A week is longer than any sensible session, and STALE_AFTER
# remains the insurance against a forgotten hold: a crashed WSL stops holding
# after fifteen minutes, however distant the deadline.
FOREVER_SECONDS = 7 * 24 * 3600


def host_name():
    # The machine's name in the menu header: the bot may have more than one
    # laptop, and the first thing to know before pressing "sleep" is which of
    # them will answer. We take the Windows machine's name (hostname in WSL
    # returns exactly that) rather than the node's name in the tailnet: they
    # have different names, and a person recognises their own hardware by the
    # first.
    try:
        import socket
        return socket.gethostname() or "keepawake"
    except Exception:
        return "keepawake"


def is_menu_button(text):
    # The keyboard below the input box was set once and labelled in the
    # language of that moment. The language may have changed since — Telegram
    # reports it in every update — while the person's old button stayed as it
    # was. So we compare against both variants rather than the current one.
    from keepawake.i18n import STRINGS
    return text in STRINGS["menu.button"]


def menu_title():
    return t("menu.title", host=escape(host_name()))


def awake_keyboard():
    return [
        [{"text": t("awake.h1"), "callback_data": "awake:3600"},
         {"text": t("awake.h2"), "callback_data": "awake:14400"},
         {"text": t("awake.h3"), "callback_data": "awake:86400"}],
        [{"text": t("awake.until"), "callback_data": "awake_until"}],
        [{"text": t("awake.forever"), "callback_data": "awake_forever"}],
        [{"text": t("awake.release"), "callback_data": "awake_release"}],
        [{"text": t("menu.back"), "callback_data": "menu_back"}],
    ]


def awake_text():
    # We show the current deadline: a person makes the "one hour or three"
    # choice knowing how much there already is, otherwise extending blind turns
    # into guesswork.
    data = read()
    now = int(time.time())
    until = data.get("until_ts") or 0
    if until <= now:
        return t("awake.title.free")
    text = t("awake.title", until=escape(local_for_lang(data.get("until_local") or "")))
    # We say the manual deadline outright: "holding until 23:00" with a single
    # live claude looks inexplicable otherwise, and the person is deciding
    # whether to extend further as well. We also answer at once what comes after
    # — the usual hour returns.
    if state.manual_until(data, now):
        text += t("awake.manual")
    return text


def hold_for(seconds, now):
    # The shared tail of every extension: move the deadline, lift the previous
    # refusal and mark the heartbeat. We lift the refusal because the person has
    # just changed their mind — otherwise the detector would see "they asked for
    # sleep" a minute later and would not extend any further.
    with locked() as st:
        state.extend(st, now, seconds, manual=True)
        state.touch(st, now)
        st["decision"] = ""
        st["decision_ts"] = 0
        st["awaiting"] = ""
        return st["until_local"]


def release_hold(now):
    # A mirror of hold_for: that one moves the deadline forward, this one drops
    # the hold entirely — both the deadline and the hard one — and sets the
    # refusal. The refusal is essential: without it the detector would see a
    # live SSH session a minute later and extend back what the person has just
    # dropped. Windows counts the idling itself from then on.
    #
    # One place for all three entrances — the button in the sleep submenu, "let
    # it sleep" in the question about forgotten holders, and the /sleep command
    # — because the order of the fields here is not obvious, and copies that
    # diverged would give a hold released by halves.
    with locked() as st:
        st["until_ts"] = now
        st["until_local"] = local_label(now)
        st["hard_hold"] = False
        st["decision"] = "sleep"
        st["decision_ts"] = now
        state.drop_manual(st)
        touch(st, now)


def parse_hhmm(text, now):
    # "until 23:30" is today's time; if it has already passed, tomorrow was
    # meant. Otherwise a "stay awake until 7:00" sent at night would mean a
    # deadline in the past, that is instant sleep.
    m = re.match(r"^(\d{1,2})[:.\s](\d{2})$", text.strip())
    if not m:
        return 0
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return 0
    now_dt = datetime.datetime.fromtimestamp(now)
    target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_dt:
        target += datetime.timedelta(days=1)
    return int(target.timestamp())


def chrome_keyboard():
    # The list of features first, then one block per feature:
    # every feature has a dev server of its own now, so "the dev server" no
    # longer names anything. 🌐 opens the feature in the laptop's Chrome —
    # a stopped one is started by sclaude-proxy on that very request — and ⏹
    # stops a running one, its database with it.
    browser_up = port_open(CHROME_PORT)
    origin = gate_origin() if gate_running() else ""

    def phone(label):
        # Two looks for two presses: a plain 🔒 that only opens the door, then
        # a green 📲 that is the Mini App — so the button itself says that the
        # first press does not show the page yet, and the second will.
        if origin:
            return {"text": t("chrome.phoneopen"), "style": "success",
                    "web_app": {"url": "%s/__sclaude/tg?f=%s" % (origin, label)}}
        return {"text": t("chrome.phone"), "callback_data": "devphone:" + label}

    # The list of every feature first, laid out like a feature: a caption,
    # then where to open it. 🌐 is the laptop's Chrome at localhost:3000,
    # started if it is down; ⏹ closes that Chrome, and only while it runs.
    rows = [[{"text": t("chrome.all"), "callback_data": "noop"}]]
    first = [{"text": t("chrome.open"), "callback_data": "chrome_start"}, phone("")]
    if browser_up:
        first.append({"text": t("chrome.stopbrowser"), "callback_data": "chrome_stop"})
    rows.append(first)
    # The phone button opens the feature inside Telegram. While the gate is
    # down it is a callback that brings the gate up; once it is up, the same
    # button is the Mini App itself — a second press, but nothing is on the
    # internet before the first.
    for label, _wt, _port, running in dev_features()[:FEATURE_ROWS]:
        # Telegram refuses callback data over 64 bytes; a feature with a name
        # that long is listed in the text and simply has no buttons.
        if len("devphone:" + label) > 64:
            continue
        # The name gets a row of its own, a caption like the browser's: on a
        # phone's width a button that carries both the name and an action cuts
        # the name off, and a bare 📱 next to it said nothing of what it does.
        rows.append([{"text": label, "callback_data": "noop"}])
        row = [{"text": t("chrome.open"), "callback_data": "devopen:" + label}, phone(label)]
        if running:
            row.append({"text": t("chrome.featstop"), "callback_data": "devstop:" + label})
        else:
            row.append({"text": t("chrome.start"), "callback_data": "devstart:" + label})
        rows.append(row)
    if origin:
        rows.append([{"text": t("chrome.gateclose"), "callback_data": "gate_stop"}])
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


def services_keyboard():
    return [
        [{"text": t("svc.repos"), "callback_data": "svc_repos"},
         {"text": t("svc.docs"), "callback_data": "svc_docs"}],
        [{"text": t("svc.lang"), "callback_data": "svc_lang"},
         {"text": t("svc.restart"), "callback_data": "svc_restart"}],
        [{"text": t("menu.back"), "callback_data": "menu_back"}],
    ]


def lang_keyboard():
    # We mark the current choice with a dot — the same as the selected
    # repository.
    data = read()
    pinned = bool(data.get("lang_pinned"))
    now = current()
    def mark(on, text):
        return ("● " if on else "") + text
    return [
        [{"text": mark(pinned and now == "ru", t("lang.ru")),
          "callback_data": "lang:ru"},
         {"text": mark(pinned and now == "en", t("lang.en")),
          "callback_data": "lang:en"}],
        [{"text": mark(not pinned, t("lang.auto")), "callback_data": "lang:auto"}],
        [{"text": t("menu.back"), "callback_data": "menu_services"}],
    ]


def lang_text():
    data = read()
    name = t("lang.name." + current())
    if data.get("lang_pinned"):
        now = name
    else:
        now = t("lang.auto.now", what=name)
    return t("lang.title", now=now)


def code_running():
    out = run("systemctl --user is-active code-server.service")
    return out.strip() == "active"


def code_url():
    # We take the address from the config rather than a constant: it is tied to
    # the address in the tailnet, and if that changes the message must change it
    # too.
    path = os.path.expanduser("~/.config/code-server/config.yaml")
    try:
        for line in open(path):
            if line.strip().startswith("bind-addr:"):
                return "http://" + line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "http://localhost:8080"


# The port sclaude-proxy holds (bin/sclaude-proxy): every feature is
# http://<feature>.localhost:3000 through it, and a bare localhost:3000 is the
# list of features. chrome-debug opens that by default.
DEV_PORT = 3000
CHROME_PORT = int(os.environ.get("CHROME_DEBUG_PORT", "9222"))
# Where sclaude registers each feature's tree for the proxy: one symlink per
# feature, the tree's .sclaude/local/feature/state.json holding its port.
DEV_REGISTRY = os.path.expanduser("~/.claude/sclaude/dev")
# More rows than this and the card stops fitting a phone's screen.
FEATURE_ROWS = 8


def dev_features():
    """[(label, worktree, port, running)] for every registered feature.

    Read the way the proxy reads it — the registry and each tree's state —
    so the card and the proxy cannot disagree about what exists."""
    out = []
    try:
        names = sorted(os.listdir(DEV_REGISTRY))
    except OSError:
        return out
    for name in names:
        link = os.path.join(DEV_REGISTRY, name)
        if name.startswith(".") or not os.path.islink(link):
            continue
        wt = os.path.realpath(link)
        try:
            with open(state_path(wt)) as fh:
                port = (json.load(fh).get("dev") or {}).get("port")
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(port, int):
            continue
        out.append((name, wt, port, port_open(port)))
    return out

# This much silence counts as "the person left without closing the session".
# The value must match IDLE_AFTER in bin/keepawake, which measures it.
IDLE_SECONDS_THRESHOLD = 3600

# The value with which the detector marks "no interactive sessions at all".
# Must match the placeholder in idle_seconds() from bin/keepawake.
IDLE_UNKNOWN = 999999


def port_open(port, host="127.0.0.1"):
    import socket
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def wsl_ip():
    # WSL's address in the Windows network. It changes on every restart of WSL,
    # so it is read afresh each time the card is shown rather than
    # remembered.
    out = run("ip -4 -o addr show eth0")
    for part in out.split():
        if part.count(".") == 3 and "/" in part:
            return part.split("/")[0]
    return ""


def phone_origin():
    """Where a phone opens features: the `tailscale serve` HTTPS name when it
    fronts the proxy's port, the node's tailnet address otherwise.

    The name is worth preferring, not merely nicer. The page opens on either,
    but only the name survives a sign-in: in development the app sends a person
    back to the address they came from, and Supabase Auth refuses to redirect
    to an IP whatever its allow-list says. HTTPS also makes the page a secure
    context, which push notifications need."""
    try:
        config = json.loads(run("tailscale serve status --json", timeout=10) or "{}")
    except ValueError:
        config = {}
    for hostport, web in (config.get("Web") or {}).items():
        handler = ((web or {}).get("Handlers") or {}).get("/") or {}
        if str(handler.get("Proxy", "")).rstrip("/").endswith(":%d" % DEV_PORT):
            host, _, port = hostport.rpartition(":")
            return "https://%s" % host if port == "443" else "https://%s:%s" % (host, port)
    # The node's address, from code-server's config as everywhere in this bot.
    host = code_url().split("//")[1].split(":")[0]
    return "http://%s:%d" % (host, DEV_PORT)


# The phone's entry from the internet, for a phone without Tailscale: the
# gate (`sclaude-proxy --gate`) behind `tailscale funnel` on this port, up only
# while sclaude-gate.service runs — the 📱 button starts it, and it ends itself
# once nobody looks.
GATE_UNIT = "sclaude-gate.service"
GATE_FUNNEL_PORT = 8443


def gate_running():
    return run("systemctl --user is-active " + GATE_UNIT).strip() == "active"


def gate_origin():
    """https://<node>.<tailnet>.ts.net:8443, or "" when Tailscale cannot say."""
    try:
        status = json.loads(run("tailscale status --json", timeout=10) or "{}")
    except ValueError:
        return ""
    name = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    return "https://%s:%d" % (name, GATE_FUNNEL_PORT) if name else ""


def proxy_start(label):
    """Ask the proxy to start the feature now — for ▶️, and for 📱 while the
    phone is still opening, where the first request would, but later. It goes
    through the proxy rather than `sclaude dev` so that the proxy knows it is
    starting and shows that page meanwhile. Not followed: the answer is
    a redirect to <label>.localhost, which is nothing to fetch from here."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", DEV_PORT, timeout=5)
        conn.request("GET", "/__sclaude/start?f=" + urllib.parse.quote(label))
        conn.getresponse().read()
        conn.close()
    except (OSError, http.client.HTTPException):
        pass


def chrome_text():
    # We remind of the features' addresses: the Chrome window stands on the
    # laptop, and from a phone a person needs not so much the browser itself as
    # the link a feature opens at.
    state_label = t("chrome.up") if port_open(CHROME_PORT) else t("chrome.down")
    proxy_label = t("chrome.proxyup") if port_open(DEV_PORT) else t("chrome.proxydown")
    # From a phone: the tailnet, which has no *.localhost to name a feature
    # by, so the link goes through the proxy's own page that picks the feature
    # with a cookie.
    phone = phone_origin()
    # From the laptop: the feature's own name. Telegram makes no link of
    # localhost in any form, so it is shown to copy rather than to tap.
    lines = []
    for label, _wt, _port, running in dev_features():
        link = "%s/__sclaude/select?f=%s" % (phone, label)
        lines.append(t("chrome.feature",
                       link='<a href="%s">%s</a>' % (link, label),
                       state=t("chrome.running") if running else t("chrome.stopped"),
                       local="http://%s.localhost:%d" % (label, DEV_PORT)))
    features = "\n".join(lines) if lines else t("chrome.nofeatures")
    gate = t("chrome.gateup") if gate_running() else t("chrome.gatedown")
    return t("chrome.title", state=state_label, proxy=proxy_label, gate=gate,
             features=features, port=CHROME_PORT)


def code_folder():
    # Which directory the server will open at its next start — the same choice
    # as sclaude's: keeping two different "current projects" would confuse a
    # person who has switched one and expects the second to have switched
    # too.
    choice = repo_choice()
    return os.path.basename(choice) if choice else "~"


def code_keyboard():
    running = code_running()
    row = []
    if running:
        row.append({"text": t("code.restart"), "callback_data": "code_restart"})
        row.append({"text": t("code.stop"), "callback_data": "code_stop"})
    else:
        row.append({"text": t("code.start"), "callback_data": "code_start"})
    return [row, [{"text": t("menu.back"), "callback_data": "menu_back"}]]


def code_text():
    state_label = t("code.running") if code_running() else t("code.stopped")
    # There are two addresses, and that is not duplication. Tailscale runs
    # inside WSL, so the tailnet address lives on its interface: a phone reaches
    # it through the tunnel, while Windows itself does not — it is not in the
    # tailnet. For Windows there is localhost, which WSL2 forwards into Windows
    # by itself.
    # We do not put the password here: it would settle in the chat's history
    # and on Telegram's servers for ever, while the browser remembers it anyway
    # after the first login.
    # 127.0.0.1 rather than localhost: Telegram makes a link of what looks like
    # a domain or an IP, and localhost does not qualify — it stays text even
    # inside an explicit <a href>, which is additionally rejected with a 400
    # error. To the Windows browser the addresses are equivalent, and only this
    # one is clickable.
    return t("code.title", state=state_label,
             folder=t("code.folder", name=escape(code_folder())),
             url=code_url(), local="http://127.0.0.1:8080")


def warn_keyboard(until_ts):
    # The deadline stamp inside callback_data is what tells a fresh press from
    # a press on yesterday's message. Without it the "Extend" button from an old
    # notification would extend the hold at an arbitrary moment the next day.
    return [[
        {"text": t("sleep.extend"), "callback_data": "extend:%d" % until_ts},
        {"text": t("sleep.let"), "callback_data": "sleep:%d" % until_ts},
    ]]


# --- commands ---------------------------------------------------------------

# ~/.local/bin, where keepawake, chrome-debug and sclaude live, is not in the
# daemon's PATH: systemd gives a bare system PATH rather than the one an
# interactive shell assembles from ~/.profile. From the terminal the commands
# were found, from under the service they were not, and every button answered
# "not found".
LOCAL_BIN = os.path.expanduser("~/.local/bin")


def nvm_bin():
    # npm and node live in the directory of nvm's active version, which is not
    # in the service's PATH: an interactive shell assembles it from
    # ~/.nvm/nvm.sh. Without this `sclaude dev` died with "setsid: failed to
    # execute npm".
    #
    # We read the version from ~/.nvm/alias/default rather than hardcoding it:
    # otherwise updating Node would quietly break the button until the next edit
    # of the code.
    base = os.path.expanduser("~/.nvm/versions/node")
    alias = os.path.expanduser("~/.nvm/alias/default")
    try:
        want = open(alias).read().strip()
    except OSError:
        want = ""
    try:
        candidates = os.listdir(base)
    except OSError:
        return ""
    if not candidates:
        return ""

    def version_key(name):
        # By numbers rather than by letters: sorted() puts "v9.11.2" above
        # "v24.20.0", and the fallback branch would silently pick an ancient
        # Node. That branch is not hypothetical — here alias/default equals
        # "lts/*", which matches no directory by prefix.
        parts = []
        for chunk in name.lstrip("v").split("."):
            parts.append(int(chunk) if chunk.isdigit() else 0)
        return parts

    # We resolve "lts/*" and other aliases through ~/.nvm/alias/, otherwise
    # they would never match a directory name.
    if want.startswith("lts/"):
        try:
            want = open(os.path.expanduser("~/.nvm/alias/" + want)).read().strip()
        except OSError:
            want = ""

    for name in sorted(candidates, key=version_key, reverse=True):
        if want and (name == want or name.lstrip("v").startswith(want.lstrip("v"))):
            return os.path.join(base, name, "bin")
    return os.path.join(base, max(candidates, key=version_key), "bin")


def run(cmd, timeout=25):
    # The bot's commands are short and free of dialogue; anything longer has no
    # place here.
    env = dict(os.environ)
    parts = [LOCAL_BIN]
    nvm = nvm_bin()
    if nvm:
        parts.append(nvm)
    env["PATH"] = ":".join(parts) + ":" + env.get("PATH", "")
    # In a session of its own, and the whole group killed on a timeout:
    # subprocess.run kills only the shell it started, and whatever the shell
    # was running (`cd … && sclaude status`) lived on as an orphan, still
    # counted as "another sclaude" by every later run.
    try:
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env,
                                start_new_session=True)
    except Exception as exc:
        return t("cmd.error", err=exc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.communicate()
        return t("cmd.timeout", sec=timeout)
    except Exception as exc:
        return t("cmd.error", err=exc)
    text = (stdout or "") + (stderr or "")
    return text.strip() or t("cmd.empty")


def uptime_of(pid):
    try:
        with open("/proc/%d/stat" % pid) as fh:
            # Field 22 (starttime) is in ticks since the system booted. The
            # command's name in brackets may contain spaces, so we cut at ")".
            fields = fh.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])
        hz = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as fh:
            up = float(fh.read().split()[0])
        return max(0, int(up - ticks / hz))
    except Exception:
        return 0


def report_restart(bot):
    # After a restart, report into the same message that the daemon is alive
    # again. It is a new process that does this, so it reads the errand from the
    # state. Returns True if the report happened: the caller judges by that
    # whether to write to the chat for the keyboard's sake as well.
    data = read()
    mid = data.get("restart_notify") or 0
    if not mid:
        return False
    old = data.get("restart_from_pid") or 0
    if old == os.getpid():
        return False    # the same process: the restart has not happened yet
    with locked() as st:
        st["restart_notify"] = 0
        st["restart_from_pid"] = 0
    bot.edit(mid, t("svc.restarted"), services_keyboard())
    log.info("reported the restart in message %s", mid)
    # Editing an old message does not set the keyboard below the input box:
    # editMessageText's reply_markup is inline only. We set it separately.
    ensure_anchor(bot)
    return True


def ensure_anchor(bot):
    # We set the keyboard once per chat rather than at every start: the daemon
    # restarts both by a button in the menu and with the system, and an "I have
    # started" on every restart is noise in the chat, which the bot was built not
    # to create. We keep the mark in the state alongside everything else that
    # survives a restart.
    if read().get("anchor_lang") == current():
        return
    # In two messages, because a message has one reply_markup: the first
    # carries the keyboard below the input box, the second the menu itself.
    # Showing a bare header without buttons and making someone press "Menu" for
    # what is already on the screen is an extra step in exactly the place where
    # the person came for the menu anyway.
    bot.anchor(t("anchor.hint"))
    bot.send(menu_title(), menu_keyboard())
    with locked() as st:
        st["anchor_lang"] = current()
    log.info("the menu keyboard is set, language=%s", current())


def relabel_anchor(bot):
    # Relabel the keyboard after a change of language — in one message rather
    # than two: the person can see the menu anyway, they have just pressed a
    # button in it. It cannot be replaced silently, a keyboard only arrives with
    # a message.
    if read().get("anchor_lang") == current():
        return
    bot.anchor(t("anchor.hint"))
    with locked() as st:
        st["anchor_lang"] = current()
    log.info("the keyboard was relabelled, language=%s", current())


# The repositories whose features the bot can show. We search once per call:
# there are not many directories in $HOME, and projects do not lie deeper than
# the first level.
def known_repos():
    home = os.path.expanduser("~")
    found = []
    try:
        names = sorted(os.listdir(home))
    except OSError:
        return found
    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(home, name)
        if os.path.isdir(os.path.join(path, ".git")):
            found.append(path)
    return found


def repo_choice():
    # The choice lives in the state: the daemon survives restarts, and it has
    # nowhere else to remember which project the person looked at last.
    data = read()
    choice = data.get("sclaude_repo") or ""
    # The repository may have been renamed or deleted — the choice is then
    # invalid.
    if choice and os.path.isdir(os.path.join(choice, ".git")):
        return choice
    return ""


def repo_path(name):
    # Only a name from the list of known repositories. The name arrives in
    # callback_data and, although shlex.quote below stops it from executing as a
    # command, relying on escaping alone is unwise: checking against the list
    # closes off both directory traversal ("../..") and any future places this
    # name may end up in.
    for repo in known_repos():
        if os.path.basename(repo) == name:
            return repo
    return ""


def features_of_name(name):
    path = repo_path(name)
    if not path:
        return [], ""
    return features_of(path)


def features_of(repo):
    # A repository's features as parsed rows of the sclaude status table. We
    # parse them ourselves, because the menu's second level is buttons onto
    # features rather than text.
    out = strip_ansi(run("cd %s && sclaude status" % shlex.quote(repo)))
    # git complains on stderr about repositories without origin/main — that has
    # nothing to do with features and must not get into the report.
    out = "\n".join(ln for ln in out.split("\n")
                    if not ln.startswith("fatal:")).strip()
    if not out or "No features in progress" in out:
        return [], out
    rows = []
    for line in out.split("\n"):
        line = line.rstrip()
        if line.startswith("FEATURE"):
            continue          # a table header will not do as a button
        if not line:
            # A blank line ends the feature table: below it sclaude prints the
            # branch breakdown ("Branches in progress"), and its rows are not
            # features. Without this a branch arrived in the menu as a separate
            # button leading nowhere.
            break
        # We split on two spaces — that is how align_columns separates the
        # columns. One will not do: a step's name is sometimes two words ("3/6
        # pull request"), and splitting on spaces returned "3/6 pull" as the step
        # and "request" as the path to the worktree. That is exactly how it
        # looked in the card.
        parts = [c for c in re.split(r" {2,}", line.strip()) if c]
        if len(parts) >= 2:
            # The columns: name, step, worktree. The path is not needed on the
            # button — it is long and eats the whole width on a phone, while the
            # table is there in full in the text below the buttons.
            rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return rows, out


def docs_keyboard():
    # The order runs from "what is this" to "how to fix it": someone opening
    # the docs for the first time does not start with the system's design.
    return [
        [{"text": t("docs.why"), "callback_data": "doc:why"},
         {"text": t("docs.usage"), "callback_data": "doc:usage"}],
        [{"text": t("docs.arch"), "callback_data": "doc:arch"},
         {"text": t("docs.holders"), "callback_data": "doc:holders"}],
        [{"text": t("docs.install"), "callback_data": "doc:install"},
         {"text": t("docs.files"), "callback_data": "doc:files"}],
        [{"text": t("docs.trouble"), "callback_data": "doc:trouble"}],
        [{"text": t("menu.back"), "callback_data": "menu_services"}],
    ]


def repos_keyboard():
    # The first level: repositories. There is no "all at once" item here — a
    # report on all of them almost always came down to a single "no features"
    # line, whereas usually one project is wanted, and it is that one that has
    # to be remembered between visits.
    rows = []
    chosen = repo_choice()
    for repo in known_repos():
        name = os.path.basename(repo)
        mark = "● " if chosen == repo else ""
        rows.append([{"text": mark + name, "callback_data": "repo:" + name}])
    # To the main menu rather than to Settings: people arrive here both by the
    # Sclaude button in the main menu and from Settings, and a "back" into a
    # branch the person never opened is the worse of the two options.
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


# --- sclaude's question-answer channel ---------------------------------------
#
# The orchestrator lays the question out as a file and waits for an answer from
# two places at once: the terminal where it was asked, and here. Whoever answers
# first has answered — which is why a step begun at the laptop continues from a
# phone without a restart, and the other way round.
#
# The channel lives in the repository's .git/sclaude/: one for all worktrees, so
# a question is found even before the feature is created. The format is in
# sclaude/lib/io.sh.


def ask_dir(repo):
    return os.path.join(repo, ".git", "sclaude")


def pending_ask(repo):
    # The repository's open question, or None. We read without locks: the file
    # is written through mv, that is it appears whole. JSON that will not parse
    # means "it is being rewritten right now" — we will come back on the next
    # turn.
    path = os.path.join(ask_dir(repo), "ask.json")
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
                     os.path.basename(repo), pid)
            try:
                os.unlink(path)
            except OSError:
                pass
            return None
    return data


# The labels of the options that mean a refusal. The orchestrator prints them:
# "Go back" in the action list, "none, go back" in the feature picker. We match
# on the start of the string and in both languages — the list is drawn in
# English, but translations of it are still to come.
BACK_OPTIONS = ("go back", "none, go back", "назад", "ничего")


def is_back_option(label):
    if not label:
        return False
    low = label.strip().lower().lstrip("‹ ").strip()
    return any(low.startswith(b) for b in BACK_OPTIONS)


def answered_option(repo, reply):
    # The label of the option behind an answer's number. Needed to tell leaving
    # the list from a real action: a number says nothing by itself, while the
    # question is still in the channel and carries its labels.
    question = pending_ask(repo)
    if not question:
        return ""
    options = question.get("options") or []
    try:
        i = int(str(reply).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= i <= len(options):
        return str(options[i - 1])
    return ""


def answer_ask(repo, reply):
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
    question = pending_ask(repo)
    if not question:
        return False
    d = ask_dir(repo)
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
                text = strip_ansi(str(label)).strip()
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
    # but BACK_OPTIONS already holds Russian, and translations of the list are
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


def ask_text(repo_name, question):
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
    slug = (question.get("feature") or "").strip()
    if slug:
        body += feature_card(repo_name, slug) + "\n\n"

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
    if context and named and ask_keyboard(repo_name, question):
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
                  body=escape(clip(strip_ansi(context), ASK_CONTEXT_MAX)))
    if slug:
        # The prompt itself in italics and without "<repository> is asking": the
        # repository and the feature are already named by the card a line
        # above.
        body += "<i>%s</i>" % escape(strip_ansi(question.get("prompt") or "").strip())
    else:
        body += t("ask.title", repo=escape(repo_name),
                  prompt=escape(strip_ansi(question.get("prompt") or "")))
    form = (question.get("form") or "").strip()
    if not form:
        body += "\n\n<i>%s</i>" % t("ask.text")
    elif form.startswith("pick:") and not ask_keyboard(repo_name, question):
        body += "\n\n<i>%s</i>" % t("ask.pick")
    return body


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
    tty = tty_of_pid(question.get("pid") or 0)
    if not tty:
        return False
    try:
        return time.time() - os.stat(tty).st_atime < ASK_QUIET_AFTER
    except OSError:
        return False


# --- the state of steps' sessions --------------------------------------------


def agents():
    # Live claude sessions, interactive and background. It needs no terminal, so
    # it is available to the daemon too. Empty on any trouble: no claude, no
    # answer, broken JSON — the card simply will not show the state.
    out = run("claude agents --json", timeout=20)
    try:
        data = json.loads(out)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def session_state(session_id, cache=None):
    # What a step's session is busy with: working / blocked / idle, or empty if
    # there is none.
    #
    # cache is a list already obtained from agents(): the call shells out with a
    # timeout, and there is no reason to ask once per feature where there are
    # several. Whoever iterates the list passes it; for a single question it can
    # be left out.
    if not session_id:
        return ""
    for a in (agents() if cache is None else cache):
        if isinstance(a, dict) and a.get("sessionId") == session_id:
            return a.get("state") or a.get("status") or "idle"
    return ""


def state_path(wt):
    """A feature's state.json, in the old .feature/ when an older sclaude
    still runs the tree: layout_migrate leaves it there until that sclaude is
    done, and the feature went missing from the bot meanwhile."""
    new = os.path.join(wt, ".sclaude/local/feature", "state.json")
    old = os.path.join(wt, ".feature", "state.json")
    return new if os.path.exists(new) or not os.path.exists(old) else old


def feature_state(repo, slug):
    # A feature's whole state — the very file with which the orchestrator ties
    # the steps together. An empty dictionary if there is no feature: the card
    # will then show what it knows from the table.
    wt = os.path.join(os.path.dirname(repo), "%s-%s" % (os.path.basename(repo), slug))
    path = state_path(wt)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def feature_session(repo, slug):
    # The session id of the feature's current step, and the step itself.
    data = feature_state(repo, slug)
    step = data.get("step") or ""
    node = (data.get("steps") or {}).get(step) or {}
    return (node.get("session") or ""), step


def feature_links(repo, slug):
    # The feature's issue and pull request. The numbers here are exact — the
    # orchestrator put them there itself — so there is no need to parse a
    # commit's text as in the repository's card.
    #
    # The issue first: it holds the statement of what all this is being done
    # for, whereas the PR appears only at the third step and until then simply
    # does not exist.
    data = feature_state(repo, slug)
    slug_gh = gh_slug(repo)
    if not slug_gh:
        return []
    links = []
    issue = data.get("issue")
    if issue:
        links.append((t("repo.issue", n=issue),
                      "https://github.com/%s/issues/%s" % (slug_gh, issue)))
    pr = data.get("pr")
    if pr:
        links.append((t("repo.pr", n=pr),
                      "https://github.com/%s/pull/%s" % (slug_gh, pr)))
    return links


def start_sclaude(repo, args):
    # Starting the orchestrator in the background.
    #
    # We detach through setsid and do not wait: sclaude lives as long as the
    # conversation does — minutes and hours — while the bot has to be back at
    # getUpdates within seconds. Waiting for it here would mean hanging the
    # whole chat for the duration of the step.
    #
    # The conversation goes on through the channel: the bot will pick the
    # questions up on the loop's turns.
    cmd = "cd %s && setsid sclaude %s < /dev/null > /dev/null 2>&1 &" % (
        shlex.quote(repo), " ".join(shlex.quote(a) for a in args))
    run(cmd, timeout=15)
    log.info("started sclaude %s in %s", " ".join(args), repo)


def feature_card(name, slug):
    feats, _ = features_of_name(name)
    row = next((r for r in feats if r[0] == slug), None)
    if not row:
        return t("feat.gone", slug=escape(slug))
    repo = repo_path(name)
    session, _step = feature_session(repo, slug) if repo else ("", "")
    state = session_state(session)
    note = {"working": t("feat.working"), "blocked": t("feat.blocked"),
            "busy": t("feat.working"), "idle": t("feat.idle")}.get(
                state, t("feat.nosession"))
    return t("feat.card", repo=escape(name), slug=escape(slug),
             step=escape(row[1]), wt=escape(row[2] or "—"), session=note,
             links=links_line(feature_links(repo, slug)) if repo else "")


def feature_keyboard(name, slug):
    # A feature's card: continue the step, actions on it, refresh, back.
    #
    # "Actions" is the same thing the checkbox below the feature list opens in
    # the terminal. The checkbox does not carry over here: there is no space bar
    # in a chat, and a button on the card speaks for itself more clearly than
    # any toggle.
    return [
        [{"text": t("feat.continue"), "callback_data": "go:%s:%s" % (name, slug)}],
        [{"text": t("feat.actions"), "callback_data": "acts:%s:%s" % (name, slug)}],
        [{"text": t("repo.refresh"), "callback_data": "feat:%s:%s" % (name, slug)},
         {"text": t("repo.torepos"), "callback_data": "repo:" + name}],
        [{"text": t("menu.back"), "callback_data": "menu_back"}],
    ]


# How many features get buttons. Eight: more rows do not fit on a phone's
# screen, and below them there are still "new feature" and three exits. Those
# that did not fit are named in a line in repo_text — they must not disappear
# from the chat.
FEATURE_BUTTONS = 8


def features_keyboard(name):
    # The second level: the selected repository's features. A row per feature,
    # and two buttons in the row — like the checkbox in the terminal, only
    # unfolded across the width.
    #
    # In the terminal "what Enter does" is switched by the checkbox below the
    # list. Here there is nothing to switch: an inline keyboard has neither a
    # space bar nor a state that would survive a press. What it does have is the
    # row's width — and the two purposes lay themselves out along it side by
    # side, with no mode at all: the wide button drives the step, the narrow one
    # opens the list of actions on the same feature.
    #
    # Both targets already exist and both check the feature's busyness
    # themselves, so only the addresses are here: go: starts the step, acts:
    # the action list. The card stops being a transfer point but does not go
    # anywhere: both handlers end with it, showing the outcome.
    rows = []
    feats, _ = features_of_name(name)
    for slug, step, _wt in feats[:FEATURE_BUTTONS]:
        label = "%s — %s" % (slug, step)
        # We cut shorter than before. Telegram splits a row between buttons
        # evenly by their number rather than by the text's length, so a lone cog
        # will take half the row however briefly it is labelled. A short label on
        # the left does not change that — but it does stop the label being
        # truncated beyond recognition at half width.
        rows.append([
            {"text": label[:40], "callback_data": "go:%s:%s" % (name, slug)},
            {"text": t("feat.acts.short"), "callback_data": "acts:%s:%s" % (name, slug)},
        ])
    rows.append([{"text": t("feat.new"), "callback_data": "newfeat:" + name}])
    # Two exits, not one. "To the repositories" is a step one level up within
    # the section; "Back" goes to the main menu, which is where people arrive
    # here from with the Sclaude button. Without the second the way out was
    # roundabout: features → repositories → Settings, that is into a neighbouring
    # branch rather than back where they came from.
    rows.append([{"text": t("repo.refresh"), "callback_data": "repo:" + name},
                 {"text": t("repo.torepos"), "callback_data": "svc_repos"}])
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


def gh_slug(repo):
    # The repository's owner/name from origin's address. We parse it ourselves
    # rather than asking `gh repo view`: that is a network call for the sake of a
    # string that sits in the config.
    url = run("git -C %s remote get-url origin" % shlex.quote(repo)).strip()
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def commit_links(repo, commit):
    # GitHub links from the last commit.
    #
    # The number in a merge commit is the PR, not the issue: "Merge pull
    # request #89" leads to the pull request. The issue itself hides a line
    # deeper, in that same PR's body ("Closes #20") — that is, where sclaude's
    # step 3 puts it. The branch's name (feat/20-change-…) holds the same number
    # and will do when the body is not to hand.
    #
    # Hence two different questions and two different links: "what change has
    # arrived" and "why it was needed". The second is the more valuable — the
    # statement lies in the issue — and without it the card made people look for
    # it by hand.
    #
    # All best-effort: no gh, no network, the number was not found — there will
    # simply be no link. A repository's card is not the place to fall over.
    slug = gh_slug(repo)
    if not slug:
        return []

    m = re.search(r"#(\d+)", commit or "")
    if not m:
        return []
    pr = m.group(1)
    links = [(t("repo.pr", n=pr), "https://github.com/%s/pull/%s" % (slug, pr))]

    body = run("gh pr view %s -R %s --json body -q .body" % (shlex.quote(pr), shlex.quote(slug)),
               timeout=20)
    issue = ""
    found = re.search(r"(?:clos(?:e|es|ed)|fix(?:e|es|ed)?|resolv(?:e|es|ed))\s+#(\d+)",
                      body or "", re.I)
    if found:
        issue = found.group(1)
    else:
        # The fallback is the PR's branch name: sclaude names it after the
        # issue's number, so the number is there even for a PR with an empty
        # body.
        head = run("gh pr view %s -R %s --json headRefName -q .headRefName"
                   % (shlex.quote(pr), shlex.quote(slug)), timeout=20)
        m2 = re.match(r"^[a-z]+/(\d+)-", (head or "").strip())
        if m2:
            issue = m2.group(1)
    if issue:
        links.append((t("repo.issue", n=issue),
                      "https://github.com/%s/issues/%s" % (slug, issue)))
    return links


def links_line(links):
    # The links as a line under the commit. Telegram makes a link of an
    # <a href>, and the caption "#20" is shorter than a bare address — on a phone
    # that is the difference between one line and three.
    if not links:
        return ""
    return "\n" + " · ".join('<a href="%s">%s</a>' % (url, escape(label))
                             for label, url in links)


def main_branch_state(repo):
    # When there are no features there is no reason to show emptiness: the
    # person opened the repository to learn something about it. The main branch
    # is the little that can always be said, and it answers the question "what
    # state is the project in".
    q = shlex.quote(repo)
    branch = run("git -C " + q + " rev-parse --abbrev-ref HEAD").strip()
    commit = run("git -C " + q + " log -1 --format='%h %s'").strip()
    when = run("git -C " + q + " log -1 --format=%cr").strip()
    dirty = run("git -C " + q + " status --porcelain")
    dirty_n = 0 if dirty == t("cmd.empty") else len([l for l in dirty.split("\n") if l.strip()])
    ahead = run("git -C " + q + " rev-list --count @{u}..HEAD 2>/dev/null").strip()
    try:
        ahead_n = int(ahead)
    except ValueError:
        ahead_n = 0          # no upstream — nothing to compare against

    # A fresh repository with no commits: git answers with a complaint on
    # stderr, and there is no reason to show it to a person — "there are no
    # commits yet" is not an error but a state that can be put in words.
    empty = ("fatal:" in commit) or ("fatal:" in branch) or ("fatal:" in when)

    extra = []
    if dirty_n:
        extra.append(t("repo.dirty", n=dirty_n))
    if ahead_n:
        extra.append(t("repo.ahead", n=ahead_n))
    if not extra:
        extra.append(t("repo.clean"))
    return {"branch": branch or "?", "commit": commit or "?",
            "when": when or "", "extra": "\n".join(extra), "empty": empty,
            "links": "" if empty else links_line(commit_links(repo, commit))}


def repo_text(name):
    # raw is the whole sclaude status table; it is no longer needed here, but
    # features_of_name returns it along with the rows, and it has to be parsed
    # for the buttons' sake anyway.
    feats, _raw = features_of_name(name)
    if not feats:
        path = repo_path(name)
        if not path:
            return t("repo.norepos")
        st = main_branch_state(path)
        if st["empty"]:
            return t("repo.nocommits", name=escape(name), extra=st["extra"])
        return t("repo.none", name=escape(name),
                 branch=escape(st["branch"]), commit=escape(st["commit"]),
                 when=escape(st["when"]), extra=st["extra"],
                 links=st["links"])
    body = t("repo.count", name=escape(name), n=len(feats))
    # A button goes to the first eight (see features_keyboard). The rest are
    # not visible in the chat at all — neither as a button nor as a line — so a
    # counter over emptiness would only mislead: "features in progress: 9" with
    # eight of them there. We name them.
    rest = [r[0] for r in feats[FEATURE_BUTTONS:]]
    if rest:
        body += t("repo.rest", rest=escape(", ".join(rest)))
    return body



def strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


def hard_hold_text(data):
    # When a hard holder is holding there is no deadline at all — and showing
    # "this much left" would be a lie.
    return t("hold.hard", who=holders_line(data, "hard"))


# The markers with which keepawake status marks a link inside a name:
# \x01 address \x02 caption \x03. Control characters rather than markup, because
# the script's output is escaped as a whole — letting ready HTML through
# escape() would mean putting holes in the escaping for cosmetics' sake.
STATUS_LINK = re.compile("\x01([^\x02]*)\x02([^\x03]*)\x03")


def status_text():
    # --raw: what is wanted from the script is the form with markers rather than
    # the one already unfolded for the terminal. Without it "dev server
    # (http://…) — none" would arrive here.
    body = strip_ansi(run("keepawake status --raw"))
    # We escape earlier and mark up later: by this moment the caption and the
    # address are already safe, and the tags are put in by us.
    body = STATUS_LINK.sub(r'<a href="\1">\2</a>', escape(body))
    return t("status.title", body=body)


def escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def local_for_lang(label):
    # state.py writes "HH:MM dd.mm" — the order a Russian reader is used to.
    # For English we swap the day and the month; we do not touch the format in
    # the state itself, it is part of the schema and more than the bot reads
    # it.
    if current() == "ru" or not label:
        return label
    parts = label.split()
    if len(parts) == 2 and "." in parts[1]:
        day, month = parts[1].split(".", 1)
        return "%s %s/%s" % (parts[0], month, day)
    return label


def holders_line(data, kind=None):
    # kind=None means all holders, "hard"/"soft" only those of that kind.
    from keepawake.state import HARD_HOLDERS, SOFT_HOLDERS
    # codesrv is essential here: without it the state "the code-server service
    # is up, nobody else" was shown as "holders: nobody" — in the very warning
    # about imminent sleep where a person needs to understand what exactly is
    # holding the machine.
    labels = {"ssh": None, "code": t("hold.code"), "tailscale": t("hold.tailnet"),
              "claude": t("hold.claude"), "dev": t("hold.dev"),
              "codesrv": t("hold.codesrv"), "sclaude": t("hold.sclaude"),
              "vscode": t("hold.vscode")}
    wanted = {"hard": HARD_HOLDERS, "soft": SOFT_HOLDERS}.get(kind)
    names = []
    counts = data.get("holders") or {}
    for name, label in labels.items():
        if wanted and name not in wanted:
            continue
        n = (counts.get(name) or {}).get("count") or 0
        if not n:
            continue
        # For SSH the number of sessions is meaningful, for the others it is
        # not.
        names.append(ssh_holders(n) if name == "ssh" else label)
    return ", ".join(names) or t("hold.nobody")


def hold_reasons(data, now):
    # Every reason the machine is not sleeping, from the longest-running to the
    # rest. The question about a forgotten session used to show hard holders
    # only, and on a day when the hold was set by the "stay awake" button until
    # the following week, the message named a third-rate tailnet and advised
    # stopping the services — advice useless by construction, as the deadline
    # would outlive them all.
    #
    # Returns a list of pairs (how much longer it will hold, text). The number
    # is for sorting only: for a manual deadline it is the remainder, for holders
    # there is nowhere to learn it from, and they follow in the order they
    # appeared.
    from keepawake.state import HARD_HOLDERS, manual_until
    reasons = []
    left = manual_until(data, now)
    if left:
        reasons.append((left, t("hold.manual", at=local_label(left))))
    counts = data.get("holders") or {}
    labels = [("ssh", None), ("code", t("hold.code")), ("tailscale", t("hold.tailnet")),
              ("claude", t("hold.claude")), ("dev", t("hold.dev")),
              ("codesrv", t("hold.codesrv")), ("sclaude", t("hold.sclaude")),
              ("vscode", t("hold.vscode"))]
    for name, label in labels:
        n = (counts.get(name) or {}).get("count") or 0
        if not n:
            continue
        text = ssh_holders(n) if name == "ssh" else label
        # Hard ones hold while they are alive, soft ones for an hour beyond
        # their last appearance. Nothing more precise can be said, and the order
        # between them is set by the list anyway.
        reasons.append((0, text))
    # The manual deadline always comes first: it is the only one whose duration
    # we know, and it is the one that outlives everything else.
    reasons.sort(key=lambda r: -r[0])
    return reasons


def reasons_lines(reasons):
    # As a list, with the main reason in bold: that is what to aim at, the rest
    # are not what is preventing sleep.
    if not reasons:
        return "• " + t("hold.nobody")
    out = []
    for i, (_, text) in enumerate(reasons):
        out.append("• <b>%s</b>" % text if i == 0 else "• " + text)
    return "\n".join(out)


# --- handling ---------------------------------------------------------------

def remember_lang(frm):
    # The client's language arrives in every message and press. We remember it
    # in the state, because the daemon sends the warning about imminent sleep by
    # itself, without an incoming update: at that moment there is nobody to ask,
    # and the last known value is the only thing it has.
    data = read()
    # A choice from the settings beats the client's. Otherwise the switch would
    # live until the very first press: language_code arrives in every update, and
    # an unconditional overwrite would bring the client's language straight
    # back.
    if data.get("lang_pinned"):
        return set_lang(data.get("lang") or DEFAULT)
    code = (frm or {}).get("language_code")
    lang = set_lang(code)
    if data.get("lang") != lang:
        with locked() as st:
            st["lang"] = lang
        log.info("the interlocutor's language: %s (language_code=%r)", lang, code)
    return lang


# The bot's commands: name → a Handler method and a description key in i18n. One
# table for both uses — parsing an incoming "/chrome" and the list in
# setMyCommands — because having diverged they would give the worst of all
# outcomes: a suggestion for a command that answers "unknown command".
#
# /start is deliberately not in the list: Telegram sends it itself when the chat
# is first opened, and there is no reason to show it to a person as one of the
# ways to open the menu.
COMMANDS = collections.OrderedDict([
    ("menu",     ("cmd_menu",     "cmd.menu")),
    ("status",   ("cmd_status",   "cmd.status")),
    ("awake",    ("cmd_awake",    "cmd.awake")),
    ("extend",   ("cmd_extend",   "cmd.extend")),
    ("sleep",    ("cmd_sleep",    "cmd.sleep")),
    ("chrome",   ("cmd_chrome",   "cmd.chrome")),
    ("code",     ("cmd_code",     "cmd.code")),
    ("sclaude",  ("cmd_sclaude",  "cmd.sclaude")),
    ("settings", ("cmd_settings", "cmd.settings")),
])
COMMANDS["start"] = COMMANDS["menu"]


class Handler(object):
    def __init__(self, bot):
        self.bot = bot

    def message(self, msg):
        text = (msg.get("text") or "").strip()
        now = int(time.time())

        # We are waiting for a time for "stay awake until" — but a command
        # always beats the wait, otherwise there would be no way out of a
        # dialogue begun by mistake except the right answer.
        if (read().get("awaiting") == "awake_until"
                and not text.startswith("/") and not is_menu_button(text)):
            until_ts = parse_hhmm(text, now)
            if not until_ts:
                log.warning("\"stay awake until\": the time was not parsed (%r)", text)
                # We ask again with the box ready too: the person has already
                # missed the format, and making them open the keyboard by hand a
                # second time is exactly what the buttons save them from.
                self.bot.ask(t("awake.badtime"), t("awake.hint"))
                return
            until = hold_for(until_ts - now, now)
            log.info("\"stay awake until\" %s: deadline until %s", text, until)
            self.bot.send(t("extended.plain", at=local_for_lang(until)),
                          awake_keyboard())
            return

        # An answer to an orchestrator's question that expects text rather than
        # a button: a feature's name, a branch's name, an option's number from a
        # long list.
        #
        # We do not set up a separate wait here: the open question is the wait,
        # it lies as a file in the channel. That also removes the perennial
        # problem of such modes — the question may have closed in the terminal
        # while the person was typing, and answer_ask will then honestly say
        # there is nothing left to answer.
        #
        # Commands and the "Menu" button do not get in here: one must be able
        # to leave a conversation begun by mistake without answering the
        # question.
        if text and not text.startswith("/") and not is_menu_button(text):
            waiting = [r for r in known_repos() if pending_ask(r)]
            if len(waiting) == 1:
                repo = waiting[0]
                if answer_ask(repo, text):
                    self.bot.send(t("ask.sent", reply=escape(text)))
                else:
                    self.bot.send(t("ask.gone"))
                return

        # Any command clears an open question about the time: the person has
        # gone elsewhere, and there is no longer anything to expect a "23:30"
        # from them for. The "Menu" button ranks with the commands here — it is
        # the declared way to cancel.
        if (text.startswith("/") or is_menu_button(text)) and read().get("awaiting"):
            with locked() as st:
                st["awaiting"] = ""

        if is_menu_button(text):
            return self.cmd_menu()
        if not text.startswith("/"):
            self.bot.send(t("cmd.unknown"), menu_keyboard())
            return
        # We cut off both the arguments and the @bot_name: Telegram appends it
        # itself when a command is chosen from the suggestions in a group.
        name = text.split()[0].split("@")[0].lstrip("/").lower()
        found = COMMANDS.get(name)
        if not found:
            self.bot.send(t("cmd.unknown"), menu_keyboard())
            return
        getattr(self, found[0])(now)

    # --- commands -----------------------------------------------------------
    #
    # Every section reachable by buttons has a command too: for a person with a
    # keyboard in their hands that is shorter than two or three presses through
    # the menu. The command sends the very same screen with the same buttons —
    # from there the person goes on pressing as though they had come through the
    # menu.

    def cmd_menu(self, now=0):
        self.bot.send(menu_title(), menu_keyboard())

    def cmd_status(self, now=0):
        self.bot.send(status_text())

    def cmd_extend(self, now=0):
        until = hold_for(HOLD_SECONDS, now or int(time.time()))
        log.info("the /extend command: deadline until %s", until)
        self.bot.send(t("extended.plain", at=local_for_lang(until)),
                      awake_keyboard())

    def cmd_sleep(self, now=0):
        release_hold(now or int(time.time()))
        log.info("the /sleep command: hold released, refusal for %d min",
                 state.REFUSAL_HOLDS // 60)
        self.bot.send(t("awake.released"), menu_keyboard())

    def cmd_awake(self, now=0):
        self.bot.send(awake_text(), awake_keyboard())

    def cmd_chrome(self, now=0):
        self.bot.send(chrome_text(), chrome_keyboard())

    def cmd_code(self, now=0):
        self.bot.send(code_text(), code_keyboard())

    def cmd_sclaude(self, now=0):
        # As with the button: we open straight on the remembered repository and
        # ask only when we remember none.
        chosen = repo_choice()
        if chosen:
            name = os.path.basename(chosen)
            self.bot.send(repo_text(name), features_keyboard(name))
        else:
            self.bot.send(t("repo.pick"), repos_keyboard())

    def cmd_settings(self, now=0):
        self.bot.send(t("svc.title"), services_keyboard())

    def callback(self, cq):
        cid = cq.get("id")
        data_raw = cq.get("data") or ""
        message_id = ((cq.get("message") or {}).get("message_id")) or 0
        now = int(time.time())

        # The answer first thing, otherwise a spinner turns on the phone.
        self.bot.answer(cid)

        # The sleep buttons only, and by an explicit prefix. A check for "has a
        # colon" would intercept repo: and feat: as well — they appeared later,
        # and a press on a repository answered "the message is out of date"
        # because the decision handler found no deadline stamp in it.
        if data_raw.startswith(("extend:", "sleep:")):
            return self.decision(data_raw, message_id, cid, now)

        if data_raw == "menu_extend":
            self.bot.edit(message_id, awake_text(), awake_keyboard())
        elif data_raw.startswith("awake:"):
            seconds = int(data_raw.split(":", 1)[1])
            until = hold_for(seconds, now)
            log.info("the extend button for %d min: deadline until %s", seconds // 60, until)
            # We leave the menu: having extended by an hour, people often want
            # to add more at once, and there is no reason to go back to the main
            # menu for that.
            self.bot.edit(message_id, t("extended.plain", at=local_for_lang(until)),
                          awake_keyboard())
        elif data_raw == "awake_forever":
            until = hold_for(FOREVER_SECONDS, now)
            log.info("the \"stay awake\" button: indefinite, deadline until %s", until)
            self.bot.edit(message_id, t("awake.forever.ok"), awake_keyboard())
        elif data_raw == "awake_until":
            with locked() as st:
                st["awaiting"] = "awake_until"
            log.info("the \"stay awake until\" button: waiting for a time")
            # We leave the "back" button: having changed their mind, people
            # leave the question with one press rather than by typing /menu —
            # which will also do for it and is named in the question itself.
            self.bot.edit(message_id, t("awake.ask"),
                          [[{"text": t("menu.back"), "callback_data": "menu_back"}]])
            # We raise the input box itself with a second message: "back" is
            # inline, and ForceReply cannot be put into inline markup, a message
            # has one reply_markup. Splitting was unavoidable, but leaving with
            # one press is preserved.
            self.bot.ask(t("awake.ask.now"), t("awake.hint"))
        elif data_raw == "awake_release":
            # The same as "Let it sleep" in the warning.
            release_hold(now)
            # We clear an open question about the time: the person has left it
            # for a neighbouring button, and there is nothing left to expect an
            # answer for.
            if read().get("awaiting"):
                with locked() as st:
                    st["awaiting"] = ""
            log.info("the \"let it sleep\" button: hold released, refusal for %d min",
                     state.REFUSAL_HOLDS // 60)
            self.bot.edit(message_id, t("awake.released"), menu_keyboard())
        elif data_raw == "menu_status":
            self.bot.edit(message_id, status_text(), menu_keyboard())
        elif data_raw == "menu_chrome":
            self.bot.edit(message_id, chrome_text(), chrome_keyboard())
        elif data_raw == "menu_code":
            self.bot.edit(message_id, code_text(), code_keyboard())
        elif data_raw in ("code_start", "code_restart", "code_stop"):
            verb = {"code_start": "start", "code_restart": "restart",
                    "code_stop": "stop"}[data_raw]
            run("systemctl --user %s code-server.service" % verb)
            self.bot.edit(message_id, code_text(), code_keyboard())
        elif data_raw == "menu_services":
            self.bot.edit(message_id, t("svc.title"), services_keyboard())
        elif data_raw == "menu_back":
            # Returning to the menu also cancels an open question about the
            # time: otherwise the bot would silently swallow the next ordinary
            # message, taking it for an answer.
            if read().get("awaiting"):
                with locked() as st:
                    st["awaiting"] = ""
            self.bot.edit(message_id, menu_title(), menu_keyboard())
        elif data_raw == "noop":
            pass          # a row caption, not a button
        elif data_raw == "idle_keep":
            # We do nothing — but mark that we asked, so that the next question
            # comes in an hour rather than at once.
            with locked() as st:
                st["idle_asked_ts"] = now
            self.bot.edit(message_id, t("idle.kept"))
        elif data_raw == "idle_sleep":
            release_hold(now)
            # We mark that we asked: otherwise the next question about
            # forgotten holders would come immediately rather than in an hour.
            with locked() as st:
                st["idle_asked_ts"] = now
            log.info("forgotten holders: let it sleep, hold released")
            self.bot.edit(message_id, t("idle.slept"))
        elif data_raw in ("chrome_start", "chrome_restart", "chrome_stop"):
            if data_raw == "chrome_stop":
                run("chrome-debug --stop")
            else:
                if data_raw == "chrome_restart":
                    run("chrome-debug --stop")
                # The list of features rather than any one of them: which one
                # is wanted is the next button's question, and the list is
                # where each of them is a click away.
                run("chrome-debug http://localhost:%d/" % DEV_PORT, timeout=60)
            # We show the state rather than the command's output:
            # chrome-debug's output is written for a terminal and reads badly in
            # a messenger, while the person has one question — did it start and
            # where to look.
            self.bot.edit(message_id, chrome_text(), chrome_keyboard())
        elif data_raw.startswith("devphone:"):
            # An empty label is the list of every feature, the first row.
            label = data_raw.partition(":")[2]
            if label and not [f for f in dev_features() if f[0] == label]:
                self.bot.edit(message_id, chrome_text(), chrome_keyboard())
                return
            run("systemctl --user start " + GATE_UNIT, timeout=60)
            if not gate_running():
                # Most often the funnel: not allowed for this node in the
                # tailnet policy, or this user is not Tailscale's operator.
                tail = run("journalctl --user -u %s -n 8 --no-pager -o cat" % GATE_UNIT)
                self.bot.edit(message_id, t("chrome.gatefail", log=escape(tail[-1500:])),
                              chrome_keyboard())
                return
            log.info("phone access opened for %s", label or "the list")
            if label:
                proxy_start(label)
            self.bot.edit(message_id, chrome_text(), chrome_keyboard())
        elif data_raw == "gate_stop":
            run("systemctl --user stop " + GATE_UNIT, timeout=60)
            log.info("phone access closed")
            self.bot.edit(message_id, chrome_text(), chrome_keyboard())
        elif data_raw.startswith(("devopen:", "devstop:", "devstart:")):
            action, _, label = data_raw.partition(":")
            found = [f for f in dev_features() if f[0] == label]
            if not found:
                # Merged or abandoned since the card was drawn.
                self.bot.edit(message_id, chrome_text(), chrome_keyboard())
                return
            _label, wt, _port, _running = found[0]
            if action == "devopen":
                # A tab in the laptop's Chrome, which starts the browser if it
                # is down. A stopped feature needs nothing more: the request
                # itself makes sclaude-proxy start it.
                run("chrome-debug " + shlex.quote("http://%s.localhost:%d/" % (label, DEV_PORT)),
                    timeout=60)
            elif action == "devstart":
                proxy_start(label)
            else:
                run("cd " + shlex.quote(wt) + " && sclaude dev --stop", timeout=90)
            self.bot.edit(message_id, chrome_text(), chrome_keyboard())
        elif data_raw == "svc_sclaude":
            # We open straight on the remembered repository: most often a
            # person comes back to the same project, and a needless choice is no
            # use to them.
            chosen = repo_choice()
            if chosen:
                name = os.path.basename(chosen)
                self.bot.edit(message_id, repo_text(name), features_keyboard(name))
            else:
                self.bot.edit(message_id, t("repo.pick"), repos_keyboard())
        elif data_raw == "svc_lang":
            self.bot.edit(message_id, lang_text(), lang_keyboard())
        elif data_raw.startswith("lang:"):
            choice = data_raw.split(":", 1)[1]
            with locked() as st:
                if choice == "auto":
                    # We unpin and take the language from this very press at
                    # once: it carries language_code, and there is no reason to
                    # wait for the next one to show the result.
                    st["lang_pinned"] = False
                    lang = set_lang((cq.get("from") or {}).get("language_code"))
                else:
                    st["lang_pinned"] = True
                    lang = set_lang(choice)
                st["lang"] = lang
            log.info("the language was switched: %s (pinned: %s)",
                     lang, choice != "auto")
            # The keyboard below the input box is labelled in the previous
            # language — we replace it, otherwise its caption would diverge from
            # the rest of the interface.
            relabel_anchor(self.bot)
            self.bot.edit(message_id, lang_text(), lang_keyboard())
        elif data_raw == "svc_docs":
            self.bot.edit(message_id, t("docs.menu"), docs_keyboard())
        elif data_raw.startswith("doc:"):
            body = docs.section(data_raw.split(":", 1)[1], current())
            if body:
                # A separate message rather than an edit of the current one:
                # the sections are long, and paging through them while losing the
                # previous one is awkward. The menu stays in place so the next
                # section opens with one press.
                self.bot.send(body)
            else:
                self.bot.edit(message_id, t("docs.menu"), docs_keyboard())
        elif data_raw == "svc_repos":
            self.bot.edit(message_id, t("repo.pick"), repos_keyboard())
        elif data_raw.startswith("repo:"):
            name = data_raw.split(":", 1)[1]
            path = repo_path(name)
            if not path:
                # A name not from the list: either the repository is gone or the
                # callback was forged. Both are a reason to show the list
                # again.
                log.warning("unknown repository in the callback: %r", name)
                self.bot.edit(message_id, t("repo.pick"), repos_keyboard())
                return
            was = repo_choice()
            with locked() as st:
                st["sclaude_repo"] = path
            # code-server opens a directory at start-up, so a change of choice
            # reaches it only through a restart. We do that ourselves and only
            # with a live server: nobody asked to bring it up for the sake of a
            # changed choice.
            if was != path and code_running():
                run("systemctl --user restart code-server.service")
            self.bot.edit(message_id, repo_text(name), features_keyboard(name))
        elif data_raw.startswith("feat:"):
            _, name, slug = data_raw.split(":", 2)
            self.bot.edit(message_id, feature_card(name, slug),
                          feature_keyboard(name, slug))
        elif data_raw.startswith("acts:"):
            # The list of actions on a feature. Started the same way as a step:
            # the orchestrator goes into the background, and the list arrives as
            # a question in the channel — as buttons labelled by the options.
            _, name, slug = data_raw.split(":", 2)
            repo = repo_path(name)
            if not repo:
                self.bot.edit(message_id, t("repo.norepos"), repos_keyboard())
                return
            # We do not touch a busy feature for the same reason as with
            # "Continue": a second orchestrator on the same feature is two
            # conversations about one thing.
            session, _step = feature_session(repo, slug)
            if session and session_state(session) in ("working", "blocked", "busy"):
                self.bot.edit(message_id, t("feat.busy"),
                              feature_keyboard(name, slug))
                return
            start_sclaude(repo, ["actions", slug])
            # We do not draw the card here. The action list will arrive in its
            # own message and bring it along — above the buttons. The previous
            # edit left a copy of it in the chat with the "Continue" and
            # "Actions" buttons, and after the question was answered that copy
            # was the last one: the list disappeared, and above it stood a menu
            # the person had already left.
            #
            # We leave the feature list — what was pressed. It stays correct
            # even once the person closes the action list.
            self.bot.edit(message_id, repo_text(name), features_keyboard(name))

        elif data_raw.startswith("go:"):
            # Starting or continuing a step. The orchestrator decides what to
            # do itself: `sclaude <feature>` returns to the current step, and if
            # the step's session is already open it will refuse — by the
            # session_holder check shared by both entrances.
            _, name, slug = data_raw.split(":", 2)
            repo = repo_path(name)
            if not repo:
                self.bot.edit(message_id, t("repo.norepos"), repos_keyboard())
                return
            # busy belongs here too: the card shows it as "running" (🟢), and
            # not blocking on it means starting a second orchestrator on the same
            # feature — exactly what this check stands against.
            session, _step = feature_session(repo, slug)
            if session and session_state(session) in ("working", "blocked", "busy"):
                self.bot.edit(message_id, t("feat.busy"),
                              feature_keyboard(name, slug))
                return
            start_sclaude(repo, [slug])
            feats, _ = features_of_name(name)
            row = next((r for r in feats if r[0] == slug), None)
            self.bot.edit(message_id,
                          t("feat.started", step=escape(row[1] if row else slug)),
                          feature_keyboard(name, slug))
        elif data_raw.startswith("newfeat:"):
            # A new feature: the conversation goes on through the channel from
            # here — the orchestrator will ask for a name (or offer issues), and
            # the bot will show the question on a turn of the loop.
            name = data_raw.split(":", 1)[1]
            repo = repo_path(name)
            if not repo:
                self.bot.edit(message_id, t("repo.norepos"), repos_keyboard())
                return
            start_sclaude(repo, ["new"])
            self.bot.edit(message_id, repo_text(name), features_keyboard(name))
        elif data_raw.startswith("answer:"):
            # An answer to an orchestrator's question. Three fields rather than
            # two: we separate the repository's name from the answer at the
            # first colon from the left — the answer itself may contain
            # anything.
            _, name, reply = data_raw.split(":", 2)
            repo = repo_path(name)
            if not repo:
                self.bot.edit(message_id, t("repo.norepos"), repos_keyboard())
                return
            # We learn what exactly was chosen before sending: afterwards the
            # question is cleared, and there will be nowhere left to read it
            # from.
            chosen = answered_option(repo, reply)
            if answer_ask(repo, reply):
                # "Answer sent: 9" is honest but useless where the answer was
                # an exit. The person pressed "back" and has a right to see what
                # they were leaving: the repository's feature list. The other
                # answers stay as they were — work follows them, and its output
                # will come in due course.
                if is_back_option(chosen):
                    self.bot.edit(message_id, repo_text(name),
                                  features_keyboard(name))
                else:
                    self.bot.edit(message_id, t("ask.sent", reply=escape(reply)))
            else:
                self.bot.edit(message_id, t("ask.gone"))
        elif data_raw == "svc_restart":
            self.restart(message_id)
        else:
            log.warning("unknown callback: %s", data_raw)

    def restart(self, message_id):
        # The daemon restarts itself, and this is the case where the order
        # matters more than the return code: systemctl kills us right in the
        # middle of handling, and there is nobody else to report the restart —
        # the process is already gone.
        #
        # So first the "restarting" message and only then the command itself:
        # detached from us (start-new-session) and with a pause, so that
        # sendMessage has time to go out over the network. Otherwise systemd
        # kills the whole process group along with the answer not yet sent.
        pid = os.getpid()
        started = uptime_of(pid)
        self.bot.edit(message_id,
                      t("svc.restarting"), None)
        # We put the mark in the state: after the restart it is a different
        # process, and it can remember the errand only through a file.
        with locked() as st:
            st["restart_notify"] = message_id
            st["restart_from_pid"] = pid
        subprocess.Popen(
            ["bash", "-c",
             "sleep 2; systemctl --user restart keepawake-telegram.service"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def decision(self, raw, message_id, cid, now):
        action, _, ts = raw.partition(":")
        try:
            stamp = int(ts)
        except ValueError:
            stamp = None

        with locked() as st:
            live_until = st.get("until_ts") or 0
            if stamp is None or stamp != live_until:
                # The window is a different one now: it was extended
                # differently, or the laptop managed to sleep and the cycle
                # started again.
                log.warning("the decision %r is stale: stamp %s, in the state %s",
                            action, stamp, live_until)
                self.bot.answer(cid, t("sleep.stale"), alert=True)
                self.bot.edit(message_id, t("sleep.staletext"))
                return
            if action == "extend":
                state.extend(st, now, manual=True)
                state.touch(st, now)
                st["decision"] = "extend"
                st["decision_ts"] = now
                until = st["until_local"]
                text = t("sleep.extended", at=local_for_lang(until))
            else:
                # Not "sleep now" but "stop holding": Windows will count its
                # own fifteen minutes of idling as usual.
                st["until_ts"] = now
                st["until_local"] = local_label(now)
                st["decision"] = "sleep"
                st["decision_ts"] = now
                state.drop_manual(st)
                state.touch(st, now)
                until = None
                text = t("sleep.accepted")
        # We write after the lock: there is no reason to hold a flock on the
        # state file for the sake of a log entry.
        if until is None:
            log.info("the warning: let it sleep, hold released")
        else:
            log.info("the warning: extend, deadline until %s", until)
        # We remove the keyboard: there will be nothing left to press a second
        # time.
        self.bot.edit(message_id, text)


# --- forgotten hard holders --------------------------------------------------

# Once an hour, no more often: the question about a forgotten session is not
# urgent, and repeating it every half hour teaches people not to read it.
IDLE_ASK_EVERY = 3600


def human_span(seconds):
    if seconds >= 3600:
        h, m = divmod(int(seconds) // 60, 60)
        return t("span.hours", h=h, m=m)
    return t("span.minutes", m=int(seconds) // 60)


def idle_keyboard():
    # "Stop them" used to be here, but it shut down only code-server and the
    # dev server and did not touch the manual deadline — on a day when it was
    # precisely an indefinite hold doing the holding, the press would have
    # changed nothing. In its place is an entrance to the menu, where any hold
    # can be released; the frequent answers stay where they were.
    return [
        [{"text": t("idle.keep"), "callback_data": "idle_keep"}],
        [{"text": t("menu.extend"), "callback_data": "menu_extend"}],
        [{"text": t("idle.sleep"), "callback_data": "idle_sleep"}],
    ]


def check_idle_hold(bot):
    # There are hard holders but no traces of work — it looks as though a
    # session was left open. We ask, but only when the machine really is busy
    # with nothing: a long build without a single keystroke is work, and
    # interrupting it with a question is not the thing to do.
    now = int(time.time())
    data = read()
    if not data.get("hard_hold"):
        return
    if data.get("busy"):
        return
    idle = data.get("idle_seconds") or 0
    if idle < IDLE_SECONDS_THRESHOLD:
        return
    # 999999 is the detector's placeholder for "no interactive sessions at
    # all". Idling cannot be judged by it: it produced "277 hours without input"
    # on a machine that had been working since yesterday. No sessions means no
    # input to wait for either, and something else is holding then (a code-server
    # tab, tailnet traffic), so a question about a forgotten terminal is out of
    # place here.
    if idle >= IDLE_UNKNOWN:
        return
    asked = data.get("idle_asked_ts") or 0
    if now - asked < IDLE_ASK_EVERY:
        return

    since = data.get("hard_since") or 0
    if not since:
        # We are holding but do not know since when — writing "it has not slept
        # for 0 minutes" is worse than writing nothing at all: the number is the
        # first thing people read.
        return
    bot.send(t("idle.warn", since=local_label(since),
               held=human_span(now - since), idle=human_span(idle),
               who=reasons_lines(hold_reasons(data, now))), idle_keyboard())
    with locked() as st:
        st["idle_asked_ts"] = now
    log.info("asked about forgotten hard holders (idle %d s)", idle)


# --- the warning -------------------------------------------------------------

def sleep_reason(data, now):
    # Why things are heading for sleep. On its own "it will sleep in 30
    # minutes" does not tell a person what has happened and what they can do:
    # the holders are gone, only soft ones are left, or they asked for sleep
    # themselves — the cases differ, and the decision made by button depends on
    # them.
    from keepawake.state import refuses
    if refuses(data, now):
        return t("why.refused", who=holders_line(data))
    soft = holders_line(data, "soft")
    if soft != t("hold.nobody"):
        return t("why.soft", who=soft)
    return t("why.nobody")


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
    # disappearance.
    shown = read().get("ask_shown") or {}
    changed = False
    for repo in known_repos():
        name = os.path.basename(repo)
        question = pending_ask(repo)
        if not question:
            # The question is closed — we forget the stamp, otherwise the
            # dictionary grows for ever and the next question in the same second
            # would count as shown.
            if name in shown:
                shown.pop(name); changed = True
            continue
        # id is on questions laid out by this version; asked is the fallback
        # key for a question left over from the previous one (the daemon and the
        # orchestrator are updated separately, and they can diverge by one
        # restart).
        mark = question.get("id") or question.get("asked") or 0
        if shown.get(name) == mark:
            continue
        # Silent if the person is right now at the terminal where the question
        # was asked: they can already see it on the screen and will answer there.
        # The message goes out anyway — one can step away mid-step, and then it
        # is already waiting in the chat.
        bot.send(ask_text(name, question), ask_keyboard(name, question),
                 quiet=at_terminal(question))
        shown[name] = mark
        changed = True
        log.info("showed the sclaude question from %s: %r", name,
                 (question.get("prompt") or "")[:60])
    if changed:
        with locked() as st:
            st["ask_shown"] = shown


def check_warning(bot):
    now = int(time.time())
    data = read()
    if not needs_warning(data, now):
        return
    until = data["until_ts"]
    left = max(0, (until - now) // 60)
    text = t("sleep.warn", at=local_for_lang(data.get("until_local")) or "?",
             min=left, why=sleep_reason(data, now))
    msg_id = bot.send(text, warn_keyboard(until))
    if not msg_id:
        # The send failed — there is no network, and on a laptop it drops
        # regularly. We do not set the mark: otherwise the warning for this
        # deadline would never repeat and the laptop would sleep silently. The
        # loop's next turn will try again in 25 seconds, which fits comfortably
        # within half an hour.
        log.warning("the warning did not send — we will retry on the next turn")
        return
    with locked() as st:
        # We record the deadline the warning was for. Extending will move
        # until_ts, the mark will stop matching — and the next warning will come
        # for the new deadline, by itself.
        st["warned_for_ts"] = until
        st["warn_message_id"] = msg_id
    log.info("the warning was sent for %s", data.get("until_local"))


# --- start-up ----------------------------------------------------------------

def load_env():
    token = os.environ.get("KEEPAWAKE_BOT_TOKEN", "").strip()
    chat = os.environ.get("KEEPAWAKE_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit("keepawake: no KEEPAWAKE_BOT_TOKEN or KEEPAWAKE_CHAT_ID "
                 "(see ~/.config/keepawake/env)")

    # A bot's token is full access to the bot. Working silently with loose
    # permissions on the secrets file is unwise.
    env_file = os.path.expanduser("~/.config/keepawake/env")
    if os.path.exists(env_file):
        mode = os.stat(env_file).st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            sys.exit("keepawake: %s is readable by the group or everyone — chmod 600" % env_file)
    return token, chat


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    token, chat = load_env()
    bot = Bot(token, chat)
    handler = Handler(bot)

    def stop(signum, frame):
        # Without this a systemctl restart would leave a long getUpdates
        # hanging.
        bot.stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    saved = read().get("lang")
    if saved:
        set_lang(saved)
    log.info("the daemon has started, chat_id=%s, language=%s", chat, current())

    # The commands are a cheap second route to the menu: typed by hand when the
    # buttons are out of reach. They do not occupy the button in the input box
    # while doing so.
    bot.commands()
    bot.menu_button()

    # If we were restarted by a button, report it into that same message. That
    # same message carries the reply keyboard: setting it with a separate "I have
    # started" means writing to the chat on every restart of the daemon, and it
    # restarts both by a button in the menu and after a reboot. Telegram has no
    # silent way of setting a keyboard — it only arrives with a message.
    try:
        if not report_restart(bot):
            ensure_anchor(bot)
    except Exception as exc:
        log.warning("the restart report: %s", exc)

    backoff = 1

    while not bot.stopped:
        try:
            out = bot.call("getUpdates", http_timeout=POLL_TIMEOUT + 10,
                           offset=bot.offset, timeout=POLL_TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                # A second instance on the same token: two daemons would for
                # ever intercept each other's updates, and carrying on quietly
                # will not do.
                sys.exit("keepawake: a second instance of the daemon is running (HTTP 409)")
            if exc.code == 401:
                sys.exit("keepawake: wrong token (HTTP 401)")
            log.warning("HTTP %s, pausing %d s", exc.code, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue
        except Exception as exc:
            log.warning("network: %s, pausing %d s", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            continue

        backoff = 1
        for upd in out.get("result") or []:
            # We move the offset BEFORE handling: otherwise the update the
            # handler died on would arrive for ever and bring the daemon down for
            # ever. Losing one press is better than looping.
            bot.offset = upd["update_id"] + 1
            try:
                if "message" in upd:
                    msg = upd["message"]
                    if (msg.get("chat") or {}).get("id") != bot.chat_id:
                        log.warning("a foreign chat: %s", (msg.get("chat") or {}).get("id"))
                        continue
                    remember_lang(msg.get("from"))
                    handler.message(msg)
                elif "callback_query" in upd:
                    cq = upd["callback_query"]
                    chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
                    if chat_id != bot.chat_id:
                        log.warning("a foreign chat in the callback: %s", chat_id)
                        continue
                    remember_lang(cq.get("from"))
                    handler.callback(cq)
            except Exception as exc:
                log.exception("handling the update: %s", exc)

        try:
            check_warning(bot)
        except Exception as exc:
            log.exception("checking the warning: %s", exc)

        try:
            check_idle_hold(bot)
        except Exception as exc:
            log.exception("checking forgotten holders: %s", exc)

        # An orchestrator's question waits for the person, not the other way
        # round: the later it reaches the chat, the longer the step stands. A
        # turn here is the same 25 seconds of long-polling as everything else,
        # and that is an order of magnitude faster than walking to the laptop.
        try:
            check_asks(bot)
        except Exception as exc:
            log.exception("checking sclaude's questions: %s", exc)

    log.info("the daemon has stopped")


if __name__ == "__main__":
    main()
