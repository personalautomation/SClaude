# The map a project's config draws: what each block needs, the variants a
# setting picks, and where each command of sclaude stands on the map.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import json
import os

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_model


# --- the map a project's config draws ---------------------------------------
#
# A project's map shows its own cycle, not every one sclaude can run: the
# review on CI or on this machine, QA on a board or none, a merge by a
# person or by sclaude. The model above holds them all; for_config takes out
# what a config does not run (NEEDS), carries the flow past a block taken
# out (PASS), and puts in the words a setting changes (VARIANTS). A block or
# an arrow not in NEEDS is on every project's map.

# A block, or an arrow by (from, to), and the setting it needs: (name,
# values). An arrow named here is not carried past a block taken out — it
# is one way of a choice, and the choice drops it.
NEEDS = {
    "ci_review": ("review", {"github"}),
    "local_pass": ("review", {"local"}),
    ("draft_pr", "ci_review"): ("review", {"github"}),
    ("draft_pr", "local_pass"): ("review", {"local"}),
    "f_away": ("review", {"local"}),
    ("f_rules", "f_away"): ("review", {"local"}),
    ("f_away", "f_review"): ("review", {"local"}),
    # Off, or local with the search ended (no pass runs on the first entry).
    ("draft_pr", "review_found"): ("review", {"off", "local"}),
    # A review on this machine writes no round marker: no round gate, the
    # session goes straight to step 4's close.
    "round": ("review", {"github", "off"}),
    ("review", "review_close"): ("review", {"local"}),
    "r_local": ("regression.local", {True}),
    "r_stop": ("regression.local", {True}),
    "r_preview": ("regression.preview", {True}),
    "r_prod": ("regression.prod", {True}),
    # A badge by (block, letter): R only where that stage has a suite.
    ("code", "R"): ("regression.local", {True}),
    ("review", "R"): ("regression.local", {True}),
    ("review_close", "R"): ("regression.local", {True}),
    ("preview", "R"): ("regression.preview", {True}),
    ("prod", "R"): ("regression.prod", {True}),
    "reg_local": ("regression.local", {True}),
    "fix_local": ("regression.local", {True}),
    "preview_ok": ("regression.preview", {True}),
    "fix_preview": ("regression.preview", {True}),
    "prod_ok": ("regression.prod", {True}),
    "rollback": ("regression.prod", {True}),
    "fix_prod": ("regression.prod", {True}),
    "hold_ways": ("regression.prod", {True}),
    "in_qa": ("board.qa", {True}),
    "qa_check": ("board.done", {True}),
    "qa_verdict": ("board.done", {True}),
    "merge": ("merge", {"both", "auto"}),
    "o_ghreview": ("review", {"github", "local"}),
    "o_qa": ("board.done", {True}),
    # ship: off never deploys: the yes and what follows it go.
    ("ship", "prod"): ("ship", {"ask", "auto"}),
    "prod": ("ship", {"ask", "auto"}),
}

# Where the flow goes on when a block is taken out: an arrow into it is
# carried to this one, and on down the chain while that one is out too.
PASS = {
    "ci_review": "review_found", "local_pass": "review_found",
    "reg_local": "pr", "preview_ok": "in_qa", "in_qa": "qa_check",
    "qa_check": "qa_verdict", "qa_verdict": "handoff", "prod_ok": "epilogue",
    "merge": "merge_wait",
    "o_ghreview": "o_review", "o_qa": "o_merge",
}

