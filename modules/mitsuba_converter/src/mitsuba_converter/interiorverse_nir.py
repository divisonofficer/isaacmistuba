"""2.5D pseudo-NIR augmentation for InteriorVerse G-buffers.

This module deliberately does not depend on Mitsuba or PyTorch.  NumPy is the
reference implementation; PyTorch is imported lazily only for CUDA shadow-map
construction when a CUDA device is requested by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2  # noqa: E402
import numpy as np

from .nir_reflectance import pseudo_nir_albedo


FORMULA_ID_V1 = "interiorverse_pseudo_nir_deferred_v1"
FORMULA_ID_V2 = "hybrid_rgb_transport_reuse_plus_visible_ss_one_bounce_v1"
PASSIVE_MODEL_MATERIAL_AWARE_V1 = "rgb_diffuse_log_shading_edge_aware_v1"
FRAME_SCHEMA_V1 = "robomituba.interiorverse_nir.frame.v1"
FRAME_SCHEMA_V2 = "robomituba.interiorverse_nir.frame.v2"
DATASET_SCHEMA_V1 = "robomituba.interiorverse_nir.dataset.v1"
DATASET_SCHEMA_V2 = "robomituba.interiorverse_nir.dataset.v2"
ACTIVE_FRAME_SCHEMA_V1 = "robomituba.interiorverse_active_nir.frame.v1"
ACTIVE_DATASET_SCHEMA_V1 = "robomituba.interiorverse_active_nir.dataset.v1"
# New callers deliberately receive v2.  v1 remains opt-in through
# ``transport_model='rgb_reused_v1'`` and is never rewritten in place.
FORMULA_ID = FORMULA_ID_V2
FRAME_SCHEMA = FRAME_SCHEMA_V2
DATASET_SCHEMA = DATASET_SCHEMA_V2
TRANSPORT_MODEL_RGB_REUSED_V1 = "rgb_reused_v1"
TRANSPORT_MODEL_SS1_V1 = "screen_space_one_bounce_v1"
TRANSPORT_MODELS = frozenset((TRANSPORT_MODEL_RGB_REUSED_V1, TRANSPORT_MODEL_SS1_V1))
HFOV_DEGREES = 85.0
SHADOW_MAP_SIZE = 512
LUMA = np.asarray([0.2126, 0.7152, 0.0722], np.float32)
OUTPUT_SUFFIXES = (
    "nir_albedo",
    "nir_passive",
    "nir_active_colocated",
    "nir_active_random",
)
SS1_OUTPUT_SUFFIXES = ("nir_indirect_ss1", "nir_ss1_confidence")
SS1_RAYS_PER_PIXEL = 16
SS1_STEPS_PER_RAY = 48
SS1_MAX_DISTANCE_M = 5.0
SOURCE_SUFFIXES = ("im", "mask", "albedo", "depth", "material", "normal")


@dataclass(frozen=True)
class FramePaths:
    scene: str
    frame: str
    source: Mapping[str, Path]


@dataclass(frozen=True)
class Light:
    position: np.ndarray
    direction: np.ndarray
    intensity: float = 1.0
    beam_degrees: float = 45.0
    cutoff_degrees: float = 52.0
    seed: int | None = None


@dataclass(frozen=True)
class CcsLdl3BarBank:
    """Camera-mounted three-bar 850 nm source, sampled as finite emitters.

    ``relative_flux_per_bar`` deliberately shares the legacy pseudo-NIR scale:
    it is not an absolute watt value.  The accompanying manufacturer prior is
    retained for later sensor calibration without pretending this G-buffer
    renderer is radiometrically calibrated.
    """
    samples: tuple[Light, ...]
    emitter_size_m: tuple[float, float] = (0.042, 0.0152)
    bar_count: int = 3
    radiant_flux_per_bar_w: float = 0.69
    relative_flux_per_bar: float = 1.0


@dataclass
class FrameData:
    image_rgb: np.ndarray
    albedo_rgb: np.ndarray
    depth_mm: np.ndarray
    normal: np.ndarray
    roughness: np.ndarray
    metallic: np.ndarray
    mask: np.ndarray
    valid: np.ndarray


def discover_frames(source_root: Path, scenes: Sequence[str] | None = None) -> list[FramePaths]:
    """Discover only complete six-file InteriorVerse frame groups."""
    source_root = Path(source_root)
    wanted = set(scenes or ())
    scene_dirs = sorted(path for path in source_root.iterdir() if path.is_dir())
    if wanted:
        found = {path.name for path in scene_dirs}
        missing = sorted(wanted - found)
        if missing:
            raise FileNotFoundError(f"unknown scene(s): {', '.join(missing)}")
        scene_dirs = [path for path in scene_dirs if path.name in wanted]
    frames: list[FramePaths] = []
    for scene_dir in scene_dirs:
        for image_path in sorted(scene_dir.glob("*_im.exr")):
            frame = image_path.name[: -len("_im.exr")]
            paths = {name: scene_dir / f"{frame}_{name}.exr" for name in SOURCE_SUFFIXES}
            missing = [str(path) for path in paths.values() if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"incomplete frame {scene_dir.name}/{frame}: {missing}")
            frames.append(FramePaths(scene=scene_dir.name, frame=frame, source=paths))
    return frames


def _read_exr(path: Path) -> np.ndarray:
    value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if value is None:
        raise ValueError(f"failed to read EXR: {path}")
    return np.asarray(value, np.float32)


def _rgb(value: np.ndarray, name: str) -> np.ndarray:
    if value.ndim != 3 or value.shape[2] < 3:
        raise ValueError(f"{name} must have at least 3 channels, got {value.shape}")
    return np.ascontiguousarray(value[..., :3][..., ::-1], dtype=np.float32)


def _scalar(value: np.ndarray, name: str, *, red_channel: bool = True) -> np.ndarray:
    if value.ndim == 2:
        return np.asarray(value, np.float32)
    if value.ndim == 3 and value.shape[2] >= 1:
        channel = 2 if red_channel and value.shape[2] >= 3 else 0
        return np.asarray(value[..., channel], np.float32)
    raise ValueError(f"{name} must be HxW or HxWxC, got {value.shape}")


def load_frame(paths: FramePaths) -> FrameData:
    """Load, BGR-to-RGB convert, and validate one InteriorVerse frame."""
    image = _rgb(_read_exr(paths.source["im"]), "im")
    albedo = _rgb(_read_exr(paths.source["albedo"]), "albedo")
    normal = _rgb(_read_exr(paths.source["normal"]), "normal")
    material = _rgb(_read_exr(paths.source["material"]), "material")
    depth = _scalar(_read_exr(paths.source["depth"]), "depth")
    mask_raw = _read_exr(paths.source["mask"])
    mask = _scalar(mask_raw, "mask", red_channel=False)
    shape = depth.shape
    named = {"im": image, "albedo": albedo, "normal": normal, "material": material, "mask": mask}
    for name, value in named.items():
        if value.shape[:2] != shape:
            raise ValueError(f"shape mismatch: depth={shape}, {name}={value.shape}")
    finite = (
        np.isfinite(depth)
        & np.isfinite(mask)
        & np.isfinite(image).all(axis=2)
        & np.isfinite(albedo).all(axis=2)
        & np.isfinite(normal).all(axis=2)
        & np.isfinite(material).all(axis=2)
    )
    normal_length = np.linalg.norm(normal, axis=2)
    valid = finite & (mask > 0.5) & (depth > 0.0) & (normal_length > 1e-6)
    safe_length = np.maximum(normal_length, 1e-8)
    normal = normal / safe_length[..., None]
    normal[~valid] = 0.0
    return FrameData(
        image_rgb=image,
        albedo_rgb=albedo,
        depth_mm=depth,
        normal=normal.astype(np.float32),
        roughness=np.clip(material[..., 0], 0.0, 1.0),
        metallic=np.clip(material[..., 1], 0.0, 1.0),
        mask=mask,
        valid=valid,
    )


def camera_intrinsics(width: int, height: int, hfov_degrees: float = HFOV_DEGREES) -> dict[str, float]:
    fx = (0.5 * width) / math.tan(math.radians(hfov_degrees) * 0.5)
    return {"fx": fx, "fy": fx, "cx": 0.5 * width, "cy": 0.5 * height}


def axial_depth_to_points(depth_mm: np.ndarray, hfov_degrees: float = HFOV_DEGREES) -> np.ndarray:
    """Restore OpenGL-camera points (x right, y up, z backward) from axial depth."""
    depth = np.asarray(depth_mm, np.float32) * np.float32(0.001)
    height, width = depth.shape
    intr = camera_intrinsics(width, height, hfov_degrees)
    u = np.arange(width, dtype=np.float32) + 0.5
    v = np.arange(height, dtype=np.float32) + 0.5
    x = (u[None, :] - intr["cx"]) / intr["fx"]
    y = -(v[:, None] - intr["cy"]) / intr["fy"]
    return np.stack((x * depth, y * depth, -depth), axis=2).astype(np.float32)


def passive_nir(
    image_rgb: np.ndarray,
    albedo_rgb: np.ndarray,
    nir_albedo: np.ndarray,
    valid: np.ndarray,
    *,
    floor: float = 0.02,
    percentile: float = 99.5,
) -> tuple[np.ndarray, np.ndarray, float]:
    image_y = np.asarray(image_rgb, np.float32) @ LUMA
    albedo_y = np.asarray(albedo_rgb, np.float32) @ LUMA
    shading = image_y / np.maximum(albedo_y, np.float32(floor))
    finite_valid = valid & np.isfinite(shading)
    cap = float(np.percentile(shading[finite_valid], percentile)) if finite_valid.any() else 0.0
    shading = np.clip(np.nan_to_num(shading, nan=0.0, posinf=cap, neginf=0.0), 0.0, cap)
    result = np.asarray(nir_albedo, np.float32) * shading
    result[~valid] = 0.0
    return result.astype(np.float32), shading.astype(np.float32), cap


def material_aware_passive_nir(
    image_rgb: np.ndarray,
    albedo_rgb: np.ndarray,
    nir_albedo: np.ndarray,
    roughness: np.ndarray,
    metallic: np.ndarray,
    normal: np.ndarray,
    depth_mm: np.ndarray,
    valid: np.ndarray,
    *,
    diffuse_floor: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    """Estimate passive NIR from robust diffuse-only RGB shading.

    A single InteriorVerse G-buffer cannot separate specular illumination
    exactly.  This estimator explicitly rejects glossy/metallic pixels while
    estimating log shading, then propagates a depth/normal-aware low-frequency
    field into those pixels.  It avoids the quantized ratio bands produced by
    applying ``RGB / albedo`` independently at every pixel.
    """
    image_y = np.asarray(image_rgb, np.float32) @ LUMA
    diffuse_rgb = (1.0 - np.asarray(metallic, np.float32)[..., None]) * np.asarray(albedo_rgb, np.float32)
    diffuse_y = diffuse_rgb @ LUMA
    rough = np.asarray(roughness, np.float32)
    metal = np.asarray(metallic, np.float32)
    finite = np.isfinite(image_y) & np.isfinite(diffuse_y) & np.isfinite(rough) & np.isfinite(metal)
    diffuse_valid = (np.asarray(valid, bool) & finite & (metal < 0.2)
                     & (rough > 0.25) & (diffuse_y > diffuse_floor))
    raw_log = np.log(np.maximum(image_y, 1e-4)) - np.log(np.maximum(diffuse_y, 1e-4))
    if diffuse_valid.any():
        lo, hi = np.percentile(raw_log[diffuse_valid], [0.5, 99.5])
        raw_log = np.clip(raw_log, lo, hi)
        global_log = float(np.median(raw_log[diffuse_valid]))
    else:
        lo = hi = global_log = 0.0

    # A large normalized blur supplies a stable global/SH-like fill for
    # metallic and specular regions.  It is only a fill field, not a claim of
    # per-pixel illumination recovery.
    weight = diffuse_valid.astype(np.float32)
    numerator = cv2.GaussianBlur(raw_log * weight, (0, 0), 24.0)
    denominator = cv2.GaussianBlur(weight, (0, 0), 24.0)
    smooth = numerator / np.maximum(denominator, 1e-5)
    smooth[denominator < 1e-3] = global_log

    # Five-by-five joint bilateral refinement preserves G-buffer depth and
    # normal boundaries while smoothing raw ratio steps on diffuse surfaces.
    h, w = raw_log.shape
    pad_log = np.pad(raw_log, 2, mode="edge")
    pad_weight = np.pad(weight, 2, mode="constant")
    safe_depth = np.nan_to_num(np.asarray(depth_mm, np.float32) * 0.001, nan=0.0, posinf=0.0, neginf=0.0)
    pad_depth = np.pad(safe_depth, 2, mode="edge")
    pad_normal = np.pad(_normalize(normal), ((2, 2), (2, 2), (0, 0)), mode="edge")
    depth = safe_depth
    n = _normalize(normal)
    local_num = np.zeros((h, w), np.float32)
    local_den = np.zeros((h, w), np.float32)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            ys, xs = slice(2 + dy, 2 + dy + h), slice(2 + dx, 2 + dx + w)
            neighbor_depth = pad_depth[ys, xs]
            neighbor_normal = pad_normal[ys, xs]
            spatial = math.exp(-(dx * dx + dy * dy) / 4.0)
            depth_sigma = np.maximum(0.03, 0.05 * np.maximum(depth, 0.2))
            depth_weight = np.exp(-0.5 * ((neighbor_depth - depth) / depth_sigma) ** 2)
            normal_weight = np.exp((np.clip(np.sum(n * neighbor_normal, axis=2), -1.0, 1.0) - 1.0) / 0.12)
            joint = np.float32(spatial) * depth_weight * normal_weight * pad_weight[ys, xs]
            local_num += joint * pad_log[ys, xs]
            local_den += joint
    local = local_num / np.maximum(local_den, 1e-5)
    # Use the local estimate only where it has actual diffuse support.
    blend = np.clip(local_den / 0.75, 0.0, 1.0)
    log_shading = blend * local + (1.0 - blend) * smooth
    shading = np.exp(np.clip(log_shading, -8.0, 8.0)).astype(np.float32)
    passive = np.asarray(nir_albedo, np.float32) * shading
    passive[~valid] = 0.0
    confidence = np.where(diffuse_valid, 1.0, np.clip(local_den / 0.75, 0.0, 0.7)).astype(np.float32)
    confidence[~valid] = 0.0
    return np.maximum(passive, 0.0).astype(np.float32), shading, confidence, {
        "diffuse_valid_fraction": float(diffuse_valid[valid].mean()) if np.any(valid) else 0.0,
        "log_shading_p005": float(lo), "log_shading_p995": float(hi),
    }


def _ss1_directions(normal: np.ndarray, *, seed: int, sample_index: int) -> np.ndarray:
    """Deterministic cosine-hemisphere directions in the local shading frame."""
    n = _normalize(normal)
    height, width = n.shape[:2]
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    # Cranley-Patterson rotated low-discrepancy samples, deterministically
    # decorrelated per pixel/frame seed without relying on global RNG state.
    phase = np.mod(np.sin((xx * 12.9898 + yy * 78.233 + seed * 0.0001)) * 43758.5453, 1.0)
    u1 = np.mod(phase + (sample_index + 0.5) * 0.61803398875, 1.0)
    u2 = np.mod(phase * 0.754877666 + (sample_index + 0.5) / SS1_RAYS_PER_PIXEL, 1.0)
    radius = np.sqrt(np.clip(u1, 0.0, 1.0))
    phi = np.float32(2.0 * math.pi) * u2
    local_x, local_y = radius * np.cos(phi), radius * np.sin(phi)
    local_z = np.sqrt(np.maximum(1.0 - u1, 0.0))
    ref = np.zeros_like(n)
    ref[..., 1] = 1.0
    alternate = np.zeros_like(n)
    alternate[..., 0] = 1.0
    ref[np.abs(n[..., 1]) > 0.95] = alternate[np.abs(n[..., 1]) > 0.95]
    tangent = _normalize(np.cross(ref, n))
    bitangent = _normalize(np.cross(n, tangent))
    return _normalize(tangent * local_x[..., None] + bitangent * local_y[..., None] + n * local_z[..., None])


def _screen_space_one_bounce_numpy(
    points: np.ndarray, normal: np.ndarray, passive: np.ndarray, nir_albedo: np.ndarray,
    metallic: np.ndarray, valid: np.ndarray, *, seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Reference visible-only 2.5D one-bounce tracer used by tests/CPU fallback."""
    h, w = valid.shape
    intr = camera_intrinsics(w, h)
    depth = -np.asarray(points[..., 2], np.float32)
    diffuse_rho = np.maximum(1.0 - np.asarray(metallic, np.float32), 0.0) * np.asarray(nir_albedo, np.float32)
    source_radiance = np.asarray(passive, np.float32) * np.maximum(1.0 - np.asarray(metallic, np.float32), 0.0)
    contribution = np.zeros((h, w), np.float32)
    hits = np.zeros((h, w), np.float32)
    yy, xx = np.mgrid[:h, :w]
    for sample in range(SS1_RAYS_PER_PIXEL):
        direction = _ss1_directions(normal, seed=seed, sample_index=sample)
        found = np.zeros((h, w), bool)
        sample_radiance = np.zeros((h, w), np.float32)
        for step in range(1, SS1_STEPS_PER_RAY + 1):
            distance = np.float32(SS1_MAX_DISTANCE_M * step / SS1_STEPS_PER_RAY)
            ray = points + normal * 0.01 + direction * distance
            ray_depth = -ray[..., 2]
            in_front = ray_depth > 1e-4
            u = np.rint(ray[..., 0] * intr["fx"] / np.maximum(ray_depth, 1e-6) + intr["cx"] - 0.5).astype(np.int32)
            v = np.rint(intr["cy"] - ray[..., 1] * intr["fy"] / np.maximum(ray_depth, 1e-6) - 0.5).astype(np.int32)
            inside = in_front & (u >= 0) & (u < w) & (v >= 0) & (v < h)
            uc, vc = np.clip(u, 0, w - 1), np.clip(v, 0, h - 1)
            hit_depth = depth[vc, uc]
            hit_valid = valid[vc, uc]
            thickness = np.maximum(0.02, hit_depth * 0.01)
            # The ray must have crossed the camera-visible surface.  A small
            # screen-space offset rejects its own G-buffer source texel.
            displaced = (np.abs(uc - xx) > 1) | (np.abs(vc - yy) > 1)
            hit = inside & displaced & hit_valid & (np.abs(ray_depth - hit_depth) <= thickness)
            accepted = hit & ~found
            if accepted.any():
                sample_radiance[accepted] = source_radiance[vc[accepted], uc[accepted]]
                found |= accepted
        contribution += sample_radiance
        hits += found.astype(np.float32)
    confidence = hits / np.float32(SS1_RAYS_PER_PIXEL)
    correction = diffuse_rho * contribution / np.float32(SS1_RAYS_PER_PIXEL)
    correction = np.nan_to_num(correction, nan=0.0, posinf=0.0, neginf=0.0)
    correction[~valid] = 0.0
    confidence[~valid] = 0.0
    return np.maximum(correction, 0.0).astype(np.float32), np.clip(confidence, 0.0, 1.0).astype(np.float32)


