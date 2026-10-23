#!/usr/bin/env python3
"""Custom statusline for Claude Code.

Reads the statusLine JSON on stdin, prints one line laid out in three zones:
left (the sclaude session, then the path), middle (git branch, the sclaude
feature's pull request, session, worktree),
right (model, effort, context, rate limits). Never raises: any surprise falls
back to a bare path.

Symlinked to ~/.claude/statusline.py by this repository's install.sh — that is
the path settings.json names, so the symlink is what keeps the setting working.
"""
import calendar
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

RESET = "\033[0m"
DIM = "\033[2m"
BLUE = "\033[38;5;39m"
GREEN = "\033[38;5;71m"
GREY = "\033[38;5;245m"
PURPLE = "\033[38;5;141m"
ORANGE = "\033[38;5;208m"
YELLOW = "\033[38;5;179m"

# Bar fill colours, by how full the bar is.
OK = "\033[38;5;71m"
WARN = "\033[38;5;179m"
HOT = "\033[38;5;167m"

ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Columns the panel keeps for itself at the right edge, and clips anything
# written into. See layout().
RIGHT_MARGIN = 5

# Emoji occupy two terminal columns; str len would undercount them.
WIDE_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")


def vislen(s):
    """Visible width in terminal columns, ignoring ANSI and counting wide chars."""
    s = ANSI_RE.sub("", s)
    n = 0
    for ch in s:
        if WIDE_RE.match(ch) or unicodedata.east_asian_width(ch) in ("W", "F"):
            n += 2
        elif unicodedata.combining(ch):
            n += 0
        else:
            n += 1
    return n


def paint(text, colour):
    return colour + text + RESET


def fill_colour(pct):
    if pct >= 80:
        return HOT
    if pct >= 50:
        return WARN
    return OK


def bar(pct, width):
    """A ▓/░ progress bar, coloured by how full it is."""
    pct = max(0, min(100, pct))
    filled = int(round(pct * width / 100.0))
    return paint("▓" * filled + "░" * (width - filled), fill_colour(pct))


def fmt_reset(epoch):
    """Seconds-from-now as `2h14m`, or None when absent/past."""
    if not epoch:
        return None
    left = int(epoch - time.time())
    if left <= 0:
        return None
    h, m = left // 3600, (left % 3600) // 60
    return "%dh%02dm" % (h, m) if h else "%dm" % m


# How long the prompt cache outlives the last request, by the TTL it was
# written with.
TTL_5M, TTL_1H = 300, 3600

# How far back in the transcript the last request is looked for. A turn's
# tool output can be large; this is several of them.
TRANSCRIPT_TAIL = 1 << 20

# Base input price, $ per million tokens, by model id prefix; the most
# specific prefix first. A cache write costs 1.25x that with a 5-minute TTL,
# 2x with a 1-hour one.
INPUT_PRICE = [
    ("claude-fable", 10.0), ("claude-mythos", 10.0),
    ("claude-opus-5-5", 4.0), ("claude-opus", 5.0),
    ("claude-sonnet-4", 3.0), ("claude-sonnet", 2.0),
    ("claude-haiku-5", 0.10), ("claude-haiku", 1.0),
]
WRITE_FACTOR = {TTL_5M: 1.25, TTL_1H: 2.0}


def parse_ts(ts):
    """ISO-8601 `2026-10-23T11:08:44.451Z` as epoch seconds, else None."""
    try:
        base, _, frac = ts.rstrip("Z").partition(".")
        t = calendar.timegm(time.strptime(base, "%Y-%m-%dT%H:%M:%S"))
        return t + (float("0." + frac) if frac.isdigit() else 0.0)
    except (AttributeError, ValueError, OverflowError):
        return None


def last_request(path):
    """(epoch, usage, ttl) of the main conversation's last request, else None.

    The time is when its answer was written; the cache was read or written by
    that request and lives for the TTL from then. The TTL is that of the last
    request that wrote to the cache: one that only read it keeps the TTL the
    cache already had. Subagents (sidechains) keep caches of their own.
    """
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TRANSCRIPT_TAIL))
            lines = f.read().splitlines()
    except OSError:
        return None
    found = None
    for raw in reversed(lines):
        if b'"assistant"' not in raw or b'"usage"' not in raw:
            continue
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        usage = dig(e, "message", "usage")
        if not isinstance(usage, dict) or dig(e, "message", "model") == "<synthetic>":
            continue
        if found is None:
            when = parse_ts(e.get("timestamp"))
            if when is None:
                continue
            found = (when, usage)
        written = usage.get("cache_creation") or {}
        if written.get("ephemeral_1h_input_tokens"):
            return found + (TTL_1H,)
        if written.get("ephemeral_5m_input_tokens"):
            return found + (TTL_5M,)
    return found + (TTL_5M,) if found else None


