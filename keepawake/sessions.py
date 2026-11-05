# keepawake's Telegram bot — the state of the steps' sessions: which claude
# runs where, how full its cache is, and the list of features with what each is
# doing.
#
# Part of the bot that keepawake/telegramd.py runs.

import glob
import json
import logging
import os
import shlex
import time

import statusline
from keepawake.i18n import t
from keepawake import asks, menus, project_config, repos, shell, status_report, topics


log = logging.getLogger("keepawake")


# --- the state of steps' sessions --------------------------------------------


# One answer serves a press: a card asks for the sessions several times over
# (its session, the one in its worktree, its state), and each ask is a Node
# process.
AGENTS_FRESH = 3
_AGENTS = {"at": 0.0, "list": [], "ok": False}


def agents():
    # Live claude sessions, interactive and background. It needs no terminal, so
    # it is available to the daemon too. Empty on any trouble: no claude, no
    # answer, broken JSON — the card simply will not show the state.
    now = time.time()
    if now - _AGENTS["at"] < AGENTS_FRESH:
        return _AGENTS["list"]
    out = shell.run("claude agents --json", timeout=20)
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    # ok: whether Claude Code answered — an empty list is then no sessions,
    # not a call that failed.
    _AGENTS.update(at=time.time(), list=data if isinstance(data, list) else [],
                   ok=isinstance(data, list))
    return _AGENTS["list"]


def session_state(session_id, cache=None):
    # What a step's session is busy with: working / blocked / idle, or empty if
    # there is none.
    #
    # cache is a list already obtained from agents(): the call shells out with a
    # timeout, and there is no reason to ask once per feature where there are
    # several. Whoever iterates the list passes it; for a single question it can
    # be left out.
    if not session_id:
        return ""
    for a in (agents() if cache is None else cache):
        if isinstance(a, dict) and a.get("sessionId") == session_id:
            return a.get("state") or a.get("status") or "idle"
    return ""


# Where Claude Code keeps each session's transcript, a directory per project.
CLAUDE_PROJECTS = os.path.expanduser("~/.claude/projects")


def feature_busy(repo, slug):
    """Whether the feature is at work: its session in any state but idle, or
    its orchestrator alive and waiting on a question — between steps there
    is no session, and a second orchestrator would be two conversations
    about one thing all the same."""
    if asks.pending_ask(os.path.join(asks.ask_dir(repo), "ask", slug)):
        return True
    session, _step = feature_session(repo, slug)
    return bool(session) and session_state(session) not in ("", "idle")


def cache_left(session_id, now=None):
    """Seconds the session's prompt cache has left — 0 once it has expired —
    or None when its transcript says nothing. The same reckoning as the
    status line's: the last request's time plus the TTL it was written with."""
    if not session_id:
        return None
    paths = glob.glob(os.path.join(CLAUDE_PROJECTS, "*",
                                   glob.escape(session_id) + ".jsonl"))
    last = statusline.last_request(paths[0]) if paths else None
    if not last:
        return None
    when, _usage, ttl = last
    return max(0, when + ttl - (time.time() if now is None else now))


