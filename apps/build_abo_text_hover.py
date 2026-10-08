#!/usr/bin/env python3
"""Hover takes that keep a piece of writing in shot for the whole move.

The object-hover planner aims at a bounding-box centre and sweeps every azimuth
for the first that clears the room. Both are wrong for text. The writing sits
off-centre on one face, so a bbox-centre aim puts it near the frame edge and
out of it entirely at close range; and any side of an object is a fine view of
the object while only one side is a view of its label. Measured on the screen:
the camera's incidence angle cannot tell the two apart, because a camera square
on the BACK of a clock is square on.

So this feeds the existing plan_arc three things it already understands:
  centre   the text anchor, not the bbox centre, so elevation banding, the
           occlusion gate and the handheld wander all key on the writing
  facings  the text normal's azimuth and a few degrees either side, instead of
           a sweep of all of them
  radius   the distance at which the letters span the requested pixel height

Everything else -- pacing, roll, clearance trends, the all-or-nothing occlusion
rule -- is the hover planner's and is deliberately not reimplemented here.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from abo_text_anchor import anchor  # noqa: E402
from build_abo_hover_trajectory import join_boxes, plan_arc  # noqa: E402

YUP_TO_ZUP = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)


def distance_for_px(text_h_m: float, px: float, hfov_deg: float,
                    width: int, height: int) -> float:
    vfov = 2 * math.atan(math.tan(math.radians(hfov_deg) / 2) * height / width)
    return text_h_m / (2 * math.tan((px * vfov / height) / 2))


def text_pose_basis(instance: dict, target: dict, box: dict, scene_bounds):
    """World-space aim point, outward normal and surface standoff for one target."""
    M = np.asarray(instance["blender_matrix"], float)
    lo_l, hi_l = scene_bounds
    predicted = M[:3, :3] @ (YUP_TO_ZUP @ ((lo_l + hi_l) / 2)) + M[:3, 3]
    # build and prepare settle an object onto whatever it stands on, by up to
    # 0.3 m, after the composer wrote the matrix. Without this the aim is the
    # pre-settle position and the camera frames the air above the label.
    delta = np.asarray(box["centre"], float) - predicted
    aim = M[:3, :3] @ (YUP_TO_ZUP @ np.asarray(target["aim"], float)) + M[:3, 3] + delta
    n = M[:3, :3] @ (YUP_TO_ZUP @ np.asarray(target["normal"], float))
    n = n / max(np.linalg.norm(n), 1e-9)
    lo, hi, centre = (np.asarray(box[k], float) for k in ("lo", "hi", "centre"))
    # Mesh winding does not reliably say which way is out, so the measured box
    # decides: 17 of 57 human-kept frames had the raw normal pointing inward.
    if float(np.dot(n, aim - centre)) < 0:
        n = -n
    ts = [float((bound - aim[a]) / n[a]) for a in range(3) if abs(n[a]) > 1e-9
          for bound in (lo[a], hi[a]) if (bound - aim[a]) / n[a] > 0]
    standoff = (min(ts) if ts else 0.0) + 0.02
    return aim, n, standoff


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", type=Path, required=True)
    ap.add_argument("--bboxes", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True,
                    help="configs/abo_text_targets.json; excluded ids are skipped")
    ap.add_argument("--anchors", type=Path, required=True,
                    help="per-id aim/normal in object space (text_props/text_flat)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--target-px", type=float, default=38.0)
    ap.add_argument("--azimuth-span-deg", type=float, default=50.0,
                    help="how far the arc travels AROUND the text normal. The "
                         "object planner uses 120; a label leaves the frame "
                         "well before that")
    ap.add_argument("--facing-window-deg", type=float, default=25.0)
    ap.add_argument("--facing-steps", type=int, default=7)
    ap.add_argument("--takes-per-target", type=int, default=1,
                    help="how many DIFFERENT arcs to shoot of the same writing. "
                         "Take length is unchanged; this multiplies takes without "
                         "needing more scenes. Each one takes a facing at least "
                         "--take-separation-deg from the ones already used, so "
                         "they are different views rather than the same shot "
                         "re-seeded.")
    ap.add_argument("--take-separation-deg", type=float, default=12.0)
    ap.add_argument("--emit-from", type=int, default=0,
                    help="skip the first N takes of each target in the OUTPUT while "
                         "still planning them. A later round uses this to add views "
                         "without re-emitting the ones already rendered: the skipped "
                         "takes still consume their facings, so what is emitted is "
                         "separated from what exists rather than overlapping it.")
    ap.add_argument("--elevation-deg", type=float, default=12.0)
    ap.add_argument("--handheld-deg", type=float, default=4.0)
    ap.add_argument("--hfov-deg", type=float, default=44.98)
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--height", type=int, default=540)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    import trimesh
    manifest = json.loads((args.scene / "scene_manifest.json").read_text(encoding="utf-8"))
    measured = json.loads(args.bboxes.read_text(encoding="utf-8"))
    measured = measured if isinstance(measured, list) else measured.get("instances", measured.get("boxes", []))
    joined = join_boxes(measured, manifest["instances"])
    by_src = {b["source_id"]: b for b in joined if b.get("source_id")}
    registry = json.loads(args.targets.read_text(encoding="utf-8"))
    excluded = set(registry.get("excluded") or {})
    anchors = {}
    for row in json.loads(args.anchors.read_text(encoding="utf-8")):
        anchors[row["id"]] = row

    room = {"width_m": None, "depth_m": None, "height_m": None}
    stage = next((b for b in measured if b.get("name") == "floor"), None)
    ceil = next((b for b in measured if b.get("name") == "ceiling"), None)
    if stage:
        room["width_m"] = stage["size"][0]; room["depth_m"] = stage["size"][1]
    room["height_m"] = ceil["lo"][2] if ceil else 2.4

    poses, takes = [], []
    blockers = [b for b in joined]
    for inst in manifest["instances"]:
        sid = inst.get("source_id")
        if sid not in anchors or sid in excluded or sid not in by_src:
            continue
        tgt, box = anchors[sid], by_src[sid]
        try:
            sc = trimesh.load(inst["source_glb"], force="scene", process=False)
        except Exception:
            continue
        aim, n, standoff = text_pose_basis(inst, tgt, box,
                                           (np.asarray(sc.bounds[0]), np.asarray(sc.bounds[1])))
        radius = max(distance_for_px(tgt["text_h_m"], args.target_px,
                                     args.hfov_deg, args.width, args.height), standoff)
        if radius > 6.0:
            continue
        base = math.atan2(n[1], n[0])
        half = math.radians(args.facing_window_deg)
        facings = [base + half * (2 * i / max(1, args.facing_steps - 1) - 1)
                   for i in range(args.facing_steps)]
        # offer the normal itself first, then outward in both directions
        facings.sort(key=lambda f: abs(f - base))
        pseudo = {**box, "centre": [float(x) for x in aim]}
        used_facings: list[float] = []
        sep = math.radians(args.take_separation_deg)
        for take_i in range(max(1, args.takes_per_target)):
            offer = [f for f in facings
                     if all(abs(f - u) >= sep for u in used_facings)]
            if not offer:
                break
            # A second take of the same writing is only worth a frame if it is a
            # different VIEW of it. Re-seeding alone moves the hand, not the
            # camera, so the facing has to move too -- hence the separation gate
            # above rather than just a fresh seed.
            plan = plan_arc([pseudo], [b for b in blockers if b is not box], room,
                            frames=args.frames, radius=float(radius),
                            azimuth_span_deg=args.azimuth_span_deg,
                            elevation_deg=args.elevation_deg, facing_candidates=1,
                            handheld_deg=args.handheld_deg, shape="quartic",
                            seed=args.seed + 7919 * take_i + len(takes),
                            handoff_window=0.0, facings=offer)
            if plan is None:
                break
            used_facings.append(float(plan["facing_rad"]))
            if take_i < args.emit_from:
                continue          # planned, so its facing is reserved; not written
            start = len(poses)
            for pos, a in zip(plan["positions"], plan["aims"]):
                poses.append({"position": [round(float(x), 5) for x in pos],
                              "target": [round(float(x), 5) for x in a],
                              "pose_qc": {"source": "text_hover"}, "coverage": {},
                              "sequence_id": f"{sid}#{take_i}" if take_i else sid,
                              "text_gt": tgt["text"],
                              "text_normal": [round(float(x), 5) for x in n],
                              "target_source_id": sid,
                              "target_distance_m": round(float(radius), 4)})
            takes.append({"source_id": sid, "take_index": take_i, "text": tgt["text"],
                          "text_h_m": tgt["text_h_m"], "frames": args.frames,
                          "radius_m": round(float(radius), 4),
                          "facing_rad": round(float(plan["facing_rad"]), 5),
                          "facings_rejected": plan["facings_rejected"],
                          "pose_from": start, "pose_to": len(poses) - 1,
                          "max_turn_deg": round(max(plan["turn_angles_deg"]), 3)
                          if plan["turn_angles_deg"] else 0.0,
                          "wall_clearance_m": plan["wall_clearance_m"],
                          "object_clearance_m": plan["object_clearance_m"]})
    args.out.write_text(json.dumps(
        {"all": poses, "important": [],
         "hover": {"schema": "abo_text_hover_v1", "trajectories": takes}},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[text-hover] {args.scene.name}: {len(takes)} takes x {args.frames} frames "
          f"= {len(poses)} poses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
