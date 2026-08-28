#!/usr/bin/env python3
"""Create read-only scene_review_v1 labels for generated IR datasets.

The review is intentionally metadata-only: it never inspects rendered pixels and
never moves/deletes a dataset.  A pose is paired when the same viewpoint,
heading, and capture anchor have more than one lighting condition.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "robomituba.ir_scene_review.v1"
COMPILER = "ir-scene-review-v1"
OVERRIDES_SCHEMA = "robomituba.ir_scene_review_overrides.v1"
DEFAULT_OVERRIDES = Path("/bean/ir_dataset_work/.catalog_scene_review_overrides.json")
VALID_TIERS = frozenset({"A", "B", "C", "D"})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(path: Path) -> str:
    return str(read(path / "dataset_config.json").get("dataset_fingerprint") or "")


def stats_for(fp: str, dataset: Path, stats_root: Path | None) -> dict:
    if stats_root:
        sidecar = stats_root / f"{fp}.json"
        if sidecar.is_file():
            try:
                value = read(sidecar)
                if value.get("schema") == "robomituba.ir_scene_statistics.v1" and (value.get("backfill") or {}).get("dataset_fingerprint") == fp:
                    return value
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    native = dataset / "quality" / "scene_statistics.json"
    try:
        value = read(native)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def load_overrides(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load persistent human review decisions without weakening source binding.

    Automatic labels are intentionally reproducible from metadata.  A small
    separate file is used for documented expert exceptions, so re-running the
    reviewer does not silently erase a visual/experimental judgment.
    """
    if path is None or not path.is_file():
        return {}
    value = read(path)
    if value.get("schema") != OVERRIDES_SCHEMA:
        raise ValueError(f"unsupported scene-review overrides schema: {path}")
    entries = value.get("overrides")
    if not isinstance(entries, dict):
        raise ValueError(f"scene-review overrides must contain an object: {path}")
    result: dict[str, dict[str, Any]] = {}
    for fp, entry in entries.items():
        if not isinstance(fp, str) or not isinstance(entry, dict):
            raise ValueError(f"invalid scene-review override entry: {fp!r}")
        tier = str(entry.get("review_tier") or "")
        if tier not in VALID_TIERS:
            raise ValueError(f"invalid scene-review override tier for {fp}: {tier!r}")
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"scene-review override rationale is required for {fp}")
        result[fp] = dict(entry)
    return result


