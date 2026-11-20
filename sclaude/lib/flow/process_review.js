// The review's map of the feature, a panel over the lower half of the page
// (or all of it, full screen) while a review step is in view — the feature standing there, the step
// clicked, or the player on it. Drawn from /__sclaude/flow/review
// (sclaude/lib/review/review_map.py):
//
//   across: the files, each column as wide as the root of the lines the
//     development wrote there, grouped by review block when the pull
//     request is read in blocks — a block's name coloured by where it
//     stands at the moment shown, its hover what its rounds cost and found,
//     a click folding it to a sliver (kept per feature);
//   down: the rounds, a line between two, each as tall as the log of its
//     time — an idle night stays visible without taking the panel;
//   a mark: one fix (a hunk) at its line, as wide as it is large — fixes
//     to one place round after round stack into a spike;
//   its hue: how the thread it answered ended (the development's beige
//     where the person asked for it: a `feat` or `Requirement:` commit;
//     mauve where code only moved between files; a dashed edge where the
//     thread is known by nearness alone); its lightness: how many earlier
//     rounds rewrote those lines, weighted by how many; its pattern: the
//     kind of file (tests, schema, docs and config), dots for comments;
//   rows where nothing happened to it: a thin stem; a removed file: a ✕;
//   dots: the threads, where they were posted; ✋ the person, ringed amber
//     where the answer was the recommended one;
//   behind the rows' names, and in a folded block: one icicle summing the
//     files, the development's code left of an axis and the review's own
//     right, and a line for how much each round grew or shrank the code.
const reviewMap = (() => {
  const REVIEW = new Set(['review_run', 'review_close', 'review']);
  const OUT = {
    fixed: [168, 'fixed'], declined: [0, 'declined'], yours: [38, 'left to you'],
    reversal: [6, 'would undo a fix'], open: [222, 'open'],
    side: [210, 'no thread'], moved: [190, 'moved'], asked: [75, 'asked for by the person'],
  };
  const panel = document.getElementById('rv');
  const chip = document.getElementById('rv-chip');
  const body = panel.querySelector('.rv-body');
  let data = null, fetched = 0, drawnKey = '', until = null, ctx = {live: false, sel: null, play: null}, shown = false, loading = null;
  let off = false, drawn = false, placesNow = [], doneOf = () => false, whyOf = () => '';
  // How icicles are drawn: 'fix' joins the files one fix touched; 'file'
  // keeps one icicle a file, splitting where its changes part.
  let mode = 'fix', maxed = false;
  try { mode = localStorage.getItem('review-map-mode') === 'file' ? 'file' : 'fix'; } catch (e) {}
  try { off = localStorage.getItem('review-map-off') === '1'; } catch (e) {}
  // Review blocks folded to a sliver, by id: a click on a block's name.
  let folded = new Set();
  // Per feature: another feature's block 2 is another block.
  const FOLDED = 'review-map-folded:' + label;
  try { folded = new Set(JSON.parse(localStorage.getItem(FOLDED) || '[]')); } catch (e) {}
  let blocksNow = [], roundsShown = [];
  const isReview = (id) => !!id && REVIEW.has((processMap.model.base || {})[id] || id);
  const dark = () => document.documentElement.dataset.theme === 'dark'
    || (document.documentElement.dataset.theme !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  const h = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);
  // Colour is a category, tone a count. The hue says how the thread a fix
  // answered ended — the rare ones that ask for the person (would undo a
  // fix, open, left to you) loud, fixed calm, a fix with
  // no thread a light grey, code moved from one file to another a muted
  // mauve (it is neither a fix nor new code), code the person asked for the
  // development's beige. The lightness says how many earlier rounds of
  // review had already rewritten those lines: 0, 1, 2, 3 or more, darker
  // each (lighter on a dark page) — in equal steps of OKLCH's perceived
  // lightness.
  const HUE = {fixed: [0.16, 180], declined: [0.04, 60], yours: [0.18, 70],
    reversal: [0.22, 27], open: [0.2, 262], side: [0.045, 250], moved: [0.08, 330]};
  const STEPS = 4;
  function colour(outcome, depth) {
    const k = Math.min(STEPS - 1, Math.max(0, depth || 0));
    if (outcome === 'asked') return 'oklch(' + (dark() ? 0.56 + 0.08 * k : 0.74 - 0.08 * k).toFixed(2) + ' 0.09 75)';
    const [c, hue] = HUE[outcome] || HUE.side;
    // No outline: the fill alone carries the shape, so even the lightest
    // step stays well off the lanes' near-white.
    let l = dark() ? 0.56 + 0.1 * k : 0.64 - 0.1 * k;
    return 'oklch(' + l.toFixed(2) + ' ' + c + ' ' + hue + ')';
  }
  // The development's code, before the review or asked for during it.
  function devColour(alpha) {
    return 'oklch(' + (dark() ? 0.56 : 0.74) + ' 0.09 75 / ' + alpha + ')';
  }
  // The summed icicles' line: no hue (the hues are the outcomes'), a
  // lightness by how many threads review posted in its round, k = 0..3.
  function netTone(k) {
    return 'oklch(' + (dark() ? 0.45 + 0.16 * k : 0.74 - 0.17 * k).toFixed(2) + ' 0 0)';
  }
  // What kind of file a fix lands in: each kind a place touched is a
  // pattern of its own over its colour; ordinary code is the solid fill.
  // One primitive each, so that any of them laid over another still reads:
  // tests /, migrations \, docs and config —, comments only ·.
  const patterns = (pre) => '<pattern id="' + pre + '-test" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
    + '<line x1="0" y1="0" x2="0" y2="5" class="rv-hl"/></pattern>'
    + '<pattern id="' + pre + '-schema" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)">'
    + '<line x1="0" y1="0" x2="0" y2="5" class="rv-hl"/></pattern>'
    + '<pattern id="' + pre + '-doc" width="5" height="4" patternUnits="userSpaceOnUse"><line x1="0" y1="0.5" x2="5" y2="0.5" class="rv-hl"/></pattern>'
    + '<pattern id="' + pre + '-comment" width="4" height="4" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="0.9" class="rv-dot"/></pattern>';
  const FLAGS = ['test', 'schema', 'doc', 'comment'];
  function kindOf(path) {
    if (/(\.|_)(test|spec)\.|(^|\/)(tests?|__tests__|e2e|spec)\//.test(path)) return 'test';
    if (/(^|\/)migrations?\/|\.sql$/.test(path)) return 'schema';
    if (/\.(md|mdx|txt|json|ya?ml|toml|ini|cfg)$|(^|\/)\.[^/]+rc$/.test(path)) return 'doc';
    return 'code';
  }
  // A thread's outcome and how it ended: a reversal is one for good, so
  // whether it was left as it is, resolved, and by whom is said beside it.
  function howEnded(t) {
    const by = t.resolvedBy ? ' by ' + t.resolvedBy : '';
    // A fixed thread is resolved by being fixed: only who did it is news.
    if (t.outcome !== 'reversal') return OUT[t.outcome][1] + (t.resolved && (by || t.outcome !== 'fixed') ? ', resolved' + by : '');
    return OUT[t.outcome][1] + (t.left ? ', left as it is' : '') + (t.resolved ? ', resolved' + by : t.left ? '' : ', still open');
  }
  // Where a block stands now: read and closed, read now, still to come.
  function blockState(b) {
    if (!data) return '';
    // Played back to an earlier moment: by the rounds shown — the block of
    // the last is being read, one an earlier round read is done.
    // Played to past the last round of a review that closed: all done.
    if (until != null && !(data.closed && roundsShown.length === data.rounds.length)) {
      const last = roundsShown[roundsShown.length - 1];
      if (!last) return 'wait';
      return last.block === b.id ? 'now' : roundsShown.some((r) => r.block === b.id) ? 'done' : 'wait';
    }
    if (data.closed) return 'done';
    if (data.blockNow == null) return '';
    return b.n < data.blockNow ? 'done' : b.n === data.blockNow ? 'now' : 'wait';
  }
  // 12635 → 12.6K: the header and the notes stay short; lines are said as
  // added and removed, +a −d, wherever the map counts them.
  const kilo = (n) => n < 1000 ? String(n) : (n / 1000).toFixed(n < 100000 ? 1 : 0).replace(/\.0$/, '') + 'K';
  const pm = (a, b) => '+' + kilo(a) + ' −' + kilo(b);
  // What is left of the development's code in a block's files now (blame,
  // review_map.py's `alive`): [wrote, alive, written since, from main].
  function survival(files) {
    const devf = (data.dev && data.dev.files) || {}, al = data.alive || {};
    return files.reduce((a, f) => { const n = al[f] || [0, 0, 0]; return [a[0] + ((devf[f] || {}).add || 0), a[1] + n[0], a[2] + n[1], a[3] + n[2]]; }, [0, 0, 0, 0]);
  }
  const pct = (a, b) => b ? Math.round(100 * a / b) + '%' : '—';
  function leftOf(b) {
    if (!data.alive) return '';
    const [wrote, left, since, main] = survival(b.files);
    if (!wrote && !since) return '';
    return '<div class="t-h">Its files now</div>'
      + '<div class="t-r">the development wrote ' + kilo(wrote) + ', <b>' + kilo(left) + ' of them still there (' + pct(left, wrote) + ')</b></div>'
      + '<div class="t-r">' + kilo(since) + ' written during the review <span class="muted">(fixes and your asks), ' + kilo(main) + ' from main</span></div>';
  }
  // The table of every block, under the panel's title: how much of each
  // block the review rewrote — what the development wrote, what of it is
  // still there, and what was written since.
  function blocksTable() {
    if (!data || !data.rounds.length) return '';
    // Every round's changes summed, as the header's +a −d, with what the
    // person asked for and the code moved between files apart.
    const sum = (f) => data.hunks.filter((x) => x.r < roundsShown.length && f(x)).reduce((a, x) => [a[0] + x.add, a[1] + x.del], [0, 0]);
    const lines = '<div class="t-f">Lines changed during the review, every round summed</div>'
      + [['the review\'s fixes', sum((x) => !x.asked && x.outcome !== 'moved')], ['what you asked for', sum((x) => x.asked)], ['moved between files', sum((x) => !x.asked && x.outcome === 'moved')]]
        .filter(([, v]) => v[0] || v[1]).map(([k, v]) => '<div class="t-r"><b>' + pm(...v) + '</b> ' + k + '</div>').join('');
    if (!data.alive || !(data.blocks || []).length) return lines;
    const rows = data.blocks.map((b) => [b, survival(b.files)]).filter(([, n]) => n[0] || n[2]);
    if (!rows.length) return lines;
    const all = rows.reduce((a, [, n]) => a.map((v, i) => v + n[i]), [0, 0, 0, 0]);
    const tr = (name, n, cls) => '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + name + '</td><td>' + kilo(n[0]) + '</td><td>' + kilo(n[1]) + ' <span class="muted">' + pct(n[1], n[0]) + '</span></td><td>' + kilo(n[2]) + '</td><td>' + kilo(n[3]) + '</td></tr>';
    return lines + '<div class="t-f" style="margin-top:8px">What is left of the development, block by block</div>'
      + '<table class="t-tab"><tr><th>block</th><th>the development wrote</th><th>still there now</th><th>written during the review</th><th>from main</th></tr>'
      + rows.map(([b, n]) => tr(h(b.id), n, blockState(b) === 'now' ? 'on' : '')).join('') + tr('all', all, 'sum') + '</table>'
      + '<div class="t-r muted">By blame on the code as it is now: a line the review rewrote counts once, where the summed changes count it each round. Written during the review takes the fixes and your asks together.</div>';
  }
  // A block hovered: what it is, how big, where it stands, its files' code
  // after the development and what the review changed there, and what its
  // rounds cost and found.
  function blockTip(b) {
    const st = blockState(b);
    const say = {done: 'read and closed', now: 'being read now', wait: 'still to come'}[st] || '';
    const rs = roundsShown.map((r, i) => [r, i]).filter(([r]) => r.block === b.id);
    const idx = new Set(rs.map(([, i]) => i));
    const ths = data.threads.filter((t) => idx.has(t.r) && (until == null || (t.t || 0) * 1000 <= until));
    const by = {};
    ths.forEach((t) => { by[t.outcome] = (by[t.outcome] || 0) + 1; });
    // Added and removed lines of the hunks that pass `f`, as +a −d.
    const sum = (f) => data.hunks.filter((x) => f(x) && x.r < roundsShown.length).reduce((a, x) => [a[0] + x.add, a[1] + x.del], [0, 0]);
    const say3 = (f) => {
      const [own, asked, moved] = [sum((x) => f(x) && !x.asked && x.outcome !== 'moved'), sum((x) => f(x) && x.asked), sum((x) => f(x) && !x.asked && x.outcome === 'moved')];
      return pm(...own) + ' in review fixes' + (asked[0] || asked[1] ? ', ' + pm(...asked) + ' you asked for' : '') + (moved[0] || moved[1] ? ', ' + pm(...moved) + ' moved between files' : '');
    };
    // Its files' code as the development left it, before the first round.
    const inBlock = new Set(b.files);
    const dev = b.files.reduce((a, f) => { const v = ((data.dev || {}).files || {})[f] || {}; return [a[0] + (v.add || 0), a[1] + (v.del || 0), a[2] + (v.code || 0), a[3] + (v.comment || 0)]; }, [0, 0, 0, 0]);
    // Rounds whose fixing was mostly what the person asked for: what they
    // find next is about the new code, not the review closing in.
    const asks = rs.filter(([, i]) => {
      const hs = data.hunks.filter((x) => x.r === i);
      const all = hs.reduce((a, x) => a + x.add + x.del, 0);
      return all && hs.filter((x) => x.asked).reduce((a, x) => a + x.add + x.del, 0) * 2 > all;
    }).map(([, i]) => roundName(i, true));
    const cost = rs.reduce((a, [r]) => a + (r.cost || 0), 0);
    const per = rs.filter(([r]) => !r.stopped).slice(-6).map(([, i]) => data.threads.filter((t) => t.r === i).length);
    const over = b.lines != null && b.lines > data.blockSize;
    // The block it was cut from: 1a from 1, 1a2 from 1a.
    const fromParent = /[a-z]\d+$/.test(b.id) ? b.id.replace(/\d+$/, '') : /[a-z]$/.test(b.id) ? b.id.slice(0, -1) : '';
    return '<div class="t-r muted">' + (folded.has(b.id) ? '▸ — folded: every file of it in one icicle; click to unfold' : '▾ — open: each file of it in its own column; click to fold') + '</div>'
      + '<div class="t-f">Block ' + h(b.id) + ': ' + h(b.title) + '</div>'
      + (say ? '<div class="t-r"><b class="rv-st-' + st + '">' + say + '</b> <span class="muted">— the colour of its name</span></div>' : '')
      + '<div class="t-r">' + (b.lines != null ? '<b' + (over ? ' class="rv-over"' : '') + '>' + b.lines + ' changed lines</b>' + (over ? ' — over the ' + data.blockSize + ' one pass reads whole' : ' of the ' + data.blockSize + ' one pass reads whole')
        + (b.generated ? ' (+' + b.generated + ' generated)' : '') + ' · ' : '') + b.files.length + ' file' + (b.files.length === 1 ? '' : 's')
        + ' · ' + b.criteria.length + (b.criteria.length === 1 ? ' criterion' : ' criteria') + '</div>'
      + '<div class="t-h">Changes to its files</div>'
      + '<div class="t-r">the development: <b>' + pm(dev[0], dev[1]) + '</b></div>'
      + '<div class="t-r">since, every round summed: ' + say3((x) => inBlock.has(x.path)) + '</div>'
      + leftOf(b)
      + (rs.length ? '<div class="t-h">Its rounds</div><div class="t-r">' + rs.length + ' round' + (rs.length === 1 ? '' : 's') + (cost ? ' · $' + cost.toFixed(2) : '')
        + ' · ' + ths.length + ' thread' + (ths.length === 1 ? '' : 's') + (ths.length ? ': ' + Object.entries(by).map(([k, v]) => '<span style="color:' + colour(k, 2) + '">' + v + ' ' + OUT[k][1] + '</span>').join(', ') : '') + '</div>'
        + '<div class="t-r">' + say3((x) => idx.has(x.r)) + '</div>'
        + (per.length > 1 ? '<div class="t-r">threads in its last rounds: ' + per.join(' → ') + '</div>' : '')
        + (asks.length ? '<div class="t-r">rounds that mostly added what you asked for: ' + asks.join(', ')
          + ' <span class="muted">— threads after them are partly about that new code</span></div>' : '')
        : '<div class="t-r muted">No round of its own yet' + (fromParent && fromParent !== b.id ? ' — block ' + h(fromParent) + '\'s rounds read it before the split' : '') + '</div>');
  }
  // A round's name: a pull request read in review blocks counts its rounds
  // afresh in each block, so the block comes first — "Block 2 · round 3";
  // read whole, "Round 3" — both numbered as the review report numbers its
  // rows and its block column (`seq`, `bseq`, rounds_of in review_map.py).
  // `short` is the number alone, for small labels.
  function roundName(i, short) {
    const rs = (data && data.rounds) || [];
    const r = rs[i];
    const n = String(r ? r.seq : i + 1);
    if (!r || !r.block) return short ? n : 'Round ' + n;
    // The pass over the seams after the last block (SEAMS in review_report.py).
    if (r.block === 'seams') return short ? 'seams.' + r.bseq : 'Seams · round ' + r.bseq;
    return short ? r.block + '.' + r.bseq : 'Block ' + r.block + ' · round ' + r.bseq;
  }
  // A round read in a block, its number across the whole review after its
  // name — "Block 3 · round 7 (131)" — the number the review report gives it
  // in the terminal (`seq`). Read whole, the name is that number already.
  function roundSeq(i) {
    const r = ((data && data.rounds) || [])[i];
    return r && r.block ? ' (' + r.seq + ')' : '';
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
    panel.hidden = !show;
    document.body.classList.toggle('rv-open', show);
    // Full screen is the person's choice: it goes with the panel and comes
    // back with it (the player leaving the review and returning), and the
    // page's address keeps it (process_url.js).
    full(show && maxed, true);
    room();
    if (show) { load(); draw(); requestAnimationFrame(centre); }
  }
  // Full screen covers the page: the room kept below it is the half
  // panel's, so the page and the player stand where they were on the way back.
  function full(on, shownOnly) {
    if (!shownOnly) maxed = on;
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
  // The review step's blocks in the middle of what the panel leaves above it:
  // the whole process's map, scrolled inside its card and the page.
  function centre() {
    // Full screen, the page lies under the panel: nothing to bring to the middle.
    if (panel.classList.contains('rv-max')) return;
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
    // Lines added and removed, every round's changes summed; the person's
    // own asks during the review are the development's, counted apart.
    const sum = (xs) => xs.reduce((a, x) => [a[0] + x.add, a[1] + x.del], [0, 0]);
    // A round with no recorded answer draws none of its fixes in the
    // icicles (draw(), below): the header counts as they draw, and names
    // those fixes apart in its note.
    const stopped = (x) => !!(d.rounds[x.r] || {}).stopped;
    const inRounds = d.hunks.filter((x) => x.r < rounds.length);
    const own = inRounds.filter((x) => !x.asked && x.outcome !== 'moved');
    const [rAdd, rDel] = sum(own.filter((x) => !stopped(x)));
    const [sAdd, sDel] = sum(own.filter(stopped));
    const [aAdd, aDel] = sum(inRounds.filter((x) => x.asked));
    const [mAdd, mDel] = sum(inRounds.filter((x) => !x.asked && x.outcome === 'moved'));
    const linesSay = 'Lines the review\'s own fixes added (+) and removed (−), every round\'s changes summed: '
      + 'a spot rewritten in several rounds counts each time; tests, docs and migrations count too.\n'
      + 'What the person asked for during the review (feat and Requirement: commits, beige on the map) and code moved from one file to another (mauve) are counted apart: '
      + 'hover the title, The review, for them.\n\nExactly: +' + rAdd + ' −' + rDel
      + (aAdd || aDel ? '; asked for +' + aAdd + ' −' + aDel : '') + (mAdd || mDel ? '; moved +' + mAdd + ' −' + mDel : '')
      + (sAdd || sDel ? '; after a stopped pass, not drawn in the icicles: +' + sAdd + ' −' + sDel : '');
    const cost = rounds.reduce((a, r) => a + (r.cost || 0), 0);
    const rec = hands.filter((x) => x.rec).length;
    return '<b>PR #' + h(d.pr) + '</b> · ' + rounds.length + ' round' + (rounds.length === 1 ? '' : 's')
      + (cost ? ' · $' + cost.toFixed(2) : '')
      + ' · threads: ' + Object.entries(n).map(([k, v]) => '<span class="rv-k" style="--c:' + colour(k, 1) + '">' + v + ' ' + OUT[k][1] + '</span>').join(' ')
      // The person's asks and moved code are in the title's note, beside
      // the blocks' table: the header stays one line (the user's word).
      + ' · <span class="rv-lines" title="' + h(linesSay) + '">' + pm(rAdd, rDel) + ' in review fixes'
      + (sAdd || sDel ? ' (and ' + pm(sAdd, sDel) + ' after a stopped pass)' : '') + '</span>'
      + ' · ✋ ' + hands.length + (rec ? ' (' + rec + ' recommended)' : '');
  }
  function draw() {
    if (!shown || !data) return;
    // Full screen, no strip is kept for the player (the user's word,
    // 2026-11-17: it took too much of the screen): it floats in the bottom
    // right corner, see-through until the pointer is on it (the CSS), and
    // the rows are fitted to the whole panel.
    // Each poll and each player step asks again; the drawing is rebuilt only
    // when what it is drawn from changed, so the element under the pointer
    // and the scroll stay as they were.
    const key = [fetched, until, mode, panel.classList.contains('rv-nohands'), body.clientWidth, body.clientHeight, dark(), [...folded].join(',')].join('|');
    if (key === drawnKey) return;
    drawnKey = key;
    // The places are numbered afresh: a tooltip kept by number would show
    // another's — unless the pointer is in it, reading or selecting: its
    // text is a snapshot and stays.
    if (hold.busy) hold.detach(); else hold.hide();
    const d = data;
    if (d.error) { body.innerHTML = '<p class="muted rv-wait">' + h(d.error) + '</p>'; return; }
    let rounds = d.rounds;
    if (until != null) rounds = rounds.filter((r) => r.t * 1000 <= until);
    // The cut the review stood under at the moment shown: the last one, or,
    // played back, the one before the split that came after that moment.
    const cutBlocks = ((until != null && (d.earlier || []).find((e) => e.until * 1000 > until)) || d).blocks || [];
    panel.querySelector('.rv-sum').innerHTML = d.rounds.length ? summary(d, rounds) : 'No review round yet';
    if (!rounds.length) { body.innerHTML = '<p class="muted rv-wait">No review round ' + (d.rounds.length ? 'by this moment' : 'yet') + '.</p>'; return; }
    let files = d.files.map((f) => f.path);
    const devf = (d.dev && d.dev.files) || {};
    // Lines of each file at each boundary between rounds: the round's head,
    // and after the last its fixes' end — where a line sits in its file.
    const lines = rounds.map((r) => r.lines).concat([rounds.length < d.rounds.length ? d.rounds[rounds.length].lines : d.final]);
    // The files not there at each boundary: a file the fixes removed is
    // gone from the next one on (an empty file has no lines, but is there).
    const absent = rounds.map((r) => new Set(r.absent || []))
      .concat([new Set((rounds.length < d.rounds.length ? d.rounds[rounds.length].absent : d.absentEnd) || [])]);
    const gone = (k, f) => !!absent[k] && absent[k].has(f);
    // A column a file, as wide as the root of the code the development wrote
    // in it (a file only the review touched: what the review wrote), so a
    // short file still has room for its icicles.
    const reviewed = {};
    d.hunks.forEach((x) => { reviewed[x.path] = (reviewed[x.path] || 0) + x.add + x.del; });
    // A file the review never touched still has a column of its own, at
    // the narrowest width, named and laned like the others — every file its
    // column (the user's rule, 2026-11-18): an unnamed strip read as part of
    // its neighbour's, with that neighbour's marks under it. The room left
    // goes to the files the icicles hang from.
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
    cutBlocks.forEach((b) => b.files.forEach((f) => { if (!(f in cutOf)) cutOf[f] = b.n; }));
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
    cutBlocks.forEach((b) => b.files.forEach((f) => { if (!(f in blockOf)) blockOf[f] = b.n; }));
    const hasBlocks = cutBlocks.length > 0;
    if (hasBlocks) {
      const rank = (f) => (blockOf[f] || 999) * 2 + (touched.has(f) ? 0 : 1);
      files = files.map((f, i) => [f, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0]);
    }
    // A folded block keeps a sliver: its files share FOLD pixels, no gaps.
    const FOLD = 30;
    const idOfN = {};
    cutBlocks.forEach((b) => { idOfN[b.n] = b.id; });
    blocksNow = cutBlocks;
    roundsShown = rounds;
    const isFold = (f) => hasBlocks && folded.has(idOfN[blockOf[f]]);
    const foldN = {};
    files.forEach((f) => { if (isFold(f)) foldN[blockOf[f]] = (foldN[blockOf[f]] || 0) + 1; });
    const weight = files.map((f) => touched.has(f) && !isFold(f)
      ? Math.max(...stackOf(f).map((g) => Math.sqrt(Math.max(1, (devf[g] || {}).add || reviewed[g] || 1)))) : 0);
    // Each round's time, to the next one or to now.
    const now = until != null ? until / 1000 : Date.now() / 1000;
    rounds.forEach((r, i) => {
      const next = i + 1 < d.rounds.length ? d.rounds[i + 1].t : now;
      r._len = Math.max(r.seconds || 0, Math.min(next, now) - r.t);
    });
    // The margin keeps its width: a long name runs under the ✋ of the
    // round's answers, which is drawn over it (the user's word, 2026-11-19).
    const measure = document.createElement('canvas').getContext('2d');
    measure.font = '700 11.5px ' + getComputedStyle(body).fontFamily;
    const GUT = 176, HEAD = hasBlocks ? 92 : 74, GAP = 2, BGAP = 8, MINW = 14, width = Math.max(320, body.clientWidth - 8);
    const total = weight.reduce((a, w) => a + w, 0) || 1;
    const groupsN = hasBlocks ? new Set(files.map((f) => blockOf[f] || 999)).size : 1;
    const open_ = files.filter((f) => !isFold(f));
    const avail = width - GUT - 8 - GAP * open_.length - BGAP * (groupsN - 1) - MINW * open_.filter((f) => !touched.has(f)).length
      - (FOLD + GAP) * Object.keys(foldN).length;
    const cols = [], groups = [];
    let cx = GUT;
    files.forEach((f, i) => {
      const g = hasBlocks ? blockOf[f] || 999 : 0;
      if (!groups.length || groups[groups.length - 1].g !== g) {
        if (groups.length) cx += BGAP;
        groups.push({g: g, x0: cx, x1: cx});
      }
      // A folded block is one column: every file of it spans the whole
      // sliver, its places laid over the others' — the block's summary,
      // not its files cut to a pixel each.
      const fold = isFold(f), grp = groups[groups.length - 1];
      if (fold && grp.fold) { cols.push([grp.x0, FOLD]); return; }
      if (fold) grp.fold = true;
      const w = fold ? FOLD : touched.has(f) ? Math.max(MINW, avail * weight[i] / total) : MINW;
      cols.push([cx, w]); cx += w + GAP;
      grp.x1 = cx - GAP;
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
    const tall = (s) => 34 + 24 * Math.log2(1 + Math.max(0, s) / 300);
    const devLen = d.dev && d.dev.t ? rounds[0].t - d.dev.t : 0;
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
    const room = Math.max(ROWMIN * 2, body.clientHeight - coming - HEAD - BOTTOM);
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
      '<defs>' + patterns('rv-p') + '</defs>'];
    // The blocks' names and the files' names: a strip of their own, held
    // at the top while the rounds scroll under it (the user's word,
    // 2026-11-17); it scrolls sideways with the map.
    const head = [];
    // The lanes, and on top all the code the development wrote: each file's
    // block, darker where the pull request changed it.
    let devAdd = 0, lane = 0;
    // Where a column goes on in another file: drawn over the icicles, below.
    const nexts = [];
    const foldLane = new Set();
    files.forEach((f, i) => {
      const c = cols[i], dv = devf[f] || {add: 0, code: 0, comment: 0, regions: []};
      devAdd += dv.add;
      // A folded block: one lane, no names (its header names the block);
      // its development is the top of its summed icicle, below.
      if (isFold(f)) {
        if (!foldLane.has(c[0])) {
          foldLane.add(c[0]);
          lane = (lane + 1) % 2;
          svg.push('<rect class="rv-col' + (lane ? ' odd' : '') + '" x="' + c[0].toFixed(1) + '" y="' + top + '" width="' + c[1].toFixed(1) + '" height="' + (H - top - 6) + '"/>');
        }
        return;
      }
      // A lane, alternating, for every file: where one column ends and the
      // next begins is always seen.
      lane = (lane + 1) % 2;
      svg.push('<rect class="rv-col' + (lane ? ' odd' : '') + '" x="' + c[0].toFixed(1) + '" y="' + top + '" width="' + c[1].toFixed(1) + '" height="' + (H - top - 6) + '"/>');
      // A file the development did not write: nothing above it.
      if (dv.add) svg.push('<g class="rv-dev" data-tip-mark="' + devColour(1) + '"><title>▬ — the development\'s code, written before the review; the stronger stripes, where in the file its lines are\n' + h(f) + ' — +' + dv.add + ' lines (' + dv.code + ' code, ' + dv.comment + ' comment)</title>'
        + '<rect x="' + c[0].toFixed(1) + '" y="' + top + '" width="' + c[1].toFixed(1) + '" height="' + bandH.toFixed(1) + '" fill="' + devColour(0.45) + '"/>'
        + (dv.proj && axisOf[f] ? dv.proj.map(([a, b]) => [a, b, true]) : dv.regions).map(([x, n, onAxis]) => {
          const x0 = onAxis ? ax(f, x) : at(0, f, x);
          const x1 = Math.max(x0 + 1, onAxis ? ax(f, n) : at(0, f, x + n));
          return '<rect x="' + x0.toFixed(1) + '" y="' + top + '" width="' + (x1 - x0).toFixed(1) + '" height="' + bandH.toFixed(1) + '" fill="' + devColour(1) + '"/>';
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
      head.push('<g class="rv-file' + (touched.has(f) ? '' : ' rv-quiet') + '"><title>' + h(stack.join('\n↓ ')) + (stack.length > 1 ? '\n\n↓ — the fixes moved on from one file to the next: each goes on under the one before, in this column.' : '')
        + (touched.has(f) ? '' : '\n\nThe review fixed nothing here and posted no thread.')
        + '</title><text transform="translate(' + tx.toFixed(1) + ',' + ty.toFixed(1) + ') rotate(-55)">'
        + lines.map((l, k) => '<tspan x="0"' + (k ? ' dy="' + LH + '"' : '') + '>' + h(l) + '</tspan>').join('') + '</text></g>');
      // Where the column goes on in the next file: a line across it, and
      // the file's name.
      stack.slice(1).forEach((g) => {
        const y = ys[split[g]];
        if (y == null) return;
        const nm = g.split('/').pop();
        nexts.push('<g class="rv-next"><title>↓ — the column goes on in the next file: from here it is ' + h(g) + ': the fixes of ' + h(before[g]) + ' went on there</title>'
          + '<line x1="' + c[0].toFixed(1) + '" x2="' + (c[0] + c[1]).toFixed(1) + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '"/>'
          + '<text x="' + (c[0] + 2).toFixed(1) + '" y="' + (y - 2).toFixed(1) + '">↓ ' + h(nm.length > Math.max(4, c[1] / 5.5) ? nm.slice(0, Math.max(3, Math.floor(c[1] / 5.5))) + '…' : nm) + '</text></g>');
      });
    });
    // The blocks: a line between two, and each one's name over its files.
    if (hasBlocks) groups.forEach((g, k) => {
      const b = cutBlocks.find((x) => x.n === g.g);
      const name = b ? 'Block ' + b.id : 'Not in the cut';
      const full = b ? name + ': ' + b.title : 'Files the cut does not name — written after it';
      const room = Math.max(0, Math.floor((g.x1 - g.x0) / 6.2));
      const fold = b && folded.has(b.id);
      const label = fold ? '▸' + b.id : room < 3 ? '' : ((b ? '▾ ' : '') + name + (b && room > name.length + 6 ? ' · ' + b.title : '')).slice(0, room);
      const st = b ? blockState(b) : '';
      head.push('<g class="rv-bk' + (st ? ' rv-bk-' + st : '') + '"' + (b ? ' data-n="' + b.n + '"' : '') + '>' + (b ? '' : '<title>' + h(full) + '</title>')
        + '<rect x="' + g.x0.toFixed(1) + '" y="2" width="' + Math.max(1, g.x1 - g.x0).toFixed(1) + '" height="16" rx="3"/>'
        + '<text x="' + (g.x0 + 4).toFixed(1) + '" y="14">' + h(label) + '</text></g>');
      if (k) [svg, head].forEach((to) => to.push('<line class="rv-bsep" x1="' + (g.x0 - BGAP / 2).toFixed(1) + '" x2="' + (g.x0 - BGAP / 2).toFixed(1) + '" y1="2" y2="' + (to === head ? HEAD : H) + '"/>'));
    });
    // The summary icicle goes here, behind the rows' names, once the
    // places below say how much each round changed.
    const sumAt = svg.length;
    svg.push('<text class="rv-rt" x="6" y="' + (top + 15) + '">Development' + (devLen ? '<tspan class="rv-dur"> · ' + dur(devLen) + '</tspan>' : '') + '</text>');
    if (two(0)) svg.push('<text class="rv-rs" x="6" y="' + (top + 29) + '">+' + devAdd + ' lines</text>');
    // The rounds: a line, and what each was.
    rounds.forEach((r, i) => {
      // A new block: a heavier line.
      const opens = r.block && (!i || rounds[i - 1].block !== r.block);
      svg.push('<line class="rv-round' + (opens && i ? ' rv-block' : '') + '" x1="0" x2="' + W + '" y1="' + ys[i] + '" y2="' + ys[i] + '"/>');
      // Round n of the review, the block of the pull request it read when
      // it was read in blocks, how long until the next round, where it ran,
      // what it found and what the conversations in it cost.
      svg.push('<g class="rv-rl"><title>' + roundName(i) + roundSeq(i) + (r.block ? '\nThe pull request is read in review blocks: each block counts its rounds from 1; in brackets, the round\'s number across the whole review, as the review report numbers it' : '')
        + '\n' + dur(r._len) + ' until ' + (i + 1 < d.rounds.length ? 'the next round' : 'now')
        + '\nThe review ran ' + (r.source === 'github' ? 'on GitHub, in the project\'s workflow' : 'on this machine')
        + (r.stopped ? '\nStopped: the pass left no recorded answer, so it found and read nothing that counts; the commits after it are its fixes' : '')
        + (r.new != null ? '\n' + r.new + ' new finding' + (r.new === 1 ? '' : 's') : '')
        + (r.cost ? '\n$' + r.cost.toFixed(2) + ': its passes and the fixes of what it found, as the review report prices them' : '')
        + (r.seen ? '\nOpened ' + r.seen.length + ' of the ' + files.length + ' files on the map (pale icicles: code it never opened)' : r.source === 'github' ? '\nWhat a GitHub run read is not known here' : '')
        + '\n\nBehind the name, every file summed in one icicle: left of its axis the development\'s code this round touched, right the review\'s own, coloured by how their threads ended; the line leans right where the round grew the code, left where it shrank it, ' + (dark() ? 'lighter' : 'darker') + ' the more threads it posted' + '</title>'
        + '<text class="rv-rt" x="6" y="' + (ys[i] + 15) + '">' + roundName(i) + (r.block ? '<tspan class="rv-seq">' + roundSeq(i) + '</tspan>' : '') + '<tspan class="rv-dur"> · ' + dur(r._len) + '</tspan></text>'
        + (two(i + 1) ? '<text class="rv-rs" x="6" y="' + (ys[i] + 29) + '">' + (r.stopped ? 'stopped, no answer' : r.source === 'github' ? 'on GitHub' : 'on this machine')
          + (r.new != null ? ' · ' + r.new + ' found' : '') + (r.cost ? ' · $' + r.cost.toFixed(2) : '') + '</text>' : '') + '</g>');
    });
    const rowsEnd = svg.length;
    // Where a block was split: a line across the map at the first round
    // after it, naming the block and its parts; a click tells the story.
    (d.earlier || []).forEach((e, j) => {
      const i = rounds.findIndex((r) => r.t >= e.until);
      if (i < 0) return;
      const next = (d.earlier[j + 1] || d).blocks || [];
      // Its parts' ids: letters after a block named by a number, numbers
      // after one named by a letter (review_blocks.py split) — block 10 is
      // no part of block 1.
      const tail = /\d$/.test(e.split) ? /^[a-z]$/ : /^\d+$/;
      const parts = next.filter((b) => b.id.startsWith(e.split) && tail.test(b.id.slice(e.split.length))).map((b) => b.id);
      svg.push('<g class="rv-cut" data-cut="' + j + '" data-r="' + i + '"><title>✂ — a block split: block ' + h(e.split) + ' split into ' + h(parts.join(', '))
        + ' before this round: click for what happened</title>'
        + '<line x1="0" x2="' + W + '" y1="' + ys[i] + '" y2="' + ys[i] + '"/>'
        + '<rect x="0" y="' + (ys[i] - 13) + '" width="' + W + '" height="17"/>'
        + '<text x="' + (GUT + 4) + '" y="' + (ys[i] - 3) + '">✂ block ' + h(e.split) + ' → ' + h(parts.join(' · ')) + '</text></g>');
    });
    // The icicles. A round's fixes close together in one file are one
    // place, and places in two files join when they are one fix (one
    // thread, or one subagent's work): an icicle widens when
    // the round draws another file in. A place hangs
    // from the places of the fixes it grows from (review_map.py's lineage:
    // one problem's line of descent, cut where a round read it and found
    // nothing), or from the development's block; a file the development
    // did not write has nothing above it, and its place starts at its own width. Each file's share
    // of the width is its column's times sqrt(changed / written), so an
    // icicle narrows as fewer of that code's lines are touched, and grows
    // again when a round touches more. A place no later round comes back to
    // ends in a point.
    const places = rounds.map(() => []);
    // Each fix's place, for the places that grow from it.
    const placeOf = new Map();
    const f1 = (n) => n.toFixed(1);
    // Rows where nothing happened to an icicle's code are a stem STEM wide
    // (or the icicle's own width, if narrower), reached through a neck that
    // narrows over a few pixels: the eye goes to the rows with fixes.
    const STEM = 2.4;
    const stem = (a, b) => b - a <= STEM ? [a, b] : [(a + b) / 2 - STEM / 2, (a + b) / 2 + STEM / 2];
    const neck = (a, b, top, bottom) => {
      const [c, e] = stem(a, b), y = Math.min(bottom, top + Math.min(6, (bottom - top) / 3));
      return 'M' + f1(a) + ',' + f1(top) + ' L' + f1(b) + ',' + f1(top) + ' L' + f1(e) + ',' + f1(y) + ' L' + f1(e) + ',' + f1(bottom)
        + ' L' + f1(c) + ',' + f1(bottom) + ' L' + f1(c) + ',' + f1(y) + 'Z ';
    };
    // How many earlier rounds' fixes had already rewritten each fix's spot —
    // the review going over its own work. Lines the person asked for are
    // the development's and count for none.
    {
      const byPath = {};
      d.hunks.forEach((x) => { if (!x.asked && x.p0 != null && !(d.rounds[x.r] || {}).stopped) (byPath[x.path] = byPath[x.path] || []).push(x); });
      d.hunks.forEach((x) => {
        const seen = new Set();
        if (x.p0 != null) (byPath[x.path] || []).forEach((y) => { if (y.r < x.r && y.p0 < x.p1 && y.p1 > x.p0) seen.add(y.r); });
        x.depth = seen.size;
        // How many of its lines are the review's own: the share of its
        // span that earlier rounds' fixes had already written or rewritten.
        // The rest is the development's code — the person's asks included,
        // and a hunk off the axis, which has no span to compare (its depth
        // is 0).
        const v = Math.max(x.add, x.del);
        if (x.asked || !x.depth) { x.own = 0; return; }
        const spans = (byPath[x.path] || []).filter((y) => y.r < x.r && y.p0 < x.p1 && y.p1 > x.p0)
          .map((y) => [Math.max(x.p0, y.p0), Math.min(x.p1, y.p1)]).sort((a, b) => a[0] - b[0]);
        let cov = 0, end = x.p0;
        spans.forEach(([a, b]) => { if (b > end) { cov += b - Math.max(a, end); end = b; } });
        x.own = Math.round(v * cov / (x.p1 - x.p0));
      });
    }
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
          // Never across a folded block's edge: its places are its icicle's.
          const fa = files[b.ci], fb = files[run ? run.ci1 : b.ci];
          const apart = (isFold(fa) || isFold(fb)) && blockOf[fa] !== blockOf[fb];
          if (run && !apart && b.ci - run.ci1 <= 1 && b.ci !== run.bits[run.bits.length - 1].ci) {
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
        // The review's own lines vote for the outcome; the person's asks
        // take their share of the fill beside it (askedShare), so a place
        // both the development and a fix wrote shows both, in proportion.
        const by = {};
        p.flags = new Set();
        let codeLines = 0, inCode = 0, asked = 0;
        p.hs.forEach((x) => {
          const n = x.add + x.del;
          if (x.asked) asked += n;
          else by[x.outcome] = (by[x.outcome] || 0) + n + (x.outcome === 'side' || x.outcome === 'moved' ? 0 : 1000);
          const k = kindOf(x.path);
          if (k !== 'code') p.flags.add(k);
          else { inCode++; codeLines += x.code; }
        });
        // Ordinary code or a migration changed — what the product does: a
        // solid fill; only comments, tests, docs or config: hollow, the
        // program itself did not change here (the user's word, 2026-11-17:
        // a migration changes the schema, so it is code).
        p.solid = codeLines > 0 || p.flags.has('schema');
        if (inCode && !codeLines) p.flags.add('comment');
        p.askedShare = p.changed ? asked / p.changed : 0;
        p.outcome = Object.entries(by).sort((a, b) => b[1] - a[1])[0]?.[0] || 'asked';
        // Its thread known only by nearness: no reply named the commit and
        // no subagent was given it — a fair guess, drawn as one.
        const tied = p.hs.filter((x) => !x.asked && x.thread);
        p.guess = tied.length > 0 && tied.every((x) => x.via === 'near');
        // How often review had already rewritten these lines, weighted by
        // how many of them it had: one rewritten line among a hundred new
        // ones leaves the place light.
        const span = p.hs.reduce((a, x) => a + (x.asked ? 0 : Math.max(x.add, x.del)), 0);
        p.depth = span ? Math.round(p.hs.reduce((a, x) => a + (x.depth || 0) * (x.own || 0), 0) / span) : 0;
        p.maxDepth = Math.max(0, ...p.hs.filter((x) => !x.asked).map((x) => x.depth));
        p.movedFrom = [...new Set(p.hs.flatMap((x) => x.movedFrom || []))];
        p.movedTo = [...new Set(p.hs.flatMap((x) => x.movedTo || []))];
        // Each file's share of the width, side by side.
        const perFile = {};
        p.bits.forEach((b) => { perFile[b.f] = (perFile[b.f] || 0) + b.hs.reduce((a, x) => a + x.add + x.del, 0); });
        p.files = Object.keys(perFile);
        p.lo = cols[p.ci0][0]; p.hi = cols[p.ci1][0] + cols[p.ci1][1];
        p.dev = p.files.some((f) => (devf[f] || {}).add);
        // It hangs from the places of the fixes it grows from
        // (review_map.py's lineage: the thread it answers was posted on
        // their lines, or it rewrote them, and their chain was not closed
        // yet), in its own files, however many rounds above — rounds that
        // left that code alone are bridged. Two or more is a merge, and a
        // place two of this round hang from splits. Nearness says nothing:
        // a fix beside a closed icicle starts its own.
        // A file with no axis (a rename, a binary) has no lineage: there it
        // hangs from the nearest round above whose code overlaps, give or
        // take a third of its narrowest column.
        p.hs.forEach((x) => placeOf.set(x, p));
        const from = new Set(p.hs.flatMap((x) => x.from || []).map((k) => d.hunks[k])
          .filter((y) => y && p.files.includes(y.path)));
        p.ups = [...new Set([...from].map((y) => placeOf.get(y)).filter((q) => q && q.ri !== ri))];
        // Code moved here from another file grows from the fixes that wrote
        // it there: joined below, as a stream or a jump, once every place
        // knows the places hanging from it.
        const away = new Set(p.hs.flatMap((x) => (x.from || []).map((k) => d.hunks[k])
          .filter((y) => y && (x.movedFrom || []).includes(y.path) && !p.files.includes(y.path))));
        p.moveUps = [...new Set([...away].map((y) => placeOf.get(y)).filter((q) => q && q.ri !== ri))];
        const loose = p.files.filter((f) => !axisOf[f]);
        if (loose.length) {
          // Measured from its part in those files alone, not the whole place.
          const own = p.bits.filter((b) => loose.includes(b.f));
          const x0 = Math.min(...own.map((b) => b.x0)), x1 = Math.max(...own.map((b) => b.x1));
          const reach = Math.min(...loose.map((f) => cols[fi[f]][1])) * 0.3;
          let near = [];
          for (let k = ri - 1; k >= 0 && !near.length; k--) {
            near = places[k].filter((q) => q.bits.some((b) => loose.includes(b.f)
              && Math.min(b.x1, x1 + reach) - Math.max(b.x0, x0 - reach) > 0));
          }
          near.forEach((q) => { if (!p.ups.includes(q)) p.ups.push(q); });
        }
        p.ri = ri;
      });
    });
    // The width at a round's bottom is the lines the round changed there, on
    // one scale for the whole map: the scale at which four places in five
    // fit the columns they stand in; the rest are held to their columns.
    const all = places.flat();
    const fits = all.filter((p) => !p.files.every(isFold)).map((p) => (p.hi - p.lo) / Math.max(1, p.changed)).sort((a, b) => a - b);
    const scale = fits.length ? fits[Math.floor(fits.length * 0.2)] : 1;
    all.forEach((p) => {
      p.w = Math.min(p.hi - p.lo, Math.max(3, p.changed * scale));
      p.cx = Math.min(p.hi - p.w / 2, Math.max(p.lo + p.w / 2, (p.x0 + p.x1) / 2));
      p.l = p.cx - p.w / 2; p.r = p.cx + p.w / 2;
    });
    // A summed icicle — the one behind the rows' names, of the whole pull
    // request, and a folded block's, of its files. Right of its axis is the
    // review's own code, left the development's, on both of its channels:
    // - the body: the development's lines on top, all left; then each row
    //   the lines the round touched (a fix's larger side), left those of
    //   the development, right those earlier rounds had already written,
    //   each side on a square-root scale and split outward from the axis
    //   by how their threads ended;
    // - a line, on the same scale: how far the round grew the code (added
    //   minus deleted, the person's asks left out) — right grown, left
    //   shrunk; darker (lighter on a dark page) the more threads review
    //   posted there in the round (0, 1–2, 3–5, 6+), the person's own not
    //   counted.
    function summed(hunk, thread, dev, lo, hi, cls, title) {
      const per = rounds.map((r, ri) => {
        const row = {L: 0, R: 0, net: 0, outL: {}, outR: {}, th: 0};
        d.hunks.forEach((x) => {
          if (x.r !== ri || !hunk(x)) return;
          const k = x.asked ? 'asked' : x.outcome, v = Math.max(x.add, x.del), own = Math.min(v, x.own || 0);
          row.L += v - own; row.R += own;
          row.outL[k] = (row.outL[k] || 0) + v - own;
          row.outR[k] = (row.outR[k] || 0) + own;
          if (!x.asked) row.net += x.add - x.del;
        });
        row.th = d.threads.filter((t) => t.r === ri && t.by !== 'person' && thread(t) && (until == null || t.t * 1000 <= until)).length;
        return row;
      });
      const most = Math.max(1, dev, ...per.map((r) => Math.max(r.L, r.R, Math.abs(r.net))));
      const half = (hi - lo) / 2 - 2, mid = (lo + hi) / 2;
      const wOf = (v) => v ? Math.max(1, half * Math.sqrt(v / most)) : 0;
      const out = ['<g class="' + cls + '">' + (title ? '<title>' + title + '</title>' : '')];
      if (dev) out.push('<rect x="' + f1(mid - wOf(dev)) + '" y="' + top + '" width="' + f1(wOf(dev)) + '" height="' + f1(ys[0] - top) + '" fill="' + devColour(1) + '"/>');
      let pL = wOf(dev), pR = 0;
      per.forEach((r, i) => {
        const y0 = ys[i], y1 = ys[i + 1], L = wOf(r.L), R = wOf(r.R);
        // After rounds that left a side alone it starts at its own width:
        // a point would read as code written there.
        if (!pL) pL = L;
        if (!pR) pR = R;
        [[-1, pL, L, r.outL, r.L], [1, pR, R, r.outR, r.R]].forEach(([side, w0, w1, o, sum]) => {
          let a = 0;
          Object.keys(OUT).filter((k) => o[k]).forEach((k) => {
            const b = a + o[k] / sum;
            out.push('<path d="M' + f1(mid + side * w0 * a) + ',' + f1(y0) + ' L' + f1(mid + side * w0 * b) + ',' + f1(y0)
              + ' L' + f1(mid + side * w1 * b) + ',' + f1(y1) + ' L' + f1(mid + side * w1 * a) + ',' + f1(y1) + 'Z" fill="' + colour(k, 1) + '"/>');
            a = b;
          });
        });
        pL = L; pR = R;
      });
      out.push('</g>');
      const body = out.join('');
      out.length = 0;
      out.push('<g class="rv-net">');
      // Only over the rounds that did something here: through rows where
      // nothing happened, a line on the axis would read as a stem — the
      // review still at work here (a folded block whose rounds are over).
      const busy = per.map((r) => !!(r.L || r.R || r.net || r.th));
      const first = busy.indexOf(true);
      // The axis too, run by run of busy rounds.
      busy.forEach((b, i) => {
        if (!b || (i && busy[i - 1])) return;
        let e = i;
        while (e + 1 < busy.length && busy[e + 1]) e++;
        out.push('<line class="rv-axis" x1="' + f1(mid) + '" x2="' + f1(mid) + '" y1="' + f1(ys[i]) + '" y2="' + f1(ys[e + 1]) + '"/>');
      });
      let px = mid, py = first > 0 ? ys[first] : ys[0];
      per.forEach((r, i) => {
        const x = mid + Math.sign(r.net) * wOf(Math.abs(r.net)), y = (ys[i] + ys[i + 1]) / 2;
        const k = !r.th ? 0 : r.th <= 2 ? 1 : r.th <= 5 ? 2 : 3;
        if (busy[i] || (i && busy[i - 1])) {
          // Into a quiet row it goes back to the axis and stops there.
          const [ex, ey] = busy[i] ? [x, y] : [mid, ys[i]];
          out.push('<line x1="' + f1(px) + '" y1="' + f1(py) + '" x2="' + f1(ex) + '" y2="' + f1(ey) + '" stroke="' + netTone(busy[i] ? k : 0) + '"/>');
        }
        if (!busy[i] && i + 1 < per.length && busy[i + 1]) { px = mid; py = ys[i + 1]; } else { px = x; py = y; }
      });
      return [body, out.join('') + '</g>'];
    }
    // The body under the rounds' names, which have a halo to read over
    // it; the line over them, thin enough not to hide a word.
    const [sumBody, sumNet] = summed((x) => fi[x.path] != null, (t) => fi[t.path] != null, devAdd, 0, GUT - 4, 'rv-sumi', '');
    // The rounds' names held at the left while the map scrolls sideways
    // (the user's word, 2026-11-17): as wide as the longest name, so the
    // durations after it stay on the map and scroll away; the summed
    // icicle drawn again to that width behind them.
    const pinW = Math.min(GUT, Math.ceil(Math.max(measure.measureText('Development').width, ...rounds.map((r, i) => measure.measureText(roundName(i)).width))) + 12);
    const [pinBody, pinNet] = summed((x) => fi[x.path] != null, (t) => fi[t.path] != null, devAdd, 0, pinW - 4, 'rv-sumi', '');
    const pin = '<rect class="rv-headbg" x="0" y="' + top + '" width="' + pinW + '" height="' + (H - top) + '"/>' + pinBody + svg.slice(sumAt, rowsEnd).join('') + pinNet
      + '<line class="rv-pinedge" x1="' + (pinW - 0.5) + '" x2="' + (pinW - 0.5) + '" y1="' + top + '" y2="' + H + '"/>';
    svg.splice(sumAt, 0, sumBody);
    svg.push(sumNet);
    // For the hover: each place's round, the places that hang from it, the
    // threads posted at it in its round and your answers about them.
    const flat = [];
    places.forEach((ps, ri) => ps.forEach((p) => {
      p.ri = ri; p.kids = []; p.id = flat.length; flat.push(p);
      // A place inside a folded block is not drawn: a link to it opens the block.
      p.foldId = p.files.every(isFold) ? idOfN[blockOf[p.files[0]]] || '' : '';
    }));
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
      // Where it was posted: the place of the fix that wrote its line; off
      // the axis, the latest place near it.
      const src = t.p != null ? (t.of != null ? placeOf.get(d.hunks[t.of]) : null)
        : flat.filter((q) => q.ri < t.r && q.files.includes(t.path) && x >= q.x0 - reach && x <= q.x1 + reach)
          .sort((a, b) => b.ri - a.ri)[0];
      // Posted on the development's lines (no fix wrote them), it has no
      // place to come from: the fix there starts its own icicle, and the
      // thread is still that place's, for the hover.
      // Into its own column or the next it is drawn as a stream; further
      // away a stream would read as a line through other files' icicles, so
      // it jumps: a mark where it leaves and one where it lands, each a link
      // to the other. Either way the chain goes on there.
      places[fx.r] && places[fx.r].forEach((q) => {
        if (q === src || !q.files.some((f) => fx.files.includes(f))) return;
        // Out of a folded block nothing goes: its places are not drawn. Into
        // one, never a stream, whose kid would not be drawn: a jump, whose
        // mark opens the block (`data-unfold`).
        // The thread is still the place's (below) whatever is folded.
        if (src && !src.files.every(isFold)) {
          if (!q.files.every(isFold) && q.files.some((f) => fx.files.includes(f) && Math.abs(fi[f] - fi[t.path]) <= 1)) {
            if (!q.ups.includes(src)) { q.ups.push(src); src.kids.push(q); }
          } else {
            q.jin = q.jin || []; src.jout = src.jout || [];
            if (!q.jin.includes(src)) { q.jin.push(src); src.jout.push(q); }
            (src.joutBy = src.joutBy || new Map()).set(q, t);
          }
        }
        if (!q.th.includes(t)) q.th.push(t);
        q.slid = q.slid || [];
        q.slid.push(t.path);
      });
    });
    // Code moved from another file: the place hangs from the places that
    // wrote it there — a stream into its own column or the next, a jump
    // further away, as a fix that slid there by its reply.
    flat.forEach((q) => (q.moveUps || []).forEach((src) => {
      if (src.files.every(isFold) || q.ups.includes(src)) return;
      if (!q.files.every(isFold) && q.files.some((f) => src.files.some((g) => Math.abs(fi[f] - fi[g]) <= 1))) {
        q.ups.push(src); src.kids.push(q);
      } else if (!(q.jin || []).includes(src)) {
        (q.jin = q.jin || []).push(src); (src.jout = src.jout || []).push(q);
        (src.joutMoved = src.joutMoved || new Set()).add(q);
      }
    }));
    flat.forEach((p) => {
      const rids = new Set(p.th.map((t) => t.rid).filter(Boolean));
      p.hd = d.hands.filter((x) => x.rid && rids.has(x.rid));
    });
    // A place's bottom shared among the places that hang from it: in its
    // own file each takes the part above where its code is (the width is a
    // place in the file, so a narrow fix under a wide one starts narrow, at
    // its spot); one in another file — a fix that slid there — takes a share
    // of what is left, in proportion to its width.
    flat.forEach((q) => {
      q.kids.sort((a, b) => a.cx - b.cx);
      q.slice = new Map();
      const map = (x) => q.l + q.w * (q.x1 > q.x0 ? Math.min(1, Math.max(0, (x - q.x0) / (q.x1 - q.x0))) : 0.5);
      const away = [];
      q.kids.forEach((k) => {
        if (!k.files.some((f) => q.files.includes(f))) { away.push(k); return; }
        let a = map(k.x0), b = map(k.x1);
        if (b - a < 1.5) { const c = (a + b) / 2; a = c - 0.75; b = c + 0.75; }
        q.slice.set(k, [a, b]);
      });
      const sum = away.reduce((a, k) => a + k.w, 0) || 1;
      let x = q.l;
      away.forEach((k) => { const s = [x, x + q.w * k.w / sum]; x = s[1]; q.slice.set(k, s); });
    });
    placesNow = flat;
    // A chain is done when every thread of it (if any) has an outcome (none
    // open, none waiting for the person), and the round after its last fix
    // read all of it (no pass stopped at its cap) and posted no new thread
    // there; code no thread led to closes the same way (why(), below).
    // A reversal is settled once it was left as it is or resolved; before,
    // it waits for the person like an open thread.
    const settled = (t) => t.outcome === 'fixed' || t.outcome === 'declined' || (t.outcome === 'reversal' && (t.left || t.resolved));
    const ownerNow = {};
    (d.blocks || []).forEach((b) => b.files.forEach((f) => { ownerNow[f] = b.n; }));
    function chain(p) {
      const all = new Set([p]), todo = [p];
      while (todo.length) { const p_ = todo.shift(); p_.ups.concat(p_.jin || []).forEach((q) => { if (!all.has(q)) { all.add(q); todo.push(q); } }); }
      return [...all];
    }
    // Threads a later round posted on the lines a place's fixes wrote
    // (review_map.py's `of`) where no fix of that round landed — fixed
    // elsewhere (a new migration, a caller), or not yet — are still the
    // place's: its chain goes on through them, and the round that reads
    // past the last of them is the one that checks it. Off the axis, the
    // threads near it, as before there was a blame.
    const inPlace = new Set(flat.flatMap((q) => q.th));
    function later(p) {
      const reach = Math.min(...p.files.map((f) => cols[fi[f]][1])) * 0.3;
      return d.threads.filter((t) => t.r != null && t.r > p.ri && t.r < rounds.length && !inPlace.has(t)
        && p.files.includes(t.path) && (t.p != null ? t.of != null && p.hs.includes(d.hunks[t.of])
          : threadX(t) >= p.x0 - reach && threadX(t) <= p.x1 + reach));
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
      // Its files removed by the fixes of its last round (its own, or a
      // move's other side): nothing is left there to read. It ends in its
      // row, marked with a ✕ either way, and is over once its threads have
      // their outcomes; a round that names a removed file has not read it.
      if (p.files.every((f) => gone(p.lastR + 1, f))) {
        p.goneAt = p.lastR + 1;
        const ths = chain(p).flatMap((q) => q.th).concat(orph);
        if (!ths.every(settled)) return orph.some((t) => !settled(t)) ? 'elsewhere' : 'open';
        return 'gone';
      }
      // The round that checks it: the first after its last fix or thread
      // that opened its files still there. A round that never opened them
      // found nothing there by not looking (review_map.py's seen; unknown
      // for a GitHub run, which leaves no transcript here, and taken as
      // read): the icicle goes on through it — still to be checked.
      const opened = (k) => !rounds[k].seen || p.files.every((f) => gone(k, f) || rounds[k].seen.includes(f));
      let v = p.lastR + 1;
      while (v < rounds.length && !opened(v)) v++;
      p.ghost = [p.lastR + 1, v];
      const next = rounds[v];
      if (!next) {
        if (p.lastR + 1 >= rounds.length) return orph.length ? 'elsewhere' : 'unread';
        // Unread while the pull request is read in blocks: a later block's
        // file is read whole when that block comes, a file no block owns by
        // the next block read whole — the review has not skipped it.
        const owners = p.files.map((f) => ownerNow[f] || 0);
        // Waiting is now's: by the cut that stands now, whatever the cut the
        // columns were grouped by at the moment shown.
        if (d.blockNow != null && rounds.length === d.rounds.length) {
          if (owners.every((n) => n > d.blockNow)) { p.laterBlock = Math.min(...owners); return 'later'; }
          if (owners.every((n) => !n)) return 'cutless';
        }
        return 'unseen';
      }
      p.verify = v;
      const ths = chain(p).flatMap((q) => q.th).concat(orph);
      if (!ths.every(settled)) return orph.some((t) => !settled(t)) ? 'elsewhere' : 'open';
      if (next.more) return 'partial';
      // The last round: its fixing is over once step 4 is.
      if (!rounds[v + 1]) return d.closed && rounds.length === d.rounds.length ? 'done' : 'checking';
      return 'done';
    }
    function done(p) { return why(p) === 'done'; }
    whyOf = why;
    doneOf = done;
    const owed = [], bodies = [], thins = [];
    places.forEach((ps, ri) => ps.forEach((p) => {
      // A folded block's places are drawn as its one summed icicle, below.
      if (p.files.every(isFold)) return;
      const y0 = ys[ri], y1 = ys[ri + 1];
      // A trapezoid: the bottom as wide as the lines this round changed
      // here; the top the slices of the places above it has (wider than one
      // when it merges them), or, in the first round, its own width under
      // the development's code. A place with nothing above it — a file the
      // development did not write, or code first touched in a later round —
      // starts flat at its own width, where its code is. Where no later round
      // came back, the icicle closes to a point in the middle of the next
      // row only once its chain is done (done()): every thread of it and of
      // the places it grew from has an outcome, and the next round read
      // the fix; otherwise it is cut flat — waiting.
      // A merge is drawn as one stream a parent, each from its slice of the
      // parent's bottom to its share of this place's bottom, left to right,
      // so it shows where each part came from.
      const quad = (a, b, c, e, t) => 'M' + f1(a) + ',' + f1(t) + ' L' + f1(b) + ',' + f1(t) + ' L' + f1(e) + ',' + f1(y1) + ' L' + f1(c) + ',' + f1(y1) + 'Z';
      let d_;
      // The stems from places further up, each in the colour of the place
      // it leaves: until this round nothing of this place's own was there.
      const stems = [];
      if (p.ups.length) {
        const s = p.ups.map((q) => [...q.slice.get(p), q.ri, q]).sort((a, b) => a[0] - b[0]);
        const total = s.reduce((a, v) => a + Math.max(0.5, v[1] - v[0]), 0);
        let x = p.l;
        d_ = s.map((v) => {
          const share = p.w * Math.max(0.5, v[1] - v[0]) / total;
          // From a round further up, through the rounds that left that code
          // alone, a thin stem: nothing happened there, and a band as wide as
          // its slice would read as fixes in every one of those rows.
          if (v[2] < ri - 1) {
            const [a, b] = stem(v[0], v[1]);
            stems.push('<path class="rv-shape" d="' + neck(v[0], v[1], ys[v[2] + 1], y0) + '" fill="' + colour(v[3].outcome, v[3].depth) + '"/>');
            const part = quad(a, b, x, x + share, y0);
            x += share;
            return part;
          }
          const part = quad(v[0], v[1], x, x + share, y0);
          x += share;
          return part;
        }).join(' ');
      } else {
        // Nothing above it: it starts at its own width, where its code is,
        // in a new file too — a point would show less code than was changed
        // (the user's word, 2026-11-18). What starts it is plain without:
        // nothing hangs above.
        d_ = quad(p.l, p.r, p.l, p.r, y0);
      }
      // Its file removed: the ✕ stands whether or not its threads have their
      // outcomes yet — there is nothing left there to read either way.
      const why_ = whyOf(p);
      const isGone = p.goneAt != null;
      const isDone = why_ !== 'gone' && done(p);
      // Rounds that never opened its files. Read later, the rows between
      // are known to have left it alone: a thin stem, as between two fixes.
      // Not read yet, the whole width waits for a reading: a dashed outline
      // of it, faintly filled — owed, not done.
      let ghost = '';
      const g0 = p.ghost ? p.ghost[0] : 0, g1 = p.ghost ? Math.min(p.ghost[1], rounds.length, ...p.files.map(until_)) : 0;
      const known = p.verify != null;
      const stemmed = !p.kids.length && !(p.jout || []).length && g1 > g0 && known;
      // The column goes on in the next file (until_) before the round that
      // read it: the stem tapers to its point in the last row that is still
      // this file's, rather than closing rows below, under another file.
      // Only a close drawn there needs that row; otherwise the stem runs on.
      const clipped = stemmed && (isDone || why_ === 'checking') && p.verify > g1;
      if (!p.kids.length && !(p.jout || []).length && g1 > g0) {
        ghost = known ? neck(p.l, p.r, ys[g0], ys[clipped ? g1 - 1 : g1])
          : 'M' + f1(p.l) + ',' + f1(ys[g0]) + ' L' + f1(p.r) + ',' + f1(ys[g0]) + ' L' + f1(p.r) + ',' + f1(ys[g1]) + ' L' + f1(p.l) + ',' + f1(ys[g1]) + 'Z';
      }
      // The close: across its whole bottom right under its fix; from the
      // stem, after rows that left it alone, a small point.
      const point = (verify) => {
        const close = clipped ? g1 - 1 : verify;
        const end = clipped ? ys[g1] : (ys[close] + ys[close + 1]) / 2;
        // Never wider than what it closes: the stem, or the place's bottom.
        const [a, b] = stemmed ? stem(p.l, p.r) : [p.l, p.r];
        return 'M' + f1(a) + ',' + f1(ys[close]) + ' L' + f1(b) + ',' + f1(ys[close]) + ' L' + f1(p.cx) + ',' + f1(end) + 'Z';
      };
      if (isDone && p.orph && p.orph.length && p.verify === p.lastR + 1) {
        // Its later threads, fixed elsewhere: their dots say it; once the
        // chain is done, a small point in the row of the round that checked it.
        const close = p.verify, stop = (ys[close] + ys[close + 1]) / 2;
        const [a, b] = [Math.max(p.l, p.cx - 4), Math.min(p.r, p.cx + 4)];
        d_ += ' M' + f1(a) + ',' + f1(ys[close]) + ' L' + f1(b) + ',' + f1(ys[close]) + ' L' + f1(p.cx) + ',' + f1(stop) + 'Z';
      } else if (isDone) {
        // Closed in the row of the round that checked it, after any stem.
        d_ += ' ' + point(p.verify);
      }
      // Read by the last round, which found nothing here but is still
      // fixing: the close it will get, drawn as an outline until then.
      let tent = '';
      if (!isDone && whyOf(p) === 'checking') tent = point(p.verify);
      // Its file removed by its round's fixes: it ends at its row's foot,
      // a line across it and a ✕, where the code went said on hover.
      let end = '';
      if (isGone) {
        const why = '✕ — file removed by the fixes of ' + roundName(p.goneAt - 1).toLowerCase() + ': ' + p.files.join(', ')
          + (p.movedTo.length ? '\nIts code was moved to ' + p.movedTo.join(', ') : '');
        end = '<g class="rv-gone"><title>' + h(why) + '</title><line x1="' + f1(p.l - 1) + '" x2="' + f1(p.r + 1) + '" y1="' + f1(y1 - 0.75) + '" y2="' + f1(y1 - 0.75) + '"/>'
          + '<text x="' + f1(p.cx) + '" y="' + f1(y1 + 8) + '">✕</text></g>';
      }
      p.look = {pale: !!ghost && !known, stem: stemmed, tent: !!tent, done: isDone, gone: isGone};
      const gid = 'rv-g' + p.id;
      let fill = colour(p.outcome, p.depth);
      // Split by share: the development's beige on the left for the lines
      // the person asked for, the outcome's colour for the review's own.
      let split = '';
      if (p.outcome !== 'asked' && p.askedShare > 0.02) {
        const a = (p.askedShare * 100).toFixed(1), beige = colour('asked', p.depth);
        split = '<linearGradient id="' + gid + 'a" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="' + beige + '"/><stop offset="'
          + a + '%" stop-color="' + beige + '"/><stop offset="' + a + '%" stop-color="' + fill + '"/><stop offset="1" stop-color="' + fill + '"/></linearGradient>';
        fill = 'url(#' + gid + 'a)';
      }
      const edge = colour(p.outcome, p.depth);
      // Where code or a migration changed, comments and tests come with it:
      // only a migration is told apart. Where neither did, what was touched
      // instead is the news: tests, docs and config, comments, laid over
      // each other (the user's word, 2026-11-17).
      const over = FLAGS.filter((f) => p.flags.has(f) && (p.solid ? f === 'schema' : f !== 'schema')).map((f) => '<path d="' + d_ + '" fill="url(#rv-p-' + f + ')"/>').join('');
      // Its thread known only by nearness: a dashed edge, the fill lighter.
      const guess = p.guess && p.solid ? ' rv-guess' : '';
      // Three layers, so that no fill hides a thin line: the faint outlines
      // of code still owed a reading under everything; the bodies, the
      // widest first, so a narrow icicle beside or over a wide one stays in
      // sight; and on top every thin thing — stems, closing outlines, the
      // marks of a removed file.
      const g = (html, main) => '<g class="rv-fix" data-i="' + p.id + '"' + (main ? ' data-body="1"' : '') + '>' + html + '</g>';
      if (ghost && !known) owed.push(g('<path class="rv-ghost" d="' + ghost + '" fill="' + edge + '" stroke="' + edge + '"/>'));
      bodies.push([p.r - p.l, g(split + '<path class="rv-shape' + (p.solid ? '' : ' rv-hollow') + guess + '" d="' + d_ + '" fill="' + fill + '"'
        + (p.solid && !guess ? '' : ' stroke="' + edge + '"') + '/>' + over, true)]);
      const thin = stems.join('') + (ghost && known ? '<path class="rv-shape" d="' + ghost + '" fill="' + edge + '"/>' : '')
        + (tent ? '<path class="rv-tent" d="' + tent + '" stroke="' + edge + '"/>' : '') + end;
      if (thin) thins.push(g(thin));
    }));
    svg.push(...owed, ...bodies.sort((a, b) => b[0] - a[0]).map(([, html]) => html), ...thins);
    // The jumps: where a chain leaves for a file too far to stream to, a
    // mark in the middle of the row it lands in, under where it left; where
    // it lands, a mark beside the place — below the threads' piles, which
    // hang from the row's top. Each is a link to the other (#rvj-<n>-out,
    // #rvj-<n>-in): a click scrolls the map there and lights it.
    // Read and found nothing: at the foot of a round's row, under each
    // column whose file the round opened and posted no thread on, a strip as
    // strong as the reading — the whole file, or all its change in a whole
    // read of the block (`read: first`), solid and thick; the last fixes'
    // change alone (a delta pass), thin and blue; a slice, a search, dashed
    // and yellow — it says less. Where a
    // round read and found nothing is where the review had nothing left.
    const CLEAN = {whole: 3, all: 3, delta: 2, part: 1.4};
    const SAY = {whole: 'read the whole file', all: 'read all its change (a whole read of the block)',
      delta: 'read the last fixes\' change in it', part: 'looked at a part of it'};
    const GLYPH = {whole: '━', all: '━', delta: '─', part: '┄'};
    const LINE = {whole: 'a thick green line', all: 'a thick green line', delta: 'a thin blue line', part: 'a dashed yellow line'};
    // Where an icicle goes on through a row — its fix's row, the pale rows
    // under it — the column was plainly opened: no strip. The row it closes
    // in keeps one: that round read it and found nothing more.
    const busy = {};
    flat.forEach((p) => {
      const end = p.verify != null ? p.verify : p.ghost ? p.ghost[1] : p.ri + 1;
      for (let k = p.ri; k < end; k++) p.files.forEach((f) => { (busy[k] = busy[k] || new Set()).add(fi[f]); });
    });
    rounds.forEach((r, ri) => {
      if (!r.how || r.stopped) return;
      const hit = new Set(d.threads.filter((t) => t.r === ri).map((t) => t.path));
      const best = {};
      Object.entries(r.how).forEach(([f, how]) => {
        if (fi[f] == null || isFold(f) || hit.has(f) || (busy[ri] && busy[ri].has(fi[f]))) return;
        const k = how === 'whole' ? 'whole' : how === 'diff' ? (r.read === 'first' ? 'all' : 'delta') : 'part';
        const c = fi[f];
        if (!best[c] || CLEAN[k] > CLEAN[best[c].k]) best[c] = {k: k, f: []};
        if (best[c].k === k) best[c].f.push(f);
      });
      Object.entries(best).forEach(([c, b]) => {
        const col = cols[c], w = CLEAN[b.k], y = ys[ri + 1] - w / 2 - 1;
        svg.push('<line class="rv-clean rv-clean-' + b.k + '" x1="' + f1(col[0] + 1) + '" x2="' + f1(col[0] + col[1] - 1)
          + '" y1="' + f1(y) + '" y2="' + f1(y) + '" style="stroke-width:' + w + '" data-tip-mark="stroke"><title>' + GLYPH[b.k] + ' — nothing found: ' + LINE[b.k] + ' under the file, in the row of the round that read it\n' + h(roundName(ri)) + ' ' + SAY[b.k]
          + ':\n' + h(b.f.join('\n')) + '</title></line>');
      });
    });
    // A folded block: one icicle of all its files, drawn as the one behind
    // the rows' names (summed, above).
    groups.filter((g) => g.fold).forEach((g) => {
      const inBlock = new Set(files.filter((f) => blockOf[f] === g.g).flatMap(stackOf));
      const dev = [...inBlock].reduce((a, f) => a + ((devf[f] || {}).add || 0), 0);
      svg.push(...summed((x) => inBlock.has(x.path), (t) => inBlock.has(t.path), dev, g.x0, g.x1, 'rv-fold',
        'Block folded: every file of it in one icicle. Left of its axis the development\'s code, right the review\'s own: the lines each round touched, split by how their threads ended; the line, how much the round grew (right) or shrank (left) the code, ' + (dark() ? 'lighter' : 'darker') + ' the more threads review posted. Click its name to open it.'));
    });
    svg.push(...nexts);
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
    // A mark into a folded block opens it and goes to the place of that
    // round in that file holding the thread (`data-r`, `data-file`,
    // `data-rid`): opened, the block's
    // places are grouped afresh and the link may be a stream.
    let jn = 0;
    flat.forEach((src) => (src.jout || []).forEach((q) => {
      const id = 'rvj-' + (++jn);
      const y = Math.max(ys[q.ri] + 14, (ys[q.ri] + ys[q.ri + 1]) / 2);
      const there = q.files.join(', '), here = src.files.join(', ');
      const shut = q.files.every(isFold) && idOfN[blockOf[q.files[0]]];
      const moved = src.joutMoved && src.joutMoved.has(q);
      const out = mark(id + '-out', id + '-in', src.cx, y, '↗',
        '↗ — goes on in another file: ' + there + ' (' + roundName(q.ri).toLowerCase() + '): ' + (moved ? 'its code was moved there' : 'a reply says its thread was fixed there') + '.\nClick to go there'
        + (shut ? ', opening block ' + shut : '') + '.', 1);
      const t = src.joutBy && src.joutBy.get(q);
      svg.push(shut ? out.replace('<a class="rv-jump"', '<a class="rv-jump" data-unfold="' + h(shut) + '" data-r="' + q.ri + '" data-file="' + h((t && t.fixedIn && q.files.find((f) => t.fixedIn.files.includes(f))) || q.files[0]) + '" data-rid="' + h(t ? t.rid : '') + '"') : out);
      if (shut) return;
      svg.push(mark(id + '-in', id + '-out', q.l - 9, y, '↘',
        '↘ — came from another file: ' + here + ' (' + roundName(src.ri).toLowerCase() + '): ' + (moved ? 'its code was moved here' : 'a reply says its thread was fixed here') + '.\nClick to see where it left.', -1));
    }));
    // A check that missed: a round read a fixed problem's chain whole,
    // found nothing and closed it, and a later round found a problem on the
    // very lines that chain's fixes wrote (review_map.py's `missed`). The
    // icicle goes on through it; where the round passed it, a purple bar
    // across it, and the thread's dot a purple ring.
    d.threads.forEach((t) => {
      if (t.missed == null || t.of == null || t.r == null || t.r >= rounds.length || t.missed >= rounds.length) return;
      if (until != null && t.t * 1000 > until) return;
      const q = placeOf.get(d.hunks[t.of]);
      if (!q || q.files.every(isFold)) return;
      const y = (ys[t.missed] + ys[t.missed + 1]) / 2;
      svg.push('<g class="rv-missed" data-tip-mark="stroke"><title>━ — the purple bar: a check that missed\n' + h(roundName(t.missed)) + ' read this fix and passed it; '
        + h(roundName(t.r).toLowerCase()) + ' then found a problem on the lines it wrote:\n' + h(t.path) + ':' + t.line + ' — ' + h(t.title)
        + '</title><line x1="' + f1(q.l - 3) + '" x2="' + f1(q.r + 3) + '" y1="' + f1(y) + '" y2="' + f1(y) + '"/></g>');
    });
    // The threads, stacked: those a round posted close together in the code
    // pile down from the round's line into one column, a dot each in the
    // colour of how it ended — the taller the column, the more the review
    // found there.
    const ORDER = ['open', 'reversal', 'yours', 'declined', 'fixed', 'side'];
    // A dot's radius, and what a pile takes across with its outline (or
    // its +n), for the ✋ to keep clear of.
    // How the dots, the +n and the ✋ are laid out and kept off one another
    // is settled at the user's word (2026-11-17): a touch left in a crowded
    // row is accepted, and the layout is not to be tuned further.
    const R = 2.8, piles = {}, pileAt = {}, handAt = {};
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
      // One size for every dot on the map, so size says nothing; a pile
      // longer than its row shows what fits, alarms first (ORDER), and the
      // rest as +n in the column's last place, so it never runs into a
      // neighbour's. Dots nearly touch, each with its own dark outline,
      // which is what sets them off an icicle of the same colour; the
      // shortest row (ROWMIN) holds two and the +n, clear of both
      // rounds' lines: past the dot's outline (up to 1, your thread's) and
      // half a block's line (1).
      const STEP = 2 * R + 0.6, TOP = R + 2;
      const room = ys[p.r + 1] - ys[p.r] - 2 * TOP;
      const fit = Math.floor(room / STEP) + 1;
      const over = p.all.length > fit;
      const shown = over ? p.all.slice(0, fit - 1) : p.all;
      const more = over ? '+' + (p.all.length - shown.length) : '';
      (pileAt[p.r] = pileAt[p.r] || []).push([x, Math.max(R + 0.5, more.length * 2.3 + 1)]);
      shown.forEach((t, k) => {
        const y = ys[p.r] + TOP + k * STEP;
        svg.push('<a href="' + h(t.url) + '" target="_blank" rel="noopener"><circle class="rv-th' + (t.by === 'person' ? ' you' : '') + (t.missed != null ? ' missed' : '') + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1)
          + '" r="' + R + '" fill="' + colour(t.outcome, 1) + '" data-tip-mark="fill"><title>● — a review thread, its colour how it ended\n' + h(t.path) + ':' + t.line + ' — ' + h(t.title) + '\n' + h(howEnded(t))
          + (t.by === 'person' ? '\nThe thick ring: your own thread' : '')
          + (t.missed != null ? '\nThe purple ring: on lines a fix wrote that ' + roundName(t.missed).toLowerCase() + ' read and passed — the check missed it' : '')
          + (p.all.length > 1 ? '\n' + p.all.length + ' threads here' : '') + '</title></circle></a>');
      });
      if (over) {
        const rest = p.all.slice(shown.length);
        const y = ys[p.r] + TOP + shown.length * STEP;
        svg.push('<text class="rv-more" x="' + x.toFixed(1) + '" y="' + (y + 2.5).toFixed(1) + '">' + more + '<title>' + more + ' — the threads past what the row has room for:\n'
          + h(rest.map((t) => t.path + ':' + t.line + ' — ' + t.title + ' (' + howEnded(t) + ')').join('\n'))
          + '</title></text>');
      }
    });
    // The person, gathered: one ✋ for each round's answers in the margin,
    // and one for the answers and threads at one place of a file, with how
    // many — ringed amber when any took the recommended answer.
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
        const mine = all.filter((p) => p.kind === 'thread').length, said = all.filter((p) => p.kind === 'sclaude').length;
        const waits = all.map((p) => p.waited).filter((w) => w != null).sort((a, b) => a - b);
        // Clear of the threads' dots: past a dot (R) and the ring (8, its
        // stroke up to 2.5), its count going outward. The first of four
        // spots with room for both, off the round's piles (a +n is wider)
        // and hands placed before it, inside the map and right of the
        // rounds' names and their ✋; in a row crowded with piles, the
        // first off the other hands at least, else to the right.
        const tw = n > 1 ? 10 + String(n).length * 6.5 : 10;
        const span = (v) => [g.x + v - (v < 0 ? tw : 9), g.x + v + (v < 0 ? 9 : tw)];
        const free = (v, piles) => {
          const [a, b] = span(v);
          return a > GUT && b < W && !(handAt[g.r] || []).some(([c, e]) => e > a && c < b)
            && !(piles && (pileAt[g.r] || []).some(([px, half]) => px + half > a && px - half < b));
        };
        const SPOTS = [13, -13, 26, -26];
        const dx = g.x == null ? 0 : SPOTS.find((v) => free(v, true)) || SPOTS.find((v) => free(v, false)) || 13;
        if (g.x != null) (handAt[g.r] = handAt[g.r] || []).push(span(dx));
        const left = dx < 0;
        const x = g.x == null ? GUT - 34 : g.x + dx;
        const y = ys[g.r] + (g.x != null ? 14 : Math.min(two(g.r + 1) ? 52 : 30, Math.max(14, ys[g.r + 1] - ys[g.r] - 4)));
        const head = '✋ — you stepped in: ' + n + (n === 1 ? ' time' : ' times') + (n > 1 ? ' (the number beside the hand)' : '')
          + (rec ? '\n' + rec + ' took the recommended answer (the amber ring)' : '')
          + (other ? '\n' + other + ' chose otherwise' : '') + (mine ? '\n' + mine + ' your own thread' + (mine > 1 ? 's' : '') : '')
          + (said ? '\n' + said + ' answered sclaude' : '')
          + (waits.length ? '\nhalf answered within ' + dur(waits[Math.floor((waits.length - 1) / 2)]) : '');
        const list = all.filter((p) => p.q).slice(0, 8).map((p) => '\n• ' + h(p.q.slice(0, 140)) + (p.a ? ' → ' + h(p.a.slice(0, 60)) : '')).join('');
        // Over a round's name in the margin the hand and its count are
        // drawn on the panel's own colour, so the name runs under them and
        // neither is read through the other (the user's word, 2026-11-19).
        measure.font = '700 11px ' + getComputedStyle(body).fontFamily;
        const cw = n > 1 ? measure.measureText(String(n)).width + 6 : 0;
        const cx0 = left ? x - 10 - cw + 3 : x + 10 - 3;
        svg.push('<g class="rv-hand' + (rec ? ' rec' : '') + '"><title>' + h(head) + list + (all.filter((p) => p.q).length > 8 ? '\n…' : '') + '</title>'
          + (g.x == null ? '<circle class="rv-handbg" cx="' + x.toFixed(1) + '" cy="' + (y - 4).toFixed(1) + '" r="8"/>'
            + (cw ? '<rect class="rv-handbg" x="' + cx0.toFixed(1) + '" y="' + (y - 11).toFixed(1) + '" width="' + cw.toFixed(1) + '" height="14" rx="3"/>' : '') : '')
          + (rec ? '<circle cx="' + x.toFixed(1) + '" cy="' + (y - 4).toFixed(1) + '" r="8"/>' : '')
          + '<text x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '">✋</text>'
          + (n > 1 ? '<text class="rv-hn" x="' + (left ? x - 10 : x + 10).toFixed(1) + '"' + (left ? ' style="text-anchor:end"' : '') + ' y="' + y.toFixed(1) + '">' + n + '</text>' : '') + '</g>');
      });
    }
    svg.push('</svg>');
    const keep = [body.scrollLeft, body.scrollTop];
    svg[0] = svg[0].replace('<svg ', '<svg style="margin-top:-' + HEAD + 'px" ');
    body.innerHTML = '<div class="rv-wrap" style="width:' + W + 'px"><svg class="rv-svg rv-head" width="' + W + '" height="' + HEAD + '" viewBox="0 0 ' + W + ' ' + HEAD + '"><rect class="rv-headbg" width="' + W + '" height="' + HEAD + '"/>'
      + head.join('') + '</svg><div class="rv-pin" style="width:' + pinW + 'px"><svg class="rv-svg" width="' + pinW + '" height="' + (H - HEAD) + '" viewBox="0 ' + HEAD + ' ' + pinW + ' ' + (H - HEAD) + '">'
      + pin + '</svg></div>' + svg.join('') + '</div>';
    body.scrollLeft = keep[0];
    body.classList.toggle('rv-sx', body.scrollLeft > 2);
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
  const hold = holdTip(tip);
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
    // Many rounds: the bars narrow to fit the note, and only every k-th
    // round is named — always the one hovered — so the names never overlap.
    const ROOM = 370, lw = 6 * Math.max(...series.map(([r]) => roundName(r, true).length)) + 4;
    const slot = Math.min(17, ROOM / series.length), every = Math.max(1, Math.ceil(lw / slot));
    const named = (r) => r === p.ri || (Math.abs(r - p.ri) >= every && (r - first) % every === 0);
    const bars = '<div class="t-sp' + (slot < 17 ? ' tight' : '') + '" style="--slot:' + slot.toFixed(1) + 'px">' + series.map(([r, v]) => {
      const out = v ? Object.entries(v.out).sort((a, b) => b[1] - a[1])[0][0] : 'side';
      return '<span class="' + (r === p.ri ? 'on' : '') + '" title="' + roundName(r) + ': ' + (v ? v.changed + ' lines, ' + v.th.length + ' threads' : 'not touched') + '">'
        + '<i style="height:' + (v ? Math.max(2, 34 * v.changed / most) : 0).toFixed(0) + 'px;background:' + (v ? colour(out, 1) : 'none') + '"></i><b>' + (named(r) ? roundName(r, true) : '&nbsp;') + '</b></span>';
    }).join('') + '</div>';
    // The reading, most telling first.
    const ths = all.flatMap((q) => q.th);
    // A reversal counts as declined only where its reply says it was left:
    // one may have been applied after all.
    const declined = ths.filter((t) => t.outcome === 'declined' || (t.outcome === 'reversal' && t.left)).length;
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
      later: 'Waiting for block ' + ((data.blocks || []).find((b) => b.n === (tips.find((q) => q.laterBlock) || {}).laterBlock) || {}).id + ': its first read reads this file whole; the icicle goes on, pale, till then.',
      cutless: 'Waiting: the cut into blocks does not name this file (written after it); the next block read whole takes it.',
      checking: 'Waiting: the round after the fix read all of it and found nothing here; its own fixing is not over yet, so a fix of it may still land here.',
      open: 'Waiting: a thread of it is still open or waits for you.',
      partial: 'Waiting: the round after the fix stopped at its cap, so it may not have said all it found here.',
      found: 'Waiting: the round after the fix posted a new thread here.',
      elsewhere: 'Waiting: a later round posted threads here and no fix landed here — they are fixed elsewhere or not yet; the chain is checked once they all have an outcome and the round after reads past them.',
    };
    const closedIn = Math.max(...tips.map((q) => (q.lastR != null ? q.lastR : q.ri) + 1));
    const removed = tips.filter((q) => whyOf(q) === 'gone');
    if (tips.length && removed.length === tips.length) says.push(['end', 'Ended in ' + roundName(closedIn - 1).toLowerCase() + ': its file was removed, and every thread of it has an outcome.']);
    else if (tips.length && tips.every((q) => doneOf(q) || whyOf(q) === 'gone')) says.push(['end', 'Done in ' + roundName(closedIn).toLowerCase() + ': every thread of it has an outcome, that round read all of it and found nothing here, and its fixing ended without coming back'
      + (removed.length ? ' — where its file was not removed first.' : '.')]);
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
    const threads = p.th.slice(0, 4).map((t) => '<div class="t-th"><i style="background:' + colour(t.outcome, 1) + '"></i>' + h(t.title || t.rid) + ' <span class="muted">· ' + h(howEnded(t)) + '</span></div>').join('')
      + (p.th.length > 4 ? '<div class="muted">… and ' + (p.th.length - 4) + ' more</div>' : '');
    whyOf(p);
    const laterThreads = (p.orph || []).map((t) => '<div class="t-th"><i style="background:' + colour(t.outcome, 1) + '"></i>' + roundName(t.r) + ': ' + h(t.title || t.rid) + ' <span class="muted">· ' + h(howEnded(t)) + '</span></div>').join('');
    const rec = p.hd.filter((x) => x.rec).length;
    return where
      + (p.why ? '<div class="t-r muted">Files joined as ' + h(p.why) + '</div>' : '')
      + (p.slid ? '<div class="t-r muted">Slid here from ' + h([...new Set(p.slid)].join(', ')) + ': the reply to its thread names the commit and this file</div>' : '')
      + ((p.jout || []).length ? '<div class="t-r muted">Went on in ' + h([...new Set(p.jout.flatMap((q) => q.files))].join(', ')) + ' — the ↗ mark leads there</div>' : '')
      + alsoIn(p)
      + (p.movedFrom.length ? '<div class="t-r muted">Code moved here from ' + h(p.movedFrom.join(', ')) + ': the same lines removed there in this round</div>' : '')
      + (p.movedTo.length ? '<div class="t-r muted">Code moved from here to ' + h(p.movedTo.join(', ')) + '</div>' : '')
      + '<div class="t-r"><b>' + roundName(p.ri) + '</b>: ' + p.hs.length + ' fix' + (p.hs.length > 1 ? 'es' : '') + ', +' + add + ' −' + del
      + ' · ' + p.code + ' code, ' + p.comment + ' comment · <span style="color:' + colour(p.outcome, 1) + '">' + OUT[p.outcome][1] + '</span>'
      + (p.net >= 3 ? ' · <b>+' + p.net + ' lines grown</b>' : '') + '</div>'
      + (threads ? '<div class="t-h">Threads posted here</div>' + threads : '<div class="muted">No thread here: these fixes came along with others.</div>')
      + (laterThreads ? '<div class="t-h">Posted here later, with no fix here</div>' + laterThreads : '')
      + (p.hd.length ? '<div class="t-r">✋ ' + p.hd.length + ' answer' + (p.hd.length > 1 ? 's' : '') + ' about them' + (rec ? ', ' + rec + ' the recommended one' : '') + '</div>' : '')
      + '<div class="t-h">This icicle, round by round (lines changed)</div>' + bars
      // How many rounds came back here is said once: by the reading
      // ('long') when it is there, else here.
      + '<div class="t-r muted">' + churn + ' lines changed here' + (series.length >= 3 ? '' : ' over ' + series.filter(([, v]) => v).length + ' round' + (series.filter(([, v]) => v).length > 1 ? 's' : ''))
      + (devLines ? ' — ' + Math.round(100 * churn / devLines) + '% of the ' + devLines + ' lines the development wrote in ' + (p.files.length > 1 ? 'these files' : 'this file') : ' — in code the development did not write') + '</div>'
      + says.map(([k, t]) => '<div class="t-say t-' + k + '">' + h(t) + '</div>').join('')
      + drawnAs(p);
  }
  // The same finding fixed in other files in the same round — what
  // drawing by fix joins when the columns are side by side; here, wherever
  // they are, each a link.
  function alsoIn(p) {
    // The keys drawing by fix joins on (linkOf): a hunk's thread, or with
    // none its subagent — so a subagent fixing two findings in two files
    // does not list one under the other.
    const keys = new Set(p.bits.flatMap((b) => [...b.keys]));
    if (!keys.size) return '';
    const rows = [];
    placesNow.forEach((q) => {
      if (q === p || q.ri !== p.ri) return;
      q.bits.forEach((b) => {
        if (p.files.includes(b.f)) return;
        const k = [...b.keys].find((key) => keys.has(key));
        if (!k) return;
        const ls = b.hs.map((x) => x.x).sort((a, c) => a - c);
        rows.push('<div class="t-r"><a class="t-go" href="#" data-r="' + q.ri + '" data-file="' + h(b.f) + '" data-line="' + ls[0] + '" data-rid="' + h(k.startsWith('t:') ? k.slice(2) : '') + '"'
          + (q.foldId ? ' data-unfold="' + h(q.foldId) + '"' : '') + '>' + h(b.f) + ':' + ls[0] + (ls.length > 1 ? '–' + ls[ls.length - 1] : '') + '</a>'
          + ' <span class="muted">· ' + (k.startsWith('t:') ? 'the same thread' : 'the same subagent\'s fix') + '</span></div>');
      });
    });
    return rows.length ? '<div class="t-h">The same finding, fixed also in</div>' + [...new Set(rows)].join('') : '';
  }
  // What this place's look means — only the legend's entries drawn here,
  // so a note says what its colour and patterns are without the legend
  // (the user's word, 2026-11-17).
  function drawnAs(p) {
    const fill = colour(p.outcome, p.depth);
    const box = (c, pat, hollow) => '<svg width="12" height="12"><rect width="12" height="12" fill="' + c + '"' + (hollow ? ' fill-opacity=".28"' : '') + '/>'
      + (pat ? '<rect width="12" height="12" fill="url(#rv-p-' + pat + ')"/>' : '') + '</svg>';
    const row = (sw, say) => '<div class="t-k">' + sw + '<span>' + say + '</span></div>';
    const KIND = {test: 'tests', doc: 'docs, config', comment: 'comments'};
    const out = [];
    out.push(row(box(fill), p.outcome === 'asked' ? '<b>beige</b>: the person asked for these lines'
      : p.outcome === 'side' ? '<b>grey</b>: no thread asked for these fixes'
      : p.outcome === 'moved' ? '<b>mauve</b>: code moved ' + (p.movedFrom.length ? 'here from ' + h(p.movedFrom.join(', ')) : 'away to ' + h(p.movedTo.join(', '))) + ', not written anew'
      : '<b>' + OUT[p.outcome][1] + '</b>: the colour is how its thread ended'));
    if (p.guess && p.solid) out.push(row(box(fill, '', true).replace('<rect', '<rect stroke="' + fill + '" stroke-dasharray="3 2"'), 'dashed edge: tied to its thread only by sitting near it — likely, not certain'));
    const most = p.maxDepth > p.depth ? ' (up to ' + p.maxDepth + ' in a part of them)' : '';
    out.push(row('<span class="t-steps">' + [0, 1, 2, 3].map((k) => '<i style="background:' + colour(p.outcome, k) + (k === Math.min(3, p.depth || 0) ? ';outline:1.5px solid var(--ink)' : '') + '"></i>').join('') + '</span>',
      p.depth ? (dark() ? 'lighter' : 'darker') + ': review had already rewritten these lines in ' + p.depth + ' earlier round' + (p.depth > 1 ? 's' : '') + most
        : 'the lightest step: few or none of these lines had been rewritten before' + most));
    if (p.outcome !== 'asked' && p.askedShare > 0.02) out.push(row(box(colour('asked', p.depth)), 'beige on the left, ' + Math.round(p.askedShare * 100) + '%: lines the person asked for'));
    if (p.solid) out.push(row(box(fill, p.flags.has('schema') ? 'schema' : ''), 'solid: code changed' + (p.flags.has('schema') ? ', the \\ hatching a migration among it' : '')));
    else {
      out.push(row(box(fill, '', true), 'hollow: no code or migration changed, only what its patterns say'));
      FLAGS.filter((f) => f !== 'schema' && p.flags.has(f)).forEach((f) => out.push(row(box(fill, f, true), KIND[f])));
    }
    const look = p.look || {};
    if (look.pale) out.push(row(box(fill, '', true), 'dashed outline below: no round has opened this code since'));
    if (look.stem) out.push(row('<b class="t-g">│</b>', 'thin stem below: rounds that left this code alone, until one read it'));
    if (look.gone) out.push(row('<b class="t-g">✕</b>', 'line and ✕: the file was removed here' + (p.movedTo.length ? ', its code moved to ' + h(p.movedTo.join(', ')) : '')));
    if (look.done) out.push(row('<b class="t-g">▼</b>', 'closed to a point: done'));
    if (look.tent) out.push(row('<b class="t-g">⋯</b>', 'dashed point: read by the round still fixing; closes once its fixing ends'));
    return '<div class="t-h">How it is drawn</div>' + out.join('');
  }
  // The held names come up only once the map is scrolled sideways: at
  // rest the whole name and its duration are there on the map.
  body.addEventListener('scroll', () => body.classList.toggle('rv-sx', body.scrollLeft > 2), {passive: true});
  body.addEventListener('mouseover', (ev) => {
    const bk = ev.target.closest && ev.target.closest('.rv-bk[data-n]');
    const blk = bk && blocksNow.find((b) => b.n === +bk.dataset.n);
    const g = !blk && ev.target.closest && ev.target.closest('.rv-fix');
    if (!blk && (!g || !placesNow[+g.dataset.i])) { hold.leave(); return; }
    hold.show(blk ? 'b' + blk.id : 'p' + g.dataset.i, () => blk ? blockTip(blk) : tipHtml(placesNow[+g.dataset.i]), ev, blk ? bk : g);
  });
  body.addEventListener('mouseleave', () => hold.leave());
  // A split's line clicked: a card of what happened — the block as it
  // was, and the parts it became, each with what it answers for.
  const card = document.createElement('div');
  card.id = 'rv-cutcard'; card.hidden = true; document.body.append(card);
  function cutCard(j, ri) {
    const e = (data.earlier || [])[j];
    if (!e) return '';
    const was = e.blocks.find((b) => b.id === e.split) || {files: [], criteria: []};
    const next = (data.earlier[j + 1] || data).blocks || [];
    const tail = /\d$/.test(e.split) ? /^[a-z]$/ : /^\d+$/;
    const parts = next.filter((b) => b.id.startsWith(e.split) && tail.test(b.id.slice(e.split.length)));
    const when = new Date(e.until * 1000).toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
    const crit = (b) => b.criteria.length ? b.criteria.length + (b.criteria.length === 1 ? ' criterion (' : ' criteria (')
      + h(b.criteria.join(', ')) + ')' : 'no criterion of its own';
    return '<button type="button" class="c-x" aria-label="Close">✕</button>'
      + '<div class="c-h">✂ Block ' + h(e.split) + ' split in ' + parts.length + '</div>'
      + '<div class="c-m">' + h(when) + ', before ' + h(roundName(ri).toLowerCase()) + '</div>'
      + '<p>It had grown past what one pass reads whole in earnest — its fixes, the files they added, or a rework: '
      + was.files.length + ' files, ' + crit(was) + '. Before reading it whole again, a session split it by behaviour, '
      + 'and each part is read whole on its own, its rounds counted afresh. The blocks after keep their names.</p>'
      + '<div class="c-was"><b>Was</b> ' + h(e.split) + ' — ' + h(was.title) + '</div>'
      + parts.map((b) => '<div class="c-part"><b>' + h(b.id) + '</b> ' + h(b.title) + '<span>' + b.files.length + ' file'
        + (b.files.length === 1 ? '' : 's') + ' · ' + crit(b) + '</span></div>').join('');
  }
  body.addEventListener('click', (ev) => {
    const g = ev.target.closest && ev.target.closest('.rv-cut');
    if (!g) return;
    card.innerHTML = cutCard(+g.dataset.cut, +g.dataset.r);
    card.hidden = !card.innerHTML;
    const w = Math.min(460, innerWidth - 24);
    card.style.left = Math.max(12, Math.min(ev.clientX - 40, innerWidth - w - 12)) + 'px';
    card.style.top = Math.max(12, Math.min(ev.clientY + 14, innerHeight - card.offsetHeight - 12)) + 'px';
    ev.stopPropagation();
  });
  card.addEventListener('click', (ev) => { if (ev.target.closest('.c-x')) card.hidden = true; ev.stopPropagation(); });
  document.addEventListener('click', () => { card.hidden = true; });
  // A block's name clicked: folded to a sliver, or opened again.
  body.addEventListener('click', (ev) => {
    const bk = ev.target.closest && ev.target.closest('.rv-bk[data-n]');
    const b = bk && blocksNow.find((x) => x.n === +bk.dataset.n);
    if (!b) return;
    if (folded.has(b.id)) folded.delete(b.id); else folded.add(b.id);
    try { localStorage.setItem(FOLDED, JSON.stringify([...folded])); } catch (e) {}
    hold.hide();
    draw();
  });
  // A jump's mark: to its other end, in the middle of the map, lit a moment.
  // To the place of round `r` in `file` holding a fix at `line` (a note's
  // link names it), else thread `rid`, else its first there, opening block
  // `unfold` first: the opened block groups its places afresh, so the place
  // is found again after the drawing.
  function goPlace(r, file, rid, unfold, line) {
    if (unfold) {
      folded.delete(unfold);
      try { localStorage.setItem(FOLDED, JSON.stringify([...folded])); } catch (e) {}
      draw();
    }
    const here = placesNow.filter((q) => q.ri === r && q.files.includes(file));
    const p = (line && here.find((q) => q.hs.some((x) => x.path === file && x.x === line)))
      || (rid && here.find((q) => q.th.some((t) => t.rid === rid) || q.hs.some((x) => x.thread === rid))) || here[0];
    return p && body.querySelector('.rv-fix[data-body][data-i="' + p.id + '"]');
  }
  function light(el) {
    if (!el) return;
    const r = el.getBoundingClientRect(), b = body.getBoundingClientRect();
    body.scrollBy({left: r.left + r.width / 2 - (b.left + b.width / 2), top: r.top + r.height / 2 - (b.top + b.height / 2), behavior: 'smooth'});
    el.classList.remove('rv-lit'); void el.getBoundingClientRect(); el.classList.add('rv-lit');
    setTimeout(() => el.classList.remove('rv-lit'), 1800);
  }
  body.addEventListener('click', (ev) => {
    const a = ev.target.closest && ev.target.closest('[data-go]');
    if (!a) return;
    ev.preventDefault();
    // Into a folded block: open it, then go to the place of that round
    // in the file it leads to that holds the thread.
    light(a.dataset.unfold ? goPlace(+a.dataset.r, a.dataset.file, a.dataset.rid, a.dataset.unfold) : body.querySelector('#' + a.dataset.go));
  });
  // The note's links to the same finding's fixes in other files.
  tip.addEventListener('click', (ev) => {
    const a = ev.target.closest && ev.target.closest('.t-go');
    if (!a) return;
    ev.preventDefault();
    light(goPlace(+a.dataset.r, a.dataset.file, a.dataset.rid, a.dataset.unfold, +a.dataset.line));
  });

  // The legend: a short name a kind, and on hover what it means (the
  // user's word, 2026-11-17: the screen keeps the names short).
  function legend() {
    const tl = (say) => ' title="' + h(say) + '"';
    const sw = (c, name, say, cls) => '<span class="rv-k' + (cls ? ' ' + cls : '') + '" style="--c:' + c + '"' + tl(say) + '>' + name + '</span>';
    const pat = (id, name, say, solid) => '<span class="rv-k"' + tl(say) + '><svg width="12" height="12"><rect width="12" height="12" fill="' + (solid ? colour('fixed', 1) : colour('side', 1))
      + '"' + (solid ? '' : ' fill-opacity=".28"') + '/><rect width="12" height="12" fill="url(#rv-lp-' + id + ')"/></svg>' + name + '</span>';
    const mark = (sign, name, say) => '<span class="rv-k rv-m"' + tl(say) + '><b>' + sign + '</b>' + name + '</span>';
    const group = (name, items) => '<span class="rv-lg"><i>' + name + '</i>' + items + '</span>';
    const lighter = dark() ? 'lighter' : 'darker';
    const ENDED = {
      fixed: 'A thread that was fixed: the colour of the lines changed for it, and of its dot.',
      declined: 'A finding left as it is, by decision: the reply says why.',
      yours: 'Left to you: the session would not decide it — or a night session did, for you to confirm — and handed it to the person.',
      reversal: 'A finding that would undo an earlier fix — a sign the review goes round in circles.',
      open: 'Still open: no outcome yet.',
      side: 'Changes no thread asked for: they came along with others, in the same commit.',
      moved: 'Code moved from one file to another — a removal there, the same lines written here. Not a fix and not new code: the icicle goes on from the file it came from.',
    };
    const NAME = {fixed: 'fixed', declined: 'declined', yours: 'yours', reversal: 'undoes a fix', open: 'open', side: 'no thread', moved: 'moved'};
    panel.querySelector('.rv-legend').innerHTML = '<svg width="0" height="0" style="position:absolute"><defs>' + patterns('rv-lp') + '</defs></svg>'
      + group('colour', sw(devColour(1), 'development', 'The development\'s code: written before the review, or asked for by the person during it (feat and Requirement: commits). Across the top, a file\'s band; below, the person\'s asks.')
        + Object.keys(NAME).map((k) => sw(colour(k, 1), NAME[k], (k === 'side' || k === 'moved' ? '' : 'How the thread ended — ') + ENDED[k])).join('')
        + sw(colour('fixed', 1), 'guessed', 'A dashed edge and a lighter fill: the fix is tied to its thread only by sitting near it in the same round — no reply named its commit and no subagent was given the thread. The colour is likely, not certain.', 'rv-gs'))
      + group('tone', '<span class="rv-k rv-steps"' + tl(lighter[0].toUpperCase() + lighter.slice(1) + ' the more earlier rounds had already rewritten the same lines: 0, 1, 2, 3 or more, weighted by how many of the place\'s lines they were. A spot that keeps being rewritten is where review circles.') + '>'
        + [0, 1, 2, 3].map((k) => '<i style="background:' + colour('fixed', k) + '"></i>').join('') + ' rewrites</span>')
      + group('fill', pat('schema', 'code', 'Solid: code changed there. The \\ hatching: a migration among it.', true)
        + '<span class="rv-k rv-hol" style="--c:' + colour('fixed', 1) + '"' + tl('Hollow: no code or migration changed — only what its patterns say: tests, docs and config, comments. Usually polishing.') + '>hollow</span>'
        + pat('test', 'tests', 'The / hatching: tests were changed there.') + pat('doc', 'docs', 'The — lines: docs or config files were changed there.')
        + pat('comment', 'comments', 'The dots: only comments were changed there.'))
      + group('shape', '<span class="rv-k rv-uk"' + tl('A dashed outline, faintly filled: no round has opened that code since its fix — it is still unchecked, and its whole width waits for a reading.') + '>unread</span>'
        + '<span class="rv-k rv-stk"' + tl('A thin stem: rounds that left that code alone, between a fix and the next one there or the round that read it. Nothing happened in those rows.') + '>quiet</span>'
        + mark('✕', 'removed', 'A line and a ✕ at the foot of a round\'s row: the round\'s fixes removed the file. Where its code was moved, the hover says, and the icicle goes on there.')
        + mark('▼', 'done', 'Closed to a point in the row of the round that read it and found nothing: every thread of it has an outcome, and its fixing ended.')
        + mark('⋯', 'closing', 'A dashed point: the round still fixing read it and found nothing; it closes once that fixing ends, unless a fix lands here.')
        + '<span class="rv-k rv-mk"' + tl('Purple: a check that missed. A round read a fixed problem\'s icicle, found nothing and closed it; a later round found a problem on the very lines those fixes wrote. The bar marks the round that passed it, the ring the thread found later. A problem elsewhere starts an icicle of its own.') + '>missed</span>'
        + '<span class="rv-k rv-steps"' + tl('Behind the rounds\' names, and in a folded block: every file summed in one icicle. Left of its axis the development\'s code a round touched, right the review\'s own — leaning right, review is polishing its own work. The thin line: right where the round grew the code, left where it shrank it, ' + lighter + ' the more threads review posted (0, 1–2, 3–5, 6+).') + '>'
        + [0, 1, 2, 3].map((k) => '<i style="background:' + netTone(k) + '"></i>').join('') + ' sum</span>')
      + group('nothing found', sw('', 'whole', 'A thick green line under a file: that round read the whole file (or the block\'s whole change) and found nothing in it.', 'rv-ck')
        + sw('', 'last fixes', 'A thin blue line: that round read only the last fixes\' change in the file and found nothing.', 'rv-dk')
        + sw('', 'a part', 'A dashed yellow line: that round looked at a part of the file and found nothing.', 'rv-pk'));

  }
  legend();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { legend(); draw(); });

  // --- the controls --------------------------------------------------------
  // The title's note: the blocks' table, what is left of the development.
  const title = panel.querySelector('.rv-top h3');
  // A phone has no hover: a tap (or focus from the keyboard) opens it too.
  const titleNote = (ev) => {
    const html = blocksTable(), r = title.getBoundingClientRect();
    // A focus has no pointer: the note goes under the title.
    if (html) hold.show('title', () => html, {clientX: ev.clientX || r.left + 20, clientY: ev.clientY || r.bottom}, title);
  };
  title.tabIndex = 0;
  title.addEventListener('mouseover', titleNote);
  title.addEventListener('click', titleNote);
  title.addEventListener('focus', titleNote);
  title.addEventListener('mouseleave', () => hold.leave());
  title.addEventListener('blur', () => hold.leave());
  panel.querySelector('.rv-off').addEventListener('click', () => {
    off = true; maxed = false;
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
    // Full screen, for the page's address: asked, and restored from a link.
    full: (on) => { if (on === undefined) return maxed; maxed = !!on; if (shown) full(maxed); },
  };
})();
window.reviewMap = reviewMap;
