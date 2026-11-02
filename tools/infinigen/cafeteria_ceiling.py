"""Ceiling of the university cafeteria (ROOM_MODE=cafeteria; hooked by kit_lighting's ROOM_MODE hook): a dark stepped soffit over the table hall (a 0.3 m drop leaving a 0.8 m cream margin round the walls),
recessed warm downlights on a 1.8 m grid, a dark fascia, and a warm cove strip along the soffit edge. The diamond pendants come from the layout (hung items).
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
    dark = pa._flat("ir_cafe_soffit", (0.1, 0.08, 0.07), 0.75); warm = pa._flat("ir_cafe_downlight", (1.0, 0.85, 0.6), 0.3); cove = pa._flat("ir_cafe_cove", (1.0, 0.75, 0.45), 0.3)
    for m, st in ((warm, 9.0), (cove, 6.0)):
        b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.78, 0.48, 1); b.inputs["Emission Strength"].default_value = st
    bm = bmesh.new(); mats = [dark, warm, cove]

    def box(c, s, slot):
        r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=s, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = slot
    m_ = 0.8; drop = 0.3
    sx0, sx1, sy0, sy1 = x0 + m_, x1 - m_, y0 + m_, y1 - m_
    box(((sx0 + sx1) / 2, (sy0 + sy1) / 2, zc - drop / 2), (sx1 - sx0, sy1 - sy0, drop), 0)
    box(((sx0 + sx1) / 2, sy0 - 0.02, zc - drop - 0.01), (sx1 - sx0 + 0.04, 0.04, 0.02), 2); box(((sx0 + sx1) / 2, sy1 + 0.02, zc - drop - 0.01), (sx1 - sx0 + 0.04, 0.04, 0.02), 2)
    box((sx0 - 0.02, (sy0 + sy1) / 2, zc - drop - 0.01), (0.04, sy1 - sy0 + 0.04, 0.02), 2); box((sx1 + 0.02, (sy0 + sy1) / 2, zc - drop - 0.01), (0.04, sy1 - sy0 + 0.04, 0.02), 2)
    n = 0
    nx, ny = max(1, int((sx1 - sx0) / 1.8)), max(1, int((sy1 - sy0) / 1.8))
    for ix in range(nx):
        for iy in range(ny):
            box((sx0 + (ix + 0.5) * (sx1 - sx0) / nx, sy0 + (iy + 0.5) * (sy1 - sy0) / ny, zc - drop - 0.012), (0.12, 0.12, 0.012), 1); n += 1
    me = bpy.data.meshes.new("CafeteriaCeiling"); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new("CafeteriaCeilingFactory(soffit).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(o)
    for k in range(4):
        ld = bpy.data.lights.new(f"ir_cafe_dl_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 2.0; ld.size_y = 2.0; ld.energy = 70.0; ld.color = (1.0, 0.84, 0.62)
        lo = bpy.data.objects.new(f"PointLampFactory(cafe).spawn_asset({k})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = (sx0 + (k + 0.5) * (sx1 - sx0) / 4, (sy0 + sy1) / 2, zc - drop - 0.05); lo.rotation_euler = (math.pi, 0, 0)
    stats["cafeteria_ceiling"] = {"room": name, "downlights": n}
    return 1
