#!/usr/bin/env python3
#
# Signing a feature's browser in as the developer, with one click.
#
# Every feature answers on a host of its own (<feature>.localhost:3000, see
# bin/sclaude-proxy), which keeps their cookies apart — and keeps the passwords
# a browser saves apart too, so a new feature starts with none and the person
# types theirs again. This signs in without one: sclaude-proxy's
# /__sclaude/login asks the feature's own Supabase for a sign-in token
# (the admin API, with the secret key the feature's dev server already reads)
# and sends the browser to the product's own route for email links, which
# verifies the token and sets the product's cookies itself. No cookie format
# of the product is known here, and no mail is sent.
#
# Two halves, each where it belongs:
#
#   the product   `devLogin` in .sclaude/config.json, the route that takes
#                 `token_hash`, `type` and `next` (`{"path": "/auth/confirm"}`).
#                 Absent, nothing is offered. Read from main, like every
#                 protection (envs.guarded).
#   the person    who to sign in as: the first line of ~/.claude/sclaude/dev-login
#                 (SCLAUDE_DEV_LOGIN_FILE moves it), else git user.email of
#                 the orchestrator's checkout, as developer.sh names people.
#                 Per machine, never committed: each developer is their own
#                 user.
#
# Never against a protected environment. A feature on its own local database
# (db.env, featuredb.sh) uses that; any other is the environment its
# .env.local points at, and only one a feature may run on (envs.runnable).
# The proxy answers the phone too, and one tap must not hand out a session on
# somebody's real data.
#
# Signing in as somebody else — `as` (link's as_address), and the list of
# the people a database has (users) — is for a feature's own local database
# alone. Its people are the seed's and its own tests'; a shared environment,
# however runnable, holds accounts other people use, and a link that turns
# whoever holds it into any of them is a step too far for one click. There
# only the developer's own address signs in.
#
# The token is a recovery one, not a magic link: both sign in once verified,
# but a magic link for an address the database does not have creates that
# user on the way, and a mistyped address became a new, empty account on a
# database others may share. Recovery is only issued for a user that exists.
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import envs  # noqa: E402

INSTRUMENTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
LOGIN_FILE = os.environ.get("SCLAUDE_DEV_LOGIN_FILE") or os.path.expanduser(
    "~/.claude/sclaude/dev-login")
SECRET_KEY = "SUPABASE_SECRET_KEY"
LOOPBACK = ("localhost", "127.0.0.1", "::1")
# What `as` may be: one address, nothing that could break out of a query,
# a header or a page.
ADDRESS = re.compile(r"^[^\s@<>\"'\\]+@[^\s@<>\"'\\]+$")
# The list of users is read page by page, up to this many pages: a database
# with more people than that is not a seed.
USERS_PER_PAGE = 200
USERS_PAGES = 50


class Refused(Exception):
    """Why this feature cannot be signed into, in words for the person."""


