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
    check("step %s on the map" % title, any(n[3] == title for n in process.all_nodes().values()))
    # The sync is S on the blocks it runs ahead of, no block of its own.
    check("step %s in the overview" % title,
          any(n[3] == title for n in process.OVERVIEW_NODES.values()) != (kind == "sync"))
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
others = set(process.OVERVIEW_NODES)
check("every overview block borrows a detail",
      not (others - set(process.ALIAS)) and all(v in process.DETAILS for v in process.ALIAS.values()),
      str(sorted(others - set(process.ALIAS))))
# W: a session that may change sclaude itself, which is a prompt carrying the
# workshop's block; a fixing session works from its step's prompt.
drawn = process.all_nodes()
for nid, prompt in (("plan", "plan"), ("code", "code"), ("pr", "pr"), ("review", "review"), ("sync", "sync"),
                    ("retro", "retro"), ("fix_local", "code"), ("fix_preview", "review"), ("fix_prod", "review")):
    writes = "<block:workshop>" in read("sclaude", "prompts", prompt + ".md")
    check("W on %s as its prompt lets it write sclaude" % nid, ("W" in drawn[nid][5]) == writes,
          "%s: %s" % (nid, drawn[nid][5]))
    logs = "<include:friction>" in read("sclaude", "prompts", prompt + ".md")
    check("F on %s as its prompt has it log what got in its way" % nid, ("F" in drawn[nid][5]) == logs,
          "%s: %s" % (nid, drawn[nid][5]))
# The reviews that change sclaude carry W as their prompts let them.
for nid, prompt in (("f_review", "_friction-body"), ("f_monthly", "friction-deferred")):
    check("W on %s as its prompt lets it write sclaude" % nid,
          ("W" in process.FRICTION_NODES[nid][5]) == ("<workshop-rules>" in read("sclaude", "prompts", prompt + ".md")))
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
    # A hold is left by what a person does: a hold drawn with no way out
    # says the cycle ends there.
    for nid, node in nodes.items():
        if node[2] == "hold":
            check("%s: %s has a way out" % (name, nid), any(a == nid for a, *_ in edges))

for pos, over in process.POSITIONS.items():
    check("position %s on a map" % pos, pos in process.all_nodes())
    check("position %s in the overview" % pos, over in process.OVERVIEW_NODES)
for cmd, _verb, _when, _what, target in process.COMMANDS:
    check("%s leads somewhere real" % cmd,
          all(t == "@here" or t in process.all_nodes() for t in process.places(target)))
drop = next(c for c in process.COMMANDS if c[1] == "drop")
check("drop ends at the clean-up and done", process.places(drop[4]) == ["cleanup", "end"])
model = process.client_model()
check("a place is lit on every map that has it",
      set(model["alias"].get("cleanup", [])) == {"o_end"})
# Merged and not shipped is a way the cycle takes (ship → epilogue): the
# glance draws it.
check("the glance: merged, not shipped",
      ("ship", "epilogue", "no", "") in process.EDGES
      and any(a == "o_prod" and b == "o_epilogue" and "not shipped" in l for a, b, l, _k in process.OVERVIEW_EDGES))

# --- the map a project's config draws ----------------------------------------

def reach(nodes, edges, start, ends):
    graph = {}
    for a, b, *_ in edges:
        graph.setdefault(a, set()).add(b)
    seen, todo = {start}, [start]
    while todo:
        for b in graph.get(todo.pop(), ()):
            if b not in seen:
                seen.add(b)
                todo.append(b)
    return seen

bare = {}
configs = [("no sections", bare)] + [
    ("review %s, qa %s, merge %s" % (r, q, m),
     dict(process.example_config(), review=r, qa=q, merge=m))
    for r in ("github", "local", "off") for q in ("github", "both", "auto") for m in ("github", "both", "auto")]
for name, cfg in configs:
    nodes, edges = process.for_config(cfg, process.NODES, process.EDGES)
    check("%s: every arrow between blocks drawn" % name, all(a in nodes and b in nodes for a, b, *_ in edges))
    seen = reach(nodes, edges, "new", {"end"})
    check("%s: every block reached from the start" % name, set(nodes) <= seen | {"end"} | set(
        n for n in nodes if n.startswith("f_") or n.startswith("w_")), str(set(nodes) - seen))
    check("%s: the end reached" % name, "end" in seen)
    check("%s: one reviewer at most" % name, not ("ci_review" in nodes and "local_pass" in nodes))
    n2, e2 = process.for_config(cfg, process.OVERVIEW_NODES, process.OVERVIEW_EDGES)
    check("%s: the glance's arrows drawn" % name, all(a in n2 and b in n2 for a, b, *_ in e2))
    with process.configured(cfg):
        process.Diagram(*process.node_sets()[0]).svg()
        lit = [o for o in process.POSITIONS.values() if o]
        check("%s: every place lit is drawn" % name, all(x in process.OVERVIEW_NODES for x in lit))
for name, cfg in configs:
    with process.configured(cfg):
        lonely = ["%s/%s" % (m, nid) for m, _l, nodes, edges in process.node_sets()
                  for nid, n in nodes.items()
                  if n[2] == "gate" and sum(1 for a, *_ in edges if a == nid) < 2]
    check("%s: every gate has a way for each answer" % name, not lonely, str(lonely))
gh = process.for_config(dict(process.example_config(), review="github"), process.NODES, process.EDGES)[0]
lo = process.for_config(dict(process.example_config(), review="local"), process.NODES, process.EDGES)[0]
check("review github draws the review on CI", "ci_review" in gh and "local_pass" not in gh)
check("review local draws the local passes", "local_pass" in lo and "ci_review" not in lo)
none = process.for_config(bare, process.NODES, process.EDGES)
check("no regression, no board: no gates for them, the flow carried past",
      not {"reg_local", "preview_ok", "prod_ok", "qa_check"} & set(none[0])
      and ("works", "pr") in {(a, b) for a, b, *_ in none[1]}
      and ("prod", "epilogue") in {(a, b) for a, b, *_ in none[1]})
