from __future__ import annotations

import argparse
from pathlib import Path

from apps.isaac_standalone._bootstrap import bootstrap_repo_paths

REPO_ROOT = bootstrap_repo_paths()

from apps.isaac_standalone._stage_bridge import export_stage_to_usda, extract_snapshot, load_stage
from robomituba_bridge import create_job_manifest, ensure_job_layout, make_job_id, to_repo_relative_posix, write_job_bundle, write_shape_mapping, build_shape_mapping
from robomituba_bridge.types import SceneSnapshot


def create_job_bundle(
    snapshot: SceneSnapshot,
    *,
    repo_root: Path,
    job_id: str,
) -> Path:
    layout = ensure_job_layout(repo_root, job_id)
    manifest = create_job_manifest(repo_root, layout, snapshot)
    write_job_bundle(layout, manifest, snapshot)
    return layout.manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a bridge job from the current Isaac stage or a USD file.")
    parser.add_argument("--scene-id", default="isaac_scene")
    parser.add_argument("--frame-id", default="frame_0000")
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--usd", default=None, help="Optional USD file to open instead of the current Isaac stage.")
    parser.add_argument("--mitsuba-scene", default=None, help="Optional Mitsuba base scene.xml used to build explicit prim↔shape mapping.")
    args = parser.parse_args()

    stage, _ = load_stage(usd_path=args.usd)
    job_id = args.job_id or make_job_id("isaac")
    layout = ensure_job_layout(REPO_ROOT, job_id)
    export_stage_to_usda(stage, layout.usd_stage)

    snapshot = extract_snapshot(
        stage,
        scene_id=args.scene_id,
        frame_id=args.frame_id,
        timestamp=args.timestamp,
        usd_stage_path=to_repo_relative_posix(REPO_ROOT, layout.usd_stage),
        source_usd_path=layout.usd_stage,
    )
    manifest_path = create_job_bundle(snapshot, repo_root=REPO_ROOT, job_id=job_id)
    if args.mitsuba_scene:
        scene_xml = Path(args.mitsuba_scene).resolve()
        shape_map_path = layout.snapshot_dir / "shape_map.json"
        write_shape_mapping(
            shape_map_path,
            mapping_payload=build_shape_mapping(snapshot, scene_xml),
            repo_root=REPO_ROOT,
            scene_xml_ref=to_repo_relative_posix(REPO_ROOT, scene_xml),
            scene_snapshot_ref=to_repo_relative_posix(REPO_ROOT, layout.scene_snapshot),
        )
    print(f"Wrote bridge job: {manifest_path}")


if __name__ == "__main__":
    main()
