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

# --- how a feature went ------------------------------------------------------

# The writers: session_runs and history_add, beside the state, in the tree.
with tempfile.TemporaryDirectory() as tmp:
    feat = os.path.join(tmp, ".sclaude", "local", "feature")
    os.makedirs(feat)
    st = os.path.join(feat, "state.json")
    with open(st, "w") as fh:
        json.dump({"step": "plan"}, fh)
    subprocess.run(["bash", "-c", 'source "%s/state.sh"; f="$1"; '
                    'session_runs "$f" steps.plan open s1; session_runs "$f" steps.plan end s1; '
                    'session_runs "$f" steps.plan open s1; session_runs "$f" steps.plan finish s1 finished; '
                    'history_add "$f" regression.local failed note=\'say "x"\'; '
                    'history_add "$f/../nowhere/state.json" qa in' % LIB, "_", st],
                   capture_output=True, text=True, timeout=30)
    rows = process.read_history(st)
    check("history is written beside the state, in the tree's .sclaude/local",
          process.HISTORY_FILE == "history.jsonl" and len(rows) == 5, str(rows))
    check("every sitting of a conversation is kept",
          [(r["what"], r["op"]) for r in rows[:4]] == [("steps.plan", "open"), ("steps.plan", "end"),
                                                         ("steps.plan", "open"), ("steps.plan", "finish")])
    check("history_add quotes its values", rows[-1].get("note") == 'say "x"', str(rows[-1]))
    check("no history where there is no feature", not os.path.exists(os.path.join(tmp, ".sclaude", "local", "nowhere")))


def at(hhmm, day=27):
    return "2026-10-%02dT%s:00+00:00" % (day, hhmm)


rows = [
    {"at": at("10:00"), "what": "steps.plan", "op": "open", "session": "p1"},
    {"at": at("10:10"), "what": "steps.plan", "op": "end", "session": "p1"},
    {"at": at("10:11"), "what": "steps.plan", "op": "open", "session": "p2"},
    {"at": at("10:20"), "what": "steps.plan", "op": "finish", "session": "p2"},
    {"at": at("10:21"), "what": "steps.code", "op": "open", "session": "c1"},
    {"at": at("11:00"), "what": "steps.code", "op": "end", "session": "c1"},
    {"at": at("11:30"), "what": "steps.code", "op": "open", "session": "c1"},
    {"at": at("12:00"), "what": "steps.code", "op": "end", "session": "c1"},
    {"at": at("13:00"), "what": "friction.code-1", "op": "open", "session": "f1"},
    {"at": at("13:10"), "what": "friction.code-1", "op": "finish", "session": "f1", "outcome": "fixed"},
    {"at": at("13:10"), "what": "friction.code-1", "op": "verdict", "verdict": "lifted"},
    {"at": at("13:11"), "what": "workshop", "op": "ready", "session": "f1"},
    {"at": at("13:12"), "what": "workshop", "op": "main"},
    {"at": at("14:00"), "what": "regression.local", "op": "start"},
    {"at": at("14:05"), "what": "regression.local", "op": "passed"},
    {"at": at("13:59"), "what": "friction.pr-1", "op": "empty"},
]
got = process.history({}, rows, "pr")
seq = [v.get("n") or tuple(v["pass"]) for v in got["visits"]]
check("history: a place entered again is entered again",
      seq[:9] == ["new", "prepare", "main_in", "plan", "approve", "plan_check", "plan", "approve", "plan_check"], str(seq))
code = [v for v in got["visits"] if v.get("n") == "code"]
check("history: a conversation resumed is one stay, its sittings summed",
      len(code) == 1 and code[0].get("k") == 2 and code[0].get("s") == 69 * 60, str(code))
check("history: the places between are filled in along the map",
      seq[seq.index("code"):seq.index("reg_local") + 1] == ["code", ("friction", 0), ("workshop", 0), "works", "reg_local"], str(seq))
works = [v for v in got["visits"] if v.get("n") == "works"][0]
check("history: the time between goes to who it waited on", works.get("wait") and works.get("s") == 120 * 60, str(works))
check("history: it ends where the feature stands", got["visits"][-1] == {"n": "pr", "here": True}, str(got["visits"][-1]))
fr = got["passes"]["friction"]
check("history: an empty friction log is no pass", len(fr) == 1 and "code-1" in fr[0]["label"], str(fr))
check("history: a review that fixed sclaude in the workshop goes by its bug",
      [s["n"] for s in fr[0]["steps"]][-4:] == ["f_bug", "f_verdict", "f_push", "f_next"], str(fr[0]["steps"]))