check("merge auto names who merges", process.for_config(dict(merge="auto"), process.NODES, process.EDGES)[0]["merge"][3]
      == "Merged by sclaude")

with tempfile.TemporaryDirectory() as tmp:
    main, tree = os.path.join(tmp, "main"), os.path.join(tmp, "tree")
    os.makedirs(os.path.join(main, ".git", "worktrees", "t"))
    for where, cfg in ((main, {"regression": {"local": ["e2e"]}, "review": None}),
                       (tree, {"regression": {"preview": ["e2e"]}, "review": "local",
                               "board": {"columns": {"done": "Done"}}})):
        os.makedirs(os.path.join(where, ".sclaude"), exist_ok=True)
        with open(os.path.join(where, ".sclaude", "config.json"), "w") as fh:
            json.dump(cfg, fh)
    with open(os.path.join(tree, ".git"), "w") as fh:
        fh.write("gitdir: %s\n" % os.path.join(main, ".git", "worktrees", "t"))
    got = process.config_of(tree)
check("config_of: a stage the tree adds is taken key by key",
      got.get("regression") == {"local": ["e2e"], "preview": ["e2e"]}, str(got))
check("config_of: null in the main checkout is no value", got.get("review") == "local", str(got))
check("QA is on the map by the Done column alone",
      "qa_check" in process.for_config({"board": {"columns": {"done": "Done"}}}, process.NODES, process.EDGES)[0]
      and "in_qa" not in process.for_config({"board": {"columns": {"done": "Done"}}}, process.NODES, process.EDGES)[0])
with process.configured({}):
    check("a place this map does not draw is lit where the flow goes on",
          process.on_map("qa_check") == "handoff", process.on_map("qa_check"))

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
    ("held", {"step": "done", "pr": 7, "deploy": {"prod": {"sha": "x"}},
              "regression": {"prod": {"status": "failed"}}}, "MERGED", "hold_ways"),
    ("a fix's own PR is not held", {"step": "done", "deploy": {"prod": {"sha": "x"}},
                                    "regression": {"prod": {"status": "failed"}}}, "OPEN", "preview"),
    ("production running", {"step": "done", "deploy": {"prod": {"sha": "x"}},
                            "regression": {"prod": {"status": "running", "started": now}}}, "MERGED", "prod"),
    ("a run cut off from an unrunnable hold is no hold",
     {"step": "done", "pr": 7, "deploy": {"prod": {"sha": "x"}},
      "regression": {"prod": {"status": "running", "started": "2020-01-01T00:00:00+00:00",
                              "unrunnable": True}}}, "MERGED", "done_cmd"),
    ("no pull request carries nothing", {"step": "done", "deploy": {"prod": {"sha": "x"}},
                                         "regression": {"prod": {"status": "failed"}}}, "MERGED", "done_cmd"),
    ("a run again from an unrunnable hold", {"step": "done", "deploy": {"prod": {"sha": "x"}},
                                             "regression": {"prod": {"status": "running", "started": now,
                                                                     "unrunnable": True}}}, "MERGED", "prod"),
    ("a fix merged in a new PR is not held by the old release",
     {"step": "done", "pr": 8, "deploy": {"prod": {"sha": "x", "pr": 7}},
      "regression": {"prod": {"status": "failed"}}}, "MERGED", "done_cmd"),
    ("held by the release of this PR", {"step": "done", "pr": 7, "deploy": {"prod": {"sha": "x", "pr": 7}},
                                        "regression": {"prod": {"status": "failed"}}}, "MERGED", "hold_ways"),
    ("rolled back", {"step": "done", "deploy": {"prod": {"sha": "x"}}, "rollback": {"prod": {"code": "done"}},
                     "regression": {"prod": {"status": "failed"}}}, "MERGED", "done_cmd"),
    ("merged", {"step": "done"}, "MERGED", "done_cmd"),
    ("retro ran", {"step": "done", "retro": {"runs": [{"done": True}]}}, "MERGED", "cleanup"),
    ("a retro open", {"step": "done", "retro": {"runs": [{"session": "r"}]}}, "MERGED", "retro"),
    ("a retro resumed after its end", {"step": "done", "retro": {"runs": [
        {"session": "r", "done": True, "finished": "2026-01-01T10:00:00+00:00",
         "resumed": "2026-01-02T10:00:00+00:00"}]}}, "MERGED", "retro"),
    ("a retro resumed and ended again", {"step": "done", "retro": {"runs": [
        {"session": "r", "done": True, "finished": "2026-01-03T10:00:00+00:00",
         "resumed": "2026-01-02T10:00:00+00:00"}]}}, "MERGED", "cleanup"),
    ("a sync going ahead of the step", {"step": "code", "sync": {"runs": [{"session": "s", "started": now}]}},
     "", "sync"),
    ("a sync left unfinished, the step going on", {"step": "review", "steps": {"review": {"runs": [
        {"session": "r", "started": "2020-01-01T00:00:00+00:00", "resumed": now}]}},
        "sync": {"runs": [{"session": "s", "started": now, "finished": now}]}}, "", "review"),
    ("a sync left unfinished in a step before", {"step": "review", "review": {"local": {"running": now}},
                                                 "sync": {"runs": [{"session": "s", "started": now,
                                                                    "finished": now}]}}, "OPEN", "local_pass"),
    ("a sync taken up again", {"step": "code", "sync": {"runs": [
        {"session": "s", "started": "2026-01-01T00:00:00+00:00", "finished": "2026-01-01T01:00:00+00:00",
         "resumed": now}]}}, "", "sync"),
    ("a sync killed long ago", {"step": "code", "sync": {"runs": [
        {"session": "s", "started": "2020-01-01T00:00:00+00:00"}]}}, "", "code"),
    ("a sync killed, then taken up a day later", {"step": "code", "sync": {"runs": [
        {"session": "s", "started": "2020-01-01T00:00:00+00:00", "resumed": now}]}}, "", "sync"),
    ("local review passes", {"step": "review", "review": {"local": {"running": now}}}, "OPEN", "local_pass"),
    ("local review passes long killed", {"step": "review", "review": {"local": {"running": "2020-01-01T00:00:00+00:00"}}},
     "OPEN", "review"),
    ("asked to ship, or shipping", {"step": "done", "pr": 7, "prod_pass": {"shipping": now}}, "MERGED", "ship"),
    ("asked to ship, the answer a night away", {"step": "done", "pr": 7,
                                                "prod_pass": {"shipping": "2020-01-01T00:00:00+00:00"}},
     "MERGED", "ship"),
    ("no change", {"step": "done", "no_change": True}, "", "cleanup"),
    ("closed", {"step": "done"}, "CLOSED", "cleanup"),
    ("no answer", {"step": "done"}, "", "preview"),
]
for name, state, pr, want in cases:
    got, _why = process.position(state, pr)
    check("position: %s" % name, got == want, "want %s, got %s" % (want, got))
    # A sync is lit where its S turns (the page's syncAt).
    check("position: %s can be lit" % name, got in process.POSITIONS or got == "sync", got)
