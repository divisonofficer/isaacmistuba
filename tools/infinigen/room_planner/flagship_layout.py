"""Deterministic floor layout for the large flagship boutique hall (reference set boutique_large_flagship_01). No bpy.

    plan = layout(x0, x1, y0, y1, seed, obstacles=(), doors=())     # world box -> {"items": [{cat, x, y, yaw, lift?}, ...], "long_axis": "x"|"y"}

realize._fill_flagship places every item directly with furnish_rooms._place (no empty-region search: that finder is sized for rooms, not halls).
(x, y) is the CENTRE of the piece's footprint, `yaw` is the direction its front (+X) faces, as _place expects; `lift` is the mounting height of
wall pieces. Rules: nothing within DOOR_CLEAR of a door, columns / other obstacles (xmin, xmax, ymin, ymax) kept clear, every pair of pieces >= AISLE
apart (so aisles are >= 1.4 m), nothing within EDGE of a wall except wall pieces.

Contents: wall rails along both long walls (mount 1.65 m), 2 rows of freestanding double rails (clothing_rack pairs back to back), stone-slab tables
(2.2 x 1.1 m) in a loose grid with 2.0-2.4 m aisles, 3-4 stepped plinths, 2 lattice screens, a cash desk near the door, fitting rooms on one side wall.
"""
from __future__ import annotations

import math
import random

AISLE, DOOR_CLEAR, EDGE, ENTRANCE = 1.4, 2.8, 0.4, 4.0
SIZE = {"wall_rail": (0.16, 3.0), "clothing_rack": (0.64, 1.75), "stone_table": (1.1, 2.2), "stepped_plinth": (1.2, 1.8), "lattice_screen": (0.45, 1.9),
        "counter": (0.65, 2.4), "fitting_room": (1.1, 1.25), "fl_wood_wall": (0.2, 3.6)}          # (depth along the front axis, length across it) in metres


