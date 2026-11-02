"""Deterministic layout of the science-museum scene (docs/space_museum_design_proposal.md). No bpy. Room ~24 x 12 m (first scene).

    plan = layout(x0, x1, y0, y1, seed, obstacles=(), doors=())    -> {"items": [{cat, x, y, yaw, lift?, direct?, hang?}], "rotunda": {"cx", "cy", "R"}}

Frame: u along the long axis from the rotunda end. The ROTUNDA (octagon, circumradius R = min(L, S)/2 - 0.35, built by museum_shell) fills the first 2R m; its centre
holds the circular floor opening: a marble parapet ring (RotundaRail, R 1.9 m), the lit scale ring below (GlowRing, flat on the floor inside the ring) and the pendulum hung
from the dome crown (`hang`, z given by the caller). Beyond the rotunda: an exhibit room (element wall on the far short wall with the nebula wall panel beside it and
3 marble benches facing it) and a video room (3 lit nebula pictures + the earth monitor on a side wall, 3 benches). (x, y) = footprint centre, yaw = front direction (+X).
"""
from __future__ import annotations

import math

from room_planner import rooftop_layout as rl

def rotunda_radius(L, S):
    """Circumradius of the octagon: fills the short side but at most 36 % of the long side, so a squarish room keeps a strip for the exhibit / video rooms (museum r2: a 17 x 17 m
    room let the rotunda take everything)."""
    return max(3.2, min(S / 2 - 0.35, L * 0.36))


SIZE = {"rail_ring": (4.2, 4.2), "glow_ring": (3.6, 3.6), "pendulum": (0.4, 0.4), "element_wall": (0.25, 5.0), "nebula_panel": (0.1, 3.3), "marble_bench": (0.5, 1.6),
        "pic_blue": (0.08, 0.7), "pic_ring": (0.08, 0.7), "pic_earth": (0.08, 1.1)}


class _H(rl._Hall):
    def add(self, cat, cx, cy, yaw, aisle=0.2, edge=0.1, **extra):
        d0, l0 = SIZE[cat]
        b = self.box(cx, cy, yaw, d0, l0)
        if not self.free(b, aisle, edge):
            return False
        self.occ.append(b)
        self.items.append({"cat": cat, "x": round(cx, 3), "y": round(cy, 3), "yaw": round(yaw, 4), **extra})
        return True


def layout(x0, x1, y0, y1, seed=0, obstacles=(), doors=()):
    H = _H(x0, x1, y0, y1, obstacles, [])
    W, D = x1 - x0, y1 - y0
    long_x = W >= D
    L, S = (W, D) if long_x else (D, W)
    world = (lambda u, v: (x0 + u, y0 + v)) if long_x else (lambda u, v: (x0 + v, y0 + u))
    face = lambda nu, nv: math.atan2(*((nv, nu) if long_x else (nu, nv)))
    R = rotunda_radius(L, S)
    cu, cv = R + 0.35, S / 2
    cx, cy = world(cu, cv)
    # rotunda centre: parapet ring (kept clear), lit ring, pendulum (hung from the crown by the caller)
    H.items.append({"cat": "rail_ring", "x": round(cx, 3), "y": round(cy, 3), "yaw": 0.0, "direct": True})
    H.items.append({"cat": "glow_ring", "x": round(cx, 3), "y": round(cy, 3), "yaw": 0.0, "direct": True, "lift": 0.01})
    H.items.append({"cat": "pendulum", "x": round(cx, 3), "y": round(cy, 3), "yaw": 0.0, "direct": True, "hang": True})
    H.occ.append(H.box(cx, cy, 0.0, 4.4, 4.4))
    # exhibit room (elements) beyond the rotunda: element wall on the far short wall, nebula panel on the next wall, benches facing the wall
    u_wall = L - 0.3
    H.add("element_wall", *world(u_wall, S * 0.36), face(-1, 0), aisle=0.05, edge=0.0)
    H.add("nebula_panel", *world(u_wall, S * 0.36 + 4.3), face(-1, 0), aisle=0.05, edge=0.0)
    for k, dv in enumerate((-1.6, 0.0, 1.6)):
        H.add("marble_bench", *world(u_wall - 3.4, S * 0.36 + dv * 1.3), face(1, 0), aisle=0.2)
    # video room strip beyond the rotunda: lit pictures on the side wall (v = S), the earth monitor on the opposite side wall, benches facing the pictures
    for k, kind in enumerate(("pic_blue", "pic_ring", "pic_blue")):
        H.add(kind, *world(L - 1.4 - k * 1.5, S - 0.12), face(0, -1), aisle=0.05, edge=0.0, lift=1.2)
    H.add("pic_earth", *world(L - 2.6, 0.22), face(0, 1), aisle=0.05, edge=0.0, lift=1.1)
    for k in range(2):
        H.add("marble_bench", *world(L - 1.9 - k * 2.2, S - 2.9), face(0, 1), aisle=0.2)
    return {"items": H.items, "rotunda": {"cx": round(cx, 3), "cy": round(cy, 3), "R": round(R, 2)}, "long_axis": "x" if long_x else "y"}


if __name__ == "__main__":
    import collections
    import sys
    W, D = (float(a) for a in (sys.argv[1:3] or (24.0, 12.0)))
    p = layout(0, W, 0, D, 1)
    print(dict(collections.Counter(e["cat"] for e in p["items"])), p["rotunda"], f"area {W * D:.0f} m2")
