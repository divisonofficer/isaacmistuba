"""Open steel roof TRUSSES across a hall (floor H ref: 'exposed ceiling trusses', industrial gave solid down-stand beams). Late pass (kit_lighting; ROOM_TRUSS_ROOMS = room-name prefixes, e.g. break-room_0/0; ROOM_TRUSS_PITCH=2.8 m).

For each listed room: one black steel truss every PITCH m across the room's SHORT span, hanging 0.5 m under the ceiling: two 5 cm chords (top at the ceiling, bottom 0.45 m below), a Warren zig-zag of 3 cm diagonals every 0.6 m and vertical hangers at the wall ends.
Stats: stats["trusses"] = count. Pair with architecture archetype 'truss_hall' (no beams, ducts kept).
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector


def apply(stats):
    pref = tuple(x for x in os.environ.get("ROOM_TRUSS_ROOMS", "").split(",") if x)
    if not pref:
        return 0
    from room_planner import proc_boutique_flagship as fl
    from room_planner import proc_assets as pa
    from room_planner import terrace_open as to
    import room_dressing as rd
    pitch = float(os.environ.get("ROOM_TRUSS_PITCH") or 2.8); hh = 0.45
    rgb = tuple(float(v) for v in (os.environ.get("ROOM_TRUSS_RGB") or "0.05,0.05,0.055").split(","))           # ROOM_TRUSS_RGB=0.92,0.92,0.9: white-painted trusses (H ref: a white exposed service ceiling)
    black = fl._flat(f"ir_truss_steel_{int(rgb[0] * 100)}", rgb, 0.45, 0.6 if max(rgb) < 0.3 else 0.0)
    n = 0
    for rname, parts in rd._rooms().items():
        if not rname.startswith(pref) or "floor" not in parts or "wall" not in parts:
            continue
        x0, x1, y0, y1, fz = to._bbox(parts["floor"]); wl = parts["wall"]
        zc = max((wl.matrix_world @ Vector(c)).z for c in wl.bound_box)
        along_x = (x1 - x0) >= (y1 - y0)                         # trusses run across the short span
        L = (x1 - x0) if along_x else (y1 - y0); S = (y1 - y0) if along_x else (x1 - x0)
        k_ = max(2, int((L - 1.0) // pitch) + 1)
        for k in range(k_):
            u = 0.5 + k * (L - 1.0) / (k_ - 1) if k_ > 1 else L / 2
            R0 = (0, 0, 0); prims = []
            zt, zb = zc - 0.03, zc - hh
            at = lambda v: ((x0 + u, y0 + v) if along_x else (x0 + v, y0 + u))
            sz_ = lambda along, thick, h: ((thick, along, h) if along_x else (along, thick, h))
            for z in (zt, zb):
                prims.append(("box", (*at(S / 2), z), sz_(S - 0.1, 0.05, 0.05), R0))
            nd = max(4, int(S / 0.6)) // 2 * 2
            for j in range(nd):                                   # Warren zig-zag: diagonals tilted in the truss plane
                v0 = 0.05 + j * (S - 0.1) / nd; v1 = v0 + (S - 0.1) / nd
                a_, b_ = (zt, zb) if j % 2 == 0 else (zb, zt)
                ln = math.hypot(v1 - v0, a_ - b_); ang = math.atan2(b_ - a_, v1 - v0)
                rot = (ang, 0, 0) if along_x else (0, -ang, 0)
                prims.append(("box", (*at((v0 + v1) / 2), (a_ + b_) / 2), sz_(ln, 0.03, 0.03), rot))
            for v in (0.05, S - 0.05):
                prims.append(("box", (*at(v), (zt + zb) / 2), sz_(0.04, 0.04, zt - zb) if False else ((0.04, 0.04, zt - zb)), R0))
            pa._prims(f"HallTruss({rname}|{k})", [(black, prims)])
            n += 1
    stats["trusses"] = n
    return n
