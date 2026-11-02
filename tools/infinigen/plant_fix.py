"""Clean HSSD plant materials (O2 r24: the tall HSSD palms rendered pure white in the full pipeline although they render green in a bare scene, and replacing the slot by a fresh Principled fixed it, so something in the
material's settings / node tree after the kit passes made it white). Hooked from kit_lighting after the weather pass, only when ROOM_PLANT_FIX=1.

Every material named HSSD_MAT::* used by an object named Atrium* or *Plant* is rebuilt as a FRESH material: Principled with the first sRGB image as Base Color (a constant colour when it has none), the normal image through a
Normal Map, roughness 0.5, metallic 0, no coat. Surface settings are the Blender defaults (opaque, no HASHED blend). Weathering is not applied again (the flag `weathered`)."""
from __future__ import annotations

import bpy


def apply(stats):
    done = {}
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or not (o.name.startswith("Atrium") or "Plant" in o.name):
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.name.startswith("HSSD_MAT") or not m.use_nodes:
                continue
            if m.name not in done:
                src = m.get("ir_plant_src") or m.name
                col = None; base = None; nrm = None
                for nd in m.node_tree.nodes:
                    if nd.type == "TEX_IMAGE" and nd.image is not None and nd.image.size[0] > 0:        # an image that failed to load (size 0) would render black
                        if nd.image.colorspace_settings.name == "sRGB" and base is None:
                            base = nd.image
                        elif nd.image.colorspace_settings.name != "sRGB" and nrm is None:
                            nrm = nd.image
                b0 = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
                if base is None and b0 is not None:
                    col = tuple(b0.inputs["Base Color"].default_value)
                    if b0.inputs["Base Color"].is_linked:                                  # the weather mix replaced the constant: fall back to a leaf green
                        col = (0.05, 0.22, 0.04, 1.0)
                if base is None and col is not None and max(col[:3]) < 0.04:                          # O2 r26: a black constant (missing texture) -> leaf green
                    col = (0.05, 0.22, 0.04, 1.0)
                nm = bpy.data.materials.new(f"ir_hssd_plant_{len(done)}"); nm.use_nodes = True; N, L = nm.node_tree.nodes, nm.node_tree.links; b = N["Principled BSDF"]
                if base is not None:
                    t = N.new("ShaderNodeTexImage"); t.image = base; L.new(t.outputs["Color"], b.inputs["Base Color"])
                else:
                    b.inputs["Base Color"].default_value = col
                if nrm is not None:
                    t2 = N.new("ShaderNodeTexImage"); t2.image = nrm; nmn = N.new("ShaderNodeNormalMap"); nmn.inputs["Strength"].default_value = 0.6
                    L.new(t2.outputs["Color"], nmn.inputs["Color"]); L.new(nmn.outputs["Normal"], b.inputs["Normal"])
                b.inputs["Roughness"].default_value = 0.5; b.inputs["Metallic"].default_value = 0.0
                nm["weathered"] = True; b["weathered"] = True
                done[m.name] = nm
            sl.material = done[m.name]; n += 1
    stats["plant_fix"] = {"slots": n, "materials": len(done)}
    return n
