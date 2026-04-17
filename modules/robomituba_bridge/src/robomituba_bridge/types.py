from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

JsonDict = Dict[str, Any]
Mat4 = List[float]
Vec2 = List[float]
Vec3 = List[float]


@dataclass
class MeshRecord:
    mesh_id: str
    name: str
    source_path: str
    material_id: Optional[str] = None
    geometry_path: Optional[str] = None
    primitive: str = "mesh"
    vertex_count: Optional[int] = None
    face_count: Optional[int] = None
    transform: Optional[Mat4] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class MaterialRecord:
    material_id: str
    name: str
    source_path: str
    kind: str = "auto"
    shader_model: Optional[str] = None
    base_color: Optional[Vec3] = None
    roughness: Optional[float] = None
    metallic: Optional[float] = None
    ior: Optional[float] = None
    opacity: Optional[float] = None
    double_sided: bool = False
    textures: JsonDict = field(default_factory=dict)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class CameraRecord:
    camera_id: str
    name: str
    source_path: str
    projection: str = "perspective"
    fov_deg: Optional[float] = None
    resolution: Optional[List[int]] = None
    clip_range: Optional[List[float]] = None
    look_at: Optional[JsonDict] = None
    transform: Optional[Mat4] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class LightRecord:
    light_id: str
    name: str
    source_path: str
    light_type: str
    color: Optional[Vec3] = None
    intensity: Optional[float] = None
    exposure: Optional[float] = None
    radius: Optional[float] = None
    size: Optional[Vec2] = None
    texture_path: Optional[str] = None
    look_at: Optional[JsonDict] = None
    transform: Optional[Mat4] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class FrameRecord:
    frame_id: str
    time_code: Optional[float] = None
    timestamp: Optional[str] = None
    active_camera_id: Optional[str] = None
    meters_per_unit: Optional[float] = None
    up_axis: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class SceneSnapshot:
    scene_id: str
    frame: FrameRecord
    meshes: List[MeshRecord] = field(default_factory=list)
    materials: List[MaterialRecord] = field(default_factory=list)
    cameras: List[CameraRecord] = field(default_factory=list)
    lights: List[LightRecord] = field(default_factory=list)
    usd_stage_path: Optional[str] = None
    robot_state: Optional[RobotState] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class JobPaths:
    job_dir: str
    manifest: str
    snapshot_dir: str
    scene_snapshot: str
    materials: str
    cameras: str
    lights: str
    usd_dir: str
    usd_stage: str
    renders_dir: str
    logs_dir: str


@dataclass
class JobManifest:
    job_id: str
    scene_id: str
    frame_id: str
    created_at: str
    paths: JobPaths
    extras: JsonDict = field(default_factory=dict)


@dataclass
class SceneState:
    job_id: str
    scene_id: str
    frame_id: str
    timestamp: str
    scene_snapshot_ref: str
    mitsuba_scene_ref: str
    scene_version: Optional[str] = None
    illumination_setup: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class CameraSpec:
    camera_id: str
    name: str
    camera_to_world: Mat4
    fov_deg: float
    resolution: Optional[List[int]] = None
    sensor_modality: str = "rgb"
    sensor_sync_group: str = "default"
    calibration_ref: Optional[str] = None
    source_camera_id: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class BsdfOverride:
    """Mitsuba BSDF 재질 정의 (Isaac에서 오브젝트별로 선택 가능)"""
    bsdf_type: str  # "diffuse" | "conductor" | "roughplastic" | "dielectric" | "roughconductor" | "principled" | "measured_polarized" | "measured"
    base_color: Optional[Vec3] = None
    roughness: Optional[float] = None
    metallic: Optional[float] = None
    ior: Optional[float] = None
    material: Optional[str] = None  # conductor용 material name ("Al", "Cu", "Au", etc)
    measured_file_path: Optional[str] = None  # measured / measured_polarized용 파일 경로 (repo-relative)
    dataset_id: Optional[str] = None  # 출처 데이터셋 ID (e.g. "pbrdf_2020", "hpbrdf_2025")
    material_id: Optional[str] = None  # 데이터셋 내 material ID
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacObjectState:
    """Isaac stage 내 단일 prim의 런타임 상태"""
    prim_path: str  # USD prim path, e.g. "/World/Robot/link_0"
    transform: Mat4  # 4x4 column-major world transform (16 floats)
    visible: Optional[bool] = None
    bsdf_override: Optional[BsdfOverride] = None
    bsdf_override_key: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacStateSnapshot:
    """Isaac Sim에서 캡처한 런타임 scene 상태 전체"""
    snapshot_id: str
    timestamp: str
    scene_id: str
    mitsuba_scene_ref: str  # repo-relative path to base scene.xml
    scene_snapshot_ref: Optional[str] = None
    shape_map_ref: Optional[str] = None
    objects: List[IsaacObjectState] = field(default_factory=list)
    camera: Optional[CameraSpec] = None
    robot_state: Optional[RobotState] = None
    modalities: List[str] = field(default_factory=lambda: ["rgb"])
    submit_mode: str = "blocking"
    render_settings: JsonDict = field(default_factory=dict)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacSessionOpen:
    scene_id: str
    mitsuba_scene_ref: str
    shape_map_ref: str
    scene_snapshot_ref: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacStatePatch:
    objects: List[IsaacObjectState] = field(default_factory=list)
    timestamp: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacMaterialPatch:
    overrides: Dict[str, BsdfOverride] = field(default_factory=dict)
    timestamp: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacSensorSpec:
    sensor_id: str
    name: str
    modalities: List[str] = field(default_factory=lambda: ["rgb"])
    calibration_ref: Optional[str] = None
    camera_to_world: Optional[Mat4] = None
    fov_deg: Optional[float] = None
    resolution: Optional[List[int]] = None
    sensor_sync_group: str = "default"
    pose_source: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class IsaacCaptureRequest:
    sensor_id: Optional[str] = None
    camera: Optional[CameraSpec] = None
    modalities: List[str] = field(default_factory=list)
    submit_mode: str = "blocking"
    render_settings: JsonDict = field(default_factory=dict)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class SceneOverrideSpec:
    target_shape_filenames: List[str] = field(default_factory=list)
    material_profile: str = "glossy_black_lacquer"
    # 새 필드: prim_path → explicit Mitsuba shape IDs 매핑
    prim_to_shape_ids: Dict[str, List[str]] = field(default_factory=dict)
    # 새 필드: prim_path → BsdfOverride 매핑 (IsaacStateSnapshot 기반)
    bsdf_overrides: Dict[str, BsdfOverride] = field(default_factory=dict)
    # 새 필드: prim_path → Mat4 transform 매핑 (IsaacStateSnapshot 기반)
    transform_overrides: Dict[str, Mat4] = field(default_factory=dict)
    extras: JsonDict = field(default_factory=dict)


