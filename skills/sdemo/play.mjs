#!/usr/bin/env node
//
// /sdemo's player: runs a demo script against a feature with Playwright,
// showing on the page itself what each step does and why, and either
// records it (one video per scenario, and a page that plays them with the
// steps beside them) or plays it live in chrome-debug with controls to pause
// and take over.
//
//   node play.mjs <demo.mjs> --out DIR --base URL [--live] [--cdp URL]
//                 [--keep-from DIR --only 2,7]
//
// demo.py play is what calls it: it knows the feature, its address and
// where the results go (DEMO_DIR). The script is a module the skill writes:
//
//   export default {
//     title: "…", viewport: "desktop" | "phone",   (a scenario may set its own)
//     kind: "main" | "delta", change: "…",   (a delta: only what changed)
//     scenarios: [{
//       title: "…", as: "<email>", path: "/start",
//       shows: "…", look: ["…"], why: "…",
//       async steps(d) { await d.click(d.page.getByRole("button", {name: "Save"}), "…"); },
//     }],
//   };
//
// A step's text is a line, or {say, look, why}: what happens, where to look,
// and what it proves — shown under the line on the page, in the video, on
// the demo's page beside it, and in its captions (WebVTT).
//
// Every scenario starts signed in as its user, through the proxy's
// /__sclaude/login on BASE, in a browser context of its own (cookies of its
// own). Its steps get `d`, whose helpers (below) put a caption, a ring and a
// cursor on the page before they act, and note each step's time and address
// — the page's "take over from here" links are those addresses.
//
// Live, the page carries ⏸ ▶ ⏭ ⏹: the helpers wait at the next step while
// paused, so the page is the person's meanwhile; ⏹ ends the script and
// leaves the windows to them. The state is kept here, not in the page,
// which a navigation would reset.
//
// --keep-from names an earlier recording of the same script (demo.py play
// --only): the scenarios --only lists are played again, every other one is
// taken from it as it was — its videos and captions copied, its record kept
// — when it played there without a fault and is the same scenario still
// (`sig`: its title, user, path, cards and steps' source). One that changed
// since, or did not play there, is played again too. A retry then costs the
// scenarios that failed, not the whole demo.
import { createRequire } from "node:module";
import { createHash } from "node:crypto";
import { execFile, execFileSync } from "node:child_process";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const args = process.argv.slice(2);
const opt = (name, dflt = "") => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : dflt;
};
const scriptPath = args.find((a, i) => !a.startsWith("--") && !args[i - 1]?.match(/^--(out|base|cdp|feature|keep-from|only)$/));
const OUT = opt("--out");
const BASE = opt("--base").replace(/\/$/, "");
const LIVE = args.includes("--live");
const FEATURE = opt("--feature");
const CDP = opt("--cdp", "http://127.0.0.1:" + (process.env.CHROME_DEBUG_PORT || 9222));
const KEEP_FROM = opt("--keep-from");
const ONLY = new Set(opt("--only").split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0));
if (!scriptPath || !OUT || !BASE) {
  console.error("usage: play.mjs <demo.mjs> --out DIR --base URL [--live]");
  process.exit(2);
}

// Playwright from the global install: the one whose browsers are in
// ~/.cache/ms-playwright, which chrome-debug runs too.
function playwright() {
  const roots = [];
  try {
    roots.push(execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim());
  } catch {}
  for (const root of roots) {
    try {
      return createRequire(path.join(root, "noop.js"))("playwright");
    } catch {}
  }
  console.error("error: no playwright — npm install -g playwright && playwright install chromium");
  process.exit(1);
}

const VIEWPORTS = {
  desktop: { viewport: { width: 1280, height: 800 } },
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};
const TIMEOUT = 10000;

