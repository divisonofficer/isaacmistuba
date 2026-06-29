from __future__ import annotations

import math
from typing import Callable

import numpy as np

from .traversability import TraversabilityGrid, cell_to_world, world_to_cell, inflate_traversable_grid
from .viewpoint_graph import ViewpointEdge, ViewpointNode


def _dilated_traversable(grid: TraversabilityGrid, robot_radius_m: float) -> np.ndarray:
    return inflate_traversable_grid(grid.traversable, robot_radius_m, grid.spec.resolution)


def line_cells(grid: TraversabilityGrid, a: list[float], b: list[float]) -> list[tuple[int, int]]:
    """Public alias — return cell indices visited by the line from ``a`` to ``b``."""
    return _line_cells(grid, a, b)


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


def _max_run(values) -> int:
    run = mx = 0
    for v in values:
        if v:
            run += 1
            mx = max(mx, run)
        else:
            run = 0
    return mx


def build_viewpoint_edges(
    grid: TraversabilityGrid,
    nodes: list[ViewpointNode],
    *,
    robot_radius_m: float = 0.25,
    k_neighbors: int = 8,
    max_edge_length_m: float = 1.5,
    wall_mask=None,
    max_wall_cross_m: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
) -> list[ViewpointEdge]:
    """Connect viewpoint nodes to their nearest neighbours with collision-free edges.

    When ``wall_mask`` (a mesh-derived robot-body-height wall occupancy grid; see
    :func:`walkable_surface._wall_body_band_mask`) is supplied, an edge whose straight
    line crosses more than ``max_wall_cross_m`` of wall is rejected. The robot-radius
    erosion of the *floor* grid does NOT represent thin interior walls (their top-down
    footprint is degenerate), so without this an edge happily threads a wall instead of
    a doorway — the "connects rooms through a wall, ignoring the door" failure.
    """
    if k_neighbors <= 0:
        raise ValueError("k_neighbors must be positive.")
    if max_edge_length_m <= 0:
        raise ValueError("max_edge_length_m must be positive.")
    traversable = _dilated_traversable(grid, robot_radius_m)
    wall_tol = int(round(max_wall_cross_m / grid.spec.resolution)) if wall_mask is not None else 0
    wall_h, wall_w = (wall_mask.shape if wall_mask is not None else (0, 0))
    edges: list[ViewpointEdge] = []
    seen_pairs: set[tuple[str, str]] = set()
    total_nodes = len(nodes)
    for node_idx, source in enumerate(nodes):
        if on_progress is not None:
            on_progress(node_idx / total_nodes if total_nodes else 1.0)
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
            if wall_mask is not None and _max_run(
                0 <= x < wall_w and 0 <= y < wall_h and bool(wall_mask[y, x]) for x, y in cells
            ) > wall_tol:
                continue  # straight line punches through a wall — route via a doorway
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
    if on_progress is not None:
        on_progress(1.0)
    return edges


def graph_summary(nodes: list[ViewpointNode], edges: list[ViewpointEdge], *, heading_count: int) -> dict:
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "heading_count": int(heading_count),
        "hazard_edge_count": sum(1 for edge in edges if edge.hazard_crossing),
    }
