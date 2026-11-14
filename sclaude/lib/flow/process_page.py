# A feature's own page: the map with where the feature stands, played back
# along its history, and kept live.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import json

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import page_asset  # noqa: E402
import process_config, process_diagram, process_doc, process_model




# --- a feature's page --------------------------------------------------------

LIVE_SCRIPT = page_asset.read(__file__, "process_live.js")

# How the feature went, played on its maps (`history` above). ▶ by a map's
# heading plays the whole way on that map: a place lights with a clock
# counting the time it stood there, then the arrow it left by; a friction
# review or a workshop pass jumps to its own map and back. By the friction
# review's and the workshop's headings ▶ plays the pass chosen beside it.
# A place entered again keeps its count: "×2 · 3 h 10 min".
PLAY_SCRIPT = page_asset.read(__file__, "process_play.js")

PLAY_STYLE = page_asset.read(__file__, "process_play.css")


def play_head(map_name, label, passes=False):
    """▶ beside a map's heading; for a map of passes, the choice of one."""
    out = '<button type="button" class="play" data-play="%s" data-label="%s" title="Play how the feature went" disabled>▶</button>' \
        % (map_name, process_diagram.esc(label))
    out += '<span class="mt-map" data-map="%s"></span>' % map_name
    if passes:
        out += '<select class="pass" data-pass="%s" aria-label="Which pass" disabled><option>no pass yet</option></select>' \
            % map_name
    return out


PLAYER_BAR = """<div id="player" hidden><button type="button" class="pl-pause" title="Pause">⏸</button>
<select class="pl-speed" aria-label="Speed"><option value="0.5">×0.5</option><option value="1" selected>×1</option><option value="2">×2</option>
<option value="4">×4</option><option value="8">×8</option><option value="16">×16</option></select>
<label class="pl-stay" title="Play the feature on this map alone: the friction reviews, regressions and syncs it went through are left out, not opened on their own maps"><input type="checkbox"> this map only</label><span class="pl-text"></span>
<button type="button" class="pl-stop" title="Stop (Esc)">✕</button></div>
<div id="pl-off" role="dialog" aria-labelledby="pl-off-h" hidden><h3 id="pl-off-h">⚠ The feature left the map here</h3>
<p class="pl-off-what"></p><p class="pl-off-when muted"></p>
<p class="muted">The way it took is not drawn: the map, or the code, is wrong here.</p>
<button type="button" class="pl-off-go">Play on</button> <button type="button" class="pl-off-stop">Stop</button></div>"""


LIVE_STYLE = page_asset.read(__file__, "process_live.css")

# The review's map, over the lower half of the page while a review step is
# in view (process_review.js, from sclaude/lib/review/review_map.py).
REVIEW_SCRIPT = page_asset.read(__file__, "process_review.js")
REVIEW_STYLE = page_asset.read(__file__, "process_review.css")
REVIEW_PANEL = """<div id="rv" role="region" aria-label="The review map" hidden><div class="rv-top"><h3>📊 The review</h3>
<span class="rv-sum muted">…</span>
<span class="rv-mode" role="radiogroup" aria-label="Icicles"><label title="Join the files one fix touched: one thread, or one subagent's work"><input type="radio" name="rv-mode" value="fix"> by fix</label><label title="One icicle a file, splitting where its changes part, never joined to another"><input type="radio" name="rv-mode" value="file"> by file</label></span>
<label title="The person's answers and threads"><input type="checkbox" class="rv-hands" checked> ✋</label>
<button type="button" class="rv-centre" title="Bring the review step back to the middle">⌖</button>
<button type="button" class="rv-off" title="Do not show the review's details; the 📊 button brings them back">✕ hide</button></div>
<div class="rv-legend"></div><div class="rv-body"></div></div>
<button type="button" id="rv-chip" hidden title="Show the review's map">📊 Review map</button>"""


def page(label, cfg=None, demo=None):
    """A feature's map: the same drawing as its project's config draws it,
    with its place lit and its actions, kept current by polling
    /__sclaude/flow/state. `demo` is (address, title) of the feature's latest
    recorded demo (skills/sdemo), linked beside the feature, or None."""
    with process_model.configured(process_config.example_config() if cfg is None else cfg):
        return _page(label, demo)


def lit_with():
    """What each place lights besides itself: its overview block, and the
    whole process's block it happens inside when only a smaller map draws it."""
    lit = {k: [v] if v else [] for k, v in process_model.POSITIONS.items()}
    for k, host in process_model.HOSTS.items():
        drawn = process_config.on_map(host)
        if drawn and drawn not in lit.setdefault(k, []):
            lit[k].append(drawn)
    return lit


