#!/usr/bin/env python3
"""Label completed IR datasets against the scene-scale specular target."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))

from mitsuba_converter.ir_dataset_readiness import (  # noqa: E402
    CLASSIFIER_VERSION,
    PROFILE,
    SCHEMA,
    build_readiness_label,
)

REPORT_SCHEMA = "robomituba.ir_inverse_rendering_readiness_report.v1"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _statistics_path(dataset: Path, fingerprint: str, statistics_root: Path) -> Path | None:
    native = dataset / "quality" / "scene_statistics.json"
    overlay = statistics_root / f"{fingerprint}.json"
    return native if native.is_file() else overlay if overlay.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=Path("/bean/ir_dataset"))
    parser.add_argument("--statistics-root", type=Path, default=Path("/bean/ir_dataset_work/.catalog_statistics"))
    parser.add_argument("--label-root", type=Path, default=Path("/bean/ir_dataset_work/.catalog_quality_labels"))
    parser.add_argument("--dataset", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    wanted = set(args.dataset)
    reports: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for dataset in sorted(args.dataset_root.iterdir(), key=lambda item: item.name.lower()):
        if not dataset.is_dir() or dataset.name.startswith("."):
            continue
        if wanted and dataset.name not in wanted:
            continue
        config_path, contract_path, index_path = (
            dataset / "dataset_config.json", dataset / "artifact_contract.json", dataset / "index.jsonl"
        )
        if not all(path.is_file() for path in (config_path, contract_path, index_path)):
            continue
        try:
            config, contract = _read(config_path), _read(contract_path)
            fingerprint = str(config.get("dataset_fingerprint") or "")
            if not fingerprint or fingerprint != str(contract.get("dataset_fingerprint") or ""):
                raise ValueError("dataset/artifact fingerprint mismatch")
            statistics_path = _statistics_path(dataset, fingerprint, args.statistics_root)
            statistics = _read(statistics_path) if statistics_path else None
            label = build_readiness_label(dataset_name=dataset.name, dataset_fingerprint=fingerprint,
                                            scene_statistics=statistics)
            sources = [config_path, contract_path, index_path]
            if statistics_path:
                sources.append(statistics_path)
            label["binding"] = {
                "dataset_fingerprint": fingerprint,
                "sources": [{"path": str(path.resolve()), "sha256": _sha256(path)} for path in sources],
            }
            label["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            target = args.label_root / f"{fingerprint}.json"
            if not args.dry_run:
                _atomic_json(target, label)
            reports.append({
                "dataset": dataset.name, "fingerprint": fingerprint, "status": label["status"],
                "visible_median": label["evidence"]["selected_visible_object_count"]["median"],
                "target": str(target),
            })
        except Exception as exc:
            failures.append({"dataset": dataset.name, "error": str(exc)})
    counts = {status: sum(row["status"] == status for row in reports)
              for status in ("below_target", "unverified")}
    report = {
        "schema": REPORT_SCHEMA, "label_schema": SCHEMA, "classifier_version": CLASSIFIER_VERSION,
        "profile": PROFILE, "dry_run": args.dry_run, "processed": len(reports), "failed": len(failures),
        "counts": counts, "datasets": reports, "failures": failures,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if not args.dry_run:
        _atomic_json(args.label_root / "inventory.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
