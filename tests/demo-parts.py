#!/usr/bin/env python3
#
# A feature built in parts, shown part by part (demo_part in
# sclaude/lib/ship/demo.sh, called by parts_built in parts.sh):
#
#   * Between two parts a session records what the part added, held, and
#     sclaude publishes it: the history keeps it with its `part`, measured
#     from where the part began (SCLAUDE_DEMO_PART, SCLAUDE_DEMO_BASE), the
#     topic gets it as "🧩 Part N", and `demo.py parts` lists it with its
#     script for the whole feature's demo to start from.
#
#   * No part demo after the last part, with demo: off or with partAccept:
#     each — where the part's own session shows it.
#
#   * The prompts and the map say the same: the next part's session hears
#     that remarks may come, the whole feature's session starts from
#     `demo.py parts`, and the parts map draws the block.
#
# Run it with: python3 tests/demo-parts.py
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


def commit(wt, msg):
    git(wt, "add", "-A")
    git(wt, "-c", "user.email=t@x", "-c", "user.name=t", "commit", "-qm", msg)


saved_env = dict(os.environ)
with tempfile.TemporaryDirectory() as root:
    os.environ["HOME"] = root
    registry = os.path.join(root, "registry")
    os.environ["SCLAUDE_DEV_REGISTRY"] = registry
    demo = load("demo", os.path.join(ROOT, "skills", "sdemo", "demo.py"))

    wt = os.path.join(root, "wt")
    os.makedirs(wt)
    git(wt, "init", "-q", "-b", "feat")
    write(os.path.join(wt, ".gitignore"), ".sclaude/\n")
    write(os.path.join(wt, "app.ts"), "export const x = 1\n")
    commit(wt, "init")
    git(wt, "checkout", "-q", "-b", "feat-1")
    write(os.path.join(wt, "app.ts"), "export const x = 2\n")
    commit(wt, "part one: the list")
    write(os.path.join(wt, ".sclaude", "local", "feature", "state.json"), json.dumps({
        "feature": "f1", "step": "code", "dev": {"label": "f1"},
        "parts": {"total": 3, "current": 1, "umbrella": "feat", "1": {"title": "The list"}}}))
    os.makedirs(registry)
    os.symlink(wt, os.path.join(registry, "f1"))

    # Stand-ins: node plays a script by writing the page and the results it
    # is given; sclaude-notify writes down what it was asked; claude, the
    # session, writes down what it was handed and plays one delta.
    stub = os.path.join(root, "bin")
    asked = os.path.join(root, "asked")
    seen = os.path.join(root, "claude-saw")
    script = os.path.join(root, "demo.mjs")
    write(script, "export default {scenarios: []}")
    write(os.path.join(stub, "node"),
          '#!/bin/sh\necho \'progress: {"kind": "delta", "scenario": 1, "of": 1, "title": "The list"}\'\n'
          'sleep 2\n'
          'while [ $# -gt 0 ]; do [ "$1" = --out ] && echo x > "$2/index.html" && '
          'echo \'{"title": "T", "kind": "delta", "change": "A guest sees the list", '
          '"scenarios": [{"title": "The list", "steps": []}]}\' > "$2/demo.json"; shift; done\n')
    write(os.path.join(stub, "sclaude-notify"),
          '#!/bin/sh\necho "notify $*" >> %s\necho "sent: 101"\n' % asked)
    write(os.path.join(stub, "claude"),
          '#!/bin/sh\nprintf "%%s|%%s|%%s|%%s\\n" "$SCLAUDE_DEMO_PART" "$SCLAUDE_DEMO_BASE" '
          '"$SCLAUDE_DEMO_STAGE" "$SCLAUDE_DEMO_HOLD" >> %s\n'
          'python3 %s play %s >/dev/null 2>&1\n'
          % (seen, os.path.join(ROOT, "skills", "sdemo", "demo.py"), script))
    for name in ("node", "sclaude-notify", "claude"):
        os.chmod(os.path.join(stub, name), 0o755)
    os.environ["PATH"] = stub + os.pathsep + saved_env.get("PATH", "")

    def run(n, demo_mode="on", accept="whole", path=None):
        bash = """
set -u
INSTRUMENTS=%(root)s
LIB=%(lib)s
PROXY_PORT=7000
source %(lib)s/ship/demo.sh
BOLD=""; OFF=""
info() { echo "$*"; }
warn() { echo "$*"; }
say() { echo "$*"; }
project_demo_mode() { echo %(demo)s; }
project_part_accept() { echo %(accept)s; }
parts_last() { echo 3; }
parts_below() { echo feat; }
state_get() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."): d=(d or {}).get(k) if isinstance(d, dict) else None
print(d if d is not None else "")' "$1" "$2"; }
history_add() { echo "history $*" >> %(rootdir)s/history; }
session_runs() { :; }
session_started() { return 0; }
new_session_id() { echo s-part; }
step_model() { echo m; }
dev_env_load() { :; }
cd %(wt)s
demo_part %(wt)s %(n)s
""" % {"root": ROOT, "lib": LIB, "wt": wt, "n": n, "demo": demo_mode, "accept": accept,
       "rootdir": root}
        return subprocess.run(["bash", "-c", bash], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL,
                              env=dict(os.environ, SCLAUDE_SESSION="s1", PATH=path or os.environ["PATH"]))

    def notified():
        if not os.path.exists(asked):
            return []
        with open(asked) as fh:
            return [line for line in fh if line.startswith("notify")]

    base = git(wt, "rev-parse", "feat")
    done = run(1)
    with open(seen) if os.path.exists(seen) else io.StringIO("") as fh:
        handed = fh.read().splitlines()
    check("session: handed the part, where it began, its stage and the hold",
          handed, ["1|%s|part 1|1" % base])
    entries = demo.history(wt)
    check("history: one recording, a delta of part 1, published",
          [(e.get("kind"), e.get("part"), e.get("from"), e.get("stage"), e.get("held")) for e in entries],
          [("delta", 1, "main", "part 1", None)])
    check("history: its commits are the part's own",
          [c.split(" ", 1)[1] for c in entries[0].get("commits") or []], ["part one: the list"])
    check("topic: sent once, headed as the part's",
          [("🧩 Part 1: A guest sees the list" in line) for line in notified()], [True])
    check("terminal: the recording's progress is said, as the part's",
          "Recorded part 1: 1 scenario" in done.stdout, True)
    check("terminal: says the demo is ready, where, and where remarks go",
          ("Part 1's demo is ready" in done.stdout,
           "http://f1.localhost:7000/__sclaude/demo/f1/" in done.stdout,
           "part 2's session" in done.stdout), (True, True, True))
    with open(os.path.join(root, "history")) as fh:
        check("history row: parts demo, part 1, recorded", fh.read().split(),
              ["history", os.path.join(wt, ".sclaude/local/feature/state.json"),
               "parts", "demo", "part=1", "recorded=yes"])
    check("stale: a part's demo is no full demo to measure from", demo.last_main(wt), None)

    code, lines = said(demo.cmd_parts, "f1", wt)
    check("parts: each part's recording and its script",
          lines, ["part 1: %s on %s — A guest sees the list" % (entries[0]["id"], entries[0]["head"][:7]),
                  "script: " + os.path.join(wt, demo.DEMO_DIR, entries[0]["id"], "demo.mjs")])
    check("parts: the script is there to start from",
          os.path.isfile(os.path.join(wt, demo.DEMO_DIR, entries[0]["id"], "demo.mjs")), True)

    # None after the last part, with demo off, or with a look at each part.
    for name, args in (("the last part", (3,)), ("demo: off", (2, "off")),
                       ("partAccept: each", (2, "on", "each"))):
        run(*args)
        check("no part demo: " + name, (len(demo.history(wt)), len(notified())), (1, 1))

    # Without claude, nothing is recorded and the next part goes on.
    # Telegram refuses: the page has it, and the terminal does not say the
    # topic does.
    write(os.path.join(stub, "sclaude-notify"),
          '#!/bin/sh\necho "notify $*" >> %s\necho "the videos did not go; the text did" >&2\n'
          'echo "bot refused" >&2\nexit 0\n' % asked)
    done = run(2)
    check("telegram refused: said, and not claimed sent",
          ("did not reach the feature's Telegram topic: the videos did not go; the text did; bot refused"
           in done.stdout,
           "in the feature's Telegram topic, and here" in done.stdout), (True, False))
    entries = demo.history(wt)
    check("telegram refused: the recording is still published on the page",
          (entries[-1].get("part"), entries[-1].get("held")), (2, None))

    # No bot on this machine: sclaude-notify exits 0 and says nothing.
    write(os.path.join(stub, "sclaude-notify"), '#!/bin/sh\necho "notify $*" >> %s\n' % asked)
    done = run(2)
    check("no bot: not claimed sent, and why",
          ("no bot set up here?" in done.stdout,
           "in the feature's Telegram topic, and here" in done.stdout), (True, False))

    # A part's session that played a full script: still the part's delta,
    # never the feature's full demo.
    os.environ["SCLAUDE_DEMO_PART"] = "3"
    entry = demo.remember(wt, "x-main", {"title": "T", "kind": "main", "scenarios": []})
    os.environ.pop("SCLAUDE_DEMO_PART")
    check("a full script in a part's session: kept as the part's delta",
          (entry["kind"], entry["part"], demo.last_main(wt)), ("delta", 3, None))

    os.remove(os.path.join(stub, "claude"))
    bare = os.pathsep.join([stub] + [d for d in os.environ["PATH"].split(os.pathsep)[1:]
                                     if not os.path.exists(os.path.join(d, "claude"))])
    done = run(2, path=bare)
    check("no claude: said, nothing recorded",
          ("No demo of part 2" in done.stdout, len(demo.history(wt)), done.returncode), (True, 4, 0))

    with tempfile.TemporaryDirectory() as empty:
        os.makedirs(os.path.join(empty, demo.DEMO_DIR))
        code, lines = said(demo.cmd_parts, "f2", empty)
        check("parts: none recorded", (lines[0].startswith("none:"), code), (True, 0))

