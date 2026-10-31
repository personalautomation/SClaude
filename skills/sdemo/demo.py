#!/usr/bin/env python3
#
# /sdemo's links: a page of a feature, opened signed in as a given user, at
# the address the person can open from where they are now.
#
#   demo.py link <email> [<path>] [--feature F] [--where laptop|phone]
#   demo.py users [--feature F]
#   demo.py criteria [--feature F]      the issue's acceptance criteria
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
import subprocess
import sys
from urllib.parse import urlencode, urlsplit

INSTRUMENTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, INSTRUMENTS)
sys.path.insert(0, os.path.join(INSTRUMENTS, "sclaude", "lib"))
import dev_login  # noqa: E402

REGISTRY = os.environ.get("SCLAUDE_DEV_REGISTRY") or os.path.expanduser("~/.claude/sclaude/dev")
PROXY_PORT = int(os.environ.get("SCLAUDE_PROXY_PORT") or 3000)


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
    for note in notes:
        print("warn: " + note)


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
    rest = []
    it = iter(argv[1:])
    for arg in it:
        if arg == "--feature":
            label = next(it, "")
        elif arg == "--where":
            where = next(it, "")
            if where not in ("laptop", "phone"):
                die("--where is laptop or phone")
        else:
            rest.append(arg)
    if not rest or rest[0] not in ("link", "users", "criteria"):
        die("usage: demo.py link <email> [<path>] | users | criteria  "
            "[--feature F] [--where laptop|phone]")
    label, wt = feature(label)
    if rest[0] == "users":
        cmd_users(label, wt)
    elif rest[0] == "criteria":
        cmd_criteria(label, wt)
    else:
        cmd_link(rest[1:], label, wt, where)


if __name__ == "__main__":
    main(sys.argv)
