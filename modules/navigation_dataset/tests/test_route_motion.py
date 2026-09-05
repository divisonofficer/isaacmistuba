from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from navigation_dataset.route_motion import (
    DEFAULT_CONFIG,
    _action_grid_path,
    _build_observation_plan,
    _grid_segment_safe,
    _merged_config,
    _yaw_to,
    _world_segment_safe,
    build_adaptive_route_motion,
    build_anchor_spanner,
    expand_motion_route_actions,
    make_motion_route_episode,
    motion_render_graph_from_plan,
    plan_motion_route_episodes,
    validate_adaptive_route_motion_v3,
)
from navigation_dataset.traversability import GridSpec, TraversabilityGrid, cell_to_world, world_to_cell
from navigation_dataset.scene_annotations import GoalRegion, HazardRegion, SceneAnnotation, TraversableRegion
from navigation_dataset.viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointHeading, ViewpointNode


def _node(node_id: str, x: float, y: float) -> ViewpointNode:
    return ViewpointNode(
        node_id=node_id,
        position=[x, y, 0.0],
        headings=[ViewpointHeading(f"h_{i * 15:03d}", i * 15.0) for i in range(24)],
    )


def _edge(edge_id: str, source: str, target: str, distance: float, **extras) -> ViewpointEdge:
    return ViewpointEdge(
        edge_id=edge_id,
        source=source,
        target=target,
        distance_m=distance,
        weight=distance,
        collision_free=True,
        extras=extras,
    )


def _graph() -> ViewpointGraph:
    # A-B-C is a safe 0.25 m action chain. B-C is an inferred, open doorway.
    nodes = [_node("a", 0.0, 0.0), _node("b", 0.5, 0.0), _node("c", 0.75, 0.0), _node("d", 0.75, 0.5)]
    return ViewpointGraph(
        scene_id="synthetic",
        graph_id="synthetic_anchor",
        node_heading_count=24,
        nodes=nodes,
        edges=[
            _edge("ab", "a", "b", 0.5, edge_validation={"mode": "normal", "wall_run_cells": 0}),
            _edge(
                "bc", "b", "c", 0.25,
                portal="door_1",
                portal_source="inferred",
                portal_type="inferred_opening",
                edge_validation={"mode": "doorway", "wall_run_cells": 0},
            ),
            _edge("cd", "c", "d", 0.5, edge_validation={"mode": "normal", "wall_run_cells": 0}),
            _edge("ad", "a", "d", math.hypot(0.75, 0.5), edge_validation={"mode": "normal", "wall_run_cells": 0}),
        ],
    )


def _annotation() -> SceneAnnotation:
    return SceneAnnotation(
        scene_id="synthetic",
        traversable_regions=[
            TraversableRegion("room_a", {"type": "box", "bounds": [-0.1, -0.1, 0.3, 0.3]}),
            TraversableRegion("room_b", {"type": "box", "bounds": [0.4, -0.1, 0.9, 0.6]}),
        ],
        goal_regions=[GoalRegion("goal", [0.75, 0.5])],
        hazard_regions=[HazardRegion("hazard", "glass", {"type": "circle", "center": [0.75, 0.0], "radius": 0.1})],
    )


def _motion_grid() -> TraversabilityGrid:
    """Clearance-eroded synthetic room containing the whole anchor topology."""
    spec = GridSpec(origin=[-1.0, -1.0], resolution=0.05, width=80, height=80, scene_id="synthetic")
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    return TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))


def test_anchor_spanner_keeps_connectivity_and_only_safe_existing_edges():
    source = _graph()
    spanner = build_anchor_spanner(source)

    assert {edge.edge_id for edge in spanner.edges} <= {edge.edge_id for edge in source.edges}
    assert len(spanner.edges) >= len(source.nodes) - 1
    assert spanner.metadata["anchor_spanner"]["stretch"] == 1.2


