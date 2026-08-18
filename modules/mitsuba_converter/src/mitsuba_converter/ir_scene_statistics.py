"""Portable scene-density statistics for the IR dataset catalog."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

SCHEMA = "robomituba.ir_scene_statistics.v1"
CLASSIFIER_VERSION = "ir-scene-density-v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _summary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "p10": None, "p90": None}
    values = sorted(float(value) for value in values)
    def percentile(q: float) -> float:
        index = (len(values) - 1) * q
        low, high = math.floor(index), math.ceil(index)
        return values[low] if low == high else values[low] * (high - index) + values[high] * (index - low)
    return {"mean": round(sum(values) / len(values), 6), "median": round(percentile(.5), 6),
            "p10": round(percentile(.1), 6), "p90": round(percentile(.9), 6)}


def _classify(objects_per_m2: float | None, visible_median: float | None) -> str:
    if objects_per_m2 is None or visible_median is None:
        return "unknown"
    if objects_per_m2 < 1.0 or visible_median < 2.0:
        return "sparse"
    if objects_per_m2 < 3.0 or visible_median < 5.0:
        return "moderate"
    return "dense"


def build_scene_statistics(*, content_audit: dict[str, Any], visibility: dict[str, Any], render_plan: dict[str, Any],
                           requested_density: str | None = None, material_mix: dict[str, Any] | None = None,
                           material_visibility: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = [pose for group in (render_plan.get("groups") or []) for pose in (group.get("poses") or [])]
    utilities = [pose.get("utility") or {} for pose in selected]
    visible = [float(item["visible_object_count"]) for item in utilities if item.get("visible_object_count") is not None]
    fractions = [float(item["nonstructural_fraction"]) for item in utilities if item.get("nonstructural_fraction") is not None]
    classes = {name: sum(str(item.get("utility_class") or "rejected") == name for item in utilities)
               for name in ("informative", "structural", "sparse_negative", "rejected")}
    candidate_classes = dict(visibility.get("class_counts") or {})
    footprint = content_audit.get("room_footprint") or {}
    area = footprint.get("area_m2")
    try:
        area = float(area) if area is not None and float(area) > 0 else None
    except (TypeError, ValueError):
        area = None
    nonstructural = int(content_audit.get("nonstructural_object_count") or 0)
    per_m2 = round(nonstructural / area, 6) if area else None
    visible_stats, fraction_stats = _summary(visible), _summary(fractions)
    density_class = _classify(per_m2, visible_stats["median"])
    material_mix = material_mix or {}
    material_visibility = material_visibility or {}
    core = {
        "schema": SCHEMA, "classifier_version": CLASSIFIER_VERSION,
        "room_type": content_audit.get("room_type"), "requested_furnishing_density": requested_density,
        "content_audit_status": content_audit.get("status"), "content_audit_digest": content_audit.get("audit_digest"),
        "object_count": int(content_audit.get("object_count") or 0), "nonstructural_object_count": nonstructural,
        "room_footprint": footprint or None, "room_area_m2": area, "nonstructural_objects_per_m2": per_m2,
        "candidate_pose_count": int(visibility.get("candidate_count") or 0), "candidate_class_counts": candidate_classes,
        "selected_pose_count": len(selected), "selected_class_counts": classes,
        "selected_sparse_pose_fraction": round(classes["sparse_negative"] / len(selected), 6) if selected else None,
        "selected_visible_object_count": visible_stats,
        "selected_nonstructural_fraction": fraction_stats,
        "density_class": density_class, "unknown_reason": None if density_class != "unknown" else "missing_area_or_visibility",
        "render_plan_digest": render_plan.get("render_plan_digest"), "visibility_digest": visibility.get("probe_digest"),
        "material_mix_profile": material_mix.get("profile"),
        "high_metallic_material_count": material_mix.get("high_metallic_constant_count"),
        "texture_metallic_material_count": material_mix.get("texture_metallic_count"),
        "high_metallic_valid_pixel_fraction": material_visibility.get("high_metallic_fraction"),
        "metallic_visibility_pose_fraction": material_visibility.get("visible_frame_fraction"),
        "dominant_metal_object_ratio": material_visibility.get("dominant_material_ratio"),
        "material_mix_status": material_mix.get("status"), "material_visibility_status": material_visibility.get("status"),
    }
    return {**core, "statistics_digest": _digest(core)}
