from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from navigation_dataset.office_sample import (  # noqa: E402
    DEFAULT_PROJECT_ID,
    DEFAULT_SHARED_OFFICE_SCENE_ID,
    install_shared_office_sample,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the shared-office v1 sample map into out/opticalnav.")
    parser.add_argument("--project", default=DEFAULT_PROJECT_ID, help=f"OpticalNav project id (default: {DEFAULT_PROJECT_ID})")
    parser.add_argument("--scene", default=DEFAULT_SHARED_OFFICE_SCENE_ID, help=f"Scene id (default: {DEFAULT_SHARED_OFFICE_SCENE_ID})")
    parser.add_argument("--fixture", default=None, help="Optional authoring_map fixture path.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing sample scene artifacts.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable install result.")
    args = parser.parse_args()

    result = install_shared_office_sample(
        REPO_ROOT,
        project_id=args.project,
        scene_id=args.scene,
        fixture_path=args.fixture,
        force=args.force,
    )
    payload = result.to_payload(repo_root=REPO_ROOT)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"Installed shared office sample: {payload['scene_dir']}")
    print(f"  objects: {result.compile_summary.get('object_count')}")
    print(f"  transparent surfaces: {result.compile_summary.get('transparent_surface_count')}")
    print(f"  reflective hazards: {result.compile_summary.get('reflective_hazard_count')}")
    print(f"  goals: {result.compile_summary.get('goal_region_count')}")
    if result.asset_gap_categories:
        print(f"  placeholder asset gaps: {', '.join(result.asset_gap_categories)}")
    if result.external_needed_categories:
        print(f"  external-needed coverage: {', '.join(result.external_needed_categories)}")
    print("  next: open the scene in the dataset editor, then Save Map / Sync Render Scene to generate render_scene.xml")


if __name__ == "__main__":
    main()