# The words, and for a few the lane, a setting changes: block -> [(name,
# values, {field: value})], the first that matches taken. Fields: lane,
# row, kind, title, text, details. A block moved to another lane takes a row
# of its own there when the one it had is taken.
VARIANTS = {
    "merge": [("merge", {"auto"}, {
        "lane": "sclaude", "row": 22.5, "title": "Merged by sclaude",
        "text": "merge: auto — once QA passed and GitHub says the way is clear",
        "details": "With merge set to auto, sclaude merges the pull request itself once QA passed and GitHub says the way is clear; a red check of the merge with main holds it until the branch or main moves."}),
              ("merge", {"both"}, {"text": "offered here once QA passed, or merge it on GitHub"})],
    "merge_wait": [("merge", {"github"}, {
        "text": "merge it on GitHub; polled every 30 s, main checked every 2 min"})],
    "qa_check": [("qa", {"auto"}, {
        "lane": "sclaude", "title": "Accepted by sclaude",
        "text": "qa: auto — moved to Done once the preview regression is green",
        "details": "With qa set to auto, sclaude moves the issue to Done itself once the preview regression is green; a person can still hand it back from the board."}),
                 ("qa", {"both"}, {
        "text": "on the preview, ticking them in the issue — or a key in sclaude's wait"})],
    "prepare": [("database.local", {False}, {
        "text": "worktree from origin/main, branch feat/<slug>, its own dev server"})],
    "prod": [("database.promote", {False}, {
        "text": "vercel --prod, then the production regression"})],
    "o_ghreview": [("review", {"local"}, {
        "lane": "sclaude", "title": "Local review", "text": "passes on this machine"})],
    "o_qa": [("qa", {"auto"}, {"lane": "sclaude", "title": "QA: auto", "text": "accepted when the preview is green"})],
    # The demo for QA is recorded only where a person does QA; with qa: auto
    # it is brought up to the code before the last epilogue instead
    # (demo_refresh in demo.sh).
    "code": [("demo", {"off"}, {
        "text": "builds it, checks it in Chrome, commits with Requirement: ACn",
        "details": "A fresh session builds from the plan, checks the result in Chrome at the feature's own address, and commits with a Requirement: ACn footer naming the criterion each commit serves. It closes with a report criterion by criterion. demo: off — no demo video is recorded."})],
    "works": [("demo", {"off"}, {
        "text": "the report, then Accept in the session's dialog, or remarks to it"})],
    "preview_ok": [("demo", {"off"}, {
        "details": "Green: the issue goes to In QA. Red: no label is claimed, the cycle goes back to step 4 and a fixing session opens there."}),
                   ("qa", {"auto"}, {
        "details": "Green: the issue goes to In QA. Red: no label is claimed, the cycle goes back to step 4 and a fixing session opens there."})],
    "epilogue": [("demo", {"off"}, {
        "details": "A short session writes a Current status comment on the issue and on every parent up the chain, and Current behaviour where the product now differs from a description. Labels deployed-preview and deployed-prod are set by how each stage ended."}),
                 ("qa", {"auto"}, {
        "details": "A short session writes a Current status comment on the issue and on every parent up the chain, and Current behaviour where the product now differs from a description. Labels deployed-preview and deployed-prod are set by how each stage ended. Nobody does QA here, so before the last one, when the product's code changed since the feature's demo, the demo is recorded again for the issue — or kept, when nothing a user meets changed — and what it found wrong in the product is printed."})],
    "o_prod": [("ship", {"off"}, {"kind": "task", "title": "Not shipped from here", "text": "ship: off — production is yours to deploy"}),
               ("regression.prod", {False}, {"kind": "task", "text": "shipped; no suite runs there"}),
               ("ship", {"auto"}, {"text": "shipped by sclaude; a red suite, not rolled back: held here"})],
    "ship": [("ship", {"auto"}, {
        "title": "Ship to production?",
        "text": "ship: auto — asked only when a gate was passed over, or others' code rides along",
        "details": "With ship set to auto, sclaude ships once the merge is in without asking — the deployment production runs now is recorded first, for a rollback. The question comes back where QA or a check was passed over on the way (merged before the preview went green or QA accepted it, or merged as a change nothing deploys that carried more), and where other features' code between production and main would go out with it."}),
             ("ship", {"off"}, {
        "title": "Not shipped from here",
        "text": "ship: off — the issue closes as merged and accepted",
        "details": "With ship set to off, sclaude never deploys production: once the merge is in the issue closes as merged and accepted, and the epilogue and the clean-up follow. Shipping is cd <repo> && vercel --prod, by hand."})],
    "r_preview": [("previewRegression", {"smoke"}, {
        "text": "the product's smoke set, against the preview, before QA"})],
    "r_prod": [("prodRegression", {"smoke"}, {
        "text": "the product's smoke set, against production, after the ship"})],
    "o_preview": [("regression.preview", {False}, {"kind": "task", "text": "deployed"})],
    # No local suite: step 4 closes on the pull request alone.
    "review_close": [("regression.local", {False}, {
        "title": "All closed?",
        "details": 'Leaving step 4 closes it only when nothing is open — no unresolved thread, no running or red check. Otherwise sclaude waits and what is open goes back to a session without a question; [s] or ⏭ makes the next session the last for new findings. A session you left yourself (/exit, Ctrl-C) with [g] off holds step 4 open until the next sclaude <name>. A session sclaude closed on its done marker — always so for a review on this machine, which writes no round marker — goes back by whose work is open: threads from before it, or a red check, to the same session; only new ones to the same session while its context is under 40% and its last request under 55 minutes old, else to a fresh one. With [g] on the rounds go on even then (30 a step 4, then it asks), a pass that did not run is tried again ten times with growing pauses, and after the search ended the fixes are checked. A night session itself resolves a minor finding the review posted, with no reply under it yet, and replies saying so; the others it leaves for you to confirm: sclaude asks whether to go through them now, and on your yes they go back to a fresh session that asks about each and, on your yes, replies and resolves them; the rest of your threads wait for your hand on GitHub.'})],
    "o_merge": [("merge", {"auto"}, {"lane": "sclaude", "text": "by sclaude: merge auto"}),
                ("merge", {"github"}, {"text": "yours, on GitHub"})],
}


