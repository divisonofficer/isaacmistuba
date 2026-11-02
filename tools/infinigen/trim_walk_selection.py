#!/usr/bin/env python3
"""Cut walk takes that end inside a wall, before anything is rendered.

Measured on infinigen_apartment_natural_v1_20261104: of 11 frames failing the
pose_gates depth thresholds across five takes, TEN were in the final five frames
of their take, with depth falling monotonically into the surface --

    take 0   27/29 0.71 m   28/29 0.57 m   29/29 0.42 m (98% near)
    take 3   21/25 0.79 -> 22 0.70 -> 23 0.58 -> 24 0.47 -> 25 0.36 (100% near)

That is not a camera glancing at a wall, it is a path whose END POINT is inside
one. So this trims tails rather than filtering frames: a per-frame filter leaves
the take ending one frame short of the wall, which is the same shot without the
punchline.

It runs on the selection, not on renders. `blender_render_hssd_ir_sample.py`
writes pose_selection.json before it renders anything and accepts one back via
--pose-selection-file, so the frames this drops are never drawn. The gate itself
is `hssd_blender_ir.pose_gates` -- the same thresholds coverage and object_closeup
are held to -- rather than numbers invented here.

Usage (inside Blender):
  blender --background <scene.blend> --python trim_walk_selection.py -- \
      --selection <pose_selection.json> --out <trimmed.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "modules/hssd_blender_ir/src"))
from hssd_blender_ir import pose_gates  # noqa: E402

#: The renderer samples a 5x3 grid across the frame for its own content checks;
#: the same grid here means a pose judged clear now is judged clear then.
GRID_X, GRID_Y = 5, 3
MAX_RAY_M = 30.0


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selection", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-take-frames", type=int, default=8,
                    help="a take trimmed below this is dropped rather than shipped short")
    ap.add_argument("--hfov-deg", type=float, default=None)
    return ap.parse_args(argv)


def _camera(position, target, hfov_deg):
    cam = bpy.data.objects.get("__trim_probe")
    if cam is None:
        cam = bpy.data.objects.new("__trim_probe", bpy.data.cameras.new("__trim_probe"))
        bpy.context.scene.collection.objects.link(cam)
    cam.data.sensor_fit = "HORIZONTAL"
    if hfov_deg:
        import math
        cam.data.lens = (cam.data.sensor_width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    cam.location = Vector(position)
    direction = (Vector(target) - Vector(position))
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()      # matrix_world is stale until this runs
    return cam


def depth_summary(position, target, hfov_deg) -> dict:
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    camera = _camera(position, target, hfov_deg)
    frame = camera.data.view_frame(scene=scene)
    distances = []
    for iy in range(GRID_Y):
        v = (iy + 0.5) / GRID_Y
        for ix in range(GRID_X):
            u = (ix + 0.5) / GRID_X
            local = frame[0].lerp(frame[1], u).lerp(frame[3].lerp(frame[2], u), v)
            ray = (camera.matrix_world.to_3x3() @ local).normalized()
            hit = scene.ray_cast(depsgraph, camera.location, ray, distance=MAX_RAY_M)
            if hit[0]:
                distances.append((hit[1] - camera.location).length)
    return pose_gates.frame_depth_summary(distances)


def fails(summary: dict) -> bool:
    return (summary["median_distance_m"] < pose_gates.MIN_MEDIAN_DISTANCE_M
            or summary["near_fraction"] > pose_gates.MAX_NEAR_FRACTION)


def main() -> int:
    args = _args()
    payload = json.loads(args.selection.read_text(encoding="utf-8"))
    poses = payload.get("all") or []

    takes: dict = {}
    for index, pose in enumerate(poses):
        takes.setdefault(pose.get("sequence_id"), []).append(index)

    keep, report = set(), []
    for sequence, indices in takes.items():
        summaries = [depth_summary(poses[i]["position"], poses[i]["target"], args.hfov_deg)
                     for i in indices]
        end = len(indices)
        while end > 0 and fails(summaries[end - 1]):
            end -= 1
        trimmed = indices[:end]
        mid = [p for p, i in enumerate(trimmed) if fails(summaries[p])]
        # A mid-path failure is rare (2 of 188 measured) and is a real per-frame
        # reject; the tail is a path problem and was already cut above.
        trimmed = [i for p, i in enumerate(trimmed) if p not in set(mid)]
        dropped = len(indices) - len(trimmed)
        if len(trimmed) < args.min_take_frames:
            report.append({"take": sequence, "frames": len(indices), "kept": 0,
                           "why": f"only {len(trimmed)} frames survived the gate"})
            continue
        keep.update(trimmed)
        report.append({"take": sequence, "frames": len(indices), "kept": len(trimmed),
                       "tail_cut": len(indices) - end, "mid_cut": len(mid)})

    payload["all"] = [p for i, p in enumerate(poses) if i in keep]
    payload["trimmed_by"] = {
        "tool": "trim_walk_selection.py",
        "thresholds": {"min_median_distance_m": pose_gates.MIN_MEDIAN_DISTANCE_M,
                       "max_near_fraction": pose_gates.MAX_NEAR_FRACTION,
                       "near_distance_m": pose_gates.NEAR_DISTANCE_M},
        "takes": report,
        "poses_before": len(poses), "poses_after": len(payload["all"])}
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("TRIMMED " + json.dumps({k: v for k, v in payload["trimmed_by"].items() if k != "takes"}))
    for row in report:
        print("  " + json.dumps(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
