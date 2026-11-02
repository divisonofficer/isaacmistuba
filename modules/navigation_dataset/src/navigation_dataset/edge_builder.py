from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import numpy as np

from .traversability import TraversabilityGrid, cell_to_world, world_to_cell, inflate_traversable_grid
from .viewpoint_graph import ViewpointEdge, ViewpointNode


@dataclass(frozen=True)
class EdgeValidation:
    """Result of applying the graph's single edge-safety policy.

    ``mode`` is ``normal`` when every line cell is robot-traversable and
    ``doorway`` only for an edge certified by a resolved/inferred portal.  The
    latter intentionally permits the small floor-mesh discontinuity at a
    threshold; it never permits a body-height wall crossing.
    """

    accepted: bool
    mode: str
    reason: str
    distance_m: float
    wall_run_cells: int
    gap_run_cells: int
    hazard_crossing: bool
    portal_id: str | None = None
    # The clearance-eroded edge grid can legitimately be discontinuous around
    # a doorway even when the underlying floor-domain discontinuity is small.
    # Keep the latter separately so an explicit user-certified opening can be
    # considered without weakening automatic edge generation.
    raw_gap_run_cells: int = 0


def _distance(source: ViewpointNode, target: ViewpointNode) -> float:
    return float(math.hypot(
        float(target.position[0]) - float(source.position[0]),
        float(target.position[1]) - float(source.position[1]),
    ))


def _max_gap_run(cells: Iterable[tuple[int, int]], traversable: np.ndarray) -> int:
    height, width = traversable.shape
    run = maximum = 0
    for x, y in cells:
        if 0 <= x < width and 0 <= y < height and bool(traversable[y, x]):
            run = 0
        else:
            run += 1
            maximum = max(maximum, run)
    return maximum


def _max_wall_run(cells: Iterable[tuple[int, int]], wall_mask) -> int:
    if wall_mask is None:
        return 0
    height, width = wall_mask.shape
    run = maximum = 0
    for x, y in cells:
        if 0 <= x < width and 0 <= y < height and bool(wall_mask[y, x]):
            run += 1
            maximum = max(maximum, run)
        else:
            run = 0
    return maximum


def _certifying_portal(
    source: ViewpointNode,
    target: ViewpointNode,
    portals: Iterable[Any] | None,
    *,
    anchor_tolerance_m: float,
) -> Any | None:
    """Return a resolved portal actually crossed by the candidate segment.

    Portal anchors are local, but sparse place nodes can sit well inside their
    rooms.  A valid place-topology link may therefore cross a certified portal
    while neither endpoint is within the local-anchor tolerance.  The fallback
    below accepts that only when the segment runs through both sides of the
    same portal corridor; caller-side wall and floor-gap checks remain strict.
    """
    if portals is None:
        return None
    sx, sy = float(source.position[0]), float(source.position[1])
    tx, ty = float(target.position[0]), float(target.position[1])
    for portal in portals:
        if not bool(getattr(portal, "resolved", False)):
            continue
        ax, ay = getattr(portal, "side_a", (None, None))
        bx, by = getattr(portal, "side_b", (None, None))
        if None in (ax, ay, bx, by):
            continue
        ab = max(math.hypot(sx - float(ax), sy - float(ay)), math.hypot(tx - float(bx), ty - float(by)))
        ba = max(math.hypot(sx - float(bx), sy - float(by)), math.hypot(tx - float(ax), ty - float(ay)))
        if min(ab, ba) <= float(anchor_tolerance_m):
            return portal
        cx, cy = getattr(portal, "center", (None, None))
        if None in (cx, cy):
            continue
        dx, dy = tx - sx, ty - sy
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            continue

        def _project(px: float, py: float) -> tuple[float, float]:
            t = ((px - sx) * dx + (py - sy) * dy) / length_sq
            qx, qy = sx + t * dx, sy + t * dy
            return t, math.hypot(px - qx, py - qy)

        center_t, center_lateral = _project(float(cx), float(cy))
        side_a_t, side_a_lateral = _project(float(ax), float(ay))
        side_b_t, side_b_lateral = _project(float(bx), float(by))
        lateral_tolerance_m = 0.35
        projection_slack = 0.05
        if not (
            projection_slack <= center_t <= 1.0 - projection_slack
            and -projection_slack <= side_a_t <= 1.0 + projection_slack
            and -projection_slack <= side_b_t <= 1.0 + projection_slack
            and center_lateral <= lateral_tolerance_m
            and side_a_lateral <= lateral_tolerance_m
            and side_b_lateral <= lateral_tolerance_m
        ):
            continue
        # The two portal-side anchors must straddle the portal centre along
        # this segment; a merely nearby, parallel hallway is not certified.
        if (side_a_t - center_t) * (side_b_t - center_t) <= 0.0:
            return portal
    return None


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


