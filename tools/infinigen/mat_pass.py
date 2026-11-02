"""Global material pass (realism program P1; ROOM_MAT_PASS=1, kit stage, after weather_pass). Only edits Principled inputs, so albedo / roughness / normal GT channels carry every change.

  walls / ceilings   the weather pass's big 'dirty stucco' patches (noise scale 1.6, mapped 0.38..0.72 -> 0..1) are compressed to 0..ROOM_MAT_PATCH (default 0.2): albedo blotching falls from ~25 % to ~4 %; the fine grain, the
                     crevice AO and the micro-normal stay. Wall / ceiling roughness gets 5-20 cm meso noise (+-0.05) on top of whatever it had.
  floors             every floor material that is not a scanned wood gets a 1 m macro roughness noise (+-ROOM_MAT_FLOOR_ROUGH, default 0.07) added to its Principled roughness (polished concrete / porcelain read as polished,
                     not as one flat value); a per-object hue / value jitter is not added here (planks vary in the scanned_wood / herringbone modules).
Idempotent: a material holding the flag ir_mat_pass is skipped."""
from __future__ import annotations

import os

import bpy


def _noise_add(m, scale, amp, tag):
    nt = m.node_tree; N, L = nt.nodes, nt.links
    for b in [x for x in N if x.type == "BSDF_PRINCIPLED"]:
        if b.get(tag):
            continue
        geo = N.new("ShaderNodeNewGeometry"); nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = scale; nz.inputs["Detail"].default_value = 5.0; L.new(geo.outputs["Position"], nz.inputs["Vector"])
        mr = N.new("ShaderNodeMapRange"); mr.inputs["To Min"].default_value = -amp; mr.inputs["To Max"].default_value = amp; L.new(nz.outputs["Fac"], mr.inputs["Value"])
        ad = N.new("ShaderNodeMath"); ad.operation = "ADD"; ad.use_clamp = True
        if b.inputs["Roughness"].is_linked:
            L.new(b.inputs["Roughness"].links[0].from_socket, ad.inputs[0])
        else:
            ad.inputs[0].default_value = b.inputs["Roughness"].default_value
        L.new(mr.outputs["Result"], ad.inputs[1]); L.new(ad.outputs["Value"], b.inputs["Roughness"]); b[tag] = True


def _is_patch(nd):
    try:
        return nd.type == "MAP_RANGE" and nd.data_type == "FLOAT" and abs(nd.inputs[1].default_value - 0.38) < 1e-3 and abs(nd.inputs[2].default_value - 0.72) < 1e-3
    except Exception:                                                                  # noqa: BLE001 -- a vector map range: not ours
        return False


def _is_fine(nd):
    try:
        return nd.type == "MAP_RANGE" and nd.data_type == "FLOAT" and abs(nd.inputs[1].default_value - 0.40) < 1e-3 and abs(nd.inputs[2].default_value - 0.66) < 1e-3
    except Exception:                                                                  # noqa: BLE001
        return False


def _calm_ceiling(m, fine_max=0.06, rough=0.85, bump=0.03):
    """A ceiling reads as flat matte paint (P2b r33 'coarse speckle that reads like carpet'): the weather pass's fine speckle (noise 26, mapped 0.40..0.66) is squashed to 0..fine_max, the micro bump
    to `bump`, and the roughness is floored at `rough`."""
    nt = m.node_tree
    for nd in nt.nodes:
        if _is_fine(nd):
            nd.inputs[4].default_value = min(nd.inputs[4].default_value, fine_max)
        elif nd.type == "BUMP":
            nd.inputs["Strength"].default_value = min(nd.inputs["Strength"].default_value, bump)
    for b in [x for x in nt.nodes if x.type == "BSDF_PRINCIPLED" and not x.get("ir_ceil_rough")]:
        mx = nt.nodes.new("ShaderNodeMath"); mx.operation = "MAXIMUM"; mx.inputs[1].default_value = rough
        if b.inputs["Roughness"].is_linked:
            nt.links.new(b.inputs["Roughness"].links[0].from_socket, mx.inputs[0])
        else:
            mx.inputs[0].default_value = b.inputs["Roughness"].default_value
        nt.links.new(mx.outputs[0], b.inputs["Roughness"]); b["ir_ceil_rough"] = True


