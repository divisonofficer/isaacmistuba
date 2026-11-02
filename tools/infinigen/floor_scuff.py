"""Scuff any floor material (review: S24 'uniformly clean mirror-like glossy floor'; the weather pass does not reach parquet that is flagged weathered). Hooked from kit_lighting after
hung_lights, only when ROOM_FLOOR_SCUFF=1.

    from floor_scuff import apply; stats["floor_scuff"] = apply(stats)

Env: ROOM_FLOOR_SCUFF_RMIN (default 0.35) / ROOM_FLOOR_SCUFF_RMAX (default 0.8): a patchy noise between them is MAXed with the material's own roughness (a roughness map stays), so only
the glossy places get duller; ROOM_FLOOR_SCUFF_BUMP (default 0.05): fine scratch bump strength. Every room's `.floor` mesh, every material slot (the material is copied per distinct original).
"""
from __future__ import annotations

import os

import bpy


def _scuff(mat, rmin, rmax, bump):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if b is None or mat.get("floor_scuffed"):
        return False
    rough = b.inputs["Roughness"]
    src = rough.links[0].from_socket if rough.is_linked else None
    val = rough.default_value
    tc = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.7, 0.7, 0.7)
    n1 = N.new("ShaderNodeTexNoise"); n1.inputs["Scale"].default_value = 2.5; n1.inputs["Detail"].default_value = 7.0; n1.inputs["Roughness"].default_value = 0.65
    n2 = N.new("ShaderNodeTexNoise"); n2.inputs["Scale"].default_value = 220.0; n2.inputs["Detail"].default_value = 2.0
    rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = rmin; rr.inputs["To Max"].default_value = rmax
    rr.inputs["From Min"].default_value = 0.35; rr.inputs["From Max"].default_value = 0.65
    mx = N.new("ShaderNodeMath"); mx.operation = "MAXIMUM"
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = bump; bp.inputs["Distance"].default_value = 0.002
    Lk.new(tc.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], n1.inputs["Vector"]); Lk.new(mp.outputs["Vector"], n2.inputs["Vector"])
    Lk.new(n1.outputs["Fac"], rr.inputs["Value"]); Lk.new(rr.outputs["Result"], mx.inputs[0])
    if src is not None:
        Lk.new(src, mx.inputs[1])
    else:
        mx.inputs[1].default_value = val
    Lk.new(mx.outputs["Value"], b.inputs["Roughness"])
    nrm = b.inputs["Normal"]
    if nrm.is_linked:
        Lk.new(nrm.links[0].from_socket, bp.inputs["Normal"])
    Lk.new(n2.outputs["Fac"], bp.inputs["Height"]); Lk.new(bp.outputs["Normal"], b.inputs["Normal"])
    mat["floor_scuffed"] = True
    return True


def apply(stats):
    if os.environ.get("ROOM_FLOOR_SCUFF") != "1":
        return 0
    rmin = float(os.environ.get("ROOM_FLOOR_SCUFF_RMIN") or 0.35); rmax = float(os.environ.get("ROOM_FLOOR_SCUFF_RMAX") or 0.8); bump = float(os.environ.get("ROOM_FLOOR_SCUFF_BUMP") or 0.05)
    done, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor"):
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); copies[m.name] = c if _scuff(c, rmin, rmax, bump) else m
            sl.material = copies[m.name]; done += 1
    stats["floor_scuff"] = done
    return done
