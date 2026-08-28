"""Contracts shared by the Blender RGB/active-NIR dataset pipeline.

This module is deliberately renderer-independent and importable both from the
normal Python applications and from the repository-bundled Blender Python.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np


MATERIAL_CONTRACT_SCHEMA = "robomituba.ir_principled_material_contract.v4"
MATERIAL_CONTRACT_VERSION = "blender42-principled-metallic-roughness-v4"
STAGE2_COMPILER_VERSION = "ir-principled-stage2-v12-render-visibility-contract"
METALLIC_CONTRACT_SCHEMA = "robomituba.metallic_contract.v2"
METALLIC_CONTRACT_FAMILIES = ("dielectric", "conductor", "coverage_mixed")
METALLIC_FAMILY_IDS = {"dielectric": 0, "conductor": 1, "coverage_mixed": 2}
PSEUDO_NIR_FORMULA_ID = "pseudo_max_complement_bt601_v1"
PSEUDO_NIR_WEIGHTS = np.asarray((0.229, 0.587, 0.114), dtype=np.float32)
LUMINANCE_WEIGHTS = np.asarray((0.2126, 0.7152, 0.0722), dtype=np.float32)

DEFAULT_BASE_COLOR = (0.5, 0.5, 0.5, 1.0)
DEFAULT_ROUGHNESS = 0.5
DEFAULT_METALLIC = 0.0
SURROGATE_MIN_ROUGHNESS = 0.35
DIFFUSE_SHADING_EPSILON = 1e-4

SUPPORTED_CHANNELS = ("base_color", "roughness", "metallic", "normal")
SEMANTIC_SURROGATES = frozenset({"window_glass", "mirror"})
INVALID_CHANNEL_SOURCES = frozenset({"missing", "unresolved", "invalid", "error"})


def normalize_legacy_metallic_scalar(value: float, *, threshold: float = 0.5) -> dict[str, Any]:
    """Normalize an uncontracted legacy scalar to physical binary metalness.

    This is intentionally limited to compatibility preparation of legacy
    materials.  Authored MetallicContractV2 values and spatial metallic maps
    must bypass it.  The returned metadata is persisted so the affected
    pixels can be excluded from source-valid evaluation.
    """
    scalar = float(value)
    if not math.isfinite(scalar):
        raise ValueError("legacy metallic scalar must be finite")
    if not 0.0 < threshold < 1.0:
        raise ValueError("metallic normalization threshold must be in (0, 1)")
    clamped = min(1.0, max(0.0, scalar))
    effective = 1.0 if clamped >= float(threshold) else 0.0
    changed = abs(scalar - effective) > 1e-6
    return {
        "policy": "legacy_uniform_fractional_snap_v1",
        "source_value": scalar,
        "clamped_value": clamped,
        "effective_value": effective,
        "threshold": float(threshold),
        "changed": changed,
        "reason": (
            "legacy_uniform_fractional_to_conductor"
            if changed and effective == 1.0
            else "legacy_uniform_fractional_to_dielectric"
            if changed
            else "already_binary"
        ),
    }


def pseudo_nir_albedo(rgb_linear: np.ndarray) -> np.ndarray:
    """Apply the dataset's deterministic pseudo-NIR convention to linear RGB."""
    rgb = np.clip(np.asarray(rgb_linear, dtype=np.float32), 0.0, 1.0)
    if rgb.shape[-1:] != (3,):
        raise ValueError(f"expected RGB in the last dimension, got {rgb.shape}")
    return (np.maximum(rgb, 1.0 - rgb) @ PSEUDO_NIR_WEIGHTS).astype(np.float32)


def matched_luminance_coefficients(rgb_linear: np.ndarray) -> dict[str, float]:
    """Return an affine luminance mapping matched to the primary pseudo-NIR moments."""
    rgb = np.asarray(rgb_linear, dtype=np.float32)
    primary = pseudo_nir_albedo(rgb).reshape(-1)
    luminance = (np.clip(rgb, 0.0, 1.0) @ LUMINANCE_WEIGHTS).reshape(-1)
    lum_std = float(luminance.std())
    scale = float(primary.std()) / lum_std if lum_std > 1e-8 else 0.0
    bias = float(primary.mean()) - scale * float(luminance.mean())
    return {"scale": scale, "bias": bias}