def test_adaptive_route_motion_uses_025_actions_and_partial_observation_contract():
    config = {
        **DEFAULT_CONFIG,
        "max_motion_poses": 20,
        "max_full_sweep_poses": 3,
        "max_polar_observations": 120,
        "max_polar_batches": 32,
        "max_requests": 8,
    }
    progress: list[tuple[str, float]] = []
    result = build_adaptive_route_motion(
        _graph(),
        annotation=_annotation(),
        config=config,
        motion_grid=_motion_grid(),
        on_progress=lambda stage, fraction, _detail: progress.append((stage, fraction)),
    )
    motion = result["motion_graph"]
    plan = result["observation_plan"]

    assert len(motion["nodes"]) <= 20
    for edge in motion["edges"]:
        assert 0.225 <= edge["distance_m"] <= 0.275
        assert edge["collision_free"] is True
    assert any(edge["edge_type"] == "portal_bridge" for edge in motion["edges"])
    assert plan["summary"]["polar_observation_count"] <= 120
    assert plan["summary"]["polar_batch_count"] <= 32
    for pose in plan["poses"]:
        if pose["tier"] == "FULL_24":
            assert len(pose["available_heading_ids"]) == 24
        elif pose["tier"] == "TRACK_4":
            assert len(pose["available_heading_ids"]) == 4
            assert pose["lazy_heading_ids"]
        else:
            assert pose["tier"] == "TRACK_REQUIRED"
            assert len(pose["available_heading_ids"]) > 4
            assert set(pose["required_action_heading_ids"]) <= set(pose["available_heading_ids"])
    assert {"anchor_spanner", "action_lattice", "action_backbone", "validation", "observation_plan"} <= {stage for stage, _fraction in progress}
    assert progress[-1] == ("complete", 1.0)


def test_motion_render_graph_has_all_action_headings_but_plan_is_allow_list():
    result = build_adaptive_route_motion(
        _graph(), annotation=_annotation(),
        config={**DEFAULT_CONFIG, "max_motion_poses": 20, "max_full_sweep_poses": 3}, motion_grid=_motion_grid(),
    )
    graph = motion_render_graph_from_plan(result["observation_plan"])

    assert graph.node_heading_count == 24
    assert all(len(node.headings) == 24 for node in graph.nodes)
    assert len(result["observation_plan"]["render_entries"]) < len(graph.nodes) * 24


def test_full_24_gold_poses_are_globally_separated_by_at_least_015m():
    """A close action pose remains TRACK_4 instead of becoming another gold ring."""
    motion = {
        "nodes": [
            {"motion_node_id": "pose_a", "position": [0.0, 0.0, 0.0], "route_heading_ids": ["h_000"]},
            {"motion_node_id": "pose_b", "position": [0.10, 0.0, 0.0], "route_heading_ids": ["h_000"]},
            {"motion_node_id": "pose_c", "position": [0.30, 0.0, 0.0], "route_heading_ids": ["h_000"]},
        ],
        "edges": [],
    }
    plan = _build_observation_plan(
        motion,
        [],
        _merged_config({
            "max_full_sweep_poses": 3,
            "min_full_sweep_spacing_m": 0.15,
            "max_polar_observations": 100,
            "max_polar_batches": 30,
        }),
    )
    full = [pose for pose in plan["poses"] if pose["tier"] == "FULL_24"]

    assert {pose["motion_node_id"] for pose in full} == {"pose_a", "pose_c"}
    assert plan["panoramic_core"]["min_pose_spacing_m"] == 0.15
    assert all(
        math.dist(left["position"][:2], right["position"][:2]) >= 0.15 - 1e-9
        for index, left in enumerate(full)
        for right in full[index + 1:]
    )


def test_motion_expander_emits_15_degree_turns_and_safe_forward_distances():
    result = build_adaptive_route_motion(_graph(), annotation=_annotation(), config={**DEFAULT_CONFIG, "max_motion_poses": 20}, motion_grid=_motion_grid())
    route_id = result["motion_graph"]["routes"][0]["request_id"]
    steps = expand_motion_route_actions(result["motion_graph"], route_id, initial_heading_id="h_090")

    assert steps[-1]["action"] == "stop"
    for step in steps:
        if step["action"] in {"turn_left", "turn_right"}:
            assert abs(step["extras"]["turn_deg"]) == 15.0
        if step["action"] == "move_forward" and step["extras"]["edge_type"] == "forward":
            assert 0.225 <= step["extras"]["forward_m"] <= 0.275


