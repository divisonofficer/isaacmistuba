"""Staged, pre-rendered navigation support graphs.

``adaptive_navigation_support_v4`` deliberately keeps topology authoring, route
approval, and dense action-space materialisation separate.  The old v3 route
motion sidecars remain readable but are never changed by this module.

The implementation is intentionally JSON-sidecar based so a support graph can be
audited before any expensive render tasks are submitted.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha1
import heapq
import json
import math
import os
from pathlib import Path
import random
import shutil
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence

from .episode_schema import EpisodeManifest, EpisodeTimestep
from .graph_episode_sampler import GraphPath, shortest_graph_path
from .scene_annotations import SceneAnnotation
from .traversability import TraversabilityGrid, cell_to_world
from .viewpoint_graph import ViewpointGraph, ViewpointHeading, ViewpointNode

# Reuse the collision-tested continuous 15-degree action primitive.  These
# helpers are geometry utilities, not v3 route/backbone policy.
from .route_motion import (
    _action_grid_path,
    _all_heading_ids,
    _distance,
    _edge_points,
    _heading_id,
    _nearest_safe_cell,
    _portal_is_open,
    _v3_portal_aware_grid,
    _world_segment_safe,
    _yaw_to,
)


PROFILE_ID = "adaptive_navigation_support_v4"
SCHEMA_VERSION = "opticalnav.adaptive_navigation_support.v4"
PLACE_GRAPH_FILE = "place_graph.json"
BLUEPRINTS_FILE = "route_blueprints.json"
SUPPORT_GRAPH_FILE = "navigation_support_graph.json"
OBSERVATION_PLAN_FILE = "support_observation_plan.json"
RENDER_GRAPH_FILE = "support_render_graph.json"
MOTION_GRID_FILE = "navigation_support_motion_grid.npy"
SUPPORT_ARCHIVE_DIR = "navigation_support_archives"

# The base support plan is deliberately small enough to make every executable
# action state available.  Context around those action headings can be grown
# later without rebuilding lanes, invalidating episodes, or mixing an
# interpolated image into the canonical observation set.  Each level is
# cumulative relative to L0: submitting L2 after L1 is therefore safe with
# ``only_missing`` and submitting L2 directly still fills its complete native
# +/-30 degree neighbourhood.
OBSERVATION_EXPANSION_SCHEMA_VERSION = "opticalnav.adaptive_navigation_support.v4.observation_expansion"
OBSERVATION_EXPANSION_FILE_PREFIX = "support_observation_expansion_"
OBSERVATION_EXPANSION_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "level_id": "l0_action_required",
        "label": "L0 · action-required headings",
        "context_radius_steps": 0,
        "description": "Only headings required by executable 15° actions, plus PANORAMA_12 core poses.",
    },
    {
        "level_id": "l1_context_15",
        "label": "L1 · ±15° action context",
        "context_radius_steps": 1,
        "description": "Add immediate left/right native context around every detail action heading.",
    },
    {
        "level_id": "l2_context_30",
        "label": "L2 · ±30° action context",
        "context_radius_steps": 2,
        "description": "Complete the cumulative native ±30° context around detail action headings.",
    },
    {
        "level_id": "l3_context_45",
        "label": "L3 · ±45° action context",
        "context_radius_steps": 3,
        "description": "Complete the cumulative native ±45° context around detail action headings.",
    },
    {
        "level_id": "l4_context_60",
        "label": "L4 · ±60° action context",
        "context_radius_steps": 4,
        "description": "Complete the cumulative native ±60° context around detail action headings.",
    },
    {
        "level_id": "l5_context_75",
        "label": "L5 · ±75° action context",
        "context_radius_steps": 5,
        "description": "Complete the cumulative native ±75° context around detail action headings.",
    },
    {
        "level_id": "l6_detail_full_24",
        "label": "L6 · detail pose full 24",
        "context_radius_steps": 6,
        "description": "Make every non-core detail pose a complete native 24-heading panorama.",
    },
)

DEFAULT_CONFIG: dict[str, Any] = {
    "profile_id": PROFILE_ID,
    "place_heading_count": 12,
    "action_heading_count": 24,
    "turn_deg": 15.0,
    "forward_step_m": 0.25,
    "forward_tolerance_m": 0.025,
    "robot_radius_m": 0.25,
    "safety_margin_m": 0.10,
    "geometry_epsilon_m": 0.03,
    # Imported Infinigen authoring regions can leave a 0.60–0.75 m floor-mask
    # discontinuity at a physically open doorway. This threshold-span bound
    # never bypasses the body-height wall or portal certification checks.
    "doorway_gap_m": 0.75,
    "max_place_nodes": 300,
    "max_support_poses": 2000,
    "max_panorama_poses": 80,
    "max_polar_observations": 8000,
    "max_polar_batches": 3200,
    "trunk_demand_coverage": 0.95,
    "lane_offset_m": 0.25,
    "junction_patch_radius_m": 0.75,
    "portal_patch_radius_m": 0.75,
    "goal_patch_radius_m": 0.50,
    # Place-graph centre lines are collision-certified, but their endpoint
    # raster phase can require a short local action detour around a corner.
    # This remains smaller than a support patch and every emitted chord is
    # still checked against the 0.38 m-eroded motion grid.
    "action_corridor_radius_m": 0.75,
    "min_pose_spacing_m": 0.15,
    "directness_stretch": 1.15,
    "directness_slack_m": 0.75,
    "heading_render_seconds": 30.24,
}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def _read_json_mapping(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _archive_copy(source: Path, destination: Path) -> None:
    """Copy one sidecar atomically without ever exposing a partial archive."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def support_lock_summary(scene_dir: str | Path) -> dict[str, Any] | None:
    """Describe a complete current v4 support build that must be confirmed before edits.

    A sparse place graph remains editable until both the action graph and its
    baseline observation plan exist and carry the same validation digest.  This
    intentionally ignores historical/archive sidecars: only the current v4
    workflow is locked.
    """
    root = Path(scene_dir)
    graph = _read_json_mapping(root / SUPPORT_GRAPH_FILE)
    plan = _read_json_mapping(root / OBSERVATION_PLAN_FILE)
    if not graph or not plan:
        return None
    digest = str((graph.get("validation") or {}).get("digest") or "")
    if (
        str(graph.get("profile_id") or "") != PROFILE_ID
        or str(plan.get("profile_id") or "") != PROFILE_ID
        or not digest
        or digest != str(graph.get("profile_digest") or "")
        or digest != str(plan.get("profile_digest") or "")
        or digest != str(plan.get("validation_digest") or "")
    ):
        return None
    return {
        "profile_digest": digest,
        "place_graph_id": str(plan.get("place_graph_id") or ""),
        "support_pose_count": int((plan.get("summary") or {}).get("support_pose_count") or 0),
        "polar_observation_count": int((plan.get("summary") or {}).get("polar_observation_count") or 0),
    }


def archive_navigation_support(
    scene_dir: str | Path,
    *,
    reason: str,
) -> dict[str, Any] | None:
    """Preserve the current support contract before a topology edit invalidates it.

    Archives are immutable render/audit evidence, not another active workflow.
    The current canonical sidecars are still removed by the caller, so episodes
    cannot silently mix an edited place graph with a stale support graph.
    """
    root = Path(scene_dir)
    lock = support_lock_summary(root)
    if lock is None:
        return None
    digest = str(lock["profile_digest"])
    archive_root = root / SUPPORT_ARCHIVE_DIR / digest
    files: list[Path] = [
        root / PLACE_GRAPH_FILE,
        root / BLUEPRINTS_FILE,
        root / SUPPORT_GRAPH_FILE,
        root / OBSERVATION_PLAN_FILE,
        root / RENDER_GRAPH_FILE,
    ]
    for path in root.glob(f"{OBSERVATION_EXPANSION_FILE_PREFIX}*.json"):
        payload = _read_json_mapping(path)
        if payload and str(payload.get("profile_digest") or "") == digest:
            files.append(path)
    for path in root.glob("support_render_graph_*.json"):
        payload = _read_json_mapping(path)
        metadata = payload.get("metadata") if payload else None
        if isinstance(metadata, Mapping) and str(metadata.get("profile_digest") or "") == digest:
            files.append(path)
    copied: list[str] = []
    for path in files:
        if not path.is_file():
            continue
        _archive_copy(path, archive_root / path.name)
        copied.append(path.name)
    manifest = {
        "schema_version": "opticalnav.navigation_support_archive.v1",
        "profile_id": PROFILE_ID,
        "profile_digest": digest,
        "reason": str(reason),
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "active": False,
        "lock": lock,
        "files": sorted(set(copied)),
    }
    _atomic_json(archive_root / "archive_manifest.json", manifest)
    return {
        "archive_ref": (Path(SUPPORT_ARCHIVE_DIR) / digest).as_posix(),
        "profile_digest": digest,
        "files": manifest["files"],
    }


