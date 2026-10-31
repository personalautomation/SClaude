#!/usr/bin/env python3
#
# /sdemo's links: a page of a feature, opened signed in as a given user, at
# the address the person can open from where they are now.
#
#   demo.py link <email> [<path>] [--feature F] [--where laptop|phone]
#   demo.py users [--feature F]
#   demo.py criteria [--feature F]      the issue's acceptance criteria
#   demo.py play <demo.mjs> [--live] [--feature F] [--where laptop|phone]
#                                       the demo the skill wrote, played
#                                       (play.mjs): recorded, its page named
#   demo.py open <email> <path> [<email> <path>]... [--feature F]
#                                       the links in chrome-debug, laptop's
#
# open puts every scenario in the laptop's chrome-debug at once: one window
# per user, a browser context with cookies of its own (chrome-debug --window),
# so a user signed in for one scenario does not sign in every other tab of the
# feature — nor the window the person and the sessions work in. The windows of
# the feature's previous `open` are closed first; their ids are kept in
# WINDOWS.
#
# The sign-in is sclaude-proxy's /__sclaude/login (as=, next=; see
# sclaude/lib/dev_login.py). Where the person is, is guessed the way
# keepawake counts remote work: a device of the tailnet with traffic now
# (Active, the funnel's tag:ingress node aside) means they are away from the
# laptop, and the link goes on the address a phone opens features at —
# phone_origin in keepawake/telegramd.py, the bot's own. Otherwise the
# laptop's <feature>.localhost. --where overrides the guess. The other
# place's link follows as `other:` when there is a phone address at all;
# with none, the laptop's link is the only one, and `where:` says why.
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit

INSTRUMENTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, INSTRUMENTS)
sys.path.insert(0, os.path.join(INSTRUMENTS, "sclaude", "lib"))
import dev_login  # noqa: E402

REGISTRY = os.environ.get("SCLAUDE_DEV_REGISTRY") or os.path.expanduser("~/.claude/sclaude/dev")
PROXY_PORT = int(os.environ.get("SCLAUDE_PROXY_PORT") or 3000)
# Where a recorded demo goes in the feature's tree, and the address it is
# served at: DEMO_DIR and DEMO_PREFIX in bin/sclaude-proxy say the same.
DEMO_DIR = ".sclaude/local/demo"
DEMO_PREFIX = "/__sclaude/demo/"
HERE = os.path.dirname(os.path.realpath(__file__))
WINDOWS = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                       "sdemo")


def die(text):
    print("error: " + text)
    sys.exit(1)


def feature(label=""):
    """(label, worktree) of the named feature, or of the tree this runs in."""
    try:
        names = sorted(n for n in os.listdir(REGISTRY) if not n.startswith("."))
    except OSError:
        names = []
    if label:
        if label not in names:
            die("no feature %s; there are: %s" % (label, ", ".join(names) or "none"))
        return label, os.path.realpath(os.path.join(REGISTRY, label))
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    top = os.path.realpath(done.stdout.strip()) if done.returncode == 0 else ""
    for name in names:
        if top and os.path.realpath(os.path.join(REGISTRY, name)) == top:
            return name, top
    die("this directory is no feature's tree; name one with --feature: %s"
        % (", ".join(names) or "none"))


def active_peers():
    """Names of the tailnet's devices with traffic now, the funnel's node aside."""
    try:
        done = subprocess.run(["tailscale", "status", "--json"], capture_output=True,
                              text=True, timeout=10)
        peers = (json.loads(done.stdout).get("Peer") or {}).values()
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [p.get("HostName") or "?" for p in peers
            if p.get("Active") and "tag:ingress" not in (p.get("Tags") or [])]


def phone_origin():
    """The origin a phone opens features at, or "" when there is none — a
    loopback or wildcard address (no serve, code-server bound locally) is
    not one a phone can open."""
    try:
        from keepawake import telegramd
        origin = telegramd.phone_origin()
        host = (urlsplit(origin).hostname or "").lower()
    except Exception:  # no Tailscale, no bot, an address that does not parse
        return ""
    if not host or host in dev_login.LOOPBACK + ("0.0.0.0", "::") or host.startswith("127."):
        return ""
    return origin


