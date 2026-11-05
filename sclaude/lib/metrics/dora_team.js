(function(){
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
card.appendChild(el('p','sub','Each bar is against the longest in its row; the mark is the figure\'s own bands, as everywhere on the page.'));
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
share.appendChild(el('p','sub','each developer\'s share of the team\'s output, last 30 days'));
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
