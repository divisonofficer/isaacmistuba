#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "modules" / "navigation_dataset" / "src"
if str(MODULE_PATH) not in sys.path:
    sys.path.insert(0, str(MODULE_PATH))

from navigation_dataset.office_assets import build_office_asset_coverage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Report shared-office asset coverage for OpticalNav.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Robomituba repository root.")
    parser.add_argument("--json", action="store_true", help="Print full JSON payload.")
    args = parser.parse_args()

    report = build_office_asset_coverage(Path(args.repo_root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("Office Asset Coverage")
    print("=====================")
    for category, item in report["summary"].items():
        required = "required" if item["required"] else "optional"
        print(
            f"{category:18} {item['status']:18} "
            f"available={item['available_count']:3} "
            f"download={item['download_candidate_count']:3} "
            f"material_missing={item['material_missing_count']:2} "
            f"{required}"
        )
        for example in item["examples"][:3]:
            print(f"  - {example['label']} [{example['source']}:{example['status']}]")
    missing = report["totals"]["external_needed_categories"]
    if missing:
        print("\nExternal assets still needed: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
