"""Deterministic layout of the airport duty-free hall (docs/airport_duty_free_design_proposal.md). No bpy. First scene ~40 x 24 m.

    plan = layout(x0, x1, y0, y1, seed, obstacles=(), doors=())    -> {"items": [{cat, x, y, yaw, lift?}]}

Frame: u along the long axis from the escalator end (u = 0), v across. Escalator arrival: 3 lanes on the first short wall with a cart rack and planters beside them.
Central hall: tree columns on a 10 x 8 m grid, island booths between the column rows (two staggered rows), yellow sign boards on every other column, white bins and
planters along the long walls. (x, y) = footprint centre, yaw = front direction (+X).
"""
from __future__ import annotations

import math

from room_planner import rooftop_layout as rl

SIZE = {"escalator": (9.0, 1.2), "cart_rack": (0.7, 2.3), "planter": (1.3, 2.5), "tree_column": (1.0, 1.0), "island_booth": (3.1, 5.1), "yellow_sign": (0.2, 1.0), "white_bin": (0.6, 0.6)}


class _H(rl._Hall):
    def add(self, cat, cx, cy, yaw, aisle=0.4, edge=0.1, **extra):
        d0, l0 = SIZE[cat]
        b = self.box(cx, cy, yaw, d0, l0)
        if not self.free(b, aisle, edge):
            return False
        self.occ.append(b)
        self.items.append({"cat": cat, "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw, 4), **extra})
        return True


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    H = _H(x0, x1, y0, y1, obstacles, doors)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    face = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    for k in (-1, 0, 1):                                              # 3 escalator lanes along u, uphill toward the first short wall
        H.add("escalator", *world(5.2, S / 2 + k * 1.8), face(-1, 0), aisle=0.1, edge=0.3)
    H.add("cart_rack", *world(1.6, S / 2 + 4.6), face(0, -1), aisle=0.3)
    H.add("planter", *world(1.2, S / 2 - 4.6), face(0, 1), aisle=0.3)
    u0 = 12.0; cols = []
    for iu in range(3):
        for iv in range(3):
            u, v = u0 + iu * 10.0, 4.0 + iv * (S - 8.0) / 2
            if u < L - 2.0 and H.add("tree_column", *world(u, v), 0.0, aisle=0.5):
                cols.append((u, v))
    for iu in range(3):                                               # booths in the aisles between the column rows, staggered
        for iv in range(2):
            u, v = u0 + 5.0 + iu * 10.0, 8.0 + iv * (S - 16.0) + (3.0 if iu % 2 else 0.0)
            if u < L - 3.0:
                H.add("island_booth", *world(u, S / 2 + (v - S / 2) * 0.7), face(0, 1), aisle=1.5)
    for k, (u, v) in enumerate(cols):
        if k % 2 == 0:
            H.add("yellow_sign", *world(u + 0.7, v), face(1, 0), aisle=0.1, edge=0.0)
    for u in range(14, int(L) - 2, 7):
        H.add("white_bin", *world(u, 0.5), face(0, 1), aisle=0.2, edge=0.0)
        H.add("planter", *world(u + 3.0, S - 0.8), face(0, -1), aisle=0.5, edge=0.0)
    return {"items": H.items, "long_axis": "x" if long_x else "y"}


if __name__ == "__main__":
    import collections
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (40.0, 24.0)))
    p = layout(0, W, 0, D, 1)
    print(dict(collections.Counter(e["cat"] for e in p["items"])), f"area {W * D:.0f} m2")
