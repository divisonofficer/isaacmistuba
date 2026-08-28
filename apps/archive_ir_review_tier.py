#!/usr/bin/env python3
"""Archive published datasets marked by scene_review_v1 without deleting them."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", action="append", required=True, choices=["A", "B", "C", "D", "unknown"])
    parser.add_argument("--dataset-root", type=Path, default=Path("/bean/ir_dataset"))
    parser.add_argument("--review-root", type=Path, default=Path("/bean/ir_dataset_work/.catalog_scene_reviews"))
    parser.add_argument("--archive-root", type=Path, default=Path("/bean/ir_dataset_archive"))
    parser.add_argument("--reason", default="scene_review_deprecated")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    if args.commit and args.dry_run:
        parser.error("--commit and --dry-run are mutually exclusive")
    tiers = set(args.tier)
    selected = []
    for review_path in sorted(args.review_root.glob("*.json")):
        try:
            review = read(review_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if review.get("review_tier") not in tiers:
            continue
        name = str(review.get("dataset_name") or "")
        source = args.dataset_root / name
        if source.is_dir() and not source.is_symlink() and (source / "dataset_config.json").is_file():
            selected.append((source, review_path, review))
    results, failures = [], []
    for source, review_path, review in selected:
        try:
            config = read(source / "dataset_config.json")
            fp = str(config.get("dataset_fingerprint") or review.get("dataset_fingerprint") or "")
            if not fp or fp != str(review.get("dataset_fingerprint") or ""):
                raise ValueError("dataset/review fingerprint mismatch")
            destination = args.archive_root / f"{source.name}.{fp[:12]}"
            manifest = {
                "schema": "robomituba.ir_dataset_retirement.v1",
                "dataset_name": source.name, "dataset_fingerprint": fp,
                "review_tier": review.get("review_tier"), "review_digest": sha256(review_path),
                "reason": args.reason, "archived_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "source": str(source.resolve()), "destination": str(destination.resolve()),
            }
            manifest["retirement_digest"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if args.commit:
                if destination.exists():
                    raise FileExistsError(f"archive destination already exists: {destination}")
                args.archive_root.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                temp = destination / "retirement_manifest.json.tmp"
                temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                os.replace(temp, destination / "retirement_manifest.json")
            results.append({"dataset": source.name, "tier": review.get("review_tier"), "destination": str(destination), "manifest": manifest})
        except Exception as exc:
            failures.append({"dataset": source.name, "error": str(exc)})
    payload = {"schema": "robomituba.ir_dataset_retirement_report.v1", "tiers": sorted(tiers), "commit": bool(args.commit), "processed": len(results), "failed": len(failures), "results": results, "failures": failures}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
