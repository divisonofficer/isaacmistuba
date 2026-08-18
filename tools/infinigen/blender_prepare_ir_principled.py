"""Prepare a Stage-1 derived blend for the opaque RGB/active-NIR dataset.

Run only through ``run_bundled_blender.py``.  The script preserves geometry,
object transforms and material-slot face assignments, replacing each slot with
an explicit Blender 4.2 Principled metallic-roughness graph backed by Stage-1
PBR atlases/constants.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[2]
NAV_SRC = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(NAV_SRC) not in sys.path:
    sys.path.insert(0, str(NAV_SRC))

from navigation_dataset.ir_principled import (  # noqa: E402
    DEFAULT_BASE_COLOR,
    DEFAULT_METALLIC,
    DEFAULT_ROUGHNESS,
    MATERIAL_CONTRACT_SCHEMA,
    MATERIAL_CONTRACT_VERSION,
    STAGE2_COMPILER_VERSION,
    PSEUDO_NIR_FORMULA_ID,
    SURROGATE_MIN_ROUGHNESS,
    files_digest,
    formula_contract,
    ceiling_softbox_specs,
    material_normalization_record,
    pbr_for_slot,
)


_AOV_TYPES = {
    "GT_BaseColorRGB": "COLOR",
    "GT_BaseColorNIR": "COLOR",
    "GT_Roughness": "VALUE",
    "GT_Metallic": "VALUE",
    "GT_GeometryNormalWorld": "COLOR",
    "GT_ShadingNormalWorld": "COLOR",
    "GT_MaterialID": "VALUE",
    "GT_Defined": "VALUE",
    "GT_SourceValid": "VALUE",
    "GT_Replacement": "VALUE",
    "GT_Fallback": "VALUE",
}


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-dir", type=Path, required=True)
    parser.add_argument("--semantic-regions", type=Path)
    parser.add_argument("--room-manifest", type=Path)
    parser.add_argument("--out-blend", type=Path, required=True)
    parser.add_argument("--out-contract", type=Path, required=True)
    parser.add_argument("--flash-energy", type=float, default=40.0)
    parser.add_argument("--flash-reference-multiple", type=float, default=100.0)
    parser.add_argument("--flash-offset-y", type=float, default=-0.10)
    parser.add_argument("--flash-beam-width", type=float, default=22.0)
    parser.add_argument("--flash-cutoff-angle", type=float, default=30.0)
    parser.add_argument("--ambient-fill-energy", type=float, default=30.0)
    parser.add_argument("--ambient-fill-coverage", type=float, default=0.12)
    parser.add_argument("--ambient-fill-min-size", type=float, default=0.8)
    parser.add_argument("--ambient-fill-max-size", type=float, default=2.2)
    parser.add_argument("--ambient-fill-ceiling-gap", type=float, default=0.10)
    parser.add_argument("--luminance-scale", type=float, required=True)
    parser.add_argument("--luminance-bias", type=float, required=True)
    parser.add_argument("--luminance-corpus-digest", required=True)
    parser.add_argument("--illumination-manifest", type=Path)
    parser.add_argument("--structural-material-manifest", type=Path,
                        help="optional canonical external-PBR bindings for a rematerialized child scene")
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _semantic_index(path: Path | None) -> dict[tuple[str, str], str]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for row in payload.get("records") or []:
        object_id = str(row.get("object_id") or "")
        material_id = str(row.get("material_id") or "")
        semantic = str(row.get("semantic_class") or "none")
        if object_id and material_id and semantic != "object_glass":
            result[(object_id, material_id)] = semantic
    return result


def _unit_states(stage1_dir: Path) -> tuple[dict, list[dict], list[Path]]:
    manifest_path = stage1_dir / "scene_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state_dir = stage1_dir / ".stage1_unit_state"
    states = []
    paths = [manifest_path]
    for unit in manifest.get("units") or []:
        state_path = state_dir / f"{unit['id']}.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"missing Stage-1 unit state: {state_path}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("object_id") != unit.get("id"):
            raise ValueError(f"Stage-1 unit identity mismatch: {state_path}")
        merged = dict(unit)
        merged.update({
            "pbr": state.get("pbr") or {}, "artifacts": state.get("artifacts") or {},
            "pbr_by_slot": state.get("pbr_by_slot") or unit.get("pbr_by_slot") or {},
            "artifacts_by_slot": state.get("artifacts_by_slot") or unit.get("artifacts_by_slot") or {},
        })
        states.append(merged)
        paths.append(state_path)
    return manifest, states, paths


def _value_for_slot(channel: dict, slot: int, default):
    values = channel.get("value")
    if not isinstance(values, list) or not values:
        return default
    value = values[min(slot, len(values) - 1)]
    return value


def _image_socket(tree, path: Path, *, color: bool):
    if not path.is_file():
        return None
    image = bpy.data.images.load(str(path.resolve()), check_existing=True)
    image.colorspace_settings.name = "sRGB" if color else "Non-Color"
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.interpolation = "Linear"
    node.extension = "REPEAT"
    return node.outputs.get("Color") or node.outputs[0]


def _external_pbr_socket(tree, binding: dict, channel: str):
    key = {"base_color": "base_color", "roughness": "roughness", "metallic": None,
           "normal": "normal_gl"}[channel]
    if key is None:
        return _value_constant(tree, 0.0), "external_fixed_zero"
    path = Path(str((binding.get("resolved_maps") or {}).get(key) or ""))
    socket = _image_socket(tree, path, color=channel == "base_color")
    if socket is None:
        raise FileNotFoundError(f"external PBR map missing: {binding.get('material_id')} {channel}")
    texture = socket.node
    texcoord = tree.nodes.new("ShaderNodeTexCoord")
    mapping = tree.nodes.new("ShaderNodeMapping")
    size = binding.get("physical_size_m") or {}
    width = max(float(size.get("width") or 1.0), 1e-4)
    height = max(float(size.get("height") or width), 1e-4)
    mapping.inputs["Scale"].default_value = (1.0 / width, 1.0 / height, 1.0)
    tree.links.new(texcoord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], texture.inputs["Vector"])
    return socket, "external_pbr_texture"


def _rgb_constant(tree, value):
    values = list(value) if isinstance(value, (list, tuple)) else [float(value)] * 3
    while len(values) < 3:
        values.append(values[-1] if values else 0.5)
    node = tree.nodes.new("ShaderNodeRGB")
    node.outputs[0].default_value = tuple(float(v) for v in values[:3]) + (1.0,)
    return node.outputs[0]


def _value_constant(tree, value: float):
    node = tree.nodes.new("ShaderNodeValue")
    node.outputs[0].default_value = float(value)
    return node.outputs[0]


def _channel_socket(tree, stage1_dir: Path, unit: dict, channel_name: str, slot: int):
    pbr = pbr_for_slot(unit, slot)
    channel = (pbr.get("channels") or {}).get(channel_name) or {}
    slot_artifacts = unit.get("artifacts_by_slot") or {}
    slot_artifact = (slot_artifacts.get(str(slot), slot_artifacts.get(slot, {})) or {}).get(channel_name)
    artifact = slot_artifact or channel.get("ref") or (unit.get("artifacts") or {}).get(channel_name)
    if artifact:
        socket = _image_socket(tree, stage1_dir / str(artifact), color=channel_name == "base_color")
        if socket is not None:
            return socket, "texture"
    if channel_name == "base_color":
        value = _value_for_slot(channel, slot, DEFAULT_BASE_COLOR[:3])
        return _rgb_constant(tree, value), "constant" if channel.get("value") else "fallback"
    default = DEFAULT_ROUGHNESS if channel_name == "roughness" else DEFAULT_METALLIC
    value = _value_for_slot(channel, slot, default)
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = float(default)
    return _value_constant(tree, value), "constant" if channel.get("value") else "fallback"


def _pseudo_nir_socket(tree, rgb_socket):
    separate = tree.nodes.new("ShaderNodeSeparateColor")
    separate.mode = "RGB"
    tree.links.new(rgb_socket, separate.inputs[0])
    weighted = []
    for index, weight in enumerate((0.229, 0.587, 0.114)):
        invert = tree.nodes.new("ShaderNodeMath")
        invert.operation = "SUBTRACT"
        invert.inputs[0].default_value = 1.0
        tree.links.new(separate.outputs[index], invert.inputs[1])
        maximum = tree.nodes.new("ShaderNodeMath")
        maximum.operation = "MAXIMUM"
        tree.links.new(separate.outputs[index], maximum.inputs[0])
        tree.links.new(invert.outputs[0], maximum.inputs[1])
        multiply = tree.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.inputs[1].default_value = weight
        tree.links.new(maximum.outputs[0], multiply.inputs[0])
        weighted.append(multiply.outputs[0])
    add_rg = tree.nodes.new("ShaderNodeMath")
    add_rg.operation = "ADD"
    tree.links.new(weighted[0], add_rg.inputs[0])
    tree.links.new(weighted[1], add_rg.inputs[1])
    add_rgb = tree.nodes.new("ShaderNodeMath")
    add_rgb.operation = "ADD"
    tree.links.new(add_rg.outputs[0], add_rgb.inputs[0])
    tree.links.new(weighted[2], add_rgb.inputs[1])
    combine = tree.nodes.new("ShaderNodeCombineColor")
    combine.mode = "RGB"
    for input_socket in combine.inputs[:3]:
        tree.links.new(add_rgb.outputs[0], input_socket)
    return combine.outputs[0]


def _matched_luminance_socket(tree, rgb_socket, *, scale: float, bias: float):
    separate = tree.nodes.new("ShaderNodeSeparateColor")
    separate.mode = "RGB"
    tree.links.new(rgb_socket, separate.inputs[0])
    weighted = []
    for index, weight in enumerate((0.2126, 0.7152, 0.0722)):
        multiply = tree.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.inputs[1].default_value = weight
        tree.links.new(separate.outputs[index], multiply.inputs[0])
        weighted.append(multiply.outputs[0])
    add_rg = tree.nodes.new("ShaderNodeMath")
    add_rg.operation = "ADD"
    tree.links.new(weighted[0], add_rg.inputs[0])
    tree.links.new(weighted[1], add_rg.inputs[1])
    add_rgb = tree.nodes.new("ShaderNodeMath")
    add_rgb.operation = "ADD"
    tree.links.new(add_rg.outputs[0], add_rgb.inputs[0])
    tree.links.new(weighted[2], add_rgb.inputs[1])
    affine = tree.nodes.new("ShaderNodeMath")
    affine.operation = "MULTIPLY_ADD"
    affine.inputs[1].default_value = float(scale)
    affine.inputs[2].default_value = float(bias)
    tree.links.new(add_rgb.outputs[0], affine.inputs[0])
    clamp = tree.nodes.new("ShaderNodeClamp")
    clamp.inputs[1].default_value = 0.0
    clamp.inputs[2].default_value = 1.0
    tree.links.new(affine.outputs[0], clamp.inputs[0])
    combine = tree.nodes.new("ShaderNodeCombineColor")
    combine.mode = "RGB"
    for input_socket in combine.inputs[:3]:
        tree.links.new(clamp.outputs[0], input_socket)
    return combine.outputs[0]


def _aov(tree, name: str, source, *, kind: str):
    node = tree.nodes.new("ShaderNodeOutputAOV")
    node.aov_name = name
    target = node.inputs.get("Value") if kind == "VALUE" else node.inputs.get("Color")
    tree.links.new(source, target)


def _effective_input(*, route: str, artifact: str | None = None, color_space: str | None = None,
                     expression: str | None = None) -> dict:
    """Describe the exact evaluated material-input socket shared with a GT AOV."""
    result = {"route": route}
    if artifact:
        result["artifact"] = str(artifact)
    if color_space:
        result["color_space"] = color_space
    if expression:
        result["expression"] = expression
    return result


def _make_material(
    *, stage1_dir: Path, unit: dict, slot: int, source_material: str,
    semantic_class: str, material_id: int, luminance_scale: float, luminance_bias: float,
    structural_binding: dict | None = None, scene_id: str = "",
) -> tuple[object, dict]:
    decision = material_normalization_record(unit, source_material, semantic_class, slot=slot)
    material = bpy.data.materials.new(f"IRPBR::{unit['id']}::{slot:03d}")
    material.use_nodes = True
    material.diffuse_color = DEFAULT_BASE_COLOR
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    principled = tree.nodes.new("ShaderNodeBsdfPrincipled")
    principled.name = "IR_Principled"
    principled.inputs["IOR"].default_value = 1.5
    if principled.inputs.get("Specular IOR Level") is not None:
        principled.inputs["Specular IOR Level"].default_value = 0.5
    for input_name in ("Coat Weight", "Sheen Weight", "Transmission Weight", "Emission Strength"):
        if principled.inputs.get(input_name) is not None:
            principled.inputs[input_name].default_value = 0.0
    tree.links.new(principled.outputs[0], output.inputs["Surface"])

    if structural_binding:
        rgb, rgb_source = _external_pbr_socket(tree, structural_binding, "base_color")
        roughness, rough_source = _external_pbr_socket(tree, structural_binding, "roughness")
        metallic, metallic_source = _external_pbr_socket(tree, structural_binding, "metallic")
    else:
        rgb, rgb_source = _channel_socket(tree, stage1_dir, unit, "base_color", slot)
        roughness, rough_source = _channel_socket(tree, stage1_dir, unit, "roughness", slot)
        metallic, metallic_source = _channel_socket(tree, stage1_dir, unit, "metallic", slot)
    # These four sockets are the single authority for both rendering and GT.
    # Never create an AOV-only image sampler or fallback branch.
    effective_base_color_rgb = rgb
    effective_roughness = roughness
    effective_metallic = metallic
    nir = _pseudo_nir_socket(tree, effective_base_color_rgb)
    nir_luminance = _matched_luminance_socket(
        tree, effective_base_color_rgb, scale=luminance_scale, bias=luminance_bias,
    )

    if semantic_class in {"window_glass", "mirror"}:
        max_rough = tree.nodes.new("ShaderNodeMath")
        max_rough.operation = "MAXIMUM"
        max_rough.inputs[1].default_value = SURROGATE_MIN_ROUGHNESS
        tree.links.new(roughness, max_rough.inputs[0])
        effective_roughness = max_rough.outputs[0]
        effective_metallic = _value_constant(tree, 0.0)
        rough_source = f"surrogate_max_{SURROGATE_MIN_ROUGHNESS:g}"
        metallic_source = "surrogate_zero"

    band = tree.nodes.new("ShaderNodeValue")
    band.name = "IR_Band"
    band.label = "0=RGB, 1=NIR"
    band.outputs[0].default_value = 0.0
    nir_formula = tree.nodes.new("ShaderNodeValue")
    nir_formula.name = "IR_NIR_Formula"
    nir_formula.label = "0=primary, 1=luminance_matched_v1"
    nir_formula.outputs[0].default_value = 0.0
    nir_mix = tree.nodes.new("ShaderNodeMixRGB")
    nir_mix.blend_type = "MIX"
    tree.links.new(nir_formula.outputs[0], nir_mix.inputs[0])
    tree.links.new(nir, nir_mix.inputs[1])
    tree.links.new(nir_luminance, nir_mix.inputs[2])
    effective_base_color_nir = nir_mix.outputs[0]
    mix = tree.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MIX"
    tree.links.new(band.outputs[0], mix.inputs[0])
    tree.links.new(effective_base_color_rgb, mix.inputs[1])
    tree.links.new(effective_base_color_nir, mix.inputs[2])
    tree.links.new(mix.outputs[0], principled.inputs["Base Color"])
    tree.links.new(effective_roughness, principled.inputs["Roughness"])
    tree.links.new(effective_metallic, principled.inputs["Metallic"])

    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    slot_pbr = pbr_for_slot(unit, slot)
    normal_channel = (slot_pbr.get("channels") or {}).get("normal") or {}
    slot_artifacts = unit.get("artifacts_by_slot") or {}
    normal_artifact = ((slot_artifacts.get(str(slot), slot_artifacts.get(slot, {})) or {}).get("normal")
                       or normal_channel.get("ref") or (unit.get("artifacts") or {}).get("normal"))
    normal_source = "geometry_normal_fallback"
    raw_shading_normal = geometry.outputs["Normal"]
    if structural_binding:
        normal_rgb, _ = _external_pbr_socket(tree, structural_binding, "normal")
        normal_map = tree.nodes.new("ShaderNodeNormalMap")
        normal_map.space = "TANGENT"
        tree.links.new(normal_rgb, normal_map.inputs["Color"])
        raw_shading_normal = normal_map.outputs["Normal"]
        normal_source = "external_pbr_normal_texture"
    elif normal_artifact:
        normal_rgb = _image_socket(tree, stage1_dir / str(normal_artifact), color=False)
        if normal_rgb is not None:
            normal_map = tree.nodes.new("ShaderNodeNormalMap")
            normal_map.space = "TANGENT"
            tree.links.new(normal_rgb, normal_map.inputs["Color"])
            raw_shading_normal = normal_map.outputs["Normal"]
            normal_source = "normal_map_texture"
    normal_normalize = tree.nodes.new("ShaderNodeVectorMath")
    normal_normalize.operation = "NORMALIZE"
    normal_normalize.name = "IR_EffectiveShadingNormalWorld"
    tree.links.new(raw_shading_normal, normal_normalize.inputs[0])
    effective_shading_normal = normal_normalize.outputs[0]
    # Explicitly connect the fallback as well: the renderer and AOV must share
    # one exact normal socket, whether it comes from a normal map or geometry.
    tree.links.new(effective_shading_normal, principled.inputs["Normal"])

    _aov(tree, "GT_BaseColorRGB", effective_base_color_rgb, kind="COLOR")
    _aov(tree, "GT_BaseColorNIR", effective_base_color_nir, kind="COLOR")
    _aov(tree, "GT_Roughness", effective_roughness, kind="VALUE")
    _aov(tree, "GT_Metallic", effective_metallic, kind="VALUE")
    _aov(tree, "GT_GeometryNormalWorld", geometry.outputs["True Normal"], kind="COLOR")
    _aov(tree, "GT_ShadingNormalWorld", effective_shading_normal, kind="COLOR")
    _aov(tree, "GT_MaterialID", _value_constant(tree, material_id), kind="VALUE")
    _aov(tree, "GT_Defined", _value_constant(tree, 1.0), kind="VALUE")
    _aov(tree, "GT_SourceValid", _value_constant(tree, float(decision["source_valid"])), kind="VALUE")
    _aov(tree, "GT_Replacement", _value_constant(tree, float(decision["replacement"])), kind="VALUE")
    _aov(tree, "GT_Fallback", _value_constant(tree, float(bool(decision["fallback_channels"]))), kind="VALUE")

    material["ir_material_contract"] = MATERIAL_CONTRACT_VERSION
    material["ir_object_id"] = str(unit["id"])
    material["ir_source_material"] = source_material
    material["ir_semantic_class"] = semantic_class
    material["ir_source_valid"] = bool(decision["source_valid"])
    material["ir_replacement"] = bool(decision["replacement"])
    material["ir_fallback"] = bool(decision["fallback_channels"])
    decision["prepared_material"] = material.name
    decision["material_id"] = material_id
    decision["channel_runtime_sources"] = {
        "base_color": rgb_source, "roughness": rough_source,
        "metallic": metallic_source, "normal": normal_source,
    }
    channel_artifacts = (slot_artifacts.get(str(slot), slot_artifacts.get(slot, {})) or unit.get("artifacts") or {})
    source_channels = (slot_pbr.get("channels") or {})
    def artifact_for(name: str):
        return channel_artifacts.get(name) or (source_channels.get(name) or {}).get("ref")
    decision["effective_inputs"] = {
        "base_color_rgb": _effective_input(
            route=rgb_source,
            artifact=artifact_for("base_color") if rgb_source == "texture" else None,
            color_space="sRGB" if rgb_source == "texture" else None,
        ),
        "base_color_nir": _effective_input(
            route="derived_from_effective_base_color_rgb",
            expression="selected pseudo-NIR branch from effective_base_color_rgb",
        ),
        "roughness": _effective_input(
            route=rough_source,
            artifact=artifact_for("roughness") if rough_source == "texture" else None,
            color_space="Non-Color" if rough_source == "texture" else None,
        ),
        "metallic": _effective_input(
            route=metallic_source,
            artifact=artifact_for("metallic") if metallic_source == "texture" else None,
            color_space="Non-Color" if metallic_source == "texture" else None,
        ),
        "normal_shading_world": _effective_input(
            route=normal_source,
            artifact=str(normal_artifact) if normal_source == "normal_map_texture" else None,
            color_space="Non-Color" if normal_source == "normal_map_texture" else None,
            expression=("normalize(tangent_space_normal_map_to_world)" if normal_source == "normal_map_texture"
                        else "Geometry.Normal world-space fallback"),
        ),
        "normal_geometry_world": _effective_input(
            route="geometry_true_normal", expression="Geometry.True Normal world-space",
        ),
    }
    decision["material_instance_id"] = f"{scene_id}:{unit['id']}:{slot}"
    if structural_binding:
        decision["structural_rematerialization"] = {
            "material_id": structural_binding.get("material_id"),
            "projection": structural_binding.get("projection"),
            "maps": structural_binding.get("maps"),
            "map_sha256": structural_binding.get("map_sha256"),
        }
    return material, decision


def _prepare_view_layer() -> None:
    for view_layer in bpy.context.scene.view_layers:
        for name, kind in _AOV_TYPES.items():
            existing = view_layer.aovs.get(name)
            if existing is None:
                existing = view_layer.aovs.add()
                existing.name = name
            existing.type = kind
        view_layer.use_pass_z = True
        view_layer.use_pass_normal = True
        view_layer.use_pass_object_index = True


def _world_bounds(obj) -> tuple[float, float, float, float, float, float]:
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return (
        min(point.x for point in points), min(point.y for point in points), min(point.z for point in points),
        max(point.x for point in points), max(point.y for point in points), max(point.z for point in points),
    )


def _room_bounds(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        raise RuntimeError("room manifest is required for realistic indoor ambient fill")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rooms = []
    for region in payload.get("regions") or []:
        if str(region.get("type") or "") != "traversable":
            continue
        bounds = ((region.get("geometry") or {}).get("bounds") or [])
        if len(bounds) != 4:
            continue
        min_x, min_y, max_x, max_y = [float(value) for value in bounds]
        if max_x > min_x and max_y > min_y:
            rooms.append({
                "room_id": str(region.get("id") or f"room_{len(rooms):02d}"),
                "bounds_xy": [min_x, min_y, max_x, max_y],
            })
    if not rooms:
        raise RuntimeError(f"room manifest has no traversable rectangle regions: {path}")
    return rooms


def _overlaps_xy(bounds, room) -> bool:
    min_x, min_y, _, max_x, max_y, _ = bounds
    rx0, ry0, rx1, ry1 = room["bounds_xy"]
    return min(max_x, rx1) > max(min_x, rx0) and min(max_y, ry1) > max(min_y, ry0)


def _ceiling_height(room: dict) -> tuple[float, str]:
    candidates = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or "ceiling" not in obj.name.lower():
            continue
        bounds = _world_bounds(obj)
        if bounds[5] > 2.0 and _overlaps_xy(bounds, room):
            candidates.append((bounds[2], obj.name))
    if candidates:
        height, source = max(candidates, key=lambda item: item[0])
        return float(height), source
    ceiling_lights = []
    rx0, ry0, rx1, ry1 = room["bounds_xy"]
    for obj in bpy.data.objects:
        if obj.type != "LIGHT":
            continue
        point = obj.matrix_world.translation
        if rx0 <= point.x <= rx1 and ry0 <= point.y <= ry1 and point.z > 2.0:
            ceiling_lights.append(float(point.z) + 0.03)
    if ceiling_lights:
        return float(statistics.median(ceiling_lights)), "median_source_ceiling_light"
    return 2.6, "fallback_2.6m"


def _install_ambient_fill(args: argparse.Namespace) -> dict:
    rooms = _room_bounds(args.room_manifest.resolve() if args.room_manifest else None)
    source_audit = []
    for obj in list(bpy.data.objects):
        if obj.type != "LIGHT" or obj.name == "__ir_nir_flash" or obj.name.startswith("__ir_ambient_fill_"):
            continue
        point = obj.matrix_world.translation
        in_room = any(
            room["bounds_xy"][0] <= point.x <= room["bounds_xy"][2]
            and room["bounds_xy"][1] <= point.y <= room["bounds_xy"][3]
            and point.z > 1.5
            for room in rooms
        )
        preserve = obj.data.type == "AREA" and in_room
        source_audit.append({
            "object": obj.name, "type": obj.data.type, "energy_before": float(obj.data.energy),
            "world_position": [float(value) for value in point],
            "valid_room_ceiling_area": bool(preserve),
            "policy": "preserved" if preserve else "disabled_variance_source",
        })
        if not preserve:
            obj.hide_render = True
            obj.data.energy = 0.0

    panels = []
    for room in rooms:
        min_x, min_y, max_x, max_y = room["bounds_xy"]
        width, depth = max_x - min_x, max_y - min_y
        specs = ceiling_softbox_specs(
            room["bounds_xy"], coverage_fraction=float(args.ambient_fill_coverage),
            min_size_m=float(args.ambient_fill_min_size), max_size_m=float(args.ambient_fill_max_size),
        )
        ceiling_z, ceiling_source = _ceiling_height(room)
        panel_z = ceiling_z - float(args.ambient_fill_ceiling_gap)
        for index, spec in enumerate(specs):
            x, y = spec["center_xy"]
            side_x, side_y = spec["size_m"]
            name = f"__ir_ambient_fill_{room['room_id']}_{index:02d}"
            old = bpy.data.objects.get(name)
            if old is not None:
                bpy.data.objects.remove(old, do_unlink=True)
            data = bpy.data.lights.new(name, type="AREA")
            data.shape = "RECTANGLE"
            data.size = float(side_x)
            data.size_y = float(side_y)
            data.energy = float(args.ambient_fill_energy)
            data.color = (1.0, 0.93, 0.82)
            data["ir_ambient_fill"] = True
            data["ir_base_energy_w"] = float(args.ambient_fill_energy)
            obj = bpy.data.objects.new(name, data)
            bpy.context.scene.collection.objects.link(obj)
            obj.location = (x, y, panel_z)
            obj.rotation_euler = (0.0, 0.0, 0.0)  # Blender AREA emits along local -Z.
            obj.lightgroup = "DATASET_AMBIENT_FILL"
            panels.append({
                "object": name, "room_id": room["room_id"], "position": [x, y, panel_z],
                "size_m": [side_x, side_y], "energy_w": float(args.ambient_fill_energy),
                "color_linear_rgb": [1.0, 0.93, 0.82],
                "ceiling_height_m": ceiling_z, "ceiling_source": ceiling_source,
            })
    return {
        "policy": "room_fixed_broad_ceiling_area_v1",
        "source_light_policy": "preserve_valid_room_ceiling_area_disable_other_light_objects",
        "coverage_fraction": float(args.ambient_fill_coverage),
        "panel_size_range_m": [float(args.ambient_fill_min_size), float(args.ambient_fill_max_size)],
        "ceiling_gap_m": float(args.ambient_fill_ceiling_gap),
        "light_group": "DATASET_AMBIENT_FILL",
        "rooms": rooms, "panels": panels, "source_lights": source_audit,
    }


def _install_flash(args: argparse.Namespace) -> object:
    old = bpy.data.objects.get("__ir_nir_flash")
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    data = bpy.data.lights.new("__ir_nir_flash", type="SPOT")
    data.energy = float(args.flash_energy)
    data.color = (1.0, 1.0, 1.0)
    data.spot_size = math.radians(float(args.flash_cutoff_angle) * 2.0)
    data.spot_blend = max(0.0, min(1.0, 1.0 - float(args.flash_beam_width) / float(args.flash_cutoff_angle)))
    obj = bpy.data.objects.new("__ir_nir_flash", data)
    bpy.context.scene.collection.objects.link(obj)
    obj.hide_render = True
    obj.lightgroup = "NIR_FLASH"
    obj["camera_offset"] = (0.0, float(args.flash_offset_y), 0.0)
    obj["beam_width_deg"] = float(args.flash_beam_width)
    obj["cutoff_angle_deg"] = float(args.flash_cutoff_angle)
    return obj


def _install_external_portals() -> dict:
    """Install lightweight window-facing area emitters for opaque window surrogates."""
    panels = []
    for index, obj in enumerate(item for item in bpy.data.objects if item.type == "MESH" and "window" in item.name.lower()):
        bounds = _world_bounds(obj)
        sx, sy, sz = bounds[3] - bounds[0], bounds[4] - bounds[1], bounds[5] - bounds[2]
        # The smallest dimension is the window thickness. Use the remaining two
        # dimensions for the portal and orient its local -Z toward the room.
        dims = [sx, sy, sz]; thin = dims.index(min(dims)); center = obj.matrix_world.translation
        data = bpy.data.lights.new(f"__ir_external_portal_{index:02d}", type="AREA")
        data.shape = "RECTANGLE"; data.energy = 0.0
        data["ir_external_portal"] = True; data["ir_base_energy_w"] = 55.0
        data["ir_external_color"] = (1.0, 1.0, 1.0)
        panel = bpy.data.objects.new(data.name, data); bpy.context.scene.collection.objects.link(panel)
        panel.location = center
        if thin == 0:
            data.size, data.size_y = max(sy, 0.2), max(sz, 0.2); panel.rotation_euler = (0.0, math.pi / 2.0, 0.0)
        elif thin == 1:
            data.size, data.size_y = max(sx, 0.2), max(sz, 0.2); panel.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
        else:
            data.size, data.size_y = max(sx, 0.2), max(sy, 0.2)
        panels.append({"object": panel.name, "source_window": obj.name, "size_m": [data.size, data.size_y], "energy_w": 55.0})
    return {"policy": "window_surrogate_area_portal_v1", "available": bool(panels), "panels": panels}


def main() -> int:
    args = _args()
    stage1_dir = args.stage1_dir.resolve()
    manifest, units, digest_paths = _unit_states(stage1_dir)
    semantic = _semantic_index(args.semantic_regions.resolve() if args.semantic_regions else None)
    structural_manifest = None
    structural_bindings = {}
    if args.structural_material_manifest:
        structural_manifest = json.loads(args.structural_material_manifest.read_text(encoding="utf-8"))
        if structural_manifest.get("schema") != "robomituba.ir_structural_rematerialization.v1":
            raise RuntimeError("unsupported structural rematerialization manifest")
        for binding in structural_manifest.get("bindings") or []:
            structural_bindings[(str(binding.get("unit_id")), int(binding.get("slot_index") or 0))] = binding
        digest_paths.append(args.structural_material_manifest.resolve())
    if args.semantic_regions and args.semantic_regions.is_file():
        digest_paths.append(args.semantic_regions.resolve())
    if args.room_manifest and args.room_manifest.is_file():
        digest_paths.append(args.room_manifest.resolve())

    records = []
    missing_objects = []
    material_id = 1
    object_id = 1
    for unit in units:
        obj = bpy.data.objects.get(str(unit.get("blender_name") or ""))
        if obj is None or obj.type != "MESH":
            missing_objects.append(str(unit.get("blender_name") or unit.get("id")))
            continue
        source_names = list(unit.get("materials") or [])
        slot_count = max(len(obj.data.materials), len(source_names), 1)
        while len(obj.data.materials) < slot_count:
            obj.data.materials.append(None)
        for slot in range(slot_count):
            source_name = source_names[slot] if slot < len(source_names) else (
                obj.data.materials[slot].name if obj.data.materials[slot] else f"missing_slot_{slot}"
            )
            semantic_class = semantic.get((str(unit["id"]), str(source_name)), "none")
            material, record = _make_material(
                stage1_dir=stage1_dir, unit=unit, slot=slot,
                source_material=str(source_name), semantic_class=semantic_class,
                material_id=material_id,
                luminance_scale=args.luminance_scale, luminance_bias=args.luminance_bias,
                structural_binding=structural_bindings.get((str(unit["id"]), slot)),
                scene_id=str((structural_manifest or {}).get("child_scene_id") or manifest.get("scene_id") or ""),
            )
            obj.data.materials[slot] = material
            records.append(record)
            material_id += 1
        obj.pass_index = object_id
        obj["ir_object_id"] = str(unit["id"])
        obj["ir_object_index"] = object_id
        object_id += 1

    if missing_objects:
        raise RuntimeError(f"Stage-1 derived blend lacks {len(missing_objects)} unit object(s): {missing_objects[:8]}")

    _prepare_view_layer()
    ambient_fill = _install_ambient_fill(args)
    external_portals = _install_external_portals()
    flash = _install_flash(args)
    scene = bpy.context.scene
    scene["ir_material_contract"] = MATERIAL_CONTRACT_VERSION
    scene["ir_pseudo_nir_formula"] = PSEUDO_NIR_FORMULA_ID
    scene["ir_prepared_at"] = _utc_now()
    scene["ir_stage1_scene_id"] = str(manifest.get("scene_id") or "")

    counts = Counter()
    for record in records:
        counts["material_slots"] += 1
        counts["source_valid"] += int(record["source_valid"])
        counts["replacement"] += int(record["replacement"])
        counts[f"semantic_{record['semantic_class']}"] += 1
        counts["fallback"] += int(bool(record["fallback_channels"]))
    contract = {
        "schema": MATERIAL_CONTRACT_SCHEMA,
        "contract_version": MATERIAL_CONTRACT_VERSION,
        "compiler_version": STAGE2_COMPILER_VERSION,
        "created_at": _utc_now(),
        "blender_version": bpy.app.version_string,
        "source_blend": str(Path(bpy.data.filepath).resolve()),
        "source_blend_sha256": _sha256(Path(bpy.data.filepath).resolve()),
        "stage1_dir": str(stage1_dir),
        "stage1_scene_id": manifest.get("scene_id"),
        "stage1_contract_digest": files_digest(digest_paths),
        "structural_rematerialization": structural_manifest,
        "structural_rematerialization_sha256": (_sha256(args.structural_material_manifest) if args.structural_material_manifest else None),
        "material_model": {
            "name": "Blender 4.2 Principled Metallic-Roughness Subset",
            "variable_parameters": ["base_color", "roughness", "metallic", "normal"],
            "fixed": {"ior": 1.5, "specular_ior_level": 0.5},
            "forbidden_lobes": [
                "transmission", "refraction", "clearcoat", "sheen", "anisotropy",
                "subsurface", "emission", "measured_brdf", "polarization",
            ],
        },
        "aov_semantics": {
            "base_color_rgb": "effective Principled Base Color RGB branch",
            "base_color_nir": "effective Principled Base Color selected NIR branch",
            "roughness": "effective Principled Roughness input",
            "metallic": "effective Principled Metallic input",
            "normal_geometry_world": "Geometry.True Normal in world space",
            "normal_shading_world": "effective Principled Normal input in world space, after tangent normal-map evaluation",
        },
        "pseudo_nir": formula_contract(),
        "pseudo_nir_ablation": {
            "id": "luminance_matched_v1",
            "input": "linear_rgb",
            "expression": "clip(linear_rec709_luminance * scale + bias, 0, 1)",
            "scale": float(args.luminance_scale),
            "bias": float(args.luminance_bias),
            "corpus_digest": str(args.luminance_corpus_digest),
        },
        "surrogate": {
            "semantic_classes": ["window_glass", "mirror"],
            "metallic": 0.0, "roughness_min": SURROGATE_MIN_ROUGHNESS,
        },
        "fallback_defaults": {
            "base_color": list(DEFAULT_BASE_COLOR[:3]),
            "roughness": DEFAULT_ROUGHNESS, "metallic": DEFAULT_METALLIC,
            "normal": "flat",
        },
        "aovs": dict(_AOV_TYPES),
        "flash_rig": {
            "object": flash.name,
            "camera_relative_offset_blender": list(flash["camera_offset"]),
            "energy_w": float(args.flash_energy),
            "reference_rgb_phone_flash_luminance_multiple": float(args.flash_reference_multiple),
            "beam_width_deg": float(args.flash_beam_width),
            "cutoff_angle_deg": float(args.flash_cutoff_angle),
            "light_group": "NIR_FLASH",
        },
        "ambient_fill_rig": ambient_fill,
        "external_portal_rig": external_portals,
        "illumination_manifest": (json.loads(args.illumination_manifest.read_text(encoding="utf-8")) if args.illumination_manifest and args.illumination_manifest.is_file() else None),
        "illumination_manifest_sha256": (_sha256(args.illumination_manifest) if args.illumination_manifest and args.illumination_manifest.is_file() else None),
        "counts": dict(counts),
        "materials": records,
    }
    args.out_contract.parent.mkdir(parents=True, exist_ok=True)
    args.out_contract.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    scene["ir_material_contract_ref"] = str(args.out_contract.resolve())
    args.out_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.out_blend.resolve()), check_existing=False)
    print(
        f"[ir-principled] prepared objects={len(units)} slots={counts['material_slots']} "
        f"source_valid={counts['source_valid']} replacement={counts['replacement']} "
        f"-> {args.out_blend}", flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
