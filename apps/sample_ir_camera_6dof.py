#!/usr/bin/env python3
"""Sample free 6-DoF camera poses around the scene's object anchors."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))

from mitsuba_converter.ir_camera_6dof import build_free_camera_poses  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--anchors", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--seed", type=int, default=20260812)
    parser.add_argument("--pose-budget", type=int, default=400)
    # 60 deg is what makes the 50-pose floor reachable in a small room: the
# bathroom yields 14/28/56/56 poses at 40/50/60/70 deg, while larger
# scenes barely move.  Framing stays constant across FOV because the
# sampler solves standoff for a fill target -- until the 1-2 m clamp
# binds, which is exactly what happens in a tight room at a narrow FOV.
    parser.add_argument("--fov", type=float, default=44.98)
    parser.add_argument("--width", type=int, default=684)
    parser.add_argument("--height", type=int, default=512)
    args = parser.parse_args()

    authoring = json.loads((args.scene_dir / "authoring_map.json").read_text(encoding="utf-8"))
    anchors = json.loads(args.anchors.read_text(encoding="utf-8"))
    payload = build_free_camera_poses(
        anchors.get("anchors") or [], authoring, scene_id=args.scene_id, seed=args.seed,
        pose_budget=args.pose_budget, fov_deg=args.fov, width=args.width, height=args.height)
    payload["anchor_digest"] = anchors.get("anchor_digest")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(f"[ir-camera-6dof] {payload['actual_pose_count']} poses "
          f"({payload['orbit_count']} orbits, {payload['tuple_count']} tuples) "
          f"over {payload['anchor_count']} anchors -> {args.out}")
    if payload["rejected"]:
        print(f"[ir-camera-6dof] rejected: {payload['rejected']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
