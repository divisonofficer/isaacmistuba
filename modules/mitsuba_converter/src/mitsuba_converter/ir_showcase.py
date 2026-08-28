"""Deterministic contracts for Infinigen IR showcase composition and cameras.

The native Infinigen constraint solver owns room layout.  This module owns the
post-generation IR layer only: selecting audited props, describing support
anchors, and selecting walkable multi-view camera sets that look at those
anchors.  It deliberately has no Blender dependency so controller recovery and
unit tests can reason about the exact same provenance.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from typing import Any, Iterable


PROFILE = "inverse_rendering_showcase_v1"
REGISTRY_SCHEMA = "robomituba.infinigen_prop_pbr_registry.v1"
COMPOSITION_SCHEMA = "robomituba.ir_showcase_composition.v1"
CAMERA_SET_SCHEMA = "robomituba.ir_showcase_camera_sets.v1"
ACCEPTANCE_SCHEMA = "robomituba.ir_showcase_acceptance.v1"
SAMPLER_VERSION = "anchor-centric-walkable-v2"

TARGET_PROP_COUNT = (16, 24)
MIN_CATEGORIES = 8
MAX_FACTORY_COUNT = 2
CLASS_MINIMUMS = {
    "polished_metallic": 3,
    "glossy_dielectric": 4,
    "coated": 3,
    "rough_textured": 3,
}
CAMERA_SET_MIN = 4
CAMERA_SET_MAX = 12
# Showcase scenes are intended for scene-scale evaluation.  Lighting variants
# must not inflate this count: these are independent camera poses.
MIN_ACCEPTED_POSES = 50
# OpticalNav's 0.3 m robot-radius graphs commonly report 0.4--0.45 m
# clearance in valid indoor aisles.  The old 0.6 m threshold rejected every
# camera in otherwise traversable single rooms.
MIN_CAMERA_CLEARANCE_M = 0.4
MIN_FORWARD_CLEARANCE_M = 1.0
MIN_ANCHOR_DISTANCE_M = 1.2
MAX_ANCHOR_DISTANCE_M = 4.5
MIN_BASELINE_M = 0.5
MIN_AZIMUTH_SPAN_DEG = 90.0


def stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def registry_digest(registry: dict[str, Any]) -> str:
    """Return the semantic digest rather than trusting a stale stored field."""
    core = {key: value for key, value in registry.items() if key not in {"registry_digest", "created_at"}}
    return stable_digest(core)


def _class_of(record: dict[str, Any]) -> str:
    return str((record.get("pbr") or {}).get("class") or record.get("pbr_class") or "context")


def _category_of(record: dict[str, Any]) -> str:
    return str(record.get("semantic_category") or record.get("category") or "object")


def _factory_of(record: dict[str, Any]) -> str:
    return str(record.get("factory") or record.get("factory_id") or record.get("asset_id") or "unknown")


def usable_registry_records(registry: dict[str, Any]) -> list[dict[str, Any]]:
    records = registry.get("props") or registry.get("assets") or []
    return [dict(record) for record in records if isinstance(record, dict) and record.get("enabled", True)
            and bool((record.get("geometry") or {}).get("valid_support_object", record.get("valid_support_object", True)))]


def sample_showcase_props(registry: dict[str, Any], *, seed: int, target_count: int | None = None) -> list[dict[str, Any]]:
    """Select a class/category balanced native-prop composition deterministically."""
    records = usable_registry_records(registry)
    if target_count is None:
        target_count = TARGET_PROP_COUNT[0] + int(seed) % (TARGET_PROP_COUNT[1] - TARGET_PROP_COUNT[0] + 1)
    target_count = int(target_count)
    if not TARGET_PROP_COUNT[0] <= target_count <= TARGET_PROP_COUNT[1]:
        raise ValueError(f"showcase target count must be in {TARGET_PROP_COUNT}")
    rng = random.Random(int(seed))
    by_class: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_class.setdefault(_class_of(record), []).append(record)
    for values in by_class.values():
        rng.shuffle(values)
    chosen: list[dict[str, Any]] = []
    factory_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()

    def take(pool: Iterable[dict[str, Any]], count: int, *, prefer_new_category: bool) -> None:
        for record in pool:
            if len(chosen) >= target_count or count <= 0:
                return
            factory = _factory_of(record)
            if factory_counts[factory] >= MAX_FACTORY_COUNT:
                continue
            category = _category_of(record)
            if prefer_new_category and category in category_counts:
                continue
            chosen.append(record)
            factory_counts[factory] += 1
            category_counts[category] += 1
            count -= 1

    for pbr_class, minimum in CLASS_MINIMUMS.items():
        before = len(chosen)
        take(by_class.get(pbr_class, ()), minimum, prefer_new_category=True)
        take(by_class.get(pbr_class, ()), minimum - (len(chosen) - before), prefer_new_category=False)
        if len(chosen) - before < minimum:
            raise ValueError(f"registry cannot supply {minimum} {pbr_class} props")
    # First make semantic diversity a hard requirement, then fill the remaining
    # slots with all remaining candidates in deterministic randomized order.
    pool = [record for values in by_class.values() for record in values]
    rng.shuffle(pool)
    take(pool, max(0, MIN_CATEGORIES - len(category_counts)), prefer_new_category=True)
    if len(category_counts) < MIN_CATEGORIES:
        raise ValueError(f"registry cannot supply {MIN_CATEGORIES} semantic categories")
    take(pool, target_count - len(chosen), prefer_new_category=False)
    if len(chosen) != target_count:
        raise ValueError("registry cannot supply requested showcase prop count within factory cap")
    return [dict(record) for record in chosen]


def composition_contract(registry: dict[str, Any], *, seed: int, target_count: int | None = None) -> dict[str, Any]:
    props = sample_showcase_props(registry, seed=seed, target_count=target_count)
    payload = {
        "schema": COMPOSITION_SCHEMA,
        "profile": PROFILE,
        "sampler_version": SAMPLER_VERSION,
        "composition_seed": int(seed),
        "registry_digest": registry_digest(registry),
        "props": props,
        "target_prop_count": len(props),
        "class_counts": dict(Counter(_class_of(prop) for prop in props)),
        "category_counts": dict(Counter(_category_of(prop) for prop in props)),
        "factory_counts": dict(Counter(_factory_of(prop) for prop in props)),
    }
    payload["composition_digest"] = stable_digest(payload)
    return payload


def _xy(value: Any) -> tuple[float, float]:
    raw = list(value or ())
    if len(raw) < 2:
        raise ValueError("expected planar position")
    return float(raw[0]), float(raw[1])


def _heading_to(source: tuple[float, float], target: tuple[float, float]) -> float:
    return math.degrees(math.atan2(target[1] - source[1], target[0] - source[0])) % 360.0


def _azimuth_span(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    ordered = sorted(value % 360.0 for value in values)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])] + [ordered[0] + 360.0 - ordered[-1]]
    return 360.0 - max(gaps)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _probe_metric(probe: dict[str, Any] | None, anchor_id: str, node_id: str) -> dict[str, Any]:
    if not probe:
        return {}
    candidates = probe.get("anchor_candidates") or probe.get("candidates") or {}
    return dict(candidates.get(f"{anchor_id}:{node_id}") or candidates.get(f"{node_id}@{anchor_id}") or {})


def _camera_candidates(graph: dict[str, Any], anchor: dict[str, Any], probe: dict[str, Any] | None) -> list[dict[str, Any]]:
    anchor_id = str(anchor.get("anchor_id") or anchor.get("id") or "anchor")
    target = _xy(anchor.get("center_xy") or anchor.get("position_xy") or anchor.get("position"))
    target_height = float(anchor.get("target_height_m") or anchor.get("height_m") or 0.8)
    result: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        node_id = str(node.get("node_id") or "")
        if not node_id:
            continue
        position = _xy(node.get("position"))
        metric = _probe_metric(probe, anchor_id, node_id)
        clearance = float(metric.get("camera_clearance_m", node.get("clearance_m", 1.0)))
        forward = float(metric.get("forward_clearance_m", metric.get("center_ray_clearance_m", float("inf"))))
        distance = _distance(position, target)
        if clearance < MIN_CAMERA_CLEARANCE_M or forward < MIN_FORWARD_CLEARANCE_M:
            continue
        if not MIN_ANCHOR_DISTANCE_M <= distance <= MAX_ANCHOR_DISTANCE_M:
            continue
        if metric.get("wall_only") or metric.get("severe_occlusion"):
            continue
        camera_height = float(node.get("camera_height_m", 1.2))
        # ``resolve_viewpoint_pose`` uses a unit-length horizontal target ray.
        # Store the equivalent endpoint height as well as the physical anchor
        # height so the final camera really looks at the anchor, not at a point
        # one metre away at the anchor's absolute Z.
        resolver_target_height = camera_height + (target_height - camera_height) / max(distance, 1e-6)
        score = float(metric.get("utility_score", metric.get("visibility_score", 1.0)))
        result.append({
            "viewpoint_id": node_id,
            "position_xy": list(position),
            "heading_deg": _heading_to(position, target),
            "pitch_deg": math.degrees(math.atan2(target_height - camera_height, distance)),
            "anchor_target_height_m": round(target_height, 6),
            "resolver_target_height_m": round(resolver_target_height, 6),
            "anchor_distance_m": round(distance, 6),
            "camera_clearance_m": round(clearance, 6),
            "forward_clearance_m": None if math.isinf(forward) else round(forward, 6),
            "azimuth_deg": _heading_to(target, position),
            "probe": metric,
            "score": score,
        })
    return result


def _choose_set(candidates: list[dict[str, Any]], *, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(int(seed))
    ordered = sorted(candidates, key=lambda item: (-float(item["score"]), item["viewpoint_id"]))
    if not ordered:
        return []
    selected = [ordered[0]]
    remaining = ordered[1:]
    while remaining and len(selected) < CAMERA_SET_MAX:
        scores = []
        for candidate in remaining:
            baseline = min(_distance(tuple(candidate["position_xy"]), tuple(existing["position_xy"])) for existing in selected)
            score = baseline + .15 * float(candidate["score"])
            scores.append(score)
        best = max(scores)
        choices = [index for index, score in enumerate(scores) if abs(score - best) <= 1e-9]
        candidate = remaining.pop(choices[rng.randrange(len(choices))])
        if min(_distance(tuple(candidate["position_xy"]), tuple(existing["position_xy"])) for existing in selected) >= MIN_BASELINE_M:
            selected.append(candidate)
    if len(selected) < CAMERA_SET_MIN:
        return []
    if _azimuth_span([float(item["azimuth_deg"]) for item in selected]) < MIN_AZIMUTH_SPAN_DEG:
        return []
    return selected


def _trim_set_members(members: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Keep a bounded set's azimuth/baseline diversity when filling a budget tail."""
    if count >= len(members):
        return list(members)
    if count < CAMERA_SET_MIN:
        return []
    ordered = sorted(members, key=lambda item: (-float(item["score"]), item["viewpoint_id"]))
    selected = [ordered.pop(0)]
    while ordered and len(selected) < count:
        def rank(candidate: dict[str, Any]) -> tuple[float, float, float, str]:
            azimuths = [float(item["azimuth_deg"]) for item in [*selected, candidate]]
            baseline = min(_distance(tuple(candidate["position_xy"]), tuple(item["position_xy"])) for item in selected)
            return (_azimuth_span(azimuths), baseline, float(candidate["score"]), str(candidate["viewpoint_id"]))
        best = max(ordered, key=rank)
        selected.append(best)
        ordered.remove(best)
    return selected if _azimuth_span([float(item["azimuth_deg"]) for item in selected]) >= MIN_AZIMUTH_SPAN_DEG else []