def setting(cfg, name):
    """A setting the map depends on, read as sclaude reads it
    (project_review_mode, project_flow_mode, project_regression_parts, the
    board's columns in project.sh)."""
    cfg = cfg or {}
    if name == "review":
        return cfg.get("review") if cfg.get("review") in ("local", "off") else "github"
    if name in ("qa", "merge"):
        mode = cfg.get(name)
        return mode if mode in ("github", "both", "auto") else ("both" if name == "merge" else "github")
    if name in ("previewRegression", "prodRegression"):
        return cfg.get(name) if cfg.get(name) in ("smoke", "none") else "full"
    if name == "ship":
        return cfg.get("ship") if cfg.get("ship") in ("auto", "off") else "ask"
    if name == "demo":
        return "off" if cfg.get("demo") == "off" else "on"
    if name.startswith("regression."):
        # As project_regression_parts runs them: a deployed stage set to
        # none has no suite, and one set to smoke runs the smoke list when
        # the product declares one.
        stage = name.split(".", 1)[1]
        lists = cfg.get("regression") or {}
        # Nothing ships under ship: off, so production's suite never runs.
        if stage == "prod" and setting(cfg, "ship") == "off":
            return False
        if stage in ("preview", "prod"):
            mode = setting(cfg, stage + "Regression")
            if mode == "none":
                return False
            if mode == "smoke" and lists.get("smoke"):
                return True
        return bool(lists.get(stage))
    if name in ("board.qa", "board.done"):
        # done is what QA is waited for by (qa_wait); qa only where the issue
        # is moved to before it (issue_qa_ready).
        columns = (cfg.get("board") or {}).get("columns") or {}
        return bool(columns.get("done") and (name == "board.done" or columns.get("qa")))
    if name.startswith("database."):
        return bool((cfg.get("database") or {}).get(name.split(".", 1)[1]))
    return None


def _needs(cfg, key):
    need = NEEDS.get(key)
    return not need or setting(cfg, need[0]) in need[1]


