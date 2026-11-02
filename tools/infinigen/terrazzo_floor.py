"""Terrazzo floor (S16 review: the reference floor is light terrazzo-speckled, ours plain white). Hooked from kit_lighting after hung_lights, only when ROOM_FLOOR_TERRAZZO=1.

    from terrazzo_floor import apply; stats["terrazzo_floor"] = apply(stats)

Every room `.floor` material is copied and its Base Color is replaced by a light base (ROOM_TERRAZZO_RGB, default 0.82,0.83,0.82) with sparse speckles: a fine Voronoi pattern thresholded to chips of
grey, green-grey and white (colours fixed), roughness 0.28 (polished). Chip density via ROOM_TERRAZZO_DENSITY (default 0.5, 0.2 sparse .. 0.8 dense).
"""
from __future__ import annotations

import os

import bpy


def _terrazzo(mat, base, density):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if mat.get("terrazzo"):
        return False
    if b is None:                                            # the floor shader is not a Principled (a node group / custom shader): replace it by a plain Principled
        N.clear(); b = N.new("ShaderNodeBsdfPrincipled"); out = N.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    for l in list(b.inputs["Base Color"].links):
        Lk.remove(l)
    tc = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (9.0, 9.0, 9.0)
    vo = N.new("ShaderNodeTexVoronoi"); vo.inputs["Scale"].default_value = 1.0; vo.feature = "F1"
    vo2 = N.new("ShaderNodeTexVoronoi"); vo2.inputs["Scale"].default_value = 1.0; vo2.feature = "F1"
    mp2 = N.new("ShaderNodeMapping"); mp2.inputs["Scale"].default_value = (14.0, 14.0, 14.0); mp2.inputs["Location"].default_value = (13.7, 4.1, 0.0)
    th = N.new("ShaderNodeMath"); th.operation = "LESS_THAN"; th.inputs[1].default_value = 0.2 * density * 2
    th2 = N.new("ShaderNodeMath"); th2.operation = "LESS_THAN"; th2.inputs[1].default_value = 0.14 * density * 2
    m1 = N.new("ShaderNodeMix"); m1.data_type = "RGBA"
    m2 = N.new("ShaderNodeMix"); m2.data_type = "RGBA"
    sock = lambda n, nm: next(x for x in n.inputs if x.name == nm and x.type == "RGBA")        # Mix has float / vector / RGBA sockets of the same name
    res = lambda n: next(x for x in n.outputs if x.type == "RGBA")
    sock(m1, "A").default_value = (*base, 1); sock(m1, "B").default_value = (0.36, 0.4, 0.37, 1); sock(m2, "B").default_value = (0.96, 0.96, 0.94, 1)
    Lk.new(tc.outputs["Position"], mp.inputs["Vector"]); Lk.new(tc.outputs["Position"], mp2.inputs["Vector"])
    for src, dst, off in ((mp, vo, 0.0), (mp2, vo2, 7.3)):                       # warp the lookup with noise so the chips are irregular blobs, not round dots
        nw = N.new("ShaderNodeTexNoise"); nw.inputs["Scale"].default_value = 3.5; nw.inputs["Detail"].default_value = 3.0
        sc_ = N.new("ShaderNodeVectorMath"); sc_.operation = "SCALE"; sc_.inputs["Scale"].default_value = 0.9
        ad = N.new("ShaderNodeVectorMath"); ad.operation = "ADD"
        Lk.new(src.outputs["Vector"], nw.inputs["Vector"]); Lk.new(nw.outputs["Color"], sc_.inputs[0]); Lk.new(src.outputs["Vector"], ad.inputs[0]); Lk.new(sc_.outputs["Vector"], ad.inputs[1]); Lk.new(ad.outputs["Vector"], dst.inputs["Vector"])
    Lk.new(vo.outputs["Distance"], th.inputs[0]); Lk.new(vo2.outputs["Distance"], th2.inputs[0])
    Lk.new(th.outputs["Value"], m1.inputs[0]); Lk.new(res(m1), sock(m2, "A")); Lk.new(th2.outputs["Value"], m2.inputs[0]); Lk.new(res(m2), b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.28
    for l in list(b.inputs["Roughness"].links):
        Lk.remove(l)
    mat["terrazzo"] = True
    return True


def apply(stats):
    if os.environ.get("ROOM_FLOOR_TERRAZZO") != "1":
        return 0
    base = tuple(float(v) for v in (os.environ.get("ROOM_TERRAZZO_RGB") or "0.82,0.83,0.82").split(","))
    dens = float(os.environ.get("ROOM_TERRAZZO_DENSITY") or 0.7)
    rooms_only = tuple(x.strip() for x in (os.environ.get("ROOM_TERRAZZO_ROOMS") or "").split(",") if x.strip())
    n, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor"):
            continue
        if rooms_only and not o.name.startswith(rooms_only):                      # ROOM_TERRAZZO_ROOMS=hallway: only these room-name prefixes
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); copies[m.name] = c if _terrazzo(c, base, dens) else m
            sl.material = copies[m.name]; n += 1
    stats["terrazzo_floor"] = n
    return n
