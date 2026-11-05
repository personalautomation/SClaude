# keepawake's Telegram bot — the status screen: what holds the machine awake
# and why.
#
# Part of the bot that keepawake/telegramd.py runs.

import logging
import re

from keepawake.i18n import current, ssh_holders, t
from keepawake.state import local_label
from keepawake import shell


log = logging.getLogger("keepawake")


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
    body = strip_ansi(shell.run("keepawake status --raw"))
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
    from keepawake.state import manual_until
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
