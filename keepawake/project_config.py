# keepawake's Telegram bot — the project's .sclaude/config.json on the phone:
# its sections explained, and a setting changed through `sclaude config set`.
#
# Part of the bot that keepawake/telegramd.py runs.

import json
import logging
import os
import shlex
import sys

from keepawake.i18n import t
from keepawake import menus, repos, shell, status_report


log = logging.getLogger("keepawake")


# --- the project's config ----------------------------------------------------
#
# The screen `sclaude config` draws in the terminal, as a menu: every section of
# the repository's .sclaude/config.json, what it holds and what it is for, in
# the words of sclaude/config.example.json (config_menu.py, which the terminal's
# screen reads too). A section with fixed choices is set from here, through
# `sclaude config set`, so that what a choice implies (review's Actions
# workflows) is done as it is at the terminal; the rest are structures edited
# in the file.
#
# The explanations are sclaude's, in English whatever the bot's language: one
# text, kept in step with the example file a person copies.

SCLAUDE_LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "sclaude", "lib")
CONFIG_EXAMPLE = os.path.join(os.path.dirname(SCLAUDE_LIB), "config.example.json")


def sclaude_module(name):
    """A module of sclaude/lib, imported on first use: the bot reads the
    config and the issues with sclaude's own code."""
    if SCLAUDE_LIB not in sys.path:
        sys.path.insert(0, SCLAUDE_LIB)
    import _path  # noqa: F401 — every folder of sclaude/lib on the path
    return __import__(name)


def config_menu():
    return sclaude_module("config_menu")


def config_path(repo):
    # The main checkout's committed one, what the project recommends; a choice
    # set here goes beside it, to this machine's .sclaude/local/config.json
    # (config_file in config.sh, set_value in config_menu.py).
    return os.path.join(repo, ".sclaude", "config.json")


def cfg_data(prefix, name, *rest):
    """A config button's data. Telegram refuses a keyboard for one button
    over 64 bytes: the remembered repository is then left out of a screen's
    button (the press finds it again), and anything longer still does
    nothing."""
    data = ":".join((prefix, name) + rest)
    # Not for a value set: a press on an old message would find the
    # repository chosen since, and change another project's config.
    if len(data.encode("utf-8")) > 64 and prefix != "cfgset" \
            and name == os.path.basename(repos.repo_choice()):
        data = ":".join((prefix, "") + rest)
    return data if len(data.encode("utf-8")) <= 64 else "noop"


def config_text_rows(name):
    """The list of sections: (text, keyboard)."""
    repo = repos.repo_path(name)
    if not repo:
        return t("repo.norepos"), menus.repos_keyboard()
    menu = config_menu()
    path = config_path(repo)
    data = menu.effective(path)
    broken = menu.unreadable(path)
    mine = menu.overrides(path)
    known = menu.explanations(CONFIG_EXAMPLE)
    text = t("cfg.title", repo=status_report.escape(name))
    if broken or not os.path.exists(path):
        text += t("cfg.broken") if broken else t("cfg.nofile")
    rows = []
    # The sections with choices first: they are what can be done here.
    keys = sorted(known, key=lambda k: k not in menu.CHOICES) + [k for k in data if k not in known]
    for key in keys:
        summary = menu.summary(key, data.get(key))
        mark = "⚙️ " if key in menu.CHOICES else ""
        # 📌: set on this machine, over what the project recommends.
        label = "%s%s · %s%s" % (mark, key, summary, " 📌" if key in mine else "")
        rows.append([{"text": label[:60], "callback_data": cfg_data("cfg", name, key)}])
    rows.append([{"text": t("cfg.torepo"), "callback_data": "repo:" + name},
                 {"text": t("menu.back"), "callback_data": "menu_back"}])
    return text, rows


