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

It also flags, and deliberately does not repair, pixels whose per-material AOVs
are a blend of more than one surface. Two things produce them: transmission,
where a pixel seen through glass accumulates the surface behind it, and partial
coverage, where a pixel straddling a silhouette edge carries a fraction of each
side. Both make that pixel's roughness, metallic and base colour a mixture that
is neither surface's ground truth, and averaging is not a repair -- the mean of
a shade's roughness and the vase behind it describes nothing. They are written
out as `aov_valid` so a consumer can exclude them.

The renderer emits `layer_count` for exactly this. It is not an integer count:
the values run continuously (1.506, 2.463) because coverage is fractional, so
it is thresholded rather than rounded. An earlier version of this file read the
count off `mr_explicit_mask`, which the renderer now clamps to 1.0 -- so the
detector found a maximum of 1.0 in every frame and reported every frame clean.
It was not measuring less than it should have; it was measuring a constant, and
a check that cannot fail reads exactly like a corpus that has no defect.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import struct
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
    # Exceeds 1.0 wherever a pixel blends surfaces, which is its entire purpose.
    # Left out of this set it fell through to the bounded default and was
    # clipped to 1.0 -- the packer destroying the one channel that records
    # which pixels it was warning about.
    "layer_count",
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
#: Preferred blend indicator, and the legacy channel to fall back on for
#: frames rendered before the renderer emitted one. The fallback is only
#: meaningful while that mask was still unclamped; a clamped one yields no
#: detections, which `blend_source` records so the difference is visible in the
#: frame record rather than inferred from a suspiciously clean result.
LAYER_COUNT_CHANNEL = "layer_count"
LEGACY_LAYER_COUNT_CHANNEL = "mr_explicit_mask"
#: A clean first hit reads 1.0; the tolerance is for float round-trip only.
LAYER_EPSILON = 1e-3


def exr_pixel_types(path: Path) -> set[str]:
    """Pixel type of every channel in an EXR, read from its header.

    Needed because "is this already half?" cannot be answered from the decoded
    array -- OpenCV hands back float32 whatever the file held. Searching the
    header bytes for b"half" or b"float" does not work either: EXR names its
    attribute *types* in the same header, so every file contains b"float" from
    `screenWindowWidth` alone and that probe reports FLOAT for everything,
    including files it just wrote as half. The channel list is the only place
    the answer actually lives, as an int32 per channel.
    """
    with path.open("rb") as handle:
        head = handle.read(65536)
    if head[:4] != b"\x76\x2f\x31\x01":
        return set()
    types: set[str] = set()
    names = {0: "UINT", 1: "HALF", 2: "FLOAT"}
    offset = 8
    try:
        while True:
            end = head.index(b"\0", offset)
            attribute = head[offset:end].decode(); offset = end + 1
            if not attribute:
                break
            offset = head.index(b"\0", offset) + 1          # attribute type
            size = struct.unpack("<i", head[offset:offset + 4])[0]; offset += 4
            value = head[offset:offset + size]; offset += size
            if attribute != "channels":
                continue
            cursor = 0
            while cursor < len(value) - 1:
                end = value.index(b"\0", cursor)
                if end == cursor:
                    break
                cursor = end + 1
                types.add(names[struct.unpack("<i", value[cursor:cursor + 4])[0]])
                cursor += 16                                  # type + flags + sampling
    except (ValueError, KeyError, struct.error):
        return set()
    return types


def _is_grey(image: np.ndarray) -> bool:
    return (image.ndim == 3 and image.shape[2] == 3
            and np.array_equal(image[..., 0], image[..., 1])
            and np.array_equal(image[..., 1], image[..., 2]))