def test_v3_validator_requires_certified_portal_crossing_in_the_route_sequence():
    result = build_adaptive_route_motion(
        _graph(), annotation=_annotation(),
        config={**DEFAULT_CONFIG, "max_motion_poses": 20}, motion_grid=_motion_grid(),
    )
    motion = result["motion_graph"]
    assert validate_adaptive_route_motion_v3(motion, motion_grid=_motion_grid())["ok"] is True

    broken = copy.deepcopy(motion)
    portal_route = next(route for route in broken["routes"] if route["portal_ids"])
    transitions = {transition["transition_id"]: transition for transition in broken["transitions"]}
    for transition_id in portal_route["primary"]["transition_ids"]:
        transitions[transition_id]["portal_ids"] = []
    with pytest.raises(ValueError, match="route_portal_bypass"):
        validate_adaptive_route_motion_v3(broken, motion_grid=_motion_grid())


def test_v3_routes_share_the_same_physical_backbone_edges():
    result = build_adaptive_route_motion(
        _graph(), annotation=_annotation(),
        config={**DEFAULT_CONFIG, "max_motion_poses": 20}, motion_grid=_motion_grid(),
    )
    motion = result["motion_graph"]
    route_edge_references = [
        edge_id
        for route in motion["routes"]
        for edge_id in route["primary"]["motion_edge_ids"]
    ]
    assert len(route_edge_references) > len(set(route_edge_references))
    assert set(route_edge_references) <= {edge["motion_edge_id"] for edge in motion["edges"]}


def test_motion_episode_uses_v3_action_metadata_and_declares_partial_headings():
    result = build_adaptive_route_motion(
        _graph(), annotation=_annotation(),
        config={**DEFAULT_CONFIG, "max_motion_poses": 20, "max_full_sweep_poses": 3}, motion_grid=_motion_grid(),
    )
    route_id = result["motion_graph"]["routes"][0]["request_id"]
    episode = make_motion_route_episode(
        episode_id="adaptive_synthetic_0001",
        split="train",
        motion_graph=result["motion_graph"],
        observation_plan=result["observation_plan"],
        route_id=route_id,
    )

    assert episode.navigation_mode == "adaptive_route_motion_v3"
    assert episode.actions[-1] == "stop"
    for timestep in episode.timesteps:
        assert timestep.extras["heading_id"] in timestep.extras["available_heading_ids"]
        if timestep.action in {"turn_left", "turn_right"}:
            assert abs(timestep.extras["turn_deg"]) == 15.0
        if timestep.action == "move_forward" and timestep.extras["edge_type"] == "forward":
            assert 0.225 <= timestep.extras["forward_m"] <= 0.275


def test_every_selected_route_has_its_action_heading_observed():
    result = build_adaptive_route_motion(
        _graph(), annotation=_annotation(),
        config={**DEFAULT_CONFIG, "max_motion_poses": 20, "max_full_sweep_poses": 1}, motion_grid=_motion_grid(),
    )
    for index, route in enumerate(result["motion_graph"]["routes"]):
        episode = make_motion_route_episode(
            episode_id=f"adaptive_synthetic_{index:04d}",
            split="train",
            motion_graph=result["motion_graph"],
            observation_plan=result["observation_plan"],
            route_id=route["request_id"],
        )
        for timestep in episode.timesteps:
            assert timestep.extras["heading_id"] in timestep.extras["available_heading_ids"]
            if timestep.action == "move_forward":
                assert 0.225 <= timestep.extras["forward_m"] <= 0.275