_, why = process.position({"step": "code", "friction": {"code-1": {"runs": [{"session": "f"}]}}})
check("position: an open friction review is said", "friction review" in why, why)
check("busy: a friction review open turns F on the step it follows",
      process.busy({"friction": {"review-3": {"runs": [{"session": "f"}]},
                                 "fix-local-1": {"runs": [{"session": "g", "done": True}]}}}) == {"review": ["F"]})
check("busy: a fixing session's review turns F on the fix",
      process.busy({"friction": {"fix-local-2": {"runs": [{"session": "f"}]}}}) == {"fix_local": ["F"]})
check("busy: a step's session never turns W: it does not write sclaude",
      process.busy({"steps": {"code": {"runs": [{"session": "c", "started": now}]}}}, {"approved": ["c"]}) == {})
check("busy: a session the workshop lets write turns W while its run is open",
      process.busy({"retro": {"runs": [{"session": "r", "started": now}]}}, {"approved": ["r"]}) == {"retro": ["W"]})
check("busy: not once that run ended",
      process.busy({"retro": {"runs": [{"session": "r", "started": now, "finished": now, "done": True}]}},
                   {"approved": ["r"]}) == {})
check("the badges carry a ring to turn", 'class="ring"' in process.doc() and "ring-turn" in process.doc())
check("_flow hands the busy badges to the page", '"busy": busy' in read("sclaude", "lib", "actions.sh"))
got, _ = process.position({"step": "done"}, "MERGED", {"session": "e", "done": False})
check("position: an epilogue broken off", got == "epilogue", got)

# The menu's words for a merged feature, from step_label itself.
def label(state, epilogue=None):
    with tempfile.TemporaryDirectory() as tmp:
        feature = os.path.join(tmp, ".sclaude", "local", "feature")
        os.makedirs(feature)
        with open(os.path.join(feature, "state.json"), "w") as fh:
            json.dump(dict(state, feature="f", branch="feat/f"), fh)
        if epilogue is not None:
            with open(os.path.join(tmp, "f.json"), "w") as fh:
                json.dump(epilogue, fh)
        script = ('LIB="$1"; source "$LIB/state.sh"; source "$LIB/steps.sh"; '
                  'D="$2"; branch_pr_state() { echo MERGED; }; epilogue_dir() { echo "$D"; }; step_label done "$D"')
        return subprocess.run(["bash", "-c", script, "bash", LIB, tmp],
                              capture_output=True, text=True, timeout=60).stdout.strip()
held = {"step": "done", "pr": 7, "deploy": {"prod": {"sha": "x"}}, "regression": {"prod": {"status": "failed"}}}
running = {"step": "done", "regression": {"prod": {"status": "running", "started": now}}}
for name, state, epi, want in [
        ("held", held, None, "steps done, production held"),
        ("production running", running, None, "steps done, production regression running"),
        ("asked to ship", {"step": "done", "prod_pass": {"shipping": now}}, None, "steps done, shipping to production"),
        ("an epilogue broken off", {"step": "done"}, {"session": "e", "done": False}, "6/7 epilogue"),
        ("the retro ran", {"step": "done", "retro": {"runs": [{"done": True}]}}, None, "all done"),
        ("merged", {"step": "done"}, None, "7/7 retro"),
        ("the map could not say", {"step": "done"}, ["not", "an", "object"], "4/7 done")]:
    got = label(state, epi)
    check("menu: %s reads %r" % (name, want), got == want, got)

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
          re.search(r'<section style="page:s%d"[ >]' % n, doc) is not None
          and ('@page s%d{@top-left{content:"%s"' % (n, title)) in doc
          and re.search(r'<h2[^>]*>%s[ <]' % re.escape(shown), doc) is not None)
check("a header's title prints as written, not as an escape",
      "\\u" not in process.running_heads())
for cmd, _verb, when, _what, _target in process.COMMANDS:
    check("%s: its When names where it is open" % cmd, when in process.WHEN, when)
for when, at in process.WHEN.items():
    check("%s: open only on real places" % when, all(n in process.all_nodes() for n in at), str(at))
with process.configured(process.example_config()):
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
check("the proxy serves the map as the project's config draws it",
      '"/__sclaude/flow"' in proxy and "model.page(label, model.config_of(found[0]))" in proxy)
check("the proxy runs _flow", '"_flow"' in proxy)
check("the proxy lists the map", "/__sclaude/flow?f=" in proxy and 'MAP_NAME = "Process map (BPMN)"' in proxy)
check("the proxy serves the whole map for main, by its config",
      '"/__sclaude/bpmn"' in proxy and "model.doc(model.config_of(main[0])" in proxy)
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
      # A plan's session broken off and opened again took it up: nothing ran
      # between them, and nothing is played there (REOPENED).
      seq[:6] == ["new", "prepare", "plan", "plan", "approve", "plan_check"], str(seq))
