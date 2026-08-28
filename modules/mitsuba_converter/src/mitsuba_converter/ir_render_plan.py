"""Deterministic camera-pose and indoor-lighting plans for IR datasets.

The navigation graph remains authoritative for traversability.  This module
only selects an immutable IR rendering subset from that graph.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "robomituba.ir_principled_render_plan.v1"
SAMPLER_VERSION = "coverage-fps-pose-heading-v2"
CONTENT_PLAN_SCHEMA = "robomituba.ir_principled_render_plan.v2"
ILLUMINATION_PLAN_SCHEMA = "robomituba.ir_principled_render_plan.v3"
ILLUMINATION_REFERENCE_PLAN_SCHEMA = "robomituba.ir_principled_render_plan.v4"
CONTENT_SAMPLER_VERSION = "content-aware-fps-v2"
LIGHTING_PRESET_VERSION = "indoor-capture-groups-v1"
LIGHTING_PRESETS = (
    {"id": "balanced_day_v1", "label": "Balanced day", "native_energy_scale": 1.0,
     "ambient_fill_scale": 1.0, "rgb_color_multiplier": [1.0, 1.0, 1.0], "side_key": False},
    {"id": "warm_evening_v1", "label": "Warm evening", "native_energy_scale": 0.85,
     "ambient_fill_scale": 0.9, "rgb_color_multiplier": [1.0, 0.70, 0.45], "side_key": False},
    {"id": "cool_bright_v1", "label": "Cool bright", "native_energy_scale": 1.25,
     "ambient_fill_scale": 1.2, "rgb_color_multiplier": [0.92, 0.98, 1.0], "side_key": False},
    {"id": "side_key_v1", "label": "Side key", "native_energy_scale": 1.0,
     "ambient_fill_scale": 1.0, "rgb_color_multiplier": [0.98, 0.98, 1.0], "side_key": True,
     "key_energy_scale": 1.45, "opposite_energy_scale": 0.35},
)


def stable_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _position(node: dict[str, Any]) -> tuple[float, float]:
    raw = list(node.get("position") or ())
    if len(raw) < 2:
        raise ValueError(f"viewpoint {node.get('node_id')!r} lacks a planar position")
    return float(raw[0]), float(raw[1])


def _axis(points: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    if not points:
        return [0.0, 0.0], [1.0, 0.0]
    cx = sum(point[0] for point in points) / len(points)
    cy = sum(point[1] for point in points) / len(points)
    xx = sum((x - cx) ** 2 for x, _ in points)
    yy = sum((y - cy) ** 2 for _, y in points)
    xy = sum((x - cx) * (y - cy) for x, y in points)
    angle = 0.5 * math.atan2(2.0 * xy, xx - yy) if xx + yy > 1e-12 else 0.0
    return [cx, cy], [math.cos(angle), math.sin(angle)]


def _distance(a: dict[str, Any], b: dict[str, Any], spatial_scale: float) -> float:
    dx, dy = a["position_xy"][0] - b["position_xy"][0], a["position_xy"][1] - b["position_xy"][1]
    spatial = math.hypot(dx, dy) / max(spatial_scale, 1e-6)
    delta = abs((a["heading_deg"] - b["heading_deg"] + 180.0) % 360.0 - 180.0) / 180.0
    return spatial + 0.35 * delta


def _camera_key(item: dict[str, Any]) -> tuple[str, float, str]:
    """Distinguish two anchor sets that intentionally share one graph node."""
    return (str(item["viewpoint_id"]), round(float(item["heading_deg"]) % 360.0, 6), str(item.get("anchor_id") or ""))


def _fps(candidates: list[dict[str, Any]], count: int, rng: random.Random, spatial_scale: float) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    remaining = list(candidates)
    selected = [remaining.pop(rng.randrange(len(remaining)))]
    while remaining and len(selected) < count:
        scores = [min(_distance(candidate, current, spatial_scale) for current in selected) for candidate in remaining]
        best = max(scores)
        # Deterministic random tie breaking avoids lexicographic node-id bias.
        choices = [index for index, score in enumerate(scores) if abs(score - best) <= 1e-12]
        selected.append(remaining.pop(choices[rng.randrange(len(choices))]))
    return selected


def _visibility_entry(visibility: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
    key = f"{candidate['viewpoint_id']}@{candidate['heading_deg'] % 360.0:.6f}"
    return (visibility.get("candidates") or {}).get(key)


def _adaptive_cap(candidates: list[dict[str, Any]]) -> tuple[int, str]:
    xs = [item["position_xy"][0] for item in candidates]
    ys = [item["position_xy"][1] for item in candidates]
    area = max(max(xs) - min(xs), 1.0) * max(max(ys) - min(ys), 1.0)
    if area < 35.0:
        return 240, "small"
    if area < 90.0:
        return 320, "medium"
    return 400, "large"


def _content_select(candidates: list[dict[str, Any]], visibility: dict[str, Any], count: int,
                    rng: random.Random, spatial_scale: float, *, max_headings_per_node: int,
                    sparse_fraction: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accepted: dict[str, list[dict[str, Any]]] = {name: [] for name in ("informative", "structural", "sparse_negative")}
    rejected = 0
    signatures: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        features = _visibility_entry(visibility, candidate)
        if not features or features.get("utility_class") == "rejected":
            rejected += 1
            continue
        candidate = {**candidate, "utility": features}
        # Collapse exact same node/heading content signatures before sampling.
        signature = (candidate["viewpoint_id"], round(candidate["heading_deg"] % 360.0, 4),
                     tuple(features.get("visible_categories") or ()), round(float(features.get("nonstructural_fraction", 0)), 2))
        if signature in signatures:
            rejected += 1
            continue
        signatures.add(signature)
        accepted.setdefault(str(features.get("utility_class")), []).append(candidate)
    target = min(count, sum(len(values) for values in accepted.values()))
    quotas = {
        "informative": round(target * 0.60),
        "structural": round(target * (1.0 - 0.60 - sparse_fraction)),
        "sparse_negative": math.floor(target * sparse_fraction),
    }
    quotas["informative"] += target - sum(quotas.values())
    selected: list[dict[str, Any]] = []
    per_node: dict[str, int] = {}
    for utility_class in ("informative", "structural", "sparse_negative"):
        ranked = sorted(accepted[utility_class], key=lambda item: (-float(item["utility"].get("utility_score", 0)), item["viewpoint_id"], item["heading_deg"]))
        # FPS keeps spatial/heading coverage; high utility breaks otherwise similar candidates.
        pool = _fps(ranked, len(ranked), rng, spatial_scale) if ranked else []
        for candidate in pool:
            if sum(item["utility"]["utility_class"] == utility_class for item in selected) >= quotas[utility_class]:
                break
            node_id = candidate["viewpoint_id"]
            if per_node.get(node_id, 0) >= max_headings_per_node:
                continue
            selected.append(candidate); per_node[node_id] = per_node.get(node_id, 0) + 1
    # Redistribute unfillable quota without violating the sparse-negative ceiling.
    leftovers = sorted((item for name in ("informative", "structural") for item in accepted[name] if item not in selected),
                       key=lambda item: (-float(item["utility"].get("utility_score", 0)), item["viewpoint_id"], item["heading_deg"]))
    for candidate in leftovers:
        if len(selected) >= target:
            break
        node_id = candidate["viewpoint_id"]
        if per_node.get(node_id, 0) < max_headings_per_node:
            selected.append(candidate); per_node[node_id] = per_node.get(node_id, 0) + 1
    non_sparse_count = sum(item["utility"]["utility_class"] != "sparse_negative" for item in selected)
    sparse_limit = math.floor(non_sparse_count * sparse_fraction / max(1.0 - sparse_fraction, 1e-9))
    sparse_seen = 0
    capped: list[dict[str, Any]] = []
    for item in selected:
        if item["utility"]["utility_class"] == "sparse_negative":
            sparse_seen += 1
            if sparse_seen > sparse_limit:
                continue
        capped.append(item)
    selected = capped
    metadata = {"quota": quotas, "class_counts": {name: sum(item["utility"]["utility_class"] == name for item in selected) for name in quotas},
                "rejected_candidate_count": rejected, "accepted_candidate_count": sum(len(v) for v in accepted.values())}
    return selected, metadata


def build_render_plan(graph: dict[str, Any], *, requested_pose_count: int, seed: int, scene_id: str,
                      visibility: dict[str, Any] | None = None, adaptive_budget: bool = False,
                      max_headings_per_node: int = 6, sparse_fraction: float = 0.15,
                      reserve_fraction: float = 0.20, illumination: dict[str, Any] | None = None,
                      paired_fraction: float = 0.25, camera_sets: dict[str, Any] | None = None,
                      showcase_provenance: dict[str, Any] | None = None,
                      min_unique_pose_count: int = 1,
                      illumination_pairing_policy: str = "legacy_six_way_v1") -> dict[str, Any]:
    """Select unique node-heading poses in balanced lighting capture groups."""
    if requested_pose_count < 1:
        raise ValueError("requested_pose_count must be positive")
    candidates: list[dict[str, Any]] = []
    if camera_sets is not None:
        # Showcase cameras are already assembled from walkable nodes and look
        # at their local anchor.  Do not resurrect OpticalNav's heading sweep.
        for pose in camera_sets.get("poses") or []:
            if not isinstance(pose, dict) or not pose.get("viewpoint_id"):
                continue
            candidate = dict(pose)
            candidate["heading_deg"] = float(candidate.get("heading_deg") or 0.0)
            candidate["position_xy"] = list(_position({"position": candidate.get("position_xy")}))
            candidates.append(candidate)
    else:
        for node in graph.get("nodes") or []:
            node_id = str(node.get("node_id") or "")
            if not node_id:
                continue
            position_xy = _position(node)
            for heading in node.get("headings") or []:
                candidates.append({"viewpoint_id": node_id, "heading_deg": float(heading.get("yaw_deg", 0.0)), "position_xy": list(position_xy)})
    candidates.sort(key=lambda item: (item["viewpoint_id"], item["heading_deg"], str(item.get("anchor_id") or "")))
    if not candidates:
        raise ValueError("viewpoint graph has no node-heading candidates")
    room_cap, room_size_class = _adaptive_cap(candidates)
    target = int(requested_pose_count) if camera_sets is not None else (
        min(int(requested_pose_count), room_cap) if adaptive_budget else int(requested_pose_count)
    )
    actual = min(target, len(candidates))
    points = [tuple(item["position_xy"]) for item in candidates]
    center, side_axis = _axis(points)
    span = max(math.hypot(x - center[0], y - center[1]) for x, y in points) * 2.0
    rng = random.Random(int(seed))
    selection_meta = None
    if camera_sets is not None:
        # build_camera_sets has already applied the anchor-set cardinality,
        # clearance and baseline invariants.  Preserve each selected pose.
        remaining = list(candidates)
    elif visibility is not None:
        selected_all, selection_meta = _content_select(candidates, visibility, actual, rng, span,
                                                       max_headings_per_node=max_headings_per_node,
                                                       sparse_fraction=sparse_fraction)
        actual = len(selected_all)
        remaining = list(selected_all)
    else:
        # Coverage mode has no visibility probe, but it must still honour the
        # requested/adaptive pose budget.  The previous implementation left
        # every graph candidate here, which only became visible after the
        # lighting expansion multiplied the accidental excess by six.
        remaining = _fps(candidates, actual, rng, span) if not illumination else list(candidates)
    groups = []
    if illumination:
        conditions = list(illumination.get("conditions") or [])
        if len(conditions) != 6:
            raise ValueError("illumination diversity requires six conditions")
        if illumination_pairing_policy not in {"legacy_six_way_v1", "reference_subset_v2"}:
            raise ValueError(f"unsupported illumination pairing policy: {illumination_pairing_policy}")
        fraction = max(0.0, min(1.0, float(paired_fraction)))
        paired_count = min(actual, max(1, round(actual * fraction)))
        if illumination_pairing_policy == "reference_subset_v2":
            reference_indices = [index for index, condition in enumerate(conditions)
                                 if str(condition.get("id") or "") == "reference_neutral_v1"]
            if len(reference_indices) != 1:
                raise ValueError("reference_subset_v2 requires exactly one reference_neutral_v1 condition")
            reference_index = reference_indices[0]
            base_poses = _fps(remaining, actual, rng, span) if len(remaining) > actual else list(remaining)
            actual = len(base_poses)
            variation_indices = [index for index in range(len(conditions)) if index != reference_index]
            variation_pool = list(base_poses)
            variation_groups: dict[int, list[dict[str, Any]]] = {}
            for ordinal, condition_index in enumerate(variation_indices):
                groups_left = len(variation_indices) - ordinal
                quota = len(variation_pool) // groups_left if groups_left else 0
                selected = _fps(variation_pool, quota, rng, span)
                selected_keys = {_camera_key(item) for item in selected}
                variation_pool = [item for item in variation_pool if _camera_key(item) not in selected_keys]
                variation_groups[condition_index] = selected

            def paired_pose(pose: dict[str, Any], member_index: int) -> dict[str, Any]:
                anchor_key = str(pose.get("anchor_id") or "")
                pair_id = f"{scene_id}:{pose['viewpoint_id']}:{pose['heading_deg'] % 360.0:.3f}:{anchor_key}"
                return {**pose, "capture_kind": "paired", "pair_id": pair_id,
                        "pair_member_index": member_index}

            for index, condition in enumerate(conditions):
                external_id = str(condition["external_asset"])
                asset = dict((illumination.get("assets") or {}).get(external_id) or {})
                recipe = {
                    "id": str(condition["id"]), "label": str(condition["id"]),
                    "version": "illumination-reference-subset-v2",
                    "native_energy_scale": float(condition.get("internal_energy_scale", 1.0)),
                    "ambient_fill_scale": 1.0,
                    "rgb_color_multiplier": list(condition.get("internal_color") or (1.0, 1.0, 1.0)),
                    "side_key": bool(condition.get("side_key", False)),
                    "key_energy_scale": float(condition.get("key_energy_scale", 1.45)),
                    "opposite_energy_scale": float(condition.get("opposite_energy_scale", 0.35)),
                    "side_axis_xy": side_axis, "side_center_xy": center,
                    "external": {"asset_id": external_id, "path": asset.get("path"), "sha256": asset.get("sha256"),
                                 "world_strength": float(condition.get("world_strength", 0.0)),
                                 "portal_strength": float(condition.get("portal_strength", 0.0))},
                }
                recipe["recipe_digest"] = stable_digest(recipe)
                poses = ([paired_pose(pose, 0) for pose in base_poses] if index == reference_index
                         else [paired_pose(pose, 1) for pose in variation_groups[index]])
                groups.append({"lighting": recipe,
                               "capture_group_id": f"{scene_id}:{recipe['id']}", "poses": poses})
            paired_count = actual
            singles = []
        else:
            # Legacy contract: one subset is repeated under every condition;
            # remaining poses receive exactly one condition.
            paired = _fps(remaining, paired_count, rng, span)
            paired_keys = {_camera_key(item) for item in paired}
            legacy_singles = [item for item in remaining if _camera_key(item) not in paired_keys]
            legacy_single_groups = [
                [pose for ordinal, pose in enumerate(legacy_singles) if ordinal % len(conditions) == index]
                for index in range(len(conditions))
            ]
            single_total = max(0, actual - paired_count)
            single_quotas = [single_total // len(conditions) + (1 if index < single_total % len(conditions) else 0)
                             for index in range(len(conditions))]
            selected_singles = [_fps(pool, quota, rng, span)
                                for pool, quota in zip(legacy_single_groups, single_quotas)]
            singles = [pose for group in selected_singles for pose in group]
            for index, condition in enumerate(conditions):
                external_id = str(condition["external_asset"])
                asset = dict((illumination.get("assets") or {}).get(external_id) or {})
                recipe = {
                    "id": str(condition["id"]), "label": str(condition["id"]),
                    "version": "illumination-diversity-paired-v1",
                    "native_energy_scale": float(condition.get("internal_energy_scale", 1.0)),
                    "ambient_fill_scale": 1.0,
                    "rgb_color_multiplier": list(condition.get("internal_color") or (1.0, 1.0, 1.0)),
                    "side_key": bool(condition.get("side_key", False)),
                    "key_energy_scale": float(condition.get("key_energy_scale", 1.45)),
                    "opposite_energy_scale": float(condition.get("opposite_energy_scale", 0.35)),
                    "side_axis_xy": side_axis, "side_center_xy": center,
                    "external": {"asset_id": external_id, "path": asset.get("path"), "sha256": asset.get("sha256"),
                                 "world_strength": float(condition.get("world_strength", 0.0)),
                                 "portal_strength": float(condition.get("portal_strength", 0.0))},
                }
                recipe["recipe_digest"] = stable_digest(recipe)
                group_poses = []
                for pose in paired:
                    anchor_key = str(pose.get("anchor_id") or "")
                    pair_id = f"{scene_id}:{pose['viewpoint_id']}:{pose['heading_deg'] % 360.0:.3f}:{anchor_key}"
                    group_poses.append({**pose, "capture_kind": "paired", "pair_id": pair_id,
                                        "pair_member_index": index})
                for pose in selected_singles[index]:
                    group_poses.append({**pose, "capture_kind": "single", "pair_id": None,
                                        "pair_member_index": None})
                groups.append({"lighting": recipe, "capture_group_id": f"{scene_id}:{recipe['id']}", "poses": group_poses})
    else:
        quotas = [actual // len(LIGHTING_PRESETS) + (1 if index < actual % len(LIGHTING_PRESETS) else 0) for index in range(len(LIGHTING_PRESETS))]
        for index, (preset, quota) in enumerate(zip(LIGHTING_PRESETS, quotas)):
            selected = _fps(remaining, quota, rng, span)
            selected_keys = {_camera_key(item) for item in selected}
            remaining = [item for item in remaining if _camera_key(item) not in selected_keys]
            recipe = {**preset, "version": LIGHTING_PRESET_VERSION, "side_axis_xy": side_axis, "side_center_xy": center}
            recipe["recipe_digest"] = stable_digest(recipe)
            groups.append({"lighting": recipe, "capture_group_id": f"{scene_id}:{preset['id']}", "poses": selected})
    # Count physical camera poses after lighting assignment.  A paired pose
    # appears in every condition group but must count once for the minimum.
    unique_selected = {_camera_key(pose) for group in groups for pose in group.get("poses") or []}
    if len(unique_selected) < int(min_unique_pose_count):
        raise ValueError(f"independent camera pose minimum not met: {len(unique_selected)} < {int(min_unique_pose_count)} (lighting ignored)")
    plan_core = {
        "schema": ((ILLUMINATION_REFERENCE_PLAN_SCHEMA if illumination_pairing_policy == "reference_subset_v2"
                    else ILLUMINATION_PLAN_SCHEMA) if illumination else
                   (CONTENT_PLAN_SCHEMA if (visibility is not None or camera_sets is not None) else PLAN_SCHEMA)),
        "sampler_version": "anchor-centric-walkable-v1" if camera_sets is not None else (CONTENT_SAMPLER_VERSION if visibility is not None else SAMPLER_VERSION), "scene_id": scene_id,
        "source_graph_digest": stable_digest(graph),
        "sampling_seed": int(seed), "requested_pose_count": int(requested_pose_count), "actual_pose_count": actual,
        "candidate_pose_count": len(candidates), "clamped": actual != int(requested_pose_count),
        "unique_pose_count": len(unique_selected), "min_unique_pose_count": int(min_unique_pose_count),
        "clamp_reason": ("utility_candidates" if visibility is not None and actual < min(target, len(candidates)) else
                         "adaptive_room_cap" if adaptive_budget and target < int(requested_pose_count) else
                         "candidate_pose_count" if actual != int(requested_pose_count) else None),
        "lighting_preset_version": LIGHTING_PRESET_VERSION, "lighting_group_count": len(groups),
        "scene_center_xy": center, "side_key_axis_xy": side_axis, "groups": groups,
    }
    if illumination:
        variation_counts = {group["lighting"]["id"]: len(group["poses"]) for group in groups}
        plan_core["illumination"] = {"contract": illumination.get("contract"), "manifest_digest": illumination.get("manifest_digest"),
                                      "pairing_policy": illumination_pairing_policy,
                                      "paired_fraction": float(paired_fraction), "paired_pose_count": paired_count,
                                      "single_pose_count": len(singles), "condition_count": len(conditions),
                                      "reference_condition_id": "reference_neutral_v1" if illumination_pairing_policy == "reference_subset_v2" else None,
                                      "base_pose_count": actual if illumination_pairing_policy == "reference_subset_v2" else None,
                                      "condition_pose_counts": variation_counts,
                                      "expected_frame_count": sum(variation_counts.values())}
    if visibility is not None:
        selected_keys = {(pose["viewpoint_id"], pose["heading_deg"]) for group in groups for pose in group["poses"]}
        reserve_pool = [item for item in candidates if (item["viewpoint_id"], item["heading_deg"]) not in selected_keys
                        and (_visibility_entry(visibility, item) or {}).get("utility_class") != "rejected"]
        reserve_count = min(len(reserve_pool), math.ceil(actual * reserve_fraction))
        plan_core.update({"source_visibility_digest": visibility.get("probe_digest") or stable_digest(visibility),
                          "adaptive_budget": bool(adaptive_budget), "room_size_class": room_size_class,
                          "room_pose_cap": room_cap, "max_headings_per_node": max_headings_per_node,
                          "sparse_negative_max_fraction": sparse_fraction, "selection": selection_meta,
                          "reserve_poses": _fps(reserve_pool, reserve_count, rng, span)})
    if camera_sets is not None:
        plan_core["camera_sets"] = {
            "camera_set_digest": camera_sets.get("camera_set_digest"),
            "camera_set_count": len(camera_sets.get("camera_sets") or []),
            "sets": list(camera_sets.get("camera_sets") or []),
        }
        plan_core["showcase_provenance"] = dict(showcase_provenance or {})
    digest = stable_digest(plan_core)
    return {**plan_core, "render_plan_id": digest[:16], "render_plan_digest": digest}


def write_render_plan(path: Path, graph_path: Path, *, requested_pose_count: int, seed: int, scene_id: str,
                      visibility_path: Path | None = None, adaptive_budget: bool = False,
                      max_headings_per_node: int = 6, sparse_fraction: float = 0.15,
                      illumination: dict[str, Any] | None = None, paired_fraction: float = 0.25,
                      camera_sets_path: Path | None = None,
                      showcase_provenance: dict[str, Any] | None = None,
                      min_unique_pose_count: int = 1,
                      illumination_pairing_policy: str = "legacy_six_way_v1") -> dict[str, Any]:
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    visibility = json.loads(visibility_path.read_text(encoding="utf-8")) if visibility_path else None
    camera_sets = json.loads(camera_sets_path.read_text(encoding="utf-8")) if camera_sets_path else None
    # A showcase raster probe is a broader durable report whose selected
    # camera-set contract is nested under ``camera_sets``.  Accept that report
    # directly so plan provenance binds to the exact raster selection.
    if camera_sets is not None and isinstance(camera_sets.get("camera_sets"), dict):
        camera_sets = dict(camera_sets["camera_sets"])
    plan = build_render_plan(graph, requested_pose_count=requested_pose_count, seed=seed, scene_id=scene_id,
                             visibility=visibility, adaptive_budget=adaptive_budget,
                             max_headings_per_node=max_headings_per_node, sparse_fraction=sparse_fraction,
                             illumination=illumination, paired_fraction=paired_fraction,
                             camera_sets=camera_sets, showcase_provenance=showcase_provenance,
                             min_unique_pose_count=min_unique_pose_count,
                             illumination_pairing_policy=illumination_pairing_policy)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return plan