def _screen_space_one_bounce_torch(
    points: np.ndarray, normal: np.ndarray, passive: np.ndarray, nir_albedo: np.ndarray,
    metallic: np.ndarray, valid: np.ndarray, *, seed: int, device: str,
) -> tuple[np.ndarray, np.ndarray]:
    """CUDA production implementation of the same deterministic SS1 contract."""
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError("screen-space NIR SS1 requires PyTorch CUDA") from exc
    if not torch.cuda.is_available() or not str(device).startswith("cuda"):
        raise RuntimeError("screen-space NIR SS1 CUDA path requires a CUDA device")
    with torch.inference_mode():
        dev = torch.device(device)
        p = torch.as_tensor(points, device=dev, dtype=torch.float32)
        n = torch.as_tensor(normal, device=dev, dtype=torch.float32)
        base = torch.as_tensor(passive, device=dev, dtype=torch.float32)
        rho = torch.as_tensor(nir_albedo, device=dev, dtype=torch.float32)
        metal = torch.as_tensor(metallic, device=dev, dtype=torch.float32)
        valid_t = torch.as_tensor(valid, device=dev, dtype=torch.bool)
        h, w = valid.shape
        fx = 0.5 * w / math.tan(math.radians(HFOV_DEGREES) * 0.5)
        yy, xx = torch.meshgrid(torch.arange(h, device=dev), torch.arange(w, device=dev), indexing="ij")
        xxf, yyf = xx.float(), yy.float()
        n = n / torch.clamp(torch.linalg.vector_norm(n, dim=-1, keepdim=True), min=1e-8)
        reference = torch.zeros_like(n); reference[..., 1] = 1.0
        alternate = torch.zeros_like(n); alternate[..., 0] = 1.0
        reference = torch.where((n[..., 1].abs() > 0.95)[..., None], alternate, reference)
        tangent = torch.linalg.cross(reference, n)
        tangent = tangent / torch.clamp(torch.linalg.vector_norm(tangent, dim=-1, keepdim=True), min=1e-8)
        bitangent = torch.linalg.cross(n, tangent)
        bitangent = bitangent / torch.clamp(torch.linalg.vector_norm(bitangent, dim=-1, keepdim=True), min=1e-8)
        phase = torch.frac(torch.sin(xxf * 12.9898 + yyf * 78.233 + seed * 0.0001) * 43758.5453)
        depth = -p[..., 2]
        diffuse_rho = (1.0 - metal).clamp_min(0.0) * rho
        source = base * (1.0 - metal).clamp_min(0.0)
        accumulated = torch.zeros((h, w), device=dev)
        hit_count = torch.zeros((h, w), device=dev)
        for sample in range(SS1_RAYS_PER_PIXEL):
            u1 = torch.frac(phase + (sample + 0.5) * 0.61803398875)
            u2 = torch.frac(phase * 0.754877666 + (sample + 0.5) / SS1_RAYS_PER_PIXEL)
            radius = torch.sqrt(u1.clamp(0.0, 1.0)); phi = 2.0 * math.pi * u2
            direction = tangent * (radius * torch.cos(phi))[..., None] + bitangent * (radius * torch.sin(phi))[..., None] + n * torch.sqrt((1.0 - u1).clamp_min(0.0))[..., None]
            found = torch.zeros((h, w), dtype=torch.bool, device=dev)
            sampled = torch.zeros((h, w), device=dev)
            for step in range(1, SS1_STEPS_PER_RAY + 1):
                distance = SS1_MAX_DISTANCE_M * step / SS1_STEPS_PER_RAY
                ray = p + n * 0.01 + direction * distance
                ray_depth = -ray[..., 2]
                u = torch.round(ray[..., 0] * fx / ray_depth.clamp_min(1e-6) + 0.5 * w - 0.5).long()
                v = torch.round(0.5 * h - ray[..., 1] * fx / ray_depth.clamp_min(1e-6) - 0.5).long()
                inside = (ray_depth > 1e-4) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
                uc, vc = u.clamp(0, w - 1), v.clamp(0, h - 1)
                source_depth, source_valid = depth[vc, uc], valid_t[vc, uc]
                displaced = ((uc - xx).abs() > 1) | ((vc - yy).abs() > 1)
                thickness = torch.maximum(torch.full_like(source_depth, 0.02), source_depth * 0.01)
                hit = inside & displaced & source_valid & ((ray_depth - source_depth).abs() <= thickness)
                accepted = hit & ~found
                sampled = torch.where(accepted, source[vc, uc], sampled)
                found |= accepted
            accumulated += sampled
            hit_count += found.float()
        correction = torch.nan_to_num(diffuse_rho * accumulated / SS1_RAYS_PER_PIXEL, nan=0.0, posinf=0.0, neginf=0.0)
        confidence = (hit_count / SS1_RAYS_PER_PIXEL).clamp(0.0, 1.0)
        correction = torch.where(valid_t, correction, torch.zeros_like(correction))
        confidence = torch.where(valid_t, confidence, torch.zeros_like(confidence))
        return correction.cpu().numpy().astype(np.float32), confidence.cpu().numpy().astype(np.float32)