code = [v for v in got["visits"] if v.get("n") == "code"]
check("history: a conversation resumed is one stay, its sittings summed",
      len(code) == 1 and code[0].get("k") == 2 and code[0].get("s") == 69 * 60, str(code))
check("history: the places between are filled in along the map",
      seq[seq.index("code"):seq.index("pr") + 1] == ["code", ("friction", 0), ("workshop", 0), "works", ("regression", 0), "pr"],
      str(seq))
rg = got["passes"]["regression"]
check("history: a regression run is a pass on its own map, with its time",
      len(rg) == 1 and [x["n"] for x in rg[0]["steps"]] == ["r_local", "reg_local", "r_on"]
      and rg[0]["steps"][1].get("s") == 300, str(rg))
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
check("history: every detailed place a feature stands on is on the overview",
      all(process.projection()[n] in process.OVERVIEW_NODES for n in process.POSITIONS))
# Where the feature left the map (deviations): a jump the map has no way
# for, a map of its own reached from no block with its letter; a history
# along the map has none.
check("deviations: none along the map", not any(v.get("off") for v in got["visits"]), str(got["visits"]))
odd = process.history({}, [{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "c"},
                           {"at": at("09:30"), "what": "steps.code", "op": "end", "session": "c"},
                           {"at": at("10:00"), "what": "steps.plan", "op": "open", "session": "p"}], "plan")["visits"]
check("deviations: a jump with no way on the map",
      [v["n"] for v in odd if v.get("off")] == ["plan"] and "no way from 2 · code to 1 · plan" in odd[-1]["off"], str(odd))
odd = process.history({}, [{"at": at("09:00"), "what": "epilogue", "op": "open", "session": "e"},
                           {"at": at("09:10"), "what": "epilogue", "op": "finish", "session": "e"},
                           {"at": at("09:40"), "what": "sync", "op": "open", "session": "y"},
                           {"at": at("09:50"), "what": "sync", "op": "finish", "session": "y"},
                           {"at": at("10:00"), "what": "retro", "op": "open", "session": "r"}], "retro")["visits"]
check("deviations: a sync where no block carries S",
      [v["pass"][0] for v in odd if v.get("off")] == ["sync"], str(odd))
# A status session run_status marked as the preview's (`about`) plays on
# the epilogue's copy beside the preview, and the way on goes from the place
# before it: no deviation. One with no mark is the cycle's own epilogue.
def ep(t, session, op="open", about="preview"):
    row = {"at": at(t), "what": "epilogue", "op": op, "session": session}
    if about and op == "open":
        row["about"] = about
    return row
red_rows = [{"at": at("09:35"), "what": "deploy.preview", "op": "start"},
            {"at": at("09:38"), "what": "deploy.preview", "op": "done"},
            {"at": at("09:40"), "what": "regression.preview", "op": "start"},
            {"at": at("09:50"), "what": "regression.preview", "op": "failed"},
            ep("09:55", "e"), ep("10:00", "e", "finish")]
red = process.history({}, red_rows + [
    {"at": at("11:00"), "what": "steps.review", "op": "open", "session": "r"}], "review")["visits"]
seq = [v.get("n") or v["pass"][0] for v in red]
check("history: a red preview's status on its copy, after the run",
      seq[seq.index("preview"):] == ["preview", "regression", "epi_preview", "review"]
      and not any(v.get("off") for v in red), str(red))
vs = process.history({}, red_rows[:4] + [ep("09:55", "e", about="")], "epilogue")["visits"]
check("history: a status with no mark is the cycle's own epilogue",
      [v.get("n") for v in vs if "n" in v][-1] == "epilogue"
      and not any(v.get("n") == "epi_preview" for v in vs), str(vs))
# Green after a red status: written again, on the copy too.
vs = process.history({}, red_rows + [
    {"at": at("10:10"), "what": "steps.review", "op": "open", "session": "r"},
    {"at": at("10:15"), "what": "steps.review", "op": "finish", "session": "r"},
    {"at": at("10:20"), "what": "deploy.preview", "op": "start"},
    {"at": at("10:21"), "what": "deploy.preview", "op": "done"},
    {"at": at("10:22"), "what": "regression.preview", "op": "start"},
    {"at": at("10:23"), "what": "regression.preview", "op": "passed"},
    ep("10:24", "e2")], "epilogue")["visits"]
check("history: green after a red status is written again on the copy",
      [v.get("n") for v in vs if "n" in v].count("epi_preview") == 2
      and not any(v.get("off") for v in vs), str(vs))
# One finished from the menu while QA checks, or during the review: a step
# aside to the copy with no merge or ship filled in, no deviation, and back
# at the place it left.
vs = process.history({}, red_rows + [
    {"at": at("10:20"), "what": "deploy.preview", "op": "start"},
    {"at": at("10:21"), "what": "deploy.preview", "op": "done"},
    {"at": at("10:22"), "what": "regression.preview", "op": "start"},
    {"at": at("10:23"), "what": "regression.preview", "op": "passed"},
    {"at": at("10:25"), "what": "qa", "op": "in"},
    ep("11:00", "e3"), ep("11:05", "e3", "finish")], "qa_check")["visits"]
names = [v.get("n") for v in vs if "n" in v]
check("history: a rewrite finished from the menu during QA is the preview's copy",
      names[names.index("qa_check"):] == ["qa_check", "epi_preview", "qa_check"]
      and not {"merge", "merged", "ship", "epilogue"} & set(names)
      and not any(v.get("off") for v in vs), str(vs))
vs = process.history({}, red_rows + [
    {"at": at("10:10"), "what": "steps.review", "op": "open", "session": "r"},
    ep("10:20", "e4"), ep("10:25", "e4", "finish")], "review")["visits"]
check("history: a rewrite finished from the menu during the review is no deviation",
      [v.get("n") for v in vs if "n" in v][-3:] == ["review", "epi_preview", "review"]
      and not any(v.get("off") for v in vs), str(vs))
