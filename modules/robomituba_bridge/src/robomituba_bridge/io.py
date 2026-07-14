from __future__ import annotations

from dataclasses import asdict, fields
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable
import zipfile

from .manifest import validate_job_manifest, validate_scene_snapshot
from .manifest import (
    validate_observation_bundle_manifest,
    validate_render_job_accepted,
    validate_render_job_status,
    validate_render_request,
)
from .paths import JobLayout, repo_root_from, resolve_repo_path
from .types import (
    ActiveLightSpec,
    AssistLightSpec,
    BsdfOverride,
    CameraRecord,
    CameraSpec,
    DepthApproxSpec,
    FrameRecord,
    IsaacCaptureRequest,
    IsaacObjectState,
    IsaacMaterialPatch,
    IsaacSensorSpec,
    IsaacSessionOpen,
    IsaacStatePatch,
    IsaacStateSnapshot,
    JobManifest,
    JobPaths,
    LightRecord,
    MaterialRecord,
    MeshRecord,
    ObservationBundleManifest,
    RenderArtifactManifest,
    RenderJobAccepted,
    RenderJobStatus,
    RenderRequest,
    RobotState,
    SceneOverrideSpec,
    SceneSnapshot,
    SceneState,
    InstancerMappingRecord,
    PoseRecord,
    ReferenceRecord,
    SCENE_SNAPSHOT_SCHEMA_VERSION,
)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dataclass_kwargs(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in payload.items() if key in allowed}


def _mesh_from_dict(payload: Dict[str, Any]) -> MeshRecord:
    return MeshRecord(**_dataclass_kwargs(MeshRecord, payload))


def _material_from_dict(payload: Dict[str, Any]) -> MaterialRecord:
    return MaterialRecord(**_dataclass_kwargs(MaterialRecord, payload))


def _camera_from_dict(payload: Dict[str, Any]) -> CameraRecord:
    return CameraRecord(**_dataclass_kwargs(CameraRecord, payload))


def _light_from_dict(payload: Dict[str, Any]) -> LightRecord:
    return LightRecord(**_dataclass_kwargs(LightRecord, payload))


def _frame_from_dict(payload: Dict[str, Any]) -> FrameRecord:
    return FrameRecord(**_dataclass_kwargs(FrameRecord, payload))


def _pose_from_dict(payload: Dict[str, Any]) -> PoseRecord:
    return PoseRecord(**_dataclass_kwargs(PoseRecord, payload))


def _instancer_mapping_from_dict(payload: Dict[str, Any]) -> InstancerMappingRecord:
    return InstancerMappingRecord(**_dataclass_kwargs(InstancerMappingRecord, payload))


def _reference_from_dict(payload: Dict[str, Any]) -> ReferenceRecord:
    return ReferenceRecord(**_dataclass_kwargs(ReferenceRecord, payload))


def _paths_from_dict(payload: Dict[str, Any]) -> JobPaths:
    normalized = dict(payload)
    if "snapshot_archive" not in normalized and normalized.get("snapshot_dir"):
        normalized["snapshot_archive"] = f"{str(normalized['snapshot_dir']).rstrip('/')}/snapshot_package.zip"
    return JobPaths(**_dataclass_kwargs(JobPaths, normalized))


def _scene_state_from_dict(payload: Dict[str, Any]) -> SceneState:
    return SceneState(**payload)


def _camera_spec_from_dict(payload: Dict[str, Any]) -> CameraSpec:
    return CameraSpec(**payload)


def _scene_override_from_dict(payload: Dict[str, Any]) -> SceneOverrideSpec:
    return SceneOverrideSpec(**payload)


def _assist_light_from_dict(payload: Dict[str, Any]) -> AssistLightSpec:
    return AssistLightSpec(**payload)


def _active_light_from_dict(payload: Dict[str, Any]) -> ActiveLightSpec:
    # Defensive: ignore unknown keys so newer/older payloads round-trip safely.
    allowed = {f.name for f in fields(ActiveLightSpec)}
    return ActiveLightSpec(**{k: v for k, v in payload.items() if k in allowed})