def _coverage_supplement(candidates: list[dict[str, Any]], existing: list[dict[str, Any]], *,
                         count: int, seed: int) -> list[dict[str, Any]]:
    """Select deterministic scene-coverage poses not already in anchor sets.

    Anchor sets are deliberately strict (four-to-twelve views with shared
    object support), which is useful for tuple evaluation but can leave a
    scene with too few *independent* cameras.  Supplemental poses retain the
    same safe candidate filtering and are stored as singleton coverage poses;
    they never masquerade as an anchor multi-view tuple.
    """
    if count <= 0:
        return []
    def key(item: dict[str, Any]) -> tuple[str, float]:
        return str(item.get("viewpoint_id")), round(float(item.get("heading_deg") or 0.0) % 360.0, 5)
    occupied = {key(item) for item in existing}
    pool = {}
    for item in candidates:
        if key(item) not in occupied:
            pool[key(item)] = item
    ordered = sorted(pool.values(), key=lambda item: (-float(item.get("score", 0.0)), key(item)))
    if not ordered:
        return []
    rng = random.Random(int(seed) ^ 0x5EED5EED)
    chosen = [ordered.pop(0)]
    while ordered and len(chosen) < count:
        def rank(item: dict[str, Any]) -> tuple[float, float, float, str]:
            position = tuple(item["position_xy"])
            baseline = min(_distance(position, tuple(other["position_xy"])) for other in chosen)
            heading_gap = min(abs((float(item["heading_deg"]) - float(other["heading_deg"]) + 180.0) % 360.0 - 180.0)
                              for other in chosen)
            return (baseline + 0.01 * heading_gap, float(item.get("score", 0.0)), rng.random(), key(item)[0])
        best = max(ordered, key=rank)
        chosen.append(best)
        ordered.remove(best)
    return chosen


