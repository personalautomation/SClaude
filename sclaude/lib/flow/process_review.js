// The review's map of the feature, a panel over the lower half of the page
// (or all of it, full screen) while a review step is in view — the feature standing there, the step
// clicked, or the player on it. Drawn from /__sclaude/flow/review
// (sclaude/lib/review/review_map.py):
//
//   across: the files, each column as wide as the file is long at that
//     round, so a file the fixes grow widens as the rounds go down;
//   down: the rounds, a line between two, each as tall as the log of its
//     time — an idle night stays visible without taking the panel;
//   a mark: one fix (a hunk) at its line, as wide as it is large — fixes
//     to one place round after round stack into a spike;
//   its hue: how the thread it answered ended; its saturation: code against
//     comments; hatched: the fix added lines (code born in review);
//   dots: the threads, where they were posted; ✋ the person, ringed red
//     where the answer was the recommended one given within seconds;
//   behind the rows' names: one pale icicle of every file at once, the
//     development's lines over the lines each round touched.
const reviewMap = (() => {
  const REVIEW = new Set(['review_run', 'review_close', 'review']);
  const OUT = {
    fixed: [168, 'fixed'], declined: [0, 'declined'], yours: [38, 'left to you'],
    night: [268, 'decided at night'], reversal: [6, 'would undo a fix'], open: [222, 'open'],
    side: [210, 'no thread'],
  };
  const FAST = 20;  // seconds: an answer quicker than this is a reflex
  const panel = document.getElementById('rv');
  const chip = document.getElementById('rv-chip');
  const body = panel.querySelector('.rv-body');
  const bar = document.getElementById('player');
  let data = null, fetched = 0, drawnKey = '', until = null, ctx = {live: false, sel: null, play: null}, shown = false, loading = null;
  let off = false, drawn = false, placesNow = [], doneOf = () => false, whyOf = () => '';
  // How icicles are drawn: 'fix' joins the files one fix touched; 'file'
  // keeps one icicle a file, splitting where its changes part.
  let mode = 'fix';
  try { mode = localStorage.getItem('review-map-mode') === 'file' ? 'file' : 'fix'; } catch (e) {}
  try { off = localStorage.getItem('review-map-off') === '1'; } catch (e) {}
  const isReview = (id) => !!id && REVIEW.has((processMap.model.base || {})[id] || id);
  const dark = () => document.documentElement.dataset.theme === 'dark'
    || (document.documentElement.dataset.theme !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  const h = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
  function colour(outcome, code) {
    const [hue] = OUT[outcome] || OUT.side;
    const grey = outcome === 'declined' || outcome === 'side';
    const sat = grey ? (outcome === 'side' ? 18 : 0) : Math.round(25 + 60 * code);
    return 'hsl(' + hue + ',' + sat + '%,' + (dark() ? 62 : 46) + '%)';
  }
  // The development's code: one tone, paler at `alpha`, its saturation code
  // against comments like a fix's.
  function devColour(code, alpha) {
    return 'hsla(222,' + Math.round(10 + 35 * code) + '%,' + (dark() ? 58 : 52) + '%,' + alpha + ')';
  }
  // A round's name: a pull request read in review blocks counts its rounds
  // afresh in each block, so the block comes first — "Block 2 · round 3";
  // read whole, "Round 3". `short` is the number alone, for small labels.
  function roundName(i, short) {
    const rs = (data && data.rounds) || [];
    const r = rs[i];
    if (!r) return short ? String(i + 1) : 'Round ' + (i + 1);
    if (!r.block) return short ? String(i + 1) : 'Round ' + (i + 1);
    let k = 0;
    for (let j = 0; j <= i; j++) if (rs[j].block === r.block) k++;
    return short ? r.block + '.' + k : 'Block ' + r.block + ' · round ' + k;
  }
  function dur(s) {
    if (s == null) return '';
    if (s < 60) return Math.round(s) + ' s';
    const m = Math.round(s / 60);
    if (m < 60) return m + ' min';
    const hh = Math.floor(m / 60);
    return hh < 24 ? hh + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '') : Math.floor(hh / 24) + ' d ' + (hh % 24) + ' h';
  }

  // --- when it shows -------------------------------------------------------
  function wanted() {
    if (ctx.play !== null) return ctx.play;
    if (ctx.sel !== null) return ctx.sel;
    return ctx.live;
  }
  function update() {
    const want = wanted();
    chip.hidden = !(want && off);
    const show = want && !off;
    if (show === shown) { if (show) draw(); return; }
    shown = show;
    if (!show) full(false);
    panel.hidden = !show;
    document.body.classList.toggle('rv-open', show);
    room();
    if (show) { load(); draw(); requestAnimationFrame(centre); }
  }
  // Full screen covers the page: the room kept below it is the half
  // panel's, so the page and the player stand where they were on the way back.
  function full(on) {
    if (panel.classList.contains('rv-max') === on) return;
    panel.classList.toggle('rv-max', on);
    const b = panel.querySelector('.rv-full');
    b.setAttribute('aria-pressed', String(on));
    b.textContent = on ? '🗗 exit full screen' : '⛶ full screen';
    document.body.classList.toggle('rv-maxed', on);
    if (!on) room();
    if (shown) draw();
  }
  function room() {
    if (panel.classList.contains('rv-max')) return;
    const px = shown ? panel.offsetHeight : 0;
    document.documentElement.style.setProperty('--rvh', px + 'px');
  }
  addEventListener('resize', () => { room(); if (shown) draw(); });
  // The player shown or gone (it hides after its last step is sent): the
  // room kept for it in full screen follows.
  if (bar) new MutationObserver(() => { if (shown) draw(); }).observe(bar, {attributes: true, attributeFilter: ['hidden']});
  // The review step's blocks in the middle of what the panel leaves above it:
  // the whole process's map, scrolled inside its card and the page.
  function centre() {
    const card = document.querySelector('.detail-card');
    const nodes = [...document.querySelectorAll('svg.map-detail .node')].filter((n) => isReview(n.dataset.node));
    if (!card || !nodes.length) return;
    const rs = nodes.map((n) => n.getBoundingClientRect());
    const top = Math.min(...rs.map((r) => r.top)), bottom = Math.max(...rs.map((r) => r.bottom));
    const left = Math.min(...rs.map((r) => r.left)), right = Math.max(...rs.map((r) => r.right));
    const c = card.getBoundingClientRect();
    card.scrollBy({top: (top + bottom) / 2 - (c.top + card.clientHeight / 2),
                   left: (left + right) / 2 - (c.left + card.clientWidth / 2), behavior: 'smooth'});
    const area = innerHeight - (shown ? panel.offsetHeight : 0);
    scrollBy({top: (c.top + c.bottom) / 2 - area / 2, behavior: 'smooth'});
  }

  // --- the data ------------------------------------------------------------
  function load(force) {
    if (loading || (!force && Date.now() - fetched < 30000)) return;
    if (!data) body.innerHTML = '<p class="muted rv-wait">Reading the review…</p>';
    loading = fetch('/__sclaude/flow/review?f=' + encodeURIComponent(label), {cache: 'no-store'})
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((d) => { data = d; fetched = Date.now(); draw(); })
      .catch((e) => { if (!data) body.innerHTML = '<p class="muted rv-wait">The review could not be read (' + h(e) + ')</p>'; })
      .finally(() => { loading = null; });
  }
  setInterval(() => { if (shown && !document.hidden) load(); }, 60000);

  // --- the drawing ---------------------------------------------------------
  function summary(d, rounds) {
    const n = {}, hands = d.hands.filter((x) => until == null || (x.t || 0) * 1000 <= until);
    d.threads.forEach((t) => { if (until == null || (t.t || 0) * 1000 <= until) n[t.outcome] = (n[t.outcome] || 0) + 1; });
    const grown = d.hunks.filter((x) => x.r < rounds.length).reduce((a, x) => a + Math.max(0, x.add - x.del), 0);
    const cost = rounds.reduce((a, r) => a + (r.cost || 0), 0);
    const fast = hands.filter((x) => x.rec && x.waited != null && x.waited <= FAST).length;
    const rec = hands.filter((x) => x.rec).length;
    return '<b>PR #' + h(d.pr) + '</b> · ' + rounds.length + ' round' + (rounds.length === 1 ? '' : 's')
      + (cost ? ' · $' + cost.toFixed(2) : '')
      + ' · threads: ' + Object.entries(n).map(([k, v]) => '<span class="rv-k" style="--c:' + colour(k, 1) + '">' + v + ' ' + OUT[k][1] + '</span>').join(' ')
      + ' · +' + grown + ' lines born in review'
      + ' · ✋ ' + hands.length + (rec ? ' (' + rec + ' recommended' + (fast ? ', <b class="rv-fast">' + fast + ' within ' + FAST + ' s</b>' : '') + ')' : '');
  }
  function draw() {
    if (!shown || !data) return;
    // Full screen, the player keeps its place at the bottom, over the
    // panel: the map's scroller ends above it (a margin, so its scroll bar
    // is lifted too), by its height, measured, while it shows — at most a
    // quarter of the panel, so a short screen still has a map to see; what
    // the cap leaves out is padding inside, so the last rows scroll out
    // from under the player.
    const need = panel.classList.contains('rv-max') && bar && !bar.hidden ? bar.offsetHeight + 20 : 0;
    const pad = Math.floor(Math.min(need, panel.clientHeight / 4));
    body.style.marginBottom = pad ? pad + 'px' : '';
    body.style.paddingBottom = need > pad ? (need - pad) + 'px' : '';
    // Each poll and each player step asks again; the drawing is rebuilt only
    // when what it is drawn from changed, so the element under the pointer
    // and the scroll stay as they were.
    const key = [fetched, until, mode, panel.classList.contains('rv-nohands'), body.clientWidth, body.clientHeight, need, dark()].join('|');
    if (key === drawnKey) return;
    drawnKey = key;
    // The places are numbered afresh: a tooltip kept by number would show another's.
    tip.hidden = true; tip.dataset.i = '';
    const d = data;
    if (d.error) { body.innerHTML = '<p class="muted rv-wait">' + h(d.error) + '</p>'; return; }
    let rounds = d.rounds;
    if (until != null) rounds = rounds.filter((r) => r.t * 1000 <= until);
    panel.querySelector('.rv-sum').innerHTML = d.rounds.length ? summary(d, rounds) : 'No review round yet';
    if (!rounds.length) { body.innerHTML = '<p class="muted rv-wait">No review round ' + (d.rounds.length ? 'by this moment' : 'yet') + '.</p>'; return; }
    let files = d.files.map((f) => f.path);
    const devf = (d.dev && d.dev.files) || {};
    // Lines of each file at each boundary between rounds: the round's head,
    // and after the last its fixes' end — where a line sits in its file.
    const lines = rounds.map((r) => r.lines).concat([rounds.length < d.rounds.length ? d.rounds[rounds.length].lines : d.final]);
    // A column a file, as wide as the root of the code the development wrote
    // in it (a file only the review touched: what the review wrote), so a
    // short file still has room for its icicles.
    const reviewed = {};
    d.hunks.forEach((x) => { reviewed[x.path] = (reviewed[x.path] || 0) + x.add + x.del; });
    // A file the review never touched is a thin strip: its code is in the
    // block above, and the room goes to the files the icicles hang from.
    const touched = new Set(Object.keys(reviewed).concat(d.threads.map((t) => t.path)));
    // One column, two files: where the review's fixes moved on from one file
    // to another for good — a reply says a thread of A was fixed in B
    // (fixedIn), B is new in the review, nothing happens in A from the round
    // B starts and nothing in B before it, B in A's block or in none (the
    // cut was made before the review wrote it) — B goes on
    // under A in A's column (a migration fixed by the next migration, and
    // that by the next). The strongest move first; a file follows one file
    // and is followed by one.
    const rowsOf = {};
    const rowsAt = (f) => rowsOf[f] = rowsOf[f] || {h: [], t: []};
    d.hunks.forEach((x) => rowsAt(x.path).h.push(x.r));
    d.threads.forEach((t) => { if (t.r != null) rowsAt(t.path).t.push(t.r); });
    const cutOf = {};
    (d.blocks || []).forEach((b) => b.files.forEach((f) => { if (!(f in cutOf)) cutOf[f] = b.n; }));
    const moves = {};
    d.threads.forEach((t) => (((t.fixedIn || {}).files) || []).forEach((b) => {
      if (b !== t.path && t.r != null && t.r < rounds.length) moves[t.path + '\n' + b] = (moves[t.path + '\n' + b] || 0) + 1;
    }));
    const after = {}, before = {}, split = {};
    const headOf = (f) => { while (before[f]) f = before[f]; return f; };
    Object.entries(moves).sort((a, b) => b[1] - a[1]).forEach(([k]) => {
      const [a, b] = k.split('\n');
      if (after[a] || before[b] || headOf(a) === b || (devf[b] || {}).add || (cutOf[b] && cutOf[b] !== cutOf[a])) return;
      const ra = rowsAt(a), rb = rowsAt(b);
      const from = Math.min(...rb.h, ...rb.t);
      if (!isFinite(from) || ra.h.some((r) => r >= from) || ra.t.some((r) => r > from)) return;
      after[a] = b; before[b] = a; split[b] = from;
    });
    // The rows each file of a column holds: from where it starts to where
    // the next one does.
    const until_ = (f) => after[f] ? split[after[f]] : Infinity;
    // The touched files side by side as the review went: the first one the
    // first round fixed most, then each time the file sharing the most
    // rounds with the last one placed — so files a round fixes together sit
    // next to each other and their icicles join. The untouched after them.
    const roundsOf = {}, size = {};
    d.hunks.forEach((x) => {
      (roundsOf[x.path] = roundsOf[x.path] || new Set()).add(x.r);
      size[x.path] = (size[x.path] || 0) + x.add + x.del;
    });
    d.threads.forEach((t) => { if (t.r != null) (roundsOf[t.path] = roundsOf[t.path] || new Set()).add(t.r); });
    Object.keys(before).forEach((f) => {
      const lead = headOf(f);
      (roundsOf[f] || []).forEach((r) => (roundsOf[lead] = roundsOf[lead] || new Set()).add(r));
      size[lead] = (size[lead] || 0) + (size[f] || 0);
    });
    const firstOf = (f) => Math.min(99, ...(roundsOf[f] || []));
    const left = files.filter((f) => touched.has(f) && !before[f])
      .sort((a, b) => firstOf(a) - firstOf(b) || (size[b] || 0) - (size[a] || 0) || (a < b ? -1 : 1));
    // Two files are linked where one fix answered a thread in both, or one
    // subagent given one or two findings edited both: the order puts linked
    // files side by side first, then files sharing rounds.
    const linkOf = (x) => x.thread ? 't:' + x.thread : x.agent ? 'a:' + x.agent : '';
    const keyFiles = {};
    d.hunks.forEach((x) => {
      const k = linkOf(x);
      if (k) (keyFiles[x.r + '|' + k] = keyFiles[x.r + '|' + k] || new Set()).add(x.path);
    });
    // A thread whose reply names the commit and the file a fix landed in
    // (fixedIn, review_map.py's replied) links its file to that one in both
    // ways of drawing: the person or the session said so.
    const strong = {};
    d.threads.forEach((t) => (((t.fixedIn || {}).files) || []).forEach((f) => {
      if (f === t.path) return;
      const a = headOf(t.path), b = headOf(f);
      if (a === b) return;
      strong[a] = strong[a] || {}; strong[a][b] = (strong[a][b] || 0) + 1;
      strong[b] = strong[b] || {}; strong[b][a] = (strong[b][a] || 0) + 1;
    }));
    const linked = {};
    Object.values(keyFiles).forEach((fs) => {
      const list = [...fs];
      list.forEach((a) => list.forEach((b) => {
        if (a !== b) { linked[a] = linked[a] || {}; linked[a][b] = (linked[a][b] || 0) + 1; }
      }));
    });
    const order = [];
    while (left.length) {
      let pick = 0;
      if (order.length) {
        const prev = order[order.length - 1];
        const last = roundsOf[prev] || new Set();
        let best = -1;
        left.forEach((f, i) => {
          const score = ((strong[prev] || {})[f] || 0) * 100000
            + (mode === 'fix' ? ((linked[prev] || {})[f] || 0) * 1000 : 0)
            + [...(roundsOf[f] || [])].filter((r) => last.has(r)).length;
          if (score > best) { best = score; pick = i; }
        });
      }
      order.push(left.splice(pick, 1)[0]);
    }
    files = order.concat(files.filter((f) => !touched.has(f)));
    // A column's files, its head first.
    const stackOf = (f) => { const out = [f]; while (after[out[out.length - 1]]) out.push(after[out[out.length - 1]]); return out; };
    // Read in review blocks, the columns are grouped by block — each changed
    // file is in one — in the order above within a block; the files the cut
    // does not name (written after it) come last. A round of block 1 not
    // opening block 4's files is the cut, not a gap.
    const blockOf = {};
    (d.blocks || []).forEach((b) => b.files.forEach((f) => { if (!(f in blockOf)) blockOf[f] = b.n; }));
    const hasBlocks = (d.blocks || []).length > 0;
    if (hasBlocks) {
      const rank = (f) => (blockOf[f] || 999) * 2 + (touched.has(f) ? 0 : 1);
      files = files.map((f, i) => [f, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0]);
    }
    const weight = files.map((f) => touched.has(f)
      ? Math.max(...stackOf(f).map((g) => Math.sqrt(Math.max(1, (devf[g] || {}).add || reviewed[g] || 1)))) : 0);
    const GUT = 176, HEAD = hasBlocks ? 92 : 74, GAP = 2, BGAP = 8, MINW = 14, THIN = 4, width = Math.max(320, body.clientWidth - 8);
    const total = weight.reduce((a, w) => a + w, 0) || 1;
    const groupsN = hasBlocks ? new Set(files.map((f) => blockOf[f] || 999)).size : 1;
    const avail = width - GUT - 8 - GAP * files.length - BGAP * (groupsN - 1) - THIN * files.filter((f) => !touched.has(f)).length;
    const cols = [], groups = [];
    let cx = GUT;
    files.forEach((f, i) => {
      const g = hasBlocks ? blockOf[f] || 999 : 0;
      if (!groups.length || groups[groups.length - 1].g !== g) {
        if (groups.length) cx += BGAP;
        groups.push({g: g, x0: cx, x1: cx});
      }
      const w = touched.has(f) ? Math.max(MINW, avail * weight[i] / total) : THIN;
      cols.push([cx, w]); cx += w + GAP;
      groups[groups.length - 1].x1 = cx - GAP;
    });
    const W = Math.max(width, cx + 8);
    const fi = {}; files.forEach((f, i) => { stackOf(f).forEach((g) => { fi[g] = i; }); });
    // Where line `line` of `f` sits at boundary `b`, by line numbers — for a
    // file with no projected axis.
    const at = (b, f, line) => {
      const c = cols[fi[f]];
      return c[0] + Math.min(1, Math.max(0, (line - 1) / Math.max(1, (lines[b] || {})[f] || line))) * c[1];
    };
    // Where place `p` of a file's projected axis sits (review_map.py's
    // project: every line ever in the file keeps its place, a deleted one
    // too, so a place is the same in every round).
    const axisOf = {};
    d.files.forEach((f) => { if (f.axis) axisOf[f.path] = f.axis; });
    const ax = (f, p) => { const c = cols[fi[f]]; return c[0] + Math.min(1, Math.max(0, p / Math.max(1, axisOf[f]))) * c[1]; };
    const threadX = (t) => t.p != null && axisOf[t.path] ? ax(t.path, t.p + 0.5) : at(t.r, t.path, t.line);
    const byRid = {};
    d.threads.forEach((t) => { if (t.rid) byRid[t.rid] = t; });
    // Heights: the development as tall as the log of its time, each round
    // the same way, to the next one.
    const now = until != null ? until / 1000 : Date.now() / 1000;
    const tall = (s) => 34 + 24 * Math.log2(1 + Math.max(0, s) / 300);
    const devLen = d.dev && d.dev.t ? rounds[0].t - d.dev.t : 0;
    rounds.forEach((r, i) => {
      const next = i + 1 < d.rounds.length ? d.rounds[i + 1].t : now;
      r._len = Math.max(r.seconds || 0, Math.min(next, now) - r.t);
    });
    // All of it fits the panel's height while it can: the height left under
    // the files' names (less a horizontal scroll bar, when the columns are
    // wider than the panel) is shared by the rows in proportion, a row
    // never under ROWMIN — the short ones stop there and the rest share
    // what is left (k found by halving). Only when every row at ROWMIN
    // still does not fit does the panel scroll.
    const ROWMIN = 22, BOTTOM = 4;
    // clientHeight already leaves out a bar that is there; one about to
    // come with this drawing is taken off here.
    const coming = W > body.clientWidth && body.scrollWidth <= body.clientWidth ? 15 : 0;
    const room = Math.max(ROWMIN * 2, body.clientHeight - (need - pad) - coming - HEAD - BOTTOM);
    const raw = [devLen ? tall(devLen) : 26].concat(rounds.map((r) => tall(r._len)));
    const fit = (k) => raw.reduce((a, v) => a + Math.max(ROWMIN, v * k), 0);
    let lo = 0, hi = 1;
    if (fit(1) > room) { for (let i = 0; i < 30; i++) { const m = (lo + hi) / 2; if (fit(m) > room) hi = m; else lo = m; } }
    else lo = 1;
    const hs = raw.map((v) => Math.max(ROWMIN, v * lo));
    const top = HEAD, bandH = hs[0];
    const ys = [top + bandH];
    rounds.forEach((r, i) => { ys.push(ys[i] + hs[i + 1]); });
    const H = ys[ys.length - 1] + BOTTOM;
    // A row too low for two lines says its first; the tooltip says it all.
    const two = (i) => hs[i] >= 34;
    const svg = ['<svg class="rv-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '">',
      '<defs><pattern id="rv-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
      '<line x1="0" y1="0" x2="0" y2="5" class="rv-hl"/></pattern></defs>'];
    // The lanes, and on top all the code the development wrote: each file's
    // block, darker where the pull request changed it.
    let devAdd = 0, lane = 0;
    // Where a column goes on in another file: drawn over the icicles, below.
    const nexts = [];
    files.forEach((f, i) => {
      const c = cols[i], dv = devf[f] || {add: 0, code: 0, comment: 0, regions: []};
      devAdd += dv.add;
      // A lane, alternating, only where something happened — a fix or a
      // thread: a file the review never touched has none, and the picture
      // stays clean.
      if (touched.has(f)) {
        lane = (lane + 1) % 2;
        svg.push('<rect class="rv-col' + (lane ? ' odd' : '') + '" x="' + c[0].toFixed(1) + '" y="' + top + '" width="' + c[1].toFixed(1) + '" height="' + (H - top - 6) + '"/>');
      }
      const code = dv.code + dv.comment ? dv.code / (dv.code + dv.comment) : 1;
      // A file the development did not write: nothing above it.
      if (dv.add) svg.push('<g class="rv-dev"><title>' + h(f) + ' — +' + dv.add + ' lines written before the review (' + dv.code + ' code, ' + dv.comment + ' comment)</title>'
        + '<rect x="' + c[0].toFixed(1) + '" y="' + top + '" width="' + c[1].toFixed(1) + '" height="' + bandH.toFixed(1) + '" fill="' + devColour(code, 0.45) + '"/>'
        + (dv.proj && axisOf[f] ? dv.proj.map(([a, b]) => [a, b, true]) : dv.regions).map(([x, n, onAxis]) => {
          const x0 = onAxis ? ax(f, x) : at(0, f, x);
          const x1 = Math.max(x0 + 1, onAxis ? ax(f, n) : at(0, f, x + n));
          return '<rect x="' + x0.toFixed(1) + '" y="' + top + '" width="' + (x1 - x0).toFixed(1) + '" height="' + bandH.toFixed(1) + '" fill="' + devColour(code, 1) + '"/>';
        }).join('') + '</g>');
      // Every file of the column in its heading, a line each, in order, each
      // name cut to fit; the hover has their full paths. The lines are
      // centred on the column across the slant.
      const stack = stackOf(f), cut = 28, LH = 11;
      const lines = stack.map((g, k) => {
        const n = g.split('/').pop();
        return (k ? '↓ ' : '') + (n.length > cut ? n.slice(0, cut - 1) + '…' : n);
      });
      const lift = (lines.length - 1) * LH / 2;
      const tx = c[0] + c[1] / 2 + 3 - lift * 0.819, ty = HEAD - 6 - lift * 0.574;
      if (touched.has(f)) svg.push('<g class="rv-file"><title>' + h(stack.join('\n↓ ')) + (stack.length > 1 ? '\n\nThe fixes moved on from one file to the next: each goes on under the one before, in this column.' : '')
        + '</title><text transform="translate(' + tx.toFixed(1) + ',' + ty.toFixed(1) + ') rotate(-55)">'
        + lines.map((l, k) => '<tspan x="0"' + (k ? ' dy="' + LH + '"' : '') + '>' + h(l) + '</tspan>').join('') + '</text></g>');
      // Where the column goes on in the next file: a line across it, and
      // the file's name.
      stack.slice(1).forEach((g) => {
        const y = ys[split[g]];
        if (y == null) return;
        const nm = g.split('/').pop();
        nexts.push('<g class="rv-next"><title>From here this column is ' + h(g) + ': the fixes of ' + h(before[g]) + ' went on there</title>'
          + '<line x1="' + c[0].toFixed(1) + '" x2="' + (c[0] + c[1]).toFixed(1) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"/>'
          + '<text x="' + (c[0] + 2).toFixed(1) + '" y="' + (y - 2).toFixed(1) + '">↓ ' + h(nm.length > Math.max(4, c[1] / 5.5) ? nm.slice(0, Math.max(3, Math.floor(c[1] / 5.5))) + '…' : nm) + '</text></g>');
      });
    });
    // The blocks: a line between two, and each one's name over its files.
    if (hasBlocks) groups.forEach((g, k) => {
      const b = (d.blocks || []).find((x) => x.n === g.g);
      const name = b ? 'Block ' + b.n : 'Not in the cut';
      const full = b ? name + ': ' + b.title : 'Files the cut does not name — written after it';
      const room = Math.max(0, Math.floor((g.x1 - g.x0) / 6.2));
      const label = room < 3 ? '' : (name + (b && room > name.length + 4 ? ' · ' + b.title : '')).slice(0, room);
      svg.push('<g class="rv-bk"><title>' + h(full) + '</title><rect x="' + g.x0.toFixed(1) + '" y="2" width="' + Math.max(1, g.x1 - g.x0).toFixed(1) + '" height="16" rx="3"/>'
        + '<text x="' + (g.x0 + 4).toFixed(1) + '" y="14">' + h(label) + '</text></g>');
      if (k) svg.push('<line class="rv-bsep" x1="' + (g.x0 - BGAP / 2).toFixed(1) + '" x2="' + (g.x0 - BGAP / 2).toFixed(1) + '" y1="2" y2="' + H + '"/>');
    });
    // The summary icicle goes here, behind the rows' names, once the
    // places below say how much each round changed.
    const sumAt = svg.length;
    svg.push('<text class="rv-rt" x="6" y="' + (top + 15) + '">Development' + (devLen ? ' · ' + dur(devLen) : '') + '</text>');
    if (two(0)) svg.push('<text class="rv-rs" x="6" y="' + (top + 29) + '">+' + devAdd + ' lines</text>');
    // The rounds: a line, and what each was.
    rounds.forEach((r, i) => {
      // A new block: a heavier line.
      const opens = r.block && (!i || rounds[i - 1].block !== r.block);
      svg.push('<line class="rv-round' + (opens && i ? ' rv-block' : '') + '" x1="0" x2="' + W + '" y1="' + ys[i] + '" y2="' + ys[i] + '"/>');
      // Round n of the review, the block of the pull request it read when
      // it was read in blocks, how long until the next round, where it ran,
      // what it found and what the conversations in it cost.
      svg.push('<g class="rv-rl"><title>' + roundName(i) + (r.block ? ' — the pull request is read in review blocks; this round read block ' + h(r.block) + ', whose rounds are counted from 1' : '')
        + '\n' + dur(r._len) + ' until ' + (i + 1 < d.rounds.length ? 'the next round' : 'now')
        + '\nThe review ran ' + (r.source === 'github' ? 'on GitHub, in the project\'s workflow' : 'on this machine')
        + (r.stopped ? '\nStopped: the pass left no recorded answer, so it found and read nothing that counts; the commits after it are its fixes' : '')
        + (r.new != null ? '\n' + r.new + ' new finding' + (r.new === 1 ? '' : 's') : '')
        + (r.cost ? '\n$' + r.cost.toFixed(2) + ': its passes and the fixes of what it found, as the review report prices them' : '')
        + (r.seen ? '\nOpened ' + r.seen.length + ' of the ' + files.length + ' files on the map (pale icicles: code it never opened)' : r.source === 'github' ? '\nWhat a GitHub run read is not known here' : '') + '</title>'
        + '<text class="rv-rt" x="6" y="' + (ys[i] + 15) + '">' + roundName(i) + ' · ' + dur(r._len) + '</text>'
        + (two(i + 1) ? '<text class="rv-rs" x="6" y="' + (ys[i] + 29) + '">' + (r.stopped ? 'stopped, no answer' : r.source === 'github' ? 'on GitHub' : 'on this machine')
          + (r.new != null ? ' · ' + r.new + ' found' : '') + (r.cost ? ' · $' + r.cost.toFixed(2) : '') + '</text>' : '') + '</g>');
    });
    // The icicles. A round's fixes close together in one file are one
    // place, and places in two files join when they are one fix (one
    // thread, or one subagent's work): an icicle widens when
    // the round draws another file in. A place hangs
    // from the place of the round before it overlaps most, or from the
    // development's block; a file the development did not write has
    // nothing above it, and its place starts as a point. Each file's share
    // of the width is its column's times sqrt(changed / written), so an
    // icicle narrows as fewer of that code's lines are touched, and grows
    // again when a round touches more. A place no later round comes back to
    // ends in a point.
    const places = rounds.map(() => []);
    const f1 = (n) => n.toFixed(1);
    rounds.forEach((r, ri) => {
      const by = {};
      d.hunks.forEach((x) => { if (x.r === ri && fi[x.path] != null) (by[x.path] = by[x.path] || []).push(x); });
      const bits = [];
      Object.entries(by).forEach(([f, hs]) => {
        const c = cols[fi[f]], gap = Math.max(6, c[1] * 0.08), mine = [];
        hs.map((x) => x.p0 != null && axisOf[f]
          ? {x0: ax(f, x.p0), x1: Math.max(ax(f, x.p0) + 1, ax(f, x.p1)), hs: [x]}
          : {x0: at(ri + 1, f, x.x), x1: at(ri + 1, f, x.x + Math.max(1, x.n)), hs: [x]})
          .sort((a, b) => a.x0 - b.x0)
          .forEach((p) => {
            const last = mine[mine.length - 1];
            if (last && p.x0 - last.x1 < gap) { last.x1 = Math.max(last.x1, p.x1); last.hs.push(...p.hs); }
            else mine.push(Object.assign(p, {f: f, ci: fi[f]}));
          });
        bits.push(...mine);
      });
      // Places in different files join when they are one fix: a thread
      // both answer, or one subagent's work on one or two findings.
      // Joined bits whose columns are not side by side stay apart.
      bits.forEach((b, i) => { b.k = i; b.keys = new Set(b.hs.map(linkOf).filter(Boolean)); });
      const root = bits.map((b, i) => i);
      const find = (i) => root[i] === i ? i : (root[i] = find(root[i]));
      // By file: each file its own icicle, never joined to another.
      if (mode === 'fix') bits.forEach((a) => bits.forEach((b) => {
        if (a.k < b.k && a.f !== b.f && [...a.keys].some((k) => b.keys.has(k))) root[find(a.k)] = find(b.k);
      }));
      const groups = {};
      bits.forEach((b) => { (groups[find(b.k)] = groups[find(b.k)] || []).push(b); });
      Object.values(groups).forEach((g) => {
        g.sort((a, b) => a.ci - b.ci || a.x0 - b.x0);
        let run = null;
        g.forEach((b) => {
          if (run && b.ci - run.ci1 <= 1 && b.ci !== run.bits[run.bits.length - 1].ci) {
            run.bits.push(b); run.ci1 = b.ci; run.x1 = Math.max(run.x1, b.x1);
          } else if (run && b.ci === run.ci1) {
            // A second place in the same file, joined through the other file:
            // its own icicle, the link said in the hover.
            places[ri].push({bits: [b], ci0: b.ci, ci1: b.ci, x0: b.x0, x1: b.x1});
          } else {
            run = {bits: [b], ci0: b.ci, ci1: b.ci, x0: b.x0, x1: b.x1};
            places[ri].push(run);
          }
        });
      });
      places[ri].sort((a, b) => a.x0 - b.x0);
      places[ri].forEach((p) => {
        // Why the files of a place are one, for the hover.
        if (p.bits.length > 1) {
          const shared = [...p.bits[0].keys].filter((k) => p.bits.slice(1).every((b) => b.keys.has(k)));
          const k = shared[0] || [...p.bits[0].keys][0] || '';
          p.why = k.startsWith('t:') ? 'one thread, ' + k.slice(2) : k.startsWith('a:') ? 'one subagent\'s fix' : '';
        }
      });
      places[ri].forEach((p) => {
        p.hs = p.bits.flatMap((b) => b.hs);
        const sum = (k) => p.hs.reduce((a, x) => a + x[k], 0);
        p.changed = sum('add') + sum('del'); p.code = sum('code'); p.comment = sum('comment'); p.net = sum('add') - sum('del');
        const by = {};
        p.hs.forEach((x) => { by[x.outcome] = (by[x.outcome] || 0) + x.add + x.del + (x.outcome === 'side' ? 0 : 1000); });
        p.outcome = Object.entries(by).sort((a, b) => b[1] - a[1])[0][0];
        // Each file's share of the width, side by side.
        const perFile = {};
        p.bits.forEach((b) => { perFile[b.f] = (perFile[b.f] || 0) + b.hs.reduce((a, x) => a + x.add + x.del, 0); });
        p.files = Object.keys(perFile);
        p.lo = cols[p.ci0][0]; p.hi = cols[p.ci1][0] + cols[p.ci1][1];
        p.dev = p.files.some((f) => (devf[f] || {}).add);
        // It hangs from every place of the round before in one of its files
        // whose code overlaps, give or take a third of its narrowest column:
        // two or more is a merge, and a place two of this round hang from
        // splits. A neighbouring column's place is never a parent.
        const reach = Math.min(...p.files.map((f) => cols[fi[f]][1])) * 0.3;
        p.ups = (ri ? places[ri - 1] : []).filter((q) =>
          q.files.some((f) => p.files.includes(f))
          && Math.min(q.x1, p.x1 + reach) - Math.max(q.x0, p.x0 - reach) > 0);
      });
    });
    // The width at a round's bottom is the lines the round changed there, on
    // one scale for the whole map: the scale at which four places in five
    // fit the columns they stand in; the rest are held to their columns.
    const all = places.flat();
    const fits = all.map((p) => (p.hi - p.lo) / Math.max(1, p.changed)).sort((a, b) => a - b);
    const scale = fits.length ? fits[Math.floor(fits.length * 0.2)] : 1;
    all.forEach((p) => {
      p.w = Math.min(p.hi - p.lo, Math.max(3, p.changed * scale));
      p.cx = Math.min(p.hi - p.w / 2, Math.max(p.lo + p.w / 2, (p.x0 + p.x1) / 2));
      p.l = p.cx - p.w / 2; p.r = p.cx + p.w / 2;
    });
    // Behind the rows' names, one quiet icicle of every file at once: the
    // development's lines on top, then the lines each round touched (a
    // fix's larger side, so a line rewritten counts once, as the
    // development's lines do), on a square-root scale so a round stays visible under a large development.
    // Coloured as the icicles are, paler: a row split by how its lines'
    // threads ended, saturated by code against comments, hatched where the
    // round added more than it took away.
    {
      const per = places.map((ps) => {
        const r = {changed: 0, net: 0, out: {}};
        ps.forEach((p) => {
          r.net += p.net;
          p.hs.forEach((x) => {
            const o = r.out[x.outcome] = r.out[x.outcome] || {n: 0, code: 0, comment: 0};
            const n = Math.max(x.add, x.del);
            o.n += n; r.changed += n; o.code += x.code; o.comment += x.comment;
          });
        });
        return r;
      });
      let dc = 0, dm = 0;
      files.forEach((f) => { dc += (devf[f] || {}).code || 0; dm += (devf[f] || {}).comment || 0; });
      const most = Math.max(1, devAdd, ...per.map((r) => r.changed));
      const wOf = (v) => (GUT - 16) * Math.sqrt(v / most), mid = (GUT - 4) / 2;
      const lerp = (wd, t) => mid - wd / 2 + wd * t;
      const out = ['<g class="rv-sumi">'];
      let wPrev = wOf(devAdd);
      out.push('<rect x="' + f1(mid - wPrev / 2) + '" y="' + top + '" width="' + f1(wPrev) + '" height="' + f1(ys[0] - top) + '" fill="' + devColour(dc + dm ? dc / (dc + dm) : 1, 1) + '"/>');
      per.forEach((r, i) => {
        const w = wOf(r.changed), y0 = ys[i], y1 = ys[i + 1];
        const parts = Object.keys(OUT).filter((k) => r.out[k] && r.out[k].n);
        const sum = parts.reduce((a, k) => a + r.out[k].n, 0);
        const outline = 'M' + f1(mid - wPrev / 2) + ',' + f1(y0) + ' L' + f1(mid + wPrev / 2) + ',' + f1(y0)
          + ' L' + f1(mid + w / 2) + ',' + f1(y1) + ' L' + f1(mid - w / 2) + ',' + f1(y1) + 'Z';
        if (!sum) out.push('<path d="' + outline + '" fill="' + colour('side', 1) + '"/>');
        let a = 0;
        parts.forEach((k) => {
          const o = r.out[k], b = a + o.n / sum;
          out.push('<path d="M' + f1(lerp(wPrev, a)) + ',' + f1(y0) + ' L' + f1(lerp(wPrev, b)) + ',' + f1(y0)
            + ' L' + f1(lerp(w, b)) + ',' + f1(y1) + ' L' + f1(lerp(w, a)) + ',' + f1(y1) + 'Z" fill="'
            + colour(k, o.code + o.comment ? o.code / (o.code + o.comment) : 1) + '"/>');
          a = b;
        });
        if (r.net >= 3) out.push('<path d="' + outline + '" fill="url(#rv-hatch)"/>');
        wPrev = w;
      });
      svg.splice(sumAt, 0, out.join('') + '</g>');
    }
    // For the hover: each place's round, the places that hang from it, the
    // threads posted at it in its round and your answers about them.
    const flat = [];
    places.forEach((ps, ri) => ps.forEach((p) => { p.ri = ri; p.kids = []; p.id = flat.length; flat.push(p); }));
    flat.forEach((p) => p.ups.forEach((q) => q.kids.push(p)));
    flat.forEach((p) => {
      p.th = d.threads.filter((t) => {
        if (t.r !== p.ri || !p.files.includes(t.path)) return false;
        const x = threadX(t);
        return x >= p.x0 - 12 && x <= p.x1 + 12;
      });
    });
    // The icicle slides to the file a reply names: a thread posted at a
    // place of an earlier round and fixed, its reply says, in another file
    // — the round's places in that file hang from the place, which the
    // layout put beside it. In both ways of drawing.
    d.threads.forEach((t) => {
      const fx = t.fixedIn;
      if (!fx || t.r == null || t.r >= rounds.length || fi[t.path] == null) return;
      const x = threadX(t);
      const reach = cols[fi[t.path]][1] * 0.3;
      const src = flat.filter((q) => q.ri < t.r && q.files.includes(t.path) && x >= q.x0 - reach && x <= q.x1 + reach)
        .sort((a, b) => b.ri - a.ri)[0];
      if (!src) return;
      // Into its own column or the next it is drawn as a stream; further
      // away a stream would read as a line through other files' icicles, so
      // it jumps: a mark where it leaves and one where it lands, each a link
      // to the other. Either way the chain goes on there.
      places[fx.r] && places[fx.r].forEach((q) => {
        if (q === src || !q.files.some((f) => fx.files.includes(f))) return;
        if (q.files.some((f) => fx.files.includes(f) && Math.abs(fi[f] - fi[t.path]) <= 1)) {
          if (!q.ups.includes(src)) { q.ups.push(src); src.kids.push(q); }
        } else {
          q.jin = q.jin || []; src.jout = src.jout || [];
          if (!q.jin.includes(src)) { q.jin.push(src); src.jout.push(q); }
        }
        if (!q.th.includes(t)) q.th.push(t);
        q.slid = q.slid || [];
        q.slid.push(t.path);
      });
    });
    flat.forEach((p) => {
      const rids = new Set(p.th.map((t) => t.rid).filter(Boolean));
      p.hd = d.hands.filter((x) => x.rid && rids.has(x.rid));
    });
    // A place's bottom shared among the places that hang from it, side by
    // side in proportion to their widths: where it splits.
    flat.forEach((q) => {
      q.kids.sort((a, b) => a.cx - b.cx);
      const sum = q.kids.reduce((a, k) => a + k.w, 0) || 1;
      let x = q.l;
      q.slice = new Map(q.kids.map((k) => { const s = [x, x + q.w * k.w / sum]; x = s[1]; return [k, s]; }));
    });
    placesNow = flat;
    // A chain is done when it is a chain of fixes — at least one thread —
    // every thread of it has an outcome (none open, none waiting for the
    // person), and the round after its last fix read all of it (no pass
    // stopped at its cap) and posted no new thread there. Code with no
    // thread, new code a fix wrote among them, is never called done: one
    // reading of it says nothing yet.
    const SETTLED = new Set(['fixed', 'declined', 'reversal']);
    const ownerOf = {};
    (d.blocks || []).forEach((b) => b.files.forEach((f) => { ownerOf[f] = b.n; }));
    function chain(p) {
      const all = new Set([p]), todo = [p];
      while (todo.length) { const p_ = todo.shift(); p_.ups.concat(p_.jin || []).forEach((q) => { if (!all.has(q)) { all.add(q); todo.push(q); } }); }
      return [...all];
    }
    // Threads a later round posted at a place where no fix of that round
    // landed — fixed elsewhere (a new migration, a caller), or not yet —
    // are still the place's: its chain goes on through them, and the round
    // that reads past the last of them is the one that checks it.
    const inPlace = new Set(flat.flatMap((q) => q.th));
    function later(p) {
      const reach = Math.min(...p.files.map((f) => cols[fi[f]][1])) * 0.3;
      return d.threads.filter((t) => t.r != null && t.r > p.ri && t.r < rounds.length && !inPlace.has(t)
        && p.files.includes(t.path) && threadX(t) >= p.x0 - reach && threadX(t) <= p.x1 + reach);
    }
    // Done: every thread of the chain (if any) has an outcome, the round
    // after its last fix or thread read all of it and found nothing there,
    // and that round's own fixing is over — the round after it has begun —
    // so no fix of it can still land here. Code no thread led to closes the
    // same way: a whole round read it, found nothing, and moved on.
    function why(p) {
      if (p.kids.length || (p.jout || []).length) return 'continues';
      const orph = later(p);
      p.lastR = Math.max(p.ri, ...orph.map((t) => t.r));
      p.orph = orph;
      // The round that checks it: the first after its last fix or thread
      // that opened its files. A round that never opened them found nothing
      // there by not looking (review_map.py's seen; unknown for a GitHub
      // run, which leaves no transcript here, and taken as read): the
      // icicle goes on through it, pale — still to be checked.
      const opened = (k) => !rounds[k].seen || p.files.every((f) => rounds[k].seen.includes(f));
      let v = p.lastR + 1;
      while (v < rounds.length && !opened(v)) v++;
      p.ghost = [p.lastR + 1, v];
      const next = rounds[v];
      if (!next) {
        if (p.lastR + 1 >= rounds.length) return orph.length ? 'elsewhere' : 'unread';
        // Unread while the pull request is read in blocks: a later block's
        // file is read whole when that block comes, a file no block owns by
        // the next block read whole — the review has not skipped it.
        const owners = p.files.map((f) => ownerOf[f] || 0);
        if (d.blockNow != null && rounds.length === d.rounds.length) {
          if (owners.every((n) => n > d.blockNow)) { p.laterBlock = Math.min(...owners); return 'later'; }
          if (owners.every((n) => !n)) return 'cutless';
        }
        return 'unseen';
      }
      p.verify = v;
      const ths = chain(p).flatMap((q) => q.th).concat(orph);
      if (!ths.every((t) => SETTLED.has(t.outcome))) return orph.some((t) => !SETTLED.has(t.outcome)) ? 'elsewhere' : 'open';
      if (next.more) return 'partial';
      // The last round: its fixing is over once step 4 is.
      if (!rounds[v + 1]) return d.closed && rounds.length === d.rounds.length ? 'done' : 'checking';
      return 'done';
    }
    function done(p) { return why(p) === 'done'; }
    whyOf = why;
    doneOf = done;
    places.forEach((ps, ri) => ps.forEach((p) => {
      const y0 = ys[ri], y1 = ys[ri + 1];
      // A trapezoid: the bottom as wide as the lines this round changed
      // here; the top the slices of the places above it has (wider than one
      // when it merges them), or, in the first round, its own width under
      // the development's code. A place with nothing above it — a file the
      // development did not write, or code first touched in a later round —
      // starts as a point in the middle of its row. Where no later round
      // came back, the icicle closes to a point in the middle of the next
      // row only once its chain is done (done()): every thread of it and of
      // the places it grew from has an outcome, and the next round read
      // the fix; otherwise it is cut flat — waiting.
      // A merge is drawn as one stream a parent, each from its slice of the
      // parent's bottom to its share of this place's bottom, left to right,
      // so it shows where each part came from.
      const quad = (a, b, c, e, t) => 'M' + f1(a) + ',' + f1(t) + ' L' + f1(b) + ',' + f1(t) + ' L' + f1(e) + ',' + f1(y1) + ' L' + f1(c) + ',' + f1(y1) + 'Z';
      let d_;
      if (p.ups.length) {
        const s = p.ups.map((q) => q.slice.get(p)).sort((a, b) => a[0] - b[0]);
        const total = s.reduce((a, v) => a + Math.max(0.5, v[1] - v[0]), 0);
        let x = p.l;
        d_ = s.map((v) => {
          const share = p.w * Math.max(0.5, v[1] - v[0]) / total;
          const part = quad(v[0], v[1], x, x + share, y0);
          x += share;
          return part;
        }).join(' ');
      } else if (ri || !p.dev) {
        d_ = quad(p.cx, p.cx, p.l, p.r, (y0 + y1) / 2);
      } else {
        d_ = quad(p.l, p.r, p.l, p.r, y0);
      }
      const isDone = done(p);
      // Rounds that never opened its files: the icicle goes on through them
      // as it was, pale — still there, still unchecked.
      let ghost = '';
      const g0 = p.ghost ? p.ghost[0] : 0, g1 = p.ghost ? Math.min(p.ghost[1], rounds.length, ...p.files.map(until_)) : 0;
      if (!p.kids.length && !(p.jout || []).length && g1 > g0) {
        ghost = 'M' + f1(p.l) + ',' + f1(ys[g0]) + ' L' + f1(p.r) + ',' + f1(ys[g0]) + ' L' + f1(p.r) + ',' + f1(ys[g1]) + ' L' + f1(p.l) + ',' + f1(ys[g1]) + 'Z';
      }
      if (isDone && p.orph && p.orph.length && p.verify === p.lastR + 1) {
        // Its later threads, fixed elsewhere: their dots say it; once the
        // chain is done, a small point in the row of the round that checked it.
        const close = p.verify, stop = (ys[close] + ys[close + 1]) / 2;
        d_ += ' M' + f1(p.cx - 4) + ',' + f1(ys[close]) + ' L' + f1(p.cx + 4) + ',' + f1(ys[close]) + ' L' + f1(p.cx) + ',' + f1(stop) + 'Z';
      } else if (isDone) {
        // Closed in the row of the round that checked it, after any pale rows.
        const close = p.verify, end = (ys[close] + ys[close + 1]) / 2;
        d_ += ' M' + f1(p.l) + ',' + f1(ys[close]) + ' L' + f1(p.r) + ',' + f1(ys[close]) + ' L' + f1(p.cx) + ',' + f1(end) + 'Z';
      }
      const code = p.code + p.comment ? p.code / (p.code + p.comment) : 1;
      // The pale rows: the place's own colour fading down to pale.
      const gid = 'rv-g' + p.id;
      svg.push('<g class="rv-fix" data-i="' + p.id + '">'
        + (ghost ? '<linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + colour(p.outcome, code)
          + '" stop-opacity="0.9"/><stop offset="1" stop-color="' + colour(p.outcome, code) + '" stop-opacity="0.12"/></linearGradient>'
          + '<linearGradient id="' + gid + 's" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="' + colour(p.outcome, code)
          + '" stop-opacity="0.9"/><stop offset="1" stop-color="' + colour(p.outcome, code) + '" stop-opacity="0"/></linearGradient>'
          + '<path class="rv-ghost" d="' + ghost + '" fill="url(#' + gid + ')" stroke="url(#' + gid + 's)"/>' : '')
        + '<path class="rv-shape" d="' + d_ + '" fill="' + colour(p.outcome, code) + '"/>'
        + (p.net >= 3 ? '<path d="' + d_ + '" fill="url(#rv-hatch)"/>' : '') + '</g>');
    }));
    // The jumps: where a chain leaves for a file too far to stream to, a
    // mark in the middle of the row it lands in, under where it left; where
    // it lands, a mark beside the place — below the threads' piles, which
    // hang from the row's top. Each is a link to the other (#rvj-<n>-out,
    // #rvj-<n>-in): a click scrolls the map there and lights it.
    svg.push(...nexts);
    let jn = 0;
    const offs = {};
    // Marks at one spot fan out away from the place: out to the right, in
    // to the left.
    const mark = (id, go, x, y, glyph, say, side) => {
      const k = Math.round(x) + ':' + Math.round(y);
      const dx = (offs[k] = (offs[k] || 0) + 1) - 1;
      const cx = x + side * dx * 13;
      return '<a class="rv-jump" id="' + id + '" href="#' + go + '" data-go="' + go + '"><title>' + h(say) + '</title>'
        + '<circle cx="' + cx.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="6.5"/><text x="' + cx.toFixed(1) + '" y="' + (y + 3.5).toFixed(1) + '">' + glyph + '</text></a>';
    };
    flat.forEach((src) => (src.jout || []).forEach((q) => {
      jn++;
      const y = Math.max(ys[q.ri] + 14, (ys[q.ri] + ys[q.ri + 1]) / 2);
      const there = q.files.join(', '), here = src.files.join(', ');
      svg.push(mark('rvj-' + jn + '-out', 'rvj-' + jn + '-in', src.cx, y, '↗',
        'Goes on in ' + there + ' (' + roundName(q.ri).toLowerCase() + '): a reply says its thread was fixed there.\nClick to go there.', 1));
      svg.push(mark('rvj-' + jn + '-in', 'rvj-' + jn + '-out', q.l - 9, y, '↘',
        'Came from ' + here + ' (' + roundName(src.ri).toLowerCase() + '): a reply says its thread was fixed here.\nClick to see where it left.', -1));
    }));
    // The threads, stacked: those a round posted close together in the code
    // pile down from the round's line into one column, a dot each in the
    // colour of how it ended — the taller the column, the more the review
    // found there. Squeezed to fit the round's height where a pile is tall.
    const ORDER = ['open', 'reversal', 'yours', 'night', 'declined', 'fixed', 'side'];
    const piles = {};
    d.threads.forEach((t) => {
      if (t.r == null || t.r >= rounds.length || fi[t.path] == null || (until != null && t.t * 1000 > until)) return;
      const x = threadX(t);
      const key = t.r + ':' + Math.round(x / 9);
      (piles[key] = piles[key] || {r: t.r, xs: [], all: []}).all.push(t);
      piles[key].xs.push(x);
    });
    Object.values(piles).forEach((p) => {
      p.all.sort((a, b) => ORDER.indexOf(a.outcome) - ORDER.indexOf(b.outcome));
      const x = p.xs.reduce((a, v) => a + v, 0) / p.xs.length;
      const room = ys[p.r + 1] - ys[p.r] - 10;
      const step = Math.min(8.5, room / Math.max(1, p.all.length));
      const r = Math.max(1.8, Math.min(4, step / 2 + 0.3));
      // A capsule under the pile, so its dots read over an icicle of the
      // same colour.
      const len = step * (p.all.length - 1);
      svg.push('<rect class="rv-pile" x="' + (x - r - 1.5).toFixed(1) + '" y="' + (ys[p.r] + 5 - r - 1.5).toFixed(1) + '" width="' + (2 * r + 3).toFixed(1)
        + '" height="' + (len + 2 * r + 3).toFixed(1) + '" rx="' + (r + 1.5).toFixed(1) + '"/>');
      p.all.forEach((t, k) => {
        const y = ys[p.r] + 5 + k * step;
        svg.push('<a href="' + h(t.url) + '" target="_blank" rel="noopener"><circle class="rv-th' + (t.by === 'person' ? ' you' : '') + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1)
          + '" r="' + r.toFixed(1) + '" fill="' + colour(t.outcome, 1) + '"><title>' + h(t.path) + ':' + t.line + ' — ' + h(t.title) + '\n' + OUT[t.outcome][1]
          + (t.resolvedBy ? ', resolved by ' + h(t.resolvedBy) : '') + (t.by === 'person' ? '\nyour thread' : '')
          + (p.all.length > 1 ? '\n' + p.all.length + ' threads here' : '') + '</title></circle></a>');
      });
    });
    // The person, gathered: one ✋ for each round's answers in the margin,
    // and one for the answers and threads at one place of a file, with how
    // many — ringed red when any was the recommended answer given within
    // FAST seconds, amber when any took the recommended one.
    if (!panel.classList.contains('rv-nohands')) {
      const groups = {};
      d.hands.forEach((p) => {
        if (p.r == null || p.r >= rounds.length || (until != null && p.t * 1000 > until)) return;
        const placed = p.path && fi[p.path] != null;
        const x = placed ? (byRid[p.rid] ? threadX(byRid[p.rid]) : at(p.r, p.path, p.line)) : null;
        const key = p.r + ':' + (placed ? Math.round(x / 18) : 'm');
        (groups[key] = groups[key] || {r: p.r, x: placed ? x : null, all: []}).all.push(p);
      });
      Object.values(groups).forEach((g) => {
        const all = g.all, n = all.length;
        const rec = all.filter((p) => p.rec).length, other = all.filter((p) => p.rec === false).length;
        const fast = all.filter((p) => p.rec && p.waited != null && p.waited <= FAST).length;
        const mine = all.filter((p) => p.kind === 'thread').length, said = all.filter((p) => p.kind === 'sclaude').length;
        const waits = all.map((p) => p.waited).filter((w) => w != null).sort((a, b) => a - b);
        const x = g.x != null ? g.x + 8 : GUT - 34;
        const y = ys[g.r] + (g.x != null ? 14 : Math.min(two(g.r + 1) ? 52 : 30, Math.max(14, ys[g.r + 1] - ys[g.r] - 4)));
        const head = n + (n === 1 ? ' time' : ' times') + ' you stepped in'
          + (rec ? '\n' + rec + ' took the recommended answer' + (fast ? ', ' + fast + ' within ' + FAST + ' s' : '') : '')
          + (other ? '\n' + other + ' chose otherwise' : '') + (mine ? '\n' + mine + ' your own thread' + (mine > 1 ? 's' : '') : '')
          + (said ? '\n' + said + ' answered sclaude' : '')
          + (waits.length ? '\nhalf answered within ' + dur(waits[Math.floor((waits.length - 1) / 2)]) : '');
        const list = all.filter((p) => p.q).slice(0, 8).map((p) => '\n• ' + h(p.q.slice(0, 140)) + (p.a ? ' → ' + h(p.a.slice(0, 60)) : '')).join('');
        svg.push('<g class="rv-hand' + (fast ? ' fast' : rec ? ' rec' : '') + '"><title>' + h(head) + list + (all.filter((p) => p.q).length > 8 ? '\n…' : '') + '</title>'
          + (fast || rec ? '<circle cx="' + x.toFixed(1) + '" cy="' + (y - 4).toFixed(1) + '" r="8"/>' : '')
          + '<text x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '">✋</text>'
          + (n > 1 ? '<text class="rv-hn" x="' + (x + 10).toFixed(1) + '" y="' + y.toFixed(1) + '">' + n + (fast ? ' · ' + fast + '⚡' : '') + '</text>' : '') + '</g>');
      });
    }
    svg.push('</svg>');
    const keep = [body.scrollLeft, body.scrollTop];
    body.innerHTML = svg.join('');
    body.scrollLeft = keep[0];
    // Too many rounds to fit: open on the latest, and follow the player down.
    body.scrollTop = until != null || !drawn ? body.scrollHeight : keep[1];
    drawn = true;
  }
  // --- the hover on an icicle ------------------------------------------------
  // What a place is and how it went: where, what this round did there, the
  // threads and your answers at it, its whole icicle round by round as a
  // small bar chart, and a reading of it — converging, growing again,
  // polishing comments, declined more than taken, or ended.
  const tip = document.createElement('div');
  tip.id = 'rv-tip'; tip.hidden = true; document.body.append(tip);
  // The whole icicle a place is part of: every place it joins to, up and
  // down, through merges and splits.
  function lineage(p) {
    const all = new Set([p]), todo = [p];
    while (todo.length) {
      const q = todo.shift();
      q.ups.concat(q.kids, q.jin || [], q.jout || []).forEach((n) => { if (!all.has(n)) { all.add(n); todo.push(n); } });
    }
    return [...all];
  }
  function tipHtml(p) {
    const half = (q) => [(q.changed + q.net) / 2, (q.changed - q.net) / 2];
    const [add, del] = half(p);
    const where = p.bits.map((b) => {
      const ls = b.hs.map((x) => x.x).sort((a, c) => a - c);
      return '<div class="t-f">' + h(b.f) + ':' + ls[0] + (ls.length > 1 ? '–' + ls[ls.length - 1] : '') + '</div>';
    }).join('');
    const all = lineage(p);
    const byRound = {};
    all.forEach((q) => {
      const r = byRound[q.ri] = byRound[q.ri] || {changed: 0, code: 0, comment: 0, out: {}, th: [], fixes: 0};
      r.changed += q.changed; r.code += q.code; r.comment += q.comment; r.fixes += q.hs.length;
      r.out[q.outcome] = (r.out[q.outcome] || 0) + q.changed;
      r.th.push(...q.th);
    });
    const first = Math.min(...Object.keys(byRound).map(Number)), last = Math.max(...Object.keys(byRound).map(Number));
    const series = [];
    for (let r = first; r <= last; r++) series.push([r, byRound[r] || null]);
    const most = Math.max(1, ...series.map(([, v]) => v ? v.changed : 0));
    const bars = '<div class="t-sp">' + series.map(([r, v]) => {
      const out = v ? Object.entries(v.out).sort((a, b) => b[1] - a[1])[0][0] : 'side';
      const code = v && v.code + v.comment ? v.code / (v.code + v.comment) : 1;
      return '<span class="' + (r === p.ri ? 'on' : '') + '" title="' + roundName(r) + ': ' + (v ? v.changed + ' lines, ' + v.th.length + ' threads' : 'not touched') + '">'
        + '<i style="height:' + (v ? Math.max(2, 34 * v.changed / most) : 0).toFixed(0) + 'px;background:' + (v ? colour(out, code) : 'none') + '"></i><b>' + roundName(r, true) + '</b></span>';
    }).join('') + '</div>';
    // The reading, most telling first.
    const ths = all.flatMap((q) => q.th);
    const declined = ths.filter((t) => t.outcome === 'declined' || t.outcome === 'reversal').length;
    const vals = series.map(([, v]) => v ? v.changed : 0);
    const tail = series.slice(-2).map(([, v]) => v);
    const latest = (data.rounds.length - 1);
    const says = [];
    const hasDown = all.some((q) => q.ri === last && q.kids.length);
    const ended = last < latest && !hasDown;
    const tips = all.filter((q) => !q.kids.length);
    const WAIT = {
      unread: 'Waiting: no round has read the fix of ' + roundName(last).toLowerCase() + ' here yet.',
      unseen: 'Waiting: no round since the fix has opened this file — they found nothing here by not looking; the icicle goes on, pale.',
      later: 'Waiting for block ' + (tips.find((q) => q.laterBlock) || {}).laterBlock + ': its first read reads this file whole; the icicle goes on, pale, till then.',
      cutless: 'Waiting: the cut into blocks does not name this file (written after it); the next block read whole takes it.',
      checking: 'Waiting: the round after the fix read all of it and found nothing here; its own fixing is not over yet, so a fix of it may still land here.',
      open: 'Waiting: a thread of it is still open or waits for you.',
      partial: 'Waiting: the round after the fix stopped at its cap, so it may not have said all it found here.',
      found: 'Waiting: the round after the fix posted a new thread here.',
      elsewhere: 'Waiting: a later round posted threads here and no fix landed here — they are fixed elsewhere or not yet; the chain is checked once they all have an outcome and the round after reads past them.',
    };
    const closedIn = Math.max(...tips.map((q) => (q.lastR != null ? q.lastR : q.ri) + 1));
    if (tips.length && tips.every((q) => doneOf(q))) says.push(['end', 'Done in ' + roundName(closedIn).toLowerCase() + ': every thread of it has an outcome, that round read all of it and found nothing here, and its fixing ended without coming back.']);
    else {
      const reasons = [...new Set(tips.map((q) => whyOf(q)).filter((w) => WAIT[w]))];
      reasons.forEach((w) => says.push(['wait', WAIT[w]]));
    }
    if (ended) { /* its trend is over */ } else if (tail.length === 2 && tail.every((v) => v && v.code === 0 && v.comment > 0)) says.push(['polish', 'Only comments for the last two rounds here — likely polishing.']);
    else if (vals.length >= 2 && vals[vals.length - 1] > vals[vals.length - 2] * 1.2) says.push(['grow', 'Growing again: ' + roundName(last).toLowerCase() + ' changed more here than the round before.']);
    else if (vals.length >= 2 && vals[vals.length - 1] < vals[vals.length - 2]) says.push(['conv', 'Converging: each round changes fewer lines here.']);
    if (ths.length >= 2 && declined * 2 >= ths.length) says.push(['decl', declined + ' of ' + ths.length + ' threads here declined: the review keeps raising what is left as it is.']);
    if (series.length >= 3) says.push(['long', 'The review came back here in ' + series.filter(([, v]) => v).length + ' of ' + (latest + 1) + ' rounds.']);
    const devLines = p.files.reduce((a, f) => a + ((((data.dev || {}).files || {})[f] || {}).add || 0), 0);
    const churn = all.reduce((a, q) => a + q.changed, 0);
    const threads = p.th.slice(0, 4).map((t) => '<div class="t-th"><i style="background:' + colour(t.outcome, 1) + '"></i>' + h(t.title || t.rid) + ' <span class="muted">· ' + OUT[t.outcome][1] + '</span></div>').join('')
      + (p.th.length > 4 ? '<div class="muted">… and ' + (p.th.length - 4) + ' more</div>' : '');
    whyOf(p);
    const laterThreads = (p.orph || []).map((t) => '<div class="t-th"><i style="background:' + colour(t.outcome, 1) + '"></i>' + roundName(t.r) + ': ' + h(t.title || t.rid) + ' <span class="muted">· ' + OUT[t.outcome][1] + '</span></div>').join('');
    const rec = p.hd.filter((x) => x.rec).length, fast = p.hd.filter((x) => x.rec && x.waited != null && x.waited <= FAST).length;
    return where
      + (p.why ? '<div class="t-r muted">Files joined as ' + h(p.why) + '</div>' : '')
      + (p.slid ? '<div class="t-r muted">Slid here from ' + h([...new Set(p.slid)].join(', ')) + ': the reply to its thread names the commit and this file</div>' : '')
      + ((p.jout || []).length ? '<div class="t-r muted">Went on in ' + h([...new Set(p.jout.flatMap((q) => q.files))].join(', ')) + ' — the ↗ mark leads there</div>' : '')
      + '<div class="t-r"><b>' + roundName(p.ri) + '</b>: ' + p.hs.length + ' fix' + (p.hs.length > 1 ? 'es' : '') + ', +' + add + ' −' + del
      + ' · ' + p.code + ' code, ' + p.comment + ' comment · <span style="color:' + colour(p.outcome, 1) + '">' + OUT[p.outcome][1] + '</span>'
      + (p.net >= 3 ? ' · <b>+' + p.net + ' lines grown</b>' : '') + '</div>'
      + (threads ? '<div class="t-h">Threads posted here</div>' + threads : '<div class="muted">No thread here: these fixes came along with others.</div>')
      + (laterThreads ? '<div class="t-h">Posted here later, with no fix here</div>' + laterThreads : '')
      + (p.hd.length ? '<div class="t-r">✋ ' + p.hd.length + ' answer' + (p.hd.length > 1 ? 's' : '') + ' about them' + (rec ? ', ' + rec + ' the recommended one' + (fast ? ' (<b class="rv-fast">' + fast + ' within ' + FAST + ' s</b>)' : '') : '') + '</div>' : '')
      + '<div class="t-h">This icicle, round by round (lines changed)</div>' + bars
      + '<div class="t-r muted">' + churn + ' lines changed here over ' + series.filter(([, v]) => v).length + ' round' + (series.filter(([, v]) => v).length > 1 ? 's' : '')
      + (devLines ? ' — ' + Math.round(100 * churn / devLines) + '% of the ' + devLines + ' lines the development wrote in ' + (p.files.length > 1 ? 'these files' : 'this file') : ' — in code the development did not write') + '</div>'
      + says.map(([k, t]) => '<div class="t-say t-' + k + '">' + h(t) + '</div>').join('');
  }
  body.addEventListener('mousemove', (ev) => {
    const g = ev.target.closest && ev.target.closest('.rv-fix');
    if (!g || !placesNow[+g.dataset.i]) { tip.hidden = true; return; }
    if (tip.dataset.i !== g.dataset.i) { tip.innerHTML = tipHtml(placesNow[+g.dataset.i]); tip.dataset.i = g.dataset.i; }
    tip.hidden = false;
    const pad = 14, w = tip.offsetWidth, hh = tip.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY - hh - pad;
    if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
    if (y < 8) y = ev.clientY + pad;
    tip.style.left = Math.max(4, x) + 'px'; tip.style.top = Math.max(4, y) + 'px';
  });
  body.addEventListener('mouseleave', () => { tip.hidden = true; });
  // A jump's mark: to its other end, in the middle of the map, lit a moment.
  body.addEventListener('click', (ev) => {
    const a = ev.target.closest && ev.target.closest('[data-go]');
    if (!a) return;
    ev.preventDefault();
    const el = body.querySelector('#' + a.dataset.go);
    if (!el) return;
    const r = el.getBoundingClientRect(), b = body.getBoundingClientRect();
    body.scrollBy({left: r.left + r.width / 2 - (b.left + b.width / 2), top: r.top + r.height / 2 - (b.top + b.height / 2), behavior: 'smooth'});
    el.classList.remove('rv-lit'); void el.getBoundingClientRect(); el.classList.add('rv-lit');
    setTimeout(() => el.classList.remove('rv-lit'), 1800);
  });

  function legend() {
    panel.querySelector('.rv-legend').innerHTML = '<span class="rv-k" style="--c:' + devColour(1, 1) + '">code before the review</span>' + ['fixed', 'declined', 'yours', 'night', 'reversal', 'open', 'side']
      .map((k) => '<span class="rv-k" style="--c:' + colour(k, 1) + '">' + OUT[k][1] + '</span>').join('')
      + '<span class="rv-k rv-pale" style="--c:' + colour('fixed', 0) + '">pale: comments</span>'
      + '<span class="rv-k rv-uk">pale: no round has opened that code since</span><span class="rv-k rv-hk">hatched: lines added</span><span>⋮ threads, a dot each, piled where they are many</span><span><b class="rv-fast">◯✋ 5 · 2⚡</b> 5 times you stepped in, 2 took the recommended answer within ' + FAST + ' s</span>';
  }
  legend();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { legend(); draw(); });

  // --- the controls --------------------------------------------------------
  panel.querySelector('.rv-off').addEventListener('click', () => {
    off = true;
    try { localStorage.setItem('review-map-off', '1'); } catch (e) {}
    update();
  });
  chip.addEventListener('click', () => {
    off = false;
    try { localStorage.setItem('review-map-off', '0'); } catch (e) {}
    update();
  });
  panel.querySelector('.rv-hands').addEventListener('change', (ev) => {
    panel.classList.toggle('rv-nohands', !ev.target.checked); draw();
  });
  panel.querySelector('.rv-centre').addEventListener('click', centre);
  panel.querySelector('.rv-full').addEventListener('click', () => full(!panel.classList.contains('rv-max')));
  panel.querySelectorAll('.rv-mode input').forEach((r) => {
    r.checked = r.value === mode;
    r.addEventListener('change', () => {
      if (!r.checked) return;
      mode = r.value;
      try { localStorage.setItem('review-map-mode', mode); } catch (e) {}
      draw();
    });
  });
  // A click on the map: the step picked, or none.
  document.addEventListener('click', (ev) => {
    if (ev.target.closest('#rv') || ev.target.closest('#rv-chip')) return;
    setTimeout(() => {
      const picked = processMap.selected().filter((k) => k.startsWith('n:'));
      ctx.sel = picked.length ? picked.some((k) => isReview(k.slice(2))) : null;
      update();
    }, 0);
  });
  // Esc in full screen only leaves it: caught before the page's own Esc
  // (the selection cleared, the player stopped) is reached.
  addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || !panel.classList.contains('rv-max')) return;
    ev.stopPropagation(); full(false);
  }, true);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { ctx.sel = null; update(); } });
  // The player on a place: the panel follows it, to the moment it left.
  document.addEventListener('pl-step', (ev) => {
    const s = ev.detail;
    if (!s) { ctx.play = null; until = null; update(); return; }
    ctx.play = isReview(s.n);
    const end = Date.parse(s.to || s.from || '');
    until = isNaN(end) ? null : end;
    update();
  });
  return {
    // The feature's place now, from each poll (process_live.js).
    live: (node) => { ctx.live = isReview(node); update(); },
  };
})();
window.reviewMap = reviewMap;
