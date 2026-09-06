#!/usr/bin/env python3
"""Repack rendered ABO frames: half-float EXR for HDR, PNG for the rest.

The renderer writes every channel as 32-bit EXR, which is right for radiance
and wasteful for the two thirds of the set that is bounded. Splitting by what
the channel actually is takes a GT-carrying frame from 34.4 MB to about 15 MB,
measured, with no loss that matters:

  * radiance and metric depth keep an EXR, at half precision. Half carries ~3
    decimal digits, which at our 0.5-4 m working range is sub-millimetre on
    depth and far finer than the sampling noise on radiance.
  * everything else is bounded and goes to PNG -- 16-bit where the value is
    continuous, 8-bit where it is a flag.
  * a channel whose three components are identical is written single-channel.
    The NIR base colour is grey under the pseudo-NIR model, and storing it as
    RGB PNG actually *grew* it against the EXR it replaced.

Each frame gets a `channels.json` recording the format, dtype, scale and offset
per channel, so the encoding is reversible without consulting this file.

It also flags, and deliberately does not repair, the AOV layer-summing defect:
per-material AOVs accumulate along the ray path rather than stopping at the
first hit, so a pixel seen through a lamp shade carries the sum of every
surface behind it. `GT_MRExplicitMask` is a per-material constant of 1.0 and so
counts the layers exactly, which is what makes the defect detectable. Dividing
by that count is tempting and wrong: it yields the mean over the layers, and
the mean of a shade's roughness and the vase behind it is neither surface's
ground truth. The affected pixels are written out as `aov_valid` instead, and
the count as `gt_layer_count`, so a consumer can exclude them.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import numpy as np  # noqa: E402

SCHEMA = "robomituba.abo_frame_pack.v1"

#: Unbounded radiance, plus depth in metres. These stay floating point.
HDR_CHANNELS = frozenset({
    "rgb", "nir_active", "nir_passive", "active_minus_passive",
    "diffuse_transport_rgb", "diffuse_transport_nir",
    "diffuse_component_rgb", "diffuse_component_nir",
    "depth", "range",
    # Not bounded [0,1] and its fractional values are real -- a pixel spanning
    # two materials carries their blend, which an integer PNG would destroy.
    "material_id",
})
#: Flags: 0 or 1, so a byte is enough.
FLAG_CHANNELS = frozenset({
    "glass_mask", "mr_explicit_mask", "mr_inferred_mask",
    "mr_training_valid_mask", "pbr_invalid_mask", "valid_mask",
})
#: Signed and bounded to [-1, 1]; stored as (v + 1) / 2.
SIGNED_CHANNELS = frozenset({"normal", "normal_tangent"})
#: The mask that doubles as a layer counter, per the module docstring.
LAYER_COUNT_CHANNEL = "mr_explicit_mask"


def _is_grey(image: np.ndarray) -> bool:
    return (image.ndim == 3 and image.shape[2] == 3
            and np.array_equal(image[..., 0], image[..., 1])
            and np.array_equal(image[..., 1], image[..., 2]))


def _encode(channel: str, image: np.ndarray, out_dir: Path) -> dict[str, Any]:
    """Write one channel in the format its content calls for."""
    if _is_grey(image):
        image = image[..., :1]
    if channel in HDR_CHANNELS:
        target = out_dir / f"{channel}.exr"
        cv2.imwrite(str(target), image, [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF])
        return {"file": target.name, "format": "exr_half", "channels": int(image.shape[2]),
                "scale": 1.0, "offset": 0.0}
    if channel in SIGNED_CHANNELS:
        target = out_dir / f"{channel}.png"
        cv2.imwrite(str(target), (np.clip(image * 0.5 + 0.5, 0, 1) * 65535).astype(np.uint16))
        return {"file": target.name, "format": "png16", "channels": int(image.shape[2]),
                "scale": 2.0, "offset": -1.0}
    if channel in FLAG_CHANNELS:
        target = out_dir / f"{channel}.png"
        cv2.imwrite(str(target), (np.clip(image, 0, 1) * 255).astype(np.uint8))
        return {"file": target.name, "format": "png8", "channels": int(image.shape[2]),
                "scale": 1.0, "offset": 0.0}
    target = out_dir / f"{channel}.png"
    cv2.imwrite(str(target), (np.clip(image, 0, 1) * 65535).astype(np.uint16))
    return {"file": target.name, "format": "png16", "channels": int(image.shape[2]),
            "scale": 1.0, "offset": 0.0}


def pack_frame(args: tuple[str, bool]) -> dict[str, Any]:
    frame_dir, keep = Path(args[0]), args[1]
    name = frame_dir.name
    sources = sorted(frame_dir.glob(f"{name}_*0001.exr"))
    if not sources:
        return {"frame": name, "error": "no source EXR"}
    packed = frame_dir / "packed"
    packed.mkdir(exist_ok=True)

    images: dict[str, np.ndarray] = {}
    for source in sources:
        channel = source.name[len(name) + 1:-len("0001.exr")]
        image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
        if image is None:
            return {"frame": name, "error": f"unreadable {source.name}"}
        images[channel] = image.astype(np.float32)

    record: dict[str, Any] = {"schema": SCHEMA, "frame": name, "channels": {}}
    layers = images.get(LAYER_COUNT_CHANNEL)
    if layers is not None:
        count = layers[..., 0] if layers.ndim == 3 else layers
        # A first hit reads exactly 1. Anything above is a summed pixel, and
        # rounding is safe because the constant being summed is exactly 1.0.
        count = np.rint(count).astype(np.float32)
        contaminated = count > 1.5
        record["aov_layer_summing"] = {
            "affected_fraction": float(contaminated.mean()),
            "max_layers": float(count.max()),
            "repaired": False,
            "note": "per-material AOVs sum along the ray path; dividing by the "
                    "count yields the mean over layers, not the first hit, so "
                    "the pixels are flagged rather than corrected",
        }
        # Written directly rather than through _encode: these are derived, so
        # their names are not channel names and the format is not up for
        # negotiation -- the count must survive as a number, the flag as a bit.
        cv2.imwrite(str(packed / "gt_layer_count.exr"), count[..., None],
                    [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF])
        record["channels"]["gt_layer_count"] = {
            "file": "gt_layer_count.exr", "format": "exr_half", "channels": 1,
            "scale": 1.0, "offset": 0.0,
            "note": "surfaces summed into this pixel's per-material AOVs; 1 is a clean first hit"}
        cv2.imwrite(str(packed / "aov_valid.png"),
                    ((~contaminated).astype(np.uint8) * 255))
        record["channels"]["aov_valid"] = {
            "file": "aov_valid.png", "format": "png8", "channels": 1,
            "scale": 1.0, "offset": 0.0,
            "note": "0 where the per-material AOVs are a sum over layers"}

    for channel, image in images.items():
        record["channels"][channel] = _encode(channel, image, packed)

    (packed / "channels.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    before = sum(s.stat().st_size for s in sources)
    after = sum(f.stat().st_size for f in packed.iterdir())
    if not keep:
        for source in sources:
            source.unlink()
    return {"frame": name, "before": before, "after": after,
            "affected": record.get("aov_layer_summing", {}).get("affected_fraction", 0.0)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="dataset root holding scene dirs")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--keep-source", action="store_true",
                        help="leave the 32-bit EXRs in place instead of deleting them")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    frames = sorted(str(p) for p in args.root.glob("*/render/shard_*/*") if p.is_dir())
    frames = [f for f in frames if not (Path(f) / "packed" / "channels.json").is_file()]
    if args.limit:
        frames = frames[:args.limit]
    if not frames:
        print("[pack] nothing to do")
        return 0
    print(f"[pack] {len(frames)} frames, keep_source={args.keep_source}", flush=True)

    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(pack_frame, [(f, args.keep_source) for f in frames], chunksize=2))

    failed = [r for r in results if "error" in r]
    ok = [r for r in results if "error" not in r]
    before = sum(r["before"] for r in ok)
    after = sum(r["after"] for r in ok)
    touched = [r for r in ok if r["affected"] > 0]
    print(f"[pack] packed={len(ok)} failed={len(failed)}")
    print(f"[pack] {before / 2**30:.2f} GB -> {after / 2**30:.2f} GB "
          f"({100 * after / max(before, 1):.0f}%, saves {100 - 100 * after / max(before, 1):.0f}%)")
    print(f"[pack] frames carrying summed AOV pixels: {len(touched)}"
          + (f" (worst {max(r['affected'] for r in touched):.2%})" if touched else ""))
    for r in failed[:5]:
        print(f"   FAILED {r['frame']}: {r['error']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
