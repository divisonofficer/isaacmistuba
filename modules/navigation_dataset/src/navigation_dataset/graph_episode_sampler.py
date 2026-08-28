from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import math
import random
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .episode_schema import EpisodeManifest, EpisodeTimestep, GENERATION_VERSION, write_episode
from .scene_dataset import SceneDatasetPaths
from .instruction_generators import EpisodeCore, InstructionContext, build_instruction_context, generate_instructions
from .rollout import scale_split_counts, split_for_index
from .scene_annotations import SceneAnnotation
from .viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointHeading, ViewpointNode


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
    """Yaw (in the render convention used by `sensor_sweep._mat4_from_xy_yaw`)
    that faces `target` when standing at `source`.

    Render convention:
      * yaw=0  → forward (-sin(yaw), cos(yaw)) = (0, 1) = +y_graph
      * +yaw   → CCW rotation viewed from above (N→W→S→E)

    Hence yaw = atan2(-dx, dy). The previous version returned the math angle
    atan2(dy, dx), which is 90° off and rotates in the opposite direction —
    producing thumbnails where "forward" was sideways and L/R were swapped.
    """
    dx = float(target.position[0]) - float(source.position[0])
    dy = float(target.position[1]) - float(source.position[1])
    return (math.degrees(math.atan2(-dx, dy)) + 360.0) % 360.0


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


def _heading_yaw(node: ViewpointNode, heading_id: str) -> float:
    for heading in node.headings:
        if heading.heading_id == heading_id:
            return float(heading.yaw_deg)
    return 0.0


