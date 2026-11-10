
const player = (() => {
  let data = null, token = 0, paused = false, speed = 1, at = 0, wanted = null;
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
    token++; paused = false; clear(); bar.hidden = true; playing = null; at = 0;
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
                 regression: "a stage's regression", sync: 'main and the branch',
                 parts: 'a feature built in parts'};
  // The maps a pass is played on, each a way of its own from the main one.
  // Who took a way, as history_edge (state.sh) names them.
  const BY = {person: 'you', setting: 'by the setting', sclaude: 'sclaude', session: 'the session',
    qa: 'QA', github: 'GitHub', none: 'nobody answered'};
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
  async function run(steps, label, start, map) {
    stop();
    start = start || 0;
    const mine = ++token;
    playing = {steps: steps, label: label, map: map};
    played = {}; inPlay = new Set(steps.map((s) => s.map));
    document.body.classList.add('playing');
    bar.hidden = false;
    showTab('history');
    list(steps, label);
    mark(steps, start);
    let prev = start ? steps[start - 1] : null;
    for (let i = start; i < steps.length; i++) {
      const s = steps[i];
      at = i;
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
      const e = arrow(prev, s), took = s.via || {};
      // Who took the way in, how and what was known, where the code wrote
      // it (history's `via`); the arrow's words alone where it did not.
      const said = [took.label || (e && e.l), BY[took.by] || took.by, took.how, took.note,
        took.at && !s.from ? when(took.at) : ''].filter(Boolean);
      if (said.length) {
        const via = document.createElement('div');
        via.className = 'h-via' + (e && e.k === 'back' ? ' back' : '');
        via.textContent = '→ ' + said.join(' · ');
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
        run(steps, label, i, playing && playing.map);
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
    const stay = stayHere();
    (map === 'detail' ? h.visits : onMap(h.visits, map)).forEach((s) => {
      if (!s.pass) { out.push(Object.assign({map: map}, s)); return; }
      if (stay) return;
      const p = (h.passes[s.pass[0]] || [])[s.pass[1]];
      if (p) p.steps.forEach((x, j) => out.push(Object.assign({map: s.pass[0], pass: p.label},
        x, j || !s.off ? {} : {off: s.off})));
    });
    return out;
  }
  document.querySelectorAll('.play').forEach((b) => b.addEventListener('click', () => {
    if (b.classList.contains('on')) { stop(); return; }
    run(expand(b.dataset.play), b.dataset.label, 0, b.dataset.play);
    b.textContent = '■'; b.classList.add('on');
  }));
  bar.querySelector('.pl-pause').addEventListener('click', (ev) => {
    paused = !paused; ev.target.textContent = paused ? '▶' : '⏸';
    document.body.classList.toggle('pl-paused', paused);
  });
  bar.querySelector('.pl-speed').addEventListener('change', (ev) => { speed = +ev.target.value; });
  // "This map only": the play stays on the map it was started from, the
  // passes it went through left out rather than opened on their own maps
  // (a steady view to watch, or to record). Kept for the next visit; a
  // change while a play runs starts that play again with it.
  const stay = bar.querySelector('.pl-stay input');
  function stayHere() { return stay.checked; }
  try { stay.checked = localStorage.getItem('process-stay') === '1'; } catch (e) {}
  stay.addEventListener('change', () => {
    try { localStorage.setItem('process-stay', stay.checked ? '1' : '0'); } catch (e) {}
    const b = document.querySelector('.play.on');
    if (!b || PASSES.includes(b.dataset.play)) return;
    run(expand(b.dataset.play), b.dataset.label, 0, b.dataset.play);
    b.textContent = '■'; b.classList.add('on');
  });
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
    if (bar.hidden && !wanted) list(expand('detail'), 'The whole process');
    if (wanted) { const w = wanted; wanted = null; resume(w); }
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
  }
  try {
    const kept = JSON.parse(localStorage.getItem('process-metrics') || '[]');
    document.querySelectorAll('.metrics input').forEach((c) => { c.checked = kept.includes(c.value); });
  } catch (e) {}
  // Kept for this browser when the person ticks them; a link's own choice
  // (process_url.js, window.processUrlRestoring) is for that view alone.
  // Only the box ticked is changed in what is kept: the boxes a link turned
  // on stay out of it.
  document.querySelectorAll('.metrics input').forEach((c) => c.addEventListener('change', () => {
    drawMetrics();
    if (window.processUrlRestoring) return;
    try {
      const kept = JSON.parse(localStorage.getItem('process-metrics') || '[]').filter((v) => v !== c.value);
      if (c.checked) kept.push(c.value);
      localStorage.setItem('process-metrics', JSON.stringify(kept));
    } catch (e) {}
  }));
  // A play as the address keeps it (process_url.js): which map, which pass,
  // where it is, how fast, on this map only, paused.
  function state() {
    if (bar.hidden || !playing || !playing.map) return null;
    const sel = document.querySelector('select.pass[data-pass="' + playing.map + '"]');
    return {map: playing.map, pass: PASSES.includes(playing.map) && sel ? sel.value : null, at: at,
            speed: speed, only: stay.checked, paused: paused};
  }
  // The same, started again once the history has come.
  function resume(w) {
    const b = document.querySelector('.play[data-play="' + w.map + '"]');
    if (!b) return;
    const sel = document.querySelector('select.pass[data-pass="' + w.map + '"]');
    if (sel && w.pass != null && sel.querySelector('option[value="' + w.pass + '"]')) sel.value = w.pass;
    stay.checked = !!w.only;
    speed = w.speed || 1;
    bar.querySelector('.pl-speed').value = String(speed);
    const steps = expand(w.map);
    run(steps, b.dataset.label, Math.min(w.at || 0, Math.max(0, steps.length - 1)), w.map);
    b.textContent = '■'; b.classList.add('on');
    if (w.paused) {
      say(b.dataset.label + ' · paused at ' + (at + 1) + '/' + steps.length);
      paused = true;
      bar.querySelector('.pl-pause').textContent = '▶';
      document.body.classList.add('pl-paused');
    }
  }
  return {update: (h) => { update(h); if (h) drawMetrics(); }, stop: stop, state: state,
          want: (w) => { if (data) resume(w); else wanted = w; }};
})();
window.player = player;
