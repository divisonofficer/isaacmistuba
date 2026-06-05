#!/usr/bin/env python3
"""Download an optimized subset of Digital Twin Catalog object models.

The script expects the Project Aria DTC object CDN JSON and uses the official
``dtc_object_downloader`` CLI. It intentionally downloads only the object GLB,
metadata, and license files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _object_entries(cdn_file: Path) -> list[tuple[int, str]]:
    payload = json.loads(cdn_file.read_text(encoding="utf-8"))
    objects = payload["releases"]["DTC"]["objects"]
    rows: list[tuple[int, str]] = []
    for name, files in objects.items():
        glb = files.get("3d-asset_glb") or {}
        size = int(glb.get("file_size_bytes") or 0)
        if size > 0:
            rows.append((size, str(name)))
    return sorted(rows)


def _already_downloaded(output_dir: Path, name: str) -> bool:
    object_dir = output_dir / name
    return (
        (object_dir / "3d-asset.glb").exists()
        and (object_dir / "metadata.json").exists()
        and (object_dir / "CC_BY-SA.txt").exists()
    )


def _batched(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdn-file", default="assets/dtc_object/DTC_objects_all_download_urls.json")
    parser.add_argument("--output", default="vendor_datasets/dtc_objects")
    parser.add_argument("--count", type=int, default=200, help="Target total object count by smallest GLB size.")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = _repo_root()
    cdn_file = (repo / args.cdn_file).resolve()
    output_dir = (repo / args.output).resolve()
    downloader = shutil.which("dtc_object_downloader")
    if downloader is None:
        print("dtc_object_downloader not found. Install projectaria-tools first.", file=sys.stderr)
        return 2
    if not cdn_file.exists():
        print(f"CDN file not found: {cdn_file}", file=sys.stderr)
        return 2

    rows = _object_entries(cdn_file)
    selected = rows[: max(0, args.count)]
    missing = [name for _, name in selected if not _already_downloaded(output_dir, name)]
    total_size = sum(size for size, _ in selected)
    missing_size = sum(size for size, name in selected if name in set(missing))
    print(f"selected_objects={len(selected)} selected_glb_gb={total_size / 1024**3:.2f}")
    print(f"already_downloaded={len(selected) - len(missing)} missing={len(missing)} missing_glb_gb={missing_size / 1024**3:.2f}")
    if args.dry_run:
        for size, name in selected[: min(40, len(selected))]:
            status = "done" if _already_downloaded(output_dir, name) else "missing"
            print(f"{size / 1024**2:7.1f} MB  {status:7s}  {name}")
        return 0
    if not missing:
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    for batch_index, batch in enumerate(_batched(missing, max(1, args.batch_size)), start=1):
        print(f"\n=== DTC batch {batch_index}: {len(batch)} objects ===")
        cmd = [
            downloader,
            "-c", str(cdn_file),
            "-o", str(output_dir),
            "-r", "DTC",
            "-l", *batch,
            "-k", "3d-asset_glb", "metadata", "license",
            "-x", "__none__",
        ]
        subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