# The second time round, after the retrospective sent it back: the mark
# still decides, not what came before.
vs = process.history({}, [
    {"at": at("08:00"), "what": "merge", "op": "merged"},
    {"at": at("08:05"), "what": "deploy.prod", "op": "done"},
    ep("08:10", "p", about=""), ep("08:15", "p", "finish"),
    {"at": at("08:20"), "what": "retro", "op": "open", "session": "t"},
    {"at": at("08:30"), "what": "retro", "op": "finish", "session": "t"}] + red_rows)["visits"]
check("history: a red status the second time round is on the copy",
      [v.get("n") for v in vs if "n" in v][-1] == "epi_preview", str(vs))
# The mark is written by run_status, before the merge only, into the row.
gh_src = read("sclaude", "lib", "github.sh")
run_src = re.search(r"^run_status\(\) \{\n.*?^\}\n", gh_src, re.S | re.M).group(0)
check("run_status marks a status before the merge as the preview's",
      '[[ -n "$pr" && "$pr" != null && "$merged" != MERGED ]] && about=preview' in run_src
      and 'SCLAUDE_ABOUT="$about" session_runs "$fstate" epilogue open' in run_src)
with tempfile.TemporaryDirectory() as wt:
    with open(os.path.join(wt, "state.json"), "w") as fh:
        json.dump({}, fh)
    subprocess.run(["bash", "-c", 'source "%s/state.sh"; SCLAUDE_ABOUT=preview session_runs "%s/state.json" epilogue open e1; '
                    'session_runs "%s/state.json" epilogue open e2' % (LIB, wt, wt)], check=True)
    with open(os.path.join(wt, "history.jsonl")) as fh:
        hist = [json.loads(line) for line in fh]
    check("the history row carries what the status is about",
          [r.get("about") for r in hist], ["preview", None])
# The rewrite is armed by any red run that got to its session, and cleared
# only by a green session that said its comments are written; red words
# standing over a green preview are not skipped by the fingerprint.
arm = run_src.find("status.preview_red true")
did_not_start = run_src.find('if [[ "$ran" -ne 1 ]]')
clear = run_src.find('"$written" -eq 1 ]]')
check("a red run arms the rewrite before the not-started exit, a written green one clears it",
      0 < run_src.find("session_closed") < arm < did_not_start < clear
      and "status.preview_red null" in run_src[clear:clear + 160]
      and 'written=1' in run_src)
check("the fingerprint does not skip red words over a green preview",
      'status.preview_red 2>/dev/null || true)" != true ]]' in run_src[:run_src.find("nothing changed, skipping")])
check("a resumed epilogue keeps its red preview",
      'state_set "$estate" preview_red' in run_src
      and '"$prod" "$wt" "$preview_red"' in read("bin", "sclaude"))
check("the green rewrite is tried on every green pass",
      read("sclaude", "lib", "deploy.sh").count('status_green_again "$slug"') == 2)
with tempfile.TemporaryDirectory() as wt:
    os.makedirs(os.path.join(wt, ".sclaude", "local", "feature"))
    out = []
    for flag in ("true", "null"):
        with open(os.path.join(wt, ".sclaude", "local", "feature", "state.json"), "w") as fh:
            json.dump({"status": {"preview_red": json.loads(flag)}}, fh)
        out.append(subprocess.run(["bash", "-c", 'source "%s/state.sh"; source "%s/github.sh"; '
                                   'run_status() { echo "RAN $5 $6"; }; status_green_again s 7 9 OPEN "%s"'
                                   % (LIB, LIB, wt)], capture_output=True, text=True).stdout.strip())
    check("a green preview rewrites a red status, and only a red one", out, ["RAN 1 0", ""])
check("the page pauses on a deviation and says it",
      'id="pl-off"' in page and "function deviate(" in page and "if (s.off) deviate(" in page)
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
got = process.history({}, [{"at": at("09:00"), "what": "sync", "op": "open", "session": "a"},
                           {"at": at("12:00"), "what": "sync", "op": "open", "session": "b"},
                           {"at": at("12:30"), "what": "sync", "op": "end", "session": "b"}])
sy = got["passes"]["sync"]
check("history: a sync is a pass on its own map", [v.get("pass") for v in got["visits"]][-1] == ["sync", 0], str(got))
check("history: a conversation opened in place of a dead one is one stay",
      len(sy) == 1 and [x["n"] for x in sy[0]["steps"]].count("sync") == 1
      and [x for x in sy[0]["steps"] if x["n"] == "sync"][0]["s"] == 210 * 60, str(sy))
got = seq_of([{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "a"},
              {"at": at("10:00"), "what": "steps.review", "op": "open", "session": "r"},
              {"at": at("11:00"), "what": "steps.review", "op": "end", "session": "r"},
              {"at": at("12:00"), "what": "steps.code", "op": "open", "session": "b"},
              {"at": at("12:30"), "what": "steps.code", "op": "end", "session": "b"}])
check("history: a stay left open while the feature went elsewhere ends there",
      got.count("code") == 2 and got.index("review") < len(got) - 1 - got[::-1].index("code"), str(got))
sync = [x for x in process.history({}, [
    {"at": at("09:00"), "what": "sync", "op": "open", "session": "a"},
    {"at": at("09:50"), "what": "sync", "op": "open", "session": "b"},
    {"at": at("09:51"), "what": "sync", "op": "drop", "session": "b"}])["passes"]["sync"][0]["steps"]
        if x["n"] == "sync"]
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
      m["input"]["detail"] == {"code": 2, "works": 1} and m["input"]["friction"] == {"f_review": 1}
      and m["input"]["regression"] == {"reg_local": 1}
      and m["input"]["detail"].get("review") is None, str(m))
check("metrics: a session costs where it ran",
      m["cost"] == {"detail": {"code": 2.5}, "friction": {"f_review": 0.5}}, str(m))
w = process.history({}, mrows + [{"at": at("11:26"), "what": "ask", "op": "answered", "waited": "600"},
                                 {"at": at("11:27"), "what": "ask", "op": "answered", "waited": "0"}],
                    "review", {"c1": {"human": [[at("09:30"), 60, 3, 7200]], "cost": 0}}.get)["metrics"]["wait"]