def links(label, address, path):
    query = {"as": address, "next": dev_login.safe_next(path)}
    laptop = "http://%s.localhost:%d/__sclaude/login?%s" % (label, PROXY_PORT, urlencode(query))
    origin = phone_origin()
    phone = ("%s/__sclaude/login?%s" % (origin, urlencode(dict(f=label, **query)))
             if origin else "")
    return laptop, phone


def warnings(label, wt, address):
    """What the person must hear about this link before opening it."""
    if not dev_login.offered(wt):
        return ["the project's .sclaude/config.json has no devLogin: the link opens "
                "the page without signing in"]
    try:
        local = dev_login.supabase(wt)[3]
    except dev_login.Refused as exc:
        return ["the link will be refused: %s" % exc]
    if not local:
        own = dev_login.email()
        if not own:
            return ["the link will be refused: nobody to sign in as — put an address "
                    "in %s" % dev_login.LOGIN_FILE]
        if address.lower() != own.lower():
            return ["the link will be refused: %s has no local database of its own, so "
                    "it signs in only as %s" % (label, own)]
        return []
    try:
        if address.lower() not in [u.lower() for u in dev_login.users(wt)]:
            return ["%s is not a user of %s's database; it will be refused" % (address, label)]
    except dev_login.Refused as exc:
        return ["users not checked: %s" % exc]
    return []


def cmd_link(args, label, wt, where):
    if not args:
        die("whom to sign in as: demo.py link <email> [<path>]")
    address = dev_login.valid_address(args[0])
    if not address:
        die("%s is not an address" % args[0])
    path = args[1] if len(args) > 1 else "/"
    notes = warnings(label, wt, address)
    if dev_login.safe_next(path) != path:
        notes.append("%s is not a path on the feature (one that starts with a single /): "
                     "the link opens / instead" % path)
    laptop, phone = links(label, address, path)
    say_where(where, laptop, phone)
    for note in notes:
        print("warn: " + note)


def say_where(where, laptop, phone):
    """The where:, link: and other: lines: the link for where the person is."""
    peers = active_peers()
    place = where or ("phone" if peers else "laptop")
    why = ("as asked" if where else "tailnet traffic from " + ", ".join(peers) if peers
           else "no tailnet device active")
    if not phone:
        # Nothing a phone can open: the laptop's link alone, said so first.
        place, why = "laptop", why + "; no address a phone can open was found " \
            "(no tailscale serve or tailnet address)"
    print("where: %s — %s" % (place, why))
    print("link: " + (phone if place == "phone" else laptop))
    if place == "phone":
        print("other: " + laptop)
    elif phone:
        print("other: " + phone)
    return place


def cmd_open(args, label, wt):
    if not args or len(args) % 2:
        die("pairs of a user and a page: demo.py open <email> <path> [<email> <path>]...")
    by_user = {}
    for address, path in zip(args[::2], args[1::2]):
        valid = dev_login.valid_address(address)
        if not valid:
            die("%s is not an address" % address)
        by_user.setdefault(valid, []).append(path)
    record = os.path.join(WINDOWS, label)
    try:
        with open(record) as fh:
            old = fh.read().split()
    except OSError:
        old = []
    for context in old:
        subprocess.run(["chrome-debug", "--close-window", context], capture_output=True)
    opened = []
    for address, paths in by_user.items():
        notes = warnings(label, wt, address)
        for note in notes:
            print("warn: " + note)
        # A sign-in known to be refused opens no window of refusals.
        if any("refused" in note and "not checked" not in note for note in notes):
            print("failed: %s — not opened, the sign-in would be refused" % address)
            continue
        urls = [links(label, address, path)[0] for path in paths]
        done = subprocess.run(["chrome-debug", "--window"] + urls,
                              capture_output=True, text=True)
        words = done.stdout.split()
        if done.returncode or len(words) < 3:
            print("failed: %s — %s" % (address, (done.stderr or done.stdout).strip()))
            continue
        opened.append(words[2])
        print("window: %s — %d tab(s): %s" % (address, len(paths), " ".join(paths)))
    os.makedirs(WINDOWS, exist_ok=True)
    with open(record, "w") as fh:
        fh.write("\n".join(opened))
    if old:
        print("closed: %d window(s) of the previous demo" % len(old))


