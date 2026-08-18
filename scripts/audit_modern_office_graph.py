#!/usr/bin/env python3
"""Validate a structural Modern Glass scene after OpticalNav graph build."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


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


def _authoring_line(points):
    # Blender floorplan uses +Y while authoring/import uses -Y.
    return [[float(points[0][0]), -float(points[0][1])], [float(points[1][0]), -float(points[1][1])]]


def _pane_segments(segment: dict):
    wall = _authoring_line(segment["wall_endpoints_m"])
    door = _authoring_line(segment["door_opening_m"])
    vertical = abs(wall[0][0] - wall[1][0]) < 1e-8
    axis = 1 if vertical else 0
    ordered = sorted(wall, key=lambda point: point[axis])
    opening = sorted(door, key=lambda point: point[axis])
    return [(ordered[0], opening[0]), (opening[1], ordered[1])]


def audit(*, source_manifest: Path, scene_dir: Path) -> dict:
    manifest = _read(source_manifest)
    spec = manifest.get("structural_glass") or {}
    if manifest.get("office_style") != "modern_glass_v1":
        raise ValueError("modern glass graph audit requires modern_glass_v1 source manifest")
    segments = spec.get("segments") or []
    requested = int(spec.get("requested_partition_count") or 0)
    if requested != 3 or len(segments) != requested or int(spec.get("eligible_segment_count") or 0) < requested:
        raise ValueError("invalid structural-glass partition contract")
    authoring = _read(scene_dir / "authoring_map.json")
    graph_path = scene_dir / "viewpoint_graph.json"
    graph = _read(graph_path)
    objects = authoring.get("objects") or []
    tagged: dict[str, list[dict]] = {}
    for obj in objects:
        meta = obj.get("metadata") or {}
        props = meta.get("source_custom_properties") or {}
        sid = props.get("office_wall_segment_id")
        if sid and props.get("transparent_partition") and obj.get("type") == "glass_wall":
            tagged.setdefault(str(sid), []).append(obj)
    ids = [segment["segment_id"] for segment in segments]
    missing_tags = [sid for sid in ids if not tagged.get(sid)]
    if missing_tags:
        raise ValueError("structural glass tags missing after import: " + ", ".join(missing_tags))
    nodes = {node["node_id"]: node for node in graph.get("nodes") or []}
    if not nodes:
        raise ValueError("viewpoint graph has no nodes")
    panes = [pane for segment in segments for pane in _pane_segments(segment)]
    crossing_edges, door_crossings = [], {sid: 0 for sid in ids}
    for edge in graph.get("edges") or []:
        polyline = edge.get("path_polyline") or []
        for a, b in zip(polyline, polyline[1:]):
            for pane in panes:
                if _segments_intersect(a, b, pane[0], pane[1]):
                    crossing_edges.append(edge.get("edge_id"))
            for segment in segments:
                wall = _authoring_line(segment["wall_endpoints_m"])
                door = _authoring_line(segment["door_opening_m"])
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
    missing_rooms = {"meeting-room", "office", "open-office"} - rooms_seen
    if missing_rooms:
        raise ValueError("no navigable viewpoint in: " + ", ".join(sorted(missing_rooms)))
    if len(nodes) > 70:
        raise ValueError(f"graph node cap exceeded: {len(nodes)} > 70")
    core = {
        "schema": "robomituba.opticalnav_modern_office_graph_audit.v1",
        "status": "passed", "office_style": "modern_glass_v1",
        "office_style_digest": manifest.get("office_style_digest"),
        "structural_glass_digest": spec.get("digest"),
        "installed_partition_ids": ids,
        "imported_tagged_objects": {sid: len(tagged[sid]) for sid in ids},
        "door_graph_crossings": door_crossings,
        "room_types_with_viewpoints": sorted(rooms_seen),
        "graph_node_count": len(nodes),
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