ws = got["passes"]["workshop"]
check("history: a publication without its session is the last pass's",
      len(ws) == 1 and ws[0]["steps"][-1]["n"] == "w_main", str(ws))
nodes = process.all_nodes()
check("history: every place it plays is on a map",
      all(s["n"] in nodes for p in fr + ws for s in p["steps"])
      and all(v["n"] in process.NODES for v in got["visits"] if "n" in v))
check("history: every detailed place a feature stands on is on the overview and the states",
      all(process.projection()[n][0] in process.OVERVIEW_NODES and process.projection()[n][1] in process.STATE_NODES
          for n in process.POSITIONS))
check("history: nothing recorded plays where it stands", process.history({}, [], "plan")["visits"] == [{"n": "plan", "here": True}])
def seq_of(rows, here=None):
    return [v.get("n") or tuple(v["pass"]) for v in process.history({}, rows, here)["visits"]]


got = seq_of([{"at": at("09:00"), "what": "steps.plan", "op": "open", "session": "a"},
              {"at": at("12:00"), "what": "steps.plan", "op": "drop", "session": "a"},
              {"at": at("12:00"), "what": "steps.plan", "op": "open", "session": "b"},
              {"at": at("12:30"), "what": "steps.plan", "op": "end", "session": "b"}])
check("history: a conversation that never took place is no stay", got.count("plan") == 1, str(got))
local = process.history({}, [{"at": at("09:00"), "what": "review.local", "op": "start"},
                             {"at": at("09:05"), "what": "fix.local", "op": "start"},
                             {"at": at("09:10"), "what": "fix.local", "op": "end"},
                             {"at": at("10:00"), "what": "review.local", "op": "start"},
                             {"at": at("10:04"), "what": "review.local", "op": "end"}])["visits"]
passes = [v for v in local if v.get("n") == "local_pass"]
check("history: a start after an interrupted run is a stay of its own",
      len(passes) == 2 and passes[1]["s"] == 240, str(local))
got = seq_of([{"at": at("09:00"), "what": "qa", "op": "in"},
              {"at": at("10:00"), "what": "qa", "op": "accepted"},
              {"at": at("10:01"), "what": "merge", "op": "wait"},
              {"at": at("11:00"), "what": "qa", "op": "accepted"},
              {"at": at("11:01"), "what": "merge", "op": "wait"},
              {"at": at("12:00"), "what": "merge", "op": "merged"}])
check("history: QA Done seen again is not another verdict",
      got.count("qa_verdict") == 1 and got.count("merge_wait") == 1, str(got))
got = process.history({}, [{"at": at("09:00"), "what": "workshop", "op": "none", "session": "s"}])
check("history: a workshop left untouched is no pass", not got["passes"]["workshop"], str(got))
got = seq_of([{"at": at("09:00"), "what": "steps.review", "op": "open", "session": "a"},
              {"at": at("09:30"), "what": "steps.review", "op": "end", "session": "a"},
              {"at": at("09:31"), "what": "review.local", "op": "start"},
              {"at": at("09:35"), "what": "review.local", "op": "end"}])
check("history: no long way round is made up between two places",
      got[-2:] == ["review", "local_pass"] and "merged" not in got, str(got))
review = [v for v in process.history({}, [
    {"at": at("09:00"), "what": "steps.review", "op": "open", "session": "r"},
    {"at": at("10:00"), "what": "steps.review", "op": "open", "session": "r"},
    {"at": at("10:30"), "what": "steps.review", "op": "end", "session": "r"}])["visits"] if v.get("n") == "review"]
check("history: a review carried on into its next round keeps the round",
      len(review) == 1 and review[0]["s"] == 90 * 60, str(review))
retro = [v for v in process.history({}, [
    {"at": at("09:00"), "what": "retro", "op": "open", "session": "t"},
    {"at": at("09:40"), "what": "retro", "op": "drop", "session": "t"}])["visits"] if v.get("n") == "retro"]
check("history: a retrospective nobody answered still took its time",
      len(retro) == 1 and retro[0]["s"] == 40 * 60, str(retro))
