#!/usr/bin/env python3
"""Create the deterministic 100-asset TextureCan extended structural registry."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.texturecan_pbr import (
    create_extended_structural_review_profile,
    finalize_structural_registry,
    write_extended_scale_overrides,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, default=Path("/bean/ir_pbr_assets/texturecan_staging_v1"))
    parser.add_argument("--out", type=Path, default=Path("/bean/ir_pbr_assets/texturecan_structural_extended_v1"))
    parser.add_argument("--profile", default="extended_v1")
    parser.add_argument("--review-subdir", default="review_extended_v1")
    parser.add_argument("--max-assets", type=int, default=100)
    parser.add_argument("--review-only", action="store_true")
    args = parser.parse_args()

    selection = create_extended_structural_review_profile(
        args.staging_root, review_subdir=args.review_subdir,
        profile_name=args.profile, max_assets=args.max_assets,
    )
    profile_dir = args.staging_root / "extended_profiles" / args.profile
    scales = profile_dir / "scale_overrides.json"
    write_extended_scale_overrides(args.staging_root, scales, review_subdir=args.review_subdir)
    print(f"[texturecan] extended profile assets={len(selection['selected'])} "
          f"candidates={selection['candidate_asset_count']} digest={selection['digest']}")
    if args.review_only:
        return 0
    registry = finalize_structural_registry(args.staging_root, args.out, scales,
                                            review_subdir=args.review_subdir)
    print(f"[texturecan] finalized materials={len(registry['materials'])} registry={args.out / 'registry.lock.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
