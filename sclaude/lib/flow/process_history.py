# How a feature went: its history read back into the places it passed,
# with the ways back, the fixes and the workshop.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import datetime
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
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
LOCAL_JOURNAL = "review-rounds.jsonl"  # JOURNAL in local_review.py
# What the transcripts said of each conversation, kept beside the history.
TRANSCRIPT_CACHE = "transcripts.json"
TRANSCRIPT_FRESH = 60

# A step closed: the check it closes on.
STEP_CLOSE = {"plan": "plan_check", "pr": "pr_check", "review": "review_close"}
STAGE_NODE = {"local": "reg_local", "preview": "preview", "prod": "prod"}
# The friction map's places a log found empty goes through: no pass.
FRICTION_QUIET = ("f_log", "f_empty", "f_none")
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


# --- the edges the code wrote ----------------------------------------------
#
# A row {"what": "edge", "op": "<from> <to>"} is a way taken on one of the
# maps, written where the code took it (history_edge, state.sh), with who
# took it (`by`: person, setting, sclaude, session, qa, github, none — nobody
# answered), how (`how`: where the answer came from, the setting and its
# value, what was checked) and what else was known then (`note`). Where they
# are, the played way follows them; between two that do not meet, and for a
# feature older than them, it is filled in along the map as before.

EDGE = "edge"

# The arrows no code of sclaude's writes, each with why: taken where sclaude
# does not see it happen. The rest of a map recorded here (RECORDED) is
# written where it is taken; tests/process.py holds the two to the code.
RECORDED = ("workshop", "detail", "friction", "regression", "sync", "parts")
# The parts map is played from the rows parts.sh and the steps write (`parts
# capture/merged/stop`, the steps' sessions, each with its `part`), not from
# edges: its arrows are what those rows mean, and none is written as one.
_PARTS_INFERRED = "inferred from the parts' rows (parts.sh, the steps' sessions), not written as an edge"
UNWRITTEN = {
    ("w_find", "w_ask"): "the session finds the fix and asks for its plan inside its conversation",
    ("approve", "plan"): "the person's corrections go to the session inside its conversation",
    ("preview", "epi_preview"): "a step aside: the status session's own row (about=preview) plays it",
    ("f_trip", "f_log"): "a hook writes the log inside the step's session",
    ("f_decide", "f_defer"): "an entry the review is unsure of becomes a deferred row inside its conversation",
    ("f_defer", "f_monthly"): "the monthly review runs over the project, not over a feature",
    ("hold_ways", "r_on"): "the run the person starts on a held production is a pass of its own, from its start",
}
UNWRITTEN.update({(a, b): _PARTS_INFERRED for a, b, _label, _kind in process_model.PARTS_EDGES})


def _edge(row):
    a, _, b = str(row.get("op") or "").partition(" ")
    return a, b


def _labels():
    """Every map's arrows on the configured model: (from, to) → its words."""
    return {(a, b): label for _name, _lanes, _nodes, edges in process_config.node_sets()
            for a, b, label, _kind in edges}


def _via(row, labels):
    """What the page says of the way into a place: the arrow's words, who
    took it, how, what was known, and when."""
    via = {k: row[k] for k in ("by", "how", "note", "at") if row.get(k)}
    label = labels.get(_edge(row))
    if label:
        via["label"] = label
    return via


