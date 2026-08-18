"""Independent close-up A/B utilities for the spatial-PBR F0-only adapter.

This module intentionally has no RenderRequest or daemon dependency.  It builds
two XML scenes which differ only in the object BSDF and provides the UV-atlas to
screen-space resampling and paired metrics used by the experiment CLI.
"""
from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_obj_bounds(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lo = np.full(3, np.inf, dtype=np.float64)
    hi = np.full(3, -np.inf, dtype=np.float64)
    count = 0
    with Path(path).open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            fields = line.split()
            if len(fields) < 4:
                continue
            point = np.asarray(fields[1:4], dtype=np.float64)
            lo = np.minimum(lo, point)
            hi = np.maximum(hi, point)
            count += 1
    if not count or not np.all(np.isfinite([lo, hi])):
        raise ValueError(f"OBJ has no finite vertices: {path}")
    return lo.astype(np.float32), hi.astype(np.float32)


def normalize(vector: Sequence[float]) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(value))
    if norm <= 1e-12:
        raise ValueError("cannot normalize a zero vector")
    return (value / norm).astype(np.float32)


def lookat_camera(center: np.ndarray, radius: float, *, azimuth_deg: float,
                  fov_deg: float, frame_fill: float) -> tuple[np.ndarray, np.ndarray]:
    half_extent = max(1e-5, math.tan(math.radians(fov_deg) * 0.5) * frame_fill)
    distance = max(radius / half_extent, radius * 1.5)
    angle = math.radians(azimuth_deg)
    origin = np.asarray(center, dtype=np.float32) + np.asarray(
        [math.sin(angle) * distance, 0.0, math.cos(angle) * distance], dtype=np.float32
    )
    forward = normalize(np.asarray(center) - origin)
    right = normalize(np.cross(forward, [0.0, 1.0, 0.0]))
    up = normalize(np.cross(right, forward))
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, 0] = right
    matrix[:3, 1] = up
    matrix[:3, 2] = -forward
    matrix[:3, 3] = origin
    return matrix, origin


def area_light_matrix(center: np.ndarray, camera_origin: np.ndarray, radius: float,
                      *, azimuth_deg: float, elevation_deg: float,
                      distance_radii: float, half_size_radii: float) -> np.ndarray:
    back = normalize(np.asarray(camera_origin) - np.asarray(center))
    right = normalize(np.cross([0.0, 1.0, 0.0], back))
    a = math.radians(azimuth_deg)
    e = math.radians(elevation_deg)
    horizontal = normalize(math.cos(a) * back + math.sin(a) * right)
    direction = normalize(math.cos(e) * horizontal + math.sin(e) * np.asarray([0, 1, 0]))
    position = np.asarray(center) + direction * (float(radius) * float(distance_radii))
    normal = normalize(np.asarray(center) - position)
    x_axis = normalize(np.cross([0.0, 1.0, 0.0], normal))
    if abs(float(np.dot(normal, [0.0, 1.0, 0.0]))) > 0.98:
        x_axis = normalize(np.cross([0.0, 0.0, 1.0], normal))
    y_axis = normalize(np.cross(normal, x_axis))
    half_size = float(radius) * float(half_size_radii)
    matrix = np.eye(4, dtype=np.float32)
    matrix[:3, 0] = x_axis * half_size
    matrix[:3, 1] = y_axis * half_size
    matrix[:3, 2] = normal
    matrix[:3, 3] = position
    return matrix


def _matrix_text(matrix: np.ndarray) -> str:
    return " ".join(f"{float(value):.9g}" for value in np.asarray(matrix).reshape(-1))


def _bitmap(parent: ET.Element, name: str, path: Path, *, raw: bool = False) -> ET.Element:
    node = ET.SubElement(parent, "texture", {"type": "bitmap", "name": name})
    ET.SubElement(node, "string", {"name": "filename", "value": str(Path(path).resolve())})
    if raw:
        ET.SubElement(node, "boolean", {"name": "raw", "value": "true"})
    return node


def _base_texture(parent: ET.Element, name: str, material: Mapping[str, Any]) -> None:
    _bitmap(parent, name, Path(material["base_color"]), raw=False)


