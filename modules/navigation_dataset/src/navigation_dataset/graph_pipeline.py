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

from .edge_builder import EdgeValidation, build_viewpoint_edges, graph_summary, validate_viewpoint_edge
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
    find_node,
    remove_nodes,
    reset_node_headings,
)
from .walkable_surface import WalkableSurface, build_walkable_surface
from .walkable_surface import PortalSpec


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
    # Raw mesh walkability restricted to the authoring interior.  It is used for
    # doorway-gap validation and connectivity repair; ``grid`` remains the full
    # persisted mesh grid for editor compatibility.
    domain_grid: TraversabilityGrid
    node_grid: TraversabilityGrid
    edge_grid: TraversabilityGrid
    node_radius: float
    edge_radius: float
    sampler_min_clearance: float
    surface: WalkableSurface | None
    portals: list[Any]
    opening_seeds: list[Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


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


def _authoring_region_masks(scene_dir: Path, spec) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Rasterize authored traversable regions into a mesh grid.

    Imported floor meshes may include exterior slabs or non-navigable appendages.
    The authoring regions are therefore a *domain* constraint, not an obstacle
    substitute: physical mesh/furniture/wall checks remain authoritative.
    """
    from .scene_annotations import read_scene_annotation
    from .traversability import _mask_geometry

    annotation_path = scene_dir / "scene_annotation.json"
    diagnostics: dict[str, Any] = {
        "domain_source": "mesh_only",
        "authoring_region_count": 0,
        "domain_reason": None,
    }
    if not annotation_path.is_file():
        diagnostics["domain_reason"] = "scene_annotation_missing"
        return {}, diagnostics
    try:
        annotation = read_scene_annotation(annotation_path)
        masks = {
            str(region.region_id): _mask_geometry(spec, region.geometry)
            for region in annotation.traversable_regions
            if bool(region.traversable)
        }
    except Exception as exc:
        diagnostics["domain_reason"] = f"scene_annotation_unusable:{type(exc).__name__}"
        return {}, diagnostics
    masks = {name: mask for name, mask in masks.items() if bool(mask.any())}
    if not masks:
        diagnostics["domain_reason"] = "no_positive_authoring_regions"
        return {}, diagnostics
    diagnostics.update({
        "domain_source": "authoring_traversable_regions",
        "authoring_region_count": len(masks),
    })
    return masks, diagnostics


def _inferred_portals(
    zone_masks: dict[str, np.ndarray],
    node_mask: np.ndarray,
    domain_grid: TraversabilityGrid,
    *,
    wall_mask,
    doorway_gap_m: float,
    max_edge_length_m: float,
    max_portals: int,
) -> tuple[list[PortalSpec], int]:
    """Find one geometry-validated threshold per adjacent authoring-zone pair."""
    if len(zone_masks) < 2 or max_portals <= 0:
        return [], 0
    from scipy import ndimage

    names = sorted(zone_masks)
    gap_tol = max(1, int(math.ceil(float(doorway_gap_m) / domain_grid.spec.resolution)) + 1)
    inferred: list[PortalSpec] = []
    rejected = 0
    for ia, name_a in enumerate(names):
        anchors_a = zone_masks[name_a] & node_mask
        if not anchors_a.any():
            continue
        distance_cells, nearest = ndimage.distance_transform_edt(~anchors_a, return_indices=True)
        distances = distance_cells * float(domain_grid.spec.resolution)
        for name_b in names[ia + 1:]:
            if len(inferred) >= max_portals:
                return inferred, rejected
            anchors_b = zone_masks[name_b] & node_mask
            candidate_cells = np.argwhere(anchors_b & (distances <= float(max_edge_length_m)))
            if candidate_cells.size == 0:
                continue
            # Stable priority makes generated portal ids/positions reproducible.  A
            # pair can share a long wall; inspect many closest samples until the real
            # body-height opening is found rather than accepting the first solid wall.
            order = sorted(
                ((float(distances[y, x]), int(y), int(x)) for y, x in candidate_cells),
                key=lambda item: item,
            )
            chosen: tuple[tuple[float, float], tuple[float, float], float] | None = None
            for _distance_m, by, bx in order[:2048]:
                ay, ax = int(nearest[0, by, bx]), int(nearest[1, by, bx])
                if ax == bx and ay == by:
                    continue
                pa = cell_to_world(domain_grid.spec, ax, ay)
                pb = cell_to_world(domain_grid.spec, bx, by)
                wall_run = _max_wall_run_cells(wall_mask, domain_grid.spec, pa, pb)
                gap_run = _max_gap_run_cells(domain_grid, pa, pb)
                if wall_run != 0 or gap_run > gap_tol:
                    rejected += 1
                    continue
                span = math.hypot(float(pb[0]) - float(pa[0]), float(pb[1]) - float(pa[1]))
                if span > float(max_edge_length_m):
                    rejected += 1
                    continue
                chosen = (pa, pb, span)
                break
            if chosen is None:
                continue
            pa, pb, span = chosen
            dx, dy = float(pb[0]) - float(pa[0]), float(pb[1]) - float(pa[1])
            axis = (dx / span, dy / span) if span > 1e-9 else (0.0, 0.0)
            inferred.append(PortalSpec(
                door_id=f"inferred_portal_{name_a}__{name_b}",
                door_type="inferred_opening",
                center=((float(pa[0]) + float(pb[0])) / 2.0, (float(pa[1]) + float(pb[1])) / 2.0),
                axis=axis,
                side_a=(float(pa[0]), float(pa[1])),
                side_b=(float(pb[0]), float(pb[1])),
                region_a=ia,
                region_b=names.index(name_b),
                resolved=True,
                source="inferred",
            ))
    return inferred, rejected


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
    edge_grid: TraversabilityGrid | None = None,
    safe_node_grid: TraversabilityGrid | None = None,
    max_bridge_m: float = 3.0,
    max_edge_length_m: float = 1.5,
    doorway_gap_m: float = 0.45,
    heading_count: int = 12,
    wall_mask=None,
    clearance_map: "np.ndarray | None" = None,
    max_nodes: int | None = None,
    max_wall_cross_m: float = 0.0,
) -> tuple[int, int]:
    """Greedily reconnect disconnected components through real walkable space.

    1. straight bridge: add an edge when the line between two nodes stays inside the
       *full* (un-eroded) walkable grid — threads a wide doorway without crossing a
       wall. Reconnects rooms whose doorway eroded away for the edge builder.
    2. route bridge: when no straight bridge exists, follow a bounded BFS route over
       the robot-safe edge grid and split it into collision-free segments no longer
       than ``max_edge_length_m``. Intermediate cells must also be in the safe node
       grid, so repair never creates a low-clearance "representative" just to make a
       graph connected.

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
    route_grid = edge_grid or full_grid
    safe_grid = safe_node_grid or route_grid
    from scipy import ndimage
    route_labels, _route_component_count = ndimage.label(route_grid.traversable)
    # A route may be long even though every individual graph edge is short.  Keep a
    # generous but finite grid bound; this is not a licence to create a long direct
    # bridge, only to discover the sequence of short safe segments.
    max_steps = max(1024, int((max_bridge_m * 12.0) / spec.resolution))
    gap_tol = max(1, int(math.ceil(doorway_gap_m / spec.resolution)) + 1)
    # Tolerate at most this many body-height wall cells on a bridge line. 0 → reject
    # any wall contact (doorway openings read exactly 0; a wall reads its thickness).
    wall_tol = int(round(max_wall_cross_m / spec.resolution))

    def _crosses_wall(pa, pb) -> bool:
        return _max_wall_run_cells(wall_mask, spec, pa, pb) > wall_tol

    def _normal_edge_ok(source: ViewpointNode, target: ViewpointNode) -> bool:
        validation = validate_viewpoint_edge(
            route_grid,
            source,
            target,
            robot_radius_m=0.0,
            max_edge_length_m=max_edge_length_m,
            wall_mask=wall_mask,
        )
        return validation.accepted and validation.mode == "normal"

    def _route_component(node: ViewpointNode) -> int:
        cx, cy = world_to_cell(spec, float(node.position[0]), float(node.position[1]))
        if not (0 <= cy < route_labels.shape[0] and 0 <= cx < route_labels.shape[1]):
            return 0
        return int(route_labels[cy, cx])

    def _route_cells(source: ViewpointNode, target: ViewpointNode, path) -> list[tuple[int, int]] | None:
        """Return safe intermediate cells whose chords follow the BFS route."""
        if not path or len(path) < 2:
            return None
        route: list[tuple[int, int]] = []
        current = source
        cursor = 0
        while True:
            if _normal_edge_ok(current, target):
                return route
            best: tuple[int, ViewpointNode] | None = None
            # Pick the furthest route cell reachable by a normal (not doorway)
            # edge.  This follows bends in corridors instead of diagonally cutting
            # through the wall on the inside of a turn.
            for index in range(cursor + 1, len(path) - 1):
                cx, cy = path[index]
                if not bool(safe_grid.traversable[cy, cx]):
                    continue
                wx, wy = cell_to_world(spec, cx, cy)
                candidate = ViewpointNode(
                    node_id="_route_probe",
                    position=[float(wx), float(wy), 0.0],
                    headings=[],
                )
                if _normal_edge_ok(current, candidate):
                    best = (index, candidate)
            if best is None:
                return None
            index, candidate = best
            route.append(path[index])
            cursor = index
            current = candidate
            if len(route) > len(path):  # defensive progress guard
                return None
    while True:
        comps = compute_connected_components(graph).get("components", [])
        if len(comps) <= 1:
            break
        comp_of: dict[str, int] = {}
        for ci, comp in enumerate(comps):
            for nid in comp["node_ids"]:
                comp_of[nid] = ci
        # Candidate pairs must share a physical edge-grid component.  Portal edges
        # already connect different components across a certified doorway; this pass
        # stitches each room's interior back together.  Restricting candidates this
        # way prevents a geometrically-close pair on opposite sides of a wall from
        # monopolising the repair search.
        route_members: dict[int, list[str]] = {}
        for node_id, node in idmap.items():
            route_component = _route_component(node)
            if route_component:
                route_members.setdefault(route_component, []).append(node_id)
        pairs: list[tuple[float, str, str]] = []
        for nid, n in idmap.items():
            source_component = comp_of.get(nid)
            if source_component is None:
                continue
            nx, ny = float(n.position[0]), float(n.position[1])
            route_component = _route_component(n)
            if route_component == 0:
                continue
            best_other: tuple[float, str] | None = None
            for mid in route_members.get(route_component, []):
                if comp_of.get(mid) == source_component:
                    continue
                mnode = idmap[mid]
                d = math.hypot(float(mnode.position[0]) - nx, float(mnode.position[1]) - ny)
                if best_other is None or d < best_other[0]:
                    best_other = (d, mid)
            if best_other is not None:
                pairs.append((best_other[0], nid, best_other[1]))
        pairs.sort(key=lambda t: t[0])

        # --- pass 1: short collision-free normal bridge ---
        # Doorway discontinuities are handled exclusively by the certified portal
        # pass above.  Repair itself must not turn an arbitrary short gap into a new
        # doorway, otherwise a thin wall would be indistinguishable from a door.
        made = False
        best_bridge: tuple[float, str, str] | None = None
        for d, a, b in pairs:
            if d > min(float(max_bridge_m), float(max_edge_length_m)):
                break
            if not _normal_edge_ok(idmap[a], idmap[b]):
                continue
            if best_bridge is None or d < best_bridge[0]:
                best_bridge = (d, a, b)
            break
        if best_bridge is not None:
            _d, a, b = best_bridge
            edge = append_edge(graph, a, b)
            if edge is not None:
                edge.extras = {**(edge.extras or {}), "bridge": True, "safe_route": True}
                straight += 1
                made = True
                continue

        # --- pass 2: split a real safe BFS route into short normal edges ---
        for _d, a, b in pairs:
            n, m = idmap[a], idmap[b]
            start = world_to_cell(spec, n.position[0], n.position[1])
            goal = world_to_cell(spec, m.position[0], m.position[1])
            path = _bfs_path_cells(route_grid, start, goal, max_steps)
            route_cells = _route_cells(n, m, path)
            if route_cells is None:
                continue
            if max_nodes is not None and len(graph.nodes) + len(route_cells) > int(max_nodes):
                continue
            previous = n
            for cell in route_cells:
                while True:
                    stone_seq += 1
                    bridge_id = f"vp_bridge_{stone_seq:04d}"
                    if bridge_id not in idmap:
                        break
                cx, cy = cell
                wx, wy = cell_to_world(spec, cx, cy)
                clearance = 0.0
                if clearance_map is not None and 0 <= cy < clearance_map.shape[0] and 0 <= cx < clearance_map.shape[1]:
                    clearance = float(clearance_map[cy, cx])
                stone = ViewpointNode(
                    node_id=bridge_id,
                    position=[float(wx), float(wy), 0.0],
                    clearance_m=clearance,
                    tags=["bridge", "hazard_decision_point"],
                    headings=heading_sweep(heading_count),
                    extras={"bridge": True, "cell": [int(cx), int(cy)], "safe_route": True},
                )
                graph.nodes.append(stone)
                idmap[stone.node_id] = stone
                edge = append_edge(graph, previous.node_id, stone.node_id)
                if edge is not None:
                    edge.extras = {**(edge.extras or {}), "bridge": True, "safe_route": True}
                    straight += 1
                previous = stone
                stones += 1
            edge = append_edge(graph, previous.node_id, m.node_id)
            if edge is not None:
                edge.extras = {**(edge.extras or {}), "bridge": True, "safe_route": True}
                straight += 1
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


def _fill_safe_node_coverage(
    nodes: list[ViewpointNode],
    node_grid: TraversabilityGrid,
    *,
    heading_count: int,
    max_nodes: int,
    max_edge_length_m: float,
) -> tuple[list[ViewpointNode], dict[str, int]]:
    """Fill large safe-node holes before edge generation.

    The regular sampler deliberately begins from portal seeds and then makes a
    shuffled Poisson pass.  With a global node cap, a narrow room can otherwise get
    one random sample several metres from its portal seed, leaving a perfectly safe
    but isolated node.  This bounded, deterministic farthest-point pass reserves a
    small amount of the same node budget for coverage.  It only chooses cells already
    valid in ``node_grid``; it never manufactures a low-clearance fallback.
    """
    if len(nodes) >= max_nodes or not node_grid.traversable.any():
        return nodes, {"coverage_nodes": 0, "coverage_components_uncovered": 0}
    from scipy import ndimage
    from .node_sampler import heading_sweep

    labels, count = ndimage.label(node_grid.traversable)
    selected: dict[int, list[tuple[int, int]]] = {label: [] for label in range(1, int(count) + 1)}
    for node in nodes:
        cell = (node.extras or {}).get("cell")
        if isinstance(cell, (list, tuple)) and len(cell) == 2:
            cx, cy = int(cell[0]), int(cell[1])
        else:
            cx, cy = world_to_cell(node_grid.spec, float(node.position[0]), float(node.position[1]))
        if 0 <= cy < labels.shape[0] and 0 <= cx < labels.shape[1]:
            label = int(labels[cy, cx])
            if label:
                selected[label].append((cy, cx))

    # Keep every safe point within the user-visible 0.75 m coverage target whenever
    # the requested node budget permits it.  The Poisson pass still supplies local
    # variety; this deterministic pass only fills its largest remaining holes.
    coverage_radius_cells = max(1.0, min(0.75, float(max_edge_length_m) * 0.50) / node_grid.spec.resolution)
    components = [
        (label, np.argwhere(labels == label))
        for label in range(1, int(count) + 1)
    ]
    added = 0
    sequence = 0
    used_ids = {node.node_id for node in nodes}

    def _append_cell(cy: int, cx: int) -> None:
        nonlocal added, sequence
        while True:
            sequence += 1
            node_id = f"vp_coverage_{sequence:04d}"
            if node_id not in used_ids:
                break
        wx, wy = cell_to_world(node_grid.spec, cx, cy)
        nodes.append(ViewpointNode(
            node_id=node_id,
            position=[float(wx), float(wy), 0.0],
            clearance_m=0.0,
            tags=["coverage"],
            headings=heading_sweep(heading_count),
            extras={"cell": [int(cx), int(cy)], "coverage": True},
        ))
        used_ids.add(node_id)
        added += 1

    while len(nodes) < max_nodes:
        best_choice: tuple[float, int, int, int] | None = None
        for label, coords in components:
            if coords.size == 0:
                continue
            anchors = selected[label]
            if anchors:
                anchor_array = np.asarray(anchors, dtype=np.float64)
                delta = coords[:, None, :].astype(np.float64) - anchor_array[None, :, :]
                nearest_sq = np.min(np.sum(delta * delta, axis=2), axis=1)
                candidate_index = int(np.argmax(nearest_sq))
                distance_cells = math.sqrt(float(nearest_sq[candidate_index]))
            else:
                centre = np.mean(coords, axis=0)
                candidate_index = int(np.argmin(np.sum((coords.astype(np.float64) - centre) ** 2, axis=1)))
                distance_cells = math.inf
            if distance_cells <= coverage_radius_cells:
                continue
            cy, cx = (int(value) for value in coords[candidate_index])
            choice = (distance_cells, label, cy, cx)
            if best_choice is None or choice[0] > best_choice[0] or (
                choice[0] == best_choice[0] and choice[1:] < best_choice[1:]
            ):
                best_choice = choice
        if best_choice is None:
            break
        _distance_cells, label, cy, cx = best_choice
        _append_cell(cy, cx)
        selected[label].append((cy, cx))

    still_uncovered = 0
    for label, coords in components:
        anchors = selected[label]
        if coords.size == 0 or not anchors:
            still_uncovered += 1
            continue
        anchor_array = np.asarray(anchors, dtype=np.float64)
        delta = coords[:, None, :].astype(np.float64) - anchor_array[None, :, :]
        nearest_sq = np.min(np.sum(delta * delta, axis=2), axis=1)
        if math.sqrt(float(np.max(nearest_sq))) > coverage_radius_cells:
            still_uncovered += 1
    return nodes, {"coverage_nodes": int(added), "coverage_components_uncovered": int(still_uncovered)}


def _drop_sealed_automatic_components(graph: ViewpointGraph) -> list[dict[str, Any]]:
    """Remove auto-only components that have no certified safe route to the graph.

    A mesh import can expose a visually walkable island that is disconnected after
    body-radius clearance and authoring-domain masking.  Keeping one random node on
    that island produces an unreachable episode start.  We never remove a user node
    (or its legacy component); auto-only sealed islands are omitted and recorded.
    """
    components = compute_connected_components(graph).get("components", [])
    if len(components) <= 1:
        return []
    nodes = {node.node_id: node for node in graph.nodes}
    remove_ids: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    for component in components[1:]:
        node_ids = [node_id for node_id in component.get("node_ids", []) if node_id in nodes]
        if not node_ids:
            continue
        if any(bool((nodes[node_id].extras or {}).get("manual")) for node_id in node_ids):
            continue
        positions = [nodes[node_id].position for node_id in node_ids]
        centroid = [
            round(sum(float(position[axis]) for position in positions) / len(positions), 3)
            for axis in (0, 1)
        ]
        remove_ids.update(node_ids)
        diagnostics.append({
            "size": len(node_ids),
            "centroid": centroid,
            "reason": "sealed_no_safe_route",
        })
    if remove_ids:
        graph.nodes = [node for node in graph.nodes if node.node_id not in remove_ids]
        graph.edges = [
            edge for edge in graph.edges
            if edge.source not in remove_ids and edge.target not in remove_ids
        ]
    return diagnostics


def _edge_generation_counts(edges) -> dict[str, int]:
    """Summarise normal, certified-doorway, and route-repair edge production."""
    doorway = 0
    bridge = 0
    for edge in edges:
        extras = edge.extras or {}
        validation = extras.get("edge_validation") if isinstance(extras, dict) else None
        if isinstance(validation, dict) and validation.get("mode") == "doorway":
            doorway += 1
        if bool(extras.get("bridge")):
            bridge += 1
    return {
        "normal_edge_count": int(len(edges) - doorway),
        "doorway_edge_count": int(doorway),
        "bridge_edge_count": int(bridge),
    }


def _connect_portals_and_repair(
    graph: ViewpointGraph,
    domain_grid: TraversabilityGrid,
    edge_grid: TraversabilityGrid,
    node_grid: TraversabilityGrid,
    portals: list[Any],
    surface: WalkableSurface | None,
    *,
    max_edge_length_m: float,
    heading_count: int,
    max_nodes: int | None = None,
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
        validation = validate_viewpoint_edge(
            edge_grid, na, nb,
            robot_radius_m=0.0,
            max_edge_length_m=max_edge_length_m,
            wall_mask=(getattr(surface, "wall_band_mask", None) if surface is not None else None),
            doorway_grid=domain_grid,
            portals=[p],
            doorway_gap_m=doorway_gap_m,
        )
        if not validation.accepted:
            continue
        edge = append_edge(graph, na.node_id, nb.node_id)
        if edge is not None:
            edge.extras = {
                **(edge.extras or {}),
                "portal": p.door_id,
                "portal_type": p.door_type,
                "portal_source": getattr(p, "source", "declared"),
                "edge_validation": {
                    "mode": validation.mode,
                    "reason": validation.reason,
                    "gap_run_cells": validation.gap_run_cells,
                    "wall_run_cells": validation.wall_run_cells,
                },
            }
            portal_edges += 1
    if surface is not None:
        bridge_edges = bridge_nodes = 0
        # A portal can merge two formerly independent room groups.  Re-run the
        # component-local repair to a fixed point so the newly merged group becomes
        # eligible for the next safe route; without this, a single pass leaves the
        # last cul-de-sac for the next user-triggered rebuild.
        for _ in range(max(1, min(16, len(graph.nodes) + 1))):
            made_edges, made_nodes = _repair_connectivity(
                graph, domain_grid, edge_grid=edge_grid, safe_node_grid=node_grid,
                max_bridge_m=max_edge_length_m,
                max_edge_length_m=max_edge_length_m,
                doorway_gap_m=doorway_gap_m, heading_count=heading_count,
                wall_mask=getattr(surface, "wall_band_mask", None),
                clearance_map=getattr(surface, "clearance_m", None),
                max_nodes=max_nodes,
            )
            bridge_edges += made_edges
            bridge_nodes += made_nodes
            if len(compute_connected_components(graph).get("components", [])) <= 1:
                break
            if made_edges == 0 and made_nodes == 0:
                break
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
    max_nodes: int = 300,
    max_edge_length_m: float = 1.5,
    doorway_gap_m: float = 0.45,
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
        if walkability_overlay is None:
            from .walkability_overlay import load_overlay as _load_walk_overlay

            overlay_path = scene_dir / "walkability_overlay.npy"
            if overlay_path.is_file():
                walkability_overlay = _load_walk_overlay(overlay_path, expected_spec=grid.spec)
        if walkability_overlay is not None and walkability_overlay.shape == grid.traversable.shape:
            merged = (grid.traversable | (walkability_overlay == 1)) & ~(walkability_overlay == 2)
            grid = TraversabilityGrid(spec=grid.spec, traversable=merged, hazard=grid.hazard)
        zone_masks, diagnostics = _authoring_region_masks(scene_dir, grid.spec)
        domain_mask = grid.traversable.copy()
        if zone_masks:
            authoring_mask = np.logical_or.reduce(list(zone_masks.values()))
            domain_mask &= authoring_mask
        diagnostics["domain_walkable_cells"] = int(domain_mask.sum())
        domain_grid = TraversabilityGrid(spec=grid.spec, traversable=domain_mask, hazard=grid.hazard)
        # Pre-erode once via the fast EDT clearance map (bypassing the O(obstacles)
        # inflate_traversable_grid that is too slow on mesh grids), with two masks:
        #   - edge_mask: physical robot fit (robot_radius). Edges may hug walls.
        #   - node_mask: robot_radius + camera_margin so rendered viewpoints aren't
        #     buried in geometry. Re-islanded so nodes only land in robot-REACHABLE
        #     space — pockets reachable only through sub-robot-width gaps (which the
        #     plain erosion leaves as isolated cells) are dropped.
        edge_clr = float(robot_radius_m)
        # ``min_clearance_m`` is a robot safety *margin* on the mesh path.  A 0.25 m
        # robot + 0.10 m margin therefore requires a 0.35 m node-centre clearance.
        node_margin = (float(min_clearance_m) if min_clearance_m is not None
                       else max(0.0, float(camera_margin_m)))
        node_clr = edge_clr + max(0.0, node_margin)
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
        node_mask = (surface.clearance_m >= node_clr) & ~wall_halo & domain_mask
        edge_mask = (surface.clearance_m >= edge_clr) & domain_mask
        comp_labels, n_comp = ndimage.label(domain_mask)
        excluded_components = 0
        for ci in range(1, int(n_comp) + 1):
            comp = comp_labels == ci
            if not (node_mask & comp).any():
                excluded_components += 1
        diagnostics.update({
            "node_clearance_required_m": round(float(node_clr), 4),
            "node_candidate_cells": int(node_mask.sum()),
            "edge_candidate_cells": int(edge_mask.sum()),
            "excluded_node_components": int(excluded_components),
        })

        declared = [p for p in surface.portals if getattr(p, "resolved", False)]
        inferred_limit = min(64, max(0, int(max_nodes) // 6))
        inferred, inferred_rejected = _inferred_portals(
            zone_masks,
            node_mask,
            domain_grid,
            wall_mask=wall_band,
            doorway_gap_m=doorway_gap_m,
            max_edge_length_m=max_edge_length_m,
            max_portals=inferred_limit,
        )
        portals = declared + inferred
        opening_seeds: list[tuple[float, float]] = []
        seen_seed_cells: set[tuple[int, int]] = set()
        for portal in portals:
            for point in (portal.side_a, portal.side_b):
                if len(opening_seeds) >= int(max_nodes):
                    break
                cell = world_to_cell(grid.spec, point[0], point[1])
                if cell in seen_seed_cells:
                    continue
                seen_seed_cells.add(cell)
                opening_seeds.append((float(point[0]), float(point[1])))
        diagnostics.update({
            "declared_portals": len(surface.portals),
            "declared_portals_resolved": len(declared),
            "inferred_portals": len(inferred),
            "inferred_portals_rejected": int(inferred_rejected),
            "forced_seed_count": len(opening_seeds),
        })
        node_grid = TraversabilityGrid(spec=grid.spec, traversable=node_mask, hazard=grid.hazard)
        edge_grid = TraversabilityGrid(spec=grid.spec, traversable=edge_mask, hazard=grid.hazard)
        return _GraphGrids(
            grid=grid, domain_grid=domain_grid, node_grid=node_grid, edge_grid=edge_grid,
            node_radius=0.0, edge_radius=0.0, sampler_min_clearance=0.0,
            surface=surface, portals=portals, opening_seeds=opening_seeds, diagnostics=diagnostics,
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
        grid=grid, domain_grid=grid, node_grid=grid, edge_grid=grid,
        node_radius=float(robot_radius_m), edge_radius=float(robot_radius_m),
        sampler_min_clearance=(float(min_clearance_m) if min_clearance_m is not None else 0.0),
        surface=None, portals=[], opening_seeds=_door_seeds,
        diagnostics={"domain_source": "legacy_annotation"},
    )


def validate_scene_graph_edge(
    scene_id: str,
    scene_dir: str | Path,
    graph: ViewpointGraph,
    source_id: str,
    target_id: str,
    *,
    resolution: float = 0.05,
    robot_radius_m: float = 0.25,
    robot_height_m: float = 1.2,
    min_clearance_m: float | None = None,
    camera_margin_m: float = 0.10,
    max_edge_length_m: float = 1.5,
    doorway_gap_m: float = 0.45,
    low_profile_max_height_m: float = 0.03,
    wall_inflate_m: float = 0.0,
    walkability_overlay: "np.ndarray | None" = None,
) -> tuple[EdgeValidation, dict[str, Any]]:
    """Validate a prospective manual edge using the same mesh policy as builds."""
    scene_path = Path(scene_dir)
    source = find_node(graph, source_id)
    target = find_node(graph, target_id)
    if source is None or target is None:
        return EdgeValidation(False, "rejected", "unknown_endpoint", 0.0, 0, 0, False), {}
    grids = _prepare_graph_grids(
        scene_id,
        scene_path,
        overlay_objects=_load_overlay_objects(scene_path),
        resolution=resolution,
        robot_radius_m=robot_radius_m,
        robot_height_m=robot_height_m,
        min_clearance_m=min_clearance_m,
        camera_margin_m=camera_margin_m,
        low_profile_max_height_m=low_profile_max_height_m,
        wall_inflate_m=wall_inflate_m,
        walkability_overlay=walkability_overlay,
        max_nodes=max(1, len(graph.nodes)),
        max_edge_length_m=max_edge_length_m,
        doorway_gap_m=doorway_gap_m,
    )
    validation = validate_viewpoint_edge(
        grids.edge_grid,
        source,
        target,
        robot_radius_m=grids.edge_radius,
        max_edge_length_m=max_edge_length_m,
        wall_mask=(grids.surface.wall_band_mask if grids.surface is not None else None),
        doorway_grid=grids.domain_grid,
        portals=grids.portals,
        doorway_gap_m=doorway_gap_m,
    )
    return validation, grids.diagnostics


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
        max_nodes=max_nodes,
        max_edge_length_m=max_edge_length_m,
        doorway_gap_m=doorway_gap_m,
    )
    surface = grids.surface
    grid = grids.grid
    domain_grid = grids.domain_grid
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
    # Leave a bounded share of the requested total for deterministic safe-coverage
    # points and, if a corridor turns, short route-repair points.  This avoids
    # spending every slot in large open rooms and stranding a small room's only node.
    bridge_reserve = min(24, max(0, int(max_nodes) // 8)) if surface is not None else 0
    coverage_reserve = min(48, max(0, int(max_nodes) // 6)) if surface is not None else 0
    sampling_node_budget = max(
        len(opening_seeds),
        int(max_nodes) - bridge_reserve - coverage_reserve,
    )
    coverage_node_budget = int(max_nodes) - bridge_reserve
    nodes = sample_viewpoint_nodes(
        node_grid,
        max_nodes=sampling_node_budget,
        heading_count=heading_count,
        min_node_spacing_m=min_node_spacing_m,
        min_clearance_m=sampler_min_clearance,
        robot_radius_m=node_radius,
        seed=seed,
        opening_seeds=opening_seeds or None,
        on_progress=lambda f: _progress("nodes", f * 0.5),
    )
    if surface is not None:
        nodes, coverage_diagnostics = _fill_safe_node_coverage(
            nodes,
            node_grid,
            heading_count=heading_count,
            # Keep the route-repair reserve intact while deterministically spreading
            # the remaining coverage slots across safe interior components.
            max_nodes=coverage_node_budget,
            max_edge_length_m=max_edge_length_m,
        )
        grids.diagnostics.update({
            "sampling_node_budget": int(sampling_node_budget),
            "coverage_node_budget": int(coverage_node_budget),
            "connectivity_node_reserve": int(bridge_reserve),
            **coverage_diagnostics,
        })

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
    manual_heading_normalizations: list[str] = []
    if existing_graph is not None:
        existing_ids = {n.node_id for n in nodes}
        for n in existing_graph.nodes:
            if bool((n.extras or {}).get("manual")) and n.node_id not in existing_ids:
                if reset_node_headings(n, heading_count):
                    manual_heading_normalizations.append(n.node_id)
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
            "min_clearance_m": float(min_clearance_m) if min_clearance_m is not None else None,
            "min_node_spacing_m": float(min_node_spacing_m),
            "max_edge_length_m": float(max_edge_length_m),
            "k_neighbors": int(k_neighbors),
            "seed": int(seed),
            "grid_resolution_m": float(resolution),
            "scene_variant_id": scene_variant_id,
            "walkable_surface": (surface.stats if surface is not None else None),
            "manual_heading_normalizations": manual_heading_normalizations,
            "generation_diagnostics": grids.diagnostics,
            **(metadata_extra or {}),
        },
    )

    # ---- forced portal bridge edges + connectivity repair ----------------- #
    portal_edges, bridge_edges, bridge_nodes = _connect_portals_and_repair(
        graph, domain_grid, edge_grid, node_grid, portals, surface,
        max_edge_length_m=max_edge_length_m, heading_count=heading_count,
        max_nodes=max_nodes,
        doorway_gap_m=doorway_gap_m,
    )
    # Re-evaluate from the fully materialised graph once.  Portal and route edges
    # are appended in separate phases; rebuilding the component index after that
    # complete mutation is required for a second doorway-adjacent cul-de-sac to see
    # the newly connected room group.
    if surface is not None and len(compute_connected_components(graph).get("components", [])) > 1:
        extra_edges, extra_nodes = _repair_connectivity(
            graph, domain_grid, edge_grid=edge_grid, safe_node_grid=node_grid,
            max_bridge_m=max_edge_length_m, max_edge_length_m=max_edge_length_m,
            doorway_gap_m=doorway_gap_m, heading_count=heading_count,
            wall_mask=surface.wall_band_mask, clearance_map=surface.clearance_m,
            max_nodes=max_nodes,
        )
        bridge_edges += extra_edges
        bridge_nodes += extra_nodes
    sealed_components = _drop_sealed_automatic_components(graph) if surface is not None else []
    if sealed_components:
        grids.diagnostics["sealed_components_removed"] = sealed_components

    summary = graph_summary(graph.nodes, graph.edges, heading_count=heading_count)
    summary["bridge_edges"] = bridge_edges
    summary["bridge_nodes"] = bridge_nodes
    summary["portal_count"] = len(portals)
    summary["portal_edges"] = portal_edges
    summary["portals_unresolved"] = sum(1 for p in portals if not getattr(p, "resolved", True))
    summary["generation_diagnostics"] = grids.diagnostics
    summary.update(_edge_generation_counts(graph.edges))
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
        max_nodes=max(1, len(graph.nodes)),
        max_edge_length_m=max_edge_length_m,
        doorway_gap_m=doorway_gap_m,
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

    # Re-append legacy manual edges unchanged, but report which ones no longer
    # satisfy the new policy.  The chosen rollout deliberately avoids silently
    # mutating a user's existing graph; new manual additions go through the same
    # validator before they can claim ``collision_free``.
    legacy_manual_audit = {"total": 0, "policy_valid": 0, "rejected": []}
    if preserve_manual_edges:
        have = {(e.source, e.target) for e in graph.edges}
        have |= {(e.target, e.source) for e in graph.edges}
        nodes_by_id = {node.node_id: node for node in graph.nodes}
        for e in old_edges:
            is_manual = bool((e.extras or {}).get("manual")) or str(e.edge_id).startswith("edge_manual")
            if is_manual and (e.source, e.target) not in have:
                legacy_manual_audit["total"] += 1
                source, target = nodes_by_id.get(e.source), nodes_by_id.get(e.target)
                if source is None or target is None:
                    validation_reason = "unknown_endpoint"
                else:
                    validation = validate_viewpoint_edge(
                        grids.edge_grid, source, target,
                        robot_radius_m=grids.edge_radius,
                        max_edge_length_m=max_edge_length_m,
                        wall_mask=(grids.surface.wall_band_mask if grids.surface is not None else None),
                        doorway_grid=grids.domain_grid,
                        portals=grids.portals,
                        doorway_gap_m=doorway_gap_m,
                    )
                    validation_reason = validation.reason
                    if validation.accepted:
                        legacy_manual_audit["policy_valid"] += 1
                if validation_reason != "ok" and validation_reason != "certified_doorway":
                    legacy_manual_audit["rejected"].append({"edge_id": e.edge_id, "reason": validation_reason})
                graph.edges.append(e)
                have.add((e.source, e.target))
                have.add((e.target, e.source))

    portal_edges, bridge_edges, bridge_nodes = _connect_portals_and_repair(
        graph, grids.domain_grid, grids.edge_grid, grids.node_grid, grids.portals, grids.surface,
        max_edge_length_m=max_edge_length_m, heading_count=heading_count,
        max_nodes=max(len(graph.nodes), int((graph.metadata or {}).get("max_nodes_requested") or len(graph.nodes))),
        doorway_gap_m=doorway_gap_m,
    )

    summary = graph_summary(graph.nodes, graph.edges, heading_count=heading_count)
    summary["bridge_edges"] = bridge_edges
    summary["bridge_nodes"] = bridge_nodes
    summary["portal_count"] = len(grids.portals)
    summary["portal_edges"] = portal_edges
    summary["portals_unresolved"] = sum(1 for p in grids.portals if not getattr(p, "resolved", True))
    summary.update(_edge_generation_counts(graph.edges))
    summary["generation_diagnostics"] = {
        **grids.diagnostics,
        "legacy_manual_edge_audit": legacy_manual_audit,
    }
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