def screen_space_one_bounce_nir(
    points: np.ndarray, normal: np.ndarray, passive: np.ndarray, nir_albedo: np.ndarray,
    metallic: np.ndarray, valid: np.ndarray, *, seed: int, device: str = "cpu",
) -> tuple[np.ndarray, np.ndarray]:
    """Visible-G-buffer-only diffuse SS1 correction and confidence fraction."""
    if str(device).startswith("cuda"):
        return _screen_space_one_bounce_torch(points, normal, passive, nir_albedo, metallic, valid, seed=seed, device=device)
    return _screen_space_one_bounce_numpy(points, normal, passive, nir_albedo, metallic, valid, seed=seed)


def stable_random_light(seed: int, scene: str, frame: str, target: np.ndarray) -> Light:
    digest = hashlib.sha256(f"{seed}/{scene}/{frame}".encode("utf-8")).digest()
    frame_seed = int.from_bytes(digest[:8], "big", signed=False)
    rng = np.random.default_rng(frame_seed)
    radius = math.sqrt(0.5**2 + float(rng.random()) * (1.5**2 - 0.5**2))
    theta = 2.0 * math.pi * float(rng.random())
    position = np.asarray([radius * math.cos(theta), radius * math.sin(theta), 0.0], np.float32)
    direction = _normalize(np.asarray(target, np.float32) - position)
    return Light(position=position, direction=direction, seed=frame_seed)


