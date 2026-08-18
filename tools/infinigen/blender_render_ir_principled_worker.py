"""Persistent Blender/Cycles worker for the opaque RGB/active-NIR dataset."""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

import bpy  # type: ignore
from mathutils import Matrix  # type: ignore


_REC709 = (0.2126, 0.7152, 0.0722)
_PNG16_MAX = 65535.0
_DIFFUSE_EPSILON = 1e-4
_GT_SPECS = {
    "base_color_rgb": ("GT_BaseColorRGB", "RGB", "16", "linear_unorm16"),
    "base_color_nir": ("GT_BaseColorNIR", "RGB", "16", "linear_unorm16"),
    "roughness": ("GT_Roughness", "BW", "16", "perceptual_roughness_unorm16"),
    "metallic": ("GT_Metallic", "BW", "16", "unorm16"),
    "normal_geometry_world": ("GT_GeometryNormalWorld", "RGB", "16", "xyz_signed_to_unorm16"),
    "normal_shading_world": ("GT_ShadingNormalWorld", "RGB", "16", "xyz_signed_to_unorm16"),
    # Cycles' Z pass is camera-to-surface ray distance.  The parent derives
    # planar camera-Z depth from this range and the recorded intrinsics.
    "range": ("Depth", "BW", "16", "millimeters_u16"),
    "object_id": ("IndexOB", "BW", "16", "uint16"),
    "material_id": ("GT_MaterialID", "BW", "16", "uint16"),
    "gt_defined_mask": ("GT_Defined", "BW", "8", "binary_mask_u8"),
    "source_valid_mask": ("GT_SourceValid", "BW", "8", "binary_mask_u8"),
    "replacement_mask": ("GT_Replacement", "BW", "8", "binary_mask_u8"),
    "fallback_mask": ("GT_Fallback", "BW", "8", "binary_mask_u8"),
    "primary_eval_valid_mask": ("GT_SourceValid", "BW", "8", "binary_mask_u8"),
}
_DIFFUSE_EXR_STEMS = {
    "rgb": ("diffuse_component_rgb", "diffuse_shading_rgb"),
    "nir": ("diffuse_component_nir", "diffuse_shading_nir"),
}
_DIFFUSE_PNG_STEMS = {
    "rgb": ("diffuse_reflectance_rgb", "diffuse_shading_valid_rgb"),
    "nir": ("diffuse_reflectance_nir", "diffuse_shading_valid_nir"),
}


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--fov", type=float, required=True)
    parser.add_argument("--rgb-spp", type=int, required=True)
    parser.add_argument("--nir-spp", type=int, required=True)
    parser.add_argument("--max-bounces", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--device", choices=("OPTIX", "CUDA"), default="OPTIX")
    parser.add_argument("--qc-components", action="store_true")
    parser.add_argument("--nir-formula", choices=("primary", "luminance_matched_v1"), default="primary")
    parser.add_argument("--flash-energy-scale", type=float, default=1.0)
    parser.add_argument("--ambient-fill-energy-scale", type=float, default=1.0)
    return parser.parse_args(argv)


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def _configure_cycles(scene, args: argparse.Namespace) -> list[str]:
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU"
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = int(args.max_bounces)
    scene.cycles.use_adaptive_sampling = False
    scene.render.resolution_x = int(args.width)
    scene.render.resolution_y = int(args.height)
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "32"
    scene.view_settings.view_transform = "Raw"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = args.device
    prefs.get_devices()
    enabled = []
    for device in prefs.devices:
        device.use = device.type == args.device
        if device.use:
            enabled.append(device.name)
    if not enabled:
        raise RuntimeError(f"Cycles exposes no {args.device} device under CUDA_VISIBLE_DEVICES")
    return enabled


def _view_layer_setup(scene) -> None:
    for view_layer in scene.view_layers:
        for source, _, _, _ in _GT_SPECS.values():
            if source.startswith("GT_") and view_layer.aovs.get(source) is None:
                raise RuntimeError(f"prepared blend lacks required AOV: {source}")
        view_layer.use_pass_z = True
        view_layer.use_pass_normal = True
        view_layer.use_pass_object_index = True
        view_layer.use_pass_diffuse_direct = True
        view_layer.use_pass_diffuse_indirect = True
        view_layer.use_pass_diffuse_color = True
        if view_layer.lightgroups.get("NIR_FLASH") is None:
            group = view_layer.lightgroups.add()
            group.name = "NIR_FLASH"
        if view_layer.lightgroups.get("DATASET_AMBIENT_FILL") is None:
            group = view_layer.lightgroups.add()
            group.name = "DATASET_AMBIENT_FILL"
        # Render Layers node sockets are cached separately from the boolean
        # pass flags. Force the engine to rebuild them before constructing the
        # per-frame compositor graph.
        view_layer.update_render_passes()


def _camera(scene, task: dict, fov_deg: float):
    camera_data = bpy.data.cameras.get("__ir_camera") or bpy.data.cameras.new("__ir_camera")
    camera_data.type = "PERSP"
    camera_data.sensor_fit = "HORIZONTAL"
    camera_data.sensor_width = 32.0
    camera_data.lens = 0.5 * camera_data.sensor_width / math.tan(math.radians(float(fov_deg)) * 0.5)
    obj = bpy.data.objects.get("__ir_camera") or bpy.data.objects.new("__ir_camera", camera_data)
    if obj.name not in scene.objects:
        scene.collection.objects.link(obj)
    obj.matrix_world = Matrix(task["camera_to_world_blender"])
    scene.camera = obj
    return obj


def _band_nodes(value: float) -> None:
    for material in bpy.data.materials:
        if not material.use_nodes or material.node_tree is None:
            continue
        node = material.node_tree.nodes.get("IR_Band")
        if node is not None:
            node.outputs[0].default_value = float(value)


def _nir_formula_nodes(formula: str) -> None:
    value = 0.0 if formula == "primary" else 1.0
    for material in bpy.data.materials:
        if not material.use_nodes or material.node_tree is None:
            continue
        node = material.node_tree.nodes.get("IR_NIR_Formula")
        if node is not None:
            node.outputs[0].default_value = value


def _luminance(color) -> float:
    return sum(float(color[i]) * _REC709[i] for i in range(3))


def _lighting_state(scene):
    lights = {}
    for obj in bpy.data.objects:
        if obj.type == "LIGHT" and obj.name != "__ir_nir_flash":
            lights[obj.name] = {
                "color": tuple(float(v) for v in obj.data.color),
                "energy": float(obj.data.energy),
                "ambient_fill": bool(obj.data.get("ir_ambient_fill", False)),
                "location": tuple(float(v) for v in obj.matrix_world.translation),
            }
    world = []
    if scene.world and scene.world.use_nodes and scene.world.node_tree:
        for node in scene.world.node_tree.nodes:
            if node.type == "BACKGROUND" and node.inputs.get("Color") is not None:
                world.append((node.name, tuple(float(v) for v in node.inputs["Color"].default_value)))
    return lights, world


def _set_lighting(scene, state, *, nir: bool, ambient_fill_energy_scale: float, recipe: dict | None = None) -> None:
    lights, world = state
    recipe = recipe or {}
    color_multiplier = tuple(float(value) for value in recipe.get("rgb_color_multiplier", (1.0, 1.0, 1.0)))
    native_scale = float(recipe.get("native_energy_scale", 1.0))
    fill_scale = float(recipe.get("ambient_fill_scale", 1.0))
    side_axis = recipe.get("side_axis_xy") or (1.0, 0.0)
    side_center = recipe.get("side_center_xy") or (0.0, 0.0)
    side_key = bool(recipe.get("side_key", False))
    for name, record in lights.items():
        obj = bpy.data.objects.get(name)
        if obj is None or obj.type != "LIGHT":
            continue
        color = tuple(record["color"][index] * color_multiplier[index] for index in range(3))
        energy = record["energy"] * native_scale
        if record["ambient_fill"]:
            energy *= float(ambient_fill_energy_scale) * fill_scale
            if side_key:
                offset_x = record["location"][0] - float(side_center[0])
                offset_y = record["location"][1] - float(side_center[1])
                dot = offset_x * float(side_axis[0]) + offset_y * float(side_axis[1])
                energy *= float(recipe.get("key_energy_scale", 1.45) if dot >= 0.0 else recipe.get("opposite_energy_scale", 0.35))
        obj.data.energy = energy
        if nir:
            y = _luminance(color)
            obj.data.color = (y, y, y)
        else:
            obj.data.color = color[:3]
    if scene.world and scene.world.use_nodes and scene.world.node_tree:
        for name, color in world:
            node = scene.world.node_tree.nodes.get(name)
            if node is None:
                continue
            recipe_color = tuple(float(color[index]) * color_multiplier[index] for index in range(3))
            if nir:
                y = _luminance(recipe_color)
                node.inputs["Color"].default_value = (y, y, y, color[3])
            else:
                node.inputs["Color"].default_value = (*recipe_color, color[3])


def _set_environment(scene, *, nir: bool, recipe: dict | None = None) -> None:
    """Switch the prepared World HDRI branch without reloading the blend."""
    external = dict((recipe or {}).get("external") or {})
    path = str(external.get("path") or "")
    if not path:
        return
    if scene.world is None:
        scene.world = bpy.data.worlds.new("IR_Environment")
    scene.world.use_nodes = True
    tree = scene.world.node_tree
    nodes, links = tree.nodes, tree.links
    output = next((node for node in nodes if node.type == "OUTPUT_WORLD"), None) or nodes.new("ShaderNodeOutputWorld")
    background = next((node for node in nodes if node.type == "BACKGROUND"), None) or nodes.new("ShaderNodeBackground")
    env = nodes.get("__ir_environment_texture") or nodes.new("ShaderNodeTexEnvironment")
    env.name = "__ir_environment_texture"
    bw = nodes.get("__ir_environment_bw") or nodes.new("ShaderNodeRGBToBW")
    bw.name = "__ir_environment_bw"
    combine = nodes.get("__ir_environment_nir_rgb") or nodes.new("ShaderNodeCombineRGB")
    combine.name = "__ir_environment_nir_rgb"
    image = bpy.data.images.get(path)
    if image is None:
        image = bpy.data.images.load(path, check_existing=True)
    env.image = image
    background.inputs["Strength"].default_value = float(external.get("world_strength", 0.0))
    links.new(env.outputs["Color"], bw.inputs["Color"])
    for channel in ("R", "G", "B"):
        links.new(bw.outputs["Val"], combine.inputs[channel])
    for link in list(background.inputs["Color"].links):
        links.remove(link)
    links.new((combine.outputs["Image"] if nir else env.outputs["Color"]), background.inputs["Color"])
    if not output.inputs["Surface"].is_linked:
        links.new(background.outputs["Background"], output.inputs["Surface"])
    for obj in bpy.data.objects:
        if obj.type == "LIGHT" and bool(obj.data.get("ir_external_portal", False)):
            obj.data.energy = float(obj.data.get("ir_base_energy_w", 0.0)) * float(external.get("portal_strength", 0.0))
            color = tuple(float(v) for v in obj.data.get("ir_external_color", (1.0, 1.0, 1.0)))
            if nir:
                y = _luminance(color); obj.data.color = (y, y, y)
            else:
                obj.data.color = color


def _place_flash(camera, *, enabled: bool, energy_scale: float = 1.0):
    flash = bpy.data.objects.get("__ir_nir_flash")
    if flash is None:
        raise RuntimeError("prepared blend lacks __ir_nir_flash")
    offset = tuple(float(v) for v in flash.get("camera_offset", (0.0, -0.10, 0.0)))
    transform = Matrix.Translation(offset)
    flash.matrix_world = camera.matrix_world @ transform
    base_energy = float(flash.data.get("ir_base_energy_w", flash.data.energy))
    flash.data["ir_base_energy_w"] = base_energy
    flash.data.energy = base_energy * float(energy_scale)
    flash.hide_render = not enabled
    return flash


def _file_node(tree, directory: Path, frame_id: str, *, mode: str, depth: str, file_format: str):
    directory.mkdir(parents=True, exist_ok=True)
    node = tree.nodes.new("CompositorNodeOutputFile")
    node.base_path = str(directory)
    node.file_slots[0].path = frame_id
    node.format.file_format = file_format
    node.format.color_mode = mode
    node.format.color_depth = depth
    node.format.color_management = "OVERRIDE"
    node.format.view_settings.view_transform = "Raw"
    node.format.view_settings.look = "None"
    if file_format == "OPEN_EXR":
        node.format.exr_codec = "ZIP"
    else:
        node.format.compression = 15
    return node


def _scale_value(tree, source, scale: float):
    node = tree.nodes.new("CompositorNodeMath")
    node.operation = "MULTIPLY"
    node.inputs[1].default_value = float(scale)
    tree.links.new(source, node.inputs[0])
    return node.outputs[0]


def _signed_normal(tree, source):
    scale = tree.nodes.new("CompositorNodeMixRGB")
    scale.blend_type = "MULTIPLY"
    scale.inputs[0].default_value = 1.0
    scale.inputs[2].default_value = (0.5, 0.5, 0.5, 1.0)
    tree.links.new(source, scale.inputs[1])
    bias = tree.nodes.new("CompositorNodeMixRGB")
    bias.blend_type = "ADD"
    bias.inputs[0].default_value = 1.0
    bias.inputs[2].default_value = (0.5, 0.5, 0.5, 1.0)
    tree.links.new(scale.outputs[0], bias.inputs[1])
    return bias.outputs[0]


def _binary_mask(tree, source):
    threshold = tree.nodes.new("CompositorNodeMath")
    threshold.operation = "GREATER_THAN"
    threshold.inputs[1].default_value = 0.5
    tree.links.new(source, threshold.inputs[0])
    return threshold.outputs[0]


def _setup_diffuse_decomposition(tree, layers, staging: Path, frame_id: str, modality: str) -> None:
    # Blender 4.2 exposes the Cycles identifiers on compositor sockets
    # (DiffDir/DiffInd/DiffCol), while the UI labels them Diffuse Direct etc.
    direct = layers.outputs.get("DiffDir") or layers.outputs.get("Diffuse Direct")
    indirect = layers.outputs.get("DiffInd") or layers.outputs.get("Diffuse Indirect")
    reflectance = layers.outputs.get("DiffCol") or layers.outputs.get("Diffuse Color")
    if direct is None or indirect is None or reflectance is None:
        available = [socket.name for socket in layers.outputs]
        raise RuntimeError(
            "render layer lacks required Cycles diffuse decomposition passes; "
            f"available={available}"
        )

    component = tree.nodes.new("CompositorNodeMixRGB")
    component.blend_type = "ADD"
    component.inputs[0].default_value = 1.0
    tree.links.new(direct, component.inputs[1])
    tree.links.new(indirect, component.inputs[2])

    component_stem, shading_stem = _DIFFUSE_EXR_STEMS[modality]
    reflectance_stem, valid_stem = _DIFFUSE_PNG_STEMS[modality]
    component_out = _file_node(
        tree, staging / component_stem, frame_id, mode="RGB", depth="32", file_format="OPEN_EXR",
    )
    tree.links.new(component.outputs[0], component_out.inputs[0])
    reflectance_out = _file_node(
        tree, staging / reflectance_stem, frame_id, mode="RGB", depth="16", file_format="PNG",
    )
    tree.links.new(reflectance, reflectance_out.inputs[0])

    separate = tree.nodes.new("CompositorNodeSepRGBA")
    tree.links.new(reflectance, separate.inputs[0])
    safe_channels = []
    for channel in range(3):
        maximum = tree.nodes.new("CompositorNodeMath")
        maximum.operation = "MAXIMUM"
        maximum.inputs[1].default_value = _DIFFUSE_EPSILON
        tree.links.new(separate.outputs[channel], maximum.inputs[0])
        safe_channels.append(maximum.outputs[0])
    safe_rgb = tree.nodes.new("CompositorNodeCombRGBA")
    for channel, source in enumerate(safe_channels):
        tree.links.new(source, safe_rgb.inputs[channel])
    safe_rgb.inputs[3].default_value = 1.0
    divide = tree.nodes.new("CompositorNodeMixRGB")
    divide.blend_type = "DIVIDE"
    divide.inputs[0].default_value = 1.0
    tree.links.new(component.outputs[0], divide.inputs[1])
    tree.links.new(safe_rgb.outputs[0], divide.inputs[2])
    shading_out = _file_node(
        tree, staging / shading_stem, frame_id, mode="RGB", depth="32", file_format="OPEN_EXR",
    )
    tree.links.new(divide.outputs[0], shading_out.inputs[0])

    max_rg = tree.nodes.new("CompositorNodeMath")
    max_rg.operation = "MAXIMUM"
    tree.links.new(separate.outputs[0], max_rg.inputs[0])
    tree.links.new(separate.outputs[1], max_rg.inputs[1])
    max_rgb = tree.nodes.new("CompositorNodeMath")
    max_rgb.operation = "MAXIMUM"
    tree.links.new(max_rg.outputs[0], max_rgb.inputs[0])
    tree.links.new(separate.outputs[2], max_rgb.inputs[1])
    valid = tree.nodes.new("CompositorNodeMath")
    valid.operation = "GREATER_THAN"
    valid.inputs[1].default_value = _DIFFUSE_EPSILON
    tree.links.new(max_rgb.outputs[0], valid.inputs[0])
    valid_out = _file_node(tree, staging / valid_stem, frame_id, mode="BW", depth="8", file_format="PNG")
    tree.links.new(valid.outputs[0], valid_out.inputs[0])


def _light_group_output(tree, layers, staging: Path, frame_id: str, *, socket_names, stem: str) -> None:
    source = None
    for socket_name in socket_names:
        source = layers.outputs.get(socket_name)
        if source is not None:
            break
    if source is None:
        raise RuntimeError(f"render layer lacks required Light Group socket: {socket_names}")
    output = _file_node(tree, staging / stem, frame_id, mode="RGB", depth="32", file_format="OPEN_EXR")
    tree.links.new(source, output.inputs[0])


def _setup_rgb_compositor(scene, staging: Path, frame_id: str, *, qc_components: bool) -> None:
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new("CompositorNodeRLayers")
    rgb = _file_node(tree, staging / "rgb", frame_id, mode="RGB", depth="32", file_format="OPEN_EXR")
    tree.links.new(layers.outputs["Image"], rgb.inputs[0])
    _setup_diffuse_decomposition(tree, layers, staging, frame_id, "rgb")
    if qc_components:
        _light_group_output(
            tree, layers, staging, frame_id,
            socket_names=("Combined_DATASET_AMBIENT_FILL", "DATASET_AMBIENT_FILL"),
            stem="qc_rgb_ambient_fill",
        )
    for stem, (source_name, mode, depth, encoding) in _GT_SPECS.items():
        source = layers.outputs.get(source_name)
        if source is None:
            raise RuntimeError(f"render layer lacks required pass socket: {source_name}")
        output = _file_node(tree, staging / stem, frame_id, mode=mode, depth=depth, file_format="PNG")
        encoded = source
        if stem == "primary_eval_valid_mask":
            valid = _binary_mask(tree, source)
            replacement_source = layers.outputs.get("GT_Replacement")
            if replacement_source is None:
                raise RuntimeError("render layer lacks required pass socket: GT_Replacement")
            replacement = _binary_mask(tree, replacement_source)
            invert_replacement = tree.nodes.new("CompositorNodeMath")
            invert_replacement.operation = "SUBTRACT"
            invert_replacement.inputs[0].default_value = 1.0
            tree.links.new(replacement, invert_replacement.inputs[1])
            primary = tree.nodes.new("CompositorNodeMath")
            primary.operation = "MULTIPLY"
            tree.links.new(valid, primary.inputs[0])
            tree.links.new(invert_replacement.outputs[0], primary.inputs[1])
            encoded = primary.outputs[0]
        elif encoding == "binary_mask_u8":
            encoded = _binary_mask(tree, source)
        elif encoding == "xyz_signed_to_unorm16":
            encoded = _signed_normal(tree, source)
        elif encoding == "millimeters_u16":
            encoded = _scale_value(tree, source, 1000.0 / _PNG16_MAX)
        elif encoding == "uint16":
            encoded = _scale_value(tree, source, 1.0 / _PNG16_MAX)
        tree.links.new(encoded, output.inputs[0])


def _setup_nir_compositor(scene, staging: Path, frame_id: str, *, qc_components: bool) -> None:
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new("CompositorNodeRLayers")
    bw = tree.nodes.new("CompositorNodeRGBToBW")
    tree.links.new(layers.outputs["Image"], bw.inputs[0])
    # Explicitly construct RGB. Connecting a VALUE socket directly to an EXR
    # file node can produce a single-channel V layer even when color_mode is
    # RGB, which several downstream EXR readers reject.
    combine = tree.nodes.new("CompositorNodeCombRGBA")
    for channel in range(3):
        tree.links.new(bw.outputs[0], combine.inputs[channel])
    combine.inputs[3].default_value = 1.0
    active = _file_node(tree, staging / "nir_active", frame_id, mode="RGB", depth="32", file_format="OPEN_EXR")
    tree.links.new(combine.outputs[0], active.inputs[0])
    _setup_diffuse_decomposition(tree, layers, staging, frame_id, "nir")
    if qc_components:
        _light_group_output(
            tree, layers, staging, frame_id,
            socket_names=("Combined_DATASET_AMBIENT_FILL", "DATASET_AMBIENT_FILL"),
            stem="qc_nir_ambient_fill",
        )
        flash_socket = layers.outputs.get("Combined_NIR_FLASH") or layers.outputs.get("NIR_FLASH")
        if flash_socket is not None:
            flash_bw = tree.nodes.new("CompositorNodeRGBToBW")
            tree.links.new(flash_socket, flash_bw.inputs[0])
            flash_rgb = tree.nodes.new("CompositorNodeCombRGBA")
            for channel in range(3):
                tree.links.new(flash_bw.outputs[0], flash_rgb.inputs[channel])
            flash_rgb.inputs[3].default_value = 1.0
            flash = _file_node(tree, staging / "qc_nir_flash", frame_id, mode="RGB", depth="32", file_format="OPEN_EXR")
            tree.links.new(flash_rgb.outputs[0], flash.inputs[0])


def _collect_one(directory: Path, frame_id: str, suffix: str) -> Path:
    matches = sorted(directory.glob(f"{frame_id}*{suffix}"))
    if not matches:
        raise RuntimeError(f"missing render artifact {directory.name}/{frame_id}{suffix}")
    target = directory / f"{frame_id}{suffix}"
    if matches[0] != target:
        if target.exists():
            target.unlink()
        matches[0].replace(target)
    for extra in matches[1:]:
        extra.unlink(missing_ok=True)
    return target


def _pass_stats(scene) -> dict:
    result = bpy.data.images.get("Render Result")
    if result is None or not result.has_data:
        return {}
    pixels = list(result.pixels[:])
    if not pixels:
        return {}
    values = []
    for i in range(0, len(pixels), 4):
        values.append(pixels[i] * _REC709[0] + pixels[i + 1] * _REC709[1] + pixels[i + 2] * _REC709[2])
    values.sort()
    count = len(values)
    return {
        "mean": float(sum(values) / count),
        "p95": float(values[min(count - 1, int(0.95 * count))]),
        "p99": float(values[min(count - 1, int(0.99 * count))]),
        "saturation_ratio_gt_1": float(sum(v > 1.0 for v in values) / count),
    }


def _publish(staging: Path, out: Path, frame_id: str, task: dict, timings: dict, qc: dict) -> dict:
    paths = {}
    exr_stems = {
        "rgb", "nir_active",
        *(stem for stems in _DIFFUSE_EXR_STEMS.values() for stem in stems),
    }
    stems = [
        "rgb", "nir_active", *_GT_SPECS.keys(),
        *(stem for stems in _DIFFUSE_EXR_STEMS.values() for stem in stems),
        *(stem for stems in _DIFFUSE_PNG_STEMS.values() for stem in stems),
    ]
    for stem in stems:
        suffix = ".exr" if stem in exr_stems else ".png"
        source = _collect_one(staging / stem, frame_id, suffix)
        target = out / stem / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        paths[stem] = str(target.relative_to(out))
    for staging_stem, output_stem in (
        ("qc_nir_flash", "nir_flash"),
        ("qc_rgb_ambient_fill", "rgb_ambient_fill"),
        ("qc_nir_ambient_fill", "nir_ambient_fill"),
    ):
        directory = staging / staging_stem
        if directory.is_dir():
            source = _collect_one(directory, frame_id, ".exr")
            target = out / "qc" / output_stem / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
            paths[staging_stem] = str(target.relative_to(out))
    row = {
        "schema": "robomituba.ir_principled_frame.v2",
        "frame_id": frame_id,
        "viewpoint_id": task["viewpoint_id"],
        "heading_deg": float(task["heading_deg"]),
        "dataset_fingerprint": task["dataset_fingerprint"],
        "pbr_gt_contract_digest": task.get("pbr_gt_contract_digest"),
        "width": int(task["width"]), "height": int(task["height"]),
        "fov_deg": float(task["fov_deg"]),
        "paths": paths, "timings_s": timings, "nir_qc": qc,
        "camera": task["camera"],
        "capture_kind": task.get("capture_kind", "single"),
        "pair_id": task.get("pair_id"),
        "pair_member_index": task.get("pair_member_index"),
        "external_lighting_available": bool(task.get("external_lighting_available", False)),
    }
    if task.get("lighting"):
        row["lighting"] = {key: value for key, value in task["lighting"].items() if key != "runtime_recipe"}
    frame_path = out / "frames" / f"{frame_id}.json"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    temp = frame_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, frame_path)
    return row