def prefix_tokens(usage):
    """The tokens the next request sends ahead of its new input: all of the last one."""
    return sum(usage.get(k) or 0 for k in (
        "input_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "output_tokens"))


def rewrite_cost(model, tokens, ttl):
    """Dollars to write `tokens` into the cache again, else None for an unknown model."""
    for prefix, price in INPUT_PRICE:
        if (model or "").startswith(prefix):
            return tokens * price * WRITE_FACTOR[ttl] / 1e6
    return None


# Spend across every session on this machine, against the five-hour limit, so
# that dollars can be told as a share of it. The limit is not in dollars and
# Claude Code does not say what a percent is worth; this file learns it from
# how far the percentage moves while the sessions spend. Use outside Claude
# Code moves the percentage too, which makes the figure an estimate on the
# high side.
SPEND_FILE = "/tmp/claude-statusline-spend.json"

# Below these the rate is mostly rounding.
RATE_MIN_SPEND = 0.5
RATE_MIN_PCT = 1.0


def remember_spend(d):
    """Add this session's new spend to the window's; return % per dollar, else None."""
    sid = d.get("session_id")
    cost = dig(d, "cost", "total_cost_usd")
    five = dig(d, "rate_limits", "five_hour") or {}
    pct, window = five.get("used_percentage"), five.get("resets_at")
    try:
        with open(SPEND_FILE) as f:
            s = json.load(f)
        if not isinstance(s, dict):
            s = {}
    except (OSError, ValueError):
        s = {}
    rate = s.get("rate")
    if not sid or not isinstance(cost, (int, float)) \
            or not isinstance(pct, (int, float)) or not window:
        return rate
    # resets_at is rounded to the minute: a second of jitter is not a new window.
    window = int(window) // 60
    if s.get("window") != window:
        s.update(window=window, start_pct=pct, spend=0.0)
    sessions = s.get("sessions") or {}
    # A session seen for the first time spent its money before we watched:
    # when within the window is unknown, so it counts from here on.
    delta = cost - sessions.get(sid, cost)
    if delta > 0:
        s["spend"] = s.get("spend", 0.0) + delta
    sessions[sid] = cost
    # Sessions gone for a day are not coming back.
    stamp = time.time()
    seen = s.get("seen") or {}
    seen[sid] = stamp
    for old in [k for k, t in seen.items() if stamp - t > 86400]:
        seen.pop(old, None)
        sessions.pop(old, None)
    s.update(sessions=sessions, seen=seen)
    moved = pct - s.get("start_pct", pct)
    if s["spend"] >= RATE_MIN_SPEND and moved >= RATE_MIN_PCT:
        rate = s["rate"] = moved / s["spend"]
    tmp = "%s.%d" % (SPEND_FILE, os.getpid())
    try:
        with open(tmp, "w") as f:
            json.dump(s, f)
        os.replace(tmp, SPEND_FILE)
    except OSError:
        pass
    return rate


def cache_piece(d, rate):
    """`37m` until the cache expires, or what it costs to rebuild once it has.

    The rebuild is told as a share of the five-hour limit (`~4%`) once a rate
    is known, else in dollars. None when there is nothing to say.
    """
    last = last_request(d.get("transcript_path"))
    if not last:
        return None
    when, usage, ttl = last
    left = when + ttl - time.time()
    if left > 0:
        mins = int((left + 59) // 60)
        return paint("%dm" % mins, WARN if left < 120 else GREY)
    cost = rewrite_cost(dig(d, "model", "id"), prefix_tokens(usage), ttl)
    if cost is None:
        return paint("off", HOT)
    if rate:
        return paint("off ~%.0f%%" % max(1, round(cost * rate)), HOT)
    return paint("off ~$%.2f" % cost, HOT)


def home_path(p):
    home = os.path.expanduser("~")
    if p == home:
        return "~"
    if p.startswith(home + os.sep):
        return "~" + p[len(home):]
    return p


def git_branch(cwd, session_id):
    """Current branch, cached 5s per session — this runs on every message."""
    cache = "/tmp/claude-statusline-branch-%s" % (session_id or "nosession")
    try:
        if time.time() - os.path.getmtime(cache) < 5:
            with open(cache) as f:
                return f.read().strip() or None
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd or None, capture_output=True, text=True, timeout=2,
        )
        branch = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        branch = ""
    try:
        with open(cache, "w") as f:
            f.write(branch)
    except OSError:
        pass
    return branch or None


# A session sclaude started: `claude -n <number>-<kind>(<round>)/<slug>`, e.g.
# `1-plan 📝/12-login` or `4-review(2) 🔍/12-login` (session_label in
# sclaude/lib/steps.sh, the emoji from named_with_icon in sclaude/lib/pane.sh,
# for the tab title). The label says which job this session has; the emoji
# and the slug are left out, the slug being the worktree's, which the folder
# or branch shows already.
SCLAUDE_NAME = re.compile(r"^(\d+-[a-z][a-z-]*(?:\(\d+\))?)(?: \S+)?/[^/]+$")


def sclaude_label(d):
    """`4-review(2)` for a session sclaude named, else None."""
    m = SCLAUDE_NAME.match(d.get("session_name") or "")
    return m.group(1) if m else None


def dig(d, *path):
    """Walk nested dicts, returning None the moment anything is missing."""
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


# The shortest a session name is cut to before the ladder gives up a field
# instead. Below this the name stops saying which session it is.
NAME_MIN = 12


def feature_pr(d):
    """`#812`: the pull request of the sclaude feature this worktree holds.

    Read on every refresh from the feature's state, which sclaude rewrites when
    the pull request changes, so a new one shows up by itself. One small read
    of a file in the worktree root; nothing at all outside sclaude.
    """
    root = dig(d, "workspace", "project_dir") or dig(d, "workspace", "current_dir") \
        or d.get("cwd")
    if not root:
        return None
    try:
        with open(os.path.join(root, ".sclaude/local/feature/state.json")) as f:
            pr = json.load(f).get("pr")
    except (OSError, ValueError, AttributeError):
        return None
    return "#%s" % pr if isinstance(pr, (int, str)) and str(pr).isdigit() else None


def session_name(d):
    """The name for the middle zone; a sclaude session has its own at the left."""
    if sclaude_label(d):
        return None
    name = d.get("session_name")
    if not name:
        sid = d.get("session_id")
        name = sid[:8] if sid else None
    return name


def clip(text, width):
    """Cut text to `width` columns, ending in an ellipsis when it was cut."""
    if width is None or vislen(text) <= width:
        return text
    out = ""
    for ch in text:
        if vislen(out + ch) > width - 1:
            break
        out += ch
    return out.rstrip() + "…"


def folder_matches_branch(cwd, branch):
    """True when the folder is the branch's worktree: `<repo>-<rest>` for `<prefix>/<rest>`.

    An exact match of folder name and branch counts too.
    """
    if not cwd or not branch:
        return False
    folder = os.path.basename(cwd.rstrip(os.sep))
    if folder == branch:
        return True
    rest = branch.split("/", 1)[1] if "/" in branch else ""
    return bool(rest) and folder.endswith("-" + rest) and len(folder) > len(rest) + 1


def build(d, opts):
    """Assemble the three zones under one set of degradation flags."""
    icons = opts["icons"]
    bw = opts["barw"]

    def ico(sym):
        return sym + " " if icons else ""

    # --- left: the sclaude session, then the path ---
    cwd = dig(d, "workspace", "current_dir") or d.get("cwd") or os.getcwd()
    branch = git_branch(cwd, d.get("session_id"))
    # A worktree folder named after its branch says the same thing twice; one
    # merged segment replaces both the path and the branch.
    merged = folder_matches_branch(cwd, branch)
    if merged:
        left = paint(ico("📁⎇") + branch, GREEN)
    else:
        left = paint(ico("📁") + home_path(cwd), BLUE)
    # Which session of the feature cycle this is. First thing on the line
    # because it is what says which job this session has.
    label = sclaude_label(d)
    if label:
        left = paint(label, YELLOW) + " " * opts.get("lgap", 1) + left

    # --- middle: branch, pull request, session, worktree ---
    mid = []
    if branch and not merged:
        mid.append(paint(ico("⎇") + branch, GREEN))
    pr = feature_pr(d)
    if pr:
        mid.append(paint("PR " + pr, ORANGE))
    if opts["session"]:
        name = session_name(d)
        if name:
            mid.append(paint(clip(name, opts.get("name_max")), GREY))
    if opts["worktree"]:
        wt = dig(d, "worktree", "name") or dig(d, "workspace", "git_worktree")
        if wt:
            mid.append(paint("wt:" + wt, GREY))
    middle = paint(" · ", DIM).join(mid)

    # --- right: model, effort, context, limits ---
    right = []
    model = dig(d, "model", "display_name")
    if model:
        right.append(paint(ico("🤖") + model, PURPLE))
    effort = dig(d, "effort", "level")
    if effort:
        right.append(paint(ico("⚡") + effort, ORANGE))

    used = dig(d, "context_window", "used_percentage")
    if isinstance(used, (int, float)):
        used = int(round(used))
        shown = paint("%d%%" % used, fill_colour(used))
        if opts["bars"]:
            shown = "%s %s" % (bar(used, bw), shown)
        right.append(ico("⬢") + shown)

    # Worked out once in main(): it reads the transcript.
    if opts.get("cache"):
        right.append(ico("💾") + opts["cache"])

    five =dig(d, "rate_limits", "five_hour")
    if opts["limit"] and isinstance(five, dict):
        piece = []
        when = fmt_reset(five.get("resets_at"))
        if when:
            piece.append(paint(ico("⏳") + when, GREY))
        pct = five.get("used_percentage")
        if isinstance(pct, (int, float)):
            pct = int(round(pct))
            shown = paint("%d%%" % pct, fill_colour(pct))
            if opts["bars"]:
                shown = "%s %s" % (bar(pct, bw), shown)
            # Without the countdown ahead of it the bar needs its own label.
            piece.append(shown if when else ico("⏳") + shown)
        if piece:
            right.append(" ".join(piece))

    if opts["week"]:
        pct = dig(d, "rate_limits", "seven_day", "used_percentage")
        if isinstance(pct, (int, float)):
            pct = int(round(pct))
            right.append("%s%s" % (ico("📅"), paint("%d%%" % pct, fill_colour(pct))))

    return left, middle, (" " * opts.get("gap", 2)).join(right)


def fits(left, middle, right):
    """Columns the three zones need, clearances and the margin included."""
    gaps = 4 if middle else 2
    return vislen(left) + vislen(middle) + vislen(right) + gaps + RIGHT_MARGIN


def layout(left, middle, right, cols):
    """Left and middle packed at the left, right near the edge but not on it.

    The right zone stops RIGHT_MARGIN columns short. COLUMNS is the terminal's
    width, not the width this line is given: the panel keeps a margin of its
    own and clips whatever is written into it, so a zone padded flush to the
    edge loses its last characters — the weekly figure first. Measured at
    COLUMNS=156, the line survived to 151.

    Holding the margin here rather than shrinking `cols` keeps the ladder
    honest: it still measures against the real width, so it does not drop a
    field believing the line is fuller than it is.
    """
    lw, mw, rw = vislen(left), vislen(middle), vislen(right)
    # Every zone needs at least two spaces of clearance from its neighbour.
    if fits(left, middle, right) > cols:
        return None
    edge = cols - RIGHT_MARGIN
    if not right:
        return left if not middle else left + "  " + middle
    if not middle:
        return left + " " * (edge - lw - rw) + right
    # Middle follows the path directly; the slack all goes before the right zone.
    return left + "  " + middle + " " * (edge - lw - 2 - mw - rw) + right


# Wider gaps between the fields, tried in order once the ladder has settled on
# what to show: on a wide terminal the slack would otherwise all sit in the
# middle, with the fields huddled at both ends. Spacing never costs a field.
SPACING = [dict(gap=4, lgap=3), dict(gap=3, lgap=2)]


def spaced(d, opts, cols):
    """The chosen variant with the widest gaps that still fit, else None."""
    for extra in SPACING:
        try:
            line = layout(*build(d, dict(opts, **extra)), cols)
        except Exception:
            return None
        if line is not None:
            return line
    return None


# Where the context in use is left for sclaude, per session. Only Claude Code
# knows the window's size, and it tells the status line alone; the transcript
# has the tokens but not what they are a share of. sclaude reads this file when
# a review session ends (review_context in sclaude/lib/run.sh), to decide
# whether the next round stays in the same conversation and to log the figure.
CONTEXT_FILE = "/tmp/claude-statusline-context-%s"


def remember_context(d):
    sid = d.get("session_id")
    used = dig(d, "context_window", "used_percentage")
    if not sid or not isinstance(used, (int, float)):
        return
    size = dig(d, "context_window", "context_window_size")
    # What the session has cost so far, for sclaude's review report (run_cost
    # in sclaude/lib/steps.sh).
    cost = dig(d, "cost", "total_cost_usd")
    try:
        with open(CONTEXT_FILE % sid, "w") as f:
            json.dump({"used_percentage": used,
                       "context_window_size": size if isinstance(size, int) else None,
                       "cost_usd": cost if isinstance(cost, (int, float)) else None}, f)
    except OSError:
        pass


def main():
    try:
        d = json.load(sys.stdin)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}
    remember_context(d)
    try:
        cache = cache_piece(d, remember_spend(d))
    except Exception:
        cache = None

    try:
        cols = int(os.environ.get("COLUMNS") or 80)
    except ValueError:
        cols = 80
    cols = max(20, cols)

    # Degradation ladder: first variant that fits wins.
    ladder = [
        dict(cache=True,  week=True,  worktree=True,  session=True,  barw=10, icons=True, bars=True, limit=True),
        # The weekly limit outranks the worktree, wide bars and the session
        # name: they go first, and the name is cut before it is dropped.
        dict(cache=True,  week=True,  worktree=False, session=True,  barw=8,  icons=True, bars=True, limit=True),
        dict(cache=True,  week=True,  worktree=False, session=True,  barw=5,  icons=True, bars=True, limit=True),
        dict(cache=True,  week=True,  worktree=False, session=False, barw=5,  icons=True, bars=True, limit=True),
        dict(cache=True,  week=False, worktree=False, session=False, barw=5,  icons=True, bars=True, limit=True),
        dict(cache=True,  week=False, worktree=False, session=False, barw=4,  icons=False, bars=True, limit=True),
        dict(cache=True,  week=False, worktree=False, session=False, barw=3,  icons=False, bars=True, limit=True),
        # Below here the bars themselves go; percentages carry the meaning.
        dict(cache=True,  week=False, worktree=False, session=False, barw=0,  icons=False, bars=False, limit=True),
        dict(cache=False, week=False, worktree=False, session=False, barw=0,  icons=False, bars=False, limit=False),
    ]
    # The cache countdown is short and says when the next message gets
    # expensive: it stays until only the bare fields are left.
    for opts in ladder:
        opts["cache"] = cache if opts["cache"] else None

    for opts in ladder:
        try:
            left, middle, right = build(d, opts)
        except Exception:
            break
        line = layout(left, middle, right, cols)
        if line is None and opts["session"]:
            # A long session name is cheaper to cut than any field after it:
            # shorten it by the overflow before the ladder drops the weekly
            # limit to make room.
            name = session_name(d)
            if name:
                room = vislen(name) - (fits(left, middle, right) - cols)
                if room >= NAME_MIN:
                    try:
                        left, middle, right = build(d, dict(opts, name_max=room))
                    except Exception:
                        break
                    line = layout(left, middle, right, cols)
        if line is not None:
            sys.stdout.write(spaced(d, opts, cols) or line)
            return

    # Nothing fit, or something went wrong: fall back to the bare path, keeping
    # the sclaude session ahead of it — on a narrow terminal which job this
    # session has is worth more than the path it runs in.
    try:
        cwd = dig(d, "workspace", "current_dir") or d.get("cwd") or os.getcwd()
        line = paint(home_path(cwd), BLUE)
        label = sclaude_label(d)
        if label and vislen(label) + 1 + vislen(line) <= cols:
            line = paint(label, YELLOW) + " " + line
        sys.stdout.write(line)
    except Exception:
        sys.stdout.write("")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
