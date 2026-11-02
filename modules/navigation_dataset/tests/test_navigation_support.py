from __future__ import annotations

from collections import defaultdict
import json
import math

import numpy as np
import pytest

from navigation_dataset.episode_schema import episode_from_payload, episode_to_payload
from navigation_dataset.navigation_support import (
    BLUEPRINTS_FILE,
    DEFAULT_CONFIG,
    OBSERVATION_PLAN_FILE,
    PLACE_GRAPH_FILE,
    PROFILE_ID,
    RENDER_GRAPH_FILE,
    SUPPORT_ARCHIVE_DIR,
    SUPPORT_GRAPH_FILE,
    add_route_blueprint,
    analyze_navigation_support_blockers,
    archive_navigation_support,
    build_support_observation_expansion,
    SWEEP_COVERAGE_LEVEL_IDS,
    select_sweep_coverage,
    build_navigation_support,
    delete_route_blueprint,
    latest_support_render_archive,
    plan_support_episodes,
    propose_route_blueprints,
    reconcile_route_blueprints_after_place_graph_edit,
    read_route_blueprints,
    read_support_observation_plan,
    recover_l0_observation_plan_from_expansion,
    support_observation_expansion_filename,
    update_route_blueprint,
    validate_support_episode,
    validate_navigation_support,
    _support_blocker_group,
    _normalize_global_support_graph,
    write_navigation_support,
    write_support_observation_expansion,
    _major_trunk_edges,
)
from navigation_dataset.traversability import GridSpec, TraversabilityGrid, world_to_cell
from navigation_dataset.viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointHeading, ViewpointNode
from navigation_dataset.route_motion import _v3_portal_aware_grid
from navigation_dataset.support_network_lab import ALGORITHM_ID, GlobalExecutableNetworkNormalizer


def _node(node_id: str, x: float, y: float) -> ViewpointNode:
    return ViewpointNode(
        node_id=node_id,
        position=[x, y, 0.0],
        headings=[ViewpointHeading(f"h_{index * 30:03d}", index * 30.0) for index in range(12)],
    )


def _edge(edge_id: str, source: str, target: str, distance: float) -> ViewpointEdge:
    return ViewpointEdge(
        edge_id=edge_id,
        source=source,
        target=target,
        distance_m=distance,
        weight=distance,
        collision_free=True,
        extras={"edge_validation": {"mode": "normal", "wall_run_cells": 0}},
    )


def _place_graph() -> ViewpointGraph:
    # The cross has two equally short A→D paths.  The test asserts v4 uses the
    # approved A-B-D corridor, rather than reconstituting a root-tree detour.
    nodes = [
        _node("a", 0.0, 0.0),
        _node("b", 1.0, 0.0),
        _node("c", 0.0, 1.0),
        _node("d", 1.0, 1.0),
    ]
    return ViewpointGraph(
        scene_id="synthetic_navigation_support",
        graph_id="synthetic_place_graph",
        node_heading_count=12,
        nodes=nodes,
        edges=[
            _edge("ab", "a", "b", 1.0),
            _edge("bd", "b", "d", 1.0),
            _edge("ac", "a", "c", 1.0),
            _edge("cd", "c", "d", 1.0),
        ],
    )


def _grid() -> TraversabilityGrid:
    spec = GridSpec(
        origin=[-2.0, -2.0], resolution=0.05, width=100, height=100,
        scene_id="synthetic_navigation_support",
    )
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    return TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))


def _approved_blueprints(graph: ViewpointGraph) -> dict:
    payload = propose_route_blueprints(graph, config=DEFAULT_CONFIG)
    candidate = next(
        row for row in payload["blueprints"]
        if row["start_anchor_id"] == "a" and row["goal_anchor_id"] == "d"
    )
    return update_route_blueprint(payload, candidate["blueprint_id"], status="approved")


def _config(**overrides: object) -> dict:
    return {
        **DEFAULT_CONFIG,
        "max_support_poses": 400,
        "max_panorama_poses": 8,
        "max_polar_observations": 4000,
        "max_polar_batches": 1200,
        **overrides,
    }




def test_global_support_normalization_hard_merges_only_action_safe_parallel_lanes() -> None:
    poses = {
        "a0": {"motion_node_id": "a0", "motion_pose_id": "a0", "position": [0.0, 0.0, 0.0], "tags": [], "anchor_node_ids": []},
        "a1": {"motion_node_id": "a1", "motion_pose_id": "a1", "position": [0.25, 0.0, 0.0], "tags": [], "anchor_node_ids": []},
        "b0": {"motion_node_id": "b0", "motion_pose_id": "b0", "position": [0.05, 0.0, 0.0], "tags": [], "anchor_node_ids": []},
        "b1": {"motion_node_id": "b1", "motion_pose_id": "b1", "position": [0.30, 0.0, 0.0], "tags": [], "anchor_node_ids": []},
    }
    edges = {
        edge_id: {
            "motion_edge_id": edge_id, "source": source, "target": target,
            "distance_m": 0.25, "action": "move_forward", "edge_type": "lane_forward",
            "lane": "test", "place_edge_ids": [place_edge_id], "portal_ids": [],
        }
        for edge_id, source, target, place_edge_id in [
            ("a_forward", "a0", "a1", "place_a"), ("a_reverse", "a1", "a0", "place_a"),
            ("b_forward", "b0", "b1", "place_b"), ("b_reverse", "b1", "b0", "place_b"),
        ]
    }
    anchors: dict[str, set[str]] = defaultdict(set)
    sequences = [["a0", "a1"], ["b0", "b1"]]

    diagnostics = _normalize_global_support_graph(
        poses, edges, anchors, sequences,
        motion_grid=_grid(), config=_config(),
        blueprint_ids_by_place_edge={"place_a": {"bp_a"}, "place_b": {"bp_b"}},
    )

    assert diagnostics["hard_merged_pose_count"] == 2
    assert len(poses) == 2
    assert all(pose["merge_kind"] == "hard" for pose in poses.values())
    assert all(math.isclose(float(edge["distance_m"]), 0.25) for edge in edges.values())
    assert all(len(pose["source_motion_pose_ids"]) == 2 for pose in poses.values())


