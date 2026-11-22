#!/usr/bin/env python3
"""A demo played again for the scenarios that failed (demo.py play --only):

  - play.mjs takes every scenario not listed from the earlier recording
    (--keep-from) when it is the same scenario still: its files copied, its
    record kept; with nothing left to play it records nothing, and says so;
  - a scenario whose script changed, or that did not play there, is not
    taken: it plays again (here, with no browser, the player fails — which
    is what shows it tried);
  - demo.py picks the scenarios that failed, and refuses to keep anything
    once the code changed since the last recording.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAY = os.path.join(ROOT, "skills", "sdemo", "play.mjs")
sys.path.insert(0, os.path.join(ROOT, "skills", "sdemo"))
failures = []


def check(name, got, want):
    if got != want:
        failures.append(name)
        print("FAIL %s\n  got:  %r\n  want: %r" % (name, got, want))
    else:
        print("ok   %s" % name)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


SCRIPT = """export default { title: "T", kind: "delta", change: "c", scenarios: [
  { title: "One", as: "a@x", path: "/a", async steps(d) { await d.say("one"); } },
  { title: "Two", as: "b@x", path: "/b", async steps(d) { await d.say(%s); } },
] };
"""

# The sig play.mjs gives a scenario, from play.mjs itself.
SIG = """
import { createHash } from "node:crypto";
const demo = (await import(process.argv[1])).default;
const VIEWPORTS = { desktop: {}, phone: {} };
%s
console.log(JSON.stringify(demo.scenarios.map((s) => sig(s, demo))));
"""


def sigs(script):
    src = open(PLAY).read()
    start = src.index("function sig(s, demo)")
    body = src[start:src.index("\n}\n", start) + 3]
    vp = src.index("const viewportOf")
    zone = src.index("const zoneOf")
    hand = src.index("function byHandOf(s)")
    body = (src[vp:src.index(";\n", vp) + 2] + src[zone:src.index(";\n", zone) + 2]
            + src[hand:src.index("\n}\n", hand) + 3] + body)
    done = subprocess.run(["node", "--input-type=module", "-e", SIG % body, script],
                          capture_output=True, text=True)
    return json.loads(done.stdout)


if not shutil.which("node"):
    print("skip: no node")
    sys.exit(0)

tmp = tempfile.mkdtemp()
try:
    script = os.path.join(tmp, "demo.mjs")
    write(script, SCRIPT % '"two"')
    one, two = sigs(script)
    # A browser zone set later changes the scenario's signature, so the
    # earlier recording in the machine's zone is not kept; none set keeps it.
    zoned = os.path.join(tmp, "zoned.mjs")
    write(zoned, SCRIPT.replace('title: "T",', 'title: "T", timezone: "Asia/Tokyo",') % '"two"')
    check("a browser zone set changes every scenario's signature", sigs(zoned) != [one, two], True)
    before = os.path.join(tmp, "before")
    rec = lambda title, sig, n, **more: dict(  # noqa: E731
        title=title, as_="x", sig=sig, steps=[{"kind": "say", "text": title, "t": 1}],
        sources=[{"src": "scenario-%d.mp4" % n, "type": "video/mp4"}],
        captions="scenario-%d.vtt" % n, **more)
    write(os.path.join(before, "demo.json"), json.dumps({"scenarios": [
        rec("One", one, 1), rec("Two", two, 2)]}))
    for n in (1, 2):
        write(os.path.join(before, "scenario-%d.mp4" % n), "video %d" % n)
        write(os.path.join(before, "scenario-%d.vtt" % n), "WEBVTT\n")
    # Scenario two kept a file for the person's own try: taken with it.
    meta = json.load(open(os.path.join(before, "demo.json")))
    meta["scenarios"][1]["files"] = [{"src": "file-2-1-event.ics", "name": "event.ics", "label": ""}]
    write(os.path.join(before, "demo.json"), json.dumps(meta))
    write(os.path.join(before, "file-2-1-event.ics"), "BEGIN:VCALENDAR")

    out = os.path.join(tmp, "all-kept")
    done = subprocess.run(["node", PLAY, script, "--out", out, "--base", "http://f.localhost:1",
                           "--keep-from", before, "--only", ""],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    check("all unchanged: the files are taken, and with nothing to play no recording is made",
          (done.returncode, "nothing to play again" in done.stderr,
           open(os.path.join(out, "scenario-2.mp4")).read(),
           os.path.isfile(os.path.join(out, "index.html"))),
          (2, True, "video 2", False))
    check("a kept scenario's file for the person is taken with it",
          open(os.path.join(out, "file-2-1-event.ics")).read(), "BEGIN:VCALENDAR")
    # What the person is to try by hand is the scenario's too: changed, it plays again.
    hand = os.path.join(tmp, "hand.mjs")
    write(hand, SCRIPT.replace('path: "/a",', 'path: "/a", byHand: { steps: ["open it"] },') % '"two"')
    write(script, SCRIPT.replace('path: "/a",', 'path: "/a", byHand: { steps: ["open it", {do: "x"}] },') % '"two"')
    check("byHand is part of what makes a scenario the same one",
          (sigs(hand)[0] != sigs(script)[0], sigs(hand)[1] == two), (True, True))
    write(script, SCRIPT % '"two"')
    done = subprocess.run(["node", PLAY, script, "--out", os.path.join(tmp, "past"), "--base",
                           "http://f.localhost:1", "--keep-from", before, "--only", "5"],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    check("a number past the script's scenarios is refused",
          (done.returncode, "no 5" in done.stderr), (2, True))

    # Scenario two listed again, and scenario one changed in the script:
    # neither is kept, so the player reaches for a browser.
    write(script, SCRIPT.replace('d.say("one")', 'd.say("one, said otherwise")') % '"two"')
    out = os.path.join(tmp, "none-kept")
    env = dict(os.environ, PATH=os.path.dirname(shutil.which("node")))  # no npm: no playwright
    done = subprocess.run(["node", PLAY, script, "--out", out, "--base", "http://f.localhost:1",
                           "--keep-from", before, "--only", "2"],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, env=env)
    check("a changed scenario plays again and says why",
          "scenario 1: plays again — it changed since" in done.stdout, True)
    check("a listed scenario is not taken", os.path.exists(os.path.join(out, "scenario-2.mp4")), False)

    # demo.py: what failed in a recording.
    import demo
    check("failed: an error, a skip, a check not seen, a step that failed",
          demo.failed_scenarios({"scenarios": [
              {"steps": []}, {"error": "x", "steps": []}, {"skipped": True},
              {"steps": [{"ok": True}, {"ok": False}]}, {"steps": [{"error": "y"}]}]}),
          [2, 3, 4, 5])

    # demo.py: the last recording's code must be the code now.
    wt = os.path.join(tmp, "wt")
    os.makedirs(wt)
    subprocess.run(["git", "init", "-q", wt], check=True)
    write(os.path.join(wt, "a.txt"), "a")
    subprocess.run(["git", "-C", wt, "add", "."], check=True)
    subprocess.run(["git", "-C", wt, "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "a"], check=True)
    write(os.path.join(wt, demo.DEMO_DIR, "d1", "demo.json"), json.dumps({"script": "/s/delta.mjs",
          "scenarios": [{"steps": []}, {"error": "x", "steps": []}]}))
    # A full demo recorded after the delta: not the one a retry of the delta reads.
    write(os.path.join(wt, demo.DEMO_DIR, "d2", "demo.json"), json.dumps({"script": "/s/main.mjs",
          "scenarios": [{"steps": []}]}))
    tree = demo.git_tree(wt)
    write(os.path.join(wt, demo.DEMO_DIR, "history.json"),
          json.dumps([{"id": "d1", "tree": tree}, {"id": "d2", "tree": tree}]))
    check("again_from: the failed ones of the last recording of the same script",
          demo.again_from(wt, "failed", "/s/delta.mjs"), (os.path.join(wt, demo.DEMO_DIR, "d1"), [2]))
    check("again_from: numbers given", demo.again_from(wt, "3,1", "/s/delta.mjs")[1], [1, 3])
    write(os.path.join(wt, "a.txt"), "changed")
    err = io.StringIO()
    with contextlib.redirect_stdout(err):
        try:
            demo.again_from(wt, "failed", "/s/delta.mjs")
            stopped = False
        except SystemExit:
            stopped = True
    check("again_from: refused once the code changed", (stopped, "code changed" in err.getvalue()),
          (True, True))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if failures else 0)