def _chain(start, edges, graph, end=None, limit=FILL_MAX):
    """The places along recorded edges from `start`, as (node, row) pairs:
    the row None for a place filled in along the map where an edge does not
    begin where the last one ended (one written nowhere yet, a jump the map
    does not draw). With `end`, the way goes on to it the same way, and `end`
    itself is left out: the second value is the row of the edge into it.
    Edges after the one that reaches `end` are left for the places after it
    (written in the same second): the third value counts the ones taken."""
    cur, out, before, used = start, [], None, 0
    for e in edges:
        if end is not None and cur == end and out:
            break
        used += 1
        a, b = _edge(e)
        # The way into the place it stands on, written after the row that
        # entered it: already taken.
        if b == cur and a != cur:
            continue
        # Back from a side place no arrow leaves (the issue taken, its
        # criteria) to the one it hangs off: no way to play.
        if a == before and not graph.get(cur):
            cur = a
        before = cur
        if a != cur:
            hop = _way(graph, cur, a)
            out += [(n, None) for n in (hop[1:] if limit is None or len(hop) - 2 <= limit else [a])]
        out.append((b, e))
        cur = b
    if end is None:
        return out, None, used
    if cur == end and out:
        return out[:-1], out[-1][1], used
    hop = _way(graph, cur, end)[1:-1]
    return out + [(n, None) for n in (hop if limit is None or len(hop) <= limit else [])], None, used


def _along(inferred, edges, start, graph, labels):
    """A pass's way along its recorded edges, each place keeping what the
    rows say it took (the inferred way's step of the same place, matched in
    order); a stay the edges have not reached yet — one going on, or cut
    off — stays at the end."""
    chain, _, _ = _chain(start, edges, graph, limit=None)
    out, i = [], 0
    for n, e in [(start, None)] + chain:
        j = next((k for k in range(i, len(inferred)) if inferred[k].get("n") == n), None)
        step = dict(inferred[j]) if j is not None else {"n": n}
        if j is not None:
            i = j + 1
        if e:
            step["via"] = _via(e, labels)
        out.append(step)
    return out + [dict(s) for s in inferred[i:] if s.get("live") or s.get("unsure")]


def _map_of(node):
    """Which map a place is on: detail (the cycle) or a pass's."""
    return next((name for name, nodes in process_config.node_sets_named().items()
                 if name != "overview" and node in nodes), None)


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


# --- a feature built in parts ------------------------------------------------
#
# A split feature's parts (parts.sh) play on the parts map rather than the
# detailed one: each part a pass of its own — its build in step 2, and later,
# once the whole is accepted, its pull request, its review and its merge into
# the common branch. Step 2 over the whole, between the two, goes to the last
# part's pass (p_whole). A row says its part (`part`, history_add and
# session_runs: the part's number while it is built or reviewed, `whole`
# while the whole is checked and after the last part is in); a row older than
# that is taken to belong to the part at work by the rows' order. The cycle's
# edges written inside a part (code works, works pr, pr pr_check…) are the
# part's way, not the feature's, and are not played on the detailed map.

PARTS_STEP = {"code": "p_code", "pr": "p_pr", "review": "p_review"}
# A row's place on another map than its own, set by history for the costs
# (process_costs._session_place): a part's sessions cost on the parts map.
ON = "_on"
# A row of step 2's session over the whole feature, after the last part.
WHOLE = "_whole"


