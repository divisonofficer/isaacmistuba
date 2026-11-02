"""Cove lighting (P2b refs: 'cove light' in the living room and the master bedroom, ours: nothing but small surface domes).

Late pass (kit_lighting; ROOM_COVE_ROOMS = room-name prefixes, e.g. living-room,bedroom_0/2). For each listed room: a shallow dropped ceiling LIP (0.14 m wide, 0.1 m tall, in the wall colour) runs round the inside of the walls at the ceiling,
hiding a warm emissive strip (2700 K look) that washes the ceiling; the strip's emission is ROOM_COVE_EMIT (default 6). Stats: stats["cove"] = rooms done.
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector


def apply(stats):
    pref = tuple(x for x in os.environ.get("ROOM_COVE_ROOMS", "").split(",") if x)
    if not pref:
        return 0
    from room_planner import proc_boutique_flagship as fl
    from room_planner import terrace_open as to
    import room_dressing as rd
    emit = float(os.environ.get("ROOM_COVE_EMIT", "6"))
    glow = fl._flat("ir_cove_glow", (1.0, 0.8, 0.55), 0.3); b = glow.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.78, 0.5, 1); b.inputs["Emission Strength"].default_value = emit
    lip = fl._flat("ir_cove_lip", (0.93, 0.91, 0.87), 0.7)
    n = 0
    for rname, parts in rd._rooms().items():
        if not rname.startswith(pref) or "floor" not in parts or "wall" not in parts:
            continue
        x0, x1, y0, y1, fz = to._bbox(parts["floor"]); wl = parts["wall"]
        zc = max((wl.matrix_world @ Vector(c)).z for c in wl.bound_box)
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2; w, d = 0.14, 0.1
        zl = zc - d / 2
        lips, strips = [], []
        for yy, sg in ((y0, 1), (y1, -1)):                                       # lip 0.12 m off the wall, the glowing strip behind it (3 cm off the wall), both under the ceiling
            lips.append(("box", xm, yy + sg * 0.12, zl, x1 - x0 - 0.3, w, d)); strips.append(("box", xm, yy + sg * 0.03, zc - 0.03, x1 - x0 - 0.3, 0.03, 0.03))
        for xx, sg in ((x0, 1), (x1, -1)):
            lips.append(("box", xx + sg * 0.12, ym, zl, w, y1 - y0 - 0.3, d)); strips.append(("box", xx + sg * 0.03, ym, zc - 0.03, 0.03, y1 - y0 - 0.3, 0.03))
        fl.mesh_object(f"CoveLip({rname})", [(lip, lips), (glow, strips)], bevel=False)
        n += 1
    stats["cove"] = n
    return n