def test_global_support_normalization_emits_bidirectional_cross_blueprint_stitches() -> None:
    poses = {
        "a0": {"motion_node_id": "a0", "motion_pose_id": "a0", "position": [0.0, 0.0, 0.0], "tags": [], "anchor_node_ids": []},
        "a1": {"motion_node_id": "a1", "motion_pose_id": "a1", "position": [0.0, 0.25, 0.0], "tags": [], "anchor_node_ids": []},
        "b0": {"motion_node_id": "b0", "motion_pose_id": "b0", "position": [0.25, 0.0, 0.0], "tags": [], "anchor_node_ids": []},
        "b1": {"motion_node_id": "b1", "motion_pose_id": "b1", "position": [0.25, 0.25, 0.0], "tags": [], "anchor_node_ids": []},
    }
    edges = {
        edge_id: {
            "motion_edge_id": edge_id, "source": source, "target": target,
            "distance_m": 0.25, "action": "move_forward", "edge_type": "lane_forward",
            "lane": "test", "place_edge_ids": [place_edge_id], "portal_ids": [],
        }
        for edge_id, source, target, place_edge_id in [
            ("a_forward", "a0", "a1", "place_a"), ("a_reverse", "a1", "a0", "place_a"),
            ("b_forward", "b0", "b1", "place_b"), ("b_reverse", "b1", "b0", "place_b"),
        ]
    }
    anchors: dict[str, set[str]] = defaultdict(set)
    sequences = [["a0", "a1"], ["b0", "b1"]]

    diagnostics = _normalize_global_support_graph(
        poses, edges, anchors, sequences,
        motion_grid=_grid(), config=_config(),
        blueprint_ids_by_place_edge={"place_a": {"bp_a"}, "place_b": {"bp_b"}},
    )

    stitches = [edge for edge in edges.values() if edge["edge_type"] == "cross_blueprint_stitch"]
    assert diagnostics["cross_blueprint_stitch_pair_count"] == 2
    assert len(stitches) == 4
    assert all(edge["distance_m"] == pytest.approx(0.25) for edge in stitches)
    assert all(edge["source_blueprint_ids"] == ["bp_a", "bp_b"] for edge in stitches)
    assert all("global_stitch" in poses[edge["source"]]["tags"] for edge in stitches)
def test_v4_requires_approved_route_blueprint() -> None:
    with pytest.raises(ValueError, match="approve at least one"):
        build_navigation_support(
            _place_graph(),
            propose_route_blueprints(_place_graph(), config=DEFAULT_CONFIG),
            annotation=None,
            motion_grid=_grid(),
            config=_config(),
        )


def test_v2_support_algorithm_has_distinct_profile_identity() -> None:
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    baseline = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(), config=_config(),
    )
    candidate = build_navigation_support(
        graph,
        blueprints,
        annotation=None,
        motion_grid=_grid(),
        config=_config(),
        normalizer=GlobalExecutableNetworkNormalizer(),
    )

    assert baseline["support_graph"]["support_algorithm_id"] == "production_v1"
    assert candidate["support_graph"]["support_algorithm_id"] == ALGORITHM_ID
    assert candidate["support_graph"]["support_pipeline"]["algorithm_id"] == ALGORITHM_ID
    assert candidate["support_graph"]["experimental"] is True
    assert candidate["observation_plan"]["support_algorithm_id"] == ALGORITHM_ID
    assert baseline["support_graph"]["profile_digest"] != candidate["support_graph"]["profile_digest"]


def test_v4_action_support_is_normalized_direct_and_native() -> None:
    graph = _place_graph()
    result = build_navigation_support(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(max_panorama_poses=1),
    )
    support = result["support_graph"]
    plan = result["observation_plan"]

    assert support["profile_id"] == PROFILE_ID
    validation = validate_navigation_support(support, motion_grid=_grid())
    assert validation["ok"] is True
    assert validation["strong_component_count"] == 1
    step_m = float(result["support_graph"]["forward_step_m"])
    tolerance_m = float(result["support_graph"]["forward_tolerance_m"])
    assert step_m == pytest.approx(0.25)
    # Lane chords stay exactly one action step; only link/stitch chords may be
    # shorter, and never below the minimum link distance.
    link_min = float(support["min_link_distance_m"])
    lane_edges = [edge for edge in support["edges"] if str(edge.get("lane")) not in {"global_stitch", "base_attach"}]
    assert lane_edges
    assert all(step_m - tolerance_m <= float(edge["distance_m"]) <= step_m + tolerance_m for edge in lane_edges)
    assert all(link_min - 1e-9 <= float(edge["distance_m"]) <= step_m + tolerance_m for edge in support["edges"])
    assert all(entry["projection"] == "native_perspective" for entry in plan["render_entries"])
    assert all("LAZY" not in str(entry.get("tier")) for entry in plan["render_entries"])
    assert plan["summary"]["polar_observation_count"] <= 4000
    assert plan["summary"]["polar_batch_count"] <= 1200

    approved = next(row for row in result["route_blueprints"]["blueprints"] if row["status"] == "approved")
    route = next(row for row in support["blueprint_routes"] if row["blueprint_id"] == approved["blueprint_id"])
    assert route["distance_m"] <= max(route["place_path_distance_m"] * 1.15, route["place_path_distance_m"] + 0.75)
    assert set(route["motion_edge_ids"])

    available = {row["motion_node_id"]: set(row["available_heading_ids"]) for row in plan["poses"]}
    states = {row["motion_state_id"]: row for row in support["states"]}
    for transition in support["transitions"]:
        source = states[transition["source_state_id"]]
        assert source["heading_id"] in available[source["motion_pose_id"]]
        if transition["action"] in {"turn_left", "turn_right"}:
            assert math.isclose(abs(float(transition["turn_deg"])), 15.0)



def test_v4_build_emits_compacted_support_topology() -> None:
    graph = _place_graph()
    result = build_navigation_support(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(max_panorama_poses=1),
    )
    support = result["support_graph"]
    topology = support["topology"]
    raw_nodes = {str(node["motion_node_id"]) for node in support["nodes"]}
    topology_nodes = {str(node["motion_node_id"]): node for node in topology["nodes"]}

    assert topology["raw_pose_count"] == len(raw_nodes)
    assert set(topology["raw_pose_to_topology_id"]) == raw_nodes
    assert set(topology["raw_pose_to_topology_id"].values()) <= set(topology_nodes)
    assert topology["topology_node_count"] == len(topology_nodes)
    assert topology["collapsed_pose_count"] == len(raw_nodes) - len(topology_nodes)
    assert all(edge["executable"] is False for edge in topology["edges"])
    assert all(
        str(edge["source"]) in topology_nodes and str(edge["target"]) in topology_nodes
        for edge in topology["edges"]
    )
    assert all(
        float(edge["distance_m"]) >= float(topology["min_node_spacing_m"]) - 1e-9
        for edge in topology["edges"]
    )
    for index, left in enumerate(topology["nodes"]):
        for right in topology["nodes"][index + 1:]:
            assert math.dist(left["position"][:2], right["position"][:2]) >= float(topology["min_node_spacing_m"]) - 1e-9