def build_camera_sets(graph: dict[str, Any], anchors: list[dict[str, Any]], *, seed: int,
                      pose_budget: int, probe: dict[str, Any] | None = None,
                      min_independent_pose_count: int | None = None) -> dict[str, Any]:
    """Build anchor-centric poses without expanding navigation headings."""
    if pose_budget < 1:
        raise ValueError("pose budget must be positive")
    provisional: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        anchor = dict(anchor)
        anchor_id = str(anchor.get("anchor_id") or anchor.get("id") or f"anchor_{index:03d}")
        members = _choose_set(_camera_candidates(graph, anchor, probe), seed=int(seed) + index)
        if not members:
            continue
        provisional.append({"camera_set_id": f"set:{anchor_id}", "anchor_id": anchor_id,
                            "anchor": anchor, "members": members})
    # Region-diverse greedy admission. Each admitted set reserves all of its
    # members, so no set is weakened by a global pose budget trim.
    selected_sets: list[dict[str, Any]] = []
    selected_positions: list[tuple[float, float]] = []
    for item in sorted(provisional, key=lambda value: (-len(value["members"]), value["camera_set_id"])):
        anchor_pos = _xy(item["anchor"].get("center_xy") or item["anchor"].get("position_xy") or item["anchor"].get("position"))
        region_distance = min((_distance(anchor_pos, current) for current in selected_positions), default=float("inf"))
        if len(selected_sets) and region_distance < 1.0:
            continue
        if sum(len(value["members"]) for value in selected_sets) + CAMERA_SET_MIN > pose_budget:
            continue
        selected_sets.append(item)
        selected_positions.append(anchor_pos)
    # If diversity was too strict for a small room, admit any non-overflow set.
    for item in provisional:
        if item in selected_sets or sum(len(value["members"]) for value in selected_sets) + CAMERA_SET_MIN > pose_budget:
            continue
        selected_sets.append(item)
    poses: list[dict[str, Any]] = []
    for item in selected_sets:
        remaining = int(pose_budget) - len(poses)
        members = _trim_set_members(item["members"], min(len(item["members"]), remaining))
        if not members:
            continue
        for member_index, member in enumerate(members):
            poses.append({
                **member,
                "camera_set_ids": [item["camera_set_id"]],
                "anchor_id": item["anchor_id"],
                "target_height_m": float(member["resolver_target_height_m"]),
                "anchor_target_height_m": float(member["anchor_target_height_m"]),
                "camera_set_member_index": member_index,
                "capture_kind": "anchor_multiview",
            })
    # The strict anchor-set contract may intentionally reject many candidates.
    # Fill the independent-pose floor from the same safe candidate pool while
    # keeping these poses out of multi-view set membership.
    supplemental_count = 0
    if min_independent_pose_count is not None:
        target = min(int(min_independent_pose_count), int(pose_budget))
        if len(poses) < target:
            all_candidates: list[dict[str, Any]] = []
            for anchor in anchors:
                all_candidates.extend(_camera_candidates(graph, anchor, probe))
            supplemental = _coverage_supplement(all_candidates, poses, count=target - len(poses), seed=seed)
            for member_index, member in enumerate(supplemental):
                poses.append({**member, "camera_set_ids": [], "anchor_id": member.get("anchor_id"),
                              "camera_set_member_index": None, "capture_kind": "coverage_supplement"})
            supplemental_count = len(supplemental)
    sets = []
    for item in selected_sets:
        members = [pose for pose in poses if item["camera_set_id"] in pose["camera_set_ids"]]
        if len(members) >= CAMERA_SET_MIN:
            sets.append({
                "camera_set_id": item["camera_set_id"], "anchor_id": item["anchor_id"],
                "anchor": item["anchor"], "member_count": len(members),
                "viewpoint_ids": [member["viewpoint_id"] for member in members],
                "azimuth_span_deg": round(_azimuth_span([float(member["azimuth_deg"]) for member in members]), 6),
            })
        else:
            poses = [pose for pose in poses if item["camera_set_id"] not in pose["camera_set_ids"]]
    payload = {
        "schema": CAMERA_SET_SCHEMA,
        "profile": PROFILE,
        "sampler_version": SAMPLER_VERSION,
        "source_graph_digest": stable_digest(graph),
        "source_probe_digest": stable_digest(probe) if probe else None,
        "sampling_seed": int(seed),
        "requested_pose_count": int(pose_budget),
        "actual_pose_count": len(poses),
        "camera_sets": sets,
        "poses": poses,
        "independent_pose_count": len(poses),
        "supplemental_pose_count": supplemental_count,
    }
    payload["camera_set_digest"] = stable_digest(payload)
    return payload