def _parts_way(rows, first, on=False, now=None, cut=None):
    """A part's way through the parts map: its build's sittings; for the last
    part, step 2 over the whole after it; then its pull request and review
    with its local review, and its merge. `on`: the detailed map went on past
    the last part."""
    way = ([{"n": "p_split"}] if first else []) + [{"n": "p_enter"}]
    sitting, by = None, None

    def close(at):
        nonlocal sitting, by
        if sitting:
            way[-1]["s"] += _seconds(sitting, at) or 0
            way[-1].setdefault(SPANS, []).append((sitting, at))
            way[-1]["to"] = at
        sitting, by = None, None

    def reach(node):
        # The gates between: the build ends at p_built, a review begins with
        # the feature's branch taken in.
        last = way[-1]["n"]
        if node == "p_whole" and last != "p_built":
            way.append({"n": "p_built"})
        if node in ("p_pr", "p_review") and last in ("p_code", "p_built", "p_whole", "p_more"):
            if last == "p_code":
                way.append({"n": "p_built"})
            way.append({"n": "p_take"})

    for r in rows:
        what, op, at = r["what"], r["op"], r["at"]
        head, _, rest = what.partition(".")
        if (head == "steps" and rest in PARTS_STEP) or what == "review.local":
            node = "p_whole" if r.get(WHOLE) else PARTS_STEP.get(rest, "p_review")
            if op in ("open", "start"):
                # The local review's pass inside the review's conversation:
                # the same minutes.
                if sitting and what == "review.local":
                    continue
                if sitting:
                    # One opened in place of a conversation that died.
                    close(at)
                if way[-1]["n"] == node:
                    way[-1]["k"] = way[-1].get("k", 1) + 1
                else:
                    reach(node)
                    way.append({"n": node, "from": at, "s": 0})
                sitting, by = at, what
            elif op == "drop" and sitting and by == what:
                # A conversation that never took place: no time, no sitting.
                sitting, by = None, None
                if way[-1].get("k", 1) > 1:
                    way[-1]["k"] -= 1
            elif sitting and by == what and (op in ("end", "stall", "finish")
                                             or what == "review.local"):
                close(at)
        elif what == "parts" and op in ("built", "stop"):
            close(at)
            if way[-1]["n"] != "p_built":
                way.append({"n": "p_built"})
        elif what == "parts" and op == "merged":
            close(at)
            way += [{"n": "p_check"}, {"n": "p_merge", "from": at, "to": at}, {"n": "p_sync"}, {"n": "p_more"}]
    # A sitting left open: going on by sclaude's state, up to now; else it
    # ended unseen, where `cut` says (_unseen_end), a guess the page marks.
    if sitting:
        end = now or cut and cut(sitting)
        if end and _when(end) > _when(sitting):
            way[-1]["s"] += _seconds(sitting, end) or 0
            way[-1].setdefault(SPANS, []).append((sitting, end))
            if not now:
                way[-1]["to"] = end
        way[-1]["live" if now else "unsure"] = True
    if on and way[-1]["n"] == "p_more":
        way.append({"n": "p_on"})
    return way


def _part_of(r, pmode, current, total, last):
    """Which part's pass a row goes to — its key, "drop" for the cycle's
    edge a part wrote, None for the detailed map and the other passes —
    and where the parts stand after it: (into, mode, current, total).

    The modes follow parts.sh: `build` while the parts are built, `whole`
    while step 2 checks the whole, `review` while the parts' pull requests
    are reviewed, `done` once the last is in."""
    what, op = r["what"], r["op"]
    head, _, rest = what.partition(".")
    part = str(r.get("part") or "")
    # A replan that undid the split while part 1 was built: the feature is
    # one pull request again, and its steps go back to the detailed map.
    if (what, op) == ("parts", "uncapture"):
        return "drop", None, "1", 0
    if what == "parts" and op == "capture" and str(r.get("total") or "").isdigit():
        total = total if pmode not in (None, "build") else int(r["total"])
    if pmode is None and ((what, op) == ("parts", "capture") or part.isdigit()):
        pmode = "build"
    if pmode == "build" and part == "whole":
        pmode = "whole"
    if pmode == "build":
        key = part if part.isdigit() else current
        if what == "parts":
            if op == "capture":
                return "drop", pmode, current, total
            if op == "built":
                if total and int(key) >= total:
                    pmode = "whole"
                else:
                    current = str(int(key) + 1)
            elif op == "stop":
                # The parts from this one on are left out: the last kept is
                # the last reviewed.
                pmode = "whole"
                if key.isdigit():
                    total = int(key) - 1
            return key, pmode, current, total
        if (head == "steps" and rest in PARTS_STEP) or what == "review.local":
            return key, pmode, current, total
        if what == EDGE and _map_of(_edge(r)[0]) == "detail":
            return "drop", pmode, current, total
        return None, pmode, current, total
    if pmode == "whole":
        lastkey = last[0] if last else current
        if what == "steps.code":
            r[WHOLE] = True
            return lastkey, pmode, current, total
        if what == "parts" and op == "accepted":
            return lastkey, "review", "1", total
        # The first row of a part's pull request: the whole was accepted.
        if part.isdigit() or (head == "steps" and rest in ("pr", "review") and op == "open"):
            pmode, current = "review", "1"
        else:
            return None, pmode, current, total
    if pmode == "review":
        key = part if part.isdigit() else current
        if part == "whole":
            return None, "done", current, total
        if what == "parts":
            if op == "merged":
                if total and int(key) >= total:
                    pmode = "done"
                else:
                    current = str(int(key) + 1)
            return key, pmode, current, total
        if (head == "steps" and rest in ("pr", "review")) or what == "review.local":
            return key, pmode, current, total
        if what == EDGE and _map_of(_edge(r)[0]) == "detail":
            return "drop", pmode, current, total
        return None, pmode, current, total
    return None, pmode, current, total


