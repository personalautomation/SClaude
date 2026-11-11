#!/usr/bin/env python3
"""/sdemo's voice: the steps' lines spoken, for the recorded videos.

  voice.py serve        one JSON line in per line to say, one out per line said
  voice.py fetch        the model downloaded, nothing said (once per machine)

play.mjs runs `serve` beside the browser while it records, through uv (the
packages are not the system's), at a lower priority. On its first line it
answers {"ready": true} once the model is loaded, or {"error": "..."} and
exits; after that each {"id", "text", "out"} becomes a WAV at `out` and the
answer {"id", "seconds"} (or {"id", "error"}). Lines are said one at a time,
in the order they came.

The engine is Kokoro-82M (Apache 2.0) through onnxruntime, on the CPU: about
three quarters of real time on a laptop's CPU, slower beside a recording
browser — play.mjs holds a step by the line's estimated length, not by the
line being ready. The model, ~350 MB, is fetched once into the
user's cache and checked against its hash. SDEMO_VOICE_ENGINE=fake answers
with silence as long as the line would take, for the tests.
"""
import hashlib
import json
import os
import sys
import tempfile
import urllib.request
import wave

VOICE = "af_heart"  # American English, the clearest of Kokoro's voices
SPEED = 1.1
LANG = "en-us"
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                     "sclaude", "voice")


def log(text):
    # Nobody may be reading: a voice the player let go goes on fetching.
    try:
        sys.stderr.write("voice: %s\n" % text)
        sys.stderr.flush()
    except OSError:
        pass


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch():
    """The model's files in the cache, downloaded when missing; their paths."""
    os.makedirs(CACHE, exist_ok=True)
    paths = []
    for name, want in FILES.items():
        path = os.path.join(CACHE, name)
        paths.append(path)
        if os.path.isfile(path):
            continue
        log("fetching %s (once per machine)" % name)
        # A name of this process's own: two recordings starting at once on a
        # fresh machine each download whole, and the second rename wins.
        fd, part = tempfile.mkstemp(dir=CACHE, prefix=name + ".", suffix=".part")
        os.close(fd)
        try:
            urllib.request.urlretrieve(RELEASE + name, part)
        except BaseException:
            os.unlink(part)
            raise
        got = sha256(part)
        if got != want:
            os.unlink(part)
            raise RuntimeError("%s does not match its hash (got %s)" % (name, got[:12]))
        os.replace(part, path)
    return paths


class Fake:
    """Silence as long as a reader would take: the protocol without a model."""
    RATE = 24000

    def say(self, text, out):
        frames = int(self.RATE * max(0.3, len(text) * 0.06))
        with wave.open(out, "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(self.RATE)
            fh.writeframes(b"\0\0" * frames)
        return frames / self.RATE


class Kokoro:
    def __init__(self):
        import onnxruntime
        import soundfile
        from kokoro_onnx import Kokoro as Engine

        model, voices = fetch()
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = os.cpu_count() or 1
        # Every core, at the lower priority play.mjs starts it at: the browser
        # beside it records first, and the voice takes what is left. Held to
        # half, it ran slower than speech there.
        session = onnxruntime.InferenceSession(model, options, providers=["CPUExecutionProvider"])
        self.engine = Engine.from_session(session, voices)
        self.soundfile = soundfile

    def say(self, text, out):
        audio, rate = self.engine.create(text, voice=VOICE, speed=SPEED, lang=LANG)
        self.soundfile.write(out, audio, rate, subtype="PCM_16")
        return len(audio) / rate


def spoken(text):
    """The line as a voice reads it: a dash is a pause, not a word."""
    return " ".join(text.replace("—", ",").replace("→", "to").split())


def answer(fields):
    sys.stdout.write(json.dumps(fields) + "\n")
    sys.stdout.flush()


def serve():
    try:
        engine = Fake() if os.environ.get("SDEMO_VOICE_ENGINE") == "fake" else Kokoro()
    except Exception as exc:  # no package, no network, a model that does not load
        answer({"error": str(exc).split("\n")[0] or type(exc).__name__})
        return 1
    answer({"ready": True})
    for line in sys.stdin:
        try:
            ask = json.loads(line)
        except ValueError:
            continue
        try:
            answer({"id": ask["id"], "seconds": round(engine.say(spoken(ask["text"]), ask["out"]), 3)})
        except Exception as exc:
            answer({"id": ask.get("id"), "error": str(exc).split("\n")[0] or type(exc).__name__})
    return 0


def main(argv):
    if argv[:1] == ["serve"]:
        return serve()
    if argv[:1] == ["fetch"]:
        for path in fetch():
            print(path)
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