def _depth_approx_from_dict(payload: Dict[str, Any]) -> DepthApproxSpec:
    return DepthApproxSpec(**payload)


def _robot_state_from_dict(payload: Dict[str, Any]) -> RobotState:
    return RobotState(**payload)


def _render_artifact_from_dict(payload: Dict[str, Any]) -> RenderArtifactManifest:
    return RenderArtifactManifest(**payload)


def _render_job_accepted_from_dict(payload: Dict[str, Any]) -> RenderJobAccepted:
    return RenderJobAccepted(**payload)


def _render_job_status_from_dict(payload: Dict[str, Any]) -> RenderJobStatus:
    return RenderJobStatus(**_dataclass_kwargs(RenderJobStatus, payload))


def scene_snapshot_to_payload(snapshot: SceneSnapshot) -> Dict[str, Any]:
    payload = {
        "scene_id": snapshot.scene_id,
        "schema_version": snapshot.schema_version,
        "frame": asdict(snapshot.frame),
        "usd_stage_path": snapshot.usd_stage_path,
        "snapshot_archive": snapshot.snapshot_archive,
        "package_metadata": snapshot.package_metadata,
        "meshes": [asdict(mesh) for mesh in snapshot.meshes],
        "pose_records": [asdict(pose) for pose in snapshot.pose_records],
        "instancer_mappings": [asdict(item) for item in snapshot.instancer_mappings],
        "reference_records": [asdict(item) for item in snapshot.reference_records],
        "extras": snapshot.extras,
    }
    if snapshot.robot_state is not None:
        payload["robot_state"] = robot_state_to_payload(snapshot.robot_state)
    return payload


def scene_snapshot_from_payload(
    payload: Dict[str, Any],
    *,
    materials: Iterable[Dict[str, Any]],
    cameras: Iterable[Dict[str, Any]],
    lights: Iterable[Dict[str, Any]],
) -> SceneSnapshot:
    return SceneSnapshot(
        scene_id=payload["scene_id"],
        frame=_frame_from_dict(payload["frame"]),
        schema_version=str(payload.get("schema_version") or SCENE_SNAPSHOT_SCHEMA_VERSION),
        usd_stage_path=payload.get("usd_stage_path"),
        snapshot_archive=payload.get("snapshot_archive"),
        package_metadata=payload.get("package_metadata", {}),
        meshes=[_mesh_from_dict(item) for item in payload.get("meshes", [])],
        materials=[_material_from_dict(item) for item in materials],
        cameras=[_camera_from_dict(item) for item in cameras],
        lights=[_light_from_dict(item) for item in lights],
        pose_records=[_pose_from_dict(item) for item in payload.get("pose_records", [])],
        instancer_mappings=[
            _instancer_mapping_from_dict(item) for item in payload.get("instancer_mappings", [])
        ],
        reference_records=[_reference_from_dict(item) for item in payload.get("reference_records", [])],
        robot_state=robot_state_from_payload(payload["robot_state"]) if payload.get("robot_state") else None,
        extras=payload.get("extras", {}),
    )


def manifest_to_payload(manifest: JobManifest) -> Dict[str, Any]:
    return {
        "job_id": manifest.job_id,
        "scene_id": manifest.scene_id,
        "frame_id": manifest.frame_id,
        "created_at": manifest.created_at,
        "paths": asdict(manifest.paths),
        "extras": manifest.extras,
    }


def manifest_from_payload(payload: Dict[str, Any]) -> JobManifest:
    manifest = JobManifest(
        job_id=payload["job_id"],
        scene_id=payload["scene_id"],
        frame_id=payload["frame_id"],
        created_at=payload["created_at"],
        paths=_paths_from_dict(payload["paths"]),
        extras=payload.get("extras", {}),
    )
    validate_job_manifest(manifest)
    return manifest


