# How a feature went: its history read back into the places it passed,
# with the ways back, the fixes and the workshop.
#
# Part of sclaude/lib/process.py, which re-exports it.

import datetime

import process_config, process_costs, process_model, process_position


# --- how a feature went ------------------------------------------------------
#
# The feature's history, history_add's and session_runs' lines (state.sh) in
# the file beside its state, played back on the map: each place it stood on,
# how long, and the way it went on. The file lives in the worktree's
# .sclaude/local, which git never carries and the clean-up removes with the
# tree; a feature begun before it has no history to play.
#
# What it gives the page: `visits`, the detailed map's places in order —
# those the history names, with the places between them filled in along the
# map's shortest way, and the time between two places given to the first
# check or person on the way — and `passes`, the friction reviews and the
# workshop's publications, each a way through its own map. A visit
# {"pass": [map, i]} is where the feature went off to one of those.

HISTORY_FILE = "history.jsonl"
# The local review's journal beside it, for the passes' conversations
# (local_review.sh names it, review_report.py reads it too).
LOCAL_JOURNAL = "local-review-rounds.jsonl"
# What the transcripts said of each conversation, kept beside the history.
TRANSCRIPT_CACHE = "transcripts.json"
TRANSCRIPT_FRESH = 60

# A step closed: the check it closes on.
STEP_CLOSE = {"plan": "plan_check", "pr": "pr_check", "review": "review_close"}
STAGE_NODE = {"local": "reg_local", "preview": "preview", "prod": "prod"}
# Who the gap before the next place is spent on: a check, a person, a wait.
WAITS_ON = ("user", "gate", "wait", "hold")
# The most places filled in between two the history names.
FILL_MAX = 5


def _when(text):
    try:
        at = datetime.datetime.fromisoformat(str(text or ""))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)


def _row(at, what, op, **extra):
    row = {"at": at, "what": what, "op": op}
    row.update({k: v for k, v in extra.items() if v})
    return row


def history_rows(lines):
    """The file's rows in the order they happened; one written in the same
    second as another stays after it."""
    rows = [r for r in lines if isinstance(r, dict) and _when(r.get("at")) and r.get("what")]
    return [r for _i, r in sorted(enumerate(rows), key=lambda p: (_when(p[1]["at"]), p[0]))]


# The epilogue's copy on the whole map, beside the preview: a status session
# run_status marked as the preview's (`about`), red or written again green.
# A step aside, from wherever the run or the menu wrote it before the merge,
# and never a deviation: the way on goes from the place before it.
COPIES = {"epi_preview"}

# Steps whose session, opened again right after one of its own, took up one
# that broke off: nothing ran between, and no way round is played. Each closes
# on a check of its own (STEP_CLOSE), entered when it finished; the code's
# "no" from you is not recorded, and the review's rounds do go round.
REOPENED = ("plan", "pr")


def _graph(edges):
    out = {}
    for a, b, _label, _kind in edges:
        out.setdefault(a, []).append(b)
    return out


def _way(graph, a, b):
    """The shortest way along the map from a to b, both ends included; from
    a place back to itself, the shortest way round. [a, b] when none."""
    queue, seen = [[a, x] for x in graph.get(a, [])], {a} if a != b else set()
    while queue:
        way = queue.pop(0)
        if way[-1] == b:
            return way
        if way[-1] in seen:
            continue
        seen.add(way[-1])
        queue += [way + [x] for x in graph.get(way[-1], []) if x not in seen or x == b]
    return [a, b]


def _seconds(a, b):
    ta, tb = _when(a), _when(b)
    return max(0, int((tb - ta).total_seconds())) if ta and tb else None


