"""Route-union motion and selective-observation planning for OpticalNav.

The legacy viewpoint graph is intentionally a *place graph*: it is sparse enough
to make global route selection inexpensive, but its edges are not an action
space.  This module keeps that distinction explicit.  It derives a second graph
only for routes that were selected for coverage, and attaches an observation plan
to the resulting motion poses.  No legacy graph, episode, or observation file is
modified by these helpers.

The file formats are deliberately JSON-only sidecars.  They can therefore be
audited, regenerated, and submitted independently of the renderer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha1
import json
import math
import os
from pathlib import Path
import random
import threading
from typing import Any, Callable, Iterable, Mapping, Sequence

from .graph_episode_sampler import GraphPath, shortest_graph_path
from .scene_annotations import SceneAnnotation
from .traversability import TraversabilityGrid, cell_to_world, world_to_cell
from .viewpoint_graph import ViewpointEdge, ViewpointGraph, ViewpointHeading, ViewpointNode, viewpoint_graph_to_payload


PROFILE_ID = "adaptive_route_motion_v3"
SCHEMA_VERSION = "opticalnav.adaptive_route_motion.v3"
DEFAULT_CONFIG: dict[str, Any] = {
    "profile_id": PROFILE_ID,
    "heading_count": 24,
    "turn_deg": 15.0,
    "forward_step_m": 0.25,
    "forward_tolerance_m": 0.025,
    "robot_radius_m": 0.25,
    "safety_margin_m": 0.10,
    "geometry_epsilon_m": 0.03,
    "max_anchor_nodes": 300,
    "max_motion_poses": 600,
    "max_action_states": 2400,
    "max_full_sweep_poses": 80,
    # Gold FULL_24 markers are a sparse panoramic core.  Keep them farther
    # apart than the 5 cm grid/preview noise, without changing the 0.25 m
    # action lattice or dropping TRACK_4 action observations.
    "min_full_sweep_spacing_m": 0.15,
    "max_polar_observations": 4000,
    "max_polar_batches": 1000,
    "max_requests": 96,
    # ``defer`` persists the connected, collision-certified backbone and
    # reports terminals that could not join it.  ``reject`` remains available
    # for audit runs that require all requested terminals to be executable.
    "unreachable_terminal_policy": "defer",
    "min_request_context_m": 2.0,
    "coverage_seed_search_radius_m": 0.75,
    "spanner_stretch": 1.20,
    "heading_render_seconds": 30.24,
}


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return path


def _merged_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    for key, value in dict(config or {}).items():
        if value is not None:
            merged[key] = value
    merged["heading_count"] = int(merged["heading_count"])
    merged["max_anchor_nodes"] = int(merged["max_anchor_nodes"])
    merged["max_motion_poses"] = int(merged["max_motion_poses"])
    merged["max_action_states"] = int(merged["max_action_states"])
    merged["max_full_sweep_poses"] = int(merged["max_full_sweep_poses"])
    merged["min_full_sweep_spacing_m"] = float(merged["min_full_sweep_spacing_m"])
    merged["max_polar_observations"] = int(merged["max_polar_observations"])
    merged["max_polar_batches"] = int(merged["max_polar_batches"])
    merged["max_requests"] = int(merged["max_requests"])
    merged["forward_step_m"] = float(merged["forward_step_m"])
    merged["forward_tolerance_m"] = float(merged["forward_tolerance_m"])
    merged["turn_deg"] = float(merged["turn_deg"])
    merged["min_request_context_m"] = float(merged["min_request_context_m"])
    merged["coverage_seed_search_radius_m"] = float(merged["coverage_seed_search_radius_m"])
    merged["effective_clearance_m"] = round(
        float(merged["robot_radius_m"])
        + float(merged["safety_margin_m"])
        + float(merged["geometry_epsilon_m"]),
        4,
    )
    if merged["heading_count"] != 24 or not math.isclose(360.0 / merged["heading_count"], merged["turn_deg"], abs_tol=1e-6):
        raise ValueError("adaptive_route_motion_v3 requires 24 headings / 15 degree turns")
    if merged["forward_step_m"] <= 0 or merged["forward_tolerance_m"] < 0:
        raise ValueError("forward_step_m must be positive and forward_tolerance_m non-negative")
    if merged["min_full_sweep_spacing_m"] < 0:
        raise ValueError("min_full_sweep_spacing_m must be non-negative")
    merged["unreachable_terminal_policy"] = str(
        merged.get("unreachable_terminal_policy") or "defer"
    ).strip().lower()
    if merged["unreachable_terminal_policy"] not in {"defer", "reject"}:
        raise ValueError("unreachable_terminal_policy must be 'defer' or 'reject'")
    return merged


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _yaw_to(a: Sequence[float], b: Sequence[float]) -> float:
    """Return the canonical camera yaw which faces ``b`` from ``a``.

    ``resolve_viewpoint_pose`` defines camera forward in authoring-floor
    coordinates as ``(sin(yaw), cos(yaw))``.  Keeping this helper in that same
    convention is essential: a sign flip on X makes east/west motion render
    with a 180-degree reversed camera heading.
    """
    return (math.degrees(math.atan2(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))) + 360.0) % 360.0


def _heading_id(yaw_deg: float, heading_count: int = 24) -> str:
    step = 360.0 / float(heading_count)
    value = int(round((float(yaw_deg) % 360.0) / step)) % heading_count
    return f"h_{int(round(value * step)) % 360:03d}"


def _all_heading_ids(heading_count: int) -> list[str]:
    return [_heading_id(index * 360.0 / heading_count, heading_count) for index in range(heading_count)]


def _edge_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _adjacency(graph: ViewpointGraph, *, blocked_edge_ids: set[str] | None = None) -> dict[str, list[tuple[str, ViewpointEdge]]]:
    blocked = blocked_edge_ids or set()
    result: dict[str, list[tuple[str, ViewpointEdge]]] = {node.node_id: [] for node in graph.nodes}
    for edge in graph.edges:
        if edge.edge_id in blocked or not edge.collision_free:
            continue
        result.setdefault(edge.source, []).append((edge.target, edge))
        result.setdefault(edge.target, []).append((edge.source, edge))
    for entries in result.values():
        entries.sort(key=lambda item: (float(item[1].weight), item[0], item[1].edge_id))
    return result


def _shortest_without_edges(graph: ViewpointGraph, start: str, goal: str, blocked: set[str]) -> GraphPath | None:
    """Dijkstra variant used only to retain one genuinely different route option."""
    import heapq

    if start == goal:
        return GraphPath(nodes=[start], edges=[], distance_m=0.0, hazard_crossing=False)
    adj = _adjacency(graph, blocked_edge_ids=blocked)
    queue: list[tuple[float, str]] = [(0.0, start)]
    dist = {start: 0.0}
    previous: dict[str, tuple[str, ViewpointEdge]] = {}
    while queue:
        cost, node_id = heapq.heappop(queue)
        if node_id == goal:
            break
        if cost > dist.get(node_id, math.inf):
            continue
        for neighbour, edge in adj.get(node_id, []):
            next_cost = cost + float(edge.weight)
            if next_cost < dist.get(neighbour, math.inf):
                dist[neighbour] = next_cost
                previous[neighbour] = (node_id, edge)
                heapq.heappush(queue, (next_cost, neighbour))
    if goal not in dist:
        return None
    nodes = [goal]
    edges: list[ViewpointEdge] = []
    cursor = goal
    while cursor != start:
        parent, edge = previous[cursor]
        nodes.append(parent)
        edges.append(edge)
        cursor = parent
    nodes.reverse()
    edges.reverse()
    return GraphPath(nodes=nodes, edges=edges, distance_m=float(dist[goal]), hazard_crossing=any(edge.hazard_crossing for edge in edges))


def build_anchor_spanner(graph: ViewpointGraph, *, stretch: float = 1.20) -> ViewpointGraph:
    """Return a deterministic safe sparse spanner of an already validated graph.

    The mesh-aware graph builder owns collision checking.  This pass never invents
    an edge: it first keeps an MST for connectivity, then restores an existing safe
    edge only when the current route is more than ``stretch`` longer.  Portal edges
    get one extra chance so a distinct doorway/homotopy is not accidentally erased.
    """
    from dataclasses import replace

    nodes = list(graph.nodes)
    parent = {node.node_id: node.node_id for node in nodes}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: str, b: str) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[rb] = ra
        return True

    candidates = sorted(
        (edge for edge in graph.edges if edge.collision_free),
        key=lambda edge: (float(edge.weight), edge.edge_id),
    )
    kept: list[ViewpointEdge] = []
    kept_ids: set[str] = set()
    for edge in candidates:
        if union(edge.source, edge.target):
            kept.append(edge)
            kept_ids.add(edge.edge_id)

    def retained_path(a: str, b: str) -> float:
        provisional = ViewpointGraph(
            scene_id=graph.scene_id,
            graph_id=graph.graph_id,
            node_heading_count=graph.node_heading_count,
            nodes=nodes,
            edges=kept,
        )
        try:
            return shortest_graph_path(provisional, a, b).distance_m
        except ValueError:
            return math.inf

    portal_pairs: set[tuple[str, str]] = set()
    for edge in candidates:
        if edge.edge_id in kept_ids:
            if (edge.extras or {}).get("portal"):
                portal_pairs.add(_edge_key(edge.source, edge.target))
            continue
        path_length = retained_path(edge.source, edge.target)
        portal = bool((edge.extras or {}).get("portal"))
        distinct_portal = portal and _edge_key(edge.source, edge.target) not in portal_pairs
        if path_length > float(stretch) * float(edge.weight) or distinct_portal:
            kept.append(edge)
            kept_ids.add(edge.edge_id)
            if portal:
                portal_pairs.add(_edge_key(edge.source, edge.target))
    return replace(
        graph,
        edges=list(kept),
        metadata={
            **dict(graph.metadata or {}),
            "anchor_spanner": {
                "method": "mst_plus_stretch_safe_edges",
                "stretch": float(stretch),
                "input_edge_count": len(graph.edges),
                "edge_count": len(kept),
            },
        },
    )


def _geometry_center(geometry: Mapping[str, Any]) -> tuple[float, float] | None:
    kind = str(geometry.get("type") or "box")
    if kind == "box":
        values = geometry.get("bounds")
        if isinstance(values, Sequence) and len(values) >= 4:
            return ((float(values[0]) + float(values[2])) / 2.0, (float(values[1]) + float(values[3])) / 2.0)
    if kind == "circle":
        values = geometry.get("center")
        if isinstance(values, Sequence) and len(values) >= 2:
            return (float(values[0]), float(values[1]))
    if kind == "polygon":
        points = geometry.get("points")
        if isinstance(points, Sequence) and points:
            xs = [float(point[0]) for point in points if isinstance(point, Sequence) and len(point) >= 2]
            ys = [float(point[1]) for point in points if isinstance(point, Sequence) and len(point) >= 2]
            if xs and ys:
                return (sum(xs) / len(xs), sum(ys) / len(ys))
    return None


def _nearest_node(nodes: Iterable[ViewpointNode], point: Sequence[float]) -> ViewpointNode | None:
    return min(nodes, key=lambda node: _distance(node.position, point), default=None)


def _component_index(graph: ViewpointGraph) -> dict[str, int]:
    result: dict[str, int] = {}
    component = 0
    adjacency = _adjacency(graph)
    for node in sorted(adjacency):
        if node in result:
            continue
        stack = [node]
        result[node] = component
        while stack:
            cursor = stack.pop()
            for neighbour, _edge in adjacency.get(cursor, []):
                if neighbour not in result:
                    result[neighbour] = component
                    stack.append(neighbour)
        component += 1
    return result


def _role_nodes(graph: ViewpointGraph, annotation: SceneAnnotation | None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return feature→anchor ids and anchor→feature ids for request selection."""
    feature_nodes: dict[str, set[str]] = defaultdict(set)
    node_features: dict[str, set[str]] = defaultdict(set)

    def add(feature: str, node: ViewpointNode | None) -> None:
        if node is None:
            return
        feature_nodes[feature].add(node.node_id)
        node_features[node.node_id].add(feature)

    if annotation is not None:
        for region in annotation.traversable_regions:
            if region.traversable:
                add(f"room:{region.region_id}", _nearest_node(graph.nodes, _geometry_center(region.geometry) or (0.0, 0.0)))
        for goal in annotation.goal_regions:
            add(f"goal:{goal.region_id}", _nearest_node(graph.nodes, goal.center))
        # Imported Infinigen scenes can emit tens of mesh fragments for one
        # semantic optical phenomenon (for this office, 147 fragments collapse
        # to two useful types).  Route catalogue coverage is a *scenario*
        # requirement, not a promise to drive to every glass triangle; grouping
        # by hazard type keeps the request budget meaningful while still
        # requiring a representative observation route for every declared type.
        hazard_centres: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for hazard in annotation.hazard_regions:
            centre = _geometry_center(hazard.geometry)
            if centre is not None:
                hazard_centres[str(hazard.hazard_type)].append(centre)
        for hazard_type, centres in sorted(hazard_centres.items()):
            # One medoid-like representative per semantic type prevents an
            # imported glass wall split into 70 meshes from multiplying the
            # request catalogue.  The closest graph node remains a real safe
            # observation position, rather than a synthetic average pose.
            cx = sum(point[0] for point in centres) / len(centres)
            cy = sum(point[1] for point in centres) / len(centres)
            representative = min(centres, key=lambda point: _distance(point, (cx, cy)))
            add(f"hazard:{hazard_type}", _nearest_node(graph.nodes, representative))
        for landmark in annotation.landmarks:
            if landmark.goal_candidate:
                add(f"landmark:{landmark.landmark_id}", _nearest_node(graph.nodes, landmark.center))
    for edge in graph.edges:
        portal_id = (edge.extras or {}).get("portal")
        if portal_id:
            feature = f"portal:{portal_id}"
            source = next((node for node in graph.nodes if node.node_id == edge.source), None)
            target = next((node for node in graph.nodes if node.node_id == edge.target), None)
            add(feature, source)
            add(feature, target)
    # Junctions, portal-adjacent points, and hazard-adjacent points remain
    # important FULL_24 candidates (their tags are carried into the motion
    # graph), but they are not individual catalogue coverage obligations.  A
    # dense Infinigen graph can otherwise create hundreds of pseudo-features and
    # make the fixed 600-pose budget impossible by construction.
    # A scene with no annotation still receives bounded open-space coverage anchors.
    if not feature_nodes and graph.nodes:
        for node in sorted(graph.nodes, key=lambda item: item.node_id)[: min(12, len(graph.nodes))]:
            add(f"coverage:{node.node_id}", node)
    return feature_nodes, node_features


def _edge_points(graph: ViewpointGraph, edge: ViewpointEdge) -> list[tuple[float, float]]:
    nodes = {node.node_id: node for node in graph.nodes}
    source = nodes[edge.source].position
    target = nodes[edge.target].position
    points = [(float(source[0]), float(source[1]))]
    for point in edge.path_polyline or []:
        if len(point) >= 2:
            candidate = (float(point[0]), float(point[1]))
            if _distance(points[-1], candidate) > 1e-7:
                points.append(candidate)
    final = (float(target[0]), float(target[1]))
    if _distance(points[-1], final) > 1e-7:
        points.append(final)
    return points