def test_v4_multiturn_route_has_reverse_turn_connectivity() -> None:
    """A reviewed route must turn at each corner in both travel directions."""
    graph = ViewpointGraph(
        scene_id="synthetic_navigation_support",
        graph_id="synthetic_multiturn_place_graph",
        node_heading_count=12,
        nodes=[
            _node("a", 0.0, 0.0),
            _node("b", 1.0, 0.0),
            _node("c", 2.0, 1.0),
            _node("d", 2.0, 2.0),
        ],
        edges=[
            _edge("ab", "a", "b", 1.0),
            _edge("bc", "b", "c", math.sqrt(2.0)),
            _edge("cd", "c", "d", 1.0),
        ],
    )
    blueprints = {
        "schema_version": "opticalnav.adaptive_navigation_support.v4",
        "profile_id": PROFILE_ID,
        "place_graph_id": graph.graph_id,
        "blueprints": [{
            "blueprint_id": "bp_multiturn",
            "start_anchor_id": "a",
            "goal_anchor_id": "d",
            "place_path_node_ids": ["a", "b", "c", "d"],
            "place_path_edge_ids": ["ab", "bc", "cd"],
            "place_path_distance_m": 2.0 + math.sqrt(2.0),
            "status": "approved",
        }],
    }

    result = build_navigation_support(
        graph,
        blueprints,
        annotation=None,
        motion_grid=_grid(),
        config=_config(max_panorama_poses=1),
    )

    assert result["support_graph"]["validation"]["ok"] is True
    assert result["support_graph"]["blueprint_routes"][0]["blueprint_id"] == "bp_multiturn"


def test_v4_defers_unowned_connector_between_independent_approved_routes() -> None:
    """An automatic coverage bridge must not become a hidden build owner."""
    graph = ViewpointGraph(
        scene_id="independent_review_components",
        graph_id="independent_review_components",
        node_heading_count=12,
        nodes=[
            _node("a", -1.0, 0.0), _node("b", 0.0, 0.0),
            _node("c", 0.0, 1.0), _node("d", 1.0, 1.0),
        ],
        edges=[
            _edge("ab", "a", "b", 1.0),
            # This is a certified but unowned coverage connector. The former
            # global-MST policy materialised it merely to join the two routes.
            _edge("coverage_bridge", "b", "c", 1.0),
            _edge("cd", "c", "d", 1.0),
        ],
    )
    blueprints = {
        "profile_id": PROFILE_ID,
        "blueprint_digest": "independent-components",
        "blueprints": [
            {
                "blueprint_id": "bp_ab", "start_anchor_id": "a", "goal_anchor_id": "b",
                "place_path_node_ids": ["a", "b"], "place_path_edge_ids": ["ab"],
                "place_path_distance_m": 1.0, "status": "approved",
            },
            {
                "blueprint_id": "bp_cd", "start_anchor_id": "c", "goal_anchor_id": "d",
                "place_path_node_ids": ["c", "d"], "place_path_edge_ids": ["cd"],
                "place_path_distance_m": 1.0, "status": "approved",
            },
        ],
    }

    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(), config=_config(),
    )

    support = result["support_graph"]
    assert set(support["trunk"]["canonical_backbone_edge_ids"]) == {"ab", "cd"}
    assert "coverage_bridge" not in support["trunk"]["canonical_backbone_edge_ids"]
    assert support["trunk"]["allow_disconnected_review_components"] is True
    validation = validate_navigation_support(support, motion_grid=_grid())
    assert validation["ok"] is True
    assert validation["strong_component_count"] == 2


def test_v4_manual_place_edge_is_auto_pinned_into_backbone() -> None:
    """A hand-drawn place edge already had its own explicit review; unlike an
    auto-sampled coverage/bridge candidate it does not need a route or a
    separate support_backbone_pin flag to join the executable trunk."""
    graph = ViewpointGraph(
        scene_id="manual_edge_join",
        graph_id="manual_edge_join",
        node_heading_count=12,
        nodes=[
            _node("a", -1.0, 0.0), _node("b", 0.0, 0.0),
            _node("c", 0.0, 1.0), _node("d", 1.0, 1.0),
        ],
        edges=[
            _edge("ab", "a", "b", 1.0),
            ViewpointEdge(
                edge_id="edge_manual_0001", source="b", target="c", distance_m=1.0, weight=1.0,
                collision_free=True,
                extras={"manual": True, "edge_validation": {"mode": "normal", "wall_run_cells": 0}},
            ),
            _edge("cd", "c", "d", 1.0),
        ],
    )
    blueprints = {
        "profile_id": PROFILE_ID,
        "blueprint_digest": "manual-edge-join",
        "blueprints": [
            {
                "blueprint_id": "bp_ab", "start_anchor_id": "a", "goal_anchor_id": "b",
                "place_path_node_ids": ["a", "b"], "place_path_edge_ids": ["ab"],
                "place_path_distance_m": 1.0, "status": "approved",
            },
        ],
    }

    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(), config=_config(),
    )

    support = result["support_graph"]
    assert set(support["trunk"]["canonical_backbone_edge_ids"]) == {"ab", "edge_manual_0001"}
    validation = validate_navigation_support(support, motion_grid=_grid())
    assert validation["ok"] is True
    poses = {pose["motion_node_id"]: pose for pose in support["poses"]}
    assert "c" in support["anchor_pose_ids"]
    c_pose_id = next(iter(support["anchor_pose_ids"]["c"]))
    assert c_pose_id in poses