// --- the overlay, injected into every document of a demo ---------------------
//
// In a shadow root, so the product's styles do not reach it, and pointer-
// events off except on the controls, so the page under it stays usable.
const OVERLAY = String.raw`(() => {
  if (window.__sdemo) return;
  const api = { pending: [] };
  window.__sdemo = api;
  function build() {
    if (api.root || !document.documentElement) return;
    const host = document.createElement("sdemo-overlay");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;pointer-events:none";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = '<style>' +
      ':host{all:initial}' +
      '*{box-sizing:border-box;font-family:system-ui,-apple-system,sans-serif}' +
      '.cap{position:fixed;left:50%;top:14px;transform:translateX(-50%);max-width:min(720px,92vw);' +
      'background:rgba(17,24,39,.92);color:#f9fafb;padding:10px 16px;border-radius:12px;font-size:16px;' +
      'line-height:1.4;font-size:17px;box-shadow:0 8px 30px rgba(0,0,0,.3);transition:opacity .2s}' +
      '.cap:empty{opacity:0}.cap .sm{font-size:14px;color:#d1d5db;margin-top:3px}.cap b{color:#93c5fd;font-weight:600}.cap .ok{color:#4ade80}.cap .bad{color:#f87171}' +
      '.ring{position:fixed;border:3px solid #f59e0b;border-radius:8px;box-shadow:0 0 0 4000px rgba(0,0,0,.18);' +
      'transition:all .35s ease;opacity:0}' +
      '.cur{position:fixed;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;' +
      'background:rgba(239,68,68,.85);border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4);' +
      'transition:left .5s ease,top .5s ease,transform .15s;opacity:0}' +
      '.cur.down{transform:scale(.7)}' +
      '.card{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;' +
      'background:rgba(15,23,42,.72);opacity:0;transition:opacity .3s}' +
      '.card.on{opacity:1}' +
      '.card>div{background:#fff;color:#111827;max-width:min(640px,90vw);padding:24px 28px;border-radius:16px;' +
      'box-shadow:0 20px 60px rgba(0,0,0,.4);font-size:16px;line-height:1.5}' +
      '.card h2{margin:0 0 4px;font-size:22px}.card .who{color:#6b7280;font-size:14px;margin-bottom:12px}' +
      '.card h3{margin:12px 0 2px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:#6b7280}' +
      '.card ul{margin:0;padding-left:20px}' +
      '.ctl{position:fixed;bottom:14px;right:14px;display:flex;gap:6px;pointer-events:auto}' +
      '.ctl button{border:0;border-radius:10px;padding:8px 12px;font-size:15px;cursor:pointer;' +
      'background:rgba(17,24,39,.9);color:#fff;box-shadow:0 4px 14px rgba(0,0,0,.3)}' +
      '.ctl .st{background:rgba(255,255,255,.95);color:#111827;font-size:13px;padding:8px 10px;border-radius:10px;' +
      'box-shadow:0 4px 14px rgba(0,0,0,.2)}' +
      '</style><div class=ring></div><div class=cur></div><div class=card></div><div class=cap></div>' +
      '<div class=ctl hidden></div>';
    document.documentElement.appendChild(host);
    api.root = root;
    api.cap = root.querySelector(".cap");
    api.ringEl = root.querySelector(".ring");
    api.curEl = root.querySelector(".cur");
    api.cardEl = root.querySelector(".card");
    api.ctl = root.querySelector(".ctl");
    if (window.__sdemoCtl) controls();
    for (const f of api.pending.splice(0)) f();
  }
  function later(f) { api.root ? f() : api.pending.push(f); }
  api.caption = (h) => later(() => { api.cap.innerHTML = h || ""; });
  api.ring = (r) => later(() => {
    const e = api.ringEl;
    if (!r) { e.style.opacity = 0; return; }
    Object.assign(e.style, { left: r.x - 6 + "px", top: r.y - 6 + "px", width: r.width + 12 + "px",
      height: r.height + 12 + "px", opacity: 1 });
  });
  api.cursor = (x, y, down) => later(() => {
    const e = api.curEl;
    if (x == null) { e.style.opacity = 0; return; }
    Object.assign(e.style, { left: x + "px", top: y + "px", opacity: 1 });
    e.classList.toggle("down", !!down);
  });
  api.card = (h) => later(() => {
    api.cardEl.innerHTML = h ? "<div>" + h + "</div>" : "";
    api.cardEl.classList.toggle("on", !!h);
  });
  function controls() {
    const c = api.ctl;
    c.hidden = false;
    const draw = (state) => {
      // Paused or stopped, the page is the person's at once: whatever the
      // demo drew goes the moment the button is pressed, not at the
      // script's next step.
      if (state === "paused" || state === "stopped") {
        api.card(null); api.caption(""); api.ring(null); api.cursor(null);
      }
      const label = { playing: "▶ playing", paused: "⏸ paused — the page is yours",
        stopped: "⏹ stopped — the page is yours" }[state] || state;
      c.innerHTML = '<span class=st>' + label + '</span>' + (state === "stopped" ? "" :
        (state === "paused" ? '<button data-c=playing title="Resume">▶</button>'
          : '<button data-c=paused title="Pause and take over">⏸</button>') +
        '<button data-c=skip title="Next scenario">⏭</button>' +
        '<button data-c=stopped title="Stop the demo, keep the page">⏹</button>');
    };
    c.onclick = async (ev) => {
      const b = ev.target.closest("button");
      if (b) draw(await window.__sdemoCtl(b.dataset.c));
    };
    api.draw = draw;
    window.__sdemoCtl("").then(draw);
  }
  if (document.documentElement) build();
  document.addEventListener("DOMContentLoaded", build);
})();`;

