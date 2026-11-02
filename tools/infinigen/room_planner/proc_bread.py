"""Real bread shapes for the bakery displays (user 10-24: 'S35 the bread modelling falls short'). Pure bmesh, no bpy.ops. Called from proc_assets._prims for parts of kind "bread:<shape>":

    ("bread:baguette", centre, (a, b, c), (rx, ry, rz))     a, b, c = semi-axes along x (length), y, z, exactly like an "lsph" part

Shapes (all smooth shaded, 300-900 faces):
  baguette   a lathe along x with a pointed taper, a flat belly, and 5 diagonal scores on top: each score is a groove with one lifted 'ear' lip (torn crust), seeded per piece
  loaf       an oval batard: the same lathe, shorter and fatter, 3 diagonal scores
  boule      a flattened sphere with a cross-score (two grooves) and a slight over-bake bulge
  roll       a round roll with a split top (one deep groove, lifted lips)
  croissant  a crescent swept along an arc, 9 layered ridges (radius modulated 12 %), tapered tips curled in
  slice      a thin oval disc (crumb face) for sliced loaves
The crust gradient / flour dust / crumb subsurface live in the material (crust_material), not in the mesh."""
from __future__ import annotations

import math
import random

import bmesh
from mathutils import Vector


def _lathe(bm, a, b, c, nx, nr, taper, seed, scores, flat=0.8):
    """Ring-by-ring body along x; returns the list of created verts."""
    rng = random.Random(seed)
    rings = []
    for i in range(nx + 1):
        t = i / nx; x = (t * 2 - 1) * a
        r = (math.sin(math.pi * t) ** taper)                                    # taper < 1: blunt ends, > 1: pointed
        ring = []
        for j in range(nr):
            th = 2 * math.pi * j / nr
            y, z = math.cos(th) * b * r, math.sin(th) * c * r
            if z < 0:
                z *= flat                                                       # a flat belly
            ring.append([x, y, z, t, th])
        rings.append(ring)
    for sc in scores:                                                           # diagonal score: groove + lifted ear on one lip
        t0, slope, w = sc; depth = 0.45 + rng.random() * 0.12                    # one depth per score (per-vertex noise made them jagged)
        for i, ring in enumerate(rings):
            for v in ring:
                x, y, z, t, th = v
                if z <= 0.4 * c:
                    continue
                d = (t - t0) * 2 * a - slope * y                                  # distance across the diagonal
                if abs(d) < w:
                    k = 1 - abs(d) / w                                                  # a sharp V cut
                    v[2] -= depth * c * k * 1.5                                          # the groove
                elif w * 0.6 <= d < w * 1.5:
                    v[2] += 0.05 * c * math.sin(math.pi * (d - w * 0.6) / (w * 0.9))   # the lifted ear sits right on the cut
    verts = [[bm.verts.new((v[0], v[1], v[2])) for v in ring] for ring in rings]
    for i in range(nx):
        for j in range(nr):
            try:
                bm.faces.new((verts[i][j], verts[i][(j + 1) % nr], verts[i + 1][(j + 1) % nr], verts[i + 1][j]))
            except ValueError:
                pass
    out = [v for ring in verts for v in ring]
    return out


def build(bm, shape, size, seed):
    vs = _build(bm, shape, size, seed)
    faces = list({f for v in vs for f in v.link_faces})
    if faces:
        bmesh.ops.recalc_face_normals(bm, faces=faces)
    return vs