check("metrics: the wait for the person, the whole of it, where it was answered",
      w == {"detail": {"code": 7200}, "regression": {"reg_local": 600}}, str(w))
check("the page offers the wait, and shows no zero", 'value="wait"' in page and "if (v)" in page)
check("a question of sclaude's says how long it waited",
      'ask_log "$__prompt" "$__from" "$__reply" "$__in" "$((SECONDS - __asked))"' in read("sclaude", "lib", "ui.sh")
      and 'waited="$5"' in read("sclaude", "lib", "io.sh"))
# A sync, which the glance does not draw, counts there under the block it ran
# ahead of (P-11), and once only in the feature's total.
ms = process.history({}, [{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "c1"},
                          {"at": at("10:00"), "what": "steps.code", "op": "end", "session": "c1"},
                          {"at": at("10:05"), "what": "sync", "op": "open", "session": "y1"},
                          {"at": at("10:20"), "what": "sync", "op": "finish", "session": "y1"},
                          {"at": at("10:30"), "what": "steps.pr", "op": "open", "session": "p1"}],
                     "pr", {"y1": {"human": [], "cost": 1.5}}.get)["metrics"]["cost"]
check("metrics: a sync costs on its map, and on the glance under the step it ran ahead of",
      ms.get("sync") == {"sync": 1.5} and ms.get("ahead") == {"pr": 1.5}, str(ms))
check("the page sums the glance with the syncs, the feature without them twice",
      "['detail', 'regression', 'ahead']" in page and "map !== 'ahead'" in page)
check("metrics: none without transcripts but the history's own",
      process.history({}, mrows, "review")["metrics"]["cost"] == {})
st = [v for p in process.history({}, [
    {"at": at("10:00"), "what": "regression.local", "op": "start"},
    {"at": at("15:00"), "what": "command", "op": "x", "run": "2.2"},
    {"at": at("15:00"), "what": "regression.local", "op": "start"},
    {"at": at("15:05"), "what": "regression.local", "op": "passed"}])["passes"]["regression"]
      for v in p["steps"] if v["n"] == "reg_local"]
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
st = [v for p in process.history({}, [
    {"at": at("10:00"), "what": "regression.local", "op": "start", "run": "1.1"},
    {"at": at("10:20"), "what": "ask", "op": "answered", "run": "1.1"},
    {"at": at("15:00"), "what": "ask", "op": "answered", "run": "2.2"},
    {"at": at("15:01"), "what": "regression.local", "op": "start", "run": "2.2"},
    {"at": at("15:05"), "what": "regression.local", "op": "passed", "run": "2.2"}])["passes"]["regression"]
      for v in p["steps"] if v["n"] == "reg_local"]
check("history: a run cut off ends at its own last line, not the next run's",
      [v.get("s") for v in st] == [20 * 60, 4 * 60], str(st))
# A run and a sync on maps of their own, in the history.
h = process.history({"sync": {"runs": [{"session": "a", "started": now}]}},
                    [{"at": at("09:00"), "what": "sync", "op": "open", "session": "a"},
                     {"at": at("09:30"), "what": "sync", "op": "end", "session": "a"},
                     {"at": at("10:00"), "what": "sync", "op": "open", "session": "a"},
                     {"at": at("10:20"), "what": "sync", "op": "close"}], "sync")
check("history: a state with a sync is played", h and len(h["passes"]["sync"]) == 1, str(h and h["passes"]))
check("history: a sync taken up again is the same pass, and stands there",
      any(x.get("here") for x in h["passes"]["sync"][0]["steps"])
      and not any(v.get("n") == "sync" for v in h["visits"]), str(h))
h = process.history({}, [{"at": at("09:00"), "what": "steps.code", "op": "open", "session": "c"},
                         {"at": at("09:30"), "what": "steps.code", "op": "end", "session": "c"},
                         {"at": at("10:00"), "what": "regression.local", "op": "start"},
                         {"at": at("10:05"), "what": "regression.local", "op": "failed"},
                         {"at": at("10:06"), "what": "fix.local", "op": "start", "session": "x"},
                         {"at": at("10:20"), "what": "fix.local", "op": "end", "session": "x"},
                         {"at": at("10:21"), "what": "friction.fix-local-1", "op": "open", "session": "f"},
                         {"at": at("10:25"), "what": "friction.fix-local-1", "op": "finish", "session": "f"},
                         {"at": at("10:30"), "what": "regression.local", "op": "start"},
                         {"at": at("10:35"), "what": "regression.local", "op": "passed"}], "pr")
seq = [v.get("n") or tuple(v["pass"]) for v in h["visits"]]
check("history: a fix's friction review plays after the run it fixed",
      seq.index(("regression", 0)) < seq.index(("friction", 0)) < seq.index(("regression", 1)), str(seq))
check("busy: S on the hand-over once QA accepted",
      process.busy({"step": "done", "qa": {"accepted": "x"}, "sync": {"runs": [{"session": "s", "started": now}]}})
      == {"handoff": ["S"]})
check("busy: S where the merge waits once handed over",
      process.busy({"step": "done", "handoff": True, "sync": {"runs": [{"session": "s", "started": now}]}})
      == {"merge_wait": ["S"]})
# Every block a sync runs ahead of is lit, and carries S, on the glance: it
# draws no block for the sync.
with process.configured({}):
    for nid in process.NODES:
        if "S" in process.NODES[nid][5] and nid in process.POSITIONS:
            small = process.POSITIONS[nid]
            n = process.OVERVIEW_NODES.get(small)
            check("S of %s on %s" % (nid, small), bool(n) and "S" in n[5], small)
# Every map at its drawn size: none stretched past it, so all share a scale.
check("every map at one scale", all('style="max-width:%dpx;' % d.width in d.svg()
                                    for d in (process.Diagram(*ns) for ns in process.node_sets())))
