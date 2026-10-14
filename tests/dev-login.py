#!/usr/bin/env python3
#
# dev_login.py and sclaude-proxy's /__sclaude/login: a feature opens signed in
# as the developer, through a magic-link token from its own Supabase, and never
# on a protected environment.
#
# A fake GoTrue stands in for Supabase's admin API and records what it was
# asked; a fake dev server stands in for the feature's `next dev`.
#
# Run it with: python3 tests/dev-login.py
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PROXY = os.path.join(ROOT, "bin", "sclaude-proxy")

failures = []
total = 0


def check(name, got, want):
    global total
    total += 1
    if got != want:
        failures.append((name, want, got))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


ASKED = []


class GoTrue(http.server.BaseHTTPRequestHandler):
    """generate_link: a token for anybody but refused@… (a 422) and
    nobody@… (a 404, as GoTrue answers recovery for an unknown user)."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        ASKED.append((self.path, self.headers.get("apikey"), body))
        if body.get("email") == "refused@example.com":
            out, code = {"msg": "nope"}, 422
        elif body.get("email") == "nobody@example.com":
            out, code = {"msg": "User not found"}, 404
        else:
            out, code = {"hashed_token": "h4sh", "verification_type": "recovery"}, 200
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class Dev(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True)


def product(root, config):
    """A main checkout with a config, environments and a worktree."""
    main = os.path.join(root, "main")
    os.makedirs(os.path.join(main, ".sclaude"))
    git(main, "init", "-q", "-b", "main")
    with open(os.path.join(main, ".sclaude", "config.json"), "w") as fh:
        json.dump(config, fh)
    git(main, "add", ".")
    git(main, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
    return main


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def request(port, host, path, cookie=None):
    lines = ["GET %s HTTP/1.1" % path, "Host: %s" % host]
    if cookie:
        lines.append("Cookie: %s" % cookie)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    head = head.decode("latin-1")
    headers = {}
    for line in head.split("\r\n")[1:]:
        name, _, value = line.partition(":")
        headers.setdefault(name.strip().lower(), value.strip())
    return head.split("\r\n")[0], headers, body.decode("utf-8", "replace")


def main():
    root = tempfile.mkdtemp(prefix="sclaude-dev-login-")
    login_file = os.path.join(root, "dev-login")
    os.environ["SCLAUDE_DEV_LOGIN_FILE"] = login_file
    sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib"))
    import dev_login

    gotrue, gport = serve(GoTrue)
    dev, dport = serve(Dev)
    supa = "http://127.0.0.1:%d" % gport
    try:
        write(login_file, "\n  dev@example.com \n")
        check("the address comes from the file", dev_login.email(), "dev@example.com")

        for value, want in (("/a?b=1", "/a?b=1"), ("//evil.com", "/"), ("http://x", "/"),
                            ("/\\evil", "/"), (None, "/")):
            check("safe_next(%r)" % value, dev_login.safe_next(value), want)

        # No devLogin: nothing offered, and asked anyway, a reason.
        bare = product(os.path.join(root, "bare"), {})
        check("no devLogin, not offered", dev_login.offered(bare), False)
        try:
            dev_login.link(bare)
            check("no devLogin refuses", "linked", "refused")
        except dev_login.Refused as exc:
            check("no devLogin says so", "devLogin" in str(exc), True)

        config = {"devLogin": {"path": "/auth/confirm"},
                  "environments": {"dev": {"env": ".env.dev"},
                                   "prod": {"env": ".env.prod", "protected": True}}}
        main_wt = product(os.path.join(root, "p"), config)
        check("devLogin, offered", dev_login.offered(main_wt), True)

        # A feature on its own local database: db.env.
        own = os.path.join(main_wt, ".sclaude", "local", "feature", "db.env")
        write(own, "NEXT_PUBLIC_SUPABASE_URL=%s\nSUPABASE_SECRET_KEY=sb_secret_x\n" % supa)
        got = urlsplit(dev_login.link(main_wt, "/feed"))
        query = parse_qs(got.query)
        check("the link is the product's route", got.path, "/auth/confirm")
        check("it carries the token", query.get("token_hash"), ["h4sh"])
        check("and its type", query.get("type"), ["recovery"])
        check("and where to land", query.get("next"), ["/feed"])
        check("Supabase was asked for this address with the secret key",
              ASKED[-1], ("/auth/v1/admin/generate_link", "sb_secret_x",
                          {"type": "recovery", "email": "dev@example.com"}))

        write(login_file, "refused@example.com\n")
        try:
            dev_login.link(main_wt)
            check("a refusal from Supabase is reported", "linked", "refused")
        except dev_login.Refused as exc:
            check("a refusal from Supabase is reported", "422" in str(exc) and "nope" in str(exc), True)
        write(login_file, "nobody@example.com\n")
        try:
            dev_login.link(main_wt)
            check("an unknown address is refused, not created", "linked", "refused")
        except dev_login.Refused as exc:
            check("an unknown address is refused, naming the file",
                  "nobody@example.com" in str(exc) and login_file in str(exc), True)
        write(login_file, "dev@example.com\n")

        write(own, "NEXT_PUBLIC_SUPABASE_URL=https://abcdefghijklmnopqrst.supabase.co\n"
                   "SUPABASE_SECRET_KEY=sb_secret_x\n")
        try:
            dev_login.link(main_wt)
            check("a db.env off this machine refuses", "linked", "refused")
        except dev_login.Refused:
            check("a db.env off this machine refuses", True, True)
        os.remove(own)

        # No db.env: the environment .env.local points at.
        write(os.path.join(main_wt, ".env.prod"),
              "NEXT_PUBLIC_SUPABASE_URL=%s\nSUPABASE_SECRET_KEY=prod\n" % supa)
        write(os.path.join(main_wt, ".env.dev"),
              "NEXT_PUBLIC_SUPABASE_URL=%s\nSUPABASE_SECRET_KEY=dev\n" % supa)
        os.symlink(os.path.join(main_wt, ".env.prod"), os.path.join(main_wt, ".env.local"))
        asked = len(ASKED)
        try:
            dev_login.link(main_wt)
            check("a protected environment refuses", "linked", "refused")
        except dev_login.Refused as exc:
            check("a protected environment refuses, naming it", "prod" in str(exc), True)
        check("production's Supabase is never asked", len(ASKED), asked)
        os.remove(os.path.join(main_wt, ".env.local"))
        os.symlink(os.path.join(main_wt, ".env.dev"), os.path.join(main_wt, ".env.local"))
        dev_login.link(main_wt)
        check("a runnable environment signs in with its key", ASKED[-1][1], "dev")

        check_proxy(root, main_wt, dport, login_file)
    finally:
        gotrue.shutdown()
        dev.shutdown()
        shutil.rmtree(root, ignore_errors=True)

    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


def check_proxy(root, wt, dport, login_file):
    registry = os.path.join(root, "registry")
    os.makedirs(registry)
    os.makedirs(os.path.join(wt, ".sclaude", "local", "feature"), exist_ok=True)
    with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json"), "w") as fh:
        json.dump({"feature": "f1", "dev": {"label": "f1", "port": dport}}, fh)
    os.symlink(wt, os.path.join(registry, "f1"))
    port = free_port()
    env = dict(os.environ, SCLAUDE_PROXY_PORT=str(port), SCLAUDE_PROXY_BIND="127.0.0.1",
               SCLAUDE_DEV_REGISTRY=registry, SCLAUDE_BIN="/bin/false",
               SCLAUDE_DEV_LOGIN_FILE=login_file)
    proc = subprocess.Popen([sys.executable, PROXY], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        host = "localhost:%d" % port

        _, _, body = request(port, host, "/")
        check("the list opens a feature signed in", "href='/__sclaude/login?f=f1'" in body, True)
        check("and offers it without", "href='http://f1.localhost:%d/'" % port in body
              and "without signing in" in body, True)

        status, headers, _ = request(port, host, "/__sclaude/login?f=f1&next=/x")
        check("from the bare host, to the feature's own first", (status, headers.get("location")),
              ("HTTP/1.1 303 See Other",
               "http://f1.localhost:%d/__sclaude/login?next=%%2Fx" % port))

        status, headers, _ = request(port, "f1." + host, "/__sclaude/login?next=/x")
        where = urlsplit(headers.get("location", ""))
        check("on the feature's host, to the product's route with a token",
              (status, where.path, parse_qs(where.query).get("token_hash")),
              ("HTTP/1.1 303 See Other", "/auth/confirm", ["h4sh"]))

        status, headers, _ = request(port, "f1." + host, "/__sclaude/login?next=/x",
                                     cookie="a=1; sb-127-auth-token.0=xyz")
        check("a browser already signed in is only sent on", headers.get("location"), "/x")

        status, headers, _ = request(port, "100.64.0.1:%d" % port, "/__sclaude/login?f=f1",
                                     cookie="sb-127-auth-token=old")
        check("off this machine: always a fresh token",
              urlsplit(headers.get("location", "")).path, "/auth/confirm")
        check("and the feature picked by the cookie",
              headers.get("set-cookie", "").startswith("sclaude_feature=f1;"), True)

        os.remove(os.path.join(wt, ".env.local"))
        os.symlink(os.path.join(wt, ".env.prod"), os.path.join(wt, ".env.local"))
        status, _, body = request(port, "f1." + host, "/__sclaude/login")
        check("on production: not signed in, and why",
              (status, "prod" in body), ("HTTP/1.1 409 Conflict", True))
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
