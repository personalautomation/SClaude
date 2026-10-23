#!/usr/bin/env python3
"""statusline.py: the prompt-cache countdown and the cost of rebuilding it."""
import importlib.util
import json
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("statusline", os.path.join(ROOT, "statusline.py"))
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)

TMP = tempfile.mkdtemp()
sl.SPEND_FILE = os.path.join(TMP, "spend.json")
FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append("%s: got %r, want %r" % (name, got, want))


def plain(s):
    return re.sub(r"\033\[[0-9;]*m", "", s or "")


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + ".123Z"


def entry(age, written=None, ttl="1h", sidechain=False, tokens=100000):
    usage = {"input_tokens": 0, "cache_read_input_tokens": tokens,
             "cache_creation_input_tokens": written or 0, "output_tokens": 0,
             "cache_creation": {"ephemeral_1h_input_tokens": written if ttl == "1h" else 0,
                                "ephemeral_5m_input_tokens": written if ttl == "5m" else 0}}
    return {"type": "assistant", "isSidechain": sidechain, "timestamp": iso(time.time() - age),
            "message": {"model": "claude-opus-5-5", "usage": usage}}


def transcript(*entries):
    path = os.path.join(TMP, "t%d.jsonl" % len(os.listdir(TMP)))
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
            f.write(json.dumps({"type": "user", "timestamp": e["timestamp"]}) + "\n")
    return path


def piece(path, rate=None):
    return plain(sl.cache_piece({"transcript_path": path, "model": {"id": "claude-opus-5-5"}}, rate))


# A 1-hour cache written ten minutes ago has fifty left, even when the last
# request only read it.
check("1h countdown", piece(transcript(entry(700, written=500), entry(600))), "50m")
# A 5-minute cache, two minutes on.
check("5m countdown", piece(transcript(entry(120, written=500, ttl="5m"))), "3m")
# A subagent's later request is not the conversation's.
check("sidechain skipped",
      piece(transcript(entry(1000, written=500, ttl="5m"), entry(10, sidechain=True))), "off ~$0.50")
# Expired: 100k tokens at $4/MTok, 2x for a 1-hour write = $0.80.
check("expired, dollars", piece(transcript(entry(4000, written=500))), "off ~$0.80")
check("expired, percent", piece(transcript(entry(4000, written=500)), rate=5.0), "off ~4%")
check("no transcript", sl.cache_piece({}, None), None)
# A transcript with no breakdown of its cache writes: the 5-minute TTL, at once.
_old = entry(120, written=500, ttl="5m")
del _old["message"]["usage"]["cache_creation"]
check("no breakdown: 5 minutes", piece(transcript(_old)), "3m")
# The write far back, past the first tail read: the tail grows to it.
check("1h write past the first tail",
      piece(transcript(entry(700, written=500),
                       *[entry(600, tokens=n) for n in range(600)])), "50m")


def tick(sid, cost, pct, window=2_000_000_000):
    return sl.remember_spend({"session_id": sid, "cost": {"total_cost_usd": cost},
                              "rate_limits": {"five_hour": {"used_percentage": pct, "resets_at": window}}})


# The rate is learnt from spend across sessions against the percentage moved.
check("first sight", tick("a", 3.0, 10), None)
check("too little yet", tick("a", 3.2, 10), None)
tick("b", 7.0, 10)                    # seen first: its earlier spend is not counted
check("learnt", round(tick("b", 8.8, 16), 6), 3.0)  # $0.2 + $1.8 moved 6%
# A new window starts over but keeps the last rate until it learns a new one.
check("new window keeps rate", round(tick("a", 4.0, 1, window=2_000_018_000), 6), 3.0)
# A session resumed under its id counts from zero again: the lower cost is the
# new baseline, and what it spends from there counts.
tick("c", 3.0, 1, window=2_000_018_000)
tick("c", 0.1, 1, window=2_000_018_000)
tick("c", 1.1, 1, window=2_000_018_000)
check("resumed session's spend counts from its new baseline",
      round(json.load(open(sl.SPEND_FILE))["spend"], 6), 1.8)  # a: $0.8 + c: $1.0

if FAILS:
    print("\n".join(FAILS))
    sys.exit(1)
print("ok")