class _Places:
    """The detailed map's places, as the rows enter and leave them."""

    def __init__(self):
        self.list, self.open = [], {}
        # Where a stay left open by an interrupted run (a Ctrl-C writes no
        # end) is taken to have ended: the last line of the sclaude run that
        # opened it, or of any run where the lines name none.
        self.last, self.last_of, self.run = None, {}, None

    def enter(self, node, at, key=None, session=None):
        key = key or node
        place = self.open.get(key)
        if place:
            # A conversation opened with no end before it and nothing else
            # between: the review carrying on into its next round in the
            # same one, or one opened in place of a conversation that died
            # (the sync's). One stay, the new conversation a sitting of its
            # own, so that its drop takes back only what it added.
            if session and place.get("session") and self.list[-1] is place:
                place["sittings"][-1][1] = at
                place["sittings"].append([at, None])
                place.setdefault("before", []).append(place["session"])
                place["session"] = session
                place["run"] = self.run or place.get("run")
                return
            # Left open while the feature went elsewhere: it ended where
            # the next place began - not a pass, which runs inside it.
            after = self.list[self.list.index(place) + 1:]
            # A wait is the feature's, not a run's: entered again with no
            # place between, it lasted until now.
            self.leave(key, next((p["from"] for p in after if "n" in p and p.get("from")),
                                 (self.last_of.get(place.get("run")) or self.last) if place.get("session")
                                 else None) or at)
        self.list.append({"n": node, "from": at, "to": None, "session": session, "sittings": [],
                          "run": self.run})
        self.open[key] = self.list[-1]
        self.list[-1]["sittings"].append([at, None])

    def leave(self, key, at):
        place = self.open.pop(key, None)
        if place:
            place["to"] = at
            place["sittings"][-1][1] = at

    def drop(self, key):
        """A conversation that never took place: no stay at all."""
        place = self.open.pop(key, None)
        if place:
            place["sittings"].pop()
            if not place["sittings"]:
                self.list.remove(place)
            else:
                place["session"] = place["before"].pop()
                place["to"] = place["sittings"][-1][1]

    def point(self, node, at):
        self.list.append({"n": node, "from": at, "to": at, "session": None, "sittings": []})

    def detour(self, kind, index, at):
        self.list.append({"pass": [kind, index], "from": at, "to": at})


def _friction_way(rows, workshop_sessions, now=None, cut=None):
    """A friction review's way through its map, from its rows."""
    ops = [r["op"] for r in rows]
    if "deferred" in ops:
        return [{"n": n} for n in ("f_trip", "f_log", "f_empty", "f_rules", "f_classify", "f_defer")]
    way = [{"n": n} for n in ("f_trip", "f_log", "f_empty", "f_rules")]
    sitting, outcome, verdict, session = None, "", "", ""
    for r in rows:
        if r["op"] == "held" and way[-1]["n"] != "f_away":
            way.append({"n": "f_away", "from": r["at"]})
        if r["op"] == "open":
            if way[-1]["n"] == "f_review":
                # Opened again, after a Ctrl-C as often as after a
                # conversation that died: the sitting before has no end that
                # can be told, and counts nothing rather than the whole gap.
                way[-1]["k"] = way[-1].get("k", 1) + 1
            else:
                way.append({"n": "f_review", "s": 0, "from": r["at"]})
            sitting, session = r["at"], r.get("session") or session
        elif r["op"] in ("end", "stall", "finish") and sitting:
            way[-1]["s"] += _seconds(sitting, r["at"]) or 0
            way[-1].setdefault(SPANS, []).append((sitting, r["at"]))
            way[-1]["to"] = r["at"]
            sitting = None
            if r["op"] == "stall":
                way.append({"n": "f_hold"})
        if r["op"] in ("finish", "end") and r.get("outcome"):
            outcome = r["outcome"]
        if r["op"] == "verdict":
            verdict = r.get("verdict", "")
    # A sitting left open: going on by sclaude's state, up to now; else it
    # ended unseen, where `cut` says (_unseen_end), a guess the page marks.
    if sitting and way[-1]["n"] == "f_review":
        end = now or cut and cut(sitting)
        if end and _when(end) > _when(sitting):
            way[-1]["s"] += _seconds(sitting, end) or 0
            way[-1].setdefault(SPANS, []).append((sitting, end))
            if not now:
                way[-1]["to"] = end  # a stay going on has no end yet
        way[-1]["live" if now else "unsure"] = True
    if not (outcome or verdict):
        return way
    if session in workshop_sessions:
        decided = "f_bug"
    elif verdict in ("lifted", "mixed") or outcome == "fixed":
        decided = "f_lift"
    else:
        decided = "f_deliberate"
    way += [{"n": "f_plan"}, {"n": "f_decide"}, {"n": decided}, {"n": "f_verdict"}]
    if outcome == "fixed":
        way.append({"n": "f_push"})
    way.append({"n": "f_next"})
    return way