def _expand_path_with_rotations(
    graph: ViewpointGraph,
    path_nodes: list[str],
    path_headings: list[str],
    *,
    start_heading_id: str | None = None,
    edge_distances: list[float] | None = None,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Expand a node path into per-step primitive actions.

    The agent spawns at ``start_heading_id`` (its initial facing) and, for each
    edge, rotates in place ``step_deg`` (360/heading_count, e.g. 30°) at a time
    until it faces the next node, then drives ``move_forward`` (variable distance)
    to it. Returns ``(node_id, heading_id, action, meta)`` tuples where:

      * ``turn_left_30`` / ``turn_right_30`` — rotation step, ``meta={"turn_deg": ±step}``
      * ``move_forward`` — depart toward the next node, ``meta={"forward_m": dist}``
      * ``stop`` — final pose, ``meta={}``

    Every emitted heading already has a rendered observation (all headings are
    swept), so the sequence is fully observed.
    """
    nodes = _node_map(graph)
    step_deg = 360.0 / float(max(1, graph.node_heading_count or 12))
    n = len(path_nodes)
    steps: list[tuple[str, str, str, dict[str, Any]]] = []
    prev_dep_yaw: float | None = None
    move_index = 0
    for index, node_id in enumerate(path_nodes):
        node = nodes[node_id]
        dep_hid = path_headings[min(index, len(path_headings) - 1)] if path_headings else _nearest_heading_id(node, 0.0)
        dep_yaw = _heading_yaw(node, dep_hid)
        if prev_dep_yaw is not None:
            arr_yaw = prev_dep_yaw                      # faced this way while driving in
        elif start_heading_id is not None:
            arr_yaw = _heading_yaw(node, start_heading_id)  # explicit spawn facing
        else:
            arr_yaw = dep_yaw
        delta = ((dep_yaw - arr_yaw + 180.0) % 360.0) - 180.0
        n_turns = int(round(abs(delta) / step_deg)) if step_deg > 0 else 0
        direction = 1.0 if delta > 0 else -1.0
        turn_token = "turn_left_30" if delta > 0 else "turn_right_30"
        # Pose 0 = arrival heading; poses 1..n_turns rotate toward departure.
        for j in range(n_turns + 1):
            yaw = arr_yaw + direction * step_deg * j
            heading_id = _nearest_heading_id(node, yaw)
            if j < n_turns:
                steps.append((node_id, heading_id, turn_token, {"turn_deg": round(direction * step_deg, 3)}))
            elif index < n - 1:
                dist = float(edge_distances[move_index]) if edge_distances and move_index < len(edge_distances) else 0.0
                steps.append((node_id, heading_id, "move_forward", {"forward_m": round(dist, 4)}))
                move_index += 1
            else:
                steps.append((node_id, heading_id, "stop", {}))
        prev_dep_yaw = dep_yaw
    return steps


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


def _spawn_heading_id(node: ViewpointNode, episode_id: str) -> str:
    """Deterministic per-episode random spawn heading (reproducible from id)."""
    if not node.headings:
        return "h_000"
    idx = int(hashlib.sha1(episode_id.encode("utf-8")).hexdigest(), 16) % len(node.headings)
    return node.headings[idx].heading_id


def _resolve_observation_ref(
    heading: "ViewpointHeading | None",
    *,
    scene_id: str,
    node_id: str,
    heading_id: str,
    observations_root: Path | None,
) -> str | None:
    """Observation ref for a (vp, heading): graph sensor_observations first, then
    the on-disk consolidated observation dir (so episodes stay trainable even when
    the graph was rebuilt and lost its swept refs)."""
    if heading is not None and heading.sensor_observations:
        ref = heading.sensor_observations.get("bundle") or next(iter(heading.sensor_observations.values()), "")
        if ref:
            return ref
    if observations_root is not None:
        obs_dir = Path(observations_root) / node_id / heading_id
        if obs_dir.exists():
            base = f"scenes/{scene_id}/observations/{node_id}/{heading_id}"
            return f"{base}/_sensor_index.json" if (obs_dir / "_sensor_index.json").exists() else base
    return None


def make_graph_episode(
    *,
    episode_id: str,
    split: str,
    graph: ViewpointGraph,
    path: GraphPath,
    scenario: str,
    modalities: list[str],
    annotation: SceneAnnotation | None = None,
    observations_root: Path | None = None,
    instruction_ctx: InstructionContext | None = None,
    use_instruction_llm: bool = False,
) -> EpisodeManifest:
    nodes = _node_map(graph)
    path_headings = _path_headings(graph, path.nodes)
    # Random (deterministic per episode) spawn facing at the start node; the first
    # actions rotate from it toward the first node.
    spawn_heading_id = _spawn_heading_id(nodes[path.nodes[0]], episode_id)
    edge_distances = [float(e.distance_m) for e in path.edges]
    # Expand to per-step primitive actions (turn_*_30 / move_forward / stop).
    # path_nodes / path_headings stay as the node-level summary (one per waypoint);
    # trajectory / timesteps / actions are the executable primitive sequence.
    expanded = _expand_path_with_rotations(
        graph, path.nodes, path_headings, start_heading_id=spawn_heading_id, edge_distances=edge_distances,
    )
    trajectory = []
    timesteps: list[EpisodeTimestep] = []
    observation_refs: list[str] = []
    actions: list[str] = []
    move_count = 0
    for step_index, (node_id, heading_id, action, meta) in enumerate(expanded):
        node = nodes[node_id]
        heading = next((item for item in node.headings if item.heading_id == heading_id), None)
        yaw_rad = math.radians(float(heading.yaw_deg if heading is not None else 0.0))
        pose = [float(node.position[0]), float(node.position[1]), yaw_rad]
        trajectory.append(pose)
        actions.append(action)
        current_ref = _resolve_observation_ref(
            heading, scene_id=graph.scene_id, node_id=node_id, heading_id=heading_id, observations_root=observations_root,
        )
        if current_ref:
            observation_refs.append(current_ref)
        # Map hazard crossing onto the move step that traverses each edge.
        hazard = False
        if action == "move_forward":
            if move_count < len(path.edges):
                hazard = bool(path.edges[move_count].hazard_crossing)
            move_count += 1
        timesteps.append(
            EpisodeTimestep(
                timestep_index=step_index,
                timestamp=float(step_index),
                agent_pose=pose,
                action=action,
                collision=False,
                hazard_collision=hazard,
                observation_bundle_ref=current_ref,
                extras={"node_id": node_id, "heading_id": heading_id, **meta},
            )
        )
    goal_region, goal_label = _nearest_goal_label(annotation, nodes[path.nodes[-1]])
    # Multi-level instruction set (turn-by-turn / landmark / perception / …). The
    # scenario string stays the primary `natural_language_instruction` for
    # back-compat; `instructions` augments it. Built only when a context is given.
    instructions: list[dict] = []
    if instruction_ctx is not None:
        label = goal_label if goal_label not in ("", goal_region) else instruction_ctx.goal_label
        if str(label).strip().lower() in ("goal", "the goal"):
            label = "the goal"
        core = EpisodeCore(
            episode_id=episode_id,
            scenario=scenario,
            path_nodes=list(path.nodes),
            node_xy={n: (float(nodes[n].position[0]), float(nodes[n].position[1])) for n in path.nodes},
            expanded_steps=expanded,
            goal_label=label,
        )
        instructions = generate_instructions(core, instruction_ctx, use_llm=use_instruction_llm)
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
        instructions=instructions,
        metadata={
            "modalities": list(modalities),
            "generation_version": GENERATION_VERSION,
            "scenario": scenario,
            "graph_distance_m": path.distance_m,
            "hazard_crossing": path.hazard_crossing,
            "scene_variant_id": graph.metadata.get("scene_variant_id"),
            "instruction_types": sorted({str(i.get("type")) for i in instructions}),
        },
        navigation_mode="viewpoint_graph",
        graph_id=graph.graph_id,
        start_node=path.nodes[0],
        goal_node=path.nodes[-1],
        path_nodes=list(path.nodes),
        path_headings=path_headings,
        observation_refs=observation_refs,
    )


def _k_shortest_paths(graph: ViewpointGraph, start_node: str, goal_node: str, k: int = 4) -> list[GraphPath]:
    """Yen's-style k-shortest simple paths. Returns at most k paths ordered by distance."""
    if start_node == goal_node:
        return []
    try:
        base = shortest_graph_path(graph, start_node, goal_node)
    except ValueError:
        return []
    results: list[GraphPath] = [base]
    adj = _adjacency(graph)
    candidates: list[tuple[float, list[str], list[ViewpointEdge]]] = []
    seen_node_seqs: set[tuple[str, ...]] = {tuple(base.nodes)}

    for _ in range(k - 1):
        prev_path = results[-1]
        for spur_idx in range(len(prev_path.nodes) - 1):
            spur_node = prev_path.nodes[spur_idx]
            root_nodes = set(prev_path.nodes[:spur_idx + 1])
            # Temporarily remove edges used by paths sharing this root segment
            removed_edges: list[tuple[str, tuple[str, ViewpointEdge]]] = []
            for existing in results:
                if existing.nodes[:spur_idx + 1] == prev_path.nodes[:spur_idx + 1]:
                    # Remove the edge from spur_node to its next node in existing path
                    if spur_idx + 1 < len(existing.nodes):
                        next_nd = existing.nodes[spur_idx + 1]
                        orig = adj.get(spur_node, [])
                        new_list = [(n, e) for n, e in orig if n != next_nd]
                        removed_edges.append((spur_node, orig[0] if orig else None))
                        adj[spur_node] = new_list
                        orig2 = adj.get(next_nd, [])
                        adj[next_nd] = [(n, e) for n, e in orig2 if n != spur_node]
            # Also block root nodes to avoid cycles
            for rn in root_nodes - {spur_node}:
                saved = adj.pop(rn, [])
                removed_edges.append((rn, saved))  # type: ignore[arg-type]

            try:
                spur_path = shortest_graph_path(
                    # Build a temporary graph view — hack: temporarily replace edges
                    graph, spur_node, goal_node
                )
                full_nodes = prev_path.nodes[:spur_idx] + spur_path.nodes
                full_edges = prev_path.edges[:spur_idx] + spur_path.edges
                key = tuple(full_nodes)
                if key not in seen_node_seqs:
                    seen_node_seqs.add(key)
                    dist = sum(float(e.weight) for e in full_edges)
                    hazard = any(e.hazard_crossing for e in full_edges)
                    heapq.heappush(candidates, (dist, full_nodes, full_edges))  # type: ignore[misc]
            except ValueError:
                pass

            # Restore adjacency
            for rn, saved_val in removed_edges:
                if isinstance(saved_val, list):
                    adj[rn] = saved_val
                elif saved_val is not None:
                    adj.setdefault(rn, [])

        if not candidates:
            break
        _, best_nodes, best_edges = heapq.heappop(candidates)
        dist = sum(float(e.weight) for e in best_edges)
        hazard = any(e.hazard_crossing for e in best_edges)
        results.append(GraphPath(nodes=best_nodes, edges=best_edges, distance_m=dist, hazard_crossing=hazard))

    return results


def _path_indirectness(path: GraphPath) -> float:
    """Ratio of path length to straight-line distance. Higher = more indirect (RxR desideratum 2)."""
    if path.distance_m <= 0:
        return 0.0
    return path.distance_m  # use absolute distance; caller normalizes


def _select_coverage_path(candidates: list[GraphPath], node_visit_counts: dict[str, int]) -> GraphPath:
    """Pick the candidate path that best balances indirectness + low-coverage nodes (RxR §3)."""
    if len(candidates) == 1:
        return candidates[0]
    best_path = candidates[0]
    best_score = float("-inf")
    for path in candidates:
        # Term 1: prefer non-shortest (longer relative to straight-line) — use node count as proxy
        indirectness = len(path.nodes)
        # Term 2: prefer paths covering under-visited nodes
        coverage = sum(1.0 / max(1, node_visit_counts.get(n, 0) + 1) for n in path.nodes) / len(path.nodes)
        score = indirectness * 0.4 + coverage * 0.6
        if score > best_score:
            best_score = score
            best_path = path
    return best_path


def plan_graph_episodes(
    *,
    graph: ViewpointGraph,
    num_pairs: int,
    split_counts: dict[str, int],
    scenarios: list[str],
    modalities: list[str],
    annotation: SceneAnnotation | None = None,
    seed: int = 0,
    observations_root: Path | None = None,
    excluded_edge_ids: set[str] | None = None,
    on_progress: "Callable[[int, int, int], None] | None" = None,
    authoring_map: dict | None = None,
    perturbation: dict | None = None,
    use_instruction_llm: bool = False,
) -> list[EpisodeManifest]:
    if num_pairs <= 0:
        raise ValueError("num_pairs must be positive.")
    # Drop edges cut by the optical-perturbation overlay (glass/mirror walls) so the
    # planner never routes an episode path through a sealed passage. Done before the
    # empty-edge check so a fully-blocked graph fails loudly instead of silently
    # planning through glass.
    if excluded_edge_ids:
        from dataclasses import replace
        kept = [edge for edge in graph.edges if edge.edge_id not in excluded_edge_ids]
        graph = replace(graph, edges=kept)
    if not graph.edges:
        raise ValueError("Viewpoint graph has no edges.")
    scenario_cycle = [item for item in scenarios if item] or ["goal_only"]
    unknown = [item for item in scenario_cycle if item not in GRAPH_SCENARIOS]
    if unknown:
        raise ValueError(f"Unsupported graph scenarios: {unknown}")
    rng = random.Random(seed)
    split_counts = scale_split_counts(split_counts, num_pairs)
    # Build the per-scene instruction context once (rooms/objects/mirrors); reused
    # for every episode. Cheap and side-effect free; degrades gracefully when
    # authoring_map / perturbation are absent.
    instruction_ctx = build_instruction_context(graph, annotation, authoring_map, perturbation)
    node_ids = sorted(node.node_id for node in graph.nodes)
    # Track how many times each node appears in accepted episodes (for coverage scoring)
    node_visit_counts: dict[str, int] = {}
    episodes: list[EpisodeManifest] = []
    attempts = 0
    while len(episodes) < num_pairs and attempts < num_pairs * 20:
        attempts += 1
        if on_progress is not None:
            on_progress(len(episodes), num_pairs, attempts)
        start, goal = rng.sample(node_ids, 2)
        # Generate a small pool of alternative paths and pick by coverage score (RxR §3)
        candidates = _k_shortest_paths(graph, start, goal, k=3)
        if not candidates:
            continue
        index = len(episodes)
        scenario = scenario_cycle[index % len(scenario_cycle)]
        # Filter candidates by scenario constraint
        valid = [p for p in candidates if not (scenario == "hazard_aware" and p.hazard_crossing)]
        if not valid:
            continue
        path = _select_coverage_path(valid, node_visit_counts)
        if len(path.nodes) < 2:
            continue
        # Update coverage counts
        for n in path.nodes:
            node_visit_counts[n] = node_visit_counts.get(n, 0) + 1
        split = split_for_index(split_counts, index)
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
                observations_root=observations_root,
                instruction_ctx=instruction_ctx,
                use_instruction_llm=use_instruction_llm,
            )
        )
    return episodes