def config_section(name, key, note=""):
    """One section: its explanation and value, and its choices when it has
    them, the one in force marked."""
    repo = repos.repo_path(name)
    if not repo:
        return t("repo.norepos"), menus.repos_keyboard()
    menu = config_menu()
    data = menu.effective(config_path(repo))
    known = menu.explanations(CONFIG_EXAMPLE)
    text = (note + "\n\n" if note else "") + "<b>%s</b>\n" % status_report.escape(key)
    text += status_report.escape(known.get(key) or t("cfg.unknown"))
    if key in data:
        value = json.dumps(data[key], indent=2, ensure_ascii=False)
        text += "\n\n" + t("cfg.now") + "\n<pre>%s</pre>" % status_report.escape(value[:1500])
    else:
        text += "\n\n" + t("cfg.notset")
    if key in menu.overrides(config_path(repo)):
        text += "\n" + t("cfg.mine", value=status_report.escape(menu.recommended(config_path(repo), key)))
    rows = []
    choices = menu.CHOICES.get(key) or []
    if choices and not os.path.exists(config_path(repo)):
        # A file of one key would pass for the project's config: `sclaude new`
        # offers to write the whole of it only where there is none.
        text += "\n\n" + t("cfg.writefirst")
    elif choices and cfg_data("cfgset", name, key, choices[0][0]) == "noop":
        # The button would do nothing: say so, rather than offer it.
        text += "\n\n" + t("cfg.toolong")
    elif choices:
        now = data.get(key) if isinstance(data.get(key), str) else menu.default(key)
        text += "\n"
        for value, meaning in choices:
            text += "\n• <b>%s</b> — %s" % (status_report.escape(value), status_report.escape(meaning))
            rows.append([{"text": ("✓ " if value == now else "") + value,
                          "callback_data": cfg_data("cfgset", name, key, value)}])
        text += "\n\n" + t("cfg.commit")
    else:
        text += "\n\n" + t("cfg.infile")
    rows.append([{"text": t("cfg.tolist"), "callback_data": cfg_data("cfg", name)}])
    return text, rows


def config_set(name, key, value, runner=None):
    """Set one section with choices, as the terminal's screen does:
    (whether it changed, the line saying what happened or why not).
    runner: how the command is run (the page's lets its lock go)."""
    repo = repos.repo_path(name)
    menu = config_menu()
    if not repo or not os.path.exists(config_path(repo)) \
            or value not in [v for v, _ in menu.CHOICES.get(key) or []]:
        log.warning("config of %r: %r cannot be set to %r here", name, key, value)
        return False, t("cfg.notchanged", section=status_report.escape(key))
    data = menu.effective(config_path(repo))
    if (data.get(key) if key in data else menu.default(key)) == value:
        # Nothing to write, and nothing to switch on or off again.
        return False, t("cfg.same", section=status_report.escape(key), value=status_report.escape(value))
    out = (runner or shell.run)("cd %s && sclaude config set %s %s 2>&1; echo \"rc=$?\""
                          % (shlex.quote(repo), shlex.quote(key), shlex.quote(value)), timeout=90)
    if not out.rstrip().endswith("rc=0") and menu.effective(config_path(repo)).get(key) == value:
        # Written, and what follows it (review's Actions) did not finish in
        # time: the value is set, and the line says what may be left.
        log.warning("sclaude config set %s %s in %s did not finish: %s",
                    key, value, repo, out.strip()[-300:])
        return True, t("cfg.setpartly", section=status_report.escape(key), value=status_report.escape(value))
    if not out.rstrip().endswith("rc=0"):
        log.warning("sclaude config set %s %s in %s: %s", key, value, repo, out.strip()[-300:])
        return False, t("cfg.notchanged", section=status_report.escape(key))
    log.info("config of %s: %s = %s", name, key, value)
    return True, t("cfg.set", section=status_report.escape(key), value=status_report.escape(value))


def config_press(data_raw, runner=None):
    """(text, keyboard, the line saying what changed or None) after a press
    on a config button."""
    prefix, _, rest = data_raw.partition(":")
    parts = rest.split(":")
    # cfg::<key> — the remembered repository, too long for the data.
    name = parts[0] or os.path.basename(repos.repo_choice())
    if prefix == "cfgset" and len(parts) == 3:
        changed, line = config_set(name, parts[1], parts[2], runner)
        return config_section(name, parts[1], line) + (line if changed else None,)
    if len(parts) >= 2 and parts[1]:
        return config_section(name, parts[1]) + (None,)
    return config_text_rows(name) + (None,)
