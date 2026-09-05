"""Staged, pre-rendered navigation support graphs.

``adaptive_navigation_support_v4`` deliberately keeps topology authoring, route
approval, and dense action-space materialisation separate.  The old v3 route
motion sidecars remain readable but are never changed by this module.

The implementation is intentionally JSON-sidecar based so a support graph can be
audited before any expensive render tasks are submitted.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
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
from .viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointHeading, ViewpointNode

# Reuse the collision-tested continuous 15-degree action primitive.  These
# helpers are geometry utilities, not v3 route/backbone policy.
from .route_motion import (
    _action_grid_path,
    _all_heading_ids,
    _distance,
    _edge_portal_id,
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
# Render sweep coverage ladder.
#
# This is a different axis from OBSERVATION_EXPANSION_LEVELS below. Those add
# native *context* headings on top of the complete L0 action set; a full L0
# sweep of a production apartment costs ~118 GPU hours per polar camera
# variant, which is far too much to pay before knowing the dataset is good.
# The ladder here instead selects a growing *subset* of the same L0 plan,
# starting from only what the sampled episodes actually look at, so a usable
# dataset exists after the first rung and every later rung is add-only.
SWEEP_COVERAGE_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "level_id": "sv1_episode_headings",
        "label": "SV1 · episode headings",
        "description": "Only the (pose, heading) pairs the sampled episodes traverse.",
    },
    {
        "level_id": "sv2_base_panorama_12",
        "label": "SV2 · base 12-heading panorama",
        "description": "SV1 plus the 12 panorama headings at every place-anchored base pose.",
    },
    {
        "level_id": "sv3_support_4_plus_turns",
        "label": "SV3 · support 4 + episode turn context",
        "description": "SV2 plus 4 spread headings at every support pose and the immediate turn neighbours of each episode heading.",
    },
    {
        "level_id": "sv4_support_8_plus_turns",
        "label": "SV4 · support 8 + wider turn context",
        "description": "SV3 widened to 8 spread headings per support pose and two turn steps around each episode heading.",
    },
    {
        "level_id": "sv5_action_complete",
        "label": "SV5 · complete L0",
        "description": "Every entry in the L0 observation plan.",
    },
)

SWEEP_COVERAGE_LEVEL_IDS: tuple[str, ...] = tuple(level["level_id"] for level in SWEEP_COVERAGE_LEVELS)


def _spread_headings(available: Sequence[str], count: int) -> set[str]:
    """Pick ``count`` headings spread as evenly as possible over ``available``."""
    ordered = sorted(available)
    if not ordered or count <= 0:
        return set()
    if count >= len(ordered):
        return set(ordered)
    step = len(ordered) / float(count)
    return {ordered[min(len(ordered) - 1, int(round(index * step)))] for index in range(count)}


def _turn_neighbours(heading: str, radius: int) -> set[str]:
    number = _heading_number(heading)
    return {_heading_id(((number + offset) % 24) * 15.0, 24) for offset in range(-radius, radius + 1)}


def sweep_coverage_episode_digest(
    observation_plan: Mapping[str, Any],
    episodes: Iterable[Mapping[str, Any]],
) -> str:
    """Fingerprint the episode views a coverage rung would be built from.

    Only pairs the plan actually offers count, so this matches exactly what
    ``select_sweep_coverage`` selects and the listing can compare a stored rung
    against the current episodes without recomputing the selection.
    """
    available: dict[str, set[str]] = defaultdict(set)
    for entry in observation_plan.get("render_entries") or []:
        if isinstance(entry, Mapping):
            available[str(entry["motion_node_id"])].add(str(entry["heading_id"]))
    pairs = sorted({
        f"{pose_id}:{heading}"
        for episode in episodes
        for pose_id, heading in zip(
            [str(value) for value in (episode.get("path_nodes") or [])],
            [str(value) for value in (episode.get("path_headings") or [])],
        )
        if heading in available.get(pose_id, ())
    })
    return _json_digest({"episode_count": len(pairs), "pairs": pairs})


def select_sweep_coverage(
    *,
    support_graph: Mapping[str, Any],
    observation_plan: Mapping[str, Any],
    episodes: Iterable[Mapping[str, Any]] = (),
    level_id: str = "sv1_episode_headings",
) -> dict[str, Any]:
    """Select the L0 render entries a sweep coverage level needs.

    Every level is a subset of ``observation_plan`` and each level contains the
    one below it, so a sweep can be resumed upward without re-rendering. A
    heading is only ever selected when the plan actually offers it at that
    pose: this never invents a view the executable graph cannot use.
    """
    if level_id not in SWEEP_COVERAGE_LEVEL_IDS:
        raise ValueError(f"level_id must be one of {SWEEP_COVERAGE_LEVEL_IDS}")
    if str(support_graph.get("profile_digest") or "") != str(observation_plan.get("profile_digest") or ""):
        raise ValueError("support observation digest mismatch")
    level_index = SWEEP_COVERAGE_LEVEL_IDS.index(level_id)

    entries = [dict(item) for item in observation_plan.get("render_entries") or [] if isinstance(item, Mapping)]
    available: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        available[str(entry["motion_node_id"])].add(str(entry["heading_id"]))
    anchored_pose_ids = {
        str(pose["motion_node_id"])
        for pose in support_graph.get("poses") or []
        if isinstance(pose, Mapping) and pose.get("anchor_node_ids")
    }

    selected: set[tuple[str, str]] = set()
    episode_pairs: set[tuple[str, str]] = set()
    for episode in episodes:
        nodes = [str(value) for value in (episode.get("path_nodes") or [])]
        headings = [str(value) for value in (episode.get("path_headings") or [])]
        for pose_id, heading in zip(nodes, headings):
            if heading in available.get(pose_id, ()):
                episode_pairs.add((pose_id, heading))
    selected |= episode_pairs

    if level_index >= 1:
        panorama = {f"h_{angle:03d}" for angle in range(0, 360, 30)}
        for pose_id in anchored_pose_ids:
            selected |= {(pose_id, heading) for heading in available.get(pose_id, ()) & panorama}
    if level_index >= 2:
        spread = 4 if level_index == 2 else 8
        radius = 1 if level_index == 2 else 2
        for pose_id, headings in available.items():
            selected |= {(pose_id, heading) for heading in _spread_headings(sorted(headings), spread)}
        for pose_id, heading in sorted(episode_pairs):
            selected |= {
                (pose_id, neighbour)
                for neighbour in _turn_neighbours(heading, radius) & available.get(pose_id, set())
            }
    if level_index >= 4:
        selected = {(str(entry["motion_node_id"]), str(entry["heading_id"])) for entry in entries}

    chosen = [entry for entry in entries if (str(entry["motion_node_id"]), str(entry["heading_id"])) in selected]
    batch_count = len({str(entry.get("polar_batch_key") or "") for entry in chosen})
    total = len(entries)
    # Every rung below the complete one is derived from the episodes, so the
    # support digest alone cannot tell whether a stored rung is still current:
    # regenerating episodes silently changes what a rung should contain and
    # breaks the nesting guarantee between rungs prepared at different times.
    episode_digest = _json_digest({
        "episode_count": len(episode_pairs),
        "pairs": sorted(f"{pose}:{heading}" for pose, heading in episode_pairs),
    })
    assert episode_digest  # keeps the fingerprint definition next to its use
    return {
        "schema_version": "opticalnav.sweep_coverage_selection.v2",
        "profile_id": PROFILE_ID,
        "level_id": level_id,
        "profile_digest": str(support_graph.get("profile_digest") or ""),
        "episode_digest": episode_digest,
        "render_entries": chosen,
        "view_keys": [f"{entry['motion_node_id']}:{entry['heading_id']}" for entry in chosen],
        "summary": {
            "level_id": level_id,
            "selected_view_count": len(chosen),
            "l0_view_count": total,
            "selected_fraction": round(len(chosen) / total, 4) if total else 0.0,
            "selected_pose_count": len({str(entry["motion_node_id"]) for entry in chosen}),
            "episode_view_count": len(episode_pairs),
            "polar_batch_count": batch_count,
            "gpu_time_estimate_hours_per_polar_camera_variant": round(
                len(chosen) * float((observation_plan.get("config") or {}).get("heading_render_seconds", 30.24)) / 3600.0, 4
            ),
        },
    }


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
    # Conservative enough to keep a physical body away from walls, but not so
    # large that ordinary office doorways disappear from the v4 place domain.
    # Together with the 0.10 m policy buffer and 0.03 m raster epsilon this is
    # a 0.28 m effective wall clearance.
    "robot_radius_m": 0.15,
    "safety_margin_m": 0.10,
    "geometry_epsilon_m": 0.03,
    # Imported Infinigen authoring regions can leave a 0.60–0.75 m floor-mask
    # discontinuity at a physically open doorway. This threshold-span bound
    # never bypasses the body-height wall or portal certification checks.
    "doorway_gap_m": 0.75,
    "max_place_nodes": 300,
    "max_support_poses": 2000,
    "max_panorama_poses": 80,
    # L0 contains every action-required native heading. It is an immutable
    # geometry/execution contract, so it must not fail merely because a scene
    # exceeds an arbitrary fixed image count. ``0`` means no independent L0
    # observation cap; ``max_polar_batches`` remains the bounded transport
    # unit, while L1–L6 opt-in expansion controls the additional context and
    # therefore the memory/throughput budget. Deployments that need a hard
    # cap can still set a positive value explicitly.
    "max_polar_observations": 0,
    # Like the L0 observation count, the number of four-heading transport
    # batches follows the certified action graph.  Zero keeps it unbounded by
    # default; deployment policy may set a positive cap explicitly.
    "max_polar_batches": 0,
    "trunk_demand_coverage": 0.95,
    "lane_offset_m": 0.25,
    "junction_patch_radius_m": 0.75,
    "portal_patch_radius_m": 0.75,
    "goal_patch_radius_m": 0.50,
    # Place-graph centre lines are collision-certified, but their endpoint
    # raster phase can require a short local action detour around a corner.
    # This remains smaller than a support patch and every emitted chord is
    # still checked against the 0.28 m-eroded motion grid.
    "action_corridor_radius_m": 0.75,
    # A place corridor can be certified at place level yet be too tight for the
    # action lattice once the grid is eroded by robot_radius + safety_margin.
    # "error" (default) aborts the build and reports the corridor for review.
    # "relief" retries that corridor against the same grid dilated back by
    # ``corridor_relief_radius_m`` -- i.e. the physically-fits-but-no-margin
    # domain -- and records every edge that needed it.
    "unmaterializable_corridor_policy": "error",
    "corridor_relief_radius_m": 0.1,
    "min_pose_spacing_m": 0.15,
    # Build first normalizes all approved-corridor samples into one executable
    # support network.  A hard merge is allowed only when every surviving L0
    # forward edge remains in its original 0.25 ± 0.025 m contract.
    #
    # There is a known dead band between this radius and
    # ``global_stitch_min_distance_m``: a pair 0.15-0.225 m apart is too far
    # to be the same place and too close to be one 0.25 m action step, so
    # neither rule owns it (measured on a production apartment scene: ~198
    # such unconnected pairs). Raising the radius to close that band was
    # tried and measured *worse* on the same scene -- each consolidation
    # cluster grows, and a cluster is rejected as a whole when any one member
    # would break the 0.25 +/- 0.025 m chord contract, so successful merges
    # fell 70 -> 46 while rejections rose 189 -> 456 and every unconnected-pair
    # band grew. Closing the band needs per-member cluster rejection, not a
    # bigger radius.
    "hard_merge_radius_m": 0.10,
    # Two poses further apart than the merge radius but closer than a full
    # action step are a real, traversable gap: link them directly instead of
    # leaving a visible hole. A forward edge is therefore no longer a fixed
    # 0.25 m step but any certified chord in
    # [min_link_distance_m, forward_step_m + forward_tolerance_m].
    "min_link_distance_m": 0.10,
    "global_stitch_enabled": True,
    "global_stitch_min_distance_m": 0.10,
    "global_stitch_target_distance_m": 0.25,
    "global_stitch_max_distance_m": 0.275,
    # A stitch chord is emitted with its bearing snapped to the nearest 15
    # degree action heading, so 7.5 degrees is exactly the nearest-neighbour
    # rounding boundary -- past it another heading is closer. The previous
    # 2.0 was an extra fidelity guard that turned out to be the main thing
    # suppressing cross-blueprint edges: on a production apartment scene it
    # left 73 pose pairs unconnected inside the legal 0.225-0.275 m window,
    # 69 of them rejected for heading alone. At 7.5 with a degree cap of 8
    # only 1 of those 73 stays unconnected (a wall blocks it). The cost is
    # up to 7.5 degrees between where a pose faces and where that single
    # step actually travels (~3.3 cm lateral over 0.25 m); pose coordinates
    # stay exact, so nothing accumulates.
    "global_stitch_max_degree": 8,
    "global_stitch_heading_tolerance_deg": 7.5,
    # Retained only as a diagnostic soft-cluster overlay for older artifacts.
    "l1_proximity_enabled": True,
    "l1_proximity_max_distance_m": 0.25,
    "l1_proximity_max_degree": 4,
    # A Blueprint reuses an already materialised canonical lane when doing so
    # stays inside this budget, and only grows its own parallel ribbon when it
    # cannot. A tight budget therefore *creates* near-duplicate ribbons whose
    # 15 degree lattice phase does not line up with the lane beside them,
    # landing poses 0.15-0.225 m apart -- too far to merge, too close to be
    # one 0.25 m step, so nothing can connect them. Widening the budget lets
    # those Blueprints share the canonical lane instead: on a production
    # apartment scene local ribbons fell 46 -> 20 place edges, unconnectable
    # pairs 198 -> 103, poses 895 -> 787 and render views 14% cheaper.
    "directness_stretch": 1.60,
    "directness_slack_m": 2.00,
    "heading_render_seconds": 30.24,
    # Turn freedom is a render-budget lever: every full-turn pose renders its
    # whole closure. ``structural`` grants it only where the executable graph
    # actually needs it (degree != 2 terminals/junctions, portals, route
    # endpoints, component roots); pass-through anchors keep local arcs only.
    # ``patch_tags`` reproduces the legacy tag-driven behaviour.
    "turn_freedom_policy": "structural",
    # ``shortest_arc`` closes a pair of opposite headings through one half
    # circle (13 states); ``full_circle`` reproduces the legacy 24-state fan.
    "turn_closure_policy": "shortest_arc",
    # Lateral band: one side lane on each side of every straight canonical run,
    # placed on the 60-degree triangular lattice so every chord stays an exact
    # 0.25 m native-heading action.  Switch chords are emitted at the run ends
    # and every ``lateral_switch_interval_steps`` poses in between.  Every
    # segment gets a mandatory entry and exit switch regardless of the
    # interval, and each switch is itself the dominant render-budget cost
    # (~16 extra headings between its two arcs).  A production scene can have
    # hundreds of short (2-3 chord) straight runs from ordinary doorway/corner
    # fragmentation; ``lateral_min_run_chords`` is therefore deliberately
    # above the geometric minimum of 1 so the band only grows on runs long
    # enough (>= 1 m) that the mandatory entry/exit pair is a small fraction
    # of their own length. Measured on a production apartment scene (291
    # poses / 1,957 views with the closure fix alone): min_run=2 grows the
    # render plan to ~6,750 views (+130% over the pre-band baseline of
    # 2,978); min_run=4 with the default switch interval below keeps it at
    # ~3,313 views (+11%).
    # Attach an unmaterialised place-graph node to any support pose exactly one
    # native action step away, so a reviewed lane running past a place node no
    # longer leaves it unreachable.
    "base_attach_enabled": True,
    "lateral_band_enabled": True,
    "lateral_switch_interval_steps": 3,
    "lateral_min_run_chords": 4,
}

LATERAL_LANE = "lateral_band"
LINK_EDGE_TYPES = {"cross_blueprint_stitch", "base_attach"}
LINK_LANES = {"global_stitch", "global_executable_stitch", "base_attach"}
LATERAL_TAG = "lateral"


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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update({key: value for key, value in dict(values or {}).items() if value is not None})
    for name in (
        "place_heading_count", "action_heading_count", "max_place_nodes", "max_support_poses",
        "max_panorama_poses", "max_polar_observations", "max_polar_batches",
        "global_stitch_max_degree", "lateral_switch_interval_steps", "lateral_min_run_chords",
    ):
        cfg[name] = int(cfg[name])
    cfg["lateral_band_enabled"] = _coerce_bool(cfg["lateral_band_enabled"])
    cfg["base_attach_enabled"] = _coerce_bool(cfg["base_attach_enabled"])
    cfg["turn_freedom_policy"] = str(cfg["turn_freedom_policy"])
    cfg["turn_closure_policy"] = str(cfg["turn_closure_policy"])
    if cfg["turn_freedom_policy"] not in {"structural", "patch_tags"}:
        raise ValueError("turn_freedom_policy must be structural or patch_tags")
    if cfg["turn_closure_policy"] not in {"shortest_arc", "full_circle"}:
        raise ValueError("turn_closure_policy must be shortest_arc or full_circle")
    if cfg["lateral_switch_interval_steps"] < 1:
        raise ValueError("lateral_switch_interval_steps must be >= 1")
    if cfg["lateral_min_run_chords"] < 1:
        raise ValueError("lateral_min_run_chords must be >= 1")
    for name in (
        "turn_deg", "forward_step_m", "forward_tolerance_m", "robot_radius_m", "safety_margin_m",
        "geometry_epsilon_m", "doorway_gap_m", "trunk_demand_coverage", "lane_offset_m", "junction_patch_radius_m",
        "portal_patch_radius_m", "goal_patch_radius_m", "min_pose_spacing_m", "directness_stretch",
        "directness_slack_m", "heading_render_seconds", "action_corridor_radius_m",
        "hard_merge_radius_m", "global_stitch_min_distance_m", "global_stitch_target_distance_m",
        "global_stitch_max_distance_m", "global_stitch_heading_tolerance_deg",
        "min_link_distance_m", "corridor_relief_radius_m",
    ):
        cfg[name] = float(cfg[name])
    cfg["unmaterializable_corridor_policy"] = str(cfg["unmaterializable_corridor_policy"])
    if cfg["unmaterializable_corridor_policy"] not in {"error", "relief"}:
        raise ValueError("unmaterializable_corridor_policy must be error or relief")
    if cfg["corridor_relief_radius_m"] < 0.0:
        raise ValueError("corridor_relief_radius_m must be >= 0")
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
        portal = _edge_portal_id(edge) or ""
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
        portal = _edge_portal_id(edge) or ""
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


def reconcile_route_blueprints_after_place_graph_edit(
    payload: Mapping[str, Any],
    place_graph: ViewpointGraph,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep route-review intent through a sparse place-graph topology edit.

    Approval is a reviewer decision about the *start/goal route intent*, not a
    vote for one transient edge id.  Re-generating every blueprint after a
    manual connector repair used to silently discard that work.  Instead, each
    existing pair is resolved against the edited certified graph.  Its status
    is retained when a path remains; only an approved pair that has genuinely
    become disconnected returns to ``proposed`` for review.

    This deliberately does not invent new automatic blueprints after an edit.
    The operator's collection stays stable while they repair a corridor.  A
    later explicit regeneration can add new coverage candidates if desired.
    """
    if str(payload.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("not an adaptive_navigation_support_v4 route blueprint payload")

    node_ids = {str(node.node_id) for node in place_graph.nodes}
    rows: list[dict[str, Any]] = []
    preserved_ids: list[str] = []
    relinked_ids: list[str] = []
    review_required_ids: list[str] = []

    for source_row in payload.get("blueprints") or []:
        if not isinstance(source_row, Mapping):
            continue
        row = dict(source_row)
        blueprint_id = str(row.get("blueprint_id") or "")
        start_id = str(row.get("start_anchor_id") or "")
        goal_id = str(row.get("goal_anchor_id") or "")
        prior_status = str(row.get("status") or "proposed")
        prior_edges = [str(value) for value in row.get("place_path_edge_ids") or []]

        if not start_id or not goal_id or start_id not in node_ids or goal_id not in node_ids:
            if prior_status == "approved":
                row["status"] = "proposed"
                row["review_reason"] = "anchor_removed_after_place_graph_edit"
                review_required_ids.append(blueprint_id)
            rows.append(row)
            continue

        try:
            path = shortest_graph_path(place_graph, start_id, goal_id)
        except ValueError:
            if prior_status == "approved":
                row["status"] = "proposed"
                row["review_reason"] = "route_disconnected_after_place_graph_edit"
                review_required_ids.append(blueprint_id)
            rows.append(row)
            continue

        next_edges = _path_edge_ids(path)
        row["place_path_node_ids"] = list(path.nodes)
        row["place_path_edge_ids"] = next_edges
        row["place_path_distance_m"] = round(float(path.distance_m), 6)
        if next_edges != prior_edges:
            row["topology_relinked"] = True
            relinked_ids.append(blueprint_id)
        else:
            row.pop("topology_relinked", None)
        row.pop("review_reason", None)
        if prior_status == "approved":
            preserved_ids.append(blueprint_id)
        rows.append(row)

    coverage = dict(payload.get("coverage") or {})
    coverage["approved_feature_ids"] = sorted({
        str(feature_id)
        for row in rows
        if str(row.get("status") or "") == "approved"
        for feature_id in row.get("coverage_feature_ids") or []
    })
    result = {
        **dict(payload),
        "place_graph_id": str(place_graph.graph_id),
        "blueprints": rows,
        "coverage": coverage,
    }
    result["blueprint_digest"] = _json_digest({key: value for key, value in result.items() if key != "blueprint_digest"})
    return result, {
        "preserved_approved_blueprint_ids": preserved_ids,
        "relinked_blueprint_ids": relinked_ids,
        "review_required_blueprint_ids": review_required_ids,
    }


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
        if _edge_portal_id(edge):
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
    allow_global_stitches: bool = True,
    allow_lateral: bool = True,
) -> tuple[list[str], list[str], float] | None:
    adjacency: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for edge_id, edge in edges.items():
        if not allow_lateral and str(edge.get("lane") or "") == LATERAL_LANE:
            continue
        place_ids = set(str(item) for item in edge.get("place_edge_ids") or [])
        if allowed_place_edges is not None and place_ids and not place_ids <= allowed_place_edges:
            continue
        if allowed_place_edges is not None and not allow_global_stitches and str(edge.get("edge_type") or "") == "cross_blueprint_stitch":
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