def write_graph_episodes(root: str | Path, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    rows = list(episodes)
    if not rows:
        return []
    scene_ids = {episode.scene_id for episode in rows}
    if len(scene_ids) != 1:
        raise ValueError("write_graph_episodes requires one scene; use explicit multi-scene orchestration")
    return write_scene_graph_episodes(SceneDatasetPaths.from_project(root, scene_ids.pop()), rows)


def write_scene_graph_episodes(paths: SceneDatasetPaths, episodes: Iterable[EpisodeManifest]) -> list[Path]:
    """Scene-local counterpart to :func:`write_graph_episodes`."""
    return [paths.write_episode(episode) for episode in episodes]


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def graph_episode_stale_refs(
    episode: Mapping[str, Any],
    *,
    node_ids: set[str],
    edge_pairs: set[tuple[str, str]],
    disabled_pairs: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Report graph references in ``episode`` that the current graph no longer satisfies.

    A viewpoint-graph episode bakes in a node path (``path_nodes``); after the user
    deletes nodes/edges (or a glass/mirror overlay disables an edge) that path may
    traverse something that no longer exists. Rather than re-scan on every edit, this
    is run on demand (the editor's "validate episodes" step) over each episode.

    Returns ``{"stale", "reasons", "missing_nodes", "missing_edges", "disabled_edges"}``.
    Non-graph episodes (``navigation_mode != 'viewpoint_graph'``) are never stale.
    """
    disabled_pairs = disabled_pairs or set()
    result: dict[str, Any] = {
        "stale": False, "reasons": [],
        "missing_nodes": [], "missing_edges": [], "disabled_edges": [],
    }
    if str(episode.get("navigation_mode") or "") != "viewpoint_graph":
        return result
    path_nodes = [str(n) for n in (episode.get("path_nodes") or [])]
    # endpoints referenced directly (start/goal) are covered by path_nodes too, but
    # check them explicitly so a malformed/empty path is still caught.
    for extra in (episode.get("start_node"), episode.get("goal_node")):
        if extra and str(extra) not in path_nodes:
            path_nodes.append(str(extra))

    missing_nodes = [n for n in path_nodes if n not in node_ids]
    if missing_nodes:
        result["missing_nodes"] = sorted(set(missing_nodes))
        result["reasons"].append("missing_nodes")

    seq = [str(n) for n in (episode.get("path_nodes") or [])]
    for a, b in zip(seq, seq[1:]):
        if a not in node_ids or b not in node_ids:
            continue  # already reported as a missing node
        pair = _pair(a, b)
        if pair not in edge_pairs:
            result["missing_edges"].append([a, b])
        elif pair in disabled_pairs:
            result["disabled_edges"].append([a, b])
    if result["missing_edges"]:
        result["reasons"].append("missing_edges")
    if result["disabled_edges"]:
        result["reasons"].append("disabled_edges")

    result["stale"] = bool(result["reasons"])
    return result
