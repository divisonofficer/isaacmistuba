from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
for module_path in (
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from mitsuba_converter import render_timestep_bundle_split_lighting
from robomituba_bridge import render_request_from_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a saved RenderRequest JSON with ambient/active/polar lighting branches.",
    )
    parser.add_argument("request_json", type=Path, help="Path to a saved RenderRequest JSON payload.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root used to resolve repo-relative scene refs.",
    )
    parser.add_argument(
        "--variant",
        default=os.environ.get("ROBOMITUBA_MITSUBA_VARIANT", "auto"),
        help="Mitsuba variant to use for rendering, or 'auto' for runtime fallback.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.request_json.read_text(encoding="utf-8"))
    render_request = render_request_from_payload(payload)
    bundle = render_timestep_bundle_split_lighting(
        render_request,
        repo_root=args.repo_root,
        variant=args.variant,
    )
    print(json.dumps(
        {
            "manifest": str(args.repo_root.resolve() / Path(bundle.bundle_root) / "manifest.json"),
            "bundle_root": bundle.bundle_root,
            "requested_modalities": bundle.requested_modalities,
            "artifact_count": len(bundle.artifacts),
            "status": bundle.status,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
