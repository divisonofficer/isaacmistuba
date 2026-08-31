"""Shared schema and artifact-safety contract for Principled IR datasets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# These are the schemas emitted by newly prepared/renders.  Keep the v2
# identifiers explicitly supported below: published v2 datasets are immutable
# and must remain inspectable/publish-verifiable as legacy data.
DATASET_SCHEMA = "robomituba.ir_principled_dataset.v3"
ARTIFACT_SCHEMA = "robomituba.ir_principled_artifact_contract.v3"
LEGACY_DATASET_SCHEMA = "robomituba.ir_principled_dataset.v2"
LEGACY_ARTIFACT_SCHEMA = "robomituba.ir_principled_artifact_contract.v2"
SUPPORTED_DATASET_SCHEMAS = frozenset((DATASET_SCHEMA, LEGACY_DATASET_SCHEMA))
SUPPORTED_ARTIFACT_SCHEMAS = frozenset((ARTIFACT_SCHEMA, LEGACY_ARTIFACT_SCHEMA))
OVERVIEW_SCHEMA = "robomituba.ir_scene_overview.v1"

# Storage is intentionally independent from the dataset/PBR schema.  A compact
# child dataset has identical pixels to its parent up to EXR half precision and
# may omit *diagnostic* diffuse decomposition products, while keeping the
# trainable RGB/NIR/PBR contract unchanged.
STORAGE_PROFILE_LEGACY_FULL_FLOAT32_V1 = "legacy_full_float32_v1"
STORAGE_PROFILE_CORE_HALF_EXR_V1 = "core_half_exr_v1"
STORAGE_PROFILE_DIAGNOSTIC_HALF_EXR_V1 = "diagnostic_half_exr_v1"
STORAGE_PROFILES = {
    STORAGE_PROFILE_LEGACY_FULL_FLOAT32_V1: {
        "exr_precision": "float32", "store_diffuse_decomposition": True,
        "publication_tier": "legacy_full",
    },
    STORAGE_PROFILE_CORE_HALF_EXR_V1: {
        "exr_precision": "float16", "store_diffuse_decomposition": False,
        "publication_tier": "core",
    },
    # Stage-0/QC can retain diffuse diagnostics without imposing their cost on
    # the full public dataset.
    STORAGE_PROFILE_DIAGNOSTIC_HALF_EXR_V1: {
        "exr_precision": "float16", "store_diffuse_decomposition": True,
        "publication_tier": "diagnostic",
    },
}


def storage_profile_spec(profile: object) -> dict[str, object]:
    """Return the immutable storage policy or reject an unknown profile."""
    key = str(profile)
    try:
        return {"id": key, **STORAGE_PROFILES[key]}
    except KeyError as exc:
        raise ValueError(f"unsupported IR dataset storage profile: {key!r}") from exc

HDR_MODALITIES = {
    "rgb", "nir_active", "nir_passive", "nir_active_minus_passive",
    "diffuse_component_rgb", "diffuse_component_nir",
    "diffuse_transport_rgb", "diffuse_transport_nir",
    # v2 compatibility only.  They are deliberately absent from v3 contracts.
    "diffuse_shading_rgb", "diffuse_shading_nir",
}
LINEAR_RGB_MODALITIES = {
    "base_color_rgb", "base_color_nir", "diffuse_reflectance_rgb", "diffuse_reflectance_nir",
}
SCALAR_MODALITIES = {"roughness", "metallic"}
NORMAL_MODALITIES = {"normal_geometry_world", "normal_shading_world"}
DISTANCE_MODALITIES = {"depth", "range"}
# Object and material IDs use the full uint16 PNG range.  Provenance is a
# compact categorical map (currently 0--255) and is intentionally emitted as
# uint8 by both the rolling renderer and the contract-repair tool.
ID_MODALITIES = {"object_id", "material_id"}
CLASS_MODALITIES = {"pbr_provenance_class"}
MASK_MODALITIES = {
    "gt_defined_mask", "source_valid_mask", "replacement_mask", "fallback_mask",
    "remediated_pbr_mask", "train_pbr_valid_mask", "primary_eval_valid_mask",
    "diffuse_transport_valid_rgb", "diffuse_transport_valid_nir",
    "diffuse_shading_valid_rgb", "diffuse_shading_valid_nir",  # v2 legacy
}


def is_supported_dataset_schema(value: object) -> bool:
    return str(value) in SUPPORTED_DATASET_SCHEMAS


def is_supported_artifact_schema(value: object) -> bool:
    return str(value) in SUPPORTED_ARTIFACT_SCHEMAS


def is_legacy_v2_schema(value: object) -> bool:
    return str(value) == LEGACY_DATASET_SCHEMA


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _safe_artifact_path(dataset_dir: Path, relative: str, *, require_file: bool = True) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"unsafe dataset artifact path: {relative!r}")
    root = dataset_dir.resolve()
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"symlinked dataset artifacts are not allowed: {relative!r}")
    resolved = cursor.resolve(strict=False)
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"artifact escapes dataset root: {relative!r}")
    if require_file and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _safe_artifact_relative_path(relative: str) -> None:
    """Reject lexical path traversal during inexpensive catalog scans."""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError(f"unsafe dataset artifact path: {relative!r}")