def review(dataset: Path, stats_root: Path | None, overrides: dict[str, dict[str, Any]] | None = None) -> dict:
    config_path, index_path = dataset / "dataset_config.json", dataset / "index.jsonl"
    fp = fingerprint(dataset)
    rows = []
    with index_path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    physical: dict[tuple, set[str]] = defaultdict(set)
    for row in rows:
        lighting = row.get("lighting") if isinstance(row.get("lighting"), dict) else {}
        lighting_id = str(lighting.get("id") or row.get("lighting_id") or "reference_neutral_v1")
        anchor = str(lighting.get("anchor_id") or row.get("anchor_id") or "")
        heading = round(float(row.get("heading_deg") or 0.0) % 360.0, 4)
        key = (str(row.get("viewpoint_id") or ""), heading, anchor)
        physical[key].add(lighting_id)
    pose_count = len(physical)
    paired_count = sum(len(values) > 1 for values in physical.values())
    ratio = paired_count / pose_count if pose_count else 0.0
    lighting_count = len({item for values in physical.values() for item in values})
    stats = stats_for(fp, dataset, stats_root)
    density = str(stats.get("density_class") or "unknown")
    rationale: list[str] = []
    if density == "dense" and pose_count >= 50 and ratio >= 0.20:
        tier, deprecated = "A", False
        rationale.append("dense scene with >=50 physical poses and >=20% paired lighting coverage")
    elif density == "dense":
        tier, deprecated = "B", False
        rationale.append("dense scene but physical pose or paired-lighting coverage is below Tier A")
    elif density in {"moderate"} and paired_count:
        tier, deprecated = "C", False
        rationale.append("paired lighting exists but scene is not classified dense")
    else:
        tier, deprecated = "D", True
        rationale.append("sparse/unknown scene or no same-pose lighting variation")
    if pose_count < 50: rationale.append(f"physical poses={pose_count} (<50)")
    if ratio < 0.20: rationale.append(f"paired pose ratio={ratio:.3f} (<0.20)")
    if density == "unknown": rationale.append("density classification is unknown")
    result = {
        "schema": SCHEMA, "compiler_version": COMPILER, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_fingerprint": fp, "dataset_name": dataset.name, "review_tier": tier,
        "density_class": density, "physical_pose_count": pose_count, "paired_pose_count": paired_count,
        "paired_pose_ratio": round(ratio, 6), "lighting_condition_count": lighting_count,
        "deprecation_candidate": deprecated, "requires_visual_qa": tier in {"A", "B"},
        "rationale": rationale,
        "binding": {"dataset_fingerprint": fp, "sources": [
            {"path": str(config_path.resolve()), "sha256": sha256(config_path)},
            {"path": str(index_path.resolve()), "sha256": sha256(index_path)},
        ]},
    }
    override = (overrides or {}).get(fp)
    if override:
        original_tier = result["review_tier"]
        result["review_tier"] = str(override["review_tier"])
        result["deprecation_candidate"] = bool(override.get("deprecation_candidate", result["review_tier"] == "D"))
        result["requires_visual_qa"] = bool(override.get("requires_visual_qa", result["review_tier"] in {"A", "B", "C"}))
        result["manual_override"] = {
            "automatic_tier": original_tier,
            "review_tier": result["review_tier"],
            "rationale": str(override["rationale"]).strip(),
            **({"reviewer": str(override["reviewer"])} if override.get("reviewer") else {}),
            **({"reviewed_at": str(override["reviewed_at"])} if override.get("reviewed_at") else {}),
        }
        result["rationale"].append(f"manual override: {result['manual_override']['rationale']}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", action="append", type=Path, default=[])
    parser.add_argument("--stats-root", type=Path, default=Path("/bean/ir_dataset_work/.catalog_statistics"))
    parser.add_argument("--out", type=Path, default=Path("/bean/ir_dataset_work/.catalog_scene_reviews"))
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES,
                        help="Persistent documented manual tier overrides (default: %(default)s).")
    parser.add_argument("--dataset", action="append", type=Path, default=[],
                        help="Review only these dataset directories (repeatable).")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    overrides = load_overrides(args.overrides)
    roots = args.dataset_root or [Path("/bean/ir_dataset"), Path("/bean/ir_dataset_work"), Path("out/ir_dataset")]
    seen: dict[str, Path] = {}
    candidates = args.dataset or []
    if candidates:
        roots = []
        paths = candidates
    else:
        paths = []
        for root in roots:
            if not root.is_dir(): continue
            paths.extend(sorted(root.iterdir(), key=lambda p: p.name))
    for path in paths:
        if not path.is_dir() or path.name.startswith(".") or path.is_symlink(): continue
        try:
            if (path / "dataset_config.json").is_file() and (path / "index.jsonl").is_file():
                fp = fingerprint(path)
                if fp and fp not in seen: seen[fp] = path
        except (OSError, ValueError, json.JSONDecodeError): continue
    reports, failures = [], []
    for fp, dataset in sorted(seen.items(), key=lambda item: item[1].name.lower()):
        try:
            value = review(dataset, args.stats_root, overrides)
            target = args.out / f"{fp}.json"
            if not args.dry_run:
                args.out.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                tmp.replace(target)
            reports.append({"dataset": dataset.name, "fingerprint": fp, "tier": value["review_tier"], "target": str(target)})
        except Exception as exc:
            failures.append({"dataset": dataset.name, "fingerprint": fp, "error": str(exc)})
    print(json.dumps({"schema": "robomituba.ir_scene_review_report.v1", "compiler_version": COMPILER,
                      "processed": len(reports), "failed": len(failures), "reports": reports, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
