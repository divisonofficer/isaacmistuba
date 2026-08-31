from __future__ import annotations

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
    archive_navigation_support,
    build_support_observation_expansion,
    build_navigation_support,
    delete_route_blueprint,
    latest_support_render_archive,
    plan_support_episodes,
    propose_route_blueprints,
    read_route_blueprints,
    read_support_observation_plan,
    recover_l0_observation_plan_from_expansion,
    support_observation_expansion_filename,
    update_route_blueprint,
    validate_navigation_support,
    write_navigation_support,
    write_support_observation_expansion,
    _major_trunk_edges,
)
from navigation_dataset.traversability import GridSpec, TraversabilityGrid, world_to_cell
from navigation_dataset.viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointHeading, ViewpointNode
from navigation_dataset.route_motion import _v3_portal_aware_grid


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


def test_v4_requires_approved_route_blueprint() -> None:
    with pytest.raises(ValueError, match="approve at least one"):
        build_navigation_support(
            _place_graph(),
            propose_route_blueprints(_place_graph(), config=DEFAULT_CONFIG),
            annotation=None,
            motion_grid=_grid(),
            config=_config(),
        )


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
    assert all(0.225 <= float(edge["distance_m"]) <= 0.275 for edge in support["edges"])
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


def test_v4_defers_unapproved_central_trunk_edges() -> None:
    graph = _place_graph()
    blueprints = _approved_blueprints(graph)
    approved = next(row for row in blueprints["blueprints"] if row["status"] == "approved")

    executable, diagnostics = _major_trunk_edges(graph, blueprints["blueprints"], None, _config())

    assert executable == set(approved["place_path_edge_ids"])
    assert diagnostics["deferred_unapproved_trunk_edge_count"] >= 0


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
