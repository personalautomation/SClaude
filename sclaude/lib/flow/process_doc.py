# The process map's page: the model the page's script reads, the commands'
# dock and table, and the printable document.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import json

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_config, process_diagram, process_model


# Where each command is open, by the words of its "When": the detailed nodes
# a feature may stand on when it shows. Hovering a node lights the commands
# open there.
def _rows(lo, hi):
    return [nid for nid, n in process_model.NODES.items() if lo <= n[1] <= hi]


# A run and a sync come after step 1 and before the cycle ends; production's
# part of the regression map only once it shipped.
_SUB = list(process_model.REGRESSION_NODES) + list(process_model.SYNC_NODES)
_PROD = ["r_prod", "prod_ok", "rollback", "hold_ways", "fix_prod"]
WHEN = {
    "always": _rows(0, 34) + _SUB,
    "before the cycle ends": _rows(3, 15) + _SUB,
    "a finished feature": _rows(16, 34) + _PROD,
    "with a pull request": _rows(10, 34) + _SUB,
    "after step 1": _rows(6, 34) + _SUB,
    "once production carried it": _rows(26, 34) + _PROD,
    "production red and carrying it": ["hold_ways"],
    "with friction logged": [nid for nid, n in process_config.all_nodes().items() if "F" in n[5]],
    "at step 4 or done": _rows(11, 34) + _SUB,
    "an epilogue broken off": ["epilogue"],
    "monthly, offered": [],
    "in a session": [nid for nid, n in process_config.all_nodes().items() if n[2] == "session"],
    "with review rounds": ["review", "round"],
    "a developer's branch": [],
    "a workshop change held": ["w_held"],
}

KIND_WORDS = {
    "start": "where the cycle begins", "end": "where it ends",
    "task": "sclaude does it, no model involved", "session": "the model works here",
    "gate": "a check or a choice: the way on depends on its answer",
    "user": "a person does it", "wait": "waiting for somebody else",
    "hold": "the cycle holds until a person acts",
}
EDGE_WORDS = {
    "": "the flow goes on", "back": "goes back: the work returns to an earlier place",
    "msg": "a message to another lane: one side tells the other", "cmd": "a command a person runs",
}
FLAG_WORDS = {"F": "a friction review follows the session",
              "W": "the session may change sclaude in its workshop",
              "R": "a regression runs here: its own map shows the run and its fixes",
              "S": "main is checked here: its own map shows the merge in and the sync"}


def client_model():
    """What the page's script needs to light and explain: every node and
    edge of the three maps, the commands, and the print sheets' geometry."""
    nodes, edges = {}, {}
    for name, lanes, set_nodes, set_edges in process_config.node_sets():
        lane_names = dict(lanes)
        for nid, (lane, _row, kind, title, text, flags) in set_nodes.items():
            base = process_model.ALIAS.get(nid, nid)
            spec = process_model.SPEC.get(base)
            nodes[nid] = {"t": title, "x": text, "lane": lane_names[lane],
                          "kind": KIND_WORDS.get(kind, kind),
                          "d": process_model.DETAILS.get(base, ""),
                          "spec": " · ".join(spec) if spec else "",
                          "flags": [FLAG_WORDS[f] for f in flags if f in FLAG_WORDS]}
        for i, (a, b, label, kind) in enumerate(set_edges):
            edges["%s:%d" % (name, i)] = {"f": a, "t": b, "l": label, "k": kind,
                                          "w": EDGE_WORDS.get(kind, "")}
    # The overview's blocks that stand for a detailed one:
    # a place lit on one map is lit on every map that has it.
    alias = {}
    for small, big in process_model.ALIAS.items():
        alias.setdefault(big, []).append(small)
    cmds = [{"c": cmd, "v": verb, "w": when, "x": what, "to": process_config.places(target),
             "at": WHEN.get(when, [])} for cmd, verb, when, what, target in process_config.COMMANDS]
    detail = process_diagram.Diagram(*process_config.node_sets()[0])
    sheets = {"w": detail.width, "h": detail.height,
              "cuts": sorted(set([detail.lane_x[lane] for lane, _ in detail.lanes] + [detail.width]))}
    return {"nodes": nodes, "edges": edges, "cmds": cmds, "sheets": sheets, "alias": alias,
            "base": dict(process_model.ALIAS), "proj": projection()}


