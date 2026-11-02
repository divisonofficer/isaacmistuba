from __future__ import annotations

from collections import defaultdict

import numpy as np
import pytest

from navigation_dataset.navigation_support import DEFAULT_CONFIG
from navigation_dataset.support_network_lab import (
    ALGORITHM_ID,
    GlobalExecutableNetworkNormalizer,
    compare_support_metrics,
    support_graph_metrics,
)
from navigation_dataset.traversability import GridSpec, TraversabilityGrid


def _grid() -> TraversabilityGrid:
    spec = GridSpec(
        origin=[-2.0, -2.0], resolution=0.025, width=200, height=200,
        scene_id="support_network_lab",
    )
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    return TraversabilityGrid(
        spec=spec,
        traversable=traversable,
        hazard=np.zeros_like(traversable),
    )


def _pose(pose_id: str, x: float, y: float) -> dict:
    return {
        "motion_node_id": pose_id,
        "motion_pose_id": pose_id,
        "position": [x, y, 0.0],
        "tags": [],
        "anchor_node_ids": [],
    }


def _edge(edge_id: str, source: str, target: str, place_edge: str) -> dict:
    return {
        "motion_edge_id": edge_id,
        "source": source,
        "target": target,
        "distance_m": 0.25,
        "action": "move_forward",
        "edge_type": "lane_forward",
        "lane": "test",
        "place_edge_ids": [place_edge],
        "portal_ids": [],
        "collision_free": True,
    }


def _config(**overrides: object) -> dict:
    return {
        **DEFAULT_CONFIG,
        "global_stitch_heading_tolerance_deg": 7.5,
        **overrides,
    }


def _normalize(
    poses: dict[str, dict],
    edges: dict[str, dict],
    owners: dict[str, set[str]],
) -> tuple[GlobalExecutableNetworkNormalizer, dict]:
    normalizer = GlobalExecutableNetworkNormalizer()
    diagnostics = normalizer(
        poses,
        edges,
        defaultdict(set),
        [],
        motion_grid=_grid(),
        config=_config(),
        blueprint_ids_by_place_edge=owners,
    )
    return normalizer, diagnostics


def test_v2_consolidates_parallel_phases_atomically() -> None:
    poses = {
        "a0": _pose("a0", 0.0, 0.0),
        "a1": _pose("a1", 0.25, 0.0),
        "b0": _pose("b0", 0.05, 0.0),
        "b1": _pose("b1", 0.30, 0.0),
    }
    edges = {
        "af": _edge("af", "a0", "a1", "place_a"),
        "ar": _edge("ar", "a1", "a0", "place_a"),
        "bf": _edge("bf", "b0", "b1", "place_b"),
        "br": _edge("br", "b1", "b0", "place_b"),
    }
    normalizer, diagnostics = _normalize(
        poses, edges, {"place_a": {"bp_a"}, "place_b": {"bp_b"}},
    )

    assert diagnostics["algorithm_id"] == ALGORITHM_ID
    assert diagnostics["hard_merged_pose_count"] == 2
    assert len(poses) == 2
    assert all(len(pose["source_motion_pose_ids"]) == 2 for pose in poses.values())
    assert normalizer.raw_support["stage"] == "raw_blueprint_induced_support"
    assert normalizer.consolidated_support["stage"] == "global_support_consolidation"
    assert normalizer.executable_support["stage"] == "global_executable_stitching"


def test_v2_splits_transitive_cluster_without_discarding_valid_pair() -> None:
    poses = {
        "a0": _pose("a0", 0.0, 0.0), "a1": _pose("a1", 0.25, 0.0),
        "b0": _pose("b0", 0.09, 0.0), "b1": _pose("b1", 0.34, 0.0),
        "c0": _pose("c0", 0.18, 0.0), "c1": _pose("c1", 0.43, 0.0),
    }
    edges = {}
    for prefix, place in (("a", "place_a"), ("b", "place_b"), ("c", "place_c")):
        edges[f"{prefix}f"] = _edge(f"{prefix}f", f"{prefix}0", f"{prefix}1", place)
        edges[f"{prefix}r"] = _edge(f"{prefix}r", f"{prefix}1", f"{prefix}0", place)

    _normalizer, diagnostics = _normalize(
        poses, edges,
        {"place_a": {"bp_a"}, "place_b": {"bp_b"}, "place_c": {"bp_c"}},
    )

    assert diagnostics["hard_merged_pose_count"] >= 2
    assert len(poses) <= 4
    assert diagnostics["soft_cluster_count"] >= 1


def test_v2_stitches_same_provenance_nodes_and_builds_cycles() -> None:
    poses = {
        "a0": _pose("a0", 0.0, 0.0), "a1": _pose("a1", 0.0, 0.25),
        "b0": _pose("b0", 0.25, 0.0), "b1": _pose("b1", 0.25, 0.25),
    }
    edges = {
        "af": _edge("af", "a0", "a1", "place_a"),
        "ar": _edge("ar", "a1", "a0", "place_a"),
        "bf": _edge("bf", "b0", "b1", "place_a"),
        "br": _edge("br", "b1", "b0", "place_a"),
    }
    _normalizer, diagnostics = _normalize(poses, edges, {"place_a": {"bp_same"}})
    stitches = [edge for edge in edges.values() if edge["edge_type"] == "cross_blueprint_stitch"]

    assert diagnostics["cross_blueprint_stitch_pair_count"] == 2
    assert len(stitches) == 4
    assert all(edge["source_blueprint_ids"] == ["bp_same"] for edge in stitches)
    metrics = support_graph_metrics({"poses": list(poses.values()), "edges": list(edges.values())})
    assert metrics["connected_component_count"] == 1
    assert metrics["cycle_rank"] == 1
    assert metrics["random_pair_alternative_ratio"] > 0


def test_metric_comparison_enforces_hard_contract_before_network_gain() -> None:
    baseline = {
        "connected_component_count": 2, "reachable_approved_blueprint_count": 3,
        "action_length_violation_count": 0, "collision_violation_count": 0,
        "residual_sub_015_pair_count": 10, "degree_one_node_count": 8,
        "junction_node_count": 2, "cycle_rank": 0, "random_pair_alternative_ratio": 0.0,
    }
    candidate = {
        **baseline,
        "connected_component_count": 1,
        "residual_sub_015_pair_count": 4,
        "junction_node_count": 6,
        "cycle_rank": 3,
    }
    comparison = compare_support_metrics(baseline, candidate)
    assert comparison["hard_validation_passed"] is True
    assert comparison["network_improved"] is True
    assert comparison["candidate_gate_passed"] is True

    invalid = {**candidate, "action_length_violation_count": 1}
    assert compare_support_metrics(baseline, invalid)["candidate_gate_passed"] is False
