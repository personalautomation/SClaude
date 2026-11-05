# The DORA page's team section: the profiles, simulated or real, and the
# section drawn from them.
#
# Part of sclaude/lib/metrics/dora.py.

import json
import os

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import metrics_guide  # noqa: E402

import dora_numbers, dora_page, dora_store


# The team part's script: draws the simulated teammates from the base, keeps
# the draw in the browser, and lays the developers side by side.
TEAM_JS = """(function(){
var holder=document.getElementById('team');if(!holder)return;
var data=JSON.parse(document.getElementById('team-data').textContent);
var KEY='sclaude-team-factors-v1';
function load(k){try{return localStorage.getItem(k)}catch(e){return null}}
function store(k,v){try{localStorage.setItem(k,v)}catch(e){}}
var factors={};try{factors=JSON.parse(load(KEY)||'{}')||{}}catch(e){factors={}}
// One draw per teammate and figure, kept: the page shows the same team on
// every load until someone asks for another.
function draw(){var changed=false;data.others.forEach(function(d){factors[d]=factors[d]||{};
data.metrics.forEach(function(m){var p=m.profiles[d];if(!p||factors[d][m.key]!==undefined)return;
factors[d][m.key]=p[1]+Math.random()*(p[2]-p[1]);changed=true})});
if(changed)store(KEY,JSON.stringify(factors))}
draw();
function value(dev,m){if(dev===data.me)return m.value;var p=m.profiles[dev];
if(!p)return m.value;if(p[0]==='none')return null;var f=factors[dev][m.key];
if(p[0]==='abs')return f;if(m.value===null||m.value===undefined)return null;
var v=m.value*f;if(m.cap!==undefined&&m.cap!==null)v=Math.min(m.cap,v);
return m.fmt==='int'?Math.round(v):v}
function span(s){if(s===null||s===undefined)return '—';if(s<3600)return Math.max(1,Math.round(s/60))+' min';
if(s<172800)return (s/3600).toFixed(1)+' h';return (s/86400).toFixed(1)+' days'}
function compact(n){if(n===null||n===undefined)return '—';var a=Math.abs(n);
if(a>=1e6)return (n/1e6).toFixed(1)+'M';if(a>=1e4)return (n/1e3).toFixed(1)+'K';return Math.round(n).toLocaleString('en')}
function fmt(m,v){if(v===null||v===undefined||isNaN(v))return '—';
switch(m.fmt){case 'share':return Math.round(v*100)+'%';case 'span':return span(v);
case 'money':return '$'+(v>=100?Math.round(v).toLocaleString('en'):v.toFixed(2));
case 'dec1':return v.toFixed(1);case 'dec2':return v.toFixed(2);default:return compact(v)}}
function band(m,v){var b=m.band;if(!b||v===null||v===undefined)return null;var d;
if(b.kind==='lower')d=(v-b.a)/((b.b-b.a)||1);else if(b.kind==='higher')d=(b.a-v)/((b.a-b.b)||1);
else d=Math.max(b.a[0]-v,v-b.a[1])/(b.b||1);return d<=0?'good':d<=1?'watch':'poor'}
var ICON={good:'▲',watch:'■',poor:'▼'};
function score(m,v){var b=m.band;var d;if(b.kind==='lower')d=(v-b.a)/((b.b-b.a)||1);
else if(b.kind==='higher')d=(b.a-v)/((b.a-b.b)||1);else d=Math.max(b.a[0]-v,v-b.a[1])/(b.b||1);
return d<=0?100:Math.max(0,100-50*d)}
// The note the page's hover shows: why, aim, how — and, for a figure per
// person, where the other developers' data comes from.
function attach(host,title,n){if(!n)return;var box=el('div','note');box.hidden=true;
box.setAttribute('data-title',title);
[['Why',n[0]],['Aim',n[1]],['How',n[2]+' '+data.sources]].forEach(function(p){var para=el('p');
para.appendChild(el('b',null,p[0]));para.appendChild(document.createTextNode(' '+p[1]));box.appendChild(para)});
host.appendChild(box);host.classList.add('hasnote')}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;
if(text!==undefined)e.textContent=text;return e}
function render(){
holder.textContent='';var devs=[data.me].concat(data.others);

var vals={};devs.forEach(function(d){vals[d]={};data.metrics.forEach(function(m){vals[d][m.key]=value(d,m)})});
// Derived, from the drawn figures.
devs.forEach(function(d){var v=vals[d];v.leverage=v.person_hours?v.features/v.person_hours:null;
v.merge_freq=v.prs!==null?v.prs/(30/7):null});
// The team in four figures.
var total=function(k){return devs.reduce(function(a,d){return a+(vals[d][k]||0)},0)};
var commits=devs.map(function(d){return [d,vals[d].commits||0]}).sort(function(a,b){return b[1]-a[1]});
var half=total('commits')/2,acc=0,bus=0;commits.forEach(function(c){if(acc<half){acc+=c[1];bus++}});
var tiles=el('div','tiles');
[['Features finished, team',compact(total('features')),'by '+devs.length+' developers'],
 ['Lines changed, team',compact(total('lines')),'last 30 days'],
 ['Bus factor',String(bus),'developers who hold half of the commits'],
 ['Spend, team','$'+Math.round(total('spend')).toLocaleString('en'),'last 30 days']].forEach(function(t,i){
var tile=el('div','tile');tile.appendChild(el('div','label',t[0]));tile.appendChild(el('div','value',t[1]));
tile.appendChild(el('div','sub',t[2]));
attach(tile,t[0],data.notes[['team_features','team_lines','bus','team_spend'][i]]);tiles.appendChild(tile)});
holder.appendChild(tiles);
// The scorecard: a row a figure, a column a developer, a bar against the row's best.
var card=el('div','card');card.appendChild(el('h3',null,'Developers side by side'));
card.appendChild(el('p','sub','Each bar is against the longest in its row; the mark is the figure\\'s own bands, as everywhere on the page.'));
var wrap=el('div','scroll'),table=el('table','team-table'),head=el('tr');head.appendChild(el('th',null,''));
devs.forEach(function(d,i){var th=el('th');var key=el('i','key s'+(i+1));th.appendChild(key);
th.appendChild(document.createTextNode(' '+d));head.appendChild(th)});table.appendChild(head);
var extra=[{key:'leverage',label:'Features per person-hour',group:'Claude',fmt:'dec2',band:null},
{key:'merge_freq',label:'Merge frequency, per week',group:'Output',fmt:'dec1',band:data.mergeBand}];
var rows=data.metrics.filter(function(m){return !m.mix}).concat(extra),group=null;
rows.forEach(function(m){if(m.group!==group){group=m.group;var gr=el('tr','group');var td=el('td',null,group);
td.colSpan=devs.length+1;gr.appendChild(td);table.appendChild(gr)}
var tr=el('tr');var name=el('td','metric',m.label);tr.appendChild(name);
attach(tr,m.label,m.note||data.notes[m.key]);
var nums=devs.map(function(d){return vals[d][m.key]}).filter(function(v){return v!==null&&v!==undefined});
var max=Math.max.apply(null,nums.concat([0]))||1;
devs.forEach(function(d,i){var v=vals[d][m.key];var td=el('td','cell');
var line=el('div','cellv');line.appendChild(document.createTextNode(fmt(m,v)));
var st=band(m,v);if(st){var mark=el('span','lvl '+st);var ic=el('i',null,ICON[st]);mark.appendChild(ic);line.appendChild(mark)}
td.appendChild(line);if(v!==null&&v!==undefined){var track=el('div','track');var fill=el('div','fill s'+(i+1));
fill.style.width=Math.max(2,100*v/max)+'%';track.appendChild(fill);td.appendChild(track)}
tr.appendChild(td)});table.appendChild(tr)});
wrap.appendChild(table);card.appendChild(wrap);holder.appendChild(card);
// Who holds what: each developer's share of commits, lines and features.
var two=el('div','two');
var share=el('div','card');share.appendChild(el('h3',null,'Who holds what'));
share.appendChild(el('p','sub','each developer\\'s share of the team\\'s output, last 30 days'));
var legend=el('div','legend');devs.forEach(function(d,i){var s=el('span');s.appendChild(el('i','key s'+(i+1)));
s.appendChild(document.createTextNode(d));legend.appendChild(s)});share.appendChild(legend);
[['commits','Commits'],['lines','Lines changed'],['features','Features'],['bugs','Bugs fixed'],['spend','Spend']].forEach(function(k){
var t=total(k[0]);var row=el('div','stackrow');row.appendChild(el('span','stacklabel',k[1]));var st=el('div','stack');
devs.forEach(function(d,i){var v=vals[d][k[0]]||0;if(!t||!v)return;var seg=el('div','seg s'+(i+1));
seg.style.width=(100*v/t)+'%';seg.title=d+' · '+Math.round(100*v/t)+'%';st.appendChild(seg)});
row.appendChild(st);share.appendChild(row)});two.appendChild(share);
// What each one works on: the mix of their changes by kind.
var mix=el('div','card');mix.appendChild(el('h3',null,'What each one works on'));
mix.appendChild(el('p','sub','changes by kind, per developer'));
var kinds=data.metrics.filter(function(m){return m.mix});var leg2=el('div','legend');
kinds.forEach(function(m,i){var s=el('span');s.appendChild(el('i','key s'+(i+1)));s.appendChild(document.createTextNode(m.label));leg2.appendChild(s)});
mix.appendChild(leg2);
devs.forEach(function(d){var parts=kinds.map(function(m){return Math.max(0,vals[d][m.key]||0)});
var sum=parts.reduce(function(a,b){return a+b},0)||1;var row=el('div','stackrow');row.appendChild(el('span','stacklabel',d));
var st=el('div','stack');parts.forEach(function(p,i){if(!p)return;var seg=el('div','seg s'+(i+1));seg.style.width=(100*p/sum)+'%';
seg.title=d+' · '+kinds[i].label+' '+Math.round(100*p/sum)+'%';st.appendChild(seg)});row.appendChild(st);mix.appendChild(row)});
two.appendChild(mix);holder.appendChild(two);
// Strong and weak sides with Claude: each person's figures scored by their
// own bands, the best three and the three to work on, with a habit for each.
var coach=el('div','card');coach.appendChild(el('h3',null,'Working with Claude: strong sides and what to work on'));
coach.appendChild(el('p','sub','the adoption and effectiveness figures above, each scored 0–100 by its bands as on the radar; the AI score is their mean, and every weak side has a habit to try'));
var grid=el('div','coach');
devs.forEach(function(d,i){var scored=[];
data.metrics.forEach(function(m){if(['AI adoption','AI effectiveness'].indexOf(m.group)<0)return;
var v=vals[d][m.key];if(v===null||v===undefined||!m.band)return;scored.push([m,score(m,v),v])});
var mean=scored.length?scored.reduce(function(a,b){return a+b[1]},0)/scored.length:null;
var box=el('div','coach-card');var h=el('div','coach-head');h.appendChild(el('i','key s'+(i+1)));
h.appendChild(el('b',null,' '+d));h.appendChild(el('span','coach-score',mean===null?'':'AI score '+Math.round(mean)));box.appendChild(h);
var best=scored.slice().sort(function(a,b){return b[1]-a[1]}).filter(function(s){return s[1]>=75}).slice(0,3);
var worst=scored.slice().sort(function(a,b){return a[1]-b[1]}).filter(function(s){return s[1]<75}).slice(0,3);
box.appendChild(el('div','coach-sub','Strong'));
if(!best.length)box.appendChild(el('p','sub','nothing at the mark yet'));
best.forEach(function(s){var p=el('p','coach-line');var mk=el('span','lvl good');mk.appendChild(el('i',null,'▲'));
p.appendChild(mk);p.appendChild(document.createTextNode(' '+s[0].label+' · '+fmt(s[0],s[2])));box.appendChild(p)});
box.appendChild(el('div','coach-sub','To work on'));
if(!worst.length)box.appendChild(el('p','sub','nothing below the mark'));
worst.forEach(function(s){var st=s[1]>=50?'watch':'poor';var p=el('p','coach-line');var mk=el('span','lvl '+st);
mk.appendChild(el('i',null,ICON[st]));p.appendChild(mk);p.appendChild(document.createTextNode(' '+s[0].label+' · '+fmt(s[0],s[2])));
box.appendChild(p);if(data.tips[s[0].key])box.appendChild(el('p','coach-tip',data.tips[s[0].key]))});
grid.appendChild(box)});coach.appendChild(grid);holder.appendChild(coach)}
render()})();
"""