// --- running ------------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const readFor = (text) => Math.min(6000, Math.max(1400, String(text || "").length * 55));

let state = "playing"; // live only: playing | paused | skip | stopped
const shown = () => (state === "skip" ? "playing" : state);
const contexts = new Map(); // live: a context per user, its windows
class Skip extends Error {}
class Stop extends Error {}

// Live, the person's controls are answered here, before each step.
//
// A tab the person closes means one thing, whenever they close it — signing
// in, under the card, a step or a check, paused or not: "done with this
// scenario". It is recorded as skipped by them, not failed, and the step it
// cut off leaves the record (no ✗ for a check it cut short, no step that never
// ran). It changes nothing else: a pause pressed in another window stays a
// pause, so the demo does not start opening windows while the person works in
// one; with every window closed while paused nobody is left to press ▶, and
// the demo stops (main's wait between scenarios). Before this rule each moment
// read a closed tab its own way — a failed sign-in, a failed step, a pause
// lifted or held for ever — and review rounds kept finding the next one.
async function gate(page) {
  if (!LIVE) return;
  // A stop outranks the closed tab that may follow it.
  if (state === "stopped") throw new Stop();
  if (page?.isClosed()) throw new Skip();
  if (state === "paused" && page) await wipe(page);
  while (state === "paused") {
    if (page?.isClosed()) throw new Skip();
    await sleep(250);
  }
  if (state === "skip") {
    state = "playing";
    throw new Skip();
  }
  if (state === "stopped") throw new Stop();
}

// What a step says: a line, or {say, look, why} — what happens, where to
// look, and what it proves.
const words = (x) => (x && typeof x === "object"
  ? { say: String(x.say || ""), look: String(x.look || ""), why: String(x.why || "") }
  : { say: String(x || ""), look: "", why: "" });
const length = (w) => w.say.length + w.look.length + w.why.length;

// Where the recording stands, one line on stdout for demo.py play to read
// (`progress: {json}`): which scenario of how many, which step. demo.py keeps
// it in the feature's state as `demo_progress`, where the status lines read
// it — sclaude's terminal (demo_progress.py) and Claude Code's (statusline.py).
function progress(fields) {
  if (!LIVE) console.log("progress: " + JSON.stringify(fields));
}

