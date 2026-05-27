from __future__ import annotations

import math
import random

import numpy as np

from .traversability import TraversabilityGrid, cell_to_world
from .viewpoint_graph import ViewpointHeading, ViewpointNode


def heading_sweep(heading_count: int = 12) -> list[ViewpointHeading]:
    if heading_count <= 0:
        raise ValueError("heading_count must be positive.")
    step = 360.0 / float(heading_count)
    headings: list[ViewpointHeading] = []
    for index in range(heading_count):
        yaw = index * step
        headings.append(ViewpointHeading(heading_id=f"h_{int(round(yaw)):03d}", yaw_deg=float(yaw)))
    return headings


def _clearance_m(grid: TraversabilityGrid, cell_x: int, cell_y: int) -> float:
    obstacle_cells = np.argwhere(~grid.traversable)
    if obstacle_cells.size == 0:
        return float("inf")
    best = math.inf
    for oy, ox in obstacle_cells:
        distance_cells = math.hypot(int(ox) - cell_x, int(oy) - cell_y)
        best = min(best, distance_cells * grid.spec.resolution)
    return float(best)


def sample_viewpoint_nodes(
    grid: TraversabilityGrid,
    *,
    max_nodes: int = 300,
    heading_count: int = 12,
    min_node_spacing_m: float = 0.5,
    min_clearance_m: float = 0.0,
    seed: int = 0,
) -> list[ViewpointNode]:
    if max_nodes <= 0:
        raise ValueError("max_nodes must be positive.")
    if min_node_spacing_m < 0:
        raise ValueError("min_node_spacing_m must be non-negative.")
    candidates = [(int(x), int(y)) for y, x in np.argwhere(grid.traversable)]
    if not candidates:
        raise ValueError("No traversable cells available for viewpoint sampling.")
    rng = random.Random(seed)
    rng.shuffle(candidates)
    selected: list[tuple[int, int, float, float, float]] = []
    for cell_x, cell_y in candidates:
        clearance = _clearance_m(grid, cell_x, cell_y)
        if clearance < min_clearance_m:
            continue
        wx, wy = cell_to_world(grid.spec, cell_x, cell_y)
        too_close = any(math.hypot(wx - sx, wy - sy) < min_node_spacing_m for _cx, _cy, sx, sy, _clear in selected)
        if too_close:
            continue
        selected.append((cell_x, cell_y, wx, wy, clearance))
        if len(selected) >= max_nodes:
            break
    if not selected:
        raise ValueError("No viewpoint nodes survived spacing/clearance filters.")
    nodes: list[ViewpointNode] = []
    for index, (cell_x, cell_y, wx, wy, clearance) in enumerate(selected):
        tags = []
        if bool(grid.hazard[cell_y, cell_x]):
            tags.append("hazard_cell")
        nodes.append(
            ViewpointNode(
                node_id=f"vp_{index + 1:06d}",
                position=[float(wx), float(wy), 0.0],
                clearance_m=float(clearance if math.isfinite(clearance) else 9999.0),
                tags=tags,
                headings=heading_sweep(heading_count),
                extras={"cell": [int(cell_x), int(cell_y)]},
            )
        )
    return nodes
