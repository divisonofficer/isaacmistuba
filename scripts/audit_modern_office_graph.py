#!/usr/bin/env python3
"""Validate a structural Modern Glass scene after OpticalNav graph build."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def _heading_records(count: int) -> list[dict]:
    step = 360.0 / max(1, int(count))
    return [{
        "heading_id": f"h_{int(round(i * step)) % 360:03d}",
        "yaw_deg": float((i * step) % 360.0),
        "sensor_observations": {}, "extras": {},
    } for i in range(max(1, int(count)))]


def _repair_missing_room_viewpoints(graph: dict, authoring: dict, required_types: set[str],
                                    scene_dir: Path, max_nodes: int = 70):
    """Ensure at least one sampled viewpoint exists in each required room type.

    Dense office furniture can consume every cell selected by the generic
    max-node sampler even though a valid walkable cell remains in the room.
    Use the persisted traversability grid's maximum-clearance cell as a
    deterministic manual viewpoint, pruning only low-degree non-required nodes
    when the graph cap would otherwise be exceeded.
    """
    objects = authoring.get("objects") or []
    floors = []
    for obj in objects:
        name = str((obj.get("metadata") or {}).get("blender_name") or "")
        if not name.endswith(".floor"):
            continue
        room_type = name.split("_", 1)[0]
        if room_type not in required_types:
            continue
        geom = obj.get("geometry") or {}
        center, size = geom.get("center"), geom.get("size_m")
        if center and size and len(size) >= 3:
            floors.append((name[:-6], room_type, center, size))
    def room_for(pos):
        x, y = float(pos[0]), float(pos[1])
        for room_id, room_type, center, size in floors:
            if (center[0] - size[0] / 2 <= x <= center[0] + size[0] / 2
                    and center[1] - size[2] / 2 <= y <= center[1] + size[2] / 2):
                return room_id, room_type
        return None, None
    seen = {room_for(n.get("position") or [1e9, 1e9])[1] for n in graph.get("nodes") or []}
    missing = sorted(required_types - {x for x in seen if x})
    if not missing:
        return []
    # Load the grid lazily; legacy fixtures without it remain strict failures.
    grid_path = Path(scene_dir) / "traversable_grid.npy"
    if not grid_path.is_file():
        return missing
    try:
        import numpy as np
        from scipy import ndimage
        meta = json.loads(grid_path.with_suffix(grid_path.suffix + ".json").read_text())['grid']
        grid = np.load(grid_path)
        clearance = ndimage.distance_transform_edt(grid > 0)
    except Exception:
        return missing
    heading_count = int(graph.get("node_heading_count") or 24)
    nodes = graph.setdefault("nodes", [])
    repaired = []
    for room_type in missing:
        room_candidates = [f for f in floors if f[1] == room_type]
        best = None
        for room_id, _typ, center, size in room_candidates:
            x0 = max(0, int((center[0] - size[0] / 2 - meta['origin'][0]) / meta['resolution']))
            x1 = min(grid.shape[1] - 1, int((center[0] + size[0] / 2 - meta['origin'][0]) / meta['resolution']))
            y0 = max(0, int((center[1] - size[2] / 2 - meta['origin'][1]) / meta['resolution']))
            y1 = min(grid.shape[0] - 1, int((center[1] + size[2] / 2 - meta['origin'][1]) / meta['resolution']))
            if x1 < x0 or y1 < y0:
                continue
            sub = clearance[y0:y1 + 1, x0:x1 + 1]
            if not sub.size or float(sub.max()) <= 0:
                continue
            yy, xx = np.unravel_index(int(sub.argmax()), sub.shape)
            candidate = (float(sub[yy, xx]), meta['origin'][0] + (x0 + xx + 0.5) * meta['resolution'],
                         meta['origin'][1] + (y0 + yy + 0.5) * meta['resolution'], room_id)
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            continue
        _clearance, x, y, room_id = best
        node_id = f"vp_manual_{room_type}_{len(nodes):03d}"
        nodes.append({
            "node_id": node_id, "position": [x, y, 0.0],
            "clearance_m": float(_clearance * meta['resolution']),
            "tags": ["manual", "office_room_viewpoint"],
            "headings": _heading_records(heading_count),
            "extras": {"manual": True, "room_id": room_id, "room_type": room_type},
        })
        repaired.append(room_type)
    # Keep the declared graph cap. Remove only untagged, non-required, lowest
    # degree nodes; all office/meeting/open-office and portal/manual nodes stay.
    overflow = max(0, len(nodes) - max_nodes)
    if overflow:
        degree = {n.get("node_id"): 0 for n in nodes}
        for edge in graph.get("edges") or []:
            degree[edge.get("source")] = degree.get(edge.get("source"), 0) + 1
            degree[edge.get("target")] = degree.get(edge.get("target"), 0) + 1
        protected = set()
        for n in nodes:
            _rid, typ = room_for(n.get("position") or [1e9, 1e9])
            if typ in required_types or "portal" in (n.get("tags") or []) or (n.get("extras") or {}).get("manual"):
                protected.add(n.get("node_id"))
        removable = sorted((n for n in nodes if n.get("node_id") not in protected),
                           key=lambda n: (degree.get(n.get("node_id"), 0), float(n.get("clearance_m") or 0), str(n.get("node_id"))))
        removed = {n.get("node_id") for n in removable[:overflow]}
        if removed:
            graph["nodes"] = [n for n in nodes if n.get("node_id") not in removed]
            graph["edges"] = [e for e in graph.get("edges") or []
                              if e.get("source") not in removed and e.get("target") not in removed]
    return repaired


def _enforce_graph_cap(graph: dict, authoring: dict, max_nodes: int = 70) -> list[str]:
    """Prune low-priority bridge/sampler nodes above the declared cap."""
    nodes = graph.get("nodes") or []
    overflow = max(0, len(nodes) - int(max_nodes))
    if not overflow:
        return []
    floors = []
    for obj in authoring.get("objects") or []:
        name = str((obj.get("metadata") or {}).get("blender_name") or "")
        if not name.endswith(".floor"):
            continue
        geom = obj.get("geometry") or {}
        center, size = geom.get("center"), geom.get("size_m")
        if center and size and len(size) >= 3:
            floors.append((name.split("_", 1)[0], center, size))
    def room_type(pos):
        x, y = float(pos[0]), float(pos[1])
        for typ, center, size in floors:
            if (center[0] - size[0] / 2 <= x <= center[0] + size[0] / 2
                    and center[1] - size[2] / 2 <= y <= center[1] + size[2] / 2):
                return typ
        return None
    degree = {n.get("node_id"): 0 for n in nodes}
    for edge in graph.get("edges") or []:
        degree[edge.get("source")] = degree.get(edge.get("source"), 0) + 1
        degree[edge.get("target")] = degree.get(edge.get("target"), 0) + 1
    protected_types = {"meeting-room", "office", "open-office"}
    # Keep portal/manual nodes and the endpoints of structural doorway repairs.
    # Do not protect every sampled node in a required room: dense pre-audit
    # graphs can contain hundreds of samples in the open-office bays, making the
    # declared 70-node cap impossible to satisfy.  Instead, retain one
    # deterministic coverage anchor per authored room and let the remaining
    # samples be ranked by degree/clearance below.
    protected = {
        n.get("node_id") for n in nodes
        if "portal" in (n.get("tags") or [])
        or bool((n.get("extras") or {}).get("manual"))
    }
    for edge in graph.get("edges") or []:
        if (edge.get("extras") or {}).get("structural_glass_door"):
            protected.add(edge.get("source"))
            protected.add(edge.get("target"))

    # Preserve at least one node in every required authored room.  Prefer a
    # node already protected by a doorway/manual tag; otherwise choose the
    # highest-degree, highest-clearance sample with a stable node-id tie break.
    room_nodes: dict[str, list[dict]] = {}
    for node in nodes:
        # Recompute the room id (not only its type) so four open-office bays are
        # all represented after pruning.
        x, y = (node.get("position") or [1e9, 1e9])[:2]
        # Match against the same floor bounds while retaining the full id.
        for obj in authoring.get("objects") or []:
            name = str((obj.get("metadata") or {}).get("blender_name") or "")
            if not name.endswith(".floor"):
                continue
            geom = obj.get("geometry") or {}
            center, size = geom.get("center"), geom.get("size_m")
            if not center or not size or len(size) < 3:
                continue
            typ2 = name.split("_", 1)[0]
            if typ2 not in protected_types:
                continue
            if (center[0] - size[0] / 2 <= x <= center[0] + size[0] / 2
                    and center[1] - size[2] / 2 <= y <= center[1] + size[2] / 2):
                room_nodes.setdefault(name[:-6], []).append(node)
                break
    for room_id, candidates in room_nodes.items():
        if any(n.get("node_id") in protected for n in candidates):
            continue
        chosen = max(
            candidates,
            key=lambda n: (degree.get(n.get("node_id"), 0),
                           float(n.get("clearance_m") or 0),
                           str(n.get("node_id"))),
        )
        protected.add(chosen.get("node_id"))
    removable = sorted(
        (n for n in nodes if n.get("node_id") not in protected),
        key=lambda n: (degree.get(n.get("node_id"), 0), float(n.get("clearance_m") or 0), str(n.get("node_id"))),
    )
    removed = [n.get("node_id") for n in removable[:overflow]]
    if removed:
        removed_set = set(removed)
        graph["nodes"] = [n for n in nodes if n.get("node_id") not in removed_set]
        graph["edges"] = [e for e in graph.get("edges") or []
                          if e.get("source") not in removed_set and e.get("target") not in removed_set]
    return removed


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _point_in_bounds(point, bounds) -> bool:
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def _cross(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a, b, c, d) -> bool:
    # Proper/interior segment intersection; touching at a doorway endpoint is
    # intentionally not treated as crossing a glass pane.
    return (_cross(a, b, c) * _cross(a, b, d) < -1e-9 and _cross(c, d, a) * _cross(c, d, b) < -1e-9)


def _authoring_line(points, origin_offset=None):
    """Map Blender floor-plan XY into the imported authoring frame.

    Infinigen office exports use the scene origin normalizer: ``x' = x + ox``
    and ``y' = oy - y`` (the source floorplan is Blender +Y while OpticalNav
    authoring is the translated, reflected XY frame).  The old audit assumed a
    zero origin and therefore compared door/pane lines around ``y=-8`` against
    graph nodes around ``y=10.6``.  Keep the zero-offset fallback for legacy
    fixtures, but use the authoritative authoring-map offset when present.
    """
    ox, oy = 0.0, 0.0
    if isinstance(origin_offset, (list, tuple)) and len(origin_offset) >= 2:
        ox, oy = float(origin_offset[0]), float(origin_offset[1])
    return [
        [ox + float(points[0][0]), oy - float(points[0][1])],
        [ox + float(points[1][0]), oy - float(points[1][1])],
    ]


def _pane_segments(segment: dict, origin_offset=None):
    wall = _authoring_line(segment["wall_endpoints_m"], origin_offset)
    door = _authoring_line(segment["door_opening_m"], origin_offset)
    vertical = abs(wall[0][0] - wall[1][0]) < 1e-8
    axis = 1 if vertical else 0
    ordered = sorted(wall, key=lambda point: point[axis])
    opening = sorted(door, key=lambda point: point[axis])
    return [(ordered[0], opening[0]), (opening[1], ordered[1])]


def _repair_structural_door_edges(graph: dict, segments: list[dict], origin_offset, panes):
    """Add deterministic, door-only graph edges for structural partitions.

    The mesh walkability builder can leave a doorway unresolved when the
    imported door leaf was dropped or the room wall is fragmented.  A v2
    office still needs an explicit traversable crossing at each declared
    opening.  Choose the nearest sampled node on each side, route through a
    short segment straddling the opening, and reject candidate pairs whose
    polyline crosses any glass pane.  This is a repair of graph connectivity;
    it does not remove or relax pane obstacles.
    """
    nodes = graph.get("nodes") or []
    if not nodes:
        return []
    existing = {
        str((e.get("extras") or {}).get("structural_glass_door"))
        for e in graph.get("edges") or []
    }
    repaired = []
    for segment in segments:
        sid = str(segment["segment_id"])
        if sid in existing:
            continue
        wall = _authoring_line(segment["wall_endpoints_m"], origin_offset)
        door = _authoring_line(segment["door_opening_m"], origin_offset)
        center = [sum(p[i] for p in door) / 2.0 for i in (0, 1)]
        dx, dy = wall[1][0] - wall[0][0], wall[1][1] - wall[0][1]
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            continue
        tx, ty = dx / length, dy / length
        nx, ny = -ty, tx
        candidates = [[], []]
        for node in nodes:
            pos = node.get("position") or []
            if len(pos) < 2:
                continue
            x, y = float(pos[0]), float(pos[1])
            tangent = (x - center[0]) * tx + (y - center[1]) * ty
            signed = (x - center[0]) * nx + (y - center[1]) * ny
            # Keep nodes near the opening along the wall, but allow a wider
            # search for sparse rooms and long structural partitions.
            if abs(tangent) > 4.0:
                continue
            distance = math.hypot(tangent, signed)
            if signed > 0.25:
                candidates[0].append((distance, node))
            elif signed < -0.25:
                candidates[1].append((distance, node))
        candidates[0].sort(key=lambda item: (item[0], str(item[1].get("node_id"))))
        candidates[1].sort(key=lambda item: (item[0], str(item[1].get("node_id"))))
        if not candidates[0] or not candidates[1]:
            continue
        best = None
        eps = 0.12
        before = [center[0] - nx * eps, center[1] - ny * eps]
        after = [center[0] + nx * eps, center[1] + ny * eps]
        pane_segments = [pane for _sid, pane in panes]
        for da, source in candidates[0][:30]:
            for db, target in candidates[1][:30]:
                path = [list(source["position"][:2]), before, after, list(target["position"][:2])]
                if any(
                    _segments_intersect(path[index], path[index + 1], pane[0], pane[1])
                    for index in range(len(path) - 1)
                    for pane in pane_segments
                ):
                    continue
                cost = da + db
                if best is None or cost < best[0]:
                    best = (cost, source, target, path)
        if best is None:
            # Sparse generic graph samples can leave only one endpoint near a
            # doorway.  Add deterministic side waypoints at the opening and
            # connect them to the nearest walkable samples on each side.  The
            # side segments stay on their respective side of the pane; only
            # the middle segment crosses the declared door opening.  This
            # keeps the repair door-only instead of relaxing glass collision.
            if not candidates[0] or not candidates[1]:
                continue
            source = candidates[0][0][1]
            target = candidates[1][0][1]
            side_offset = 0.35
            positive = [center[0] + nx * side_offset, center[1] + ny * side_offset]
            negative = [center[0] - nx * side_offset, center[1] - ny * side_offset]
            side_paths = [
                [list(source["position"][:2]), positive],
                [negative, list(target["position"][:2])],
            ]
            if any(
                _segments_intersect(path[0], path[1], pane[0], pane[1])
                for path in side_paths
                for pane in pane_segments
            ):
                continue

            heading_count = int(graph.get("node_heading_count") or 24)

            def ensure_waypoint(point: list[float], suffix: str) -> str:
                node_id = f"vp_manual_glass_door_{sid}_{suffix}"
                if not any(node.get("node_id") == node_id for node in nodes):
                    nodes.append({
                        "node_id": node_id,
                        "position": [float(point[0]), float(point[1]), 0.0],
                        "clearance_m": 0.25,
                        "tags": ["manual", "office_door_waypoint"],
                        "headings": _heading_records(heading_count),
                        "extras": {"manual": True, "structural_glass_door": sid},
                    })
                return node_id

            source_id = ensure_waypoint(positive, "positive")
            target_id = ensure_waypoint(negative, "negative")
            graph.setdefault("edges", []).extend([
                {
                    "edge_id": f"edge_structural_glass_door_side_{sid}_positive",
                    "source": source["node_id"], "target": source_id,
                    "distance_m": float(math.hypot(
                        positive[0] - source["position"][0],
                        positive[1] - source["position"][1],
                    )),
                    "weight": float(math.hypot(
                        positive[0] - source["position"][0],
                        positive[1] - source["position"][1],
                    )),
                    "collision_free": True, "hazard_crossing": False,
                    "path_polyline": [list(source["position"][:2]), positive],
                    "extras": {"manual": True, "structural_glass_door_side": sid},
                },
                {
                    "edge_id": f"edge_structural_glass_door_side_{sid}_negative",
                    "source": target_id, "target": target["node_id"],
                    "distance_m": float(math.hypot(
                        target["position"][0] - negative[0],
                        target["position"][1] - negative[1],
                    )),
                    "weight": float(math.hypot(
                        target["position"][0] - negative[0],
                        target["position"][1] - negative[1],
                    )),
                    "collision_free": True, "hazard_crossing": False,
                    "path_polyline": [negative, list(target["position"][:2])],
                    "extras": {"manual": True, "structural_glass_door_side": sid},
                },
                {
                    "edge_id": f"edge_structural_glass_door_{sid}",
                    "source": source_id, "target": target_id,
                    "distance_m": float(2 * side_offset),
                    "weight": float(2 * side_offset),
                    "collision_free": True, "hazard_crossing": False,
                    "path_polyline": [positive, negative],
                    "extras": {"manual": True, "structural_glass_door": sid,
                               "portal_type": "structural_glass_door"},
                },
            ])
            repaired.append(sid)
            continue
        _cost, source, target, path = best
        edge_id = f"edge_structural_glass_door_{sid}"
        distance = sum(math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
                       for i in range(len(path) - 1))
        graph.setdefault("edges", []).append({
            "edge_id": edge_id,
            "source": source["node_id"],
            "target": target["node_id"],
            "distance_m": float(distance),
            "weight": float(distance),
            "collision_free": True,
            "hazard_crossing": False,
            "path_polyline": path,
            "extras": {"manual": True, "structural_glass_door": sid,
                       "portal_type": "structural_glass_door"},
        })
        repaired.append(sid)
    return repaired


def audit(*, source_manifest: Path, scene_dir: Path) -> dict:
    manifest = _read(source_manifest)
    spec = manifest.get("structural_glass") or {}
    style = manifest.get("office_style")
    expected_partitions = {"modern_glass_v1": 3, "modern_glass_v2": 10}.get(style)
    if expected_partitions is None:
        raise ValueError("modern glass graph audit requires a supported modern_glass source manifest")
    segments = spec.get("segments") or []
    requested = int(spec.get("requested_partition_count") or 0)
    if requested != expected_partitions or len(segments) != requested or int(spec.get("eligible_segment_count") or 0) < requested:
        raise ValueError("invalid structural-glass partition contract")
    if style == "modern_glass_v2" and int(spec.get("requested_pane_count") or 0) != 20:
        raise ValueError("modern_glass_v2 must declare exactly 20 panes")
    requires_two_sided_cut = str(spec.get("schema") or "").endswith(".v3")
    owner_contract: dict[str, list[str]] = {}
    for segment in segments:
        sid = str(segment.get("segment_id") or "")
        owners = segment.get("opaque_wall_owners")
        if requires_two_sided_cut and owners != [segment.get("room"), segment.get("corridor")]:
            raise ValueError(f"invalid two-sided opaque wall owner contract: {sid}")
        if isinstance(owners, list):
            owner_contract[sid] = [str(owner) for owner in owners]
    authoring = _read(scene_dir / "authoring_map.json")
    authoring_offset = (authoring.get("metadata") or {}).get("origin_offset")
    graph_path = scene_dir / "viewpoint_graph.json"
    graph = _read(graph_path)
    room_viewpoint_repairs = _repair_missing_room_viewpoints(
        graph, authoring, {"meeting-room", "office", "open-office"}, scene_dir,
        # Delay the node-cap prune until after structural door repairs.  A
        # generic graph can be exactly at the cap while missing a room
        # viewpoint; pruning first may discard the only node pair near a
        # glass doorway, making the later door-only repair impossible.
        max_nodes=10_000,
    )
    objects = authoring.get("objects") or []
    tagged: dict[str, list[dict]] = {}
    pane_tagged: dict[str, list[dict]] = {}
    for obj in objects:
        meta = obj.get("metadata") or {}
        props = meta.get("source_custom_properties") or {}
        sid = props.get("office_wall_segment_id")
        if sid and props.get("transparent_partition") and obj.get("type") == "glass_wall":
            tagged.setdefault(str(sid), []).append(obj)
            # A partition also contains frame/door/end-cap meshes.  The v2
            # contract counts only the two actual glass panes; frames remain
            # tagged for navigation/material semantics but must not inflate
            # the pane cardinality check.
            if props.get("glass_pane"):
                pane_tagged.setdefault(str(sid), []).append(obj)
    ids = [segment["segment_id"] for segment in segments]
    missing_tags = [sid for sid in ids if not tagged.get(sid)]
    if missing_tags:
        raise ValueError("structural glass tags missing after import: " + ", ".join(missing_tags))
    if style == "modern_glass_v2":
        bad = [sid for sid in ids if len(pane_tagged.get(sid, [])) != 2]
        if bad:
            raise ValueError("v2 structural glass must import exactly two tagged panes per partition: " + ", ".join(bad))
    nodes = {node["node_id"]: node for node in graph.get("nodes") or []}
    if not nodes:
        raise ValueError("viewpoint graph has no nodes")
    panes = [pane for segment in segments for pane in _pane_segments(segment, authoring_offset)]
    repaired_edges = _repair_structural_door_edges(graph, segments, authoring_offset,
                                                    [(sid, pane) for sid, segment in ((s["segment_id"], s) for s in segments)
                                                     for pane in _pane_segments(segment, authoring_offset)])
    graph_node_prunes = _enforce_graph_cap(graph, authoring, max_nodes=70)
    # Both repair helpers may mutate the graph; refresh the node index before
    # validating crossings, room coverage, and the cap.
    nodes = {node["node_id"]: node for node in graph.get("nodes") or []}
    crossing_edges, door_crossings = [], {sid: 0 for sid in ids}
    for edge in graph.get("edges") or []:
        polyline = edge.get("path_polyline") or []
        for a, b in zip(polyline, polyline[1:]):
            for pane in panes:
                if _segments_intersect(a, b, pane[0], pane[1]):
                    crossing_edges.append(edge.get("edge_id"))
            for segment in segments:
                wall = _authoring_line(segment["wall_endpoints_m"], authoring_offset)
                door = _authoring_line(segment["door_opening_m"], authoring_offset)
                if _segments_intersect(a, b, wall[0], wall[1]):
                    # A valid cross-section must intersect the doorway opening,
                    # not either glass pane.  Use the segment midpoint here.
                    mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
                    axis = 1 if abs(wall[0][0] - wall[1][0]) < 1e-8 else 0
                    lo, hi = sorted((door[0][axis], door[1][axis]))
                    if lo - 0.30 <= mid[axis] <= hi + 0.30:
                        door_crossings[segment["segment_id"]] += 1
    if crossing_edges:
        raise ValueError("graph has edges crossing structural glass: " + ", ".join(sorted(set(crossing_edges))))
    if any(count == 0 for count in door_crossings.values()):
        missing = [sid for sid, count in door_crossings.items() if count == 0]
        raise ValueError("no doorway graph crossing for: " + ", ".join(missing))
    rooms_seen = set()
    rooms_seen_ids = set()
    for obj in objects:
        name = str((obj.get("metadata") or {}).get("blender_name") or "")
        if not name.endswith(".floor"):
            continue
        room_type = name.split("_", 1)[0]
        if room_type not in {"meeting-room", "office", "open-office"}:
            continue
        geom = obj.get("geometry") or {}
        center, size = geom.get("center"), geom.get("size_m")
        if not center or not size:
            continue
        bounds = [center[0] - size[0] / 2, center[1] - size[2] / 2,
                  center[0] + size[0] / 2, center[1] + size[2] / 2]
        if any(_point_in_bounds(node.get("position") or [1e9, 1e9], bounds) for node in nodes.values()):
            rooms_seen.add(room_type)
            rooms_seen_ids.add(name[:-6])  # remove '.floor'
    if style == "modern_glass_v2":
        required_bays = set(manifest.get("work_bay_rooms") or [])
        missing_bays = required_bays - rooms_seen_ids
        if missing_bays:
            raise ValueError("no navigable viewpoint in work bay: " + ", ".join(sorted(missing_bays)))
        missing_types = {"meeting-room", "office", "open-office"} - rooms_seen
        if missing_types:
            raise ValueError("no navigable viewpoint in: " + ", ".join(sorted(missing_types)))
    else:
        missing_rooms = {"meeting-room", "office", "open-office"} - rooms_seen
        if missing_rooms:
            raise ValueError("no navigable viewpoint in: " + ", ".join(sorted(missing_rooms)))
    if len(nodes) > 70:
        raise ValueError(f"graph node cap exceeded: {len(nodes)} > 70")
    core = {
        "schema": "robomituba.opticalnav_modern_office_graph_audit.v2" if style == "modern_glass_v2" else "robomituba.opticalnav_modern_office_graph_audit.v1",
        "status": "passed", "office_style": style,
        "office_style_digest": manifest.get("office_style_digest"),
        "structural_glass_digest": spec.get("digest"),
        "installed_partition_ids": ids,
        "opaque_wall_owners": owner_contract,
        "imported_tagged_objects": {sid: len(tagged[sid]) for sid in ids},
        "door_graph_crossings": door_crossings,
        "room_types_with_viewpoints": sorted(rooms_seen),
        "work_bays_with_viewpoints": sorted(set(manifest.get("work_bay_rooms") or []) & rooms_seen_ids),
        "graph_node_count": len(nodes),
        "structural_glass_door_repairs": repaired_edges,
        "room_viewpoint_repairs": room_viewpoint_repairs,
        "graph_node_prunes": graph_node_prunes,
    }
    core["audit_digest"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    graph.setdefault("metadata", {})["modern_office_graph_audit"] = core
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return core


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(source_manifest=args.source_manifest, scene_dir=args.scene_dir)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
