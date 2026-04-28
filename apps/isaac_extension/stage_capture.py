"""Robomituba Isaac Extension — stage state capture."""
from __future__ import annotations

import datetime as _dt
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

# Allow importing sibling packages when running inside Isaac Sim
_APPS_DIR = Path(__file__).resolve().parent.parent
if str(_APPS_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_DIR))

DEFAULT_UNC_REPO_ROOT = r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba"


def _resolve_windows_repo_root(repo_root: str | None = None) -> str:
    return (
        repo_root
        or os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT")
        or os.environ.get("ROBOMITUBA_ROOT")
        or DEFAULT_UNC_REPO_ROOT
    )


def _repo_relative_to_local_path(path: str, *, repo_root: str | None = None) -> Path:
    from pathlib import PurePosixPath, PureWindowsPath

    resolved_repo_root = _resolve_windows_repo_root(repo_root)
    raw = str(path or "")
    if not raw:
        raise ValueError("Path must not be empty.")
    if raw.startswith(("file:", "omniverse://", "\\\\")) or (len(raw) > 1 and raw[1] == ":"):
        return Path(raw)
    return Path(PureWindowsPath(resolved_repo_root) / PurePosixPath(raw))


def capture_isaac_state(
    stage: Any,
    *,
    scene_id: str,
    mitsuba_scene_ref: str,
    scene_snapshot_ref: str | None = None,
    shape_map_ref: str | None = None,
    bsdf_overrides_by_path: Mapping[str, Any] | None = None,
    modalities: list[str] | None = None,
    render_settings: Mapping[str, Any] | None = None,
    submit_mode: str = "blocking",
    scene_version: str | None = None,
    illumination_setup: str = "ambient_room",
    assist_light: Mapping[str, Any] | None = None,
    depth_approx: Mapping[str, Any] | None = None,
) -> Any:
    """Capture the current Isaac Sim stage state as an IsaacStateSnapshot."""
    from isaac_standalone._stage_bridge import extract_snapshot as _extract_snapshot
    from isaac_capture_current_view_request import capture_active_view_camera
    from robomituba_bridge import CameraSpec, IsaacObjectState, IsaacStateSnapshot

    bsdf_map = dict(bsdf_overrides_by_path or {})
    requested_modalities = list(modalities or ["rgb"])

    scene_snap = _extract_snapshot(stage, scene_id=scene_id, frame_id="live")

    objects: list[IsaacObjectState] = []
    for mesh in scene_snap.meshes:
        if mesh.transform is None:
            continue
        selected_override = bsdf_map.get(mesh.source_path)
        objects.append(
            IsaacObjectState(
                prim_path=mesh.source_path,
                transform=mesh.transform,
                visible=True,
                bsdf_override=selected_override,
                bsdf_override_key=getattr(selected_override, "bsdf_type", None) if selected_override is not None else None,
                extras={
                    "mesh_id": mesh.mesh_id,
                    "mesh_name": mesh.name,
                    "material_id": mesh.material_id,
                },
            )
        )

    cam_dict = capture_active_view_camera()
    camera = CameraSpec(
        camera_id="isaac_viewport",
        name="Isaac Active Viewport",
        camera_to_world=list(cam_dict["camera_to_world"]),
        fov_deg=float(cam_dict["fov_deg"]),
        resolution=list(cam_dict.get("resolution") or []),
        sensor_modality="multimodal",
        sensor_sync_group="isaac_viewport",
        calibration_ref="isaac_active_view",
        source_camera_id=cam_dict.get("camera_path"),
        extras={"stage_camera_path": cam_dict.get("camera_path")},
    )

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    snapshot_id = f"isaac-{stamp}-{uuid.uuid4().hex[:6]}"
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()

    extras: dict[str, Any] = {
        "scene_version": scene_version,
        "illumination_setup": illumination_setup,
    }
    if assist_light:
        extras["assist_light"] = dict(assist_light)
    if depth_approx:
        extras["depth_approx"] = dict(depth_approx)

    return IsaacStateSnapshot(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        scene_id=scene_id,
        scene_snapshot_ref=scene_snapshot_ref,
        mitsuba_scene_ref=mitsuba_scene_ref,
        shape_map_ref=shape_map_ref,
        objects=objects,
        camera=camera,
        robot_state=scene_snap.robot_state,
        modalities=requested_modalities,
        submit_mode=submit_mode,
        render_settings=dict(render_settings or {}),
        extras=extras,
    )


