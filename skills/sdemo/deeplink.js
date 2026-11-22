// A place in a demo's video, in the page's address: #v=<video>&t=<seconds>.
// Inlined into both demo pages — the feature's page (write_feature_page in
// demo.py) and one demo's page (player.html, filled by play.mjs) — and run
// once the page's videos are in it. A video takes part when it has
// data-v="<id>", unique on its page.
//
// Playing, seeking or pausing writes the place into the address, so the
// address bar is always a link to what is on the screen; opened, the link
// seeks that video there, paused. Each video gets a copy button over its
// corner, and a full-screen button that puts the video and the copy button
// on the screen together: the browser's own full screen shows the video
// alone, and the person tells Claude about a place mostly from there. On
// the screen it takes the keys as a video's own full screen does: space or
// k, the arrows or j and l, m, f. A click on the picture plays and pauses,
// on the page and on the screen alike.
//
// Play in a row, a checkbox put into the page's <h1> (on by default, kept
// in localStorage): a video that ends starts the next one, on the page and
// on the screen, within its section (data-row: the feature's page marks
// each version so; the end of one is no cue for the next). ⏮ and ⏭ over each video (Shift+P, Shift+N) start the one
// before or after it, on the page and on the screen alike. Only one video
// plays at a time: one that starts pauses every other.
//
// A video whose scenario ends in a case for the person to try by hand
// (data-hand: its steps, files and links, and `at`, the second the
// recording handed over) shows that case beside the picture in full screen
// from that second: the video narrows and a panel slides in on the right
// for HAND_SHOW seconds, then slides back out — seconds of the clock, since
// the case often comes as the video ends. Nothing waits for the person:
// the video and the row play on. Back before that second, it comes again.
//
// 📍 then a click on the frame puts a point in the address too: p=<x>,<y>,
// in per cent of the video's own frame from its top left corner — not of the
// screen or the element, so the same link points at the same thing on any
// screen and at any size, and the frame at t= can be cut out with ffmpeg
// and looked at there. Playing on takes the point away: it was about that
// frame, and so does a seek to another one. The link is copied as soon as
// the point is put: what is pointed at is what will be said.
//
// The product's page the video shows at that second goes in as u=<path>:
// each step was recorded with its address, and a video with
// data-pages='[[t, url], …]' (the scenario's start at 0) names the one
// under way — the path alone, since the host is wherever the person opens
// the feature from.
(() => {
  const css = document.createElement("style");
  css.textContent = `
.vw{position:relative;display:block}
.vw.phone{width:fit-content;max-width:100%;margin:0 auto}
.vw .vb{position:absolute;top:8px;right:8px;display:flex;gap:6px;z-index:2;opacity:.75;transition:opacity .15s}
.vw:hover .vb,.vw .vb:focus-within{opacity:1}
.vw .vb button{font:600 13px/1 system-ui,sans-serif;color:#fff;background:rgba(0,0,0,.6);border:1px solid rgba(255,255,255,.35);
border-radius:8px;padding:6px 9px;cursor:pointer;font-variant-numeric:tabular-nums}
.vw .vb button:hover{background:rgba(0,0,0,.85)}
.vw video::-webkit-media-controls-fullscreen-button{display:none}
.vw .pick{position:absolute;inset:0;z-index:1;cursor:crosshair;display:none}
.vw.picking .pick{display:block}
.vw.picking .vb .pin{background:#dc2626}
.vw .dot{position:absolute;z-index:1;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
border:3px solid #fff;background:rgba(220,38,38,.85);box-shadow:0 0 0 2px #dc2626,0 0 12px rgba(0,0,0,.6);pointer-events:none;display:none}
/* Under the buttons, off the middle, where the point usually is. */
.vw .toast{position:absolute;left:50%;top:48px;transform:translateX(-50%);z-index:3;max-width:90%;
font:600 15px/1.4 system-ui,sans-serif;color:#fff;background:rgba(0,0,0,.82);border-radius:10px;padding:10px 16px;
text-align:center;pointer-events:none;opacity:0;transition:opacity .2s}
.vw .toast.on{opacity:1}
/* The steps' strip under the video; see steps(). */
.vw .vs{position:relative;padding:7px 0 3px;cursor:pointer;touch-action:pan-y}
.vw .vs .tr{position:relative;height:8px;transition:height .1s}
.vw .vs:hover .tr{height:12px}
.vw .vs i{position:absolute;top:0;bottom:0;border-left:2px solid transparent;background-clip:padding-box;
background-color:rgba(120,113,108,.35);border-radius:3px;overflow:hidden}
.vw .vs i:first-child{border-left:0}
.vw .vs i.bad{background-color:rgba(220,38,38,.35)}
.vw .vs i b{display:block;height:100%;background:#2563eb}
.vw .vs i.bad b{background:#dc2626}
.vw .vs i.now{box-shadow:inset 0 0 0 1px rgba(37,99,235,.7)}
.vw .vs .tip{position:absolute;bottom:100%;left:0;z-index:4;max-width:280px;padding:6px 8px;
border-radius:8px;background:rgba(0,0,0,.88);color:#fff;font:600 12px/1.35 system-ui,sans-serif;display:none;
cursor:text;user-select:text;-webkit-user-select:text;touch-action:auto}
.vw .vs .tip.on{display:block}
.vw .vs .tip canvas{display:none;border-radius:4px;margin:0 auto 5px}
.vw .vs .tip.pic canvas{display:block}
.vw .lk{font-weight:400;opacity:.85}
/* The step under way over the picture: full screen hides the steps beside it. */
.vw .cap{position:absolute;left:12px;top:12px;z-index:3;max-width:min(560px,70%);padding:8px 12px;border-radius:10px;
background:rgba(0,0,0,.78);color:#fff;font:600 16px/1.4 system-ui,sans-serif;pointer-events:none;opacity:0;transition:opacity .25s;
cursor:text;user-select:text;-webkit-user-select:text}
.vw .cap.on{opacity:1;pointer-events:auto}
/* Full screen is the stage's, with the video's wrapper moved into it: see enter(). */
.vstage{display:none}
.vstage:fullscreen{display:flex;background:#000;width:100%;height:100%}
.vstage:-webkit-full-screen{display:flex;background:#000;width:100%;height:100%}
/* In the window: the stage over the page, the browser's own bar and tools left. */
.vstage.inwin{display:flex;position:fixed;inset:0;z-index:2147483000;background:#000;width:100%;height:100%}
html.sdemo-inwin{overflow:hidden}
.vstage .vw{flex:1;min-width:0;display:flex;flex-direction:column;width:100%;max-width:none;margin:0}
.vstage .vw video{flex:1;min-height:0;width:100%;height:auto;max-width:none;max-height:none;object-fit:contain;border-radius:0}
.vstage .vw .vs{flex:none;padding:8px 16px 12px}
/* Play in a row: the checkbox in the page's heading, and its copy on the
   buttons over a video in full screen, where the heading is not in view. */
label.inrow{display:inline-flex;align-items:center;gap:5px;margin-left:14px;vertical-align:middle;
font:400 13px/1 system-ui,sans-serif;color:inherit;opacity:.8;cursor:pointer;user-select:none;white-space:nowrap}
label.inrow input{margin:0;cursor:pointer}
.vw .vb .nx{display:none}
.vstage .vw .vb .nx{display:inline-block}
.vw .vb .nx.on{background:rgba(37,99,235,.85)}
.vw .vb button:disabled{opacity:.35;cursor:default}
/* The by-hand case beside the picture in full screen; see handView(). */
.vw .hp{display:none}
.vstage .vw{--hw:min(440px,36%);transition:padding-right .45s ease;overflow:hidden}
.vstage .vw.handon{padding-right:var(--hw)}
.vstage .vw.handon .vb{right:calc(var(--hw) + 8px)}
.vstage .vw .hp{display:block;transform:translateX(100%);transition:transform .45s ease}
.vstage .vw.handon .hp{transform:none}
.vw .hp{position:absolute;top:0;right:0;bottom:0;width:var(--hw);overflow:auto;box-sizing:border-box;padding:22px 20px;
background:#111827;color:#f9fafb;font:15px/1.5 system-ui,sans-serif;border-left:1px solid rgba(255,255,255,.15)}
.vw .hp h3{margin:0 0 6px;font-size:18px}
.vw .hp .why{color:#d1d5db;font-size:14px;margin:0 0 10px}
.vw .hp ol{margin:10px 0;padding:0 0 0 22px;list-style:decimal}
.vw .hp li{display:list-item;margin:6px 0;padding:0;border-radius:0;background:none;cursor:auto}
.vw .hp .ex{color:#a7f3d0;font-size:14px}
.vw .hp a{color:#93c5fd;display:block;margin:4px 0}
.vw .vb button:disabled:hover{background:rgba(0,0,0,.6)}`;
  document.head.appendChild(css);

  const clock = (t) => Math.floor(t / 60) + ":" + String(Math.floor(t % 60)).padStart(2, "0");
  // 83, 83.4 or 1:23 — what a person may type by hand too.
  const seconds = (s) => {
    if (!s) return 0;
    const parts = String(s).split(":").map(Number);
    if (parts.some((n) => !isFinite(n))) return 0;
    return parts.reduce((a, n) => a * 60 + n, 0);
  };
  const parse = () => {
    const p = new URLSearchParams(location.hash.slice(1));
    const at = (p.get("p") || "").split(",").map(Number);
    return {v: p.get("v"), t: seconds(p.get("t")),
      p: at.length === 2 && at.every((n) => isFinite(n) && n >= 0 && n <= 100) ? at : null};
  };

  // Where the frame is inside the element: object-fit contain leaves bars
  // on two sides, and a point is about the picture, not the bars.
  function frame(video) {
    const r = video.getBoundingClientRect();
    const k = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : r.width / r.height;
    let w = r.width, h = r.width / k;
    if (h > r.height) { h = r.height; w = h * k; }
    return {left: r.left + (r.width - w) / 2, top: r.top + (r.height - h) / 2, w, h};
  }
  function place(video) {
    const dot = video.parentNode.querySelector(".dot");
    if (!video.point) { dot.style.display = "none"; return; }
    const f = frame(video), box = video.parentNode.getBoundingClientRect();
    dot.style.left = (f.left - box.left + f.w * video.point[0] / 100) + "px";
    dot.style.top = (f.top - box.top + f.h * video.point[1] / 100) + "px";
    dot.style.display = "block";
  }

  function pageAt(video) {
    let pages = video.pages;
    if (!pages) {
      try { pages = JSON.parse(video.dataset.pages || "[]"); } catch { pages = []; }
      video.pages = pages;
    }
    let url = "";
    for (const [t, u] of pages) if (t <= video.currentTime + 0.2 && u) url = u;
    try { const x = new URL(url); return x.pathname + x.search + x.hash; } catch { return url; }
  }

  let last = 0;
  function mark(video, now) {
    // The browser limits how often the address may change; a second is fine.
    if (!now && Date.now() - last < 1000) return;
    last = Date.now();
    const t = Math.round(video.currentTime * 10) / 10;
    const q = {v: video.dataset.v, t: String(t)};
    if (video.point) q.p = video.point.join(",");
    const page = pageAt(video);
    if (page) q.u = page;
    // A slash, a comma and a question mark need no escaping in a hash, and
    // the path reads better without it.
    const hash = "#" + new URLSearchParams(q).toString().replace(/%2C|%2F|%3F/g, decodeURIComponent);
    if (location.hash !== hash) history.replaceState(history.state, "", hash);
  }

  async function copy(video, button) {
    mark(video, true);
    const text = location.href;
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch {}
    if (!ok) {
      // Off a secure origin there is no clipboard API: the old way, from a
      // field put in the wrapper, which is what is on the screen in full screen.
      const field = document.createElement("textarea");
      field.value = text;
      field.style.cssText = "position:absolute;opacity:0;left:0;top:0";
      button.parentNode.appendChild(field);
      field.select();
      try { ok = document.execCommand("copy"); } catch {}
      field.remove();
    }
    button.textContent = ok ? "✓ copied" : "✗ not copied";
    setTimeout(() => { button.textContent = "🔗 " + clock(video.currentTime); }, 1200);
    const toast = button.closest(".vw").querySelector(".toast");
    toast.textContent = ok
      ? "✓ Link copied: " + clock(video.currentTime) + (video.point ? ", with the point" : "") +
        " — paste it to Claude with your remark"
      : "✗ Not copied — the link is in the address bar";
    toast.classList.add("on");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => toast.classList.remove("on"), 2200);
  }

  // Full screen goes to one stage for the page, with the video's wrapper
  // moved into it and a placeholder of its size left in the page. The next
  // video played in a row takes the wrapper's place on the stage: the
  // browser lets a page ask for full screen only on a click, and the end of
  // a video is none, so the element on the screen stays the same.
  const stage = document.createElement("div");
  stage.className = "vstage";
  document.body.appendChild(stage);
  const held = document.createElement("div");
  const screenEl = () => document.fullscreenElement || document.webkitFullscreenElement;
  // The stage in the window (W, ▣): over the page, with no Fullscreen API,
  // so the browser's address bar and tools stay in view.
  const inWin = () => stage.classList.contains("inwin") && !screenEl();
  // The video's wrapper on the screen or in the window, or what else is on
  // the screen (a video alone).
  const full = () => {
    const f = screenEl();
    return f === stage || inWin() ? stage.firstElementChild : f;
  };
  const resync = () => { for (const f of syncs) f(); };
  function winMark(on) {
    stage.classList.toggle("inwin", on);
    document.documentElement.classList.toggle("sdemo-inwin", on);
  }
  // Each wrapper's buttons and caption follow whether it is on the screen;
  // a swap on the stage is no fullscreenchange, so it tells them itself.
  const syncs = [];
  function onStage(wrap) {
    if (stage.firstElementChild === wrap) return;
    offStage();
    held.style.height = wrap.offsetHeight + "px";
    wrap.replaceWith(held);
    stage.appendChild(wrap);
    for (const f of syncs) f();
  }
  function offStage() {
    const wrap = stage.firstElementChild;
    if (wrap && held.parentNode) held.replaceWith(wrap);
    for (const f of syncs) f();
  }
  // Whether the whole screen was asked for from the window: leaving it goes
  // back there, as W from the whole screen does.
  let fromWin = false;
  function enter(wrap) {
    const go = stage.requestFullscreen || stage.webkitRequestFullscreen;
    const wasWin = inWin();
    if (!go) {
      // An iPhone puts only a video on the whole screen, and says nothing
      // when it leaves it: the video goes back to the page first.
      if (wasWin) { winMark(false); offStage(); }
      const video = wrap.querySelector("video");
      if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
      return;
    }
    // From the window to the whole screen: the wrapper stays on the stage.
    fromWin = wasWin;
    winMark(false);
    onStage(wrap);
    const asked = go.call(stage);
    // Refused: where the person was — the window, or the page.
    if (asked && asked.catch) asked.catch(() => {
      if (screenEl()) return;
      fromWin = false;
      if (wasWin) { winMark(true); resync(); } else offStage();
    });
  }
  function toggle(wrap) {
    if (screenEl()) return (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    enter(wrap);
  }
  // W, ▣: in the window, or back to the page; from the whole screen, down
  // to the window rather than out of it.
  function winToggle(wrap) {
    if (inWin() && stage.firstElementChild === wrap) {
      winMark(false);
      offStage();
      return;
    }
    const f = screenEl();
    winMark(true);
    // The stage on the screen goes down to the window as it is; a video the
    // browser put there alone (its own button) comes onto the stage first,
    // or the window would be an empty black stage.
    if (f === stage) {
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
      return;
    }
    if (f) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    if (stage.firstElementChild === wrap) resync();
    else onStage(wrap);
  }
  for (const ev of ["fullscreenchange", "webkitfullscreenchange"])
    document.addEventListener(ev, () => {
      if (screenEl() === stage) return;
      // Back from the whole screen to the window it was asked for from.
      if (fromWin) { fromWin = false; winMark(true); }
      // Down to the window (winToggle, or the line above): the wrapper stays.
      if (stage.classList.contains("inwin")) resync();
      else offStage();
    });
  // A version unfolded or folded changes which videos are next door (⏮ ⏭).
  document.addEventListener("toggle", (e) => { if (e.target.tagName === "DETAILS") for (const f of syncs) f(); }, true);

  // Play in a row: once a video ends the next one on the page starts, in
  // full screen as out of it. The next is the next in the page that has a
  // video to play and is not folded away in a closed <details> (the
  // feature's earlier versions). On by default; the choice is remembered.
  const ROW_KEY = "sclaude-demo-in-row";
  let inRow = true;
  try { inRow = localStorage.getItem(ROW_KEY) !== "0"; } catch {}
  const rowViews = [];
  function setRow(on) {
    inRow = on;
    try { localStorage.setItem(ROW_KEY, on ? "1" : "0"); } catch {}
    for (const f of rowViews) f();
  }
  const hasSource = (v) => v.getAttribute("src") || v.querySelector("source");
  const playable = (v) => !v.closest("details:not([open])") && hasSource(v);
  // The row's controls only where there is a next video; one folded away
  // counts, since its version can be opened.
  const many = [...document.querySelectorAll("video[data-v]")].filter(hasSource).length > 1;
  // In the page's order, the one on the stage counted where its placeholder is.
  const spot = (v) => (stage.contains(v) ? held : v);
  function ordered() {
    return [...document.querySelectorAll("video[data-v]")].sort((a, b) => a === b ? 0 :
      spot(a).compareDocumentPosition(spot(b)) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
  }
  function nextOf(video) {
    const all = ordered();
    return all.slice(all.indexOf(video) + 1).find(playable) || null;
  }
  function prevOf(video) {
    const all = ordered();
    return all.slice(0, all.indexOf(video)).reverse().find(playable) || null;
  }
  const PRESS_PLAY = "▶ Press play to go on";
  // How long the by-hand panel stays beside the video, in seconds (see the top).
  const HAND_SHOW = 15;
  // The video `to` from its start, in full screen where the screen is, else
  // scrolled to on the page; the one playing pauses as it starts (below).
  function playFrom(to) {
    const wrap = to.closest(".vw");
    if (screenEl() === stage || inWin()) onStage(wrap);
    else wrap.scrollIntoView({block: "center", behavior: "smooth"});
    to.currentTime = 0;
    // A browser may refuse to play with sound when no click started it; a
    // pause the person made before it began is no refusal.
    to.play().catch((e) => { if (e.name === "NotAllowedError") say(wrap, PRESS_PLAY, 6000); });
  }
  // In a row: the next video, only from the same section where the page
  // marks sections (data-row) — a version ended is not the next one begun.
  function playNext(video) {
    const next = nextOf(video), row = spot(video).closest("[data-row]");
    if (next && (!row || row.contains(next))) playFrom(next);
  }
  // ⏮ ⏭ and Shift+P, Shift+N.
  function goVideo(wrap, d) {
    const video = wrap.querySelector("video"), to = d > 0 ? nextOf(video) : prevOf(video);
    if (to) playFrom(to);
    else say(wrap, d > 0 ? "This is the last video" : "This is the first video");
  }
  // Only the last video started plays: the rest pause, on the page and on
  // the screen alike.
  document.addEventListener("play", (e) => {
    const v = e.target;
    if (!(v instanceof HTMLVideoElement) || !v.dataset.v) return;
    for (const other of document.querySelectorAll("video[data-v]")) if (other !== v && !other.paused) other.pause();
  }, true);

  const flip = (video) => (video.paused ? video.play().catch(() => {}) : video.pause());
  function say(wrap, text, ms = 1200) {
    const toast = wrap.querySelector(".toast");
    toast.textContent = text;
    toast.classList.add("on");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => toast.classList.remove("on"), ms);
  }

  // The steps on a strip under the video. The browser draws no chapters on
  // its own time line (a <track kind=chapters> loads and shows nothing in
  // Chrome), so the strip is the page's: a stretch for each step, from its
  // second to the next one's, a failed check red, the played part filled; a
  // hover says the step and shows the frame there, a click goes there.
  // data-steps='[[t, text, ok, look], …]' — ok 1, 0 or null — names them.
  function stepsOf(video) {
    if (!video.steps) {
      try { video.steps = JSON.parse(video.dataset.steps || "[]").map(([t, text, ok, look]) => ({t: +t || 0, text, ok, look})); }
      catch { video.steps = []; }
    }
    return video.steps;
  }
  // The step under way: the same rule as the steps beside the video.
  function stepAt(video, t) {
    let at = -1;
    stepsOf(video).forEach((s, i) => { if (s.t <= t + 0.2) at = i; });
    return at;
  }
  const markOf = (s) => (s.ok === 1 ? "✓ " : s.ok === 0 ? "✗ " : "");
  function stepText(video, i) {
    const all = stepsOf(video);
    return i < 0 ? {head: "Start", look: ""}
      : {head: (i + 1) + "/" + all.length + " · " + markOf(all[i]) + all[i].text, look: all[i].look};
  }
  function fill(box, {head, look}) {
    box.textContent = "";
    const h = document.createElement("div");
    h.textContent = head;
    box.append(h);
    if (look) {
      const l = document.createElement("div");
      l.className = "lk";
      l.textContent = "👀 " + look;
      box.append(l);
    }
  }
  // Over the picture, top left: full screen hides the steps beside the video.
  function showStep(video, cap, ms) {
    if (!stepsOf(video).length) return;
    const txt = stepText(video, stepAt(video, video.currentTime));
    // The same step again keeps its text, and a selection in it.
    if (cap.dataset.head !== txt.head) { fill(cap, txt); cap.dataset.head = txt.head; }
    cap.classList.add("on");
    clearTimeout(cap.timer);
    if (!cap.matches(":hover")) cap.timer = setTimeout(() => cap.classList.remove("on"), ms);
  }
  // [ and ]: the next step's start, or this one's — the one before when
  // this one has only just begun, as a player's "previous" does.
  function jump(wrap, d) {
    const video = wrap.querySelector("video"), all = stepsOf(video);
    if (!all.length) return;
    const now = video.currentTime, i = stepAt(video, now);
    let to;
    if (d > 0) { if (i + 1 >= all.length) return; to = all[i + 1].t; }
    else { const start = i >= 0 ? all[i].t : 0; to = now - start > 1.5 ? start : i > 0 ? all[i - 1].t : 0; }
    video.currentTime = to;
    // Said for the second the seek lands on, not the one it left.
    video.addEventListener("seeked", () => showStep(video, wrap.querySelector(".cap"), 2500), {once: true});
  }
  // The recordings are 25 frames a second.
  function frameStep(video, d) {
    video.pause();
    video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + d / 25));
  }
  const RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2], RATE_KEY = "sdemo-rate";
  function speed(wrap, d) {
    const now = wrap.querySelector("video").playbackRate;
    let i = RATES.findIndex((r) => r >= now - 0.01);
    if (i < 0) i = RATES.length - 1;
    const r = RATES[Math.max(0, Math.min(RATES.length - 1, (RATES[i] > now + 0.01 && d > 0 ? i - 1 : i) + d))];
    // Every video on the page, and the next visit: one way of watching.
    for (const v of document.querySelectorAll("video[data-v]")) v.defaultPlaybackRate = v.playbackRate = r;
    try { localStorage.setItem(RATE_KEY, String(r)); } catch {}
    say(wrap, "Speed " + r + "×");
  }

  function steps(video, wrap, cap) {
    const strip = document.createElement("div");
    strip.className = "vs";
    const track = document.createElement("div");
    track.className = "tr";
    const tip = document.createElement("div");
    tip.className = "tip";
    const pic = document.createElement("canvas");
    const words = document.createElement("div");
    tip.append(pic, words);
    strip.append(track, tip);
    let segs = [], shown = null;

    // A WebM straight from the recorder (no ffmpeg to squeeze it) has no
    // duration in its header: Infinity until read to the end. What is known
    // stands in — the last step's second a little on, or as far as it was
    // played or loaded — and the strip is drawn again as that grows.
    let drawn = 0;
    const length = () => {
      const d = video.duration, all = stepsOf(video), b = video.buffered;
      if (isFinite(d) && d > 0) return d;
      return Math.max(all.length ? all[all.length - 1].t + 3 : 0, video.currentTime + 1,
        b.length ? b.end(b.length - 1) : 0);
    };
    function build() {
      const all = stepsOf(video), dur = length();
      if (!all.length || dur <= 0) return;
      drawn = dur;
      if (!strip.parentNode) wrap.insertBefore(strip, video.nextSibling);
      track.textContent = "";
      const bounds = (all[0].t > 0.5 ? [{t: 0, i: -1}] : []).concat(all.map((s, i) => ({t: s.t, i})));
      segs = bounds.map((b, k) => {
        const end = k + 1 < bounds.length ? bounds[k + 1].t : dur;
        const el = document.createElement("i");
        if (b.i >= 0 && all[b.i].ok === 0) el.className = "bad";
        el.style.left = (b.t / dur * 100) + "%";
        el.style.width = (Math.max(0, end - b.t) / dur * 100) + "%";
        el.append(document.createElement("b"));
        track.append(el);
        return {from: b.t, to: end, i: b.i, el};
      });
      paint();
    }
    function paint() {
      const t = video.currentTime;
      if (!isFinite(video.duration) && length() > drawn + 0.5) return build();
      for (const s of segs) {
        s.el.firstChild.style.width = (t >= s.to ? 100 : t <= s.from ? 0 : (t - s.from) / (s.to - s.from) * 100) + "%";
        s.el.classList.toggle("now", t >= s.from && t < s.to);
      }
      const at = stepAt(video, t);
      if (at !== shown) {
        // A new step on the screen says itself there.
        if (shown !== null && full() === wrap && !video.paused) showStep(video, cap, 4000);
        shown = at;
      }
    }
    const timeAt = (x) => {
      const r = track.getBoundingClientRect();
      // By the length the strip was drawn with, which a stand-in may have outgrown.
      return Math.max(0, Math.min(1, (x - r.left) / r.width)) * drawn;
    };

    // The frame under the pointer, from a second copy of the video that
    // seeks there: nothing to cut out at recording, and the old demos have it
    // too. One seek at a time; the latest wish is the next one.
    let ghost = null, want = null, busy = false;
    function seekGhost() {
      if (want === null || busy || ghost.readyState < 1) return;
      busy = true;
      ghost.currentTime = want;
      want = null;
    }
    function preview(t) {
      if (!ghost) {
        ghost = document.createElement("video");
        ghost.muted = true;
        // Metadata only: each seek fetches the ranges it needs, not the file again.
        ghost.preload = "metadata";
        ghost.src = video.currentSrc || video.src || (video.querySelector("source") || {}).src || "";
        ghost.addEventListener("loadedmetadata", seekGhost);
        ghost.addEventListener("seeked", () => {
          busy = false;
          const k = Math.min(240 / ghost.videoWidth, 150 / ghost.videoHeight);
          pic.width = Math.round(ghost.videoWidth * k);
          pic.height = Math.round(ghost.videoHeight * k);
          pic.getContext("2d").drawImage(ghost, 0, 0, pic.width, pic.height);
          tip.classList.add("pic");
          seekGhost();
        });
      }
      want = t;
      seekGhost();
    }
    function hover(e) {
      // Over the tip itself it stays put: its text is there to be selected.
      if (!segs.length || tip.contains(e.target)) return;
      const t = timeAt(e.clientX), seg = segs.find((s) => t >= s.from && t < s.to) || segs[segs.length - 1];
      const txt = stepText(video, seg.i);
      fill(words, {head: clock(t) + " · " + txt.head, look: txt.look});
      clearTimeout(tip.timer);
      tip.classList.add("on");
      const r = track.getBoundingClientRect(), w = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(r.width - w, e.clientX - r.left - w / 2)) + "px";
      preview(t);
    }
    let lifted = null;  // the finger or pen that just lifted, whose leave follows
    // Only that pointer moving again (a pen hovering on) ends its lift.
    const again = (e) => { if (lifted === e.pointerId) lifted = null; hover(e); };
    strip.addEventListener("pointermove", again);
    strip.addEventListener("pointerdown", again);
    // A finger, or a pen that cannot hover, leaves as it lifts: the tip
    // stays four seconds after that leave, to be read. A pen still hovering
    // has not left and keeps it, as a mouse does. A leave with no lift before
    // it (a mouse, a hovering pen moving off) hides it; so does a swipe the
    // page takes for a scroll, which cancels the touch.
    strip.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "mouse" && lifted === e.pointerId) {
        lifted = null;
        clearTimeout(tip.timer);
        tip.timer = setTimeout(() => tip.classList.remove("on"), 4000);
        return;
      }
      tip.classList.remove("on");
    });
    strip.addEventListener("pointercancel", () => tip.classList.remove("on"));
    strip.addEventListener("pointerup", (e) => {
      if (e.pointerType !== "mouse") lifted = e.pointerId;
    });
    // A click goes to the start of the step under it: the strip is for
    // finding a step; the time line above is for a second.
    strip.addEventListener("click", (e) => {
      if (tip.contains(e.target) || !segs.length) return;
      const t = timeAt(e.clientX);
      video.currentTime = (segs.find((s) => t >= s.from && t < s.to) || segs[segs.length - 1]).from;
      used = wrap;
    });

    video.addEventListener("loadedmetadata", build);
    video.addEventListener("durationchange", build);
    video.addEventListener("timeupdate", paint);
    video.addEventListener("seeked", paint);
    if (video.readyState >= 1) build();
  }

  // The keys, as a video player takes them, by the key's place on the
  // keyboard (e.code), so another layout's letters work the same. They go
  // to the video on the screen, else the one under the pointer or holding
  // the focus, else the last one played while half in view — that one only
  // while focus is on no link, summary or button of the page. A field keeps
  // its keys always; with no video, the page keeps them (space scrolls). A
  // focused video takes space, Enter and the arrows itself: twice would
  // undo them.
  const KEYS = "Keys: space or K play/pause · ← → or J L 5 s · [ ] step · , . frame · < > speed · M sound · F full screen · W in the window" +
    " · Shift+P Shift+N the video before or after";
  let hovered = null, used = null;
  // [wrapper, chosen]: chosen when the person points at it — on the screen,
  // under the pointer, holding the focus — not when it is only remembered.
  function active() {
    const f = full();
    if (f && f.classList && f.classList.contains("vw")) return [f, true];
    // A video the browser put on the screen alone: its wrapper, whatever the
    // pointer last rested on.
    const alone = f && f.closest && f.closest(".vw");
    if (alone) return [alone, true];
    if (hovered) return [hovered, true];
    const a = document.activeElement && document.activeElement.closest && document.activeElement.closest(".vw");
    if (a) return [a, true];
    if (used) {
      const r = used.getBoundingClientRect();
      if (Math.min(r.bottom, innerHeight) - Math.max(r.top, 0) > r.height / 2) return [used, false];
    }
    return [null, false];
  }
  const NATIVE = ["Space", "Enter", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    // A field keeps its keys always; anything else of the page's own (a link,
    // a summary) keeps them unless a video is chosen — on the screen or
    // under the pointer — rather than only the last one played.
    const t = e.target;
    if (t.closest && t.closest("input,textarea,select,[contenteditable]:not([contenteditable=false])")) return;
    // Esc leaves the window as the browser's leaves the whole screen.
    if (e.code === "Escape" && inWin()) {
      winMark(false);
      offStage();
      e.preventDefault();
      return;
    }
    const [wrap, chosen] = active();
    if (!wrap) return;
    if (!chosen && t !== document.body && t !== document.documentElement) return;
    const video = wrap.querySelector("video");
    if (t === video && NATIVE.includes(e.code)) return;
    const c = e.code, s = e.shiftKey;
    // Space on a button just pressed (⛶ itself) would press it again.
    if (s && c === "KeyP") { if (many) goVideo(wrap, -1); else return; }
    else if (s && c === "KeyN") { if (many) goVideo(wrap, 1); else return; }
    else if (c === "Space" || c === "KeyK") flip(video);
    else if (c === "ArrowLeft" || c === "KeyJ") video.currentTime = Math.max(0, video.currentTime - 5);
    else if (c === "ArrowRight" || c === "KeyL") video.currentTime = Math.min(video.duration || 0, video.currentTime + 5);
    else if (c === "BracketLeft") jump(wrap, -1);
    else if (c === "BracketRight") jump(wrap, 1);
    else if (c === "Comma") s ? speed(wrap, -1) : frameStep(video, -1);
    else if (c === "Period") s ? speed(wrap, 1) : frameStep(video, 1);
    else if (c === "KeyM") video.muted = !video.muted;
    else if (c === "KeyF") toggle(wrap);
    else if (c === "KeyW") winToggle(wrap);
    else return;
    used = wrap;
    e.preventDefault();
    e.stopPropagation();
  });

  for (const video of document.querySelectorAll("video[data-v]")) {
    const wrap = document.createElement("div");
    wrap.className = "vw" + (video.classList.contains("phone") ? " phone" : "");
    video.parentNode.insertBefore(wrap, video);
    wrap.appendChild(video);
    // The browser's own full screen would leave the buttons behind.
    video.setAttribute("controlsList", "nofullscreen");
    const bar = document.createElement("div");
    bar.className = "vb";
    const link = document.createElement("button");
    link.type = "button";
    link.title = "Copy a link to this moment of the video";
    link.textContent = "🔗 0:00";
    const big = document.createElement("button");
    big.type = "button";
    big.title = "Full screen, with the copy button";
    big.textContent = "⛶";
    const win = document.createElement("button");
    win.type = "button";
    win.className = "win";
    win.textContent = "▣";
    const pin = document.createElement("button");
    pin.type = "button";
    pin.className = "pin";
    pin.title = "Point at a place in the frame: it goes into the link";
    pin.textContent = "📍";
    const nx = document.createElement("button");
    nx.type = "button";
    nx.className = "nx";
    nx.textContent = "🔁";
    const nxView = () => {
      nx.classList.toggle("on", inRow);
      nx.title = "Play in a row: " + (inRow ? "on — the next video starts when this one ends" : "off");
    };
    nxView();
    rowViews.push(nxView);
    nx.addEventListener("click", () => setRow(!inRow));
    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "pv";
    prev.textContent = "⏮";
    prev.title = "The video before (Shift+P)";
    const next = document.createElement("button");
    next.type = "button";
    next.className = "nv";
    next.textContent = "⏭";
    next.title = "The next video (Shift+N)";
    prev.addEventListener("click", () => goVideo(wrap, -1));
    next.addEventListener("click", () => goVideo(wrap, 1));
    // Greyed where there is none: looked again whenever the bar may be seen,
    // since a version unfolded or the stage's swap changes the neighbours.
    const ends = () => { prev.disabled = !prevOf(video); next.disabled = !nextOf(video); };
    if (many) {
      wrap.addEventListener("pointerenter", ends);
      wrap.addEventListener("focusin", ends);
      syncs.push(ends);
      ends();
    }
    bar.append(...(many ? [prev, next, pin, link, nx, win, big] : [pin, link, win, big]));
    const pick = document.createElement("div");
    pick.className = "pick";
    const dot = document.createElement("div");
    dot.className = "dot";
    const toast = document.createElement("div");
    toast.className = "toast";
    wrap.append(pick, dot, bar, toast);
    pin.addEventListener("click", () => {
      if (wrap.classList.toggle("picking")) video.pause();
    });
    pick.addEventListener("click", (e) => {
      const f = frame(video);
      const x = (e.clientX - f.left) / f.w * 100, y = (e.clientY - f.top) / f.h * 100;
      wrap.classList.remove("picking");
      if (x < 0 || x > 100 || y < 0 || y > 100) return;
      video.pending = null;  // the person's own point wins over a link's still on its way
      video.point = [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
      place(video);
      copy(video, link);
    });
    link.addEventListener("click", () => copy(video, link));
    big.addEventListener("click", () => toggle(wrap));
    win.addEventListener("click", () => winToggle(wrap));
    video.addEventListener("dblclick", (e) => {
      e.preventDefault();
      // The double click's first click flipped playback: taken back, or
      // never made if it is still waiting, so the video goes to full screen,
      // or leaves it, playing or paused as it was. Taken back after the move
      // to the stage, or once back on the page, since either move would cut
      // a play() under way short.
      const back = !video.flipping && Date.now() - (video.flipped || 0) < 1000;
      clearTimeout(video.flipping);
      video.flipping = 0;
      video.flipped = 0;
      const left = toggle(wrap);
      if (!back) return;
      // The exit's promise may come before its fullscreenchange: put back here.
      // Back to the page — or to the window the full screen was asked for
      // from, where the wrapper stays on the stage (fullscreenchange).
      const home = () => { if (!fromWin && !stage.classList.contains("inwin")) offStage(); flip(video); };
      if (left && left.then) left.then(home, home);
      else flip(video);
    });
    // A click on the picture pauses and plays, on the page as on the screen:
    // Chrome does it only for a video that is itself in full screen, which
    // the wrapper is not; Firefox plays on a click anywhere, so the click
    // acts only when the browser did not. Clicks on Chrome's control bar do
    // not reach the page; the strip at the bottom is left alone for a
    // browser whose do. On the page a tap is left to a phone's browser,
    // which shows its controls on one. A double click's second click is the
    // full screen's; dblclick takes the first one's flip back.
    video.addEventListener("click", (e) => {
      // A click of its own forgets an earlier one's flip; a double click's
      // second click leaves it for dblclick.
      if (e.detail <= 1) video.flipped = 0;
      if (e.detail > 1 || video.getBoundingClientRect().bottom - e.clientY < 48) return;
      if (full() !== wrap && e.pointerType === "touch") return;
      const was = video.paused;
      video.flipping = setTimeout(() => {
        video.flipping = 0;
        if (video.paused !== was) return;
        flip(video);
        video.flipped = Date.now();
      }, 0);
    });
    const sync = () => {
      const on = full() === wrap, inw = on && inWin(), whole = on && !inw;
      big.textContent = whole ? "✕" : "⛶";
      big.title = whole ? "Leave full screen (Esc)" : "Full screen, with the copy button\n\n" + KEYS;
      win.textContent = inw ? "✕" : "▣";
      win.title = inw ? "Back to the page (Esc or W)"
        : "In the window: the video fills the browser's window, its address bar and tools still there (W)";
      if (!on) cap.classList.remove("on");
    };
    const cap = document.createElement("div");
    cap.className = "cap";
    wrap.append(cap);
    // Selectable: it stays while the pointer is on it.
    cap.addEventListener("pointerenter", () => clearTimeout(cap.timer));
    cap.addEventListener("pointerleave", () => { cap.timer = setTimeout(() => cap.classList.remove("on"), 1500); });
    // In full screen a click on it is one on the picture under it — unless
    // it selects words: waited out, so a double click on a word only selects.
    cap.addEventListener("click", (e) => {
      clearTimeout(cap.flip);
      if (full() !== wrap || e.detail > 1) return;
      cap.flip = setTimeout(() => { if (!String(getSelection())) flip(video); }, 300);
    });
    sync();
    syncs.push(sync);
    steps(video, wrap, cap);
    wrap.addEventListener("pointerenter", () => { hovered = wrap; });
    wrap.addEventListener("pointerleave", () => { if (hovered === wrap) hovered = null; });
    for (const ev of ["play", "click", "seeked"]) video.addEventListener(ev, () => { used = wrap; });
    // Shown again with the browser's own controls, which a move brings back.
    wrap.addEventListener("pointermove", () => { if (full() === wrap) showStep(video, cap, 2500); });
    try { const r = +localStorage.getItem(RATE_KEY); if (RATES.includes(r)) video.defaultPlaybackRate = video.playbackRate = r; } catch {}
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("webkitfullscreenchange", sync);
    video.addEventListener("timeupdate", () => {
      if (!link.textContent.startsWith("🔗")) return;
      link.textContent = "🔗 " + clock(video.currentTime);
      if (!video.paused) mark(video);
    });
    video.addEventListener("play", () => {
      if (toast.textContent === PRESS_PLAY) toast.classList.remove("on");
      wrap.classList.remove("picking");
      video.pending = null;
      if (video.point) { video.point = null; place(video); }
    });
    // A seek on pause moves to another frame just as playing does. A link's
    // point (open) waits in `pending` for the seek that reaches its second;
    // any other seek's end drops it.
    video.addEventListener("seeking", () => {
      if (video.point) { video.point = null; place(video); }
    });
    video.addEventListener("seeked", () => {
      const wait = video.pending;
      video.pending = null;
      if (wait && Math.abs(video.currentTime - wait.at) <= 0.5) { video.point = wait.p; place(video); }
    });
    for (const ev of ["pause", "seeked", "play"]) video.addEventListener(ev, () => mark(video, true));
    video.addEventListener("loadedmetadata", () => place(video));
    // Only a video played to its end goes on: one moved to its end on pause
    // (a link to its last frame, the keys, the strip) stays where it was put.
    video.addEventListener("seeking", () => { if (video.paused) video.sought = true; });
    video.addEventListener("play", () => { video.sought = false; });
    // The by-hand case beside the picture (see the top).
    let hand = null;
    try { hand = video.dataset.hand ? JSON.parse(video.dataset.hand) : null; } catch {}
    const hp = document.createElement("div");
    hp.className = "hp";
    if (hand) {
      const add = (tag, text, cls) => {
        const el = document.createElement(tag);
        el.textContent = text;
        if (cls) el.className = cls;
        return el;
      };
      hp.append(add("h3", "✋ Try it yourself"));
      if (hand.why) hp.append(add("p", hand.why, "why"));
      for (const f of hand.files || []) {
        const a = add("a", "📎 " + (f.label || f.name) + (f.label ? " (" + f.name + ")" : ""));
        a.href = f.href;
        a.download = f.name;
        hp.append(a);
      }
      if ((hand.steps || []).length) {
        const ol = document.createElement("ol");
        for (const x of hand.steps) {
          const li = add("li", x.do);
          if (x.expect) li.append(add("div", "✅ Expect: " + x.expect, "ex"));
          ol.append(li);
        }
        hp.append(ol);
      }
      for (const l of hand.links || []) {
        const a = add("a", "🔗 " + l.label + " →");
        a.href = l.href;
        a.target = "_blank";
        a.rel = "noopener";
        hp.append(a);
      }
      wrap.append(hp);
      let crossed = false, timer = 0;
      const handView = () => {
        if (full() !== wrap || video.currentTime < hand.at - 0.1) {
          crossed = false;
          clearTimeout(timer);
          wrap.classList.remove("handon");
          return;
        }
        if (crossed) return;
        crossed = true;
        wrap.classList.add("handon");
        timer = setTimeout(() => wrap.classList.remove("handon"), HAND_SHOW * 1000);
      };
      for (const ev of ["timeupdate", "seeked"]) video.addEventListener(ev, handView);
      syncs.push(handView);
      document.addEventListener("fullscreenchange", handView);
      document.addEventListener("webkitfullscreenchange", handView);
    }
    video.addEventListener("ended", () => { if (inRow && !video.sought) playNext(video); });
    new ResizeObserver(() => place(video)).observe(video);
  }

  // A browser without controlsList (Firefox, Safari) still has its own full
  // screen button: once the video alone is on the screen, swap in its
  // wrapper. Should the browser refuse, the video stays on the screen alone
  // and the address still holds the place.
  document.addEventListener("fullscreenchange", () => {
    const el = document.fullscreenElement;
    if (!el || el.tagName !== "VIDEO" || !el.parentNode.classList.contains("vw")) return;
    // The stage first, the wrapper after: moving the video out of the page
    // while it is the one on the screen would end the full screen.
    const wrap = el.parentNode;
    stage.requestFullscreen().then(() => onStage(wrap), () => {});
  });

  // The checkbox, in the page's heading, where there is more than one video.
  const heading = document.querySelector("h1");
  if (heading && many) {
    const label = document.createElement("label");
    label.className = "inrow";
    label.title = "When a video ends, the next one starts — in full screen too";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.addEventListener("change", () => setRow(box.checked));
    label.append(box, "Play in a row");
    heading.appendChild(label);
    rowViews.push(() => { box.checked = inRow; });
    box.checked = inRow;
  }

  function open() {
    const {v, t, p} = parse();
    if (!v) return;
    const video = [...document.querySelectorAll("video[data-v]")].find((x) => x.dataset.v === v);
    if (!video) return;
    // A link opened before is over: its late seek must not write it back.
    for (const other of document.querySelectorAll("video[data-v]")) other.pending = null;
    for (let d = video.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
    // A video not loaded yet needs telling to load: the attribute changed
    // alone does not make every browser start.
    if (video.readyState === 0) { video.preload = "metadata"; video.load(); }
    // Scrolled once the video knows its size: before, the page above it may
    // still grow, and the browser's own jump to the hash comes after ours.
    // The point goes on once the seek is done: the seek itself clears one.
    // Paused, so the frame the point is about stays on the screen.
    const seek = () => {
      const at = Math.min(t, video.duration || t);
      video.pause();
      video.pending = p && {p, at};
      video.currentTime = at;
      requestAnimationFrame(() => video.closest(".vw").scrollIntoView({block: "center"}));
    };
    if (video.readyState >= 1) seek(); else video.addEventListener("loadedmetadata", seek, {once: true});
  }
  open();
  // A link pasted into the same tab's address bar changes only the hash.
  window.addEventListener("hashchange", open);
})();