def latest_support_render_archive(scene_dir: str | Path) -> dict[str, Any] | None:
    """Return a compact, read-only render-plan and pose overlay from an archive.

    A topology edit deliberately removes the active support graph because it is
    no longer safe to create episodes from it.  It must not, however, make an
    already submitted render contract disappear from the editor.  This helper
    exposes only the pose overlay, render-pose graph, and summary from the newest
    qualified archive; it never makes the archived graph executable again.
    """
    root = Path(scene_dir)
    archive_root = root / SUPPORT_ARCHIVE_DIR
    candidates: list[tuple[str, dict[str, Any]]] = []
    if not archive_root.is_dir():
        return None
    for manifest_path in sorted(archive_root.glob("*/archive_manifest.json")):
        manifest = _read_json_mapping(manifest_path)
        if not manifest or str(manifest.get("profile_id") or "") != PROFILE_ID:
            continue
        plan_path = manifest_path.parent / OBSERVATION_PLAN_FILE
        plan = _read_json_mapping(plan_path)
        if not plan or str(plan.get("profile_id") or "") != PROFILE_ID:
            continue
        if str(plan.get("profile_digest") or "") != str(manifest.get("profile_digest") or ""):
            continue
        poses = plan.get("poses")
        if not isinstance(poses, list) or not poses:
            continue
        # ``support_render_graph.json`` is deliberately a render-only graph: it
        # has the canonical recovered pose positions but no executable edges.
        # Return only the fields the editor needs so an archived support plan
        # remains inspectable after a page refresh without accidentally looking
        # like a live Stage-3 action graph.
        render_graph = _read_json_mapping(manifest_path.parent / RENDER_GRAPH_FILE)
        render_metadata = render_graph.get("metadata") if render_graph else None
        render_nodes = render_graph.get("nodes") if render_graph else None
        if (
            not isinstance(render_metadata, Mapping)
            or str(render_metadata.get("profile_id") or "") != PROFILE_ID
            or str(render_metadata.get("profile_digest") or "") != str(manifest.get("profile_digest") or "")
            or not isinstance(render_nodes, list)
        ):
            render_graph_payload = None
        else:
            render_graph_payload = {
                "graph_id": str(render_graph.get("graph_id") or ""),
                "nodes": [
                    {
                        "node_id": str(node.get("node_id") or ""),
                        "position": list(node.get("position") or []),
                        "tags": list(node.get("tags") or []),
                    }
                    for node in render_nodes
                    if isinstance(node, Mapping)
                    and str(node.get("node_id") or "")
                    and isinstance(node.get("position"), list)
                ],
                # Deliberately omit the historical action graph. The archive is
                # an observation/render contract, not a safe graph after a
                # place-topology edit.
                "edges": [],
                "metadata": {
                    "profile_id": PROFILE_ID,
                    "profile_digest": str(render_metadata.get("profile_digest") or ""),
                    "render_only": True,
                    "read_only": True,
                },
            }
        candidates.append((str(manifest.get("archived_at") or manifest_path.parent.name), {
            "archive_ref": (Path(SUPPORT_ARCHIVE_DIR) / manifest_path.parent.name).as_posix(),
            "profile_digest": str(manifest.get("profile_digest") or ""),
            "recovered": bool(manifest.get("recovered")),
            "read_only": True,
            "render_graph": render_graph_payload,
            "observation_plan": {
                "profile_id": str(plan.get("profile_id") or ""),
                "profile_digest": str(plan.get("profile_digest") or ""),
                "validation_digest": str(plan.get("validation_digest") or ""),
                "poses": poses,
                "summary": dict(plan.get("summary") or {}),
            },
        }))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def recover_l0_observation_plan_from_expansion(
    expansion: Mapping[str, Any],
    *,
    support_graph_ref: str,
) -> dict[str, Any]:
    """Recover an exact L0 plan from an immutable L1–L6 expansion context.

    Expansion sidecars retain every base pose and its pre-expansion
    ``action_heading_ids``.  Reapplying L0's PANORAMA_12 union rule therefore
    reconstructs the original entries and K=4 grouping byte-for-byte at the
    logical-view level, without inventing new headings.
    """
    if str(expansion.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("not an adaptive_navigation_support_v4 expansion")
    if str(expansion.get("plan_kind") or "") != "observation_expansion":
        raise ValueError("recovery source must be an observation expansion")
    profile_digest = str(expansion.get("profile_digest") or "")
    validation_digest = str(expansion.get("validation_digest") or "")
    if not profile_digest or profile_digest != validation_digest:
        raise ValueError("observation expansion digest mismatch")
    raw_poses = expansion.get("poses")
    if not isinstance(raw_poses, list) or not raw_poses:
        raise ValueError("observation expansion has no poses")
    panorama_headings = {f"h_{angle:03d}" for angle in range(0, 360, 30)}
    recovered_poses: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    action_state_count = 0
    for raw_pose in raw_poses:
        if not isinstance(raw_pose, Mapping):
            raise ValueError("observation expansion has a malformed pose")
        pose = dict(raw_pose)
        pose_id = str(pose.get("motion_node_id") or "")
        if not pose_id:
            raise ValueError("observation expansion has a pose without motion_node_id")
        action_headings = _sorted_heading_ids(pose.get("action_heading_ids") or [])
        if not action_headings:
            raise ValueError(f"observation expansion pose {pose_id} has no action headings")
        action_state_count += len(action_headings)
        tier = str(pose.get("tier") or "ACTION_NATIVE")
        available = _sorted_heading_ids(
            [*action_headings, *(panorama_headings if tier == "PANORAMA_12" else set())]
        )
        pose["action_heading_ids"] = action_headings
        pose["available_heading_ids"] = available
        recovered_poses.append(pose)
        for offset in range(0, len(available), 4):
            batch = available[offset:offset + 4]
            batch_key = f"{pose_id}:b{offset // 4:02d}"
            for heading in batch:
                entries.append({
                    "motion_node_id": pose_id,
                    "heading_id": heading,
                    "tier": tier,
                    "available_heading_ids": available,
                    "polar_batch_key": batch_key,
                    "polar_batch_size": len(batch),
                    "projection": "native_perspective",
                    "canonical": True,
                })
    batch_count = len({str(entry["polar_batch_key"]) for entry in entries})
    source_summary = dict(expansion.get("summary") or {})
    expected_entries = source_summary.get("base_polar_observation_count")
    expected_batches = source_summary.get("base_polar_batch_count")
    if expected_entries is not None and int(expected_entries) != len(entries):
        raise ValueError(f"recovered L0 entry count {len(entries)} does not match expansion base count {expected_entries}")
    if expected_batches is not None and int(expected_batches) != batch_count:
        raise ValueError(f"recovered L0 batch count {batch_count} does not match expansion base count {expected_batches}")
    config = dict(expansion.get("config") or {})
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "scene_id": str(expansion.get("scene_id") or ""),
        "place_graph_id": str(expansion.get("place_graph_id") or ""),
        "support_graph_ref": str(support_graph_ref),
        "profile_digest": profile_digest,
        "validation_digest": validation_digest,
        "heading_count": 24,
        "panoramic_heading_count": 12,
        "poses": recovered_poses,
        "render_entries": entries,
        "config": config,
        "summary": {
            "support_pose_count": len(recovered_poses),
            "action_state_count": action_state_count,
            "panorama_12_pose_count": sum(1 for pose in recovered_poses if pose.get("tier") == "PANORAMA_12"),
            "polar_observation_count": len(entries),
            "polar_batch_count": batch_count,
            "gpu_time_estimate_hours_per_polar_camera_variant": len(entries) * float(config.get("heading_render_seconds") or DEFAULT_CONFIG["heading_render_seconds"]) / 3600.0,
        },
        "recovery": {
            "kind": "l0_reconstructed_from_expansion",
            "source_coverage_level_id": str(expansion.get("coverage_level_id") or ""),
            "source_profile_digest": profile_digest,
        },
    }