# The sittings a stay's `s` adds up, (from, to) each: what the time metric
# lays side by side, so a minute two maps both timed counts once. Taken off
# the stays before the history goes out.
SPANS = "_spans"


def _timed(node, a, b):
    step = {"n": node, "from": a}
    if b:
        step.update({"to": b, "s": _seconds(a, b) or 0, SPANS: [(a, b)]})
    return step


def _regression_way(stage, rows, cut=None, now=None):
    """A stage's run through the regression map, each place with its time,
    so what it took is counted there and not on the step it came from. A run
    cut off ends where `cut`, a function of the moment it started, says
    (history's `unseen`); one going now (`now`) counts up to it."""
    gate = {"local": "reg_local", "preview": "preview_ok", "prod": "prod_ok"}[stage]
    way, run, fix = [{"n": "r_" + stage}], None, None
    for r in rows:
        what, op, at = r["what"], r["op"], r["at"]
        if what.startswith("regression."):
            if op == "start":
                run = at
            else:
                way.append(_timed(gate, run or at, at))
                run = None
                if op == "passed":
                    way.append({"n": "r_on"})
        elif what.startswith("fix."):
            node = "fix_" + stage
            if op == "start":
                fix = at
                way.append(dict(_timed(node, at, None), session=r.get("session")))
            elif way and way[-1]["n"] == node:
                way[-1].update(_timed(node, fix or at, at))
                if stage == "local":
                    way.append({"n": gate})
        elif what == "rollback.prod":
            way.append({"n": "rollback", "from": at, "to": at})
    if run and now:
        way.append(dict(_timed(gate, run, now), live=True))
    elif run:
        end = cut(run) if cut else None
        way.append(dict(_timed(gate, run, end if end and _seconds(run, end) else None), unsure=True))
    return way


def _sync_way(rows, now=None, cut=None):
    """A sync with main through its map: the check, the session's sittings,
    and the merge in once it settled."""
    way = [{"n": "y_when"}, {"n": "merge_check"}]
    sitting = None
    for r in rows:
        if r["op"] == "open":
            if way[-1]["n"] == "sync":
                # One opened in place of a conversation that died: that one
                # ended here, and this is a sitting of the same stay.
                if sitting:
                    way[-1]["s"] += _seconds(sitting, r["at"]) or 0
                    way[-1].setdefault(SPANS, []).append((sitting, r["at"]))
                way[-1]["k"] = way[-1].get("k", 1) + 1
            else:
                way.append({"n": "sync", "from": r["at"], "s": 0})
            sitting = r["at"]
        elif r["op"] == "drop" and sitting:
            # A conversation that never took place: no time, no sitting.
            sitting = None
            if way[-1].get("k", 1) > 1:
                way[-1]["k"] -= 1
        elif r["op"] in ("end", "finish", "stall") and sitting:
            way[-1]["s"] += _seconds(sitting, r["at"]) or 0
            way[-1].setdefault(SPANS, []).append((sitting, r["at"]))
            way[-1]["to"] = r["at"]
            sitting = None
        if r["op"] in ("finish", "close"):
            way += [{"n": "merge_check"}, {"n": "main_in"}, {"n": "y_on"}]
    # A sitting left open: going on by sclaude's state, up to now; else it
    # ended unseen, where `cut` says (_unseen_end), a guess the page marks.
    if sitting and way[-1]["n"] == "sync":
        end = now or cut and cut(sitting)
        if end and _when(end) > _when(sitting):
            way[-1]["s"] += _seconds(sitting, end) or 0
            way[-1].setdefault(SPANS, []).append((sitting, end))
            if not now:
                way[-1]["to"] = end  # a stay going on has no end yet
        way[-1]["live" if now else "unsure"] = True
    return way


WORKSHOP_START = ("w_find", "w_ask", "w_open", "w_change", "w_ready", "w_exit", "w_ready_gate")
WORKSHOP_OUT = {
    "blocked": ("w_leaks", "w_leak_ask", "w_held"), "held": ("w_leaks", "w_leak_ask", "w_held"),
    "left": ("w_back", "w_pending"), "red": ("w_leaks", "w_tests"),
    "declined": ("w_leaks", "w_tests", "w_send", "w_held"), "waits": ("w_leaks", "w_tests", "w_send"),
    "stopped": ("w_leaks", "w_tests", "w_send", "w_who"),
    "main": ("w_leaks", "w_tests", "w_send", "w_who", "w_main"),
    "pr": ("w_leaks", "w_tests", "w_send", "w_who", "w_pr"),
}


