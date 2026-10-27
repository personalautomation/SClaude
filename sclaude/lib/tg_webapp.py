#!/usr/bin/env python3
#
# Who may open a feature through the Telegram Mini App: the check behind
# `sclaude-proxy --gate`, the entry `tailscale funnel` publishes while the
# person looks at a feature from the phone.
#
# Telegram hands a Mini App `initData`, a query string signed with the bot's
# token. Checking it proves the page was opened from this bot, by the account
# that owns it (KEEPAWAKE_CHAT_ID — a private chat's id is the user's id), and
# recently. After that the gate gives the browser a cookie of its own, signed
# with a key derived from the same token, so that every later request of the
# page is let in without Telegram's help.
#
# The token never leaves this machine and is the only secret: replacing it in
# BotFather revokes every cookie at once.
#
# Two sides, two origins (bin/sclaude-proxy): the bot's own pages and
# code-server on one, the features on another, so that a feature's page can
# neither read initData nor press the menu. initData is only ever handed to
# the bot's side, which gives the features' side a ticket for it: short-lived,
# good once, and good for nothing on the bot's side. Each side's cookie has a
# key of its own, so neither passes for the other.
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import parse_qsl, urlencode

# How old an initData may be. Telegram signs it when the button is pressed;
# a day is plenty for a page that is opened at once.
INIT_MAX_AGE = 86400
# How long the gate's cookie lets a browser in.
COOKIE_TTL = 12 * 3600
# How long a ticket from the bot's side to the features' side lasts: the
# page goes there at once.
TICKET_TTL = 60


def _webapp_secret(token):
    # Telegram's rule: the key is HMAC-SHA256 of the token under "WebAppData".
    return hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()


# The key of each thing the gate signs: a cookie can never pass for initData
# or back, nor one side's cookie for the other's, nor a ticket for either.
PURPOSES = {"cookie": b"sclaude-gate-cookie", "app": b"sclaude-gate-app-cookie",
            "ticket": b"sclaude-gate-ticket"}


def _cookie_secret(token, purpose="cookie"):
    return hmac.new(PURPOSES[purpose], token.encode(), hashlib.sha256).digest()


def sign_init_data(fields, token):
    """initData for these fields, signed as Telegram signs it — for the tests."""
    check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    digest = hmac.new(_webapp_secret(token), check.encode(), hashlib.sha256).hexdigest()
    return urlencode(dict(fields, hash=digest))


def verify_init_data(raw, token, owner_id, max_age=INIT_MAX_AGE, now=None):
    """True when initData is Telegram's, fresh, and from owner_id."""
    if not raw or not token:
        return False
    fields = dict(parse_qsl(raw, keep_blank_values=True))
    given = fields.pop("hash", "")
    check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    want = hmac.new(_webapp_secret(token), check.encode(), hashlib.sha256).hexdigest()
    if not given or not hmac.compare_digest(want, given):
        return False
    try:
        signed_at = int(fields.get("auth_date", ""))
        user = json.loads(fields.get("user", "")) or {}
        uid = int(user.get("id"))
    except (TypeError, ValueError, AttributeError):
        return False
    now = time.time() if now is None else now
    if now - signed_at > max_age:
        return False
    return uid == int(owner_id)


def sign_cookie(token, ttl=COOKIE_TTL, now=None, purpose="cookie"):
    """`<expiry>.<hmac>` — the value of the gate's cookie (purpose "cookie"
    on the bot's side, "app" on the features')."""
    expiry = int((time.time() if now is None else now) + ttl)
    mac = hmac.new(_cookie_secret(token, purpose), str(expiry).encode(),
                   hashlib.sha256).hexdigest()
    return "%d.%s" % (expiry, mac)


def cookie_valid(value, token, now=None, purpose="cookie"):
    expiry, _, mac = (value or "").partition(".")
    if not expiry.isdigit() or not mac or not token:
        return False
    want = hmac.new(_cookie_secret(token, purpose), expiry.encode(),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, mac):
        return False
    return int(expiry) > (time.time() if now is None else now)


def sign_ticket(token, now=None):
    """`<expiry>-<nonce>.<hmac>`: the bot's side lets the features' side in.
    The nonce makes every ticket different, so that one used is told apart."""
    expiry = int((time.time() if now is None else now) + TICKET_TTL)
    body = "%d-%s" % (expiry, secrets.token_hex(8))
    mac = hmac.new(_cookie_secret(token, "ticket"), body.encode(), hashlib.sha256).hexdigest()
    return "%s.%s" % (body, mac)


def ticket_valid(value, token, now=None):
    """The ticket's expiry when it is the gate's and not yet out, else 0.
    Using it once is the gate's to remember."""
    body, _, mac = (value or "").partition(".")
    expiry, _, nonce = body.partition("-")
    if not expiry.isdigit() or not nonce or not mac or not token:
        return 0
    want = hmac.new(_cookie_secret(token, "ticket"), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, mac):
        return 0
    return int(expiry) if int(expiry) > (time.time() if now is None else now) else 0


def read_env(path):
    """{name: value} of a KEY=value file such as ~/.config/keepawake/env."""
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                out[name.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return out