def for_config(cfg, nodes, edges):
    """One map as cfg runs it: the blocks it needs, the arrows carried past
    the ones it does not, the words it changes; rows left empty closed up."""
    kept = {}
    for nid, node in nodes.items():
        if not _needs(cfg, nid):
            continue
        lane, row, kind, title, text, flags = node
        for name, values, fields in VARIANTS.get(nid, []):
            if setting(cfg, name) in values:
                lane, kind = fields.get("lane", lane), fields.get("kind", kind)
                row = fields.get("row", row)
                title, text = fields.get("title", title), fields.get("text", text)
                break
        flags = "".join(f for f in flags if _needs(cfg, (nid, f)))
        kept[nid] = (lane, row, kind, title, text, flags)
    out, seen = [], set()
    for a, b, label, kind in edges:
        if a not in kept or not _needs(cfg, (a, b)):
            continue
        if b not in kept:
            if (a, b) in NEEDS:
                continue
            hops = 0
            while b not in kept and b in PASS and hops < len(PASS):
                b, hops = PASS[b], hops + 1
            if b not in kept or b == a:
                continue
            kind = "" if kind == "msg" else kind
        if (a, b) in seen:
            continue
        seen.add((a, b))
        out.append((a, b, label, kind))
    rows = {r: i for i, r in enumerate(sorted({n[1] for n in kept.values()}))}
    kept = {nid: (n[0], rows[n[1]]) + n[2:] for nid, n in kept.items()}
    return kept, out


def _variant_details(cfg):
    details = dict(process_model.DETAILS)
    for nid, variants in VARIANTS.items():
        for name, values, fields in variants:
            if setting(cfg, name) in values:
                if "details" in fields:
                    details[nid] = fields["details"]
                break
    return details


def config_of(tree):
    """The project's config as sclaude reads it for a tree (project_config,
    project_get): the main checkout's, this machine's choices over it, with a
    key it lacks taken from the tree's own copy. {} when neither can be read."""
    main = tree
    try:
        with open(os.path.join(tree, ".git")) as fh:
            line = fh.read().strip()
        if line.startswith("gitdir:"):
            gitdir = line.split(":", 1)[1].strip()
            main = os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(gitdir))))
    except OSError:
        pass
    def read(where):
        try:
            with open(os.path.join(where, ".sclaude", "config.json")) as fh:
                got = json.load(fh)
            return got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            return {}

    def fill(first, second):
        # Key by key down every path, as project_get falls back: the first's
        # value, the second's where the first has none (null is none).
        out = dict(second)
        for key, value in first.items():
            if value is None:
                continue
            if isinstance(value, dict) and isinstance(second.get(key), dict):
                out[key] = fill(value, second[key])
            else:
                out[key] = value
        return out
    first, second = read(main), (read(tree) if main != tree else {})
    # This machine's choices, outside git, over the main checkout's.
    import config_menu
    first.update(config_menu.overrides(os.path.join(main, ".sclaude", "config.json")))
    cfg = fill(first, second)
    # A section read whole (project_config_with): the board's, from the file
    # that has it.
    if "board" in first or "board" in second:
        cfg["board"] = first.get("board") if first.get("board") is not None else second.get("board")
    return cfg


def on_map(nid):
    """A place on the map drawn now: the block itself, or the one the flow
    goes on to when this config draws none (PASS). "" when neither."""
    drawn = all_nodes()
    hops = 0
    while nid and nid not in drawn and hops < len(PASS):
        nid, hops = PASS.get(nid, ""), hops + 1
    return nid if nid in drawn else ""


EXAMPLE_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.example.json")


def example_config():
    try:
        with open(EXAMPLE_CONFIG) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# Commands: (command, verb in the action list or "", when it applies, what it
