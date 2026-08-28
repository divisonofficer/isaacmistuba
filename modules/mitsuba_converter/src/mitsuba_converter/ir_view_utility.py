"""Cheap deterministic content visibility probes for IR camera candidates.

The probe deliberately uses only the navigation graph and authoring-map object
bounds.  It is therefore suitable for queue planning: no Blender/Cycles context
is created and a scene with thousands of candidate poses can be scored quickly.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

SCHEMA = "robomituba.ir_candidate_visibility.v1"
STRUCTURAL = ("wall", "floor", "ceiling", "door", "window", "exterior", "room")


def stable_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _candidate_key(viewpoint_id: str, heading_deg: float) -> str:
    return f"{viewpoint_id}@{float(heading_deg) % 360.0:.6f}"


def _object_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    geometry = raw.get("geometry") or {}
    center = geometry.get("center") or raw.get("center")
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    size = geometry.get("size_m") or raw.get("size_m") or [0.5, 0.5, 0.5]
    metadata = raw.get("metadata") or {}
    text = " ".join(str(metadata.get(k, "")) for k in ("kind", "factory", "category", "semantic_type"))
    text = f"{raw.get('id', '')} {raw.get('type', '')} {text}".lower()
    structural = any(token in text for token in STRUCTURAL)
    factory = str(metadata.get("factory") or metadata.get("category") or raw.get("type") or "unknown")
    category = factory.removesuffix("Factory").split("_")[0].lower()
    radius = max(0.08, 0.5 * math.hypot(float(size[0] or 0.0), float(size[1] or 0.0)))
    return {"id": str(raw.get("id") or factory), "center": [float(center[0]), float(center[1])],
            "radius": radius, "category": category, "structural": structural}


def _room_bounds(authoring_map: dict[str, Any]) -> tuple[float, float, float, float] | None:
    boxes: list[tuple[float, float, float, float]] = []
    for region in authoring_map.get("regions") or []:
        geometry = region.get("geometry") or {}
        bounds = geometry.get("bounds") or region.get("bounds")
        if isinstance(bounds, (list, tuple)) and len(bounds) >= 4:
            boxes.append(tuple(map(float, bounds[:4])))
    if not boxes:
        return None
    return min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)


def _wall_distance(origin: tuple[float, float], angle: float, bounds: tuple[float, float, float, float] | None) -> float:
    if bounds is None:
        return 20.0
    x, y = origin
    dx, dy = math.cos(angle), math.sin(angle)
    distances = []
    if abs(dx) > 1e-9:
        distances += [(bounds[0] - x) / dx, (bounds[2] - x) / dx]
    if abs(dy) > 1e-9:
        distances += [(bounds[1] - y) / dy, (bounds[3] - y) / dy]
    valid = [distance for distance in distances if distance > 0]
    return min(valid) if valid else 20.0


def classify_probe(features: dict[str, Any]) -> tuple[str, list[str]]:
    """Return utility class and explicit rejection reasons."""
    reasons: list[str] = []
    if float(features["forward_clearance_m"]) < 0.35:
        reasons.append("forward_obstacle")
    if float(features["nonstructural_fraction"]) < 0.03 and int(features["visible_object_count"]) < 2:
        reasons.append("empty_corner")
    if float(features["wall_fraction"]) > 0.85 and float(features["depth_entropy"]) < 0.28:
        reasons.append("wall_only")
    protected = bool(features.get("protected"))
    if reasons and not protected:
        return "rejected", reasons
    score = float(features["utility_score"])
    if protected or score >= 0.56:
        return "informative", reasons
    if score >= 0.28:
        return "structural", reasons
    return "sparse_negative", reasons


def probe_candidates(graph: dict[str, Any], authoring_map: dict[str, Any], *, fov_deg: float = 70.0,
                     ray_count: int = 96) -> dict[str, Any]:
    if ray_count < 16:
        raise ValueError("ray_count must be at least 16")
    objects = [record for raw in (authoring_map.get("objects") or []) if (record := _object_record(raw))]
    bounds = _room_bounds(authoring_map)
    candidates: dict[str, Any] = {}
    half_fov = math.radians(fov_deg) / 2.0
    for node in graph.get("nodes") or []:
        node_id = str(node.get("node_id") or "")
        position = node.get("position") or []
        if not node_id or len(position) < 2:
            continue
        origin = float(position[0]), float(position[1])
        tags = {str(tag).lower() for tag in (node.get("tags") or [])}
        node_protected = bool(node.get("portal") or node.get("hazard") or node.get("protected")
                              or tags.intersection({"portal", "doorway", "hazard", "transition"}))
        for heading in node.get("headings") or []:
            yaw = float(heading.get("yaw_deg", 0.0))
            depths: list[float] = []
            hits: list[str | None] = []
            categories: set[str] = set()
            visible_ids: set[str] = set()
            for index in range(ray_count):
                angle = math.radians(yaw) - half_fov + (index + 0.5) * (2.0 * half_fov / ray_count)
                wall_depth = _wall_distance(origin, angle, bounds)
                best_depth, best = wall_depth, None
                for obj in objects:
                    dx, dy = obj["center"][0] - origin[0], obj["center"][1] - origin[1]
                    distance = math.hypot(dx, dy)
                    if distance <= obj["radius"]:
                        continue
                    delta = abs((math.atan2(dy, dx) - angle + math.pi) % (2 * math.pi) - math.pi)
                    angular_radius = math.asin(min(0.999, obj["radius"] / distance))
                    if delta <= angular_radius and distance - obj["radius"] < best_depth:
                        best_depth, best = max(0.0, distance - obj["radius"]), obj
                depths.append(best_depth)
                hits.append(best["id"] if best and not best["structural"] else None)
                if best and not best["structural"]:
                    visible_ids.add(best["id"]); categories.add(best["category"])
            nonstruct = sum(hit is not None for hit in hits) / ray_count
            # Normalized histogram entropy is a stable proxy for depth complexity.
            lo, hi = min(depths), max(depths)
            histogram = [0] * 8
            for depth in depths:
                bucket = min(7, int(8 * (depth - lo) / max(hi - lo, 1e-6)))
                histogram[bucket] += 1
            entropy = -sum((n / ray_count) * math.log(n / ray_count) for n in histogram if n) / math.log(8)
            center = depths[ray_count * 2 // 5:ray_count * 3 // 5]
            clearance = min(center) if center else min(depths)
            diversity = min(1.0, len(categories) / 6.0)
            count_score = min(1.0, len(visible_ids) / 8.0)
            score = 0.48 * min(1.0, nonstruct / 0.35) + 0.22 * diversity + 0.18 * count_score + 0.12 * entropy
            features = {"viewpoint_id": node_id, "heading_deg": yaw, "nonstructural_fraction": round(nonstruct, 6),
                        "wall_fraction": round(1.0 - nonstruct, 6), "visible_object_count": len(visible_ids),
                        "visible_category_count": len(categories), "visible_categories": sorted(categories),
                        "depth_entropy": round(entropy, 6), "forward_clearance_m": round(clearance, 6),
                        "utility_score": round(score, 6), "protected": node_protected or bool(heading.get("protected"))
                        or bool((heading.get("extras") or {}).get("protected"))}
            utility_class, reasons = classify_probe(features)
            features.update({"utility_class": utility_class, "reject_reasons": reasons})
            candidates[_candidate_key(node_id, yaw)] = features
    counts = {name: sum(value["utility_class"] == name for value in candidates.values())
              for name in ("informative", "structural", "sparse_negative", "rejected")}
    core = {"schema": SCHEMA, "source_graph_digest": stable_digest(graph),
            "source_authoring_map_digest": stable_digest(authoring_map), "fov_deg": float(fov_deg),
            "ray_count": int(ray_count), "candidate_count": len(candidates), "class_counts": counts,
            "candidates": candidates}
    return {**core, "probe_digest": stable_digest(core)}
