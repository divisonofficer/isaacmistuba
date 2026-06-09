"""
Phase 3: Export an OpticalNav scene's authoring_map to a .usda file.

The exported file can be opened in Isaac Sim.  Each object that has a
source_ref (USD prim path) is emitted as an Xform with a USD Reference to the
original prim — so full geometry and materials are preserved without copying data.

Usage:
  python apps/export_scene_to_usd.py \\
      --project opticalnav-v0.2 \\
      --scene office_lobby_001 \\
      --output out/exported/office_lobby_001.usda

  python apps/export_scene_to_usd.py \\
      --project opticalnav-v0.2 \\
      --scene moorelane_kitchen_001 \\
      --output out/exported/kitchen.usda

Validation:
  python -c "from pxr import Usd; s=Usd.Stage.Open('out/exported/kitchen.usda'); print(len(list(s.TraverseAll())), 'prims')"
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPTICALNAV_ROOT = REPO_ROOT / "out" / "opticalnav"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export authoring_map to .usda for Isaac Sim")
    parser.add_argument("--project", required=True, help="Project ID (e.g. opticalnav-v0.2)")
    parser.add_argument("--scene", required=True, help="Scene ID (e.g. office_lobby_001)")
    parser.add_argument(
        "--output", default=None,
        help="Output .usda path (default: out/exported/{scene}.usda)",
    )
    parser.add_argument(
        "--wall-height", type=float, default=None,
        help="Override default wall height in metres",
    )
    args = parser.parse_args()

    am_path = OPTICALNAV_ROOT / args.project / "scenes" / args.scene / "authoring_map.json"
    if not am_path.exists():
        print(f"[ERROR] authoring_map.json not found: {am_path}", file=sys.stderr)
        sys.exit(1)

    authoring_map = json.loads(am_path.read_text(encoding="utf-8"))

    if args.output:
        out_path = Path(args.output)
    else:
        out_dir = REPO_ROOT / "out" / "exported"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.scene}.usda"

    sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
    sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
    from mitsuba_converter.usd_exporter import export_authoring_map_to_usd

    objects = authoring_map.get("objects") or []
    has_ref = sum(1 for o in objects if "#" in (o.get("source_ref") or ""))
    print(f"Exporting {args.scene}: {len(objects)} objects ({has_ref} with USD references)")

    result = export_authoring_map_to_usd(
        authoring_map,
        output_usda_path=out_path,
        repo_root=REPO_ROOT,
        default_wall_height_m=args.wall_height,
    )
    print(f"Written: {result}")

    # Quick validation
    try:
        from pxr import Usd
        stage = Usd.Stage.Open(str(result))
        prim_count = sum(1 for _ in stage.TraverseAll())
        print(f"Validation OK — {prim_count} prims in stage")
    except Exception as exc:
        print(f"[WARN] Validation failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
