#!/usr/bin/env python3
"""Score an existing IR dataset's views and mark the ones with nothing to see.

The graph camera universe pointed a fixed heading sweep from every node, so a
sizeable share of frames face a bare wall from a few tens of centimetres away.
Those frames are already rendered, and their own AOVs say so: a flat surface
filling the frame has almost no depth spread and one object id.  Scoring what
the camera actually saw needs no re-render and no scene access.

Three signals, all read from the frame's own ground truth:

  depth_iqr        metres between the depth quartiles.  A plane seen head-on
                   has almost none; a view down a room has metres of it.
  centre_objects   distinct object ids in the central half of the frame.
  centre_dominance largest share a single object id takes of that centre.

They are complementary rather than redundant: the worst-rated view in the
calibration set clears the depth threshold on a slightly oblique wall, and is
caught by the other two.

Geometry does not depend on lighting, so each distinct camera is scored once
and its lighting variants inherit the verdict.

Nothing is deleted or overwritten: the report and the filtered index are
written alongside the dataset, which stays immutable.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

SCHEMA = "robomituba.ir_view_content_filter.v1"
FILTER_VERSION = "rendered-content-v1"

#: Calibrated against sixteen human-labelled views across four datasets
#: (nine poor, seven good); the rule reproduces all sixteen.
#:
#: The two object signals carry the decision and are the ones with margin:
#: every labelled poor view has at most two objects in the centre, every good
#: one at least three, and dominance separates 0.82 (good) from 0.92 (poor).
#: Depth spread is only a weak guard against a flat view that somehow shows
#: three ids -- it cannot carry a threshold of its own, since a good view sits
#: at 0.28 m and a poor one at 0.40 m.  The lowest good view is 0.28, so 0.15
#: keeps margin.
MIN_DEPTH_IQR_M = 0.15
MIN_CENTRE_OBJECTS = 3
MAX_CENTRE_DOMINANCE = 0.85


def _read(path: Path):
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)


def score_view(root: Path, frame_id: str) -> dict | None:
    depth = _read(root / "range" / f"{frame_id}.png")
    objects = _read(root / "object_id" / f"{frame_id}.png")
    if depth is None or objects is None:
        return None
    depth = depth.astype(np.float32) / 1000.0
    height, width = depth.shape[:2]
    centre = objects[height // 4:3 * height // 4, width // 4:3 * width // 4]
    _, counts = np.unique(centre, return_counts=True)
    return {
        "depth_iqr_m": float(np.percentile(depth, 75) - np.percentile(depth, 25)),
        "centre_objects": int(len(counts)),
        "centre_dominance": float(counts.max() / centre.size),
        "median_depth_m": float(np.median(depth)),
    }


def verdict(metrics: dict) -> tuple[bool, list[str]]:
    reasons = []
    if metrics["depth_iqr_m"] < MIN_DEPTH_IQR_M:
        reasons.append("flat_surface")
    if metrics["centre_objects"] < MIN_CENTRE_OBJECTS:
        reasons.append("single_object_centre")
    if metrics["centre_dominance"] > MAX_CENTRE_DOMINANCE:
        reasons.append("one_object_fills_centre")
    return (not reasons), reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="report path (default: <dataset>/view_content_filter.json)")
    parser.add_argument("--write-index", action="store_true",
                        help="also write index_filtered.jsonl next to index.jsonl")
    args = parser.parse_args()

    root = args.dataset.resolve()
    rows = [json.loads(line) for line in (root / "index.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]

    cameras: dict[str, list[dict]] = {}
    for row in rows:
        cameras.setdefault(str(row["frame_id"]).split("__l_")[0], []).append(row)

    results, kept_rows = {}, []
    for key, group in cameras.items():
        metrics = score_view(root, str(group[0]["frame_id"]))
        if metrics is None:
            continue
        keep, reasons = verdict(metrics)
        results[key] = {**metrics, "keep": keep, "reject_reasons": reasons,
                        "frame_count": len(group)}
        if keep:
            kept_rows.extend(group)

    kept_cameras = sum(1 for v in results.values() if v["keep"])
    report = {
        "schema": SCHEMA, "filter_version": FILTER_VERSION,
        "dataset": root.name,
        "thresholds": {"min_depth_iqr_m": MIN_DEPTH_IQR_M,
                       "min_centre_objects": MIN_CENTRE_OBJECTS,
                       "max_centre_dominance": MAX_CENTRE_DOMINANCE},
        "camera_count": len(results), "camera_kept": kept_cameras,
        "frame_count": len(rows), "frame_kept": len(kept_rows),
        "cameras": results,
    }
    out = args.out or (root / "view_content_filter.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[view-filter] {root.name}")
    print(f"[view-filter]   cameras kept {kept_cameras}/{len(results)}"
          f"  frames kept {len(kept_rows)}/{len(rows)}"
          f" ({len(kept_rows)/max(len(rows),1)*100:.0f}%)")
    reasons: dict[str, int] = {}
    for value in results.values():
        for reason in value["reject_reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    if reasons:
        print(f"[view-filter]   reject reasons: {dict(sorted(reasons.items()))}")
    print(f"[view-filter]   report -> {out}")

    if args.write_index:
        target = root / "index_filtered.jsonl"
        target.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept_rows),
                          encoding="utf-8")
        print(f"[view-filter]   index  -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
