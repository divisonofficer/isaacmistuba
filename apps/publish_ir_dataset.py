#!/usr/bin/env python3
"""Safely publish a completed Principled IR dataset to /bean/ir_dataset."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.ir_dataset_publish import publish_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="completed dataset below out/ir_dataset")
    parser.add_argument("--name", help="destination directory name; defaults to source basename")
    parser.add_argument("--destination-root", type=Path, default=Path("/bean/ir_dataset"))
    args = parser.parse_args()
    source = args.dataset.resolve()
    allowed = (REPO_ROOT / "out" / "ir_dataset").resolve()
    if allowed != source and allowed not in source.parents:
        parser.error(f"--dataset must be inside {allowed}")

    last_stage = None

    def progress(stage: str, files_done: int, files_total: int, bytes_done: int, bytes_total: int) -> None:
        nonlocal last_stage
        if stage != last_stage or files_done == files_total or files_done % 100 == 0:
            pct = 100.0 * bytes_done / max(bytes_total, 1)
            print(f"[publish] {stage} files={files_done}/{files_total} bytes={bytes_done}/{bytes_total} ({pct:.1f}%)", flush=True)
            last_stage = stage

    result = publish_dataset(source, args.destination_root, name=args.name, progress=progress)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