WORKSHOP_START = ("w_find", "w_ask", "w_open", "w_change", "w_ready", "w_exit", "w_ready_gate")
WORKSHOP_OUT = {
    "blocked": ("w_leaks", "w_leak_ask", "w_held"), "held": ("w_leaks", "w_leak_ask", "w_held"),
    "left": ("w_back", "w_pending"), "red": ("w_leaks", "w_tests", "w_wait"),
    "unchanged": ("w_wait",),
    "declined": ("w_leaks", "w_tests", "w_send", "w_held"), "waits": ("w_leaks", "w_tests", "w_send"),
    # Held unasked, by the machine's setting: past the person's gates.
    "leaks-off": ("w_leaks", "w_held"), "contribute-off": ("w_leaks", "w_tests", "w_held"),
    # The leak question unanswered: it waits, asked again at the next opening.
    "leaks-waits": ("w_leaks", "w_leak_ask", "w_wait"),
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
        # Red and an unanswered leak question end in the wait, unless the
        # session was sent back for red (sent-back, written as it reopens):
        # then the return is the way. A publication after such a wait with
        # no return between is a retry at a later opening, played from the
        # gate that stopped it, as a jump the map does not draw; after the
        # wait of a session that left the head as it was (unchanged), the
        # wait stays, as the stop between the two openings.
        if way[-1] == "w_wait" and way[-2] in ("w_tests", "w_leak_ask"):
            if r["op"] == "sent-back":
                way = way[:-1] + ["w_change", "w_ready", "w_exit", "w_ready_gate"]
                continue
            if r["op"] in WORKSHOP_OUT:
                way.pop()
        for n in WORKSHOP_OUT.get(r["op"], ()):
            if n != way[-1]:
                way.append(n)
    return [{"n": n} for n in way]


def _edged(inferred, rows, start, map_edges, labels, timed=True):
    """A pass's way: along the edges its rows recorded, where there are any,
    keeping what the rows say each place took; else as the rows tell it.
    The workshop's way takes no time of its own, and its edges are the
    whole of it."""
    written = [r for r in rows if r["what"] == EDGE]
    if not written:
        return inferred
    return _along(inferred if timed else [], written, start, _graph(map_edges), labels)


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
    # The demo recorded again (demo_refresh, demo.sh): no place of a map.
    for run in process_position._runs(state.get("demo") if isinstance(state.get("demo"), dict) else None):
        names[run.get("session")] = "demo refresh"
    names.pop(None, None)
    return names


def _short(at):
    when = _when(at)
    return when.strftime("%d %b %H:%M") if when else ""


def history(state, lines, here=None, transcripts=None, pass_rows=None):
    """The feature's way through the maps, for the page to play, and what
    each place took (`metrics`) when the sessions' transcripts are given:
    a function from a session id to claude_usage.read's summary, or None."""
    # Copies: a part's rows are marked with their place for the costs.
    rows = [dict(r) for r in history_rows(lines)]
    places = _Places()
    friction, workshop, regression, syncs = {}, {}, {}, {}
    # A feature built in parts: each part's rows, where the parts stand
    # (None, build, whole, done), the part a row with no `part` is taken to
    # be in, the parts' count, the time they span, and whether the detailed
    # map went on past step 2 over the whole.
    parts, pmode, pcurrent, ptotal, pspan, pon = {}, None, "1", 0, [], False
    # The cycle's recorded edges, and the friction reviews whose pass began.
    edges, quiet = [], {}
    last_run = {}
    merged = qa_open = False
    first = rows[0]["at"] if rows else None
    if first:
        places.point("new", first)
    for r in rows:
        what, op, at = r["what"], r["op"], r["at"]
        head, _, rest = what.partition(".")
        places.run = r.get("run")
        into, pmode, pcurrent, ptotal = _part_of(r, pmode, pcurrent, ptotal, list(parts)[-1:])
        if into == "drop":
            continue
        if into:
            if into not in parts:
                parts[into] = []
                places.detour("parts", into, at)
            parts[into].append(r)
            if op == "open" and r.get("session") and head == "steps":
                r[ON] = ("parts", "p_whole" if r.get(WHOLE) else PARTS_STEP[rest])
            pspan[:] = [pspan[0] if pspan else at, at]
            places.last = at
            if r.get("run"):
                places.last_of[r["run"]] = at
            continue
        if pmode == "done" and not pon and parts and head == "steps" and op == "open":
            pon = True
        if what == EDGE:
            on = _map_of(_edge(r)[0])
            if on == "detail":
                edges.append(r)
            elif on == "workshop":
                session = r.get("session") or (list(workshop)[-1] if workshop else "")
                if session not in workshop:
                    workshop[session] = []
                    places.detour("workshop", session, at)
                workshop[session].append(r)
            elif on == "friction" and r.get("key"):
                if r["key"] not in friction:
                    friction[r["key"]] = []
                if not quiet.get(r["key"]) and _edge(r)[1] not in FRICTION_QUIET:
                    quiet[r["key"]] = True
                    places.detour("friction", r["key"], at)
                friction[r["key"]].append(r)
            elif on == "regression" and r.get("stage") in STAGE_NODE:
                key = last_run.get(r["stage"])
                if key is None:
                    key = last_run[r["stage"]] = "%s-%d" % (r["stage"], len(regression))
                    regression[key] = []
                    places.detour("regression", key, at)
                regression[key].append(r)
            elif on == "sync":
                # Main found moved with a conflict, or only the deferred
                # logs: a sync of its own begins; its other ways go on in it.
                if _edge(r)[0] == "y_when" or last_run.get("sync") is None:
                    key = last_run["sync"] = str(len(syncs))
                    syncs[key] = []
                    places.detour("sync", key, at)
                syncs[last_run["sync"]].append(r)
        elif head == "steps" and rest in process_model.NODES:
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
                                 or [x["op"] for x in syncs[key] if x["what"] != EDGE][-1:] == ["drop"]):
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
            # Its pass begins at the first row that is more than a log
            # found empty (an empty log is no review, and no pass).
            if op != "empty" and not quiet.get(rest):
                quiet[rest] = True
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
                places.enter("review_run", at, what)
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
    labels = _labels()
    out, prev, held, stray, after_copy = [], None, [], False, False
    taken = 0  # the recorded edges played so far
    def recorded(until):
        """The cycle's edges written up to `until` (all that are left when
        it is None) not played yet."""
        nonlocal taken
        upto = taken
        while upto < len(edges) and (until is None or _when(edges[upto]["at"]) <= _when(until)):
            upto += 1
        got, taken = edges[taken:upto], upto
        return got
    def started(x):
        return x.get("from") or (x["sittings"][0][0] if x.get("sittings") else None)
    def in_parts(x):
        """A pass run while the parts were built."""
        return bool(pspan) and bool(x.get("from")) and _when(pspan[0]) <= _when(x["from"]) <= _when(pspan[1])
    for vi, v in enumerate(visits):
        if "pass" in v:
            # A regression run or a sync stands between two places of the
            # cycle (an R, an S on the way): it is played after the way that
            # led to it, which waited until it began.
            if (v["pass"][0] in ("regression", "sync", "parts") or held) and prev is not None:
                held.append(v)
            else:
                out.append({"pass": v["pass"]})
            continue
        copy = v["n"] in COPIES
        stop = prev
        entered = None
        # The parts of a feature built in parts, and the passes run while
        # they were built, go inside step 2: after its block on the way, and
        # nothing on the way before them waited while they ran.
        inside = [h for h in held if h["pass"][0] == "parts" or in_parts(h)]
        if prev is not None and not copy:
            until = next((h.get("from") for h in held if h not in inside), None)
            until = until or v.get("from") or (v["sittings"][0][0] if v["sittings"] else None)
            # A place with no time of its own takes the edges up to the next
            # place that has one (all that are left where none has); the
            # chain stops at it and leaves the rest to the places after.
            upto = until or next((started(x) for x in visits[vi + 1:] if "n" in x and started(x)), None)
            written = recorded(upto)
            if written:
                # The edges the code wrote lead the way; the map fills in
                # only where two of them do not meet.
                chain, entered, used = _chain(prev["n"], written, graph, v["n"])
                taken -= len(written) - used
                way = [n for n, _e in chain]
                vias = {i: _via(e, labels) for i, (_n, e) in enumerate(chain) if e}
                stray = False
            else:
                vias = {}
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
            # A stay still going is not waited after: its sitting holds it.
            after = prev.get("to")
            at_code = None
            if inside:
                after = pspan[1]
                at_code = next((i for i, n in enumerate(way) if n == "code"), len(way))
            gap = None if any(not b for a, b in prev.get("sittings", [])) else _seconds(after, until)
            waited = next((i for i, n in enumerate(way) if (at_code is None or i > at_code)
                           and process_model.NODES[n][2] in WAITS_ON), None)
            for i, n in enumerate(way):
                step = {"n": n}
                if i in vias:
                    step["via"] = vias[i]
                if i == waited and gap and gap >= 60:
                    step.update({"s": gap, "from": after, "to": until, "wait": True,
                                 SPANS: [(after, until)]})
                out.append(step)
                if i == at_code:
                    out += [{"pass": h["pass"]} for h in inside]
            if at_code is not None and at_code < len(way):
                held = [h for h in held if h not in inside]
        out += [{"pass": h["pass"]} for h in held]
        held = []
        step = {"n": v["n"]}
        if entered:
            step["via"] = _via(entered, labels)
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
    # The last passes, with no place after them yet, and the edges written
    # after the last place: the gates past it that no row enters (the
    # retrospective's, the clean-up's).
    out += [{"pass": h["pass"]} for h in held]
    if prev is not None:
        chain, _, _ = _chain(prev["n"], recorded(None), graph)
        out += [dict({"n": n}, **({"via": _via(e, labels)} if e else {})) for n, e in chain]

    names = _session_names(state)
    workshop_sessions = set(workshop)
    passes = {"friction": [], "workshop": [], "regression": [], "sync": [], "parts": []}
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
            "steps": _edged(_regression_way(key.split("-")[0], [x for x in rs if x["what"] != EDGE],
                                            unseen(rs),
                                            now_iso if key == last_run.get(key.split("-")[0])
                                            and process_position._running(state, key.split("-")[0]) else None),
                            rs, "r_" + key.split("-")[0], process_model.REGRESSION_EDGES, labels)})
    for key, rs in syncs.items():
        index[("sync", key)] = len(passes["sync"])
        ends = [x["op"] for x in rs if x["op"] != "open" and x["what"] != EDGE]
        passes["sync"].append({
            "label": "%s · sync%s" % (_short(rs[0]["at"]), (" · " + ends[-1]) if ends else ""),
            "steps": _edged(_sync_way([x for x in rs if x["what"] != EDGE],
                                      now_iso if key == list(syncs)[-1] and process_position._session_going(state, "sync") else None,
                                      unseen(rs)),
                            rs, "y_when", process_model.SYNC_EDGES, labels)})
    # The pass the feature's own pull request follows: the last part
    # merged — not one the person left out after the whole was built on the
    # parts before it.
    merged_keys = [k for k, rs in parts.items() if any(x["what"] == "parts" and x["op"] == "merged" for x in rs)]
    for j, (key, rs) in enumerate(parts.items()):
        index[("parts", key)] = len(passes["parts"])
        last = j == len(parts) - 1
        # The part's conversation open now: the state's step, and its run.
        opened = next((x for x in reversed(rs) if x["op"] == "open" and x["what"].startswith("steps.")), None)
        step = opened["what"].split(".", 1)[1] if opened else ""
        going = last and step and state.get("step") == step and process_position._session_going(state, step)
        ends = [x["op"] for x in rs if x["what"] == "parts"]
        whole = any(x.get(WHOLE) for x in rs)
        passes["parts"].append({
            "label": "%s · part %s%s%s%s" % (_short(rs[0]["at"]), key, ("/%d" % ptotal) if ptotal else "",
                                          (" · " + ends[-1]) if ends else "", " · the whole" if whole else ""),
            "steps": _parts_way(rs, j == 0, pon and key == (merged_keys[-1] if merged_keys else list(parts)[-1]),
                                now_iso if going else None, unseen(rs))})
    for key, rs in friction.items():
        if not quiet.get(key):
            continue
        verdict = next((r.get("verdict") for r in rs if r["op"] == "verdict"), "")
        if any(r["op"] == "deferred" for r in rs):
            verdict = "put off, no session"
        index[("friction", key)] = len(passes["friction"])
        passes["friction"].append({
            "label": "%s · %s%s" % (_short(rs[0]["at"]), key, (" · " + verdict) if verdict else ""),
            "steps": _edged(_friction_way([x for x in rs if x["what"] != EDGE], workshop_sessions,
                                          now_iso if process_position._open((process_position._runs((state.get("friction") or {}).get(key)) or [None])[-1])
                                          else None,
                                          unseen(rs)),
                            rs, "f_trip", process_model.FRICTION_EDGES, labels)})
    for session, rs in workshop.items():
        # Opened (core-open writes its ways) and left with nothing made: no pass.
        if [r["op"] for r in rs if r["what"] != EDGE] == ["none"]:
            continue
        ends = [r["op"] for r in rs if r["op"] in WORKSHOP_OUT or r["op"] in ("none", "ready", "sent-back")]
        index[("workshop", session)] = len(passes["workshop"])
        passes["workshop"].append({
            "label": "%s · after %s%s" % (_short(rs[0]["at"]), names.get(session, "a session"),
                                       (" · " + ends[-1]) if ends else ""),
            "steps": _edged(_workshop_way([x for x in rs if x["what"] != EDGE]), rs, "w_find",
                            process_model.WORKSHOP_EDGES, labels, timed=False)})
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
    counted = process_costs.metrics(rows, steps, passes, transcripts, now_iso, pass_rows,
                                    process_costs.launches(state))
    for st in steps + [x for ps in passes.values() for p in ps for x in p["steps"]]:
        st.pop(SPANS, None)
    return {"visits": steps, "passes": passes, "metrics": counted,
            "now": now_iso}


def played(state_path, here=None):
    """The feature's history as both its readers take it — the feature's
    page (actions.sh) and `process.py history`: played on the map its
    project draws, so the ways filled in run through blocks it has, and a
    place that map does not draw (a merge awaited with no QA board) stands
    where the flow goes on from it. Gives the place on that map (None when
    it draws none), its title, and the history."""
    try:
        with open(state_path) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    read = process_costs.transcripts_of(state_path)
    tree = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(state_path)))))
    try:
        with process_model.configured(process_config.config_of(tree)):
            drawn = process_config.all_nodes()
            node = (process_config.on_map(here) or here) if here else None
            node = node if node in drawn else None
            return node, drawn[node][3] if node else None, \
                history(state, process_costs.read_history(state_path), node, read)
    finally:
        read.done()


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
        # The parts are step 2's own, reached from no lettered block.
        if not letter:
            continue
        # Its block may stand a gate or two back: a run after your yes on
        # step 2's work is played after "Accept the work?" (history's fill).
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
