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
from robomituba_bridge.types import CameraRecord, FrameRecord, LightRecord, MaterialRecord, MeshRecord, SceneSnapshot


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
    values: list[float] = []
    for row in range(4):
        for col in range(4):
            values.append(float(matrix[row][col]))
    return values


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


def extract_snapshot(
    stage,
    *,
    scene_id: str,
    frame_id: str,
    timestamp: str | None = None,
    usd_stage_path: str | None = None,
    source_usd_path: Path | None = None,
) -> SceneSnapshot:
    _, _, UsdGeom, UsdLux, UsdShade = _require_pxr()

    xform_cache = UsdGeom.XformCache()
    material_records: dict[str, MaterialRecord] = {}
    mesh_records: list[MeshRecord] = []
    camera_records: list[CameraRecord] = []
    light_records: list[LightRecord] = []

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get() or []
            counts = mesh.GetFaceVertexCountsAttr().Get() or []
            material_id = None
            bound = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
            material = _unwrap_connected_source(bound)
            if material:
                material_id = str(material.GetPath())
                if material_id not in material_records:
                    material_records[material_id] = _extract_material_record(material, source_usd_path)

            mesh_records.append(
                MeshRecord(
                    mesh_id=str(prim.GetPath()),
                    name=prim.GetName(),
                    source_path=str(prim.GetPath()),
                    material_id=material_id,
                    vertex_count=len(points),
                    face_count=_tri_face_count(list(counts)),
                    transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
                )
            )
            continue

        if prim.IsA(UsdGeom.Camera):
            camera = UsdGeom.Camera(prim)
            clip_range = camera.GetClippingRangeAttr().Get()
            camera_records.append(
                CameraRecord(
                    camera_id=str(prim.GetPath()),
                    name=prim.GetName(),
                    source_path=str(prim.GetPath()),
                    fov_deg=_fov_from_camera(camera),
                    clip_range=[float(clip_range[0]), float(clip_range[1])] if clip_range else None,
                    look_at=_extract_look_at(xform_cache.GetLocalToWorldTransform(prim)),
                    transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
                )
            )
            continue

        light_type = None
        radius = None
        size = None
        texture_path = None
        if prim.IsA(UsdLux.RectLight):
            light_type = "rectangle"
            rect = UsdLux.RectLight(prim)
            size = [float(rect.GetWidthAttr().Get() or 1.0), float(rect.GetHeightAttr().Get() or 1.0)]
        elif prim.IsA(UsdLux.SphereLight):
            light_type = "sphere"
            sphere = UsdLux.SphereLight(prim)
            radius = float(sphere.GetRadiusAttr().Get() or 0.5)
        elif prim.IsA(UsdLux.DomeLight):
            light_type = "envmap"
            dome = UsdLux.DomeLight(prim)
            texture_path = _resolve_asset_path(source_usd_path, dome.GetTextureFileAttr().Get())
        elif prim.IsA(UsdLux.DistantLight):
            light_type = "distant"
        elif prim.IsA(UsdLux.DiskLight):
            light_type = "disk"

        if light_type is None:
            continue

        light_api = UsdLux.LightAPI(prim)
        color = light_api.GetColorAttr().Get() if light_api else None
        intensity = light_api.GetIntensityAttr().Get() if light_api else None
        exposure = light_api.GetExposureAttr().Get() if light_api else None

        light_records.append(
            LightRecord(
                light_id=str(prim.GetPath()),
                name=prim.GetName(),
                source_path=str(prim.GetPath()),
                light_type=light_type,
                color=[float(color[0]), float(color[1]), float(color[2])] if color else None,
                intensity=float(intensity) if intensity is not None else None,
                exposure=float(exposure) if exposure is not None else None,
                radius=radius,
                size=size,
                texture_path=texture_path,
                transform=_matrix_to_list(xform_cache.GetLocalToWorldTransform(prim)),
            )
        )

    frame = FrameRecord(
        frame_id=frame_id,
        timestamp=timestamp,
        active_camera_id=camera_records[0].camera_id if camera_records else None,
        meters_per_unit=float(UsdGeom.GetStageMetersPerUnit(stage)),
        up_axis=str(UsdGeom.GetStageUpAxis(stage)),
    )
    return SceneSnapshot(
        scene_id=scene_id,
        frame=frame,
        meshes=mesh_records,
        materials=list(material_records.values()),
        cameras=camera_records,
        lights=light_records,
        usd_stage_path=usd_stage_path,
    )


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
