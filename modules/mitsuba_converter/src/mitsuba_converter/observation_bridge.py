from __future__ import annotations

from dataclasses import asdict, fields, replace
import json
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from types import SimpleNamespace

import numpy as np

from robomituba_bridge import (
    AssistLightSpec,
    CameraSpec,
    DepthApproxSpec,
    IsaacSensorSpec,
    ObservationBundleManifest,
    RenderArtifactManifest,
    RenderRequest,
    RobotState,
    SceneOverrideSpec,
    SceneState,
    ensure_observation_layout,
    resolve_repo_path,
    to_repo_relative_posix,
    validate_observation_bundle_manifest,
    validate_render_request,
    write_observation_bundle_manifest,
    load_ouster_metadata,
)

from .multimodal import MODALITY_DEFINITIONS, MultimodalRenderResult, RenderConfig, camera_to_world_from_lookat, render_modalities
from .multimodal import _camera_basis, _compute_target_union_bounds, _project_bounds_to_image_bbox
from .versioned_artifacts import versioned_bundle_dir


REFLECTIVE_ISLAND_RGB_TARGETS = (
    "materials_sideboard_mtl.obj",
    "materials_counterMarble_mtl.obj",
    "materials_kitchenBooks_mtl.obj",
)
REFLECTIVE_ISLAND_DEPTH_TARGETS = (
    "materials_counterMarble_mtl.obj",
    "materials_kitchenBooks_mtl.obj",
)
REFLECTIVE_ISLAND_STEP_LENGTHS_M = (0.7, 0.75, 0.8)
AMBIENT_MODALITIES = {
    "rgb",
    "depth",
    "depth_sensor",
    "depth_transient",
    "albedo",
    "direct_light_map",
    "indirect_light_map",
    "diffuse_map",
    "specular_map",
    "hazard_mask",
}
ACTIVE_MODALITIES = {
    "active_nir_intensity",
    "nir_intensity",
    "sensor_depth_approx",
    "lidar_point_cloud",
    "lidar_range",
    "lidar_signal",
    "lidar_reflectivity",
    "lidar_near_ir",
    "lidar_valid",
    "lidar_xyz",
}
POLAR_MODALITIES = {
    "polar_rgb_preview",
    "s1",
    "s2",
    "s1_over_s0",
    "s2_over_s0",
    "dop",
    "aolp",
}


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm < 1e-8:
        raise ValueError("Cannot normalize a near-zero vector")
    return np.asarray(v, dtype=np.float32) / norm


def build_reflective_island_frontal_candidate_cameras(
    base_camera: CameraSpec,
    *,
    step_lengths_m: tuple[float, ...] = REFLECTIVE_ISLAND_STEP_LENGTHS_M,
    step_count: int = 5,
) -> list[CameraSpec]:
    camera_to_world = np.asarray(base_camera.camera_to_world, dtype=np.float32).reshape(4, 4)
    origin, _right, _up, forward = _camera_basis(camera_to_world)
    horizontal = _normalize(np.array([forward[0], 0.0, forward[2]], dtype=np.float32))
    rotated_horizontal = np.array([-horizontal[2], 0.0, horizontal[0]], dtype=np.float32)
    new_forward = _normalize(np.array([rotated_horizontal[0], float(forward[1]), rotated_horizontal[2]], dtype=np.float32))
    world_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    new_right = _normalize(np.cross(new_forward, world_up))
    new_left = -new_right

    candidates: list[CameraSpec] = []
    for step_length in step_lengths_m:
        candidate_origin = origin + new_left * float(step_count * step_length)
        candidate_target = candidate_origin + new_forward * 5.0
        candidate_matrix = camera_to_world_from_lookat(candidate_origin, candidate_target, world_up).reshape(-1).tolist()
        step_tag = f"{int(round(step_length * 100)):03d}"
        candidates.append(
            CameraSpec(
                camera_id=f"{base_camera.camera_id}_frontal_step{step_tag}",
                name=f"{base_camera.name} Frontal {step_length:.2f}m",
                camera_to_world=candidate_matrix,
                fov_deg=base_camera.fov_deg,
                resolution=list(base_camera.resolution) if base_camera.resolution is not None else None,
                sensor_modality=base_camera.sensor_modality,
                sensor_sync_group=base_camera.sensor_sync_group,
                calibration_ref=base_camera.calibration_ref,
                source_camera_id=base_camera.camera_id,
                extras={
                    **base_camera.extras,
                    "base_camera_id": base_camera.camera_id,
                    "step_count": int(step_count),
                    "step_length_m": float(step_length),
                    "origin": candidate_origin.astype(float).tolist(),
                    "target": candidate_target.astype(float).tolist(),
                },
            )
        )
    return candidates