function helpers(page, record, started) {
  const note = (kind, w, extra = {}) => {
    const step = { kind, text: w.say, t: (Date.now() - started) / 1000, url: page.url(), ...extra };
    if (w.look) step.look = w.look;
    if (w.why) step.why = w.why;
    record.steps.push(step);
    progress({ step: record.steps.length });
    return step;
  };
  // A step whose tab the person closed under it did not happen: it leaves
  // the record, and the scenario is their skip.
  const closed = (step) => {
    record.steps.splice(record.steps.indexOf(step), 1);
    return new Skip();
  };
  const ov = (fn, arg) => page.evaluate(fn, arg).catch(() => {});
  const caption = (w, mark = "", cls = "") =>
    ov((h) => window.__sdemo?.caption(h), !w.say && !w.look && !w.why && !mark ? "" :
      `<span class="${cls}">${esc(mark)}${esc(w.say)}</span>` +
      (w.look ? `<div class=sm>👀 ${esc(w.look)}</div>` : "") +
      (w.why ? `<div class=sm>💡 ${esc(w.why)}</div>` : ""));
  async function point(target) {
    const loc = typeof target === "string" ? page.locator(target) : target;
    await loc.first().waitFor({ state: "visible", timeout: TIMEOUT });
    await loc.first().scrollIntoViewIfNeeded({ timeout: TIMEOUT }).catch(() => {});
    const box = await loc.first().boundingBox();
    if (box) {
      await ov((b) => { window.__sdemo?.ring(b); window.__sdemo?.cursor(b.x + b.width / 2, b.y + b.height / 2); }, box);
      await sleep(550);
    }
    return { loc: loc.first(), box };
  }
  const clear = () => ov(() => window.__sdemo?.ring(null));
  async function act(kind, text, target, fn) {
    await gate(page);
    const w = words(text);
    const step = note(kind, w);
    await caption(w);
    try {
      const p = target ? await point(target) : {};
      await sleep(readFor(" ".repeat(length(w))) * (kind === "say" ? 1 : 0.6));
      await gate(page);
      if (fn) {
        if (p.box) await ov((b) => window.__sdemo?.cursor(b.x + b.width / 2, b.y + b.height / 2, true), p.box);
        await fn(p.loc);
        await sleep(150);
        if (p.box) await ov(() => window.__sdemo?.cursor(null));
        await page.waitForLoadState("domcontentloaded").catch(() => {});
        await sleep(700);
      }
      await clear();
    } catch (err) {
      if (err instanceof Stop) throw err;
      if (LIVE && page.isClosed()) throw closed(step);
      if (err instanceof Skip) throw err;
      step.error = String(err.message || err).split("\n")[0];
      await caption({ say: (w.say ? w.say + " — " : "") + "did not work: " + step.error, look: "", why: "" },
        "⚠ ", "bad");
      await sleep(2500);
      throw err;
    }
  }
  return {
    page,
    say: (text, target) => act("say", text, target),
    click: (target, text) => act("click", text, target, (l) => l.click({ timeout: TIMEOUT })),
    fill: (target, value, text) => act("fill", text, target, async (l) => {
      await l.click({ timeout: TIMEOUT });
      await l.fill("");
      await l.pressSequentially(String(value), { delay: 45 });
    }),
    select: (target, value, text) => act("select", text, target, (l) => l.selectOption(value)),
    press: (key, text) => act("press", text, null, () => page.keyboard.press(key)),
    goto: (p, text) => act("goto", text, null, () => page.goto(BASE + p)),
    wait: async (ms) => { await gate(page); await sleep(ms); },
    // A check says what must be seen, and is marked passed or failed in the
    // caption and on the page; a failed one does not stop the scenario.
    check: async (target, text) => {
      await gate(page);
      const w = words(text);
      const step = note("check", w);
      await caption(w);
      try {
        await point(target);
        step.ok = true;
        await caption(w, "✓ ", "ok");
      } catch (err) {
        if (err instanceof Stop) throw err;
        if (LIVE && page.isClosed()) throw closed(step);
        if (err instanceof Skip) throw err;
        step.ok = false;
        step.error = `not seen within ${TIMEOUT / 1000} s`;
        await caption({ ...w, say: w.say + " — not seen" }, "✗ ", "bad");
      }
      await sleep(readFor(" ".repeat(length(w))));
      await clear();
    },
  };
}

