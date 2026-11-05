# The DORA page's small drawings: tiles, columns and stacked bars.
#
# Part of sclaude/lib/dora.py.

import html

import metrics_guide  # noqa: E402

import dora_numbers


# --- the page -----------------------------------------------------------------

def span(seconds):
    if seconds is None:
        return "—"
    if seconds < 3600:
        return "%d min" % max(1, round(seconds / 60))
    if seconds < 2 * dora_numbers.DAY:
        return "%.1f h" % (seconds / 3600)
    return "%.1f days" % (seconds / dora_numbers.DAY)


def esc(value):
    return html.escape(str(value), quote=True)


def stamp(at):
    return at.astimezone().strftime("%Y-%m-%d %H:%M") if at else "—"


STATUS_WORD = {"good": "Good", "watch": "Watch", "poor": "Poor"}
STATUS_ICON = {"good": "▲", "watch": "■", "poor": "▼"}
LEVEL_STATUS = {"Elite": "good", "High": "good", "Medium": "watch", "Low": "poor"}


SCALES = ("Scales with the feature's size. Per complexity divides it by the feature's "
          "size in standard features — its acceptance criteria, or its lines where it has "
          "none; 1 is the median finished feature.")


def tile(label, value, sub, lvl, delta, raw=None, mode="", scales=False):
    """One figure: its value, what it is, its colour — DORA's level where it
    has one, the guide's bands otherwise — and, on hover, why it matters,
    what to aim for and how it is counted (metrics_guide.py)."""
    status = LEVEL_STATUS.get(lvl) if lvl else metrics_guide.judge(label, raw)
    badge = ""
    if status:
        badge = "<span class='lvl %s'><i>%s</i>%s</span>" % (
            status, STATUS_ICON[status], lvl or STATUS_WORD[status])
    note = ""
    entry = metrics_guide.lookup(label)
    if entry:
        # Not shown in the tile: the page's script shows it on hover over the
        # tile, and on a tap where there is no hover.
        note = ("<div class=note hidden>"
                "<p><b>Why</b> %s</p><p><b>Aim</b> %s</p><p><b>How</b> %s</p>%s</div>"
                % (esc(entry[0]), esc(entry[1]), esc(entry[2]),
                   "<p><b>◆</b> %s</p>" % esc(SCALES) if scales else ""))
    mark = " <span class=scales title='%s'>◆</span>" % esc(SCALES) if scales else ""
    return ("<div class='tile%s%s'><div class=label>%s%s</div><div class=value>%s</div>"
            "<div class=sub>%s</div><div class=foot>%s<span class=delta>%s</span></div>%s</div>"
            % (" " + status if status else "", " " + mode if mode else "", esc(label), mark,
               esc(value), esc(sub), badge, esc(delta), note))


def delta_text(cur, prev, fmt):
    if cur is None or prev is None:
        return "no earlier 30 days to compare" if prev is None else ""
    if abs(cur - prev) < 1e-9:
        return "same as the 30 days before"
    word = "down" if cur < prev else "up"
    return "%s from %s the 30 days before" % (word, fmt(prev))


def short_span(seconds):
    """A duration for an axis tick, where there is room for four characters."""
    if seconds < 3600:
        return "%dm" % round(seconds / 60)
    if seconds < 2 * dora_numbers.DAY:
        return "%dh" % round(seconds / 3600)
    return "%dd" % round(seconds / dora_numbers.DAY)


