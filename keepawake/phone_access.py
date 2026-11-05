# keepawake's Telegram bot — the phone's way in: tailscale serve and funnel,
# the gate, whether the funnel's name is published yet, and the proxy's lazy
# start.
#
# Part of the bot that keepawake/telegramd.py runs.

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from keepawake.i18n import t
from keepawake.state import locked, read
from keepawake import card_view, services, shell


log = logging.getLogger("keepawake")


def phone_button(origin, label):
    # The Mini App, green so it reads apart from the laptop's button. Only
    # while phone access is on (Settings); off, there is none.
    return [{"text": t("chrome.phoneopen"), "style": "success",
             "web_app": {"url": "%s/__sclaude/tg?f=%s" % (origin, label)}}] if origin else []


def map_button(origin, key, dev):
    """The feature's process map in the Mini App (sclaude/lib/flow/process.py,
    served by the proxy at /__sclaude/flow), through the gate; the map asks
    the proxy to start the dev server it is reached by (start=1). A feature
    that never had a dev server has no address yet: the button then starts
    one first (the card's "map" press), and the card comes back with the
    map's own button. None while phone access is off."""
    if not origin:
        return []
    if not dev:
        return [{"text": t("act.map"), "callback_data": card_view.card_data("map", key)}]
    path = "/__sclaude/flow?f=%s&start=1" % dev[0]
    return [{"text": t("act.map"), "web_app": {"url": "%s/__sclaude/tg?f=%s&p=%s" % (
        origin, dev[0], urllib.parse.quote(path, safe=""))}}]


def port_open(port, host="127.0.0.1"):
    import socket
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def wsl_ip():
    # WSL's address in the Windows network. It changes on every restart of WSL,
    # so it is read afresh each time the card is shown rather than
    # remembered.
    out = shell.run("ip -4 -o addr show eth0")
    for part in out.split():
        if part.count(".") == 3 and "/" in part:
            return part.split("/")[0]
    return ""


def json_in(out):
    """The JSON object in a command's output, None when there is none. run()
    gives stderr with stdout, and a warning beside the answer — tailscale's
    after an upgrade, before tailscaled restarts — is not a failed answer."""
    start = (out or "").find("{")
    if start < 0:
        return None
    try:
        found, _end = json.JSONDecoder().raw_decode(out[start:])
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def serve_config():
    """`tailscale serve status`, parsed; {} when it does not answer."""
    return json_in(shell.run("tailscale serve status --json", timeout=10)) or {}


def phone_origin(config=None):
    """Where a phone opens features: the `tailscale serve` HTTPS name when it
    fronts the proxy's port, the node's tailnet address otherwise.

    The name is worth preferring, not merely nicer. The page opens on either,
    but only the name survives a sign-in: in development the app sends a person
    back to the address they came from, and Supabase Auth refuses to redirect
    to an IP whatever its allow-list says. HTTPS also makes the page a secure
    context, which push notifications need."""
    if config is None:
        config = serve_config()
    for hostport, web in (config.get("Web") or {}).items():
        handler = ((web or {}).get("Handlers") or {}).get("/") or {}
        if str(handler.get("Proxy", "")).rstrip("/").endswith(":%d" % services.DEV_PORT):
            host, _, port = hostport.rpartition(":")
            return "https://%s" % host if port == "443" else "https://%s:%s" % (host, port)
    # The node's address, from code-server's config as everywhere in this bot.
    host = services.code_url().split("//")[1].split(":")[0]
    return "http://%s:%d" % (host, services.DEV_PORT)


# The phone's entry from the internet, for a phone without Tailscale: the
# gate (`sclaude-proxy --gate`, socket-activated on 127.0.0.1:3001) behind
# `tailscale funnel` on :8443. The person switches it in Settings
# (`phone_toggle`), and it stays as they left it across restarts of the bot,
# but not of the machine (`phone_off_after_boot`). A funnel just turned on is
# not reachable for minutes, so the app is offered only once its name is
# published (below). While it is on, what stands at the door is the gate,
# which lets in only the bot's owner.
GATE_PORT = 3001
GATE_LOCAL = "http://127.0.0.1:%d" % GATE_PORT
GATE_FUNNEL_PORT = 8443
FUNNEL_ON = "tailscale funnel --bg --https=%d %s" % (GATE_FUNNEL_PORT, GATE_LOCAL)
FUNNEL_OFF = "tailscale funnel --https=%d off" % GATE_FUNNEL_PORT


def phone_on():
    """Turn phone access on: (on, what the commands said). The gate's
    socket is started unless something already answers on its port — the
    gate itself, run by hand — which would make the socket fail to bind.
    On means the funnel is set up; the app opens once the address is
    published (gate_origin)."""
    PUBLISHED.update(host="", ok=False)
    start = "" if port_open(GATE_PORT) else "systemctl --user start sclaude-gate.socket && "
    out = shell.run(start + FUNNEL_ON, timeout=60)
    with locked() as st:
        st["phone_on_at"] = int(time.time())
        st.pop("published", None)
    return bool(gate_origin(None, False)), out


