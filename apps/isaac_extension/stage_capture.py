"""Robomituba Isaac Extension — stage state capture."""
from __future__ import annotations

import datetime as _dt
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

# Allow importing sibling packages when running inside Isaac Sim
_APPS_DIR = Path(__file__).resolve().parent.parent
if str(_APPS_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_DIR))


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
        modalities=requested_modalities,
        submit_mode=submit_mode,
        render_settings=dict(render_settings or {}),
        extras=extras,
    )
