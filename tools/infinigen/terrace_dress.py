"""Terrace dressing (P2b r36 / r37: 'a fluted-wood slat wall on the bare white terrace walls; a soffit with downlights'). Hooked from kit_lighting, only when ROOM_TERRACE_DRESS=1; balcony rooms only.

  slat wall   on every INTERIOR side of the balcony (a side that is not on the building's outer edge) that has no door / window object within 0.8 m of its plane: vertical walnut-brown slats 3 cm wide, 2 cm deep, 5 cm pitch,
              from 0.15 m above the floor to 0.25 m under the ceiling, 1.5 cm off the wall; a dark backing plane behind them so the gaps read as shadow
  soffit      along the glass railing side: a white plaster soffit 0.55 m deep and 0.16 m high under the ceiling, with a row of warm recessed downlights (a disc + a 40 W spot each) every 0.9 m
Idempotent: TerraceDress(...) objects and their lights are removed first."""
from __future__ import annotations

import math
import os

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa
from room_planner import terrace_open as to


def apply(stats):
    for o in [o for o in bpy.data.objects if o.name.startswith(("TerraceDress(", "ir_td_"))]:
        bpy.data.objects.remove(o, do_unlink=True)
    for l in [l for l in bpy.data.lights if l.name.startswith("ir_td_")]:
        bpy.data.lights.remove(l)
    slat_m = pa._flat("ir_td_slat", (0.32, 0.18, 0.09), 0.55, wood=True); back = pa._flat("ir_td_back", (0.04, 0.03, 0.025), 0.9); plas = pa._flat("ir_td_soffit", (0.9, 0.89, 0.86), 0.7)
    warm = pa._flat("ir_td_lamp", (1.0, 0.8, 0.5), 0.4); wb = warm.node_tree.nodes["Principled BSDF"]; wb.inputs["Emission Color"].default_value = (1.0, 0.78, 0.45, 1); wb.inputs["Emission Strength"].default_value = 10.0
    ns = nl = 0
    for name, p in rd._rooms().items():
        if not name.startswith("balcony") or "floor" not in p or "wall" not in p:
            continue
        bb, fz, outer = to._sides(name)
        if bb is None:
            continue
        x0, x1, y0, y1 = bb; zc = max((p["wall"].matrix_world @ Vector(c)).z for c in p["wall"].bound_box)
        bm = bmesh.new(); kinds = []
        for side in ("W", "E", "S", "N"):
            if side in outer:
                continue
            along_y = side in ("W", "E")
            wp = {"W": x0, "E": x1, "S": y0, "N": y1}[side]
            busy = any(o.type == "MESH" and any(k in o.name for k in ("Window", "door", "Door")) and ((abs(o.matrix_world.translation.x - wp) < 0.8) if along_y else (abs(o.matrix_world.translation.y - wp) < 0.8)) and x0 - 0.5 < o.matrix_world.translation.x < x1 + 0.5 and y0 - 0.5 < o.matrix_world.translation.y < y1 + 0.5 for o in bpy.data.objects)
            if busy:
                continue
            L = (y1 - y0) if along_y else (x1 - x0); sgn = 1 if side in ("W", "S") else -1; zlo, zhi = fz + 0.15, zc - 0.25
            off = 0.015
            for k in range(int((L - 0.1) / 0.05)):
                u = (y0 if along_y else x0) + 0.05 + k * 0.05
                c = (wp + sgn * (off + 0.01), u, (zlo + zhi) / 2) if along_y else (u, wp + sgn * (off + 0.01), (zlo + zhi) / 2)
                r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=((0.02, 0.03, zhi - zlo) if along_y else (0.03, 0.02, zhi - zlo)), verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
                for f in {f for v in r["verts"] for f in v.link_faces}:
                    f.material_index = 0
            cb = ((wp + sgn * 0.008, (y0 + y1) / 2, (zlo + zhi) / 2), (0.006, L, zhi - zlo)) if along_y else (((x0 + x1) / 2, wp + sgn * 0.008, (zlo + zhi) / 2), (L, 0.006, zhi - zlo))
            r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=cb[1], verts=r["verts"]); bmesh.ops.translate(bm, vec=cb[0], verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = 1
            ns += 1
        if bm.verts:
            me = bpy.data.meshes.new("TerraceSlats"); bm.to_mesh(me); me.materials.append(slat_m); me.materials.append(back)
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"TerraceDress(slats {name})", me))
        bm.free()
        # soffit + downlights along the first outer (railing) side
        if outer:
            side = outer[0]; along_y = side in ("W", "E"); wp = {"W": x0, "E": x1, "S": y0, "N": y1}[side]; sgn = -1 if side in ("W", "S") else 1; sgn_in = -sgn
            L = (y1 - y0) if along_y else (x1 - x0); D = 0.55
            bm = bmesh.new(); c = (wp + sgn_in * D / 2, (y0 + y1) / 2, zc - 0.08) if along_y else ((x0 + x1) / 2, wp + sgn_in * D / 2, zc - 0.08)
            r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=((D, L - 0.1, 0.16) if along_y else (L - 0.1, D, 0.16)), verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
            me = bpy.data.meshes.new("TerraceSoffit"); bm.to_mesh(me); bm.free(); me.materials.append(plas)
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"TerraceDress(soffit {name})", me))
            bm = bmesh.new(); pts = []
            for k in range(max(2, int((L - 0.4) / 0.9))):
                u = (y0 if along_y else x0) + 0.4 + k * 0.9
                cc = (wp + sgn_in * D / 2, u, zc - 0.162) if along_y else (u, wp + sgn_in * D / 2, zc - 0.162); pts.append(cc)
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.045, radius2=0.045, depth=0.006); bmesh.ops.translate(bm, vec=cc, verts=r["verts"])
            me = bpy.data.meshes.new("TerraceLamps"); bm.to_mesh(me); bm.free(); me.materials.append(warm)
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"TerraceDress(lamps {name})", me))
            for q, cc in enumerate(pts):
                ld = bpy.data.lights.new(f"ir_td_spot_{name}_{q}", "SPOT"); ld.energy = 40.0; ld.spot_size = math.radians(90); ld.spot_blend = 0.5; ld.color = (1.0, 0.78, 0.5); ld.shadow_soft_size = 0.05
                lo = bpy.data.objects.new(f"ir_td_spot_{name}_{q}", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (cc[0], cc[1], cc[2] - 0.01); nl += 1
    stats["terrace_dress"] = {"slat_walls": ns, "downlights": nl}
    return ns + nl
