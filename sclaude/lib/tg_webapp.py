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
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl, urlencode

# How old an initData may be. Telegram signs it when the button is pressed;
# a day is plenty for a page that is opened at once.
INIT_MAX_AGE = 86400
# How long the gate's cookie lets a browser in.
COOKIE_TTL = 12 * 3600


def _webapp_secret(token):
    # Telegram's rule: the key is HMAC-SHA256 of the token under "WebAppData".
    return hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()


def _cookie_secret(token):
    # A key of its own, so that a cookie can never pass for initData or back.
    return hmac.new(b"sclaude-gate-cookie", token.encode(), hashlib.sha256).digest()


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


def sign_cookie(token, ttl=COOKIE_TTL, now=None):
    """`<expiry>.<hmac>` — the value of the gate's cookie."""
    expiry = int((time.time() if now is None else now) + ttl)
    mac = hmac.new(_cookie_secret(token), str(expiry).encode(), hashlib.sha256).hexdigest()
    return "%d.%s" % (expiry, mac)


def cookie_valid(value, token, now=None):
    expiry, _, mac = (value or "").partition(".")
    if not expiry.isdigit() or not mac or not token:
        return False
    want = hmac.new(_cookie_secret(token), expiry.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, mac):
        return False
    return int(expiry) > (time.time() if now is None else now)


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
