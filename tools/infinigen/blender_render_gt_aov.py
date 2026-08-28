"""Render camera-space PBR ground truth directly from an Infinigen ``.blend``.

This is intentionally a Blender-side exporter.  It does not unwrap, bake, or
re-import an OBJ/GLB.  Principled inputs are routed to temporary AOV outputs so
procedural shader graphs are evaluated at the visible camera sample.  The
resulting artifacts use a modality-first PNG layout.  PBR values are stored as
raw scene-linear 16-bit UNORM PNGs; NIR synthesis remains the responsibility
of the camera-space postprocessor using the existing material-class prior.

Run through the bundled Blender launcher, for example::

  python tools/infinigen/run_bundled_blender.py --background scene.blend \
    --python tools/infinigen/blender_render_gt_aov.py -- \
    --scene-graph out/.../viewpoint_graph.json --viewpoints vp_000055@255 \
    --out /tmp/kitchen_gt_probe --width 684 --height 512
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

import bpy  # type: ignore
from mathutils import Matrix, Vector  # type: ignore

# The bundled Blender process does not install the repository packages globally.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BRIDGE_SRC = _REPO_ROOT / "modules" / "robomituba_bridge" / "src"
if str(_BRIDGE_SRC) not in sys.path:
    sys.path.insert(0, str(_BRIDGE_SRC))
from robomituba_bridge.camera_pose import (  # noqa: E402
    pose_from_mitsuba_camera_to_world,
    resolve_viewpoint_pose,
)
from blender_ir_scene_domain import (  # noqa: E402
    apply_face_exclusion,
    fingerprint as _gt_fingerprint,
    load_domain,
    prepare_resume,
    record_progress,
    restore_face_exclusion,
)


_OUTPUT_STEMS = [
    "base_color_rgb", "roughness", "metallic", "normal_geometry_world",
    "normal_shading_camera", "depth", "object_id", "material_id",
]

_AOVS = {
    "GT_BaseColor": "color",
    "GT_Roughness": "value",
    "GT_Metallic": "value",
    "GT_GeometryNormal": "color",
    "GT_MaterialID": "value",
}


# Do not infer an image's numeric interpretation from its filename.  The
# contract is written alongside every export in gt_artifact_contract.json
# and the compositor configuration below is deliberately a one-to-one
# implementation of it.
_ARTIFACT_LAYOUT = "modality_first_v1"
_PNG16_MAX = 65535.0
_ARTIFACT_SPECS = {
    "base_color_rgb": {
        "color_mode": "RGB", "color_depth": "16",
        "encoding": "linear_unorm16", "source": "GT_BaseColor",
    },
    "roughness": {
        "color_mode": "BW", "color_depth": "16",
        "encoding": "perceptual_roughness_unorm16", "source": "GT_Roughness",
    },
    "metallic": {
        "color_mode": "BW", "color_depth": "16",
        "encoding": "unorm16", "source": "GT_Metallic",
    },
    "pbr_validity": {
        "color_mode": "BW", "color_depth": "8",
        "encoding": "binary_mask_u8", "source": "GT_PBR_PARAMS.B",
    },
    "pbr_params": {
        "color_mode": "RGB", "color_depth": "16",
        "encoding": "roughness_metallic_validity_unorm16", "source": "GT_PBR_PARAMS",
    },
    "normal_geometry_world": {
        "color_mode": "RGB", "color_depth": "16",
        "encoding": "xyz_signed_to_unorm16", "source": "GT_GeometryNormal",
    },
    "normal_shading_camera": {
        "color_mode": "RGB", "color_depth": "16",
        "encoding": "xyz_signed_to_unorm16", "source": "Normal",
    },
    "depth": {
        "color_mode": "BW", "color_depth": "16",
        "encoding": "millimeters_u16", "invalid": 0, "source": "Depth",
    },
    "object_id": {
        "color_mode": "BW", "color_depth": "16",
        "encoding": "uint16", "invalid": 0, "source": "IndexOB",
    },
    "material_id": {
        "color_mode": "BW", "color_depth": "16",
        "encoding": "uint16", "invalid": 0, "source": "GT_MaterialID",
    },
}


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-graph", type=Path, required=True)
    parser.add_argument(
        "--origin-offset", type=float, nargs="+", default=None, metavar="M",
        help="optional Infinigen authoring normalization offset [dx dy dz]; defaults to scene sibling authoring_map.json",
    )
    parser.add_argument(
        "--pose-manifest", type=Path, default=None,
        help="optional JSON/JSONL observation manifest; resolved Mitsuba poses take precedence over graph fallback",
    )
    parser.add_argument(
        "--require-pose-manifest", action="store_true",
        help="require one valid manifest pose for every requested frame; disables graph fallback",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--viewpoints", required=True)
    parser.add_argument("--width", type=int, default=684)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--fov", type=float, default=60.0, help="horizontal Mitsuba/Blender field of view")
    parser.add_argument("--eye-height", type=float, default=1.2, help="camera eye height in Mitsuba Y-up metres")
    parser.add_argument(
        "--target-height", type=float, default=None,
        help="Mitsuba target height; default is 0.9 * eye height (the existing kitchen contract)",
    )
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument(
        "--engine", choices=("CYCLES", "BLENDER_EEVEE_NEXT"), default="CYCLES",
        help="Blender render engine. Cycles CPU is the headless-safe default; "
             "EEVEE requires a working EGL context.",
    )
    parser.add_argument(
        "--ir-scene-domain", type=Path,
        help="opaque-PBR effective-scene contract; temporarily removes selected dielectric faces",
    )
    parser.add_argument("--resume", action="store_true", help="skip fully written frames matching this GT run fingerprint")
    parser.add_argument("--adopt-existing", action="store_true",
                        help="with --resume, index an older complete PNG prefix that lacks gt_progress.json")
    return parser.parse_args(argv)


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("_") or "unnamed"


def _authoring_origin_offset(scene_graph: Path, override) -> tuple[float, float, float]:
    """Load graph-world normalization applied by the Infinigen importer.

    Stage 2 renders the normalized authoring world, but the Blender source scene
    remains in native coordinates.  GT therefore needs the inverse offset after
    the fixed Mitsuba-to-Blender axis rotation.
    """
    values = override
    source = "cli"
    if values is None:
        map_path = scene_graph.parent / "authoring_map.json"
        if map_path.is_file():
            payload = json.loads(map_path.read_text(encoding="utf-8"))
            values = (payload.get("metadata") or {}).get("origin_offset")
            source = str(map_path)
    if values is None:
        return (0.0, 0.0, 0.0)
    if not isinstance(values, (list, tuple)) or len(values) not in (2, 3):
        raise ValueError("origin_offset must be [dx, dy] or [dx, dy, dz]")
    offset = tuple(float(v) for v in values)
    if len(offset) == 2:
        offset = (*offset, 0.0)
    print(f"[gt-aov] authoring origin_offset={list(offset)} source={source}", flush=True)
    return offset


def _pose_manifest_rows(path: Path | None) -> dict[str, dict]:
    """Index resolved camera poses from JSON/JSONL observation manifests.

    The exporter normally resolves graph poses itself.  When an observation
    manifest already contains a resolved Mitsuba matrix, this optional index
    lets GT reuse that exact pose instead of silently recomputing it from a
    graph revision.  Several historical manifest containers are accepted
    (top-level list, ``records``, ``observations`` or ``frames``).
    """
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        found_container = False
        for key in ("records", "observations", "frames", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                found_container = True
                break
            if isinstance(value, dict):
                rows = [dict(v, _container_key=k) if isinstance(v, dict) else {} for k, v in value.items()]
                found_container = True
                break
        # A single observation manifest record is also a valid input.
        if not found_container and (payload.get("frame_id") or payload.get("camera_to_world") or payload.get("camera_to_world_mitsuba")):
            rows = [payload]
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested = [row]
        for key in ("camera", "pose", "resolved_pose"):
            value = row.get(key)
            if isinstance(value, dict):
                nested.append({**row, **value})
        node = row.get("viewpoint_id", row.get("node_id"))
        heading = row.get("heading_deg", row.get("yaw_deg", row.get("heading")))
        keys = []
        for candidate in nested:
            for key in ("frame_id", "observation_id", "id"):
                if candidate.get(key):
                    keys.append(str(candidate[key]))
        if node is not None and heading is not None:
            try:
                yaw = float(heading)
                keys.extend((
                    f"{node}__h_{int(round(yaw)) % 360:03d}",
                    f"{node}@{yaw:g}",
                    f"{node}@{int(round(yaw)) % 360}",
                ))
            except (TypeError, ValueError):
                pass
        if not keys:
            continue
        for key in keys:
            previous = result.get(key)
            if previous is not None and previous is not row:
                raise ValueError(f"duplicate pose-manifest key: {key}")
            result[key] = row
    return result


def _pose_from_manifest_record(
    row: dict | None, *, yaw_deg: float, origin_offset: tuple[float, float, float]
):
    if not row:
        return None
    candidates = [row]
    for key in ("camera", "pose", "resolved_pose"):
        value = row.get(key)
        if isinstance(value, dict):
            candidates.insert(0, value)
    matrix = None
    for candidate in candidates:
        matrix = candidate.get("camera_to_world_mitsuba")
        if matrix is None:
            matrix = candidate.get("camera_to_world")
        if matrix is not None:
            break
    if matrix is None:
        return None
    target = None
    for candidate in candidates:
        target = candidate.get("target_mitsuba")
        if target is not None:
            break
    return pose_from_mitsuba_camera_to_world(
        matrix, pose_source="observation_manifest", target_mitsuba=target,
        origin_offset=origin_offset,
    )


def _lookup_pose_manifest(
    index: dict[str, dict], node_id: str, yaw_deg: float, *, origin_offset: tuple[float, float, float]
):
    key = f"{node_id}__h_{int(round(float(yaw_deg))) % 360:03d}"
    row = index.get(key) or index.get(f"{node_id}@{float(yaw_deg):g}")
    return _pose_from_manifest_record(row, yaw_deg=yaw_deg, origin_offset=origin_offset)


def _socket_source(socket):
    """Return the upstream output socket, or None for an unlinked input."""
    if socket is None or not socket.links:
        return None
    return socket.links[0].from_socket


def _principled_nodes(material):
    """Return Principled nodes in the material and nested shader groups.

    Infinigen materials normally expose a Group node at the material level;
    looking only at ``material.node_tree.nodes`` silently produces zero-valued
    roughness/metallic AOVs for those assets.
    """
    if not material or not material.use_nodes or not material.node_tree:
        return []
    found = []
    seen = set()

    def walk(tree):
        if tree is None or tree.as_pointer() in seen:
            return
        seen.add(tree.as_pointer())
        for node in tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                found.append((tree, node))
            elif node.type == "GROUP" and getattr(node, "node_tree", None):
                walk(node.node_tree)

    walk(material.node_tree)
    return found


def _new_aov_output(tree, name: str, kind: str):
    node = tree.nodes.new("ShaderNodeOutputAOV")
    node.name = f"__gt_aov__{name}"
    node.label = node.name
    node.aov_name = name
    if kind == "value" and node.inputs.get("Value") is not None:
        return node, node.inputs["Value"]
    return node, node.inputs.get("Color") or node.inputs[0]


def _constant_source(tree, socket, kind: str):
    if kind == "color":
        node = tree.nodes.new("ShaderNodeRGB")
        value = getattr(socket, "default_value", (0.0, 0.0, 0.0, 1.0))
        if isinstance(value, (float, int)):
            value = (float(value),) * 3 + (1.0,)
        node.outputs[0].default_value = tuple(value[:4])
    else:
        node = tree.nodes.new("ShaderNodeValue")
        value = getattr(socket, "default_value", 0.0)
        node.outputs[0].default_value = float(value[0] if isinstance(value, (tuple, list)) else value)
    return node.outputs[0]


def _install_material_aovs(materials: list, material_ids: dict[str, int]):
    """Install temporary AOV nodes and return enough state to remove them."""
    created = []
    for material in materials:
        tree = material.node_tree if material and material.use_nodes else None
        if tree is None:
            continue
        principled = _principled_nodes(material)
        if not principled:
            continue
        shader_tree, shader = principled[0]
        for name, kind, input_name in (
            ("GT_BaseColor", "color", "Base Color"),
            ("GT_Roughness", "value", "Roughness"),
            ("GT_Metallic", "value", "Metallic"),
        ):
            src = _socket_source(shader.inputs.get(input_name))
            if src is None:
                src = _constant_source(shader_tree, shader.inputs.get(input_name), kind)
                created.append((shader_tree, src.node))
            out, dst = _new_aov_output(shader_tree, name, kind)
            shader_tree.links.new(src, dst)
            created.append((shader_tree, out))

        # New Geometry.Normal is the authored geometric surface normal. Blender's
        # built-in Normal pass is retained separately as the shading-normal pass.
        geom = shader_tree.nodes.new("ShaderNodeNewGeometry")
        out, dst = _new_aov_output(shader_tree, "GT_GeometryNormal", "color")
        shader_tree.links.new(geom.outputs.get("Normal") or geom.outputs[0], dst)
        created.extend(((shader_tree, geom), (shader_tree, out)))

        # Material ID is emitted in the outer material tree, so it remains a
        # per-material constant even when the Principled closure is nested in
        # a shared shader group.
        value = tree.nodes.new("ShaderNodeValue")
        value.outputs[0].default_value = float(material_ids[material.name])
        out, dst = _new_aov_output(tree, "GT_MaterialID", "value")
        tree.links.new(value.outputs[0], dst)
        created.extend(((tree, value), (tree, out)))
    return created


def _remove_nodes(created) -> None:
    for tree, node in reversed(created):
        try:
            tree.nodes.remove(node)
        except Exception:
            pass


def _prepare_view_layer(view_layer):
    for name in _AOVS:
        if view_layer.aovs.get(name) is None:
            aov = view_layer.aovs.add()
            aov.name = name
            aov.type = "COLOR" if _AOVS[name] == "color" else "VALUE"
    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True
    view_layer.use_pass_object_index = True


def _camera_from_spec(
    node: dict,
    yaw_deg: float,
    fov_deg: float,
    *,
    eye_height_m: float = 1.2,
    target_height_m: float | None = None,
    origin_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    resolved_pose=None,
):
    """Create the Blender camera from the canonical Mitsuba graph pose.

    Graph positions are authoring XZ coordinates, not Blender XYZ.  The
    resolver applies Mitsuba Y-up -> Blender Z-up to the complete camera
    basis, so no implicit ``to_track_quat`` global-up assumption can reintroduce
    the old vertical-axis bug.
    """
    pose = resolved_pose or resolve_viewpoint_pose(
        node["position"],
        float(yaw_deg),
        eye_height_m=float(eye_height_m),
        target_height_m=target_height_m,
        origin_offset=origin_offset,
    )
    camera = bpy.data.cameras.get("__gt_camera") or bpy.data.cameras.new("__gt_camera")
    camera.type = "PERSP"
    camera.sensor_fit = "HORIZONTAL"
    camera.sensor_width = 32.0
    camera.lens = 0.5 * camera.sensor_width / math.tan(math.radians(float(fov_deg)) * 0.5)
    obj = bpy.data.objects.get("__gt_camera") or bpy.data.objects.new("__gt_camera", camera)
    if obj.name not in bpy.context.scene.objects:
        bpy.context.collection.objects.link(obj)
    obj.matrix_world = Matrix(pose.camera_to_world_blender)
    obj["coordinate_system"] = "blender_z_up"
    obj["camera_coordinate_system"] = "mitsuba_y_up"
    obj["axis_transform"] = pose.axis_transform
    obj["fov_axis"] = "x"
    return obj, pose


def _artifact_directory(out_dir: Path, stem: str) -> Path:
    if stem not in _ARTIFACT_SPECS:
        raise KeyError(f"no PNG artifact contract for {stem!r}")
    directory = out_dir / stem
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _configure_png_output(node, out_dir: Path, frame_id: str, stem: str):
    """Configure one raw, modality-first PNG output slot."""
    spec = _ARTIFACT_SPECS[stem]
    node.name = f"GT_File_{stem}"
    node.base_path = str(_artifact_directory(out_dir, stem))
    node.format.file_format = "PNG"
    node.format.color_depth = spec["color_depth"]
    node.format.color_mode = spec["color_mode"]
    # AOVs are numeric GT, not display-referred images.  In particular do not
    # apply Standard/Filmic's linear-to-display transform before quantization.
    node.format.color_management = "OVERRIDE"
    node.format.view_settings.view_transform = "Raw"
    node.format.view_settings.look = "None"
    try:
        node.format.compression = 15
    except Exception:
        pass
    node.file_slots[0].path = frame_id
    return node


def _scale_value(tree, socket, scale: float, *, name: str):
    node = tree.nodes.new("CompositorNodeMath")
    node.name = name
    node.operation = "MULTIPLY"
    node.inputs[1].default_value = float(scale)
    tree.links.new(socket, node.inputs[0])
    return node.outputs[0]


def _encode_signed_normal(tree, socket, *, name: str):
    """Map a vector in [-1, 1] to RGB UNORM [0, 1] without clamping."""
    scale = tree.nodes.new("CompositorNodeMixRGB")
    scale.name = f"{name}_signed_scale"
    scale.blend_type = "MULTIPLY"
    scale.inputs[0].default_value = 1.0
    scale.inputs[2].default_value = (0.5, 0.5, 0.5, 1.0)
    tree.links.new(socket, scale.inputs[1])
    bias = tree.nodes.new("CompositorNodeMixRGB")
    bias.name = f"{name}_signed_bias"
    bias.blend_type = "ADD"
    bias.inputs[0].default_value = 1.0
    bias.inputs[2].default_value = (0.5, 0.5, 0.5, 1.0)
    tree.links.new(scale.outputs[0], bias.inputs[1])
    return bias.outputs[0]


def _encode_artifact_socket(tree, stem: str, socket):
    if stem in {"normal_geometry_world", "normal_shading_camera"}:
        return _encode_signed_normal(tree, socket, name=stem)
    if stem == "depth":
        # 0 is Blender's miss value; positive values decode as u16 / 1000 m.
        return _scale_value(tree, socket, 1000.0 / _PNG16_MAX, name="depth_m_to_u16")
    if stem in {"object_id", "material_id"}:
        # IDs are assigned by this exporter and are checked below to fit u16.
        return _scale_value(tree, socket, 1.0 / _PNG16_MAX, name=f"{stem}_to_u16")
    return socket


def _setup_compositor(scene, out_dir: Path, frame_id: str):
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new("CompositorNodeRLayers")
    layers.name = "GT_RenderLayers"
    outputs = {}
    for source, stem in (
        ("GT_BaseColor", "base_color_rgb"),
        ("GT_Roughness", "roughness"),
        ("GT_Metallic", "metallic"),
        ("GT_GeometryNormal", "normal_geometry_world"),
        ("GT_MaterialID", "material_id"),
        ("Normal", "normal_shading_camera"),
        ("Depth", "depth"),
        ("IndexOB", "object_id"),
    ):
        socket = layers.outputs.get(source)
        if socket is None:
            continue
        node = tree.nodes.new("CompositorNodeOutputFile")
        _configure_png_output(node, out_dir, frame_id, stem)
        tree.links.new(_encode_artifact_socket(tree, stem, socket), node.inputs[0])
        outputs[stem] = node
    return outputs


def _collect_outputs(out_dir: Path, frame_id: str, stems: list[str]) -> dict[str, str]:
    result = {}
    for stem in stems:
        directory = _artifact_directory(out_dir, stem)
        matches = sorted(directory.glob(f"{frame_id}*.png"))
        if not matches:
            continue
        target = directory / f"{frame_id}.png"
        if matches[0] != target:
            if target.exists():
                target.unlink()
            matches[0].replace(target)
        for extra in matches[1:]:
            try:
                extra.unlink()
            except OSError:
                pass
        result[stem] = str(target.resolve())
    return result


def _artifact_contract() -> dict:
    artifacts = {}
    for stem, spec in _ARTIFACT_SPECS.items():
        artifacts[stem] = {
            **spec,
            "path_template": f"{stem}/{{frame_id}}.png",
        }
    return {
        "schema": "robomituba.blender_gt_artifact_contract.v2",
        "artifact_layout": _ARTIFACT_LAYOUT,
        "format": "PNG",
        "artifacts": artifacts,
        "decode": {
            "linear_unorm16": "float32(u16) / 65535",
            "xyz_signed_to_unorm16": "normalize(float32(u16) / 65535 * 2 - 1)",
            "millimeters_u16": "float32(u16) / 1000; 0 is invalid",
            "uint16": "u16 directly",
            "binary_mask_u8": "u8 > 0",
        },
    }


def main() -> int:
    args = _args()
    if args.require_pose_manifest and args.pose_manifest is None:
        raise ValueError("--require-pose-manifest requires --pose-manifest")
    if args.pose_manifest is not None and not args.pose_manifest.is_file():
        raise FileNotFoundError(f"pose manifest not found: {args.pose_manifest}")
    graph = json.loads(args.scene_graph.read_text(encoding="utf-8"))
    nodes = {str(row["node_id"]): row for row in graph["nodes"]}
    view_specs: list[tuple[str, float, str]] = []
    for spec in args.viewpoints.split(","):
        node_id, sep, yaw_text = spec.strip().partition("@")
        if node_id not in nodes:
            raise ValueError(f"viewpoint not found: {node_id}")
        yaw = float(yaw_text) if sep else 0.0
        view_specs.append((node_id, yaw, f"{node_id}__h_{int(round(yaw)) % 360:03d}"))
    origin_offset = _authoring_origin_offset(args.scene_graph, args.origin_offset)
    pose_manifest_index = _pose_manifest_rows(args.pose_manifest)
    args.out.mkdir(parents=True, exist_ok=True)
    domain = load_domain(args.ir_scene_domain)
    source_blend = Path(bpy.data.filepath).resolve()
    if not source_blend.is_file():
        raise ValueError(f"Blender GT requires a saved source blend, got {bpy.data.filepath!r}")
    domain_handles, domain_report = apply_face_exclusion(domain)
    try:
        scene = bpy.context.scene
        scene.render.engine = args.engine
        if args.engine == "CYCLES":
            # This exporter is an offline GT pass. Explicit CPU avoids trying to
            # create an EGL/OptiX context on headless workers and is deterministic
            # across the Blender installations used for asset authoring.
            scene.cycles.device = "CPU"
        scene.render.resolution_x = int(args.width)
        scene.render.resolution_y = int(args.height)
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_depth = "16"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.film_transparent = False
        scene.render.use_file_extension = True
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
        scene.render.fps = 1
        try:
            scene.render.image_settings.color_management = "FOLLOW_SCENE"
        except Exception:
            pass
        view_layer = bpy.context.view_layer
        _prepare_view_layer(view_layer)

        mesh_objects = sorted(
            (o for o in bpy.data.objects if o.type == "MESH" and len(o.data.polygons) > 0),
            key=lambda o: o.name,
        )
        materials_by_name = {}
        for obj in mesh_objects:
            for poly in obj.data.polygons:
                if 0 <= poly.material_index < len(obj.data.materials):
                    material = obj.data.materials[poly.material_index]
                    if material is not None:
                        materials_by_name[material.name] = material
        materials = [materials_by_name[name] for name in sorted(materials_by_name)]
        if len(materials) > int(_PNG16_MAX):
            raise ValueError(f"material count {len(materials)} exceeds PNG uint16 ID capacity")
        if len(mesh_objects) > int(_PNG16_MAX):
            raise ValueError(f"object count {len(mesh_objects)} exceeds PNG uint16 ID capacity")
        material_ids = {m.name: i for i, m in enumerate(materials, 1)}
        object_ids = {}
        for i, obj in enumerate(mesh_objects, 1):
            object_ids[obj.name] = i
            obj.pass_index = i
        created = _install_material_aovs(materials, material_ids)

        stems = list(_OUTPUT_STEMS)
        run_fingerprint = _gt_fingerprint(
            graph_path=args.scene_graph,
            source_blend=source_blend,
            args=args,
            domain=domain,
            frame_ids=[frame_id for _, _, frame_id in view_specs],
        )
        completed = prepare_resume(
            out=args.out, fingerprint_value=run_fingerprint, stems=stems,
            resume=bool(args.resume), adopt_existing=bool(args.adopt_existing),
        )
        records = []
        try:
            for node_id, yaw, frame_id in view_specs:
                resolved_pose = _lookup_pose_manifest(
                    pose_manifest_index, node_id, yaw, origin_offset=origin_offset
                )
                if args.require_pose_manifest and resolved_pose is None:
                    raise ValueError(f"missing required observation pose: {frame_id}")
                camera, pose = _camera_from_spec(
                    nodes[node_id],
                    yaw,
                    args.fov,
                    eye_height_m=args.eye_height,
                    target_height_m=args.target_height,
                    origin_offset=origin_offset,
                    resolved_pose=resolved_pose,
                )
                if frame_id in completed:
                    paths = _collect_outputs(args.out, frame_id, stems)
                    if set(paths) != set(stems):
                        raise ValueError(f"resume state claims incomplete frame {frame_id}")
                    print(f"[gt-aov] resume skip {frame_id}", flush=True)
                else:
                    _setup_compositor(scene, args.out, frame_id)
                    scene.camera = camera
                    scene.render.filepath = str(args.out / f"{frame_id}__combined.png")
                    scene.cycles.samples = max(1, int(args.samples))
                    bpy.ops.render.render(write_still=False)
                    paths = _collect_outputs(args.out, frame_id, stems)
                    if set(paths) != set(stems):
                        raise RuntimeError(
                            f"{frame_id}: output collection incomplete; expected={stems} got={sorted(paths)}"
                        )
                    completed.add(frame_id)
                    record_progress(args.out, run_fingerprint, completed)
                    print(f"[gt-aov] {frame_id} outputs={len(paths)}", flush=True)
                records.append({
                    "schema": "robomituba.blender_gt_frame.v3",
                    "frame_id": frame_id, "viewpoint_id": node_id,
                    "heading_deg": yaw, "width": args.width, "height": args.height,
                    "fov_deg": args.fov, "paths": paths,
                    "artifact_layout": _ARTIFACT_LAYOUT,
                    "artifact_contract_ref": "gt_artifact_contract.json",
                    "provider": "blender_aov",
                    "surface_domain": (domain or {}).get("surface_domain", "all"),
                    "effective_scene_digest": (domain or {}).get("effective_scene_digest"),
                    "ir_scene_domain_ref": str(args.ir_scene_domain.resolve()) if args.ir_scene_domain else None,
                    "pose_manifest_ref": str(args.pose_manifest) if resolved_pose is not None and args.pose_manifest else None,
                    **pose.provenance(),
                })
        finally:
            _remove_nodes(created)
    finally:
        restore_face_exclusion(domain_handles)

    contract = _artifact_contract()
    contract["surface_domain"] = (domain or {}).get("surface_domain", "all")
    contract["effective_scene_digest"] = (domain or {}).get("effective_scene_digest")
    contract["ir_scene_domain_ref"] = str(args.ir_scene_domain.resolve()) if args.ir_scene_domain else None
    (args.out / "gt_artifact_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "material_table.json").write_text(json.dumps({
        "schema": "robomituba.blender_gt_material_table.v3",
        "source_blend": bpy.data.filepath,
        "artifact_layout": _ARTIFACT_LAYOUT,
        "artifact_contract_ref": "gt_artifact_contract.json",
        "surface_domain": (domain or {}).get("surface_domain", "all"),
        "effective_scene_digest": (domain or {}).get("effective_scene_digest"),
        "ir_scene_domain_ref": str(args.ir_scene_domain.resolve()) if args.ir_scene_domain else None,
        "face_exclusion": domain_report,
        "materials": [
            {"material_id": material_ids[m.name], "blender_material": m.name,
             "use_nodes": bool(m.use_nodes)} for m in materials
        ],
        "objects": [{"object_id": i, "blender_object": n} for n, i in object_ids.items()],
    }, indent=2), encoding="utf-8")
    (args.out / "index.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
        encoding="utf-8",
    )
    print(f"[gt-aov] done frames={len(records)} out={args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
