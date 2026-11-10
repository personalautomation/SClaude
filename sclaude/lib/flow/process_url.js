// The page's state in its address, kept as it changes, so that a link opens
// the page as it was seen: the section in view (`s`), the metrics ticked
// above the maps (`show`), the panel's tab (`tab`), the commands pinned
// (`pin`), what is selected (`sel`, the elements' keys), and a play — which
// map (`play`), which pass on a map of passes (`pass`), the place it is at
// (`at`, its index in the play), its speed (`speed`), "this map only"
// (`only`) and paused (`paused`). In the hash: nothing of it goes to sclaude,
// and a change does not load the page again. A hash naming a section alone
// (the legend's links) is read as `s`.
(() => {
  const SECTIONS = () => [...document.querySelectorAll('main h2[id], main section[id]')];
  function read() {
    const h = location.hash.slice(1);
    if (!h) return new URLSearchParams();
    if (!h.includes('=')) return new URLSearchParams({s: decodeURIComponent(h)});
    return new URLSearchParams(h);
  }
  // The section whose top has passed the top of the window last.
  function inView() {
    let out = '';
    SECTIONS().forEach((el) => { if (el.getBoundingClientRect().top <= 90) out = el.id; });
    return out;
  }
  function state() {
    const p = new URLSearchParams();
    const s = inView();
    if (s) p.set('s', s);
    const show = [...document.querySelectorAll('.metrics input:checked')].map((c) => c.value);
    if (show.length) p.set('show', show.join(','));
    const tab = document.querySelector('.tabs button.on');
    if (tab && tab.dataset.tab !== 'actions') p.set('tab', tab.dataset.tab);
    const dock = document.getElementById('dock');
    if (dock) p.set('pin', dock.hidden ? '0' : '1');
    const sel = window.processMap ? window.processMap.selected() : [];
    if (sel.length) p.set('sel', sel.join(','));
    const play = window.player && window.player.state();
    if (play) {
      p.set('play', play.map);
      if (play.pass != null) p.set('pass', play.pass);
      p.set('at', play.at);
      if (play.speed !== 1) p.set('speed', play.speed);
      if (play.only) p.set('only', '1');
      if (play.paused) p.set('paused', '1');
    }
    return p.toString();
  }
  const wanted = read();
  // What the link restores is not saved as this browser's own choice; a
  // link that names what the page lacks restores the rest.
  window.processUrlRestoring = true;
  try {
    // Read before the page sets itself up from what this browser kept: the
    // address wins over it.
    if (wanted.has('show')) {
      const on = wanted.get('show').split(',');
      document.querySelectorAll('.metrics input').forEach((c) => {
        if (c.checked !== on.includes(c.value)) { c.checked = on.includes(c.value); c.dispatchEvent(new Event('change')); }
      });
    }
    if (wanted.get('tab')) {
      const b = document.querySelector('.tabs button[data-tab="' + CSS.escape(wanted.get('tab')) + '"]');
      if (b) b.click();
    }
    if (wanted.has('pin')) {
      const dock = document.getElementById('dock');
      if (dock && dock.hidden === (wanted.get('pin') === '1')) {
        const b = document.querySelector('.pin');
        if (b) b.click();
      }
    }
  } finally {
    window.processUrlRestoring = false;
  }
  if (wanted.get('sel') && window.processMap) window.processMap.select(wanted.get('sel').split(','));
  if (wanted.get('play') && window.player) {
    window.player.want({map: wanted.get('play'), pass: wanted.get('pass'), at: +wanted.get('at') || 0,
      speed: +wanted.get('speed') || 1, only: wanted.get('only') === '1', paused: wanted.get('paused') === '1'});
  }
  // The section last, once the page is laid out; a play brings its own place
  // into view instead.
  const section = wanted.get('s');
  window.processUrl = {section: section || ''};
  if (section && !wanted.get('play')) {
    const go = () => { const el = document.getElementById(section); if (el) el.scrollIntoView({block: 'start'}); };
    requestAnimationFrame(go);
    // Again once the first state has drawn the panel and the metrics.
    setTimeout(go, 400);
  }
  // Written as it changes: a look twice a second costs nothing, and catches
  // every way the page changes without a hook in each.
  let last = state();
  setInterval(() => {
    const now = state();
    if (now === last) return;
    last = now;
    history.replaceState(null, '', location.pathname + location.search + (now ? '#' + now : ''));
  }, 500);
  // A legend's link to a section: read as a section, then written back whole.
  addEventListener('hashchange', () => {
    const p = read();
    if (p.get('s') && !location.hash.includes('=')) {
      const el = document.getElementById(p.get('s'));
      if (el) el.scrollIntoView({block: 'start'});
    }
  });
})();
