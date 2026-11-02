"""Manufacturing details (user review 10-23, axis B: 'screws / seams are tiny in the image but a strong cue the object was manufactured'). Hooked from kit_lighting after surface_realism, only when ROOM_MFG_DETAIL=1:

    import mfg_detail; stats["mfg_detail"] = mfg_detail.apply(stats)

  bevel      a 1.5 mm Bevel modifier (2 segments, 35 deg limit) on every furniture / fixture mesh that has none (ROOM_MFG_BEVEL = width in m, 0 = off). Walls, floors, ceilings, cards, glass, plants are left alone.
  plates     a switch plate at 1.1 m beside every door (on both wall faces, found by ray-casting onto the wall) and a socket at 0.3 m on the other side; white 8.5 cm plate, rocker / socket face in grey.
  hinges     3 steel hinge knuckles (and the screw heads of their leaves) on every flush door leaf, parented to the leaf so they swing with it.
  edgeband   a 1.5 mm contrasting laminate edge band round every rectangular table / desk top (ROOM_MFG_EDGEBAND=0 off, ROOM_MFG_EDGEBAND_RGB = colour, default dark brown)
  vents      ROOM_MFG_VENTS=1: a 0.6 m slot diffuser (frame + 9 slats) in the ceiling of every room over 8 m2, away from the lights.
Everything is separate small meshes with their own plain materials (ir_mfg_*), so no pass can paint over them. Deterministic (seeded by the object names).
"""
from __future__ import annotations

import math
import os
import random

import bpy
import bmesh
from mathutils import Vector, Matrix

SKIP_NAMES = ("wall", "floor", "ceiling", "window", "glass", "card", "ground", "backdrop", "photo", "light", "lamp", "plant", "tree", "leaf", "foliage", "grass", "rug", "carpet", "curtain", "blind", "cloth", "sky",
              "ir_real_sun", "pano", "bigglass", "mfg", "skirt", "baseboard", "beam", "street")


def _mat(name, rgb, rough=0.5, metal=0.0):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1.0); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
    return m


def _bevels(width):
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or o.hide_render or any(k in o.name.lower() for k in SKIP_NAMES):
            continue
        if any(md.type == "BEVEL" for md in o.modifiers) or not (20 < len(o.data.polygons) < 400000):
            continue
        d = o.dimensions
        if max(d) < 0.05:
            continue
        md = o.modifiers.new("ir_mfg_bevel", "BEVEL"); md.width = width; md.segments = 2; md.limit_method = "ANGLE"; md.angle_limit = math.radians(35); md.harden_normals = False
        n += 1
    return n


def _doors():
    """(centre, wall normal, opening width) of every flush door leaf."""
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.parent is None or not o.data.name.startswith("ir_flush_leaf"):
            continue
        c = o.parent.matrix_world.translation.copy()
        nrm = o.parent.matrix_world.to_3x3() @ Vector((0, 1, 0)); nrm.z = 0
        if nrm.length < 1e-6:
            continue
        nrm.normalize()
        bb = [Vector(v) for v in o.bound_box]
        w = max(max(v[i] for v in bb) - min(v[i] for v in bb) for i in (0, 1)) * max(o.scale[0], 1e-6)
        out.append((o, c, nrm, min(max(w, 0.7), 1.2)))
    return out


def _box(bm, c, size, axes, mi):
    """A box centred on c with half-sizes size along the frame axes (tangent, up, normal)."""
    r = bmesh.ops.create_cube(bm, size=1.0)
    for v in r["verts"]:
        x, y, z = v.co
        v.co = c + axes[0] * (x * size[0]) + axes[1] * (y * size[1]) + axes[2] * (z * size[2])
    for f in {f for v in r["verts"] for f in v.link_faces}:
        f.material_index = mi


