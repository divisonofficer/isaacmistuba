"""No-bake IR prep: make a generated Infinigen scene renderable by hssd_blender_ir without the Stage-1 bake and the Stage-2 rebuild.

    run_bundled_blender.py --background SCENE.blend --python-exit-code 1 --python prepare_nobake_ir_scene.py -- --out PREPPED.blend

Validated 2026-10-13 on kr_22572521: rendering the Principled inputs straight from the procedural shaders matched the baked GT
(metallic 98-100 %, roughness 87-95 % of pixels within 0.03) and is sharper; the gaps were the bake's own slot replacements and blur.

Per material (node groups included, each tree patched once):
  * every Principled BSDF takes Base Color = mix(rgb, pseudo_nir(rgb), IR_Band). The renderer's _set_band only looks for IR_Band at a
    material's top level, so groups get an added `ir_band` input fed from there. pseudo_nir is Stage-2's own _pseudo_nir_socket.
  * GT_BaseColorRGB / GT_BaseColorNIR / GT_Roughness / GT_Metallic AOVs at the top level follow the shader closure that reaches the
    Material Output: Principled -> its inputs, Mix Shader -> the same Fac, Add Shader -> the mean, Diffuse/Glossy/Translucent/... -> their
    colour and roughness, Glass/Emission/Transparent -> 0 (the adapter marks glass/emitter/window materials invalid). Groups expose the
    same four values as added outputs.
  * GT_MaterialID = a sequential index per material.
Also the NIR flash (`__ir_nir_flash`, Stage-2 defaults) and the view-layer AOV/pass registration. The adapter runs after this.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blender_prepare_ir_principled as stage2  # noqa: E402  (main() is guarded; we reuse its pseudo-NIR + AOV helpers)
import sanitize_far_objects  # noqa: E402

CHANNELS = ("rgb", "nir", "rough", "metal")
AOVS = {"GT_BaseColorRGB": ("rgb", "COLOR"), "GT_BaseColorNIR": ("nir", "COLOR"),
        "GT_Roughness": ("rough", "VALUE"), "GT_Metallic": ("metal", "VALUE")}
COLOR_ONLY = {"BSDF_DIFFUSE": (None, 0.0), "BSDF_TRANSLUCENT": (None, 0.0), "SUBSURFACE_SCATTERING": (None, 0.0),
              "BSDF_SHEEN": (None, 0.0), "BSDF_GLOSSY": ("Roughness", 1.0), "BSDF_ANISOTROPIC": ("Roughness", 1.0)}


class Prep:
    def __init__(self):
        self.band = {}         # tree pointer -> socket carrying IR_Band inside that tree
        self.patched = {}      # principled pointer -> (rgb socket, nir socket) in its own tree
        self.group_outs = {}   # (group tree pointer, output name) -> True once the group exposes the four channels
        self.stats = {"principled": 0, "groups_patched": 0, "unknown_closures": 0}

    # ---- constants -----------------------------------------------------------------------------------------------------------
    @staticmethod
    def const(tree, value, color=False):
        if color:
            node = tree.nodes.new("ShaderNodeRGB")
            node.outputs[0].default_value = (*list(value)[:3], 1.0)
        else:
            node = tree.nodes.new("ShaderNodeValue")
            node.outputs[0].default_value = float(value)
        return node.outputs[0]

    def source(self, tree, socket, color=False):
        if socket.is_linked:
            return socket.links[0].from_socket
        value = socket.default_value
        if color and not hasattr(value, "__len__"):
            value = (value, value, value)
        return self.const(tree, value if color else (value if not hasattr(value, "__len__") else value[0]), color)

    def zeros(self, tree):
        return {"rgb": self.const(tree, (0, 0, 0), True), "nir": self.const(tree, (0, 0, 0), True),
                "rough": self.const(tree, 0.0), "metal": self.const(tree, 0.0)}

    # ---- IR_Band ------------------------------------------------------------------------------------------------------------
    def band_in(self, tree):
        key = tree.as_pointer()
        if key not in self.band:                     # a group tree: an added float input
            if "ir_band" not in [i.name for i in tree.interface.items_tree if getattr(i, "in_out", "") == "INPUT"]:
                tree.interface.new_socket("ir_band", in_out="INPUT", socket_type="NodeSocketFloat")
            gi = next((n for n in tree.nodes if n.type == "GROUP_INPUT"), None) or tree.nodes.new("NodeGroupInput")
            self.band[key] = gi.outputs["ir_band"]
        return self.band[key]

    def patch_tree(self, tree, seen):
        """IR_Band mix in front of every Principled Base Color, through every nested group."""
        if tree.as_pointer() in seen:
            return
        seen.add(tree.as_pointer())
        band = self.band_in(tree)
        for node in list(tree.nodes):
            color_input = "Base Color" if node.type == "BSDF_PRINCIPLED" else "Color" if node.type in COLOR_ONLY else None
            if color_input and color_input in node.inputs and node.as_pointer() not in self.patched:
                rgb = self.source(tree, node.inputs[color_input], color=True)
                nir = stage2._pseudo_nir_socket(tree, rgb)
                mix = tree.nodes.new("ShaderNodeMixRGB")
                mix.blend_type = "MIX"
                tree.links.new(band, mix.inputs[0])
                tree.links.new(rgb, mix.inputs[1])
                tree.links.new(nir, mix.inputs[2])
                tree.links.new(mix.outputs[0], node.inputs[color_input])
                self.patched[node.as_pointer()] = (rgb, nir)
                self.stats["principled"] += 1
            elif node.type == "GROUP" and node.node_tree is not None:
                inner = node.node_tree
                if inner.as_pointer() not in seen:
                    self.stats["groups_patched"] += 1
                self.patch_tree(inner, seen)
                if "ir_band" in node.inputs:
                    tree.links.new(band, node.inputs["ir_band"])

    # ---- closure -> channels ------------------------------------------------------------------------------------------------
    def mix_values(self, tree, fac, a, b):
        out = {}
        for ch in CHANNELS:
            if ch in ("rgb", "nir"):
                m = tree.nodes.new("ShaderNodeMixRGB"); m.blend_type = "MIX"
                tree.links.new(fac, m.inputs[0]); tree.links.new(a[ch], m.inputs[1]); tree.links.new(b[ch], m.inputs[2])
            else:
                m = tree.nodes.new("ShaderNodeMix"); m.data_type = "FLOAT"
                tree.links.new(fac, m.inputs[0]); tree.links.new(a[ch], m.inputs[2]); tree.links.new(b[ch], m.inputs[3])
            out[ch] = m.outputs[0]
        return out

    def channels(self, tree, shader_socket, depth=0):
        """The four GT values of the closure arriving through shader_socket, as sockets in `tree`."""
        node = shader_socket.node
        kind = node.type
        if depth > 40:
            return self.zeros(tree)
        if kind == "REROUTE":
            return self.channels(tree, node.inputs[0].links[0].from_socket, depth + 1) if node.inputs[0].is_linked else self.zeros(tree)
        if kind == "BSDF_PRINCIPLED":
            rgb, nir = self.patched[node.as_pointer()]
            return {"rgb": rgb, "nir": nir, "rough": self.source(tree, node.inputs["Roughness"]),
                    "metal": self.source(tree, node.inputs["Metallic"])}
        if kind in ("MIX_SHADER", "ADD_SHADER"):
            sides = [s for s in (node.inputs[1], node.inputs[2]) if s.is_linked] if kind == "MIX_SHADER" else \
                    [s for s in node.inputs if s.is_linked]
            vals = [self.channels(tree, s.links[0].from_socket, depth + 1) for s in sides]
            if not vals:
                return self.zeros(tree)
            if len(vals) == 1:
                return vals[0]
            fac = self.source(tree, node.inputs[0]) if kind == "MIX_SHADER" else self.const(tree, 0.5)
            return self.mix_values(tree, fac, vals[0], vals[1])
        if kind in COLOR_ONLY:
            rough_input, metal = COLOR_ONLY[kind]
            rgb, nir = self.patched.get(node.as_pointer()) or (self.const(tree, (0, 0, 0), True),) * 2
            rough = self.source(tree, node.inputs[rough_input]) if rough_input and rough_input in node.inputs else self.const(tree, 1.0)
            return {"rgb": rgb, "nir": nir, "rough": rough, "metal": self.const(tree, metal)}
        if kind == "GROUP" and node.node_tree is not None:
            return self.group_channels(tree, node, shader_socket.name, depth)
        if kind not in ("BSDF_GLASS", "BSDF_REFRACTION", "BSDF_TRANSPARENT", "EMISSION", "HOLDOUT", "BACKGROUND"):
            self.stats["unknown_closures"] += 1
        return self.zeros(tree)

    def group_channels(self, tree, gnode, out_name, depth):
        inner = gnode.node_tree
        key = (inner.as_pointer(), out_name)
        names = {ch: f"ir_{ch}__{out_name}" for ch in CHANNELS}
        if key not in self.group_outs:
            go = next((n for n in inner.nodes if n.type == "GROUP_OUTPUT" and n.is_active_output), None) or \
                 next((n for n in inner.nodes if n.type == "GROUP_OUTPUT"), None)
            target = go.inputs.get(out_name) if go else None
            vals = self.channels(inner, target.links[0].from_socket, depth + 1) if target is not None and target.is_linked \
                else self.zeros(inner)
            for ch in CHANNELS:
                stype = "NodeSocketColor" if ch in ("rgb", "nir") else "NodeSocketFloat"
                inner.interface.new_socket(names[ch], in_out="OUTPUT", socket_type=stype)
            go = next((n for n in inner.nodes if n.type == "GROUP_OUTPUT" and n.is_active_output), None) or \
                 next((n for n in inner.nodes if n.type == "GROUP_OUTPUT"), None) or inner.nodes.new("NodeGroupOutput")
            for ch in CHANNELS:
                inner.links.new(vals[ch], go.inputs[names[ch]])
            self.group_outs[key] = True
        return {ch: gnode.outputs[names[ch]] for ch in CHANNELS}


GLASS_TYPES = {"BSDF_GLASS", "BSDF_REFRACTION"}


def _has_glass(tree, seen=None):
    seen = set() if seen is None else seen
    if tree is None or tree.as_pointer() in seen:
        return False
    seen.add(tree.as_pointer())
    for n in tree.nodes:
        if n.type in GLASS_TYPES:
            return True
        if n.type == "BSDF_PRINCIPLED":
            t = n.inputs.get("Transmission Weight") or n.inputs.get("Transmission")
            if t is not None and (t.is_linked or t.default_value > 0.05):
                return True
        if n.type == "GROUP" and _has_glass(n.node_tree, seen):
            return True
    return False


def light_through_glass(tree, out) -> bool:
    """Glass for camera rays, transparent for every other ray. Cycles blocks direct sun behind a Glass BSDF (no caustics), so with
    real window panes a room got ~1/800 of v1's light; Stage-2 used opaque panes + portal emitters instead. GT is unaffected: these
    materials are pbr-invalid anyway."""
    if not _has_glass(tree):
        return False
    surface = out.inputs["Surface"].links[0].from_socket
    path = tree.nodes.new("ShaderNodeLightPath")
    clear = tree.nodes.new("ShaderNodeBsdfTransparent")
    mix = tree.nodes.new("ShaderNodeMixShader")
    tree.links.new(path.outputs["Is Camera Ray"], mix.inputs[0])
    tree.links.new(clear.outputs[0], mix.inputs[1])
    tree.links.new(surface, mix.inputs[2])
    tree.links.new(mix.outputs[0], out.inputs["Surface"])
    return True


def material_output(tree):
    outs = [n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"]
    return next((n for n in outs if n.is_active_output), None) or (outs[0] if outs else None)


def install_flash():
    """Stage-2's _install_flash with its CLI defaults (40 W spot, 22 deg beam, 30 deg cutoff, 0.10 m below the lens)."""
    defaults = argparse.Namespace(flash_energy=40.0, flash_offset_y=-0.10, flash_beam_width=22.0, flash_cutoff_angle=30.0)
    return stage2._install_flash(defaults).name


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    prep, report, mat_id = Prep(), {"materials": 0, "no_output": 0}, 0
    # Stray pillars at ~1e23 m hang walk planning. The 1000 m default also deletes legitimate outdoor terrain, haze
    # domes and far ridges (PH04/06/14/16 lost their ground, 10-31); outdoor scenes set NOBAKE_FAR_LIMIT_M (e.g. 1e5).
    # GT channels are written with a Raw view transform that still inherits scene exposure/gamma (OVERRIDE copies
    # them), so a builder's look exposure scaled and clipped albedo/roughness/normal PNGs (PH11 +1 EV: 49% of albedo
    # pixels at 1.0; CS06 -2 EV: albedo capped at 0.25; found 11-01). Dataset frames are radiometric: no look exposure.
    vs = bpy.context.scene.view_settings
    report["view_exposure_reset"] = {"exposure": vs.exposure, "gamma": vs.gamma}
    if os.environ.get("NOBAKE_KEEP_EXPOSURE") != "1":
        vs.exposure, vs.gamma = 0.0, 1.0
    report["far_objects_removed"] = sanitize_far_objects.remove_far_objects(float(os.environ.get("NOBAKE_FAR_LIMIT_M", "1000")))
    for mat in sorted(bpy.data.materials, key=lambda m: m.name):
        if not (mat.use_nodes and mat.node_tree):
            continue
        tree = mat.node_tree
        out = material_output(tree)
        if out is None or not out.inputs["Surface"].is_linked:
            report["no_output"] += 1
            continue
        band = tree.nodes.new("ShaderNodeValue")
        band.name = band.label = "IR_Band"
        band.outputs[0].default_value = 0.0
        prep.band[tree.as_pointer()] = band.outputs[0]
        prep.patch_tree(tree, set())
        if mat.name.startswith("ir_screen_"):        # an LCD emits next to no NIR (tidy_objects_infinigen2 names the lit screens)
            for node in [n for n in tree.nodes if n.type == "BSDF_PRINCIPLED" and not n.inputs["Emission Strength"].is_linked]:
                off = tree.nodes.new("ShaderNodeMath"); off.operation = "MULTIPLY_ADD"     # strength * (1 - band)
                tree.links.new(band.outputs[0], off.inputs[0])
                off.inputs[1].default_value = -node.inputs["Emission Strength"].default_value
                off.inputs[2].default_value = node.inputs["Emission Strength"].default_value
                tree.links.new(off.outputs[0], node.inputs["Emission Strength"])
                report["screens_nir_off"] = report.get("screens_nir_off", 0) + 1
        vals = prep.channels(tree, out.inputs["Surface"].links[0].from_socket)
        for aov, (ch, kind) in AOVS.items():
            stage2._aov(tree, aov, vals[ch], kind=kind)
        report["glass_passthrough"] = report.get("glass_passthrough", 0) + int(light_through_glass(tree, out))
        mat_id += 1
        stage2._aov(tree, "GT_MaterialID", prep.const(tree, float(mat_id)), kind="VALUE")
        report["materials"] += 1
    for view_layer in bpy.context.scene.view_layers:
        for name, kind in [(k, v[1]) for k, v in AOVS.items()] + [("GT_MaterialID", "VALUE")]:
            item = view_layer.aovs.get(name) or view_layer.aovs.add()
            item.name, item.type = name, kind
        view_layer.use_pass_z = view_layer.use_pass_normal = view_layer.use_pass_object_index = True
    # v1's rooms are lit mostly by these window portals (the daylight rig sets them to ~100 W/m2); sun + sky through the panes is a
    # small share, so without them a no-bake frame came out ~1/800 as bright as v1.
    portals = stage2._install_external_portals()
    report.update(prep.stats, flash=install_flash(), portals=len(portals["panels"]))
    bpy.ops.wm.save_as_mainfile(filepath=a.out, copy=True)
    json.dump(report, open(a.out + ".nobake_prep.json", "w"), indent=1)
    print("NOBAKE_PREP", json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
