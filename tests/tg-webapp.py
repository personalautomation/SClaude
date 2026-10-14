#!/usr/bin/env python3
#
# sclaude/lib/tg_webapp.py: the check behind `sclaude-proxy --gate`. Telegram's
# initData is accepted only when signed with this bot's token, fresh, and from
# the owner; the gate's cookie only when it is its own and unexpired.
#
# Run it with: python3 tests/tg-webapp.py
import hashlib
import hmac
import json
import os
import sys
import tempfile
from urllib.parse import urlencode

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sclaude", "lib"))
import tg_webapp  # noqa: E402

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


TOKEN = "123456:ABC-test"
OWNER = 777
NOW = 1_800_000_000


def telegram_signed(fields, token=TOKEN):
    # Written out from Telegram's documentation rather than through the module,
    # so that the module is checked against the rule and not against itself.
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check_string = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    digest = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(dict(fields, hash=digest))


user = json.dumps({"id": OWNER, "first_name": "A", "language_code": "en"})
fields = {"auth_date": str(NOW - 60), "query_id": "AAE", "user": user}
good = telegram_signed(fields)

check("the owner, fresh", tg_webapp.verify_init_data(good, TOKEN, OWNER, now=NOW), True)
check("the module signs as Telegram does",
      tg_webapp.verify_init_data(tg_webapp.sign_init_data(fields, TOKEN), TOKEN, OWNER, now=NOW),
      True)
check("another user", tg_webapp.verify_init_data(good, TOKEN, OWNER + 1, now=NOW), False)
check("another bot", tg_webapp.verify_init_data(telegram_signed(fields, "9:other"),
                                                TOKEN, OWNER, now=NOW), False)
check("a field changed after signing",
      tg_webapp.verify_init_data(good.replace("query_id=AAE", "query_id=AAF"),
                                 TOKEN, OWNER, now=NOW), False)
check("no hash", tg_webapp.verify_init_data(urlencode(fields), TOKEN, OWNER, now=NOW), False)
check("too old", tg_webapp.verify_init_data(good, TOKEN, OWNER, now=NOW + 2 * 86400), False)
check("no user", tg_webapp.verify_init_data(telegram_signed({"auth_date": str(NOW)}),
                                            TOKEN, OWNER, now=NOW), False)
check("empty", tg_webapp.verify_init_data("", TOKEN, OWNER, now=NOW), False)
check("no token", tg_webapp.verify_init_data(good, "", OWNER, now=NOW), False)

cookie = tg_webapp.sign_cookie(TOKEN, ttl=3600, now=NOW)
check("a fresh cookie", tg_webapp.cookie_valid(cookie, TOKEN, now=NOW + 10), True)
check("an expired cookie", tg_webapp.cookie_valid(cookie, TOKEN, now=NOW + 3601), False)
check("a cookie of another token", tg_webapp.cookie_valid(cookie, "9:other", now=NOW), False)
expiry, _, mac = cookie.partition(".")
check("a pushed-out expiry", tg_webapp.cookie_valid("%d.%s" % (int(expiry) + 99999, mac),
                                                    TOKEN, now=NOW), False)
check("garbage", tg_webapp.cookie_valid("x.y", TOKEN, now=NOW), False)
check("a signed initData is no cookie",
      tg_webapp.cookie_valid("%s.%s" % (expiry, good.rsplit("hash=", 1)[1]), TOKEN, now=NOW),
      False)

with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
    fh.write("# comment\nKEEPAWAKE_BOT_TOKEN='%s'\n\nKEEPAWAKE_CHAT_ID=%d\n" % (TOKEN, OWNER))
try:
    check("the env file is read", tg_webapp.read_env(fh.name),
          {"KEEPAWAKE_BOT_TOKEN": TOKEN, "KEEPAWAKE_CHAT_ID": str(OWNER)})
finally:
    os.unlink(fh.name)
check("a missing env file is empty", tg_webapp.read_env("/nonexistent/env"), {})

for name, want, got in failures:
    print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
print("%d/%d passed" % (total - len(failures), total))
sys.exit(1 if failures else 0)
