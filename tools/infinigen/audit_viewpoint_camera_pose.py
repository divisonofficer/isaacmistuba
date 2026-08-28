#!/usr/bin/env python3
"""Audit every viewpoint-graph camera pose without opening Blender or Mitsuba.

The graph is an authoring XZ floor frame.  This tool resolves all headings via
the shared canonical pose contract and checks the Blender Z-up conversion,
height, pitch, and optional scene-manifest bounds.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
src = REPO / "modules" / "robomituba_bridge" / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))
from robomituba_bridge.camera_pose import AXIS_TRANSFORM_ID, resolve_viewpoint_pose  # noqa: E402


def _bounds_from_manifest(path: Path) -> tuple[float, float, float, float] | None:
    """Native Blender-world X/Y bounds from the Stage 1 manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    mins: list[tuple[float, float]] = []
    maxs: list[tuple[float, float]] = []
    for unit in payload.get("units", []):
        lo = unit.get("world_bbox_min")
        hi = unit.get("world_bbox_max")
        if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) >= 2 and len(hi) >= 2):
            continue
        mins.append((float(lo[0]), float(lo[1])))
        maxs.append((float(hi[0]), float(hi[1])))
    if not mins:
        return None
    return (min(x for x, _ in mins), min(y for _, y in mins),
            max(x for x, _ in maxs), max(y for _, y in maxs))


def _origin_offset(scene_graph: Path, authoring_map: Path | None) -> tuple[float, float, float]:
    path = authoring_map or (scene_graph.parent / "authoring_map.json")
    if not path.is_file():
        return (0.0, 0.0, 0.0)
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = (payload.get("metadata") or {}).get("origin_offset")
    if not isinstance(raw, (list, tuple)) or len(raw) not in (2, 3):
        return (0.0, 0.0, 0.0)
    values = tuple(float(v) for v in raw)
    return (values[0], values[1], values[2] if len(values) == 3 else 0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-graph", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scene-manifest", type=Path)
    ap.add_argument("--authoring-map", type=Path, help="defaults to sibling authoring_map.json")
    ap.add_argument("--eye-height", type=float, default=1.2)
    ap.add_argument("--target-height", type=float, default=None)
    ap.add_argument("--pitch-limit-deg", type=float, default=15.0)
    ap.add_argument("--bounds-margin-m", type=float, default=0.25)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    graph = json.loads(args.scene_graph.read_text(encoding="utf-8"))
    origin_offset = _origin_offset(args.scene_graph, args.authoring_map)
    bounds = _bounds_from_manifest(args.scene_manifest) if args.scene_manifest else None
    rows = []
    errors = []
    outside = []
    wrong_height = []
    steep = []
    for node in graph.get("nodes", []):
        position = node.get("position") or []
        for heading in node.get("headings") or [{"heading_id": "h_000", "yaw_deg": 0.0}]:
            node_id = str(node.get("node_id") or "")
            heading_id = str(heading.get("heading_id") or "")
            try:
                pose = resolve_viewpoint_pose(
                    position,
                    float(heading.get("yaw_deg", 0.0)),
                    eye_height_m=args.eye_height,
                    target_height_m=args.target_height,
                    origin_offset=origin_offset,
                )
                dx = pose.target_mitsuba[0] - pose.origin_mitsuba[0]
                dz = pose.target_mitsuba[2] - pose.origin_mitsuba[2]
                dy = pose.target_mitsuba[1] - pose.origin_mitsuba[1]
                pitch = math.degrees(math.atan2(abs(dy), max(math.hypot(dx, dz), 1e-12)))
                bpos = pose.origin_blender
                row = {
                    "node_id": node_id, "heading_id": heading_id,
                    "yaw_deg": pose.yaw_deg,
                    "origin_mitsuba": list(pose.origin_mitsuba),
                    "origin_blender": list(pose.origin_blender),
                    "target_mitsuba": list(pose.target_mitsuba),
                    "target_blender": list(pose.target_blender),
                    "pitch_deg": pitch,
                    "axis_transform": pose.axis_transform,
                }
                rows.append(row)
                if abs(bpos[2] - (args.eye_height - origin_offset[2])) > 1e-6:
                    wrong_height.append(f"{node_id}/{heading_id}")
                if pitch > args.pitch_limit_deg:
                    steep.append(f"{node_id}/{heading_id}")
                if bounds is not None:
                    x0, y0, x1, y1 = bounds
                    m = float(args.bounds_margin_m)
                    if not (x0 - m <= bpos[0] <= x1 + m and y0 - m <= bpos[1] <= y1 + m):
                        outside.append(f"{node_id}/{heading_id}")
            except Exception as exc:  # noqa: BLE001
                errors.append({"node_id": node_id, "heading_id": heading_id, "error": str(exc)})

    report = {
        "schema": "robomituba.camera_pose_audit.v1",
        "scene_graph": str(args.scene_graph),
        "scene_manifest": str(args.scene_manifest) if args.scene_manifest else None,
        "authoring_origin_offset": list(origin_offset),
        "axis_transform": AXIS_TRANSFORM_ID,
        "eye_height_m": args.eye_height,
        "target_height_m": args.target_height if args.target_height is not None else args.eye_height * 0.9,
        "pitch_limit_deg": args.pitch_limit_deg,
        "bounds_blender_xy": list(bounds) if bounds is not None else None,
        "counts": {
            "nodes": len(graph.get("nodes", [])),
            "resolved": len(rows),
            "errors": len(errors),
            "outside_bounds": len(outside),
            "wrong_height": len(wrong_height),
            "steep_pitch": len(steep),
        },
        "status": "ok" if not errors and not outside and not wrong_height and not steep else "degraded",
        "errors": errors,
        "outside_bounds": outside[:100],
        "wrong_height": wrong_height[:100],
        "steep_pitch": steep[:100],
        "samples": rows[:3] + (rows[-3:] if len(rows) > 3 else []),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    if args.strict and report["status"] != "ok":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
