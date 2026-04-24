from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from collections import OrderedDict
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from robomituba_bridge import AssistLightSpec, BsdfOverride, DepthApproxSpec, SceneOverrideSpec


SUPPORTED_MODALITIES = (
    "rgb",
    "depth",
    "sensor_depth_approx",
    "albedo",
    "direct_light_map",
    "indirect_light_map",
    "diffuse_map",
    "specular_map",
    "active_nir_intensity",
    "polar_rgb_preview",
    "dop",
    "aolp",
    "s1",
    "s2",
)


MODALITY_DEFINITIONS = {
    "rgb": "Path-traced RGB radiance image.",
    "depth": "AOV depth distance from the pinhole.",
    "sensor_depth_approx": "Approximate active-sensor depth with reflective planar proxy corruption.",
    "albedo": "AOV diffuse reflectance approximation reported by Mitsuba.",
    "direct_light_map": "Path tracer with max_depth=2.",
    "indirect_light_map": "max(path_total - direct_light_map, 0).",
    "diffuse_map": "Path tracer with non-glass BSDFs converted to diffuse using original base colors.",
    "specular_map": "max(path_total - diffuse_map, 0).",
    "active_nir_intensity": "Camera-aligned active illumination grayscale proxy rendered under an assist light.",
    "polar_rgb_preview": "RGB preview image derived from the polarized Stokes render.",
    "dop": "Degree of polarization derived from luminance-weighted Stokes S0/S1/S2.",
    "aolp": "Angle of linear polarization in degrees derived from luminance-weighted Stokes S1/S2.",
    "s1": "Luminance-weighted Stokes S1 signed field.",
    "s2": "Luminance-weighted Stokes S2 signed field.",
    "polarization": "Stokes integrator with direct nested integrator, with pplastic fallback when needed.",
}

_PARSED_SCENE_CACHE: dict[tuple[str, int, int], ET.Element] = {}
_SCENE_TEMPLATE_CACHE: dict[tuple[tuple[str, int, int], str, tuple[Any, ...]], ET.Element] = {}
_RESIDENT_SCENE_CACHE: "OrderedDict[tuple[str, int, int, str], Any]" = OrderedDict()
_STAGED_SCENE_SIGNATURE_CACHE: dict[str, tuple[Any, ...]] = {}
_SCENE_CACHE_LOCK = threading.Lock()
_RESIDENT_SCENE_CACHE_LIMIT = 8


@dataclass
class RenderConfig:
    width: int = 768
    height: int = 576
    path_spp: int = 4096
    aov_spp: int = 16
    polar_spp: int = 256
    path_max_depth: int = 6
    direct_max_depth: int = 2
    rr_depth: int = 8
    samples_per_pass: int | None = None
    polar_scale_threshold: float = 1e-4
    artifact_stems: dict[str, str] = field(default_factory=dict)
    scene_filenames: dict[str, str] = field(default_factory=dict)

    def artifact_stem(self, modality: str, default: str) -> str:
        return self.artifact_stems.get(modality, default)

    def scene_filename(self, pass_name: str, default: str) -> str:
        return self.scene_filenames.get(pass_name, default)


@dataclass
class ModalityResult:
    name: str
    array: np.ndarray
    raw_channels: dict[str, np.ndarray] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "array_shape": list(self.array.shape),
            "array_dtype": str(self.array.dtype),
            "raw_channels": {
                key: {
                    "shape": list(value.shape),
                    "dtype": str(value.dtype),
                }
                for key, value in self.raw_channels.items()
            },
            "metadata": self.metadata,
            "timing": self.timing,
            "artifacts": self.artifacts,
        }


@dataclass
class MultimodalRenderResult:
    scene: dict[str, Any]
    camera: dict[str, Any]
    config: RenderConfig
    definitions: dict[str, str]
    results: dict[str, ModalityResult]
    pass_records: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "camera": self.camera,
            "config": asdict(self.config),
            "definitions": self.definitions,
            "results": {key: value.to_record() for key, value in self.results.items()},
            "pass_records": self.pass_records,
        }


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(data), indent=2), encoding="utf-8")


def extract_first_by_name(parent: ET.Element, tag: str, names: tuple[str, ...]) -> ET.Element | None:
    for node in parent.iter(tag):
        if node.attrib.get("name") in names:
            return node
    return None


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if norm < 1e-8:
        raise ValueError("Cannot normalize a near-zero vector")
    return v / norm


def normalize_mat4_storage(matrix: np.ndarray | Sequence[float]) -> np.ndarray:
    candidate = np.asarray(matrix, dtype=np.float32)
    if candidate.shape == (16,):
        candidate = candidate.reshape(4, 4)
    if candidate.shape != (4, 4):
        raise ValueError(f"Expected 4x4 transform matrix, got {candidate.shape}")
    last_col = candidate[:3, 3]
    last_row = candidate[3, :3]
    last_col_strength = float(np.linalg.norm(last_col))
    last_row_strength = float(np.linalg.norm(last_row))
    if last_row_strength > max(1e-5, last_col_strength * 2.0):
        candidate = candidate.T
    return candidate


def camera_to_world_from_lookat(
    origin: Sequence[float],
    target: Sequence[float],
    up: Sequence[float],
) -> np.ndarray:
    origin_v = np.asarray(origin, dtype=np.float32)
    target_v = np.asarray(target, dtype=np.float32)
    up_v = np.asarray(up, dtype=np.float32)

    forward = _normalize(target_v - origin_v)
    right = _normalize(np.cross(forward, up_v))
    true_up = _normalize(np.cross(right, forward))

    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, 0] = right
    matrix[:3, 1] = true_up
    matrix[:3, 2] = -forward
    matrix[:3, 3] = origin_v
    return matrix


def camera_to_world_to_lookat(camera_to_world: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = normalize_mat4_storage(camera_to_world)

    origin = matrix[:3, 3]
    up = _normalize(matrix[:3, 1])
    forward = _normalize(-matrix[:3, 2])
    target = origin + forward
    return origin, target, up


def _parse_vec3(value: str) -> np.ndarray:
    return np.asarray([float(part) for part in value.replace(" ", "").split(",")], dtype=np.float32)


def _parse_matrix_value(value: str) -> np.ndarray:
    parts = [float(part) for part in value.replace(",", " ").split()]
    if len(parts) != 16:
        raise ValueError(f"Expected 16 matrix values, got {len(parts)}")
    return np.asarray(parts, dtype=np.float32).reshape(4, 4)


def extract_camera_from_scene(scene_xml: str | Path) -> tuple[np.ndarray, float]:
    root = ET.parse(scene_xml).getroot()
    sensor = root.find("./sensor")
    if sensor is None:
        raise RuntimeError("Scene has no sensor node")

    transform = sensor.find("./transform[@name='to_world']")
    if transform is None:
        raise RuntimeError("Scene has no sensor to_world transform")

    lookat = transform.find("./lookat")
    matrix_node = transform.find("./matrix")
    if lookat is not None:
        camera_to_world = camera_to_world_from_lookat(
            _parse_vec3(lookat.attrib["origin"]),
            _parse_vec3(lookat.attrib["target"]),
            _parse_vec3(lookat.attrib["up"]),
        )
    elif matrix_node is not None and "value" in matrix_node.attrib:
        camera_to_world = _parse_matrix_value(matrix_node.attrib["value"])
    else:
        raise RuntimeError("Unsupported sensor transform: expected lookat or matrix")

    fov = sensor.find("./float[@name='fov']")
    if fov is None:
        raise RuntimeError("Scene has no sensor fov")
    return camera_to_world, float(fov.attrib["value"])


def _scene_cache_key(scene_path: Path) -> tuple[str, int, int]:
    resolved = scene_path.resolve()
    stat = resolved.stat()
    return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))


def _clone_scene_root(root: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(root, encoding="unicode"))


def _parse_scene_uncached(scene_path: Path) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    return ET.parse(scene_path, parser=parser).getroot()


def _parse_scene(scene_path: Path) -> ET.Element:
    cache_key = _scene_cache_key(scene_path)
    with _SCENE_CACHE_LOCK:
        cached = _PARSED_SCENE_CACHE.get(cache_key)
    if cached is None:
        parsed = _parse_scene_uncached(scene_path)
        with _SCENE_CACHE_LOCK:
            _PARSED_SCENE_CACHE[cache_key] = _clone_scene_root(parsed)
        return parsed
    return _clone_scene_root(cached)


def _scene_template(
    scene_path: Path,
    *,
    branch_kind: str,
    branch_signature: Sequence[Any],
    builder: Callable[[ET.Element], None],
) -> ET.Element:
    scene_key = _scene_cache_key(scene_path)
    template_key = (scene_key, branch_kind, tuple(branch_signature))
    with _SCENE_CACHE_LOCK:
        cached = _SCENE_TEMPLATE_CACHE.get(template_key)
    if cached is None:
        root = _parse_scene(scene_path)
        builder(root)
        with _SCENE_CACHE_LOCK:
            _SCENE_TEMPLATE_CACHE[template_key] = _clone_scene_root(root)
        return root
    return _clone_scene_root(cached)


def _normalize_signature_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return round(float(value), 6)
    if isinstance(value, np.ndarray):
        return tuple(_normalize_signature_value(item) for item in np.asarray(value).reshape(-1).tolist())
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _normalize_signature_value(val))
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple, set)):
        return tuple(_normalize_signature_value(item) for item in value)
    if hasattr(value, "__dict__"):
        return _normalize_signature_value(vars(value))
    return repr(value)


def _camera_signature(camera_to_world: np.ndarray, *, fov_deg: float, spp: int, width: int, height: int) -> tuple[Any, ...]:
    matrix = normalize_mat4_storage(camera_to_world).reshape(-1).tolist()
    return (
        tuple(round(float(item), 6) for item in matrix),
        round(float(fov_deg), 6),
        int(spp),
        int(width),
        int(height),
    )


def _scene_override_signature(scene_override: SceneOverrideSpec | None) -> Any:
    if scene_override is None:
        return None
    return _normalize_signature_value(
        {
            "target_shape_filenames": list(scene_override.target_shape_filenames),
            "material_profile": scene_override.material_profile,
            "bsdf_overrides": scene_override.bsdf_overrides,
            "transform_overrides": scene_override.transform_overrides,
            "prim_to_shape_ids": scene_override.prim_to_shape_ids,
            "extras": scene_override.extras,
        }
    )


def _assist_light_signature(assist_light: AssistLightSpec | None) -> Any:
    if assist_light is None:
        return None
    return _normalize_signature_value(asdict(assist_light))


def _should_reuse_staged_scene(out_scene: Path, *, signature: tuple[Any, ...]) -> bool:
    cache_key = str(out_scene.resolve())
    with _SCENE_CACHE_LOCK:
        cached_signature = _STAGED_SCENE_SIGNATURE_CACHE.get(cache_key)
    return cached_signature == signature and out_scene.exists()


def _record_staged_scene_signature(out_scene: Path, *, signature: tuple[Any, ...]) -> None:
    cache_key = str(out_scene.resolve())
    with _SCENE_CACHE_LOCK:
        _STAGED_SCENE_SIGNATURE_CACHE[cache_key] = signature


def _write_scene(root: ET.Element, out_scene: Path) -> Path:
    ET.indent(root, space="  ")
    scene_text = ET.tostring(root, encoding="unicode")
    if out_scene.exists():
        try:
            if out_scene.read_text(encoding="utf-8") == scene_text:
                return out_scene
        except OSError:
            pass
    out_scene.write_text(scene_text, encoding="utf-8")
    return out_scene


def _shape_filename_value(shape: ET.Element) -> str | None:
    filename = shape.find("string[@name='filename']")
    if filename is None:
        return None
    return filename.attrib.get("value")


def _shape_basename(shape: ET.Element) -> str | None:
    value = _shape_filename_value(shape)
    if value is None:
        return None
    return Path(value).name


def _target_name_set(target_shape_filenames: Sequence[str] | None) -> set[str]:
    return {Path(item).name for item in (target_shape_filenames or [])}


def _shape_matches_targets(shape: ET.Element, targets: set[str]) -> bool:
    basename = _shape_basename(shape)
    return basename in targets if basename is not None else False


def _remove_children(shape: ET.Element, tag: str) -> None:
    for child in list(shape.findall(f"./{tag}")):
        shape.remove(child)


def _remove_all_emitters(root: ET.Element) -> None:
    for emitter in list(root.findall("./emitter")):
        root.remove(emitter)
    for shape in root.findall("./shape"):
        _remove_children(shape, "emitter")


def _identity_matrix() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def _matrix_to_string(matrix: np.ndarray) -> str:
    return " ".join(f"{float(value):.9f}" for value in np.asarray(matrix, dtype=np.float32).reshape(-1))


def _shape_matrix(shape: ET.Element) -> np.ndarray:
    transform = shape.find("./transform[@name='to_world']")
    if transform is None:
        return _identity_matrix()

    matrix_node = transform.find("./matrix")
    if matrix_node is not None and "value" in matrix_node.attrib:
        return _parse_matrix_value(matrix_node.attrib["value"])

    matrix = _identity_matrix()
    for child in list(transform):
        tag = child.tag
        if tag == "translate":
            translation = np.eye(4, dtype=np.float32)
            translation[0, 3] = float(child.attrib.get("x", "0"))
            translation[1, 3] = float(child.attrib.get("y", "0"))
            translation[2, 3] = float(child.attrib.get("z", "0"))
            matrix = matrix @ translation
        elif tag == "scale":
            scale = np.eye(4, dtype=np.float32)
            if "value" in child.attrib:
                value = float(child.attrib["value"])
                scale[0, 0] = value
                scale[1, 1] = value
                scale[2, 2] = value
            else:
                scale[0, 0] = float(child.attrib.get("x", "1"))
                scale[1, 1] = float(child.attrib.get("y", "1"))
                scale[2, 2] = float(child.attrib.get("z", "1"))
            matrix = matrix @ scale
    return matrix


def _load_obj_bounds(path: Path) -> tuple[np.ndarray, np.ndarray]:
    bounds_min = None
    bounds_max = None
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            point = np.asarray([float(parts[1]), float(parts[2]), float(parts[3])], dtype=np.float32)
            bounds_min = point.copy() if bounds_min is None else np.minimum(bounds_min, point)
            bounds_max = point.copy() if bounds_max is None else np.maximum(bounds_max, point)
    if bounds_min is None or bounds_max is None:
        raise RuntimeError(f"OBJ has no vertices: {path}")
    return bounds_min, bounds_max


