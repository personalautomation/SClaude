#!/usr/bin/env python3
#
# The process map (sclaude/lib/process.py) against the code it describes:
#
#   * every command sclaude dispatches is in COMMANDS, and every one there is
#     dispatched; every verb of the action list (actions.sh) has its command;
#   * the numbered steps on the map are STEPS and cycle_number's;
#   * every edge, position and command names a node that exists, and no two
#     nodes of a map stand in one place;
#   * `position` answers what a feature's state says, and only with places
#     the page can light;
#   * docs/presentations/bpmn_diagrams.html is what the model draws now;
#   * `_flow` is a report (no update, no channel), and the proxy serves the map.
#
# Run it with: python3 tests/process.py
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "sclaude", "lib")
sys.path.insert(0, LIB)
import process  # noqa: E402

failed = 0


def check(name, ok, detail=""):
    global failed
    if not ok:
        failed += 1
        print("FAIL %s%s" % (name, (": " + detail) if detail else ""))


def read(*path):
    with open(os.path.join(ROOT, *path)) as fh:
        return fh.read()


# --- commands ----------------------------------------------------------------

sclaude = read("bin", "sclaude")
main = sclaude[sclaude.index("main() {"):]
dispatch = main[main.index('case "${1:-}" in'):]
dispatch = dispatch[:dispatch.index("\n  esac")]
words = set(re.findall(r"^\s{4}([a-z][a-z-]*)\)", dispatch, re.M))
words |= {w for alt in re.findall(r"^\s{4}([a-z|-]+)\)", dispatch, re.M) for w in alt.split("|")}
words = {w for w in words if not w.startswith("-")} - {"help", "ls"}
model = {cmd.split()[1] for cmd, *_ in process.COMMANDS if len(cmd.split()) > 1
         and not cmd.split()[1].startswith("<")}
check("every dispatched command is on the map", not (words - model), str(sorted(words - model)))
check("every command on the map is dispatched", not (model - words), str(sorted(model - words)))

actions = read("sclaude", "lib", "actions.sh")
verbs = set(re.findall(r"verbs\+=\(([a-z-]+)\)", actions))
mapped = {verb for _c, verb, *_ in process.COMMANDS if verb} | process.ACTION_ONLY
check("every action has its command", not (verbs - mapped), str(sorted(verbs - mapped)))
check("every command's verb is an action", not (mapped - verbs - process.ACTION_ONLY),
      str(sorted(mapped - verbs - process.ACTION_ONLY)))

# --- steps -------------------------------------------------------------------

steps_sh = read("sclaude", "lib", "steps.sh")
steps = re.search(r"^STEPS=\(([^)]*)\)", steps_sh, re.M).group(1).split()
numbered = dict(enumerate(steps, start=1))
script = 'source "%s/steps.sh"; for k in sync epilogue retro; do echo "$k $(cycle_number $k)"; done' % LIB
out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30).stdout
for line in out.split("\n"):
    if line:
        kind, number = line.split()
        numbered[int(number)] = kind
for number, kind in numbered.items():
    title = "%d · %s" % (number, kind)
    check("step %s on the map" % title, any(n[3] == title for n in process.NODES.values()))
    check("step %s in the overview" % title,
          any(n[3] == title for n in process.OVERVIEW_NODES.values()))
check("seven steps", len(numbered) == 7, str(numbered))

# --- how each session runs ---------------------------------------------------

spec = dict(re.findall(r'^\s+\[(\w+)\]="([^"|]*)', steps_sh, re.M))
for step in steps:
    words = tuple(spec.get(step, "").split()[:3])
    check("%s runs as STEP_SPEC says" % step, process.SPEC.get(step) == words,
          "%s vs %s" % (process.SPEC.get(step), words))
check("a local fix runs as step 2", process.SPEC["fix_local"] == process.SPEC["code"])
for fix in ("fix_preview", "fix_prod"):
    check("%s runs as step 4" % fix, process.SPEC[fix] == process.SPEC["review"])
