from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
import random
from pathlib import Path
from typing import Iterable

from .episode_schema import EpisodeManifest, EpisodeTimestep, GENERATION_VERSION, write_episode
from .rollout import split_for_index
from .scene_annotations import SceneAnnotation
from .viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointNode


GRAPH_SCENARIOS = ("goal_only", "hazard_aware", "stop_before_glass", "detour")


@dataclass(frozen=True)
class GraphPath:
    nodes: list[str]
    edges: list[ViewpointEdge]
    distance_m: float
    hazard_crossing: bool


def _node_map(graph: ViewpointGraph) -> dict[str, ViewpointNode]:
    return {node.node_id: node for node in graph.nodes}


def _adjacency(graph: ViewpointGraph) -> dict[str, list[tuple[str, ViewpointEdge]]]:
    adj: dict[str, list[tuple[str, ViewpointEdge]]] = {node.node_id: [] for node in graph.nodes}
    for edge in graph.edges:
        adj.setdefault(edge.source, []).append((edge.target, edge))
        adj.setdefault(edge.target, []).append((edge.source, edge))
    for values in adj.values():
        values.sort(key=lambda item: (item[1].weight, item[0]))
    return adj


def shortest_graph_path(graph: ViewpointGraph, start_node: str, goal_node: str) -> GraphPath:
    if start_node == goal_node:
        return GraphPath(nodes=[start_node], edges=[], distance_m=0.0, hazard_crossing=False)
    adj = _adjacency(graph)
    if start_node not in adj or goal_node not in adj:
        raise ValueError(f"Unknown graph start/goal: {start_node}/{goal_node}")
    heap: list[tuple[float, str]] = [(0.0, start_node)]
    dist = {start_node: 0.0}
    previous: dict[str, tuple[str, ViewpointEdge]] = {}
    while heap:
        cost, node_id = heapq.heappop(heap)
        if node_id == goal_node:
            break
        if cost > dist.get(node_id, math.inf):
            continue
        for neighbor, edge in adj.get(node_id, []):
            next_cost = cost + float(edge.weight)
            if next_cost < dist.get(neighbor, math.inf):
                dist[neighbor] = next_cost
                previous[neighbor] = (node_id, edge)
                heapq.heappush(heap, (next_cost, neighbor))
    if goal_node not in dist:
        raise ValueError(f"No graph path found from {start_node} to {goal_node}.")
    nodes = [goal_node]
    edges: list[ViewpointEdge] = []
    cursor = goal_node
    while cursor != start_node:
        parent, edge = previous[cursor]
        edges.append(edge)
        nodes.append(parent)
        cursor = parent
    nodes.reverse()
    edges.reverse()
    return GraphPath(
        nodes=nodes,
        edges=edges,
        distance_m=float(dist[goal_node]),
        hazard_crossing=any(edge.hazard_crossing for edge in edges),
    )


def _nearest_heading_id(node: ViewpointNode, yaw_deg: float) -> str:
    if not node.headings:
        return "h_000"
    target = yaw_deg % 360.0
    return min(node.headings, key=lambda heading: abs(((heading.yaw_deg - target + 180.0) % 360.0) - 180.0)).heading_id


