from __future__ import annotations

import math
import random
from typing import Callable

import numpy as np

from .traversability import TraversabilityGrid, cell_to_world, inflate_traversable_grid, world_to_cell
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
    robot_radius_m: float = 0.0,
    seed: int = 0,
    on_progress: Callable[[float], None] | None = None,
    region_mask: "np.ndarray | None" = None,
    opening_seeds: "list[tuple[float, float]] | None" = None,
) -> list[ViewpointNode]:
    """Sample viewpoint nodes from a traversability grid.

    ``region_mask`` (when provided) restricts sampling to cells where the mask is
    True. Useful for local regeneration of a single bbox.

    ``opening_seeds`` are world (x, y) points (e.g. doorway / passage thresholds)
    where a viewpoint is force-placed if the cell is traversable, ignoring
    ``min_node_spacing_m``. The Poisson pass then respects spacing from the seeds.
    Guarantees coverage at transitions the random sampler tends to miss.
    """
    if max_nodes <= 0:
        raise ValueError("max_nodes must be positive.")
    if min_node_spacing_m < 0:
        raise ValueError("min_node_spacing_m must be non-negative.")
    # Inflate obstacles by robot radius so nodes are never placed inside the clearance zone.
    sampling_traversable = inflate_traversable_grid(grid.traversable, robot_radius_m, grid.spec.resolution)
    if region_mask is not None:
        if region_mask.shape != sampling_traversable.shape:
            raise ValueError(
                f"region_mask shape {region_mask.shape} != grid shape {sampling_traversable.shape}"
            )
        sampling_traversable = sampling_traversable & region_mask
    candidates = [(int(x), int(y)) for y, x in np.argwhere(sampling_traversable)]
    if not candidates:
        raise ValueError("No traversable cells available for viewpoint sampling.")
    rng = random.Random(seed)
    rng.shuffle(candidates)
    selected: list[tuple[int, int, float, float, float]] = []
    # Force-place opening/doorway seeds first. The threshold cell itself may be
    # masked (a glass door is an obstacle), so snap to the nearest traversable
    # cell within a small radius — this lands a viewpoint right beside the door.
    snap_radius_cells = max(1, int(round(0.6 / grid.spec.resolution)))
    for seed_pt in opening_seeds or []:
        try:
            sx, sy = float(seed_pt[0]), float(seed_pt[1])
        except (TypeError, ValueError, IndexError):
            continue
        cx, cy = world_to_cell(grid.spec, sx, sy)
        best: tuple[int, int] | None = None
        best_d = None
        for dy in range(-snap_radius_cells, snap_radius_cells + 1):
            for dx in range(-snap_radius_cells, snap_radius_cells + 1):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < grid.spec.width and 0 <= ny < grid.spec.height):
                    continue
                if not bool(grid.traversable[ny, nx]):
                    continue
                dd = dx * dx + dy * dy
                if best_d is None or dd < best_d:
                    best_d, best = dd, (nx, ny)
        if best is None:
            continue
        nx, ny = best
        wx, wy = cell_to_world(grid.spec, nx, ny)
        if any(math.hypot(wx - s2x, wy - s2y) < grid.spec.resolution for _a, _b, s2x, s2y, _c in selected):
            continue
        selected.append((nx, ny, wx, wy, 0.0))
    total = len(candidates)
    report_every = max(1, total // 40)
    # Precompute distance transform only if clearance filtering is needed.
    clearance_map: np.ndarray | None = None
    if min_clearance_m > 0:
        obstacle_mask = ~grid.traversable
        obstacle_cells = np.argwhere(obstacle_mask)  # shape (N, 2) — [y, x]
        h, w = grid.traversable.shape
        if obstacle_cells.size == 0:
            clearance_map = np.full((h, w), np.inf, dtype=np.float32)
        else:
            ys = np.arange(h, dtype=np.float32)[:, None, None]
            xs = np.arange(w, dtype=np.float32)[None, :, None]
            clearance_map = np.full((h, w), np.inf, dtype=np.float32)
            # Vectorized over obstacles, looped over cells — split into chunks to avoid OOM.
            chunk = 512
            for start in range(0, len(obstacle_cells), chunk):
                batch = obstacle_cells[start:start + chunk]  # (B, 2)
                oy = batch[:, 0].astype(np.float32)  # (B,)
                ox = batch[:, 1].astype(np.float32)  # (B,)
                d = np.sqrt((ys - oy[None, None, :]) ** 2 + (xs - ox[None, None, :]) ** 2)
                clearance_map = np.minimum(clearance_map, d.min(axis=2))
            clearance_map = clearance_map * grid.spec.resolution
    for idx, (cell_x, cell_y) in enumerate(candidates):
        if on_progress is not None and idx % report_every == 0:
            on_progress(idx / total)
        if clearance_map is not None:
            clearance = float(clearance_map[cell_y, cell_x])
            if clearance < min_clearance_m:
                continue
        else:
            clearance = 0.0
        wx, wy = cell_to_world(grid.spec, cell_x, cell_y)
        too_close = any(math.hypot(wx - sx, wy - sy) < min_node_spacing_m for _cx, _cy, sx, sy, _clear in selected)
        if too_close:
            continue
        selected.append((cell_x, cell_y, wx, wy, clearance))
        if len(selected) >= max_nodes:
            break
    if on_progress is not None:
        on_progress(1.0)
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