def part_optical_class(material: Mapping[str, Any], part_index: int) -> str:
    """Optical class of one material slot, not of the whole unit.

    A unit's ``optical_class`` describes its *container* material only.  The
    mushroom-in-a-jar unit is 90K triangles of glass and 2.9M of diffuse
    mushrooms/sand, so applying the unit class to every part renders the
    mushrooms as glass - the exact defect dev_report 2026-07-28 (polar LOD)
    fixed for the per-slot renderer.  Resolve per part and fall back to the
    unit class only when the part carries no material id.
    """
    classes = material.get("part_optical_classes") or []
    if 0 <= part_index < len(classes) and classes[part_index]:
        return str(classes[part_index]).lower()
    return str(material.get("optical_class") or "diffuse").lower()


def _wrap_normal(shape: ET.Element, material: Mapping[str, Any],
                 optical_class: str) -> ET.Element:
    # Mitsuba rejects transmission BSDFs nested below ``twosided``.  Only the
    # transmissive slot skips the wrapper; opaque slots keep it for back-face
    # visibility.
    is_transmissive = optical_class.startswith("glass")
    outer = shape if is_transmissive else ET.SubElement(shape, "bsdf", {"type": "twosided"})
    normal = material.get("normal")
    if normal:
        wrapper = ET.SubElement(outer, "bsdf", {"type": "normalmap"})
        _bitmap(wrapper, "normalmap", Path(str(normal)), raw=True)
        return wrapper
    return outer


def _analytic_material(parent: ET.Element, material: Mapping[str, Any],
                       optical_class: str) -> dict[str, Any]:
    roughness = Path(material["roughness_raw"])
    if optical_class.startswith("glass"):
        # Smooth dielectric only. roughdielectric returns DoLP=0 in the polarized
        # build (dev_report 2026-07-06 §2.1), which would make the analytic
        # baseline trivially unpolarized and void the A/B polarization contrast.
        # Roughness is therefore dropped rather than fed to a BSDF that cannot
        # carry the Fresnel polarization signal.
        bsdf = ET.SubElement(parent, "bsdf", {"type": "dielectric"})
        ET.SubElement(bsdf, "float", {"name": "int_ior", "value": "1.5"})
        return {"type": "dielectric", "alpha": "dropped_smooth_only", "int_ior": 1.5}
    if optical_class.startswith("metal"):
        preset = "Al"
        for token, candidate in (("gold", "Au"), ("copper", "Cu"), ("steel", "Cr"), ("iron", "Cr")):
            if token in optical_class:
                preset = candidate
        bsdf = ET.SubElement(parent, "bsdf", {"type": "roughconductor"})
        ET.SubElement(bsdf, "string", {"name": "material", "value": preset})
        _base_texture(bsdf, "specular_reflectance", material)
        _bitmap(bsdf, "alpha", roughness, raw=True)
        return {"type": "roughconductor", "alpha": "raw_roughness", "preset": preset}
    bsdf = ET.SubElement(parent, "bsdf", {"type": "pplastic"})
    ET.SubElement(bsdf, "float", {"name": "int_ior", "value": "1.5"})
    _base_texture(bsdf, "diffuse_reflectance", material)
    _bitmap(bsdf, "alpha", roughness, raw=True)
    return {"type": "pplastic", "alpha": "raw_roughness", "int_ior": 1.5}


def _spatial_material(parent: ET.Element, material: Mapping[str, Any],
                      optical_class: str) -> dict[str, Any]:
    if optical_class.startswith("glass"):
        # The spatial layer has no transmission path: blendbsdf(pplastic,
        # roughconductor) is opaque by construction.  Routing a glass slot
        # through it would turn the jar into stone, so transmissive slots keep
        # the analytic dielectric in BOTH branches and act as a true no-op.
        summary = _analytic_material(parent, material, optical_class)
        summary["spatial"] = "bypassed_transmissive_slot"
        return summary
    blend = ET.SubElement(parent, "bsdf", {"type": "blendbsdf"})
    _bitmap(blend, "weight", Path(material["metallic"]), raw=True)
    plastic = ET.SubElement(blend, "bsdf", {"type": "pplastic"})
    ET.SubElement(plastic, "float", {"name": "int_ior", "value": "1.5"})
    _base_texture(plastic, "diffuse_reflectance", material)
    _bitmap(plastic, "alpha", Path(material["alpha"]), raw=True)
    metal = ET.SubElement(blend, "bsdf", {"type": "roughconductor"})
    # eta/k are spectral-valued parameters. ``raw=true`` disables Mitsuba's
    # RGB-to-spectrum conversion and makes polarized spectral variants reject
    # the texture outright. EXR is already linear; leaving raw unset preserves
    # linear samples while enabling the required spectral upsampling.
    _bitmap(metal, "eta", Path(material["eta"]), raw=False)
    _bitmap(metal, "k", Path(material["k"]), raw=False)
    _bitmap(metal, "alpha", Path(material["alpha"]), raw=True)
    return {
        "type": "blendbsdf", "weight": "continuous_metallic", "plastic": "pplastic",
        "conductor": "roughconductor", "alpha": "roughness_squared",
        "eta_k": "continuous_F0_eta1",
    }


