"""Optical-nav perturbation layer: auto-place mirrors + glass walls onto a finished
scene as a SEPARATE, toggleable overlay (base scene untouched).

Purpose: eval whether reflective/transparent surfaces affect navigation. The same
scene geometry can then be rendered base (no perturbation) vs perturbed (mirrors +
glass), and glass walls disable the base-graph edges they cross (toggleable — the
disabled set lives here, not baked into the graph).

The placement is a pure function of (authoring_map, viewpoint_graph) + a seed, so it
runs without the render daemon (CLI / import) and is reused by the editor endpoint.

Sidecar written next to render_scene_overlays.json:  optical_perturbation.json
  { version, enabled, seed, objects: [mirror_wall|glass_wall ...],
    disabled_edge_ids: [...], metadata: {...} }
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from .object_footprint import object_footprint, point_in_footprint

JsonDict = dict[str, Any]

PERTURBATION_VERSION = "opticalnav-optical-perturbation-v0.1"
PERTURBATION_FILENAME = "optical_perturbation.json"

# Mirror geometry sampling (flush sub-segments mounted on a wall face).
_MIRROR_WIDTH_M = (0.6, 1.5)
_MIRROR_BASE_HEIGHT_M = (0.8, 1.2)
_MIRROR_HEIGHT_M = (0.8, 1.6)
_MIRROR_THICKNESS_M = 0.04
_WALL_CORNER_INSET_M = 0.35        # keep mirrors away from corners
_MIRROR_GAP_M = 0.5                # min gap between mirrors on the same wall
_OPENING_CLEARANCE_M = 0.8         # keep mirrors away from doors/windows
_MIRROR_PASSAGE_CLEARANCE_M = 0.15 # reject a mirror only when a nav edge actually passes through it
                                   # (a doorway/threshold crossing) — interior edges run >0.3m off the
                                   # wall (node camera-margin) so parallel edges don't trip it
_MIRROR_PER_METER = 0.22           # ~1 mirror per 4.5 m of wall (× density)
_MIN_ROOM_AREA_M2 = 2.0            # ignore tiny regions (goal/start corners)

# Glass-wall sampling (partial partitions across passages).
_GLASS_HEIGHT_M = 2.2
_GLASS_THICKNESS_M = 0.06
_GLASS_HALF_SPAN_M = 0.7           # wall extends ±this perpendicular to the blocked edge
_GLASS_CROSS_STEP_M = 0.04         # edge-sampling step for the crossing test


# --------------------------------------------------------------------------- #
# object factories                                                            #
# --------------------------------------------------------------------------- #

def _line_object(oid: str, otype: str, material: str, hazard_type: str,
                 start: list[float], end: list[float], height: float,
                 base_height: float, thickness: float, extras: JsonDict) -> JsonDict:
    return {
        "id": oid,
        "type": otype,
        "label": otype.replace("_", " ").title(),
        "placement": "line",
        "geometry": {
            "type": "line",
            "start": [round(float(start[0]), 4), round(float(start[1]), 4)],
            "end": [round(float(end[0]), 4), round(float(end[1]), 4)],
            "height_m": round(float(height), 4),
            "thickness_m": round(float(thickness), 4),
            "base_height_m": round(float(base_height), 4),
        },
        "material": material,
        "navigation": {
            "blocks_navigation": True,
            "hazard_type": hazard_type,
            "include_in_hazard_mask": True,
            "instruction_candidate": True,
            "goal_candidate": False,
        },
        "metadata": {"created_by": "optical_perturbation", **extras},
    }


def _mirror_object(oid: str, start, end, base_height: float, height: float, wall_ref: str) -> JsonDict:
    return _line_object(oid, "mirror_wall", "mirror", "reflective_obstacle",
                        start, end, height, base_height, _MIRROR_THICKNESS_M,
                        {"snapped_to_wall": wall_ref})


def _glass_object(oid: str, start, end, blocked_edge: str) -> JsonDict:
    return _line_object(oid, "glass_wall", "clear_glass", "transparent_obstacle",
                        start, end, _GLASS_HEIGHT_M, 0.0, _GLASS_THICKNESS_M,
                        {"blocks_edge": blocked_edge})


# --------------------------------------------------------------------------- #
# geometry helpers                                                            #
# --------------------------------------------------------------------------- #

def _region_bounds(region: JsonDict) -> list[float] | None:
    geom = region.get("geometry") if isinstance(region.get("geometry"), dict) else region
    b = geom.get("bounds") if isinstance(geom, dict) else None
    if isinstance(b, (list, tuple)) and len(b) >= 4:
        return [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
    return None


def _room_rects(authoring_map: JsonDict) -> list[tuple[str, float, float, float, float]]:
    """Room rectangles at the WALL faces (the floor footprint), not the inset
    traversable region. Mirrors must snap to these so they sit flush on the wall.

    Floor structure objects carry geometry.center + size_m ([x, height, z]); the XY
    rect is center ± half-extent. Falls back to traversable regions if no floors."""
    rects: list[tuple[str, float, float, float, float]] = []
    for o in authoring_map.get("objects") or []:
        md = o.get("metadata") or {}
        if str(md.get("kind")) != "structure":
            continue
        if not str(md.get("blender_name") or "").endswith(".floor"):
            continue
        g = o.get("geometry") or {}
        c, s = g.get("center"), g.get("size_m")
        if not (isinstance(c, (list, tuple)) and len(c) >= 2 and isinstance(s, (list, tuple)) and len(s) >= 3):
            continue
        cx, cy, hx, hy = float(c[0]), float(c[1]), float(s[0]) / 2.0, float(s[2]) / 2.0
        rid = str(md.get("blender_name")).split(".")[0]
        rects.append((rid, cx - hx, cy - hy, cx + hx, cy + hy))
    if not rects:  # non-Infinigen / no floor structures — fall back to regions
        for r in authoring_map.get("regions") or []:
            b = _region_bounds(r)
            if b:
                rects.append((str(r.get("region_id") or r.get("id") or "room"), b[0], b[1], b[2], b[3]))
    return rects


def _opening_points(authoring_map: JsonDict) -> list[tuple[float, float]]:
    """Door + window object centers — mirrors keep clear of these."""
    pts: list[tuple[float, float]] = []
    for o in authoring_map.get("objects") or []:
        t = str(o.get("type") or "")
        kind = str((o.get("metadata") or {}).get("kind") or "")
        if t in ("glass_door", "door") or kind in ("window", "door"):
            c = (o.get("geometry") or {}).get("center")
            if isinstance(c, (list, tuple)) and len(c) >= 2:
                pts.append((float(c[0]), float(c[1])))
    return pts


def _near_opening(x: float, y: float, openings) -> bool:
    return any(math.hypot(x - ox, y - oy) < _OPENING_CLEARANCE_M for ox, oy in openings)


def _edge_crosses_footprint(a: tuple[float, float], b: tuple[float, float], fp,
                            step: float = _GLASS_CROSS_STEP_M) -> bool:
    """True if the segment a→b passes through footprint ``fp`` (grid-free sampling)."""
    dist = math.hypot(b[0] - a[0], b[1] - a[1])
    n = max(2, int(math.ceil(dist / step)))
    for i in range(n + 1):
        t = i / n
        if point_in_footprint(a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t, fp):
            return True
    return False


def _edge_cut_by_footprint(a: tuple[float, float], b: tuple[float, float], fp,
                           step: float = _GLASS_CROSS_STEP_M) -> bool:
    """True only if a→b is *severed* by ``fp`` — both endpoints clear of the obstacle
    but an interior point inside it. Distinguishes an edge that drives THROUGH a wall
    (a real cut) from one that merely runs PARALLEL inside a wall-mounted mirror's
    inflated band (endpoints buried → not a cut), avoiding false positives that would
    drop traversable along-the-wall edges."""
    if point_in_footprint(a[0], a[1], fp) or point_in_footprint(b[0], b[1], fp):
        return False
    dist = math.hypot(b[0] - a[0], b[1] - a[1])
    n = max(2, int(math.ceil(dist / step)))
    for i in range(1, n):
        t = i / n
        if point_in_footprint(a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t, fp):
            return True
    return False


def _num_components(node_ids: set[str], edges: list[tuple[str, str]]) -> int:
    adj: dict[str, list[str]] = {n: [] for n in node_ids}
    for s, t in edges:
        if s in adj and t in adj:
            adj[s].append(t)
            adj[t].append(s)
    seen: set[str] = set()
    comps = 0
    for start in node_ids:
        if start in seen:
            continue
        comps += 1
        stack = [start]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(adj[x])
    return comps


# --------------------------------------------------------------------------- #
# placement                                                                   #
# --------------------------------------------------------------------------- #

def _rect_segments(rects: list[tuple[str, float, float, float, float]]) -> list[tuple[str, tuple, tuple]]:
    """4 axis-aligned wall segments per room rect (fallback when mesh walls unavailable)."""
    segs = []
    for rid, minx, miny, maxx, maxy in rects:
        if (maxx - minx) * (maxy - miny) < _MIN_ROOM_AREA_M2:
            continue
        segs.append((f"{rid}:S", (minx, miny), (maxx, miny)))
        segs.append((f"{rid}:N", (minx, maxy), (maxx, maxy)))
        segs.append((f"{rid}:W", (minx, miny), (minx, maxy)))
        segs.append((f"{rid}:E", (maxx, miny), (maxx, maxy)))
    return segs


def _wall_segments_from_floor_meshes(scene_dir: Path) -> list[tuple[str, tuple, tuple]]:
    """Real wall segments = the boundary polygon of each room's FLOOR mesh, in authoring
    XY (handles diagonal / non-rectangular rooms). Returns [] if meshes/trimesh are
    unavailable so the caller can fall back to room-rectangle edges."""
    try:
        import numpy as np
        from .graph_pipeline import _infinigen_inputs
        from .walkable_surface import _load_unit_faces
    except Exception:
        return []
    inputs = _infinigen_inputs(Path(scene_dir))
    if inputs is None:
        return []
    import_root, origin_offset = inputs
    try:
        manifest = json.loads((import_root / "scene_manifest.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    segments: list[tuple[str, tuple, tuple]] = []
    for u in manifest.get("units") or []:
        bn = str(u.get("blender_name") or "")
        if u.get("subtype") != "floor" and not bn.endswith(".floor"):
            continue
        xy, faces = _load_unit_faces(import_root, u, origin_offset)
        if len(xy) == 0 or len(faces) == 0:
            continue
        rid = bn.split(".")[0] or "room"
        for a, b in _boundary_polylines(np.asarray(xy), np.asarray(faces)):
            segments.append((rid, (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))))
    return segments


def _boundary_polylines(verts_xy, faces) -> list[tuple]:
    """Mesh boundary edges (used by exactly one triangle), merged into straight wall
    runs (collinear edges joined). Returns a list of (p0, p1) segments."""
    import numpy as np
    from collections import Counter, defaultdict

    ec: Counter = Counter()
    for tri in faces:
        for i in range(3):
            a, b = int(tri[i]), int(tri[(i + 1) % 3])
            ec[(min(a, b), max(a, b))] += 1
    badj: dict[int, list[int]] = defaultdict(list)
    for (a, b), c in ec.items():
        if c == 1:
            badj[a].append(b)
            badj[b].append(a)
    # Walk boundary loops, simplify near-collinear vertices, emit polygon edges.
    visited: set[int] = set()
    segs: list[tuple] = []
    for start in list(badj):
        if start in visited or len(badj[start]) == 0:
            continue
        loop = [start]
        visited.add(start)
        prev, cur = None, start
        while True:
            nxts = [n for n in badj[cur] if n != prev]
            nxt = next((n for n in nxts if n != start), nxts[0] if nxts else None)
            if nxt is None or nxt == start or nxt in visited:
                break
            loop.append(nxt)
            visited.add(nxt)
            prev, cur = cur, nxt
        if len(loop) < 2:
            continue
        pts = [verts_xy[i] for i in loop] + [verts_xy[loop[0]]]
        # collinear simplification: keep a vertex only if it bends the path enough.
        keep = [pts[0]]
        for i in range(1, len(pts) - 1):
            p0, p1, p2 = keep[-1], pts[i], pts[i + 1]
            v1 = np.array(p1) - np.array(p0)
            v2 = np.array(p2) - np.array(p1)
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 < 1e-6:
                continue
            cosang = float(np.dot(v1, v2) / (n1 * n2)) if n2 > 1e-6 else 1.0
            if cosang < 0.985:   # > ~10° turn → real corner, keep it
                keep.append(p1)
        keep.append(pts[-1])
        for i in range(len(keep) - 1):
            segs.append((keep[i], keep[i + 1]))
    return segs


def place_mirrors(wall_segments: list[tuple[str, tuple, tuple]], openings: list[tuple[float, float]],
                  edges: list[tuple[tuple, tuple]], *, rng: random.Random, density: float = 1.0) -> list[JsonDict]:
    """Mirrors flush ON the given wall segments (real, possibly diagonal, room outline)
    — varied width/height, spaced, mounted (not floor-to-ceiling, not floating). A
    candidate is REJECTED if it sits over a door/window or if its footprint would block
    a navigation edge (a passage/doorway), so mirrors never seal a walkable route."""
    mirrors: list[JsonDict] = []
    seq = 0
    for rid, (x0, y0), (x1, y1) in wall_segments:
        seglen = math.hypot(x1 - x0, y1 - y0)
        usable = seglen - 2 * _WALL_CORNER_INSET_M
        if usable < _MIRROR_WIDTH_M[0]:
            continue
        ux, uy = (x1 - x0) / seglen, (y1 - y0) / seglen   # unit direction along the wall
        target = max(0, int(round(usable * _MIRROR_PER_METER * max(0.0, density))))
        cursor = _WALL_CORNER_INSET_M
        placed = 0
        while placed < target and cursor < seglen - _WALL_CORNER_INSET_M - _MIRROR_WIDTH_M[0]:
            w = min(rng.uniform(*_MIRROR_WIDTH_M), seglen - _WALL_CORNER_INSET_M - cursor)
            if w < _MIRROR_WIDTH_M[0]:
                break
            t0, t1 = cursor, cursor + w
            start = (x0 + ux * t0, y0 + uy * t0)
            end = (x0 + ux * t1, y0 + uy * t1)
            mx, my = (start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0
            if not _near_opening(mx, my, openings) and not _blocks_a_passage(start, end, edges):
                seq += 1
                mirrors.append(_mirror_object(
                    f"mirror_auto_{seq:03d}", list(start), list(end),
                    rng.uniform(*_MIRROR_BASE_HEIGHT_M), rng.uniform(*_MIRROR_HEIGHT_M), rid))
                placed += 1
            cursor = t1 + _MIRROR_GAP_M + rng.uniform(0.0, 1.0)
    return mirrors


def _blocks_a_passage(start: tuple, end: tuple, edges: list[tuple[tuple, tuple]]) -> bool:
    """True if a mirror at [start,end] would block a nav edge (passage/doorway). The
    mirror footprint is inflated by robot clearance so it never pinches a route."""
    if not edges:
        return False
    fp = object_footprint({"type": "line", "start": list(start), "end": list(end),
                           "thickness_m": _MIRROR_THICKNESS_M}, margin=_MIRROR_PASSAGE_CLEARANCE_M)
    if fp is None:
        return False
    return any(_edge_crosses_footprint(a, b, fp) for a, b in edges)


def place_glass_walls(authoring_map: JsonDict, graph: JsonDict, *, rng: random.Random,
                      max_walls: int = 2) -> tuple[list[JsonDict], list[str]]:
    """Place a few glass walls across graph edges, disabling the edges each crosses —
    but only when a detour remains (graph stays one component after removal)."""
    nodes = {n.get("node_id") or n.get("id"): n for n in (graph.get("nodes") or [])}
    pos = {nid: (float(n["position"][0]), float(n["position"][1]))
           for nid, n in nodes.items() if n.get("position")}
    edges = [(e.get("edge_id"), e.get("source"), e.get("target"))
             for e in (graph.get("edges") or [])
             if e.get("source") in pos and e.get("target") in pos]
    if not edges:
        return [], []
    node_ids = set(pos)
    base_comps = _num_components(node_ids, [(s, t) for _, s, t in edges])

    # Candidate edges to block: longest first (most "straight path" worth detouring),
    # with a little jitter so successive runs differ.
    def _elen(e):
        _, s, t = e
        return math.hypot(pos[t][0] - pos[s][0], pos[t][1] - pos[s][1])
    candidates = sorted(edges, key=lambda e: -_elen(e) + rng.uniform(-0.1, 0.1))

    glass: list[JsonDict] = []
    disabled: set[str] = set()
    seq = 0
    for eid, s, t in candidates:
        if len(glass) >= max_walls:
            break
        ax, ay = pos[s]
        bx, by = pos[t]
        mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
        # glass wall perpendicular to the edge, centered at its midpoint.
        d = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / d, (bx - ax) / d   # unit normal
        gstart = [mx - nx * _GLASS_HALF_SPAN_M, my - ny * _GLASS_HALF_SPAN_M]
        gend = [mx + nx * _GLASS_HALF_SPAN_M, my + ny * _GLASS_HALF_SPAN_M]
        fp = object_footprint({"type": "line", "start": gstart, "end": gend,
                               "thickness_m": _GLASS_THICKNESS_M}, margin=_GLASS_THICKNESS_M)
        if fp is None:
            continue
        crossed = {ce for ce, cs, ct in edges
                   if _edge_crosses_footprint(pos[cs], pos[ct], fp)}
        if not crossed or crossed & disabled:
            continue
        # detour guard: removing these (and already-disabled) edges must not split rooms.
        remaining = [(cs, ct) for ce, cs, ct in edges if ce not in (disabled | crossed)]
        if _num_components(node_ids, remaining) != base_comps:
            continue
        seq += 1
        glass.append(_glass_object(f"glass_auto_{seq:03d}", gstart, gend, str(eid)))
        disabled |= crossed
    return glass, sorted(disabled)


# --------------------------------------------------------------------------- #
# orchestration + IO                                                          #
# --------------------------------------------------------------------------- #

def perturbation_path(scene_dir: Path) -> Path:
    return Path(scene_dir) / PERTURBATION_FILENAME


def load_perturbation(scene_dir: Path) -> JsonDict | None:
    p = perturbation_path(scene_dir)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def disabled_edge_ids(
    perturbation: JsonDict | None,
    nodes_xy: dict[str, tuple[float, float]],
    edges: list[tuple[str, str, str]],
) -> set[str]:
    """Edge ids blocked by an ENABLED perturbation overlay.

    The blocked set is recomputed *geometrically* against the CURRENT graph (so it
    stays correct after a graph rebuild reissued edge ids) and unioned with any
    stored ``disabled_edge_ids`` whose edge is still present. Glass walls cut
    edges that pass through them; mirrors are flush on walls and normally don't,
    but are checked too (a mirror that happens to seal a passage disables it).

    ``nodes_xy``: node_id -> (x, y). ``edges``: list of (edge_id, source, target).
    Returns an empty set when the overlay is missing or disabled.
    """
    if not perturbation or not perturbation.get("enabled", True):
        return set()
    valid_edges = [(eid, s, t) for eid, s, t in edges if eid and s in nodes_xy and t in nodes_xy]
    blocked: set[str] = set()
    for obj in perturbation.get("objects") or []:
        otype = str(obj.get("type") or "")
        if otype == "glass_wall":
            margin = _GLASS_THICKNESS_M
        elif otype == "mirror_wall":
            margin = _MIRROR_PASSAGE_CLEARANCE_M
        else:
            continue
        fp = object_footprint(obj.get("geometry") or {}, margin=margin)
        if fp is None:
            continue
        for eid, s, t in valid_edges:
            if eid in blocked:
                continue
            if _edge_cut_by_footprint(nodes_xy[s], nodes_xy[t], fp):
                blocked.add(str(eid))
    present = {str(eid) for eid, _, _ in edges if eid}
    blocked |= {str(eid) for eid in (perturbation.get("disabled_edge_ids") or []) if str(eid) in present}
    return blocked


def disabled_edges_for_scene(scene_dir: Path, graph: Any) -> set[str]:
    """Convenience wrapper: load the scene's perturbation sidecar and return the set
    of edge ids it blocks for ``graph`` (a ViewpointGraph; duck-typed so this module
    stays import-light). Empty when there is no enabled overlay."""
    pert = load_perturbation(Path(scene_dir))
    if not pert or not pert.get("enabled", True):
        return set()
    nodes_xy: dict[str, tuple[float, float]] = {}
    for n in getattr(graph, "nodes", []) or []:
        pos = getattr(n, "position", None)
        if pos is not None and len(pos) >= 2:
            nodes_xy[n.node_id] = (float(pos[0]), float(pos[1]))
    edges = [(e.edge_id, e.source, e.target) for e in (getattr(graph, "edges", []) or [])]
    return disabled_edge_ids(pert, nodes_xy, edges)


def build_optical_perturbation(scene_dir: Path, *, seed: int = 0, enabled: bool = True,
                               mirror_density: float = 1.0, max_glass_walls: int = 2,
                               write: bool = True) -> JsonDict:
    """Generate the perturbation overlay for a materialized scene dir and (optionally)
    write the sidecar. Reads authoring_map.json + viewpoint_graph.json."""
    scene_dir = Path(scene_dir)
    authoring_map = json.loads((scene_dir / "authoring_map.json").read_text(encoding="utf-8"))
    graph_path = scene_dir / "viewpoint_graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.is_file() else {"nodes": [], "edges": []}

    rng = random.Random(int(seed))
    # Real wall segments from the floor-mesh boundary (diagonal-aware); fall back to
    # room-rectangle edges if meshes/trimesh aren't available.
    wall_segments = _wall_segments_from_floor_meshes(scene_dir)
    wall_source = "floor_mesh_boundary"
    if not wall_segments:
        wall_segments = _rect_segments(_room_rects(authoring_map))
        wall_source = "room_rect_fallback"
    openings = _opening_points(authoring_map)
    # Nav edges (world segments) so mirrors never block a passage/doorway.
    _pos = {n.get("node_id") or n.get("id"): n for n in (graph.get("nodes") or [])}
    edges = [((float(_pos[e["source"]]["position"][0]), float(_pos[e["source"]]["position"][1])),
              (float(_pos[e["target"]]["position"][0]), float(_pos[e["target"]]["position"][1])))
             for e in (graph.get("edges") or [])
             if e.get("source") in _pos and e.get("target") in _pos
             and _pos[e["source"]].get("position") and _pos[e["target"]].get("position")]
    mirrors = place_mirrors(wall_segments, openings, edges, rng=rng, density=mirror_density)
    glass, disabled = place_glass_walls(authoring_map, graph, rng=rng, max_walls=max_glass_walls)

    payload: JsonDict = {
        "version": PERTURBATION_VERSION,
        "scene_id": authoring_map.get("scene_id"),
        "enabled": bool(enabled),
        "seed": int(seed),
        "objects": mirrors + glass,
        "disabled_edge_ids": disabled,
        "metadata": {
            "source": "optical_perturbation",
            "mirror_count": len(mirrors),
            "glass_wall_count": len(glass),
            "disabled_edge_count": len(disabled),
            "mirror_density": mirror_density,
            "wall_source": wall_source,
        },
    }
    if write:
        perturbation_path(scene_dir).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