def colocated_light(target: np.ndarray) -> Light:
    position = np.asarray([0.0, -0.10, 0.0], np.float32)
    return Light(position=position, direction=_normalize(np.asarray(target, np.float32) - position))


def ccs_ldl_3bar_bank(
    target: np.ndarray,
    *,
    mount_position: Sequence[float] = (0.0, -0.10, 0.0),
    samples_per_bar: int = 3,
    relative_flux_per_bar: float = 1.0,
) -> CcsLdl3BarBank:
    """Build an end-to-end 126 x 15.2 mm CCS LDL-42X15IR2-850 bank.

    The long side lies horizontally in the camera frame.  Each bar is sampled
    along that long side, retaining front-only Lambertian emission in
    :func:`ccs_ldl_3bar_direct`.
    """
    if samples_per_bar < 1:
        raise ValueError("samples_per_bar must be positive")
    center = np.asarray(mount_position, np.float32)
    forward = _normalize(np.asarray(target, np.float32) - center)
    camera_up = np.asarray([0.0, 1.0, 0.0], np.float32)
    if abs(float(np.dot(forward, camera_up))) > 0.98:
        camera_up = np.asarray([1.0, 0.0, 0.0], np.float32)
    right = _normalize(np.cross(forward, camera_up))
    samples: list[Light] = []
    # 42 mm long bars are arranged end-to-end; their centers are 42 mm apart.
    for bar_index in (-1, 0, 1):
        bar_center = center + right * np.float32(bar_index * 0.042)
        for sample_index in range(samples_per_bar):
            local = ((sample_index + 0.5) / samples_per_bar - 0.5) * 0.042
            samples.append(Light(
                position=(bar_center + right * np.float32(local)).astype(np.float32),
                direction=forward.astype(np.float32),
                intensity=float(relative_flux_per_bar) / samples_per_bar,
                # Visibility needs a finite projection cone; 85 degrees is an
                # approximation to the physical front hemisphere.
                beam_degrees=85.0,
                cutoff_degrees=85.0,
            ))
    return CcsLdl3BarBank(
        samples=tuple(samples), relative_flux_per_bar=float(relative_flux_per_bar),
    )