def columns(weeks, pick, fmt, title):
    """Weekly columns as inline SVG, one series: the title names it."""
    # Drawn about as wide as it is shown, half a page, so its text keeps the
    # page's size rather than shrinking with the drawing.
    w, h, left, bottom, top = 440, 200, 44, 24, 16
    vals = [pick(wk) for wk in weeks]
    peak = max([v for v in vals if v is not None] or [0]) or 1
    step = nice_step(peak, fmt is span)
    peak = step * max(1, -(-peak // step))
    # Durations get a short tick; the bars' own labels keep the long form.
    tick_text = short_span if fmt is span else fmt
    band = (w - left - 8) / len(weeks)
    bar = min(24, band * 0.6)
    plot_h = h - bottom - top
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>" % (w, h, esc(title))]
    tick = 0
    while tick <= peak + 1e-9:
        y = top + plot_h - plot_h * tick / peak
        parts.append("<line class=grid x1=%d x2=%d y1=%.1f y2=%.1f />" % (left, w - 8, y, y))
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>"
                     % (left - 6, y + 4, esc(tick_text(tick) if tick else "0")))
        tick += step
    biggest = max(range(len(vals)), key=lambda i: vals[i] or 0)
    for i, (wk, v) in enumerate(zip(weeks, vals)):
        x = left + band * i + (band - bar) / 2
        label = wk[0].strftime("%d %b")
        if len(weeks) <= 6 or (len(weeks) - 1 - i) % 2 == 0:
            parts.append("<text class=tick x=%.1f y=%d text-anchor=middle>%s</text>"
                         % (x + bar / 2, h - 6, esc(label)))
        tip = "Week of %s · %s" % (label, fmt(v) if v is not None else "nothing shipped")
        parts.append("<rect class=hit x=%.1f y=%d width=%.1f height=%d data-tip='%s' tabindex=0 />"
                     % (left + band * i, top, band, plot_h, esc(tip)))
        if not v:
            continue
        bh = max(2, plot_h * v / peak)
        y = top + plot_h - bh
        r = min(4, bh / 2)
        parts.append("<path class=bar d='M%.1f %.1f v%.1f h%.1f v-%.1f a%.1f %.1f 0 0 0 -%.1f -%.1f "
                     "h-%.1f a%.1f %.1f 0 0 0 -%.1f %.1f z' />"
                     % (x, y + r, bh - r, bar, bh - r, r, r, r, r, bar - 2 * r, r, r, r, r))
        if i == biggest or i == len(weeks) - 1:
            parts.append("<text class=val x=%.1f y=%.1f text-anchor=middle>%s</text>"
                         % (x + bar / 2, y - 5, esc(fmt(v))))
    parts.append("<line class=axis x1=%d x2=%d y1=%d y2=%d /></svg>"
                 % (left, w - 8, top + plot_h, top + plot_h))
    return "".join(parts)


def nice_step(peak, duration=False):
    """A round tick step that splits `peak` into about four."""
    raw = peak / 4
    if raw <= 0:
        return 1
    if duration and peak > 3600:
        # Durations: hours, half-days, days, weeks.
        for s in (3600, 2 * 3600, 6 * 3600, 12 * 3600, dora_numbers.DAY, 2 * dora_numbers.DAY, 7 * dora_numbers.DAY, 14 * dora_numbers.DAY, 30 * dora_numbers.DAY):
            if raw <= s:
                return s
        return 30 * dora_numbers.DAY
    if raw < 1:
        # A share or a small rate: tenths, quarters, halves.
        for m in (0.05, 0.1, 0.25, 0.5, 1):
            if raw <= m:
                return m
    mag = 10 ** len(str(int(raw))) / 10
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return max(1, int(m * mag))
    return max(1, int(raw))


def stacked(features):
    """One horizontal bar per finished feature, cut by where its time went."""
    if not features:
        return "<p class=empty>No finished feature of this product in sclaude's records yet.</p>"
    return stacked_rows([(name, part) for name, part, _ in reversed(features)],
                        dora_numbers.PARTS, dora_numbers.PART_NAMES, span, "Cycle time by step")


def stacked_rows(rows, keys, names, fmt, label):
    """One horizontal bar per (name, {key: value}) row, cut by `keys` in the
    categorical order, its total at the end."""
    if not rows:
        return "<p class=empty>Nothing recorded yet.</p>"
    w, left, right, rh = 900, 190, 80, 28
    h = len(rows) * rh + 8
    peak = max(sum(p.get(k) or 0 for k in keys) for _, p in rows) or 1
    plot = w - left - right
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>" % (w, h, esc(label))]
    for i, (name, part) in enumerate(rows):
        y = 4 + i * rh
        text = name if len(name) <= 24 else name[:23] + "…"
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>"
                     % (left - 8, y + 16, esc(text)))
        x = left
        for k, key in enumerate(keys):
            value = part.get(key) or 0
            if value <= 0:
                continue
            bw = plot * value / peak
            gap = 2 if bw > 3 else 0
            parts.append("<rect class='seg s%d' x=%.1f y=%d width=%.1f height=18 rx=%s "
                         "data-tip='%s' tabindex=0 />"
                         % (k + 1, x, y + 4, max(1, bw - gap), "2" if bw > 6 else "0",
                            esc("%s · %s: %s" % (name, names[key], fmt(value)))))
            x += bw
        parts.append("<text class=val x=%.1f y=%.1f>%s</text>"
                     % (x + 6, y + 17, esc(fmt(sum(part.get(k) or 0 for k in keys)))))
    parts.append("</svg>")
    legend = "".join("<span><i class='key s%d'></i>%s</span>" % (k + 1, esc(names[key]))
                     for k, key in enumerate(keys))
    return "<div class=legend>%s</div>%s" % (legend, "".join(parts))


