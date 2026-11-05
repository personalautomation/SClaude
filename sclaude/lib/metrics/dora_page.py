# The DORA page itself: its style and scripts, and the page rendered from
# the numbers.
#
# Part of sclaude/lib/metrics/dora.py.

import os

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import metrics_extra  # noqa: E402

import dora_charts, dora_numbers, dora_team


STYLE = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--link:#1d4ed8}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;
--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--link:#93c5fd}}
:root[data-theme=dark]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;
--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;
--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--link:#93c5fd}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 40px;background:var(--page);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto}
h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:0 0 4px}
p{color:var(--ink2);margin:0 0 12px}a{color:var(--link)}
.lead{color:var(--muted);font-size:13px;margin-bottom:20px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.tile,.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px}
.card{margin-bottom:16px}
.label{font-size:13px;color:var(--ink2)}
.value{font-size:30px;font-weight:600;line-height:1.2;margin:4px 0 2px}
.sub,.delta,.empty{font-size:12px;color:var(--muted)}
.foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}
.lvl{font-size:12px;font-weight:600;color:var(--ink);display:inline-flex;gap:5px;align-items:center}
.lvl i{font-style:normal;font-size:10px}
.lvl.good i{color:var(--good)}.lvl.watch i{color:var(--warning)}.lvl.poor i{color:var(--critical)}
.tile.good{border-top:3px solid var(--good)}.tile.watch{border-top:3px solid var(--warning)}
.tile.poor{border-top:3px solid var(--critical)}
.note[hidden]{display:none}
svg{width:100%;height:auto;display:block}
svg text{font:11px system-ui,sans-serif}
.tick{fill:var(--muted);font-variant-numeric:tabular-nums}.val{fill:var(--ink2)}
.grid{stroke:var(--grid);stroke-width:1}.axis{stroke:var(--axis);stroke-width:1}
.bar{fill:var(--s1)}.hit{fill:transparent}.hit:hover+.bar,.hit:focus+.bar{opacity:.8}
.s1{fill:var(--s1);background:var(--s1)}.s2{fill:var(--s2);background:var(--s2)}
.s3{fill:var(--s3);background:var(--s3)}.s4{fill:var(--s4);background:var(--s4)}
.s5{fill:var(--s5);background:var(--s5)}
.seg:hover,.seg:focus{opacity:.8;outline:none}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0 8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.key{display:inline-block;width:10px;height:10px;border-radius:2px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.two .card{margin-bottom:0}.two{margin-bottom:16px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{text-align:left;color:var(--muted);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--axis)}
td{padding:6px 8px;border-top:1px solid var(--grid);white-space:nowrap}
code{font-size:12px}
.bad{font-weight:600}.bad i{color:var(--critical);font-style:normal;margin-right:4px}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);
border:1px solid var(--ring);border-radius:6px;padding:4px 8px;font-size:12px;
box-shadow:0 2px 8px rgba(0,0,0,.15);display:none;z-index:9}
#tip.note{max-width:340px;padding:10px 12px;font-size:12.5px;line-height:1.45}
#tip.note b{display:block;margin-bottom:2px}
#tip.note p{margin:6px 0 0;color:var(--ink2)}
#tip.note p b{display:inline;color:var(--ink);margin:0}
.tile{cursor:help}
ul.notes{font-size:12px;color:var(--muted);padding-left:18px;margin:0}
h2.part{font-size:19px;margin:32px 0 2px;padding-top:16px;border-top:1px solid var(--grid)}
h3{font-size:15px;margin:0 0 4px}
.card .sub{margin:0 0 6px}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
background:var(--surface);border:1px solid var(--ring);border-radius:10px;overflow:hidden;margin:8px 0 8px}
.hero div{padding:14px 16px;box-shadow:0 0 0 .5px var(--grid)}
.hero b{display:block;font-size:28px;font-weight:600;line-height:1.15}
.hero span{font-size:12px;color:var(--ink2)}
.cell{fill:var(--grid)}
.area{fill:var(--s1);fill-opacity:.12;stroke:var(--s1);stroke-width:2;stroke-linejoin:round}
.dot{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.axis-name{fill:var(--ink2);font-weight:600;font-size:13px}
.team-table td,.team-table th{white-space:normal;vertical-align:top}
.team-table tr.group td{font-weight:600;color:var(--ink);padding-top:14px;border-top:0}
.team-table td.metric{color:var(--ink2);min-width:180px}
.cellv{display:flex;gap:6px;align-items:center}
.track{height:6px;background:var(--grid);border-radius:3px;margin-top:4px;min-width:90px}
.fill{height:6px;border-radius:3px}
.fill.s1,.seg.s1{background:var(--s1)}.fill.s2,.seg.s2{background:var(--s2)}
.fill.s3,.seg.s3{background:var(--s3)}.fill.s4,.seg.s4{background:var(--s4)}
.coach{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.coach-card{border:1px solid var(--ring);border-radius:8px;padding:10px 12px;font-size:12.5px}
.coach-head{display:flex;align-items:center;gap:4px;margin-bottom:4px}
.coach-score{margin-left:auto;color:var(--ink2);font-weight:600}
.coach-sub{margin:8px 0 2px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.coach-line{margin:3px 0 0;color:var(--ink)}
.coach-tip{margin:2px 0 6px 16px;color:var(--ink2)}
.stackrow{display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center;margin:8px 0;font-size:12px}
.stacklabel{color:var(--ink2);text-align:right}
.stack{display:flex;height:16px;border-radius:4px;overflow:hidden;gap:2px;background:var(--surface)}
.radar-wrap{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px;align-items:center}
@media (max-width:760px){.radar-wrap{grid-template-columns:1fr}}
body{padding-left:252px}
#toc{position:fixed;top:0;left:0;bottom:0;width:232px;overflow:auto;padding:12px 10px 24px;
background:var(--surface);border-right:1px solid var(--grid);z-index:6;font-size:13px}
#toc ol{list-style:none;margin:10px 0 0;padding:0}
#toc a{display:block;padding:6px 10px;border-radius:6px;color:var(--ink2);text-decoration:none}
#toc a:hover{background:var(--grid)}
#toc a.here{color:var(--ink);background:var(--grid);font-weight:600}
#toc-fold{border:1px solid var(--ring);background:var(--surface);color:var(--ink);border-radius:6px;
font-size:16px;width:36px;height:32px;cursor:pointer}
:root[data-toc=folded] #toc{bottom:auto;width:auto;border:0;background:transparent;padding:10px}
:root[data-toc=folded] #toc ol{display:none}
:root[data-toc=folded] body{padding-left:16px}
section{scroll-margin-top:96px}
@media (max-width:1100px){body{padding-left:16px}
#toc{box-shadow:0 0 24px rgba(0,0,0,.2)}}
.switch{position:sticky;top:0;z-index:5;background:var(--page);padding:10px 0 8px;margin:0 0 4px;
border-bottom:1px solid var(--grid)}
.switch .sub{margin:6px 0 0}
.modes{display:inline-flex;border:1px solid var(--ring);border-radius:999px;padding:4px;
background:var(--surface)}
.modes button{font:600 16px system-ui,sans-serif;border:0;background:transparent;color:var(--ink2);
padding:10px 22px;border-radius:999px;cursor:pointer}
.modes button[aria-pressed=true]{background:var(--s1);color:#fff}
.norm{display:none}
:root[data-mode=norm] .norm{display:block}
:root[data-mode=norm] .abs{display:none}
.scales{color:var(--s1);font-size:12px}
"""

TIP_JS = """
(function(){var root=document.documentElement,key='sclaude-metrics-toc',fold=document.getElementById('toc-fold');
if(!fold)return;var narrow=window.matchMedia('(max-width:1100px)');
function set(folded){root.setAttribute('data-toc',folded?'folded':'open');
fold.setAttribute('aria-expanded',String(!folded));fold.title=folded?'Show the contents':'Fold the contents'}
var saved=null;try{saved=localStorage.getItem(key)}catch(e){}
set(narrow.matches?true:saved==='folded');
fold.addEventListener('click',function(){var folded=root.getAttribute('data-toc')!=='folded';set(folded);
if(!narrow.matches){try{localStorage.setItem(key,folded?'folded':'open')}catch(e){}}});
var links={};document.querySelectorAll('#toc a').forEach(function(a){links[a.getAttribute('href').slice(1)]=a;
a.addEventListener('click',function(){if(narrow.matches)set(true)})});
if('IntersectionObserver' in window){var seen={};
var io=new IntersectionObserver(function(es){es.forEach(function(e){seen[e.target.id]=e.isIntersecting});
var first=null;document.querySelectorAll('main section').forEach(function(sec){if(!first&&seen[sec.id])first=sec.id});
Object.keys(links).forEach(function(k){links[k].classList.toggle('here',k===first)})},{rootMargin:'-90px 0px -55% 0px'});
document.querySelectorAll('main section').forEach(function(sec){io.observe(sec)})}})();
(function(){var root=document.documentElement,key='sclaude-metrics-mode';
var buttons=document.querySelectorAll('.modes button');
function set(mode){root.setAttribute('data-mode',mode);
buttons.forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-mode')===mode))});
try{localStorage.setItem(key,mode)}catch(e){}}
var saved=null;try{saved=localStorage.getItem(key)}catch(e){}
set(saved==='norm'?'norm':'abs');
buttons.forEach(function(b){b.addEventListener('click',function(){set(b.getAttribute('data-mode'))})})})();
(function(){var t=document.getElementById('tip');
function place(r){var x=Math.min(r.x+14,window.innerWidth-t.offsetWidth-8);
var y=r.y-t.offsetHeight-12;if(y<8)y=r.y+18;
if(y+t.offsetHeight>window.innerHeight-8)y=Math.max(8,window.innerHeight-t.offsetHeight-8);
t.style.left=Math.max(8,x)+'px';t.style.top=y+'px'}
function at(e,el){return e.clientX!==undefined?{x:e.clientX,y:e.clientY}:
(function(b){return{x:b.left+b.width/2,y:b.top}})(el.getBoundingClientRect())}
function hide(){t.style.display='none';t.classList.remove('note')}
document.querySelectorAll('[data-tip]').forEach(function(el){
function show(e){t.classList.remove('note');t.textContent=el.getAttribute('data-tip');
t.style.display='block';place(at(e,el))}
el.addEventListener('pointermove',show);el.addEventListener('focus',function(){show({})});
['pointerleave','blur'].forEach(function(n){el.addEventListener(n,hide)})});
// A figure's note — why, aim, how — follows the pointer over whatever holds
// it: a tile, or a row the team part's script draws later. Delegated, so
// what is drawn after this runs has its note too; a tap opens it where there
// is no hover.
var open=null,shown=null;
function host(e){var h=e.target.closest&&e.target.closest('.tile,.hasnote');
return h&&h.querySelector('.note')?h:null}
function note(el){var info=el.querySelector('.note');var box=document.createElement('div');
var head=document.createElement('b');head.textContent=info.getAttribute('data-title')||
(el.querySelector('.label')||el).textContent;box.appendChild(head);
info.querySelectorAll('p').forEach(function(p){box.appendChild(p.cloneNode(true))});return box}
function showNote(e,el){if(e.target.closest('[data-tip]'))return;if(shown!==el){t.textContent='';
t.appendChild(note(el));shown=el}t.classList.add('note');t.style.display='block';place(at(e,el))}
document.addEventListener('pointermove',function(e){if(e.pointerType==='touch'||open)return;
var el=host(e);if(el)showNote(e,el);else if(shown){hide();shown=null}});
document.addEventListener('click',function(e){var el=host(e);
if(el&&open!==el){showNote(e,el);open=el;return}if(open){hide();open=null;shown=null}})})();
"""


def hero(items):
    return "<div class=hero>%s</div>" % "".join(
        "<div><b>%s</b><span>%s</span></div>" % (dora_charts.esc(v), dora_charts.esc(k)) for v, k in items)


def section(key, title, lead, *blocks):
    """A part of the page, with the id the table of contents links to."""
    return "<section id='%s'><h2 class=part>%s</h2><p>%s</p>%s</section>" % (
        dora_charts.esc(key), dora_charts.esc(title), dora_charts.esc(lead), "".join(blocks))


def contents(parts):
    """The table of contents: [(id, title)], folded away with its button."""
    return ("<nav id=toc aria-label='Contents'><button type=button id=toc-fold "
            "aria-expanded=true title='Fold the contents'>☰</button><ol>%s</ol></nav>"
            % "".join("<li><a href='#%s'>%s</a></li>" % (dora_charts.esc(k), dora_charts.esc(t)) for k, t in parts))


def card(title, body, note="", mode=""):
    mark = " <span class=scales title='%s'>◆</span>" % dora_charts.esc(dora_charts.SCALES) if mode else ""
    return "<div class='card%s'><h3>%s%s</h3>%s%s</div>" % (
        " " + mode if mode else "", dora_charts.esc(title), mark, "<p class=sub>%s</p>" % dora_charts.esc(note) if note else "", body)


def dual(absolute, normalised):
    """A chart drawn both ways: (title, body, note) each, the switch showing
    one."""
    return card(*absolute, mode="abs") + card(*normalised, mode="norm")


def tiles(*items):
    """Each item is (label, value, sub), (label, value, sub, raw) — raw being
    the number the guide colours by — or DORA's (label, value, sub, level,
    delta); or a figure that scales with a feature's size, as
    {"abs": item, "norm": item}: both are drawn, and the page's switch shows
    one."""
    def one(i, mode="", scales=False):
        if len(i) == 5:
            return dora_charts.tile(*i, mode=mode, scales=scales)
        return dora_charts.tile(i[0], i[1], i[2], None, "", i[3] if len(i) > 3 else None, mode, scales)
    return "<div class=tiles>%s</div>" % "".join(
        one(i["abs"], "abs", True) + one(i["norm"], "norm", True) if isinstance(i, dict) else one(i)
        for i in items)


def render(repo, data, m):
    cur, prev = m["current"], m["previous"]
    x = m["more"]
    name = data.get("github") or os.path.basename(os.path.realpath(repo))
    per_week = cur["per_day"] * 7
    tok = x["tokens"]
    hist = x["history"] or {}
    hist_all = x["history_all"] or {}
    reg = x["regression"]
    fr = x["friction"]
    dm, dv, sw, ai, wk = x["dora"], x["devex"], x["software"], x["ai"], x["weekly"]
    nm = x["norm"]
    size_rows = "".join(
        "<tr><td>%s</td><td>%s</td><td>%s</td><td>%.1f</td><td>%s</td></tr>"
        % (dora_charts.esc(f), dora_charts.compact(v["criteria"]), dora_charts.compact(v["lines"]), v["unit"],
           "criteria" if v["source"] == "criteria" else "lines, at the median rate")
        for f, v in sorted(nm["sizes"].items(), key=lambda kv: -kv[1]["unit"]))
    sizes_card = card("How big each finished feature was", (
        "<div class=scroll><table><tr><th>Feature</th><th>Criteria</th><th>Lines</th>"
        "<th>Standard features</th><th>Sized by</th></tr>%s</table></div>" % size_rows)
        if size_rows else "<p class=empty>No finished feature could be sized yet.</p>",
        "A standard feature is the median: %s acceptance criteria. %d of %d finished features sized."
        % (dora_charts.compact(nm["standard"]), nm["sized"], nm["features"]))
    people_rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>"
        % (dora_charts.esc(n), a["commits"], dora_charts.compact(a["lines"]), dora_charts.share(dora_numbers.ratio(a["by_claude"], a["commits"])))
        for n, a in sorted((hist.get("authors") or {}).items(), key=lambda kv: -kv[1]["commits"]))
    people = ("<div class=scroll><table><tr><th>Author</th><th>Commits</th><th>Lines</th>"
              "<th>By Claude</th></tr>%s</table></div>" % people_rows) if people_rows \
        else "<p class=empty>No commits in the last %d days.</p>" % dora_numbers.WINDOW

    hm = x["human"]
    head = hero([
        (dora_charts.compact(x["sessions"]), "Claude sessions, and %s subagents" % dora_charts.compact(x["subagents"])),
        (dora_charts.compact(sum(tok.values()) - tok["thinking"]), "tokens processed"),
        (dora_charts.money(x["cost"]), "spent by Claude Code, as it counted"),
        (dora_charts.compact(x["tool_calls"]), "tool calls"),
        (dora_charts.share(dora_numbers.ratio(hist_all.get("by_claude"), hist_all.get("commits"))), "of commits written by Claude"),
        (dora_charts.compact(x["lines_by_claude"]), "lines Claude edited"),
        ("—" if hm["run_calls"] is None else "%.0f" % hm["run_calls"],
         "actions Claude takes between a person's interventions"),
        (dora_charts.share(hm["unattended"]), "of sclaude's sessions ran with no one stepping in"),
        ("—" if hm["minutes_per_hour"] is None else "%.0f min" % hm["minutes_per_hour"],
         "of a person per hour of Claude's work"),
        (dora_charts.compact(m["total_deploys"]), "production deploys"),
        (dora_charts.compact(x["done"]), "features finished"),
        (dora_charts.compact(x["review_comments"]), "review threads answered"),
        (dora_charts.compact(x["criteria"]), "acceptance criteria written"),
        (dora_charts.compact(sum(r["runs"] for r in reg.values())), "regression stages run"),
        (dora_charts.compact(fr["reviews"] + x["deferred"]), "friction reviews and entries"),
        (dora_charts.share(x["cache_hit"]), "of input from the prompt cache"),
    ])
    overview = section("overview", "Overview", "What sclaude has counted for this product.", head)

    dora = section(
        "dora", "Delivery performance (DORA)",
        "The four keys of delivery performance, over the last %d days, and the rest of DORA's "
        "picture." % dora_numbers.WINDOW,
        tiles(
            ("Deployment frequency", "%.1f / week" % per_week,
             "%d production deploys in the last %d days" % (cur["deploys"], dora_numbers.WINDOW),
             dora_numbers.level("frequency", cur["per_day"]) if cur["deploys"] else "Low",
             dora_charts.delta_text(per_week, prev["per_day"] * 7 if prev["deploys"] else None,
                        lambda v: "%.1f" % v)),
            ("Lead time for changes", dora_charts.span(cur["lead"]),
             "median, first commit to production · %d changes" % cur["changes"],
             dora_numbers.level("lead", cur["lead"]), dora_charts.delta_text(cur["lead"], prev["lead"], dora_charts.span)),
            ("Change failure rate",
             "—" if cur["failure"] is None else "%d%%" % round(cur["failure"] * 100),
             "%d of %d deploys rolled back" % (cur["failed"], cur["deploys"]),
             dora_numbers.level("failure", cur["failure"]),
             dora_charts.delta_text(cur["failure"], prev["failure"], lambda v: "%d%%" % round(v * 100))),
            ("Time to restore", dora_charts.span(cur["restore"]) if cur["incidents"] else "no failures",
             "median, failed deploy to rollback · %d incidents" % cur["incidents"],
             dora_numbers.level("restore", cur["restore"]),
             dora_charts.delta_text(cur["restore"], prev["restore"], dora_charts.span) if cur["incidents"] else "")),
        tiles(
            ("Rework rate", dora_charts.share(dm["rework"]),
             "deploys that only fixed what was out · %d" % dm["rework_n"], dm["rework"]),
            ("Hotfix rate", dora_charts.share(dm["hotfix"]),
             "deploys followed within a day by a fix · %d" % dm["hotfix_n"], dm["hotfix"]),
            ("Lead time, 90th percentile", dora_charts.span(dm["lead_p90"]), "the slow tail of changes", dm["lead_p90"]),
            ("Batch size", dora_charts.compact(dm["batch"]), "median changes per deploy", dm["batch"]),
            ("Days with a deploy", dora_charts.share(dm["deploy_days"]), "of the last %d" % dora_numbers.WINDOW, dm["deploy_days"]),
            ("Time between deploys", dora_charts.span(dm["interval"]), "median", dm["interval"]),
            ("Production suite green", dora_charts.share(dm["reliability"]),
             "after %d production deploys — reliability's stand-in" % dm["reliability_n"],
             dm["reliability"])),
        "<div class=two>%s%s</div>" % (
            card("Production deploys per week",
                 dora_charts.columns(m["weeks"], lambda w: w[1], lambda v: str(int(v)), "Production deploys per week")),
            card("Median lead time per week",
                 dora_charts.columns(m["weeks"], lambda w: w[2], dora_charts.span, "Median lead time per week"))),
        "<div class=two>%s%s</div>" % (
            card("Lead time, cut by stage",
                 dora_charts.hbars([("Coding", dm["coding"]), ("Review", dm["review"]), ("Deploy", dm["deploy"])],
                       dora_charts.span, "Lead time by stage"),
                 "median per change: first commit to PR, PR to merge, merge to production"),
            card("Lead time, by path",
                 dora_charts.hbars([("Through a pull request", dm["lead_pr"]), ("Straight to main", dm["lead_direct"])],
                       dora_charts.span, "Lead time by path"), "median per change")))

    flow = section(
        "flow", "Flow of work", "What the cycle turns out, how long a feature takes, and how much waits.",
        tiles(
            {"abs": ("Features shipped", dora_charts.compact(x["shipped"]), "reached production in the last %d days" % dora_numbers.WINDOW),
             "norm": ("Features shipped", "%.1f" % nm["shipped"],
                      "standard features reached production in the last %d days" % dora_numbers.WINDOW)},
            {"abs": ("Feature cycle time", dora_charts.span(x["cycle"]),
                     "median, plan to production, %d features" % x["done"], x["cycle"]),
             "norm": ("Feature cycle time", dora_charts.span(nm["cycle"]), "median per standard feature", nm["cycle"])},
            {"abs": ("Time to market", dora_charts.span(ai["market"]), "median, issue opened to production", ai["market"]),
             "norm": ("Time to market", dora_charts.span(nm["market"]), "median per standard feature", nm["market"])},
            ("Time in the queue", dora_charts.span(ai["queue"]), "median, issue opened to its first session", ai["queue"]),
            ("Flow efficiency", dora_charts.share(ai["flow"]), "of a feature's cycle with Claude at work", ai["flow"]),
            ("Features at once", dora_charts.compact(ai["concurrent_max"]),
             "most on one day · median %s" % dora_charts.compact(ai["concurrent_median"]), ai["concurrent_max"]),
            ("Pull requests per feature", "—" if x["prs_per_feature"] is None else "%.1f" % x["prs_per_feature"],
             "%d features needed more than one" % x["reworked"], x["prs_per_feature"]),
            ("Features dropped", dora_charts.share(dora_numbers.ratio(x["dropped"], x["done"] + x["dropped"])),
             "%d of %d started, all time" % (x["dropped"], x["done"] + x["dropped"]),
             dora_numbers.ratio(x["dropped"], x["done"] + x["dropped"]))),
        "<div class=two>%s%s</div>" % (
            dual(("Features shipped per week",
                  dora_charts.columns(x["shipped_weeks"], lambda w: w[1], lambda v: str(int(v)), "Features shipped per week"), ""),
                 ("Standard features shipped per week",
                  dora_charts.columns(nm["weekly_shipped"], lambda w: w[1], lambda v: "%.1f" % v,
                          "Standard features shipped per week"), "each feature weighted by its size")),
            dual(("Features in work per week",
                  dora_charts.columns(wk, lambda w: w[4], lambda v: str(int(v)), "Features in work per week"), ""),
                 ("Standard features in work per week",
                  dora_charts.columns(nm["weekly_work"], lambda w: w[1], lambda v: "%.1f" % v,
                          "Standard features in work per week"),
                  "finished features only: one in progress has no size yet"))),
        dual(("Where a feature's time goes", dora_charts.stacked(m["features"]),
              "The last finished features, by step. Review includes waiting for QA."),
             ("Where a feature's time goes, per standard feature", dora_charts.stacked(nm["features_time"]),
              "each feature's steps divided by its size")),
        sizes_card)

    prs = section(
        "prs", "Pull requests and builds", "Where a pull request waits, from first commit to production.",
        tiles(
            ("Coding time", dora_charts.span(dv["coding"]), "first commit to PR opened", dv["coding"]),
            ("Pickup time", dora_charts.span(dv["pickup"]), "PR opened to its first review answer", dv["pickup"]),
            ("Approve time", dora_charts.span(dv["approve"]) if dv["approvals"] else "—",
             "first answer to approval" if dv["approvals"]
             else "no approvals: the person merges after the review", dv["approve"]),
            ("Merge time", dora_charts.span(dv["merge"]), "approval, or first answer, to merge", dv["merge"]),
            ("Review time", dora_charts.span(dv["review"]), "PR opened to approval or merge", dv["review"]),
            ("Deploy time", dora_charts.span(dv["deploy"]), "merge to production", dv["deploy"]),
            ("PR aging", dora_charts.span(dv["aging"]), "PR opened to merged", dv["aging"]),
            ("Merge frequency", "—" if dv["merge_frequency"] is None else "%.1f / week" % dv["merge_frequency"],
             "merged PRs per author · %d authors" % dv["authors"], dv["merge_frequency"]),
            ("Pull request size", dora_charts.compact(x["pr_size"]), "median lines changed, %d merged" % x["merged"],
             x["pr_size"]),
            ("PR maturity", dora_charts.share(dv["maturity"]), "of its lines written before it was opened", dv["maturity"]),
            ("PRs without review", dora_charts.share(dv["unreviewed"]), "merged with no answer at all", dv["unreviewed"]),
            ("Builds", dora_charts.compact(x["builds"]), "%d previews · %d failed" % (x["previews"], x["build_errors"]),
             dora_numbers.ratio(x["build_errors"], x["builds"])),
            ("Build time", dora_charts.span(x["build_time"]), "median, on Vercel", x["build_time"])),
        card("A pull request's way, median",
             dora_charts.hbars([("Coding", dv["coding"]), ("Pickup", dv["pickup"]), ("Approve", dv["approve"]),
                    ("Merge", dv["merge"]), ("Deploy", dv["deploy"])], dora_charts.span, "PR stages", width=900),
             "over the %d pull requests merged in the last %d days" % (dv["merged"], dora_numbers.WINDOW)))

    rq = x["requirements"]
    sizes = nm["sizes"]
    requirements = section(
        "requirements", "Requirements", "Whether features started from requirements that said enough, and held.",
        tiles(
            ("Requirements changed in development", dora_charts.share(rq["significant"]),
             "%d of %d features · any change in %s" % (rq["significant_n"], rq["covered"], dora_charts.share(rq["changed"])),
             rq["significant"]),
            ("Requirements added in development", dora_charts.compact(rq["added"]),
             "median %s per feature, under the request's \"Added during development\""
             % dora_charts.compact(rq["added_median"])),
            ("Requirements unclear at the start", dora_charts.share(rq["unclear"]),
             "%d of %d features needed a question per criterion or more in planning"
             % (rq["unclear_n"], rq["planned"]), rq["unclear"]),
            ("Questions per criterion", "—" if rq["per_criterion"] is None else "%.2f" % rq["per_criterion"],
             "median, clarifying questions in planning over acceptance criteria", rq["per_criterion"]),
            {"abs": ("Clarifying questions in planning", dora_charts.compact(rq["questions"]), "median per feature",
                     rq["questions"]),
             "norm": ("Clarifying questions in planning",
                      "—" if rq["questions_norm"] is None else "%.1f" % rq["questions_norm"],
                      "median per standard feature", rq["questions_norm"])},
            ("Request grew in planning", "—" if rq["growth"] is None else "%.1f×" % rq["growth"],
             "the agreed request against the issue's description, in words", rq["growth"]),
            ("Acceptance criteria", dora_charts.compact(x["criteria"]),
             "on %d issues · %s ticked by QA" % (x["criteria_issues"],
                                                 dora_charts.share(dora_numbers.ratio(x["criteria_ticked"], x["criteria"]))),
             dora_numbers.ratio(x["criteria_ticked"], x["criteria"]))),
        "<div class=two>%s%s</div>" % (
            card("How much the requirements moved, per feature",
                 dora_charts.hbars([(f, mv["change"]) for f, mv, _ in reversed(rq["rows"]) if mv], dora_charts.share,
                       "Requirements moved"),
                 "share of the description, request and criteria rewritten after the plan was "
                 "approved; ticks in the criteria's boxes do not count"),
            dual(("Clarifying questions in planning, per feature",
                  dora_charts.hbars([(f, q) for f, q in reversed(rq["questions_by"])], dora_charts.compact, "Questions"),
                  "each question of Claude's AskUserQuestion in the feature's plan sessions"),
                 ("Clarifying questions in planning, per standard feature",
                  dora_charts.hbars([(f, q / sizes[f]["unit"]) for f, q in reversed(rq["questions_by"]) if f in sizes],
                        lambda v: "%.1f" % v, "Questions per standard feature"),
                  "each feature's questions divided by its size"))))

    stage_rates = [("%s · %d runs" % (st.capitalize(), r["runs"]), dora_numbers.ratio(r["first_pass"], r["runs"]))
                   for st, r in reg.items() if r["runs"]]
    first_time = dora_numbers.ratio(sum(r["first_pass"] for r in reg.values()), sum(r["runs"] for r in reg.values()))
    testing = section(
        "testing", "Testing", "Whether the code was right before the suite ran, and what got past it.",
        tiles(
            ("Regression green first time", dora_charts.share(first_time), "stages that passed with no fixing session",
             first_time),
            ("Fixing sessions", dora_charts.compact(sum(r["fixes"] for r in reg.values())),
             "%d of them left the suite red" % sum(r["red_fixes"] for r in reg.values())),
            ("Escaped defects", dora_charts.share(sw["escaped"]), "of what the regression found, found in production",
             sw["escaped"]),
            ("Tests in new lines", dora_charts.share(dora_numbers.ratio(hist.get("test_added"), hist.get("added"))),
             "%s lines of tests added" % dora_charts.compact(hist.get("test_added")),
             dora_numbers.ratio(hist.get("test_added"), hist.get("added")))),
        "<div class=two>%s%s</div>" % (
            card("Green first time, by regression stage", dora_charts.hbars(stage_rates, dora_charts.share, "First-pass rate")),
            card("Where the regression found something",
                 dora_charts.hbars([("Local", sw["found"]["local"]), ("Preview", sw["found"]["preview"]),
                        ("Production", sw["found"]["prod"])], dora_charts.compact, "Defects found by stage"),
                 "features whose stage needed a fix, and production rollbacks")))

    review = section(
        "review", "Code review", "How much the review found, how many rounds it took, and what became of it.",
        tiles(
            {"abs": ("Review rounds per feature", dora_charts.compact(x["rounds_per_feature"]),
                     "median · runs of the review, not sessions · %d features" % x["reviewed_n"],
                     x["rounds_per_feature"]),
             "norm": ("Review rounds per feature", "—" if nm["rounds"] is None else "%.1f" % nm["rounds"],
                      "median per standard feature", nm["rounds"])},
            {"abs": ("Review threads per feature", dora_charts.compact(x["threads_per_feature"]),
                     "median · %s threads in all" % dora_charts.compact(x["review_threads_all"]), x["threads_per_feature"]),
             "norm": ("Review threads per feature", "—" if nm["threads"] is None else "%.0f" % nm["threads"],
                      "median per standard feature", nm["threads"])},
            ("Review threads per PR", dora_charts.compact(x["threads_per_pr"]),
             "median · %s threads on %d merged PRs" % (dora_charts.compact(x["threads"]), x["merged"]), x["threads_per_pr"]),
            ("Threads closed without a fix", dora_charts.share(x["declined_share"]), "declined by the author",
             x["declined_share"]),
            ("Threads still open", dora_charts.share(x["open_share"]), "neither fixed nor declined", x["open_share"]),
            ("Review threads resolved", dora_charts.share(dv["resolved"]), "of %s threads" % dora_charts.compact(x["threads"]),
             dv["resolved"])),
        "<div class=two>%s%s</div>" % (
            dual(("Review rounds per feature",
                  dora_charts.hbars([(f, v["rounds"]) for f, v in reversed(x["reviewed_features"])], dora_charts.compact,
                        "Review rounds per feature"),
                  "runs of the automatic review over all the feature's pull requests"),
                 ("Review rounds per standard feature",
                  dora_charts.hbars([(f, v["rounds"]) for f, v in reversed(nm["reviewed"][-10:])], lambda v: "%.1f" % v,
                        "Review rounds per standard feature"), "each feature's rounds divided by its size")),
            card("Review sessions",
                 dora_charts.hbars([("Sessions", x["review_sessions"]), ("Rounds they handed back", x["review_rounds"]),
                        ("Findings declined as reversals", x["reversals"])], dora_charts.compact, "Review sessions"),
                 "from the review log: one session can carry several rounds")),
        dual(("Review threads per feature, by what became of them",
              dora_charts.stacked_rows([(f, {"fixed": v["fixed"], "declined": v["declined"], "open": v["open"]})
                            for f, v in reversed(x["reviewed_features"])],
                           ("fixed", "declined", "open"),
                           {"fixed": "Fixed", "declined": "Closed without a fix", "open": "Still open"},
                           dora_charts.compact, "Threads by fate"), ""),
             ("Review threads per standard feature, by what became of them",
              dora_charts.stacked_rows([(f, {k: v[k] for k in ("fixed", "declined", "open")})
                            for f, v in reversed(nm["reviewed"][-10:])],
                           ("fixed", "declined", "open"),
                           {"fixed": "Fixed", "declined": "Closed without a fix", "open": "Still open"},
                           lambda v: "%.0f" % v, "Threads by fate per standard feature"), "")))

    defects = section(
        "defects", "Defects and rework", "What broke, how fast it was mended, and what had to be done again.",
        tiles(
            ("Defect density", "—" if sw["defect_density"] is None else "%.2f" % sw["defect_density"],
             "bugs per 1,000 lines changed · %d bugs" % sw["bugs"], sw["defect_density"]),
            ("Bug resolution time", dora_charts.span(sw["bug_resolution"]), "median, opened to closed", sw["bug_resolution"]),
            ("Reopened issues", dora_charts.share(sw["reopened"]), "%d of the closed ones" % sw["reopened_n"], sw["reopened"]),
            ("Rollback ratio", "—" if cur["failure"] is None else "%d%%" % round(cur["failure"] * 100),
             "production deploys rolled back", cur["failure"]),
            ("Reverts", dora_charts.compact(hist.get("reverts")), "commits that undid one on main", hist.get("reverts"))))

    mix = section(
        "mix", "Work mix", "What the changes were: new value, upkeep or tidying, and whether they were planned.",
        tiles(
            ("Planned work", dora_charts.share(sw["planned"]), "changes from a PR of an issue", sw["planned"]),
            ("Changes through a PR", dora_charts.share(sw["through_pr"]), "change control: reviewed before main",
             sw["through_pr"]),
            ("Refactor work", dora_charts.share(sw["refactor"]), "of changes, by commit type", sw["refactor"]),
            ("Support work", dora_charts.share(sw["support"]), "fixes, chores, CI and dependencies", sw["support"]),
            ("Commits", dora_charts.compact(hist.get("commits")), "%s lines added, %s removed"
             % (dora_charts.compact(hist.get("added")), dora_charts.compact(hist.get("removed")))),
            ("Migrations", dora_charts.compact(hist.get("migrations")), "schema changes added")),
        "<div class=two>%s%s</div>" % (
            card("Work by commit type", dora_charts.hbars(sw["types"], dora_charts.compact, "Commit types"),
                 "the %d changes shipped in the last %d days" % (sw["changes"], dora_numbers.WINDOW)),
            card("Throughput per person", people)))

    code = x["code"] or {}
    hy = x["hygiene"]
    health = section(
        "health", "Code and project health", "The tracked source as it stands, and how work traces from issue to branch.",
        tiles(
            ("Source lines", dora_charts.compact(code.get("lines")), "in %s files" % dora_charts.compact(code.get("files"))),
            ("Comment lines", dora_charts.share(code.get("comments")), "of source lines", code.get("comments")),
            ("Large files", dora_charts.compact(code.get("large")), "over %d lines" % metrics_extra.LARGE_FILE,
             dora_numbers.ratio(code.get("large"), code.get("files"))),
            ("Tests", dora_charts.share(code.get("tests")), "of source lines", code.get("tests")),
            ("Issues under a parent", dora_charts.share(hy["parented"]), "of %d issues" % hy["issues"], hy["parented"]),
            ("Branches named after an issue", dora_charts.share(hy["linked"]), "of PR branches", hy["linked"]),
            ("Open issues with an owner", dora_charts.share(hy["assigned"]), "of %d open" % hy["open"], hy["assigned"])))

    human = section(
        "human", "The person and Claude",
        "How much a person had to work for what Claude did: every time they stepped in, and how long it took them.",
        tiles(
            ("Claude's run between interventions", "—" if hm["run_calls"] is None else "%.0f" % hm["run_calls"],
             "median tool calls before the person is needed", hm["run_calls"]),
            ("Time Claude runs alone", dora_charts.span(hm["run_time"]), "median, between two interventions",
             hm["run_time"]),
            ("Sessions with no one stepping in", dora_charts.share(hm["unattended"]),
             "%d of %d that sclaude started" % (hm["unattended_n"], hm["started"]), hm["unattended"]),
            ("Person's share of the time", dora_charts.share(hm["person_share"]),
             "%s of a person against %s of Claude" % (dora_charts.span(hm["person_s"]), dora_charts.span(hm["claude_s"])),
             hm["person_share"]),
            ("Person's minutes per hour of Claude",
             "—" if hm["minutes_per_hour"] is None else "%.0f min" % hm["minutes_per_hour"],
             "answering, reading, deciding", hm["minutes_per_hour"]),
            {"abs": ("Interventions per feature", dora_charts.compact(hm["turns_per_feature"]), "median per finished feature",
                     hm["turns_per_feature"]),
             "norm": ("Interventions per feature",
                      "—" if hm["turns_per_feature_norm"] is None else "%.1f" % hm["turns_per_feature_norm"],
                      "median per standard feature", hm["turns_per_feature_norm"])},
            {"abs": ("Person's time per feature",
                     "—" if hm["minutes_per_feature"] is None else "%.0f min" % hm["minutes_per_feature"],
                     "median per finished feature", hm["minutes_per_feature"]),
             "norm": ("Person's time per feature",
                      "—" if hm["minutes_per_feature_norm"] is None else "%.0f min" % hm["minutes_per_feature_norm"],
                      "median per standard feature", hm["minutes_per_feature_norm"])},
            ("Autonomy", "—" if ai["autonomy"] is None else "%.0f" % ai["autonomy"],
             "tool calls per human input · %d inputs" % ai["inputs"], ai["autonomy"]),
            {"abs": ("Questions per feature", dora_charts.compact(ai["questions_per_feature"]), "median, Claude asking the person"),
             "norm": ("Questions per feature", "—" if nm["questions"] is None else "%.1f" % nm["questions"],
                      "median per standard feature")},
            ("Sessions by hand", dora_charts.share(ai["manual"]), "the rest sclaude started", ai["manual"]),
            ("Adoption", dora_charts.share(ai["adoption"]), "of %d commit authors use Claude" % ai["developers"],
             ai["adoption"])),
        "<div class=two>%s%s</div>" % (
            card("Autonomy per week", dora_charts.columns(hm["weekly"], lambda w: w[1], lambda v: "%.0f" % v,
                                              "Tool calls per intervention per week"),
                 "tool calls per intervention: rising means Claude needs the person less"),
            card("Person's share of the time per week", dora_charts.columns(hm["weekly"], lambda w: w[2], dora_charts.share,
                                                                "Person's share per week"),
                 "falling means more of the work is Claude's")),
        "<div class=two>%s%s</div>" % (
            card("Interventions by step", dora_charts.hbars([(dora_charts.STEP_NAMES.get(k, k), v[0]) for k, v in hm["steps"]],
                                                dora_charts.compact, "Interventions by step"),
                 "where the person is needed most"),
            card("Person's time by step", dora_charts.hbars([(dora_charts.STEP_NAMES.get(k, k), v[1]) for k, v in hm["steps"]],
                                                dora_charts.span, "Person's time by step"),
                 "each wait capped at half an hour: longer, they were away")),
        dual(("Interventions per feature",
              dora_charts.hbars([(f, v[0]) for f, v in reversed(hm["features"])], dora_charts.compact, "Interventions per feature"),
              "the last finished features"),
             ("Interventions per standard feature",
              dora_charts.hbars([(f, v[0] / sizes[f]["unit"]) for f, v in reversed(hm["features"]) if f in sizes],
                    lambda v: "%.1f" % v, "Interventions per standard feature"),
              "each feature's interventions divided by its size")))

    claude = section(
        "claude", "Claude at work", "Every session sclaude ran for this product, and the ones run here by hand.",
        tiles(
            ("Sessions", dora_charts.compact(x["sessions"]), "%d in the last %d days" % (x["sessions_recent"], dora_numbers.WINDOW)),
            ("Subagents", dora_charts.compact(x["subagents"]), "started by those sessions"),
            ("Tool calls", dora_charts.compact(x["tool_calls"]), "median %s per session" % dora_charts.compact(x["calls_per_session"])),
            ("Commits by Claude", dora_charts.share(dora_numbers.ratio(hist.get("by_claude"), hist.get("commits"))),
             "%d of %d in the last %d days" % (hist.get("by_claude", 0), hist.get("commits", 0), dora_numbers.WINDOW)),
            ("Subagents per session", "—" if ai["subagents_per_session"] is None
             else "%.1f" % ai["subagents_per_session"], "on average"),
            ("Sessions per week", "%.0f" % ai["sessions_per_week"], "last %d days" % dora_numbers.WINDOW),
            ("Tokens per week", dora_charts.compact(ai["tokens_per_week"]), "last %d days" % dora_numbers.WINDOW),
            ("Session length", "—" if ai["session_minutes"] is None else "%.0f min" % ai["session_minutes"],
             "median")),
        "<div class=two>%s%s</div>" % (
            # An MCP tool by its own name: `mcp__<server>__<tool>`.
            card("Most used tools", dora_charts.hbars([(k.rsplit("__", 1)[-1], v) for k, v in x["tools"]],
                                          dora_charts.compact, "Tool calls")),
            card("What of Claude Code is used", dora_charts.hbars(ai["uses"], dora_charts.share, "Feature use"),
                 "share of sessions that used each")),
        card("When the work happens", dora_charts.heatmap(ai["heat"]), "sessions started, by weekday and hour"))

    cost = section(
        "cost", "Cost and tokens", "What a result costs. Dollars are Claude Code's own account, not an estimate.",
        tiles(
            ("Spend, last %d days" % dora_numbers.WINDOW, dora_charts.money(x["cost_recent"]), "%s all time" % dora_charts.money(x["cost"])),
            {"abs": ("Per finished feature", dora_charts.money(x["per_feature"]), "median of its sessions' spend"),
             "norm": ("Per finished feature", dora_charts.money(nm["cost"]), "median per standard feature")},
            ("Per production deploy", dora_charts.money(x["per_deploy"]), "last %d days" % dora_numbers.WINDOW),
            ("Per merged pull request", dora_charts.money(x["per_pr"]), "last %d days" % dora_numbers.WINDOW),
            ("Per 1,000 lines changed", dora_charts.money(x["per_kloc"]), "on main, last %d days" % dora_numbers.WINDOW),
            ("Cache hit rate", dora_charts.share(x["cache_hit"]), "input read from the prompt cache", x["cache_hit"]),
            ("Thinking", dora_charts.share(x["thinking_share"]), "of output tokens"),
            ("Output per tool call", dora_charts.compact(x["output_per_call"]), "tokens"),
            ("Time in the model", dora_charts.share(x["api_share"]), "of session time, the rest in tools")),
        "<div class=two>%s%s</div>" % (
            dual(("Spend per week", dora_charts.columns(wk, lambda w: w[1], dora_charts.money, "Spend per week"), ""),
                 ("Spend per standard feature shipped, per week",
                  dora_charts.columns(nm["weekly_spend"], lambda w: w[1], dora_charts.money, "Spend per standard feature shipped"),
                  "the week's spend over the size of what it shipped")),
            card("Cache hit rate per week", dora_charts.columns(wk, lambda w: w[2], dora_charts.share, "Cache hit rate per week"))),
        "<div class=two>%s%s</div>" % (
            dual(("Spend per finished feature", dora_charts.hbars(x["by_feature"], dora_charts.money, "Spend per feature"), ""),
                 ("Spend per standard feature", dora_charts.hbars(nm["by_feature"], dora_charts.money, "Spend per standard feature"),
                  "each feature's spend divided by its size")),
            card("Spend by step", dora_charts.hbars([(dora_charts.STEP_NAMES.get(k, k), v) for k, v in x["by_step"]],
                                        dora_charts.money, "Spend by step"))),
        "<div class=two>%s%s</div>" % (
            card("Spend by model", dora_charts.hbars(sorted(x["models"].items(), key=lambda kv: -kv[1]),
                                         dora_charts.money, "Spend by model")),
            card("Review sessions' context",
                 dora_charts.hbars([("Held before round one", x["review_door"])], dora_charts.compact, "Context"),
                 "median tokens · %s of the window used when handed back" % dora_charts.share(x["review_end_pct"]))))

    process = section(
        "process", "Process learning", "Where the rules got in the way, and whether they have learnt from it.",
        tiles(
            ("Deferred friction age", "—" if x["deferred_age"][0] is None else "%d days" % x["deferred_age"][0],
             "median · oldest %s days" % dora_charts.compact(x["deferred_age"][1]), x["deferred_age"][0])),
        "<div class=two>%s%s</div>" % (
            card("Friction reviews, by verdict",
                 dora_charts.hbars([(dora_charts.VERDICT_NAMES.get(k, k), v) for k, v in
                        sorted(fr["verdicts"].items(), key=lambda kv: -kv[1])], dora_charts.compact, "Verdicts"),
                 "%d reviews · %d changed the rules · %d entries put off for the monthly review"
                 % (fr["reviews"], fr["fixed"], x["deferred"])),
            card("Refusals per 100 tool calls, per week",
                 dora_charts.columns(wk, lambda w: w[3], lambda v: "%.1f" % v, "Refusals per week"),
                 "falling means the rules have learnt")),
        "<div class=two>%s%s</div>" % (
            card("Tool calls refused, by whom",
                 dora_charts.hbars([(dora_charts.DENIAL_NAMES.get(k, k), v) for k, v in
                        sorted(x["denials"].items(), key=lambda kv: -kv[1])], dora_charts.compact, "Refusals"),
                 "out of %s calls" % dora_charts.compact(x["tool_calls"])),
            card("Session trouble",
                 dora_charts.hbars([("API errors", x["api_errors"]), ("Context compactions", x["compactions"])],
                       dora_charts.compact, "Session trouble"))))

    rows = []
    for d in m["recent"]:
        what = ("<code>%s</code>" % dora_charts.esc(d["sha"][:8])) if d["sha"] else dora_charts.esc(d.get("feature") or "")
        if d["url"]:
            what = "<a href='https://%s'>%s</a>" % (dora_charts.esc(d["url"].replace("https://", "")), what)
        status = ("<span class=bad><i>▼</i>rolled back after %s</span>"
                  % dora_charts.esc(dora_charts.span((d["restored"] - d["at"]).total_seconds()))) if d["restored"] else ""
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (dora_charts.esc(dora_charts.stamp(d["at"])), what, d["changes"] or "—", dora_charts.esc(dora_charts.span(d["lead"])), status))
    table = ("<div class=scroll><table><tr><th>Deployed</th><th>Commit</th><th>Changes</th>"
             "<th>Median lead time</th><th></th></tr>%s</table></div>" % "".join(rows)) \
        if rows else "<p class=empty>No production deploy found.</p>"
    weeks_rows = "".join("<tr><td>%s</td><td>%d</td><td>%s</td></tr>"
                         % (dora_charts.esc(wk[0].strftime("%Y-%m-%d")), wk[1], dora_charts.esc(dora_charts.span(wk[2])))
                         for wk in reversed(m["weeks"]))
    notes = "".join("<li>%s</li>" % dora_charts.esc(n) for n in data["notes"])
    since = (" Production history since %s." % dora_charts.stamp(m["since"])) if m["since"] else ""
    tables = section(
        "records", "Records and method", "The rows the figures above are counted from, and how.",
        card("Recent production deploys", table),
        card("By week", "<div class=scroll><table><tr><th>Week of</th><th>Deploys</th>"
                        "<th>Median lead time</th></tr>%s</table></div>" % weeks_rows),
        card("How this is counted", (
            "<ul class=notes>"
            "<li>A deploy is a READY production deployment on Vercel. A change is a commit that "
            "a deploy put on production for the first time; a squashed pull request counts from "
            "its first commit.</li>"
            "<li>A failure is a production rollback: the incident comment sclaude writes on the "
            "issue, or a rollback in sclaude's own record of the feature. Restore time runs from "
            "the failed deploy to that rollback.</li>"
            "<li>DORA levels follow the State of DevOps thresholds: daily, weekly and monthly "
            "deploys; lead time under a day, week and month; failure rate up to 5, 10 and 15%%; "
            "restore within an hour, a day and a week.</li>"
            "<li>Sessions, tokens and dollars are read from Claude Code's transcripts of this "
            "product's checkout and worktrees; its own cost record, not a price list. A commit "
            "is Claude's when a session signed it.</li>"
            "<li>Regression, friction and cycle times come from sclaude's record of each "
            "finished feature; review rounds from its review log; acceptance criteria from the "
            "issue.</li>%s</ul>" % notes)),
        card("Not measured here", "<ul class=notes>%s</ul>" % "".join(
            "<li>%s</li>" % dora_charts.esc(n) for n in dora_charts.NOT_MEASURED)))

    switch = (
        "<div class=switch><div class=modes role=group aria-label='How features are compared'>"
        "<button type=button data-mode=abs aria-pressed=true>Absolute</button>"
        "<button type=button data-mode=norm aria-pressed=false>Per complexity ◆</button></div>"
        "<p class=sub>◆ marks the figures that scale with a feature's size. Per complexity "
        "divides them by it, so features of different size compare: values are per standard "
        "feature — the median one, %s acceptance criteria — and the weekly charts weigh each "
        "week by the size of what it delivered.</p></div>" % dora_charts.compact(nm["standard"]))
    # The whole at a glance: each direction's figures, scored by their own
    # bands (metrics_guide.Band.score) and averaged into one spoke.
    spend = [w[1] for w in nm["weekly_spend"] if w[1]]
    trend = spend[-1] / metrics_extra.med(spend[:-1]) if len(spend) > 1 and metrics_extra.med(spend[:-1]) else None

    def same(label, raw):
        return (label, raw, raw)
    directions = (
        ("Speed", [same("Deployment frequency", cur["per_day"]), same("Lead time for changes", cur["lead"]),
                   ("Feature cycle time", x["cycle"], nm["cycle"]), ("Time to market", ai["market"], nm["market"]),
                   same("PR aging", dv["aging"])]),
        ("Stability", [same("Change failure rate", cur["failure"]), same("Time to restore", cur["restore"]),
                       same("Rework rate", dm["rework"]), same("Hotfix rate", dm["hotfix"]),
                       same("Escaped defects", sw["escaped"]), same("Production suite green", dm["reliability"])]),
        ("Quality", [
            same("Regression green first time", first_time),
            ("Review rounds per feature", x["rounds_per_feature"], nm["rounds"]),
            ("Review threads per feature", x["threads_per_feature"], nm["threads"]),
            same("Threads still open", x["open_share"]), same("Reopened issues", sw["reopened"]),
            same("Tests in new lines", dora_numbers.ratio(hist.get("test_added"), hist.get("added")))]),
        ("Clear requirements", [same("Requirements changed in development", rq["significant"]),
                                same("Requirements unclear at the start", rq["unclear"]),
                                same("Questions per criterion", rq["per_criterion"]),
                                same("Request grew in planning", rq["growth"])]),
        ("Flow", [same("Flow efficiency", ai["flow"]), same("Time in the queue", ai["queue"]),
                  same("Pickup time", dv["pickup"]), same("Review time", dv["review"]),
                  same("Features at once", ai["concurrent_max"])]),
        ("Autonomy", [same("Claude's run between interventions", hm["run_calls"]),
                      same("Person's share of the time", hm["person_share"]),
                      same("Sessions with no one stepping in", hm["unattended"]),
                      ("Interventions per feature", hm["turns_per_feature"], hm["turns_per_feature_norm"]),
                      ("Person's time per feature", hm["minutes_per_feature"], hm["minutes_per_feature_norm"])]),
        ("Cost", [same("Cache hit rate", x["cache_hit"]), same("Spend trend", trend)]),
        ("Discipline", [same("Changes through a PR", sw["through_pr"]), same("Planned work", sw["planned"]),
                        same("PRs without review", dv["unreviewed"]),
                        same("Branches named after an issue", hy["linked"]),
                        same("Open issues with an owner", hy["assigned"])]),
    )

    def health_block(mode):
        axes = [dora_charts.axis(n, ms, mode) for n, ms in directions]
        index, spread, best, worst = dora_charts.health_of(axes)
        suffix = "" if mode == "abs" else ", per complexity"
        bars = dora_charts.hbars([(n, v) for n, v, _ in axes], lambda v: "%d" % round(v), "Directions", width=380)
        figures = tiles(
            ("Health index", "—" if index is None else "%d" % round(index),
             "out of 100, the mean of the %d directions%s" % (len(axes), suffix), index),
            ("Imbalance", "—" if spread is None else "%d" % round(spread),
             "points between %s and %s" % (best[0], worst[0]) if best else "", spread),
            ("Weakest direction", worst[0] if worst else "—",
             "%d of 100 — where to look first" % round(worst[1]) if worst else "", worst[1] if worst else None))
        return ("<div class='%s'>%s%s</div>" % (
            mode, figures,
            card("The shape of the whole",
                 "<div class=radar-wrap><div>%s</div><div>%s</div></div>" % (dora_charts.radar(axes, "Health radar"), bars),
                 "Each spoke is a direction's figures, each scored 0–100 by its own bands — 100 at the "
                 "good mark, 50 at the watch mark — and averaged. A round shape is balanced; a dent is "
                 "where to look. Point at a dot for its figures.")))
    glance = section(
        "health-index", "Health at a glance",
        "Many figures, one picture: eight directions of the work, and how even they are.",
        health_block("abs"), health_block("norm"))

    # Generated teammates only where the product's config asks for them
    # (`metricsTeam: demo`); otherwise the page has no team part, and the
    # real people's figures stay in the work mix's table.
    team = dora_team.team_section(x, cur, dv, sw, hm, ai, first_time, hist) \
        if dora_team.team_mode(repo) == "demo" else ""

    parts = (("overview", "Overview", overview), ("health-index", "Health at a glance", glance),
             ("dora", "Delivery performance", dora),
             ("flow", "Flow of work", flow), ("prs", "Pull requests and builds", prs),
             ("requirements", "Requirements", requirements), ("testing", "Testing", testing),
             ("review", "Code review", review), ("defects", "Defects and rework", defects),
             ("mix", "Work mix", mix), ("health", "Code and project health", health),
             ("human", "The person and Claude", human), ("claude", "Claude at work", claude),
             ("cost", "Cost and tokens", cost), ("team", "Team", team),
             ("process", "Process learning", process),
             ("records", "Records and method", tables))
    parts = tuple(p for p in parts if p[2])
    body = (
        "%s<main><h1>What sclaude measures</h1>"
        "<p class=lead>%s · built %s · the last %d days unless a figure says otherwise.%s "
        "Rebuilt in the background when sclaude starts, at most every few hours.</p>%s%s</main>"
        % (contents([(k, t) for k, t, _ in parts]), dora_charts.esc(name), dora_charts.esc(dora_charts.stamp(m["now"])), dora_numbers.WINDOW, dora_charts.esc(since),
           switch, "".join(html_ for _, _, html_ in parts)))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            # An open tab follows the rebuilds by itself.
            "<meta http-equiv=refresh content=3600>"
            "<title>DORA metrics</title><style>%s</style></head><body>%s"
            "<div id=tip role=tooltip></div><script>%s</script><script>%s</script></body></html>"
            % (STYLE, body, TIP_JS, dora_team.TEAM_JS))
