"""Ceiling of the underground parking level (ROOM_MODE=parking; hooked by kit_lighting's ROOM_MODE hook): the concrete slab with cross beams on the column lines (every 7.8 m), two grey ventilation ducts
and a pair of red / grey pipes along the long axis, and rows of cool-white LED tubes (1.2 m, emissive + an area light each) along both sides of every aisle. Existing ceiling fixtures are removed.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

import room_dressing as rd
from room_planner import proc_assets as pa

BAY_W, BAY_D, AISLE, BAND = 2.6, 5.0, 6.0, 16.0


def apply(stats):
    rooms = [(n, p) for n, p in rd._rooms().items() if "floor" in p and "wall" in p]
    if not rooms:
        return 0
    name, parts = max(rooms, key=lambda np_: np_[1]["floor"].dimensions.x * np_[1]["floor"].dimensions.y)
    fp = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]; wp = [parts["wall"].matrix_world @ Vector(c) for c in parts["wall"].bound_box]
    x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
    fz, zc = max(p.z for p in fp), max(p.z for p in wp)
    along_x = (x1 - x0) >= (y1 - y0); L = (x1 - x0) if along_x else (y1 - y0); S = (y1 - y0) if along_x else (x1 - x0)
    loc = lambda u, v, z: ((x0 + u, y0 + v, z) if along_x else (x0 + v, y0 + u, z))
    sz = lambda su, sv, sw: ((su, sv, sw) if along_x else (sv, su, sw))
    for o in list(bpy.data.objects):
        t = o.matrix_world.translation
        # the warehouse template's hung high-bay lamps + cords (r1: grey slabs floating at 1.4-1.5 m with two wires each) and pallets
        if o.name.split("(")[0] in ("HighBayLampFactory", "HighBayCordFactory", "PalletFactory") and x0 - 0.2 <= t.x <= x1 + 0.2 and y0 - 0.2 <= t.y <= y1 + 0.2:
            bpy.data.objects.remove(o, do_unlink=True); continue
        if o.type == "LIGHT" and x0 - 0.2 <= t.x <= x1 + 0.2 and y0 - 0.2 <= t.y <= y1 + 0.2 and t.z > fz + 2.0:
            bpy.data.objects.remove(o, do_unlink=True)
    conc = pa._flat("ir_pk_beam", (0.55, 0.55, 0.53), 0.9); duct = pa._flat("ir_pk_duct", (0.6, 0.62, 0.64), 0.4, 0.8); red = pa._flat("ir_pk_pipe_red", (0.75, 0.1, 0.08), 0.5, 0.3)
    grey = pa._flat("ir_pk_pipe_grey", (0.45, 0.46, 0.48), 0.5, 0.5)
    tube = pa._flat("ir_pk_tube", (0.85, 0.92, 1.0), 0.3); tb = tube.node_tree.nodes["Principled BSDF"]
    tb.inputs["Emission Color"].default_value = (0.82, 0.92, 1.0, 1); tb.inputs["Emission Strength"].default_value = 18.0
    bm = bmesh.new(); mats = [conc, duct, red, grey, tube]

    def box(c, s, slot):
        r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=s, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = slot

    def pipe(u0_, u1_, v, z, rad, slot):
        r = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=rad, radius2=rad, depth=u1_ - u0_)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y" if along_x else "X"), verts=r["verts"])
        bmesh.ops.translate(bm, vec=loc((u0_ + u1_) / 2, v, z), verts=r["verts"])
        for f in {f for v_ in r["verts"] for f in v_.link_faces}:
            f.material_index = slot
    n_bays = max(1, int((L - 1.0) // BAY_W)); u_start = (L - n_bays * BAY_W) / 2
    for k in range(0, n_bays + 1, 3):                                      # beams on the column lines
        box(loc(u_start + k * BAY_W, S / 2, zc - 0.25), sz(0.5, S, 0.5), 0)
    bands = max(1, int((S - 0.3) // BAND)) if S >= BAND else 1
    n_t = 0
    for b in range(bands):
        v0 = 0.25 + b * BAND; av = v0 + BAY_D + AISLE / 2
        box(loc(L / 2, av + 2.9, zc - 0.55), sz(L - 0.6, 0.6, 0.3), 1)                                 # a supply duct along each side of the aisle
        box(loc(L / 2, av - 2.9, zc - 0.55), sz(L - 0.6, 0.6, 0.3), 1)
        pipe(0.3, L - 0.3, av + 1.0, zc - 0.7, 0.08, 2); pipe(0.3, L - 0.3, av + 1.3, zc - 0.65, 0.06, 3)
        for dv in (-1.6, 1.6):
            u = 1.5
            while u < L - 1.0:
                box(loc(u, av + dv, zc - 0.82), sz(1.2, 0.07, 0.05), 4)
                ld = bpy.data.lights.new(f"ir_pk_tube_{b}_{n_t}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.2; ld.size_y = 0.5; ld.energy = 40.0; ld.color = (0.85, 0.93, 1.0)
                lo = bpy.data.objects.new(f"PointLampFactory(pk).spawn_asset({b}_{n_t})", ld); bpy.context.scene.collection.objects.link(lo)
                lo.location = loc(u, av + dv, zc - 0.88); lo.rotation_euler = (math.pi, 0, 0 if along_x else math.pi / 2); n_t += 1
                u += 3.0
    # large double-sided exit signs hung over every aisle (user 2026-10-20: 'exit signs on the ceiling'): black housing, two green emissive faces with a white arrow bar, two rods to the slab
    hous = pa._flat("ir_pk_exit_housing", (0.05, 0.05, 0.055), 0.5); grn = pa._flat("ir_pk_exit_green", (0.1, 0.8, 0.3), 0.4); wht = pa._flat("ir_pk_exit_white", (0.95, 0.98, 0.95), 0.4)
    for m_, rgb, st in ((grn, (0.1, 0.9, 0.35), 9.0), (wht, (0.95, 0.98, 0.95), 7.0)):
        bs = m_.node_tree.nodes["Principled BSDF"]; bs.inputs["Emission Color"].default_value = (*rgb, 1); bs.inputs["Emission Strength"].default_value = st
    mats += [hous, grn, wht]; s_h, s_g, s_w = len(mats) - 3, len(mats) - 2, len(mats) - 1
    n_sign = 0
    for b in range(bands):
        av = 0.25 + b * BAND + BAY_D + AISLE / 2
        us = sorted({3.0, L - 3.0, *[u_ for u_ in (3.0 + 16.0 * k_ for k_ in range(1, int(L // 16) + 1)) if 6.0 < u_ < L - 6.0]})
        for u_ in us:
            zs = zc - 0.75
            box(loc(u_, av, zs), sz(0.09, 0.78, 0.3), s_h)                                       # housing
            for sg in (1, -1):
                box(loc(u_ + sg * 0.05, av, zs), sz(0.012, 0.7, 0.22), s_g)                       # green face
                box(loc(u_ + sg * 0.058, av, zs), sz(0.006, 0.34, 0.045), s_w)                   # white bar
            for dv in (-0.3, 0.3):
                box(loc(u_, av + dv, (zs + 0.15 + zc) / 2), sz(0.015, 0.015, zc - zs - 0.15), 3)  # rods
            n_sign += 1
    me = bpy.data.meshes.new("ParkingCeiling"); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new("ParkingCeilingFactory(slab).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(o)
    stats["parking_ceiling"] = {"room": name, "tubes": n_t, "exit_signs": n_sign}
    return 1