STEP_NAMES = {"plan": "Plan", "code": "Code", "pr": "Pull request", "review": "Review",
              "fix": "Regression fixes", "friction": "Friction reviews", "epilogue": "Epilogue",
              "retro": "Retrospective", "sync": "Sync with main", "status": "Status",
              "deferred": "Deferred review", "regression": "Regression", "manual": "By hand",
              "workshop": "sclaude workshop", "other": "Other"}
VERDICT_NAMES = {"deliberate": "every ban deliberate", "lifted": "a ban lifted",
                 "deferred": "put off", "mixed": "mixed", "unsaid": "no verdict"}
DENIAL_NAMES = {"permission-rule": "a permission rule", "user-rejected": "the person",
                "automode-blocked": "auto mode's check", "automode-unavailable": "auto mode unavailable"}


def compact(n):
    """1,284 · 12.9K · 4.2M · 2.7B."""
    if n is None:
        return "—"
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= size * 10 or (abs(n) >= size and unit != "K"):
            return "%.1f%s" % (n / size, unit)
    return "{:,}".format(int(round(n)))


def money(x):
    if x is None:
        return "—"
    return "${:,.0f}".format(x) if x >= 100 else "${:,.2f}".format(x)


def share(x):
    return "—" if x is None else "%d%%" % round(x * 100)


def hbars(items, fmt, label="", width=440):
    """One horizontal bar per item, a single series: the card's title names
    it. `items` is [(name, value)]."""
    items = [(n, v) for n, v in items if v is not None]
    if not items:
        return "<p class=empty>Nothing recorded yet.</p>"
    left, right, rh = 150, 70, 26
    peak = max(v for _, v in items) or 1
    plot = width - left - right
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>"
             % (width, len(items) * rh + 4, esc(label))]
    for i, (name, value) in enumerate(items):
        y = 2 + i * rh
        text = name if len(name) <= 24 else name[:23] + "…"
        bw = max(2, plot * value / peak) if value else 0
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>"
                     % (left - 8, y + 15, esc(text)))
        if bw:
            parts.append("<rect class=bar x=%d y=%d width=%.1f height=14 rx=%s data-tip='%s' tabindex=0 />"
                         % (left, y + 4, bw, "3" if bw > 6 else "0", esc("%s · %s" % (name, fmt(value)))))
        parts.append("<text class=val x=%.1f y=%.1f>%s</text>" % (left + bw + 6, y + 15, esc(fmt(value))))
    parts.append("</svg>")
    return "".join(parts)


# What engineering scorecards usually ask for and this page cannot say, and
# why — so that a missing figure reads as a decision rather than an oversight.
NOT_MEASURED = (
    "Sprint velocity, predictability, capacity accuracy: no story points or sprints.",
    "Code reliability, maintainability, security, duplication, complexity: needs a "
    "static analyser's report.",
    "Code coverage: needs the test runner's coverage report.",
    "Technical debt in hours, estimation of issues: nothing is estimated.",
    "Uptime and MTTR of incidents outside a deploy: needs monitoring.",
    "Support, onboarding, SLA and compliance metrics: outside the development cycle.",
    "QA hand-backs: not yet recorded past the feature's life.",
)


