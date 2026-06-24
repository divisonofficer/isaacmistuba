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
from .walkable_surface import WalkableSurface, _largest_island, build_walkable_surface


@dataclass
class GraphBuildResult:
    grid: TraversabilityGrid
    graph: ViewpointGraph
    surface: WalkableSurface | None
    summary: dict[str, Any] = field(default_factory=dict)


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
    heading_count: int = 12,
) -> tuple[int, int]:
    """Greedily reconnect disconnected components through real walkable space.

    1. straight bridge: add an edge when the line between two nodes stays inside the
       *full* (un-eroded) walkable grid — threads a wide doorway without crossing a
       wall. Reconnects rooms whose doorway eroded away for the edge builder.
    2. stepping-stone: when no straight bridge exists (misaligned / open doorway with
       no door object), BFS the full grid between the closest node pair, drop a node
       at the path's doorway midpoint, and connect both ends. Mirrors the manual node
       + bridge edges users add at thresholds.

    Returns (straight_bridges, stepping_stone_nodes).
    """
    from .node_sampler import heading_sweep

    idmap = {n.node_id: n for n in graph.nodes}
    spec = full_grid.spec
    straight = 0
    stones = 0
    stone_seq = 0
    max_steps = int((max_bridge_m * 6.0) / spec.resolution)
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

        # --- pass 1: nearest cross-component pair with a clear straight line ---
        made = False
        for d, a, b in pairs:
            if d > max_bridge_m:
                break
            if _line_clear(full_grid, idmap[a].position, idmap[b].position):
                edge = append_edge(graph, a, b)
                if edge is not None:
                    edge.extras = {**(edge.extras or {}), "bridge": True}
                    straight += 1
                    made = True
                    break
        if made:
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
        node_mask = _largest_island(surface.clearance_m >= node_clr)
        if not node_mask.any():              # very narrow scene — relax to physical fit
            node_mask = _largest_island(surface.clearance_m >= edge_clr)
        if not node_mask.any():
            node_mask = grid.traversable
        edge_mask = surface.clearance_m >= edge_clr
        if not edge_mask.any():
            edge_mask = grid.traversable
        node_grid = TraversabilityGrid(spec=grid.spec, traversable=node_mask, hazard=grid.hazard)
        edge_grid = TraversabilityGrid(spec=grid.spec, traversable=edge_mask, hazard=grid.hazard)
        node_radius = 0.0
        edge_radius = 0.0
        sampler_min_clearance = 0.0
    else:
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
        portals = []
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
        opening_seeds = _door_seeds
        node_grid = edge_grid = grid
        node_radius = edge_radius = float(robot_radius_m)
        sampler_min_clearance = float(min_clearance_m) if min_clearance_m is not None else 0.0

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

    # ---- forced portal bridge edges --------------------------------------- #
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

    # ---- connectivity repair: bridge rooms through doorways (full grid) ---- #
    # Mesh path only — the legacy annotation grid keeps its original (unbridged)
    # behaviour so non-Infinigen scenes don't regress.
    if surface is not None:
        bridge_edges, bridge_nodes = _repair_connectivity(
            graph, grid, max_bridge_m=max(3.0, max_edge_length_m * 2.0), heading_count=heading_count,
        )
    else:
        bridge_edges, bridge_nodes = 0, 0

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
