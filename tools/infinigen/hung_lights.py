"""Ceiling lights hung off the ceiling (review 10-19: 'ceiling fixtures flush/flat light', 19 of 23 scenes). Hooked from kit_lighting after env_windows, only when
ROOM_HUNG_LIGHTS=<drop in m> (try 0.7).

    from hung_lights import apply; stats["hung_lights"] = apply(stats)

Env: ROOM_HUNG_STYLE = bar (default, linear suspended LED bar) | dome (white enamel dome) | globe (opal globe); ROOM_HUNG_ROOMS = comma list of room-name prefixes / types (default
every room with a ceiling and >= 8 m2); ROOM_HUNG_PITCH = grid pitch in m (default 2.8); ROOM_HUNG_W = watts per light (default 60).
For every selected room: pendants on a grid over the room's own floor (a down-ray against that floor mesh decides; L-shaped plans stay right), each with two cords (or one),
an emissive body, and an AREA light just below it; the room's flush ir_led_* area lights are removed so the light is not doubled.
"""
from __future__ import annotations

import math
import os

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa


def _mesh(name, groups):
    bm = bmesh.new()
    mats = []
    for mat, prims in groups:
        mats.append(mat)
    me = bpy.data.meshes.new(name)
    for slot, (mat, prims) in enumerate(groups):
        for p in prims:
            if p[0] == "box":
                _, (cx, cy, cz), (sx, sy, sz) = p
                r = bmesh.ops.create_cube(bm, size=1.0)
                bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"]); bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
            elif p[0] == "cyl":
                _, (x0, y0, z0), (z1,), rad = p
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=rad, radius2=rad, depth=abs(z1 - z0))
                bmesh.ops.translate(bm, vec=(x0, y0, (z0 + z1) / 2), verts=r["verts"])
            else:                                                  # ("sph", (x, y, z), radius, (sx, sy, sz))
                _, (cx, cy, cz), rad, sc = p
                r = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rad)
                bmesh.ops.scale(bm, vec=sc, verts=r["verts"]); bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot
    bm.to_mesh(me); bm.free()
    for mat in mats:
        me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _emit(name, rgb, strength):
    m = pa._flat(name, rgb, 0.4)
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


def apply(stats):
    drop = float(os.environ.get("ROOM_HUNG_LIGHTS") or 0.0)
    if drop <= 0.0:
        return 0
    style = os.environ.get("ROOM_HUNG_STYLE") or "bar"
    sel = [s.strip() for s in (os.environ.get("ROOM_HUNG_ROOMS") or "").split(",") if s.strip()]
    pitch = float(os.environ.get("ROOM_HUNG_PITCH") or 2.8); watts = float(os.environ.get("ROOM_HUNG_W") or 60.0)
    black = pa._flat("ir_hung_black", (0.04, 0.04, 0.045), 0.45, 0.7); cord = pa._flat("ir_hung_cord", (0.5, 0.5, 0.52), 0.4, 1.0)
    glow = _emit("ir_hung_glow", (1.0, 0.93, 0.8), 9.0); dome = pa._flat("ir_hung_dome", (0.93, 0.93, 0.9), 0.3)
    dg = bpy.context.evaluated_depsgraph_get(); total = 0
    for name, parts in rd._rooms().items():
        if "floor" not in parts or "wall" not in parts:
            continue
        if sel and not any(name.startswith(s) or s in name for s in sel):
            continue
        fl, ce = parts["floor"], parts.get("ceiling") or parts["wall"]
        fp = [fl.matrix_world @ Vector(c) for c in fl.bound_box]; cp = [ce.matrix_world @ Vector(c) for c in ce.bound_box]
        x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
        fz = max(p.z for p in fp); zc = min(p.z for p in cp) if parts.get("ceiling") else max(p.z for p in cp)     # the wall top when the room has no ceiling mesh
        if (x1 - x0) * (y1 - y0) < 8.0 or zc - fz < 2.5:
            continue
        inv = fl.matrix_world.inverted(); n_room = 0
        nx, ny = max(1, int((x1 - x0 - 1.0) / pitch)), max(1, int((y1 - y0 - 1.0) / pitch))
        for ix in range(nx):
            for iy in range(ny):
                x = x0 + (ix + 0.5) * (x1 - x0) / nx; y = y0 + (iy + 0.5) * (y1 - y0) / ny
                hit = fl.ray_cast(inv @ Vector((x, y, zc - 0.05)), Vector((0, 0, -1)))[0]
                if not hit:
                    continue
                zb = max(zc - drop, fz + 2.2)                              # never below head height
                up = zc - zb                                               # cords run from the body up to the ceiling (relative z)
                if style == "dome":
                    parts_ = [(dome, [("sph", (0, 0, 0), 0.22, (1, 1, 0.55))]), (glow, [("sph", (0, 0, -0.06), 0.15, (1, 1, 0.5))]), (cord, [("cyl", (0, 0, 0.12), (up,), 0.004)])]
                elif style == "globe":
                    parts_ = [(glow, [("sph", (0, 0, 0), 0.17, (1, 1, 1))]), (cord, [("cyl", (0, 0, 0.17), (up,), 0.004)])]
                else:
                    parts_ = [(black, [("box", (0, 0, 0), (1.2, 0.08, 0.06))]), (glow, [("box", (0, 0, -0.034), (1.1, 0.05, 0.006))]),
                              (cord, [("cyl", (sx * 0.5, 0, 0.03), (up,), 0.003) for sx in (-1, 1)])]
                o = _mesh(f"HungLightFactory({name}).spawn_asset({n_room})", parts_)
                o.location = (x, y, zb)
                ld = bpy.data.lights.new(f"ir_hung_{name}_{n_room}", "AREA"); ld.shape = "SQUARE"; ld.size = 0.9; ld.energy = watts; ld.color = (1.0, 0.92, 0.78)
                lo = bpy.data.objects.new(f"PointLampFactory(hung).spawn_asset({name}_{n_room})", ld); bpy.context.scene.collection.objects.link(lo)
                lo.location = (x, y, zb - 0.08); lo.rotation_euler = (math.pi, 0, 0)
                n_room += 1
        if n_room:                                                           # the flush fixtures' area lights of this room: removed, so the light is not doubled
            for o in list(bpy.data.objects):
                t = o.matrix_world.translation
                if o.type == "LIGHT" and o.name.startswith("ir_led") and x0 <= t.x <= x1 and y0 <= t.y <= y1 and t.z > zc - 0.4:
                    bpy.data.objects.remove(o, do_unlink=True)
        total += n_room
    stats["hung_lights"] = total
    return total