def main_root(wt):
    """The main checkout of a tree: where the environments' files are named from."""
    try:
        done = subprocess.run(["git", "-C", wt, "rev-parse", "--path-format=absolute",
                               "--git-common-dir"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return wt
    common = done.stdout.strip()
    return os.path.dirname(common) if done.returncode == 0 and common else wt


def route(data):
    """The product's route for email links, or None when it names none."""
    conf = data.get("devLogin")
    path = conf.get("path") if isinstance(conf, dict) else None
    if isinstance(path, str) and path.startswith("/") and not path.startswith("//"):
        return path
    return None


def offered(wt):
    """Whether the product behind a tree has asked for the button at all."""
    return route(envs.guarded(main_root(wt))) is not None


def email():
    """Who to sign in as, or "" when nothing says."""
    try:
        with open(LOGIN_FILE, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    for args in (["git", "-C", INSTRUMENTS, "config", "user.email"],
                 ["git", "config", "user.email"]):
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return ""


def own_db(wt):
    """The feature's own db.env, written by featuredb.sh, or "" when it has none."""
    path = os.path.join(wt, ".sclaude", "local", "feature", "db.env")
    return path if os.path.isfile(path) else ""


def valid_address(value):
    """An address `as` may carry, or ""."""
    value = (value or "").strip()
    return value if len(value) <= 254 and ADDRESS.match(value) else ""


def supabase(wt):
    """(path, Supabase URL, secret key, own local database?) for a tree, or Refused."""
    root = main_root(wt)
    data = envs.guarded(root)
    path = route(data)
    if not path:
        raise Refused("the project's .sclaude/config.json has no devLogin, so sclaude "
                      "does not know where the product takes a sign-in link")
    keys = envs.keys(root, data)
    secret_key = keys.get("secretKey") or SECRET_KEY
    own = own_db(wt)
    if own:
        values = envs.read_env(own)
        url = values.get(keys["supabaseUrl"]) or ""
        # Written by sclaude for a stack on this machine; anything else in it
        # is not that file any more.
        if (urlsplit(url).hostname or "") not in LOOPBACK:
            raise Refused("this feature's db.env names a database that is not on this machine")
    else:
        name = envs.current(root, wt, data)
        if not name:
            raise Refused("this tree's .env.local points at none of the project's environments")
        if envs.protected(root, name, data) or not envs.runnable(root, name, data):
            raise Refused("this tree is on %s, which is not an environment to sign into "
                          "with one click" % name)
        values = envs.read_env(envs.env_file(root, name, data) or "")
        url = values.get(keys["supabaseUrl"]) or ""
    secret = values.get(secret_key) or ""
    if not url or not secret:
        raise Refused("no %s and %s in this feature's environment"
                      % (keys["supabaseUrl"], secret_key))
    return path, url.rstrip("/"), secret, bool(own)


def anybody(wt):
    """Whether a tree can sign in as any user: its own local database, usable."""
    try:
        return supabase(wt)[3]
    except Refused:
        return False


def admin(url, secret, method, path, body=None, timeout=10):
    """One call to GoTrue's admin API: (status, parsed answer)."""
    req = urllib.request.Request(url + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"apikey": secret, "Authorization": "Bearer " + secret,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            said = json.load(exc)
        except (ValueError, AttributeError):
            said = {}
        return exc.code, said if isinstance(said, dict) else {}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Refused("Supabase did not answer at %s: %s" % (url, getattr(exc, "reason", exc)))


def said(data):
    return data.get("msg") or data.get("message") or data.get("error_description") or ""


def users(wt):
    """The addresses a feature's own local database can sign in as, sorted."""
    _path, url, secret, local = supabase(wt)
    if not local:
        raise Refused("this feature has no local database of its own, so it signs in "
                      "only as %s" % (email() or "the developer"))
    found = []
    for page in range(1, USERS_PAGES + 1):
        code, data = admin(url, secret, "GET", "/auth/v1/admin/users?page=%d&per_page=%d"
                           % (page, USERS_PER_PAGE))
        if code != 200:
            raise Refused("Supabase refused the list of users: %s%s"
                          % (code, " — " + said(data) if said(data) else ""))
        batch = data.get("users") if isinstance(data.get("users"), list) else []
        found += batch
        if len(batch) < USERS_PER_PAGE:
            break
    return sorted({u["email"] for u in found
                   if isinstance(u, dict) and isinstance(u.get("email"), str) and u["email"]},
                  key=str.lower)


def token(url, secret, address, timeout=10, named=False):
    """(hashed token, its type) of a fresh sign-in link for an address;
    `named` when the address came with the link rather than from LOGIN_FILE."""
    code, data = admin(url, secret, "POST", "/auth/v1/admin/generate_link",
                       {"type": "recovery", "email": address}, timeout)
    if code == 404:
        raise Refused("this database has no user %s%s" % (address, "" if named else
                      ": put the address you sign in with in %s" % LOGIN_FILE))
    if code != 200:
        raise Refused("Supabase refused the link: %s%s"
                      % (code, " — " + said(data) if said(data) else ""))
    # GoTrue puts the link's fields at the top; supabase-js moves them under
    # `properties`. Either is read.
    props = data.get("properties") if isinstance(data.get("properties"), dict) else data
    hashed = props.get("hashed_token")
    if not isinstance(hashed, str) or not hashed:
        raise Refused("Supabase answered without a token")
    kind = props.get("verification_type")
    return hashed, kind if isinstance(kind, str) and kind else "recovery"


def safe_next(value):
    """A path on the same site to land on, or "/".

    No control character either: it goes into a Location header as it is,
    where CR LF would start headers of the caller's choosing, and a browser
    drops a tab or a newline from an address, so "/<tab>/evil.com" lands
    on evil.com."""
    if isinstance(value, str) and value.startswith("/") and not value.startswith("//") \
            and "\\" not in value and not any(ord(c) < 0x20 or c == "\x7f" for c in value):
        return value
    return "/"


def link(wt, next_path="/", as_address=""):
    """The path and query on the feature's host that sign the browser in:
    as the developer, or as `as_address` on the feature's own database."""
    own = email()
    address = as_address or own
    if not address:
        raise Refused("nobody to sign in as: put an address in %s" % LOGIN_FILE)
    path, url, secret, local = supabase(wt)
    if address.lower() != own.lower() and not local:
        raise Refused("this feature has no local database of its own, so it signs in "
                      "only as %s, not as %s" % (own or "the developer", address))
    hashed, kind = token(url, secret, address, named=address.lower() != own.lower())
    return "%s?%s" % (path, urlencode({"token_hash": hashed, "type": kind,
                                        "next": safe_next(next_path)}))