def validate_viewpoint_edge(
    grid: TraversabilityGrid,
    source: ViewpointNode,
    target: ViewpointNode,
    *,
    robot_radius_m: float = 0.25,
    max_edge_length_m: float = 1.5,
    wall_mask=None,
    max_wall_cross_m: float = 0.0,
    doorway_grid: TraversabilityGrid | None = None,
    portals: Iterable[Any] | None = None,
    doorway_gap_m: float = 0.45,
    portal_anchor_tolerance_m: float = 0.75,
    traversable_mask: np.ndarray | None = None,
) -> EdgeValidation:
    """Validate an edge for automatic and manual graph paths alike.

    A normal edge must stay on the robot-traversable ``grid``.  A doorway edge is
    an intentionally narrow exception: it must match one known portal, stay clear
    of body-height walls, and span only a bounded gap in ``doorway_grid``.  Passing
    a precomputed ``traversable_mask`` keeps the O(N²) automatic builder fast.
    """
    distance = _distance(source, target)
    cells = _line_cells(grid, source.position, target.position)
    wall_run = _max_wall_run(cells, wall_mask)
    wall_tol = int(round(float(max_wall_cross_m) / grid.spec.resolution)) if wall_mask is not None else 0
    hazard = any(
        bool(grid.hazard[y, x])
        for x, y in cells
        if 0 <= x < grid.spec.width and 0 <= y < grid.spec.height
    )
    if distance > float(max_edge_length_m) + 1e-9:
        return EdgeValidation(False, "rejected", "too_far", distance, wall_run, 0, hazard)
    if wall_run > wall_tol:
        return EdgeValidation(False, "rejected", "crosses_wall", distance, wall_run, 0, hazard)

    traversable = traversable_mask
    if traversable is None:
        traversable = _dilated_traversable(grid, robot_radius_m)
    normal_gap = _max_gap_run(cells, traversable)
    if normal_gap == 0:
        return EdgeValidation(True, "normal", "ok", distance, wall_run, 0, hazard)

    raw_grid = doorway_grid or grid
    doorway_cells = _line_cells(raw_grid, source.position, target.position)
    raw_gap_run = _max_gap_run(doorway_cells, raw_grid.traversable)
    portal = _certifying_portal(
        source, target, portals, anchor_tolerance_m=portal_anchor_tolerance_m,
    )
    if portal is None:
        return EdgeValidation(
            False, "rejected", "not_certified_doorway", distance, wall_run,
            normal_gap, hazard, raw_gap_run_cells=raw_gap_run,
        )
    # A sampled line includes cells centred just inside both floor regions, so one
    # resolution cell of quantisation slack is required for a physical 0.45 m gap.
    gap_tol = max(1, int(math.ceil(float(doorway_gap_m) / raw_grid.spec.resolution)) + 1)
    if raw_gap_run > gap_tol:
        return EdgeValidation(False, "rejected", "doorway_gap_too_wide", distance, wall_run, raw_gap_run, hazard,
                              str(getattr(portal, "door_id", "")) or None, raw_gap_run)
    return EdgeValidation(True, "doorway", "certified_doorway", distance, wall_run, raw_gap_run, hazard,
                          str(getattr(portal, "door_id", "")) or None, raw_gap_run)


def user_certifiable_opening(
    validation: EdgeValidation,
    *,
    resolution_m: float,
    max_raw_gap_m: float = 1.0,
) -> bool:
    """Whether a user may explicitly certify a missing portal annotation.

    This is deliberately *not* part of automatic graph building.  It only
    applies when the body-height wall test is clean and the non-eroded floor
    domain has one short gap.  The resulting edge is stored as an auditable
    manual open portal and is restored into the support grid just like a
    geometry-certified inferred portal.
    """
    if validation.accepted or validation.reason != "not_certified_doorway":
        return False
    if validation.wall_run_cells != 0 or validation.hazard_crossing:
        return False
    if resolution_m <= 0.0 or max_raw_gap_m <= 0.0:
        return False
    # One grid cell of rasterisation slack, matching doorway validation.
    max_cells = max(1, int(math.ceil(float(max_raw_gap_m) / float(resolution_m))) + 1)
    return 0 < validation.raw_gap_run_cells <= max_cells


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
            validation = validate_viewpoint_edge(
                grid, source, target,
                robot_radius_m=robot_radius_m,
                max_edge_length_m=max_edge_length_m,
                wall_mask=wall_mask,
                max_wall_cross_m=max_wall_cross_m,
                traversable_mask=traversable,
            )
            if not validation.accepted:
                continue
            cells = _line_cells(grid, source.position, target.position)
            seen_pairs.add(pair)
            edge_id = f"edge_{source.node_id}_{target.node_id}"
            edge = ViewpointEdge(
                edge_id=edge_id,
                source=source.node_id,
                target=target.node_id,
                distance_m=float(distance),
                weight=float(distance),
                collision_free=True,
                hazard_crossing=bool(validation.hazard_crossing),
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
