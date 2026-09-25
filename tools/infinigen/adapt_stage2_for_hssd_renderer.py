#!/usr/bin/env python3
"""Make an Infinigen Stage-2 blend renderable by the HSSD renderer.

Writes a copy; the original is what this pipeline's own renderer uses and is
left exactly as it was. Three differences to reconcile, each read out of
modules/hssd_blender_ir/tools/blender_render_hssd_ir_sample.py rather than
guessed:

  1. `__ir_nir_flash` is a *controller* there, and `_flash()` toggles
     `hide_render` on its **children**. Here it is the flash light itself, so
     that loop finds nothing to toggle and the flash never turns on -- active
     NIR would come out identical to passive, silently. So: an empty takes the
     name, and the light becomes its child.
  2. The renderer wires `Combined_NIR_FLASH` off the render-layer node, which
     exists only once the light group is registered on the view layer. The
     lights already carry the group names; the view layer does not.
  3. It reads Depth, Normal and the three Diffuse passes.

The eleven HSSD-only AOVs (GT_RoughnessRawGLTF, the four MR provenance masks,
GT_MRConfidence, the two *Effective channels, GT_GlassMask, GT_PBRInvalidMask,
GT_LayerCount) are deliberately NOT registered. An AOV registered with nothing
driving it renders as zeros, and a zeroed MRConfidence would read as a
measurement of this corpus rather than the absence of one. The renderer skips a
missing output (`if source is None: continue`) and writes no file, which is the
honest representation: the channel is absent, not zero.

Usage (inside Blender):
  blender --background <stage2.blend> --python-exit-code 1 \
    --python adapt_stage2_for_hssd_renderer.py -- --out <adapted.blend>
"""
from __future__ import annotations

import json
import sys

import bpy

FLASH = "__ir_nir_flash"
LIGHT_GROUPS = ("NIR_FLASH", "DATASET_AMBIENT_FILL")


# `_closeup_target_objects` and `_frame_content` both gate on two custom
# properties the HSSD builder writes: role "interior_asset" and a non-empty
# `hssd_source_id`. Nothing in an Infinigen blend carries them, so every pose
# mode that picks its subject from the scene finds an empty candidate set and
# raises. Tagging is the whole fix -- the geometry was always eligible.
OPENING_TOKENS = ("door", "window")
# Same tuple as ir_view_utility.STRUCTURAL, minus the two above: shell geometry
# must not become a closeup subject, and must not count as foreground evidence.
STRUCTURE_TOKENS = ("wall", "floor", "ceiling", "exterior", "room", "staircase", "stair")


def _role(name: str) -> str | None:
    low = name.lower()
    if any(token in low for token in OPENING_TOKENS):
        return "opening"
    if any(token in low for token in STRUCTURE_TOKENS):
        return None
    return "interior_asset"


def tag_asset_roles() -> dict:
    """Give Infinigen meshes the HSSD role/source properties, by name."""
    counts = {"interior_asset": 0, "opening": 0, "structure": 0}
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        role = _role(obj.name)
        if role is None:
            counts["structure"] += 1
            obj["hssd_asset_role"] = "structure"
            continue
        obj["hssd_asset_role"] = role
        # Infinigen names read `SomeFactory(12345).spawn_asset(678)`; the factory
        # is the stable identity across instances, which is what source_id means
        # on the HSSD side, and the full name is unique per instance.
        obj["hssd_source_id"] = obj.name.split("(")[0] or obj.name
        obj["hssd_instance_id"] = obj.name
        counts[role] += 1
    return counts


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    return ap.parse_args(argv)


def reparent_flash() -> dict:
    """Give the controller name to an empty and hang the flash light under it."""
    obj = bpy.data.objects.get(FLASH)
    if obj is None:
        return {"status": "absent", "note": "no flash object to adapt"}
    if obj.type == "EMPTY":
        return {"status": "already_controller", "children": [c.name for c in obj.children]}
    obj.name = f"{FLASH}_lamp"
    ctl = bpy.data.objects.new(FLASH, None)          # empty
    bpy.context.scene.collection.objects.link(ctl)
    ctl.matrix_world = obj.matrix_world.copy()
    obj.parent = ctl
    obj.matrix_parent_inverse = ctl.matrix_world.inverted()
    # _flash() sets hide_render on children per frame; start hidden as passive.
    obj.hide_render = True
    return {"status": "reparented", "controller": ctl.name, "child": obj.name}


def register_light_groups(view_layer) -> list[str]:
    for name in LIGHT_GROUPS:
        if view_layer.lightgroups.get(name) is None:
            view_layer.lightgroups.add().name = name
    return sorted(g.name for g in view_layer.lightgroups)


def enable_passes(view_layer) -> dict:
    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True
    view_layer.use_pass_diffuse_direct = True
    view_layer.use_pass_diffuse_indirect = True
    view_layer.use_pass_diffuse_color = True
    return {k: True for k in ("z", "normal", "diffuse_direct", "diffuse_indirect", "diffuse_color")}


def main() -> int:
    a = _args()
    vl = bpy.context.scene.view_layers[0]
    report = {
        "schema": "robomituba.stage2_hssd_adapter.v1",
        "source_blend": bpy.data.filepath,
        "flash": reparent_flash(),
        "asset_roles": tag_asset_roles(),
        "lightgroups": register_light_groups(vl),
        "passes": enable_passes(vl),
        "aovs_registered": sorted(x.name for x in vl.aovs),
        "hssd_only_aovs_left_unregistered": [
            "GT_RoughnessRawGLTF", "GT_MetallicRawGLTF", "GT_MRExplicitMask",
            "GT_MRInferredMask", "GT_MRTrainingValidMask", "GT_MRConfidence",
            "GT_RoughnessEffective", "GT_MetallicEffective", "GT_GlassMask",
            "GT_PBRInvalidMask", "GT_LayerCount"],
        "why_unregistered": ("an AOV with nothing driving it renders as zeros; the renderer skips a "
                             "missing output and writes no file, so absent beats zero"),
        "out_blend": a.out,
    }
    bpy.ops.wm.save_as_mainfile(filepath=a.out, copy=True)
    print("ADAPTED " + json.dumps(report), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
