"""Plain finishes for Infinigen's chairs (S31 r18 SRF-02: 'chair rails and legs show broad blotchy pale / dark patches' that survive IR_WEATHER_SKIP, so the blotch is in the chair's own wood / plastic shader groups). Hooked from kit_lighting after the weather pass, only when ROOM_CHAIR_PLAIN=1.

Every object named Chair* / DiningChair* (and children) with a shader_wood* slot gets a varnished-oak Principled (ROOM_CHAIR_WOOD_RGB, default 0.30,0.17,0.08, roughness 0.45); shader_rough_plastic* slots get a darker walnut (ROOM_CHAIR_FRAME_RGB, default 0.16,0.09,0.045, roughness 0.5). One shared material each, so repeated chairs match; the usage_realism per-object jitter still varies them slightly."""
from __future__ import annotations

import os

import bpy


def _mat(name, rgb, rough):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough; b["weathered"] = True
    return m


def apply(stats):
    wood = _mat("ir_chair_oak", tuple(float(v) for v in (os.environ.get("ROOM_CHAIR_WOOD_RGB") or "0.30,0.17,0.08").split(",")), 0.45)
    frame = _mat("ir_chair_walnut", tuple(float(v) for v in (os.environ.get("ROOM_CHAIR_FRAME_RGB") or "0.16,0.09,0.045").split(",")), 0.5)
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or "Chair" not in o.name.split("(")[0] or "Office" in o.name or "Task" in o.name:
            continue
        for sl in o.material_slots:
            nm = sl.material.name if sl.material else ""
            if nm.startswith("shader_wood"):
                sl.material = wood; n += 1
            elif nm.startswith("shader_rough_plastic"):
                sl.material = frame; n += 1
    stats["chair_plain"] = n
    return n
