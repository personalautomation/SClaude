# What each place took: the sessions' transcripts matched to the places,
# their time and cost.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import datetime
import json
import os
import time

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_history, process_model


# --- what each place took ----------------------------------------------------
#
# Shown on the maps by the checkboxes above them, never in the History:
#
#   input   each time the person stepped in — a message typed to Claude after
#           its turn or an answer to its question (claude_usage's `human`), an
#           answer to sclaude's own question (`ask answered`, io.sh) and a
#           command run on the feature at the terminal (`command`, state.sh) —
#           counted on the place the feature stood on at that moment;
#   cost    the dollars Claude Code's own account gives each conversation,
#           on the place the conversation ran;
#   wait    the seconds a question waited for the person's answer, counted
#           on the place the answer came in: Claude's, after its turn or its
#           question (claude_usage's `human`, not capped), and sclaude's own
#           (`ask answered waited=`, ask_once in ui.sh);
#   expired how many times a conversation's prompt cache had expired and its
#           context was written again (claude_usage's `expired`), on the
#           place the feature stood on then;
#   time    the seconds the feature stood on a place, each stay's own `s`
#           (what the player's clock shows), on the map the stay is on; a
#           detailed stay gives up what a regression or a sync ran inside
#           it, which counts on that pass's map, so no minute counts twice;
#   visits  how many stays each place had (not a checkbox: it goes beside
#           the time; the player counts its own as it plays);
#   unsure  how many of them ended unseen, their time a guess (⚠ beside it).
#
# Both as {map: {node: total}}, the friction review's over every review;
# each stay carries its own share as well ("m", {kind: n}), which the player
# adds up step by step. A workshop's work is done in the conversation of the
# step or the review that opened it, and counts there.

def _session_place(rows, opened=None):
    """Where each conversation ran, from the rows that opened it; with
    `opened`, a dict, when it was last opened there too."""
    out = {}
    for r in rows:
        if r["op"] not in ("open", "start") or not r.get("session"):
            continue
        head, _, rest = r["what"].partition(".")
        if r.get(process_history.ON):
            # A part's session of a feature built in parts: on the parts
            # map, where history played it.
            out[r["session"]] = tuple(r[process_history.ON])
        elif head == "steps" and rest in process_model.NODES:
            out[r["session"]] = ("detail", rest)
        elif head == "fix" and rest in process_history.STAGE_NODE:
            out[r["session"]] = ("regression", "fix_" + rest)
        elif r["what"] == "sync":
            out[r["session"]] = ("sync", "sync")
        elif r["what"] in ("retro", "epilogue"):
            # The preview's status has a block of its own, as its stay does.
            out[r["session"]] = ("detail", "epi_preview" if r.get("about") == "preview" else r["what"])
        elif head == "friction":
            out[r["session"]] = ("friction", "f_review")
        else:
            continue
        if opened is not None:
            opened[r["session"]] = r["at"]
    return out


def launches(state):
    """What each launch of a resumed session added, by session: [(when, $)].

    Claude Code keeps one running total for a conversation carried on with
    --resume, so a transcript prices the whole of it at once. sclaude writes
    each launch's share beside its run (`costs` and `cost_at`, run_cost in
    steps.sh), and that is what spreads it over the stays it was launched in.
    """
    out = {}
    for step in ((state or {}).get("steps") or {}).values():
        if not isinstance(step, dict):
            continue
        for run in step.get("runs") or []:
            if not isinstance(run, dict) or not run.get("session"):
                continue
            pairs = [(at, c) for at, c in zip(run.get("cost_at") or [], run.get("costs") or [])
                     if at and isinstance(c, (int, float)) and c >= 0]
            if pairs:
                out.setdefault(run["session"], []).extend(pairs)
    return out


