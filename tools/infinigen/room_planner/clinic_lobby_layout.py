"""Deterministic layout of the warm clinic reception lobby (VLM refs S17 / D3). No bpy.

    plan = layout(x0, x1, y0, y1, seed, obstacles=(), doors=())     -> {"items": [{cat, x, y, yaw, lift?, direct?}], "far_wall": {...}}

The FAR wall (the wall farthest from the doors) gets the oak wood-panel wall and, 1.25 m in front of it, the oak louver desk (front toward the room).
In front of the desk, 55-65 % of the way to the door side, a seating group on a jute rug: a sofa on one side, two armchairs on the other, a round oak coffee
table between. Four tall plants (floor_plant: the catalog's Infinigen plant) at the far corners and beside the group; framed botanical art on the side walls.
Conventions as the other layouts: (x, y) = footprint centre, yaw = front direction (+X) as furnish_rooms._place expects; `lift` = mounting height of wall pieces;
`direct` = flat piece placed without the footprint check (the rug lies under the furniture). Doors are kept clear (DOOR_CLEAR).
"""
from __future__ import annotations

import math
import random

from room_planner import rooftop_layout as rl

DOOR_CLEAR, WALL_OFF = 1.0, 0.14
SIZE = {"wood_wall": (0.2, 3.6), "oak_desk": (0.9, 3.2), "beige_sofa": (0.9, 2.0), "oak_armchair": (0.85, 0.8), "round_table": (1.0, 1.0), "jute_rug": (1.7, 2.4),
        "floor_plant": (0.6, 0.6), "wall_art": (0.06, 0.9)}


