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
#                                       in a session sclaude runs, also to the
#                                       feature's topic and issue (DEMO comment)
#   demo.py stale [--feature F]         whether the code changed since the
#                                       last demo: exit 0 record one, 1 fresh
#   demo.py replay [--feature F]        the last full demo's script played again
#   demo.py last [--feature F]          the last full demo: what a delta is
#                                       measured from (its commit, its script)
#   demo.py keep <reason> [--feature F] the last full demo carried on to the
#                                       code as it is, nothing a user meets
#                                       having changed: no recording, nothing
#                                       published, `stale` fresh again
#   demo.py publish <id> [--feature F]  a recording held back while sclaude
#                                       recorded (SCLAUDE_DEMO_HOLD=1), sent
#                                       to the topic and the issue now
#
# A full demo that goes to the topic deletes the messages of the full demo
# before it and of everything older (withdraw_old): the topic keeps the
# current demo and the deltas leading to it. The feature's page keeps every
# recording, as its history of versions.
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
# sclaude/lib/tree/dev_login.py). Where the person is, is guessed the way
# keepawake counts remote work: a device of the tailnet with traffic now
# (Active, the funnel's tag:ingress node aside) means they are away from the
# laptop, and the link goes on the address a phone opens features at —
# phone_origin in keepawake/phone_access.py, the bot's own. Otherwise the
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
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import dev_login  # noqa: E402

REGISTRY = os.environ.get("SCLAUDE_DEV_REGISTRY") or os.path.expanduser("~/.claude/sclaude/dev")
PROXY_PORT = int(os.environ.get("SCLAUDE_PROXY_PORT") or 3000)
# Where a recorded demo goes in the feature's tree, and the address it is
# served at: DEMO_DIR and DEMO_PREFIX in bin/sclaude-proxy say the same.
DEMO_DIR = ".sclaude/local/demo"
DEMO_PREFIX = "/__sclaude/demo/"
HERE = os.path.dirname(os.path.realpath(__file__))
from issue_comments import DEMO as DEMO_MARKER  # noqa: E402
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
        from keepawake import phone_access
        origin = phone_access.phone_origin()
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


def demo_links(label, demo=""):
    """(laptop, phone) addresses of the feature's demo page, or of one
    recording's with `demo`; phone "" when none."""
    tail = "%s%s/%s" % (DEMO_PREFIX, label, demo + "/" if demo else "")
    origin = phone_origin()
    return ("http://%s.localhost:%d%s" % (label, PROXY_PORT, tail),
            origin + tail if origin else "")


