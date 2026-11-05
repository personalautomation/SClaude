# Drawing a map: the layout, the SVG and its style.
#
# Part of sclaude/lib/flow/process.py, which re-exports it.

import html

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # noqa: E402,F401 — every folder of sclaude/lib on the path
import process_position


# --- drawing -----------------------------------------------------------------

LANE_W = 246
NODE_W = 198
NODE_H = 78
# The strip under a block the feature's page writes in: its metrics, the
# player's count (drawMetrics, the player's tag).
UNDER = 16
TOP = 52
CHANNEL = 10


def wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    return lines


def esc(text):
    return html.escape(text, quote=True)


class Diagram:
    def __init__(self, name, lanes, nodes, edges):
        self.name, self.lanes, self.nodes, self.edges = name, lanes, nodes, edges
        self.rows = max(n[1] for n in nodes.values()) + 1
        self.lane_x = {lane: 0 for lane, _ in lanes}
        # Edges running down past a node in their way take a channel on the
        # left (or the right, below), as edges running back take one on the
        # right — one for each block they go into (_route: the trunks).
        self.detours = [e for e in edges if not self.is_back(e) and self.blocked(e)]
        # One between two lanes right of the middle goes round on the right,
        # its runs the shorter, inside the ways back there.
        order = {lane: i for i, (lane, _) in enumerate(lanes)}
        self.east = [e for e in self.detours
                     if min(order[nodes[e[0]][0]], order[nodes[e[1]][0]]) > (len(lanes) - 1) / 2]
        west = {e[1] for e in self.detours if e not in self.east}
        # A channel per block the detours go into (body: the trunks).
        self.left = CHANNEL * (len(west) + 1) if west else 0
        self.lane_x = {lane: self.left + i * LANE_W for i, (lane, _) in enumerate(lanes)}
        # A channel per block the ways back go into (body: the trunks).
        backs = {e[1] for e in edges if self.is_back(e)} | {("east", e[1]) for e in self.east}
        self.right = self.left + len(lanes) * LANE_W
        self.width = self.right + CHANNEL * (len(backs) + 1) + 8
        # The ways routed first — across the map, and how far under or over a
        # block each turns — then each gap as tall as what turns in it
        # (_rows), and the turns put where the rows came out (_place).
        self.top = [0] * self.rows
        self._route()
        self._rows()
        self._place()

    def center(self, nid):
        lane, row = self.nodes[nid][0], self.nodes[nid][1]
        return self.lane_x[lane] + LANE_W / 2, self.top[row] + NODE_H / 2

    def is_back(self, edge):
        return self.nodes[edge[1]][1] < self.nodes[edge[0]][1]

    def blocked(self, edge):
        """Whether a node stands in an edge's way down: a way leaves its block
        right under it and goes down in the target's lane, so a node there
        between the two rows is in its way."""
        (_, ra), (lb, rb) = self.nodes[edge[0]][:2], self.nodes[edge[1]][:2]
        return any(n[0] == lb and ra < n[1] < rb for nid, n in self.nodes.items() if nid not in edge[:2])

    def shape(self, nid):
        lane, row, kind, title, text, flags = self.nodes[nid]
        cx, cy = self.center(nid)
        x, y, w, h = cx - NODE_W / 2, cy - NODE_H / 2, NODE_W, NODE_H
        out = ['<g class="node k-%s" data-node="%s" data-key="n:%s">' % (kind, nid, nid)]
        if kind in ("start", "end"):
            r = 13
            out.append('<circle class="shape" cx="%.1f" cy="%.1f" r="%d"/>' % (cx, y + r + 2, r))
            ty = y + 2 * r + 16
            out.append('<text class="t" x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (cx, ty, esc(title)))
            for i, line in enumerate(wrap(text, 30)[:2]):
                out.append('<text class="s" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                           % (cx, ty + 14 + i * 13, esc(line)))
        else:
            if kind == "gate":
                d = 14
                pts = [(x, cy), (x + d, y), (x + w - d, y), (x + w, cy), (x + w - d, y + h), (x + d, y + h)]
                out.append('<polygon class="shape" points="%s"/>' % " ".join("%.1f,%.1f" % p for p in pts))
            else:
                out.append('<rect class="shape" x="%.1f" y="%.1f" width="%d" height="%d" rx="%d"/>'
                           % (x, y, w, h, 12 if kind != "hold" else 4))
                if kind == "wait":
                    out.append('<circle class="clock" cx="%.1f" cy="%.1f" r="7"/>' % (x + 12, y + 12))
            heads = wrap(title, 22 if kind == "gate" else 28)
            lines = wrap(text, 30 if kind == "gate" else 33)
            room = (4 if kind != "gate" else 3) - (len(heads) - 1)
            shown = min(len(lines), room)
            ty = cy - (len(heads) * 14 + shown * 12) / 2 + 10
            for i, line in enumerate(heads):
                out.append('<text class="t" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                           % (cx, ty + i * 14, esc(line)))
            ty += len(heads) * 14
            for i, line in enumerate(lines[:room]):
                last = i == room - 1 and len(lines) > room
                out.append('<text class="s" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                           % (cx, ty + i * 12 - 1, esc(line + (" …" if last else ""))))
        badge = x + w - 6
        for flag in "FWRS":
            if flag in flags:
                # The ring turns while the review or the workshop is at work
                # (busy, lit by the feature's page).
                # Why the letter is on this block, shown on hover; the page
                # adds how the work is going while it is at work.
                why = process_position.badge_why(nid, flag)
                out.append('<g class="badge b-%s" data-why="%s"><title>%s</title>'
                           '<circle class="ring" cx="%.1f" cy="%.1f" r="13"/>'
                           '<circle class="dot" cx="%.1f" cy="%.1f" r="10"/>'
                           '<text x="%.1f" y="%.1f" text-anchor="middle">%s</text></g>'
                           % (flag, esc(why), esc(why), badge, y + 2, badge, y + 2, badge, y + 6.5, flag))
                badge -= 26
        out.append("</g>")
        return "\n".join(out)

    def edge(self, edge, index):
        """An arrow by the three rules (corners, levels, entries): out of a
        side's corner along its row, or from below turning on its level right
        under its block; into its target's top at its own point, a way from
        a channel turning above the target's row at its own height. A way
        round by a channel into a block others go round into too ends at
        their trunk, with a small arrow (_route: self.trunk)."""
        a, b, label, kind = edge
        ax, ay = self.center(a)
        bx, by = self.center(b)
        half = NODE_H / 2
        if self.nodes[a][1] == self.nodes[b][1]:
            side = 1 if bx > ax else -1
            dy = 9 if side > 0 else -9
            pts = [(ax + side * NODE_W / 2, ay + dy), (bx - side * NODE_W / 2, by + dy)]
            lx, ly, anchor = (ax + bx) / 2, (ay + dy - 4 if side < 0 else ay + dy + 13), "middle"
        else:
            ex, top = bx + self.entry.get(index, 0), by - half
            corner = self.corner.get(index)
            y = self.run_y(index)
            if corner:
                start = [(ax + corner * NODE_W / 2, ay)]
                lx, ly, anchor = ax + corner * (NODE_W / 2 + 6), ay - 5, "start" if corner > 0 else "end"
            else:
                start = [(ax, ay + half), (ax, y)]
                lx, ly, anchor = (ax - 6, y - 3, "end") if self.goes_left(edge) else (ax + 6, y - 3, "start")
                # A labelled way straight down has its label where this one's
                # would be: this one's goes out past the block's edge.
                if self.reach(edge) >= 1 and any(
                        e[0] == a and e[2] and e is not edge and self.reach(e) < 1 for e in self.edges):
                    lx += (-1 if anchor == "end" else 1) * NODE_W / 2
            if index in self.channel_x:
                cx, turn = self.channel_x[index], self.turn[index]
                pts = start + [(cx, y), (cx, turn), (ex, turn), (ex, top)]
            else:
                pts = start + [(ex, y), (ex, top)]
        path = "M" + " L".join("%.1f %.1f" % p for p in pts)
        # A wide transparent twin under the line: something to point at.
        out = ['<g class="edge e-%s" data-key="e:%s:%d">' % (kind or "flow", self.name, index),
               '<path class="hit" d="%s"/>' % path]
        if index in self.trunk:
            # Its own run ends at the trunk; the rest of its way, the trunk's,
            # shows only while it is lit.
            k = len(start) + 1
            out += ['<path class="line" d="M%s" marker-end="url(#join%s-%s)"/>'
                    % (" L".join("%.1f %.1f" % p for p in pts[:k]),
                       "-back" if self.is_back(edge) else "", self.name),
                    '<path class="line ride" d="M%s" marker-end="url(#arrow-%s)"/>'
                    % (" L".join("%.1f %.1f" % p for p in pts[k - 1:]), self.name)]
        else:
            out.append('<path class="line" d="%s" marker-end="url(#arrow-%s)"/>' % (path, self.name))
            # On a trunk, a chevron past each way joining it: the way on is up
            # a trunk back, down a detour's.
            cx = self.channel_x.get(index)
            up = -1 if self.is_back(edge) else 1
            for y in sorted(self.run_y(i) for i, j in self.trunk.items() if j == index):
                out.append('<path class="chev" d="M%.1f %.1f L%.1f %.1f L%.1f %.1f"/>'
                           % (cx - 3.5, y + up * 5, cx, y + up * 9, cx + 3.5, y + up * 5))
        if label:
            out.append('<text class="el" x="%.1f" y="%.1f" text-anchor="%s">%s</text>'
                       % (lx, ly, anchor, esc(label)))
        out.append("</g>")
        return "\n".join(out)

    def run_y(self, index):
        """The height a way runs across at, and meets a trunk at: its row's
        middle from a corner, its level under the block from below."""
        if index in self.corner:
            return self.center(self.edges[index][0])[1]
        return self.level[index]

    def goes_left(self, edge):
        """A detour round the left, or a way to a lane on the left; a way back
        goes right, as a detour round the right does."""
        if edge in self.east:
            return False
        return edge in self.detours or (not self.is_back(edge)
                                        and self.center(edge[1])[0] < self.center(edge[0])[0] - 1)

    def reach(self, edge):
        """How far across a way runs: a way to a channel, the farthest."""
        if self.is_back(edge) or edge in self.detours:
            return float("inf")
        return abs(self.center(edge[1])[0] - self.center(edge[0])[0])

    def corners(self):
        """Rule 1, the corners: on each side of a block, the way reaching
        farthest that side leaves from its corner and runs along the row —
        when the row is clear that far and no arrow to a block of the same
        row takes that side. {edge index: 1 right, -1 left}."""
        out, ways = {}, {}
        for i, e in enumerate(self.edges):
            ways.setdefault(e[0], []).append((i, e))
        for a, es in ways.items():
            ax, row = self.center(a)[0], self.nodes[a][1]
            for side in (1, -1):
                best, taken = None, False
                for i, e in es:
                    bx = self.center(e[1])[0]
                    if self.nodes[e[1]][1] == row:
                        taken = taken or (bx - ax) * side > 0
                        continue
                    reach = self.reach(e)
                    # A way straight down has no side to leave by.
                    if (side < 0) != self.goes_left(e) or reach < 1:
                        continue
                    if any(n[1] == row and 0 < (self.center(nid)[0] - ax) * side <= reach
                           for nid, n in self.nodes.items() if nid not in (a, e[1])):
                        continue
                    if best is None or reach > best[0]:
                        best = (reach, i)
                if best and not taken:
                    out[best[1]] = side
        return out

    def levels(self):
        """Rule 1, from below: the other ways turn right under their block,
        per side — left, or right and straight down — each on its own level,
        the farthest first, so none crosses another on its way. {index: how
        far under its block}."""
        out, sides = {}, {}
        for i, e in enumerate(self.edges):
            if i in self.corner or self.nodes[e[0]][1] == self.nodes[e[1]][1]:
                continue
            sides.setdefault((e[0], self.goes_left(e)), []).append((-self.reach(e), i))
        for (a, _left), ways in sides.items():
            # From 12 under it, so a label 3 above its line clears the block.
            step = min(12, 20 / (len(ways) - 1)) if len(ways) > 1 else 0
            for k, (_reach, i) in enumerate(sorted(ways)):
                out[i] = 12 + k * step
        # Ways from one row into one block would share their level and merge:
        # the nearer source's turns higher, so a farther one's drop does not
        # cross it.
        into = {}
        for i, e in enumerate(self.edges):
            if i in out and i not in self.channel_x:
                ax, bx = self.center(e[0])[0], self.center(e[1])[0]
                into.setdefault((e[1], self.nodes[e[0]][1]), []).append((self.reach(e), min(ax, bx), max(ax, bx), i))
        for ways in into.values():
            ways.sort()
            for k, (_reach, lo, hi, i) in enumerate(ways):
                # Moved by the nearer ways whose run shares a stretch with it.
                out[i] += 3 * sum(1 for _r, lo2, hi2, _i in ways[:k] if max(lo, lo2) < min(hi, hi2))
        return out

    def entries(self):
        """Rules 2 and 3, the way in: several ways into one block enter its
        top apart, left of its letters (BPMN asks no shared point), in the
        order they come from — the left channel and the blocks by x, then
        a detour round the right, then the way back, the farthest channel
        innermost, so their runs nest. The ways round by one channel into a
        block come in as one, by their trunk.
        A way from a channel turns above its target's row by how near its
        channel is, the nearest lowest. Returns ({index: x offset},
        {index: how far over its target's top it turns})."""
        entry, turn, into, rows = {}, {}, {}, {}
        for i, e in enumerate(self.edges):
            # A way into a trunk comes in where the trunk does.
            if self.nodes[e[0]][1] == self.nodes[e[1]][1] or i in self.trunk:
                continue
            came = self.channel_x.get(i, self.center(e[0])[0])
            back = self.is_back(e)
            east = back or e in self.east
            # From the right, a detour enters left of the ways back: it
            # turns above them, so their runs stop short of its drop.
            into.setdefault(e[1], []).append((2 if back else 1 if east else 0, -came if east else came, i))
            if i in self.channel_x:
                near = abs(self.channel_x[i] - (self.right if east else self.left))
                # A way back comes up its channel, the nearest turning lowest;
                # a detour comes down the left one, the farthest lowest. The
                # ways back take the lowest heights, the detours those above.
                rows.setdefault(self.nodes[e[1]][1], []).append((not back, near if back else -near, i))
        for b, ways in into.items():
            if len(ways) < 2:
                continue
            letters = len(self.nodes[b][5])
            lo, hi = -NODE_W / 2 + 16, (NODE_W / 2 - 16 if not letters else NODE_W / 2 - 22 - 26 * letters)
            step = min(22, (hi - lo) / (len(ways) - 1))
            for k, (_back, _came, i) in enumerate(sorted(ways)):
                entry[i] = (lo + hi) / 2 + (k - (len(ways) - 1) / 2) * step
        for row, ways in rows.items():
            # 12 px off the block, so the arrowhead has its drop, then 4
            # apart; the gap is made tall enough for them and the levels
            # under the row above (_rows).
            for k, (_detour, _near, i) in enumerate(sorted(ways)):
                turn[i] = 12 + k * 4
        for i, j in self.trunk.items():
            if j in entry:
                entry[i] = entry[j]
            turn[i] = turn[j]
        return entry, turn

    def _route(self):
        """The ways' channels, corners, levels and turns, by the rows' tops."""
        self.corner = self.corners()
        # Rule 3, the channels: the ways back on the right nested — one going
        # up fewer rows nearer, a longer one round it; of two as long, the
        # one into the block further right nearer — the detours on their side
        # nested too (nest).
        #
        # The ways round by a channel into one block share it, a trunk, one
        # per side — back on the right, round the right, round the left: each
        # runs along its row into it, and one carries it in, with the arrow
        # (self.trunk: a way -> the one carrying it). Where a way meets its
        # channel, down the map: its row, and in the row a corner's run (the
        # row's middle) above a level (under it). A way back is carried by the
        # one meeting it lowest, a detour by the one meeting it highest.
        def meets(i):
            return (self.nodes[self.edges[i][0]][1], 0 if i in self.corner else 1)

        def side(e):
            return "back" if self.is_back(e) else ("east" if e in self.east else "west") if e in self.detours else ""
        carrier = {}
        for i, e in enumerate(self.edges):
            if side(e):
                key, j = (side(e), e[1]), carrier.get((side(e), e[1]))
                if j is None or (meets(i) > meets(j) if key[0] == "back" else meets(i) < meets(j)):
                    carrier[key] = i
        self.trunk = {i: carrier[(side(e), e[1])] for i, e in enumerate(self.edges)
                      if side(e) and carrier[(side(e), e[1])] != i}

        # Nested: a detour into a higher row nearer; into one row, the one
        # reaching farther across nearer, turning higher (entries), so neither
        # crosses the other. The detours round the right run nearest the
        # lanes, the ways back past them.
        def nest(i, way):
            b = self.edges[i][1]
            return (self.nodes[b][1], -way * self.center(b)[0], i)
        east = sorted((c for (k, _b), c in carrier.items() if k == "east"), key=lambda i: nest(i, -1))
        backs = sorted((c for (k, _b), c in carrier.items() if k == "back"), key=lambda i: (
            self.nodes[self.edges[i][0]][1] - self.nodes[self.edges[i][1]][1],
            -self.center(self.edges[i][1])[0], i))
        west = sorted((c for (k, _b), c in carrier.items() if k == "west"), key=lambda i: nest(i, 1))
        self.channel_x = {i: self.right + CHANNEL * (k + 1) for k, i in enumerate(east + backs)}
        self.channel_x.update({i: self.left - CHANNEL * (k + 1) for k, i in enumerate(west)})
        self.channel_x.update({i: self.channel_x[j] for i, j in self.trunk.items()})
        self.level_off = self.levels()
        self.entry, self.turn_off = self.entries()

    def _place(self):
        """The levels and the turns where the rows came out."""
        self.level = {i: self.top[self.nodes[self.edges[i][0]][1]] + NODE_H + off
                      for i, off in self.level_off.items()}
        self.turn = {i: self.top[self.nodes[self.edges[i][1]][1]] - off for i, off in self.turn_off.items()}

    def _rows(self):
        """Each row's top, its gap above as tall as what runs in it: the
        levels the ways under the row above turn on and the turns of the ways
        into the row — 30 px where only a way straight down crosses it, room
        for its label and its arrowhead.

        Where no way turns under the upper row — they all leave from its
        blocks' middles — the lower row rises: under what is drawn above it in
        its own lanes, a drop for the arrowheads under the middles' runs, its
        own runs and their labels clear of the blocks above, and the turns of
        the ways coming into it by a channel under the middles' runs and
        clear of the blocks they pass."""
        lev, above = [0] * (self.rows + 1), [0] * (self.rows + 1)
        sides = [False] * (self.rows + 1)
        for i, e in enumerate(self.edges):
            ra = self.nodes[e[0]][1]
            if i in self.level_off:
                lev[ra] = max(lev[ra], self.level_off[i])
            if i in self.corner:
                sides[ra] = True
            if i in self.turn_off:
                rb = self.nodes[e[1]][1]
                above[rb] = max(above[rb], self.turn_off[i])
        drawn = {}
        for nid, (_lane, row, kind, _t, text, _f) in self.nodes.items():
            drawn[nid] = NODE_H
            if kind in ("start", "end"):
                # The words under the circle (shape): its title, then the text.
                lines = len(wrap(text, 30)[:2])
                drawn[nid] = 2 * 13 + 16 + (14 + 13 * (lines - 1) if lines else 0) + 4
        tops, y = [], TOP + max(above[0], 14) + 6
        for r in range(self.rows):
            tops.append(y)
            step = NODE_H + max(30, lev[r] + max(above[r + 1], 14) + 6)
            upper = {n[0]: drawn[nid] for nid, n in self.nodes.items() if n[1] == r}
            if r + 1 < self.rows and upper and not lev[r]:
                lower = [n[0] for n in self.nodes.values() if n[1] == r + 1]
                # Under a start or an end the page writes a line of its own
                # (its metrics, 13 px; a block keeps them inside), and a
                # block's letters stand 13 px over its top: in one lane, both
                # fit between.
                rise = [upper[lane] + UNDER + 14 for lane in lower if lane in upper]
                if sides[r]:
                    rise.append(NODE_H / 2 + 14)
                # Its own middles' runs, their labels 15 px above them, clear
                # of the blocks above and the line under them.
                rise.append(max(upper.values()) + UNDER + 15 - NODE_H / 2)
                # A way into the lower row from a channel turns over it: its
                # run under the upper row's middles, and clear of the line
                # under any block above that it passes.
                for i, off in self.turn_off.items():
                    e = self.edges[i]
                    if self.nodes[e[1]][1] != r + 1 or i in self.trunk:
                        continue
                    ends = sorted((self.channel_x[i], self.center(e[1])[0] + self.entry.get(i, 0)))
                    rise.append(NODE_H / 2 + 14 + off)
                    rise += [drawn[nid] + UNDER + off for nid, n in self.nodes.items() if n[1] == r
                             and ends[0] < self.center(nid)[0] + NODE_W / 2
                             and ends[1] > self.center(nid)[0] - NODE_W / 2]
                step = min(step, max(rise))
            y += step
        self.top = tops
        last = [drawn[nid] for nid, n in self.nodes.items() if n[1] == self.rows - 1]
        self.height = int(tops[-1] + max(last + [NODE_H]) + max(lev[self.rows - 1], 0) + 20)

    def body(self):
        parts = []
        if self.left:
            parts.append('<rect class="lane l-gutter" x="0" y="0" width="%d" height="%d"/>'
                         % (self.left, self.height))
        for i, (lane, title) in enumerate(self.lanes):
            x = self.lane_x[lane]
            parts.append('<rect class="lane l-%s%s" x="%d" y="0" width="%d" height="%d"/>'
                         % (lane, " alt" if i % 2 else "", x, LANE_W, self.height))
            parts.append('<text class="lt" x="%.1f" y="30" text-anchor="middle">%s</text>'
                         % (x + LANE_W / 2, esc(title)))
        parts.append('<line class="lh" x1="0" y1="%d" x2="%d" y2="%d"/>' % (TOP - 8, self.width, TOP - 8))
        for i, e in enumerate(self.edges):
            parts.append(self.edge(e, i))
        for nid in self.nodes:
            parts.append(self.shape(nid))
        return "\n".join(parts)

    def svg(self, symbol=False):
        defs = ('<defs><marker id="arrow-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="10" '
                'markerHeight="10" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" class="ah"/>'
                '</marker>' % self.name
                # Half as large, where a way joins a trunk.
                + "".join('<marker id="join%s-%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
                          'markerHeight="6" markerUnits="userSpaceOnUse" orient="auto">'
                          '<path d="M0 0 L10 5 L0 10 z" class="%s"/></marker>' % (kind, self.name, cls)
                          for kind, cls in (("", "ah"), ("-back", "ahb")))
                + '</defs>')
        if symbol:
            return ('<svg class="defs" width="0" height="0" aria-hidden="true">%s<symbol id="sym-%s" '
                    'viewBox="0 0 %d %d">%s</symbol></svg>' % (defs, self.name, self.width, self.height, self.body()))
        # Never wider than drawn, so every map is at one scale; narrower when
        # the window is (it scales down to fit), and on a phone no narrower
        # than 760 px — but a map narrower than that is not stretched to it.
        cap = ' style="max-width:%dpx;min-width:%dpx"' % (self.width, min(760, self.width))
        return ('<svg class="map map-%s" viewBox="0 0 %d %d" width="%d" height="%d"%s '
                'role="img" aria-label="%s">%s%s</svg>'
                % (self.name, self.width, self.height, self.width, self.height, cap, esc(self.name),
                   defs, self.body()))


STYLE = """
:root{--paper:#EEF1F5;--surface:#FFFFFF;--ink:#131B2C;--muted:#586379;--line:#C9D1DE;
--signal:#C97A0A;--signal-soft:#FBEFD9;--auto:#0C7A6B;--auto-soft:#DDF1EC;--human:#C2452F;
--human-soft:#FBE4DE;--cloud:#2F57C9;--cloud-soft:#E2E9FB;--violet:#7A4CC2;--violet-soft:#EEE4FB;
--lane-a:#F7F9FC;--lane-b:#EFF3F8;--here:#E8A400;
--body:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
--paper:#0D1320;--surface:#161F31;--ink:#E7EBF2;--muted:#9AA5BA;--line:#33415E;--signal:#F0A93B;
--signal-soft:#3A2C14;--auto:#4CC7B4;--auto-soft:#11332F;--human:#F07F69;--human-soft:#3B1F1A;
--cloud:#86A4F5;--cloud-soft:#1A2647;--violet:#B89AF0;--violet-soft:#2A1F45;--lane-a:#121A2A;
--lane-b:#0F1624;--here:#FFC53D;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#0D1320;--surface:#161F31;--ink:#E7EBF2;--muted:#9AA5BA;--line:#33415E;
--signal:#F0A93B;--signal-soft:#3A2C14;--auto:#4CC7B4;--auto-soft:#11332F;--human:#F07F69;
--human-soft:#3B1F1A;--cloud:#86A4F5;--cloud-soft:#1A2647;--violet:#B89AF0;--violet-soft:#2A1F45;
--lane-a:#121A2A;--lane-b:#0F1624;--here:#FFC53D;color-scheme:dark}
*{box-sizing:border-box}
html,body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 var(--body)}
main{max-width:1760px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:36px 0 8px}
p.lead,.muted{color:var(--muted)}
code{font-family:var(--mono);font-size:.92em}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px;overflow-x:auto}
/* A map's card hugs its map: no empty field round a narrow one. */
.card:has(> svg.map){width:fit-content;max-width:100%;margin-inline:auto}
svg.map{display:block;width:100%;height:auto;min-width:760px;margin:0 auto}
.lane{stroke:var(--line);stroke-width:1}
.lane{fill:var(--lane-a)}.lane.alt{fill:var(--lane-b)}.l-gutter{fill:var(--surface);stroke:none}
.lt{font:600 14px var(--body);fill:var(--muted);letter-spacing:.02em}
.lh{stroke:var(--line)}
.node .shape{stroke-width:1.6;fill:var(--surface);stroke:var(--muted)}
.node .t{font:600 12.5px var(--body);fill:var(--ink)}
.node .s{font:11px var(--body);fill:var(--muted)}
.k-session .shape{fill:var(--violet-soft);stroke:var(--violet);stroke-width:2.2}
.k-task .shape{fill:var(--auto-soft);stroke:var(--auto)}
.k-gate .shape{fill:var(--signal-soft);stroke:var(--signal)}
.k-user .shape{fill:var(--human-soft);stroke:var(--human)}
.k-wait .shape{fill:var(--cloud-soft);stroke:var(--cloud);stroke-dasharray:5 3}
.k-wait .clock{fill:none;stroke:var(--cloud);stroke-width:1.4}
.k-hold .shape{fill:var(--human-soft);stroke:var(--human);stroke-width:2.4;stroke-dasharray:6 3}
.k-start .shape{fill:var(--auto-soft);stroke:var(--auto);stroke-width:2}
.k-end .shape{fill:var(--surface);stroke:var(--ink);stroke-width:4}
.badge .dot{stroke:none}.badge text{font:700 12px var(--body);fill:#fff}
.b-F .dot{fill:var(--signal)}.b-W .dot{fill:var(--cloud)}.b-R .dot{fill:var(--human)}.b-S .dot{fill:var(--auto)}
.badge .ring{fill:none;stroke-width:0;opacity:0}
.b-F .ring{stroke:var(--signal)}.b-W .ring{stroke:var(--cloud)}.b-R .ring{stroke:var(--human)}.b-S .ring{stroke:var(--auto)}
.badge.busy .ring{opacity:1;stroke-width:3;stroke-dasharray:21 6.2;
  animation:ring-turn 1.4s linear infinite,ring-beat 1.4s ease-in-out infinite}
@keyframes ring-turn{to{stroke-dashoffset:-81.7}}
@keyframes ring-beat{50%{stroke-width:5}}
@media (prefers-reduced-motion:reduce){.badge.busy .ring{animation:none;stroke-width:4}}
.badge.stalled .ring{opacity:1;stroke:var(--human);stroke-width:3}
.edge path{fill:none;stroke:var(--muted);stroke-width:1.4}
.e-back path{stroke:var(--human);stroke-dasharray:6 4}
.e-msg path{stroke:var(--cloud);stroke-dasharray:2 3}
.ah{fill:var(--muted)}.ahb{fill:var(--human)}
.edge path.chev{fill:none;stroke:var(--muted);stroke-width:1.6;stroke-dasharray:none}
.e-back path.chev{stroke:var(--human)}
.el{font:10.5px var(--body);fill:var(--muted);paint-order:stroke;stroke:var(--paper);stroke-width:4px;
stroke-linejoin:round}
.e-back .el{fill:var(--human)}
.node.here .shape{stroke:var(--here);stroke-width:5;filter:drop-shadow(0 0 8px var(--here))}
.node.here .t{fill:var(--ink)}
[data-key]{cursor:pointer}
.edge path.hit{fill:none;stroke:transparent!important;stroke-width:14;stroke-dasharray:none!important}
.map .node,.map .edge,tr[data-key],#acts li{transition:opacity .12s}
body.dimming svg.map .node:not(.is-focus):not(.is-lit),
body.dimming svg.map .edge:not(.is-focus):not(.is-lit),
body.dimming tr[data-key]:not(.is-focus):not(.is-lit),
body.dimming #acts li[data-key]:not(.is-focus):not(.is-lit),
body.dimming #dock li[data-key]:not(.is-focus):not(.is-lit){opacity:.18}
#dock{position:fixed;top:8px;right:6px;z-index:15;width:max-content;max-height:calc(100vh - 16px);overflow:auto;
font-size:clamp(9px,calc((100vh - 64px) / var(--n,29) / 1.5),12px);
background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:6px;
box-shadow:0 6px 20px rgba(0,0,0,.12)}
#dock .dock-head{display:flex;align-items:center;gap:4px;margin:0 2px 4px;font-size:13px}
#dock .pin{margin:0;padding:1px 5px}
#dock ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0}
#dock li{padding:1px 5px;border-radius:5px;line-height:1.35;transition:opacity .12s}
#dock li code{font-size:1em}
#dock li:hover{background:var(--lane-b)}
#dock li.is-focus{background:var(--signal-soft);box-shadow:inset 3px 0 0 var(--signal)}
#dock li.is-lit{background:var(--lane-b)}
#dock li.is-picked{box-shadow:inset 3px 0 0 var(--ink)}
.pin{font:500 12px var(--body);padding:3px 8px;border-radius:7px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer;vertical-align:middle;margin-left:8px}
body.pinned main{max-width:none;margin:0;padding-right:calc(var(--dockw,130px) + 14px)}
body.pinned #clear{right:calc(var(--dockw,130px) + 20px)}
body.dimming svg.map .node.here:not(.is-focus):not(.is-lit){opacity:.6}
.node.is-focus .shape{stroke-width:4.2;filter:saturate(1.5) drop-shadow(0 0 6px var(--cloud-soft))}
.node.is-lit .shape{stroke-width:2.8}
.node.is-picked .shape{stroke-dasharray:none}
.edge.is-focus path.line{stroke-width:3.4}
.edge path.ride{opacity:0}
.edge.is-focus path.ride,.edge.is-lit path.ride,.edge.pl-go path.ride,.edge.pl-went path.ride{opacity:1}
.edge.is-focus .el{font-weight:700;fill:var(--ink)}
.edge.e-back.is-focus .el{fill:var(--human)}
tr.is-focus td{background:var(--signal-soft)}tr.is-lit td{background:var(--lane-b)}
tr.is-picked td:first-child{box-shadow:inset 4px 0 0 var(--signal)}
#clear{position:fixed;right:20px;bottom:20px;z-index:20;border:0;border-radius:999px;padding:10px 16px;
font:600 14px var(--body);background:var(--ink);color:var(--paper);box-shadow:0 6px 20px rgba(0,0,0,.25);cursor:pointer}
#tip{position:fixed;z-index:30;max-width:340px;padding:10px 12px;border-radius:10px;background:var(--surface);
color:var(--ink);border:1px solid var(--line);box-shadow:0 8px 24px rgba(0,0,0,.18);font-size:13px;
line-height:1.4;pointer-events:none}
#tip p{margin:4px 0}#tip .spec{font:600 12px var(--mono);color:var(--violet);margin-top:2px}#tip .tk{color:var(--muted);font-size:12px}#tip i{color:var(--muted);font-style:normal}
.printbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;margin:6px 0 12px;font-size:14px}
.printbar select,.printbar button{font:inherit;padding:5px 8px;border-radius:8px;border:1px solid var(--line);
background:var(--surface);color:var(--ink)}
.printbar button{background:var(--ink);color:var(--paper);border-color:var(--ink);cursor:pointer}
.printbar p{flex-basis:100%;margin:0;font-size:13px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin:10px 0 0;padding:0;list-style:none;font-size:13px}
.legend-maps{margin-top:6px}
.legend li{display:flex;align-items:center;gap:6px}
.sw{width:22px;height:14px;border-radius:4px;border:2px solid}
table{border-collapse:collapse;width:100%;background:var(--surface);border-radius:12px;overflow:hidden}
th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line);font-size:13.5px}
th{background:var(--lane-b);font-weight:600}
td code{white-space:nowrap}
a{color:var(--cloud)}
.print-only{display:none}
@media print{
 html,body{background:#fff}
 main{max-width:none;padding:0}
 .card{border:0;padding:0;overflow:visible}
 .screen-only{display:none!important}.print-only{display:block}
 h2{break-before:page;margin-top:0}
 h2.first{break-before:auto}
 svg.map{min-width:0;max-height:180mm}
 .sheet{break-after:page;position:relative}
 .sheet:last-child{break-after:auto}
 .sheet svg{width:100%;height:auto;display:block}
 .sheet .mark{font:9px var(--body);color:#555;display:flex;justify-content:space-between}
 .cut line{stroke:#888;stroke-width:1;stroke-dasharray:4 4}
 table{break-inside:auto}tr{break-inside:avoid}
}
"""

LEGEND = """<ul class="legend">
<li><span class="sw" style="background:var(--violet-soft);border-color:var(--violet)"></span>a Claude session</li>
<li><span class="sw" style="background:var(--auto-soft);border-color:var(--auto)"></span>sclaude does it</li>
<li><span class="sw" style="background:var(--signal-soft);border-color:var(--signal)"></span>a check or a choice</li>
<li><span class="sw" style="background:var(--human-soft);border-color:var(--human)"></span>a person</li>
<li><span class="sw" style="background:var(--cloud-soft);border-color:var(--cloud);border-style:dashed"></span>waiting</li>
<li><svg width="34" height="10"><path d="M0 5 H34" stroke="var(--human)" stroke-dasharray="6 4" stroke-width="2"/></svg>goes back</li>
<li><svg width="34" height="10"><path d="M0 5 H34" stroke="var(--cloud)" stroke-dasharray="2 3" stroke-width="2"/></svg>a message to another lane</li>
</ul>
<ul class="legend legend-maps">
<li><span class="sw" style="background:var(--signal);border-color:var(--signal);border-radius:50%;width:14px"></span>F — a friction review follows (<a href="#map-friction">its own map</a>)</li>
<li><span class="sw" style="background:var(--cloud);border-color:var(--cloud);border-radius:50%;width:14px"></span>W — may change sclaude in its workshop (<a href="#map-workshop">its own map</a>)</li>
<li><span class="sw" style="background:var(--human);border-color:var(--human);border-radius:50%;width:14px"></span>R — a regression runs here (<a href="#map-regression">its own map</a>)</li>
<li><span class="sw" style="background:var(--auto);border-color:var(--auto);border-radius:50%;width:14px"></span>S — main is checked here (<a href="#map-sync">its own map</a>)</li>
<li>The issue's summary comment — sessions, rounds, reviews — is rewritten at every step, by sclaude itself</li>
</ul>"""