got = seq_of([{"at": at("09:00"), "what": "sync", "op": "open", "session": "a"},
              {"at": at("12:00"), "what": "sync", "op": "open", "session": "b"},
              {"at": at("12:30"), "what": "sync", "op": "end", "session": "b"}])
check("history: a conversation opened in place of a dead one is one stay",
      got.count("sync") == 1 and "merge_check" not in got, str(got))
got = seq_of([{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "a"},
              {"at": at("10:00"), "what": "steps.review", "op": "open", "session": "r"},
              {"at": at("11:00"), "what": "steps.review", "op": "end", "session": "r"},
              {"at": at("12:00"), "what": "steps.code", "op": "open", "session": "b"},
              {"at": at("12:30"), "what": "steps.code", "op": "end", "session": "b"}])
check("history: a stay left open while the feature went elsewhere ends there",
      got.count("code") == 2 and got.index("review") < len(got) - 1 - got[::-1].index("code"), str(got))
sync = [v for v in process.history({}, [
    {"at": at("09:00"), "what": "sync", "op": "open", "session": "a"},
    {"at": at("09:50"), "what": "sync", "op": "open", "session": "b"},
    {"at": at("09:51"), "what": "sync", "op": "drop", "session": "b"}])["visits"] if v.get("n") == "sync"]
check("history: a drop takes back only its own conversation",
      len(sync) == 1 and sync[0]["s"] == 50 * 60, str(sync))
summaries = {"c1": {"human": [[at("09:30"), 60, 3], [at("13:00"), 30, 1]], "cost": 2.5},
             "f1": {"human": [[at("11:05"), 10, 0]], "cost": 0.5}}
mrows = [{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "c1"},
         {"at": at("10:00"), "what": "steps.code", "op": "end", "session": "c1"},
         {"at": at("11:00"), "what": "friction.code-1", "op": "open", "session": "f1"},
         {"at": at("11:10"), "what": "friction.code-1", "op": "finish", "session": "f1", "outcome": "reviewed"},
         {"at": at("11:20"), "what": "regression.local", "op": "start"},
         {"at": at("11:25"), "what": "ask", "op": "answered", "from": "tty"},
         {"at": at("11:30"), "what": "regression.local", "op": "passed"},
         {"at": at("12:00"), "what": "command", "op": "return", "run": "1.1"}]
m = process.history({}, mrows, "review", summaries.get)["metrics"]
check("metrics: each time the person stepped in counts where the feature stood",
      m["input"]["detail"] == {"code": 2, "reg_local": 2} and m["input"]["friction"] == {"f_review": 1}
      and m["input"]["detail"].get("review") is None, str(m))
check("metrics: a session costs where it ran",
      m["cost"] == {"detail": {"code": 2.5}, "friction": {"f_review": 0.5}}, str(m))
check("metrics: none without transcripts but the history's own",
      process.history({}, mrows, "review")["metrics"]["cost"] == {})
st = [v for v in process.history({}, [
    {"at": at("10:00"), "what": "regression.local", "op": "start"},
    {"at": at("15:00"), "what": "command", "op": "x", "run": "2.2"},
    {"at": at("15:00"), "what": "regression.local", "op": "start"},
    {"at": at("15:05"), "what": "regression.local", "op": "passed"}])["visits"] if v.get("n") == "reg_local"]
