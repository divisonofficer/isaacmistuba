"""Deterministic floor layout for the underground wine pub (80-90 m2; docs/wine_pub_underground_design_proposal.md). No bpy.

    plan = layout(x0, x1, y0, y1, seed, obstacles=(), doors=())   -> {"items": [{cat, x, y, yaw, lift?}], "ceiling": [{cat, x, y, z}], "long_axis": ...}

Frame: u along the long axis from the entrance, v across; the bar is at the far short wall (u = L), the mirrored-pipe wall on the solid wall v = 0.
(x, y) = footprint centre, yaw = front direction (+X) as furnish_rooms._place expects. Zones: bar counter + two steel bottle shelves behind it; a floor-edge
bottle row line (fairy-lit) that separates the bar zone from the seating; round marble tables with 2-3 burgundy velvet chairs in two loose rows;
a mirror wall on the solid wall; a mirror ball and silver sphere clusters hung from the ceiling (the caller hangs them at its ceiling height).
"""
from __future__ import annotations

import math
import random

from room_planner import rooftop_layout as rl

AISLE, DOOR_CLEAR, EDGE, ENTRANCE = 0.9, 2.0, 0.3, 1.6
SIZE = {"bar_counter": (0.68, 3.6), "bottle_shelf": (0.4, 1.5), "bottle_row": (0.14, 2.4), "round_table": (0.7, 0.7), "velvet_chair": (0.6, 0.55),
        "mirror_wall": (0.07, 2.4), "mirror_column": (0.8, 0.8)}


class _H(rl._Hall):
    def add(self, cat, cx, cy, yaw, aisle=AISLE, edge=EDGE, kind=None, length=None):
        d0, l0 = SIZE[cat]
        b = self.box(cx, cy, yaw, d0, length or l0)
        if not self.free(b, aisle, edge):
            return False
        self.occ.append(b)
        self.items.append({"cat": cat, "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw, 4)})
        return True


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    H = _H(x0, x1, y0, y1, obstacles, [(dx, dy) for dx, dy in doors])
    H.keep = [(k[0], k[1], k[2], k[3]) for k in H.keep]
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    face = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    to_entrance, to_far, to_wall, to_glass = face(-1, 0), face(1, 0), face(0, -1), face(0, 1)
    # bar at the far short wall: counter faces the room (front +X toward the guests), shelves behind it against the wall
    H.add("bar_counter", *world(L - 1.5, S / 2), to_entrance, aisle=0.3, edge=0.05)
    nsh = max(2, int((S - 0.6) / 1.55))                                   # a LONG bottle shelf wall: shelves side by side along the whole back wall
    for k in range(nsh):
        H.add("bottle_shelf", *world(L - 0.25, 0.3 + 0.775 + k * 1.55 + ((S - 0.6) - nsh * 1.55) / 2), to_entrance, aisle=0.05, edge=0.04)
    # floor-edge bottle rows (fairy lights) along a line separating the bar zone: u = L - 3.2
    nrow = max(1, int((S - 0.8) / 2.4))
    for k in range(nrow):
        H.add("bottle_row", *world(L - 3.3, 0.6 + 1.2 + k * 2.4), face(1, 0), aisle=0.2, edge=0.05)
    # mirrored-pipe wall on the solid wall (v = 0), two panels
    for u in (L * 0.45, L * 0.45 + 2.5):
        if u + 1.2 < L - 3.4:
            H.add("mirror_wall", *world(u, 0.1), to_glass, aisle=0.05, edge=0.03)
    # mirrored columns (stone-clad, mirror face) at the seating / bar boundary: they carry the reflections of the photos
    for k, vv in enumerate((S * 0.22, S * 0.78)):
        H.add("mirror_column", *world(L - 4.4, vv), to_wall if k == 0 else to_glass, aisle=0.4, edge=0.1)
    # round tables with velvet chairs in two loose rows in the seating zone
    u = ENTRANCE + 0.5; n = 0; settings = []
    while u < L - 4.6:
        for row, v in enumerate((S * 0.2, S * 0.5, S * 0.8) if S > 6.5 else (S * 0.3, S * 0.72)):
            jit = rng.uniform(-0.25, 0.25)
            n_i, n_o, n_s = len(H.items), len(H.occ), len(settings)
            if H.add("round_table", *world(u + jit, v + rng.uniform(-0.2, 0.2)), 0.0, aisle=0.3):
                tx, ty = H.items[-1]["x"], H.items[-1]["y"]
                k = rng.choice((2, 2, 3))
                for q in range(k):
                    a = rng.uniform(0, 2 * math.pi) if k == 3 and q == 2 else (math.pi * q + math.pi / 2 + (0.3 if q else 0.0))
                    cx, cy = tx + 0.9 * math.cos(a), ty + 0.9 * math.sin(a)     # table radius 0.35 + chair half-depth 0.3 + _place margin 0.05 + slack
                    cb = H.box(cx, cy, a + math.pi, *SIZE["velvet_chair"])
                    if H.free(cb, 0.06, 0.15):                       # a chair must not land on a neighbour, a wall piece or a door keep-out
                        H.occ.append(cb)
                        H.items.append({"cat": "velvet_chair", "x": round(cx, 3), "y": round(cy, 3), "yaw": round(a + math.pi, 4)})
                        settings.append({"x": round(tx + 0.16 * math.cos(a), 3), "y": round(ty + 0.16 * math.sin(a), 3), "yaw": round(a + math.pi, 4), "z": 0.74})   # a dish and glass at every seat
                if len(H.items) == n_i + 1:                              # S23 r4: a table that got no chair is taken back
                    del H.items[n_i:]; del H.occ[n_o:]
                    continue
                n += 1
        u += 2.0
    ceiling = [{"cat": "mirror_ball", "x": round(world(L * 0.55, S * 0.5)[0], 2), "y": round(world(L * 0.55, S * 0.5)[1], 2)}] + \
              [{"cat": "silver_spheres", "x": round(world(u_, S * 0.5)[0], 2), "y": round(world(u_, S * 0.5)[1], 2)} for u_ in (L * 0.25, L * 0.8)]
    return {"items": H.items, "settings": settings, "ceiling": ceiling, "long_axis": "x" if long_x else "y"}


if __name__ == "__main__":
    import collections
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (14.0, 6.2)))
    p = layout(0, W, 0, D, 1, obstacles=[(W * 0.3, W * 0.3 + 0.4, D / 2 - 0.2, D / 2 + 0.2)], doors=[(0.0, D / 2)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "ceiling", len(p["ceiling"]), f"area {W * D:.0f} m2")
    g = [["." for _ in range(int(W * 2))] for _ in range(int(D * 2))]
    ch = {"bar_counter": "B", "bottle_shelf": "S", "bottle_row": "b", "round_table": "T", "velvet_chair": "c", "mirror_wall": "M", "mirror_column": "C"}
    for e in p["items"]:
        yy, xx = int(e["y"] * 2), int(e["x"] * 2)
        if 0 <= yy < len(g) and 0 <= xx < len(g[0]):
            g[yy][xx] = ch[e["cat"]]
    print("\n".join("".join(r) for r in g))
