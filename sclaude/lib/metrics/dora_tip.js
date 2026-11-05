
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