def scene_state_to_payload(scene_state: SceneState) -> Dict[str, Any]:
    return asdict(scene_state)


def scene_state_from_payload(payload: Dict[str, Any]) -> SceneState:
    return _scene_state_from_dict(payload)


def camera_spec_to_payload(camera_spec: CameraSpec) -> Dict[str, Any]:
    return asdict(camera_spec)


def camera_spec_from_payload(payload: Dict[str, Any]) -> CameraSpec:
    return _camera_spec_from_dict(payload)


def scene_override_spec_to_payload(scene_override: SceneOverrideSpec) -> Dict[str, Any]:
    return asdict(scene_override)


def scene_override_spec_from_payload(payload: Dict[str, Any]) -> SceneOverrideSpec:
    return _scene_override_from_dict(payload)


def assist_light_spec_to_payload(assist_light: AssistLightSpec) -> Dict[str, Any]:
    return asdict(assist_light)


def assist_light_spec_from_payload(payload: Dict[str, Any]) -> AssistLightSpec:
    return _assist_light_from_dict(payload)


def active_light_spec_to_payload(active_light: ActiveLightSpec) -> Dict[str, Any]:
    return asdict(active_light)


def active_light_spec_from_payload(payload: Dict[str, Any]) -> ActiveLightSpec:
    return _active_light_from_dict(payload)


def depth_approx_spec_to_payload(depth_approx: DepthApproxSpec) -> Dict[str, Any]:
    return asdict(depth_approx)


def depth_approx_spec_from_payload(payload: Dict[str, Any]) -> DepthApproxSpec:
    return _depth_approx_from_dict(payload)


def robot_state_to_payload(robot_state: RobotState) -> Dict[str, Any]:
    return asdict(robot_state)


def robot_state_from_payload(payload: Dict[str, Any]) -> RobotState:
    return _robot_state_from_dict(payload)


def render_request_to_payload(render_request: RenderRequest) -> Dict[str, Any]:
    validate_render_request(render_request)
    return {
        "request_id": render_request.request_id,
        "job_id": render_request.job_id,
        "frame_id": render_request.frame_id,
        "timestamp": render_request.timestamp,
        "scene_state": scene_state_to_payload(render_request.scene_state),
        "camera_specs": [camera_spec_to_payload(item) for item in render_request.camera_specs],
        "sensor_specs": [isaac_sensor_spec_to_payload(item) for item in render_request.sensor_specs],
        "modalities": list(render_request.modalities),
        "robot_state": robot_state_to_payload(render_request.robot_state),
        "render_settings": render_request.render_settings,
        "scene_override": scene_override_spec_to_payload(render_request.scene_override) if render_request.scene_override else None,
        "assist_light": assist_light_spec_to_payload(render_request.assist_light) if render_request.assist_light else None,
        "active_lights": [active_light_spec_to_payload(item) for item in render_request.active_lights],
        "depth_approx": depth_approx_spec_to_payload(render_request.depth_approx) if render_request.depth_approx else None,
        "action_ref": render_request.action_ref,
        "prev_observation_ref": render_request.prev_observation_ref,
        "next_observation_ref": render_request.next_observation_ref,
        "extras": render_request.extras,
    }


