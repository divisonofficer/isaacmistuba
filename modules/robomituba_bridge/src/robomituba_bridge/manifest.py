from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import PurePosixPath
import secrets

from .paths import JobLayout, to_repo_relative_posix
from .types import (
    ActiveLightSpec,
    AssistLightSpec,
    CameraSpec,
    DepthApproxSpec,
    IsaacSensorSpec,
    JobManifest,
    JobPaths,
    ObservationBundleManifest,
    RenderArtifactManifest,
    RenderJobAccepted,
    RenderJobStatus,
    RenderRequest,
    RobotState,
    SceneOverrideSpec,
    SceneSnapshot,
    SceneState,
)


def make_job_id(prefix: str = "job") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{secrets.token_hex(4)}"


def create_job_manifest(repo_root, layout: JobLayout, snapshot: SceneSnapshot, *, created_at: str | None = None) -> JobManifest:
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    paths = JobPaths(
        job_dir=to_repo_relative_posix(repo_root, layout.job_dir),
        manifest=to_repo_relative_posix(repo_root, layout.manifest),
        snapshot_dir=to_repo_relative_posix(repo_root, layout.snapshot_dir),
        scene_snapshot=to_repo_relative_posix(repo_root, layout.scene_snapshot),
        materials=to_repo_relative_posix(repo_root, layout.materials),
        cameras=to_repo_relative_posix(repo_root, layout.cameras),
        lights=to_repo_relative_posix(repo_root, layout.lights),
        usd_dir=to_repo_relative_posix(repo_root, layout.usd_dir),
        usd_stage=to_repo_relative_posix(repo_root, layout.usd_stage),
        renders_dir=to_repo_relative_posix(repo_root, layout.renders_dir),
        logs_dir=to_repo_relative_posix(repo_root, layout.logs_dir),
        snapshot_archive=to_repo_relative_posix(repo_root, layout.snapshot_dir / "snapshot_package.zip"),
    )
    return JobManifest(
        job_id=layout.job_dir.name,
        scene_id=snapshot.scene_id,
        frame_id=snapshot.frame.frame_id,
        created_at=timestamp,
        paths=paths,
    )


def validate_repo_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"Expected repo-relative path, got absolute path: {value}")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"Expected repo-relative path without parent traversal: {value}")


def validate_job_manifest(manifest: JobManifest) -> None:
    if not manifest.job_id:
        raise ValueError("job_id must not be empty.")
    if not manifest.scene_id:
        raise ValueError("scene_id must not be empty.")
    if not manifest.frame_id:
        raise ValueError("frame_id must not be empty.")

    for _, value in asdict(manifest.paths).items():
        if value is not None:
            validate_repo_relative_path(value)


def validate_scene_snapshot(snapshot: SceneSnapshot) -> None:
    if not snapshot.scene_id:
        raise ValueError("scene_id must not be empty.")
    if not snapshot.frame.frame_id:
        raise ValueError("frame.frame_id must not be empty.")
    if snapshot.usd_stage_path:
        validate_repo_relative_path(snapshot.usd_stage_path)
    if snapshot.snapshot_archive:
        validate_repo_relative_path(snapshot.snapshot_archive)

    for mesh in snapshot.meshes:
        if mesh.geometry_path:
            validate_repo_relative_path(mesh.geometry_path)
        if mesh.geometry_sidecar:
            validate_repo_relative_path(mesh.geometry_sidecar)
    for material in snapshot.materials:
        for texture_path in material.textures.values():
            if isinstance(texture_path, str):
                validate_repo_relative_path(texture_path)
    for light in snapshot.lights:
        if light.texture_path:
            validate_repo_relative_path(light.texture_path)
    for reference in snapshot.reference_records:
        if reference.asset_path and not reference.asset_path.startswith(("/", "omniverse://", "http://", "https://")):
            validate_repo_relative_path(reference.asset_path)
        if reference.package_path:
            validate_repo_relative_path(reference.package_path)
    if snapshot.robot_state is not None:
        validate_robot_state(snapshot.robot_state)