class _Hall:
    def __init__(self, x0, x1, y0, y1, obstacles, doors):
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.occ, self.items = [], []
        self.keep = [(o[0] - 0.4, o[1] + 0.4, o[2] - 0.4, o[3] + 0.4) for o in obstacles]
        self.keep += [(dx - DOOR_CLEAR, dx + DOOR_CLEAR, dy - DOOR_CLEAR, dy + DOOR_CLEAR) for dx, dy in doors]

    def box(self, cx, cy, yaw, depth, length):
        """World AABB of a piece whose front (depth axis) points along yaw."""
        c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
        hx = (depth * c + length * s) / 2; hy = (depth * s + length * c) / 2
        return (cx - hx, cx + hx, cy - hy, cy + hy)

    def free(self, b, aisle=AISLE, edge=EDGE, wall=False):
        if not wall and (b[0] < self.x0 + edge or b[1] > self.x1 - edge or b[2] < self.y0 + edge or b[3] > self.y1 - edge):
            return False
        if wall and (b[0] < self.x0 - 0.05 or b[1] > self.x1 + 0.05 or b[2] < self.y0 - 0.05 or b[3] > self.y1 + 0.05):
            return False
        for k in self.keep:
            if b[0] < k[1] and k[0] < b[1] and b[2] < k[3] and k[2] < b[3]:
                return False
        for o, wallpiece in self.occ:
            m = 0.05 if (wall and wallpiece) else aisle
            if b[0] < o[1] + m and o[0] < b[1] + m and b[2] < o[3] + m and o[2] < b[3] + m:
                return False
        return True

    def add(self, cat, cx, cy, yaw, depth=None, length=None, lift=0.0, wall=False, aisle=AISLE, edge=EDGE, reserve_depth=None):
        d0, l0 = SIZE[cat]
        depth, length = depth or d0, length or l0
        real = self.box(cx, cy, yaw, depth, length)
        if reserve_depth and reserve_depth > depth:               # reserve extra floor in front of the piece (garments, a person's width)
            sh = (reserve_depth - depth) / 2
            b = self.box(cx + sh * math.cos(yaw), cy + sh * math.sin(yaw), yaw, reserve_depth, length)
        else:
            b = real
        if not self.free(real, aisle, edge, wall) or not self.free(b, aisle, edge, True):
            return False
        self.occ.append((b, wall))
        e = {"cat": cat, "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw, 4)}
        if lift:
            e["lift"] = lift
        self.items.append(e)
        return True


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    H = _Hall(x0, x1, y0, y1, obstacles, doors)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    face = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))      # a (u, v) direction -> world yaw

    # 1. fitting rooms on one side wall (the far long wall), at the back half
    side_v = S - SIZE["fitting_room"][0] / 2 - 0.05
    n_fit, u = 0, L - 1.0
    while n_fit < 5 and u - SIZE["fitting_room"][1] > L * 0.55:
        cx, cy = world(u - SIZE["fitting_room"][1] / 2, side_v)
        if H.add("fitting_room", cx, cy, face(0, -1), aisle=0.05, edge=0.05):
            n_fit += 1
        u -= SIZE["fitting_room"][1] + 0.05
    # 2. cash desk near the door, to the side, facing the door
    d0 = doors[0] if doors else world(0.0, S / 2)
    for off in (2.6, -2.6, 3.4, -3.4):
        cu = ENTRANCE - 0.2
        cx, cy = world(cu, S / 2 + off)
        if H.add("counter", cx, cy, face(-1, 0), aisle=0.8):
            break
    # 2b. warm oak panel wall(s) on the back short wall (u = L), flush: the reference's teak zone
    nw = max(1, min(3, int((S - 1.0) // 3.7)))
    for k in range(nw):
        vv = S / 2 + (k - (nw - 1) / 2) * 3.7
        H.add("fl_wood_wall", *world(L - 0.24, vv), face(-1, 0), aisle=0.05, edge=0.0, wall=True)
    # 3. wall rails along both long walls
    for v, nv in ((SIZE["wall_rail"][0] / 2 + 0.12, 1), (S - SIZE["wall_rail"][0] / 2 - 0.12, -1)):     # 0.1 m off the wall: the room mesh is not exactly at the box edge
        u = ENTRANCE - 0.5
        while u + 2.4 <= L - 0.8:
            length = rng.choice((2.4, 3.0, 3.6))
            if u + length > L - 0.8:
                length = 2.4
            cx, cy = world(u + length / 2, v)
            if H.add("wall_rail", cx, cy, face(0, nv), length=length, lift=1.65, wall=True, reserve_depth=0.7):
                pass
            u += length + 0.15
    # 4. bands across the hall, alternating double rails (R) and stone-slab tables (T), 2.0 m aisles between bands
    cur, kind = 0.8 + AISLE + 0.2, "R"
    while cur + 1.1 <= S - (0.8 + AISLE):
        vc = cur + 0.55
        u = ENTRANCE + 1.5
        if kind == "R":                                            # two clothing racks back to back, a gap every now and then
            while u + 1.6 <= L - 2.0:
                a = H.add("clothing_rack", *world(u + 0.9, vc + 0.34), face(0, 1), aisle=AISLE)     # measured with cloth: 0.62 deep, 1.33 long (L 1.2)
                b = H.add("clothing_rack", *world(u + 0.9, vc - 0.34), face(0, -1), aisle=0.0) if a else False   # back to back needs 0.68, not 0.54
                u += 1.9 + (1.6 if rng.random() < 0.3 else 0.05)
        else:                                                      # tables lengthwise, loosely jittered, a 1.6-2.2 m cross aisle between them
            while u + 2.2 <= L - 2.0:
                yaw_t = 0.0 if long_x else math.pi / 2             # (front axis x; length along local y): lengthwise needs yaw +-pi/2 when u is x
                yaw_t = math.pi / 2 if long_x else 0.0
                H.add("stone_table", *world(u + 1.1 + rng.uniform(-0.2, 0.2), vc + rng.uniform(-0.15, 0.15)), yaw_t, aisle=1.4)
                u += 2.2 + rng.uniform(1.6, 2.2)
        cur += 1.1 + rng.uniform(2.0, 2.4); kind = "T" if kind == "R" else "R"
    # 5. stepped plinths (3-4) and lattice screens (2) where space is left, preferring the back half
    for cat, n, aisle in (("stepped_plinth", rng.choice((3, 4)), 1.0), ("lattice_screen", 2, 0.9)):
        tries = got = 0
        while got < n and tries < 1200:
            tries += 1
            cx, cy = world(rng.uniform(L * 0.3, L - 1.5), rng.uniform(1.2, S - 1.2))
            if H.add(cat, cx, cy, rng.choice((0.0, math.pi / 2, math.pi, -math.pi / 2)), aisle=aisle):
                got += 1
    return {"items": H.items, "long_axis": "x" if long_x else "y"}


if __name__ == "__main__":
    import collections
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (25.0, 13.6)))
    p = layout(0, W, 0, D, 1, obstacles=[(W / 3 - 0.2, W / 3 + 0.2, D / 2 - 0.2, D / 2 + 0.2)], doors=[(0.0, D / 2)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "long axis", p["long_axis"], f"area {W * D:.0f} m2")
    g = [["." for _ in range(int(W * 2))] for _ in range(int(D * 2))]
    ch = {"fl_wood_wall": "W", "wall_rail": "=", "clothing_rack": "r", "stone_table": "T", "stepped_plinth": "P", "lattice_screen": "L", "counter": "C", "fitting_room": "F"}
    for e in p["items"]:
        if 0 <= int(e["y"] * 2) < len(g) and 0 <= int(e["x"] * 2) < len(g[0]):
            g[int(e["y"] * 2)][int(e["x"] * 2)] = ch[e["cat"]]
    print("\n".join("".join(r) for r in g))
