from __future__ import annotations

import argparse
from pathlib import Path

from apps.isaac_standalone._bootstrap import bootstrap_repo_paths

REPO_ROOT = bootstrap_repo_paths()

from apps.isaac_standalone._stage_bridge import export_stage_to_usda, extract_snapshot, load_stage, write_snapshot_directory
from robomituba_bridge.paths import to_repo_relative_posix


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a scene snapshot from the current Isaac stage or a USD file.")
    parser.add_argument("--scene-id", default="isaac_scene")
    parser.add_argument("--frame-id", default="frame_0000")
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--usd", default=None, help="Optional USD file to open instead of the current Isaac stage.")
    parser.add_argument("--usd-out", default=None, help="Optional output path for an exported USDA file.")
    parser.add_argument("--mitsuba-scene", default=None, help="Optional Mitsuba base scene.xml used to build explicit prim↔shape mapping.")
    args = parser.parse_args()

    stage, source_usd_path = load_stage(usd_path=args.usd)
    snapshot_dir = Path(args.snapshot_dir)

    usd_stage_rel = None
    if args.usd_out:
        usd_out = Path(args.usd_out)
        export_stage_to_usda(stage, usd_out)
        usd_stage_rel = to_repo_relative_posix(REPO_ROOT, usd_out.resolve())

    snapshot = extract_snapshot(
        stage,
        scene_id=args.scene_id,
        frame_id=args.frame_id,
        timestamp=args.timestamp,
        usd_stage_path=usd_stage_rel,
        source_usd_path=Path(args.usd_out).resolve() if args.usd_out else source_usd_path,
    )
    write_snapshot_directory(
        snapshot,
        snapshot_dir,
        scene_xml_path=Path(args.mitsuba_scene).resolve() if args.mitsuba_scene else None,
        repo_root=REPO_ROOT,
    )
    print(f"Wrote snapshot directory: {snapshot_dir}")


if __name__ == "__main__":
    main()