def test_v4_open_portal_is_preserved_on_certified_forward_transitions() -> None:
    graph = _place_graph()
    portal_edge = next(edge for edge in graph.edges if edge.edge_id == "ab")
    portal_edge.extras = {
        **portal_edge.extras,
        "portal": "portal_ab",
        "portal_state": "open",
    }
    blueprints = propose_route_blueprints(graph, config=DEFAULT_CONFIG)
    portal_blueprint = next(
        row for row in blueprints["blueprints"]
        if "portal:portal_ab" in row["coverage_feature_ids"]
    )
    blueprints = update_route_blueprint(blueprints, portal_blueprint["blueprint_id"], status="approved")
    result = build_navigation_support(
        graph,
        blueprints,
        annotation=None,
        motion_grid=_grid(),
        config=_config(),
    )
    support = result["support_graph"]
    portal_motion_edges = [edge for edge in support["edges"] if edge["edge_type"] == "portal_bridge"]
    assert portal_motion_edges
    assert all(edge["portal_ids"] == ["portal_ab"] for edge in portal_motion_edges)
    by_motion_edge = {edge["motion_edge_id"]: edge for edge in portal_motion_edges}
    portal_transitions = [
        item for item in support["transitions"]
        if item.get("motion_edge_id") in by_motion_edge
    ]
    assert portal_transitions
    assert all(item["portal_ids"] == ["portal_ab"] for item in portal_transitions)


def test_v4_user_certified_opening_restores_one_cell_action_capsule() -> None:
    """A reviewed floor-mask gap must tolerate the 15-degree lattice phase.

    Ordinary portal centre lines stay narrow.  The extra one-cell band belongs
    only to an explicitly certified manual opening and never makes diagonal
    corner cells walkable.
    """
    graph = _place_graph()
    edge = next(item for item in graph.edges if item.edge_id == "ab")
    edge.extras = {
        "portal": "manual_opening_ab",
        "portal_source": "user_certified",
        "portal_type": "manual_opening",
        "portal_state": "open",
        "open": True,
        "manual_opening": {"certified": True},
        "edge_validation": {"wall_run_cells": 0},
    }
    grid = _grid()
    # Simulate an authoring-mask gap at the reviewed doorway line.
    x, y = world_to_cell(grid.spec, 0.5, 0.0)
    grid.traversable[y - 2:y + 3, x - 2:x + 3] = False

    restored, portal_ids = _v3_portal_aware_grid(graph, grid)

    assert portal_ids == ["manual_opening_ab"]
    assert restored.traversable[y, x]
    assert restored.traversable[y + 1, x]
    assert restored.traversable[y, x + 1]
    assert not restored.traversable[y + 2, x]


def test_v4_legacy_geometry_certified_doorway_restores_action_capsule() -> None:
    """Older direct doorway edits remain executable without recertification.

    The first v4 editor recorded the inferred portal only inside its accepted
    edge-validation record.  The support builder must honour that immutable
    certificate, but must not widen unrelated manual edges.
    """
    graph = _place_graph()
    edge = next(item for item in graph.edges if item.edge_id == "ab")
    edge.extras = {
        "manual": True,
        "edge_validation": {
            "mode": "doorway",
            "reason": "certified_doorway",
            "portal_id": "inferred_portal_ab",
            "wall_run_cells": 0,
        },
    }
    grid = _grid()
    x, y = world_to_cell(grid.spec, 0.5, 0.0)
    grid.traversable[y - 2:y + 3, x - 2:x + 3] = False

    restored, portal_ids = _v3_portal_aware_grid(graph, grid)

    assert portal_ids == ["inferred_portal_ab"]
    assert restored.traversable[y, x]
    assert restored.traversable[y + 1, x]
    assert restored.traversable[y, x + 1]
    assert not restored.traversable[y + 2, x]


def test_v4_blueprints_are_reviewable_and_budget_failure_is_atomic() -> None:
    graph = _place_graph()
    proposed = propose_route_blueprints(graph, config=DEFAULT_CONFIG)
    existing = {(row["start_anchor_id"], row["goal_anchor_id"]) for row in proposed["blueprints"]}
    start, goal = next(pair for pair in (("b", "a"), ("c", "a"), ("d", "b"), ("d", "c")) if pair not in existing)
    proposed = add_route_blueprint(proposed, graph, start_anchor_id=start, goal_anchor_id=goal)
    blueprint_id = proposed["blueprints"][-1]["blueprint_id"]
    approved = update_route_blueprint(proposed, blueprint_id, status="approved")
    assert next(row for row in approved["blueprints"] if row["blueprint_id"] == blueprint_id)["status"] == "approved"
    assert approved["blueprint_digest"] != proposed["blueprint_digest"]
    deleted = delete_route_blueprint(approved, blueprint_id)
    assert all(row["blueprint_id"] != blueprint_id for row in deleted["blueprints"])

    with pytest.raises(ValueError, match="support_polar_budget_exceeded"):
        build_navigation_support(
            graph,
            approved,
            annotation=None,
            motion_grid=_grid(),
            config=_config(max_polar_observations=1),
        )


def test_v4_reconciles_route_intent_after_place_edge_repair() -> None:
    """Removing one reviewed corridor keeps an approved intent via its safe detour."""
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    approved = next(row for row in blueprints["blueprints"] if row["status"] == "approved")
    assert approved["start_anchor_id"] == "a"
    assert approved["goal_anchor_id"] == "d"
    assert "ab" in approved["place_path_edge_ids"]

    graph.edges = [edge for edge in graph.edges if edge.edge_id != "ab"]
    reconciled, summary = reconcile_route_blueprints_after_place_graph_edit(blueprints, graph)
    updated = next(row for row in reconciled["blueprints"] if row["blueprint_id"] == approved["blueprint_id"])

    assert updated["status"] == "approved"
    assert updated["place_path_edge_ids"] == ["ac", "cd"]
    assert approved["blueprint_id"] in summary["preserved_approved_blueprint_ids"]
    assert approved["blueprint_id"] in summary["relinked_blueprint_ids"]
    assert summary["review_required_blueprint_ids"] == []


def test_v4_defers_unapproved_central_trunk_edges() -> None:
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    approved = next(row for row in blueprints["blueprints"] if row["status"] == "approved")

    executable, diagnostics = _major_trunk_edges(graph, blueprints["blueprints"], None, _config())

    assert executable == set(approved["place_path_edge_ids"])
    assert diagnostics["deferred_unapproved_trunk_edge_count"] >= 0


