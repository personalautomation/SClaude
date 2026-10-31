#!/usr/bin/env python3
#
# dev_login.py and sclaude-proxy's /__sclaude/login: a feature opens signed in
# as the developer, through a recovery token from its own Supabase, and never
# on a protected environment; `as=<email>` signs in as another user of the
# feature's own local database, and nowhere else; /__sclaude/users lists them.
# The step prompt spells the same link out, and skills/sdemo/demo.py builds
# it; both are checked to.
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
ASKED_URL = []


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

    def do_GET(self):
        ASKED.append((self.path, self.headers.get("apikey"), None))
        query = parse_qs(urlsplit(self.path).query)
        page, per = int(query["page"][0]), int(query["per_page"][0])
        people = [{"email": "seed@example.com"}, {"email": "Bob@example.com"},
                  {"phone": "+1"}, {"email": "dev@example.com"}]
        data = json.dumps({"users": people[(page - 1) * per:page * per]}).encode()
        self.send_response(200)
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


def request(port, host, path, cookie=None, extra=()):
    lines = ["GET %s HTTP/1.1" % path, "Host: %s" % host] + list(extra)
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
        name = name.strip().lower()
        if name == "set-cookie" and name in headers:
            headers[name] += "\n" + value.strip()
        else:
            headers.setdefault(name, value.strip())
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
    ASKED_URL.append(supa)
    try:
        write(login_file, "\n  dev@example.com \n")
        check("the address comes from the file", dev_login.email(), "dev@example.com")

        for value, want in (("/a?b=1", "/a?b=1"), ("//evil.com", "/"), ("http://x", "/"),
                            ("/\\evil", "/"), (None, "/"),
                            ("/\r\nSet-Cookie: a=1", "/"), ("/\t/evil.com", "/"),
                            ("/a\x7f", "/")):
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

        # As somebody else, on the feature's own database.
        got = parse_qs(urlsplit(dev_login.link(main_wt, "/x", "seed@example.com")).query)
        check("as= asks for that user", (ASKED[-1][2], got.get("next")),
              ({"type": "recovery", "email": "seed@example.com"}, ["/x"]))
        check("its users, sorted, addresses only", dev_login.users(main_wt),
              ["Bob@example.com", "dev@example.com", "seed@example.com"])
        check("listed with the secret key", ASKED[-1][:2],
              ("/auth/v1/admin/users?page=1&per_page=200", "sb_secret_x"))
        dev_login.USERS_PER_PAGE = 2
        check("every page of them", dev_login.users(main_wt),
              ["Bob@example.com", "dev@example.com", "seed@example.com"])
        check("read until a short page", ASKED[-1][0], "/auth/v1/admin/users?page=3&per_page=2")
        dev_login.USERS_PER_PAGE = 200
        try:
            dev_login.link(main_wt, "/", "nobody@example.com")
            check("an unknown as= is refused", "linked", "refused")
        except dev_login.Refused as exc:
            check("an unknown as= is refused, not pointing at the file",
                  "nobody@example.com" in str(exc) and login_file not in str(exc), True)
        for value, want in (("a@b.c", "a@b.c"), (" a@b.c ", "a@b.c"), ("ab.c", ""),
                            ("a b@c", ""), ("a@b@c", ""), ("<a>@b", ""), ("a@b\r\nX: y", ""),
                            ("", ""), ("a@" + "b" * 260, "")):
            check("valid_address(%r)" % value, dev_login.valid_address(value), want)

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
        asked = len(ASKED)
        try:
            dev_login.link(main_wt, "/", "seed@example.com")
            check("a shared environment refuses as=", "linked", "refused")
        except dev_login.Refused as exc:
            check("a shared environment refuses as=, naming who it does sign in as",
                  "dev@example.com" in str(exc), True)
        try:
            dev_login.users(main_wt)
            check("a shared environment lists nobody", "listed", "refused")
        except dev_login.Refused:
            check("a shared environment lists nobody", True, True)
        check("and Supabase is not asked for either", len(ASKED), asked)
        dev_login.link(main_wt, "/", "DEV@example.com")
        check("as= naming the developer still signs in there",
              ASKED[-1][2]["email"], "DEV@example.com")

        with open(os.path.join(ROOT, "sclaude", "prompts", "_dev-server.md")) as fh:
            prompt = fh.read()
        check("the step prompt gives the link the proxy reads",
              "<dev-url>/__sclaude/login?as=<email>&next=<path>" in prompt
              and "<dev-url>/__sclaude/users" in prompt, True)

        check_proxy(root, main_wt, dport, login_file)
    finally:
        gotrue.shutdown()
        dev.shutdown()
        shutil.rmtree(root, ignore_errors=True)

    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