def _page(label, demo=None):
    detail = process_diagram.Diagram(*process_config.node_sets()[0])
    overview = process_diagram.Diagram(*process_config.node_sets()[1])
    script = LIVE_SCRIPT.replace("/*LABEL*/", json.dumps(label)).replace(
        "/*POSITIONS*/", json.dumps(lit_with()))
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
""" + page_asset.tab_icon("🗺") + """
<title>%s — sclaude map</title>
<style>%s%s</style></head><body><main>
<p class="muted"><a href="/__sclaude/">features</a> · <a href="/__sclaude/select?f=%s">open the feature</a>%s</p>
<h1>%s</h1>
%s
<div class="metrics"><span class="muted">Show on the maps:</span>
<label title="Each time you stepped in: a message to Claude after its turn, an answer to its question or to sclaude's, a command run on the feature"><input type="checkbox" value="input"> ✋ your input <b class="mt-total" data-kind="input"></b></label>
<label title="What Claude Code's own account says each conversation cost"><input type="checkbox" value="cost"> $ Claude's cost <b class="mt-total" data-kind="cost"></b></label>
<label title="How long a question waited for your answer — Claude's, after its turn or its question, and sclaude's own — the whole of it, nights included"><input type="checkbox" value="wait"> ⏳ waiting for you <b class="mt-total" data-kind="wait"></b></label>
<label title="How many times Claude's prompt cache had expired and a conversation's context was written to it again — usually after a pause longer than the cache lives; each costs a fresh write of the whole context"><input type="checkbox" value="expired"> ♻ cache rebuilt <b class="mt-total" data-kind="expired"></b></label>
<label title="How long the feature stood on each place, every stay added up — what the player's clock shows; ⚠ where a conversation ended with no end written (a Ctrl-C, a terminal that died) and its time is a guess, up to the last line it wrote"><input type="checkbox" value="time"> ⏱ time in the step <b class="mt-total" data-kind="time"></b></label></div>
<div class="live" style="margin-top:14px">
<div>
<h2 class="first-map" id="map-detail">The whole process%s</h2>
<div class="card detail-card">%s</div>
<h2 id="map-overview">The cycle at a glance%s</h2><div class="card mini">%s</div>
<h2 id="map-workshop">How a session changes sclaude%s</h2><div class="card mini">%s</div>
<h2 id="map-friction">The friction review%s</h2><div class="card mini">%s</div>
<h2 id="map-regression">A stage's regression%s</h2><div class="card mini">%s</div>
<h2 id="map-sync">Main and the branch%s</h2><div class="card mini">%s</div>
<h2 id="map-parts">A feature built in parts%s</h2><div class="card mini">%s</div>
<h2 id="commands">Every command</h2>%s
</div>
<aside class="panel">
<div class="tabs" role="tablist"><button type="button" data-tab="actions" class="on">Actions</button><button type="button" data-tab="history">History</button></div>
<div class="tab" id="tab-actions">
<div class="muted" id="stamp">…</div>
<h3>Where it stands</h3><div id="where">…</div><div class="muted" id="why"></div>
<h3>What you can do now</h3><ul id="acts"></ul>
<p id="err"></p>
</div>
<div class="tab" id="tab-history" hidden>
<p class="muted">Played: <b id="hist-what">The whole process</b>. Click a place to play from it.</p>
<ul id="hist"></ul>
</div>
</aside>
</div>
<button id="clear" type="button" hidden>Clear the selection</button>
%s
%s
</main><script>%s%s%s%s%s</script></body></html>
""" % (process_diagram.esc(label), process_diagram.STYLE, LIVE_STYLE + PLAY_STYLE + REVIEW_STYLE, process_diagram.esc(label),
       ' · <a href="%s">🎬 demo: %s</a>' % (process_diagram.esc(demo[0]), process_diagram.esc(demo[1])) if demo else "",
       process_diagram.esc(label), process_diagram.LEGEND,
       play_head("detail", "The whole process"), detail.svg(),
       play_head("overview", "The cycle at a glance"), overview.svg(),
       play_head("workshop", "How a session changes sclaude", passes=True), process_diagram.Diagram(*process_config.node_sets()[2]).svg(),
       play_head("friction", "The friction review", passes=True), process_diagram.Diagram(*process_config.node_sets()[3]).svg(),
       play_head("regression", "A stage's regression", passes=True), process_diagram.Diagram(*process_config.node_sets()[4]).svg(),
       play_head("sync", "Main and the branch", passes=True), process_diagram.Diagram(*process_config.node_sets()[5]).svg(),
       play_head("parts", "A feature built in parts", passes=True), process_diagram.Diagram(*process_config.node_sets()[6]).svg(),
       process_doc.commands_table(), PLAYER_BAR, REVIEW_PANEL,
       process_doc.INTERACT_SCRIPT.replace("/*MODEL*/", json.dumps(process_doc.client_model())), PLAY_SCRIPT, script,
       REVIEW_SCRIPT, process_doc.URL_SCRIPT)
