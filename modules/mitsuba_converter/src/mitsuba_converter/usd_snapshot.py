from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
from typing import Any, Iterable

from robomituba_bridge.paths import to_repo_relative_posix
from robomituba_bridge.types import (
    CameraRecord,
    FrameRecord,
    InstancerMappingRecord,
    LightRecord,
    MaterialRecord,
    MeshRecord,
    PoseRecord,
    ReferenceRecord,
    RobotState,
    SceneSnapshot,
)


def require_pxr():
    try:
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade
    except Exception as exc:
        raise RuntimeError(
            "pxr Python bindings are required. Run inside Isaac Sim Python or an OpenUSD environment."
        ) from exc
    return Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade


def open_stage(usd_path: str):
    _, _, Usd, _, _, _ = require_pxr()
    stage = Usd.Stage.Open(str(usd_path))
    if stage is None:
        raise RuntimeError(f"Failed to open USD stage: {usd_path}")
    return stage


def _matrix_to_list(matrix: Any) -> list[float]:
    import numpy as np

    candidate = np.asarray(matrix, dtype=np.float64)
    if candidate.shape == (16,):
        candidate = candidate.reshape(4, 4)
    if candidate.shape != (4, 4):
        raise ValueError(f"Expected 4x4 matrix, got {candidate.shape}")
    last_col = candidate[:3, 3]
    last_row = candidate[3, :3]
    if float(np.linalg.norm(last_row)) > max(1e-5, float(np.linalg.norm(last_col)) * 2.0):
        candidate = candidate.T
    return candidate.reshape(-1).astype(float).tolist()


def _extract_look_at(matrix: Any) -> dict[str, list[float]]:
    Gf, _, _, _, _, _ = require_pxr()
    origin = matrix.Transform(Gf.Vec3d(0, 0, 0))
    target = matrix.Transform(Gf.Vec3d(0, 0, -1))
    up = matrix.TransformDir(Gf.Vec3d(0, 1, 0))
    return {
        "origin": [float(origin[0]), float(origin[1]), float(origin[2])],
        "target": [float(target[0]), float(target[1]), float(target[2])],
        "up": [float(up[0]), float(up[1]), float(up[2])],
    }


def _fov_from_camera(camera: Any) -> float | None:
    focal_length = camera.GetFocalLengthAttr().Get()
    aperture = camera.GetHorizontalApertureAttr().Get()
    if not focal_length or not aperture:
        return None
    return float(2.0 * math.degrees(math.atan(float(aperture) / (2.0 * float(focal_length)))))


def _repo_rel_or_none(repo_root: Path | None, path: Path | None) -> str | None:
    if path is None or repo_root is None:
        return None
    try:
        return to_repo_relative_posix(repo_root, path)
    except Exception:
        return None


