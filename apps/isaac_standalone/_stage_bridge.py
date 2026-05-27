from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import math
from typing import Any

from ._bootstrap import bootstrap_repo_paths

REPO_ROOT = bootstrap_repo_paths()

from robomituba_bridge.io import scene_snapshot_to_payload
from robomituba_bridge.paths import to_repo_relative_posix
from robomituba_bridge.shape_mapping import build_shape_mapping, write_shape_mapping
from robomituba_bridge.types import CameraRecord, FrameRecord, LightRecord, MaterialRecord, MeshRecord, RobotState, SceneSnapshot
from mitsuba_converter.usd_snapshot import extract_snapshot_from_stage


def _require_pxr():
    try:
        from pxr import Gf, Usd, UsdGeom, UsdLux, UsdShade
    except Exception as exc:
        raise RuntimeError("pxr Python bindings are required. Run this inside Isaac Sim Python or an OpenUSD environment.") from exc
    return Gf, Usd, UsdGeom, UsdLux, UsdShade


def load_stage(*, usd_path: str | None = None):
    _, Usd, _, _, _ = _require_pxr()
    if usd_path:
        stage = Usd.Stage.Open(usd_path)
        if stage is None:
            raise RuntimeError(f"Failed to open USD stage: {usd_path}")
        return stage, Path(usd_path).resolve()

    try:
        from isaacsim.core.utils.stage import get_current_stage
    except Exception as exc:
        raise RuntimeError("Isaac Sim stage API is unavailable. Pass --usd or run this inside Isaac Sim Python.") from exc

    stage = get_current_stage()
    if stage is None:
        raise RuntimeError("No current USD stage is open in Isaac Sim.")

    root_layer = stage.GetRootLayer()
    real_path = getattr(root_layer, "realPath", "") or ""
    return stage, Path(real_path).resolve() if real_path else None


def _tri_face_count(counts: list[int]) -> int:
    return sum(max(int(count) - 2, 0) for count in counts)


def _matrix_to_list(matrix: Any) -> list[float]:
    import numpy as np

    candidate = np.asarray(matrix, dtype=np.float32)
    if candidate.shape == (16,):
        candidate = candidate.reshape(4, 4)
    if candidate.shape != (4, 4):
        raise ValueError(f"Expected 4x4 matrix, got {candidate.shape}")
    last_col = candidate[:3, 3]
    last_row = candidate[3, :3]
    if float(np.linalg.norm(last_row)) > max(1e-5, float(np.linalg.norm(last_col)) * 2.0):
        candidate = candidate.T
    return candidate.reshape(-1).astype(float).tolist()


def _extract_look_at(matrix) -> dict[str, list[float]]:
    Gf, _, _, _, _ = _require_pxr()
    origin = matrix.Transform(Gf.Vec3d(0, 0, 0))
    target = matrix.Transform(Gf.Vec3d(0, 0, -1))
    up = matrix.TransformDir(Gf.Vec3d(0, 1, 0))
    return {
        "origin": [float(origin[0]), float(origin[1]), float(origin[2])],
        "target": [float(target[0]), float(target[1]), float(target[2])],
        "up": [float(up[0]), float(up[1]), float(up[2])],
    }


def _fov_from_camera(camera) -> float | None:
    focal_length = camera.GetFocalLengthAttr().Get()
    aperture = camera.GetHorizontalApertureAttr().Get()
    if not focal_length or not aperture:
        return None
    return float(2.0 * math.degrees(math.atan(aperture / (2.0 * focal_length))))