def test_v4_blocker_scan_groups_every_approval_that_uses_one_corridor(monkeypatch) -> None:
    """One bad shared corridor must not make the UI blame a single route."""
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    primary = next(row for row in blueprints["blueprints"] if row["status"] == "approved")
    assert "ab" in primary["place_path_edge_ids"]
    shared = {
        **primary,
        "blueprint_id": "bp_shared_ab",
        "start_anchor_id": "a",
        "goal_anchor_id": "b",
        "place_path_node_ids": ["a", "b"],
        "place_path_edge_ids": ["ab"],
        "place_path_distance_m": 1.0,
        "status": "approved",
    }
    independent = {
        **primary,
        "blueprint_id": "bp_shared_cd",
        "start_anchor_id": "c",
        "goal_anchor_id": "d",
        "place_path_node_ids": ["c", "d"],
        "place_path_edge_ids": ["cd"],
        "place_path_distance_m": 1.0,
        "status": "approved",
    }
    blueprints["blueprints"].extend((shared, independent))

    from navigation_dataset import navigation_support as support_module
    original = support_module._action_grid_path

    def fail_ab(grid, start, end, config, **kwargs):
        if math.isclose(float(end[0]), 1.0) and math.isclose(float(end[1]), 0.0):
            return None
        if math.isclose(float(end[0]), 1.0) and math.isclose(float(end[1]), 1.0):
            return None
        return original(grid, start, end, config, **kwargs)

    monkeypatch.setattr(support_module, "_action_grid_path", fail_ab)
    diagnosis = analyze_navigation_support_blockers(
        graph,
        blueprints,
        annotation=None,
        motion_grid=_grid(),
        config=_config(),
    )

    assert diagnosis["complete"] is True
    assert diagnosis["buildable_after_exclusion"] is False
    assert len(diagnosis["blockers"]) == 2
    groups = {group["place_edge_id"]: group for group in diagnosis["blockers"]}
    assert set(groups) == {"ab", "cd"}
    assert groups["ab"]["kind"] == "support_corridor_unreachable"
    assert set(groups["ab"]["blocked_blueprint_ids"]) == {primary["blueprint_id"], "bp_shared_ab"}
    assert groups["cd"]["blocked_blueprint_ids"] == ["bp_shared_cd"]
    # The helper must remain a dry run: the durable review states are untouched.
    blocked_ids = set(diagnosis["blocked_blueprint_ids"])
    assert all(row["status"] == "approved" for row in blueprints["blueprints"] if row["blueprint_id"] in blocked_ids)


def test_v4_structural_corridor_blocker_exposes_edge_without_blaming_routes() -> None:
    graph = _place_graph()
    group = _support_blocker_group(
        "support_corridor_unreachable:cd",
        place_graph=graph,
        blueprints=_approved_blueprints(graph),
    )

    assert group["structural_backbone"] is True
    assert group["requires_place_graph_repair"] is True
    assert group["ownership"] == "shared_backbone_connector"
    assert group["blocked_blueprint_ids"] == []
    assert group["source"] == "c"
    assert group["target"] == "d"
    assert group["distance_m"] == pytest.approx(1.0)


def test_v4_route_component_failure_is_a_route_owned_blocker() -> None:
    """A validation error naming a blueprint must not halt blocker scanning globally."""
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    blueprint = next(row for row in blueprints["blueprints"] if row["status"] == "approved")

    group = _support_blocker_group(
        f"support_route_component_disconnected:{blueprint['blueprint_id']}",
        place_graph=graph,
        blueprints=blueprints,
    )

    assert group["kind"] == "support_route_component_disconnected"
    assert group["blocked_blueprint_ids"] == [blueprint["blueprint_id"]]
    assert group["source"] == blueprint["start_anchor_id"]
    assert group["target"] == blueprint["goal_anchor_id"]
    assert group["place_edge_ids"] == blueprint["place_path_edge_ids"]


def test_v4_blocker_scan_keeps_a_clean_plan_as_the_exact_dry_run() -> None:
    graph = _place_graph()
    diagnosis = analyze_navigation_support_blockers(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(),
    )

    assert diagnosis["ok"] is True
    assert diagnosis["complete"] is True
    assert diagnosis["blockers"] == []
    assert diagnosis["_artifacts"]["support_graph"]["profile_id"] == PROFILE_ID


def test_v4_episodes_use_existing_state_heading_observations() -> None:
    graph = _place_graph()
    result = build_navigation_support(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(),
    )
    episodes = plan_support_episodes(
        support_graph=result["support_graph"],
        observation_plan=result["observation_plan"],
        num_pairs=1,
        split_counts={"train": 1},
    )
    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.navigation_mode == PROFILE_ID
    assert episode.actions[-1] == "stop"
    assert episode.path_nodes
    assert len(episode.path_nodes) == len(episode.path_headings)
    forward_actions = sum(action == "move_forward" for action in episode.actions)
    assert 4 <= forward_actions <= 48
    # Planning used to appear to succeed but failed when the daemon wrote the
    # episode because the shared schema did not recognise the v4 mode.
    assert episode_from_payload(episode_to_payload(episode)).navigation_mode == PROFILE_ID
    for timestep in episode.timesteps:
        assert timestep.extras["heading_id"] in timestep.extras["available_heading_ids"]
    summary = validate_support_episode(episode)
    assert summary["forward_action_count"] == forward_actions
    forward_index = next(index for index, step in enumerate(episode.timesteps[:-1]) if step.action == "move_forward")
    episode.timesteps[forward_index + 1].agent_pose[0] += 0.25
    with pytest.raises(ValueError, match="support_episode_non_normalized_forward"):
        validate_support_episode(episode)


def test_v4_observation_expansion_is_native_add_only_and_full_at_l6(tmp_path) -> None:
    graph = _place_graph()
    result = build_navigation_support(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(max_panorama_poses=1),
    )
    base = result["observation_plan"]
    l1 = build_support_observation_expansion(base, level_id="l1_context_15")
    base_keys = {
        (entry["motion_node_id"], entry["heading_id"])
        for entry in base["render_entries"]
    }
    l1_keys = {
        (entry["motion_node_id"], entry["heading_id"])
        for entry in l1["render_entries"]
    }
    assert l1["profile_digest"] == base["profile_digest"]
    assert l1["validation_digest"] == base["validation_digest"]
    assert l1["coverage_level_id"] == "l1_context_15"
    assert not (base_keys & l1_keys)
    assert l1["summary"]["coverage_polar_observation_count"] == len(base_keys) + len(l1_keys)
    assert all(entry["projection"] == "native_perspective" for entry in l1["render_entries"])
    assert all(entry["canonical"] is True for entry in l1["render_entries"])

    l6 = build_support_observation_expansion(base, level_id="l6_detail_full_24")
    detail_poses = [pose for pose in l6["poses"] if pose["tier"] == "ACTION_NATIVE"]
    assert detail_poses
    assert all(len(pose["available_heading_ids"]) == 24 for pose in detail_poses)
    assert l6["summary"]["coverage_polar_observation_count"] <= 4000

    # L6 is a true full detail-pose sweep even when a pose happens to have just
    # one action heading; it is not merely a +/-90 degree neighbourhood.
    single_heading_base = {
        "profile_id": PROFILE_ID,
        "scene_id": "synthetic_navigation_support",
        "place_graph_id": "single_heading",
        "profile_digest": "single-heading-digest",
        "validation_digest": "single-heading-digest",
        "poses": [{
            "motion_node_id": "detail",
            "position": [0.0, 0.0, 0.0],
            "tier": "ACTION_NATIVE",
            "available_heading_ids": ["h_000"],
            "action_heading_ids": ["h_000"],
        }],
        "render_entries": [{"motion_node_id": "detail", "heading_id": "h_000", "polar_batch_key": "detail:b00"}],
        "summary": {"support_pose_count": 1, "polar_batch_count": 1},
        "config": _config(),
    }
    assert len(build_support_observation_expansion(single_heading_base, level_id="l6_detail_full_24")["poses"][0]["available_heading_ids"]) == 24

    path = write_support_observation_expansion(tmp_path, l1)
    assert path.name == support_observation_expansion_filename("l1_context_15")
    assert read_support_observation_plan(path)["coverage_digest"] == l1["coverage_digest"]