class _H(rl._Hall):
    def add(self, cat, cx, cy, yaw, aisle=0.1, edge=0.1, length=None, depth=None, **extra):
        d0, l0 = SIZE[cat]
        b = self.box(cx, cy, yaw, depth or d0, length or l0)
        if not self.free(b, aisle, edge):
            return False
        self.occ.append(b)
        self.items.append({"cat": cat, "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw, 4), **extra})
        return True


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    H = _H(x0, x1, y0, y1, obstacles, doors)
    H.keep = [(o[0] - 0.4, o[1] + 0.4, o[2] - 0.4, o[3] + 0.4) for o in obstacles] + \
             [(dx - DOOR_CLEAR, dx + DOOR_CLEAR, dy - DOOR_CLEAR, dy + DOOR_CLEAR) for dx, dy in doors]     # this module's own door clearance
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    # the 4 walls: (centre, inward normal, tangent, length)
    walls = [((x1, ym), (-1, 0), (0, 1), y1 - y0), ((x0, ym), (1, 0), (0, 1), y1 - y0), ((xm, y1), (0, -1), (1, 0), x1 - x0), ((xm, y0), (0, 1), (1, 0), x1 - x0)]

    def door_dist(w):
        return min((math.hypot(w[0][0] - dx, w[0][1] - dy) for dx, dy in doors), default=0.0)
    far = max((w for w in walls if w[3] >= 3.6), key=lambda w: (door_dist(w), w[3]), default=max(walls, key=lambda w: w[3]))
    (cx, cy), n, t, Wl = far
    depth = (x1 - x0) if n[0] else (y1 - y0)
    yaw_n = math.atan2(n[1], n[0])                                   # a piece facing into the room

    def at(d, v):                                                    # d from the far wall into the room, v along it
        return cx + n[0] * d + t[0] * v, cy + n[1] * d + t[1] * v
    face = lambda wx, wy: math.atan2(wy, wx)
    pw = min(3.6, Wl - 1.0)
    H.add("wood_wall", *at(WALL_OFF + 0.1, 0.0), yaw_n, aisle=0.05, edge=0.0, length=pw, lift=0.0)
    H.add("oak_desk", *at(1.35, 0.0), yaw_n, aisle=0.1, edge=0.0, length=min(3.2, Wl - 1.4))
    # seating group: rug + round table + sofa + 2 armchairs, tried at several distances from the far wall and both sides until all four pieces fit
    base_dg = max(3.4, min(depth - 1.8, depth * 0.62))
    side0 = rng.choice((-1, 1)); placed_group = False
    for ddg, sd in ((0.0, side0), (0.0, -side0), (-0.5, side0), (-0.5, -side0), (0.5, side0), (0.5, -side0), (-1.0, side0), (-1.0, -side0)):
        dg = base_dg + ddg
        gv = sd * min(0.5, (Wl - 4.2) / 2 if Wl > 4.2 else 0.0)
        n_items, n_occ = len(H.items), len(H.occ)
        tx, ty = at(dg, gv)
        ok = H.add("round_table", tx, ty, 0.0, aisle=0.0, edge=0.2)
        sx, sy = at(dg, gv - sd * 1.45)
        ok = ok and H.add("beige_sofa", sx, sy, face(sd * t[0], sd * t[1]), aisle=0.0, edge=0.15)          # on the -sd side, facing the table
        for dd in (-0.65, 0.65):
            ax, ay = at(dg + dd, gv + sd * 1.25)
            ok = ok and H.add("oak_armchair", ax, ay, face(-sd * t[0], -sd * t[1]), aisle=0.0, edge=0.15)
        if ok:
            H.items.append({"cat": "jute_rug", "x": round(tx, 3), "y": round(ty, 3), "yaw": round(yaw_n + math.pi / 2, 4), "direct": True})
            placed_group = True
            break
        del H.items[n_items:]; del H.occ[n_occ:]
    if not placed_group:                                                  # no room for the full group: the table and two armchairs only
        dg, gv = base_dg, 0.0
        tx, ty = at(dg, gv)
        if H.add("round_table", tx, ty, 0.0, aisle=0.0, edge=0.2):
            H.items.append({"cat": "jute_rug", "x": round(tx, 3), "y": round(ty, 3), "yaw": round(yaw_n + math.pi / 2, 4), "direct": True})
    # four plants: the far corners, and beside the seating group's far end
    for dv in (-1, 1):
        px, py = at(0.55, dv * (Wl / 2 - 0.55))
        H.add("floor_plant", px, py, 0.0, aisle=0.1, edge=0.1)
    for dv in (-1, 1):
        px, py = at(dg + 1.6, dv * (Wl / 2 - 0.5))
        H.add("floor_plant", px, py, 0.0, aisle=0.1, edge=0.1)
    # framed art on the two side walls, flush, hung at 0.9 m (wall pieces: back at the wall, front into the room)
    for dv in (-1, 1):
        ax, ay = at(max(2.4, dg * 0.6), dv * (Wl / 2 - WALL_OFF))
        H.add("wall_art", ax, ay, face(-dv * t[0], -dv * t[1]), aisle=0.05, edge=0.0, lift=0.9)
    return {"items": H.items, "far_wall": {"normal": n, "tangent": t, "length": round(Wl, 2), "depth": round(depth, 2)}}


if __name__ == "__main__":
    import collections
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (7.0, 5.6)))
    p = layout(0, W, 0, D, 1, obstacles=[], doors=[(0.0, D * 0.3)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "far wall", p["far_wall"], f"area {W * D:.0f} m2")
    g = [["." for _ in range(int(W * 3))] for _ in range(int(D * 3))]
    ch = {"wood_wall": "W", "oak_desk": "D", "beige_sofa": "S", "oak_armchair": "a", "round_table": "t", "jute_rug": "r", "floor_plant": "p", "wall_art": "A"}
    for e in p["items"]:
        yy, xx = int(e["y"] * 3), int(e["x"] * 3)
        if 0 <= yy < len(g) and 0 <= xx < len(g[0]):
            g[yy][xx] = ch[e["cat"]]
    print("\n".join("".join(r) for r in g))