def build_scene_xml(*, path: Path, branch: str, obj_path: Path,
                    material: Mapping[str, Any], camera_to_world: np.ndarray,
                    light_to_world: np.ndarray, bounds_min: np.ndarray,
                    bounds_max: np.ndarray, resolution: int, spp: int,
                    fov_deg: float, radiance: float, seed: int) -> dict[str, Any]:
    """Write one controlled scene. Geometry/camera/light are branch invariant."""
    if branch not in {"A", "B"}:
        raise ValueError(f"unknown branch: {branch}")
    root = ET.Element("scene", {"version": "3.0.0"})
    integrator = ET.SubElement(root, "integrator", {"type": "path"})
    ET.SubElement(integrator, "integer", {"name": "max_depth", "value": "8"})
    sensor = ET.SubElement(root, "sensor", {"type": "perspective"})
    ET.SubElement(sensor, "float", {"name": "fov", "value": f"{fov_deg:.8g}"})
    transform = ET.SubElement(sensor, "transform", {"name": "to_world"})
    ET.SubElement(transform, "matrix", {"value": _matrix_text(camera_to_world)})
    sampler = ET.SubElement(sensor, "sampler", {"type": "independent"})
    ET.SubElement(sampler, "integer", {"name": "sample_count", "value": str(int(spp))})
    # Mitsuba's default render seed is zero. Keep the explicit experiment seed in
    # XML as an invariant comment without relying on a sampler property that is
    # not portable across the two local Mitsuba builds.
    sampler.append(ET.Comment(f" deterministic render seed={int(seed)} (mi.render default) "))
    film = ET.SubElement(sensor, "film", {"type": "hdrfilm"})
    ET.SubElement(film, "integer", {"name": "width", "value": str(int(resolution))})
    ET.SubElement(film, "integer", {"name": "height", "value": str(int(resolution))})

    # A GLB can contain several material primitives. Keep every materialized
    # part as a separate shape; using trimesh's combined Scene export can drop
    # node transforms and collapse the object to a thin subset of the mesh.
    obj_parts = [Path(value) for value in (material.get("obj_parts") or [obj_path])]
    part_materials = list(material.get("parts") or [])
    summary: dict[str, Any] | None = None
    for part_index, part_path in enumerate(obj_parts):
        shape_id = "experiment_object" if part_index == 0 else f"experiment_object_part_{part_index:03d}"
        shape = ET.SubElement(root, "shape", {"type": "obj", "id": shape_id})
        ET.SubElement(shape, "string", {"name": "filename", "value": str(part_path.resolve())})
        # Each GLB part owns its UV layout and its own converted atlas.  Fall
        # back to the unit-level maps only when no per-part material exists
        # (single-mesh assets and the OBJ fallback path).
        part_material = part_materials[part_index] if part_index < len(part_materials) else material
        optical_class = part_optical_class(material, part_index)
        parent = _wrap_normal(shape, part_material, optical_class)
        part_summary = (
            _analytic_material(parent, part_material, optical_class) if branch == "A"
            else _spatial_material(parent, part_material, optical_class)
        )
        if summary is None:
            summary = part_summary
    assert summary is not None

    center = (np.asarray(bounds_min) + np.asarray(bounds_max)) * 0.5
    radius = float(np.linalg.norm(np.asarray(bounds_max) - np.asarray(bounds_min)) * 0.5)
    floor_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": "neutral_floor"})
    floor_matrix = np.asarray([
        [radius * 4, 0, 0, center[0]], [0, 0, 1, float(bounds_min[1]) - 2e-4],
        [0, radius * 4, 0, center[2]], [0, 0, 0, 1],
    ], dtype=np.float32)
    floor_transform = ET.SubElement(floor_shape, "transform", {"name": "to_world"})
    ET.SubElement(floor_transform, "matrix", {"value": _matrix_text(floor_matrix)})
    floor_bsdf = ET.SubElement(floor_shape, "bsdf", {"type": "diffuse"})
    ET.SubElement(floor_bsdf, "rgb", {"name": "reflectance", "value": "0.025 0.025 0.025"})

    light = ET.SubElement(root, "shape", {"type": "rectangle", "id": "key_area"})
    light_transform = ET.SubElement(light, "transform", {"name": "to_world"})
    ET.SubElement(light_transform, "matrix", {"value": _matrix_text(light_to_world)})
    emitter = ET.SubElement(light, "emitter", {"type": "area"})
    ET.SubElement(emitter, "rgb", {"name": "radiance", "value": f"{float(radiance):.8g}"})
    ET.indent(root, space="  ")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return summary