def test_v4_l0_recovery_from_l3_context_is_exact_and_archive_is_immutable(tmp_path) -> None:
    graph = _place_graph()
    result = build_navigation_support(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(max_panorama_poses=1),
    )
    paths = write_navigation_support(tmp_path, result)
    l3 = build_support_observation_expansion(result["observation_plan"], level_id="l3_context_45")
    l3_path = write_support_observation_expansion(tmp_path, l3)
    recovered = recover_l0_observation_plan_from_expansion(
        l3,
        support_graph_ref="navigation_support_archives/test/navigation_support_graph.json",
    )
    original_keys = {
        (entry["motion_node_id"], entry["heading_id"])
        for entry in result["observation_plan"]["render_entries"]
    }
    recovered_keys = {
        (entry["motion_node_id"], entry["heading_id"])
        for entry in recovered["render_entries"]
    }
    l3_keys = {(entry["motion_node_id"], entry["heading_id"]) for entry in l3["render_entries"]}
    assert recovered_keys == original_keys
    assert not (recovered_keys & l3_keys)
    assert recovered["summary"]["polar_batch_count"] == result["observation_plan"]["summary"]["polar_batch_count"]

    archived = archive_navigation_support(tmp_path, reason="test")
    assert archived is not None
    archive_root = tmp_path / SUPPORT_ARCHIVE_DIR / result["observation_plan"]["profile_digest"]
    assert (archive_root / SUPPORT_GRAPH_FILE).is_file()
    assert (archive_root / OBSERVATION_PLAN_FILE).is_file()
    assert (archive_root / RENDER_GRAPH_FILE).is_file()
    assert (archive_root / l3_path.name).is_file()
    assert json.loads((archive_root / "archive_manifest.json").read_text(encoding="utf-8"))["active"] is False
    overlay = latest_support_render_archive(tmp_path)
    assert overlay is not None
    assert overlay["read_only"] is True
    assert overlay["render_graph"]["edges"] == []
    assert len(overlay["render_graph"]["nodes"]) == len(result["observation_plan"]["poses"])


def test_v4_sidecars_are_separate_from_legacy_and_round_trip(tmp_path) -> None:
    graph = _place_graph()
    result = build_navigation_support(
        graph,
        _approved_blueprints(graph),
        annotation=None,
        motion_grid=_grid(),
        config=_config(),
    )
    paths = write_navigation_support(tmp_path, result)

    assert (tmp_path / PLACE_GRAPH_FILE).is_file()
    assert (tmp_path / BLUEPRINTS_FILE).is_file()
    assert (tmp_path / SUPPORT_GRAPH_FILE).is_file()
    assert (tmp_path / OBSERVATION_PLAN_FILE).is_file()
    assert not (tmp_path / "motion_graph.json").exists()
    assert read_route_blueprints(paths["route_blueprints"])["profile_id"] == PROFILE_ID


# --- Lateral band / turn-freedom budget -------------------------------------


def _corridor_graph(length_m: float = 2.0) -> ViewpointGraph:
    """A single straight place edge, long enough for several lateral chords."""
    nodes = [_node("p0", 0.0, 0.0), _node("p1", length_m, 0.0)]
    return ViewpointGraph(
        scene_id="synthetic_lateral_band",
        graph_id="synthetic_lateral_place_graph",
        node_heading_count=12,
        nodes=nodes,
        edges=[_edge("p0p1", "p0", "p1", length_m)],
    )


def _corridor_blueprints(graph: ViewpointGraph) -> dict:
    payload = propose_route_blueprints(graph, config=DEFAULT_CONFIG)
    candidate = next(
        row for row in payload["blueprints"]
        if row["start_anchor_id"] == "p0" and row["goal_anchor_id"] == "p1"
    )
    return update_route_blueprint(payload, candidate["blueprint_id"], status="approved")


def _portal_corridor_graph(length_m: float = 1.0) -> ViewpointGraph:
    edge = ViewpointEdge(
        edge_id="p0p1", source="p0", target="p1", distance_m=length_m, weight=length_m,
        collision_free=True, extras={"portal": "test_portal", "portal_state": "open"},
    )
    return ViewpointGraph(
        scene_id="synthetic_lateral_band_portal",
        graph_id="synthetic_lateral_portal_place_graph",
        node_heading_count=12,
        nodes=[_node("p0", 0.0, 0.0), _node("p1", length_m, 0.0)],
        edges=[edge],
    )


def _grid_blocking_positive_y() -> TraversabilityGrid:
    """Same footprint as ``_grid`` but everything with y > 0.1 is a wall."""
    spec = GridSpec(origin=[-2.0, -2.0], resolution=0.05, width=100, height=100, scene_id="synthetic_navigation_support")
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    for row in range(spec.height):
        y = spec.origin[1] + row * spec.resolution
        if y > 0.1:
            traversable[row, :] = False
    return TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))