def _heading_closure(headings: set[str], policy: str = "full_circle") -> set[str]:
    """Required native 15-degree states for transitions among patch directions.

    ``full_circle`` joins every ordered pair; two opposite headings therefore
    fill both half circles (24 states).  ``shortest_arc`` joins each unordered
    pair once and resolves the 180-degree tie through the positive half circle,
    so a U-turn remains executable with 13 states instead of 24.
    """
    values = {int(value.split("_", 1)[1]) // 15 for value in headings if value.startswith("h_")}
    if len(values) <= 1:
        return {_heading_id(value * 15.0, 24) for value in values}
    result = set(values)
    ordered = sorted(values)
    for index, left in enumerate(ordered):
        partners = ordered[index + 1:] if policy == "shortest_arc" else ordered
        for right in partners:
            delta = (right - left) % 24
            if delta > 12:
                delta -= 24
            step = 1 if delta >= 0 else -1
            for item in range(0, abs(delta) + 1):
                result.add((left + step * item) % 24)
    return {_heading_id(value * 15.0, 24) for value in result}


def _heading_number(heading: str) -> int:
    return int(heading.split("_", 1)[1]) // 15


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
    """Return executable backbone edges without inventing an unreviewed bridge.

    A route Blueprint is the executable-support ownership boundary.  Earlier
    versions grew a global MST over *all* certified place links to join every
    approved route into one action component.  That silently promoted an
    unowned coverage/manual connector into an execution requirement: a failed
    0.25 m lattice on that connector then blocked otherwise independent,
    reviewed routes.

    Keep each reviewed route component independently phase-consistent instead.
    An operator can still deliberately join components by marking a certified
    place edge ``support_backbone_pin=true``; that explicit pin is the only
    *automatic* ownerless edge eligible for the executable trunk. Ordinary
    bridge, portal, demand and ``vp_coverage_*`` links remain review
    candidates.

    A hand-drawn place edge is a second, deliberate exception: the operator
    who dragged it into the map already gave it an explicit, individual
    review (unlike an auto-sampled bridge/coverage candidate), so it is
    treated the same as a ``support_backbone_pin``. It still has to be a
    certified (``collision_free``) place edge to reach this function at all.
    """
    edge_by_id = {str(edge.edge_id): edge for edge in graph.edges if edge.collision_free}
    if not required_edges:
        raise ValueError("navigation support has no required place edges")
    missing = sorted(required_edges - set(edge_by_id))
    if missing:
        raise ValueError("support trunk references non-certified place edges: " + ", ".join(missing))

    def _is_manual(edge: ViewpointEdge) -> bool:
        return bool((edge.extras or {}).get("manual", False)) or str(edge.edge_id).startswith("edge_manual")

    pinned = {
        str(edge.edge_id)
        for edge in edge_by_id.values()
        if bool((edge.extras or {}).get("support_backbone_pin", False)) or _is_manual(edge)
    }
    return set(required_edges) | pinned


def _normalize_global_support_graph(
    poses: dict[str, dict[str, Any]],
    edges: dict[str, dict[str, Any]],
    anchor_poses: dict[str, set[str]],
    path_sequences: list[list[str]],
    *,
    motion_grid: TraversabilityGrid,
    config: Mapping[str, Any],
    blueprint_ids_by_place_edge: Mapping[str, set[str]],
) -> dict[str, Any]:
    """Apply build-time merge/stitch rules to the executable support graph."""
    raw_poses = {pose_id: deepcopy(pose) for pose_id, pose in poses.items()}
    raw_edges = [deepcopy(edge) for _, edge in sorted(edges.items())]
    merge_radius = float(config.get("hard_merge_radius_m", config["min_pose_spacing_m"]))
    # Normalization used a full forward step as its lower bound while
    # validate_navigation_support accepts any chord from min_link_distance_m
    # upward ("short links close gaps that a fixed-step lattice cannot
    # express"). Two layers of the same builder disagreed, so a pose pair that
    # survived the hard merge but sat closer than one action -- which is
    # exactly the band between hard_merge_radius_m and a forward step -- aborted
    # the build instead of producing the short link validation would have
    # accepted. Take the same lower bound as validation.
    action_min = min(
        float(config["forward_step_m"]) - float(config["forward_tolerance_m"]),
        float(config["min_link_distance_m"]),
    )
    action_max = float(config["forward_step_m"]) + float(config["forward_tolerance_m"])

    incident_portals: dict[str, set[str]] = defaultdict(set)
    for edge in raw_edges:
        for pose_id in (str(edge["source"]), str(edge["target"])):
            incident_portals[pose_id].update(str(value) for value in edge.get("portal_ids") or [] if str(value))

    parent = {pose_id: pose_id for pose_id in raw_poses}
    cluster_members: dict[str, set[str]] = {pose_id: {pose_id} for pose_id in raw_poses}
    def find(pose_id: str) -> str:
        while parent[pose_id] != pose_id:
            parent[pose_id] = parent[parent[pose_id]]
            pose_id = parent[pose_id]
        return pose_id
    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            keep, drop = min(left, right), max(left, right)
            parent[drop] = keep
            cluster_members[keep] |= cluster_members.pop(drop)

    # An action chord is what makes two poses *different places*: merging its
    # endpoints would delete the step between them. Chains of near pairs can
    # otherwise walk along a lane (0.10 m + 0.10 m) and pull chord-connected
    # endpoints into one all-or-nothing cluster, which is then rejected
    # wholesale -- losing even the merges that were individually valid.
    chord_pairs = {
        frozenset((str(edge["source"]), str(edge["target"])))
        for edge in raw_edges
        if str(edge["source"]) != str(edge["target"])
    }

    def chord_connected(left: str, right: str) -> bool:
        return any(
            frozenset((source, target)) in chord_pairs
            for source in cluster_members[left]
            for target in cluster_members[right]
        )

    merge_pair_count = 0
    candidate_pairs: list[tuple[float, str, str]] = []
    ids = sorted(raw_poses)
    for index, source_id in enumerate(ids):
        source_portals = tuple(sorted(incident_portals[source_id]))
        for target_id in ids[index + 1:]:
            if tuple(sorted(incident_portals[target_id])) != source_portals:
                continue
            distance = _distance(raw_poses[source_id]["position"], raw_poses[target_id]["position"])
            if distance < merge_radius - 1e-9:
                candidate_pairs.append((distance, source_id, target_id))
    # Closest first, so a genuine duplicate wins over a merely nearby pose.
    for distance, source_id, target_id in sorted(candidate_pairs):
        left, right = find(source_id), find(target_id)
        if left == right or chord_connected(left, right):
            continue
        merge_pair_count += 1
        union(source_id, target_id)

    component_members: dict[str, list[str]] = defaultdict(list)
    for pose_id in ids:
        component_members[find(pose_id)].append(pose_id)
    components = [members for members in component_members.values() if len(members) > 1]
    component_for_pose = {
        pose_id: index for index, members in enumerate(components) for pose_id in members
    }

    def pose_priority(pose_id: str) -> tuple[int, int, str]:
        pose = raw_poses[pose_id]
        tags = set(str(value) for value in pose.get("tags") or [])
        return (0 if pose.get("anchor_node_ids") else 1, 0 if tags & {"portal", "junction", "patch"} else 1, pose_id)

    representatives = {index: min(members, key=pose_priority) for index, members in enumerate(components)}
    # A transitive <0.15 m spatial group is not automatically a valid hard
    # merge: the chosen existing representative must itself be close and
    # collision-visible to every member. Otherwise it remains a soft cluster.
    soft_components: set[int] = {
        index
        for index, members in enumerate(components)
        if any(
            _distance(raw_poses[representatives[index]]["position"], raw_poses[member]["position"]) >= merge_radius - 1e-9
            or not _world_segment_safe(
                motion_grid,
                tuple(raw_poses[representatives[index]]["position"][:2]),
                tuple(raw_poses[member]["position"][:2]),
            )
            for member in members
            if member != representatives[index]
        )
    }

    def replacement_map() -> dict[str, str]:
        result = dict.fromkeys(raw_poses)
        for pose_id in raw_poses:
            component = component_for_pose.get(pose_id)
            result[pose_id] = pose_id if component is None or component in soft_components else representatives[component]
        return result

    # A component is only a hard merge when every action chord remains an
    # executable 0.25 ± tolerance edge after all replacements happen together.
    while True:
        mapping = replacement_map()
        unsafe_components: set[int] = set()
        for edge in raw_edges:
            raw_source, raw_target = str(edge["source"]), str(edge["target"])
            source, target = mapping[raw_source], mapping[raw_target]
            if source == target:
                continue
            distance = _distance(raw_poses[source]["position"], raw_poses[target]["position"])
            safe = _world_segment_safe(motion_grid, tuple(raw_poses[source]["position"][:2]), tuple(raw_poses[target]["position"][:2]))
            if not safe or not (action_min - 1e-9 <= distance <= action_max + 1e-9):
                unsafe_components.update(
                    component_for_pose[pose_id]
                    for pose_id in (raw_source, raw_target)
                    if pose_id in component_for_pose
                )
        next_soft = soft_components | unsafe_components
        if next_soft == soft_components:
            break
        soft_components = next_soft

    mapping = replacement_map()
    members_by_final: dict[str, list[str]] = defaultdict(list)
    for raw_id, final_id in mapping.items():
        members_by_final[final_id].append(raw_id)
    normalized_poses: dict[str, dict[str, Any]] = {}
    for final_id, members in sorted(members_by_final.items()):
        pose = deepcopy(raw_poses[final_id])
        pose["motion_node_id"] = final_id
        pose["motion_pose_id"] = final_id
        pose["source_motion_pose_ids"] = sorted(members)
        pose["source_pose_ids"] = sorted(members)
        pose["merge_kind"] = "hard" if len(members) > 1 else "native"
        pose["tags"] = sorted({str(value) for member in members for value in raw_poses[member].get("tags") or []})
        pose["anchor_node_ids"] = sorted({str(value) for member in members for value in raw_poses[member].get("anchor_node_ids") or []})
        normalized_poses[final_id] = pose

    normalized_edges: dict[str, dict[str, Any]] = {}
    by_action_chord: dict[tuple[str, str, str], str] = {}
    collapsed_edge_count = 0
    for raw_edge in raw_edges:
        source, target = mapping[str(raw_edge["source"])], mapping[str(raw_edge["target"])]
        if source == target:
            collapsed_edge_count += 1
            continue
        distance = _distance(normalized_poses[source]["position"], normalized_poses[target]["position"])
        if not (action_min - 1e-9 <= distance <= action_max + 1e-9):
            raise ValueError(f"support_normalization_non_action_chord:{raw_edge['motion_edge_id']}:{distance:.5f}")
        if not _world_segment_safe(motion_grid, tuple(normalized_poses[source]["position"][:2]), tuple(normalized_poses[target]["position"][:2])):
            raise ValueError(f"support_normalization_unsafe_chord:{raw_edge['motion_edge_id']}")
        key = (source, target, str(raw_edge.get("action") or "move_forward"))
        if key in by_action_chord:
            edge = normalized_edges[by_action_chord[key]]
            edge["source_motion_edge_ids"] = sorted(set(edge.get("source_motion_edge_ids") or []) | {str(raw_edge["motion_edge_id"])})
            edge["place_edge_ids"] = sorted(set(edge.get("place_edge_ids") or []) | {str(value) for value in raw_edge.get("place_edge_ids") or [] if str(value)})
            edge["portal_ids"] = sorted(set(edge.get("portal_ids") or []) | {str(value) for value in raw_edge.get("portal_ids") or [] if str(value)})
            collapsed_edge_count += 1
            continue
        edge = deepcopy(raw_edge)
        edge["source"], edge["target"], edge["distance_m"] = source, target, distance
        edge["source_motion_edge_ids"] = [str(raw_edge["motion_edge_id"])]
        normalized_edges[str(edge["motion_edge_id"])] = edge
        by_action_chord[key] = str(edge["motion_edge_id"])

    anchor_poses.clear()
    for pose_id, pose in normalized_poses.items():
        for anchor_id in pose.get("anchor_node_ids") or []:
            anchor_poses[str(anchor_id)].add(pose_id)

    pose_blueprints: dict[str, set[str]] = defaultdict(set)
    for edge in normalized_edges.values():
        owners = {
            blueprint_id
            for place_edge_id in edge.get("place_edge_ids") or []
            for blueprint_id in blueprint_ids_by_place_edge.get(str(place_edge_id), set())
        }
        edge["source_blueprint_ids"] = sorted(owners)
        pose_blueprints[str(edge["source"])].update(owners)
        pose_blueprints[str(edge["target"])].update(owners)
    for pose_id, pose in normalized_poses.items():
        pose["blueprint_ids"] = sorted(pose_blueprints[pose_id])

    stitch_candidates = 0
    stitch_pairs = 0
    existing_pairs = {tuple(sorted((str(edge["source"]), str(edge["target"])))) for edge in normalized_edges.values()}
    degree: dict[str, int] = defaultdict(int)
    candidates: list[tuple[float, str, str]] = []
    if bool(config.get("global_stitch_enabled", True)):
        stitch_min = float(config["global_stitch_min_distance_m"])
        stitch_max = float(config["global_stitch_max_distance_m"])
        heading_tolerance = float(config.get("global_stitch_heading_tolerance_deg", 2.0))
        normalized_portals: dict[str, tuple[str, ...]] = defaultdict(tuple)
        for pose_id in normalized_poses:
            normalized_portals[pose_id] = tuple(sorted({
                str(value) for edge in normalized_edges.values()
                if pose_id in {str(edge["source"]), str(edge["target"])}
                for value in edge.get("portal_ids") or [] if str(value)
            }))
        normalized_ids = sorted(normalized_poses)
        for index, source in enumerate(normalized_ids):
            for target in normalized_ids[index + 1:]:
                if tuple(sorted((source, target))) in existing_pairs:
                    continue
                # Blueprint provenance is metadata, not a linking predicate:
                # any two poses closer than one action step are a real gap and
                # get a direct edge. Restricting this to differing blueprints
                # used to leave same-corridor poses 0.10-0.15 m apart with
                # neither a merge nor a link once the overlap radius dropped.
                if normalized_portals[source] != normalized_portals[target]:
                    continue
                distance = _distance(normalized_poses[source]["position"], normalized_poses[target]["position"])
                if not (stitch_min - 1e-9 <= distance <= stitch_max + 1e-9):
                    continue
                yaw = _yaw_to(normalized_poses[source]["position"], normalized_poses[target]["position"])
                heading_error = abs((yaw - round(yaw / 15.0) * 15.0 + 180.0) % 360.0 - 180.0)
                if heading_error > heading_tolerance + 1e-9:
                    continue
                if not _world_segment_safe(motion_grid, tuple(normalized_poses[source]["position"][:2]), tuple(normalized_poses[target]["position"][:2])):
                    continue
                stitch_candidates += 1
                candidates.append((abs(distance - float(config["global_stitch_target_distance_m"])), source, target))
        degree_limit = max(0, int(config.get("global_stitch_max_degree", 4)))
        for _distance_error, source, target in sorted(candidates, key=lambda value: (value[0], value[1], value[2])):
            if degree_limit == 0 or degree[source] >= degree_limit or degree[target] >= degree_limit:
                continue
            stitch_pairs += 1
            degree[source] += 1
            degree[target] += 1
            distance = _distance(normalized_poses[source]["position"], normalized_poses[target]["position"])
            owners = sorted(pose_blueprints[source] | pose_blueprints[target])
            for left, right, direction in ((source, target, "forward"), (target, source, "reverse")):
                edge_id = f"support_stitch_{stitch_pairs:05d}_{direction}"
                normalized_edges[edge_id] = {
                    "motion_edge_id": edge_id, "source": left, "target": right,
                    "distance_m": distance, "action": "move_forward",
                    "edge_type": "cross_blueprint_stitch", "lane": "global_stitch",
                    "place_edge_ids": [], "portal_ids": [], "source_blueprint_ids": owners,
                    "collision_free": True,
                    "safety_certificate": {
                        "effective_clearance_m": float(config.get("effective_clearance_m", 0.0)),
                        "world_segment_safe": True, "portal_open": True,
                    },
                }
            for pose_id in (source, target):
                normalized_poses[pose_id]["tags"] = sorted(set(normalized_poses[pose_id].get("tags") or []) | {"junction", "global_stitch"})

    sequences: list[list[str]] = []
    seen_sequences: set[tuple[str, ...]] = set()
    for sequence in path_sequences:
        remapped = []
        for pose_id in sequence:
            final_id = mapping.get(str(pose_id), str(pose_id))
            if not remapped or remapped[-1] != final_id:
                remapped.append(final_id)
        if len(remapped) >= 2 and tuple(remapped) not in seen_sequences:
            sequences.append(remapped)
            seen_sequences.add(tuple(remapped))
    for edge in normalized_edges.values():
        if str(edge.get("edge_type")) == "cross_blueprint_stitch":
            sequence = (str(edge["source"]), str(edge["target"]))
            if sequence not in seen_sequences:
                sequences.append(list(sequence))
                seen_sequences.add(sequence)

    for index, members in enumerate(components):
        if index not in soft_components:
            continue
        cluster_id = f"soft_cluster_{index + 1:03d}"
        for pose_id in members:
            if pose_id in normalized_poses:
                normalized_poses[pose_id]["soft_cluster_id"] = cluster_id

    poses.clear(); poses.update(normalized_poses)
    edges.clear(); edges.update(normalized_edges)
    path_sequences[:] = sequences
    soft_clusters = [
        {
            "cluster_id": f"soft_cluster_{index + 1:03d}",
            "member_motion_pose_ids": members,
            "representative_motion_pose_id": representatives[index],
            "reason": "hard_merge_would_break_action_chord",
        }
        for index, members in enumerate(components) if index in soft_components
    ]
    return {
        "schema_version": "opticalnav.global_support_normalization.v1",
        "raw_pose_count": len(raw_poses), "raw_edge_count": len(raw_edges),
        "hard_merge_spatial_pair_count": merge_pair_count,
        "hard_merge_candidate_cluster_count": len(components),
        "hard_merge_cluster_count": len(components) - len(soft_components),
        "soft_cluster_count": len(soft_clusters), "soft_clusters": soft_clusters,
        "hard_merged_pose_count": len(raw_poses) - len(normalized_poses),
        "collapsed_action_edge_count": collapsed_edge_count,
        "cross_blueprint_stitch_candidate_count": stitch_candidates,
        "cross_blueprint_stitch_pair_count": stitch_pairs,
        "cross_blueprint_stitch_edge_count": stitch_pairs * 2,
        "normalized_pose_count": len(normalized_poses),
        "normalized_edge_count": len(normalized_edges),
    }


def _lateral_band_stage(
    poses: Mapping[str, Mapping[str, Any]],
    edges: Mapping[str, Mapping[str, Any]],
    path_sequences: list[list[str]],
    *,
    grid: TraversabilityGrid,
    cfg: Mapping[str, Any],
    add_path: Callable[..., list[str]],
    pose_exists: Callable[[tuple[float, float]], bool],
) -> tuple[dict[str, int], dict[str, set[tuple[str, str]]]]:
    """Emit one side lane per side of every straight canonical run.

    Side poses sit on the 60-degree triangular lattice: ``B_i = A_i +
    0.25·(sin(y±60°), cos(y±60°))``.  Every chain chord ``B_i→B_{i+1}`` then
    equals the main chord vector, the entry ``A_i→B_i`` is an exact 0.25 m
    chord at ``y±60°`` and the exit ``B_i→A_{i+1}`` an exact chord at ``y∓60°``
    — all on the 15-degree action lattice, so the differential-drive contract
    (``move_forward``/``turn_left``/``turn_right``) is unchanged.  Each segment
    always gets an entry and an exit switch; additional switches alternate
    every ``lateral_switch_interval_steps`` poses.  Unsafe chords split a run;
    nothing here can raise, so the band never becomes a build blocker.

    Returns ``(diagnostics, switch_turn_pairs)``: the latter maps a pose id to
    the ``(heading, heading)`` corner(s) it needs -- the lane's own travel
    heading turning into the switch heading -- which the caller folds into its
    turn-freedom computation so a switch pose keeps only that one local arc
    instead of a full closure.
    """
    diagnostics = {
        "lateral_run_count": 0, "lateral_segment_count": 0, "lateral_switch_count": 0,
        "lateral_unsafe_chord_skip_count": 0, "lateral_occupied_point_skip_count": 0,
    }
    switch_turn_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)

    def register_switch_turn(pose_id: str, heading_a: str, heading_b: str) -> None:
        # The switch chord is bidirectional (add_path always emits both
        # directions), so the pose also carries the two mirrored headings
        # 180 degrees opposite (the "departing backwards"/"arriving from
        # behind" pair of the same physical chord).  Registering the mirror
        # too keeps every state this stage creates reachable, at the cost of
        # one more small arc rather than a full closure.
        switch_turn_pairs[pose_id].add((heading_a, heading_b))
        switch_turn_pairs[pose_id].add((_heading_id(_heading_number(heading_a) * 15.0 + 180.0, 24), _heading_id(_heading_number(heading_b) * 15.0 + 180.0, 24)))

    if not bool(cfg.get("lateral_band_enabled", False)):
        return diagnostics, dict(switch_turn_pairs)
    step = float(cfg["forward_step_m"]); tolerance = float(cfg["forward_tolerance_m"])
    interval = max(1, int(cfg["lateral_switch_interval_steps"]))
    min_run = max(1, int(cfg["lateral_min_run_chords"]))

    def position(pose_id: str) -> tuple[float, float]:
        value = poses[pose_id]["position"]
        return float(value[0]), float(value[1])

    edge_by_pair: dict[tuple[str, str], Mapping[str, Any]] = {}
    for _edge_id, edge in sorted(edges.items()):
        edge_by_pair.setdefault((str(edge["source"]), str(edge["target"])), edge)
    portal_tagged = {pose_id for pose_id, pose in poses.items() if "portal" in (pose.get("tags") or [])}

    candidate_runs: list[list[dict[str, Any]]] = []

    def flush(chords: list[dict[str, Any]]) -> None:
        if len(chords) >= min_run:
            candidate_runs.append(list(chords))

    for sequence in list(path_sequences):
        chords: list[dict[str, Any]] = []
        for source, target in zip(sequence, sequence[1:]):
            edge = edge_by_pair.get((str(source), str(target)))
            blocked = (
                edge is None or bool(edge.get("portal_ids")) or str(edge.get("lane") or "") == LATERAL_LANE
                or source in portal_tagged or target in portal_tagged
            )
            if blocked:
                flush(chords); chords = []
                continue
            heading = _heading_id(_yaw_to(position(source), position(target)), 24)
            if chords and chords[-1]["heading"] != heading:
                flush(chords); chords = []
            place_edge_ids = [str(value) for value in edge.get("place_edge_ids") or []]
            chords.append({
                "source": str(source), "target": str(target), "edge_id": str(edge["motion_edge_id"]),
                "heading": heading, "place_edge_id": place_edge_ids[0] if place_edge_ids else "",
            })
        flush(chords)

    # Forward/reverse sequences and several blueprints describe the same lane;
    # keep only maximal runs by undirected chord set.
    runs: list[list[dict[str, Any]]] = []
    run_keys: list[frozenset[frozenset[str]]] = []
    for chords in sorted(candidate_runs, key=lambda item: (-len(item), item[0]["source"], item[0]["target"])):
        key = frozenset(frozenset((chord["source"], chord["target"])) for chord in chords)
        if any(key <= existing for existing in run_keys):
            continue
        runs.append(chords); run_keys.append(key)
    diagnostics["lateral_run_count"] = len(runs)

    def chord_ok(source: tuple[float, float], target: tuple[float, float], expected_heading: str | None) -> bool:
        distance = _distance(source, target)
        if not (step - tolerance - 1e-9 <= distance <= step + tolerance + 1e-9):
            return False
        if expected_heading is not None and _heading_id(_yaw_to(source, target), 24) != expected_heading:
            return False
        if not _world_segment_safe(grid, source, target):
            diagnostics["lateral_unsafe_chord_skip_count"] += 1
            return False
        return True

    for chords in runs:
        main = [chords[0]["source"], *(chord["target"] for chord in chords)]
        count = len(chords)
        lane_yaw = _heading_number(chords[0]["heading"]) * 15.0
        lane_heading = chords[0]["heading"]
        for sign, side in ((1, "right"), (-1, "left")):
            side_yaw = lane_yaw + sign * 60.0
            offset = (step * math.sin(math.radians(side_yaw)), step * math.cos(math.radians(side_yaw)))
            entry_heading = _heading_id(side_yaw, 24)
            exit_heading = _heading_id(lane_yaw - sign * 60.0, 24)
            side_points = [
                (position(main[index])[0] + offset[0], position(main[index])[1] + offset[1])
                for index in range(count)
            ]
            pose_ok = [not pose_exists(point) for point in side_points]
            diagnostics["lateral_occupied_point_skip_count"] += sum(1 for flag in pose_ok if not flag)
            entry_ok = [pose_ok[index] and chord_ok(position(main[index]), side_points[index], entry_heading) for index in range(count)]
            exit_ok = [pose_ok[index] and chord_ok(side_points[index], position(main[index + 1]), exit_heading) for index in range(count)]
            chain_ok = [
                pose_ok[index] and pose_ok[index + 1] and chord_ok(side_points[index], side_points[index + 1], lane_heading)
                for index in range(count - 1)
            ]
            phase = 0 if sign == 1 else interval // 2
            exit_phase = ((interval + 1) // 2) % interval
            index = 0
            while index < count:
                if not pose_ok[index]:
                    index += 1
                    continue
                last = index
                while last + 1 < count and chain_ok[last]:
                    last += 1
                first = index
                while first <= last and not entry_ok[first]:
                    first += 1
                end = last
                while end >= first and not exit_ok[end]:
                    end -= 1
                index = last + 1
                if first >= end or end - first < max(1, min_run - 1):
                    continue
                diagnostics["lateral_segment_count"] += 1
                for chord_index in range(first, end):
                    chord = chords[chord_index]
                    extras = {"band_parent_motion_edge_ids": [chord["edge_id"]], "band_side": side}
                    add_path([side_points[chord_index], side_points[chord_index + 1]], place_edge_id=chord["place_edge_id"], lane=LATERAL_LANE, edge_type="lateral_lane", tags=(LATERAL_TAG,), extras=extras)
                    add_path([side_points[chord_index + 1], side_points[chord_index]], place_edge_id=chord["place_edge_id"], lane=LATERAL_LANE, edge_type="lateral_lane", tags=(LATERAL_TAG,), extras=extras)
                for pose_index in range(first, end + 1):
                    relative = pose_index - first + phase
                    chord = chords[pose_index]
                    extras = {"band_parent_motion_edge_ids": [chord["edge_id"]], "band_side": side}
                    want_entry = pose_index == first or (relative % interval == 0 and entry_ok[pose_index])
                    want_exit = pose_index == end or (relative % interval == exit_phase and exit_ok[pose_index])
                    if want_entry:
                        forward_ids = add_path([position(main[pose_index]), side_points[pose_index]], place_edge_id=chord["place_edge_id"], lane=LATERAL_LANE, edge_type="lateral_switch", extras=extras)
                        add_path([side_points[pose_index], position(main[pose_index])], place_edge_id=chord["place_edge_id"], lane=LATERAL_LANE, edge_type="lateral_switch", extras=extras)
                        diagnostics["lateral_switch_count"] += 1
                        # The switch chord itself only gives each endpoint a
                        # plain two-heading in/out pair.  Register the actual
                        # corner -- the lane's own travel heading turning into
                        # the switch heading -- at both ends so the ordinary
                        # local-turn-pair machinery synthesises just that one
                        # arc (both directions, via its later symmetrisation)
                        # instead of a full closure at every switch pose.
                        register_switch_turn(main[pose_index], lane_heading, entry_heading)
                        register_switch_turn(forward_ids[-1], lane_heading, entry_heading)
                    if want_exit:
                        forward_ids = add_path([side_points[pose_index], position(main[pose_index + 1])], place_edge_id=chord["place_edge_id"], lane=LATERAL_LANE, edge_type="lateral_switch", extras=extras)
                        add_path([position(main[pose_index + 1]), side_points[pose_index]], place_edge_id=chord["place_edge_id"], lane=LATERAL_LANE, edge_type="lateral_switch", extras=extras)
                        diagnostics["lateral_switch_count"] += 1
                        register_switch_turn(forward_ids[0], lane_heading, exit_heading)
                        register_switch_turn(main[pose_index + 1], lane_heading, exit_heading)
    return diagnostics, dict(switch_turn_pairs)


def build_navigation_support(
    place_graph: ViewpointGraph,
    blueprints: Mapping[str, Any],
    *,
    annotation: SceneAnnotation | None,
    motion_grid: TraversabilityGrid,
    config: Mapping[str, Any] | None = None,
    on_progress: Callable[[str, float, Mapping[str, Any]], None] | None = None,
    normalizer: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a directed, collision-certified ribbon support graph in memory.

    ``normalizer`` is an explicit algorithm seam. Callers that leave it unset
    retain the production-v1 behaviour; experimental callers may inject a
    versioned strategy whose id is included in the support profile digest.
    """
    cfg = _config(config)
    support_algorithm_id = str(getattr(normalizer, "algorithm_id", "") or "")
    if support_algorithm_id:
        requested_algorithm_id = str(cfg.get("support_algorithm_id") or support_algorithm_id)
        if requested_algorithm_id != support_algorithm_id:
            raise ValueError(
                "support normalizer/config algorithm mismatch: "
                f"{support_algorithm_id} != {requested_algorithm_id}"
            )
        # _support_digest hashes the complete config. Candidate artifacts can
        # therefore never reuse or masquerade as production-v1 support.
        cfg["support_algorithm_id"] = support_algorithm_id
    if place_graph.node_heading_count != 12:
        raise ValueError("place graph must have 12 headings")
    if str(blueprints.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("route blueprints are not adaptive_navigation_support_v4")
    if not [item for item in blueprints.get("blueprints") or [] if str(item.get("status")) == "approved"]:
        raise ValueError("approve at least one route blueprint before building navigation support")
    def report(stage: str, progress: float, **detail: Any) -> None:
        if on_progress: on_progress(stage, max(0.0, min(1.0, progress)), detail)

    effective_grid, restored_portals = _v3_portal_aware_grid(place_graph, motion_grid)
    # Relief domain for ``unmaterializable_corridor_policy == "relief"``.  The
    # motion grid is eroded by robot_radius + safety_margin; dilating it back by
    # ``corridor_relief_radius_m`` recovers the corridor the robot physically
    # fits through with a reduced margin.  Built once, lazily, and used only as
    # a retry for a corridor the strict domain cannot materialize.
    relaxed_corridor_edge_ids: list[str] = []
    _relief_grid_cache: list[TraversabilityGrid | None] = []

    def relief_grid() -> "TraversabilityGrid | None":
        if _relief_grid_cache:
            return _relief_grid_cache[0]
        grid: TraversabilityGrid | None = None
        if cfg["unmaterializable_corridor_policy"] == "relief" and cfg["corridor_relief_radius_m"] > 0.0:
            try:
                import numpy as _np
                from scipy import ndimage as _ndimage

                iterations = max(1, int(round(
                    cfg["corridor_relief_radius_m"] / float(effective_grid.spec.resolution)
                )))
                dilated = _ndimage.binary_dilation(
                    _np.asarray(effective_grid.traversable, dtype=bool), iterations=iterations,
                )
                grid = TraversabilityGrid(
                    spec=effective_grid.spec, traversable=dilated, hazard=effective_grid.hazard,
                )
            except Exception:
                grid = None
        _relief_grid_cache.append(grid)
        return grid

    def corridor_path(start, goal, params, *, guide, edge_id, **kwargs):
        """Strict action path, with an optional reduced-margin retry."""
        path = _action_grid_path(effective_grid, start, goal, params, guide=guide, **kwargs)
        if path is not None and len(path) >= 2:
            return path
        grid = relief_grid()
        if grid is None:
            return path
        relaxed = _action_grid_path(grid, start, goal, params, guide=guide, **kwargs)
        if relaxed is not None and len(relaxed) >= 2:
            if str(edge_id) not in relaxed_corridor_edge_ids:
                relaxed_corridor_edge_ids.append(str(edge_id))
            return relaxed
        return path

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
    # One action ribbon per directed certified place edge. Approved routes
    # borrow these paths rather than growing a fresh near-coincident lattice.
    action_paths: dict[tuple[str, str, str], list[str]] = {}
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
        portal_ids: Iterable[str] = (), extras: Mapping[str, Any] | None = None,
    ) -> list[str]:
        nonlocal edge_counter
        if len(points) < 2: return []
        portal_ids = tuple(sorted({str(value) for value in portal_ids if str(value)}))
        ids = [ensure_pose(point, tags=tags, anchor_ids=([anchor_start] if index == 0 and anchor_start else []) + ([anchor_end] if index == len(points) - 1 and anchor_end else [])) for index, point in enumerate(points)]
        for source, target in zip(ids, ids[1:]):
            source_point = tuple(poses[source]["position"][:2]); target_point = tuple(poses[target]["position"][:2])
            distance = _distance(source_point, target_point)
            if not (cfg["min_link_distance_m"] - 1e-9 <= distance <= cfg["forward_step_m"] + cfg["forward_tolerance_m"] + 1e-9):
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
                **{str(key): deepcopy(value) for key, value in (extras or {}).items()},
            }
        path_sequences.append(ids)
        return ids

    # Every reviewed place component gets one canonical physical root. Sampling
    # every edge independently creates incompatible 15-degree lattice phases;
    # conversely, forcing unrelated reviewed components through an automatic
    # global connector makes an ownerless edge a hidden build blocker. The
    # resulting components are each strongly connected and route-complete, but
    # are only joined when an explicit support_backbone_pin owns that connector.
    backbone_edge_ids = _canonical_backbone_edges(place_graph, required_edges, rows)
    backbone_adjacency: dict[str, list[tuple[str, Any]]] = defaultdict(list)
    for edge_id in backbone_edge_ids:
        edge = edge_by_id[edge_id]
        backbone_adjacency[str(edge.source)].append((str(edge.target), edge))
        backbone_adjacency[str(edge.target)].append((str(edge.source), edge))
    approved_rows = [row for row in rows if str(row.get("status")) == "approved"]
    node_by_id = _node_map(place_graph)
    representative: dict[str, str] = {}
    visited: set[str] = set()
    component_root_anchor_ids: list[str] = []
    canonical_centerline_edges: list[str] = []
    canonical_cycle_edge_ids: list[str] = []
    unmaterialized_canonical_cycle_edge_ids: list[str] = []
    narrow_edges: list[str] = []
    root_candidates = [str(row["start_anchor_id"]) for row in approved_rows]
    root_candidates.extend(sorted(backbone_adjacency))
    for root_anchor_id in root_candidates:
        if root_anchor_id in visited or root_anchor_id not in backbone_adjacency:
            continue
        root_anchor = node_by_id.get(root_anchor_id)
        if root_anchor is None:
            raise ValueError(f"support_root_anchor_missing:{root_anchor_id}")
        root_cell = _nearest_safe_cell(effective_grid, tuple(root_anchor.position[:2]))
        if root_cell is None:
            raise ValueError(f"support_root_anchor_unreachable:{root_anchor_id}")
        root_point = cell_to_world(effective_grid.spec, *root_cell)
        root_pose_id = ensure_pose(root_point, tags=("patch", "junction"), anchor_ids=(root_anchor_id,))
        representative[root_anchor_id] = root_pose_id
        visited.add(root_anchor_id)
        component_root_anchor_ids.append(root_anchor_id)
        pending = [root_anchor_id]
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
                path = corridor_path(
                    parent_point, guide[-1],
                    {
                        "forward_step_m": cfg["forward_step_m"],
                        "forward_tolerance_m": cfg["forward_tolerance_m"],
                        "heading_count": 24,
                        "action_corridor_radius_m": cfg["action_corridor_radius_m"],
                    },
                    guide=guide, edge_id=edge.edge_id, exact_start=True,
                )
                if path is None or len(path) < 2:
                    raise ValueError(f"support_corridor_unreachable:{edge.edge_id}")
                portal_id = _edge_portal_id(edge)
                portal_ids = [portal_id] if portal_id else []
                if portal_ids and not _portal_is_open(edge):
                    raise ValueError(f"support_portal_not_open:{portal_ids[0]}")
                edge_type = "portal_bridge" if portal_ids else "lane_forward"
                tags = ("lane", "portal") if portal_ids else ("lane",)
                forward_ids = add_path(path, place_edge_id=str(edge.edge_id), lane="canonical_center", edge_type=edge_type, anchor_start=parent_id, anchor_end=child_id, tags=tags, portal_ids=portal_ids)
                reverse_ids = add_path(list(reversed(path)), place_edge_id=str(edge.edge_id), lane="canonical_center", edge_type=edge_type, anchor_start=child_id, anchor_end=parent_id, tags=tags, portal_ids=portal_ids)
                action_paths[(str(edge.edge_id), parent_id, child_id)] = forward_ids
                action_paths[(str(edge.edge_id), child_id, parent_id)] = reverse_ids
                representative[child_id] = forward_ids[-1]
                canonical_centerline_edges.append(str(edge.edge_id))
                visited.add(child_id)
                pending.append(child_id)
                if len(canonical_centerline_edges) % 8 == 0:
                    report("support_backbone", 0.10 + 0.45 * len(canonical_centerline_edges) / max(1, len(backbone_edge_ids)), place_edge_count=len(canonical_centerline_edges), pose_count=len(poses))

    # A spanning tree establishes one lattice phase but omits its cycle edges.
    # Materialise those approved/pinned cycles from the existing endpoint poses
    # before processing any Blueprint. Every Blueprint can then borrow the
    # same physical action lane instead of emitting an almost coincident ribbon.
    for edge_id in sorted(backbone_edge_ids - set(canonical_centerline_edges)):
        edge = edge_by_id[edge_id]
        source_id, target_id = str(edge.source), str(edge.target)
        source_pose_id = representative.get(source_id)
        target_pose_id = representative.get(target_id)
        if source_pose_id is None or target_pose_id is None:
            unmaterialized_canonical_cycle_edge_ids.append(edge_id)
            continue
        source_point = tuple(poses[source_pose_id]["position"][:2])
        target_point = tuple(poses[target_pose_id]["position"][:2])
        guide = _edge_points(place_graph, edge)
        guide = [source_point, *guide[1:-1], target_point]
        # The tree can terminate a branch within one action of its place anchor.
        # First grow the shared cycle from that existing lattice phase. When it
        # reaches a different valid phase near the target anchor, close the two
        # phases with an action-only anchor patch. This keeps the connector in
        # the canonical topology rather than letting every Blueprint invent a
        # private near-coincident ribbon.
        cycle_path = corridor_path(
            source_point, target_point,
            {
                "forward_step_m": cfg["forward_step_m"],
                "forward_tolerance_m": cfg["forward_tolerance_m"],
                "heading_count": 24,
                "action_corridor_radius_m": cfg["action_corridor_radius_m"],
            },
            guide=guide, edge_id=edge_id, exact_start=True,
        )
        if cycle_path is None or len(cycle_path) < 2:
            unmaterialized_canonical_cycle_edge_ids.append(edge_id)
            continue
        patch_path: list[tuple[float, float]] | None = None
        if _distance(cycle_path[-1], target_point) > 1e-7:
            patch_path = corridor_path(
                cycle_path[-1], target_point,
                {
                    "forward_step_m": cfg["forward_step_m"],
                    "forward_tolerance_m": cfg["forward_tolerance_m"],
                    "heading_count": 24,
                    "action_corridor_radius_m": max(
                        cfg["action_corridor_radius_m"],
                        cfg["junction_patch_radius_m"],
                    ),
                },
                guide=[cycle_path[-1], target_point], edge_id=edge_id,
                exact_start=True, exact_goal=True,
            )
            if patch_path is None or len(patch_path) < 2:
                unmaterialized_canonical_cycle_edge_ids.append(edge_id)
                continue
        portal_id = _edge_portal_id(edge)
        portal_ids = [portal_id] if portal_id else []
        if portal_ids and not _portal_is_open(edge):
            raise ValueError(f"support_portal_not_open:{portal_ids[0]}")
        edge_type = "portal_bridge" if portal_ids else "lane_forward"
        tags = ("lane", "portal") if portal_ids else ("lane",)
        if patch_path is None:
            forward_ids = add_path(cycle_path, place_edge_id=edge_id, lane="canonical_cycle", edge_type=edge_type, anchor_start=source_id, anchor_end=target_id, tags=tags, portal_ids=portal_ids)
            reverse_ids = add_path(list(reversed(cycle_path)), place_edge_id=edge_id, lane="canonical_cycle", edge_type=edge_type, anchor_start=target_id, anchor_end=source_id, tags=tags, portal_ids=portal_ids)
        else:
            forward_cycle_ids = add_path(cycle_path, place_edge_id=edge_id, lane="canonical_cycle", edge_type=edge_type, anchor_start=source_id, tags=tags, portal_ids=portal_ids)
            forward_patch_ids = add_path(patch_path, place_edge_id=edge_id, lane="canonical_anchor_patch", edge_type="lane_forward", anchor_end=target_id, tags=("lane", "patch"))
            reverse_patch_ids = add_path(list(reversed(patch_path)), place_edge_id=edge_id, lane="canonical_anchor_patch", edge_type="lane_forward", anchor_start=target_id, tags=("lane", "patch"))
            reverse_cycle_ids = add_path(list(reversed(cycle_path)), place_edge_id=edge_id, lane="canonical_cycle", edge_type=edge_type, anchor_end=source_id, tags=tags, portal_ids=portal_ids)
            forward_ids = [*forward_cycle_ids, *forward_patch_ids[1:]]
            reverse_ids = [*reverse_patch_ids, *reverse_cycle_ids[1:]]
            path_sequences.extend((forward_ids, reverse_ids))
        action_paths[(edge_id, source_id, target_id)] = forward_ids
        action_paths[(edge_id, target_id, source_id)] = reverse_ids
        canonical_centerline_edges.append(edge_id)
        canonical_cycle_edge_ids.append(edge_id)
        if len(canonical_cycle_edge_ids) % 8 == 0:
            report("support_cycles", 0.56, place_edge_count=len(canonical_centerline_edges), cycle_edge_count=len(canonical_cycle_edge_ids), pose_count=len(poses))

    # All canonical tree and cycle lanes are built before review routes. Grow a
    # direct per-Blueprint ribbon only when its reviewed place-edge subset still
    # cannot be represented by that shared action topology.
    route_local_edge_ids: list[str] = []
    reused_canonical_blueprint_ids: list[str] = []
    for blueprint in approved_rows:
        path_nodes = [str(value) for value in blueprint.get("place_path_node_ids") or []]
        path_edge_ids = [str(value) for value in blueprint.get("place_path_edge_ids") or []]
        if len(path_nodes) != len(path_edge_ids) + 1 or not path_nodes:
            raise ValueError(f"blueprint_place_path_malformed:{blueprint.get('blueprint_id')}")
        if path_nodes[0] not in representative:
            raise ValueError(f"blueprint_anchor_unrepresented:{blueprint.get('blueprint_id')}:{path_nodes[0]}")
        # The canonical trunk already materialises many approved corridors.
        # Re-growing a second action ribbon for those same place edges gives
        # every viewpoint its own nearly coincident lattice phase. Besides
        # wasting render poses, those nodes used to appear as <0.15 m visual
        # duplicates even though a collision-certified route already existed.
        # Only grow a local ribbon when the route cannot be represented by the
        # current canonical support edges restricted to its reviewed corridor.
        existing_route = _dijkstra(
            poses,
            edges,
            anchor_poses.get(path_nodes[0], set()),
            anchor_poses.get(path_nodes[-1], set()),
            allowed_place_edges=set(path_edge_ids),
        )
        if existing_route is not None:
            reused_canonical_blueprint_ids.append(str(blueprint.get("blueprint_id") or ""))
            continue
        # A reviewed path can contain a cycle edge that is deliberately not
        # part of the canonical spanning tree. Before growing a second action
        # lattice for the whole blueprint, reuse an already materialised
        # approved support corridor when it remains within the route's audited
        # directness budget. The canonical pool contains only required
        # approved edges (plus explicit pins), never an automatic unowned
        # connector, so this joins overlapping blueprints without silently
        # promoting a new execution requirement.
        shared_route = _dijkstra(
            poses,
            edges,
            anchor_poses.get(path_nodes[0], set()),
            anchor_poses.get(path_nodes[-1], set()),
        )
        if shared_route is not None:
            _shared_pose_ids, _shared_edge_ids, shared_distance = shared_route
            approved_distance = float(blueprint["place_path_distance_m"])
            shared_upper = max(
                approved_distance * cfg["directness_stretch"],
                approved_distance + cfg["directness_slack_m"],
            )
            if shared_distance <= shared_upper + 1e-6:
                reused_canonical_blueprint_ids.append(str(blueprint.get("blueprint_id") or ""))
                continue
        route_pose_id = representative[path_nodes[0]]
        route_point = tuple(poses[route_pose_id]["position"][:2])
        route_sequence: list[str] = []
        reverse_route_sequence: list[str] = []
        for index, edge_id in enumerate(path_edge_ids):
            edge = edge_by_id.get(edge_id)
            source_id, target_id = path_nodes[index], path_nodes[index + 1]
            if edge is None or {str(edge.source), str(edge.target)} != {source_id, target_id}:
                raise ValueError(f"blueprint_place_path_invalid:{blueprint.get('blueprint_id')}:{edge_id}")
            known_path = action_paths.get((edge_id, source_id, target_id))
            if known_path is not None and known_path[0] == route_pose_id:
                known_reverse = action_paths.get((edge_id, target_id, source_id), list(reversed(known_path)))
                route_sequence.extend(known_path if not route_sequence else known_path[1:])
                reverse_route_sequence = known_reverse if not reverse_route_sequence else [*known_reverse, *reverse_route_sequence[1:]]
                route_pose_id = known_path[-1]
                route_point = tuple(poses[route_pose_id]["position"][:2])
                continue
            guide = _edge_points(place_graph, edge)
            if str(edge.source) != source_id:
                guide.reverse()
            guide = [route_point, *guide[1:]]
            path = _action_grid_path(
                effective_grid, route_point, guide[-1],
                {
                    "forward_step_m": cfg["forward_step_m"],
                    "forward_tolerance_m": cfg["forward_tolerance_m"],
                    "heading_count": 24,
                    "action_corridor_radius_m": cfg["action_corridor_radius_m"],
                },
                guide=guide, exact_start=True,
            )
            if path is None or len(path) < 2:
                raise ValueError(f"support_corridor_unreachable:{edge_id}")
            portal_id = _edge_portal_id(edge)
            portal_ids = [portal_id] if portal_id else []
            if portal_ids and not _portal_is_open(edge):
                raise ValueError(f"support_portal_not_open:{portal_ids[0]}")
            edge_type = "portal_bridge" if portal_ids else "route_forward"
            tags = ("route", "portal") if portal_ids else ("route",)
            forward_ids = add_path(
                path, place_edge_id=edge_id, lane="approved_route", edge_type=edge_type,
                anchor_start=source_id, anchor_end=target_id, tags=tags, portal_ids=portal_ids,
            )
            reverse_ids = add_path(
                list(reversed(path)), place_edge_id=edge_id, lane="approved_route", edge_type=edge_type,
                anchor_start=target_id, anchor_end=source_id, tags=tags, portal_ids=portal_ids,
            )
            if route_pose_id == representative.get(source_id):
                action_paths[(edge_id, source_id, target_id)] = forward_ids
                action_paths[(edge_id, target_id, source_id)] = reverse_ids
            route_sequence.extend(forward_ids if not route_sequence else forward_ids[1:])
            # The forward ribbon alone records only forward corner turns.  A
            # physical route is bidirectional: at the same intermediate
            # samples the reverse traversal also has to rotate into its next
            # segment.  Without this mirrored sequence, a long multi-turn
            # approved route appears as two one-way state islands and the
            # validator reports its *distant anchors* as a bogus jump edge.
            # Keep the reverse sequence for local-turn synthesis below; the
            # move edges themselves were already emitted above.
            reverse_route_sequence = reverse_ids if index == 0 else [*reverse_ids, *reverse_route_sequence[1:]]
            route_pose_id = forward_ids[-1]
            route_point = tuple(poses[route_pose_id]["position"][:2])
            route_local_edge_ids.append(edge_id)
        if route_sequence:
            # Route-level adjacency supplies 15° turns across original sparse
            # edge boundaries; individual per-edge paths cannot see that turn.
            path_sequences.append(route_sequence)
            path_sequences.append(reverse_route_sequence)
            terminal = poses[route_sequence[-1]]
            terminal["tags"] = sorted(set(terminal.get("tags") or []) | {"route", "patch", "junction"})

    # Only anchor/portal/junction locations carry broad turning freedom.  The
    # intermediate lane turns added below represent genuine local curvature,
    # not a place to reverse or change lane arbitrarily.
    incident_portals = {
        str(node_id)
        for edge_id in backbone_edge_ids
        for node_id in (str(edge_by_id[edge_id].source), str(edge_by_id[edge_id].target))
        if _edge_portal_id(edge_by_id[edge_id])
    }
    for anchor_id, pose_id in representative.items():
        tags = set(poses[pose_id].get("tags") or []) | {"patch"}
        if len(backbone_adjacency.get(anchor_id, [])) != 2 or anchor_id in incident_portals:
            tags.add("junction")
        if anchor_id in incident_portals:
            tags.add("portal")
        poses[pose_id]["tags"] = sorted(tags)
    report(
        "support_patches", 0.62, pose_count=len(poses),
        backbone_edge_count=len(backbone_edge_ids), route_local_edge_count=len(set(route_local_edge_ids)),
    )

    # Attach place-graph nodes that no approved corridor materialised. Such a
    # node is visible in the editor but has no support pose at all, so nothing
    # can ever reach it -- even when a certified lane already runs exactly one
    # action step away. Whenever a pose sits at a native 0.25 m chord from such
    # a node, mint the pose and emit that chord in both directions. The node
    # belongs to no approved blueprint by construction, so this only ever adds
    # cross-blueprint reach; it never rewrites an existing corridor.
    base_attach_diagnostics = {
        "base_attach_node_count": 0, "base_attach_edge_count": 0,
        "base_attach_unsafe_skip_count": 0, "base_attach_heading_skip_count": 0,
    }
    if bool(cfg.get("base_attach_enabled", True)):
        attach_min = float(cfg["global_stitch_min_distance_m"])
        attach_max = float(cfg["global_stitch_max_distance_m"])
        attach_tolerance = float(cfg["global_stitch_heading_tolerance_deg"])
        attach_degree = max(0, int(cfg["global_stitch_max_degree"]))
        for node in sorted(place_graph.nodes, key=lambda item: str(item.node_id)):
            node_id = str(node.node_id)
            if anchor_poses.get(node_id):
                continue
            node_point = (float(node.position[0]), float(node.position[1]))
            candidates: list[tuple[float, str]] = []
            for pose_id, pose in poses.items():
                distance = _distance(node_point, pose["position"])
                if not (attach_min - 1e-9 <= distance <= attach_max + 1e-9):
                    continue
                candidates.append((distance, pose_id))
            attached = 0
            for distance, pose_id in sorted(candidates):
                if attach_degree and attached >= attach_degree:
                    break
                pose_point = (float(poses[pose_id]["position"][0]), float(poses[pose_id]["position"][1]))
                yaw = _yaw_to(pose_point, node_point)
                heading_error = abs((yaw - round(yaw / 15.0) * 15.0 + 180.0) % 360.0 - 180.0)
                if heading_error > attach_tolerance + 1e-9:
                    base_attach_diagnostics["base_attach_heading_skip_count"] += 1
                    continue
                if not _world_segment_safe(effective_grid, pose_point, node_point):
                    base_attach_diagnostics["base_attach_unsafe_skip_count"] += 1
                    continue
                forward = add_path(
                    [pose_point, node_point], place_edge_id="", lane="base_attach",
                    edge_type="base_attach", anchor_end=node_id, tags=("base_attach",),
                )
                reverse = add_path(
                    [node_point, pose_point], place_edge_id="", lane="base_attach",
                    edge_type="base_attach", anchor_start=node_id, tags=("base_attach",),
                )
                base_attach_diagnostics["base_attach_edge_count"] += len(forward[1:]) + len(reverse[1:])
                attached += 1
            if attached:
                base_attach_diagnostics["base_attach_node_count"] += 1
    report("base_attach", 0.63, pose_count=len(poses), **base_attach_diagnostics)

    # Side lanes are grown from the finished canonical lattice and before the
    # global normalisation, so a side pose that lands next to another
    # blueprint's lane still takes part in hard merge / cross-blueprint stitch.
    lateral_diagnostics, lateral_switch_turn_pairs = _lateral_band_stage(
        poses, edges, path_sequences,
        grid=effective_grid, cfg=cfg, add_path=add_path,
        pose_exists=lambda point: _point_key(point) in pose_by_key,
    )
    if len(poses) > cfg["max_support_poses"]:
        raise ValueError(f"support_pose_budget_exceeded:{len(poses)}/{cfg['max_support_poses']}")
    report("lateral_band", 0.64, pose_count=len(poses), **lateral_diagnostics)

    # Provenance is retained, but no longer partitions the executable graph.
    # Normalisation happens before blueprint route/state derivation so the
    # resulting nodes and stitches are the graph that planners actually use.
    blueprint_ids_by_place_edge: dict[str, set[str]] = defaultdict(set)
    for blueprint in approved_rows:
        blueprint_id = str(blueprint.get("blueprint_id") or "")
        if not blueprint_id:
            continue
        for place_edge_id in blueprint.get("place_path_edge_ids") or []:
            blueprint_ids_by_place_edge[str(place_edge_id)].add(blueprint_id)
    normalize_support = normalizer or _normalize_global_support_graph
    global_normalization = normalize_support(
        poses,
        edges,
        anchor_poses,
        path_sequences,
        motion_grid=effective_grid,
        config=cfg,
        blueprint_ids_by_place_edge=blueprint_ids_by_place_edge,
    )
    report(
        "global_support_normalization", 0.67,
        normalized_pose_count=global_normalization["normalized_pose_count"],
        hard_merged_pose_count=global_normalization["hard_merged_pose_count"],
        cross_blueprint_stitch_pair_count=global_normalization["cross_blueprint_stitch_pair_count"],
    )
    # Normalisation can hard-merge a switch pose into a cross-blueprint
    # duplicate, changing its id.  Remap the switch corners onto whichever
    # final pose absorbed each raw id so the turn-freedom computation below
    # still finds them.
    if lateral_switch_turn_pairs:
        raw_to_final: dict[str, str] = {}
        for final_id, pose in poses.items():
            for raw_id in pose.get("source_motion_pose_ids") or [final_id]:
                raw_to_final[str(raw_id)] = final_id
        remapped_switch_turn_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for raw_id, pairs in lateral_switch_turn_pairs.items():
            final_id = raw_to_final.get(raw_id)
            if final_id is not None:
                remapped_switch_turn_pairs[final_id].update(pairs)
        lateral_switch_turn_pairs = dict(remapped_switch_turn_pairs)

    # Store direct certified support routes for every approved blueprint.  They
    # use only the blueprint's place corridors plus local patch edges.
    blueprint_routes: list[dict[str, Any]] = []
    for blueprint in rows:
        if str(blueprint.get("status")) != "approved": continue
        allowed = set(str(value) for value in blueprint.get("place_path_edge_ids") or [])
        found = _dijkstra(
            poses, edges,
            anchor_poses.get(str(blueprint["start_anchor_id"]), set()),
            anchor_poses.get(str(blueprint["goal_anchor_id"]), set()),
            allowed_place_edges=allowed,
            allow_global_stitches=False,
            allow_lateral=False,
        )
        execution_kind = "approved_corridor"
        if found is None:
            # The sparse reviewed route can contain a safe cycle edge that is
            # absent from the one-phase canonical tree.  Do not manufacture a
            # second lattice phase just to mirror that edge: fall back to the
            # already collision-checked canonical trunk, then enforce the
            # same directness bound below.  The result is explicit in the
            # route metadata so the reviewer can distinguish it from an exact
            # corridor materialisation.
            found = _dijkstra(
                poses, edges,
                anchor_poses.get(str(blueprint["start_anchor_id"]), set()),
                anchor_poses.get(str(blueprint["goal_anchor_id"]), set()),
                allow_lateral=False,
            )
            execution_kind = "canonical_safe_fallback"
        if found is None:
            raise ValueError(f"blueprint_support_unreachable:{blueprint['blueprint_id']}:no_safe_canonical_route")
        pose_ids, edge_ids, distance = found
        upper = max(float(blueprint["place_path_distance_m"]) * cfg["directness_stretch"], float(blueprint["place_path_distance_m"]) + cfg["directness_slack_m"])
        if distance > upper + 1e-6:
            raise ValueError(f"blueprint_directness_exceeded:{blueprint['blueprint_id']}:{distance:.3f}>{upper:.3f}")
        blueprint_routes.append({"blueprint_id": blueprint["blueprint_id"], "start_anchor_id": blueprint["start_anchor_id"], "goal_anchor_id": blueprint["goal_anchor_id"], "motion_pose_ids": pose_ids, "motion_edge_ids": edge_ids, "distance_m": distance, "place_path_distance_m": float(blueprint["place_path_distance_m"]), "directness_ratio": (distance / max(float(blueprint["place_path_distance_m"]), 1e-9)), "execution_kind": execution_kind})
        # A reused canonical route never grows its own ribbon (see the
        # per-blueprint materialisation above), so a pass-through anchor on
        # its actual traversed path can otherwise have no path_sequence
        # crossing it and therefore no local corner turn.  The Dijkstra result
        # above is exactly the pose sequence every consumer (episodes,
        # validation) treats as this blueprint's execution, so register it and
        # its reverse directly.
        if len(pose_ids) >= 2:
            path_sequences.append(list(pose_ids))
            path_sequences.append(list(reversed(pose_ids)))


    # Build a compact support topology alongside the executable L0 graph. L0
    # remains the exact 0.25 m action graph used by rollouts, episodes and
    # validation. The topology is a build artifact: nearby raw L0 poses are
    # clustered at the configured minimum spacing, existing L0 adjacencies are
    # collapsed into stable relations, and collision-safe L1 relations connect
    # nearby support nodes across blueprint boundaries.
    topology_min_spacing_m = float(cfg["min_pose_spacing_m"])
    topology_max_distance_m = float(cfg.get("l1_proximity_max_distance_m", cfg["forward_step_m"]))
    topology_max_degree = max(0, int(cfg.get("l1_proximity_max_degree", 4)))
    incident_place_edges: dict[str, set[str]] = defaultdict(set)
    incident_motion_edges: dict[str, set[str]] = defaultdict(set)
    for edge in edges.values():
        raw_edge_id = str(edge["motion_edge_id"])
        place_edge_ids = {str(value) for value in edge.get("place_edge_ids") or [] if str(value)}
        for pose_id in (str(edge["source"]), str(edge["target"])):
            incident_place_edges[pose_id].update(place_edge_ids)
            incident_motion_edges[pose_id].add(raw_edge_id)

    def topology_pose_priority(pose_id: str) -> tuple[int, int, str]:
        pose = poses[pose_id]
        tags = set(str(value) for value in pose.get("tags") or [])
        return (
            0 if pose.get("anchor_node_ids") else 1,
            0 if tags & {"portal", "junction", "patch"} else 1,
            pose_id,
        )

    raw_pose_to_topology_id: dict[str, str] = {}
    topology_members: dict[str, list[str]] = {}
    topology_nodes_by_id: dict[str, dict[str, Any]] = {}
    topology_node_ids: list[str] = []
    sub_min_spacing_pair_count = 0
    for raw_pose_id in sorted(poses, key=topology_pose_priority):
        raw_pose = poses[raw_pose_id]
        raw_point = tuple(raw_pose["position"][:2])
        nearby = [
            (_distance(raw_point, tuple(topology_nodes_by_id[node_id]["position"][:2])), node_id)
            for node_id in topology_node_ids
            if _distance(raw_point, tuple(topology_nodes_by_id[node_id]["position"][:2])) < topology_min_spacing_m - 1e-9
        ]
        if nearby:
            sub_min_spacing_pair_count += 1
            _, topology_node_id = min(nearby, key=lambda item: (item[0], item[1]))
            raw_pose_to_topology_id[raw_pose_id] = topology_node_id
            topology_members[topology_node_id].append(raw_pose_id)
            node = topology_nodes_by_id[topology_node_id]
            node["anchor_node_ids"] = sorted(set(node.get("anchor_node_ids") or []) | set(raw_pose.get("anchor_node_ids") or []))
            node["tags"] = sorted(set(node.get("tags") or []) | set(raw_pose.get("tags") or []))
            continue
        topology_node_id = f"support_topology_{len(topology_node_ids) + 1:05d}"
        raw_pose_to_topology_id[raw_pose_id] = topology_node_id
        topology_node_ids.append(topology_node_id)
        topology_members[topology_node_id] = [raw_pose_id]
        topology_nodes_by_id[topology_node_id] = {
            "topology_node_id": topology_node_id,
            "motion_node_id": topology_node_id,
            "position": list(raw_pose["position"]),
            "anchor_node_ids": list(raw_pose.get("anchor_node_ids") or []),
            "tags": list(raw_pose.get("tags") or []),
            "layer": "L1",
            "executable": False,
        }
    topology_nodes: list[dict[str, Any]] = []
    for topology_node_id in topology_node_ids:
        node = topology_nodes_by_id[topology_node_id]
        members = sorted(topology_members[topology_node_id])
        node["place_edge_ids"] = sorted({edge_id for pose_id in members for edge_id in incident_place_edges[pose_id]})
        node["raw_motion_edge_ids"] = sorted({edge_id for pose_id in members for edge_id in incident_motion_edges[pose_id]})
        topology_nodes.append({
            **node,
            "member_motion_pose_ids": members,
            "member_count": len(members),
        })

    topology_edges_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    raw_motion_edge_to_topology_edge_id: dict[str, str] = {}
    for raw_edge in sorted(edges.values(), key=lambda item: str(item["motion_edge_id"])):
        raw_edge_id = str(raw_edge["motion_edge_id"])
        source_id = raw_pose_to_topology_id[str(raw_edge["source"])]
        target_id = raw_pose_to_topology_id[str(raw_edge["target"])]
        if source_id == target_id:
            continue
        pair = tuple(sorted((source_id, target_id)))
        relation = topology_edges_by_pair.get(pair)
        if relation is None:
            topology_edge_id = f"support_topology_l0_{len(topology_edges_by_pair) + 1:05d}"
            relation = {
                "topology_edge_id": topology_edge_id,
                "motion_edge_id": topology_edge_id,
                "source": source_id,
                "target": target_id,
                "distance_m": _distance(
                    tuple(topology_nodes_by_id[source_id]["position"][:2]),
                    tuple(topology_nodes_by_id[target_id]["position"][:2]),
                ),
                "edge_type": "action_adjacency",
                "lane": "l0_action_adjacency",
                "layer": "L0",
                "executable": False,
                "raw_motion_edge_ids": [],
                "place_edge_ids": [],
            }
            topology_edges_by_pair[pair] = relation
        relation["raw_motion_edge_ids"].append(raw_edge_id)
        relation["place_edge_ids"] = sorted(
            set(relation["place_edge_ids"])
            | {str(value) for value in raw_edge.get("place_edge_ids") or [] if str(value)}
        )
        raw_motion_edge_to_topology_edge_id[raw_edge_id] = str(relation["motion_edge_id"])

    l1_topology_edges: list[dict[str, Any]] = []
    if bool(cfg.get("l1_proximity_enabled", True)):
        candidates: list[tuple[float, str, str, tuple[str, ...]]] = []
        for index, source_id in enumerate(topology_node_ids):
            source_point = tuple(topology_nodes_by_id[source_id]["position"][:2])
            for target_id in topology_node_ids[index + 1:]:
                target_point = tuple(topology_nodes_by_id[target_id]["position"][:2])
                distance = _distance(source_point, target_point)
                if distance < topology_min_spacing_m - 1e-9 or distance > topology_max_distance_m + 1e-9:
                    continue
                if tuple(sorted((source_id, target_id))) in topology_edges_by_pair:
                    continue
                if not _world_segment_safe(effective_grid, source_point, target_point):
                    continue
                source_places = set(topology_nodes_by_id[source_id].get("place_edge_ids") or [])
                target_places = set(topology_nodes_by_id[target_id].get("place_edge_ids") or [])
                candidates.append((distance, source_id, target_id, tuple(sorted(source_places | target_places))))
        degree: dict[str, int] = defaultdict(int)
        for distance, source_id, target_id, place_edge_ids in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
            if topology_max_degree == 0 or degree[source_id] >= topology_max_degree or degree[target_id] >= topology_max_degree:
                continue
            topology_edge_id = f"support_topology_l1_{len(l1_topology_edges) + 1:05d}"
            l1_topology_edges.append({
                "topology_edge_id": topology_edge_id,
                "motion_edge_id": topology_edge_id,
                "source": source_id,
                "target": target_id,
                "distance_m": distance,
                "edge_type": "proximity_topology",
                "lane": "l1_proximity",
                "layer": "L1",
                "executable": False,
                "collision_free": True,
                "raw_motion_edge_ids": [],
                "place_edge_ids": list(place_edge_ids),
            })
            degree[source_id] += 1
            degree[target_id] += 1
    topology_edges = list(topology_edges_by_pair.values()) + l1_topology_edges
    support_topology = {
        "schema_version": "opticalnav.support_topology.v1",
        "min_node_spacing_m": topology_min_spacing_m,
        "max_l1_distance_m": topology_max_distance_m,
        "nodes": topology_nodes,
        "edges": topology_edges,
        "raw_pose_to_topology_id": raw_pose_to_topology_id,
        "raw_motion_edge_to_topology_edge_id": raw_motion_edge_to_topology_edge_id,
        "raw_pose_count": len(poses),
        "topology_node_count": len(topology_nodes),
        "collapsed_pose_count": len(poses) - len(topology_nodes),
        "l0_action_adjacency_edge_count": len(topology_edges_by_pair),
        "l1_proximity_edge_count": len(l1_topology_edges),
    }
    # Discover native action headings only after blueprint fallback corridors
    # have been materialised; every stored forward edge must therefore have an
    # exact source/target action state and a renderable heading.
    incoming: dict[str, set[str]] = defaultdict(set); outgoing: dict[str, set[str]] = defaultdict(set)
    structural_headings: dict[str, set[str]] = defaultdict(set)
    structural_neighbors: dict[str, set[str]] = defaultdict(set)
    portal_incident_pose_ids: set[str] = set()
    # A link/stitch chord joins two lanes that need not share a travel
    # direction, so its endpoints must be able to turn onto it. Without full
    # turn freedom a pose reached only through a link keeps a heading that no
    # arc connects to its lane heading, and the route splits directionally.
    link_incident_pose_ids: set[str] = set()
    lateral_switch_main_pose_ids: set[str] = set()
    for edge in edges.values():
        source_id, target_id = str(edge["source"]), str(edge["target"])
        source = poses[source_id]["position"]; target = poses[target_id]["position"]
        heading = _heading_id(_yaw_to(source, target), 24)
        edge["heading_id"] = heading; outgoing[source_id].add(heading); incoming[target_id].add(heading)
        if str(edge.get("edge_type") or "") in LINK_EDGE_TYPES or str(edge.get("lane") or "") in LINK_LANES:
            link_incident_pose_ids.update((source_id, target_id))
        if str(edge.get("lane") or "") == LATERAL_LANE:
            for pose_id in (source_id, target_id):
                if LATERAL_TAG not in (poses[pose_id].get("tags") or []):
                    lateral_switch_main_pose_ids.add(pose_id)
        else:
            structural_headings[source_id].add(heading); structural_headings[target_id].add(heading)
            structural_neighbors[source_id].add(target_id); structural_neighbors[target_id].add(source_id)
        if edge.get("portal_ids"):
            portal_incident_pose_ids.update((source_id, target_id))
    local_turn_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for sequence in path_sequences:
        for previous, current, following in zip(sequence, sequence[1:], sequence[2:]):
            prior_heading = _heading_id(_yaw_to(poses[previous]["position"], poses[current]["position"]), 24)
            next_heading = _heading_id(_yaw_to(poses[current]["position"], poses[following]["position"]), 24)
            if prior_heading != next_heading:
                local_turn_pairs[current].add((prior_heading, next_heading))
    # Full turn freedom (closure) is the dominant render cost, so it is granted
    # structurally: a pose whose executable degree is not 2 (terminal or
    # junction), portal poses, blueprint route endpoints and component roots.
    # A pass-through anchor keeps only the local arcs of its actual curvature.
    lateral_pose_ids = {pose_id for pose_id, pose in poses.items() if LATERAL_TAG in (pose.get("tags") or [])}
    if str(cfg["turn_freedom_policy"]) == "patch_tags":
        full_turn_pose_ids = {
            pose_id for pose_id, pose in poses.items()
            if {"patch", "junction", "portal"} & set(pose.get("tags") or [])
        }
    else:
        route_endpoint_pose_ids = {
            str(route["motion_pose_ids"][index])
            for route in blueprint_routes if route.get("motion_pose_ids")
            for index in (0, -1)
        }
        root_pose_ids = {
            pose_id for anchor_id in component_root_anchor_ids
            for pose_id in anchor_poses.get(str(anchor_id), set())
        }
        full_turn_pose_ids = (
            {pose_id for pose_id in poses if len(structural_neighbors.get(pose_id, set())) != 2}
            | portal_incident_pose_ids
            | {pose_id for pose_id, pose in poses.items() if "portal" in (pose.get("tags") or [])}
            | route_endpoint_pose_ids
            | root_pose_ids
        # A side-lane pose is normally kept cheap at its two travel headings,
        # but once a link lands on it that pose is a real junction: subtract
        # the band first, then restore every link endpoint.
        ) - lateral_pose_ids | link_incident_pose_ids
    turn_pairs_by_pose: dict[str, set[tuple[str, str]]] = {}
    state_rows: dict[tuple[str, str], dict[str, Any]] = {}
    pose_headings: dict[str, set[str]] = {}
    for pose_id, pose in poses.items():
        headings = set(outgoing.get(pose_id, set())) | set(incoming.get(pose_id, set()))
        if pose_id in full_turn_pose_ids:
            headings = _heading_closure(headings, str(cfg["turn_closure_policy"]))
            turn_pairs: set[tuple[str, str]] = set()
        else:
            # A recorded pair only reflects one travel direction through the
            # sequence it came from (an arriving heading immediately followed
            # by a departing one).  A robot must always be able to turn back
            # through the same arc it just turned through, so every pair is
            # made bidirectional here rather than depending on some other
            # sequence happening to also record the exact reverse pair.
            base_pairs = set(local_turn_pairs.get(pose_id, set())) | lateral_switch_turn_pairs.get(pose_id, set())
            turn_pairs = base_pairs | {(end, start) for start, end in base_pairs}
            for start, end in turn_pairs:
                headings.update(_heading_arc(start, end))
        turn_pairs_by_pose[pose_id] = turn_pairs
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
        if pose_id in full_turn_pose_ids:
            numbers = {int(value.split("_", 1)[1]) // 15 for value in headings}
            for number in sorted(numbers):
                for delta in (1, -1):
                    next_number = (number + delta) % 24
                    if next_number in numbers:
                        add_turn(_heading_id(number * 15.0, 24), _heading_id(next_number * 15.0, 24), pose_id)
        else:
            for start, end in sorted(turn_pairs_by_pose.get(pose_id, set())):
                for source_heading, target_heading in zip(_heading_arc(start, end), _heading_arc(start, end)[1:]):
                    add_turn(source_heading, target_heading, pose_id)
    report(
        "action_states", 0.74, action_state_count=len(state_rows), transition_count=len(transitions),
        full_turn_pose_count=len(full_turn_pose_ids), lateral_pose_count=len(lateral_pose_ids),
    )

    # Panorama context is reserved for poses with full turn freedom; a side
    # lane or a pass-through anchor never promotes to PANORAMA_12.
    if str(cfg["turn_freedom_policy"]) == "patch_tags":
        core_candidates = sorted(
            poses.values(), key=lambda pose: (
                not bool({"portal", "junction", "patch"} & set(pose.get("tags") or [])),
                str(pose["motion_node_id"]),
            )
        )
    else:
        core_candidates = sorted(
            (pose for pose_id, pose in poses.items() if pose_id in full_turn_pose_ids),
            key=lambda pose: (
                not bool({"portal", "junction"} & set(pose.get("tags") or [])),
                str(pose["motion_node_id"]),
            ),
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
    # Budget attribution of the band: every side-pose view plus the extra
    # switch arcs on main poses beyond their bare structural in/out headings.
    # This is a diagnostic estimate (it does not separate a switch arc from an
    # unrelated route turn that happens to land on the same pose).
    available_by_pose = {str(row["motion_node_id"]): set(row["available_heading_ids"]) for row in observation_poses}
    lateral_added_heading_count = sum(len(available_by_pose.get(pose_id, set())) for pose_id in lateral_pose_ids)
    for pose_id in lateral_switch_main_pose_ids:
        if pose_id in full_turn_pose_ids:
            continue
        baseline = set(structural_headings.get(pose_id, set()))
        lateral_added_heading_count += max(0, len(pose_headings.get(pose_id, set())) - len(baseline))
    lateral_diagnostics["lateral_pose_count"] = len(lateral_pose_ids)
    lateral_diagnostics["lateral_edge_count"] = sum(1 for edge in edges.values() if str(edge.get("lane") or "") == LATERAL_LANE)
    lateral_diagnostics["lateral_added_heading_count"] = lateral_added_heading_count
    lateral_diagnostics["full_turn_pose_count"] = len(full_turn_pose_ids)
    if int(cfg["max_polar_observations"]) > 0 and len(render_entries) > cfg["max_polar_observations"]:
        raise ValueError(f"support_polar_budget_exceeded:{len(render_entries)}/{cfg['max_polar_observations']}")
    if int(cfg["max_polar_batches"]) > 0 and batch_count > cfg["max_polar_batches"]:
        raise ValueError(f"support_batch_budget_exceeded:{batch_count}/{cfg['max_polar_batches']}")
    report("observation_plan", 0.90, polar_observation_count=len(render_entries), polar_batch_count=batch_count, panorama_pose_count=len(panorama_ids))

    digest = _support_digest(place_graph, blueprints, cfg)
    support_graph = {
        "schema_version": SCHEMA_VERSION, "profile_id": PROFILE_ID, "scene_id": place_graph.scene_id,
        "place_graph_id": place_graph.graph_id, "blueprint_digest": blueprints.get("blueprint_digest"), "profile_digest": digest,
        "heading_count": 24, "turn_deg": 15.0, "forward_step_m": cfg["forward_step_m"], "forward_tolerance_m": cfg["forward_tolerance_m"], "min_link_distance_m": cfg["min_link_distance_m"], "effective_clearance_m": cfg["effective_clearance_m"],
        "poses": list(poses.values()), "nodes": list(poses.values()), "edges": list(edges.values()), "states": list(state_rows.values()), "transitions": transitions,
        "anchor_pose_ids": {key: sorted(value) for key, value in anchor_poses.items()}, "blueprint_routes": blueprint_routes,
        "global_normalization": global_normalization,
        "topology": support_topology,
        "topology_edges": topology_edges,
        "trunk": {
            "place_edge_ids": sorted(required_edges),
            "canonical_backbone_edge_ids": sorted(backbone_edge_ids),
            # Independent reviewed corridors are valid execution islands. They
            # are deliberately not joined through a convenient-but-unowned
            # place edge; every Blueprint route is still validated as strongly
            # connected below.
            "allow_disconnected_review_components": True,
            "component_root_anchor_ids": component_root_anchor_ids,
            **trunk_meta,
        },
        "narrow_corridor_edge_ids": narrow_edges,
    }
    support_graph["support_algorithm_id"] = support_algorithm_id or "production_v1"
    if support_algorithm_id:
        support_graph["experimental"] = True
        support_graph["support_pipeline"] = {
            "algorithm_id": support_algorithm_id,
            "stages": [
                "raw_blueprint_induced_support",
                "global_support_consolidation",
                "global_executable_stitching",
            ],
        }
    # Corridors materialized on the reduced-margin relief domain are recorded on
    # the graph itself so validation, the daemon response and any later reader
    # can see exactly which lanes carry less than the configured safety margin.
    support_graph["relaxed_corridor_place_edge_ids"] = sorted(relaxed_corridor_edge_ids)
    validation = validate_navigation_support(support_graph, motion_grid=effective_grid)
    support_graph["validation"] = {**validation, "digest": digest}
    observation_plan = {
        "schema_version": SCHEMA_VERSION, "profile_id": PROFILE_ID, "scene_id": place_graph.scene_id,
        "place_graph_id": place_graph.graph_id, "support_graph_ref": SUPPORT_GRAPH_FILE, "profile_digest": digest,
        "validation_digest": digest, "heading_count": 24, "panoramic_heading_count": 12,
        "poses": observation_poses, "render_entries": render_entries, "config": cfg,
        "summary": {"support_pose_count": len(poses), "action_state_count": len(state_rows), "panorama_12_pose_count": len(panorama_ids), "polar_observation_count": len(render_entries), "polar_batch_count": batch_count, "gpu_time_estimate_hours_per_polar_camera_variant": len(render_entries) * cfg["heading_render_seconds"] / 3600.0},
    }
    observation_plan["support_algorithm_id"] = support_algorithm_id or "production_v1"
    support_graph["generation_diagnostics"] = {
        "restored_portals": restored_portals,
        "required_trunk_edge_count": len(required_edges),
        "canonical_backbone_edge_count": len(backbone_edge_ids),
        "canonical_centerline_edge_count": len(canonical_centerline_edges),
        "canonical_cycle_edge_count": len(canonical_cycle_edge_ids),
        "unmaterialized_canonical_cycle_edge_count": len(unmaterialized_canonical_cycle_edge_ids),
        "relaxed_corridor_edge_count": len(relaxed_corridor_edge_ids),
        "relaxed_corridor_place_edge_ids": sorted(relaxed_corridor_edge_ids),
        "unmaterializable_corridor_policy": cfg["unmaterializable_corridor_policy"],
        "narrow_corridor_edge_count": len(narrow_edges),
        "local_ribbon_place_edge_count": len(set(route_local_edge_ids)),
        "reused_canonical_blueprint_count": len(reused_canonical_blueprint_ids),
        "topology_node_count": len(topology_nodes),
        "topology_collapsed_pose_count": len(poses) - len(topology_nodes),
        "l0_topology_edge_count": len(topology_edges_by_pair),
        "l1_topology_edge_count": len(l1_topology_edges),
        "sub_min_raw_pose_spacing_pair_count": sub_min_spacing_pair_count,
        "blueprint_route_count": len(blueprint_routes),
        **base_attach_diagnostics,
        **lateral_diagnostics,
        **global_normalization,
        **trunk_meta,
        **observation_plan["summary"],
    }
    observation_plan["summary"]["lateral_pose_count"] = len(lateral_pose_ids)
    observation_plan["summary"]["lateral_added_heading_count"] = lateral_added_heading_count
    observation_plan["summary"]["full_turn_pose_count"] = len(full_turn_pose_ids)
    report("complete", 1.0, support_pose_count=len(poses), polar_observation_count=len(render_entries))
    return {"place_graph": place_graph, "route_blueprints": dict(blueprints), "support_graph": support_graph, "observation_plan": observation_plan, "generation_diagnostics": dict(support_graph["generation_diagnostics"])}


def analyze_navigation_support(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Dry-run alias; callers keep the returned payload in memory only."""
    return build_navigation_support(*args, **kwargs)


def _support_blocker_group(
    error: str,
    *,
    place_graph: ViewpointGraph,
    blueprints: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe the approvals which are sufficient to reproduce one failure.

    A v4 support plan materialises a shared canonical backbone before it checks
    individual blueprint directness.  Consequently one unsafe place edge can
    make several otherwise sensible routes fail together.  This helper turns a
    builder exception into a reviewer-facing *group*, rather than implying that
    every route in the group is independently invalid.
    """
    approved = [
        row for row in blueprints.get("blueprints") or []
        if isinstance(row, Mapping) and str(row.get("status") or "proposed") == "approved"
    ]

    def route_ids_for_edges(edge_ids: Iterable[str]) -> list[str]:
        wanted = {str(edge_id) for edge_id in edge_ids}
        return sorted(
            str(row.get("blueprint_id"))
            for row in approved
            if wanted & {str(edge_id) for edge_id in row.get("place_path_edge_ids") or []}
            and str(row.get("blueprint_id") or "")
        )

    if error.startswith("support_corridor_unreachable:"):
        edge_id = error.split(":", 1)[1]
        edge = next((item for item in place_graph.edges if str(item.edge_id) == edge_id), None)
        source = str(edge.source) if edge is not None else None
        target = str(edge.target) if edge is not None else None
        dependent_blueprints = route_ids_for_edges([edge_id])
        # The canonical support backbone can need a connector which no route
        # blueprint owns (normally an automatic ``vp_coverage_*`` endpoint).
        # That is a geometry/action-lattice failure, not a reviewer decision.
        coverage_backbone = any(str(node_id or "").startswith("vp_coverage_") for node_id in (source, target))
        structural_backbone = not dependent_blueprints
        ownership = (
            "automatic_coverage_backbone" if coverage_backbone
            else "shared_backbone_connector" if structural_backbone
            else "approved_route_corridor"
        )
        return {
            "kind": "support_corridor_unreachable",
            "place_edge_id": edge_id,
            "source": source,
            "target": target,
            "distance_m": float(edge.distance_m) if edge is not None else None,
            "collision_free": bool(edge.collision_free) if edge is not None else None,
            "edge_metadata": dict(edge.extras or {}) if edge is not None else {},
            "ownership": ownership,
            "structural_backbone": structural_backbone,
            "requires_place_graph_repair": structural_backbone,
            "blocked_blueprint_ids": dependent_blueprints,
            "message": (
                "The action lattice cannot materialize this structural support connector. "
                "No route blueprint owns this edge, so inspect or rebuild the Place Graph corridor on the canvas."
                if structural_backbone else
                "The action lattice cannot materialize this shared place corridor. "
                "The listed approved blueprints depend on it; inspect the corridor before "
                "returning any route to Proposed."
            ),
            "error": error,
        }
    if error.startswith("support_portal_not_open:"):
        portal_id = error.split(":", 1)[1]
        portal_edges = [
            str(edge.edge_id)
            for edge in place_graph.edges
            if str((edge.extras or {}).get("portal") or "") == portal_id
        ]
        return {
            "kind": "support_portal_not_open",
            "portal_id": portal_id,
            "place_edge_ids": portal_edges,
            "blocked_blueprint_ids": route_ids_for_edges(portal_edges),
            "message": "A required portal is closed. Open/certify the doorway or review only the routes that cross it.",
            "error": error,
        }
    if error.startswith("blueprint_support_unreachable:"):
        fragments = error.split(":", 2)
        blueprint_id = fragments[1] if len(fragments) > 1 else ""
        return {
            "kind": "blueprint_support_unreachable",
            "blocked_blueprint_ids": [blueprint_id] if blueprint_id else [],
            "message": "This approved blueprint is not represented by the executable support backbone.",
            "error": error,
        }
    if error.startswith("blueprint_directness_exceeded:"):
        fragments = error.split(":", 2)
        blueprint_id = fragments[1] if len(fragments) > 1 else ""
        return {
            "kind": "blueprint_directness_exceeded",
            "blocked_blueprint_ids": [blueprint_id] if blueprint_id else [],
            "message": "This route would require a support detour beyond the strict directness budget.",
            "error": error,
        }
    if error.startswith("support_route_component_disconnected:"):
        # ``validate_navigation_support`` reports the route that owns the
        # disconnected action-state component.  It is therefore a reviewable
        # route-local failure, not a global precondition.  Treating it as
        # global used to stop the dry-run scan after the first route and left
        # the UI with an unhelpful, ownerless "strict blocker" card.
        fragments = error.split(":", 1)
        blueprint_id = fragments[1] if len(fragments) > 1 else ""
        blueprint = next(
            (
                row for row in approved
                if str(row.get("blueprint_id") or "") == blueprint_id
            ),
            None,
        )
        return {
            "kind": "support_route_component_disconnected",
            "blueprint_id": blueprint_id or None,
            "source": str(blueprint.get("start_anchor_id") or "") if blueprint else None,
            "target": str(blueprint.get("goal_anchor_id") or "") if blueprint else None,
            "place_edge_ids": list(blueprint.get("place_path_edge_ids") or []) if blueprint else [],
            "blocked_blueprint_ids": [blueprint_id] if blueprint_id else [],
            "message": (
                "This approved route has action states that are not mutually reachable. "
                "Inspect its place path and doorway transitions, then repair the corridor or return only this route to Proposed."
            ),
            "error": error,
        }
    if error.startswith("support_route_missing_states:"):
        fragments = error.split(":", 1)
        blueprint_id = fragments[1] if len(fragments) > 1 else ""
        return {
            "kind": "support_route_missing_states",
            "blueprint_id": blueprint_id or None,
            "blocked_blueprint_ids": [blueprint_id] if blueprint_id else [],
            "message": "This approved route has no executable action states after support expansion.",
            "error": error,
        }
    return {
        "kind": "support_analysis_failed",
        "blocked_blueprint_ids": [],
        "message": "A global support precondition failed before a route-specific blocker could be isolated.",
        "error": error,
    }


def analyze_navigation_support_blockers(
    place_graph: ViewpointGraph,
    blueprints: Mapping[str, Any],
    *,
    annotation: SceneAnnotation | None,
    motion_grid: TraversabilityGrid,
    config: Mapping[str, Any] | None = None,
    on_progress: Callable[[str, float, Mapping[str, Any]], None] | None = None,
    normalizer: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Find every strict-build blocker without changing saved blueprint state.

    The support builder is deliberately fail-fast: a partially materialised
    action graph is unsafe to publish.  For review, we run that same strict
    builder against an in-memory copy, temporarily excluding only the group
    that reproduced each failure.  Repeating until the dry run succeeds gives
    the user all groups which actually prevent *this* plan from materialising,
    while preserving the original approvals and all good routes on disk.
    """
    working = deepcopy(dict(blueprints))
    initial_approved = [
        row for row in working.get("blueprints") or []
        if isinstance(row, Mapping) and str(row.get("status") or "proposed") == "approved"
    ]
    max_passes = max(1, len(initial_approved) + 1)
    blockers: list[dict[str, Any]] = []
    excluded_ids: set[str] = set()
    seen: set[tuple[str, str, tuple[str, ...]]] = set()

    for attempt in range(max_passes):
        active_count = sum(
            1 for row in working.get("blueprints") or []
            if isinstance(row, Mapping) and str(row.get("status") or "proposed") == "approved"
        )
        if active_count == 0:
            return {
                "ok": False,
                "complete": True,
                "blockers": blockers,
                "blocked_blueprint_ids": sorted(excluded_ids),
                "remaining_approved_count": 0,
                "buildable_after_exclusion": False,
                "message": "Every currently approved route belongs to a blocking group; repair a corridor before rebuilding support.",
            }
        if on_progress:
            on_progress(
                "support_blocker_scan",
                attempt / max(1, max_passes),
                {"pass": attempt + 1, "active_approved_route_count": active_count, "blocker_group_count": len(blockers)},
            )
        try:
            artifacts = build_navigation_support(
                place_graph,
                working,
                annotation=annotation,
                motion_grid=motion_grid,
                config=config,
                normalizer=normalizer,
            )
        except ValueError as exc:
            group = _support_blocker_group(
                str(exc), place_graph=place_graph, blueprints=working,
            )
            affected = sorted({str(item) for item in group.get("blocked_blueprint_ids") or [] if str(item)})
            fingerprint = (
                str(group.get("kind") or "support_analysis_failed"),
                str(group.get("place_edge_id") or group.get("portal_id") or group.get("error") or ""),
                tuple(affected),
            )
            if not affected or fingerprint in seen:
                group["id"] = f"blocker_{len(blockers) + 1:02d}"
                blockers.append(group)
                return {
                    "ok": False,
                    "complete": False,
                    "blockers": blockers,
                    "blocked_blueprint_ids": sorted(excluded_ids),
                    "remaining_approved_count": active_count,
                    "buildable_after_exclusion": False,
                    "message": "The blocker scan stopped at a global precondition that cannot be assigned safely to individual blueprints.",
                }
            seen.add(fingerprint)
            group["id"] = f"blocker_{len(blockers) + 1:02d}"
            group["blocked_blueprint_ids"] = affected
            blockers.append(group)
            excluded_ids.update(affected)
            for row in working.get("blueprints") or []:
                if isinstance(row, dict) and str(row.get("blueprint_id") or "") in excluded_ids:
                    row["status"] = "proposed"
            continue

        if on_progress:
            on_progress("support_blocker_scan", 1.0, {"blocker_group_count": len(blockers), "buildable": True})
        return {
            "ok": not blockers,
            "complete": True,
            "blockers": blockers,
            "blocked_blueprint_ids": sorted(excluded_ids),
            "remaining_approved_count": active_count,
            "buildable_after_exclusion": bool(blockers),
            "feasible_summary": artifacts["observation_plan"]["summary"],
            # This is intentionally private in-process data.  The daemon uses
            # it for a no-blocker Analyze response but never serialises it.
            "_artifacts": artifacts,
        }

    return {
        "ok": False,
        "complete": False,
        "blockers": blockers,
        "blocked_blueprint_ids": sorted(excluded_ids),
        "remaining_approved_count": sum(
            1 for row in working.get("blueprints") or []
            if isinstance(row, Mapping) and str(row.get("status") or "proposed") == "approved"
        ),
        "buildable_after_exclusion": False,
        "message": "The blocker scan reached its safe pass limit before the strict build converged.",
    }


def validate_navigation_support(graph: Mapping[str, Any], *, motion_grid: TraversabilityGrid | None = None) -> dict[str, Any]:
    if str(graph.get("profile_id") or "") != PROFILE_ID: raise ValueError("not an adaptive_navigation_support_v4 graph")
    poses = {str(item.get("motion_node_id")): item for item in graph.get("poses") or [] if isinstance(item, Mapping)}
    edges = {str(item.get("motion_edge_id")): item for item in graph.get("edges") or [] if isinstance(item, Mapping)}
    states = {str(item.get("motion_state_id")): item for item in graph.get("states") or [] if isinstance(item, Mapping)}
    if not poses or not edges or not states: raise ValueError("support graph is empty")
    support_config = dict(graph.get("config") or {})
    relaxed_place_edge_ids = {
        str(value) for value in graph.get("relaxed_corridor_place_edge_ids") or [] if str(value)
    }
    relaxed_forward_edge_ids: list[str] = []
    # The persisted v4 support graph keeps its executable action contract at
    # the top level. Retain the nested lookup as a forward-compatible fallback
    # for an early experimental artifact.
    forward_step_m = float(graph.get("forward_step_m") or support_config.get("forward_step_m") or 0.25)
    forward_tolerance_m = float(graph.get("forward_tolerance_m") or support_config.get("forward_tolerance_m") or 0.025)
    for edge_id, edge in edges.items():
        source, target = poses.get(str(edge.get("source"))), poses.get(str(edge.get("target")))
        if source is None or target is None: raise ValueError(f"support_edge_missing_pose:{edge_id}")
        distance = _distance(source["position"], target["position"])
        # A forward edge is any certified chord from the minimum link distance
        # up to one full action step; short links close gaps that a fixed-step
        # lattice cannot express.
        link_min = float(graph.get("min_link_distance_m") or support_config.get("min_link_distance_m") or 0.10)
        if not (link_min - 1e-9 <= distance <= forward_step_m + forward_tolerance_m + 1e-9):
            raise ValueError(f"support_non_normalized_forward:{edge_id}:{distance:.5f}")
        if motion_grid is not None and not _world_segment_safe(motion_grid, tuple(source["position"][:2]), tuple(target["position"][:2])):
            # A lane deliberately materialized on the reduced-margin relief
            # domain is not a validation failure: it fails the strict grid by
            # construction. Count it instead of aborting, so the reduced margin
            # stays visible rather than silently passing as a full-margin lane.
            if not (set(str(value) for value in edge.get("place_edge_ids") or []) & relaxed_place_edge_ids):
                raise ValueError(f"support_unsafe_forward:{edge_id}")
            relaxed_forward_edge_ids.append(edge_id)
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
    if len(forward_component) == len(states) and len(reverse_component) == len(states):
        strong_component_count = 1
    else:
        trunk = graph.get("trunk") if isinstance(graph.get("trunk"), Mapping) else {}
        if not bool(trunk.get("allow_disconnected_review_components", False)):
            raise ValueError(
                "support_action_backbone_disconnected:"
                f"forward={len(forward_component)}/{len(states)}:reverse={len(reverse_component)}/{len(states)}"
            )

        # The global support graph may contain separate reviewed corridors, but
        # each Blueprint must still be bidirectionally executable through every
        # action state it owns.  This is stricter than merely checking a weak
        # place-graph component and prevents an unowned coverage connector from
        # being the only thing that makes a route look valid.
        weak: dict[str, list[str]] = defaultdict(list)
        for source_id, targets in forward.items():
            for target_id in targets:
                weak[source_id].append(target_id)
                weak[target_id].append(source_id)
        remaining = set(states)
        strong_component_count = 0
        while remaining:
            strong_component_count += 1
            root = min(remaining)
            component = {root}
            pending = [root]
            while pending:
                current = pending.pop()
                for target_id in weak.get(current, []):
                    if target_id not in component:
                        component.add(target_id)
                        pending.append(target_id)
            remaining -= component

        states_by_pose: dict[str, set[str]] = defaultdict(set)
        for state_id, state in states.items():
            states_by_pose[str(state.get("motion_pose_id"))].add(state_id)
        for route in graph.get("blueprint_routes") or []:
            if not isinstance(route, Mapping):
                continue
            route_state_ids = {
                state_id
                for pose_id in route.get("motion_pose_ids") or []
                for state_id in states_by_pose.get(str(pose_id), set())
            }
            if not route_state_ids:
                raise ValueError(f"support_route_missing_states:{route.get('blueprint_id')}")
            root = min(route_state_ids)

            def route_reachable(adjacency: Mapping[str, Sequence[str]]) -> set[str]:
                found = {root}; pending = [root]
                while pending:
                    current = pending.pop()
                    for target_id in adjacency.get(current, []):
                        if target_id not in found:
                            found.add(target_id)
                            pending.append(target_id)
                return found

            if not route_state_ids <= route_reachable(forward) or not route_state_ids <= route_reachable(reverse):
                raise ValueError(f"support_route_component_disconnected:{route.get('blueprint_id')}")
    return {
        "ok": True,
        "pose_count": len(poses),
        "edge_count": len(edges),
        "state_count": len(states),
        "transition_count": len(graph.get("transitions") or []),
        "strong_component_count": strong_component_count,
        # Forward lanes that clear the robot body but not the configured safety
        # margin, because their place corridor was materialized under the
        # "relief" policy. Empty on every strict build.
        "reduced_margin_forward_edge_count": len(relaxed_forward_edge_ids),
        "reduced_margin_place_edge_ids": sorted(relaxed_place_edge_ids),
    }


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


SWEEP_COVERAGE_FILE_PREFIX = "support_sweep_coverage_"


def sweep_coverage_filename(level_id: str) -> str:
    return f"{SWEEP_COVERAGE_FILE_PREFIX}{level_id}.json"


def write_sweep_coverage_selection(scene_dir: str | Path, payload: Mapping[str, Any]) -> Path:
    level_id = str(payload.get("level_id") or "")
    if level_id not in SWEEP_COVERAGE_LEVEL_IDS:
        raise ValueError(f"level_id must be one of {SWEEP_COVERAGE_LEVEL_IDS}")
    return _atomic_json(Path(scene_dir) / sweep_coverage_filename(level_id), payload)


def list_sweep_coverage_levels(
    scene_dir: str | Path,
    *,
    base_plan: Mapping[str, Any] | None = None,
    episode_digest: str = "",
) -> dict[str, Any]:
    """List the sweep coverage rungs and which of them this build already has.

    Replaces the L0-L6 context ladder as the selectable coverage axis: each
    rung here is a growing subset of the same L0 plan rather than extra
    context on top of it, so the cheapest rung already yields a usable
    dataset.
    """
    root = Path(scene_dir)
    if base_plan is None:
        base_path = root / OBSERVATION_PLAN_FILE
        base_plan = read_support_observation_plan(base_path) if base_path.is_file() else None
    base_digest = str((base_plan or {}).get("profile_digest") or "")
    levels: list[dict[str, Any]] = []
    for level in SWEEP_COVERAGE_LEVELS:
        level_id = str(level["level_id"])
        path = root / sweep_coverage_filename(level_id)
        selection: dict[str, Any] | None = None
        if path.is_file():
            payload = _read_json_mapping(path)
            if payload is not None:
                selection = payload
        digest_ok = bool(selection and str(selection.get("profile_digest") or "") == base_digest)
        # A rung prepared from a different episode set is not current even when
        # its support digest still matches.
        episode_ok = bool(selection and str(selection.get("episode_digest") or "") == episode_digest)
        levels.append({
            **level,
            "plan_ref": path.name,
            "prepared": bool(selection),
            "current": digest_ok and episode_ok,
            "stale_reason": (
                "" if not selection or (digest_ok and episode_ok)
                else "support_rebuilt" if not digest_ok else "episodes_changed"
            ),
            "summary": dict((selection or {}).get("summary") or {}),
        })
    return {
        "base_profile_digest": base_digest,
        "episode_digest": episode_digest,
        "levels": levels,
        "ladder": "sweep_coverage",
    }


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


def validate_support_episode(
    episode: EpisodeManifest,
    *,
    forward_step_m: float | None = None,
    forward_tolerance_m: float | None = None,
) -> dict[str, int | float]:
    """Validate the executable 15-degree support-step contract of one v4 episode.

    The action at timestep *i* owns the transition from pose *i* to pose
    *i + 1*.  Checking this again at episode publication closes the gap between
    support-graph validation and a persisted dataset artifact.
    """
    if episode.navigation_mode != PROFILE_ID:
        raise ValueError(f"not a {PROFILE_ID} episode: {episode.episode_id}")
    episode_config = dict(episode.metadata or {})
    step_m = float(forward_step_m if forward_step_m is not None else episode_config.get("forward_step_m") or 0.25)
    tolerance_m = float(forward_tolerance_m if forward_tolerance_m is not None else episode_config.get("forward_tolerance_m") or 0.025)
    steps = list(episode.timesteps)
    if len(steps) < 2 or steps[-1].action != "stop":
        raise ValueError(f"support_episode_missing_terminal_stop:{episode.episode_id}")
    forward_count = 0
    for index, (current, following) in enumerate(zip(steps, steps[1:])):
        dx = float(following.agent_pose[0]) - float(current.agent_pose[0])
        dy = float(following.agent_pose[1]) - float(current.agent_pose[1])
        distance = math.hypot(dx, dy)
        if current.action == "move_forward":
            forward_count += 1
            link_min = float(episode_config.get("min_link_distance_m") or 0.10)
            if not (link_min - 1e-9 <= distance <= step_m + tolerance_m + 1e-9):
                raise ValueError(
                    "support_episode_non_normalized_forward:"
                    f"{episode.episode_id}:t={index}:distance_m={distance:.6f}"
                )
        elif current.action in {"turn_left", "turn_right"} and distance > 1e-6:
            raise ValueError(
                "support_episode_turn_translates:"
                f"{episode.episode_id}:t={index}:distance_m={distance:.6f}"
            )
    if forward_count == 0:
        raise ValueError(f"support_episode_has_no_forward_action:{episode.episode_id}")
    return {
        "forward_action_count": forward_count,
        "forward_step_m": step_m,
        "forward_tolerance_m": tolerance_m,
    }


def _support_forward_adjacency(
    transitions: Mapping[str, Mapping[str, Any]], allowed_transition_ids: Iterable[str] | None = None,
) -> dict[str, list[tuple[str, str, int, float]]]:
    """(target_state_id, transition_id, hop_cost, distance_m) for every move_forward/turn transition.

    ``hop_cost`` is 1 for ``move_forward`` -- the unit the episode's
    min/max-forward-action range counts -- and 0 for a turn, since a robot can
    always turn in place before its next forward step.  A pure move_forward
    graph cannot reach a lateral-band pose at all: the switch chord onto it
    sits at a different heading than the corridor's own travel heading, so
    the turn that reaches that heading has to be part of the search too.
    ``distance_m`` is the transition's own travel distance (0.0 for a turn)
    so callers can also bound episodes by physical length, not just action
    count.
    """
    adjacency: dict[str, list[tuple[str, str, int, float]]] = defaultdict(list)
    ids = transitions if allowed_transition_ids is None else allowed_transition_ids
    for transition_id in ids:
        transition = transitions.get(str(transition_id))
        if transition is None:
            continue
        action = transition.get("action")
        if action == "move_forward":
            cost = 1
            distance = float(transition.get("distance_m") or 0.0)
        elif action in ("turn_left", "turn_right"):
            cost = 0
            distance = 0.0
        else:
            continue
        adjacency[str(transition["source_state_id"])].append((str(transition["target_state_id"]), str(transition_id), cost, distance))
    return adjacency


def _bfs_forward_pairs(
    adjacency: Mapping[str, Sequence[tuple[str, str, int, float]]], start: str, *, min_hops: int, max_hops: int,
) -> list[tuple[str, int, float]]:
    """States reachable from ``start`` by 1..``max_hops`` move_forward hops.

    0-1 BFS: a turn transition costs 0 move_forward-hops, a move_forward
    transition costs 1.  Only states whose move_forward hop count lands in
    ``[min_hops, max_hops]`` are returned as candidates; states reached
    entirely by turning (0 hops) are walked but never counted -- a start and
    goal facing different headings at the same pose is not a move episode.
    Each result also carries the physical travel distance accumulated along
    that shortest-hop path, for callers that additionally bound episodes by
    length.
    """
    best: dict[str, int] = {start: 0}
    best_distance: dict[str, float] = {start: 0.0}
    queue: deque[str] = deque([start])
    seen_as_result: set[str] = set()
    results: list[tuple[str, int, float]] = []
    while queue:
        state_id = queue.popleft()
        depth = best[state_id]
        if depth >= max_hops:
            continue
        for target, _transition_id, cost, distance in adjacency.get(state_id, []):
            next_depth = depth + cost
            if next_depth > max_hops or (target in best and best[target] <= next_depth):
                continue
            best[target] = next_depth
            best_distance[target] = best_distance[state_id] + distance
            if cost == 0:
                queue.appendleft(target)
            else:
                queue.append(target)
            if min_hops <= next_depth <= max_hops and target not in seen_as_result:
                seen_as_result.add(target)
                results.append((target, next_depth, best_distance[target]))
    return results


ROUTE_SCOPES = ("blueprint", "blueprint_band", "global")


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
    excluded_signatures: set[str] | None = None,
    route_scope: str = "blueprint",
    min_distance_m: float | None = None,
    max_distance_m: float | None = None,
    motion_grid: TraversabilityGrid | None = None,
    max_detour_ratio: float | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[EpisodeManifest]:
    """Sample balanced, executable support-state episodes without new renders.

    A support graph deliberately contains many short action states.  Treating
    every adjacent pair as a training episode would inflate a split with trivial
    one-step examples and let the longest blueprint dominate.  The default
    range therefore keeps episodes in the 1--12 m movement band and samples
    candidate subpaths round-robin across approved blueprints.

    ``max_detour_ratio`` rejects an episode that walks much further than the
    scene's own free space requires. The support graph is only dense along
    approved corridors, so a start/goal pair whose direct route was never
    materialised is answered with a long way round; comparing the walked
    distance against the shortest path on the same clearance-eroded motion
    grid is what distinguishes that from a legitimate detour around a wall.
    It needs ``motion_grid``.

    ``min_forward_actions``/``max_forward_actions`` bound episodes by action
    count. ``min_distance_m``/``max_distance_m`` additionally (optionally)
    bound them by actual travelled distance -- the sum of each traversed
    forward transition's own ``distance_m``, not an estimate from
    ``forward_step_m`` -- which is what actually guarantees a minimum
    physical episode length regardless of per-step tolerance.

    ``route_scope`` controls which part of the executable graph episodes may
    use:

    - ``"blueprint"`` (default): only a blueprint's own certified corridor, as
      an ordered subpath -- unchanged from the original behaviour.
    - ``"blueprint_band"``: a blueprint's corridor plus the lateral-band poses
      grown alongside it (``edges[*].band_parent_motion_edge_ids`` intersects
      the route), so an episode may step onto a side lane and back.
    - ``"global"``: any start/goal pair reachable through the whole executable
      transition graph, bucketed round-robin by each start's owning
      blueprint(s) so no single corridor dominates.
    """
    from .rollout import scale_split_counts, split_for_index
    from .scene_dataset import episode_signature
    if str(support_graph.get("profile_id") or "") != PROFILE_ID or str(observation_plan.get("profile_id") or "") != PROFILE_ID: raise ValueError("support sidecar profile mismatch")
    if str(support_graph.get("profile_digest") or "") != str(observation_plan.get("profile_digest") or ""): raise ValueError("support observation digest mismatch")
    if route_scope not in ROUTE_SCOPES:
        raise ValueError(f"route_scope must be one of {ROUTE_SCOPES}")
    poses = {str(item["motion_node_id"]): item for item in support_graph.get("poses") or [] if isinstance(item, Mapping)}
    states = {str(item["motion_state_id"]): item for item in support_graph.get("states") or [] if isinstance(item, Mapping)}
    transitions = {str(item["transition_id"]): item for item in support_graph.get("transitions") or [] if isinstance(item, Mapping)}
    edges = {str(item["motion_edge_id"]): item for item in support_graph.get("edges") or [] if isinstance(item, Mapping)}
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
    if min_distance_m is not None and min_distance_m < 0:
        raise ValueError("min_distance_m must be >= 0")
    if max_distance_m is not None and (min_distance_m or 0.0) > max_distance_m:
        raise ValueError("max_distance_m must be >= min_distance_m")
    if max_detour_ratio is not None:
        if max_detour_ratio < 1.0:
            raise ValueError("max_detour_ratio must be >= 1.0")
        if motion_grid is None:
            raise ValueError("max_detour_ratio needs motion_grid to measure free-space distance")

    free_space_cache: dict[tuple[int, int], dict[tuple[int, int], float]] = {}

    def free_space_distance(goal: Sequence[float], start: Sequence[float]) -> float | None:
        """Shortest collision-free distance between two poses, in metres.

        An 8-connected Dijkstra over the same eroded grid the lanes were
        certified on. The field is cached per goal cell and each search stops
        as soon as the start cell is settled, so many candidates sharing a
        goal cost one partial sweep.
        """
        assert motion_grid is not None
        traversable = motion_grid.traversable
        height, width = traversable.shape
        resolution = float(motion_grid.spec.resolution)
        goal_cell = _nearest_safe_cell(motion_grid, (float(goal[0]), float(goal[1])))
        start_cell = _nearest_safe_cell(motion_grid, (float(start[0]), float(start[1])))
        if goal_cell is None or start_cell is None:
            return None
        field = free_space_cache.setdefault(goal_cell, {goal_cell: 0.0})
        if start_cell in field:
            return field[start_cell]
        queue: list[tuple[float, tuple[int, int]]] = [(cost, cell) for cell, cost in field.items()]
        heapq.heapify(queue)
        while queue:
            cost, cell = heapq.heappop(queue)
            if cost > field.get(cell, math.inf) + 1e-9:
                continue
            if cell == start_cell:
                return cost
            x, y = cell
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < width and 0 <= ny < height) or not bool(traversable[ny, nx]):
                    continue
                step = resolution * (math.sqrt(2.0) if dx and dy else 1.0)
                if cost + step + 1e-9 < field.get((nx, ny), math.inf):
                    field[(nx, ny)] = cost + step
                    heapq.heappush(queue, (cost + step, (nx, ny)))
        return None
    candidates_by_blueprint: dict[str, list[tuple[str, str, str, set[str]]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    if route_scope in ("blueprint", "blueprint_band"):
        for route in support_graph.get("blueprint_routes") or []:
            if not isinstance(route, Mapping):
                continue
            route_edge_ids = [str(value) for value in route.get("motion_edge_ids") or []]
            route_pose_ids = {str(value) for value in route.get("motion_pose_ids") or []}
            if not route_edge_ids or len(route_pose_ids) < 2:
                continue
            blueprint_id = str(route.get("blueprint_id") or "")
            allowed_motion_edges = set(route_edge_ids)
            allowed_pose_ids = set(route_pose_ids)
            if route_scope == "blueprint_band":
                for edge_id, edge in edges.items():
                    parents = {str(value) for value in edge.get("band_parent_motion_edge_ids") or []}
                    if parents & allowed_motion_edges:
                        allowed_motion_edges.add(edge_id)
                        allowed_pose_ids.add(str(edge.get("source")))
                        allowed_pose_ids.add(str(edge.get("target")))
            allowed_transition_ids = {
                transition_id
                for transition_id, transition in transitions.items()
                if (
                    transition.get("action") == "move_forward"
                    and str(transition.get("motion_edge_id")) in allowed_motion_edges
                ) or (
                    transition.get("action") in {"turn_left", "turn_right"}
                    and str(states[str(transition["source_state_id"])]["motion_pose_id"]) in allowed_pose_ids
                    and str(states[str(transition["target_state_id"])]["motion_pose_id"]) in allowed_pose_ids
                )
            }
            forward_transitions = [forward_by_motion_edge.get(edge_id) for edge_id in route_edge_ids]
            if any(value is None for value in forward_transitions):
                raise ValueError(f"support_route_transition_missing:{route.get('blueprint_id')}")
            if route_scope == "blueprint":
                # Every contiguous subpath is a unique route-pair candidate. It
                # lets a small number of approved long blueprints yield many
                # train/test episodes without synthesising unsupported global
                # start/goal pairs.
                cumulative_distance_m = [0.0]
                for transition in forward_transitions:
                    cumulative_distance_m.append(cumulative_distance_m[-1] + float(transition.get("distance_m") or 0.0))
                for start_index in range(len(route_edge_ids)):
                    for end_index in range(start_index + 1, len(route_edge_ids) + 1):
                        forward_count = end_index - start_index
                        if not min_forward_actions <= forward_count <= max_forward_actions:
                            continue
                        segment_distance_m = cumulative_distance_m[end_index] - cumulative_distance_m[start_index]
                        if min_distance_m is not None and segment_distance_m < min_distance_m:
                            continue
                        if max_distance_m is not None and segment_distance_m > max_distance_m:
                            continue
                        forward_source = str(forward_transitions[start_index]["source_state_id"])
                        forward_goal = str(forward_transitions[end_index - 1]["target_state_id"])
                        if forward_source == forward_goal or (forward_source, forward_goal) in seen_pairs:
                            continue
                        seen_pairs.add((forward_source, forward_goal))
                        candidates_by_blueprint[blueprint_id].append(
                            (blueprint_id, forward_source, forward_goal, allowed_transition_ids)
                        )
            else:
                # The band is no longer a single line, so contiguous index
                # ranges no longer enumerate every reachable pair: walk the
                # route+band forward graph from every route state instead.
                band_adjacency = _support_forward_adjacency(transitions, allowed_transition_ids)
                for transition in forward_transitions:
                    start_state = str(transition["source_state_id"])
                    for goal_state, _hops, path_distance_m in _bfs_forward_pairs(
                        band_adjacency, start_state, min_hops=min_forward_actions, max_hops=max_forward_actions,
                    ):
                        if start_state == goal_state or (start_state, goal_state) in seen_pairs:
                            continue
                        if min_distance_m is not None and path_distance_m < min_distance_m:
                            continue
                        if max_distance_m is not None and path_distance_m > max_distance_m:
                            continue
                        seen_pairs.add((start_state, goal_state))
                        candidates_by_blueprint[blueprint_id].append(
                            (blueprint_id, start_state, goal_state, allowed_transition_ids)
                        )
    else:
        # No per-blueprint corridor restriction: any start/goal pair reachable
        # through the whole executable transition graph.  Bucketing by each
        # start's owning blueprint(s) keeps the round-robin selection below
        # from letting one dense corridor dominate the sample.
        all_transition_ids = set(transitions)
        global_adjacency = _support_forward_adjacency(transitions)
        forward_sources = sorted({
            str(transition["source_state_id"])
            for transition in transitions.values()
            if transition.get("action") == "move_forward"
        })
        for start_state in forward_sources:
            pose_id = str(states[start_state]["motion_pose_id"])
            owners = sorted(poses.get(pose_id, {}).get("blueprint_ids") or []) or ["unowned"]
            bucket = owners[0]
            for goal_state, _hops, path_distance_m in _bfs_forward_pairs(
                global_adjacency, start_state, min_hops=min_forward_actions, max_hops=max_forward_actions,
            ):
                if start_state == goal_state or (start_state, goal_state) in seen_pairs:
                    continue
                if min_distance_m is not None and path_distance_m < min_distance_m:
                    continue
                if max_distance_m is not None and path_distance_m > max_distance_m:
                    continue
                seen_pairs.add((start_state, goal_state))
                candidates_by_blueprint[bucket].append(("global", start_state, goal_state, all_transition_ids))
    if not candidates_by_blueprint:
        distance_note = f", distance {min_distance_m}..{max_distance_m} m" if (min_distance_m, max_distance_m) != (None, None) else ""
        raise ValueError(
            "support graph has no executable approved blueprint pairs in the "
            f"{min_forward_actions}..{max_forward_actions} forward-action range{distance_note}"
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
    excluded_signatures = excluded_signatures or set()
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
        path_distance_m = sum(
            float(transitions[transition_id].get("distance_m") or 0.0)
            for transition_id in transition_ids
            if transitions[transition_id].get("action") == "move_forward"
        )
        free_space_m: float | None = None
        detour_ratio: float | None = None
        if max_detour_ratio is not None:
            free_space_m = free_space_distance(final, trajectory[0])
            if free_space_m is None or free_space_m <= 1e-6:
                continue
            detour_ratio = path_distance_m / free_space_m
            if detour_ratio > max_detour_ratio + 1e-9:
                continue
        derived_from_blueprints: set[str] = set()
        lateral_state_count = 0
        for state_id in state_ids:
            state_pose = poses.get(str(states[state_id]["motion_pose_id"]), {})
            derived_from_blueprints.update(str(value) for value in state_pose.get("blueprint_ids") or [])
            if LATERAL_TAG in (state_pose.get("tags") or []):
                lateral_state_count += 1
        for transition_id in transition_ids:
            edge_id = transitions[transition_id].get("motion_edge_id")
            if edge_id is not None:
                derived_from_blueprints.update(str(value) for value in edges.get(str(edge_id), {}).get("source_blueprint_ids") or [])
        if not derived_from_blueprints and blueprint_id not in ("", "global"):
            derived_from_blueprints.add(blueprint_id)
        split = split_for_index(split_spec, len(episodes))
        candidate = EpisodeManifest(
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
                "forward_step_m": float(support_graph.get("forward_step_m") or (support_graph.get("config") or {}).get("forward_step_m") or 0.25),
                "forward_tolerance_m": float(support_graph.get("forward_tolerance_m") or (support_graph.get("config") or {}).get("forward_tolerance_m") or 0.025),
                "min_link_distance_m": float(support_graph.get("min_link_distance_m") or (support_graph.get("config") or {}).get("min_link_distance_m") or 0.10),
                "support_graph_ref": SUPPORT_GRAPH_FILE,
                "observation_plan_ref": OBSERVATION_PLAN_FILE,
                "modalities": list(modalities or []),
                "blueprint_id": blueprint_id,
                "route_scope": route_scope,
                "derived_from_blueprints": sorted(derived_from_blueprints),
                "lateral_state_count": lateral_state_count,
                "path_distance_m": round(path_distance_m, 4),
                "free_space_distance_m": round(free_space_m, 4) if free_space_m is not None else None,
                "detour_ratio": round(detour_ratio, 4) if detour_ratio is not None else None,
                "pair_signature": _json_digest({
                    "route_scope": route_scope,
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
        )
        if episode_signature(candidate) in excluded_signatures:
            continue
        episodes.append(candidate)
        if on_progress is not None:
            on_progress(len(episodes), num_pairs)
    if len(episodes) < num_pairs:
        raise ValueError(
            f"support graph could only sample {len(episodes)}/{num_pairs} connected unique episodes "
            f"in the {min_forward_actions}..{max_forward_actions} forward-action range"
        )
    for episode in episodes:
        validate_support_episode(episode)
    return episodes


def write_support_episodes(paths: Any, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    rows = list(episodes)
    for episode in rows:
        validate_support_episode(episode)
    return [paths.write_episode(episode) for episode in rows]
