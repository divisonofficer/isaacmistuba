#!/usr/bin/env python3
"""Select the near-field, object-facing subset of an already rendered IR dataset.

The active-NIR flash irradiance falls off as ``1/r^2``, so the specular cue the
roughness hypothesis depends on is only present in frames captured close to a
material-rich surface.  The graph-driven camera universe that produced the
existing datasets had no look-at target and no distance control, so only a
minority of its frames satisfy that condition.

This selects those frames from the artifacts a dataset already stores -- the
``depth`` camera-Z map and the ``material_id`` map -- so a near-field corpus is
available for analysis without spending a single GPU-second on re-rendering.

It is deliberately read-only: it writes a sidecar selection next to the dataset
and never edits ``index.jsonl`` or any raster.

Caveat recorded in the output: these frames are *accidentally* near-field, not
composed around an object.  Framing is uncentred and there is no multi-view
capture-set structure, so this is a sanity-check corpus, not a training corpus.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

SCHEMA = "robomituba.ir_near_field_subset.v1"
SELECTOR_VERSION = "depth-material-near-field-v1"
# The centre crop the distance and content tests are evaluated over.  A camera
# "looks at" whatever occupies the middle of its frame; the periphery is mostly
# floor and wall at any pose.
CENTRE_CROP = 0.30, 0.70
MIN_VALID_DEPTH_M = 0.01


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _centre(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    lo, hi = CENTRE_CROP
    return image[int(height * lo):int(height * hi), int(width * lo):int(width * hi)]


def _frame_metrics(dataset: Path, row: dict) -> dict | None:
    """Return centre-crop distance and material richness, or None if unreadable."""
    paths = row.get("paths") or {}
    depth_ref = paths.get("depth")
    if not depth_ref:
        return None
    depth = cv2.imread(str(dataset / depth_ref), cv2.IMREAD_UNCHANGED)
    if depth is None:
        return None
    # ``depth`` is the documented ``camera_z_millimeters_u16`` encoding.
    metres = _centre(depth.astype(np.float32) / 1000.0)
    valid = metres[metres > MIN_VALID_DEPTH_M]
    if valid.size < 100:
        return None
    material_count = None
    material_ref = paths.get("material_id")
    if material_ref:
        material = cv2.imread(str(dataset / material_ref), cv2.IMREAD_UNCHANGED)
        if material is not None:
            crop = _centre(material)
            flat = crop.reshape(-1, crop.shape[-1]) if crop.ndim == 3 else crop.reshape(-1, 1)
            material_count = int(np.unique(flat, axis=0).shape[0])
    return {
        "centre_depth_median_m": round(float(np.median(valid)), 4),
        "centre_depth_p10_m": round(float(np.percentile(valid, 10)), 4),
        "centre_depth_p90_m": round(float(np.percentile(valid, 90)), 4),
        "centre_valid_fraction": round(float(valid.size / metres.size), 4),
        "centre_material_count": material_count,
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="rendered IR dataset root")
    parser.add_argument("--out", type=Path, help="selection JSON (default: <dataset>/near_field_subset.json)")
    parser.add_argument("--min-distance", type=float, default=0.7)
    parser.add_argument("--max-distance", type=float, default=1.4)
    parser.add_argument("--min-material-count", type=int, default=4,
                        help="distinct material ids required in the centre crop")
    parser.add_argument("--min-valid-fraction", type=float, default=0.5,
                        help="minimum finite-surface fraction of the centre crop")
    parser.add_argument("--limit", type=int, help="only inspect the first N frames (sampling)")
    return parser.parse_args()


def main() -> int:
    args = _args()
    dataset = args.dataset.resolve()
    index = dataset / "index.jsonl"
    if not index.is_file():
        raise SystemExit(f"dataset has no index.jsonl: {dataset}")
    config = json.loads((dataset / "dataset_config.json").read_text(encoding="utf-8"))

    rows = [json.loads(line) for line in index.open(encoding="utf-8") if line.strip()]
    if args.limit is not None:
        rows = rows[:args.limit]

    selected, rejected, unreadable = [], 0, 0
    distances: list[float] = []
    for row in rows:
        metrics = _frame_metrics(dataset, row)
        if metrics is None:
            unreadable += 1
            continue
        distances.append(metrics["centre_depth_median_m"])
        in_band = args.min_distance <= metrics["centre_depth_median_m"] < args.max_distance
        rich = (metrics["centre_material_count"] is not None
                and metrics["centre_material_count"] >= args.min_material_count)
        if in_band and rich and metrics["centre_valid_fraction"] >= args.min_valid_fraction:
            selected.append({"frame_id": row["frame_id"],
                             "viewpoint_id": row.get("viewpoint_id"),
                             "heading_deg": row.get("heading_deg"),
                             "lighting_id": (row.get("lighting") or {}).get("id"),
                             **metrics})
        else:
            rejected += 1

    quantiles = {}
    if distances:
        array = np.asarray(distances, dtype=np.float64)
        quantiles = {f"p{q}": round(float(np.percentile(array, q)), 4) for q in (10, 25, 50, 75, 90)}

    core = {
        "schema": SCHEMA,
        "selector_version": SELECTOR_VERSION,
        "dataset": dataset.name,
        "dataset_fingerprint": config.get("dataset_fingerprint"),
        "source_frame_count": len(rows),
        "inspected_frame_count": len(rows) - unreadable,
        "unreadable_frame_count": unreadable,
        "selected_frame_count": len(selected),
        "rejected_frame_count": rejected,
        "selection_rate": round(len(selected) / max(len(rows) - unreadable, 1), 4),
        "criteria": {
            "centre_crop": list(CENTRE_CROP),
            "distance_band_m": [args.min_distance, args.max_distance],
            "min_material_count": args.min_material_count,
            "min_valid_fraction": args.min_valid_fraction,
            "depth_encoding": "camera_z_millimeters_u16",
        },
        "centre_depth_quantiles_m": quantiles,
        # These frames were not composed around an object; they are near-field by
        # accident of the graph sweep.  Framing is uncentred and there is no
        # capture-set structure, so this is a diagnostic corpus only.
        "usage": "sanity_check_corpus_not_training_corpus",
        "frames": selected,
    }
    payload = {**core, "selection_digest": _digest(core)}

    out = args.out or (dataset / "near_field_subset.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(out.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(out)
    print(json.dumps({key: payload[key] for key in (
        "dataset", "source_frame_count", "selected_frame_count", "selection_rate",
        "centre_depth_quantiles_m",
    )}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