sync_sh = read("sclaude", "lib", "sync.sh")
sync = (re.search(r'^SYNC_MODEL="(\w+)"', sync_sh, re.M).group(1),
        re.search(r'^SYNC_EFFORT="(\w+)"', sync_sh, re.M).group(1), process.SPEC["review"][2])
check("the sync runs as SYNC_MODEL says", process.SPEC["sync"] == sync, str(sync))
model, effort, mode = process.SPEC["epilogue"]
check("the epilogue runs as github.sh launches it",
      "--model %s --effort %s" % (model, effort) in read("sclaude", "lib", "github.sh"))
model, effort, mode = process.SPEC["retro"]
retro_sh = read("sclaude", "lib", "retro.sh")
check("the retro runs as retro.sh launches it",
      "--model %s --effort %s" % (model, effort) in retro_sh and "--permission-mode %s" % mode in retro_sh)
check("every block says what it does", not (set(process.NODES) - set(process.DETAILS)),
      str(sorted(set(process.NODES) - set(process.DETAILS))))
check("every detail is a block's", not (set(process.DETAILS) - set(process.all_nodes())))
for name, nodes in (("workshop", process.WORKSHOP_NODES), ("friction", process.FRICTION_NODES)):
    check("every %s block says what it does" % name, not (set(nodes) - set(process.DETAILS)),
          str(sorted(set(nodes) - set(process.DETAILS))))
classify = read("sclaude", "lib", "friction_classify.py")
check("the matching runs as friction_classify.py says",
      '"SCLAUDE_CLASSIFY_MODEL", "%s"' % process.SPEC["f_classify"][0] in classify)
deferred = read("sclaude", "lib", "deferred.sh")
model, effort, mode = process.SPEC["f_monthly"]
check("the monthly review runs as deferred.sh launches it",
      "--model %s --effort %s" % (model, effort) in deferred and "--permission-mode %s" % mode in deferred)
model, effort, mode = process.SPEC["f_review"]
check("the friction review runs as run_friction launches it",
      re.search(r"run_friction\(\) \{.*?--model %s --effort %s.*?--permission-mode %s" % (model, effort, mode),
                read("sclaude", "lib", "run.sh"), re.S) is not None)
others = set(process.OVERVIEW_NODES) | set(process.STATE_NODES)
check("every overview and state block borrows a detail",
      not (others - set(process.ALIAS)) and all(v in process.DETAILS for v in process.ALIAS.values()),
      str(sorted(others - set(process.ALIAS))))
check("no model on a block", not any(re.search(r"\b(opus|sonnet|haiku)\b", n[4])
                                      for n in process.NODES.values()))

# --- the drawing -------------------------------------------------------------

for name, lanes, nodes, edges in process.node_sets():
    lane_names = {lane for lane, _ in lanes}
    seen = {}
    for nid, node in nodes.items():
        check("%s: %s in a known lane" % (name, nid), node[0] in lane_names)
        place = node[:2]
        check("%s: %s alone in its place" % (name, nid), place not in seen, str(seen.get(place)))
        seen[place] = nid
    for a, b, _label, _kind in edges:
        check("%s: edge %s → %s" % (name, a, b), a in nodes and b in nodes)
    svg = process.Diagram(name, lanes, nodes, edges).svg()
    check("%s draws every node" % name, svg.count('class="node ') == len(nodes))

for pos, (over, state) in process.POSITIONS.items():
    check("position %s on the map" % pos, pos in process.NODES)
    check("position %s in the overview" % pos, over in process.OVERVIEW_NODES)
    check("position %s among the states" % pos, state in process.STATE_NODES)
for cmd, _verb, _when, _what, target in process.COMMANDS:
    check("%s leads somewhere real" % cmd,
          all(t == "@here" or t in process.all_nodes() for t in process.places(target)))
drop = next(c for c in process.COMMANDS if c[1] == "drop")
check("drop ends at the clean-up and done", process.places(drop[4]) == ["cleanup", "end"])
model = process.client_model()
check("a place is lit on every map that has it",
      set(model["alias"].get("cleanup", [])) == {"o_end"} and set(model["alias"].get("end", [])) == {"s_done"})

