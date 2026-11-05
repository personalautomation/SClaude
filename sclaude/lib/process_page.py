# A feature's own page: the map with where the feature stands, played back
# along its history, and kept live.
#
# Part of sclaude/lib/process.py, which re-exports it.

import json

import process_config, process_diagram, process_doc, process_model


# --- a feature's page --------------------------------------------------------

LIVE_SCRIPT = r"""
const label = %(label)s;
const POS = %(positions)s;
let last = '';
function render(v) {
  document.getElementById('where').textContent = v.where || '—';
  document.getElementById('why').textContent = v.why || '';
  document.getElementById('stamp').textContent = 'updated ' + new Date().toLocaleTimeString();
  const here = v.node || '';
  document.querySelectorAll('.node.here').forEach((n) => n.classList.remove('here'));
  // F and W at work now: their rings turn.
  document.querySelectorAll('.badge.busy, .badge.stalled').forEach((b) => {
    b.classList.remove('busy', 'stalled');
    b.querySelector('title').textContent = b.dataset.why;
  });
  // The glance's blocks carry their step's letters (ALIAS):
  // they turn with it.
  Object.entries(v.busy || {}).forEach(([id, flags]) => flags.forEach((f) =>
    [id].concat(M.alias[id] || []).forEach((at) =>
    document.querySelectorAll('svg.map [data-node="' + at + '"] .b-' + f).forEach((b) => {
      b.classList.add('busy');
      // On hover, how it goes now, under why it is there.
      const note = ((v.notes || {})[id] || {})[f];
      b.querySelector('title').textContent = b.dataset.why + (note ? '\n' + note : '');
    }))));
  // A sync with main has no block on the glance: its S stands
  // on the block it runs ahead of, which is lit for it, the S turning — or,
  // broken off, standing still in the colour of a wait on the person.
  const syncAt = [];
  Object.entries(v.busy || {}).forEach(([id, flags]) => { if (flags.includes('S')) syncAt.push(id); });
  Object.entries(v.stalled || {}).forEach(([id, notes]) => {
    syncAt.push(id);
    [id].concat(M.alias[id] || [], POS[id] || []).forEach((at) =>
      document.querySelectorAll('svg.map [data-node="' + at + '"] .b-S').forEach((b) => {
        b.classList.add('stalled');
        b.querySelector('title').textContent = b.dataset.why + '\n' + notes.S;
      }));
  });
  (v.busy ? syncAt : []).forEach((id) => (POS[id] || []).forEach((at) =>
    document.querySelectorAll('svg.map [data-node="' + at + '"] .b-S').forEach((b) => {
      if (!b.classList.contains('stalled')) b.classList.add('busy');
    })));
  if (here) {
    [here].concat(POS[here] || (here === 'sync' ? syncAt.flatMap((id) => POS[id] || []) : [])).forEach((id) =>
      document.querySelectorAll('svg.map [data-node="' + id + '"]').forEach((n) => n.classList.add('here')));
  }
  if (here && here !== last) {
    // On the whole process, or on the map of its own a place has (R, S).
    const n = document.querySelector('svg.map-detail [data-node="' + here + '"]')
      || document.querySelector('svg.map [data-node="' + here + '"]');
    // Down to it only: centred across as well, the card scrolled the map's
    // first lanes off its left edge with no way to tell they were there.
    if (n && last === '') n.scrollIntoView({block: 'center', inline: 'nearest'});
    last = here;
  }
  const ul = document.getElementById('acts');
  ul.textContent = '';
  (v.actions || []).forEach((a) => {
    const li = document.createElement('li');
    const i = M.cmds.findIndex((c) => c.v === a.verb);
    if (i >= 0) li.dataset.key = 'c:' + i;
    const head = document.createElement('div');
    head.className = 'an';
    head.textContent = a.label;
    li.append(head);
    if (a.hint) { const h = document.createElement('div'); h.className = 'ah2'; h.textContent = a.hint; li.append(h); }
    if (i >= 0) {
      const c = document.createElement('code');
      c.textContent = M.cmds[i].c.replace('<name>', v.feature || label).replace('[name]', v.feature || label);
      li.append(c);
      const to = M.cmds[i].to.map((x) => x === '@here' ? here : x).filter(Boolean);
      if (to.length) {
        const g = document.createElement('div');
        g.className = 'leads';
        g.textContent = '→ ' + to.map((x) => (M.nodes[x] || {}).t || x).join(', ');
        li.append(g);
      }
    }
    ul.append(li);
  });
  window.processMap.paint();
  player.update(v.history);
  document.getElementById('err').textContent = v.error || '';
}
function poll() {
  fetch('/__sclaude/flow/state?f=' + encodeURIComponent(label), {cache: 'no-store'})
    .then((r) => r.ok ? r.json() : Promise.reject(r.status))
    .then(render)
    .catch((e) => { document.getElementById('err').textContent = 'sclaude did not answer (' + e + ')'; })
    .finally(() => setTimeout(poll, document.hidden ? 60000 : 15000));
}
poll();
"""