def validate_scene_state(scene_state: SceneState) -> None:
    if not scene_state.job_id:
        raise ValueError("scene_state.job_id must not be empty.")
    if not scene_state.scene_id:
        raise ValueError("scene_state.scene_id must not be empty.")
    if not scene_state.frame_id:
        raise ValueError("scene_state.frame_id must not be empty.")
    if not scene_state.timestamp:
        raise ValueError("scene_state.timestamp must not be empty.")
    if not scene_state.scene_snapshot_ref:
        raise ValueError("scene_state.scene_snapshot_ref must not be empty.")
    if not scene_state.mitsuba_scene_ref:
        raise ValueError("scene_state.mitsuba_scene_ref must not be empty.")
    validate_repo_relative_path(scene_state.scene_snapshot_ref)
    validate_repo_relative_path(scene_state.mitsuba_scene_ref)


def validate_camera_spec(camera_spec: CameraSpec) -> None:
    if not camera_spec.camera_id:
        raise ValueError("camera_spec.camera_id must not be empty.")
    if not camera_spec.name:
        raise ValueError("camera_spec.name must not be empty.")
    if len(camera_spec.camera_to_world) != 16:
        raise ValueError("camera_spec.camera_to_world must contain 16 values.")
    if camera_spec.resolution is not None:
        if len(camera_spec.resolution) != 2:
            raise ValueError("camera_spec.resolution must contain width and height.")
        if any(int(value) <= 0 for value in camera_spec.resolution):
            raise ValueError("camera_spec.resolution values must be positive.")
    if not camera_spec.sensor_modality:
        raise ValueError("camera_spec.sensor_modality must not be empty.")
    if not camera_spec.sensor_sync_group:
        raise ValueError("camera_spec.sensor_sync_group must not be empty.")
    if camera_spec.calibration_ref:
        validate_repo_relative_path(camera_spec.calibration_ref)


def validate_sensor_spec(sensor_spec: IsaacSensorSpec) -> None:
    if not sensor_spec.sensor_id:
        raise ValueError("sensor_spec.sensor_id must not be empty.")
    if not sensor_spec.name:
        raise ValueError("sensor_spec.name must not be empty.")
    allowed_types = {"rgb_camera", "polar_camera", "depth_sensor", "ouster_lidar"}
    if sensor_spec.sensor_type not in allowed_types:
        raise ValueError(f"Unsupported sensor_spec.sensor_type: {sensor_spec.sensor_type}")
    if not sensor_spec.modalities:
        raise ValueError("sensor_spec.modalities must not be empty.")
    if sensor_spec.camera_to_world is not None and len(sensor_spec.camera_to_world) != 16:
        raise ValueError("sensor_spec.camera_to_world must contain 16 values when provided.")
    if sensor_spec.resolution is not None:
        if len(sensor_spec.resolution) != 2 or any(int(value) <= 0 for value in sensor_spec.resolution):
            raise ValueError("sensor_spec.resolution must contain two positive values.")
    if not sensor_spec.sensor_sync_group:
        raise ValueError("sensor_spec.sensor_sync_group must not be empty.")
    for field_name in ("calibration_ref", "metadata_ref"):
        value = getattr(sensor_spec, field_name)
        if value:
            validate_repo_relative_path(value)


def validate_scene_override_spec(scene_override: SceneOverrideSpec) -> None:
    if (
        not scene_override.target_shape_filenames
        and not scene_override.prim_to_shape_ids
        and not scene_override.bsdf_overrides
        and not scene_override.transform_overrides
    ):
        raise ValueError(
            "scene_override must define at least one target via target_shape_filenames, prim_to_shape_ids, "
            "bsdf_overrides, or transform_overrides."
        )
    if scene_override.target_shape_filenames and not scene_override.material_profile:
        raise ValueError("scene_override.material_profile must not be empty when target_shape_filenames are provided.")


def validate_assist_light_spec(assist_light: AssistLightSpec) -> None:
    if assist_light.mode != "camera_aligned_rect":
        raise ValueError(f"Unsupported assist_light.mode: {assist_light.mode}")
    if assist_light.distance_m <= 0:
        raise ValueError("assist_light.distance_m must be positive.")
    if len(assist_light.size_world) != 2:
        raise ValueError("assist_light.size_world must contain width and height.")
    if any(float(value) <= 0 for value in assist_light.size_world):
        raise ValueError("assist_light.size_world values must be positive.")
    if not assist_light.spectrum_mode:
        raise ValueError("assist_light.spectrum_mode must not be empty.")


