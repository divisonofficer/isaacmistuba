#!/usr/bin/env python3
"""Derive a per-frame structural mask so metallic loss is not spent on walls.

The room shell fills roughly three quarters of a frame and carries essentially
no metal -- measured on a dining room, structural pixels average 0.00077
metallic with 0.78% non-zero, against 0.31 and 50.5% on props. Training the
metallic head over the whole frame therefore spends most of its loss on pixels
that are trivially zero, and the signal it exists to learn sits in the
remaining quarter.

Nothing needs re-rendering. ``material_id`` already indexes the prepared
material contract exactly, and each record names the Blender object it came
from, so the split is recoverable from artifacts every dataset already has.

The mask marks structure. Train on its complement, or weight by it -- that
choice belongs to the training code, not here.
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "modules" / "mitsuba_converter" / "src"))
sys.path.insert(0, str(REPO / "modules" / "robomituba_bridge" / "src"))

from mitsuba_converter.ir_object_anchors import STRUCTURAL_TOKENS  # noqa: E402

SCHEMA = "robomituba.ir_structural_mask.v1"
MASK_VERSION = "structural-mask-v1"


#: Factories whose names contain a structural word but which are objects a
#: metallic head should be trained on: a ceiling lamp has a metal fitting, wall
#: art has a frame, a wall shelf has brackets.  Masking those out would remove
#: exactly the signal the mask exists to protect.  Checked before the tokens,
#: because every one of them matches a token.
OBJECT_DESPITE_NAME = (
    "lamp", "light", "art", "shelf", "clock", "mirror", "curtain", "blind",
    "vent", "radiator", "switch", "socket", "handle", "sign", "picture",
)
#: The shell itself is named by the room, not by a factory.  Infinigen writes it
#: as ``<room>_<i>_<j>.<part>``, which is the only reliable structural marker
#: here -- the factory names are too easily confused with the objects above.
SHELL_PARTS = ("wall", "floor", "ceiling", "exterior", "room")


def is_structural(record: dict) -> bool:
    """Is this material part of the room shell rather than an object in it?

    Name tokens alone are not enough: ``CeilingClassicLampFactory`` and
    ``WallArtFactory`` both match a structural word while being objects. So an
    explicit object list is consulted first, and the remaining decision leans on
    the room-shell naming Infinigen uses for the shell itself.
    """
    name = str(record.get("object_id") or record.get("blender_object") or "").lower()
    if any(token in name for token in OBJECT_DESPITE_NAME):
        return False
    # A shell part looks like "dining-room_0_0.floor" -- a room prefix and a
    # part suffix, with no "Factory" in it.
    if "factory" not in name:
        suffix = name.rsplit(".", 1)[-1]
        if suffix in SHELL_PARTS:
            return True
    text = " ".join(str(record.get(key) or "").lower() for key in
                    ("object_id", "blender_object", "source_material", "semantic_class"))
    return any(token in text for token in STRUCTURAL_TOKENS) and "factory" not in name


def structural_material_ids(contract: dict) -> set[int]:
    ids = set()
    for record in contract.get("materials") or []:
        value = record.get("material_id")
        if value is not None and is_structural(record):
            ids.add(int(value))
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True,
                        help="dataset root holding material_id/ and index.jsonl")
    parser.add_argument("--contract", type=Path, required=True,
                        help="principled_material_contract.json the dataset was rendered from")
    parser.add_argument("--out", type=Path, default=None,
                        help="mask directory (default: <dataset>/structural_mask)")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    root = args.dataset.resolve()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    ids = structural_material_ids(contract)
    if not ids:
        print("[structural-mask] no structural materials in the contract", file=sys.stderr)
        return 1
    out = (args.out or root / "structural_mask").resolve()
    out.mkdir(parents=True, exist_ok=True)
    lookup = np.array(sorted(ids))

    coverage, metal_struct, metal_prop, written, missing = [], [], [], 0, 0
    frames = sorted((root / "material_id").glob("*.png"))
    for path in frames[:args.limit] if args.limit else frames:
        material = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if material is None:
            missing += 1
            continue
        mask = np.isin(material, lookup)
        cv2.imwrite(str(out / path.name), (mask.astype(np.uint8) * 255))
        written += 1
        coverage.append(float(mask.mean()))
        metallic = cv2.imread(str(root / "metallic" / path.name), cv2.IMREAD_UNCHANGED)
        if metallic is not None:
            metallic = metallic.astype(np.float32) / 65535.0
            metal_struct.append(metallic[mask])
            metal_prop.append(metallic[~mask])

    report = {"schema": SCHEMA, "mask_version": MASK_VERSION, "dataset": root.name,
              "structural_material_ids": sorted(ids), "frames": written,
              "unreadable_frames": missing,
              "structural_coverage_mean": round(float(np.mean(coverage)), 4) if coverage else None}
    if metal_struct:
        s, p = np.concatenate(metal_struct), np.concatenate(metal_prop)
        report["metallic"] = {
            "structural_mean": round(float(s.mean()), 6),
            "structural_nonzero_fraction": round(float((s > 0.02).mean()), 6),
            "prop_mean": round(float(p.mean()), 6),
            "prop_nonzero_fraction": round(float((p > 0.02).mean()), 6),
        }
    target = args.report or (out.parent / "structural_mask.json")
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[structural-mask] {written} frames, {len(ids)} structural materials")
    if coverage:
        print(f"[structural-mask]   structure covers {np.mean(coverage)*100:.1f}% of pixels")
    if "metallic" in report:
        m = report["metallic"]
        print(f"[structural-mask]   metallic on structure {m['structural_mean']:.5f} "
              f"({m['structural_nonzero_fraction']*100:.2f}% non-zero)  "
              f"vs props {m['prop_mean']:.5f} ({m['prop_nonzero_fraction']*100:.1f}%)")
    print(f"[structural-mask]   masks -> {out}")
    print(f"[structural-mask]   report -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