def projection():
    """Each detailed place as the overview draws it: the places a feature
    stands on (POSITIONS), and the blocks that borrow a detail (ALIAS). A
    place neither has is not on it."""
    out = {}
    for nid in process_config.all_nodes():
        o = process_model.POSITIONS.get(nid) or next((s for s, big in process_model.ALIAS.items() if big == nid), "")
        if o:
            out[nid] = o
    return out


def tiles(diagram, page_w=1010, page_h=640, overlap=36):
    """The detailed map cut into sheets for print, each a window on the one
    drawing (a <use> of its symbol). Neighbouring sheets share a strip of
    `overlap` px: cut one along its dashed line and glue it over the next.
    The page's script cuts them again for the paper and scale chosen; these
    are A4 landscape at 100%, for a page printed with no script."""
    # Columns are cut between lanes, never through one.
    edges = sorted(set([diagram.lane_x[lane] for lane, _ in diagram.lanes] + [diagram.width]))
    starts, start = [], 0
    while True:
        starts.append(start)
        fits = [e for e in edges if start < e <= start + page_w]
        end = fits[-1] if fits else start + page_w
        if end >= diagram.width:
            break
        start = max(end - overlap, start + 1)
    cols = len(starts)
    rows = max(1, -(-(diagram.height - overlap) // (page_h - overlap)))
    out = []
    for r in range(rows):
        for c in range(cols):
            x, y = starts[c], r * (page_h - overlap)
            cuts = []
            if c < cols - 1:
                cut = starts[c + 1] + overlap
                cuts.append('<line x1="%d" y1="%d" x2="%d" y2="%d"/>' % (cut, y, cut, y + page_h))
            if r < rows - 1:
                cuts.append('<line x1="%d" y1="%d" x2="%d" y2="%d"/>'
                            % (x, y + page_h - overlap, x + page_w, y + page_h - overlap))
            glue = []
            if c < cols - 1:
                glue.append("right edge under sheet %d" % (r * cols + c + 2))
            if r < rows - 1:
                glue.append("bottom edge under sheet %d" % ((r + 1) * cols + c + 1))
            out.append(
                '<div class="sheet"><div class="mark"><span>Detailed process — sheet %d of %d '
                '(row %d, column %d)</span><span>%s</span></div>'
                '<svg viewBox="%d %d %d %d"><use href="#sym-%s" width="%d" height="%d"/>'
                '<g class="cut">%s</g></svg></div>'
                % (r * cols + c + 1, rows * cols, r + 1, c + 1,
                   ("glue the " + ", the ".join(glue) + "; the dashed line is the edge of the overlap")
                   if glue else "the last sheet",
                   x, y, page_w, page_h, diagram.name, diagram.width, diagram.height, "".join(cuts)))
    return '<div id="sheets" class="print-only">%s</div>' % "\n".join(out)


def short_command(cmd):
    """A command's name alone, for the pinned list: `sclaude sync <name>` is
    `sync`, `sclaude regression <name> prod` is `regression prod`."""
    words = [w for w in cmd.split()[1:] if not w.startswith(("<", "["))]
    if words:
        return " ".join(words)
    return "continue" if len(cmd.split()) > 1 else "menu"


def commands_dock():
    """The commands' names in a floating list beside the maps, pinned by
    default, so the map and the commands can be read together; they light
    and select as the table's rows do. Only those with a place on a map:
    the menu, the reports and the doctor are in the table alone."""
    shown = [(i, cmd) for i, (cmd, _v, _w, _x, target) in enumerate(process_config.COMMANDS) if target]
    items = "".join('<li data-key="c:%d"><code>%s</code></li>' % (i, process_diagram.esc(short_command(cmd)))
                    for i, cmd in shown)
    return ('<aside id="dock" class="screen-only" style="--n:%d" hidden><div class="dock-head"><b>Commands</b>'
            '<button type="button" class="pin" title="Unpin: the full list stays in section %d" aria-label="Unpin">📌</button>'
            '</div><ul>%s</ul></aside>' % (len(shown), len(SECTIONS), items))


def commands_table():
    rows = []
    for i, (cmd, _verb, when, what, target) in enumerate(process_config.COMMANDS):
        # A place this project's map does not draw is left out.
        shown = process_config.all_nodes()
        lead = ", ".join("where the feature stands" if t == "@here" else process_diagram.esc(shown[t][3])
                         for t in process_config.places(target) if t == "@here" or t in shown)
        rows.append('<tr data-key="c:%d"><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>'
                    % (i, process_diagram.esc(cmd), process_diagram.esc(when), process_diagram.esc(what), lead))
    return ('<table class="cmds"><thead><tr><th>Command</th><th>When</th><th>What it does</th>'
            '<th>Leads to</th></tr></thead><tbody>%s</tbody></table>' % "".join(rows))


# Hover and select, shared by the printed page and a feature's page.
#
# Everything with a data-key takes part: a node ("n:<id>"), an edge
# ("e:<map>:<n>"), a command ("c:<n>", a row of the table or an action of a
# feature's page). What is hovered and what is selected are lit together, a
# union: each lights itself and what it touches — a node its edges and their
# other ends, an edge its two ends, a command the place it leads to, and a
# node the commands open there or leading to it. While anything is lit, the
# rest fades. A click selects; Ctrl (or Cmd) adds to the selection or takes
# away; a click on the one thing selected, Esc or the floating button clears.
INTERACT_SCRIPT = r"""
const M = %(model)s;
const byNode = {};
Object.entries(M.edges).forEach(([k, e]) => {
  (byNode[e.f] = byNode[e.f] || []).push(k);
  (byNode[e.t] = byNode[e.t] || []).push(k);
});
const sel = new Set();
let hover = null;
const scope = (el) => !el.closest('svg.defs') && !el.closest('#sheets');
function parts(k) { const i = k.indexOf(':'); return [k.slice(0, i), k.slice(i + 1)]; }
function light(k, focus, lit) {
  const [t, id] = parts(k);
  focus.add(k);
  if (t === 'n') {
    (byNode[id] || []).forEach((e) => { focus.add('e:' + e); lit.add('n:' + M.edges[e].f); lit.add('n:' + M.edges[e].t); });
    const b = M.base[id] || id;
    M.cmds.forEach((c, i) => { if (c.to.includes(b) || c.at.includes(b)) lit.add('c:' + i); });
  } else if (t === 'e') {
    const e = M.edges[id];
    if (e) { focus.add('n:' + e.f); focus.add('n:' + e.t); }
  } else if (t === 'c') {
    const c = M.cmds[+id];
    (c ? c.to : []).filter((to) => to !== '@here').forEach((to) => {
      // The place on every map that has it.
      [to].concat(M.alias[to] || []).forEach((n) => {
        focus.add('n:' + n);
        (byNode[n] || []).forEach((e) => { if (M.edges[e].t === n) lit.add('e:' + e); });
      });
    });
  }
}
function paint() {
  const focus = new Set(), lit = new Set();
  sel.forEach((k) => light(k, focus, lit));
  if (hover) light(hover, focus, lit);
  document.body.classList.toggle('dimming', focus.size > 0);
  document.querySelectorAll('[data-key]').forEach((el) => {
    if (!scope(el)) return;
    const k = el.dataset.key;
    el.classList.toggle('is-focus', focus.has(k));
    el.classList.toggle('is-lit', !focus.has(k) && lit.has(k));
    el.classList.toggle('is-picked', sel.has(k));
  });
  const b = document.getElementById('clear');
  if (b) { b.hidden = sel.size === 0; b.textContent = 'Clear the selection (' + sel.size + ')'; }
}
function name(id) { const n = M.nodes[id]; return n ? n.t : id; }
function tipFor(k) {
  const [t, id] = parts(k);
  const h = (s) => s.replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
  if (t === 'n') {
    const n = M.nodes[id]; if (!n) return '';
    const cmds = M.cmds.filter((c) => c.to.includes(M.base[id] || id)).map((c) => c.c);
    return '<b>' + h(n.t) + '</b><div class="tk">' + h(n.lane) + ' · ' + h(n.kind) + '</div>'
      + (n.spec ? '<div class="spec">' + h(n.spec) + '</div>' : '')
      + '<p>' + h(n.d || n.x) + '</p>'
      + n.flags.map((f) => '<div class="tk">• ' + h(f) + '</div>').join('')
      + (cmds.length ? '<div><i>commands that lead here</i> ' + h(cmds.join(', ')) + '</div>' : '');
  }
  if (t === 'e') {
    const e = M.edges[id]; if (!e) return '';
    return '<b>' + h(name(e.f)) + ' → ' + h(name(e.t)) + '</b>'
      + (e.l ? '<p>' + h(e.l) + '</p>' : '') + '<div class="tk">' + h(e.w) + '</div>'
      + '<div><i>to</i> ' + h((M.nodes[e.t] || {}).x || '') + '</div>';
  }
  if (t === 'c') {
    const c = M.cmds[+id]; if (!c) return '';
    return '<b>' + h(c.c) + '</b><p>' + h(c.x) + '</p><div class="tk">when: ' + h(c.w) + '</div>'
      + (c.to.length ? '<div><i>leads to</i> ' + h(c.to.map((to) => to === '@here'
          ? 'where the feature stands' : name(to)).join(', ')) + '</div>' : '');
  }
  return '';
}
const tip = document.createElement('div');
tip.id = 'tip'; tip.hidden = true; document.body.append(tip);
document.addEventListener('mouseover', (ev) => {
  const el = ev.target.closest('[data-key]');
  const k = el && scope(el) ? el.dataset.key : null;
  if (k === hover) return;
  hover = k; paint();
  tip.innerHTML = k ? tipFor(k) : ''; tip.hidden = !tip.innerHTML;
});
document.addEventListener('mousemove', (ev) => {
  if (tip.hidden) return;
  const pad = 16, w = tip.offsetWidth, hh = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + hh > innerHeight - 8) y = ev.clientY - hh - pad;
  tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
});
document.addEventListener('click', (ev) => {
  if (ev.target.closest('#clear')) { sel.clear(); paint(); return; }
  const el = ev.target.closest('[data-key]');
  if (!el || !scope(el)) return;
  const k = el.dataset.key;
  if (ev.ctrlKey || ev.metaKey) { if (sel.has(k)) sel.delete(k); else sel.add(k); }
  else if (sel.size === 1 && sel.has(k)) sel.clear();
  else { sel.clear(); sel.add(k); }
  paint();
  // A command clicked brings the place it leads to into view, if it is not.
  const [t, id] = parts(k);
  const to = t === 'c' && M.cmds[+id] ? M.cmds[+id].to.filter((x) => x !== '@here')[0] : '';
  const n = to && document.querySelector('svg.map [data-key="n:' + to + '"]');
  if (n && sel.has(k)) {
    const r = n.getBoundingClientRect();
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth)
      n.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'center'});
  }
});
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { sel.clear(); paint(); } });
window.processMap = {paint: paint, model: M};
"""

# The pinned commands: shown unless unpinned, a choice the browser keeps.
DOCK_SCRIPT = r"""
function dockWidth() {
  const d = document.getElementById('dock');
  if (!d.hidden) document.body.style.setProperty('--dockw', d.offsetWidth + 'px');
}
addEventListener('resize', dockWidth);
function pin(on) {
  document.getElementById('dock').hidden = !on;
  document.body.classList.toggle('pinned', on);
  dockWidth();
  document.querySelectorAll('.pin-head').forEach((b) => { b.textContent = on ? '📌 Unpin' : '📌 Pin'; });
  try { localStorage.setItem('process-pinned', on ? '1' : '0'); } catch (e) {}
}
let pinned = true;
try { pinned = localStorage.getItem('process-pinned') !== '0'; } catch (e) {}
document.querySelectorAll('.pin').forEach((b) => b.addEventListener('click', () =>
  pin(document.getElementById('dock').hidden)));
pin(pinned);
"""

# The printed page's own choice of paper and scale: the sheets are cut again
# for it, and @page is set to match. The page names the paper itself, so a
# browser's print dialog hides Layout and Paper size: they are chosen here.
PRINT_SCRIPT = r"""
const PAPER = {'a4-landscape': [297, 210, 'A4 landscape'], 'a4-portrait': [210, 297, 'A4 portrait'],
  'a3-landscape': [420, 297, 'A3 landscape'], 'a3-portrait': [297, 420, 'A3 portrait']};
const MARGIN = 9, TOP = 12, MARK = 6, OVERLAP = 36, PX = 96 / 25.4;
function cutSheets(paper, scale) {
  const [pw, ph] = PAPER[paper];
  const S = M.sheets;
  // "fit": the whole width on one sheet, the map going on down only.
  if (scale === 'fit') scale = Math.min(1, (pw - 2 * MARGIN) * PX / S.w);
  const w = Math.floor((pw - 2 * MARGIN) * PX / scale), h = Math.floor((ph - TOP - MARGIN - MARK) * PX / scale);
  const starts = []; let start = 0;
  for (;;) {
    starts.push(start);
    const fits = S.cuts.filter((e) => e > start && e <= start + w);
    const end = fits.length ? fits[fits.length - 1] : start + w;
    if (end >= S.w) break;
    start = Math.max(end - OVERLAP, start + 1);
  }
  const cols = starts.length, rows = Math.max(1, Math.ceil((S.h - OVERLAP) / (h - OVERLAP)));
  let out = '';
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = starts[c], y = r * (h - OVERLAP), n = r * cols + c + 1;
    let cuts = '';
    const glue = [];
    if (c < cols - 1) { const cx = starts[c + 1] + OVERLAP;
      cuts += '<line x1="' + cx + '" y1="' + y + '" x2="' + cx + '" y2="' + (y + h) + '"/>';
      glue.push('right edge under sheet ' + (n + 1)); }
    if (r < rows - 1) { cuts += '<line x1="' + x + '" y1="' + (y + h - OVERLAP) + '" x2="' + (x + w) + '" y2="' + (y + h - OVERLAP) + '"/>';
      glue.push('bottom edge under sheet ' + (n + cols)); }
    out += '<div class="sheet"><div class="mark"><span>Detailed process — sheet ' + n + ' of ' + rows * cols
      + ' (row ' + (r + 1) + ', column ' + (c + 1) + ')</span><span>'
      + (glue.length ? 'glue the ' + glue.join(', the ') + '; the dashed line is the edge of the overlap' : 'the last sheet')
      + '</span></div><svg viewBox="' + x + ' ' + y + ' ' + w + ' ' + h + '"><use href="#sym-detail" width="'
      + S.w + '" height="' + S.h + '"/><g class="cut">' + cuts + '</g></svg></div>';
  }
  document.getElementById('sheets').innerHTML = out;
  // A deeper top margin: the running header names the section there.
  document.getElementById('pagesize').textContent = '@page{size:' + PAPER[paper][2] + ';margin:' + TOP + 'mm '
    + MARGIN + 'mm ' + MARGIN + 'mm}';
  return rows * cols;
}
function choosePrint() {
  const paper = document.getElementById('paper').value, chosen = document.getElementById('scale').value;
  const scale = chosen === 'fit' ? 'fit' : +chosen;
  const n = cutSheets(paper, scale);
  document.getElementById('count').textContent = n + (n === 1 ? ' sheet' : ' sheets') + ' for the whole process, plus '
    + 'a page for the overview, and the commands';
  try { localStorage.setItem('process-print', JSON.stringify([paper, scale])); } catch (e) {}
}
try { const saved = JSON.parse(localStorage.getItem('process-print') || 'null');
  if (saved) { document.getElementById('paper').value = saved[0]; document.getElementById('scale').value = saved[1]; } } catch (e) {}
document.getElementById('paper').onchange = choosePrint;
document.getElementById('scale').onchange = choosePrint;
document.getElementById('print').onclick = () => window.print();
choosePrint();
"""

PRINT_BAR = """<div class="printbar screen-only">
<label>Paper <select id="paper"><option value="a4-landscape">A4 landscape</option>
<option value="a4-portrait">A4 portrait</option><option value="a3-landscape">A3 landscape</option>
<option value="a3-portrait">A3 portrait</option></select></label>
<label>Scale <select id="scale"><option value="1">100% — as on screen</option>
<option value="fit">Fit the width — one column of sheets</option><option value="0.85">85%</option>
<option value="0.7">70%</option><option value="0.55">55%</option></select></label>
<button id="print" type="button">Print…</button>
<span class="muted" id="count"></span>
<p class="muted">Recommended: <b>A4 landscape at 100%</b> — the text is as large as on screen and the sheet
is cut between lanes, so each lane stays whole on one sheet; <b>A3 landscape</b>, if a printer takes it, or
<b>70%</b> on A4 need fewer sheets (the count is beside the button), 70% with smaller text. Choose the paper and the scale here: the
page names its paper, so the browser's dialog has no Layout or Paper size, and its own Scale (under More settings)
would only shrink each sheet without making fewer of them. Leave the dialog's margins at Default.</p>
</div>"""


# The printed page's sections, in order: each is a named page (`page: sN`)
# whose running header names it, so a loose sheet says where it belongs.
SECTIONS = ["1. The cycle at a glance", "2. The whole process",
            "3. How a session changes sclaude", "4. The friction review",
            "5. A stage's regression", "6. Main and the branch",
            "7. Commands and where they lead"]


def running_heads():
    css = ['@page{@top-right{content:"sclaude — the process";font:9px sans-serif;color:#666}'
           '@bottom-right{content:"page " counter(page);font:9px sans-serif;color:#666}}']
    for n, title in enumerate(SECTIONS, start=1):
        # A CSS string, not JSON: json's \\uXXXX would print as "uXXXX".
        css.append('@page s%d{@top-left{content:"%s";font:600 10px sans-serif;color:#333}}'
                   % (n, title.replace("\\", "\\\\").replace('"', '\\"')))
    return "\n".join(css)


def doc(cfg=None):
    """The printed page: the maps as cfg draws them — a project's own, or,
    with none, the example config's (config.example.json), the cycle a
    typical project runs."""
    with process_model.configured(process_config.example_config() if cfg is None else cfg):
        return _doc()


def _doc():
    detail = process_diagram.Diagram(*process_config.node_sets()[0])
    overview = process_diagram.Diagram(*process_config.node_sets()[1])
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>sclaude Process Map</title>
<style>%s
%s</style><style id="pagesize">@page{size:A4 landscape;margin:12mm 9mm 9mm}</style></head><body><main>
<section style="page:s1">
<h1>sclaude — the process</h1>
<p class="lead">The feature cycle as BPMN: who does what, in which order, and every way back.
Drawn from <code>sclaude/lib/flow/process.py</code>, which tests check against the code; a feature's own copy,
with where it stands lit and its actions, is at <code>http://localhost:3000/__sclaude/flow?f=&lt;feature&gt;</code>.</p>
%s
<p class="muted screen-only">Point at a block, an arrow or a command to see what it is and what it touches;
click to keep it lit, Ctrl-click to add more, Esc to clear.</p>
<h2 class="first">%s</h2>
<div class="card">%s</div>
</section><section style="page:s2">
<h2>%s</h2>
<p class="muted">Every lane, every check and every way back.</p>
%s
<div class="card screen-only">%s</div>
%s
%s
</section><section style="page:s3" id="map-workshop">
<h2>%s</h2>
<p class="muted">Any session marked W may take this way: it changes sclaude in its tree's workshop, and sclaude
publishes the change once the session ends.</p>
<div class="card">%s</div>
</section><section style="page:s4" id="map-friction">
<h2>%s</h2>
<p class="muted">Every session marked F leads here once it ends: what the safety rules refused it is read by a
session of its own, which lifts a rule, leaves it, puts it off a month, or fixes sclaude.</p>
<div class="card">%s</div>
</section><section style="page:s5" id="map-regression">
<h2>%s</h2>
<p class="muted">Every block marked R runs a stage's suite here: the local one closes steps 2 and 4, the
preview's comes before QA, production's after the ship. Red goes to a fixing session, at most two, or back to
step 4; production is rolled back first.</p>
<div class="card">%s</div>
</section><section style="page:s6" id="map-sync">
<h2>%s</h2>
<p class="muted">Every block marked S checks main here: it is merged in without asking, and a conflict goes to
the sync session.</p>
<div class="card">%s</div>
</section><section style="page:s7">
<h2>%s <button type="button" class="pin pin-head screen-only">📌 Pin</button></h2>
<p class="muted">A feature's action list shows only those that apply to it now. A command lights the place it
leads to; a block lights the commands open there.</p>
%s
</section>
<button id="clear" class="screen-only" type="button" hidden>Clear the selection</button>
%s
</main><script>%s%s%s</script></body></html>
""" % (process_diagram.STYLE, running_heads(), process_diagram.LEGEND, process_diagram.esc(SECTIONS[0]), overview.svg(),
       process_diagram.esc(SECTIONS[1]), PRINT_BAR, detail.svg(), detail.svg(symbol=True), tiles(detail),
       process_diagram.esc(SECTIONS[2]), process_diagram.Diagram(*process_config.node_sets()[2]).svg(), process_diagram.esc(SECTIONS[3]), process_diagram.Diagram(*process_config.node_sets()[3]).svg(),
       process_diagram.esc(SECTIONS[4]), process_diagram.Diagram(*process_config.node_sets()[4]).svg(), process_diagram.esc(SECTIONS[5]), process_diagram.Diagram(*process_config.node_sets()[5]).svg(),
       process_diagram.esc(SECTIONS[6]), commands_table(),
       commands_dock(), INTERACT_SCRIPT % {"model": json.dumps(client_model())}, PRINT_SCRIPT, DOCK_SCRIPT)