def _resolve_asset_path(source_usd_path: Path | None, repo_root: Path | None, asset_path: Any) -> str | None:
    if not asset_path:
        return None
    raw = str(asset_path).strip("@")
    if not raw or raw.startswith(("omniverse://", "http://", "https://")):
        return None
    candidate = Path(raw)
    if not candidate.is_absolute() and source_usd_path is not None:
        candidate = (source_usd_path.parent / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return _repo_rel_or_none(repo_root, candidate)


def _unwrap_connected_source(payload: Any):
    value = payload
    while isinstance(value, (tuple, list)) and value:
        value = value[0]
    return value


def _connected_shader(shader_input: Any, UsdShade: Any):
    if not shader_input:
        return None
    connected = shader_input.GetConnectedSource()
    if not connected:
        return None
    prim = _unwrap_connected_source(connected)
    return UsdShade.Shader(prim.GetPrim())


def _extract_texture(shader_input: Any, source_usd_path: Path | None, repo_root: Path | None, UsdShade: Any) -> str | None:
    shader = _connected_shader(shader_input, UsdShade)
    if shader is None:
        return None
    shader_id = shader.GetIdAttr().Get() or ""
    if "UVTexture" not in str(shader_id) and "UsdUVTexture" not in str(shader_id):
        return None
    file_input = shader.GetInput("file")
    if not file_input:
        return None
    return _resolve_asset_path(source_usd_path, repo_root, file_input.Get())


def _float_input(shader: Any, name: str) -> float | None:
    shader_input = shader.GetInput(name) if shader else None
    if not shader_input:
        return None
    value = shader_input.Get()
    return float(value) if value is not None else None


def _vec3_input(shader: Any, name: str) -> list[float] | None:
    shader_input = shader.GetInput(name) if shader else None
    if not shader_input:
        return None
    value = shader_input.Get()
    if value is None:
        return None
    return [float(value[0]), float(value[1]), float(value[2])]


def extract_material_record(material: Any, source_usd_path: Path | None, repo_root: Path | None) -> MaterialRecord:
    _, _, _, _, _, UsdShade = require_pxr()

    material_path = str(material.GetPath())
    shader_model = None
    shader = None
    surface_output = material.GetSurfaceOutput()
    if surface_output:
        connected = surface_output.GetConnectedSource()
        if connected:
            shader = UsdShade.Shader(_unwrap_connected_source(connected).GetPrim())
            shader_model = shader.GetIdAttr().Get()

    textures: dict[str, str] = {}
    if shader:
        texture_slots = {
            "base_color": ["diffuseColor", "base_color"],
            "roughness": ["roughness"],
            "metallic": ["metallic"],
            "normal": ["normal", "normalmap"],
            "opacity": ["opacity"],
            "emissive": ["emissiveColor", "emissionColor"],
        }
        for target_slot, source_slots in texture_slots.items():
            for source_slot in source_slots:
                texture_path = _extract_texture(shader.GetInput(source_slot), source_usd_path, repo_root, UsdShade)
                if texture_path:
                    textures[target_slot] = texture_path
                    break

    return MaterialRecord(
        material_id=material_path,
        name=material.GetPrim().GetName(),
        source_path=material_path,
        shader_model=str(shader_model) if shader_model else None,
        base_color=_vec3_input(shader, "diffuseColor") or _vec3_input(shader, "base_color"),
        roughness=_float_input(shader, "roughness"),
        metallic=_float_input(shader, "metallic"),
        ior=_float_input(shader, "ior"),
        opacity=_float_input(shader, "opacity"),
        specular=_float_input(shader, "specular"),
        transmission=_float_input(shader, "transmission"),
        emission_color=_vec3_input(shader, "emissiveColor") or _vec3_input(shader, "emissionColor"),
        emission_intensity=_float_input(shader, "emissiveIntensity") or _float_input(shader, "emissionIntensity"),
        textures=textures,
        physical_params={
            key: value
            for key, value in {
                "clearcoat": _float_input(shader, "clearcoat"),
                "clearcoatRoughness": _float_input(shader, "clearcoatRoughness"),
            }.items()
            if value is not None
        },
    )


def _triangulate(counts: Iterable[int], indices: Iterable[int]) -> list[list[int]]:
    idx = list(indices)
    tri_faces: list[list[int]] = []
    cursor = 0
    for raw_count in counts:
        count = int(raw_count)
        face = idx[cursor: cursor + count]
        cursor += count
        if count < 3:
            continue
        v0 = int(face[0])
        for k in range(1, count - 1):
            tri_faces.append([v0, int(face[k]), int(face[k + 1])])
    return tri_faces


def mesh_geometry_payload(mesh: Any) -> dict[str, Any]:
    points = mesh.GetPointsAttr().Get() or []
    counts = mesh.GetFaceVertexCountsAttr().Get() or []
    indices = mesh.GetFaceVertexIndicesAttr().Get() or []
    payload: dict[str, Any] = {
        "vertices": [[float(p[0]), float(p[1]), float(p[2])] for p in points],
        "faces": _triangulate(counts, indices),
    }
    normals_attr = mesh.GetNormalsAttr()
    normals = normals_attr.Get() if normals_attr else None
    if normals:
        payload["normals"] = [[float(n[0]), float(n[1]), float(n[2])] for n in normals]
    try:
        _, _, _, UsdGeom, _, _ = require_pxr()
        primvars = UsdGeom.PrimvarsAPI(mesh).GetPrimvars()
    except Exception:
        primvars = []
    for primvar in primvars:
        name = primvar.GetPrimvarName()
        if name in {"st", "uv", "UVMap"}:
            values = primvar.Get()
            if values:
                payload["uvs"] = [[float(v[0]), float(v[1])] for v in values]
                payload["uv_interpolation"] = str(primvar.GetInterpolation())
                break
    return payload


def _is_renderable_mesh(mesh_prim: Any) -> bool:
    try:
        _, _, _, UsdGeom, _, _ = require_pxr()
        imageable = UsdGeom.Imageable(mesh_prim)
    except Exception:
        imageable = None
    if imageable:
        purpose = imageable.GetPurposeAttr().Get() if imageable.GetPurposeAttr() else None
        if str(purpose or "") in {"guide", "proxy"}:
            return False
        visibility = imageable.GetVisibilityAttr().Get() if imageable.GetVisibilityAttr() else None
        if str(visibility or "") == "invisible":
            return False
    path_lower = str(mesh_prim.GetPath()).lower()
    return "/colliders/" not in path_lower and "/collision/" not in path_lower


def _imageable_visible(prim: Any) -> bool | None:
    try:
        _, _, _, UsdGeom, _, _ = require_pxr()
        imageable = UsdGeom.Imageable(prim)
        visibility = imageable.GetVisibilityAttr().Get() if imageable else None
        return str(visibility or "") != "invisible"
    except Exception:
        return None


def _attr_value(prim: Any, name: str):
    attr = prim.GetAttribute(name)
    if not attr:
        return None
    return attr.Get()


def extract_robot_state(stage: Any, xform_cache: Any) -> RobotState | None:
    for prim in stage.Traverse():
        if str(_attr_value(prim, "robomituba:robotName") or "") != "ranger_mini_v3":
            continue
        joint_names = [str(item) for item in (_attr_value(prim, "robomituba:jointNames") or [])]
        joint_positions = [float(item) for item in (_attr_value(prim, "robomituba:jointPositions") or [])]
        steering_angles = [float(item) for item in (_attr_value(prim, "robomituba:steeringAngles") or [])]
        wheel_speeds = [float(item) for item in (_attr_value(prim, "robomituba:wheelSpeeds") or [])]
        return RobotState(
            base_pose=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
            joint_names=joint_names,
            joint_positions=joint_positions,
            extras={
                "ranger_mini": {
                    "robot_name": "ranger_mini_v3",
                    "motion_mode": int(_attr_value(prim, "robomituba:motionMode") or 0),
                    "steering_angles": steering_angles,
                    "wheel_speeds": wheel_speeds,
                    "battery": {
                        "voltage": float(_attr_value(prim, "robomituba:batteryVoltage") or 48.0),
                        "soc": float(_attr_value(prim, "robomituba:batterySoc") or 1.0),
                    },
                    "estop": bool(_attr_value(prim, "robomituba:estop") or False),
                    "has_error": bool(_attr_value(prim, "robomituba:hasError") or False),
                }
            },
        )
    return None


def _bound_material_id(prim: Any, material_records: dict[str, MaterialRecord], source_usd_path: Path | None, repo_root: Path | None) -> str | None:
    _, _, _, _, _, UsdShade = require_pxr()
    bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
    material = _unwrap_connected_source(bound)
    if not material:
        return None
    material_id = str(material.GetPath())
    if material_id not in material_records:
        material_records[material_id] = extract_material_record(material, source_usd_path, repo_root)
    return material_id


def _camera_record(prim: Any, xform_cache: Any) -> CameraRecord:
    _, _, _, UsdGeom, _, _ = require_pxr()
    camera = UsdGeom.Camera(prim)
    clip_range = camera.GetClippingRangeAttr().Get()
    projection = str(camera.GetProjectionAttr().Get() or "perspective")
    orientation_attr = camera.GetCameraOrientationAttr() if hasattr(camera, "GetCameraOrientationAttr") else None
    return CameraRecord(
        camera_id=str(prim.GetPath()),
        name=prim.GetName(),
        source_path=str(prim.GetPath()),
        projection=projection,
        fov_deg=_fov_from_camera(camera),
        clip_range=[float(clip_range[0]), float(clip_range[1])] if clip_range else None,
        horizontal_aperture=float(camera.GetHorizontalApertureAttr().Get() or 0.0) or None,
        vertical_aperture=float(camera.GetVerticalApertureAttr().Get() or 0.0) or None,
        focal_length=float(camera.GetFocalLengthAttr().Get() or 0.0) or None,
        focus_distance=float(camera.GetFocusDistanceAttr().Get() or 0.0) or None,
        f_stop=float(camera.GetFStopAttr().Get() or 0.0) or None,
        sensor_orientation=str(orientation_attr.Get()) if orientation_attr and orientation_attr.Get() is not None else None,
        look_at=_extract_look_at(xform_cache.GetLocalToWorldTransform(prim)),
        transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
    )


def _light_record(prim: Any, xform_cache: Any, source_usd_path: Path | None, repo_root: Path | None) -> LightRecord | None:
    _, _, _, _, UsdLux, _ = require_pxr()
    light_type = None
    radius = None
    size = None
    angle = None
    texture_path = None
    params: dict[str, Any] = {}
    if prim.IsA(UsdLux.RectLight):
        light_type = "rectangle"
        rect = UsdLux.RectLight(prim)
        size = [float(rect.GetWidthAttr().Get() or 1.0), float(rect.GetHeightAttr().Get() or 1.0)]
    elif prim.IsA(UsdLux.SphereLight):
        light_type = "sphere"
        sphere = UsdLux.SphereLight(prim)
        radius = float(sphere.GetRadiusAttr().Get() or 0.5)
        params["treat_as_point"] = bool(sphere.GetTreatAsPointAttr().Get() or False)
    elif prim.IsA(UsdLux.DomeLight):
        light_type = "envmap"
        dome = UsdLux.DomeLight(prim)
        texture_path = _resolve_asset_path(source_usd_path, repo_root, dome.GetTextureFileAttr().Get())
    elif prim.IsA(UsdLux.DistantLight):
        light_type = "distant"
        distant = UsdLux.DistantLight(prim)
        angle = float(distant.GetAngleAttr().Get() or 0.53)
    elif prim.IsA(UsdLux.DiskLight):
        light_type = "disk"
        disk = UsdLux.DiskLight(prim)
        radius = float(disk.GetRadiusAttr().Get() or 0.5)
    if light_type is None:
        return None
    light_api = UsdLux.LightAPI(prim)
    color = light_api.GetColorAttr().Get() if light_api else None
    intensity = light_api.GetIntensityAttr().Get() if light_api else None
    exposure = light_api.GetExposureAttr().Get() if light_api else None
    normalize_attr = prim.GetAttribute("normalize")
    color_temp_attr = prim.GetAttribute("inputs:colorTemperature") or prim.GetAttribute("colorTemperature")
    return LightRecord(
        light_id=str(prim.GetPath()),
        name=prim.GetName(),
        source_path=str(prim.GetPath()),
        light_type=light_type,
        color=[float(color[0]), float(color[1]), float(color[2])] if color else None,
        intensity=float(intensity) if intensity is not None else None,
        exposure=float(exposure) if exposure is not None else None,
        radius=radius,
        size=size,
        angle=angle,
        temperature=float(color_temp_attr.Get()) if color_temp_attr and color_temp_attr.Get() is not None else None,
        normalize=bool(normalize_attr.Get()) if normalize_attr and normalize_attr.Get() is not None else None,
        texture_path=texture_path,
        light_params=params,
        transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
    )


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


def _reference_records(stage: Any, source_usd_path: Path | None, repo_root: Path | None) -> list[ReferenceRecord]:
    records: list[ReferenceRecord] = []
    seen: set[tuple[str, str]] = set()
    for prim in stage.Traverse():
        for spec in prim.GetPrimStack():
            ref_list = getattr(spec, "referenceList", None)
            if ref_list is None:
                continue
            refs = list(getattr(ref_list, "prependedItems", []) or []) + list(getattr(ref_list, "appendedItems", []) or [])
            for ref in refs:
                asset_path = str(getattr(ref, "assetPath", "") or "")
                if not asset_path:
                    continue
                resolved = Path(asset_path)
                if not resolved.is_absolute() and source_usd_path is not None:
                    resolved = (source_usd_path.parent / resolved).resolve()
                package_path = _repo_rel_or_none(repo_root, resolved)
                key = (str(prim.GetPath()), package_path or asset_path)
                if key in seen:
                    continue
                seen.add(key)
                records.append(
                    ReferenceRecord(
                        reference_id=f"ref_{len(records)}",
                        source_path=str(prim.GetPath()),
                        asset_path=package_path or asset_path,
                        package_path=package_path,
                        sha256=_sha256(resolved) if resolved.exists() else None,
                        size_bytes=resolved.stat().st_size if resolved.exists() else None,
                        layer_identifier=str(getattr(spec.layer, "identifier", "") or ""),
                    )
                )
    return records


def _pose_time_codes(stage: Any, explicit_time_codes: Iterable[float] | None) -> list[float | None]:
    if explicit_time_codes is not None:
        return [float(item) for item in explicit_time_codes]
    start = stage.GetStartTimeCode()
    end = stage.GetEndTimeCode()
    if start != end:
        return [float(start), float(end)]
    return [None]


def _point_instancer_mappings(prim: Any, xform_cache: Any, material_records: dict[str, MaterialRecord], source_usd_path: Path | None, repo_root: Path | None, time_code: float | None) -> list[InstancerMappingRecord]:
    _, _, _, UsdGeom, _, _ = require_pxr()
    instancer = UsdGeom.PointInstancer(prim)
    proto_indices = list(instancer.GetProtoIndicesAttr().Get(time_code) or [])
    prototypes = instancer.GetPrototypesRel().GetTargets() or []
    try:
        transforms = instancer.ComputeInstanceTransformsAtTime(time_code if time_code is not None else 0.0, time_code if time_code is not None else 0.0)
    except Exception:
        transforms = []
    records: list[InstancerMappingRecord] = []
    for index, proto_index in enumerate(proto_indices):
        prototype_path = str(prototypes[int(proto_index)]) if 0 <= int(proto_index) < len(prototypes) else None
        proto_prim = prim.GetStage().GetPrimAtPath(prototype_path) if prototype_path else None
        material_id = _bound_material_id(proto_prim, material_records, source_usd_path, repo_root) if proto_prim else None
        transform = _matrix_to_list(transforms[index]) if index < len(transforms) else None
        records.append(
            InstancerMappingRecord(
                instance_id=f"{prim.GetPath()}[{index}]",
                instancer_path=str(prim.GetPath()),
                prototype_id=prototype_path or f"prototype_{proto_index}",
                prototype_path=prototype_path,
                parent_id=str(prim.GetPath()),
                mesh_id=prototype_path,
                material_id=material_id,
                instance_index=index,
                transform=transform,
                visible=_imageable_visible(prim),
            )
        )
    return records


@dataclass
class ExtractedSnapshot:
    snapshot: SceneSnapshot
    geometry_payloads: dict[str, dict[str, Any]]


def extract_snapshot_from_stage(
    stage: Any,
    *,
    scene_id: str,
    frame_id: str,
    timestamp: str | None = None,
    usd_stage_path: str | None = None,
    source_usd_path: Path | None = None,
    repo_root: Path | None = None,
    time_codes: Iterable[float] | None = None,
    include_geometry_payloads: bool = True,
) -> ExtractedSnapshot:
    _, _, _, UsdGeom, _, _ = require_pxr()
    xform_cache = UsdGeom.XformCache()
    material_records: dict[str, MaterialRecord] = {}
    mesh_records: list[MeshRecord] = []
    camera_records: list[CameraRecord] = []
    light_records: list[LightRecord] = []
    pose_records: list[PoseRecord] = []
    instancer_mappings: list[InstancerMappingRecord] = []
    geometry_payloads: dict[str, dict[str, Any]] = {}
    pose_time_codes = _pose_time_codes(stage, time_codes)

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.PointInstancer):
            instancer_mappings.extend(
                _point_instancer_mappings(
                    prim, xform_cache, material_records, source_usd_path, repo_root, pose_time_codes[0],
                )
            )

        if prim.IsA(UsdGeom.Xformable):
            for time_code in pose_time_codes:
                if time_code is not None:
                    xform_cache.SetTime(time_code)
                pose_records.append(
                    PoseRecord(
                        prim_path=str(prim.GetPath()),
                        transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
                        time_code=time_code,
                        timestamp=timestamp,
                        visible=_imageable_visible(prim),
                    )
                )
            if pose_time_codes and pose_time_codes[0] is not None:
                xform_cache.SetTime(pose_time_codes[0])

        if prim.IsA(UsdGeom.Mesh):
            if not _is_renderable_mesh(prim):
                continue
            mesh = UsdGeom.Mesh(prim)
            geometry = mesh_geometry_payload(mesh) if include_geometry_payloads else {}
            material_id = _bound_material_id(prim, material_records, source_usd_path, repo_root)
            mesh_id = str(prim.GetPath())
            if geometry:
                geometry_payloads[mesh_id] = geometry
            mesh_records.append(
                MeshRecord(
                    mesh_id=mesh_id,
                    name=prim.GetName(),
                    source_path=mesh_id,
                    material_id=material_id,
                    primitive="mesh",
                    vertex_count=len(geometry.get("vertices", mesh.GetPointsAttr().Get() or [])),
                    face_count=len(geometry.get("faces", [])) if geometry else None,
                    normal_count=len(geometry.get("normals", [])) if geometry else None,
                    uv_count=len(geometry.get("uvs", [])) if geometry else None,
                    visible=_imageable_visible(prim),
                    transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
                    extras={"geometry": geometry} if geometry else {},
                )
            )
            continue

        if prim.IsA(UsdGeom.Camera):
            camera_records.append(_camera_record(prim, xform_cache))
            continue

        light = _light_record(prim, xform_cache, source_usd_path, repo_root)
        if light is not None:
            light_records.append(light)

    frame = FrameRecord(
        frame_id=frame_id,
        time_code=pose_time_codes[0],
        timestamp=timestamp,
        active_camera_id=camera_records[0].camera_id if camera_records else None,
        meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
        up_axis=str(UsdGeom.GetStageUpAxis(stage)),
    )
    snapshot = SceneSnapshot(
        scene_id=scene_id,
        frame=frame,
        meshes=mesh_records,
        materials=list(material_records.values()),
        cameras=camera_records,
        lights=light_records,
        pose_records=pose_records,
        instancer_mappings=instancer_mappings,
        reference_records=_reference_records(stage, source_usd_path, repo_root),
        usd_stage_path=usd_stage_path,
        robot_state=extract_robot_state(stage, xform_cache),
        package_metadata={
            "source": "usd_snapshot_v2",
            "geometry_payload_count": len(geometry_payloads),
        },
    )
    return ExtractedSnapshot(snapshot=snapshot, geometry_payloads=geometry_payloads)


def extract_snapshot_from_usd(
    usd_path: str,
    *,
    scene_id: str | None = None,
    frame_id: str = "frame_0",
    repo_root: str | Path | None = None,
    time_codes: Iterable[float] | None = None,
    include_geometry_payloads: bool = True,
) -> ExtractedSnapshot:
    source = Path(usd_path).resolve()
    root = Path(repo_root).resolve() if repo_root is not None else None
    stage = open_stage(str(source))
    return extract_snapshot_from_stage(
        stage,
        scene_id=scene_id or source.stem,
        frame_id=frame_id,
        usd_stage_path=_repo_rel_or_none(root, source),
        source_usd_path=source,
        repo_root=root,
        time_codes=time_codes,
        include_geometry_payloads=include_geometry_payloads,
    )