@dataclass
class AssistLightSpec:
    mode: str = "camera_aligned_rect"
    distance_m: float = 0.12
    size_world: Vec2 = field(default_factory=lambda: [2.2, 1.6])
    spectrum_mode: str = "nir_grayscale_proxy"
    polarized: bool = True
    polarizer_angle_deg: float = 0.0
    extras: JsonDict = field(default_factory=dict)


@dataclass
class DepthApproxSpec:
    mode: str = "planar_reflective_proxy"
    target_shape_filenames: List[str] = field(default_factory=list)
    blur_sigma_px: float = 2.0
    blend: float = 1.0
    extras: JsonDict = field(default_factory=dict)


@dataclass
class RobotState:
    base_pose: Optional[Mat4] = None
    joint_names: List[str] = field(default_factory=list)
    joint_positions: List[float] = field(default_factory=list)
    gripper_state: Optional[JsonDict] = None
    ee_pose: Optional[Mat4] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class RenderRequest:
    request_id: str
    job_id: str
    frame_id: str
    timestamp: str
    scene_state: SceneState
    camera_specs: List[CameraSpec] = field(default_factory=list)
    modalities: List[str] = field(default_factory=list)
    robot_state: RobotState = field(default_factory=RobotState)
    render_settings: JsonDict = field(default_factory=dict)
    scene_override: Optional[SceneOverrideSpec] = None
    assist_light: Optional[AssistLightSpec] = None
    depth_approx: Optional[DepthApproxSpec] = None
    action_ref: Optional[str] = None
    prev_observation_ref: Optional[str] = None
    next_observation_ref: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class RenderJobAccepted:
    job_id: str
    frame_id: str
    status: str
    submitted_at: str
    status_url: str
    manifest_url: str
    queue_position: int = 0
    extras: JsonDict = field(default_factory=dict)


@dataclass
class RenderJobStatus:
    job_id: str
    frame_id: str
    status: str
    submitted_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    progress_stage: str = "queued"
    manifest_path: Optional[str] = None
    error: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class RenderArtifactManifest:
    camera_id: str
    modality: str
    definition: str
    artifact_paths: JsonDict = field(default_factory=dict)
    timing: JsonDict = field(default_factory=dict)
    dependencies: JsonDict = field(default_factory=dict)
    scene_ref: Optional[str] = None
    material_mode: Optional[str] = None
    array_shape: List[int] = field(default_factory=list)
    dtype: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)


@dataclass
class ObservationBundleManifest:
    job_id: str
    scene_id: str
    frame_id: str
    timestamp: str
    scene_state: SceneState
    robot_state: RobotState
    requested_modalities: List[str] = field(default_factory=list)
    camera_specs: List[CameraSpec] = field(default_factory=list)
    artifacts: List[RenderArtifactManifest] = field(default_factory=list)
    bundle_root: str = ""
    status: str = "complete"
    action_ref: Optional[str] = None
    prev_observation_ref: Optional[str] = None
    next_observation_ref: Optional[str] = None
    extras: JsonDict = field(default_factory=dict)
