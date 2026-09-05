#!/usr/bin/env python3
"""Select the frames worth training a metallic head on.

PBR-Rooms reports one corpus-wide number -- 0.83% of pixels above metallic 0.5,
2.50% in its richest room type -- and ours sits in the same regime at 0.90%.
That is a property of Infinigen's indoor assets, not of either pipeline, so
raising it is not the lever. Choosing frames is.

Area alone is the wrong selector. Measured over 474 metal-bearing frames it
correlates only +0.33 with the number of distinct metal materials in view and
-0.12 with distance, the median frame shows exactly one metal material, and the
three highest-area frames are a single material filling the view from 0.24 to
0.52 m -- one of them closer than the camera sampler's own standoff band. That
is a close-up of one surface, not a rich frame.

So select on what the frame actually contains: at least two distinct metal
materials, seen from the working distance the dataset was designed around. On
the r13 corpus that keeps roughly a third of metal-bearing frames across 14 of
16 scenes and raises the median distinct-material count from 1 to 3, at a
median coverage of 2.1%.

    python apps/build_ir_metallic_rich_subset.py --dataset <root> [--dataset ...] \
        --out subset.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

SCHEMA = "robomituba.ir_metallic_rich_subset.v1"
SELECTOR_VERSION = "metal-material-diversity-v1"

#: A pixel counts as metal-bearing here at the same 0.5 the benchmark uses, so
#: the reported coverage stays comparable to a published number.
METAL_THRESHOLD = 0.5
#: Ignore a material occupying a handful of pixels: an anti-aliased sliver of a
#: neighbouring object is not a second metal material in view.
MIN_MATERIAL_PIXELS = 200
DEFAULT_MIN_MATERIALS = 2
#: The camera sampler places poses 1-2 m from their anchor. Frames whose metal
#: sits far outside that band are either a close-up of one surface or metal
#: glimpsed across the room; neither is what the flash was aimed at.
DEFAULT_DEPTH_RANGE_M = (0.8, 2.5)
#: Per scene, so one metal-rich room cannot become the subset. Selecting purely
#: by coverage gave a single dining room 22-32% of the frames, which is the
#: room-type bias this exists to avoid.
DEFAULT_PER_SCENE_QUOTA = 40


def frame_metrics(root: Path, frame_id: str) -> dict | None:
    """Metal coverage, distinct metal materials and metal depth for one frame."""
    metallic = cv2.imread(str(root / "metallic" / f"{frame_id}.png"), cv2.IMREAD_UNCHANGED)
    if metallic is None:
        return None
    values = metallic.astype(np.float32) / 65535.0
    values = values.mean(2) if values.ndim == 3 else values
    valid = np.ones(values.shape, dtype=bool)
    defined = cv2.imread(str(root / "gt_defined_mask" / f"{frame_id}.png"), cv2.IMREAD_UNCHANGED)
    if defined is not None:
        valid = defined.astype(np.float32) > 0.5
    metal = valid & (values > METAL_THRESHOLD)
    if not metal.any():
        return {"coverage": 0.0, "materials": 0, "depth_m": None}

    materials = 0
    ids = cv2.imread(str(root / "material_id" / f"{frame_id}.png"), cv2.IMREAD_UNCHANGED)
    if ids is not None:
        present, counts = np.unique(ids[metal], return_counts=True)
        materials = int((counts >= MIN_MATERIAL_PIXELS).sum())

    depth_m = None
    depth = cv2.imread(str(root / "depth" / f"{frame_id}.png"), cv2.IMREAD_UNCHANGED)
    if depth is not None:
        # camera_z_millimeters_u16
        samples = depth.astype(np.float32)
        samples = samples.mean(2) if samples.ndim == 3 else samples
        samples = samples[metal]
        samples = samples[samples > 0]
        if samples.size:
            depth_m = float(np.median(samples)) / 1000.0
    return {"coverage": float(metal.sum() / max(1, int(valid.sum()))),
            "materials": materials, "depth_m": depth_m}


def select(rows: list[dict], *, min_materials: int, depth_range: tuple[float, float],
           quota: int) -> list[dict]:
    """Keep the richest frames per scene among those that pass the rule."""
    low, high = depth_range
    eligible = [r for r in rows
                if r["materials"] >= min_materials
                and (r["depth_m"] is None or low <= r["depth_m"] <= high)]
    by_scene: dict[str, list[dict]] = {}
    for row in eligible:
        by_scene.setdefault(row["scene"], []).append(row)
    kept: list[dict] = []
    for scene_rows in by_scene.values():
        scene_rows.sort(key=lambda r: (-r["materials"], -r["coverage"], r["frame_id"]))
        kept.extend(scene_rows[:quota])
    kept.sort(key=lambda r: (r["scene"], r["frame_id"]))
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, action="append", required=True,
                        help="dataset root holding metallic/ and material_id/ (repeatable)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-materials", type=int, default=DEFAULT_MIN_MATERIALS)
    parser.add_argument("--depth-min", type=float, default=DEFAULT_DEPTH_RANGE_M[0])
    parser.add_argument("--depth-max", type=float, default=DEFAULT_DEPTH_RANGE_M[1])
    parser.add_argument("--per-scene-quota", type=int, default=DEFAULT_PER_SCENE_QUOTA)
    args = parser.parse_args()

    rows: list[dict] = []
    for root in args.dataset:
        root = root.resolve()
        if not (root / "metallic").is_dir():
            print(f"[metal-subset] skipping {root.name}: no metallic/", file=sys.stderr)
            continue
        for path in sorted((root / "metallic").glob("*.png")):
            frame_id = path.stem
            metrics = frame_metrics(root, frame_id)
            if metrics is None:
                continue
            rows.append({"scene": root.name, "frame_id": frame_id, "dataset": str(root), **metrics})

    kept = select(rows, min_materials=args.min_materials,
                  depth_range=(args.depth_min, args.depth_max), quota=args.per_scene_quota)
    covered = [r["coverage"] for r in kept]
    report = {
        "schema": SCHEMA, "selector_version": SELECTOR_VERSION,
        "metal_threshold": METAL_THRESHOLD,
        "rule": {"min_distinct_metal_materials": args.min_materials,
                 "metal_depth_range_m": [args.depth_min, args.depth_max],
                 "per_scene_quota": args.per_scene_quota,
                 "min_material_pixels": MIN_MATERIAL_PIXELS},
        "examined_frames": len(rows), "selected_frames": len(kept),
        "scenes_examined": len({r["scene"] for r in rows}),
        "scenes_selected": len({r["scene"] for r in kept}),
        "mean_coverage": round(float(np.mean(covered)), 6) if covered else None,
        "median_distinct_materials": (int(np.median([r["materials"] for r in kept]))
                                      if kept else None),
        "frames": kept,
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[metal-subset] {len(kept)} of {len(rows)} frames, "
          f"{report['scenes_selected']}/{report['scenes_examined']} scenes")
    if covered:
        share = max(len([r for r in kept if r['scene'] == s]) for s in {r['scene'] for r in kept})
        print(f"[metal-subset]   mean metal coverage {np.mean(covered)*100:.2f}% "
              f"(PBR-Rooms reports 0.83% overall, 2.50% in its richest room type)")
        print(f"[metal-subset]   median distinct metal materials "
              f"{report['median_distinct_materials']}  ·  largest scene share "
              f"{share/len(kept)*100:.1f}%")
    print(f"[metal-subset]   -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