def render_request_from_payload(payload: Dict[str, Any]) -> RenderRequest:
    render_request = RenderRequest(
        request_id=payload["request_id"],
        job_id=payload["job_id"],
        frame_id=payload["frame_id"],
        timestamp=payload["timestamp"],
        scene_state=scene_state_from_payload(payload["scene_state"]),
        camera_specs=[camera_spec_from_payload(item) for item in payload.get("camera_specs", [])],
        sensor_specs=[isaac_sensor_spec_from_payload(item) for item in payload.get("sensor_specs", [])],
        modalities=list(payload.get("modalities", [])),
        robot_state=robot_state_from_payload(payload.get("robot_state", {})),
        render_settings=payload.get("render_settings", {}),
        scene_override=scene_override_spec_from_payload(payload["scene_override"]) if payload.get("scene_override") else None,
        assist_light=assist_light_spec_from_payload(payload["assist_light"]) if payload.get("assist_light") else None,
        active_lights=[active_light_spec_from_payload(item) for item in payload.get("active_lights", [])],
        depth_approx=depth_approx_spec_from_payload(payload["depth_approx"]) if payload.get("depth_approx") else None,
        action_ref=payload.get("action_ref"),
        prev_observation_ref=payload.get("prev_observation_ref"),
        next_observation_ref=payload.get("next_observation_ref"),
        extras=payload.get("extras", {}),
    )
    validate_render_request(render_request)
    return render_request


def render_job_accepted_to_payload(accepted: RenderJobAccepted) -> Dict[str, Any]:
    validate_render_job_accepted(accepted)
    return asdict(accepted)


def render_job_accepted_from_payload(payload: Dict[str, Any]) -> RenderJobAccepted:
    accepted = _render_job_accepted_from_dict(payload)
    validate_render_job_accepted(accepted)
    return accepted


def render_job_status_to_payload(status: RenderJobStatus) -> Dict[str, Any]:
    validate_render_job_status(status)
    return asdict(status)


def render_job_status_from_payload(payload: Dict[str, Any]) -> RenderJobStatus:
    status = _render_job_status_from_dict(payload)
    validate_render_job_status(status)
    return status


def render_artifact_manifest_to_payload(artifact: RenderArtifactManifest) -> Dict[str, Any]:
    return asdict(artifact)


def render_artifact_manifest_from_payload(payload: Dict[str, Any]) -> RenderArtifactManifest:
    return _render_artifact_from_dict(payload)


def observation_bundle_manifest_to_payload(bundle: ObservationBundleManifest) -> Dict[str, Any]:
    validate_observation_bundle_manifest(bundle)
    return {
        "job_id": bundle.job_id,
        "scene_id": bundle.scene_id,
        "frame_id": bundle.frame_id,
        "timestamp": bundle.timestamp,
        "scene_state": scene_state_to_payload(bundle.scene_state),
        "robot_state": robot_state_to_payload(bundle.robot_state),
        "requested_modalities": list(bundle.requested_modalities),
        "camera_specs": [camera_spec_to_payload(item) for item in bundle.camera_specs],
        "sensor_specs": [isaac_sensor_spec_to_payload(item) for item in bundle.sensor_specs],
        "artifacts": [render_artifact_manifest_to_payload(item) for item in bundle.artifacts],
        "bundle_root": bundle.bundle_root,
        "status": bundle.status,
        "action_ref": bundle.action_ref,
        "prev_observation_ref": bundle.prev_observation_ref,
        "next_observation_ref": bundle.next_observation_ref,
        "extras": bundle.extras,
    }


def observation_bundle_manifest_from_payload(payload: Dict[str, Any]) -> ObservationBundleManifest:
    bundle = ObservationBundleManifest(
        job_id=payload["job_id"],
        scene_id=payload["scene_id"],
        frame_id=payload["frame_id"],
        timestamp=payload["timestamp"],
        scene_state=scene_state_from_payload(payload["scene_state"]),
        robot_state=robot_state_from_payload(payload.get("robot_state", {})),
        requested_modalities=list(payload.get("requested_modalities", [])),
        camera_specs=[camera_spec_from_payload(item) for item in payload.get("camera_specs", [])],
        sensor_specs=[isaac_sensor_spec_from_payload(item) for item in payload.get("sensor_specs", [])],
        artifacts=[render_artifact_manifest_from_payload(item) for item in payload.get("artifacts", [])],
        bundle_root=payload["bundle_root"],
        status=payload.get("status", "complete"),
        action_ref=payload.get("action_ref"),
        prev_observation_ref=payload.get("prev_observation_ref"),
        next_observation_ref=payload.get("next_observation_ref"),
        extras=payload.get("extras", {}),
    )
    validate_observation_bundle_manifest(bundle)
    return bundle