def metrics(rows, steps, passes, transcripts, now_iso=None, pass_rows=None, shares=None):
    stays = [("detail", s) for s in steps if "n" in s]
    stays += [(m, s) for m, ps in passes.items() for p in ps for s in p["steps"]]
    now = process_history._when(now_iso) or datetime.datetime.now(datetime.timezone.utc)
    timed = [(m, s["n"], process_history._when(s["from"]), now if s.get("live") else process_history._when(s.get("to")) or process_history._when(s["from"]), s)
             for m, s in stays if s.get("from")]

    def place(at, inside_only=False):
        when = process_history._when(at)
        if not when:
            return None
        inside = [t for t in timed if t[2] <= when <= t[3]]
        if inside:
            return min(inside, key=lambda t: t[3] - t[2])[:2]
        if inside_only:
            return None
        before = [t for t in timed if t[0] == "detail" and t[2] <= when]
        return max(before, key=lambda t: t[2])[:2] if before else None

    def stay_of(where, at):
        """The stay at that place the moment falls in, else the last one
        begun before it, else the first, timed or not: where the player adds
        it up."""
        mine = [t for t in timed if t[:2] == where]
        if not mine:
            return next((st for m, st in stays if (m, st["n"]) == where), None)
        when = process_history._when(at)
        inside = [t for t in mine if when and t[2] <= when <= t[3]]
        before = [t for t in mine if when and t[2] <= when]
        return (min(inside, key=lambda t: t[3] - t[2]) if inside else
                max(before, key=lambda t: t[2]) if before else mine[0])[4]

    out = {"input": {}, "cost": {}, "wait": {}, "expired": {}, "time": {}, "visits": {}, "unsure": {}}
    detail = [t for t in timed if t[0] == "detail"]

    def ahead(at):
        """The detailed block a sync at this moment ran ahead of, one marked
        S: the stay that holds it (the merge's wait), else the next one."""
        when = process_history._when(at)
        marked = [t for t in detail if "S" in process_model.NODES.get(t[1], ("",) * 6)[5]]
        if not when or not marked:
            return None
        inside = [t for t in marked if t[2] <= when <= t[3]]
        later = [t for t in marked if t[2] > when]
        pick = min(inside, key=lambda t: t[3] - t[2]) if inside else \
            min(later, key=lambda t: t[2]) if later else max(marked, key=lambda t: t[2])
        return pick[1]

    def add(kind, where, n, at=None):
        if where and n:
            box = out[kind].setdefault(where[0], {})
            box[where[1]] = round(box.get(where[1], 0) + n, 4)
            # And on the stay itself, for the player's count step by step.
            stay = stay_of(where, at)
            if stay is not None:
                box = stay.setdefault("m", {})
                box[kind] = round(box.get(kind, 0) + n, 4)
            # The glance draws no sync: what one took counts under the block
            # it ran ahead of ("ahead", the page's totals for the overview),
            # by when its pass began: a pass broken off and resumed later is
            # still drawn ahead of that one.
            node = ahead((stay or {}).get("from") or at) if where[0] == "sync" else None
            if node:
                box = out[kind].setdefault("ahead", {})
                box[node] = round(box.get(node, 0) + n, 4)

    def spans(st):
        return [(a, b) for a, b in ((process_history._when(x), process_history._when(y)) for x, y in st.get(process_history.SPANS) or []) if a and b and b > a]

    def union(parts):
        out = []
        for a, b in sorted(parts):
            if out and a <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    # What the passes' maps timed, laid side by side once: a regression run
    # inside a sync is the same minutes.
    passed = union([sp for m, st in stays if m != "detail" for sp in spans(st)])
    for m, st in stays:
        # A stay's time and count go on that stay, not on one stay_of would
        # pick: the passes' stays mostly carry no moment to find them by.
        box = out["visits"].setdefault(m, {})
        box[st["n"]] = box.get(st["n"], 0) + 1
        # A stay whose end could not be told: its time is a guess, on the
        # glance too, under the block a sync ran ahead of.
        if st.get("unsure"):
            box = out["unsure"].setdefault(m, {})
            box[st["n"]] = box.get(st["n"], 0) + 1
            node = ahead(st.get("from")) if m == "sync" else None
            if node:
                box = out["unsure"].setdefault("ahead", {})
                box[node] = box.get(node, 0) + 1
        secs = st.get("s") or 0
        if secs and m == "detail" and passed:
            # Its own sittings, less what a pass's map timed in them.
            inside = sum(max(0, (min(b, y) - max(a, x)).total_seconds())
                         for a, b in union(spans(st)) for x, y in passed)
            secs = max(0, secs - int(inside))
        if not secs:
            continue
        box = out["time"].setdefault(m, {})
        box[st["n"]] = box.get(st["n"], 0) + secs
        st.setdefault("m", {})["time"] = secs
        node = ahead(st.get("from")) if m == "sync" else None
        if node:
            box = out["time"].setdefault("ahead", {})
            box[node] = box.get(node, 0) + secs
    for r in rows:
        if (r["what"], r["op"]) == ("ask", "answered") or r["what"] == "command":
            add("input", place(r["at"]), 1, r["at"])
        if (r["what"], r["op"]) == ("ask", "answered") and str(r.get("waited", "")).isdigit():
            add("wait", place(r["at"]), int(r["waited"]), r["at"])
    counted, opened = set(), {}
    opens = {}
    for r in rows:
        if r["op"] in ("open", "start") and r.get("session"):
            opens[r["session"]] = opens.get(r["session"], 0) + 1
    for session, where in _session_place(rows, opened).items():
        summary = transcripts(session) if transcripts else None
        # Two ids of one conversation carried on: its last transcript once.
        if not summary or summary.get("id", session) in counted:
            continue
        counted.add(summary.get("id", session))
        for turn in summary.get("human") or []:
            # Within its conversation: where the feature stood then, or
            # where the conversation ran when no stay holds the moment.
            at = place(turn[0], True) or where
            add("input", at, 1, turn[0])
            # How long Claude waited for the person, the whole of it: a
            # night left unanswered is a night (a summary older than the
            # field gives the capped time).
            add("wait", at, turn[3] if len(turn) > 3 else turn[1], turn[0])
        # Each time the prompt cache had to be written again, where the
        # feature stood then (claude_usage's `expired`).
        for when, _tokens in summary.get("expired") or []:
            add("expired", place(when, True) or where, 1, when)
        # On the stay of each launch, by its share, where sclaude saw the
        # launches (launches()); else all of it where it was last opened.
        # Only when every opening of the conversation has its share: with
        # one missed (no status line to read), the shares around it are
        # wrong too — a launch's share is the running total less the last
        # one seen — so the whole goes where it was opened last, as before.
        cost = summary.get("cost") or 0
        parts = (shares or {}).get(session) or []
        seen = sum(c for _, c in parts)
        if cost and seen and len(parts) == opens.get(session, 0):
            for at, c in parts:
                add("cost", where, cost * c / seen, at)
        else:
            add("cost", where, cost, opened.get(session))
    # A review pass on this machine is a headless conversation of its own,
    # named by its row in the local review's journal (local_review.rows, the
    # passes not recorded included): it costs on the pass's place, apart from
    # the fixing session's, as the review report prices it.
    for p in pass_rows or []:
        session = p.get("session")
        summary = transcripts(session) if transcripts and session else None
        if summary and summary.get("id", session) not in counted:
            counted.add(summary.get("id", session))
            for when, _tokens in summary.get("expired") or []:
                add("expired", place(when, True) or place(p.get("at")), 1, when)
            add("cost", place(p.get("at")), summary.get("cost") or 0, p.get("at"))
    return out