def _config(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({key: value for key, value in dict(values or {}).items() if value is not None})
    for name in (
        "place_heading_count", "action_heading_count", "max_place_nodes", "max_support_poses",
        "max_panorama_poses", "max_polar_observations", "max_polar_batches",
    ):
        cfg[name] = int(cfg[name])
    for name in (
        "turn_deg", "forward_step_m", "forward_tolerance_m", "robot_radius_m", "safety_margin_m",
        "geometry_epsilon_m", "doorway_gap_m", "trunk_demand_coverage", "lane_offset_m", "junction_patch_radius_m",
        "portal_patch_radius_m", "goal_patch_radius_m", "min_pose_spacing_m", "directness_stretch",
        "directness_slack_m", "heading_render_seconds", "action_corridor_radius_m",
    ):
        cfg[name] = float(cfg[name])
    cfg["effective_clearance_m"] = round(
        cfg["robot_radius_m"] + cfg["safety_margin_m"] + cfg["geometry_epsilon_m"], 4
    )
    if cfg["place_heading_count"] != 12:
        raise ValueError("adaptive_navigation_support_v4 requires 12 place-graph headings")
    if cfg["action_heading_count"] != 24 or not math.isclose(cfg["turn_deg"], 15.0, abs_tol=1e-9):
        raise ValueError("adaptive_navigation_support_v4 requires a 24-heading / 15-degree action lattice")
    if not (0.0 < cfg["trunk_demand_coverage"] <= 1.0):
        raise ValueError("trunk_demand_coverage must be in (0, 1]")
    return cfg


def _json_digest(payload: Mapping[str, Any]) -> str:
    return sha1(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _node_map(graph: ViewpointGraph) -> dict[str, Any]:
    return {str(node.node_id): node for node in graph.nodes}


def _feature_nodes(graph: ViewpointGraph, annotation: SceneAnnotation | None) -> dict[str, set[str]]:
    """Map semantic coverage features to real sparse graph nodes."""
    nodes = _node_map(graph)
    result: dict[str, set[str]] = defaultdict(set)

    def nearest(point: Sequence[float]) -> str | None:
        if not nodes:
            return None
        node = min(nodes.values(), key=lambda item: _distance(item.position, point))
        return str(node.node_id)

    def centre(geometry: Mapping[str, Any]) -> tuple[float, float] | None:
        kind = str(geometry.get("type") or "box")
        if kind == "box":
            values = geometry.get("bounds")
            if isinstance(values, Sequence) and len(values) >= 4:
                return ((float(values[0]) + float(values[2])) / 2.0, (float(values[1]) + float(values[3])) / 2.0)
        if kind == "circle":
            values = geometry.get("center")
            if isinstance(values, Sequence) and len(values) >= 2:
                return float(values[0]), float(values[1])
        if kind == "polygon":
            points = [point for point in geometry.get("points") or [] if isinstance(point, Sequence) and len(point) >= 2]
            if points:
                return (
                    sum(float(point[0]) for point in points) / len(points),
                    sum(float(point[1]) for point in points) / len(points),
                )
        return None

    if annotation is not None:
        for region in annotation.traversable_regions:
            if region.traversable:
                node_id = nearest(centre(region.geometry) or (0.0, 0.0))
                if node_id:
                    result[f"room:{region.region_id}"].add(node_id)
        for region in annotation.goal_regions:
            node_id = nearest(region.center)
            if node_id:
                result[f"goal:{region.region_id}"].add(node_id)
        for landmark in annotation.landmarks:
            if landmark.goal_candidate:
                node_id = nearest(landmark.center)
                if node_id:
                    result[f"landmark:{landmark.landmark_id}"].add(node_id)
        hazard_centres: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for hazard in annotation.hazard_regions:
            point = centre(hazard.geometry)
            if point is not None:
                hazard_centres[str(hazard.hazard_type)].append(point)
        for kind, points in sorted(hazard_centres.items()):
            mx, my = sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)
            point = min(points, key=lambda item: _distance(item, (mx, my)))
            node_id = nearest(point)
            if node_id:
                result[f"hazard:{kind}"].add(node_id)
    for edge in graph.edges:
        portal = str((edge.extras or {}).get("portal") or "")
        if portal:
            result[f"portal:{portal}"].update((str(edge.source), str(edge.target)))
    if not result:
        for node in sorted(graph.nodes, key=lambda item: str(item.node_id))[: min(16, len(graph.nodes))]:
            result[f"coverage:{node.node_id}"].add(str(node.node_id))
    return result


def _path_edge_ids(path: GraphPath) -> list[str]:
    return [str(edge.edge_id) for edge in path.edges]


def propose_route_blueprints(
    place_graph: ViewpointGraph,
    *,
    annotation: SceneAnnotation | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate reviewable route intents; none are approved automatically."""
    cfg = _config(config)
    features = _feature_nodes(place_graph, annotation)
    all_nodes = _node_map(place_graph)
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    sorted_features = sorted(features.items())
    for feature_index, (feature_id, goal_ids) in enumerate(sorted_features):
        for goal_id in sorted(goal_ids)[:1]:
            goal = all_nodes.get(goal_id)
            if goal is None:
                continue
            starts = [node for node in all_nodes.values() if node.node_id != goal_id]
            if not starts:
                continue
            starts.sort(key=lambda node: (-_distance(node.position, goal.position), str(node.node_id)))
            start = next((node for node in starts if _distance(node.position, goal.position) >= 2.0), starts[0])
            key = (str(start.node_id), goal_id)
            try:
                path = shortest_graph_path(place_graph, *key)
            except ValueError:
                continue
            item = candidates.get(key)
            if item is None:
                item = {
                    "blueprint_id": f"bp_{len(candidates) + 1:04d}",
                    "start_anchor_id": key[0],
                    "goal_anchor_id": key[1],
                    "scenario": ("goal_only", "hazard_aware", "detour")[feature_index % 3],
                    "coverage_feature_ids": [],
                    "place_path_node_ids": list(path.nodes),
                    "place_path_edge_ids": _path_edge_ids(path),
                    "place_path_distance_m": round(float(path.distance_m), 6),
                    "status": "proposed",
                }
                candidates[key] = item
            item["coverage_feature_ids"] = sorted(set(item["coverage_feature_ids"]) | {feature_id})

    # Every open portal gets a short explicit crossing blueprint.  It remains
    # proposed, but it is visible to the reviewer rather than hidden in traffic
    # centrality accounting.
    existing = {(row["start_anchor_id"], row["goal_anchor_id"]) for row in candidates.values()}
    for edge in sorted(place_graph.edges, key=lambda item: str(item.edge_id)):
        portal = str((edge.extras or {}).get("portal") or "")
        if not portal or not _portal_is_open(edge):
            continue
        key = (str(edge.source), str(edge.target))
        if key in existing:
            continue
        candidates[key] = {
            "blueprint_id": f"bp_{len(candidates) + 1:04d}",
            "start_anchor_id": key[0], "goal_anchor_id": key[1], "scenario": "portal_crossing",
            "coverage_feature_ids": [f"portal:{portal}"],
            "place_path_node_ids": [key[0], key[1]], "place_path_edge_ids": [str(edge.edge_id)],
            "place_path_distance_m": round(float(edge.weight), 6), "status": "proposed",
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "place_graph_id": str(place_graph.graph_id),
        "config": cfg,
        "blueprints": sorted(candidates.values(), key=lambda item: str(item["blueprint_id"])),
        "coverage": {"feature_ids": sorted(features), "approved_feature_ids": []},
    }
    payload["blueprint_digest"] = _json_digest({key: value for key, value in payload.items() if key != "blueprint_digest"})
    return payload


def add_route_blueprint(
    payload: Mapping[str, Any],
    place_graph: ViewpointGraph,
    *,
    start_anchor_id: str,
    goal_anchor_id: str,
    scenario: str = "goal_only",
    approved: bool = False,
) -> dict[str, Any]:
    """Return a new blueprint payload with a deterministic user route added."""
    rows = [dict(item) for item in payload.get("blueprints") or [] if isinstance(item, Mapping)]
    if any(str(item.get("start_anchor_id")) == start_anchor_id and str(item.get("goal_anchor_id")) == goal_anchor_id for item in rows):
        raise ValueError("a blueprint with this directed start/goal already exists")
    path = shortest_graph_path(place_graph, start_anchor_id, goal_anchor_id)
    rows.append({
        "blueprint_id": f"bp_{len(rows) + 1:04d}", "start_anchor_id": start_anchor_id,
        "goal_anchor_id": goal_anchor_id, "scenario": scenario, "coverage_feature_ids": ["manual"],
        "place_path_node_ids": list(path.nodes), "place_path_edge_ids": _path_edge_ids(path),
        "place_path_distance_m": round(float(path.distance_m), 6),
        "status": "approved" if approved else "proposed", "user_created": True,
    })
    result = {**dict(payload), "blueprints": rows}
    result["blueprint_digest"] = _json_digest({key: value for key, value in result.items() if key != "blueprint_digest"})
    return result


def update_route_blueprint(payload: Mapping[str, Any], blueprint_id: str, *, status: str) -> dict[str, Any]:
    if status not in {"proposed", "approved", "rejected"}:
        raise ValueError("blueprint status must be proposed, approved, or rejected")
    rows = [dict(item) for item in payload.get("blueprints") or [] if isinstance(item, Mapping)]
    target = next((item for item in rows if str(item.get("blueprint_id")) == blueprint_id), None)
    if target is None:
        raise KeyError(f"unknown blueprint: {blueprint_id}")
    target["status"] = status
    result = {**dict(payload), "blueprints": rows}
    result["blueprint_digest"] = _json_digest({key: value for key, value in result.items() if key != "blueprint_digest"})
    return result


def delete_route_blueprint(payload: Mapping[str, Any], blueprint_id: str) -> dict[str, Any]:
    """Return the payload without one reviewable blueprint."""
    rows = [dict(item) for item in payload.get("blueprints") or [] if isinstance(item, Mapping)]
    kept = [item for item in rows if str(item.get("blueprint_id")) != blueprint_id]
    if len(kept) == len(rows):
        raise KeyError(f"unknown blueprint: {blueprint_id}")
    result = {**dict(payload), "blueprints": kept}
    result["blueprint_digest"] = _json_digest({key: value for key, value in result.items() if key != "blueprint_digest"})
    return result


def read_route_blueprints(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if str(payload.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("not an adaptive_navigation_support_v4 route blueprint file")
    if not isinstance(payload.get("blueprints"), list):
        raise ValueError("route blueprints has no blueprint list")
    return payload


def write_route_blueprints(path: str | Path, payload: Mapping[str, Any]) -> Path:
    if str(payload.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("not an adaptive_navigation_support_v4 route blueprint file")
    return _atomic_json(Path(path), payload)


def _bridge_edge_ids(graph: ViewpointGraph) -> set[str]:
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge in graph.edges:
        if edge.collision_free:
            adjacency[str(edge.source)].append((str(edge.target), str(edge.edge_id)))
            adjacency[str(edge.target)].append((str(edge.source), str(edge.edge_id)))
    disc: dict[str, int] = {}; low: dict[str, int] = {}; bridges: set[str] = set(); clock = 0
    def visit(node: str, parent_edge: str | None) -> None:
        nonlocal clock
        clock += 1; disc[node] = low[node] = clock
        for neighbour, edge_id in adjacency.get(node, []):
            if edge_id == parent_edge:
                continue
            if neighbour not in disc:
                visit(neighbour, edge_id); low[node] = min(low[node], low[neighbour])
                if low[neighbour] > disc[node]: bridges.add(edge_id)
            else:
                low[node] = min(low[node], disc[neighbour])
    for node in sorted(adjacency):
        if node not in disc: visit(node, None)
    return bridges


def _major_trunk_edges(graph: ViewpointGraph, blueprints: Sequence[Mapping[str, Any]], annotation: SceneAnnotation | None, cfg: Mapping[str, Any]) -> tuple[set[str], dict[str, Any]]:
    """Return the executable trunk and the unapproved coverage candidates.

    A place graph is deliberately more permissive than the fixed 0.25 m action
    space.  In particular, old auto-generated ``collision_free`` links can be
    topologically useful while requiring a long detour after 0.38 m clearance
    erosion.  Materialising those merely because they are central makes a
    reviewer-approved support build fail for a route they never selected.

    Stage 2 is the contract boundary: only approved blueprint corridors enter
    the executable support trunk.  Portals, articulation bridges, and demand
    edges remain explicit *candidates* in the analysis metadata (and have
    their own proposed portal blueprints), so they become executable as soon
    as the reviewer approves a route that uses them.
    """
    candidate_mandatory: set[str] = set(_bridge_edge_ids(graph))
    for edge in graph.edges:
        if (edge.extras or {}).get("portal"):
            candidate_mandatory.add(str(edge.edge_id))
    approved: set[str] = set()
    for blueprint in blueprints:
        if str(blueprint.get("status")) == "approved":
            approved.update(str(value) for value in blueprint.get("place_path_edge_ids") or [])

    terminals = sorted({node_id for values in _feature_nodes(graph, annotation).values() for node_id in values})[:48]
    demand: Counter[str] = Counter()
    for index, source in enumerate(terminals):
        for target in terminals[index + 1:]:
            try:
                path = shortest_graph_path(graph, source, target)
            except ValueError:
                continue
            for edge in path.edges:
                demand[str(edge.edge_id)] += 1
    total = sum(demand.values())
    central: set[str] = set()
    running = 0
    for edge_id, count in sorted(demand.items(), key=lambda item: (-item[1], item[0])):
        central.add(edge_id); running += count
        if total and running / total >= float(cfg["trunk_demand_coverage"]):
            break
    candidate_edges = candidate_mandatory | central
    deferred = candidate_edges - approved
    return approved, {
        "approved_blueprint_edge_count": len(approved),
        "candidate_mandatory_edge_count": len(candidate_mandatory),
        "central_edge_count": len(central),
        "deferred_unapproved_trunk_edge_count": len(deferred),
        "deferred_unapproved_trunk_edge_ids": sorted(deferred),
        "terminal_count": len(terminals), "weighted_demand_coverage": (running / total if total else 1.0),
    }


def _point_key(point: Sequence[float]) -> tuple[int, int]:
    return round(float(point[0]) * 100000), round(float(point[1]) * 100000)


def _dijkstra(
    nodes: Mapping[str, Mapping[str, Any]],
    edges: Mapping[str, Mapping[str, Any]],
    starts: Iterable[str],
    goals: set[str],
    *,
    allowed_place_edges: set[str] | None = None,
) -> tuple[list[str], list[str], float] | None:
    adjacency: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for edge_id, edge in edges.items():
        place_ids = set(str(item) for item in edge.get("place_edge_ids") or [])
        if allowed_place_edges is not None and place_ids and not place_ids <= allowed_place_edges:
            continue
        adjacency[str(edge["source"])].append((str(edge["target"]), edge_id, float(edge.get("distance_m") or 0.0)))
    queue: list[tuple[float, str]] = []; distance: dict[str, float] = {}; prior: dict[str, tuple[str, str]] = {}
    for start in starts:
        if start in nodes:
            distance[start] = 0.0; heapq.heappush(queue, (0.0, start))
    resolved: str | None = None
    while queue:
        cost, node_id = heapq.heappop(queue)
        if cost != distance.get(node_id): continue
        if node_id in goals:
            resolved = node_id; break
        for target, edge_id, amount in adjacency.get(node_id, []):
            next_cost = cost + amount
            if next_cost + 1e-9 < distance.get(target, math.inf):
                distance[target] = next_cost; prior[target] = (node_id, edge_id); heapq.heappush(queue, (next_cost, target))
    if resolved is None:
        return None
    node_ids = [resolved]; edge_ids: list[str] = []
    while node_ids[-1] not in starts:
        source, edge_id = prior[node_ids[-1]]; edge_ids.append(edge_id); node_ids.append(source)
    node_ids.reverse(); edge_ids.reverse()
    return node_ids, edge_ids, distance[resolved]


def _heading_closure(headings: set[str]) -> set[str]:
    """Required native 15-degree states for transitions among patch directions."""
    values = {int(value.split("_", 1)[1]) // 15 for value in headings if value.startswith("h_")}
    if len(values) <= 1:
        return {_heading_id(value * 15.0, 24) for value in values}
    result = set(values)
    ordered = sorted(values)
    for left in ordered:
        for right in ordered:
            delta = (right - left) % 24
            if delta > 12:
                delta -= 24
            step = 1 if delta >= 0 else -1
            for item in range(0, abs(delta) + 1):
                result.add((left + step * item) % 24)
    return {_heading_id(value * 15.0, 24) for value in result}


def _heading_arc(start: str, end: str) -> list[str]:
    """Shortest ordered 15-degree turn arc, including both endpoints."""
    first = int(start.split("_", 1)[1]) // 15
    last = int(end.split("_", 1)[1]) // 15
    delta = (last - first) % 24
    if delta > 12:
        delta -= 24
    direction = 1 if delta >= 0 else -1
    return [_heading_id(((first + direction * step) % 24) * 15.0, 24) for step in range(abs(delta) + 1)]


def _support_digest(place_graph: ViewpointGraph, blueprints: Mapping[str, Any], cfg: Mapping[str, Any]) -> str:
    return _json_digest({"profile_id": PROFILE_ID, "place_graph_id": place_graph.graph_id, "blueprint_digest": blueprints.get("blueprint_digest"), "config": cfg})


def _canonical_backbone_edges(
    graph: ViewpointGraph,
    required_edges: set[str],
    blueprints: Sequence[Mapping[str, Any]],
) -> set[str]:
    """Return the active-terminal subtree of a deterministic place-graph MST.

    Every disconnected action lattice has an arbitrary positional phase.  A
    support graph therefore cannot materialise independently sampled place
    edges and expect fixed-length actions to meet later.  We first select a
    connected, acyclic place backbone, then grow all action edges from one root
    pose.  Approved blueprint edges have the highest MST priority; bridge and
    demand-trunk edges follow, and the rest of the place graph only supplies
    the shortest connector necessary to join active terminals.
    """
    edge_by_id = {str(edge.edge_id): edge for edge in graph.edges if edge.collision_free}
    if not required_edges:
        raise ValueError("navigation support has no required place edges")
    blueprint_edges = {
        str(edge_id)
        for blueprint in blueprints
        if str(blueprint.get("status")) == "approved"
        for edge_id in blueprint.get("place_path_edge_ids") or []
    }
    active_nodes = {
        str(node_id)
        for edge_id in required_edges
        for node_id in (
            str(edge_by_id[edge_id].source), str(edge_by_id[edge_id].target),
        )
        if edge_id in edge_by_id
    }
    if len(active_nodes) < 2:
        raise ValueError("navigation support has fewer than two active place terminals")

    parent = {str(node.node_id): str(node.node_id) for node in graph.nodes}

    def find(node_id: str) -> str:
        while parent[node_id] != node_id:
            parent[node_id] = parent[parent[node_id]]
            node_id = parent[node_id]
        return node_id

    def union(left: str, right: str) -> bool:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return False
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        return True

    selected: dict[str, Any] = {}
    for edge in sorted(
        edge_by_id.values(),
        key=lambda item: (
            0 if str(item.edge_id) in blueprint_edges else 1 if str(item.edge_id) in required_edges else 2,
            float(item.distance_m), str(item.edge_id),
        ),
    ):
        if union(str(edge.source), str(edge.target)):
            selected[str(edge.edge_id)] = edge

    # Prune global-MST leaves that do not support any mandatory terminal. The
    # residual is the smallest connected subtree that retains all active place
    # edges/terminals while avoiding an all-room dense support graph.
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for edge_id, edge in selected.items():
        adjacency[str(edge.source)].append((str(edge.target), edge_id))
        adjacency[str(edge.target)].append((str(edge.source), edge_id))
    queue = [node_id for node_id, rows in adjacency.items() if len(rows) <= 1 and node_id not in active_nodes]
    removed: set[str] = set()
    while queue:
        node_id = queue.pop()
        rows = [(other, edge_id) for other, edge_id in adjacency.get(node_id, []) if edge_id not in removed]
        if node_id in active_nodes or len(rows) != 1:
            continue
        other, edge_id = rows[0]
        removed.add(edge_id)
        if other not in active_nodes:
            remaining = sum(1 for _next, candidate in adjacency[other] if candidate not in removed)
            if remaining <= 1:
                queue.append(other)
    result = set(selected) - removed
    if not result:
        raise ValueError("navigation support backbone is empty")
    return result


def build_navigation_support(
    place_graph: ViewpointGraph,
    blueprints: Mapping[str, Any],
    *,
    annotation: SceneAnnotation | None,
    motion_grid: TraversabilityGrid,
    config: Mapping[str, Any] | None = None,
    on_progress: Callable[[str, float, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Create a directed, collision-certified ribbon support graph in memory."""
    cfg = _config(config)
    if place_graph.node_heading_count != 12:
        raise ValueError("place graph must have 12 headings")
    if str(blueprints.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("route blueprints are not adaptive_navigation_support_v4")
    if not [item for item in blueprints.get("blueprints") or [] if str(item.get("status")) == "approved"]:
        raise ValueError("approve at least one route blueprint before building navigation support")
    def report(stage: str, progress: float, **detail: Any) -> None:
        if on_progress: on_progress(stage, max(0.0, min(1.0, progress)), detail)

    effective_grid, restored_portals = _v3_portal_aware_grid(place_graph, motion_grid)
    rows = [dict(item) for item in blueprints.get("blueprints") or [] if isinstance(item, Mapping)]
    required_edges, trunk_meta = _major_trunk_edges(place_graph, rows, annotation, cfg)
    edge_by_id = {str(edge.edge_id): edge for edge in place_graph.edges if edge.collision_free}
    missing = sorted(required_edges - set(edge_by_id))
    if missing: raise ValueError("support trunk references non-certified place edges: " + ", ".join(missing))
    report("support_trunk", 0.05, required_place_edge_count=len(required_edges), **trunk_meta)

    poses: dict[str, dict[str, Any]] = {}
    pose_by_key: dict[tuple[int, int], str] = {}
    edges: dict[str, dict[str, Any]] = {}
    anchor_poses: dict[str, set[str]] = defaultdict(set)
    path_sequences: list[list[str]] = []
    edge_counter = 0

    def ensure_pose(point: tuple[float, float], *, tags: Iterable[str] = (), anchor_ids: Iterable[str] = ()) -> str:
        key = _point_key(point)
        pose_id = pose_by_key.get(key)
        if pose_id is None:
            # No coordinate averaging: action vectors must survive JSON round trips unchanged.
            pose_id = f"support_pose_{len(poses) + 1:05d}"
            poses[pose_id] = {"motion_node_id": pose_id, "motion_pose_id": pose_id, "position": [float(point[0]), float(point[1]), 0.0], "tags": [], "anchor_node_ids": []}
            pose_by_key[key] = pose_id
        pose = poses[pose_id]
        pose["tags"] = sorted(set(pose["tags"]) | {str(value) for value in tags})
        pose["anchor_node_ids"] = sorted(set(pose["anchor_node_ids"]) | {str(value) for value in anchor_ids})
        for anchor_id in anchor_ids: anchor_poses[str(anchor_id)].add(pose_id)
        return pose_id

    def add_path(
        points: Sequence[tuple[float, float]], *, place_edge_id: str,
        lane: str, edge_type: str, anchor_start: str | None = None,
        anchor_end: str | None = None, tags: Iterable[str] = (),
        portal_ids: Iterable[str] = (),
    ) -> list[str]:
        nonlocal edge_counter
        if len(points) < 2: return []
        portal_ids = tuple(sorted({str(value) for value in portal_ids if str(value)}))
        ids = [ensure_pose(point, tags=tags, anchor_ids=([anchor_start] if index == 0 and anchor_start else []) + ([anchor_end] if index == len(points) - 1 and anchor_end else [])) for index, point in enumerate(points)]
        for source, target in zip(ids, ids[1:]):
            source_point = tuple(poses[source]["position"][:2]); target_point = tuple(poses[target]["position"][:2])
            distance = _distance(source_point, target_point)
            if not (cfg["forward_step_m"] - cfg["forward_tolerance_m"] - 1e-9 <= distance <= cfg["forward_step_m"] + cfg["forward_tolerance_m"] + 1e-9):
                raise ValueError(f"non_normalized_support_forward:{place_edge_id}:{distance:.5f}")
            if not _world_segment_safe(effective_grid, source_point, target_point):
                raise ValueError(f"unsafe_support_forward:{place_edge_id}")
            edge_counter += 1
            edge_id = f"support_edge_{edge_counter:06d}"
            edges[edge_id] = {
                "motion_edge_id": edge_id, "source": source, "target": target,
                "distance_m": distance, "action": "move_forward", "edge_type": edge_type,
                "lane": lane, "place_edge_ids": [place_edge_id] if place_edge_id else [],
                "portal_ids": list(portal_ids),
                "collision_free": True,
                "safety_certificate": {
                    "effective_clearance_m": cfg["effective_clearance_m"],
                    "world_segment_safe": True,
                    "portal_open": edge_type != "portal_bridge" or bool(portal_ids),
                },
            }
        path_sequences.append(ids)
        return ids

    # All action paths start from one canonical physical pose and are extended
    # along a connected place backbone.  Sampling each place edge independently
    # creates incompatible 15-degree lattice phases: nodes can look adjacent in
    # the editor but no legal 0.25m transition can join them.  The pruned MST is
    # only a support substrate; approved blueprint routes are checked below for
    # their own directness and never reconstructed through a root/LCA detour.
    backbone_edge_ids = _canonical_backbone_edges(place_graph, required_edges, rows)
    backbone_adjacency: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for edge_id in backbone_edge_ids:
        edge = edge_by_id[edge_id]
        backbone_adjacency[str(edge.source)].append((str(edge.target), edge))
        backbone_adjacency[str(edge.target)].append((str(edge.source), edge))
    approved_rows = [row for row in rows if str(row.get("status")) == "approved"]
    root_anchor_id = str(approved_rows[0]["start_anchor_id"])
    if root_anchor_id not in backbone_adjacency:
        root_anchor_id = sorted(backbone_adjacency)[0]
    root_anchor = _node_map(place_graph).get(root_anchor_id)
    if root_anchor is None:
        raise ValueError(f"support_root_anchor_missing:{root_anchor_id}")
    root_cell = _nearest_safe_cell(effective_grid, tuple(root_anchor.position[:2]))
    if root_cell is None:
        raise ValueError(f"support_root_anchor_unreachable:{root_anchor_id}")
    root_point = cell_to_world(effective_grid.spec, *root_cell)
    root_pose_id = ensure_pose(root_point, tags=("patch", "junction"), anchor_ids=(root_anchor_id,))
    representative: dict[str, str] = {root_anchor_id: root_pose_id}
    visited = {root_anchor_id}
    pending = [root_anchor_id]
    canonical_centerline_edges: list[str] = []
    narrow_edges: list[str] = []
    while pending:
        parent_id = pending.pop()
        parent_pose_id = representative[parent_id]
        parent_point = tuple(poses[parent_pose_id]["position"][:2])
        for child_id, edge in sorted(backbone_adjacency[parent_id], key=lambda item: (item[0], str(item[1].edge_id))):
            if child_id in visited:
                continue
            raw_guide = _edge_points(place_graph, edge)
            if str(edge.target) == parent_id:
                raw_guide.reverse()
            guide = [parent_point, *raw_guide[1:]]
            path = _action_grid_path(
                effective_grid, parent_point, guide[-1],
                {
                    "forward_step_m": cfg["forward_step_m"],
                    "forward_tolerance_m": cfg["forward_tolerance_m"],
                    "heading_count": 24,
                    "action_corridor_radius_m": cfg["action_corridor_radius_m"],
                },
                guide=guide, exact_start=True,
            )
            if path is None or len(path) < 2:
                raise ValueError(f"support_corridor_unreachable:{edge.edge_id}")
            portal_ids = [str((edge.extras or {}).get("portal"))] if (edge.extras or {}).get("portal") else []
            if portal_ids and not _portal_is_open(edge):
                raise ValueError(f"support_portal_not_open:{portal_ids[0]}")
            edge_type = "portal_bridge" if portal_ids else "lane_forward"
            tags = ("lane", "portal") if portal_ids else ("lane",)
            forward_ids = add_path(path, place_edge_id=str(edge.edge_id), lane="canonical_center", edge_type=edge_type, anchor_start=parent_id, anchor_end=child_id, tags=tags, portal_ids=portal_ids)
            add_path(list(reversed(path)), place_edge_id=str(edge.edge_id), lane="canonical_center", edge_type=edge_type, anchor_start=child_id, anchor_end=parent_id, tags=tags, portal_ids=portal_ids)
            representative[child_id] = forward_ids[-1]
            canonical_centerline_edges.append(str(edge.edge_id))
            visited.add(child_id)
            pending.append(child_id)
            if len(canonical_centerline_edges) % 8 == 0:
                report("support_backbone", 0.10 + 0.45 * len(canonical_centerline_edges) / max(1, len(backbone_edge_ids)), place_edge_count=len(canonical_centerline_edges), pose_count=len(poses))

    # Only anchor/portal/junction locations carry broad turning freedom.  The
    # intermediate lane turns added below represent genuine local curvature,
    # not a place to reverse or change lane arbitrarily.
    incident_portals = {
        str(node_id)
        for edge_id in backbone_edge_ids
        for node_id in (str(edge_by_id[edge_id].source), str(edge_by_id[edge_id].target))
        if (edge_by_id[edge_id].extras or {}).get("portal")
    }
    for anchor_id, pose_id in representative.items():
        tags = set(poses[pose_id].get("tags") or []) | {"patch"}
        if len(backbone_adjacency.get(anchor_id, [])) != 2 or anchor_id in incident_portals:
            tags.add("junction")
        if anchor_id in incident_portals:
            tags.add("portal")
        poses[pose_id]["tags"] = sorted(tags)
    if len(poses) > cfg["max_support_poses"]:
        raise ValueError(f"support_pose_budget_exceeded:{len(poses)}/{cfg['max_support_poses']}")
    report("support_patches", 0.62, pose_count=len(poses), backbone_edge_count=len(backbone_edge_ids))

    # Store direct certified support routes for every approved blueprint.  They
    # use only the blueprint's place corridors plus local patch edges.
    blueprint_routes: list[dict[str, Any]] = []
    for blueprint in rows:
        if str(blueprint.get("status")) != "approved": continue
        allowed = set(str(value) for value in blueprint.get("place_path_edge_ids") or [])
        found = _dijkstra(poses, edges, anchor_poses.get(str(blueprint["start_anchor_id"]), set()), anchor_poses.get(str(blueprint["goal_anchor_id"]), set()), allowed_place_edges=allowed)
        if found is None:
            raise ValueError(f"blueprint_support_unreachable:{blueprint['blueprint_id']}:outside_canonical_backbone")
        pose_ids, edge_ids, distance = found
        upper = max(float(blueprint["place_path_distance_m"]) * cfg["directness_stretch"], float(blueprint["place_path_distance_m"]) + cfg["directness_slack_m"])
        if distance > upper + 1e-6:
            raise ValueError(f"blueprint_directness_exceeded:{blueprint['blueprint_id']}:{distance:.3f}>{upper:.3f}")
        blueprint_routes.append({"blueprint_id": blueprint["blueprint_id"], "start_anchor_id": blueprint["start_anchor_id"], "goal_anchor_id": blueprint["goal_anchor_id"], "motion_pose_ids": pose_ids, "motion_edge_ids": edge_ids, "distance_m": distance, "place_path_distance_m": float(blueprint["place_path_distance_m"]), "directness_ratio": (distance / max(float(blueprint["place_path_distance_m"]), 1e-9))})

    if len(poses) > cfg["max_support_poses"]:
        raise ValueError(f"support_pose_budget_exceeded:{len(poses)}/{cfg['max_support_poses']}")

    # Discover native action headings only after blueprint fallback corridors
    # have been materialised; every stored forward edge must therefore have an
    # exact source/target action state and a renderable heading.
    incoming: dict[str, set[str]] = defaultdict(set); outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in edges.values():
        source = poses[str(edge["source"])]["position"]; target = poses[str(edge["target"])]["position"]
        heading = _heading_id(_yaw_to(source, target), 24)
        edge["heading_id"] = heading; outgoing[str(edge["source"])].add(heading); incoming[str(edge["target"])].add(heading)
    local_turn_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for sequence in path_sequences:
        for previous, current, following in zip(sequence, sequence[1:], sequence[2:]):
            prior_heading = _heading_id(_yaw_to(poses[previous]["position"], poses[current]["position"]), 24)
            next_heading = _heading_id(_yaw_to(poses[current]["position"], poses[following]["position"]), 24)
            if prior_heading != next_heading:
                local_turn_pairs[current].add((prior_heading, next_heading))
    state_rows: dict[tuple[str, str], dict[str, Any]] = {}
    pose_headings: dict[str, set[str]] = {}
    for pose_id, pose in poses.items():
        headings = set(outgoing.get(pose_id, set())) | set(incoming.get(pose_id, set()))
        is_patch = bool({"patch", "junction", "portal"} & set(pose.get("tags") or []))
        if is_patch:
            headings = _heading_closure(headings)
        else:
            for start, end in local_turn_pairs.get(pose_id, set()):
                headings.update(_heading_arc(start, end))
        if not headings: continue
        pose_headings[pose_id] = headings
        for heading in sorted(headings):
            state_id = f"{pose_id}:{heading}"
            state_rows[(pose_id, heading)] = {"motion_state_id": state_id, "motion_pose_id": pose_id, "heading_id": heading}
    transitions: list[dict[str, Any]] = []
    for edge in edges.values():
        heading = str(edge["heading_id"]); source = str(edge["source"]); target = str(edge["target"])
        if (source, heading) not in state_rows or (target, heading) not in state_rows:
            raise ValueError(f"support_action_heading_missing:{edge['motion_edge_id']}")
        transitions.append({"transition_id": f"transition_{len(transitions) + 1:06d}", "source_state_id": state_rows[(source, heading)]["motion_state_id"], "target_state_id": state_rows[(target, heading)]["motion_state_id"], "action": "move_forward", "motion_edge_id": edge["motion_edge_id"], "distance_m": edge["distance_m"], "portal_ids": list(edge.get("portal_ids") or [])})
    emitted_turns: set[tuple[str, str, str]] = set()

    def add_turn(source_heading: str, target_heading: str, pose_id: str) -> None:
        source_number = int(source_heading.split("_", 1)[1]) // 15
        target_number = int(target_heading.split("_", 1)[1]) // 15
        delta = (target_number - source_number) % 24
        if delta == 23:
            delta = -1
        if delta not in {-1, 1}:
            raise ValueError(f"support_non_incremental_turn:{pose_id}:{source_heading}:{target_heading}")
        key = (pose_id, source_heading, target_heading)
        if key in emitted_turns:
            return
        emitted_turns.add(key)
        transitions.append({
            "transition_id": f"transition_{len(transitions) + 1:06d}",
            "source_state_id": state_rows[(pose_id, source_heading)]["motion_state_id"],
            "target_state_id": state_rows[(pose_id, target_heading)]["motion_state_id"],
            "action": "turn_left" if delta == 1 else "turn_right",
            "turn_deg": 15.0 * delta,
        })

    for pose_id, headings in pose_headings.items():
        if {"patch", "junction", "portal"} & set(poses[pose_id].get("tags", [])):
            numbers = {int(value.split("_", 1)[1]) // 15 for value in headings}
            for number in sorted(numbers):
                for delta in (1, -1):
                    next_number = (number + delta) % 24
                    if next_number in numbers:
                        add_turn(_heading_id(number * 15.0, 24), _heading_id(next_number * 15.0, 24), pose_id)
        else:
            for start, end in local_turn_pairs.get(pose_id, set()):
                for source_heading, target_heading in zip(_heading_arc(start, end), _heading_arc(start, end)[1:]):
                    add_turn(source_heading, target_heading, pose_id)
    report("action_states", 0.74, action_state_count=len(state_rows), transition_count=len(transitions))

    core_candidates = sorted(
        poses.values(), key=lambda pose: (
            not bool({"portal", "junction", "patch"} & set(pose.get("tags") or [])),
            str(pose["motion_node_id"]),
        )
    )
    panorama_ids: set[str] = set(); panorama_positions: list[Sequence[float]] = []
    for pose in core_candidates:
        if len(panorama_ids) >= cfg["max_panorama_poses"]: break
        if any(_distance(pose["position"], position) < cfg["min_pose_spacing_m"] - 1e-9 for position in panorama_positions): continue
        panorama_ids.add(str(pose["motion_node_id"])); panorama_positions.append(pose["position"])
    render_entries: list[dict[str, Any]] = []; observation_poses: list[dict[str, Any]] = []
    panorama_headings = [f"h_{angle:03d}" for angle in range(0, 360, 30)]
    for pose_id, pose in sorted(poses.items()):
        action_headings = set(pose_headings.get(pose_id, set()))
        available = sorted(action_headings | (set(panorama_headings) if pose_id in panorama_ids else set()))
        tier = "PANORAMA_12" if pose_id in panorama_ids else "ACTION_NATIVE"
        observation_poses.append({**pose, "tier": tier, "available_heading_ids": available, "action_heading_ids": sorted(action_headings)})
        for offset in range(0, len(available), 4):
            batch = available[offset:offset + 4]
            batch_key = f"{pose_id}:b{offset // 4:02d}"
            for heading in batch:
                render_entries.append({"motion_node_id": pose_id, "heading_id": heading, "tier": tier, "available_heading_ids": available, "polar_batch_key": batch_key, "polar_batch_size": len(batch), "projection": "native_perspective", "canonical": True})
    batch_count = len({entry["polar_batch_key"] for entry in render_entries})
    if len(render_entries) > cfg["max_polar_observations"]:
        raise ValueError(f"support_polar_budget_exceeded:{len(render_entries)}/{cfg['max_polar_observations']}")
    if batch_count > cfg["max_polar_batches"]:
        raise ValueError(f"support_batch_budget_exceeded:{batch_count}/{cfg['max_polar_batches']}")
    report("observation_plan", 0.90, polar_observation_count=len(render_entries), polar_batch_count=batch_count, panorama_pose_count=len(panorama_ids))

    digest = _support_digest(place_graph, blueprints, cfg)
    support_graph = {
        "schema_version": SCHEMA_VERSION, "profile_id": PROFILE_ID, "scene_id": place_graph.scene_id,
        "place_graph_id": place_graph.graph_id, "blueprint_digest": blueprints.get("blueprint_digest"), "profile_digest": digest,
        "heading_count": 24, "turn_deg": 15.0, "forward_step_m": cfg["forward_step_m"], "forward_tolerance_m": cfg["forward_tolerance_m"], "effective_clearance_m": cfg["effective_clearance_m"],
        "poses": list(poses.values()), "nodes": list(poses.values()), "edges": list(edges.values()), "states": list(state_rows.values()), "transitions": transitions,
        "anchor_pose_ids": {key: sorted(value) for key, value in anchor_poses.items()}, "blueprint_routes": blueprint_routes,
        "trunk": {
            "place_edge_ids": sorted(required_edges),
            "canonical_backbone_edge_ids": sorted(backbone_edge_ids),
            **trunk_meta,
        },
        "narrow_corridor_edge_ids": narrow_edges,
    }
    validation = validate_navigation_support(support_graph, motion_grid=effective_grid)
    support_graph["validation"] = {**validation, "digest": digest}
    observation_plan = {
        "schema_version": SCHEMA_VERSION, "profile_id": PROFILE_ID, "scene_id": place_graph.scene_id,
        "place_graph_id": place_graph.graph_id, "support_graph_ref": SUPPORT_GRAPH_FILE, "profile_digest": digest,
        "validation_digest": digest, "heading_count": 24, "panoramic_heading_count": 12,
        "poses": observation_poses, "render_entries": render_entries, "config": cfg,
        "summary": {"support_pose_count": len(poses), "action_state_count": len(state_rows), "panorama_12_pose_count": len(panorama_ids), "polar_observation_count": len(render_entries), "polar_batch_count": batch_count, "gpu_time_estimate_hours_per_polar_camera_variant": len(render_entries) * cfg["heading_render_seconds"] / 3600.0},
    }
    support_graph["generation_diagnostics"] = {
        "restored_portals": restored_portals,
        "required_trunk_edge_count": len(required_edges),
        "canonical_backbone_edge_count": len(backbone_edge_ids),
        "canonical_centerline_edge_count": len(canonical_centerline_edges),
        "narrow_corridor_edge_count": len(narrow_edges),
        "blueprint_route_count": len(blueprint_routes),
        **trunk_meta,
        **observation_plan["summary"],
    }
    report("complete", 1.0, support_pose_count=len(poses), polar_observation_count=len(render_entries))
    return {"place_graph": place_graph, "route_blueprints": dict(blueprints), "support_graph": support_graph, "observation_plan": observation_plan, "generation_diagnostics": dict(support_graph["generation_diagnostics"])}


def analyze_navigation_support(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Dry-run alias; callers keep the returned payload in memory only."""
    return build_navigation_support(*args, **kwargs)


def validate_navigation_support(graph: Mapping[str, Any], *, motion_grid: TraversabilityGrid | None = None) -> dict[str, Any]:
    if str(graph.get("profile_id") or "") != PROFILE_ID: raise ValueError("not an adaptive_navigation_support_v4 graph")
    poses = {str(item.get("motion_node_id")): item for item in graph.get("poses") or [] if isinstance(item, Mapping)}
    edges = {str(item.get("motion_edge_id")): item for item in graph.get("edges") or [] if isinstance(item, Mapping)}
    states = {str(item.get("motion_state_id")): item for item in graph.get("states") or [] if isinstance(item, Mapping)}
    if not poses or not edges or not states: raise ValueError("support graph is empty")
    for edge_id, edge in edges.items():
        source, target = poses.get(str(edge.get("source"))), poses.get(str(edge.get("target")))
        if source is None or target is None: raise ValueError(f"support_edge_missing_pose:{edge_id}")
        distance = _distance(source["position"], target["position"])
        if not math.isclose(distance, 0.25, abs_tol=0.025): raise ValueError(f"support_non_normalized_forward:{edge_id}")
        if motion_grid is not None and not _world_segment_safe(motion_grid, tuple(source["position"][:2]), tuple(target["position"][:2])): raise ValueError(f"support_unsafe_forward:{edge_id}")
        if str(edge.get("edge_type") or "") == "portal_bridge":
            if not edge.get("portal_ids") or not bool((edge.get("safety_certificate") or {}).get("portal_open")):
                raise ValueError(f"support_uncertified_portal:{edge_id}")
    for transition in graph.get("transitions") or []:
        source, target = states.get(str(transition.get("source_state_id"))), states.get(str(transition.get("target_state_id")))
        if source is None or target is None: raise ValueError(f"support_transition_missing_state:{transition.get('transition_id')}")
        if transition.get("action") in {"turn_left", "turn_right"}:
            expected = 15.0 if transition.get("action") == "turn_left" else -15.0
            if source["motion_pose_id"] != target["motion_pose_id"] or not math.isclose(float(transition.get("turn_deg") or 0.0), expected, abs_tol=1e-9): raise ValueError(f"support_invalid_turn:{transition.get('transition_id')}")
        elif transition.get("action") == "move_forward":
            edge = edges.get(str(transition.get("motion_edge_id")))
            if edge is None: raise ValueError(f"support_invalid_forward:{transition.get('transition_id')}")
            if sorted(str(value) for value in transition.get("portal_ids") or []) != sorted(str(value) for value in edge.get("portal_ids") or []):
                raise ValueError(f"support_portal_transition_mismatch:{transition.get('transition_id')}")
            expected_heading = str(edge.get("heading_id") or "")
            if str(source.get("heading_id")) != expected_heading or str(target.get("heading_id")) != expected_heading:
                raise ValueError(f"support_forward_heading_mismatch:{transition.get('transition_id')}")
        else: raise ValueError(f"support_invalid_action:{transition.get('transition_id')}")
    for route in graph.get("blueprint_routes") or []:
        pose_ids = [str(value) for value in route.get("motion_pose_ids") or []]
        edge_ids = [str(value) for value in route.get("motion_edge_ids") or []]
        if len(pose_ids) != len(edge_ids) + 1:
            raise ValueError(f"support_route_sequence_mismatch:{route.get('blueprint_id')}")
        for source_id, edge_id, target_id in zip(pose_ids, edge_ids, pose_ids[1:]):
            edge = edges.get(edge_id)
            if edge is None or str(edge.get("source")) != source_id or str(edge.get("target")) != target_id:
                raise ValueError(f"support_route_edge_mismatch:{route.get('blueprint_id')}:{edge_id}")

    forward: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    for transition in graph.get("transitions") or []:
        source_id, target_id = str(transition.get("source_state_id")), str(transition.get("target_state_id"))
        forward[source_id].append(target_id)
        reverse[target_id].append(source_id)

    def reachable(adjacency: Mapping[str, Sequence[str]]) -> set[str]:
        root = min(states)
        result = {root}; pending = [root]
        while pending:
            current = pending.pop()
            for target_id in adjacency.get(current, []):
                if target_id not in result:
                    result.add(target_id)
                    pending.append(target_id)
        return result

    forward_component = reachable(forward)
    reverse_component = reachable(reverse)
    if len(forward_component) != len(states) or len(reverse_component) != len(states):
        raise ValueError(
            "support_action_backbone_disconnected:"
            f"forward={len(forward_component)}/{len(states)}:reverse={len(reverse_component)}/{len(states)}"
        )
    return {"ok": True, "pose_count": len(poses), "edge_count": len(edges), "state_count": len(states), "transition_count": len(graph.get("transitions") or []), "strong_component_count": 1}


def write_navigation_support(scene_dir: str | Path, payload: Mapping[str, Any]) -> dict[str, Path]:
    root = Path(scene_dir)
    place_graph = payload["place_graph"]
    from .viewpoint_graph import write_viewpoint_graph
    paths = {
        "place_graph": write_viewpoint_graph(root / PLACE_GRAPH_FILE, place_graph),
        "route_blueprints": write_route_blueprints(root / BLUEPRINTS_FILE, payload["route_blueprints"]),
        "support_graph": _atomic_json(root / SUPPORT_GRAPH_FILE, payload["support_graph"]),
        "observation_plan": _atomic_json(root / OBSERVATION_PLAN_FILE, payload["observation_plan"]),
    }
    paths["render_graph"] = write_viewpoint_graph(root / RENDER_GRAPH_FILE, support_render_graph(payload["observation_plan"]))
    return paths


def write_place_graph(scene_dir: str | Path, graph: ViewpointGraph, *, config: Mapping[str, Any]) -> Path:
    from .viewpoint_graph import write_viewpoint_graph
    graph.metadata = {**dict(graph.metadata or {}), "profile_id": PROFILE_ID, "navigation_support_config": _config(config)}
    return write_viewpoint_graph(Path(scene_dir) / PLACE_GRAPH_FILE, graph)


def read_support_observation_plan(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if str(payload.get("profile_id") or "") != PROFILE_ID: raise ValueError("not an adaptive_navigation_support_v4 observation plan")
    if not isinstance(payload.get("render_entries"), list): raise ValueError("support observation plan has no render entries")
    if payload.get("plan_kind") == "observation_expansion":
        if not str(payload.get("coverage_level_id") or ""):
            raise ValueError("support observation expansion has no coverage_level_id")
        if not str(payload.get("coverage_digest") or ""):
            raise ValueError("support observation expansion has no coverage_digest")
    return payload


def support_observation_expansion_filename(level_id: str) -> str:
    """Return the fixed, scene-local sidecar name for one additive level."""
    _observation_expansion_level(level_id)
    return f"{OBSERVATION_EXPANSION_FILE_PREFIX}{level_id}.json"


def _observation_expansion_level(level_id: str) -> dict[str, Any]:
    for level in OBSERVATION_EXPANSION_LEVELS:
        if level["level_id"] == level_id:
            return dict(level)
    supported = ", ".join(level["level_id"] for level in OBSERVATION_EXPANSION_LEVELS)
    raise ValueError(f"unsupported support observation expansion level {level_id!r}; expected one of {supported}")


def _heading_sort_key(heading_id: str) -> int:
    try:
        return int(str(heading_id).split("_", 1)[1]) % 360
    except (IndexError, ValueError):
        return 10_000


def _sorted_heading_ids(headings: Iterable[str]) -> list[str]:
    return sorted({str(heading) for heading in headings}, key=_heading_sort_key)


def _context_headings(action_headings: Iterable[str], *, radius_steps: int) -> set[str]:
    """Native 15-degree neighbours of the required action headings.

    The action lattice is intentionally fixed at 24 headings.  Keeping this
    helper independent of an arbitrary pose yaw makes an expansion stable when
    a user returns to the scene after the original L0 render has finished.
    """
    values: set[str] = set()
    for heading_id in action_headings:
        degrees = _heading_sort_key(str(heading_id))
        if degrees >= 10_000 or degrees % 15:
            raise ValueError(f"support action heading must be a 15-degree id: {heading_id!r}")
        index = degrees // 15
        for delta in range(-radius_steps, radius_steps + 1):
            values.add(_heading_id(float(((index + delta) % 24) * 15), 24))
    return values


def build_support_observation_expansion(
    base_plan: Mapping[str, Any],
    *,
    level_id: str,
) -> dict[str, Any]:
    """Build an add-only native-heading render plan for one V4 context level.

    The returned ``render_entries`` are every entry needed beyond baseline L0
    up to the requested cumulative level.  A render submission always carries
    ``only_missing`` by default, so sequential levels submit only their newly
    absent entries while a direct jump (for example L0 -> L3) remains complete.
    Core PANORAMA_12 poses are intentionally not expanded; this controls cost by
    spending extra views only at non-core ACTION_NATIVE detail poses.
    """
    if str(base_plan.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("not an adaptive_navigation_support_v4 observation plan")
    if base_plan.get("plan_kind") == "observation_expansion":
        raise ValueError("observation expansions must be derived from support_observation_plan.json, not another expansion")
    level = _observation_expansion_level(level_id)
    if int(level["context_radius_steps"]) == 0:
        raise ValueError("L0 is support_observation_plan.json and does not need an expansion sidecar")
    base_entries = [dict(entry) for entry in base_plan.get("render_entries") or [] if isinstance(entry, Mapping)]
    poses = [dict(pose) for pose in base_plan.get("poses") or [] if isinstance(pose, Mapping)]
    if not base_entries or not poses:
        raise ValueError("support observation plan is empty")
    profile_digest = str(base_plan.get("profile_digest") or "")
    validation_digest = str(base_plan.get("validation_digest") or "")
    if not profile_digest or profile_digest != validation_digest:
        raise ValueError("support observation plan digest mismatch")

    entry_keys = {
        (str(entry.get("motion_node_id") or ""), str(entry.get("heading_id") or ""))
        for entry in base_entries
    }
    if ("", "") in entry_keys:
        raise ValueError("support observation plan contains an incomplete render entry")
    expansion_entries: list[dict[str, Any]] = []
    expanded_poses: list[dict[str, Any]] = []
    expanded_detail_pose_count = 0
    for pose in poses:
        pose_id = str(pose.get("motion_node_id") or "")
        if not pose_id:
            raise ValueError("support observation plan contains a pose without motion_node_id")
        base_available = _sorted_heading_ids(pose.get("available_heading_ids") or [])
        action_headings = _sorted_heading_ids(pose.get("action_heading_ids") or [])
        tier = str(pose.get("tier") or "ACTION_NATIVE")
        target_headings: set[str] = set()
        if tier == "ACTION_NATIVE" and action_headings:
            target_headings = (
                set(_all_heading_ids(24))
                if level_id == "l6_detail_full_24"
                else _context_headings(
                    action_headings,
                    radius_steps=int(level["context_radius_steps"]),
                )
            )
            expanded_detail_pose_count += 1
        available = _sorted_heading_ids([*base_available, *target_headings])
        expanded_pose = {
            **pose,
            "available_heading_ids": available,
            "action_heading_ids": action_headings,
        }
        expanded_poses.append(expanded_pose)
        additions = [heading for heading in available if (pose_id, heading) not in entry_keys]
        for offset in range(0, len(additions), 4):
            batch = additions[offset:offset + 4]
            batch_key = f"{pose_id}:{level_id}:b{offset // 4:02d}"
            for heading in batch:
                expansion_entries.append({
                    "motion_node_id": pose_id,
                    "heading_id": heading,
                    "tier": "ACTION_CONTEXT",
                    "base_tier": tier,
                    "observation_role": "action_context",
                    "coverage_level_id": level_id,
                    "available_heading_ids": available,
                    "action_heading_ids": action_headings,
                    "polar_batch_key": batch_key,
                    "polar_batch_size": len(batch),
                    "projection": "native_perspective",
                    "canonical": True,
                })
    batch_count = len({str(entry["polar_batch_key"]) for entry in expansion_entries})
    base_summary = dict(base_plan.get("summary") or {})
    base_observations = len(base_entries)
    base_batches = int(base_summary.get("polar_batch_count") or len({str(entry.get("polar_batch_key") or "") for entry in base_entries}))
    heading_seconds = float((base_plan.get("config") or {}).get("heading_render_seconds") or DEFAULT_CONFIG["heading_render_seconds"])
    coverage_digest = _json_digest({
        "schema_version": OBSERVATION_EXPANSION_SCHEMA_VERSION,
        "base_profile_digest": profile_digest,
        "level_id": level_id,
        "render_keys": [
            [entry["motion_node_id"], entry["heading_id"]]
            for entry in expansion_entries
        ],
    })
    summary = {
        "support_pose_count": int(base_summary.get("support_pose_count") or len(poses)),
        "detail_pose_count": sum(1 for pose in poses if str(pose.get("tier") or "") == "ACTION_NATIVE"),
        "expanded_detail_pose_count": expanded_detail_pose_count,
        "base_polar_observation_count": base_observations,
        "additional_polar_observation_count": len(expansion_entries),
        "coverage_polar_observation_count": base_observations + len(expansion_entries),
        "base_polar_batch_count": base_batches,
        "additional_polar_batch_count": batch_count,
        "coverage_polar_batch_count": base_batches + batch_count,
        "additional_gpu_time_estimate_hours_per_polar_camera_variant": len(expansion_entries) * heading_seconds / 3600.0,
        "coverage_gpu_time_estimate_hours_per_polar_camera_variant": (base_observations + len(expansion_entries)) * heading_seconds / 3600.0,
    }
    return {
        "schema_version": OBSERVATION_EXPANSION_SCHEMA_VERSION,
        "plan_kind": "observation_expansion",
        "profile_id": PROFILE_ID,
        "scene_id": str(base_plan.get("scene_id") or ""),
        "place_graph_id": str(base_plan.get("place_graph_id") or ""),
        "support_graph_ref": str(base_plan.get("support_graph_ref") or SUPPORT_GRAPH_FILE),
        "base_observation_plan_ref": OBSERVATION_PLAN_FILE,
        "profile_digest": profile_digest,
        "validation_digest": validation_digest,
        "coverage_digest": coverage_digest,
        "coverage_level_id": level_id,
        "coverage_level": level,
        "heading_count": 24,
        "panoramic_heading_count": 12,
        "poses": expanded_poses,
        "render_entries": expansion_entries,
        "config": dict(base_plan.get("config") or {}),
        "summary": summary,
    }


def write_support_observation_expansion(scene_dir: str | Path, expansion: Mapping[str, Any]) -> Path:
    """Atomically persist one additive expansion without touching the L0 plan."""
    if str(expansion.get("plan_kind") or "") != "observation_expansion":
        raise ValueError("not a support observation expansion")
    level_id = str(expansion.get("coverage_level_id") or "")
    return _atomic_json(Path(scene_dir) / support_observation_expansion_filename(level_id), expansion)


def list_support_observation_expansions(
    scene_dir: str | Path,
    *,
    base_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """List L0–L6 choices and identify sidecars tied to the current support build."""
    root = Path(scene_dir)
    if base_plan is None:
        base_path = root / OBSERVATION_PLAN_FILE
        base_plan = read_support_observation_plan(base_path) if base_path.is_file() else None
    base_digest = str((base_plan or {}).get("profile_digest") or "")
    levels: list[dict[str, Any]] = []
    for level in OBSERVATION_EXPANSION_LEVELS:
        level_id = str(level["level_id"])
        if level_id == "l0_action_required":
            levels.append({
                **level,
                "plan_ref": OBSERVATION_PLAN_FILE,
                "prepared": bool(base_plan),
                "current": bool(base_plan),
                "summary": dict((base_plan or {}).get("summary") or {}),
            })
            continue
        path = root / support_observation_expansion_filename(level_id)
        expansion: dict[str, Any] | None = None
        if path.is_file():
            try:
                expansion = read_support_observation_plan(path)
            except (OSError, ValueError, json.JSONDecodeError):
                expansion = None
        current = bool(expansion and str(expansion.get("profile_digest") or "") == base_digest)
        levels.append({
            **level,
            "plan_ref": path.name,
            "prepared": bool(expansion),
            "current": current,
            "summary": dict((expansion or {}).get("summary") or {}),
        })
    return {"base_profile_digest": base_digest, "levels": levels}


def support_render_graph(plan: Mapping[str, Any]) -> ViewpointGraph:
    nodes = []
    for pose in plan.get("poses") or []:
        if not isinstance(pose, Mapping): continue
        position = pose.get("position") or []
        if len(position) < 2: continue
        nodes.append(ViewpointNode(node_id=str(pose["motion_node_id"]), position=[float(position[0]), float(position[1]), 0.0], tags=["navigation_support", str(pose.get("tier") or "ACTION_NATIVE")], headings=[ViewpointHeading(heading_id=heading, yaw_deg=index * 15.0) for index, heading in enumerate(_all_heading_ids(24))], extras={"profile_id": PROFILE_ID, "available_heading_ids": list(pose.get("available_heading_ids") or [])}))
    if not nodes: raise ValueError("support observation plan has no poses")
    coverage_digest = str(plan.get("coverage_digest") or plan.get("profile_digest") or "")
    return ViewpointGraph(scene_id=str(plan["scene_id"]), graph_id=f"{plan.get('place_graph_id', 'place')}_support_render_{coverage_digest[:12]}", node_heading_count=24, nodes=nodes, edges=[], metadata={"profile_id": PROFILE_ID, "profile_digest": str(plan.get("profile_digest") or ""), "coverage_digest": coverage_digest, "coverage_level_id": plan.get("coverage_level_id"), "render_only": True})


def render_positions_from_support_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    positions = {str(pose["motion_node_id"]): pose["position"] for pose in plan.get("poses") or [] if isinstance(pose, Mapping)}
    rows: list[dict[str, Any]] = []
    for entry in plan.get("render_entries") or []:
        if not isinstance(entry, Mapping): continue
        point = positions.get(str(entry.get("motion_node_id")))
        if point is None: raise ValueError("support render entry references a missing pose")
        heading = str(entry.get("heading_id") or "")
        rows.append({"node_id": str(entry["motion_node_id"]), "heading_id": heading, "x": float(point[0]), "y": float(point[1]), "yaw_deg": float(heading.split("_", 1)[1]), "render_mode": PROFILE_ID, "tier": entry.get("tier"), "available_heading_ids": list(entry.get("available_heading_ids") or []), "polar_batch_key": entry.get("polar_batch_key"), "polar_batch_size": entry.get("polar_batch_size"), "profile_digest": plan.get("profile_digest")})
    return rows


def plan_support_episodes(
    *,
    support_graph: Mapping[str, Any],
    observation_plan: Mapping[str, Any],
    num_pairs: int,
    split_counts: Mapping[str, int],
    modalities: Sequence[str] | None = None,
    seed: int = 0,
    min_forward_actions: int = 4,
    max_forward_actions: int = 48,
) -> list[EpisodeManifest]:
    """Sample balanced, executable support-state episodes without new renders.

    A support graph deliberately contains many 0.25 m action states.  Treating
    every adjacent pair as a training episode would inflate a split with trivial
    one-step examples and let the longest blueprint dominate.  The default
    range therefore keeps episodes in the 1--12 m movement band and samples
    candidate subpaths round-robin across approved blueprints.
    """
    from .rollout import scale_split_counts, split_for_index
    if str(support_graph.get("profile_id") or "") != PROFILE_ID or str(observation_plan.get("profile_id") or "") != PROFILE_ID: raise ValueError("support sidecar profile mismatch")
    if str(support_graph.get("profile_digest") or "") != str(observation_plan.get("profile_digest") or ""): raise ValueError("support observation digest mismatch")
    poses = {str(item["motion_node_id"]): item for item in support_graph.get("poses") or [] if isinstance(item, Mapping)}
    states = {str(item["motion_state_id"]): item for item in support_graph.get("states") or [] if isinstance(item, Mapping)}
    transitions = {str(item["transition_id"]): item for item in support_graph.get("transitions") or [] if isinstance(item, Mapping)}
    pose_available = {str(item["motion_node_id"]): set(str(value) for value in item.get("available_heading_ids") or []) for item in observation_plan.get("poses") or [] if isinstance(item, Mapping)}
    forward_by_motion_edge = {
        str(transition["motion_edge_id"]): transition
        for transition in transitions.values()
        if transition.get("action") == "move_forward"
    }
    # Episodes are sampled from approved blueprint corridors, not arbitrary
    # anchor pairs in the backbone.  This preserves the reviewed place shortest
    # path and avoids silently turning a support-tree branch into an LCA detour.
    if num_pairs <= 0:
        raise ValueError("num_pairs must be positive")
    if min_forward_actions <= 0:
        raise ValueError("min_forward_actions must be positive")
    if max_forward_actions < min_forward_actions:
        raise ValueError("max_forward_actions must be >= min_forward_actions")
    candidates_by_blueprint: dict[str, list[tuple[str, str, str, set[str]]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    for route in support_graph.get("blueprint_routes") or []:
        if not isinstance(route, Mapping):
            continue
        route_edge_ids = [str(value) for value in route.get("motion_edge_ids") or []]
        route_pose_ids = {str(value) for value in route.get("motion_pose_ids") or []}
        if not route_edge_ids or len(route_pose_ids) < 2:
            continue
        allowed_motion_edges = set(route_edge_ids)
        allowed_transition_ids = {
            transition_id
            for transition_id, transition in transitions.items()
            if (
                transition.get("action") == "move_forward"
                and str(transition.get("motion_edge_id")) in allowed_motion_edges
            ) or (
                transition.get("action") in {"turn_left", "turn_right"}
                and str(states[str(transition["source_state_id"])]["motion_pose_id"]) in route_pose_ids
                and str(states[str(transition["target_state_id"])]["motion_pose_id"]) in route_pose_ids
            )
        }
        forward_transitions = [forward_by_motion_edge.get(edge_id) for edge_id in route_edge_ids]
        if any(value is None for value in forward_transitions):
            raise ValueError(f"support_route_transition_missing:{route.get('blueprint_id')}")
        # Every contiguous subpath is a unique route-pair candidate. It lets a
        # small number of approved long blueprints yield many train/test
        # episodes without synthesising unsupported global start/goal pairs.
        for start_index in range(len(route_edge_ids)):
            for end_index in range(start_index + 1, len(route_edge_ids) + 1):
                forward_count = end_index - start_index
                if not min_forward_actions <= forward_count <= max_forward_actions:
                    continue
                forward_source = str(forward_transitions[start_index]["source_state_id"])
                forward_goal = str(forward_transitions[end_index - 1]["target_state_id"])
                if forward_source == forward_goal or (forward_source, forward_goal) in seen_pairs:
                    continue
                seen_pairs.add((forward_source, forward_goal))
                candidates_by_blueprint[str(route.get("blueprint_id") or "")].append(
                    (str(route.get("blueprint_id") or ""), forward_source, forward_goal, allowed_transition_ids)
                )
    if not candidates_by_blueprint:
        raise ValueError(
            "support graph has no executable approved blueprint pairs in the "
            f"{min_forward_actions}..{max_forward_actions} forward-action range"
        )
    rng = random.Random(seed)
    blueprint_ids = list(candidates_by_blueprint)
    rng.shuffle(blueprint_ids)
    for blueprint_id in blueprint_ids:
        rng.shuffle(candidates_by_blueprint[blueprint_id])
    # Round-robin selection protects route/room coverage: a 60-step blueprint
    # no longer contributes thousands of candidates before a short approved
    # doorway route appears at all.
    candidates: list[tuple[str, str, str, set[str]]] = []
    while blueprint_ids:
        next_round: list[str] = []
        for blueprint_id in blueprint_ids:
            rows = candidates_by_blueprint[blueprint_id]
            if rows:
                candidates.append(rows.pop())
            if rows:
                next_round.append(blueprint_id)
        blueprint_ids = next_round
    split_spec = scale_split_counts({str(key): int(value) for key, value in split_counts.items()}, num_pairs)
    episodes: list[EpisodeManifest] = []
    for blueprint_id, source, goal, allowed_transition_ids in candidates:
        if len(episodes) >= num_pairs: break
        adj: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        for transition_id in allowed_transition_ids:
            transition = transitions[transition_id]
            adj[str(transition["source_state_id"])].append((str(transition["target_state_id"]), transition_id, float(transition.get("distance_m") or 0.01)))
        queue = [(0.0, source)]; dist = {source: 0.0}; prior: dict[str, tuple[str, str]] = {}; found: str | None = None
        while queue:
            cost, state_id = heapq.heappop(queue)
            if cost != dist.get(state_id): continue
            if state_id == goal: found = state_id; break
            for target, transition_id, amount in adj.get(state_id, []):
                next_cost = cost + amount
                if next_cost < dist.get(target, math.inf): dist[target] = next_cost; prior[target] = (state_id, transition_id); heapq.heappush(queue, (next_cost, target))
        if found is None: continue
        state_ids = [found]; transition_ids: list[str] = []
        while state_ids[-1] != source:
            previous, transition_id = prior[state_ids[-1]]; transition_ids.append(transition_id); state_ids.append(previous)
        state_ids.reverse(); transition_ids.reverse()
        actions: list[str] = []; trajectory: list[list[float]] = []; timesteps: list[EpisodeTimestep] = []
        valid = True
        for index, transition_id in enumerate(transition_ids):
            state = states[state_ids[index]]; pose_id = str(state["motion_pose_id"]); heading = str(state["heading_id"]); transition = transitions[transition_id]
            if heading not in pose_available.get(pose_id, set()): valid = False; break
            pose = poses[pose_id]["position"]; action = str(transition["action"]); agent_pose = [float(pose[0]), float(pose[1]), math.radians(float(heading.split("_", 1)[1]))]
            trajectory.append(agent_pose); actions.append(action); timesteps.append(EpisodeTimestep(timestep_index=index, timestamp=float(index), agent_pose=agent_pose, action=action, extras={"motion_profile": PROFILE_ID, "motion_state_id": state_ids[index], "heading_id": heading, "transition_id": transition_id, "available_heading_ids": sorted(pose_available[pose_id])}))
        if not valid or not timesteps: continue
        last_state = states[state_ids[-1]]; last_pose = poses[str(last_state["motion_pose_id"])]["position"]; last_heading = str(last_state["heading_id"]); final = [float(last_pose[0]), float(last_pose[1]), math.radians(float(last_heading.split("_", 1)[1]))]
        trajectory.append(final); actions.append("stop"); timesteps.append(EpisodeTimestep(timestep_index=len(timesteps), timestamp=float(len(timesteps)), agent_pose=final, action="stop", extras={"motion_profile": PROFILE_ID, "motion_state_id": state_ids[-1], "heading_id": last_heading, "available_heading_ids": sorted(pose_available[str(last_state["motion_pose_id"])])}))
        if last_heading not in pose_available.get(str(last_state["motion_pose_id"]), set()):
            continue
        split = split_for_index(split_spec, len(episodes))
        episodes.append(EpisodeManifest(
            episode_id=f"{support_graph['scene_id']}_{split}_ansv4_{len(episodes)+1:06d}",
            scene_id=str(support_graph["scene_id"]),
            split=split,
            start_pose=trajectory[0],
            goal_pose=trajectory[-1],
            goal_region=str(last_state["motion_pose_id"]),
            natural_language_instruction="Navigate safely to the destination.",
            trajectory=trajectory,
            actions=actions,
            timesteps=timesteps,
            metadata={
                "motion_profile": PROFILE_ID,
                "profile_digest": str(support_graph["profile_digest"]),
                "support_graph_ref": SUPPORT_GRAPH_FILE,
                "observation_plan_ref": OBSERVATION_PLAN_FILE,
                "modalities": list(modalities or []),
                "blueprint_id": blueprint_id,
                "pair_signature": _json_digest({
                    "blueprint_id": blueprint_id,
                    "source": source,
                    "goal": goal,
                    "states": state_ids,
                }),
            },
            navigation_mode=PROFILE_ID,
            graph_id=str(support_graph.get("place_graph_id") or ""),
            start_node=str(states[source]["motion_pose_id"]),
            goal_node=str(last_state["motion_pose_id"]),
            # Persist the actual action-state lineage rather than asking a
            # reader to reconstruct it from a sparse place graph.  Repeated
            # pose IDs are meaningful here: they represent in-place 15-degree
            # turns at the same canonical support pose.
            path_nodes=[str(states[state_id]["motion_pose_id"]) for state_id in state_ids],
            path_headings=[str(states[state_id]["heading_id"]) for state_id in state_ids],
        ))
    if len(episodes) < num_pairs:
        raise ValueError(
            f"support graph could only sample {len(episodes)}/{num_pairs} connected unique episodes "
            f"in the {min_forward_actions}..{max_forward_actions} forward-action range"
        )
    return episodes


def write_support_episodes(paths: Any, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    return [paths.write_episode(episode) for episode in episodes]