# A funnel just turned on is not reachable at once: Tailscale publishes its
# name in public DNS only after a while (five minutes once), and a phone that
# asks before then is told the name does not exist — and keeps that answer for
# five minutes more. So nothing offers the app until the name is there: the
# chat says it is waiting, and changes that message when it is ready.
#
# The name is asked of the zone's own nameserver, which keeps no answer: a
# resolver asked too early would itself remember "no such name" for minutes.
# DNS over HTTPS stands in when that fails, and the system's resolver only
# when DNS over HTTPS cannot be reached at all: some networks block every
# such service by name, and the probe then never found the name and the app
# waited the full PUBLISH_WAIT_MAX after every restart. Not when it answers
# "no such name": the system's resolver is the network's, a phone on the same
# Wi-Fi asks it too, and it would keep that answer for minutes.
PUBLISHED = {"host": "", "at": 0.0, "ok": False, "since": 0.0}
# How often a name not yet published is asked again.
PUBLISH_RECHECK = 10
# Past this the app is offered anyway, and the log says so.
PUBLISH_WAIT_MAX = 900


def doh(name, rtype):
    """The answers of DNS over HTTPS for a name, as data strings."""
    url = "https://dns.google/resolve?name=%s&type=%s" % (urllib.parse.quote(name), rtype)
    with urllib.request.urlopen(url, timeout=3) as resp:
        data = json.load(resp)
    return [a.get("data", "") for a in data.get("Answer") or []]


def dns_addresses(server, name):
    """The A records the nameserver at server has for name: one question over
    UDP, no recursion asked."""
    import socket
    qid = os.urandom(2)
    query = (qid + b"\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
             + b"".join(bytes([len(p)]) + p.encode() for p in name.split("."))
             + b"\x00\x00\x01\x00\x01")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        sock.sendto(query, (server, 53))
        data = sock.recv(4096)
    if data[:2] != qid or len(data) < 12:
        raise OSError("not the answer to this question")
    if data[3] & 0x0F:
        return []

    def skip_name(i):
        while data[i]:
            if data[i] & 0xC0 == 0xC0:
                return i + 2
            i += data[i] + 1
        return i + 1

    i = skip_name(12) + 4
    found = []
    for _ in range(int.from_bytes(data[6:8], "big")):
        i = skip_name(i)
        rtype, rlen = int.from_bytes(data[i:i + 2], "big"), int.from_bytes(data[i + 8:i + 10], "big")
        i += 10
        if rtype == 1 and rlen == 4:
            found.append(".".join(str(b) for b in data[i:i + 4]))
        i += rlen
    return found


def system_addresses(host):
    """The public addresses the system's resolver has for host, IPv4 first:
    the last resort of name_published. Public only: a resolver with MagicDNS
    answers the node's name with a tailnet address (100.64.0.0/10,
    fd7a:115c:a1e0::/48), which reaches the node directly and says nothing
    about the funnel's relays, and is_global is false for both ranges."""
    import ipaddress
    import socket
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return []
    found = []
    for family, _, _, _, sockaddr in sorted(infos, key=lambda i: i[0] != socket.AF_INET):
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if ip.is_global and str(ip) not in found:
            found.append(str(ip))
    return found