function cardHtml(s) {
  const look = Array.isArray(s.look) ? s.look : s.look ? [s.look] : [];
  return `<h2>${esc(s.title)}</h2><div class=who>as ${esc(s.as)}</div>` +
    (s.shows ? `<h3>What this shows</h3><div>${esc(s.shows)}</div>` : "") +
    (look.length ? `<h3>Look at</h3><ul>${look.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : "") +
    (s.why ? `<h3>Why this case</h3><div>${esc(s.why)}</div>` : "");
}

// The page's own script in the scenario's first moments: a page that moves
// on by itself as it loads (a redirect, a query string put right) destroys
// the document an evaluate ran in. Waited for and tried again, three times —
// before, such a page failed its whole scenario before its first step.
async function onPage(page, fn, arg) {
  for (let i = 0; ; i++) {
    try {
      return await page.evaluate(fn, arg);
    } catch (err) {
      if (i >= 3 || page.isClosed() || !/context was destroyed|navigat/i.test(String(err.message || err)))
        throw err;
      await page.waitForLoadState("load").catch(() => {});
      await sleep(300);
    }
  }
}

// Everything the demo draws, taken off the page.
const wipe = (page) => page.evaluate(() => {
  const d = window.__sdemo;
  d?.card(null); d?.caption(""); d?.ring(null); d?.cursor(null);
}).catch(() => {});

async function signIn(context, s) {
  // In a page of its own, closed after: the scenario's video starts on the
  // signed-in page, not on the redirects.
  const page = await context.newPage();
  // Recorded, this page's own video is thrown away however it ends.
  const drop = async () => {
    const video = page.video();
    await page.close().catch(() => {});
    if (video) await fs.promises.rm(await video.path(), { force: true }).catch(() => {});
  };
  try {
    const q = new URLSearchParams({ as: s.as, next: s.path || "/" });
    await page.goto(`${BASE}/__sclaude/login?${q}`, { waitUntil: "domcontentloaded", timeout: 60000 });
    for (let i = 0; i < 120 && new URL(page.url()).pathname.startsWith("/__sclaude/"); i++) {
      // The proxy's status page while the feature's server starts reloads
      // itself; a refusal stays.
      const text = await page.locator("body").innerText().catch(() => "");
      if (/not signed in/i.test(text)) throw new Error(text.split("\n").slice(0, 2).join(" "));
      // The controls are on the proxy's page too: a pause, a skip or a stop
      // pressed while the server starts is answered now, not when it has.
      await gate(page);
      await sleep(1000);
    }
    if (new URL(page.url()).pathname.startsWith("/__sclaude/"))
      throw new Error("the feature's server did not start in two minutes");
  } catch (err) {
    if (!LIVE) await drop();
    if (LIVE && page.isClosed() && !(err instanceof Stop)) throw new Skip();
    throw err;
  }
  if (LIVE) return page;
  const landed = page.url();
  await drop();
  return landed;
}

// The viewport a scenario plays at: its own, else the demo's, else desktop.
const viewportOf = (s, demo) =>
  VIEWPORTS[s.viewport] ? s.viewport : VIEWPORTS[demo.viewport] ? demo.viewport : "desktop";

async function scenario(browser, demo, s, i, contexts) {
  // A scenario may set its own viewport: the same path shown on a desktop and
  // on a phone is two scenarios, one of each.
  const viewport = viewportOf(s, demo);
  const record = { title: s.title, as: s.as, path: s.path || "/", shows: s.shows || "", why: s.why || "",
    look: Array.isArray(s.look) ? s.look : s.look ? [s.look] : [], steps: [], viewport };
  const size = VIEWPORTS[viewport];
  let context = LIVE ? contexts.get(s.as) : null;
  if (!context) {
    // Live, the window is the person's and keeps its own size: the phone's
    // emulation (scale, touch) would not even start with no viewport.
    context = await browser.newContext(LIVE ? { viewport: null }
      : { ...size, recordVideo: { dir: OUT, size: size.viewport } });
    await context.addInitScript(OVERLAY);
    if (LIVE) {
      await context.exposeBinding("__sdemoCtl", (_src, cmd) => {
        if (cmd) {
          state = cmd;
          // Every window's controls say the same: the one pressed redraws
          // from the answer, the others from here.
          for (const c of contexts.values())
            for (const p of c.pages()) p.evaluate((st) => window.__sdemo?.draw?.(st), shown()).catch(() => {});
        }
        return shown();
      });
      contexts.set(s.as, context);
    }
  }
  let page;
  // Step times count from the start of the scenario's video, which is the
  // moment its page is made.
  let started = Date.now();
  try {
    const landed = await signIn(context, s);
    if (LIVE) page = landed;
    else {
      page = await context.newPage();
      started = Date.now();
      await page.goto(landed, { waitUntil: "domcontentloaded" });
    }
  } catch (err) {
    if (err instanceof Stop) throw err;
    if (err instanceof Skip) record.skipped = true;
    else record.error = "not signed in: " + String(err.message || err).split("\n")[0];
    // Recorded, a context is the scenario's alone: closed, and the video of
    // a page that never showed the scenario dropped with it.
    if (!LIVE) {
      const video = page?.video();
      await context.close();
      if (video) await fs.promises.rm(await video.path(), { force: true }).catch(() => {});
    }
    return record;
  }
  await page.waitForLoadState("load").catch(() => {});
  try {
    // A pause pressed as the page landed holds before the card covers it.
    await gate(page);
    await onPage(page, (h) => window.__sdemo?.card(h), cardHtml(s));
    await sleep(Math.min(9000, readFor((s.shows || "") + (s.why || "") + record.look.join(" "))));
    await gate(page);
    await onPage(page, () => window.__sdemo?.card(null));
    await sleep(400);
    await s.steps(helpers(page, record, started));
    await gate(page);
    await page.evaluate(() => window.__sdemo?.caption('<b>✓ end of this scenario</b>')).catch(() => {});
    await sleep(1500);
  } catch (err) {
    // Skipped, stopped or failed, nothing of the demo is left on a page the
    // person may now take over.
    await wipe(page);
    if (err instanceof Stop) throw err;
    // Live, a tab that went away under a step was closed by the person:
    // their skip, whenever in the step it came.
    if (err instanceof Skip || (LIVE && page.isClosed())) record.skipped = true;
    else record.error = String(err.message || err).split("\n")[0];
  } finally {
    if (!LIVE) {
      const video = page.video();
      await context.close();
      if (video) {
        const name = `scenario-${i + 1}.webm`;
        await fs.promises.rename(await video.path(), path.join(OUT, name));
        record.video = name;
      }
    }
  }
  return record;
}

// The local time with its offset (2026-11-01T14:05:00+03:00): shown as
// written, it is the developer's clock, as the commits beside it are.
function localTime() {
  const d = new Date(), off = -d.getTimezoneOffset(), pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  const local = new Date(d.getTime() + off * 60000).toISOString().slice(0, 19);
  return `${local}${off >= 0 ? "+" : "-"}${pad(off / 60)}:${pad(off % 60)}`;
}

// What makes a scenario the same one in two recordings: everything the
// script says of it, its steps' source included. A helper of the script's
// own outside the scenario is not in it — change one, and play all again.
function sig(s, demo) {
  const look = Array.isArray(s.look) ? s.look : s.look ? [s.look] : [];
  return createHash("sha1").update(JSON.stringify([s.title, s.as, s.path || "/", viewportOf(s, demo),
    s.shows || "", look, s.why || "", String(s.steps)])).digest("hex").slice(0, 16);
}

// The scenarios taken from the earlier recording (--keep-from), by index:
// its record with its files copied here, or null for one to play.
function keepPlan(demo) {
  const plan = demo.scenarios.map(() => null);
  if (!KEEP_FROM) return plan;
  const past = [...ONLY].filter((n) => n > demo.scenarios.length);
  if (past.length) {
    console.error(`error: the script has ${demo.scenarios.length} scenario(s), no ${past.join(", ")}`);
    process.exit(2);
  }
  let before;
  try {
    before = JSON.parse(fs.readFileSync(path.join(KEEP_FROM, "demo.json"), "utf8"));
  } catch {
    console.log(`again: ${KEEP_FROM} has no demo.json — every scenario plays`);
    return plan;
  }
  for (const [i, s] of demo.scenarios.entries()) {
    if (ONLY.has(i + 1)) continue;
    const r = (before.scenarios || [])[i];
    const files = r ? [...(r.sources || []).map((v) => v.src), r.captions].filter(Boolean) : [];
    const ok = r && !r.error && !r.skipped && r.sig && r.sig === sig(s, demo) && files.length
      && files.every((f) => fs.existsSync(path.join(KEEP_FROM, f)));
    if (!ok) {
      if (r) console.log(`scenario ${i + 1}: plays again — ${r.error || r.skipped ? "it did not play there"
        : r.sig === sig(s, demo) ? "its video is not there" : "it changed since"}`);
      continue;
    }
    for (const f of files) {
      // A hard link where the file system allows: the same video twice costs nothing.
      try { fs.linkSync(path.join(KEEP_FROM, f), path.join(OUT, f)); }
      catch { fs.copyFileSync(path.join(KEEP_FROM, f), path.join(OUT, f)); }
    }
    plan[i] = { ...r, kept: path.basename(KEEP_FROM) };
  }
  // Nothing left to play is no try: it would go into the history as one.
  if (plan.every(Boolean)) {
    console.error("error: every scenario is the same as in " + path.basename(KEEP_FROM) +
      " and none is listed — nothing to play again");
    process.exit(2);
  }
  return plan;
}

// A scenario's video made what the page plays, and its captions.
async function finish(r) {
  r.sources = await squeeze(r.video);
  r.captions = r.video.replace(/\.webm$/, ".vtt");
  fs.writeFileSync(path.join(OUT, r.captions), vtt(r));
}

async function main() {
  const demo = (await import(pathToFileURL(path.resolve(scriptPath)).href)).default;
  if (!demo || !Array.isArray(demo.scenarios) || !demo.scenarios.length) {
    console.error("error: the script exports no scenarios");
    process.exit(2);
  }
  for (const [i, s] of demo.scenarios.entries()) {
    if (!s.title || !s.as || typeof s.steps !== "function") {
      console.error(`error: scenario ${i + 1} needs title, as and steps(d)`);
      process.exit(2);
    }
  }
  fs.mkdirSync(OUT, { recursive: true });
  const kept = LIVE ? [] : keepPlan(demo);
  // Opened for the first scenario that plays: one taken whole from the
  // earlier recording needs no browser.
  let browser = null;
  const open = async () => {
    if (browser) return browser;
    const { chromium } = playwright();
    browser = LIVE ? await chromium.connectOverCDP(CDP) : await chromium.launch();
    return browser;
  };
  // Each video is encoded as soon as its scenario ends, one at a time and
  // at a lower priority, while the next scenario records — most of which is
  // waiting for a reader. Before, all of them were encoded after the last.
  let encoding = Promise.resolve();
  // kind "delta": only what changed for the user since the last full demo,
  // `change` saying what, in a sentence (demo.py keeps the history of both).
  const results = { title: demo.title || "Demo", viewport: demo.viewport || "desktop",
    made: localTime(), live: LIVE, kind: demo.kind === "delta" ? "delta" : "main",
    change: String(demo.change || ""), scenarios: [] };
  let stopped = false;
  for (const [i, s] of demo.scenarios.entries()) {
    // Live, a pause or a stop pressed as the last scenario ended holds the
    // next one before it opens anything; ⏭ there means "go on" — to this
    // scenario, which nothing of has been shown yet.
    while (state === "paused") {
      // Every window closed while paused: nobody is left to press ▶.
      if (![...contexts.values()].some((c) => c.pages().length)) state = "stopped";
      else await sleep(250);
    }
    if (state === "skip") state = "playing";
    if (state === "stopped") {
      stopped = true;
      console.log(`scenario ${i + 1}: not started, stopped by the person`);
      break;
    }
    if (kept[i]) {
      results.scenarios.push(kept[i]);
      console.log(`scenario ${i + 1}: kept from ${path.basename(KEEP_FROM)}`);
      fs.writeFileSync(path.join(OUT, "demo.json"), JSON.stringify(results, null, 1));
      continue;
    }
    progress({ kind: results.kind, scenario: i + 1, of: demo.scenarios.length, title: String(s.title),
      viewport: viewportOf(s, demo),
      step: 0, playing: demo.scenarios.length - kept.filter(Boolean).length });
    try {
      const r = await scenario(await open(), demo, s, i, contexts);
      r.sig = sig(s, demo);
      // A failure here is this video's alone: left to reject, it would kill
      // the player in the middle of the next scenario. A scenario with no
      // video did not play, for publishing and for --only failed alike.
      if (r.video) encoding = encoding.then(() => finish(r)).catch((err) => {
        const why = "its video was not finished: " + String(err.message || err).split("\n")[0];
        // The scenario's own failure stays first: it is what the script needs fixed.
        r.error = r.error ? `${r.error}; ${why}` : why;
        console.log(`scenario ${i + 1}: ${why}`);
      });
      // A skip pressed while this scenario signed in, ended or failed was
      // meant for it — not for the next one.
      if (state === "skip") state = "playing";
      results.scenarios.push(r);
      const failed = r.steps.filter((x) => x.ok === false || x.error).length;
      console.log(`scenario ${i + 1}: ${r.error ? "failed — " + r.error : r.skipped ? "skipped by the person" : "done"}` +
        (failed ? ` (${failed} step(s) not as expected)` : ""));
    } catch (err) {
      if (!(err instanceof Stop)) throw err;
      stopped = true;
      console.log(`scenario ${i + 1}: stopped by the person`);
      break;
    }
    fs.writeFileSync(path.join(OUT, "demo.json"), JSON.stringify(results, null, 1));
  }
  fs.writeFileSync(path.join(OUT, "demo.json"), JSON.stringify(results, null, 1));
  if (LIVE) {
    // The windows are the person's now: stay connected until they close
    // them (closing the connection would close them too), at most a day.
    if (!stopped) state = "stopped";
    for (const c of contexts.values())
      for (const p of c.pages()) p.evaluate(() => window.__sdemo?.draw?.("stopped")).catch(() => {});
    console.log("live: the windows stay open until they are closed");
    const open = () => [...contexts.values()].some((c) => c.pages().length);
    const until = Date.now() + 24 * 3600 * 1000;
    while (open() && Date.now() < until) await sleep(2000);
    process.exit(0);
  }
  if (browser) await browser.close();
  await encoding;
  fs.writeFileSync(path.join(OUT, "demo.json"), JSON.stringify(results, null, 1));
  const page = fs.readFileSync(new URL("./player.html", import.meta.url), "utf8")
    // Functions, not strings: a "$&" in a caption would otherwise be read as
    // a pattern of replace() itself.
    .replace("/*DEMO*/null", () => JSON.stringify(results).replace(/</g, "\\u003c"))
    .replace('/*FEATURE*/""', () => JSON.stringify(FEATURE).replace(/</g, "\\u003c"))
    .replace("/*DEEPLINK*/", () => fs.readFileSync(new URL("./deeplink.js", import.meta.url), "utf8"));
  fs.writeFileSync(path.join(OUT, "index.html"), page);
}

// The steps as captions, for a full-screen player, where the page around
// the video is gone: each from its time to the next step's.
function vtt(r) {
  const ts = (t) => {
    const ms = Math.max(0, Math.round(t * 1000));
    const h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, sec = Math.floor(ms / 1000) % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
  };
  const clean = (x) => String(x).replace(/-->/g, "→").replace(/\n+/g, " ");
  const cues = r.steps.map((st, i) => {
    const end = i + 1 < r.steps.length ? r.steps[i + 1].t : st.t + 5;
    const mark = st.ok === true ? "✓ " : st.ok === false || st.error ? "✗ " : "";
    const lines = [mark + clean(st.text || st.kind)];
    if (st.look) lines.push("👀 " + clean(st.look));
    if (st.why) lines.push("💡 " + clean(st.why));
    return `${i + 1}\n${ts(st.t)} --> ${ts(Math.max(end, st.t + 0.5))}\n${lines.join("\n")}`;
  });
  return "WEBVTT\n\n" + cues.join("\n\n") + "\n";
}

// What the page plays. Playwright writes VP8 WebM at a fixed, generous
// rate, which Safari before 17.4 does not play. With an ffmpeg that has
// libx264 (Ubuntu's does; Playwright's own is built for VP8 alone) it becomes
// H.264 MP4: every browser and Telegram play it, at about a quarter of the
// size. A screen recording is sharp text on flat colour that barely moves:
// tuned for still images (less deblocking) the text stays sharp; 4:2:0, since
// no phone decodes 4:4:4 in hardware; a key frame every 4 s, which costs
// little where frames repeat and keeps a tap on a step quick to seek.
// AV1 was measured against it on such a recording (SVT-AV1 1.7, its
// screen-content tools on): 1% smaller at three times the encoding time, 7%
// at six — not worth a second file. Without ffmpeg, the WebM alone.
async function squeeze(name) {
  const src = path.join(OUT, name);
  const webm = [{ src: name, type: "video/webm" }];
  const mp4 = name.replace(/\.webm$/, ".mp4");
  try {
    await new Promise((resolve, reject) => {
      const child = execFile("ffmpeg", ["-y", "-loglevel", "error", "-i", src, "-c:v", "libx264", "-preset", "slow",
        "-crf", "26", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-profile:v", "high", "-g", "100",
        "-movflags", "+faststart", "-an", path.join(OUT, mp4)], (err) => (err ? reject(err) : resolve()));
      // Below the browser that records the next scenario: a frame it drops
      // is a jerk in the video, an encoding a second slower is nothing.
      try { os.setPriority(child.pid, 10); } catch {}
    });
    if (!fs.statSync(path.join(OUT, mp4)).size) return webm;
  } catch {
    return webm;
  }
  fs.unlinkSync(src);
  return [{ src: mp4, type: "video/mp4" }];
}

main().catch((err) => {
  console.error("error: " + (err.stack || err));
  process.exit(1);
});