# The teammates the team part simulates, and how each differs from the one real
# developer: [mode, low, high] per figure — "x" multiplies the real figure by a
# draw between low and high, "abs" draws the figure itself, "none" has none.
# Alex and Anastasia write far more code than the base, Anastasia cleaner;
# Kris only fixes bugs.
SIMULATED = ("Alex", "Anastasia", "Kris")
PROFILES = {
    "features": {"Alex": ["x", 1.6, 2.2], "Anastasia": ["x", 1.4, 2.0], "Kris": ["abs", 0, 0]},
    "prs": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.5, 2.2], "Kris": ["x", 0.8, 1.4]},
    "commits": {"Alex": ["x", 2.0, 3.0], "Anastasia": ["x", 1.8, 2.6], "Kris": ["x", 0.6, 1.0]},
    "lines": {"Alex": ["x", 2.5, 4.0], "Anastasia": ["x", 2.0, 3.5], "Kris": ["x", 0.1, 0.25]},
    "bugs": {"Alex": ["x", 0.5, 0.9], "Anastasia": ["x", 0.4, 0.8], "Kris": ["x", 1.2, 1.8]},
    "cycle": {"Alex": ["x", 0.9, 1.3], "Anastasia": ["x", 0.8, 1.1], "Kris": ["none", 0, 0]},
    "lead": {"Alex": ["x", 1.0, 1.4], "Anastasia": ["x", 0.8, 1.1], "Kris": ["x", 0.3, 0.6]},
    "aging": {"Alex": ["x", 1.1, 1.5], "Anastasia": ["x", 0.8, 1.1], "Kris": ["x", 0.3, 0.6]},
    "pr_size": {"Alex": ["x", 1.8, 2.8], "Anastasia": ["x", 1.3, 2.0], "Kris": ["x", 0.1, 0.25]},
    "green": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.05, 1.3], "Kris": ["x", 0.9, 1.2]},
    "rounds": {"Alex": ["x", 1.2, 1.6], "Anastasia": ["x", 0.6, 0.9], "Kris": ["abs", 1, 3]},
    "threads": {"Alex": ["x", 1.3, 1.8], "Anastasia": ["x", 0.7, 1.0], "Kris": ["abs", 2, 8]},
    "escaped": {"Alex": ["abs", 0.05, 0.15], "Anastasia": ["abs", 0, 0.05], "Kris": ["abs", 0, 0.03]},
    "reopened": {"Alex": ["x", 1.0, 1.5], "Anastasia": ["x", 0.5, 0.9], "Kris": ["x", 0.6, 1.2]},
    "run": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 1.2, 1.6], "Kris": ["x", 0.6, 0.9]},
    "person_share": {"Alex": ["x", 0.8, 1.1], "Anastasia": ["x", 0.7, 0.95], "Kris": ["x", 1.1, 1.4]},
    "interventions": {"Alex": ["x", 1.1, 1.5], "Anastasia": ["x", 0.7, 1.0], "Kris": ["none", 0, 0]},
    "questions": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 0.6, 0.9], "Kris": ["none", 0, 0]},
    "sessions": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.6, 2.2], "Kris": ["x", 0.8, 1.2]},
    "person_hours": {"Alex": ["x", 1.6, 2.4], "Anastasia": ["x", 1.2, 1.8], "Kris": ["x", 0.8, 1.2]},
    "spend": {"Alex": ["x", 2.0, 3.0], "Anastasia": ["x", 1.6, 2.4], "Kris": ["x", 0.4, 0.7]},
    "spend_feature": {"Alex": ["x", 1.0, 1.4], "Anastasia": ["x", 0.8, 1.1], "Kris": ["none", 0, 0]},
    # Working with Claude. Alex uses it heavily and loosely; Anastasia is the
    # practised one; Kris is still taking it up.
    "ai_commits": {"Alex": ["x", 0.9, 1.05], "Anastasia": ["x", 0.95, 1.1], "Kris": ["x", 0.3, 0.5]},
    "sessions_week": {"Alex": ["x", 1.8, 2.6], "Anastasia": ["x", 1.6, 2.2], "Kris": ["x", 0.4, 0.7]},
    "tokens_week": {"Alex": ["x", 2.2, 3.2], "Anastasia": ["x", 1.4, 2.0], "Kris": ["x", 0.2, 0.4]},
    "subagents": {"Alex": ["x", 1.2, 1.8], "Anastasia": ["x", 1.5, 2.2], "Kris": ["x", 0.2, 0.5]},
    "skills": {"Alex": ["x", 0.5, 0.9], "Anastasia": ["x", 1.3, 2.0], "Kris": ["x", 0.3, 0.6]},
    "plan": {"Alex": ["x", 0.3, 0.7], "Anastasia": ["x", 1.5, 2.5], "Kris": ["abs", 0, 0.03]},
    "mcp": {"Alex": ["x", 0.8, 1.3], "Anastasia": ["x", 1.4, 2.2], "Kris": ["x", 0.5, 1.0]},
    "top_model": {"Alex": ["abs", 0.92, 0.99], "Anastasia": ["abs", 0.55, 0.75], "Kris": ["abs", 0.8, 0.95]},
    "cache": {"Alex": ["x", 0.85, 0.95], "Anastasia": ["x", 1.0, 1.03], "Kris": ["x", 0.75, 0.9]},
    "unattended": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.1, 1.3], "Kris": ["x", 0.5, 0.8]},
    "minutes_hour": {"Alex": ["x", 0.9, 1.2], "Anastasia": ["x", 0.6, 0.85], "Kris": ["x", 1.3, 1.8]},
    "rejected": {"Alex": ["x", 1.5, 2.5], "Anastasia": ["x", 0.4, 0.8], "Kris": ["x", 0.8, 1.2]},
    "refusals": {"Alex": ["x", 1.2, 1.8], "Anastasia": ["x", 0.6, 0.9], "Kris": ["x", 0.9, 1.4]},
    "compactions": {"Alex": ["x", 1.5, 2.5], "Anastasia": ["x", 0.6, 1.0], "Kris": ["x", 0.3, 0.7]},
    "thinking": {"Alex": ["x", 0.8, 1.0], "Anastasia": ["x", 1.0, 1.2], "Kris": ["x", 0.9, 1.1]},
    "kloc": {"Alex": ["x", 0.7, 1.0], "Anastasia": ["x", 0.6, 0.9], "Kris": ["x", 1.5, 2.5]},
    "mix_feat": {"Alex": ["x", 1.3, 1.6], "Anastasia": ["x", 1.2, 1.5], "Kris": ["abs", 0, 0.03]},
    "mix_fix": {"Alex": ["x", 0.6, 0.9], "Anastasia": ["x", 0.6, 0.9], "Kris": ["abs", 0.8, 0.9]},
    "mix_refactor": {"Alex": ["x", 0.8, 1.5], "Anastasia": ["x", 1.5, 2.5], "Kris": ["abs", 0.02, 0.06]},
    "mix_other": {"Alex": ["x", 0.8, 1.2], "Anastasia": ["x", 0.8, 1.2], "Kris": ["abs", 0.05, 0.1]},
}