def write_job_bundle(layout: JobLayout, manifest: JobManifest, snapshot: SceneSnapshot) -> None:
    validate_job_manifest(manifest)
    validate_scene_snapshot(snapshot)

    _write_json(layout.manifest, manifest_to_payload(manifest))
    _write_json(layout.scene_snapshot, scene_snapshot_to_payload(snapshot))
    _write_json(layout.materials, {"materials": [asdict(item) for item in snapshot.materials]})
    _write_json(layout.cameras, {"cameras": [asdict(item) for item in snapshot.cameras]})
    _write_json(layout.lights, {"lights": [asdict(item) for item in snapshot.lights]})


def read_job_manifest(manifest_path: str | Path, *, repo_root: str | Path | None = None) -> JobManifest:
    manifest_file = Path(manifest_path)
    root = Path(repo_root) if repo_root else repo_root_from(manifest_file)
    payload = _read_json(resolve_repo_path(root, manifest_file.as_posix()) if not manifest_file.is_absolute() else manifest_file)
    return manifest_from_payload(payload)


def load_job_bundle(manifest_path: str | Path, *, repo_root: str | Path | None = None) -> tuple[JobManifest, SceneSnapshot]:
    manifest_file = Path(manifest_path)
    root = Path(repo_root) if repo_root else repo_root_from(manifest_file)
    resolved_manifest = resolve_repo_path(root, manifest_file.as_posix()) if not manifest_file.is_absolute() else manifest_file
    manifest = manifest_from_payload(_read_json(resolved_manifest))

    scene_payload = _read_json(resolve_repo_path(root, manifest.paths.scene_snapshot))
    materials_payload = _read_json(resolve_repo_path(root, manifest.paths.materials))
    cameras_payload = _read_json(resolve_repo_path(root, manifest.paths.cameras))
    lights_payload = _read_json(resolve_repo_path(root, manifest.paths.lights))

    snapshot = scene_snapshot_from_payload(
        scene_payload,
        materials=materials_payload.get("materials", []),
        cameras=cameras_payload.get("cameras", []),
        lights=lights_payload.get("lights", []),
    )
    validate_scene_snapshot(snapshot)
    return manifest, snapshot


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_refs_from_snapshot(snapshot: SceneSnapshot) -> dict[str, str]:
    refs: dict[str, str] = {}
    for mesh in snapshot.meshes:
        for value in (mesh.geometry_path, mesh.geometry_sidecar):
            if value:
                refs[value] = value
    for material in snapshot.materials:
        for value in material.textures.values():
            if isinstance(value, str):
                refs[value] = value
    for light in snapshot.lights:
        if light.texture_path:
            refs[light.texture_path] = light.texture_path
    for record in snapshot.reference_records:
        if record.asset_path:
            refs[record.asset_path] = record.package_path or record.asset_path
    if snapshot.usd_stage_path:
        refs[snapshot.usd_stage_path] = snapshot.usd_stage_path
    return refs


