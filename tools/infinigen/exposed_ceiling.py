"""Exposed industrial ceiling (O3 urban-dirty office: raw cast-concrete slab, downstand beams, bare steel services; O4 / O5 painted variants). Hooked from kit_lighting after the timber ceiling, only when ROOM_EXPOSED_CEILING=1.

    from exposed_ceiling import apply; stats["exposed_ceiling"] = apply(stats)

Env: ROOM_EXPOSED_CEILING=1
     ROOM_EXPOSED_CEILING_ROOMS=break-room,office,meeting-room,hallway   ceiling-name prefixes that get it (empty = every ceiling)
     ROOM_EXPOSED_CEILING_RGB=0.9,0.9,0.88   paint everything (slab, beams, pipes, ducts) in this colour instead of bare concrete / bare metal (O5: white-painted)
     ROOM_EXPOSED_BEAM_SPACING=5.0           primary downstand beams across the short side every this many metres (0.3 wide x 0.38 deep); secondary beams along the long axis for rooms wider than 8 m
     ROOM_EXPOSED_LIGHTS=1                   hang linear LED tubes (the suspended grid's panels are removed, so the room needs light): rows every 3.5 m, 1.2 m tubes every 2.4 m, each with an area light
For each matching ceiling: removes the suspended grid / tile / cassette fixtures above 2.2 m in the room; replaces the slab material by a stained, uneven concrete with formwork board marks (2.4 x 0.6 m);
adds the beams; runs bare steel services along the long axis on threaded-rod hangers: a galvanised sprinkler main with red sprinkler heads every 3 m, a raw steel pipe, a copper line, one big round spiral duct
(ribbed) and a black cable tray. Metal stays unpainted (metallic, like ROOM_LAB_BARE_METAL)."""
from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa
from lab_ceiling import REMOVE, _bare, _emit