def _render_task(scene, args, lighting_state, task: dict) -> dict:
    frame_id = str(task["frame_id"])
    staging = args.out / ".staging" / args.worker_id / frame_id
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    camera = _camera(scene, task, args.fov)
    timings = {}
    try:
        _band_nodes(0.0)
        _nir_formula_nodes(args.nir_formula)
        _set_lighting(
            scene, lighting_state, nir=False,
            ambient_fill_energy_scale=args.ambient_fill_energy_scale,
            recipe=(task.get("lighting") or {}).get("runtime_recipe") or (task.get("lighting") or {}).get("recipe"),
        )
        _set_environment(scene, nir=False, recipe=(task.get("lighting") or {}).get("runtime_recipe") or (task.get("lighting") or {}).get("recipe"))
        _place_flash(camera, enabled=False, energy_scale=args.flash_energy_scale)
        _setup_rgb_compositor(scene, staging, frame_id, qc_components=args.qc_components)
        scene.cycles.samples = int(args.rgb_spp)
        scene.cycles.seed = int(args.seed)
        started = time.perf_counter()
        bpy.ops.render.render(write_still=False)
        timings["rgb"] = time.perf_counter() - started

        _band_nodes(1.0)
        _nir_formula_nodes(args.nir_formula)
        _set_lighting(
            scene, lighting_state, nir=True,
            ambient_fill_energy_scale=args.ambient_fill_energy_scale,
            recipe=(task.get("lighting") or {}).get("runtime_recipe") or (task.get("lighting") or {}).get("recipe"),
        )
        _set_environment(scene, nir=True, recipe=(task.get("lighting") or {}).get("runtime_recipe") or (task.get("lighting") or {}).get("recipe"))
        _place_flash(camera, enabled=True, energy_scale=args.flash_energy_scale)
        _setup_nir_compositor(scene, staging, frame_id, qc_components=args.qc_components)
        scene.cycles.samples = int(args.nir_spp)
        scene.cycles.seed = int(args.seed) + 1
        started = time.perf_counter()
        bpy.ops.render.render(write_still=False)
        timings["nir_active"] = time.perf_counter() - started
        qc = _pass_stats(scene)
        row = _publish(staging, args.out, frame_id, task, timings, qc)
        return row
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> int:
    args = _args()
    args.out = args.out.resolve()
    scene = bpy.context.scene
    started = time.perf_counter()
    devices = _configure_cycles(scene, args)
    _view_layer_setup(scene)
    lighting_state = _lighting_state(scene)
    _emit({
        "type": "ready", "worker_id": args.worker_id,
        "scene_load_s": time.perf_counter() - started,
        "devices": devices, "blender_version": bpy.app.version_string,
    })
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message.get("op") == "shutdown":
                _emit({"type": "stopped", "worker_id": args.worker_id})
                return 0
            if message.get("op") != "render":
                raise ValueError(f"unknown worker operation: {message.get('op')!r}")
            task = dict(message["task"])
            if task.get("dataset_fingerprint") != args.fingerprint:
                raise ValueError("task dataset fingerprint differs from worker fingerprint")
            row = _render_task(scene, args, lighting_state, task)
            _emit({
                "type": "complete", "worker_id": args.worker_id,
                "frame_id": task["frame_id"], "row": row,
            })
        except Exception as exc:
            _emit({
                "type": "failed", "worker_id": args.worker_id,
                "frame_id": (message.get("task") or {}).get("frame_id") if "message" in locals() else None,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