def test_motion_episode_planner_keeps_routes_distinct_and_rejects_duplication():
    result = build_adaptive_route_motion(
        _graph(), annotation=_annotation(),
        config={**DEFAULT_CONFIG, "max_motion_poses": 20, "max_full_sweep_poses": 1}, motion_grid=_motion_grid(),
    )
    count = len(result["motion_graph"]["routes"])
    episodes = plan_motion_route_episodes(
        motion_graph=result["motion_graph"],
        observation_plan=result["observation_plan"],
        navigation_requests=result["navigation_requests"],
        num_pairs=count,
        split_counts={"train": 1},
        seed=3,
    )
    assert len(episodes) == count
    assert len({episode.metadata["route_id"] for episode in episodes}) == count
    assert all(episode.navigation_mode == "adaptive_route_motion_v3" for episode in episodes)
    with pytest.raises(ValueError, match="distinct executable routes"):
        plan_motion_route_episodes(
            motion_graph=result["motion_graph"],
            observation_plan=result["observation_plan"],
            navigation_requests=result["navigation_requests"],
            num_pairs=count + 1,
            split_counts={"train": 1},
        )


def test_unreachable_terminals_are_deferred_without_creating_an_unsafe_bridge():
    """The connected core is usable while a sealed terminal stays advisory-only."""
    base = _motion_grid()
    traversable = base.traversable.copy()
    # A wide horizontal wall isolates node d.  The smaller seed radius avoids
    # treating a nearby pose on the other side of that wall as the terminal.
    _, row_start = world_to_cell(base.spec, 0.0, 0.15)
    _, row_end = world_to_cell(base.spec, 0.0, 0.40)
    traversable[row_start : row_end + 1, :] = False
    sealed_grid = TraversabilityGrid(
        spec=base.spec,
        traversable=traversable,
        hazard=base.hazard,
    )
    result = build_adaptive_route_motion(
        _graph(),
        annotation=_annotation(),
        config={
            **DEFAULT_CONFIG,
            "max_motion_poses": 40,
            "coverage_seed_search_radius_m": 0.12,
            "unreachable_terminal_policy": "defer",
        },
        motion_grid=sealed_grid,
    )

    diagnostics = result["generation_diagnostics"]
    assert diagnostics["coverage_status"] == "partial"
    assert diagnostics["unreachable_terminal_ids"] == ["d"]
    assert diagnostics["backbone_component_count"] == 1
    detached = diagnostics["detached_terminal_subgraphs"]
    assert detached[0]["anchor_node_ids"] == ["d"]
    assert detached[0]["nearest_reachable_motion_pose_id"] in {
        node["motion_node_id"] for node in result["motion_graph"]["nodes"]
    }
    assert all(edge["distance_m"] <= 0.275 for edge in result["motion_graph"]["edges"])
    assert all(route["goal_anchor_id"] != "d" for route in result["motion_graph"]["routes"])
    with pytest.raises(ValueError, match="coverage is incomplete"):
        plan_motion_route_episodes(
            motion_graph=result["motion_graph"],
            observation_plan=result["observation_plan"],
            navigation_requests=result["navigation_requests"],
            num_pairs=1,
            split_counts={"train": 1},
        )
    episodes = plan_motion_route_episodes(
        motion_graph=result["motion_graph"],
        observation_plan=result["observation_plan"],
        navigation_requests=result["navigation_requests"],
        num_pairs=1,
        split_counts={"train": 1},
        allow_incomplete_coverage=True,
    )
    assert len(episodes) == 1
    assert episodes[0].metadata["coverage_status"] == "partial"
    assert episodes[0].metadata["allow_incomplete_coverage"] is True
    with pytest.raises(ValueError, match="action_terminal_unreachable:d"):
        build_adaptive_route_motion(
            _graph(),
            annotation=_annotation(),
            config={
                **DEFAULT_CONFIG,
                "max_motion_poses": 40,
                "coverage_seed_search_radius_m": 0.12,
                "unreachable_terminal_policy": "reject",
            },
            motion_grid=sealed_grid,
        )