def team_mode(repo):
    """`metricsTeam` for this machine: its own .sclaude/local/config.json
    first — outside git, so turning the demo on for one laptop does not turn
    it on for the team — then the product's committed config."""
    for path in (os.path.join(repo, ".sclaude", "local", "config.json"),
                 os.path.join(repo, ".sclaude", "config.json")):
        found = dora_store.load(path, {})
        if isinstance(found, dict) and found.get("metricsTeam"):
            return found["metricsTeam"]
    return "real"


def team_section(x, cur, dv, sw, hm, ai, first_time, hist):
    """Developers side by side, for `metricsTeam: demo`: the real developer's
    figures are the product's — on one developer's product they are the same
    thing — and the generated teammates are drawn from them in the browser
    (TEAM_JS) by PROFILES, the draw kept per browser."""
    authors = sorted((hist.get("authors") or {}).items(), key=lambda kv: -kv[1]["commits"])
    me = authors[0][0] if authors else "You"
    types = dict(sw["types"])
    changes = sum(types.values()) or 1
    uses = dict(ai["uses"])
    spend_by_model = x["models"] or {}
    top_model = dora_numbers.ratio(sum(v for k, v in spend_by_model.items() if "opus" in k.lower()),
                      sum(spend_by_model.values()))

    def kind(*names):
        return sum(types.get(n, 0) for n in names) / changes
    rows = [
        ("features", "Features finished", "Output", "int", x["done"], None),
        ("prs", "Pull requests merged", "Output", "int", x["merged"], None),
        ("commits", "Commits", "Output", "int", hist.get("commits"), None),
        ("lines", "Lines changed", "Output", "int", (hist.get("added") or 0) + (hist.get("removed") or 0), None),
        ("bugs", "Bugs fixed", "Output", "int", types.get("fix", 0), None),
        ("cycle", "Feature cycle time", "Speed", "span", x["cycle"], None),
        ("lead", "Lead time for changes", "Speed", "span", cur["lead"], None),
        ("aging", "PR aging", "Speed", "span", dv["aging"], None),
        ("pr_size", "Pull request size", "Speed", "int", x["pr_size"], None),
        ("green", "Regression green first time", "Quality", "share", first_time, 1.0),
        ("rounds", "Review rounds per feature", "Quality", "dec1", x["rounds_per_feature"], None),
        ("threads", "Review threads per feature", "Quality", "int", x["threads_per_feature"], None),
        ("escaped", "Escaped defects", "Quality", "share", sw["escaped"], 1.0),
        ("reopened", "Reopened issues", "Quality", "share", sw["reopened"], 1.0),
        ("ai_commits", "Commits written by Claude", "AI adoption", "share",
         dora_numbers.ratio(hist.get("by_claude"), hist.get("commits")), 1.0),
        ("sessions", "Sessions, last 30 days", "AI adoption", "int", x["sessions_recent"], None),
        ("sessions_week", "Sessions per week", "AI adoption", "dec1", ai["sessions_per_week"], None),
        ("tokens_week", "Tokens per week", "AI adoption", "int", ai["tokens_per_week"], None),
        ("person_hours", "Person's hours with Claude", "AI adoption", "dec1", hm["person_s"] / 3600, None),
        ("subagents", "Subagent use", "AI adoption", "share", uses.get("Subagents"), 1.0),
        ("skills", "Skill use", "AI adoption", "share", uses.get("Skills"), 1.0),
        ("plan", "Plan mode use", "AI adoption", "share", uses.get("Plan mode"), 1.0),
        ("mcp", "MCP tool use", "AI adoption", "share", uses.get("MCP tools"), 1.0),
        ("top_model", "Top-model share of spend", "AI adoption", "share", top_model, 1.0),
        ("cache", "Cache hit rate", "AI effectiveness", "share", x["cache_hit"], 0.995),
        ("run", "Claude's run between interventions", "AI effectiveness", "dec1", hm["run_calls"], None),
        ("unattended", "Sessions with no one stepping in", "AI effectiveness", "share", hm["unattended"], 0.98),
        ("person_share", "Person's share of the time", "AI effectiveness", "share", hm["person_share"], 0.95),
        ("minutes_hour", "Person's minutes per hour of Claude", "AI effectiveness", "dec1",
         hm["minutes_per_hour"], None),
        ("interventions", "Interventions per feature", "AI effectiveness", "dec1", hm["turns_per_feature"], None),
        ("questions", "Questions per feature", "AI effectiveness", "dec1", ai["questions_per_feature"], None),
        ("rejected", "Actions turned down per 100 calls", "AI effectiveness", "dec2",
         dora_numbers.ratio(100 * x["denials"].get("user-rejected", 0), x["tool_calls"]), None),
        ("refusals", "Refusals per 100 calls", "AI effectiveness", "dec2",
         dora_numbers.ratio(100 * sum(x["denials"].values()), x["tool_calls"]), None),
        ("compactions", "Compactions per 100 sessions", "AI effectiveness", "dec1",
         dora_numbers.ratio(100 * x["compactions"], x["sessions"]), None),
        ("thinking", "Thinking", "AI effectiveness", "share", x["thinking_share"], 1.0),
        ("spend", "Spend, last 30 days", "Cost", "money", x["cost_recent"], None),
        ("spend_feature", "Spend per feature", "Cost", "money", x["per_feature"], None),
        ("kloc", "Per 1,000 lines changed", "Cost", "money", x["per_kloc"], None),
    ]
    metrics = [{"key": k, "label": label, "group": group, "fmt": f, "value": v, "cap": cap,
                "band": metrics_guide.spec(label), "profiles": PROFILES.get(k, {})}
               for k, label, group, f, v, cap in rows]
    for key, label, share_ in (("mix_feat", "Features", kind("feat", "perf")),
                               ("mix_fix", "Fixes", kind("fix", "hotfix", "revert")),
                               ("mix_refactor", "Refactoring", kind("refactor")),
                               ("mix_other", "Everything else", 1 - kind("feat", "perf", "fix", "hotfix",
                                                                        "revert", "refactor"))):
        metrics.append({"key": key, "label": label, "group": "Mix", "fmt": "share", "value": share_,
                        "cap": None, "band": None, "profiles": PROFILES[key], "mix": True})
    for m in metrics:
        m["note"] = metrics_guide.TEAM_GUIDE.get(m["key"])
    data = json.dumps({"me": me, "others": list(SIMULATED), "metrics": metrics,
                       "mergeBand": metrics_guide.spec("Merge frequency"),
                       "notes": metrics_guide.TEAM_GUIDE, "sources": metrics_guide.TEAM_SOURCES,
                       "tips": metrics_guide.TEAM_TIPS}).replace("</", "<\\/")
    return dora_page.section(
        "team", "Team", "Developers side by side, over the last %d days." % dora_numbers.WINDOW,
        "<div id=team></div><script type=application/json id=team-data>%s</script>" % data)