def test_v4_turn_freedom_is_structural() -> None:
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    structural = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(lateral_band_enabled=False),
    )
    legacy = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(lateral_band_enabled=False, turn_freedom_policy="patch_tags"),
    )
    support = structural["support_graph"]
    assert support["validation"]["ok"] is True
    assert support["validation"]["strong_component_count"] == 1
    assert legacy["support_graph"]["validation"]["ok"] is True

    def heading_counts(graph_payload: dict) -> dict:
        counts: dict[str, int] = defaultdict(int)
        for state in graph_payload["states"]:
            counts[state["motion_pose_id"]] += 1
        return counts

    structural_counts = heading_counts(support)
    legacy_counts = heading_counts(legacy["support_graph"])
    # "b" is a pass-through anchor between the two approved edges (ab, bd):
    # degree 2, not a route endpoint, not a portal. The legacy tag-driven
    # policy always closed it (24 headings); the structural policy keeps it
    # to just its real corner.
    b_pose_id = next(iter(support["anchor_pose_ids"]["b"]))
    assert legacy_counts[b_pose_id] == 24
    assert 2 <= structural_counts[b_pose_id] < 24


def test_v4_shortest_arc_closure_keeps_u_turn() -> None:
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(lateral_band_enabled=False),
    )
    support = result["support_graph"]
    assert support["validation"]["ok"] is True
    # "a" is the approved route's start anchor and component root: a genuine
    # full-turn pose with only one real direction (ab) plus its reverse.
    a_pose_id = next(iter(support["anchor_pose_ids"]["a"]))
    headings = {state["heading_id"] for state in support["states"] if state["motion_pose_id"] == a_pose_id}
    assert headings == {"h_090", "h_270"} or len(headings) == 13
    assert len(headings) == 13

    full_circle = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(lateral_band_enabled=False, turn_closure_policy="full_circle"),
    )
    full_headings = {
        state["heading_id"] for state in full_circle["support_graph"]["states"]
        if state["motion_pose_id"] == a_pose_id
    }
    assert len(full_headings) == 24


def test_v4_lateral_band_emits_triangular_side_lanes() -> None:
    graph = _corridor_graph()
    blueprints = _corridor_blueprints(graph)
    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(),
    )
    support = result["support_graph"]
    assert support["validation"]["ok"] is True
    assert support["validation"]["strong_component_count"] == 1

    lateral_edges = [edge for edge in support["edges"] if edge["lane"] == "lateral_band"]
    assert lateral_edges
    poses = {pose["motion_node_id"]: pose for pose in support["poses"]}
    step = float(support["forward_step_m"]); tolerance = float(support["forward_tolerance_m"])
    for edge in lateral_edges:
        source_point = poses[edge["source"]]["position"][:2]
        target_point = poses[edge["target"]]["position"][:2]
        distance = math.dist(source_point, target_point)
        assert step - tolerance <= distance <= step + tolerance
        assert int(edge["heading_id"].split("_", 1)[1]) % 15 == 0

    lateral_pose_ids = {pose["motion_node_id"] for pose in support["poses"] if "lateral" in (pose.get("tags") or [])}
    assert lateral_pose_ids

    plan = result["observation_plan"]
    tier_by_pose = {row["motion_node_id"]: row["tier"] for row in plan["poses"]}
    assert all(tier_by_pose[pose_id] == "ACTION_NATIVE" for pose_id in lateral_pose_ids)

    route_pose_ids = {pose_id for route in support["blueprint_routes"] for pose_id in route["motion_pose_ids"]}
    assert not (route_pose_ids & lateral_pose_ids)

    diagnostics = support["generation_diagnostics"]
    assert diagnostics["lateral_run_count"] > 0
    assert diagnostics["lateral_segment_count"] > 0
    assert diagnostics["lateral_switch_count"] > 0
    assert diagnostics["lateral_pose_count"] == len(lateral_pose_ids)
    assert diagnostics["lateral_edge_count"] == len(lateral_edges)


def test_v4_lateral_band_skips_unsafe_and_portal_chords() -> None:
    graph = _corridor_graph()
    blueprints = _corridor_blueprints(graph)
    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid_blocking_positive_y(),
        config=_config(),
    )
    support = result["support_graph"]
    assert support["validation"]["ok"] is True
    poses = {pose["motion_node_id"]: pose for pose in support["poses"]}
    lateral_edges = [edge for edge in support["edges"] if edge["lane"] == "lateral_band"]
    assert lateral_edges
    for edge in lateral_edges:
        assert poses[edge["source"]]["position"][1] <= 0.15
        assert poses[edge["target"]]["position"][1] <= 0.15
    assert support["generation_diagnostics"]["lateral_unsafe_chord_skip_count"] > 0

    portal_graph = _portal_corridor_graph()
    portal_blueprints = _corridor_blueprints(portal_graph)
    portal_result = build_navigation_support(
        portal_graph, portal_blueprints, annotation=None, motion_grid=_grid(),
        config=_config(),
    )
    portal_support = portal_result["support_graph"]
    assert portal_support["validation"]["ok"] is True
    assert not [edge for edge in portal_support["edges"] if edge["lane"] == "lateral_band"]
    assert portal_support["generation_diagnostics"]["lateral_run_count"] == 0


def test_v4_lateral_band_disabled_is_legacy() -> None:
    graph = _corridor_graph()
    blueprints = _corridor_blueprints(graph)
    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(lateral_band_enabled=False),
    )
    support = result["support_graph"]
    assert support["validation"]["ok"] is True
    assert not [pose for pose in support["poses"] if "lateral" in (pose.get("tags") or [])]
    assert not [edge for edge in support["edges"] if edge["lane"] == "lateral_band"]
    assert support["generation_diagnostics"]["lateral_run_count"] == 0


def test_v4_episodes_blueprint_band_and_global() -> None:
    graph = _corridor_graph()
    blueprints = _corridor_blueprints(graph)
    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_grid(),
        config=_config(max_panorama_poses=2, lateral_switch_interval_steps=1),
    )
    support = result["support_graph"]
    plan = result["observation_plan"]
    poses = {pose["motion_node_id"]: pose for pose in support["poses"]}

    band_episodes = plan_support_episodes(
        support_graph=support, observation_plan=plan,
        num_pairs=5, split_counts={"train": 5},
        min_forward_actions=1, max_forward_actions=6,
        route_scope="blueprint_band",
    )
    assert band_episodes
    for episode in band_episodes:
        validate_support_episode(episode)
        assert episode.metadata["route_scope"] == "blueprint_band"
        assert episode.metadata["derived_from_blueprints"]
    assert any(
        any("lateral" in (poses[pose_id].get("tags") or []) for pose_id in episode.path_nodes)
        for episode in band_episodes
    )

    global_episodes = plan_support_episodes(
        support_graph=support, observation_plan=plan,
        num_pairs=3, split_counts={"train": 3},
        min_forward_actions=1, max_forward_actions=6,
        route_scope="global",
    )
    assert global_episodes
    for episode in global_episodes:
        validate_support_episode(episode)
        assert episode.metadata["route_scope"] == "global"
        assert episode.metadata["blueprint_id"] == "global"
        assert episode.metadata["derived_from_blueprints"]

    with pytest.raises(ValueError, match="route_scope"):
        plan_support_episodes(
            support_graph=support, observation_plan=plan,
            num_pairs=1, split_counts={"train": 1}, route_scope="bogus",
        )