# --- where a feature stands --------------------------------------------------

now = datetime.datetime.now(datetime.timezone.utc).isoformat()
cases = [
    ("a step", {"step": "code"}, "", "code"),
    ("a local run", {"step": "code", "regression": {"local": {"status": "running", "started": now}}},
     "", "reg_local"),
    ("a local fix", {"step": "code", "regression": {"local": {"fix_status": "red open"}}}, "", "fix_local"),
    ("a preview fix", {"step": "review", "regression": {"preview": {"fix_status": "open"}}}, "", "fix_preview"),
    ("an old run", {"step": "review", "regression": {"local": {"status": "running",
                                                               "started": "2020-01-01T00:00:00+00:00"}}},
     "", "review"),
    ("a sync", {"step": "done", "sync": {"runs": [{"session": "s"}]}}, "OPEN", "sync"),
    ("with QA", {"step": "done", "qa": {"sha": "abc"}}, "OPEN", "qa_check"),
    ("accepted", {"step": "done", "qa": {"sha": "abc", "accepted": "abc"}}, "OPEN", "merge_wait"),
    ("handed over", {"step": "done", "handoff": "abc"}, "OPEN", "merge_wait"),
    ("no preview yet", {"step": "done"}, "OPEN", "preview"),
    ("held", {"step": "done", "deploy": {"prod": {"sha": "x"}},
              "regression": {"prod": {"status": "failed"}}}, "MERGED", "hold_ways"),
    ("a fix's own PR is not held", {"step": "done", "deploy": {"prod": {"sha": "x"}},
                                    "regression": {"prod": {"status": "failed"}}}, "OPEN", "preview"),
    ("rolled back", {"step": "done", "deploy": {"prod": {"sha": "x"}}, "rollback": {"prod": {"code": "done"}},
                     "regression": {"prod": {"status": "failed"}}}, "MERGED", "done_cmd"),
    ("merged", {"step": "done"}, "MERGED", "done_cmd"),
    ("retro ran", {"step": "done", "retro": {"runs": [{"done": True}]}}, "MERGED", "end"),
    ("no change", {"step": "done", "no_change": True}, "", "cleanup"),
    ("closed", {"step": "done"}, "CLOSED", "cleanup"),
    ("no answer", {"step": "done"}, "", "preview"),
]
for name, state, pr, want in cases:
    got, _why = process.position(state, pr)
    check("position: %s" % name, got == want, "want %s, got %s" % (want, got))
    check("position: %s can be lit" % name, got in process.POSITIONS, got)
got, _ = process.position({"step": "done"}, "MERGED", {"session": "e", "done": False})
check("position: an epilogue broken off", got == "epilogue", got)

# The command line answers the same, tab-separated, for cmd_flow.
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "state.json")
    with open(path, "w") as fh:
        json.dump({"step": "done"}, fh)
    out = subprocess.run([sys.executable, os.path.join(LIB, "process.py"), "position", path, "OPEN"],
                         capture_output=True, text=True, timeout=30).stdout
check("position from the command line", out.split("\t")[0] == "preview", out)

# --- the printed map ---------------------------------------------------------

committed = read("docs", "presentations", "bpmn_diagrams.html")
check("bpmn_diagrams.html is current (python3 docs/presentations/build.py)",
      committed == process.doc())
doc = process.doc()
check("the doc has the detailed map as print sheets", 'id="sheets" class="print-only"' in doc
      and doc.count('class="sheet"') > 1)
check("the doc lets the paper be chosen", 'id="paper"' in doc and "cutSheets" in doc)
for n, title in enumerate(process.SECTIONS, start=1):
    shown = process.esc(title)
    check("section %d is a page of its own, its header and its heading one title" % n,
          ('<section style="page:s%d">' % n) in doc
          and ('@page s%d{@top-left{content:"%s"' % (n, title)) in doc
          and re.search(r'<h2[^>]*>%s[ <]' % re.escape(shown), doc) is not None)