def heatmap(grid):
    """Weekday × hour counts as a grid of one hue, deeper for more."""
    peak = max(max(row) for row in grid) or 1
    left, top, cw, ch = 40, 16, 35, 18
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='Sessions by weekday and hour'>"
             % (left + 24 * cw + 4, top + 7 * ch + 4)]
    for h in range(0, 24, 3):
        parts.append("<text class=tick x=%.1f y=11 text-anchor=middle>%02d</text>" % (left + h * cw + cw / 2, h))
    for d, row in enumerate(grid):
        y = top + d * ch
        parts.append("<text class=tick x=%d y=%.1f text-anchor=end>%s</text>" % (left - 6, y + 13, days[d]))
        for h, n in enumerate(row):
            level = 0 if not n else 0.2 + 0.8 * n / peak
            parts.append("<rect x=%d y=%d width=%d height=%d rx=2 class='%s' style='opacity:%.2f' "
                         "data-tip='%s' tabindex=0 />"
                         % (left + h * cw + 1, y + 1, cw - 2, ch - 2, "bar" if n else "cell",
                            level or 1, esc("%s %02d:00 · %d sessions" % (days[d], h, n))))
    parts.append("</svg>")
    return "".join(parts)


def radar(axes, label):
    """The health radar: one spoke per axis, its score 0–100 out from the
    centre, the polygon the shape of the whole. `axes` is [(name, score or
    None, [(metric, score), …])]; an axis with nothing to stand on sits at the
    centre, named as such."""
    import math
    w, h, cx, cy, r = 660, 470, 330, 235, 165
    n = len(axes)

    def point(i, value, turn=0.0):
        angle = -math.pi / 2 + 2 * math.pi * (i + turn) / n
        return cx + r * value / 100 * math.cos(angle), cy + r * value / 100 * math.sin(angle)
    parts = ["<svg viewBox='0 0 %d %d' role=img aria-label='%s'>" % (w, h, esc(label))]
    for ring in (25, 50, 75, 100):
        pts = " ".join("%.1f,%.1f" % point(i, ring) for i in range(n))
        parts.append("<polygon class=grid points='%s' fill=none />" % pts)
        # The ring's value between the first two spokes, clear of both.
        x, y = point(0, ring, 0.5)
        parts.append("<text class=tick x=%.1f y=%.1f text-anchor=middle>%d</text>" % (x, y + 3, ring))
    for i in range(n):
        x, y = point(i, 100)
        parts.append("<line class=grid x1=%d y1=%d x2=%.1f y2=%.1f />" % (cx, cy, x, y))
    shape = " ".join("%.1f,%.1f" % point(i, a[1] or 0) for i, a in enumerate(axes))
    parts.append("<polygon class=area points='%s' />" % shape)
    for i, (name, value, metrics) in enumerate(axes):
        x, y = point(i, value or 0)
        tip = "%s · %s — %s" % (name, "no data" if value is None else "%d of 100" % round(value),
                                "; ".join("%s %d" % (m, round(v)) for m, v in metrics) or "nothing measured")
        parts.append("<circle class=dot cx=%.1f cy=%.1f r=5 data-tip='%s' tabindex=0 />" % (x, y, esc(tip)))
        lx, ly = point(i, 118)
        anchor = "middle" if abs(lx - cx) < 20 else ("start" if lx > cx else "end")
        parts.append("<text class=axis-name x=%.1f y=%.1f text-anchor=%s>%s</text>"
                     % (lx, ly + 4, anchor, esc(name)))
        parts.append("<text class=tick x=%.1f y=%.1f text-anchor=%s>%s</text>"
                     % (lx, ly + 18, anchor, "no data" if value is None else "%d" % round(value)))
    parts.append("</svg>")
    return "".join(parts)


def health_of(axes):
    """The index — the mean of the axes — and the imbalance between the best
    and the worst, over the axes that have a score."""
    scored = [(n, v) for n, v, _ in axes if v is not None]
    if not scored:
        return None, None, None, None
    best = max(scored, key=lambda a: a[1])
    worst = min(scored, key=lambda a: a[1])
    return sum(v for _, v in scored) / len(scored), best[1] - worst[1], best, worst


def axis(name, metrics, mode):
    """One axis from [(label, absolute raw, per-complexity raw)]: the mean of
    its metrics' scores in the mode."""
    scored = []
    for label, raw_abs, raw_norm in metrics:
        raw = raw_norm if mode == "norm" else raw_abs
        value = metrics_guide.score(label, raw)
        if value is not None:
            scored.append((label, value))
    return (name, sum(v for _, v in scored) / len(scored) if scored else None, scored)