def select_projected_bbox_candidate(
    scene_xml: str | Path,
    candidates: list[CameraSpec],
    *,
    target_shape_filenames: list[str] | tuple[str, ...],
    width: int | None = None,
    height: int | None = None,
) -> tuple[CameraSpec, list[dict[str, Any]]]:
    scene_path = Path(scene_xml)
    bounds = _compute_target_union_bounds(scene_path, set(target_shape_filenames))
    if bounds is None:
        raise RuntimeError(f"Could not resolve bounds for targets: {target_shape_filenames}")

    metrics: list[dict[str, Any]] = []
    for index, camera_spec in enumerate(candidates):
        metric_width = int(camera_spec.resolution[0]) if camera_spec.resolution is not None else int(width or 768)
        metric_height = int(camera_spec.resolution[1]) if camera_spec.resolution is not None else int(height or 576)
        camera_to_world = np.asarray(camera_spec.camera_to_world, dtype=np.float32).reshape(4, 4)
        bbox = _project_bounds_to_image_bbox(
            bounds[0],
            bounds[1],
            camera_to_world=camera_to_world,
            fov_deg=float(camera_spec.fov_deg),
            width=metric_width,
            height=metric_height,
        )
        if bbox is None:
            center_distance = float("inf")
            area = 0
            bbox_center = None
        else:
            x0, y0, x1, y1 = bbox
            bbox_center = [0.5 * (x0 + x1), 0.5 * (y0 + y1)]
            center_distance = float(np.hypot(bbox_center[0] - (metric_width * 0.5), bbox_center[1] - (metric_height * 0.5)))
            area = int(max(0, x1 - x0) * max(0, y1 - y0))
        step_length = float(camera_spec.extras.get("step_length_m", 0.75))
        metrics.append(
            {
                "index": index,
                "camera_id": camera_spec.camera_id,
                "camera_name": camera_spec.name,
                "step_length_m": step_length,
                "projected_bbox": list(bbox) if bbox is not None else None,
                "bbox_center_distance_px": center_distance,
                "bbox_area_px": area,
                "resolution": [metric_width, metric_height],
            }
        )

    ranked = sorted(
        metrics,
        key=lambda item: (
            item["bbox_center_distance_px"],
            -item["bbox_area_px"],
            abs(float(item["step_length_m"]) - 0.75),
            item["camera_id"],
        ),
    )
    selected = candidates[int(ranked[0]["index"])]
    return selected, metrics


def render_config_from_payload(payload: Mapping[str, Any] | None) -> RenderConfig:
    if payload is None:
        return RenderConfig()
    settings = dict(payload)
    # Accept old saved requests while removing the retired material fallback control.
    settings.pop("polar_fallback_mode", None)
    allowed = {item.name for item in fields(RenderConfig)}
    unknown = sorted(set(settings.keys()) - allowed)
    if unknown:
        raise ValueError(f"Unknown render_settings keys: {', '.join(unknown)}")
    return RenderConfig(**settings)



def _camera_render_settings_payload(
    base_payload: Mapping[str, Any] | None,
    camera_spec: CameraSpec,
    modalities: Any = None,
) -> dict[str, Any]:
    payload = dict(base_payload or {})
    extras = camera_spec.extras if isinstance(camera_spec.extras, Mapping) else {}
    overrides = extras.get("render") if isinstance(extras.get("render"), Mapping) else extras.get("render_settings")
    if isinstance(overrides, Mapping):
        allowed = {item.name for item in fields(RenderConfig)}
        for key, value in overrides.items():
            if key in allowed and value is not None:
                payload[str(key)] = value
    return payload


def _camera_modalities(render_request: RenderRequest, camera_spec: CameraSpec) -> list[str]:
    extras = camera_spec.extras if isinstance(camera_spec.extras, Mapping) else {}
    values = extras.get("render_modalities")
    if isinstance(values, list):
        modalities = [str(item) for item in values if str(item)]
        if modalities:
            return modalities
    value = extras.get("render_modality")
    if value:
        return [str(value)]
    fallback = list(render_request.modalities)
    # A mixed camera + non-camera request stores the union at request level.
    # Do not accidentally render Ouster/depth sensor fields once per camera.
    sensor_modalities = {
        str(item)
        for sensor in getattr(render_request, "sensor_specs", [])
        for item in (getattr(sensor, "modalities", []) or [])
    }
    if sensor_modalities:
        fallback = [item for item in fallback if item not in sensor_modalities]
    return fallback or ["rgb"]


def _camera_assist_light(render_request: RenderRequest, camera_spec: CameraSpec, camera_modalities: list[str]) -> AssistLightSpec | None:
    extras = camera_spec.extras if isinstance(camera_spec.extras, Mapping) else {}
    # Multi-sensor rig sweeps stamp render_modalities per camera. In that mode,
    # keep camera-aligned active illumination scoped to the cameras that need it
    # instead of lighting unrelated RGB/polar cameras in the same bundle.
    if "render_modalities" in extras:
        if any(item in {"active_nir_intensity", "nir_intensity"} for item in camera_modalities) or extras.get("active_emitter"):
            return render_request.assist_light
        # An active-polar request intentionally scopes the same camera-aligned
        # area-emitter + polarizer construction to polar cameras only.  This
        # keeps RGB cameras passive in a mixed rig capture.
        request_extras = render_request.extras if isinstance(render_request.extras, Mapping) else {}
        if bool(request_extras.get("polar_active")) and any(item in POLAR_MODALITIES for item in camera_modalities):
            return render_request.assist_light
        return None
    return render_request.assist_light


