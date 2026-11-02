"""Skirting boards (review: floor C r23 SRF-01 'break-room / office walls are plain grey planes, no trim'). Hooked from kit_lighting after hung_lights, only when ROOM_BASEBOARD=1.

    from baseboard import apply; stats["baseboard"] = apply(stats)

Env: ROOM_BASEBOARD_PROFILE=1 (profiled board + top cap in 2.4 m lengths with joints), ROOM_BASEBOARD_RGB = r,g,b (default 0.9,0.88,0.84), ROOM_BASEBOARD_H = height in m (default 0.1).
For every room floor mesh: its boundary edges (edges with one face) are the wall foot; each edge gets a 1.6 cm strip standing on the floor, minus the spans of door openings and full-height
glass: meshes named 'door*' (the portal cutters door / door.00N), DoorCasingFactory, LiteDoorFactory and window meshes that start below 0.4 m.
"""
from __future__ import annotations

import math
import os

import bmesh
import bpy
from mathutils import Matrix, Vector

import room_dressing as rd
from room_planner import proc_assets as pa


def _blockers():
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        n = o.name
        if not (n == "door" or n.startswith("door.") or n.startswith("DoorCasingFactory") or n.startswith("LiteDoorFactory") or n == "window" or n.startswith("window.") or n.startswith("WindowFactory")):
            continue
        bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
        z0 = min(p.z for p in bb)
        out.append((min(p.x for p in bb) - 0.04, max(p.x for p in bb) + 0.04, min(p.y for p in bb) - 0.04, max(p.y for p in bb) + 0.04, z0, n.startswith(("window", "WindowFactory"))))
    return out


def _free_ranges(a, b, boxes, fz):
    """Parameter ranges of the segment a->b (2D) not inside any blocker box that reaches the floor (a window only when it starts below 0.4 m)."""
    d = b - a; L = d.length
    blocked = []
    for x0, x1, y0, y1, z0, is_win in boxes:
        if z0 - fz > (0.4 if is_win else 0.2):
            continue
        t0, t1 = 0.0, 1.0
        for (p, dd, lo, hi) in ((a.x, d.x, x0, x1), (a.y, d.y, y0, y1)):
            if abs(dd) < 1e-9:
                if p < lo or p > hi:
                    t0, t1 = 1.0, 0.0
                    break
            else:
                ta, tb = (lo - p) / dd, (hi - p) / dd
                t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
        if t0 < t1:
            blocked.append((t0, t1))
    blocked.sort(); free, cur = [], 0.0
    for t0, t1 in blocked:
        if t0 > cur:
            free.append((cur, t0))
        cur = max(cur, t1)
    if cur < 1.0:
        free.append((cur, 1.0))
    return [(s, e) for s, e in free if (e - s) * L > 0.12]


def apply(stats):
    if os.environ.get("ROOM_BASEBOARD") != "1":
        return 0
    rgb = tuple(float(v) for v in (os.environ.get("ROOM_BASEBOARD_RGB") or "0.9,0.88,0.84").split(","))
    H = float(os.environ.get("ROOM_BASEBOARD_H") or 0.1)
    mat = pa._flat("ir_late_baseboard", rgb, 0.55)
    boxes = _blockers(); done = 0; pieces = 0
    for name, parts in rd._rooms().items():
        fl = parts.get("floor")
        if fl is None:
            continue
        me = fl.data; mw = fl.matrix_world
        bm0 = bmesh.new(); bm0.from_mesh(me); bm0.edges.ensure_lookup_table()
        fz = max((mw @ v.co).z for v in bm0.verts)
        cen = sum((mw @ f.calc_center_median() for f in bm0.faces), Vector()) / max(1, len(bm0.faces))
        edges = [(mw @ e.verts[0].co, mw @ e.verts[1].co) for e in bm0.edges if len(e.link_faces) == 1 and abs((mw @ e.verts[0].co).z - fz) < 0.05]
        bm0.free()
        if not edges:
            continue
        bm = bmesh.new()
        for a, b in edges:
            a2, b2 = Vector((a.x, a.y)), Vector((b.x, b.y))
            for s, e in _free_ranges(a2, b2, boxes, fz):
                p0, p1 = a2.lerp(b2, s), a2.lerp(b2, e); ln = (p1 - p0).length; mid = (p0 + p1) / 2
                dirv = (p1 - p0).normalized(); inward = Vector((-dirv.y, dirv.x))
                if (Vector((cen.x, cen.y)) - mid).dot(inward) < 0:
                    inward = -inward
                if os.environ.get("ROOM_BASEBOARD_PROFILE") == "1":           # a profiled board in 2.4 m lengths: 12 mm board + a 20 x 14 mm top cap, a 3 mm joint between lengths (axis B manufacturing detail, user 10-23)
                    nseg = max(1, int(math.ceil(ln / 2.4))); sl = ln / nseg; rot = Matrix.Rotation(math.atan2(dirv.y, dirv.x), 3, "Z")
                    for k in range(nseg):
                        c0 = p0 + dirv * (sl * (k + 0.5))
                        for (th, hh, zc, off) in ((0.012, H - 0.014, fz + (H - 0.014) / 2, 0.006), (0.02, 0.014, fz + H - 0.007, 0.01)):
                            r = bmesh.ops.create_cube(bm, size=1.0)
                            bmesh.ops.scale(bm, vec=(sl - 0.003, th, hh), verts=r["verts"]); bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=rot, verts=r["verts"])
                            bmesh.ops.translate(bm, vec=(c0.x + inward.x * off, c0.y + inward.y * off, zc), verts=r["verts"])
                    pieces += nseg
                    continue
                r = bmesh.ops.create_cube(bm, size=1.0)
                bmesh.ops.scale(bm, vec=(ln, 0.016, H), verts=r["verts"])
                bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.atan2(dirv.y, dirv.x), 3, "Z"), verts=r["verts"])
                bmesh.ops.translate(bm, vec=(mid.x + inward.x * 0.008, mid.y + inward.y * 0.008, fz + H / 2), verts=r["verts"])
                pieces += 1
        om = bpy.data.meshes.new(f"Baseboard({name})"); bm.to_mesh(om); bm.free(); om.materials.append(mat)
        o = bpy.data.objects.new(f"BaseboardFactory({name}).spawn_asset(0)", om); bpy.context.scene.collection.objects.link(o)
        done += 1
    stats["baseboard"] = {"rooms": done, "pieces": pieces}
    return done
