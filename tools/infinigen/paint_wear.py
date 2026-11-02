"""Wear on painted metal (user/review 2026-10-17: metallic is binary per material; intermediate values belong in spatial masks).
Painted metal is a dielectric (metallic 0, see proc_assets.PAINTED_METAL); this pass lets bare steel show where paint wears off:
convex edges and sparse chips get metallic 1, a lower roughness and a steel base colour. The mask is binary (a hard threshold), so the ground
truth stays 0/1 with intermediate values only on the anti-aliased boundary.
    from paint_wear import apply; apply()          # inside a bpy session, after weather_pass
"""
import bpy

PAINTED = ("ir_arch_black_metal", "ir_arch_duct", "ir_black_metal", "ir_desk_frame", "ir_filer", "ir_office_door_frame", "ir_linear_body",
           "ir_pedestal", "ir_rack", "ir_locker", "ir_hanger", "ir_cart")
STEEL = (0.56, 0.57, 0.6, 1.0)


def _n(nt, kind, **kw):
    n = nt.nodes.new(kind)
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def apply(chip_density=0.55, edge_width=0.004):
    done = 0
    for m in bpy.data.materials:
        if not m.use_nodes or not m.users or not m.name.startswith(PAINTED):
            continue
        nt = m.node_tree
        for b in [x for x in nt.nodes if x.type == "BSDF_PRINCIPLED"]:
            if b.inputs["Metallic"].is_linked:
                continue
            bev = _n(nt, "ShaderNodeBevel"); bev.samples = 4; bev.inputs["Radius"].default_value = edge_width
            geo = _n(nt, "ShaderNodeNewGeometry")
            dot = _n(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")
            nt.links.new(bev.outputs["Normal"], dot.inputs[0]); nt.links.new(geo.outputs["Normal"], dot.inputs[1])
            edge = _n(nt, "ShaderNodeMath", operation="LESS_THAN"); edge.inputs[1].default_value = 0.985       # convex edge: bevel normal leans off
            nt.links.new(dot.outputs["Value"], edge.inputs[0])
            tc = _n(nt, "ShaderNodeTexCoord"); noise = _n(nt, "ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 38.0
            nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
            chip = _n(nt, "ShaderNodeMath", operation="GREATER_THAN"); chip.inputs[1].default_value = 1.0 - chip_density
            nt.links.new(noise.outputs["Fac"], chip.inputs[0])
            mask = _n(nt, "ShaderNodeMath", operation="MULTIPLY")                                              # chips only along edges
            nt.links.new(edge.outputs["Value"], mask.inputs[0]); nt.links.new(chip.outputs["Value"], mask.inputs[1])
            nt.links.new(mask.outputs["Value"], b.inputs["Metallic"])
            col0 = tuple(b.inputs["Base Color"].default_value)
            mix = _n(nt, "ShaderNodeMix", data_type="RGBA"); mix.inputs["A"].default_value = col0; mix.inputs["B"].default_value = STEEL
            if b.inputs["Base Color"].is_linked:
                nt.links.new(b.inputs["Base Color"].links[0].from_socket, mix.inputs["A"])
            nt.links.new(mask.outputs["Value"], mix.inputs["Factor"]); nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
            r0 = b.inputs["Roughness"].default_value
            rm = _n(nt, "ShaderNodeMath", operation="MULTIPLY_ADD")        # roughness: r0 on paint, 0.4 on bare steel
            rm.inputs[1].default_value = 0.4 - r0; rm.inputs[2].default_value = r0
            nt.links.new(mask.outputs["Value"], rm.inputs[0]); nt.links.new(rm.outputs["Value"], b.inputs["Roughness"])
            done += 1
    return done
