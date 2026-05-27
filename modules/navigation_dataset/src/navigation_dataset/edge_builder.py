from __future__ import annotations

import math

import numpy as np

from .traversability import TraversabilityGrid, cell_to_world, world_to_cell
from .viewpoint_graph import ViewpointEdge, ViewpointNode


def _dilated_traversable(grid: TraversabilityGrid, robot_radius_m: float) -> np.ndarray:
    if robot_radius_m <= 0:
        return grid.traversable.copy()
    radius_cells = int(math.ceil(robot_radius_m / grid.spec.resolution))
    traversable = grid.traversable.copy()
    obstacle_cells = np.argwhere(~grid.traversable)
    for oy, ox in obstacle_cells:
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > radius_cells * radius_cells:
                    continue
                x = int(ox) + dx
                y = int(oy) + dy
                if 0 <= x < grid.spec.width and 0 <= y < grid.spec.height:
                    traversable[y, x] = False
    return traversable


def _line_cells(grid: TraversabilityGrid, a: list[float], b: list[float]) -> list[tuple[int, int]]:
    distance = math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
    steps = max(2, int(math.ceil(distance / max(grid.spec.resolution * 0.5, 1e-9))))
    cells: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for index in range(steps + 1):
        t = index / float(steps)
        x = float(a[0]) * (1.0 - t) + float(b[0]) * t
        y = float(a[1]) * (1.0 - t) + float(b[1]) * t
        cell = world_to_cell(grid.spec, x, y)
        if cell not in seen:
            seen.add(cell)
            cells.append(cell)
    return cells


def _edge_yaw_deg(source: ViewpointNode, target: ViewpointNode) -> float:
    dx = float(target.position[0]) - float(source.position[0])
    dy = float(target.position[1]) - float(source.position[1])
    return (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0


def build_viewpoint_edges(
    grid: TraversabilityGrid,
    nodes: list[ViewpointNode],
    *,
    robot_radius_m: float = 0.25,
    k_neighbors: int = 8,
    max_edge_length_m: float = 1.5,
) -> list[ViewpointEdge]:
    if k_neighbors <= 0:
        raise ValueError("k_neighbors must be positive.")
    if max_edge_length_m <= 0:
        raise ValueError("max_edge_length_m must be positive.")
    traversable = _dilated_traversable(grid, robot_radius_m)
    edges: list[ViewpointEdge] = []
    seen_pairs: set[tuple[str, str]] = set()
    for source in nodes:
        candidates: list[tuple[float, ViewpointNode]] = []
        for target in nodes:
            if source.node_id == target.node_id:
                continue
            distance = math.hypot(float(target.position[0]) - float(source.position[0]), float(target.position[1]) - float(source.position[1]))
            if distance <= max_edge_length_m:
                candidates.append((distance, target))
        candidates.sort(key=lambda item: (item[0], item[1].node_id))
        for distance, target in candidates[:k_neighbors]:
            pair = tuple(sorted((source.node_id, target.node_id)))
            if pair in seen_pairs:
                continue
            cells = _line_cells(grid, source.position, target.position)
            if any(not (0 <= x < grid.spec.width and 0 <= y < grid.spec.height and bool(traversable[y, x])) for x, y in cells):
                continue
            seen_pairs.add(pair)
            hazard_crossing = any(bool(grid.hazard[y, x]) for x, y in cells if 0 <= x < grid.spec.width and 0 <= y < grid.spec.height)
            edge_id = f"edge_{source.node_id}_{target.node_id}"
            edge = ViewpointEdge(
                edge_id=edge_id,
                source=source.node_id,
                target=target.node_id,
                distance_m=float(distance),
                weight=float(distance),
                collision_free=True,
                hazard_crossing=bool(hazard_crossing),
                path_polyline=[
                    [float(source.position[0]), float(source.position[1])],
                    [float(target.position[0]), float(target.position[1])],
                ],
                extras={
                    "source_cell": list(world_to_cell(grid.spec, source.position[0], source.position[1])),
                    "target_cell": list(world_to_cell(grid.spec, target.position[0], target.position[1])),
                    "edge_yaw_deg": _edge_yaw_deg(source, target),
                },
            )
            edges.append(edge)
    return edges


def graph_summary(nodes: list[ViewpointNode], edges: list[ViewpointEdge], *, heading_count: int) -> dict:
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "heading_count": int(heading_count),
        "hazard_edge_count": sum(1 for edge in edges if edge.hazard_crossing),
    }
