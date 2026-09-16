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


def _classify(objects_per_m2: float | None, visible_median: float | None) -> tuple[str, str]:
    """Classify how furnished the SCENE is, and say what the answer rests on.

    Density is a property of the room; how many objects a given pose happens to
    see is a property of the pose set. Combining them made the two inseparable
    and the result wrong in both directions:

      * ``objects_per_m2 or visible_median`` let one weak term veto a strong
        one, so a closet holding 42 objects in 2.45 m² -- 17.2 per m² -- was
        classified sparse because its poses looked at walls.
      * ``visible_median`` falls as a pose sweep widens, so the same scene came
        out dense at 53 poses and sparse at 200. Density anti-correlated with
        coverage, which is backwards.

    So visibility no longer decides density. It stays in the record as
    ``selected_visible_object_count`` and gets its own class, and this returns
    the class alongside the basis it was reached from, because a reader cannot
    otherwise tell a measured class from a fallback one.
    """
    if objects_per_m2 is not None:
        if objects_per_m2 < 1.0:
            return "sparse", "objects_per_m2"
        if objects_per_m2 < 3.0:
            return "moderate", "objects_per_m2"
        return "dense", "objects_per_m2"
    # No footprint. Visibility is a weaker proxy -- it answers "how much did
    # these poses see" rather than "how furnished is the room" -- but it is a
    # measurement, and returning "unknown" when a measurement exists is what
    # sent 166 of 168 datasets to a deprecation tier for lack of a sidecar.
    if visible_median is not None:
        if visible_median < 2.0:
            return "sparse", "visible_median_fallback"
        if visible_median < 5.0:
            return "moderate", "visible_median_fallback"
        return "dense", "visible_median_fallback"
    return "unknown", "no_measurement"


def _visibility_class(visible_median: float | None) -> str:
    """How much the selected poses actually see. Not density -- coverage."""
    if visible_median is None:
        return "unknown"
    if visible_median < 2.0:
        return "narrow"
    if visible_median < 5.0:
        return "mixed"
    return "wide"


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
    density_class, density_basis = _classify(per_m2, visible_stats["median"])
    visibility_class = _visibility_class(visible_stats["median"])
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
        "density_class": density_class, "density_basis": density_basis,
        "pose_visibility_class": visibility_class,
        "unknown_reason": None if density_class != "unknown" else "no_room_footprint_and_no_pose_visibility",
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
