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
# The token is a recovery one, not a magic link: both sign in once verified,
# but a magic link for an address the database does not have creates that
# user on the way, and a mistyped address became a new, empty account on a
# database others may share. Recovery is only issued for a user that exists.
import json
import os
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


def supabase(wt):
    """(path, Supabase URL, secret key) for a tree, or Refused."""
    root = main_root(wt)
    data = envs.guarded(root)
    path = route(data)
    if not path:
        raise Refused("the project's .sclaude/config.json has no devLogin, so sclaude "
                      "does not know where the product takes a sign-in link")
    keys = envs.keys(root, data)
    secret_key = keys.get("secretKey") or SECRET_KEY
    own = os.path.join(wt, ".sclaude", "local", "feature", "db.env")
    if os.path.isfile(own):
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
    return path, url.rstrip("/"), secret


def token(url, secret, address, timeout=10):
    """(hashed token, its type) of a fresh sign-in link for an address."""
    body = json.dumps({"type": "recovery", "email": address}).encode()
    req = urllib.request.Request(url + "/auth/v1/admin/generate_link", data=body, method="POST",
                                 headers={"apikey": secret, "Authorization": "Bearer " + secret,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise Refused("this database has no user %s: put the address you sign in "
                          "with in %s" % (address, LOGIN_FILE))
        try:
            said = json.load(exc)
            said = said.get("msg") or said.get("message") or said.get("error_description") or ""
        except (ValueError, AttributeError):
            said = ""
        raise Refused("Supabase refused the link: %s%s" % (exc.code, " — " + said if said else ""))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Refused("Supabase did not answer at %s: %s" % (url, getattr(exc, "reason", exc)))
    # GoTrue puts the link's fields at the top; supabase-js moves them under
    # `properties`. Either is read.
    props = data.get("properties") if isinstance(data.get("properties"), dict) else data
    hashed = props.get("hashed_token")
    if not isinstance(hashed, str) or not hashed:
        raise Refused("Supabase answered without a token")
    kind = props.get("verification_type")
    return hashed, kind if isinstance(kind, str) and kind else "recovery"


def safe_next(value):
    """A path on the same site to land on, or "/"."""
    if isinstance(value, str) and value.startswith("/") and not value.startswith("//") \
            and "\\" not in value:
        return value
    return "/"


def link(wt, next_path="/"):
    """The path and query on the feature's host that sign the browser in."""
    address = email()
    if not address:
        raise Refused("nobody to sign in as: put an address in %s" % LOGIN_FILE)
    path, url, secret = supabase(wt)
    hashed, kind = token(url, secret, address)
    return "%s?%s" % (path, urlencode({"token_hash": hashed, "type": kind,
                                        "next": safe_next(next_path)}))
