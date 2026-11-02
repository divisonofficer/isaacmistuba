"""Deterministic floor layout for the rooftop fine-dining restaurant (reference set rooftop_restaurant_01). No bpy.

    plan = layout(x0, x1, y0, y1, seed, obstacles=(), doors=())    -> {"items": [{cat, x, y, yaw, kind?}], "chandeliers": [{x, y, z}], "settings": [...]}

Frame: the long axis is u from the entrance end; the GLASS wall is the far long wall (v = S, as rooftop_shell builds it), the solid wall v = 0.
(x, y) = footprint centre, yaw = direction of the piece's front (+X), as furnish_rooms._place expects (see flagship_layout). Zones:
  window  : along the glass, high marble tables (round / square) with 2 bar stools each (white metal / gold), pyramid heaters between pairs
  banquette: along the solid wall, cream leather banquettes (back to the wall), a low marble table in front of each, 2 cube ottomans
  booths  : the middle, rows of navy velvet booths back to back with low marble tables between
  fixtures: mirror-clad columns on the axis, floor air conditioners on the solid wall, a bar counter at the far short wall
  chandeliers: along the centre line every ~5 m (hung from the trusses; z given by the caller's ridge, here a default 3.4 m)
Rules: AISLE >= 1.3 m between pieces, DOOR_CLEAR around doors, obstacles padded.
"""
from __future__ import annotations

import math
import random

AISLE, DOOR_CLEAR, EDGE, ENTRANCE = 1.3, 2.4, 0.3, 3.0
SIZE = {"banquette": (0.6, 2.4), "marble_table_low": (0.7, 1.2), "marble_table_high": (0.7, 0.7), "marble_table_round": (0.7, 0.7),
        "bar_stool": (0.42, 0.42), "cube_ottoman": (0.5, 0.5), "velvet_booth": (0.8, 2.2), "mirror_column": (0.7, 0.7), "timber_column": (0.6, 0.6), "floor_ac": (0.35, 0.5),
        "patio_heater": (0.64, 0.64), "counter": (0.65, 3.0)}