def visible_point_center(points: np.ndarray, valid: np.ndarray) -> np.ndarray:
    selected = np.asarray(points, np.float32)[valid]
    if not len(selected):
        return np.asarray([0.0, 0.0, -1.0], np.float32)
    return np.median(selected, axis=0).astype(np.float32)


def _normalize(value: np.ndarray, axis: int = -1) -> np.ndarray:
    value = np.nan_to_num(np.asarray(value, np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    return value / np.maximum(np.linalg.norm(value, axis=axis, keepdims=True), np.float32(1e-8))


def _light_projection(points: np.ndarray, light: Light) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    forward = _normalize(light.direction)
    up_hint = np.asarray([0.0, 1.0, 0.0], np.float32)
    if abs(float(np.dot(forward, up_hint))) > 0.98:
        up_hint = np.asarray([1.0, 0.0, 0.0], np.float32)
    right = _normalize(np.cross(forward, up_hint))
    up = _normalize(np.cross(right, forward))
    relative = np.asarray(points, np.float32) - light.position
    z = relative @ forward
    tan_cutoff = math.tan(math.radians(light.cutoff_degrees))
    x_ndc = (relative @ right) / np.maximum(z * tan_cutoff, 1e-8)
    y_ndc = (relative @ up) / np.maximum(z * tan_cutoff, 1e-8)
    distance = np.linalg.norm(relative, axis=1)
    inside = (z > 0.0) & (np.abs(x_ndc) <= 1.0) & (np.abs(y_ndc) <= 1.0)
    return x_ndc, y_ndc, distance, inside


def shadow_visibility(
    points: np.ndarray,
    valid: np.ndarray,
    light: Light,
    *,
    map_size: int = SHADOW_MAP_SIZE,
    device: str = "cpu",
) -> np.ndarray:
    """Approximate visibility by point-splat shadow map and 3x3 PCF."""
    shape = valid.shape
    flat_valid = valid.reshape(-1)
    result = np.zeros(flat_valid.shape, np.float32)
    if not flat_valid.any():
        return result.reshape(shape)
    cloud = np.asarray(points, np.float32).reshape(-1, 3)[flat_valid]
    x_ndc, y_ndc, distance, inside = _light_projection(cloud, light)
    local_visibility = np.zeros(len(cloud), np.float32)
    if inside.any():
        px = np.clip(((x_ndc + 1.0) * 0.5 * map_size).astype(np.int64), 0, map_size - 1)
        py = np.clip(((1.0 - y_ndc) * 0.5 * map_size).astype(np.int64), 0, map_size - 1)
        if device.startswith("cuda"):
            local_visibility = _shadow_visibility_torch(px, py, distance, inside, map_size, device)
        else:
            shadow = np.full(map_size * map_size, np.inf, np.float32)
            indices = py[inside] * map_size + px[inside]
            np.minimum.at(shadow, indices, distance[inside])
            shadow = shadow.reshape(map_size, map_size)
            bias = np.maximum(0.01, distance * 0.01)
            samples = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    sx = np.clip(px + dx, 0, map_size - 1)
                    sy = np.clip(py + dy, 0, map_size - 1)
                    samples.append(distance <= shadow[sy, sx] + bias)
            local_visibility = np.mean(np.stack(samples, axis=0), axis=0, dtype=np.float32)
            local_visibility[~inside] = 0.0
    result[flat_valid] = local_visibility
    return result.reshape(shape)


def _shadow_visibility_torch(
    px: np.ndarray,
    py: np.ndarray,
    distance: np.ndarray,
    inside: np.ndarray,
    map_size: int,
    device: str,
) -> np.ndarray:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - depends on deployment
        raise RuntimeError("CUDA shadow maps require optional PyTorch") from exc
    with torch.inference_mode():
        tx = torch.as_tensor(px, device=device, dtype=torch.int64)
        ty = torch.as_tensor(py, device=device, dtype=torch.int64)
        td = torch.as_tensor(distance, device=device, dtype=torch.float32)
        ti = torch.as_tensor(inside, device=device, dtype=torch.bool)
        shadow = torch.full((map_size * map_size,), float("inf"), device=device)
        shadow.scatter_reduce_(0, (ty[ti] * map_size + tx[ti]), td[ti], reduce="amin", include_self=True)
        shadow = shadow.reshape(map_size, map_size)
        bias = torch.maximum(torch.tensor(0.01, device=device), td * 0.01)
        samples = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sx = torch.clamp(tx + dx, 0, map_size - 1)
                sy = torch.clamp(ty + dy, 0, map_size - 1)
                samples.append(td <= shadow[sy, sx] + bias)
        visibility = torch.stack(samples).float().mean(0)
        visibility[~ti] = 0.0
        return visibility.cpu().numpy().astype(np.float32)


def spot_profile(points: np.ndarray, light: Light) -> tuple[np.ndarray, np.ndarray]:
    relative = np.asarray(points, np.float32) - light.position
    distance = np.linalg.norm(relative, axis=2)
    direction = relative / np.maximum(distance[..., None], 1e-8)
    cosine = np.clip(direction @ _normalize(light.direction), -1.0, 1.0)
    angle = np.degrees(np.arccos(cosine))
    beam = float(light.beam_degrees)
    cutoff = float(light.cutoff_degrees)
    t = np.clip((cutoff - angle) / max(cutoff - beam, 1e-6), 0.0, 1.0)
    smooth = t * t * (3.0 - 2.0 * t)
    smooth[angle <= beam] = 1.0
    smooth[angle >= cutoff] = 0.0
    return smooth.astype(np.float32), distance.astype(np.float32)


def ggx_direct(
    points: np.ndarray,
    normal: np.ndarray,
    roughness: np.ndarray,
    metallic: np.ndarray,
    nir_albedo: np.ndarray,
    valid: np.ndarray,
    light: Light,
    visibility: np.ndarray | float = 1.0,
    emission_model: str = "spot",
) -> np.ndarray:
    """Scalar Cook-Torrance GGX direct response in the fixed NIR band."""
    p = np.asarray(points, np.float32)
    n = _normalize(normal)
    v = _normalize(-p)
    light_delta = light.position - p
    distance = np.linalg.norm(light_delta, axis=2)
    l = light_delta / np.maximum(distance[..., None], 1e-8)
    h = _normalize(v + l)
    ndotl = np.clip(np.sum(n * l, axis=2), 0.0, 1.0)
    ndotv = np.clip(np.sum(n * v, axis=2), 0.0, 1.0)
    ndoth = np.clip(np.sum(n * h, axis=2), 0.0, 1.0)
    vdoth = np.clip(np.sum(v * h, axis=2), 0.0, 1.0)
    perceptual = np.clip(np.asarray(roughness, np.float32), 0.0, 1.0)
    alpha = np.maximum(perceptual * perceptual, np.float32(1e-3))
    alpha2 = alpha * alpha
    denom = ndoth * ndoth * (alpha2 - 1.0) + 1.0
    distribution = alpha2 / np.maximum(np.pi * denom * denom, 1e-8)
    k = ((perceptual + 1.0) ** 2) / 8.0
    gv = ndotv / np.maximum(ndotv * (1.0 - k) + k, 1e-8)
    gl = ndotl / np.maximum(ndotl * (1.0 - k) + k, 1e-8)
    geometry = gv * gl
    metal = np.clip(np.asarray(metallic, np.float32), 0.0, 1.0)
    albedo = np.asarray(nir_albedo, np.float32)
    f0 = (1.0 - metal) * 0.04 + metal * albedo
    fresnel = f0 + (1.0 - f0) * ((1.0 - vdoth) ** 5)
    specular = distribution * geometry * fresnel / np.maximum(4.0 * ndotl * ndotv, 1e-8)
    diffuse = (1.0 - metal) * (1.0 - fresnel) * albedo / np.pi
    if emission_model == "spot":
        profile, _ = spot_profile(p, light)
    elif emission_model == "lambertian":
        # ``l`` points from receiver to emitter, so -l is the outgoing ray at
        # the emitting surface.  Reject its back side instead of imposing the
        # legacy 52 degree spot cutoff.
        profile = np.clip(np.sum((-l) * _normalize(light.direction), axis=2), 0.0, 1.0)
    else:
        raise ValueError(f"unsupported emission_model: {emission_model!r}")
    radiance = np.float32(light.intensity) * profile / np.maximum(distance * distance, 1e-8)
    result = (diffuse + specular) * radiance * ndotl * np.asarray(visibility, np.float32)
    result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    result[(~valid) | (ndotl <= 0.0) | (ndotv <= 0.0)] = 0.0
    return np.maximum(result, 0.0).astype(np.float32)


def ccs_ldl_3bar_direct(
    points: np.ndarray,
    normal: np.ndarray,
    roughness: np.ndarray,
    metallic: np.ndarray,
    nir_albedo: np.ndarray,
    valid: np.ndarray,
    bank: CcsLdl3BarBank,
    *,
    shadow_map_size: int = SHADOW_MAP_SIZE,
    shadow_device: str = "cpu",
    visibility_mode: str = "bank_center",
    geometry_mode: str = "far_field_centroid",
    denoise_direct: bool = True,
    angular_model: str = "spot",
) -> tuple[np.ndarray, dict[str, Any]]:
    """Accumulate finite-sample direct response for the three physical bars."""
    if visibility_mode not in {"bank_center", "per_sample"}:
        raise ValueError(f"unsupported visibility_mode: {visibility_mode!r}")
    if geometry_mode not in {"far_field_centroid", "quadrature"}:
        raise ValueError(f"unsupported geometry_mode: {geometry_mode!r}")
    if angular_model not in {"spot", "lambertian"}:
        raise ValueError(f"unsupported angular_model: {angular_model!r}")
    result = np.zeros(np.asarray(valid).shape, np.float32)
    visibility_means: list[float] = []
    center = np.mean(np.stack([light.position for light in bank.samples]), axis=0).astype(np.float32)
    center_direction = _normalize(np.mean(np.stack([light.direction for light in bank.samples]), axis=0))
    projection_beam, projection_cutoff = ((45.0, 52.0) if angular_model == "spot" else (85.0, 85.0))
    center_light = Light(center, center_direction, beam_degrees=projection_beam, cutoff_degrees=projection_cutoff)
    center_visibility: np.ndarray | None = None
    if visibility_mode == "bank_center":
        center_visibility = shadow_visibility(
            points, valid, center_light, map_size=shadow_map_size, device=shadow_device,
        )
    samples: Sequence[Light]
    if geometry_mode == "far_field_centroid":
        # At normal InteriorVerse ranges the 126 mm bank subtends little solid
        # angle.  A centroid avoids amplifying G-buffer facet discontinuities;
        # retain quadrature for dedicated <0.5 m experiments.
        samples = (Light(center, center_direction, intensity=bank.relative_flux_per_bar * bank.bar_count,
                         beam_degrees=projection_beam, cutoff_degrees=projection_cutoff),)
    else:
        samples = bank.samples
    for light in samples:
        visibility = center_visibility if center_visibility is not None else shadow_visibility(
            points, valid, light, map_size=shadow_map_size, device=shadow_device,
        )
        result += ggx_direct(
            points, normal, roughness, metallic, nir_albedo, valid, light,
            visibility, emission_model=angular_model,
        )
        selected = visibility[valid]
        visibility_means.append(float(selected.mean()) if len(selected) else 0.0)
    if denoise_direct:
        result = _depth_aware_log_smooth(result, depth_mm=-np.asarray(points, np.float32)[..., 2] * 1000.0, valid=valid)
    metadata = {
        "model": f"ccs_ldl_42x15ir2_850_three_bar_{angular_model}_v1",
        "manufacturer": "CCS",
        "model_number": "LDL-42X15IR2-850",
        "emitting_size_per_bar_m": list(bank.emitter_size_m),
        "arrangement": "three 42 mm bars end-to-end; total emitting extent 126 x 15.2 mm",
        "sample_count": len(samples),
        "geometry_mode": geometry_mode,
        "angular_model": angular_model,
        "angular_profile": (
            "provisional_spot_smoothstep: core=45 deg, cutoff=52 deg; replace with digitized CCS curve"
            if angular_model == "spot" else "front_only_lambertian"
        ),
        "relative_flux_per_bar": bank.relative_flux_per_bar,
        "radiant_flux_prior_per_bar_w": bank.radiant_flux_per_bar_w,
        "radiant_flux_prior_total_w": bank.radiant_flux_per_bar_w * bank.bar_count,
        "absolute_scale_status": "uncalibrated_pseudo_nir_prior",
        "visibility_mode": visibility_mode,
        "direct_denoise": "depth_aware_log_9x9" if denoise_direct else "disabled",
        "mean_sample_visibility": float(np.mean(visibility_means)) if visibility_means else 0.0,
    }
    return np.maximum(result, 0.0).astype(np.float32), metadata


def render_ccs_active_nir_frame(
    data: FrameData,
    *,
    relative_flux_per_bar: float = 12.0 / 6.9,
    samples_per_bar: int = 3,
    shadow_map_size: int = SHADOW_MAP_SIZE,
    shadow_device: str = "cpu",
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Render the material-aware passive and CCS 3-bar active NIR bundle."""
    points = axial_depth_to_points(data.depth_mm)
    points[~data.valid] = 0.0
    target = visible_point_center(points, data.valid)
    nir_albedo = pseudo_nir_albedo(data.albedo_rgb)
    nir_albedo[~data.valid] = 0.0
    passive, diffuse_shading, confidence, passive_metadata = material_aware_passive_nir(
        data.image_rgb, data.albedo_rgb, nir_albedo, data.roughness, data.metallic,
        data.normal, data.depth_mm, data.valid,
    )
    bank = ccs_ldl_3bar_bank(
        target, samples_per_bar=samples_per_bar,
        relative_flux_per_bar=relative_flux_per_bar,
    )
    direct, light_metadata = ccs_ldl_3bar_direct(
        points, data.normal, data.roughness, data.metallic, nir_albedo, data.valid,
        bank, shadow_map_size=shadow_map_size, shadow_device=shadow_device,
        visibility_mode="bank_center", geometry_mode="far_field_centroid", angular_model="spot",
    )
    diffuse_rgb = (1.0 - data.metallic[..., None]) * data.albedo_rgb
    reconstruction = diffuse_rgb * diffuse_shading[..., None]
    outputs = {
        "rgb_diffuse_shading": diffuse_shading,
        "rgb_diffuse_reconstruction": reconstruction.astype(np.float32),
        "nir_passive_diffuse": passive,
        "nir_passive_confidence": confidence,
        "nir_active_direct_ccs_3bar": direct,
        "nir_active_ccs_3bar": (passive + direct).astype(np.float32),
    }
    for value in outputs.values():
        value[~data.valid] = 0.0
    metadata = {
        "schema": ACTIVE_FRAME_SCHEMA_V1,
        "camera_target_m": target.tolist(),
        "passive": {"model": PASSIVE_MODEL_MATERIAL_AWARE_V1, **passive_metadata,
                    "confidence": _stats(confidence, data.valid)},
        "active_light": light_metadata,
        "statistics": {name: _stats(value if value.ndim == 2 else value @ LUMA, data.valid)
                       for name, value in outputs.items()},
    }
    return outputs, metadata


def _depth_aware_log_smooth(value: np.ndarray, *, depth_mm: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Suppress per-triangle direct-light banding without crossing depth edges."""
    source = np.log1p(np.maximum(np.asarray(value, np.float32), 0.0))
    valid_f = np.asarray(valid, np.float32)
    h, w = source.shape
    radius = 4
    pad_value = np.pad(source, radius, mode="edge")
    pad_valid = np.pad(valid_f, radius, mode="constant")
    depth = np.asarray(depth_mm, np.float32) * 0.001
    pad_depth = np.pad(depth, radius, mode="edge")
    numerator = np.zeros((h, w), np.float32)
    denominator = np.zeros((h, w), np.float32)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            ys, xs = slice(radius + dy, radius + dy + h), slice(radius + dx, radius + dx + w)
            neighbor_depth = pad_depth[ys, xs]
            spatial = math.exp(-(dx * dx + dy * dy) / 12.0)
            sigma = np.maximum(0.025, 0.03 * np.maximum(depth, 0.2))
            joint = np.float32(spatial) * np.exp(-0.5 * ((neighbor_depth - depth) / sigma) ** 2) * pad_valid[ys, xs]
            numerator += joint * pad_value[ys, xs]
            denominator += joint
    smoothed = np.expm1(numerator / np.maximum(denominator, 1e-6))
    smoothed[~np.asarray(valid, bool)] = 0.0
    return np.maximum(smoothed, 0.0).astype(np.float32)


def render_frame(
    data: FrameData,
    *,
    seed: int,
    scene: str,
    frame: str,
    shadow_device: str = "cpu",
    shadow_map_size: int = SHADOW_MAP_SIZE,
    transport_model: str = TRANSPORT_MODEL_SS1_V1,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    if transport_model not in TRANSPORT_MODELS:
        raise ValueError(f"unsupported transport model: {transport_model!r}")
    points = axial_depth_to_points(data.depth_mm)
    points[~data.valid] = 0.0
    target = visible_point_center(points, data.valid)
    nir_albedo = pseudo_nir_albedo(data.albedo_rgb)
    nir_albedo[~data.valid] = 0.0
    if transport_model == TRANSPORT_MODEL_RGB_REUSED_V1:
        passive, shading, cap = passive_nir(data.image_rgb, data.albedo_rgb, nir_albedo, data.valid)
        passive_confidence = np.asarray(data.valid, np.float32)
        passive_metadata: dict[str, Any] = {
            "model": "legacy_rgb_luma_albedo_ratio_v1", "albedo_floor": 0.02,
            "clip_percentile": 99.5, "clip_value": cap,
        }
    else:
        passive, shading, passive_confidence, passive_metadata = material_aware_passive_nir(
            data.image_rgb, data.albedo_rgb, nir_albedo, data.roughness, data.metallic,
            data.normal, data.depth_mm, data.valid,
        )
    lights = {"colocated": colocated_light(target), "random": stable_random_light(seed, scene, frame, target)}
    outputs: dict[str, np.ndarray] = {"nir_albedo": nir_albedo}
    if transport_model == TRANSPORT_MODEL_SS1_V1:
        ss1_seed = int.from_bytes(hashlib.sha256(f"{seed}/{scene}/{frame}/ss1".encode()).digest()[:8], "big")
        correction, confidence = screen_space_one_bounce_nir(
            points, data.normal, passive, nir_albedo, data.metallic, data.valid,
            seed=ss1_seed, device=shadow_device,
        )
        passive = (passive + correction).astype(np.float32)
        outputs["nir_indirect_ss1"] = correction
        outputs["nir_ss1_confidence"] = confidence
    outputs["nir_passive"] = passive
    visibility_stats: dict[str, Any] = {}
    for name, light in lights.items():
        visibility = shadow_visibility(points, data.valid, light, map_size=shadow_map_size, device=shadow_device)
        direct = ggx_direct(
            points, data.normal, data.roughness, data.metallic, nir_albedo,
            data.valid, light, visibility,
        )
        outputs[f"nir_active_{name}"] = (passive + direct).astype(np.float32)
        values = visibility[data.valid]
        visibility_stats[name] = {
            "mean": float(values.mean()) if len(values) else 0.0,
            "occluded_fraction": float(np.mean(values < 0.5)) if len(values) else 0.0,
        }
    for value in outputs.values():
        value[~data.valid] = 0.0
    metadata = {
        "formula_id": FORMULA_ID_V2 if transport_model == TRANSPORT_MODEL_SS1_V1 else FORMULA_ID_V1,
        "transport_model": transport_model,
        "schema": FRAME_SCHEMA_V2 if transport_model == TRANSPORT_MODEL_SS1_V1 else FRAME_SCHEMA_V1,
        "camera": {
            "horizontal_fov_degrees": HFOV_DEGREES,
            "coordinates": "OpenGL camera: +x right, +y up, -z forward",
            "depth": "axial millimeters converted to meters",
            "intrinsics": camera_intrinsics(data.depth_mm.shape[1], data.depth_mm.shape[0]),
        },
        "passive": {"luma": LUMA.tolist(), **passive_metadata,
                    "confidence": _stats(passive_confidence, data.valid)},
        "transport_provenance": (
            {
                "id": FORMULA_ID_V2,
                "method": "visible_gbuffer_cosine_hemisphere_one_bounce",
                "base": "rho_nir * Y(I_rgb)/max(Y(R_rgb), 0.02)",
                "correction": "(1-metallic)*rho_nir*mean(hit_radiance)",
                "rays_per_pixel": SS1_RAYS_PER_PIXEL,
                "depth_tested_steps_per_ray": SS1_STEPS_PER_RAY,
                "max_range_m": SS1_MAX_DISTANCE_M,
                "visible_only_limitation": "off_screen_or_unresolved_rays_contribute_zero",
                "train_eligible": True,
                "default_training_weight": 1.0,
                "confidence": _stats(outputs["nir_ss1_confidence"], data.valid),
            }
            if transport_model == TRANSPORT_MODEL_SS1_V1 else {
                "id": FORMULA_ID_V1, "method": "rgb_transport_reuse_only", "train_eligible": True,
            }
        ),
        "ggx": {"alpha": "max(roughness^2, 1e-3)", "dielectric_f0": 0.04, "attenuation": "inverse_square"},
        "visibility": {
            "method": "visible_point_cloud_shadow_map_pcf",
            "map_size": shadow_map_size,
            "pcf": "3x3",
            "bias": "max(0.01 m, 0.01 * light_distance)",
            "device": shadow_device,
            "statistics": visibility_stats,
        },
        "lights": {name: _light_metadata(light) for name, light in lights.items()},
        "statistics": {
            "valid_pixels": int(data.valid.sum()),
            "total_pixels": int(data.valid.size),
            "valid_fraction": float(data.valid.mean()),
            "shading": _stats(shading, data.valid),
            "outputs": {name: _stats(value, data.valid) for name, value in outputs.items()},
        },
    }
    return outputs, metadata


def _light_metadata(light: Light) -> dict[str, Any]:
    return {
        "position_camera_m": np.asarray(light.position).tolist(),
        "direction_camera": np.asarray(light.direction).tolist(),
        "intensity": light.intensity,
        "beam_degrees": light.beam_degrees,
        "cutoff_degrees": light.cutoff_degrees,
        "seed": light.seed,
    }


def _stats(value: np.ndarray, valid: np.ndarray) -> dict[str, float | None]:
    selected = np.asarray(value, np.float32)[valid]
    selected = selected[np.isfinite(selected)]
    if not len(selected):
        return {name: None for name in ("min", "max", "mean", "p50", "p95", "p99_5")}
    q = np.percentile(selected, [50.0, 95.0, 99.5])
    return {
        "min": float(selected.min()), "max": float(selected.max()), "mean": float(selected.mean()),
        "p50": float(q[0]), "p95": float(q[1]), "p99_5": float(q[2]),
    }


def output_paths(output_root: Path, scene: str, frame: str, *, transport_model: str = TRANSPORT_MODEL_SS1_V1) -> dict[str, Path]:
    scene_dir = Path(output_root) / scene
    suffixes = OUTPUT_SUFFIXES + (SS1_OUTPUT_SUFFIXES if transport_model == TRANSPORT_MODEL_SS1_V1 else ())
    paths = {name: scene_dir / f"{frame}_{name}.exr" for name in suffixes if name != "nir_ss1_confidence"}
    if transport_model == TRANSPORT_MODEL_SS1_V1:
        paths["nir_ss1_confidence"] = scene_dir / f"{frame}_nir_ss1_confidence.png"
    paths["metadata"] = scene_dir / f"{frame}_nir_meta.json"
    return paths


def atomic_write_exr(path: Path, value: np.ndarray) -> None:
    """Write a linear HxW or HxWxC HALF EXR and atomically publish it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".exr", dir=str(path.parent))
    os.close(fd)
    try:
        options = [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF]
        if hasattr(cv2, "IMWRITE_EXR_COMPRESSION_ZIP"):
            options += [cv2.IMWRITE_EXR_COMPRESSION, cv2.IMWRITE_EXR_COMPRESSION_ZIP]
        ok = cv2.imwrite(temp_name, np.ascontiguousarray(value, np.float32), options)
        if not ok:
            raise OSError(f"OpenCV failed to write EXR: {path}")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def atomic_write_png16(path: Path, value: np.ndarray) -> None:
    """Write a [0,1] scalar PNG16 atomically for SS1 confidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".png", dir=str(path.parent))
    os.close(fd)
    try:
        encoded = np.rint(np.clip(np.asarray(value, np.float32), 0.0, 1.0) * 65535.0).astype(np.uint16)
        if not cv2.imwrite(temp_name, encoded, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
            raise OSError(f"OpenCV failed to write PNG: {path}")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def frame_is_complete(output_root: Path, scene: str, frame: str) -> bool:
    try:
        metadata_path = output_paths(output_root, scene, frame)["metadata"]
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        model = str(metadata.get("transport_model") or TRANSPORT_MODEL_RGB_REUSED_V1)
        schema = FRAME_SCHEMA_V2 if model == TRANSPORT_MODEL_SS1_V1 else FRAME_SCHEMA_V1
        if metadata.get("schema") != schema or metadata.get("complete") is not True:
            return False
        paths = output_paths(output_root, scene, frame, transport_model=model)
        expected_shape = tuple(metadata["shape"])
        for name, path in paths.items():
            if name == "metadata":
                continue
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None or image.shape[:2] != expected_shape or image.ndim != 2:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def write_frame(
    frame_paths: FramePaths,
    output_root: Path,
    outputs: Mapping[str, np.ndarray],
    metadata: Mapping[str, Any],
    source_root: Path,
) -> dict[str, Any]:
    model = str(metadata.get("transport_model") or TRANSPORT_MODEL_RGB_REUSED_V1)
    paths = output_paths(output_root, frame_paths.scene, frame_paths.frame, transport_model=model)
    for name, path in paths.items():
        if name == "metadata":
            continue
        if name == "nir_ss1_confidence":
            atomic_write_png16(path, outputs[name])
        else:
            atomic_write_exr(path, outputs[name])
    relative_sources = {name: str(path.relative_to(source_root)) for name, path in frame_paths.source.items()}
    relative_outputs = {name: str(path.relative_to(output_root)) for name, path in paths.items() if name != "metadata"}
    payload = {
        "schema": FRAME_SCHEMA_V2 if model == TRANSPORT_MODEL_SS1_V1 else FRAME_SCHEMA_V1,
        "complete": True,
        "scene": frame_paths.scene,
        "frame": frame_paths.frame,
        "shape": list(next(iter(outputs.values())).shape),
        "source": relative_sources,
        "outputs": relative_outputs,
        "output_encoding": "linear single-channel IEEE 754 binary16 OpenEXR; nir_ss1_confidence is [0,1] PNG16; invalid pixels are zero; HDR is unclipped",
        **dict(metadata),
    }
    atomic_write_json(paths["metadata"], payload)
    return payload


def source_inventory(frames: Sequence[FramePaths], source_root: Path) -> list[dict[str, Any]]:
    unique = sorted({path for frame in frames for path in frame.source.values()})
    result = []
    for path in unique:
        stat = path.stat()
        result.append({"path": str(path.relative_to(source_root)), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return result


def verify_source_inventory(inventory: Sequence[Mapping[str, Any]], source_root: Path) -> list[str]:
    changed = []
    for item in inventory:
        path = Path(source_root) / str(item["path"])
        try:
            stat = path.stat()
        except FileNotFoundError:
            changed.append(str(item["path"]))
            continue
        if stat.st_size != item["size"] or stat.st_mtime_ns != item["mtime_ns"]:
            changed.append(str(item["path"]))
    return changed
