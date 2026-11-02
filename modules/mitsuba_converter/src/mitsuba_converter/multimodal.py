from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
import re
import sys
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, Sequence
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from robomituba_bridge import ActiveLightSpec, AssistLightSpec, BsdfOverride, DepthApproxSpec, SceneOverrideSpec, OusterLidarMetadata, load_ouster_metadata


SUPPORTED_MODALITIES = (
    "rgb",
    "depth",
    "sensor_depth_approx",
    "depth_sensor",
    "depth_transient",
    "albedo",
    "direct_light_map",
    "indirect_light_map",
    "diffuse_map",
    "specular_map",
    "active_nir_intensity",
    "nir_intensity",
    "lidar_point_cloud",
    "lidar_range",
    "lidar_signal",
    "lidar_reflectivity",
    "lidar_near_ir",
    "lidar_valid",
    "lidar_xyz",
    "hazard_mask",
    "polar_rgb_preview",
    "dop",
    "aolp",
    "s1",
    "s2",
    "s1_over_s0",
    "s2_over_s0",
)


MODALITY_DEFINITIONS = {
    "rgb": "Path-traced RGB radiance image.",
    "depth": "AOV depth distance from the pinhole.",
    "sensor_depth_approx": "Approximate active-sensor depth with reflective planar proxy corruption.",
    "depth_sensor": "Sensorized depth derived from geometric depth with explicit quantization/noise/dropout.",
    "depth_transient": "Transient ToF depth histogram and estimate (requires mitransient adapter).",
    "albedo": "AOV diffuse reflectance approximation reported by Mitsuba.",
    "direct_light_map": "Path tracer with max_depth=2.",
    "indirect_light_map": "max(path_total - direct_light_map, 0).",
    "diffuse_map": "Path tracer with non-glass BSDFs converted to diffuse using original base colors.",
    "specular_map": "max(path_total - diffuse_map, 0).",
    "active_nir_intensity": "Camera-aligned active illumination grayscale proxy rendered under an assist light.",
    "nir_intensity": "Active NIR intensity image with explicit wavelength/filter/emitter metadata.",
    "lidar_point_cloud": "Ouster-compatible 3D spinning LiDAR range image and point cloud.",
    "lidar_range": "Ouster lidar range image in metres and millimetre-quantized integer form.",
    "lidar_signal": "Ouster lidar signal-photon proxy field.",
    "lidar_reflectivity": "Ouster calibrated reflectivity proxy field.",
    "lidar_near_ir": "Ouster near-infrared return proxy field.",
    "lidar_valid": "Ouster valid/padded/invalid return mask.",
    "lidar_xyz": "Ouster Cartesian point cloud in sensor coordinates.",
    "hazard_mask": "Binary camera-space mask for annotated transparent/reflective optical hazard targets.",
    "polar_rgb_preview": "RGB preview image derived from the polarized Stokes render.",
    "dop": "Degree of polarization derived from luminance-weighted Stokes S0/S1/S2.",
    "aolp": "Angle of linear polarization in degrees derived from luminance-weighted Stokes S1/S2.",
    "s1": "Luminance-weighted Stokes S1 signed field.",
    "s2": "Luminance-weighted Stokes S2 signed field.",
    "s1_over_s0": "Normalized Stokes S1/S0 (luminance-weighted), range [-1, 1], fixed colorbar scale.",
    "s2_over_s0": "Normalized Stokes S2/S0 (luminance-weighted), range [-1, 1], fixed colorbar scale.",
    "polarization": "Ideal Stokes polarization; physical transport uses a path nested integrator by default.",
}

_PARSED_SCENE_CACHE: dict[tuple[str, int, int], ET.Element] = {}
_SCENE_TEMPLATE_CACHE: dict[tuple[tuple[str, int, int], str, tuple[Any, ...]], ET.Element] = {}
_RESIDENT_SCENE_CACHE: "OrderedDict[tuple[str, int, int, str], Any]" = OrderedDict()
# Resolved ``slot_N.to_world`` parameter *names* for the scene cached above.
# Only the names are cached: a ParameterMap captured here would go stale the
# moment dr.freeze replays the scene (it swaps the underlying JIT variables),
# and writing through the stale map crashed the worker with
# CUDA_ERROR_ILLEGAL_ADDRESS. Names are pose-independent, so re-traversing per
# strip is both cheap and safe.
_RESIDENT_BATCH_BINDINGS: dict[tuple[str, int, int, str], tuple[str, ...]] = {}
# One ``dr.freeze``-wrapped render callable per resident scene cache entry,
# keyed a second level by spp (freeze bakes spp into the traced closure).
# See ``_drjit_freeze_enabled`` for why this stays opt-in.
_RESIDENT_FROZEN_RENDER_CACHE: dict[tuple[str, int, int, str], dict[int, Any]] = {}
_STAGED_SCENE_SIGNATURE_CACHE: dict[str, tuple[Any, ...]] = {}
_SCENE_CACHE_LOCK = threading.Lock()
_RESIDENT_SCENE_CACHE_LIMIT: int = int(os.environ.get("ROBOMITUBA_SCENE_CACHE_LIMIT", "32"))
_POLAR_RESIDENT_SCENE_CACHE_LIMIT: int = int(
    os.environ.get("ROBOMITUBA_POLAR_RESIDENT_SCENE_CACHE_LIMIT", "1")
)
# Every resident Stokes heading batch is staged at this one slot count so the
# whole sweep shares a single resident scene -- and therefore a single
# dr.freeze recording -- instead of thrashing between per-K scene shapes.
#
# The count also sets the batch film width (slots * width), and the render
# wavefront scales with it: K=4 at 512x384x1024spp exhausted a 32 GB card
# (CUDA_ERROR_OUT_OF_MEMORY, killing the worker and cascading every job it
# held). Keep this at the largest value that leaves GPU headroom for the
# resident scene on the target device.
_RESIDENT_STOKES_HEADING_BATCH_SLOTS: int = int(
    os.environ.get("ROBOMITUBA_RESIDENT_STOKES_BATCH_SLOTS", "4")
)
_RENDER_DRJIT_FREEZE_ENV = "ROBOMITUBA_RENDER_DRJIT_FREEZE"
# Last stage ("record"/"replay") printed per resident scene, so the worker
# console shows one line per transition instead of one per frame.
_FROZEN_RENDER_LOG_STATE: dict[tuple[str, int, int, str], str] = {}
_last_source_scene_dir: str = ""


def _drjit_freeze_enabled() -> bool:
    """Opt-in Dr.Jit function freezing for resident-scene renders.

    Freezing replays a recorded CUDA kernel graph instead of re-tracing on
    every call, which only pays off when the scene/sensor structure stays
    fixed across calls -- the resident heading-batch and camera-aligned polar
    hot paths that keep one scene object resident and mutate it only through
    ``mi.traverse()``. Only Device 1's OptiX 8 build exposes ``dr.freeze``
    reliably; Device 2's OptiX 7 build segfaults when it is exercised. Detect
    that from the outside instead of hardcoding it: launchers set this
    per-device (``run_render_queue_local.sh`` on, ``run_render_queue_optix7.sh``
    off).
    """
    return os.environ.get(_RENDER_DRJIT_FREEZE_ENV, "0").strip().lower() in {"1", "true", "yes", "on"}


def _resident_stokes_heading_batches_enabled() -> bool:
    """Whether passive K=2..4 Stokes strips retain one scene per worker.

    A resident batch scene has fixed sensor slots and only updates their
    transforms between strips.  It avoids the otherwise dominant repeated
    ``mi.load_file`` cost while preserving the max512 memory envelope.
    """
    return str(os.environ.get("ROBOMITUBA_RESIDENT_STOKES_HEADING_BATCH", "1")).strip().lower() not in {
        "0", "false", "no", "off",
    }

# ``stokes_data.npz`` is a learning/delivery artifact, not a rendering
# interchange file.  Keep its contract deliberately small: the four RGB
# Stokes vectors are the complete physical signal, while RGB previews and all
# scalar polar products are deterministic derivations.  The individual arrays
# are also the least-surprising representation for polanalyser users (who can
# stack them with ``np.stack([s0, s1, s2, s3], axis=-1)``).
MINIMAL_STOKES_SCHEMA = "minimal_rgb_stokes_f16_v2"
MINIMAL_STOKES_KEYS = ("s0", "s1", "s2", "s3")


def load_stokes_rgb_channels(stokes_npz: str | Path) -> dict[str, np.ndarray]:
    """Load either legacy or minimal Stokes NPZ data as float32 arrays.

    The returned mapping always contains ``rgb``, ``s0`` ... ``s3``. Minimal
    v2 products intentionally omit a redundant raw RGB raster; S0 is the
    radiometric RGB representation used for regeneration in that case.  A
    historical S0/S1-only diagnostic NPZ is normalized by zero-filling S2/S3
    so old gallery entries remain browseable without mutating their bundles.
    """
    source = Path(stokes_npz)
    with np.load(source, allow_pickle=False) as data:
        # A short-lived legacy gallery format wrote only S0/S1.  It is not a
        # complete learning artifact, but it is still safe to browse: retain
        # its measured S0/S1 and make the absent linear components explicitly
        # zero.  Missing S0 or S1 remains a corrupt Stokes artifact because
        # RGB previews, DoLP and AoLP then have no reliable baseline.
        if "s0" not in data.files or "s1" not in data.files:
            missing = [key for key in ("s0", "s1") if key not in data.files]
            raise ValueError(f"{source} lacks required Stokes arrays: {', '.join(missing)}")
        channels = {
            "s0": np.asarray(data["s0"], dtype=np.float32),
            "s1": np.asarray(data["s1"], dtype=np.float32),
        }
        for key in ("s2", "s3"):
            channels[key] = np.asarray(data[key], dtype=np.float32) if key in data.files else np.zeros_like(channels["s0"])
        rgb = np.asarray(data["rgb"], dtype=np.float32) if "rgb" in data.files else channels["s0"]
    shape = channels["s0"].shape
    if len(shape) != 3 or shape[-1] != 3 or any(value.shape != shape for value in channels.values()):
        raise ValueError(f"{source} has invalid RGB Stokes shapes")
    return {"rgb": rgb, **channels}


def stokes_rgb_tensor_for_polanalyser(stokes_npz: str | Path) -> np.ndarray:
    """Return the Polanalyser-friendly ``(H, W, RGB, S0..S3)`` tensor."""
    arrays = load_stokes_rgb_channels(stokes_npz)
    return np.stack([arrays[key] for key in MINIMAL_STOKES_KEYS], axis=-1)


def _save_minimal_stokes_npz(path: Path, *, s0: np.ndarray, s1: np.ndarray, s2: np.ndarray, s3: np.ndarray) -> tuple[float, int]:
    """Atomically publish the compact F16 Stokes payload.

    Conversion occurs after rendering has completed, so no CUDA work is held
    while Deflate writes to a potentially slow NFS mount. A temporary sibling
    also prevents a reader from ever observing a partial NPZ.
    """
    started = time.perf_counter()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            np.savez_compressed(
                handle,
                s0=np.asarray(s0, dtype=np.float16),
                s1=np.asarray(s1, dtype=np.float16),
                s2=np.asarray(s2, dtype=np.float16),
                s3=np.asarray(s3, dtype=np.float16),
            )
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return time.perf_counter() - started, path.stat().st_size

# RGB radiance tonemapping (extended Reinhard). Render-time uses these fixed
# defaults so every frame in a sweep shares the same exposure (consistent for
# ML); the export step recomputes a scene-global (exposure, white) from the EXR
# population and re-tonemaps. Both reuse `_tonemap_reinhard` below.
_TONE_EXPOSURE_DEFAULT: float = float(os.environ.get("ROBOMITUBA_TONE_EXPOSURE", "1.0"))
_TONE_WHITE_DEFAULT: float = float(os.environ.get("ROBOMITUBA_TONE_WHITE", "10.0"))

# Firefly clamp: cap isolated bright specks at (local 3x3 median × factor) for
# preview/filtered outputs. Raw EXR/NPZ stay unclamped except NaN/Inf repair.
# Disable with ROBOMITUBA_FIREFLY_CLAMP=0.
_FIREFLY_CLAMP_DEFAULT: bool = os.environ.get("ROBOMITUBA_FIREFLY_CLAMP", "1") not in ("", "0", "false", "False")
_FIREFLY_CLAMP_FACTOR: float = float(os.environ.get("ROBOMITUBA_FIREFLY_CLAMP_FACTOR", "10.0"))
_MIN_ROUGHPLASTIC_ALPHA: float = float(os.environ.get("ROBOMITUBA_MIN_ROUGHPLASTIC_ALPHA", "0.08"))
_MIN_ROUGHCONDUCTOR_ALPHA: float = float(os.environ.get("ROBOMITUBA_MIN_ROUGHCONDUCTOR_ALPHA", "0.10"))
_MIN_ROUGHDIELECTRIC_ALPHA: float = float(os.environ.get("ROBOMITUBA_MIN_ROUGHDIELECTRIC_ALPHA", "0.08"))


def _clamp_bsdf_alpha(value: Any, *, default: float, floor: float, ceiling: float = 0.9) -> float:
    try:
        alpha = float(value) if value is not None else float(default)
    except Exception:
        alpha = float(default)
    return max(float(floor), min(float(ceiling), alpha))


@dataclass
class RenderConfig:
    width: int = 768
    height: int = 576
    path_spp: int = 4096
    aov_spp: int = 16
    polar_spp: int = 256
    # Optional progressive Stokes sampling.  When enabled, the renderer makes
    # independent low-spp estimates and only spends the remaining budget on a
    # view whose *Stokes* noise has not converged.  ``polar_spp`` remains the
    # hard maximum, so old requests retain their fixed-SPP behaviour unless an
    # explicit minimum/maximum pair is supplied.
    polar_adaptive_spp_min: int | None = None
    polar_adaptive_spp_max: int | None = None
    polar_adaptive_noise_threshold: float = 0.035
    # ``raw_stokes_aolp_v1`` is the compact dataset policy: persist the
    # lossless RGB Stokes 12-channel NPZ plus the two useful human-readable
    # images (polar RGB and AoLP).  Signed/DoLP/component previews remain
    # reproducible from the NPZ on demand.
    # ``core_preview_v1`` retains the historical RGB thumbnail, and ``full_v1``
    # remains the backwards-compatible default for direct/library callers.
    polar_visualization_policy: str = "full_v1"
    # One RGB-polarized Stokes render returns S0/S1/S2/S3, each with RGB
    # components: the public OpticalNav v2 ground truth has 12 scalar channels.
    polar_color_mode: str = "rgb_stokes_12"
    # ``physical`` is the dataset-quality default: it traces reflected and
    # transmitted background transport through the nested path integrator.
    # ``physical_volpath`` is an opt-in control for scenes with a small
    # polarized emitter / polarizer topology. It is deliberately not the
    # default: the extra medium transport is useful for validating that setup,
    # but is materially more expensive for production sweeps.
    # ``preview`` retains the inexpensive direct-light diagnostic path.
    polar_transport: str = "physical"
    path_max_depth: int = 6
    direct_max_depth: int = 2
    rr_depth: int = 8
    samples_per_pass: int | None = None
    polar_scale_threshold: float = 1e-4
    polar_min_finite_ratio: float = field(default_factory=lambda: float(os.environ.get("ROBOMITUBA_POLAR_MIN_FINITE_RATIO", "0.99")))
    polar_max_invalid_pixels: int = field(default_factory=lambda: int(os.environ.get("ROBOMITUBA_POLAR_MAX_INVALID_PIXELS", "2000")))
    nir_wavelength_min_nm: float = 830.0
    nir_wavelength_max_nm: float = 870.0
    nir_active_emitter_radiance: float = 40.0
    lidar_horizontal_fov_deg: float = 360.0
    lidar_vertical_fov_min_deg: float = -25.0
    lidar_vertical_fov_max_deg: float = 15.0
    lidar_min_range_m: float = 0.2
    lidar_max_range_m: float = 80.0
    lidar_wavelength_nm: float = 865.0
    lidar_profile: str = "os1-128"
    lidar_return_mode: str = "single"
    lidar_metadata_ref: str | None = None
    lidar_noise_std_m: float = 0.0
    lidar_dropout_probability: float = 0.0
    lidar_signal_scale: float = 1.0
    lidar_destagger: bool = True
    depth_sensor_quantization_m: float = 0.001
    depth_sensor_noise_std_m: float = 0.0
    depth_sensor_dropout_probability: float = 0.0
    depth_sensor_seed: int = 0
    ambient_radiance: float = 1.0
    # RGB radiance tonemapping (extended Reinhard) — fixed per-frame exposure so a
    # sweep stays consistent; export recomputes a scene-global value from EXRs.
    tone_exposure: float = field(default_factory=lambda: _TONE_EXPOSURE_DEFAULT)
    tone_white: float = field(default_factory=lambda: _TONE_WHITE_DEFAULT)
    # OptiX AI denoiser on the linear-HDR rgb pass, guided by albedo + shading
    # normal AOVs. Removes path-tracing noise without raising spp. CUDA-only
    # (auto-skips on CPU variants). Default from ROBOMITUBA_OPTIX_DENOISE.
    use_optix_denoiser: bool = field(
        default_factory=lambda: os.environ.get("ROBOMITUBA_OPTIX_DENOISE", "") not in ("", "0", "false", "False")
    )
    # Firefly clamp on the linear-HDR rgb (local 3x3 median × factor). Applied to
    # preview/filtered outputs only; raw EXR/NPZ remain unclamped.
    use_firefly_clamp: bool = field(default_factory=lambda: _FIREFLY_CLAMP_DEFAULT)
    firefly_clamp_factor: float = field(default_factory=lambda: _FIREFLY_CLAMP_FACTOR)
    write_raw_npz: bool = True
    # Measured-pBRDF band mode: "single" (stable 1 band × albedo, default) |
    # "hybrid" (achromatic→1 band, colored materials→3 bands) | "rgb"
    # (3 bands). Empty = ROBOMITUBA_PBRDF_BAND_MODE env then "single".
    pbrdf_band_mode: str = "single"
    # Measured-pBRDF scope: "analytic_only" (0 measured, DEFAULT) |
    # "analytic_priority" (forced/target/anchor up to max) |
    # "budgeted_measured" (top candidates up to max) | "measured_full".
    # Default flipped to analytic_only (2026-06-29): analytic BSDFs
    # (pplastic/dielectric/conductor) cover RGB+NIR+polarization, avoid measured
    # pBRDF cost + low-light collapse + measured_polarized_rgb build dependency.
    # Measured stays opt-in via explicit measured_scope.
    measured_scope: str = "analytic_only"
    max_measured_bsdfs: int = 3
    # Perf render option (2026-07-29): when true, non-polar passes (rgb/nir) run on the
    # rgb_polarized Stokes carrier too, so ONE resident scene serves rgb+nir+polar via
    # band-flip instead of a separate rgb-variant scene instance. Avoids per-modality
    # reload IO + dual-resident VRAM. See report_2026-07-29_perf.html §1.
    unified_spectral: bool = False
    artifact_stems: dict[str, str] = field(default_factory=dict)
    scene_filenames: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.polar_transport = str(self.polar_transport or "physical").strip().lower()
        if self.polar_transport not in {"physical", "physical_volpath", "preview"}:
            raise ValueError(
                "polar_transport must be one of: physical, physical_volpath, preview"
            )
        self.polar_color_mode = str(self.polar_color_mode or "rgb_stokes_12").strip().lower()
        if self.polar_color_mode not in {"rgb_stokes_12", "legacy_auto"}:
            raise ValueError("polar_color_mode must be one of: rgb_stokes_12, legacy_auto")

    def artifact_stem(self, modality: str, default: str) -> str:
        return self.artifact_stems.get(modality, default)

    def scene_filename(self, pass_name: str, default: str) -> str:
        return self.scene_filenames.get(pass_name, default)


def _polar_quality_summary(summary: Mapping[str, Any], config: "RenderConfig | None") -> dict[str, Any]:
    try:
        s1_scale = float(summary.get("s1_scale_abs_p995", 0.0))
    except Exception:
        s1_scale = 0.0
    try:
        s2_scale = float(summary.get("s2_scale_abs_p995", 0.0))
    except Exception:
        s2_scale = 0.0
    try:
        threshold = float(getattr(config, "polar_scale_threshold", 1e-4) if config is not None else 1e-4)
    except Exception:
        threshold = 1e-4
    try:
        invalid_pixels = int(summary.get("invalid_pixel_count", 0))
    except Exception:
        invalid_pixels = 0
    try:
        finite_ratio = float(summary.get("finite_ratio", 1.0))
    except Exception:
        finite_ratio = 0.0
    try:
        min_finite_ratio = float(getattr(config, "polar_min_finite_ratio", 0.99) if config is not None else 0.99)
    except Exception:
        min_finite_ratio = 0.99
    try:
        max_invalid_pixels = int(getattr(config, "polar_max_invalid_pixels", 2000) if config is not None else 2000)
    except Exception:
        max_invalid_pixels = 2000
    weak_scales = max(s1_scale, s2_scale) < threshold
    invalid_polar = finite_ratio < min_finite_ratio or invalid_pixels > max_invalid_pixels
    return {
        "weak_scales": bool(weak_scales),
        "invalid_polar": bool(invalid_polar),
        "invalid_pixel_count": int(invalid_pixels),
        "finite_ratio": float(finite_ratio),
        "min_finite_ratio": float(min_finite_ratio),
        "max_invalid_pixels": int(max_invalid_pixels),
    }


def _polar_transport_integrator(config: "RenderConfig") -> tuple[str, int]:
    """Resolve the nested Stokes integrator from the public transport mode."""
    if config.polar_transport == "physical":
        return "path", int(config.path_max_depth)
    if config.polar_transport == "physical_volpath":
        return "volpath", int(config.path_max_depth)
    return "direct", int(config.direct_max_depth)


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


_MEASURED_BSDF_TYPES = {"measured", "measured_polarized"}
_CHANNEL_SPLIT_RGB_PLUGIN_TYPE = "measured_polarized_rgb"
_CHANNEL_SPLIT_FILENAME_RE = re.compile(r"/channels/(?P<material>[^/]+)/(?P<wl>\d+)\.pbrdf$")
_RGB_CHANNEL_SPLIT_WAVELENGTHS_NM: tuple[tuple[str, int], ...] = (
    ("r", 614),
    ("g", 542),
    ("b", 446),
)

# pBRDF band mode (see dev_report/report_2026-06-23_single_band_pbrdf_albedo.md):
#   "single" — every measured material stays single-band (542 placeholder) × RGB albedo_scale
#   "hybrid" — achromatic materials → single-band; colored metals → 3 bands
#   "rgb"    — every measured material loads 3 bands (614/542/446)
# Single-band still renders colour because measured_polarized applies albedo_scale.
_PBRDF_BAND_MODES = {"rgb", "single", "hybrid"}

# Measured materials whose reflectance is ~achromatic across the visible bands, so a
# single band × RGB albedo reproduces them with negligible error. Conservative:
# anything NOT here (colored metals like fake_gold/brass/copper, colored silicones
# /billiards) keeps 3 bands so its coloured specular is preserved.
_ACHROMATIC_MEASURED_MATERIALS = {
    "aluminum", "suj2", "steel", "chrome", "nickel", "iron",
    "white_billiard", "black_billiard", "black_glass", "spectralon",
    "silver_rough_plastic", "white_rough_plastic", "white_smooth_plastic",
    "black_rough_plastic", "gray_silicone",
}


def _measured_material_is_colored(material_id: str | None) -> bool:
    """True when a measured material needs 3 bands to preserve its colour."""
    return str(material_id or "").strip().lower() not in _ACHROMATIC_MEASURED_MATERIALS


def _resolve_pbrdf_band_mode(config: "RenderConfig | None") -> str:
    """Effective band mode: request (config) → env → 'single'; unknown values fall back to 'single'."""
    mode = getattr(config, "pbrdf_band_mode", None) if config is not None else None
    if not mode:
        mode = os.environ.get("ROBOMITUBA_PBRDF_BAND_MODE")
    mode = str(mode or "single").strip().lower()
    return mode if mode in _PBRDF_BAND_MODES else "single"


def _swap_measured_bsdf_wavelength(root: ET.Element, *, target_nm: int) -> int:
    """Rewrite filenames of channel-split measured BSDFs to a target wavelength.

    Only swaps when the existing filename matches the channel-split layout
    (``.../channels/{material}/{wavelength}.pbrdf``). Raw monolithic .hpbrdf
    references are left alone since they're not channel-keyed.
    """
    swapped = 0
    for bsdf in list(root.findall(".//bsdf")):
        if str(bsdf.get("type") or "") not in _MEASURED_BSDF_TYPES:
            continue
        for s in bsdf.findall("./string"):
            if s.get("name") != "filename":
                continue
            value = s.get("value") or ""
            m = _CHANNEL_SPLIT_FILENAME_RE.search(value)
            if not m:
                continue
            new_value = value[: m.start("wl")] + str(target_nm) + ".pbrdf"
            if new_value != value:
                s.set("value", new_value)
                swapped += 1
    return swapped


def _ensure_measured_bsdf_wavelength(root: ET.Element, *, target_nm: int = 542) -> int:
    """Make single-band measured BSDFs load in non-spectral RGB variants.

    ``measured_polarized`` can be used in RGB variants as long as the XML gives a
    concrete wavelength. The source scene often only carries a channel-split
    filename placeholder, so stable RGB staging rewrites it to the target band and
    records ``<float name="wavelength" value="...">`` while preserving
    ``albedo_scale`` children.
    """
    touched = 0
    for bsdf in list(root.findall(".//bsdf")):
        if str(bsdf.get("type") or "") not in _MEASURED_BSDF_TYPES:
            continue
        changed = False
        filename_node = None
        for child in bsdf.findall("./string"):
            if child.get("name") == "filename":
                filename_node = child
                break
        if filename_node is not None:
            value = filename_node.get("value") or ""
            new_value = _channel_split_filename_for(value, target_nm=target_nm)
            if new_value != value:
                filename_node.set("value", new_value)
                changed = True

        first_float_index: int | None = None
        insert_at = len(list(bsdf))
        for idx, child in enumerate(list(bsdf)):
            if child.tag == "float":
                first_float_index = idx if first_float_index is None else first_float_index
            if child.tag == "string" and child.get("name") == "filename":
                insert_at = idx + 1
        if first_float_index is not None:
            insert_at = max(insert_at, first_float_index)
        for child in list(bsdf.findall("./float")):
            if child.get("name") == "wavelength":
                bsdf.remove(child)
                changed = True
        bsdf.insert(
            min(insert_at, len(list(bsdf))),
            ET.Element("float", {"name": "wavelength", "value": str(int(target_nm))}),
        )
        touched += 1
    return touched


def _stage_measured_bsdfs_for_rgb(root: ET.Element, *, band_mode: str) -> dict[str, int]:
    converted = _convert_channel_split_measured_bsdfs_to_rgb_plugin(root, band_mode=band_mode)
    single = _ensure_measured_bsdf_wavelength(root, target_nm=542)
    return {"three_band_converted": int(converted), "single_band_wavelength": int(single)}


def _pbrdf_band_policy_inventory(scene: Path | ET.Element) -> dict[str, Any]:
    """Count staged measured-BSDF policy choices for render diagnostics."""
    try:
        root = _parse_scene(scene) if isinstance(scene, Path) else scene
    except Exception:
        return {
            "single_band_measured": 0,
            "three_band_measured": 0,
            "measured_without_wavelength": 0,
            "channel_split_candidates": 0,
            "analytic_or_diffuse_background": 0,
            "analytic_polar_rgb_count": 0,
            "analytic_rgb_only_count": 0,
            "analytic_bsdf_type_counts": {},
            "total_bsdfs": 0,
        }
    counts = {
        "single_band_measured": 0,
        "three_band_measured": 0,
        "measured_without_wavelength": 0,
        "channel_split_candidates": 0,
        "analytic_or_diffuse_background": 0,
        "analytic_polar_rgb_count": 0,
        "analytic_rgb_only_count": 0,
        "analytic_bsdf_type_counts": {},
        "total_bsdfs": 0,
    }
    wrapper_types = {"twosided", "normalmap", "bumpmap", "blendbsdf", "mask"}
    # roughdielectric/thindielectric excluded: DoLP=0 in the polarized build
    # (dev_report 2026-07-06 §2.1); they are coerced to the trio before polar render.
    polar_rgb_types = {"pplastic", "dielectric", "conductor", "roughconductor"}
    for bsdf in root.findall(".//bsdf"):
        counts["total_bsdfs"] += 1
        bsdf_type = str(bsdf.get("type") or "")
        if bsdf_type == _CHANNEL_SPLIT_RGB_PLUGIN_TYPE:
            counts["three_band_measured"] += 1
            continue
        if bsdf_type in _MEASURED_BSDF_TYPES:
            filename = None
            for s in bsdf.findall("./string"):
                if s.get("name") == "filename":
                    filename = s.get("value") or ""
                    break
            if filename and _CHANNEL_SPLIT_FILENAME_RE.search(filename):
                counts["channel_split_candidates"] += 1
            if bsdf.find("./float[@name='wavelength']") is not None:
                counts["single_band_measured"] += 1
            else:
                counts["measured_without_wavelength"] += 1
            continue
        if bsdf_type not in wrapper_types:
            counts["analytic_or_diffuse_background"] += 1
            type_counts = dict(counts["analytic_bsdf_type_counts"])
            type_counts[bsdf_type] = type_counts.get(bsdf_type, 0) + 1
            counts["analytic_bsdf_type_counts"] = type_counts
            if bsdf_type in polar_rgb_types:
                counts["analytic_polar_rgb_count"] += 1
            else:
                counts["analytic_rgb_only_count"] += 1
    return counts