def _plates(stats):
    dg = bpy.context.evaluated_depsgraph_get(); sc = bpy.context.scene
    bm = bmesh.new(); n = 0
    for o, c, nrm, w in _doors():
        tan = Vector((-nrm.y, nrm.x, 0.0))
        for side in (1, -1):
            for k, (u, z, kind) in enumerate(((w / 2 + 0.2, 1.1, "sw"), (-(w / 2 + 0.2), 0.3, "sock"))):
                p = c + tan * u * side + nrm * side * 0.6; p.z = z
                hit, loc, hn, _, ho, _ = sc.ray_cast(dg, p, -nrm * side, distance=1.0)
                if not hit or "wall" not in ho.name.lower():
                    continue
                if abs(hn.z) > 0.3:
                    continue
                axes = (tan, Vector((0, 0, 1)), hn)
                _box(bm, loc + hn * 0.004, (0.085, 0.085, 0.008), axes, 0)
                if kind == "sw":
                    _box(bm, loc + hn * 0.0105, (0.02, 0.042, 0.004), axes, 1)
                else:
                    for dz in (0.0,):
                        _box(bm, loc + hn * 0.0095 + tan * 0.015, (0.012, 0.012, 0.003), axes, 1); _box(bm, loc + hn * 0.0095 - tan * 0.015, (0.012, 0.012, 0.003), axes, 1)
                n += 1
    if n:
        me = bpy.data.meshes.new("MfgPlates"); bm.to_mesh(me); me.materials.append(_mat("ir_mfg_plate", (0.9, 0.9, 0.88), 0.45)); me.materials.append(_mat("ir_mfg_plate_dark", (0.25, 0.25, 0.27), 0.4))
        ob = bpy.data.objects.new("MfgSwitchPlates", me); sc.collection.objects.link(ob); ob["src"] = "arch:mfg_detail"
    bm.free()
    return n


def _hinges():
    n = 0; steel = _mat("ir_mfg_hinge", (0.62, 0.63, 0.65), 0.35, 1.0)
    for o, c, nrm, w in _doors():
        bb = [Vector(v) for v in o.bound_box]
        ext = [max(v[i] for v in bb) - min(v[i] for v in bb) for i in range(3)]
        thin = min((0, 1), key=lambda i: ext[i]); wid = 1 - thin
        tc = (max(v[thin] for v in bb) + min(v[thin] for v in bb)) / 2
        zh = max(v[2] for v in bb)
        bm = bmesh.new()
        for z in (0.25, zh / 2 + 0.05, zh - 0.3):
            loc = Vector((0, 0, 0)); loc[thin] = tc; loc[wid] = 0.0; loc[2] = z
            bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=0.009, radius2=0.009, depth=0.1, matrix=Matrix.Translation(loc))
        me = bpy.data.meshes.new("MfgHinges"); bm.to_mesh(me); bm.free(); me.materials.append(steel)
        ob = bpy.data.objects.new("MfgHinges", me); bpy.context.scene.collection.objects.link(ob); ob.parent = o; ob["src"] = "arch:mfg_detail"
        n += 3
    return n


def _vents():
    n = 0; steel = _mat("ir_mfg_vent", (0.88, 0.88, 0.86), 0.5); dark = _mat("ir_mfg_vent_dark", (0.06, 0.06, 0.07), 0.6)
    lights = [o.matrix_world.translation for o in bpy.data.objects if o.type == "LIGHT"]
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".ceiling") or o.get("ir_no_vent"):          # ir_no_vent: a shell that owns this ceiling (H2 bedrooms: recessed downlight grid, no grille)
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts); y0, y1 = min(p.y for p in pts), max(p.y for p in pts); z = max(p.z for p in pts)
        if (x1 - x0) * (y1 - y0) < 8.0:
            continue
        rnd = random.Random(o.name)
        for _ in range(12):
            cx, cy = rnd.uniform(x0 + 0.8, x1 - 0.8), rnd.uniform(y0 + 0.8, y1 - 0.8)
            if all((l.x - cx) ** 2 + (l.y - cy) ** 2 > 0.8 ** 2 for l in lights):
                break
        else:
            continue
        bm = bmesh.new(); ax = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        _box(bm, Vector((cx, cy, z - 0.006)), (0.3, 0.3, 0.006), ax, 0)
        for k in range(9):
            _box(bm, Vector((cx, cy - 0.24 + k * 0.06, z - 0.015)), (0.28, 0.012, 0.008), ax, 1)
        me = bpy.data.meshes.new("MfgVent"); bm.to_mesh(me); bm.free(); me.materials.append(steel); me.materials.append(dark)
        ob = bpy.data.objects.new("MfgVent", me); bpy.context.scene.collection.objects.link(ob); ob["src"] = "arch:mfg_detail"; n += 1
    return n


