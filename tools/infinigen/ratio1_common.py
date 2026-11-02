"""Shared reference-ratio dressing for the S37 / S38 / S39 shells (user goal 2026-10-26: Codex match ratio >= 0.5). Pure helpers, no scene flag:
tree      a real HSSD Christmas tree + red / gold baubles + a warm LED string (the beads are the only emitters, a real fixture)
cassette  a white ceiling AC cassette with a dark louvre grille + trim, replaces a plain box (S38 / S37) or is added where the scene has none (S39)
pipes     two white ceiling-hung service pipes with brackets + two white ceiling speakers on cables
mat       an entrance mat (soft slab, woven charcoal) just inside the door
"""
from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector


def bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def flat(name, rgb, rough=0.5, metal=0.0, emit=0.0, emit_rgb=None):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True; m["weathered"] = True
        b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
        if emit:
            b.inputs["Emission Color"].default_value = (*(emit_rgb or rgb), 1); b.inputs["Emission Strength"].default_value = emit
    return m


def _mesh(name, bm, mat, smooth=False, bevel=0.0):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = smooth
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    if bevel:
        m = o.modifiers.new("bv", "BEVEL"); m.width = bevel; m.segments = 2; m.limit_method = "ANGLE"
    return o


def _box(bm, c, s):
    r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=s, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])


def _cyl(bm, p0, p1, r, seg=16):
    a, b = Vector(p0), Vector(p1); d = b - a
    res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=d.length)
    q = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((a + b) / 2) @ q, verts=res["verts"])


def tree(ra, x, y, z0, h=2.7, rad=1.4, seed=7, tag="r1"):
    """Real HSSD Christmas tree fitted to h x rad, decorated; returns the tree object (or None when no asset)."""
    o = ra.hssd(r"christmas tree green|christmas tree", seed, x, y, z0, 0.0, fit=(rad, rad, h), size=(1.0, 4.0), grow=True)
    if o is None:
        return None
    bpy.context.view_layer.update(); a, b = bb(o)
    rg = random.Random(5); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; zb, zt = a[2] + 0.3, b[2] - 0.15; R0 = 0.45 * (b[0] - a[0])

    def rad_at(z):
        return max(0.04, R0 * (1 - (z - zb) / (zt - zb)) + 0.02)
    sets = {"red": ([], 0.055), "gold": ([], 0.045), "led": ([], 0.02)}
    for i in range(48):
        z = zb + 0.05 + (zt - zb - 0.15) * rg.random(); t = rg.uniform(0, 6.283); sets["red" if i % 3 else "gold"][0].append((cx + rad_at(z) * math.cos(t), cy + rad_at(z) * math.sin(t), z))
    for i in range(130):
        u = i / 129.0; z = zt - (zt - zb) * u; t = u * 6.283 * 6.0; sets["led"][0].append((cx + (rad_at(z) + 0.012) * math.cos(t), cy + (rad_at(z) + 0.012) * math.sin(t), z))
    mats = {"red": flat(f"ir_{tag}_bauble_red", (0.55, 0.02, 0.03), 0.12, 0.35), "gold": flat(f"ir_{tag}_bauble_gold", (0.8, 0.6, 0.2), 0.15, 0.8),
            "led": flat(f"ir_{tag}_tree_led", (1.0, 0.8, 0.5), 0.5, emit=25.0, emit_rgb=(1.0, 0.72, 0.38))}
    for k, (pts, rr) in sets.items():
        bm = bmesh.new()
        for q in pts:
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rr, matrix=Matrix.Translation(q))
        _mesh(f"{tag}_Tree_{k}", bm, mats[k], smooth=True)
    return o