def capture_session_open(
    *,
    scene_id: str,
    mitsuba_scene_ref: str,
    shape_map_ref: str,
    scene_snapshot_ref: str | None = None,
    extras: Mapping[str, Any] | None = None,
) -> Any:
    from robomituba_bridge import IsaacSessionOpen

    return IsaacSessionOpen(
        scene_id=scene_id,
        mitsuba_scene_ref=mitsuba_scene_ref,
        shape_map_ref=shape_map_ref,
        scene_snapshot_ref=scene_snapshot_ref,
        extras=dict(extras or {}),
    )


def capture_state_patch(
    stage: Any,
    *,
    scene_id: str = "live",
    bsdf_overrides_by_path: Mapping[str, Any] | None = None,
    timestamp: str | None = None,
    extras: Mapping[str, Any] | None = None,
) -> Any:
    from isaac_standalone._stage_bridge import extract_snapshot as _extract_snapshot
    from robomituba_bridge import IsaacObjectState, IsaacStatePatch

    scene_snap = _extract_snapshot(stage, scene_id=scene_id, frame_id="live")
    bsdf_map = dict(bsdf_overrides_by_path or {})
    objects: list[IsaacObjectState] = []
    for mesh in scene_snap.meshes:
        if mesh.transform is None:
            continue
        selected_override = bsdf_map.get(mesh.source_path)
        objects.append(
            IsaacObjectState(
                prim_path=mesh.source_path,
                transform=mesh.transform,
                visible=True,
                bsdf_override=selected_override,
                bsdf_override_key=getattr(selected_override, "bsdf_type", None) if selected_override is not None else None,
                extras={
                    "mesh_id": mesh.mesh_id,
                    "mesh_name": mesh.name,
                    "material_id": mesh.material_id,
                },
            )
        )
    return IsaacStatePatch(
        objects=objects,
        timestamp=timestamp or _dt.datetime.now(_dt.timezone.utc).isoformat(),
        extras=dict(extras or {}),
    )


def capture_material_patch(
    bsdf_overrides_by_path: Mapping[str, Any],
    *,
    timestamp: str | None = None,
    extras: Mapping[str, Any] | None = None,
) -> Any:
    from robomituba_bridge import IsaacMaterialPatch

    return IsaacMaterialPatch(
        overrides=dict(bsdf_overrides_by_path),
        timestamp=timestamp or _dt.datetime.now(_dt.timezone.utc).isoformat(),
        extras=dict(extras or {}),
    )


def capture_current_view_camera() -> Any:
    from isaac_capture_current_view_request import capture_active_view_camera
    from robomituba_bridge import CameraSpec

    cam_dict = capture_active_view_camera()
    return CameraSpec(
        camera_id="isaac_viewport",
        name="Isaac Active Viewport",
        camera_to_world=list(cam_dict["camera_to_world"]),
        fov_deg=float(cam_dict["fov_deg"]),
        resolution=list(cam_dict.get("resolution") or []),
        sensor_modality="multimodal",
        sensor_sync_group="isaac_viewport",
        calibration_ref="isaac_active_view",
        source_camera_id=cam_dict.get("camera_path"),
        extras={"stage_camera_path": cam_dict.get("camera_path")},
    )