check("a header's title prints as written, not as an escape",
      "\\u" not in process.running_heads())
for cmd, _verb, when, _what, _target in process.COMMANDS:
    check("%s: its When names where it is open" % cmd, when in process.WHEN, when)
for when, at in process.WHEN.items():
    check("%s: open only on real places" % when, all(n in process.NODES for n in at), str(at))
model = process.client_model()
check("every edge can be pointed at", all(("e:%s" % k) in doc for k in model["edges"]))
placed = [i for i, c in enumerate(process.COMMANDS) if c[4]]
check("the commands with a place are pinned beside the maps", 'id="dock"' in doc and "pin-head" in doc
      and all(('<li data-key="c:%d">' % i) in doc for i in placed))
check("the commands with no place are not pinned",
      not any(('<li data-key="c:%d">' % i) in doc for i in range(len(process.COMMANDS)) if i not in placed))
check("a pinned command is named alone", process.short_command("sclaude regression <name> prod")
      == "regression prod" and process.short_command("sclaude <name>") == "continue")
check("every command row can be pointed at", all(('data-key="c:%d"' % i) in doc
                                                  for i in range(len(process.COMMANDS))))
check("the doc lists the commands", "sclaude return &lt;name&gt; [reason]" in doc)

# --- a feature's page, and the way to it -------------------------------------

page = process.page("x<y")
check("page escapes the label", "x&lt;y" in page and "x<y</h1>" not in page)
check("page asks for its state", "/__sclaude/flow/state?f=" in page)
known = subprocess.run(["bash", "-c", 'source "%s/branches.sh"; gh() { echo ASKED; }; '
                        'PR_STATE_KNOWN=1 PR_STATE=MERGED branch_pr_state feat/x' % LIB],
                       capture_output=True, text=True, timeout=30).stdout.strip()
check("a pull request's state cmd_flow knows is not asked again", known == "MERGED", known)
check("cmd_flow hands it down", "local PR_STATE_KNOWN=1 PR_STATE=\"$pr_state\"" in read("sclaude", "lib", "actions.sh"))
check("_flow is a report", re.search(r"status\|ls\|dev\|[^\n]*\|_flow\|", sclaude) is not None)
check("_flow is dispatched", "_flow)" in dispatch and "cmd_flow" in dispatch)
proxy = read("bin", "sclaude-proxy")
check("the proxy serves the map", '"/__sclaude/flow"' in proxy and "process_map().page(label)" in proxy)
check("the proxy runs _flow", '"_flow"' in proxy)
check("the proxy lists the map", "/__sclaude/flow?f=" in proxy and 'MAP_NAME = "Process map (BPMN)"' in proxy)
check("the proxy serves the whole map for main", '"/__sclaude/bpmn"' in proxy and "process_map().doc()" in proxy)
check("the proxy opens code-server on a feature's tree, starting its service",
      'CODE_LOCAL = "http://127.0.0.1:8080"' in proxy and '"/__sclaude/code"' in proxy
      and '"folder": found[0]' in proxy and '"start", CODE_SERVICE' in proxy and "— Code Server" in proxy)
check("another site's page cannot start code-server", 'if cross_site("GET", headers or {}):' in proxy)
check("code-server's local entry is the socket that starts it",
      "ListenStream=127.0.0.1:8080" in read("systemd", "code-server-local.socket"))
check("the gate frames the map", "path.startswith(FLOW_PREFIX)" in proxy
      and 'FLOW_PREFIX = "/__sclaude/flow?f="' in proxy)
check("the Mini App opens it at the same path, starting the server",
      '"/__sclaude/flow?f=%s&start=1" % dev[0]' in read("keepawake", "telegramd.py"))
check("the proxy starts the server for start=1", 'get("start")' in proxy)
check("the map's button starts sclaude dev without holding the bot",
      "setsid nohup sclaude dev --no-browser >/dev/null 2>&1 &" in read("keepawake", "telegramd.py"))
