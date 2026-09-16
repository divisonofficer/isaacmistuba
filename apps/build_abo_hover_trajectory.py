"""Camera paths that hover around one ABO object, for video inverse rendering.

The Cornell-box placement is this file's; the angle arithmetic is not. That
lives in hssd_blender_ir.hover_path, written for the HSSD hover mode, and is
imported rather than reimplemented -- the two corpora disagree about what a
room is, and agree exactly about what a sphere is.

What this does NOT share with the HSSD mode is target selection. That one
picks interior assets out of a furnished room and runs an interior preflight;
here a single ABO product sits in a five-metre box, and the questions are
different ones: which object is not buried inside another, and where can the
camera stand without a table between it and the object.

Aim point: the object's measured bounding-box centre, never its origin. ABO
GLB origins sit on the object's base, which is the host table's surface -- a
camera aimed there frames the tabletop and clips the object's head off. At
1 m radius the frame is 0.83 x 0.62 m, so an origin 0.23 m below the centre
is 37% of the frame height of error, which is what it looked like.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "hssd_blender_ir" / "src"))
from hssd_blender_ir import hover_path  # noqa: E402

SCHEMA = "abo_hover_trajectory/2"

RADIUS_M = 1.0
AZIMUTH_SPAN_DEG = 60.0     # the total sweep, -30..+30, as the HSSD mode names it
ELEVATION_DEG = 55.0
WALL_CLEARANCE_M = 0.25
FLOOR_CLEARANCE_M = 0.30
CEILING_CLEARANCE_M = 0.30
# Above this, two props are sharing a position rather than merely touching,
# and neither is a sensible thing to point a camera at and call identifiable.
BURIAL_FRACTION = 0.50


def _aabb_overlap_fraction(a: dict, b: dict) -> float:
    """Intersection volume over the smaller box. A screen, not a proof: a
    concave host (a table) has a bounding box full of the air its props sit in,
    so a prop on a table scores high against it without touching it. Only
    applied between props of comparable size, where that excuse does not hold.
    """
    inter = 1.0
    for axis in range(3):
        span = min(a["hi"][axis], b["hi"][axis]) - max(a["lo"][axis], b["lo"][axis])
        if span <= 0.0:
            return 0.0
        inter *= span
    volumes = [max(1e-9, box["size"][0] * box["size"][1] * box["size"][2]) for box in (a, b)]
    return inter / min(volumes)


def _segment_hits_box(origin, end, box) -> bool:
    """Slab test: does the camera-to-object segment pass through this box."""
    near, far = 0.0, 1.0
    for axis in range(3):
        direction = end[axis] - origin[axis]
        lo, hi = box["lo"][axis], box["hi"][axis]
        if abs(direction) < 1e-9:
            if origin[axis] < lo or origin[axis] > hi:
                return False
            continue
        t0 = (lo - origin[axis]) / direction
        t1 = (hi - origin[axis]) / direction
        if t0 > t1:
            t0, t1 = t1, t0
        near, far = max(near, t0), min(far, t1)
        if near > far:
            return False
    return True


def _inside_room(position, room) -> bool:
    half_width = room["width_m"] / 2.0 - WALL_CLEARANCE_M
    half_depth = room["depth_m"] / 2.0 - WALL_CLEARANCE_M
    return (abs(position[0]) <= half_width and abs(position[1]) <= half_depth
            and FLOOR_CLEARANCE_M <= position[2] <= room["height_m"] - CEILING_CLEARANCE_M)


def plan_arc(target: dict, blockers: list[dict], room: dict, *, frames: int,
             radius: float, azimuth_span_deg: float, elevation_deg: float,
             facing_candidates: int) -> dict[str, Any] | None:
    """One unobstructed arc around `target`, or None if no facing gives one.

    All or nothing, deliberately. A blocked sample dropped from the middle of
    an arc leaves a video with a hole in it, which is worse than a scene that
    reports it could not be shot.
    """
    centroid = target["centre"]
    band = (FLOOR_CLEARANCE_M, room["height_m"] - CEILING_CLEARANCE_M)
    lowest, highest = hover_path.elevation_band_deg(centroid[2], radius, band=band,
                                                    requested=elevation_deg)
    samples = hover_path.arc(frames, azimuth_span_deg, lowest, highest)

    rejected = 0
    for index in range(facing_candidates):
        facing = 2.0 * math.pi * index / facing_candidates
        positions = [hover_path.camera_position(centroid, radius, facing,
                                                s["azimuth_deg"], s["elevation_deg"])
                     for s in samples]
        if not all(_inside_room(p, room) for p in positions):
            rejected += 1
            continue
        if any(_segment_hits_box(p, centroid, box) for p in positions for box in blockers):
            rejected += 1
            continue
        return {"facing_rad": facing, "samples": samples, "positions": positions,
                "elevation_from_deg": lowest, "elevation_to_deg": highest,
                "facings_rejected": rejected,
                "angular_steps_deg": hover_path.angular_steps_deg(samples)}
    return None


def choose_targets(boxes: list[dict], instances: list[dict], count: int) -> list[dict]:
    """Props that are neither hosts, luminaires, nor buried in another prop."""
    for box, instance in zip(boxes, instances):
        box["source_id"] = instance.get("source_id")
        box["instance_id"] = instance.get("instance_id")
        box["role"] = instance.get("abo_role")
    props = [b for b in boxes if b.get("role") == "prop"]
    out = []
    for box in sorted(props, key=lambda b: -max(b["size"])):
        buried = max((_aabb_overlap_fraction(box, other) for other in props
                      if other is not box
                      and 0.5 <= max(other["size"]) / max(box["size"]) <= 2.0),
                     default=0.0)
        box["burial_fraction"] = buried
        if buried <= BURIAL_FRACTION:
            out.append(box)
        if len(out) >= count:
            break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", type=Path, required=True,
                        help="composed scene directory holding scene_manifest.json")
    parser.add_argument("--bboxes", type=Path, required=True,
                        help="measured world bounding boxes (apps/dump_abo_scene_bboxes.py)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=20, help="frames per trajectory")
    parser.add_argument("--radius", type=float, default=RADIUS_M)
    parser.add_argument("--azimuth-span-deg", type=float, default=AZIMUTH_SPAN_DEG,
                        help="the TOTAL sweep, as the HSSD hover mode names it")
    parser.add_argument("--elevation-deg", type=float, default=ELEVATION_DEG)
    parser.add_argument("--targets", type=int, default=1)
    parser.add_argument("--facing-candidates", type=int, default=36)
    args = parser.parse_args()

    manifest = json.loads((args.scene / "scene_manifest.json").read_text(encoding="utf-8"))
    room = manifest["room"]
    instances = manifest["instances"]
    measured = json.loads(args.bboxes.read_text(encoding="utf-8"))
    boxes = [b for b in measured if b["name"].startswith("RootNode")]
    if len(boxes) != len(instances):
        parser.error(f"{len(boxes)} measured boxes vs {len(instances)} instances: "
                     "the dump is from a different scene")

    targets = choose_targets(boxes, instances, args.targets)
    if not targets:
        parser.error("every prop in this scene is buried inside another one")

    poses, summaries = [], []
    for target in targets:
        plan = plan_arc(target, [b for b in boxes if b is not target], room,
                        frames=args.frames, radius=args.radius,
                        azimuth_span_deg=args.azimuth_span_deg,
                        elevation_deg=args.elevation_deg,
                        facing_candidates=args.facing_candidates)
        if plan is None:
            print(f"[hover] {target['source_id']}: no unobstructed facing, skipped")
            continue
        for order, (sample, position) in enumerate(zip(plan["samples"], plan["positions"])):
            poses.append({
                "position": list(position),
                "target": list(target["centre"]),
                "pose_mode": "hover_trajectory",
                "trajectory_order": order,
                "trajectory_segment": sample["segment"],
                "hover_azimuth_deg": sample["azimuth_deg"],
                "hover_elevation_deg": sample["elevation_deg"],
                "target_distance_m": args.radius,
                "target_source_id": target["source_id"],
                "target_instance_id": target["instance_id"],
                "specular_score": 0.0, "base_score": 0.0,
                "coverage": {}, "pose_qc": {}, "specular": {},
            })
        steps = plan["angular_steps_deg"]
        summaries.append({
            "source_id": target["source_id"], "instance_id": target["instance_id"],
            "target": target["centre"], "size_m": target["size"],
            "burial_fraction": round(target["burial_fraction"], 4),
            "radius_m": args.radius, "facing_rad": plan["facing_rad"],
            "facings_rejected": plan["facings_rejected"],
            "elevation_requested_deg": args.elevation_deg,
            "elevation_from_deg": plan["elevation_from_deg"],
            "elevation_to_deg": plan["elevation_to_deg"],
            "frames": args.frames,
            "sweep_frames": sum(1 for s in plan["samples"] if s["segment"] == "azimuth"),
            "angular_step_deg": [round(min(steps), 3), round(max(steps), 3)],
        })

    if not poses:
        print("[hover] nothing shootable in this scene")
        return 1

    # An empty `important` list renders the baseline lighting only: a video
    # wants one lighting condition from its first frame to its last.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"all": poses, "important": [],
                                    "hover": {"schema": SCHEMA, "trajectories": summaries}},
                                   indent=2), encoding="utf-8")
    print(f"[hover] {len(summaries)} trajectories, {len(poses)} poses -> {args.out}")
    for s in summaries:
        print(f"    {s['source_id']}  centre z={s['target'][2]:.2f}  size={s['size_m']}")
        print(f"      elevation {s['elevation_from_deg']:.1f}..{s['elevation_to_deg']:.1f}deg"
              f" (asked {s['elevation_requested_deg']:.0f})   sweep {s['sweep_frames']}"
              f"/{s['frames']} frames   step {s['angular_step_deg'][0]}-{s['angular_step_deg'][1]}deg")
        print(f"      facings rejected before one cleared: {s['facings_rejected']}"
              f"   burial {s['burial_fraction']*100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