# How the feature went, played on its maps (`history` above). ▶ by a map's
# heading plays the whole way on that map: a place lights with a clock
# counting the time it stood there, then the arrow it left by; a friction
# review or a workshop pass jumps to its own map and back. By the friction
# review's and the workshop's headings ▶ plays the pass chosen beside it.
# A place entered again keeps its count: "×2 · 3 h 10 min".
PLAY_SCRIPT = r"""
const player = (() => {
  let data = null, token = 0, paused = false, speed = 1;
  const bar = document.getElementById('player');
  const say = (t) => { bar.querySelector('.pl-text').textContent = t; };
  function dur(s) {
    if (s == null) return '';
    if (s < 60) return Math.round(s) + ' s';
    const m = Math.round(s / 60);
    if (m < 60) return m + ' min';
    const h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d) return d + ' d ' + (h % 24) + ' h';
    return h + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
  }
  function when(t) {
    if (!t) return '';
    const d = new Date(t);
    return d.toLocaleDateString(undefined, {day: 'numeric', month: 'short'}) + ' '
      + d.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'});
  }
  // A wait that stands still while paused and follows a change of speed.
  function sleep(ms, mine) {
    return new Promise((done) => {
      let left = ms, last = performance.now();
      const tick = () => {
        if (mine !== token) return done(false);
        const now = performance.now();
        if (!paused) left -= (now - last) * speed;
        last = now;
        if (left <= 0) return done(true);
        setTimeout(tick, 40);
      };
      setTimeout(tick, 40);
    });
  }
  function clear() {
    document.querySelectorAll('.pl-clock,.pl-tag,.pl-ghost').forEach((g) => g.remove());
    document.querySelectorAll('.pl-wrong').forEach((g) => g.classList.remove('pl-wrong'));
    document.getElementById('pl-off').hidden = true;
    document.querySelectorAll('.pl-now,.pl-seen,.pl-go,.pl-went').forEach((el) => {
      el.classList.remove('pl-now', 'pl-seen', 'pl-go', 'pl-went');
      delete el.__pl;
    });
    document.body.classList.remove('playing');
    played = null; current = null;
    drawMetrics();
  }
  function stop() {
    token++; paused = false; clear(); bar.hidden = true; playing = null;
    bar.querySelector('.pl-pause').textContent = '⏸';
    document.body.classList.remove('pl-paused');
    document.querySelectorAll('#hist li.on').forEach((li) => li.classList.remove('on'));
    document.querySelectorAll('.play').forEach((b) => { b.textContent = '▶'; b.classList.remove('on'); });
  }
  // What the person put in and Claude cost, by kind: {input, cost, wait}.
  function addUp(into, m) {
    Object.entries(m || {}).forEach(([k, v]) => { into[k] = (into[k] || 0) + v; });
    return into;
  }
  // While a play runs, the metrics under a block are what was played so far:
  // the stays done there (`played`, by map:node), and on the one playing now
  // its own share after a plus (`current`). A map the play does not go on
  // (`inPlay`) keeps its totals, and so does every map once it has played.
  let played = null, current = null, inPlay = new Set();
  // The detailed map's places as the overview draws them; one place
  // standing for several in a row is entered once, their times summed.
  function onMap(steps, map) {
    const out = [];
    steps.forEach((s) => {
      if (s.pass) { out.push(s); return; }
      const n = M.proj[s.n];
      if (!n) return;
      const last = out[out.length - 1];
      if (last && !last.pass && last.n === n) {
        last.off = last.off || s.off;
        if (s.s != null) last.s = (last.s || 0) + s.s;
        if (s.m) last.m = addUp(Object.assign({}, last.m), s.m);
        last.to = s.to || last.to; last.here = last.here || s.here; last.unsure = last.unsure || s.unsure;
        return;
      }
      out.push(Object.assign({}, s, {n: n}));
    });
    return out;
  }
  function edgeKey(map, a, b) {
    return Object.keys(M.edges).find((k) => k.startsWith(map + ':') && M.edges[k].f === a && M.edges[k].t === b);
  }
  function svgEl(map, sel) {
    const svg = document.querySelector('svg.map-' + map);
    return svg ? svg.querySelector(sel) : null;
  }
  // `lead` ({k, t}): the times the place was entered with this one, and
  // what the stays played before took, said ahead of the running time
  // ("×3 · 40 min+5 min"), where the ⏱ of the metrics would stand and does
  // not while the clock is there.
  function clock(g, s, ms, mine, lead) {
    const box = g.querySelector('.shape').getBBox(), ns = 'http://www.w3.org/2000/svg';
    const c = document.createElementNS(ns, 'g');
    c.setAttribute('class', 'pl-clock');
    c.setAttribute('transform', 'translate(' + (box.x + 2) + ' ' + (box.y + 2) + ')');
    c.innerHTML = '<circle r="12"/><line class="pl-hand" x1="0" y1="0" x2="0" y2="-8"/>'
      + '<line x1="0" y1="0" x2="5" y2="0"/><text x="17" y="4"></text>';
    g.append(c);
    const text = c.querySelector('text'), hand = c.querySelector('.pl-hand');
    const say = (t) => [lead && lead.k > 1 ? '×' + lead.k : '',
      (lead && lead.t ? dur(lead.t) + (s != null ? '+' : '') : '') + (s != null ? dur(t) : '')]
      .filter(Boolean).join(' · ') + (lead && lead.guess ? ' ⚠' : '');
    // Its words stop before the badges, measured once at their longest: a
    // layout every frame would stutter on a phone. The running time is
    // longest just under a round one ("1 h 59 min" before "2 h"), so the
    // longest of the words it will say on the way is the one measured.
    const room = upToBadges(g, box.x + 2 + 17), all = s || 0;
    let longest = say(all);
    for (let t = 0; t < all; t += Math.max(60, all / 2000)) {
      const w = say(t);
      if (w.length > longest.length) longest = w;
    }
    text.textContent = longest;
    const wide = text.getComputedTextLength();
    if (wide > room) text.style.fontSize = Math.max(7, 12 * room / wide) + 'px';
    let gone = 0, last = performance.now();
    (function frame(t) {
      if (mine !== token || !c.isConnected) return;
      if (!paused) gone += (t - last) * speed;
      last = t;
      const f = Math.min(1, gone / ms);
      hand.setAttribute('transform', 'rotate(' + (f * 720) + ')');
      text.textContent = say(s * f);
      if (f < 1) requestAnimationFrame(frame);
    })(last);
    return c;
  }
  // Times entered and time taken so far, inside the block at its top left;
  // the ⏱ of the metrics says both when it is checked.
  function tag(g, n, s) {
    const seen = g.__pl || (g.__pl = {k: 0, s: 0});
    seen.k++; seen.s += s || 0;
    g.querySelectorAll('.pl-tag').forEach((t) => t.remove());
    if (timeShown() || (!seen.s && seen.k < 2)) return;
    const box = g.querySelector('.shape').getBBox(), ns = 'http://www.w3.org/2000/svg';
    const t = document.createElementNS(ns, 'text');
    t.setAttribute('class', 'pl-tag');
    t.setAttribute('x', box.x + inset(g, true)); t.setAttribute('y', box.y + 12);
    t.textContent = [seen.k > 1 ? '×' + seen.k : '', seen.s ? dur(seen.s) : ''].filter(Boolean).join(' · ');
    g.append(t);
  }
  const timeShown = () => !!document.querySelector('.metrics input[value="time"]:checked');
  // How far from a block's side its corners' words start: a gate's corners
  // are cut, and a wait has its clock at the top left.
  const kindOf = (g) => (g.getAttribute('class').match(/k-(\S+)/) || [])[1];
  const inset = (g, top) => kindOf(g) === 'gate' ? 17 : top && kindOf(g) === 'wait' ? 24 : 7;
  // The room from x along a block's top to the first of its badges.
  const upToBadges = (g, x) => {
    const box = g.querySelector('.shape').getBBox();
    return Math.min(box.x + box.width - 7,
                    ...[...g.querySelectorAll('.badge .dot')].map((d) => +d.getAttribute('cx') - 14)) - x;
  };
  const TITLE = {friction: 'the friction review', workshop: 'how a session changes sclaude',
                 regression: "a stage's regression", sync: 'main and the branch'};
  // The maps a pass is played on, each a way of its own from the main one.
  const PASSES = Object.keys(TITLE);
  // What is being played, kept for the history list: a click there plays
  // from that place on.
  let playing = null;
  function arrow(prev, s) {
    if (!prev || prev.map !== s.map) return null;
    const k = edgeKey(s.map, prev.n, s.n);
    return k ? M.edges[k] : null;
  }
  // The places already passed, lit at once: a jump in the list lands with
  // what came before it as the play would have left it.
  function mark(steps, upto) {
    for (let i = 0; i < upto; i++) {
      const s = steps[i], g = svgEl(s.map, '[data-node="' + s.n + '"]');
      if (!g) continue;
      const k = i && steps[i - 1].map === s.map ? edgeKey(s.map, steps[i - 1].n, s.n) : null;
      const e = k && svgEl(s.map, '[data-key="e:' + k + '"]');
      if (e) e.classList.add('pl-went');
      g.classList.add('pl-seen');
      tag(g, s.n, s.s);
      done(s);
    }
    drawMetrics();
  }
  function done(s) {
    const key = s.map + ':' + s.n;
    played[key] = addUp(played[key] || {}, Object.assign({visits: 1, unsure: s.unsure ? 1 : 0}, s.m));
  }
  async function run(steps, label, start) {
    stop();
    start = start || 0;
    const mine = ++token;
    playing = {steps: steps, label: label};
    played = {}; inPlay = new Set(steps.map((s) => s.map));
    document.body.classList.add('playing');
    bar.hidden = false;
    showTab('history');
    list(steps, label);
    mark(steps, start);
    let prev = start ? steps[start - 1] : null;
    for (let i = start; i < steps.length; i++) {
      const s = steps[i];
      pick(i);
      if (s.map !== (prev && prev.map) && prev) {
        say(label + ' · ' + (PASSES.includes(s.map)
          ? '↪ off to ' + TITLE[s.map] + (s.pass ? ': ' + s.pass : '') : '↩ back to the cycle'));
        if (!await sleep(1100, mine)) return;
      }
      const g = svgEl(s.map, '[data-node="' + s.n + '"]');
      if (s.off) deviate(prev, s, g);
      if (!g) { prev = s; continue; }
      g.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'smooth'});
      if (prev && prev.map === s.map) {
        const k = edgeKey(s.map, prev.n, s.n);
        const e = k && svgEl(s.map, '[data-key="e:' + k + '"]');
        if (e) {
          e.classList.add('pl-go');
          if (!await sleep(650, mine)) return;
          e.classList.remove('pl-go'); e.classList.add('pl-went');
        }
      }
      const n = M.nodes[s.n] || {};
      const ms = s.s != null ? Math.min(4200, 900 + 700 * Math.log10(1 + s.s / 60)) : 420;
      say(label + ' · ' + (i + 1) + '/' + steps.length + ' — ' + (n.t || s.n)
        + (s.s != null ? ' · ' + (s.wait ? 'waited ' : '') + dur(s.s) : '')
        + (s.k > 1 ? ' in ' + s.k + ' sittings' : '')
        + (s.from ? ' · ' + when(s.from) + (s.to && s.to !== s.from ? ' – ' + when(s.to) : '') : '')
        + (s.here ? ' · it is here now' : ''));
      g.classList.add('pl-now');
      current = {key: s.map + ':' + s.n, m: s.m || {}};
      drawMetrics();
      const was = played[current.key] || {};
      const c = clock(g, s.s, ms, mine, timeShown()
        ? {k: s.map === 'overview' ? 1 : (was.visits || 0) + 1, t: was.time, guess: s.unsure || was.unsure}
        : null);
      if (!await sleep(ms, mine)) return;
      c.remove();
      g.classList.remove('pl-now'); g.classList.add('pl-seen');
      tag(g, s.n, s.s);
      done(s); current = null;
      drawMetrics();
      prev = s;
    }
    say(label + ' · played' + (steps.length ? '' : ': nothing recorded yet'));
    played = null;
    drawMetrics();
    pick(-1);
    document.querySelectorAll('.play.on').forEach((b) => { b.textContent = '▶'; b.classList.remove('on'); });
  }
  // The feature went where the map does not go: the play pauses on it, the
  // places are ringed and joined by a ghost of the way it took, and a note
  // says what happened — where the map is wrong, or the code.
  function deviate(prev, s, g) {
    if (g) g.classList.add('pl-wrong');
    const p = g && prev && prev.map === s.map && svgEl(s.map, '[data-node="' + prev.n + '"]');
    if (p) {
      p.classList.add('pl-wrong');
      const a = p.querySelector('.shape').getBBox(), b = g.querySelector('.shape').getBBox();
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      line.setAttribute('class', 'pl-ghost');
      line.setAttribute('d', 'M' + (a.x + a.width / 2) + ' ' + (a.y + a.height / 2)
        + ' L' + (b.x + b.width / 2) + ' ' + (b.y + b.height / 2));
      g.ownerSVGElement.append(line);
    }
    const box = document.getElementById('pl-off');
    box.querySelector('.pl-off-what').textContent = s.off.charAt(0).toUpperCase() + s.off.slice(1) + '.';
    box.querySelector('.pl-off-when').textContent = s.from ? when(s.from) : '';
    box.hidden = false;
    paused = true;
    bar.querySelector('.pl-pause').textContent = '▶';
    document.body.classList.add('pl-paused');
  }
  document.querySelector('#pl-off .pl-off-go').addEventListener('click', () => {
    document.getElementById('pl-off').hidden = true;
    paused = false;
    bar.querySelector('.pl-pause').textContent = '⏸';
    document.body.classList.remove('pl-paused');
  });
  document.querySelector('#pl-off .pl-off-stop').addEventListener('click', () => stop());
  // The history beside the map: every place with when, how long and the
  // arrow it came by; the one playing is lit and kept in view.
  function list(steps, label) {
    const ul = document.getElementById('hist');
    ul.textContent = '';
    document.getElementById('hist-what').textContent = label;
    if (!steps.length) {
      const li = document.createElement('li');
      li.className = 'muted';
      li.textContent = 'Nothing recorded yet: the history starts with the sessions run since sclaude kept one.';
      ul.append(li);
      return;
    }
    const offs = steps.filter((s) => s.off).length;
    if (offs) {
      const li = document.createElement('li');
      li.className = 'h-offs';
      li.textContent = '⚠ ' + offs + (offs === 1 ? ' place' : ' places') + ' where the feature left the map';
      ul.append(li);
    }
    steps.forEach((s, i) => {
      const prev = steps[i - 1], li = document.createElement('li'), n = M.nodes[s.n] || {};
      li.dataset.i = i;
      if (s.off) {
        li.classList.add('h-wrong');
        li.title = s.off;
      }
      if (prev && prev.map !== s.map) {
        const off = document.createElement('div');
        off.className = 'h-off';
        off.textContent = PASSES.includes(s.map)
          ? '↪ ' + TITLE[s.map] + (s.pass ? ': ' + s.pass : '') : '↩ back to the cycle';
        li.append(off);
      }
      const e = arrow(prev, s);
      if (e && e.l) {
        const via = document.createElement('div');
        via.className = 'h-via' + (e.k === 'back' ? ' back' : '');
        via.textContent = '→ ' + e.l;
        li.append(via);
      }
      const head = document.createElement('div');
      head.className = 'h-t';
      head.textContent = n.t || s.n;
      li.append(head);
      const bits = [];
      if (s.from) bits.push(when(s.from) + (s.to && s.to !== s.from ? ' – ' + when(s.to) : ''));
      if (s.s != null) bits.push((s.wait ? 'waited ' : '') + dur(s.s));
      if (s.k > 1) bits.push(s.k + ' sittings');
      if (s.here) bits.push('here now');
      if (bits.length) {
        const m = document.createElement('div');
        m.className = 'h-m';
        m.textContent = bits.join(' · ');
        li.append(m);
      } else li.classList.add('h-pass');
      li.addEventListener('click', () => {
        const b = document.querySelector('.play.on');
        run(steps, label, i);
        if (b) { b.textContent = '■'; b.classList.add('on'); }
      });
      ul.append(li);
    });
  }
  function pick(i) {
    const panel = document.querySelector('.panel');
    document.querySelectorAll('#hist li.on').forEach((li) => li.classList.remove('on'));
    const li = document.querySelector('#hist li[data-i="' + i + '"]');
    if (!li) return;
    li.classList.add('on');
    panel.scrollTo({top: li.offsetTop - panel.clientHeight / 2 + li.offsetHeight / 2, behavior: 'smooth'});
  }
  function expand(map) {
    const h = data || {visits: [], passes: {}};
    if (PASSES.includes(map)) {
      const sel = document.querySelector('select.pass[data-pass="' + map + '"]');
      const p = (h.passes[map] || [])[+(sel && sel.value)];
      return p ? p.steps.map((s) => Object.assign({map: map}, s)) : [];
    }
    const out = [];
    (map === 'detail' ? h.visits : onMap(h.visits, map)).forEach((s) => {
      if (!s.pass) { out.push(Object.assign({map: map}, s)); return; }
      const p = (h.passes[s.pass[0]] || [])[s.pass[1]];
      if (p) p.steps.forEach((x, j) => out.push(Object.assign({map: s.pass[0], pass: p.label},
        x, j || !s.off ? {} : {off: s.off})));
    });
    return out;
  }
  document.querySelectorAll('.play').forEach((b) => b.addEventListener('click', () => {
    if (b.classList.contains('on')) { stop(); return; }
    run(expand(b.dataset.play), b.dataset.label);
    b.textContent = '■'; b.classList.add('on');
  }));
  bar.querySelector('.pl-pause').addEventListener('click', (ev) => {
    paused = !paused; ev.target.textContent = paused ? '▶' : '⏸';
    document.body.classList.toggle('pl-paused', paused);
  });
  bar.querySelector('.pl-speed').addEventListener('change', (ev) => { speed = +ev.target.value; });
  bar.querySelector('.pl-stop').addEventListener('click', stop);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !bar.hidden) stop(); });
  function update(h) {
    if (!h) return;
    data = h;
    PASSES.forEach((map) => {
      const sel = document.querySelector('select.pass[data-pass="' + map + '"]');
      if (!sel) return;
      const list = h.passes[map] || [], was = sel.value;
      const sig = JSON.stringify(list.map((p) => p.label));
      if (sel.dataset.sig === sig) return;
      sel.dataset.sig = sig;
      sel.textContent = '';
      list.forEach((p, i) => { const o = document.createElement('option'); o.value = i; o.textContent = p.label; sel.append(o); });
      if (!list.length) { const o = document.createElement('option'); o.textContent = 'no pass yet'; sel.append(o); }
      sel.disabled = !list.length;
      if (was && +was < list.length) sel.value = was;
      else if (list.length) sel.value = list.length - 1;
      document.querySelector('.play[data-play="' + map + '"]').disabled = !list.length;
    });
    document.querySelectorAll('.play').forEach((b) => {
      if (!PASSES.includes(b.dataset.play)) b.disabled = false;
    });
    if (bar.hidden) list(expand('detail'), 'The whole process');
  }
  // The panel's two faces: what can be done now, and how it went.
  function showTab(name) {
    document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
    document.querySelectorAll('.tab').forEach((t) => { t.hidden = t.id !== 'tab-' + name; });
  }
  document.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));
  // What each place took, under its block, by the checkboxes above the maps.
  const took = (s) => s < 3600 ? Math.max(1, Math.round(s / 60)) + ' min'
    : s < 86400 ? Math.floor(s / 3600) + ' h' + (Math.round(s % 3600 / 60) ? ' ' + Math.round(s % 3600 / 60) + ' min' : '')
    : Math.floor(s / 86400) + ' d ' + Math.round(s % 86400 / 3600) + ' h';
  // With `more`, what a stay playing now adds to the count before it.
  const plus = (put, n, more) => more == null ? put(n) : (n ? put(n) : '') + '+' + put(more);
  const money = (n) => '$' + (n < 10 ? n.toFixed(2) : Math.round(n));
  const SHOW = {input: (n, more) => '✋ ' + plus(String, n, more),
                cost: (n, more) => plus(money, n, more),
                wait: (n, more) => '⏳ ' + plus(took, n, more),
                expired: (n, more) => '♻ ' + plus(String, n, more),
                time: (n, more) => '⏱ ' + plus(took, n, more)};
  // A kind's whole, as the line above the maps and a map's heading say it.
  const whole = (kind, sum) => kind === 'cost' ? '$' + sum.toFixed(2)
    : kind === 'wait' || kind === 'time' ? (sum ? took(sum) : '0') : String(sum);
  const ICON = {input: '✋', cost: '', wait: '⏳', expired: '♻', time: '⏱'};
  function totals(kind, map) {
    const m = ((data || {}).metrics || {})[kind] || {};
    if (map !== 'overview') return m[map] || {};
    const out = {};
    // The whole process and the regressions' map project onto it; a sync,
    // which it does not draw, counts under the block it ran ahead of.
    ['detail', 'regression', 'ahead'].forEach((from) => Object.entries(m[from] || {}).forEach(([n, v]) => {
      const to = M.proj[n];
      if (to) out[to] = (out[to] || 0) + v;
    }));
    return out;
  }
  function drawMetrics() {
    // The whole feature beside each checkbox: every map the metrics name,
    // which share no place (the overview, drawn from the detailed map here,
    // is not among them).
    document.querySelectorAll('.mt-total').forEach((b) => {
      const m = ((data || {}).metrics || {})[b.dataset.kind] || {};
      // "ahead" repeats the sync's under the glance's blocks: not twice.
      const sum = Object.keys(m).filter((map) => map !== 'ahead').reduce((t, map) =>
        t + Object.values(m[map] || {}).reduce((a, v) => a + v, 0), 0);
      const guess = b.dataset.kind === 'time' && Object.keys(((data || {}).metrics || {}).unsure || {}).length;
      b.textContent = '· ' + whole(b.dataset.kind, sum) + (guess ? ' ⚠' : '');
    });
    document.querySelectorAll('.mt').forEach((t) => t.remove());
    // A block's own words as drawn, before the metrics made room in it.
    document.querySelectorAll('.mt-hid').forEach((t) => t.classList.remove('mt-hid'));
    document.querySelectorAll('[data-mt-was]').forEach((t) => {
      t.textContent = t.dataset.mtWas; delete t.dataset.mtWas;
    });
    document.querySelectorAll('[data-mt-moved]').forEach((t) => {
      t.removeAttribute('transform'); delete t.dataset.mtMoved;
    });
    const on = [...document.querySelectorAll('.metrics input:checked')].map((c) => c.value);
    // Each map's own whole beside its heading, by the same checkboxes: a
    // map nothing was counted on says its zeros rather than nothing.
    document.querySelectorAll('.mt-map').forEach((b) => {
      b.textContent = on.map((kind) => {
        const sum = Object.values(totals(kind, b.dataset.map)).reduce((a, v) => a + v, 0);
        const guess = kind === 'time' && Object.keys(totals('unsure', b.dataset.map)).length;
        return (ICON[kind] ? ICON[kind] + ' ' : '') + whole(kind, sum) + (guess ? ' ⚠' : '');
      }).join('  ');
    });
    ['detail', 'overview'].concat(PASSES).forEach((map) => {
      // per[node][kind]: the words one kind puts in it.
      const per = {};
      const put = (n, kind, word) => { (per[n] = per[n] || {})[kind] = word; };
      // ⏱ with the times the place was entered, where a place is one block:
      // the glance draws several in one, entered as one.
      // ⚠ after it: a stay there ended unseen, and its time is a guess.
      const timed = (k, a, b, guess) => {
        const said = [k > 1 && map !== 'overview' ? '×' + k : '',
                      a || b ? plus(took, a, b || null).replace(/^\+/, '') : ''].filter(Boolean).join(' · ');
        return said ? '⏱ ' + said + (guess ? ' ⚠' : '') : '';
      };
      if (played && inPlay.has(map)) {
        // ✋3+2: three before this stay, two in it; a stay done shows 5.
        const keys = new Set(Object.keys(played).concat(current ? [current.key] : []));
        keys.forEach((key) => {
          if (!key.startsWith(map + ':')) return;
          const n = key.slice(map.length + 1), was = played[key] || {};
          const now = current && current.key === key ? current.m : null;
          on.forEach((kind) => {
            const a = was[kind] || 0, b = now ? now[kind] || 0 : 0;
            // The block playing now has the clock in that corner, saying it.
            if (kind === 'time') {
              const k = (was.visits || 0) + (now ? 1 : 0);
              if (!now && timed(k, a)) put(n, kind, timed(k, a, 0, was.unsure));
            } else if (b) put(n, kind, SHOW[kind](a, b));
            else if (a) put(n, kind, SHOW[kind](a));
          });
        });
      } else {
        // The stay the feature is on now, when the place had stays before
        // it: what those took, then its own after a plus, as a play says it.
        // Not on the glance, whose one stay may be several in a row here.
        const here = {};
        const mark = (m, st) => { if (st.live && st.m) here[m + ':' + st.n] = st.m; };
        ((data || {}).visits || []).forEach((st) => mark('detail', st));
        PASSES.forEach((m) => (((data || {}).passes || {})[m] || []).forEach((p) => p.steps.forEach((st) => mark(m, st))));
        const visits = totals('visits', map), guessed = totals('unsure', map);
        on.forEach((kind) => Object.entries(totals(kind, map)).concat(
          kind === 'time' ? Object.keys(visits).map((n) => [n, totals('time', map)[n] || 0]) : []
        ).forEach(([n, v]) => {
          const b = (here[map + ':' + n] || {})[kind] || 0, a = v - b;
          const first = !(a > 1e-9 && b);
          if (kind === 'time') {
            const word = first ? timed(visits[n], v, 0, guessed[n]) : timed(visits[n], a, b, guessed[n]);
            if (word) put(n, kind, word);
          } else if (v) put(n, kind, first ? SHOW[kind](v) : SHOW[kind](a, b));
        }));
      }
      const ns = 'http://www.w3.org/2000/svg';
      const text = (g, x, y, anchor, words) => {
        const t = document.createElementNS(ns, 'text');
        t.setAttribute('class', 'mt in');
        t.setAttribute('x', x); t.setAttribute('y', y);
        t.setAttribute('text-anchor', anchor);
        t.textContent = words;
        g.append(t);
        return t;
      };
      const squeeze = (t, room) => {
        if (t && t.getComputedTextLength() > room) {
          t.setAttribute('textLength', Math.max(room, 1));
          t.setAttribute('lengthAdjust', 'spacingAndGlyphs');
        }
      };
      Object.entries(per).forEach(([n, w]) => {
        const g = svgEl(map, '[data-node="' + n + '"]');
        if (!g) return;
        const box = g.querySelector('.shape').getBBox();
        const own = [...g.children].filter((t) => t.matches('text.t, text.s'));
        // A start or an end is a small circle with its words under it: the
        // numbers go in one line under those.
        if (['start', 'end'].includes(kindOf(g))) {
          const low = Math.max(box.y + box.height, ...own.map((t) => { const b = t.getBBox(); return b.y + b.height; }));
          text(g, box.x + box.width / 2, low + 11, 'middle',
               [w.time, w.input, w.wait, w.expired, w.cost].filter(Boolean).join('  '));
          return;
        }
        // Inside the block, in its corners: outside, the ways coming in and
        // going out ran over the numbers. The badges hold the top right.
        const pad = inset(g);
        const top = box.y + 12, bottom = box.y + box.height - 5;
        // Four lines of its own leave no room above and below them: the
        // last line of the description gives way (the one before it ends in
        // "…"), and the rest moves to the middle again.
        const desc = own.filter((t) => t.matches('.s'));
        if (own.length >= 4 && desc.length) {
          const last = desc[desc.length - 1], before = desc[desc.length - 2];
          last.classList.add('mt-hid');
          if (before) {
            before.dataset.mtWas = before.textContent;
            before.textContent = before.textContent.replace(/\s*…$/, '') + ' …';
          }
          own.filter((t) => t !== last).forEach((t) => {
            t.setAttribute('transform', 'translate(0 6)'); t.dataset.mtMoved = '1';
          });
        }
        // What you did, side by side at the bottom left; what Claude cost,
        // the caches it wrote again before it, pressed to the bottom right.
        const said = [w.input, w.wait].filter(Boolean).join('  ');
        const spent = [w.expired, w.cost].filter(Boolean).join('  ');
        const left = said ? text(g, box.x + pad, bottom, 'start', said) : null;
        const right = spent ? text(g, box.x + box.width - pad, bottom, 'end', spent) : null;
        const room = box.width - 2 * pad - (left && right ? 10 : 0);
        const lw = left ? left.getComputedTextLength() : 0, rw = right ? right.getComputedTextLength() : 0;
        if (lw + rw > room) { squeeze(left, room * lw / (lw + rw)); squeeze(right, room * rw / (lw + rw)); }
        // The time the place took at the top left, up to the badges.
        if (w.time) {
          const x = box.x + inset(g, true);
          squeeze(text(g, x, top, 'start', w.time), upToBadges(g, x));
        }
      });
    });
    try { localStorage.setItem('process-metrics', JSON.stringify(on)); } catch (e) {}
  }
  try {
    const kept = JSON.parse(localStorage.getItem('process-metrics') || '[]');
    document.querySelectorAll('.metrics input').forEach((c) => { c.checked = kept.includes(c.value); });
  } catch (e) {}
  document.querySelectorAll('.metrics input').forEach((c) => c.addEventListener('change', drawMetrics));
  return {update: (h) => { update(h); if (h) drawMetrics(); }, stop: stop};
})();
"""