check("the step's header names the map", "flow_address" in read("sclaude", "lib", "run.sh"))

# --- the proxy's runs of `sclaude _flow` -------------------------------------
#
# A run past its limit is ended with everything it started: a hung git or gh
# holding its stdout must not keep the read waiting. And one run at a time per
# feature, whose result is kept even when the request that started it leaves.
import asyncio  # noqa: E402
import time  # noqa: E402
from importlib.machinery import SourceFileLoader  # noqa: E402
from importlib.util import module_from_spec, spec_from_loader  # noqa: E402

loader = SourceFileLoader("sclaude_proxy", os.path.join(ROOT, "bin", "sclaude-proxy"))
proxy_mod = module_from_spec(spec_from_loader("sclaude_proxy", loader))
loader.exec_module(proxy_mod)
# A model changed on disk is what the next page is drawn from.
with tempfile.TemporaryDirectory() as tmp2:
    import shutil  # noqa: E402
    copy = os.path.join(tmp2, "process.py")
    shutil.copy(os.path.join(LIB, "process.py"), copy)
    saved = proxy_mod.process
    sys.path.insert(0, tmp2)  # where reload finds "process" by name
    try:
        spec = __import__("importlib.util").util.spec_from_file_location("process", copy)
        mod = __import__("importlib.util").util.module_from_spec(spec)
        sys.modules["process"] = mod
        spec.loader.exec_module(mod)
        proxy_mod.process = mod
        proxy_mod._PROCESS_SEEN[0] = None
        first = proxy_mod.process_map().doc()
        with open(copy) as fh:
            text = fh.read()
        with open(copy, "w") as fh:
            fh.write(text.replace('"1. The cycle at a glance"', '"1. The cycle, reloaded"'))
        os.utime(copy, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
        second = proxy_mod.process_map().doc()
        check("the proxy draws the map from the model on disk now",
              "1. The cycle, reloaded" in second and "1. The cycle, reloaded" not in first)
    finally:
        sys.path.remove(tmp2)
        proxy_mod.process = saved
        sys.modules["process"] = process
with tempfile.TemporaryDirectory() as tmp:
    hung = os.path.join(tmp, "sclaude")
    with open(hung, "w") as fh:
        # A child that keeps stdout open long after its parent is gone.
        fh.write("#!/bin/sh\nsleep 30 &\nsleep 30\n")
    os.chmod(hung, 0o755)
    proxy_mod.SCLAUDE, proxy_mod.FLOW_LIMIT = hung, 1
    began = time.time()
    body = json.loads(proxy_mod.flow_run(tmp))
    check("a hung _flow is ended whole", time.time() - began < 10 and "error" in body,
          "%.1fs %s" % (time.time() - began, body))

    counter = os.path.join(tmp, "runs")
    slow = os.path.join(tmp, "slow")
    with open(slow, "w") as fh:
        fh.write('#!/bin/sh\necho x >> "%s"\nsleep 1\necho \'{"node": "plan"}\'\n' % counter)
    os.chmod(slow, 0o755)
    proxy_mod.SCLAUDE, proxy_mod.FLOW_LIMIT = slow, 10

    async def two_tabs():
        first = asyncio.ensure_future(proxy_mod.flow_state("x", tmp))
        await asyncio.sleep(0.2)
        first.cancel()  # the tab that asked is closed
        second = await proxy_mod.flow_state("x", tmp)
        third = await proxy_mod.flow_state("x", tmp)  # fresh: from the store
        return second, third

    second, third = asyncio.run(two_tabs())
    with open(counter) as fh:
        runs = len(fh.read().split())
    check("one run of _flow for a closed tab and the next", runs == 1, "%d runs" % runs)
    check("the run's answer is kept", json.loads(second).get("node") == "plan"
          and third == second, "%s / %s" % (second, third))

if failed:
    print("%d check(s) failed" % failed)
    sys.exit(1)
print("process: all checks passed")
