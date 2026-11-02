"""Procedural kitchen utensils and a lathed lamp shade for the ramen line (S32 r17: the primitive vocabulary read as game art). All plain bmesh objects with `_flat` materials; origin where the thing is held / hung.
    ladle(r)      long straight handle with a hook end + a deep hemispherical cup with a rim bead          origin at the hook tip, hangs along -Z (cup at the bottom)
    tongs(r)      two long flat arms joined at a spring pivot, tips slightly open, with grip ridges          origin at the pivot, hangs along -Z
    tebo(r)       a shallow noodle strainer basket: wireframe hemisphere + rim ring + long wooden handle    origin at the handle end, hangs along -Z, basket at the bottom
    shade(r, h)   a lathed pendant shade: dome, rolled rim, socket cap and cord grommet                   origin at the cord attachment, hangs along -Z
Every function returns an object linked into the scene collection (not yet transformed)."""
import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector


def plain(name, rgb, rough, metal=0.0):
    """A plain Principled material with NO surface-detail / scan layer (pa._flat picks a scanned concrete-like detail for names without a material rule: the ticket machine rendered as a grey concrete slab, S32 r19)."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1.0); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
    return m


def _mat(name, rgb, rough, metal=0.0):
    return plain(name, rgb, rough, metal)


def _obj(name, bm, mats):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _cyl(bm, p0, p1, r, seg=10, mi=0):
    v = Vector(p1) - Vector(p0)
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=v.length)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Vector((0, 0, 1)).rotation_difference(v.normalized()).to_matrix(), verts=res["verts"])
    bmesh.ops.translate(bm, vec=(Vector(p0) + Vector(p1)) / 2, verts=res["verts"])
    for f in {f for q in res["verts"] for f in q.link_faces}:
        f.material_index = mi


def _hemi(bm, c, r, down=True, mi=0, seg=16):
    """A hemisphere (open at the top when down=True) centred on c."""
    res = bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=seg // 2, radius=r)
    bmesh.ops.translate(bm, vec=c, verts=res["verts"])
    kill = [v for v in res["verts"] if (v.co.z > c.z + 1e-4 if down else v.co.z < c.z - 1e-4)]
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    for f in bm.faces:
        f.material_index = mi


def ladle(rng=None):
    r = rng or random.Random(1)
    steel = _mat("ir_pu_steel", (0.7, 0.72, 0.74), 0.28, 1.0)
    bm = bmesh.new(); L = r.uniform(0.3, 0.38); cr = r.uniform(0.04, 0.05)
    _cyl(bm, (0, 0, 0), (0, 0, -L), 0.0065, 10)                                          # the handle
    _cyl(bm, (0, 0, 0.0), (0.03, 0, 0.02), 0.0065, 10); _cyl(bm, (0.03, 0, 0.02), (0.05, 0, -0.0), 0.0065, 10)             # the hook end
    _cyl(bm, (0, 0, -L), (0.0, 0.015, -L - 0.03), 0.008, 10)                                # the neck into the cup
    _hemi(bm, Vector((0, 0.045, -L - 0.03)), cr, mi=0)                                      # the cup, open at the top
    ring = bmesh.ops.create_circle(bm, cap_ends=False, segments=20, radius=cr + 0.002)
    bmesh.ops.translate(bm, vec=Vector((0, 0.045, -L - 0.03)), verts=ring["verts"])
    return _obj("PuLadle", bm, [steel])


def tongs(rng=None):
    r = rng or random.Random(2)
    steel = _mat("ir_pu_steel", (0.7, 0.72, 0.74), 0.28, 1.0); dark = _mat("ir_pu_grip", (0.05, 0.05, 0.055), 0.5)
    bm = bmesh.new(); L = r.uniform(0.26, 0.32); open_ = r.uniform(0.012, 0.03)
    for sg in (1, -1):
        pts = [Vector((0, 0.002 * sg, 0)), Vector((0, (0.006 + open_ * 0.2) * sg, -L * 0.45)), Vector((0, (0.008 + open_ * 0.6) * sg, -L * 0.8)), Vector((0, (0.01 + open_) * sg, -L))]
        for a, b in zip(pts, pts[1:]):
            _cyl(bm, a, b, 0.0045, 8)
        _cyl(bm, Vector((0, (0.01 + open_) * sg, -L)), Vector((0, (0.012 + open_) * sg, -L - 0.03)), 0.007, 8)             # the flattened tip
        for k in range(4):                                                                                              # grip ridges
            z = -L * 0.12 - k * 0.012; _cyl(bm, Vector((-0.006, 0.0035 * sg, z)), Vector((0.006, 0.0035 * sg, z)), 0.0035, 6, 1)
    _cyl(bm, Vector((0, -0.006, 0.0)), Vector((0, 0.006, 0.0)), 0.006, 8)                                                # the spring pivot
    return _obj("PuTongs", bm, [steel, dark])


def tebo(rng=None):
    r = rng or random.Random(3)
    steel = _mat("ir_pu_steel", (0.7, 0.72, 0.74), 0.28, 1.0); wood = _mat("ir_pu_wood", (0.5, 0.33, 0.16), 0.55)
    bm = bmesh.new(); H = r.uniform(0.34, 0.4); br = r.uniform(0.085, 0.1)
    _cyl(bm, (0, 0, 0), (0, 0, -H), 0.011, 10, 1)                                          # the wooden handle
    _cyl(bm, (0, 0, -H), (0, 0.03, -H - 0.03), 0.005, 8)
    c = Vector((0, 0.03 + br * 0.9, -H - 0.04))
    _hemi(bm, c, br, mi=0, seg=18)                                                          # the basket (wireframed below)
    o = _obj("PuTebo", bm, [steel, wood])
    m = o.modifiers.new("wf", "WIREFRAME"); m.thickness = 0.0016; m.use_replace = True; m.use_even_offset = False
    # the rim ring + handle stay solid: add them as a second object joined afterwards
    ring = bmesh.new(); circ = bmesh.ops.create_circle(ring, cap_ends=False, segments=24, radius=br)
    bmesh.ops.translate(ring, vec=c, verts=circ["verts"])
    res = bmesh.ops.create_cone(ring, cap_ends=False, segments=24, radius1=br, radius2=br, depth=0.006)
    bmesh.ops.translate(ring, vec=c, verts=res["verts"]); bmesh.ops.delete(ring, geom=circ["verts"], context="VERTS")
    ro = _obj("PuTeboRim", ring, [steel])
    bpy.context.view_layer.update()
    for ob in (o, ro):
        ob.select_set(False)
    bpy.ops.object.select_all(action="DESELECT")
    for ob in (o, ro):
        ob.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.convert(target="MESH") if False else None
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def shade(radius=0.14, h=0.16, rng=None):
    """A lathed pendant shade: the profile (r, z) is spun round Z: socket cap, a short neck, a dome that flares to a rolled rim (z = 0 at the cord attachment)."""
    black = _mat("ir_pu_shade", (0.04, 0.04, 0.045), 0.38, 1.0); glow = _mat("ir_pu_bulb", (1.0, 0.7, 0.4), 0.3)
    gb = glow.node_tree.nodes["Principled BSDF"]; gb.inputs["Emission Color"].default_value = (1.0, 0.62, 0.3, 1); gb.inputs["Emission Strength"].default_value = 25.0
    bm = bmesh.new()
    prof = [(0.0, 0.0), (0.012, 0.0), (0.013, -0.015), (0.03, -0.03), (radius * 0.38, -h * 0.35), (radius * 0.72, -h * 0.72), (radius * 0.95, -h * 0.95), (radius, -h), (radius * 1.01, -h - 0.005), (radius * 0.97, -h - 0.009), (radius * 0.92, -h - 0.004)]
    verts = [bm.verts.new((px, 0, pz)) for px, pz in prof]
    edges = [bm.edges.new((a, b)) for a, b in zip(verts, verts[1:])]
    bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=(0, 0, 1), angle=math.tau, steps=28, use_merge=True)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    o = _obj("PuShade", bm, [black])
    bb = bmesh.new(); sp = bmesh.ops.create_uvsphere(bb, u_segments=12, v_segments=8, radius=0.032); bmesh.ops.translate(bb, vec=Vector((0, 0, -h * 0.86)), verts=sp["verts"])
    bo = _obj("PuBulb", bb, [glow])
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bo.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active