def validate_active_light_spec(active_light: "ActiveLightSpec") -> None:
    if not active_light.light_id:
        raise ValueError("active_light.light_id must not be empty.")
    if active_light.emitter_type not in ("spot", "point", "area"):
        raise ValueError(f"Unsupported active_light.emitter_type: {active_light.emitter_type}")
    if active_light.spectrum_kind not in ("rgb", "nir"):
        raise ValueError(f"Unsupported active_light.spectrum_kind: {active_light.spectrum_kind}")
    if active_light.emitter_type == "area" and active_light.area_size_m <= 0:
        raise ValueError("active_light.area_size_m must be positive for area emitter.")
    mount = active_light.mount or {}
    xyz = mount.get("xyz_m", [])
    rpy = mount.get("rpy_deg", [])
    if len(xyz) != 3 or len(rpy) != 3:
        raise ValueError("active_light.mount must have xyz_m[3] and rpy_deg[3].")
    if active_light.radiance < 0:
        raise ValueError("active_light.radiance must be non-negative.")
    if active_light.spectrum_kind == "nir" and active_light.wavelength_nm <= 0:
        raise ValueError("active_light.wavelength_nm must be positive for nir.")


def validate_depth_approx_spec(depth_approx: DepthApproxSpec) -> None:
    if depth_approx.mode != "planar_reflective_proxy":
        raise ValueError(f"Unsupported depth_approx.mode: {depth_approx.mode}")
    if not depth_approx.target_shape_filenames:
        raise ValueError("depth_approx.target_shape_filenames must not be empty.")
    if depth_approx.blur_sigma_px < 0:
        raise ValueError("depth_approx.blur_sigma_px must be non-negative.")
    if not 0.0 <= depth_approx.blend <= 1.0:
        raise ValueError("depth_approx.blend must be in [0, 1].")


def validate_robot_state(robot_state: RobotState) -> None:
    if robot_state.base_pose is not None and len(robot_state.base_pose) != 16:
        raise ValueError("robot_state.base_pose must contain 16 values when provided.")
    if robot_state.ee_pose is not None and len(robot_state.ee_pose) != 16:
        raise ValueError("robot_state.ee_pose must contain 16 values when provided.")
    if robot_state.joint_positions and robot_state.joint_names and len(robot_state.joint_names) != len(robot_state.joint_positions):
        raise ValueError("robot_state.joint_names and joint_positions must have the same length.")


def validate_render_request(render_request: RenderRequest) -> None:
    if not render_request.request_id:
        raise ValueError("render_request.request_id must not be empty.")
    if not render_request.job_id:
        raise ValueError("render_request.job_id must not be empty.")
    if not render_request.frame_id:
        raise ValueError("render_request.frame_id must not be empty.")
    if not render_request.timestamp:
        raise ValueError("render_request.timestamp must not be empty.")
    if not render_request.modalities:
        raise ValueError("render_request.modalities must not be empty.")
    if not render_request.camera_specs and not render_request.sensor_specs:
        raise ValueError("render_request must contain camera_specs or sensor_specs.")
    validate_scene_state(render_request.scene_state)
    validate_robot_state(render_request.robot_state)
    if render_request.job_id != render_request.scene_state.job_id:
        raise ValueError("render_request.job_id must match scene_state.job_id.")
    if render_request.frame_id != render_request.scene_state.frame_id:
        raise ValueError("render_request.frame_id must match scene_state.frame_id.")
    if render_request.timestamp != render_request.scene_state.timestamp:
        raise ValueError("render_request.timestamp must match scene_state.timestamp.")
    seen: set[str] = set()
    for camera_spec in render_request.camera_specs:
        validate_camera_spec(camera_spec)
        if camera_spec.camera_id in seen:
            raise ValueError(f"Duplicate camera_id in render_request.camera_specs: {camera_spec.camera_id}")
        seen.add(camera_spec.camera_id)
    for sensor_spec in render_request.sensor_specs:
        validate_sensor_spec(sensor_spec)
        if sensor_spec.sensor_id in seen:
            raise ValueError(f"Duplicate sensor_id in render_request: {sensor_spec.sensor_id}")
        seen.add(sensor_spec.sensor_id)
    if render_request.scene_override is not None:
        validate_scene_override_spec(render_request.scene_override)
    if render_request.assist_light is not None:
        validate_assist_light_spec(render_request.assist_light)
    active_light_ids: set[str] = set()
    for active_light in render_request.active_lights:
        validate_active_light_spec(active_light)
        if active_light.light_id in active_light_ids:
            raise ValueError(f"Duplicate active_light.light_id: {active_light.light_id}")
        active_light_ids.add(active_light.light_id)
    if render_request.depth_approx is not None:
        validate_depth_approx_spec(render_request.depth_approx)
    if "sensor_depth_approx" in render_request.modalities and render_request.depth_approx is None:
        raise ValueError("sensor_depth_approx requires render_request.depth_approx.")
    # Active NIR needs an illumination source: either the legacy camera-aligned
    # assist_light or at least one rig-mounted active light that covers the nir pass.
    _has_nir_active_light = any(
        light.enabled and "nir" in (light.modalities or []) for light in render_request.active_lights
    )
    if any(item in render_request.modalities for item in ("active_nir_intensity", "nir_intensity")) \
            and render_request.assist_light is None and not _has_nir_active_light:
        raise ValueError("active NIR modalities require render_request.assist_light or an nir active_light.")
    try:
        json.dumps(render_request.render_settings)
    except TypeError as exc:
        raise ValueError("render_request.render_settings must be JSON-serializable.") from exc


