"""Tiny subprocess sanity check for packed scalar Blender Color AOVs.

This intentionally creates a fresh plane and a synthetic Principled material;
it does not open or modify the kitchen blend.  The test answers one narrow
question: does Cycles preserve roughness/metallic packed into RGB AOV channels?

Example::

  python tools/infinigen/run_bundled_blender.py --background --python \
    tools/infinigen/blender_aov_scalar_sanity.py -- --out /tmp/aov_sanity
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def _file_output(tree, layers, socket_name: str, stem: str, out: Path):
    socket = layers.outputs.get(socket_name)
    if socket is None:
        raise RuntimeError(f"render layer socket not found: {socket_name}")
    node = tree.nodes.new("CompositorNodeOutputFile")
    node.name = f"Sanity_{stem}"
    node.base_path = str(out)
    node.format.file_format = "OPEN_EXR"
    node.format.color_depth = "32"
    node.format.color_mode = "RGB"
    node.format.exr_codec = "ZIP"
    node.file_slots[0].path = stem
    tree.links.new(socket, node.inputs[0])


def main() -> int:
    args = _args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.render.resolution_x = 16
    scene.render.resolution_y = 16
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    world = bpy.data.worlds.new("SanityWorld")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0

    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
    plane = bpy.context.object
    material = bpy.data.materials.new("SanityPrincipled")
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.2, 0.3, 0.4, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.37
    bsdf.inputs["Metallic"].default_value = 0.81
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    plane.data.materials.append(material)

    aov = bpy.context.view_layer.aovs.add()
    aov.name = "GT_PBR_PARAMS"
    aov.type = "COLOR"
    aov_base = bpy.context.view_layer.aovs.add()
    aov_base.name = "GT_BASE_COLOR"
    aov_base.type = "COLOR"
    combine = tree.nodes.new("ShaderNodeCombineColor")
    combine.inputs["Red"].default_value = 0.37
    combine.inputs["Green"].default_value = 0.81
    combine.inputs["Blue"].default_value = 1.0
    pbr_out = tree.nodes.new("ShaderNodeOutputAOV")
    pbr_out.aov_name = "GT_PBR_PARAMS"
    tree.links.new(combine.outputs.get("Color") or combine.outputs[0], pbr_out.inputs["Color"])
    base_out = tree.nodes.new("ShaderNodeOutputAOV")
    base_out.aov_name = "GT_BASE_COLOR"
    base_rgb = tree.nodes.new("ShaderNodeRGB")
    base_rgb.outputs[0].default_value = (0.2, 0.3, 0.4, 1.0)
    tree.links.new(base_rgb.outputs[0], base_out.inputs["Color"])

    bpy.ops.object.camera_add(location=(0, 0, 2.0))
    camera = bpy.context.object
    camera.rotation_euler = (0.0, 0.0, 0.0)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 2.2
    scene.camera = camera

    scene.use_nodes = True
    comp = scene.node_tree
    comp.nodes.clear()
    layers = comp.nodes.new("CompositorNodeRLayers")
    _file_output(comp, layers, "GT_PBR_PARAMS", "pbr_params", out)
    _file_output(comp, layers, "GT_BASE_COLOR", "base_color", out)
    bpy.ops.render.render(write_still=False)
    result = {
        "schema": "robomituba.blender_aov_scalar_sanity.v1",
        "roughness_expected": 0.37,
        "metallic_expected": 0.81,
        "base_color_expected": [0.2, 0.3, 0.4],
        "out": str(out),
    }
    (out / "sanity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
