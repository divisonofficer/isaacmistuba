"""Timber ceiling (S31 Stillroom ref: dark hewn log beams across a honey-coloured tongue-and-groove plank ceiling). Hooked from kit_lighting after the patchwork / stripes floors, only when ROOM_TIMBER_CEILING=1.

    from timber_ceiling import apply; stats["timber_ceiling"] = apply(stats)

Env: ROOM_TIMBER_CEILING=1
     ROOM_TIMBER_ROOMS=break-room     ceiling-name prefixes that get it (empty = every ceiling)
     ROOM_TIMBER_RGB=0.62,0.42,0.2    plank colour, linear sRGB 0..1 (honey oak)     ROOM_TIMBER_PLANK=0.12,1.2  plank width, length in m (straight planks, staggered)
     ROOM_TIMBER_BEAMS=4              number of log beams (0 = planks only; default 3-5 by the room length)    ROOM_TIMBER_BEAM_R=0.1  beam radius (m; 0.18-0.22 m thick logs)
     ROOM_TIMBER_BEAM_RGB=0.05,0.03,0.018   log colour (dark)
The planks are the straight-plank pattern of herringbone_floor._bake mapped in WORLD metres onto the ceiling (planks along the room's long axis); the beams span the short side, spaced along the long axis, each a
12-sided log of 14 rings with a per-ring radius and a small lateral wobble (roughly round, slightly irregular), embedded 20 % into the ceiling."""
from __future__ import annotations

import math
import os
import random

import bmesh
import bpy
from mathutils import Vector

from room_planner import proc_assets as pa


def _planks(mat, rgb, wpl, lpl, angle):
    import herringbone_floor as hf
    png, _n = hf._bake(rgb, wpl, lpl, 0.002, 0.06, straight=True)
    img = bpy.data.images.load(str(png), check_existing=True); img.colorspace_settings.name = "sRGB"
    nt = mat.node_tree; N_, Lk = nt.nodes, nt.links
    b = next((n for n in N_ if n.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        N_.clear(); b = N_.new("ShaderNodeBsdfPrincipled"); out = N_.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
        Lk.remove(l)
    size_m = hf._size_m(png)
    geo = N_.new("ShaderNodeNewGeometry"); mp = N_.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.0 / size_m, 1.0 / size_m, 1.0); mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(angle))
    tx = N_.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Smart"; tx.extension = "REPEAT"
    Lk.new(geo.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.55
    mat["timber"] = True


def _log(name, p0, p1, r, rng, mat):
    """A roughly round log from p0 to p1 (12 sides, 14 rings, radius and centre wobble per ring)."""
    d = (p1 - p0); ln = d.length; ax = d.normalized()
    up = Vector((0, 0, 1)) if abs(ax.z) < 0.9 else Vector((1, 0, 0))
    u = ax.cross(up).normalized(); v = ax.cross(u).normalized()
    bm = bmesh.new(); rings = []
    for k in range(15):
        t = k / 14.0; c = p0 + ax * ln * t + u * rng.uniform(-0.012, 0.012) + v * rng.uniform(-0.01, 0.01); rr = r * rng.uniform(0.92, 1.08)
        rings.append([bm.verts.new(c + (u * math.cos(a) + v * math.sin(a)) * rr * rng.uniform(0.95, 1.05)) for a in [q * 2 * math.pi / 12 for q in range(12)]])
    for k in range(14):
        for q in range(12):
            bm.faces.new((rings[k][q], rings[k][(q + 1) % 12], rings[k + 1][(q + 1) % 12], rings[k + 1][q]))
    for f in bm.faces:
        f.smooth = True
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def apply(stats):
    if os.environ.get("ROOM_TIMBER_CEILING") != "1":
        return 0
    rgb = tuple(float(v) for v in (os.environ.get("ROOM_TIMBER_RGB") or "0.62,0.42,0.2").split(","))
    wpl, lpl = (float(v) for v in (os.environ.get("ROOM_TIMBER_PLANK") or "0.12,1.2").split(","))
    brgb = tuple(float(v) for v in (os.environ.get("ROOM_TIMBER_BEAM_RGB") or "0.05,0.03,0.018").split(","))
    br = float(os.environ.get("ROOM_TIMBER_BEAM_R") or 0.1)
    only = tuple(x.strip() for x in (os.environ.get("ROOM_TIMBER_ROOMS") or "").split(",") if x.strip())
    log_m = pa._flat("ir_timber_log", brgb, 0.7, wood=True)
    rng = random.Random(31)
    n_ceil = n_beam = 0; copies = {}
    for o in list(bpy.data.objects):
        if o.type != "MESH" or not o.name.endswith(".ceiling") or (only and not o.name.startswith(only)):
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        x0, x1, y0, y1 = min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts); zc = min(p.z for p in pts)
        along_x = (x1 - x0) >= (y1 - y0)
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); c.name = m.name + ".timber"; _planks(c, rgb, wpl, lpl, 0.0 if along_x else 90.0); copies[m.name] = c
            sl.material = copies[m.name]
        n_ceil += 1
        L = (x1 - x0) if along_x else (y1 - y0)
        nb = int(os.environ.get("ROOM_TIMBER_BEAMS") or max(3, min(5, int(L / 2.2))))
        for k in range(nb):
            t = (k + 1) / (nb + 1) + rng.uniform(-0.012, 0.012); z = zc - br * 0.8
            if along_x:
                x = x0 + (x1 - x0) * t; a, b = Vector((x, y0 + 0.05, z)), Vector((x, y1 - 0.05, z))
            else:
                y = y0 + (y1 - y0) * t; a, b = Vector((x0 + 0.05, y, z)), Vector((x1 - 0.05, y, z))
            ob = _log(f"TimberBeam({o.name}|{k})", a, b, br * rng.uniform(0.95, 1.1), rng, log_m); ob["src"] = "arch:kit_stage"; n_beam += 1
    stats["timber_ceiling"] = {"ceilings": n_ceil, "beams": n_beam}
    return n_ceil