def _rgb_render_mode_from_policy(
    *,
    band_mode: str,
    timing: Mapping[str, Any] | None,
    band_policy_counts: Mapping[str, Any],
) -> str:
    if timing and bool(timing.get("channel_split_rgb")) and not bool(timing.get("channel_rgb_plugin")):
        return "channel_split"
    if int(band_policy_counts.get("three_band_measured", 0) or 0) > 0:
        return "rgb_plugin"
    if band_mode == "single":
        return "one_pass_single"
    if band_mode == "hybrid":
        return "one_pass_single"
    return "spectral_polarized" if str((timing or {}).get("variant", "")).endswith("spectral_polarized") else "one_pass_single"


def _channel_split_filename_for(value: str, *, target_nm: int) -> str:
    m = _CHANNEL_SPLIT_FILENAME_RE.search(value)
    if not m:
        return value
    return value[: m.start("wl")] + str(target_nm) + ".pbrdf"


def _convert_channel_split_measured_bsdfs_to_rgb_plugin(
    root: ET.Element, *, band_mode: str = "rgb"
) -> int:
    """Convert channel-split measured BSDFs to the RGB single-pass plugin.

    Source XML deliberately keeps the stable measured_polarized + 542 nm
    placeholder. RGB staging rewrites that placeholder to a plugin that evaluates
    the three channel-split pBRDF files in one Mitsuba RGB render.

    ``band_mode`` selects which materials get the 3-band plugin:
      * "rgb"    — all of them (current behaviour),
      * "single" — none (every measured BSDF stays single-band; colour comes from
                   its albedo_scale texture),
      * "hybrid" — only colour-bearing materials (achromatic ones stay single-band).
    Materials left as single-band still render colour via ``albedo_scale``.
    """
    if band_mode == "single":
        return 0
    converted = 0
    for bsdf in list(root.findall(".//bsdf")):
        if str(bsdf.get("type") or "") not in _MEASURED_BSDF_TYPES:
            continue
        filename = None
        for child in bsdf.findall("./string"):
            if child.get("name") == "filename":
                filename = child
                break
        if filename is None:
            continue
        value = filename.get("value") or ""
        m = _CHANNEL_SPLIT_FILENAME_RE.search(value)
        if not m:
            continue
        if band_mode == "hybrid" and not _measured_material_is_colored(m.group("material")):
            # Achromatic material: keep single-band (542 placeholder) × albedo_scale.
            continue

        bsdf.set("type", _CHANNEL_SPLIT_RGB_PLUGIN_TYPE)
        insert_at = list(bsdf).index(filename)
        bsdf.remove(filename)
        for child in list(bsdf.findall("./float")):
            if child.get("name") == "wavelength":
                bsdf.remove(child)
        for offset, (label, wavelength_nm) in enumerate(_RGB_CHANNEL_SPLIT_WAVELENGTHS_NM):
            bsdf.insert(
                insert_at + offset,
                ET.Element(
                    "string",
                    {
                        "name": f"filename_{label}",
                        "value": _channel_split_filename_for(value, target_nm=wavelength_nm),
                    },
                ),
            )
        converted += 1
    return converted


def _scene_has_channel_split_measured_bsdfs(scene_path: Path) -> bool:
    try:
        root = _parse_scene(scene_path)
    except Exception:
        return False
    for bsdf in root.findall(".//bsdf"):
        if str(bsdf.get("type") or "") not in _MEASURED_BSDF_TYPES:
            continue
        for s in bsdf.findall("./string"):
            if s.get("name") == "filename" and _CHANNEL_SPLIT_FILENAME_RE.search(s.get("value") or ""):
                return True
    return False


def _rgb_channel_intensity(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float32)
    if arr.ndim == 2:
        return arr.astype(np.float32)
    if arr.ndim != 3:
        raise RuntimeError(f"Unexpected channel-split RGB tensor shape: {arr.shape}")
    rgb = arr[:, :, :3] if arr.shape[2] >= 3 else np.repeat(arr[:, :, :1], 3, axis=2)
    return np.tensordot(
        rgb,
        np.array([0.2126, 0.7152, 0.0722], dtype=np.float32),
        axes=([2], [0]),
    ).astype(np.float32)


def _compose_channel_split_rgb(channel_images: Mapping[str, np.ndarray]) -> np.ndarray:
    missing = [label for label, _nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM if label not in channel_images]
    if missing:
        raise RuntimeError(f"Missing channel-split RGB render(s): {', '.join(missing)}")
    return np.stack(
        [
            _rgb_channel_intensity(channel_images["r"]),
            _rgb_channel_intensity(channel_images["g"]),
            _rgb_channel_intensity(channel_images["b"]),
        ],
        axis=2,
    ).astype(np.float32)


def _merge_channel_split_timing(channel_timings: Mapping[str, Mapping[str, Any]], *, spp: int) -> dict[str, Any]:
    ordered = [channel_timings[label] for label, _nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM if label in channel_timings]
    if not ordered:
        return {
            "variant": "unknown",
            "load_scene_s": 0.0,
            "scene_cache_hit": False,
            "render_s": 0.0,
            "total_s": 0.0,
            "spp": spp,
        }
    variants = [str(t.get("variant", "unknown")) for t in ordered]
    return {
        "variant": variants[0] if len(set(variants)) == 1 else ",".join(variants),
        "load_scene_s": float(sum(float(t.get("load_scene_s", 0.0)) for t in ordered)),
        "scene_cache_hit": all(bool(t.get("scene_cache_hit", False)) for t in ordered),
        "render_s": float(sum(float(t.get("render_s", 0.0)) for t in ordered)),
        "total_s": float(sum(float(t.get("total_s", 0.0)) for t in ordered)),
        "spp": spp,
        "channel_split_rgb": True,
        "channel_wavelengths_nm": {label: nm for label, nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM},
        "channel_timings": {label: dict(channel_timings[label]) for label, _nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM if label in channel_timings},
    }


def _substitute_measured_bsdfs_with_diffuse(root: ET.Element, *, reflectance: str = "0.7 0.7 0.7") -> int:
    """Replace measured BSDFs with diffuse stand-ins, preserving ids.

    Used for depth-only / AOV passes where BSDF response is irrelevant but the
    measured BSDF would otherwise force a multi-hundred-MB GPU upload.
    """
    swapped = 0
    for bsdf in list(root.findall(".//bsdf")):
        if str(bsdf.get("type") or "") not in _MEASURED_BSDF_TYPES:
            continue
        bsdf_id = bsdf.get("id")
        # Clear children and reset to diffuse.
        for child in list(bsdf):
            bsdf.remove(child)
        bsdf.set("type", "diffuse")
        rgb = ET.SubElement(bsdf, "rgb")
        rgb.set("name", "reflectance")
        rgb.set("value", reflectance)
        if bsdf_id is not None:
            bsdf.set("id", bsdf_id)
        swapped += 1
    return swapped


_MEASURED_SCOPES = {"analytic_only", "analytic_priority", "budgeted_measured", "measured_full"}
_PRIORITY_MEASURED_ROLES = {"forced", "target", "anchor"}
_MEASURED_SCOPE_STAGE_VERSION = "measured-scope-v3"
# Dynamic active-polar scenes update the source sensor through ``mi.traverse``.
# Give staged sensors a stable XML id and version their shared scene path so an
# old, anonymous base scene cannot be reused after that contract changed.
_DYNAMIC_SCENE_SENSOR_BINDING_STAGE_VERSION = "dynamic-sensor-binding-v3"


def _resolve_measured_scope(config: "RenderConfig | None") -> str:
    mode = getattr(config, "measured_scope", None) if config is not None else None
    if not mode:
        mode = os.environ.get("ROBOMITUBA_MEASURED_SCOPE")
    mode = str(mode or "analytic_only").strip().lower()
    return mode if mode in _MEASURED_SCOPES else "analytic_only"


def _resolve_max_measured_bsdfs(config: "RenderConfig | None") -> int:
    raw = getattr(config, "max_measured_bsdfs", None) if config is not None else None
    if raw is None:
        raw = os.environ.get("ROBOMITUBA_MAX_MEASURED_BSDFS", "3")
    try:
        return max(0, int(raw))
    except Exception:
        return 3


def _material_policy_path_for_scene(scene_path: Path) -> Path:
    return scene_path.parent / "render_scene_material_policy.json"


def _material_policy_signature(scene_path: Path) -> tuple[int, int]:
    path = _material_policy_path_for_scene(scene_path)
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (0, 0)


def _load_material_policy_for_scene(scene_path: Path) -> dict[str, Any] | None:
    path = _material_policy_path_for_scene(scene_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _select_measured_policy_records(
    policy: Mapping[str, Any] | None,
    *,
    measured_scope: str,
    max_measured_bsdfs: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = [
        dict(item)
        for item in ((policy or {}).get("shape_policies") or [])
        if isinstance(item, Mapping) and item.get("measured_candidate")
    ]
    enabled: list[dict[str, Any]] = []
    if measured_scope == "measured_full":
        enabled = records
    elif measured_scope == "budgeted_measured":
        enabled = records[:max_measured_bsdfs]
    elif measured_scope == "analytic_priority":
        priority = [record for record in records if str(record.get("measured_role") or "").lower() in _PRIORITY_MEASURED_ROLES]
        enabled = priority[:max_measured_bsdfs]
    else:
        enabled = []
    enabled_ids = {str(record.get("shape_id") or "") for record in enabled}
    summary = dict((policy or {}).get("summary") or {})
    return enabled, {
        "measured_scope": measured_scope,
        "max_measured_bsdfs": int(max_measured_bsdfs),
        "measured_candidates": len(records),
        "measured_enabled": len(enabled),
        "measured_suppressed": max(0, len(records) - len(enabled)),
        "enabled_shape_ids": sorted(sid for sid in enabled_ids if sid),
        "analytic_polar_rgb_count": int(summary.get("analytic_polar_rgb_count", 0) or 0),
        "analytic_rgb_only_count": int(summary.get("analytic_rgb_only_count", 0) or 0),
        "invalid_analytic_fallback_count": int(summary.get("invalid_analytic_fallback_count", 0) or 0),
        "analytic_bsdf_type_counts": dict(summary.get("analytic_bsdf_type_counts") or {}),
    }


def _append_measured_candidate_bsdf(
    shape: ET.Element,
    candidate: Mapping[str, Any],
    extracted_material: Mapping[str, Any] | None,
) -> bool:
    channels_dir = str(candidate.get("channels_dir") or "").strip()
    native_file = str(candidate.get("native_file") or "").strip()
    if channels_dir:
        filename = channels_dir.rstrip("/") + "/542.pbrdf"
    elif native_file:
        filename = native_file
    else:
        return False

    for child in list(shape):
        if child.tag in {"bsdf", "ref"}:
            shape.remove(child)

    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    bsdf_type = "measured_polarized" if str(candidate.get("bsdf_strategy") or "measured_polarized") == "measured_polarized" else "measured"
    bsdf = ET.SubElement(twosided, "bsdf", {"type": bsdf_type})
    ET.SubElement(bsdf, "string", {"name": "filename", "value": filename})
    if bsdf_type == "measured_polarized":
        ET.SubElement(bsdf, "float", {"name": "alpha_sample", "value": "0.0800"})

    base_tex = str((extracted_material or {}).get("base_color_texture_ref") or candidate.get("base_color_texture_ref") or "").strip()
    if base_tex and Path(base_tex).exists():
        tex = ET.SubElement(bsdf, "texture", {"name": "albedo_scale", "type": "bitmap"})
        ET.SubElement(tex, "string", {"name": "filename", "value": base_tex})
    else:
        base_factor = (extracted_material or {}).get("base_color_factor") or candidate.get("base_color_factor")
        if isinstance(base_factor, (list, tuple)) and len(base_factor) >= 3:
            try:
                rgb = " ".join(f"{max(0.0, min(1.0, float(c))):.6g}" for c in base_factor[:3])
                ET.SubElement(bsdf, "rgb", {"name": "albedo_scale", "value": rgb})
            except Exception:
                pass
    return True


def _base_color_from_policy(
    analytic: Mapping[str, Any],
    extracted_material: Mapping[str, Any] | None,
) -> tuple[str | None, str]:
    base_tex = str((extracted_material or {}).get("base_color_texture_ref") or analytic.get("base_color_texture_ref") or "").strip()
    if base_tex and Path(base_tex).exists():
        return base_tex, "0.65 0.62 0.58"
    base_factor = (extracted_material or {}).get("base_color_factor") or analytic.get("base_color_factor")
    if isinstance(base_factor, (list, tuple)) and len(base_factor) >= 3:
        try:
            rgb = " ".join(f"{max(0.0, min(1.0, float(c))):.6g}" for c in base_factor[:3])
            return None, rgb
        except Exception:
            pass
    return None, "0.65 0.62 0.58"


def _append_policy_analytic_bsdf(
    shape: ET.Element,
    analytic: Mapping[str, Any],
    extracted_material: Mapping[str, Any] | None,
) -> bool:
    strategy = str(analytic.get("bsdf_strategy") or analytic.get("analytic_strategy") or "pplastic").strip().lower()
    if strategy in {"roughplastic", "diffuse", "plastic", "principled", "measured", "measured_polarized"}:
        strategy = "pplastic"

    for child in list(shape):
        if child.tag in {"bsdf", "ref"}:
            shape.remove(child)

    if strategy == "dielectric":
        bsdf = ET.SubElement(shape, "bsdf", {"type": "dielectric"})
        ET.SubElement(bsdf, "float", {"name": "int_ior", "value": "1.5"})
        return True
    if strategy == "roughdielectric":
        bsdf = ET.SubElement(shape, "bsdf", {"type": "roughdielectric"})
        alpha = _clamp_bsdf_alpha(analytic.get("roughness"), default=0.2, floor=_MIN_ROUGHDIELECTRIC_ALPHA)
        ET.SubElement(bsdf, "float", {"name": "alpha", "value": f"{alpha:.4f}"})
        ET.SubElement(bsdf, "float", {"name": "int_ior", "value": "1.5"})
        return True
    if strategy == "conductor":
        twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
        bsdf = ET.SubElement(twosided, "bsdf", {"type": "conductor"})
        ET.SubElement(bsdf, "string", {"name": "material", "value": "Al"})
        return True
    if strategy == "roughconductor":
        twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
        bsdf = ET.SubElement(twosided, "bsdf", {"type": "roughconductor"})
        ET.SubElement(bsdf, "string", {"name": "material", "value": "Al"})
        alpha = _clamp_bsdf_alpha(analytic.get("roughness"), default=0.2, floor=_MIN_ROUGHCONDUCTOR_ALPHA)
        ET.SubElement(bsdf, "float", {"name": "alpha", "value": f"{alpha:.4f}"})
        return True

    # The material policy is also used to make a Stokes-compatible analytic
    # scene.  Do not turn ordinary PBR surfaces into a uniform colour while
    # doing that: this used to make every carpet/wall/tile in a polar render
    # look like white plastic, even though the source render XML referenced
    # the correct PBR maps.  Preserve the texture inputs that ``pplastic`` and
    # ``normalmap`` can represent in the RGB-polarized variant.
    normal_tex = str(
        (extracted_material or {}).get("normal_texture_ref")
        or analytic.get("normal_texture_ref")
        or ""
    ).strip()
    roughness_tex = str(
        (extracted_material or {}).get("roughness_texture_ref")
        or analytic.get("roughness_texture_ref")
        or ""
    ).strip()
    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    parent = twosided
    if normal_tex and Path(normal_tex).is_file():
        normalmap = ET.SubElement(twosided, "bsdf", {"type": "normalmap"})
        normal_texture = ET.SubElement(normalmap, "texture", {"name": "normalmap", "type": "bitmap"})
        ET.SubElement(normal_texture, "string", {"name": "filename", "value": normal_tex})
        ET.SubElement(normal_texture, "boolean", {"name": "raw", "value": "true"})
        parent = normalmap
    bsdf = ET.SubElement(parent, "bsdf", {"type": "pplastic"})
    base_tex, rgb = _base_color_from_policy(analytic, extracted_material)
    if base_tex:
        tex = ET.SubElement(bsdf, "texture", {"name": "diffuse_reflectance", "type": "bitmap"})
        ET.SubElement(tex, "string", {"name": "filename", "value": base_tex})
    else:
        ET.SubElement(bsdf, "rgb", {"name": "diffuse_reflectance", "value": rgb})
    if roughness_tex and Path(roughness_tex).is_file():
        roughness_texture = ET.SubElement(bsdf, "texture", {"name": "alpha", "type": "bitmap"})
        ET.SubElement(roughness_texture, "string", {"name": "filename", "value": roughness_tex})
        ET.SubElement(roughness_texture, "boolean", {"name": "raw", "value": "true"})
    else:
        alpha = _clamp_bsdf_alpha(analytic.get("roughness"), default=0.2, floor=_MIN_ROUGHPLASTIC_ALPHA)
        ET.SubElement(bsdf, "float", {"name": "alpha", "value": f"{max(0.2, alpha):.4f}"})
    return True


def _bsdf_tree_contains_measured(bsdf: ET.Element) -> bool:
    bsdf_type = str(bsdf.get("type") or "")
    if bsdf_type in _MEASURED_BSDF_TYPES or bsdf_type == _CHANNEL_SPLIT_RGB_PLUGIN_TYPE:
        return True
    return any(child.tag == "bsdf" and _bsdf_tree_contains_measured(child) for child in bsdf)


def _remove_unreferenced_measured_bsdf_declarations(root: ET.Element) -> int:
    referenced_ids = {str(ref.get("id")) for ref in root.findall(".//ref") if ref.get("id")}
    removed = 0
    for child in list(root):
        if child.tag != "bsdf":
            continue
        bsdf_id = child.get("id")
        if bsdf_id and bsdf_id in referenced_ids:
            continue
        if _bsdf_tree_contains_measured(child):
            root.remove(child)
            removed += 1
    return removed


def _apply_measured_scope_policy(
    root: ET.Element,
    *,
    source_scene: Path,
    measured_scope: str,
    max_measured_bsdfs: int,
) -> dict[str, Any]:
    policy = _load_material_policy_for_scene(source_scene)
    enabled, summary = _select_measured_policy_records(
        policy,
        measured_scope=measured_scope,
        max_measured_bsdfs=max_measured_bsdfs,
    )
    injected = 0
    if policy is None:
        if measured_scope == "analytic_only":
            summary["legacy_measured_substituted"] = _substitute_measured_bsdfs_with_diffuse(root)
        return summary

    shapes = {str(shape.get("id") or ""): shape for shape in root.findall(".//shape") if shape.get("id")}
    analytic_rewritten = 0
    for record in (policy.get("shape_policies") or []):
        if not isinstance(record, Mapping):
            continue
        shape = shapes.get(str(record.get("shape_id") or ""))
        if shape is None:
            continue
        if _append_policy_analytic_bsdf(
            shape,
            record.get("analytic_fallback") if isinstance(record.get("analytic_fallback"), Mapping) else record,
            record.get("extracted_material") if isinstance(record.get("extracted_material"), Mapping) else None,
        ):
            analytic_rewritten += 1
    for record in enabled:
        shape_id = str(record.get("shape_id") or "")
        shape = shapes.get(shape_id)
        if shape is None:
            continue
        if _append_measured_candidate_bsdf(
            shape,
            dict(record.get("measured_candidate") or {}),
            record.get("extracted_material") if isinstance(record.get("extracted_material"), Mapping) else None,
        ):
            injected += 1
    summary["analytic_rewritten"] = analytic_rewritten
    summary["measured_injected"] = injected
    summary["unreferenced_measured_declarations_removed"] = _remove_unreferenced_measured_bsdf_declarations(root)
    return summary


def _measured_scope_policy_inventory(
    scene_path: Path,
    *,
    measured_scope: str,
    max_measured_bsdfs: int,
) -> dict[str, Any]:
    policy = _load_material_policy_for_scene(scene_path)
    _enabled, summary = _select_measured_policy_records(
        policy,
        measured_scope=measured_scope,
        max_measured_bsdfs=max_measured_bsdfs,
    )
    return summary


def _scene_has_enabled_measured_policy(
    scene_path: Path,
    *,
    measured_scope: str,
    max_measured_bsdfs: int,
) -> bool:
    policy = _load_material_policy_for_scene(scene_path)
    enabled, _summary = _select_measured_policy_records(
        policy,
        measured_scope=measured_scope,
        max_measured_bsdfs=max_measured_bsdfs,
    )
    return bool(enabled)


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


def _active_lights_signature(
    active_lights: Sequence["ActiveLightSpec"],
    base_pose: Any,
    pass_kind: str,
) -> Any:
    """Signature for pose-baked active lights (Stage B): pose IS included, so a
    different base_pose yields a different staged scene (correct, no reuse). Stage C
    will use a topology-only variant that excludes pose to enable reuse."""
    if not active_lights or not pass_kind:
        return None
    relevant = [asdict(l) for l in active_lights if getattr(l, "enabled", True) and pass_kind in (l.modalities or [])]
    if not relevant:
        return None
    try:
        pose = np.round(np.asarray(base_pose, dtype=np.float32).reshape(-1), 5).tolist() if base_pose is not None else None
    except Exception:
        pose = None
    return _normalize_signature_value({"pass": pass_kind, "lights": relevant, "base_pose": pose})


def _should_reuse_staged_scene(out_scene: Path, *, signature: tuple[Any, ...]) -> bool:
    cache_key = str(out_scene.resolve())
    signature = _effective_stage_signature(signature)
    with _SCENE_CACHE_LOCK:
        cached_signature = _STAGED_SCENE_SIGNATURE_CACHE.get(cache_key)
    return cached_signature == signature and out_scene.exists()


def _record_staged_scene_signature(out_scene: Path, *, signature: tuple[Any, ...]) -> None:
    cache_key = str(out_scene.resolve())
    signature = _effective_stage_signature(signature)
    with _SCENE_CACHE_LOCK:
        _STAGED_SCENE_SIGNATURE_CACHE[cache_key] = signature


def _texture_max_resolution() -> int:
    raw = os.environ.get("ROBOMITUBA_TEXTURE_MAX_RESOLUTION", "0")
    try:
        return max(0, int(str(raw).strip() or "0"))
    except (TypeError, ValueError):
        return 0


def _texture_cache_signature() -> tuple[str, int]:
    return ("texture_max_resolution", _texture_max_resolution())


def _effective_stage_signature(signature: tuple[Any, ...]) -> tuple[Any, ...]:
    return (*tuple(signature), _texture_cache_signature())


def _texture_cache_root(out_scene: Path, *, override: Path | None = None) -> Path:
    override = override or (Path(os.environ["ROBOMITUBA_TEXTURE_CACHE_DIR"]).expanduser()
                            if os.environ.get("ROBOMITUBA_TEXTURE_CACHE_DIR") else None)
    if override:
        return Path(override).resolve()
    return Path.cwd().resolve() / "out" / "texture_cache" / "mitsuba_downsampled"


def _texture_audit_path(scene_path: Path) -> Path:
    return scene_path.with_suffix(".texture_audit.json")


def _downsampled_texture_path(src: Path, *, cache_root: Path, max_resolution: int) -> Path | None:
    try:
        stat = src.stat()
    except OSError:
        return None
    digest = hashlib.sha1(
        f"{src.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{max_resolution}".encode("utf-8")
    ).hexdigest()[:16]
    suffix = src.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".exr"}:
        return None
    return cache_root / f"max{max_resolution}" / digest[:2] / f"{src.stem}_{digest}{suffix}"


@contextmanager
def _texture_cache_write_guard(cached: Path):
    """Serialize first-writer cache publication across independent GPU workers.

    Worker processes do not share Python locks.  The cache filename is content/source
    stable, so a cold fleet start can otherwise make every worker resample the same
    source image before their atomic ``os.replace`` calls race.  A lock sidecar makes
    the first writer authoritative while retaining atomic publication of the image.
    """
    if cached.exists():
        yield False
        return

    cached.parent.mkdir(parents=True, exist_ok=True)
    lock = cached.with_name(f".{cached.name}.lock")
    timeout_s = max(1.0, float(os.environ.get("ROBOMITUBA_TEXTURE_CACHE_LOCK_TIMEOUT_S", "120")))
    stale_s = max(timeout_s, float(os.environ.get("ROBOMITUBA_TEXTURE_CACHE_LOCK_STALE_S", "900")))
    deadline = time.monotonic() + timeout_s
    fd: int | None = None
    while fd is None:
        if cached.exists():
            yield False
            return
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"timed out waiting for texture cache writer: cache={cached} lock={lock}"
                )
            time.sleep(0.05)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()} created_at={time.time():.6f}\n")
        yield True
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