def drawn_right(where):
    """Every map as drawn under the config in force: the rules held."""
    # Ways back into one block share its trunk: one channel, one way in, the
    # arrow on the one from lowest down.
    maps = [(ns, process.Diagram(*ns)) for ns in process.node_sets()]
    for ns, d in maps:
        groups = {}
        for i, e in enumerate(d.edges):
            # Ways back on the right, detours on the left: a trunk each per block.
            if d.is_back(e) or e in d.detours:
                side = "back" if d.is_back(e) else "east" if e in d.east else "west"
                groups.setdefault((side, e[1]), []).append(i)
        for target, ways in groups.items():
            check("%s/%s: one way in by its trunk: %s" % (where, ns[0], target),
                  len({d.channel_x[i] for i in ways}) == 1 and len({d.entry.get(i, 0) for i in ways}) == 1
                  and sum(1 for i in ways if i not in d.trunk) == 1, str(ways))
            # Which way each goes is told where they meet: an arrow into the
            # trunk on each joining, a chevron up the trunk above it.
            carrier = next(i for i in ways if i not in d.trunk)
            check("%s/%s: the ways into %s's trunk show their way" % (where, ns[0], target),
                  all('url(#join' in d.edge(d.edges[i], i) for i in d.trunk if i in ways)
                  and d.edge(d.edges[carrier], carrier).count('class="chev"') == len(ways) - 1)
    # Each gap between rows as tall as what runs in it: a turn 12 px off the
    # block it enters, the levels under the row above clear of the turns, and
    # no gap taller than it needs.
    for ns, d in maps:
        for i, e in enumerate(d.edges):
            if i in d.turn:
                rb = d.nodes[e[1]][1]
                check("%s/%s: way %d turns clear of %s" % (where, ns[0], i, e[1]), d.top[rb] - d.turn[i] >= 12)
                ups = [d.level[j] for j, f in enumerate(d.edges) if j in d.level and d.nodes[f[0]][1] == rb - 1]
                check("%s/%s: way %d turns below the levels over it" % (where, ns[0], i),
                      all(d.turn[i] - y >= 6 for y in ups), str((d.turn[i], ups)))
        # No line crosses a block but its own two ends.
        boxes = {nid: (d.center(nid)[0] - process.NODE_W / 2, d.top[n[1]],
                       d.center(nid)[0] + process.NODE_W / 2, d.top[n[1]] + process.NODE_H)
                 for nid, n in d.nodes.items()}
        for i, e in enumerate(d.edges):
            drawn = " ".join(re.findall(r'class="line[^"]*" d="M([^"]*)"', d.edge(e, i)))
            pts = [tuple(map(float, q.split())) for q in re.findall(r"-?[\d.]+ -?[\d.]+", drawn)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                for nid, (lf, tp, rt, bt) in boxes.items():
                    if nid not in e[:2]:
                        check("%s/%s: way %d (%s to %s) clear of %s" % (where, ns[0], i, e[0], e[1], nid),
                              not (min(x1, x2) < rt - 1 and max(x1, x2) > lf + 1
                                   and min(y1, y2) < bt - 1 and max(y1, y2) > tp + 1))
        gaps = [b - a - process.NODE_H for a, b in zip(d.top, d.top[1:])]
        # A row rises into the one above where nothing turns between them
        # (_rows), its runs still clear of the blocks above.
        check("%s/%s: rows no farther apart than they need" % (where, ns[0]),
              not gaps or (min(gaps) >= -process.NODE_H / 2 + 14 and max(gaps) < 60), str(gaps))
        # A risen row leaves the strip under the blocks above to the page's line,
        # and in one lane room for the letters over the block below.
        for nid, n in d.nodes.items():
            for mid, m in d.nodes.items():
                if m[1] == n[1] + 1 and m[0] == n[0] and n[2] not in ("start", "end"):
                    check("%s/%s: %s clear under %s" % (where, ns[0], mid, nid),
                          d.top[m[1]] - (d.top[n[1]] + process.NODE_H) >= process.UNDER + 14)
        # A way's label along its row clear of the blocks above it and the
        # page's line under them.
        for i, e in enumerate(d.edges):
            if i in d.corner and e[2] and d.nodes[e[0]][1]:
                r, side = d.nodes[e[0]][1], d.corner[i]
                x = d.center(e[0])[0] + side * (process.NODE_W / 2 + 6)
                lo, hi = sorted((x, x + side * 6 * len(e[2])))
                for mid, m in d.nodes.items():
                    mx = d.center(mid)[0]
                    if m[1] == r - 1 and m[2] not in ("start", "end") \
                            and lo < mx + process.NODE_W / 2 and hi > mx - process.NODE_W / 2:
                        check("%s/%s: way %d's label clear of %s" % (where, ns[0], i, mid),
                              d.center(e[0])[1] - 15 >= d.top[r - 1] + process.NODE_H + process.UNDER)


drawn_right("model")
for name, cfg in configs + [("no suites", dict(process.example_config(), regression={})),
                            ("no local database", dict(process.example_config(), database={}))]:
    with process.configured(cfg):
        drawn_right(name)
# The legend's letters lead to their maps, on the printed page and a feature's.
for name in ("friction", "workshop", "regression", "sync"):
    check("the legend links to the %s map" % name,
          'href="#map-%s"' % name in process.LEGEND and 'id="map-%s"' % name in process.doc()
          and 'id="map-%s"' % name in page)
# A way into the epilogue from each place the run stops after its steps and
# writes the issue's status (run_status in remind_prod) — not the merge's
# wait, which the labels and the pull request say — and the status prompt
# claims no end it has not been told of.
check("the status is written where the map says",
      {a for a, b, _l, _k in process.EDGES if b in ("epilogue", "epi_preview")} == {"preview", "ship", "prod"}
      and len([e for e in process.EDGES if e[1] == "epilogue"]) == 2
      # The copies beside the stops lead nowhere: the run stops there.
      and not any(a == "epi_preview" for a, *_ in process.EDGES)
      and "Waiting for the merge of PR" in read("sclaude", "lib", "deploy.sh")
      and read("sclaude", "lib", "deploy.sh").count('run_status "$slug"')
      - read("sclaude", "lib", "deploy.sh").count('STATUS_LABELS_ONLY=1 run_status') == 7
      and 'status_green_again "$slug"' in read("sclaude", "lib", "deploy.sh"))
status_md = read("sclaude", "prompts", "status.md")
check("the status prompt claims no end of the cycle",
      "through the whole cycle" not in status_md and "closed feature" not in status_md
      and "never write that the cycle is through" in status_md)
check("a map's card hugs its map", ".card:has(> svg.map){width:fit-content" in process.STYLE)
# The clean-up asks: yes removes, no keeps it all.
check("the clean-up has its yes and its no",
      {(b, l) for a, b, l, _k in process.EDGES if a == "cleanup"} == {("end", "yes"), ("kept", "no")})
check("sclaude done is the run's, not the person's", process.NODES["done_cmd"][0] == "sclaude")
check("no sync block on the glance",
      not any("sync" in n[3] for n in process.OVERVIEW_NODES.values()))
broken = {"step": "done", "feature": "x", "handoff": True,
          "sync": {"runs": [{"session": "s", "started": "2020-01-01T00:00:00+00:00"}]}}
check("stalled: a sync broken off after the steps stands still on its block",
      list(process.stalled(broken, "OPEN")) == ["merge_wait"]
      and "sclaude sync x" in process.stalled(broken, "OPEN")["merge_wait"]["S"])
check("stalled: one going, or broken off in a step, is not",
      process.stalled(dict(broken, sync={"runs": [{"session": "s", "started": now}]}), "OPEN") == {}
      and process.stalled(dict(broken, step="code"), "OPEN") == {})
check("stalled: nothing once the pull request is merged or closed, or nothing changed",
      process.stalled(broken, "MERGED") == {} and process.stalled(broken, "CLOSED") == {}
      and process.stalled(dict(broken, no_change=True), "OPEN") == {})
check("commands light the blocks of the maps of their own",
      "fix_local" in process.WHEN["with friction logged"] and "sync" in process.WHEN["always"])
check("the small maps sum the maps of their own", "['detail', 'regression', 'ahead']" in page)

check("a letter says why it is on its block", process.badge_why("preview", "R").startswith("R — the preview suite")
      and process.badge_why("o_code", "R") == process.badge_why("code", "R")
      and process.badge_why("epilogue", "W").startswith("W — "))
check("the letters carry their why to hover", '<title>R — after your yes' in process.doc())
notes = process.busy_notes({"step": "code", "regression": {"local": {"status": "running", "started": now,
                                                                      "attempts": "1"}}})
check("a running suite says since when and after how many fixes",
      "local suite, running since" in notes["code"]["R"] and "fixing attempts used: 1" in notes["code"]["R"], str(notes))
two = process.busy_notes({"friction": {"code-1": {"runs": [{"session": "f", "started": now}]},
                                       "review-2": {"runs": [{"session": "g", "started": now}]}}})
check("an F names the review of its own block", "code-1" in two["code"]["F"] and "review-2" in two["review"]["F"], str(two))

def labels(name, gate):
    with process.configured(process.example_config()):
        sets = dict((n, (l, nd, e)) for n, l, nd, e in process.node_sets())
        lanes, nodes, edges = sets[name]
        svg = process.Diagram(name, lanes, nodes, edges).svg()
    out = []
    for i, e in enumerate(edges):
        if e[0] == gate and e[2]:
            m = re.search(r'data-key="e:%s:%d">.*?<text class="el" x="([\d.]+)" y="([\d.]+)" text-anchor="(\w+)"'
                          % (name, i), svg, re.S)
            out.append((float(m.group(1)), float(m.group(2)), m.group(3)))
    return out
for name, gate in (("detail", "ship"), ("regression", "prod_ok"), ("friction", "f_decide")):
    got = labels(name, gate)
    # Two labels on one side of the block, at one x, need a line of 10.5 px.
    apart = all(abs(a[1] - b[1]) >= 11 for i, a in enumerate(got) for b in got[i + 1:]
                if a[2] == b[2] and abs(a[0] - b[0]) < 60)
    check("%s: the ways out of %s are labelled apart" % (name, gate), apart, str(got))
check("a friction review open says which and that it holds the step",
      "code-1" in process.busy_notes({"friction": {"code-1": {"runs": [{"session": "f", "started": now}]}}})
      ["code"]["F"])
check("_flow hands the notes to the page", '"notes": notes' in read("sclaude", "lib", "actions.sh"))
check("the page offers the metrics by checkboxes, each with the whole feature's total",
      'class="metrics"' in page and 'value="input"' in page and 'value="cost"' in page
      and page.count('class="mt-total"') == 3)
check("an answer to sclaude and a command go into the history",
      "history_add \"$ASK_TREE/.sclaude/local/feature/state.json\" ask answered" in read("sclaude", "lib", "io.sh")
      and "history_command \"$wt\"" in read("sclaude", "lib", "state.sh")
      and 'SCLAUDE_COMMAND="${1:-menu}"' in sclaude
      and 'export SCLAUDE_RUN="${SCLAUDE_RUN:-' in sclaude and "SCLAUDE_REEXEC" not in sclaude)
check("the player pauses the arrow too", "animation-play-state:paused" in process.PLAY_STYLE)
check("the player pauses the time, not only the steps",
      "if (!paused) left -=" in process.PLAY_SCRIPT and "if (!paused) gone +=" in process.PLAY_SCRIPT)
for m in ("detail", "overview", "workshop", "friction"):
    check("page plays the %s map" % m, 'data-play="%s"' % m in page)
check("page chooses the friction and the workshop passes",
      'data-pass="friction"' in page and 'data-pass="workshop"' in page)
check("cmd_flow sends the history", "process.history(data, process.read_history(state)" in read("sclaude", "lib", "actions.sh")
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