class _Hall:
    def __init__(self, x0, x1, y0, y1, obstacles, doors):
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.occ, self.items = [], []
        self.keep = [(o[0] - 0.4, o[1] + 0.4, o[2] - 0.4, o[3] + 0.4) for o in obstacles]
        self.keep += [(dx - DOOR_CLEAR, dx + DOOR_CLEAR, dy - DOOR_CLEAR, dy + DOOR_CLEAR) for dx, dy in doors]

    @staticmethod
    def box(cx, cy, yaw, depth, length):
        c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
        hx, hy = (depth * c + length * s) / 2, (depth * s + length * c) / 2
        return (cx - hx, cx + hx, cy - hy, cy + hy)

    def free(self, b, aisle, edge):
        if b[0] < self.x0 + edge or b[1] > self.x1 - edge or b[2] < self.y0 + edge or b[3] > self.y1 - edge:
            return False
        for k in self.keep:
            if b[0] < k[1] and k[0] < b[1] and b[2] < k[3] and k[2] < b[3]:
                return False
        return not any(b[0] < o[1] + aisle and o[0] < b[1] + aisle and b[2] < o[3] + aisle and o[2] < b[3] + aisle for o in self.occ)

    def add(self, cat, cx, cy, yaw, aisle=AISLE, edge=EDGE, kind=None, length=None):
        d0, l0 = SIZE[cat]
        b = self.box(cx, cy, yaw, d0, length or l0)
        if not self.free(b, aisle, edge):
            return False
        self.occ.append(b)
        e = {"cat": cat, "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw, 4)}
        if kind:
            e["kind"] = kind
        self.items.append(e)
        return True


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    rng = random.Random(seed)
    H = _Hall(x0, x1, y0, y1, obstacles, doors)
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    face = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    towards_glass, towards_wall, towards_far = face(0, 1), face(0, -1), face(1, 0)
    # fixtures first: floor air conditioners on the solid wall, a bar at the far short wall, mirror columns on the axis (before the seating)
    for u in (1.4, L - 1.2):
        H.add("floor_ac", *world(u, 0.26), towards_glass, aisle=0.2, edge=0.04)
    H.add("counter", *world(L - 0.5, S / 2), face(-1, 0), aisle=0.5, edge=0.04, length=3.6)
    for uc in (ENTRANCE + 6.5,):
        if uc < L - 2.0:
            H.add("mirror_column", *world(uc, S * 0.5), towards_wall, aisle=0.6)
    for k, uc in enumerate((ENTRANCE + 3.2, ENTRANCE + 8.8, ENTRANCE + 14.4)):      # timber slat columns first (before the seating takes the floor)
        if uc < L - 2.0:
            H.add("timber_column", *world(uc, S * (0.5 if k % 2 == 0 else 0.6)), towards_wall, aisle=0.4)
    settings = []

    def setting(u, v, nv, z):                                  # a table setting facing along +-v (nv = +1 faces the glass)
        x, y = world(u, v)
        settings.append({"x": round(x, 3), "y": round(y, 3), "yaw": round(face(0, nv), 4), "z": z})

    # window zone: tables along the glass; stools on the room side and the glass side of each
    u, n, vt = ENTRANCE + 1.0, 0, S - 1.3
    while u < L - 3.0:
        cat = ("marble_table_round", "marble_table_low", "marble_table_high")[n % 3]
        low = cat == "marble_table_low"
        n_i, n_o, n_s = len(H.items), len(H.occ), len(settings)
        if H.add(cat, *world(u, vt), towards_glass, aisle=0.9):
            so = 0.35 + 0.21 + 0.1                                 # table half-width (0.35 across v for round/high; low tables are 1.2 long along v) + stool half + _place margin
            offs = ((-0.3, -(0.6 + 0.21 + 0.1)), (0.3, -(0.6 + 0.21 + 0.1)), (-0.3, 0.6 + 0.21 + 0.1), (0.3, 0.6 + 0.21 + 0.1)) if low else ((0.0, -so), (0.0, so))
            for du, dv in offs:
                if H.add("bar_stool", *world(u + du, vt + dv), face(0, 1) if dv < 0 else face(0, -1), aisle=0.0, kind="white" if rng.random() < 0.7 else "gold"):
                    setting(u + (du * 0.9), vt + (0.14 if dv > 0 else -0.14), -1 if dv > 0 else 1, 0.75 if low else 1.05)      # a setting only where a seat exists
            if not any(e["cat"] == "bar_stool" for e in H.items[n_i + 1:]):     # S22 r5 'tables without chairs': a table that got no seat is taken back
                del H.items[n_i:]; del H.occ[n_o:]; del settings[n_s:]
                u += 2.2
                continue
            n += 1
            if n % 2 == 0:
                H.add("patio_heater", *world(u + 1.5, S - 0.7), towards_glass, aisle=0.5)
        u += 2.2
    # banquette zone along the solid wall: banquette, a low table in front, two ottomans
    u = ENTRANCE + 0.5
    while u + 2.4 < L - 3.0:
        L_b = rng.choice((2.4, 3.0, 3.6))
        if H.add("banquette", *world(u + L_b / 2, 0.36), towards_glass, aisle=0.1, edge=0.04, length=L_b):
            if H.add("marble_table_low", *world(u + L_b / 2, 1.45), towards_glass, aisle=0.2):
                for du in (-0.35, 0.35):
                    setting(u + L_b / 2 + du, 1.45 - 0.14, 1, 0.75)
            for du in (-0.45, 0.45):
                H.add("cube_ottoman", *world(u + L_b / 2 + du, 2.15), towards_wall, aisle=0.1)
        u += L_b + 0.5
    # middle: ONE row of navy velvet booths facing low tables (a third of the seating), cream banquettes in the second row facing the booths, timber columns
    for r, vb in enumerate((S * 0.30, S * 0.30 + 3.6)):
        u = ENTRANCE + 1.2; k = 0
        while u + 2.2 < L - 3.0:
            if r == 0:
                ok = H.add("velvet_booth", *world(u + 1.1, vb), towards_glass if False else towards_glass, aisle=0.3)
                if ok and H.add("marble_table_low", *world(u + 1.1, vb + 1.35), towards_glass, aisle=0.1):
                    for du in (-0.35, 0.35):
                        setting(u + 1.1 + du, vb + 1.35 - 0.14, -1, 0.75); setting(u + 1.1 + du, vb + 1.35 + 0.14, 1, 0.75)
                u += 2.2 + (2.4 if k % 2 == 0 else 0.4)                        # every other slot stays open: booths are about a third of the seats
            else:
                L_b = 2.4
                if H.add("banquette", *world(u + L_b / 2, vb), towards_wall, aisle=0.3, length=L_b):
                    for du in (-0.45, 0.45):
                        H.add("cube_ottoman", *world(u + L_b / 2 + du, vb - 1.0), towards_glass, aisle=0.1)
                u += L_b + 0.9
            k += 1
    chand = [{"x": round(world(u, S / 2)[0], 2), "y": round(world(u, S / 2)[1], 2), "z": 3.4} for u in
             [ENTRANCE + 2.0 + k * 5.0 for k in range(int(max(0, L - ENTRANCE - 3.0) / 5.0) + 1)]]
    # table settings: the caller puts them on every marble table (2 on a low table, 1-2 on a high one)
    return {"items": H.items, "chandeliers": chand, "settings": settings, "long_axis": "x" if long_x else "y"}


if __name__ == "__main__":
    import collections
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (22.0, 11.0)))
    p = layout(0, W, 0, D, 1, obstacles=[(W / 3 - 0.2, W / 3 + 0.2, D / 2 - 0.2, D / 2 + 0.2)], doors=[(0.0, D / 2)])
    print(dict(collections.Counter(e["cat"] for e in p["items"])), "chandeliers", len(p["chandeliers"]), "settings", len(p["settings"]), f"area {W * D:.0f} m2")
    g = [["." for _ in range(int(W * 2))] for _ in range(int(D * 2))]
    ch = {"banquette": "B", "marble_table_low": "t", "marble_table_high": "h", "marble_table_round": "o", "bar_stool": "s", "cube_ottoman": "q",
          "velvet_booth": "V", "mirror_column": "M", "timber_column": "T", "floor_ac": "A", "patio_heater": "H", "counter": "C"}
    for e in p["items"]:
        yy, xx = int(e["y"] * 2), int(e["x"] * 2)
        if 0 <= yy < len(g) and 0 <= xx < len(g[0]):
            g[yy][xx] = ch[e["cat"]]
    print("\n".join("".join(r) for r in g))
