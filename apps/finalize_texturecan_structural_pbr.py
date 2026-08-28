#!/usr/bin/env python3
"""Create an immutable explicit-role TextureCan structural PBR registry from review tokens."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.texturecan_pbr import finalize_structural_registry, write_scale_overrides_template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, default=Path("/bean/ir_pbr_assets/texturecan_staging_v1"))
    parser.add_argument("--out", type=Path, default=Path("/bean/ir_pbr_assets/texturecan_structural_v1"))
    parser.add_argument("--scale-overrides", type=Path)
    parser.add_argument("--review-subdir", default="review",
                        help="staging-relative review profile (default: review)")
    parser.add_argument("--write-scale-template", type=Path,
                        help="write a null-valued worksheet for the currently retained review thumbnails and exit")
    parser.add_argument("--purge-unselected", action="store_true",
                        help="after a successful finalization, remove unselected raw staging bundles")
    args = parser.parse_args()
    if args.write_scale_template:
        template = write_scale_overrides_template(args.staging_root, args.write_scale_template,
                                                   review_subdir=args.review_subdir)
        print(f"[texturecan] scale worksheet assets={len(template['assets'])} path={args.write_scale_template}")
        return 0
    if args.scale_overrides is None:
        parser.error("--scale-overrides is required unless --write-scale-template is used")
    registry = finalize_structural_registry(args.staging_root, args.out, args.scale_overrides,
                                            purge_unselected=args.purge_unselected,
                                            review_subdir=args.review_subdir)
    print(f"[texturecan] finalized materials={len(registry['materials'])} registry={args.out / 'registry.lock.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