def demo_links(label, demo):
    """(laptop, phone) addresses of a recorded demo's page; phone "" when none."""
    tail = "%s%s/%s/" % (DEMO_PREFIX, label, demo)
    origin = phone_origin()
    return ("http://%s.localhost:%d%s" % (label, PROXY_PORT, tail),
            origin + tail if origin else "")


def cmd_play(args, label, wt, where, live):
    """Run a demo script (play.mjs): recorded into DEMO_DIR/<id>/ and its page
    named, or live in chrome-debug, left running for the person."""
    if len(args) != 1 or not os.path.isfile(args[0]):
        die("the demo script: demo.py play <demo.mjs> [--live]")
    demo = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(wt, DEMO_DIR, demo)
    os.makedirs(out, exist_ok=True)
    script = os.path.join(out, "demo.mjs")
    shutil.copyfile(args[0], script)
    base = "http://%s.localhost:%d" % (label, PROXY_PORT)
    run = ["node", os.path.join(HERE, "play.mjs"), script, "--out", out, "--base", base,
           "--feature", label]
    if live:
        # Brought forward first: the demo plays in its windows, in front of
        # the person. The player then keeps them until they are closed, so it
        # is left running on its own.
        subprocess.run(["chrome-debug"], capture_output=True)
        log = os.path.join(out, "live.log")
        with open(log, "w") as fh:
            subprocess.Popen(run + ["--live"], stdout=fh, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        print("live: playing in chrome-debug; ⏸ on the page hands it over. Its log: " + log)
        return
    done = subprocess.run(run, stdin=subprocess.DEVNULL)
    if done.returncode or not os.path.isfile(os.path.join(out, "index.html")):
        die("the demo did not finish (exit %d); what it recorded is in %s"
            % (done.returncode, out))
    laptop, phone = demo_links(label, demo)
    say_where(where, laptop, phone)
    # Its page goes to the feature's topic too, at the address a phone opens.
    title = demo
    try:
        with open(os.path.join(out, "demo.json")) as fh:
            title = json.load(fh).get("title") or demo
    except (OSError, ValueError):
        pass
    sent = subprocess.run(["sclaude-notify", "--quiet", "--in", wt, "🎬 %s\n%s" % (
        title, phone or laptop)], capture_output=True, text=True)
    if sent.returncode == 0:
        print("sent: the page's link to the feature's Telegram topic")


def cmd_users(label, wt):
    try:
        for address in dev_login.users(wt):
            print(address)
    except dev_login.Refused as exc:
        die(str(exc))


def cmd_criteria(label, wt):
    """The acceptance criteria, as sclaude keeps them in the feature's issue."""
    try:
        with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json")) as fh:
            issue = json.load(fh).get("issue")
    except (OSError, ValueError):
        issue = None
    if not issue:
        die("%s has no issue, so no acceptance criteria" % label)
    done = subprocess.run([sys.executable, os.path.join(INSTRUMENTS, "sclaude", "lib",
                                                        "acceptance.py"), str(issue), wt],
                          capture_output=True, text=True)
    if not done.stdout.strip():
        die("issue #%s has no acceptance criteria (or GitHub did not answer)" % issue)
    sys.stdout.write(done.stdout)


def main(argv):
    label = where = ""
    live = False
    rest = []
    it = iter(argv[1:])
    for arg in it:
        if arg == "--feature":
            label = next(it, "")
        elif arg == "--where":
            where = next(it, "")
            if where not in ("laptop", "phone"):
                die("--where is laptop or phone")
        elif arg == "--live":
            live = True
        else:
            rest.append(arg)
    if not rest or rest[0] not in ("link", "users", "criteria", "open", "play"):
        die("usage: demo.py link <email> [<path>] | users | criteria | "
            "open <email> <path>... | play <demo.mjs> [--live]  "
            "[--feature F] [--where laptop|phone]")
    label, wt = feature(label)
    if rest[0] == "users":
        cmd_users(label, wt)
    elif rest[0] == "criteria":
        cmd_criteria(label, wt)
    elif rest[0] == "play":
        cmd_play(rest[1:], label, wt, where, live)
    elif rest[0] == "open":
        cmd_open(rest[1:], label, wt)
    else:
        cmd_link(rest[1:], label, wt, where)


if __name__ == "__main__":
    main(sys.argv)
