"""Black-and-white checker tile floor (O5 cafe ref: black / white 30 cm tiles). Hooked from kit_lighting after the stripes floor, only when ROOM_FLOOR_CHECKER is set.

    from checker_floor import apply; stats["checker_floor"] = apply(stats)

Env: ROOM_FLOOR_CHECKER=<floor-name prefixes, comma list>   e.g. break-room_0/2        ROOM_CHECKER_TILE=0.3 tile edge (m)
     ROOM_CHECKER_RGB="0.02,0.02,0.02;0.85,0.85,0.82"   the two tile colours (linear)       ROOM_CHECKER_ROUGH=0.25 (glazed)
World-metre mapping (Geometry Position) so the pattern runs on across the room and needs no UVs; floor materials are copied and replaced like carpet_floor.py."""
from __future__ import annotations

import os

import bpy


def apply(stats):
    raw = os.environ.get("ROOM_FLOOR_CHECKER")
    if not raw:
        return 0
    only = tuple(x.strip() for x in raw.split(",") if x.strip())
    tile = float(os.environ.get("ROOM_CHECKER_TILE") or 0.3); rough = float(os.environ.get("ROOM_CHECKER_ROUGH") or 0.25)
    c1, c2 = [tuple(float(v) for v in c.split(",")) for c in (os.environ.get("ROOM_CHECKER_RGB") or "0.02,0.02,0.02;0.85,0.85,0.82").split(";")]
    cnt, copies = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".floor") or not o.name.startswith(only):
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            if m.name not in copies:
                c = m.copy(); c.name = m.name + ".checker"; nt = c.node_tree; N, Lk = nt.nodes, nt.links
                b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
                if b is None:
                    N.clear(); b = N.new("ShaderNodeBsdfPrincipled"); out = N.new("ShaderNodeOutputMaterial"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
                for l in list(b.inputs["Base Color"].links) + list(b.inputs["Roughness"].links):
                    Lk.remove(l)
                geo = N.new("ShaderNodeNewGeometry"); ck = N.new("ShaderNodeTexChecker"); ck.inputs["Scale"].default_value = 1.0 / tile
                ck.inputs["Color1"].default_value = (*c1, 1); ck.inputs["Color2"].default_value = (*c2, 1)
                Lk.new(geo.outputs["Position"], ck.inputs["Vector"]); Lk.new(ck.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
                copies[m.name] = c
            sl.material = copies[m.name]; cnt += 1
    stats["checker_floor"] = {"slots": cnt}
    return cnt
