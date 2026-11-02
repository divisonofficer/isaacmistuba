"""Plaster coffer ceiling with a cornice (S10 r11 SRF-01: 'the ceiling is one flat dark brown'). Hooked from kit_lighting after hung_lights, only when ROOM_COFFER_CEILING=1.

    from plaster_ceiling import apply; stats["coffer_ceiling"] = apply(stats)

Env: ROOM_COFFER_RGB = r,g,b of the plaster (default 0.86,0.82,0.74); ROOM_COFFER_PITCH = beam spacing (default 1.5 m); ROOM_COFFER_ROOMS = comma list of room prefixes (default all rooms >= 8 m2).
Per rectangular room: a cornice (0.09 x 0.09 m) round the top of the walls, beams (0.12 wide, 0.09 deep) in both directions under the ceiling, and a darker inset panel colour is the
room's own ceiling showing through, so the beams read as raised plaster.
"""
from __future__ import annotations

import os

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa


def apply(stats):
    if os.environ.get("ROOM_COFFER_CEILING") != "1":
        return 0
    rgb = tuple(float(v) for v in (os.environ.get("ROOM_COFFER_RGB") or "0.86,0.82,0.74").split(","))
    pitch = float(os.environ.get("ROOM_COFFER_PITCH") or 1.5)
    sel = [s.strip() for s in (os.environ.get("ROOM_COFFER_ROOMS") or "").split(",") if s.strip()]
    mat = pa._flat("ir_late_coffer_plaster", rgb, 0.8)
    done = 0
    for name, parts in rd._rooms().items():
        if "floor" not in parts or "wall" not in parts or (sel and not any(name.startswith(s) for s in sel)):
            continue
        fp = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]; wp = [parts["wall"].matrix_world @ Vector(c) for c in parts["wall"].bound_box]
        x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
        zc = max(p.z for p in wp)
        if (x1 - x0) * (y1 - y0) < 8.0:
            continue
        bm = bmesh.new()

        def box(cx, cy, cz, sx, sy, sz):
            r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"]); bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
        W, D = x1 - x0, y1 - y0; cxm, cym = (x0 + x1) / 2, (y0 + y1) / 2; c = 0.045
        box(cxm, y0 + c, zc - c, W, 0.09, 0.09); box(cxm, y1 - c, zc - c, W, 0.09, 0.09); box(x0 + c, cym, zc - c, 0.09, D, 0.09); box(x1 - c, cym, zc - c, 0.09, D, 0.09)   # cornice
        for k in range(1, max(1, int(W / pitch))):
            box(x0 + k * W / max(1, int(W / pitch)), cym, zc - 0.045, 0.12, D, 0.09)
        for k in range(1, max(1, int(D / pitch))):
            box(cxm, y0 + k * D / max(1, int(D / pitch)), zc - 0.045, W, 0.12, 0.09)
        me = bpy.data.meshes.new(f"CofferCeiling({name})"); bm.to_mesh(me); bm.free(); me.materials.append(mat)
        o = bpy.data.objects.new(f"CofferCeilingFactory({name}).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(o)
        done += 1
    stats["coffer_ceiling"] = done
    return done
