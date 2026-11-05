# keepawake's Telegram bot — the machine's services the bot shows: Chrome's
# debugging port, code-server and the features' dev servers registered for the
# proxy.
#
# Part of the bot that keepawake/telegramd.py runs.

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from keepawake.i18n import t
from keepawake import menus, phone_access, repos, sessions, shell, status_report


log = logging.getLogger("keepawake")


def code_app_button(origin, folder=""):
    # code-server inside the Mini App, through the gate's /__code/ (an
    # experiment). Only while phone access is on and code-server is up: the
    # gate starts nothing.
    if not origin or not code_running():
        return []
    # Always a folder: without one code-server reopens whatever was open in
    # it last, not the repository the screen names (code_folder).
    folder = folder or repos.repo_choice() or os.path.expanduser("~")
    path = "/__code/?folder=" + urllib.parse.quote(folder)
    return [{"text": t("code.app"), "style": "success", "web_app": {
        "url": "%s/__sclaude/tg?p=%s" % (origin, urllib.parse.quote(path, safe=""))}}]


def chrome_keyboard(config=None):
    # The laptop's browser and every feature at once. A feature's own
    # buttons — open, phone, start, stop — are on its card in its topic.
    browser_up = phone_access.port_open(CHROME_PORT)
    origin = phone_access.gate_origin(config)

    # The list of every feature first, laid out like a feature: a caption,
    # then where to open it. 🌐 is the laptop's Chrome at localhost:3000,
    # started if it is down; ⏹ closes that Chrome, and only while it runs.
    rows = [[{"text": t("chrome.all"), "callback_data": "noop"}]]
    first = [{"text": t("chrome.open"), "callback_data": "chrome_start"}] + phone_access.phone_button(origin, "")
    if browser_up:
        first.append({"text": t("chrome.stopbrowser"), "callback_data": "chrome_stop"})
    rows.append(first)
    # A feature's own buttons — open, phone, start, stop — are on its card in
    # its topic now; here the browser and the list of every feature remain.
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows


def code_running():
    out = shell.run("systemctl --user is-active code-server.service")
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
            with open(sessions.state_path(wt)) as fh:
                port = (json.load(fh).get("dev") or {}).get("port")
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(port, int):
            continue
        out.append((name, wt, port, phone_access.port_open(port)))
    return out

# This much silence counts as "the person left without closing the session".
# The value must match IDLE_AFTER in bin/keepawake, which measures it.
IDLE_SECONDS_THRESHOLD = 3600

# The value with which the detector marks "no interactive sessions at all".
# Must match the placeholder in idle_seconds() from bin/keepawake.
IDLE_UNKNOWN = 999999


def chrome_screen():
    """(text, keyboard) of the Chrome screen, from one look at tailscale."""
    config = phone_access.serve_config()
    return chrome_text(config), chrome_keyboard(config)


def chrome_text(config=None):
    # The laptop's browser and the proxy it opens features through. Each
    # feature's addresses and dev server are on its card, and phone access
    # in Settings. config is kept for the callers that look at tailscale once.
    state_label = t("chrome.up") if phone_access.port_open(CHROME_PORT) else t("chrome.down")
    proxy_label = t("chrome.proxyup") if phone_access.port_open(DEV_PORT) else t("chrome.proxydown")
    return t("chrome.title", state=state_label, proxy=proxy_label, port=CHROME_PORT)


def code_folder():
    # Which directory the server will open at its next start — the same choice
    # as sclaude's: keeping two different "current projects" would confuse a
    # person who has switched one and expects the second to have switched
    # too.
    choice = repos.repo_choice()
    return os.path.basename(choice) if choice else "~"


def code_password():
    """code-server's password from its config, or ""."""
    path = os.path.expanduser("~/.config/code-server/config.yaml")
    try:
        for line in open(path):
            if line.strip().startswith("password:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def code_keyboard(folder=""):
    # folder: the worktree the 📲 button opens, when the menu page stands on
    # a feature.
    running = code_running()
    row = []
    if running:
        row.append({"text": t("code.restart"), "callback_data": "code_restart"})
        row.append({"text": t("code.stop"), "callback_data": "code_stop"})
    else:
        row.append({"text": t("code.start"), "callback_data": "code_start"})
    rows = [row]
    app = code_app_button(phone_access.gate_origin(), folder)
    if app:
        rows.append(app)
    return rows + [[{"text": t("menu.back"), "callback_data": "menu_back"}]]


def code_text(folder_name=""):
    state_label = (t("code.running") if code_running()
                   else t("code.stoppedpage") if menus.ON_PAGE else t("code.stopped"))
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
    if menus.ON_PAGE:
        # The page is not kept in the chat's history, and is let in for the
        # owner only: the password can be shown where it is typed.
        pw = code_password()
        return t("code.titlepage", state=state_label,
                 folder=t("code.folder", name=status_report.escape(folder_name or code_folder())),
                 password=t("code.password", pw=status_report.escape(pw)) if pw else t("code.nopassword"))
    return t("code.title", state=state_label,
             folder=t("code.folder", name=status_report.escape(code_folder())),
             url=code_url(), local="http://127.0.0.1:8080")
