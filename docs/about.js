/* "Ilia Poliakov" in the nav: one slide about the author, shown in a
   rounded dialog over the page. Shared by index.html and contact.html, which
   carry only the link (data-about); the slide and its styles live here so the
   two pages cannot drift apart. The dialog is dark in both themes, like the
   landing page's hero and the decks. */
(function(){
  var CV = 'media/cv/Ilia_Poliakov_CV.pdf';
  var HASH = '#about';
  var pushed = false;
  var LINKEDIN = 'https://www.linkedin.com/in/poliakovilia/';
  var LI_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="currentColor"><path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 110-4.13 2.06 2.06 0 010 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z"/></svg>';

  var SLIDE =
    '<div class="ab-grid">' +
      '<div class="ab-who">' +
        '<p class="ab-kick">About the author</p>' +
        '<h2 id="ab-title">Ilia Poliakov</h2>' +
        '<p class="ab-sub">Where delivery management meets <em>technology</em>.</p>' +
        '<p>Over fifteen years as an IT Project/Program Manager on client and in-house projects and products: helping teams work efficiently, spotting dependencies early, clearing blockers and delivering on time and within budget.</p>' +
        '<p>A bridge between business and engineering teams who owns the outcome and makes sure the goal is reached.</p>' +
        '<div class="ab-stats"><div><b>15+</b><span>years in delivery</span></div><div><b>50+</b><span>projects</span></div><div><b>4</b><span>years as PMO Director</span></div></div>' +
        '<p class="ab-chips"><span>PMP®</span><span>PME®</span><span>Scrum certified</span><span>Mathematician who codes</span></p>' +
      '</div>' +
      '<ol class="ab-path">' +
        '<li class="ab-old"><i>2007 \u2013 2025</i><b>Expert in project delivery and process automation</b></li>' +
        '<li><i>2023 \u00b7 First AI project</i><b>A client asked for AI</b><span>The brief was an AI-powered, RAG-based chat that answers from the product’s own data. That is how my team and I went deep into AI.</span></li>' +
        '<li><i>2025 · AI lab</i><b>Led the AI transformation</b><span>As the only manager in the company with hands-on AI experience, I ran the AI lab: agentic proofs of concept for incident prioritisation, autoscaling driven by AWS logs, test-impact analysis and process QA, plus Claude Code MVPs that generate code from specifications.</span></li>' +
        '<li class="ab-now"><i>2026 · SClaude</i><b>Experience, turned into a method</b><span>Working on both sides, technical and managerial, I created SClaude: where vibe coding meets process and scalability, with guardrails, metrics, feedback loops and best-practice sharing.</span></li>' +
      '</ol>' +
    '</div>' +
    '<div class="ab-cta">' +
      '<a class="ab-btn ab-primary" href="' + LINKEDIN + '" target="_blank" rel="noopener">' + LI_ICON + 'Connect on LinkedIn</a>' +
      '<a class="ab-btn" href="' + CV + '" target="_blank" rel="noopener">Download CV (PDF)</a>' +
      '<a class="ab-btn" href="contact.html">Contact</a>' +
    '</div>';

  var CSS = '' +
  'body.ab-open{overflow:hidden}' +
  '.ab-dlg{border:0;padding:0;background:transparent;color:#EEF1F6;width:min(1100px,calc(100vw - 32px));max-width:none;max-height:calc(100dvh - 32px);overflow:visible}' +
  '.ab-dlg::backdrop{background:rgba(4,8,16,.72);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}' +
  '.ab-dlg[open]{animation:ab-in .28s ease-out}' +
  '@keyframes ab-in{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:none}}' +
  '.ab-card{position:relative;background:#081321;border:1px solid #1F2A40;border-radius:28px;overflow:hidden;box-shadow:0 30px 80px rgba(0,0,0,.5);max-height:calc(100dvh - 32px);font:16px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}' +
  '.ab-card::before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(620px 320px at 90% 0%,rgba(0,240,200,.16),transparent 60%),radial-gradient(520px 300px at 0% 100%,rgba(99,102,241,.14),transparent 60%)}' +
  '.ab-card::after{content:"";position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(#1F2A40 1px,transparent 1px),linear-gradient(90deg,#1F2A40 1px,transparent 1px);background-size:48px 48px;opacity:.3;-webkit-mask-image:linear-gradient(to bottom,#000,transparent 60%);mask-image:linear-gradient(to bottom,#000,transparent 60%)}' +
  '.ab-body{position:relative;z-index:1;overflow-y:auto;max-height:calc(100dvh - 34px);padding:40px 48px 22px}' +
  '.ab-x{position:absolute;z-index:2;top:16px;right:16px;width:38px;height:38px;border-radius:50%;border:1px solid #33405C;background:rgba(8,19,33,.7);color:#EEF1F6;font-size:20px;line-height:1;cursor:pointer}' +
  '.ab-x:hover{background:#141D30}' +
  '.ab-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:44px;align-items:start}' +
  '.ab-kick{margin:0;font:500 12px/1 "JetBrains Mono",ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:#00F0C8}' +
  '.ab-who h2{font:400 clamp(42px,5.6vw,64px)/1 "Instrument Serif",Georgia,serif;letter-spacing:-.02em;margin:14px 0 10px;color:#EEF1F6}' +
  '.ab-sub{font:400 clamp(20px,2.2vw,24px)/1.25 "Instrument Serif",Georgia,serif;color:#EEF1F6;margin:0 0 14px}' +
  '.ab-sub em{font-style:italic;color:#00F0C8}' +
  '.ab-who p{color:#B4BDCE;margin:0 0 10px}' +
  '.ab-stats{display:flex;gap:10px;margin:20px 0}' +
  '.ab-stats div{flex:1;border:1px solid #1F2A40;border-radius:16px;padding:12px 14px;background:rgba(255,255,255,.03)}' +
  '.ab-stats b{display:block;font:400 36px/1 "Instrument Serif",Georgia,serif;color:#00F0C8}' +
  '.ab-stats span{display:block;margin-top:6px;font-size:13px;color:#9AA4B8}' +
  '.ab-chips{display:flex;flex-wrap:nowrap;gap:6px;margin:0}' +
  '.ab-chips span{white-space:nowrap;font-size:12.5px;color:#D6DEEA;padding:5px 10px;border:1px solid #33405C;border-radius:999px;background:rgba(255,255,255,.03)}' +
  '.ab-path{list-style:none;margin:6px 0 0;padding:0 0 0 22px;border-left:1px solid #33405C}' +
  '.ab-path li{position:relative;margin:0 0 22px}' +
  '.ab-path li:last-child{margin:0}' +
  '.ab-path li::before{content:"";position:absolute;left:-28px;top:3px;width:11px;height:11px;border-radius:50%;background:#081321;border:2px solid #5F6B85}' +
  '.ab-path .ab-now::before{background:#00F0C8;border-color:#00F0C8;box-shadow:0 0 14px #00F0C8}' +
  '.ab-path i{display:block;font:500 11px/1 "JetBrains Mono",ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:#9AA4B8;font-style:normal}' +
  '.ab-path .ab-now i{color:#00F0C8}' +
  '.ab-path .ab-old b{color:#CDD4E0}' +
  '.ab-path b{display:block;margin:7px 0 4px;font-size:17px;color:#EEF1F6}' +
  '.ab-path span{display:block;font-size:14.5px;color:#B4BDCE}' +
  '.ab-cta{display:flex;flex-wrap:wrap;gap:10px;margin-top:30px;padding-top:24px;border-top:1px solid #1F2A40}' +
  '.ab-btn{display:inline-flex;align-items:center;gap:8px;padding:11px 18px;border-radius:999px;font-weight:600;font-size:14px;color:#EEF1F6;border:1px solid #33405C;text-decoration:none}' +
  '.ab-btn:hover{background:#141D30;text-decoration:none}' +
  '.ab-primary{background:#00F0C8;color:#04201C;border-color:#00F0C8}' +
  '.ab-primary:hover{background:#5CF5DA}' +
  '@media (max-width:820px){.ab-chips{flex-wrap:wrap}.ab-grid{grid-template-columns:1fr;gap:28px}.ab-body{padding:32px 20px 24px}.ab-card{border-radius:22px}.ab-stats b{font-size:30px}}' +
  '@media (prefers-reduced-motion: reduce){.ab-dlg[open]{animation:none}}';

  function build(){
    var st = document.createElement('style'); st.textContent = CSS; document.head.appendChild(st);
    var d = document.createElement('dialog');
    d.className = 'ab-dlg'; d.setAttribute('aria-labelledby', 'ab-title');
    d.innerHTML = '<div class="ab-card"><button class="ab-x" type="button" aria-label="Close">×</button><div class="ab-body">' + SLIDE + '</div></div>';
    document.body.appendChild(d);
    d.querySelector('.ab-x').onclick = function(){ d.close(); };
    // A click on the backdrop lands on the dialog itself, outside the card.
    d.addEventListener('click', function(e){ if (e.target === d) d.close(); });
    d.addEventListener('close', function(){
      document.body.classList.remove('ab-open');
      // Opened here: step back over our own entry. Opened from a link: drop the hash.
      if (location.hash === HASH){ if (pushed){ pushed = false; history.back(); } else history.replaceState(null, '', location.pathname + location.search); }
    });
    return function(){
      if (location.hash !== HASH){ history.pushState(null, '', HASH); pushed = true; }
      if (!d.open){ document.body.classList.add('ab-open'); d.showModal(); d.querySelector('.ab-x').focus(); }
    };
  }

  var open = null;
  var dialogs = typeof HTMLDialogElement !== 'undefined';
  document.querySelectorAll('[data-about]').forEach(function(a){
    a.addEventListener('click', function(e){
      if (!dialogs) return;  // the link to the CV still works
      e.preventDefault();
      (open = open || build())();
    });
  });
  // The dialog has an address of its own, so a link can open it; Back closes it.
  if (dialogs){
    if (location.hash === HASH) (open = open || build())();
    window.addEventListener('popstate', function(){
      var d = document.querySelector('.ab-dlg');
      if (location.hash === HASH) (open = open || build())();
      else if (d && d.open){ pushed = false; d.close(); }
    });
  }
})();
