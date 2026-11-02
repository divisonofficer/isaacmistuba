#!/usr/bin/env python3
"""Check a HSSD-rendered sample's channel set, addressing files exactly.

The reason this exists as a script rather than an ad-hoc glob: channel suffixes
OVERLAP. `*_rgb0001.exr` also matches `albedo_rgb0001.exr`,
`diffuse_component_rgb0001.exr` and `diffuse_transport_rgb0001.exr` -- four files
for one intended channel -- and an unsorted `glob(...)[0]` then returns whichever
the filesystem hands back first. That is silent: every number comes out
plausible, and comparing two channels read that way "found" an rgb/albedo
cross-wire in 14 of 53 frames that does not exist. Addressing a channel means
building its filename from the frame directory's own name, never matching a
suffix pattern.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import imageio.v3 as iio
import numpy as np

#: What a feed-forward inverse-rendering loader needs from a baseline frame.
REQUIRED = ("rgb", "nir_passive", "nir_active", "roughness", "metallic",
            "normal", "depth", "pbr_invalid_mask")
#: Present on baseline frames only; a lighting-variant frame carries no PBR GT.
BASELINE_ONLY = ("albedo_rgb", "material_id")


def channel(directory: Path, name: str):
    path = directory / f"{directory.name}_{name}0001.exr"
    if not path.is_file():
        return None
    return np.nan_to_num(np.asarray(iio.imread(path), dtype=np.float32))


def check_frame(directory: Path) -> dict:
    present = {name: channel(directory, name) for name in REQUIRED + BASELINE_ONLY}
    missing = [n for n in REQUIRED if present[n] is None]
    row = {"frame": directory.name, "missing": missing}
    rgb, albedo = present["rgb"], present["albedo_rgb"]
    if rgb is not None:
        row["rgb_mean"] = float(rgb.mean())
    mask = present["pbr_invalid_mask"]
    if mask is not None:
        row["invalid_fraction"] = float((mask[..., 0] > 0.5).mean())
    # Two different signals do not agree to the last bit by accident, so byte
    # equality between the render and its albedo would mean one of them was
    # written from the other. It does not happen -- this is a guard, not a fix.
    if rgb is not None and albedo is not None and np.array_equal(rgb, albedo):
        row["fault"] = "rgb_is_albedo"
    elif missing:
        row["fault"] = "missing_channels"
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="a --out directory from the sample renderer")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    frames = sorted(p for p in args.root.glob("shard_*/*") if p.is_dir())
    if not frames:
        print(f"no frame directories under {args.root}", file=sys.stderr)
        return 2
    rows = [check_frame(p) for p in frames]
    faults = [r for r in rows if "fault" in r]
    means = [r["rgb_mean"] for r in rows if "rgb_mean" in r]
    invalid = [r["invalid_fraction"] for r in rows if "invalid_fraction" in r]
    report = {
        "root": str(args.root), "frames": len(rows), "faults": len(faults),
        "rgb_mean": {"min": min(means), "median": float(np.median(means)), "max": max(means)} if means else None,
        "invalid_fraction": {"min": min(invalid), "mean": float(np.mean(invalid)),
                             "max": max(invalid)} if invalid else None,
        "faulty_frames": [r for r in faults][:10],
    }
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"{report['frames']} frames, {report['faults']} faults")
        if report["rgb_mean"]:
            m = report["rgb_mean"]
            print(f"  rgb mean  {m['min']:.4f} .. {m['median']:.4f} (median) .. {m['max']:.4f}")
        if report["invalid_fraction"]:
            v = report["invalid_fraction"]
            print(f"  pbr invalid  {100*v['min']:.2f}% .. {100*v['mean']:.2f}% (mean) .. {100*v['max']:.2f}%")
        for r in faults[:10]:
            print(f"  FAULT {r['frame']}: {r['fault']} {r.get('missing') or ''}")
    return 1 if faults else 0


if __name__ == "__main__":
    raise SystemExit(main())