def cmd_play(args, label, wt, where, live):
    """Run a demo script (play.mjs): recorded into DEMO_DIR/<id>/ and its page
    named, or live in chrome-debug, left running for the person."""
    if len(args) != 1 or not os.path.isfile(args[0]):
        die("the demo script: demo.py play <demo.mjs> [--live]")
    # By the second, and apart from any demo already there: a replay can
    # follow a recording within the same second.
    stamp = demo = time.strftime("%Y%m%d-%H%M%S")
    n = 1
    while os.path.exists(os.path.join(wt, DEMO_DIR, demo)):
        n += 1
        demo = "%s-%d" % (stamp, n)
    out = os.path.join(wt, DEMO_DIR, demo)
    os.makedirs(out)
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
    try:
        with open(os.path.join(out, "demo.json")) as fh:
            results = json.load(fh)
    except (OSError, ValueError):
        results = {}
    # The commit the demo shows, and the tree it was played from — which is
    # what `stale` compares the code with: a demo plays the files as they
    # are, committed or not.
    results["head"] = git_head(wt)
    results["tree"] = git_tree(wt)
    with open(os.path.join(out, "demo.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    entry = remember(wt, demo, results)
    # The tree of a full demo that played is what `stale` measures from: a
    # ref keeps it, or git gc would prune an object nothing points to and
    # the demo would read as stale for ever. One per feature, moved on.
    if entry["kind"] == "main" and not entry["broken"] and not entry.get("held") and entry["tree"]:
        subprocess.run(["git", "-C", wt, "update-ref", DEMO_REF % label, entry["tree"]],
                       capture_output=True)
    write_feature_page(wt, label)
    # The feature's demo page, not this recording's: one address that always
    # shows the latest full demo and every change before it.
    laptop, phone = demo_links(label)
    say_where(where, laptop, phone)
    if entry["kind"] == "delta":
        print("delta: %s → %s — %s" % (entry["from"] or "?", entry["stage"], entry["change"]))
    # One that did not play stays here: the topic and the issue keep the
    # demo they had, and `stale` still measures from that one.
    if entry["broken"]:
        print("not published: %d scenario(s) did not play — fix the script and play it again"
              % entry["broken"])
        return
    # Held while sclaude records a demo again with nobody watching: the
    # session may play a script several times before it is right, and only
    # what it ends on is worth a message. Once it is over sclaude publishes
    # its last delta and its last full recording with `demo.py publish`, or
    # nothing when it ended on `keep`.
    if os.environ.get("SCLAUDE_DEMO_HOLD") == "1":
        print("held: on no page and in no message yet — once the session ends, sclaude "
              "publishes its last delta and last full recording (nothing after keep)")
        return
    publish(wt, label, demo, entry, results, phone)


def publish(wt, label, demo, entry, results, phone):
    """A recording that played, to the feature's topic and, a full one, to
    its issue — in a session sclaude runs; anywhere else the links already
    said are the whole answer."""
    # Outside a session sclaude runs, the links are the whole answer: nothing
    # goes to the feature's topic or its issue on somebody's casual /sdemo.
    if not os.environ.get("SCLAUDE_SESSION"):
        print("kept here: not a session sclaude runs, so nothing went to Telegram or GitHub")
        return
    out = os.path.join(wt, DEMO_DIR, demo)
    # For both places: the phone's address opens only on the tailnet, which
    # the laptop's Windows side is not on. The laptop's goes on the bare
    # loopback address — Telegram makes a link of an IP, not of a *.localhost
    # name — which the proxy routes by the path; the page's sign-in links
    # move on to the feature's own host.
    here = "http://127.0.0.1:%d%s%s/" % (PROXY_PORT, DEMO_PREFIX, label)
    title = results.get("title") or demo
    head_line = ("Δ %s → %s: %s" % (entry["from"] or "?", entry["stage"], entry["change"] or title)
                 if entry["kind"] == "delta" else "🎬 " + title)
    lines = [head_line] + (["📱 " + phone] if phone else []) + ["💻 " + here]
    # The videos themselves too, an album of them under the links: watched in
    # the chat without opening anything.
    clips = videos(out, results)
    sent = subprocess.run(["sclaude-notify", "--quiet", "--ids", "--in", wt]
                          + [a for c in clips[:10] for a in ("--video", c)]
                          + ["\n".join(lines)], capture_output=True, text=True)
    if sent.returncode == 0 and TEXT_ONLY in sent.stderr:
        print("sent: the links to the feature's Telegram topic; the videos were refused ("
              + sent.stderr.strip().splitlines()[-1] + ")")
    elif sent.returncode == 0 and not sent.stderr.strip():
        print("sent: the links%s to the feature's Telegram topic"
              % (" and %d video(s)" % len(clips[:10]) if clips else ""))
    else:
        print("not sent to Telegram: " + (sent.stderr.strip() or "sclaude-notify failed"))
    ids = [int(w) for line in sent.stdout.splitlines() if line.startswith(SENT)
           for w in line[len(SENT):].split() if w.isdigit()] if sent.returncode == 0 else []
    if ids:
        keep_messages(wt, demo, ids)
        # A full demo that went out makes the one before it, and what came
        # before that, old news in the chat: they leave it (the page keeps
        # them, as its history).
        if entry["kind"] == "main":
            print("telegram: " + withdraw_old(wt, demo))
    # The issue keeps one demo comment, written with a full demo: a delta goes
    # into it with the full demo that follows it (a delta is recorded first).
    if entry["kind"] == "main":
        print("issue: " + issue_comment(wt, results, phone, here))


def git_head(wt):
    done = subprocess.run(["git", "-C", wt, "rev-parse", "HEAD"], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


# What a demo can see of the code: every file of the tree as it is on disk —
# tracked or new, committed or not — but sclaude's own files and docs.
CODE = [".", ":!.sclaude", ":!*.md"]


# What sclaude-notify says when the videos were refused and the text went.
TEXT_ONLY = "the text did"
# How sclaude-notify --ids starts the line of the ids it sent, and --delete
# the ids it could not delete.
SENT = "sent: "
STAYED = "not deleted: "
# And the ids Telegram will never delete (older than 48 hours).
LEFT = "will not delete them: "

# One ref per feature holds the tree its last full demo played, which `stale`
# compares with; remove_worktree in sclaude/lib/tree/worktree.sh deletes it once
# the tree is gone.
DEMO_REF = "refs/sclaude/demo/%s"


def git_tree(wt):
    """The git tree of the working files as they are now (CODE), written
    through a scratch index so the real one is untouched; "" when git fails.
    Untracked files count — a new component nobody added yet is a change —
    unless .gitignore names them: build and test output a project leaves
    out of its .gitignore reads as code here, and is the project's gap."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        for cmd in (["read-tree", "HEAD"], ["add", "-A", "--"] + CODE):
            if subprocess.run(["git", "-C", wt] + cmd, env=env, capture_output=True).returncode:
                return ""
        done = subprocess.run(["git", "-C", wt, "write-tree"], env=env, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


# --- the feature's history of demos -----------------------------------------
#
# DEMO_DIR/history.json, oldest first: every recording, full ("main") or a
# delta — only what changed for the user since the last full one — with the
# stage it was recorded at, the commit it shows, and for a delta the stage it
# is measured from, the commits it covers and the change in a sentence.
# The feature's demo page (DEMO_DIR/index.html) is written from it.

STAGES = {"plan": "1-plan", "code": "2-code", "pr": "3-pr", "review": "4-review"}


def stage(wt):
    """Where in the cycle a recording is made: sclaude says so for its own
    (SCLAUDE_DEMO_STAGE: preview, epilogue); a step's session is its step."""
    named = os.environ.get("SCLAUDE_DEMO_STAGE", "").strip()
    if named:
        return named
    try:
        with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json")) as fh:
            step = json.load(fh).get("step") or ""
    except (OSError, ValueError):
        step = ""
    return STAGES.get(step, "by hand")


def history(wt):
    try:
        with open(os.path.join(wt, DEMO_DIR, "history.json")) as fh:
            found = json.load(fh)
        return found if isinstance(found, list) else []
    except (OSError, ValueError):
        return []


def broken(results):
    """How many scenarios did not play: not signed in, or a step that could
    not be done (a check that failed is a finding, not this)."""
    return sum(1 for s in results.get("scenarios") or [] if s.get("error"))


def last_main(wt):
    """The last full demo that played and went out: one with a scenario that
    did not is no record of the feature, and no demo to measure the code
    against; nor is a try still held back (`held`)."""
    mains = [e for e in history(wt)
             if e.get("kind") == "main" and e.get("head") and not e.get("broken")
             and not e.get("held")]
    return mains[-1] if mains else None


def remember(wt, demo, results):
    """The recording into the history; its entry."""
    kind = "delta" if results.get("kind") == "delta" else "main"
    entry = {"id": demo, "kind": kind, "stage": stage(wt), "when": results.get("made") or "",
             "head": results.get("head") or "", "tree": results.get("tree") or "",
             "title": results.get("title") or "",
             "change": results.get("change") or "", "scenarios": len(results.get("scenarios") or []),
             "broken": broken(results)}
    # Held back while sclaude records with nobody watching: not on the page,
    # in the issue, or measured from, until `demo.py publish` lets it go.
    if os.environ.get("SCLAUDE_DEMO_HOLD") == "1":
        entry["held"] = True
    base = last_main(wt)
    if kind == "delta":
        entry["from"] = base["stage"] if base else ""
        entry["base"] = base["head"] if base else ""
        log = subprocess.run(["git", "-C", wt, "log", "--format=%h %s",
                              "%s..%s" % (entry["base"], entry["head"])],
                             capture_output=True, text=True) if base else None
        entry["commits"] = log.stdout.splitlines() if log and log.returncode == 0 else []
    found = history(wt) + [entry]
    with open(os.path.join(wt, DEMO_DIR, "history.json"), "w") as fh:
        json.dump(found, fh, indent=1)
    return entry


def keep_messages(wt, demo, ids):
    """The Telegram messages a recording went out as, into its entry, so a
    later full demo can take them back out of the chat."""
    entries = history(wt)
    for e in entries:
        if e.get("id") == demo and not e.get("kept"):
            e["messages"] = ids
    with open(os.path.join(wt, DEMO_DIR, "history.json"), "w") as fh:
        json.dump(entries, fh, indent=1)


def withdraw_old(wt, demo):
    """The chat's messages of every recording up to the full demo before
    `demo` (that one included) deleted: what stays in the topic is the new
    full demo and the deltas that lead to it — what the issue's comment
    shows too. The history keeps the entries; a deleted one loses its
    `messages`. What happened, in a few words."""
    entries = [e for e in history(wt) if not e.get("broken") and not e.get("held")
               and not e.get("kept")]
    pos = next((k for k, e in enumerate(entries) if e.get("id") == demo), None)
    if pos is None:
        return "nothing earlier to delete"
    mains = [k for k, e in enumerate(entries[:pos]) if e.get("kind") == "main"]
    if not mains:
        return "nothing earlier to delete"
    old = {e["id"]: e["messages"] for e in entries[:mains[-1] + 1] if e.get("messages")}
    ids = [m for ms in old.values() for m in ms]
    if not ids:
        return "nothing earlier to delete"
    done = subprocess.run(["sclaude-notify"] + [a for m in ids for a in ("--delete", str(m))],
                          capture_output=True, text=True)
    def named(marker):
        return {int(w) for line in done.stderr.splitlines() if marker in line
                for w in line.split(marker, 1)[1].split() if w.isdigit()}

    # What did not go stays in its entry, for the next full demo to try
    # again; a failure that names no id kept them all. What Telegram will
    # never delete (too old) is said, and not tried again.
    stayed = set() if done.returncode == 0 else named(STAYED) or set(ids)
    too_old = named(LEFT)
    old_note = "; %d too old for Telegram to delete, left in the chat" % len(too_old) if too_old else ""
    found = history(wt)
    for e in found:
        if e.get("id") in old and not e.get("kept"):
            kept = [m for m in e.get("messages") or [] if m in stayed]
            if kept:
                e["messages"] = kept
            else:
                e.pop("messages", None)
    with open(os.path.join(wt, DEMO_DIR, "history.json"), "w") as fh:
        json.dump(found, fh, indent=1)
    if stayed:
        why = [line for line in done.stderr.splitlines() if STAYED not in line and LEFT not in line]
        return "%d of %d earlier message(s) not deleted, kept to try again%s%s" % (
            len(stayed), len(ids), " (%s)" % "; ".join(why) if why else "", old_note)
    return "%d earlier message(s) deleted, from %d recording(s)%s" % (
        len(ids) - len(too_old), len(old), old_note)


def recording(wt, demo):
    try:
        with open(os.path.join(wt, DEMO_DIR, demo, "demo.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def versions(entries):
    """The feature's recordings as versions, oldest first: each full demo
    with the deltas recorded before it (a delta is recorded first, its full
    demo next) and the `keep`s that carried it on; plus the deltas after the
    last full one, which no full demo covers yet."""
    out, pending = [], []
    for e in entries:
        if e.get("kind") == "delta":
            pending.append(e)
        elif e.get("kept"):
            mine = [v for v in out if v["main"]["id"] == e["id"]] or out[-1:]
            if mine:
                mine[-1]["confirms"].append(e)
        else:
            out.append({"main": e, "deltas": pending, "confirms": []})
            pending = []
    return out, pending


def moment(entry):
    """When a recording was made, as a datetime in this machine's zone;
    None when its entry does not say."""
    import datetime
    try:
        return datetime.datetime.fromisoformat(entry.get("when") or "").astimezone()
    except ValueError:
        return None


def at(entry):
    found = moment(entry)
    return found.strftime("%a %-d %b, %H:%M") if found else "an unknown time"


def lasted(start, end):
    """How long a version was the current one, roughly: "3 h 20 min"."""
    a, b = moment(start), moment(end)
    if not a or not b or b < a:
        return ""
    mins = int((b - a).total_seconds() // 60)
    if mins < 60:
        return "%d min" % max(mins, 1)
    if mins < 48 * 60:
        return "%d h %d min" % (mins // 60, mins % 60) if mins % 60 else "%d h" % (mins // 60)
    return "%d days" % round(mins / 1440)


def write_feature_page(wt, label):
    """DEMO_DIR/index.html: the feature's demos as versions. On top the
    current one — the latest full demo, since when it is current, what
    changed in it, its videos; below, every earlier version, newest first,
    marked outdated, with the time it was the current one. Nothing is left
    out: the topic keeps only the current demo, the page keeps them all."""
    import html as h
    # Only what played and went out: a recording that did not, or one still
    # held, was never published.
    entries = [e for e in history(wt) if not e.get("broken") and not e.get("held")]
    found, newer = versions(entries)

    def clips(entry):
        """(video or "", scenario) for each scenario, in order — the page
        plays any size, unlike a comment."""
        rec = recording(wt, entry["id"])
        out = []
        for sc in rec.get("scenarios") or []:
            path = pick(os.path.join(wt, DEMO_DIR, entry["id"]), sc)
            out.append((os.path.relpath(path, os.path.join(wt, DEMO_DIR)) if path else "", sc))
        return out

    def grid(entry, preload):
        return "<div class=grid>%s</div>" % "".join(
            "<figure>%s<figcaption>%s</figcaption></figure>" % (
                "<video controls playsinline preload=%s src='%s'></video>" % (preload, h.escape(c))
                if c else "<p class=sub>⚠ no video: %s</p>" % h.escape(sc.get("error") or "not recorded"),
                h.escape(sc.get("title", "")))
            for c, sc in clips(entry))

    def facts(e):
        return "%s · on <code>%s</code> · %d scenario(s)" % (
            h.escape(e.get("stage") or "?"), h.escape((e.get("head") or "")[:7]),
            e.get("scenarios") or 0)

    def changes(deltas, preload):
        """The deltas of a version, newest first: the change for the user,
        between which stages, the commits, the videos."""
        return "".join(
            "<div class=delta><div><b>Δ %s</b></div><div class=sub>%s → %s · %s · "
            "<a href='%s/'>its page →</a></div>"
            "<details><summary>%d commit(s)</summary>%s</details>%s</div>" % (
                h.escape(e.get("change") or e.get("title") or "a change"),
                h.escape(e.get("from") or "?"), h.escape(e.get("stage") or "?"), at(e), h.escape(e["id"]),
                len(e.get("commits") or []),
                "".join("<div><code>%s</code></div>" % h.escape(c) for c in e.get("commits") or []),
                "<details><summary>video</summary>%s</details>" % grid(e, "none") if preload == "none"
                else grid(e, preload))
            for e in deltas[::-1])

    def confirms(v):
        # A demo carried on (`keep`) was recorded on an earlier commit and
        # still showed the feature on a later one: said, with why.
        return "".join(
            "<p class=ok>✓ still current on <code>%s</code> at %s, %s: %s</p>" % (
                h.escape((k.get("head") or "")[:7]), h.escape(k.get("stage") or "?"), at(k),
                h.escape(k.get("kept") or ""))
            for k in v["confirms"])

    title = found[-1]["main"].get("title") if found else ""
    parts = ["<header><h1>%s</h1><p class=sub>%s · %d version(s) of the demo</p></header>" % (
        h.escape(title or label), h.escape(label), len(found))]
    if newer:
        parts.append("<section class='card newer'><span class='badge amber'>NEWER CHANGE</span>"
                     "<h2>Not in a full demo yet</h2><p class=sub>Recorded after the current "
                     "version; the next full demo will take it in.</p>%s</section>"
                     % changes(newer, "metadata"))
    if found:
        cur = found[-1]
        m = cur["main"]
        parts.append(
            "<section class='card current'><span class='badge green'>CURRENT</span> "
            "<span class=ver>v%d</span><h2>Current since %s</h2><p class=sub>%s · "
            "<a href='%s/'>scenarios with their steps →</a></p>%s%s%s</section>" % (
                len(found), at(m), facts(m), h.escape(m["id"]), confirms(cur),
                ("<h3>What changed in this version</h3>" + changes(cur["deltas"], "metadata"))
                if cur["deltas"] else "",
                "<h3>The whole feature</h3>" + grid(m, "metadata")))
    if len(found) > 1:
        cards = []
        for n in range(len(found) - 2, -1, -1):
            v, nxt = found[n], found[n + 1]
            m = v["main"]
            took = lasted(m, nxt["main"])
            cards.append(
                "<li class='card old'><span class='badge grey'>OUTDATED</span> "
                "<span class=ver>v%d</span><h3>Current from %s to %s%s</h3>"
                "<p class=sub>%s · replaced by v%d · <a href='%s/'>scenarios with their steps →</a></p>"
                "%s%s<details><summary>the whole feature as it was (%d video(s))</summary>%s</details></li>" % (
                    n + 1, at(m), at(nxt["main"]), " <span class=sub>(%s)</span>" % took if took else "",
                    facts(m), n + 2, h.escape(m["id"]), confirms(v),
                    changes(v["deltas"], "none"), len([c for c, _ in clips(m) if c]), grid(m, "none")))
        parts.append("<h2 class=hist>History — earlier versions, newest first</h2>"
                     "<ol class=timeline>%s</ol>" % "".join(cards))
    if not entries:
        parts.append("<p>No demo recorded yet.</p>")
    page = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>%s — demos</title><style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--green:#15803d;
--greenbg:#dcfce7;--amber:#b45309;--amberbg:#fef3c7;--grey:#57534e;--greybg:#e7e5e4}
@media (prefers-color-scheme:dark){:root{--bg:#18181b;--card:#232326;--ink:#f4f4f5;--mute:#a1a1aa;
--line:#3f3f46;--green:#4ade80;--greenbg:#14532d;--amber:#fbbf24;--amberbg:#451a03;--grey:#d4d4d8;--greybg:#3f3f46}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0}
h2{font-size:18px;margin:6px 0 2px}h3{font-size:15px;margin:14px 0 6px}
.sub{color:var(--mute);font-size:13px;margin:2px 0}a{color:#2563eb}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:16px 0}
.current{border-left:6px solid var(--green)}.newer{border-left:6px solid var(--amber)}
.old{border-left:6px solid var(--line);opacity:.85}.old:hover{opacity:1}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.06em;padding:2px 8px;border-radius:999px}
.green{color:var(--green);background:var(--greenbg)}.amber{color:var(--amber);background:var(--amberbg)}
.grey{color:var(--grey);background:var(--greybg)}.ver{color:var(--mute);font-size:13px;font-weight:600}
.ok{color:var(--green);font-size:13px;margin:4px 0}
.delta{border-top:1px dashed var(--line);padding:8px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;align-items:start;margin-top:6px}
figure{margin:0;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:8px}
figcaption{font-size:13px;margin-top:4px}video{width:100%%;max-height:60vh;border-radius:8px;background:#000}
details{margin:4px 0}summary{cursor:pointer;color:var(--mute);font-size:13px}
.hist{margin-top:32px}.timeline{list-style:none;margin:0;padding:0 0 0 18px;border-left:2px solid var(--line)}
.timeline>li{position:relative}.timeline>li::before{content:"";position:absolute;left:-26px;top:20px;
width:10px;height:10px;border-radius:50%%;background:var(--line);border:2px solid var(--bg)}
code{font-size:13px}
</style></head><body><main>%s</main></body></html>""" % (h.escape(label), "".join(parts))
    with open(os.path.join(wt, DEMO_DIR, "index.html"), "w") as fh:
        fh.write(page)


# GitHub takes a video attached to a comment up to 10 MB on a free plan; a
# larger one is left to the page.
ATTACH_MAX = 10 * 1024 * 1024


def pick(out, scenario):
    """A scenario's video: the MP4 a browser and Telegram play, or the WebM
    when there is no MP4; "" when it has none."""
    sources = [v.get("src") for v in scenario.get("sources") or [] if v.get("src")]
    name = next((v for v in sources if v.endswith(".mp4")), sources[0] if sources else "")
    path = os.path.join(out, name) if name else ""
    return path if path and os.path.isfile(path) else ""


def videos(out, results):
    """The scenarios' videos a comment or a chat can carry, in order: each
    one's video, none above GitHub's size for an attachment."""
    found = [pick(out, s) for s in results.get("scenarios") or []]
    return [v for v in found if v and os.path.getsize(v) <= ATTACH_MAX]


def scenario_rows(results, out, root):
    """A recording's scenarios for the comment: how each went, its video under it."""
    rows = []
    for i, s in enumerate(results.get("scenarios") or [], 1):
        bad = [st for st in s.get("steps") or [] if st.get("ok") is False or st.get("error")]
        how = ("⚠ " + s["error"] if s.get("error") else "skipped" if s.get("skipped")
               else "✗ %d step(s) not as expected" % len(bad) if bad else "✓")
        rows.append("**%d. %s** — as %s%s — %s" % (
            i, s.get("title", ""), s.get("as", ""),
            " · 📱 phone" if s.get("viewport") == "phone" else "", how))
        clip = videos(out, {"scenarios": [s]}) if out else []
        rows += ["", "![](./%s)" % os.path.relpath(clip[0], root), ""] if clip else [""]
    return rows


def demo_body(results, phone, here, out=None, deltas=(), root=None):
    """The issue's demo comment: the links; what changed since the last full
    demo (`deltas`: (entry, its recording, its directory)); the full demo,
    the commit it shows and how each scenario went, videos under them."""
    root = root or out
    head = results.get("head") or ""
    lines = [DEMO_MARKER, "### 🎬 Demo", "",
             "%s — recorded %s%s." % (results.get("title") or "The feature",
                                     time.strftime("%Y-%m-%d %H:%M"),
                                     " on `%s`" % head[:7] if head else ""), ""]
    lines += (["- 📱 phone, over the tailnet: " + phone] if phone else [])
    lines += ["- 💻 the laptop it runs on: " + here, ""]
    for entry, rec, where in deltas:
        lines += ["#### Δ What changed, %s → %s" % (entry.get("from") or "?", entry["stage"]), "",
                  entry.get("change") or "", ""]
        lines += ["<details><summary>%d commit(s)</summary>" % len(entry.get("commits") or []), ""]
        lines += ["- `%s`" % c for c in entry.get("commits") or []] + ["", "</details>", ""]
        lines += scenario_rows(rec, where, root)
    if deltas:
        lines += ["#### The whole feature", ""]
    lines += scenario_rows(results, out, root)
    lines += ["<sub>The page has each scenario's steps beside its video, a link on "
              "each step to go on by hand, signed in, and every change before; it "
              "opens on the developer's own devices. Recorded again when the code "
              "changes, in place of this one.</sub>"]
    return "\n".join(lines)


def issue_comment(wt, results, phone, here):
    """Write the demo comment on the feature's issue — the full demo just
    recorded and the deltas recorded since the one before it — its videos
    attached, in place of the one before; what happened. A comment's
    attachments cannot be changed by editing it, so the old one is deleted
    and a new one posted — the newest in the issue, where a reader looks
    first."""
    import issue_comments
    try:
        with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json")) as fh:
            issue = json.load(fh).get("issue")
    except (OSError, ValueError):
        issue = None
    if not issue:
        return "none — the feature has no issue"
    found = issue_comments.fetch(issue, cwd=wt)
    if found is None:
        return "not written — issue #%s could not be read (gh, network or permissions)" % issue
    root = os.path.join(wt, DEMO_DIR)
    # Only what played: a recording that did not was never published. A
    # keep is no recording, and no new version: the deltas since the full
    # demo before it still lead to this one, as on the page and in the topic.
    entries = [e for e in history(wt) if not e.get("broken") and not e.get("held")
               and not e.get("kept")]
    mains = [k for k, e in enumerate(entries) if e.get("kind") == "main"]
    since = mains[-2] + 1 if len(mains) > 1 else 0
    deltas = [(e, recording(wt, e["id"]), os.path.join(root, e["id"]))
              for e in entries[since:] if e.get("kind") == "delta"]
    out = os.path.join(root, entries[mains[-1]]["id"]) if mains else root
    clips = [c for _, rec, where in deltas for c in videos(where, rec)] + videos(out, results)
    body = demo_body(results, phone, here, out, deltas, root)
    note = os.path.join(root, "issue-comment.md")
    with open(note, "w") as fh:
        fh.write(body)
    try:
        done = subprocess.run(
            ["gh", "issue", "comment", str(issue), "--body-file", note]
            + [a for c in clips for a in ("--attach", c)],
            cwd=wt, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return "not posted on #%s (%s)" % (issue, exc)
    if done.returncode != 0:
        return "not posted on #%s (gh: %s)" % (issue, (done.stderr.strip().splitlines() or ["refused"])[-1])
    # The new one stands; only then does the old one go.
    old = [c for c in found["comments"] if (c.get("body") or "").startswith(DEMO_MARKER)]
    gone = sum(1 for c in old if issue_comments.comment_id(c) and subprocess.run(
        ["gh", "api", "-X", "DELETE", "repos/{owner}/{repo}/issues/comments/%s"
         % issue_comments.comment_id(c)], cwd=wt, capture_output=True).returncode == 0)
    return "posted on #%s with %d video(s)%s" % (
        issue, len(clips), ", the earlier one deleted" if gone else "")


def cmd_last(label, wt):
    """The last full demo, which a delta is measured from: its id, the commit
    it shows, the stage it was recorded at and its script."""
    main = last_main(wt)
    if not main:
        die("no full demo of %s recorded here yet: record one (/sdemo) before a delta" % label)
    print("last: %s on %s at %s" % (main["id"], main["head"][:7], main["stage"]))
    print("head: " + main["head"])
    print("script: " + os.path.join(wt, DEMO_DIR, main["id"], "demo.mjs"))


def cmd_replay(label, wt, where):
    """The last full demo's script, played again as it is: what sclaude falls
    back to when it cannot start a session to write the demo again. A step
    whose page changed under it is reported as failed."""
    main = last_main(wt)
    script = os.path.join(wt, DEMO_DIR, main["id"], "demo.mjs") if main else ""
    if not script or not os.path.isfile(script):
        die("no full demo of %s recorded here to play again" % label)
    cmd_play([script], label, wt, where, False)


def cmd_stale(label, wt):
    """Whether the product's code changed since the last full demo recorded
    here: exit 0 and `stale:` or `none:` — record one; exit 1 and `fresh:` —
    the demo shows the code as it is. Docs (*.md) and sclaude's own files do
    not count."""
    main = last_main(wt)
    if not main:
        print("none: no demo of %s recorded here yet" % label)
        return
    name, head = main["id"], main["head"]
    # Tree against tree where the demo noted its own and git still has it; a
    # demo from before that, or a tree lost after all, against its commit.
    kept = main.get("tree") and subprocess.run(
        ["git", "-C", wt, "cat-file", "-e", main["tree"]], capture_output=True).returncode == 0
    now = git_tree(wt) if kept else ""
    done = subprocess.run(["git", "-C", wt, "diff", "--name-only"]
                          + ([main["tree"], now] if now else [head]) + ["--"] + CODE,
                          capture_output=True, text=True)
    changed = [f for f in done.stdout.splitlines() if f.strip()]
    if done.returncode:
        print("stale: the commit of the last demo (%s) is not in this tree" % head[:7])
    elif changed:
        print("stale: %d file(s) changed since the demo %s on %s: %s" % (
            len(changed), name, head[:7], ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "")))
    else:
        print("fresh: the demo %s shows the code as it is (%s)" % (name, head[:7]))
        sys.exit(1)


def cmd_keep(args, label, wt):
    """The last full demo, carried on to the code as it is now: what sclaude
    asks for when the code changed since but nothing a user sees or does
    did — its videos still show the feature, and a new recording would say
    the same. Nothing is published: there is nothing new to show."""
    reason = " ".join(args).strip()
    if not reason:
        die("why the demo still shows the feature: demo.py keep <reason>")
    main = last_main(wt)
    if not main:
        die("no full demo of %s recorded here to keep" % label)
    entry = {"id": main["id"], "kind": "main", "stage": stage(wt),
             "when": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
             "head": git_head(wt), "tree": git_tree(wt), "title": main.get("title") or "",
             "change": "", "scenarios": main.get("scenarios") or 0, "broken": 0,
             "kept": reason, "recorded": main.get("recorded") or main["head"]}
    # Read before the file is opened for writing, which empties it.
    found = history(wt) + [entry]
    with open(os.path.join(wt, DEMO_DIR, "history.json"), "w") as fh:
        json.dump(found, fh, indent=1)
    if entry["tree"]:
        subprocess.run(["git", "-C", wt, "update-ref", DEMO_REF % label, entry["tree"]],
                       capture_output=True)
    write_feature_page(wt, label)
    print("kept: the demo %s still shows the feature on %s — %s"
          % (main["id"], entry["head"][:7], reason))


def cmd_publish(args, label, wt):
    """A recording that was held (SCLAUDE_DEMO_HOLD), published now: what
    sclaude does with a refresh session's last delta and last full
    recording, unless the session ended on `keep`."""
    if len(args) != 1:
        die("the recording to publish: demo.py publish <id>")
    found = [e for e in history(wt) if e.get("id") == args[0] and not e.get("kept")]
    if not found:
        die("no recording %s in this feature's history" % args[0])
    entry = found[-1]
    if entry.get("broken"):
        die("not published: %d scenario(s) of %s did not play" % (entry["broken"], args[0]))
    # Let go first: the issue comment and the page read only what is not held.
    entries = history(wt)
    for e in entries:
        if e.get("id") == args[0]:
            e.pop("held", None)
    with open(os.path.join(wt, DEMO_DIR, "history.json"), "w") as fh:
        json.dump(entries, fh, indent=1)
    entry.pop("held", None)
    if entry["kind"] == "main" and entry.get("tree"):
        subprocess.run(["git", "-C", wt, "update-ref", DEMO_REF % label, entry["tree"]],
                       capture_output=True)
    write_feature_page(wt, label)
    _, phone = demo_links(label)
    publish(wt, label, args[0], entry, recording(wt, args[0]), phone)


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
                                                        "cycle", "acceptance.py"), str(issue), wt],
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
    if not rest or rest[0] not in ("link", "users", "criteria", "open", "play", "stale",
                                   "replay", "last", "keep", "publish"):
        die("usage: demo.py link <email> [<path>] | users | criteria | "
            "open <email> <path>... | play <demo.mjs> [--live] | stale | replay | last | "
            "keep <reason> | publish <id>  "
            "[--feature F] [--where laptop|phone]")
    label, wt = feature(label)
    if rest[0] == "users":
        cmd_users(label, wt)
    elif rest[0] == "criteria":
        cmd_criteria(label, wt)
    elif rest[0] == "last":
        cmd_last(label, wt)
    elif rest[0] == "replay":
        cmd_replay(label, wt, where)
    elif rest[0] == "stale":
        cmd_stale(label, wt)
    elif rest[0] == "play":
        cmd_play(rest[1:], label, wt, where, live)
    elif rest[0] == "keep":
        cmd_keep(rest[1:], label, wt)
    elif rest[0] == "publish":
        cmd_publish(rest[1:], label, wt)
    elif rest[0] == "open":
        cmd_open(rest[1:], label, wt)
    else:
        cmd_link(rest[1:], label, wt, where)


if __name__ == "__main__":
    main(sys.argv)
