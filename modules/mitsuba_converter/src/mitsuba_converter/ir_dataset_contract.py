"""Shared schema and artifact-safety contract for Principled IR datasets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATASET_SCHEMA = "robomituba.ir_principled_dataset.v2"
ARTIFACT_SCHEMA = "robomituba.ir_principled_artifact_contract.v2"
OVERVIEW_SCHEMA = "robomituba.ir_scene_overview.v1"

HDR_MODALITIES = {
    "rgb", "nir_active", "diffuse_component_rgb", "diffuse_component_nir",
    "diffuse_shading_rgb", "diffuse_shading_nir",
}
LINEAR_RGB_MODALITIES = {
    "base_color_rgb", "base_color_nir", "diffuse_reflectance_rgb", "diffuse_reflectance_nir",
}
SCALAR_MODALITIES = {"roughness", "metallic"}
NORMAL_MODALITIES = {"normal_geometry_world", "normal_shading_world"}
DISTANCE_MODALITIES = {"depth", "range"}
ID_MODALITIES = {"object_id", "material_id"}
MASK_MODALITIES = {
    "gt_defined_mask", "source_valid_mask", "replacement_mask", "fallback_mask",
    "primary_eval_valid_mask", "diffuse_shading_valid_rgb", "diffuse_shading_valid_nir",
}


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