def load_demo(registry, port):
    """skills/sdemo/demo.py, pointed at the bench's registry and proxy."""
    import importlib.util
    os.environ["SCLAUDE_DEV_REGISTRY"] = registry
    os.environ["SCLAUDE_PROXY_PORT"] = str(port)
    spec = importlib.util.spec_from_file_location(
        "demo", os.path.join(ROOT, "skills", "sdemo", "demo.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Nothing of this machine's tailnet or bot: the bench's own answers.
    module.real_phone_origin = module.phone_origin
    module.active_peers = lambda: []
    module.phone_origin = lambda: ""
    return module


def demo_out(demo, wt, args, where=""):
    """demo.py link's lines for a tree, as the skill reads them."""
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        demo.cmd_link(args, "f1", wt, where)
    return buf.getvalue().splitlines()


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

        # next= goes into the Location header: CR LF in it must not start
        # headers of a link's choosing.
        status, headers, _ = request(
            port, "f1." + host, "/__sclaude/login?next=/%0d%0aSet-Cookie:%20planted=1",
            cookie="sb-127-auth-token=xyz")
        check("a CR LF in next= plants no header",
              (headers.get("location"), "planted" in headers.get("set-cookie", "")), ("/", False))

        status, headers, _ = request(port, "100.64.0.1:%d" % port, "/__sclaude/login?f=f1",
                                     cookie="sb-127-auth-token=old")
        check("off this machine: always a fresh token",
              urlsplit(headers.get("location", "")).path, "/auth/confirm")
        check("and the feature picked by the cookie",
              headers.get("set-cookie", "").startswith("sclaude_feature=f1;"), True)
        check("and the session there dropped first",
              "sb-127-auth-token=; Path=/; Max-Age=0" in headers.get("set-cookie", ""), True)

        # The shared dev environment: no "as another user", and as= refused.
        check("no other users offered on a shared environment",
              "as another user" in request(port, host, "/")[2], False)
        status, _, body = request(port, "f1." + host, "/__sclaude/login?as=seed@example.com")
        check("as= on a shared environment: not signed in",
              (status, "dev@example.com" in body), ("HTTP/1.1 409 Conflict", True))
        shared = load_demo(registry, port)
        check("demo: somebody else on a shared environment is warned of as refused",
              [l for l in demo_out(shared, wt, ["seed@example.com"]) if l.startswith("warn:")],
              ["warn: the link will be refused: f1 has no local database of its own, so it "
               "signs in only as dev@example.com"])
        check("demo: the developer there is not warned of",
              [l for l in demo_out(shared, wt, ["dev@example.com"]) if l.startswith("warn:")], [])
        email = shared.dev_login.email
        shared.dev_login.email = lambda: ""
        check("demo: with nobody to sign in as, refused and the file named",
              [l for l in demo_out(shared, wt, ["dev@example.com"]) if l.startswith("warn:")],
              ["warn: the link will be refused: nobody to sign in as — put an address in %s"
               % login_file])
        shared.dev_login.email = email

        own = os.path.join(wt, ".sclaude", "local", "feature", "db.env")
        write(own, "NEXT_PUBLIC_SUPABASE_URL=https://x.supabase.co\nSUPABASE_SECRET_KEY=k\n")
        check("a db.env off this machine: no other users offered",
              "as another user" in request(port, host, "/")[2], False)
        write(own, "NEXT_PUBLIC_SUPABASE_URL=%s\nSUPABASE_SECRET_KEY=sb_secret_x\n"
              % ASKED_URL[0])
        _, _, body = request(port, host, "/")
        check("its own database: other users offered",
              "href='/__sclaude/users?f=f1'" in body, True)
        status, _, body = request(port, "f1." + host, "/__sclaude/users")
        check("the users page links a sign-in each",
              (status, "/__sclaude/login?f=f1&amp;as=seed%40example.com" in body),
              ("HTTP/1.1 200 OK", True))

        # /sdemo's links, read back by the proxy itself.
        demo = load_demo(registry, port)
        demo.phone_origin = lambda: "https://node.example.ts.net"
        laptop, phone = demo.links("f1", "seed@example.com", "/a?b=1&c=2")
        check("demo: the laptop link is the feature's host",
              laptop.startswith("http://f1.localhost:%d/__sclaude/login?" % port), True)
        check("demo: the phone link names the feature on the phone's origin",
              phone.startswith("https://node.example.ts.net/__sclaude/login?f=f1&"), True)
        check("demo: a feature named is its tree", demo.feature("f1"),
              ("f1", os.path.realpath(wt)))
        for name, link, at in (("laptop", laptop, "f1." + host),
                               ("phone", phone, "100.64.0.1:%d" % port)):
            target = link.split("/", 3)[3]
            status, headers, _ = request(port, at, "/" + target)
            check("demo: the %s link signs in as its user, landing on the whole page" % name,
                  (status, ASKED[-1][2]["email"],
                   parse_qs(urlsplit(headers.get("location", "")).query).get("next")),
                  ("HTTP/1.1 303 See Other", "seed@example.com", ["/a?b=1&c=2"]))

        demo.active_peers = lambda: ["phone"]
        check("demo: away, the phone link first",
              demo_out(demo, wt, ["seed@example.com", "/x"])[:2],
              ["where: phone — tailnet traffic from phone", "link: " + demo.links(
                  "f1", "seed@example.com", "/x")[1]])
        demo.phone_origin = lambda: ""
        out = demo_out(demo, wt, ["seed@example.com", "x"], "phone")
        check("demo: no phone address, the laptop link alone, and said where it is for",
              (out[0].startswith("where: laptop — as asked; no address a phone can open"),
               out[1].startswith("link: http://f1.localhost"),
               any(l.startswith("other:") for l in out)), (True, True, False))
        check("demo: a page that is no path is said, not swapped silently",
              any("opens / instead" in l for l in out), True)
        import types
        fake = types.ModuleType("keepawake.telegramd")
        sys.modules["keepawake.telegramd"] = fake
        import keepawake
        for origin, want in (("https://node.example.ts.net", "https://node.example.ts.net"),
                             ("http://100.64.0.1:3000", "http://100.64.0.1:3000"),
                             ("http://127.0.0.1:3000", ""), ("http://localhost:3000", ""),
                             ("http://0.0.0.0:3000", ""), ("http://[::]:3000", ""),
                             ("http://[:3000", "")):
            fake.phone_origin = lambda origin=origin: origin
            keepawake.telegramd = fake
            check("demo: phone_origin(%s)" % origin, demo.real_phone_origin(), want)
        del sys.modules["keepawake.telegramd"]
        del keepawake.telegramd
        check("demo: an unknown user is warned of",
              any("not a user" in l for l in demo_out(demo, wt, ["nobody@example.com"])), True)

        # open: a window of its own per user, through a chrome-debug that
        # only writes down what it was asked; the previous demo's go first.
        import contextlib
        import io
        stub = os.path.join(root, "stubbin")
        os.makedirs(stub, exist_ok=True)
        asked = os.path.join(root, "chrome-asked")
        with open(os.path.join(stub, "chrome-debug"), "w") as fh:
            fh.write('#!/bin/sh\necho "$*" >> %s\n'
                     '[ "$1" = --window ] && echo "chrome-debug: window ctx$# — tabs"\n'
                     'exit 0\n' % asked)
        os.chmod(os.path.join(stub, "chrome-debug"), 0o755)
        saved_path, os.environ["PATH"] = os.environ["PATH"], stub + os.pathsep + os.environ["PATH"]
        demo.WINDOWS = os.path.join(root, "sdemo-windows")
        try:
            for _ in range(2):
                with contextlib.redirect_stdout(io.StringIO()):
                    demo.cmd_open(["seed@example.com", "/a", "dev@example.com", "/b",
                                   "seed@example.com", "/c"], "f1", wt)
        finally:
            os.environ["PATH"] = saved_path
        with open(asked) as fh:
            calls = fh.read().splitlines()
        seed = lambda p: demo.links("f1", "seed@example.com", p)[0]
        dev = demo.links("f1", "dev@example.com", "/b")[0]
        check("demo open: one window per user, the user's pages in order, laptop links",
              calls[:2], ["--window %s %s" % (seed("/a"), seed("/c")), "--window " + dev])
        check("demo open: the next open closes the previous windows first",
              calls[2:4], ["--close-window ctx3", "--close-window ctx2"])
        os.environ["PATH"] = stub + os.pathsep + saved_path
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                demo.cmd_open(["nobody@example.com", "/a"], "f1", wt)
        finally:
            os.environ["PATH"] = saved_path
        with open(asked) as fh:
            after = fh.read().splitlines()
        check("demo open: a user the database refuses gets no window",
              (any(l.startswith("--window") for l in after[len(calls):]),
               "failed: nobody@example.com — not opened, the sign-in would be refused"
               in out.getvalue().splitlines()), (False, True))

        # A recorded demo: where demo.py puts it is where the proxy serves it
        # from, the video by ranges, and nothing but its own files.
        proxy_src = open(PROXY).read()
        check("demo: demo.py and the proxy name the same directory and address",
              ('DEMO_DIR = "%s"' % demo.DEMO_DIR in proxy_src,
               'DEMO_PREFIX = "%s"' % demo.DEMO_PREFIX in proxy_src), (True, True))
        player = open(os.path.join(ROOT, "skills", "sdemo", "player.html")).read()
        filler = open(os.path.join(ROOT, "skills", "sdemo", "play.mjs")).read()
        check("demo: play.mjs fills the markers player.html has",
              [m in player and m in filler for m in ('/*DEMO*/null', '/*FEATURE*/""')],
              [True, True])
        recorded = os.path.join(wt, demo.DEMO_DIR, "20261031-120000")
        write(os.path.join(recorded, "index.html"), "<h1>the demo</h1>")
        write(os.path.join(recorded, "scenario-1.webm"), "0123456789")
        write(os.path.join(recorded, "demo.mjs"), "export default {}")
        page_url = demo.demo_links("f1", "20261031-120000")[0]
        check("demo: the page's laptop address is on the feature's host",
              page_url, "http://f1.localhost:%d/__sclaude/demo/f1/20261031-120000/" % port)
        tail = "/__sclaude/demo/f1/20261031-120000"
        status, headers, body = request(port, host, tail + "/")
        check("demo: the page is served", (status.split(" ", 1)[1], body),
              ("200 OK", "<h1>the demo</h1>"))
        status, headers, _ = request(port, host, tail)
        check("demo: without the slash, sent under it",
              (status.split(" ", 1)[1], headers.get("location")), ("303 See Other", tail + "/"))
        status, headers, body = request(port, host, tail + "/scenario-1.webm",
                                        extra=["Range: bytes=2-5"])
        check("demo: a video by ranges", (status.split(" ", 1)[1], body,
                                          headers.get("content-range")),
              ("206 Partial Content", "2345", "bytes 2-5/10"))
        status, _, body = request(port, host, tail + "/scenario-1.webm", extra=["Range: bytes=-3"])
        check("demo: the last bytes of a video", body, "789")
        write(os.path.join(recorded, "scenario-1.vtt"), "WEBVTT\n")
        status, headers, _ = request(port, host, tail + "/scenario-1.vtt")
        check("demo: the captions are served as WebVTT",
              (status.split(" ", 1)[1], headers.get("content-type")),
              ("200 OK", "text/vtt; charset=utf-8"))
        with open(os.path.join(recorded, "big.webm"), "wb") as fh:
            fh.write(b"x" * (5 * 1024 * 1024))
        status, headers, _ = request(port, host, tail + "/big.webm", extra=["Range: bytes=0-"])
        check("demo: an open range is answered a piece at a time",
              (status.split(" ", 1)[1], headers.get("content-range")),
              ("206 Partial Content", "bytes 0-4194303/5242880"))
        status, headers, _ = request(port, host, tail + "/big.webm",
                                     extra=["Range: bytes=-5000000"])
        check("demo: a range asked in full is answered in full",
              headers.get("content-range"), "bytes 242880-5242879/5242880")
        for bad in ("/demo.mjs", "/../../feature/state.json", "/.hidden.json", "/nothere.webm"):
            status, _, _ = request(port, host, tail + bad)
            check("demo: %s is not served" % bad, status.split(" ", 1)[1], "404 Not Found")
        status, _, _ = request(port, host, "/__sclaude/demo/nofeature/20261031-120000/")
        check("demo: an unknown feature's demo is not served", status.split(" ", 1)[1],
              "404 Not Found")

        # demo.py play: play.mjs run on a copy of the script in a demo of its
        # own, and the page's link to the feature's topic. node and
        # sclaude-notify are stand-ins that write down what they were asked.
        with open(os.path.join(stub, "node"), "w") as fh:
            fh.write('#!/bin/sh\necho "$*" >> %s\nwhile [ $# -gt 0 ]; do '
                     '[ "$1" = --out ] && echo "<h1>x</h1>" > "$2/index.html" && '
                     'echo \'{"title": "T"}\' > "$2/demo.json"; shift; done\n' % asked)
        with open(os.path.join(stub, "sclaude-notify"), "w") as fh:
            fh.write('#!/bin/sh\necho "notify $*" >> %s\n' % asked)
        for name in ("node", "sclaude-notify"):
            os.chmod(os.path.join(stub, name), 0o755)
        os.remove(asked)
        script = os.path.join(root, "my-demo.mjs")
        write(script, "export default {scenarios: []}")
        os.environ["PATH"] = stub + os.pathsep + saved_path
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                demo.cmd_play([script], "f1", wt, "laptop", False)
        finally:
            os.environ["PATH"] = saved_path
        with open(asked) as fh:
            calls = fh.read().splitlines()
        ran = calls[0].split()
        made = ran[1]
        check("demo play: play.mjs runs a copy, in a demo of the feature's own",
              (ran[0] == os.path.join(ROOT, "skills", "sdemo", "play.mjs") or
               os.path.realpath(ran[0]) == os.path.realpath(os.path.join(ROOT, "skills", "sdemo", "play.mjs")),
               os.path.dirname(os.path.dirname(made)) == os.path.join(wt, demo.DEMO_DIR),
               os.path.isfile(made), ran[ran.index("--base") + 1], ran[ran.index("--feature") + 1]),
              (True, True, True, "http://f1.localhost:%d" % port, "f1"))
        demo_id = os.path.basename(os.path.dirname(made))
        check("demo play: the page's link is said, and sent to the topic",
              ("link: " + demo.demo_links("f1", demo_id)[0] in out.getvalue().splitlines(),
               calls[1] == "notify --quiet --in %s 🎬 T" % wt,
               calls[2] == demo.demo_links("f1", demo_id)[0]), (True, True, True))

        status, headers, _ = request(port, host,
                                     "/__sclaude/login?f=f1&as=seed@example.com&next=/y")
        check("as= survives the way to the feature's host", headers.get("location"),
              "http://f1.localhost:%d/__sclaude/login?next=%%2Fy&as=seed%%40example.com" % port)
        status, headers, _ = request(port, "f1." + host,
                                     "/__sclaude/login?as=seed@example.com&next=/y",
                                     cookie="a=1; sb-127-auth-token.0=x; sb-127-auth-token.1=y")
        where = urlsplit(headers.get("location", ""))
        check("signed in already, as= still takes a fresh token for that user",
              (status, where.path, ASKED[-1][2]),
              ("HTTP/1.1 303 See Other", "/auth/confirm",
               {"type": "recovery", "email": "seed@example.com"}))
        dropped = headers.get("set-cookie", "").split("\n")
        check("and the old session goes, every chunk of it, nothing else",
              sorted(dropped), ["sb-127-auth-token.0=; Path=/; Max-Age=0; SameSite=Lax",
                                "sb-127-auth-token.1=; Path=/; Max-Age=0; SameSite=Lax"])
        status, _, _ = request(port, "f1." + host, "/__sclaude/login?as=not-an-address")
        check("as= that is not an address", status, "HTTP/1.1 400 Bad Request")
        os.remove(own)

        os.remove(os.path.join(wt, ".env.local"))
        os.symlink(os.path.join(wt, ".env.prod"), os.path.join(wt, ".env.local"))
        status, _, body = request(port, "f1." + host, "/__sclaude/login")
        check("on production: not signed in, and why",
              (status, "prod" in body), ("HTTP/1.1 409 Conflict", True))
        check("demo: on production the link is said to be refused",
              any(l.startswith("warn: the link will be refused") and "prod" in l
                  for l in demo_out(load_demo(registry, port), wt, ["dev@example.com"])), True)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