def _build(bm, shape, size, seed):
    a, b, c = size
    rng = random.Random(seed)
    if shape == "baguette":
        c = b * 0.85                                                             # a round-to-oval section, ~6 x 5 cm
        sc = [(0.13 + 0.185 * k, 0.9 + rng.uniform(-0.15, 0.15), 0.03 * a / 0.4 + 0.008) for k in range(5)]
        return _lathe(bm, a, b, c, 120, 28, 0.55, seed, sc, flat=0.9)
    if shape == "loaf":
        sc = [(0.26 + 0.24 * k, 0.8 + rng.uniform(-0.15, 0.15), 0.04) for k in range(3)]
        return _lathe(bm, a, b, c, 56, 24, 0.5, seed, sc, flat=0.9)
    if shape == "boule":
        vs = _lathe(bm, a, a, c, 20, 20, 0.5, seed, [(0.5, 0.0, 0.012), (0.5, 100.0, 0.012)], flat=0.6)       # slope 100 ~ a groove across y
        return vs
    if shape == "roll":
        return _lathe(bm, a, b, c, 14, 14, 0.5, seed, [(0.5, 100.0, 0.009)], flat=0.6)
    if shape == "slice":
        return _lathe(bm, a * 0.15, b, c, 4, 16, 0.4, seed, [], flat=1.0)
    if shape == "croissant":
        c = max(c, b * 0.85)                                                     # puffed: height ~0.45 of the width
        n, m = 36, 14; arc = math.radians(200); R = a * 0.9
        verts = []
        for i in range(n + 1):
            t = i / n; ang = (t - 0.5) * arc
            cx, cy = math.sin(ang) * R, (math.cos(ang) - 1) * R
            ph = 9 * t + 0.9 * math.sin(2 * math.pi * 1.3 * t + seed % 7)             # irregular layer widths
            r = (math.sin(math.pi * (0.04 + 0.92 * t)) ** 0.6) * (1 + (0.07 + 0.03 * math.sin(7 * t + seed)) * math.cos(2 * math.pi * ph)) * (0.85 + 0.3 * math.exp(-((t - 0.5) / 0.25) ** 2))   # puffed middle
            ring = []
            for j in range(m):
                th = 2 * math.pi * j / m
                fk = 1 + 0.03 * math.sin(11 * th + 31 * t)                                # a faint flake texture
                lx, lz = math.cos(th) * b * r * fk, math.sin(th) * c * r * fk * (0.8 if math.sin(th) < 0 else 1.0) + 0.5 * c * (max(0.0, abs(t - 0.5) * 2 - 0.6) ** 2) * 2.0   # tips curl up
                # the cross-section sits in the plane normal to the arc: radial direction in xy, vertical z
                nxv, nyv = math.sin(ang), math.cos(ang)
                ring.append(bm.verts.new((cx + nxv * lx * 0.0 + (-math.sin(ang) * 0) + nxv * lx, cy + nyv * lx, lz)))
            verts.append(ring)
        for i in range(n):
            for j in range(m):
                try:
                    bm.faces.new((verts[i][j], verts[i][(j + 1) % m], verts[i + 1][(j + 1) % m], verts[i + 1][j]))
                except ValueError:
                    pass
        return [v for ring in verts for v in ring]
    return _lathe(bm, a, b, c, 10, 10, 0.5, seed, [])


