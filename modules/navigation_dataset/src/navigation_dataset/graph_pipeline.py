"""Shared viewpoint-graph build core.

``build_viewpoint_graph_core`` is the single entry point used by both the render
daemon's ``build_graph`` HTTP handler and the CLI ``cmd_graph_build``. It builds an
accurate mesh-derived walkable surface (see :mod:`.walkable_surface`) for Infinigen
imports, samples viewpoint nodes off the walls, connects them, and force-bridges
door portals — falling back to the legacy annotation grid for non-Infinigen scenes.

The core does NOT do HTTP, locking, edit-history logging, or revision bumps; those
stay at the call sites so behaviour there is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .edge_builder import build_viewpoint_edges, graph_summary
from .node_sampler import sample_viewpoint_nodes
from .traversability import (
    TraversabilityGrid,
    build_traversability_grid,
    cell_to_world,
    save_traversability_grid,
    world_to_cell,
)
from .viewpoint_graph import (
    ViewpointGraph,
    ViewpointNode,
    append_edge,
    compute_connected_components,
    find_object_overlapping_nodes,
    remove_nodes,
)
from .walkable_surface import WalkableSurface, build_walkable_surface


@dataclass
class GraphBuildResult:
    grid: TraversabilityGrid
    graph: ViewpointGraph
    surface: WalkableSurface | None
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class _GraphGrids:
    """Prepared traversability grids for node sampling + edge building.

    Shared by :func:`build_viewpoint_graph_core` and :func:`rebuild_viewpoint_edges`
    so both paths derive edges from the SAME surface/clearance logic. ``*_radius``
    is the dilation passed to :func:`build_viewpoint_edges`: ``0.0`` on the mesh
    path because the masks are already clearance-pre-eroded (avoids double erosion),
    ``robot_radius_m`` on the legacy annotation path.
    """

    grid: TraversabilityGrid
    node_grid: TraversabilityGrid
    edge_grid: TraversabilityGrid
    node_radius: float
    edge_radius: float
    sampler_min_clearance: float
    surface: WalkableSurface | None
    portals: list[Any]
    opening_seeds: list[Any]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_overlay_objects(scene_dir: Path) -> list[dict]:
    """Objects (with authoring-frame footprint geometry) from render_scene_overlays.json."""
    p = scene_dir / "render_scene_overlays.json"
    if not p.is_file():
        return []
    try:
        data = _read_json(p)
    except Exception:
        return []
    objs = data.get("objects") if isinstance(data, dict) else None
    return objs if isinstance(objs, list) else []


def _infinigen_inputs(scene_dir: Path) -> tuple[Path, list[float]] | None:
    """Return (import_root, origin_offset) when this scene is a mesh-backed Infinigen import."""
    am_path = scene_dir / "authoring_map.json"
    if not am_path.is_file():
        return None
    try:
        md = (_read_json(am_path) or {}).get("metadata") or {}
    except Exception:
        return None
    import_root = md.get("import_root")
    origin_offset = md.get("origin_offset")
    if not import_root or not isinstance(origin_offset, (list, tuple)) or len(origin_offset) < 3:
        return None
    # import_root is repo-relative; resolve against the repo root (scene_dir is
    # .../<repo>/out/opticalnav/<project>/scenes/<scene_id>).
    root = scene_dir
    for _ in range(5):
        root = root.parent
    cand = root / str(import_root)
    if not (cand / "scene_manifest.json").is_file():
        # Fall back to treating import_root as already absolute / cwd-relative.
        cand = Path(str(import_root))
        if not (cand / "scene_manifest.json").is_file():
            return None
    return cand, [float(v) for v in origin_offset[:3]]


def _line_clear(full_grid: TraversabilityGrid, a, b) -> bool:
    from .edge_builder import line_cells

    spec, trav = full_grid.spec, full_grid.traversable
    for x, y in line_cells(full_grid, a, b):
        if not (0 <= x < spec.width and 0 <= y < spec.height and bool(trav[y, x])):
            return False
    return True


def _max_gap_run_cells(full_grid: TraversabilityGrid, a, b) -> int:
    """Longest contiguous run of non-walkable cells along the a->b line.

    A real doorway/threshold between two rooms is a short run (the wall/threshold the
    floor mesh didn't bridge); a thick solid wall or an exterior void is a long run.
    Lets the connectivity repair bridge rooms whose doorway isn't in the grid (no
    door object, per-room floor meshes that stop at the threshold) without punching
    through thick walls.
    """
    from .edge_builder import line_cells

    spec, trav = full_grid.spec, full_grid.traversable
    run = mx = 0
    for x, y in line_cells(full_grid, a, b):
        if 0 <= x < spec.width and 0 <= y < spec.height and bool(trav[y, x]):
            run = 0
        else:
            run += 1
            mx = max(mx, run)
    return mx


def _max_wall_run_cells(wall_mask, spec, a, b) -> int:
    """Longest contiguous run of robot-body-height WALL cells along the a->b line.

    Uses the mesh-derived wall-band mask (sills/lintels excluded) so a real doorway —
    open at body height — reads as zero, while a straight line punched through a wall
    reads as the wall's thickness in cells. Repair rejects bridges with a non-trivial
    run so rooms connect through doorways, not through walls.
    """
    from .edge_builder import line_cells

    if wall_mask is None:
        return 0
    h, w = wall_mask.shape
    run = mx = 0
    for x, y in line_cells(TraversabilityGrid(spec=spec, traversable=wall_mask,
                                              hazard=wall_mask), a, b):
        if 0 <= x < w and 0 <= y < h and bool(wall_mask[y, x]):
            run += 1
            mx = max(mx, run)
        else:
            run = 0
    return mx


def _bfs_path_cells(full_grid: TraversabilityGrid, start_cell, goal_cell, max_steps: int):
    """4-connected BFS between two cells over the full walkable grid (bounded)."""
    from collections import deque

    spec, trav = full_grid.spec, full_grid.traversable
    sx, sy = start_cell
    gx, gy = goal_cell
    if not (0 <= sx < spec.width and 0 <= sy < spec.height and trav[sy, sx]):
        return None
    if not (0 <= gx < spec.width and 0 <= gy < spec.height and trav[gy, gx]):
        return None
    seen = {(sx, sy)}
    q = deque([(sx, sy, 0)])
    prev: dict[tuple[int, int], tuple[int, int]] = {}
    while q:
        x, y, dpt = q.popleft()
        if (x, y) == (gx, gy):
            path = [(x, y)]
            while (x, y) in prev:
                x, y = prev[(x, y)]
                path.append((x, y))
            return path[::-1]
        if dpt >= max_steps:
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < spec.width and 0 <= ny < spec.height and trav[ny, nx] and (nx, ny) not in seen:
                seen.add((nx, ny))
                prev[(nx, ny)] = (x, y)
                q.append((nx, ny, dpt + 1))
    return None


def _repair_connectivity(
    graph: ViewpointGraph,
    full_grid: TraversabilityGrid,
    *,
    max_bridge_m: float = 3.0,
    doorway_gap_m: float = 0.45,
    heading_count: int = 12,
    wall_mask=None,
    max_wall_cross_m: float = 0.0,
) -> tuple[int, int]:
    """Greedily reconnect disconnected components through real walkable space.

    1. straight bridge: add an edge when the line between two nodes stays inside the
       *full* (un-eroded) walkable grid — threads a wide doorway without crossing a
       wall. Reconnects rooms whose doorway eroded away for the edge builder.
    2. stepping-stone: when no straight bridge exists (misaligned / open doorway with
       no door object), BFS the full grid between the closest node pair, drop a node
       at the path's doorway midpoint, and connect both ends. Mirrors the manual node
       + bridge edges users add at thresholds.

    ``wall_mask`` (mesh-derived, robot-body-height; see
    :func:`walkable_surface._wall_body_band_mask`) gates BOTH passes: a bridge whose
    straight line crosses more than ``max_wall_cross_m`` of wall is rejected, so rooms
    connect through doorway openings instead of punching through walls. Without it the
    repair picked the smallest *grid* gap, which a thin interior wall satisfies just as
    well as a real doorway — the exact "connects rooms through a wall, ignoring the
    door" failure this guards against.

    Returns (straight_bridges, stepping_stone_nodes).
    """
    from .node_sampler import heading_sweep

    idmap = {n.node_id: n for n in graph.nodes}
    spec = full_grid.spec
    straight = 0
    stones = 0
    stone_seq = 0
    max_steps = int((max_bridge_m * 6.0) / spec.resolution)
    gap_tol = max(1, int(round(doorway_gap_m / spec.resolution)))
    # Tolerate at most this many body-height wall cells on a bridge line. 0 → reject
    # any wall contact (doorway openings read exactly 0; a wall reads its thickness).
    wall_tol = int(round(max_wall_cross_m / spec.resolution))

    def _crosses_wall(pa, pb) -> bool:
        return _max_wall_run_cells(wall_mask, spec, pa, pb) > wall_tol
    while True:
        comps = compute_connected_components(graph).get("components", [])
        if len(comps) <= 1:
            break
        comp_of: dict[str, int] = {}
        for ci, comp in enumerate(comps):
            for nid in comp["node_ids"]:
                comp_of[nid] = ci
        # Candidate cross-component node pairs, closest first. Restrict the search to
        # nodes of the smaller (non-main) components against all others.
        frag_nodes = [nid for comp in comps[1:] for nid in comp["node_ids"]]
        pairs: list[tuple[float, str, str]] = []
        for nid in frag_nodes:
            n = idmap[nid]
            nx, ny = float(n.position[0]), float(n.position[1])
            best_other: tuple[float, str] | None = None
            for mid, mnode in idmap.items():
                if comp_of.get(mid) == comp_of.get(nid):
                    continue
                d = math.hypot(float(mnode.position[0]) - nx, float(mnode.position[1]) - ny)
                if best_other is None or d < best_other[0]:
                    best_other = (d, mid)
            if best_other is not None:
                pairs.append((best_other[0], nid, best_other[1]))
        pairs.sort(key=lambda t: t[0])

        # --- pass 1: bridge the cleanest cross-component doorway ---
        # Accept a short non-walkable run (a doorway/threshold the floor mesh didn't
        # bridge); prefer the smallest gap, then the shortest edge. Minimal-spanning
        # (one bridge per iteration) so rooms aren't over-connected through walls.
        made = False
        best_bridge: tuple[int, float, str, str] | None = None
        for d, a, b in pairs:
            if d > max_bridge_m:
                break
            if _crosses_wall(idmap[a].position, idmap[b].position):
                continue  # straight line punches through a wall — not a doorway
            gap = _max_gap_run_cells(full_grid, idmap[a].position, idmap[b].position)
            if gap > gap_tol:
                continue
            if best_bridge is None or (gap, d) < (best_bridge[0], best_bridge[1]):
                best_bridge = (gap, d, a, b)
            if gap == 0:
                break  # closest fully-clear bridge — can't do better
        if best_bridge is not None:
            gap, _d, a, b = best_bridge
            edge = append_edge(graph, a, b)
            if edge is not None:
                edge.extras = {**(edge.extras or {}), "bridge": True}
                if gap > 0:
                    edge.extras["doorway_gap_cells"] = int(gap)
                straight += 1
                made = True
                continue

        # --- pass 2: stepping-stone via BFS through the doorway ---
        for _d, a, b in pairs:
            n, m = idmap[a], idmap[b]
            start = world_to_cell(spec, n.position[0], n.position[1])
            goal = world_to_cell(spec, m.position[0], m.position[1])
            path = _bfs_path_cells(full_grid, start, goal, max_steps)
            if not path or len(path) < 3:
                continue
            mid_cell = path[len(path) // 2]
            wx, wy = cell_to_world(spec, mid_cell[0], mid_cell[1])
            if not (_line_clear(full_grid, n.position, [wx, wy]) and _line_clear(full_grid, m.position, [wx, wy])):
                continue
            if _crosses_wall(n.position, [wx, wy]) or _crosses_wall(m.position, [wx, wy]):
                continue  # stepping stone reachable only by crossing a wall
            stone_seq += 1
            stone = ViewpointNode(
                node_id=f"vp_bridge_{stone_seq:04d}",
                position=[float(wx), float(wy), 0.0],
                clearance_m=0.0,
                tags=["bridge", "portal", "hazard_decision_point"],
                headings=heading_sweep(heading_count),
                extras={"bridge": True, "cell": [int(mid_cell[0]), int(mid_cell[1])]},
            )
            graph.nodes.append(stone)
            idmap[stone.node_id] = stone
            for e in (append_edge(graph, n.node_id, stone.node_id), append_edge(graph, m.node_id, stone.node_id)):
                if e is not None:
                    e.extras = {**(e.extras or {}), "bridge": True}
            stones += 1
            made = True
            break
        if not made:
            break  # remaining fragments are genuinely sealed
    return straight, stones


def _nearest_node(nodes: list[ViewpointNode], x: float, y: float) -> ViewpointNode | None:
    best = None
    best_d = math.inf
    for n in nodes:
        p = n.position or []
        if len(p) < 2:
            continue
        d = (float(p[0]) - x) ** 2 + (float(p[1]) - y) ** 2
        if d < best_d:
            best_d, best = d, n
    return best


def _connect_portals_and_repair(
    graph: ViewpointGraph,
    grid: TraversabilityGrid,
    portals: list[Any],
    surface: WalkableSurface | None,
    *,
    max_edge_length_m: float,
    heading_count: int,
    doorway_gap_m: float = 0.45,
) -> tuple[int, int, int]:
    """Force door-portal edges, then bridge any remaining disconnected rooms.

    Returns ``(portal_edges, bridge_edges, bridge_nodes)``. Connectivity repair is
    mesh-path only (``surface is not None``) so non-Infinigen scenes keep their
    original unbridged behaviour. Shared by ``build_viewpoint_graph_core`` and
    ``rebuild_viewpoint_edges``.
    """
    portal_edges = 0
    for p in portals:
        if not getattr(p, "resolved", False):
            continue
        na = _nearest_node(graph.nodes, p.side_a[0], p.side_a[1])
        nb = _nearest_node(graph.nodes, p.side_b[0], p.side_b[1])
        if na is None or nb is None or na.node_id == nb.node_id:
            continue
        edge = append_edge(graph, na.node_id, nb.node_id)
        if edge is not None:
            edge.extras = {**(edge.extras or {}), "portal": p.door_id, "portal_type": p.door_type}
            portal_edges += 1
    if surface is not None:
        bridge_edges, bridge_nodes = _repair_connectivity(
            graph, grid, max_bridge_m=max(3.0, max_edge_length_m * 2.0),
            doorway_gap_m=doorway_gap_m, heading_count=heading_count,
            wall_mask=getattr(surface, "wall_band_mask", None),
        )
    else:
        bridge_edges, bridge_nodes = 0, 0
    return portal_edges, bridge_edges, bridge_nodes


def _prepare_graph_grids(
    scene_id: str,
    scene_dir: Path,
    *,
    overlay_objects: list[dict],
    resolution: float,
    robot_radius_m: float,
    robot_height_m: float,
    min_clearance_m: float | None,
    camera_margin_m: float,
    low_profile_max_height_m: float,
    wall_inflate_m: float,
    walkability_overlay: "np.ndarray | None",
) -> _GraphGrids:
    """Derive node/edge traversability grids + portals for a scene.

    Mesh-aware (Infinigen) scenes use the EDT clearance map with ``*_radius=0`` so
    edges are NOT eroded a second time; non-Infinigen scenes use the legacy
    annotation grid with crude ``robot_radius`` erosion. This is the single source
    of truth so ``build_graph`` and ``rebuild_edges`` stay consistent — previously
    the daemon's rebuild handler re-derived a much smaller annotation grid here and
    collapsed dense graphs to a few edges.
    """
    inf = _infinigen_inputs(scene_dir)

    surface: WalkableSurface | None = None
    if inf is not None:
        import_root, origin_offset = inf
        try:
            surface = build_walkable_surface(
                scene_id,
                import_root=import_root,
                origin_offset=origin_offset,
                overlay_objects=overlay_objects,
                resolution=resolution,
                robot_radius_m=robot_radius_m,
                robot_height_m=robot_height_m,
                low_profile_max_height_m=low_profile_max_height_m,
                wall_inflate_m=wall_inflate_m,
            )
        except Exception:
            surface = None  # fall through to legacy

    if surface is not None:
        grid = surface.grid
        # Merge user-painted walkability strokes (1=force walkable, 2=force blocked).
        if walkability_overlay is not None and walkability_overlay.shape == grid.traversable.shape:
            merged = (grid.traversable | (walkability_overlay == 1)) & ~(walkability_overlay == 2)
            grid = TraversabilityGrid(spec=grid.spec, traversable=merged, hazard=grid.hazard)
            surface.grid = grid
        portals = surface.portals
        opening_seeds = [p.side_a for p in portals if p.resolved] + [p.side_b for p in portals if p.resolved]
        # Pre-erode once via the fast EDT clearance map (bypassing the O(obstacles)
        # inflate_traversable_grid that is too slow on mesh grids), with two masks:
        #   - edge_mask: physical robot fit (robot_radius). Edges may hug walls.
        #   - node_mask: robot_radius + camera_margin so rendered viewpoints aren't
        #     buried in geometry. Re-islanded so nodes only land in robot-REACHABLE
        #     space — pockets reachable only through sub-robot-width gaps (which the
        #     plain erosion leaves as isolated cells) are dropped.
        edge_clr = float(robot_radius_m)
        if min_clearance_m is not None and float(min_clearance_m) > 0:
            node_clr = max(edge_clr, float(min_clearance_m))
        else:
            node_clr = edge_clr + max(0.0, float(camera_margin_m))
        # Node candidates need extra clearance (camera_margin) so viewpoints aren't
        # buried in geometry. But a tight room (1.2m hallway, furniture-packed kitchen/
        # bath) can have ZERO node-clearance cells and would get no nodes at all. So
        # instead of keeping only the largest island, take every node-clearance cell,
        # then per walkable ROOM component recover any room left with none: first relax
        # to physical-fit clearance (drop the camera margin), then fall back to that
        # room's single best-clearance cell. grid.traversable is the kept multi-room
        # surface (sub-robot pockets already dropped upstream).
        from scipy import ndimage
        # The clearance EDT is computed from the walkable ISLAND only, so it cannot see
        # thin interior walls — a node can land in the sliver between two walls and read
        # as "clear". Exclude a robot-radius halo around the body-height wall mask so
        # node centres keep the robot body off walls (the "node wedged between walls"
        # failure). Edges are gated separately (build_viewpoint_edges wall_mask).
        wall_band = getattr(surface, "wall_band_mask", None)
        if wall_band is not None and wall_band.shape == grid.traversable.shape:
            halo_it = max(1, int(round(float(robot_radius_m) / float(resolution))))
            wall_halo = ndimage.binary_dilation(wall_band, iterations=halo_it)
        else:
            wall_halo = np.zeros_like(grid.traversable)
        node_mask = (surface.clearance_m >= node_clr) & ~wall_halo
        edge_ok = (surface.clearance_m >= edge_clr) & ~wall_halo
        comp_labels, n_comp = ndimage.label(grid.traversable)
        for ci in range(1, int(n_comp) + 1):
            comp = comp_labels == ci
            if (node_mask & comp).any():
                continue                      # room already has node candidates
            relaxed = edge_ok & comp
            if relaxed.any():
                node_mask = node_mask | relaxed
            else:                             # nothing fits clear of walls — best cell off the wall
                clr = np.where(comp & ~wall_halo, surface.clearance_m, -1.0)
                iy, ix = np.unravel_index(int(np.argmax(clr)), clr.shape)
                if comp[iy, ix] and clr[iy, ix] >= 0.0:
                    node_mask[iy, ix] = True
        if not node_mask.any():
            node_mask = grid.traversable
        edge_mask = surface.clearance_m >= edge_clr
        if not edge_mask.any():
            edge_mask = grid.traversable
        node_grid = TraversabilityGrid(spec=grid.spec, traversable=node_mask, hazard=grid.hazard)
        edge_grid = TraversabilityGrid(spec=grid.spec, traversable=edge_mask, hazard=grid.hazard)
        return _GraphGrids(
            grid=grid, node_grid=node_grid, edge_grid=edge_grid,
            node_radius=0.0, edge_radius=0.0, sampler_min_clearance=0.0,
            surface=surface, portals=portals, opening_seeds=opening_seeds,
        )

    # ---- legacy path (non-Infinigen scenes): annotation grid, unchanged ----
    from .scene_annotations import read_scene_annotation
    from .walkability_overlay import load_overlay as _load_walk_overlay

    annotation_path = scene_dir / "scene_annotation.json"
    if annotation_path.is_file():
        annotation = read_scene_annotation(annotation_path)
        grid = build_traversability_grid(
            annotation, resolution=resolution, objects=overlay_objects, robot_height_m=robot_height_m,
        )
        if walkability_overlay is None:
            ov_path = scene_dir / "walkability_overlay.npy"
            if ov_path.is_file():
                walkability_overlay = _load_walk_overlay(ov_path, expected_spec=grid.spec)
        if walkability_overlay is not None:
            grid = build_traversability_grid(
                annotation, resolution=resolution, walkability_overlay=walkability_overlay,
                objects=overlay_objects, robot_height_m=robot_height_m,
            )
    else:
        from .traversability import load_traversability_grid
        grid = load_traversability_grid(scene_dir / "traversable_grid.npy")
    _door_seeds: list[tuple[float, float]] = []
    for o in overlay_objects:
        if str(o.get("type") or "") not in {"glass_door", "door"}:
            continue
        g = o.get("geometry") or {}
        c = g.get("center")
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            _door_seeds.append((float(c[0]), float(c[1])))
            continue
        s, e = g.get("start"), g.get("end")
        if isinstance(s, (list, tuple)) and isinstance(e, (list, tuple)):
            _door_seeds.append(((float(s[0]) + float(e[0])) / 2.0, (float(s[1]) + float(e[1])) / 2.0))
    return _GraphGrids(
        grid=grid, node_grid=grid, edge_grid=grid,
        node_radius=float(robot_radius_m), edge_radius=float(robot_radius_m),
        sampler_min_clearance=(float(min_clearance_m) if min_clearance_m is not None else 0.0),
        surface=None, portals=[], opening_seeds=_door_seeds,
    )


def build_viewpoint_graph_core(
    scene_id: str,
    scene_dir: str | Path,
    *,
    graph_id: str | None = None,
    resolution: float = 0.05,
    robot_radius_m: float = 0.25,
    robot_height_m: float = 1.2,
    heading_count: int = 12,
    min_node_spacing_m: float = 0.5,
    min_clearance_m: float | None = None,
    camera_margin_m: float = 0.10,
    doorway_gap_m: float = 0.45,
    max_nodes: int = 300,
    k_neighbors: int = 8,
    max_edge_length_m: float = 1.5,
    low_profile_max_height_m: float = 0.03,
    wall_inflate_m: float = 0.0,
    seed: int = 0,
    prune_overlapping: bool = True,
    prune_margin_m: float = 0.0,
    persist_grid: bool = True,
    walkability_overlay: "np.ndarray | None" = None,
    existing_graph: ViewpointGraph | None = None,
    scene_variant_id: Any = None,
    on_progress: Callable[[str, float], None] | None = None,
    metadata_extra: dict | None = None,
) -> GraphBuildResult:
    scene_dir = Path(scene_dir)

    def _progress(stage: str, frac: float) -> None:
        if on_progress is not None:
            on_progress(stage, frac)

    overlay_objects = _load_overlay_objects(scene_dir)
    grids = _prepare_graph_grids(
        scene_id,
        scene_dir,
        overlay_objects=overlay_objects,
        resolution=resolution,
        robot_radius_m=robot_radius_m,
        robot_height_m=robot_height_m,
        min_clearance_m=min_clearance_m,
        camera_margin_m=camera_margin_m,
        low_profile_max_height_m=low_profile_max_height_m,
        wall_inflate_m=wall_inflate_m,
        walkability_overlay=walkability_overlay,
    )
    surface = grids.surface
    grid = grids.grid
    portals = grids.portals
    opening_seeds = grids.opening_seeds
    node_grid = grids.node_grid
    edge_grid = grids.edge_grid
    node_radius = grids.node_radius
    edge_radius = grids.edge_radius
    sampler_min_clearance = grids.sampler_min_clearance

    # Persist the (full, un-eroded) traversability grid for the editor / nav_graph.
    if persist_grid:
        save_traversability_grid(scene_dir / "traversable_grid.npy", grid)

    # ---- sample nodes ----------------------------------------------------- #
    nodes = sample_viewpoint_nodes(
        node_grid,
        max_nodes=max_nodes,
        heading_count=heading_count,
        min_node_spacing_m=min_node_spacing_m,
        min_clearance_m=sampler_min_clearance,
        robot_radius_m=node_radius,
        seed=seed,
        opening_seeds=opening_seeds or None,
        on_progress=lambda f: _progress("nodes", f * 0.5),
    )

    # Backfill clearance + tag portal nodes (nearest sampled node to each portal side).
    if surface is not None:
        for n in nodes:
            cell = (n.extras or {}).get("cell")
            if isinstance(cell, (list, tuple)) and len(cell) == 2:
                cx, cy = int(cell[0]), int(cell[1])
                if 0 <= cy < surface.clearance_m.shape[0] and 0 <= cx < surface.clearance_m.shape[1]:
                    n.clearance_m = float(surface.clearance_m[cy, cx])
        for p in portals:
            if not p.resolved:
                continue
            for side in (p.side_a, p.side_b):
                node = _nearest_node(nodes, side[0], side[1])
                if node is None:
                    continue
                for tag in ("portal", p.door_type, "hazard_decision_point"):
                    if tag not in node.tags:
                        node.tags.append(tag)

    # ---- preserve manual nodes from the existing graph -------------------- #
    if existing_graph is not None:
        existing_ids = {n.node_id for n in nodes}
        for n in existing_graph.nodes:
            if bool((n.extras or {}).get("manual")) and n.node_id not in existing_ids:
                nodes.append(n)
                existing_ids.add(n.node_id)

    # ---- safety-net overlap prune (never remove manual/portal nodes) ------ #
    if prune_overlapping and overlay_objects:
        tmp = ViewpointGraph(scene_id=scene_id, graph_id="tmp", node_heading_count=heading_count, nodes=nodes)
        flagged = set(find_object_overlapping_nodes(tmp, overlay_objects, margin_m=prune_margin_m, robot_height_m=robot_height_m))
        protect = {n.node_id for n in nodes if ("portal" in (n.tags or []) or bool((n.extras or {}).get("manual")))}
        to_remove = [nid for nid in flagged if nid not in protect]
        if to_remove:
            remove_nodes(tmp, to_remove)
            nodes = tmp.nodes

    # ---- edges ------------------------------------------------------------ #
    _progress("edges", 0.5)
    edges = build_viewpoint_edges(
        edge_grid,
        nodes,
        robot_radius_m=edge_radius,
        k_neighbors=k_neighbors,
        max_edge_length_m=max_edge_length_m,
        wall_mask=(surface.wall_band_mask if surface is not None else None),
        on_progress=lambda f: _progress("edges", 0.5 + f * 0.5),
    )

    graph = ViewpointGraph(
        scene_id=scene_id,
        graph_id=graph_id or f"{scene_id}_vg_0001",
        node_heading_count=heading_count,
        nodes=nodes,
        edges=edges,
        metadata={
            "generation_version": "opticalnav-v0.2",
            "max_nodes_requested": int(max_nodes),
            "robot_radius_m": float(robot_radius_m),
            "min_node_spacing_m": float(min_node_spacing_m),
            "max_edge_length_m": float(max_edge_length_m),
            "k_neighbors": int(k_neighbors),
            "seed": int(seed),
            "grid_resolution_m": float(resolution),
            "scene_variant_id": scene_variant_id,
            "walkable_surface": (surface.stats if surface is not None else None),
            **(metadata_extra or {}),
        },
    )

    # ---- forced portal bridge edges + connectivity repair ----------------- #
    portal_edges, bridge_edges, bridge_nodes = _connect_portals_and_repair(
        graph, grid, portals, surface,
        max_edge_length_m=max_edge_length_m, heading_count=heading_count,
        doorway_gap_m=doorway_gap_m,
    )

    summary = graph_summary(graph.nodes, graph.edges, heading_count=heading_count)
    summary["bridge_edges"] = bridge_edges
    summary["bridge_nodes"] = bridge_nodes
    summary["portal_count"] = len(portals)
    summary["portal_edges"] = portal_edges
    summary["portals_unresolved"] = sum(1 for p in portals if not getattr(p, "resolved", True))
    # Connectivity assertion: after portal edges + repair, the graph SHOULD be one
    # component. If not, a passage stayed sealed (e.g. furniture blocking the only
    # doorway, which _repair_connectivity can't bridge because the full grid has no
    # walkable cell there). Report each isolated component's size + centroid so the
    # caller/UI can point at the cut-off room instead of silently shipping a graph
    # the planner can't traverse.
    comps = compute_connected_components(graph).get("components", [])
    summary["connected_components"] = len(comps)
    if len(comps) > 1:
        idpos = {n.node_id: n.position for n in graph.nodes}
        isolated = []
        for comp in comps[1:]:
            pts = [idpos[nid] for nid in comp.get("node_ids", []) if nid in idpos]
            if pts:
                cx = sum(float(p[0]) for p in pts) / len(pts)
                cy = sum(float(p[1]) for p in pts) / len(pts)
            else:
                cx = cy = 0.0
            isolated.append({"size": int(comp.get("size", len(pts))),
                             "centroid": [round(cx, 3), round(cy, 3)]})
        summary["disconnected"] = {"component_count": len(comps), "isolated": isolated}
    if surface is not None:
        summary["walkable_surface"] = surface.stats
    _progress("edges", 1.0)
    return GraphBuildResult(grid=grid, graph=graph, surface=surface, summary=summary)


def rebuild_viewpoint_edges(
    scene_id: str,
    scene_dir: str | Path,
    graph: ViewpointGraph,
    *,
    resolution: float = 0.05,
    robot_radius_m: float = 0.25,
    robot_height_m: float = 1.2,
    heading_count: int = 12,
    k_neighbors: int = 8,
    max_edge_length_m: float = 1.5,
    min_clearance_m: float | None = None,
    camera_margin_m: float = 0.10,
    doorway_gap_m: float = 0.45,
    low_profile_max_height_m: float = 0.03,
    wall_inflate_m: float = 0.0,
    walkability_overlay: "np.ndarray | None" = None,
    preserve_manual_edges: bool = True,
    on_progress: Callable[[str, float], None] | None = None,
) -> GraphBuildResult:
    """Re-run edge building over the graph's CURRENT node set (not resampled).

    Uses the same grid/portal/connectivity logic as :func:`build_viewpoint_graph_core`
    (mesh-aware clearance grid with no double erosion + portal bridges + room repair)
    so a rebuild connects manually-added nodes densely instead of collapsing the
    graph. The previous daemon handler re-derived a much smaller annotation grid and
    eroded it a second time, which dropped ~80% of valid edges.

    Manually-added nodes are preserved (they are part of ``graph.nodes`` already);
    manual edges the auto pass doesn't reproduce are re-appended when
    ``preserve_manual_edges`` is true. Connectivity repair may add a few
    stepping-stone bridge nodes at doorways, exactly like ``build_graph``.
    """
    scene_dir = Path(scene_dir)

    def _progress(stage: str, frac: float) -> None:
        if on_progress is not None:
            on_progress(stage, frac)

    overlay_objects = _load_overlay_objects(scene_dir)
    grids = _prepare_graph_grids(
        scene_id,
        scene_dir,
        overlay_objects=overlay_objects,
        resolution=resolution,
        robot_radius_m=robot_radius_m,
        robot_height_m=robot_height_m,
        min_clearance_m=min_clearance_m,
        camera_margin_m=camera_margin_m,
        low_profile_max_height_m=low_profile_max_height_m,
        wall_inflate_m=wall_inflate_m,
        walkability_overlay=walkability_overlay,
    )

    _progress("edges", 0.0)
    old_edges = list(graph.edges)
    new_edges = build_viewpoint_edges(
        grids.edge_grid,
        graph.nodes,
        robot_radius_m=grids.edge_radius,
        k_neighbors=k_neighbors,
        max_edge_length_m=max_edge_length_m,
        wall_mask=(grids.surface.wall_band_mask if grids.surface is not None else None),
        on_progress=lambda f: _progress("edges", f * 0.9),
    )
    graph.edges = new_edges

    # Re-append manual edges the auto pass didn't reproduce.
    if preserve_manual_edges:
        have = {(e.source, e.target) for e in graph.edges}
        have |= {(e.target, e.source) for e in graph.edges}
        for e in old_edges:
            is_manual = bool((e.extras or {}).get("manual")) or str(e.edge_id).startswith("edge_manual")
            if is_manual and (e.source, e.target) not in have:
                graph.edges.append(e)
                have.add((e.source, e.target))
                have.add((e.target, e.source))

    portal_edges, bridge_edges, bridge_nodes = _connect_portals_and_repair(
        graph, grids.grid, grids.portals, grids.surface,
        max_edge_length_m=max_edge_length_m, heading_count=heading_count,
    )

    summary = graph_summary(graph.nodes, graph.edges, heading_count=heading_count)
    summary["bridge_edges"] = bridge_edges
    summary["bridge_nodes"] = bridge_nodes
    summary["portal_count"] = len(grids.portals)
    summary["portal_edges"] = portal_edges
    summary["portals_unresolved"] = sum(1 for p in grids.portals if not getattr(p, "resolved", True))
    comps = compute_connected_components(graph).get("components", [])
    summary["connected_components"] = len(comps)
    if len(comps) > 1:
        idpos = {n.node_id: n.position for n in graph.nodes}
        isolated = []
        for comp in comps[1:]:
            pts = [idpos[nid] for nid in comp.get("node_ids", []) if nid in idpos]
            if pts:
                cx = sum(float(p[0]) for p in pts) / len(pts)
                cy = sum(float(p[1]) for p in pts) / len(pts)
            else:
                cx = cy = 0.0
            isolated.append({"size": int(comp.get("size", len(pts))),
                             "centroid": [round(cx, 3), round(cy, 3)]})
        summary["disconnected"] = {"component_count": len(comps), "isolated": isolated}
    if grids.surface is not None:
        summary["walkable_surface"] = grids.surface.stats
    _progress("edges", 1.0)
    return GraphBuildResult(grid=grids.grid, graph=graph, surface=grids.surface, summary=summary)
