
const label = /*LABEL*/;
const POS = /*POSITIONS*/;
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
    // R also on the glance's block the place is lit on (POS), for a place
    // no block there borrows: step 4's close turns 4 · review. Not F: a
    // fix block's POS is step 2's, though its friction may follow step 4.
    [id].concat(M.alias[id] || [], f === 'R' ? POS[id] || [] : []).forEach((at) =>
    document.querySelectorAll('svg.map [data-node="' + at + '"] .b-' + f).forEach((b) => {
      // On hover, how it goes now, under why it is there: each place's note
      // added, where two places turn the same letter of one block.
      const note = ((v.notes || {})[id] || {})[f];
      const t = b.querySelector('title');
      t.textContent = (b.classList.contains('busy') ? t.textContent : b.dataset.why) + (note ? '\n' + note : '');
      b.classList.add('busy');
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
    // also: a block of a smaller map the place stands on meanwhile (a
    // local run at step 4 on the regression map).
    [here].concat(POS[here] || (here === 'sync' ? syncAt.flatMap((id) => POS[id] || []) : []), v.also || []).forEach((id) =>
      document.querySelectorAll('svg.map [data-node="' + id + '"]').forEach((n) => n.classList.add('here')));
  }
  if (here && here !== last) {
    // On the whole process, or on the map of its own a place has (R, S).
    const n = document.querySelector('svg.map-detail [data-node="' + here + '"]')
      || document.querySelector('svg.map [data-node="' + here + '"]');
    // Down to it only: centred across as well, the card scrolled the map's
    // first lanes off its left edge with no way to tell they were there.
    // Not over a section or a play the address asked for (process_url.js).
    if (n && last === '' && !(window.processUrl && window.processUrl.section) && !location.hash.includes('play='))
      n.scrollIntoView({block: 'center', inline: 'nearest'});
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
