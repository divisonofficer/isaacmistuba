#!/usr/bin/env python3
"""Run the reversible, architecture-oriented second pass over TextureCan review tokens."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.texturecan_pbr import second_pass_structural_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/bean/ir_pbr_assets/texturecan_staging_v1"))
    parser.add_argument("--apply-hard-deferrals", action="store_true",
                        help="move only high-confidence non-structural tokens to reversible review_deferred/<run-id>/")
    parser.add_argument("--apply-interior-baseline", action="store_true",
                        help="also defer specialty/style/weathering candidates, leaving only conservative interior structural finishes")
    parser.add_argument("--run-id", help="stable audit/defer folder ID; default is UTC time")
    args = parser.parse_args()
    report = second_pass_structural_review(
        args.root,
        apply_hard_deferrals=args.apply_hard_deferrals or args.apply_interior_baseline,
        apply_manual_deferrals=args.apply_interior_baseline,
        run_id=args.run_id,
    )
    print(
        f"[texturecan] second-pass run={report['run_id']} counts={report['counts']} "
        f"moved={len(report['moved'])} report={args.root / 'second_pass_reports' / 'latest.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