def _transform_bounds(bounds_min: np.ndarray, bounds_max: np.ndarray, matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    corners = np.asarray(
        [
            [x, y, z, 1.0]
            for x in (bounds_min[0], bounds_max[0])
            for y in (bounds_min[1], bounds_max[1])
            for z in (bounds_min[2], bounds_max[2])
        ],
        dtype=np.float32,
    )
    transformed = corners @ np.asarray(matrix, dtype=np.float32).T
    xyz = transformed[:, :3] / np.maximum(transformed[:, 3:4], 1e-8)
    return xyz.min(axis=0), xyz.max(axis=0)


def _project_bounds_to_image_bbox(
    bounds_min: np.ndarray,
    bounds_max: np.ndarray,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    corners = np.asarray(
        [
            [x, y, z, 1.0]
            for x in (bounds_min[0], bounds_max[0])
            for y in (bounds_min[1], bounds_max[1])
            for z in (bounds_min[2], bounds_max[2])
        ],
        dtype=np.float32,
    )
    world_to_camera = np.linalg.inv(np.asarray(camera_to_world, dtype=np.float32))
    camera_corners = corners @ world_to_camera.T
    z = camera_corners[:, 2]
    in_front = z < -1e-4
    if not np.any(in_front):
        return None

    camera_corners = camera_corners[in_front]
    aspect = float(width) / max(float(height), 1.0)
    tan_half_x = np.tan(np.deg2rad(float(fov_deg)) * 0.5)
    tan_half_y = tan_half_x / max(aspect, 1e-6)
    x_ndc = (camera_corners[:, 0] / -camera_corners[:, 2]) / max(tan_half_x, 1e-6)
    y_ndc = (camera_corners[:, 1] / -camera_corners[:, 2]) / max(tan_half_y, 1e-6)

    x_px = ((x_ndc * 0.5) + 0.5) * float(width)
    y_px = ((-y_ndc * 0.5) + 0.5) * float(height)
    x0 = max(0, min(width - 1, int(np.floor(np.min(x_px))) - 6))
    y0 = max(0, min(height - 1, int(np.floor(np.min(y_px))) - 6))
    x1 = max(x0 + 1, min(width, int(np.ceil(np.max(x_px))) + 6))
    y1 = max(y0 + 1, min(height, int(np.ceil(np.max(y_px))) + 6))
    return x0, y0, x1, y1


def _compute_target_union_bounds(scene_path: Path, targets: set[str]) -> tuple[np.ndarray, np.ndarray] | None:
    root = _parse_scene(scene_path)
    bounds_min = None
    bounds_max = None
    for shape in root.findall("./shape"):
        if not _shape_matches_targets(shape, targets):
            continue
        filename = _shape_filename_value(shape)
        if filename is None:
            continue
        obj_path = Path(filename)
        if not obj_path.exists():
            continue
        local_min, local_max = _load_obj_bounds(obj_path)
        world_min, world_max = _transform_bounds(local_min, local_max, _shape_matrix(shape))
        bounds_min = world_min.copy() if bounds_min is None else np.minimum(bounds_min, world_min)
        bounds_max = world_max.copy() if bounds_max is None else np.maximum(bounds_max, world_max)
    if bounds_min is None or bounds_max is None:
        return None
    return bounds_min, bounds_max


def _camera_basis(camera_to_world: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    matrix = normalize_mat4_storage(camera_to_world)
    origin = matrix[:3, 3]
    right = _normalize(matrix[:3, 0])
    up = _normalize(matrix[:3, 1])
    forward = _normalize(-matrix[:3, 2])
    return origin, right, up, forward


def _set_principled_bsdf(
    shape: ET.Element,
    *,
    base_color: tuple[float, float, float],
    roughness: float,
    metallic: float,
) -> None:
    _remove_children(shape, "bsdf")
    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    principled = ET.SubElement(twosided, "bsdf", {"type": "principled"})
    ET.SubElement(
        principled,
        "rgb",
        {
            "name": "base_color",
            "value": ",".join(f"{float(value):.4f}" for value in base_color),
        },
    )
    ET.SubElement(principled, "float", {"name": "roughness", "value": f"{float(roughness):.4f}"})
    ET.SubElement(principled, "float", {"name": "metallic", "value": f"{float(metallic):.4f}"})


def _set_roughplastic_bsdf(
    shape: ET.Element,
    *,
    diffuse_reflectance: tuple[float, float, float],
    alpha: float,
    int_ior: float,
) -> None:
    _remove_children(shape, "bsdf")
    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    roughplastic = ET.SubElement(twosided, "bsdf", {"type": "roughplastic"})
    ET.SubElement(roughplastic, "string", {"name": "distribution", "value": "ggx"})
    ET.SubElement(
        roughplastic,
        "rgb",
        {
            "name": "diffuse_reflectance",
            "value": ",".join(f"{float(value):.4f}" for value in diffuse_reflectance),
        },
    )
    ET.SubElement(roughplastic, "float", {"name": "alpha", "value": f"{float(alpha):.4f}"})
    ET.SubElement(roughplastic, "float", {"name": "int_ior", "value": f"{float(int_ior):.4f}"})
    ET.SubElement(roughplastic, "float", {"name": "ext_ior", "value": "1.0000"})


def _set_roughconductor_bsdf(
    shape: ET.Element,
    *,
    alpha: float,
) -> None:
    _remove_children(shape, "bsdf")
    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    roughconductor = ET.SubElement(twosided, "bsdf", {"type": "roughconductor"})
    ET.SubElement(roughconductor, "string", {"name": "distribution", "value": "ggx"})
    ET.SubElement(roughconductor, "float", {"name": "alpha", "value": f"{float(alpha):.4f}"})


def _set_pplastic_bsdf(
    shape: ET.Element,
    *,
    diffuse_reflectance: tuple[float, float, float],
    alpha: float,
    int_ior: float,
) -> None:
    _remove_children(shape, "bsdf")
    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    pplastic = ET.SubElement(twosided, "bsdf", {"type": "pplastic"})
    ET.SubElement(
        pplastic,
        "rgb",
        {
            "name": "diffuse_reflectance",
            "value": ",".join(f"{float(value):.4f}" for value in diffuse_reflectance),
        },
    )
    ET.SubElement(pplastic, "float", {"name": "alpha", "value": f"{float(alpha):.4f}"})
    ET.SubElement(pplastic, "float", {"name": "int_ior", "value": f"{float(int_ior):.4f}"})
    ET.SubElement(pplastic, "float", {"name": "ext_ior", "value": "1.0000"})


def _set_diffuse_bsdf(shape: ET.Element, *, reflectance: tuple[float, float, float]) -> None:
    _remove_children(shape, "bsdf")
    diffuse = ET.SubElement(shape, "bsdf", {"type": "diffuse"})
    ET.SubElement(
        diffuse,
        "rgb",
        {
            "name": "reflectance",
            "value": ",".join(f"{float(value):.4f}" for value in reflectance),
        },
    )


def _set_twosided_diffuse_bsdf(shape: ET.Element, *, reflectance: tuple[float, float, float]) -> None:
    _remove_children(shape, "bsdf")
    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    diffuse = ET.SubElement(twosided, "bsdf", {"type": "diffuse"})
    ET.SubElement(
        diffuse,
        "rgb",
        {
            "name": "reflectance",
            "value": ",".join(f"{float(value):.4f}" for value in reflectance),
        },
    )


def _shape_matches_prim_path(shape: ET.Element, prim_path: str) -> bool:
    """Check if shape matches the given USD prim path.

    Matches by comparing shape ID or filename to the last component of prim_path.
    Example: prim_path="/World/Table" matches shape with id="Table" or filename="Table.obj"
    """
    shape_id = shape.attrib.get("id", "")
    prim_name = prim_path.rstrip("/").split("/")[-1] if prim_path else ""

    # Direct ID match
    if shape_id == prim_name:
        return True

    # Filename match
    basename = _shape_basename(shape)
    if basename is not None:
        # Check if the filename (without extension) matches the prim name
        filename_stem = Path(basename).stem
        if filename_stem == prim_name:
            return True

    return False


def _shape_index_by_id(root: ET.Element) -> dict[str, ET.Element]:
    indexed: dict[str, ET.Element] = {}
    for shape in root.findall("./shape"):
        shape_id = shape.attrib.get("id")
        if shape_id:
            indexed[shape_id] = shape
    return indexed


def _shapes_for_prim_path(
    root: ET.Element,
    prim_path: str,
    *,
    scene_override: SceneOverrideSpec,
    shape_index: dict[str, ET.Element] | None = None,
) -> list[ET.Element]:
    explicit_ids = scene_override.prim_to_shape_ids.get(prim_path, [])
    if explicit_ids:
        index = shape_index or _shape_index_by_id(root)
        return [index[shape_id] for shape_id in explicit_ids if shape_id in index]

    if not scene_override.extras.get("allow_heuristic_shape_matching", False):
        return []

    return [shape for shape in root.findall("./shape") if _shape_matches_prim_path(shape, prim_path)]


def _apply_bsdf_override(shape: ET.Element, bsdf_override: BsdfOverride, *, mode: str) -> None:
    """Apply BSDF override to a shape based on type and parameters.

    Handles different BSDF types: diffuse, conductor, roughplastic, dielectric, roughconductor, principled
    """
    bsdf_type = (bsdf_override.bsdf_type or "diffuse").strip().lower()

    # Use provided colors or sensible defaults
    base_color = tuple(bsdf_override.base_color) if bsdf_override.base_color else (0.5, 0.5, 0.5)
    roughness = float(bsdf_override.roughness) if bsdf_override.roughness is not None else 0.5
    metallic = float(bsdf_override.metallic) if bsdf_override.metallic is not None else 0.0
    ior = float(bsdf_override.ior) if bsdf_override.ior is not None else 1.5

    if bsdf_type == "diffuse":
        _set_diffuse_bsdf(shape, reflectance=base_color)
    elif bsdf_type == "pplastic":
        _set_pplastic_bsdf(
            shape,
            diffuse_reflectance=base_color,
            alpha=max(roughness, 0.01),
            int_ior=ior,
        )
    elif bsdf_type == "roughplastic":
        _set_roughplastic_bsdf(
            shape,
            diffuse_reflectance=base_color,
            alpha=roughness,
            int_ior=ior,
        )
    elif bsdf_type == "glossy_black_lacquer":
        _set_principled_bsdf(
            shape,
            base_color=base_color if bsdf_override.base_color is not None else (0.03, 0.03, 0.035),
            roughness=roughness if bsdf_override.roughness is not None else 0.03,
            metallic=0.0,
        )
    elif bsdf_type in {"mirror_black_enamel", "high_reflect_black"}:
        _set_roughconductor_bsdf(shape, alpha=roughness if bsdf_override.roughness is not None else 0.0012)
    elif bsdf_type == "conductor":
        # Conductor BSDF - use material name if provided
        _set_roughconductor_bsdf(shape, alpha=roughness)
    elif bsdf_type == "roughconductor":
        _set_roughconductor_bsdf(shape, alpha=roughness)
    elif bsdf_type == "dielectric":
        # For dielectric, use principled as fallback with high opacity
        _set_principled_bsdf(
            shape,
            base_color=base_color,
            roughness=roughness,
            metallic=0.0,
        )
    elif bsdf_type == "principled":
        _set_principled_bsdf(
            shape,
            base_color=base_color,
            roughness=roughness,
            metallic=metallic,
        )
    else:
        # Default to roughplastic for unknown types
        _set_roughplastic_bsdf(
            shape,
            diffuse_reflectance=base_color,
            alpha=roughness,
            int_ior=ior,
        )


def _set_shape_transform(shape: ET.Element, mat4: list[float]) -> None:
    """Set the shape's world transform from a 16-element Mat4 list (column-major).

    Replaces or creates the shape's to_world transform element.
    """
    if not mat4 or len(mat4) != 16:
        return

    transform = shape.find("./transform[@name='to_world']")
    if transform is None:
        transform = ET.SubElement(shape, "transform", {"name": "to_world"})
    else:
        # Clear existing children
        for child in list(transform):
            transform.remove(child)

    # Convert Mat4 list to matrix string (column-major format)
    matrix_value = _matrix_to_string(np.array(mat4, dtype=np.float32).reshape(4, 4))
    ET.SubElement(transform, "matrix", {"value": matrix_value})


def _apply_scene_override(root: ET.Element, scene_override: SceneOverrideSpec | None, *, mode: str) -> None:
    if scene_override is None:
        return

    shape_index = _shape_index_by_id(root)

    # Process dynamic BSDF overrides (prim_path → BsdfOverride)
    if scene_override.bsdf_overrides:
        for prim_path, bsdf_override in scene_override.bsdf_overrides.items():
            for shape in _shapes_for_prim_path(root, prim_path, scene_override=scene_override, shape_index=shape_index):
                _apply_bsdf_override(shape, bsdf_override, mode=mode)

    # Process dynamic transform overrides (prim_path → Mat4)
    if scene_override.transform_overrides:
        for prim_path, mat4 in scene_override.transform_overrides.items():
            for shape in _shapes_for_prim_path(root, prim_path, scene_override=scene_override, shape_index=shape_index):
                _set_shape_transform(shape, mat4)

    # Process preset-based overrides (backward compatibility)
    targets = _target_name_set(scene_override.target_shape_filenames)
    profile = (scene_override.material_profile or "glossy_black_lacquer").strip().lower()
    for shape in root.findall("./shape"):
        if not _shape_matches_targets(shape, targets):
            continue
        if mode == "polar":
            alpha = 0.03
            int_ior = 1.5
            diffuse_reflectance = (0.045, 0.045, 0.045)
            if profile in {"glossy_black_lacquer", "mirror_black_enamel", "high_reflect_black"}:
                # Keep the surface dark, but make the specular lobe tight enough that
                # the active-light polarized branch produces a stronger S1 response.
                diffuse_reflectance = (0.032, 0.032, 0.035)
                alpha = 0.0045
                int_ior = 1.78
            _set_pplastic_bsdf(
                shape,
                diffuse_reflectance=diffuse_reflectance,
                alpha=alpha,
                int_ior=int_ior,
            )
        else:
            base_color = (0.03, 0.03, 0.035)
            roughness = 0.03
            metallic = 0.0
            if profile in {"glossy_black_lacquer", "mirror_black_enamel", "high_reflect_black"}:
                # The demo needs stronger cabinet reflections than a physically
                # plausible black lacquer would produce. Use a very smooth rough
                # conductor so nearby furniture reads clearly in the surface.
                _set_roughconductor_bsdf(shape, alpha=0.0012)
            else:
                _set_principled_bsdf(
                    shape,
                    base_color=base_color,
                    roughness=roughness,
                    metallic=metallic,
                )


def _camera_aligned_rectangle_matrix(
    camera_to_world: np.ndarray,
    *,
    distance_m: float,
    size_world: Sequence[float],
    roll_deg: float = 0.0,
) -> np.ndarray:
    origin, right, up, forward = _camera_basis(camera_to_world)
    if abs(float(roll_deg)) > 1e-6:
        angle = np.deg2rad(float(roll_deg))
        right_rolled = _normalize(right * np.cos(angle) + up * np.sin(angle))
        up_rolled = _normalize(-right * np.sin(angle) + up * np.cos(angle))
    else:
        right_rolled = right
        up_rolled = up
    center = origin - forward * float(distance_m)
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, 0] = right_rolled * (float(size_world[0]) * 0.5)
    matrix[:3, 1] = up_rolled * (float(size_world[1]) * 0.5)
    matrix[:3, 2] = forward
    matrix[:3, 3] = center
    return matrix


def _append_camera_assist_light(
    root: ET.Element,
    camera_to_world: np.ndarray,
    assist_light: AssistLightSpec,
    *,
    polarized: bool,
) -> None:
    default_radiance = 18.0 if polarized else 14.0
    radiance = float(assist_light.extras.get("radiance", default_radiance))
    light_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": "camera_assist_light"})
    transform = ET.SubElement(light_shape, "transform", {"name": "to_world"})
    ET.SubElement(
        transform,
        "matrix",
        {
            "value": _matrix_to_string(
                _camera_aligned_rectangle_matrix(
                    camera_to_world,
                    distance_m=assist_light.distance_m,
                    size_world=assist_light.size_world,
                )
            ),
        },
    )
    ET.SubElement(light_shape, "bsdf", {"type": "null"})
    emitter = ET.SubElement(light_shape, "emitter", {"type": "area"})
    ET.SubElement(emitter, "rgb", {"name": "radiance", "value": f"{radiance:.4f},{radiance:.4f},{radiance:.4f}"})

    if not polarized:
        return

    polar_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": "camera_assist_polarizer"})
    polar_transform = ET.SubElement(polar_shape, "transform", {"name": "to_world"})
    ET.SubElement(
        polar_transform,
        "matrix",
        {
            "value": _matrix_to_string(
                _camera_aligned_rectangle_matrix(
                    camera_to_world,
                    distance_m=assist_light.distance_m + 0.01,
                    size_world=assist_light.size_world,
                    roll_deg=assist_light.polarizer_angle_deg,
                )
            ),
        },
    )
    ET.SubElement(polar_shape, "bsdf", {"type": "polarizer"})

def _update_sensor(
    root: ET.Element,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
) -> None:
    sensor = root.find("./sensor")
    if sensor is None:
        raise RuntimeError("Scene has no sensor")

    sampler = sensor.find("./sampler")
    if sampler is None:
        raise RuntimeError("Scene has no sensor sampler")
    sample_count_node = sampler.find("./integer[@name='sample_count']")
    if sample_count_node is None:
        sample_count_node = ET.SubElement(sampler, "integer", {"name": "sample_count"})
    sample_count_node.attrib["value"] = str(spp)

    film = sensor.find("./film")
    if film is not None:
        width_node = film.find("./integer[@name='width']")
        height_node = film.find("./integer[@name='height']")
        if width_node is None:
            width_node = ET.SubElement(film, "integer", {"name": "width"})
        if height_node is None:
            height_node = ET.SubElement(film, "integer", {"name": "height"})
        width_node.attrib["value"] = str(width)
        height_node.attrib["value"] = str(height)

    fov_node = sensor.find("./float[@name='fov']")
    if fov_node is None:
        fov_node = ET.SubElement(sensor, "float", {"name": "fov"})
    fov_node.attrib["value"] = f"{float(fov_deg):.9f}"

    transform = sensor.find("./transform[@name='to_world']")
    if transform is None:
        transform = ET.SubElement(sensor, "transform", {"name": "to_world"})
    for child in list(transform):
        transform.remove(child)
    origin, target, up = camera_to_world_to_lookat(camera_to_world)
    ET.SubElement(
        transform,
        "lookat",
        {
            "origin": ",".join(f"{v:.9f}" for v in origin),
            "target": ",".join(f"{v:.9f}" for v in target),
            "up": ",".join(f"{v:.9f}" for v in up),
        },
    )


def _configure_path_integrator(
    integrator: ET.Element,
    *,
    integrator_type: str,
    max_depth: int,
    rr_depth: int,
    samples_per_pass: int | None,
) -> None:
    integrator.attrib["type"] = integrator_type
    for child in list(integrator):
        integrator.remove(child)
    ET.SubElement(integrator, "integer", {"name": "max_depth", "value": str(max_depth)})
    ET.SubElement(integrator, "integer", {"name": "rr_depth", "value": str(rr_depth)})
    if samples_per_pass is not None and samples_per_pass > 0:
        ET.SubElement(integrator, "integer", {"name": "samples_per_pass", "value": str(samples_per_pass)})


def _stage_path_scene(
    scene_path: Path,
    out_scene: Path,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
    max_depth: int,
    rr_depth: int,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
    integrator_type: str = "path",
) -> Path:
    stage_signature = (
        "path",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (integrator_type, int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    def _build_template(root: ET.Element) -> None:
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        _configure_path_integrator(
            integrator,
            integrator_type=integrator_type,
            max_depth=max_depth,
            rr_depth=rr_depth,
            samples_per_pass=samples_per_pass,
        )

    root = _scene_template(
        scene_path,
        branch_kind="path",
        branch_signature=(integrator_type, int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        builder=_build_template,
    )
    _update_sensor(
        root,
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        spp=spp,
        width=width,
        height=height,
    )
    _apply_scene_override(root, scene_override, mode="rgb")
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=False)
    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _stage_aov_scene(
    scene_path: Path,
    out_scene: Path,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
) -> Path:
    stage_signature = (
        "aov",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    def _build_template(root: ET.Element) -> None:
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        integrator.attrib["type"] = "aov"
        for child in list(integrator):
            integrator.remove(child)
        ET.SubElement(integrator, "string", {"name": "aovs", "value": "ab:albedo,dd:depth"})
        ET.SubElement(integrator, "integrator", {"type": "direct", "name": "img"})

    root = _scene_template(
        scene_path,
        branch_kind="aov",
        branch_signature=(),
        builder=_build_template,
    )
    _update_sensor(
        root,
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        spp=spp,
        width=width,
        height=height,
    )
    _apply_scene_override(root, scene_override, mode="rgb")
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=False)
    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _stage_stokes_scene(
    scene_path: Path,
    out_scene: Path,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
    nested_integrator_type: str = "direct",
) -> Path:
    stage_signature = (
        "stokes",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (nested_integrator_type, int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    def _build_template(root: ET.Element) -> None:
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        integrator.attrib["type"] = "stokes"
        for child in list(integrator):
            integrator.remove(child)
        if samples_per_pass is not None and samples_per_pass > 0:
            ET.SubElement(integrator, "integer", {"name": "samples_per_pass", "value": str(samples_per_pass)})
        ET.SubElement(integrator, "integrator", {"type": nested_integrator_type})

    root = _scene_template(
        scene_path,
        branch_kind="stokes",
        branch_signature=(nested_integrator_type, int(samples_per_pass or 0)),
        builder=_build_template,
    )
    _update_sensor(
        root,
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        spp=spp,
        width=width,
        height=height,
    )
    _apply_scene_override(root, scene_override, mode="polar")
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=assist_light.polarized)
    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _stage_diffuse_override_scene(
    scene_path: Path,
    out_scene: Path,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
    max_depth: int,
    rr_depth: int,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
) -> Path:
    stage_signature = (
        "diffuse_override",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    def _build_template(root: ET.Element) -> None:
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        _configure_path_integrator(
            integrator,
            integrator_type="path",
            max_depth=max_depth,
            rr_depth=rr_depth,
            samples_per_pass=samples_per_pass,
        )

        for shape in root.findall("./shape"):
            filename = shape.find("string[@name='filename']")
            if filename is None:
                continue
            obj_name = Path(filename.attrib["value"]).name.lower()
            old_bsdf = shape.find("./bsdf")
            if old_bsdf is not None:
                shape.remove(old_bsdf)

            if "glass" in obj_name:
                bsdf = ET.SubElement(shape, "bsdf", {"type": "roughdielectric"})
                ET.SubElement(bsdf, "float", {"name": "alpha", "value": "0.02"})
                ET.SubElement(bsdf, "float", {"name": "int_ior", "value": "1.5"})
                ET.SubElement(bsdf, "float", {"name": "ext_ior", "value": "1.0"})
                continue

            twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
            diffuse = ET.SubElement(twosided, "bsdf", {"type": "diffuse"})

            base_tex = None
            base_rgb = None
            if old_bsdf is not None:
                base_tex = extract_first_by_name(old_bsdf, "texture", ("base_color", "diffuse_reflectance"))
                base_rgb = extract_first_by_name(old_bsdf, "rgb", ("base_color", "reflectance", "diffuse_reflectance"))

            if base_tex is not None:
                tex = ET.SubElement(
                    diffuse,
                    "texture",
                    {
                        "type": base_tex.attrib.get("type", "bitmap"),
                        "name": "reflectance",
                    },
                )
                for key, value in base_tex.attrib.items():
                    if key not in ("type", "name"):
                        tex.attrib[key] = value
                for child in list(base_tex):
                    tex.append(child)
            elif base_rgb is not None:
                ET.SubElement(
                    diffuse,
                    "rgb",
                    {
                        "name": "reflectance",
                        "value": base_rgb.attrib.get("value", "0.75,0.75,0.75"),
                    },
                )
            else:
                ET.SubElement(diffuse, "rgb", {"name": "reflectance", "value": "0.75,0.75,0.75"})

    root = _scene_template(
        scene_path,
        branch_kind="diffuse_override",
        branch_signature=(int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        builder=_build_template,
    )
    _update_sensor(
        root,
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        spp=spp,
        width=width,
        height=height,
    )
    _apply_scene_override(root, scene_override, mode="rgb")
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=False)

    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _stage_polarized_fallback_scene(
    scene_path: Path,
    out_scene: Path,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
    nested_integrator_type: str = "direct",
) -> Path:
    stage_signature = (
        "polarized_fallback",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (nested_integrator_type, int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    def _build_template(root: ET.Element) -> None:
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        integrator.attrib["type"] = "stokes"
        for child in list(integrator):
            integrator.remove(child)
        if samples_per_pass is not None and samples_per_pass > 0:
            ET.SubElement(integrator, "integer", {"name": "samples_per_pass", "value": str(samples_per_pass)})
        ET.SubElement(integrator, "integrator", {"type": nested_integrator_type})

        for shape in root.findall("./shape"):
            filename = shape.find("string[@name='filename']")
            if filename is None:
                continue
            obj_name = Path(filename.attrib["value"]).name.lower()
            old_bsdf = shape.find("./bsdf")
            if old_bsdf is not None:
                shape.remove(old_bsdf)

            if "glass" in obj_name:
                bsdf = ET.SubElement(shape, "bsdf", {"type": "roughdielectric"})
                ET.SubElement(bsdf, "float", {"name": "alpha", "value": "0.02"})
                ET.SubElement(bsdf, "float", {"name": "int_ior", "value": "1.5"})
                ET.SubElement(bsdf, "float", {"name": "ext_ior", "value": "1.0"})
                continue

            twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
            pplastic = ET.SubElement(twosided, "bsdf", {"type": "pplastic"})

            base_tex = None
            base_rgb = None
            roughness = None
            if old_bsdf is not None:
                base_tex = extract_first_by_name(old_bsdf, "texture", ("base_color", "diffuse_reflectance"))
                base_rgb = extract_first_by_name(old_bsdf, "rgb", ("base_color", "reflectance", "diffuse_reflectance"))
                roughness = extract_first_by_name(old_bsdf, "float", ("roughness", "alpha"))

            if base_tex is not None:
                tex = ET.SubElement(
                    pplastic,
                    "texture",
                    {
                        "type": base_tex.attrib.get("type", "bitmap"),
                        "name": "diffuse_reflectance",
                    },
                )
                for child in list(base_tex):
                    tex.append(child)
                for key, value in base_tex.attrib.items():
                    if key not in ("type", "name"):
                        tex.attrib[key] = value
            elif base_rgb is not None:
                ET.SubElement(
                    pplastic,
                    "rgb",
                    {
                        "name": "diffuse_reflectance",
                        "value": base_rgb.attrib.get("value", "0.75,0.75,0.75"),
                    },
                )
            else:
                ET.SubElement(
                    pplastic,
                    "rgb",
                    {
                        "name": "diffuse_reflectance",
                        "value": "0.75,0.75,0.75",
                    },
                )

            alpha = "0.12"
            if roughness is not None:
                try:
                    alpha = f"{max(0.03, min(0.35, float(roughness.attrib.get('value', '0.12')))):.4f}"
                except ValueError:
                    alpha = "0.12"
            ET.SubElement(pplastic, "float", {"name": "alpha", "value": alpha})
            ET.SubElement(pplastic, "float", {"name": "int_ior", "value": "1.49"})
            ET.SubElement(pplastic, "float", {"name": "ext_ior", "value": "1.0"})

    root = _scene_template(
        scene_path,
        branch_kind="polarized_fallback",
        branch_signature=(nested_integrator_type, int(samples_per_pass or 0)),
        builder=_build_template,
    )
    _update_sensor(
        root,
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        spp=spp,
        width=width,
        height=height,
    )
    _apply_scene_override(root, scene_override, mode="polar")
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=assist_light.polarized)

    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _stage_target_mask_scene(
    scene_path: Path,
    out_scene: Path,
    *,
    camera_to_world: np.ndarray,
    fov_deg: float,
    spp: int,
    width: int,
    height: int,
    target_shape_filenames: Sequence[str],
) -> Path:
    stage_signature = (
        "target_mask",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        tuple(sorted(Path(item).name for item in target_shape_filenames)),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    root = _parse_scene(scene_path)
    integrator = root.find("./integrator")
    if integrator is None:
        raise RuntimeError("Scene has no integrator node")
    integrator.attrib["type"] = "direct"
    for child in list(integrator):
        integrator.remove(child)

    _update_sensor(
        root,
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        spp=spp,
        width=width,
        height=height,
    )
    _remove_all_emitters(root)

    targets = _target_name_set(target_shape_filenames)
    for shape in root.findall("./shape"):
        if _shape_matches_targets(shape, targets):
            _set_twosided_diffuse_bsdf(shape, reflectance=(1.0, 1.0, 1.0))
        else:
            _set_twosided_diffuse_bsdf(shape, reflectance=(0.0, 0.0, 0.0))

    _append_camera_assist_light(
        root,
        camera_to_world,
        AssistLightSpec(
            mode="camera_aligned_rect",
            distance_m=0.18,
            size_world=[5.0, 3.6],
            spectrum_mode="mask_proxy",
            polarized=False,
            polarizer_angle_deg=0.0,
            extras={"radiance": 24.0},
        ),
        polarized=False,
    )

    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _import_mitsuba():
    import mitsuba as mi

    return mi


def _resident_scene_cache_key(scene_path: Path, *, variant: str) -> tuple[str, int, int, str]:
    stat = scene_path.stat()
    return (str(scene_path.resolve()), int(stat.st_mtime_ns), int(stat.st_size), str(variant))


def _count_scene_assets(scene_path: Path) -> dict[str, int]:
    try:
        root = ET.parse(scene_path).getroot()
    except (ET.ParseError, OSError):
        return {}
    return {
        "mesh_count": len(root.findall(".//shape")),
        "texture_count": len(root.findall(".//texture")),
        "bsdf_count": len(root.findall(".//bsdf")),
    }


def _resident_scene_cache_has(scene_path: Path, *, variant: str) -> bool:
    try:
        cache_key = _resident_scene_cache_key(scene_path, variant=variant)
    except OSError:
        return False
    with _SCENE_CACHE_LOCK:
        return cache_key in _RESIDENT_SCENE_CACHE


def _load_resident_scene(scene_path: Path, *, variant: str) -> tuple[Any, float, bool]:
    mi = _import_mitsuba()
    mi.set_variant(variant)
    cache_key = _resident_scene_cache_key(scene_path, variant=variant)

    with _SCENE_CACHE_LOCK:
        cached_scene = _RESIDENT_SCENE_CACHE.get(cache_key)
        if cached_scene is not None:
            _RESIDENT_SCENE_CACHE.move_to_end(cache_key)
            return cached_scene, 0.0, True

    load_start = time.perf_counter()
    scene = mi.load_file(str(scene_path))
    load_s = time.perf_counter() - load_start

    with _SCENE_CACHE_LOCK:
        _RESIDENT_SCENE_CACHE[cache_key] = scene
        _RESIDENT_SCENE_CACHE.move_to_end(cache_key)
        while len(_RESIDENT_SCENE_CACHE) > _RESIDENT_SCENE_CACHE_LIMIT:
            _RESIDENT_SCENE_CACHE.popitem(last=False)
    return scene, load_s, False


def _clear_scene_caches() -> None:
    with _SCENE_CACHE_LOCK:
        _PARSED_SCENE_CACHE.clear()
        _SCENE_TEMPLATE_CACHE.clear()
        _RESIDENT_SCENE_CACHE.clear()
        _STAGED_SCENE_SIGNATURE_CACHE.clear()


def _render_scene(
    scene_path: Path,
    *,
    variant: str,
    spp: int,
    on_loaded: Callable[[], None] | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    mi = _import_mitsuba()
    start = time.perf_counter()
    scene, load_s, cache_hit = _load_resident_scene(scene_path, variant=variant)

    if on_loaded is not None:
        on_loaded()

    render_start = time.perf_counter()
    image = np.array(mi.render(scene, spp=spp), dtype=np.float32)
    render_s = time.perf_counter() - render_start
    total_s = time.perf_counter() - start
    return image, {
        "variant": variant,
        "load_scene_s": load_s,
        "scene_cache_hit": cache_hit,
        "render_s": render_s,
        "total_s": total_s,
    }


def srgb_encode(arr: np.ndarray) -> np.ndarray:
    arr = np.clip(arr, 0.0, None)
    return np.where(arr <= 0.0031308, 12.92 * arr, 1.055 * np.power(arr, 1.0 / 2.4) - 0.055)


def _rgb_preview_array(arr: np.ndarray, *, percentile: float) -> tuple[np.ndarray, dict[str, float]]:
    safe_arr = np.where(np.isfinite(arr), arr, 0.0)
    positive = safe_arr[safe_arr > 0]
    scale = float(np.quantile(positive, percentile)) if positive.size else 1.0
    scale = max(scale, 1e-6)
    preview = srgb_encode(safe_arr / scale)
    preview = np.clip(preview, 0.0, 1.0).astype(np.float32)
    return preview, {"tone_scale_percentile": percentile, "tone_scale_value": scale}


def _save_preview_image(preview_rgb: np.ndarray, path: Path, *, blur_radius: float = 0.0) -> None:
    preview_u8 = np.clip(np.round(np.clip(preview_rgb, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)
    image = Image.fromarray(preview_u8, mode="RGB")
    if blur_radius > 0.0:
        image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    image.save(path)


def save_rgb_preview(arr: np.ndarray, path: Path, percentile: float = 0.995) -> dict[str, float]:
    preview, summary = _rgb_preview_array(arr, percentile=percentile)
    _save_preview_image(preview, path, blur_radius=0.45 if percentile <= 0.992 else 0.0)
    return summary


def save_unit_rgb_preview(arr: np.ndarray, path: Path) -> dict[str, Any]:
    safe_arr = np.where(np.isfinite(arr), arr, 0.0)
    preview = srgb_encode(np.clip(safe_arr, 0.0, 1.0))
    _save_preview_image(preview, path)
    return {"encoding": "srgb", "input_range": [0.0, 1.0]}


def jet_colormap(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    r = np.clip(1.5 - np.abs(4.0 * x - 3.0), 0.0, 1.0)
    g = np.clip(1.5 - np.abs(4.0 * x - 2.0), 0.0, 1.0)
    b = np.clip(1.5 - np.abs(4.0 * x - 1.0), 0.0, 1.0)
    return np.stack([r, g, b], axis=-1)


def hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    h = np.mod(h, 1.0)
    i = np.floor(h * 6.0).astype(np.int32) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    out = np.zeros(h.shape + (3,), dtype=np.float32)
    values = [
        np.stack([v, t, p], axis=-1),
        np.stack([q, v, p], axis=-1),
        np.stack([p, v, t], axis=-1),
        np.stack([p, q, v], axis=-1),
        np.stack([t, p, v], axis=-1),
        np.stack([v, p, q], axis=-1),
    ]
    for idx, value in enumerate(values):
        mask = i == idx
        out[mask] = value[mask]
    return out


def to_u8(arr: np.ndarray) -> np.ndarray:
    return np.clip(np.round(np.clip(arr, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)


def append_colorbar(
    image_rgb: np.ndarray,
    bar_rgb: np.ndarray,
    ticks: list[tuple[float, str]],
    title: str,
    path: Path,
    *,
    title_mode: str,
) -> None:
    font = ImageFont.load_default()
    image = Image.fromarray(to_u8(image_rgb), mode="RGB")
    bar = Image.fromarray(to_u8(bar_rgb), mode="RGB")

    width, height = image.size
    bar_w = bar.size[0]
    pad = 14
    label_gap = 8
    text_w = 86
    canvas = Image.new("RGB", (width + pad + bar_w + label_gap + text_w, height), (0, 0, 0))
    canvas.paste(image, (0, 0))
    bar_x = width + pad
    canvas.paste(bar, (bar_x, 0))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([bar_x - 1, 0, bar_x + bar_w, height - 1], outline=(220, 220, 220), width=1)
    draw.text((bar_x, 6), title, font=font, fill=(255, 255, 255))
    label_x = bar_x + bar_w + label_gap

    for value, label in ticks:
        if title_mode == "signed":
            norm = (1.0 - value) / 2.0
        elif title_mode == "angle":
            norm = 1.0 - (value / 180.0)
        else:
            norm = 1.0 - value
        y = int(round(norm * (height - 1)))
        draw.line([(bar_x + bar_w, y), (bar_x + bar_w + 5, y)], fill=(255, 255, 255), width=1)
        draw.text((label_x, max(0, min(height - 12, y - 6))), label, font=font, fill=(255, 255, 255))

    canvas.save(path)


def save_depth_products(depth: np.ndarray, out_dir: Path, *, stem: str = "depth", title: str = "Depth") -> dict[str, Any]:
    valid = np.isfinite(depth) & (depth > 0)
    if not np.any(valid):
        raise RuntimeError("Depth image has no valid pixels")

    raw_path = out_dir / f"{stem}_raw.npz"
    np.savez_compressed(raw_path, depth=depth, valid=valid)

    d_min = float(np.quantile(depth[valid], 0.01))
    d_max = float(np.quantile(depth[valid], 0.99))
    span = max(d_max - d_min, 1e-6)
    norm = np.clip((depth - d_min) / span, 0.0, 1.0)
    depth_rgb = jet_colormap(norm)
    depth_rgb[~valid] = 0.0

    bar_deg = np.linspace(d_max, d_min, depth.shape[0], dtype=np.float32)[:, None]
    bar_norm = np.clip((bar_deg - d_min) / span, 0.0, 1.0)
    bar_rgb = jet_colormap(np.repeat(bar_norm, 38, axis=1))
    ticks = [
        (1.0, f"{d_max:.2f}"),
        (0.75, f"{d_min + 0.75 * span:.2f}"),
        (0.50, f"{d_min + 0.50 * span:.2f}"),
        (0.25, f"{d_min + 0.25 * span:.2f}"),
        (0.0, f"{d_min:.2f}"),
    ]
    png_path = out_dir / f"{stem}_jet_colorbar.png"
    append_colorbar(depth_rgb, bar_rgb, ticks, title, png_path, title_mode="range")

    return {
        "valid_pixels": int(np.count_nonzero(valid)),
        "depth_p01": d_min,
        "depth_p99": d_max,
        "depth_min": float(np.min(depth[valid])),
        "depth_max": float(np.max(depth[valid])),
        "png": str(png_path),
        "raw_npz": str(raw_path),
        "valid_mask": valid,
    }


def _extract_binary_mask(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        luminance = np.tensordot(image[:, :, :3], np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([2], [0]))
    else:
        luminance = image.astype(np.float32)
    finite = luminance[np.isfinite(luminance)]
    threshold = 0.5 * float(finite.max()) if finite.size else 0.5
    return np.isfinite(luminance) & (luminance > threshold)


def _mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if ys.size == 0 or xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _resize_scalar_field(field: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    if out_h <= 0 or out_w <= 0:
        return np.zeros((0, 0), dtype=np.float32)
    src_h, src_w = field.shape
    y_idx = np.linspace(0, max(src_h - 1, 0), out_h).astype(np.int32)
    x_idx = np.linspace(0, max(src_w - 1, 0), out_w).astype(np.int32)
    return field[np.ix_(y_idx, x_idx)].astype(np.float32)


def _extract_salient_reflection_patch(
    field: np.ndarray,
    *,
    target_aspect: float,
) -> np.ndarray:
    valid = np.isfinite(field) & (field > 0)
    if not np.any(valid):
        return field.astype(np.float32)

    clean = field.astype(np.float32).copy()
    fill_value = float(np.median(clean[valid]))
    clean[~valid] = fill_value

    grad_y, grad_x = np.gradient(clean)
    grad_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y)
    grad_mag[~valid] = 0.0

    h, w = clean.shape
    aspect = max(float(target_aspect), 0.2)
    best_score = -1.0
    best_patch: np.ndarray | None = None

    for frac in (0.28, 0.38, 0.50):
        crop_h = max(64, min(h, int(round(h * frac))))
        crop_w = max(64, int(round(crop_h * aspect)))
        if crop_w > int(w * 0.70):
            crop_w = max(64, int(round(w * 0.70)))
            crop_h = max(64, int(round(crop_w / aspect)))
        crop_h = min(crop_h, h)
        crop_w = min(crop_w, w)
        if crop_h <= 0 or crop_w <= 0:
            continue

        y_positions = np.unique(np.linspace(0, max(h - crop_h, 0), 7).astype(np.int32))
        x_positions = np.unique(np.linspace(0, max(w - crop_w, 0), 7).astype(np.int32))
        for y0 in y_positions:
            for x0 in x_positions:
                patch_valid = valid[y0:y0 + crop_h, x0:x0 + crop_w]
                valid_ratio = float(np.mean(patch_valid))
                if valid_ratio < 0.35:
                    continue
                patch = clean[y0:y0 + crop_h, x0:x0 + crop_w]
                patch_values = patch[patch_valid]
                grad_score = float(np.mean(grad_mag[y0:y0 + crop_h, x0:x0 + crop_w][patch_valid]))
                depth_span = float(np.quantile(patch_values, 0.9) - np.quantile(patch_values, 0.1))
                score = grad_score * 4.0 + depth_span + valid_ratio
                if score > best_score:
                    best_score = score
                    best_patch = patch.copy()

    if best_patch is None:
        return clean.astype(np.float32)
    return best_patch.astype(np.float32)


def _extract_guided_reflection_patch(
    base_depth: np.ndarray,
    mirrored_depth: np.ndarray,
    *,
    target_bbox: tuple[int, int, int, int],
) -> np.ndarray:
    x0, y0, x1, y1 = target_bbox
    h, w = base_depth.shape
    target_aspect = (x1 - x0) / max(float(y1 - y0), 1.0)

    # For the dining_north demo, the reflective cabinet sits on the right edge.
    # A mirrored crop of the left-center dining set produces a much clearer
    # "wrong depth" failure than generic saliency alone.
    if x0 > int(w * 0.58):
        px0 = int(w * 0.10)
        px1 = min(int(w * 0.54), max(int(w * 0.34), x0 - int(w * 0.08)))
        py0 = int(h * 0.42)
        py1 = int(h * 0.96)
        if (px1 - px0) >= 64 and (py1 - py0) >= 64:
            preferred = base_depth[py0:py1, px0:px1]
            preferred_valid = np.isfinite(preferred) & (preferred > 0)
            if float(np.mean(preferred_valid)) > 0.35:
                return preferred[:, ::-1].astype(np.float32)

    left_limit = max(int(w * 0.24), min(int(w * 0.72), x0 - int(w * 0.03)))
    lower_band_top = max(0, min(int(h * 0.42), y0 - int(h * 0.04)))
    lower_band_bottom = min(h, max(y1 + int(h * 0.08), int(h * 0.96)))
    central_top = max(0, min(int(h * 0.28), y0 - int(h * 0.12)))

    search_regions = [
        (base_depth, (int(w * 0.05), lower_band_top, left_limit, lower_band_bottom), 1.85),
        (base_depth, (int(w * 0.10), central_top, min(int(w * 0.76), max(left_limit, int(w * 0.45))), h), 1.45),
        (mirrored_depth, (0, central_top, w, h), 1.10),
        (base_depth, (0, 0, w, h), 0.95),
    ]

    best_patch: np.ndarray | None = None
    best_score = -1.0
    for field, (rx0, ry0, rx1, ry1), weight in search_regions:
        rx0 = max(0, min(w - 1, rx0))
        ry0 = max(0, min(h - 1, ry0))
        rx1 = max(rx0 + 1, min(w, rx1))
        ry1 = max(ry0 + 1, min(h, ry1))
        if (rx1 - rx0) < 64 or (ry1 - ry0) < 64:
            continue
        candidate = _extract_salient_reflection_patch(
            field[ry0:ry1, rx0:rx1],
            target_aspect=target_aspect,
        )
        valid = np.isfinite(candidate) & (candidate > 0)
        if not np.any(valid):
            continue
        median_depth = float(np.median(candidate[valid]))
        near_bonus = 2.5 / max(median_depth, 1.0)
        score = weight * (_scalar_patch_saliency(candidate) + near_bonus)
        if score > best_score:
            best_score = score
            best_patch = candidate

    if best_patch is not None:
        return best_patch.astype(np.float32)
    return _extract_salient_reflection_patch(base_depth, target_aspect=target_aspect)


def _scalar_patch_saliency(field: np.ndarray) -> float:
    valid = np.isfinite(field) & (field > 0)
    if not np.any(valid):
        return 0.0
    clean = field.astype(np.float32).copy()
    clean[~valid] = float(np.median(clean[valid]))
    grad_y, grad_x = np.gradient(clean)
    grad_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y)
    patch_values = clean[valid]
    depth_span = float(np.quantile(patch_values, 0.9) - np.quantile(patch_values, 0.1))
    return float(np.mean(grad_mag[valid]) * 4.0 + depth_span)


def _box_blur_masked(field: np.ndarray, mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return field.astype(np.float32)
    out = field.astype(np.float32).copy()
    weights = mask.astype(np.float32)
    for _ in range(radius):
        padded_values = np.pad(out * weights, ((1, 1), (1, 1)), mode="edge")
        padded_weights = np.pad(weights, ((1, 1), (1, 1)), mode="edge")
        accum = np.zeros_like(out, dtype=np.float32)
        denom = np.zeros_like(out, dtype=np.float32)
        for dy in range(3):
            for dx in range(3):
                accum += padded_values[dy:dy + out.shape[0], dx:dx + out.shape[1]]
                denom += padded_weights[dy:dy + out.shape[0], dx:dx + out.shape[1]]
        averaged = np.where(denom > 1e-6, accum / denom, out)
        out = np.where(mask, averaged, out)
    return out


def _select_reflective_plane(bounds_min: np.ndarray, bounds_max: np.ndarray, camera_to_world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    origin, _right, _up, _forward = _camera_basis(camera_to_world)
    center = (bounds_min + bounds_max) * 0.5
    extents = bounds_max - bounds_min
    candidates = []
    for axis in range(3):
        normal = np.zeros(3, dtype=np.float32)
        normal[axis] = 1.0
        for sign in (-1.0, 1.0):
            signed_normal = normal * sign
            point = center.copy()
            point[axis] = bounds_min[axis] if sign < 0 else bounds_max[axis]
            to_camera = _normalize(origin - point)
            score = float(np.dot(signed_normal, to_camera))
            area_axes = [idx for idx in range(3) if idx != axis]
            area = float(extents[area_axes[0]] * extents[area_axes[1]])
            candidates.append((score, area, point, signed_normal))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _score, _area, point, normal = candidates[0]
    return point.astype(np.float32), normal.astype(np.float32)


def _reflect_camera_to_world(camera_to_world: np.ndarray, plane_point: np.ndarray, plane_normal: np.ndarray) -> np.ndarray:
    origin, _right, up, forward = _camera_basis(camera_to_world)
    plane_normal = _normalize(plane_normal)

    def reflect_point(point: np.ndarray) -> np.ndarray:
        return point - 2.0 * np.dot(point - plane_point, plane_normal) * plane_normal

    def reflect_direction(direction: np.ndarray) -> np.ndarray:
        return direction - 2.0 * np.dot(direction, plane_normal) * plane_normal

    origin_ref = reflect_point(origin)
    forward_ref = _normalize(reflect_direction(forward))
    up_ref = _normalize(reflect_direction(up))
    right_ref = _normalize(np.cross(forward_ref, up_ref))
    true_up = _normalize(np.cross(right_ref, forward_ref))

    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, 0] = right_ref
    matrix[:3, 1] = true_up
    matrix[:3, 2] = -forward_ref
    matrix[:3, 3] = origin_ref
    return matrix


def _build_sensor_depth_approx(
    base_depth: np.ndarray,
    *,
    target_mask: np.ndarray,
    mirrored_depth: np.ndarray,
    blur_sigma_px: float,
    blend: float,
) -> np.ndarray:
    approx = base_depth.astype(np.float32).copy()
    bbox = _mask_bbox(target_mask)
    if bbox is None:
        return approx

    x0, y0, x1, y1 = bbox
    patch_h = max(y1 - y0, 1)
    patch_w = max(x1 - x0, 1)
    reflection_patch = _extract_guided_reflection_patch(
        base_depth,
        mirrored_depth,
        target_bbox=bbox,
    )
    resized = _resize_scalar_field(reflection_patch, patch_h, patch_w)
    valid_resized = np.isfinite(resized) & (resized > 0)
    if np.any(valid_resized):
        median_depth = float(np.median(resized[valid_resized]))
        resized = median_depth + (resized - median_depth) * 1.35
    patch_mask = np.ones((patch_h, patch_w), dtype=bool)
    patch = approx[y0:y1, x0:x1].copy()
    patch[patch_mask] = (1.0 - blend) * patch[patch_mask] + blend * resized[patch_mask]
    radius = max(0, int(round(blur_sigma_px)))
    patch = _box_blur_masked(patch, patch_mask, radius)
    approx[y0:y1, x0:x1] = patch
    return approx


def extract_stokes_channels(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if image.ndim != 3:
        raise RuntimeError(f"Expected a 3D stokes tensor, got shape {image.shape}")
    if image.shape[2] == 15:
        offset = 3
    elif image.shape[2] == 16:
        offset = 4
    else:
        raise RuntimeError(f"Unexpected stokes channel count: {image.shape[2]}")

    rgb = image[:, :, 0:3]
    s0 = image[:, :, offset + 0:offset + 3]
    s1 = image[:, :, offset + 3:offset + 6]
    s2 = image[:, :, offset + 6:offset + 9]
    s3 = image[:, :, offset + 9:offset + 12]
    return rgb, s0, s1, s2, s3


def _fill_invalid_preview_pixels(
    image_rgb: np.ndarray,
    *,
    valid_mask: np.ndarray,
    fallback_rgb: np.ndarray,
    max_iterations: int = 4,
) -> np.ndarray:
    out = np.asarray(image_rgb, dtype=np.float32).copy()
    valid = np.asarray(valid_mask, dtype=bool)
    fallback = np.asarray(fallback_rgb, dtype=np.float32)
    if not np.any(~valid):
        return np.clip(out, 0.0, 1.0)

    height, width = valid.shape
    out[~valid] = fallback[~valid]
    known = valid.copy()
    for _ in range(max(1, int(max_iterations))):
        invalid = ~known
        if not np.any(invalid):
            break
        padded = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        known_padded = np.pad(known, ((1, 1), (1, 1)), mode="constant", constant_values=False)
        accum = np.zeros_like(out)
        counts = np.zeros((height, width), dtype=np.float32)
        for dy in range(3):
            for dx in range(3):
                if dx == 1 and dy == 1:
                    continue
                neighbor_known = known_padded[dy:dy + height, dx:dx + width]
                neighbor_rgb = padded[dy:dy + height, dx:dx + width, :]
                accum += neighbor_rgb * neighbor_known[:, :, None]
                counts += neighbor_known.astype(np.float32)
        fillable = invalid & (counts > 0)
        if not np.any(fillable):
            break
        out[fillable] = accum[fillable] / counts[fillable, None]
        known[fillable] = True
    return np.clip(out, 0.0, 1.0)


def _despeckle_dark_preview_pixels(
    image_rgb: np.ndarray,
    *,
    iterations: int = 2,
    darkness_threshold: float = 0.08,
    contrast_threshold: float = 0.10,
) -> np.ndarray:
    out = np.clip(np.asarray(image_rgb, dtype=np.float32), 0.0, 1.0).copy()
    if out.ndim != 3 or out.shape[2] != 3:
        return out

    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    height, width = out.shape[:2]
    for _ in range(max(1, int(iterations))):
        lum = np.tensordot(out, weights, axes=([2], [0]))
        padded = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        lum_padded = np.pad(lum, ((1, 1), (1, 1)), mode="edge")
        accum = np.zeros_like(out)
        lum_accum = np.zeros((height, width), dtype=np.float32)
        for dy in range(3):
            for dx in range(3):
                if dx == 1 and dy == 1:
                    continue
                accum += padded[dy:dy + height, dx:dx + width, :]
                lum_accum += lum_padded[dy:dy + height, dx:dx + width]
        mean_rgb = accum / 8.0
        mean_lum = lum_accum / 8.0
        speckle = (lum < darkness_threshold) & (mean_lum > (lum + contrast_threshold)) & (mean_lum > 0.12)
        if not np.any(speckle):
            break
        out[speckle] = mean_rgb[speckle]
    return np.clip(out, 0.0, 1.0)


def save_polarization_products(
    image: np.ndarray,
    out_dir: Path,
    requested_modalities: set[str],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    rgb, s0, s1, s2, s3 = extract_stokes_channels(image)

    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    s0_l = np.tensordot(s0, weights, axes=([2], [0]))
    s1_l = np.tensordot(s1, weights, axes=([2], [0]))
    s2_l = np.tensordot(s2, weights, axes=([2], [0]))
    s3_l = np.tensordot(s3, weights, axes=([2], [0]))

    finite_mask = np.isfinite(s0_l) & np.isfinite(s1_l) & np.isfinite(s2_l)
    finite_s0 = s0_l[finite_mask & (s0_l > 0)]
    threshold = max(float(np.quantile(finite_s0, 0.02)) * 0.25, 1e-6) if finite_s0.size else 1e-6
    mask = finite_mask & (s0_l > threshold)
    dop = np.sqrt(np.maximum(0.0, s1_l * s1_l + s2_l * s2_l)) / np.maximum(s0_l, 1e-8)
    dop = np.clip(dop, 0.0, 1.0)
    aolp = np.mod(0.5 * np.arctan2(s2_l, s1_l), np.pi)
    aolp_deg = np.degrees(aolp)
    context_scale = max(float(np.quantile(finite_s0, 0.995)) if finite_s0.size else 1.0, 1e-6)
    context = np.clip(np.sqrt(np.clip(s0_l, 0.0, None) / context_scale), 0.0, 1.0)
    context_rgb = np.repeat((0.12 + 0.88 * context)[:, :, None], 3, axis=2).astype(np.float32)
    context_rgb[~finite_mask] = 0.18
    invalid_pixel_count = int(np.count_nonzero(~finite_mask))
    finite_ratio = float(np.mean(finite_mask))

    stokes_npz = out_dir / "stokes_data.npz"
    np.savez_compressed(
        stokes_npz,
        rgb=rgb,
        s0=s0,
        s1=s1,
        s2=s2,
        s3=s3,
        s0_l=s0_l,
        s1_l=s1_l,
        s2_l=s2_l,
        s3_l=s3_l,
        dop=dop,
        aolp=aolp,
        mask=mask,
    )

    def bwr_map(field: np.ndarray, scale: float) -> np.ndarray:
        safe_field = np.where(np.isfinite(field), field, 0.0)
        norm = np.clip(safe_field / scale, -1.0, 1.0)
        pos = np.clip(norm, 0.0, 1.0)
        neg = np.clip(-norm, 0.0, 1.0)
        overlay = np.ones(field.shape + (3,), dtype=np.float32)
        overlay[..., 1] = 1.0 - np.maximum(pos, neg)
        overlay[..., 0] = 1.0 - neg
        overlay[..., 2] = 1.0 - pos
        strength = np.clip(np.abs(norm), 0.0, 1.0)[:, :, None]
        rgb_out = context_rgb * (1.0 - 0.75 * strength) + overlay * (0.15 + 0.85 * strength)
        return _fill_invalid_preview_pixels(rgb_out, valid_mask=finite_mask, fallback_rgb=context_rgb)

    def bwr_bar(scale: float, height: int) -> tuple[np.ndarray, list[tuple[float, str]]]:
        y = np.linspace(1.0, -1.0, height, dtype=np.float32)[:, None]
        grad = np.repeat(y, 38, axis=1)
        pos = np.clip(grad, 0.0, 1.0)
        neg = np.clip(-grad, 0.0, 1.0)
        rgb_out = np.ones((height, 38, 3), dtype=np.float32)
        rgb_out[..., 1] = 1.0 - np.maximum(pos, neg)
        rgb_out[..., 0] = 1.0 - neg
        rgb_out[..., 2] = 1.0 - pos
        ticks = [(1.0, f"+{scale:.3g}"), (0.0, "0"), (-1.0, f"-{scale:.3g}")]
        return rgb_out, ticks

    def dop_map(field: np.ndarray) -> np.ndarray:
        safe_field = np.where(np.isfinite(field), field, 0.0)
        strength = np.sqrt(np.clip(safe_field, 0.0, 1.0))
        rgb_out = context_rgb * (1.0 - 0.68 * strength[:, :, None])
        rgb_out[..., 0] = np.clip(rgb_out[..., 0] + 0.95 * strength, 0.0, 1.0)
        return _fill_invalid_preview_pixels(rgb_out, valid_mask=finite_mask, fallback_rgb=context_rgb)

    def dop_bar(height: int) -> tuple[np.ndarray, list[tuple[float, str]]]:
        y = np.linspace(1.0, 0.0, height, dtype=np.float32)[:, None]
        grad = np.repeat(y, 38, axis=1)
        rgb_out = np.zeros((height, 38, 3), dtype=np.float32)
        rgb_out[..., 0] = grad
        ticks = [(1.0, "1.0"), (0.75, "0.75"), (0.5, "0.5"), (0.25, "0.25"), (0.0, "0.0")]
        return rgb_out, ticks

    def aolp_map(field_deg: np.ndarray) -> np.ndarray:
        safe_field = np.where(np.isfinite(field_deg), field_deg, 0.0)
        hue = np.mod(safe_field / 180.0, 1.0)
        overlay = hsv_to_rgb(
            hue,
            np.ones(field_deg.shape, dtype=np.float32),
            np.ones(field_deg.shape, dtype=np.float32),
        )
        strength = np.where(mask, np.sqrt(np.clip(dop, 0.0, 1.0)), 0.0)[:, :, None]
        rgb_out = context_rgb * (1.0 - 0.80 * strength) + overlay * (0.20 + 0.80 * strength)
        return _fill_invalid_preview_pixels(rgb_out, valid_mask=finite_mask, fallback_rgb=context_rgb)

    def aolp_bar(height: int) -> tuple[np.ndarray, list[tuple[float, str]]]:
        deg = np.linspace(180.0, 0.0, height, dtype=np.float32)[:, None]
        hue = np.mod(deg / 180.0, 1.0)
        rgb_out = hsv_to_rgb(
            np.repeat(hue, 38, axis=1),
            np.ones((height, 38), dtype=np.float32),
            np.ones((height, 38), dtype=np.float32),
        )
        ticks = [(180.0, "180°"), (135.0, "135°"), (90.0, "90°"), (45.0, "45°"), (0.0, "0°")]
        return rgb_out, ticks

    s1_scale = max(float(np.quantile(np.abs(s1_l[mask]), 0.99)) if np.any(mask) else 1.0, 1e-6)
    s2_scale = max(float(np.quantile(np.abs(s2_l[mask]), 0.99)) if np.any(mask) else 1.0, 1e-6)

    outputs: dict[str, str] = {"stokes_npz": str(stokes_npz)}
    if "polar_rgb_preview" in requested_modalities:
        polar_rgb_preview = out_dir / "polar_rgb_preview.png"
        preview_rgb, _ = _rgb_preview_array(rgb, percentile=0.992)
        finite_rgb_mask = np.all(np.isfinite(rgb), axis=2)
        preview_rgb = _fill_invalid_preview_pixels(
            preview_rgb,
            valid_mask=finite_rgb_mask,
            fallback_rgb=context_rgb,
            max_iterations=8,
        )
        preview_rgb = _despeckle_dark_preview_pixels(preview_rgb, iterations=3)
        _save_preview_image(preview_rgb, polar_rgb_preview, blur_radius=0.45)
        outputs["rgb_preview"] = str(polar_rgb_preview)
    if "s1" in requested_modalities:
        bar, ticks = bwr_bar(s1_scale, s1_l.shape[0])
        s1_path = out_dir / "s1_bwr_colorbar.png"
        s1_rgb = _despeckle_dark_preview_pixels(bwr_map(s1_l, s1_scale), iterations=3)
        append_colorbar(s1_rgb, bar, ticks, "S1", s1_path, title_mode="signed")
        outputs["s1"] = str(s1_path)
    if "s2" in requested_modalities:
        bar, ticks = bwr_bar(s2_scale, s2_l.shape[0])
        s2_path = out_dir / "s2_bwr_colorbar.png"
        s2_rgb = _despeckle_dark_preview_pixels(bwr_map(s2_l, s2_scale), iterations=3)
        append_colorbar(s2_rgb, bar, ticks, "S2", s2_path, title_mode="signed")
        outputs["s2"] = str(s2_path)
    if "dop" in requested_modalities:
        bar, ticks = dop_bar(dop.shape[0])
        dop_path = out_dir / "dop_red_black_colorbar.png"
        dop_rgb = _despeckle_dark_preview_pixels(dop_map(dop), iterations=3)
        append_colorbar(dop_rgb, bar, ticks, "DoP", dop_path, title_mode="range")
        outputs["dop"] = str(dop_path)
    if "aolp" in requested_modalities:
        bar, ticks = aolp_bar(aolp_deg.shape[0])
        aolp_path = out_dir / "aolp_rainbow_colorbar.png"
        aolp_rgb = _despeckle_dark_preview_pixels(aolp_map(aolp_deg), iterations=3)
        append_colorbar(aolp_rgb, bar, ticks, "AoLP", aolp_path, title_mode="angle")
        outputs["aolp"] = str(aolp_path)

    summary = {
        "s1_scale_abs_p995": s1_scale,
        "s2_scale_abs_p995": s2_scale,
        "s1_scale_abs_p99": s1_scale,
        "s2_scale_abs_p99": s2_scale,
        "invalid_pixel_count": invalid_pixel_count,
        "finite_ratio": finite_ratio,
        "dop_range": [0.0, 1.0],
        "aolp_range_degrees": [0.0, 180.0],
        "outputs": outputs,
    }
    arrays = {
        "rgb": rgb.astype(np.float32),
        "s0": s0.astype(np.float32),
        "s1": s1.astype(np.float32),
        "s2": s2.astype(np.float32),
        "s3": s3.astype(np.float32),
        "s0_l": s0_l.astype(np.float32),
        "s1_l": s1_l.astype(np.float32),
        "s2_l": s2_l.astype(np.float32),
        "s3_l": s3_l.astype(np.float32),
        "dop": dop.astype(np.float32),
        "aolp_deg": aolp_deg.astype(np.float32),
        "mask": mask.astype(bool),
    }
    return summary, arrays


def _write_bitmap(path: Path, array: np.ndarray) -> None:
    mi = _import_mitsuba()
    mi.util.write_bitmap(str(path), array.astype(np.float32))


def _build_rgb_result(
    modality: str,
    rgb: np.ndarray,
    out_dir: Path,
    *,
    stem: str,
    timing: dict[str, Any],
    scene_path: Path,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[ModalityResult, dict[str, Any]]:
    exr_path = out_dir / f"{stem}.exr"
    png_path = out_dir / f"{stem}.png"
    raw_path = out_dir / f"{stem}_raw.npz"

    save_start = time.perf_counter()
    _write_bitmap(exr_path, rgb)
    preview_percentile = 0.992 if modality == "rgb" else 0.995
    preview = save_rgb_preview(rgb, png_path, percentile=preview_percentile)
    np.savez_compressed(raw_path, rgb=rgb.astype(np.float32))
    timing_record = {
        "task": "rgb",
        "scene": str(scene_path),
        "spp": timing["spp"],
        "load_scene_s": timing["load_scene_s"],
        "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
        "render_s": timing["render_s"],
        "save_s": time.perf_counter() - save_start,
        "total_s": timing["total_s"] + (time.perf_counter() - save_start),
        "preview": preview,
        "outputs": {
            "exr": str(exr_path),
            "png": str(png_path),
            "raw_npz": str(raw_path),
        },
    }
    result = ModalityResult(
        name=modality,
        array=rgb.astype(np.float32),
        raw_channels={"rgb": rgb.astype(np.float32)},
        metadata={"preview": preview, **dict(metadata or {})},
        timing={
            "variant": timing["variant"],
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "save_s": timing_record["save_s"],
            "total_s": timing_record["total_s"],
            "scene": str(scene_path),
            "spp": timing["spp"],
        },
        artifacts=timing_record["outputs"],
    )
    return result, timing_record


def _build_grayscale_result(
    modality: str,
    intensity: np.ndarray,
    out_dir: Path,
    *,
    stem: str,
    timing: dict[str, Any],
    scene_path: Path,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[ModalityResult, dict[str, Any]]:
    exr_path = out_dir / f"{stem}.exr"
    png_path = out_dir / f"{stem}.png"
    raw_path = out_dir / f"{stem}_raw.npz"
    rgb = np.repeat(intensity[:, :, None], 3, axis=2).astype(np.float32)

    save_start = time.perf_counter()
    _write_bitmap(exr_path, rgb)
    preview_percentile = 0.992 if modality == "active_nir_intensity" else 0.995
    preview = save_rgb_preview(rgb, png_path, percentile=preview_percentile)
    np.savez_compressed(raw_path, intensity=intensity.astype(np.float32))
    save_s = time.perf_counter() - save_start

    timing_record = {
        "task": modality,
        "scene": str(scene_path),
        "spp": timing["spp"],
        "load_scene_s": timing["load_scene_s"],
        "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
        "render_s": timing["render_s"],
        "save_s": save_s,
        "total_s": timing["total_s"] + save_s,
        "preview": preview,
        "outputs": {
            "exr": str(exr_path),
            "png": str(png_path),
            "raw_npz": str(raw_path),
        },
    }
    result = ModalityResult(
        name=modality,
        array=intensity.astype(np.float32),
        raw_channels={"intensity": intensity.astype(np.float32)},
        metadata={"preview": preview, **dict(metadata or {})},
        timing={
            "variant": timing["variant"],
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "save_s": save_s,
            "total_s": timing_record["total_s"],
            "scene": str(scene_path),
            "spp": timing["spp"],
        },
        artifacts=timing_record["outputs"],
    )
    return result, timing_record


def _compose_derived_result(
    modality: str,
    array: np.ndarray,
    out_dir: Path,
    *,
    timing_seed: dict[str, Any],
    dependencies: dict[str, str],
) -> ModalityResult:
    stem = modality
    exr_path = out_dir / f"{stem}.exr"
    png_path = out_dir / f"{stem}.png"
    raw_path = out_dir / f"{stem}_raw.npz"
    _write_bitmap(exr_path, array)
    preview = save_rgb_preview(array, png_path)
    np.savez_compressed(raw_path, rgb=array.astype(np.float32))
    return ModalityResult(
        name=modality,
        array=array.astype(np.float32),
        raw_channels={"rgb": array.astype(np.float32)},
        metadata={
            "preview": preview,
            "dependencies": dependencies,
        },
        timing=dict(timing_seed),
        artifacts={
            "exr": str(exr_path),
            "png": str(png_path),
            "raw_npz": str(raw_path),
        },
    )


def _branch_metadata(
    *,
    illumination_tag: str,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
    depth_model: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "illumination_tag": illumination_tag,
    }
    if scene_override is not None:
        metadata["target_shape_filenames"] = list(scene_override.target_shape_filenames)
        metadata["material_profile"] = scene_override.material_profile
    if assist_light is not None:
        metadata["assist_light"] = asdict(assist_light)
    if depth_model is not None:
        metadata["depth_model"] = depth_model
    if extra:
        metadata.update(dict(extra))
    return metadata


def _resolve_modalities(modalities: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for modality in modalities:
        if modality not in SUPPORTED_MODALITIES:
            raise ValueError(f"Unsupported modality: {modality}")
        if modality not in seen:
            normalized.append(modality)
            seen.add(modality)
    return normalized


def _needs_path_total(modalities: set[str]) -> bool:
    return any(modality in modalities for modality in ("rgb", "indirect_light_map", "specular_map"))


def _needs_direct(modalities: set[str]) -> bool:
    return any(modality in modalities for modality in ("direct_light_map", "indirect_light_map"))


def _needs_diffuse(modalities: set[str]) -> bool:
    return any(modality in modalities for modality in ("diffuse_map", "specular_map"))


def _needs_aov(modalities: set[str]) -> bool:
    return any(modality in modalities for modality in ("depth", "albedo", "sensor_depth_approx"))


def _needs_polar(modalities: set[str]) -> bool:
    return any(modality in modalities for modality in ("polar_rgb_preview", "dop", "aolp", "s1", "s2"))


def _needs_active_nir(modalities: set[str]) -> bool:
    return "active_nir_intensity" in modalities


def _needs_sensor_depth(modalities: set[str]) -> bool:
    return "sensor_depth_approx" in modalities


def _polar_variant(base_variant: str) -> str:
    if base_variant.endswith("_polarized"):
        return base_variant
    return f"{base_variant}_polarized"


def render_modalities(
    scene_xml: str | Path,
    camera_to_world: np.ndarray,
    fov_deg: float,
    modalities: Sequence[str],
    *,
    out_dir: str | Path | None = None,
    config: RenderConfig | None = None,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
    depth_approx: DepthApproxSpec | None = None,
    variant: str = "cuda_ad_spectral",
    progress_callback: Callable[[str, Mapping[str, Any] | None], None] | None = None,
) -> MultimodalRenderResult:
    config = config or RenderConfig()
    requested = _resolve_modalities(modalities)
    requested_set = set(requested)
    source_scene = Path(scene_xml).resolve()

    if out_dir is None:
        workspace = Path(tempfile.mkdtemp(prefix="robomituba_multimodal_"))
        temporary_workspace = True
    else:
        workspace = Path(out_dir).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        temporary_workspace = False

    results: dict[str, ModalityResult] = {}
    pass_records: dict[str, dict[str, Any]] = {}
    staged_scenes: dict[str, str] = {}
    scene_override = scene_override if (scene_override and (
        scene_override.target_shape_filenames
        or scene_override.bsdf_overrides
        or scene_override.transform_overrides
    )) else None
    assist_light = assist_light if assist_light and assist_light.mode == "camera_aligned_rect" else None
    depth_approx = depth_approx if depth_approx and depth_approx.target_shape_filenames else None
    if "sensor_depth_approx" in requested_set and depth_approx is None:
        raise ValueError("sensor_depth_approx requires a depth_approx specification.")
    if "active_nir_intensity" in requested_set and assist_light is None:
        raise ValueError("active_nir_intensity requires an assist_light specification.")

    # ── progress helpers ──────────────────────────────────────────────────
    _pass_index: list[int] = [0]
    _total_passes = sum([
        1 if _needs_path_total(requested_set) else 0,
        1 if _needs_direct(requested_set) else 0,
        1 if _needs_diffuse(requested_set) else 0,
        1 if _needs_aov(requested_set) else 0,
        1 if (_needs_sensor_depth(requested_set) and depth_approx is not None) else 0,
        1 if (_needs_sensor_depth(requested_set) and depth_approx is not None) else 0,  # mirror pass
        1 if (_needs_active_nir(requested_set) and assist_light is not None) else 0,
        1 if _needs_polar(requested_set) else 0,
    ])

    def _cb(stage: str, ctx: Mapping[str, Any] | None = None) -> None:
        if progress_callback is not None:
            progress_callback(stage, ctx)

    def _render_pass(
        scene_path: Path,
        *,
        pass_name: str,
        spp: int,
        variant_override: str | None = None,
    ) -> tuple[np.ndarray, dict[str, float]]:
        _pass_index[0] += 1
        v = variant_override or variant
        base_ctx = {
            "pass": pass_name,
            "spp": spp,
            "variant": v,
            "pass_index": _pass_index[0],
            "total_passes": _total_passes,
        }
        cache_hit = _resident_scene_cache_has(scene_path, variant=v)
        if cache_hit:
            _cb("loading_scene", {
                **base_ctx,
                "sub_step": "cached",
                "sub_phase": 5,
                "sub_total": 5,
                "cached": True,
            })
        else:
            counts = _count_scene_assets(scene_path)
            # phases 1-4 emit *before* mi.load_file() because mitsuba exposes no
            # in-call progress callback; the actual mesh/texture/optix work all
            # happens inside the single load_file() invocation below.
            _cb("loading_scene", {**base_ctx, "sub_step": "parsing_xml",        "sub_phase": 1, "sub_total": 5, **counts})
            _cb("loading_scene", {**base_ctx, "sub_step": "loading_meshes",     "sub_phase": 2, "sub_total": 5, **counts})
            _cb("loading_scene", {**base_ctx, "sub_step": "uploading_textures", "sub_phase": 3, "sub_total": 5, **counts})
            _cb("loading_scene", {**base_ctx, "sub_step": "compiling_optix",    "sub_phase": 4, "sub_total": 5, **counts})

        def _on_loaded() -> None:
            if not cache_hit:
                _cb("loading_scene", {
                    **base_ctx,
                    "sub_step": "ready",
                    "sub_phase": 5,
                    "sub_total": 5,
                })
            _cb("rendering", base_ctx)
        image, timing = _render_scene(scene_path, variant=v, spp=spp, on_loaded=_on_loaded)
        _cb("saving_output", {
            "pass": pass_name,
            "pass_index": _pass_index[0],
            "total_passes": _total_passes,
        })
        return image, timing
    # ─────────────────────────────────────────────────────────────────────

    def stage_filename(key: str, default: str) -> Path:
        return workspace / config.scene_filename(key, default)

    if _needs_path_total(requested_set):
        _cb("staging_scene", {"pass": "rgb"})
        scene_rgb = _stage_path_scene(
            source_scene,
            stage_filename("rgb", "scene_rgb.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.path_spp,
            width=config.width,
            height=config.height,
            max_depth=config.path_max_depth,
            rr_depth=config.rr_depth,
            samples_per_pass=config.samples_per_pass,
            scene_override=scene_override,
        )
        staged_scenes["rgb"] = str(scene_rgb)
        image, timing = _render_pass(scene_rgb, pass_name="rgb", spp=config.path_spp)
        timing["spp"] = config.path_spp
        rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
        rgb_result, rgb_record = _build_rgb_result(
            "rgb",
            rgb,
            workspace,
            stem=config.artifact_stem("rgb", "rgb"),
            timing=timing,
            scene_path=scene_rgb,
            metadata=_branch_metadata(
                illumination_tag="ambient_room",
                scene_override=scene_override,
            ),
        )
        pass_records["rgb"] = rgb_record
        if "rgb" in requested_set:
            results["rgb"] = rgb_result

    if _needs_direct(requested_set):
        _cb("staging_scene", {"pass": "direct_light_map"})
        scene_direct = _stage_path_scene(
            source_scene,
            stage_filename("direct_light_map", "scene_direct_light_map.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.path_spp,
            width=config.width,
            height=config.height,
            max_depth=config.direct_max_depth,
            rr_depth=config.rr_depth,
            samples_per_pass=config.samples_per_pass,
            scene_override=scene_override,
        )
        staged_scenes["direct_light_map"] = str(scene_direct)
        image, timing = _render_pass(scene_direct, pass_name="direct_light_map", spp=config.path_spp)
        timing["spp"] = config.path_spp
        rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
        direct_result, direct_record = _build_rgb_result(
            "direct_light_map",
            rgb,
            workspace,
            stem=config.artifact_stem("direct_light_map", "direct_light_map"),
            timing=timing,
            scene_path=scene_direct,
            metadata=_branch_metadata(
                illumination_tag="ambient_room",
                scene_override=scene_override,
            ),
        )
        pass_records["direct_light_map"] = direct_record
        if "direct_light_map" in requested_set:
            results["direct_light_map"] = direct_result

    if _needs_diffuse(requested_set):
        _cb("staging_scene", {"pass": "diffuse_map"})
        scene_diffuse = _stage_diffuse_override_scene(
            source_scene,
            stage_filename("diffuse_map", "scene_diffuse_map.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.path_spp,
            width=config.width,
            height=config.height,
            max_depth=config.path_max_depth,
            rr_depth=config.rr_depth,
            samples_per_pass=config.samples_per_pass,
            scene_override=scene_override,
        )
        staged_scenes["diffuse_map"] = str(scene_diffuse)
        image, timing = _render_pass(scene_diffuse, pass_name="diffuse_map", spp=config.path_spp)
        timing["spp"] = config.path_spp
        rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
        diffuse_result, diffuse_record = _build_rgb_result(
            "diffuse_map",
            rgb,
            workspace,
            stem=config.artifact_stem("diffuse_map", "diffuse_map"),
            timing=timing,
            scene_path=scene_diffuse,
            metadata=_branch_metadata(
                illumination_tag="ambient_room",
                scene_override=scene_override,
            ),
        )
        pass_records["diffuse_map"] = diffuse_record
        if "diffuse_map" in requested_set:
            results["diffuse_map"] = diffuse_result

    if _needs_aov(requested_set):
        _cb("staging_scene", {"pass": "aov"})
        scene_aov = _stage_aov_scene(
            source_scene,
            stage_filename("aov", "scene_aov.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.aov_spp,
            width=config.width,
            height=config.height,
            scene_override=scene_override,
        )
        staged_scenes["aov"] = str(scene_aov)
        image, timing = _render_pass(scene_aov, pass_name="aov", spp=config.aov_spp)
        timing["spp"] = config.aov_spp
        if image.ndim != 3 or image.shape[2] < 7:
            raise RuntimeError(f"Unexpected AOV tensor shape: {image.shape}")
        albedo = np.clip(image[:, :, -4:-1], 0.0, 1.0).astype(np.float32)
        depth = image[:, :, -1].astype(np.float32)
        albedo_outputs: dict[str, Any] = {}
        if "albedo" in requested_set:
            albedo_exr = workspace / "albedo.exr"
            albedo_png = workspace / "albedo.png"
            albedo_raw = workspace / "albedo_raw.npz"
            _write_bitmap(albedo_exr, albedo)
            albedo_preview = save_unit_rgb_preview(albedo, albedo_png)
            np.savez_compressed(albedo_raw, albedo=albedo)
            albedo_outputs = {
                "preview": albedo_preview,
                "outputs": {
                    "exr": str(albedo_exr),
                    "png": str(albedo_png),
                    "raw_npz": str(albedo_raw),
                },
            }
            results["albedo"] = ModalityResult(
                name="albedo",
                array=albedo,
                raw_channels={"albedo": albedo},
                metadata=_branch_metadata(
                    illumination_tag="ambient_room",
                    scene_override=scene_override,
                    extra={"preview": albedo_preview},
                ),
                timing={
                    "variant": timing["variant"],
                    "load_scene_s": timing["load_scene_s"],
                    "render_s": timing["render_s"],
                    "scene": str(scene_aov),
                    "spp": config.aov_spp,
                    "total_s": timing["total_s"],
                },
                artifacts=albedo_outputs["outputs"],
            )
        depth_info = save_depth_products(depth, workspace, stem="depth", title="Depth") if "depth" in requested_set else {
            "valid_mask": np.isfinite(depth) & (depth > 0),
        }
        if "depth" in requested_set:
            results["depth"] = ModalityResult(
                name="depth",
                array=depth,
                raw_channels={
                    "depth": depth,
                    "valid": depth_info["valid_mask"].astype(bool),
                },
                metadata={
                    **_branch_metadata(
                        illumination_tag="ambient_room",
                        scene_override=scene_override,
                    ),
                    "valid_pixels": depth_info["valid_pixels"],
                    "depth_p01": depth_info["depth_p01"],
                    "depth_p99": depth_info["depth_p99"],
                    "depth_min": depth_info["depth_min"],
                    "depth_max": depth_info["depth_max"],
                },
                timing={
                    "variant": timing["variant"],
                    "load_scene_s": timing["load_scene_s"],
                    "render_s": timing["render_s"],
                    "scene": str(scene_aov),
                    "spp": config.aov_spp,
                    "total_s": timing["total_s"],
                },
                artifacts={
                    "png": depth_info["png"],
                    "raw_npz": depth_info["raw_npz"],
                },
            )
        pass_records["aov"] = {
            "task": "aov",
            "scene": str(scene_aov),
            "spp": config.aov_spp,
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "total_s": timing["total_s"],
            "albedo": albedo_outputs,
            "depth": {
                key: value
                for key, value in depth_info.items()
                if key != "valid_mask"
            } if "depth" in requested_set else {},
        }
        if _needs_sensor_depth(requested_set) and depth_approx is not None:
            target_names = _target_name_set(depth_approx.target_shape_filenames)
            bounds = _compute_target_union_bounds(source_scene, target_names)
            projected_bbox = None
            if bounds is not None:
                projected_bbox = _project_bounds_to_image_bbox(
                    bounds[0],
                    bounds[1],
                    camera_to_world=camera_to_world,
                    fov_deg=fov_deg,
                    width=config.width,
                    height=config.height,
                )

            _cb("staging_scene", {"pass": "target_mask"})
            scene_mask = _stage_target_mask_scene(
                source_scene,
                stage_filename("target_mask", "scene_target_mask.xml"),
                camera_to_world=camera_to_world,
                fov_deg=fov_deg,
                spp=max(1, config.aov_spp),
                width=config.width,
                height=config.height,
                target_shape_filenames=depth_approx.target_shape_filenames,
            )
            staged_scenes["target_mask"] = str(scene_mask)
            mask_image, mask_timing = _render_pass(scene_mask, pass_name="target_mask", spp=max(1, config.aov_spp))
            mask_timing["spp"] = max(1, config.aov_spp)
            target_mask = _extract_binary_mask(mask_image)
            use_projected_bbox = bool(depth_approx.extras.get("use_projected_bbox", False))
            if projected_bbox is not None and (use_projected_bbox or not np.any(target_mask)):
                x0, y0, x1, y1 = projected_bbox
                bbox_mask = np.zeros((config.height, config.width), dtype=bool)
                bbox_mask[y0:y1, x0:x1] = True
                target_mask = bbox_mask if not np.any(target_mask) else np.logical_or(target_mask, bbox_mask)

            mirror_depth = depth.copy()
            plane_point = None
            plane_normal = None
            if bounds is not None:
                bounds_min, bounds_max = bounds
                plane_point, plane_normal = _select_reflective_plane(bounds_min, bounds_max, camera_to_world)
                mirrored_camera = _reflect_camera_to_world(camera_to_world, plane_point, plane_normal)
                scene_mirror = _stage_aov_scene(
                    source_scene,
                    stage_filename("sensor_depth_mirror", "scene_sensor_depth_mirror.xml"),
                    camera_to_world=mirrored_camera,
                    fov_deg=fov_deg,
                    spp=config.aov_spp,
                    width=config.width,
                    height=config.height,
                )
                staged_scenes["sensor_depth_mirror"] = str(scene_mirror)
                _cb("staging_scene", {"pass": "sensor_depth_mirror"})
                mirror_image, mirror_timing = _render_pass(scene_mirror, pass_name="sensor_depth_mirror", spp=config.aov_spp)
                mirror_timing["spp"] = config.aov_spp
                if mirror_image.ndim == 3 and mirror_image.shape[2] >= 7:
                    mirror_depth = mirror_image[:, :, -1].astype(np.float32)
                pass_records["sensor_depth_mirror"] = {
                    "task": "sensor_depth_mirror",
                    "scene": str(scene_mirror),
                    "spp": config.aov_spp,
                    "load_scene_s": mirror_timing["load_scene_s"],
                    "scene_cache_hit": bool(mirror_timing.get("scene_cache_hit", False)),
                    "render_s": mirror_timing["render_s"],
                    "total_s": mirror_timing["total_s"],
                    "plane_point": plane_point.tolist(),
                    "plane_normal": plane_normal.tolist(),
                }

            sensor_depth = _build_sensor_depth_approx(
                depth,
                target_mask=target_mask,
                mirrored_depth=mirror_depth,
                blur_sigma_px=depth_approx.blur_sigma_px,
                blend=depth_approx.blend,
            )
            sensor_depth_info = save_depth_products(sensor_depth, workspace, stem="sensor_depth_approx", title="Approx Depth")
            results["sensor_depth_approx"] = ModalityResult(
                name="sensor_depth_approx",
                array=sensor_depth.astype(np.float32),
                raw_channels={
                    "depth": sensor_depth.astype(np.float32),
                    "valid": sensor_depth_info["valid_mask"].astype(bool),
                    "target_mask": target_mask.astype(bool),
                    "base_depth": depth.astype(np.float32),
                    "mirrored_depth": mirror_depth.astype(np.float32),
                },
                metadata={
                    **_branch_metadata(
                        illumination_tag="camera_aligned_nir_active",
                        scene_override=scene_override,
                        assist_light=assist_light,
                        depth_model=depth_approx.mode,
                        extra={
                            "target_shape_filenames": list(depth_approx.target_shape_filenames),
                        },
                    ),
                    "valid_pixels": sensor_depth_info["valid_pixels"],
                    "depth_p01": sensor_depth_info["depth_p01"],
                    "depth_p99": sensor_depth_info["depth_p99"],
                    "depth_min": sensor_depth_info["depth_min"],
                    "depth_max": sensor_depth_info["depth_max"],
                },
                timing={
                    "variant": timing["variant"],
                    "load_scene_s": timing["load_scene_s"] + mask_timing["load_scene_s"] + pass_records.get("sensor_depth_mirror", {}).get("load_scene_s", 0.0),
                    "render_s": timing["render_s"] + mask_timing["render_s"] + pass_records.get("sensor_depth_mirror", {}).get("render_s", 0.0),
                    "scene": str(scene_aov),
                    "spp": config.aov_spp,
                    "total_s": timing["total_s"] + mask_timing["total_s"] + pass_records.get("sensor_depth_mirror", {}).get("total_s", 0.0),
                    "source_results": ["depth", "target_mask", "sensor_depth_mirror"] if "sensor_depth_mirror" in pass_records else ["depth", "target_mask"],
                },
                artifacts={
                    "png": sensor_depth_info["png"],
                    "raw_npz": sensor_depth_info["raw_npz"],
                },
            )
            pass_records["target_mask"] = {
                "task": "target_mask",
                "scene": str(scene_mask),
                "spp": max(1, config.aov_spp),
                "load_scene_s": mask_timing["load_scene_s"],
                "scene_cache_hit": bool(mask_timing.get("scene_cache_hit", False)),
                "render_s": mask_timing["render_s"],
                "total_s": mask_timing["total_s"],
                "mask_pixels": int(np.count_nonzero(target_mask)),
                "projected_bbox": list(projected_bbox) if projected_bbox is not None else None,
            }

    if _needs_active_nir(requested_set) and assist_light is not None:
        scene_active = _stage_path_scene(
            source_scene,
            stage_filename("active_nir_intensity", "scene_active_nir.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.polar_spp,
            width=config.width,
            height=config.height,
            max_depth=config.path_max_depth,
            rr_depth=config.rr_depth,
            samples_per_pass=config.samples_per_pass,
            scene_override=scene_override,
            assist_light=assist_light,
        )
        staged_scenes["active_nir_intensity"] = str(scene_active)
        _cb("staging_scene", {"pass": "active_nir_intensity"})
        image, timing = _render_pass(scene_active, pass_name="active_nir_intensity", spp=config.polar_spp)
        timing["spp"] = config.polar_spp
        rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
        intensity = np.tensordot(rgb, np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axes=([2], [0])).astype(np.float32)
        nir_result, nir_record = _build_grayscale_result(
            "active_nir_intensity",
            intensity,
            workspace,
            stem=config.artifact_stem("active_nir_intensity", "active_nir_intensity"),
            timing=timing,
            scene_path=scene_active,
            metadata=_branch_metadata(
                illumination_tag="camera_aligned_nir_active",
                scene_override=scene_override,
                assist_light=assist_light,
            ),
        )
        pass_records["active_nir_intensity"] = nir_record
        results["active_nir_intensity"] = nir_result

    polarization_material_mode = "not_requested"
    if _needs_polar(requested_set):
        polar_nested = "volpath" if assist_light is not None and assist_light.polarized else "direct"
        polar_illumination_tag = "camera_aligned_nir_active_polarized" if assist_light is not None else "ambient_room"
        scene_polar = _stage_stokes_scene(
            source_scene,
            stage_filename("polar", "scene_polar.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.polar_spp,
            width=config.width,
            height=config.height,
            samples_per_pass=config.samples_per_pass,
            scene_override=scene_override,
            assist_light=assist_light,
            nested_integrator_type=polar_nested,
        )
        scene_polar_fallback = _stage_polarized_fallback_scene(
            source_scene,
            stage_filename("polar_fallback", "scene_polar_fallback.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=config.polar_spp,
            width=config.width,
            height=config.height,
            samples_per_pass=config.samples_per_pass,
            scene_override=scene_override,
            assist_light=assist_light,
            nested_integrator_type=polar_nested,
        )
        staged_scenes["polar"] = str(scene_polar)
        staged_scenes["polar_fallback"] = str(scene_polar_fallback)
        _cb("staging_scene", {"pass": "polar"})

        requested_polar = {modality for modality in requested_set if modality in {"polar_rgb_preview", "dop", "aolp", "s1", "s2"}}
        polar_scene_used = scene_polar
        fallback_used = False
        try:
            image, timing = _render_pass(scene_polar, pass_name="polar", spp=config.polar_spp, variant_override=_polar_variant(variant))
            timing["spp"] = config.polar_spp
            summary, arrays = save_polarization_products(image, workspace, requested_polar)
            polarization_material_mode = "original_scene"
            weak_scales = max(float(summary["s1_scale_abs_p995"]), float(summary["s2_scale_abs_p995"])) < config.polar_scale_threshold
            invalid_pixels = int(summary.get("invalid_pixel_count", 0))
            finite_ratio = float(summary.get("finite_ratio", 1.0))
            invalid_polar = finite_ratio < 0.999 or invalid_pixels > 2000
            if weak_scales or invalid_polar:
                fallback_workspace = workspace / "_polar_fallback_candidate"
                fallback_workspace.mkdir(parents=True, exist_ok=True)
                fallback_image, fallback_timing = _render_pass(scene_polar_fallback, pass_name="polar_fallback", spp=config.polar_spp, variant_override=_polar_variant(variant))
                fallback_timing["spp"] = config.polar_spp
                fallback_summary, fallback_arrays = save_polarization_products(fallback_image, fallback_workspace, requested_polar)
                prefer_fallback = weak_scales
                if not prefer_fallback:
                    fallback_ratio = float(fallback_summary.get("finite_ratio", 0.0))
                    fallback_invalid = int(fallback_summary.get("invalid_pixel_count", 0))
                    prefer_fallback = (
                        fallback_ratio > finite_ratio
                        or (abs(fallback_ratio - finite_ratio) < 1e-9 and fallback_invalid < invalid_pixels)
                    )
                if prefer_fallback:
                    image = fallback_image
                    timing = fallback_timing
                    summary, arrays = save_polarization_products(image, workspace, requested_polar)
                    polarization_material_mode = "pplastic_fallback"
                    polar_scene_used = scene_polar_fallback
                    fallback_used = True
        except Exception:
            image, timing = _render_pass(scene_polar_fallback, pass_name="polar_fallback", spp=config.polar_spp, variant_override=_polar_variant(variant))
            timing["spp"] = config.polar_spp
            summary, arrays = save_polarization_products(image, workspace, requested_polar)
            polarization_material_mode = "pplastic_fallback"
            polar_scene_used = scene_polar_fallback
            fallback_used = True

        pass_records["polarization"] = {
            "task": "polar",
            "scene": str(polar_scene_used),
            "spp": config.polar_spp,
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "total_s": timing["total_s"],
            "material_mode": polarization_material_mode,
            "selected_polar_scene": "polar_fallback" if fallback_used else "polar",
            "fallback_used": fallback_used,
            "illumination_tag": polar_illumination_tag,
            "stokes_shape": list(image.shape),
            "polarization": summary,
        }
        shared_timing = {
            "variant": timing["variant"],
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "scene": str(polar_scene_used),
            "spp": config.polar_spp,
            "total_s": timing["total_s"],
            "material_mode": polarization_material_mode,
        }
        shared_artifacts = {
            "stokes_npz": summary["outputs"]["stokes_npz"],
        }
        shared_metadata = _branch_metadata(
            illumination_tag=polar_illumination_tag,
            scene_override=scene_override,
            assist_light=assist_light,
            extra={
                "material_mode": polarization_material_mode,
                "fallback_used": fallback_used,
                "selected_polar_scene": "polar_fallback" if fallback_used else "polar",
                "invalid_pixel_count": int(summary.get("invalid_pixel_count", 0)),
                "finite_ratio": float(summary.get("finite_ratio", 1.0)),
            },
        )
        if "polar_rgb_preview" in requested_set:
            results["polar_rgb_preview"] = ModalityResult(
                name="polar_rgb_preview",
                array=arrays["rgb"],
                raw_channels={
                    "rgb": arrays["rgb"],
                    "mask": arrays["mask"],
                },
                metadata=dict(shared_metadata),
                timing=dict(shared_timing),
                artifacts={**shared_artifacts, "png": summary["outputs"]["rgb_preview"]},
            )
        if "dop" in requested_set:
            results["dop"] = ModalityResult(
                name="dop",
                array=arrays["dop"],
                raw_channels={
                    "dop": arrays["dop"],
                    "mask": arrays["mask"],
                    "s0_l": arrays["s0_l"],
                },
                metadata={
                    **shared_metadata,
                    "range": [0.0, 1.0],
                },
                timing=dict(shared_timing),
                artifacts={**shared_artifacts, "png": summary["outputs"]["dop"]},
            )
        if "aolp" in requested_set:
            results["aolp"] = ModalityResult(
                name="aolp",
                array=arrays["aolp_deg"],
                raw_channels={
                    "aolp_deg": arrays["aolp_deg"],
                    "dop": arrays["dop"],
                    "mask": arrays["mask"],
                },
                metadata={
                    **shared_metadata,
                    "range_degrees": [0.0, 180.0],
                },
                timing=dict(shared_timing),
                artifacts={**shared_artifacts, "png": summary["outputs"]["aolp"]},
            )
        if "s1" in requested_set:
            results["s1"] = ModalityResult(
                name="s1",
                array=arrays["s1_l"],
                raw_channels={
                    "s1_l": arrays["s1_l"],
                    "mask": arrays["mask"],
                },
                metadata={
                    **shared_metadata,
                    "scale_abs_p995": summary["s1_scale_abs_p995"],
                },
                timing=dict(shared_timing),
                artifacts={**shared_artifacts, "png": summary["outputs"]["s1"]},
            )
        if "s2" in requested_set:
            results["s2"] = ModalityResult(
                name="s2",
                array=arrays["s2_l"],
                raw_channels={
                    "s2_l": arrays["s2_l"],
                    "mask": arrays["mask"],
                },
                metadata={
                    **shared_metadata,
                    "scale_abs_p995": summary["s2_scale_abs_p995"],
                },
                timing=dict(shared_timing),
                artifacts={**shared_artifacts, "png": summary["outputs"]["s2"]},
            )

    if "indirect_light_map" in requested_set:
        total_rgb = pass_records["rgb"]["outputs"]["raw_npz"]
        direct_rgb = pass_records["direct_light_map"]["outputs"]["raw_npz"]
        total_arr = np.load(total_rgb)["rgb"].astype(np.float32)
        direct_arr = np.load(direct_rgb)["rgb"].astype(np.float32)
        indirect = np.clip(total_arr - direct_arr, 0.0, None)
        results["indirect_light_map"] = _compose_derived_result(
            "indirect_light_map",
            indirect,
            workspace,
            timing_seed={
                "source_results": ["rgb", "direct_light_map"],
            },
            dependencies={
                "rgb": total_rgb,
                "direct_light_map": direct_rgb,
            },
        )
    if "specular_map" in requested_set:
        total_rgb = pass_records["rgb"]["outputs"]["raw_npz"]
        diffuse_rgb = pass_records["diffuse_map"]["outputs"]["raw_npz"]
        total_arr = np.load(total_rgb)["rgb"].astype(np.float32)
        diffuse_arr = np.load(diffuse_rgb)["rgb"].astype(np.float32)
        specular = np.clip(total_arr - diffuse_arr, 0.0, None)
        results["specular_map"] = _compose_derived_result(
            "specular_map",
            specular,
            workspace,
            timing_seed={
                "source_results": ["rgb", "diffuse_map"],
            },
            dependencies={
                "rgb": total_rgb,
                "diffuse_map": diffuse_rgb,
            },
        )

    if any(modality in requested_set for modality in ("indirect_light_map", "specular_map")):
        total_arr = np.load(pass_records["rgb"]["outputs"]["raw_npz"])["rgb"].astype(np.float32) if "rgb" in pass_records else None
        direct_arr = np.load(pass_records["direct_light_map"]["outputs"]["raw_npz"])["rgb"].astype(np.float32) if "direct_light_map" in pass_records else None
        diffuse_arr = np.load(pass_records["diffuse_map"]["outputs"]["raw_npz"])["rgb"].astype(np.float32) if "diffuse_map" in pass_records else None
        pass_records["derived"] = {
            "assumptions": {
                "direct_light_map": "Path tracer with max_depth=2.",
                "indirect_light_map": "Clamped difference max(path_total - direct_light_map, 0).",
                "diffuse_map": "Path tracer on a diffuse-override scene preserving base color textures and keeping glass as rough dielectric.",
                "specular_map": "Clamped difference max(path_total - diffuse_map, 0).",
            },
            "difference_stats": {
                "indirect_negative_pixels_before_clamp": int(np.count_nonzero((total_arr - direct_arr) < 0.0)) if total_arr is not None and direct_arr is not None else 0,
                "specular_negative_pixels_before_clamp": int(np.count_nonzero((total_arr - diffuse_arr) < 0.0)) if total_arr is not None and diffuse_arr is not None else 0,
            },
        }
        if "indirect_light_map" in results:
            pass_records["derived"]["indirect_light_map"] = {
                "preview": results["indirect_light_map"].metadata["preview"],
                "outputs": results["indirect_light_map"].artifacts,
            }
        if "specular_map" in results:
            pass_records["derived"]["specular_map"] = {
                "preview": results["specular_map"].metadata["preview"],
                "outputs": results["specular_map"].artifacts,
            }

    return MultimodalRenderResult(
        scene={
            "source_scene": str(source_scene),
            "workspace": str(workspace),
            "temporary_workspace": temporary_workspace,
            "staged_scenes": staged_scenes,
            "polarization_material_mode": polarization_material_mode,
            "scene_override": asdict(scene_override) if scene_override is not None else None,
            "assist_light": asdict(assist_light) if assist_light is not None else None,
            "depth_approx": asdict(depth_approx) if depth_approx is not None else None,
            "start_time": now_iso(),
        },
        camera={
            "camera_to_world": np.asarray(camera_to_world, dtype=np.float32).tolist(),
            "fov_deg": float(fov_deg),
            "convention": "cam-to-world, local -Z forward, local +Y up",
        },
        config=config,
        definitions=dict(MODALITY_DEFINITIONS),
        results=results,
        pass_records=pass_records,
    )


def render_rgb(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(*args, modalities=["rgb"], **kwargs)


def render_depth(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(*args, modalities=["depth"], **kwargs)


def render_polarization(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(*args, modalities=["polar_rgb_preview", "dop", "aolp", "s1", "s2"], **kwargs)


def render_decomposition(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(
        *args,
        modalities=["albedo", "direct_light_map", "indirect_light_map", "diffuse_map", "specular_map"],
        **kwargs,
    )