def cassette(x, y, zc, size=0.95, drop=0.2, tag="r1"):
    """White 4-way ceiling cassette: housing, recessed panel, dark louvre grille (bars), 4 slot vents, hung on short rods."""
    white = flat(f"ir_{tag}_ac_white", (0.86, 0.86, 0.84), 0.45); dark = flat(f"ir_{tag}_ac_grille", (0.06, 0.06, 0.065), 0.5); zb = zc - drop
    bm = bmesh.new(); _box(bm, (x, y, zc - drop / 2), (size, size, drop)); _mesh(f"{tag}_AcBody", bm, white, bevel=0.02)
    bm = bmesh.new(); s = size * 0.5
    for sx in (-1, 1):
        for sy in (-1, 1):
            _cyl(bm, (x + sx * s * 0.8, y + sy * s * 0.8, zc), (x + sx * s * 0.8, y + sy * s * 0.8, zc + 0.12), 0.008, 8)
    _mesh(f"{tag}_AcRods", bm, flat(f"ir_{tag}_ac_rod", (0.5, 0.5, 0.5), 0.4, 0.8))
    bm = bmesh.new(); gw = size * 0.46
    for i in range(13):                                           # grille: 13 slats under the middle of the panel
        _box(bm, (x - gw / 2 + gw * i / 12, y, zb - 0.004), (0.012, gw, 0.01))
    for sgn in (-1, 1):                                           # 4 louvre slots along the sides
        _box(bm, (x + sgn * size * 0.4, y, zb - 0.003), (0.05, size * 0.7, 0.008)); _box(bm, (x, y + sgn * size * 0.4, zb - 0.003), (size * 0.7, 0.05, 0.008))
    _mesh(f"{tag}_AcGrille", bm, dark)
    return zb


def grille_on(o, tag="r1"):
    """Retrofit an existing plain AC box (bbox underside): a dark slat grille + 4 louvre slots under it, body repainted white."""
    a, b = bb(o); x, y = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; sx, sy = b[0] - a[0], b[1] - a[1]; zb = a[2]
    white = flat(f"ir_{tag}_ac_white", (0.86, 0.86, 0.84), 0.45); dark = flat(f"ir_{tag}_ac_grille", (0.06, 0.06, 0.065), 0.5)
    if o.type == "MESH":
        o.data = o.data.copy()
        for i in range(len(o.data.materials)):
            o.data.materials[i] = white
        if not o.data.materials:
            o.data.materials.append(white)
    bm = bmesh.new(); gw = min(sx, sy) * 0.55
    for i in range(13):
        _box(bm, (x - gw / 2 + gw * i / 12, y, zb - 0.004), (0.012, gw, 0.01))
    for sgn in (-1, 1):
        _box(bm, (x + sgn * sx * 0.4, y, zb - 0.003), (0.05, sy * 0.7, 0.008)); _box(bm, (x, y + sgn * sy * 0.4, zb - 0.003), (sx * 0.7, 0.05, 0.008))
    _mesh(f"{tag}_AcGrille", bm, dark)


def pipes_speakers(lo, hi, zc, y_pipe, z_pipe, tag="r1", speakers=((0.3, 0.5), (0.7, 0.45))):
    """Two white pipes along x at y_pipe (hung from the ceiling by brackets every 1.8 m) and two white ceiling speakers on cables at fractional (u, v) of the floor."""
    white = flat(f"ir_{tag}_pipe_white", (0.88, 0.88, 0.86), 0.4); bm = bmesh.new()
    for dy, rr in ((0.0, 0.045), (0.14, 0.03)):
        _cyl(bm, (lo[0] + 0.2, y_pipe + dy, z_pipe), (hi[0] - 0.2, y_pipe + dy, z_pipe), rr, 16)
    n = int((hi[0] - lo[0]) // 1.8)
    for i in range(n + 1):
        xx = lo[0] + 0.6 + i * (hi[0] - lo[0] - 1.2) / max(n, 1); _cyl(bm, (xx, y_pipe + 0.07, z_pipe), (xx, y_pipe + 0.07, zc), 0.006, 6)
    _mesh(f"{tag}_Pipes", bm, white, smooth=True)
    sp = flat(f"ir_{tag}_speaker", (0.9, 0.9, 0.88), 0.4); bm = bmesh.new(); cord = bmesh.new()
    for u, v in speakers:
        x, y = lo[0] + u * (hi[0] - lo[0]), lo[1] + v * (hi[1] - lo[1]); zs = zc - 0.9
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=0.12, radius2=0.09, depth=0.22, matrix=Matrix.Translation((x, y, zs)))
        _cyl(cord, (x, y, zs + 0.11), (x, y, zc), 0.005, 6)
    _mesh(f"{tag}_Speakers", bm, sp, smooth=True); _mesh(f"{tag}_SpeakerCords", cord, flat(f"ir_{tag}_cord", (0.03, 0.03, 0.03), 0.6))