os.environ.clear()
os.environ.update(saved_env)

# The prompts and the map.
with open(os.path.join(ROOT, "sclaude", "prompts", "code.md")) as fh:
    code_md = fh.read()
alone = code_md[code_md.index("<if:part-alone>"):code_md.index("</if:part-alone>")]
check("code.md: a part's session hears remarks on an earlier part may come",
      "I see each part as soon as it is built" in alone, True)
whole = code_md[code_md.index("<if:parts-built>"):code_md.index("</if:parts-built>")]
check("code.md: the whole feature's demo starts from demo.py parts",
      "<if:demo>" in whole and "demo.py parts" in whole, True)
with open(os.path.join(ROOT, "skills", "sdemo", "SKILL.md")) as fh:
    check("SKILL.md: names demo.py parts", "demo.py parts" in fh.read(), True)
sys.path.insert(0, os.path.join(LIB, "flow"))
import process_model  # noqa: E402
check("map: the part's demo is told in the gate before the next part, as the other demos are",
      ("demo" in process_model.PARTS_NODES["p_built"][4],
       "sdemo" in process_model.DETAILS["p_built"]), (True, True))

# The next part is the state's before the demo records: a recording cut off
# leaves the next part to start, not this one to be built again.
with open(os.path.join(LIB, "tree", "parts.sh")) as fh:
    body = fh.read()