def transcripts_of(state_path):
    """The sessions' summaries, read from Claude Code's transcripts and kept
    beside the feature's state by size and time, so a poll reads only the
    conversations that grew. A transcript is looked for under the feature's
    tree, then under the main checkout and sclaude's own checkout, where a
    friction review or an epilogue of an earlier sclaude ran."""
    import subprocess
    import claude_usage
    from session_end import SESSION_ID, next_link
    feature = os.path.dirname(state_path)
    tree = os.path.dirname(os.path.dirname(os.path.dirname(feature)))
    try:
        common = subprocess.run(["git", "-C", tree, "rev-parse", "--path-format=absolute",
                                 "--git-common-dir"], capture_output=True, text=True,
                                timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        common = ""
    own = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    folders = []
    for where in (tree, os.path.dirname(common) if common else "", own):
        folder = os.path.join(claude_usage.ROOT, claude_usage.project_name(where)) if where else ""
        if folder and folder not in folders:
            folders.append(folder)
    cache_path = os.path.join(feature, process_history.TRANSCRIPT_CACHE)
    try:
        with open(cache_path) as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    changed = []

    def one(path):
        try:
            st = os.stat(path)
        except OSError:
            return None
        stamp = [st.st_size, st.st_mtime_ns]
        held = cache.get(path)
        # A conversation still going grows between two polls: read again
        # at most once a minute, not its whole transcript every poll.
        # A summary from an older reader lacks a field: read again.
        if held and len(held) == 3 and held[1].get("v") == claude_usage.VERSION \
                and (held[0] == stamp or time.time() - held[2] < process_history.TRANSCRIPT_FRESH):
            return held[1]
        whole = claude_usage.read(path)
        if whole is None:
            return None  # not read: tried again next time, not kept as empty
        summary = {"human": whole.get("human") or [], "cost": whole.get("cost"),
                   "expired": whole.get("expired") or [], "v": claude_usage.VERSION}
        cache[path] = [stamp, summary, time.time()]
        changed.append(path)
        return summary

    def after(path):
        """The transcript a conversation was carried on in, or None: one
        link of session_end.chain (next_link), kept as `one` keeps its
        summaries. A successor named but not on disk yet is looked for again
        next time."""
        st = os.stat(path)
        stamp, key = [st.st_size, st.st_mtime_ns], "next:" + path
        held = cache.get(key)
        if held and len(held) == 3 and (held[0] == stamp or time.time() - held[2] < process_history.TRANSCRIPT_FRESH):
            nxt = held[1]
        else:
            try:
                sid = next_link(path)
            except OSError:
                raise  # read again next time, not kept as "no link"
            nxt = os.path.join(os.path.dirname(path), sid + ".jsonl") if sid else None
            cache[key] = [stamp, nxt, time.time()]
            changed.append(key)
        # The link is kept even before its transcript is there: a stat on
        # every poll, not a read of the whole file.
        return nxt if nxt and os.path.isfile(nxt) else None

    def read(session):
        """A conversation as its last transcript holds it whole: Claude Code
        carries one on under a new id by copying it, the rule
        session_end.chain reads it by."""
        if not SESSION_ID.match(session or ""):
            return None
        found = [p for p in (os.path.join(f, session + ".jsonl") for f in folders) if os.path.isfile(p)]
        if not found:
            return None
        last = found[0]
        seen = set()
        while last not in seen:
            seen.add(last)
            # A link not read leaves the conversation unknown this time: an
            # earlier transcript taken for the last would count it twice.
            try:
                nxt = after(last)
            except OSError:
                return None
            if not nxt:
                break
            last = nxt
        summary = one(last)
        return dict(summary, id=last) if summary else None

    def done():
        if changed:
            # Transcripts gone (a tree cleaned up by hand) leave no keys.
            for key in [k for k in cache if not os.path.exists(k.replace("next:", "", 1))]:
                del cache[key]
            tmp = "%s.%d.tmp" % (cache_path, os.getpid())
            try:
                with open(tmp, "w") as fh:
                    json.dump(cache, fh)
                os.replace(tmp, cache_path)
            except OSError:
                pass
    read.done = done
    # The local review's passes, each a conversation of its own, for metrics
    # to price on their block: every caller of history gets them so.
    from local_review import rows as journal_rows
    read.passes = journal_rows(os.path.join(feature, process_history.LOCAL_JOURNAL), with_spent=True)
    return read


def read_history(state_path):
    """The rows of the history file beside a state."""
    lines = []
    try:
        with open(os.path.join(os.path.dirname(state_path), process_history.HISTORY_FILE)) as fh:
            for line in fh:
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return lines
