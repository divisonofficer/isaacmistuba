#!/usr/bin/env python3
"""Mirror TextureCan's selected CC0 categories into a reviewable 2K staging corpus."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.texturecan_pbr import CATEGORY_SLUGS, create_review_thumbnails, mirror_categories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/bean/ir_pbr_assets/texturecan_staging_v1"))
    parser.add_argument("--category", action="append", choices=sorted(CATEGORY_SLUGS), help="repeat to restrict the mirror")
    parser.add_argument("--limit", type=int, help="development/testing cap after discovery")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--review", action="store_true", help="create role-specific review thumbnails after staging")
    parser.add_argument("--reset-review", action="store_true", help="replace a prior review folder; normally deleted tokens are preserved")
    args = parser.parse_args()
    payload = mirror_categories(args.root, categories=args.category or CATEGORY_SLUGS, limit=args.limit,
                                workers=args.workers, timeout=args.timeout)
    accepted = sum(row.get("status") == "accepted" for row in payload["materials"])
    rejected = sum(row.get("status") == "rejected" for row in payload["materials"])
    print(f"[texturecan] accepted={accepted} rejected={rejected} manifest={args.root / 'staging_manifest.json'}")
    if args.review:
        review = create_review_thumbnails(args.root, reset=args.reset_review)
        print(f"[texturecan] review={args.root / 'review'} counts={review['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