def write_scene_snapshot_package(
    snapshot: SceneSnapshot,
    archive_path: str | Path,
    *,
    repo_root: str | Path,
) -> Path:
    """Write a portable JSON + sidecar ZIP package for a SceneSnapshot."""

    archive = Path(archive_path)
    archive.parent.mkdir(parents=True, exist_ok=True)
    root = Path(repo_root)
    payload = scene_snapshot_to_payload(snapshot)
    asset_manifest: list[dict[str, Any]] = []

    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scene_snapshot.json", json.dumps(payload, ensure_ascii=False, indent=2))
        zf.writestr("materials.json", json.dumps({"materials": [asdict(item) for item in snapshot.materials]}, ensure_ascii=False, indent=2))
        zf.writestr("cameras.json", json.dumps({"cameras": [asdict(item) for item in snapshot.cameras]}, ensure_ascii=False, indent=2))
        zf.writestr("lights.json", json.dumps({"lights": [asdict(item) for item in snapshot.lights]}, ensure_ascii=False, indent=2))

        for repo_ref, package_ref in sorted(_asset_refs_from_snapshot(snapshot).items()):
            try:
                source = resolve_repo_path(root, repo_ref)
            except Exception:
                continue
            if not source.exists() or not source.is_file():
                continue
            archive_name = f"assets/{package_ref}".replace("\\", "/").lstrip("/")
            zf.write(source, archive_name)
            stat = source.stat()
            asset_manifest.append(
                {
                    "repo_path": repo_ref,
                    "archive_path": archive_name,
                    "size_bytes": stat.st_size,
                    "sha256": _sha256_file(source),
                }
            )

        package = {
            "package_version": "1.0",
            "snapshot_schema_version": snapshot.schema_version,
            "scene_id": snapshot.scene_id,
            "frame_id": snapshot.frame.frame_id,
            "assets": asset_manifest,
        }
        zf.writestr("package.json", json.dumps(package, ensure_ascii=False, indent=2))

    return archive


def read_scene_snapshot_package(archive_path: str | Path) -> SceneSnapshot:
    """Read a SceneSnapshot from a portable package ZIP."""

    with zipfile.ZipFile(Path(archive_path), mode="r") as zf:
        scene_payload = json.loads(zf.read("scene_snapshot.json").decode("utf-8"))
        materials_payload = json.loads(zf.read("materials.json").decode("utf-8")) if "materials.json" in zf.namelist() else {}
        cameras_payload = json.loads(zf.read("cameras.json").decode("utf-8")) if "cameras.json" in zf.namelist() else {}
        lights_payload = json.loads(zf.read("lights.json").decode("utf-8")) if "lights.json" in zf.namelist() else {}
    snapshot = scene_snapshot_from_payload(
        scene_payload,
        materials=materials_payload.get("materials", []),
        cameras=cameras_payload.get("cameras", []),
        lights=lights_payload.get("lights", []),
    )
    validate_scene_snapshot(snapshot)
    return snapshot