def validate_render_job_accepted(accepted: RenderJobAccepted) -> None:
    if not accepted.job_id:
        raise ValueError("accepted.job_id must not be empty.")
    if not accepted.frame_id:
        raise ValueError("accepted.frame_id must not be empty.")
    if accepted.status != "queued":
        raise ValueError("accepted.status must be 'queued'.")
    if not accepted.submitted_at:
        raise ValueError("accepted.submitted_at must not be empty.")
    if not accepted.status_url:
        raise ValueError("accepted.status_url must not be empty.")
    if not accepted.manifest_url:
        raise ValueError("accepted.manifest_url must not be empty.")
    if accepted.queue_position < 0:
        raise ValueError("accepted.queue_position must be non-negative.")


def validate_render_job_status(status: RenderJobStatus) -> None:
    if not status.job_id:
        raise ValueError("status.job_id must not be empty.")
    if not status.frame_id:
        raise ValueError("status.frame_id must not be empty.")
    if status.status not in {"queued", "running", "succeeded", "failed", "cancelled"}:
        raise ValueError(f"Unsupported status: {status.status}")
    if not status.submitted_at:
        raise ValueError("status.submitted_at must not be empty.")
    if not status.progress_stage:
        raise ValueError("status.progress_stage must not be empty.")
    if status.manifest_path:
        validate_repo_relative_path(status.manifest_path)


def validate_render_artifact_manifest(artifact: RenderArtifactManifest) -> None:
    if not artifact.camera_id:
        raise ValueError("artifact.camera_id must not be empty.")
    if not artifact.modality:
        raise ValueError("artifact.modality must not be empty.")
    if not artifact.definition:
        raise ValueError("artifact.definition must not be empty.")
    for value in artifact.artifact_paths.values():
        if isinstance(value, str):
            validate_repo_relative_path(value)
    if artifact.scene_ref:
        validate_repo_relative_path(artifact.scene_ref)


def validate_observation_bundle_manifest(bundle: ObservationBundleManifest) -> None:
    if not bundle.job_id:
        raise ValueError("bundle.job_id must not be empty.")
    if not bundle.scene_id:
        raise ValueError("bundle.scene_id must not be empty.")
    if not bundle.frame_id:
        raise ValueError("bundle.frame_id must not be empty.")
    if not bundle.timestamp:
        raise ValueError("bundle.timestamp must not be empty.")
    if not bundle.bundle_root:
        raise ValueError("bundle.bundle_root must not be empty.")
    if not bundle.requested_modalities:
        raise ValueError("bundle.requested_modalities must not be empty.")
    validate_repo_relative_path(bundle.bundle_root)
    validate_scene_state(bundle.scene_state)
    validate_robot_state(bundle.robot_state)
    if bundle.job_id != bundle.scene_state.job_id:
        raise ValueError("bundle.job_id must match scene_state.job_id.")
    if bundle.frame_id != bundle.scene_state.frame_id:
        raise ValueError("bundle.frame_id must match scene_state.frame_id.")
    if bundle.timestamp != bundle.scene_state.timestamp:
        raise ValueError("bundle.timestamp must match scene_state.timestamp.")
    for camera_spec in bundle.camera_specs:
        validate_camera_spec(camera_spec)
    for sensor_spec in bundle.sensor_specs:
        validate_sensor_spec(sensor_spec)
    for artifact in bundle.artifacts:
        validate_render_artifact_manifest(artifact)