def _edge_heading(source: ViewpointNode, target: ViewpointNode) -> float:
    dx = float(target.position[0]) - float(source.position[0])
    dy = float(target.position[1]) - float(source.position[1])
    return (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0


def _path_headings(graph: ViewpointGraph, path_nodes: list[str]) -> list[str]:
    nodes = _node_map(graph)
    headings: list[str] = []
    for index, node_id in enumerate(path_nodes):
        node = nodes[node_id]
        if index + 1 < len(path_nodes):
            yaw = _edge_heading(node, nodes[path_nodes[index + 1]])
        elif headings:
            headings.append(headings[-1])
            continue
        else:
            yaw = 0.0
        headings.append(_nearest_heading_id(node, yaw))
    return headings


def _actions_for_headings(path_nodes: list[str], path_headings: list[str], graph: ViewpointGraph) -> list[str]:
    actions: list[str] = []
    node_lookup = _node_map(graph)
    heading_yaw = {
        (node.node_id, heading.heading_id): float(heading.yaw_deg)
        for node in graph.nodes
        for heading in node.headings
    }
    previous_yaw: float | None = None
    for index, node_id in enumerate(path_nodes[:-1]):
        heading_id = path_headings[index]
        yaw = heading_yaw.get((node_id, heading_id), 0.0)
        if previous_yaw is not None:
            delta = ((yaw - previous_yaw + 180.0) % 360.0) - 180.0
            steps = int(round(delta / 30.0))
            token = "turn_left_30" if steps > 0 else "turn_right_30"
            actions.extend([token] * abs(steps))
        actions.append("move_to_neighbor")
        previous_yaw = yaw
        node_lookup[node_id]  # keep KeyError behavior for corrupt paths
    actions.append("stop")
    return actions


def _scenario_instruction(scenario: str, annotation: SceneAnnotation | None, goal_label: str) -> str:
    hazard_label = "transparent partition"
    if annotation is not None and annotation.hazard_regions:
        hazard_label = annotation.hazard_regions[0].hazard_type.replace("_", " ")
    if scenario == "hazard_aware":
        return f"Go to {goal_label} without crossing the {hazard_label}."
    if scenario == "stop_before_glass":
        return f"Move toward {goal_label} and stop before the {hazard_label}."
    if scenario == "detour":
        return f"Go to {goal_label} by taking the safe detour around the {hazard_label}."
    return f"Go to {goal_label}."


def _nearest_goal_label(annotation: SceneAnnotation | None, node: ViewpointNode) -> tuple[str, str]:
    if annotation is None or not annotation.goal_regions:
        return node.node_id, node.node_id
    best = min(
        annotation.goal_regions,
        key=lambda goal: math.hypot(float(goal.center[0]) - float(node.position[0]), float(goal.center[1]) - float(node.position[1])),
    )
    return best.region_id, best.label or best.region_id


def make_graph_episode(
    *,
    episode_id: str,
    split: str,
    graph: ViewpointGraph,
    path: GraphPath,
    scenario: str,
    modalities: list[str],
    annotation: SceneAnnotation | None = None,
) -> EpisodeManifest:
    nodes = _node_map(graph)
    path_headings = _path_headings(graph, path.nodes)
    actions = _actions_for_headings(path.nodes, path_headings, graph)
    trajectory = []
    timesteps: list[EpisodeTimestep] = []
    observation_refs: list[str] = []
    for index, node_id in enumerate(path.nodes):
        node = nodes[node_id]
        heading_id = path_headings[min(index, len(path_headings) - 1)]
        heading = next((item for item in node.headings if item.heading_id == heading_id), None)
        yaw_rad = math.radians(float(heading.yaw_deg if heading is not None else 0.0))
        pose = [float(node.position[0]), float(node.position[1]), yaw_rad]
        trajectory.append(pose)
        current_ref = None
        if heading is not None:
            ref = heading.sensor_observations.get("bundle") or next(iter(heading.sensor_observations.values()), "")
            if ref:
                current_ref = ref
                observation_refs.append(ref)
        timesteps.append(
            EpisodeTimestep(
                timestep_index=index,
                timestamp=float(index),
                agent_pose=pose,
                action="stop" if index == len(path.nodes) - 1 else "move_to_neighbor",
                collision=False,
                hazard_collision=bool(path.edges[index].hazard_crossing) if index < len(path.edges) else False,
                observation_bundle_ref=current_ref,
            )
        )
    goal_region, goal_label = _nearest_goal_label(annotation, nodes[path.nodes[-1]])
    return EpisodeManifest(
        episode_id=episode_id,
        scene_id=graph.scene_id,
        split=split,
        start_pose=trajectory[0],
        goal_pose=trajectory[-1],
        goal_region=goal_region,
        natural_language_instruction=_scenario_instruction(scenario, annotation, goal_label),
        trajectory=trajectory,
        actions=actions,
        timesteps=timesteps,
        metadata={
            "modalities": list(modalities),
            "generation_version": GENERATION_VERSION,
            "scenario": scenario,
            "graph_distance_m": path.distance_m,
            "hazard_crossing": path.hazard_crossing,
            "scene_variant_id": graph.metadata.get("scene_variant_id"),
        },
        navigation_mode="viewpoint_graph",
        graph_id=graph.graph_id,
        start_node=path.nodes[0],
        goal_node=path.nodes[-1],
        path_nodes=list(path.nodes),
        path_headings=path_headings,
        observation_refs=observation_refs,
    )


def plan_graph_episodes(
    *,
    graph: ViewpointGraph,
    num_pairs: int,
    split_counts: dict[str, int],
    scenarios: list[str],
    modalities: list[str],
    annotation: SceneAnnotation | None = None,
    seed: int = 0,
) -> list[EpisodeManifest]:
    if num_pairs <= 0:
        raise ValueError("num_pairs must be positive.")
    if not graph.edges:
        raise ValueError("Viewpoint graph has no edges.")
    scenario_cycle = [item for item in scenarios if item] or ["goal_only"]
    unknown = [item for item in scenario_cycle if item not in GRAPH_SCENARIOS]
    if unknown:
        raise ValueError(f"Unsupported graph scenarios: {unknown}")
    rng = random.Random(seed)
    node_ids = sorted(node.node_id for node in graph.nodes)
    episodes: list[EpisodeManifest] = []
    attempts = 0
    while len(episodes) < num_pairs and attempts < num_pairs * 20:
        attempts += 1
        start, goal = rng.sample(node_ids, 2)
        try:
            path = shortest_graph_path(graph, start, goal)
        except ValueError:
            continue
        if len(path.nodes) < 2:
            continue
        index = len(episodes)
        split = split_for_index(split_counts, index)
        scenario = scenario_cycle[index % len(scenario_cycle)]
        if scenario == "hazard_aware" and path.hazard_crossing:
            continue
        episode_id = f"{graph.scene_id}_{split}_graph_{index + 1:06d}"
        episodes.append(
            make_graph_episode(
                episode_id=episode_id,
                split=split,
                graph=graph,
                path=path,
                scenario=scenario,
                modalities=modalities,
                annotation=annotation,
            )
        )
    return episodes


def write_graph_episodes(root: str | Path, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    dataset_root = Path(root)
    written: list[Path] = []
    for episode in episodes:
        path = dataset_root / "episodes" / episode.split / f"{episode.episode_id}.json"
        written.append(write_episode(path, episode))
    return written
