#!/usr/bin/env python3
"""Render inverse-rendering observations, PBR GT maps, and masks."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import gc
import json
import math
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.material_pipeline import (  # noqa: E402
    OPAQUE_PBR_DOMAIN,
    SPECULAR_MASKED_PBR_DOMAIN,
    STRUCTURAL_SPECULAR_PBR_DOMAIN,
    SUPPORTED_SURFACE_DOMAINS,
    uses_specular_semantic_masks,
    build_band_scene,
    materialize_ir_effective_scene,
    render_property_maps,
    validate_ir_effective_scene,
)
from mitsuba_converter.multimodal import (  # noqa: E402
    cap_scene_texture_resolution,
    camera_to_world_to_lookat,
)
from robomituba_bridge.camera_pose import resolve_viewpoint_pose  # noqa: E402

EYE_HEIGHT_M = 1.2
LUMINANCE = np.asarray([0.2126, 0.7152, 0.0722], np.float32)
WEIGHT_RE = re.compile(r"^.*\.weight\.value$")

OBSERVATION_VARIANT_CHOICES = (
    "auto", "cuda_ad_rgb", "cuda_ad_spectral",
    "cuda_ad_rgb_polarized", "cuda_ad_spectral_polarized",
)


def _resolve_observation_variant(
    available_variants: list[str] | tuple[str, ...], *, polarized: bool, requested: str,
) -> str:
    """Select the fastest valid carrier without changing the requested sensor contract."""
    available = set(available_variants)
    if requested != "auto":
        if requested not in available:
            raise RuntimeError(
                f"requested observation variant {requested!r} is not compiled; "
                f"available={sorted(available)}"
            )
        if bool(polarized) != requested.endswith("_polarized"):
            raise RuntimeError(
                f"observation variant {requested!r} does not match polarized={polarized}"
            )
        return requested
    candidates = (
        ("cuda_ad_rgb_polarized", "cuda_ad_spectral_polarized")
        if polarized else ("cuda_ad_rgb", "cuda_ad_spectral")
    )
    selected = next((variant for variant in candidates if variant in available), None)
    if selected is None:
        raise RuntimeError(
            f"no compiled observation variant for polarized={polarized}; "
            f"tried={candidates}, available={sorted(available)}"
        )
    return selected


def _publish_frame_dir(out: Path, frame_id: str) -> Path:
    """Create a frame directory only once it has a rendered artifact to publish."""
    frame_dir = out / frame_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    return frame_dir


def _write_exr(path: Path, values: np.ndarray) -> None:
    import mitsuba as mi
    array = np.ascontiguousarray(np.asarray(values, np.float32))
    if array.ndim == 2:
        array = array[..., None]
    mi.Bitmap(array).write(str(path))




# Canonical GT storage is independent of the EXR observation writer above.
# It keeps all frames of one modality together and makes the numerical decode
# rule explicit instead of depending on a viewer's color-management defaults.
_GT_ARTIFACT_LAYOUT = "modality_first_v1"
_PNG16_MAX = 65535.0
_GT_PNG_SPECS = {
    "rgb_albedo": {"directory": "base_color_rgb", "encoding": "linear_unorm16"},
    "nir_albedo": {"directory": "base_color_nir", "encoding": "linear_unorm16"},
    "roughness_perceptual": {"directory": "roughness", "encoding": "perceptual_roughness_unorm16"},
    "metallic": {"directory": "metallic", "encoding": "unorm16"},
    "depth": {"directory": "depth", "encoding": "millimeters_u16", "invalid": 0},
    "range": {"directory": "range", "encoding": "millimeters_u16", "invalid": 0},
    "normal_geometry_world": {"directory": "normal_geometry_world", "encoding": "xyz_signed_to_unorm16"},
    "normal_shading_world": {"directory": "normal_shading_world", "encoding": "xyz_signed_to_unorm16"},
    "normal_tangent": {"directory": "normal_tangent", "encoding": "xyz_signed_to_unorm16"},
}
_MASK_PNG_SPECS = {
    "material_id": {"directory": "material_id", "encoding": "uint16_plus_one", "invalid": 0},
    "object_id": {"directory": "object_id", "encoding": "uint16_plus_one", "invalid": 0},
    "valid_mask": {"directory": "valid_mask", "encoding": "binary_mask_u8"},
    "replacement_mask": {"directory": "replacement_mask", "encoding": "binary_mask_u8"},
    "window_glass": {"directory": "masks/window_glass", "encoding": "binary_mask_u8"},
    "object_glass": {"directory": "masks/object_glass", "encoding": "binary_mask_u8"},
    "glass": {"directory": "masks/glass", "encoding": "binary_mask_u8"},
    "mirror": {"directory": "masks/mirror", "encoding": "binary_mask_u8"},
}


def _require_finite(name: str, values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, np.float32)
    if not np.isfinite(array).all():
        raise ValueError(f"{name}: cannot encode non-finite GT values as PNG")
    return array


def _quantize_unorm16(name: str, values: np.ndarray) -> np.ndarray:
    array = _require_finite(name, values)
    tolerance = 2.0 / _PNG16_MAX
    if float(array.min()) < -tolerance or float(array.max()) > 1.0 + tolerance:
        raise ValueError(f"{name}: values outside [0, 1] cannot use UNORM16 PNG")
    return np.rint(np.clip(array, 0.0, 1.0) * _PNG16_MAX).astype(np.uint16)


def _encode_png_artifact(name: str, values: np.ndarray, spec: dict) -> np.ndarray:
    encoding = str(spec["encoding"])
    if encoding in {"linear_unorm16", "perceptual_roughness_unorm16", "unorm16"}:
        return _quantize_unorm16(name, values)
    if encoding == "xyz_signed_to_unorm16":
        array = _require_finite(name, values)
        tolerance = 2.0 / _PNG16_MAX
        if float(array.min()) < -1.0 - tolerance or float(array.max()) > 1.0 + tolerance:
            raise ValueError(f"{name}: normal values outside [-1, 1]")
        return np.rint(np.clip(array * 0.5 + 0.5, 0.0, 1.0) * _PNG16_MAX).astype(np.uint16)
    if encoding == "millimeters_u16":
        array = _require_finite(name, values)
        if float(array.min()) < 0.0 or float(array.max()) > 65.535 + 0.0005:
            raise ValueError(f"{name}: metric range exceeds PNG millimeter uint16 capacity")
        return np.rint(array * 1000.0).astype(np.uint16)
    if encoding == "uint16_plus_one":
        array = _require_finite(name, values)
        rounded = np.rint(array)
        if not np.allclose(array, rounded, rtol=0.0, atol=1e-4):
            raise ValueError(f"{name}: ID map contains non-integer values")
        if float(rounded.max()) > 65534.0:
            raise ValueError(f"{name}: ID exceeds PNG uint16 capacity after invalid offset")
        return np.where(rounded >= 0.0, rounded + 1.0, 0.0).astype(np.uint16)
    if encoding == "binary_mask_u8":
        array = _require_finite(name, values)
        return np.where(array > 0.5, 255, 0).astype(np.uint8)
    raise ValueError(f"unsupported PNG GT encoding: {encoding}")


def _write_png(path: Path, values: np.ndarray, *, compression: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import cv2
    except ModuleNotFoundError:
        # The OptiX-7 Conda renderer environment deliberately stays small and
        # does not install OpenCV.  Mitsuba's Bitmap writer preserves uint8 and
        # uint16 PNG channel values exactly, unlike Pillow's RGB uint16 path.
        # It also uses RGB order directly (OpenCV needs the reversal below).
        import mitsuba as mi
        mi.Bitmap(np.ascontiguousarray(values)).write(str(path))
        return
    # OpenCV's encoder uses BGR channel order while every GT contract is RGB.
    encoded = values[..., ::-1] if values.ndim == 3 and values.shape[-1] == 3 else values
    if not cv2.imwrite(str(path), np.ascontiguousarray(encoded), [cv2.IMWRITE_PNG_COMPRESSION, int(compression)]):
        raise OSError(f"failed to write PNG: {path}")


def _write_gt_artifact(
    out: Path, frame_dir: Path, frame_id: str, name: str, values: np.ndarray, *,
    is_mask: bool, storage: str, png_compression: int,
) -> Path:
    if storage == "exr":
        path = frame_dir / f"{name}.exr"
        _write_exr(path, values)
        return path
    spec = (_MASK_PNG_SPECS if is_mask else _GT_PNG_SPECS)[name]
    path = out / str(spec["directory"]) / f"{frame_id}.png"
    _write_png(path, _encode_png_artifact(name, values, spec), compression=png_compression)
    return path


def _render_scene_audit(
    scene_xml: Path, effective_contract: dict, *, polarized: bool, observation_variant: str,
) -> dict:
    """Record whether this run will use spatial PBR textures, polar BSDFs and full meshes.

    This is intentionally XML-only: it runs before Mitsuba allocation and makes a
    queue plan inspectable without launching a GPU worker.
    """
    root = ET.parse(scene_xml).getroot()
    bsdfs = list(root.findall(".//bsdf"))
    textures = list(root.findall(".//texture"))
    texture_names: dict[str, int] = {}
    texture_types: dict[str, int] = {}
    for texture in textures:
        name = str(texture.get("name") or "unnamed")
        texture_names[name] = texture_names.get(name, 0) + 1
        kind = str(texture.get("type") or "unknown")
        texture_types[kind] = texture_types.get(kind, 0) + 1
    bsdf_types: dict[str, int] = {}
    for bsdf in bsdfs:
        kind = str(bsdf.get("type") or "unknown")
        bsdf_types[kind] = bsdf_types.get(kind, 0) + 1
    geometry = dict(effective_contract.get("geometry") or {})
    return {
        "schema": "robomituba.ir_render_input_audit.v1",
        "surface_domain": effective_contract["surface_domain"],
        "effective_scene_digest": effective_contract["effective_scene_digest"],
        "render_scene_ref": str(scene_xml.resolve()),
        "shape_count": len(root.findall("./shape")),
        "bsdf_types": dict(sorted(bsdf_types.items())),
        "texture_types": dict(sorted(texture_types.items())),
        "texture_parameters": dict(sorted(texture_names.items())),
        "normalmap_wrapper_count": bsdf_types.get("normalmap", 0),
        "measured_polarized_bsdf_count": bsdf_types.get("measured_polarized", 0),
        "polarized_render_requested": bool(polarized),
        "polar_artifacts": ["dop", "aolp"] if polarized else [],
        "renderer_runtime": os.environ.get("ROBOMITUBA_MITSUBA_RUNTIME", "unspecified"),
        "observation_mitsuba_variant": str(observation_variant),
        "geometry": geometry,
        "specular_semantics": effective_contract.get("specular_semantics"),
    }


def _write_gt_artifact_contract(out: Path, *, storage: str, band_nm: int) -> None:
    artifacts = {**_GT_PNG_SPECS, **_MASK_PNG_SPECS}
    payload = {
        "schema": "robomituba.ir_gt_artifact_contract.v3",
        "artifact_layout": _GT_ARTIFACT_LAYOUT if storage == "png16" else "per_frame_legacy_v1",
        "storage": storage,
        "artifacts": {
            name: {**spec, "path_template": f"{spec['directory']}/{{frame_id}}.png"}
            for name, spec in artifacts.items()
        },
        "aliases": {"base_color": "rgb_albedo"},
        "nir_band_nm": int(band_nm),
        "decode": {
            "linear_unorm16": "float32(u16) / 65535",
            "perceptual_roughness_unorm16": "float32(u16) / 65535",
            "xyz_signed_to_unorm16": "normalize(float32(u16) / 65535 * 2 - 1)",
            "millimeters_u16": "float32(u16) / 1000; 0 is invalid",
            "uint16_plus_one": "int32(u16) - 1; 0 is invalid",
            "binary_mask_u8": "u8 > 0",
        },
    }
    (out / "gt_artifact_contract.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
def _write_exr_threadsafe(path: Path, values: np.ndarray) -> None:
    # mi.Bitmap.write() touches Mitsuba's Thread/Logger internals, which
    # assume the calling thread is registered with Mitsuba. A raw
    # ThreadPoolExecutor thread is not, and calling it concurrently with the
    # main thread's CUDA render work aborts the process (SIGABRT). imageio
    # is already a dependency for EXR I/O elsewhere in this codebase and has
    # no such thread affinity.
    import imageio.v3 as iio
    array = np.ascontiguousarray(np.asarray(values, np.float32))
    if array.ndim == 2:
        array = array[..., None]
    iio.imwrite(str(path), array)


def _camera(node: dict, yaw_deg: float) -> np.ndarray:
    pose = resolve_viewpoint_pose(
        node["position"], float(yaw_deg), eye_height_m=EYE_HEIGHT_M,
        target_height_m=EYE_HEIGHT_M * 0.9,
    )
    return np.asarray(pose.camera_to_world_mitsuba, dtype=np.float32)


def _rig_light_to_world(
    camera_to_world: np.ndarray,
    *,
    offset_y_m: float,
    area_half_m: float | None,
) -> np.ndarray:
    """Place a forward-facing light at a camera-rig-local vertical offset."""
    transform = np.asarray(camera_to_world, dtype=np.float32).copy()
    transform[:3, 3] += transform[:3, :3] @ np.asarray([0.0, offset_y_m, 0.0], np.float32)
    if area_half_m is not None:
        transform[:3, :3] *= float(area_half_m)
    return transform


def _render_rig_transforms(
    camera_to_world: np.ndarray,
    *,
    offset_y_m: float,
    area_half_m: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build aligned Mitsuba sensor/light transforms from the stored camera pose."""
    origin, target, up = camera_to_world_to_lookat(camera_to_world)
    forward = np.asarray(target, np.float32) - np.asarray(origin, np.float32)
    forward /= max(float(np.linalg.norm(forward)), 1e-8)
    right = np.cross(np.asarray(up, np.float32), forward)
    right /= max(float(np.linalg.norm(right)), 1e-8)
    corrected_up = np.cross(forward, right)
    corrected_up /= max(float(np.linalg.norm(corrected_up)), 1e-8)

    sensor_to_world = np.eye(4, dtype=np.float32)
    sensor_to_world[:3, 0] = right
    sensor_to_world[:3, 1] = corrected_up
    sensor_to_world[:3, 2] = forward
    sensor_to_world[:3, 3] = np.asarray(origin, np.float32)
    light_to_world = _rig_light_to_world(
        sensor_to_world,
        offset_y_m=offset_y_m,
        area_half_m=area_half_m,
    )
    return sensor_to_world, light_to_world


