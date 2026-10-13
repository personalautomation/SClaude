#!/usr/bin/env python3
"""Custom statusline for Claude Code.

Reads the statusLine JSON on stdin, prints one line laid out in three zones:
left (the sclaude step, then the path), middle (git branch, session, worktree),
right (model, effort, context, rate limits). Never raises: any surprise falls
back to a bare path.

Symlinked to ~/.claude/statusline.py by this repository's install.sh — that is
the path settings.json names, so the symlink is what keeps the setting working.
"""
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


# The four steps of the sclaude feature cycle, in order. The label is what the
# statusline shows; the key is what .sclaude/local/feature/state.json holds.
SCLAUDE_STEPS = ["plan", "code", "pr", "review"]


def feature_step(cwd):
    """`2-code` for a worktree under sclaude, else None.

    Cheap enough to run per message: one stat and, at most, one small read of a
    file that sits in the worktree root.
    """
    if not cwd:
        return None
    try:
        with open(os.path.join(cwd, ".sclaude/local/feature", "state.json")) as f:
            step = json.load(f).get("step")
    except (OSError, ValueError, AttributeError):
        return None
    if step == "done":
        # Every step passed; what is left — merge, promote, deploy — is his.
        return "%d/%d done" % (len(SCLAUDE_STEPS), len(SCLAUDE_STEPS))
    try:
        return "%d-%s" % (SCLAUDE_STEPS.index(step) + 1, step)
    except ValueError:
        return None


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


def session_name(d):
    name = d.get("session_name")
    if not name:
        sid = d.get("session_id")
        name = sid[:8] if sid else None
    name = drop_shown_slug(d, name) or None
    # The step at the left of the line may already say exactly this.
    cwd = dig(d, "workspace", "current_dir") or d.get("cwd") or os.getcwd()
    if name and name == feature_step(cwd):
        return None
    return name


def drop_shown_slug(d, name):
    """`1-plan/<slug>` as `1-plan` when the slug is on the line already.

    sclaude names a session `<kind>/<slug>`, and its worktree and branch carry
    the same slug: the folder ends in `-<slug>`, the branch in `/<slug>`.
    """
    if not name or "/" not in name:
        return name
    head, slug = name.rsplit("/", 1)
    if not head or not slug:
        return name
    cwd = dig(d, "workspace", "current_dir") or d.get("cwd") or os.getcwd()
    folder = os.path.basename(cwd.rstrip(os.sep))
    branch = git_branch(cwd, d.get("session_id")) or ""
    if folder == slug or folder.endswith("-" + slug) \
            or branch == slug or branch.endswith("/" + slug):
        return head
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

    # --- left: the sclaude step, then the path ---
    cwd = dig(d, "workspace", "current_dir") or d.get("cwd") or os.getcwd()
    branch = git_branch(cwd, d.get("session_id"))
    # A worktree folder named after its branch says the same thing twice; one
    # merged segment replaces both the path and the branch.
    merged = folder_matches_branch(cwd, branch)
    if merged:
        left = paint(ico("📁⎇") + branch, GREEN)
    else:
        left = paint(ico("📁") + home_path(cwd), BLUE)
    # Which step of the feature cycle this worktree is on. First thing on the
    # line because it is what says which of four jobs this session has.
    step = feature_step(cwd)
    if step:
        left = paint(step, YELLOW) + " " + left

    # --- middle: branch, session, worktree ---
    mid = []
    if branch and not merged:
        mid.append(paint(ico("⎇") + branch, GREEN))
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

    five = dig(d, "rate_limits", "five_hour")
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

    return left, middle, "  ".join(right)


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


def main():
    try:
        d = json.load(sys.stdin)
        if not isinstance(d, dict):
            d = {}
    except Exception:
        d = {}

    try:
        cols = int(os.environ.get("COLUMNS") or 80)
    except ValueError:
        cols = 80
    cols = max(20, cols)

    # Degradation ladder: first variant that fits wins.
    ladder = [
        dict(week=True,  worktree=True,  session=True,  barw=10, icons=True, bars=True, limit=True),
        # The weekly limit outranks the worktree, wide bars and the session
        # name: they go first, and the name is cut before it is dropped.
        dict(week=True,  worktree=False, session=True,  barw=8,  icons=True, bars=True, limit=True),
        dict(week=True,  worktree=False, session=True,  barw=5,  icons=True, bars=True, limit=True),
        dict(week=True,  worktree=False, session=False, barw=5,  icons=True, bars=True, limit=True),
        dict(week=False, worktree=False, session=False, barw=5,  icons=True, bars=True, limit=True),
        dict(week=False, worktree=False, session=False, barw=4,  icons=False, bars=True, limit=True),
        dict(week=False, worktree=False, session=False, barw=3,  icons=False, bars=True, limit=True),
        # Below here the bars themselves go; percentages carry the meaning.
        dict(week=False, worktree=False, session=False, barw=0,  icons=False, bars=False, limit=True),
        dict(week=False, worktree=False, session=False, barw=0,  icons=False, bars=False, limit=False),
    ]

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
            sys.stdout.write(line)
            return

    # Nothing fit, or something went wrong: fall back to the bare path, keeping
    # the step ahead of it — on a narrow terminal which of four jobs this
    # session has is worth more than the path it runs in.
    try:
        cwd = dig(d, "workspace", "current_dir") or d.get("cwd") or os.getcwd()
        line = paint(home_path(cwd), BLUE)
        step = feature_step(cwd)
        if step and vislen(step) + 1 + vislen(line) <= cols:
            line = paint(step, YELLOW) + " " + line
        sys.stdout.write(line)
    except Exception:
        sys.stdout.write("")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