def render_config_to_payload(config: RenderConfig) -> dict[str, Any]:
    return asdict(config)


def _repo_relative_or_value(repo_root: Path, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        candidate = Path(value)
        if candidate.is_absolute():
            return to_repo_relative_posix(repo_root, candidate)
    except Exception:
        return value
    return value


def _dependencies_from_result(repo_root: Path, result) -> dict[str, Any]:
    dependencies: dict[str, Any] = {}
    metadata_deps = result.metadata.get("dependencies")
    if isinstance(metadata_deps, Mapping):
        dependencies["artifacts"] = {key: _repo_relative_or_value(repo_root, value) for key, value in metadata_deps.items()}
    timing_sources = result.timing.get("source_results")
    if timing_sources is not None:
        dependencies["source_results"] = timing_sources
    return dependencies


def _artifact_manifest_from_result(
    repo_root: Path,
    camera_spec: CameraSpec,
    modality: str,
    result,
) -> RenderArtifactManifest:
    artifacts = {key: _repo_relative_or_value(repo_root, value) for key, value in result.artifacts.items()}
    scene_ref = _repo_relative_or_value(repo_root, result.timing.get("scene"))
    material_mode = result.metadata.get("material_mode") or result.timing.get("material_mode")
    return RenderArtifactManifest(
        camera_id=camera_spec.camera_id,
        modality=modality,
        definition=MODALITY_DEFINITIONS.get(modality, MODALITY_DEFINITIONS.get("polarization", "")),
        artifact_paths=artifacts,
        timing=dict(result.timing),
        dependencies=_dependencies_from_result(repo_root, result),
        scene_ref=scene_ref if isinstance(scene_ref, str) else None,
        material_mode=material_mode,
        array_shape=list(result.array.shape),
        dtype=str(result.array.dtype),
        extras={
            "camera_name": camera_spec.name,
            "sensor_modality": camera_spec.sensor_modality,
            "sensor_sync_group": camera_spec.sensor_sync_group,
            "calibration_ref": camera_spec.calibration_ref,
            "raw_channels": sorted(result.raw_channels.keys()),
            "illumination_tag": result.metadata.get("illumination_tag"),
            "target_shape_filenames": result.metadata.get("target_shape_filenames"),
            "material_profile": result.metadata.get("material_profile"),
            "depth_model": result.metadata.get("depth_model"),
            "assist_light": result.metadata.get("assist_light"),
            "polar_visualization_policy": result.metadata.get("polar_visualization_policy"),
            "stokes_preview_recipe": result.metadata.get("stokes_preview_recipe"),
            "derived_on_demand": result.metadata.get("derived_on_demand"),
        },
    )


def _sensor_artifact_manifest_from_result(
    repo_root: Path,
    sensor_spec: IsaacSensorSpec,
    modality: str,
    result,
) -> RenderArtifactManifest:
    artifacts = {key: _repo_relative_or_value(repo_root, value) for key, value in result.artifacts.items()}
    scene_ref = _repo_relative_or_value(repo_root, result.timing.get("scene"))
    return RenderArtifactManifest(
        camera_id=sensor_spec.sensor_id,
        sensor_id=sensor_spec.sensor_id,
        modality=modality,
        definition=MODALITY_DEFINITIONS.get(modality, "Sensor artifact"),
        artifact_paths=artifacts,
        timing=dict(result.timing),
        dependencies=_dependencies_from_result(repo_root, result),
        scene_ref=scene_ref if isinstance(scene_ref, str) else None,
        material_mode=result.metadata.get("material_mode"),
        array_shape=list(result.array.shape),
        dtype=str(result.array.dtype),
        extras={
            "sensor_id": sensor_spec.sensor_id,
            "sensor_name": sensor_spec.name,
            "sensor_type": sensor_spec.sensor_type,
            "profile": sensor_spec.profile,
            "sensor_sync_group": sensor_spec.sensor_sync_group,
            "calibration_ref": sensor_spec.calibration_ref,
            "metadata_ref": sensor_spec.metadata_ref,
            "raw_channels": sorted(result.raw_channels.keys()),
            "sensor_metadata": result.metadata.get("metadata"),
            "depth_space": result.metadata.get("depth_space"),
            "units": result.metadata.get("units"),
            "frame": "sensor",
            "staggered": bool(sensor_spec.sensor_type == "ouster_lidar"),
            "destaggered_ref": artifacts.get("destaggered_npz") if sensor_spec.sensor_type == "ouster_lidar" else None,
            "measurement_id_ref": artifacts.get("raw_npz") if sensor_spec.sensor_type == "ouster_lidar" else None,
            "timestamp_ref": artifacts.get("raw_npz") if sensor_spec.sensor_type == "ouster_lidar" else None,
            "polar_visualization_policy": result.metadata.get("polar_visualization_policy"),
            "stokes_preview_recipe": result.metadata.get("stokes_preview_recipe"),
            "derived_on_demand": result.metadata.get("derived_on_demand"),
        },
    )


def _sensor_render_settings_payload(
    base_payload: Mapping[str, Any] | None,
    sensor_spec: IsaacSensorSpec,
) -> dict[str, Any]:
    payload = dict(base_payload or {})
    extras = sensor_spec.extras if isinstance(sensor_spec.extras, Mapping) else {}
    overrides = extras.get("render") if isinstance(extras.get("render"), Mapping) else extras.get("render_settings")
    allowed = {item.name for item in fields(RenderConfig)}
    if isinstance(overrides, Mapping):
        for key, value in overrides.items():
            if key in allowed and value is not None:
                payload[str(key)] = value
    if sensor_spec.resolution and len(sensor_spec.resolution) == 2:
        payload.setdefault("width", int(sensor_spec.resolution[0]))
        payload.setdefault("height", int(sensor_spec.resolution[1]))
    if sensor_spec.sensor_type == "ouster_lidar":
        payload.setdefault("lidar_profile", sensor_spec.profile or "os1-128")
        if sensor_spec.metadata_ref:
            payload.setdefault("lidar_metadata_ref", sensor_spec.metadata_ref)
        for source, target in (
            ("return_mode", "lidar_return_mode"),
            ("noise_std_m", "lidar_noise_std_m"),
            ("dropout_probability", "lidar_dropout_probability"),
            ("signal_scale", "lidar_signal_scale"),
            ("destagger", "lidar_destagger"),
            ("wavelength_nm", "lidar_wavelength_nm"),
            ("min_range_m", "lidar_min_range_m"),
            ("max_range_m", "lidar_max_range_m"),
        ):
            if source in extras and extras[source] is not None:
                payload.setdefault(target, extras[source])
    return payload



def _versioned_bundle_dir_for_request(render_request: RenderRequest, root: Path) -> Path | None:
    """Resolve an OpticalNav request to its immutable version directory."""
    extras = render_request.extras if isinstance(render_request.extras, Mapping) else {}
    project_id = str(extras.get("opticalnav_project_id") or "").strip()
    scene_id = str(extras.get("opticalnav_scene_id") or render_request.scene_state.scene_id or "").strip()
    render_version_id = str(extras.get("render_version_id") or "").strip()
    node_id = str(extras.get("opticalnav_vp_id") or extras.get("node_id") or "").strip()
    heading_id = str(extras.get("opticalnav_heading_id") or extras.get("heading_id") or "").strip()
    if not all((project_id, scene_id, render_version_id, node_id, heading_id)):
        return None
    variant = str(extras.get("scene_variant_key") or ("perturbed" if "-perturbed-" in render_request.job_id else "base")).lower()
    project_dir = root / "out" / "opticalnav" / project_id
    return versioned_bundle_dir(
        project_dir,
        scene_id=scene_id,
        render_version_id=render_version_id,
        variant=variant,
        node_id=node_id,
        heading_id=heading_id,
    )


def _observation_layout_for_request(render_request: RenderRequest, root: Path) -> Any:
    version_dir = _versioned_bundle_dir_for_request(render_request, root)
    if version_dir is None:
        return ensure_observation_layout(root, render_request.job_id, render_request.frame_id)
    cameras_dir = version_dir / "cameras"
    sensors_dir = version_dir / "sensors"
    logs_dir = version_dir / "logs"
    for path in (version_dir, cameras_dir, sensors_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(frame_dir=version_dir, cameras_dir=cameras_dir, sensors_dir=sensors_dir, logs_dir=logs_dir)


def _merge_existing_versioned_artifacts(layout: Any, artifacts: list[RenderArtifactManifest], requested_modalities: list[str]) -> tuple[list[RenderArtifactManifest], list[str]]:
    """Merge phase manifests when RGB and polar jobs share one version dir."""
    manifest_path = Path(layout.frame_dir) / "manifest.json"
    if not manifest_path.exists():
        return artifacts, requested_modalities
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous = payload.get("artifacts") if isinstance(payload, Mapping) else None
        if not isinstance(previous, list):
            return artifacts, requested_modalities
        merged: dict[tuple[str, str], RenderArtifactManifest] = {}
        for item in previous:
            if not isinstance(item, Mapping):
                continue
            try:
                key = (str(item.get("camera_id") or item.get("sensor_id") or ""), str(item.get("modality") or ""))
                merged[key] = RenderArtifactManifest(**dict(item))
            except Exception:
                continue
        for item in artifacts:
            key = (str(item.camera_id or item.sensor_id or ""), str(item.modality or ""))
            merged[key] = item
        requested = list(dict.fromkeys([*payload.get("requested_modalities", []), *requested_modalities]))
        return list(merged.values()), requested
    except (OSError, ValueError, TypeError):
        return artifacts, requested_modalities

def render_sensor_state(
    scene_state: SceneState,
    sensor_specs: list[IsaacSensorSpec],
    render_request: RenderRequest,
    *,
    repo_root: str | Path,
    out_dir: str | Path | None = None,
    variant: str = "auto",
) -> dict[str, MultimodalRenderResult]:
    root = Path(repo_root).resolve()
    scene_path = resolve_repo_path(root, scene_state.mitsuba_scene_ref)
    sensor_root = Path(out_dir).resolve() if out_dir is not None else _observation_layout_for_request(render_request, root).sensors_dir
    sensor_root.mkdir(parents=True, exist_ok=True)
    rendered: dict[str, MultimodalRenderResult] = {}
    for sensor_spec in sensor_specs:
        if sensor_spec.camera_to_world is None:
            raise ValueError(f"Sensor {sensor_spec.sensor_id} requires camera_to_world for rendering")
        modalities = list(sensor_spec.modalities or [])
        if not modalities:
            raise ValueError(f"Sensor {sensor_spec.sensor_id} has no modalities")
        sensor_dir = sensor_root / sensor_spec.sensor_id
        sensor_dir.mkdir(parents=True, exist_ok=True)
        settings = _sensor_render_settings_payload(render_request.render_settings, sensor_spec)
        config = render_config_from_payload(settings)
        metadata = None
        if sensor_spec.sensor_type == "ouster_lidar" and sensor_spec.metadata_ref:
            metadata = load_ouster_metadata(resolve_repo_path(root, sensor_spec.metadata_ref))
        fov_deg = float(sensor_spec.fov_deg if sensor_spec.fov_deg is not None else (360.0 if sensor_spec.sensor_type == "ouster_lidar" else 90.0))
        rendered[sensor_spec.sensor_id] = render_modalities(
            scene_path,
            np.asarray(sensor_spec.camera_to_world, dtype=np.float32).reshape(4, 4),
            fov_deg,
            modalities,
            out_dir=sensor_dir,
            config=config,
            scene_override=render_request.scene_override,
            assist_light=None,
            depth_approx=render_request.depth_approx if "sensor_depth_approx" in modalities else None,
            lidar_metadata=metadata,
            variant=variant,
        )
    return rendered


def _camera_config(base_config: RenderConfig, camera_spec: CameraSpec) -> RenderConfig:
    if camera_spec.resolution is None:
        return base_config
    width, height = int(camera_spec.resolution[0]), int(camera_spec.resolution[1])
    return replace(base_config, width=width, height=height)


def render_scene_state(
    scene_state: SceneState,
    camera_specs: list[CameraSpec],
    render_request: RenderRequest,
    *,
    repo_root: str | Path,
    out_dir: str | Path | None = None,
    variant: str = "auto",
) -> dict[str, MultimodalRenderResult]:
    validate_render_request(render_request)
    if scene_state != render_request.scene_state:
        raise ValueError("scene_state must match render_request.scene_state.")
    requested_camera_ids = [item.camera_id for item in render_request.camera_specs]
    provided_camera_ids = [item.camera_id for item in camera_specs]
    if requested_camera_ids != provided_camera_ids:
        raise ValueError("camera_specs must match render_request.camera_specs in order and content.")

    root = Path(repo_root).resolve()
    scene_path = resolve_repo_path(root, scene_state.mitsuba_scene_ref)
    if out_dir is None:
        layout = _observation_layout_for_request(render_request, root)
        camera_root = layout.cameras_dir
    else:
        camera_root = Path(out_dir).resolve()
        camera_root.mkdir(parents=True, exist_ok=True)

    rendered: dict[str, MultimodalRenderResult] = {}
    for camera_spec in camera_specs:
        camera_dir = camera_root / camera_spec.camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        camera_to_world = np.asarray(camera_spec.camera_to_world, dtype=np.float32).reshape(4, 4)
        camera_modalities = _camera_modalities(render_request, camera_spec)
        base_config = render_config_from_payload(
            _camera_render_settings_payload(render_request.render_settings, camera_spec, camera_modalities)
        )
        config = _camera_config(base_config, camera_spec)
        camera_assist_light = _camera_assist_light(render_request, camera_spec, camera_modalities)
        rendered[camera_spec.camera_id] = render_modalities(
            scene_path,
            camera_to_world,
            camera_spec.fov_deg,
            camera_modalities,
            out_dir=camera_dir,
            config=config,
            scene_override=render_request.scene_override,
            assist_light=camera_assist_light,
            depth_approx=render_request.depth_approx,
            variant=variant,
        )
    return rendered


def write_manifest(bundle_manifest: ObservationBundleManifest, *, repo_root: str | Path) -> Path:
    validate_observation_bundle_manifest(bundle_manifest)
    root = Path(repo_root).resolve()
    manifest_path = resolve_repo_path(root, bundle_manifest.bundle_root) / "manifest.json"
    return write_observation_bundle_manifest(manifest_path, bundle_manifest)


def render_timestep_bundle(
    render_request: RenderRequest,
    *,
    repo_root: str | Path,
    variant: str = "auto",
) -> ObservationBundleManifest:
    validate_render_request(render_request)
    root = Path(repo_root).resolve()
    layout = _observation_layout_for_request(render_request, root)

    camera_results = render_scene_state(
        render_request.scene_state,
        render_request.camera_specs,
        render_request,
        repo_root=root,
        out_dir=layout.cameras_dir,
        variant=variant,
    )
    sensor_results = render_sensor_state(
        render_request.scene_state,
        render_request.sensor_specs,
        render_request,
        repo_root=root,
        out_dir=layout.sensors_dir,
        variant=variant,
    )

    artifacts: list[RenderArtifactManifest] = []
    timing_log = {
        "request_id": render_request.request_id,
        "job_id": render_request.job_id,
        "frame_id": render_request.frame_id,
        "timestamp": render_request.timestamp,
        "cameras": {},
        "sensors": {},
    }
    for camera_spec in render_request.camera_specs:
        result = camera_results[camera_spec.camera_id]
        timing_log["cameras"][camera_spec.camera_id] = result.pass_records
        for modality in _camera_modalities(render_request, camera_spec):
            if modality not in result.results:
                continue
            artifacts.append(_artifact_manifest_from_result(root, camera_spec, modality, result.results[modality]))
    for sensor_spec in render_request.sensor_specs:
        result = sensor_results[sensor_spec.sensor_id]
        timing_log["sensors"][sensor_spec.sensor_id] = result.pass_records
        for modality in sensor_spec.modalities:
            if modality in result.results:
                artifacts.append(_sensor_artifact_manifest_from_result(root, sensor_spec, modality, result.results[modality]))

    timing_log_path = layout.logs_dir / "render_timing.json"
    manifest_start = time.perf_counter()
    timing_log_path.write_text(json.dumps(timing_log, indent=2), encoding="utf-8")

    artifacts, merged_modalities = _merge_existing_versioned_artifacts(layout, artifacts, list(render_request.modalities))
    bundle_manifest = ObservationBundleManifest(
        job_id=render_request.job_id,
        scene_id=render_request.scene_state.scene_id,
        frame_id=render_request.frame_id,
        timestamp=render_request.timestamp,
        scene_state=render_request.scene_state,
        robot_state=render_request.robot_state,
        requested_modalities=merged_modalities,
        camera_specs=list(render_request.camera_specs),
        sensor_specs=list(render_request.sensor_specs),
        artifacts=artifacts,
        bundle_root=to_repo_relative_posix(root, layout.frame_dir),
        status="complete",
        action_ref=render_request.action_ref,
        prev_observation_ref=render_request.prev_observation_ref,
        next_observation_ref=render_request.next_observation_ref,
        extras={
            **render_request.extras,
            "timing_log_ref": to_repo_relative_posix(root, timing_log_path),
            "scene_version": render_request.scene_state.scene_version,
            "scene_version_id": render_request.extras.get("scene_version_id") if isinstance(render_request.extras, Mapping) else None,
            "render_version_id": render_request.extras.get("render_version_id") if isinstance(render_request.extras, Mapping) else None,
            "run_id": render_request.extras.get("run_id") if isinstance(render_request.extras, Mapping) else None,
            "illumination_setup": render_request.scene_state.illumination_setup,
            "scene_override": asdict(render_request.scene_override) if render_request.scene_override is not None else None,
            "assist_light": asdict(render_request.assist_light) if render_request.assist_light is not None else None,
            "depth_approx": asdict(render_request.depth_approx) if render_request.depth_approx is not None else None,
            "render_profile_id": render_request.extras.get("render_profile_id") if isinstance(render_request.extras, Mapping) else None,
            "render_profile": render_request.extras.get("render_profile") if isinstance(render_request.extras, Mapping) else None,
        },
    )
    write_manifest(bundle_manifest, repo_root=root)
    manifest_s = time.perf_counter() - manifest_start
    timing_log["manifest_s"] = manifest_s
    timing_log["manifest_publish_s"] = manifest_s
    timing_log_path.write_text(json.dumps(timing_log, indent=2), encoding="utf-8")
    bundle_manifest.extras["manifest_s"] = manifest_s
    write_manifest(bundle_manifest, repo_root=root)
    return bundle_manifest


def _split_lighting_modalities(modalities: list[str]) -> dict[str, list[str]]:
    ambient = [item for item in modalities if item in AMBIENT_MODALITIES]
    active = [item for item in modalities if item in ACTIVE_MODALITIES]
    polar = [item for item in modalities if item in POLAR_MODALITIES]
    unknown = [item for item in modalities if item not in AMBIENT_MODALITIES | ACTIVE_MODALITIES | POLAR_MODALITIES]
    ambient.extend(unknown)
    return {
        "ambient": ambient,
        "active": active,
        "polar": polar,
    }


def render_timestep_bundle_split_lighting(
    render_request: RenderRequest,
    *,
    repo_root: str | Path,
    variant: str = "auto",
    progress_callback: Callable[[str, Mapping[str, Any] | None], None] | None = None,
) -> ObservationBundleManifest:
    validate_render_request(render_request)
    root = Path(repo_root).resolve()
    layout = _observation_layout_for_request(render_request, root)
    scene_path = resolve_repo_path(root, render_request.scene_state.mitsuba_scene_ref)

    artifacts: list[RenderArtifactManifest] = []
    timing_log = {
        "request_id": render_request.request_id,
        "job_id": render_request.job_id,
        "frame_id": render_request.frame_id,
        "timestamp": render_request.timestamp,
        "branch_policy": "ambient_active_split",
        "cameras": {},
    }

    for camera_spec in render_request.camera_specs:
        camera_dir = layout.cameras_dir / camera_spec.camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        camera_to_world = np.asarray(camera_spec.camera_to_world, dtype=np.float32).reshape(4, 4)
        camera_modalities = _camera_modalities(render_request, camera_spec)
        base_config = render_config_from_payload(
            _camera_render_settings_payload(render_request.render_settings, camera_spec, camera_modalities)
        )
        camera_config = _camera_config(base_config, camera_spec)
        camera_assist_light = _camera_assist_light(render_request, camera_spec, camera_modalities)
        # Rig-mounted active lights (RGB/NIR flash + polarizer). Positioned at
        # base_pose @ mount inside the renderer. Robot base pose comes from the
        # request; the helper normalises matrix storage.
        active_lights = list(render_request.active_lights or [])
        base_pose = render_request.robot_state.base_pose if render_request.robot_state else None
        branch_modalities = _split_lighting_modalities(camera_modalities)
        branch_results: dict[str, MultimodalRenderResult] = {}

        if branch_modalities["ambient"]:
            if progress_callback is not None:
                progress_callback("ambient", {"camera_id": camera_spec.camera_id, "modalities": branch_modalities["ambient"]})
            branch_results["ambient"] = render_modalities(
                scene_path,
                camera_to_world,
                camera_spec.fov_deg,
                branch_modalities["ambient"],
                out_dir=camera_dir,
                config=camera_config,
                scene_override=render_request.scene_override,
                assist_light=None,
                depth_approx=None,
                variant=variant,
                progress_callback=progress_callback,
            )

        if branch_modalities["active"]:
            if progress_callback is not None:
                progress_callback("active", {"camera_id": camera_spec.camera_id, "modalities": branch_modalities["active"]})
            branch_results["active"] = render_modalities(
                scene_path,
                camera_to_world,
                camera_spec.fov_deg,
                branch_modalities["active"],
                out_dir=camera_dir,
                config=camera_config,
                scene_override=render_request.scene_override,
                assist_light=camera_assist_light,
                active_lights=active_lights,
                base_pose=base_pose,
                depth_approx=render_request.depth_approx,
                variant=variant,
                progress_callback=progress_callback,
            )

        if branch_modalities["polar"]:
            if progress_callback is not None:
                progress_callback("polar", {"camera_id": camera_spec.camera_id, "modalities": branch_modalities["polar"]})
            polar_config = replace(camera_config, samples_per_pass=None)
            branch_results["polar"] = render_modalities(
                scene_path,
                camera_to_world,
                camera_spec.fov_deg,
                branch_modalities["polar"],
                out_dir=camera_dir,
                config=polar_config,
                scene_override=render_request.scene_override,
                assist_light=camera_assist_light,
                active_lights=active_lights,
                base_pose=base_pose,
                depth_approx=None,
                variant=variant,
                progress_callback=progress_callback,
            )

        timing_log["cameras"][camera_spec.camera_id] = {
            branch_name: result.pass_records
            for branch_name, result in branch_results.items()
        }
        for result in branch_results.values():
            for modality in camera_modalities:
                if modality not in result.results:
                    continue
                artifacts.append(_artifact_manifest_from_result(root, camera_spec, modality, result.results[modality]))

    sensor_results = render_sensor_state(
        render_request.scene_state,
        render_request.sensor_specs,
        render_request,
        repo_root=root,
        out_dir=layout.sensors_dir,
        variant=variant,
    )
    timing_log.setdefault("sensors", {})
    for sensor_spec in render_request.sensor_specs:
        result = sensor_results[sensor_spec.sensor_id]
        timing_log["sensors"][sensor_spec.sensor_id] = result.pass_records
        for modality in sensor_spec.modalities:
            if modality in result.results:
                artifacts.append(_sensor_artifact_manifest_from_result(root, sensor_spec, modality, result.results[modality]))

    timing_log_path = layout.logs_dir / "render_timing.json"
    if progress_callback is not None:
        progress_callback("writing_manifest", {"path": str(timing_log_path)})
    manifest_start = time.perf_counter()
    timing_log_path.write_text(json.dumps(timing_log, indent=2), encoding="utf-8")

    artifacts, merged_modalities = _merge_existing_versioned_artifacts(layout, artifacts, list(render_request.modalities))
    bundle_manifest = ObservationBundleManifest(
        job_id=render_request.job_id,
        scene_id=render_request.scene_state.scene_id,
        frame_id=render_request.frame_id,
        timestamp=render_request.timestamp,
        scene_state=render_request.scene_state,
        robot_state=render_request.robot_state,
        requested_modalities=merged_modalities,
        camera_specs=list(render_request.camera_specs),
        sensor_specs=list(render_request.sensor_specs),
        artifacts=artifacts,
        bundle_root=to_repo_relative_posix(root, layout.frame_dir),
        status="complete",
        action_ref=render_request.action_ref,
        prev_observation_ref=render_request.prev_observation_ref,
        next_observation_ref=render_request.next_observation_ref,
        extras={
            **render_request.extras,
            "timing_log_ref": to_repo_relative_posix(root, timing_log_path),
            "scene_version": render_request.scene_state.scene_version,
            "scene_version_id": render_request.extras.get("scene_version_id") if isinstance(render_request.extras, Mapping) else None,
            "render_version_id": render_request.extras.get("render_version_id") if isinstance(render_request.extras, Mapping) else None,
            "run_id": render_request.extras.get("run_id") if isinstance(render_request.extras, Mapping) else None,
            "illumination_setup": render_request.scene_state.illumination_setup,
            "scene_override": asdict(render_request.scene_override) if render_request.scene_override is not None else None,
            "assist_light": asdict(render_request.assist_light) if render_request.assist_light is not None else None,
            "depth_approx": asdict(render_request.depth_approx) if render_request.depth_approx is not None else None,
            "branch_policy": "ambient_active_split",
            "branch_modalities": branch_modalities,
        },
    )
    write_manifest(bundle_manifest, repo_root=root)
    manifest_s = time.perf_counter() - manifest_start
    timing_log["manifest_s"] = manifest_s
    timing_log_path.write_text(json.dumps(timing_log, indent=2), encoding="utf-8")
    bundle_manifest.extras["manifest_s"] = manifest_s
    write_manifest(bundle_manifest, repo_root=root)
    return bundle_manifest


def make_reflective_island_demo_request(
    scene_state: SceneState,
    *,
    request_id: str = "reflective-island-demo",
    calibration_ref: str | None = None,
    render_settings: Mapping[str, Any] | None = None,
    camera_spec: CameraSpec | None = None,
) -> RenderRequest:
    if camera_spec is None:
        camera_to_world = camera_to_world_from_lookat(
            origin=[1.55, 1.28, -4.75],
            target=[0.15, 0.45, -10.6],
            up=[0.0, 1.0, 0.0],
        ).reshape(-1).tolist()
        camera_spec = CameraSpec(
            camera_id="dining_north",
            name="Dining North",
            camera_to_world=camera_to_world,
            fov_deg=61.22851509283464,
            resolution=[768, 576],
            sensor_modality="multimodal",
            sensor_sync_group="dining_demo",
            calibration_ref=calibration_ref,
            source_camera_id="dining_north",
        )
    elif calibration_ref is not None and camera_spec.calibration_ref is None:
        camera_spec = replace(camera_spec, calibration_ref=calibration_ref)
    return RenderRequest(
        request_id=request_id,
        job_id=scene_state.job_id,
        frame_id=scene_state.frame_id,
        timestamp=scene_state.timestamp,
        scene_state=scene_state,
        camera_specs=[camera_spec],
        modalities=[
            "rgb",
            "sensor_depth_approx",
            "active_nir_intensity",
            "polar_rgb_preview",
            "s1_over_s0",
            "s2_over_s0",
            "s1",
            "s2",
            "dop",
            "aolp",
        ],
        robot_state=RobotState(),
        render_settings=dict(render_settings or {}),
        scene_override=SceneOverrideSpec(
            target_shape_filenames=list(REFLECTIVE_ISLAND_RGB_TARGETS),
            material_profile="mirror_black_enamel",
        ),
        assist_light=AssistLightSpec(
            mode="camera_aligned_rect",
            distance_m=0.14,
            size_world=[4.8, 3.6],
            spectrum_mode="nir_grayscale_proxy",
            polarized=True,
            polarizer_angle_deg=0.0,
            extras={"radiance": 40.0},
        ),
        depth_approx=DepthApproxSpec(
            mode="planar_reflective_proxy",
            target_shape_filenames=list(REFLECTIVE_ISLAND_DEPTH_TARGETS),
            blur_sigma_px=0.0,
            blend=1.0,
            extras={"use_projected_bbox": True},
        ),
        extras={"demo_name": "reflective_island_active_nir"},
    )
