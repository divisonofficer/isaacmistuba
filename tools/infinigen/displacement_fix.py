"""Infinigen 2.0 brick/masonry materials hand their displacement to the Material Output as a raw vector. Cycles' bump method then reads it
as a colour average with no scale, and the GT normal of a brick wall comes out flat ('brick normals cannot be felt', user 2026-10-17).
fix() routes every such link through a Displacement node (height = the vector's mean, in metres) so the bump has a real physical depth."""
import bpy


def fix(scale=1.0):
    n = 0
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        nt = m.node_tree
        for o in [x for x in nt.nodes if x.type == "OUTPUT_MATERIAL"]:
            sock = o.inputs["Displacement"]
            if not sock.is_linked or sock.links[0].from_node.type == "DISPLACEMENT":
                continue
            src = sock.links[0].from_socket
            d = nt.nodes.new("ShaderNodeDisplacement"); d.inputs["Midlevel"].default_value = 0.0; d.inputs["Scale"].default_value = scale
            nt.links.new(src, d.inputs["Height"]); nt.links.new(d.outputs["Displacement"], sock)
            m.displacement_method = "BUMP"; n += 1
    return n