def _ensure_downsampled_exr(src: Path, cached: Path, *, max_resolution: int) -> Path | None:
    try:
        import imageio.v3 as iio
    except Exception as exc:
        print(
            f"[multimodal] EXR texture downsample skipped path={src}: imageio unavailable ({exc})",
            file=sys.stderr,
            flush=True,
        )
        return None
    try:
        image = np.asarray(iio.imread(src))
        if image.ndim < 2:
            return None
        height, width = int(image.shape[0]), int(image.shape[1])
        largest = max(width, height)
        if largest <= max_resolution:
            return src
        factor = max(1, int(np.ceil(largest / float(max_resolution))))
        new_height = max(1, height // factor)
        new_width = max(1, width // factor)
        cropped = image[: new_height * factor, : new_width * factor]
        if image.ndim == 2:
            resized = cropped.reshape(new_height, factor, new_width, factor).mean(axis=(1, 3))
        else:
            resized = cropped.reshape(new_height, factor, new_width, factor, *image.shape[2:]).mean(axis=(1, 3))
        temporary = cached.with_name(
            f".{cached.stem}.tmp.{os.getpid()}.{threading.get_ident()}{cached.suffix}"
        )
        try:
            iio.imwrite(temporary, resized.astype(np.float32, copy=False))
            os.replace(temporary, cached)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return cached
    except Exception as exc:
        print(
            f"[multimodal] EXR texture downsample skipped path={src} max={max_resolution}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None


def _ensure_downsampled_texture(src: Path, *, cache_root: Path, max_resolution: int) -> Path | None:
    cached = _downsampled_texture_path(src, cache_root=cache_root, max_resolution=max_resolution)
    if cached is None:
        return None
    if cached.exists():
        return cached
    try:
        with _texture_cache_write_guard(cached) as owns_write:
            if not owns_write:
                return cached
            if cached.suffix.lower() == ".exr":
                return _ensure_downsampled_exr(src, cached, max_resolution=max_resolution)
            with Image.open(src) as image:
                width, height = image.size
                largest = max(width, height)
                if largest <= max_resolution:
                    return src
                scale = max_resolution / float(largest)
                new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
                resized = image.copy()
                resized.thumbnail(new_size, Image.Resampling.LANCZOS)
                save_kwargs: dict[str, Any] = {}
                if cached.suffix.lower() in {".jpg", ".jpeg"}:
                    save_kwargs.update({"quality": 92, "subsampling": 0})
                # The process guard above prevents redundant resampling.  Keep
                # atomic publication as a second line of defence against a crash.
                temporary = cached.with_name(
                    f".{cached.stem}.tmp.{os.getpid()}.{threading.get_ident()}{cached.suffix}"
                )
                try:
                    resized.save(temporary, **save_kwargs)
                    os.replace(temporary, cached)
                finally:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
                return cached
    except Exception as exc:
        print(
            f"[multimodal] texture downsample skipped path={src} max={max_resolution}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None


def _rewrite_texture_filenames(
    root: ET.Element,
    *,
    out_scene: Path,
    max_resolution: int | None = None,
    cache_root: Path | None = None,
) -> dict[str, int]:
    max_resolution = _texture_max_resolution() if max_resolution is None else max(0, int(max_resolution))
    if max_resolution <= 0:
        return {"rewritten": 0, "skipped": 0}
    cache_root = _texture_cache_root(out_scene, override=cache_root)
    rewritten = 0
    skipped = 0
    for node in root.iter():
        if node.tag not in {"texture", "emitter"}:
            continue
        plugin_type = node.attrib.get("type")
        if plugin_type not in {"bitmap", "envmap"}:
            continue
        filename = node.find("string[@name='filename']")
        if filename is None:
            continue
        value = filename.attrib.get("value")
        if not value:
            continue
        src = Path(value)
        if not src.is_absolute():
            # Material-policy injection stores repo-relative texture refs.  The
            # render-scene sync capped the original XML, but staging then appends
            # these analytic BSDFs and used to skip every relative filename,
            # silently resurrecting 4K atlases in the GPU worker.  Workers run from
            # the repo root; also support XML-relative paths for standalone scenes.
            cwd_candidate = (Path.cwd() / src).resolve()
            scene_candidate = (out_scene.parent / src).resolve()
            if cwd_candidate.is_file():
                src = cwd_candidate
            elif scene_candidate.is_file():
                src = scene_candidate
            else:
                skipped += 1
                continue
        cached = _ensure_downsampled_texture(src, cache_root=cache_root, max_resolution=max_resolution)
        if cached is None:
            skipped += 1
            continue
        if cached != src:
            filename.attrib["value"] = str(cached)
            rewritten += 1
    if rewritten or skipped:
        print(
            f"[multimodal] texture cap max={max_resolution} references_retargeted={rewritten} "
            f"skipped={skipped} cache={cache_root}",
            file=sys.stderr,
            flush=True,
        )
    return {"rewritten": rewritten, "skipped": skipped}



def _texture_image_size(path: Path) -> tuple[int, int] | None:
    if path.suffix.lower() == ".exr":
        try:
            import imageio.v3 as iio
            image = np.asarray(iio.imread(path))
            if image.ndim >= 2:
                return int(image.shape[1]), int(image.shape[0])
        except Exception:
            return None
        return None
    try:
        with Image.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except Exception:
        return None


def _build_texture_audit(
    root: ET.Element,
    *,
    out_scene: Path,
    max_resolution: int | None = None,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    max_resolution = _texture_max_resolution() if max_resolution is None else max(0, int(max_resolution))
    cache_root = _texture_cache_root(out_scene, override=cache_root)
    texture_refs = 0
    downsampled_refs = 0
    original_refs = 0
    original_gt_profile_refs = 0
    missing_refs = 0
    unreadable_refs = 0
    original_gt_profile_examples: list[str] = []
    for node in root.iter():
        if node.tag not in {"texture", "emitter"}:
            continue
        plugin_type = node.attrib.get("type")
        if plugin_type not in {"bitmap", "envmap"}:
            continue
        filename = node.find("string[@name='filename']")
        if filename is None:
            continue
        value = filename.attrib.get("value")
        if not value:
            continue
        texture_refs += 1
        src = Path(value)
        src_text = str(src)
        if "out/texture_cache/mitsuba_downsampled" in src_text or src_text.startswith(str(cache_root)):
            downsampled_refs += 1
            continue
        original_refs += 1
        if not src.exists():
            missing_refs += 1
            continue
        size = _texture_image_size(src)
        if size is None:
            unreadable_refs += 1
            continue
        width, height = size
        if max_resolution > 0 and max(width, height) > max_resolution:
            original_gt_profile_refs += 1
            if len(original_gt_profile_examples) < 12:
                original_gt_profile_examples.append(src_text)
    audit = {
        "texture_profile": max_resolution,
        "texture_refs": texture_refs,
        "downsampled_refs": downsampled_refs,
        "original_refs": original_refs,
        "original_gt_profile_refs": original_gt_profile_refs,
        "missing_refs": missing_refs,
        "xml_path": str(out_scene),
        "audit_ok": original_gt_profile_refs == 0,
    }
    if unreadable_refs:
        audit["unreadable_refs"] = unreadable_refs
    if original_gt_profile_examples:
        audit["original_gt_profile_examples"] = original_gt_profile_examples
    return audit


def _write_texture_audit(
    root: ET.Element,
    *,
    out_scene: Path,
    fail_on_gt_profile: bool = False,
    max_resolution: int | None = None,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    audit = _build_texture_audit(
        root, out_scene=out_scene, max_resolution=max_resolution, cache_root=cache_root,
    )
    audit_path = _texture_audit_path(out_scene)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if fail_on_gt_profile and int(audit.get("original_gt_profile_refs", 0) or 0) > 0:
        raise RuntimeError(
            "texture audit failed: "
            f"profile=max{audit.get('texture_profile')} "
            f"original_gt_profile_refs={audit.get('original_gt_profile_refs')} "
            f"xml={out_scene}"
        )
    return audit


def _ensure_texture_audit(scene_path: Path, *, fail_on_gt_profile: bool = False) -> dict[str, Any] | None:
    audit_path = _texture_audit_path(scene_path)
    if audit_path.exists():
        try:
            return json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        root = ET.parse(scene_path).getroot()
    except Exception:
        return None
    return _write_texture_audit(root, out_scene=scene_path, fail_on_gt_profile=fail_on_gt_profile)


def _texture_audit_progress_payload(scene_path: Path) -> dict[str, Any]:
    audit_path = _texture_audit_path(scene_path)
    if not audit_path.exists():
        return {"texture_profile": _texture_max_resolution()}
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return {"texture_profile": _texture_max_resolution()}
    return {
        "texture_profile": audit.get("texture_profile", _texture_max_resolution()),
        "texture_audit": {
            "texture_refs": audit.get("texture_refs"),
            "downsampled_refs": audit.get("downsampled_refs"),
            "original_refs": audit.get("original_refs"),
            "original_gt_profile_refs": audit.get("original_gt_profile_refs"),
            "missing_refs": audit.get("missing_refs"),
            "xml_path": audit.get("xml_path"),
            "audit_ok": audit.get("audit_ok"),
        },
    }

def _write_scene(root: ET.Element, out_scene: Path) -> Path:
    _rewrite_texture_filenames(root, out_scene=out_scene)
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


def cap_scene_texture_resolution(
    scene_path: Path,
    *,
    max_resolution: int,
    cache_dir: Path | None = None,
    fail_on_unbounded: bool = True,
) -> dict[str, Any]:
    """Rewrite one derived render XML to use a bounded, shared texture cache.

    This is intentionally a *render-scene* operation: source GLB/PBR atlases
    stay authoritative at their export resolution, while a memory-limited
    worker uses content-addressed downsampled copies.  It is safe for several
    processes to share ``cache_dir`` because cache publication is atomic.
    """
    scene_path = Path(scene_path).resolve()
    max_resolution = max(0, int(max_resolution))
    cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir is not None else None
    try:
        # Render-scene XML carries ``opticalnav-obj:`` comments used by the
        # editor index and by additive perturbation publishing. Preserve them
        # while applying a texture-only rewrite.
        tree = ET.parse(
            scene_path,
            parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)),
        )
    except (OSError, ET.ParseError) as exc:
        raise RuntimeError(f"cannot apply texture cap to {scene_path}: {exc}") from exc
    root = tree.getroot()
    rewrite = _rewrite_texture_filenames(
        root, out_scene=scene_path, max_resolution=max_resolution, cache_root=cache_dir,
    )
    # Do not mutate a scene in place while Mitsuba might read it.  The IR
    # workers call this before ``mi.load_file``; the atomic replace also makes
    # the helper safe for a retry using the same batch directory.
    temporary = scene_path.with_name(
        f".{scene_path.stem}.texture-cap.{os.getpid()}.{threading.get_ident()}{scene_path.suffix}"
    )
    try:
        ET.indent(tree, space="  ")
        tree.write(temporary, encoding="utf-8", xml_declaration=True)
        os.replace(temporary, scene_path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    audit = _write_texture_audit(
        root,
        out_scene=scene_path,
        fail_on_gt_profile=fail_on_unbounded,
        max_resolution=max_resolution,
        cache_root=cache_dir,
    )
    return {**audit, "rewritten": int(rewrite["rewritten"]), "skipped": int(rewrite["skipped"]),
            "cache_dir": str(_texture_cache_root(scene_path, override=cache_dir))}


def _has_emitter(root: ET.Element) -> bool:
    if root.find("./emitter") is not None:
        return True
    return any(shape.find("./emitter") is not None for shape in root.findall("./shape"))


def _inject_constant_emitter(root: ET.Element, radiance: float) -> None:
    emitter = ET.SubElement(root, "emitter", {"type": "constant"})
    ET.SubElement(emitter, "rgb", {"name": "radiance", "value": f"{float(radiance):.6f}"})


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


def _remove_shape_bsdf_children(shape: ET.Element) -> None:
    """Remove direct material bindings before authoring a replacement BSDF.

    Mitsuba accepts exactly one BSDF child per shape. Scene XML can bind that
    material either inline with ``<bsdf>`` or by referencing a top-level BSDF
    via ``<ref id="..."/>``. Polarization fallback rewrites per-shape BSDFs, so
    both forms must be removed first.
    """

    for child in list(shape):
        if child.tag == "bsdf" or child.tag == "ref":
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
    ET.SubElement(
        principled,
        "float",
        {"name": "roughness", "value": f"{_clamp_bsdf_alpha(roughness, default=0.5, floor=_MIN_ROUGHPLASTIC_ALPHA):.4f}"},
    )
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
    ET.SubElement(
        roughplastic,
        "float",
        {"name": "alpha", "value": f"{_clamp_bsdf_alpha(alpha, default=0.2, floor=_MIN_ROUGHPLASTIC_ALPHA):.4f}"},
    )
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
    ET.SubElement(
        roughconductor,
        "float",
        {"name": "alpha", "value": f"{_clamp_bsdf_alpha(alpha, default=0.2, floor=_MIN_ROUGHCONDUCTOR_ALPHA):.4f}"},
    )


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


def _active_light_mount_matrix(mount: Mapping[str, Any] | None) -> np.ndarray:
    """Canonical (row-major, translation in col 3) local mount transform from a
    rig mount dict {xyz_m[3], rpy_deg[3]}. Y-up world; rotation = Ry(yaw) Rx(pitch)
    Rz(roll) with rpy=[roll_x, pitch_x?, yaw_y] following the codebase Y-up
    convention (yaw about +Y). The emitter's local +Z is the beam axis, so at
    identity the flash points along +Z; rpy aims it."""
    mount = mount or {}
    xyz = mount.get("xyz_m") or [0.0, 0.0, 0.0]
    rpy = mount.get("rpy_deg") or [0.0, 0.0, 0.0]
    try:
        tx, ty, tz = float(xyz[0]), float(xyz[1]), float(xyz[2])
    except Exception:
        tx, ty, tz = 0.0, 0.0, 0.0
    try:
        roll = np.deg2rad(float(rpy[0])); pitch = np.deg2rad(float(rpy[1])); yaw = np.deg2rad(float(rpy[2]))
    except Exception:
        roll = pitch = yaw = 0.0
    cy, sy = np.cos(yaw), np.sin(yaw)
    cx, sx = np.cos(pitch), np.sin(pitch)
    cz, sz = np.cos(roll), np.sin(roll)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)   # about +Y
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)   # about +X
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)   # about +Z
    rot = ry @ rx @ rz
    m = np.eye(4, dtype=np.float32)
    m[:3, :3] = rot
    m[:3, 3] = [tx, ty, tz]
    return m


def _active_light_intensity_xml(emitter: ET.Element, light: ActiveLightSpec, *, spectral: bool, name: str = "intensity") -> None:
    """Emit the emitter radiance field (``name`` = "intensity" for spot/point,
    "radiance" for an area emitter). NIR uses a single-band spectrum when a
    spectral variant is active; otherwise a grayscale-proxy rgb (Stage 5 upgrades
    the spectral path)."""
    scale = max(0.0, float(light.radiance))
    if light.spectrum_kind == "nir":
        if spectral:
            ET.SubElement(emitter, "spectrum", {"name": name, "value": f"{float(light.wavelength_nm):.1f}:{scale:.6g}"})
        else:
            ET.SubElement(emitter, "rgb", {"name": name, "value": f"{scale:.6g},{scale:.6g},{scale:.6g}"})
    else:
        rgb = light.rgb if isinstance(light.rgb, (list, tuple)) and len(light.rgb) >= 3 else [1.0, 1.0, 1.0]
        vals = ",".join(f"{max(0.0, float(c)) * scale:.6g}" for c in rgb[:3])
        ET.SubElement(emitter, "rgb", {"name": name, "value": vals})


def _append_base_active_lights(
    root: ET.Element,
    active_lights: Sequence["ActiveLightSpec"],
    base_pose: np.ndarray | Sequence[float] | None,
    *,
    pass_kind: str,
    spectral: bool,
) -> int:
    """Bake rig-mounted active lights into the scene as spot/point emitters (+ an
    optional linear `polarizer` surface for polarized illumination), positioned at
    light_to_world = base_pose @ mount. `pass_kind` in {"rgb","nir","polar"} filters
    which lights participate. Returns the count injected. Pose-baked (Stage B):
    correctness-first, no scene reuse."""
    if not active_lights or base_pose is None:
        return 0
    base = normalize_mat4_storage(base_pose)
    injected = 0
    for light in active_lights:
        if not getattr(light, "enabled", True):
            continue
        if pass_kind not in (light.modalities or []):
            continue
        world = (base @ _active_light_mount_matrix(light.mount)).astype(np.float32)
        emitter_type = light.emitter_type if light.emitter_type in ("spot", "point", "area") else "spot"
        area_half = max(1e-3, float(getattr(light, "area_size_m", 0.1)))
        if emitter_type == "area":
            # Emissive rectangle (local normal +Z = beam). Required for polarized
            # illumination: unlike a delta spot/point, an area emitter's radiance
            # physically transmits through the polarizer surface in front of it.
            shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": f"active_light_{light.light_id}"})
            stf = ET.SubElement(shape, "transform", {"name": "to_world"})
            eshalf = np.eye(4, dtype=np.float64); eshalf[0, 0] = eshalf[1, 1] = area_half
            ET.SubElement(stf, "matrix", {"value": _matrix_to_string((world.astype(np.float64) @ eshalf).astype(np.float32))})
            area_emitter = ET.SubElement(shape, "emitter", {"type": "area"})
            _active_light_intensity_xml(area_emitter, light, spectral=spectral, name="radiance")
        else:
            emitter = ET.SubElement(root, "emitter", {"type": emitter_type, "id": f"active_light_{light.light_id}"})
            etf = ET.SubElement(emitter, "transform", {"name": "to_world"})
            ET.SubElement(etf, "matrix", {"value": _matrix_to_string(world)})
            _active_light_intensity_xml(emitter, light, spectral=spectral)
            if emitter_type == "spot":
                ET.SubElement(emitter, "float", {"name": "cutoff_angle", "value": f"{float(light.cutoff_angle_deg):.4f}"})
                ET.SubElement(emitter, "float", {"name": "beam_width", "value": f"{float(light.beam_width_deg):.4f}"})
        injected += 1
        # Polarized illumination: emitters emit UNPOLARIZED, so place a linear
        # `polarizer` BSDF surface just in front of the emitter along its +Z beam.
        # (Genuinely polarizes only for an area emitter — see area note above.)
        if light.polarized:
            offset = np.eye(4, dtype=np.float64)
            offset[:3, 3] = [0.0, 0.0, 0.03 if emitter_type == "area" else 0.02]  # along local +Z (beam)
            # rectangle facing the beam; local normal is +Z. For an area emitter,
            # size the polarizer to cover the emissive panel so all rays transmit.
            pol_half = max(0.05, area_half * 1.1) if emitter_type == "area" else 0.05
            pol_world = (world.astype(np.float64) @ offset).astype(np.float32)
            pol_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": f"active_polarizer_{light.light_id}"})
            ptf = ET.SubElement(pol_shape, "transform", {"name": "to_world"})
            scale = np.eye(4, dtype=np.float32); scale[0, 0] = scale[1, 1] = pol_half
            ET.SubElement(ptf, "matrix", {"value": _matrix_to_string((pol_world @ scale).astype(np.float32))})
            pol_bsdf = ET.SubElement(pol_shape, "bsdf", {"type": "polarizer"})
            ET.SubElement(pol_bsdf, "float", {"name": "theta", "value": f"{float(light.polarizer_angle_deg):.4f}"})
    return injected


def _append_camera_assist_light(
    root: ET.Element,
    camera_to_world: np.ndarray,
    assist_light: AssistLightSpec,
    *,
    polarized: bool,
    id_suffix: str = "",
) -> None:
    default_radiance = 18.0 if polarized else 14.0
    radiance = float(assist_light.extras.get("radiance", default_radiance))
    suffix = str(id_suffix or "")
    light_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": f"camera_assist_light{suffix}"})
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

    polar_shape = ET.SubElement(root, "shape", {"type": "rectangle", "id": f"camera_assist_polarizer{suffix}"})
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
    # An unnamed XML sensor is exposed by Mitsuba as ``perspective.to_world``
    # (rather than ``sensor.to_world``). Dynamic active-polar rendering must
    # update it after loading, so all newly staged scenes receive a stable
    # parameter name. Preserve explicit source ids such as ``polar_cam``.
    sensor.attrib.setdefault("id", "sensor")

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
    ambient_radiance: float = 1.0,
    measured_wavelength_nm: int | None = None,
    channel_rgb_plugin: bool = False,
    band_mode: str = "rgb",
    measured_scope: str = "analytic_only",
    max_measured_bsdfs: int = 3,
    active_lights: Sequence["ActiveLightSpec"] = (),
    base_pose: Any = None,
    active_pass_kind: str = "",
    active_spectral: bool = False,
) -> Path:
    stage_signature = (
        "path",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (integrator_type, int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
        _active_lights_signature(active_lights, base_pose, active_pass_kind),
        round(float(ambient_radiance), 4),
        int(measured_wavelength_nm) if measured_wavelength_nm else 0,
        bool(channel_rgb_plugin),
        str(band_mode),
        str(measured_scope),
        int(max_measured_bsdfs),
        _MEASURED_SCOPE_STAGE_VERSION,
        _material_policy_signature(scene_path),
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
        if channel_rgb_plugin:
            _apply_measured_scope_policy(
                root,
                source_scene=scene_path,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )
            _stage_measured_bsdfs_for_rgb(root, band_mode=band_mode)
        elif measured_wavelength_nm is not None:
            _apply_measured_scope_policy(
                root,
                source_scene=scene_path,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )
            _ensure_measured_bsdf_wavelength(root, target_nm=int(measured_wavelength_nm))
        else:
            _apply_measured_scope_policy(
                root,
                source_scene=scene_path,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )

    root = _scene_template(
        scene_path,
        branch_kind="path",
        branch_signature=(
            integrator_type,
            int(max_depth),
            int(rr_depth),
            int(samples_per_pass or 0),
            int(measured_wavelength_nm) if measured_wavelength_nm else 0,
            bool(channel_rgb_plugin),
            str(band_mode),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _material_policy_signature(scene_path),
        ),
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
    if ambient_radiance > 0 and not _has_emitter(root):
        _inject_constant_emitter(root, ambient_radiance)
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=False)
    if active_lights and active_pass_kind:
        _append_base_active_lights(root, active_lights, base_pose, pass_kind=active_pass_kind, spectral=active_spectral)
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
    with_normals: bool = False,
) -> Path:
    stage_signature = (
        "aov",
        "measured_nested_substituted_v2",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
        ("normals",) if with_normals else (),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    # Channel order follows the aov string after the nested "img" integrator:
    #   [img(3), albedo(3), depth(1)(, sh_normal(3))]
    aovs = "ab:albedo,dd:depth,nn:sh_normal" if with_normals else "ab:albedo,dd:depth"

    def _build_template(root: ET.Element) -> None:
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        integrator.attrib["type"] = "aov"
        for child in list(integrator):
            integrator.remove(child)
        ET.SubElement(integrator, "string", {"name": "aovs", "value": aovs})
        ET.SubElement(integrator, "integrator", {"type": "direct", "name": "img"})
        # AOV branch only needs primary-ray hit geometry/depth; measured BSDFs
        # contribute nothing here yet cost the full hpbrdf/pbrdf table load.
        # Substitute them with diffuse so depth renders skip the heavy upload.
        _substitute_measured_bsdfs_with_diffuse(root)

    root = _scene_template(
        scene_path,
        branch_kind="aov",
        branch_signature=("measured_nested_substituted_v2", "normals" if with_normals else "base"),
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
    nested_max_depth: int | None = None,
    measured_scope: str = "analytic_only",
    max_measured_bsdfs: int = 3,
    active_lights: Sequence["ActiveLightSpec"] = (),
    base_pose: Any = None,
    stokes_reference_axis: Sequence[float] | None = None,
) -> Path:
    reference_axis: tuple[float, float, float] | None = None
    if stokes_reference_axis is not None:
        axis = np.asarray(stokes_reference_axis, dtype=np.float64).reshape(-1)
        if axis.shape != (3,) or not np.all(np.isfinite(axis)) or float(np.linalg.norm(axis)) == 0.0:
            raise ValueError("stokes_reference_axis must be a finite, non-zero 3-vector")
        reference_axis = tuple(float(value) for value in axis)
    stage_signature = (
        "stokes",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (
            nested_integrator_type,
            int(nested_max_depth or 0),
            int(samples_per_pass or 0),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _material_policy_signature(scene_path),
            reference_axis,
        ),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
        _active_lights_signature(active_lights, base_pose, "polar"),
    )
    if _should_reuse_staged_scene(out_scene, signature=stage_signature):
        return out_scene

    def _build_template(root: ET.Element) -> None:
        # The authored render_scene.xml this stages from never sets a sensor
        # id, so an unnamed sensor is exposed through an unstable
        # memory-address-keyed parameter (e.g. ``object_<addr>.to_world``,
        # not ``perspective.to_world`` as _scene_sensor_transform_parameter_key
        # otherwise assumes) whenever a resident stokes scene is driven purely
        # through mi.traverse(). Give it the same stable id _update_sensor
        # already stamps on other staged copies.
        sensor = root.find("./sensor")
        if sensor is not None:
            sensor.attrib.setdefault("id", "sensor")
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        integrator.attrib["type"] = "stokes"
        for child in list(integrator):
            integrator.remove(child)
        if samples_per_pass is not None and samples_per_pass > 0:
            ET.SubElement(integrator, "integer", {"name": "samples_per_pass", "value": str(samples_per_pass)})
        if reference_axis is not None:
            ET.SubElement(
                integrator,
                "vector",
                {
                    "name": "reference_axis",
                    "x": str(reference_axis[0]),
                    "y": str(reference_axis[1]),
                    "z": str(reference_axis[2]),
                },
            )
        nested = ET.SubElement(integrator, "integrator", {"type": nested_integrator_type})
        if nested_max_depth is not None and nested_max_depth > 0:
            ET.SubElement(nested, "integer", {"name": "max_depth", "value": str(nested_max_depth)})
        _apply_measured_scope_policy(
            root,
            source_scene=scene_path,
            measured_scope=measured_scope,
            max_measured_bsdfs=max_measured_bsdfs,
        )

    root = _scene_template(
        scene_path,
        branch_kind="stokes",
        branch_signature=(
            nested_integrator_type,
            int(nested_max_depth or 0),
            int(samples_per_pass or 0),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _material_policy_signature(scene_path),
            reference_axis,
        ),
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
    if active_lights:
        # Polar branch is spectral-polarized → single-band NIR spectrum allowed.
        _append_base_active_lights(root, active_lights, base_pose, pass_kind="polar", spectral=True)
    result = _write_scene(root, out_scene)
    _record_staged_scene_signature(result, signature=stage_signature)
    return result


def _stage_base_stokes_scene(
    scene_path: Path,
    *,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    assist_light: AssistLightSpec | None = None,
    camera_fov_deg: float | None = None,
    camera_width: int | None = None,
    camera_height: int | None = None,
    nested_integrator_type: str = "direct",
    nested_max_depth: int | None = None,
    measured_scope: str = "analytic_only",
    max_measured_bsdfs: int = 3,
    stokes_reference_axis: Sequence[float] | None = None,
) -> Path:
    """Stage a camera-free Stokes scene shared across polar viewpoints."""
    reference_axis: tuple[float, float, float] | None = None
    if stokes_reference_axis is not None:
        from .polar_heading_batch import _normalized_reference_axis
        reference_axis = _normalized_reference_axis(stokes_reference_axis)
    sig = (
        "base_stokes",
        _scene_cache_key(scene_path),
        (
            nested_integrator_type,
            int(nested_max_depth or 0),
            int(samples_per_pass or 0),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _DYNAMIC_SCENE_SENSOR_BINDING_STAGE_VERSION,
            _material_policy_signature(scene_path),
            reference_axis,
        ),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
        # A camera-aligned active polar scene keeps the source sensor and
        # emitter transforms live. They are updated through ``mi.traverse``
        # for every heading, so the resident scene is shared without baking a
        # pose-specific XML file per view.
        (
            round(float(camera_fov_deg), 6) if camera_fov_deg is not None else None,
            int(camera_width or 0),
            int(camera_height or 0),
        ),
        _texture_cache_signature(),
    )
    out_scene = _shared_base_scene_path(scene_path, sig)
    if out_scene.exists():
        _ensure_texture_audit(out_scene, fail_on_gt_profile=True)
        return out_scene

    def _build_template(root: ET.Element) -> None:
        # The authored render_scene.xml this stages from never sets a sensor
        # id, so an unnamed sensor is exposed through an unstable
        # memory-address-keyed parameter (e.g. ``object_<addr>.to_world``,
        # not ``perspective.to_world`` as _scene_sensor_transform_parameter_key
        # otherwise assumes) whenever a resident stokes scene is driven purely
        # through mi.traverse(). Give it the same stable id _update_sensor
        # already stamps on other staged copies.
        sensor = root.find("./sensor")
        if sensor is not None:
            sensor.attrib.setdefault("id", "sensor")
        integrator = root.find("./integrator")
        if integrator is None:
            raise RuntimeError("Scene has no integrator node")
        integrator.attrib["type"] = "stokes"
        for child in list(integrator):
            integrator.remove(child)
        if samples_per_pass is not None and samples_per_pass > 0:
            ET.SubElement(integrator, "integer", {"name": "samples_per_pass", "value": str(samples_per_pass)})
        if reference_axis is not None:
            ET.SubElement(
                integrator,
                "vector",
                {
                    "name": "reference_axis",
                    "x": str(reference_axis[0]),
                    "y": str(reference_axis[1]),
                    "z": str(reference_axis[2]),
                },
            )
        nested = ET.SubElement(integrator, "integrator", {"type": nested_integrator_type})
        if nested_max_depth is not None and nested_max_depth > 0:
            ET.SubElement(nested, "integer", {"name": "max_depth", "value": str(nested_max_depth)})
        _apply_measured_scope_policy(
            root,
            source_scene=scene_path,
            measured_scope=measured_scope,
            max_measured_bsdfs=max_measured_bsdfs,
        )

    root = _scene_template(
        scene_path,
        branch_kind="stokes",
        branch_signature=(
            nested_integrator_type,
            int(nested_max_depth or 0),
            int(samples_per_pass or 0),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _DYNAMIC_SCENE_SENSOR_BINDING_STAGE_VERSION,
            _material_policy_signature(scene_path),
            reference_axis,
        ),
        builder=_build_template,
    )
    _apply_scene_override(root, scene_override, mode="polar")
    if camera_fov_deg is not None and camera_width is not None and camera_height is not None:
        # This scene's own sensor is the one that renders (its pose is driven
        # through mi.traverse), so stamp the requesting camera's intrinsics on
        # it. Without this the render silently falls back to whatever film and
        # fov the authored scene XML happens to carry.
        _update_sensor(
            root,
            camera_to_world=np.eye(4, dtype=np.float32),
            fov_deg=float(camera_fov_deg),
            spp=1,
            width=int(camera_width),
            height=int(camera_height),
        )
    if assist_light is not None:
        if camera_fov_deg is None or camera_width is None or camera_height is None:
            raise ValueError("camera-aligned base Stokes staging requires fov and resolution")
        _append_camera_assist_light(
            root,
            np.eye(4, dtype=np.float32),
            assist_light,
            polarized=assist_light.polarized,
        )
    out_scene.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_scene.with_name(f"{out_scene.stem}.tmp.{os.getpid()}.{threading.get_ident()}.xml")
    _write_scene(root, tmp)
    try:
        os.replace(tmp, out_scene)
    except FileNotFoundError:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        if not out_scene.exists():
            raise
    # ``_write_scene`` initially targets a temporary filename.  Material-policy
    # injection can leave a texture introduced after that first cap pass (for
    # example a TextureCan structural map) at its source resolution.  Run the
    # cap against the published path before enforcing the audit so the worker
    # never rejects a scene solely because it has a late-added bitmap.
    _write_scene(root, out_scene)
    _write_texture_audit(root, out_scene=out_scene, fail_on_gt_profile=True)
    return out_scene


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
    ambient_radiance: float = 1.0,
) -> Path:
    stage_signature = (
        "diffuse_override",
        _scene_cache_key(scene_path),
        _camera_signature(camera_to_world, fov_deg=fov_deg, spp=spp, width=width, height=height),
        (int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _assist_light_signature(assist_light),
        round(float(ambient_radiance), 4),
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
            _remove_shape_bsdf_children(shape)

            if "glass" in obj_name:
                bsdf = ET.SubElement(shape, "bsdf", {"type": "roughdielectric"})
                ET.SubElement(bsdf, "float", {"name": "alpha", "value": f"{_MIN_ROUGHDIELECTRIC_ALPHA:.4f}"})
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
    if ambient_radiance > 0 and not _has_emitter(root):
        _inject_constant_emitter(root, ambient_radiance)
    if assist_light is not None:
        _append_camera_assist_light(root, camera_to_world, assist_light, polarized=False)

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


@dataclass
class _ViewpointSensorSpec:
    """Camera parameters passed to _render_scene() for base-scene rendering."""
    camera_to_world: np.ndarray
    fov_deg: float
    width: int
    height: int


def _shared_base_scene_path(source_scene: Path, base_sig: tuple) -> Path:
    sig_hash = hashlib.sha1(str(base_sig).encode()).hexdigest()[:16]
    return source_scene.parent / ".staged_mitsuba" / "base" / f"{sig_hash}.xml"


def _resident_stokes_heading_batch_scene_path(
    base_scene: Path,
    *,
    batch_size: int,
    width: int,
    height: int,
    fov_deg: float,
    stokes_reference_axis: Sequence[float],
) -> Path:
    """Return a stable K-slot batch XML path suitable for resident caching."""
    signature = (
        "resident_stokes_heading_batch_v4",
        _scene_cache_key(base_scene),
        int(batch_size),
        int(width),
        int(height),
        round(float(fov_deg), 6),
        tuple(round(float(value), 9) for value in stokes_reference_axis),
    )
    digest = hashlib.sha1(repr(signature).encode("utf-8")).hexdigest()[:16]
    return base_scene.parent.parent / "stokes_heading_batches" / f"{digest}.xml"


def _stage_resident_stokes_heading_batch_scene(
    base_scene: Path,
    *,
    batch_size: int,
    width: int,
    height: int,
    fov_deg: float,
    stokes_reference_axis: Sequence[float],
) -> Path:
    """Create the immutable K-slot scene whose sensors are updated at runtime."""
    from .polar_heading_batch import stage_resident_ambient_stokes_heading_batch

    output = _resident_stokes_heading_batch_scene_path(
        base_scene,
        batch_size=batch_size,
        width=width,
        height=height,
        fov_deg=fov_deg,
        stokes_reference_axis=stokes_reference_axis,
    )
    stage_resident_ambient_stokes_heading_batch(
        base_scene,
        output,
        batch_size=batch_size,
        width=width,
        height=height,
        fov_deg=fov_deg,
        stokes_reference_axis=stokes_reference_axis,
    )
    return output


def _stage_base_path_scene(
    scene_path: Path,
    *,
    max_depth: int,
    rr_depth: int,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    integrator_type: str = "path",
    ambient_radiance: float = 1.0,
    measured_wavelength_nm: int | None = None,
    channel_rgb_plugin: bool = False,
    band_mode: str = "rgb",
    measured_scope: str = "analytic_only",
    max_measured_bsdfs: int = 3,
) -> Path:
    """Stage a camera-free path-tracer scene shared across viewpoints.

    The scene has no sensor transform baked in; callers must pass a
    _ViewpointSensorSpec when calling _render_scene().
    """
    sig = (
        "base_path",
        _scene_cache_key(scene_path),
        (
            integrator_type,
            int(max_depth),
            int(rr_depth),
            int(samples_per_pass or 0),
            int(measured_wavelength_nm) if measured_wavelength_nm else 0,
            bool(channel_rgb_plugin),
            str(band_mode),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _material_policy_signature(scene_path),
        ),
        _scene_override_signature(scene_override),
        _texture_cache_signature(),
        round(float(ambient_radiance), 4),
    )
    out_scene = _shared_base_scene_path(scene_path, sig)
    if out_scene.exists():
        _ensure_texture_audit(out_scene, fail_on_gt_profile=True)
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
        if channel_rgb_plugin:
            _apply_measured_scope_policy(
                root,
                source_scene=scene_path,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )
            _stage_measured_bsdfs_for_rgb(root, band_mode=band_mode)
        elif measured_wavelength_nm is not None:
            _apply_measured_scope_policy(
                root,
                source_scene=scene_path,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )
            _ensure_measured_bsdf_wavelength(root, target_nm=int(measured_wavelength_nm))
        else:
            _apply_measured_scope_policy(
                root,
                source_scene=scene_path,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )

    root = _scene_template(
        scene_path,
        branch_kind="path",
        branch_signature=(
            integrator_type,
            int(max_depth),
            int(rr_depth),
            int(samples_per_pass or 0),
            int(measured_wavelength_nm) if measured_wavelength_nm else 0,
            bool(channel_rgb_plugin),
            str(band_mode),
            str(measured_scope),
            int(max_measured_bsdfs),
            _MEASURED_SCOPE_STAGE_VERSION,
            _material_policy_signature(scene_path),
        ),
        builder=_build_template,
    )
    _apply_scene_override(root, scene_override, mode="rgb")
    if ambient_radiance > 0 and not _has_emitter(root):
        _inject_constant_emitter(root, ambient_radiance)
    out_scene.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_scene.with_name(f"{out_scene.stem}.tmp.{os.getpid()}.{threading.get_ident()}.xml")
    _write_scene(root, tmp)
    try:
        os.replace(tmp, out_scene)
    except FileNotFoundError:
        # Another worker won the race and already published out_scene; clean up if needed.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        if not out_scene.exists():
            raise
    _write_texture_audit(root, out_scene=out_scene, fail_on_gt_profile=True)
    return out_scene


def _stage_base_diffuse_override_scene(
    scene_path: Path,
    *,
    max_depth: int,
    rr_depth: int,
    samples_per_pass: int | None,
    scene_override: SceneOverrideSpec | None = None,
    ambient_radiance: float = 1.0,
) -> Path:
    """Stage a camera-free diffuse-override scene shared across viewpoints."""
    sig = (
        "base_diffuse_override",
        _scene_cache_key(scene_path),
        (int(max_depth), int(rr_depth), int(samples_per_pass or 0)),
        _scene_override_signature(scene_override),
        _texture_cache_signature(),
        round(float(ambient_radiance), 4),
    )
    out_scene = _shared_base_scene_path(scene_path, sig)
    if out_scene.exists():
        _ensure_texture_audit(out_scene, fail_on_gt_profile=True)
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
            _remove_shape_bsdf_children(shape)

            if "glass" in obj_name:
                bsdf = ET.SubElement(shape, "bsdf", {"type": "roughdielectric"})
                ET.SubElement(bsdf, "float", {"name": "alpha", "value": f"{_MIN_ROUGHDIELECTRIC_ALPHA:.4f}"})
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
    _apply_scene_override(root, scene_override, mode="rgb")
    if ambient_radiance > 0 and not _has_emitter(root):
        _inject_constant_emitter(root, ambient_radiance)
    out_scene.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_scene.with_name(f"{out_scene.stem}.tmp.{os.getpid()}.{threading.get_ident()}.xml")
    _write_scene(root, tmp)
    try:
        os.replace(tmp, out_scene)
    except FileNotFoundError:
        # Another worker won the race and already published out_scene; clean up if needed.
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        if not out_scene.exists():
            raise
    _write_texture_audit(root, out_scene=out_scene, fail_on_gt_profile=True)
    return out_scene


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


def _load_resident_scene(
    scene_path: Path,
    *,
    variant: str,
    cache_limit: int | None = None,
) -> tuple[Any, float, bool]:
    mi = _import_mitsuba()
    from .mitsuba_runtime import ensure_mitsuba_variant

    variant = ensure_mitsuba_variant(variant)
    cache_key = _resident_scene_cache_key(scene_path, variant=variant)

    effective_cache_limit = max(1, int(cache_limit or _RESIDENT_SCENE_CACHE_LIMIT))
    evicted_scene: Any | None = None
    evicted_binding: Any | None = None
    evicted_frozen: Any | None = None
    with _SCENE_CACHE_LOCK:
        cached_scene = _RESIDENT_SCENE_CACHE.get(cache_key)
        if cached_scene is not None:
            _RESIDENT_SCENE_CACHE.move_to_end(cache_key)
            return cached_scene, 0.0, True
        # A K=2 tail and the normal K=4 strip use different fixed-slot XMLs.
        # On a 24 GiB card, loading the new scene *before* evicting the old
        # one transiently holds two complete OptiX texture scenes and crashes
        # in cuda_tex.cpp. Reserve the cache slot first, drop its ParamMap
        # sidecar too, and return allocator-only scratch before mi.load_file.
        while len(_RESIDENT_SCENE_CACHE) >= effective_cache_limit:
            evicted_key, evicted_scene = _RESIDENT_SCENE_CACHE.popitem(last=False)
            evicted_binding = _RESIDENT_BATCH_BINDINGS.pop(evicted_key, None)
            evicted_frozen = _RESIDENT_FROZEN_RENDER_CACHE.pop(evicted_key, None)

    if evicted_scene is not None or evicted_binding is not None or evicted_frozen is not None:
        try:
            import gc
            import drjit as dr  # type: ignore

            # Drop both Python references before asking Dr.Jit to release its
            # now-unreferenced device allocations.
            evicted_scene = None
            evicted_binding = None
            evicted_frozen = None
            gc.collect()
            dr.sync_thread()
            dr.flush_malloc_cache()
        except Exception:
            pass

    load_start = time.perf_counter()
    scene = mi.load_file(str(scene_path))
    load_s = time.perf_counter() - load_start

    with _SCENE_CACHE_LOCK:
        _RESIDENT_SCENE_CACHE[cache_key] = scene
        _RESIDENT_SCENE_CACHE.move_to_end(cache_key)
    return scene, load_s, False


def _clear_scene_caches() -> None:
    with _SCENE_CACHE_LOCK:
        _PARSED_SCENE_CACHE.clear()
        _SCENE_TEMPLATE_CACHE.clear()
        _RESIDENT_SCENE_CACHE.clear()
        _RESIDENT_BATCH_BINDINGS.clear()
        _RESIDENT_FROZEN_RENDER_CACHE.clear()
        _STAGED_SCENE_SIGNATURE_CACHE.clear()


def _get_or_build_frozen_render(cache_key: tuple[str, int, int, str], spp: int) -> Any:
    """Return (building once per resident scene + spp) a ``dr.freeze``-wrapped renderer.

    Caller must guarantee the target scene stays resident and is only mutated
    through ``mi.traverse()`` between calls -- see ``_drjit_freeze_enabled``.
    """
    mi = _import_mitsuba()
    import drjit as dr  # type: ignore

    with _SCENE_CACHE_LOCK:
        per_scene = _RESIDENT_FROZEN_RENDER_CACHE.get(cache_key)
        cached = per_scene.get(spp) if per_scene else None
    if cached is not None:
        return cached

    frozen = dr.freeze(
        lambda active_scene: mi.render(active_scene, spp=spp),
        backend=dr.JitBackend.CUDA,
    )
    with _SCENE_CACHE_LOCK:
        _RESIDENT_FROZEN_RENDER_CACHE.setdefault(cache_key, {})[spp] = frozen
    return frozen


def _scene_sensor_transform_parameter_key(scene: Any, params: Any) -> str:
    """Return the writable ``to_world`` parameter for the scene sensor.

    Historically generated Infinigen XMLs often leave the top-level sensor
    anonymous. Mitsuba exposes that parameter as ``perspective.to_world``;
    newer staged XMLs name it ``sensor.to_world``. Resolving both forms here
    lets pending durable tasks use their old staged scene while new stages use
    the stable name. Explicitly named sensors are supported through the sensor
    object's id as well.
    """
    parameter_names = {str(key) for key in params.keys()}
    for candidate in (
        "sensor.to_world",
        "perspective.to_world",
        "orthographic.to_world",
        "thinlens.to_world",
        "telecentric.to_world",
    ):
        if candidate in parameter_names:
            return candidate

    try:
        sensors = list(scene.sensors())
    except Exception:
        sensors = []
    for sensor in sensors:
        identifier = getattr(sensor, "id", None)
        try:
            identifier = identifier() if callable(identifier) else identifier
        except Exception:
            identifier = None
        if isinstance(identifier, str) and identifier:
            candidate = f"{identifier}.to_world"
            if candidate in parameter_names:
                return candidate

    available = [
        key for key in sorted(parameter_names)
        if key.endswith(".to_world") and ("sensor" in key.lower() or "perspective" in key.lower())
    ][:16]
    raise KeyError(
        "scene sensor transform is not exposed through a known parameter; "
        f"expected sensor/perspective to_world, available={available}"
    )


def _render_scene(
    scene_path: Path,
    *,
    variant: str,
    spp: int,
    on_loaded: Callable[[], None] | None = None,
    viewpoint: "_ViewpointSensorSpec | None" = None,
    scene_viewpoint: "_ViewpointSensorSpec | None" = None,
    dynamic_assist_light: AssistLightSpec | None = None,
    seed: int | None = None,
    scene_parameter_updater: Callable[[Any], None] | None = None,
    resident_cache_limit: int | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    mi = _import_mitsuba()
    start = time.perf_counter()
    scene, load_s, cache_hit = _load_resident_scene(
        scene_path, variant=variant, cache_limit=resident_cache_limit
    )
    # variant is now active; safe to call mi.ScalarTransform4f etc.

    sensor = None
    sensor_build_start = time.perf_counter()
    if viewpoint is not None:
        origin, target, up = camera_to_world_to_lookat(viewpoint.camera_to_world)
        sensor = mi.load_dict({
            "type": "perspective",
            "fov": float(viewpoint.fov_deg),
            "to_world": mi.ScalarTransform4f.look_at(
                origin=list(origin), target=list(target), up=list(up)
            ),
            "film": {
                "type": "hdrfilm",
                "width": int(viewpoint.width),
                "height": int(viewpoint.height),
            },
            "sampler": {
                "type": "independent",
                "sample_count": 1,
            },
        })
    if scene_viewpoint is not None:
        # Keep the scene's own sensor active instead of constructing a
        # temporary sensor. This is essential for the legacy OptiX-7 Stokes
        # plugin, whose reference frame is the scene sensor. It also lets a
        # camera-aligned active emitter move with the same pose while retaining
        # one resident scene across all headings.
        params = mi.traverse(scene)

        def _assign_transform(key: str, transform: Any) -> None:
            """Assign an active-variant transform without relying on pybind casts."""
            expected_type = type(params[key])
            if not isinstance(transform, expected_type):
                transform = expected_type(transform)
            params[key] = transform

        origin, target, up = camera_to_world_to_lookat(scene_viewpoint.camera_to_world)
        _assign_transform(
            _scene_sensor_transform_parameter_key(scene, params),
            mi.ScalarTransform4f.look_at(
                origin=list(origin), target=list(target), up=list(up)
            ),
        )
        if dynamic_assist_light is not None:
            light_matrix = _camera_aligned_rectangle_matrix(
                scene_viewpoint.camera_to_world,
                distance_m=dynamic_assist_light.distance_m,
                size_world=dynamic_assist_light.size_world,
            )
            _assign_transform("camera_assist_light.to_world", mi.ScalarTransform4f(light_matrix))
            polarizer_matrix = _camera_aligned_rectangle_matrix(
                scene_viewpoint.camera_to_world,
                distance_m=dynamic_assist_light.distance_m + 0.01,
                size_world=dynamic_assist_light.size_world,
                roll_deg=dynamic_assist_light.polarizer_angle_deg,
            )
            _assign_transform("camera_assist_polarizer.to_world", mi.ScalarTransform4f(polarizer_matrix))
        params.update()
    if scene_parameter_updater is not None:
        scene_parameter_updater(scene)
    sensor_build_s = time.perf_counter() - sensor_build_start

    if on_loaded is not None:
        on_loaded()

    sampler_spp: int | None = None
    if sensor is not None:
        try:
            sampler_spp = int(sensor.sampler().sample_count())
        except Exception:
            sampler_spp = None

    # A resident K-heading Stokes scene deliberately retains its full OptiX
    # scene (geometry, textures, and acceleration structures) in VRAM.  The
    # frame-local Dr.Jit allocator cache must *not* accumulate between strips:
    # on a 24 GiB card the cached scratch blocks can otherwise make the next
    # ``cuda_tex`` allocation fail even though the retained scene is healthy.
    #
    # Do this before the next render as well as after the previous image has
    # been copied.  A worker can have survived an earlier job with cached
    # allocations before it receives its first resident strip.
    resident_allocator_prepare_s = 0.0
    if resident_cache_limit is not None:
        prepare_start = time.perf_counter()
        try:
            import gc
            import drjit as dr  # type: ignore

            gc.collect()
            # Pending kernels can still own temporary allocations.  Synchronize
            # before flushing so the allocator can actually return those blocks.
            dr.sync_thread()
            dr.flush_malloc_cache()
        except Exception:
            # This is memory hygiene only; minimal test doubles and Dr.Jit
            # builds without allocator control remain functionally correct.
            pass
        resident_allocator_prepare_s = time.perf_counter() - prepare_start

    render_start = time.perf_counter()
    render_kwargs: dict[str, Any] = {"spp": spp}
    # Explicit independent seeds are essential for progressive Monte-Carlo
    # estimates.  Reusing Mitsuba's default seed would compare the same sample
    # sequence with itself and incorrectly declare every frame converged.
    if seed is not None:
        render_kwargs["seed"] = int(seed)
    frozen_stage: str | None = None
    frozen_render_active = False
    # Freezing only pays off, and only stays safe, on the resident hot paths
    # that keep the same scene object and mutate it purely through
    # mi.traverse() (scene_viewpoint above, and the heading-batch slot update
    # in _render_resident_stokes_heading_batch_scene) -- never on a fresh
    # per-call sensor object (the ``viewpoint`` branch) or a varying seed,
    # either of which would defeat kernel-graph reuse. See
    # _drjit_freeze_enabled for the OptiX 8 vs. OptiX 7 opt-in split.
    if (
        sensor is None
        and seed is None
        # ``resident_cache_limit`` only narrows the eviction ceiling for the
        # camera-aligned active-light path -- it is None for the (equally
        # resident, still traverse-only-mutated) passive K=1 ambient polar
        # path, which would otherwise be silently excluded from freezing.
        # The real signal is which updater actually touches the scene:
        # scene_viewpoint (camera-aligned polar) or scene_parameter_updater
        # (heading-batch slots) both only call mi.traverse() on the existing
        # scene object; the one-shot non-resident temp batch scene at the
        # bottom of render_ambient_stokes_heading_batch() passes neither and
        # is correctly excluded here.
        and (scene_viewpoint is not None or scene_parameter_updater is not None)
        and variant.startswith("cuda_")
        and _drjit_freeze_enabled()
    ):
        scene_cache_key: tuple[str, int, int, str] | None = None
        try:
            # ``variant`` is already the concrete resolved variant at this
            # call layer (every caller resolves "auto" before reaching
            # _render_scene), so it keys the same resident scene cache entry
            # _load_resident_scene just populated/reused above.
            scene_cache_key = _resident_scene_cache_key(scene_path, variant=variant)
            if not cache_hit:
                # ``scene_cache_key`` is (path, mtime, size, variant): stable
                # across a scene *file* being evicted and reloaded, even
                # though eviction/reload produces a brand-new live mi.Scene
                # object. A frozen callable recorded against the old object
                # is invalid for the new one -- reusing it silently corrupts
                # state until a later call fails deep inside dr.freeze's
                # record(). Drop any stale entry so this call rebuilds fresh
                # against the object _load_resident_scene just returned.
                with _SCENE_CACHE_LOCK:
                    _RESIDENT_FROZEN_RENDER_CACHE.pop(scene_cache_key, None)
            frozen_render = _get_or_build_frozen_render(scene_cache_key, spp)
            previous_recordings = int(frozen_render.n_recordings)
            image_tensor = frozen_render(scene)
            frozen_stage = "record" if int(frozen_render.n_recordings) > previous_recordings else "replay"
            frozen_render_active = True
            # Log every *record*, not just stage transitions: a scene stuck
            # re-recording each frame otherwise looks identical to one that
            # recorded once, which is the difference between freeze paying off
            # and freeze costing a full trace per frame.
            if frozen_stage == "record" or _FROZEN_RENDER_LOG_STATE.get(scene_cache_key) != frozen_stage:
                _FROZEN_RENDER_LOG_STATE[scene_cache_key] = frozen_stage
                print(
                    f"[drjit-freeze] {scene_path.name} variant={variant} spp={spp} "
                    f"stage={frozen_stage} n_recordings={int(frozen_render.n_recordings)}",
                    file=sys.stderr, flush=True,
                )
        except Exception as exc:
            frozen_render_active = False
            # A frozen callable that errors once is not safe to keep calling:
            # dr.freeze's internal recording state is left inconsistent, so a
            # future call would pay a doomed record attempt every time on top
            # of the classic mi.render() fallback -- silently double-costing
            # every remaining frame against this scene. Drop it so the next
            # call gets a clean dr.freeze() wrapper instead of retrying the
            # same broken one forever.
            if scene_cache_key is not None:
                with _SCENE_CACHE_LOCK:
                    _RESIDENT_FROZEN_RENDER_CACHE.pop(scene_cache_key, None)
            if _FROZEN_RENDER_LOG_STATE.get(scene_cache_key) != "failed":
                _FROZEN_RENDER_LOG_STATE[scene_cache_key] = "failed"
                print(
                    f"[drjit-freeze] {scene_path.name} variant={variant} spp={spp} "
                    f"FAILED, falling back to classic mi.render(): {exc!r}",
                    file=sys.stderr, flush=True,
                )
    if not frozen_render_active:
        if sensor is not None:
            image_tensor = mi.render(scene, sensor=sensor, **render_kwargs)
        else:
            image_tensor = mi.render(scene, **render_kwargs)
    # ``mi.render`` can return a lazily scheduled Dr.Jit tensor.  Force
    # completion before timing it; without this a later NumPy conversion or
    # product write can accidentally absorb the CUDA work.
    try:
        import drjit as dr  # type: ignore
        dr.eval(image_tensor)
        dr.sync_thread()
    except Exception:
        # NumPy conversion below remains a mandatory materialization fallback
        # for minimal/non-Dr.Jit test environments.
        pass
    image = np.array(image_tensor, dtype=np.float32)
    # A resident K-heading Stokes scene deliberately retains its full OptiX
    # scene (geometry, textures, and acceleration structures) in VRAM.  The
    # rendered film tensor is different: once copied into ``image`` it is
    # dead, but Dr.Jit's allocator may otherwise retain its temporary CUDA
    # blocks between strips.  On a 24 GiB card this can turn a healthy ~22 GiB
    # resident scene into a later ``cuda_tex.cpp`` OOM.  Keep the scene cache
    # intact while releasing only unused allocator-cache blocks on the
    # explicit resident path.
    resident_allocator_flush_s = 0.0
    if resident_cache_limit is not None:
        flush_start = time.perf_counter()
        try:
            import gc
            import drjit as dr  # type: ignore

            dr.sync_thread()
            del image_tensor
            gc.collect()
            dr.flush_malloc_cache()
        except Exception:
            # This is a memory-hygiene optimization.  Rendering remains
            # correct on minimal test doubles and on Dr.Jit builds that do
            # not expose allocator-cache control.
            pass
        resident_allocator_flush_s = time.perf_counter() - flush_start
    render_s = time.perf_counter() - render_start
    total_s = time.perf_counter() - start
    return image, {
        "variant": variant,
        "load_scene_s": load_s,
        "scene_cache_hit": cache_hit,
        "sensor_build_s": sensor_build_s,
        "requested_spp": int(spp),
        "sensor_sampler_spp": sampler_spp,
        "render_s": render_s,
        "resident_allocator_prepare_s": resident_allocator_prepare_s,
        "resident_allocator_flush_s": resident_allocator_flush_s,
        "drjit_freeze_active": frozen_render_active,
        "drjit_freeze_stage": frozen_stage,
        "total_s": total_s,
    }


def _render_resident_stokes_heading_batch_scene(
    scene_path: Path,
    *,
    camera_to_worlds: Sequence[np.ndarray],
    variant: str,
    spp: int,
    on_loaded: Callable[[], None] | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    """Render a stable K-slot Stokes scene after updating its sensor poses.

    The batch XML's path and contents stay fixed.  Consequently
    :func:`_load_resident_scene` returns the same Mitsuba scene object after
    its initial load, retaining geometry, textures and OptiX acceleration data
    in the worker's VRAM.
    """
    from .polar_heading_batch import normalize_camera_to_world

    # RenderRequest persists camera matrices in the historical column-major
    # flat layout. Resident slot updates consume ordinary row-major matrices;
    # normalize here as a second guard even when callers have already done it.
    poses = [normalize_camera_to_world(item).astype(np.float32) for item in camera_to_worlds]
    from .polar_heading_batch import MIN_STOKES_HEADING_BATCH_SLOTS, max_stokes_heading_batch_slots
    if not MIN_STOKES_HEADING_BATCH_SLOTS <= len(poses) <= max_stokes_heading_batch_slots():
        raise ValueError(
            f"resident Stokes heading batches require {MIN_STOKES_HEADING_BATCH_SLOTS} to "
            f"{max_stokes_heading_batch_slots()} poses, got {len(poses)}"
        )

    slot_binding_cache_hit = False

    def _update_sensor_slots(scene: Any) -> None:
        nonlocal slot_binding_cache_hit
        mi = _import_mitsuba()
        cache_key = _resident_scene_cache_key(scene_path, variant=variant)
        # Re-traverse on every strip and cache only the resolved *key names*.
        #
        # Caching the ParameterMap itself was the intended optimisation, but it
        # is unsafe once dr.freeze replays this scene: a frozen replay swaps the
        # scene's underlying JIT variables, so a ParameterMap captured before
        # the replay addresses variables that no longer belong to the live
        # scene. Writing slot transforms through it corrupted the CUDA context
        # and killed the worker with CUDA_ERROR_ILLEGAL_ADDRESS. A fresh
        # mi.traverse() is negligible next to a 1024spp strip render.
        params = mi.traverse(scene)
        with _SCENE_CACHE_LOCK:
            cached_keys = _RESIDENT_BATCH_BINDINGS.get(cache_key)
        if cached_keys is not None and len(cached_keys) == len(poses):
            slot_binding_cache_hit = True
            keys = list(cached_keys)
        else:
            parameter_names = [str(key) for key in params.keys()]
            keys: list[str] = []
            missing: list[str] = []
            for index in range(len(poses)):
                # Upstream BatchSensor::traverse() keys children by their id
                # ("heading_NN" as staged here, "sensorN" when unnamed). The
                # ".slot_N" form is what this project's older patched 3.7.x
                # renderer exposed; accept both so one renderer build can be
                # swapped for the other without restaging every batch scene.
                suffixes = (
                    f".heading_{index:02d}.to_world",
                    f".slot_{index}.to_world",
                    f".sensor{index}.to_world",
                )
                matches = [
                    key for key in parameter_names
                    if any(key.endswith(suffix) for suffix in suffixes)
                ]
                if len(matches) == 1:
                    keys.append(matches[0])
                else:
                    missing.append(suffixes[0])
            if missing:
                available = [
                    key for key in parameter_names
                    if "sensor" in key.lower() or "slot_" in key.lower() or "heading_" in key.lower()
                ][:32]
                raise RuntimeError(
                    "resident Stokes batch scene does not expose the expected sensor transforms: "
                    f"missing={missing}; available={available}"
                )
            with _SCENE_CACHE_LOCK:
                _RESIDENT_BATCH_BINDINGS[cache_key] = tuple(keys)
        for key, pose in zip(keys, poses):
            origin, target, up = camera_to_world_to_lookat(pose)
            transform = mi.ScalarTransform4f.look_at(
                origin=list(origin), target=list(target), up=list(up),
            )
            # Batch child transforms are exposed through the parent sensor and
            # Mitsuba reports them as the active variant's ``Transform4f``.
            # A scalar look-at transform is usually implicitly castable, but
            # the OptiX7 CUDA-AD binding rejects that conversion for some
            # XML-loaded batch scenes. Construct the exact parameter class so
            # the resident hot path is independent of that pybind overload.
            expected_transform_type = type(params[key])
            if not isinstance(transform, expected_transform_type):
                transform = expected_transform_type(transform)
            params[key] = transform
        params.update()

    image, timing = _render_scene(
        scene_path,
        variant=variant,
        spp=spp,
        on_loaded=on_loaded,
        scene_parameter_updater=_update_sensor_slots,
        # A polar worker has scene affinity: retaining a second full OptiX
        # scene buys nothing but makes its VRAM ceiling unpredictable.
        resident_cache_limit=_POLAR_RESIDENT_SCENE_CACHE_LIMIT,
    )
    timing["resident_slot_binding_cache_hit"] = slot_binding_cache_hit
    timing["resident_scene_cache_limit"] = _POLAR_RESIDENT_SCENE_CACHE_LIMIT
    return image, timing


def _polar_adaptive_noise_score(reference: np.ndarray, estimate: np.ndarray) -> float:
    """Return a robust relative Stokes disagreement score for two equal-SPP estimates.

    The comparison is normalized by S0 luminance, never by DoLP/AoLP.  Those
    quantities are non-linear (and AoLP wraps), therefore estimating their
    error directly would let a noisy dark pixel make a sound Stokes estimate
    look unconverged.  The score is intentionally a high percentile over
    illuminated pixels: a single caustic/firefly must not force all frames to
    the maximum budget, but glass/reflection edges still receive extra samples.
    """
    if reference.shape != estimate.shape or reference.ndim != 3 or reference.shape[-1] < 3:
        return float("inf")
    ref = np.nan_to_num(np.asarray(reference, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    est = np.nan_to_num(np.asarray(estimate, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    mean = 0.5 * (ref + est)
    # In rgb_stokes_12, S0 is the first RGB triplet.  Keep the fallback useful
    # for a scalar/spectral carrier used by direct library callers.
    s0 = mean[..., :3]
    luminance = np.maximum(
        0.2126 * np.abs(s0[..., 0]) + 0.7152 * np.abs(s0[..., 1]) + 0.0722 * np.abs(s0[..., 2]),
        0.0,
    )
    reference_scale = float(np.quantile(luminance, 0.95)) if luminance.size else 0.0
    floor = max(reference_scale * 0.02, 1e-6)
    valid = luminance >= floor
    if not np.any(valid):
        return float("inf")
    # S1/S2/S3 are bounded by the total intensity for a physical Stokes vector,
    # so S0 luminance is a common stable normalizer across all twelve channels.
    delta = np.max(np.abs(ref - est), axis=-1)
    relative = delta[valid] / np.maximum(luminance[valid], floor)
    return float(np.quantile(relative, 0.95)) if relative.size else float("inf")


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


def stokes_rgb_component_preview(component: np.ndarray, *, component_name: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Build a compact RGB visualization for one Stokes component.

    ``S0`` is radiance-like and is displayed with the same tone mapping as an
    RGB render.  ``S1``--``S3`` are signed quantities: each of their RGB
    channels is retained, zero is neutral mid-grey, and a symmetric percentile
    scale makes positive/negative values visible without discarding colour.
    This is deliberately different from the existing luminance BWR products.
    """
    safe = np.where(np.isfinite(component), component, 0.0).astype(np.float32)
    if component_name == "s0":
        preview, summary = _rgb_preview_array(safe, percentile=0.992)
        summary.update({"kind": "stokes_rgb", "component": "S0", "signed": False})
        return preview, summary
    magnitude = np.abs(safe[np.isfinite(safe)])
    scale = float(np.quantile(magnitude, 0.99)) if magnitude.size else 1.0
    scale = max(scale, 1e-6)
    preview = np.clip(0.5 + 0.5 * (safe / scale), 0.0, 1.0).astype(np.float32)
    return preview, {
        "kind": "stokes_rgb",
        "component": component_name.upper(),
        "signed": True,
        "zero_color": "#808080",
        "symmetric_scale_abs_p99": scale,
    }


def save_unit_rgb_preview(arr: np.ndarray, path: Path) -> dict[str, Any]:
    safe_arr = np.where(np.isfinite(arr), arr, 0.0)
    preview = srgb_encode(np.clip(safe_arr, 0.0, 1.0))
    _save_preview_image(preview, path)
    return {"encoding": "srgb", "input_range": [0.0, 1.0]}


def read_exr_rgb(path: str | Path) -> np.ndarray:
    """Read an HDR EXR into an (H, W, 3) float32 array (linear radiance).

    Tries ``imageio`` (already a dependency for texture handling) and falls back
    to ``OpenEXR``/``Imath`` (used elsewhere in this package). Raises if neither
    backend can read the file.
    """
    path = Path(path)
    last_err: Exception | None = None
    try:
        import imageio.v3 as iio

        arr = np.asarray(iio.imread(str(path)), dtype=np.float32)
        if arr.ndim == 2:
            arr = np.repeat(arr[:, :, None], 3, axis=2)
        elif arr.shape[2] > 3:
            arr = arr[:, :, :3]
        return np.ascontiguousarray(arr, dtype=np.float32)
    except Exception as exc:  # noqa: BLE001 - fall through to OpenEXR
        last_err = exc
    try:
        import OpenEXR
        import Imath

        exr = OpenEXR.InputFile(str(path))
        dw = exr.header()["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        chans = exr.channels(["R", "G", "B"], pt)
        rgb = [np.frombuffer(c, dtype=np.float32).reshape(h, w) for c in chans]
        return np.ascontiguousarray(np.stack(rgb, axis=-1), dtype=np.float32)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to read EXR {path}: imageio={last_err}; OpenEXR={exc}") from exc


def luminance(arr: np.ndarray) -> np.ndarray:
    """Rec.709 luminance of an (..., 3) linear-RGB array."""
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim >= 1 and a.shape[-1] >= 3:
        return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    return a.reshape(a.shape[:-1]) if a.shape[-1] == 1 else a


def _tonemap_reinhard(arr: np.ndarray, *, exposure: float, white: float) -> np.ndarray:
    """Extended Reinhard tonemap (per-channel) → sRGB-encoded [0, 1] float.

    ``y = x (1 + x / white**2) / (1 + x)`` with ``x = arr * exposure`` rolls off
    highlights toward 1.0 (a light source in view no longer forces the rest of
    the frame dark) while ``white`` sets the radiance that maps to ~1.0.
    """
    # Inpaint NaN/Inf (low-spp "black square" pixels) instead of zeroing them.
    x = _sanitize_radiance(arr) * float(exposure)
    w = max(float(white), 1e-6)
    y = x * (1.0 + x / (w * w)) / (1.0 + x)
    return np.clip(srgb_encode(y), 0.0, 1.0).astype(np.float32)


def compute_global_tone_params(
    luminance_samples: Sequence[np.ndarray] | np.ndarray,
    *,
    exposure_percentile: float = 0.90,
    white_percentile: float = 0.999,
) -> dict[str, float]:
    """Derive a scene-global (exposure, white) from sampled positive luminance.

    ``exposure`` is set so the ``exposure_percentile`` of the radiance population
    maps to ~1.0 before roll-off; ``white`` places the ``white_percentile`` (the
    brightest non-outlier radiance) at the roll-off knee. Reused by the export
    pipeline and the in-place retonemap migration.
    """
    if isinstance(luminance_samples, np.ndarray):
        pool = luminance_samples.reshape(-1)
    else:
        flat = [np.asarray(s, dtype=np.float32).reshape(-1) for s in luminance_samples if s is not None]
        pool = np.concatenate(flat) if flat else np.zeros(0, dtype=np.float32)
    pool = pool[np.isfinite(pool)]
    pool = pool[pool > 0.0]
    if pool.size == 0:
        return {"tone_exposure": 1.0, "tone_white": _TONE_WHITE_DEFAULT}
    key = float(np.quantile(pool, exposure_percentile))
    key = max(key, 1e-6)
    exposure = 1.0 / key
    hi = float(np.quantile(pool, white_percentile)) * exposure
    white = max(hi, 1.0)
    return {"tone_exposure": exposure, "tone_white": white}


def save_rgb_radiance_preview(
    arr: np.ndarray,
    path: Path,
    *,
    exposure: float,
    white: float,
) -> dict[str, float]:
    """Tonemap a linear-HDR radiance image (extended Reinhard) and save as PNG."""
    preview = _tonemap_reinhard(arr, exposure=exposure, white=white)
    _save_preview_image(preview, path)
    return {
        "tone_operator": "reinhard_ext",
        "tone_exposure": float(exposure),
        "tone_white": float(white),
    }


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


def _build_sensor_depth(
    base_depth: np.ndarray,
    *,
    quantization_m: float,
    noise_std_m: float,
    dropout_probability: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply explicit depth-sensor quantization/noise/dropout to geometric depth."""
    depth = np.asarray(base_depth, dtype=np.float32).copy()
    valid = np.isfinite(depth) & (depth > 0.0)
    rng = np.random.default_rng(int(seed))
    if noise_std_m > 0.0:
        depth[valid] += rng.normal(0.0, float(noise_std_m), int(np.count_nonzero(valid))).astype(np.float32)
    if quantization_m > 0.0:
        depth[valid] = np.rint(depth[valid] / float(quantization_m)) * float(quantization_m)
    if dropout_probability > 0.0:
        valid &= rng.random(valid.shape) >= float(dropout_probability)
    valid &= np.isfinite(depth) & (depth > 0.0)
    depth[~valid] = np.nan
    confidence = np.zeros(depth.shape, dtype=np.float32)
    confidence[valid] = 1.0
    return depth, valid, confidence


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

    # The lossless public GT contract is explicitly float32, regardless of the
    # renderer buffer's native precision.  Each Stokes component remains RGB.
    rgb = np.asarray(image[:, :, 0:3], dtype=np.float32)
    s0 = np.asarray(image[:, :, offset + 0:offset + 3], dtype=np.float32)
    s1 = np.asarray(image[:, :, offset + 3:offset + 6], dtype=np.float32)
    s2 = np.asarray(image[:, :, offset + 6:offset + 9], dtype=np.float32)
    s3 = np.asarray(image[:, :, offset + 9:offset + 12], dtype=np.float32)
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
    *,
    visualization_policy: str = "full_v1",
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if visualization_policy not in {"full_v1", "core_preview_v1", "raw_stokes_aolp_v1"}:
        raise ValueError(
            "polar_visualization_policy must be 'full_v1', 'core_preview_v1', or 'raw_stokes_aolp_v1'"
        )
    write_started = time.perf_counter()
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
    # Normalized Stokes (S1/S0, S2/S0) — physically standard, range [-1, 1], so a
    # fixed colorbar scale of 1.0 is comparable across frames (unlike the absolute
    # s1_l/s2_l fields whose scale is per-frame percentile-based).
    s0_safe = np.maximum(s0_l, 1e-8)
    s1_n = np.clip(np.where(np.isfinite(s1_l), s1_l, 0.0) / s0_safe, -1.0, 1.0)
    s2_n = np.clip(np.where(np.isfinite(s2_l), s2_l, 0.0) / s0_safe, -1.0, 1.0)
    context_scale = max(float(np.quantile(finite_s0, 0.995)) if finite_s0.size else 1.0, 1e-6)
    context = np.clip(np.sqrt(np.clip(s0_l, 0.0, None) / context_scale), 0.0, 1.0)
    context_rgb = np.repeat((0.12 + 0.88 * context)[:, :, None], 3, axis=2).astype(np.float32)
    context_rgb[~finite_mask] = 0.18
    invalid_pixel_count = int(np.count_nonzero(~finite_mask))
    finite_ratio = float(np.mean(finite_mask))

    stokes_npz = out_dir / "stokes_data.npz"
    stokes_npz_write_s, stokes_npz_bytes = _save_minimal_stokes_npz(
        stokes_npz, s0=s0, s1=s1, s2=s2, s3=s3
    )

    def bwr_map(field: np.ndarray, scale: float) -> np.ndarray:
        safe_field = np.where(np.isfinite(field), field, 0.0)
        norm = np.clip(safe_field / scale, -1.0, 1.0)
        pos = np.clip(norm, 0.0, 1.0)
        neg = np.clip(-norm, 0.0, 1.0)
        # Pure diverging red/white/blue: white at 0, saturated red at +scale,
        # saturated blue at -scale. No S0-intensity background is blended in, so the
        # sign/magnitude of the Stokes field reads directly against a white ground.
        overlay = np.ones(field.shape + (3,), dtype=np.float32)
        overlay[..., 1] = 1.0 - np.maximum(pos, neg)
        overlay[..., 0] = 1.0 - neg
        overlay[..., 2] = 1.0 - pos
        white_bg = np.ones(field.shape + (3,), dtype=np.float32)
        return _fill_invalid_preview_pixels(overlay, valid_mask=finite_mask, fallback_rgb=white_bg)

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
        # Full DoLP gating (no floor): hue opacity == sqrt(DoLP), so unpolarized
        # regions fall back to the grayscale S0 context with zero AoLP hue leak
        # (previously a 0.20 floor let noisy angle bleed through at DoLP~0).
        strength = np.where(mask, np.sqrt(np.clip(dop, 0.0, 1.0)), 0.0)[:, :, None]
        rgb_out = context_rgb * (1.0 - strength) + overlay * strength
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

    # Gallery inspection needs the actual RGB-channel Stokes fields, rather
    # than the older luminance-composited signed preview.  These are generated
    # on demand from the immutable NPZ under ``core_preview_v1`` and therefore
    # do not multiply dataset storage.  Each BWR image declares its own p99
    # scale in the embedded colorbar; it is a raw Sᵢ channel diagnostic, not
    # the normalized Sᵢ/S0 product below.
    channel_stokes_bwr_keys: set[str] = set()
    component_channels = (("s1", s1), ("s2", s2), ("s3", s3))
    rgb_channels = (("r", 0), ("g", 1), ("b", 2))

    outputs: dict[str, str] = {"stokes_npz": str(stokes_npz)}
    # Keep an immediately browsable RGB representation for every Stokes
    # component.  The immutable gallery also synthesizes these from legacy
    # NPZs, so this only affects new renders.
    preview_started = time.perf_counter()
    if visualization_policy == "full_v1":
        for component_name, component in (("s0", s0), ("s1", s1), ("s2", s2), ("s3", s3)):
            component_path = out_dir / f"{component_name}_rgb_preview.png"
            component_preview, _ = stokes_rgb_component_preview(component, component_name=component_name)
            _save_preview_image(component_preview, component_path)
            outputs[f"{component_name}_rgb_preview"] = str(component_path)
    # The compact policy deliberately retains one normal RGB view.  It is the
    # only image needed for quick visual QA beside AoLP, while all of the
    # per-Stokes-component and DoLP diagnostics stay derivable from the NPZ.
    if (
        visualization_policy == "raw_stokes_aolp_v1"
        or "polar_rgb_preview" in requested_modalities
    ):
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
    if visualization_policy == "full_v1" and "s1" in requested_modalities:
        bar, ticks = bwr_bar(s1_scale, s1_l.shape[0])
        s1_path = out_dir / "s1_bwr_colorbar.png"
        s1_rgb = _despeckle_dark_preview_pixels(bwr_map(s1_l, s1_scale), iterations=3)
        append_colorbar(s1_rgb, bar, ticks, "S1", s1_path, title_mode="signed")
        outputs["s1"] = str(s1_path)
    if visualization_policy == "full_v1" and "s2" in requested_modalities:
        bar, ticks = bwr_bar(s2_scale, s2_l.shape[0])
        s2_path = out_dir / "s2_bwr_colorbar.png"
        s2_rgb = _despeckle_dark_preview_pixels(bwr_map(s2_l, s2_scale), iterations=3)
        append_colorbar(s2_rgb, bar, ticks, "S2", s2_path, title_mode="signed")
        outputs["s2"] = str(s2_path)
    for component_name, component in component_channels:
        for channel_name, channel_index in rgb_channels:
            key = f"stokes_{component_name}_{channel_name}_bwr"
            channel_stokes_bwr_keys.add(key)
            if visualization_policy != "full_v1" or key not in requested_modalities:
                continue
            field = component[:, :, channel_index]
            finite = np.isfinite(field) & mask
            scale = max(
                float(np.quantile(np.abs(field[finite]), 0.99)) if np.any(finite) else 1.0,
                1e-6,
            )
            bar, ticks = bwr_bar(scale, field.shape[0])
            path = out_dir / f"{component_name}_{channel_name}_bwr_colorbar.png"
            preview = _despeckle_dark_preview_pixels(bwr_map(field, scale), iterations=3)
            append_colorbar(
                preview, bar, ticks, f"{component_name.upper()} · {channel_name.upper()}", path,
                title_mode="signed",
            )
            outputs[key] = str(path)
    if visualization_policy == "full_v1" and "dop" in requested_modalities:
        bar, ticks = dop_bar(dop.shape[0])
        dop_path = out_dir / "dop_red_black_colorbar.png"
        dop_rgb = _despeckle_dark_preview_pixels(dop_map(dop), iterations=3)
        append_colorbar(dop_rgb, bar, ticks, "DoP", dop_path, title_mode="range")
        outputs["dop"] = str(dop_path)
    if visualization_policy in {"full_v1", "raw_stokes_aolp_v1"} and (
        "aolp" in requested_modalities or visualization_policy == "raw_stokes_aolp_v1"
    ):
        bar, ticks = aolp_bar(aolp_deg.shape[0])
        aolp_path = out_dir / "aolp_rainbow_colorbar.png"
        aolp_rgb = _despeckle_dark_preview_pixels(aolp_map(aolp_deg), iterations=3)
        append_colorbar(aolp_rgb, bar, ticks, "AoLP", aolp_path, title_mode="angle")
        outputs["aolp"] = str(aolp_path)
    if visualization_policy == "full_v1" and "s1_over_s0" in requested_modalities:
        bar, ticks = bwr_bar(1.0, s1_n.shape[0])
        s1n_path = out_dir / "s1_over_s0_bwr_colorbar.png"
        s1n_rgb = _despeckle_dark_preview_pixels(bwr_map(s1_n, 1.0), iterations=3)
        append_colorbar(s1n_rgb, bar, ticks, "S1/S0", s1n_path, title_mode="signed")
        outputs["s1_over_s0"] = str(s1n_path)
    if visualization_policy == "full_v1" and "s2_over_s0" in requested_modalities:
        bar, ticks = bwr_bar(1.0, s2_n.shape[0])
        s2n_path = out_dir / "s2_over_s0_bwr_colorbar.png"
        s2n_rgb = _despeckle_dark_preview_pixels(bwr_map(s2_n, 1.0), iterations=3)
        append_colorbar(s2n_rgb, bar, ticks, "S2/S0", s2n_path, title_mode="signed")
        outputs["s2_over_s0"] = str(s2n_path)

    preview_write_s = time.perf_counter() - preview_started
    derived_on_demand = sorted(
        {"rgb_preview", "s0_rgb_preview", "s1_rgb_preview", "s2_rgb_preview", "s3_rgb_preview"}
        | channel_stokes_bwr_keys
        | ({"s1", "s2", "dop", "aolp", "s1_over_s0", "s2_over_s0"}
           if visualization_policy in {"core_preview_v1", "raw_stokes_aolp_v1"} else set())
        - set(outputs)
    )
    summary = {
        "s1_scale_abs_p995": s1_scale,
        "s2_scale_abs_p995": s2_scale,
        "s1_scale_abs_p99": s1_scale,
        "s2_scale_abs_p99": s2_scale,
        "invalid_pixel_count": invalid_pixel_count,
        "finite_ratio": finite_ratio,
        "stokes_luminance_stats": {
            name: {
                "min": float(np.min(values)) if values.size else 0.0,
                "max": float(np.max(values)) if values.size else 0.0,
                "mean": float(np.mean(values)) if values.size else 0.0,
            }
            for name, values in {
                "s0": s0_l[np.isfinite(s0_l)],
                "s1": s1_l[np.isfinite(s1_l)],
                "s2": s2_l[np.isfinite(s2_l)],
                "s3": s3_l[np.isfinite(s3_l)],
            }.items()
        },
        "dop_range": [0.0, 1.0],
        "aolp_range_degrees": [0.0, 180.0],
        "channel_stokes_bwr_products": sorted(channel_stokes_bwr_keys),
        "visualization_policy": visualization_policy,
        "stokes_preview_recipe": "stokes_preview_v1",
        "stokes_schema": MINIMAL_STOKES_SCHEMA,
        "stokes_dtype": "float16",
        "stokes_shape": list(s0.shape),
        "stokes_axis_order": ["height", "width", "rgb"],
        "stokes_component_order": ["S0", "S1", "S2", "S3"],
        "polanalyser_tensor_axis_order": ["height", "width", "rgb", "stokes"],
        "rgb_source": "s0",
        "derived_precision": "float32",
        "aolp_derivation": "0.5*atan2(luminance(S2), luminance(S1)) mod pi",
        "dolp_derivation": "sqrt(luminance(S1)^2+luminance(S2)^2)/max(luminance(S0),1e-8)",
        "derived_on_demand": derived_on_demand,
        "stokes_npz_write_s": stokes_npz_write_s,
        "stokes_npz_bytes": stokes_npz_bytes,
        "preview_write_s": preview_write_s,
        "polar_postprocess_s": time.perf_counter() - write_started,
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
        "s1_over_s0": s1_n.astype(np.float32),
        "s2_over_s0": s2_n.astype(np.float32),
        "dop": dop.astype(np.float32),
        "aolp_deg": aolp_deg.astype(np.float32),
        "mask": mask.astype(bool),
    }
    return summary, arrays


def polar_save_worker_count(batch_size: int) -> int:
    """Threads to use when saving a K-view Stokes strip.

    Measured on the RTX 5090 host at K=12 (512x384, full_v1 policy): 7.5 s
    serial, 2.9 s at 4 threads, 2.5 s at 8. The curve is flat past ~4 because
    the residual is GIL-bound Python between the numpy calls, so the default
    stops there rather than oversubscribing cores the render worker also uses.
    """
    try:
        configured = int(os.environ.get("ROBOMITUBA_POLAR_SAVE_WORKERS", "4"))
    except (TypeError, ValueError):
        configured = 4
    if configured < 1:
        configured = 1
    return max(1, min(configured, int(batch_size)))


def _save_polarization_products_batch(
    strips: Sequence[np.ndarray],
    destinations: Sequence[Path],
    requested_modalities: set[str],
    *,
    visualization_policy: str = "full_v1",
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    progress_extra: dict[str, Any] | None = None,
) -> list[tuple[dict[str, Any], dict[str, np.ndarray]]]:
    """Save every view of a Stokes strip, in parallel, preserving order.

    Each ``(strip, destination)`` pair is independent -- separate host arrays
    writing to separate directories -- so the only shared state is the progress
    callback, which is serialized behind a lock.
    """
    count = len(strips)
    extra = dict(progress_extra or {})
    if progress_callback is not None:
        progress_callback("saving_output", {**extra, "batch_index": 0})

    def _save(index: int) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        return save_polarization_products(
            strips[index],
            destinations[index],
            requested_modalities,
            visualization_policy=visualization_policy,
        )

    workers = polar_save_worker_count(count)
    if workers <= 1 or count <= 1:
        return [_save(index) for index in range(count)]

    lock = threading.Lock()
    done = 0

    def _save_and_report(index: int) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        result = _save(index)
        if progress_callback is not None:
            nonlocal done
            with lock:
                done += 1
                progress_callback("saving_output", {**extra, "batch_index": done - 1})
        return result

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="polar-save") as pool:
        return list(pool.map(_save_and_report, range(count)))


def materialize_stokes_visualizations(
    stokes_npz: str | Path,
    out_dir: str | Path,
    requested_modalities: set[str],
) -> dict[str, str]:
    """Regenerate legacy Stokes PNG products without touching an observation.

    This deliberately delegates to :func:`save_polarization_products` so the
    viewer and ``legacy_full`` exporter share the exact colour-map recipe.  The
    temporary duplicate NPZ is harmless for staging callers and is never
    published by the on-demand viewer path.
    """
    source = Path(stokes_npz)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    arrays = load_stokes_rgb_channels(source)
    image = np.concatenate([arrays[key] for key in ("rgb", *MINIMAL_STOKES_KEYS)], axis=2)
    summary, _arrays = save_polarization_products(
        image,
        target,
        set(requested_modalities),
        visualization_policy="full_v1",
    )
    return dict(summary["outputs"])


def _write_bitmap(path: Path, array: np.ndarray) -> None:
    mi = _import_mitsuba()
    mi.util.write_bitmap(str(path), array.astype(np.float32))


def _sanitize_radiance(arr: np.ndarray, *, max_value: float = 1e4) -> np.ndarray:
    """Repair non-finite (NaN/Inf) pixels and clamp to [0, max_value].

    The measured-pBRDF / channel-split path occasionally emits NaN samples; at
    low spp these survive as opaque black blocks ("black square fireflies") and
    would also corrupt the OptiX denoiser. Non-finite pixels are inpainted from
    their finite 4-neighbours over a few iterations (falling back to 0), so the
    EXR/preview/denoiser all see clean radiance. At high spp (no NaN) this is a
    cheap no-op beyond the finiteness check.
    """
    a = np.asarray(arr, dtype=np.float32)
    bad = ~np.isfinite(a)
    if not bad.any():
        return np.clip(a, 0.0, max_value).astype(np.float32)
    filled = np.where(bad, 0.0, a).astype(np.float32)
    valid = (~bad).astype(np.float32)
    for _ in range(4):
        if valid.min() >= 0.5:
            break
        s = np.zeros_like(filled)
        w = np.zeros_like(valid)
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            s += np.roll(filled * valid, shift, axis=axis)
            w += np.roll(valid, shift, axis=axis)
        fill_here = (valid < 0.5) & (w > 0.0)
        filled = np.where(fill_here, s / np.maximum(w, 1e-6), filled)
        valid = np.where(fill_here, 1.0, valid)
    filled = np.where(valid < 0.5, 0.0, filled)
    return np.clip(filled, 0.0, max_value).astype(np.float32)


def _reject_firefly_outliers(
    rgb: np.ndarray,
    *,
    factor: float = 10.0,
    floor: float = 1e-3,
    iterations: int = 2,
) -> np.ndarray:
    """Clamp isolated bright specks (fireflies) toward their local neighbourhood.

    A firefly is a pixel whose luminance massively exceeds the *median* of its
    3×3 neighbourhood — i.e. an isolated high-variance Monte-Carlo spike. We cap
    such pixels at ``median * factor`` (preserving hue by scaling RGB). A genuine
    bright source spans many pixels, so its neighbourhood median is also high and
    it is left untouched; only lone specks are pulled in. ``floor`` avoids
    touching near-black regions. NaN/Inf are repaired first via _sanitize_radiance.
    """
    out = _sanitize_radiance(rgb)
    if out.ndim != 3 or out.shape[2] != 3:
        return out
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    h, w = out.shape[:2]
    factor = max(1.0, float(factor))
    for _ in range(max(1, int(iterations))):
        lum = out @ weights
        lum_p = np.pad(lum, 1, mode="edge")
        neigh = np.stack(
            [lum_p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)],
            axis=-1,
        )
        med = np.median(neigh, axis=-1)
        thresh = med * factor
        flag = (lum > thresh) & (lum > floor)
        if not np.any(flag):
            break
        target = np.maximum(thresh, floor)
        scale = np.where(flag, target / np.maximum(lum, 1e-6), 1.0).astype(np.float32)
        out = (out * scale[:, :, None]).astype(np.float32)
    return out


# OptiX denoiser objects are bound to a fixed input resolution + guide layout and
# are reusable across frames of that size. Cache one per (variant, w, h, albedo,
# normals) so a same-resolution sweep allocates the denoiser's state/scratch
# (~40MB @256x192 … ~300MB @1280x720) ONCE instead of churning it every frame —
# which would otherwise repeatedly flush Dr.Jit's malloc pool. The resident
# Mitsuba scene is unaffected: it is held by the loaded mi.Scene object, not by
# this pool, so denoising never evicts the cached scene.
_OPTIX_DENOISER_CACHE: dict[tuple, Any] = {}


def _get_optix_denoiser(mi, *, width: int, height: int, albedo: bool, normals: bool):
    key = (str(mi.variant()), int(width), int(height), bool(albedo), bool(normals))
    den = _OPTIX_DENOISER_CACHE.get(key)
    if den is None:
        den = mi.OptixDenoiser(input_size=(width, height), albedo=albedo, normals=normals)
        _OPTIX_DENOISER_CACHE[key] = den
    return den


def _denoise_rgb(
    rgb: np.ndarray,
    albedo: np.ndarray | None,
    normal: np.ndarray | None,
    camera_to_world: np.ndarray,
    *,
    timing: dict[str, Any] | None = None,
) -> np.ndarray:
    """OptiX-denoise a linear-HDR rgb image, guided by albedo + shading normals.

    Returns ``rgb`` unchanged on non-CUDA variants (the OptiX denoiser needs a
    GPU) or if denoising raises. ``normal`` is world-space ``sh_normal``; the
    denoiser is told to map it into the sensor frame via ``to_sensor``.
    """
    mi = _import_mitsuba()
    try:
        variant = mi.variant()
    except Exception:  # noqa: BLE001
        variant = None
    if not variant or not str(variant).startswith("cuda_"):
        return rgb
    h, w = rgb.shape[:2]
    t0 = time.perf_counter()
    use_albedo = albedo is not None
    use_normals = normal is not None
    rgb = _sanitize_radiance(rgb)
    noisy = mi.TensorXf(np.ascontiguousarray(rgb.astype(np.float32)))
    denoiser = _get_optix_denoiser(mi, width=w, height=h, albedo=use_albedo, normals=use_normals)
    kwargs: dict[str, Any] = {}
    if use_albedo:
        kwargs["albedo"] = mi.TensorXf(np.ascontiguousarray(albedo.astype(np.float32)))
    if use_normals:
        kwargs["normals"] = mi.TensorXf(np.ascontiguousarray(normal.astype(np.float32)))
        kwargs["to_sensor"] = mi.Transform4f(np.ascontiguousarray(camera_to_world.astype(np.float32))).inverse()
    out = np.array(denoiser(noisy, **kwargs), dtype=np.float32)
    if timing is not None:
        timing["denoise_s"] = time.perf_counter() - t0
        timing["denoised"] = True
        timing["denoise_albedo"] = use_albedo
        timing["denoise_normals"] = use_normals
    return out


def _build_rgb_result(
    modality: str,
    rgb: np.ndarray,
    out_dir: Path,
    *,
    stem: str,
    timing: dict[str, Any],
    scene_path: Path,
    metadata: Mapping[str, Any] | None = None,
    write_raw_npz: bool = True,
    tone_exposure: float | None = None,
    tone_white: float | None = None,
    firefly_clamp: bool = False,
    firefly_factor: float = 10.0,
    filtered_rgb: np.ndarray | None = None,
) -> tuple[ModalityResult, dict[str, Any]]:
    exr_path = out_dir / f"{stem}.exr"
    png_path = out_dir / f"{stem}.png"
    raw_path = out_dir / f"{stem}_raw.npz"
    filtered_exr_path = out_dir / f"{stem}_filtered.exr"

    raw_rgb = _sanitize_radiance(rgb)
    preview_rgb = _sanitize_radiance(filtered_rgb) if filtered_rgb is not None else raw_rgb
    filtered_written = filtered_rgb is not None or bool(firefly_clamp)
    if firefly_clamp:
        preview_rgb = _reject_firefly_outliers(preview_rgb, factor=firefly_factor)
    save_start = time.perf_counter()
    exr_start = time.perf_counter()
    _write_bitmap(exr_path, raw_rgb)
    save_exr_s = time.perf_counter() - exr_start
    save_filtered_exr_s = 0.0
    if filtered_written:
        filtered_exr_start = time.perf_counter()
        _write_bitmap(filtered_exr_path, preview_rgb)
        save_filtered_exr_s = time.perf_counter() - filtered_exr_start
    elif filtered_exr_path.exists():
        filtered_exr_path.unlink()
    png_start = time.perf_counter()
    preview = save_rgb_radiance_preview(
        preview_rgb,
        png_path,
        exposure=_TONE_EXPOSURE_DEFAULT if tone_exposure is None else tone_exposure,
        white=_TONE_WHITE_DEFAULT if tone_white is None else tone_white,
    )
    save_png_s = time.perf_counter() - png_start
    outputs = {
        "exr": str(exr_path),
        "png": str(png_path),
    }
    if filtered_written:
        outputs["filtered_exr"] = str(filtered_exr_path)
    save_npz_s = 0.0
    raw_npz_removed = False
    if write_raw_npz:
        npz_start = time.perf_counter()
        np.savez_compressed(raw_path, rgb=raw_rgb.astype(np.float32))
        save_npz_s = time.perf_counter() - npz_start
        outputs["raw_npz"] = str(raw_path)
    elif raw_path.exists():
        raw_path.unlink()
        raw_npz_removed = True
    save_s = time.perf_counter() - save_start
    timing_record = {
        "task": "rgb",
        "scene": str(scene_path),
        "spp": timing["spp"],
        "load_scene_s": timing["load_scene_s"],
        "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
        "render_s": timing["render_s"],
        "save_exr_s": save_exr_s,
        "save_filtered_exr_s": save_filtered_exr_s,
        "save_png_s": save_png_s,
        "save_npz_s": save_npz_s,
        "raw_npz_removed": raw_npz_removed,
        "save_s": save_s,
        "total_s": timing["total_s"] + save_s,
        "preview": preview,
        "filtered_output": filtered_written,
        "firefly_clamped_preview": bool(firefly_clamp),
        "outputs": outputs,
    }
    timing_extras = {
        key: value
        for key, value in timing.items()
        if key not in {"variant", "load_scene_s", "scene_cache_hit", "render_s", "save_s", "total_s", "spp"}
    }
    timing_record.update(timing_extras)
    result = ModalityResult(
        name=modality,
        array=raw_rgb.astype(np.float32),
        raw_channels={
            "rgb": raw_rgb.astype(np.float32),
            **({"filtered_rgb": preview_rgb.astype(np.float32)} if filtered_written else {}),
        },
        metadata={
            "preview": preview,
            "filtered_output": filtered_written,
            "firefly_clamped_preview": bool(firefly_clamp),
            **dict(metadata or {}),
        },
        timing={
            "variant": timing["variant"],
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "requested_spp": timing.get("requested_spp"),
            "sensor_sampler_spp": timing.get("sensor_sampler_spp"),
            "render_s": timing["render_s"],
            "save_exr_s": save_exr_s,
            "save_filtered_exr_s": save_filtered_exr_s,
            "save_png_s": save_png_s,
            "save_npz_s": save_npz_s,
            "raw_npz_removed": raw_npz_removed,
            "save_s": timing_record["save_s"],
            "total_s": timing_record["total_s"],
            "scene": str(scene_path),
            "spp": timing["spp"],
            "filtered_output": filtered_written,
            "firefly_clamped_preview": bool(firefly_clamp),
            **timing_extras,
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
    write_raw_npz: bool = True,
) -> tuple[ModalityResult, dict[str, Any]]:
    exr_path = out_dir / f"{stem}.exr"
    png_path = out_dir / f"{stem}.png"
    raw_path = out_dir / f"{stem}_raw.npz"
    rgb = np.repeat(intensity[:, :, None], 3, axis=2).astype(np.float32)

    save_start = time.perf_counter()
    exr_start = time.perf_counter()
    _write_bitmap(exr_path, rgb)
    save_exr_s = time.perf_counter() - exr_start
    preview_percentile = 0.992 if modality == "active_nir_intensity" else 0.995
    png_start = time.perf_counter()
    preview = save_rgb_preview(rgb, png_path, percentile=preview_percentile)
    save_png_s = time.perf_counter() - png_start
    outputs = {
        "exr": str(exr_path),
        "png": str(png_path),
    }
    save_npz_s = 0.0
    raw_npz_removed = False
    if write_raw_npz:
        npz_start = time.perf_counter()
        np.savez_compressed(raw_path, intensity=intensity.astype(np.float32))
        save_npz_s = time.perf_counter() - npz_start
        outputs["raw_npz"] = str(raw_path)
    elif raw_path.exists():
        raw_path.unlink()
        raw_npz_removed = True
    save_s = time.perf_counter() - save_start

    timing_record = {
        "task": modality,
        "scene": str(scene_path),
        "spp": timing["spp"],
        "load_scene_s": timing["load_scene_s"],
        "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
        "render_s": timing["render_s"],
        "save_exr_s": save_exr_s,
        "save_png_s": save_png_s,
        "save_npz_s": save_npz_s,
        "raw_npz_removed": raw_npz_removed,
        "save_s": save_s,
        "total_s": timing["total_s"] + save_s,
        "preview": preview,
        "outputs": outputs,
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
            "requested_spp": timing.get("requested_spp"),
            "sensor_sampler_spp": timing.get("sensor_sampler_spp"),
            "render_s": timing["render_s"],
            "save_exr_s": save_exr_s,
            "save_png_s": save_png_s,
            "save_npz_s": save_npz_s,
            "raw_npz_removed": raw_npz_removed,
            "save_s": save_s,
            "total_s": timing_record["total_s"],
            "scene": str(scene_path),
            "spp": timing["spp"],
        },
        artifacts=timing_record["outputs"],
    )
    return result, timing_record


def _dr_to_numpy(value: Any) -> np.ndarray:
    """Convert a Dr.Jit value to numpy without forcing a dependency at import time."""
    try:
        import drjit as dr
        return np.asarray(dr.to_numpy(dr.detach(value)))
    except Exception:
        return np.asarray(value)


def _transform_points_directions(points: np.ndarray, directions: np.ndarray, transform: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    matrix = np.asarray(transform, dtype=np.float32).reshape(4, 4)
    rotation = matrix[:3, :3]
    translation = matrix[:3, 3]
    return points @ rotation.T + translation, directions @ rotation.T


def _destagger_lidar_field(field: np.ndarray, pixel_shift_by_row: Sequence[int]) -> np.ndarray:
    arr = np.asarray(field)
    if arr.ndim < 2:
        return arr.copy()
    out = np.empty_like(arr)
    for row, shift in enumerate(pixel_shift_by_row):
        out[row] = np.roll(arr[row], -int(shift), axis=0)
    return out


def _batched_scene_intersect(scene: Any, origins: np.ndarray, directions: np.ndarray, mi: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Intersect a batch of rays, with a scalar fallback for scalar Mitsuba builds."""
    count = int(origins.shape[0])
    try:
        ray = mi.Ray3f(
            mi.Point3f(mi.Float(origins[:, 0]), mi.Float(origins[:, 1]), mi.Float(origins[:, 2])),
            mi.Vector3f(mi.Float(directions[:, 0]), mi.Float(directions[:, 1]), mi.Float(directions[:, 2])),
        )
        si = scene.ray_intersect(ray)
        valid = _dr_to_numpy(si.is_valid()).astype(bool).reshape(-1)
        distance = _dr_to_numpy(si.t).astype(np.float32).reshape(-1)
        normals = np.stack([_dr_to_numpy(si.n[i]).astype(np.float32).reshape(-1) for i in range(3)], axis=1)
        if valid.size != count:
            raise RuntimeError("Mitsuba returned a non-batched intersection result")
        return valid, distance, normals, np.ones(count, dtype=bool)
    except Exception:
        valid = np.zeros(count, dtype=bool)
        distance = np.full(count, np.nan, dtype=np.float32)
        normals = np.zeros((count, 3), dtype=np.float32)
        for index, (origin, direction) in enumerate(zip(origins, directions)):
            try:
                ray = mi.Ray3f(
                    mi.Point3f(float(origin[0]), float(origin[1]), float(origin[2])),
                    mi.Vector3f(float(direction[0]), float(direction[1]), float(direction[2])),
                )
                si = scene.ray_intersect(ray)
                if bool(si.is_valid()):
                    valid[index] = True
                    distance[index] = float(si.t)
                    normals[index] = [float(si.n[0]), float(si.n[1]), float(si.n[2])]
            except Exception:
                continue
        return valid, distance, normals, np.zeros(count, dtype=bool)


def _render_lidar_point_cloud(
    scene_path: Path,
    camera_to_world: np.ndarray,
    *,
    config: RenderConfig,
    variant: str,
    lidar_metadata: OusterLidarMetadata | Mapping[str, Any] | str | Path | None = None,
) -> tuple[ModalityResult, dict[str, Any]]:
    from .mitsuba_runtime import resolve_variant

    start = time.perf_counter()
    if lidar_metadata is None and config.lidar_metadata_ref:
        lidar_metadata = config.lidar_metadata_ref
    metadata = lidar_metadata if isinstance(lidar_metadata, OusterLidarMetadata) else load_ouster_metadata(lidar_metadata)
    if lidar_metadata is None and config.lidar_profile not in {"", "os1-128"}:
        metadata = load_ouster_metadata({
            "model": config.lidar_profile,
            "lidar_mode": f"{max(1, int(config.width))}x10",
            "n_rings": max(1, int(config.height)),
            "min_range_m": config.lidar_min_range_m,
            "max_range_m": config.lidar_max_range_m,
        })
    v = resolve_variant(variant, kind="rgb", allow_cpu=True)
    scene, load_s, cache_hit = _load_resident_scene(scene_path, variant=v)
    mi = _import_mitsuba()

    origin, right, up, forward = _camera_basis(camera_to_world)
    horizontal_samples = int(config.width) if int(config.width) > 0 else metadata.columns
    vertical_channels = int(config.height) if int(config.height) > 0 else metadata.n_rings
    # Sensor profiles are authoritative for lidar dimensions; config dimensions
    # remain useful for legacy point-cloud callers.
    if lidar_metadata is not None or config.lidar_profile == "os1-128":
        horizontal_samples = metadata.columns
        vertical_channels = metadata.n_rings
    horizontal_samples = max(1, horizontal_samples)
    vertical_channels = max(1, vertical_channels)
    h0, h1 = metadata.azimuth_window_deg
    h_angles = np.deg2rad(np.linspace(h0, h1, horizontal_samples, endpoint=False, dtype=np.float32))
    altitude = np.asarray(metadata.beam_altitude_angles_deg, dtype=np.float32)
    azimuth_offset = np.asarray(metadata.beam_azimuth_angles_deg, dtype=np.float32)
    if altitude.size != vertical_channels or azimuth_offset.size != vertical_channels:
        raise ValueError("Ouster metadata beam arrays do not match the requested ring count")

    min_range = float(config.lidar_min_range_m if config.lidar_min_range_m > 0.0 else metadata.min_range_m)
    max_range = float(config.lidar_max_range_m if config.lidar_max_range_m > 0.0 else metadata.max_range_m)
    if lidar_metadata is not None:
        min_range = float(metadata.min_range_m)
        max_range = float(metadata.max_range_m)
    wavelength_nm = float(config.lidar_wavelength_nm or metadata.wavelength_nm)
    if lidar_metadata is not None:
        wavelength_nm = float(metadata.wavelength_nm)

    # Beam-local Ouster coordinates: x forward, y left, z up.  Apply the
    # per-beam azimuth/elevation and beam-to-lidar calibration before the
    # sensor pose is applied to world space.
    elev = np.deg2rad(altitude)[:, None]
    az = h_angles[None, :] + np.deg2rad(azimuth_offset)[:, None]
    cv = np.cos(elev)
    local_dirs = np.stack([cv * np.cos(az), cv * np.sin(az), np.broadcast_to(np.sin(elev), (vertical_channels, horizontal_samples))], axis=-1)
    local_dirs = local_dirs.reshape(-1, 3).astype(np.float32)
    local_origins = np.zeros_like(local_dirs)
    beam_origins, beam_dirs = _transform_points_directions(local_origins, local_dirs, metadata.beam_to_lidar_transform)
    sensor_origins, sensor_dirs = _transform_points_directions(beam_origins, beam_dirs, metadata.lidar_to_sensor_transform)
    # Ouster lidar frame uses x-forward, y-left, z-up.
    sensor_basis = np.column_stack([forward, -right, up]).astype(np.float32)
    world_origins = sensor_origins @ sensor_basis.T + origin
    world_dirs = sensor_dirs @ sensor_basis.T
    norms = np.linalg.norm(world_dirs, axis=1, keepdims=True)
    world_dirs = world_dirs / np.maximum(norms, 1e-8)

    render_start = time.perf_counter()
    hit_valid, hit_range, normals_world, batched = _batched_scene_intersect(scene, world_origins, world_dirs, mi)
    hit_range = hit_range.reshape(vertical_channels, horizontal_samples)
    normals_world = normals_world.reshape(vertical_channels, horizontal_samples, 3)
    directions_world = world_dirs.reshape(vertical_channels, horizontal_samples, 3)
    valid = hit_valid.reshape(vertical_channels, horizontal_samples) & np.isfinite(hit_range)
    valid &= (hit_range >= min_range) & (hit_range <= max_range)
    rng = np.random.default_rng(int(config.depth_sensor_seed))
    if config.lidar_noise_std_m > 0.0:
        hit_range = np.where(valid, hit_range + rng.normal(0.0, float(config.lidar_noise_std_m), hit_range.shape), hit_range)
    if config.lidar_dropout_probability > 0.0:
        valid &= rng.random(valid.shape) >= float(config.lidar_dropout_probability)
    valid &= (hit_range >= min_range) & (hit_range <= max_range)
    points_world = world_origins.reshape(vertical_channels, horizontal_samples, 3) + directions_world * hit_range[..., None]
    points_sensor = sensor_origins.reshape(vertical_channels, horizontal_samples, 3) + sensor_dirs.reshape(vertical_channels, horizontal_samples, 3) * hit_range[..., None]
    points_lidar = beam_origins.reshape(vertical_channels, horizontal_samples, 3) + beam_dirs.reshape(vertical_channels, horizontal_samples, 3) * hit_range[..., None]
    points_world[~valid] = np.nan
    points_sensor[~valid] = np.nan
    points_lidar[~valid] = np.nan
    normals_world[~valid] = np.nan
    incidence = np.clip(np.sum(-directions_world * normals_world, axis=-1), 0.0, 1.0)
    incidence[~np.isfinite(incidence)] = 0.0
    reflectivity = np.clip(np.rint(255.0 * incidence), 0, 255).astype(np.uint8)
    safe_range = np.where(valid, hit_range, np.inf)
    signal = np.clip(65535.0 * float(config.lidar_signal_scale) * incidence / np.maximum(safe_range * safe_range, 1e-6), 0, 65535)
    signal[~valid] = 0.0
    signal = signal.astype(np.uint16)
    near_ir = signal.copy()
    range_mm = np.where(valid, np.rint(np.maximum(hit_range, 0.0) * 1000.0), 0).astype(np.uint32)
    range_m = np.where(valid, range_mm.astype(np.float32) / 1000.0, np.nan).astype(np.float32)
    status = np.where(valid, 1, 0).astype(np.uint8)
    # A 10 Hz scan spans 100 ms; each azimuth column is acquired at its
    # own encoder phase within that revolution (not once per full scan).
    column_period_us = 1_000_000.0 / max(metadata.scan_rate_hz * horizontal_samples, 1e-6)
    timestamp_us = np.broadcast_to((np.arange(horizontal_samples, dtype=np.float64) * column_period_us).astype(np.uint64), (vertical_channels, horizontal_samples))
    measurement_id = np.broadcast_to(np.arange(horizontal_samples, dtype=np.uint32), (vertical_channels, horizontal_samples))
    points_lidar_destaggered = _destagger_lidar_field(points_lidar, metadata.pixel_shift_by_row) if config.lidar_destagger else points_lidar.copy()
    ranges_destaggered = _destagger_lidar_field(range_m, metadata.pixel_shift_by_row) if config.lidar_destagger else range_m.copy()
    valid_destaggered = _destagger_lidar_field(valid, metadata.pixel_shift_by_row) if config.lidar_destagger else valid.copy()

    render_s = time.perf_counter() - render_start
    total_s = time.perf_counter() - start
    point_cloud = np.concatenate([points_lidar.reshape(-1, 3), range_m.reshape(-1, 1)], axis=1).astype(np.float32)
    raw_channels = {
        "points": points_lidar.astype(np.float32),
        "xyz": points_lidar.astype(np.float32),
        "xyz_sensor": points_sensor.astype(np.float32),
        "xyz_world": points_world.astype(np.float32),
        "xyz_destaggered": points_lidar_destaggered.astype(np.float32),
        "ranges": range_m,
        "range_m": range_m,
        "range_mm": range_mm,
        "range_destaggered": ranges_destaggered.astype(np.float32),
        "directions": directions_world.astype(np.float32),
        "normals": normals_world.astype(np.float32),
        "valid": valid,
        "valid_destaggered": valid_destaggered,
        "status": status,
        "signal": signal,
        "reflectivity": reflectivity,
        "near_ir": near_ir,
        "timestamp_us": timestamp_us,
        "measurement_id": measurement_id,
        "incidence": incidence.astype(np.float32),
    }
    result = ModalityResult(
        name="lidar_point_cloud",
        array=point_cloud,
        raw_channels=raw_channels,
        metadata={
            "sensor_model": metadata.model,
            "sensor_type": "ouster_lidar",
            "profile": config.lidar_profile,
            "lidar_mode": metadata.lidar_mode,
            "horizontal_samples": horizontal_samples,
            "vertical_channels": vertical_channels,
            "horizontal_fov_deg": [float(h0), float(h1)],
            "vertical_fov_deg": [float(np.min(altitude)), float(np.max(altitude))],
            "range_m": [min_range, max_range],
            "wavelength_nm": wavelength_nm,
            "return_mode": metadata.return_mode,
            "column_period_us": column_period_us,
            "scan_duration_us": 1_000_000.0 / max(metadata.scan_rate_hz, 1e-6),
            "valid_points": int(np.count_nonzero(valid)),
            "batched_intersection": bool(np.all(batched)),
            "signal_model": "analytic_incidence_range",
            "metadata": metadata.to_dict(),
        },
        timing={
            "variant": v,
            "load_scene_s": load_s,
            "scene_cache_hit": cache_hit,
            "render_s": render_s,
            "total_s": total_s,
            "scene": str(scene_path),
            "spp": 1,
        },
        artifacts={},
    )
    record = {
        "task": "ouster_lidar",
        "scene": str(scene_path),
        "spp": 1,
        "load_scene_s": load_s,
        "scene_cache_hit": cache_hit,
        "render_s": render_s,
        "total_s": total_s,
        "valid_points": int(np.count_nonzero(valid)),
        "batched_intersection": bool(np.all(batched)),
        "shape": [vertical_channels, horizontal_samples],
    }
    return result, record

def _save_lidar_point_cloud(result: ModalityResult, out_dir: Path, *, stem: str = "lidar_point_cloud") -> None:
    raw_path = out_dir / f"{stem}.npz"
    np.savez_compressed(raw_path, **result.raw_channels, point_cloud=result.array.astype(np.float32))
    destaggered_path = out_dir / f"{stem}_destaggered.npz"
    np.savez_compressed(
        destaggered_path,
        range_m=np.asarray(result.raw_channels.get("range_destaggered")),
        xyz=np.asarray(result.raw_channels.get("xyz_destaggered")),
        valid=np.asarray(result.raw_channels.get("valid_destaggered")),
    )
    manifest_path = out_dir / f"{stem}_manifest.json"
    manifest_payload = {
        "sensor_type": "ouster_lidar",
        "modality": "lidar_point_cloud",
        "frame": "sensor",
        "staggered": True,
        "array_shape": list(result.raw_channels.get("range_m", result.array).shape),
        "artifacts": {"npz": str(raw_path), "destaggered_npz": str(destaggered_path)},
        "destaggered_ref": str(destaggered_path),
        "measurement_id_ref": str(raw_path),
        "timestamp_ref": str(raw_path),
        "channels": {
            name: {
                "shape": list(np.asarray(value).shape),
                "dtype": str(np.asarray(value).dtype),
                "units": (
                    "m" if name in {"range_m", "ranges", "range_destaggered", "xyz", "xyz_sensor", "xyz_world", "xyz_destaggered", "points"}
                    else "mm" if name == "range_mm"
                    else "us" if name == "timestamp_us"
                    else "unitless"
                ),
            }
            for name, value in result.raw_channels.items()
        },
        "metadata": result.metadata,
        "timing": result.timing,
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    result.artifacts["raw_npz"] = str(raw_path)
    result.artifacts["destaggered_npz"] = str(destaggered_path)
    result.artifacts["sensor_manifest"] = str(manifest_path)


def _compose_derived_result(
    modality: str,
    array: np.ndarray,
    out_dir: Path,
    *,
    timing_seed: dict[str, Any],
    dependencies: dict[str, str],
    write_raw_npz: bool = True,
) -> ModalityResult:
    stem = modality
    exr_path = out_dir / f"{stem}.exr"
    png_path = out_dir / f"{stem}.png"
    raw_path = out_dir / f"{stem}_raw.npz"
    save_start = time.perf_counter()
    exr_start = time.perf_counter()
    _write_bitmap(exr_path, array)
    save_exr_s = time.perf_counter() - exr_start
    png_start = time.perf_counter()
    preview = save_rgb_preview(array, png_path)
    save_png_s = time.perf_counter() - png_start
    artifacts = {
        "exr": str(exr_path),
        "png": str(png_path),
    }
    save_npz_s = 0.0
    raw_npz_removed = False
    if write_raw_npz:
        npz_start = time.perf_counter()
        np.savez_compressed(raw_path, rgb=array.astype(np.float32))
        save_npz_s = time.perf_counter() - npz_start
        artifacts["raw_npz"] = str(raw_path)
    elif raw_path.exists():
        raw_path.unlink()
        raw_npz_removed = True
    timing = dict(timing_seed)
    timing.update({
        "save_exr_s": save_exr_s,
        "save_png_s": save_png_s,
        "save_npz_s": save_npz_s,
        "raw_npz_removed": raw_npz_removed,
        "save_s": time.perf_counter() - save_start,
    })
    return ModalityResult(
        name=modality,
        array=array.astype(np.float32),
        raw_channels={"rgb": array.astype(np.float32)},
        metadata={
            "preview": preview,
            "dependencies": dependencies,
        },
        timing=timing,
        artifacts=artifacts,
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
    return any(modality in modalities for modality in ("depth", "depth_sensor", "depth_transient", "albedo", "sensor_depth_approx"))


def _needs_polar(modalities: set[str]) -> bool:
    return any(modality in modalities for modality in ("polar_rgb_preview", "dop", "aolp", "s1", "s2", "s1_over_s0", "s2_over_s0"))


def _needs_active_nir(modalities: set[str]) -> bool:
    return bool({"active_nir_intensity", "nir_intensity"} & modalities)


def _needs_lidar(modalities: set[str]) -> bool:
    return bool({"lidar_point_cloud", "lidar_range", "lidar_signal", "lidar_reflectivity", "lidar_near_ir", "lidar_valid", "lidar_xyz"} & modalities)


def _needs_hazard_mask(modalities: set[str]) -> bool:
    return "hazard_mask" in modalities


def _needs_sensor_depth(modalities: set[str]) -> bool:
    return bool({"sensor_depth_approx", "depth_sensor"} & modalities)


def _polar_variant(base_variant: str, *, color_mode: str = "rgb_stokes_12") -> str:
    """Return the required variant for the requested Stokes GT contract."""
    if color_mode == "rgb_stokes_12":
        # Do not negotiate this from ``auto``: a spectral carrier has different
        # semantics and would silently violate the 12-channel RGB contract.
        #
        # Prefer the non-AD rgb-polarized variant: this render never needs
        # gradients, and the AD variant spends most of its wall time building
        # a differentiable graph on one CPU core while the GPU sits at ~2%.
        #
        # An earlier attempt to switch was reverted because K>=2 resident
        # heading batches failed with "missing .slot_1.to_world" -- that was
        # not a variant incompatibility but the batch slot bug (identical
        # identity placeholders collapsing the child sensors, plus BatchSensor
        # lacking MI_TRAVERSE_CB), both since fixed. Re-verified on a real K=4
        # batch scene afterwards: 4 slots exposed, no segfault, and dr.freeze
        # settles into replay at 0.67 s per 4-view batch (vs ~100 s+ per view
        # on the AD variant), with slot pose updates correctly applied.
        from .mitsuba_runtime import available_variants

        if "cuda_rgb_polarized" in available_variants():
            return "cuda_rgb_polarized"
        return "cuda_ad_rgb_polarized"
    if not base_variant or base_variant in {"auto", "default"}:
        return "auto"
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
    active_lights: Sequence["ActiveLightSpec"] = (),
    base_pose: Any = None,
    depth_approx: DepthApproxSpec | None = None,
    lidar_metadata: OusterLidarMetadata | Mapping[str, Any] | str | Path | None = None,
    variant: str = "auto",
    progress_callback: Callable[[str, Mapping[str, Any] | None], None] | None = None,
) -> MultimodalRenderResult:
    config = config or RenderConfig()
    requested = _resolve_modalities(modalities)
    requested_set = set(requested)
    if "depth_transient" in requested_set:
        from .mitransient_adapter import availability
        capability = availability()
        reason = capability.get("reason") or "renderer adapter integration is not enabled for this scene pass"
        raise RuntimeError(
            "depth_transient requires a compatible mitransient scene/integrator; "
            f"{reason}. Geometric depth_sensor fallback is intentionally disabled."
        )
    source_scene = Path(scene_xml).resolve()

    if out_dir is None:
        workspace = Path(tempfile.mkdtemp(prefix="robomituba_multimodal_"))
        temporary_workspace = True
    else:
        workspace = Path(out_dir).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        temporary_workspace = False

    _disable_scene_reuse = str(os.environ.get("ROBOMITUBA_DISABLE_SCENE_REUSE", "")).strip().lower()
    _use_scene_reuse = _disable_scene_reuse not in {"1", "true", "yes", "on"}
    _viewpoint = _ViewpointSensorSpec(
        camera_to_world=camera_to_world,
        fov_deg=fov_deg,
        width=config.width,
        height=config.height,
    )

    global _last_source_scene_dir
    current_dir = str(source_scene.parent.resolve())
    if _last_source_scene_dir and _last_source_scene_dir != current_dir:
        with _SCENE_CACHE_LOCK:
            _RESIDENT_SCENE_CACHE.clear()
            _RESIDENT_BATCH_BINDINGS.clear()
    _last_source_scene_dir = current_dir

    results: dict[str, ModalityResult] = {}
    pass_records: dict[str, dict[str, Any]] = {}
    staged_scenes: dict[str, str] = {}
    scene_override = scene_override if (scene_override and (
        scene_override.target_shape_filenames
        or scene_override.bsdf_overrides
        or scene_override.transform_overrides
    )) else None
    assist_light = assist_light if assist_light and assist_light.mode == "camera_aligned_rect" else None
    active_lights = [l for l in (active_lights or []) if getattr(l, "enabled", True)]
    _nir_active_lights = [l for l in active_lights if "nir" in (l.modalities or [])]
    depth_approx = depth_approx if depth_approx and depth_approx.target_shape_filenames else None
    if "sensor_depth_approx" in requested_set and depth_approx is None:
        raise ValueError("sensor_depth_approx requires a depth_approx specification.")
    if _needs_active_nir(requested_set) and assist_light is None and not _nir_active_lights:
        raise ValueError("active NIR modalities require an assist_light or an nir active_light.")
    hazard_target_shape_filenames: list[str] = []
    if scene_override is not None and scene_override.target_shape_filenames:
        hazard_target_shape_filenames = list(scene_override.target_shape_filenames)
    elif depth_approx is not None and depth_approx.target_shape_filenames:
        hazard_target_shape_filenames = list(depth_approx.target_shape_filenames)
    if "hazard_mask" in requested_set and not hazard_target_shape_filenames:
        raise ValueError("hazard_mask requires scene_override.target_shape_filenames or depth_approx.target_shape_filenames.")
    band_mode = _resolve_pbrdf_band_mode(config)
    measured_scope = _resolve_measured_scope(config)
    max_measured_bsdfs = _resolve_max_measured_bsdfs(config)
    use_channel_split_rgb = _needs_path_total(requested_set) and (
        _scene_has_channel_split_measured_bsdfs(source_scene)
        or _scene_has_enabled_measured_policy(
            source_scene,
            measured_scope=measured_scope,
            max_measured_bsdfs=max_measured_bsdfs,
        )
    )
    use_channel_rgb_plugin = (
        use_channel_split_rgb
        and (band_mode == "single" or not os.environ.get("ROBOMITUBA_DISABLE_HPBRDF_RGB_PLUGIN"))
    )

    # ── progress helpers ──────────────────────────────────────────────────
    _pass_index: list[int] = [0]
    _total_passes = [sum([
        (1 if use_channel_rgb_plugin else len(_RGB_CHANNEL_SPLIT_WAVELENGTHS_NM) if use_channel_split_rgb else 1) if _needs_path_total(requested_set) else 0,
        1 if _needs_direct(requested_set) else 0,
        1 if _needs_diffuse(requested_set) else 0,
        1 if _needs_aov(requested_set) else 0,
        1 if ("sensor_depth_approx" in requested_set and depth_approx is not None) else 0,
        1 if ("sensor_depth_approx" in requested_set and depth_approx is not None) else 0,  # mirror pass
        1 if _needs_hazard_mask(requested_set) else 0,
        1 if (_needs_active_nir(requested_set) and assist_light is not None) else 0,
        1 if _needs_polar(requested_set) else 0,
        1 if _needs_lidar(requested_set) else 0,
    ])]

    def _cb(stage: str, ctx: Mapping[str, Any] | None = None) -> None:
        if progress_callback is not None:
            progress_callback(stage, ctx)

    def _render_pass(
        scene_path: Path,
        *,
        pass_name: str,
        spp: int,
        variant_override: str | None = None,
        viewpoint: "_ViewpointSensorSpec | None" = None,
        scene_viewpoint: "_ViewpointSensorSpec | None" = None,
        dynamic_assist_light: AssistLightSpec | None = None,
        seed: int | None = None,
    ) -> tuple[np.ndarray, dict[str, float]]:
        _pass_index[0] += 1
        from .mitsuba_runtime import mark_variant_unavailable, resolve_variant

        requested_variant = variant_override or variant
        if pass_name.startswith("polar"):
            # Band-pinned discrete polar renders run on the rgb Stokes carrier;
            # they must never degrade to a spectral variant (and vice versa).
            kind = (
                "rgb_polarized"
                if isinstance(requested_variant, str) and requested_variant.endswith("rgb_polarized")
                else "spectral_polarized"
            )
        else:
            # unified_spectral: run rgb/nir passes on the rgb_polarized Stokes carrier
            # too, so ONE resident scene serves rgb+nir+polar via band-flip instead of a
            # separate rgb-variant instance (report_2026-07-29_perf.html §1). rgb S0 is
            # channels[3:6] of the Stokes output — the same extraction the polar pass uses.
            kind = "rgb_polarized" if getattr(config, "unified_spectral", False) else "rgb"
        v = resolve_variant(requested_variant, kind=kind, allow_cpu=True)
        if not v.startswith("cuda_"):
            try:
                cpu_spp_cap = int(os.environ.get("ROBOMITUBA_CPU_SPP_CAP", "256"))
            except (TypeError, ValueError):
                cpu_spp_cap = 256
            if cpu_spp_cap > 0 and spp > cpu_spp_cap:
                _cb("render_settings_adjusted", {
                    "pass": pass_name,
                    "requested_spp": spp,
                    "effective_spp": cpu_spp_cap,
                    "variant": v,
                    "reason": "cpu_variant_spp_cap",
                })
                spp = cpu_spp_cap
        base_ctx = {
            "pass": pass_name,
            "spp": spp,
            "variant": v,
            "pass_index": _pass_index[0],
            "total_passes": _total_passes[0],
            **_texture_audit_progress_payload(scene_path),
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
        try:
            image, timing = _render_scene(
                scene_path, variant=v, spp=spp, on_loaded=_on_loaded,
                viewpoint=viewpoint, scene_viewpoint=scene_viewpoint,
                dynamic_assist_light=dynamic_assist_light, seed=seed,
                # K=1 camera-aligned polar views keep one full scene resident
                # just like K=4 passive strips.  Do not let unrelated generic
                # scenes accumulate in this worker, and release only unused
                # Dr.Jit temporary allocations after each view.
                resident_cache_limit=(
                    _POLAR_RESIDENT_SCENE_CACHE_LIMIT
                    if scene_viewpoint is not None and dynamic_assist_light is not None
                    else None
                ),
            )
        except Exception as exc:
            if not v.startswith("cuda_"):
                raise
            mark_variant_unavailable(v, exc)
            fallback = resolve_variant("auto", kind=kind, allow_cpu=True)
            if fallback == v:
                raise
            base_ctx["variant"] = fallback
            _cb("loading_scene", {
                **base_ctx,
                "fallback_from_variant": v,
                "sub_step": "runtime_fallback",
                "sub_phase": 0,
                "sub_total": 5,
                "error": str(exc),
            })
            image, timing = _render_scene(
                scene_path, variant=fallback, spp=spp, on_loaded=_on_loaded,
                viewpoint=viewpoint, scene_viewpoint=scene_viewpoint,
                dynamic_assist_light=dynamic_assist_light, seed=seed,
            )
        _cb("saving_output", {
            "pass": pass_name,
            "pass_index": _pass_index[0],
            "total_passes": _total_passes[0],
        })
        return image, timing

    def _render_adaptive_polar_pass(
        scene_path: Path,
        *,
        variant_override: str | None,
        viewpoint: "_ViewpointSensorSpec | None",
        scene_viewpoint: "_ViewpointSensorSpec | None" = None,
        dynamic_assist_light: AssistLightSpec | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Progressively render physical Stokes data without discarding samples.

        Two independent half-minimum passes form the minimum-SPP candidate.
        Additional independent buckets are traced only when their Stokes
        disagreement exceeds the configured bound; every final image is the
        weighted mean of all samples actually traced.
        """
        configured_min = config.polar_adaptive_spp_min
        configured_max = config.polar_adaptive_spp_max
        if configured_min is None or configured_max is None:
            return _render_pass(
                scene_path, pass_name="polar", spp=config.polar_spp,
                variant_override=variant_override, viewpoint=viewpoint,
                scene_viewpoint=scene_viewpoint,
                dynamic_assist_light=dynamic_assist_light,
            )
        minimum = int(configured_min)
        maximum = min(int(configured_max), int(config.polar_spp))
        if minimum <= 0 or maximum < minimum or minimum % 2:
            raise ValueError(
                "polar adaptive SPP requires an even positive polar_adaptive_spp_min "
                "and polar_adaptive_spp_max >= min"
            )
        threshold = float(config.polar_adaptive_noise_threshold)
        if not math.isfinite(threshold) or threshold <= 0.0:
            raise ValueError("polar_adaptive_noise_threshold must be a finite positive number")

        batches: list[tuple[np.ndarray, int, dict[str, Any]]] = []

        def _take(spp: int, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
            image, timing = _render_pass(
                scene_path, pass_name="polar", spp=spp,
                variant_override=variant_override, viewpoint=viewpoint,
                scene_viewpoint=scene_viewpoint,
                dynamic_assist_light=dynamic_assist_light,
                seed=seed,
            )
            batches.append((image, spp, timing))
            return image, timing

        half = minimum // 2
        first, _ = _take(half, 17011)
        second, first_timing = _take(half, 17012)
        combined = 0.5 * (first + second)
        total_spp = minimum
        noise_scores = [_polar_adaptive_noise_score(first, second)]

        # The next independently sampled bucket has the same weight as the
        # accumulated estimate, allowing an apples-to-apples convergence test.
        if noise_scores[-1] > threshold and maximum >= minimum * 2:
            next_bucket, _ = _take(minimum, 17013)
            noise_scores.append(_polar_adaptive_noise_score(combined, next_bucket))
            combined = 0.5 * (combined + next_bucket)
            total_spp += minimum

        # If the 2048 estimate remains noisy, use every remaining sample.  The
        # final bucket is not used as a stop test: it is the configured upper
        # quality bound and is always incorporated before products are saved.
        if noise_scores[-1] > threshold and total_spp < maximum:
            remaining = maximum - total_spp
            final_bucket, _ = _take(remaining, 17014)
            combined = ((combined * float(total_spp)) + (final_bucket * float(remaining))) / float(maximum)
            total_spp = maximum

        render_s = float(sum(float(timing.get("render_s", 0.0)) for _, _, timing in batches))
        total_s = float(sum(float(timing.get("total_s", 0.0)) for _, _, timing in batches))
        timing = dict(first_timing)
        timing.update({
            "render_s": render_s,
            "total_s": total_s,
            "adaptive_spp_enabled": True,
            "adaptive_spp_min": minimum,
            "adaptive_spp_max": maximum,
            "adaptive_spp_used": total_spp,
            "adaptive_noise_threshold": threshold,
            "adaptive_noise_scores": noise_scores,
            "adaptive_pass_count": len(batches),
        })
        return combined.astype(np.float32, copy=False), timing
    # ─────────────────────────────────────────────────────────────────────

    def stage_filename(key: str, default: str) -> Path:
        return workspace / config.scene_filename(key, default)

    # Denoiser needs albedo + shading-normal guides; render the AOV pass once and
    # reuse it for both the guides and the albedo/depth modality outputs.
    aov_with_normals = bool(config.use_optix_denoiser)
    _aov_render: dict[str, Any] = {}
    path_total_rgb: np.ndarray | None = None

    def _get_aov_render(with_normals: bool) -> dict[str, Any]:
        if _aov_render and _aov_render.get("with_normals") == with_normals:
            return _aov_render
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
            with_normals=with_normals,
        )
        image, timing = _render_pass(scene_aov, pass_name="aov", spp=config.aov_spp)
        timing["spp"] = config.aov_spp
        # The img integrator may emit rgb (3) or rgba (4), so index the trailing
        # AOVs from the end: [..img.., albedo(3), depth(1)(, sh_normal(3))].
        min_ch = 10 if with_normals else 7
        if image.ndim != 3 or image.shape[2] < min_ch:
            raise RuntimeError(f"Unexpected AOV tensor shape: {image.shape} (with_normals={with_normals})")
        if with_normals:
            normal = image[:, :, -3:].astype(np.float32)
            depth = image[:, :, -4].astype(np.float32)
            albedo = np.clip(image[:, :, -7:-4], 0.0, 1.0).astype(np.float32)
        else:
            normal = None
            depth = image[:, :, -1].astype(np.float32)
            albedo = np.clip(image[:, :, -4:-1], 0.0, 1.0).astype(np.float32)
        _aov_render.clear()
        _aov_render.update(
            {
                "with_normals": with_normals,
                "albedo": albedo,
                "depth": depth,
                "normal": normal,
                "timing": timing,
                "scene_aov": scene_aov,
            }
        )
        return _aov_render

    if _needs_path_total(requested_set):
        if use_channel_split_rgb:
            rgb = None
            timing: dict[str, Any] | None = None
            scene_rgb: Path | None = None
            plugin_error: str | None = None
            if use_channel_rgb_plugin:
                try:
                    stage_start = time.perf_counter()
                    _cb("staging_scene", {
                        "pass": "rgb",
                        "channel_rgb_plugin": True,
                        "channel_wavelengths_nm": {label: nm for label, nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM},
                    })
                    if _use_scene_reuse:
                        scene_rgb = _stage_base_path_scene(
                            source_scene,
                            max_depth=config.path_max_depth,
                            rr_depth=config.rr_depth,
                            samples_per_pass=config.samples_per_pass,
                            scene_override=scene_override,
                            ambient_radiance=config.ambient_radiance,
                            channel_rgb_plugin=True,
                            band_mode=band_mode,
                            measured_scope=measured_scope,
                            max_measured_bsdfs=max_measured_bsdfs,
                        )
                    else:
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
                            ambient_radiance=config.ambient_radiance,
                            channel_rgb_plugin=True,
                            band_mode=band_mode,
                            measured_scope=measured_scope,
                            max_measured_bsdfs=max_measured_bsdfs,
                        )
                    staged_scenes["rgb"] = str(scene_rgb)
                    stage_s = time.perf_counter() - stage_start
                    image, timing = _render_pass(
                        scene_rgb,
                        pass_name="rgb",
                        spp=config.path_spp,
                        viewpoint=_viewpoint if _use_scene_reuse else None,
                    )
                    timing["spp"] = config.path_spp
                    timing["stage_s"] = stage_s
                    timing["channel_rgb_plugin"] = True
                    timing["channel_split_rgb"] = True
                    timing["channel_wavelengths_nm"] = {label: nm for label, nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM}
                    rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
                except Exception as exc:
                    plugin_error = str(exc)
                    if band_mode == "single":
                        raise RuntimeError(
                            "single-band RGB staging/render failed; refusing channel-split fallback"
                        ) from exc
                    _clear_scene_caches()
                    _pass_index[0] = max(0, _pass_index[0] - 1)
                    _total_passes[0] += len(_RGB_CHANNEL_SPLIT_WAVELENGTHS_NM) - 1
                    _cb("render_fallback", {
                        "pass": "rgb",
                        "reason": "channel_rgb_plugin_failed",
                        "error": plugin_error,
                        "channel_split_rgb": True,
                        "fallback_passes": len(_RGB_CHANNEL_SPLIT_WAVELENGTHS_NM),
                    })

            if rgb is None or timing is None or scene_rgb is None:
                channel_images: dict[str, np.ndarray] = {}
                channel_timings: dict[str, dict[str, Any]] = {}
                channel_scenes: dict[str, Path] = {}
                for label, wavelength_nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM:
                    stage_start = time.perf_counter()
                    _cb("staging_scene", {
                        "pass": "rgb",
                        "channel": label,
                        "wavelength_nm": wavelength_nm,
                        "channel_split_rgb": True,
                        "channel_rgb_fallback": plugin_error is not None,
                    })
                    if _use_scene_reuse:
                        scene_channel = _stage_base_path_scene(
                            source_scene,
                            max_depth=config.path_max_depth,
                            rr_depth=config.rr_depth,
                            samples_per_pass=config.samples_per_pass,
                            scene_override=scene_override,
                            ambient_radiance=config.ambient_radiance,
                            measured_wavelength_nm=wavelength_nm,
                            measured_scope=measured_scope,
                            max_measured_bsdfs=max_measured_bsdfs,
                        )
                    else:
                        scene_channel = _stage_path_scene(
                            source_scene,
                            stage_filename(f"rgb_{label}", f"scene_rgb_{label}_{wavelength_nm}nm.xml"),
                            camera_to_world=camera_to_world,
                            fov_deg=fov_deg,
                            spp=config.path_spp,
                            width=config.width,
                            height=config.height,
                            max_depth=config.path_max_depth,
                            rr_depth=config.rr_depth,
                            samples_per_pass=config.samples_per_pass,
                            scene_override=scene_override,
                            ambient_radiance=config.ambient_radiance,
                            measured_wavelength_nm=wavelength_nm,
                            measured_scope=measured_scope,
                            max_measured_bsdfs=max_measured_bsdfs,
                        )
                    staged_scenes[f"rgb_{label}"] = str(scene_channel)
                    channel_scenes[label] = scene_channel
                    stage_s = time.perf_counter() - stage_start
                    image, channel_timing = _render_pass(
                        scene_channel,
                        pass_name=f"rgb_{label}_{wavelength_nm}nm",
                        spp=config.path_spp,
                        viewpoint=_viewpoint if _use_scene_reuse else None,
                    )
                    channel_timing["spp"] = config.path_spp
                    channel_timing["stage_s"] = stage_s
                    channel_timing["channel"] = label
                    channel_timing["wavelength_nm"] = wavelength_nm
                    channel_timing["channel_split_rgb"] = True
                    channel_timing["channel_rgb_fallback"] = plugin_error is not None
                    if plugin_error is not None:
                        channel_timing["channel_rgb_plugin_error"] = plugin_error
                    channel_images[label] = image
                    channel_timings[label] = channel_timing

                scene_rgb = channel_scenes.get("g") or next(iter(channel_scenes.values()))
                staged_scenes["rgb"] = str(scene_rgb)
                rgb = _compose_channel_split_rgb(channel_images)
                timing = _merge_channel_split_timing(channel_timings, spp=config.path_spp)
                timing["channel_rgb_plugin"] = False
                timing["channel_rgb_fallback"] = plugin_error is not None
                if plugin_error is not None:
                    timing["channel_rgb_plugin_error"] = plugin_error
        else:
            stage_start = time.perf_counter()
            _cb("staging_scene", {"pass": "rgb"})
            if _use_scene_reuse:
                scene_rgb = _stage_base_path_scene(
                    source_scene,
                    max_depth=config.path_max_depth,
                    rr_depth=config.rr_depth,
                    samples_per_pass=config.samples_per_pass,
                    scene_override=scene_override,
                    ambient_radiance=config.ambient_radiance,
                    measured_scope=measured_scope,
                    max_measured_bsdfs=max_measured_bsdfs,
                )
            else:
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
                    ambient_radiance=config.ambient_radiance,
                    measured_scope=measured_scope,
                    max_measured_bsdfs=max_measured_bsdfs,
                )
            staged_scenes["rgb"] = str(scene_rgb)
            stage_s = time.perf_counter() - stage_start
            image, timing = _render_pass(
                scene_rgb, pass_name="rgb", spp=config.path_spp,
                viewpoint=_viewpoint if _use_scene_reuse else None,
            )
            timing["spp"] = config.path_spp
            timing["stage_s"] = stage_s
            rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
        filtered_rgb: np.ndarray | None = None
        if config.use_optix_denoiser:
            try:
                guides = _get_aov_render(with_normals=True)
                denoise_input = (
                    _reject_firefly_outliers(rgb, factor=config.firefly_clamp_factor)
                    if config.use_firefly_clamp
                    else _sanitize_radiance(rgb)
                )
                filtered_rgb = _denoise_rgb(
                    denoise_input,
                    guides.get("albedo"),
                    guides.get("normal"),
                    camera_to_world,
                    timing=timing,
                )
            except Exception as exc:  # noqa: BLE001 - denoise is best-effort
                _cb("denoise_failed", {"error": str(exc)})
        if filtered_rgb is None and config.use_firefly_clamp:
            filtered_rgb = _reject_firefly_outliers(rgb, factor=config.firefly_clamp_factor)
        band_policy_counts = _pbrdf_band_policy_inventory(scene_rgb)
        measured_policy_counts = _measured_scope_policy_inventory(
            source_scene,
            measured_scope=measured_scope,
            max_measured_bsdfs=max_measured_bsdfs,
        )
        rgb_render_mode = _rgb_render_mode_from_policy(
            band_mode=band_mode,
            timing=timing,
            band_policy_counts=band_policy_counts,
        )
        timing["pbrdf_band_mode"] = band_mode
        timing["measured_scope"] = measured_scope
        timing["max_measured_bsdfs"] = max_measured_bsdfs
        timing["rgb_render_mode"] = rgb_render_mode
        timing["band_policy_counts"] = dict(band_policy_counts)
        timing["measured_policy_counts"] = dict(measured_policy_counts)
        timing["channel_split_rgb"] = rgb_render_mode == "channel_split"
        timing["channel_rgb_plugin"] = rgb_render_mode == "rgb_plugin"
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
                extra={
                    "pbrdf_band_mode": band_mode,
                    "measured_scope": measured_scope,
                    "max_measured_bsdfs": max_measured_bsdfs,
                    "rgb_render_mode": rgb_render_mode,
                    "band_policy_counts": dict(band_policy_counts),
                    "measured_policy_counts": dict(measured_policy_counts),
                    "wall_material_policy": {
                        "background_default": "analytic_or_single_band_albedo_scale",
                        "normal_map": "not_inspected",
                        "bump_map": "not_inspected",
                    },
                    "channel_split_rgb": rgb_render_mode == "channel_split",
                    "channel_rgb_plugin": rgb_render_mode == "rgb_plugin",
                    "channel_rgb_fallback": bool(timing.get("channel_rgb_fallback", False)),
                    **({"channel_rgb_plugin_error": timing["channel_rgb_plugin_error"]} if timing.get("channel_rgb_plugin_error") else {}),
                    "channel_wavelengths_nm": {label: nm for label, nm in _RGB_CHANNEL_SPLIT_WAVELENGTHS_NM},
                },
            ),
            write_raw_npz=config.write_raw_npz,
            tone_exposure=config.tone_exposure,
            tone_white=config.tone_white,
            firefly_clamp=False,
            firefly_factor=config.firefly_clamp_factor,
            filtered_rgb=filtered_rgb,
        )
        pass_records["rgb"] = rgb_record
        path_total_rgb = rgb_result.array.astype(np.float32)
        if "rgb" in requested_set:
            results["rgb"] = rgb_result

    if _needs_direct(requested_set):
        stage_start = time.perf_counter()
        _cb("staging_scene", {"pass": "direct_light_map"})
        if _use_scene_reuse:
            scene_direct = _stage_base_path_scene(
                source_scene,
                max_depth=config.direct_max_depth,
                rr_depth=config.rr_depth,
                samples_per_pass=config.samples_per_pass,
                scene_override=scene_override,
                ambient_radiance=config.ambient_radiance,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )
        else:
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
                ambient_radiance=config.ambient_radiance,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
            )
        staged_scenes["direct_light_map"] = str(scene_direct)
        stage_s = time.perf_counter() - stage_start
        image, timing = _render_pass(
            scene_direct, pass_name="direct_light_map", spp=config.path_spp,
            viewpoint=_viewpoint if _use_scene_reuse else None,
        )
        timing["spp"] = config.path_spp
        timing["stage_s"] = stage_s
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
            write_raw_npz=config.write_raw_npz,
            tone_exposure=config.tone_exposure,
            tone_white=config.tone_white,
            firefly_clamp=config.use_firefly_clamp,
            firefly_factor=config.firefly_clamp_factor,
        )
        pass_records["direct_light_map"] = direct_record
        if "direct_light_map" in requested_set:
            results["direct_light_map"] = direct_result

    if _needs_diffuse(requested_set):
        stage_start = time.perf_counter()
        _cb("staging_scene", {"pass": "diffuse_map"})
        if _use_scene_reuse:
            scene_diffuse = _stage_base_diffuse_override_scene(
                source_scene,
                max_depth=config.path_max_depth,
                rr_depth=config.rr_depth,
                samples_per_pass=config.samples_per_pass,
                scene_override=scene_override,
                ambient_radiance=config.ambient_radiance,
            )
        else:
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
                ambient_radiance=config.ambient_radiance,
            )
        staged_scenes["diffuse_map"] = str(scene_diffuse)
        stage_s = time.perf_counter() - stage_start
        image, timing = _render_pass(
            scene_diffuse, pass_name="diffuse_map", spp=config.path_spp,
            viewpoint=_viewpoint if _use_scene_reuse else None,
        )
        timing["spp"] = config.path_spp
        timing["stage_s"] = stage_s
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
            write_raw_npz=config.write_raw_npz,
            tone_exposure=config.tone_exposure,
            tone_white=config.tone_white,
            firefly_clamp=config.use_firefly_clamp,
            firefly_factor=config.firefly_clamp_factor,
        )
        pass_records["diffuse_map"] = diffuse_record
        if "diffuse_map" in requested_set:
            results["diffuse_map"] = diffuse_result

    if _needs_aov(requested_set):
        # Reuses the guide pass when the denoiser already rendered it this frame.
        aov = _get_aov_render(with_normals=aov_with_normals)
        scene_aov = aov["scene_aov"]
        timing = aov["timing"]
        albedo = aov["albedo"]
        depth = aov["depth"]
        staged_scenes["aov"] = str(scene_aov)
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
                    "depth_space": "mitsuba_aov_camera_depth",
                    "units": "m",
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
        if "depth_sensor" in requested_set:
            sensor_depth, sensor_valid, confidence = _build_sensor_depth(
                depth,
                quantization_m=config.depth_sensor_quantization_m,
                noise_std_m=config.depth_sensor_noise_std_m,
                dropout_probability=config.depth_sensor_dropout_probability,
                seed=config.depth_sensor_seed,
            )
            sensor_info = save_depth_products(sensor_depth, workspace, stem="depth_sensor", title="Sensor Depth")
            sensor_info["confidence_npz"] = str(workspace / "depth_sensor_confidence.npz")
            np.savez_compressed(sensor_info["confidence_npz"], confidence=confidence, valid=sensor_valid)
            results["depth_sensor"] = ModalityResult(
                name="depth_sensor",
                array=sensor_depth.astype(np.float32),
                raw_channels={"depth": sensor_depth.astype(np.float32), "valid": sensor_valid, "confidence": confidence},
                metadata={
                    **_branch_metadata(illumination_tag="active_tof_sensor_model", scene_override=scene_override),
                    "source_result": "depth",
                    "depth_space": "mitsuba_aov_camera_depth",
                    "units": "m",
                    "quantization_m": float(config.depth_sensor_quantization_m),
                    "noise_std_m": float(config.depth_sensor_noise_std_m),
                    "dropout_probability": float(config.depth_sensor_dropout_probability),
                    "valid_pixels": int(np.count_nonzero(sensor_valid)),
                },
                timing={**dict(timing), "source_results": ["depth"]},
                artifacts={"png": sensor_info["png"], "raw_npz": sensor_info["raw_npz"], "confidence_npz": sensor_info["confidence_npz"]},
            )
        if "depth_transient" in requested_set:
            from .mitransient_adapter import availability
            capability = availability()
            reason = capability.get("reason") or "renderer adapter integration is not enabled for this scene pass"
            raise RuntimeError(
                "depth_transient requires a compatible mitransient scene/integrator; "
                f"{reason}. Geometric depth_sensor fallback is intentionally disabled."
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

    if _needs_hazard_mask(requested_set):
        _cb("staging_scene", {"pass": "hazard_mask"})
        scene_mask = _stage_target_mask_scene(
            source_scene,
            stage_filename("hazard_mask", "scene_hazard_mask.xml"),
            camera_to_world=camera_to_world,
            fov_deg=fov_deg,
            spp=max(1, config.aov_spp),
            width=config.width,
            height=config.height,
            target_shape_filenames=hazard_target_shape_filenames,
        )
        staged_scenes["hazard_mask"] = str(scene_mask)
        mask_image, mask_timing = _render_pass(scene_mask, pass_name="hazard_mask", spp=max(1, config.aov_spp))
        mask_timing["spp"] = max(1, config.aov_spp)
        hazard_mask = _extract_binary_mask(mask_image)
        mask_result, mask_record = _build_grayscale_result(
            "hazard_mask",
            hazard_mask.astype(np.float32),
            workspace,
            stem=config.artifact_stem("hazard_mask", "hazard_mask"),
            timing=mask_timing,
            scene_path=scene_mask,
            metadata=_branch_metadata(
                illumination_tag="hazard_annotation_mask",
                scene_override=scene_override,
                depth_model=depth_approx.mode if depth_approx is not None else None,
                extra={
                    "target_shape_filenames": list(hazard_target_shape_filenames),
                    "mask_pixels": int(np.count_nonzero(hazard_mask)),
                },
            ),
            write_raw_npz=config.write_raw_npz,
        )
        mask_result.raw_channels["mask"] = hazard_mask.astype(bool)
        pass_records["hazard_mask"] = mask_record
        results["hazard_mask"] = mask_result

    if _needs_lidar(requested_set):
        _pass_index[0] += 1
        _cb("rendering", {
            "pass": "lidar_point_cloud",
            "spp": 1,
            "variant": variant,
            "pass_index": _pass_index[0],
            "total_passes": _total_passes[0],
        })
        lidar_result, lidar_record = _render_lidar_point_cloud(
            source_scene,
            camera_to_world,
            config=config,
            variant=variant,
            lidar_metadata=lidar_metadata,
        )
        _save_lidar_point_cloud(lidar_result, workspace, stem=config.artifact_stem("lidar_point_cloud", "lidar_point_cloud"))
        pass_records["lidar_point_cloud"] = lidar_record
        results["lidar_point_cloud"] = lidar_result
        alias_map = {
            "lidar_range": "range_m",
            "lidar_signal": "signal",
            "lidar_reflectivity": "reflectivity",
            "lidar_near_ir": "near_ir",
            "lidar_valid": "valid",
            "lidar_xyz": "xyz",
        }
        for alias, channel in alias_map.items():
            if alias in requested_set:
                value = lidar_result.raw_channels[channel]
                results[alias] = ModalityResult(
                    name=alias,
                    array=np.asarray(value),
                    raw_channels={channel: np.asarray(value)},
                    metadata={**lidar_result.metadata, "source_result": "lidar_point_cloud", "channel": channel},
                    timing=dict(lidar_result.timing),
                    artifacts=dict(lidar_result.artifacts),
                )

    if _needs_active_nir(requested_set) and (assist_light is not None or _nir_active_lights):
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
            measured_wavelength_nm=854,
            measured_scope=measured_scope,
            max_measured_bsdfs=max_measured_bsdfs,
            active_lights=_nir_active_lights,
            base_pose=base_pose,
            active_pass_kind="nir",
            active_spectral=False,
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
            write_raw_npz=config.write_raw_npz,
        )
        pass_records["active_nir_intensity"] = nir_record
        if "active_nir_intensity" in requested_set:
            results["active_nir_intensity"] = nir_result
        if "nir_intensity" in requested_set:
            nir_alias = ModalityResult(
                name="nir_intensity",
                array=nir_result.array,
                raw_channels=dict(nir_result.raw_channels),
                metadata={
                    **dict(nir_result.metadata),
                    "sensor_model": "active_nir_camera",
                    "wavelength_band_nm": [
                        float(config.nir_wavelength_min_nm),
                        float(config.nir_wavelength_max_nm),
                    ],
                    "active_emitter_radiance": float(config.nir_active_emitter_radiance),
                    "calibration_status": "metadata_explicit_radiometric_proxy",
                },
                timing=dict(nir_result.timing),
                artifacts=dict(nir_result.artifacts),
            )
            results["nir_intensity"] = nir_alias

    polarization_material_mode = "not_requested"
    if _needs_polar(requested_set):
        # Keep K=1 and K=4 products in one global, gravity-aligned Stokes
        # frame. The camera is slightly pitched, so its local image-up rotates
        # with yaw and cannot serve as a shared K=4 batch reference axis.
        from .polar_heading_batch import shared_stokes_reference_axis

        stokes_reference_axis = shared_stokes_reference_axis([camera_to_world])
        _polar_active_lights = [l for l in active_lights if "polar" in (l.modalities or [])]
        # Physical Stokes GT must include reflected/transmitted background paths.
        # Keep direct only as an explicit fast diagnostic preview.
        polar_nested, polar_max_depth = _polar_transport_integrator(config)
        polar_illumination_tag = (
            "camera_aligned_rgb_active_polarized" if assist_light is not None
            else "rig_active_light" if _polar_active_lights
            else "ambient_room"
        )
        # A rig-mounted active light remains pose-baked. A camera-aligned
        # rectangle, however, has a fixed topology: retain it once in a base
        # Stokes scene and update its two transforms together with the scene
        # sensor. This avoids reparsing the complete XML for every heading.
        use_base_polar_scene = _use_scene_reuse and not _polar_active_lights
        use_dynamic_camera_assist = use_base_polar_scene and assist_light is not None
        # Any resident base-Stokes scene (ambient or camera-aligned active
        # light, base or scene_override-perturbed) always stages an explicit
        # ``stokes_reference_axis`` a few lines below, so the C++
        # StokesIntegrator's reference frame comes from that static
        # world-space property (stokes.cpp: m_has_reference_axis), never from
        # `m_sensor->world_transform()`. That means whichever sensor object
        # renders a given call is physically interchangeable here, so every
        # use_base_polar_scene case can reuse the scene's own sensor via
        # mi.traverse() (scene_viewpoint) instead of constructing a fresh one
        # (viewpoint) each call -- which is also what lets _render_scene's
        # dr.freeze path engage for ambient/perturbed K=1 polar, not just the
        # active-light case.
        polar_viewpoint = _viewpoint if not use_base_polar_scene else None
        polar_scene_viewpoint = _viewpoint if use_base_polar_scene else None
        if use_base_polar_scene:
            scene_polar = _stage_base_stokes_scene(
                source_scene,
                samples_per_pass=config.samples_per_pass,
                scene_override=scene_override,
                assist_light=assist_light if use_dynamic_camera_assist else None,
                # The staged scene's own sensor is what actually renders on the
                # use_base_polar_scene path (its transform is driven through
                # mi.traverse), so it must carry the *camera's* intrinsics.
                # Passing these only for the camera-aligned active-light case
                # silently made ambient/perturbed views inherit the authored
                # render_scene.xml film instead -- e.g. 640x480 @ fov 60 for a
                # polar_cam declared as 512x384 @ fov 90.
                camera_fov_deg=float(fov_deg),
                camera_width=int(config.width),
                camera_height=int(config.height),
                nested_integrator_type=polar_nested,
                nested_max_depth=polar_max_depth,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
                stokes_reference_axis=stokes_reference_axis,
            )
        else:
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
                nested_max_depth=polar_max_depth,
                measured_scope=measured_scope,
                max_measured_bsdfs=max_measured_bsdfs,
                active_lights=_polar_active_lights,
                base_pose=base_pose,
                stokes_reference_axis=stokes_reference_axis,
            )
        staged_scenes["polar"] = str(scene_polar)
        _cb("staging_scene", {"pass": "polar"})

        requested_polar = {modality for modality in requested_set if modality in {"polar_rgb_preview", "dop", "aolp", "s1", "s2", "s1_over_s0", "s2_over_s0"}}
        image, timing = _render_adaptive_polar_pass(
            scene_polar,
            variant_override=_polar_variant(variant, color_mode=config.polar_color_mode),
            viewpoint=polar_viewpoint,
            scene_viewpoint=polar_scene_viewpoint,
            dynamic_assist_light=assist_light if use_dynamic_camera_assist else None,
        )
        timing["spp"] = int(timing.get("adaptive_spp_used", config.polar_spp))
        timing["dynamic_sensor"] = bool(use_base_polar_scene)
        timing["dynamic_camera_assist"] = bool(use_dynamic_camera_assist)
        summary, arrays = save_polarization_products(
            image,
            workspace,
            requested_polar,
            visualization_policy=config.polar_visualization_policy,
        )
        summary.update({
            "schema": "opticalnav.stokes_rgb_12.minimal_f16.v2",
            "polar_color_mode": config.polar_color_mode,
            "stokes_channel_order": ["S0_RGB", "S1_RGB", "S2_RGB", "S3_RGB"],
            "stokes_basis": "world_gravity_y_v1",
            "stokes_reference_axis": list(stokes_reference_axis),
        })
        quality_summary = _polar_quality_summary(summary, config)
        polarization_material_mode = "shared_material_policy"

        pass_records["polarization"] = {
            "task": "polar",
            "scene": str(scene_polar),
            "spp": config.polar_spp,
            # This path is deliberately K=1 for camera-local polarized
            # illumination.  It remains resident, but never co-renders two
            # active emitters in a spatial strip.
            "batch_size": 1,
            "batch_mode": (
                "active_stokes_heading_k1_resident_v1"
                if use_dynamic_camera_assist
                else "stokes_k1_v1"
            ),
            "resident_scene": bool(use_base_polar_scene),
            # Persist both the caller's requested value and the dynamic
            # sensor's local sampler value. The AD integrator's ``prepare``
            # call overrides that sampler with requested_spp; retaining both
            # prevents a misleading future diagnosis from the XML sampler's
            # default sample_count alone.
            "requested_spp": int(timing.get("requested_spp", config.polar_spp)),
            "sensor_sampler_spp": timing.get("sensor_sampler_spp"),
            "effective_spp": int(timing["spp"]),
            "polar_transport": config.polar_transport,
            "polar_color_mode": config.polar_color_mode,
            "stokes_schema": summary["schema"],
            "stokes_channel_order": summary["stokes_channel_order"],
            "stokes_basis": summary["stokes_basis"],
            "stokes_reference_axis": summary["stokes_reference_axis"],
            "nested_integrator": polar_nested,
            "max_depth": polar_max_depth,
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "total_s": timing["total_s"],
            "stokes_npz_write_s": summary["stokes_npz_write_s"],
            "stokes_npz_bytes": summary["stokes_npz_bytes"],
            "preview_write_s": summary["preview_write_s"],
            "polar_postprocess_s": summary["polar_postprocess_s"],
            "material_mode": polarization_material_mode,
            "material_policy": "shared_with_rgb",
            **quality_summary,
            "dynamic_sensor": bool(use_base_polar_scene),
            "dynamic_camera_assist": bool(use_dynamic_camera_assist),
            "resident_allocator_prepare_s": timing.get("resident_allocator_prepare_s", 0.0),
            "resident_allocator_flush_s": timing.get("resident_allocator_flush_s", 0.0),
            # This record enumerates its keys, so freeze state has to be listed
            # explicitly -- without it a durable timing log cannot distinguish
            # "freeze re-recorded every frame" from "freeze never engaged".
            "drjit_freeze_active": timing.get("drjit_freeze_active"),
            "drjit_freeze_stage": timing.get("drjit_freeze_stage"),
            "illumination_tag": polar_illumination_tag,
            "stokes_shape": list(image.shape),
            "polarization": summary,
            "measured_scope": measured_scope,
            "max_measured_bsdfs": max_measured_bsdfs,
            **{
                key: timing[key]
                for key in (
                    "adaptive_spp_enabled", "adaptive_spp_min", "adaptive_spp_max",
                    "adaptive_spp_used", "adaptive_noise_threshold", "adaptive_noise_scores",
                    "adaptive_pass_count",
                )
                if key in timing
            },
        }
        shared_timing = {
            "variant": timing["variant"],
            "load_scene_s": timing["load_scene_s"],
            "scene_cache_hit": bool(timing.get("scene_cache_hit", False)),
            "render_s": timing["render_s"],
            "scene": str(scene_polar),
            "spp": config.polar_spp,
            "requested_spp": int(timing.get("requested_spp", config.polar_spp)),
            "sensor_sampler_spp": timing.get("sensor_sampler_spp"),
            "effective_spp": int(timing["spp"]),
            "polar_transport": config.polar_transport,
            "polar_color_mode": config.polar_color_mode,
            "stokes_schema": summary["schema"],
            "stokes_channel_order": summary["stokes_channel_order"],
            "stokes_basis": summary["stokes_basis"],
            "nested_integrator": polar_nested,
            "max_depth": polar_max_depth,
            "total_s": timing["total_s"],
            "stokes_npz_write_s": summary["stokes_npz_write_s"],
            "stokes_npz_bytes": summary["stokes_npz_bytes"],
            "preview_write_s": summary["preview_write_s"],
            "polar_postprocess_s": summary["polar_postprocess_s"],
            "material_mode": polarization_material_mode,
            "material_policy": "shared_with_rgb",
            **quality_summary,
            "dynamic_sensor": bool(use_base_polar_scene),
            "measured_scope": measured_scope,
            "max_measured_bsdfs": max_measured_bsdfs,
            **{
                key: timing[key]
                for key in (
                    "adaptive_spp_enabled", "adaptive_spp_min", "adaptive_spp_max",
                    "adaptive_spp_used", "adaptive_noise_threshold", "adaptive_noise_scores",
                    "adaptive_pass_count",
                )
                if key in timing
            },
        }
        shared_artifacts = {
            "stokes_npz": summary["outputs"]["stokes_npz"],
        }
        def _polar_artifacts(name: str) -> dict[str, Any]:
            artifacts = {**shared_artifacts, "stokes_npz": summary["outputs"]["stokes_npz"]}
            output = summary["outputs"].get(name)
            if output:
                artifacts["png"] = output
            elif name != "rgb_preview":
                artifacts["derived_on_demand"] = {
                    "source": summary["outputs"]["stokes_npz"],
                    "recipe": summary["stokes_preview_recipe"],
                    "modality": name,
                }
            return artifacts
        shared_metadata = _branch_metadata(
            illumination_tag=polar_illumination_tag,
            scene_override=scene_override,
            assist_light=assist_light,
            extra={
                "material_mode": polarization_material_mode,
                "material_policy": "shared_with_rgb",
                "polar_transport": config.polar_transport,
                "polar_color_mode": config.polar_color_mode,
                "stokes_schema": summary["schema"],
                "stokes_channel_order": summary["stokes_channel_order"],
                "stokes_basis": summary["stokes_basis"],
                "nested_integrator": polar_nested,
                "max_depth": polar_max_depth,
                **quality_summary,
                "measured_scope": measured_scope,
                "max_measured_bsdfs": max_measured_bsdfs,
                "invalid_pixel_count": int(summary.get("invalid_pixel_count", 0)),
                "finite_ratio": float(summary.get("finite_ratio", 1.0)),
                "stokes_luminance_stats": dict(summary.get("stokes_luminance_stats") or {}),
                "polar_visualization_policy": config.polar_visualization_policy,
                "stokes_preview_recipe": summary["stokes_preview_recipe"],
                "derived_on_demand": list(summary["derived_on_demand"]),
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
                artifacts=_polar_artifacts("rgb_preview"),
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
                artifacts=_polar_artifacts("dop"),
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
                artifacts=_polar_artifacts("aolp"),
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
                artifacts=_polar_artifacts("s1"),
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
                artifacts=_polar_artifacts("s2"),
            )
        if "s1_over_s0" in requested_set:
            results["s1_over_s0"] = ModalityResult(
                name="s1_over_s0",
                array=arrays["s1_over_s0"],
                raw_channels={
                    "s1_over_s0": arrays["s1_over_s0"],
                    "s0_l": arrays["s0_l"],
                    "mask": arrays["mask"],
                },
                metadata={**shared_metadata, "range": [-1.0, 1.0]},
                timing=dict(shared_timing),
                artifacts=_polar_artifacts("s1_over_s0"),
            )
        if "s2_over_s0" in requested_set:
            results["s2_over_s0"] = ModalityResult(
                name="s2_over_s0",
                array=arrays["s2_over_s0"],
                raw_channels={
                    "s2_over_s0": arrays["s2_over_s0"],
                    "s0_l": arrays["s0_l"],
                    "mask": arrays["mask"],
                },
                metadata={**shared_metadata, "range": [-1.0, 1.0]},
                timing=dict(shared_timing),
                artifacts=_polar_artifacts("s2_over_s0"),
            )

    total_arr = results["rgb"].array.astype(np.float32) if "rgb" in results else path_total_rgb
    direct_arr = results["direct_light_map"].array.astype(np.float32) if "direct_light_map" in results else None
    diffuse_arr = results["diffuse_map"].array.astype(np.float32) if "diffuse_map" in results else None
    if "indirect_light_map" in requested_set:
        if total_arr is None or direct_arr is None:
            raise RuntimeError("indirect_light_map requires rgb and direct_light_map source arrays.")
        indirect = np.clip(total_arr - direct_arr, 0.0, None)
        results["indirect_light_map"] = _compose_derived_result(
            "indirect_light_map",
            indirect,
            workspace,
            timing_seed={
                "source_results": ["rgb", "direct_light_map"],
            },
            dependencies={
                "rgb": pass_records["rgb"]["outputs"].get("raw_npz", pass_records["rgb"]["outputs"]["exr"]),
                "direct_light_map": pass_records["direct_light_map"]["outputs"].get("raw_npz", pass_records["direct_light_map"]["outputs"]["exr"]),
            },
            write_raw_npz=config.write_raw_npz,
        )
    if "specular_map" in requested_set:
        if total_arr is None or diffuse_arr is None:
            raise RuntimeError("specular_map requires rgb and diffuse_map source arrays.")
        specular = np.clip(total_arr - diffuse_arr, 0.0, None)
        results["specular_map"] = _compose_derived_result(
            "specular_map",
            specular,
            workspace,
            timing_seed={
                "source_results": ["rgb", "diffuse_map"],
            },
            dependencies={
                "rgb": pass_records["rgb"]["outputs"].get("raw_npz", pass_records["rgb"]["outputs"]["exr"]),
                "diffuse_map": pass_records["diffuse_map"]["outputs"].get("raw_npz", pass_records["diffuse_map"]["outputs"]["exr"]),
            },
            write_raw_npz=config.write_raw_npz,
        )

    if any(modality in requested_set for modality in ("indirect_light_map", "specular_map")):
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


def render_ambient_stokes_heading_batch(
    scene_xml: str | Path,
    camera_to_worlds: Sequence[np.ndarray | Sequence[float]],
    fov_deg: float,
    modalities: Sequence[str],
    *,
    out_dirs: Sequence[str | Path],
    config: RenderConfig | None = None,
    scene_override: SceneOverrideSpec | None = None,
    assist_lights: Sequence[AssistLightSpec] | None = None,
    batch_mode: str = "ambient_stokes_heading_batch_v1",
    variant: str = "auto",
    progress_callback: Callable[[str, Mapping[str, Any] | None], None] | None = None,
    defer: bool = False,
) -> list[MultimodalRenderResult] | Callable[[], list[MultimodalRenderResult]]:
    """Render 2–4 Stokes views in one native-perspective batch.

    With ``defer=True`` the GPU render still runs synchronously, but the
    host-side tail (save + result assembly) is returned as a zero-argument
    callable instead of being executed. The caller owns exactly one such
    callable at a time and must invoke it — the batch is not complete until it
    returns. This exists so a worker can start the next batch's render while
    the previous batch's ~7 s of CPU work drains on another thread.

    This is deliberately narrower than :func:`render_modalities`: it is the
    production K=4 fast path for a single polar camera.  By default the scene
    is passive.  Supplying one ``assist_lights`` entry per camera stages every
    camera-local emitter in the shared batch scene; callers must first certify
    that the selected spatially separated views have negligible cross-light
    influence.  Each returned item is an ordinary per-heading result; only the
    renderer's temporary batch film is shared. Passive batches use a stable
    K-slot scene when resident reuse is enabled, so consecutive strips update
    only sensor transforms instead of reloading geometry and textures.
    """
    from .mitsuba_runtime import resolve_variant
    from .polar_heading_batch import (
        MIN_STOKES_HEADING_BATCH_SLOTS,
        max_stokes_heading_batch_slots,
        normalize_camera_to_world,
        shared_stokes_reference_axis,
        split_stokes_heading_batch,
        stage_ambient_stokes_heading_batch,
    )

    config = config or RenderConfig()
    requested = _resolve_modalities(modalities)
    requested_set = set(requested)
    if not requested or not _needs_polar(requested_set) or any(item not in {
        "polar_rgb_preview", "dop", "aolp", "s1", "s2", "s1_over_s0", "s2_over_s0",
    } for item in requested):
        raise ValueError("Stokes heading batches support polar camera modalities only")
    if not MIN_STOKES_HEADING_BATCH_SLOTS <= len(camera_to_worlds) <= max_stokes_heading_batch_slots():
        raise ValueError(
            f"Stokes heading batches require {MIN_STOKES_HEADING_BATCH_SLOTS} to "
            f"{max_stokes_heading_batch_slots()} headings, got {len(camera_to_worlds)}"
        )
    if len(out_dirs) != len(camera_to_worlds):
        raise ValueError("out_dirs must contain one destination per heading")
    if assist_lights is not None and len(assist_lights) != len(camera_to_worlds):
        raise ValueError("assist_lights must contain one camera-aligned light per batch view")
    if config.polar_adaptive_spp_min is not None or config.polar_adaptive_spp_max is not None:
        raise ValueError("Stokes heading batches require fixed polar SPP")
    source_scene = Path(scene_xml).resolve()
    # Camera poses arriving from a durable RenderRequest may still use its
    # legacy column-major-flat storage. Normalize before both reference-frame
    # certification and resident ParamMap updates.
    poses = [normalize_camera_to_world(item).astype(np.float32) for item in camera_to_worlds]
    # A K-heading strip has one outer Stokes integrator.  Make its basis
    # explicit and certify that this yaw-only rig really shares the same up
    # axis before the first expensive scene load.
    stokes_reference_axis = shared_stokes_reference_axis(poses)
    polar_nested, polar_max_depth = _polar_transport_integrator(config)
    base_scene = _stage_base_stokes_scene(
        source_scene,
        samples_per_pass=config.samples_per_pass,
        scene_override=scene_override,
        nested_integrator_type=polar_nested,
        nested_max_depth=polar_max_depth,
        measured_scope=_resolve_measured_scope(config),
        max_measured_bsdfs=_resolve_max_measured_bsdfs(config),
        stokes_reference_axis=stokes_reference_axis,
    )
    destinations = [Path(item).resolve() for item in out_dirs]
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
    if progress_callback is not None:
        progress_callback("staging_scene", {"pass": "polar", "batch_size": len(poses), "mode": batch_mode})
    selected_variant = resolve_variant(
        _polar_variant(variant, color_mode=config.polar_color_mode),
        kind="rgb_polarized",
        allow_cpu=True,
    )
    use_resident_batch_scene = assist_lights is None and _resident_stokes_heading_batches_enabled()
    if use_resident_batch_scene:
        # Always stage the *same* K-slot shape, padding a short tail batch up to
        # the maximum. A K=2 strip would otherwise be a different XML file than
        # a K=3/K=4 strip, and because only one polar scene stays resident
        # (_POLAR_RESIDENT_SCENE_CACHE_LIMIT) the two shapes evict each other
        # every time the batch size changes. That eviction also discards the
        # dr.freeze recording bound to the evicted scene, so each new batch
        # paid a fresh ~100s record instead of a fast replay. One shape means
        # one resident scene and one recording reused across every batch; the
        # padded slots render duplicate pixels that are dropped right below,
        # which is far cheaper than re-recording.
        #
        # A request may ask for more headings than one resident strip holds
        # (the slot count is capped by GPU memory, not by the planner), so the
        # poses are rendered in fixed-size chunks against that one scene and
        # the resulting strips are concatenated back into the requested order.
        resident_slots = max(2, int(_RESIDENT_STOKES_HEADING_BATCH_SLOTS))
        pose_chunks = [
            list(poses[start:start + resident_slots])
            for start in range(0, len(poses), resident_slots)
        ]
        batch_scene = _stage_resident_stokes_heading_batch_scene(
            base_scene,
            batch_size=resident_slots,
            width=int(config.width),
            height=int(config.height),
            fov_deg=float(fov_deg),
            stokes_reference_axis=stokes_reference_axis,
        )
        # A first cold load of a heavy scene can take many minutes. Report the
        # GPU-load phase separately from ray tracing so the monitor does not
        # look stalled while textures and the OptiX BVH are still being built.
        batch_progress_ctx = {
            "pass": "polar", "batch_size": len(poses), "variant": selected_variant,
            "mode": batch_mode, "resident_scene": True, "resident_slots": resident_slots,
        }
        scene_cached = _resident_scene_cache_has(batch_scene, variant=selected_variant)
        if progress_callback is not None:
            progress_callback("loading_scene", {
                **batch_progress_ctx,
                "sub_step": "cached" if scene_cached else "uploading_textures",
                "cached": scene_cached,
                **({} if scene_cached else _count_scene_assets(batch_scene)),
            })

        def _on_batch_loaded() -> None:
            if progress_callback is not None:
                progress_callback("rendering", batch_progress_ctx)

        chunk_strips: list[np.ndarray] = []
        timing: dict[str, Any] = {}
        padded_total = 0
        for chunk_index, chunk in enumerate(pose_chunks):
            padded_chunk = list(chunk)
            while len(padded_chunk) < resident_slots:
                # Duplicate the tail so the film keeps the staged slot count;
                # the extra strip is discarded right after the split below.
                padded_chunk.append(chunk[-1])
            padded_total += len(padded_chunk) - len(chunk)
            chunk_image, chunk_timing = _render_resident_stokes_heading_batch_scene(
                batch_scene,
                camera_to_worlds=padded_chunk,
                variant=selected_variant,
                spp=int(config.polar_spp),
                on_loaded=_on_batch_loaded if chunk_index == 0 else None,
            )
            strips = split_stokes_heading_batch(
                chunk_image, batch_size=len(padded_chunk),
                width=int(config.width), height=int(config.height),
            )
            chunk_strips.extend(strips[: len(chunk)])
            for key, value in chunk_timing.items():
                # Sum the per-chunk costs; keep scalars from the last chunk.
                if key.endswith("_s") and isinstance(value, (int, float)):
                    timing[key] = float(timing.get(key, 0.0)) + float(value)
                else:
                    timing[key] = value
        image = np.concatenate(chunk_strips, axis=1)
        timing["resident_slots"] = resident_slots
        timing["resident_chunks"] = len(pose_chunks)
        timing["resident_padded_slots"] = padded_total
    else:
        with tempfile.TemporaryDirectory(prefix="robomituba_stokes_heading_batch_") as tmpdir:
            batch_scene = Path(tmpdir) / "stokes_heading_batch.xml"
            batch_source = base_scene
            if assist_lights is not None:
                active_source = Path(tmpdir) / "stokes_heading_batch_active.xml"
                root = ET.parse(base_scene).getroot()
                for light_index, (pose, light) in enumerate(zip(poses, assist_lights)):
                    _append_camera_assist_light(
                        root,
                        pose,
                        light,
                        polarized=light.polarized,
                        id_suffix=f"_{light_index:02d}",
                    )
                ET.ElementTree(root).write(active_source, encoding="utf-8", xml_declaration=True)
                batch_source = active_source
            stage_ambient_stokes_heading_batch(
                batch_source,
                batch_scene,
                camera_to_worlds=poses,
                width=int(config.width),
                height=int(config.height),
                fov_deg=float(fov_deg),
                stokes_reference_axis=stokes_reference_axis,
            )
            if progress_callback is not None:
                progress_callback("rendering", {
                    "pass": "polar", "batch_size": len(poses), "variant": selected_variant,
                    "mode": batch_mode, "resident_scene": False,
                })
            image, timing = _render_scene(
                batch_scene,
                variant=selected_variant,
                spp=int(config.polar_spp),
            )
    # Everything below is host-side: splitting the film, saving products and
    # assembling manifests-ready results. It is hoisted into a closure so a
    # caller that wants to overlap it with the *next* batch's GPU render can
    # take the callable instead of the result (see ``defer``). The default
    # path calls it immediately, so behaviour is unchanged.
    def _finish() -> list[MultimodalRenderResult]:
        strips = split_stokes_heading_batch(
            image,
            batch_size=len(poses),
            width=int(config.width),
            height=int(config.height),
        )
        common_timing = dict(timing)
        common_timing.update({
            "spp": int(config.polar_spp),
            "effective_spp": int(config.polar_spp),
            "batch_size": len(poses),
            "batch_render_s": float(timing.get("render_s", 0.0)),
            "batch_total_s": float(timing.get("total_s", 0.0)),
            "batch_mode": batch_mode,
            "resident_batch_scene": bool(use_resident_batch_scene),
            "resident_batch_scene_ref": str(batch_scene) if use_resident_batch_scene else None,
            "stokes_reference_axis": list(stokes_reference_axis),
            "stokes_basis": "world_gravity_y_v1",
            "scene": str(base_scene),
        })
        outputs: list[MultimodalRenderResult] = []
        array_names = {
            "polar_rgb_preview": "rgb",
            "dop": "dop",
            "aolp": "aolp_deg",
            "s1": "s1_l",
            "s2": "s2_l",
            "s1_over_s0": "s1_over_s0",
            "s2_over_s0": "s2_over_s0",
        }
        # Saving is pure host-side work (the strips are already numpy) while the GPU
        # sits idle waiting for the next batch, so at K=12 the serial loop below was
        # the second-largest term in the batch cycle. numpy, PIL and zlib all drop
        # the GIL, so a thread pool converts it to wall time / ~3. Only the save
        # itself is parallel -- result assembly stays serial and ordered so the
        # emitted outputs are byte-identical to the serial path.
        saved = _save_polarization_products_batch(
            strips,
            destinations,
            requested_set,
            visualization_policy=config.polar_visualization_policy,
            progress_callback=progress_callback,
            progress_extra={"pass": "polar", "batch_size": len(poses), "mode": batch_mode},
        )
        for batch_index, (pose, destination, strip) in enumerate(zip(poses, destinations, strips)):
            summary, arrays = saved[batch_index]
            summary.update({
                "schema": "opticalnav.stokes_rgb_12.minimal_f16.v2",
                "polar_color_mode": config.polar_color_mode,
                "stokes_channel_order": ["S0_RGB", "S1_RGB", "S2_RGB", "S3_RGB"],
                "stokes_basis": "world_gravity_y_v1",
                "stokes_reference_axis": list(stokes_reference_axis),
            })
            quality_summary = _polar_quality_summary(summary, config)
            item_timing = {
                **common_timing,
                "batch_index": batch_index,
                "render_s": float(timing.get("render_s", 0.0)) / len(poses),
                "total_s": float(timing.get("total_s", 0.0)) / len(poses),
                "stokes_npz_write_s": summary["stokes_npz_write_s"],
                "stokes_npz_bytes": summary["stokes_npz_bytes"],
                "preview_write_s": summary["preview_write_s"],
                "polar_postprocess_s": summary["polar_postprocess_s"],
            }
            base_metadata = _branch_metadata(
                illumination_tag="active_camera_aligned" if assist_lights is not None else "ambient_room",
                scene_override=scene_override,
                extra={
                    "material_mode": "shared_material_policy",
                    "material_policy": "shared_with_rgb",
                    "polar_transport": config.polar_transport,
                    "polar_color_mode": config.polar_color_mode,
                    "stokes_schema": summary["schema"],
                    "stokes_channel_order": summary["stokes_channel_order"],
                    "stokes_basis": summary["stokes_basis"],
                    "nested_integrator": polar_nested,
                    "max_depth": polar_max_depth,
                    "polar_visualization_policy": config.polar_visualization_policy,
                    "stokes_preview_recipe": summary["stokes_preview_recipe"],
                    "derived_on_demand": list(summary["derived_on_demand"]),
                    "stokes_heading_batch": {
                        "batch_size": len(poses),
                        "batch_index": batch_index,
                        "mode": batch_mode,
                        "camera_aligned_light": assist_lights is not None,
                    },
                    **quality_summary,
                },
            )

            def _artifacts(modality: str) -> dict[str, Any]:
                artifacts: dict[str, Any] = {"stokes_npz": summary["outputs"]["stokes_npz"]}
                output_name = "rgb_preview" if modality == "polar_rgb_preview" else modality
                output = summary["outputs"].get(output_name)
                if output:
                    artifacts["png"] = output
                elif modality != "polar_rgb_preview":
                    artifacts["derived_on_demand"] = {
                        "source": summary["outputs"]["stokes_npz"],
                        "recipe": summary["stokes_preview_recipe"],
                        "modality": modality,
                    }
                return artifacts

            results: dict[str, ModalityResult] = {}
            for modality in requested:
                result_metadata = dict(base_metadata)
                if modality == "dop":
                    result_metadata["range"] = [0.0, 1.0]
                elif modality == "aolp":
                    result_metadata["range_degrees"] = [0.0, 180.0]
                elif modality in {"s1_over_s0", "s2_over_s0"}:
                    result_metadata["range"] = [-1.0, 1.0]
                elif modality == "s1":
                    result_metadata["scale_abs_p995"] = summary["s1_scale_abs_p995"]
                elif modality == "s2":
                    result_metadata["scale_abs_p995"] = summary["s2_scale_abs_p995"]
                array_name = array_names[modality]
                results[modality] = ModalityResult(
                    name=modality,
                    array=arrays[array_name],
                    raw_channels={"mask": arrays["mask"], array_name: arrays[array_name]},
                    metadata=result_metadata,
                    timing=dict(item_timing),
                    artifacts=_artifacts(modality),
                )
            outputs.append(MultimodalRenderResult(
                scene={
                    "source_scene": str(source_scene),
                    "workspace": str(destination),
                    "temporary_workspace": False,
                    "staged_scenes": {"polar": str(base_scene)},
                    "polarization_material_mode": "shared_material_policy",
                    "stokes_heading_batch": {
                        "batch_size": len(poses),
                        "batch_index": batch_index,
                        "mode": batch_mode,
                        "camera_aligned_light": assist_lights is not None,
                    },
                    "start_time": now_iso(),
                },
                camera={
                    "camera_to_world": pose.tolist(),
                    "fov_deg": float(fov_deg),
                    "convention": "cam-to-world, local -Z forward, local +Y up",
                },
                config=config,
                definitions=dict(MODALITY_DEFINITIONS),
                results=results,
                pass_records={
                    "polarization": {
                        **item_timing,
                        "task": "polar",
                        "mode": batch_mode,
                        "stokes_shape": list(strip.shape),
                        "polarization": summary,
                    },
                },
            ))
        return outputs

    if defer:
        return _finish
    return _finish()


def render_rgb(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(*args, modalities=["rgb"], **kwargs)


def render_depth(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(*args, modalities=["depth"], **kwargs)


def render_polarization(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(*args, modalities=["polar_rgb_preview", "s1_over_s0", "s2_over_s0", "dop", "aolp", "s1", "s2"], **kwargs)


def render_decomposition(*args, **kwargs) -> MultimodalRenderResult:
    return render_modalities(
        *args,
        modalities=["albedo", "direct_light_map", "indirect_light_map", "diffuse_map", "specular_map"],
        **kwargs,
    )
