#!/usr/bin/env python3
#
# sclaude-proxy: <feature>.localhost:3000 reaches that feature's server, a
# stopped feature is started by the first request for it, and an idle one is
# stopped again.
#
# Two fake upstreams stand in for two features' dev servers. Each answers with
# its own name and the Host it was sent, and echoes whatever follows an
# upgrade — which is all a WebSocket is to a proxy that copies bytes. A stub
# stands in for `sclaude dev`, which the proxy runs to start and stop features.
#
# Run it with: python3 tests/proxy.py
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

PROXY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "sclaude-proxy")

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


def answers_on(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
        return True
    except OSError:
        return False


def wait_for(predicate, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def upstream(name):
    """A dev server that says who it is, and echoes after an upgrade."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(16)

    def serve(conn):
        with conn:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            text = head.decode("latin-1").lower()
            host = ""
            for line in text.split("\r\n"):
                if line.startswith("host:"):
                    host = line[5:].strip()
            if "upgrade: websocket" in text:
                conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                             b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                while True:
                    data = conn.recv(4096)
                    if not data:
                        return
                    conn.sendall(data)
            body = ("%s %s" % (name, host)).encode()
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n"
                         b"Connection: close\r\n\r\n%s" % (len(body), body))

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=serve, args=(conn,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return server, server.getsockname()[1]


# A stand-in for `sclaude dev`: `--no-browser` starts a small server on the
# port the tree's state records, answering "<LABEL> <host>"; `--stop` kills it.
# A tree with .sclaude/local/feature/fail refuses to start, the way a broken build would.
STUB_SERVER = (
    "import http.server, sys\n"
    "class H(http.server.BaseHTTPRequestHandler):\n"
    "    def do_GET(self):\n"
    "        body = ('%s %s' % (sys.argv[2], self.headers.get('Host'))).encode()\n"
    "        self.send_response(200)\n"
    "        self.send_header('Content-Length', str(len(body)))\n"
    "        self.end_headers()\n"
    "        self.wfile.write(body)\n"
    "    def log_message(self, *a):\n"
    "        pass\n"
    "http.server.HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()\n"
)

STUB = """#!/usr/bin/env python3
import json, os, signal, subprocess, sys
wt = os.getcwd()
with open(os.environ["STUB_LOG"], "a") as fh:
    fh.write("%%s %%s\\n" %% (os.path.basename(wt), " ".join(sys.argv[1:])))
pidfile = os.path.join(wt, ".sclaude/local/feature", "stub.pid")
if "--stop" in sys.argv:
    try:
        os.kill(int(open(pidfile).read()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    sys.exit(0)
if os.path.exists(os.path.join(wt, ".sclaude/local/feature", "fail")):
    print("boom: the build broke")
    sys.exit(1)
state = json.load(open(os.path.join(wt, ".sclaude/local/feature", "state.json")))
port, label = state["dev"]["port"], state["dev"]["label"]
proc = subprocess.Popen([sys.executable, "-c", %r, str(port), label.upper()],
                        start_new_session=True, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
open(pidfile, "w").write(str(proc.pid))
""" % STUB_SERVER


def stub_calls(log):
    try:
        with open(log) as fh:
            return [line.strip() for line in fh]
    except OSError:
        return []


def calls_for(log, label):
    return [c for c in stub_calls(log) if c.startswith("wt-%s " % label)]


def request(port, host, path="/", cookie=None):
    """(status line, headers text, body) of one request through the proxy."""
    lines = ["GET %s HTTP/1.1" % path, "Host: %s" % host]
    if cookie:
        lines.append("Cookie: %s" % cookie)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    head = head.decode("latin-1")
    return head.split("\r\n")[0], head, body.decode("utf-8", "replace")


def register(registry, root, label, port, db_base=None, config_ports=None):
    """`config_ports` writes supabase/config.toml with each {section: port},
    enabled — used both for a feature's own block (with db_base) and for
    main's shared stack (without one, so services() reads the literal ports
    this config names instead of base + slot)."""
    wt = os.path.join(root, "wt-" + label)
    os.makedirs(os.path.join(wt, ".sclaude/local/feature"))
    state = {"feature": label, "dev": {"label": label, "port": port}}
    if db_base is not None:
        state["db"] = {"base": db_base}
    if config_ports:
        os.makedirs(os.path.join(wt, "supabase"))
        with open(os.path.join(wt, "supabase", "config.toml"), "w") as fh:
            for section, p in config_ports.items():
                fh.write("[%s]\nenabled = true\nport = %d\n" % (section, p))
    with open(os.path.join(wt, ".sclaude/local/feature", "state.json"), "w") as fh:
        json.dump(state, fh)
    os.symlink(wt, os.path.join(registry, label))
    return wt


def connection_echo():
    """A dev server that answers with the Connection header it was sent."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(16)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                head = b""
                while b"\r\n\r\n" not in head:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    head += chunk
                value = ""
                for line in head.decode("latin-1").split("\r\n"):
                    if line.lower().startswith("connection:"):
                        value = line.split(":", 1)[1].strip()
                body = ("connection=%s" % value).encode()
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))

    threading.Thread(target=loop, daemon=True).start()
    return server, server.getsockname()[1]


def start_proxy(registry, stub, log, idle, tick, grace=180):
    port = free_port()
    env = dict(os.environ, SCLAUDE_PROXY_PORT=str(port), SCLAUDE_PROXY_BIND="127.0.0.1",
               SCLAUDE_DEV_REGISTRY=registry, SCLAUDE_BIN=stub, STUB_LOG=log,
               SCLAUDE_DEV_IDLE=str(idle), SCLAUDE_PROXY_TICK=str(tick),
               SCLAUDE_PROXY_BUILD_GRACE=str(grace))
    proc = subprocess.Popen([sys.executable, PROXY], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    wait_for(lambda: answers_on(port), 5)
    return proc, port


def check_peers(registry, stub, log):
    """Only loopback and the tailnet are answered (allowed, SCLAUDE_PROXY_ALLOW)."""
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    loader = SourceFileLoader("sclaude_proxy", PROXY)
    mod = module_from_spec(spec_from_loader("sclaude_proxy", loader))
    loader.exec_module(mod)
    # A tree an older sclaude still runs keeps its state in .feature/.
    old = tempfile.mkdtemp(prefix="proxy-old-")
    try:
        os.makedirs(os.path.join(old, "wt", ".feature"))
        with open(os.path.join(old, "wt", ".feature", "state.json"), "w") as fh:
            json.dump({"dev": {"port": 3123}}, fh)
        os.symlink(os.path.join(old, "wt"), os.path.join(old, "12-old"))
        mod.REGISTRY = old
        check("the old state folder is read", (mod.feature("12-old") or (None, None))[1], 3123)
    finally:
        mod.REGISTRY = registry
        shutil.rmtree(old, ignore_errors=True)
    head = ("HTTP/1.1 200 OK\r\nX-Frame-Options: DENY\r\n"
            "Content-Security-Policy: default-src 'self'; frame-ancestors 'none'\r\n"
            "Content-Security-Policy-Report-Only: frame-ancestors 'none'\r\n"
            "Content-Type: text/html").encode()
    got = mod.frameable(head).decode()
    check("gate: the framing ban is taken out",
          ("X-Frame-Options" in got, "Content-Security-Policy: default-src 'self'" in got,
           "Report-Only: frame-ancestors" in got, "Content-Type: text/html" in got),
          (False, True, True, True))
    check("gate: a policy of frame-ancestors alone goes whole",
          mod.frameable(b"HTTP/1.1 200 OK\r\nContent-Security-Policy: frame-ancestors 'none'"),
          b"HTTP/1.1 200 OK")
    for peer, want in (("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
                       ("100.72.15.17", True), ("::ffff:100.101.2.3", True),
                       ("fd7a:115c:a1e0::1", True), ("192.168.1.20", False),
                       ("::ffff:192.168.1.20", False), ("172.28.0.1", False),
                       ("100.128.0.1", False), ("fe80::1%eth0", False), ("junk", False)):
        check("peer-allowed-%s" % peer, mod.allowed(peer), want)

    calls = len(stub_calls(log))
    os.environ["SCLAUDE_PROXY_ALLOW"] = "10.0.0.0/8"
    try:
        proc, port = start_proxy(registry, stub, log, idle=600, tick=60)
    finally:
        del os.environ["SCLAUDE_PROXY_ALLOW"]
    try:
        status, _, body = request(port, "localhost:%d" % port, "/__sclaude/")
        check("stranger-refused", status, "HTTP/1.1 403 Forbidden")
        check("stranger-sees-nothing", body, "")
        status, _, _ = request(port, "a.localhost:%d" % port)
        check("stranger-starts-nothing", (status, len(stub_calls(log))),
              ("HTTP/1.1 403 Forbidden", calls))
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def raw_request(port, text):
    """(status line, headers text, body) of raw bytes sent to a port."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(text.encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    head = head.decode("latin-1")
    return head.split("\r\n")[0], head, body.decode("utf-8", "replace")


def check_gate(proxy_port, root):
    """`sclaude-proxy --gate`: the phone's entry from the internet lets in only
    the bot's owner, by Telegram's signed initData, and passes them on to the
    proxy one request per connection."""
    sys.path.insert(0, os.path.join(os.path.dirname(PROXY), "..", "sclaude", "lib"))
    import tg_webapp
    token, owner = "123:TEST-TOKEN", 4242
    envfile = os.path.join(root, "gate.env")
    with open(envfile, "w") as fh:
        fh.write("KEEPAWAKE_BOT_TOKEN=%s\nKEEPAWAKE_CHAT_ID=%d\n" % (token, owner))

    # No credentials: the gate does not open at all.
    port = free_port()
    proc = subprocess.run([sys.executable, PROXY, "--gate"], timeout=10,
                          env=dict(os.environ, SCLAUDE_GATE_PORT=str(port),
                                   SCLAUDE_GATE_ENV=os.path.join(root, "nothing.env")),
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    check("gate: no credentials, no gate", (proc.returncode, answers_on(port)), (1, False))

    port = free_port()
    proc = subprocess.Popen([sys.executable, PROXY, "--gate"],
                            env=dict(os.environ, SCLAUDE_GATE_PORT=str(port),
                                     SCLAUDE_GATE_UPSTREAM=str(proxy_port),
                                     SCLAUDE_GATE_ENV=envfile, SCLAUDE_GATE_IDLE="2",
                                     SCLAUDE_PROXY_TICK="0.2"),
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        wait_for(lambda: answers_on(port), 5)
        host = "box.tail1.ts.net:8443"

        status, _, body = request(port, host, "/")
        check("gate: a stranger is refused", status, "HTTP/1.1 403 Forbidden")
        check("gate: a stranger sees no feature", ">a<" in body, False)
        status, _, _ = request(port, host, "/__sclaude/")
        check("gate: the list is closed too", status, "HTTP/1.1 403 Forbidden")
        status, _, _ = request(port, host, "/", cookie="sclaude_tg=99999999999.forged")
        check("gate: a forged cookie is refused", status, "HTTP/1.1 403 Forbidden")

        status, _, body = request(port, host, "/__sclaude/tg?f=a")
        check("gate: the bootstrap page is open", status, "HTTP/1.1 200 OK")
        check("gate: it loads Telegram's script",
              "telegram.org/js/telegram-web-app.js" in body, True)
        check("gate: it asks for full screen", "requestFullscreen" in body, True)
        check("gate: it draws an address bar over the feature's frame",
              all(x in body for x in ("id=url", "<iframe id=frame", "--tg-content-safe-area-inset-top")),
              True)
        status, _, body = request(port, host, "/__sclaude/tg")
        check("gate: no feature is the list", ("200 OK" in status, "'/__sclaude/'" in body),
              (True, True))
        status, _, _ = request(port, host, "/__sclaude/tg?f=../x")
        check("gate: a bad label is not echoed", status, "HTTP/1.1 404 Not Found")

        def auth(data):
            return raw_request(port, "POST /__sclaude/tg/auth HTTP/1.1\r\nHost: %s\r\n"
                               "Content-Length: %d\r\n\r\n%s" % (host, len(data), data))

        now = int(time.time())
        good = tg_webapp.sign_init_data(
            {"auth_date": str(now), "user": json.dumps({"id": owner})}, token)
        other = tg_webapp.sign_init_data(
            {"auth_date": str(now), "user": json.dumps({"id": owner + 1})}, token)
        stale = tg_webapp.sign_init_data(
            {"auth_date": str(now - 3 * 86400), "user": json.dumps({"id": owner})}, token)
        foreign = tg_webapp.sign_init_data(
            {"auth_date": str(now), "user": json.dumps({"id": owner})}, "999:OTHER")
        for name, data in (("somebody else", other), ("a stale sign-in", stale),
                           ("another bot", foreign), ("tampered data", good.replace("4242", "4243"))):
            check("gate: %s is refused" % name, auth(data)[0], "HTTP/1.1 403 Forbidden")

        status, head, _ = auth(good)
        check("gate: the owner signs in", status, "HTTP/1.1 204 No Content")
        cookie = ""
        for line in head.split("\r\n"):
            if line.lower().startswith("set-cookie: sclaude_tg="):
                cookie = line.split(":", 1)[1].strip().split(";")[0]
        check("gate: the cookie is secure and hidden from scripts",
              all(x in head for x in ("Secure", "HttpOnly")), True)

        status, head, _ = request(port, host, "/__sclaude/select?f=a", cookie=cookie)
        check("gate: the proxy picks the feature", status, "HTTP/1.1 303 See Other")
        status, _, body = request(port, host, "/", cookie=cookie + "; sclaude_feature=a")
        check("gate: the owner reaches the feature", body, "A %s" % host)

        # Two requests on one connection: only the first is answered — the
        # second would otherwise go through on a check made for the first.
        req = ("GET / HTTP/1.1\r\nHost: %s\r\nCookie: %s; sclaude_feature=a\r\n\r\n"
               % (host, cookie))
        _, _, body = raw_request(port, req + req)
        check("gate: one request per connection", body.count("A %s" % host), 1)

        check("gate: it ends itself when nobody looks",
              wait_for(lambda: proc.poll() is not None, 10), True)
        check("gate: and exits cleanly", proc.returncode, 0)
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=5)


def check_heal_path():
    """A saved PATH naming a Node nvm has since uninstalled reaches the one installed."""
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    loader = SourceFileLoader("sclaude_proxy", PROXY)
    mod = module_from_spec(spec_from_loader("sclaude_proxy", loader))
    loader.exec_module(mod)
    home = tempfile.mkdtemp(prefix="proxy-nvm-")
    try:
        versions = os.path.join(home, ".nvm", "versions", "node")
        for version in ("v24.9.0", "v24.22.0"):
            os.makedirs(os.path.join(versions, version, "bin"))
        gone = os.path.join(versions, "v24.21.0", "bin")
        there = os.path.join(versions, "v24.9.0", "bin")
        newest = os.path.join(versions, "v24.22.0", "bin")
        elsewhere = os.path.join(home, "no-such", "bin")
        check("heal_path: a Node that is gone becomes the newest installed",
              mod.heal_path(os.pathsep.join(["/usr/bin", gone, "/bin"])),
              os.pathsep.join(["/usr/bin", newest, "/bin"]))
        check("heal_path: a Node that is still there is kept, older or not",
              mod.heal_path(there), there)
        check("heal_path: a missing directory outside nvm is left alone",
              mod.heal_path(elsewhere), elsewhere)
        shutil.rmtree(versions)
        os.makedirs(versions)
        check("heal_path: with no Node installed the entry stays as it was",
              mod.heal_path(gone), gone)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main():
    check_heal_path()
    root = tempfile.mkdtemp(prefix="sclaude-proxy-")
    registry = os.path.join(root, "registry")
    os.makedirs(registry)
    ups, procs = [], []
    try:
        stub = os.path.join(root, "stub-sclaude")
        with open(stub, "w") as fh:
            fh.write(STUB)
        os.chmod(stub, 0o755)
        log = os.path.join(root, "stub.log")

        check_peers(registry, stub, log)
        srv_a, port_a = upstream("A")
        srv_b, port_b = upstream("B")
        ups = [srv_a, srv_b]
        register(registry, root, "a", port_a)
        register(registry, root, "b", port_b)
        c_port = free_port()
        register(registry, root, "c", c_port)  # registered, not running

        proc, port = start_proxy(registry, stub, log, idle=100000, tick=0.3)
        procs.append(proc)

        host = "localhost:%d" % port
        status, _, body = request(port, "a." + host)
        check("a.localhost reaches a", body, "A a.localhost:%d" % port)
        status, _, body = request(port, "b." + host)
        check("b.localhost reaches b", body, "B b.localhost:%d" % port)
        status, _, body = request(port, "B." + host)
        check("the host is case-insensitive", body.split(" ")[0], "B")

        status, head, body = request(port, host)
        check("the bare host lists the features", status, "HTTP/1.1 200 OK")
        check("the list names every feature", all(x in body for x in (">a<", ">b<", ">c<")), True)
        check("the list says which run", body.count(">running<"), 2)
        check("a local list links by subdomain",
              "href='http://a.localhost:%d/'" % port in body, True)
        check("the proxy's own pages close the connection",
              "Connection: close" in head, True)

        check_gate(port, root)

        # A feature with a database block of its own is offered its Studio —
        # enabled in the stub config and actually listening, at base + 3 — but
        # not Inbucket: disabled in that same config, so its port (base + 4)
        # is never even guessed at, let alone offered as a dead link.
        svc_base = free_port()
        svc_base -= svc_base % 10  # a block boundary, so base+3 is ours to bind
        svc_wt = register(registry, root, "svc", free_port(), db_base=svc_base)
        os.makedirs(os.path.join(svc_wt, "supabase"))
        with open(os.path.join(svc_wt, "supabase", "config.toml"), "w") as fh:
            fh.write("[studio]\nenabled = true\nport = 999\n"
                     "[local_smtp]\nenabled = false\nport = 999\n")
        studio = socket.socket()
        studio.bind(("127.0.0.1", svc_base + 3))
        studio.listen(1)
        try:
            status, _, body = request(port, host)
            check("a running, enabled service is offered, by its own port",
                  "href='http://127.0.0.1:%d/'" % (svc_base + 3) in body
                  and "svc — Studio" in body, True)
            check("a disabled service is never offered, even unprobed",
                  "svc — Inbucket" in body, False)
        finally:
            studio.close()

        # A stopped feature's services are not offered either — same config,
        # nothing listening on Studio's port this time.
        svc_base2 = free_port()
        svc_base2 -= svc_base2 % 10
        svc2_wt = register(registry, root, "svc2", free_port(), db_base=svc_base2)
        os.makedirs(os.path.join(svc2_wt, "supabase"))
        with open(os.path.join(svc2_wt, "supabase", "config.toml"), "w") as fh:
            fh.write("[studio]\nenabled = true\nport = 999\n")
        status, _, body = request(port, host)
        check("a stopped feature's own services are not offered",
              "svc2 — Studio" in body, False)

        # main has no database block of its own — its Studio is the shared
        # stack's, on the literal port its config names, not base + slot.
        main_studio_port = free_port()
        register(registry, root, "main", free_port(),
                 config_ports={"studio": main_studio_port})
        main_studio = socket.socket()
        main_studio.bind(("127.0.0.1", main_studio_port))
        main_studio.listen(1)
        try:
            status, _, body = request(port, host)
            check("main's own Studio is offered on its config's literal port",
                  "href='http://127.0.0.1:%d/'" % main_studio_port in body
                  and "main — Studio" in body, True)
        finally:
            main_studio.close()

        status, _, body = request(port, "100.64.0.1:%d" % port)
        check("a remote list links through the cookie",
              "href='/__sclaude/select?f=a'" in body, True)

        status, _, body = request(port, host, cookie="x=1; sclaude_feature=b")
        check("the cookie picks the feature on a bare host", body.split(" ")[0], "B")
        status, _, body = request(port, "a." + host, cookie="sclaude_feature=b")
        check("the host wins over the cookie", body.split(" ")[0], "A")

        status, head, _ = request(port, "100.64.0.1:%d" % port, "/__sclaude/select?f=a")
        check("select redirects", status, "HTTP/1.1 303 See Other")
        check("select sets the cookie", "Set-Cookie: sclaude_feature=a;" in head, True)
        status, _, _ = request(port, host, "/__sclaude/select?f=nope")
        check("select refuses an unknown feature", status, "HTTP/1.1 404 Not Found")
        status, head, _ = request(port, host, "/__sclaude/clear")
        check("clear drops the cookie", "Max-Age=0" in head, True)
        status, _, body = request(port, "a." + host, "/__sclaude/")
        check("/__sclaude/ is the list on any host", "Features" in body, True)

        status, _, body = request(port, "zz." + host)
        check("an unknown feature is a 404", status, "HTTP/1.1 404 Not Found")

        # An upgrade, then bytes both ways — HMR's shape.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(("GET /_next/webpack-hmr HTTP/1.1\r\nHost: a.%s\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n" % host).encode())
            got = b""
            while b"\r\n\r\n" not in got:
                got += s.recv(4096)
            check("the upgrade passes", got.split(b"\r\n")[0], b"HTTP/1.1 101 Switching Protocols")
            s.sendall(b"ping")
            check("bytes flow after the upgrade", s.recv(4096), b"ping")

        # A feature being removed is stopped on purpose: a page still open on it
        # must not bring its server back into a tree git is deleting.
        closing_wt = register(registry, root, "closing", free_port())
        open(os.path.join(closing_wt, ".sclaude/local/feature", "closing"), "w").close()
        status, _, body = request(port, "closing." + host)
        check("a closing feature is a 404", status, "HTTP/1.1 404 Not Found")
        time.sleep(0.3)
        check("a closing feature is never started", calls_for(log, "closing"), [])

        # A stopped feature is started by the first request for it, once.
        status, head, body = request(port, "c." + host)
        check("a stopped feature answers 503 while it starts", status,
              "HTTP/1.1 503 Service Unavailable")
        check("the page says it is starting and reloads",
              "Starting c" in body and "http-equiv=refresh" in body, True)
        check("and marks the 503 as the proxy's own",
              "X-Sclaude-Proxy: starting" in head, True)
        for _ in range(3):
            request(port, "c." + host)
        wait_for(lambda: answers_on(c_port), 10)
        check("started once however often it is asked",
              calls_for(log, "c"), ["wt-c dev --no-browser"])
        status, _, body = request(port, "c." + host)
        check("then it answers", body, "C c.localhost:%d" % port)

        # A start that fails says so, with the log, and waits to be asked again.
        d = register(registry, root, "d", free_port())
        open(os.path.join(d, ".sclaude/local/feature", "fail"), "w").close()
        request(port, "d." + host)
        wait_for(lambda: len(calls_for(log, "d")) == 1, 5)
        time.sleep(0.5)
        status, head, body = request(port, "d." + host)
        check("a failed start is a 502", status, "HTTP/1.1 502 Bad Gateway")
        check("and marks the 502 as the proxy's own",
              "X-Sclaude-Proxy: failed" in head, True)
        check("the failure shows the log", "boom: the build broke" in body, True)
        request(port, "d." + host)
        check("a failed start is not retried by itself", len(calls_for(log, "d")), 1)
        status, _, _ = request(port, host, "/__sclaude/start?f=d")
        wait_for(lambda: len(calls_for(log, "d")) == 2, 5)
        check("start retries", (status, len(calls_for(log, "d"))),
              ("HTTP/1.1 303 See Other", 2))

        # Idle: a second proxy that gives up on a feature after a second.
        idle_registry = os.path.join(root, "idle-registry")
        os.makedirs(idle_registry)
        e = register(idle_registry, root, "e", free_port())
        f = register(idle_registry, root, "f", free_port())
        for wt in (e, f):
            subprocess.run([stub, "dev", "--no-browser"], cwd=wt,
                           env=dict(os.environ, STUB_LOG=log))
        e_port = json.load(open(os.path.join(e, ".sclaude/local/feature", "state.json")))["dev"]["port"]
        f_port = json.load(open(os.path.join(f, ".sclaude/local/feature", "state.json")))["dev"]["port"]
        wait_for(lambda: answers_on(e_port) and answers_on(f_port), 5)
        # Something is working in f: a shell, a session, a regression.
        worker = subprocess.Popen(["sleep", "30"], cwd=f)
        try:
            idle_proxy, _ = start_proxy(idle_registry, stub, log, idle=1, tick=0.3)
            procs.append(idle_proxy)
            wait_for(lambda: not answers_on(e_port), 8)
            check("an idle feature is stopped", "wt-e dev --stop" in stub_calls(log), True)
            check("its server is gone", answers_on(e_port), False)
            time.sleep(1.5)
            check("a feature something works in is not",
                  "wt-f dev --stop" in stub_calls(log), False)
        finally:
            worker.kill()
            worker.wait()

        # A request routed by the cookie asks the server to close after it, so
        # the next request — maybe after a switch — is routed afresh; one
        # routed by the host keeps its connection.
        echo_srv, echo_port = connection_echo()
        ups.append(echo_srv)
        register(registry, root, "h", echo_port)
        _, _, body = request(port, host, cookie="sclaude_feature=h")
        check("a cookie-routed request closes after the answer", body, "connection=close")
        _, _, body = request(port, "h." + host)
        check("a host-routed request keeps its connection", body, "connection=")

        status, _, body = request(port, host, "/__sclaude/ping")
        check("ping answers cheaply", (status, body), ("HTTP/1.1 200 OK", "sclaude-proxy"))

        # A start that could not even be launched says so on the page.
        broken_proxy, broken_port = start_proxy(registry, "/nonexistent/sclaude", log,
                                                idle=100000, tick=100)
        procs.append(broken_proxy)
        g = register(registry, root, "g", free_port())
        request(broken_port, "g.localhost:%d" % broken_port)
        status, _, body = request(broken_port, "g.localhost:%d" % broken_port)
        check("an unlaunchable start is a 502 that says why",
              (status, "could not run" in body), ("HTTP/1.1 502 Bad Gateway", True))

        # A clean start whose server was stopped later, with no request through
        # the proxy in between, is started again — once.
        grace_proxy, grace_port = start_proxy(registry, stub, log, idle=100000, tick=100,
                                              grace=0.5)
        procs.append(grace_proxy)
        k_port = free_port()
        k = register(registry, root, "k", k_port)
        stop_k = lambda: subprocess.run([stub, "dev", "--stop"], cwd=k,
                                        env=dict(os.environ, STUB_LOG=log))
        request(grace_port, "k.localhost:%d" % grace_port)
        wait_for(lambda: answers_on(k_port), 5)
        stop_k()
        wait_for(lambda: not answers_on(k_port), 5)
        time.sleep(0.8)
        status, _, _ = request(grace_port, "k.localhost:%d" % grace_port)
        wait_for(lambda: len([c for c in calls_for(log, "k") if "--no-browser" in c]) == 2, 5)
        check("a long-finished clean start is started again",
              (status, len([c for c in calls_for(log, "k") if "--no-browser" in c])),
              ("HTTP/1.1 503 Service Unavailable", 2))
        wait_for(lambda: answers_on(k_port), 5)
        stop_k()
        wait_for(lambda: not answers_on(k_port), 5)
        time.sleep(0.8)
        status, _, _ = request(grace_port, "k.localhost:%d" % grace_port)
        check("but not a second time", status, "HTTP/1.1 502 Bad Gateway")

        # A dead link does not break the list.
        os.symlink(os.path.join(root, "missing"), os.path.join(registry, "dead"))
        status, _, body = request(port, host)
        check("a dead link is left out", (status, ">dead<" in body), ("HTTP/1.1 200 OK", False))
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=5)
        for s in ups:
            s.close()
        # Whatever the stub started, it recorded.
        for dirpath, _, files in os.walk(root):
            if "stub.pid" in files:
                try:
                    os.kill(int(open(os.path.join(dirpath, "stub.pid")).read()), 15)
                except (OSError, ValueError):
                    pass
        shutil.rmtree(root, ignore_errors=True)

    # A proxy whose own code changes steps down onto the new code: one left
    # on old code looked in the old state folder and found no feature.
    watched = tempfile.mkdtemp(prefix="proxy-watch-")
    try:
        # A copy with the library beside it, as in the checkout, so that its
        # file can be touched without touching the real one.
        os.makedirs(os.path.join(watched, "bin"))
        shutil.copytree(os.path.join(os.path.dirname(PROXY), "..", "sclaude", "lib"),
                        os.path.join(watched, "sclaude", "lib"))
        copy = os.path.join(watched, "bin", "sclaude-proxy")
        shutil.copy(PROXY, copy)
        port = free_port()
        env = dict(os.environ, SCLAUDE_PROXY_PORT=str(port), SCLAUDE_PROXY_BIND="127.0.0.1",
                   SCLAUDE_DEV_REGISTRY=watched, SCLAUDE_PROXY_WATCH="0.2")
        env.pop("LISTEN_PID", None)
        proc = subprocess.Popen([sys.executable, copy], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            wait_for(lambda: answers_on(port), 5)
            time.sleep(0.5)
            os.utime(copy, (time.time() + 5, time.time() + 5))
            time.sleep(1.5)
            wait_for(lambda: answers_on(port), 5)
            check("a code change is picked up, and it answers again", answers_on(port), True)
        finally:
            proc.terminate()
            _, err = proc.communicate(timeout=5)
        check("it says it restarted", b"its code changed" in err, True)
        # Started by the socket, as systemd does it: the same process goes on,
        # on the socket it was handed, since an exit takes the unit's dev
        # servers down with it.
        port = free_port()
        launcher = ("import os, socket, sys\n"
                    "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
                    "s.bind(('127.0.0.1', %d)); s.listen(16)\n"
                    "os.dup2(s.fileno(), 3); os.set_inheritable(3, True)\n"
                    "os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1')\n"
                    "os.execv(sys.executable, [sys.executable, %r])\n" % (port, copy))
        senv = dict(env)
        proc = subprocess.Popen([sys.executable, "-c", launcher], env=senv,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            wait_for(lambda: answers_on(port), 5)
            # The socket listens before the proxy is up on it: give it time
            # to read its own file first.
            time.sleep(1)
            os.utime(copy, (time.time() + 10, time.time() + 10))
            time.sleep(1.5)
            check("socket-started: still the same process", proc.poll(), None)
            check("socket-started: answers on the new code", answers_on(port), True)
        finally:
            proc.terminate()
            _, err = proc.communicate(timeout=5)
        check("socket-started: it restarted in place", b"its code changed" in err, True)
    finally:
        shutil.rmtree(watched, ignore_errors=True)

    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    print("%d/%d passed" % (total - len(failures), total))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