def _compress_patches(m, to_max):
    n = 0
    trees = [m.node_tree] + [x.node_tree for x in m.node_tree.nodes if x.type == "GROUP" and x.node_tree]
    for t in trees:
        for nd in t.nodes:
            if _is_patch(nd):
                nd.inputs[4].default_value = min(nd.inputs[4].default_value, to_max); n += 1                  # 'To Max' of the float map range
    return n


def apply(stats):
    if os.environ.get("ROOM_HOME_SURF") == "1":
        home_surfaces(stats)
    if os.environ.get("ROOM_MAT_PASS") != "1":
        return 0
    to_max = float(os.environ.get("ROOM_MAT_PATCH") or 0.2); fr = float(os.environ.get("ROOM_MAT_FLOOR_ROUGH") or 0.07)
    done, nw, nf = set(), 0, 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        kind = "wall" if o.name.endswith((".wall", ".ceiling")) else "floor" if o.name.endswith(".floor") else None
        if kind is None:
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes or m.name in done or m.get("ir_mat_pass") or m.get("scanned_wood"):
                continue
            done.add(m.name)
            if kind == "wall":
                _compress_patches(m, to_max); _noise_add(m, 14.0, 0.05, "ir_mat_meso"); nw += 1
                if o.name.endswith(".ceiling") and "timber" not in m.name.lower():
                    _calm_ceiling(m)
            else:
                _noise_add(m, 1.0, fr, "ir_mat_macro"); nf += 1
            m["ir_mat_pass"] = True
    stats["mat_pass"] = {"wall_materials": nw, "floor_materials": nf}
    return nw + nf


def home_surfaces(stats):
    """ROOM_HOME_SURF=1 (P2b r33): kitchen steel and counters. Fridge / oven / run steel (ir_bf_steel, ir_kit_steel, ir_kit_fridge, ir_ot_steel) -> one uniform brushed stainless Principled (metallic 1, roughness 0.25,
    anisotropy 0.6; the streak bands went); counter and island tops (ir_kit_top, ir_isl_stone) -> veined white quartz (a distorted Wave band ramp, roughness 0.15, clear coat 0.5). Principled inputs only."""
    steel = ("ir_bf_steel", "ir_kit_steel", "ir_kit_fridge", "ir_ot_steel"); tops = ("ir_kit_top", "ir_isl_stone")
    ns = nt_ = 0
    for m in bpy.data.materials:
        if not m.use_nodes or m.get("ir_home_surf") or m.name.split(".")[0] not in steel + tops:
            continue
        N, L = m.node_tree.nodes, m.node_tree.links
        for nd in list(N):
            if nd.type != "OUTPUT_MATERIAL":
                N.remove(nd)
        out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
        b = N.new("ShaderNodeBsdfPrincipled"); L.new(b.outputs["BSDF"], out.inputs["Surface"])
        if m.name.split(".")[0] in steel:
            b.inputs["Base Color"].default_value = (0.66, 0.67, 0.69, 1); b.inputs["Metallic"].default_value = 1.0; b.inputs["Roughness"].default_value = 0.25
            if "Anisotropic" in b.inputs:
                b.inputs["Anisotropic"].default_value = 0.6
            ns += 1
        else:
            tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); wv.inputs["Scale"].default_value = 2.4; wv.inputs["Distortion"].default_value = 14.0; wv.inputs["Detail"].default_value = 3.0; L.new(tc.outputs["Object"], wv.inputs["Vector"])
            rp = N.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].position = 0.44; rp.color_ramp.elements[0].color = (0.8, 0.8, 0.82, 1); rp.color_ramp.elements[1].position = 0.56; rp.color_ramp.elements[1].color = (0.93, 0.93, 0.91, 1); L.new(wv.outputs["Fac"], rp.inputs["Fac"])
            L.new(rp.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.15
            if "Coat Weight" in b.inputs:
                b.inputs["Coat Weight"].default_value = 0.5; b.inputs["Coat Roughness"].default_value = 0.05
            nt_ += 1
        m["ir_home_surf"] = True; m["weathered"] = True; b["weathered"] = True
    stats["home_surf"] = {"steel": ns, "tops": nt_}
    return ns + nt_
