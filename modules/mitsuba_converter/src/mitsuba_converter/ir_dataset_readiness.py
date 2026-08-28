"""Dataset-level readiness labels for scene-scale inverse rendering research."""
from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA = "robomituba.ir_inverse_rendering_readiness.v1"
PROFILE = "scene_scale_specular_showcase_v1"
CLASSIFIER_VERSION = "ir-inverse-rendering-readiness-v1"
MIN_VISIBLE_OBJECTS_PER_SELECTED_VIEW = 10.0


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_readiness_label(*, dataset_name: str, dataset_fingerprint: str,
                          scene_statistics: dict[str, Any] | None) -> dict[str, Any]:
    """Classify only what existing metadata can prove.

    The legacy visibility probe counts approximate total first-hit objects, not
    specular-eligible objects or their raster area.  A total-object median below
    ten is therefore enough to mark a dataset below the showcase target.  A
    dataset above that proxy threshold remains unverified until the planned
    raster PBR/specular probe exists; it is never promoted to ready here.
    """
    statistics = scene_statistics if isinstance(scene_statistics, dict) else {}
    visible_summary = statistics.get("selected_visible_object_count") or {}
    median = visible_summary.get("median")
    p90 = visible_summary.get("p90")
    try:
        median = float(median) if median is not None else None
    except (TypeError, ValueError):
        median = None
    try:
        p90 = float(p90) if p90 is not None else None
    except (TypeError, ValueError):
        p90 = None

    findings: list[str] = []
    if median is None:
        status = "unverified"
        findings.append("selected_view_visibility_metadata_missing")
    elif median < MIN_VISIBLE_OBJECTS_PER_SELECTED_VIEW:
        status = "below_target"
        findings.append("selected_visible_object_median_below_10")
    else:
        status = "unverified"
        findings.append("specular_raster_evidence_missing")
    # The current sidecar cannot establish the research-grade material target,
    # even when its coarse total-object proxy happens to pass.
    findings.extend([
        "specular_eligible_object_count_unmeasured",
        "per_object_pixel_coverage_unmeasured",
        "visible_pbr_material_diversity_unmeasured",
    ])
    recommendation = (
        "exclude_from_scene_scale_specular_headline_set"
        if status == "below_target" else "hold_for_raster_specular_audit"
    )
    core = {
        "schema": SCHEMA,
        "classifier_version": CLASSIFIER_VERSION,
        "profile": PROFILE,
        "dataset_name": dataset_name,
        "dataset_fingerprint": dataset_fingerprint,
        "status": status,
        "labels": [
            f"{PROFILE}:{status}",
            f"density:{statistics.get('density_class') or 'unknown'}",
        ],
        "findings": findings,
        "recommendation": recommendation,
        "criteria": {
            "selected_visible_object_median_min": MIN_VISIBLE_OBJECTS_PER_SELECTED_VIEW,
            "specular_eligible_objects_per_view_min": 10,
            "visible_pbr_material_ids_per_view_min": 8,
            "roughness_bins_per_view_min": 3,
            "specular_pixel_fraction_range": [0.12, 0.45],
        },
        "evidence": {
            "selected_visible_object_count": {"median": median, "p90": p90},
            "selected_pose_count": statistics.get("selected_pose_count"),
            "density_class": statistics.get("density_class"),
            "statistics_digest": statistics.get("statistics_digest"),
            "visibility_digest": statistics.get("visibility_digest"),
            "evidence_kind": "legacy_2d_total_object_visibility_proxy",
            "limitations": [
                "not_a_raster_visibility_measurement",
                "does_not_identify_specular_eligible_objects",
                "does_not_measure_pixel_coverage_or_material_bins",
            ],
        },
    }
    return {**core, "label_digest": _digest(core)}