def _resize_sensor(xml_path: Path, width: int, height: int) -> None:
    tree = ET.parse(xml_path)
    for node in tree.getroot().findall(".//sensor/film/integer"):
        if node.get("name") == "width":
            node.set("value", str(int(width)))
        elif node.get("name") == "height":
            node.set("value", str(int(height)))
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _stokes(image: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if image.shape[-1] < 12:
        raise ValueError(f"polarized Stokes render has only {image.shape[-1]} channels")
    s0_rgb = image[..., 3:6].astype(np.float32)
    s0 = np.maximum((s0_rgb * LUMINANCE).sum(2), 1e-8)
    s1 = (image[..., 6:9] * LUMINANCE).sum(2)
    s2 = (image[..., 9:12] * LUMINANCE).sum(2)
    dop = np.clip(np.sqrt(s1 * s1 + s2 * s2) / s0, 0.0, 1.0)
    aolp = 0.5 * np.arctan2(s2, s1)
    return s0_rgb, dop.astype(np.float32), np.nan_to_num(aolp).astype(np.float32)


def _free_gpu() -> None:
    """Synchronize pending JIT work, then release transient allocations.

    Mitsuba/Dr.Jit launches CUDA work asynchronously.  The daemon worker
    performs this boundary after every render; the IR batch renderer used to
    do it only when switching scenes.  That allowed an illegal-address from a
    previous ``mi.render`` to surface during the next ``params.update`` or
    render, making a whole multi-frame batch look guilty.  Keep the scene
    resident for batching, but make the allocator/synchronization boundary
    explicit at frame boundaries.
    """
    gc.collect()
    try:
        import drjit as dr
    except ImportError:
        return
    sync = getattr(dr, "sync_thread", None)
    if callable(sync):
        # Do not swallow a CUDA error here.  It identifies the frame boundary
        # that poisoned the context and lets the queue restart the worker.
        sync()
    try:
        dr.flush_malloc_cache()
    except Exception:
        pass


class _AsyncWriter:
    """Bounded CPU writer so EXR I/O overlaps the next GPU render."""

    def __init__(self, enabled: bool, workers: int = 2, max_pending: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=workers) if enabled else None
        self._pending = []
        self._max_pending = max(1, int(max_pending))

    def write(self, path: Path, values: np.ndarray) -> None:
        # Own a contiguous host copy before returning to the render loop.  The
        # Dr.Jit/NumPy view is then free to be reclaimed without racing the
        # writer thread.
        array = np.ascontiguousarray(np.asarray(values, np.float32).copy())
        if self._executor is None:
            _write_exr(path, array)
            return
        self._pending.append(self._executor.submit(_write_exr_threadsafe, path, array))
        if len(self._pending) >= self._max_pending:
            self._pending.pop(0).result()

    def flush(self) -> None:
        for future in self._pending:
            future.result()
        self._pending.clear()

    def close(self) -> None:
        self.flush()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None


def _sync_gpu() -> None:
    """Wait for asynchronous GPU work before consuming/reusing scene state."""
    try:
        import drjit as dr
    except ImportError:
        return
    sync = getattr(dr, "sync_thread", None)
    if callable(sync):
        sync()


def _camera_metadata(camera_to_world: np.ndarray, fov_deg: float, width: int, height: int) -> dict:
    """Return explicit intrinsics and the OpenGL, Mitsuba, and COLMAP extrinsics."""
    sensor_to_world, _ = _render_rig_transforms(
        camera_to_world, offset_y_m=0.0, area_half_m=None,
    )
    fx = 0.5 * float(width) / math.tan(0.5 * math.radians(float(fov_deg)))
    # Mitsuba: +X right, +Y up, +Z forward. COLMAP: +X right, +Y down, +Z forward.
    colmap_camera_to_world = sensor_to_world.copy()
    colmap_camera_to_world[:3, 1] *= -1.0
    colmap_world_to_camera = np.linalg.inv(colmap_camera_to_world)
    return {
        "intrinsics": {
            "model": "PINHOLE", "fov_deg": float(fov_deg),
            "width": int(width), "height": int(height),
            "fx": fx, "fy": fx, "cx": float(width) / 2.0, "cy": float(height) / 2.0,
        },
        "extrinsics": {
            "camera_to_world_opengl": np.asarray(camera_to_world, np.float64).tolist(),
            "sensor_to_world_mitsuba": np.asarray(sensor_to_world, np.float64).tolist(),
            "world_to_camera_colmap": np.asarray(colmap_world_to_camera, np.float64).tolist(),
        },
        "conventions": {
            "camera_to_world_opengl": "+X right, +Y up, -Z forward",
            "sensor_to_world_mitsuba": "+X right, +Y up, +Z forward",
            "world_to_camera_colmap": "+X right, +Y down, +Z forward",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument(
        "--surface-domain", choices=sorted(SUPPORTED_SURFACE_DOMAINS), default=STRUCTURAL_SPECULAR_PBR_DOMAIN,
        help="IR surface domain; structural_specular_pbr removes object glass, retains window glass/mirrors, and emits semantic masks",
    )
    parser.add_argument(
        "--effective-scene-dir", type=Path,
        help="reuse or publish the immutable effective scene here (defaults under --out)",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--viewpoints", default="vp_000005@180,vp_000009@180,vp_000010@180,vp_000012@180")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fov", type=float, default=60.0)
    parser.add_argument("--spp", type=int, default=256,
                        help="legacy common observation SPP; pass-specific values default to this")
    parser.add_argument("--rgb-spp", type=int,
                        help="RGB passive path SPP (defaults to --spp)")
    parser.add_argument("--nir-ambient-spp", type=int,
                        help="NIR passive path SPP (defaults to --spp)")
    parser.add_argument("--nir-direct-spp", type=int,
                        help="NIR flash direct SPP (defaults to --spp)")
    parser.add_argument("--max-depth", type=int, default=8,
                        help="path-integrator maximum depth for all observation passes")
    parser.add_argument("--subpixel", type=int, default=2)
    parser.add_argument("--band", type=int, default=854)
    parser.add_argument("--nir-cache-dir", type=Path,
                        help="shared synthesized NIR texture cache (defaults under --out)")
    parser.add_argument("--nir-radiance", type=float, default=400.0)
    parser.add_argument("--nir-half", type=float, default=0.015)
    parser.add_argument("--nir-flash-model", choices=("area", "spot"), default="spot")
    parser.add_argument("--nir-flash-offset-y", type=float, default=-0.10,
                        help="flash vertical offset in camera-rig coordinates (m)")
    parser.add_argument("--nir-flash-beam-width", type=float, default=22.0)
    parser.add_argument("--nir-flash-cutoff-angle", type=float, default=30.0)
    parser.add_argument("--polar", action="store_true")
    parser.add_argument(
        "--observation-variant", choices=OBSERVATION_VARIANT_CHOICES, default="auto",
        help="Mitsuba carrier variant; auto uses RGB for non-polar and RGB-polarized when compiled",
    )
    parser.add_argument(
        "--render-full-path-active",
        action="store_true",
        help="also render the legacy ambient+flash path pass for QC only",
    )
    parser.add_argument("--gt-only", action="store_true")
    parser.add_argument("--observations-only", action="store_true")
    parser.add_argument(
        "--gt-storage", choices=("png16", "exr"), default="png16",
        help="canonical GT/mask storage; png16 is modality-first and EXR is legacy compatibility",
    )
    parser.add_argument(
        "--gt-png-compression", type=int, default=6,
        help="PNG DEFLATE level for --gt-storage png16 (0-9)",
    )
    parser.add_argument(
        "--async-io", action="store_true",
        help="overlap bounded EXR observation writes with the next GPU render",
    )
    parser.add_argument(
        "--gpu-cleanup-interval", type=int, default=4,
        help="flush Dr.Jit allocator every N frames; scene boundaries always flush",
    )
    parser.add_argument(
        "--texture-max-resolution", type=int,
        default=int(os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "0") or 0),
        help="max bitmap edge for the derived IR render XML; 0 preserves source texture resolution",
    )
    parser.add_argument(
        "--texture-cache-dir", type=Path,
        default=(Path(os.environ["ROBOMITUBA_TEXTURE_CACHE_DIR"])
                 if os.environ.get("ROBOMITUBA_TEXTURE_CACHE_DIR") else None),
        help="shared cache for downsampled render textures (source GLB/PNG files remain unchanged)",
    )
    parser.add_argument(
        "--worker-stdio", action="store_true",
        help="serve rolling observation leases over JSON-lines stdin instead of rendering --viewpoints once",
    )
    parser.add_argument(
        "--worker-phase", choices=("passive", "flash_direct"),
        help="immutable scene phase for --worker-stdio",
    )
    parser.add_argument(
        "--rolling-staging-root", type=Path,
        help="run-global .rolling_frames directory owned by the rolling queue parent",
    )
    args = parser.parse_args()
    if args.gt_only and args.observations_only:
        parser.error("--gt-only and --observations-only are mutually exclusive")
    for name in ("rgb_spp", "nir_ambient_spp", "nir_direct_spp"):
        if getattr(args, name) is None:
            setattr(args, name, int(args.spp))
        if int(getattr(args, name)) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.max_depth == 0 or args.max_depth < -1:
        parser.error("--max-depth must be -1 (unlimited) or a positive integer")
    if args.gpu_cleanup_interval < 1:
        parser.error("--gpu-cleanup-interval must be positive")
    if args.texture_max_resolution < 0:
        parser.error("--texture-max-resolution must be non-negative")
    if not 0 <= args.gt_png_compression <= 9:
        parser.error("--gt-png-compression must be between 0 and 9")
    if args.texture_cache_dir is not None:
        args.texture_cache_dir = args.texture_cache_dir.expanduser().resolve()
    if args.worker_stdio:
        if args.worker_phase is None or args.rolling_staging_root is None:
            parser.error("--worker-stdio requires --worker-phase and --rolling-staging-root")
        if args.gt_only:
            parser.error("--worker-stdio cannot be combined with --gt-only")
        # A rolling worker owns only GPU observation artifacts.  Property/Blender
        # GT remains a parent-orchestrated post-observation stage.
        args.observations_only = True
        from ir_rolling_worker import run_worker_stdio
        return run_worker_stdio(args, sys.modules[__name__])

    source_scene_dir = args.scene_dir.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    existing_contract_path = source_scene_dir / "ir_scene_domain.json"
    if existing_contract_path.is_file():
        effective_contract = validate_ir_effective_scene(source_scene_dir)
        if effective_contract.get("surface_domain") != args.surface_domain:
            parser.error(
                f"prepared effective scene domain={effective_contract.get('surface_domain')} does not match --surface-domain={args.surface_domain}"
            )
        scene_dir = source_scene_dir
    else:
        effective_dir = (args.effective_scene_dir or (args.out / "ir_effective_scene")).resolve()
        effective_contract = materialize_ir_effective_scene(
            source_scene_dir, effective_dir, surface_domain=args.surface_domain, reuse_existing=True,
        )
        scene_dir = effective_dir
    _write_gt_artifact_contract(args.out, storage=args.gt_storage, band_nm=args.band)
    render_input_audit = _render_scene_audit(
        scene_dir / "render_scene.xml", effective_contract, polarized=args.polar,
        observation_variant=args.observation_variant,
    )
    render_input_audit["texture_policy"] = {
        "max_resolution": int(args.texture_max_resolution),
        "cache_dir": str(args.texture_cache_dir) if args.texture_cache_dir is not None else None,
        "source_atlas_immutable": True,
    }
    render_input_audit["observation_sampling"] = {
        "rgb_spp": int(args.rgb_spp),
        "nir_ambient_spp": int(args.nir_ambient_spp),
        "nir_direct_spp": int(args.nir_direct_spp),
        "max_depth": int(args.max_depth),
    }
    canonical = json.loads((scene_dir / "material_canonical.json").read_text())
    graph = json.loads((scene_dir / "viewpoint_graph.json").read_text())
    # Keep the effective XML immutable.  The batch-local copy is rewritten to
    # host-local cached textures *before* NIR synthesis, preventing every
    # worker from constructing full-resolution NIR atlases only to downsample
    # them later.
    render_scene_xml = scene_dir / "render_scene.xml"
    if args.texture_max_resolution > 0:
        capped_source_xml = args.out / f"scene_texture_max{args.texture_max_resolution}.xml"
        shutil.copy2(render_scene_xml, capped_source_xml)
        source_cap = cap_scene_texture_resolution(
            capped_source_xml,
            max_resolution=args.texture_max_resolution,
            cache_dir=args.texture_cache_dir,
            fail_on_unbounded=True,
        )
        render_scene_xml = capped_source_xml
        # Keep only batch-independent evidence in the run input audit: the
        # temporary XML and cache paths necessarily differ per chunk/GPU.
        render_input_audit["texture_policy"]["source_cap"] = {
            key: source_cap.get(key)
            for key in (
                "texture_profile", "texture_refs", "downsampled_refs", "original_refs",
                "original_gt_profile_refs", "missing_refs", "audit_ok", "rewritten", "skipped",
            )
        }
    nodes = {row["node_id"]: row for row in graph["nodes"]}
    views: list[tuple[str, float, np.ndarray]] = []
    for spec in args.viewpoints.split(","):
        node_id, sep, yaw_text = spec.strip().partition("@")
        yaw = float(yaw_text) if sep else 0.0
        if node_id not in nodes:
            parser.error(f"viewpoint not found: {node_id}")
        views.append((node_id, yaw, _camera(nodes[node_id], yaw)))

    labels: list[dict] = []
    for node_id, yaw, camera in views:
        frame_id = f"{node_id}__h_{int(round(yaw)) % 360:03d}"
        frame_dir = args.out / frame_id
        camera_meta = _camera_metadata(camera, args.fov, args.width, args.height)
        label = {
            "schema": "robomituba.ir_frame.v3", "frame_id": frame_id,
            "surface_domain": str(effective_contract["surface_domain"]),
            "ir_scene_domain_ref": str((scene_dir / "ir_scene_domain.json").resolve()),
            "effective_scene_digest": str(effective_contract["effective_scene_digest"]),
            "viewpoint_id": node_id, "heading_deg": yaw,
            "camera_to_world": np.asarray(camera).tolist(),
            "intrinsics": camera_meta["intrinsics"],
            "extrinsics": camera_meta["extrinsics"],
            "camera_conventions": camera_meta["conventions"],
            "render_config": {
                "observation_spp": int(args.spp),
                "observation_spp_by_pass": {
                    "rgb": int(args.rgb_spp),
                    "nir_ambient": int(args.nir_ambient_spp),
                    "nir_flash_direct": int(args.nir_direct_spp),
                },
                "max_depth": int(args.max_depth),
                "gt_subpixel": int(args.subpixel),
                "polarized": bool(args.polar),
                "mitsuba_runtime": os.environ.get("ROBOMITUBA_MITSUBA_RUNTIME", "unspecified"),
                "observation_mitsuba_variant": str(args.observation_variant),
                "observation_variant_requested": str(args.observation_variant),
                "observation_protocol": "ambient_path_plus_flash_direct",
                "full_path_active_qc": bool(args.render_full_path_active),
                "depth_convention": "camera_z",
                "range_convention": "euclidean_camera_ray",
                "gt_storage": args.gt_storage,
                "gt_artifact_layout": _GT_ARTIFACT_LAYOUT if args.gt_storage == "png16" else "per_frame_legacy_v1",
                "gt_artifact_contract_ref": "gt_artifact_contract.json",
                "effective_scene_digest": str(effective_contract["effective_scene_digest"]),
                "specular_mask_policy": (effective_contract.get("specular_semantics") or {}).get("mask_semantics"),
                "nir_emitter": {
                    "product_model": "Advanced Illumination SL223-850IC",
                    "nominal_wavelength_nm": 850,
                    "material_carrier_band_nm": int(args.band),
                    "model": args.nir_flash_model,
                    "offset_y_m": float(args.nir_flash_offset_y),
                    "aperture_diameter_m": 0.0079,
                    "beam_width_deg": float(args.nir_flash_beam_width),
                    "cutoff_angle_deg": float(args.nir_flash_cutoff_angle),
                },
            },
            "observation_paths": {}, "gt_paths": {}, "mask_paths": {},
            "material_canonical_ref": str((scene_dir / "material_canonical.json").resolve()),
            "opaque_substitutions_ref": (
                str((scene_dir / "opaque_substitutions_applied.json").resolve())
                if (scene_dir / "opaque_substitutions_applied.json").is_file() else None
            ),
        }
        existing_path = frame_dir / "frame.json"
        if existing_path.is_file():
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            if args.gt_only:
                label["observation_paths"] = dict(existing.get("observation_paths") or {})
            if args.observations_only:
                for key in ("gt_paths", "mask_paths", "id_legends_ref", "coverage"):
                    if key in existing:
                        label[key] = existing[key]
        labels.append(label)

    # gt-only runs do not create a band carrier, but their input geometry and
    # PBR texture provenance must still be visible to validators and reviewers.
    if not (args.out / "render_input_audit.json").is_file():
        (args.out / "render_input_audit.json").write_text(
            json.dumps(render_input_audit, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    writer = _AsyncWriter(args.async_io)
    if not args.gt_only:
        import mitsuba as mi
        variant = _resolve_observation_variant(
            list(mi.variants()), polarized=args.polar, requested=args.observation_variant,
        )
        mi.set_variant(variant)
        render_input_audit["observation_mitsuba_variant"] = variant
        render_input_audit["observation_variant_requested"] = str(args.observation_variant)
        for label in labels:
            label["render_config"]["observation_mitsuba_variant"] = variant
        flash_value = (
            args.nir_radiance / (4.0 * args.nir_half**2)
            if args.nir_flash_model == "area" else args.nir_radiance
        )
        passive_xml = args.out / "scene_band_passive.xml"
        flash_direct_xml = args.out / "scene_band_flash_direct.xml"
        scene_specs = [
            (passive_xml, False, False, "path"),
            (flash_direct_xml, True, True, "direct"),
        ]
        if args.render_full_path_active:
            scene_specs.append((args.out / "scene_band_active_path_qc.xml", True, False, "path"))
        band_builds = []
        for xml_path, has_flash, flash_only, integrator in scene_specs:
            band_builds.append(build_band_scene(
                render_scene_xml, canonical, xml_path,
                metadata_scene=scene_dir,
                band=args.band, nir_dir=(args.nir_cache_dir or args.out / f"nir_band_{args.band}"),
                nir_flash=has_flash, nir_flash_half_m=args.nir_half,
                nir_flash_initial_radiance=flash_value,
                nir_flash_model=args.nir_flash_model,
                nir_flash_beam_width_deg=args.nir_flash_beam_width,
                nir_flash_cutoff_angle_deg=args.nir_flash_cutoff_angle,
                # The effective domain may retain dielectric/conductor surfaces, but
                # optional measured pBRDF leaves are never IR render authority.
                # Preserve the canonical analytic fallback so stale calibration files
                # cannot make a runnable scene variant-dependent.
                max_depth=args.max_depth, integrator=integrator, force_analytic=True,
                polarized=args.polar, enforce_bsdf_contract=False,
                flash_only=flash_only,
            ))
            _resize_sensor(xml_path, args.width, args.height)
            texture_cap = cap_scene_texture_resolution(
                xml_path,
                max_resolution=args.texture_max_resolution,
                cache_dir=args.texture_cache_dir,
                # A cap of zero is a deliberately explicit compatibility
                # mode.  Any positive IR cap must leave no original oversized
                # bitmap references behind, otherwise fail before GPU load.
                fail_on_unbounded=args.texture_max_resolution > 0,
            )
            band_builds[-1]["texture_cap"] = texture_cap
        render_input_audit["band_scene_builds"] = band_builds
        (args.out / "render_input_audit.json").write_text(
            json.dumps(render_input_audit, ensure_ascii=False, indent=2), encoding="utf-8",
        )

        def load_scene(xml_path: Path):
            started = time.time()
            scene = mi.load_file(str(xml_path)); params = mi.traverse(scene)
            keys = {
                "camera": next(k for k in params.keys() if k.endswith(".to_world") and "nir_flash" not in k),
                "fov": next((k for k in params.keys() if k.endswith(".x_fov")), None),
                "weights": [k for k in params.keys() if WEIGHT_RE.match(k)],
                "flash_tw": next((k for k in params.keys() if "nir_flash" in k and k.endswith(".to_world")), None),
            }
            print(f"[obs] loaded {xml_path.name} {variant} in {time.time()-started:.1f}s")
            return scene, params, keys

        def render(
            scene, params, keys, camera: np.ndarray, *, band: float, spp: int,
        ) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, float]]:
            """Render one pass and expose the actual renderer time in every frame record.

            The three observation passes share a scene load, but they are
            still separate ``mi.render`` calls.  Keep parameter-update,
            rendering, and final synchronization separate so a slow IR run
            can distinguish transport cost from host or driver overhead.
            """
            total_start = time.perf_counter()
            sensor_to_world, light_to_world = _render_rig_transforms(
                camera,
                offset_y_m=args.nir_flash_offset_y,
                area_half_m=args.nir_half if args.nir_flash_model == "area" else None,
            )
            params[keys["camera"]] = mi.Transform4f(sensor_to_world)
            if keys["fov"]:
                params[keys["fov"]] = float(args.fov)
            for key in keys["weights"]:
                params[key] = mi.Float(band)
            if keys["flash_tw"]:
                params[keys["flash_tw"]] = mi.Transform4f(light_to_world)
            params.update()
            update_s = time.perf_counter() - total_start
            _sync_gpu()
            render_start = time.perf_counter()
            image = np.asarray(mi.render(scene, spp=int(spp), seed=7))
            render_s = time.perf_counter() - render_start
            # np.asarray normally synchronizes the returned tensor, but make
            # the contract explicit before the next params.update()/render.
            sync_start = time.perf_counter()
            _sync_gpu()
            timing = {
                "params_update_s": round(update_s, 6),
                "spp": int(spp),
                "mi_render_s": round(render_s, 6),
                "post_render_sync_s": round(time.perf_counter() - sync_start, 6),
                "total_s": round(time.perf_counter() - total_start, 6),
            }
            if args.polar:
                rgb, dop, aolp = _stokes(image)
                return rgb, {"dop": dop, "aolp": aolp}, timing
            return image[..., :3].astype(np.float32), {}, timing

        passive: dict[str, np.ndarray] = {}
        passive_timings: dict[str, dict[str, dict[str, float]]] = {}
        scene, params, keys = load_scene(passive_xml)
        for view_index, (label, (_, _, camera)) in enumerate(zip(labels, views), 1):
            frame_dir = args.out / label["frame_id"]
            rgb, _, rgb_timing = render(scene, params, keys, camera, band=0.0, spp=args.rgb_spp)
            frame_dir = _publish_frame_dir(args.out, label["frame_id"])
            writer.write(frame_dir / "rgb.exr", rgb)
            ambient_rgb, _, ambient_timing = render(
                scene, params, keys, camera, band=1.0, spp=args.nir_ambient_spp,
            )
            ambient = (ambient_rgb * LUMINANCE).sum(2).astype(np.float32)
            passive[label["frame_id"]] = ambient
            passive_timings[label["frame_id"]] = {
                "rgb": rgb_timing,
                "nir_ambient": ambient_timing,
            }
            writer.write(frame_dir / "nir_ambient.exr", ambient)
            rgb_max = float(rgb.max())
            ambient_max = float(ambient.max())
            print(
                f"[obs-passive] {view_index}/{len(labels)} {label['frame_id']} "
                f"rgb_max={rgb_max:.5g} ambient_max={ambient_max:.5g} "
                f"rgb_render_s={rgb_timing['mi_render_s']:.2f} "
                f"nir_ambient_render_s={ambient_timing['mi_render_s']:.2f}",
                flush=True,
            )
            del rgb, ambient_rgb
            if view_index % args.gpu_cleanup_interval == 0:
                _free_gpu()
        del scene, params, keys
        _free_gpu()

        scene, params, keys = load_scene(flash_direct_xml)
        for view_index, (label, (_, _, camera)) in enumerate(zip(labels, views), 1):
            frame_dir = args.out / label["frame_id"]
            flash_rgb, polar, flash_timing = render(
                scene, params, keys, camera, band=1.0, spp=args.nir_direct_spp,
            )
            flash = (flash_rgb * LUMINANCE).sum(2).astype(np.float32)
            ambient = passive[label["frame_id"]]
            active = ambient + flash
            frame_dir = _publish_frame_dir(args.out, label["frame_id"])
            paths = {
                "rgb": frame_dir / "rgb.exr", "nir_ambient": frame_dir / "nir_ambient.exr",
                "nir_flash_direct": frame_dir / "nir_flash_direct.exr",
                "nir_active": frame_dir / "nir_active.exr", "nir_dflash": frame_dir / "nir_dflash.exr",
            }
            writer.write(paths["nir_flash_direct"], flash)
            writer.write(paths["nir_active"], active)
            writer.write(paths["nir_dflash"], flash)
            for name, values in polar.items():
                path = frame_dir / f"{name}.exr"; writer.write(path, values); paths[name] = path
            label["observation_paths"] = {key: str(path.resolve()) for key, path in paths.items()}
            label["render_timings_s"] = {
                **passive_timings[label["frame_id"]],
                "nir_flash_direct": flash_timing,
                "observation_render_total_s": round(
                    sum(
                        timing["total_s"]
                        for timing in (*passive_timings[label["frame_id"]].values(), flash_timing)
                    ),
                    6,
                ),
            }
            ambient_max = float(ambient.max())
            flash_max = float(flash.max())
            active_max = float(active.max())
            print(
                f"[obs] {label['frame_id']} ambient_max={ambient_max:.5g} "
                f"flash_direct_max={flash_max:.5g} active_max={active_max:.5g} "
                f"nir_direct_render_s={flash_timing['mi_render_s']:.2f}"
            )
            del flash_rgb, flash, active
            if view_index % args.gpu_cleanup_interval == 0:
                _free_gpu()
        del scene, params
        _free_gpu()

        if args.render_full_path_active:
            scene, params, keys = load_scene(args.out / "scene_band_active_path_qc.xml")
            for label, (_, _, camera) in zip(labels, views):
                frame_dir = args.out / label["frame_id"]
                qc_rgb, _, _ = render(
                    scene, params, keys, camera, band=1.0, spp=args.nir_direct_spp,
                )
                qc = (qc_rgb * LUMINANCE).sum(2).astype(np.float32)
                frame_dir = _publish_frame_dir(args.out, label["frame_id"])
                qc_path = frame_dir / "nir_active_path_qc.exr"
                _write_exr(qc_path, qc)
                label["observation_paths"]["nir_active_path_qc"] = str(qc_path.resolve())
            del scene, params, keys
            _free_gpu()

        # Ensure every observation file is durable before the subprocess exits
        # and the queue merges this bounded batch.
        writer.flush()

    if not args.observations_only:
        for label, (_, _, camera) in zip(labels, views):
            frame_dir = args.out / label["frame_id"]
            print(f"[gt] {label['frame_id']}", flush=True)
            maps = render_property_maps(
                render_scene_xml, camera, args.fov, canonical,
                # OptiX-7 host builds expose cuda_ad_rgb (not cuda_rgb).
                # Primary-ray property evaluation is non-differentiating, but
                # it must use a compiled carrier variant on both hosts.
                width=args.width, height=args.height, subpixel=args.subpixel, variant="cuda_ad_rgb",
                nir_band=args.band,
                nir_dir=(args.nir_cache_dir or args.out / f"nir_band_{args.band}"),
                scratch_dir=args.out / ".property_readout",
                metadata_scene=scene_dir,
            )
            frame_dir = _publish_frame_dir(args.out, label["frame_id"])
            gt = {
                "rgb_albedo": maps["base_color"], "nir_albedo": maps["nir_albedo"],
                "roughness_perceptual": maps["roughness"], "metallic": maps["metallic"],
                "depth": maps["depth"], "range": maps["range"],
                "normal_geometry_world": maps["geo_normal"],
                "normal_shading_world": maps["sh_normal"], "normal_tangent": maps["tangent_normal"],
            }
            masks = {
                "material_id": maps["material_region_id"].astype(np.float32),
                "object_id": maps["object_id"].astype(np.float32),
                # A primary-ray hit is geometrically valid even when a future
                # importer cannot yet assign it a stable object/material ID.
                # Do not turn a valid depth/normal pixel into background merely
                # because the ID legend is incomplete.
                "valid_mask": maps["valid"].astype(np.float32),
                "replacement_mask": maps["replacement_mask"].astype(np.float32),
                "window_glass": maps["window_glass_mask"].astype(np.float32),
                "object_glass": maps["object_glass_mask"].astype(np.float32),
                "glass": maps["glass_mask"].astype(np.float32),
                "mirror": maps["mirror_mask"].astype(np.float32),
            }
            gt_paths = {}; mask_paths = {}
            for name, values in gt.items():
                path = _write_gt_artifact(
                    args.out, frame_dir, label["frame_id"], name, values,
                    is_mask=False, storage=args.gt_storage, png_compression=args.gt_png_compression,
                )
                gt_paths[name] = str(path.resolve())
            # Keep the v1 base_color key as a path alias without duplicating a raster.
            gt_paths["base_color"] = gt_paths["rgb_albedo"]
            for name, values in masks.items():
                path = _write_gt_artifact(
                    args.out, frame_dir, label["frame_id"], name, values,
                    is_mask=True, storage=args.gt_storage, png_compression=args.gt_png_compression,
                )
                mask_paths[name] = str(path.resolve())
            legends_dir = args.out / "id_legends" if args.gt_storage == "png16" else frame_dir
            legends_dir.mkdir(parents=True, exist_ok=True)
            legends = legends_dir / (f"{label['frame_id']}.json" if args.gt_storage == "png16" else "id_legends.json")
            legends.write_text(json.dumps({"material": maps["region_legend"], "object": maps["object_legend"]}, indent=2))
            label["gt_paths"] = gt_paths; label["mask_paths"] = mask_paths
            label["id_legends_ref"] = str(legends.resolve())
            label["coverage"] = {
                "valid": float(masks["valid_mask"].mean()),
                "replacement": float(masks["replacement_mask"].mean()),
                "window_glass": float(masks["window_glass"].mean()),
                "object_glass": float(masks["object_glass"].mean()),
                "glass": float(masks["glass"].mean()),
                "mirror": float(masks["mirror"].mean()),
            }
            # GT extraction allocates large temporary Dr.Jit ray/intersection
            # buffers.  Drop the returned numpy maps and flush between views;
            # the next view reuses the staged scene cache but not its scratch
            # allocations.
            del maps, gt, masks, gt_paths, mask_paths
            _free_gpu()

    writer.close()

    index_path = args.out / "index.jsonl"
    with index_path.open("w", encoding="utf-8") as handle:
        for label in labels:
            frame_dir = _publish_frame_dir(args.out, label["frame_id"])
            label_path = frame_dir / "frame.json"
            label_path.write_text(json.dumps(label, ensure_ascii=False, indent=2), encoding="utf-8")
            handle.write(json.dumps(label, ensure_ascii=False) + "\n")
    print(f"done frames={len(labels)} index={index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
