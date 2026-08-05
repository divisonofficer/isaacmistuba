#!/usr/bin/env python3
"""Merge a single-asset spatial-PBR A/B re-render back into the main run.

The glass asset had to be re-rendered on local disk (the 1.5M-triangle OBJ parts
stall on the CIFS mount), so its pairs land in a separate output directory.  This
splices those rows into the main ``metrics.json`` and recomputes the bootstrap
summary with the harness's own aggregators, so the merged file is byte-compatible
with one the harness would have written itself.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_harness():
    for extra in ("modules/mitsuba_converter/src", "modules/robomituba_bridge/src"):
        sys.path.insert(0, str(ROOT / extra))
    spec = importlib.util.spec_from_file_location(
        "render_spatial_pbr_ab", ROOT / "apps/render_spatial_pbr_ab.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", type=Path, required=True, help="main run directory")
    ap.add_argument("--patch", type=Path, required=True, help="single-asset re-render directory")
    ap.add_argument("--asset", required=True)
    ap.add_argument("--bootstrap-samples", type=int, default=2000)
    args = ap.parse_args()

    harness = load_harness()
    main_metrics = json.loads((args.main / "metrics.json").read_text(encoding="utf-8"))
    patch_metrics = json.loads((args.patch / "metrics.json").read_text(encoding="utf-8"))

    fresh = [r for r in patch_metrics["pairs"] if r["asset"] == args.asset]
    if not fresh:
        raise SystemExit(f"no pairs for {args.asset} in {args.patch}")
    kept = [r for r in main_metrics["pairs"] if r["asset"] != args.asset]
    if len(kept) + len(fresh) != len(main_metrics["pairs"]):
        raise SystemExit(
            f"pair count would change: {len(kept)}+{len(fresh)} != {len(main_metrics['pairs'])}"
        )
    rows = kept + fresh

    summary = harness.aggregate(rows, args.bootstrap_samples)
    summary["rgb"] = harness.aggregate_rgb(rows, args.bootstrap_samples)
    for key in ("expected_pairs", "expected_renders", "expected_render_modes"):
        if key in main_metrics["summary"]:
            summary[key] = main_metrics["summary"][key]
    summary["complete"] = len(rows) == summary.get("expected_pairs", len(rows))
    summary["merged_from"] = {"asset": args.asset, "patch_run": str(args.patch)}

    # Per-pair artefacts (comparison montages, Stokes EXRs) must follow the rows.
    src_asset = args.patch / args.asset
    dst_asset = args.main / args.asset
    if src_asset.is_dir():
        if dst_asset.exists():
            shutil.rmtree(dst_asset)
        shutil.copytree(src_asset, dst_asset)

    (args.main / "metrics.json").write_text(
        json.dumps({"summary": summary, "pairs": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"merged {len(fresh)} pairs for {args.asset}; total {len(rows)}")
    for group in ("positive", "negative"):
        value = summary["groups"][group]["object"]["delta_dolp_mean"]["mean"]
        print(f"  {group:9s} delta_dolp_mean = {value:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