def _workshop_way(rows):
    """A session's change to sclaude, from the session's end to how its
    publication went."""
    way = list(WORKSHOP_START)
    for r in rows:
        if way[-1] == "w_pending" and r["op"] != "left":
            way += ["w_change", "w_ready", "w_exit", "w_ready_gate"]
        for n in WORKSHOP_OUT.get(r["op"], ()):
            if n != way[-1]:
                way.append(n)
    return [{"n": n} for n in way]


def _session_names(state):
    """What each conversation was: "2 · code", "friction code-1", "retro"."""
    names = {}
    for step, node in (state.get("steps") or {}).items():
        for run in process_position._runs(node):
            names[run.get("session")] = process_model.NODES.get(step, ("", "", "", step))[3]
    for key, node in (state.get("friction") or {}).items():
        for run in process_position._runs(node):
            names[run.get("session")] = "friction review " + key
    for what in ("sync", "retro", "epilogue"):
        for run in process_position._runs(state.get(what) if isinstance(state.get(what), dict) else None):
            names[run.get("session")] = process_config.all_nodes()[what][3]
    names.pop(None, None)
    return names


def _short(at):
    when = _when(at)
    return when.strftime("%d %b %H:%M") if when else ""


def history(state, lines, here=None, transcripts=None, pass_rows=None):
    """The feature's way through the maps, for the page to play, and what
    each place took (`metrics`) when the sessions' transcripts are given:
    a function from a session id to claude_usage.read's summary, or None."""
    rows = history_rows(lines)
    places = _Places()
    friction, workshop, regression, syncs = {}, {}, {}, {}
    last_run = {}
    merged = qa_open = False
    first = rows[0]["at"] if rows else None
    if first:
        places.point("new", first)
    for r in rows:
        what, op, at = r["what"], r["op"], r["at"]
        head, _, rest = what.partition(".")
        places.run = r.get("run")
        if head == "steps" and rest in process_model.NODES:
            if op == "open":
                places.enter(rest, at, "steps." + rest, r.get("session"))
            elif op == "drop":
                places.drop("steps." + rest)
            elif op in ("end", "stall", "finish"):
                places.leave("steps." + rest, at)
            if op in ("close", "finish") and rest in STEP_CLOSE:
                places.point(STEP_CLOSE[rest], at)
        elif what == "sync":
            # A sync is a pass on its own map: where it ran, and what it took.
            key = last_run.get("sync")
            # A new pass once the last one settled or never took place; one
            # left unfinished and taken up again goes on in its own.
            if op == "open" and (key is None or any(x["op"] in ("finish", "close")
                                                    for x in syncs[key])
                                 or [x["op"] for x in syncs[key]][-1:] == ["drop"]):
                key = last_run["sync"] = str(len(syncs))
                syncs[key] = []
                places.detour("sync", key, at)
            if key is not None:
                syncs[key].append(r)
        elif what in ("retro", "epilogue"):
            if op == "open":
                places.enter("epi_preview" if r.get("about") == "preview" else what,
                             at, what, r.get("session"))
            elif op == "drop" and what != "retro":
                places.drop(what)
            elif op in ("end", "stall", "finish", "drop"):
                # A retrospective nobody answered is dropped (retro.sh), but
                # its conversation took place.
                places.leave(what, at)
        elif head == "friction" and rest:
            if rest not in friction:
                friction[rest] = []
                if op != "empty":
                    places.detour("friction", rest, at)
            friction[rest].append(r)
        elif head in ("regression", "fix") and rest in STAGE_NODE \
                or what == "rollback.prod":
            # A stage's run is a pass on the regression map, its fixing
            # sessions and a rollback with it.
            stage = "prod" if what == "rollback.prod" else rest
            key = last_run.get(stage)
            if (head, op) == ("regression", "start") or key is None:
                key = last_run[stage] = "%s-%d" % (stage, len(regression))
                regression[key] = []
                places.detour("regression", key, at)
            regression[key].append(r)
        elif what == "deploy.preview":
            if op == "start":
                places.enter("preview", at, what)
            else:
                places.leave(what, at)
        elif what == "deploy.prod" and op == "done":
            places.point("prod", at)
        elif what == "review.local":
            if op == "start":
                places.enter("local_pass", at, what)
            else:
                places.leave(what, at)
        elif what == "qa":
            # Done is seen again on every look before the merge: a verdict is
            # one only after QA was sent to look.
            if op == "in":
                places.point("in_qa", at)
                places.enter("qa_check", at, "qa")
                qa_open = True
            elif qa_open or op == "back":
                places.leave("qa", at)
                places.point("qa_verdict", at)
                qa_open = False
        elif what == "handoff":
            places.point("handoff", at)
        elif what == "merge":
            if op == "wait":
                places.enter("merge_wait", at, "merge")
            elif not merged:
                merged = True
                places.leave("merge", at)
                places.point("merged", at)
        elif what == "workshop" and op == "none" and r.get("session") not in workshop:
            pass  # let write there, and changed nothing: no pass
        elif what == "workshop":
            session = r.get("session") or (list(workshop)[-1] if workshop else "")
            if session not in workshop:
                workshop[session] = []
                places.detour("workshop", session, at)
            workshop[session].append(r)
        # A command is the next process's: it says nothing of when the run
        # before it left off.
        if what != "command":
            places.last = at
        if r.get("run") and what != "command":
            places.last_of[r["run"]] = at

    # A stay left with no end row is going on only when sclaude's state says
    # so, and then counts up to now (`live`): a step's conversation while it
    # is the state's step and its run open, the retrospective's, the
    # epilogue's (`_session_going`); a wait the feature stands in (the
    # merge's, QA's look: its position, `here`, with nothing after it). Any
    # other ended unseen (a Ctrl-C, a terminal that died write no end): at
    # the earliest of the next place begun after it (a pass run inside it is
    # not the feature leaving it) and the last line its run wrote
    # (`_unseen_end`), its time a guess the page marks (`unsure`) - except
    # the merge's wait or QA's look the next place began after, which ended
    # there as _Places.enter has it. Decided by the user on 2026-11-03, after
    # rules guessed from the rows alone broke one case for each they fixed.
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for key, place in list(places.open.items()):
        name = key.split(".", 1)[-1]  # "steps.<step>" for a step
        after = places.list[places.list.index(place) + 1:]
        # The next place, not a pass: a pass is run inside a stay.
        later = next((p["from"] for p in after if "n" in p and p.get("from")), None)
        if place.get("session"):
            going = process_position._session_going(state, name) and (not key.startswith("steps.") or name == state.get("step"))
        else:
            going = place["n"] in process_position.WAITS_HERE and place["n"] == here and not later
        if going:
            place["going"] = True
            continue
        if place["n"] in process_position.WAITS_HERE and later:
            # A wait is the feature's, not a run's: it lasts across runs and
            # ended where the next place began.
            places.leave(key, later)
            continue
        places.leave(key, process_position._unseen_end(place["sittings"][-1][0], place.get("run"), places))
        place["unsure"] = True

    # Merged into one: the same place entered again with nothing between, by
    # the same conversation — a session resumed, a deploy and its regression.
    visits = []
    for p in places.list:
        last = visits[-1] if visits else None
        if last and "n" in p and last.get("n") == p["n"] and p["n"] != "new" and (
                not p.get("session") or not last.get("session") or p["session"] == last["session"]):
            last["sittings"] += p["sittings"]
            last["to"] = p["to"] or last["to"]
            for flag in ("going", "unsure"):
                last[flag] = last.get(flag) or p.get(flag)
            continue
        visits.append(p)
    aside = here and here not in process_model.NODES
    if here and not aside and (not visits or visits[-1].get("n") != here):
        visits.append({"n": here, "from": None, "to": None, "sittings": [], "here": True})
    elif visits and here and not aside:
        visits[-1]["here"] = True

    # The places between, along the map; the time between two places to the
    # first check or person on the way, who is what it waited on.
    graph = _graph(process_model.EDGES)
    out, prev, held, stray, after_copy = [], None, [], False, False
    for v in visits:
        if "pass" in v:
            # A regression run or a sync stands between two places of the
            # cycle (an R, an S on the way): it is played after the way that
            # led to it, which waited until it began.
            if (v["pass"][0] in ("regression", "sync") or held) and prev is not None:
                held.append(v)
            else:
                out.append({"pass": v["pass"]})
            continue
        copy = v["n"] in COPIES
        stop = prev
        if prev is not None and not copy:
            # Back where it was before a status copy: no way round.
            reopened = prev["n"] == v["n"] and (v["n"] in REOPENED or after_copy)
            full = [] if reopened else _way(graph, prev["n"], v["n"])
            way = full[1:-1]
            # The map has no way at all from the one to the other: the
            # feature went where the map does not go (deviations).
            stray = full == [prev["n"], v["n"]] and v["n"] not in graph.get(prev["n"], [])
            # A long way round is a guess, not a fill: a local review pass
            # after a round has no arrow of its own, and the shortest way
            # there runs through the merge and the retrospective.
            if len(way) > FILL_MAX:
                way = []
            until = held[0].get("from") if held else None
            until = until or v.get("from") or (v["sittings"][0][0] if v["sittings"] else None)
            # A stay still going is not waited after: its sitting holds it.
            gap = None if any(not b for a, b in prev.get("sittings", [])) else _seconds(prev.get("to"), until)
            waited = next((n for n in way if process_model.NODES[n][2] in WAITS_ON), None)
            for n in way:
                step = {"n": n}
                if n == waited and gap and gap >= 60:
                    step.update({"s": gap, "from": prev.get("to"), "to": until, "wait": True,
                                 SPANS: [(prev.get("to"), until)]})
                out.append(step)
        out += [{"pass": h["pass"]} for h in held]
        held = []
        step = {"n": v["n"]}
        spans = [(a, b) for a, b in v["sittings"] if a and b]
        # A sitting of the conversation going on counts up to this moment,
        # and its stay is the one that holds the step going on (`live`).
        going = [(a, now_iso) for a, b in v["sittings"] if a and not b] if v.get("going") else []
        spans += going
        secs = [n for n in (_seconds(a, b) for a, b in spans) if n is not None]
        if secs:
            step["s"] = sum(secs)
            step[SPANS] = spans
        if going:
            step["live"] = True
        if v.get("unsure"):
            step["unsure"] = True
        if len(v["sittings"]) > 1:
            step["k"] = len(v["sittings"])
        if v.get("from"):
            step["from"] = v["from"]
        if v.get("to"):
            step["to"] = v["to"]
        if v.get("here"):
            step["here"] = True
        if prev is not None and stray:
            step["off"] = "the map has no way from %s to %s" % (
                process_model.NODES.get(prev["n"], ("",) * 4)[3] or prev["n"], process_model.NODES.get(v["n"], ("",) * 4)[3] or v["n"])
        stray = False
        out.append(step)
        prev = dict(stop, to=v.get("to") or stop.get("to")) if copy else v
        after_copy = copy
    # The last passes, with no place after them yet.
    out += [{"pass": h["pass"]} for h in held]

    names = _session_names(state)
    workshop_sessions = set(workshop)
    passes = {"friction": [], "workshop": [], "regression": [], "sync": []}
    index = {}
    def unseen(rs):
        """For a pass's sitting left with no end: where it ended unseen. One
        whose rows name no run has no line of its own to end at, and the
        history's last says nothing of it: it took no time."""
        # The run of the row that opened the sitting left open: a later
        # process's rows (a rollback, a fix) say nothing of when it ended.
        run = next((r.get("run") for r in reversed(rs) if r["op"] in ("open", "start")), rs[0].get("run"))
        return (lambda began: process_position._unseen_end(began, run, places)) if run else (lambda began: began)

    for key, rs in regression.items():
        index[("regression", key)] = len(passes["regression"])
        ends = [x["op"] for x in rs if x["what"].startswith("regression.") and x["op"] != "start"]
        passes["regression"].append({
            "label": "%s · %s%s" % (_short(rs[0]["at"]), key.split("-")[0], (" · " + ends[-1]) if ends else ""),
            "steps": _regression_way(key.split("-")[0], rs,
                                     unseen(rs),
                                     now_iso if key == last_run.get(key.split("-")[0])
                                     and process_position._running(state, key.split("-")[0]) else None)})
    for key, rs in syncs.items():
        index[("sync", key)] = len(passes["sync"])
        ends = [x["op"] for x in rs if x["op"] != "open"]
        passes["sync"].append({
            "label": "%s · sync%s" % (_short(rs[0]["at"]), (" · " + ends[-1]) if ends else ""),
            "steps": _sync_way(rs, now_iso if key == list(syncs)[-1] and process_position._session_going(state, "sync") else None,
                               unseen(rs))})
    for key, rs in friction.items():
        if [r["op"] for r in rs] == ["empty"]:
            continue
        verdict = next((r.get("verdict") for r in rs if r["op"] == "verdict"), "")
        if any(r["op"] == "deferred" for r in rs):
            verdict = "put off, no session"
        index[("friction", key)] = len(passes["friction"])
        passes["friction"].append({
            "label": "%s · %s%s" % (_short(rs[0]["at"]), key, (" · " + verdict) if verdict else ""),
            "steps": _friction_way(rs, workshop_sessions,
                                   now_iso if process_position._open((process_position._runs((state.get("friction") or {}).get(key)) or [None])[-1])
                                   else None,
                                   unseen(rs))})
    for session, rs in workshop.items():
        ends = [r["op"] for r in rs if r["op"] in WORKSHOP_OUT or r["op"] in ("none", "ready")]
        index[("workshop", session)] = len(passes["workshop"])
        passes["workshop"].append({
            "label": "%s · after %s%s" % (_short(rs[0]["at"]), names.get(session, "a session"),
                                       (" · " + ends[-1]) if ends else ""),
            "steps": _workshop_way(rs)})
    if aside:
        # On a map of its own (a run, a sync): the last pass there that
        # reaches it stands there now.
        for name, ps in passes.items():
            if ps and here in process_config.node_sets_named().get(name, {}):
                last = ps[-1]["steps"]
                hit = [x for x in last if x.get("n") == here]
                (hit[-1] if hit else last.append({"n": here}) or last[-1])["here"] = True
    steps = []
    for s in out:
        if "pass" in s:
            i = index.get(tuple(s["pass"]))
            if i is not None:
                steps.append({"pass": [s["pass"][0], i]})
        else:
            steps.append(s)
    deviations(steps)
    if pass_rows is None:
        pass_rows = getattr(transcripts, "passes", None)
    counted = process_costs.metrics(rows, steps, passes, transcripts, now_iso, pass_rows)
    for st in steps + [x for ps in passes.values() for p in ps for x in p["steps"]]:
        st.pop(SPANS, None)
    return {"visits": steps, "passes": passes, "metrics": counted,
            "now": now_iso}