def _obj(name, mat_prims):
    """Like lab_ceiling._obj, plus cylinders on the vertical axis (ax = 2): ("box", centre, size) | ("cyl", centre, radius, length, ax)."""
    import bmesh
    from mathutils import Matrix
    bm = bmesh.new(); mats = []
    for slot, (mat, prims) in enumerate(mat_prims):
        mats.append(mat)
        for p in prims:
            if p[0] == "box":
                _, c, sz = p
                r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=sz, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
            else:
                _, c, rad, ln, ax = p
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=int(os.environ.get("ROOM_DUCT_SEGS") or 12), radius1=rad, radius2=rad, depth=ln)
                if ax != 2:
                    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y" if ax == 0 else "X"), verts=r["verts"])
                bmesh.ops.translate(bm, vec=c, verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    if int(os.environ.get("ROOM_DUCT_SEGS") or 12) > 12:                                                    # O3 / O4 / O5 reviews: 8-12-sided prism ducts with facet bands -> 40 segments, smooth shading, an edge split keeps the beams and trays crisp
        for p_ in me.polygons:
            p_.use_smooth = True
        md = o.modifiers.new("ir_duct_split", "EDGE_SPLIT"); md.split_angle = 0.61; md.use_edge_angle = True; md.use_edge_sharp = False
    return o


def _concrete(src, paint):
    m = src.copy(); m.name = src.name + ".exposed"
    nt = m.node_tree; N, Lk = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        N.clear(); b = N.new("ShaderNodeBsdfPrincipled"); out = N.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    if paint:
        b.inputs["Base Color"].default_value = (*paint, 1); b.inputs["Roughness"].default_value = 0.85
        return m
    geo = N.new("ShaderNodeNewGeometry"); nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 0.8; nz.inputs["Detail"].default_value = 9.0
    nz2 = N.new("ShaderNodeTexNoise"); nz2.inputs["Scale"].default_value = 6.0; nz2.inputs["Detail"].default_value = 6.0
    ramp = N.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].position = 0.3; ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[0].color = (0.2, 0.2, 0.205, 1); ramp.color_ramp.elements[1].color = (0.42, 0.415, 0.4, 1)
    br = N.new("ShaderNodeTexBrick"); br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 2.4; br.inputs["Row Height"].default_value = 0.6; br.inputs["Mortar Size"].default_value = 0.006
    br.inputs["Color1"].default_value = (1, 1, 1, 1); br.inputs["Color2"].default_value = (0.9, 0.9, 0.9, 1); br.inputs["Mortar"].default_value = (0.35, 0.35, 0.35, 1)
    mixc = N.new("ShaderNodeMix"); mixc.data_type = "RGBA"; mixc.blend_type = "MULTIPLY"; mixc.inputs[0].default_value = 1.0
    stain = N.new("ShaderNodeMix"); stain.data_type = "RGBA"; stain.blend_type = "MULTIPLY"; stain.inputs[7].default_value = (0.55, 0.52, 0.48, 1)
    for n_ in (nz, nz2, br):
        Lk.new(geo.outputs["Position"], n_.inputs["Vector"])
    Lk.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    Lk.new(ramp.outputs["Color"], mixc.inputs[6]); Lk.new(br.outputs["Color"], mixc.inputs[7])
    Lk.new(nz2.outputs["Fac"], stain.inputs[0]); Lk.new(mixc.outputs[2], stain.inputs[6])                          # patchy darker stains
    Lk.new(stain.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.88
    bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.25; Lk.new(nz2.outputs["Fac"], bump.inputs["Height"]); Lk.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def apply(stats):
    if os.environ.get("ROOM_EXPOSED_CEILING") != "1":
        return 0
    only = tuple(x.strip() for x in (os.environ.get("ROOM_EXPOSED_CEILING_ROOMS") or "").split(",") if x.strip())
    paint = tuple(float(v) for v in os.environ["ROOM_EXPOSED_CEILING_RGB"].split(",")) if os.environ.get("ROOM_EXPOSED_CEILING_RGB") else None
    spacing = float(os.environ.get("ROOM_EXPOSED_BEAM_SPACING") or 5.0); lights_on = os.environ.get("ROOM_EXPOSED_LIGHTS", "1") != "0"
    rng = random.Random(23)
    if paint:
        galv = pa._flat("ir_ex_paint_pipe", paint, 0.6); steel = galv; copper = galv; duct = galv
    else:
        galv = _bare("ir_ex_galv", (0.7, 0.72, 0.74), 0.35, 0.08); steel = _bare("ir_ex_steel", (0.33, 0.31, 0.29), 0.45, 0.1)
        copper = _bare("ir_ex_copper", (0.72, 0.42, 0.28), 0.3, 0.05); duct = _bare("ir_ex_duct", (0.62, 0.64, 0.66), 0.4, 0.06)
    red = pa._flat("ir_ex_sprinkler", (0.8, 0.05, 0.04), 0.5); blk = pa._flat("ir_ex_tray", (0.03, 0.03, 0.033), 0.5, 0.0); tube = _emit("ir_ex_tube", (1.0, 0.93, 0.78), 30.0)
    cmat, n_room, n_rm = {}, 0, 0
    for c in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".ceiling") and (not only or o.name.startswith(only))]:
        pts = [c.matrix_world @ Vector(v) for v in c.bound_box]
        x0, x1, y0, y1, zc = min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts)
        alx = (x1 - x0) >= (y1 - y0); L, Wd = ((x1 - x0), (y1 - y0)) if alx else ((y1 - y0), (x1 - x0))
        if L < 3.0 or Wd < 1.5:
            continue
        loc = (lambda u, v, z: Vector((x0 + u, y0 + v, z))) if alx else (lambda u, v, z: Vector((x0 + v, y0 + u, z)))
        sz = (lambda a, b, h: (a, b, h)) if alx else (lambda a, b, h: (b, a, h))                 # box size in world axes for a (along u) x (across v) x (height) footprint
        for o in list(bpy.data.objects):                                                       # the suspended grid goes
            if o.type == "MESH" and o.name.split("(")[0] in REMOVE and x0 - 0.2 < o.matrix_world.translation.x < x1 + 0.2 and y0 - 0.2 < o.matrix_world.translation.y < y1 + 0.2 and \
                    max((o.matrix_world @ Vector(v)).z for v in o.bound_box) > 2.2:
                bpy.data.objects.remove(o, do_unlink=True); n_rm += 1
        for sl in c.material_slots:
            m0 = sl.material
            if m0 is not None and m0.use_nodes:
                if m0.name not in cmat:
                    cmat[m0.name] = _concrete(m0, paint)
                sl.material = cmat[m0.name]
        slab = next(iter(cmat.values()), None)
        parts_c, n_beam = [], 0
        nb = max(1, int(round(L / spacing)))
        for k in range(nb):                                                                    # primary beams across the short side, 0.3 wide x 0.38 deep
            u = L * (k + 0.5) / nb
            parts_c.append(("box", loc(u, Wd / 2, zc - 0.19), sz(0.3, Wd - 0.02, 0.38))); n_beam += 1
        if Wd > 8.0:
            for k in range(max(1, int(Wd / 6.0))):                                             # secondary beams along the long axis, 0.25 x 0.3
                v = Wd * (k + 1) / (max(1, int(Wd / 6.0)) + 1)
                parts_c.append(("box", loc(L / 2, v, zc - 0.15), sz(L - 0.02, 0.25, 0.3))); n_beam += 1
        if slab is not None and parts_c:
            _obj(f"ExposedBeams({c.name})", [(slab, parts_c)])
        # services along the long axis
        lines = [("galv", 0.045, galv), ("steel", 0.07, steel), ("copper", 0.022, copper)]
        pipes, rods, heads, ductp, rings, tray, tparts = [], [], [], [], [], [], []
        vs = sorted(rng.sample([Wd * f for f in (0.18, 0.3, 0.42, 0.58, 0.7, 0.82)], min(len(lines) + 2, 6)))
        for idx, (nm, rad, mat) in enumerate(lines):
            v = vs[idx]; z = zc - 0.42 - 0.12 * idx - (0.19 if (idx != 0 and Wd > 8.0) else 0.0)
            pipes.append((mat, ("cyl", loc(L / 2, v, z), rad, L - 0.3, 0 if alx else 1)))
            for u in [1.2 + k * 2.4 for k in range(int((L - 1.5) / 2.4) + 1)]:
                rods.append(("cyl", loc(u, v, (zc + z) / 2), 0.006, zc - z, 2))
            if nm == "galv":
                for u in [1.5 + k * 3.0 for k in range(int((L - 2.0) / 3.0) + 1)]:
                    heads.append(("cyl", loc(u, v, z - rad - 0.04), 0.016, 0.08, 2))
        v = vs[len(lines)]; z = zc - 0.62; dr = 0.24                                           # the big spiral duct
        ductp.append(("cyl", loc(L / 2, v, z), dr, L - 0.6, 0 if alx else 1))
        for u in [0.5 + k * 0.4 for k in range(int((L - 1.2) / 0.4))]:
            rings.append(("cyl", loc(u, v, z), dr * 1.03, 0.02, 0 if alx else 1))
        for u in [1.2 + k * 2.4 for k in range(int((L - 1.5) / 2.4) + 1)]:
            rods.append(("cyl", loc(u, v - dr * 0.9, (zc + z) / 2), 0.007, zc - z, 2)); rods.append(("cyl", loc(u, v + dr * 0.9, (zc + z) / 2), 0.007, zc - z, 2))
        v = vs[len(lines) + 1]; z = zc - 0.3                                                   # black cable tray: a base and two side rails, with a few cables
        tparts += [("box", loc(L / 2, v, z), sz(L - 0.4, 0.3, 0.02)), ("box", loc(L / 2, v - 0.15, z + 0.03), sz(L - 0.4, 0.015, 0.06)), ("box", loc(L / 2, v + 0.15, z + 0.03), sz(L - 0.4, 0.015, 0.06))]
        for u in [1.0 + k * 2.0 for k in range(int((L - 1.5) / 2.0) + 1)]:
            rods.append(("cyl", loc(u, v - 0.15, (zc + z) / 2), 0.005, zc - z, 2)); rods.append(("cyl", loc(u, v + 0.15, (zc + z) / 2), 0.005, zc - z, 2))
        mats = {}
        for mat, prim in pipes:
            mats.setdefault(mat.name, (mat, []))[1].append(prim)
        groups = list(mats.values()) + [(duct, ductp + rings), (galv if not paint else galv, rods), (red, heads), (blk, tparts)]
        _obj(f"ExposedServices({c.name})", groups)
        n_tube = 0
        if lights_on:
            rows = max(1, int(Wd / 3.5))
            for r_ in range(rows):
                v = Wd * (r_ + 0.5) / rows; tubes = []
                for k in range(max(1, int((L - 1.0) // 2.4))):
                    u = 1.0 + 1.2 + k * 2.4 if L > 4.0 else L / 2
                    if u > L - 0.8:
                        break
                    tubes.append(("box", loc(u, v, zc - 0.5), sz(1.2, 0.07, 0.04)))
                    ld = bpy.data.lights.new(f"ir_ex_tube_{c.name}_{r_}_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.2; ld.size_y = 0.4; ld.energy = 110.0; ld.color = (1.0, 0.93, 0.8)
                    lo = bpy.data.objects.new(f"AreaLampFactory(exposed).spawn_asset({c.name}_{r_}_{k})", ld); bpy.context.scene.collection.objects.link(lo)
                    lo.location = loc(u, v, zc - 0.55); lo.rotation_euler = (0, 0, 0 if alx else math.pi / 2); n_tube += 1
                if tubes:
                    _obj(f"ExposedLights({c.name}|{r_})", [(tube, tubes), (blk, [("cyl", p0[1] + Vector((0.5, 0, 0.25)) if False else p0[1] + Vector((0, 0, 0.25)), 0.004, 0.5, 2) for p0 in tubes])])
        n_room += 1
        print(f"EXPOSED_CEILING {c.name} removed={n_rm} beams={n_beam} L={L:.1f} W={Wd:.1f} tubes={n_tube}", flush=True)
    stats["exposed_ceiling"] = {"ceilings": n_room, "grid_objects_removed": n_rm}
    return n_room
