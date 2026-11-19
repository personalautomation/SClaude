
// --- hover notes that hold ---------------------------------------------------
// A note shown on hover stays while the pointer moves onto it, so its text
// can be selected and copied (the user's word, 2026-11-17): it is placed once
// for what is hovered, not dragged along with the pointer, and hidden a
// moment after the pointer has left both; going over something else on the
// way to it changes it only if the pointer stays there. One note is open at
// a time. holdTip(el) gives a note element show(key, html, ev, hovered),
// leave(), hide(), redraw(), detach() and busy; the review's map uses it too.
const TIPS = [];
function holdTip(tip) {
  const GRACE = 400, SWITCH = 180;
  let key = null, timer = 0, pend = 0, inside = false, drag = false;
  tip.classList.add('hold-tip');
  const hide = () => {
    clearTimeout(timer); clearTimeout(pend);
    tip.hidden = true; key = null; inside = false;
  };
  const leave = () => {
    clearTimeout(pend);
    if (tip.hidden || inside || drag) return;
    clearTimeout(timer); timer = setTimeout(hide, GRACE);
  };
  tip.addEventListener('mouseenter', () => { inside = true; clearTimeout(timer); clearTimeout(pend); });
  tip.addEventListener('mouseleave', () => { inside = false; leave(); });
  // Selecting its text may drag the pointer out: it stays till the button is let go.
  tip.addEventListener('mousedown', () => { drag = true; });
  document.addEventListener('mouseup', () => { if (drag) { drag = false; if (!inside) leave(); } });
  // Placed off what is hovered, so it does not cover where the pointer is
  // heading: below a small thing (a block, a dot, a button) or above it
  // where there is no room; beside the pointer, never under it, on a large
  // one (an icicle) or where neither side has room for the note.
  function place(cx, cy, r) {
    const pad = 10, w = tip.offsetWidth, hh = tip.offsetHeight;
    let x, y;
    const small = r && r.width <= 320 && r.height <= 200;
    const below = small && r.bottom + 6 + hh <= innerHeight - 8, above = small && r.top - hh - 6 >= 4;
    if (below || above) {
      x = Math.min(cx - 12, innerWidth - w - 8);
      y = below ? r.bottom + 6 : r.top - hh - 6;
    } else {
      // Room on neither side, or a large thing: beside the pointer.
      x = cx + pad; y = cy - hh - pad;
      if (x + w > innerWidth - 8) x = cx - w - pad;
      if (y < 8) y = Math.min(cy + pad + 8, innerHeight - hh - 8);
    }
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  }
  function show(k, html, ev, el) {
    if (inside || drag) return;
    clearTimeout(timer);
    if (k === key && !tip.hidden) { clearTimeout(pend); return; }
    // Measured now, and again when it shows if still on the page: a redraw
    // before the switch detaches it, a scroll moves it.
    const cx = ev.clientX, cy = ev.clientY, r = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
    const go = () => {
      const text = typeof html === 'function' ? html() : html;
      if (!text) { hide(); return; }
      TIPS.forEach((t) => { if (t !== api) t.hide(); });
      key = k; tip.innerHTML = text; tip.hidden = false; place(cx, cy, el && el.isConnected ? el.getBoundingClientRect() : r);
    };
    clearTimeout(pend);
    if (tip.hidden) go(); else pend = setTimeout(go, SWITCH);
  }
  // The same note with new text, where it stands (a title changed under it).
  function redraw(k, html) { if (!tip.hidden) { key = k; tip.innerHTML = html; } }
  // Kept open over a redraw that renumbered what it was about: no key, so
  // the next hover always draws afresh.
  function detach() { key = null; }
  const api = {show, leave, hide, redraw, detach, get key() { return tip.hidden ? null : key; },
    get busy() { return !tip.hidden && (inside || drag); }};
  TIPS.push(api);
  return api;
}
const inTip = (el) => !!(el && el.closest && el.closest('.hold-tip'));
// The browser's own tooltips — a title attribute, an SVG <title> — vanish
// as the pointer moves and cannot be selected; they are shown as a note
// that holds. On first hover the text moves into data-tip (a title set or
// redrawn later is taken afresh); tipOf/setTip read and write it for code
// that changes a title while the page is open.
function tipOf(el) {
  const t = el.querySelector(':scope > title');
  return t ? t.textContent : el.getAttribute('title') || el.dataset.tip || '';
}
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
function setTip(el, text) {
  const t = el.querySelector(':scope > title');
  if (t) t.textContent = text; else el.dataset.tip = text;
  // Its note open now: it says the new text at once.
  if (el.tipId && (titleTip.key || '').startsWith(el.tipId)) titleTip.redraw(el.tipId + text, esc(text));
}
function titled(el) {
  for (; el && el.nodeType === 1; el = el.parentNode) {
    if (inTip(el)) return null;
    const t = el.querySelector(':scope > title');
    if (t) { el.dataset.tip = t.textContent; t.remove(); }
    if (el.hasAttribute('title')) {
      el.dataset.tip = el.getAttribute('title');
      // A glyph alone (⌖, ⏸, ✕) names nothing: the title becomes its name.
      if (!el.hasAttribute('aria-label') && el.textContent.trim().length <= 2) el.setAttribute('aria-label', el.dataset.tip);
      el.removeAttribute('title');
    }
    if (el.dataset && el.dataset.tip) return el;
  }
  return null;
}
// A note whose first character repeats a mark of the map — a line, a dot —
// draws that character in the mark's own colour, so that it is plainly the
// one hovered: data-tip-mark names which paint, `stroke` or `fill`, of the
// element itself or of its first line, circle or text — or is the colour.
function tipHtml(el) {
  const text = el.dataset.tip, paint = el.dataset.tipMark;
  if (!paint) return esc(text);
  const src = el.matches('line,circle,rect,path,text') ? el : el.querySelector('line,circle,rect,path,text');
  const colour = paint !== 'fill' && paint !== 'stroke' ? paint : src ? getComputedStyle(src)[paint] : '';
  const first = [...text][0] || '';
  if (!colour || colour === 'none') return esc(text);
  return '<b style="color:' + esc(colour) + '">' + esc(first) + '</b>' + esc(text.slice(first.length));
}
const titleEl = Object.assign(document.createElement('div'), {id: 'tip-t', hidden: true});
document.body.append(titleEl);
const titleTip = holdTip(titleEl);
document.addEventListener('mouseover', (ev) => {
  if (inTip(ev.target)) return;
  const el = titled(ev.target);
  if (!el) { titleTip.leave(); return; }
  if (!el.tipId) el.tipId = 't' + Math.random();
  titleTip.show(el.tipId + el.dataset.tip, tipHtml(el), ev, el);
});

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
const mapTip = holdTip(tip);
document.addEventListener('mouseover', (ev) => {
  if (inTip(ev.target)) return;
  const el = ev.target.closest('[data-key]');
  const k = el && scope(el) ? el.dataset.key : null;
  if (k !== hover) { hover = k; paint(); }
  // A badge's own note, inside a block, is the one shown there.
  const own = k && titled(ev.target);
  if (k && !(own && el.contains(own))) mapTip.show(k, () => tipFor(k), ev, el);
  else mapTip.leave();
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
// What is selected, and a selection to restore (process_url.js): only keys
// the page draws.
function selected() { return [...sel]; }
function select(keys) {
  sel.clear();
  keys.forEach((k) => { if (document.querySelector('[data-key="' + CSS.escape(k) + '"]')) sel.add(k); });
  paint();
}
window.processMap = {paint: paint, model: M, selected: selected, select: select};
