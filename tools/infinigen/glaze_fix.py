"""Glazed ceramic (the restroom / kitchen tiles of Infinigen 2.0's `ceramic` node group) came out with roughness ~1.0 in the ground-truth
channel (review 2026-10-17: mean 0.9 over a restroom). A glaze is 0.05-0.3; only the grout is rough. fix() caps the roughness of every
Principled BSDF inside a node group named ceramic*/porcelain*/glaze* with Math MINIMUM(rough, cap). Grout lives in other groups and is untouched."""
import bpy


def fix(cap=0.28):
    n = 0
    for g in bpy.data.node_groups:
        if g.bl_idname != "ShaderNodeTree" or not g.name.lower().startswith(("ceramic", "porcelain", "glaze")):
            continue
        for b in [x for x in g.nodes if x.type == "BSDF_PRINCIPLED"]:
            r = b.inputs["Roughness"]
            m = g.nodes.new("ShaderNodeMath"); m.operation = "MINIMUM"; m.inputs[1].default_value = cap
            if r.is_linked:
                g.links.new(r.links[0].from_socket, m.inputs[0])
            else:
                m.inputs[0].default_value = r.default_value
            g.links.new(m.outputs["Value"], r)
            n += 1
    return n
