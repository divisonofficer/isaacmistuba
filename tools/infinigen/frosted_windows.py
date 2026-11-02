"""High frosted windows for service rooms (floors G / H, refs: kitchen / utility / restroom have 'a narrow HIGH frosted window', ours are big clear panes with the street behind).

Late pass (kit_lighting after env_windows; ROOM_FROSTED_WINDOW_ROOMS=kitchen,utility,restroom,bathroom = room-name prefixes; ROOM_FROSTED_SILL=1.95 m new sill). For every WindowFactory mesh
inside one of those rooms: its lower part (from the old sill to the new one) is closed with wall quads on the room's inner wall plane (big_glass._patch on `<room>.wall`, so they follow every wall
material), and every glass slot gets the frosted material of glass_partitions (a transparent / white mix). Stats: stats["frosted_windows"] = number of windows treated.
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector


def _glow_frost():
    """Frosted pane that glows with daylight (H r62: 'service windows read OPAQUE pale; ref: textured frosted, light coming through'): 45 % diffuse white + 55 % transparent, plus a soft cool emission, a fine noise bump."""
    m = bpy.data.materials.get("ir_win_frost_glow")
    if m is not None:
        return m
    m = bpy.data.materials.new("ir_win_frost_glow"); m.use_nodes = True
    N, L = m.node_tree.nodes, m.node_tree.links; N.clear()
    out = N.new("ShaderNodeOutputMaterial"); mx = N.new("ShaderNodeMixShader"); tr = N.new("ShaderNodeBsdfTransparent"); df = N.new("ShaderNodeBsdfPrincipled")
    df.inputs["Base Color"].default_value = (0.9, 0.93, 0.95, 1); df.inputs["Roughness"].default_value = 0.8
    df.inputs["Emission Color"].default_value = (0.85, 0.92, 1.0, 1); df.inputs["Emission Strength"].default_value = 0.9
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 60.0; bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.25
    L.new(nz.outputs["Fac"], bp.inputs["Height"]); L.new(bp.outputs["Normal"], df.inputs["Normal"])
    mx.inputs[0].default_value = 0.45
    L.new(tr.outputs[0], mx.inputs[1]); L.new(df.outputs[0], mx.inputs[2]); L.new(mx.outputs[0], out.inputs["Surface"])
    return m


def apply(stats):
    prefixes = tuple(x for x in os.environ.get("ROOM_FROSTED_WINDOW_ROOMS", "").split(",") if x)
    if not prefixes:
        return 0
    from room_planner import big_glass as bg
    from room_planner import glass_partitions as gp
    from room_planner import terrace_open as to
    import room_dressing as rd
    sill = float(os.environ.get("ROOM_FROSTED_SILL", "1.95"))
    n = 0
    wins = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WindowFactory")]
    for rname, parts in rd._rooms().items():
        if not rname.startswith(prefixes) or "floor" not in parts:
            continue
        x0, x1, y0, y1, _ = to._bbox(parts["floor"]); bb = (x0, x1, y0, y1)
        for w in wins:
            pts = [w.matrix_world @ Vector(c) for c in w.bound_box]
            cx, cy = sum(p.x for p in pts) / 8, sum(p.y for p in pts) / 8
            if not (x0 - 0.4 <= cx <= x1 + 0.4 and y0 - 0.4 <= cy <= y1 + 0.4):
                continue
            side = min(((abs(cx - x0), "W"), (abs(cx - x1), "E"), (abs(cy - y0), "S"), (abs(cy - y1), "N")))[1]
            if min(abs(cx - x0), abs(cx - x1), abs(cy - y0), abs(cy - y1)) > 0.6:
                continue                                                               # not on this room's wall
            o0, ux, vx, vg, L, _d = to._frame(bb, side)
            us = [(p - o0).dot(ux) for p in pts]; zs = [p.z for p in pts]
            z0 = min(zs)
            if z0 < sill - 0.05:
                bg._patch(bpy.data.objects.get(f"{rname}.wall"), o0, ux, vx, vg, [(min(us) - 0.02, max(us) + 0.02, 0.0, min(sill, max(zs) - 0.3))])
            frost = _glow_frost()
            for sl in w.material_slots:
                if sl.material and "glass" in sl.material.name.lower():
                    sl.material = frost
            n += 1
    stats["frosted_windows"] = n
    return n