def test_clearance_grid_action_search_turns_without_short_chord_or_wall_crossing():
    """A 90 degree corridor must not produce the old inside-corner short hop."""
    spec = GridSpec(origin=[0.0, 0.0], resolution=0.05, width=24, height=24, scene_id="synthetic")
    traversable = np.zeros((spec.height, spec.width), dtype=bool)
    # A five-cell-wide L corridor.  This is already a clearance-eroded mask:
    # every true cell is a legal robot-centre location.
    traversable[2:8, 2:17] = True
    traversable[2:17, 12:18] = True
    grid = TraversabilityGrid(spec=spec, traversable=traversable, hazard=traversable.copy())
    start = cell_to_world(spec, 4, 4)
    goal = cell_to_world(spec, 14, 14)
    guide = [start, cell_to_world(spec, 14, 4), goal]

    path = _action_grid_path(grid, start, goal, _merged_config(), guide=guide)

    assert path is not None and len(path) >= 2
    for source, target in zip(path, path[1:]):
        distance = math.dist(source, target)
        assert 0.225 <= distance <= 0.275
        yaw_deg = _yaw_to(source, target)
        assert math.isclose(yaw_deg / 15.0, round(yaw_deg / 15.0), abs_tol=1e-6)
        assert _grid_segment_safe(grid, world_to_cell(spec, *source), world_to_cell(spec, *target))


@pytest.mark.parametrize(
    ("target", "expected_yaw"),
    [
        ((0.0, 1.0), 0.0),
        ((1.0, 0.0), 90.0),
        ((0.0, -1.0), 180.0),
        ((-1.0, 0.0), 270.0),
    ],
)
def test_motion_heading_matches_canonical_camera_forward(target: tuple[float, float], expected_yaw: float):
    """A route heading must point in the same direction as the rendered camera."""
    yaw = _yaw_to((0.0, 0.0), target)
    assert math.isclose(yaw, expected_yaw, abs_tol=1e-9)
    assert math.isclose(math.sin(math.radians(yaw)), target[0], abs_tol=1e-9)
    assert math.isclose(math.cos(math.radians(yaw)), target[1], abs_tol=1e-9)


def test_action_grid_path_keeps_an_exact_single_forward_primitive():
    """A 25 cm portal-like link must yield one move, not a zero-step path."""
    spec = GridSpec(origin=[0.0, 0.0], resolution=0.05, width=32, height=32, scene_id="single_step")
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    grid = TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))
    start = cell_to_world(spec, 10, 10)
    goal = cell_to_world(spec, 15, 10)

    path = _action_grid_path(grid, start, goal, _merged_config(), guide=[start, goal], exact_start=True)

    assert path == [start, goal]
    assert math.isclose(math.dist(path[0], path[1]), 0.25, abs_tol=1e-9)


def test_action_grid_path_near_terminal_still_emits_one_forward_primitive():
    """Terminal tolerance is not permission to omit a required portal move."""
    spec = GridSpec(origin=[0.0, 0.0], resolution=0.05, width=40, height=40, scene_id="near_terminal")
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    grid = TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))
    start = (0.50, 0.50)
    # 22.8 cm away: the direct vector is not an exact 15-degree primitive,
    # but a 315-degree 25 cm action lands within the permitted terminal band.
    goal = (0.6625, 0.34)

    path = _action_grid_path(grid, start, goal, _merged_config(), guide=[start, goal], exact_start=True)

    assert path is not None and len(path) == 2
    assert math.isclose(math.dist(path[0], path[1]), 0.25, abs_tol=1e-9)
    assert math.dist(path[-1], goal) <= 0.25


def test_v3_keeps_continuous_pose_coordinates_after_safety_validation():
    """Rounding a safe lattice chord must not flip it into the next grid cell.

    This is the exact failure mode behind ``unsafe_forward`` on the 0824 office:
    the action search certified its continuous coordinates, then a ten-decimal
    serialization rounded a point across a 5 cm occupancy boundary.
    """
    origin_y = 0.5122336366577123
    spec = GridSpec(origin=[0.6533999655761717, origin_y], resolution=0.05, width=16, height=300, scene_id="precision")
    traversable = np.ones((spec.height, spec.width), dtype=bool)
    traversable[123, :] = False
    grid = TraversabilityGrid(spec=spec, traversable=traversable, hazard=np.zeros_like(traversable))
    safe_y = origin_y + 123 * spec.resolution - 1e-12
    source = [0.78, safe_y, 0.0]
    target = [0.98, safe_y, 0.0]

    assert _world_segment_safe(grid, source, target)
    rounded_source = [round(source[0], 10), round(source[1], 10), 0.0]
    rounded_target = [round(target[0], 10), round(target[1], 10), 0.0]
    assert not _world_segment_safe(grid, rounded_source, rounded_target)