def capture_current_view_sensor_spec(
    *,
    sensor_id: str = "viewport_current",
    name: str = "Current Viewport",
    modalities: list[str] | None = None,
    calibration_ref: str | None = "isaac_active_view",
    sensor_sync_group: str = "isaac_viewport",
    extras: Mapping[str, Any] | None = None,
) -> Any:
    from robomituba_bridge import IsaacSensorSpec

    camera = capture_current_view_camera()
    return IsaacSensorSpec(
        sensor_id=sensor_id,
        name=name,
        modalities=list(modalities or ["rgb"]),
        calibration_ref=calibration_ref,
        camera_to_world=list(camera.camera_to_world),
        fov_deg=float(camera.fov_deg),
        resolution=list(camera.resolution) if camera.resolution is not None else None,
        sensor_sync_group=sensor_sync_group,
        pose_source=camera.source_camera_id,
        extras={**dict(camera.extras), **dict(extras or {})},
    )


def capture_selected_prim_paths(stage: Any | None = None) -> list[str]:
    try:
        import omni.usd  # type: ignore
    except Exception:
        return []

    try:
        selection = omni.usd.get_context().get_selection()
        prim_paths = selection.get_selected_prim_paths()
    except Exception:
        prim_paths = []
    return [str(path) for path in prim_paths if isinstance(path, str) and path]


def generate_shape_map_for_stage(
    stage: Any,
    *,
    scene_id: str,
    mitsuba_scene_ref: str,
    shape_map_ref: str | None = None,
    scene_snapshot_ref: str | None = None,
    repo_root: str | None = None,
) -> dict[str, Any]:
    import json

    from isaac_standalone._stage_bridge import extract_snapshot as _extract_snapshot
    from robomituba_bridge import build_shape_mapping, to_repo_relative_posix, write_shape_mapping
    from robomituba_bridge.io import scene_snapshot_to_payload

    scene_snapshot = _extract_snapshot(stage, scene_id=scene_id, frame_id="live")
    local_scene_xml = _repo_relative_to_local_path(mitsuba_scene_ref, repo_root=repo_root)
    resolved_repo_root = Path(_resolve_windows_repo_root(repo_root)).resolve()

    # Persist the extracted SceneSnapshot alongside the XML so downstream code
    # (3D Blueprint, offline consumers) can load it back without Isaac. Without
    # this, scene_snapshot_ref kept pointing at the shape_map.json from a prior
    # run and `_load_snapshot_sidecars` silently returned None.
    local_snapshot_path = local_scene_xml.with_suffix(".scene_snapshot.json")
    local_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    local_snapshot_path.write_text(
        json.dumps(scene_snapshot_to_payload(scene_snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    resolved_scene_snapshot_ref = to_repo_relative_posix(resolved_repo_root, local_snapshot_path.resolve())

    if shape_map_ref:
        local_shape_map = _repo_relative_to_local_path(shape_map_ref, repo_root=repo_root)
    else:
        local_shape_map = local_scene_xml.with_suffix(".shape_map.json")
        shape_map_ref = to_repo_relative_posix(resolved_repo_root, local_shape_map.resolve())

    mapping_payload = build_shape_mapping(scene_snapshot, local_scene_xml)
    write_shape_mapping(
        local_shape_map,
        mapping_payload=mapping_payload,
        repo_root=resolved_repo_root,
        scene_xml_ref=mitsuba_scene_ref,
        scene_snapshot_ref=resolved_scene_snapshot_ref,
    )
    return {
        "status": "generated",
        "scene_id": scene_id,
        "shape_map_ref": shape_map_ref,
        "shape_map_path": str(local_shape_map),
        "scene_snapshot_ref": resolved_scene_snapshot_ref,
        "scene_snapshot_path": str(local_snapshot_path),
        "unmatched_prim_paths": list(mapping_payload.get("unmatched_prim_paths") or []),
        "prim_count": len(mapping_payload.get("prim_to_shape_ids") or {}),
        "shape_count": int(mapping_payload.get("shape_count") or 0),
    }
