// /sdemo's voice, play.mjs's side: voice.py run beside the browser, a step's
// line sent to it as the step starts, and the lines put on the video's sound
// track when its scenario is encoded.
//
// Why at the step, not after the recording: the player holds each step until
// its line should have been said (`hold`: by its length, or by `spokenFor`
// while it is still being made), so the video is cut to the voice. A line
// made longer than guessed is hurried to fit, up to FASTEST; past that its
// tail runs over the next line's start. The line is made while the step plays — the
// ring, the reading pause, the click, the page loading — which is longer than
// the making, so the hold rarely waits. Said after the recording instead, a
// long line could only be hurried or pushed past its step.
import { spawn, execFileSync } from "node:child_process";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

const VOICE_PY = fileURLToPath(new URL("./voice.py", import.meta.url));
// Pinned, as the model's hash is: what was heard is what will be heard.
const PACKAGES = ["kokoro-onnx==0.6.1", "soundfile==0.14.0"];
// A line is made in seconds; one not made in a minute is not coming.
const LINE_WITHIN = 60 * 1000;

function which(cmd) {
  try {
    execFileSync("sh", ["-c", `command -v ${cmd}`], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

// The worker started. `ready` resolves to "" once it can speak, or to why it
// cannot — the recording then goes on silent.
export function startVoice(log = console.log) {
  const fake = process.env.SDEMO_VOICE_ENGINE === "fake";
  if (!fake && !which("uv")) return { ready: Promise.resolve("no uv on this machine (docs.astral.sh/uv)"), say: async () => null,
    dead: () => "no uv", close: async () => {}, release() {} };
  const run = fake ? ["python3", VOICE_PY, "serve"]
    : ["uv", "run", "--quiet", "--no-project", ...PACKAGES.flatMap((p) => ["--with", p]), "python3", VOICE_PY, "serve"];
  // Under nice, so that the python uv starts is at the lower priority too,
  // and in a process group of its own: uv does not exec python, and a kill
  // meant for the voice must reach it (close).
  const child = spawn("nice", ["-n", "10", ...run], { stdio: ["pipe", "pipe", "pipe"], detached: true });
  const waiting = new Map();
  let next = 1, dead = "";
  let ready;
  const readyP = new Promise((r) => (ready = r));
  readline.createInterface({ input: child.stderr }).on("line", (l) => log(l));
  readline.createInterface({ input: child.stdout }).on("line", (l) => {
    let m;
    try { m = JSON.parse(l); } catch { return; }
    if (m.ready) { ready(""); return; }
    if (m.id == null) { ready(m.error || "the voice did not start"); return; }
    const w = waiting.get(m.id);
    waiting.delete(m.id);
    if (w) w(m.error ? null : m.seconds);
  });
  let exited;
  const exit = new Promise((r) => (exited = r));
  const gone = (why) => {
    exited();
    dead = why;
    ready(why);
    for (const w of waiting.values()) w(null);
    waiting.clear();
  };
  child.on("error", (err) => gone(String(err.message || err)));
  child.on("exit", (code) => gone(`the voice stopped (exit ${code})`));
  child.stdin.on("error", () => {});
  return {
    ready: readyP,
    // The line made into `out`; its length in seconds, or null when it was not.
    say(text, out) {
      if (dead || !String(text || "").trim()) return Promise.resolve(null);
      const id = next++;
      return new Promise((resolve) => {
        // A line the voice never answers is a silent line, not a player
        // that waits for ever to encode its video.
        const timer = setTimeout(() => { if (waiting.delete(id)) resolve(null); }, LINE_WITHIN);
        timer.unref();
        waiting.set(id, (s) => { clearTimeout(timer); resolve(s); });
        child.stdin.write(JSON.stringify({ id, text: String(text), out }) + "\n");
      });
    },
    // Why the voice stopped, once it has; "" while it runs.
    dead: () => dead,
    // No more lines; resolves once the voice has said what it was given and
    // gone — given ten seconds, then stopped, so that nothing it writes
    // later lands in a demo already swept.
    async close() {
      child.stdin.end();
      let timer;
      const late = await Promise.race([exit.then(() => false),
        new Promise((r) => { timer = setTimeout(() => r(true), 10000); })]);
      clearTimeout(timer);
      if (late) {
        try { process.kill(-child.pid, "SIGKILL"); } catch {}
        await exit;
      }
    },
    // Let go of a voice that is not ready yet: it goes on fetching the model
    // on its own, for the next recording, and the player may exit meanwhile.
    release() {
      child.stdin.end();
      child.stdout.destroy();
      child.stderr.destroy();
      child.unref();
    },
  };
}

// How long a line takes to say, before it is made: Kokoro at voice.py's
// SPEED speaks about 18 characters a second, steadily (measured on a demo's
// lines: within half a second for lines of 4 to 90 characters). Changed
// there, measured again here.
export const spokenFor = (text) => 0.25 + 0.056 * String(text || "").replace(/→/g, " to ").trim().length;

// The most a line is hurried to fit its place: beyond it the words blur, and
// the tail of the line runs a little over the next one instead.
const FASTEST = 1.3;

// What ffmpeg needs, after the video's own input (0), to lay the lines on a
// track at their times: an input per line, and the filter that delays each to
// its time and mixes them. A line's place is up to the next line (the last
// one's, its estimate and the end caption's moment); a line longer than its
// place — made slower than guessed while the step was held — is sped up to
// fit. Kept apart so, the mix only adds silence to speech: normalize=0, or
// each line would come out quieter by the number of lines.
export function trackArgs(clips) {
  if (!clips.length) return null;
  const inputs = clips.flatMap((c) => ["-i", c.file]);
  const delayed = clips.map((c, i) => {
    const ms = Math.max(0, Math.round(c.t * 1000));
    const room = i + 1 < clips.length ? clips[i + 1].t - c.t - 0.15 : (c.guess ?? c.seconds) + 1.5;
    const tempo = room > 0 ? Math.min(FASTEST, c.seconds / room) : 1;
    const fit = tempo > 1.01 ? `atempo=${tempo.toFixed(3)},` : "";
    return `[${i + 1}:a]${fit}adelay=${ms}:all=1[a${i}]`;
  });
  const mix = clips.length === 1 ? "[a0]anull[voice]"
    : `${clips.map((_, i) => `[a${i}]`).join("")}amix=inputs=${clips.length}:normalize=0:dropout_transition=0[voice]`;
  return { inputs, filter: [...delayed, mix].join(";"), map: ["-map", "0:v", "-map", "[voice]",
    "-c:a", "aac", "-b:a", "96k"] };
}