def extract_scene_snapshot_package(archive_path: str | Path, output_dir: str | Path) -> SceneSnapshot:
    """Extract package contents and return the contained SceneSnapshot."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(Path(archive_path), mode="r") as zf:
        zf.extractall(output)
    return read_scene_snapshot_package(archive_path)


def write_observation_bundle_manifest(path: str | Path, bundle: ObservationBundleManifest) -> Path:
    validate_observation_bundle_manifest(bundle)
    output = Path(path)
    _write_json(output, observation_bundle_manifest_to_payload(bundle))
    return output


def read_observation_bundle_manifest(path: str | Path) -> ObservationBundleManifest:
    return observation_bundle_manifest_from_payload(_read_json(Path(path)))


def write_render_job_status(path: str | Path, status: RenderJobStatus) -> Path:
    validate_render_job_status(status)
    output = Path(path)
    _write_json(output, render_job_status_to_payload(status))
    return output


def read_render_job_status(path: str | Path) -> RenderJobStatus:
    return render_job_status_from_payload(_read_json(Path(path)))


# --- New Isaac Sim Integration Types --- #


def bsdf_override_to_payload(bsdf: BsdfOverride) -> Dict[str, Any]:
    return asdict(bsdf)


def bsdf_override_from_payload(payload: Dict[str, Any]) -> BsdfOverride:
    return BsdfOverride(
        bsdf_type=str(payload.get("bsdf_type", "diffuse")),
        base_color=payload.get("base_color"),
        roughness=payload.get("roughness"),
        metallic=payload.get("metallic"),
        ior=payload.get("ior"),
        material=payload.get("material"),
        measured_file_path=payload.get("measured_file_path"),
        dataset_id=payload.get("dataset_id"),
        material_id=payload.get("material_id"),
        extras=payload.get("extras", {}),
    )


def isaac_object_state_to_payload(obj: IsaacObjectState) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "prim_path": obj.prim_path,
        "transform": obj.transform,
    }
    if obj.visible is not None:
        result["visible"] = bool(obj.visible)
    if obj.bsdf_override is not None:
        result["bsdf_override"] = bsdf_override_to_payload(obj.bsdf_override)
    if obj.bsdf_override_key is not None:
        result["bsdf_override_key"] = obj.bsdf_override_key
    if obj.extras:
        result["extras"] = obj.extras
    return result


def isaac_object_state_from_payload(payload: Dict[str, Any]) -> IsaacObjectState:
    bsdf_payload = payload.get("bsdf_override")
    bsdf_override = bsdf_override_from_payload(bsdf_payload) if bsdf_payload else None
    return IsaacObjectState(
        prim_path=str(payload["prim_path"]),
        transform=list(payload["transform"]),
        visible=payload.get("visible"),
        bsdf_override=bsdf_override,
        bsdf_override_key=payload.get("bsdf_override_key"),
        extras=payload.get("extras", {}),
    )


def isaac_state_snapshot_to_payload(snapshot: IsaacStateSnapshot) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "snapshot_id": snapshot.snapshot_id,
        "timestamp": snapshot.timestamp,
        "scene_id": snapshot.scene_id,
        "mitsuba_scene_ref": snapshot.mitsuba_scene_ref,
        "objects": [isaac_object_state_to_payload(obj) for obj in snapshot.objects],
        "modalities": snapshot.modalities,
        "submit_mode": snapshot.submit_mode,
    }
    if snapshot.scene_snapshot_ref is not None:
        result["scene_snapshot_ref"] = snapshot.scene_snapshot_ref
    if snapshot.shape_map_ref is not None:
        result["shape_map_ref"] = snapshot.shape_map_ref
    if snapshot.camera is not None:
        result["camera"] = camera_spec_to_payload(snapshot.camera)
    if snapshot.robot_state is not None:
        result["robot_state"] = robot_state_to_payload(snapshot.robot_state)
    if snapshot.render_settings:
        result["render_settings"] = snapshot.render_settings
    if snapshot.extras:
        result["extras"] = snapshot.extras
    return result


def isaac_state_snapshot_from_payload(payload: Dict[str, Any]) -> IsaacStateSnapshot:
    camera_payload = payload.get("camera")
    camera = camera_spec_from_payload(camera_payload) if camera_payload else None

    robot_payload = payload.get("robot_state")
    robot_state = robot_state_from_payload(robot_payload) if robot_payload else None

    objects = [
        isaac_object_state_from_payload(obj_payload)
        for obj_payload in payload.get("objects", [])
    ]

    return IsaacStateSnapshot(
        snapshot_id=str(payload["snapshot_id"]),
        timestamp=str(payload["timestamp"]),
        scene_id=str(payload["scene_id"]),
        scene_snapshot_ref=payload.get("scene_snapshot_ref"),
        mitsuba_scene_ref=str(payload["mitsuba_scene_ref"]),
        shape_map_ref=payload.get("shape_map_ref"),
        objects=objects,
        camera=camera,
        robot_state=robot_state,
        modalities=list(payload.get("modalities", ["rgb"])),
        submit_mode=str(payload.get("submit_mode", "blocking")),
        render_settings=payload.get("render_settings", {}),
        extras=payload.get("extras", {}),
    )


def isaac_session_open_to_payload(session_open: IsaacSessionOpen) -> Dict[str, Any]:
    return asdict(session_open)


def isaac_session_open_from_payload(payload: Dict[str, Any]) -> IsaacSessionOpen:
    return IsaacSessionOpen(
        scene_id=str(payload["scene_id"]),
        mitsuba_scene_ref=str(payload["mitsuba_scene_ref"]),
        shape_map_ref=str(payload["shape_map_ref"]),
        scene_snapshot_ref=payload.get("scene_snapshot_ref"),
        extras=payload.get("extras", {}),
    )


def isaac_state_patch_to_payload(state_patch: IsaacStatePatch) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "objects": [isaac_object_state_to_payload(obj) for obj in state_patch.objects],
    }
    if state_patch.timestamp is not None:
        result["timestamp"] = state_patch.timestamp
    if state_patch.extras:
        result["extras"] = state_patch.extras
    return result


def isaac_state_patch_from_payload(payload: Dict[str, Any]) -> IsaacStatePatch:
    return IsaacStatePatch(
        objects=[isaac_object_state_from_payload(item) for item in payload.get("objects", [])],
        timestamp=payload.get("timestamp"),
        extras=payload.get("extras", {}),
    )


def isaac_material_patch_to_payload(material_patch: IsaacMaterialPatch) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "overrides": {prim_path: bsdf_override_to_payload(bsdf) for prim_path, bsdf in material_patch.overrides.items()},
    }
    if material_patch.timestamp is not None:
        result["timestamp"] = material_patch.timestamp
    if material_patch.extras:
        result["extras"] = material_patch.extras
    return result


def isaac_material_patch_from_payload(payload: Dict[str, Any]) -> IsaacMaterialPatch:
    overrides_payload = payload.get("overrides", {})
    return IsaacMaterialPatch(
        overrides={
            str(prim_path): bsdf_override_from_payload(bsdf_payload)
            for prim_path, bsdf_payload in overrides_payload.items()
            if isinstance(bsdf_payload, dict)
        },
        timestamp=payload.get("timestamp"),
        extras=payload.get("extras", {}),
    )


def isaac_sensor_spec_to_payload(sensor_spec: IsaacSensorSpec) -> Dict[str, Any]:
    return asdict(sensor_spec)


def isaac_sensor_spec_from_payload(payload: Dict[str, Any]) -> IsaacSensorSpec:
    return IsaacSensorSpec(
        sensor_id=str(payload["sensor_id"]),
        name=str(payload.get("name") or payload["sensor_id"]),
        modalities=list(payload.get("modalities", ["rgb"])),
        calibration_ref=payload.get("calibration_ref"),
        camera_to_world=list(payload["camera_to_world"]) if payload.get("camera_to_world") is not None else None,
        fov_deg=float(payload["fov_deg"]) if payload.get("fov_deg") is not None else None,
        resolution=list(payload["resolution"]) if payload.get("resolution") is not None else None,
        sensor_sync_group=str(payload.get("sensor_sync_group", "default")),
        pose_source=payload.get("pose_source"),
        sensor_type=str(payload.get("sensor_type", "rgb_camera")),
        profile=payload.get("profile"),
        metadata_ref=payload.get("metadata_ref"),
        extras=payload.get("extras", {}),
    )


def isaac_capture_request_to_payload(capture_request: IsaacCaptureRequest) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "submit_mode": capture_request.submit_mode,
        "render_settings": dict(capture_request.render_settings),
    }
    if capture_request.sensor_id is not None:
        result["sensor_id"] = capture_request.sensor_id
    if capture_request.camera is not None:
        result["camera"] = camera_spec_to_payload(capture_request.camera)
    if capture_request.modalities:
        result["modalities"] = list(capture_request.modalities)
    if capture_request.extras:
        result["extras"] = capture_request.extras
    return result


def isaac_capture_request_from_payload(payload: Dict[str, Any]) -> IsaacCaptureRequest:
    camera_payload = payload.get("camera")
    return IsaacCaptureRequest(
        sensor_id=payload.get("sensor_id"),
        camera=camera_spec_from_payload(camera_payload) if camera_payload else None,
        modalities=list(payload.get("modalities", [])),
        submit_mode=str(payload.get("submit_mode", "blocking")),
        render_settings=dict(payload.get("render_settings", {})),
        extras=payload.get("extras", {}),
    )
