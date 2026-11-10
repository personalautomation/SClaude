#!/usr/bin/env python3
#
# The demo recorded again with nobody watching (demo_refresh in
# sclaude/lib/ship/demo.sh): what goes out, what is kept, what is said.
#
#   * A session that plays a script several times before it is right must
#     not send each try to the feature's topic and issue: with
#     SCLAUDE_DEMO_HOLD=1 `demo.py play` records and sends nothing, and
#     `demo.py publish <id>` sends the one sclaude picks, once.
#
#   * A change nobody sees needs no new recording: `demo.py keep` carries
#     the last full demo on to the code as it is, `stale` is fresh again,
#     and the page shows that demo once, still current.
#
#   * What the session found wrong in the product, and the checks of its
#     last recording that failed, reach sclaude's terminal
#     (sclaude/lib/ship/demo_refresh.py findings), not only its log.
#
# Run it with: python3 tests/demo-refresh.py
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")

failures = []


def check(name, got, want):
    if got != want:
        failures.append((name, want, got))


def git(wt, *args):
    return subprocess.run(["git", "-C", wt] + list(args), capture_output=True, text=True,
                          check=True).stdout.strip()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def said(fn, *args):
    out = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out):
        try:
            fn(*args)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue().splitlines()


saved_env = dict(os.environ)
with tempfile.TemporaryDirectory() as root:
    os.environ["HOME"] = root
    os.environ["SCLAUDE_DEV_REGISTRY"] = os.path.join(root, "registry")
    demo = load("demo", os.path.join(ROOT, "skills", "sdemo", "demo.py"))
    refresh = load("demo_refresh", os.path.join(LIB, "ship", "demo_refresh.py"))
    # No tailnet here: the laptop's link alone.
    demo.demo_links = lambda label, d="": ("http://f1.localhost/", "")

    wt = os.path.join(root, "wt")
    os.makedirs(wt)
    git(wt, "init", "-q")
    write(os.path.join(wt, ".gitignore"), ".sclaude/\n")
    write(os.path.join(wt, "app.ts"), "export const x = 1\n")
    git(wt, "add", "-A")
    git(wt, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-qm", "init")

    # Stand-ins: node plays a script by writing the page and the results it
    # is given; sclaude-notify writes down what it was asked.
    stub = os.path.join(root, "bin")
    asked = os.path.join(root, "asked")
    write(os.path.join(stub, "node"),
          '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = --out ] && echo x > "$2/index.html" && '
          '{ [ -n "$DEMO_JSON" ] && echo "$DEMO_JSON" || echo \'{"title": "T"}\'; } > "$2/demo.json"; '
          'shift; done\n')
    write(os.path.join(stub, "sclaude-notify"), '#!/bin/sh\necho "notify $*" >> %s\n' % asked)
    for name in ("node", "sclaude-notify"):
        os.chmod(os.path.join(stub, name), 0o755)
    os.environ["PATH"] = stub + os.pathsep + saved_env.get("PATH", "")
    os.environ["SCLAUDE_SESSION"] = "s1"
    script = os.path.join(root, "demo.mjs")
    write(script, "export default {scenarios: []}")

    def notified():
        if not os.path.exists(asked):
            return 0
        with open(asked) as fh:
            return sum(1 for line in fh if line.startswith("notify"))

    def play(hold, results=None):
        if hold:
            os.environ["SCLAUDE_DEMO_HOLD"] = "1"
        else:
            os.environ.pop("SCLAUDE_DEMO_HOLD", None)
        if results:
            os.environ["DEMO_JSON"] = json.dumps(results)
        else:
            os.environ.pop("DEMO_JSON", None)
        try:
            return said(demo.cmd_play, [script], "f1", wt, "laptop", False)
        finally:
            os.environ.pop("SCLAUDE_DEMO_HOLD", None)
            os.environ.pop("DEMO_JSON", None)

    # The demo of step 2, published as it is played.
    code, lines = play(False)
    check("play: without the hold, a recording goes out as it is played", notified(), 1)
    first = demo.last_main(wt)["id"]

    # A refresh: two tries held, a failed check in the last one.
    os.environ["SCLAUDE_DEMO_STAGE"] = "epilogue"
    before = len(demo.history(wt))
    code, lines = play(True)
    check("play: held, it says so and sends nothing",
          (any(l.startswith("held:") for l in lines), notified()), (True, 1))
    # Two tries at a delta: the first with a check that failed, fixed in the second.
    play(True, {"title": "T", "kind": "delta", "change": "First try", "scenarios": [
        {"title": "Try", "steps": [{"text": "a wait too short", "ok": False}]}]})
    first_delta = demo.history(wt)[-1]["id"]
    play(True, {"title": "T", "kind": "delta", "change": "Second try", "scenarios": [
        {"title": "Delta", "steps": [{"text": "the new hint", "ok": False,
                                      "error": "not seen within 10 s"}]}]})
    delta = demo.history(wt)[-1]["id"]
    code, lines = play(True, {"title": "T", "scenarios": [
        {"title": "Likes", "steps": [{"text": "the list says so", "ok": False,
                                      "error": "not seen within 10 s"}]}]})
    held_ids = refresh.held(wt, before)
    last = demo.history(wt)[-1]["id"]
    check("held: the last delta and the last full recording are the ones to publish",
          held_ids, [delta, last])
    check("held: nothing held is measured from, until it goes out",
          demo.last_main(wt)["id"], first)
    write(os.path.join(wt, demo.DEMO_DIR, "findings.md"),
          "- Paged view: the empty list names the wrong cause\n\n")
    check("findings: the session's lines, then the failed checks of what is published",
          refresh.findings(wt, os.path.join(wt, demo.DEMO_DIR, "findings.md"), before),
          ["Paged view: the empty list names the wrong cause",
           "Delta: a check failed — the new hint (not seen within 10 s)",
           "Likes: a check failed — the list says so (not seen within 10 s)"])
    for demo_id in held_ids:
        said(demo.cmd_publish, [demo_id], "f1", wt)
    check("publish: each held recording goes out once", notified(), 3)
    check("publish: a published full demo is the one measured from", demo.last_main(wt)["id"], last)
    with open(os.path.join(wt, demo.DEMO_DIR, "index.html")) as fh:
        page = fh.read()
    check("page: the delta that went out is shown, the try before it is not",
          ("Second try" in page, "First try" in page), (True, False))
    check("history: the try never published stays held",
          [e.get("held") for e in demo.history(wt) if e["id"] == first_delta], [True])
    code, lines = said(demo.cmd_publish, ["nothing"], "f1", wt)
    check("publish: an id the history does not hold is refused", (code != 0, notified()), (True, 3))

    # A change nobody sees: kept, not recorded.
    def stale():
        code, lines = said(demo.cmd_stale, "f1", wt)
        return code, (lines or [""])[0].split(":")[0]
    check("stale: nothing changed since the last recording", stale(), (1, "fresh"))
    write(os.path.join(wt, "app.ts"), "export const x = 2\n")
    git(wt, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-qam", "refactor")
    check("stale: a change since", stale(), (0, "stale"))
    before = len(demo.history(wt))
    # The session plays a try first, then decides nothing changed for a user.
    os.remove(os.path.join(wt, demo.DEMO_DIR, "findings.md"))
    play(True, {"title": "T", "scenarios": [
        {"title": "Try", "steps": [{"text": "the badge", "ok": False, "error": "not seen"}]}]})
    code, lines = said(demo.cmd_keep, [], "f1", wt)
    check("keep: a reason is required", code != 0, True)
    code, lines = said(demo.cmd_keep, ["a refactoring nobody sees"], "f1", wt)
    entry = demo.history(wt)[-1]
    check("keep: the last full demo carried on to the code as it is",
          (entry["id"], entry["kept"], entry["head"], entry["stage"]),
          (last, "a refactoring nobody sees", demo.git_head(wt), "epilogue"))
    check("keep: stale is fresh again, and nothing went out", (stale(), notified()),
          ((1, "fresh"), 3))
    check("kept: what sclaude says instead of 'recorded again'", refresh.kept(wt, before),
          "the demo %s still shows the feature — a refactoring nobody sees" % last)
    check("held: a session that ended on keep publishes nothing, its try neither",
          refresh.held(wt, before), [])
    check("findings: a failed check in a try before keep is still said",
          refresh.findings(wt, os.path.join(wt, demo.DEMO_DIR, "findings.md"), before),
          ["Try: a check failed — the badge (not seen)"])
    with open(os.path.join(wt, demo.DEMO_DIR, "index.html")) as fh:
        page = fh.read()
    check("page: the kept demo is said still current, and listed once",
          ("still current on" in page, "a refactoring nobody sees" in page,
           page.count("href='%s/'" % last)), (True, True, 1))
    check("page: the first demo stays among the earlier ones", "href='%s/'" % first in page, True)
    check("replay: still plays the kept demo's own script",
          os.path.isfile(os.path.join(wt, demo.DEMO_DIR, demo.last_main(wt)["id"], "demo.mjs")), True)

    # demo_refresh starts its session with the feature's environment, as every
    # other session in a tree: a feature with a database of its own (db.env)
    # hands its address to the session, and from it to what the session plays.
    write(os.path.join(wt, "app.ts"), "export const x = 3\n")
    git(wt, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-qam", "change")
    write(os.path.join(wt, ".sclaude", "local", "feature", "db.env"),
          "POSTGRES_URL_NON_POOLING=postgresql://feature-own:1/db\n")
    # demo.py, run from the tree, knows the feature by the registry's link.
    os.makedirs(os.environ["SCLAUDE_DEV_REGISTRY"], exist_ok=True)
    os.symlink(wt, os.path.join(os.environ["SCLAUDE_DEV_REGISTRY"], "f1"))
    seen = os.path.join(root, "claude-saw")
    write(os.path.join(stub, "claude"),
          '#!/bin/sh\nprintf "%%s" "$POSTGRES_URL_NON_POOLING" > %s\n' % seen)
    os.chmod(os.path.join(stub, "claude"), 0o755)
    bash = """
set -u
INSTRUMENTS=%(root)s
LIB=%(lib)s
source %(lib)s/tree/worktree.sh
source %(lib)s/tree/featuredb.sh
source %(lib)s/ship/demo.sh
BOLD=""; OFF=""
info() { :; }
warn() { :; }
say() { :; }
project_demo_mode() { echo on; }
new_session_id() { echo s-refresh; }
step_model() { echo m; }
unset POSTGRES_URL_NON_POOLING
demo_refresh %(wt)s epilogue
""" % {"root": ROOT, "lib": LIB, "wt": wt}
    done = subprocess.run(["bash", "-c", bash], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    got = open(seen).read() if os.path.exists(seen) else "(claude never started: %s)" % done.stderr[-300:]
    check("refresh: the session gets the feature's own database from db.env",
          got, "postgresql://feature-own:1/db")

    # demo.sh: the session plays held, sclaude publishes and says what was found.
    with open(os.path.join(LIB, "ship", "demo.sh")) as fh:
        body = fh.read()
    check("deploy: the refresh session plays with the hold on",
          "SCLAUDE_DEMO_HOLD=1" in body, True)
    check("deploy: what was held is published by demo.py publish, picked by demo_refresh.py held",
          ('"$tool" publish "$id"' in body, "demo_refresh.py\" held" in body), (True, True))
    check("deploy: the session is told of keep and of findings.md",
          ("demo.py keep" in body, "findings.md" in body), (True, True))
    check("deploy: findings.md is the file demo_refresh.py reads",
          '"$wt/.sclaude/local/demo/findings.md"' in body
          and refresh.DEMO_DIR == demo.DEMO_DIR.replace("/", os.sep), True)

os.environ.clear()
os.environ.update(saved_env)

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("demo-refresh: all passed")