def _repo_rel_or_none(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return to_repo_relative_posix(REPO_ROOT, path)
    except Exception:
        return None


def _resolve_asset_path(source_usd_path: Path | None, asset_path: Any) -> str | None:
    if not asset_path:
        return None
    raw = str(asset_path).strip("@")
    candidate = Path(raw)
    if not candidate.is_absolute() and source_usd_path is not None:
        candidate = (source_usd_path.parent / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return _repo_rel_or_none(candidate)


def _unwrap_connected_source(payload):
    value = payload
    while isinstance(value, (tuple, list)) and value:
        value = value[0]
    return value


def _connected_shader(shader_input, UsdShade):
    if not shader_input:
        return None
    connected = shader_input.GetConnectedSource()
    if not connected:
        return None
    prim = _unwrap_connected_source(connected)
    return UsdShade.Shader(prim.GetPrim())


def _extract_texture(shader_input, source_usd_path: Path | None, UsdShade) -> str | None:
    shader = _connected_shader(shader_input, UsdShade)
    if shader is None:
        return None
    shader_id = shader.GetIdAttr().Get() or ""
    if "UVTexture" not in shader_id and "UsdUVTexture" not in shader_id:
        return None
    file_input = shader.GetInput("file")
    if not file_input:
        return None
    return _resolve_asset_path(source_usd_path, file_input.Get())


def _extract_material_record(material, source_usd_path: Path | None):
    _, _, _, _, UsdShade = _require_pxr()

    material_path = str(material.GetPath())
    shader_model = None
    base_color = None
    roughness = None
    metallic = None
    ior = None
    opacity = None
    textures: dict[str, str] = {}

    surface_output = material.GetSurfaceOutput()
    shader = None
    if surface_output:
        connected = surface_output.GetConnectedSource()
        if connected:
            shader = UsdShade.Shader(_unwrap_connected_source(connected).GetPrim())
            shader_model = shader.GetIdAttr().Get()

    if shader:
        def _float_or_none(name: str) -> float | None:
            shader_input = shader.GetInput(name)
            if not shader_input:
                return None
            value = shader_input.Get()
            return float(value) if value is not None else None

        def _vec3_or_none(name: str) -> list[float] | None:
            shader_input = shader.GetInput(name)
            if not shader_input:
                return None
            value = shader_input.Get()
            if value is None:
                return None
            return [float(value[0]), float(value[1]), float(value[2])]

        base_color = _vec3_or_none("diffuseColor") or _vec3_or_none("base_color")
        roughness = _float_or_none("roughness")
        metallic = _float_or_none("metallic")
        ior = _float_or_none("ior")
        opacity = _float_or_none("opacity")

        texture_slots = {
            "base_color": ["diffuseColor", "base_color"],
            "roughness": ["roughness"],
            "metallic": ["metallic"],
            "normal": ["normal", "normalmap"],
            "opacity": ["opacity"],
        }
        for target_slot, source_slots in texture_slots.items():
            for source_slot in source_slots:
                texture_path = _extract_texture(shader.GetInput(source_slot), source_usd_path, UsdShade)
                if texture_path:
                    textures[target_slot] = texture_path
                    break

    return MaterialRecord(
        material_id=material_path,
        name=material.GetPrim().GetName(),
        source_path=material_path,
        shader_model=str(shader_model) if shader_model else None,
        base_color=base_color,
        roughness=roughness,
        metallic=metallic,
        ior=ior,
        opacity=opacity,
        textures=textures,
    )


def _is_renderable_mesh(mesh_prim) -> bool:
    imageable = None
    try:
        _, _, UsdGeom, _, _ = _require_pxr()
        imageable = UsdGeom.Imageable(mesh_prim)
    except Exception:
        imageable = None

    if imageable:
        purpose_attr = imageable.GetPurposeAttr()
        purpose = purpose_attr.Get() if purpose_attr else None
        if str(purpose or "") in {"guide", "proxy"}:
            return False
        visibility_attr = imageable.GetVisibilityAttr()
        visibility = visibility_attr.Get() if visibility_attr else None
        if str(visibility or "") == "invisible":
            return False

    path_lower = str(mesh_prim.GetPath()).lower()
    return "/colliders/" not in path_lower and "/collision/" not in path_lower


def _attr_value(prim, name: str):
    attr = prim.GetAttribute(name)
    if not attr:
        return None
    return attr.Get()


def _extract_robot_state(stage, xform_cache) -> RobotState | None:
    for prim in stage.Traverse():
        robot_name = _attr_value(prim, "robomituba:robotName")
        if str(robot_name or "") != "ranger_mini_v3":
            continue

        joint_names_raw = _attr_value(prim, "robomituba:jointNames") or []
        joint_positions_raw = _attr_value(prim, "robomituba:jointPositions") or []
        steering_angles_raw = _attr_value(prim, "robomituba:steeringAngles") or []
        wheel_speeds_raw = _attr_value(prim, "robomituba:wheelSpeeds") or []

        joint_names = [str(item) for item in joint_names_raw]
        joint_positions = [float(item) for item in joint_positions_raw]
        steering_angles = [float(item) for item in steering_angles_raw]
        wheel_speeds = [float(item) for item in wheel_speeds_raw]

        battery_soc = _attr_value(prim, "robomituba:batterySoc")
        battery_voltage = _attr_value(prim, "robomituba:batteryVoltage")
        estop = _attr_value(prim, "robomituba:estop")
        has_error = _attr_value(prim, "robomituba:hasError")
        motion_mode = _attr_value(prim, "robomituba:motionMode")

        return RobotState(
            base_pose=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
            joint_names=joint_names,
            joint_positions=joint_positions,
            extras={
                "ranger_mini": {
                    "robot_name": "ranger_mini_v3",
                    "motion_mode": int(motion_mode) if motion_mode is not None else 0,
                    "steering_angles": steering_angles,
                    "wheel_speeds": wheel_speeds,
                    "battery": {
                        "voltage": float(battery_voltage) if battery_voltage is not None else 48.0,
                        "soc": float(battery_soc) if battery_soc is not None else 1.0,
                    },
                    "estop": bool(estop) if estop is not None else False,
                    "has_error": bool(has_error) if has_error is not None else False,
                }
            },
        )
    return None


def extract_snapshot(
    stage,
    *,
    scene_id: str,
    frame_id: str,
    timestamp: str | None = None,
    usd_stage_path: str | None = None,
    source_usd_path: Path | None = None,
) -> SceneSnapshot:
    extracted = extract_snapshot_from_stage(
        stage,
        scene_id=scene_id,
        frame_id=frame_id,
        timestamp=timestamp,
        usd_stage_path=usd_stage_path,
        source_usd_path=source_usd_path,
        repo_root=REPO_ROOT,
        include_geometry_payloads=True,
    )
    return extracted.snapshot


def inspect_stage_summary(stage, *, source_usd_path: Path | None = None) -> dict[str, Any]:
    snapshot = extract_snapshot(
        stage,
        scene_id="inspect",
        frame_id="inspect",
        source_usd_path=source_usd_path,
    )
    return {
        "scene_id": snapshot.scene_id,
        "mesh_count": len(snapshot.meshes),
        "material_count": len(snapshot.materials),
        "camera_count": len(snapshot.cameras),
        "light_count": len(snapshot.lights),
        "meters_per_unit": snapshot.frame.meters_per_unit,
        "up_axis": snapshot.frame.up_axis,
    }


def export_stage_to_usda(stage, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stage.Export(str(output_path))


def write_snapshot_directory(
    snapshot: SceneSnapshot,
    output_dir: Path,
    *,
    scene_xml_path: Path | None = None,
    repo_root: Path | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "scene_snapshot.json").write_text(
        json.dumps(scene_snapshot_to_payload(snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "materials.json").write_text(
        json.dumps({"materials": [asdict(item) for item in snapshot.materials]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "cameras.json").write_text(
        json.dumps({"cameras": [asdict(item) for item in snapshot.cameras]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "lights.json").write_text(
        json.dumps({"lights": [asdict(item) for item in snapshot.lights]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if scene_xml_path is not None:
        mapping_payload = build_shape_mapping(snapshot, scene_xml_path)
        shape_map_path = output_dir / "shape_map.json"
        write_shape_mapping(
            shape_map_path,
            mapping_payload=mapping_payload,
            repo_root=repo_root or REPO_ROOT,
            scene_xml_ref=_repo_rel_or_none(scene_xml_path.resolve()),
            scene_snapshot_ref=_repo_rel_or_none((output_dir / "scene_snapshot.json").resolve()),
        )