def _encode(channel: str, image: np.ndarray, out_dir: Path,
            source: Path | None = None) -> dict[str, Any]:
    """Write one channel in the format its content calls for.

    An HDR channel already stored as half, with no duplicate components to
    drop, is copied rather than re-encoded. The renderer's compact format now
    writes half EXR itself, so re-encoding those channels changed nothing about
    their precision and cost about 80 KB a frame in compression noise --
    measured, the pack step made a frame 0.07% *larger*. What remains worth
    doing is the component collapse on depth, material_id and layer_count.
    """
    collapsed = _is_grey(image)
    if collapsed:
        image = image[..., :1]
    if channel in HDR_CHANNELS:
        target = out_dir / f"{channel}.exr"
        if source is not None and not collapsed and exr_pixel_types(source) == {"HALF"}:
            shutil.copy2(source, target)
            return {"file": target.name, "format": "exr_half", "channels": int(image.shape[2]),
                    "scale": 1.0, "offset": 0.0, "reencoded": False}
        cv2.imwrite(str(target), image, [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_HALF])
        return {"file": target.name, "format": "exr_half", "channels": int(image.shape[2]),
                "scale": 1.0, "offset": 0.0, "reencoded": True}
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
    paths: dict[str, Path] = {}
    for source in sources:
        channel = source.name[len(name) + 1:-len("0001.exr")]
        paths[channel] = source
        image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH)
        if image is None:
            return {"frame": name, "error": f"unreadable {source.name}"}
        images[channel] = image.astype(np.float32)

    record: dict[str, Any] = {"schema": SCHEMA, "frame": name, "channels": {}}
    source_channel = (LAYER_COUNT_CHANNEL if LAYER_COUNT_CHANNEL in images
                      else LEGACY_LAYER_COUNT_CHANNEL)
    layers = images.get(source_channel)
    if layers is not None:
        count = layers[..., 0] if layers.ndim == 3 else layers
        # Not rounded. The values are continuous because pixel coverage is
        # fractional, so 1.506 is a real half-and-half pixel rather than a 2
        # that needs recovering, and rounding it either way asserts something
        # the renderer did not say.
        blended = count > 1.0 + LAYER_EPSILON
        record["aov_surface_blend"] = {
            "blend_source": source_channel,
            "affected_fraction": float(blended.mean()),
            "max_layers": float(count.max()),
            "repaired": False,
            "note": "pixels whose per-material AOVs mix more than one surface, "
                    "through transmission or partial coverage; averaging them "
                    "yields neither surface's ground truth, so they are flagged",
        }
        # Derived, so written directly rather than through `_encode`: their
        # names are not channel names and the format is not negotiable -- the
        # flag must stay a bit, and it is the only one of the two that is new,
        # since the renderer now writes `layer_count` itself.
        cv2.imwrite(str(packed / "aov_valid.png"),
                    ((~blended).astype(np.uint8) * 255))
        record["channels"]["aov_valid"] = {
            "file": "aov_valid.png", "format": "png8", "channels": 1,
            "scale": 1.0, "offset": 0.0,
            "note": f"0 where the per-material AOVs mix surfaces, per {source_channel}"}

    for channel, image in images.items():
        record["channels"][channel] = _encode(channel, image, packed, paths.get(channel))

    (packed / "channels.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    before = sum(s.stat().st_size for s in sources)
    after = sum(f.stat().st_size for f in packed.iterdir())
    if not keep:
        for source in sources:
            source.unlink()
    return {"frame": name, "before": before, "after": after,
            "affected": record.get("aov_surface_blend", {}).get("affected_fraction", 0.0),
            "blend_source": record.get("aov_surface_blend", {}).get("blend_source")}


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
    print(f"[pack] frames with surface-blended AOV pixels: {len(touched)}"
          + (f" (worst {max(r['affected'] for r in touched):.2%})" if touched else ""))
    # Zero detections is the answer a broken detector gives, so say which
    # channel produced it rather than leaving a clean result unattributed.
    sources = collections.Counter(r["blend_source"] for r in ok)
    print(f"[pack] blend detected from: "
          + ", ".join(f"{name or 'no channel'}={n}" for name, n in sources.most_common()))
    for r in failed[:5]:
        print(f"   FAILED {r['frame']}: {r['error']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