def crust_material(name, rgb, flour=0.0, crumb=False, rough=(0.82, 0.93)):
    """Baked-crust Principled material, no UV / coordinate dependence: albedo goes from a pale belly (1.35x the tone) to a dark top (0.62x) by the surface normal's z, the grooves (ambient occlusion) show the pale
    unbaked dough, an optional flour dusting (`flour` 0..1) speckles the top, roughness varies 0.5-0.75, a fine bump. `crumb=True`: cut-face material (soft cream, subsurface 0.25, rough 0.8)."""
    import bpy
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    if crumb:
        b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.8
        for nm in ("Subsurface Weight", "Subsurface"):
            if nm in b.inputs:
                b.inputs[nm].default_value = 0.25; break
        if "Subsurface Radius" in b.inputs:
            b.inputs["Subsurface Radius"].default_value = (0.8, 0.5, 0.3)
        return m
    geo = N.new("ShaderNodeNewGeometry"); sep = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Normal"], sep.inputs[0])
    mr = N.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = -0.3; mr.inputs["From Max"].default_value = 0.9; L.new(sep.outputs["Z"], mr.inputs["Value"])
    ramp = N.new("ShaderNodeMix"); ramp.data_type = "RGBA"; ramp.inputs[6].default_value = (min(rgb[0] * 1.25, 1), min(rgb[1] * 1.2, 1), min(rgb[2] * 1.15, 1), 1); ramp.inputs[7].default_value = (rgb[0] * 0.48, rgb[1] * 0.42, rgb[2] * 0.36, 1)
    L.new(mr.outputs["Result"], ramp.inputs["Factor"])
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 60.0; nz.inputs["Detail"].default_value = 6.0; tc = N.new("ShaderNodeTexCoord"); L.new(tc.outputs["Object"], nz.inputs["Vector"])
    vary = N.new("ShaderNodeMix"); vary.data_type = "RGBA"; vary.blend_type = "MULTIPLY"; vary.inputs["Factor"].default_value = 0.35; vary.inputs[7].default_value = (0.8, 0.75, 0.7, 1); L.new(nz.outputs["Color"], vary.inputs[7]); L.new(ramp.outputs[2], vary.inputs[6])
    ao = N.new("ShaderNodeAmbientOcclusion"); ao.inputs["Distance"].default_value = 0.012; ao.samples = 4
    inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0; L.new(ao.outputs["AO"], inv.inputs[1]); inv.use_clamp = True
    sc = N.new("ShaderNodeMath"); sc.operation = "MULTIPLY"; sc.inputs[1].default_value = 1.0; L.new(inv.outputs[0], sc.inputs[0]); sc.use_clamp = True
    pale = N.new("ShaderNodeMix"); pale.data_type = "RGBA"; pale.inputs[7].default_value = (0.9, 0.78, 0.55, 1); L.new(sc.outputs[0], pale.inputs["Factor"]); L.new(vary.outputs[2], pale.inputs[6])
    last = pale.outputs[2]
    if flour > 0:
        fn = N.new("ShaderNodeTexNoise"); fn.inputs["Scale"].default_value = 260.0; fn.inputs["Detail"].default_value = 4.0; L.new(tc.outputs["Object"], fn.inputs["Vector"])
        th = N.new("ShaderNodeMapRange"); th.inputs["From Min"].default_value = 0.5; th.inputs["From Max"].default_value = 0.78; L.new(fn.outputs["Fac"], th.inputs["Value"])
        up = N.new("ShaderNodeMath"); up.operation = "MULTIPLY"; L.new(th.outputs["Result"], up.inputs[0]); L.new(mr.outputs["Result"], up.inputs[1])
        fm = N.new("ShaderNodeMath"); fm.operation = "MULTIPLY"; fm.inputs[1].default_value = flour * 0.3; L.new(up.outputs[0], fm.inputs[0])
        fl = N.new("ShaderNodeMix"); fl.data_type = "RGBA"; fl.inputs[7].default_value = (0.95, 0.93, 0.88, 1); L.new(fm.outputs[0], fl.inputs["Factor"]); L.new(pale.outputs[2], fl.inputs[6]); last = fl.outputs[2]
    L.new(last, b.inputs["Base Color"])
    rn = N.new("ShaderNodeMapRange"); rn.inputs["To Min"].default_value = rough[0]; rn.inputs["To Max"].default_value = rough[1]; L.new(nz.outputs["Fac"], rn.inputs["Value"]); L.new(rn.outputs["Result"], b.inputs["Roughness"])
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.25; bp.inputs["Distance"].default_value = 0.002; L.new(nz.outputs["Fac"], bp.inputs["Height"]); L.new(bp.outputs["Normal"], b.inputs["Normal"])
    for nm in ("Specular IOR Level", "Specular"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.08; break
    for nm in ("Subsurface Weight", "Subsurface"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.05; break
    m["weathered"] = True; b["weathered"] = True
    return m


def slice_material(name, crust_rgb=(0.62, 0.36, 0.14)):
    """Sliced-loaf cut face + rim in one material, no UVs: faces whose OBJECT normal points along the slice axis (x) are the open crumb (cream, cell holes: Voronoi bump + darker pores, subsurface 0.25),
    the rest is the golden crust rim."""
    import bpy
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); sep = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Normal"], sep.inputs[0])
    ab = N.new("ShaderNodeMath"); ab.operation = "ABSOLUTE"; L.new(sep.outputs["X"], ab.inputs[0])
    face = N.new("ShaderNodeMapRange"); face.inputs["From Min"].default_value = 0.6; face.inputs["From Max"].default_value = 0.9; L.new(ab.outputs[0], face.inputs["Value"])            # 1 on the cut face
    vo = N.new("ShaderNodeTexVoronoi"); vo.inputs["Scale"].default_value = 140.0; L.new(tc.outputs["Object"], vo.inputs["Vector"])
    pores = N.new("ShaderNodeMapRange"); pores.inputs["From Min"].default_value = 0.05; pores.inputs["From Max"].default_value = 0.22; L.new(vo.outputs["Distance"], pores.inputs["Value"])      # 0 in a pore
    crumb = N.new("ShaderNodeMix"); crumb.data_type = "RGBA"; crumb.inputs[6].default_value = (0.42, 0.28, 0.13, 1); crumb.inputs[7].default_value = (0.78, 0.62, 0.36, 1); L.new(pores.outputs["Result"], crumb.inputs["Factor"])
    fin = N.new("ShaderNodeMix"); fin.data_type = "RGBA"; fin.inputs[6].default_value = (*[c * 0.9 for c in crust_rgb], 1); L.new(face.outputs["Result"], fin.inputs["Factor"]); L.new(crumb.outputs[2], fin.inputs[7]); L.new(fin.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.85
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.8; bp.inputs["Distance"].default_value = 0.002; L.new(pores.outputs["Result"], bp.inputs["Height"]); L.new(bp.outputs["Normal"], b.inputs["Normal"])
    for nm in ("Subsurface Weight", "Subsurface"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.2; break
    m["weathered"] = True; b["weathered"] = True
    return m