def funnel_answers(host, port, address):
    """True when the funnel at address carries a request to the gate: TLS
    under the funnel's name, and an HTTP answer back. A relay that has not
    taken the funnel up yet accepts the connection and drops the handshake."""
    import socket
    import ssl
    try:
        context = ssl.create_default_context()
        with socket.create_connection((address, port), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                tls.settimeout(5)
                tls.sendall(("GET /__sclaude/menu HTTP/1.1\r\nHost: %s:%d\r\n"
                             "Connection: close\r\n\r\n" % (host, port)).encode())
                return tls.recv(16).startswith(b"HTTP/")
    except (OSError, ssl.SSLError):
        return False


def name_published(host, port=None):
    """Whether a phone can reach the funnel now: its name in public DNS, and
    the relay at that address carrying it. The name alone is not enough — a
    funnel off for a few minutes keeps its name, and the relay takes a minute
    or more to carry it again."""
    import socket
    port = port or GATE_FUNNEL_PORT
    zone = ".".join(host.split(".")[-2:])
    try:
        server = socket.gethostbyname(doh(zone, "NS")[0].rstrip("."))
        addresses = dns_addresses(server, host)
    except (OSError, ValueError, IndexError):
        addresses = []
    if not addresses:
        # No answer from the zone's own server — an error, or a referral or
        # an empty answer, which raise nothing: a public resolver then.
        try:
            addresses = [a for a in doh(host, "A") if a.count(".") == 3]
        except urllib.error.HTTPError:
            # Reached, and it said no (a 429, a 503): as good as "no such name".
            addresses = []
        except OSError:
            # DNS over HTTPS out of reach — refused, or no answer in time, as
            # where its servers are dropped: the system's resolver then.
            addresses = system_addresses(host)
        except ValueError:
            addresses = []
    return any(funnel_answers(host, port, a) for a in addresses[:2])


# The loop's probe, run in a thread: {host: None while running, else the
# answer not yet taken}. Off in tests, which want the answer at once.
PROBE = {}
PROBE_ASYNC = True


def probe_published(host):
    """The loop's probe, in its thread. Whatever it raises is a "not yet":
    an answer never left would hold the wait on "still probing" for good."""
    try:
        ok = name_published(host)
    except Exception as exc:
        log.warning("the probe of %s failed: %s", host, exc)
        ok = False
    PROBE[host] = ok


def published(host, look=False):
    """Whether a phone can find the funnel's name: asked again every
    PUBLISH_RECHECK seconds until it can, then remembered while it lasts.
    Only the loop asks (look): a lookup is seconds of network, and a button
    or a menu takes the loop's last answer — the first one in a process
    excepted, which has none to take."""
    if not look:
        # The loop's answer, from the state where it leaves it: the gate
        # serving the menu page is another process, and its own first answer
        # would otherwise stand for the life of that process.
        shared = read().get("published") or {}
        if shared.get("host") == host:
            return bool(shared.get("ok"))
    if PUBLISHED["host"] == host and PUBLISHED["ok"]:
        return True
    now = time.time()
    if PUBLISHED["host"] == host and (not look or now - PUBLISHED["at"] < PUBLISH_RECHECK):
        return False
    if look and PROBE_ASYNC:
        # Off the loop: the probes take up to some fifteen seconds, and
        # every press would wait on them. The answer is taken on a later turn.
        # Meanwhile the last answer stands — the previous process's too, so
        # a restart does not read as access turned off for a turn.
        shared = read().get("published") or {}
        meanwhile = shared.get("host") == host and bool(shared.get("ok"))
        if host not in PROBE:
            PROBE[host] = None
            threading.Thread(target=probe_published, args=(host,), daemon=True).start()
            return meanwhile
        if PROBE[host] is None:
            return meanwhile          # still probing
        ok = PROBE.pop(host)
    else:
        ok = name_published(host)
    # Counted from the wait the chat showed, or else from this process's
    # first look that found the name not yet reachable — access turned on
    # from the terminal shows no wait, and would otherwise never be offered.
    if PUBLISHED["host"] != host or PUBLISHED["ok"]:
        PUBLISHED["since"] = now
    since = (read().get("phone_wait") or {}).get("since") or PUBLISHED["since"]
    if not ok and since and now - since > PUBLISH_WAIT_MAX:
        log.warning("%s is still not in public DNS after %d s: offering the app anyway",
                    host, PUBLISH_WAIT_MAX)
        ok = True
    PUBLISHED.update(host=host, at=now, ok=ok)
    if look:
        with locked() as st:
            st["published"] = {"host": host, "ok": ok}
    return ok


def gate_origin(config=None, ready=True, look=False):
    """https://<node>.<tailnet>.ts.net:8443 while the funnel carries the gate,
    "" while it does not — read from Tailscale, never remembered. With
    ready, also "" until a phone can find the name (published); without,
    the funnel's set-up alone counts, as for turning it off."""
    if config is None:
        config = serve_config()
    for hostport, allowed in (config.get("AllowFunnel") or {}).items():
        host, _, port = hostport.rpartition(":")
        if not allowed or port != str(GATE_FUNNEL_PORT):
            continue
        web = (config.get("Web") or {}).get(hostport) or {}
        proxy = str((((web.get("Handlers") or {}).get("/")) or {}).get("Proxy", ""))
        if proxy.rstrip("/").endswith(":3001"):
            if ready and not published(host, look):
                return ""
            return "https://%s:%s" % (host, port)
    PUBLISHED.update(host="", ok=False)
    # The funnel is off: the loop's last answer goes too, or a funnel set up
    # again by hand would read as published before it is.
    if read().get("published"):
        with locked() as st:
            st.pop("published", None)
    return ""


def proxy_start(label):
    """Ask the proxy to start the feature now — for ▶️, and for 📱 while the
    phone is still opening, where the first request would, but later. It goes
    through the proxy rather than `sclaude dev` so that the proxy knows it is
    starting and shows that page meanwhile. Not followed: the answer is
    a redirect to <label>.localhost, which is nothing to fetch from here."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", services.DEV_PORT, timeout=5)
        conn.request("GET", "/__sclaude/start?f=" + urllib.parse.quote(label))
        conn.getresponse().read()
        conn.close()
    except (OSError, http.client.HTTPException):
        pass
