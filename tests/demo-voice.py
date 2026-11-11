#!/usr/bin/env python3
"""A recorded demo spoken (skills/sdemo/voice.py, voice.mjs, play.mjs --voice):

  - voice.py serve answers ready, then a WAV and its length for each line
    (the fake engine: the protocol without the model);
  - voice.mjs starts it and hands play.mjs the lengths; trackArgs lays the
    lines at their times, hurries one longer than its place (no more than
    FASTEST), and ffmpeg takes the filter it writes;
  - demo.py passes --voice unless the project's demoVoice is off, this
    machine's choice first; config_menu offers the key and the example
    config explains it.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDEMO = os.path.join(ROOT, "skills", "sdemo")
sys.path.insert(0, SDEMO)
sys.path.insert(0, os.path.join(ROOT, "sclaude", "lib", "core"))
failures = []


def check(name, got, want):
    if got != want:
        failures.append(name)
        print("FAIL %s\n  got:  %r\n  want: %r" % (name, got, want))
    else:
        print("ok   %s" % name)


FAKE = dict(os.environ, SDEMO_VOICE_ENGINE="fake")
tmp = tempfile.mkdtemp()
try:
    # voice.py serve, its protocol.
    wav = os.path.join(tmp, "one.wav")
    done = subprocess.run([sys.executable, os.path.join(SDEMO, "voice.py"), "serve"], env=FAKE,
                          input=json.dumps({"id": 7, "text": "Send it", "out": wav}) + "\n",
                          capture_output=True, text=True, timeout=30)
    lines = [json.loads(x) for x in done.stdout.splitlines()]
    check("voice.py: ready first", lines[:1], [{"ready": True}])
    check("voice.py: the line answered by its id, with its length",
          (lines[1]["id"], lines[1]["seconds"] > 0) if len(lines) > 1 else None, (7, True))
    check("voice.py: the WAV written", os.path.getsize(wav) > 44 if os.path.exists(wav) else False, True)
    import voice
    check("voice.py: a dash is a pause, not a word", voice.spoken("A — b  c"), "A , b c")

    if shutil.which("node"):
        js = r"""
import { startVoice, trackArgs, spokenFor } from "%s";
const v = startVoice(() => {});
const why = await v.ready;
const secs = await v.say("Bring one companion", process.argv[1] + "/a.wav");
const blank = await v.say("   ", process.argv[1] + "/b.wav");
v.close();
await new Promise((r) => setTimeout(r, 1500));
const dead = v.dead();
const after = await v.say("too late", process.argv[1] + "/c.wav");
const two = trackArgs([{ t: 1.5, seconds: 1.6, guess: 1.6, file: "a.wav" },
                       { t: 3, seconds: 1, guess: 1, file: "b.wav" }]);
const far = trackArgs([{ t: 0, seconds: 9, guess: 1, file: "a.wav" }, { t: 2, seconds: 1, file: "b.wav" }]);
console.log(JSON.stringify({ why, secs, blank, dead, after, arrow: spokenFor("A → B") > spokenFor("A x B"), none: trackArgs([]), two, far, est: spokenFor("x".repeat(90)) }));
""" % os.path.join(SDEMO, "voice.mjs")
        done = subprocess.run(["node", "--input-type=module", "-e", js, tmp], env=FAKE,
                              capture_output=True, text=True, timeout=60)
        got = json.loads(done.stdout or "{}")
        check("voice.mjs: the fake voice is ready", got.get("why"), "")
        check("voice.mjs: a line's length comes back", (got.get("secs") or 0) > 0, True)
        check("voice.mjs: nothing to say is not sent", got.get("blank"), None)
        check("voice.mjs: no lines, no track", got.get("none"), None)
        check("voice.mjs: a voice that stopped says why", bool(got.get("dead")), True)
        check("voice.mjs: a stopped voice makes no line", got.get("after"), None)
        check("spokenFor: an arrow is said as a word", got.get("arrow"), True)
        two = got.get("two") or {}
        check("trackArgs: an input per line", two.get("inputs"), ["-i", "a.wav", "-i", "b.wav"])
        check("trackArgs: each line delayed to its time, hurried to fit before the next",
              two.get("filter"), "[1:a]atempo=1.185,adelay=1500:all=1[a0];[2:a]adelay=3000:all=1[a1];"
              "[a0][a1]amix=inputs=2:normalize=0:dropout_transition=0[voice]")
        check("trackArgs: never hurried past FASTEST",
              (got.get("far") or {}).get("filter", "").startswith("[1:a]atempo=1.300,"), True)
        check("spokenFor: about 18 characters a second", round(got.get("est", 0), 2), 5.29)

        # ffmpeg takes the filter: a short video and two lines become one
        # file with a sound track.
        if shutil.which("ffmpeg"):
            video = os.path.join(tmp, "v.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=64x64:d=4",
                            "-c:v", "libx264", video], check=True)
            for name in ("a", "b"):
                voice.Fake().say("a line", os.path.join(tmp, name + ".wav"))
            track = two
            out = os.path.join(tmp, "out.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video] +
                           [x if not x.endswith(".wav") else os.path.join(tmp, x) for x in track["inputs"]] +
                           ["-filter_complex", track["filter"]] + track["map"] + ["-c:v", "copy", out],
                           check=True)
            streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                      "-of", "csv=p=0", out], capture_output=True, text=True).stdout.split()
            check("ffmpeg: the video gets a sound track", streams, ["video", "audio"])
    else:
        print("skip: no node")

    # The setting: on unless off, this machine's choice over the config.
    import demo
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, ".sclaude", "local"))
    subprocess.run(["git", "init", "-q", repo], check=True)
    check("demoVoice: absent is on", demo.voice_on(repo), True)
    with open(os.path.join(repo, ".sclaude", "config.json"), "w") as fh:
        json.dump({"demoVoice": "off"}, fh)
    check("demoVoice: off in the config", demo.voice_on(repo), False)
    with open(os.path.join(repo, ".sclaude", "local", "config.json"), "w") as fh:
        json.dump({"demoVoice": "on"}, fh)
    check("demoVoice: this machine's choice first", demo.voice_on(repo), True)

    import config_menu
    check("config_menu: demoVoice offers on and off",
          [c for c, _ in config_menu.CHOICES.get("demoVoice", [])], ["on", "off"])
    example = json.load(open(os.path.join(ROOT, "sclaude", "config.example.json")))
    check("config.example: demoVoice set", example.get("demoVoice"), "on")
    check("config.example: demoVoice explained",
          "demoVoice" in config_menu.explanations(os.path.join(ROOT, "sclaude", "config.example.json")), True)

    play = open(os.path.join(SDEMO, "play.mjs")).read()
    check("play.mjs: --voice read", '"--voice"' in play, True)
    check("demo.py: passes --voice", '"--voice"' in open(os.path.join(SDEMO, "demo.py")).read(), True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

sys.exit(1 if failures else 0)