# A map of its own is reached from a block marked with its letter: a pass
# between two places neither of which carries it is the feature going where
# the map does not say.
PASS_LETTER = {"regression": "R", "sync": "S", "friction": "F", "workshop": "W"}


def deviations(steps):
    """Marks in place each pass the map does not lead to from where it ran
    (`off`, a sentence): the places before and after it carry no letter of
    its map. A jump with no way on the map is marked as it is played (history)."""
    for i, s in enumerate(steps):
        if "pass" not in s:
            continue
        letter = PASS_LETTER.get(s["pass"][0])
        # Its block may stand a gate or two back: a run after your yes on
        # step 2's work is played after "Does it work?" (history's fill).
        before = []
        for x in steps[:i][::-1]:
            if "n" in x:
                before.append(x["n"])
                if len(before) == 3 or process_model.NODES.get(x["n"], ("",) * 3)[2] not in WAITS_ON:
                    break
        near = before + [x["n"] for x in steps[i + 1:] if "n" in x][:1]
        # Or a pass beside it whose map has the letter: a fixing session's
        # friction review (F on the regression map), a review's change to
        # sclaude (W on the friction map).
        beside = [x["pass"][0] for x in steps[max(0, i - 1):i + 2] if "pass" in x and x is not s]
        if any(letter in n[5] for m in beside for n in process_config.node_sets_named().get(m, {}).values()):
            continue
        if letter and near and not any(letter in process_model.NODES.get(n, ("",) * 6)[5] for n in near):
            ends = [near[0]] + near[len(before):] if before else near
            names = " and ".join(process_model.NODES.get(n, ("",) * 4)[3] or n for n in ends)
            if len(ends) == 1:
                names = "here and " + names
            s["off"] = "%s ran between %s, and no block there carries %s" % (
                {"regression": "a regression", "sync": "a sync with main", "friction": "a friction review",
                 "workshop": "a change to sclaude"}[s["pass"][0]], names, letter)