def apply_matched_luminance(rgb_linear: np.ndarray, *, scale: float, bias: float) -> np.ndarray:
    rgb = np.clip(np.asarray(rgb_linear, dtype=np.float32), 0.0, 1.0)
    return np.clip((rgb @ LUMINANCE_WEIGHTS) * float(scale) + float(bias), 0.0, 1.0).astype(np.float32)


def diffuse_shading_from_component(
    diffuse_component: np.ndarray, diffuse_reflectance: np.ndarray,
    *, epsilon: float = DIFFUSE_SHADING_EPSILON,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the dataset's RGB/NIR diffuse-shading decomposition contract."""
    component = np.asarray(diffuse_component, dtype=np.float32)
    reflectance = np.asarray(diffuse_reflectance, dtype=np.float32)
    if component.shape != reflectance.shape or component.shape[-1:] != (3,):
        raise ValueError(f"expected equal RGB tensors, got {component.shape} and {reflectance.shape}")
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    shading = component / np.maximum(reflectance, float(epsilon))
    valid = np.max(reflectance, axis=-1) > float(epsilon)
    return shading.astype(np.float32), valid


def diffuse_component_from_transport(
    diffuse_transport: np.ndarray, diffuse_reflectance: np.ndarray,
    *, epsilon: float = DIFFUSE_SHADING_EPSILON,
) -> tuple[np.ndarray, np.ndarray]:
    """Return v3 diffuse component C=R*T and its transport-valid mask.

    ``diffuse_transport`` is Cycles Diffuse Direct + Diffuse Indirect and
    ``diffuse_reflectance`` is Cycles Diffuse Color.  Unlike the legacy v2
    helper above this does not divide by reflectance.
    """
    transport = np.asarray(diffuse_transport, dtype=np.float32)
    reflectance = np.asarray(diffuse_reflectance, dtype=np.float32)
    if transport.shape != reflectance.shape or transport.shape[-1:] != (3,):
        raise ValueError(f"expected equal RGB tensors, got {transport.shape} and {reflectance.shape}")
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    component = transport * reflectance
    valid = np.isfinite(transport).all(axis=-1) & np.isfinite(reflectance).all(axis=-1)
    valid &= np.max(reflectance, axis=-1) > float(epsilon)
    return component.astype(np.float32), valid


def ceiling_softbox_specs(
    bounds_xy: tuple[float, float, float, float] | list[float], *,
    coverage_fraction: float = 0.12, min_size_m: float = 0.8, max_size_m: float = 2.2,
) -> list[dict[str, Any]]:
    """Return deterministic room-fixed ceiling-panel centers and dimensions."""
    if len(bounds_xy) != 4:
        raise ValueError("bounds_xy must contain min_x, min_y, max_x, max_y")
    min_x, min_y, max_x, max_y = [float(value) for value in bounds_xy]
    width, depth = max_x - min_x, max_y - min_y
    if width <= 0 or depth <= 0 or not 0 < coverage_fraction <= 0.5:
        raise ValueError("room bounds and coverage must be positive")
    if min_size_m <= 0 or max_size_m < min_size_m:
        raise ValueError("invalid softbox size range")
    area = width * depth
    count = 1 if area < 35.0 else 2 if area < 65.0 else 3 if area < 105.0 else 4
    target_area = area * float(coverage_fraction) / count
    size_x = min(max_size_m, max(min_size_m, math.sqrt(target_area)), width * 0.8)
    size_y = min(max_size_m, max(min_size_m, target_area / max(size_x, 1e-8)), depth * 0.8)
    cx, cy = min_x + width * 0.5, min_y + depth * 0.5
    if count == 1:
        positions = [(cx, cy)]
    elif count == 2:
        positions = ([(min_x + width / 3.0, cy), (min_x + width * 2.0 / 3.0, cy)] if width >= depth
                     else [(cx, min_y + depth / 3.0), (cx, min_y + depth * 2.0 / 3.0)])
    elif count == 3 and width >= depth * 1.45:
        positions = [(min_x + width * factor, cy) for factor in (0.25, 0.5, 0.75)]
    elif count == 3 and depth >= width * 1.45:
        positions = [(cx, min_y + depth * factor) for factor in (0.25, 0.5, 0.75)]
    elif count == 3:
        positions = [(min_x + width * 0.3, min_y + depth * 0.35),
                     (min_x + width * 0.7, min_y + depth * 0.35),
                     (cx, min_y + depth * 0.68)]
    else:
        positions = [(min_x + width * fx, min_y + depth * fy) for fx, fy in (
            (0.33, 0.33), (0.67, 0.33), (0.33, 0.67), (0.67, 0.67),
        )]
    return [{"center_xy": [x, y], "size_m": [size_x, size_y]} for x, y in positions]


def channel_has_source_value(channel: Mapping[str, Any] | None, channel_name: str | None = None) -> bool:
    if not isinstance(channel, Mapping):
        return False
    source = str(channel.get("source") or channel.get("mode") or "missing").lower()
    mode = str(channel.get("mode") or "").lower()
    # Some Stage-1 normal atlases use ``source=not_applicable`` to mean that
    # the source material did not expose a named normal parameter, while still
    # carrying the baked normal texture in ``mode/ref``.  That is authored PBR
    # data, not an absent/flat normal.
    if mode == "texture" and channel.get("ref"):
        return True
    if source in INVALID_CHANNEL_SOURCES:
        return False
    # An absent authored normal is an exact flat-normal statement.  The same
    # marker on base color/roughness/metallic provides no parameter value and
    # therefore requires the documented dataset fallback.
    if source == "not_applicable":
        return channel_name == "normal"
    return True


def pbr_for_slot(unit: Mapping[str, Any], slot: int | None = None) -> Mapping[str, Any]:
    """Return the authoritative PBR contract for one material slot.

    Stage-1 v2 emits ``pbr_by_slot`` for multi-material meshes.  Falling back
    to the historic object-level ``pbr`` keeps old published scenes readable,
    but new preparation never aliases one object's atlas across slots.
    """
    if slot is not None:
        entries = unit.get("pbr_by_slot")
        if isinstance(entries, Mapping):
            candidate = entries.get(str(slot), entries.get(slot))
            if isinstance(candidate, Mapping):
                return candidate
        if isinstance(entries, list) and 0 <= int(slot) < len(entries):
            candidate = entries[int(slot)]
            if isinstance(candidate, Mapping):
                return candidate
    value = unit.get("pbr")
    return value if isinstance(value, Mapping) else {}


def validate_metallic_contract(value: Mapping[str, Any] | None) -> tuple[bool, list[str]]:
    """Validate the strict, renderer-independent MetallicContractV2 payload."""
    if not isinstance(value, Mapping):
        return False, ["missing_metallic_contract"]
    failures = []
    if value.get("schema") != METALLIC_CONTRACT_SCHEMA:
        failures.append("invalid_schema")
    family = str(value.get("family") or "")
    if family not in METALLIC_CONTRACT_FAMILIES:
        failures.append("invalid_family")
    expected_representation = "spatial_texture" if family == "coverage_mixed" else "scalar"
    if value.get("representation") != expected_representation:
        failures.append("invalid_representation")
    if value.get("encoding") != "linear_scalar":
        failures.append("invalid_encoding")
    if value.get("color_space") != "non_color":
        failures.append("metallic_not_non_color")
    if family == "coverage_mixed" and value.get("approximation") != "principled_coverage":
        failures.append("invalid_coverage_approximation")
    if family != "coverage_mixed" and value.get("approximation") not in {None, "none"}:
        failures.append("unexpected_approximation")
    if not str(value.get("generator_id") or ""):
        failures.append("missing_generator_id")
    if not isinstance(value.get("seed"), int):
        failures.append("invalid_seed")
    return not failures, failures


def metallic_contract_for_slot(unit: Mapping[str, Any], slot: int | None = None) -> Mapping[str, Any] | None:
    value = pbr_for_slot(unit, slot).get("metallic_contract")
    if isinstance(value, Mapping):
        return value
    return None


def unit_source_valid(unit: Mapping[str, Any], slot: int | None = None) -> bool:
    pbr = pbr_for_slot(unit, slot)
    if str(pbr.get("status") or "").lower() != "ok":
        return False
    channels = pbr.get("channels") if isinstance(pbr.get("channels"), Mapping) else {}
    return all(channel_has_source_value(channels.get(name), name) for name in SUPPORTED_CHANNELS)


def material_normalization_record(
    unit: Mapping[str, Any], material_name: str, semantic_class: str = "none", *, slot: int | None = None,
) -> dict[str, Any]:
    """Build the deterministic normalization decision for one object material slot."""
    pbr = pbr_for_slot(unit, slot)
    channels = pbr.get("channels") if isinstance(pbr.get("channels"), Mapping) else {}
    missing = [name for name in SUPPORTED_CHANNELS if not channel_has_source_value(channels.get(name), name)]
    semantic = str(semantic_class or "none")
    surrogate = semantic in SEMANTIC_SURROGATES
    replacement_reasons = []
    if surrogate:
        replacement_reasons.append(f"{semantic}_to_opaque_principled")
    replacement_reasons.extend(f"missing_{name}_fallback" for name in missing)
    source_valid = unit_source_valid(unit, slot) and not surrogate
    source_channels = {
        name: {
            key: channels.get(name, {}).get(key)
            for key in ("source", "mode", "value", "ref")
            if isinstance(channels.get(name), Mapping) and channels.get(name, {}).get(key) is not None
        }
        for name in SUPPORTED_CHANNELS
    }
    fallback_values = {
        "base_color": list(DEFAULT_BASE_COLOR[:3]),
        "roughness": DEFAULT_ROUGHNESS,
        "metallic": DEFAULT_METALLIC,
        "normal": "flat_geometry_normal",
    }
    return {
        "object_id": str(unit.get("id") or ""),
        "blender_object": str(unit.get("blender_name") or ""),
        "source_material": str(material_name),
        "semantic_class": semantic,
        "source_valid": bool(source_valid),
        "gt_defined": True,
        "replacement": bool(replacement_reasons),
        "replacement_reasons": replacement_reasons,
        "fallback_channels": missing,
        "source_channels": source_channels,
        "material_slot": slot,
        "applied_fallback_values": {name: fallback_values[name] for name in missing},
        "metallic_contract": metallic_contract_for_slot(unit, slot),
    }


def stable_json_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def files_digest(paths: list[Path], *, root: Path | None = None) -> str:
    h = hashlib.sha256()
    for path in sorted(Path(p).resolve() for p in paths):
        label = str(path.relative_to(root.resolve())) if root is not None else str(path)
        h.update(label.encode("utf-8"))
        h.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(block)
        h.update(b"\0")
    return h.hexdigest()


def formula_contract() -> dict[str, Any]:
    return {
        "id": PSEUDO_NIR_FORMULA_ID,
        "input": "linear_rgb",
        "expression": "dot(max(rgb, 1-rgb), [0.229, 0.587, 0.114])",
        "weights": PSEUDO_NIR_WEIGHTS.astype(float).tolist(),
        "implementation_digest": stable_json_digest({
            "id": PSEUDO_NIR_FORMULA_ID,
            "weights": PSEUDO_NIR_WEIGHTS.astype(float).tolist(),
            "operation": "dot(max(rgb, 1-rgb), weights)",
        }),
    }