def mat(ra, x, y, z0, w=1.2, d=0.8, yaw=0.0, rgb=(0.05, 0.05, 0.055), tag="r1"):
    """Entrance mat: a flat soft slab (woven charcoal, a light rim stripe) lying on the floor."""
    m = bpy.data.materials.get(f"ir_{tag}_doormat")
    if m is None:
        m = flat(f"ir_{tag}_doormat", rgb, 0.95); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.inputs["Scale"].default_value = 60.0; wv.inputs["Distortion"].default_value = 1.0
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (*rgb, 1); mx.inputs["B"].default_value = (rgb[0] * 2.2, rgb[1] * 2.2, rgb[2] * 2.2, 1)
        L.new(wv.outputs["Fac"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
        bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.6; L.new(wv.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return ra.soft(f"{tag}_EntranceMat", m, x, y, z0 + 0.012, w, d, 0.024, yaw=yaw, seed=3, puff=0.05)


def plant_fix(o):
    """HSSD / sd_plant leaf materials drive Roughness from a noise clamp that dips to ~0 (and some wire Metallic to a colour channel): leaves mirror the bright window and read near-white (Codex 'translucent foliage'). Unlink both, keep a leaf-like spec."""
    n = 0
    if o is None or o.type != "MESH":
        return 0
    for m in o.data.materials:
        if m is None or not m.use_nodes:
            continue
        b = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        n += _tint_pale(m)
        for lk in list(b.inputs["Roughness"].links):                 # the noise-driven roughness dips to ~0: leaves mirror the bright window and render white
            m.node_tree.links.remove(lk); n += 1
        b.inputs["Roughness"].default_value = max(b.inputs["Roughness"].default_value, 0.55)
        for lk in list(b.inputs["Metallic"].links):
            m.node_tree.links.remove(lk); n += 1
        if n:
            b.inputs["Metallic"].default_value = 0.0; b.inputs["Specular IOR Level"].default_value = 0.3
    return n


def _tint_pale(m):
    """A leaf material whose colour texture is pale (value > 0.6, saturation 0.12-0.6: the HSSD artificial plants that render white under sun) gets a green multiply so it reads as foliage."""
    nt = m.node_tree; b = next((x for x in nt.nodes if x.type == "BSDF_PRINCIPLED"), None)
    if b is None or not b.inputs["Base Color"].links:
        return 0
    src = b.inputs["Base Color"].links[0]
    if src.from_node.type != "TEX_IMAGE" or src.from_node.image is None:
        return 0
    import numpy as np
    px = np.array(src.from_node.image.pixels[:]).reshape(-1, 4)[:, :3]; mx = px.max(1); mn = px.min(1)
    sat = ((mx - mn) / np.maximum(mx, 1e-3)).mean()
    if mx.mean() < 0.6 or not 0.12 < sat < 0.6:                    # pale but not grey-white (ceramic pots stay white)
        return 0
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 1.0; mix.inputs["B"].default_value = (0.5, 0.8, 0.4, 1.0)
    nt.links.new(src.from_socket, mix.inputs["A"]); nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    return 1


def plant_fix_all(min_h=0.7):
    """plant_fix on every HSSD plant (HssdPlant*, Real_hssd* taller than min_h and narrower than 2.2 m)."""
    k = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith(("HssdPlant", "Real_hssd")):
            a, b = bb(o)
            if b[2] - a[2] > min_h and max(b[0] - a[0], b[1] - a[1]) < 2.2 and plant_fix(o):
                k += 1
    return k


def card(x, y, z, yaw, w, h, mat, tag="r1", lean=0.2):
    """A small framed promo card standing on a counter (black bevelled frame + printed face, leaning back)."""
    fr = flat(f"ir_{tag}_card_frame", (0.03, 0.03, 0.033), 0.4, 0.5); bm = bmesh.new(); _box(bm, (0, 0, h / 2), (w, 0.016, h)); o = _mesh(f"{tag}_CardFrame", bm, fr, bevel=0.003)
    bm = bmesh.new(); _box(bm, (0, -0.0085, h / 2), (w - 0.03, 0.002, h - 0.03)); f = _mesh(f"{tag}_CardFace", bm, mat)
    for q in (o, f):
        q.rotation_euler = (-lean, 0, yaw); q.location = (x, y, z)
    return o