def acceptance_report(camera_sets: dict[str, Any], *, composition: dict[str, Any] | None = None,
                      probe: dict[str, Any] | None = None, min_pose_count: int = MIN_ACCEPTED_POSES) -> dict[str, Any]:
    """Evaluate the durable primary-frame and multi-view contract from probe metrics."""
    poses = list(camera_sets.get("poses") or [])
    failures: list[str] = []
    if len(poses) < int(min_pose_count):
        failures.append("insufficient_anchor_multiview_poses")
    set_rows = list(camera_sets.get("camera_sets") or [])
    if not set_rows:
        failures.append("no_valid_camera_sets")
    for row in set_rows:
        if not CAMERA_SET_MIN <= int(row.get("member_count") or 0) <= CAMERA_SET_MAX:
            failures.append(f"invalid_camera_set_size:{row.get('camera_set_id')}")
        if float(row.get("azimuth_span_deg") or 0.0) < MIN_AZIMUTH_SPAN_DEG:
            failures.append(f"insufficient_camera_set_azimuth:{row.get('camera_set_id')}")
    primary_failures = 0
    for pose in poses:
        metric = dict(pose.get("probe") or {})
        if not metric:
            continue  # A renderer-less unit-test selection cannot claim a primary-frame pass.
        valid = (
            int(metric.get("visible_pbr_object_count") or 0) >= 10
            and int(metric.get("material_id_count") or 0) >= 8
            and int(metric.get("specular_eligible_object_count") or 0) >= 8
            and float(metric.get("object_pixel_fraction") or 0) >= .0025
            and .12 <= float(metric.get("specular_pixel_fraction") or 0) <= .45
            and int(metric.get("roughness_bin_count") or 0) >= 3
            and float(metric.get("structural_or_empty_fraction") or 1.0) <= .55
            and not metric.get("wall_only") and not metric.get("severe_occlusion")
        )
        if not valid:
            primary_failures += 1
    if poses and primary_failures == len([pose for pose in poses if pose.get("probe")]):
        failures.append("no_primary_frame_passed")
    payload = {
        "schema": ACCEPTANCE_SCHEMA,
        "profile": PROFILE,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "actual_pose_count": len(poses),
        "camera_set_count": len(set_rows),
        "primary_frame_failure_count": primary_failures,
        "source_camera_set_digest": camera_sets.get("camera_set_digest") or stable_digest(camera_sets),
        "composition_digest": (composition or {}).get("composition_digest"),
        "probe_digest": stable_digest(probe) if probe else None,
    }
    payload["acceptance_digest"] = stable_digest(payload)
    return payload