def scene_invariants(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    obj = root.find("./shape[@id='experiment_object']")
    sensor = root.find("./sensor")
    light = root.find("./shape[@id='key_area']")
    normal = obj.find(".//texture[@name='normalmap']/string[@name='filename']") if obj is not None else None
    filename = obj.find("./string[@name='filename']") if obj is not None else None
    camera = sensor.find("./transform[@name='to_world']/matrix") if sensor is not None else None
    light_matrix = light.find("./transform[@name='to_world']/matrix") if light is not None else None
    film = sensor.find("./film") if sensor is not None else None
    sampler = sensor.find("./sampler") if sensor is not None else None
    return {
        "geometry": [node.find("./string[@name='filename']").attrib.get("value")
                     for node in root.findall("./shape")
                     if node.attrib.get("id", "").startswith("experiment_object")
                     and node.find("./string[@name='filename']") is not None],
        "normal": normal.attrib.get("value") if normal is not None else None,
        "camera": camera.attrib.get("value") if camera is not None else None,
        "light": light_matrix.attrib.get("value") if light_matrix is not None else None,
        "resolution": [
            film.find("./integer[@name='width']").attrib["value"],
            film.find("./integer[@name='height']").attrib["value"],
        ] if film is not None else None,
        "sample_count": sampler.find("./integer[@name='sample_count']").attrib["value"] if sampler is not None else None,
        "obj_sha256": [sha256_file(Path(value)) for value in (
            node.find("./string[@name='filename']").attrib["value"]
            for node in root.findall("./shape")
            if node.attrib.get("id", "").startswith("experiment_object")
            and node.find("./string[@name='filename']") is not None
        )],
    }


def assert_scene_pair_invariants(path_a: Path, path_b: Path) -> dict[str, Any]:
    a, b = scene_invariants(path_a), scene_invariants(path_b)
    if a != b:
        differences = {key: [a.get(key), b.get(key)] for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)}
        raise RuntimeError(f"A/B scene invariant mismatch: {differences}")
    return a


def resample_atlas_to_screen(uv: np.ndarray, object_mask: np.ndarray,
                             atlas: np.ndarray) -> np.ndarray:
    uv = np.asarray(uv, dtype=np.float32)
    mask = np.asarray(object_mask, dtype=bool)
    source = np.asarray(atlas)
    if uv.shape[:2] != mask.shape or uv.shape[-1] != 2:
        raise ValueError(f"UV/mask shape mismatch: {uv.shape}, {mask.shape}")
    height, width = source.shape[:2]
    x = np.clip(np.floor(uv[..., 0] * width).astype(np.int64), 0, width - 1)
    y = np.clip(np.floor((1.0 - uv[..., 1]) * height).astype(np.int64), 0, height - 1)
    sampled = source[y, x]
    result = np.zeros(mask.shape + source.shape[2:], dtype=source.dtype)
    result[mask] = sampled[mask]
    return result