check("history: an input says nothing of when a run left off", st and st[0].get("s", 0) < 3600, str(st))
with tempfile.TemporaryDirectory() as tmp:
    import claude_usage
    tree = os.path.join(tmp, "tree")
    feat = os.path.join(tree, ".sclaude", "local", "feature")
    os.makedirs(feat)
    folder = os.path.join(tmp, "projects", claude_usage.project_name(tree))
    os.makedirs(folder)
    for sid, nxt in (("a", "b"), ("b", None)):
        with open(os.path.join(folder, sid + ".jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "cost-state", "startTime": 1, "totalCostUSD": 1.5}) + "\n")
            if nxt:
                fh.write(json.dumps({"type": "continued-in", "continuedInSessionId": nxt}) + "\n")
    root, claude_usage.ROOT = claude_usage.ROOT, os.path.join(tmp, "projects")
    try:
        reader = process.transcripts_of(os.path.join(feat, "state.json"))
        got = reader("a")
        reader.done()
    finally:
        claude_usage.ROOT = root
    check("metrics: a conversation carried on under a new id is its last transcript, once",
          got and got["cost"] == 1.5 and got["id"].endswith("b.jsonl"), str(got))
    check("metrics: the transcripts are cached beside the history",
          os.path.exists(os.path.join(feat, process.TRANSCRIPT_CACHE)))
    with open(os.path.join(folder, "c.jsonl"), "w") as fh:
        fh.write(json.dumps({"type": "cost-state", "startTime": 1, "totalCostUSD": 1.0}) + "\n")
        fh.write(json.dumps({"type": "continued-in", "continuedInSessionId": "d"}) + "\n")
    claude_usage.ROOT = os.path.join(tmp, "projects")
    try:
        reader = process.transcripts_of(os.path.join(feat, "state.json"))
        before = reader("c")
        reader.done()
        with open(os.path.join(folder, "d.jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "cost-state", "startTime": 1, "totalCostUSD": 4.0}) + "\n")
        reader = process.transcripts_of(os.path.join(feat, "state.json"))
        after = reader("c")
    finally:
        claude_usage.ROOT = root
    check("metrics: a continuation not on disk yet is followed once it is",
          before["cost"] == 1.0 and after["cost"] == 4.0, "%s %s" % (before, after))
same = {"a": {"human": [], "cost": 2.0, "id": "/t/b.jsonl"}, "b": {"human": [], "cost": 2.0, "id": "/t/b.jsonl"}}
m = process.history({}, [{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "a"},
                         {"at": at("10:00"), "what": "steps.code", "op": "open", "session": "b"},
                         {"at": at("11:00"), "what": "steps.code", "op": "end", "session": "b"}],
                    None, same.get)["metrics"]
check("metrics: two ids of one conversation count it once", m["cost"] == {"detail": {"code": 2.0}}, str(m))
st = [v for v in process.history({}, [
    {"at": at("10:00"), "what": "regression.local", "op": "start", "run": "1.1"},
    {"at": at("10:20"), "what": "ask", "op": "answered", "run": "1.1"},
    {"at": at("15:00"), "what": "ask", "op": "answered", "run": "2.2"},
    {"at": at("15:01"), "what": "regression.local", "op": "start", "run": "2.2"},
    {"at": at("15:05"), "what": "regression.local", "op": "passed", "run": "2.2"}])["visits"] if v.get("n") == "reg_local"]
check("history: a run cut off ends at its own last line, not the next run's",
      st and st[0].get("s") == 24 * 60 and st[0].get("k") == 2, str(st))
check("the page offers the metrics by checkboxes, each with the whole feature's total",
      'class="metrics"' in page and 'value="input"' in page and 'value="cost"' in page
      and page.count('class="mt-total"') == 2)
check("an answer to sclaude and a command go into the history",
      "history_add \"$ASK_TREE/.sclaude/local/feature/state.json\" ask answered" in read("sclaude", "lib", "io.sh")
      and "history_command \"$wt\"" in read("sclaude", "lib", "state.sh")
      and 'SCLAUDE_COMMAND="${1:-menu}"' in sclaude
      and 'export SCLAUDE_RUN="${SCLAUDE_RUN:-' in sclaude and "SCLAUDE_REEXEC" not in sclaude)
check("the player pauses the arrow too", "animation-play-state:paused" in process.PLAY_STYLE)
check("the player pauses the time, not only the steps",
      "if (!paused) left -=" in process.PLAY_SCRIPT and "if (!paused) gone +=" in process.PLAY_SCRIPT)
for m in ("detail", "overview", "states", "workshop", "friction"):
    check("page plays the %s map" % m, 'data-play="%s"' % m in page)
check("page chooses the friction and the workshop passes",
      'data-pass="friction"' in page and 'data-pass="workshop"' in page)
check("cmd_flow sends the history", "process.history(json.load(fh), process.read_history(state)" in read("sclaude", "lib", "actions.sh")
      and '"history": history' in read("sclaude", "lib", "actions.sh"))
check("the state's writers name the same file",
      '"history.jsonl"' in read("sclaude", "lib", "state.sh") and "history.jsonl" in read("sclaude", "lib", "state.sh"))
check("the map is not centred across on open (it hid the first lanes)",
      "inline: 'nearest'" in process.LIVE_SCRIPT and "inline: 'center'" not in process.LIVE_SCRIPT)

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