built = body[body.index("parts_built() {"):]
check("parts_built: parts.current moves on before demo_part",
      built.index("parts.current $((n + 1))") < built.index('demo_part "$wt" "$n"'), True)
with open(os.path.join(LIB, "ship", "demo.sh")) as fh:
    check("demo_part: its run is named as part n's, not the state's next part",
          'SCLAUDE_ABOUT_PART="$n"' in fh.read(), True)

# session_runs names the run as part n's and keeps what it is about, though
# the state is at the next part.
with tempfile.TemporaryDirectory() as tmp:
    st = os.path.join(tmp, "state.json")
    write(st, json.dumps({"parts": {"total": 3, "current": 2}}))
    subprocess.run(["bash", "-c", 'LIB=%s; source %s/core/state.sh; session_runs "$1" demo open s1' % (LIB, LIB),
                    "-", st], env=dict(os.environ, SCLAUDE_ABOUT="part 1", SCLAUDE_ABOUT_PART="1"), check=True)
    run1 = json.load(open(st))["demo"]["runs"][0]
    check("session_runs: a part's demo run is part 1's, about part 1",
          (run1.get("part"), run1.get("about")), ("1", "part 1"))

# A part's demo session is named as such in the issue and on the map.
sys.path.insert(0, os.path.join(LIB, "flow"))
import process_history  # noqa: E402
names = process_history._session_names({"demo": {"runs": [
    {"session": "a", "about": "part 1", "part": "1"}, {"session": "b", "about": "preview"}]}})
check("map: a part's demo session is named by its part, a refresh as a refresh",
      (names.get("a"), names.get("b")), ("part demo · part 1", "demo refresh"))

# The progress of a part's recording is said as that part's.
progress = load("demo_progress", os.path.join(LIB, "ship", "demo_progress.py"))
os.environ["SCLAUDE_DEMO_PART"] = "2"
check("progress: a part's delta is named by its part",
      (progress.kind_name("delta"), progress.kind_name("main")), ("part 2", "the whole feature"))
os.environ.pop("SCLAUDE_DEMO_PART")
check("progress: any other delta stays the delta", progress.kind_name("delta"), "the delta")

if failures:
    for name, want, got in failures:
        print("FAIL %s\n  want: %r\n  got:  %r" % (name, want, got))
    sys.exit(1)
print("demo-parts: all passed")