def _interpolate_polyline(points: Sequence[tuple[float, float]], segments: int) -> list[tuple[float, float]]:
    if len(points) < 2 or segments <= 0:
        return list(points)
    lengths = [_distance(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 1e-9:
        return [points[0]]
    output = [points[0]]
    cursor = 0
    prior = 0.0
    for index in range(1, segments):
        target = total * index / segments
        while cursor < len(lengths) - 1 and prior + lengths[cursor] < target:
            prior += lengths[cursor]
            cursor += 1
        length = lengths[cursor]
        if length <= 1e-9:
            point = points[cursor]
        else:
            ratio = (target - prior) / length
            a, b = points[cursor], points[cursor + 1]
            point = (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)
        output.append(point)
    output.append(points[-1])
    return output


def _edge_portal_id(edge: ViewpointEdge) -> str:
    """Return the portal id a place edge crosses, or "" when it crosses none.

    The id is the ``portal`` extra written by the place-graph builder; every
    other portal predicate in this module reads the same key.
    """
    portal_id = (edge.extras or {}).get("portal")
    return str(portal_id) if portal_id else ""


def _portal_is_open(edge: ViewpointEdge) -> bool:
    extras = dict(edge.extras or {})
    if not extras.get("portal"):
        return False
    state = str(extras.get("portal_state") or extras.get("semantic_state") or "").strip().lower()
    if state == "open" or extras.get("open") is True:
        return True
    source = str(extras.get("portal_source") or "").lower()
    portal_type = str(extras.get("portal_type") or "")
    # An inferred opening is geometry-certified from an actual body-height gap;
    # unlike a declared door mesh it has no closed-state ambiguity. A user
    # certified opening takes the same route only after the server retained its
    # wall-free / short raw-floor-gap certificate on the place edge.
    if source == "inferred" and portal_type == "inferred_opening":
        return True
    manual = extras.get("manual_opening")
    return (
        source == "user_certified"
        and portal_type == "manual_opening"
        and isinstance(manual, Mapping)
        and manual.get("certified") is True
    )


def _edge_motion_template(graph: ViewpointGraph, edge: ViewpointEdge, config: Mapping[str, Any]) -> tuple[list[tuple[float, float]], str, str | None] | tuple[None, None, str]:
    """Return sampled points, type, rejection reason for one certified anchor edge."""
    if not edge.collision_free:
        return None, None, "anchor_edge_not_collision_free"
    validation = (edge.extras or {}).get("edge_validation") or {}
    if isinstance(validation, Mapping) and validation.get("wall_run_cells") not in (None, 0):
        return None, None, "body_height_wall_run"
    points = _edge_points(graph, edge)
    total = sum(_distance(a, b) for a, b in zip(points, points[1:]))
    if total <= 1e-7:
        return None, None, "zero_length_anchor_edge"
    if (edge.extras or {}).get("portal"):
        if not _portal_is_open(edge):
            return None, None, "portal_not_explicitly_open"
        # A certified doorway is still part of the action space.  The old code
        # preserved it as one 0.85--1.0 m ``move_forward`` transition, which
        # silently defeated the 0.25 m rollout contract.  A straight threshold
        # may be split only when every child chord stays in tolerance.  If the
        # two threshold anchors cannot be expressed this way, leave the portal
        # out of the action graph and report it as a geometry/action-resolution
        # incompatibility instead of emitting a physically false transition.
        target = float(config["forward_step_m"])
        tolerance = float(config["forward_tolerance_m"])
        yaw = _yaw_to(points[0], points[-1])
        heading_step = 360.0 / float(config["heading_count"])
        if not math.isclose(yaw / heading_step, round(yaw / heading_step), abs_tol=1e-6):
            return None, None, "portal_not_aligned_to_action_heading"
        count = max(1, int(round(total / target)))
        step = total / count
        if not (target - tolerance - 1e-9 <= step <= target + tolerance + 1e-9):
            return None, None, f"portal_not_representable_at_{target:.2f}m"
        return _interpolate_polyline(points, count), "portal_bridge", None
    target = float(config["forward_step_m"])
    tolerance = float(config["forward_tolerance_m"])
    count = max(1, int(round(total / target)))
    step = total / count
    if not (target - tolerance - 1e-9 <= step <= target + tolerance + 1e-9):
        return None, None, f"edge_not_representable_at_{target:.2f}m"
    return _interpolate_polyline(points, count), "forward", None


def _guide_distance(point: tuple[float, float], guide: Sequence[tuple[float, float]]) -> float:
    """Distance to a graph-certified route polyline (for local action A*)."""
    if len(guide) <= 1:
        return _distance(point, guide[0]) if guide else math.inf
    best = math.inf
    px, py = point
    for start, end in zip(guide, guide[1:]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            best = min(best, _distance(point, start))
            continue
        t = max(0.0, min(1.0, ((px - start[0]) * dx + (py - start[1]) * dy) / denom))
        best = min(best, math.hypot(px - (start[0] + t * dx), py - (start[1] + t * dy)))
    return best


def _motion_step_offsets(grid: TraversabilityGrid, config: Mapping[str, Any]) -> list[tuple[int, int, float]]:
    """Grid deltas whose physical displacement is one legal forward action."""
    resolution = float(grid.spec.resolution)
    minimum = float(config["forward_step_m"]) - float(config["forward_tolerance_m"])
    maximum = float(config["forward_step_m"]) + float(config["forward_tolerance_m"])
    radius = int(math.ceil(maximum / resolution))
    values: list[tuple[int, int, float]] = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            distance_m = math.hypot(dx * resolution, dy * resolution)
            if minimum - 1e-9 <= distance_m <= maximum + 1e-9:
                values.append((dx, dy, distance_m))
    # Cardinal moves first makes otherwise equal paths stable and visually less
    # noisy, while diagonal offsets retain reachability around bends.
    values.sort(key=lambda item: (abs(item[0]) + abs(item[1]) != max(abs(item[0]), abs(item[1])), item[1], item[0]))
    return values


def _grid_segment_safe(grid: TraversabilityGrid, source: tuple[int, int], target: tuple[int, int]) -> bool:
    """Super-sample a short action chord against the already clearance-eroded grid."""
    dx, dy = target[0] - source[0], target[1] - source[1]
    samples = max(abs(dx), abs(dy)) * 3 + 1
    for index in range(samples + 1):
        ratio = index / max(1, samples)
        x = int(round(source[0] + dx * ratio))
        y = int(round(source[1] + dy * ratio))
        if not (0 <= x < grid.spec.width and 0 <= y < grid.spec.height and bool(grid.traversable[y, x])):
            return False
    return True


def _nearest_safe_cell(grid: TraversabilityGrid, point: tuple[float, float]) -> tuple[int, int] | None:
    """Nearest safe grid cell, with a bounded search rather than a full-grid scan."""
    sx, sy = world_to_cell(grid.spec, point[0], point[1])
    sx = max(0, min(grid.spec.width - 1, sx))
    sy = max(0, min(grid.spec.height - 1, sy))
    if bool(grid.traversable[sy, sx]):
        return sx, sy
    for radius in range(1, 41):  # 2m at the standard 5cm resolution
        for y in range(max(0, sy - radius), min(grid.spec.height, sy + radius + 1)):
            for x in range(max(0, sx - radius), min(grid.spec.width, sx + radius + 1)):
                if max(abs(x - sx), abs(y - sy)) == radius and bool(grid.traversable[y, x]):
                    return x, y
    return None


def _world_segment_safe(
    grid: TraversabilityGrid,
    source: tuple[float, float],
    target: tuple[float, float],
) -> bool:
    """Validate a continuous action chord on the clearance-eroded grid."""
    distance_m = _distance(source, target)
    samples = max(1, int(math.ceil(distance_m / max(1e-6, float(grid.spec.resolution) / 3.0))))
    for index in range(samples + 1):
        ratio = index / samples
        point = (
            source[0] + (target[0] - source[0]) * ratio,
            source[1] + (target[1] - source[1]) * ratio,
        )
        x, y = world_to_cell(grid.spec, *point)
        if not (0 <= x < grid.spec.width and 0 <= y < grid.spec.height and bool(grid.traversable[y, x])):
            return False
    return True


def _action_grid_path(
    grid: TraversabilityGrid,
    start_point: tuple[float, float],
    goal_point: tuple[float, float],
    config: Mapping[str, Any],
    *,
    guide: Sequence[tuple[float, float]],
    exact_start: bool = False,
    exact_goal: bool = False,
) -> list[tuple[float, float]] | None:
    """Find legal 0.25m action chords near a certified anchor route.

    A graph edge may contain a tiny repair connector or a right-angle turn.  A
    raw polyline resample either emits a sub-0.25m action or cuts the inside of
    the corner.  This bounded A* operates directly on the same clearance-eroded
    grid used for graph nodes, and every transition is one legal action chord.
    The graph route is used as a corridor guide; it is not treated as a straight
    line that can cut through a wall.
    """
    import heapq

    start = _nearest_safe_cell(grid, start_point)
    goal = _nearest_safe_cell(grid, goal_point)
    if start is None or goal is None:
        return None
    resolution = float(grid.spec.resolution)
    corridor_radius = max(
        0.40,
        float(config.get("action_corridor_radius_m", float(config["forward_step_m"]) * 1.6)),
    )
    step_m = float(config["forward_step_m"])
    # The policy's forward primitive is not merely a distance: it follows one
    # of the 24 15-degree headings.  Grid-cell deltas such as (4, 3) are close
    # to 37 degrees but are not a legal 15-degree action.  Search continuous
    # poses while using the clearance grid solely for collision validation.
    heading_deltas = [
        (-math.sin(math.radians(index * 15.0)) * step_m, math.cos(math.radians(index * 15.0)) * step_m)
        for index in range(int(config["heading_count"]))
    ]
    allowed_cache: dict[tuple[int, int], bool] = {}

    def allowed(point: tuple[float, float], *, endpoint: bool = False) -> bool:
        cell = world_to_cell(grid.spec, *point)
        cached = allowed_cache.get(cell)
        if cached is not None:
            return cached and (endpoint or _guide_distance(point, guide) <= corridor_radius)
        x, y = cell
        if not (0 <= x < grid.spec.width and 0 <= y < grid.spec.height and bool(grid.traversable[y, x])):
            allowed_cache[cell] = False
            return False
        allowed_cache[cell] = True
        return endpoint or _guide_distance(point, guide) <= corridor_radius

    # v4 support construction grows one canonical action lattice outward from
    # an already-emitted pose.  Preserve that exact pose when requested so a
    # local connector cannot silently start a few centimetres away and create
    # a disconnected lattice phase.  Existing v3 callers retain the raster
    # centre behaviour by default.
    start_point = tuple(start_point) if exact_start else cell_to_world(grid.spec, *start)
    goal_point = tuple(goal_point) if exact_goal else cell_to_world(grid.spec, *goal)
    if not (allowed(start_point, endpoint=True) and allowed(goal_point, endpoint=True)):
        return None

    # Anchor coordinates are sampled on a 5 cm raster while actions live on a
    # 15-degree 25 cm lattice. Requiring an exact anchor landing can make a
    # perfectly safe room/goal route unreachable solely from phase mismatch.
    # End within one forward primitive; all actual transitions remain fixed
    # length and collision-checked. The selected route is still labelled with
    # the original anchor feature for coverage accounting.
    # An anchor patch must land on the caller's exact pose, not merely within
    # one action of it: it exists to reconcile two lattice phases, and a
    # relaxed landing would leave the very gap it is meant to close.
    goal_radius_m = 1e-7 if exact_goal else float(config["forward_step_m"])

    # A place edge can already be one exact forward primitive (most notably a
    # 25 cm portal threshold).  The relaxed terminal radius below exists only
    # to absorb lattice *phase* at longer, non-aligned anchors.  Applying it
    # to an exact legal chord makes the start state satisfy ``goal_reached``
    # immediately, yielding a one-pose path.  V4 quite rightly rejects that
    # as a missing action transition.  Preserve the actual primitive when it
    # is an exact member of the 15-degree action set.
    direct_delta = (goal_point[0] - start_point[0], goal_point[1] - start_point[1])
    direct_distance = _distance(start_point, goal_point)
    min_step = step_m - float(config["forward_tolerance_m"])
    max_step = step_m + float(config["forward_tolerance_m"])
    if min_step - 1e-9 <= direct_distance <= max_step + 1e-9:
        action_epsilon = max(1e-7, resolution * 1e-5)
        if any(math.hypot(direct_delta[0] - dx, direct_delta[1] - dy) <= action_epsilon for dx, dy in heading_deltas):
            if _world_segment_safe(grid, start_point, goal_point):
                return [start_point, goal_point]

    def goal_reached(point: tuple[float, float]) -> bool:
        return _distance(point, goal_point) <= goal_radius_m + 1e-9

    def heuristic(point: tuple[float, float]) -> float:
        # The final action state is intentionally allowed to land within half
        # a particular grid residue makes an otherwise valid 15-degree action
        # lattice disconnected in a corridor.
        return max(0.0, _distance(point, goal_point) - goal_radius_m)

    # Quantise only the A* closed-set key (1/4 grid-cell).  Stored poses remain
    # continuous so every emitted vector has an exact 15 degree direction.
    def point_key(point: tuple[float, float]) -> tuple[int, int]:
        return (
            int(round((point[0] - float(grid.spec.origin[0])) / resolution * 4.0)),
            int(round((point[1] - float(grid.spec.origin[1])) / resolution * 4.0)),
        )

    start_key = point_key(start_point)
    queue: list[tuple[float, float, tuple[int, int]]] = [(heuristic(start_point), 0.0, start_key)]
    cost = {start_key: 0.0}
    positions = {start_key: start_point}
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    expansions = 0
    max_expansions = max(30_000, int(math.ceil(_distance(start_point, goal_point) / step_m)) * 400)
    while queue and expansions < max_expansions:
        _priority, current_cost, current_key = heapq.heappop(queue)
        current = positions[current_key]
        if current_cost > cost.get(current_key, math.inf) + 1e-9:
            continue
        # ``goal_radius_m`` permits a final action state near a sparse place
        # anchor, but it must never turn an already-near *start* pose into a
        # zero-action corridor.  That occurred when the preceding canonical
        # lattice phase stopped 22.8 cm before a 25 cm portal threshold: the
        # portal path consisted of one pose and V4 rejected it.  Expand at
        # least one legal 0.25 m chord; the next pose may then satisfy the
        # same terminal tolerance without introducing a short action.
        if current_key != start_key and goal_reached(current):
            keys = [current_key]
            while current_key in previous:
                current_key = previous[current_key]
                keys.append(current_key)
            keys.reverse()
            return [positions[key] for key in keys]
        expansions += 1
        for dx, dy in heading_deltas:
            neighbour = (current[0] + dx, current[1] + dy)
            if not allowed(neighbour) or not _world_segment_safe(grid, current, neighbour):
                continue
            neighbour_key = point_key(neighbour)
            next_cost = current_cost + step_m
            if next_cost + 1e-9 < cost.get(neighbour_key, math.inf):
                cost[neighbour_key] = next_cost
                positions[neighbour_key] = neighbour
                previous[neighbour_key] = current_key
                heapq.heappush(queue, (next_cost + heuristic(neighbour), next_cost, neighbour_key))
    return None


def _path_template(
    graph: ViewpointGraph,
    path: GraphPath,
    config: Mapping[str, Any],
    *,
    motion_grid: TraversabilityGrid | None = None,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Convert a safe anchor path into fixed-distance action primitives.

    Anchor edges are planning conveniences, not actions.  In particular, mesh
    graph repair may add a 5 cm connector immediately before a normal 1.2 m
    corridor edge.  Rejecting that connector by itself made every long route
    disappear.  We therefore re-sample each *continuous non-portal run* as a
    whole; portal thresholds remain explicit special primitives.
    """
    steps: list[dict[str, Any]] = []
    rejected: list[str] = []
    normal_edges: list[tuple[ViewpointEdge, list[tuple[float, float]]]] = []

    def flush_normal_run() -> None:
        nonlocal normal_edges
        if not normal_edges:
            return
        points: list[tuple[float, float]] = []
        edge_ids: list[str] = []
        for normal_edge, raw_points in normal_edges:
            sampled_points, _kind, reason = _edge_motion_template(graph, normal_edge, config)
            # ``edge_not_representable`` is expected for a short anchor
            # fragment.  The aggregate route run below is what must satisfy
            # the 0.25 m action tolerance; all other rejections are unsafe.
            if reason and reason != f"edge_not_representable_at_{float(config['forward_step_m']):.2f}m":
                rejected.append(f"{normal_edge.edge_id}:{reason}")
                normal_edges = []
                return
            for point in raw_points:
                if not points or _distance(points[-1], point) > 1e-7:
                    points.append(point)
            edge_ids.append(normal_edge.edge_id)
        if motion_grid is not None:
            grid_points = _action_grid_path(motion_grid, points[0], points[-1], config, guide=points)
            if not grid_points or len(grid_points) < 2:
                rejected.append(f"{','.join(edge_ids)}:safe_action_lattice_unreachable")
                normal_edges = []
                return
            for source, target_point in zip(grid_points, grid_points[1:]):
                steps.append({
                    "source": source,
                    "target": target_point,
                    "kind": "forward",
                    "anchor_edge_ids": list(edge_ids),
                })
            normal_edges = []
            return
        # Legacy/no-grid callers retain the old straight-run behaviour.  New
        # Infinigen builds always take the action-grid branch above.
        # Never make one action straddle a sharp bend.  The chord of a 0.25 m
        # polyline interval around a 90° corner is shorter and can cut through
        # the wall; it was the source of the observed 0.15–0.22 m "forward"
        # actions.  Split at changes of direction, while retaining collinear
        # anchor fragments in the same action run.
        linear_runs: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        prior_direction: tuple[float, float] | None = None
        for start, end in zip(points, points[1:]):
            length = _distance(start, end)
            if length <= 1e-7:
                continue
            direction = ((end[0] - start[0]) / length, (end[1] - start[1]) / length)
            same_direction = (
                prior_direction is not None
                and abs(prior_direction[0] * direction[1] - prior_direction[1] * direction[0]) <= 1e-5
                and prior_direction[0] * direction[0] + prior_direction[1] * direction[1] > 0.9999
            )
            if not current:
                current = [start, end]
            elif same_direction:
                current.append(end)
            else:
                linear_runs.append(current)
                current = [start, end]
            prior_direction = direction
        if current:
            linear_runs.append(current)
        target = float(config["forward_step_m"])
        tolerance = float(config["forward_tolerance_m"])
        for linear_points in linear_runs:
            total = sum(_distance(a, b) for a, b in zip(linear_points, linear_points[1:]))
            count = max(1, int(round(total / target)))
            action_step = total / count
            if not (target - tolerance <= action_step <= target + tolerance):
                rejected.append(
                    f"{','.join(edge_ids)}:straight_run_not_representable_at_{target:.2f}m"
                )
                normal_edges = []
                return
            run_points = _interpolate_polyline(linear_points, count)
            for source, target_point in zip(run_points, run_points[1:]):
                steps.append({
                    "source": source,
                    "target": target_point,
                    "kind": "forward",
                    "anchor_edge_ids": list(edge_ids),
                })
        normal_edges = []

    for edge_index, edge in enumerate(path.edges):
        raw_points = _edge_points(graph, edge)
        # Graph edges are stored undirected.  Their source/target order need
        # not match the Dijkstra path direction, so orient the safe polyline
        # before concatenating route runs or producing a doorway primitive.
        if edge_index < len(path.nodes) - 1 and edge.source != path.nodes[edge_index]:
            raw_points.reverse()
        if not (edge.extras or {}).get("portal"):
            normal_edges.append((edge, raw_points))
            continue
        flush_normal_run()
        if rejected:
            return None, rejected
        points, kind, reason = _edge_motion_template(graph, edge, config)
        if points is None:
            rejected.append(f"{edge.edge_id}:{reason}")
            continue
        if raw_points and points and _distance(points[0], raw_points[0]) > 1e-7:
            points = list(reversed(points))
        for source, target in zip(points, points[1:]):
            steps.append({
                "source": source,
                "target": target,
                "kind": kind,
                "anchor_edge_ids": [edge.edge_id],
            })
    flush_normal_run()
    return (steps if not rejected else None), rejected


def _path_portal_signature(path: GraphPath) -> tuple[str, ...]:
    return tuple(sorted(str((edge.extras or {}).get("portal")) for edge in path.edges if (edge.extras or {}).get("portal")))


def _coverage_seed_steps(
    grid: TraversabilityGrid,
    target: Sequence[float],
    config: Mapping[str, Any],
) -> list[dict[str, Any]] | None:
    """Build a short, safe 0.25 m approach for an otherwise-unsampled feature.

    This is deliberately a last-resort semantic coverage seed, not a wall-band
    densifier.  It lets a room/goal/hazard whose sparse anchor path cannot be
    snapped to the action lattice contribute one meaningful local approach
    route.  Portal features are never handled here because they must retain
    their separate doorway validation.
    """
    target_cell = _nearest_safe_cell(grid, (float(target[0]), float(target[1])))
    if target_cell is None:
        return None
    step = float(config["forward_step_m"])
    min_steps = max(1, int(math.ceil(float(config["min_request_context_m"]) / step)))
    max_steps = max(min_steps, 12)
    heading_count = int(config["heading_count"])
    radius_cells = max(0, int(math.ceil(float(config["coverage_seed_search_radius_m"]) / grid.spec.resolution)))
    candidates: list[tuple[float, tuple[float, float]]] = []
    for cy in range(max(0, target_cell[1] - radius_cells), min(grid.spec.height, target_cell[1] + radius_cells + 1)):
        for cx in range(max(0, target_cell[0] - radius_cells), min(grid.spec.width, target_cell[0] + radius_cells + 1)):
            if not bool(grid.traversable[cy, cx]):
                continue
            point = cell_to_world(grid.spec, cx, cy)
            offset = _distance(point, target)
            if offset <= float(config["coverage_seed_search_radius_m"]) + 1e-9:
                candidates.append((offset, point))
    candidates.sort(key=lambda item: (item[0], item[1][1], item[1][0]))
    best: list[tuple[float, float]] | None = None
    # Search feature-adjacent safe cells in increasing semantic offset.  Return
    # the first cell with a legal approach rather than moving farther away just
    # to gain a longer corridor segment.
    for _offset, target_point in candidates:
        local_best: list[tuple[float, float]] | None = None
        for index in range(heading_count):
            yaw = math.radians(index * 360.0 / heading_count)
            dx, dy = -math.sin(yaw) * step, math.cos(yaw) * step
            points = [target_point]
            for depth in range(1, max_steps + 1):
                source = (target_point[0] - dx * depth, target_point[1] - dy * depth)
                if not _world_segment_safe(grid, source, points[0]):
                    break
                points.insert(0, source)
                if local_best is None or len(points) > len(local_best):
                    local_best = list(points)
        if local_best is not None:
            best = local_best
            break
    if best is None:
        return None
    return [
        {"source": source, "target": target_point, "kind": "forward", "anchor_edge_ids": []}
        for source, target_point in zip(best, best[1:])
    ]


def _candidate_requests(
    graph: ViewpointGraph,
    annotation: SceneAnnotation | None,
    config: Mapping[str, Any],
    *,
    motion_grid: TraversabilityGrid | None = None,
) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    feature_nodes, node_features = _role_nodes(graph, annotation)
    components = _component_index(graph)
    nodes = {node.node_id: node for node in graph.nodes}
    candidates: list[dict[str, Any]] = []
    # Several semantic features can resolve to the same safe anchor (for
    # example a room medoid and a nearby glass hazard).  Keep a single route
    # but merge every feature into its obligation set; dropping later duplicates
    # was why reachable goals/hazards could disappear from coverage accounting.
    candidate_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    scenario_cycle = ("goal_only", "hazard_aware", "stop_before_glass", "detour")
    feature_items = sorted(feature_nodes.items())
    for feature_index, (feature, target_ids) in enumerate(feature_items):
        # A portal has two threshold anchors but a catalogue request needs only
        # one route that reaches that portal.  Expanding both sides duplicates
        # nearly all action-state work without adding coverage.
        for target_id in sorted(target_ids)[:1]:
            target = nodes.get(target_id)
            if target is None:
                continue
            eligible = [node for node in nodes.values() if components.get(node.node_id) == components.get(target_id) and node.node_id != target_id]
            if not eligible:
                continue
            # Use the shortest start that still gives the request meaningful
            # route context.  Farthest-node starts looked diverse, but consumed
            # the entire 600-pose union before several rooms and portals could
            # be represented.  The subsequent greedy selector is therefore
            # choosing between comparable, useful route costs rather than
            # paying for arbitrary whole-building traversals.
            minimum_context = float(config["min_request_context_m"])
            contextual = [
                node for node in eligible
                if _distance(node.position, target.position) >= minimum_context
            ]
            start = min(
                contextual or eligible,
                key=lambda node: (_distance(node.position, target.position), node.node_id),
            )
            pair = (start.node_id, target_id)
            # A portal is covered only when its edge is traversed.  Merely
            # arriving at one threshold anchor must not satisfy a doorway
            # coverage obligation.
            inherited_features = {
                value
                for value in (set(node_features.get(start.node_id, set())) | set(node_features.get(target_id, set())))
                if not value.startswith("portal:")
            }
            existing = candidate_by_pair.get(pair)
            if existing is not None:
                existing["feature_ids"] = sorted(set(existing["feature_ids"]) | inherited_features | {feature})
                continue
            try:
                primary = shortest_graph_path(graph, *pair)
            except ValueError:
                continue
            if str(config.get("profile_id") or "") == PROFILE_ID:
                # v3 chooses coverage on anchor topology and only later creates
                # one canonical lattice.  Filtering here with v2's separate
                # normal/portal sampler would incorrectly erase a portal before
                # the v3 planner has a chance to certify it.
                steps, rejected = _v3_anchor_estimate_steps(graph, primary), []
            else:
                steps, rejected = _path_template(graph, primary, config, motion_grid=motion_grid)
            if steps is None or not steps:
                continue
            features = inherited_features
            for edge in primary.edges:
                portal = (edge.extras or {}).get("portal")
                if portal:
                    features.add(f"portal:{portal}")
            alternatives: list[GraphPath] = []
            retained_alternative_steps: list[list[dict[str, Any]]] = []
            primary_signature = _path_portal_signature(primary)
            # A distinct homotopy is meaningful only for a doorway route.  Do
            # not run one expensive action-lattice search for every ordinary
            # anchor edge merely to rediscover the same corridor path.
            for edge in primary.edges:
                if not (edge.extras or {}).get("portal"):
                    continue
                alternative = _shortest_without_edges(graph, start.node_id, target_id, {edge.edge_id})
                if alternative is None or alternative.distance_m > primary.distance_m * float(config["spanner_stretch"]):
                    continue
                sampled_alternative_steps = (
                    _v3_anchor_estimate_steps(graph, alternative)
                    if str(config.get("profile_id") or "") == PROFILE_ID
                    else _path_template(graph, alternative, config, motion_grid=motion_grid)[0]
                )
                if sampled_alternative_steps is None:
                    continue
                if _path_portal_signature(alternative) != primary_signature:
                    alternatives = [alternative]
                    retained_alternative_steps = [sampled_alternative_steps]
                    break
            candidate = {
                "request_id": f"navreq_{len(candidates) + 1:04d}",
                "start_anchor_id": start.node_id,
                "goal_anchor_id": target_id,
                "scenario": scenario_cycle[feature_index % len(scenario_cycle)],
                "feature_ids": sorted(features | {feature}),
                "primary": primary,
                "primary_steps": steps,
                "alternatives": alternatives,
                "alternative_steps": retained_alternative_steps,
                "rejections": rejected,
            }
            candidates.append(candidate)
            candidate_by_pair[pair] = candidate

    # Add a direct, geometry-certified crossing candidate for every portal.
    # Generic target routes may stop at a threshold anchor without crossing the
    # opening, which made portal coverage a false positive.  This short route is
    # a mandatory coverage seed; longer contextual routes can still be selected
    # for rooms/goals/hazards above.
    portal_edges = sorted(
        (edge for edge in graph.edges if (edge.extras or {}).get("portal")),
        key=lambda edge: (str((edge.extras or {}).get("portal")), edge.edge_id),
    )
    for index, edge in enumerate(portal_edges):
        feature = f"portal:{(edge.extras or {}).get('portal')}"
        primary = GraphPath(
            nodes=[edge.source, edge.target],
            edges=[edge],
            distance_m=float(edge.weight),
            hazard_crossing=bool(edge.hazard_crossing),
        )
        if str(config.get("profile_id") or "") == PROFILE_ID:
            steps, rejected = _v3_anchor_estimate_steps(graph, primary), []
        else:
            steps, rejected = _path_template(graph, primary, config, motion_grid=motion_grid)
        if steps is None or not steps:
            continue
        candidates.append({
            "request_id": f"navreq_{len(candidates) + 1:04d}",
            "start_anchor_id": edge.source,
            "goal_anchor_id": edge.target,
            "scenario": scenario_cycle[(len(feature_items) + index) % len(scenario_cycle)],
            "feature_ids": [feature],
            "primary": primary,
            "primary_steps": steps,
            "alternatives": [],
            "alternative_steps": [],
            "rejections": rejected,
        })

    # Some semantic anchors sit in a real navigable room but their nearest
    # sparse-graph route cannot be phase-aligned to 0.25 m actions (often due
    # to imported manual edges). Keep coverage honest by adding one short local
    # approach only for those still-unrepresented non-portal features.
    candidate_features = set().union(*(set(item["feature_ids"]) for item in candidates)) if candidates else set()
    if motion_grid is not None:
        for feature, target_ids in sorted(feature_nodes.items()):
            if feature.startswith("portal:") or feature in candidate_features:
                continue
            target_id = next(iter(sorted(target_ids)), None)
            target = nodes.get(str(target_id)) if target_id is not None else None
            if target is None:
                continue
            steps = _coverage_seed_steps(motion_grid, target.position, config)
            if not steps:
                continue
            candidates.append({
                "request_id": f"navreq_{len(candidates) + 1:04d}",
                "start_anchor_id": target.node_id,
                "goal_anchor_id": target.node_id,
                "scenario": scenario_cycle[(len(candidates) + len(feature_items)) % len(scenario_cycle)],
                "feature_ids": [feature],
                "primary": GraphPath(nodes=[target.node_id], edges=[], distance_m=0.0, hazard_crossing=False),
                "primary_steps": steps,
                "alternatives": [],
                "alternative_steps": [],
                "coverage_seed": True,
                "rejections": [],
            })
    return candidates, set(feature_nodes), {"feature_nodes": {key: sorted(value) for key, value in feature_nodes.items()}, "components": components}


def _point_key(point: Sequence[float]) -> str:
    return f"{float(point[0]):.5f},{float(point[1]):.5f}"


def _candidate_point_keys(
    candidate: Mapping[str, Any],
    graph: ViewpointGraph,
    config: Mapping[str, Any],
    *,
    motion_grid: TraversabilityGrid | None = None,
) -> set[str]:
    values: set[str] = set()
    route_sets = [candidate.get("primary_steps") or []]
    route_sets.extend(candidate.get("alternative_steps") or [])
    for steps in route_sets:
        for step in steps:
            values.add(_point_key(step["source"]))
            values.add(_point_key(step["target"]))
    return values


def _v3_anchor_estimate_steps(graph: ViewpointGraph, path: GraphPath) -> list[dict[str, Any]]:
    """Cheap topology-only cost estimate used before canonical v3 motionization."""
    rows: list[dict[str, Any]] = []
    for index, edge in enumerate(path.edges):
        source = next(node for node in graph.nodes if node.node_id == path.nodes[index])
        target = next(node for node in graph.nodes if node.node_id == path.nodes[index + 1])
        rows.append({"source": source.position[:2], "target": target.position[:2], "kind": "portal_bridge" if (edge.extras or {}).get("portal") else "forward", "anchor_edge_ids": [edge.edge_id]})
    return rows


def _select_requests(
    candidates: list[dict[str, Any]],
    graph: ViewpointGraph,
    config: Mapping[str, Any],
    required_features: set[str],
    *,
    motion_grid: TraversabilityGrid | None = None,
) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    used_points: set[str] = set()
    covered: set[str] = set()
    warnings: list[dict[str, Any]] = []
    remaining = list(candidates)
    maximum = int(config["max_motion_poses"])

    # Coverage is a hard feasibility phase, not just a coefficient in a
    # cost/benefit score.  Otherwise cheap portal routes consume the selected
    # set and a perfectly reachable room/goal can be left uncovered.
    while remaining and len(selected) < int(config["max_requests"]):
        ranked: list[tuple[int, int, str, dict[str, Any], set[str]]] = []
        for candidate in remaining:
            point_keys = _candidate_point_keys(candidate, graph, config, motion_grid=motion_grid)
            new_points = point_keys - used_points
            if len(used_points | point_keys) > maximum:
                continue
            new_required = (set(candidate["feature_ids"]) & required_features) - covered
            if not new_required:
                continue
            # First cover as many outstanding obligations as possible; only
            # then choose the lower incremental action-state cost.
            ranked.append((-len(new_required), len(new_points), str(candidate["request_id"]), candidate, point_keys))
        if not ranked:
            break
        ranked.sort(key=lambda row: row[:3])
        _gain, _cost, _request_id, candidate, point_keys = ranked[0]
        selected.append(candidate)
        used_points.update(point_keys)
        covered.update(candidate["feature_ids"])
        remaining.remove(candidate)

    missing = sorted(required_features - covered)
    if missing:
        candidate_features = set().union(*(set(item["feature_ids"]) for item in candidates)) if candidates else set()
        warnings.append({
            "code": "coverage_unreachable_or_motion_budget",
            "missing_feature_ids": missing,
            "no_safe_candidate_feature_ids": sorted(set(missing) - candidate_features),
            "motion_budget_limited_feature_ids": sorted(set(missing) & candidate_features),
        })
    return selected, covered, warnings


def _materialize_motion(
    graph: ViewpointGraph,
    selected: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    *,
    motion_grid: TraversabilityGrid | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    nodes_by_key: dict[str, dict[str, Any]] = {}
    edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    routes: list[dict[str, Any]] = []
    anchor_positions = {node.node_id: _point_key(node.position) for node in graph.nodes}
    anchor_by_key = {value: key for key, value in anchor_positions.items()}

    def ensure_node(point: Sequence[float], *, tag: str | None = None) -> str:
        key = _point_key(point)
        node = nodes_by_key.get(key)
        if node is None:
            node = {
                "motion_node_id": f"motion_{len(nodes_by_key) + 1:04d}",
                # Keep enough precision that a 15-degree 0.25m action remains
                # geometrically aligned after JSON round-trip (six decimals can
                # visibly perturb the derived heading at this step size).
                "position": [round(float(point[0]), 10), round(float(point[1]), 10), 0.0],
                "anchor_node_ids": [],
                "tags": [],
                "route_heading_ids": [],
            }
            if key in anchor_by_key:
                node["anchor_node_ids"].append(anchor_by_key[key])
                node["tags"].append("anchor")
            nodes_by_key[key] = node
        if tag and tag not in node["tags"]:
            node["tags"].append(tag)
        return str(node["motion_node_id"])

    def materialize_path(steps: Sequence[Mapping[str, Any]], *, route_id: str, alt_index: int | None = None) -> dict[str, Any]:
        route_nodes: list[str] = []
        route_edges: list[str] = []
        for step in steps:
            kind = str(step["kind"])
            source_id = ensure_node(step["source"], tag="portal" if kind == "portal_bridge" else None)
            target_id = ensure_node(step["target"], tag="portal" if kind == "portal_bridge" else None)
            if not route_nodes:
                route_nodes.append(source_id)
            route_nodes.append(target_id)
            distance_m = _distance(step["source"], step["target"])
            key = (*_edge_key(source_id, target_id), kind)
            edge = edges_by_key.get(key)
            if edge is None:
                edge = {
                    "motion_edge_id": f"motion_edge_{len(edges_by_key) + 1:05d}",
                    "source": source_id,
                    "target": target_id,
                    "distance_m": round(distance_m, 6),
                    "action": "move_forward",
                    "edge_type": kind,
                    "collision_free": True,
                    "anchor_edge_ids": [str(item) for item in step.get("anchor_edge_ids") or []],
                }
                edges_by_key[key] = edge
            else:
                for anchor_edge_id in step.get("anchor_edge_ids") or []:
                    if str(anchor_edge_id) not in edge["anchor_edge_ids"]:
                        edge["anchor_edge_ids"].append(str(anchor_edge_id))
            route_edges.append(edge["motion_edge_id"])
            heading = _heading_id(_yaw_to(step["source"], step["target"]), int(config["heading_count"]))
            for node_id in (source_id, target_id):
                for item in nodes_by_key.values():
                    if item["motion_node_id"] == node_id and heading not in item["route_heading_ids"]:
                        item["route_heading_ids"].append(heading)
                        break
        initial_heading_id = "h_000"
        if len(route_nodes) >= 2:
            first = next((item for item in nodes_by_key.values() if item["motion_node_id"] == route_nodes[0]), None)
            second = next((item for item in nodes_by_key.values() if item["motion_node_id"] == route_nodes[1]), None)
            if first is not None and second is not None:
                initial_heading_id = _heading_id(
                    _yaw_to(first["position"], second["position"]), int(config["heading_count"])
                )
        return {
            "route_id": route_id if alt_index is None else f"{route_id}_alt_{alt_index}",
            "motion_node_ids": route_nodes,
            "motion_edge_ids": route_edges,
            "initial_heading_id": initial_heading_id,
            "is_alternative": alt_index is not None,
        }

    for candidate in selected:
        primary = materialize_path(candidate["primary_steps"], route_id=str(candidate["request_id"]))
        route = {
            "request_id": candidate["request_id"],
            "start_anchor_id": candidate["start_anchor_id"],
            "goal_anchor_id": candidate["goal_anchor_id"],
            "scenario": candidate["scenario"],
            "feature_ids": list(candidate["feature_ids"]),
            "primary": primary,
            "alternatives": [],
        }
        alternatives = list(candidate.get("alternatives") or [])
        alternative_steps = list(candidate.get("alternative_steps") or [])
        for index, alternative in enumerate(alternatives, start=1):
            steps = alternative_steps[index - 1] if index - 1 < len(alternative_steps) else None
            if steps:
                route["alternatives"].append(materialize_path(steps, route_id=str(candidate["request_id"]), alt_index=index))
        routes.append(route)
    motion_nodes = list(nodes_by_key.values())
    for node in motion_nodes:
        node["route_heading_ids"].sort()
        node["tags"].sort()
    motion_edges = list(edges_by_key.values())
    return {"nodes": motion_nodes, "edges": motion_edges}, routes


def _required_action_headings(
    motion: Mapping[str, Any], routes: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> dict[str, list[str]]:
    """Return the exact pose-heading states consumed by selected route actions.

    ``TRACK_4`` is a render saving policy, not permission to omit an action's
    current heading.  We expand every selected route using its own initial
    direction and retain each intermediate 15-degree turn state.  The result is
    used before tier assignment so episode materialisation cannot discover a
    missing observation after the renderer has already been submitted.
    """
    heading_count = int(config["heading_count"])
    # v3 stores the actual action-state sequence.  Consume it verbatim rather
    # than re-deriving a 180-degree tie from floating yaw; otherwise a route
    # can turn right in its saved transition list while the observation planner
    # incorrectly renders the symmetric left-turn heading.
    state_by_id = {
        str(item.get("motion_state_id")): item
        for item in motion.get("states") or []
        if isinstance(item, Mapping) and item.get("motion_state_id")
    }
    if state_by_id:
        exact: dict[str, set[str]] = defaultdict(set)
        for route in routes:
            primary = route.get("primary") if isinstance(route.get("primary"), Mapping) else {}
            for state_id in primary.get("state_ids") or []:
                state = state_by_id.get(str(state_id))
                if state is not None:
                    exact[str(state["motion_pose_id"])].add(str(state["heading_id"]))
        ordered_ids = _all_heading_ids(heading_count)
        return {node_id: sorted(values, key=ordered_ids.index) for node_id, values in exact.items()}
    heading_step = 360.0 / heading_count
    node_by_id = {
        str(node["motion_node_id"]): node
        for node in motion.get("nodes", [])
        if isinstance(node, Mapping) and node.get("motion_node_id")
    }
    required: dict[str, set[str]] = defaultdict(set)
    for route in routes:
        primary = route.get("primary") if isinstance(route.get("primary"), Mapping) else {}
        node_ids = [str(item) for item in primary.get("motion_node_ids") or []]
        if len(node_ids) < 2:
            continue
        initial = str(primary.get("initial_heading_id") or "h_000")
        try:
            current_yaw = float(initial.split("_", 1)[1]) % 360.0
        except (IndexError, ValueError):
            current_yaw = 0.0
        for source_id, target_id in zip(node_ids, node_ids[1:]):
            source = node_by_id.get(source_id)
            target = node_by_id.get(target_id)
            if source is None or target is None:
                raise ValueError(f"motion route references a missing pose: {source_id}/{target_id}")
            target_yaw = round(_yaw_to(source["position"], target["position"]) / heading_step) * heading_step % 360.0
            delta = ((target_yaw - current_yaw + 180.0) % 360.0) - 180.0
            turn_sign = 1.0 if delta > 0 else -1.0
            for _ in range(int(round(abs(delta) / heading_step))):
                current_yaw = (current_yaw + heading_step * turn_sign) % 360.0
                required[source_id].add(_heading_id(current_yaw, heading_count))
            # The departure observation is also the last turn observation (or
            # the initial one for a straight first action).
            required[source_id].add(_heading_id(current_yaw, heading_count))
        required[node_ids[-1]].add(_heading_id(current_yaw, heading_count))
    ordered_ids = _all_heading_ids(heading_count)
    return {
        node_id: sorted(values, key=lambda heading_id: ordered_ids.index(heading_id))
        for node_id, values in required.items()
    }


def _track_headings(
    required: Sequence[str], all_ids: Sequence[str], route_heading: str,
) -> list[str]:
    """Fill a genuine TRACK_4 pose without displacing required action views."""
    values = list(dict.fromkeys(required))
    if len(values) >= 4:
        return values
    route_index = all_ids.index(route_heading) if route_heading in all_ids else 0
    for candidate in (
        all_ids[(route_index - 1) % len(all_ids)],
        all_ids[route_index],
        all_ids[(route_index + 1) % len(all_ids)],
        all_ids[(route_index + len(all_ids) // 2) % len(all_ids)],
    ):
        if candidate not in values:
            values.append(candidate)
        if len(values) == 4:
            break
    # A route-free open-space coverage pose still has a deterministic TRACK_4
    # contract even though no action route currently consumes it.
    for candidate in all_ids:
        if len(values) == 4:
            break
        if candidate not in values:
            values.append(candidate)
    return values


def _build_observation_plan(motion: Mapping[str, Any], routes: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    nodes = [dict(node) for node in motion.get("nodes", [])]
    degrees = defaultdict(int)
    for edge in motion.get("edges", []):
        degrees[str(edge["source"])] += 1
        degrees[str(edge["target"])] += 1
    required_headings = _required_action_headings(motion, routes, config)
    endpoints: set[str] = set()
    for route in routes:
        path = route.get("primary") or {}
        ids = list(path.get("motion_node_ids") or [])
        if ids:
            endpoints.update((str(ids[0]), str(ids[-1])))
    high_priority: set[str] = set(endpoints)
    for node in nodes:
        node_id = str(node["motion_node_id"])
        tags = set(node.get("tags") or [])
        if degrees[node_id] >= 3 or "portal" in tags or "hazard" in tags:
            high_priority.add(node_id)
        if len(required_headings.get(node_id, [])) >= 2:
            high_priority.add(node_id)
    # The fixed 80/520 budget is intentional when the scene has 600 poses.  Fill
    # unused full-sweep capacity deterministically from route-used points.
    ordered = sorted(nodes, key=lambda node: (str(node["motion_node_id"]) not in high_priority, str(node["motion_node_id"])))
    # FULL_24 promotion must respect both render entries *and* K=4 durable
    # batches.  TRACK_REQUIRED poses can already use >4 headings, so treating
    # every non-full pose as four was enough to breach the 1,000 batch cap on
    # Office 0824 despite staying under the 4,000 observation cap.
    def base_count(node_id: str) -> int:
        return max(4, len(required_headings.get(node_id, [])))
    base_entries = sum(base_count(str(node["motion_node_id"])) for node in nodes)
    base_batches = sum(int(math.ceil(base_count(str(node["motion_node_id"])) / 4.0)) for node in nodes)
    selected_full_entries = base_entries
    selected_full_batches = base_batches
    full_ids: set[str] = set()
    full_positions: list[Sequence[float]] = []
    min_full_sweep_spacing_m = float(config["min_full_sweep_spacing_m"])
    for node in ordered:
        if len(full_ids) >= int(config["max_full_sweep_poses"]):
            break
        node_id = str(node["motion_node_id"])
        # FULL_24 is the yellow/gold detailed-pose layer in the editor.  The
        # route motion lattice remains 0.25 m, but dense junction/turn
        # candidates can come close from different branches.  Do not promote
        # two panorama poses closer than the configured global 2D spacing;
        # the rejected pose still receives its required TRACK observations.
        if any(
            _distance(node["position"], position) < min_full_sweep_spacing_m - 1e-9
            for position in full_positions
        ):
            continue
        current = base_count(node_id)
        proposed_entries = selected_full_entries + 24 - current
        proposed_batches = selected_full_batches + 6 - int(math.ceil(current / 4.0))
        if proposed_entries > int(config["max_polar_observations"]) or proposed_batches > int(config["max_polar_batches"]):
            continue
        full_ids.add(node_id)
        full_positions.append(node["position"])
        selected_full_entries = proposed_entries
        selected_full_batches = proposed_batches
    all_ids = _all_heading_ids(int(config["heading_count"]))
    poses: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    batch_count = 0
    for node in sorted(nodes, key=lambda item: str(item["motion_node_id"])):
        node_id = str(node["motion_node_id"])
        required = list(required_headings.get(node_id, []))
        route_heading = required[0] if required else (node.get("route_heading_ids") or ["h_000"])[0]
        if node_id in full_ids:
            tier = "FULL_24"
            available = list(all_ids)
        elif len(required) > 4:
            # These positions are not panoramas.  They simply need more than
            # four headings to make all shared-route turn actions observable.
            tier = "TRACK_REQUIRED"
            available = list(required)
        else:
            tier = "TRACK_4"
            available = _track_headings(required, all_ids, route_heading)
        if not set(required).issubset(available):
            raise AssertionError(f"observation plan omitted required action headings at {node_id}")
        poses.append({
            "motion_node_id": node_id,
            "position": list(node["position"]),
            "tier": tier,
            "route_heading_id": route_heading,
            "required_action_heading_ids": required,
            "available_heading_ids": available,
            "lazy_heading_ids": [value for value in all_ids if value not in available],
            "tags": list(node.get("tags") or []),
        })
        for offset in range(0, len(available), 4):
            group = available[offset:offset + 4]
            batch_key = f"{node_id}:{tier}:{offset // 4:02d}"
            batch_count += 1
            for heading_id in group:
                entries.append({
                    "entry_id": f"obs_{len(entries) + 1:05d}",
                    "motion_node_id": node_id,
                    "heading_id": heading_id,
                    "tier": tier,
                    "available_heading_ids": available,
                    "polar_batch_key": batch_key,
                    "polar_batch_size": len(group),
                    "native_resolution": [512, 512],
                    "projection": "native_perspective",
                })
    if len(entries) > int(config["max_polar_observations"]):
        raise ValueError("observation plan exceeds max_polar_observations")
    if batch_count > int(config["max_polar_batches"]):
        raise ValueError(
            f"observation plan exceeds max_polar_batches: generated={batch_count}, "
            f"estimated={selected_full_batches}, full_poses={len(full_ids)}"
        )
    full_entries = sum(1 for entry in entries if entry["tier"] == "FULL_24")
    track_4_entries = sum(1 for entry in entries if entry["tier"] == "TRACK_4")
    track_required_entries = sum(1 for entry in entries if entry["tier"] == "TRACK_REQUIRED")
    track_required_pose_count = sum(1 for pose in poses if pose["tier"] == "TRACK_REQUIRED")
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "heading_count": int(config["heading_count"]),
        "panoramic_core": {
            "motion_node_ids": sorted(full_ids),
            "observation_count": full_entries,
            "min_pose_spacing_m": min_full_sweep_spacing_m,
            "interpretation": "complete_24_view_panorama",
        },
        "motion_rollout": {
            "observation_count": len(entries),
            "interpretation": "partial_heading_state; use available_heading_ids",
            "action_heading_closure": "all selected 15-degree action states are materialised",
        },
        "poses": poses,
        "render_entries": entries,
        "summary": {
            "full_sweep_pose_count": len(full_ids),
            "full_sweep_min_spacing_m": min_full_sweep_spacing_m,
            "track_pose_count": len(nodes) - len(full_ids),
            "track_4_pose_count": len(nodes) - len(full_ids) - track_required_pose_count,
            "track_required_pose_count": track_required_pose_count,
            "full_24_observation_count": full_entries,
            "track_4_observation_count": track_4_entries,
            "track_required_observation_count": track_required_entries,
            "required_action_heading_count": sum(len(values) for values in required_headings.values()),
            "polar_observation_count": len(entries),
            "polar_batch_count": batch_count,
            "gpu_time_estimate_hours_per_polar_camera_variant": round(
                len(entries) * float(config["heading_render_seconds"]) / 3600.0,
                3,
            ),
        },
    }


def build_adaptive_route_motion(
    anchor_graph: ViewpointGraph,
    *,
    annotation: SceneAnnotation | None = None,
    config: Mapping[str, Any] | None = None,
    motion_grid: TraversabilityGrid | None = None,
) -> dict[str, Any]:
    """Build immutable route/motion/observation sidecar payloads in memory."""
    cfg = _merged_config(config)
    if len(anchor_graph.nodes) > int(cfg["max_anchor_nodes"]):
        raise ValueError("anchor graph exceeds adaptive_route_motion_v3 max_anchor_nodes")
    if anchor_graph.node_heading_count != int(cfg["heading_count"]):
        raise ValueError("adaptive_route_motion_v3 anchor graph must use 24 headings")
    spanner = build_anchor_spanner(anchor_graph, stretch=float(cfg["spanner_stretch"]))
    candidates, required_features, catalogue_meta = _candidate_requests(
        spanner, annotation, cfg, motion_grid=motion_grid,
    )
    selected, covered, warnings = _select_requests(
        candidates, spanner, cfg, required_features, motion_grid=motion_grid,
    )
    motion, routes = _materialize_motion(spanner, selected, cfg, motion_grid=motion_grid)
    if len(motion["nodes"]) > int(cfg["max_motion_poses"]):
        raise AssertionError("route selector exceeded its motion-pose budget")
    invalid_action_edges = [
        str(edge.get("motion_edge_id") or "")
        for edge in motion["edges"]
        if not math.isclose(float(edge.get("distance_m") or 0.0), float(cfg["forward_step_m"]), abs_tol=float(cfg["forward_tolerance_m"]))
    ]
    if invalid_action_edges:
        raise AssertionError("adaptive motion graph contains non-normalized forward actions: " + ", ".join(invalid_action_edges))
    observation_plan = _build_observation_plan(motion, routes, cfg)
    digest_payload = {
        "profile_id": PROFILE_ID,
        "anchor_graph_id": spanner.graph_id,
        "config": cfg,
        "motion_nodes": motion["nodes"],
        "motion_edges": motion["edges"],
    }
    profile_digest = sha1(json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    navigation_requests = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "anchor_graph_id": spanner.graph_id,
        "profile_digest": profile_digest,
        "requests": [
            {
                "request_id": item["request_id"],
                "start_anchor_id": item["start_anchor_id"],
                "goal_anchor_id": item["goal_anchor_id"],
                "scenario": item["scenario"],
                "feature_ids": item["feature_ids"],
                "primary_anchor_path": list(item["primary"].nodes),
                "alternative_anchor_paths": [list(path.nodes) for path in item.get("alternatives") or []],
            }
            for item in selected
        ],
        "catalogue": catalogue_meta,
        "coverage": {
            "required_feature_ids": sorted(required_features),
            "covered_feature_ids": sorted(covered),
            "missing_feature_ids": sorted(required_features - covered),
        },
    }
    motion_graph = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "profile_digest": profile_digest,
        "scene_id": spanner.scene_id,
        "anchor_graph_id": spanner.graph_id,
        "heading_count": int(cfg["heading_count"]),
        "turn_deg": float(cfg["turn_deg"]),
        "forward_step_m": float(cfg["forward_step_m"]),
        "forward_tolerance_m": float(cfg["forward_tolerance_m"]),
        "effective_clearance_m": float(cfg["effective_clearance_m"]),
        "nodes": motion["nodes"],
        "edges": motion["edges"],
        "routes": routes,
    }
    observation_plan.update({
        "scene_id": spanner.scene_id,
        "anchor_graph_id": spanner.graph_id,
        "profile_digest": profile_digest,
        "motion_graph_ref": "motion_graph.json",
        "config": cfg,
    })
    diagnostics = {
        "anchor_node_count": len(spanner.nodes),
        "anchor_edge_count": len(spanner.edges),
        "motion_pose_count": len(motion["nodes"]),
        "motion_edge_count": len(motion["edges"]),
        "non_normalized_action_edge_count": len(invalid_action_edges),
        "request_count": len(selected),
        "required_feature_count": len(required_features),
        "covered_feature_count": len(covered),
        "portal_coverage": {
            "required": sum(1 for item in required_features if item.startswith("portal:")),
            "covered": sum(1 for item in covered if item.startswith("portal:")),
        },
        "hazard_coverage": {
            "required": sum(1 for item in required_features if item.startswith(("hazard:", "hazard_view:"))),
            "covered": sum(1 for item in covered if item.startswith(("hazard:", "hazard_view:"))),
        },
        "observation": dict(observation_plan["summary"]),
        "warnings": warnings,
    }
    return {
        "anchor_graph": viewpoint_graph_to_payload(spanner),
        "navigation_requests": navigation_requests,
        "motion_graph": motion_graph,
        "observation_plan": observation_plan,
        "generation_diagnostics": diagnostics,
    }


def write_adaptive_route_motion(scene_dir: str | Path, payload: Mapping[str, Any]) -> dict[str, Path]:
    """Atomically write v3 sidecars without touching legacy graph/episode data."""
    root = Path(scene_dir)
    names = {
        "anchor_graph": "anchor_graph.json",
        "navigation_requests": "navigation_requests.json",
        "motion_graph": "motion_graph.json",
        "observation_plan": "observation_plan.json",
    }
    return {key: _atomic_json(root / name, dict(payload[key])) for key, name in names.items()}


def read_observation_plan(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if str(payload.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("not an adaptive_route_motion_v3 observation plan")
    entries = payload.get("render_entries")
    if not isinstance(entries, list):
        raise ValueError("observation plan has no render_entries")
    return payload


def render_positions_from_observation_plan(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten planned pose/headings into custom-position sweep payload rows."""
    positions = {str(item["motion_node_id"]): item.get("position") for item in plan.get("poses", []) if isinstance(item, Mapping)}
    output: list[dict[str, Any]] = []
    for entry in plan.get("render_entries") or []:
        if not isinstance(entry, Mapping):
            continue
        node_id = str(entry.get("motion_node_id") or "")
        position = positions.get(node_id)
        if not isinstance(position, Sequence) or len(position) < 2:
            raise ValueError(f"render entry references missing motion pose: {node_id}")
        heading_id = str(entry.get("heading_id") or "")
        try:
            yaw_deg = float(heading_id.split("_", 1)[1])
        except (IndexError, ValueError):
            raise ValueError(f"invalid motion heading id: {heading_id}") from None
        output.append({
            "node_id": node_id,
            "heading_id": heading_id,
            "x": float(position[0]),
            "y": float(position[1]),
            "yaw_deg": yaw_deg,
            "render_mode": "adaptive_route_motion_v3",
            "tier": str(entry.get("tier") or "TRACK_4"),
            "available_heading_ids": list(entry.get("available_heading_ids") or []),
            "polar_batch_key": str(entry.get("polar_batch_key") or ""),
            "polar_batch_size": int(entry.get("polar_batch_size") or 1),
            "profile_digest": str(plan.get("profile_digest") or ""),
        })
    return output


def motion_render_graph_from_plan(plan: Mapping[str, Any]) -> ViewpointGraph:
    """Materialise a render-only 24-heading graph for the durable sweep queue.

    This graph is an implementation adapter, not a user-editable navigation graph.
    It exists so the existing ledger-backed graph-sweep submission path can keep
    ownership of task identity, retries, and render versions while rendering only
    the explicit plan allow-list.
    """
    heading_count = int(plan.get("heading_count") or 24)
    if heading_count != 24:
        raise ValueError("adaptive route motion render graph requires 24 headings")
    nodes: list[ViewpointNode] = []
    for pose in plan.get("poses") or []:
        if not isinstance(pose, Mapping):
            continue
        position = pose.get("position")
        if not isinstance(position, Sequence) or len(position) < 2:
            raise ValueError("motion plan pose has no xy position")
        nodes.append(ViewpointNode(
            node_id=str(pose["motion_node_id"]),
            position=[float(position[0]), float(position[1]), 0.0],
            tags=["adaptive_route_motion", str(pose.get("tier") or "TRACK_4")],
            headings=[
                ViewpointHeading(heading_id=heading_id, yaw_deg=float(index * 15))
                for index, heading_id in enumerate(_all_heading_ids(heading_count))
            ],
            extras={
                "profile_id": PROFILE_ID,
                "tier": str(pose.get("tier") or "TRACK_4"),
                "available_heading_ids": list(pose.get("available_heading_ids") or []),
            },
        ))
    if not nodes:
        raise ValueError("motion plan has no poses")
    digest = str(plan.get("profile_digest") or "")
    return ViewpointGraph(
        scene_id=str(plan["scene_id"]),
        graph_id=f"{str(plan.get('anchor_graph_id') or 'anchor')}_motion_render_{digest[:12] or 'v3'}",
        node_heading_count=heading_count,
        nodes=nodes,
        edges=[],
        metadata={
            "profile_id": PROFILE_ID,
            "profile_digest": digest,
            "render_only": True,
            "observation_plan_ref": "observation_plan.json",
        },
    )


def expand_motion_route_actions(
    motion_graph: Mapping[str, Any],
    route_id: str,
    *,
    initial_heading_id: str | None = None,
) -> list[dict[str, Any]]:
    """Expand a v3 route into 15° turns and fixed-distance forward actions.

    The legacy graph expander remains untouched for legacy 30°/variable-distance
    episodes.  New callers use this explicit v3 function and receive the physical
    distance/angle on every action timestep, plus the partial-observation contract
    can be joined from ``observation_plan.json`` by ``motion_node_id``.
    """
    heading_count = int(motion_graph.get("heading_count") or 24)
    if heading_count != 24 or not math.isclose(float(motion_graph.get("turn_deg") or 15.0), 15.0):
        raise ValueError("motion graph is not a 15-degree adaptive route graph")
    node_by_id = {str(node["motion_node_id"]): node for node in motion_graph.get("nodes", []) if isinstance(node, Mapping)}
    edge_by_id = {str(edge["motion_edge_id"]): edge for edge in motion_graph.get("edges", []) if isinstance(edge, Mapping)}
    route = next((item for item in motion_graph.get("routes", []) if isinstance(item, Mapping) and item.get("request_id") == route_id), None)
    if route is None:
        raise KeyError(f"unknown motion route: {route_id}")
    primary = route.get("primary") if isinstance(route.get("primary"), Mapping) else {}
    motion_ids = [str(item) for item in primary.get("motion_node_ids") or []]
    edge_ids = [str(item) for item in primary.get("motion_edge_ids") or []]
    if not motion_ids:
        return []
    if len(edge_ids) != max(0, len(motion_ids) - 1):
        raise ValueError("motion route node/edge sequence is inconsistent")
    current_heading = initial_heading_id or _heading_id(0.0, heading_count)
    try:
        current_yaw = float(current_heading.split("_", 1)[1])
    except (IndexError, ValueError):
        current_yaw = 0.0
    rows: list[dict[str, Any]] = []
    for index, edge_id in enumerate(edge_ids):
        source_id, target_id = motion_ids[index], motion_ids[index + 1]
        edge = edge_by_id.get(edge_id)
        source, target = node_by_id.get(source_id), node_by_id.get(target_id)
        if edge is None or source is None or target is None:
            raise ValueError(f"motion route references a missing node/edge: {source_id}/{edge_id}/{target_id}")
        target_yaw = round(_yaw_to(source["position"], target["position"]) / 15.0) * 15.0 % 360.0
        delta = ((target_yaw - current_yaw + 180.0) % 360.0) - 180.0
        turn_sign = 1.0 if delta > 0 else -1.0
        for _ in range(int(round(abs(delta) / 15.0))):
            current_yaw = (current_yaw + 15.0 * turn_sign) % 360.0
            rows.append({
                "motion_node_id": source_id,
                "heading_id": _heading_id(current_yaw, heading_count),
                "action": "turn_left" if turn_sign > 0 else "turn_right",
                "agent_pose": [float(source["position"][0]), float(source["position"][1]), math.radians(current_yaw)],
                "extras": {"turn_deg": 15.0 * turn_sign, "motion_profile": PROFILE_ID},
            })
        edge_type = str(edge.get("edge_type") or "forward")
        forward_m = float(edge.get("distance_m") or 0.0)
        if not math.isclose(forward_m, 0.25, abs_tol=0.025):
            raise ValueError(f"motion edge {edge_id} violates 0.25m action tolerance")
        rows.append({
            "motion_node_id": source_id,
            "heading_id": _heading_id(current_yaw, heading_count),
            "action": "move_forward",
            "agent_pose": [float(source["position"][0]), float(source["position"][1]), math.radians(current_yaw)],
            "extras": {
                "forward_m": forward_m,
                "edge_type": edge_type,
                "motion_edge_id": edge_id,
                "motion_profile": PROFILE_ID,
            },
        })
    final = node_by_id[motion_ids[-1]]
    rows.append({
        "motion_node_id": motion_ids[-1],
        "heading_id": _heading_id(current_yaw, heading_count),
        "action": "stop",
        "agent_pose": [float(final["position"][0]), float(final["position"][1]), math.radians(current_yaw)],
        "extras": {"motion_profile": PROFILE_ID},
    })
    return rows


def make_motion_route_episode(
    *,
    episode_id: str,
    split: str,
    motion_graph: Mapping[str, Any],
    observation_plan: Mapping[str, Any],
    route_id: str,
    natural_language_instruction: str | None = None,
    goal_region: str | None = None,
    initial_heading_id: str | None = None,
    observation_refs_by_view: Mapping[str, str] | None = None,
) -> "EpisodeManifest":
    """Materialise a v3 route as a 15° / fixed-forward episode.

    This intentionally does not call the legacy graph-path expander: the
    anchor graph is a global planner, whereas this episode's action space is
    the route-union motion graph.  Observation refs are optional because plans
    are valid before rendering; every timestep still declares exactly which
    headings were materialised at that pose.
    """
    from .episode_schema import EpisodeManifest, EpisodeTimestep

    if str(motion_graph.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("motion graph is not adaptive_route_motion_v3")
    if str(observation_plan.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("observation plan is not adaptive_route_motion_v3")
    if str(motion_graph.get("profile_digest") or "") != str(observation_plan.get("profile_digest") or ""):
        raise ValueError("motion graph and observation plan digest mismatch")
    scene_id = str(motion_graph.get("scene_id") or observation_plan.get("scene_id") or "")
    if not scene_id:
        raise ValueError("motion graph has no scene_id")
    route = next(
        (
            item
            for item in motion_graph.get("routes", [])
            if isinstance(item, Mapping) and str(item.get("request_id") or "") == route_id
        ),
        None,
    )
    if route is None:
        raise KeyError(f"unknown motion route: {route_id}")
    pose_contract = {
        str(item.get("motion_node_id") or ""): item
        for item in observation_plan.get("poses", [])
        if isinstance(item, Mapping)
    }
    primary = route.get("primary") if isinstance(route.get("primary"), Mapping) else {}
    motion_node_ids = [str(item) for item in primary.get("motion_node_ids") or []]
    if not motion_node_ids:
        raise ValueError("motion route has no poses")
    # Episodes spawn facing their own first route direction by default.  A
    # shared motion pose can start several routes, so the old pose-level
    # ``route_heading_id`` was not sufficient and could force an unseen turn
    # before the first move.
    spawn_heading = initial_heading_id or str(
        primary.get("initial_heading_id")
        or (pose_contract.get(motion_node_ids[0]) or {}).get("route_heading_id")
        or "h_000"
    )
    expanded = expand_motion_route_actions(
        motion_graph, route_id, initial_heading_id=spawn_heading
    )
    if not expanded:
        raise ValueError("motion route has no executable actions")
    refs = {str(key): str(value) for key, value in (observation_refs_by_view or {}).items() if value}
    timesteps: list[EpisodeTimestep] = []
    trajectory: list[list[float]] = []
    actions: list[str] = []
    observation_refs: list[str] = []
    for index, action_row in enumerate(expanded):
        node_id = str(action_row["motion_node_id"])
        heading_id = str(action_row["heading_id"])
        contract = pose_contract.get(node_id)
        if contract is None:
            raise ValueError(f"motion route references pose absent from observation plan: {node_id}")
        available = [str(item) for item in contract.get("available_heading_ids") or []]
        # Every action must have its current heading rendered.  This catches a
        # seemingly harmless TRACK_4 selection that would make rollout state
        # unobservable at the exact turn/move timestep.
        if heading_id not in available:
            raise ValueError(f"required route heading is not available: {node_id}/{heading_id}")
        pose = [float(value) for value in action_row["agent_pose"]]
        action = str(action_row["action"])
        ref = refs.get(f"{node_id}/{heading_id}")
        if ref and ref not in observation_refs:
            observation_refs.append(ref)
        trajectory.append(pose)
        actions.append(action)
        timesteps.append(EpisodeTimestep(
            timestep_index=index,
            timestamp=float(index),
            agent_pose=pose,
            action=action,
            observation_bundle_ref=ref,
            extras={
                "motion_node_id": node_id,
                "heading_id": heading_id,
                "available_heading_ids": available,
                "observation_tier": str(contract.get("tier") or "TRACK_4"),
                **dict(action_row.get("extras") or {}),
            },
        ))
    path_headings = [str(item["heading_id"]) for item in expanded]
    resolved_goal = goal_region or str(route.get("goal_anchor_id") or motion_node_ids[-1])
    instruction = natural_language_instruction or f"Navigate safely to {resolved_goal}."
    return EpisodeManifest(
        episode_id=episode_id,
        scene_id=scene_id,
        split=split,
        start_pose=trajectory[0],
        goal_pose=trajectory[-1],
        goal_region=resolved_goal,
        natural_language_instruction=instruction,
        trajectory=trajectory,
        actions=actions,
        timesteps=timesteps,
        metadata={
            "motion_profile": PROFILE_ID,
            "profile_digest": str(motion_graph.get("profile_digest") or ""),
            "turn_deg": 15.0,
            "forward_step_m": float(motion_graph.get("forward_step_m") or 0.25),
            "forward_tolerance_m": float(motion_graph.get("forward_tolerance_m") or 0.025),
            "observation_plan_ref": "observation_plan.json",
            "partial_observation_contract": "available_heading_ids",
            "scenario": str(route.get("scenario") or "goal_only"),
        },
        navigation_mode=PROFILE_ID,
        graph_id=str(motion_graph.get("anchor_graph_id") or ""),
        start_node=motion_node_ids[0] if motion_node_ids else None,
        goal_node=motion_node_ids[-1] if motion_node_ids else None,
        path_nodes=motion_node_ids,
        path_headings=path_headings,
        observation_refs=observation_refs,
    )


def plan_motion_route_episodes(
    *,
    motion_graph: Mapping[str, Any],
    observation_plan: Mapping[str, Any],
    navigation_requests: Mapping[str, Any],
    num_pairs: int,
    split_counts: Mapping[str, int],
    modalities: Sequence[str] | None = None,
    seed: int = 0,
    allow_incomplete_coverage: bool = False,
) -> list["EpisodeManifest"]:
    """Materialise distinct selected v3 routes without touching legacy episodes.

    The route catalogue is already the diversity/coverage selection surface.  We
    intentionally do not manufacture duplicate copies when the caller asks for
    more episodes than there are selected routes; that would make a nominal
    split look larger without adding new motion or perception states.
    """
    from .rollout import scale_split_counts, split_for_index

    if str(motion_graph.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("motion graph is not adaptive_route_motion_v3")
    if str(observation_plan.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("observation plan is not adaptive_route_motion_v3")
    if str(motion_graph.get("profile_digest") or "") != str(observation_plan.get("profile_digest") or ""):
        raise ValueError("motion graph and observation plan digest mismatch")
    missing = [str(item) for item in ((navigation_requests.get("coverage") or {}).get("missing_feature_ids") or [])]
    if missing and not allow_incomplete_coverage:
        raise ValueError(
            "adaptive route coverage is incomplete; rebuild after resolving: " + ", ".join(sorted(missing))
        )
    routes = [
        route for route in motion_graph.get("routes", [])
        if isinstance(route, Mapping) and isinstance(route.get("primary"), Mapping)
        and list((route.get("primary") or {}).get("motion_edge_ids") or [])
    ]
    if not routes:
        raise ValueError("adaptive motion graph has no executable routes")
    if num_pairs <= 0:
        raise ValueError("num_pairs must be positive")
    if num_pairs > len(routes):
        raise ValueError(
            f"adaptive route plan has {len(routes)} distinct executable routes; requested {num_pairs}. "
            "Rebuild with more navigation requests instead of duplicating trajectories."
        )
    split_spec = scale_split_counts({str(key): int(value) for key, value in split_counts.items()}, num_pairs)
    if sum(split_spec.values()) != num_pairs:
        raise ValueError("splits must define at least one positive episode weight")
    catalogue = {
        str(item.get("request_id")): item
        for item in navigation_requests.get("requests", [])
        if isinstance(item, Mapping) and item.get("request_id")
    }
    selected = list(routes)
    random.Random(seed).shuffle(selected)
    episodes: list["EpisodeManifest"] = []
    for index, route in enumerate(selected[:num_pairs]):
        request_id = str(route["request_id"])
        request = catalogue.get(request_id, {})
        features = [str(item) for item in request.get("feature_ids") or route.get("feature_ids") or []]
        goal_region = next((item for item in features if item.startswith("goal:")), str(route.get("goal_anchor_id") or request_id))
        split = split_for_index(split_spec, index)
        episode = make_motion_route_episode(
            episode_id=f"{motion_graph['scene_id']}_{split}_armv3_{index + 1:06d}",
            split=split,
            motion_graph=motion_graph,
            observation_plan=observation_plan,
            route_id=request_id,
            natural_language_instruction=f"Navigate safely to {goal_region}.",
            goal_region=goal_region,
        )
        episode.metadata.update({
            "route_id": request_id,
            "route_feature_ids": features,
            "modalities": [str(item) for item in (modalities or [])],
            "coverage_status": "partial" if missing else "complete",
            "missing_feature_ids": sorted(missing),
            "allow_incomplete_coverage": bool(missing and allow_incomplete_coverage),
        })
        episodes.append(episode)
    return episodes


def write_scene_motion_route_episodes(paths: Any, episodes: Iterable["EpisodeManifest"]) -> list[Path]:
    """Write profile-prefixed v3 manifests alongside, never over, legacy IDs."""
    return [paths.write_episode(episode) for episode in episodes]


"""v3 implementation follows.  The v2 functions above remain read-only helpers
for already persisted sidecars; their public names are deliberately shadowed below
so a new build can never re-enter the per-route lattice materialiser."""


def _v3_portal_aware_grid(graph: ViewpointGraph, grid: TraversabilityGrid) -> tuple[TraversabilityGrid, list[str]]:
    """Restore certified doorway crossings without widening ordinary free space.

    Inferred/declared portals retain their one-cell centre line: their anchor
    geometry has already been constructed around the raster phase.  A manual
    opening is different.  It is a deliberately reviewed, wall-free short
    floor-mask discontinuity, and a 15-degree/0.25 m action chord can land one
    raster cell to either side of its mathematical centre line.  Restore a
    *single-cell-radius capsule* only for that reviewed link.  This is not a
    generic clearance relaxation: it remains bounded to the certified segment
    and is unavailable to ordinary or rejected place edges.
    """
    mask = grid.traversable.copy()
    restored: list[str] = []
    for edge in graph.edges:
        extras = dict(edge.extras or {})
        validation = extras.get("edge_validation") or {}
        if not isinstance(validation, Mapping):
            continue
        # The first v4 editor recorded an inferred doorway only inside the
        # accepted edge-validation record, never as a ``portal`` extra. That
        # certificate is immutable, so honour it as a portal of its own rather
        # than requiring the edge to be recertified.
        legacy_doorway = (
            str(validation.get("mode") or "") == "doorway"
            and str(validation.get("reason") or "") == "certified_doorway"
            and bool(validation.get("portal_id"))
        )
        portal_id = str(extras.get("portal") or (validation.get("portal_id") if legacy_doorway else "") or "")
        if not portal_id or not (_portal_is_open(edge) or legacy_doorway):
            continue
        if validation.get("wall_run_cells") not in (None, 0):
            continue
        manual = extras.get("manual_opening")
        is_user_certified = (
            str(extras.get("portal_source") or "").lower() == "user_certified"
            and str(extras.get("portal_type") or "") == "manual_opening"
            and isinstance(manual, Mapping)
            and manual.get("certified") is True
        )
        # One physical grid cell is enough to absorb a legal action-lattice
        # phase offset while still being much narrower than the 0.38 m robot
        # clearance that was used to certify the endpoint nodes.
        padding_cells = 1 if (is_user_certified or legacy_doorway) else 0
        for source, target in zip(_edge_points(graph, edge), _edge_points(graph, edge)[1:]):
            count = max(1, int(math.ceil(_distance(source, target) / (float(grid.spec.resolution) / 3.0))))
            for index in range(count + 1):
                t = index / count
                x, y = world_to_cell(grid.spec, source[0] + (target[0] - source[0]) * t, source[1] + (target[1] - source[1]) * t)
                for yy in range(max(0, y - padding_cells), min(grid.spec.height, y + padding_cells + 1)):
                    for xx in range(max(0, x - padding_cells), min(grid.spec.width, x + padding_cells + 1)):
                        # A square would re-open diagonal corner cells that a
                        # 5 cm capsule never occupies.  Keep the restoration
                        # as a true one-cell-radius disk.
                        if math.hypot(xx - x, yy - y) <= padding_cells + 1e-9:
                            mask[yy, xx] = True
        restored.append(portal_id)
    return TraversabilityGrid(spec=grid.spec, traversable=mask, hazard=grid.hazard), sorted(set(restored))


def _v3_crosses_portal_gate(
    source: Sequence[float], target: Sequence[float], corridor_start: Sequence[float], corridor_end: Sequence[float]
) -> bool:
    """Return true only for a forward chord that crosses a portal's middle gate.

    A certified portal segment follows the doorway *corridor*. Treating that
    segment itself as an intersection target makes an action that merely starts
    at one endpoint (then walks away from the door) look like a doorway
    crossing. The navigation contract instead uses a short perpendicular gate
    at the corridor midpoint, which requires a genuine side-to-side crossing.
    """
    dx = float(corridor_end[0]) - float(corridor_start[0])
    dy = float(corridor_end[1]) - float(corridor_start[1])
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return False
    midpoint = ((float(corridor_start[0]) + float(corridor_end[0])) * 0.5, (float(corridor_start[1]) + float(corridor_end[1])) * 0.5)
    ux, uy = dx / length, dy / length
    source_along = (float(source[0]) - midpoint[0]) * ux + (float(source[1]) - midpoint[1]) * uy
    target_along = (float(target[0]) - midpoint[0]) * ux + (float(target[1]) - midpoint[1]) * uy
    # This is a physical separating gate, not an endpoint touch. A 2.5 cm
    # tolerance admits a lattice point on the gate but never an action that
    # remains on one side.
    tolerance = 0.025
    if source_along > tolerance and target_along > tolerance:
        return False
    if source_along < -tolerance and target_along < -tolerance:
        return False
    denominator = target_along - source_along
    if abs(denominator) <= 1e-9:
        return False
    fraction = max(0.0, min(1.0, -source_along / denominator))
    cross_x = float(source[0]) + (float(target[0]) - float(source[0])) * fraction
    cross_y = float(source[1]) + (float(target[1]) - float(source[1])) * fraction
    lateral = abs((cross_x - midpoint[0]) * -uy + (cross_y - midpoint[1]) * ux)
    return lateral <= max(0.30, min(0.75, length * 0.5)) + tolerance


def _v3_union_paths(graph: ViewpointGraph, selected: Sequence[Mapping[str, Any]]) -> tuple[list[GraphPath], list[GraphPath]]:
    """Union selected anchor paths, then add certified Kruskal-style connectors."""
    paths = [item["primary"] for item in selected if isinstance(item.get("primary"), GraphPath)]
    for item in selected:
        paths.extend(path for path in item.get("alternatives") or [] if isinstance(path, GraphPath))
    if not paths:
        raise ValueError("adaptive_route_motion_v3 has no selected anchor routes")
    parent = {node.node_id: node.node_id for node in graph.nodes}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def join(a: str, b: str) -> bool:
        a, b = find(a), find(b)
        if a == b:
            return False
        parent[b] = a
        return True

    active: set[str] = set()
    for path in paths:
        active.update(path.nodes)
        for edge in path.edges:
            join(edge.source, edge.target)
    connectors: list[GraphPath] = []
    # The full anchor graph is already geometry certified.  Kruskal over its
    # edges connects only route-union components and never invents a bridge.
    for edge in sorted((item for item in graph.edges if item.collision_free), key=lambda item: (float(item.weight), item.edge_id)):
        roots = {find(item) for item in active}
        if len(roots) <= 1:
            break
        if find(edge.source) == find(edge.target):
            continue
        before = {find(edge.source), find(edge.target)}
        join(edge.source, edge.target)
        if before & roots:
            connectors.append(GraphPath(nodes=[edge.source, edge.target], edges=[edge], distance_m=float(edge.weight), hazard_crossing=bool(edge.hazard_crossing)))
    if len({find(item) for item in active}) != 1:
        raise ValueError("adaptive_route_motion_v3 anchor_backbone_disconnected")
    return paths, connectors


def _v3_build_action_tree(
    graph: ViewpointGraph,
    selected: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any],
    grid: TraversabilityGrid,
    *,
    on_progress: Callable[[str, float, Mapping[str, Any]], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Explore one global continuous 15-degree action lattice and prune to a tree.

    Search keys are deliberately coarse *only for frontier de-duplication*.  A
    retained tree edge always keeps the original continuous 0.25 m vector, so
    no quantisation can create a short move, a yaw drift, or a phase join.
    """
    import heapq

    def report(stage: str, fraction: float, **detail: Any) -> None:
        if on_progress is not None:
            on_progress(stage, min(1.0, max(0.0, float(fraction))), detail)

    union_paths, connector_paths = _v3_union_paths(graph, selected)
    node_by_id = {node.node_id: node for node in graph.nodes}
    guide_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for path in [*union_paths, *connector_paths]:
        for edge in path.edges:
            points = _edge_points(graph, edge)
            if edge.source != path.nodes[0] and points:
                points.reverse()
            guide_segments.extend(zip(points, points[1:]))
    if not guide_segments:
        raise ValueError("adaptive_route_motion_v3 has an empty union corridor")
    needed_anchor_ids = sorted({str(item[key]) for item in selected for key in ("start_anchor_id", "goal_anchor_id")})
    step = float(cfg["forward_step_m"])
    headings = [
        (-math.sin(math.radians(index * 15.0)) * step, math.cos(math.radians(index * 15.0)) * step)
        for index in range(24)
    ]
    portal_segments: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)
    for edge in graph.edges:
        portal_id = str((edge.extras or {}).get("portal") or "")
        validation = (edge.extras or {}).get("edge_validation") or {}
        if portal_id and _portal_is_open(edge) and isinstance(validation, Mapping) and validation.get("wall_run_cells") in (None, 0):
            portal_segments[portal_id].extend(zip(_edge_points(graph, edge), _edge_points(graph, edge)[1:]))
    required_portals = sorted({feature.split(":", 1)[1] for item in selected for feature in item.get("feature_ids") or [] if str(feature).startswith("portal:")})
    missing_portal_definitions = sorted(set(required_portals) - set(portal_segments))
    # A 2.5 cm occupancy key bounds exploration but is never written to output.
    resolution = float(grid.spec.resolution)
    def key(point: tuple[float, float]) -> tuple[int, int]:
        return (int(round((point[0] - float(grid.spec.origin[0])) / resolution * 2.0)), int(round((point[1] - float(grid.spec.origin[1])) / resolution * 2.0)))
    corridor_radius = max(0.55, step * 2.4)
    terminal_radius = float(cfg["coverage_seed_search_radius_m"])
    expansions = 0
    # A full office can have several long, mutually separated selected routes.
    # This remains a bounded planning search (never persisted itself), while the
    # pruned backbone is normally two orders of magnitude smaller.
    max_expansions = 180_000

    # Calling point-to-polyline distance for every one of the 24 action
    # successors made a 26-room Infinigen build effectively quadratic in the
    # anchor union.  Rasterise the same corridor once; this is only a search
    # limiter, while every retained chord still receives continuous validation.
    radius_cells = int(math.ceil(corridor_radius / resolution))
    guide_cells: set[tuple[int, int]] = set()
    sampled_guide: set[tuple[int, int]] = set()
    for source, target in guide_segments:
        count = max(1, int(math.ceil(_distance(source, target) / resolution)))
        for index in range(count + 1):
            x, y = world_to_cell(grid.spec, source[0] + (target[0] - source[0]) * index / count, source[1] + (target[1] - source[1]) * index / count)
            sampled_guide.add((x, y))
    for x, y in sampled_guide:
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy <= radius_cells * radius_cells:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < grid.spec.width and 0 <= ny < grid.spec.height:
                        guide_cells.add((nx, ny))
    report(
        "action_lattice",
        0.03,
        corridor_cell_count=len(guide_cells),
        selected_request_count=len(selected),
    )

    def allowed(point: tuple[float, float]) -> bool:
        x, y = world_to_cell(grid.spec, *point)
        return (
            0 <= x < grid.spec.width and 0 <= y < grid.spec.height
            and bool(grid.traversable[y, x])
            and (x, y) in guide_cells
        )

    # Pick a root that is both clearance-safe and inside the union corridor.
    # A lexicographically first anchor could itself be an isolated terminal,
    # which would otherwise make a healthy main component look unreachable.
    anchor_frequency = {
        anchor_id: sum(
            1
            for item in selected
            if anchor_id in {str(item["start_anchor_id"]), str(item["goal_anchor_id"])}
        )
        for anchor_id in needed_anchor_ids
    }
    root_candidates: list[tuple[int, str, tuple[int, int]]] = []
    for anchor_id in needed_anchor_ids:
        candidate_cell = _nearest_safe_cell(grid, tuple(node_by_id[anchor_id].position[:2]))
        if candidate_cell is None:
            continue
        candidate_point = cell_to_world(grid.spec, *candidate_cell)
        if allowed(candidate_point):
            root_candidates.append((-anchor_frequency[anchor_id], anchor_id, candidate_cell))
    if not root_candidates:
        raise ValueError("action_root_unreachable:" + ",".join(needed_anchor_ids))
    _frequency, root_anchor_id, root_cell = min(root_candidates)
    root_point = cell_to_world(grid.spec, *root_cell)

    records: dict[str, dict[str, Any]] = {
        "motion_pose_0001": {"motion_pose_id": "motion_pose_0001", "motion_node_id": "motion_pose_0001", "position": [root_point[0], root_point[1], 0.0], "parent": None, "parent_edge_id": None}
    }
    frontier: list[tuple[float, float, int, str]] = [(0.0, 0.0, 0, "motion_pose_0001")]
    seen = {key(root_point): "motion_pose_0001"}
    order = 0
    bindings: dict[str, str] = {}
    binding_distance: dict[str, float] = {}
    crossings: dict[str, tuple[str, str]] = {}
    tree_edges: dict[str, dict[str, Any]] = {}
    report(
        "action_lattice",
        0.06,
        required_terminal_count=len(needed_anchor_ids),
        required_portal_count=len(required_portals),
    )

    def heuristic(point: tuple[float, float]) -> float:
        targets = [tuple(node_by_id[item].position[:2]) for item in needed_anchor_ids if item not in bindings]
        for portal_id in required_portals:
            if portal_id in crossings:
                continue
            for source, target in portal_segments[portal_id]:
                targets.append(((source[0] + target[0]) * 0.5, (source[1] + target[1]) * 0.5))
        return min((_distance(point, target) for target in targets), default=0.0)

    def bindings_are_executable() -> bool:
        return all(
            item["start_anchor_id"] == item["goal_anchor_id"]
            or bindings.get(str(item["start_anchor_id"])) != bindings.get(str(item["goal_anchor_id"]))
            for item in selected
        )

    while frontier and expansions < max_expansions:
        _priority, distance_cost, _order, pose_id = heapq.heappop(frontier)
        record = records[pose_id]
        point = (float(record["position"][0]), float(record["position"][1]))
        for anchor_id in needed_anchor_ids:
            distance_to_anchor = _distance(point, node_by_id[anchor_id].position)
            if distance_to_anchor <= terminal_radius and distance_to_anchor + 1e-9 < binding_distance.get(anchor_id, math.inf):
                bindings[anchor_id] = pose_id
                binding_distance[anchor_id] = distance_to_anchor
        if len(bindings) == len(needed_anchor_ids) and bindings_are_executable() and all(portal in crossings for portal in required_portals):
            break
        expansions += 1
        if expansions == 1 or expansions % 2_048 == 0:
            report(
                "action_lattice",
                min(0.88, 0.06 + 0.82 * expansions / max_expansions),
                expanded_state_count=expansions,
                frontier_count=len(frontier),
                bound_terminal_count=len(bindings),
                required_terminal_count=len(needed_anchor_ids),
            )
        for dx, dy in headings:
            candidate = (point[0] + dx, point[1] + dy)
            candidate_key = key(candidate)
            if candidate_key in seen or not allowed(candidate) or not _world_segment_safe(grid, point, candidate):
                continue
            order += 1
            child_id = f"motion_pose_{len(records) + 1:04d}"
            edge_id = f"motion_edge_{len(tree_edges) + 1:05d}"
            records[child_id] = {"motion_pose_id": child_id, "motion_node_id": child_id, "position": [candidate[0], candidate[1], 0.0], "parent": pose_id, "parent_edge_id": edge_id}
            crossed = sorted(portal for portal, segments in portal_segments.items() if any(_v3_crosses_portal_gate(point, candidate, start, end) for start, end in segments))
            tree_edges[edge_id] = {"motion_edge_id": edge_id, "source": pose_id, "target": child_id, "distance_m": step, "action": "move_forward", "edge_type": "portal_bridge" if crossed else "forward", "portal_ids": crossed, "portal_id": crossed[0] if crossed else None, "collision_free": True, "safety_certificate": {"clearance_m": float(cfg["effective_clearance_m"]), "world_segment_safe": True}}
            for portal in crossed:
                crossings.setdefault(portal, (pose_id, child_id))
            seen[candidate_key] = child_id
            child_cost = distance_cost + step
            heapq.heappush(frontier, (child_cost + heuristic(candidate), child_cost, order, child_id))
    missing_terminal_ids = sorted(set(needed_anchor_ids) - set(bindings))
    missing_portal_ids = sorted(set(required_portals) - set(crossings))
    report(
        "action_lattice",
        0.92,
        expanded_state_count=expansions,
        frontier_count=len(frontier),
        bound_terminal_count=len(bindings),
        required_terminal_count=len(needed_anchor_ids),
        unreachable_terminal_count=len(missing_terminal_ids),
    )
    if str(cfg["unreachable_terminal_policy"]) == "reject":
        if missing_terminal_ids:
            raise ValueError(
                "action_terminal_unreachable:" + ",".join(missing_terminal_ids)
                + f"; expanded={expansions}; frontier={len(frontier)}; bound={len(bindings)}/{len(needed_anchor_ids)}"
            )
        if missing_portal_ids:
            raise ValueError("portal_bypass:" + ",".join(missing_portal_ids))

    def route_portal_ids(item: Mapping[str, Any]) -> list[str]:
        portals: list[str] = []
        for edge in item["primary"].edges:
            portal_id = str((edge.extras or {}).get("portal") or "")
            if portal_id and portal_id not in portals:
                portals.append(portal_id)
        return portals

    # A deferred request is deliberately not represented by an action edge.
    # It remains visible in the sidecar/UI as a repair target, rather than
    # inviting a wall-crossing or an arbitrary long bridge into the backbone.
    executable_selected: list[Mapping[str, Any]] = []
    deferred_reasons: dict[str, list[str]] = {}
    for item in selected:
        request_id = str(item["request_id"])
        reasons: list[str] = []
        for anchor_id in (str(item["start_anchor_id"]), str(item["goal_anchor_id"])):
            if anchor_id in missing_terminal_ids:
                reasons.append(f"action_terminal_unreachable:{anchor_id}")
        if not reasons and bindings.get(str(item["start_anchor_id"])) == bindings.get(str(item["goal_anchor_id"])):
            reasons.append("action_terminal_collapsed")
        for portal_id in route_portal_ids(item):
            if portal_id in missing_portal_definitions:
                reasons.append(f"portal_not_certified:{portal_id}")
            elif portal_id in missing_portal_ids:
                reasons.append(f"portal_bypass:{portal_id}")
        if reasons:
            deferred_reasons[request_id] = reasons
        else:
            executable_selected.append(item)
    if not executable_selected:
        details = "; ".join(
            f"{request_id}={','.join(reasons)}"
            for request_id, reasons in sorted(deferred_reasons.items())
        )
        raise ValueError("no_executable_action_routes; " + details)

    def root_chain(pose_id: str) -> list[str]:
        result = [pose_id]
        while records[result[-1]]["parent"] is not None:
            result.append(str(records[result[-1]]["parent"]))
        return list(reversed(result))

    def tree_path(source: str, target: str) -> tuple[list[str], list[str]]:
        left, right = root_chain(source), root_chain(target)
        prefix = 0
        while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
            prefix += 1
        nodes = list(reversed(left[prefix - 1:])) + right[prefix:]
        edge_ids = [str(records[node]["parent_edge_id"]) for node in reversed(left[prefix:])]
        edge_ids.extend(str(records[node]["parent_edge_id"]) for node in right[prefix:])
        return nodes, edge_ids

    def append_path(nodes: list[str], edges: list[str], extra_nodes: list[str], extra_edges: list[str]) -> None:
        if not nodes:
            nodes.extend(extra_nodes); edges.extend(extra_edges); return
        if not extra_nodes or nodes[-1] != extra_nodes[0]:
            raise ValueError("action_route_discontinuity")
        nodes.extend(extra_nodes[1:]); edges.extend(extra_edges)

    candidate_routes: list[dict[str, Any]] = []
    for item in executable_selected:
        current = bindings[str(item["start_anchor_id"])]
        route_nodes = [current]
        route_edges: list[str] = []
        portal_ids = route_portal_ids(item)
        for portal in portal_ids:
            side_a, side_b = crossings[portal]
            options = [(side_a, side_b), (side_b, side_a)]
            source, target = min(options, key=lambda pair: len(tree_path(current, pair[0])[1]))
            nodes, edges = tree_path(current, source)
            append_path(route_nodes, route_edges, nodes, edges)
            crossing_edge = str(records[target]["parent_edge_id"] if records[target]["parent"] == source else records[source]["parent_edge_id"])
            append_path(route_nodes, route_edges, [source, target], [crossing_edge])
            current = target
        nodes, edges = tree_path(current, bindings[str(item["goal_anchor_id"])])
        append_path(route_nodes, route_edges, nodes, edges)
        if len(route_nodes) != len(route_edges) + 1:
            raise ValueError(f"route_sequence_invalid:{item['request_id']}")
        candidate_routes.append({"request_id": item["request_id"], "start_anchor_id": item["start_anchor_id"], "goal_anchor_id": item["goal_anchor_id"], "scenario": item["scenario"], "feature_ids": list(item["feature_ids"]), "portal_ids": portal_ids, "primary": {"route_id": item["request_id"], "motion_pose_ids": route_nodes, "motion_node_ids": route_nodes, "motion_edge_ids": route_edges, "is_alternative": False}, "alternatives": []})
    # Route selection estimated the anchor cost, but the canonical 0.25 m
    # lattice can still make that estimate too optimistic.  Keep the first
    # coverage-ranked routes whose *root-closed* action geometry fits the
    # physical pose budget; defer the rest with a visible repair status.
    route_closures: dict[str, tuple[set[str], set[str]]] = {}
    for route in candidate_routes:
        route_pose_ids = {str(item) for item in route["primary"]["motion_node_ids"]}
        route_edge_ids = {str(item) for item in route["primary"]["motion_edge_ids"]}
        closure_seeds = [
            bindings[str(route["start_anchor_id"])],
            bindings[str(route["goal_anchor_id"])],
            *(pose for portal_id in route["portal_ids"] for pose in crossings[portal_id]),
        ]
        for pose_id in closure_seeds:
            chain = root_chain(pose_id)
            route_pose_ids.update(chain)
            route_edge_ids.update(str(records[item]["parent_edge_id"]) for item in chain[1:])
        route_closures[str(route["request_id"])] = (route_pose_ids, route_edge_ids)

    routes: list[dict[str, Any]] = []
    used_pose_ids: set[str] = {"motion_pose_0001"}
    used_edge_ids: set[str] = set()
    for route in candidate_routes:
        route_pose_ids, route_edge_ids = route_closures[str(route["request_id"])]
        if len(used_pose_ids | route_pose_ids) > int(cfg["max_motion_poses"]):
            deferred_reasons.setdefault(str(route["request_id"]), []).append(
                "canonical_backbone_exceeds_motion_pose_budget"
            )
            continue
        routes.append(route)
        used_pose_ids.update(route_pose_ids)
        used_edge_ids.update(route_edge_ids)
    if not routes:
        raise ValueError("no_executable_action_routes_within_motion_pose_budget")
    report(
        "action_backbone",
        1.0,
        route_count=len(routes),
        deferred_request_count=len(deferred_reasons),
        motion_pose_count=len(used_pose_ids),
    )

    executable_request_ids = {str(route["request_id"]) for route in routes}
    executable_selected = [
        item for item in executable_selected
        if str(item["request_id"]) in executable_request_ids
    ]
    executable_anchor_ids = {
        str(item[key])
        for item in executable_selected
        for key in ("start_anchor_id", "goal_anchor_id")
    }
    executable_portal_ids = {
        portal_id
        for item in executable_selected
        for portal_id in route_portal_ids(item)
    }
    budget_deferred_terminal_ids = sorted({
        str(item[key])
        for item in candidate_routes
        if str(item["request_id"]) not in executable_request_ids
        for key in ("start_anchor_id", "goal_anchor_id")
        if str(item[key]) not in executable_anchor_ids
    })
    poses: list[dict[str, Any]] = []
    portal_pose_ids = {
        pose
        for portal_id, pair in crossings.items()
        if portal_id in executable_portal_ids
        for pose in pair
    }
    for pose_id in sorted(used_pose_ids):
        record = records[pose_id]
        tags = []
        anchors = [anchor_id for anchor_id in executable_anchor_ids if _distance(record["position"], node_by_id[anchor_id].position) <= terminal_radius]
        if anchors: tags.append("anchor")
        if pose_id in portal_pose_ids: tags.append("portal")
        # Do not round a lattice pose before the final validator.  At a 5 cm
        # grid boundary, even a 1e-10 perturbation can flip ``world_to_cell``
        # and turn a chord accepted during search into ``unsafe_forward`` on
        # the serialized graph.  JSON preserves Python floats round-trip.
        poses.append({"motion_pose_id": pose_id, "motion_node_id": pose_id, "position": [float(record["position"][0]), float(record["position"][1]), 0.0], "anchor_node_ids": anchors, "tags": tags})
    edges = [dict(tree_edges[edge_id]) for edge_id in sorted(used_edge_ids)]
    route_edge_ids = {edge_id for route in routes for edge_id in route["primary"]["motion_edge_ids"]}
    for edge in edges:
        if edge["motion_edge_id"] not in route_edge_ids and edge["edge_type"] == "forward":
            edge["edge_type"] = "backbone_connector"
    detached_terminal_subgraphs: list[dict[str, Any]] = []
    detached_terminal_specs = [
        *( (anchor_id, "action_terminal_unreachable") for anchor_id in missing_terminal_ids ),
        *( (anchor_id, "canonical_backbone_exceeds_motion_pose_budget") for anchor_id in budget_deferred_terminal_ids if anchor_id not in missing_terminal_ids ),
    ]
    for index, (anchor_id, reason) in enumerate(detached_terminal_specs, start=1):
        nearest_pose_id = min(
            used_pose_ids,
            key=lambda pose_id: _distance(records[pose_id]["position"], node_by_id[anchor_id].position),
        )
        terminal_position = [
            round(float(node_by_id[anchor_id].position[0]), 10),
            round(float(node_by_id[anchor_id].position[1]), 10),
            0.0,
        ]
        nearest_position = [
            round(float(records[nearest_pose_id]["position"][0]), 10),
            round(float(records[nearest_pose_id]["position"][1]), 10),
            0.0,
        ]
        detached_terminal_subgraphs.append({
            "subgraph_id": f"detached_terminal_{index:03d}",
            "anchor_node_ids": [anchor_id],
            "terminal_position": terminal_position,
            "reason": reason,
            "nearest_reachable_motion_pose_id": nearest_pose_id,
            "nearest_reachable_position": nearest_position,
            "advisory_distance_m": round(_distance(terminal_position, nearest_position), 4),
            "guide": {
                "kind": "inspect_clearance_or_add_safe_connector",
                "message": "Dashed advisory connectors are not action edges. Inspect clearance, traversable mask, and portal geometry, then rebuild.",
            },
        })
    deferred_requests = [
        {"request_id": request_id, "reasons": reasons}
        for request_id, reasons in sorted(deferred_reasons.items())
    ]
    return {"nodes": poses, "edges": edges, "portal_segments": {key: [[list(a), list(b)] for a, b in value] for key, value in portal_segments.items()}}, routes, {
        "expanded_state_count": len(records),
        "expanded_edge_count": len(tree_edges),
        "corridor_radius_m": corridor_radius,
        "connector_count": len(connector_paths),
        "root_anchor_id": root_anchor_id,
        "unreachable_terminal_ids": missing_terminal_ids,
        "budget_deferred_terminal_ids": budget_deferred_terminal_ids,
        "unreachable_portal_ids": missing_portal_ids,
        "deferred_request_ids": sorted(deferred_reasons),
        "deferred_requests": deferred_requests,
        "executable_request_ids": [str(item["request_id"]) for item in executable_selected],
        "detached_terminal_subgraphs": detached_terminal_subgraphs,
        "coverage_status": "partial" if deferred_reasons else "complete",
    }


def _v3_attach_states(motion: dict[str, Any], routes: list[dict[str, Any]], cfg: Mapping[str, Any]) -> None:
    poses = {str(item["motion_node_id"]): item for item in motion["nodes"]}
    edges = {str(item["motion_edge_id"]): item for item in motion["edges"]}
    states: dict[tuple[str, str], dict[str, Any]] = {}
    transitions: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    def state(pose_id: str, heading_id: str) -> str:
        item = states.setdefault((pose_id, heading_id), {"motion_state_id": f"state_{len(states) + 1:05d}", "motion_pose_id": pose_id, "motion_node_id": pose_id, "heading_id": heading_id})
        return str(item["motion_state_id"])
    def transition(source: str, target: str, action: str, **extras: Any) -> str:
        identity = (source, target, action, str(extras.get("motion_edge_id") or extras.get("turn_deg")))
        item = transitions.setdefault(identity, {"transition_id": f"transition_{len(transitions) + 1:05d}", "source_state_id": source, "target_state_id": target, "action": action, **extras})
        return str(item["transition_id"])
    for route in routes:
        primary = route["primary"]; pose_ids = list(primary["motion_node_ids"]); edge_ids = list(primary["motion_edge_ids"])
        if not edge_ids:
            raise ValueError(f"route_has_no_action:{route['request_id']}")
        first_heading = _heading_id(_yaw_to(poses[pose_ids[0]]["position"], poses[pose_ids[1]]["position"]))
        current_heading, current_state = first_heading, state(pose_ids[0], first_heading)
        state_ids, transition_ids = [current_state], []
        for index, edge_id in enumerate(edge_ids):
            source_id, target_id, edge = pose_ids[index], pose_ids[index + 1], edges[edge_id]
            if _edge_key(str(edge["source"]), str(edge["target"])) != _edge_key(source_id, target_id):
                raise ValueError(f"route_edge_mismatch:{route['request_id']}:{edge_id}")
            desired = _heading_id(_yaw_to(poses[source_id]["position"], poses[target_id]["position"]))
            delta = (int(desired.split("_")[1]) - int(current_heading.split("_")[1])) // 15
            delta = ((delta + 12) % 24) - 12
            for _ in range(abs(delta)):
                next_heading = _heading_id((int(current_heading.split("_")[1]) + (15 if delta > 0 else -15)) % 360)
                next_state = state(source_id, next_heading)
                transition_ids.append(transition(current_state, next_state, "turn_left" if delta > 0 else "turn_right", turn_deg=15.0 if delta > 0 else -15.0))
                state_ids.append(next_state); current_state, current_heading = next_state, next_heading
            next_state = state(target_id, desired)
            transition_ids.append(transition(current_state, next_state, "move_forward", motion_edge_id=edge_id, distance_m=float(edge["distance_m"]), forward_m=float(edge["distance_m"]), edge_type=str(edge.get("edge_type") or "forward"), portal_ids=list(edge.get("portal_ids") or []), safety_certificate=dict(edge.get("safety_certificate") or {})))
            state_ids.append(next_state); current_state, current_heading = next_state, desired
        primary.update({"initial_heading_id": first_heading, "state_ids": state_ids, "transition_ids": transition_ids})
    if len(states) > int(cfg["max_action_states"]):
        raise ValueError("canonical_backbone_exceeds_action_state_budget")
    motion.update({"poses": motion["nodes"], "states": list(states.values()), "transitions": list(transitions.values())})


def validate_adaptive_route_motion_v3(motion_graph: Mapping[str, Any], *, motion_grid: TraversabilityGrid | None = None) -> dict[str, Any]:
    if str(motion_graph.get("profile_id") or "") != PROFILE_ID:
        raise ValueError("motion graph is not adaptive_route_motion_v3")
    poses = {str(item.get("motion_node_id")): item for item in motion_graph.get("poses") or motion_graph.get("nodes") or [] if isinstance(item, Mapping)}
    edges = {str(item.get("motion_edge_id")): item for item in motion_graph.get("edges", []) if isinstance(item, Mapping)}
    portal_segments: dict[str, list[tuple[Sequence[float], Sequence[float]]]] = {}
    raw_portal_segments = motion_graph.get("portal_segments") or {}
    if not isinstance(raw_portal_segments, Mapping):
        raise ValueError("portal_segments_invalid")
    for portal_id, raw_segments in raw_portal_segments.items():
        parsed: list[tuple[Sequence[float], Sequence[float]]] = []
        if not isinstance(raw_segments, list):
            raise ValueError(f"portal_segments_invalid:{portal_id}")
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, Sequence) or len(raw_segment) != 2:
                raise ValueError(f"portal_segment_invalid:{portal_id}")
            start, end = raw_segment
            if not isinstance(start, Sequence) or not isinstance(end, Sequence) or len(start) < 2 or len(end) < 2:
                raise ValueError(f"portal_segment_invalid:{portal_id}")
            parsed.append((start, end))
        portal_segments[str(portal_id)] = parsed
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge_id, edge in edges.items():
        source, target = poses.get(str(edge.get("source"))), poses.get(str(edge.get("target")))
        if source is None or target is None: raise ValueError(f"motion edge references unknown pose:{edge_id}")
        if not math.isclose(_distance(source["position"], target["position"]), 0.25, abs_tol=0.025): raise ValueError(f"non_normalized_forward:{edge_id}")
        yaw = _yaw_to(source["position"], target["position"])
        if not math.isclose(yaw / 15.0, round(yaw / 15.0), abs_tol=1e-6): raise ValueError(f"non_lattice_heading:{edge_id}")
        if motion_grid is not None and not _world_segment_safe(motion_grid, source["position"], target["position"]): raise ValueError(f"unsafe_forward:{edge_id}")
        edge_portals = {str(portal_id) for portal_id in edge.get("portal_ids") or []}
        if edge.get("edge_type") == "portal_bridge" and not edge_portals:
            raise ValueError(f"portal_bridge_missing_id:{edge_id}")
        for portal_id in edge_portals:
            segments = portal_segments.get(portal_id) or []
            if not segments:
                raise ValueError(f"portal_transition_not_certified:{edge_id}:{portal_id}")
            if not any(_v3_crosses_portal_gate(source["position"], target["position"], start, end) for start, end in segments):
                raise ValueError(f"portal_transition_does_not_cross_corridor:{edge_id}:{portal_id}")
        adjacency[str(edge["source"])].add(str(edge["target"])); adjacency[str(edge["target"])].add(str(edge["source"]))
    if poses:
        seen, stack = set(), [next(iter(poses))]
        while stack:
            item = stack.pop()
            if item in seen: continue
            seen.add(item); stack.extend(adjacency[item] - seen)
        if seen != set(poses): raise ValueError("action_backbone_disconnected")
    states = {str(item.get("motion_state_id")): item for item in motion_graph.get("states") or [] if isinstance(item, Mapping)}
    transitions = {str(item.get("transition_id")): item for item in motion_graph.get("transitions") or [] if isinstance(item, Mapping)}
    for route in motion_graph.get("routes", []):
        primary = route.get("primary") or {}; node_ids = list(primary.get("motion_node_ids") or []); edge_ids = list(primary.get("motion_edge_ids") or [])
        state_ids, transition_ids = list(primary.get("state_ids") or []), list(primary.get("transition_ids") or [])
        traversed_portals: set[str] = set()
        if len(node_ids) != len(edge_ids) + 1 or len(state_ids) != len(transition_ids) + 1: raise ValueError(f"route_sequence_length:{route.get('request_id')}")
        for index, edge_id in enumerate(edge_ids):
            edge = edges.get(str(edge_id))
            if edge is None or _edge_key(str(edge["source"]), str(edge["target"])) != _edge_key(str(node_ids[index]), str(node_ids[index + 1])): raise ValueError(f"route_edge_mismatch:{route.get('request_id')}:{edge_id}")
        for index, transition_id in enumerate(transition_ids):
            transition = transitions.get(str(transition_id)); source = states.get(str(state_ids[index])); target = states.get(str(state_ids[index + 1]))
            if transition is None or source is None or target is None or transition.get("source_state_id") != state_ids[index] or transition.get("target_state_id") != state_ids[index + 1]: raise ValueError(f"route_transition_mismatch:{route.get('request_id')}:{transition_id}")
            if transition["action"] in ("turn_left", "turn_right"):
                expected = 15.0 if transition["action"] == "turn_left" else -15.0
                if source.get("motion_pose_id") != target.get("motion_pose_id") or not math.isclose(float(transition.get("turn_deg") or 0.0), expected, abs_tol=1e-9): raise ValueError(f"invalid_turn:{transition_id}")
            elif transition["action"] == "move_forward":
                if transition.get("motion_edge_id") not in edges or source.get("motion_pose_id") == target.get("motion_pose_id"): raise ValueError(f"invalid_forward:{transition_id}")
                traversed_portals.update(str(portal_id) for portal_id in transition.get("portal_ids") or [])
            else: raise ValueError(f"invalid_action:{transition_id}")
        required_portals = {str(portal_id) for portal_id in route.get("portal_ids") or []}
        missing_portals = sorted(required_portals - traversed_portals)
        if missing_portals:
            raise ValueError(f"route_portal_bypass:{route.get('request_id')}:{','.join(missing_portals)}")
    return {"ok": True, "pose_count": len(poses), "edge_count": len(edges), "state_count": len(states), "transition_count": len(transitions), "backbone_component_count": 1 if poses else 0}


def build_adaptive_route_motion(
    anchor_graph: ViewpointGraph,
    *,
    annotation: SceneAnnotation | None = None,
    config: Mapping[str, Any] | None = None,
    motion_grid: TraversabilityGrid | None = None,
    on_progress: Callable[[str, float, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Build a certified connected core and explicitly defer unsafe terminals.

    The saved motion graph is always one connected, fully validated component.
    A terminal outside that component is a repair task, not a licence to add a
    long edge, interpolate through a wall, or silently omit an episode.
    """
    def report(stage: str, fraction: float, **detail: Any) -> None:
        if on_progress is not None:
            on_progress(stage, min(1.0, max(0.0, float(fraction))), detail)

    cfg = _merged_config(config)
    if motion_grid is None:
        raise ValueError("adaptive_route_motion_v3 requires a clearance-eroded motion grid")
    if len(anchor_graph.nodes) > int(cfg["max_anchor_nodes"]) or anchor_graph.node_heading_count != 24:
        raise ValueError("adaptive_route_motion_v3 requires <= max anchors and 24 headings")
    report("anchor_spanner", 0.02, anchor_node_count=len(anchor_graph.nodes))
    spanner = build_anchor_spanner(anchor_graph, stretch=float(cfg["spanner_stretch"]))
    report("portal_grid", 0.08, anchor_edge_count=len(spanner.edges))
    effective_grid, restored_portals = _v3_portal_aware_grid(spanner, motion_grid)
    report("request_catalogue", 0.16, restored_portal_count=len(restored_portals))
    candidates, required_features, catalogue_meta = _candidate_requests(
        spanner, annotation, cfg, motion_grid=effective_grid,
    )
    report("request_selection", 0.25, candidate_request_count=len(candidates), required_feature_count=len(required_features))
    selected, selected_coverage, warnings = _select_requests(
        candidates, spanner, cfg, required_features, motion_grid=effective_grid,
    )
    if not selected:
        raise ValueError("adaptive_route_motion_v3 has no selected navigation requests")
    initial_missing = set(required_features) - set(selected_coverage)
    if initial_missing and str(cfg["unreachable_terminal_policy"]) == "reject":
        raise ValueError("adaptive_route_motion_v3 coverage incomplete: " + ", ".join(sorted(initial_missing)))

    report("action_lattice", 0.32, selected_request_count=len(selected))
    motion, routes, search_diagnostics = _v3_build_action_tree(
        spanner,
        selected,
        cfg,
        effective_grid,
        on_progress=lambda stage, fraction, detail: report(
            stage,
            0.32 + 0.48 * fraction,
            **dict(detail),
        ),
    )
    report("action_states", 0.82, motion_pose_count=len(motion["nodes"]), route_count=len(routes))
    _v3_attach_states(motion, routes, cfg)
    executable_request_ids = {
        str(item) for item in search_diagnostics.get("executable_request_ids") or []
    }
    deferred_by_id = {
        str(item.get("request_id")): [str(reason) for reason in item.get("reasons") or []]
        for item in search_diagnostics.get("deferred_requests") or []
        if isinstance(item, Mapping) and item.get("request_id")
    }
    executable_coverage = {
        str(feature)
        for item in selected
        if str(item["request_id"]) in executable_request_ids
        for feature in item.get("feature_ids") or []
    }
    missing_features = set(required_features) - executable_coverage
    partial_coverage = bool(missing_features or deferred_by_id)
    if initial_missing:
        warnings = [*warnings, "request_catalogue_missing:" + ",".join(sorted(initial_missing))]
    if deferred_by_id:
        warnings = [*warnings, f"deferred_action_requests:{len(deferred_by_id)}"]

    motion_graph = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "scene_id": spanner.scene_id,
        "anchor_graph_id": spanner.graph_id,
        "heading_count": 24,
        "turn_deg": 15.0,
        "forward_step_m": 0.25,
        "forward_tolerance_m": 0.025,
        "effective_clearance_m": float(cfg["effective_clearance_m"]),
        "coverage_status": "partial" if partial_coverage else "complete",
        "detached_terminal_subgraphs": list(search_diagnostics.get("detached_terminal_subgraphs") or []),
        "nodes": motion["nodes"],
        "poses": motion["poses"],
        "edges": motion["edges"],
        "states": motion["states"],
        "transitions": motion["transitions"],
        "routes": routes,
        "portal_segments": motion["portal_segments"],
    }
    report("validation", 0.88, motion_edge_count=len(motion["edges"]), action_state_count=len(motion["states"]))
    validation = validate_adaptive_route_motion_v3(motion_graph, motion_grid=effective_grid)
    digest = sha1(json.dumps({"profile_id": PROFILE_ID, "config": cfg, "motion": motion_graph}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    motion_graph.update({"profile_digest": digest, "validation": {**validation, "digest": digest}})
    report("observation_plan", 0.94, route_count=len(routes))
    observation_plan = _build_observation_plan(motion_graph, routes, cfg)
    observation_plan.update({
        "scene_id": spanner.scene_id,
        "anchor_graph_id": spanner.graph_id,
        "profile_digest": digest,
        "validation_digest": digest,
        "motion_graph_ref": "motion_graph.json",
        "config": cfg,
        "coverage_status": "partial" if partial_coverage else "complete",
        "missing_feature_ids": sorted(missing_features),
    })
    navigation_requests = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": PROFILE_ID,
        "anchor_graph_id": spanner.graph_id,
        "profile_digest": digest,
        "requests": [
            {
                "request_id": item["request_id"],
                "start_anchor_id": item["start_anchor_id"],
                "goal_anchor_id": item["goal_anchor_id"],
                "scenario": item["scenario"],
                "feature_ids": item["feature_ids"],
                "primary_anchor_path": list(item["primary"].nodes),
                "status": "executable" if str(item["request_id"]) in executable_request_ids else "deferred",
                "deferred_reasons": deferred_by_id.get(str(item["request_id"]), []),
            }
            for item in selected
        ],
        "catalogue": catalogue_meta,
        "coverage": {
            "status": "partial" if partial_coverage else "complete",
            "required_feature_ids": sorted(required_features),
            "covered_feature_ids": sorted(executable_coverage),
            "missing_feature_ids": sorted(missing_features),
        },
    }
    diagnostics = {
        "anchor_node_count": len(spanner.nodes),
        "anchor_edge_count": len(spanner.edges),
        "motion_pose_count": len(motion["nodes"]),
        "motion_edge_count": len(motion["edges"]),
        "action_state_count": len(motion["states"]),
        "transition_count": len(motion["transitions"]),
        "backbone_component_count": 1,
        "request_count": len(routes),
        "selected_request_count": len(selected),
        "deferred_request_count": len(deferred_by_id),
        "coverage_status": "partial" if partial_coverage else "complete",
        "required_feature_count": len(required_features),
        "covered_feature_count": len(executable_coverage),
        "missing_feature_ids": sorted(missing_features),
        "observation": dict(observation_plan["summary"]),
        "warnings": warnings,
        "validation_digest": digest,
        "portal_grid_overrides": restored_portals,
        **search_diagnostics,
    }
    # Persist diagnostics with the graph so a later GET can give the editor the
    # same repair guidance as the build response.  It is intentionally outside
    # the action-graph digest: it never changes executable geometry.
    motion_graph["generation_diagnostics"] = diagnostics
    report(
        "complete",
        1.0,
        motion_pose_count=len(motion["nodes"]),
        route_count=len(routes),
        deferred_request_count=len(deferred_by_id),
    )
    return {
        "anchor_graph": viewpoint_graph_to_payload(spanner),
        "navigation_requests": navigation_requests,
        "motion_graph": motion_graph,
        "observation_plan": observation_plan,
        "generation_diagnostics": diagnostics,
    }


def expand_motion_route_actions(motion_graph: Mapping[str, Any], route_id: str, *, initial_heading_id: str | None = None) -> list[dict[str, Any]]:
    """Read v3 transition IDs directly; no legacy edge/heading reinterpretation."""
    if str(motion_graph.get("profile_id") or "") != PROFILE_ID: raise ValueError("motion graph is not adaptive_route_motion_v3")
    validate_adaptive_route_motion_v3(motion_graph)
    poses = {str(item["motion_node_id"]): item for item in motion_graph.get("poses") or motion_graph.get("nodes") or [] if isinstance(item, Mapping)}
    states = {str(item["motion_state_id"]): item for item in motion_graph.get("states") or [] if isinstance(item, Mapping)}
    transitions = {str(item["transition_id"]): item for item in motion_graph.get("transitions") or [] if isinstance(item, Mapping)}
    route = next((item for item in motion_graph.get("routes") or [] if isinstance(item, Mapping) and item.get("request_id") == route_id), None)
    if route is None: raise KeyError(f"unknown motion route: {route_id}")
    primary = route.get("primary") or {}; state_ids, transition_ids = list(primary.get("state_ids") or []), list(primary.get("transition_ids") or [])
    rows: list[dict[str, Any]] = []
    for index, transition_id in enumerate(transition_ids):
        source = states[str(state_ids[index])]; transition = transitions[str(transition_id)]; pose = poses[str(source["motion_pose_id"])]
        extras = {"motion_profile": PROFILE_ID, "transition_id": transition_id, **{key: value for key, value in transition.items() if key not in {"transition_id", "source_state_id", "target_state_id", "action"}}}
        rows.append({"motion_node_id": str(source["motion_pose_id"]), "heading_id": str(source["heading_id"]), "action": str(transition["action"]), "agent_pose": [float(pose["position"][0]), float(pose["position"][1]), math.radians(float(str(source["heading_id"]).split("_")[1]))], "extras": extras})
    final = states[str(state_ids[-1])]; pose = poses[str(final["motion_pose_id"])]
    rows.append({"motion_node_id": str(final["motion_pose_id"]), "heading_id": str(final["heading_id"]), "action": "stop", "agent_pose": [float(pose["position"][0]), float(pose["position"][1]), math.radians(float(str(final["heading_id"]).split("_")[1]))], "extras": {"motion_profile": PROFILE_ID}})
    return rows
