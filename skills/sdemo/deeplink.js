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
// alone, and the person tells Claude about a place mostly from there.
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
.vw:fullscreen{background:#000;display:flex;align-items:center;justify-content:center;width:100%;max-width:none;margin:0}
.vw:fullscreen video{width:100%;height:100%;max-width:none;max-height:none;object-fit:contain;border-radius:0}
.vw:-webkit-full-screen{background:#000;width:100%;height:100%}
.vw:-webkit-full-screen video{width:100%;height:100%;max-height:none;object-fit:contain}`;
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

  const full = () => document.fullscreenElement || document.webkitFullscreenElement;
  function toggle(wrap) {
    if (full()) return (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    const go = wrap.requestFullscreen || wrap.webkitRequestFullscreen;
    if (go) return go.call(wrap);
    // An iPhone puts only a video on the whole screen.
    const video = wrap.querySelector("video");
    if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
  }

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
    const pin = document.createElement("button");
    pin.type = "button";
    pin.className = "pin";
    pin.title = "Point at a place in the frame: it goes into the link";
    pin.textContent = "📍";
    bar.append(pin, link, big);
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
    video.addEventListener("dblclick", (e) => { e.preventDefault(); toggle(wrap); });
    video.addEventListener("timeupdate", () => {
      if (!link.textContent.startsWith("🔗")) return;
      link.textContent = "🔗 " + clock(video.currentTime);
      if (!video.paused) mark(video);
    });
    video.addEventListener("play", () => {
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
    new ResizeObserver(() => place(video)).observe(video);
  }

  // A browser without controlsList (Firefox, Safari) still has its own full
  // screen button: once the video alone is on the screen, swap in its
  // wrapper. Should the browser refuse, the video stays on the screen alone
  // and the address still holds the place.
  document.addEventListener("fullscreenchange", () => {
    const el = document.fullscreenElement;
    if (!el || el.tagName !== "VIDEO" || !el.parentNode.classList.contains("vw")) return;
    el.parentNode.requestFullscreen().catch(() => {});
  });

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