PLAY_STYLE = """
.pl-wrong .shape{stroke:var(--human)!important;stroke-width:3.5!important}
.pl-ghost{fill:none;stroke:var(--human);stroke-width:2.5;stroke-dasharray:5 4;pointer-events:none}
#pl-off{position:fixed;left:50%;top:18%;transform:translateX(-50%);z-index:30;max-width:min(460px,92vw);
background:var(--surface);border:2px solid var(--human);border-radius:12px;padding:14px 16px;
box-shadow:0 10px 30px rgba(0,0,0,.25)}
#pl-off h3{margin:0 0 6px;color:var(--human)}#pl-off p{margin:6px 0}
#pl-off button{font:600 13px var(--body);padding:5px 12px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer}
#hist li.h-wrong{border-left:3px solid var(--human)}#hist li.h-wrong .h-t::before{content:"⚠ "}
#hist li.h-offs{color:var(--human);font-weight:600}
.play{font:600 13px var(--body);width:30px;height:26px;margin-left:10px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--auto);cursor:pointer;vertical-align:middle}
.play:hover:not(:disabled){border-color:var(--auto)}.play.on{background:var(--auto);color:var(--surface)}
.play:disabled{opacity:.4;cursor:default}
select.pass{font:13px var(--body);margin-left:8px;padding:3px 6px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);vertical-align:middle;max-width:min(380px,60vw)}
#player{position:fixed;left:16px;bottom:16px;z-index:25;display:flex;align-items:center;gap:8px;max-width:calc(100vw - 32px);
padding:8px 10px;border-radius:12px;background:var(--surface);border:1px solid var(--line);
box-shadow:0 6px 20px rgba(0,0,0,.18);font-size:13.5px}
#player[hidden]{display:none}
#player button,#player select{font:inherit;padding:3px 8px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer}
.pl-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body.playing svg.map .node:not(.pl-now):not(.pl-seen){opacity:.4}
body.playing svg.map .edge:not(.pl-go):not(.pl-went){opacity:.3}
.node.pl-now .shape{stroke:var(--auto);stroke-width:5;filter:drop-shadow(0 0 10px var(--auto))}
.node.pl-seen .shape{stroke-width:2.8}
.edge.pl-go path.line{stroke:var(--auto);stroke-width:4;stroke-dasharray:10 6;animation:pl-flow .5s linear infinite}
.edge.pl-went path.line{stroke:var(--auto);stroke-width:2.4}
@keyframes pl-flow{to{stroke-dashoffset:-16}}
body.pl-paused .edge.pl-go path.line{animation-play-state:paused}
.pl-clock circle{fill:var(--surface);stroke:var(--auto);stroke-width:2}
.pl-clock line{stroke:var(--ink);stroke-width:2;stroke-linecap:round}
.pl-clock text,.pl-tag{font:700 12px var(--body);fill:var(--auto);paint-order:stroke;stroke:var(--paper);
stroke-width:4px;stroke-linejoin:round}
.pl-tag{font-size:11px}
.metrics{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;margin:10px 0 0;font-size:13.5px}
.metrics label{display:flex;align-items:center;gap:5px;cursor:pointer}
.mt.in{font-size:10.5px;stroke:none}
.mt-hid{display:none}
.mt-map{font:700 13px var(--body);color:var(--violet);margin:0 8px}
.mt-map:empty{display:none}
.mt{font:700 11.5px var(--body);fill:var(--violet);paint-order:stroke;stroke:var(--paper);stroke-width:4px;
stroke-linejoin:round;pointer-events:none}
.panel{position:sticky}
.tabs{display:flex;gap:4px;margin:-4px 0 10px;padding:3px;border-radius:10px;background:var(--lane-b)}
.tabs button{flex:1;font:600 13px var(--body);padding:6px 8px;border:0;border-radius:8px;background:none;
color:var(--muted);cursor:pointer}
.tabs button.on{background:var(--surface);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.12)}
#hist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px}
#hist li{padding:5px 8px;border-radius:8px;cursor:pointer;border-left:3px solid transparent}
#hist li:hover{background:var(--lane-b)}
#hist li.on{background:var(--auto-soft);border-left-color:var(--auto)}
#hist li.h-pass .h-t{font-weight:500;color:var(--muted)}
.h-t{font-weight:600;font-size:14px}.h-m{color:var(--muted);font-size:12.5px}
.h-via{color:var(--muted);font-size:12px}.h-via.back{color:var(--human)}
.h-off{font:600 12px var(--body);color:var(--cloud);margin:6px 0 2px}
"""


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
<option value="4">×4</option></select><span class="pl-text"></span>
<button type="button" class="pl-stop" title="Stop (Esc)">✕</button></div>
<div id="pl-off" role="dialog" aria-labelledby="pl-off-h" hidden><h3 id="pl-off-h">⚠ The feature left the map here</h3>
<p class="pl-off-what"></p><p class="pl-off-when muted"></p>
<p class="muted">The way it took is not drawn: the map, or the code, is wrong here.</p>
<button type="button" class="pl-off-go">Play on</button> <button type="button" class="pl-off-stop">Stop</button></div>"""


LIVE_STYLE = """
.live{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px;align-items:start}
.panel{position:sticky;top:12px;background:var(--surface);border:1px solid var(--line);border-radius:14px;
padding:14px;max-height:calc(100vh - 24px);overflow:auto}
.panel h3{margin:14px 0 6px;font-size:14px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
#where{font-size:20px;font-weight:700}
#acts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
#acts li{border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:var(--lane-a);cursor:pointer}
#acts li:hover{border-color:var(--cloud)}
#acts li.is-focus{border-color:var(--cloud);border-width:2px;background:var(--cloud-soft)}
.an{font-weight:600}.ah2{color:var(--muted);font-size:13px}
#acts code{display:block;margin-top:4px;font-size:12px;color:var(--ink)}
.leads{color:var(--cloud);font-size:13px;margin-top:2px}
#err{color:var(--human)}
.mini{margin-top:12px}
.mini svg.map{min-width:0}
.detail-card{max-height:calc(100vh - 120px);overflow:auto}
.detail-card svg.map{width:auto;max-width:none}
h2.first-map{margin-top:0}
@media (max-width:900px){.live{grid-template-columns:1fr}.panel{position:static;max-height:none}}
"""


def page(label, cfg=None, demo=None):
    """A feature's map: the same drawing as its project's config draws it,
    with its place lit and its actions, kept current by polling
    /__sclaude/flow/state. `demo` is (address, title) of the feature's latest
    recorded demo (skills/sdemo), linked beside the feature, or None."""
    with process_model.configured(process_config.example_config() if cfg is None else cfg):
        return _page(label, demo)


def _page(label, demo=None):
    detail = process_diagram.Diagram(*process_config.node_sets()[0])
    overview = process_diagram.Diagram(*process_config.node_sets()[1])
    script = LIVE_SCRIPT % {
        "label": json.dumps(label),
        "positions": json.dumps({k: [v] if v else [] for k, v in process_model.POSITIONS.items()}),
    }
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
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
<h2 class="first-map">The whole process%s</h2>
<div class="card detail-card">%s</div>
<h2>The cycle at a glance%s</h2><div class="card mini">%s</div>
<h2 id="map-workshop">How a session changes sclaude%s</h2><div class="card mini">%s</div>
<h2 id="map-friction">The friction review%s</h2><div class="card mini">%s</div>
<h2 id="map-regression">A stage's regression%s</h2><div class="card mini">%s</div>
<h2 id="map-sync">Main and the branch%s</h2><div class="card mini">%s</div>
<h2>Every command</h2>%s
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
</main><script>%s%s%s</script></body></html>
""" % (process_diagram.esc(label), process_diagram.STYLE, LIVE_STYLE + PLAY_STYLE, process_diagram.esc(label),
       ' · <a href="%s">🎬 demo: %s</a>' % (process_diagram.esc(demo[0]), process_diagram.esc(demo[1])) if demo else "",
       process_diagram.esc(label), process_diagram.LEGEND,
       play_head("detail", "The whole process"), detail.svg(),
       play_head("overview", "The cycle at a glance"), overview.svg(),
       play_head("workshop", "How a session changes sclaude", passes=True), process_diagram.Diagram(*process_config.node_sets()[2]).svg(),
       play_head("friction", "The friction review", passes=True), process_diagram.Diagram(*process_config.node_sets()[3]).svg(),
       play_head("regression", "A stage's regression", passes=True), process_diagram.Diagram(*process_config.node_sets()[4]).svg(),
       play_head("sync", "Main and the branch", passes=True), process_diagram.Diagram(*process_config.node_sets()[5]).svg(),
       process_doc.commands_table(), PLAYER_BAR,
       process_doc.INTERACT_SCRIPT % {"model": json.dumps(process_doc.client_model())}, PLAY_SCRIPT, script)