# does, the node it leads to or "").
COMMANDS = [
    ("sclaude", "", "always", "the menu: features in progress", ""),
    ("sclaude new [name]", "", "always", "a new feature at step 1", "new"),
    ("sclaude <name>", "resume", "always", "continue: the current step, or the end of the cycle", "@here"),
    ("sclaude status", "", "always", "a table of every feature and its step", ""),
    ("sclaude doctor", "", "always", "what this machine lacks, with the fix", ""),
    ("sclaude config", "", "always", "the project's config, explained; the review mode", ""),
    ("sclaude actions [name]", "", "always", "the action list of one feature", ""),
    ("sclaude dev [name]", "dev", "always", "start the dev server (--stop stops it)", "prepare"),
    ("sclaude sync <name>", "sync", "always", "merge origin/main in; a conflict opens the sync session", "merge_check"),
    ("sclaude replan <name>", "replan", "before the cycle ends", "back to step 1 in a new conversation; the code stays", "plan"),
    ("sclaude return <name> [reason]", "return", "a finished feature", "back to step 4 with what was said since", "review"),
    ("sclaude issue <name>", "issue", "always", "link or create the feature's issue", "new"),
    ("sclaude news <name>", "news", "with a pull request", "what moved on the PR since the last session", "review_found"),
    ("sclaude preview <name>", "preview", "after step 1", "deploy a preview of the branch", "preview"),
    ("sclaude rollback <name>", "rollback", "once production carried it", "the previous release back; a red one sends the fix to step 4", "rollback"),
    ("sclaude regression <name>", "regression", "always", "the local regression, the one steps 2 and 4 close on", "reg_local"),
    ("sclaude regression <name> prod", "regression-prod", "production red and carrying it", "production's suite again; green, or no production suite, lifts the hold", "prod_ok"),
    ("sclaude friction <name>", "friction", "with friction logged", "review what the safety rules refused", "f_review"),
    ("sclaude done <name>", "done", "at step 4 or done", "the retro, then the clean-up after the merge", "done_cmd"),
    ("sclaude reset <name>", "reset", "before the cycle ends", "start the step over, forgetting its conversation", "@here"),
    ("sclaude drop <name>", "drop", "always", "abandon the feature, each trace asked about", ("cleanup", "end")),
    ("sclaude epilogue [name]", "", "an epilogue broken off", "write the status into the issue", "epilogue"),
    ("sclaude deferred", "", "monthly, offered", "the review of the friction put off", "f_monthly"),
    ("sclaude review-stats", "", "always", "what review sessions cost in context", "review"),
    ("sclaude review-report <name>", "", "with review rounds", "is the review still worth it", "review"),
    ("sclaude checks [pr]", "", "in a session", "wait for the checks of the pushed head", "review_close"),
    ("sclaude core-open", "", "in a session", "let the session write sclaude in its workshop", "w_open"),
    ("sclaude core-ready", "", "in a session", "mark the workshop's change ready to publish", "w_ready"),
    ("sclaude propose", "", "a developer's branch", "send dev/<name>'s commits to sclaude as a PR", "w_pr"),
    ("sclaude workshop", "", "always", "a session that changes sclaude with you, in a worktree of its own", ""),
    ("sclaude core-send", "", "a workshop change held", "send the tree's held change to sclaude after all", "w_send"),
    ("sclaude update", "", "always", "take sclaude's main now, whatever sclaude.update says", ""),
]

def places(target):
    """A command's places: its target is one node, several (a tuple), "@here"
    or nothing."""
    if not target:
        return []
    return list(target) if isinstance(target, tuple) else [target]


# Verbs in the action list with no command of their own.
ACTION_ONLY = {"back", "nothing"}


def all_nodes():
    return {nid: n for _name, _lanes, nodes, _edges in node_sets() for nid, n in nodes.items()}


def node_sets_named():
    return {name: nodes for name, _lanes, nodes, _edges in node_sets()}


def node_sets():
    return [("detail", process_model.LANES, process_model.NODES, process_model.EDGES), ("overview", process_model.OVERVIEW_LANES, process_model.OVERVIEW_NODES, process_model.OVERVIEW_EDGES),
            ("workshop", process_model.WORKSHOP_LANES, process_model.WORKSHOP_NODES, process_model.WORKSHOP_EDGES),
            ("friction", process_model.FRICTION_LANES, process_model.FRICTION_NODES, process_model.FRICTION_EDGES),
            ("regression", process_model.REGRESSION_LANES, process_model.REGRESSION_NODES, process_model.REGRESSION_EDGES),
            ("sync", process_model.SYNC_LANES, process_model.SYNC_NODES, process_model.SYNC_EDGES)]
