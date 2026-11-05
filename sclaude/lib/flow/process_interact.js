
const M = /*MODEL*/;
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