def screen_space_maps(uv: np.ndarray, object_mask: np.ndarray,
                      atlas_maps: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    maps = {key: resample_atlas_to_screen(uv, object_mask, value) for key, value in atlas_maps.items()}
    metallic = np.asarray(maps["metallic"], dtype=np.float32)
    maps["object_mask"] = np.asarray(object_mask, dtype=bool)
    maps["metal_mask"] = np.asarray(object_mask, bool) & (metallic >= 0.5)
    maps["dielectric_mask"] = np.asarray(object_mask, bool) & (metallic < 0.5)
    if np.any(maps["metal_mask"] & ~maps["object_mask"]) or np.any(maps["dielectric_mask"] & ~maps["object_mask"]):
        raise AssertionError("screen-space ROI leaked outside object mask")
    return maps


def aolp_circular_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return 0.5 * np.abs(np.angle(np.exp(2j * (np.asarray(a) - np.asarray(b)))))


def roi_metrics(stokes_a: Mapping[str, np.ndarray], stokes_b: Mapping[str, np.ndarray],
                roi: np.ndarray) -> dict[str, Any]:
    mask = np.asarray(roi, dtype=bool)
    finite = mask.copy()
    for key in ("rgb", "dop", "aolp", "s1_over_s0", "s2_over_s0"):
        aa, bb = np.asarray(stokes_a[key]), np.asarray(stokes_b[key])
        finite &= np.all(np.isfinite(aa), axis=-1) & np.all(np.isfinite(bb), axis=-1) if aa.ndim == 3 else np.isfinite(aa) & np.isfinite(bb)
    count = int(np.count_nonzero(finite))
    if not count:
        return {"pixels": 0, "coverage": 0.0}
    rgb_a, rgb_b = np.asarray(stokes_a["rgb"]), np.asarray(stokes_b["rgb"])
    rgb_relative = np.abs(rgb_a - rgb_b) / np.maximum(0.5 * (np.abs(rgb_a) + np.abs(rgb_b)), 1e-4)
    delta_dop = np.abs(np.asarray(stokes_a["dop"]) - np.asarray(stokes_b["dop"]))
    delta_aolp = aolp_circular_distance(np.asarray(stokes_a["aolp"]), np.asarray(stokes_b["aolp"]))
    weight = np.minimum(np.asarray(stokes_a["dop"]), np.asarray(stokes_b["dop"]))
    weight_sum = float(np.sum(weight[finite]))
    def mae(key: str) -> float:
        return float(np.mean(np.abs(np.asarray(stokes_a[key])[finite] - np.asarray(stokes_b[key])[finite])))
    return {
        "pixels": count,
        "coverage": float(count / mask.size),
        "rgb_relative_mae": float(np.mean(rgb_relative[finite])),
        "delta_dolp_mean": float(np.mean(delta_dop[finite])),
        "delta_dolp_p95": float(np.quantile(delta_dop[finite], 0.95)),
        "delta_dolp_gt_005_fraction": float(np.mean(delta_dop[finite] > 0.05)),
        "weighted_aolp_distance_rad": float(np.sum(delta_aolp[finite] * weight[finite]) / weight_sum) if weight_sum > 0 else 0.0,
        "s1_over_s0_mae": mae("s1_over_s0"),
        "s2_over_s0_mae": mae("s2_over_s0"),
    }


def rgb_roi_metrics(rgb_a: np.ndarray, rgb_b: np.ndarray,
                    roi: np.ndarray) -> dict[str, Any]:
    """Compute linear-RGB A/B differences for one screen-space ROI."""
    a = np.asarray(rgb_a, dtype=np.float32)
    b = np.asarray(rgb_b, dtype=np.float32)
    mask = np.asarray(roi, dtype=bool)
    if a.shape != b.shape or a.ndim != 3 or a.shape[-1] < 3 or a.shape[:2] != mask.shape:
        raise ValueError(f"RGB/ROI shape mismatch: {a.shape}, {b.shape}, {mask.shape}")
    finite = mask & np.all(np.isfinite(a[..., :3]), axis=-1) & np.all(np.isfinite(b[..., :3]), axis=-1)
    count = int(np.count_nonzero(finite))
    if not count:
        return {"pixels": 0, "coverage": 0.0}
    aa, bb = a[..., :3], b[..., :3]
    absolute = np.abs(aa - bb)
    relative = absolute / np.maximum(0.5 * (np.abs(aa) + np.abs(bb)), 1e-4)
    return {
        "pixels": count,
        "coverage": float(count / mask.size),
        "linear_rgb_mae": float(np.mean(absolute[finite])),
        "linear_rgb_relative_mae": float(np.mean(relative[finite])),
        "linear_rgb_p95": float(np.quantile(absolute[finite], 0.95)),
    }


def paired_bootstrap(values: Sequence[float], *, samples: int = 2000,
                     seed: int = 20260713) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    array = array[np.isfinite(array)]
    if not len(array):
        return {"n": 0, "mean": None, "ci95": [None, None]}
    rng = np.random.default_rng(seed)
    draws = rng.choice(array, size=(int(samples), len(array)), replace=True).mean(axis=1)
    return {"n": int(len(array)), "mean": float(array.mean()),
            "ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
