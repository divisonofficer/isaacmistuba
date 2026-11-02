"""Ceiling of the LP-cafe lounge (ROOM_MODE=lounge; hooked by kit_lighting's ROOM_MODE hook): a dark soffit box over the high-table zone with a ceiling AC cassette in it and recessed warm downlights,
plain cream ceiling elsewhere with a few recessed downlights. Rooms of type break-room / office / hallway only; the first (largest) room gets it.
"""
from __future__ import annotations

import math
import os

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
    dark = pa._flat("ir_lounge_soffit", (0.1, 0.075, 0.06), 0.7); grille = pa._flat("ir_lounge_grille", (0.85, 0.85, 0.83), 0.4)
    warm = pa._flat("ir_lounge_downlight", (1.0, 0.85, 0.6), 0.3); wb = warm.node_tree.nodes["Principled BSDF"]
    wb.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); wb.inputs["Emission Strength"].default_value = 9.0
    bm = bmesh.new(); mats = [dark, grille, warm]
    if os.environ.get("ROOM_LOUNGE_CHECKER") == "1":                                  # S29F refs: the soffit's underside is a black / charcoal checkerboard of 0.45 m blocks
        mats += [pa._flat("ir_lounge_chk_a", (0.025, 0.025, 0.028), 0.6), pa._flat("ir_lounge_chk_b", (0.13, 0.12, 0.115), 0.6)]

    def box(c, s, slot):
        r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=s, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = slot
    drop = 0.35; ulo, uhi = 0.6, min(L - 5.0, 8.5)
    box(loc((ulo + uhi) / 2, S / 2 - 0.4, zc - drop / 2), sz(uhi - ulo, S - 3.4, drop), 0)                       # the dark soffit over the table zone
    box(loc((ulo + uhi) / 2, S / 2 - 0.4, zc - drop - 0.02), sz(0.9, 0.9, 0.02), 1)                              # the AC cassette grille
    if len(mats) > 3:
        cs = 0.45; nu = int((uhi - ulo) / cs); nv = int((S - 3.4) / cs)
        for iu in range(nu):
            for iv in range(nv):
                box(loc(ulo + (iu + 0.5) * cs + ((uhi - ulo) - nu * cs) / 2, S / 2 - 0.4 - (S - 3.4) / 2 + (iv + 0.5) * cs + ((S - 3.4) - nv * cs) / 2, zc - drop - 0.004), sz(cs - 0.01, cs - 0.01, 0.008), 3 + (iu + iv) % 2)
    n_dl = 0
    for iu in range(int((uhi - ulo) / 1.4)):
        for iv in range(int((S - 3.4) / 1.4)):
            box(loc(ulo + 0.7 + iu * 1.4, 1.0 + iv * 1.4 + 0.2, zc - drop - 0.012), sz(0.1, 0.1, 0.012), 2); n_dl += 1
    me = bpy.data.meshes.new("LoungeCeiling"); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new("LoungeCeilingFactory(soffit).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(o)
    for k in range(3):
        ld = bpy.data.lights.new(f"ir_lounge_dl_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.5; ld.size_y = 1.5; ld.energy = 45.0; ld.color = (1.0, 0.82, 0.6)
        lo = bpy.data.objects.new(f"PointLampFactory(lounge).spawn_asset({k})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = loc(ulo + (k + 0.5) * (uhi - ulo) / 3, S / 2 - 0.4, zc - drop - 0.05); lo.rotation_euler = (math.pi, 0, 0)
    stats["lounge_ceiling"] = {"room": name, "downlights": n_dl}
    return 1
