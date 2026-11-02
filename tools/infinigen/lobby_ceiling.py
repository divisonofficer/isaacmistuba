"""Ceiling of the tall building lobby (ROOM_MODE=lobby): a continuous warm COVE (emissive strip + a ledge) round the top of all walls at 0.45 m under the slab, a long warm 'perforated' ceiling band
(dark panel with a grid of glowing dots) over the middle axis, a few recessed downlights, and soft area lights under the band. The largest room gets it.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa


def apply(stats):
    rooms = [(n, p) for n, p in rd._rooms().items() if "floor" in p and "wall" in p]
    if not rooms:
        return 0
    name, parts = max(rooms, key=lambda np_: np_[1]["floor"].dimensions.x * np_[1]["floor"].dimensions.y)
    fp = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]; wp = [parts["wall"].matrix_world @ Vector(c) for c in parts["wall"].bound_box]
    x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
    zc = max(p.z for p in wp)
    along_x = (x1 - x0) >= (y1 - y0); L = (x1 - x0) if along_x else (y1 - y0); S = (y1 - y0) if along_x else (x1 - x0)
    loc = lambda u, v, z: ((x0 + u, y0 + v, z) if along_x else (x0 + v, y0 + u, z))
    sz = lambda su, sv, sw: ((su, sv, sw) if along_x else (sv, su, sw))
    dark = pa._flat("ir_lobby_ceil_dark", (0.12, 0.09, 0.07), 0.6); gold = pa._flat("ir_lobby_ceil_gold", (0.55, 0.38, 0.18), 0.35, 0.9)
    warm = pa._flat("ir_lobby_cove", (1.0, 0.8, 0.5), 0.3); wb = warm.node_tree.nodes["Principled BSDF"]
    wb.inputs["Emission Color"].default_value = (1.0, 0.75, 0.42, 1); wb.inputs["Emission Strength"].default_value = 7.0
    dot = pa._flat("ir_lobby_dots", (1.0, 0.85, 0.55), 0.3); db = dot.node_tree.nodes["Principled BSDF"]
    db.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); db.inputs["Emission Strength"].default_value = 14.0
    bm = bmesh.new(); mats = [dark, gold, warm, dot]

    def box(c, s, slot):
        r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=s, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = slot
    zl = zc - 0.55                                                                   # the cove ledge
    for (u0, u1, v0, v1) in ((0.1, L - 0.1, 0.1, 0.35), (0.1, L - 0.1, S - 0.35, S - 0.1), (0.1, 0.35, 0.1, S - 0.1), (L - 0.35, L - 0.1, 0.1, S - 0.1)):
        box(loc((u0 + u1) / 2, (v0 + v1) / 2, zl), sz(u1 - u0, v1 - v0, 0.06), 0)
        iu, iv = ((u0 + u1) / 2, (v0 + v1) / 2)
        box(loc(iu, iv, zl + 0.05), sz(max(0.05, u1 - u0 - 0.06) if (u1 - u0) > (v1 - v0) else 0.04, max(0.05, v1 - v0 - 0.06) if (v1 - v0) >= (u1 - u0) else 0.04, 0.03), 2)      # the glowing strip
    ulo, uhi = 0.3 * L, L - 3.0; band_w = min(5.5, S * 0.3); zb = zc - 0.9
    box(loc((ulo + uhi) / 2, S / 2, zb), sz(uhi - ulo, band_w, 0.08), 1)               # the perforated gold band
    n_dot = 0
    for iu in range(int((uhi - ulo) / 0.5)):
        for iv in range(int(band_w / 0.5)):
            box(loc(ulo + 0.25 + iu * 0.5, S / 2 - band_w / 2 + 0.25 + iv * 0.5, zb - 0.045), sz(0.07, 0.07, 0.012), 3); n_dot += 1
    me = bpy.data.meshes.new("LobbyCeiling"); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new("LobbyCeilingFactory(cove).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(o)
    for k in range(5):
        ld = bpy.data.lights.new(f"ir_lobby_light_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 3.0; ld.size_y = band_w * 0.8; ld.energy = 900.0; ld.color = (1.0, 0.8, 0.55)
        lo = bpy.data.objects.new(f"PointLampFactory(lobby).spawn_asset({k})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = loc(ulo + (k + 0.5) * (uhi - ulo) / 5, S / 2, zb - 0.08); lo.rotation_euler = (math.pi, 0, 0)
    stats["lobby_ceiling"] = {"room": name, "dots": n_dot, "zc": round(zc, 2)}
    return 1
