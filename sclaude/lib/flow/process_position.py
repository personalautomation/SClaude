# Where a feature stands: the node of the map its state.json points at, and
# what is running or waiting there.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import datetime

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_config, process_doc, process_history, process_model


# --- where a feature stands --------------------------------------------------

def _runs(node):
    return [r for r in ((node or {}).get("runs") or []) if isinstance(r, dict)]


# The waits with no conversation the feature stands in while its position
# names them: the merge's and QA's look. A deploy or a local pass named by
# the position is the next thing to do, not one going on.
WAITS_HERE = ("merge_wait", "qa_check")


def _unseen_end(began, run, places):
    """Where a sitting with no end row ended: the earliest of the next place
    begun after it (a pass run inside it is not the feature leaving it) and
    the last line its run wrote (any line when it names no run); a bound
    before the sitting began says nothing of it."""
    start = process_history._when(began)
    later = next((p["from"] for p in places.list
                  if "n" in p and process_history._when(p.get("from")) and start and process_history._when(p["from"]) > start), None)
    ends = [x for x in (later, places.last_of.get(run) if run else places.last)
            if process_history._when(x) and start and process_history._when(x) >= start]
    return min(ends, key=process_history._when) if ends else began


def _session_going(state, key):
    """Whether sclaude's state has the conversation of a step, the
    retrospective or the epilogue (its key) open now, as the position takes
    it however long ago it began (`_open`), or a sync going, as its badge
    takes it (`_going`)."""
    node = (state.get("steps") or {}).get(key) or state.get(key)
    runs = _runs(node) if isinstance(node, dict) else []
    return bool(runs) and (_going if key == "sync" else _open)(runs[-1])


def _fix_open(state, stage):
    words = (((state.get("regression") or {}).get(stage) or {}).get("fix_status") or "").split()
    return bool(words) and words[-1] == "open"


def _when_iso(text):
    try:
        when = datetime.datetime.fromisoformat(text or "")
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else None