def cache_note(session_id):
    """The card's line on the session's cache, "" when nothing is known."""
    left = cache_left(session_id)
    if left is None:
        return ""
    if not left:
        return t("feat.cachegone")
    return t("feat.cache", m=int((left + 59) // 60))


def state_path(wt):
    """A feature's state.json, in the old .feature/ when an older sclaude
    still runs the tree: layout_migrate leaves it there until that sclaude is
    done, and the feature went missing from the bot meanwhile."""
    new = os.path.join(wt, ".sclaude/local/feature", "state.json")
    old = os.path.join(wt, ".feature", "state.json")
    return new if os.path.exists(new) or not os.path.exists(old) else old


def feature_state(repo, slug):
    # A feature's whole state — the very file with which the orchestrator ties
    # the steps together. An empty dictionary if there is no feature: the card
    # will then show what it knows from the table.
    path = state_path(topics.feature_wt(repo, slug))
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def feature_session(repo, slug):
    # The session id of the feature's current step, and the step itself.
    #
    # Past the four steps — the epilogue, the retrospective — a session is
    # kept elsewhere than under steps, and a feature with one open read as
    # having none: "not running", and Continue free to open a second
    # conversation beside it. A live Claude session working in the feature's
    # worktree is the feature's, whatever the state names.
    data = feature_state(repo, slug)
    step = data.get("step") or ""
    node = (data.get("steps") or {}).get(step) or {}
    session = node.get("session") or ""
    if not session or not session_state(session):
        live = session_in(topics.feature_wt(repo, slug))
        session = live or session
    return session, step


def session_in(wt):
    """The id of a live Claude session working in the worktree, or ""."""
    if not wt:
        return ""
    root = os.path.realpath(wt)
    for a in agents():
        cwd = os.path.realpath(a.get("cwd") or "") if isinstance(a, dict) else ""
        if cwd == root or cwd.startswith(root + os.sep):
            return a.get("sessionId") or ""
    return ""


def feature_links(repo, slug):
    # The feature's issue and pull request. The numbers here are exact — the
    # orchestrator put them there itself — so there is no need to parse a
    # commit's text as in the repository's card.
    #
    # The issue first: it holds the statement of what all this is being done
    # for, whereas the PR appears only at the third step and until then simply
    # does not exist.
    data = feature_state(repo, slug)
    slug_gh = repos.gh_slug(repo)
    if not slug_gh:
        return []
    links = []
    issue = data.get("issue")
    if issue:
        links.append((t("repo.issue", n=issue),
                      "https://github.com/%s/issues/%s" % (slug_gh, issue)))
    pr = data.get("pr")
    if pr:
        links.append((t("repo.pr", n=pr),
                      "https://github.com/%s/pull/%s" % (slug_gh, pr)))
    return links


def start_sclaude(repo, args):
    # Starting the orchestrator in the background.
    #
    # We detach through setsid and do not wait: sclaude lives as long as the
    # conversation does — minutes and hours — while the bot has to be back at
    # getUpdates within seconds. Waiting for it here would mean hanging the
    # whole chat for the duration of the step.
    #
    # The conversation goes on through the channel: the bot will pick the
    # questions up on the loop's turns.
    cmd = "cd %s && setsid sclaude %s < /dev/null > /dev/null 2>&1 &" % (
        shlex.quote(repo), " ".join(shlex.quote(a) for a in args))
    shell.run(cmd, timeout=15)
    log.info("started sclaude %s in %s", " ".join(args), repo)


def feature_card(name, slug, feats=None):
    if feats is None:
        feats, _ = repos.features_of_name(name)
    row = next((r for r in feats if r[0] == slug), None)
    if not row:
        return t("feat.gone", slug=status_report.escape(slug))
    repo = repos.repo_path(name)
    session, _step = feature_session(repo, slug) if repo else ("", "")
    state = session_state(session)
    # Claude Code names the states its own way and adds to them: "waiting" is
    # a session that asks the person something. A state not known here is
    # still an open session, never "none is open".
    if not state:
        note = (t("feat.nosessiondone") if " done" in row[1] or row[1].startswith("all done")
                else t("feat.nosession"))
    else:
        note = {"working": t("feat.working"), "busy": t("feat.working"),
                "blocked": t("feat.blocked"), "waiting": t("feat.blocked")}.get(
                    state, t("feat.idle"))
        # How long the open session stays cheap to go on with: on the page,
        # drawn anew at each press. A card in the chat would keep the minutes
        # it was drawn with.
        if menus.ON_PAGE:
            note += cache_note(session)
    return t("feat.card", repo=status_report.escape(name), slug=status_report.escape(slug),
             step=status_report.escape(row[1]), wt=status_report.escape(row[2] or "—"), session=note,
             links=repos.links_line(feature_links(repo, slug)) if repo else "")


# How many features get buttons. Eight: more rows do not fit on a phone's
# screen, and below them there are still "new feature" and three exits. Those
# that did not fit are named in a line in repo_text — they must not disappear
# from the chat.
FEATURE_BUTTONS = 8


def features_keyboard(name):
    # The second level: the selected repository's features, a button each.
    # The step and the actions on a feature are on its card, in its topic, and
    # the button takes it there (the topic: callback).
    rows = []
    feats, _ = repos.features_of_name(name)
    for slug, step, _wt in feats[:FEATURE_BUTTONS]:
        label = "%s — %s" % (slug, step)
        # We cut shorter than before. Telegram splits a row between buttons
        # evenly by their number rather than by the text's length, so a lone cog
        # will take half the row however briefly it is labelled. A short label on
        # the left does not change that — but it does stop the label being
        # truncated beyond recognition at half width.
        # Telegram refuses the whole keyboard for one button over 64 bytes.
        # The remembered repository may be left out of the data — the press
        # finds it again; any other, and a feature longer still, get a button
        # that does nothing rather than vanish from a list that counts them.
        data = "topic:%s:%s" % (name, slug)
        if len(data.encode("utf-8")) > 64 and name == os.path.basename(repos.repo_choice()):
            data = "topic::" + slug
        if len(data.encode("utf-8")) > 64:
            # Still listed, as the header counts it: open it from the terminal.
            data = "noop"
        rows.append([{"text": label[:60], "callback_data": data}])
    rows.append([{"text": t("feat.new"), "callback_data": "newfeat:" + name}])
    rows.append([{"text": t("cfg.button"), "callback_data": project_config.cfg_data("cfg", name)}])
    # Two exits, not one. "To the repositories" is a step one level up within
    # the section; "Back" goes to the main menu, which is where people arrive
    # here from with the Sclaude button. Without the second the way out was
    # roundabout: features → repositories → Settings, that is into a neighbouring
    # branch rather than back where they came from.
    rows.append([{"text": t("repo.refresh"), "callback_data": "repo:" + name},
                 {"text": t("repo.torepos"), "callback_data": "svc_repos"}])
    rows.append([{"text": t("menu.back"), "callback_data": "menu_back"}])
    return rows