def _edgebands():
    """A 1.5 mm proud contrasting edge band round every rectangular table / desk top (laminate edge-banding); round or irregular tops (convex-hull area < 92 % of the box) are left alone."""
    from mathutils.geometry import convex_hull_2d
    band = _mat("ir_mfg_edgeband", tuple(float(v) for v in (os.environ.get("ROOM_MFG_EDGEBAND_RGB") or "0.11,0.09,0.08").split(",")), 0.4)
    n = 0
    for o in list(bpy.data.objects):
        nm = o.name.lower()
        if o.type != "MESH" or not any(k in nm for k in ("table", "desk")) or any(k in nm for k in ("lamp", "mfg", "wall", "cloth", "tablet")) or o.hide_render or len(o.data.vertices) > 200000:
            continue
        co = [v.co for v in o.data.vertices]
        zt = max(c.z for c in co); top = [c for c in co if c.z > zt - 0.012]
        if len(top) < 4:
            continue
        xs = [c.x for c in top]; ys = [c.y for c in top]; x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, d = x1 - x0, y1 - y0
        if w < 0.35 or d < 0.35 or w > 4.5 or d > 4.5:
            continue
        hull = convex_hull_2d([(c.x, c.y) for c in top]); 
        hp = [Vector((top[i].x, top[i].y, 0)) for i in hull]
        if len(hull) < 3 or abs(sum(hp[k].x * hp[(k + 1) % len(hp)].y - hp[(k + 1) % len(hp)].x * hp[k].y for k in range(len(hp)))) / 2 < 0.92 * w * d:
            continue
        zb = min(c.z for c in top); t = max(zt - zb, 0.012) + 0.002; e = 0.0015; zc = zt - t / 2 + 0.001
        bm = bmesh.new(); ax = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        for c, sz in ((Vector(((x0 + x1) / 2, y0 - e / 2, zc)), (w + 2 * e, e, t)), (Vector(((x0 + x1) / 2, y1 + e / 2, zc)), (w + 2 * e, e, t)),
                      (Vector((x0 - e / 2, (y0 + y1) / 2, zc)), (e, d, t)), (Vector((x1 + e / 2, (y0 + y1) / 2, zc)), (e, d, t))):
            _box(bm, c, sz, ax, 0)
        me = bpy.data.meshes.new("MfgEdgeBand"); bm.to_mesh(me); bm.free(); me.materials.append(band)
        ob = bpy.data.objects.new("MfgEdgeBand", me); bpy.context.scene.collection.objects.link(ob); ob.parent = o; ob["src"] = "arch:mfg_detail"; n += 1
    return n


def apply(stats):
    if os.environ.get("ROOM_MFG_DETAIL") != "1":
        return {}
    out = {}
    bw = float(os.environ.get("ROOM_MFG_BEVEL") or 0.0015)
    if bw > 0:
        out["bevelled"] = _bevels(bw)
    if os.environ.get("ROOM_MFG_EDGEBAND", "1") != "0":
        out["edgebands"] = _edgebands()
    out["plates"] = _plates(stats)
    out["hinges"] = _hinges()
    if os.environ.get("ROOM_MFG_VENTS") == "1":
        out["vents"] = _vents()
    return out