def _recent(when):
    """A start believed: less than three hours ago. One left by a run that
    was killed stays behind."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return bool(when) and (now - when).total_seconds() < 3 * 3600


def _fresh(text):
    return _recent(_when_iso(text))


def _running(state, stage):
    run = (state.get("regression") or {}).get(stage) or {}
    return run.get("status") == "running" and _fresh(run.get("started"))


def _going(run):
    """A session's run going now: not ended, or taken up again after its end
    (session_runs' resumed), and begun or taken up less than three hours
    ago. One left unfinished has an end, and is not going."""
    if not run or run.get("done"):
        return False
    began = _when_iso(run.get("resumed")) or _when_iso(run.get("started"))
    ended = _when_iso(run.get("finished"))
    return _recent(began) and (not ended or began > ended)


def _sync_in_step(state):
    """A sync with main going during a step: the sync before the step's
    session, or one asked for from the menu. One left unfinished is not where
    the feature stands — the step opens on the branch as it is
    (sync_broken_off)."""
    sync = _runs(state.get("sync"))
    return bool(sync) and _going(sync[-1])


def _friction_open(state):
    """A friction review open holds the next step (f_hold)."""
    return any(runs and not runs[-1].get("done")
               for runs in (_runs(v) for v in (state.get("friction") or {}).values() if isinstance(v, dict)))


def _open(run):
    """A run not ended, or taken up again after its end (session_runs'
    resumed): open however long ago it began, as the retrospective is."""
    if not run or run.get("done"):
        return False
    resumed, ended = _when_iso(run.get("resumed")), _when_iso(run.get("finished"))
    return not ended or bool(resumed and resumed > ended)


def _session_node(state, session):
    """The block of the session's run, while it is open."""
    places = [("steps.%s" % step, step) for step in ((state.get("steps") or {}))]
    places += [("retro", "retro"), ("sync", "sync"), ("epilogue", "epilogue")]
    for path, nid in places:
        node = state
        for part in path.split("."):
            node = (node or {}).get(part) if isinstance(node, dict) else None
        for run in _runs(node if isinstance(node, dict) else None):
            if run.get("session") == session and _open(run):
                return nid
    return ""


def busy(state, workshop=None):
    """The F and W badges at work now, {block: [flags]}: a friction review
    open behind the session it follows (its key is the step and a number,
    review-3, fix-local-1), and a session the workshop's record lets write
    sclaude (workshop, .sclaude/local/instruments.json) while its run is
    open."""
    out, drawn = {}, process_config.all_nodes()
    for key, node in (state.get("friction") or {}).items():
        runs = _runs(node) if isinstance(node, dict) else []
        nid = key.rsplit("-", 1)[0].replace("-", "_")
        if runs and not runs[-1].get("done") and "F" in drawn.get(nid, ("",) * 6)[5]:
            out.setdefault(nid, []).append("F")
    for session in (workshop or {}).get("approved") or []:
        nid = _session_node(state, session)
        if nid and "W" in drawn.get(nid, ("",) * 6)[5] and "W" not in out.get(nid, []):
            out.setdefault(nid, []).append("W")
    # R: a suite running, or a session fixing what it found, on the block the
    # stage runs from; S: a sync with main going, on the step it runs ahead
    # of, or on the preview once the steps are done.
    step = state.get("step") or "plan"
    at_step = step if step in process_model.NODES else "review"
    for stage, block in (("local", at_step), ("preview", "preview"), ("prod", "prod")):
        fixing = _fix_open(state, stage)
        if _running(state, stage) or fixing:
            nid = "review" if fixing and stage != "local" else block
            if "R" in process_model.NODES.get(nid, ("",) * 6)[5] and "R" not in out.get(nid, []):
                out.setdefault(nid, []).append("R")
    sync = _runs(state.get("sync"))
    if sync and _going(sync[-1]):
        nid = _sync_block(state)
        if "S" in process_model.NODES.get(nid, ("",) * 6)[5]:
            out.setdefault(nid, []).append("S")
    return out


def _sync_block(state):
    """The block a sync with main runs ahead of: the step's, or once the steps
    are done the preview, the hand-over after QA's yes, the merge's wait."""
    step = state.get("step") or "plan"
    if step in process_model.NODES and step != "done":
        return step
    if state.get("handoff"):
        return "merge_wait"
    return "handoff" if (state.get("qa") or {}).get("accepted") else "preview"


def stalled(state, pr_state=""):
    """A sync with main broken off once the steps are done, its pull request
    open, {block: {"S": text}}: the feature stands there until the person runs
    it again (_past_steps). One broken off in a step is not: the step opens on
    the branch as it is (_sync_in_step); nor once the pull request is merged
    or closed, when there is nothing left to sync."""
    sync = _runs(state.get("sync"))
    if (state.get("step") != "done" or pr_state != "OPEN" or state.get("no_change")
            or not sync or sync[-1].get("done") or _going(sync[-1])):
        return {}
    nid = _sync_block(state)
    if "S" not in process_model.NODES.get(nid, ("",) * 6)[5]:
        return {}
    return {nid: {"S": "broken off — `sclaude sync %s` takes it up again" % (state.get("feature") or "<name>")}}


# Why a letter stands on a block: (block, letter) -> a sentence, else the
# letter's own words (FLAG_WORDS). The glance's blocks borrow
# their step's (ALIAS).
BADGE_WHY = {
    ("plan", "S"): "S — main is merged into the branch before the plan's session opens; a conflict goes to the sync first.",
    ("code", "S"): "S — main is merged in before step 2's session opens; a conflict goes to the sync first.",
    ("pr", "S"): "S — main is merged in before step 3, so the pull request carries what will merge.",
    ("review", "S"): "S — main is merged in before each review round.",
    ("preview", "S"): "S — the branch must merge with main before its preview is deployed.",
    ("merge_wait", "S"): "S — every 2 min the wait checks whether main moved into a conflict, and a later run checks main before the hand-over; a conflict goes to the sync, commits from elsewhere take the hand-off back, and the run goes to the preview again.",
    ("handoff", "S"): "S — before the hand-over main is checked; a conflict goes to the sync, and the run to the preview and QA again, as do commits that reached the branch from elsewhere.",
    # The glance's QA and merge, which carry their own S (OVERVIEW_NODES).
    ("qa_check", "S"): "S — once QA accepted, main is checked before the hand-over; a conflict goes to the sync, and the run to the preview and QA again, as do commits that reached the branch from elsewhere.",
    ("merge", "S"): "S — while the merge waits, main is checked every 2 min; a conflict goes to the sync, the PR back to a draft, and the run to the preview again.",
    ("code", "R"): "R — after your yes the local suite runs against this feature's server; red opens a fixing session, two at most.",
    ("review", "R"): "R — a red preview or production comes back here to be fixed.",
    ("review_close", "R"): "R — the local suite runs again before step 4 closes; red opens a fixing session, two at most.",
    ("local_pass", "S"): "S — main is merged in when step 4 starts or is taken up again, before the local review's pass; a conflict goes to the sync first.",
    ("preview", "R"): "R — the preview suite runs against this deployment; green sends the issue to QA, red back to step 4.",
    ("prod", "R"): "R — production's suite runs after the ship; red is rolled back first, then fixed from step 4 — or held.",
    ("plan", "F"): "F — what the safety rules refused the plan's session is reviewed once it ends.",
    ("code", "F"): "F — what the safety rules refused step 2's session is reviewed once it ends.",
    ("pr", "F"): "F — what the safety rules refused step 3's session is reviewed once it ends.",
    ("friction_left", "F"): "F — the friction reviews still owed run here, one after another, before the retrospective.",
    ("review", "F"): "F — what the safety rules refused a review round is reviewed when the round goes to a fresh session.",
    ("retro", "W"): "W — the retrospective may fix what it found in sclaude, in the workshop; its approved plan is the yes.",
    ("f_review", "W"): "W — a bug in sclaude the review finds it fixes in the workshop; its approved plan is the yes.",
    ("f_monthly", "W"): "W — the monthly review makes a change to sclaude it decides on in the workshop; its approved plan is the yes.",
    ("sync", "F"): "F — what got in the sync session's way is reviewed once it ends, as after a step's session.",
}


def badge_why(nid, flag):
    base = process_model.ALIAS.get(nid, nid)
    return BADGE_WHY.get((base, flag)) or "%s — %s" % (flag, process_doc.FLAG_WORDS.get(flag, ""))


def _hhmm(text):
    when = _when_iso(text)
    return when.astimezone().strftime("%H:%M") if when else ""


def busy_notes(state, workshop=None):
    """How the work behind each turning letter goes, {block: {letter: text}},
    from what the state holds: since when, which attempt, what is open."""
    out = {}
    for nid, flags in busy(state, workshop).items():
        for flag in flags:
            text = ""
            if flag == "R":
                for stage in ("local", "preview", "prod"):
                    run = (state.get("regression") or {}).get(stage) or {}
                    if _running(state, stage):
                        tries = str(run.get("attempts") or 0)
                        # attempts: the fixing attempts the stage has used of
                        # its two (regression.sh), given back after a yes to
                        # another or a session that spent nothing.
                        text = "now: the %s suite, running since %s%s" % (
                            stage, _hhmm(run.get("started")),
                            "" if tries == "0" else " (fixing attempts used: %s)" % tries)
                    elif _fix_open(state, stage):
                        text = "now: a session fixing the red %s suite" % stage
            elif flag == "S":
                sync = _runs(state.get("sync"))
                text = "now: a sync with main, since %s" % _hhmm((sync[-1].get("resumed") or sync[-1].get("started"))) \
                    if sync else ""
            elif flag == "F":
                open_ = [(k, _runs(v)[-1]) for k, v in (state.get("friction") or {}).items()
                         if isinstance(v, dict) and _runs(v) and not _runs(v)[-1].get("done")
                         and k.rsplit("-", 1)[0].replace("-", "_") == nid]
                if open_:
                    key, run = open_[-1]
                    text = "now: friction review %s open since %s — it holds the next step" % (key, _hhmm(run.get("started")))
            elif flag == "W":
                ready = (workshop or {}).get("ready") or {}
                text = "now: changing sclaude" + (
                    "; ready at %s, published when the session ends" % str(ready.get("head", ""))[:7]
                    if ready.get("head") else "; not marked ready yet")
            if text:
                out.setdefault(nid, {})[flag] = text
    return out


def prod_held(state):
    """As prod_red_hold's condition: production carries the feature and its
    last run there was not green, and it was not rolled back. Carried is read
    from the state, not from GitHub as prod_carries_feature does it: the
    pull request production was shipped for is the feature's pull request now
    — a fix sent forward in a new one is not in that release — and with no
    pull request nothing is carried. A ship recorded before deploy.prod.pr was
    kept counts as carried."""
    reg = (state.get("regression") or {}).get("prod") or {}
    prod = (state.get("deploy") or {}).get("prod") or {}
    rolled = ((state.get("rollback") or {}).get("prod") or {}).get("code") == "done"
    pr = state.get("pr")
    carried = bool(prod.get("sha")) and bool(pr) and prod.get("pr") in (None, pr)
    # failed alone, as regression_status reads it: a run that could not run
    # is recorded failed too, and one cut off midway is not a hold.
    return carried and not rolled and reg.get("status") == "failed"


def position(state, pr_state="", epilogue=None):
    """The detailed node a feature stands on, and a line saying why.

    pr_state is GitHub's word for the branch's pull request (OPEN, MERGED,
    CLOSED, or "" when it did not answer); epilogue the epilogue's own record
    (~/.claude/sclaude/epilogue/<feature>.json), when there is one."""
    step = state.get("step") or "plan"
    if step != "done":
        node, why = _in_step(state, step)
        if _friction_open(state):
            why += "; an open friction review holds the next step"
        return node, why
    return _past_steps(state, pr_state, epilogue)


def _in_step(state, step):
    if _sync_in_step(state):
        return "sync", "a sync with main is open, ahead of the step"
    # A feature built in parts (parts.sh) is in step 2 while its parts are:
    # code, pull request and review of the part at work.
    parts = state.get("parts") or {}
    if (isinstance(parts.get("total"), int) and parts["total"] >= 2 and parts.get("done") is not True
            and step in ("code", "pr", "review")):
        if step in ("code", "review") and _running(state, "local"):
            return "reg_local", "part %s/%s: the local regression is running" % (parts.get("current"), parts["total"])
        if step == "review" and _fresh(((state.get("review") or {}).get("local") or {}).get("running")):
            return "local_pass", "part %s/%s: the local review is reading its pull request" % (
                parts.get("current"), parts["total"])
        return "p_" + step, "step 2, part %s/%s: %s" % (
            parts.get("current"), parts["total"], {"code": "development", "pr": "its pull request",
                                                  "review": "its review"}[step])
    if step in ("code", "review") and _running(state, "local"):
        return "reg_local", "the local regression is running"
    if step == "code" and _fix_open(state, "local"):
        return "fix_local", "a session is fixing the local regression"
    if step == "review":
        for stage in ("prod", "preview"):
            if _fix_open(state, stage):
                return "fix_" + stage, "a session is fixing the %s regression" % stage
        if _fix_open(state, "local"):
            return "fix_local", "a session is fixing the local regression"
        if _fresh(((state.get("review") or {}).get("local") or {}).get("running")):
            return "local_pass", "the local review is reading the pull request"
    return (step if step in process_model.NODES else "plan"), "step %s" % step


def _past_steps(state, pr_state, epilogue):
    if state.get("no_change"):
        if state.get("friction_owed"):
            return "friction_left", "a friction review still owed waits before the retrospective: sclaude done at the terminal"
        return "cleanup", "no change to the code: only the clean-up is left"
    if pr_state == "OPEN":
        runs = _runs(state.get("sync"))
        if runs and not runs[-1].get("done"):
            return "sync", "a sync with main is open"
        if _running(state, "preview"):
            return "preview", "the preview regression is running"
        qa = state.get("qa") or {}
        if state.get("handoff") or qa.get("accepted"):
            return "merge_wait", "QA accepted it; the pull request waits for the merge"
        if qa.get("sha"):
            return "qa_check", "the preview is with QA"
        return "preview", "next: the preview, then QA"
    if pr_state == "MERGED":
        # As remind_prod holds: only once the pull request is merged. A fix
        # going round on a pull request of its own is not held, though the
        # red run it answers stays recorded until the next ship.
        # A run going on is said first: one started from the hold leaves its
        # unrunnable mark until it ends.
        if _running(state, "prod"):
            return "prod", "the production regression is running"
        # Not bounded in time: the answer may take a night (remind_prod).
        if (state.get("prod_pass") or {}).get("shipping"):
            return "ship", "asked whether to ship to production, or shipping"
        if prod_held(state):
            return "hold_ways", "production carries the feature, and its last run was not green"
        retro = _runs(state.get("retro"))
        if not retro and ((state.get("steps") or {}).get("review") or {}).get("friction_held"):
            return "friction_left", "a friction review held in step 4 comes before the retrospective"
        if state.get("friction_owed"):
            return "friction_left", "a friction review still owed waits before the retrospective: sclaude done at the terminal"
        last = retro[-1] if retro else {}
        # Resumed, a retrospective keeps the end it had (session_runs): it is
        # open again while taken up after that end.
        resumed, ended = _when_iso(last.get("resumed")), _when_iso(last.get("finished"))
        again = bool(resumed and ended and resumed > ended)
        # The tree is still here, so the clean-up was not done: not asked yet,
        # or declined (kept) — sclaude done asks it again.
        if retro and last.get("done") and not again:
            return "cleanup", "the retrospective ran; the clean-up is left: sclaude done asks it"
        if retro:
            return "retro", "the retrospective is open: running, or broken off"
        epi = epilogue or {}
        if epi.get("session") and not epi.get("done"):
            return "epilogue", "the epilogue broke off"
        return "done_cmd", "merged: the retrospective and the clean-up are next"
    if pr_state == "CLOSED":
        return "cleanup", "the pull request was closed without a merge"
    return "preview", "past step 4; GitHub did not say where the pull request is"