def _large_grid(length_m: float = 20.0) -> TraversabilityGrid:
    """A wide-open grid for corridors longer than the default 5 m ``_grid``."""
    spec = GridSpec(
        origin=[-2.0, -2.0], resolution=0.05, width=int(length_m / 0.05), height=100,
        scene_id="synthetic_navigation_support",
    )
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    return TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))


def test_v4_episodes_min_distance_guarantees_physical_length() -> None:
    graph = _corridor_graph(length_m=6.0)
    blueprints = _corridor_blueprints(graph)
    result = build_navigation_support(
        graph, blueprints, annotation=None, motion_grid=_large_grid(),
        config=_config(lateral_band_enabled=False),
    )
    support = result["support_graph"]
    plan = result["observation_plan"]

    episodes = plan_support_episodes(
        support_graph=support, observation_plan=plan,
        num_pairs=3, split_counts={"train": 3},
        min_forward_actions=1, max_forward_actions=48,
        min_distance_m=5.0,
    )
    assert episodes
    for episode in episodes:
        validate_support_episode(episode)
        assert episode.metadata["path_distance_m"] >= 5.0 - 1e-6
        # Physical length must match the actual trajectory, not just the
        # forward-action count times the nominal step.
        forward_hops = sum(1 for action in episode.actions if action == "move_forward")
        assert episode.metadata["path_distance_m"] <= forward_hops * (0.25 + 0.025) + 1e-6

    # A 6 m corridor cannot contain a 10 m episode.
    with pytest.raises(ValueError, match="distance"):
        plan_support_episodes(
            support_graph=support, observation_plan=plan,
            num_pairs=1, split_counts={"train": 1},
            min_forward_actions=1, max_forward_actions=48,
            min_distance_m=10.0,
        )

    with pytest.raises(ValueError, match="max_distance_m"):
        plan_support_episodes(
            support_graph=support, observation_plan=plan,
            num_pairs=1, split_counts={"train": 1},
            min_distance_m=5.0, max_distance_m=1.0,
        )


def test_sweep_coverage_ladder_is_nested_and_starts_from_episodes() -> None:
    graph = _corridor_graph(length_m=6.0)
    result = build_navigation_support(
        graph, _corridor_blueprints(graph), annotation=None,
        motion_grid=_large_grid(), config=_config(),
    )
    support = result["support_graph"]
    plan = result["observation_plan"]
    episodes = plan_support_episodes(
        support_graph=support, observation_plan=plan, num_pairs=2,
        split_counts={"train": 2}, min_forward_actions=4, max_forward_actions=48,
    )
    rows = [{"path_nodes": e.path_nodes, "path_headings": e.path_headings} for e in episodes]

    previous: set[str] | None = None
    for level_id in SWEEP_COVERAGE_LEVEL_IDS:
        selection = select_sweep_coverage(
            support_graph=support, observation_plan=plan, episodes=rows, level_id=level_id,
        )
        keys = set(selection["view_keys"])
        assert selection["summary"]["level_id"] == level_id
        # Every rung is a subset of the certified L0 plan ...
        assert selection["summary"]["selected_view_count"] <= selection["summary"]["l0_view_count"]
        # ... and contains the rung below it, so a sweep resumes upward
        # without re-rendering anything.
        if previous is not None:
            assert previous <= keys
        previous = keys

    cheapest = select_sweep_coverage(
        support_graph=support, observation_plan=plan, episodes=rows,
        level_id=SWEEP_COVERAGE_LEVEL_IDS[0],
    )
    fullest = select_sweep_coverage(
        support_graph=support, observation_plan=plan, episodes=rows,
        level_id=SWEEP_COVERAGE_LEVEL_IDS[-1],
    )
    assert cheapest["summary"]["episode_view_count"] > 0
    assert cheapest["summary"]["selected_view_count"] < fullest["summary"]["selected_view_count"]
    assert fullest["summary"]["selected_view_count"] == fullest["summary"]["l0_view_count"]
    # Only headings the plan actually offers may be selected.
    offered = {f"{row['motion_node_id']}:{row['heading_id']}" for row in plan["render_entries"]}
    assert set(cheapest["view_keys"]) <= offered

    with pytest.raises(ValueError, match="level_id"):
        select_sweep_coverage(
            support_graph=support, observation_plan=plan, episodes=rows, level_id="bogus",
        )


def test_v4_max_detour_ratio_rejects_sparse_graph_long_way_round() -> None:
    """A pair whose direct route was never materialised must be rejected.

    The corridor lane is straight, so free space and the walked route agree and
    a tight cap keeps every episode; a cap below 1 is refused outright, and the
    cap needs the grid it measures against.
    """
    graph = _corridor_graph(length_m=6.0)
    grid = _large_grid()
    result = build_navigation_support(
        graph, _corridor_blueprints(graph), annotation=None,
        motion_grid=grid, config=_config(),
    )
    support = result["support_graph"]
    plan = result["observation_plan"]

    kept = plan_support_episodes(
        support_graph=support, observation_plan=plan, num_pairs=3,
        split_counts={"train": 3}, min_forward_actions=4, max_forward_actions=48,
        motion_grid=grid, max_detour_ratio=1.5,
    )
    assert kept
    for episode in kept:
        ratio = float(episode.metadata["detour_ratio"])
        free_space = float(episode.metadata["free_space_distance_m"])
        assert ratio <= 1.5 + 1e-9
        assert free_space > 0.0
        # The measured reference is a real free-space distance, so the walked
        # route can never be shorter than it by more than rounding.
        assert float(episode.metadata["path_distance_m"]) >= free_space - 1e-3

    with pytest.raises(ValueError, match="motion_grid"):
        plan_support_episodes(
            support_graph=support, observation_plan=plan, num_pairs=1,
            split_counts={"train": 1}, max_detour_ratio=1.5,
        )
    with pytest.raises(ValueError, match="max_detour_ratio"):
        plan_support_episodes(
            support_graph=support, observation_plan=plan, num_pairs=1,
            split_counts={"train": 1}, motion_grid=grid, max_detour_ratio=0.5,
        )
